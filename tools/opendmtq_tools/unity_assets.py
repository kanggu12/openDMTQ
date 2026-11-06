"""Small in-place edits to the game's Unity asset files: hide a UI object, move a UI object.

The game's screens are prefabs in hash-named files under assets/bin/Data, each one a Unity 5.6
"SerializedFile". A menu entry that leads nowhere on this server is taken off by clearing the
active flag of its GameObject, and the entries around it are moved up by changing their Transform's
local position. Neither changes a single byte's position in the file, so nothing else in it needs
to be rewritten. Only the two object types needed here are read: GameObject and Transform.

The layouts below are those of file format 17 (Unity 5.6), the only one the game uses:
  file header (big endian): metadata size, file size, format, data offset, endianness byte, 3 reserved
  metadata: version text, platform, type-tree flag, types, objects (each aligned to 4)
  GameObject: component count, (file id int32, path id int64) each, layer, name, tag, active flag
  Transform: GameObject (file id, path id), rotation (4 floats), position (3), scale (3), children,
             parent (file id, path id)
"""

import struct

# Unity's numbers for the two types read here, and the only format they were checked against.
CLASS_GAME_OBJECT = 1
CLASS_TRANSFORM = 4
CLASS_MONO_BEHAVIOUR = 114
FORMAT = 17
# Offset of the position inside a Transform: GameObject reference (4 + 8) and rotation (4 * 4).
POSITION_OFFSET = 12 + 16


class AssetError(ValueError):
    """The file is not what this reader understands, or the object is not in it."""


class _Reader:
    """Little-endian reads over the metadata, with Unity's four-byte alignment."""

    def __init__(self, data, pos):
        self.data = data
        self.pos = pos

    def read(self, fmt):
        # One value of a struct format, advancing past it.
        size = struct.calcsize(fmt)
        value = struct.unpack_from("<" + fmt, self.data, self.pos)[0]
        self.pos += size
        return value

    def skip(self, count):
        self.pos += count

    def text(self):
        # A null-terminated string (only the Unity version in the metadata).
        end = self.data.index(b"\0", self.pos)
        value = self.data[self.pos:end]
        self.pos = end + 1
        return value

    def align(self, base=0):
        # To the next multiple of four, counted from base.
        self.pos += -(self.pos - base) % 4


class SerializedFile:
    """One asset file: its objects' places, and the UI objects by their path in the hierarchy."""

    def __init__(self, data):
        # A private, writable copy: edits land here, and tobytes() hands the result back.
        self.data = bytearray(data)
        self.objects = list(self._read_objects())
        self._index_hierarchy()

    def _read_objects(self):
        """(path id, absolute offset, size, Unity class number) of every object in the file."""
        if len(self.data) < 20:
            raise AssetError("too short to be an asset file")
        meta_size, file_size, fmt, data_offset = struct.unpack_from(">IIII", self.data, 0)
        if fmt != FORMAT or file_size != len(self.data) or self.data[16] != 0 or data_offset > file_size:
            raise AssetError(f"not a format {FORMAT} little-endian asset file")
        meta = _Reader(self.data, 20)
        meta.text()
        meta.skip(4)
        if meta.read("B"):
            raise AssetError("type trees are not expected in the game's own files")
        classes = []
        for _ in range(meta.read("i")):
            class_id = meta.read("i")
            meta.skip(1 + 2)
            # MonoBehaviours also carry their script's hash, every type its own hash.
            meta.skip((16 if class_id == CLASS_MONO_BEHAVIOUR else 0) + 16)
            classes.append(class_id)
        for _ in range(meta.read("i")):
            meta.align()
            path_id = meta.read("q")
            start = meta.read("I")
            size = meta.read("I")
            type_index = meta.read("i")
            if type_index < 0 or type_index >= len(classes) or data_offset + start + size > file_size:
                raise AssetError("object table does not fit the file")
            yield path_id, data_offset + start, size, classes[type_index]

    def _game_object(self, offset, size):
        """(name, offset of the active flag) of the GameObject stored at offset."""
        count = struct.unpack_from("<i", self.data, offset)[0]
        # Component list, then the layer.
        pos = offset + 4 + count * 12 + 4
        length = struct.unpack_from("<i", self.data, pos)[0]
        name = bytes(self.data[pos + 4:pos + 4 + length]).decode("utf-8", "replace")
        # Name padded to four bytes, then the two-byte tag.
        pos += 4 + length
        pos += -(pos - offset) % 4
        active = pos + 2
        if count < 0 or length < 0 or active >= offset + size:
            raise AssetError("a GameObject does not fit its place")
        return name, active

    def _index_hierarchy(self):
        """Names, parents and active flags, then each object's full path from its prefab's root."""
        names = {}
        active_at = {}
        owners = {}
        parents = {}
        position_at = {}
        for path_id, offset, size, class_id in self.objects:
            if class_id == CLASS_GAME_OBJECT:
                names[path_id], active_at[path_id] = self._game_object(offset, size)
            elif class_id == CLASS_TRANSFORM:
                owners[path_id] = struct.unpack_from("<q", self.data, offset + 4)[0]
                count_at = offset + POSITION_OFFSET + 12 + 12
                count = struct.unpack_from("<i", self.data, count_at)[0]
                parents[path_id] = struct.unpack_from("<q", self.data, count_at + 4 + count * 12 + 4)[0]
                position_at[owners[path_id]] = offset + POSITION_OFFSET
        self._active_at = {}
        self._position_at = {}
        for transform, owner in owners.items():
            parts = []
            seen = set()
            current = transform
            while current in owners and current not in seen:
                seen.add(current)
                parts.append(names.get(owners[current], "?"))
                current = parents.get(current, 0)
            path = "/".join(reversed(parts))
            # The same path twice (some prefabs repeat a name) would make an edit ambiguous.
            if path in self._active_at:
                self._active_at[path] = None
                continue
            if owner in active_at:
                self._active_at[path] = active_at[owner]
                self._position_at[path] = position_at[owner]

    def _place(self, table, path):
        place = table.get(path)
        if place is None:
            raise AssetError(f"no single object at {path}")
        return place

    def is_active(self, path):
        return bool(self.data[self._place(self._active_at, path)])

    def position(self, path):
        return struct.unpack_from("<fff", self.data, self._place(self._position_at, path))

    def hide(self, path):
        """Clear the object's active flag: it and everything under it are left out of the screen."""
        self.data[self._place(self._active_at, path)] = 0

    def move(self, path, x=None, y=None):
        """A new local position; an axis left out stays as it is."""
        place = self._place(self._position_at, path)
        old = struct.unpack_from("<fff", self.data, place)
        struct.pack_into("<fff", self.data, place, old[0] if x is None else x, old[1] if y is None else y, old[2])

    def tobytes(self):
        return bytes(self.data)


def apply(data, edits):
    """The file with the edits made. An edit is ("hide", path), ("move", path, x, y), or either with " if there" for an
    object only some versions of the game have; raises AssetError."""
    asset = SerializedFile(data)
    for edit in edits:
        if edit[0] == "hide":
            asset.hide(edit[1])
        elif edit[0] == "hide if there":
            if asset._active_at.get(edit[1]) is not None:
                asset.hide(edit[1])
        elif edit[0] == "move if there":
            if asset._position_at.get(edit[1]) is not None:
                asset.move(edit[1], x=edit[2], y=edit[3])
        elif edit[0] == "move":
            asset.move(edit[1], x=edit[2], y=edit[3])
        else:
            raise AssetError(f"unknown edit {edit[0]}")
    return asset.tobytes()


def build(objects):
    """A minimal asset file for the tests: objects are (path id, name, parent's path id or 0, active, (x, y)).

    Every object is written as a GameObject (its path id) and a Transform (its path id + 1000000).
    """
    body = bytearray()
    table = []
    offset_id = 1000000

    def place(path_id, type_index, blob):
        # Objects start on eight-byte boundaries in real files; the reader only needs the table.
        body.extend(b"\0" * (-len(body) % 8))
        table.append((path_id, len(body), len(blob), type_index))
        body.extend(blob)

    for path_id, name, parent, active, position in objects:
        encoded = name.encode()
        blob = struct.pack("<i", 1) + struct.pack("<iq", 0, path_id + offset_id) + struct.pack("<i", 5)
        blob += struct.pack("<i", len(encoded)) + encoded + b"\0" * (-len(encoded) % 4)
        blob += struct.pack("<HB", 0, 1 if active else 0) + b"\0"
        place(path_id, 0, blob)
        children = [o[0] + offset_id for o in objects if o[2] == path_id]
        blob = struct.pack("<iq", 0, path_id) + struct.pack("<ffff", 0, 0, 0, 1)
        blob += struct.pack("<fff", position[0], position[1], 0) + struct.pack("<fff", 1, 1, 1)
        blob += struct.pack("<i", len(children)) + b"".join(struct.pack("<iq", 0, c) for c in children)
        blob += struct.pack("<iq", 0, parent + offset_id if parent else 0)
        place(path_id + offset_id, 1, blob)

    meta = bytearray(b"5.6.5p2\0" + struct.pack("<i", 13) + b"\0")
    meta += struct.pack("<i", 2)
    for class_id in (CLASS_GAME_OBJECT, CLASS_TRANSFORM):
        meta += struct.pack("<i", class_id) + b"\0" + struct.pack("<h", -1) + b"\0" * 16
    meta += struct.pack("<i", len(table))
    for path_id, start, size, type_index in table:
        # Aligned from the start of the file, as the reader's positions are.
        meta += b"\0" * (-(20 + len(meta)) % 4)
        meta += struct.pack("<qIIi", path_id, start, size, type_index)
    data_offset = 20 + len(meta)
    data_offset += -data_offset % 16
    total = data_offset + len(body)
    header = struct.pack(">IIII", len(meta), total, FORMAT, data_offset) + b"\0\0\0\0"
    return header + bytes(meta) + b"\0" * (data_offset - 20 - len(meta)) + bytes(body)
