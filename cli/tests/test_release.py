"""A release's files (.github/release_assets.py): their names, the check before anything is published, the notes' table
of which file is for whom, and every program and guide that names them."""

import hashlib
import importlib.util
import io
import json
import os
import re
import struct
import sys
import tarfile
import tempfile
import unittest
import unittest.mock
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The version the made-up release carries.
V = "1.2.3"


def load(name):
    """A script of .github/ (outside any package) as a module."""
    sys.path.insert(0, os.path.join(ROOT, ".github"))
    try:
        spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, ".github", name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(os.path.join(ROOT, ".github"))


assets = load("release_assets")
signing = assets.signing
# A key made for these tests alone: the checks below take it in place of the project's (TestKey), and nothing outside
# them ever does. Its seed is fixed so that a failure reads the same each time.
TEST_SEED = bytes(range(32))
TEST_KEY = signing.public_key(TEST_SEED).hex()


class TestKey:
    """Mixed into a test case: while it runs, the signing module takes the test's key alone, as a launcher built for a
    test takes its own (signing.KEYS)."""

    def setUp(self):
        super().setUp()
        kept = signing.KEYS
        signing.KEYS = (TEST_KEY,)
        self.addCleanup(setattr, signing, "KEYS", kept)


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as f:
        return f.read()


def program(machine=assets.X64):
    """The first bytes of a Windows program for `machine` (x64 unless said), as its header has them."""
    head = bytearray(b"MZ" + bytes(0x3E))
    # The PE header right after the DOS header: its place at 0x3C, then "PE\0\0" and the machine type.
    struct.pack_into("<I", head, 0x3C, 0x40)
    return bytes(head) + b"PE\0\0" + struct.pack("<H", machine) + bytes(64)


def package(path, version, files=None, test_keys=""):
    """A package as vpk makes it, small: its manifest at the top, the launcher's files under lib/app, and the file of a
    test build's keys (empty in a release's)."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("OpenDMTQ.Client.nuspec", f"<package><metadata><id>OpenDMTQ.Client</id><version>{version}</version>"
                                             "<rid>win-x64</rid></metadata></package>")
        z.writestr("lib/app/OpenDMTQ.exe", program())
        z.writestr("lib/app/_internal/opendmtq_client/update-test-keys.txt", test_keys)
        for name, data in (files or {}).items():
            z.writestr(name, data)


def made_release(folder, version=V, machine=assets.X64, delta=False, signed=True, test_keys=""):
    """A release's files as the release job lays them out, small: each with what check() reads of it; with `delta`, the
    delta package from 1.2.2 too, and with `signed`, the checksums signed with the test's key."""
    names = assets.expected(version, delta)
    path = {k: os.path.join(folder, n) for k, n in names.items()}
    with open(path["client"], "wb") as f:
        f.write(program(machine))
    with zipfile.ZipFile(path["server-windows"], "w") as z:
        z.writestr("OpenDMTQ/OpenDMTQ.exe", program(machine))
        z.writestr("OpenDMTQ/runtime/python/python.exe", program(machine))
        z.writestr("OpenDMTQ/app/VERSION", version + "\n")
    with tarfile.open(path["chart"], "w:gz") as t:
        chart = f'apiVersion: v2\nname: opendmtq\nversion: {version}\nappVersion: "{version}"\n'.encode()
        info = tarfile.TarInfo("opendmtq/Chart.yaml")
        info.size = len(chart)
        t.addfile(info, io.BytesIO(chart))
    with zipfile.ZipFile(path["runtime"], "w") as z:
        for member in ("bundle.json", "arm64-v8a/libarm32.so", "armeabi-v7a/libopendmtq.so"):
            z.writestr(member, member)
    # The package: a zip with its manifest at the top, as vpk makes it.
    package(path["package"], version, test_keys=test_keys)
    feed = {"Assets": [{"PackageId": "OpenDMTQ.Client", "Version": version, "Type": "Full", "FileName": names["package"],
                        "SHA256": assets.sha256(path["package"]).upper(), "Size": os.path.getsize(path["package"]),
                        "FilesSHA256": signing.files_sha256(path["package"])}]}
    if delta:
        # The delta package from the release before, and that release's full package as vpk lists it (in its own
        # release, not in this one).
        package(path["delta"], version, {"lib/app/OpenDMTQ.exe.zsdiff": b"patch"})
        feed["Assets"].append({"PackageId": "OpenDMTQ.Client", "Version": version, "Type": "Delta",
                               "FileName": names["delta"], "SHA256": assets.sha256(path["delta"]).upper(),
                               "Size": os.path.getsize(path["delta"])})
        feed["Assets"].append({"PackageId": "OpenDMTQ.Client", "Version": "1.2.2", "Type": "Full",
                               "FileName": "opendmtq.client-1.2.2-full.nupkg", "SHA256": "AB" * 32, "Size": 1})
    # vpk writes its feed with a byte-order mark: read as it comes.
    with open(path["feed"], "w", encoding="utf-8-sig") as f:
        json.dump(feed, f)
    with open(path["sums"], "w", encoding="utf-8") as f:
        f.write("".join(f"{assets.sha256(path[k])}  {n}\n" for k, n in names.items() if k not in assets.NOT_SUMMED))
    if signed:
        with open(path["sums"], "rb") as f:
            data = f.read()
        with open(path["sig"], "wb") as f:
            f.write(signing.sign(TEST_SEED, data))
    else:
        path.pop("sig")
    return path


class NamesTest(unittest.TestCase):
    """DEP-50: one scheme, saying what each file is, for which system and architecture, and which version, all in lower
    case."""

    def test_each_name_says_its_version_and_what_it_runs_on(self):
        names = assets.names(V)
        self.assertEqual(names["client"], "opendmtq-pc-client-1.2.3-windows-x64-setup.exe")
        self.assertEqual(names["server-windows"], "opendmtq-server-1.2.3-windows-x64.zip")
        self.assertEqual(names["chart"], "opendmtq-server-1.2.3-helm-chart.tgz")
        self.assertEqual(names["runtime"], "opendmtq-phone-runtime-1.2.3-android-arm64-armv7.zip")
        self.assertEqual(names["package"], "opendmtq.client-1.2.3-full.nupkg")
        self.assertEqual(names["delta"], "opendmtq.client-1.2.3-delta.nupkg")
        self.assertEqual(names["sums"], "opendmtq-1.2.3-sha256sums.txt")
        self.assertEqual(names["sig"], "opendmtq-1.2.3-sha256sums.txt.sig")
        for key, name in names.items():
            # One way of writing them: no capital letter anywhere.
            self.assertEqual(name, name.lower(), key)
            # The feed's name is Velopack's, fixed by the launchers already installed; every other has the version.
            if key != "feed":
                self.assertIn(V, name, key)
        # Nine files: what the last release had and nobody needs (the player alone, the bundle's own .sha256, the
        # installer's .version, Velopack's RELEASES and assets.win.json) is gone; the delta package and the
        # signature of the checksums came. A release with no release before it has no delta package.
        self.assertEqual(len(names), 9)
        self.assertEqual(len(assets.expected(V, delta=False)), 8)

    def test_the_update_feed_keeps_the_name_installed_launchers_look_for(self):
        # Velopack's GitHub source reads releases.<channel>.json, channel win, and the package its FileName gives, under
        # any name; the package id inside is the install folder's name (client/opendmtq_client/installed.py).
        self.assertEqual(assets.names(V)["feed"], "releases.win.json")
        self.assertEqual(assets.PACKAGE_ID, "OpenDMTQ.Client")
        self.assertEqual(assets.BUILT_PACKAGE.format(version=V), "OpenDMTQ.Client-1.2.3-full.nupkg")
        # The launcher's repair finds the installed package in any case: the installer's as the id is written, an
        # update's as the release names it.
        self.assertIn("n.lower() == want", read("client", "opendmtq_client", "repair.py"))
        build = read("client", "packaging", "windows", "build.sh")
        self.assertIn("--packId OpenDMTQ.Client ", build)
        self.assertNotIn("--channel", build)
        self.assertIn('rm -f "$OUT/releases/RELEASES" "$OUT/releases/assets.win.json"', build)
        self.assertIn('PACKAGE_ID = "OpenDMTQ.Client"', read("client", "opendmtq_client", "installed.py"))
        # The launcher fetches a release's feed, checksums and signature by these names itself (updates.py).
        updates = read("client", "opendmtq_client", "updates.py")
        self.assertIn('FEED = "releases.win.json"', updates)
        self.assertIn('PACKAGE = "opendmtq.client-{version}-full.nupkg"', updates)
        self.assertIn('DELTA = "opendmtq.client-{version}-delta.nupkg"', updates)
        self.assertEqual(signing.sums_name(V) + signing.SIG_SUFFIX, assets.names(V)["sig"])

    def test_the_servers_fetch_and_take_them_by_the_same_names(self):
        names = assets.names("{version}")
        self.assertIn(f'RELEASE_NAME = "{names["runtime"]}"', read("tools", "opendmtq_tools", "runtime.py"))
        self.assertIn(f'RELEASE_NAME = "{names["client"]}"', read("tools", "opendmtq_tools", "windows_client.py"))
        install = read("host", "install.sh")
        self.assertIn("'" + names["runtime"].format(version="*") + "'", install)
        self.assertIn("'" + names["client"].format(version="*") + "'", install)
        # DEP-69: the kit's signed checksums beside them, and the PC client's updates where the builder takes them from
        # (tools/opendmtq_tools/client_updates.py KIT).
        self.assertIn("kit_file '" + names["sums"].format(version="*") + "'", install)
        self.assertIn('cp "$sums" "$sums.sig" "$REPO/data/apk/"', install)
        for name in (names["feed"], names["package"], names["delta"]):
            self.assertIn(name.replace("{version}", "$version"), install)
        self.assertIn('KIT = "pc-client-updates"', read("tools", "opendmtq_tools", "client_updates.py"))
        self.assertIn('"$REPO/data/apk/pc-client-updates/"', install)

    def test_the_guides_name_the_files_as_a_release_has_them(self):
        guides = ["README.md", "docs/install.md", "docs/windows-player.md", "docs/closed-network.md", "CONTRIBUTING.md",
                  "docs/admin.md", "docs/faq.md", "host/windows/README.txt"]
        text = {g: read(*g.split("/")) for g in guides}
        # The old names a person could look for in a release and not find.
        for old in ("OpenDMTQ-windows.zip", "opendmtq-player-windows.zip", "OpenDMTQ-Setup.exe.version`",
                    "`opendmtq-arm32-runtime.zip`", "RELEASES`", "assets.win.json", "releases/latest/download/"):
            for guide, body in text.items():
                self.assertNotIn(old, body, f"{guide} names {old}")
        # The release's names of 0.11.0's first builds, in capitals, which no release has.
        for old in ("OpenDMTQ-PC-Client", "OpenDMTQ-Server-", "OpenDMTQ-Phone-", "SHA256SUMS", "OpenDMTQ.Client-<",
                    "OpenDMTQ.Client-1"):
            for guide, body in text.items():
                self.assertNotIn(old, body, f"{guide} names {old}")
        # The quick start and the guide download the server for Windows from the release the chart names, under the name
        # that release gives it (.github/doc_versions.py keeps the number right at each release).
        version = re.search(r"^version:\s*(\S+)", read("deploy", "helm", "opendmtq", "Chart.yaml"), re.M).group(1)
        windows = assets.names(version)["server-windows"]
        for guide in ("README.md", "docs/install.md"):
            self.assertIn(f"releases/download/v{version}/{windows}\ntar.exe -xf {windows}\n", text[guide])
        self.assertIn("opendmtq-pc-client-<version>-windows-x64-setup.exe", text["docs/windows-player.md"])
        self.assertIn("opendmtq-<version>-sha256sums.txt", text["docs/install.md"])


class CheckTest(TestKey, unittest.TestCase):
    """DEP-51: the check before anything is published finds what a person or a program would trip over."""

    def setUp(self):
        # The test's key in place of the project's first (TestKey).
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = self._tmp.name

    def test_a_whole_release_passes(self):
        made_release(self.folder)
        self.assertEqual(assets.check(V, self.folder), [])

    def test_a_missing_file_and_one_more_are_said(self):
        path = made_release(self.folder)
        os.remove(path["runtime"])
        open(os.path.join(self.folder, "RELEASES"), "w").close()
        problems = assets.check(V, self.folder)
        self.assertIn("opendmtq-phone-runtime-1.2.3-android-arm64-armv7.zip is missing", problems)
        self.assertIn("RELEASES is not one of the release's files", problems)

    def test_programs_for_another_machine_are_said(self):
        # 32-bit x86 (IMAGE_FILE_MACHINE_I386): a name that says x64 must hold x64.
        made_release(self.folder, machine=0x14C)
        problems = assets.check(V, self.folder)
        self.assertTrue(any("setup.exe is not a Windows program for x64" in p for p in problems), problems)
        self.assertTrue(any("OpenDMTQ/OpenDMTQ.exe is not a Windows program for x64" in p for p in problems), problems)

    def test_another_version_inside_is_said(self):
        made_release(self.folder, version="1.2.2")
        # Named for 1.2.2 throughout: under 1.2.3 every name is wrong.
        self.assertTrue(assets.check(V, self.folder))
        for name in os.listdir(self.folder):
            os.rename(os.path.join(self.folder, name), os.path.join(self.folder, name.replace("1.2.2", V)))
        problems = assets.check(V, self.folder)
        self.assertTrue(any("says version 1.2.2" in p for p in problems), problems)
        self.assertTrue(any("Chart.yaml has no 'version: 1.2.3'" in p for p in problems), problems)

    def test_a_feed_that_does_not_name_the_package_beside_it_is_said(self):
        path = made_release(self.folder)
        with open(path["package"], "ab") as f:
            f.write(b" changed after the feed was written")
        problems = assets.check(V, self.folder)
        self.assertIn("releases.win.json gives opendmtq.client-1.2.3-full.nupkg another size or hash", problems)

    def test_a_name_with_a_capital_letter_is_said(self):
        path = made_release(self.folder)
        # The same file under the name as vpk writes it: one too many, and not in lower case.
        os.rename(path["package"], os.path.join(self.folder, "OpenDMTQ.Client-1.2.3-full.nupkg"))
        problems = assets.check(V, self.folder)
        self.assertIn("opendmtq.client-1.2.3-full.nupkg is missing", problems)
        self.assertIn("OpenDMTQ.Client-1.2.3-full.nupkg is not all lower case", problems)

    def test_a_package_of_another_program_or_machine_is_said(self):
        path = made_release(self.folder)
        with zipfile.ZipFile(path["package"], "w") as z:
            z.writestr("Other.App.nuspec", "<package><metadata><id>Other.App</id><version>1.2.3</version>"
                                           "<rid>win-arm64</rid></metadata></package>")
        problems = assets.check(V, self.folder)
        self.assertIn("opendmtq.client-1.2.3-full.nupkg's manifest has no <id>OpenDMTQ.Client</id>", problems)
        self.assertIn("opendmtq.client-1.2.3-full.nupkg's manifest has no <rid>win-x64</rid>", problems)

    def built(self, delta=True):
        """The builds' own outputs, under the names they are built with: the installer as PyInstaller makes it, the
        packages and the feed as vpk writes them (named after the program's id, the feed naming them so, without the
        files' field the layout adds). Returns (the made-up release's paths, the client's folder, vpk's feed)."""
        built = os.path.join(self.folder, "built")
        client = os.path.join(built, "client")
        os.makedirs(client)
        path = made_release(built, delta=delta, signed=False)
        os.rename(path["client"], os.path.join(client, "OpenDMTQ-Setup.exe"))
        os.rename(path["package"], os.path.join(client, "OpenDMTQ.Client-1.2.3-full.nupkg"))
        if delta:
            os.rename(path["delta"], os.path.join(client, "OpenDMTQ.Client-1.2.3-delta.nupkg"))
        with open(path["feed"], encoding="utf-8-sig") as f:
            feed = json.load(f)
        for asset in feed["Assets"]:
            asset.pop("FilesSHA256", None)
            if asset["Version"] == V:
                asset["FileName"] = "OpenDMTQ.Client-1.2.3-%s.nupkg" % asset["Type"].lower()
        with open(os.path.join(client, "releases.win.json"), "w", encoding="utf-8") as f:
            json.dump(feed, f)
        # What vpk also writes, which the release leaves out, and the release before's package vpk made the delta from.
        open(os.path.join(client, "RELEASES"), "w").close()
        open(os.path.join(client, "OpenDMTQ.Client-1.2.2-full.nupkg"), "w").close()
        return path, client, feed

    def test_layout_names_the_built_files_and_checks_them(self):
        path, client, feed = self.built()
        out = os.path.join(self.folder, "release")
        key = os.path.join(self.folder, "test.key")
        with open(key, "w", encoding="ascii") as f:
            f.write(TEST_SEED.hex() + "\n")
        with unittest.mock.patch.dict(os.environ, {"OPENDMTQ_SIGNING_KEY": key}):
            self.assertEqual(assets.layout(V, out, path["runtime"], client, path["server-windows"], path["chart"]), [])
        self.assertEqual(sorted(os.listdir(out)), sorted(assets.names(V).values()))
        # The feed names the packages by the release's names, with the same hashes and sizes: the bytes did not change.
        with open(os.path.join(out, "releases.win.json"), encoding="utf-8") as f:
            laid = json.load(f)["Assets"]
        self.assertEqual([a["FileName"] for a in laid], ["opendmtq.client-1.2.3-full.nupkg",
                                                         "opendmtq.client-1.2.3-delta.nupkg",
                                                         "opendmtq.client-1.2.2-full.nupkg"])
        for asset, was in zip(laid, feed["Assets"]):
            self.assertEqual({k: v for k, v in asset.items() if k not in ("FileName", "FilesSHA256")},
                             {k: v for k, v in was.items() if k != "FileName"})


class SignedTest(TestKey, unittest.TestCase):
    """DEP-60: the release's checksums are signed with the project's key, which the layout takes from
    OPENDMTQ_SIGNING_KEY alone; nothing unsigned, signed by another key or built for a test passes the check."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = self._tmp.name

    def test_a_signed_release_passes_and_its_signature_checks_out_by_openssls_rules(self):
        path = made_release(self.folder, delta=True)
        self.assertEqual(assets.check(V, self.folder), [])
        # 64 bytes, Ed25519 over the checksums file's bytes as they are: what openssl pkeyutl -verify -rawin checks.
        with open(path["sig"], "rb") as f:
            signature = f.read()
        with open(path["sums"], "rb") as f:
            self.assertTrue(signing.verify(bytes.fromhex(TEST_KEY), f.read(), signature))
        self.assertEqual(len(signature), 64)

    def test_no_signature_or_another_keys_is_refused(self):
        path = made_release(self.folder, signed=False)
        self.assertIn("opendmtq-1.2.3-sha256sums.txt.sig is missing", assets.check(V, self.folder))
        # A rehearsal is checked without it.
        self.assertEqual(assets.check(V, self.folder, signed=False), [])
        with open(path["sums"], "rb") as f:
            data = f.read()
        with open(os.path.join(self.folder, assets.names(V)["sig"]), "wb") as f:
            f.write(signing.sign(bytes(32), data))
        self.assertIn("opendmtq-1.2.3-sha256sums.txt.sig is not the OpenDMTQ project's signature of "
                      "opendmtq-1.2.3-sha256sums.txt", assets.check(V, self.folder))

    def test_checksums_changed_after_they_were_signed_are_refused(self):
        path = made_release(self.folder)
        with open(path["sums"], "a", encoding="utf-8") as f:
            f.write("%s  extra.txt\n" % ("0" * 64))
        problems = assets.check(V, self.folder)
        self.assertIn("opendmtq-1.2.3-sha256sums.txt.sig is not the OpenDMTQ project's signature of "
                      "opendmtq-1.2.3-sha256sums.txt", problems)

    def test_a_launcher_built_for_a_test_is_refused(self):
        made_release(self.folder, test_keys=TEST_KEY + "\n")
        self.assertIn("opendmtq.client-1.2.3-full.nupkg's launcher takes a test's key: it is a test build, not a release",
                      assets.check(V, self.folder))

    def test_the_layout_signs_with_the_key_the_variable_names_and_with_no_other(self):
        check = CheckTest("test_layout_names_the_built_files_and_checks_them")
        check.folder = self.folder
        path, client, _ = check.built()
        out = os.path.join(self.folder, "release")
        args = (V, out, path["runtime"], client, path["server-windows"], path["chart"])
        # No key named: nothing is laid out, and it says why.
        with unittest.mock.patch.dict(os.environ, {"OPENDMTQ_SIGNING_KEY": ""}):
            with self.assertRaises(SystemExit) as stop:
                assets.layout(*args)
            self.assertIn("not signed", str(stop.exception))
            self.assertFalse(os.path.exists(out))
            # A rehearsal lays out without one, and says it is not signed.
            self.assertEqual(assets.layout(*args, signed=False), [])
            self.assertNotIn(assets.names(V)["sig"], os.listdir(out))
        # A name that is no file is a mistake, never a quiet release without its signature.
        with unittest.mock.patch.dict(os.environ, {"OPENDMTQ_SIGNING_KEY": os.path.join(self.folder, "nowhere.key")}):
            with self.assertRaises(SystemExit):
                assets.layout(*args)
        # A key no launcher takes: refused, and its signature is not left there.
        other = os.path.join(self.folder, "other.key")
        with open(other, "w", encoding="ascii") as f:
            f.write("11" * 32 + "\n")
        with unittest.mock.patch.dict(os.environ, {"OPENDMTQ_SIGNING_KEY": other}):
            with self.assertRaises(SystemExit) as stop:
                assets.layout(*args)
            self.assertIn("is not the project's", str(stop.exception))
        self.assertNotIn(assets.names(V)["sig"], os.listdir(out))

    def test_the_project_key_is_the_one_in_the_launcher_the_tools_and_the_guides(self):
        # One module, byte for byte, in the tools and in the launcher: the same keys, the same checks.
        self.assertEqual(read("tools", "opendmtq_tools", "signing.py"), read("client", "opendmtq_client", "signing.py"))
        key = re.search(r'^KEYS = \("([0-9a-f]{64})",\)$', read("tools", "opendmtq_tools", "signing.py"), re.M)
        self.assertIsNotNone(key)
        for guide in ("docs/install.md", "docs/windows-player.md", "docs/closed-network.md"):
            self.assertIn(key.group(1), read(*guide.split("/")), guide)
        self.assertIn(signing.pem(key.group(1)).strip(), read("docs", "install.md"))
        # A test build's keys never enter the repository.
        ignored = read(".gitignore")
        self.assertIn("update-test-keys.txt", ignored)


class DeltaTest(TestKey, unittest.TestCase):
    """DEP-61: the delta package from the release before is laid out, summed and named by the feed, and the feed gives
    the files the full package holds, by which a launcher checks a package put together from the delta."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = self._tmp.name

    def test_the_delta_package_is_summed_and_named_by_the_feed(self):
        path = made_release(self.folder, delta=True)
        self.assertEqual(assets.check(V, self.folder), [])
        with open(path["sums"], encoding="utf-8") as f:
            self.assertIn("  opendmtq.client-1.2.3-delta.nupkg\n", f.read())
        # The feed names a delta package that is not there: said.
        os.remove(path["delta"])
        self.assertIn("opendmtq.client-1.2.3-delta.nupkg is missing", assets.check(V, self.folder))

    def test_a_feed_without_the_full_packages_files_is_refused(self):
        path = made_release(self.folder)
        with open(path["feed"], encoding="utf-8-sig") as f:
            feed = json.load(f)
        feed["Assets"][0]["FilesSHA256"] = "0" * 64
        with open(path["feed"], "w", encoding="utf-8") as f:
            json.dump(feed, f)
        problems = assets.check(V, self.folder)
        self.assertIn("releases.win.json does not give the files of opendmtq.client-1.2.3-full.nupkg (FilesSHA256)",
                      problems)

    def test_the_files_sha256_is_the_same_whatever_zipped_them(self):
        # Velopack puts a package together from a delta and zips it again: another order, another compression.
        one, other = os.path.join(self.folder, "one.zip"), os.path.join(self.folder, "other.zip")
        with zipfile.ZipFile(one, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("lib/app/a.txt", b"a")
            z.writestr("lib/app/b.txt", b"b")
        with zipfile.ZipFile(other, "w", zipfile.ZIP_STORED) as z:
            z.writestr("lib/app/", b"")
            z.writestr("lib\\app\\b.txt", b"b")
            z.writestr("lib/app/a.txt", b"a")
        self.assertEqual(signing.files_sha256(one), signing.files_sha256(other))
        self.assertNotEqual(assets.sha256(one), assets.sha256(other))
        with zipfile.ZipFile(other, "a") as z:
            z.writestr("lib/app/c.txt", b"c")
        self.assertNotEqual(signing.files_sha256(one), signing.files_sha256(other))

    def test_the_build_makes_the_delta_from_the_release_before(self):
        build = read("client", "packaging", "windows", "build.sh")
        # The previous release's full package beside the new one, and vpk with zstd, which makes the delta.
        self.assertIn("OPENDMTQ_PREVIOUS_RELEASE", build)
        self.assertIn("zstd", build)
        self.assertIn("previous.py", build)


class NotesTest(unittest.TestCase):
    """DEP-52: the release notes are the changelog's section of the version, as the project's other releases have them:
    no table of files (their names say what each is, and docs/install.md says it at length)."""

    def test_release_notes_are_the_changelog_section_alone(self):
        notes = load("release_notes")
        chart, _ = notes.chart_versions(notes.ROOT)
        out = io.StringIO()
        from contextlib import redirect_stdout
        with redirect_stdout(out):
            self.assertEqual(notes.main(["v" + chart, "--root", ROOT]), 0)
        text = out.getvalue()
        # Exactly the section, each paragraph on one line, and nothing before or after it.
        section = notes.section(read("CHANGELOG.md"), chart)
        self.assertEqual(text, notes.unwrap(section) + "\n")
        # No table of files and no heading of the notes' own.
        self.assertNotIn("Which file is for you", text)
        self.assertNotIn("## What changed in", text)

    def test_install_guide_names_every_file_a_person_downloads(self):
        # What the notes no longer say, the install guide does: every file a person downloads, by its name's pattern.
        guide = read("docs", "install.md")
        for key in ("client", "server-windows", "chart"):
            name = dict((k, n) for k, n, _, _ in assets.FILES)[key].replace("{version}", "<version>")
            self.assertIn(name, guide, key)


class WorkflowTest(unittest.TestCase):
    """DEP-53: release.yml lays the files out and checks them before it pushes anything, and publishes those alone."""

    def test_the_files_are_checked_before_the_first_push_and_published_alone(self):
        workflow = read(".github", "workflows", "release.yml")
        layout = workflow.index("python3 .github/release_assets.py layout")
        self.assertLess(layout, workflow.index("push: true"))
        self.assertLess(layout, workflow.index("helm push"))
        # DEP-62: without the project's key (which GitHub never has) the job stops before it builds or pushes anything.
        refuse = workflow.index("A release is signed")
        self.assertLess(refuse, workflow.index("uses: docker/setup-qemu-action"))
        self.assertIn("OPENDMTQ_SIGNING_KEY", workflow[refuse:workflow.index("uses: docker/setup-qemu-action")])
        self.assertNotIn("--unsigned", workflow)
        self.assertIn('gh release create "$GITHUB_REF_NAME" dist/release/* \\', workflow)
        # Nothing else on the release: the old names are not handed to gh any more.
        release = workflow[workflow.index("gh release create"):]
        for old in ("opendmtq-player-windows.zip", "OpenDMTQ-windows.zip.sha256", "dist/client/*"):
            self.assertNotIn(old, release)

    def test_the_release_is_there_before_anything_names_it(self):
        # DEP-117: .github/release.sh publishes the tag, then the release with its files on it, then the images and the
        # chart that names them, and main last: the README's quick start on main and the Linux line download this
        # version's files from the release, which is there before main names it (main pushed main and the tag first, then
        # built the images for minutes, and every quick-start line answered 404 until the release was made).
        script = read(".github", "release.sh")
        body = script[script.index("\npublish() {"):script.index("\nstep publish publish")]
        order = [body.index(step) for step in ('git push origin "v$VERSION"', 'gh release create "v$VERSION"', "\n  images\n",
                                               "helm push", "git push origin HEAD:main")]
        self.assertEqual(order, sorted(order), body)
        self.assertEqual(body.count("git push"), 2)
        self.assertIn("--verify-tag", body)

    def test_the_rehearsal_names_the_same_steps(self):
        # The update proof under Wine (tests/release/update.sh) reads both sides as release_assets.py lays them out.
        script = read("tests", "release", "update.sh")
        self.assertIn("releases.win.json", script)
        self.assertIn("GithubSource(", script)
        stub = read("tests", "release", "github_stub.py")
        self.assertIn("/api/v3/repos/", stub)


if __name__ == "__main__":
    unittest.main()
