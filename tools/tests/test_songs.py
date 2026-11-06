"""Tests for the client table round trip: decode, rewrite, re-encode without changing shipped rows."""

import csv
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from opendmtq_tools import songs


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


if __name__ == "__main__":
    unittest.main()
