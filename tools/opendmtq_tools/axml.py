"""Edits Android binary XML (the compiled AndroidManifest.xml inside an APK) in place.

The patcher keeps the game's resources compiled (apktool -r), so the manifest stays binary. This
adds boolean attributes to the <application> element without decoding anything else:

  * the attribute names go at the end of the string pool, so no existing string index moves;
  * the resource map, which gives the string at index i the attribute ID ids[i], grows to
    cover them (the strings in between map to 0, "no resource ID", as strings past its end do);
  * the attributes are inserted in resource ID order, which the framework relies on when it
    reads them.

Usage: set_application_flags(manifest_bytes, {"multiArch": (0x0101048e, True), ...}) -> bytes

It also replaces the app's name, set_application_label(manifest_bytes, "Some name"), and its package,
set_package(manifest_bytes, old, new) with set_table_package(table_bytes, old, new) for the resources. And it sets the
Android version the app says it was made for, set_target_sdk(manifest_bytes, 28), and adds a library it asks the system
for, add_optional_library(manifest_bytes, "some.library"). In the network security config, set_plain_flag(document_bytes,
"base-config", "cleartextTrafficPermitted") turns on a plain attribute. manifest_info(manifest_bytes) only reads: the
package name and the version of the app.
"""

import struct

ANDROID_NS = "http://schemas.android.com/apk/res/android"

RES_STRING_POOL_TYPE = 0x0001
RES_XML_TYPE = 0x0003
RES_XML_START_ELEMENT_TYPE = 0x0102
RES_XML_END_ELEMENT_TYPE = 0x0103
RES_XML_RESOURCE_MAP_TYPE = 0x0180
UTF8_FLAG = 0x100
SORTED_FLAG = 0x1
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_BOOLEAN = 0x12
ATTR_LABEL = 0x01010001
ATTR_NAME = 0x01010003
ATTR_REQUIRED = 0x0101028e
ATTR_TARGET_SDK = 0x01010270
ATTR_VERSION_CODE = 0x0101021b
ATTR_VERSION_NAME = 0x0101021c
NO_INDEX = 0xFFFFFFFF


class StringPool:
    """A string pool chunk: the strings decoded, the style data kept as it is."""

    def __init__(self, chunk):
        (_type, header_size, _size, count, style_count, flags, strings_start,
         styles_start) = struct.unpack_from("<HHIIIIII", chunk, 0)
        self.flags = flags
        self.utf8 = bool(flags & UTF8_FLAG)
        offsets = struct.unpack_from(f"<{count}I", chunk, header_size)
        self.style_offsets = list(struct.unpack_from(f"<{style_count}I", chunk, header_size + 4 * count))
        self.strings = [self._read(chunk, strings_start + o) for o in offsets]
        # Styles run from stylesStart to the end of the chunk; their offsets are relative to it.
        self.styles = chunk[styles_start:] if style_count else b""

    def _read(self, chunk, at):
        if self.utf8:
            # UTF-16 length, then UTF-8 byte length, each one or two bytes.
            n = chunk[at]
            at += 2 if n & 0x80 else 1
            n = chunk[at]
            if n & 0x80:
                n = ((n & 0x7F) << 8) | chunk[at + 1]
                at += 2
            else:
                at += 1
            return chunk[at:at + n].decode("utf-8")
        n = struct.unpack_from("<H", chunk, at)[0]
        at += 2
        if n & 0x8000:
            n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", chunk, at)[0]
            at += 2
        return chunk[at:at + 2 * n].decode("utf-16-le")

    def _encode(self, s):
        if self.utf8:
            data = s.encode("utf-8")
            def length(n):
                return bytes([n]) if n < 0x80 else bytes([0x80 | (n >> 8), n & 0xFF])
            return length(len(s.encode("utf-16-le")) // 2) + length(len(data)) + data + b"\0"
        data = s.encode("utf-16-le")
        n = len(data) // 2
        head = struct.pack("<H", n) if n < 0x8000 else struct.pack("<HH", 0x8000 | (n >> 16), n & 0xFFFF)
        return head + data + b"\0\0"

    def index(self, s):
        """Index of s, added at the end if it is not there yet."""
        if s in self.strings:
            return self.strings.index(s)
        self.strings.append(s)
        return len(self.strings) - 1

    def build(self):
        header_size = 28
        data = bytearray()
        offsets = []
        for s in self.strings:
            offsets.append(len(data))
            data += self._encode(s)
        # The string data is padded to four bytes before the styles.
        while len(data) % 4:
            data.append(0)
        strings_start = header_size + 4 * len(self.strings) + 4 * len(self.style_offsets)
        styles_start = strings_start + len(data) if self.style_offsets else 0
        size = strings_start + len(data) + len(self.styles)
        # Appended strings break any sort order.
        flags = self.flags & ~SORTED_FLAG
        out = struct.pack("<HHIIIIII", RES_STRING_POOL_TYPE, header_size, size, len(self.strings),
                          len(self.style_offsets), flags, strings_start, styles_start)
        out += struct.pack(f"<{len(offsets)}I", *offsets)
        out += struct.pack(f"<{len(self.style_offsets)}I", *self.style_offsets)
        return out + bytes(data) + self.styles


def chunks(data, start):
    """(offset, type, header size, size) of each chunk from start to the end of data."""
    at = start
    while at + 8 <= len(data):
        ctype, header_size, size = struct.unpack_from("<HHI", data, at)
        if size < 8 or at + size > len(data):
            raise ValueError(f"bad chunk at {at:#x}")
        yield at, ctype, header_size, size
        at += size


def set_application_flags(manifest, flags):
    """The manifest with each flag set on <application>: {name: (attribute ID, bool)}."""
    ctype, header_size, size = struct.unpack_from("<HHI", manifest, 0)
    if ctype != RES_XML_TYPE or size != len(manifest):
        raise ValueError("not a binary XML document")
    parts = list(chunks(manifest, header_size))
    pool_at = next(c for c in parts if c[1] == RES_STRING_POOL_TYPE)
    pool = StringPool(manifest[pool_at[0]:pool_at[0] + pool_at[3]])
    map_at = next((c for c in parts if c[1] == RES_XML_RESOURCE_MAP_TYPE), None)
    ids = list(struct.unpack_from(f"<{(map_at[3] - 8) // 4}I", manifest, map_at[0] + 8)) if map_at else []

    # Name strings for the attributes, mapped to their IDs.
    ns = pool.index(ANDROID_NS)
    wanted = {}
    for name, (attr_id, value) in flags.items():
        idx = ids.index(attr_id) if attr_id in ids else pool.index(name)
        while len(ids) <= idx:
            ids.append(0)
        ids[idx] = attr_id
        wanted[attr_id] = (idx, value)

    out = bytearray()
    done = False
    for at, ctype, hsize, csize in parts:
        chunk = manifest[at:at + csize]
        if ctype == RES_STRING_POOL_TYPE:
            continue
        if ctype == RES_XML_RESOURCE_MAP_TYPE:
            continue
        if ctype == RES_XML_START_ELEMENT_TYPE and not done:
            (el_ns, el_name, attr_start, attr_size, count, id_index, class_index,
             style_index) = struct.unpack_from("<IIHHHHHH", chunk, hsize)
            if el_ns == NO_INDEX and pool.strings[el_name] == "application":
                chunk = _with_attributes(chunk, hsize, attr_start, attr_size, count, ids, ns, wanted,
                                         (id_index, class_index, style_index))
                done = True
        out += chunk
    if not done:
        raise ValueError("no <application> element")
    # Header, string pool, resource map, then the tree as it was apart from <application>.
    pool_bytes = pool.build()
    map_bytes = struct.pack("<HHI", RES_XML_RESOURCE_MAP_TYPE, 8, 8 + 4 * len(ids)) + struct.pack(f"<{len(ids)}I", *ids)
    body = pool_bytes + map_bytes + bytes(out)
    return struct.pack("<HHI", RES_XML_TYPE, header_size, header_size + len(body)) + body


def set_target_sdk(manifest, version):
    """The manifest with android:targetSdkVersion on <uses-sdk> set to version. No string or resource ID changes: the
    attribute is already there, and only its number is overwritten in place."""
    ctype, header_size, size = struct.unpack_from("<HHI", manifest, 0)
    if ctype != RES_XML_TYPE or size != len(manifest):
        raise ValueError("not a binary XML document")
    parts = list(chunks(manifest, header_size))
    pool_at = next(c for c in parts if c[1] == RES_STRING_POOL_TYPE)
    pool = StringPool(manifest[pool_at[0]:pool_at[0] + pool_at[3]])
    map_at = next((c for c in parts if c[1] == RES_XML_RESOURCE_MAP_TYPE), None)
    ids = struct.unpack_from(f"<{(map_at[3] - 8) // 4}I", manifest, map_at[0] + 8) if map_at else ()
    out = bytearray(manifest)
    for at, ctype, hsize, _csize in parts:
        if ctype != RES_XML_START_ELEMENT_TYPE:
            continue
        el_ns, el_name, attr_start, attr_size, count = struct.unpack_from("<IIHHH", manifest, at + hsize)
        if el_ns != NO_INDEX or pool.strings[el_name] != "uses-sdk":
            continue
        for i in range(count):
            a = at + hsize + attr_start + i * attr_size
            name = struct.unpack_from("<I", manifest, a + 4)[0]
            if name < len(ids) and ids[name] == ATTR_TARGET_SDK:
                # No raw text for a number; the typed value is its size, a zero, its type and the number.
                struct.pack_into("<I", out, a + 8, NO_INDEX)
                struct.pack_into("<HBBI", out, a + 12, 8, 0, TYPE_INT_DEC, version)
                return bytes(out)
    raise ValueError("no android:targetSdkVersion in <uses-sdk>")


def add_optional_library(manifest, library):
    """The manifest with <uses-library android:name=library android:required="false"/> as the first thing inside
    <application>. A library it already asks for is left as it is."""
    ctype, header_size, size = struct.unpack_from("<HHI", manifest, 0)
    if ctype != RES_XML_TYPE or size != len(manifest):
        raise ValueError("not a binary XML document")
    parts = list(chunks(manifest, header_size))
    pool_at = next(c for c in parts if c[1] == RES_STRING_POOL_TYPE)
    pool = StringPool(manifest[pool_at[0]:pool_at[0] + pool_at[3]])
    map_at = next((c for c in parts if c[1] == RES_XML_RESOURCE_MAP_TYPE), None)
    ids = list(struct.unpack_from(f"<{(map_at[3] - 8) // 4}I", manifest, map_at[0] + 8)) if map_at else []
    # Already there: the same text, on a <uses-library> element.
    if library in pool.strings and "uses-library" in pool.strings:
        return manifest

    # The strings the new element needs. pool.index() adds one that is missing, at the end, so no existing index moves.
    ns = pool.index(ANDROID_NS)
    element = pool.index("uses-library")
    value = pool.index(library)
    # A resource ID goes with the name of an attribute, at that name's index in the map; strings past the map's end have none.
    attr_names = {}
    for name, attr_id in (("name", ATTR_NAME), ("required", ATTR_REQUIRED)):
        idx = ids.index(attr_id) if attr_id in ids else pool.index(name)
        while len(ids) <= idx:
            ids.append(0)
        ids[idx] = attr_id
        attr_names[attr_id] = idx

    # One attribute: namespace, name, raw text, then the typed value. In resource ID order, as the framework reads them.
    attrs = struct.pack("<IIIHBBI", ns, attr_names[ATTR_NAME], value, 8, 0, TYPE_STRING, value)
    attrs += struct.pack("<IIIHBBI", ns, attr_names[ATTR_REQUIRED], NO_INDEX, 8, 0, TYPE_INT_BOOLEAN, 0)
    # A node's header: type, its size (16), the whole chunk's size, then its line in the source and no comment.
    start_ext = struct.pack("<IIHHHHHH", NO_INDEX, element, 20, 20, 2, 0, 0, 0)
    start = struct.pack("<HHIII", RES_XML_START_ELEMENT_TYPE, 16, 16 + len(start_ext) + len(attrs), 1, NO_INDEX) + start_ext + attrs
    end = struct.pack("<HHIIIII", RES_XML_END_ELEMENT_TYPE, 16, 24, 1, NO_INDEX, NO_INDEX, element)

    out = bytearray()
    done = False
    for at, ctype, hsize, csize in parts:
        if ctype in (RES_STRING_POOL_TYPE, RES_XML_RESOURCE_MAP_TYPE):
            continue
        chunk = manifest[at:at + csize]
        out += chunk
        if ctype == RES_XML_START_ELEMENT_TYPE and not done:
            el_ns, el_name = struct.unpack_from("<II", chunk, hsize)
            if el_ns == NO_INDEX and pool.strings[el_name] == "application":
                out += start + end
                done = True
    if not done:
        raise ValueError("no <application> element")
    map_bytes = struct.pack("<HHI", RES_XML_RESOURCE_MAP_TYPE, 8, 8 + 4 * len(ids)) + struct.pack(f"<{len(ids)}I", *ids)
    body = pool.build() + map_bytes + bytes(out)
    return struct.pack("<HHI", RES_XML_TYPE, header_size, header_size + len(body)) + body


def set_plain_flag(document, element, attribute):
    """The document with attribute="true" on the first <element>: a plain attribute, with no namespace or resource ID, as
    a network security config has them. Android reads these by their type, so the value is a boolean, not the text."""
    ctype, header_size, size = struct.unpack_from("<HHI", document, 0)
    if ctype != RES_XML_TYPE or size != len(document):
        raise ValueError("not a binary XML document")
    parts = list(chunks(document, header_size))
    pool_at = next(c for c in parts if c[1] == RES_STRING_POOL_TYPE)
    pool = StringPool(document[pool_at[0]:pool_at[0] + pool_at[3]])
    # Added at the end if it is new; a string past the resource map's end has no ID, as this one should not.
    name = pool.index(attribute)
    new = struct.pack("<IIIHBBI", NO_INDEX, name, NO_INDEX, 8, 0, TYPE_INT_BOOLEAN, 0xFFFFFFFF)
    out = bytearray()
    done = False
    for at, ctype, hsize, csize in parts:
        if ctype == RES_STRING_POOL_TYPE:
            continue
        chunk = bytearray(document[at:at + csize])
        if ctype == RES_XML_START_ELEMENT_TYPE and not done:
            el_ns, el_name, attr_start, attr_size, count = struct.unpack_from("<IIHHH", chunk, hsize)
            if el_ns == NO_INDEX and pool.strings[el_name] == element:
                base = hsize + attr_start
                attrs = [bytes(chunk[base + i * attr_size:base + (i + 1) * attr_size]) for i in range(count)]
                # Set already: replaced where it is. New: after the others, which is where those without an ID go.
                old = [i for i, a in enumerate(attrs) if struct.unpack_from("<I", a, 4)[0] == name]
                if old:
                    attrs[old[0]] = new
                else:
                    attrs.append(new)
                head = bytearray(chunk[:base])
                struct.pack_into("<H", head, hsize + 12, len(attrs))
                chunk = head + b"".join(attrs) + chunk[base + count * attr_size:]
                struct.pack_into("<I", chunk, 4, len(chunk))
                done = True
        out += chunk
    if not done:
        raise ValueError(f"no <{element}> element")
    body = pool.build() + bytes(out)
    return struct.pack("<HHI", RES_XML_TYPE, header_size, header_size + len(body)) + body


def set_application_label(manifest, label):
    """The manifest with android:label on <application> set to the text `label`.

    The manifest names the app through a resource (@string/app_name), in a resource table this patcher
    leaves compiled: the attribute becomes the text itself. Any other element that names the same
    resource (a launcher activity's own label, say) follows, so the home screen and the system's app
    list agree. The new text goes at the end of the string pool, so no existing index moves.
    """
    ctype, header_size, size = struct.unpack_from("<HHI", manifest, 0)
    if ctype != RES_XML_TYPE or size != len(manifest):
        raise ValueError("not a binary XML document")
    parts = list(chunks(manifest, header_size))
    pool_at = next(c for c in parts if c[1] == RES_STRING_POOL_TYPE)
    pool = StringPool(manifest[pool_at[0]:pool_at[0] + pool_at[3]])
    map_at = next((c for c in parts if c[1] == RES_XML_RESOURCE_MAP_TYPE), None)
    ids = struct.unpack_from(f"<{(map_at[3] - 8) // 4}I", manifest, map_at[0] + 8) if map_at else ()
    text = pool.index(label)

    def label_attrs(chunk, hsize):
        """Byte offsets, in the start-element chunk, of its android:label attribute."""
        attr_start, attr_size, count = struct.unpack_from("<HHH", chunk, hsize + 8)
        base = hsize + attr_start
        for i in range(count):
            at = base + i * attr_size
            name = struct.unpack_from("<I", chunk, at + 4)[0]
            if name < len(ids) and ids[name] == ATTR_LABEL:
                yield at

    # What <application> names now: the same reference elsewhere means the same name.
    named = None
    for at, ctype, hsize, csize in parts:
        if ctype == RES_XML_START_ELEMENT_TYPE:
            chunk = manifest[at:at + csize]
            el_ns, el_name = struct.unpack_from("<II", chunk, hsize)
            if el_ns == NO_INDEX and pool.strings[el_name] == "application":
                for a in label_attrs(chunk, hsize):
                    named = struct.unpack_from("<I", chunk, a + 16)[0]
                if named is None:
                    raise ValueError("<application> has no android:label")
                break
    if named is None:
        raise ValueError("no <application> element")

    out = bytearray()
    for at, ctype, hsize, csize in parts:
        chunk = bytearray(manifest[at:at + csize])
        if ctype == RES_STRING_POOL_TYPE:
            continue
        if ctype == RES_XML_START_ELEMENT_TYPE:
            for a in label_attrs(bytes(chunk), hsize):
                if struct.unpack_from("<I", chunk, a + 16)[0] == named:
                    # Raw value, then the typed value (size, zero, type, data).
                    struct.pack_into("<I", chunk, a + 8, text)
                    struct.pack_into("<HBBI", chunk, a + 12, 8, 0, TYPE_STRING, text)
        out += chunk
    body = pool.build() + bytes(out)
    return struct.pack("<HHI", RES_XML_TYPE, header_size, header_size + len(body)) + body


def manifest_info(manifest):
    """The package name and version of the app, from the <manifest> element: {"package", "version", "code"} (None for
    what it does not say). Read only: what a client is, before anything is changed in it."""
    ctype, header_size, size = struct.unpack_from("<HHI", manifest, 0)
    if ctype != RES_XML_TYPE or size != len(manifest):
        raise ValueError("not a binary XML document")
    parts = list(chunks(manifest, header_size))
    pool_at = next(c for c in parts if c[1] == RES_STRING_POOL_TYPE)
    pool = StringPool(manifest[pool_at[0]:pool_at[0] + pool_at[3]])
    map_at = next((c for c in parts if c[1] == RES_XML_RESOURCE_MAP_TYPE), None)
    ids = struct.unpack_from(f"<{(map_at[3] - 8) // 4}I", manifest, map_at[0] + 8) if map_at else ()
    info = {"package": None, "version": None, "code": None}
    for at, ctype, hsize, csize in parts:
        if ctype != RES_XML_START_ELEMENT_TYPE:
            continue
        chunk = manifest[at:at + csize]
        el_ns, el_name, attr_start, attr_size, count = struct.unpack_from("<IIHHH", chunk, hsize)
        # The first element is <manifest>; nothing else names the package.
        if el_ns != NO_INDEX or pool.strings[el_name] != "manifest":
            break
        for i in range(count):
            a = hsize + attr_start + i * attr_size
            _ns, name, raw, _size, _zero, vtype, data = struct.unpack_from("<IIIHBBI", chunk, a)
            # android: attributes by their resource ID (their name strings may be anything), package by its name.
            key = {ATTR_VERSION_CODE: "code", ATTR_VERSION_NAME: "version"}.get(ids[name] if name < len(ids) else 0)
            if key is None and pool.strings[name] == "package":
                key = "package"
            if key is None:
                continue
            if raw != NO_INDEX:
                # Text: the package and, in every manifest seen, the version name.
                info[key] = pool.strings[raw]
            elif key == "code" and vtype == TYPE_INT_DEC:
                info[key] = data
            # Anything else (a version name given as a resource reference) stays unknown.
        break
    return info


def set_package(manifest, old, new):
    """The manifest with the package name `old` replaced by `new` everywhere it stands.

    Everything that must be unique per app is the package name or starts with it: the package itself,
    the content providers' authorities, its own permission and the intent categories that name it. The
    game's classes live under other names, so nothing that names a class changes. Strings are replaced
    in the pool, in place, so no index moves.
    """
    ctype, header_size, size = struct.unpack_from("<HHI", manifest, 0)
    if ctype != RES_XML_TYPE or size != len(manifest):
        raise ValueError("not a binary XML document")
    parts = list(chunks(manifest, header_size))
    pool_at = next(c for c in parts if c[1] == RES_STRING_POOL_TYPE)
    pool = StringPool(manifest[pool_at[0]:pool_at[0] + pool_at[3]])
    if old not in pool.strings:
        raise ValueError(f"the manifest does not name {old}")
    pool.strings = [new + s[len(old):] if s == old or s.startswith(old + ".") else s for s in pool.strings]
    out = bytearray()
    for at, ctype, hsize, csize in parts:
        if ctype != RES_STRING_POOL_TYPE:
            out += manifest[at:at + csize]
    body = pool.build() + bytes(out)
    return struct.pack("<HHI", RES_XML_TYPE, header_size, header_size + len(body)) + body


def set_table_package(table, old, new):
    """The compiled resource table with its package's name replaced: code that looks resources up by the
    app's package name (Resources.getIdentifier) finds nothing otherwise. The name is a fixed field of
    128 UTF-16 units in the package chunk, so nothing else moves."""
    name = old.encode("utf-16-le")
    fresh = new.encode("utf-16-le")
    field = 256
    if len(fresh) >= field:
        raise ValueError("package name too long")
    ctype, header_size, size = struct.unpack_from("<HHI", table, 0)
    if ctype != 0x0002 or size != len(table):
        raise ValueError("not a resource table")
    found = 0
    data = bytearray(table)
    for at, ctype, _hsize, csize in chunks(table, header_size):
        # Package chunk: type, header size, size, id, then the name.
        if ctype == 0x0200 and bytes(data[at + 12:at + 12 + len(name)]) == name:
            data[at + 12:at + 12 + field] = fresh.ljust(field, b"\0")
            found += 1
    if found != 1:
        raise ValueError(f"the resource table's package is not {old}")
    return bytes(data)


def _with_attributes(chunk, hsize, attr_start, attr_size, count, ids, ns, wanted, special):
    """The start-element chunk with the wanted boolean attributes set, in resource ID order."""
    base = hsize + attr_start
    attrs = [bytearray(chunk[base + i * attr_size:base + (i + 1) * attr_size]) for i in range(count)]
    def attr_id(a):
        name = struct.unpack_from("<I", a, 4)[0]
        return ids[name] if name < len(ids) else 0
    for wid, (name_idx, value) in sorted(wanted.items()):
        data = 0xFFFFFFFF if value else 0
        new = bytearray(struct.pack("<IIIHBBI", ns, name_idx, NO_INDEX, 8, 0, TYPE_INT_BOOLEAN, data))
        new += bytes(attr_size - len(new))
        existing = [i for i, a in enumerate(attrs) if attr_id(a) == wid]
        if existing:
            attrs[existing[0]] = new
            continue
        # Before the first attribute with a larger ID; attributes without an ID come last.
        pos = next((i for i, a in enumerate(attrs) if attr_id(a) == 0 or attr_id(a) > wid), len(attrs))
        attrs.insert(pos, new)
        # The id, class and style attribute positions (1-based) move with the insertion.
        special = tuple(s + 1 if s and s > pos else s for s in special)
    head = bytearray(chunk[:base])
    struct.pack_into("<HHHH", head, hsize + 12, len(attrs), *special)
    body = head + b"".join(attrs) + chunk[base + count * attr_size:]
    struct.pack_into("<I", body, 4, len(body))
    return bytes(body)
