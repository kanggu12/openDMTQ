"""Tests for the in-place IL2CPP literal editor, on synthetic metadata built with the real layout."""

import struct
import unittest

from opendmtq_tools import il2cpp


class Il2cppTest(unittest.TestCase):
    def test_replace_shrinks_only_the_target(self):
        # Three literals back to back, the middle one is edited.
        data = il2cpp.build(["before", "https://dmqglb.mb.pmang.com/DMQ/rpc", "after"])
        m = il2cpp.Metadata(data)
        m.replace("https://dmqglb.mb.pmang.com/DMQ/rpc", "http://10.0.0.5/DMQ/rpc")
        # Re-read from bytes, as the game would.
        out = il2cpp.Metadata(m.tobytes())
        self.assertEqual(out.literal(1), b"http://10.0.0.5/DMQ/rpc")
        # Neighbours untouched and the file size unchanged.
        self.assertEqual(out.literal(0), b"before")
        self.assertEqual(out.literal(2), b"after")
        self.assertEqual(len(m.tobytes()), len(data))

    def test_longer_replacement_is_appended_and_later_sections_shift(self):
        data = il2cpp.build(["one", "http://pmangplus.com", "three"], tail=b"TAILDATA")
        m = il2cpp.Metadata(data)
        m.replace("http://pmangplus.com", "http://192.168.219.100")
        out = m.tobytes()
        o = il2cpp.Metadata(out)
        # The long literal reads back whole; the others are unchanged.
        self.assertEqual(o.literal(1), b"http://192.168.219.100")
        self.assertEqual([o.literal(0), o.literal(2)], [b"one", b"three"])
        # The section after the literal data moved and its header offset followed it.
        tail_off, tail_size = struct.unpack_from("<ii", out, il2cpp.HEADER.size)
        self.assertEqual(out[tail_off:tail_off + tail_size], b"TAILDATA")
        # Growth is padded to 8 bytes so alignment is kept.
        self.assertEqual((len(out) - len(data)) % 8, 0)

    def test_missing_or_duplicate_literal_is_refused(self):
        m = il2cpp.Metadata(il2cpp.build(["a", "a"]))
        # Duplicate: ambiguous.
        with self.assertRaises(il2cpp.MetadataError):
            m.replace("a", "b")
        # Missing: a different client build.
        with self.assertRaises(il2cpp.MetadataError):
            m.replace("zzz", "y")

    def test_every_copy_of_a_literal_is_replaced(self):
        # A client changed by hand: both RPC literals of the original now hold the same text.
        m = il2cpp.Metadata(il2cpp.build(["a", "http://play.example.net/DMQ/rpc", "http://play.example.net/DMQ/rpc", "b"]))
        self.assertEqual(m.replace_all("http://play.example.net/DMQ/rpc", "http://10.0.0.5/DMQ/rpc"), 2)
        out = il2cpp.Metadata(m.tobytes())
        self.assertEqual([out.literal(i) for i in range(4)], [b"a", b"http://10.0.0.5/DMQ/rpc", b"http://10.0.0.5/DMQ/rpc", b"b"])
        with self.assertRaises(il2cpp.MetadataError):
            m.replace_all("not there", "x")

    def test_entries_sharing_one_text_are_edited_together(self):
        # Two entries that point at the same bytes are one literal: replaced once, both entries follow.
        data = bytearray(il2cpp.build(["http://h.example/api", "zz"]))
        lit_off = il2cpp.HEADER.size + 8
        length, index = struct.unpack_from("<Ii", data, lit_off)
        struct.pack_into("<Ii", data, lit_off + 8, length, index)
        m = il2cpp.Metadata(bytes(data))
        self.assertEqual(m.replace_all("http://h.example/api", "http://10.0.0.5/api"), 2)
        out = il2cpp.Metadata(m.tobytes())
        self.assertEqual([out.literal(0), out.literal(1)], [b"http://10.0.0.5/api", b"http://10.0.0.5/api"])

    def test_shared_bytes_are_refused(self):
        # Literal 1 points into the middle of literal 0; editing 0 would change 1.
        data = bytearray(il2cpp.build(["abcdef", "xy"]))
        lit_off = il2cpp.HEADER.size + 8
        struct.pack_into("<Ii", data, lit_off + 8, 2, 2)
        m = il2cpp.Metadata(bytes(data))
        with self.assertRaises(il2cpp.MetadataError):
            m.replace("abcdef", "zz")

    def test_rejects_non_metadata_and_unknown_versions(self):
        with self.assertRaises(il2cpp.MetadataError):
            il2cpp.Metadata(b"\0" * 64)
        with self.assertRaises(il2cpp.MetadataError):
            il2cpp.Metadata(il2cpp.build(["x"], version=31))


if __name__ == "__main__":
    unittest.main()
