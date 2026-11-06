"""An added song's jacket in the song list: a one-sprite NGUI atlas bundle the client already knows how to load.

How the game finds a tile's image (Technika Q 1.3.4, libil2cpp):

    product_item.img_url_1            the sprite name, for example e33_uad (ItemInfo.ImageSelectedName)
    text before the first "_"         e33
    UI3DlcSprite.AtlasPrefix + that   the atlas name, d3_e33 (UI3DlcSprite.SpriteNameToAtlasName)
    "dlc/" + atlas + ".unity3d"       a file in the phone's patch folder, opened with WWW("file://...")
                                      (OnDemandTextureLoader.LoadAsset_Internal)

Nothing in that chain lists the atlases: any name works if the patch manifest delivered the file, and
the loader takes whatever UIAtlas component the bundle holds, by type. So an added song gets its own
bundle, dlc/d3_e<song id>.unity3d, and the sprite name e<song id>_<name>. Song ids are never reused and
start above the shipped atlas numbers (0 to 33), so no name meets a shipped one.

The bundle is a shipped jacket atlas with two objects rewritten: the texture and the atlas's sprite list.
Reusing one keeps the parts OpenDMTQ cannot produce itself (the compiled shader, the material and the
type information), and needs no Unity tooling: only the file formats below are touched, by hand, so
the tools image needs nothing new. The template comes from the server's own read-only tree, at run time.

The texture is uncompressed RGBA32 where the shipped atlases use ETC2: every GPU reads it, and the
tools image has no ETC2 encoder. The bundle is LZMA packed like the shipped ones, so it stays smaller
than they are (about 30 KB for a 1024x768 jacket); on the phone the texture takes 256 KB of memory.
"""

import hashlib
import io
import lzma
import struct

import lz4.block

# Tile size in the shipped atlases (every sprite in them measures this). The game scales it to the slot.
TILE_WIDTH = 256
TILE_HEIGHT = 149
# Smallest power-of-two square holding one tile: the shipped atlases are square powers of two too.
TEXTURE_SIZE = 256
# Unity's TextureFormat.RGBA32.
FORMAT_RGBA32 = 4
# Unity class ids of the two objects rewritten.
CLASS_TEXTURE2D = 28
CLASS_MONOBEHAVIOUR = 114
# Serialized file format of Unity 5.6, the only one this code can read. Anything else is refused.
SERIALIZED_VERSION = 17
# Block flags of the shipped bundles: LZMA (1) in the streamed form (0x40).
BLOCK_FLAGS = 0x41
# LZMA settings of the shipped bundles' first bytes: properties byte 0x5D means lc 3, lp 0, pb 2.
LZMA_PROPS = 0x5D
LZMA_DICT = 0x80000
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA1, "lc": 3, "lp": 0, "pb": 2, "dict_size": LZMA_DICT}]
# Size of the fields after the image bytes in Texture2D: m_StreamData's offset, size and empty path.
STREAM_DATA_SIZE = 12


class AtlasError(Exception):
    """The template is not a bundle of the expected shape, or the jacket cannot be read."""


def atlas_name(song_id):
    """The atlas an added song's sprite resolves to, as UI3DlcSprite.SpriteNameToAtlasName computes it."""
    return f"d3_e{song_id}"


def sprite_name(song_id, name):
    """The sprite name for product_item.img_url_1. The client cuts it at the first "_" for the atlas."""
    return f"e{song_id}_{name}"


def bundle_path(song_id):
    """The bundle's path in the patch folder and manifest, without the .lz4 the server stores it with."""
    return f"dlc/{atlas_name(song_id)}.unity3d"


# ------------------------------------------------------------------------------ small readers

def _cstring(data, i):
    """Read a zero-terminated string at i; returns (bytes, next index)."""
    end = data.index(0, i)
    return data[i:end], end + 1


def _align(i, to=4):
    """The next multiple of `to` at or after i."""
    return (i + to - 1) & ~(to - 1)


def _aligned_string(text):
    """A Unity serialized string: little-endian length, UTF-8 bytes, padded to four."""
    raw = text.encode("utf-8")
    out = struct.pack("<I", len(raw)) + raw
    return out + b"\0" * (_align(len(out)) - len(out))


# ------------------------------------------------------------------------------ UnityFS container

def _lzma_unpack(chunk, raw_size):
    """A Unity LZMA block: a properties byte, a 32-bit dictionary size, the raw stream."""
    props, dict_size = struct.unpack_from("<BI", chunk, 0)
    # lc + 9 * (lp + 5 * pb) in one byte.
    pb, rest = divmod(props, 45)
    lp, lc = divmod(rest, 9)
    filters = [{"id": lzma.FILTER_LZMA1, "lc": lc, "lp": lp, "pb": pb, "dict_size": dict_size}]
    # The stream may end without a marker: ask for the known size and stop there.
    return lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters).decompress(chunk[5:], max_length=raw_size)


def _read_bundle(data):
    """The one serialized file in a UnityFS bundle: returns (header strings, flags, node name, file bytes).

    Layout, big-endian: signature, format version, two version strings, total size, the block info's
    packed and raw sizes, flags, the packed block info, then the blocks. Block info: a 16-byte hash,
    the block table, the node table.
    """
    try:
        signature, i = _cstring(data, 0)
        if signature != b"UnityFS":
            raise AtlasError("the template is not a UnityFS bundle")
        version = struct.unpack_from(">I", data, i)[0]
        i += 4
        player, i = _cstring(data, i)
        engine, i = _cstring(data, i)
        # The total size is not needed to read; it is written anew.
        _, packed_info, raw_info, flags = struct.unpack_from(">qIII", data, i)
        i += 20
        # Shipped bundles keep the block info right after the header, LZ4 packed (flags 0x43).
        if flags != 0x43:
            raise AtlasError(f"unexpected bundle flags {flags:#x}")
        info = lz4.block.decompress(data[i:i + packed_info], uncompressed_size=raw_info)
        i += packed_info
        # Blocks after the 16-byte hash: raw size, packed size, flags.
        count = struct.unpack_from(">I", info, 16)[0]
        p = 20
        blocks = []
        for _ in range(count):
            blocks.append(struct.unpack_from(">IIH", info, p))
            p += 10
        joined = bytearray()
        for raw_size, packed_size, block_flags in blocks:
            chunk = data[i:i + packed_size]
            i += packed_size
            # Low bits: 0 is stored, 1 is LZMA (shipped atlases), 2 and 3 are LZ4.
            method = block_flags & 0x3F
            if method == 1:
                joined += _lzma_unpack(chunk, raw_size)
            elif method == 0:
                joined += chunk
            elif method in (2, 3):
                joined += lz4.block.decompress(chunk, uncompressed_size=raw_size)
            else:
                raise AtlasError(f"unexpected block flags {block_flags:#x}")
        # A jacket atlas holds exactly one file: the serialized assets.
        nodes = struct.unpack_from(">I", info, p)[0]
        if nodes != 1:
            raise AtlasError(f"expected one file in the template, found {nodes}")
        p += 4 + 20
        node_name, _ = _cstring(info, p)
    except (struct.error, ValueError, lzma.LZMAError, lz4.block.LZ4BlockError) as e:
        raise AtlasError(f"the template bundle cannot be read: {e}")
    return (version, player, engine), flags, node_name, bytes(joined)


def _write_bundle(strings, flags, node_name, payload):
    """A UnityFS bundle holding `payload` as one file, in the form the shipped jacket atlases have."""
    version, player, engine = strings
    # One LZMA block in the shipped streamed form: five bytes of settings, then the raw stream.
    packed = struct.pack("<BI", LZMA_PROPS, LZMA_DICT) + lzma.compress(payload, format=lzma.FORMAT_RAW, filters=LZMA_FILTERS)
    # All-zero hash: the shipped bundles' is zero as well, the client does not check it.
    info = bytes(16) + struct.pack(">I", 1) + struct.pack(">IIH", len(payload), len(packed), BLOCK_FLAGS)
    # One node: offset 0, the whole payload, flag 4 (a serialized file), its name.
    info += struct.pack(">I", 1) + struct.pack(">qqI", 0, len(payload), 4) + node_name + b"\0"
    packed_info = lz4.block.compress(info, store_size=False, mode="high_compression")
    head = b"UnityFS\0" + struct.pack(">I", version) + player + b"\0" + engine + b"\0"
    # The total size counts everything, these size fields included.
    total = len(head) + 20 + len(packed_info) + len(packed)
    return head + struct.pack(">qIII", total, len(packed_info), len(info), flags) + packed_info + packed


# ------------------------------------------------------------------------------ serialized file

def _object_table(data):
    """Where the object table starts in a Unity 5.6 serialized file, and the class id of each type.

    Layout: a big-endian header (metadata size, file size, version, data offset, endianness), then the
    metadata: Unity version, platform, a type-tree flag, the types, and the object table. Returns
    (offset of the object count, class ids by type index, data offset).
    """
    _meta_size, _file_size, version, data_offset = struct.unpack_from(">IIII", data, 0)
    # The rest of the file's values are little-endian when this byte is 0.
    if version != SERIALIZED_VERSION or data[16] != 0:
        raise AtlasError(f"unexpected serialized file (version {version}, endian byte {data[16]})")
    _, i = _cstring(data, 20)
    i += 4
    has_trees = data[i]
    i += 1
    count = struct.unpack_from("<i", data, i)[0]
    i += 4
    classes = []
    for _ in range(count):
        class_id = struct.unpack_from("<i", data, i)[0]
        # Class id, stripped flag, script type index.
        i += 4 + 1 + 2
        # Scripts carry a 16-byte script id before the 16-byte type hash.
        if class_id == CLASS_MONOBEHAVIOUR:
            i += 16
        i += 16
        if has_trees:
            nodes, strings = struct.unpack_from("<ii", data, i)
            # Two counts, 24-byte nodes, their string buffer.
            i += 8 + nodes * 24 + strings
        classes.append(class_id)
    return i, classes, data_offset


def _read_objects(data):
    """All objects as [path id, type index, bytes], in table order, plus what is needed to write them back."""
    i, classes, data_offset = _object_table(data)
    count = struct.unpack_from("<i", data, i)[0]
    i += 4
    objects = []
    table_at = []
    for _ in range(count):
        # Each entry is aligned to four within the file.
        i = _align(i)
        path_id, start, size, type_index = struct.unpack_from("<qIIi", data, i)
        table_at.append(i)
        i += 20
        objects.append([path_id, type_index, data[data_offset + start:data_offset + start + size]])
    return objects, table_at, classes, data_offset


def _write_objects(data, objects, table_at, data_offset):
    """The serialized file again, with the objects' new bytes. Only the table's offsets and the sizes change."""
    head = bytearray(data[:data_offset])
    body = bytearray()
    for (path_id, type_index, raw), at in zip(objects, table_at):
        # Objects start on eight-byte boundaries, as Unity writes them.
        body += b"\0" * (_align(len(body), 8) - len(body))
        struct.pack_into("<qIIi", head, at, path_id, len(body), len(raw), type_index)
        body += raw
    # The header's file size is the only field that depends on the data.
    struct.pack_into(">I", head, 4, len(head) + len(body))
    return bytes(head + body)


# ------------------------------------------------------------------------------ the two objects

def _texture_bytes(old, pixels):
    """Texture2D with new pixels. The name stays; only size, format and the image bytes change.

    Fields: m_Name, m_Width, m_Height, m_CompleteImageSize, m_TextureFormat, m_MipCount, the settings
    (fixed size), the image bytes with their length, m_StreamData.
    """
    name_length = struct.unpack_from("<I", old, 0)[0]
    fields = _align(4 + name_length)
    _width, _height, old_size = struct.unpack_from("<iii", old, fields)
    # From the end: stream data, then the image bytes (padded to four), then their length.
    tail = len(old) - STREAM_DATA_SIZE
    length_at = tail - _align(old_size) - 4
    if length_at <= fields or struct.unpack_from("<I", old, length_at)[0] != old_size:
        raise AtlasError("the template's texture does not have the expected layout")
    # A shipped atlas keeps its pixels in the object: stream offset, size and path are all empty.
    if old[tail:] != bytes(STREAM_DATA_SIZE):
        raise AtlasError("the template's texture streams its pixels from another file")
    out = bytearray(old[:length_at])
    # One mip level, as shipped: the tile is shown near its full size, and mips would only add bytes.
    struct.pack_into("<iiiii", out, fields, TEXTURE_SIZE, TEXTURE_SIZE, len(pixels), FORMAT_RGBA32, 1)
    return bytes(out) + struct.pack("<I", len(pixels)) + pixels + old[tail:]


def _atlas_bytes(old, sprite):
    """The UIAtlas MonoBehaviour with one sprite. Everything around the sprite list stays.

    Fields: m_GameObject, m_Enabled, m_Script, m_Name, material, mSprites, then mPixelSize and the rest.
    """
    # PPtr (12 bytes), enabled padded to four, PPtr, then the (empty, in shipped atlases) name.
    i = 12 + 4 + 12
    i = _align(i + 4 + struct.unpack_from("<I", old, i)[0])
    # The material's PPtr, then the list.
    i += 12
    list_at = i
    count = struct.unpack_from("<i", old, i)[0]
    i += 4
    for _ in range(count):
        # Each entry: a name and twelve 32-bit numbers (x, y, width, height, four borders, four paddings).
        i = _align(i + 4 + struct.unpack_from("<I", old, i)[0]) + 12 * 4
    if count < 1 or i > len(old) or struct.unpack_from("<f", old, i)[0] != 1.0:
        # mPixelSize follows the list and is 1.0 in every shipped atlas: a check that the walk stayed on course.
        raise AtlasError("the template's atlas does not have the expected layout")
    # x, y, width, height from the texture's top left, then borders and paddings, all zero.
    entry = _aligned_string(sprite) + struct.pack("<12i", 0, 0, TILE_WIDTH, TILE_HEIGHT, 0, 0, 0, 0, 0, 0, 0, 0)
    return old[:list_at] + struct.pack("<i", 1) + entry + old[i:]


def tile_pixels(jacket_bytes):
    """The texture for a jacket: the centre of the image at tile proportions, in the top left of a square.

    Returns RGBA32 bytes in Unity's order: the first row is the bottom one, while NGUI's sprite
    coordinates count from the top (the tile at y 0 is at the end of the bytes).
    """
    from PIL import Image, ImageOps
    try:
        with Image.open(io.BytesIO(jacket_bytes)) as im:
            # The shipped tiles were each framed by hand; the centre is the neutral choice for a 4:3 jacket.
            tile = ImageOps.fit(im.convert("RGB"), (TILE_WIDTH, TILE_HEIGHT), Image.Resampling.LANCZOS)
    except Exception as e:  # noqa: BLE001 - Pillow raises many kinds for broken files
        raise AtlasError(f"the jacket cannot be read: {e}")
    texture = Image.new("RGBA", (TEXTURE_SIZE, TEXTURE_SIZE))
    texture.paste(tile, (0, 0))
    # Repeat the tile's last row below it, so filtering at its edge does not pull in black.
    last_row = tile.crop((0, TILE_HEIGHT - 1, TILE_WIDTH, TILE_HEIGHT))
    texture.paste(last_row.resize((TEXTURE_SIZE, TEXTURE_SIZE - TILE_HEIGHT)), (0, TILE_HEIGHT))
    # Jackets are opaque; RGB converted to RGBA has alpha 255, so premultiplying changes nothing.
    texture.putalpha(255)
    return texture.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes("raw", "RGBA")


def build(template, jacket_bytes, song_id, name):
    """A complete bundle for an added song, from a shipped atlas bundle and its jacket PNG.

    Unchanged input gives unchanged output, so a rebuild does not make phones download it again.
    """
    strings, flags, _node, data = _read_bundle(template)
    try:
        objects, table_at, classes, data_offset = _read_objects(data)
        pixels = tile_pixels(jacket_bytes)
        seen = set()
        for obj in objects:
            kind = classes[obj[1]]
            if kind == CLASS_TEXTURE2D:
                obj[2] = _texture_bytes(obj[2], pixels)
            elif kind == CLASS_MONOBEHAVIOUR:
                obj[2] = _atlas_bytes(obj[2], sprite_name(song_id, name))
            else:
                continue
            seen.add(kind)
    except (struct.error, ValueError, IndexError) as e:
        raise AtlasError(f"the template cannot be rewritten: {e}")
    if seen != {CLASS_TEXTURE2D, CLASS_MONOBEHAVIOUR}:
        raise AtlasError("the template has no atlas or no texture")
    payload = _write_objects(data, objects, table_at, data_offset)
    # Unity refuses to load two bundles whose inner file has the same name, so each song gets its own,
    # in the form Unity gives them ("CAB-" and 32 hex digits). It is derived from the id alone: stable.
    node = b"CAB-" + hashlib.md5(f"opendmtq-tile-{song_id}".encode()).hexdigest().encode()
    return _write_bundle(strings, flags, node, payload)
