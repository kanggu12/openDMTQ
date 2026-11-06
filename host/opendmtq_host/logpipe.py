"""Apache's piped logs on Windows: what Apache writes to this program goes into a file, in a circle of a few files of a
set size, as rotatelogs -n does (data/state/logs/<name>, then <name>.1, then <name>.2, then <name> again).

rotatelogs.exe is a console program: started by Apache's worker, which has no console, it gets a window of its own,
empty, beside the server's, one for each log. pythonw.exe has no console, so this one opens no window.

    pythonw.exe -I logpipe.py <file> <count> <bytes>
"""

import os
import sys


def names(path, count):
    """The files of the circle, in their order: <path>, <path>.1, ..."""
    return [path] + [f"{path}.{i}" for i in range(1, count)]


def newest(path, count):
    """Where to go on writing: the file of the circle written last, or the first when there is none yet."""
    there = [(os.path.getmtime(p), i) for i, p in enumerate(names(path, count)) if os.path.isfile(p)]
    return max(there)[1] if there else 0


def run(stream, path, count, limit):
    """Copy stream (bytes, line by line) into the circle of files until it ends."""
    files = names(path, count)
    at = newest(path, count)
    out = open(files[at], "ab")
    size = out.tell()
    try:
        for line in stream:
            # The next file of the circle, emptied, once this one is full (a line longer than the limit still fits).
            if size and size + len(line) > limit:
                out.close()
                at = (at + 1) % count
                out = open(files[at], "wb")
                size = 0
            out.write(line)
            # Each line at once: the admin pages read the newest requests as they come.
            out.flush()
            size += len(line)
    finally:
        out.close()


def main(argv):
    path, count, limit = argv[1], max(1, int(argv[2])), max(1024, int(argv[3]))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    # pythonw has no console: stdin is Apache's pipe, and there is nowhere to print. Ends when Apache closes the pipe.
    run(sys.stdin.buffer, path, count, limit)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except (OSError, ValueError, IndexError):
        # Nothing to say it to: Apache starts the program again if it ends.
        sys.exit(1)
