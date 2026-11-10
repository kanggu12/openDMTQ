"""The installed program, seen from the launcher that runs inside it.

Velopack's setup lays the program out like this, in %LOCALAPPDATA%\\OpenDMTQ.Client of the Windows user:

  OpenDMTQ.exe    the stub the shortcuts start: it runs the current version
  Update.exe      Velopack's updater and uninstaller
  current\\        the program: OpenDMTQ.exe, OpenDMTQ-cmd.exe, the player, and sq.version with the version it is
  packages\\       the package the installed version came from

A launcher run from a checkout or from a copied folder has none of this: root() answers None there, and repairing and
uninstalling say that they work in the installed launcher.
"""

import os
import sys

# Velopack's package id: the install folder's name and the first part of its packages' names.
PACKAGE_ID = "OpenDMTQ.Client"
# Velopack's updater and uninstaller, in the install folder.
UPDATER = "Update.exe"


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
