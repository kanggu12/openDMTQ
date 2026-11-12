"""The installed program, seen from the launcher that runs inside it.

Velopack's setup lays the program out like this, in %LOCALAPPDATA%\\OpenDMTQ.Client of the Windows user:

  OpenDMTQ.exe    the stub the shortcuts start: it runs the current version
  Update.exe      Velopack's updater and uninstaller
  current\\        the program: OpenDMTQ.exe, OpenDMTQ-cmd.exe, the player, and sq.version with the version it is
  packages\\       the package the installed version came from

A launcher run from a checkout or from a copied folder has none of this: root() answers None there, and repairing and
uninstalling say that they work in the installed launcher.
"""

import logging
import os
import sys

log = logging.getLogger("opendmtq_client")

# Velopack's package id: the install folder's name and the first part of its packages' names.
PACKAGE_ID = "OpenDMTQ.Client"
# Velopack's updater and uninstaller, in the install folder.
UPDATER = "Update.exe"
# Windows' entry for the program in Settings, Apps, under the current user's part of the registry: Velopack's setup
# writes it, and each update writes it again.
UNINSTALL_KEY = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + PACKAGE_ID


def root():
    """The folder this program is installed in (the one above current\\), or None when OpenDMTQ-Setup.exe did not
    install it. OPENDMTQ_INSTALL_ROOT names a folder laid out like one for the tests."""
    named = os.environ.get("OPENDMTQ_INSTALL_ROOT")
    if named:
        return named if os.path.isdir(named) else None
    if not getattr(sys, "frozen", False):
        # Run from a checkout: nothing was installed.
        return None
    here = os.path.dirname(os.path.abspath(sys.executable))
    # Velopack's layout: the program in current\, the version it is in the file beside it.
    if os.path.basename(here).lower() != "current" or not os.path.isfile(os.path.join(here, "sq.version")):
        return None
    return os.path.dirname(here)


def updater(folder):
    """Velopack's Update.exe of an install folder, or None when it is not there."""
    path = os.path.join(folder, UPDATER)
    return path if os.path.isfile(path) else None


def quiet_uninstall(folder=None):
    """Windows' Settings, Apps uninstalls with Velopack's uninstaller as the launcher runs it, silent: none of Velopack's
    plain system windows (its progress, its "Uninstall Complete"), and the launcher's own card after it, which says what
    went and what stayed (removal.card_after_uninstall). Velopack writes the entry's UninstallString without --silent,
    at the install and again at each update (its QuietUninstallString has it): it is made the same as the quiet one
    here, by the installer once its setup is done, by the update's hook, and at each start of the launcher. `folder` is
    the install folder (this launcher's own when None). True when the entry was changed."""
    if sys.platform != "win32":
        # Windows' registry only.
        return False
    folder = folder or root()
    if not folder or not updater(folder):
        # Not installed by OpenDMTQ-Setup.exe: there is no entry of Velopack's to make quiet.
        return False
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE)
    except OSError:
        # No entry (an install in a folder of its own, or one being removed): nothing to change.
        return False
    with key:
        try:
            now = str(winreg.QueryValueEx(key, "UninstallString")[0])
        except OSError:
            now = ""
        if "--silent" in now.split():
            # Quiet already: written by an earlier start, or by this launcher's update.
            return False
        # The same command as Velopack's own quiet one: its updater, quoted, with --uninstall --silent.
        quiet = '"%s" --uninstall --silent' % os.path.join(folder, UPDATER)
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, quiet)
    log.info("Windows' Apps uninstall OpenDMTQ silently now, the launcher's card after it: %s", quiet)
    return True
