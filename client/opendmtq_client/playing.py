"""A named mutex the launcher holds while a game it started is running.

The installer looks for it and waits then: Velopack's setup replaces the player's files, and a game playing from them
would lose them mid-song. The launcher's own update waits in the same moment for the same reason (maintenance.py).
"""

import sys

NAME = "Local\\OpenDMTQ.playing"
_handle = None


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    k.OpenMutexW.restype = wintypes.HANDLE
    k.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k


def hold():
    """Say a game is running (until release(), or until this process ends)."""
    global _handle
    if sys.platform != "win32" or _handle:
        return
    _handle = _kernel32().CreateMutexW(None, False, NAME)


def release():
    global _handle
    if _handle:
        _kernel32().CloseHandle(_handle)
        _handle = None


def running():
    """True while some launcher says a game it started is running."""
    if sys.platform != "win32":
        return False
    k = _kernel32()
    synchronize = 0x00100000
    handle = k.OpenMutexW(synchronize, False, NAME)
    if handle:
        k.CloseHandle(handle)
        return True
    return False
