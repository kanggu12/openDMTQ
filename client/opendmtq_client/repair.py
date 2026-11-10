"""Repair of the installed program, from the package Velopack keeps beside it.

Velopack leaves the package it installed in packages\\ of the install folder (OpenDMTQ.Client-<version>-full.nupkg, a
zip), and current\\ holds exactly the files under the package's lib/app/. So a file of the program that went missing or
changed (a cleaner, an antivirus, a disk fault) is found by comparing sizes and CRC-32s, and comes back from the
package: no download and no installer. The launcher's settings, the servers' apps and the game's data are no part of
the program and are never touched here.

Windows does not let a file of a running program be written over, but lets it be renamed: such a file is moved aside
first and the aside copy goes at the next repair. What still cannot be put back is counted, and the installer's own
Repair (OpenDMTQ-Setup.exe run again) takes over from there.
"""

import logging
import os
import zipfile
import zlib

from opendmtq_client import errors, installed, installer

log = logging.getLogger("opendmtq_client")

# Where a package keeps the program's files.
APP_PREFIX = "lib/app/"
# The package's copy of Update.exe, and the ending of its copy of the stub that starts the current version: both live
# in the install folder itself, above current\.
UPDATER_ENTRY, STUB_ENDING = "Squirrel.exe", "_ExecutionStub.exe"
# A file moved aside because it was in use, and one still being written.
ASIDE, PART = ".odq-old", ".odq-new"
# Read and written a megabyte at a time.
CHUNK = 1 << 20


class RepairError(errors.Worded):
    """The repair cannot be made here; its words say why and what to do instead."""


class Result:
    """What a repair found and did: how many files it compared, which were missing or changed, and which of those it
    could not put back."""

    def __init__(self, checked, missing, changed, failed):
        self.checked, self.missing, self.changed, self.failed = checked, missing, changed, failed

    @property
    def restored(self):
        """How many files came back."""
        return len(self.missing) + len(self.changed) - len(self.failed)

    @property
    def needs_restart(self):
        """Whether a file of the launcher itself came back: the running one goes on with what it loaded at its start."""
        back = [n for n in self.missing + self.changed if n not in self.failed]
        # The launcher is everything in current\ but the player, the licences and the version file.
        others = ("player" + os.sep, "licenses" + os.sep, "sq.version")
        return any(n.startswith("current" + os.sep) and not n[len("current" + os.sep):].startswith(others)
                   for n in back)


def package_path(root):
    """The package of the installed version in the install folder; RepairError when it is not there."""
    version = installer.installed_version(root)
    path = os.path.join(root, "packages", "%s-%s-full.nupkg" % (installed.PACKAGE_ID, version)) if version else None
    if not path or not os.path.isfile(path):
        raise RepairError("the installed package is not on this PC (run OpenDMTQ-Setup.exe again)",
                          "error.repair.no_package")
    return path


def _target(root, entry):
    """Where a package's entry belongs on the disk, or None for an entry that is no file of the program."""
    if not entry.startswith(APP_PREFIX) or entry.endswith("/"):
        return None
    name = entry[len(APP_PREFIX):]
    parts = name.split("/")
    # Names that would leave the install folder are no part of a package Velopack made.
    if not name or any(p in ("", ".", "..") or ":" in p or "\\" in p for p in parts):
        return None
    if len(parts) == 1 and name == UPDATER_ENTRY:
        return os.path.join(root, installed.UPDATER)
    if len(parts) == 1 and name.endswith(STUB_ENDING):
        return os.path.join(root, name[:-len(STUB_ENDING)] + ".exe")
    return os.path.join(root, "current", *parts)


def _crc(path):
    """The CRC-32 of a file, as a zip keeps it."""
    value = 0
    with open(path, "rb") as f:
        while True:
            piece = f.read(CHUNK)
            if not piece:
                return value & 0xFFFFFFFF
            value = zlib.crc32(piece, value)


def _sweep(root):
    """Remove what earlier repairs moved aside or left half written; a file still in use stays for the next one."""
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith((ASIDE, PART)):
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    pass


def _put_back(package, info, target):
    """One file out of the package into its place; False when Windows does not let it be replaced."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    part = target + PART
    try:
        # Written beside its place first: a repair that stops half way leaves the file there as it was.
        with package.open(info) as source, open(part, "wb") as out:
            while True:
                piece = source.read(CHUNK)
                if not piece:
                    break
                out.write(piece)
        try:
            os.replace(part, target)
        except OSError:
            # In use by a running program (this one, most likely): renamed aside, which Windows allows.
            os.replace(target, target + ASIDE)
            os.replace(part, target)
        return True
    except OSError as e:
        log.warning("could not put %s back: %s", target, e)
        try:
            os.remove(part)
        except OSError:
            pass
        return False


def run(root=None, progress=None):
    """Compare the installed program with its package and put back what is missing or changed; returns the Result.

    progress(done, total) is told as the files are compared. RepairError when the program was not installed by
    OpenDMTQ-Setup.exe, or its package is gone or cannot be read.
    """
    root = root or installed.root()
    if not root:
        raise RepairError("repair works in the launcher installed by OpenDMTQ-Setup.exe", "error.repair.not_installed")
    path = package_path(root)
    _sweep(root)
    missing, changed, failed, checked = [], [], [], 0
    try:
        with zipfile.ZipFile(path) as package:
            entries = [(info, _target(root, info.filename)) for info in package.infolist()]
            entries = [(info, target) for info, target in entries if target]
            for done, (info, target) in enumerate(entries, 1):
                name = os.path.relpath(target, root)
                if not os.path.isfile(target):
                    kind = missing
                elif os.path.getsize(target) != info.file_size or _crc(target) != info.CRC:
                    kind = changed
                else:
                    kind = None
                if kind is not None:
                    kind.append(name)
                    if not _put_back(package, info, target):
                        failed.append(name)
                checked += 1
                if progress:
                    progress(done, len(entries))
    except (zipfile.BadZipFile, zlib.error, EOFError) as e:
        # The package itself is damaged: only the installer has another copy.
        log.warning("the installed package cannot be read: %s", e)
        raise RepairError("the installed package cannot be read (run OpenDMTQ-Setup.exe again)",
                          "error.repair.package") from e
    log.info("repair: %d files compared, %d missing, %d changed, %d not put back", checked, len(missing),
             len(changed), len(failed))
    for name in missing + changed:
        log.info("repair: %s%s", name, " (not put back)" if name in failed else "")
    return Result(checked, missing, changed, failed)
