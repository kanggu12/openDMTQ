"""A named mutex the launcher holds while a game it started is running.

The installer looks for it and waits then: Velopack's setup replaces the player's files, and a game playing from them
would lose them mid-song. The launcher's own update waits in the same moment for the same reason (maintenance.py).
"""

from opendmtq_client import mutex

# The mutex's handle while this process says a game is running.
_handle = None


def hold():
    """Say a game is running (until release(), or until this process ends)."""
    global _handle
    if not _handle:
        _handle, _existed = mutex.hold(mutex.PLAYING)


def release():
    global _handle
    mutex.release(_handle)
    _handle = None


def running():
    """True while some launcher says a game it started is running."""
    return mutex.exists(mutex.PLAYING)
