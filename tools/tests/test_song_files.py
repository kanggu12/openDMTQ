"""Tests for song_files.py, on files made here in the game's layouts (no game file is needed): what passes and what is
turned away, and how songs.py uses the checks on an uploaded package and on the imported charts."""

import io
import json
import os
import struct
import tempfile
import unittest
import zipfile
from unittest import mock

from PIL import Image

from opendmtq_tools import song_files, songs


def chart(notes=((0, 1), (96, 1)), sounds=1, end=None, per_measure=192, tempo=120.0):
    """A chart in the game's layout: the sounds, one track of the given events (tick, type), the head last, as every
    chart of the game's songs is laid out."""
    # Each sound: its number, its stream flag and its file name in 64 bytes.
    body = b"".join(struct.pack("<HB64s", n + 1, 0, b"s%d.ogg" % n) for n in range(sounds))
    # Each event: its tick, its type, and 8 bytes of data (for a note, the sound it plays first).
    events = b"".join(struct.pack("<IB8s", tick, kind, b"\x01" + bytes(7)) for tick, kind in notes)
    # One track: type, name, length and event count, then its events.
    body += struct.pack("<H64sII", 0, b"track", 0, len(notes)) + events
    last = max([tick for tick, kind in notes if kind == song_files.NOTE] or [0])
    # The head: sound and track counts, ticks a measure, tempo, a tick, the play time, the end tick, the events.
    head = struct.pack("<3HfIfII", sounds, 1, per_measure, tempo, last, 1.0, last if end is None else end, len(notes))
    # The first word, the head's place, the body, the head.
    return struct.pack("<II", 0, 8 + len(body)) + body + head


def fpk(entries=(("bgm.ogg", b"OggS" + bytes(60)),)):
    """A music pack in the game's layout: the 28-byte head, the entries' data, the 144-byte table entries last."""
    data = b"".join(d for _, d in entries)
    table = song_files.FPK_HEAD + len(data)
    out = struct.pack("<7I", 4096, 3, len(data), len(data), table, len(entries), 1) + data
    at = song_files.FPK_HEAD
    for name, d in entries:
        out += struct.pack("<4I128s", at, len(d), len(d), len(name), name.encode())
        at += len(d)
    return out


def jacket():
    """A small PNG for jacket.png."""
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (0, 0, 255)).save(out, "PNG")
    return out.getvalue()


WEBM = song_files.WEBM + bytes(28)
OPUS = b"OggS" + bytes(24) + b"OpusHead" + bytes(11)


class FilesTest(unittest.TestCase):
    """The checks, one file at a time."""

    def test_files_in_the_game_layouts_pass(self):
        self.assertIsNone(song_files.fpk_problem(fpk()))
        self.assertIsNone(song_files.chart_problem(chart()))
        self.assertTrue(song_files.chart_readable(chart()))
        self.assertIsNone(song_files.video_problem(WEBM))
        self.assertIsNone(song_files.preview_problem(OPUS))

    def test_a_pack_the_game_cannot_read_is_named(self):
        good = fpk()
        self.assertEqual(song_files.fpk_problem(b""), ("song.fpk_format", {}))
        # Cut short: the table runs past the end.
        self.assertEqual(song_files.fpk_problem(good[:-1]), ("song.fpk_format", {}))
        # An entry whose data would start inside the table.
        moved = bytearray(good)
        struct.pack_into("<I", moved, song_files.FPK_HEAD + 64, len(good))
        self.assertEqual(song_files.fpk_problem(bytes(moved)), ("song.fpk_format", {}))
        # A sound that is no Ogg, named.
        self.assertEqual(song_files.fpk_problem(fpk((("bgm.ogg", b"RIFF" + bytes(60)),))),
                         ("song.fpk_sound", {"name": "'bgm.ogg'"}))
        # Images and text only: no sound to play.
        self.assertEqual(song_files.fpk_problem(fpk((("cover.png", b"\x89PNG" + bytes(8)),))),
                         ("song.fpk_no_sounds", {}))

    def test_images_and_text_in_a_pack_are_left_as_they_are(self):
        # The game's own packs carry a few of them beside the sounds.
        self.assertIsNone(song_files.fpk_problem(fpk((("bgm.ogg", b"OggS" + bytes(60)), ("cover.png", b"\x89PNG"),
                                                      ("notes.txt", b"text")))))

    def test_a_chart_the_game_cannot_load_is_named(self):
        good = chart()
        self.assertEqual(song_files.chart_problem(b""), ("song.chart_format", {}))
        # Cut short, as two of the game's own charts are: the head is past the end.
        self.assertEqual(song_files.chart_problem(good[:-1]), ("song.chart_format", {}))
        # A head that counts a track more than there is: the tracks would run into the head.
        more = bytearray(good)
        struct.pack_into("<H", more, struct.unpack_from("<I", good, 4)[0] + 2, 2)
        self.assertEqual(song_files.chart_problem(bytes(more)), ("song.chart_format", {}))
        for data in (b"", good[:-1], bytes(more)):
            self.assertFalse(song_files.chart_readable(data))

    def test_a_chart_that_loads_but_cannot_be_played_is_named(self):
        # Only a tempo change: nothing to play.
        self.assertEqual(song_files.chart_problem(chart(notes=((0, 3),))), ("song.chart_no_notes", {}))
        self.assertEqual(song_files.chart_problem(chart(per_measure=0)), ("song.chart_timing", {}))
        self.assertEqual(song_files.chart_problem(chart(tempo=0.0)), ("song.chart_timing", {}))
        self.assertEqual(song_files.chart_problem(chart(tempo=float("nan"))), ("song.chart_timing", {}))
        # The end before the last note: the game would stop the song first.
        self.assertEqual(song_files.chart_problem(chart(end=50)), ("song.chart_ends_early", {}))
        # They load all the same: the imported charts' quick check is about loading only.
        self.assertTrue(song_files.chart_readable(chart(notes=((0, 3),))))

    def test_an_end_tick_of_0_means_the_tick(self):
        # The head's tick is the last note's here.
        self.assertIsNone(song_files.chart_problem(chart(end=0)))

    def test_a_video_or_preview_of_another_kind_is_named(self):
        self.assertEqual(song_files.video_problem(b"\x00\x00\x00\x18ftypmp42"), ("song.video_format", {}))
        self.assertEqual(song_files.preview_problem(b"OggS" + bytes(24) + b"\x01vorbis"), ("song.preview_format", {}))
        self.assertEqual(song_files.preview_problem(b"ID3\x04"), ("song.preview_format", {}))


class PackageTest(unittest.TestCase):
    """add_package turns a package away for its files before anything is written, and takes one whose files pass."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        for target in ("CONTENT", "CUSTOM"):
            patcher = mock.patch.object(songs, target, os.path.join(tmp.name, target.lower()))
            patcher.start()
            self.addCleanup(patcher.stop)

    def package(self, **files):
        """A package with a good song.json, song.fpk, jacket.png and one chart, files replaced or added by name."""
        meta = {"name": "mysong", "full_name": "My Song",
                "charts": [{"line": 5, "signature": 1, "difficulty": 4, "file": "patterns/4l_normal"}]}
        members = {"song.json": json.dumps(meta).encode(), "song.fpk": fpk(), "jacket.png": jacket(),
                   "patterns/4l_normal": chart()}
        members.update(files)
        path = os.path.join(self.tmp, "song.zip")
        with zipfile.ZipFile(path, "w") as z:
            for name, data in members.items():
                z.writestr(name, data)
        return path

    def refused(self, key, **files):
        with self.assertRaises(songs.SongError) as caught:
            songs.add_package(self.package(**files))
        self.assertEqual(caught.exception.key, key)
        # Nothing of the song was written.
        self.assertFalse(os.path.exists(os.path.join(songs.CUSTOM, "songs")) and
                         os.listdir(os.path.join(songs.CUSTOM, "songs")))
        return caught.exception

    def test_each_file_is_checked_and_named(self):
        self.refused("song.fpk_format", **{"song.fpk": b"OggS" + bytes(100)})
        e = self.refused("song.chart_format", **{"patterns/4l_normal": b"not a chart"})
        self.assertEqual(e.values["name"], "'patterns/4l_normal'")
        self.refused("song.chart_ends_early", **{"patterns/4l_normal": chart(end=10)})
        self.refused("song.video_format", **{"song.webm": b"\x00\x00\x00\x18ftypmp42" + bytes(8)})
        self.refused("song.preview_format", **{"preview.opus": b"ID3\x04" + bytes(40)})

    def test_a_package_whose_files_pass_is_added(self):
        # The rebuild is another test's: here, what the package leaves.
        with mock.patch.object(songs, "rebuild"):
            record = songs.add_package(self.package(**{"song.webm": WEBM, "preview.opus": OPUS}))
        folder = os.path.join(songs.CUSTOM, "songs", str(record["song_id"]))
        with open(os.path.join(folder, "patterns", str(record["charts"][0]["pattern_id"])), "rb") as f:
            self.assertEqual(f.read(), chart())
        self.assertTrue(record["has_video"] and record["has_preview"])


class RepairTest(unittest.TestCase):
    """rebuild() serves an imported chart the game cannot load from its pair, and says which."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for target in ("CONTENT", "CUSTOM"):
            patcher = mock.patch.object(songs, target, os.path.join(tmp.name, target.lower()))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.patterns = os.path.join(songs.CONTENT, "web", "DMQ", "Patterns")
        os.makedirs(self.patterns)
        charts = [{"pattern_id": n, "line": 3, "signature": n, "difficulty": 1} for n in (1, 2, 3)]
        with open(os.path.join(songs.CONTENT, "songs.json"), "w") as f:
            json.dump([{"song_id": 1, "name": "a", "song_patterns": charts}], f)
        # 1: empty, its earphone pair fine. 2: both cut short. 3: both fine.
        for name, data in (("1", b""), ("1_EARPHONE", chart()), ("2", chart()[:-3]), ("2_EARPHONE", chart()[:20]),
                           ("3", chart()), ("3_EARPHONE", chart())):
            with open(os.path.join(self.patterns, name), "wb") as f:
                f.write(data)

    def test_a_chart_is_served_from_its_pair_and_the_rest_said(self):
        result = songs.rebuild()
        self.assertEqual(result["charts_from_pair"], ["1"])
        self.assertEqual(result["charts_unreadable"], ["2", "2_EARPHONE"])
        overlay = os.path.join(songs.CUSTOM, "web", "DMQ", "Patterns")
        with open(os.path.join(overlay, "1"), "rb") as f:
            self.assertEqual(f.read(), chart())
        # Only the repaired chart is in the overlay; the imported ones are served as they are.
        self.assertEqual(os.listdir(overlay), ["1"])


if __name__ == "__main__":
    unittest.main()
