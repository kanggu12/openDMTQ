"""The arm32 runtime, ready-made: what an app needs to run on phones without 32-bit support.

Newer phones cannot run 32-bit apps, and the game is 32-bit only: the app needs the runtime in it (arm32/README.md). A release
carries it as one zip, the bundle arm32/bundle.sh makes: the translator, the shim, Android's 32-bit linker and system libraries,
and the licenses of all of them. The app builder asks for it here before each build, so that no owner has anything to do for it,
and it comes to data/apk/arm32 from the first of:

  * the copy that came with this program, beside this file: the Windows bundle and a release's tools image have one, the one
    tested with them. One of another version replaces what is in place: a new bundle or image brings its runtime along;
  * a copy put in data/apk by hand: how a host install without internet gets it (docs/closed-network.md). It is taken, and goes
    once it is in place: left there, it would hold back every later runtime;
  * the project's latest release, when no runtime is in place, or when asked to look (--refresh: `opendmtq runtime`, and the
    update of a host install with its one command).

Otherwise what is in place stays: an app's build does not replace a runtime built here (arm32/bundle.sh) behind the back of whoever
built it.

Usage: python3 -m opendmtq_tools.runtime                 the runtime, unless it is in place
       python3 -m opendmtq_tools.runtime --refresh       the same, and the latest release's when it is another version
       python3 -m opendmtq_tools.runtime --pack DIR ZIP  a bundle as that zip, for a release and the Windows bundle
"""

import http.client
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
import zlib

ZIP_NAME = "opendmtq-arm32-runtime.zip"
RELEASE_URL = "https://github.com/kanggu12/openDMTQ/releases/latest/download/" + ZIP_NAME
# The copy a Windows bundle or a release's tools image comes with, beside this file.
HERE = os.path.dirname(os.path.abspath(__file__))
APK_DIR = os.environ.get("OPENDMTQ_APK", "/apk")
# The last failure, for the setup page and the doctor: they look long after this run's output is gone.
NOTE = "runtime-error.txt"
# What any bundle has, whichever phones it was built for: without these it is half of one.
WHOLE = ("bundle.json", "sysroot/bin/linker", "sysroot/lib/libc.so", "notices/NOTICES.txt")
# And one handed out has what phones need (the translator and its proxy on 64-bit phones, the shim on the others), and every
# license: the zip is checked for these before it replaces anything.
HANDED_OUT = WHOLE + ("arm64-v8a/libarm32.so", "arm64-v8a/libarm32proxy.so", "armeabi-v7a/libopendmtq.so", "arm32-agent",
                      "notices/android-NOTICE.html.gz")
# How long to wait for an answer: on a network with no way out this is all a build waits for.
TIMEOUT = 15


class RuntimeError_(Exception):
    """Why the runtime could not be had, in words for the page that shows it."""


def log(message):
    """One line of progress, at once: the setup page shows them as they come."""
    print(message, flush=True)


def fetch(url, path):
    """The latest release's copy to path."""
    log(f"Fetching the runtime for newer phones from {url}")
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r, open(path, "wb") as out:
            shutil.copyfileobj(r, out)
    # URLError is an OSError; a connection cut off half-way can also end as the HTTP library's own error.
    except (OSError, http.client.HTTPException) as e:
        raise RuntimeError_(f"could not fetch it from {url}: {e}") from e


def version_of(path):
    """The version in a runtime zip, once the zip is known to be whole and undamaged."""
    name = os.path.basename(path)
    try:
        with zipfile.ZipFile(path) as z:
            missing = sorted(set(HANDED_OUT) - set(z.namelist()))
            if missing:
                raise RuntimeError_(f"{name} is not the whole runtime: it has no {missing[0]}")
            # Every file's checksum: a copy cut short or damaged on its way goes no further.
            damaged = z.testzip()
            if damaged:
                raise RuntimeError_(f"{name} is damaged: {damaged}")
            return json.loads(z.read("bundle.json")).get("version") or "unknown"
    # A damaged file does not always look like a bad zip: the decompressor has its own errors for what it cannot read.
    except (OSError, ValueError, AttributeError, EOFError, zipfile.BadZipFile, zlib.error) as e:
        raise RuntimeError_(f"{name} is damaged: {e}") from e


def version_in_place(dest):
    """The version of the bundle in place, or None when there is no whole one."""
    try:
        with open(os.path.join(dest, "bundle.json"), encoding="utf-8") as f:
            version = json.load(f).get("version") or "unknown"
    except (OSError, ValueError, AttributeError):
        return None
    return version if all(os.path.isfile(os.path.join(dest, rel)) for rel in WHOLE) else None


def install(path, dest):
    """A zip's bundle in place of the old one, swapped whole: the builder never sees half of one, and what goes wrong leaves the
    old one there. In folders of its own, as another run may be at the same thing (the setup's button just as the server's own
    builder starts): each makes a whole bundle, and whichever comes last stays."""
    folder = os.path.dirname(dest)
    new = tempfile.mkdtemp(dir=folder, prefix=".runtime-new-")
    aside = tempfile.mkdtemp(dir=folder, prefix=".runtime-old-")
    try:
        unpacked = os.path.join(new, "arm32")
        with zipfile.ZipFile(path) as z:
            z.extractall(unpacked)
        # A zip's modes do not come back when it is unpacked, and what the runtime runs must stay executable on the phone (the
        # packer reads the bundle's modes on a host that has them).
        for where, _, names in os.walk(unpacked):
            for name in names:
                os.chmod(os.path.join(where, name), 0o755 if name.endswith(".so") or name in ("linker", "arm32-agent") else 0o644)
        old = os.path.join(aside, "arm32")
        try:
            os.rename(dest, old)
        # None yet, or another run has just moved it.
        except FileNotFoundError:
            old = None
        try:
            os.rename(unpacked, dest)
        except OSError:
            # Another run got there first with a whole one: that will do.
            if version_in_place(dest):
                return
            # Anything else (on Windows, a scanner holding a file): the old one goes back.
            if old:
                os.rename(old, dest)
            raise
    finally:
        shutil.rmtree(new, ignore_errors=True)
        shutil.rmtree(aside, ignore_errors=True)


def same_files(one, other):
    """True when two versions hold the same files. A version ends in a hash of its files, after the commit it was made from
    (arm32/bundle.sh): a release that did not touch the runtime must not make every phone install the app again."""
    return bool(one and other) and one.rsplit("-", 1)[-1] == other.rsplit("-", 1)[-1]


def put_in_place(path, dest, have):
    """A zip's bundle in place, unless what is there holds the same files."""
    version = version_of(path)
    if not same_files(version, have):
        install(path, dest)
        log(f"The runtime for newer phones is ready ({version}).")


def add_runtime(apk_dir=None, refresh=False):
    """The runtime in data/apk/arm32. Raises RuntimeError_ with the reason when it cannot be had."""
    apk_dir = apk_dir or APK_DIR
    dest = os.path.join(apk_dir, "arm32")
    os.makedirs(apk_dir, exist_ok=True)
    have = version_in_place(dest)
    came_with_the_program = os.path.join(HERE, ZIP_NAME)
    by_hand = os.path.join(apk_dir, ZIP_NAME)
    if os.path.isfile(came_with_the_program):
        put_in_place(came_with_the_program, dest, have)
    elif os.path.isfile(by_hand):
        put_in_place(by_hand, dest, have)
        os.remove(by_hand)
    elif refresh or not have:
        # In the data folder: the same disk as where it goes, which is the one known to have room.
        work = tempfile.mkdtemp(dir=apk_dir, prefix=".runtime-")
        try:
            path = os.path.join(work, ZIP_NAME)
            fetch(RELEASE_URL, path)
            put_in_place(path, dest, have)
        finally:
            shutil.rmtree(work, ignore_errors=True)


def add_or_note(apk_dir=None, refresh=False):
    """The runtime if it can be had. A failure is said and noted, and never stops an app's build: without the runtime the app
    still runs on phones that run 32-bit apps. True when the runtime is in place."""
    apk_dir = apk_dir or APK_DIR
    note = os.path.join(apk_dir, NOTE)
    try:
        add_runtime(apk_dir, refresh)
    # Everything, not only what is foreseen here: whatever else it is, it is no reason to leave players without an app.
    except Exception as e:  # noqa: BLE001
        log(f"The runtime for newer phones could not be added: {e}")
        try:
            with open(note, "w", encoding="utf-8") as f:
                f.write(str(e))
        # A folder this run cannot write to already said why above, and the note is only a courtesy.
        except OSError:
            pass
        return False
    # It worked: what went wrong the last time is no longer so.
    try:
        os.remove(note)
    except OSError:
        pass
    return True


def pack(bundle, out):
    """A bundle as the zip a release hands out. Not a half one: a release job stops here instead of publishing it."""
    missing = [rel for rel in HANDED_OUT if not os.path.isfile(os.path.join(bundle, rel))]
    if missing:
        raise SystemExit(f"{bundle} is not a whole runtime: it has no {missing[0]}")
    # Android's own notices do not name libc++: without its license this may not be handed out. An older bundle has none.
    with open(os.path.join(bundle, "notices", "NOTICES.txt"), encoding="utf-8", errors="replace") as f:
        if "---- libc++" not in f.read():
            raise SystemExit(f"{bundle} was made before libc++'s license went with it: arm32/bundle.sh makes it again")
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, _, names in os.walk(bundle):
            for name in sorted(names):
                path = os.path.join(folder, name)
                # Forward slashes whatever the system: the names are the same in every copy.
                z.write(path, os.path.relpath(path, bundle).replace(os.sep, "/"))
                count += 1
    log(f"{out}: {count} files")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 3 and argv[0] == "--pack":
        pack(argv[1], argv[2])
        return 0
    if not add_or_note(refresh="--refresh" in argv):
        return 1
    log(f"The runtime for newer phones is in place ({version_in_place(os.path.join(APK_DIR, 'arm32'))}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
