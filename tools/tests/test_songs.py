"""Tests for the client table round trip: decode, rewrite, re-encode without changing shipped rows; and for rebuild() on a
made-up library: what it writes, one rebuild at a time, and the added songs' tiles made once."""

import csv
import io
import json
import multiprocessing
import os
import shutil
import tempfile
import unittest
from unittest import mock

from PIL import Image

from opendmtq_tools import jacket_atlas, songs
from tests import test_jacket_atlas as tja
from tests.test_jacket_atlas import _jacket, _template


class Lz4Test(unittest.TestCase):
    def test_container_round_trip(self):
        raw = ("﻿song_id,name\r\n1,paperplanes\r\n" * 50).encode("utf-8")
        packed = songs.lz4_encode(raw)
        # Type byte 3, then two varints, then the block.
        self.assertEqual(packed[0], 3)
        self.assertEqual(songs.lz4_decode(packed), raw)

    def test_bad_container_is_refused(self):
        with self.assertRaises(songs.SongError):
            songs.lz4_decode(b"\x01\x00\x00")


class CsvTest(unittest.TestCase):
    def test_unchanged_rows_stay_byte_identical(self):
        # Shipped tables: BOM, CRLF, a quoted field with a comma.
        text = '﻿song_id,name,visualized_by\r\n1,paperplanes,Ann Lee\r\n2,neonrain,"Kim, Park"\r\n'
        header, rows = songs._table_rows(text)
        out = songs._csv_text(header, rows, songs._eol(text), text.endswith("\n")).decode("utf-8")
        self.assertEqual(out, text)
        # Without a final line break, as the shipped files are.
        bare = text.rstrip("\r\n")
        out = songs._csv_text(*songs._table_rows(bare), songs._eol(bare), bare.endswith("\n")).decode("utf-8")
        self.assertEqual(out, bare)

    def test_added_song_gets_a_product_like_a_shipped_free_song(self):
        # The shipped tables' header, and a shipped free song's product row as the model.
        header = ["product_id", "item_id", "platform_product_id", "store_product_id", "product_type",
                  "cost_game_point", "cost_game_cash", "status", "sale_start_date", "sale_end_date", "update"]
        self.assertEqual(songs._product_row(header, 1001),
                         ["2001001", "1001", "2001001", "", "I", "1", "0", "N", "", "", "0"])

    def test_added_song_is_listed_in_the_music_shop_categories(self):
        header = ["category_id", "product_id", "display_order", "update"]
        self.assertEqual(songs._category_rows(header, 1001),
                         [["3", "2001001", "0", "0"], ["103", "2001001", "0", "0"]])

    def test_appended_row_uses_the_same_line_endings(self):
        text = "﻿a,b\r\n1,2\r\n"
        header, rows = songs._table_rows(text)
        rows.append(["3", "x,y"])
        out = songs._csv_text(header, rows, songs._eol(text), True).decode("utf-8")
        self.assertTrue(out.endswith('3,"x,y"\r\n'))
        self.assertEqual(list(csv.reader(io.StringIO(out.lstrip("﻿"))))[-1], ["3", "x,y"])


class GameFilesTest(unittest.TestCase):
    """The game's own files the import left out. Without the image bundles of its screens the game stops at its first start
    and says nothing (tried on an emulator): the owner has to hear of it. A song's files may well be missing, and the
    fonts for Chinese are not needed to start."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src, custom = os.path.join(tmp.name, "content"), os.path.join(tmp.name, "custom")
        for target, value in (("CONTENT", src), ("CUSTOM", custom)):
            patcher = mock.patch.object(songs, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        os.makedirs(src)
        with open(os.path.join(src, "songs.json"), "w", encoding="utf-8") as f:
            json.dump([], f)
        self.patch = songs.patch_dir(os.path.join(src, "web"))
        os.makedirs(os.path.join(self.patch, "dlc"))
        names = ["dlc/d3_a0.unity3d", "dlc/d_sk01.unity3d", "dlc/d3_e5.unity3d", "dlc/d_e5.unity3d", "preview/a.p.opus",
                 "Fonts/SimplifiedChinese/a.unity3d"]
        manifest = "file_name,file_size\r\n" + "\r\n".join(f"{n},1" for n in names)
        with open(os.path.join(self.patch, "patch_new.csv.lz4"), "wb") as f:
            f.write(songs.lz4_encode(("\ufeff" + manifest).encode("utf-8")))
        # Of the game's own bundles, only the skin came.
        self.bundle("dlc/d_sk01.unity3d")

    def bundle(self, rel):
        with open(os.path.join(self.patch, rel + ".lz4"), "wb") as f:
            f.write(songs.stored_encode(b"UnityFS"))

    def test_the_screens_left_out_are_named_and_the_songs_and_fonts_are_not(self):
        self.assertEqual(songs.rebuild()["missing_game_files"], ["dlc/d3_a0.unity3d"])
        self.assertEqual(songs.missing_game_files(), ["dlc/d3_a0.unity3d"])

    def test_with_all_of_them_nothing_is_named(self):
        self.bundle("dlc/d3_a0.unity3d")
        songs.rebuild()
        self.assertEqual(songs.missing_game_files(), [])


# ------------------------------------------------------------------------------ a made-up library

# The client tables' columns, in the order the client's own tables have them (only the names the code reads matter).
SONG_HEADER = ["song_id", "item_id", "name", "full_name", "genre", "artist_name", "original_bga_yn", "loop_bga_yn",
               "composed_by", "singer", "feat_by", "arranged_by", "visualized_by", "cost_game_point", "cost_game_cash",
               "flag", "status", "free_yn", "hidden_yn", "open_yn", "track_id", "mod_date", "update"]
PATTERN_HEADER = ["pattern_id", "song_id", "signature", "line", "difficulty", "point_type", "point_value", "flg", "update"]
ITEM_HEADER = ["item_id", "item_name", "img_url_1", "img_url_2", "description", "repeat_count", "item_type", "limit_minute",
               "status", "buy_level", "buy_limit_count", "buy_limit_type", "summary", "update"]
PRODUCT_HEADER = ["product_id", "item_id", "platform_product_id", "store_product_id", "product_type", "cost_game_point",
                  "cost_game_cash", "status", "sale_start_date", "sale_end_date", "update"]
CATEGORY_HEADER = ["category_id", "product_id", "display_order", "update"]
DESC_HEADER = ["song_id", "fullname", "genre", "artist", "composed_by", "singer", "feat_by", "arranged_by", "visualized_by"]

# The made-up songs the tables list, by id: name, title, charts (pattern id, line, signature, difficulty, point type,
# point value). 1 and 5 are among the songs whose charts can cost MAX POINT (songs.POINT_SONGS); 5 is listed by the
# tables but not imported, 2 is imported and hidden.
LISTED = {1: ("made_one", "Made Up One", [(101, 3, 1, 3, 0, 0), (102, 5, 3, 12, 1, 300)]),
          2: ("made_two", "Made Up Two", [(201, 4, 2, 7, 0, 0)]),
          5: ("made_five", "Made Up Five", [(501, 5, 3, 13, 1, 500)])}
IMPORTED = (1, 2)
HIDDEN = [2]
# Items besides the songs': one every player owns, a package (owned by none), one the official server never handed out
# (songs.NOT_OWNED), and the level unlock (songs.UNLOCK_PRODUCT), each with a product of its own.
OTHER_ITEMS = [("30001", "made_coin", "C"), ("40001", "made_pack", "P"), ("39001", "made_partner", "C"), ("80002", "made_unlock", "U")]
# The language folders, and the one the catalog reads (the first by name).
LOCALES = ("us", "kr")
# The added song, as add_package() leaves it: its folder's song.json.
ADDED = {"song_id": 1001, "name": "made_added", "has_video": False, "has_preview": True,
         "charts": [{"pattern_id": 20001, "line": 3, "signature": 1, "difficulty": 4},
                    {"pattern_id": 20002, "line": 4, "signature": 2, "difficulty": 9}],
         "full_name": "Made Up Added", "genre": "Pop", "artist_name": "Nobody", "composed_by": "Nobody", "singer": "",
         "feat_by": "", "arranged_by": "", "visualized_by": ""}


def _table_files(header, rows, eol="\r\n", final=False):
    """A client table as the client's patch folder has it: a byte-order mark, its line endings, no final one unless asked."""
    return songs._csv_text(header, [[str(v) for v in r] for r in rows], eol, final)


def made_up_tables(loc):
    """Every client table of one language folder, by its path in the patch folder: {rel: bytes}."""
    song_rows, pattern_rows, desc_rows = [], [], []
    for sid, (name, title, charts) in LISTED.items():
        # Track ids are a numbering of their own (11, 12, 15): an added song's continues after the highest of them.
        song_rows.append([sid, sid, name, title, "Pop", "Nobody", "N", "N", "", "", "", "", "", 0, 0, 0, "", "Y", "N", "Y",
                          10 + sid, "20200101", 0])
        pattern_rows += [[pid, sid, sig, line, diff, ptype, pvalue, "Y", 0] for pid, line, sig, diff, ptype, pvalue in charts]
        desc_rows.append([sid, f"{title} ({loc})", "Pop", "Nobody", "", "", "", "", ""])
    items = [[sid, name, f"e1_{name}", "", "", 0, "S", 0, "N", 0, 1, "F", title, 0] for sid, (name, title, _) in LISTED.items()]
    items += [[iid, name, "", "", "", 0, kind, 0, "N", 0, 1, "F", "", 0] for iid, name, kind in OTHER_ITEMS]
    # Each item's product: 1,000,000 + item for the songs, the item's own id for the others (as the unlock's is).
    products = [[1000000 + int(r[0]) if r[6] == "S" else r[0], r[0], 1000000 + int(r[0]), "", "I", 1, 0, "N", "", "", 0] for r in items]
    categories = [[cat, p[0], 0, 0] for p in products if str(p[1]).isdigit() and int(p[1]) in LISTED for cat in ("3", "103")]
    categories.append(["7", "80002", 0, 0])
    return {f"table/{loc}/song_song.csv": _table_files(SONG_HEADER, song_rows),
            # One table with line feeds and a final one, as some languages' are: kept as it is by the rewrite.
            f"table/{loc}/song_songPattern.csv": _table_files(PATTERN_HEADER, pattern_rows, *(("\n", True) if loc == "kr" else ())),
            f"table/{loc}/product_item.csv": _table_files(ITEM_HEADER, items),
            f"table/{loc}/product_product.csv": _table_files(PRODUCT_HEADER, products),
            f"table/{loc}/category_categoryproduct.csv": _table_files(CATEGORY_HEADER, categories),
            f"table/{loc}/song_desc_{loc}.csv": _table_files(DESC_HEADER, desc_rows)}


def made_up_library(content, custom):
    """A made-up library in content/ (the import) and custom/ (one added song, one hidden): client tables in two language
    folders, a manifest, a tile template, a song's preview and tiles and a screen of the game. Returns the content's patch
    folder."""
    songs_json = [{"song_id": sid, "name": LISTED[sid][0], "full_name": LISTED[sid][1], "hidden_yn": "N",
                   "song_patterns": [{"pattern_id": c[0], "line": c[1], "signature": c[2], "difficulty": c[3]} for c in LISTED[sid][2]]}
                  for sid in IMPORTED]
    os.makedirs(content)
    with open(os.path.join(content, "songs.json"), "w", encoding="utf-8") as f:
        json.dump(songs_json, f)
    with mock.patch.object(songs, "CONTENT", content), mock.patch.object(songs, "CUSTOM", custom):
        patch = songs.patch_dir(os.path.join(content, "web"))
    files = {}
    for loc in LOCALES:
        files.update(made_up_tables(loc))
    # The game's own bundles, a song's preview and tile, and the template the added songs' tiles are made from: stored
    # as the shipped image bundles are.
    files.update({"dlc/d_ui0.unity3d": b"UnityFS made screen", "preview/made_one.p.opus": b"OggS made preview",
                  "dlc/d3_e1.unity3d": b"UnityFS made tiles", songs.TILE_TEMPLATE: _template()})
    for rel, raw in files.items():
        os.makedirs(os.path.dirname(os.path.join(patch, rel)), exist_ok=True)
        with open(os.path.join(patch, rel + ".lz4"), "wb") as f:
            f.write(songs.stored_encode(raw) if rel.startswith("dlc/") else songs.lz4_encode(raw))
    # One table also plain beside its .lz4, as some patch folders have: the overlay writes both.
    with open(os.path.join(patch, "table/us/song_desc_us.csv"), "wb") as f:
        f.write(files["table/us/song_desc_us.csv"])
    # The manifest names every one of them, the files of the song not imported (its preview and tile) and a screen the
    # import did not bring. In the form the client data's has: no byte-order mark, CRLF, a final one.
    names = sorted(files) + ["preview/made_five.p.opus", "dlc/d3_e5.unity3d", "dlc/d_ui1.unity3d"]
    manifest = "file_name,file_size,checksum,compressed_file_size,compressed_checksum,acquire_on_demand,compressed,platform,tag,\r\n"
    manifest += "".join(f"{rel},1,x,1,x,0,1,,,\r\n" for rel in names)
    with open(os.path.join(patch, "patch_new.csv.lz4"), "wb") as f:
        f.write(songs.lz4_encode(manifest.encode("utf-8")))
    # The added song and the hidden one.
    folder = os.path.join(custom, "songs", str(ADDED["song_id"]))
    os.makedirs(os.path.join(folder, "patterns"))
    for rel, raw in (("song.fpk", b"made music"), ("jacket.png", _jacket()), ("preview.opus", b"OggS made added preview"),
                     ("patterns/20001", b"made chart one"), ("patterns/20002", b"made chart two")):
        with open(os.path.join(folder, rel), "wb") as f:
            f.write(raw)
    with open(os.path.join(folder, "song.json"), "w", encoding="utf-8") as f:
        json.dump(ADDED, f)
    with open(os.path.join(custom, "hidden.json"), "w", encoding="utf-8") as f:
        json.dump(HIDDEN, f)
    return patch


class LibraryCase(unittest.TestCase):
    """A test on the made-up library, in a folder of its own: songs.CONTENT and songs.CUSTOM point at it meanwhile."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.content, self.custom = os.path.join(tmp.name, "content"), os.path.join(tmp.name, "custom")
        self.patch = made_up_library(self.content, self.custom)
        for target, value in (("CONTENT", self.content), ("CUSTOM", self.custom)):
            patcher = mock.patch.object(songs, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def overlay(self, rel=""):
        """A path in the overlay's patch folder."""
        return os.path.join(songs.patch_dir(os.path.join(self.custom, "web")), rel)


# ------------------------------------------------------------------------------ one rebuild at a time

def _rebuild_rounds(content, custom, rounds, out):
    """In a process of its own: rebuild() on the library rounds times, and what failed to out."""
    # A spawned process starts without the test's patches: the library's folders are set here.
    songs.CONTENT, songs.CUSTOM = content, custom
    failed = []
    for _ in range(rounds):
        try:
            songs.rebuild()
        except Exception as e:  # noqa: BLE001 - every failure counts here
            failed.append(f"{type(e).__name__}: {e}")
    out.put(failed)


class OneRebuildAtATimeTest(LibraryCase):
    """A rebuild builds the overlay aside (web.new) and swaps it in: two at once, as a start's or an import's rebuild while
    the admin pages add or hide a song, would build in the same folder and swap each other's half out. Every rebuild
    takes the songs' lock, once."""

    def counting_locks(self):
        """filelock.lock as it is, counted."""
        return mock.patch.object(songs.filelock, "lock", side_effect=songs.filelock.lock)

    def test_a_rebuild_called_directly_takes_the_lock_once(self):
        with self.counting_locks() as lock:
            songs.rebuild()
        # Once for the whole rebuild, not once per file it places in the overlay (or not at all).
        self.assertEqual(lock.call_count, 1)

    def test_a_change_that_rebuilds_takes_it_once_too(self):
        with self.counting_locks() as lock:
            songs.set_hidden(1, True)
        self.assertEqual(lock.call_count, 1)

    def test_a_restore_puts_the_songs_back_and_rebuilds_under_one_lock(self):
        # A backup's custom folder: no added song, song 1 hidden, ids handed out up to 1003.
        backup = os.path.join(self.custom, "..", "backup")
        os.makedirs(os.path.join(backup, "songs"))
        with open(os.path.join(backup, "hidden.json"), "w", encoding="utf-8") as f:
            json.dump([1], f)
        with open(os.path.join(backup, "ids.json"), "w", encoding="utf-8") as f:
            json.dump({"song": 1003, "pattern": 20010}, f)
        with self.counting_locks() as lock:
            self.assertIsNone(songs.put_back(backup))
        self.assertEqual(lock.call_count, 1)
        # The backup's flags and ids, no added song any more, and the song list made for them.
        self.assertEqual(songs.hidden(), {1})
        self.assertEqual(os.listdir(os.path.join(self.custom, "songs")), [])
        with open(os.path.join(self.custom, "songList.json"), encoding="utf-8") as f:
            listed = {s["song_id"]: s["hidden_yn"] for s in json.load(f)}
        self.assertEqual(listed, {1: "Y", 2: "N"})

    def test_a_restore_says_why_the_list_was_not_made_and_keeps_the_songs(self):
        backup = os.path.join(self.custom, "..", "backup")
        shutil.copytree(os.path.join(self.custom, "songs"), os.path.join(backup, "songs"))
        with mock.patch.object(songs, "rebuild", side_effect=OSError("no client data")):
            self.assertEqual(songs.put_back(backup), "no client data")
        self.assertTrue(os.path.isfile(os.path.join(self.custom, "songs", "1001", "song.json")))

    def test_two_processes_rebuilding_at_once_both_get_through(self):
        # Two processes, as the admin service and a start's `python -m opendmtq_tools.songs` are, several rounds each.
        spawn = multiprocessing.get_context("spawn")
        out = spawn.Queue()
        # Six rounds each: on the code before, enough for some of them to fail in every run (3 runs of 3).
        workers = [spawn.Process(target=_rebuild_rounds, args=(self.content, self.custom, 6, out)) for _ in range(2)]
        for w in workers:
            w.start()
        # Each one's list of failures, whichever ends first; one that hangs fails the test instead of hanging it.
        failed = [e for _ in workers for e in out.get(timeout=120)]
        for w in workers:
            w.join(timeout=30)
        self.assertEqual(failed, [])
        # The overlay is whole, with nothing left of a build beside it.
        self.assertTrue(os.path.isfile(self.overlay("patch_new.csv.lz4")))
        self.assertEqual(sorted(n for n in os.listdir(self.custom) if n.startswith("web.")), [])


# ------------------------------------------------------------------------------ what a rebuild writes

class RebuildOutputTest(LibraryCase):
    """What rebuild() makes of the made-up library for phones and the game server: the client's tables in both language
    folders (the song not imported out, the added one in, the hidden one flagged), the manifest with the new files' sizes
    and checksums and without the files the server lacks, the song list and catalog.json."""

    def setUp(self):
        super().setUp()
        self.result = songs.rebuild()

    def written(self, rel, root=None):
        """A file of the overlay (or of the patch folder root) unpacked from its .lz4, as text with its byte-order mark."""
        with open(os.path.join(root or self.overlay(), rel + ".lz4"), "rb") as f:
            return songs.lz4_decode(f.read()).decode("utf-8")

    def text(self, rel):
        """A table of the overlay as phones get it, decoded from its .lz4."""
        return self.written(rel).lstrip("﻿")

    def column(self, rel, name):
        """One column of an overlay table, row by row."""
        header, rows = songs._table_rows(self.text(rel))
        return [r[header.index(name)] for r in rows]

    def row(self, rel, key, value):
        """The row of an overlay table whose column key is value, by column name."""
        header, rows = songs._table_rows(self.text(rel))
        return next(dict(zip(header, r)) for r in rows if r[header.index(key)] == value)

    def test_the_song_table_has_the_imported_songs_the_added_one_and_the_hidden_flag(self):
        for loc in LOCALES:
            rel = f"table/{loc}/song_song.csv"
            with self.subTest(loc):
                # Song 5 was listed but not imported: its row goes. 2 stays, hidden.
                self.assertEqual(self.column(rel, "song_id"), ["1", "2", "1001"])
                self.assertEqual(self.column(rel, "hidden_yn"), ["N", "Y", "N"])
                added = self.row(rel, "song_id", "1001")
                # Numbered after the highest track of the table as shipped (15, the song taken out), dated as its last row.
                self.assertEqual((added["item_id"], added["name"], added["full_name"], added["track_id"], added["mod_date"]),
                                 ("1001", "made_added", "Made Up Added", "16", "20200101"))
                self.assertEqual((added["free_yn"], added["open_yn"], added["original_bga_yn"]), ("Y", "Y", "N"))
                # The rows kept are byte for byte the shipped ones, in the shipped form: a byte-order mark, CRLF, no final break.
                written, shipped = self.written(rel), self.written(rel, root=self.patch)
                self.assertTrue(written.startswith("﻿"))
                self.assertEqual(written.split("\r\n")[:2], shipped.split("\r\n")[:2])
                self.assertFalse(written.endswith("\n"))
                # The hidden song's row differs in its flag alone.
                ours, theirs = written.split("\r\n")[2].split(","), shipped.split("\r\n")[2].split(",")
                flag = SONG_HEADER.index("hidden_yn")
                self.assertEqual((ours[:flag] + ours[flag + 1:], theirs[flag], ours[flag]), (theirs[:flag] + theirs[flag + 1:], "N", "Y"))

    def test_the_chart_table_keeps_every_row_and_gains_the_added_charts(self):
        for loc in LOCALES:
            rel = f"table/{loc}/song_songPattern.csv"
            with self.subTest(loc):
                # The client refuses an empty chart table: the song not imported keeps its chart rows (501), never offered.
                self.assertEqual(self.column(rel, "pattern_id"), ["101", "102", "201", "501", "20001", "20002"])
                added = self.row(rel, "pattern_id", "20002")
                self.assertEqual([added[h] for h in PATTERN_HEADER], ["20002", "1001", "2", "4", "9", "0", "0", "Y", "0"])
        # The language folder whose table has line feeds and a final one keeps them.
        written = self.written("table/kr/song_songPattern.csv")
        self.assertTrue(written.endswith("\n"))
        self.assertNotIn("\r", written)

    def test_the_items_products_and_categories_lose_the_song_not_imported_and_gain_the_added_one(self):
        for loc in LOCALES:
            with self.subTest(loc):
                items = f"table/{loc}/product_item.csv"
                # Song 5's item goes; every other item stays, the added song's comes last with its tile's sprite.
                self.assertEqual(self.column(items, "item_id"), ["1", "2", "30001", "40001", "39001", "80002", "1001"])
                added = self.row(items, "item_id", "1001")
                self.assertEqual((added["item_name"], added["img_url_1"], added["item_type"], added["summary"]),
                                 ("made_added", "e1001_made_added", "S", "Made Up Added"))
                # Its product goes with it, and the added song's comes in the form of a free song's.
                products = f"table/{loc}/product_product.csv"
                self.assertEqual(self.column(products, "product_id"),
                                 ["1000001", "1000002", "30001", "40001", "39001", "80002", "2001001"])
                self.assertEqual(songs._table_rows(self.text(products))[1][-1], songs._product_row(PRODUCT_HEADER, 1001))
                # The music shop's categories list the products there are, the added one in both.
                categories = f"table/{loc}/category_categoryproduct.csv"
                header, rows = songs._table_rows(self.text(categories))
                self.assertEqual([(r[0], r[1]) for r in rows],
                                 [("3", "1000001"), ("103", "1000001"), ("3", "1000002"), ("103", "1000002"), ("7", "80002"),
                                  ("3", "2001001"), ("103", "2001001")])

    def test_the_song_descriptions_follow_the_song_table(self):
        for loc in LOCALES:
            rel = f"table/{loc}/song_desc_{loc}.csv"
            with self.subTest(loc):
                self.assertEqual(self.column(rel, "song_id"), ["1", "2", "1001"])
                self.assertEqual(self.row(rel, "song_id", "1001")["fullname"], "Made Up Added")
        # Where the content has the table plain beside its .lz4, the overlay has both, the same.
        with open(self.overlay("table/us/song_desc_us.csv"), "rb") as f:
            self.assertEqual(f.read().decode("utf-8-sig"), self.text("table/us/song_desc_us.csv"))
        self.assertFalse(os.path.exists(self.overlay("table/kr/song_desc_kr.csv")))

    def test_the_manifest_has_every_written_files_sizes_and_checksums_and_not_what_the_server_lacks(self):
        manifest = self.written("patch_new.csv")
        # The content's form: its header first, CRLF, a final one.
        self.assertTrue(manifest.startswith("file_name,"))
        self.assertTrue(manifest.endswith(",\r\n"))
        lines = manifest[:-2].split("\r\n")
        names = [ln.split(",", 1)[0] for ln in lines[1:]]
        # The song not imported, its preview and tile, and the screen the import lacks are not offered.
        for gone in ("preview/made_five.p.opus", "dlc/d3_e5.unity3d", "dlc/d_ui1.unity3d"):
            self.assertNotIn(gone, names)
        self.assertEqual(self.result["missing_game_files"], ["dlc/d_ui1.unity3d"])
        # What did not change keeps its line as the content has it.
        for kept in ("dlc/d_ui0.unity3d", "preview/made_one.p.opus", "dlc/d3_e1.unity3d", songs.TILE_TEMPLATE):
            self.assertIn(f"{kept},1,x,1,x,0,1,,,", lines)
        # Every file written: the six tables of each language folder, the added song's tile and preview.
        tables = [f"table/{loc}/{t}.csv" for loc in LOCALES
                  for t in ("song_song", "song_songPattern", "product_item", "product_product", "category_categoryproduct", f"song_desc_{loc}")]
        self.assertEqual(self.result["client_files"], sorted(tables + ["dlc/d3_e1001.unity3d", "preview/made_added.p.opus"]))
        for rel in self.result["client_files"]:
            with self.subTest(rel):
                with open(self.overlay(rel + ".lz4"), "rb") as f:
                    packed = f.read()
                raw = songs.lz4_decode(packed)
                # Its sizes and checksums are of the bytes phones get, packed and unpacked.
                self.assertIn(f"{rel},{len(raw)},{songs._md5(raw)},{len(packed)},{songs._md5(packed)},0,1,,,", lines)
        # The lines kept stay in the content's order (the made-up manifest's is by name), each once; the new files' come
        # last.
        kept = sorted([*made_up_tables("us"), *made_up_tables("kr"), "dlc/d_ui0.unity3d", "preview/made_one.p.opus",
                       "dlc/d3_e1.unity3d", songs.TILE_TEMPLATE])
        self.assertEqual(names, kept + ["dlc/d3_e1001.unity3d", "preview/made_added.p.opus"])

    def test_the_catalog_is_of_the_tables_as_phones_get_them(self):
        with open(os.path.join(self.custom, "catalog.json"), encoding="utf-8") as f:
            catalog = json.load(f)
        # Song 1's chart that costs MAX POINT; song 5's is not counted, as the server has not got the song.
        self.assertEqual(catalog["point_charts"], [{"pattern_id": 102, "song_id": 1, "point_type": 1, "point_value": 300}])
        # Every item a player owns: neither songs, nor packages, nor those never handed out.
        self.assertEqual(catalog["items"], [30001, 80002])
        # The level unlock's product, its keys in the order the client reads them, numbers as numbers.
        self.assertEqual(list(catalog["unlock_product"].items()), [
            ("product_id", 80002), ("platform_product_id", 1080002), ("store_product_id", ""), ("product_type", "I"),
            ("cost_game_point", 1), ("cost_game_cash", 0), ("item_id", 80002), ("item_name", "made_unlock"),
            ("img_url_1", ""), ("img_url_2", ""), ("summary", ""), ("description", ""), ("repeat_count", 0),
            ("item_type", "U"), ("limit_minute", 0), ("status", "N"), ("buy_level", 0), ("buy_limit_count", 1),
            ("buy_limit_type", "F"), ("reg_date", ""), ("sale_start_date", ""), ("sale_end_date", ""), ("display_order", 0)])

    def test_the_song_list_and_the_added_songs_files(self):
        with open(os.path.join(self.custom, "songList.json"), encoding="utf-8") as f:
            listed = json.load(f)
        self.assertEqual([(s["song_id"], s["hidden_yn"]) for s in listed], [(1, "N"), (2, "Y"), (1001, "N")])
        self.assertEqual(listed[-1]["song_patterns"], [{k: c[k] for k in ("pattern_id", "line", "difficulty", "signature")}
                                                        for c in ADDED["charts"]])
        # The added song's files in the overlay, as the game asks for them, are its own (a chart twice: with earphones too).
        folder = os.path.join(self.custom, "songs", "1001")
        web = os.path.join(self.custom, "web")
        for theirs, ours in (("DMQ/Songs/1001/1001.fpk", "song.fpk"), ("DMQ/Patterns/20001", "patterns/20001"),
                             ("DMQ/Patterns/20001_EARPHONE", "patterns/20001"), ("DMQ/Patterns/20002_EARPHONE", "patterns/20002"),
                             ("viewImg/eye/made_added.png", "jacket.png")):
            with self.subTest(theirs):
                with open(os.path.join(web, theirs), "rb") as a, open(os.path.join(folder, ours), "rb") as b:
                    self.assertEqual(a.read(), b.read())
        # And its picture for the web pages.
        self.assertTrue(os.path.isfile(os.path.join(self.custom, "thumbs", "made_added.jpg")))


# ------------------------------------------------------------------------------ tiles made once

def _plain_jacket(colour):
    """A jacket of one colour, at the game's size: a tile unlike _jacket()'s."""
    out = io.BytesIO()
    Image.new("RGB", (1024, 768), colour).save(out, "PNG")
    return out.getvalue()


class KeptTileTest(LibraryCase):
    """An added song's tile bundle is made once and kept in its folder under the key of what it is made from: later
    rebuilds (every start, and every add, hide or removal) take it from there, byte for byte, and make it again only for
    a new jacket, template or way of making it. The template is read once a rebuild."""

    def setUp(self):
        super().setUp()
        # A second added song beside the library's, with a jacket of its own.
        folder = os.path.join(self.custom, "songs", "1002")
        os.makedirs(os.path.join(folder, "patterns"))
        for rel, raw in (("song.fpk", b"made music two"), ("jacket.png", _plain_jacket((0, 160, 0))), ("patterns/20003", b"made chart three")):
            with open(os.path.join(folder, rel), "wb") as f:
                f.write(raw)
        meta = dict(ADDED, song_id=1002, name="made_second", full_name="Made Up Second", has_preview=False,
                    charts=[{"pattern_id": 20003, "line": 3, "signature": 1, "difficulty": 4}])
        with open(os.path.join(folder, "song.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f)

    def building(self):
        """jacket_atlas.build as it is, counted: one call per bundle made."""
        return mock.patch.object(songs.jacket_atlas, "build", side_effect=songs.jacket_atlas.build)

    @staticmethod
    def made(build):
        """The song ids of the bundles build made, in order."""
        return [c.args[2] for c in build.call_args_list]

    def served(self):
        """Each added song's bundle in the overlay, as phones download it."""
        out = {}
        for sid in (1001, 1002):
            with open(self.overlay(f"dlc/d3_e{sid}.unity3d.lz4"), "rb") as f:
                out[sid] = f.read()
        return out

    def kept(self, sid):
        """The tiles kept in a song's folder, by name."""
        return sorted(n for n in os.listdir(os.path.join(self.custom, "songs", str(sid))) if n.startswith("tile-"))

    def test_a_second_rebuild_makes_no_bundle_and_serves_the_same_bytes(self):
        with self.building() as build:
            songs.rebuild()
        self.assertEqual(self.made(build), [1001, 1002])
        first = self.served()
        with open(self.overlay("patch_new.csv.lz4"), "rb") as f:
            manifest = f.read()
        # Each kept once, the bytes phones get.
        for sid in (1001, 1002):
            self.assertEqual(len(self.kept(sid)), 1)
            with open(os.path.join(self.custom, "songs", str(sid), self.kept(sid)[0]), "rb") as f:
                self.assertEqual(f.read(), songs.lz4_decode(first[sid]))
        with self.building() as build, mock.patch.object(songs, "_tile_template", side_effect=songs._tile_template) as read:
            songs.rebuild()
        # Nothing made again; the template read once, not once per song.
        self.assertEqual(self.made(build), [])
        self.assertEqual(read.call_count, 1)
        # And phones are told of nothing new.
        self.assertEqual(self.served(), first)
        with open(self.overlay("patch_new.csv.lz4"), "rb") as f:
            self.assertEqual(f.read(), manifest)

    def test_a_new_jacket_makes_that_songs_bundle_again_and_only_it(self):
        songs.rebuild()
        before, kept_before = self.served(), self.kept(1002)
        with open(os.path.join(self.custom, "songs", "1002", "jacket.png"), "wb") as f:
            f.write(_plain_jacket((200, 0, 200)))
        with self.building() as build:
            songs.rebuild()
        self.assertEqual(self.made(build), [1002])
        after = self.served()
        self.assertEqual(after[1001], before[1001])
        self.assertNotEqual(after[1002], before[1002])
        # Kept in place of the one before, which goes.
        self.assertEqual(len(self.kept(1002)), 1)
        self.assertNotEqual(self.kept(1002), kept_before)

    def test_a_song_named_anew_gets_a_bundle_with_its_new_sprite(self):
        songs.rebuild()
        # Its song.json changed by hand: the sprite inside the bundle must be the name the item table now gives.
        path = os.path.join(self.custom, "songs", "1002", "song.json")
        with open(path, encoding="utf-8") as f:
            meta = json.load(f)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict(meta, name="made_renamed"), f)
        with self.building() as build:
            songs.rebuild()
        self.assertEqual([c.args[2:] for c in build.call_args_list], [(1002, "made_renamed")])

    def test_a_new_template_makes_every_bundle_again(self):
        songs.rebuild()
        # The same layout, with another object beside the texture and the atlas.
        other = jacket_atlas._write_bundle((6, b"5.x.x", b"5.6.5p2"), 0x43, b"CAB-" + b"1" * 32, tja._serialized(
            [(21, b"another material"), (28, tja._texture()), (114, tja._atlas(["e33_a"]))]))
        with open(os.path.join(self.patch, songs.TILE_TEMPLATE + ".lz4"), "wb") as f:
            f.write(songs.stored_encode(other))
        with self.building() as build:
            songs.rebuild()
        self.assertEqual(self.made(build), [1001, 1002])

    def test_another_way_of_making_them_makes_every_bundle_again(self):
        songs.rebuild()
        # An OpenDMTQ whose jacket_atlas.py differs, if only by a line: its bundles may differ too.
        maker = os.path.join(self.custom, "..", "jacket_atlas.py")
        with open(songs.jacket_atlas.__file__, "rb") as src, open(maker, "wb") as dst:
            dst.write(src.read() + b"\n# another version\n")
        with self.building() as build, mock.patch.object(songs.jacket_atlas, "__file__", maker):
            songs.rebuild()
        self.assertEqual(self.made(build), [1001, 1002])

    def test_a_tile_that_cannot_be_kept_is_served_all_the_same(self):
        with mock.patch.object(songs, "_keep_tile", side_effect=OSError("read-only folder")):
            result = songs.rebuild()
            self.assertEqual(result["tile_failures"], [])
            self.assertEqual(sorted(self.served()), [1001, 1002])
            # Nothing kept: the next rebuild makes them again, as before there was keeping.
            with self.building() as build:
                songs.rebuild()
        self.assertEqual(self.made(build), [1001, 1002])
        self.assertEqual(self.kept(1001), [])


if __name__ == "__main__":
    unittest.main()
