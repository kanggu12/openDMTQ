"""Updates of the installed launcher and its player, from the server it plays on or from the project's releases.

Only a launcher installed by its installer can update itself; one run from source or from a copied folder says so
instead. Every call here may be slow (network), so the window runs them on a worker thread.

Where an update comes from, in this order:

  1. The server PLAY plays on (the launcher's current server), at its /updates/: the PC client's update feed of the
     version the server hands out (releases.win.json), that release's checksums and their signature, and the packages
     the feed names (server/portal/updates.php). A launcher goes no further than its server: what a server hands out is
     the newest version it takes from anywhere, and a server that hands out no feed (one older than 0.11.0) lets the
     project's releases in only up to its own version (client.php?about), so that the launcher stays matched to it.
     A server that does not answer is no reason to go elsewhere: the launcher says nothing then, as it does offline.
  2. The project's releases on GitHub, the address written in at build time (client/packaging/windows/build.sh's
     OPENDMTQ_UPDATE_SOURCE into update-source.txt; the same variable at run time takes its place, for a test): the
     latest release's feed, checksums and signature, under its tag. With no server, or one without a feed.

An update is taken only when the release's checksums carry the OpenDMTQ project's signature (signing.py) and the feed is
the file they sum; its package is a file they sum as well, or, put together from a delta package, holds the files the
feed gives (FilesSHA256). Nothing of a download is in the install folder before it is checked (apply):

  1. the feed's names are checked before anything is fetched or deleted: the packages named for the version offered,
     that version newer than the one installed (offered);
  2. the launcher fetches the update itself, into a folder of its own in the temporary folder: the delta package when
     the version installed is the one the release's delta starts from, which the installed Update.exe puts the new
     package together from, into that same folder; else, or when that does not give the package signed, the whole one;
  3. the package is checked there: by its bytes, or put together from the delta by the files it holds; and its own
     manifest is the PC client's of the version offered;
  4. only then is it moved into packages\\, the installed Update.exe replaced by the one the package carries, and
     Velopack told to put the package in once this program has ended. The packages of earlier versions go at the next
     start, once the new version runs (outcome).

Velopack's own check and download (UpdateManager.check_for_updates and download_updates) are never used: the check reads
a feed nobody has checked, and the download writes what it fetches straight into packages\\ under the feed's names and
puts the downloaded package's Update.exe over the installed one before it returns (Velopack 1.2.161, manager.rs).
"""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from opendmtq_client import installed, installer, signing
from opendmtq_client.errors import Worded

log = logging.getLogger("opendmtq_client")

# How long the look for a newer launcher at each start waits for its answer, in seconds: past it the launcher says
# nothing, as it says nothing offline.
START_LIMIT = 10

SOURCE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "update-source.txt")
# The release's files a launcher reads, by the names .github/release_assets.py gives them: the feed (Velopack's name),
# the full package and the delta package from the release before.
FEED = "releases.win.json"
PACKAGE = "opendmtq.client-{version}-full.nupkg"
DELTA = "opendmtq.client-{version}-delta.nupkg"
# The field of the feed's full package that gives the files it holds (signing.files_sha256).
FILES_FIELD = "FilesSHA256"
# Where a server keeps them, on its one port.
SERVER_PATH = "/updates/"
# A version as a release names one: every file name below is made of it, so nothing but these letters may pass (no
# folder, no drive, no name of dots only).
VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?")
# The most bytes a feed may hold (a few entries of a few hundred bytes), a package (some 40 MB; a disk is never
# filled from a feed), the seconds one read may wait and one file may take, and the seconds Update.exe may take to put
# a package together from a delta.
FEED_LIMIT, FETCH_LIMIT, READ_SECONDS, FILE_SECONDS, PATCH_SECONDS = 256 << 10, 512 << 20, 30, 1800, 600
# The launcher's own folders for what it fetches start with this in the temporary folder; one left by a launcher that
# ended mid-update goes at the next update once it is this many seconds old.
OWN_PREFIX, OWN_STALE = "opendmtq-update-", 3600
# A package written beside its place until it is whole (copied in from another drive): a name Velopack reads as no
# package.
PART = ".odq-new"
# Where a package keeps the program's files, and its copy of Update.exe (repair.py's names).
APP_PREFIX, UPDATER_ENTRY = "lib/app/", "Squirrel.exe"


def _update_source():
    """The project's releases: the variable when it is set, else the address written in at build time, else none."""
    if os.environ.get("OPENDMTQ_UPDATE_SOURCE"):
        return os.environ["OPENDMTQ_UPDATE_SOURCE"].strip()
    try:
        with open(SOURCE_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


UPDATE_SOURCE = _update_source()


class UpdateError(Worded):
    """An update that is not put in, worded for the player (i18n.TEXT)."""


class Refused(Exception):
    """A release's files that do not check out against the project's signature: why, for the log."""


class Missing(Exception):
    """A release's file the source does not have (404)."""


class NoFeed(Exception):
    """A server that hands out no updates (one older than 0.11.0 answers 404 at /updates/)."""


class Result:
    """What a check found: kind is 'not_installed', 'no_source', 'uptodate', 'available', 'refused' or 'failed'. A
    failed or refused check's `error` is the words for the log; a person reads it by its kind (i18n). `source` is where
    the answer came from (a Source), `info` the release on offer (a Release)."""

    def __init__(self, kind, version=None, info=None, error=None, source=None):
        self.kind, self.version, self.info, self.error, self.source = kind, version, info, error, source


class Source:
    """Where a release's files are fetched from: a server's /updates/ (kind "server", its entry in the launcher's
    state), or the project's releases on GitHub (kind "github"), each release's files under its tag."""

    def __init__(self, kind, base, server=None):
        self.kind, self.base, self.server = kind, base.rstrip("/"), server

    def url(self, name, version):
        """The address of a release's file. `name` is a plain file name (offered, check), so it stays where it is
        put."""
        if self.kind == "server":
            # The server keeps one release's files, the one it hands out: by their names alone.
            return self.base + SERVER_PATH + urllib.parse.quote(name)
        return "%s/releases/download/v%s/%s" % (self.base, urllib.parse.quote(version), urllib.parse.quote(name))

    def label(self):
        """The source as a person reads it: the server as its ready check names it, or "GitHub"."""
        if self.kind == "server":
            from opendmtq_client import state as st
            return st.label(self.server)
        return "GitHub"

    def opener(self):
        """What a request goes through: for a server, the launcher's own (the server's certificate authority trusted
        for it alone, no redirect followed: server.py); for GitHub, one that follows GitHub's redirects to its file
        store, checked against Windows' own authorities."""
        from opendmtq_client import server as srv
        if self.kind == "server":
            return srv._opener(self.base)
        # GitHub's: its answers kept to their deadlines as a server's are (server.within), its redirects followed.
        return srv.build_opener()


class Release:
    """One release's files as checked: its version, the feed (JSON) and the signed checksums ({name: SHA-256}), from
    the source they came from."""

    def __init__(self, source, version, feed, sums):
        self.source, self.version, self.feed, self.sums = source, version, feed, sums

    def assets(self):
        """The feed's entries: each a dict as vpk writes it (PackageId, Version, Type, FileName, SHA256, Size)."""
        found = self.feed.get("Assets") if isinstance(self.feed, dict) else None
        return [a for a in found if isinstance(a, dict)] if isinstance(found, list) else []


def current_version():
    """The installed version, or None outside an installed launcher."""
    try:
        import velopack
        return velopack.UpdateManager(UPDATE_SOURCE or ".").get_current_version()
    except Exception:  # noqa: BLE001  (not installed: run from source or a copied folder)
        return None


def shown_version():
    """The version the launcher shows, beside the logo, on the Launcher page and on the command line: the installed one,
    else the code's own (a run from source or from a copied folder). One source for all of them, so that after an
    update none of them says an older number than the others."""
    # Imported here: the package's __init__ reads the version once, and this module is imported by it indirectly.
    from opendmtq_client import __version__
    # Velopack's installed version first: what the installer put in and the updates moved on.
    return current_version() or __version__


def _request(url, method=None):
    """A request as the launcher makes them, with its own name (server.py's requests carry the same)."""
    from opendmtq_client import __version__
    request = urllib.request.Request(url, method=method)
    request.add_header("User-Agent", "OpenDMTQ-client/%s" % __version__)
    return request


def _read(source, name, version, limit):
    """A release's small file (the feed, the checksums, the signature) as bytes, at most `limit` and one more (a file
    longer than that is none of these), whole within READ_SECONDS however it trickles in. Missing for a 404."""
    from opendmtq_client import server as srv
    request = _request(source.url(name, version))
    try:
        with srv.within(READ_SECONDS), source.opener().open(request, timeout=READ_SECONDS) as response:
            return response.read(limit + 1)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise Missing("%s has no %s" % (source.base, name)) from None
        raise OSError("%s answered %s for %s" % (source.base, e.code, name)) from None


def _newest_full(assets):
    """The feed's newest full package of the PC client, as (its version, its entry), or (None, None)."""
    best = (None, None)
    for asset in assets:
        version = str(asset.get("Version") or "")
        if asset.get("Type") == "Full" and asset.get("PackageId") == installed.PACKAGE_ID and VERSION.fullmatch(version):
            if best[0] is None or installer.version_key(version) > installer.version_key(best[0]):
                best = (version, asset)
    return best


def release(source, version=None):
    """The release a source offers, checked: its feed, then its checksums and their signature, by a key the launcher
    takes, and the feed the very file they sum. `version` names the release on GitHub (its tag); a server keeps one.
    Refused, with why, for anything that does not check out; NoFeed, OSError and ValueError when it cannot be had."""
    try:
        data = _read(source, FEED, version, FEED_LIMIT)
    except Missing as e:
        if source.kind == "server":
            # A server with nothing at /updates/: one that hands out no updates.
            raise NoFeed(str(e)) from None
        raise OSError(str(e)) from None
    if len(data) > FEED_LIMIT:
        raise Refused("%s from %s is far larger than an update feed" % (FEED, source.base))
    try:
        feed = json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise Refused("%s from %s is no update feed" % (FEED, source.base)) from None
    newest, _ = _newest_full(Release(source, None, feed, {}).assets())
    if newest is None or (version is not None and newest != version):
        # A feed with no package of the PC client, or one of another release than its tag.
        raise Refused("%s from %s offers no package of %s" % (FEED, source.base, version or "the PC client"))
    name = signing.sums_name(newest)
    try:
        sums_data = _read(source, name, newest, signing.SUMS_LIMIT)
        signature = _read(source, name + signing.SIG_SUFFIX, newest, signing.SIG_SIZE)
    except Missing as e:
        # A feed without the release's signed checksums beside it (a release before 0.11.0 has none): nothing in it
        # says the project made it.
        raise Refused("%s: the release %s has no signed checksums" % (e, newest)) from None
    try:
        sums = signing.check_sums(sums_data, signature, newest)
    except signing.Unsigned as e:
        raise Refused(str(e)) from None
    # The feed itself is a file of the release: what it names and gives is signed only as the file the checksums sum.
    if sums.get(FEED) != hashlib.sha256(data).hexdigest():
        raise Refused("%s from %s is not the feed the release %s signed" % (FEED, source.base, newest))
    return Release(source, newest, feed, sums)


def _latest_tag(source):
    """The latest release's version on GitHub (1.2.3): its /releases/latest leads to the tag's page, whose address names
    it. A HEAD request, as the servers' tools ask (no API, whose limit for unnamed callers a shared address runs into),
    answered within READ_SECONDS however it trickles in, its redirects too."""
    from opendmtq_client import server as srv
    request = _request(source.base + "/releases/latest", method="HEAD")
    with srv.within(READ_SECONDS), source.opener().open(request, timeout=READ_SECONDS) as response:
        where = response.geturl()
    found = re.search(r"/releases/tag/v(%s)/?$" % VERSION.pattern, where)
    if not found:
        raise OSError("%s has no release" % source.base)
    return found.group(1)


def _current_server(state):
    """The server PLAY plays on, from the state given or the launcher's file, or None."""
    if state is None:
        from opendmtq_client import state as st
        try:
            state = st.LauncherState.load()
        except Exception:  # noqa: BLE001  (a state file that cannot be read: no server to ask)
            return None
    try:
        return state.server()
    except Exception:  # noqa: BLE001
        return None


def _answer(found, have, source):
    """A Result for a release checked (found), against the version installed (have)."""
    if installer.version_key(found.version) > installer.version_key(have):
        return Result("available", version=found.version, info=found, source=source)
    return Result("uptodate", version=found.version, source=source)


def check(state=None):
    """Whether a newer version is on offer: its server first, GitHub second (the module's description). `state`: the
    launcher's settings (the window's own); read from its file when none is given. Whatever goes wrong is a check that
    failed, said as one: never an error that ends the worker thread with the Launcher page still saying it checks."""
    try:
        return _check(state)
    except Exception as e:  # noqa: BLE001  (a feed or an answer of a shape nobody foresaw)
        log.exception("could not check for updates")
        return Result("failed", error=str(e))


def _check(state):
    """check(), with what it foresees caught here."""
    try:
        import velopack  # noqa: F401  (only to know whether the update library is there)
    except ImportError:
        return Result("not_installed")
    have = current_version()
    if have is None:
        # Velopack finds no installation: run from source or a copied folder.
        return Result("not_installed")
    server = _current_server(state)
    cap = None
    if server is not None:
        source = Source("server", server["url"], server)
        try:
            return _answer(release(source), have, source)
        except NoFeed:
            # An older server: the project's releases, up to its own version. Asked as the ready check asks it.
            from opendmtq_client import server as srv
            try:
                said = srv.about(server["url"]).get("opendmtq") or ""
                # The release its version names, by its numbers: a copy past a release says its commit after a dash
                # (0.11.2-29a49e4, as the command line names a clone's), one still to come its pre-release, and GitHub
                # has the release's tag alone (the servers' own tools read it so: windows_client.own_release).
                named = re.match(r"\d+\.\d+\.\d+", said)
                cap = named.group(0) if named else None
            except srv.ServerError as e:
                log.warning("could not ask %s for its version: %s", server["url"], e)
                return Result("failed", error=str(e), source=source)
        except Refused as e:
            log.warning("refused the update %s offers: %s", server["url"], e)
            return Result("refused", error=str(e), source=source)
        except (OSError, ValueError) as e:
            # No answer, or one cut off: said by its kind, Python's words in the log.
            log.warning("could not check %s for updates: %s", server["url"], e)
            return Result("failed", error=str(e), source=source)
    if not UPDATE_SOURCE:
        return Result("no_source")
    github = Source("github", UPDATE_SOURCE)
    try:
        latest = _latest_tag(github)
        if cap and VERSION.fullmatch(cap) and installer.version_key(latest) > installer.version_key(cap):
            # The server is older than the latest release: the launcher stays with the server's version.
            if installer.version_key(cap) <= installer.version_key(have):
                return Result("uptodate", version=cap, source=Source("server", server["url"], server))
            latest = cap
        return _answer(release(github, latest), have, github)
    except Refused as e:
        log.warning("refused the update GitHub offers: %s", e)
        return Result("refused", error=str(e), source=github)
    except (OSError, ValueError, NoFeed) as e:
        log.warning("could not check for updates: %s", e)
        return Result("failed", error=str(e), source=github)


class Look:
    """The look for a newer launcher that each start makes (the window's, --status's): check() on a thread of its own,
    started at once, so that what the start does meanwhile waits for nothing. Nothing is downloaded or installed."""

    def __init__(self, limit=None, state=None):
        # The time it may take (START_LIMIT, read now), counted from now: a start that asks for the answer later waits
        # only for what is left.
        self.started, self.limit = time.monotonic(), START_LIMIT if limit is None else limit
        self._result, self._done, self._state = None, threading.Event(), state
        threading.Thread(target=self._look, daemon=True, name="update-look").start()

    def _look(self):
        try:
            self._result = check(self._state)
        finally:
            # Answered, whatever the answer: newer() stops waiting.
            self._done.set()

    def newer(self):
        """The newer version on offer (check()'s result, kind "available"), or None for anything else: up to date, no
        network, a failure, a refusal (in the log), a launcher not installed, or no answer within the time limit (the
        look goes on, and its late answer is dropped)."""
        left = self.limit - (time.monotonic() - self.started)
        if not self._done.wait(max(0.0, left)):
            log.info("no answer about updates within %d s at the start: nothing said", self.limit)
            return None
        result = self._result
        return result if result is not None and result.kind == "available" else None


# ---- the update itself

def plain(name):
    """True when a name from a feed is one file's name and nothing else: no folder, no drive, no stream, no name of dots
    only, nothing Windows would read as another name."""
    if not isinstance(name, str) or not name:
        return False
    if any(c in name for c in "/\\:") or any(ord(c) < 32 for c in name):
        # A separator leaves the folder, a colon names a drive or another stream, a control character no file.
        return False
    # Windows drops dots and spaces at a name's end ("x." and "x " would be the file x).
    return name == name.strip() and not name.endswith(".")


def _refuse(result, why):
    """An update that is not the project's own release of the version offered is not put in: the log says what was
    wrong with it, the player reads the one sentence."""
    log.warning("refused the update to %s from %s: %s", result.version, result.source.base, why)
    raise UpdateError("the update to %s from %s is not signed by the OpenDMTQ project, so it was not installed"
                      % (result.version, result.source.label()), "error.update.unsigned", v=result.version,
                      source=result.source.label())


def offered(result, have=None):
    """What the release offers, checked before anything is fetched or deleted: (the full package's entry, the delta
    package's entry or None, the installed package to start the delta from or None). Refused: a version that is none, a
    package not named for the version, a version not newer than the one installed, a size past any package's."""
    found, version = result.info, str(result.version)
    if not VERSION.fullmatch(version):
        _refuse(result, "the feed's version %r is not a version" % version)
    have = have or current_version()
    if installer.version_key(version) <= installer.version_key(have or "0"):
        # Velopack offers only a newer version; a feed's list is never taken for that alone.
        _refuse(result, "version %s is not newer than the one installed, %s" % (version, have))
    full = delta = None
    for asset in found.assets():
        if asset.get("Version") != version or asset.get("PackageId") != installed.PACKAGE_ID:
            continue
        kind, name = asset.get("Type"), asset.get("FileName")
        if not plain(name) or name != {"Full": PACKAGE, "Delta": DELTA}.get(kind, "").format(version=version):
            # A feed that names anything else for the version offered is not one the project made.
            _refuse(result, "the feed names %r as the %s package of %s" % (name, kind, version))
        if not isinstance(asset.get("Size"), int) or not 0 < asset["Size"] <= FETCH_LIMIT:
            _refuse(result, "the feed gives %s a size no package has (%r)" % (name, asset.get("Size")))
        if kind == "Full":
            full = asset
        else:
            delta = asset
    if full is None:
        _refuse(result, "the feed has no full package of %s" % version)
    base = None
    if delta is not None:
        # The delta starts from the release before: the newest full package before this one in the feed (vpk lists the
        # one it made the delta from). Taken only by the launcher of that version, from its own package.
        before = [str(a.get("Version")) for a in found.assets() if a.get("Type") == "Full"
                  and VERSION.fullmatch(str(a.get("Version") or ""))
                  and installer.version_key(str(a.get("Version"))) < installer.version_key(version)]
        start = max(before, key=installer.version_key) if before else None
        root = installed.root()
        if start is not None and have == start and root:
            from opendmtq_client import repair
            try:
                base = repair.package_path(root)
            except repair.RepairError:
                log.info("no package of %s in packages\\ to start the delta from: the whole package", have)
        if base is None:
            delta = None
    return full, delta, base


def _own_folder():
    """A new folder of the launcher's own for what it fetches, in the temporary folder: outside the install folder, so
    nothing reaches that before it is checked. One left by a launcher that ended mid-update goes first, once it is old
    enough to be no other launcher's update under way."""
    top = tempfile.gettempdir()
    try:
        names = os.listdir(top)
    except OSError:
        names = []
    for name in names:
        path = os.path.join(top, name)
        try:
            if name.startswith(OWN_PREFIX) and time.time() - os.path.getmtime(path) > OWN_STALE:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            # Gone meanwhile: nothing left to do.
            pass
    return tempfile.mkdtemp(prefix=OWN_PREFIX)


def _fetch(result, asset, folder):
    """One package of the release fetched into the launcher's own folder; returns its path. It stops at the size the
    feed gives and at FILE_SECONDS: a feed is never given the whole disk or the whole day. A download that fails says
    so in words."""
    from opendmtq_client import server as srv
    name, size = asset["FileName"], asset["Size"]
    path = os.path.join(folder, name)
    request = _request(result.source.url(name, result.version))
    try:
        # The whole file within FILE_SECONDS, however it trickles in: every read waits only for what is left of them
        # (server.within), where a time checked between reads of a megabyte waited on a megabyte coming a byte at a time.
        with srv.within(FILE_SECONDS), result.source.opener().open(request, timeout=READ_SECONDS) as response, \
                open(path, "wb") as out:
            done = 0
            # A megabyte at a time: a package is tens of megabytes.
            for piece in iter(lambda: response.read(1 << 20), b""):
                done += len(piece)
                if done > size:
                    raise OSError("%s is larger than the feed says (%d bytes and more)" % (name, done))
                out.write(piece)
    except Exception as e:  # noqa: BLE001  (the network's errors are of many kinds; each ends the same way)
        # Its deadline passed: in a read of the file, or of the answer's start (which urllib hands on as its reason).
        late = isinstance(e, srv.Late) or isinstance(getattr(e, "reason", None), srv.Late)
        log.warning("could not fetch %s from %s: %s", name, result.source.base,
                    "it took longer than %d seconds" % FILE_SECONDS if late else e)
        raise UpdateError("the update to %s could not be downloaded" % result.version, "error.update.download",
                          v=result.version) from e
    return path


def updater():
    """Velopack's Update.exe of the installed launcher, above current\\, or None outside an install."""
    root = installed.root()
    return installed.updater(root) if root else None


def _put_together(base, delta, out, run):
    """Have the installed Update.exe put the new package together from the installed one and the delta package
    (Velopack's own command, as its library runs it), into the launcher's own folder; True when it wrote `out`."""
    exe = updater()
    if exe is None:
        log.warning("no Update.exe to put the package together: the whole package")
        return False
    args = [exe, "patch", "--old", base, "--output", out, "--delta", delta]
    try:
        # No window of its own, nothing read from this program's console (the window copy has none).
        done = run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=PATCH_SECONDS,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Update.exe could not put the package together: %s", e)
        return False
    if done.returncode != 0:
        # Whatever it wrote before it failed is not taken: the end of what it said goes to the log.
        log.warning("Update.exe could not put the package together (exit %s): %s", done.returncode,
                    (done.stderr or b"")[-400:])
        return False
    return os.path.isfile(out)


def _from_delta(result, full, delta, base, folder, run):
    """The package put together from the delta package, in the launcher's own folder: its path when it checked out, or
    None (the caller fetches the whole package). The delta is checked against the signed checksums before Update.exe
    reads it; what Update.exe wrote is checked by its bytes, or by the files it holds (FilesSHA256, signed in the
    feed), as it is zipped again."""
    try:
        path = _fetch(result, delta, folder)
    except UpdateError:
        # A delta the feed names and the source does not hand out (_fetch said why in the log): the whole package.
        return None
    try:
        signing.check_file(result.info.sums, delta["FileName"], path)
    except signing.Unsigned as e:
        log.warning("the delta package is refused: %s", e)
        return None
    out = os.path.join(folder, full["FileName"])
    if not _put_together(base, path, out, run):
        return None
    if signing.sha256_of(out) == result.info.sums.get(full["FileName"]):
        log.info("the update %s, put together from the delta package, is the package the release signed", result.version)
        return out
    want = str(full.get(FILES_FIELD) or "").lower()
    if want and signing.files_sha256(out) == want:
        log.info("the update %s, put together from the delta package, holds the files the release signed",
                 result.version)
        return out
    log.warning("the package put together from the delta package is not the one the release signed")
    _remove(out)
    return None


def inside(package):
    """(id, version) a package itself gives (its one .nuspec at the top, the file Velopack reads them from), or (None,
    None) for a package with no such file, more than one, or one that cannot be read."""
    try:
        with zipfile.ZipFile(package) as archive:
            specs = [i for i in archive.infolist() if i.filename.endswith(".nuspec") and "/" not in i.filename]
            # Velopack takes the first it finds: with two, which one that is depends on the order, so neither counts.
            if len(specs) != 1 or specs[0].file_size > 1 << 20:
                return None, None
            text = archive.read(specs[0]).decode("utf-8", "replace")
    except (zipfile.BadZipFile, OSError, ValueError, EOFError):
        return None, None
    found = [re.search(r"<%s>\s*([^<\s]+)\s*</%s>" % (tag, tag), text) for tag in ("id", "version")]
    return tuple(m.group(1) if m else None for m in found)


def _checked(result, full, delta, base, folder, tell, run):
    """The update's package in the launcher's own folder, checked: put together from the delta package when there is
    one for the installed version, else (or when that did not give the package signed) the whole one, which
    tell("whole") says first. Refused: a package that is not the one the release signed, or whose own manifest is not
    the PC client's of the version offered."""
    package = None
    if delta is not None:
        try:
            package = _from_delta(result, full, delta, base, folder, run)
        except Exception:  # noqa: BLE001  (whatever went wrong with the delta: the whole package instead)
            log.exception("the delta package of %s could not be used", result.version)
        if package is None:
            log.warning("downloading the whole package of %s instead", result.version)
            if tell is not None:
                tell("whole")
    if package is None:
        package = _fetch(result, full, folder)
        try:
            signing.check_file(result.info.sums, full["FileName"], package)
        except signing.Unsigned as e:
            _refuse(result, str(e))
        log.info("the update %s is the package the release signed", full["FileName"])
    package_id, version = inside(package)
    if package_id != installed.PACKAGE_ID or installer.version_key(version or "0") != installer.version_key(result.version):
        # What Velopack puts in is the program and version written inside the package, whatever the feed called it.
        _refuse(result, "the package says it is %s %s, the feed %s" % (package_id, version, result.version))
    return package


def _remove(path):
    """A file gone, when it is there."""
    try:
        os.remove(path)
    except OSError:
        pass


def packages_dir():
    """Where Velopack keeps the packages it puts in: packages\\ of the install folder."""
    root = installed.root()
    if root is None:
        raise UpdateError("updates work in the launcher installed by its installer", "about.not_installed")
    return os.path.join(root, "packages")


def _leftovers(name):
    """What an earlier update left in packages\\ under the package's name (a package never handed over, a copy never
    finished) goes: nothing under that name is there but what this update checks."""
    for path in (os.path.join(packages_dir(), name), os.path.join(packages_dir(), name + PART)):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            # In use, or no rights: the checked package is moved over it below, or that move says what is wrong.
            log.warning("could not remove %s, left by an earlier update: %s", path, e)


def _hand_in(package, name):
    """Move a package that checked out into packages\\, where Velopack takes it from. From another drive it is copied in
    under a name Velopack reads as no package, compared with the one checked, and renamed: a package is under its own
    name only whole and checked."""
    os.makedirs(packages_dir(), exist_ok=True)
    target = os.path.join(packages_dir(), name)
    try:
        os.replace(package, target)
        return target
    except OSError:
        # The temporary folder is on another drive than the install folder: a rename cannot cross drives.
        pass
    part = target + PART
    try:
        shutil.copyfile(package, part)
        if signing.sha256_of(part) != signing.sha256_of(package):
            raise OSError("the update's package was not copied whole into %s" % packages_dir())
        os.replace(part, target)
    except OSError:
        # The copy never stays behind: under its own name the package is whole and checked, or it is not there.
        _remove(part)
        raise
    return target


def _refresh_updater(package):
    """Velopack's updater as the checked package carries it (lib/app/Squirrel.exe), over the installed Update.exe, as
    Velopack's own download does, but only from a package that checked out. Written beside Update.exe first and renamed
    over it, so that Update.exe is whole at every moment; a failure leaves the installed one (it puts the package in as
    well) and is logged."""
    target = updater()
    if target is None:
        return
    part = target + PART
    try:
        with zipfile.ZipFile(package) as archive:
            carried = [i.filename for i in archive.infolist() if i.filename.endswith(UPDATER_ENTRY)]
            if carried != [APP_PREFIX + UPDATER_ENTRY]:
                # A package with no updater of its own, or two: left as it is.
                return
            with archive.open(APP_PREFIX + UPDATER_ENTRY) as f, open(part, "wb") as out:
                shutil.copyfileobj(f, out, 1 << 20)
        os.replace(part, target)
    except (OSError, zipfile.BadZipFile, ValueError, EOFError) as e:
        log.warning("Update.exe stays as installed: %s", e)
        _remove(part)


def apply(result, tell=None, run=subprocess.run):
    """Fetch the update, check it, and hand it to Velopack, which puts it in once this program has ended and then
    starts the new launcher. The caller ends the program right after. tell("whole") is called when the whole package
    is fetched after the delta package did not give the one signed; `run` starts Update.exe (a test gives its own).

    Nothing of the download is in the install folder before it is checked (the module's description has the steps).
    Velopack applies it silently: the launcher's own dialog has said what happens, and Velopack's would be a plain
    system window with a progress bar.
    """
    import velopack
    # Before anything is fetched or deleted: the names, the sizes, a newer version, the delta's starting point.
    full, delta, base = offered(result)
    _leftovers(full["FileName"])
    folder = _own_folder()
    try:
        package = _checked(result, full, delta, base, folder, tell, run)
        target = _hand_in(package, full["FileName"])
    finally:
        # Whatever was fetched and not handed in goes with the folder, checked or not.
        shutil.rmtree(folder, ignore_errors=True)
    _refresh_updater(target)
    # A note for the next start: Velopack says nothing when a silent update fails, so the new start compares.
    _note_pending(result.version)
    # Velopack puts in the package of this name from packages\ (UpdateManager.wait_exit_then_apply_updates reads the
    # name alone and starts Update.exe apply with it).
    asset = velopack.VelopackAsset(installed.PACKAGE_ID, result.version, "Full", full["FileName"], "",
                                   str(full.get("SHA256") or ""), int(full["Size"]), "", "")
    velopack.UpdateManager(UPDATE_SOURCE or ".").wait_exit_then_apply_updates(asset, silent=True, restart=True)


PENDING = "update-pending.json"


def _note_pending(version):
    from opendmtq_client import __version__
    from opendmtq_client import state as st
    os.makedirs(st.config_dir(), exist_ok=True)
    with open(os.path.join(st.config_dir(), PENDING), "w", encoding="utf-8") as f:
        json.dump({"to": version, "from": current_version() or __version__}, f)


def drop_older(keep_version):
    """The packages of other versions in packages\\ go, once the new version runs (Velopack's own download removes them
    before it puts the new one in; here the installed one stays until the new one is in): Repair takes the installed
    version's package, and nothing else is read from there."""
    try:
        folder = packages_dir()
        names = os.listdir(folder)
    except (OSError, UpdateError):
        return
    keep = ("%s-%s-full.nupkg" % (installed.PACKAGE_ID, keep_version)).lower()
    for name in names:
        if name.lower().endswith((".nupkg", ".partial", PART)) and name.lower() != keep:
            _remove(os.path.join(folder, name))


def outcome():
    """After an update was handed to Velopack: ("updated", version) or ("not_updated", version, this version),
    once; None when no update was waiting. After an update that went in, the packages of earlier versions go."""
    from opendmtq_client import __version__
    from opendmtq_client import state as st
    path = os.path.join(st.config_dir(), PENDING)
    try:
        # utf-8-sig: as saved again by Notepad, with a byte-order mark.
        with open(path, encoding="utf-8-sig") as f:
            note = json.load(f)
    except (OSError, ValueError):
        return None
    try:
        os.remove(path)
    except OSError:
        pass
    now = current_version() or __version__
    target = str(note.get("to", ""))
    if target and now == target:
        drop_older(target)
        return ("updated", target)
    return ("not_updated", target, now)
