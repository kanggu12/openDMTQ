"""The arm32 runtime, ready-made: what an app needs to run on phones without 32-bit support.

Newer phones cannot run 32-bit apps, and the game is 32-bit only: the app needs the runtime in it (arm32/README.md). A release
carries it as one zip, the bundle arm32/bundle.sh makes: the translator, the shim, Android's 32-bit linker and system libraries,
and the licenses of all of them. The app builder asks for it here before each build, so that no owner has anything to do for it,
and it comes to data/apk/arm32 from the first of:

  * the copy that came with this program, beside this file: the Windows bundle and a release's tools image have one, the one
    tested with them. One of another version replaces what is in place: a new bundle or image brings its runtime along;
  * a copy put in data/apk by hand, as downloaded from a release (opendmtq-phone-runtime-1.2.3-android-arm64-armv7.zip) or
    under this program's own name: how a host install without internet gets it (docs/closed-network.md). It is taken, and
    goes once it is in place: left there, it would hold back every later runtime;
  * the project's latest release, when no runtime is in place, or when asked to look (--refresh: `opendmtq runtime`, and the
    update of a host install with its one command).

Otherwise what is in place stays: an app's build does not replace a runtime built here (arm32/bundle.sh) behind the back of whoever
built it.

What comes from a release is checked before it is used: the release's checksums, fetched with it, carry the OpenDMTQ project's
signature (signing.py), and the zip is the file they sum. A copy put in data/apk by hand is checked the same way when the release's
checksums and their signature are beside it (a host install's kit carries them); one that does not match is refused, in words the
setup page shows (strings.py release.unsigned_file).

Usage: python3 -m opendmtq_tools.runtime                 the runtime, unless it is in place
       python3 -m opendmtq_tools.runtime --refresh       the same, and the latest release's when it is another version
       python3 -m opendmtq_tools.runtime --pack DIR ZIP  a bundle as that zip, for a release and the Windows bundle
"""

import glob
import http.client
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
import zlib

try:
    # In the tools' package.
    from . import signing
except ImportError:
    # Run as a file of its own (python3 runtime.py --pack, by the release job): the module beside it.
    import signing

# The zip's name beside this file, in data/apk and in a release job's build.
ZIP_NAME = "opendmtq-arm32-runtime.zip"
# The project's releases. Each file of a release has the release's version in its name (.github/release_assets.py names
# them), so a download first asks which release is the latest.
RELEASES = "https://github.com/kanggu12/openDMTQ/releases"
# The zip's name in a release, as a person also downloads it into data/apk.
RELEASE_NAME = "opendmtq-phone-runtime-{version}-android-arm64-armv7.zip"
# A file of that name, whatever its version, for one put in data/apk by hand.
RELEASE_GLOB = RELEASE_NAME.format(version="*")
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
# How long a whole answer may take, however its bytes come: a release's file (the runtime, the PC client's installer and
# its update packages: tens of megabytes, a slow line among them) and a small one (its checksums, their signature). A
# read's own wait (TIMEOUT) is no limit to a server that sends a byte at a time, each within it.
FILE_SECONDS = 30 * 60
SMALL_SECONDS = 60
# A piece of an answer read at a time: what has come, at most this much, the clock looked at after each.
PIECE = 64 * 1024


class RuntimeError_(Exception):
    """Why the runtime could not be had, in words for the page that shows it."""


class Late(OSError):
    """An answer that had not come whole within its time (pieces)."""


def pieces(response, started, seconds):
    """An answer's body in the pieces it comes in (what has arrived, at most PIECE each), whole within `seconds` from
    `started` (time.monotonic() when it was asked for, its headers' time counted too): the clock is looked at after each
    piece, so a server that sends a byte at a time, each within a read's wait, is stopped at the deadline, give or take
    one read's wait (TIMEOUT); a megabyte read at a time waited for a megabyte however long it took. Late past it, an
    OSError as any failure of a download is. As the PC client keeps its answers to one deadline
    (client/opendmtq_client/server.py, within)."""
    while True:
        # One read of the connection at most: what has come, without waiting for the rest of the piece.
        piece = response.read1(PIECE)
        if not piece:
            return
        yield piece
        if time.monotonic() - started > seconds:
            raise Late(f"it did not come whole within {seconds} seconds")


def log(message):
    """One line of progress, at once: the setup page shows them as they come."""
    print(message, flush=True)


def latest_version(releases=None):
    """The latest release's version (1.2.3). GitHub answers the releases' /latest with a redirect to the tag's page: the
    page's address is all it takes, so a HEAD request, and no API, whose limit for unnamed callers a shared address runs
    into."""
    releases = releases or RELEASES
    try:
        with urllib.request.urlopen(urllib.request.Request(releases + "/latest", method="HEAD"), timeout=TIMEOUT) as r:
            where = r.geturl()
    # No way out, or an answer cut off: said as for a download.
    except (OSError, http.client.HTTPException) as e:
        raise RuntimeError_(f"could not ask {releases} for the latest release: {e}") from e
    # A repository with no release stays on its releases' page.
    found = re.search(r"/releases/tag/v([0-9][0-9A-Za-z.+-]*)/?$", where)
    if not found:
        raise RuntimeError_(f"{releases} has no release")
    return found.group(1)


def release_url(name, version, releases=None):
    """Where the release `version` keeps its file `name` (a pattern with {version})."""
    return f"{releases or RELEASES}/download/v{version}/{name.format(version=version)}"


class Missing(RuntimeError_):
    """A release with no such file (404): a release from before its files were signed, or no release of that version."""


def _small(url, limit):
    """A release's small file (its checksums, their signature) as bytes, at most `limit` and one more, whole within
    SMALL_SECONDS however it trickles in (pieces)."""
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            data = b""
            for piece in pieces(r, started, SMALL_SECONDS):
                data += piece
                # Past the limit: no such file is that long, and no more of it is read.
                if len(data) > limit:
                    break
            return data[:limit + 1]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise Missing(f"{url} is not there") from None
        raise RuntimeError_(f"could not fetch {url}: {e}") from e
    except (OSError, http.client.HTTPException) as e:
        raise RuntimeError_(f"could not fetch {url}: {e}") from e


def release_sums(version, releases=None):
    """{file name: SHA-256} of the release `version`: its checksums, fetched with their signature and checked against the
    project's key (signing.check_sums). signing.Unsigned when they do not check out; Missing for a release without them."""
    try:
        data = _small(release_url(signing.SUMS_NAME, version, releases), signing.SUMS_LIMIT)
    except Missing:
        # No such file: no release of that version, or one from before releases were signed (strings.py words it).
        raise Missing(f"the release {version} has no signed checksums") from None
    try:
        signature = _small(release_url(signing.SUMS_NAME + signing.SIG_SUFFIX, version, releases), signing.SIG_SIZE)
    except Missing:
        # Checksums and no signature: nothing says the project made them.
        raise signing.Unsigned(f"{signing.sums_name(version)} is not signed by the OpenDMTQ project") from None
    return signing.check_sums(data, signature, version)


def sums_beside(folder, version):
    """{file name: SHA-256} of the release `version` from its checksums and their signature in `folder` (put there with a
    file of the release, by hand or by a host install's kit), checked; None when they are not there. signing.Unsigned when
    they are and do not check out."""
    path = os.path.join(folder, signing.sums_name(version))
    try:
        with open(path, "rb") as f:
            data = f.read(signing.SUMS_LIMIT + 1)
        with open(path + signing.SIG_SUFFIX, "rb") as f:
            signature = f.read(signing.SIG_SIZE + 1)
    except OSError:
        return None
    return signing.check_sums(data, signature, version)


def checked(path, name, version, sums):
    """Nothing when the file at `path` is the release `version`'s file `name` as its signed checksums give it; else
    RuntimeError_ with the words of signing.Unsigned ("... is not the file the release signed"), which the setup page shows
    in its own language (strings.py release.unsigned_file)."""
    try:
        signing.check_file(sums, name.format(version=version), path)
    except signing.Unsigned as e:
        raise RuntimeError_(str(e)) from None


def version_named(path, pattern):
    """The version a release's file name says (the part that stands for {version} in `pattern`), or None."""
    head, _, tail = pattern.partition("{version}")
    name = os.path.basename(path)
    if not (name.startswith(head) and name.endswith(tail)):
        return None
    found = name[len(head):len(name) - len(tail)]
    return found if re.fullmatch(r"[0-9][0-9A-Za-z.+-]*", found) else None


def by_hand(apk_dir):
    """A copy put in data/apk by hand: under this program's name, or as downloaded from a release (the newest name
    first, should there be several); None when there is none."""
    plain = os.path.join(apk_dir, ZIP_NAME)
    if os.path.isfile(plain):
        return plain
    found = glob.glob(os.path.join(glob.escape(apk_dir), RELEASE_GLOB))
    # The newest by the numbers in its name: 0.11.0 after 0.9.0, which an order by the letters would not give.
    return max(found, key=numbers_in) if found else None


def numbers_in(path):
    """A file name's numbers in order, to compare versions by: (0, 11, 0) for ...-0.11.0-..."""
    return tuple(int(n) for n in re.findall(r"[0-9]+", os.path.basename(path)))


def fetch(url, path):
    """The latest release's copy to path, whole within FILE_SECONDS however it trickles in (pieces)."""
    log(f"Fetching the runtime for newer phones from {url}")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r, open(path, "wb") as out:
            for piece in pieces(r, started, FILE_SECONDS):
                out.write(piece)
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
    put_there = by_hand(apk_dir)
    if os.path.isfile(came_with_the_program):
        put_in_place(came_with_the_program, dest, have)
    elif put_there:
        # A release's file with the release's signed checksums beside it (a kit carries them): checked against them first.
        version = version_named(put_there, RELEASE_NAME)
        try:
            sums = sums_beside(apk_dir, version) if version else None
        except signing.Unsigned as e:
            raise RuntimeError_(str(e)) from None
        if sums is not None:
            checked(put_there, RELEASE_NAME, version, sums)
        put_in_place(put_there, dest, have)
        # The one taken goes, and with it any older one downloaded before: the next build would take that one back.
        for path in [put_there] + glob.glob(os.path.join(glob.escape(apk_dir), RELEASE_GLOB)):
            if os.path.exists(path):
                os.remove(path)
    elif refresh or not have:
        # In the data folder: the same disk as where it goes, which is the one known to have room.
        work = tempfile.mkdtemp(dir=apk_dir, prefix=".runtime-")
        try:
            path = os.path.join(work, ZIP_NAME)
            latest = latest_version()
            # The release's signed checksums first: without them nothing of it is fetched.
            try:
                sums = release_sums(latest)
            except signing.Unsigned as e:
                raise RuntimeError_(str(e)) from None
            fetch(release_url(RELEASE_NAME, latest), path)
            checked(path, RELEASE_NAME, latest, sums)
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
    before = version_in_place(os.path.join(APK_DIR, "arm32"))
    if not add_or_note(refresh="--refresh" in argv):
        return 1
    now = version_in_place(os.path.join(APK_DIR, "arm32"))
    # One line: a new one put in place has said it is ready (put_in_place); the one there already says it is in place.
    if now == before:
        log(f"The runtime for newer phones is in place ({now}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
