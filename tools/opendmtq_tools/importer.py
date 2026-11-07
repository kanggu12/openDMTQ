"""Import the game files an operator has, from the folder or files they choose.

Accepts a folder (or files) holding any mix of:
  * the game's Android client (APK): loose, inside an archive, or in an APK bundle (.xapk, .apks). Kept in
    data/apk/base, the base every phone app of this server is built from: the original, or one changed for another
    server (its build points it at this one). An app OpenDMTQ built is not a base, nor is any other app.
  * the game's server files: the game host's folder (dmqglb.mb.pmang.com, or the same files in a folder of another
    name, such as the web folder of an OpenDMTQ server's content), or only the client's patch folder in it (patch, or
    phone_new: the game data alone), loose or in an archive, at any depth, with or without the song list kept beside
    the folder or in it (_info/songList.json, or songs.json; without one the list is made from the game's own tables).
    The whole files are taken before the game data alone. Copied into data/content in two parts, each on its own:
      game data   the client's tables, the images of its screens and its fonts: what the game cannot start without
      songs       the music, charts, jackets, previews and song tiles, and the song list
    Nothing else of it: no program code, no database, no notes.
  * archives as people have them: .zip, .7z, .rar, one split in parts (.7z.001, .part1.rar and the like, all parts in
    one folder), and one archive inside another.

OpenDMTQ itself ships none of these files. With the game data and no songs the server runs with an empty song list.
IMPORT_SONGS=yes imports the songs too (the CLI's --songs), from files that have some: without, the server keeps its
songs. IMPORT_GAME=no leaves the game data as it is. Archives
are opened with 7-Zip inside this container, never on the host.

Usage (inside the tools container): python3 -m opendmtq_tools.importer
  /in    the user's folder or file, read-only
  /data  the repository's data/ folder
"""

import csv
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from .patch_apk import describe, inspect, sha256

# What to read and where data/ is: compose's mount points, or a host install's own folders.
IN = os.environ.get("OPENDMTQ_IMPORT_IN", "/in")
DATA = os.environ.get("OPENDMTQ_DATA", "/data")
# The game's server files: the game host's folder, with the client's patch folder in it. An old server kept a song list
# beside that folder; the list is optional (made from the game's own tables without it).
HOST = "dmqglb.mb.pmang.com"
GAME_DIR = HOST + "/patch/phone_new"
PATCH_DIR = "patch/phone_new"
SONG_LIST = "_info/songList.json"
# The client's patch folder copied by itself (phone_new, or the patch folder around it) is the game data alone. It
# counts by what is in it too, since another program may have a patch folder: a client version's folder (1.003.005)
# with the client's tables for Android.
PATCH_NAME = "phone_new"
PATCH_PARENT = "patch"
CLIENT_VERSION = re.compile(r"\d+(?:\.\d+)+")
# The same in an archive's listing: a path through phone_new and a client version's folder into its Android tables.
PATCH_MEMBER = re.compile(r"(?:^|/)(" + PATCH_NAME + r"/)\d+(?:\.\d+)+/android/table/")
# An OpenDMTQ server's content folder holds the same files in web/, and the song list beside it.
CONTENT_SONGS = "songs.json"
# Archive types 7-Zip opens here, and the 7-Zip program: the image's 7zz, or the one a host install names (the
# official build, as the distributions' leave out RAR). APK bundles are zip files with the app inside.
ARCHIVES = (".rar", ".zip", ".7z")
APK_BUNDLES = (".xapk", ".apks")
# Words the game's files are usually named with: archives with one in the name are opened first, so that a folder full
# of other archives is not listed through before the game's.
GAME_WORDS = ("dmtq", "djmax", "technika")
SEVENZIP = os.environ.get("OPENDMTQ_7ZIP") or "7zz"
# What is taken from the game host's folder: (path in it, path in data/content, the file names kept there). Only the
# game's data files: music (.fpk), videos (.webm), charts (a number, or a number and _EARPHONE), images, the client's
# tables and their packed forms. Anything else (scripts, pages, databases, notes) stays where it was.
TAKE = [
    ("DMQ/Songs/", "web/DMQ/Songs/", re.compile(r"\d+/\d+\.(?:fpk|webm)")),
    ("DMQ/Patterns/", "web/DMQ/Patterns/", re.compile(r"\d+(?:_EARPHONE)?")),
    ("viewImg/", "web/viewImg/", re.compile(r"[\w.-]+/[\w .()-]+\.(?:png|jpg)", re.I)),
    (PATCH_DIR + "/", "web/patch/phone_new/", re.compile(r"[\d.]+/(?:android|ios)/[\w./ -]+\.(?:lz4|csv)")),
    ("static/", "web/static/", re.compile(r"[\w./-]+\.(?:png|jpg)", re.I)),
]
# The song list's fields, all in the client's song table too, and those of them that are numbers.
SONG_FIELDS = ("song_id", "name", "full_name", "genre", "artist_name", "original_bga_yn", "loop_bga_yn", "composed_by",
               "singer", "feat_by", "arranged_by", "visualized_by", "cost_game_point", "cost_game_cash", "flag", "status",
               "free_yn", "hidden_yn")
SONG_NUMBERS = ("song_id", "cost_game_point", "cost_game_cash", "flag")
# A song's own files in the client's patch folder: its preview and the song list tiles (d3_e<n>, d_e<n>).
SONG_PATCH = re.compile(r"web/patch/phone_new/[^/]+/[^/]+/(?:preview/.*|dlc/d3?_e\d+\.unity3d\.lz4)")


def part_of(rel):
    """Which part a file of data/content belongs to (rel: its path there): "songs" or "game"."""
    if rel == "songs.json" or rel.startswith("web/DMQ/") or rel.startswith("web/viewImg/eye/") or SONG_PATCH.fullmatch(rel):
        return "songs"
    return "game"


def log(msg):
    """Progress line, flushed so docker shows it immediately."""
    print(msg, flush=True)


def is_patch_folder(path):
    """True when path is the client's patch folder by what is in it: a client version's folder with the client's
    Android tables."""
    try:
        names = os.listdir(path)
    except OSError:
        return False
    return any(CLIENT_VERSION.fullmatch(n) and os.path.isdir(os.path.join(path, n, "android", "table")) for n in names)


def patch_itself(path):
    """True when path is the client's patch folder copied by itself: phone_new, or the patch folder around it. Known by
    its name first, then by what is in it: every folder of a search is asked, and a name costs nothing to look at."""
    name = os.path.basename(path.rstrip("/\\"))
    return ((name == PATCH_NAME and is_patch_folder(path))
            or (name == PATCH_PARENT and is_patch_folder(os.path.join(path, PATCH_NAME))))


def patch_of(host):
    """The client's patch folder of a game host's folder, or None: its patch/phone_new, else the game data alone (the
    phone_new in host, or host itself), by what is in it: asked only of folders found already, whatever their names."""
    # Each in one spelling (normpath): the same folder found from two places compares equal, on Windows too, where
    # PATCH_DIR's slash would sit beside the system's backslashes.
    standard = os.path.join(host, PATCH_PARENT, PATCH_NAME)
    if os.path.isdir(standard):
        return os.path.normpath(standard)
    for path in (os.path.join(host, PATCH_NAME), host):
        if is_patch_folder(path):
            return os.path.normpath(path)
    return None


def host_folder(path, alone=True, chosen=False):
    """What stands for the game host's folder in or at path, or None: path/dmqglb.mb.pmang.com, or path itself when it
    holds the same files under another name (the client's patch folder, and the songs' or the images' folder beside
    it), or path/web in an OpenDMTQ server's content folder. Else, unless alone is False, the game data alone: path,
    when it holds the client's patch folder by itself (patch/phone_new) or is that folder (patch, phone_new). The
    patch folder alone counts by what is in it, as another program may have one. chosen: path is the folder chosen
    for the import, whose name may be lost (mounted as /in): the patch folder counts by what is in it alone."""
    if os.path.isdir(os.path.join(path, GAME_DIR)):
        return os.path.join(path, HOST)
    # Each folder asked once: a search asks this of every folder it passes.
    patch = os.path.join(path, PATCH_DIR)
    has_patch = os.path.isdir(patch)
    for here, there in ((path, has_patch), (os.path.join(path, "web"), None)):
        if (there if there is not None else os.path.isdir(os.path.join(here, PATCH_DIR))) and (
                os.path.isdir(os.path.join(here, "DMQ")) or os.path.isdir(os.path.join(here, "viewImg"))):
            return here
    if alone and ((has_patch and is_patch_folder(patch)) or patch_itself(path)
                  or (chosen and (is_patch_folder(path) or is_patch_folder(os.path.join(path, PATCH_NAME))))):
        return path
    return None


def whole_host_folder(path):
    """The whole game host's folder in or at path (host_folder without the game data alone), or None."""
    return host_folder(path, alone=False)


def songs_in(host):
    """How many songs (their music files) a game host's folder holds."""
    folder = os.path.join(host, "DMQ", "Songs")
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    return sum(1 for d in names if os.path.isfile(os.path.join(folder, d, d + ".fpk")))


def song_list_of(host):
    """The song list kept with the game host's folder, or None: an old server's (_info/songList.json) beside the folder
    or in it, or the one beside the web folder of an OpenDMTQ server's content (songs.json)."""
    parent = os.path.dirname(os.path.normpath(host))
    for path in (os.path.join(parent, SONG_LIST),
                 os.path.join(parent, CONTENT_SONGS) if os.path.basename(os.path.normpath(host)) == "web" else "",
                 os.path.join(host, SONG_LIST)):
        if path and os.path.isfile(path):
            return path
    return None


def is_game_folder(path):
    """True when path is a folder of the game's server files, whatever its name."""
    return host_folder(path) is not None


def archive_role(path):
    """What a file is to the import: "first" for an archive to open (a whole one, or the first part of one split in
    parts), "part" for a later part (7-Zip reads it through the first), None for anything else."""
    low = os.path.basename(path).lower()
    m = re.search(r"\.part(\d+)\.rar$", low) or re.search(r"\.(?:7z|zip|rar)\.(\d{3})$", low)
    if m:
        return "first" if int(m.group(1)) == 1 else "part"
    if re.search(r"\.[rz]\d\d$", low):
        return "part"
    return "first" if low.endswith(ARCHIVES + APK_BUNDLES) else None


def split_stem(name):
    """The name the parts of an archive in parts share (lower case), or None for an archive in one piece."""
    low = name.lower()
    m = (re.fullmatch(r"(.+)\.part\d+\.rar", low) or re.fullmatch(r"(.+\.(?:7z|zip|rar))\.\d{3}", low)
         or re.fullmatch(r"(.+)\.[rz]\d\d", low))
    return m.group(1) if m else None


def parts_with(first, names):
    """The later parts, among names, of the archive whose first part (or whole file, for x.rar with x.r00 beside it) is
    first."""
    stem = split_stem(first) or os.path.splitext(first.lower())[0]
    return [n for n in names if archive_role(n) == "part" and split_stem(n) == stem]


def walk(root, depth=4):
    """Files and folders under root, a few levels deep (downloads are shallow: a folder or two around the game's)."""
    if os.path.isfile(root):
        yield root
        return
    # How deep a folder is, by its separators (both kinds: Windows paths may carry either).
    def depth_of(path):
        return path.replace("\\", "/").rstrip("/").count("/")
    base = depth_of(root)
    for d, dirs, files in os.walk(root):
        # Do not descend into a game files folder: thousands of song files, nothing else to find there; nor into the
        # client's patch folder alone. A folder that only holds the patch folder is looked in further: the whole files
        # may be beside it.
        if whole_host_folder(d) or patch_itself(d):
            dirs[:] = []
        if depth_of(d) - base >= depth:
            dirs[:] = []
        yield d
        for f in files:
            yield os.path.join(d, f)


# Each archive's listing, read once per run: the APKs and the game's files are both looked for in the same archives.
_listed = {}


def archive_paths(archive, say=True):
    """Every member path of an archive, as 7-Zip lists them. say: log an archive it cannot list (check() says so in its
    own words)."""
    if archive not in _listed:
        # In UTF-8 whatever the system's code page (-sccUTF-8), as this program reads it: names in Korean come through.
        r = subprocess.run([SEVENZIP, "l", "-ba", "-slt", "-sccUTF-8", archive], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            if say:
                log(f"  skip {os.path.basename(archive)}: 7-Zip cannot list it")
            _listed[archive] = []
        else:
            # Windows' 7-Zip lists its paths with backslashes; it takes forward ones back.
            _listed[archive] = [line[7:].replace("\\", "/") for line in r.stdout.splitlines() if line.startswith("Path = ")]
    return _listed[archive]


def named_like_the_game(path):
    """True when a file's name carries one of the game's words, in any letter case."""
    name = os.path.basename(path).lower()
    return any(word in name for word in GAME_WORDS)


def patch_alone_in(paths):
    """The game data alone in an archive's listing, the client's patch folder in it by itself (known by the client's
    tables in it): the folder that stands for the game host's, as host_folder takes it from a folder (the one that holds
    patch/phone_new, else phone_new itself), the one nearest the top; or None."""
    found = set()
    for p in paths:
        m = PATCH_MEMBER.search(p)
        if m:
            found.add(p[:m.end(1)])
    if not found:
        return None
    patch = min(found, key=lambda f: (f.count("/"), f))
    inner = PATCH_DIR + "/"
    return patch[: -len(inner)] if patch == inner or patch.endswith("/" + inner) else patch


def tree_in(paths):
    """Where the game's server files are inside an archive: (the game host's folder, the song list or None), or None.
    The folder is the game host's (dmqglb.mb.pmang.com), or one of another name with the same files (whole_tree_in);
    else the game data alone (patch_alone_in), without a song list: it has no songs."""
    found = whole_tree_in(paths)
    if found:
        return found
    alone = patch_alone_in(paths)
    return (alone, None) if alone is not None else None


def whole_tree_in(paths):
    """tree_in for the whole files only: the game host's folder, nearest the top when there are several, with the song
    list beside it or in it; or None."""
    names = set(paths)
    hosts = set()
    for p in paths:
        at = ("/" + p).find("/" + PATCH_DIR + "/")
        if at < 0:
            continue
        host = p[:at]
        # A patch folder of another program does not count: the game host's name, or the songs or images beside it.
        if (host.rstrip("/").endswith(HOST) or host == HOST + "/"
                or any(n.startswith(host + "DMQ/") or n.startswith(host + "viewImg/") for n in names)):
            hosts.add(host)
    if not hosts:
        return None
    host = min(hosts, key=lambda h: (h.count("/"), h))
    parent = host[: -len(HOST) - 1] if host.rstrip("/").endswith(HOST) else "/".join(host.rstrip("/").split("/")[:-1])
    parent = parent + "/" if parent and not parent.endswith("/") else parent
    # The old server's list beside the folder or in it, or the one beside an OpenDMTQ content folder's web/.
    for listed in (parent + SONG_LIST, parent + CONTENT_SONGS if host.rstrip("/").split("/")[-1] == "web" else None,
                   host + SONG_LIST):
        if listed and listed in names:
            return host, listed
    return host, None


def game_prefix(paths):
    """The folder inside an archive that holds the game's files, or None (the folder around the game host's)."""
    found = tree_in(paths)
    if found is None:
        return None
    host = found[0]
    return host[: -len(HOST) - 1] if host.rstrip("/").endswith(HOST) else host


def _put(src, dest):
    """One file into the content: a hard link where the system allows one (the same disk: no second copy of
    gigabytes, and the files never change), else a copy."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        os.link(src, dest)
    except OSError:
        shutil.copyfile(src, dest)


def keep_others(dest, parts, patch_only=False):
    """Start the content folder being built with the current content's files of the parts not imported now (linked,
    not copied), so that importing the songs keeps the game data and the other way round. patch_only: the files come
    from the client's patch folder alone, which replaces that folder only: the rest of the game data stays (the
    pictures of HOW TO PLAY and of the news)."""
    current = os.path.join(DATA, "content")
    if not os.path.isdir(current):
        return
    for d, _, files in os.walk(current):
        for f in files:
            rel = os.path.relpath(os.path.join(d, f), current).replace(os.sep, "/")
            if part_of(rel) not in parts or (patch_only and not rel.startswith("web/patch/")):
                _put(os.path.join(d, f), os.path.join(dest, rel))


def _table(path_plain):
    """A client table's rows as dicts, from the plain .csv or its .lz4 form beside it; [] when there is neither."""
    from . import songs
    for path in (path_plain, path_plain + ".lz4"):
        if os.path.isfile(path):
            with open(path, "rb") as f:
                raw = f.read()
            text = (songs.lz4_decode(raw) if path.endswith(".lz4") else raw).decode("utf-8-sig", errors="replace")
            rows = list(csv.reader(io.StringIO(text)))
            return [dict(zip(rows[0], r)) for r in rows[1:] if r] if rows else []
    return []


def made_song_list(host):
    """The song list, from the game's own tables, for the songs whose files the game host's folder has: what an old
    server kept as _info/songList.json holds the same fields. A chart is listed when its file is there."""
    patch = patch_of(host)
    tables = sorted(glob.glob(os.path.join(patch, "*", "android", "table", "*", "song_song.csv*"))) if patch else []
    if not tables:
        return []
    # The newest patch folder, and English where it has it (every language's table lists the same songs).
    newest = max({os.path.dirname(os.path.dirname(os.path.dirname(t))) for t in tables}, key=lambda d: [
        int(x) if x.isdigit() else 0 for x in os.path.basename(os.path.dirname(d)).split(".")])
    langs = sorted(os.listdir(os.path.join(newest, "table")), key=lambda lang: lang != "us")
    table = os.path.join(newest, "table", langs[0])
    charts = {}
    for p in _table(os.path.join(table, "song_songPattern.csv")):
        if p.get("pattern_id", "").isdigit() and os.path.isfile(os.path.join(host, "DMQ", "Patterns", p["pattern_id"])):
            charts.setdefault(p["song_id"], []).append({k: int(p[k]) for k in ("pattern_id", "line", "difficulty", "signature")})
    out = []
    for r in _table(os.path.join(table, "song_song.csv")):
        sid = r.get("song_id", "")
        if not sid.isdigit() or not os.path.isfile(os.path.join(host, "DMQ", "Songs", sid, sid + ".fpk")):
            continue
        song = {k: (int(r[k]) if k in SONG_NUMBERS and r.get(k, "").lstrip("-").isdigit() else r.get(k, "")) for k in SONG_FIELDS}
        song["song_patterns"] = sorted(charts.get(sid, []), key=lambda c: c["pattern_id"])
        out.append(song)
    return out


def collect(root, dest, parts, song_list=None):
    """Copy the files of the given parts ("game", "songs") that TAKE names from the game host's folder root into the
    content folder being built, with the song list (the old server's, at song_list, else made from the game's tables).
    Returns how many songs, charts and other files came."""
    counts = {"songs": 0, "charts": 0, "files": 0}
    for there, here, keep in TAKE:
        # The client's patch folder where it is: in the game host's folder, or the folder itself for the game data alone.
        base = (patch_of(root) or "") if there == PATCH_DIR + "/" else os.path.join(root, there)
        if not os.path.isdir(base):
            continue
        for d, _, files in os.walk(base):
            for f in files:
                rel = os.path.relpath(os.path.join(d, f), base).replace(os.sep, "/")
                if not keep.fullmatch(rel) or part_of(here + rel) not in parts:
                    continue
                _put(os.path.join(d, f), os.path.join(dest, here, rel))
                if here == "web/DMQ/Songs/" and rel.endswith(".fpk"):
                    counts["songs"] += 1
                elif here == "web/DMQ/Patterns/" and not rel.endswith("_EARPHONE"):
                    counts["charts"] += 1
                else:
                    counts["files"] += 1
    if "songs" not in parts:
        return counts
    # The song list, as the server reads it (a Windows editor's byte-order mark taken off), or made from the tables.
    if song_list:
        with open(song_list, encoding="utf-8-sig") as f:
            songs = json.load(f)
    else:
        songs = made_song_list(root)
        log(f"  song list: made from the game's own tables ({len(songs)} songs with their files)")
    with open(os.path.join(dest, "songs.json"), "w", encoding="utf-8") as f:
        json.dump(songs, f, ensure_ascii=False, indent=1)
    # Windows ignored letter case and Linux does not: the game asks for <name>.png with the name from the song list,
    # so a jacket whose file is named in another case gets the asked name too (Song.png for song.png).
    eye = os.path.join(dest, "web", "viewImg", "eye")
    have = {f.lower(): f for f in os.listdir(eye)} if os.path.isdir(eye) else {}
    for s in songs:
        want = f"{s.get('name', '')}.png"
        found = have.get(want.lower())
        if found and found != want and not os.path.exists(os.path.join(eye, want)):
            _put(os.path.join(eye, found), os.path.join(eye, want))
            log(f"  jacket {want} -> {found}")
    return counts


def report(parts, counts):
    """One line for what came in."""
    what = []
    if "game" in parts:
        what.append("game data")
    if "songs" in parts:
        what.append(f"{counts['songs']} songs, {counts['charts']} charts")
    log(f"  {' and '.join(what)} ({counts['files']} other files) -> data/content")


def install_content(built):
    """Move a complete content folder into data/content, entry by entry inside it: a running server has data/content
    mounted, and keeps seeing the folder itself (a folder swapped whole would leave it the deleted old one). Each
    entry is renamed into place, the old one kept until the new one is there."""
    dest = os.path.join(DATA, "content")
    os.makedirs(dest, exist_ok=True)
    for name in ("web", "songs.json"):
        new, cur, old = os.path.join(built, name), os.path.join(dest, name), os.path.join(dest, name + ".old")
        shutil.rmtree(old, ignore_errors=True) if os.path.isdir(old) else (os.path.exists(old) and os.remove(old))
        if os.path.exists(cur):
            os.rename(cur, old)
        if os.path.exists(new):
            os.rename(new, cur)
        shutil.rmtree(old, ignore_errors=True) if os.path.isdir(old) else (os.path.exists(old) and os.remove(old))
    shutil.rmtree(built, ignore_errors=True)


def named(parts):
    """The parts in words, for the log: "game data and songs"."""
    return " and ".join(("game data" if p == "game" else "songs") for p in sorted(parts))


def with_songs_only(parts, songs_folder):
    """The parts to take from files with or without the songs' folder (DMQ): without, not the songs, so that the server
    keeps the ones it has. The patch folder alone, or whole files copied without DMQ, would otherwise leave a song
    list with nothing to play, or none at all."""
    if songs_folder or "songs" not in parts:
        return parts
    log("  songs: none there, the songs on the server stay as they are")
    return parts - {"songs"}


def import_folder(path, host, parts, alone=False):
    """Import the given parts from the game host's folder host, found at path. alone: it is the game data alone (the
    patch folder copied by itself), which replaces the patch folder only."""
    where = path[len(IN):] if path.startswith(IN) else path[len(DATA):] if path.startswith(DATA) else path
    log(f"{named(parts)}: folder {where or '/'}")
    parts = with_songs_only(parts, os.path.isdir(os.path.join(host, "DMQ")))
    if not parts:
        return
    built = os.path.join(DATA, "content.new")
    keep_others(built, parts, patch_only=alone)
    counts = collect(host, built, parts, song_list_of(host))
    install_content(built)
    report(parts, counts)


def import_archive(path, found, parts, alone=False):
    """Import the given parts from an archive, found: tree_in's answer for it. False when 7-Zip could not unpack it.
    alone: as import_folder's."""
    host, listed = found
    listing = archive_paths(path)
    log(f"{named(parts)}: {os.path.basename(path)} ({host or 'root'}), extracting")
    parts = with_songs_only(parts, any(m == host + "DMQ" or m.startswith(host + "DMQ/") for m in listing))
    if not parts:
        return True
    built = os.path.join(DATA, "content.new")
    tmp = tempfile.mkdtemp(dir=DATA, prefix=".extract-")
    try:
        # Only the game's files and the list: an archive may carry other programs beside them. The client's patch
        # folder where it is: in the game host's folder, or the folder itself (phone_new by itself).
        patch = host + PATCH_DIR + "/"
        if not any(m.startswith(patch) for m in listing):
            patch = host
        wanted = ([f"{host}{there}*" for there, _, _ in TAKE if there != PATCH_DIR + "/"] + [patch + "*"]
                  + ([listed] if listed else []))
        try:
            subprocess.run([SEVENZIP, "x", "-y", "-bso0", "-bsp0", f"-o{tmp}", path] + wanted, check=True)
        except subprocess.CalledProcessError as e:
            # A damaged archive, or one split in parts with a part missing: said so, and the next one is tried.
            log(f"  skip {os.path.basename(path)}: 7-Zip could not unpack it (exit {e.returncode}); "
                "an archive in parts needs all of them in one folder")
            return False
        # Extracted on the same disk as the content: linked across, then the extraction goes.
        keep_others(built, parts, patch_only=alone)
        counts = collect(os.path.join(tmp, host) if host else tmp, built, parts,
                         os.path.join(tmp, listed) if listed else None)
        install_content(built)
        report(parts, counts)
    finally:
        # Never leave gigabytes of half-extracted files behind.
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(built, ignore_errors=True)
    return True


def import_game_files(candidates, parts, inner=True, chosen=()):
    """Import the given parts of the first game files folder or archive found: the whole files before the game data
    alone (the patch folder copied by itself), a folder before an archive, and an archive inside one of the archives
    (inner) before the game data alone too: one level, deeper is no download anyone makes. chosen: the folders chosen
    for the import (host_folder's chosen)."""
    # What an earlier run left when it was killed: gigabytes each, and nothing else ever removes them.
    if inner:
        for old in glob.glob(os.path.join(DATA, ".extract-*")) + glob.glob(os.path.join(DATA, "content.new")):
            shutil.rmtree(old, ignore_errors=True)
    alone = []
    for path in candidates:
        host = host_folder(path, chosen=path in chosen) if os.path.isdir(path) else None
        if host and whole_host_folder(path):
            import_folder(path, host, parts)
            return True
        if host:
            alone.append((path, host))
    # The archives, those named like the game's first: the first that holds the game's files is the one imported. A
    # split one through its first part; APK bundles hold an app, not these.
    archives = sorted((p for p in candidates if os.path.isfile(p) and archive_role(p) == "first"
                       and not p.lower().endswith(APK_BUNDLES)), key=lambda p: not named_like_the_game(p))
    later = []
    for path in archives:
        found = whole_tree_in(archive_paths(path))
        if found is None:
            # The game data alone waits for the whole files in the archives after it, and in those inside them.
            alone_in = patch_alone_in(archive_paths(path))
            if alone_in is not None:
                later.append((path, (alone_in, None)))
            continue
        if import_archive(path, found, parts):
            return True
    if inner and import_inside(archives, parts):
        return True
    for path, host in alone[:1]:
        import_folder(path, host, parts, alone=True)
        return True
    for path, found in later:
        if import_archive(path, found, parts, alone=True):
            return True
    return False


def import_inside(archives, parts):
    """import_game_files one level down: in an archive inside one of these (a .zip made of the .rar, say), with its
    parts if it has any. True when it imported something."""
    for path in archives:
        inside = [m for m in archive_paths(path) if archive_role(m) and not m.lower().endswith(APK_BUNDLES)]
        if not any(archive_role(m) == "first" for m in inside):
            continue
        log(f"  looking inside {os.path.basename(path)}: {', '.join(os.path.basename(m) for m in inside[:3])}")
        tmp = tempfile.mkdtemp(dir=DATA, prefix=".extract-")
        try:
            try:
                subprocess.run([SEVENZIP, "x", "-y", "-bso0", "-bsp0", f"-o{tmp}", path] + inside, check=True)
            except subprocess.CalledProcessError as e:
                log(f"  skip {os.path.basename(path)}: 7-Zip could not unpack it (exit {e.returncode})")
                continue
            if import_game_files([os.path.join(tmp, m) for m in inside], parts, inner=False):
                return True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return False


def import_apks(candidates):
    """Copy every game client found (loose, or one level inside an archive or an APK bundle) into data/apk/base: the
    original, or one changed for another server (the build points it at this one). Returns how many."""
    base = os.path.join(DATA, "apk", "base")
    os.makedirs(base, exist_ok=True)
    kept = 0
    with tempfile.TemporaryDirectory() as tmp:
        apks = []
        for path in candidates:
            low = path.lower()
            if os.path.isfile(path) and low.endswith(".apk"):
                apks.append(path)
            elif os.path.isfile(path) and archive_role(path) == "first":
                # A client may come inside an archive, with or without a folder around it, or in an APK bundle (which
                # holds the app and its split parts: those are no client, and the check below leaves them out).
                members = [p for p in archive_paths(path) if p.lower().endswith(".apk")]
                if members:
                    out = tempfile.mkdtemp(dir=tmp)
                    try:
                        subprocess.run([SEVENZIP, "e", "-y", "-bso0", "-bsp0", f"-o{out}", path] + members, check=True)
                    except subprocess.CalledProcessError as e:
                        # A damaged archive: said so; the other files still come in.
                        log(f"  skip {os.path.basename(path)}: 7-Zip could not unpack it (exit {e.returncode})")
                        continue
                    apks += [os.path.join(out, f) for f in os.listdir(out)]
        # Clients already in base/, by content, so a second copy of the same file is not added.
        have = {sha256(os.path.join(base, f)) for f in os.listdir(base) if f.lower().endswith(".apk")}
        for apk in apks:
            name = os.path.basename(apk)
            info = inspect(apk)
            if info["kind"] in ("original", "other server"):
                digest = sha256(apk)
                if digest in have:
                    log(f"base APK: {name} (already imported)")
                else:
                    shutil.copyfile(apk, os.path.join(base, name))
                    have.add(digest)
                    log(f"base APK: {name} ({describe(info)})")
                kept += 1
            elif re.fullmatch(r"(?:split_)?config\..+\.apk", name, re.I):
                # A split part of an app bundle (its languages, screen sizes or processor): nothing to say about it.
                continue
            else:
                log(f"  skip {name}: {describe(info)}")
    return kept


def song_count(paths, host=""):
    """How many songs (their music files) a listing of the game host's folder holds."""
    music = re.compile(re.escape(host) + r"DMQ/Songs/(\d+)/\1\.fpk")
    return sum(1 for p in paths if music.fullmatch(p))


def what_is(path, chosen=False):
    """What one file or folder is to the import, without importing anything: {"kind", "ok", ...}.
      kind  "app"           an Android app (.apk, or one in an .xapk or .apks bundle): "client" has inspect()'s answer
            "iphone app"    the game's iPhone app (.ipa): of no use here
            "server files"  a folder or an archive with the game's server files: "songs", "song_list" (True when one
                            comes with them), and "apps" for the clients in the same archive
            "part"          a later part of an archive split in parts: read through its first part
            "archive"       an archive with neither (it may hold another archive, which the import opens)
            "unreadable"    an archive 7-Zip cannot read: damaged, or split with a part missing
            "other"         anything else"""
    low = os.path.basename(path).lower()
    if os.path.isdir(path):
        host = host_folder(path, chosen=chosen)
        if host is None:
            return {"kind": "other", "ok": False}
        return {"kind": "server files", "ok": True, "songs": songs_in(host), "song_list": song_list_of(host) is not None,
                "apps": []}
    if low.endswith(".ipa"):
        return {"kind": "iphone app", "ok": False}
    if low.endswith(".apk"):
        info = inspect(path)
        return {"kind": "app", "ok": info["kind"] in ("original", "other server"), "client": info}
    role = archive_role(path)
    if role == "part":
        return {"kind": "part", "ok": True}
    if role != "first":
        return {"kind": "other", "ok": False}
    paths = archive_paths(path, say=False)
    if not paths:
        return {"kind": "unreadable", "ok": False}
    apps = [p for p in paths if p.lower().endswith(".apk") and not re.fullmatch(r"(?:split_)?config\..+\.apk",
                                                                             os.path.basename(p), re.I)]
    found = tree_in(paths)
    if found:
        return {"kind": "server files", "ok": True, "songs": song_count(paths, found[0]), "song_list": found[1] is not None,
                "apps": apps}
    if apps:
        # A client in an archive or a bundle: looked at as the import would, from a copy taken out.
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([SEVENZIP, "e", "-y", "-bso0", "-bsp0", f"-o{tmp}", path, apps[0]], capture_output=True)
            out = os.path.join(tmp, os.path.basename(apps[0]))
            info = inspect(out) if r.returncode == 0 and os.path.isfile(out) else {"kind": "not the game", "version": None,
                                                                                    "hosts": [], "known": False}
        return {"kind": "app", "ok": info["kind"] in ("original", "other server"), "client": info}
    return {"kind": "archive", "ok": any(archive_role(p) == "first" for p in paths)}


def check(paths, chosen=()):
    """Print what each file or folder is, one line each, and import nothing (the CLI's import --check). chosen: the
    folders chosen (host_folder's chosen)."""
    seen = set()
    for path in paths:
        # A folder and the game host's folder in it are the same files: said once (by their patch folder, which the
        # game data alone has too).
        host = host_folder(path, chosen=path in chosen) if os.path.isdir(path) else None
        if host is not None:
            if patch_of(host) in seen:
                continue
            seen.add(patch_of(host))
        w = what_is(path, chosen=path in chosen)
        name = os.path.basename(os.path.normpath(path)) or path
        if w["kind"] == "app":
            line = describe(w["client"])
        elif w["kind"] == "server files":
            line = ((f"the game's server files, {w['songs']} songs" + ("" if w["song_list"] else
                     ", no song list (made from the game's own tables)")) if w["songs"] else
                    "the game's server files without songs: the game starts, with nothing to play yet") + (
                    f", with {len(w['apps'])} app(s)" if w["apps"] else "")
        else:
            line = {"iphone app": "the iPhone app: of no use here, the Android app (.apk) is needed",
                    "part": "a part of an archive in parts: read through its first part, all parts in one folder",
                    "archive": "an archive with neither the game's app nor its server files" + (
                        " (it holds another archive, which the import opens)" if w["ok"] else ""),
                    "unreadable": "7-Zip cannot read it: damaged, or split in parts with one missing",
                    "other": "not one of the game's files"}[w["kind"]]
        log(f"{'ok  ' if w['ok'] else 'no  '} {name}: {line}")


def main():
    # Single files: compose mounts their folder and names them, "/" between several (no file name holds one). setup
    # passes the files its search matched, and nothing else in that folder.
    only = [n for n in os.environ.get("IMPORT_ONLY", "").split("/") if n]
    # A folder inside data/ (data/server, from an earlier OpenDMTQ) is read where it is, on the content's own disk.
    inside = os.environ.get("IMPORT_DATA", "")
    if inside:
        targets = [os.path.join(DATA, inside)]
    else:
        targets = [os.path.join(IN, n) for n in only] or [IN]
    # The tools run unprivileged: a folder only its owner can read looks empty, so say so instead.
    for target in targets:
        if not os.access(target, os.R_OK) or (os.path.isdir(target) and not os.access(target, os.X_OK)):
            who = f"uid {os.getuid()}" if hasattr(os, "getuid") else "this user"
            print(f"import error: cannot read {target} as {who}; "
                  "make it readable (chmod a+rX) or copy the files somewhere readable", file=sys.stderr, flush=True)
            sys.exit(2)
    candidates = targets if (only or inside) else list(walk(IN))
    if os.environ.get("IMPORT_CHECK") == "yes":
        # Only say what each one is: the files and folders that matter, not every folder walked through.
        found = [c for c in candidates if what_is(c, chosen=c in targets)["kind"] != "other"] or targets
        # Folders first, then the files by name.
        check(sorted(found, key=lambda c: (not os.path.isdir(c), os.path.basename(c).lower())), chosen=targets)
        sys.exit(0)
    # The game data unless told otherwise; the songs only when asked for.
    parts = set()
    if os.environ.get("IMPORT_GAME", "yes") != "no":
        parts.add("game")
    if os.environ.get("IMPORT_SONGS", "no") == "yes":
        parts.add("songs")
    # The clients first: they are quick, and a damaged archive among the game's files cannot keep them out.
    apks = import_apks(candidates)
    if not apks:
        log("base APK: none found (need the game's Android app, an .apk, under any file name)")
        # The iPhone app is often beside it: it cannot be used, and saying so saves looking for what is wrong with it.
        for target in targets:
            names = os.listdir(target) if os.path.isdir(target) else [os.path.basename(target)]
            for name in sorted(n for n in names if n.lower().endswith(".ipa")):
                log(f"  {name}: the iPhone app, which cannot be used: the Android app (.apk) is needed")
    found = bool(parts) and import_game_files(candidates, parts, chosen=targets)
    if parts and not found:
        log("game files: none found (looked for a folder or archive with the game host's folder, dmqglb.mb.pmang.com, "
            "and its patch/phone_new folder)")
    # Non-zero only when nothing at all was imported, so a partial import still reports cleanly.
    sys.exit(0 if found or apks else 1)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        # Exit 2 tells the CLI "something broke", as opposed to 1, "nothing found".
        print(f"import error: {e}", file=sys.stderr, flush=True)
        sys.exit(2)
