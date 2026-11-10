"""Windows' named mutexes, by which OpenDMTQ's programs see one another.

The launcher's window holds LAUNCHER while it is open (main.py): a second start brings that window forward instead, the
command line leaves alone what the window keeps, and the installer asks for it to be closed. The launcher holds PLAYING
while a game it started runs (playing.py): the installer, the update and the tools that delete wait for it. Off Windows
there are none: nothing is held and nothing is found.
"""

import sys

# The two names, in the user's own session ("Local\"): another Windows user's launcher is no concern of this one.
LAUNCHER = "Local\\OpenDMTQ.launcher"
PLAYING = "Local\\OpenDMTQ.playing"
# CreateMutexW's answer when the mutex was there already (another process holds it).
ALREADY_EXISTS = 183
# The right OpenMutexW asks for: the least there is, enough to know the mutex is there.
SYNCHRONIZE = 0x00100000

# kernel32 with the calls' types, made once (_kernel32).
_k32 = None


def _kernel32():
    """kernel32 with the types these calls take and give: a handle is a pointer, which ctypes' default int would cut
    on 64-bit Windows; its own copy of the last error, so no other call in between can change it."""
    global _k32
    if _k32 is None:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateMutexW.restype = wintypes.HANDLE
        k.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        k.OpenMutexW.restype = wintypes.HANDLE
        k.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        _k32 = k
    return _k32


def hold(name):
    """Hold a named mutex until release() or the end of this process: (its handle, whether another process held it
    already); (None, False) off Windows."""
    if sys.platform != "win32":
        return None, False
    import ctypes
    handle = _kernel32().CreateMutexW(None, False, name)
    # Read at once, from ctypes' own copy: the mutex was there before when Windows says it already exists.
    return handle, ctypes.get_last_error() == ALREADY_EXISTS


def release(handle):
    """Let go of a mutex hold() took: it is gone once no process holds it."""
    if handle:
        _kernel32().CloseHandle(handle)


def exists(name):
    """True while some process holds the named mutex; False off Windows."""
    if sys.platform != "win32":
        return False
    k = _kernel32()
    handle = k.OpenMutexW(SYNCHRONIZE, False, name)
    if handle:
        # Only looked at: the handle goes at once, so this look never keeps the mutex alive.
        k.CloseHandle(handle)
        return True
    return False
