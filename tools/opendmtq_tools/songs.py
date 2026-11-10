"""Songs: the song list the server offers, the client's tables it hands out, and songs added or hidden on the
admin pages, without touching the imported content.

The imported content (data/content, read only here; importer.py fills it from the operator's own files):

    songs.json            the imported songs' list
    web/                  their files, as the game asks for them: DMQ/Songs, DMQ/Patterns, viewImg, static and
                          the client's patch folder (patch/phone_new/<version>/android: tables, manifest, images)

Everything else lives under the custom folder (data/custom):

    songs/<song_id>/      one added song: song.json plus its files, as uploaded
    hidden.json           song ids hidden from the song list
    songList.json         the list the server reads (imported songs + added songs + hidden flags)
    catalog.json          facts of the client's tables some replies need (game server, src/content.php)
    web/                  overlay the server prefers over the content, path for path: DMQ/Songs, DMQ/Patterns,
                          viewImg/eye, the client's patch tables and the song-list jacket bundles (jacket_atlas.py)

The game learns about songs twice: the server's song list (what it offers) and the client's patch tables
(song_song, song_songPattern, song_desc per language, and the song's item and product in product_item,
product_product and category_categoryproduct), which the client downloads when the patch manifest
(patch_new.csv.lz4) lists a different checksum. rebuild() regenerates both.

What phones are told of is what the server has. The client data (the client's tables, the images of its screens and
its fonts) comes from the operator's files; the songs are imported apart from it. Without imported songs the tables
lose every song's row, item and product (the chart table keeps its rows: the client refuses an empty one); the
songs' previews and tiles stay with the patch folder they came in. The game then starts with an empty song list, and
offers the songs added on the admin pages alone.
"""

import csv
import functools
import glob
import hashlib
import io
import json
import os
import re
import shutil
import threading
import zipfile
import zlib

import lz4.block

from . import filelock, jacket_atlas, song_files, strings

# The imported content (read only) and the writable custom folder (container paths).
CONTENT = os.environ.get("OPENDMTQ_CONTENT", "/srv/content")
CUSTOM = os.environ.get("OPENDMTQ_CUSTOM", "/custom")
# The patch folder version phones download from when the content has none of its own (the server says the same).
DEFAULT_PATCH_ID = "1.003.005"
# The songs whose 4 LINE charts cost MAX POINT to open (game.getPatternUsePointData): the official server named
# these 23 of the 50 songs the chart table gives a cost; the costs themselves come from the table.
POINT_SONGS = {1, 5, 17, 26, 27, 31, 34, 36, 49, 52, 54, 63, 71, 72, 73, 77, 100, 107, 114, 133, 142, 145, 146}
# Every player owns every item of the client's product_item table but songs (S) and packages (P), and but these:
# the partners a coupon gave and the note items, which the official server never handed out.
NOT_OWNED = {39001, 39002, 39003, 39004, 39101, 90001, 90002, 90003, 90004, 90005, 90006, 90007, 90008, 90009,
             91001, 99101}
# A song's own files in the client's patch folder, as the manifest names them: its preview and its tiles in the song list
# (atlases of several songs each). They come with the patch folder, every song's; files given without some of them
# leave those out, and they go from the manifest.
SONG_FILE = re.compile(r"preview/.*|dlc/d3?_e\d+\.unity3d")
# The game's own files the game starts without: the fonts it uses only in Chinese.
OPTIONAL_GAME_FILES = ("Fonts/",)
# The product the shop's unlock screen shows (shop.getProductForUnlock).
UNLOCK_PRODUCT = "80002"
# First ids handed to added songs and charts, far above the shipped ones (191 and 1320).
FIRST_SONG_ID = 1001
FIRST_PATTERN_ID = 20001
# The shipped jacket atlas that added songs' bundles are made from: any would do, all have one layout.
TILE_TEMPLATE = "dlc/d3_e33.unity3d"
# Product ids of added songs: above every shipped one (the highest is 1080020).
PRODUCT_ID_BASE = 2000000
# The shop categories every shipped song's product is listed in (the music shop, old and new): the
# game finds a song's product through them.
SONG_CATEGORIES = ("3", "103")


def _product_row(header, song_id):
    """An added song's row in product_product, in the form the shipped free songs have (the product
    and platform ids equal, one game point, status N). The game looks up every listed song's product
    there; without one its song list fails (NullReferenceException in PlaySongSlotView.ApplyDiscInfo)
    and the game closes at the lobby."""
    pid = PRODUCT_ID_BASE + song_id
    values = {"product_id": pid, "item_id": song_id, "platform_product_id": pid, "store_product_id": "",
              "product_type": "I", "cost_game_point": 1, "cost_game_cash": 0, "status": "N",
              "sale_start_date": "", "sale_end_date": "", "update": 0}
    return [str(values.get(h.lstrip("\ufeff"), "")) for h in header]


def _category_rows(header, song_id):
    """An added song's product in the music shop categories (category_categoryproduct), as the
    shipped songs' products are: the game looks a song's product up through them."""
    pid = PRODUCT_ID_BASE + song_id
    return [[str({"category_id": cat, "product_id": pid, "display_order": 0, "update": 0}.get(h.lstrip("\ufeff"), ""))
             for h in header] for cat in SONG_CATEGORIES]
# Chart types the game knows: lines and the signature (0 special, 1 normal, 2 hard, 3 maximum).
LINES = {3, 4, 5}
SIGNATURES = {0, 1, 2, 3}
# Song "name": the key for jacket and preview file names.
NAME_RE = re.compile(r"[a-z0-9_]{1,40}")
# Text fields copied from song.json into the tables.
TEXT_FIELDS = ["full_name", "genre", "artist_name", "composed_by", "singer", "feat_by", "arranged_by",
               "visualized_by"]
# Size limits for uploads: an archive with a music video is tens of MB.
MAX_PACKAGE = 300 * 1024 * 1024
MAX_FILE = 200 * 1024 * 1024
# Everything unpacked together, so a small archive cannot fill the disk.
MAX_UNPACKED = 600 * 1024 * 1024
# Jackets are 1024x768 in the game; refuse absurd images before decoding them.
MAX_JACKET_PIXELS = 4096 * 4096

# One change at a time: the admin service has several threads, and ids, staging folders and the
# overlay swap must not interleave.
_lock = threading.RLock()


_depth = threading.local()


def _serialized(fn):
    """One change at a time, across threads (the lock) and processes (a lock file in CUSTOM: a start's or an import's
    `python -m opendmtq_tools.songs` may rebuild while the admin service adds or hides a song). Nested calls
    (add_package -> rebuild) take the file lock only once: a second flock on a new descriptor would wait for the first
    forever."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _lock:
            if getattr(_depth, "n", 0):
                _depth.n += 1
                try:
                    return fn(*args, **kwargs)
                finally:
                    _depth.n -= 1
            os.makedirs(CUSTOM, exist_ok=True)
            with open(os.path.join(CUSTOM, ".lock"), "w") as lf:
                filelock.lock(lf)
                _depth.n = 1
                try:
                    return fn(*args, **kwargs)
                finally:
                    _depth.n = 0
                    filelock.unlock(lf)
    return wrapper


class SongError(Exception):
    """A problem the admin page shows to the user, in the user's language: a key of strings.py and its
    values. As text (the command line, the tests) it is the English."""

    def __init__(self, key, **values):
        super().__init__(strings.text("en", key, **values))
        self.key, self.values = key, values


# ------------------------------------------------------------------------------ lz4 container

def _varint(data, i):
    """Decode one LEB128 varint at i; returns (value, next index)."""
    value = shift = 0
    while True:
        b = data[i]
        i += 1
        value |= (b & 0x7F) << shift
        shift += 7
        if b < 0x80:
            return value, i


def _put_varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def lz4_decode(data):
    """The game's .lz4 files: type byte 3, varint raw size, varint packed size, one LZ4 block; or, for
    what is packed already (image bundles), type byte 2, varint raw size, the bytes as they are."""
    if data and data[0] == 2:
        raw, i = _varint(data, 1)
        return data[i:i + raw]
    if not data or data[0] != 3:
        raise SongError("song.lz4")
    raw, i = _varint(data, 1)
    packed, i = _varint(data, i)
    return lz4.block.decompress(data[i:i + packed], uncompressed_size=raw)


def lz4_encode(raw):
    packed = lz4.block.compress(raw, store_size=False)
    return bytes([3]) + _put_varint(len(raw)) + _put_varint(len(packed)) + packed


def stored_encode(raw):
    """The container for bytes that LZ4 cannot shrink: the form the shipped image bundles have."""
    return bytes([2]) + _put_varint(len(raw)) + raw


# ------------------------------------------------------------------------------ shipped data

def _version_key(version):
    """A patch version as numbers part by part, so that 1.003.005 comes after 1.000.030."""
    return [int(p) if p.isdigit() else 0 for p in version.split(".")]


def patch_version():
    """Patch id the server announces (the client's patch folder name), e.g. 1.003.005: the newest folder with a
    manifest in the overlay or the content, else the default. The game server picks it the same way."""
    found = []
    for root in (os.path.join(CUSTOM, "web"), os.path.join(CONTENT, "web")):
        for manifest in glob.glob(os.path.join(root, "patch", "phone_new", "*", "android", "patch_new.csv.lz4")):
            found.append(os.path.basename(os.path.dirname(os.path.dirname(manifest))))
    return max(found, key=_version_key) if found else DEFAULT_PATCH_ID


def patch_dir(root):
    """The client patch folder under a web root (the content's, the overlay's, or one being built)."""
    return os.path.join(root, "patch", "phone_new", patch_version(), "android")


def content_web():
    """The imported files, as the game asks for them."""
    return os.path.join(CONTENT, "web")


def has_game_data():
    """True once the client data is imported (the client's patch folder with its manifest): the game cannot start
    without it, songs or no songs."""
    return os.path.isfile(os.path.join(patch_dir(content_web()), "patch_new.csv.lz4"))


def base_song_list():
    """The imported songs, as their list has them; none without imported songs."""
    try:
        with open(os.path.join(CONTENT, "songs.json"), encoding="utf-8-sig") as f:
            songs = json.load(f)
    except (OSError, ValueError):
        return []
    return songs if isinstance(songs, list) else []


def _decode_table(raw):
    """A table's text. The client's tables are UTF-8 (most with a byte-order mark) or, a few of them, the Korean
    code page CP949: the client reads both, and a table rewritten here is written as UTF-8 with the mark, as the
    official server's patches had them."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp949")


def _read_table(path_plain):
    """CSV text of an imported table, from the plain file or its .lz4 twin."""
    if os.path.isfile(path_plain):
        with open(path_plain, "rb") as f:
            return _decode_table(f.read())
    with open(path_plain + ".lz4", "rb") as f:
        return _decode_table(lz4_decode(f.read()))


# ------------------------------------------------------------------------------ custom songs

def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, value):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def added_songs():
    """Added songs' song.json contents, by id order."""
    root = os.path.join(CUSTOM, "songs")
    out = []
    if os.path.isdir(root):
        for d in sorted(os.listdir(root), key=lambda x: int(x) if x.isdigit() else 0):
            meta = _load_json(os.path.join(root, d, "song.json"), None)
            if meta:
                out.append(meta)
    return out


def hidden():
    return set(_load_json(os.path.join(CUSTOM, "hidden.json"), []))


@_serialized
def set_hidden(song_id, hide):
    ids = hidden()
    # Showing one is always fine (it may be an old flag being cleaned up). Hiding: only a song there is.
    if hide and int(song_id) not in {s["song_id"] for s in catalog()}:
        raise SongError("songs.no_such", id=int(song_id))
    before = sorted(ids)
    (ids.add if hide else ids.discard)(int(song_id))
    os.makedirs(CUSTOM, exist_ok=True)
    _write_json(os.path.join(CUSTOM, "hidden.json"), sorted(ids))
    # The list could not be made with it: as it was, so that the page's "it failed" is true.
    try:
        rebuild()
    except Exception:
        _write_json(os.path.join(CUSTOM, "hidden.json"), before)
        raise


def missing_game_files():
    """The game's own files the manifest names and the import did not bring, as of the last rebuild. Without the image
    bundles of its screens among them the game stops at its first start, on "Starting the game", and says nothing."""
    try:
        with open(os.path.join(CUSTOM, "missing-game-files.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def tile_failures():
    """Why songs have no picture on their tile in the game's song list, as of the last rebuild."""
    try:
        with open(os.path.join(CUSTOM, "tile-failures.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def catalog():
    """Every song (shipped and added) with id, title, artist, chart count, hidden and added flags."""
    hide = hidden()
    out = []
    for s in base_song_list():
        out.append({"song_id": s["song_id"], "name": s["name"], "title": (s.get("full_name") or s["name"]).strip(),
                    "artist": s.get("artist_name", ""), "charts": len(s.get("song_patterns", [])),
                    "hidden": s["song_id"] in hide, "added": False})
    for m in added_songs():
        out.append({"song_id": m["song_id"], "name": m["name"], "title": m["full_name"], "artist": m["artist_name"],
                    "charts": len(m["charts"]), "hidden": m["song_id"] in hide, "added": True})
    return out


@_serialized
def add_package(path):
    """Validate an uploaded song package (.zip) and add it; returns the new song's song.json."""
    try:
        return _add_package(path)
    except (zipfile.BadZipFile, zlib.error, EOFError) as e:
        raise SongError("song.damaged", detail=str(e))


def _check_jacket(data):
    """The jacket must decode as a PNG of sane size (the web thumbnail is made from it later)."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = MAX_JACKET_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format != "PNG":
                raise SongError("song.jacket_format")
            if im.width * im.height > MAX_JACKET_PIXELS:
                raise SongError("song.jacket_pixels")
            im.load()
    except SongError:
        raise
    except Exception as e:  # noqa: BLE001 - Pillow raises many kinds for broken files
        raise SongError("song.jacket_read", detail=str(e))


def _add_package(path):
    if os.path.getsize(path) > MAX_PACKAGE:
        raise SongError("song.too_large")
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise SongError("song.not_zip")
    with z:
        names = {i.filename: i for i in z.infolist() if not i.is_dir()}
        # Never trust member names: no absolute paths, no "..", no huge members.
        for n, info in names.items():
            if n.startswith("/") or ".." in n.split("/") or info.file_size > MAX_FILE:
                raise SongError("song.member", name=repr(n))
        if sum(i.file_size for i in names.values()) > MAX_UNPACKED:
            raise SongError("song.unpacked")
        if "song.json" not in names:
            raise SongError("song.no_json")
        try:
            meta = json.loads(z.read("song.json").decode("utf-8-sig"))
        except ValueError as e:
            raise SongError("song.bad_json", detail=str(e))

        name = str(meta.get("name", ""))
        if not NAME_RE.fullmatch(name):
            raise SongError("song.bad_name")
        existing = {s["name"] for s in base_song_list()} | {m["name"] for m in added_songs()}
        if name in existing:
            raise SongError("song.exists", name=repr(name))
        if not str(meta.get("full_name", "")).strip():
            raise SongError("song.no_title")
        for required in ("song.fpk", "jacket.png"):
            if required not in names:
                raise SongError("song.missing", name=required)
        if names["jacket.png"].file_size > 20 * 1024 * 1024:
            raise SongError("song.jacket_size")
        _check_jacket(z.read("jacket.png"))
        charts = meta.get("charts") or []
        if not charts:
            raise SongError("song.no_charts")
        seen, seen_files = set(), set()
        for number, c in enumerate(charts, 1):
            line, sig, diff, f = c.get("line"), c.get("signature"), c.get("difficulty"), c.get("file")
            if line not in LINES or sig not in SIGNATURES or not isinstance(diff, int) or not 1 <= diff <= 15:
                raise SongError("song.bad_chart", chart=number)
            if (line, sig) in seen:
                raise SongError("song.two_charts", line=line, signature=sig)
            seen.add((line, sig))
            if f not in names or names[f].file_size == 0:
                raise SongError("song.no_chart_file", name=repr(f))
            if f in seen_files:
                raise SongError("song.chart_twice", name=repr(f))
            seen_files.add(f)
        # The files themselves, before anything is written: a pack or a chart the game could not load would break the
        # song for every phone, and the game says nothing of why (song_files.py has what each check looks at).
        problem = song_files.fpk_problem(z.read("song.fpk"))
        if problem:
            raise SongError(problem[0], **problem[1])
        for f in sorted(seen_files):
            problem = song_files.chart_problem(z.read(f))
            if problem:
                raise SongError(problem[0], name=repr(f), **problem[1])
        if "song.webm" in names:
            # Its first bytes say what it is; the video itself may be hundreds of MB.
            with z.open("song.webm") as video:
                problem = song_files.video_problem(video.read(16))
            if problem:
                raise SongError(problem[0], **problem[1])
        if "preview.opus" in names:
            # Its first Ogg page names the codec.
            with z.open("preview.opus") as preview:
                problem = song_files.preview_problem(preview.read(256))
            if problem:
                raise SongError(problem[0], **problem[1])

        # Ids above everything ever handed out, removed songs included: a reused id would attach the
        # removed song's scores, and phones' cached files, to the new one.
        used = _load_json(os.path.join(CUSTOM, "ids.json"), {})
        song_id = max([FIRST_SONG_ID - 1, used.get("song", 0)] + [m["song_id"] for m in added_songs()]) + 1
        next_pid = max([FIRST_PATTERN_ID - 1, used.get("pattern", 0)]
                       + [c["pattern_id"] for m in added_songs() for c in m["charts"]]) + 1
        record = {"song_id": song_id, "name": name, "has_video": "song.webm" in names,
                  "has_preview": "preview.opus" in names, "charts": []}
        for k in TEXT_FIELDS:
            record[k] = str(meta.get(k, "")).replace("\n", " ").strip()

        # Stage into a temporary folder, then move into place.
        dest = os.path.join(CUSTOM, "songs", str(song_id))
        tmp = dest + ".new"
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            os.makedirs(os.path.join(tmp, "patterns"))
            for member, target in (("song.fpk", "song.fpk"), ("song.webm", "song.webm"),
                                   ("jacket.png", "jacket.png"), ("preview.opus", "preview.opus")):
                if member in names:
                    with z.open(member) as src, open(os.path.join(tmp, target), "wb") as out:
                        shutil.copyfileobj(src, out)
            for c in charts:
                pid = next_pid
                next_pid += 1
                with z.open(c["file"]) as src, open(os.path.join(tmp, "patterns", str(pid)), "wb") as out:
                    shutil.copyfileobj(src, out)
                record["charts"].append({"pattern_id": pid, "line": c["line"], "signature": c["signature"],
                                         "difficulty": c["difficulty"]})
            _write_json(os.path.join(tmp, "song.json"), record)
            os.replace(tmp, dest)
            _write_json(os.path.join(CUSTOM, "ids.json"), {"song": song_id, "pattern": next_pid - 1})
        finally:
            # A failed or partial unpack leaves nothing behind.
            shutil.rmtree(tmp, ignore_errors=True)
    rebuild()
    return record


@_serialized
def remove_song(song_id):
    """Remove an added song (shipped songs can only be hidden)."""
    path = os.path.join(CUSTOM, "songs", str(int(song_id)))
    if not os.path.isdir(path):
        raise SongError("song.not_added")
    meta = _load_json(os.path.join(path, "song.json"), {})
    shutil.rmtree(path)
    # Its thumbnail would otherwise outlive it (a later song could reuse the name).
    thumb = os.path.join(CUSTOM, "thumbs", meta.get("name", "") + ".jpg")
    if meta.get("name") and os.path.exists(thumb):
        os.remove(thumb)
    rebuild()


# What a backup holds of the custom folder: the added songs, the hidden flags and the ids handed out so far. The rest of
# the folder is made from these by rebuild().
BACKED_UP = ("songs", "hidden.json", "ids.json")


@_serialized
def put_back(folder):
    """A backup's added songs, hidden flags and ids (folder: its custom/, unpacked) in place of these, and the song list
    and overlay made anew for them, under one lock: no add, hide or removal on the admin pages, and no other rebuild,
    comes between the copy and the rebuild, to read songs half copied or to have its change undone by the copy.

    A copy that fails raises. Returns None, or why the song list could not be made anew: the songs are back all the
    same, and a server without client data has nothing to merge them with yet (its next start makes the list)."""
    for item in BACKED_UP:
        src, dst = os.path.join(folder, item), os.path.join(CUSTOM, item)
        # Today's goes first, whether the backup has one or not: a backup without hidden flags shows every song.
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        elif os.path.exists(dst):
            os.remove(dst)
        # Then the backup's, a folder or a file, when it has one.
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        elif os.path.exists(src):
            shutil.copyfile(src, dst)
    try:
        # Nested in this call's lock: it takes no second one.
        rebuild()
    except (SongError, OSError, ValueError) as e:
        # Said to the caller, which notes it: the restore itself went through.
        return str(e)
    return None


# ------------------------------------------------------------------------------ rebuild

def _md5(b):
    return hashlib.md5(b).hexdigest()


def _csv_text(header, rows, eol="\r\n", final_eol=False):
    out = io.StringIO()
    # Same line endings as the shipped table, so unchanged rows stay byte-identical.
    w = csv.writer(out, lineterminator=eol)
    w.writerow(header)
    w.writerows(rows)
    text = out.getvalue()
    # The shipped tables end without a final line break. A table with no rows never has one: the client reads the
    # empty line after the header as a row and fails its whole download ("Download failed" at the first start).
    if not final_eol or not rows:
        text = text[: -len(eol)]
    # They also start with a byte-order mark; keep the same encoding.
    return ("\ufeff" + text).encode("utf-8")


def _table_rows(text):
    # The byte-order mark is written back by _csv_text; never keep it in the first header name.
    r = list(csv.reader(io.StringIO(text.lstrip("\ufeff"), newline="")))
    return r[0], [row for row in r[1:] if row]


def _eol(text):
    return "\r\n" if "\r\n" in text else "\n"


def _place(src, dest):
    """An added song's file into the overlay being built: a hard link where the disk allows one (no second copy of
    hundreds of MB at every rebuild; the overlay never writes into its files), else a copy. Only rebuild() calls it,
    under its lock."""
    try:
        os.link(src, dest)
    except OSError:
        shutil.copyfile(src, dest)


@_serialized
def rebuild():
    """Regenerate songList.json, catalog.json and the overlay from the imported content plus the added songs and
    the hidden flags. One at a time, across threads and processes (_serialized): two at once would build the overlay in
    the same web.new folder and swap each other's half out."""
    os.makedirs(CUSTOM, exist_ok=True)
    adds = added_songs()
    hide = hidden()

    # 1. The server's song list.
    songs = base_song_list()
    for s in songs:
        s["hidden_yn"] = "Y" if s["song_id"] in hide else s.get("hidden_yn", "N")
    for m in adds:
        songs.append({"song_id": m["song_id"], "name": m["name"], "full_name": m["full_name"],
                      "genre": m["genre"], "artist_name": m["artist_name"], "composed_by": m["composed_by"],
                      "singer": m["singer"], "feat_by": m["feat_by"], "arranged_by": m["arranged_by"],
                      "visualized_by": m["visualized_by"], "original_bga_yn": "Y" if m["has_video"] else "N",
                      "loop_bga_yn": "N", "cost_game_point": 0, "cost_game_cash": 0, "flag": 0, "status": "",
                      "free_yn": "Y", "hidden_yn": "Y" if m["song_id"] in hide else "N",
                      "song_patterns": [{"pattern_id": c["pattern_id"], "line": c["line"],
                                         "difficulty": c["difficulty"], "signature": c["signature"]}
                                        for c in m["charts"]]})

    # 2. The overlay, built aside and swapped in whole.
    web = os.path.join(CUSTOM, "web")
    new = web + ".new"
    shutil.rmtree(new, ignore_errors=True)
    os.makedirs(new)
    changed = {}
    # Sprite name by song id, for the added songs whose tile bundle could be made.
    tiles = {}
    tile_failures = []
    # The client's tables, image bundles and fonts: the client data imported from the operator's files (the content's
    # patch folder). Phones are told only of what the server has: the songs that came with the import and the added
    # ones; the other songs' rows, previews and tiles leave the tables and the manifest. Without client data the game
    # cannot start at all (it needs the images of its screens): there is nothing to rebuild then.
    content_patch = patch_dir(content_web())
    imported = {s["song_id"] for s in base_song_list()}

    def source(rel):
        """A table's text as the content has it (rel: "table/us/song_song.csv")."""
        return _read_table(os.path.join(content_patch, rel))

    def has(rel):
        return os.path.exists(os.path.join(content_patch, rel)) or os.path.exists(os.path.join(content_patch, rel + ".lz4"))

    manifest_path = os.path.join(content_patch, "patch_new.csv.lz4")
    locales, manifest_text, missing = [], "", set()
    if os.path.isfile(manifest_path):
        table_root = os.path.join(content_patch, "table")
        locales = sorted(loc for loc in os.listdir(table_root)
                         if os.path.exists(os.path.join(table_root, loc, "song_song.csv.lz4"))) if os.path.isdir(table_root) else []
        with open(manifest_path, "rb") as f:
            manifest_text = lz4_decode(f.read()).decode("utf-8-sig")
        # Files the manifest names that the content does not have: those of songs not imported, which is as it should
        # be, and the game's own when the files given lacked them, which is not.
        missing = {ln.split(",", 1)[0] for ln in manifest_text.splitlines()[1:]
                   if ln and not os.path.exists(os.path.join(content_patch, ln.split(",", 1)[0] + ".lz4"))}
    game_missing = sorted(n for n in missing if not SONG_FILE.fullmatch(n) and not n.startswith(OPTIONAL_GAME_FILES))
    # Whether the tables list songs the server has not got: then their rows go, with their items and products.
    shipped = set()
    if locales:
        header, rows = _table_rows(source(f"table/{locales[0]}/song_song.csv"))
        col = {h: i for i, h in enumerate(header)}
        shipped = {int(r[col["song_id"]]) for r in rows if r[col["song_id"]].isdigit()}
    filtering = bool(shipped - imported)
    if locales and (adds or hide or filtering or missing):
        for m in adds:
            src = os.path.join(CUSTOM, "songs", str(m["song_id"]))
            sid = str(m["song_id"])
            os.makedirs(os.path.join(new, "DMQ", "Songs", sid), exist_ok=True)
            _place(os.path.join(src, "song.fpk"), os.path.join(new, "DMQ", "Songs", sid, sid + ".fpk"))
            if m["has_video"]:
                _place(os.path.join(src, "song.webm"), os.path.join(new, "DMQ", "Songs", sid, sid + ".webm"))
            os.makedirs(os.path.join(new, "DMQ", "Patterns"), exist_ok=True)
            for c in m["charts"]:
                pid = str(c["pattern_id"])
                for suffix in ("", "_EARPHONE"):
                    _place(os.path.join(src, "patterns", pid), os.path.join(new, "DMQ", "Patterns", pid + suffix))
            os.makedirs(os.path.join(new, "viewImg", "eye"), exist_ok=True)
            _place(os.path.join(src, "jacket.png"), os.path.join(new, "viewImg", "eye", m["name"] + ".png"))
            if m["has_preview"]:
                with open(os.path.join(src, "preview.opus"), "rb") as f:
                    raw = f.read()
                changed[f"preview/{m['name']}.p.opus"] = (raw, False)
            # The jacket on its tile in the song list: the game reads those from image bundles.
            try:
                with open(os.path.join(src, "jacket.png"), "rb") as f:
                    bundle = jacket_atlas.build(_tile_template(), f.read(), m["song_id"], m["name"])
            except (OSError, SongError, jacket_atlas.AtlasError) as e:
                # A song without a tile image still plays, so this must not stop the rebuild.
                tile_failures.append(f"{m['name']}: {e}")
            else:
                changed[jacket_atlas.bundle_path(m["song_id"])] = (bundle, False)
                tiles[m["song_id"]] = jacket_atlas.sprite_name(m["song_id"], m["name"])

        # Client tables for every language folder that has them.
        for loc in locales:
            # Songs taken out of the tables, and their items and products with them: the game looks a listed song's
            # product up, and a product whose song is gone would point at nothing.
            gone_items, gone_products = set(), set()
            text = source(f"table/{loc}/song_song.csv")
            header, rows = _table_rows(text)
            col = {h: i for i, h in enumerate(header)}
            stamp = rows[-1][col["mod_date"]] if rows and "mod_date" in col else "0"
            # Shipped track ids are their own numbering (up to 490); continue after the highest.
            track_base = max([int(r[col["track_id"]]) for r in rows if "track_id" in col and r[col["track_id"]].isdigit()] or [0])
            rows = [r for r in rows if r[col["song_id"]].isdigit() and int(r[col["song_id"]]) in imported]
            for row in rows:
                if int(row[col["song_id"]]) in hide:
                    row[col["hidden_yn"]] = "Y"
            for m in adds:
                values = {"song_id": m["song_id"], "item_id": m["song_id"], "name": m["name"],
                          "full_name": m["full_name"], "genre": m["genre"], "artist_name": m["artist_name"],
                          "original_bga_yn": "Y" if m["has_video"] else "N", "loop_bga_yn": "N",
                          "composed_by": m["composed_by"], "singer": m["singer"], "feat_by": m["feat_by"],
                          "arranged_by": m["arranged_by"], "visualized_by": m["visualized_by"],
                          "cost_game_point": 0, "cost_game_cash": 0, "flag": 0, "status": "", "free_yn": "Y",
                          "hidden_yn": "Y" if m["song_id"] in hide else "N", "open_yn": "Y",
                          "track_id": track_base + m["song_id"] - FIRST_SONG_ID + 1, "mod_date": stamp, "update": 0}
                rows.append([str(values.get(h, "")) for h in header])
            changed[f"table/{loc}/song_song.csv"] = (_csv_text(header, rows, _eol(text), text.endswith("\n")), True)

            # The charts keep every row: the client refuses an empty chart table (its whole first download fails), and
            # a chart whose song is not listed is never offered.
            if adds:
                text = source(f"table/{loc}/song_songPattern.csv")
                header, rows = _table_rows(text)
                for m in adds:
                    for c in m["charts"]:
                        values = {"pattern_id": c["pattern_id"], "song_id": m["song_id"], "signature": c["signature"],
                                  "line": c["line"], "difficulty": c["difficulty"], "point_type": 0, "point_value": 0,
                                  "flg": "Y", "update": 0}
                        rows.append([str(values.get(h, "")) for h in header])
                changed[f"table/{loc}/song_songPattern.csv"] = (_csv_text(header, rows, _eol(text), text.endswith("\n")), True)

            # Every shipped song also has a "song" item; give added songs one in the same form.
            if (adds or filtering) and has(f"table/{loc}/product_item.csv"):
                text = source(f"table/{loc}/product_item.csv")
                header, rows = _table_rows(text)
                icol = {h: i for i, h in enumerate(header)}
                # A table without the item type has no song items to take out.
                gone_items = {r[icol["item_id"]] for r in rows
                              if r[icol["item_type"]] == "S" and not (r[icol["item_id"]].isdigit() and int(r[icol["item_id"]]) in imported)} \
                    if {"item_id", "item_type"} <= icol.keys() else set()
                rows = [r for r in rows if not gone_items or r[icol["item_id"]] not in gone_items]
                for m in adds:
                    values = {"item_id": m["song_id"], "item_name": m["name"], "img_url_1": tiles.get(m["song_id"], "e0_" + m["name"]),
                              "img_url_2": "", "description": "", "repeat_count": 0, "item_type": "S",
                              "limit_minute": 0, "status": "N", "buy_level": 0, "buy_limit_count": 1,
                              "buy_limit_type": "F", "summary": m["full_name"], "update": 0}
                    rows.append([str(values.get(h, "")) for h in header])
                changed[f"table/{loc}/product_item.csv"] = (_csv_text(header, rows, _eol(text), text.endswith("\n")), True)

            # And a product, as every shipped song has (see _product_row).
            if (adds or gone_items) and has(f"table/{loc}/product_product.csv"):
                text = source(f"table/{loc}/product_product.csv")
                header, rows = _table_rows(text)
                pcol = {h: i for i, h in enumerate(header)}
                gone_products = {r[pcol["product_id"]] for r in rows if r[pcol["item_id"]] in gone_items}
                rows = [r for r in rows if r[pcol["product_id"]] not in gone_products]
                rows.extend(_product_row(header, m["song_id"]) for m in adds)
                changed[f"table/{loc}/product_product.csv"] = (_csv_text(header, rows, _eol(text), text.endswith("\n")), True)

            # Listed in the music shop categories, as the shipped songs' products are.
            if (adds or gone_products) and has(f"table/{loc}/category_categoryproduct.csv"):
                text = source(f"table/{loc}/category_categoryproduct.csv")
                header, rows = _table_rows(text)
                ccol = {h: i for i, h in enumerate(header)}
                rows = [r for r in rows if r[ccol["product_id"]] not in gone_products]
                for m in adds:
                    rows.extend(_category_rows(header, m["song_id"]))
                changed[f"table/{loc}/category_categoryproduct.csv"] = (_csv_text(header, rows, _eol(text), text.endswith("\n")), True)

            if has(f"table/{loc}/song_desc_{loc}.csv"):
                text = source(f"table/{loc}/song_desc_{loc}.csv")
                header, rows = _table_rows(text)
                dcol = {h: i for i, h in enumerate(header)}
                if "song_id" in dcol:
                    rows = [r for r in rows if r[dcol["song_id"]].isdigit() and int(r[dcol["song_id"]]) in imported]
                for m in adds:
                    values = {"song_id": m["song_id"], "fullname": m["full_name"], "genre": m["genre"],
                              "artist": m["artist_name"], "composed_by": m["composed_by"], "singer": m["singer"],
                              "feat_by": m["feat_by"], "arranged_by": m["arranged_by"],
                              "visualized_by": m["visualized_by"]}
                    rows.append([str(values.get(h, "")) for h in header])
                changed[f"table/{loc}/song_desc_{loc}.csv"] = (_csv_text(header, rows, _eol(text), text.endswith("\n")), True)

        # Write the changed client files (plain where the content has plain, always .lz4) and the manifest: the
        # content's own, without the files the server has not got, with these rows replaced or added.
        out_patch = patch_dir(new)
        manifest_eol = _eol(manifest_text)
        manifest_final = manifest_text.endswith("\n")
        lines = [ln for ln in manifest_text.splitlines() if ln.split(",", 1)[0] not in missing]
        index = {ln.split(",", 1)[0]: i for i, ln in enumerate(lines)}
        for rel, (raw, has_plain) in sorted(changed.items()):
            # Image bundles are packed already, and travel in the form the shipped ones do.
            packed = stored_encode(raw) if rel.startswith("dlc/") else lz4_encode(raw)
            os.makedirs(os.path.dirname(os.path.join(out_patch, rel)), exist_ok=True)
            with open(os.path.join(out_patch, rel + ".lz4"), "wb") as f:
                f.write(packed)
            if has_plain and os.path.exists(os.path.join(content_patch, rel)):
                with open(os.path.join(out_patch, rel), "wb") as f:
                    f.write(raw)
            row = f"{rel},{len(raw)},{_md5(raw)},{len(packed)},{_md5(packed)},0,1,,,"
            if rel in index:
                lines[index[rel]] = row
            else:
                lines.append(row)
        with open(os.path.join(out_patch, "patch_new.csv.lz4"), "wb") as f:
            # Same line endings (and final break, or none) as the content's manifest.
            body = manifest_eol.join(lines) + (manifest_eol if manifest_final else "")
            f.write(lz4_encode(body.encode("utf-8")))

    # Charts the imported files carry that the game cannot load (empty, or cut short): the overlay serves the chart's
    # pair in their place. A chart and its earphone variant have their notes at the same ticks (every pair of the
    # game's songs does), so the song plays the same. A chart whose pair cannot be loaded either stays as it is.
    charts_from_pair, charts_unreadable = _repair_charts(new)

    # Facts of the client's tables the game server's replies need (src/content.php), from the tables as phones get them.
    def effective(rel):
        if rel in changed:
            return _decode_table(changed[rel][0])
        return source(rel) if has(rel) else None
    _write_json(os.path.join(CUSTOM, "catalog.json"), _catalog(effective, locales, imported | {m["song_id"] for m in adds}))

    # Maintenance notice survives a rebuild (it lives in the overlay too).
    old_notice = os.path.join(web, "inspection")
    if os.path.isdir(old_notice):
        shutil.copytree(old_notice, os.path.join(new, "inspection"))

    shutil.rmtree(web + ".old", ignore_errors=True)
    if os.path.exists(web):
        os.rename(web, web + ".old")
    os.rename(new, web)
    shutil.rmtree(web + ".old", ignore_errors=True)
    _write_json(os.path.join(CUSTOM, "songList.json"), songs)
    # For the admin pages: songs that went out without a picture on their list tile.
    _write_json(os.path.join(CUSTOM, "tile-failures.json"), tile_failures)
    # For the setup and the doctor: the game's own files that did not come with the import.
    _write_json(os.path.join(CUSTOM, "missing-game-files.json"), game_missing)
    made = thumbnails(songs)
    return {"added": len(adds), "hidden": len(hide), "client_files": sorted(changed), "thumbnails": made,
            "tile_failures": tile_failures, "missing_game_files": game_missing,
            "charts_from_pair": charts_from_pair, "charts_unreadable": charts_unreadable}


def _chart_loads(path):
    """True when the game can load the chart file at path (song_files.chart_readable); a file that cannot be read
    counts as one the game could not load either."""
    try:
        with open(path, "rb") as f:
            return song_files.chart_readable(f.read())
    except OSError:
        return False


def _repair_charts(overlay):
    """Put, into the overlay being built, the pair of every imported chart the game cannot load. Returns the charts
    served from their pair and those left unreadable, by file name ("388", "534_EARPHONE")."""
    patterns = os.path.join(content_web(), "DMQ", "Patterns")
    from_pair, unreadable = [], []
    for song in base_song_list():
        for chart in song.get("song_patterns") or []:
            pid = chart.get("pattern_id")
            if pid is None:
                continue
            # A chart is asked for by its number, or with _EARPHONE for the earphone timing; each is the other's pair.
            for name, pair in ((f"{pid}", f"{pid}_EARPHONE"), (f"{pid}_EARPHONE", f"{pid}")):
                path = os.path.join(patterns, name)
                # A chart the import did not bring is not this check's to answer; one that loads needs nothing.
                if not os.path.isfile(path) or _chart_loads(path):
                    continue
                if _chart_loads(os.path.join(patterns, pair)):
                    os.makedirs(os.path.join(overlay, "DMQ", "Patterns"), exist_ok=True)
                    _place(os.path.join(patterns, pair), os.path.join(overlay, "DMQ", "Patterns", name))
                    from_pair.append(name)
                else:
                    unreadable.append(name)
    return from_pair, unreadable


def _tile_template():
    """The imported image bundle that added songs' tile bundles are made from, without its container. A server
    without imported content has none (OSError): its added songs go without a picture on their tile."""
    path = os.path.join(patch_dir(content_web()), TILE_TEMPLATE + ".lz4")
    with open(path, "rb") as f:
        return lz4_decode(f.read())


def _ints(row, col, names):
    """The named columns of a table row as ints (an empty or odd cell as 0)."""
    return {n: int(row[col[n]]) if row[col[n]].lstrip("-").isdigit() else 0 for n in names}


def _catalog(table, locales, songs=None):
    """What some of the game server's replies need from the client's tables, as phones get them. table(rel) gives a
    table's text ("table/us/product_item.csv"), or None when there is none. The language folders hold the same rows
    in these three tables; the first one is read.

      point_charts    the charts that cost MAX POINT to open (game.getPatternUsePointData), by chart id
      items           every item a player owns (shop.getOwnItemList), by id
      unlock_product  the level unlock product (shop.getProductForUnlock), or None
    """
    out = {"point_charts": [], "items": [], "unlock_product": None}
    if not locales:
        return out
    loc = locales[0]
    text = table(f"table/{loc}/song_songPattern.csv")
    if text:
        header, rows = _table_rows(text)
        col = {h: i for i, h in enumerate(header)}
        # An older table without the cost columns: no chart costs anything then.
        if {"pattern_id", "song_id", "point_type", "point_value"} <= col.keys():
            charts = [_ints(r, col, ("pattern_id", "song_id", "point_type", "point_value")) for r in rows]
            # Only charts of songs the server has (songs: their ids; None for all).
            out["point_charts"] = sorted((c for c in charts if c["point_type"] and c["song_id"] in POINT_SONGS
                                          and (songs is None or c["song_id"] in songs)), key=lambda c: c["pattern_id"])
    items = table(f"table/{loc}/product_item.csv")
    products = table(f"table/{loc}/product_product.csv")
    item_rows = {}
    if items:
        header, rows = _table_rows(items)
        col = {h: i for i, h in enumerate(header)}
        for r in rows:
            item_rows[r[col["item_id"]]] = dict(zip(header, r))
        out["items"] = sorted(int(i) for i, r in item_rows.items()
                              if i.isdigit() and r.get("item_type") not in ("S", "P") and int(i) not in NOT_OWNED)
    if products and UNLOCK_PRODUCT in item_rows:
        header, rows = _table_rows(products)
        col = {h: i for i, h in enumerate(header)}
        row = next((dict(zip(header, r)) for r in rows if r[col["product_id"]] == UNLOCK_PRODUCT), None)
        if row:
            item = item_rows[UNLOCK_PRODUCT]
            num = lambda v: int(v) if str(v).lstrip("-").isdigit() else 0
            # The reply's keys in the client's order, numbers as numbers.
            out["unlock_product"] = {
                "product_id": num(row.get("product_id")), "platform_product_id": num(row.get("platform_product_id")),
                "store_product_id": row.get("store_product_id", ""), "product_type": row.get("product_type", ""),
                "cost_game_point": num(row.get("cost_game_point")), "cost_game_cash": num(row.get("cost_game_cash")),
                "item_id": num(item.get("item_id")), "item_name": item.get("item_name", ""),
                "img_url_1": item.get("img_url_1", ""), "img_url_2": item.get("img_url_2", ""),
                "summary": item.get("summary", ""), "description": item.get("description", ""),
                "repeat_count": num(item.get("repeat_count")), "item_type": item.get("item_type", ""),
                "limit_minute": num(item.get("limit_minute")), "status": item.get("status", ""),
                "buy_level": num(item.get("buy_level")), "buy_limit_count": num(item.get("buy_limit_count")),
                "buy_limit_type": item.get("buy_limit_type", ""), "reg_date": "",
                "sale_start_date": row.get("sale_start_date", ""), "sale_end_date": row.get("sale_end_date", ""),
                "display_order": 0,
            }
    return out


def thumbnails(song_list):
    """Small JPEG jackets for the web pages (the game's PNGs are 1024x768, about 0.85 MB each).

    Only missing ones are made, so this is quick after the first run. Returns how many were made.
    """
    out = os.path.join(CUSTOM, "thumbs")
    os.makedirs(out, exist_ok=True)
    eye = os.path.join(content_web(), "viewImg", "eye")
    # Imported jacket names by lowercase name: one shipped name differs in case from the song list.
    shipped = {f.lower(): f for f in os.listdir(eye)} if os.path.isdir(eye) else {}
    made = 0
    for s in song_list:
        dest = os.path.join(out, s["name"] + ".jpg")
        if os.path.exists(dest):
            continue
        # An added song's jacket is in the overlay; an imported one in the content.
        src = os.path.join(CUSTOM, "web", "viewImg", "eye", s["name"] + ".png")
        if not os.path.exists(src):
            found = shipped.get((s["name"] + ".png").lower())
            if not found:
                continue
            src = os.path.join(eye, found)
        try:
            _thumbnail(src, dest)
            made += 1
        except Exception:  # noqa: BLE001 - one bad image must not stop the song pages
            continue
    return made


def _thumbnail(src, dest):
    """Write a 320x240 JPEG of src to dest."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = MAX_JACKET_PIXELS
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((320, 240))
        im.save(dest + ".tmp", "JPEG", quality=82, optimize=True)
    os.replace(dest + ".tmp", dest)


@_serialized
def set_maintenance(on, message, host):
    """Turn the in-game maintenance notice on or off (served from the overlay)."""
    folder = os.path.join(CUSTOM, "web", "inspection")
    if not on:
        shutil.rmtree(folder, ignore_errors=True)
        return
    os.makedirs(folder, exist_ok=True)
    status = {"value": {"open_yn": "Y", "disable_apps": [], "non_kill_apps": [],
                        "noti_url": f"http://{host}/inspection/noti.html"},
              "result_code": "000", "resulr_msg": "API_OK"}
    _write_json(os.path.join(folder, "status.json"), status)
    page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            "<body style='background:#0d1118;color:#e6edf5;font:18px system-ui;padding:24px'>"
            # Its lines stay lines, in the game's notice and when the admin page reads it back.
            f"<h2>Maintenance</h2><p>{_html(message).replace(chr(13), '').replace(chr(10), '<br>')}</p></body>")
    with open(os.path.join(folder, "noti.html"), "w", encoding="utf-8") as f:
        f.write(page)


def maintenance():
    """(on, message) for the current notice."""
    path = os.path.join(CUSTOM, "web", "inspection", "noti.html")
    if not os.path.isfile(path):
        return False, ""
    with open(path, encoding="utf-8") as f:
        m = re.search(r"<p>(.*)</p>", f.read(), re.S)
    import html
    return True, html.unescape(m.group(1).replace("<br>", "\n")) if m else ""


if __name__ == "__main__":
    # python3 -m opendmtq_tools.songs : regenerate songList.json and the overlay (used at start-up).
    print(json.dumps(rebuild()), flush=True)


def _html(text):
    import html
    return html.escape(text or "The server is under maintenance. Please try again later.")
