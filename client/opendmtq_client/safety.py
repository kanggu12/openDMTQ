"""A guard for everything that would put a window on someone's screen.

Tests must never open a window on the developer's own desktop: under WSL a Tk window lands on the Windows desktop
through WSLg, and a Windows program started from WSL opens there too. So each function that opens a window (the
launcher's own, a dialog's, the game's player, Explorer) calls refuse_windows_in_tests() first.

A test run sets OPENDMTQ_TESTING=1 (client/tests/__init__.py). Inside the test containers, whose screen is a virtual X
server, OPENDMTQ_VIRTUAL_DISPLAY=1 lets the UI tests open windows on that screen and nowhere else.

The same goes for what deletes whole folders (removal.py): a test that forgot to point the launcher at folders of its
own would delete the developer's real settings and game data. So those functions call refuse_deleting_in_tests() with
each folder first, and a test run deletes only inside the system's folder for temporary files.
"""

import os
import tempfile


class WindowRefused(RuntimeError):
    """A test tried to open a window outside the virtual screen."""


class DeleteRefused(RuntimeError):
    """A test tried to delete a folder that is not a temporary one."""


def testing():
    """True while the test suite runs."""
    return os.environ.get("OPENDMTQ_TESTING") == "1"


def on_virtual_display():
    """True only inside a test container, whose X server has no real screen behind it."""
    return os.environ.get("OPENDMTQ_VIRTUAL_DISPLAY") == "1"


def refuse_windows_in_tests(what):
    """Stop a test from opening `what` unless the run is on the virtual screen."""
    if testing() and not on_virtual_display():
        raise WindowRefused("a test tried to open %s outside the virtual screen" % what)


def refuse_deleting_in_tests(folder):
    """Stop a test from deleting `folder` or anything in it unless it lies inside the folder for temporary files."""
    if not testing():
        return
    temp, real = os.path.realpath(tempfile.gettempdir()), os.path.realpath(folder)
    # The temporary folder itself is no test's own either.
    if not real.startswith(temp + os.sep):
        raise DeleteRefused("a test tried to delete %s, which is outside %s" % (folder, temp))
