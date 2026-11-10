"""Repair: the installed program compared with its package, what is missing or changed put back (repair.py)."""

import os
import zipfile
from unittest import mock

from opendmtq_client import repair
from tests.base import Folder
from tests.test_removal import listing, write

# The program as a package holds it under lib/app/, with Velopack's own copies of Update.exe and of the stub.
PROGRAM = {
    "OpenDMTQ.exe": b"launcher",
    "OpenDMTQ-cmd.exe": b"console",
    "_internal/python312.dll": b"p" * 4000,
    "player/opendmtq-player.exe": b"player",
    "player/lib/x86/libc++.dll": b"c" * 2000,
    "licenses/LICENSE.txt": b"terms",
}
VELOPACK = {"Squirrel.exe": b"update", "OpenDMTQ_ExecutionStub.exe": b"stub"}
VERSION = b"<?xml version='1.0'?><package><metadata><version>0.8.0</version></metadata></package>"


class Repair(Folder):
    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.home, "OpenDMTQ.Client")
        os.makedirs(os.path.join(self.root, "packages"))
        self.package = os.path.join(self.root, "packages", "OpenDMTQ.Client-0.8.0-full.nupkg")
        with zipfile.ZipFile(self.package, "w", zipfile.ZIP_DEFLATED) as z:
            # What else a package holds, which is no file of the program.
            z.writestr("OpenDMTQ.Client.nuspec", VERSION)
            z.writestr("lib/app/", b"")
            for name, data in list(PROGRAM.items()) + list(VELOPACK.items()):
                z.writestr("lib/app/" + name, data)
        # The install as Velopack lays it out: the program in current\, Update.exe and the stub above it.
        write(os.path.join(self.root, "current"), PROGRAM)
        write(self.root, {"current/sq.version": VERSION, "Update.exe": VELOPACK["Squirrel.exe"],
                          "OpenDMTQ.exe": VELOPACK["OpenDMTQ_ExecutionStub.exe"]})
        os.environ["OPENDMTQ_INSTALL_ROOT"] = self.root

    def tearDown(self):
        os.environ.pop("OPENDMTQ_INSTALL_ROOT", None)
        super().tearDown()

    def path(self, name):
        return os.path.join(self.root, *name.split("/"))

    def read(self, name):
        with open(self.path(name), "rb") as f:
            return f.read()

    def test_an_intact_install_has_nothing_to_repair(self):
        before = listing(self.root)
        result = repair.run()
        self.assertEqual(result.checked, len(PROGRAM) + len(VELOPACK))
        self.assertEqual((result.missing, result.changed, result.failed, result.restored), ([], [], [], 0))
        self.assertEqual(listing(self.root), before)

    def test_missing_and_changed_files_come_back(self):
        os.remove(self.path("current/player/opendmtq-player.exe"))
        with open(self.path("current/_internal/python312.dll"), "wb") as f:
            f.write(b"p" * 3999 + b"x")
        os.remove(self.path("Update.exe"))
        os.remove(self.path("OpenDMTQ.exe"))
        result = repair.run()
        self.assertEqual(sorted(result.missing), sorted([os.path.join("current", "player", "opendmtq-player.exe"),
                                                         "Update.exe", "OpenDMTQ.exe"]))
        self.assertEqual(result.changed, [os.path.join("current", "_internal", "python312.dll")])
        self.assertEqual(result.restored, 4)
        for name, data in PROGRAM.items():
            self.assertEqual(self.read("current/" + name), data, name)
        self.assertEqual(self.read("Update.exe"), VELOPACK["Squirrel.exe"])
        self.assertEqual(self.read("OpenDMTQ.exe"), VELOPACK["OpenDMTQ_ExecutionStub.exe"])
        # Nothing half written stays, and a second repair finds nothing.
        self.assertFalse([n for n in listing(self.root) if n.endswith((repair.ASIDE, repair.PART))])
        self.assertEqual(repair.run().restored, 0)

    def test_a_file_in_use_is_moved_aside_and_swept_later(self):
        target = self.path("current/OpenDMTQ.exe")
        with open(target, "wb") as f:
            f.write(b"damaged")
        real = os.replace

        def replace(source, destination):
            # Windows refuses to write over a running program's file, and lets it be renamed.
            if source.endswith(repair.PART) and destination == target and not os.path.exists(target + repair.ASIDE):
                raise PermissionError(13, "in use", destination)
            real(source, destination)

        with mock.patch.object(os, "replace", replace):
            result = repair.run()
        self.assertEqual(result.restored, 1)
        self.assertEqual(self.read("current/OpenDMTQ.exe"), PROGRAM["OpenDMTQ.exe"])
        self.assertTrue(os.path.isfile(target + repair.ASIDE))
        # The launcher's own file: it is read at the next start.
        self.assertTrue(result.needs_restart)
        repair.run()
        self.assertFalse(os.path.exists(target + repair.ASIDE))

    def test_a_changed_file_never_becomes_a_missing_one(self):
        # The new copy cannot take the old one's place even after the old one moved aside (a scanner holding it):
        # the old one comes back, and the file is counted as not put back.
        target = self.path("current/OpenDMTQ.exe")
        with open(target, "wb") as f:
            f.write(b"damaged")
        real = os.replace

        def replace(source, destination):
            if source.endswith(repair.PART):
                raise PermissionError(32, "in use", source)
            real(source, destination)

        with mock.patch.object(os, "replace", replace), mock.patch.object(repair, "PAUSE", 0):
            result = repair.run()
        self.assertEqual(result.failed, [os.path.join("current", "OpenDMTQ.exe")])
        self.assertEqual(self.read("current/OpenDMTQ.exe"), b"damaged")
        self.assertFalse(os.path.exists(target + repair.ASIDE))

    def test_a_file_that_cannot_be_read_is_put_back_and_the_rest_compared(self):
        os.remove(self.path("current/player/opendmtq-player.exe"))
        real = repair._crc

        def crc(path):
            if path.endswith("python312.dll"):
                raise PermissionError(13, "denied", path)
            return real(path)

        with mock.patch.object(repair, "_crc", crc):
            result = repair.run()
        self.assertEqual(sorted(result.changed + result.missing),
                         sorted([os.path.join("current", "_internal", "python312.dll"),
                                 os.path.join("current", "player", "opendmtq-player.exe")]))
        self.assertEqual(result.failed, [])

    def test_a_package_that_cannot_be_opened(self):
        with mock.patch.object(repair.zipfile, "ZipFile", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(repair.RepairError) as caught:
                repair.run()
        self.assertEqual(caught.exception.key, "error.repair.package")

    def test_what_cannot_be_put_back_is_counted(self):
        os.remove(self.path("current/player/lib/x86/libc++.dll"))
        with mock.patch.object(repair, "_put_back", return_value=False):
            result = repair.run()
        self.assertEqual(result.failed, [os.path.join("current", "player", "lib", "x86", "libc++.dll")])
        self.assertEqual(result.restored, 0)

    def test_the_player_alone_needs_no_restart(self):
        os.remove(self.path("current/player/opendmtq-player.exe"))
        self.assertFalse(repair.run().needs_restart)

    def test_names_that_leave_the_install_folder_are_ignored(self):
        with zipfile.ZipFile(self.package, "a") as z:
            z.writestr("lib/app/../../outside.txt", b"no")
            z.writestr("lib/app/C:/outside.txt", b"no")
        result = repair.run()
        self.assertEqual(result.restored, 0)
        self.assertFalse(os.path.exists(os.path.join(self.home, "outside.txt")))

    def test_without_the_package(self):
        os.remove(self.package)
        with self.assertRaises(repair.RepairError) as caught:
            repair.run()
        self.assertEqual(caught.exception.key, "error.repair.no_package")

    def test_a_damaged_package(self):
        with open(self.package, "r+b") as f:
            f.write(b"not a zip at all")
            f.truncate(100)
        with self.assertRaises(repair.RepairError) as caught:
            repair.run()
        self.assertEqual(caught.exception.key, "error.repair.package")

    def test_a_copied_folder_has_nothing_to_repair_from(self):
        os.environ.pop("OPENDMTQ_INSTALL_ROOT")
        with self.assertRaises(repair.RepairError) as caught:
            repair.run()
        self.assertEqual(caught.exception.key, "error.repair.not_installed")
