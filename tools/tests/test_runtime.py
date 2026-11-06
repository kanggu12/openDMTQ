"""The arm32 runtime, ready-made: one zip with everything in it, from a copy at hand or the latest release, swapped in whole."""

import io
import json
import os
import shutil
import stat
import tempfile
import threading
import unittest
import urllib.error
import zipfile
from unittest import mock

from opendmtq_tools import runtime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")


def bundle(folder, version="v1", leave_out=()):
    """A runtime bundle as arm32/bundle.sh makes it, small."""
    for rel in runtime.HANDED_OUT + ("sysroot/lib/libEGL.so", "sysroot/lib/libm.so"):
        if rel in leave_out:
            continue
        path = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"version": version}) if rel == "bundle.json" else "---- libc++" if rel.endswith("NOTICES.txt") else rel)


class PackTest(unittest.TestCase):
    def test_a_release_hands_out_all_of_it(self):
        with tempfile.TemporaryDirectory() as d:
            bundle(os.path.join(d, "b"))
            out = os.path.join(d, "runtime.zip")
            with mock.patch.object(runtime, "log"):
                runtime.pack(os.path.join(d, "b"), out)
            with zipfile.ZipFile(out) as z:
                names = set(z.namelist())
            # Android's libraries, and what lets them be handed out.
            for rel in ("sysroot/lib/libc.so", "sysroot/bin/linker", "notices/NOTICES.txt", "notices/android-NOTICE.html.gz",
                        "arm64-v8a/libarm32.so", "armeabi-v7a/libopendmtq.so", "sysroot/lib/libEGL.so"):
                self.assertIn(rel, names)

    def test_a_half_bundle_stops_a_release(self):
        # Above all one without its licenses: they are what allows handing the rest out.
        with tempfile.TemporaryDirectory() as d:
            bundle(os.path.join(d, "b"), leave_out=("notices/android-NOTICE.html.gz",))
            with self.assertRaises(SystemExit) as e:
                runtime.pack(os.path.join(d, "b"), os.path.join(d, "runtime.zip"))
            self.assertIn("android-NOTICE", str(e.exception))
            self.assertFalse(os.path.exists(os.path.join(d, "runtime.zip")))

    def test_a_bundle_made_before_libcxxs_license_stops_a_release_too(self):
        with tempfile.TemporaryDirectory() as d:
            bundle(os.path.join(d, "b"))
            with open(os.path.join(d, "b", "notices", "NOTICES.txt"), "w", encoding="utf-8") as f:
                f.write("---- OpenDMTQ\n---- dynarmic\n")
            with self.assertRaises(SystemExit) as e:
                runtime.pack(os.path.join(d, "b"), os.path.join(d, "runtime.zip"))
            self.assertIn("libc++", str(e.exception))


class AddTest(unittest.TestCase):
    """The whole way, with the release's server stood in for."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.apk = os.path.join(self.root, "apk")
        # The folder beside the program, empty: nothing is at hand unless a test puts it there.
        self.here = os.path.join(self.root, "program")
        os.makedirs(self.here)
        self.fetched = []
        self.release = None
        for patch in (mock.patch.object(runtime, "HERE", self.here), mock.patch.object(runtime, "log"),
                      mock.patch.object(runtime.urllib.request, "urlopen", self.urlopen)):
            patch.start()
            self.addCleanup(patch.stop)

    def urlopen(self, url, timeout=None):
        """The release's server: its zip, or no answer when there is none."""
        self.fetched.append(url)
        if self.release is None:
            raise urllib.error.URLError("no way out")
        with open(self.release, "rb") as f:
            return io.BytesIO(f.read())

    def made_zip(self, version="v1", leave_out=()):
        """A runtime zip in a folder of its own, as a release's job makes it."""
        folder = tempfile.mkdtemp(dir=self.root)
        bundle(os.path.join(folder, "b"), version, leave_out)
        path = os.path.join(folder, runtime.ZIP_NAME)
        # Compressed, as a release's is: a damaged one fails in the decompressor, not only in the zip's own records.
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for rel in runtime.HANDED_OUT:
                if rel not in leave_out:
                    z.write(os.path.join(folder, "b", rel), rel)
        return path

    def in_place(self):
        return runtime.version_in_place(os.path.join(self.apk, "arm32"))

    def test_first_time_it_comes_from_the_latest_release_and_leaves_nothing_on_the_way(self):
        self.release = self.made_zip()
        runtime.add_runtime(self.apk)
        self.assertEqual(self.fetched, [runtime.RELEASE_URL])
        self.assertEqual(self.in_place(), "v1")
        self.assertEqual(os.listdir(self.apk), ["arm32"])
        with open(os.path.join(self.apk, "arm32", "sysroot/lib/libc.so"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "sysroot/lib/libc.so")

    def test_what_runs_on_the_phone_stays_executable(self):
        # The packer reads the modes where a host has them, and a zip does not bring them back.
        self.release = self.made_zip()
        runtime.add_runtime(self.apk)
        for rel in ("sysroot/lib/libc.so", "sysroot/bin/linker", "arm32-agent"):
            self.assertTrue(os.stat(os.path.join(self.apk, "arm32", rel)).st_mode & stat.S_IXUSR, rel)

    def test_the_copy_that_came_with_the_program_needs_no_network(self):
        shutil.copy(self.made_zip(), self.here)
        runtime.add_runtime(self.apk)
        self.assertEqual(self.fetched, [])
        self.assertEqual(self.in_place(), "v1")

    def test_a_copy_put_there_by_hand_needs_no_network_and_is_taken(self):
        os.makedirs(self.apk)
        shutil.copy(self.made_zip("by hand"), self.apk)
        runtime.add_runtime(self.apk)
        self.assertEqual(self.fetched, [])
        self.assertEqual(self.in_place(), "by hand")
        # Gone once it is in: left there it would hold back every later runtime, without a word.
        self.assertEqual(os.listdir(self.apk), ["arm32"])
        self.release = self.made_zip("newer")
        runtime.add_runtime(self.apk, refresh=True)
        self.assertEqual(self.in_place(), "newer")

    def test_a_damaged_copy_put_there_by_hand_stays_to_be_replaced_and_changes_nothing(self):
        bundle(os.path.join(self.apk, "arm32"), "v1")
        with open(os.path.join(self.apk, runtime.ZIP_NAME), "w", encoding="utf-8") as f:
            f.write("not a zip")
        self.assertFalse(runtime.add_or_note(self.apk))
        self.assertEqual(self.in_place(), "v1")
        with open(os.path.join(self.apk, runtime.NOTE), encoding="utf-8") as f:
            self.assertIn("damaged", f.read())

    def test_the_copy_that_came_with_the_program_comes_before_one_by_hand(self):
        # The one tested with this program. Taking turns would change the app at every start.
        shutil.copy(self.made_zip("from the program"), self.here)
        os.makedirs(self.apk)
        shutil.copy(self.made_zip("by hand"), self.apk)
        runtime.add_runtime(self.apk)
        runtime.add_runtime(self.apk)
        self.assertEqual(self.in_place(), "from the program")

    def test_a_new_program_brings_its_runtime_along_whole(self):
        shutil.copy(self.made_zip("v1"), self.here)
        runtime.add_runtime(self.apk)
        leftover = os.path.join(self.apk, "arm32", "old-file")
        with open(leftover, "w", encoding="utf-8") as f:
            f.write("x")
        shutil.copy(self.made_zip("v2"), self.here)
        runtime.add_runtime(self.apk)
        self.assertEqual(self.in_place(), "v2")
        self.assertFalse(os.path.exists(leftover))

    def test_the_same_version_is_not_unpacked_again(self):
        shutil.copy(self.made_zip(), self.here)
        runtime.add_runtime(self.apk)
        with mock.patch.object(runtime, "install") as install:
            runtime.add_runtime(self.apk)
        install.assert_not_called()

    def test_a_release_that_did_not_touch_the_runtime_changes_nothing(self):
        # The hash at the end of a version is that of its files. A new commit with the same files stays out, or the app would be
        # built again, and every phone asked to install it, for nothing.
        shutil.copy(self.made_zip("aaaa111-1f7557a4"), self.here)
        runtime.add_runtime(self.apk)
        shutil.copy(self.made_zip("bbbb222-1f7557a4"), self.here)
        runtime.add_runtime(self.apk)
        self.assertEqual(self.in_place(), "aaaa111-1f7557a4")
        shutil.copy(self.made_zip("cccc333-99999999"), self.here)
        runtime.add_runtime(self.apk)
        self.assertEqual(self.in_place(), "cccc333-99999999")

    def test_a_runtime_built_here_stays_and_no_network_is_asked(self):
        # arm32/bundle.sh on this machine: replacing it behind its builder's back would throw their work away.
        bundle(os.path.join(self.apk, "arm32"), "built here")
        self.release = self.made_zip("v9")
        runtime.add_runtime(self.apk)
        self.assertEqual(self.fetched, [])
        self.assertEqual(self.in_place(), "built here")

    def test_asked_to_look_it_takes_the_latest_release(self):
        bundle(os.path.join(self.apk, "arm32"), "v1")
        self.release = self.made_zip("v2")
        runtime.add_runtime(self.apk, refresh=True)
        self.assertEqual(self.in_place(), "v2")

    def test_half_a_bundle_in_place_is_none(self):
        bundle(os.path.join(self.apk, "arm32"), "v1", leave_out=("sysroot/lib/libc.so",))
        self.release = self.made_zip("v2")
        runtime.add_runtime(self.apk)
        self.assertEqual(self.in_place(), "v2")

    def test_a_zip_without_the_licenses_or_the_libraries_replaces_nothing(self):
        bundle(os.path.join(self.apk, "arm32"), "v1")
        for missing in ("notices/android-NOTICE.html.gz", "sysroot/lib/libc.so", "arm64-v8a/libarm32.so"):
            self.release = self.made_zip("v2", leave_out=(missing,))
            with self.assertRaises(runtime.RuntimeError_) as e:
                runtime.add_runtime(self.apk, refresh=True)
            self.assertIn(missing, str(e.exception))
            self.assertEqual(self.in_place(), "v1")

    def test_a_damaged_download_replaces_nothing_and_leaves_nothing(self):
        bundle(os.path.join(self.apk, "arm32"), "v1")
        self.release = self.made_zip("v2")
        with open(self.release, "rb") as f:
            whole = f.read()
        # Cut short, as a connection that dropped leaves it; then with a byte changed inside.
        with open(self.release, "wb") as f:
            f.write(whole[:len(whole) // 2])
        with self.assertRaises(runtime.RuntimeError_):
            runtime.add_runtime(self.apk, refresh=True)
        changed = bytearray(whole)
        changed[len(whole) // 4] ^= 0xFF
        with open(self.release, "wb") as f:
            f.write(changed)
        with self.assertRaises(runtime.RuntimeError_):
            runtime.add_runtime(self.apk, refresh=True)
        self.assertEqual(self.in_place(), "v1")
        self.assertEqual(os.listdir(self.apk), ["arm32"])

    def test_damage_the_decompressor_finds_is_noted_like_any_other(self):
        # Zeros over the compressed bytes: it used to escape as zlib's own error and stop every start of the server.
        self.release = self.made_zip()
        with open(self.release, "rb") as f:
            whole = bytearray(f.read())
        names = zipfile.ZipFile(self.release).infolist()
        for info in names:
            at = info.header_offset + 30 + len(info.filename)
            whole[at:at + 8] = bytes(8)
        with open(self.release, "wb") as f:
            f.write(whole)
        self.assertFalse(runtime.add_or_note(self.apk))
        with open(os.path.join(self.apk, runtime.NOTE), encoding="utf-8") as f:
            self.assertIn("damaged", f.read())

    def test_what_goes_wrong_at_the_swap_leaves_the_old_one(self):
        dest = os.path.join(self.apk, "arm32")
        bundle(dest, "v1")
        self.release = self.made_zip("v2")
        real = os.rename

        def rename(src, dst):
            # The new one will not move in, as when a scanner holds a file on Windows.
            if dst == dest and ".runtime-new-" in src:
                raise OSError("a program holds a file")
            real(src, dst)

        with mock.patch.object(runtime.os, "rename", rename):
            self.assertFalse(runtime.add_or_note(self.apk, refresh=True))
        self.assertEqual(self.in_place(), "v1")
        self.assertEqual(sorted(os.listdir(self.apk)), ["arm32", runtime.NOTE])

    def test_two_runs_at_once_leave_a_whole_bundle(self):
        # The setup's button just as the server's own builder starts. With one shared folder they left half of one, which then
        # looked whole enough to stay.
        for version in ("a", "b"):
            shutil.copy(self.made_zip(version), os.path.join(self.root, version + ".zip"))
        dest = os.path.join(self.apk, "arm32")
        os.makedirs(self.apk)
        for _ in range(15):
            errors = []

            def one(version):
                try:
                    runtime.install(os.path.join(self.root, version + ".zip"), dest)
                except OSError as e:
                    errors.append(e)

            runs = [threading.Thread(target=one, args=(v,)) for v in ("a", "b")]
            for run in runs:
                run.start()
            for run in runs:
                run.join()
            self.assertEqual(errors, [])
            self.assertIn(self.in_place(), ("a", "b"))
            for rel in runtime.HANDED_OUT:
                self.assertTrue(os.path.isfile(os.path.join(dest, rel)), rel)
            self.assertEqual(os.listdir(self.apk), ["arm32"])

    def test_with_no_way_out_it_says_where_it_tried(self):
        with self.assertRaises(runtime.RuntimeError_) as e:
            runtime.add_runtime(self.apk)
        self.assertIn(runtime.RELEASE_URL, str(e.exception))
        self.assertIn("no way out", str(e.exception))
        self.assertEqual(os.listdir(self.apk), [])

    def test_a_failure_is_noted_for_the_owner_and_goes_with_the_next_try_that_works(self):
        self.assertFalse(runtime.add_or_note(self.apk))
        with open(os.path.join(self.apk, runtime.NOTE), encoding="utf-8") as f:
            self.assertIn("no way out", f.read())
        self.release = self.made_zip()
        self.assertTrue(runtime.add_or_note(self.apk))
        self.assertFalse(os.path.exists(os.path.join(self.apk, runtime.NOTE)))

    def test_a_disk_that_says_no_is_noted_too_and_stops_nothing(self):
        self.release = self.made_zip()
        with mock.patch.object(runtime, "install", side_effect=OSError("disk full")):
            self.assertFalse(runtime.add_or_note(self.apk))
        with open(os.path.join(self.apk, runtime.NOTE), encoding="utf-8") as f:
            self.assertIn("disk full", f.read())

    def test_the_command_line_says_how_it_went(self):
        with mock.patch.object(runtime, "APK_DIR", self.apk):
            self.assertEqual(runtime.main([]), 1)
            self.release = self.made_zip()
            self.assertEqual(runtime.main([]), 0)
            self.fetched.clear()
            # Asked to look, it does, and the same version changes nothing.
            with mock.patch.object(runtime, "install") as install:
                self.assertEqual(runtime.main(["--refresh"]), 0)
            self.assertEqual(self.fetched, [runtime.RELEASE_URL])
            install.assert_not_called()


@unittest.skipUnless(os.path.isfile(os.path.join(ROOT, "arm32", "build.sh")), "the runtime's sources are not at hand")
class WhatIsHandedOutTest(unittest.TestCase):
    def test_every_system_library_the_build_takes_has_its_license_with_the_bundle(self):
        # The image's own notices name all of them but libc++: its text has to travel with the bundle, by name.
        with open(os.path.join(ROOT, "arm32", "bundle.sh"), encoding="utf-8") as f:
            script = f.read()
        self.assertIn("libc++-LICENSE.txt", script)
        self.assertIn("android-NOTICE.html.gz", script)
        with open(os.path.join(ROOT, "arm32", "libc++-LICENSE.txt"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("University of Illinois", text)
        self.assertIn("Permission is hereby granted", text)
        with open(os.path.join(ROOT, "arm32", "NOTICES.txt"), encoding="utf-8") as f:
            notices = f.read()
        with open(os.path.join(ROOT, "arm32", "build.sh"), encoding="utf-8") as f:
            build = f.read()
        for name in ("libc", "libm", "libdl", "libstdc++", "libc++", "libz", "liblog"):
            self.assertIn(f"{name}.so", build)
            self.assertIn(name, notices)


if __name__ == "__main__":
    unittest.main()
