"""Edits of string literals in a Unity IL2CPP global-metadata.dat.

Literals are stored back to back without terminators; a table of (length, offset) entries is the
only thing that says where one ends. Two ways to replace one:

  * not longer: write the new bytes over the start of the old ones and shrink the length entry.
    Nothing moves.
  * longer: append the new bytes to the end of the literal data and point the entry there. Every
    section after the literal data moves by the same padded amount, and the header offsets of those
    sections are shifted to match. Cross references inside sections are indexes, not file offsets,
    so nothing else changes.
"""

import struct

# Magic number at the start of every IL2CPP metadata file.
SANITY = 0xFAB11BAF
# Versions whose literal entries are (uint32 length, int32 data index) with the header layout below.
# Unity 5.3 through 2020.x; the Technika Q 1.3.4 client ships version 23.
SUPPORTED_VERSIONS = range(16, 29)
# sanity, version, stringLiteralOffset, stringLiteralSize, stringLiteralDataOffset, stringLiteralDataSize
HEADER = struct.Struct("<Iiiiii")
# One literal table entry.
ENTRY = struct.Struct("<Ii")


class MetadataError(Exception):
    """The file is not metadata this module can edit safely."""


class Metadata:
    """A global-metadata.dat held in memory, with its literal table decoded."""

    def __init__(self, data):
        # Mutable copy; edits go straight into it.
        self.data = bytearray(data)
        # Too short to even hold the header.
        if len(self.data) < HEADER.size:
            raise MetadataError("file too short for an IL2CPP header")
        sanity, self.version, lit_off, lit_size, self.dat_off, dat_size = HEADER.unpack_from(self.data, 0)
        # Not IL2CPP metadata at all.
        if sanity != SANITY:
            raise MetadataError(f"bad sanity {sanity:#x}, not IL2CPP metadata")
        # A layout this code was not written for.
        if self.version not in SUPPORTED_VERSIONS:
            raise MetadataError(f"unsupported metadata version {self.version}")
        # Both regions must lie inside the file.
        if lit_off + lit_size > len(self.data) or self.dat_off + dat_size > len(self.data):
            raise MetadataError("literal table or data runs past the end of the file")
        self.lit_off = lit_off
        # End of the original literal data: where appended literals go.
        self.dat_end = self.dat_off + dat_size
        # The header runs up to the first section, which in these versions is the literal table.
        self.header_end = lit_off
        first = min(struct.unpack_from("<i", self.data, pos)[0] for pos in range(8, lit_off, 8))
        if first != lit_off or (lit_off - 8) % 8:
            raise MetadataError("unexpected header layout: the literal table is not the first section")
        # Longer replacements waiting to be appended, and their bytes so far.
        self.appended = bytearray()
        # (length, absolute start) for every literal, in table order.
        self.entries = []
        for i in range(lit_size // ENTRY.size):
            length, index = ENTRY.unpack_from(self.data, lit_off + i * ENTRY.size)
            self.entries.append((length, self.dat_off + index))

    def literal(self, i):
        """Bytes of literal i."""
        length, start = self.entries[i]
        return bytes(self.data[start:start + length])

    def find(self, text):
        """Indexes of every literal exactly equal to text."""
        b = text.encode("utf-8")
        return [i for i, (length, start) in enumerate(self.entries)
                if length == len(b) and self.data[start:start + length] == b]

    def replace(self, old, new):
        """Replace the single literal equal to old with new. Returns its index."""
        hits = self.find(old)
        # Zero means a different client build; more than one means the edit would be ambiguous.
        if len(hits) != 1:
            raise MetadataError(f"literal {old!r}: expected exactly 1, found {len(hits)}")
        self._replace_at(hits, old.encode("utf-8"), new.encode("utf-8"))
        return hits[0]

    def replace_all(self, old, new):
        """Replace every literal equal to old with new: a client changed by hand may hold the same text twice, where the
        original had two different ones. Returns how many."""
        hits = self.find(old)
        if not hits:
            raise MetadataError(f"literal {old!r}: not in this file")
        # Entries that point at the same bytes are one literal: edited once, together.
        same = {}
        for i in hits:
            same.setdefault(self.entries[i][1], []).append(i)
        for group in same.values():
            self._replace_at(group, old.encode("utf-8"), new.encode("utf-8"))
        return len(hits)

    def _replace_at(self, group, old_b, new_b):
        """Replace the literal the entries in group all point at (bytes old_b) with new_b."""
        # Longer text cannot overwrite in place: queue it for the end of the literal data.
        if len(new_b) > len(old_b):
            index = (self.dat_end - self.dat_off) + len(self.appended)
            self.appended += new_b
            for i in group:
                struct.pack_into("<Ii", self.data, self.lit_off + i * ENTRY.size, len(new_b), index)
                self.entries[i] = (len(new_b), self.dat_off + index)
            return
        _, start = self.entries[group[0]]
        # Another literal sharing any of these bytes would change too; refuse rather than corrupt it.
        end = start + len(old_b)
        for j, (length, other) in enumerate(self.entries):
            if j not in group and length and other < end and start < other + length:
                raise MetadataError(f"literal {old_b.decode('utf-8')!r} shares bytes with literal {j}; cannot edit in place")
        # New text over the start of the old; the tail is never read again.
        self.data[start:start + len(new_b)] = new_b
        # Shrink the length entries so the game reads only the new text.
        for i in group:
            struct.pack_into("<I", self.data, self.lit_off + i * ENTRY.size, len(new_b))
            self.entries[i] = (len(new_b), start)

    def tobytes(self):
        """The edited file, with any appended literals spliced in and later sections shifted."""
        if not self.appended:
            return bytes(self.data)
        # Pad to 8 bytes so every following section keeps its alignment.
        block = bytes(self.appended) + b"\0" * (-len(self.appended) % 8)
        out = bytearray(self.data[:self.dat_end] + block + self.data[self.dat_end:])
        # Header is (offset, size) pairs after sanity and version, up to the first section.
        for pos in range(8, self.header_end, 8):
            off, size = struct.unpack_from("<ii", out, pos)
            if off >= self.dat_end:
                # A section after the literal data: it moved by the block size.
                struct.pack_into("<i", out, pos, off + len(block))
            elif off == self.dat_off:
                # The literal data itself grew.
                struct.pack_into("<i", out, pos + 4, size + len(block))
        return bytes(out)


def build(literals, version=23, tail=b"TAILDATA"):
    """Make a small metadata file: literals, then one more section (used by the tests)."""
    # Literal bytes back to back, and their (length, index) entries.
    blob, table = b"", b""
    for s in literals:
        b = s.encode("utf-8")
        table += ENTRY.pack(len(b), len(blob))
        blob += b
    # Header with three sections (table, data, tail), then the sections in that order.
    lit_off = HEADER.size + 8
    dat_off = lit_off + len(table)
    tail_off = dat_off + len(blob)
    header = HEADER.pack(SANITY, version, lit_off, len(table), dat_off, len(blob))
    header += struct.pack("<ii", tail_off, len(tail))
    return header + table + blob + tail
