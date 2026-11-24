"""The launcher's updates: the version it shows (one source for the logo's, the Launcher page's and the command line's,
the installed version first), and where an update comes from and what is checked before it goes in: its server's
/updates/ first and GitHub's releases second, the server's version as the newest it takes, the release's checksums
signed by the project, the package fetched into a folder of the launcher's own and checked there before anything goes
into packages\\, a delta package when the installed version is the one it starts from, the whole package otherwise.

The releases are made up here and signed with a key made for these tests (TEST_SEED), which the signing module takes in
place of the project's while a test runs; a stand-in answers for the server and for GitHub on a port of this machine."""

import ast
import hashlib
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import urllib.parse
import zipfile
from unittest import mock

from opendmtq_client import __version__, i18n, signing, updates
from opendmtq_client import state as st

from tests.base import Folder

PACKAGE = os.path.join(os.path.dirname(__file__), "..", "opendmtq_client")
# The test's own key pair, and another nobody takes.
TEST_SEED, OTHER_SEED = bytes(range(32)), bytes(range(1, 33))
TEST_KEY = signing.public_key(TEST_SEED).hex()
# The repository the stand-in answers for, as a build writes it into update-source.txt.
REPO = "/kanggu12/openDMTQ"


def package_bytes(version, files=None, compression=zipfile.ZIP_DEFLATED, order=1):
    """A package as vpk makes it, small: its manifest at the top, the launcher's files under lib/app (Update.exe's copy
    among them), in the order given (1 or -1), compressed as given."""
    entries = [("OpenDMTQ.Client.nuspec", "<package><metadata><id>OpenDMTQ.Client</id><version>%s</version>"
                                          "<rid>win-x64</rid></metadata></package>" % version),
               ("lib/app/OpenDMTQ.exe", "launcher " + version),
               ("lib/app/Squirrel.exe", "updater " + version)]
    entries += sorted((files or {}).items())
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression) as z:
        for name, data in entries[::order]:
            z.writestr(name, data)
    return out.getvalue()


def made_release(version, base=None, seed=TEST_SEED, delta=True):
    """{file name: bytes} of a release as .github/release_assets.py lays it out: the feed, the full package, the delta
    package from `base` (when given), the checksums and their signature with `seed`."""
    full = package_bytes(version, {"lib/app/new.txt": "new in " + version})
    files = {"opendmtq.client-%s-full.nupkg" % version: full}
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(full)
    try:
        files_sha = signing.files_sha256(f.name)
    finally:
        os.remove(f.name)
    assets = [{"PackageId": "OpenDMTQ.Client", "Version": version, "Type": "Full",
               "FileName": "opendmtq.client-%s-full.nupkg" % version, "SHA256": hashlib.sha256(full).hexdigest().upper(),
               "Size": len(full), "FilesSHA256": files_sha}]
    if base and delta:
        patch = package_bytes(version, {"lib/app/OpenDMTQ.exe.zsdiff": "patch"})
        files["opendmtq.client-%s-delta.nupkg" % version] = patch
        assets.append({"PackageId": "OpenDMTQ.Client", "Version": version, "Type": "Delta",
                       "FileName": "opendmtq.client-%s-delta.nupkg" % version,
                       "SHA256": hashlib.sha256(patch).hexdigest().upper(), "Size": len(patch)})
    if base:
        # The release before's full package, as vpk lists the one it made the delta from (in its own release).
        assets.append({"PackageId": "OpenDMTQ.Client", "Version": base, "Type": "Full",
                       "FileName": "opendmtq.client-%s-full.nupkg" % base, "SHA256": "AB" * 32, "Size": 10})
    files["releases.win.json"] = b"\xef\xbb\xbf" + json.dumps({"Assets": assets}, separators=(",", ":")).encode()
    sums = "".join("%s  %s\n" % (hashlib.sha256(data).hexdigest(), name) for name, data in files.items())
    files[signing.sums_name(version)] = sums.encode()
    files[signing.sums_name(version) + ".sig"] = signing.sign(seed, sums.encode())
    return files


class Stand:
    """A stand-in on a port of this machine for one OpenDMTQ server (its /updates/ and client.php?about) and for
    GitHub's releases of the repository: what each holds is a field a test sets, and every request is kept."""

    def __init__(self):
        self.server_files = None       # {name: bytes} at /updates/, or None: a server that hands out none
        self.server_version = "0.11.0"  # what client.php?about says
        self.releases = {}             # {version: {name: bytes}} on GitHub; the newest is the latest
        self.requests = []             # the paths asked for, in order
        stand = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                # Quiet: the test's own output only.
                pass

            def send(self, code, body=b"", headers=()):
                self.send_response(code)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def do_HEAD(self):
                self.do_GET()

            def do_GET(self):
                path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
                stand.requests.append(path)
                if path == "/opendmtq/client.php":
                    about = {"opendmtq": stand.server_version, "name": "Stand-in", "address": "127.0.0.1", "app": True}
                    return self.send(200, json.dumps(about).encode(), [("Content-Type", "application/json")])
                if path.startswith("/updates/"):
                    found = (stand.server_files or {}).get(path[len("/updates/"):])
                    return self.send(200, found) if found is not None else self.send(404, b"not found")
                if path == REPO + "/releases/latest":
                    newest = max(stand.releases, key=lambda v: tuple(int(n) for n in v.split(".")))
                    return self.send(302, headers=[("Location", "%s/releases/tag/v%s" % (REPO, newest))])
                if path.startswith(REPO + "/releases/tag/"):
                    return self.send(200, b"<html>a release</html>")
                prefix = REPO + "/releases/download/v"
                if path.startswith(prefix):
                    version, _, name = path[len(prefix):].partition("/")
                    found = stand.releases.get(version, {}).get(name)
                    return self.send(200, found) if found is not None else self.send(404, b"not found")
                self.send(404, b"not found")

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def asked(self, start):
        """The paths asked for that start so."""
        return [p for p in self.requests if p.startswith(start)]


class Velopack:
    """A stand-in for the velopack module as the launcher uses it: the version installed, and the hand-over to Update.exe
    once the launcher has ended, kept for the test to read."""

    def __init__(self, version="0.11.0"):
        self.version, self.applied = version, []
        outer = self

        class UpdateManager:
            def __init__(self, source=None, options=None, locator=None):
                pass

            def get_current_version(self):
                return outer.version

            def check_for_updates(self):
                raise AssertionError("Velopack's own check reads a feed nobody checked: never used")

            def download_updates(self, info, progress=None):
                raise AssertionError("Velopack's own download writes into packages\\ unchecked: never used")

            def wait_exit_then_apply_updates(self, asset, silent=False, restart=True, restart_args=None):
                outer.applied.append((asset.FileName, asset.Version, silent, restart))

        self.module = types.SimpleNamespace(
            UpdateManager=UpdateManager,
            VelopackAsset=lambda *a: types.SimpleNamespace(**dict(zip(
                ("PackageId", "Version", "Type", "FileName", "SHA1", "SHA256", "Size", "NotesMarkdown", "NotesHtml"), a))))


class Updates(Folder):
    """A launcher installed at 0.11.0 (a made-up install folder, OPENDMTQ_INSTALL_ROOT), playing on the stand-in's
    server, with the stand-in's GitHub built in; the test's key taken in place of the project's."""

    installed = "0.11.0"

    def setUp(self):
        super().setUp()
        self.stand = Stand()
        self.addCleanup(self.stand.stop)
        kept = signing.KEYS
        signing.KEYS = (TEST_KEY,)
        self.addCleanup(setattr, signing, "KEYS", kept)
        # The install folder as Velopack's setup lays it out: the version, its package, Update.exe.
        self.root = os.path.join(self.home, "install")
        os.makedirs(os.path.join(self.root, "current"))
        os.makedirs(os.path.join(self.root, "packages"))
        with open(os.path.join(self.root, "current", "sq.version"), "w", encoding="utf-8") as f:
            f.write("<package><metadata><version>%s</version></metadata></package>" % self.installed)
        self.base_package = os.path.join(self.root, "packages", "OpenDMTQ.Client-%s-full.nupkg" % self.installed)
        with open(self.base_package, "wb") as f:
            f.write(package_bytes(self.installed))
        with open(os.path.join(self.root, "Update.exe"), "w", encoding="utf-8") as f:
            f.write("updater %s" % self.installed)
        self.velopack = Velopack(self.installed)
        patches = [mock.patch.dict(os.environ, {"OPENDMTQ_INSTALL_ROOT": self.root}),
                   mock.patch.dict(sys.modules, {"velopack": self.velopack.module}),
                   mock.patch.object(updates, "UPDATE_SOURCE", self.stand.base + REPO),
                   # The launcher's own temporary folders under the test's own.
                   mock.patch.object(updates.tempfile, "gettempdir", lambda: self.temp)]
        self.temp = os.path.join(self.home, "tmp")
        os.makedirs(self.temp)
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.state = st.LauncherState()
        self.state.add_server(self.stand.base, name="Stand-in")

    def packages(self):
        return sorted(os.listdir(os.path.join(self.root, "packages")))

    def updater_text(self):
        with open(os.path.join(self.root, "Update.exe"), encoding="utf-8") as f:
            return f.read()


class WhereFrom(Updates):
    """WIN-200: the server PLAY plays on first, GitHub second; the server's version the newest a launcher takes."""

    def test_the_servers_update_first_and_github_never_asked(self):
        self.stand.server_files = made_release("0.11.1", base="0.11.0")
        self.stand.releases = {"0.11.2": made_release("0.11.2", base="0.11.1")}
        result = updates.check(self.state)
        self.assertEqual((result.kind, result.version, result.source.kind), ("available", "0.11.1", "server"))
        self.assertEqual(self.stand.asked(REPO), [])
        # Its words name the server it comes from.
        self.assertEqual(result.source.label(), "Stand-in (%s)" % self.stand.base)

    def test_a_server_that_hands_out_its_own_version_keeps_the_launcher_there(self):
        # The server is older than GitHub's latest: the launcher stays with the server's version.
        self.stand.server_files = made_release("0.11.0")
        self.stand.releases = {"0.11.2": made_release("0.11.2", base="0.11.1")}
        result = updates.check(self.state)
        self.assertEqual((result.kind, result.source.kind), ("uptodate", "server"))
        self.assertEqual(self.stand.asked(REPO), [])

    def test_a_server_without_updates_lets_github_in_up_to_its_own_version(self):
        # A server older than 0.11.0 has no /updates/: GitHub's release of the server's version, not the latest.
        self.stand.server_version = "0.11.1"
        self.stand.releases = {"0.11.1": made_release("0.11.1", base="0.11.0"),
                               "0.11.2": made_release("0.11.2", base="0.11.1")}
        result = updates.check(self.state)
        self.assertEqual((result.kind, result.version, result.source.kind), ("available", "0.11.1", "github"))
        self.assertIn(REPO + "/releases/download/v0.11.1/releases.win.json", self.stand.requests)
        self.assertNotIn(REPO + "/releases/download/v0.11.2/releases.win.json", self.stand.requests)
        # A server of the version installed: nothing newer for it.
        self.stand.server_version = "0.11.0"
        self.assertEqual(updates.check(self.state).kind, "uptodate")

    def test_a_server_past_its_release_lets_github_in_up_to_that_release(self):
        # A server run from a copy past a release says the release and its commit (0.11.2-29a49e4, as the command line
        # names a clone's version), or a release still to come (0.11.2-rc.1), with no updates of its own: GitHub's
        # release of those numbers, a tag that is there, never one named after the commit.
        self.stand.releases = {"0.11.1": made_release("0.11.1", base="0.11.0"),
                               "0.11.2": made_release("0.11.2", base="0.11.1")}
        for said in ("0.11.2-29a49e4", "0.11.2-rc.1", "0.11.2+build.5"):
            self.stand.server_version = said
            result = updates.check(self.state)
            self.assertEqual((result.kind, result.version, result.source.kind), ("available", "0.11.2", "github"), said)
        self.assertNotIn(REPO + "/releases/download/v0.11.2-29a49e4/releases.win.json", self.stand.requests)
        # Past an older release than GitHub's latest: that release, not the latest.
        self.stand.server_version = "0.11.1-29a49e4"
        result = updates.check(self.state)
        self.assertEqual((result.kind, result.version, result.source.kind), ("available", "0.11.1", "github"))

    def test_without_a_server_githubs_latest(self):
        self.state.remove_server(self.stand.base)
        self.stand.releases = {"0.11.1": made_release("0.11.1", base="0.11.0"),
                               "0.11.2": made_release("0.11.2", base="0.11.1")}
        result = updates.check(self.state)
        self.assertEqual((result.kind, result.version, result.source.kind), ("available", "0.11.2", "github"))
        self.assertEqual(self.stand.asked("/updates/"), [])

    def test_a_server_that_does_not_answer_sends_the_launcher_nowhere_else(self):
        self.state.remove_server(self.stand.base)
        self.state.add_server("http://127.0.0.1:9", name="Gone")
        self.stand.releases = {"0.11.2": made_release("0.11.2", base="0.11.1")}
        result = updates.check(self.state)
        self.assertEqual(result.kind, "failed")
        self.assertEqual(self.stand.asked(REPO), [])

    def test_velopacks_own_check_and_download_are_never_used(self):
        # The stand-in velopack raises in both: a check and an update go through without them.
        self.stand.server_files = made_release("0.11.1")
        result = updates.check(self.state)
        updates.apply(result, run=lambda *a, **k: self.fail("no delta here"))
        self.assertEqual(self.velopack.applied, [("opendmtq.client-0.11.1-full.nupkg", "0.11.1", True, True)])


class Signatures(Updates):
    """WIN-201: an update is taken only from a release whose checksums the project signed, and whose feed is the file
    they sum; anything else is refused, and said."""

    def test_a_signature_by_another_key_is_refused(self):
        self.stand.server_files = made_release("0.11.1", seed=OTHER_SEED)
        result = updates.check(self.state)
        self.assertEqual(result.kind, "refused")
        self.assertIn("not signed by the OpenDMTQ project", result.error)

    def test_checksums_or_a_feed_changed_after_the_signature_are_refused(self):
        files = made_release("0.11.1")
        changed = dict(files)
        changed[signing.sums_name("0.11.1")] = files[signing.sums_name("0.11.1")] + b"0" * 64 + b"  x.txt\n"
        self.stand.server_files = changed
        self.assertEqual(updates.check(self.state).kind, "refused")
        changed = dict(files)
        feed = json.loads(files["releases.win.json"].decode("utf-8-sig"))
        feed["Assets"][0]["SHA256"] = "00" * 32
        changed["releases.win.json"] = json.dumps(feed).encode()
        self.stand.server_files = changed
        result = updates.check(self.state)
        self.assertEqual(result.kind, "refused")
        self.assertIn("is not the feed the release 0.11.1 signed", result.error)

    def test_a_release_without_signed_checksums_is_refused(self):
        # As every release before 0.11.0: a feed and its package, no signature.
        files = made_release("0.11.1")
        del files[signing.sums_name("0.11.1") + ".sig"]
        self.stand.server_files = files
        result = updates.check(self.state)
        self.assertEqual(result.kind, "refused")
        self.assertIn("has no signed checksums", result.error)

    def test_signed_checksums_of_another_release_do_not_pass_for_this_one(self):
        # 0.11.1's feed with 0.11.2's checksums and signature under 0.11.1's names: refused by the names they sum.
        files = made_release("0.11.1")
        other = made_release("0.11.2")
        files[signing.sums_name("0.11.1")] = other[signing.sums_name("0.11.2")]
        files[signing.sums_name("0.11.1") + ".sig"] = other[signing.sums_name("0.11.2") + ".sig"]
        self.stand.server_files = files
        self.assertEqual(updates.check(self.state).kind, "refused")

    def test_a_tampered_package_is_refused_and_nothing_reaches_the_install_folder(self):
        files = made_release("0.11.1")
        name = "opendmtq.client-0.11.1-full.nupkg"
        # One byte changed in the middle: the size the feed gives, so that only the hash tells.
        middle = len(files[name]) // 2
        files[name] = files[name][:middle] + bytes([files[name][middle] ^ 0xFF]) + files[name][middle + 1:]
        self.stand.server_files = files
        result = updates.check(self.state)
        self.assertEqual(result.kind, "available")
        before, updater = self.packages(), self.updater_text()
        with self.assertRaises(updates.UpdateError) as refused:
            updates.apply(result)
        self.assertEqual(refused.exception.key, "error.update.unsigned")
        self.assertIn("not signed by the OpenDMTQ project", str(refused.exception))
        # Nothing handed over, nothing in packages\, Update.exe as it was, nothing left in the temporary folder.
        self.assertEqual(self.velopack.applied, [])
        self.assertEqual(self.packages(), before)
        self.assertEqual(self.updater_text(), updater)
        self.assertEqual(os.listdir(self.temp), [])

    def test_a_package_whose_manifest_is_another_version_is_refused(self):
        # Signed as it is (a release's own file, another version inside): what Velopack would put in is the manifest's.
        files = made_release("0.11.1")
        name = "opendmtq.client-0.11.1-full.nupkg"
        files[name] = package_bytes("0.11.9")
        feed = json.loads(files["releases.win.json"].decode("utf-8-sig"))
        feed["Assets"][0].update(SHA256=hashlib.sha256(files[name]).hexdigest(), Size=len(files[name]))
        files["releases.win.json"] = json.dumps(feed).encode()
        sums = "".join("%s  %s\n" % (hashlib.sha256(files[n]).hexdigest(), n) for n in (name, "releases.win.json"))
        files[signing.sums_name("0.11.1")] = sums.encode()
        files[signing.sums_name("0.11.1") + ".sig"] = signing.sign(TEST_SEED, sums.encode())
        self.stand.server_files = files
        with self.assertRaises(updates.UpdateError):
            updates.apply(updates.check(self.state))
        self.assertEqual(self.velopack.applied, [])

    def test_names_that_leave_the_folder_are_refused_before_anything_is_fetched(self):
        files = made_release("0.11.1")
        feed = json.loads(files["releases.win.json"].decode("utf-8-sig"))
        feed["Assets"][0]["FileName"] = "..\\..\\Update.exe"
        files["releases.win.json"] = json.dumps(feed).encode()
        sums = files[signing.sums_name("0.11.1")].decode().splitlines()
        sums = [line for line in sums if not line.endswith("releases.win.json")]
        sums.append("%s  releases.win.json" % hashlib.sha256(files["releases.win.json"]).hexdigest())
        files[signing.sums_name("0.11.1")] = ("\n".join(sums) + "\n").encode()
        files[signing.sums_name("0.11.1") + ".sig"] = signing.sign(TEST_SEED, files[signing.sums_name("0.11.1")])
        self.stand.server_files = files
        result = updates.check(self.state)
        asked = len(self.stand.requests)
        with self.assertRaises(updates.UpdateError):
            updates.apply(result)
        self.assertEqual(len(self.stand.requests), asked)


class Packages(Updates):
    """WIN-202: the package fetched and checked in a folder of the launcher's own, then handed into packages\\; the
    delta package for the version it starts from, put together by the installed Update.exe and checked by the files
    the release signed; the whole package when the delta does not give that."""

    def patcher(self, how="same files"):
        """A stand-in for Update.exe patch: writes the package the release built, zipped again ("same files"), with a
        file of its own ("other files"), or fails ("fails"). Keeps what it was given."""
        self.patched = []

        def run(args, **kwargs):
            self.patched.append(args)
            out = args[args.index("--output") + 1]
            if how == "fails":
                return subprocess.CompletedProcess(args, 1, b"", b"zstd: checksum mismatch")
            extra = {"lib/app/new.txt": "new in 0.11.1"}
            if how == "other files":
                extra["lib/app/stale.txt"] = "left from the base"
            with open(out, "wb") as f:
                f.write(package_bytes("0.11.1", extra, compression=zipfile.ZIP_STORED, order=-1))
            return subprocess.CompletedProcess(args, 0, b"", b"")
        return run

    def test_the_whole_package_goes_into_packages_after_its_check(self):
        self.stand.server_files = made_release("0.11.1")
        updates.apply(updates.check(self.state))
        self.assertIn("opendmtq.client-0.11.1-full.nupkg", self.packages())
        with open(os.path.join(self.root, "packages", "opendmtq.client-0.11.1-full.nupkg"), "rb") as f:
            self.assertEqual(f.read(), self.stand.server_files["opendmtq.client-0.11.1-full.nupkg"])
        # Update.exe as the checked package carries it, as Velopack's own download leaves it.
        self.assertEqual(self.updater_text(), "updater 0.11.1")
        # The installed version's package stays until the new one runs (outcome), for Repair.
        self.assertIn(os.path.basename(self.base_package), self.packages())
        self.assertEqual(os.listdir(self.temp), [])

    def test_the_delta_package_for_the_installed_version(self):
        self.stand.server_files = made_release("0.11.1", base="0.11.0")
        run = self.patcher()
        updates.apply(updates.check(self.state), run=run)
        # Update.exe put it together from the installed package, in the launcher's own folder.
        args = self.patched[0]
        self.assertEqual(args[1:4], ["patch", "--old", self.base_package])
        self.assertTrue(args[args.index("--output") + 1].startswith(self.temp))
        self.assertEqual(self.stand.asked("/updates/opendmtq.client-0.11.1-full.nupkg"), [])
        self.assertEqual(len(self.stand.asked("/updates/opendmtq.client-0.11.1-delta.nupkg")), 1)
        # Zipped again, so not the bytes signed: taken by the files it holds.
        with open(os.path.join(self.root, "packages", "opendmtq.client-0.11.1-full.nupkg"), "rb") as f:
            self.assertNotEqual(f.read(), self.stand.server_files["opendmtq.client-0.11.1-full.nupkg"])
        self.assertEqual(self.velopack.applied, [("opendmtq.client-0.11.1-full.nupkg", "0.11.1", True, True)])

    def test_a_delta_that_does_not_give_the_package_signed_falls_back_to_the_whole_one(self):
        for how in ("fails", "other files"):
            with self.subTest(how):
                self.stand.requests.clear()
                self.velopack.applied.clear()
                self.stand.server_files = made_release("0.11.1", base="0.11.0")
                told = []
                updates.apply(updates.check(self.state), tell=told.append, run=self.patcher(how))
                self.assertEqual(told, ["whole"])
                self.assertEqual(len(self.stand.asked("/updates/opendmtq.client-0.11.1-full.nupkg")), 1)
                with open(os.path.join(self.root, "packages", "opendmtq.client-0.11.1-full.nupkg"), "rb") as f:
                    self.assertEqual(f.read(), self.stand.server_files["opendmtq.client-0.11.1-full.nupkg"])
                self.assertEqual(len(self.velopack.applied), 1)

    def test_a_delta_the_server_does_not_hand_out_gives_the_whole_package(self):
        # The feed names it, the server has it not (404): said in the log as a warning, and the whole package comes.
        files = made_release("0.11.1", base="0.11.0")
        del files["opendmtq.client-0.11.1-delta.nupkg"]
        self.stand.server_files = files
        told = []
        with self.assertLogs("opendmtq_client", "INFO") as said:
            updates.apply(updates.check(self.state), tell=told.append, run=self.patcher())
        self.assertEqual(told, ["whole"])
        self.assertEqual(self.patched, [])
        self.assertEqual(len(self.velopack.applied), 1)
        self.assertFalse([line for line in said.output if line.startswith("ERROR")], said.output)

    def test_a_delta_that_is_not_the_one_signed_never_reaches_update_exe(self):
        files = made_release("0.11.1", base="0.11.0")
        files["opendmtq.client-0.11.1-delta.nupkg"] = b"x" * len(files["opendmtq.client-0.11.1-delta.nupkg"])
        self.stand.server_files = files
        told = []
        updates.apply(updates.check(self.state), tell=told.append, run=self.patcher())
        self.assertEqual(self.patched, [])
        self.assertEqual(told, ["whole"])
        self.assertEqual(len(self.velopack.applied), 1)

    def test_a_launcher_of_another_version_than_the_deltas_takes_the_whole_package(self):
        # The delta starts from 0.10.5: this launcher (0.11.0) would patch a package that is not its base.
        self.stand.server_files = made_release("0.11.1", base="0.10.5")
        updates.apply(updates.check(self.state), run=self.patcher())
        self.assertEqual(self.patched, [])
        self.assertEqual(self.stand.asked("/updates/opendmtq.client-0.11.1-delta.nupkg"), [])

    def test_the_earlier_packages_go_once_the_new_version_runs(self):
        self.stand.server_files = made_release("0.11.1")
        updates.apply(updates.check(self.state))
        self.velopack.version = "0.11.1"
        self.assertEqual(updates.outcome(), ("updated", "0.11.1"))
        self.assertEqual(self.packages(), ["opendmtq.client-0.11.1-full.nupkg"])

    def test_an_update_from_github_is_fetched_by_its_tag(self):
        self.state.remove_server(self.stand.base)
        self.stand.releases = {"0.11.1": made_release("0.11.1")}
        updates.apply(updates.check(self.state))
        self.assertIn(REPO + "/releases/download/v0.11.1/opendmtq.client-0.11.1-full.nupkg", self.stand.requests)
        self.assertEqual(len(self.velopack.applied), 1)


class Words(Updates):
    """WIN-203: what the Launcher page and the command line say of where an update comes from and of one refused."""

    def test_the_server_is_named_and_a_refusal_is_said(self):
        self.stand.server_files = made_release("0.11.1")
        for language in ("en", "ko"):
            w = i18n.Words(language)
            self.assertIn("Stand-in", w("about.available.from", v="0.11.1", source="Stand-in"))
            self.assertIn("OpenDMTQ", w("about.refused", source="Stand-in"))
            self.assertIn("0.11.1", w("error.update.unsigned", v="0.11.1", source="Stand-in"))
        self.assertEqual(i18n.Words("ko")("about.refused", source="Stand-in"),
                         "Stand-in의 업데이트는 OpenDMTQ 프로젝트가 서명한 것이 아니어서 설치하지 않습니다.")


class Trickled(Folder):
    """A package from a server's /updates/ or GitHub's releases sent a byte at a time, each byte within a read's wait:
    given up at FILE_SECONDS, never given the whole day (main: for as long as the server trickled, here 5 s)."""

    def test_a_package_that_trickles_in_is_given_up_in_time(self):
        from tests.test_server import Trickling, timed
        server = Trickling(what="body", kind="application/octet-stream")
        self.addCleanup(server.stop)
        folder = os.path.join(self.home, "fetched")
        os.makedirs(folder)
        asset = {"FileName": "opendmtq.client-9.9.9-full.nupkg", "Size": 2 << 20}
        # A second for the whole file, two for a read: the reads of a byte each come well within theirs.
        with mock.patch.object(updates, "FILE_SECONDS", 1), mock.patch.object(updates, "READ_SECONDS", 2):
            for source in (updates.Source("server", server.base), updates.Source("github", server.base)):
                result = updates.Result("available", version="9.9.9", source=source)
                took, out = timed(lambda: updates._fetch(result, asset, folder))
                self.assertIsInstance(out, updates.UpdateError, source.kind)
                self.assertEqual(out.key, "error.update.download")
                self.assertLess(took, 2.5, source.kind)


class ShownVersion(unittest.TestCase):
    """WIN-125: the version the launcher shows."""

    def test_the_installed_version_first(self):
        # Velopack's installed version: what the installer put in and the updates moved on.
        with mock.patch.object(updates, "current_version", return_value="9.8.7"):
            self.assertEqual(updates.shown_version(), "9.8.7")

    def test_the_codes_own_outside_an_install(self):
        # Run from source or a copied folder: no installed version, the code's own.
        with mock.patch.object(updates, "current_version", return_value=None):
            self.assertEqual(updates.shown_version(), __version__)

    def test_the_logo_shows_the_same_version(self):
        # The menu column's version block beside the wordmark (app.make_rail) takes it from shown_version, as the
        # Launcher page does: an installed 9.8.7 is v9.8.7 there, whatever the code says.
        from opendmtq_client import app as app_module
        from opendmtq_client import art, widgets
        fake = types.SimpleNamespace(scale=1.0, ui=None)
        with mock.patch.object(updates, "current_version", return_value="9.8.7"), \
                mock.patch.object(art, "brand") as brand, mock.patch.object(widgets, "Rail"):
            app_module.LauncherApp.make_rail(fake, None)
        self.assertEqual(brand.call_args[0][1], "v9.8.7")

    def test_no_other_place_works_the_version_out_itself(self):
        # Every place that shows the launcher's version asks shown_version: the installed version is asked for in
        # updates.py alone, so that the logo, the Launcher page and --status cannot drift apart again.
        asking = []
        for name in sorted(os.listdir(PACKAGE)):
            if not name.endswith(".py") or name == "updates.py":
                continue
            with open(os.path.join(PACKAGE, name), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            # A call of current_version() anywhere but in updates.py is a place that works it out on its own.
            asking.extend(name for node in ast.walk(tree) if isinstance(node, ast.Call)
                          and isinstance(node.func, ast.Attribute) and node.func.attr == "current_version")
        self.assertEqual(asking, [])


class SameModule(unittest.TestCase):
    """WIN-204: the launcher checks with the very module the server's tools check with, and with the project's key."""

    def test_the_signing_module_is_the_tools_own(self):
        here = os.path.join(PACKAGE, "signing.py")
        tools = os.path.join(PACKAGE, "..", "..", "tools", "opendmtq_tools", "signing.py")
        if not os.path.isfile(tools):
            self.skipTest("the tools are not beside this copy of the launcher")
        with open(here, "rb") as one, open(tools, "rb") as other:
            self.assertEqual(one.read(), other.read())

    def test_rfc_8032s_signatures_check_out(self):
        # RFC 8032, 7.1, TEST 2: a one-byte message.
        seed = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
        public = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
        signature = bytes.fromhex("92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
                                  "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")
        self.assertEqual(signing.public_key(seed), public)
        self.assertEqual(signing.sign(seed, b"\x72"), signature)
        self.assertTrue(signing.verify(public, b"\x72", signature))
        self.assertFalse(signing.verify(public, b"\x73", signature))

    def test_a_test_builds_keys_come_from_its_file_alone(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        path = os.path.join(folder, "update-test-keys.txt")
        with open(path, "w", encoding="ascii") as f:
            f.write(TEST_KEY.upper() + "\nnot a key\n")
        self.assertEqual(signing.added_keys(path), (TEST_KEY,))
        open(path, "w").close()
        self.assertEqual(signing.added_keys(path), ())
        # The repository's copy has no such file: the project's key alone.
        self.assertFalse(os.path.exists(signing.TEST_KEYS_FILE))


if __name__ == "__main__":
    unittest.main()
