"""Tests for the song-list jacket bundles: what a shipped atlas turns into, and how rebuild() delivers it.

The template here is a small bundle made by the test, in the layout of the shipped ones (their game data
is not in the repository). A real one was checked with UnityPy and in the game; see docs/songs.md.
"""

import io
import json
import os
import struct
import tempfile
import unittest
from unittest import mock

from PIL import Image

from opendmtq_tools import jacket_atlas, songs

# Shipped atlases are 512x512 ETC2: one byte per pixel.
OLD_PIXELS = bytes(range(256)) * 1024


def _string(text):
    return jacket_atlas._aligned_string(text)


def _texture():
    # Name, width, height, image size, format, mip count; flags and settings; image; stream data.
    return (_string("d3_e33") + struct.pack("<iiiii", 512, 512, len(OLD_PIXELS), 47, 1) + bytes(40)
            + struct.pack("<I", len(OLD_PIXELS)) + OLD_PIXELS + bytes(jacket_atlas.STREAM_DATA_SIZE))


def _sprite(name):
    return _string(name) + struct.pack("<12i", 0, 363, 256, 149, *[0] * 8)


def _atlas(names):
    # GameObject pointer, enabled, script pointer, empty name, material pointer, sprites, what follows.
    head = bytes(12) + struct.pack("<I", 1) + bytes(12) + _string("") + bytes(12)
    return (head + struct.pack("<i", len(names)) + b"".join(_sprite(n) for n in names)
            + struct.pack("<f", 1.0) + bytes(12 + 4 + 4))


def _serialized(objects):
    """A Unity 5.6 serialized file: objects are (class id, bytes), without type trees."""
    classes = sorted({c for c, _ in objects})
    meta = bytearray(b"5.6.5p2\0" + struct.pack("<i", 13) + b"\0" + struct.pack("<i", len(classes)))
    for c in classes:
        meta += struct.pack("<iBh", c, 0, 0 if c == 114 else -1)
        meta += bytes(16 if c == 114 else 0) + bytes(16)
    meta += struct.pack("<i", len(objects))
    body = bytearray()
    for n, (c, raw) in enumerate(objects):
        # Table entries are aligned within the file; the metadata starts after the 20-byte header.
        meta += bytes(jacket_atlas._align(20 + len(meta)) - 20 - len(meta))
        body += bytes(jacket_atlas._align(len(body), 8) - len(body))
        meta += struct.pack("<qIIi", n + 1, len(body), len(raw), classes.index(c))
        body += raw
    data_offset = jacket_atlas._align(20 + len(meta), 16)
    pad = data_offset - 20 - len(meta)
    head = struct.pack(">IIII", len(meta), data_offset + len(body), jacket_atlas.SERIALIZED_VERSION, data_offset)
    return head + bytes(4) + bytes(meta) + bytes(pad) + bytes(body)


# A material-like object that must come through untouched.
OTHER = b"keep me as I am"


def _template():
    payload = _serialized([(21, OTHER), (28, _texture()), (114, _atlas(["e33_a", "e33_bb", "e33_ccc"]))])
    # The same form as the shipped bundles: this writer is tested against UnityPy on a real one.
    return jacket_atlas._write_bundle((6, b"5.x.x", b"5.6.5p2"), 0x43, b"CAB-" + b"0" * 32, payload)


def _jacket(size=(1024, 768)):
    """Top half red, bottom half blue."""
    im = Image.new("RGB", size, (255, 0, 0))
    im.paste((0, 0, 255), (0, size[1] // 2, size[0], size[1]))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


class NamesTest(unittest.TestCase):
    def test_names_follow_what_the_client_computes(self):
        sprite = jacket_atlas.sprite_name(1001, "my_song")
        self.assertEqual(sprite, "e1001_my_song")
        # UI3DlcSprite.SpriteNameToAtlasName: "d3_" and the text before the first underscore.
        self.assertEqual(jacket_atlas.atlas_name(1001), "d3_" + sprite.split("_")[0])
        # OnDemandTextureLoader.LoadAsset_Internal: "dlc/" + atlas + ".unity3d".
        self.assertEqual(jacket_atlas.bundle_path(1001), "dlc/d3_e1001.unity3d")


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.bundle = jacket_atlas.build(_template(), _jacket(), 1001, "mysong")
        _, _, self.node, self.data = jacket_atlas._read_bundle(self.bundle)
        self.objects, _, self.classes, _ = jacket_atlas._read_objects(self.data)

    def _of(self, class_id):
        return next(o[2] for o in self.objects if self.classes[o[1]] == class_id)

    def test_texture_is_a_256_square_of_rgba32(self):
        raw = self._of(28)
        fields = jacket_atlas._align(4 + struct.unpack_from("<I", raw, 0)[0])
        width, height, size, fmt, mips = struct.unpack_from("<iiiii", raw, fields)
        self.assertEqual((width, height, size, fmt, mips), (256, 256, 256 * 256 * 4, 4, 1))
        # The fixed fields after them are as they were; then the length and exactly that many bytes.
        self.assertEqual(raw[fields + 20:fields + 60], bytes(40))
        self.assertEqual(struct.unpack_from("<I", raw, fields + 60)[0], size)
        self.assertEqual(len(raw), fields + 64 + size + jacket_atlas.STREAM_DATA_SIZE)

    def test_tile_is_the_centre_of_the_jacket_at_the_textures_top(self):
        pixels = jacket_atlas.tile_pixels(_jacket())
        self.assertEqual(len(pixels), 256 * 256 * 4)

        def at(x, y):
            # y counts from the top as NGUI does; the bytes start at the texture's bottom row.
            i = ((255 - y) * 256 + x) * 4
            return tuple(pixels[i:i + 4])
        # A tile keeps the jacket's vertical order: red on top, blue below, opaque.
        self.assertEqual(at(10, 5), (255, 0, 0, 255))
        self.assertEqual(at(10, 140), (0, 0, 255, 255))
        # Below the tile the last row repeats, so filtering at the edge finds no black.
        self.assertEqual(at(10, 200), (0, 0, 255, 255))

    def test_atlas_lists_only_the_new_sprite_and_keeps_what_follows(self):
        raw = self._of(114)
        old = _atlas(["e33_a", "e33_bb", "e33_ccc"])
        # Same bytes up to the list, and from mPixelSize on.
        list_at = 12 + 4 + 12 + 4 + 12
        self.assertEqual(raw[:list_at], old[:list_at])
        self.assertEqual(raw[-24:], old[-24:])
        self.assertEqual(struct.unpack_from("<i", raw, list_at)[0], 1)
        self.assertEqual(raw[list_at + 4:-24], _string("e1001_mysong")
                         + struct.pack("<12i", 0, 0, 256, 149, *[0] * 8))

    def test_other_objects_stay_byte_identical(self):
        self.assertEqual(self._of(21), OTHER)

    def test_same_input_gives_the_same_bytes(self):
        # A changed checksum would have every phone download it again at each server start.
        self.assertEqual(jacket_atlas.build(_template(), _jacket(), 1001, "mysong"), self.bundle)

    def test_each_song_has_its_own_inner_file_name(self):
        # Unity refuses a second bundle whose inner file has the same name.
        other = jacket_atlas.build(_template(), _jacket(), 1002, "mysong")
        self.assertNotEqual(jacket_atlas._read_bundle(other)[2], self.node)
        self.assertTrue(self.node.startswith(b"CAB-"))
        self.assertEqual(len(self.node), 36)

    def test_another_shape_of_jacket_still_fills_the_tile(self):
        # A wide image is cut to tile proportions, not squeezed: its colours stay split at half height.
        pixels = jacket_atlas.tile_pixels(_jacket((2000, 300)))
        self.assertEqual(tuple(pixels[((255 - 5) * 256) * 4:((255 - 5) * 256) * 4 + 4]), (255, 0, 0, 255))

    def test_things_that_are_not_templates_are_refused(self):
        with self.assertRaises(jacket_atlas.AtlasError):
            jacket_atlas.build(b"not a bundle at all", _jacket(), 1001, "x")
        streamed = _texture()[:-jacket_atlas.STREAM_DATA_SIZE] + struct.pack("<III", 0, 5, 0)
        with self.assertRaises(jacket_atlas.AtlasError):
            jacket_atlas._texture_bytes(streamed, b"x" * 4)
        # An atlas whose list does not end in mPixelSize 1.0 is not one this code understands.
        with self.assertRaises((jacket_atlas.AtlasError, struct.error)):
            jacket_atlas._atlas_bytes(_atlas(["e33_a"])[:-24] + bytes(24), "e1_x")
        with self.assertRaises(jacket_atlas.AtlasError):
            jacket_atlas.tile_pixels(b"not an image")


class ContainerTest(unittest.TestCase):
    def test_stored_container_round_trip(self):
        # Type byte 2, the raw size as a varint, the bytes: the form of the shipped image bundles.
        raw = b"UnityFS" * 100
        packed = songs.stored_encode(raw)
        self.assertEqual(packed[:3], bytes([2]) + songs._put_varint(700))
        self.assertEqual(songs.lz4_decode(packed), raw)


class RebuildTest(unittest.TestCase):
    """rebuild() on a small tree: the bundle in the overlay and manifest, the sprite name in the item table."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.src = os.path.join(tmp.name, "content")
        self.custom = os.path.join(tmp.name, "custom")
        for target, value in (("CONTENT", self.src), ("CUSTOM", self.custom)):
            patcher = mock.patch.object(songs, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # One imported song, which the tables list too.
        os.makedirs(self.src)
        with open(os.path.join(self.src, "songs.json"), "w") as f:
            json.dump([{"song_id": 1, "name": "a", "song_patterns": [{"pattern_id": 1, "line": 3, "signature": 1, "difficulty": 1}]}], f)
        self.patch = songs.patch_dir(os.path.join(self.src, "web"))
        tables = {"song_song": "song_id,item_id,name,hidden_yn,track_id,mod_date\r\n1,1,a,N,1,0",
                  "song_songPattern": "pattern_id,song_id\r\n1,1",
                  "product_item": "item_id,item_name,img_url_1\r\n1,a,e10_a"}
        os.makedirs(os.path.join(self.patch, "table", "us"))
        for name, text in tables.items():
            with open(os.path.join(self.patch, "table", "us", name + ".csv.lz4"), "wb") as f:
                f.write(songs.lz4_encode(("﻿" + text).encode("utf-8")))
        with open(os.path.join(self.patch, "patch_new.csv.lz4"), "wb") as f:
            f.write(songs.lz4_encode(b"\xef\xbb\xbffile_name,file_size\r\n"))
        os.makedirs(os.path.join(self.patch, "dlc"))
        self._template_path = os.path.join(self.patch, "dlc", "d3_e33.unity3d.lz4")
        with open(self._template_path, "wb") as f:
            f.write(songs.stored_encode(_template()))
        # One added song, as _add_package leaves it.
        folder = os.path.join(self.custom, "songs", "1001")
        os.makedirs(os.path.join(folder, "patterns"))
        for name, data in (("song.fpk", b"music"), ("jacket.png", _jacket()), ("patterns/20001", b"chart")):
            with open(os.path.join(folder, name), "wb") as f:
                f.write(data)
        record = {"song_id": 1001, "name": "mysong", "has_video": False, "has_preview": False,
                  "charts": [{"pattern_id": 20001, "line": 4, "signature": 1, "difficulty": 4}]}
        record.update({k: "x" for k in songs.TEXT_FIELDS})
        with open(os.path.join(folder, "song.json"), "w") as f:
            json.dump(record, f)

    def _overlay(self, rel):
        return os.path.join(songs.patch_dir(os.path.join(self.custom, "web")), rel)

    def _item_row(self):
        with open(self._overlay("table/us/product_item.csv.lz4"), "rb") as f:
            return songs.lz4_decode(f.read()).decode("utf-8-sig").splitlines()[-1]

    def _manifest(self):
        with open(self._overlay("patch_new.csv.lz4"), "rb") as f:
            return songs.lz4_decode(f.read()).decode("utf-8-sig")

    def test_bundle_reaches_the_overlay_manifest_and_item_table(self):
        result = songs.rebuild()
        self.assertEqual(result["tile_failures"], [])
        self.assertIn("1001,mysong,e1001_mysong", self._item_row())
        with open(self._overlay("dlc/d3_e1001.unity3d.lz4"), "rb") as f:
            packed = f.read()
        # Stored like the shipped bundles, and the manifest's sizes and checksums are of these bytes.
        self.assertEqual(packed[0], 2)
        raw = songs.lz4_decode(packed)
        self.assertTrue(raw.startswith(b"UnityFS\0"))
        row = f"dlc/d3_e1001.unity3d,{len(raw)},{songs._md5(raw)},{len(packed)},{songs._md5(packed)},0,1,,,"
        self.assertIn(row, self._manifest().splitlines())

    def test_a_rebuild_does_not_change_the_bundle(self):
        songs.rebuild()
        first = self._manifest()
        songs.rebuild()
        self.assertEqual(self._manifest(), first)

    def test_without_a_template_the_song_keeps_working_without_a_tile(self):
        os.remove(self._template_path)
        result = songs.rebuild()
        self.assertEqual(len(result["tile_failures"]), 1)
        # The form a song had before bundles: an atlas that exists, without its sprite.
        self.assertIn("1001,mysong,e0_mysong", self._item_row())
        self.assertNotIn("d3_e1001", self._manifest())

    def test_removing_the_song_removes_the_bundle(self):
        songs.rebuild()
        songs.remove_song(1001)
        self.assertFalse(os.path.exists(self._overlay("dlc/d3_e1001.unity3d.lz4")))
        # Nothing added or hidden: the overlay is empty again, so the server serves the shipped files.
        self.assertFalse(os.path.exists(self._overlay("patch_new.csv.lz4")))


if __name__ == "__main__":
    unittest.main()
