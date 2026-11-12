"""Tests for the patcher's bookkeeping around a build: the signing key, its scratch space, which
builds it keeps, and how it finds the base APK. apktool, the signer and keytool are faked."""

import contextlib
import errno
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import signal
import stat
import struct
import subprocess
import tempfile
import zipfile
import threading
import time
import unittest
from unittest import mock

from opendmtq_tools import unity_assets, builder, patch_apk

HOST = "192.168.0.10"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Workshop:
    """data/apk in a temporary folder; the external programs write what they would."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.apk = self._tmp.name
        for d in ("base", "out", "keystore"):
            os.makedirs(os.path.join(self.apk, d))
        self.base = self.write("base/client.apk", b"base")
        self.work = os.path.join(self.apk, "scratch")
        # Make apktool's rebuild fail, as a client it cannot rebuild would.
        self.fail_rebuild = False
        # What the signer writes: each build can tell its app apart from the last one's.
        self.signed = b"signed"
        # keytool's command lines and environments, as it was run.
        self.keytool_runs = []
        # The signer's command lines, with the arguments its file held and that file's mode, as it was run.
        self.signer_runs = []

    def path(self, rel):
        return os.path.join(self.apk, rel)

    def write(self, rel, data):
        path = self.path(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb" if isinstance(data, bytes) else "w") as f:
            f.write(data)
        return path

    def manifest(self, rel="out/latest.json"):
        with open(self.path(rel), encoding="utf-8") as f:
            return json.load(f)

    def run(self, cmd, *args, **kwargs):
        if cmd[0] == "java" and cmd[1].startswith("@"):
            # Java's argument file (java @file): its arguments in double quotes, a backslash escaping what follows.
            with open(cmd[1][1:], encoding="utf-8") as f:
                held = [re.sub(r"\\(.)", r"\1", a) for a in re.findall(r'"((?:[^"\\]|\\.)*)"', f.read())]
            self.signer_runs.append((list(cmd), held, stat.S_IMODE(os.stat(cmd[1][1:]).st_mode)))
            cmd = ["java"] + held

        def arg(flag):
            return cmd[cmd.index(flag) + 1]
        if cmd[0] == "keytool":
            self.keytool_runs.append((list(cmd), dict(kwargs.get("env") or {})))
            self.write(os.path.relpath(arg("-keystore"), self.apk), b"new key")
        elif cmd[:3] == ["java", "-jar", patch_apk.APKTOOL] and cmd[3] == "d":
            os.makedirs(arg("-o"))
        elif cmd[:3] == ["java", "-jar", patch_apk.APKTOOL] and cmd[3] == "b":
            if self.fail_rebuild:
                raise subprocess.CalledProcessError(1, cmd)
            self.write(os.path.relpath(arg("-o"), self.apk), b"unsigned")
        elif cmd[:3] == ["java", "-jar", patch_apk.SIGNER]:
            self.write(os.path.relpath(os.path.join(arg("-o"), "unsigned-aligned-signed.apk"), self.apk), self.signed)
        else:
            raise AssertionError(f"unexpected program: {cmd}")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def build(self, *args):
        return patch_apk.main(["--host", HOST, "--stamp", "2026.11.01", *args])

    def status(self):
        """data/apk/out/build.json, as the builder left it."""
        with open(self.path("out/build.json"), encoding="utf-8") as f:
            return json.load(f)

    def __enter__(self):
        self._patches = [
            mock.patch.multiple(patch_apk, APK_DIR=self.apk, WORK=self.work, RUNTIME_DIR=self.path("arm32"),
                                inspect=lambda path: {"kind": "original", "version": "1.3.4", "hosts": [], "known": True},
                                patch_metadata=mock.DEFAULT, redirect_smali=mock.DEFAULT,
                                patch_smali=mock.DEFAULT, patch_il2cpp=mock.DEFAULT, patch_assets=mock.DEFAULT, patch_settings=mock.DEFAULT, log=mock.DEFAULT),
            mock.patch.object(patch_apk, "patch_label", return_value="TECHNIKA Q (test)"),
            mock.patch.object(patch_apk, "patch_package"),
            mock.patch.object(patch_apk, "patch_target"),
            mock.patch.object(patch_apk.qr, "write", create=True),
            mock.patch.object(builder, "OUT", self.path("out")),
            # The installer for Windows only where a test puts one, and no release to fetch it from: no test reaches the
            # internet.
            mock.patch.object(builder.windows_client, "HERE", self.path("no-code")),
            mock.patch.object(builder.windows_client, "RELEASE_URL", "file:///nowhere/" + builder.windows_client.SETUP_NAME),
            mock.patch("subprocess.run", self.run),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()
        return False


class KeyTest(unittest.TestCase):
    def test_first_build_creates_the_key_and_records_it(self):
        with Workshop() as w:
            w.build()
            self.assertEqual(w.manifest()["key_sha256"], sha256(b"new key"))

    def test_a_lost_key_is_not_replaced(self):
        # Phones hold apps signed with the old key; an app signed with a new one cannot update them.
        with Workshop() as w:
            w.write("out/latest.json", json.dumps({"file": "OpenDMTQ-old.apk", "host": HOST,
                                                   "key_sha256": sha256(b"lost key")}))
            with self.assertRaises(SystemExit) as e:
                w.build()
            self.assertIn("restore", str(e.exception))
            self.assertIn("--with-key", str(e.exception))
            self.assertFalse(os.path.exists(w.path("keystore/opendmtq.jks")))

    def test_the_builder_reports_a_lost_key_at_start(self):
        with Workshop() as w:
            w.write("out/OpenDMTQ-old.apk", b"app")
            w.write("out/latest.json", json.dumps({
                "file": "OpenDMTQ-old.apk", "host": HOST, "base_sha256": sha256(b"base"),
                "patcher": patch_apk.VERSION, "key_sha256": sha256(b"lost key"), "runtime": None,
                "label": "TECHNIKA Q (192.168.0.10)"}))
            self.assertIsNotNone(builder.reason_to_build(HOST, w.base))
            # With the key in place the same app is current.
            w.write("keystore/opendmtq.jks", b"lost key")
            self.assertIsNone(builder.reason_to_build(HOST, w.base))

    def test_the_signer_does_not_get_the_password_on_its_command_line(self):
        # Every user of the machine can read a process's command line: the signer's arguments go in a file of this
        # user's alone, gone once it has run.
        with Workshop() as w:
            w.build()
            [(cmd, held, mode)] = w.signer_runs
            with open(w.path("keystore/password.txt"), encoding="utf-8") as f:
                password = f.read().strip()
            self.assertFalse([part for part in cmd if password in part], cmd)
            self.assertEqual(held[held.index("--ksPass") + 1], password)
            self.assertEqual(held[:2], ["-jar", patch_apk.SIGNER])
            self.assertEqual(mode, 0o600)
            self.assertFalse(os.path.exists(cmd[1][1:]))

    def test_keytool_does_not_get_the_password_on_its_command_line(self):
        # A failed run's error (recorded in build.json, shown on the admin pages) and the process
        # list would show it.
        with Workshop() as w:
            w.build()
            [(cmd, env)] = w.keytool_runs
            with open(w.path("keystore/password.txt"), encoding="utf-8") as f:
                password = f.read().strip()
            self.assertNotIn(password, cmd)
            self.assertIn("-storepass:env", cmd)
            self.assertEqual(env.get(cmd[cmd.index("-storepass:env") + 1]), password)


class ScratchTest(unittest.TestCase):
    def test_removed_after_a_build(self):
        with Workshop() as w:
            w.build()
            self.assertFalse(os.path.exists(w.work))

    def test_removed_after_a_failed_build(self):
        with Workshop() as w:
            w.fail_rebuild = True
            with self.assertRaises(subprocess.CalledProcessError):
                w.build()
            self.assertFalse(os.path.exists(w.work))


class KeepTest(unittest.TestCase):
    def test_a_build_for_another_address_keeps_the_portal_download(self):
        with Workshop() as w:
            w.write("keystore/opendmtq.jks", b"key")
            w.write("keystore/password.txt", "pw\n")
            # The portal offers the oldest of ten builds.
            for i in range(10):
                name = f"OpenDMTQ-10.0.0.{i}-v2026.10.{10 + i}.apk"
                os.utime(w.write(f"out/{name}", b"app"), (1_700_000_000 + i, 1_700_000_000 + i))
            offered = "OpenDMTQ-10.0.0.0-v2026.10.10.apk"
            w.write("out/latest.json", json.dumps({"file": offered, "host": "10.0.0.0", "key_sha256": sha256(b"key")}))
            patch_apk.main(["--host", "friend.example.com", "--stamp", "2026.11.01", "--keep-latest"])
            self.assertTrue(os.path.exists(w.path("out/" + offered)))
            self.assertEqual(w.manifest()["file"], offered)
            # Still only the newest ten besides it.
            builds = [f for f in os.listdir(w.path("out")) if f.endswith(".apk")]
            self.assertEqual(len(builds), 11)


class BaseTest(unittest.TestCase):
    def test_a_misspelt_base_apk_says_so(self):
        # BASE_APK=<file name> in .env reaches find_base as given.
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "game.apk"), "wb").close()
            with self.assertRaises(SystemExit) as e:
                patch_apk.find_base(d, "gmae.apk")
            self.assertIn("gmae.apk", str(e.exception))
            self.assertIn("game.apk", str(e.exception))

    def test_of_different_clients_the_newest_is_used(self):
        # A build must still work from the setup pages, which have no way to edit .env. Two clients alike (test_clients
        # has the other orders): the newest.
        alike = {"kind": "original", "version": "1.3.4", "hosts": [], "known": True}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(patch_apk, "inspect", return_value=alike):
            for name, text, age in (("older.apk", b"one", 100), ("newer.apk", b"two", 0)):
                path = os.path.join(d, name)
                with open(path, "wb") as f:
                    f.write(text)
                os.utime(path, (time.time() - age, time.time() - age))
            with mock.patch("sys.stderr", new_callable=io.StringIO) as said:
                self.assertEqual(os.path.basename(patch_apk.find_base(d)), "newer.apk")
            self.assertIn("using newer.apk", said.getvalue())

    def test_no_base_folder_says_what_to_do(self):
        # A fresh install before the import: a message, not a traceback.
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit) as e:
                patch_apk.find_base(os.path.join(d, "base"))
            self.assertIn("opendmtq import", str(e.exception))

    def test_unusable_apks_are_named(self):
        # An APK patched for another server (or another version) in base/: the import would skip it
        # too, so the message names it instead of only sending the owner back to the import. The text
        # also shows on the admin pages: the command is written as typed, without Markdown quotes.
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "changed-client.apk"), "wb").close()
            other = {"kind": "not the game", "version": None, "hosts": [], "known": False}
            with mock.patch.object(patch_apk, "inspect", return_value=other):
                with self.assertRaises(SystemExit) as e:
                    patch_apk.find_base(d)
            self.assertIn("changed-client.apk", str(e.exception))
            self.assertIn("./opendmtq import", str(e.exception))
            self.assertNotIn("`", str(e.exception))


class ReplaceTest(unittest.TestCase):
    """A build for the same address on the same day has the same file name as the app the portal
    offers: it must take that file's place whole, never rewrite it."""

    def test_a_download_in_progress_keeps_the_old_app(self):
        with Workshop() as w:
            w.signed = b"first build"
            name = w.build()
            # A phone halfway through the download holds the file open.
            with open(w.path("out/" + name), "rb") as download:
                w.signed = b"second build, another size"
                self.assertEqual(w.build(), name)
                self.assertEqual(download.read(), b"first build")
            with open(w.path("out/" + name), "rb") as f:
                self.assertEqual(f.read(), b"second build, another size")
            self.assertEqual(w.manifest()["size"], len(b"second build, another size"))

    def test_a_copy_that_fails_half_way_keeps_the_offered_app(self):
        with Workshop() as w:
            w.signed = b"first build"
            name = w.build()
            out = w.path("out")
            real = shutil.copyfile

            def full_disk(src, dst, *args, **kwargs):
                # Into data/apk/out the copy stops after two bytes, as on a full disk.
                if os.path.dirname(os.path.abspath(dst)) == out:
                    with open(dst, "wb") as f:
                        f.write(b"se")
                    raise OSError(errno.ENOSPC, "No space left on device")
                return real(src, dst, *args, **kwargs)

            w.signed = b"second build"
            with mock.patch("shutil.copyfile", full_disk), self.assertRaises(OSError):
                w.build()
            with open(w.path("out/" + name), "rb") as f:
                self.assertEqual(f.read(), b"first build")
            self.assertEqual(w.manifest()["size"], len(b"first build"))
            # Nothing half-copied is left next to it.
            self.assertEqual([f for f in os.listdir(out) if f.endswith(".part")], [])

    def test_a_damaged_app_is_built_again(self):
        # The size the manifest records no longer fits the file (a copy cut short before builds
        # swapped their file in whole): phones would download a broken app.
        with Workshop() as w:
            w.build()
            w.write("out/" + w.manifest()["file"], b"si")
            self.assertIn("damaged", builder.reason_to_build(HOST, w.base) or "")

    def test_builds_wait_for_each_other(self):
        # The builder, the admin pages and ./opendmtq apk may start one each.
        with Workshop() as w:
            with open(w.path("out/.build.lock"), "a") as held:
                fcntl.flock(held, fcntl.LOCK_EX)
                done = []
                worker = threading.Thread(target=lambda: done.append(w.build()))
                worker.start()
                worker.join(0.5)
                # Still waiting, and nothing written yet.
                self.assertTrue(worker.is_alive())
                self.assertFalse(os.path.exists(w.path("out/latest.json")))
                fcntl.flock(held, fcntl.LOCK_UN)
            worker.join(10)
            self.assertFalse(worker.is_alive())
            self.assertEqual(done, [w.manifest()["file"]])


class StatusTest(unittest.TestCase):
    """data/apk/out/build.json: what the portal, the admin pages and ./opendmtq read about the builder's
    last run."""

    def run_builder(self, w, outcome, why="no app built yet"):
        """builder.main with the patcher replaced by outcome (a function standing in for its main), and what it returns.
        why: the reason to build, None for an app that is up to date."""
        with mock.patch.object(builder.patch_apk, "main", outcome), \
                mock.patch.object(builder, "reason_to_build", return_value=why), \
                mock.patch.object(builder.runtime, "add_or_note"), \
                contextlib.redirect_stdout(io.StringIO()):
            return builder.main(["--host", HOST])

    @staticmethod
    def with_an_installer(w):
        """An installer for Windows beside the code, as a release's tools image has one (windows_client.py), and a stand-in
        for the patcher that leaves the app and latest.json as it does: (the patch for the installer's place, the
        stand-in)."""
        code = w.path("code")
        os.makedirs(code, exist_ok=True)
        # The smallest installer the builder takes: a Windows program's first bytes at a believable size, and its version.
        w.write("code/" + builder.windows_client.SETUP_NAME, b"MZ" + bytes(builder.windows_client.SMALLEST))
        w.write("code/" + builder.windows_client.VERSION_NAME, "0.8.0\n")

        def patcher(argv):
            # The app, and latest.json naming it, as the patcher leaves them.
            w.write("out/OpenDMTQ-new.apk", b"PK an app")
            w.write("out/latest.json", json.dumps({"file": "OpenDMTQ-new.apk", "host": HOST, "sha256": sha256(b"PK an app"),
                                                   "label": "TECHNIKA Q (test)", "package": "com.example.app.s1234"}))
            return "OpenDMTQ-new.apk"
        return mock.patch.object(builder.windows_client, "HERE", code), patcher

    def test_the_runtime_for_newer_phones_comes_before_the_question_whether_to_build(self):
        # A runtime that has just come is a reason to build: asked the other way round, the app would go without it until
        # the next start.
        with Workshop() as w:
            order = []
            with mock.patch.object(builder.patch_apk, "main", lambda argv: "OpenDMTQ-new.apk"), \
                    mock.patch.object(builder.runtime, "add_or_note", lambda folder: order.append(("runtime", folder))), \
                    mock.patch.object(builder, "reason_to_build", lambda host, base: order.append(("asked", host)) or "a reason"), \
                    contextlib.redirect_stdout(io.StringIO()):
                builder.main(["--host", HOST])
            self.assertEqual(order, [("runtime", builder.patch_apk.APK_DIR), ("asked", HOST)])
            self.assertEqual(w.status()["state"], "done")

    def test_with_no_app_for_the_address_it_says_building_before_the_runtime(self):
        # The runtime's download can take a minute: all that time the site said nothing was making an app.
        with Workshop() as w:
            seen = []
            with mock.patch.object(builder.patch_apk, "main", lambda argv: "OpenDMTQ-new.apk"), \
                    mock.patch.object(builder.runtime, "add_or_note", lambda folder: seen.append(dict(w.status()))), \
                    mock.patch.object(builder, "reason_to_build", return_value="no app built yet"), \
                    contextlib.redirect_stdout(io.StringIO()):
                builder.main(["--host", HOST])
            self.assertEqual([(s["state"], s["host"]) for s in seen], [("building", HOST)])
            self.assertEqual(w.status()["state"], "done")

    def test_with_an_app_for_the_address_it_says_nothing_until_it_knows(self):
        # An app up to date: no "building" at every start, which the site would show for nothing.
        with Workshop() as w:
            w.write("out/OpenDMTQ-old.apk", b"PK an app")
            w.write("out/latest.json", json.dumps({"file": "OpenDMTQ-old.apk", "host": HOST}))
            seen = []
            with mock.patch.object(builder.runtime, "add_or_note", lambda folder: seen.append(os.path.exists(w.path("out/build.json")))), \
                    mock.patch.object(builder, "reason_to_build", return_value=None), \
                    contextlib.redirect_stdout(io.StringIO()):
                builder.main(["--host", HOST])
            self.assertEqual(seen, [False])
            self.assertEqual(w.status()["state"], "done")

    def test_a_runtime_that_cannot_be_had_stops_no_build(self):
        # The whole way through runtime.py, with nothing at hand and the release out of reach, as on a closed network.
        with Workshop() as w:
            with mock.patch.object(builder.patch_apk, "main", lambda argv: "OpenDMTQ-new.apk"), \
                    mock.patch.object(builder, "reason_to_build", return_value="no app built yet"), \
                    mock.patch.object(builder.runtime, "HERE", "/nowhere"), \
                    mock.patch.object(builder.runtime.urllib.request, "urlopen", side_effect=OSError("no way out")), \
                    contextlib.redirect_stdout(io.StringIO()):
                builder.main(["--host", HOST])
            self.assertEqual((w.status()["state"], w.status()["file"]), ("done", "OpenDMTQ-new.apk"))
            with open(os.path.join(builder.patch_apk.APK_DIR, "runtime-error.txt"), encoding="utf-8") as f:
                self.assertIn("no way out", f.read())

    def test_a_new_app_is_recorded_with_its_file(self):
        with Workshop() as w:
            self.run_builder(w, lambda argv: "OpenDMTQ-new.apk")
            self.assertEqual((w.status()["state"], w.status()["file"]), ("done", "OpenDMTQ-new.apk"))

    def test_a_failing_installer_for_windows_leaves_the_app_done(self):
        # The installer for Windows comes after the app, and whatever goes wrong with it (a full disk, a damaged file,
        # anything at all) leaves phones their app: build.json says done, as it said before the step, for a new app and
        # one up to date.
        for err in (OSError(errno.ENOSPC, "No space left on device"), ValueError("anything"), RuntimeError("anything else")):
            for why in ("no app built yet", None):
                with self.subTest(err=err, why=why), Workshop() as w, \
                        mock.patch.object(builder.windows_client, "keep", side_effect=err):
                    # The run ends as a run that worked: the app is what it is for.
                    self.assertEqual(self.run_builder(w, lambda argv: "OpenDMTQ-new.apk", why), 0)
                    self.assertEqual(w.status()["state"], "done")
                    # "file" only for a new app: the command line tells built from up to date by it.
                    self.assertEqual(w.status().get("file"), "OpenDMTQ-new.apk" if why else None)

    def test_the_app_is_done_before_the_installer_for_windows_is_put_beside_it(self):
        # Phones can have the app while the installer is copied: build.json says so first, on both paths.
        for why in ("no app built yet", None):
            with self.subTest(why=why), Workshop() as w:
                # What build.json said when the step began.
                seen = []
                with mock.patch.object(builder.windows_client, "keep", lambda out: seen.append(w.status()["state"])):
                    self.run_builder(w, lambda argv: "OpenDMTQ-new.apk", why)
                self.assertEqual(seen, ["done"])

    def test_docker_stop_while_the_installer_is_copied_leaves_the_app_done(self):
        # docker stop waits ten seconds, then kills: the step ends at once under the builder's handler, with its file half
        # copied removed, and the app stays done. The next run puts the installer there.
        with Workshop() as w:
            here, patcher = self.with_an_installer(w)

            def stopped(*args, **kwargs):
                # SIGTERM as docker stop sends it, while the installer is copied.
                handler = signal.getsignal(signal.SIGTERM)
                self.assertTrue(callable(handler), "no SIGTERM handler while the installer for Windows is copied")
                handler(signal.SIGTERM, None)
            with here, mock.patch.object(builder.windows_client.shutil, "copyfile", stopped):
                self.assertEqual(self.run_builder(w, patcher), 0)
            self.assertEqual((w.status()["state"], w.status()["file"]), ("done", "OpenDMTQ-new.apk"))
            # Nothing half made, and no windows.json for an installer that is not there.
            self.assertEqual(sorted(os.listdir(w.path("out"))), ["OpenDMTQ-new.apk", "build.json", "latest.json"])
            # The next run, with the app up to date, puts the installer beside it.
            with here:
                self.run_builder(w, patcher, None)
            self.assertIn(builder.windows_client.SETUP_NAME, os.listdir(w.path("out")))
            self.assertEqual(builder.windows_client.current(w.path("out"))["version"], "0.8.0")

    def test_ctrl_c_is_recorded(self):
        # Without it build.json said "building" until the portal gave up on it fifteen minutes later.
        def interrupted(argv):
            raise KeyboardInterrupt
        with Workshop() as w:
            with self.assertRaises(KeyboardInterrupt):
                self.run_builder(w, interrupted)
            self.assertEqual(w.status()["state"], "failed")
            self.assertIn("interrupted", w.status()["error"])

    def test_docker_stop_is_recorded(self):
        # docker stop sends SIGTERM, which Python as a container's first process would ignore.
        def stopped(argv):
            handler = signal.getsignal(signal.SIGTERM)
            self.assertTrue(callable(handler), "no SIGTERM handler while building")
            handler(signal.SIGTERM, None)
        with Workshop() as w:
            with self.assertRaises(SystemExit):
                self.run_builder(w, stopped)
            self.assertEqual(w.status()["state"], "failed")
            self.assertIn("stopped", w.status()["error"])

    def test_a_failed_program_is_recorded_without_its_command_line(self):
        # keytool's command line carried the signing key's password; build.json is readable by every
        # user on the server PC and its error is shown on the admin pages.
        def keytool_failed(argv):
            raise subprocess.CalledProcessError(1, ["keytool", "-genkeypair", "-storepass", "S3cret", "-keypass", "S3cret"])
        with Workshop() as w:
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_builder(w, keytool_failed)
            self.assertEqual(w.status()["state"], "failed")
            self.assertNotIn("S3cret", json.dumps(w.status()))
            self.assertIn("keytool", w.status()["error"])

    def test_a_jar_is_named_by_its_file(self):
        err = subprocess.CalledProcessError(1, ["java", "-jar", "/opt/apktool.jar", "b", "-o", "x.apk"])
        self.assertEqual(builder.short_reason(err), "apktool.jar failed (exit status 1)")


class SmaliTest(unittest.TestCase):
    """The SDK edits on a made-up tree where each original text appears as often as expected: every
    test above replaces patch_smali, so this is where its counting and the table are exercised."""

    def tree(self, d):
        files = {}
        for rel, old, _new, expected in patch_apk.smali_edits(HOST):
            files.setdefault(rel, []).append(old * expected)
        for rel, parts in files.items():
            path = os.path.join(d, "smali", rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n# --\n".join(parts))

    def test_every_edit_applies(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(patch_apk, "log"):
            self.tree(d)
            patch_apk.patch_smali(d, HOST)
            for rel, old, new, expected in patch_apk.smali_edits(HOST):
                with open(os.path.join(d, "smali", rel), encoding="utf-8") as f:
                    text = f.read()
                if new:
                    self.assertIn(new, text, rel)

    def test_a_different_client_is_refused_with_the_file(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(patch_apk, "log"):
            self.tree(d)
            rel = "com/neowiz/externalsdkgbl/ExternalSDK.smali"
            with open(os.path.join(d, "smali", rel), "w", encoding="utf-8") as f:
                f.write("a client without the clipboard methods\n")
            with self.assertRaises(SystemExit) as e:
                patch_apk.patch_smali(d, HOST)
            self.assertIn("ExternalSDK.smali", str(e.exception))



class PackageTest(unittest.TestCase):
    """Each server's app has a package of its own, fixed by its signing key."""

    def test_follows_the_key(self):
        self.assertEqual(patch_apk.package_id("abcdef0123456789"), patch_apk.BASE_PACKAGE + ".sabcdef0123")
        self.assertNotEqual(patch_apk.package_id("aa" * 16), patch_apk.package_id("bb" * 16))


class LabelTest(unittest.TestCase):
    """The name in the app's title."""

    def label(self, host, name=""):
        with mock.patch.dict(os.environ, {"SERVER_NAME": name}):
            return patch_apk.app_label(host)

    def test_from_the_address(self):
        self.assertEqual(self.label("jg.example.com:8790"), "TECHNIKA Q (jg.example.com:8790)")
        self.assertEqual(self.label("192.168.0.10"), "TECHNIKA Q (192.168.0.10)")
        self.assertEqual(self.label("192.168.0.10:8000"), "TECHNIKA Q (192.168.0.10:8000)")

    def test_a_set_name_wins(self):
        self.assertEqual(self.label("jg.example.com", "우리 서버"), "TECHNIKA Q (우리 서버)")

    def test_a_bad_name_stops_the_build(self):
        with self.assertRaises(SystemExit):
            self.label("a.b", "x" * 81)
        with self.assertRaises(SystemExit):
            self.label("a.b", "a\nb")


class CodeEditTest(unittest.TestCase):
    """The game code's edits: what they write, and that a client with other bytes keeps its code."""

    def test_branches_are_encoded_as_the_processor_reads_them(self):
        # The one the first version of this edit wrote by hand: b 0xEF42D0 from 0xEF40F0.
        self.assertEqual(patch_apk.arm_branch(0xEF40F0, 0xEF42D0).hex(), "760000ea")
        # Backwards, and with link.
        self.assertEqual(patch_apk.arm_branch(0xD2F4B4, 0x9D735C).hex(), "a89ff2ea")
        self.assertEqual(patch_apk.arm_branch(0xCF9254, 0xCFD45C, link=True).hex(), "801000eb")

    def test_an_edit_writes_as_many_bytes_as_it_checks(self):
        for what, versions in patch_apk.IL2CPP_EDITS:
            for version, parts in versions.items():
                for _, old, new in parts:
                    self.assertEqual(len(old), len(new), f"{what} ({version})")

    def test_every_edit_is_made_for_both_versions(self):
        for what, versions in patch_apk.IL2CPP_EDITS:
            self.assertEqual(sorted(versions), ["1.3.4", "1.3.5"], what)

    def test_the_menu_rate_code_is_the_one_written_by_hand_for_1_3_4(self):
        # Its branch back and its literal (the distance to the class's slot in the GOT), as the first version had them.
        code = patch_apk._menu_rate(0x9D736C, 0x9AFE64, 0x1452058)
        self.assertEqual(code[-8:].hex(), "af62ffeadcaca700")
        self.assertEqual(len(code), 60)

    def test_a_client_with_other_bytes_keeps_that_edit_whole(self):
        edits = [("both parts", {"1": [(0, b"AAAA", b"BBBB"), (8, b"CCCC", b"DDDD")]}), ("one part", {"1": [(12, b"EEEE", b"FFFF")]})]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(patch_apk, "IL2CPP_EDITS", edits), mock.patch.object(patch_apk, "log"):
            path = os.path.join(d, "lib.so")
            # The first edit's second part does not match: neither part is written.
            with open(path, "wb") as f:
                f.write(b"AAAAxxxxZZZZEEEE")
            self.assertEqual(patch_apk.patch_il2cpp(path), {"one part"})
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"AAAAxxxxZZZZFFFF")

    def test_each_client_takes_the_version_whose_bytes_it_has(self):
        # The same edit at another place in each version; a client has the bytes of one of them.
        edits = [("the edit", {"old": [(0, b"AAAA", b"BBBB")], "new": [(8, b"CCCC", b"DDDD")]})]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(patch_apk, "IL2CPP_EDITS", edits), \
                mock.patch.object(patch_apk, "log") as log:
            for code, after, version in ((b"AAAAxxxxCCCC", b"BBBBxxxxCCCC", "old"), (b"xxxxyyyyCCCC", b"xxxxyyyyDDDD", "new")):
                path = os.path.join(d, "lib.so")
                with open(path, "wb") as f:
                    f.write(code)
                self.assertEqual(patch_apk.code_versions(code), {"the edit": version})
                patch_apk.patch_il2cpp(path)
                with open(path, "rb") as f:
                    self.assertEqual(f.read(), after, version)
                self.assertIn(f"the edit ({version})", log.call_args_list[-1].args[0])


def settings_file(objects):
    """A Unity 5.6 asset file holding objects of other kinds than screens: [(Unity class number, its bytes)]."""
    meta = b"5.6.5f1\0" + struct.pack("<i", 13) + b"\0"
    kinds = sorted({kind for kind, _ in objects})
    meta += struct.pack("<i", len(kinds))
    for kind in kinds:
        meta += struct.pack("<i", kind) + b"\0" + struct.pack("<h", -1) + b"\0" * 16
    meta += struct.pack("<i", len(objects))
    body = b""
    for n, (kind, blob) in enumerate(objects):
        meta += b"\0" * (-(20 + len(meta)) % 4)
        meta += struct.pack("<qIIi", n + 1, len(body), len(blob), kinds.index(kind))
        body += blob + b"\0" * (-len(blob) % 8)
    data_offset = 20 + len(meta)
    data_offset += -data_offset % 16
    header = struct.pack(">IIII", len(meta), data_offset + len(body), unity_assets.FORMAT, data_offset) + b"\0" * 4
    return header + meta + b"\0" * (data_offset - 20 - len(meta)) + body


class SettingEditTest(unittest.TestCase):
    """The game's project settings: found by their object, wherever the file has it, and left alone when it differs."""

    def setUp(self):
        self.edits = {"Player.flag": (129, 16, 5, 0, 1), "Quality.level": (47, 8, 2, 1, 0)}
        patcher = mock.patch.object(patch_apk, "SETTING_EDITS", self.edits)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_each_setting_is_found_in_its_object_wherever_that_is(self):
        player, quality = bytes(16), b"\0\0\1" + bytes(5)
        seen = set()
        for objects in ([(129, player), (47, quality)], [(47, quality), (30, bytes(40)), (129, player)]):
            data = settings_file(objects)
            places = patch_apk.setting_places(data)
            self.assertEqual(sorted(places), ["Player.flag", "Quality.level"])
            # In the objects' bytes, after the file's header and tables, at the place in the object.
            body = struct.unpack_from(">I", data, 12)[0]
            place = places["Quality.level"][0]
            self.assertGreaterEqual(place, body)
            self.assertEqual(data[place - 2:place + 6], quality)
            seen.add(place)
        # The two files have it at two places.
        self.assertEqual(len(seen), 2)

    def test_an_object_of_another_size_or_byte_keeps_its_setting(self):
        data = settings_file([(129, bytes(17)), (47, b"\0\0\7" + bytes(5))])
        self.assertEqual(patch_apk.setting_places(data), {})
        self.assertEqual(patch_apk.setting_places(b"not an asset file"), {})

    def test_the_settings_land_and_the_rest_of_the_file_stays(self):
        data = settings_file([(129, bytes(16)), (47, b"\0\0\1" + bytes(5))])
        with tempfile.TemporaryDirectory() as d, mock.patch.object(patch_apk, "log"):
            folder = os.path.join(d, patch_apk.ASSET_DIR)
            os.makedirs(folder)
            path = os.path.join(folder, patch_apk.SETTINGS_FILE)
            with open(path, "wb") as f:
                f.write(data)
            patch_apk.patch_settings(d)
            with open(path, "rb") as f:
                after = f.read()
        changed = [i for i in range(len(data)) if data[i] != after[i]]
        self.assertEqual(len(after), len(data))
        self.assertEqual([(after[i], data[i]) for i in changed], [(1, 0), (0, 1)])


class ScreenEditTest(unittest.TestCase):
    """The game's screens: the edits land in the file, and a client without that screen keeps going."""

    def test_edits_land_and_a_missing_file_is_only_reported(self):
        data = unity_assets.build([(1, "Root", 0, True, (0, 0)), (2, "Button", 1, True, (5, 5))])
        edits = {"screen": [("hide", "Root/Button")], "not-there": [("hide", "Root/Button")], "other": [("hide", "Root/Nothing")]}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(patch_apk, "ASSET_EDITS", edits), mock.patch.object(patch_apk, "log") as log:
            folder = os.path.join(d, patch_apk.ASSET_DIR)
            os.makedirs(folder)
            for name in ("screen", "other"):
                with open(os.path.join(folder, name), "wb") as f:
                    f.write(data)
            patch_apk.patch_assets(d)
            with open(os.path.join(folder, "screen"), "rb") as f:
                self.assertFalse(unity_assets.SerializedFile(f.read()).is_active("Root/Button"))
            # The file whose object is missing stays as it was.
            with open(os.path.join(folder, "other"), "rb") as f:
                self.assertEqual(f.read(), data)
            said = " ".join(str(c) for c in log.call_args_list)
            self.assertIn("skipped not-there", said)
            self.assertIn("skipped other", said)
            # One edit is said as one.
            self.assertIn("screen: 1 edit'", said)

    def test_every_screen_edit_is_written_correctly(self):
        for name, edits in patch_apk.ASSET_EDITS.items():
            self.assertRegex(name, r"^[0-9a-f]{32}$")
            for edit in edits:
                self.assertIn(edit[0], ("hide", "hide if there", "move", "move if there"))
                self.assertTrue(edit[1].count("/") >= 1, edit)


if __name__ == "__main__":
    unittest.main()


class AppIconTest(unittest.TestCase):
    """The app's launcher icon beside it, for the download page: the largest one the app has."""

    def test_the_largest_icon_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            apk = os.path.join(d, "app.apk")
            with zipfile.ZipFile(apk, "w") as z:
                z.writestr("res/drawable-mdpi-v4/app_icon.png", b"small")
                z.writestr("res/drawable-xxxhdpi-v4/app_icon.png", b"the largest one")
                z.writestr("res/drawable-xxxhdpi-v4/other.png", b"something else that is even larger than the icon")
            self.assertTrue(patch_apk.write_icon(apk, os.path.join(d, "app-icon.png")))
            with open(os.path.join(d, "app-icon.png"), "rb") as f:
                self.assertEqual(f.read(), b"the largest one")

    def test_an_app_without_one_or_a_broken_file_leaves_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            apk = os.path.join(d, "app.apk")
            with zipfile.ZipFile(apk, "w") as z:
                z.writestr("res/drawable-mdpi-v4/launcher.png", b"x")
            self.assertFalse(patch_apk.write_icon(apk, os.path.join(d, "app-icon.png")))
            with open(apk, "wb") as f:
                f.write(b"not a zip")
            self.assertFalse(patch_apk.write_icon(apk, os.path.join(d, "app-icon.png")))
            self.assertFalse(os.path.exists(os.path.join(d, "app-icon.png")))

