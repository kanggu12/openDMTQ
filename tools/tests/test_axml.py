"""Tests for the binary manifest editor, on small documents built with the real chunk layout."""

import struct
import unittest

from opendmtq_tools import axml

NS = "http://schemas.android.com/apk/res/android"
# Attribute IDs as in the framework.
THEME, LABEL, IS_GAME, NETWORK_SECURITY_CONFIG = 0x01010000, 0x01010001, 0x010103F4, 0x01010527
MULTI_ARCH, USE_32BIT_ABI = 0x0101048E, 0x01010515
FLAGS = {"multiArch": (MULTI_ARCH, True), "use32bitAbi": (USE_32BIT_ABI, True)}


def pool(strings, utf8):
    """A string pool chunk."""
    data = bytearray()
    offsets = []
    for s in strings:
        offsets.append(len(data))
        if utf8:
            b = s.encode("utf-8")
            data += bytes([len(s), len(b)]) + b + b"\0"
        else:
            data += struct.pack("<H", len(s)) + s.encode("utf-16-le") + b"\0\0"
    while len(data) % 4:
        data.append(0)
    start = 28 + 4 * len(strings)
    head = struct.pack("<HHIIIIII", 1, 28, start + len(data), len(strings), 0, 0x100 if utf8 else 0, start, 0)
    return head + struct.pack(f"<{len(strings)}I", *offsets) + bytes(data)


def element(ns, name, attrs, idx):
    """A start-element chunk; attrs are (name, type, data) with the android namespace."""
    body = struct.pack("<IIHHHHHH", 0xFFFFFFFF, idx[name], 20, 20, len(attrs), 0, 0, 0)
    for aname, atype, adata in attrs:
        body += struct.pack("<IIIHBBI", idx[ns], idx[aname], 0xFFFFFFFF, 8, 0, atype, adata)
    return struct.pack("<HHIII", 0x0102, 16, 16 + len(body), 1, 0xFFFFFFFF) + body


def end(name, idx):
    return struct.pack("<HHIIIII", 0x0103, 16, 24, 1, 0xFFFFFFFF, 0xFFFFFFFF, idx[name])


def manifest(utf8=True, flags_present=False):
    """<manifest><application theme label isGame [multiArch] networkSecurityConfig/></manifest>."""
    # The attribute names come first, as aapt puts them, so the resource map covers them.
    strings = ["theme", "label", "isGame", "networkSecurityConfig"]
    ids = [THEME, LABEL, IS_GAME, NETWORK_SECURITY_CONFIG]
    if flags_present:
        strings.insert(3, "multiArch")
        ids.insert(3, MULTI_ARCH)
    strings += ["android", NS, "manifest", "application"]
    idx = {s: i for i, s in enumerate(strings)}
    attrs = [("theme", 0x01, 0x01030007), ("label", 0x01, 0x7F05013C), ("isGame", 0x12, 0xFFFFFFFF)]
    if flags_present:
        attrs.append(("multiArch", 0x12, 0))
    attrs.append(("networkSecurityConfig", 0x01, 0x7F0E0000))
    nodes = struct.pack("<HHIIIII", 0x0100, 16, 24, 1, 0xFFFFFFFF, idx["android"], idx[NS])
    nodes += element(NS, "manifest", [], idx)
    nodes += element(NS, "application", attrs, idx)
    nodes += end("application", idx) + end("manifest", idx)
    nodes += struct.pack("<HHIIIII", 0x0101, 16, 24, 1, 0xFFFFFFFF, idx["android"], idx[NS])
    resmap = struct.pack("<HHI", 0x0180, 8, 8 + 4 * len(ids)) + struct.pack(f"<{len(ids)}I", *ids)
    body = pool(strings, utf8) + resmap + nodes
    return struct.pack("<HHI", 3, 8, 8 + len(body)) + body


def read(doc):
    """(strings, resource IDs, {element name: [(attribute ID, type, data)]}) of a document."""
    strings, ids, elements = None, [], {}
    for at, ctype, hsize, size in axml.chunks(doc, 8):
        chunk = doc[at:at + size]
        if ctype == 1:
            strings = axml.StringPool(chunk).strings
        elif ctype == 0x0180:
            ids = list(struct.unpack_from(f"<{(size - 8) // 4}I", chunk, 8))
        elif ctype == 0x0102:
            _, name, start, asize, count = struct.unpack_from("<IIHHH", chunk, hsize)
            attrs = []
            for i in range(count):
                _, aname, _, _, _, atype, adata = struct.unpack_from("<IIIHBBI", chunk, hsize + start + i * asize)
                attrs.append((ids[aname] if aname < len(ids) else 0, atype, adata))
            elements[strings[name]] = attrs
    return strings, ids, elements


def with_sdk(target):
    """<manifest><uses-sdk minSdkVersion targetSdkVersion/><application .../></manifest>, as the game's has it."""
    strings = ["minSdkVersion", "targetSdkVersion", "label", "android", NS, "manifest", "uses-sdk", "application"]
    ids = [0x0101020C, axml.ATTR_TARGET_SDK, LABEL]
    idx = {s: i for i, s in enumerate(strings)}
    nodes = struct.pack("<HHIIIII", 0x0100, 16, 24, 1, 0xFFFFFFFF, idx["android"], idx[NS])
    nodes += element(NS, "manifest", [], idx)
    nodes += element(NS, "uses-sdk", [("minSdkVersion", 0x10, 15), ("targetSdkVersion", 0x10, target)], idx) + end("uses-sdk", idx)
    nodes += element(NS, "application", [("label", 0x01, 0x7F05013C)], idx)
    nodes += end("application", idx) + end("manifest", idx)
    nodes += struct.pack("<HHIIIII", 0x0101, 16, 24, 1, 0xFFFFFFFF, idx["android"], idx[NS])
    resmap = struct.pack("<HHI", 0x0180, 8, 8 + 4 * len(ids)) + struct.pack(f"<{len(ids)}I", *ids)
    body = pool(strings, True) + resmap + nodes
    return struct.pack("<HHI", 3, 8, 8 + len(body)) + body


class TargetTest(unittest.TestCase):
    def test_the_target_changes_and_nothing_else(self):
        out = axml.set_target_sdk(with_sdk(27), 28)
        self.assertEqual(len(out), len(with_sdk(27)))
        self.assertEqual(read(out)[2]["uses-sdk"], [(0x0101020C, 0x10, 15), (axml.ATTR_TARGET_SDK, 0x10, 28)])

    def test_a_manifest_without_one_is_refused(self):
        with self.assertRaises(ValueError):
            axml.set_target_sdk(manifest(), 28)

    def test_a_library_is_asked_for_inside_the_application(self):
        out = axml.add_optional_library(with_sdk(27), "org.apache.http.legacy")
        self.assertEqual(struct.unpack_from("<I", out, 4)[0], len(out))
        strings, _, elements = read(out)
        # Its name as text, and required as false; its attributes in resource ID order.
        name = strings.index("org.apache.http.legacy")
        self.assertEqual(elements["uses-library"], [(axml.ATTR_NAME, 0x03, name), (axml.ATTR_REQUIRED, 0x12, 0)])
        # Between the application's start and end.
        order = [(ctype, struct.unpack_from("<I", out, at + hsize + 4)[0]) for at, ctype, hsize, _ in axml.chunks(out, 8) if ctype in (0x0102, 0x0103)]
        names = [("start " if ctype == 0x0102 else "end ") + strings[n] for ctype, n in order]
        self.assertEqual(names.index("start application") + 1, names.index("start uses-library"))
        self.assertEqual(names.index("start uses-library") + 1, names.index("end uses-library"))
        self.assertEqual(names.index("end uses-library") + 1, names.index("end application"))

    def test_asking_twice_changes_nothing(self):
        out = axml.add_optional_library(with_sdk(27), "org.apache.http.legacy")
        self.assertEqual(axml.add_optional_library(out, "org.apache.http.legacy"), out)

    def test_a_plain_flag_goes_on_the_element(self):
        strings = ["network-security-config", "base-config"]
        idx = {s: i for i, s in enumerate(strings)}
        nodes = element(NS, "network-security-config", [], idx) + element(NS, "base-config", [], idx) + end("base-config", idx) + end("network-security-config", idx)
        body = pool(strings, True) + nodes
        doc = struct.pack("<HHI", 3, 8, 8 + len(body)) + body
        out = axml.set_plain_flag(doc, "base-config", "cleartextTrafficPermitted")
        # A boolean, not the text: Android reads this attribute by its type. With no resource ID.
        self.assertEqual(read(out)[2]["base-config"], [(0, 0x12, 0xFFFFFFFF)])
        self.assertIn("cleartextTrafficPermitted", read(out)[0])
        # Set again, it stays one.
        self.assertEqual(read(axml.set_plain_flag(out, "base-config", "cleartextTrafficPermitted"))[2]["base-config"], [(0, 0x12, 0xFFFFFFFF)])


class AxmlTest(unittest.TestCase):
    def check(self, doc):
        out = axml.set_application_flags(doc, FLAGS)
        # The header gives the whole size and every chunk lies inside it.
        self.assertEqual(struct.unpack_from("<I", out, 4)[0], len(out))
        strings, _, elements = read(out)
        app = elements["application"]
        # In resource ID order, the new ones true, the others untouched.
        self.assertEqual([a[0] for a in app], [THEME, LABEL, IS_GAME, MULTI_ARCH, USE_32BIT_ABI, NETWORK_SECURITY_CONFIG])
        self.assertEqual(app[3][1:], (0x12, 0xFFFFFFFF))
        self.assertEqual(app[4][1:], (0x12, 0xFFFFFFFF))
        self.assertEqual(app[0][1:], (0x01, 0x01030007))
        self.assertEqual(app[5][1:], (0x01, 0x7F0E0000))
        # Existing strings keep their indices.
        before, _, _ = read(doc)
        self.assertEqual(strings[:len(before)], before)
        self.assertEqual(elements["manifest"], [])
        return out

    def test_adds_flags_utf8(self):
        self.check(manifest(utf8=True))

    def test_adds_flags_utf16(self):
        self.check(manifest(utf8=False))

    def test_sets_an_existing_flag_and_is_idempotent(self):
        out = self.check(manifest(flags_present=True))
        # A second pass changes nothing.
        self.assertEqual(axml.set_application_flags(out, FLAGS), out)



class PackageTest(unittest.TestCase):
    """The package name changes where it stands, and nothing else moves."""

    def test_manifest(self):
        for utf8 in (True, False):
            doc = manifest(utf8)
            strings, _, _ = read(doc)
            old = strings[0]
            before = [s for s in strings]
            out = axml.set_package(doc, old, "new.pkg")
            after, _, _ = read(out)
            self.assertEqual(len(after), len(before))
            self.assertEqual(after[0], "new.pkg")
            self.assertEqual(after[1:], before[1:])

    def test_a_manifest_without_the_package_is_refused(self):
        with self.assertRaises(ValueError):
            axml.set_package(manifest(), "no.such.package", "x")

    def test_resource_table(self):
        name = "old.pkg".encode("utf-16-le").ljust(256, b"\0")
        package = struct.pack("<HHII", 0x0200, 288, 288, 127) + name + bytes(288 - 12 - 256)
        table = struct.pack("<HHII", 0x0002, 12, 12 + len(package), 1) + package
        out = axml.set_table_package(table, "old.pkg", "much.longer.package")
        self.assertEqual(len(out), len(table))
        self.assertEqual(out[24:24 + 38].decode("utf-16-le"), "much.longer.package")
        self.assertEqual(out[24 + 38:24 + 256], bytes(256 - 38))
        with self.assertRaises(ValueError):
            axml.set_table_package(table, "other", "x")


class LabelTest(unittest.TestCase):
    """The app's name replaces the reference to its string resource."""

    def test_label_text_replaces_the_reference(self):
        for utf8 in (True, False):
            doc = manifest(utf8)
            before, _, _ = read(doc)
            strings, _, elements = read(axml.set_application_label(doc, "TECHNIKA Q (이름)"))
            # Existing strings keep their indexes; the new one is last.
            self.assertEqual(strings[:len(before)], before)
            self.assertEqual(strings[-1], "TECHNIKA Q (이름)")
            label = [a for a in elements["application"] if a[0] == LABEL]
            self.assertEqual(label, [(LABEL, axml.TYPE_STRING, len(strings) - 1)])

    def test_refuses_a_document_that_is_not_binary_xml(self):
        with self.assertRaises(ValueError):
            axml.set_application_label(b"<manifest/>", "x")


if __name__ == "__main__":
    unittest.main()
