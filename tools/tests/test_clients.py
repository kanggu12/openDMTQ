"""Tests for the clients the patcher builds from: what an APK is (the original, one changed for another server, an app
OpenDMTQ built, anything else), how a changed one is pointed at this server, and which client is used when there are
several. The APKs are small zips with the real layouts: metadata from il2cpp.build, a binary manifest made here."""

import io
import json
import os
import struct
import tempfile
import time
import unittest
import zipfile
from unittest import mock

from opendmtq_tools import axml, il2cpp, patch_apk, unity_assets

HOST = "192.168.0.10"
NS = "http://schemas.android.com/apk/res/android"
NO_INDEX = 0xFFFFFFFF
# The official addresses of the original client, and those of a made-up other server.
ORIGINAL = [patch_apk.MARKER, "https://dmqglb-dq.mb.pmang.com/DMQ/rpc", "http://www.neonapi.com/api", "http://pmangplus.com"]
OTHER = ["http://play.example.net/DMQ/rpc", "http://play.example.net/DMQ/rpc", "http://play.example.net/api",
         "http://play.example.net"]
# Literals every client has besides: a policy page that stays as it is.
COMMON = ["Startup", "http://www.pmangplus.com/mobile/policies/tos"]


def manifest(package="com.neowizinternet.game.technikaq_g_a", version="1.3.4", code=1661):
    """A binary <manifest package=... android:versionCode=... android:versionName=...> with an empty <application>."""
    strings = ["versionCode", "versionName", "package", "android", NS, "manifest", "application", version, package]
    ids = [axml.ATTR_VERSION_CODE, axml.ATTR_VERSION_NAME]
    idx = {s: i for i, s in enumerate(strings)}
    data = bytearray()
    offsets = []
    for s in strings:
        offsets.append(len(data))
        b = s.encode("utf-8")
        data += bytes([len(s), len(b)]) + b + b"\0"
    while len(data) % 4:
        data.append(0)
    start = 28 + 4 * len(strings)
    pool = struct.pack("<HHIIIIII", 1, 28, start + len(data), len(strings), 0, 0x100, start, 0)
    pool += struct.pack(f"<{len(strings)}I", *offsets) + bytes(data)
    resmap = struct.pack("<HHI", 0x0180, 8, 8 + 4 * len(ids)) + struct.pack(f"<{len(ids)}I", *ids)

    def element(name, attrs):
        body = struct.pack("<IIHHHHHH", NO_INDEX, idx[name], 20, 20, len(attrs), 0, 0, 0)
        for ns, aname, raw, atype, value in attrs:
            body += struct.pack("<IIIHBBI", ns, idx[aname], raw, 8, 0, atype, value)
        return struct.pack("<HHIII", 0x0102, 16, 16 + len(body), 1, NO_INDEX) + body

    def end(name):
        return struct.pack("<HHIIIII", 0x0103, 16, 24, 1, NO_INDEX, NO_INDEX, idx[name])

    nodes = struct.pack("<HHIIIII", 0x0100, 16, 24, 1, NO_INDEX, idx["android"], idx[NS])
    nodes += element("manifest", [(idx[NS], "versionCode", NO_INDEX, 0x10, code),
                                  (idx[NS], "versionName", idx[version], 0x03, idx[version]),
                                  (NO_INDEX, "package", idx[package], 0x03, idx[package])])
    nodes += element("application", []) + end("application") + end("manifest")
    nodes += struct.pack("<HHIIIII", 0x0101, 16, 24, 1, NO_INDEX, idx["android"], idx[NS])
    body = pool + resmap + nodes
    return struct.pack("<HHI", 3, 8, 8 + len(body)) + body


def apk(path, literals=None, dex=b"dex\n035\0Lcom/pmangplus/core/PPCore;", game_code=b"game code", **info):
    """A small APK at path: its manifest (info: package, version, code), code, metadata (when literals are given) and
    game code."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AndroidManifest.xml", manifest(**info))
        z.writestr("classes.dex", dex)
        if literals is not None:
            z.writestr(patch_apk.METADATA, il2cpp.build(literals))
        z.writestr(patch_apk.CODE_FILE, game_code)
    return path


class InspectTest(unittest.TestCase):
    """What an APK is, from its own contents and never its name."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = tmp.name

    def test_the_original(self):
        info = patch_apk.inspect(apk(os.path.join(self.d, "a.apk"), COMMON + ORIGINAL))
        self.assertEqual((info["kind"], info["version"], info["hosts"]), ("original", "1.3.4", []))
        self.assertTrue(patch_apk.is_patchable(os.path.join(self.d, "a.apk")))

    def test_one_changed_for_another_server(self):
        info = patch_apk.inspect(apk(os.path.join(self.d, "a.apk"), COMMON + OTHER, version="1.3.5", code=1859))
        self.assertEqual((info["kind"], info["version"], info["hosts"]), ("other server", "1.3.5", ["play.example.net"]))
        self.assertTrue(patch_apk.is_patchable(os.path.join(self.d, "a.apk")))

    def test_an_app_opendmtq_built(self):
        # Its addresses name a server too: the hook class tells it apart.
        path = apk(os.path.join(self.d, "a.apk"), COMMON + ["http://10.0.0.5/DMQ/rpc"],
                   dex=b"dex\n035\0" + patch_apk.HOOK_CLASS, package=patch_apk.BASE_PACKAGE + ".s0123456789")
        self.assertEqual(patch_apk.inspect(path)["kind"], "built here")
        self.assertFalse(patch_apk.is_patchable(path))

    def test_anything_else(self):
        other_app = apk(os.path.join(self.d, "app.apk"), package="org.example.player")
        no_rpc = apk(os.path.join(self.d, "game.apk"), COMMON)
        broken = os.path.join(self.d, "broken.apk")
        with open(broken, "wb") as f:
            f.write(b"PK\3\4 not really")
        for path in (other_app, no_rpc, broken):
            self.assertEqual(patch_apk.inspect(path)["kind"], "not the game", path)
            self.assertFalse(patch_apk.is_patchable(path))

    def test_the_client_the_code_edits_were_made_for(self):
        # Every code edit fits, each in one of its versions; a client that one does not fit is not that client.
        path = apk(os.path.join(self.d, "a.apk"), COMMON + ORIGINAL, game_code=b"the code, 1.3.5")
        fits = [("one", {"1.3.4": [(0, b"xxx", b"yyy")], "1.3.5": [(4, b"code", b"CODE")]}), ("two", {"1.3.4": [(10, b"1.3.5", b"1.3.6")]})]
        with mock.patch.object(patch_apk, "IL2CPP_EDITS", fits):
            self.assertTrue(patch_apk.inspect(path)["known"])
        with mock.patch.object(patch_apk, "IL2CPP_EDITS", fits + [("three", {"1.3.4": [(0, b"zzz", b"yyy")]})]):
            self.assertFalse(patch_apk.inspect(path)["known"])

    def test_described_in_a_few_words(self):
        info = {"kind": "other server", "version": "1.3.5", "hosts": ["play.example.net"], "known": False}
        self.assertEqual(patch_apk.describe(info),
                         "client 1.3.5, changed for another server (play.example.net): pointed at this one instead")
        self.assertEqual(patch_apk.describe({**info, "kind": "original", "version": None}), "client, original")


class AddressTest(unittest.TestCase):
    """A client changed for another server reaches this one: every address on that server's host, in the game's
    literals and in the SDK's code."""

    def test_the_literals_of_the_other_server_all_point_here(self):
        meta = il2cpp.Metadata(il2cpp.build(COMMON + OTHER + ["http://play.example.net:8080/www", "play.example.network"]))
        edits = patch_apk.address_edits(meta, HOST)
        self.assertEqual(edits, {
            "http://play.example.net/DMQ/rpc": f"http://{HOST}/DMQ/rpc",
            "http://play.example.net/api": f"http://{HOST}/api",
            "http://play.example.net": f"http://{HOST}",
            "http://play.example.net:8080/www": f"http://{HOST}/www",
        })

    def test_the_original_keeps_its_four_edits(self):
        meta = il2cpp.Metadata(il2cpp.build(COMMON + ORIGINAL))
        self.assertEqual(patch_apk.address_edits(meta, HOST), patch_apk.metadata_edits(HOST))

    def test_the_metadata_is_rewritten_with_both_copies_of_the_rpc(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(patch_apk, "log"):
            path = os.path.join(d, "global-metadata.dat")
            with open(path, "wb") as f:
                f.write(il2cpp.build(COMMON + OTHER))
            self.assertEqual(patch_apk.patch_metadata(path, HOST), ["play.example.net"])
            with open(path, "rb") as f:
                meta = il2cpp.Metadata(f.read())
            self.assertEqual(len(meta.find(f"http://{HOST}/DMQ/rpc")), 2)
            self.assertEqual(meta.find("http://play.example.net/DMQ/rpc"), [])
            self.assertEqual(len(meta.find(COMMON[1])), 1)

    def test_the_sdk_strings_on_that_host_point_here_and_nothing_else(self):
        files = {
            "smali/com/x/ApiHost.smali": 'const-string v3, "play.example.net"\nconst-string v4, "play.example.net/api"\n',
            "smali/com/x/Center.smali": 'const-string v3, "https://play.example.net/www"\nconst-string v3, "not.play.example.net"\n',
            "smali_classes2/com/y/Log.smali": 'const-string v7, "http://play.example.net:8080/api/send/"\n'
                                              'const-string v7, "play.example.network"\n',
            "res/values/strings.xml": "<string>play.example.net</string>\n",
        }
        with tempfile.TemporaryDirectory() as d, mock.patch.object(patch_apk, "log"):
            for rel, text in files.items():
                os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
                with open(os.path.join(d, rel), "w", encoding="utf-8") as f:
                    f.write(text)
            self.assertEqual(patch_apk.redirect_smali(d, ["play.example.net"], HOST), 4)

            def read(rel):
                with open(os.path.join(d, rel), encoding="utf-8") as f:
                    return f.read()
            self.assertEqual(read("smali/com/x/ApiHost.smali"), f'const-string v3, "{HOST}"\nconst-string v4, "{HOST}/api"\n')
            self.assertIn(f'"http://{HOST}/www"', read("smali/com/x/Center.smali"))
            self.assertIn('"not.play.example.net"', read("smali/com/x/Center.smali"))
            self.assertIn(f'"http://{HOST}/api/send/"', read("smali_classes2/com/y/Log.smali"))
            self.assertIn('"play.example.network"', read("smali_classes2/com/y/Log.smali"))
            # Only the code: resources stay as they are.
            self.assertEqual(read("res/values/strings.xml"), files["res/values/strings.xml"])

    def test_the_sdk_edits_made_by_hand_already_count(self):
        # A changed client often has the same edits: its addresses (pointed here by redirect_smali) and plain HTTP.
        with tempfile.TemporaryDirectory() as d, mock.patch.object(patch_apk, "log") as log:
            files = {}
            for rel, old, new, expected in patch_apk.smali_edits(HOST):
                done_by_hand = rel.endswith(("ApiHost.smali", "PPCore.smali", "PPCustomerCenter.smali", "RequestProcessor.smali"))
                files.setdefault(rel, []).append((new if done_by_hand else old) * expected)
            for rel, parts in files.items():
                path = os.path.join(d, "smali", rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n# --\n".join(parts))
            patch_apk.patch_smali(d, HOST)
            said = " ".join(str(c) for c in log.call_args_list)
            self.assertIn("already", said)
            with open(os.path.join(d, "smali", "com/pmangplus/core/internal/request/RequestProcessor$ApiHost.smali"),
                      encoding="utf-8") as f:
                self.assertEqual(f.read().count(f'"{HOST}"'), 2)

    def test_a_package_name_of_its_own_is_replaced(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(patch_apk, "log"):
            with open(os.path.join(d, "AndroidManifest.xml"), "wb") as f:
                f.write(manifest(package="net.example.freeserver"))
            name = "net.example.freeserver".encode("utf-16-le").ljust(256, b"\0")
            package = struct.pack("<HHII", 0x0200, 288, 288, 127) + name + bytes(288 - 12 - 256)
            with open(os.path.join(d, "resources.arsc"), "wb") as f:
                f.write(struct.pack("<HHII", 0x0002, 12, 12 + len(package), 1) + package)
            patch_apk.patch_package(d, "com.example.new")
            with open(os.path.join(d, "AndroidManifest.xml"), "rb") as f:
                self.assertEqual(axml.manifest_info(f.read())["package"], "com.example.new")


class ManifestInfoTest(unittest.TestCase):
    def test_package_and_version(self):
        self.assertEqual(axml.manifest_info(manifest(package="a.b", version="1.3.5", code=1859)),
                         {"package": "a.b", "version": "1.3.5", "code": 1859})

    def test_not_binary_xml(self):
        with self.assertRaises(ValueError):
            axml.manifest_info(b"<manifest/>")


class ChoiceTest(unittest.TestCase):
    """Which client is used when data/apk/base holds several different ones."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.apk = tmp.name
        self.base = os.path.join(tmp.name, "base")
        os.makedirs(self.base)
        os.makedirs(os.path.join(tmp.name, "out"))

    def client(self, name, literals, age=0, **info):
        path = apk(os.path.join(self.base, name), COMMON + literals, **info)
        os.utime(path, (time.time() - age, time.time() - age))
        return path

    def chosen(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO) as said:
            return os.path.basename(patch_apk.find_base(self.base)), said.getvalue()

    def test_the_newest_version_before_an_older_one(self):
        # An original 1.3.4 and a 1.3.5 changed for another server: the game's last version, whatever it was changed for.
        self.client("original.apk", ORIGINAL, age=100)
        self.client("changed.apk", OTHER, version="1.3.5")
        name, said = self.chosen()
        self.assertEqual(name, "changed.apk")
        self.assertIn("using changed.apk", said)
        # Versions are numbers: 1.3.10 comes after 1.3.9.
        self.assertGreater(patch_apk.version_key("1.3.10"), patch_apk.version_key("1.3.9"))
        self.assertEqual(patch_apk.version_key(None), ())

    def test_of_one_version_the_original_before_one_changed_for_another_server(self):
        self.client("original.apk", ORIGINAL, age=100, version="1.3.5")
        self.client("changed.apk", OTHER, version="1.3.5")
        self.assertEqual(self.chosen()[0], "original.apk")

    def test_of_one_version_the_client_the_code_edits_fit_first(self):
        self.client("fits.apk", ORIGINAL, age=100, game_code=b"1.3.4 code")
        self.client("other.apk", ORIGINAL, game_code=b"other code")
        with mock.patch.object(patch_apk, "IL2CPP_EDITS", [("edit", {"1.3.4": [(0, b"1.3.4", b"1.3.x")]})]):
            self.assertEqual(self.chosen()[0], "fits.apk")

    def test_of_two_alike_the_newest(self):
        self.client("older.apk", ORIGINAL, age=100, game_code=b"one")
        self.client("newer.apk", ORIGINAL, game_code=b"two")
        self.assertEqual(self.chosen()[0], "newer.apk")

    def test_the_one_the_phones_app_came_from_while_it_is_there(self):
        # The phones have an app of that version: another could not be installed over a higher version number.
        changed = self.client("changed.apk", OTHER, version="1.3.5", code=1859)
        self.client("original.apk", ORIGINAL)
        with open(os.path.join(self.apk, "out", "latest.json"), "w") as f:
            json.dump({"base_sha256": patch_apk.sha256(changed)}, f)
        name, said = self.chosen()
        self.assertEqual(name, "changed.apk")
        self.assertIn("which the last app was built from", said)

    def test_none_usable_names_each_with_what_it_is(self):
        apk(os.path.join(self.base, "friend.apk"), COMMON + ["http://10.0.0.5/DMQ/rpc"], dex=b"dex" + patch_apk.HOOK_CLASS)
        with self.assertRaises(SystemExit) as e:
            patch_apk.find_base(self.base)
        self.assertIn("friend.apk: an app OpenDMTQ built", str(e.exception))
        self.assertIn("./opendmtq import", str(e.exception))
        self.assertNotIn("`", str(e.exception))

    def test_with_no_client_it_names_the_import_of_the_install_it_runs_in(self):
        # The Windows bundle's window shows the builder's words (OpenDMTQ.exe apk, runtime): its own program, never the
        # command of a Linux install; elsewhere ./opendmtq, as before.
        self.assertEqual(patch_apk.CLI, "OpenDMTQ.exe" if os.name == "nt" else "./opendmtq")
        for command in ("OpenDMTQ.exe", "./opendmtq"):
            with mock.patch.object(patch_apk, "CLI", command), self.assertRaises(SystemExit) as e:
                patch_apk.find_base(self.base)
            self.assertEqual(str(e.exception), "no base APK in data/apk/base; run %s import <folder> first" % command)
            # A client that is no game client to build from: the same command in its sentence.
            apk(os.path.join(self.base, "friend.apk"), COMMON + ["http://10.0.0.5/DMQ/rpc"], dex=b"dex" + patch_apk.HOOK_CLASS)
            with mock.patch.object(patch_apk, "CLI", command), self.assertRaises(SystemExit) as e:
                patch_apk.find_base(self.base)
            self.assertIn("with %s import <folder>" % command, str(e.exception))
            os.remove(os.path.join(self.base, "friend.apk"))


class ScreenNeedsTest(unittest.TestCase):
    """A screen edit that goes with a code edit stays out when the code edit did not fit (another client version)."""

    def test_the_shop_tab_stays_when_the_shop_still_opens_on_it(self):
        objects = [(1, "Shop2Scene", 0, True, (0, 0)), (2, "UI_Tab", 1, True, (0, 0)), (3, "Btn_Tab1", 2, True, (0, 0)),
                   (4, "Other", 1, True, (0, 0))]
        data = unity_assets.build(objects)
        edits = {"screen": [("hide", "Shop2Scene/UI_Tab/Btn_Tab1"), ("hide", "Shop2Scene/Other")]}
        need = {"Shop2Scene/UI_Tab/": "the shop edit"}
        for code, tab_shown in ((set(), True), ({"the shop edit"}, False)):
            with tempfile.TemporaryDirectory() as d, mock.patch.object(patch_apk, "ASSET_EDITS", edits), \
                    mock.patch.object(patch_apk, "ASSET_NEEDS", need), mock.patch.object(patch_apk, "log"):
                folder = os.path.join(d, patch_apk.ASSET_DIR)
                os.makedirs(folder)
                with open(os.path.join(folder, "screen"), "wb") as f:
                    f.write(data)
                patch_apk.patch_assets(d, code)
                with open(os.path.join(folder, "screen"), "rb") as f:
                    asset = unity_assets.SerializedFile(f.read())
                self.assertEqual(asset.is_active("Shop2Scene/UI_Tab/Btn_Tab1"), tab_shown, code)
                self.assertFalse(asset.is_active("Shop2Scene/Other"))

    def test_every_need_names_a_code_edit(self):
        names = {what for what, _ in patch_apk.IL2CPP_EDITS}
        for prefix, need in patch_apk.ASSET_NEEDS.items():
            self.assertIn(need, names, prefix)


if __name__ == "__main__":
    unittest.main()
