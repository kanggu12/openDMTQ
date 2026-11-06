"""A lock on an open file that holds across processes and ends with the process that took it: flock on Linux and macOS,
a lock on the file's first byte on Windows, where there is no flock."""

import os
import time

if os.name == "nt":
    import msvcrt

    def lock(f, blocking=True):
        """Lock the open file f for this process. With blocking False, raise BlockingIOError when another process
        holds it."""
        # The lock covers the first byte, which stands for the whole file (the file needs no content for that).
        f.seek(0)
        while True:
            try:
                # Non-blocking: Windows' own blocking mode gives up after ten seconds.
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if not blocking:
                    raise BlockingIOError("the file is locked by another process") from None
                # Held by another process: ask again in a moment, for as long as it takes.
                time.sleep(0.5)

    def unlock(f):
        """Release the lock lock() took on f."""
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def lock(f, blocking=True):
        """Lock the open file f for this process. With blocking False, raise BlockingIOError when another process
        holds it."""
        fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))

    def unlock(f):
        """Release the lock lock() took on f."""
        fcntl.flock(f, fcntl.LOCK_UN)
