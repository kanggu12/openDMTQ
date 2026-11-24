"""The PC client's updates this server hands out to the launchers that play on it, at /updates/ on its one port
(server/portal/updates.php): the PC client's update feed (releases.win.json), its full package, its delta package from
the release before, and the release's checksums with their signature (signing.py). They are of the version of the
installer the site hands out (windows_client.py: the server's own release, in a release's images, in the Windows bundle
and wherever that release can be had), so that a launcher stays matched to its server: it takes its updates from here
before it looks at the project's releases, and goes no further than the version this server hands out
(client/opendmtq_client/updates.py).

The files come from the first of:

  * beside this code (pc-client-updates/): a release's tools image brings the ones of its release;
  * data/apk/pc-client-updates: put there by hand or by a host install's kit, for a server without internet (the
    Windows bundle cannot bring them: the release's checksums name the bundle's own hash);
  * the release of the installer's version, fetched when none of these has them.

Wherever they come from, they are checked before the site hands any out: the checksums signed by the project, the feed
and the packages the very files they sum. What does not check out is refused, said on the App page in its words
(strings.py release.unsigned_file), and the files handed out before stay. A fetch that fails is not tried again for a
day: a server without internet would wait for an answer at every start.

data/apk/out/updates holds the files the site hands out, data/apk/out/updates.json what they are (kept()).
"""

import datetime
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request

from . import runtime, signing, windows_client

HERE = os.path.dirname(os.path.abspath(__file__))
# The folder of the files the site hands out, beside the app and the installer in data/apk/out, and what they are.
FOLDER = "updates"
MANIFEST = "updates.json"
# The folder of a release's update files beside this code and in data/apk.
KIT = "pc-client-updates"
# The release's files by the names .github/release_assets.py gives them: the feed under Velopack's name, the packages.
FEED = "releases.win.json"
PACKAGE = "opendmtq.client-{version}-full.nupkg"
DELTA = "opendmtq.client-{version}-delta.nupkg"
PACKAGE_ID = "OpenDMTQ.Client"
# In data/apk: why the last try did not give the files. The file's own time says when, and so when the next one may be.
FAILED = "client-updates-error.txt"
RETRY_AFTER = windows_client.RETRY_AFTER
# The most bytes a feed may hold, and a package: a release's are a few hundred bytes and some 40 MB.
FEED_LIMIT, PACKAGE_LIMIT = 256 << 10, 512 << 20


def log(message):
    """One line of progress, at once, in the builder's output."""
    print(message, flush=True)


def _entries(feed, version):
    """(the full package's entry, the delta package's entry or None, the version the delta starts from or None) of the
    release `version` in its feed; signing.Unsigned for a feed that names its packages otherwise than a release does."""
    assets = feed.get("Assets") if isinstance(feed, dict) else None
    assets = [a for a in assets if isinstance(a, dict)] if isinstance(assets, list) else []
    full = delta = None
    for asset in assets:
        if asset.get("Version") != version or asset.get("PackageId") != PACKAGE_ID:
            continue
        kind, name = asset.get("Type"), asset.get("FileName")
        want = {"Full": PACKAGE, "Delta": DELTA}.get(kind, "").format(version=version)
        if name != want or not isinstance(asset.get("Size"), int) or not 0 < asset["Size"] <= PACKAGE_LIMIT:
            raise signing.Unsigned(f"{FEED} names {name!r} as a package of {version}, which no release does")
        if kind == "Full":
            full = asset
        else:
            delta = asset
    if full is None:
        raise signing.Unsigned(f"{FEED} has no package of the PC client {version}")
    # The delta starts from the newest full package before this one that the feed lists (vpk lists the one it used).
    before = [str(a.get("Version")) for a in assets if a.get("Type") == "Full" and a.get("PackageId") == PACKAGE_ID
              and re.fullmatch(r"\d+\.\d+\.\d+", str(a.get("Version") or ""))
              and runtime.numbers_in("-" + str(a.get("Version"))) < runtime.numbers_in("-" + version)]
    start = max(before, key=lambda v: runtime.numbers_in("-" + v)) if before and delta else None
    return full, delta if start else None, start


def verify(folder, version):
    """What the release `version`'s update files in `folder` are, once each checks out: {"version", "files": {name:
    {"size", "sha256"}}, "full", "delta", "delta_from", "signed_by"}. signing.Unsigned, with why, for anything that does
    not (no signed checksums, a feed or a package that is not the file they sum)."""
    sums = runtime.sums_beside(folder, version)
    if sums is None:
        # The checksums without their signature (or neither): nothing says the project made these files.
        raise signing.Unsigned(f"{signing.sums_name(version)} is not signed by the OpenDMTQ project")
    feed_path = os.path.join(folder, FEED)
    signing.check_file(sums, FEED, feed_path)
    with open(feed_path, "rb") as f:
        try:
            feed = json.loads(f.read(FEED_LIMIT + 1).decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            raise signing.Unsigned(f"{FEED} is no update feed") from None
    full, delta, start = _entries(feed, version)
    sums_file = signing.sums_name(version)
    names = [FEED, sums_file, sums_file + signing.SIG_SUFFIX, full["FileName"]] + ([delta["FileName"]] if delta else [])
    for name in names[3:]:
        signing.check_file(sums, name, os.path.join(folder, name))
    with open(os.path.join(folder, sums_file), "rb") as f, open(os.path.join(folder, sums_file + signing.SIG_SUFFIX),
                                                                   "rb") as g:
        signer = signing.signed_by(f.read(), g.read())
    files = {}
    for name in names:
        path = os.path.join(folder, name)
        files[name] = {"size": os.path.getsize(path), "sha256": signing.sha256_of(path)}
    return {"version": version, "files": files, "full": full["FileName"], "delta": delta["FileName"] if delta else None,
            "delta_from": start, "signed_by": signer}


def kept(out_dir):
    """What the site hands out (updates.json), when every file it names is there at its size; else None."""
    try:
        with open(os.path.join(out_dir, MANIFEST), encoding="utf-8") as f:
            made = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(made, dict) or not isinstance(made.get("files"), dict):
        return None
    for name, about in made["files"].items():
        try:
            if os.path.getsize(os.path.join(out_dir, FOLDER, os.path.basename(name))) != about.get("size"):
                return None
        # One gone (a disk replaced, removed by hand): nothing to hand out.
        except (OSError, AttributeError):
            return None
    return made


def _fetch(version, folder, releases):
    """The release `version`'s update files fetched into `folder`: its checksums and signature first (nothing else of a
    release without them), then the feed, then the packages it names."""
    sums_file = signing.sums_name(version)
    for name in (sums_file, sums_file + signing.SIG_SUFFIX, FEED):
        _download(runtime.release_url(name, version, releases), os.path.join(folder, name), FEED_LIMIT)
    # The checksums and the feed checked before a package is asked for.
    sums = runtime.sums_beside(folder, version)
    signing.check_file(sums, FEED, os.path.join(folder, FEED))
    with open(os.path.join(folder, FEED), "rb") as f:
        feed = json.loads(f.read().decode("utf-8-sig"))
    full, delta, _ = _entries(feed, version)
    for entry in [full] + ([delta] if delta else []):
        _download(runtime.release_url(entry["FileName"], version, releases), os.path.join(folder, entry["FileName"]),
                  entry["Size"])


def _download(url, path, limit):
    """One file to `path`, at most `limit` bytes and whole within runtime.FILE_SECONDS however it trickles in
    (runtime.pieces): a feed is never given the whole disk, nor the whole day."""
    log(f"builder: fetching {url}")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=runtime.TIMEOUT) as r, open(path, "wb") as out:
            done = 0
            for piece in runtime.pieces(r, started, runtime.FILE_SECONDS):
                done += len(piece)
                if done > limit:
                    raise OSError(f"{os.path.basename(path)} is larger than the release says")
                out.write(piece)
    except urllib.error.HTTPError as e:
        raise runtime.RuntimeError_(f"could not fetch {url}: {e}") from e


def _swap(out_dir, staged, about):
    """The checked files of `staged` in the place of the ones the site hands out, and updates.json describing them, each
    whole: the folder is renamed in, the manifest written beside it and renamed over the old one."""
    target = os.path.join(out_dir, FOLDER)
    aside = tempfile.mkdtemp(dir=out_dir, prefix=".updates-old-")
    try:
        if os.path.isdir(target):
            os.rename(target, os.path.join(aside, FOLDER))
        os.rename(staged, target)
        part = os.path.join(out_dir, MANIFEST + ".part")
        with open(part, "w", encoding="utf-8") as f:
            json.dump(about, f, indent=2)
        os.replace(part, os.path.join(out_dir, MANIFEST))
    finally:
        shutil.rmtree(aside, ignore_errors=True)


def _note(apk_dir, why):
    """Why the files could not be had, for the App page and the next try's wait (the file's time)."""
    try:
        with open(os.path.join(apk_dir, FAILED), "w", encoding="utf-8") as f:
            f.write(f"{why}\n")
    # A folder this run cannot write to: the builder's output says why all the same.
    except OSError:
        pass


def failure(apk_dir):
    """Why the last try did not give the files (FAILED), or ""."""
    try:
        with open(os.path.join(apk_dir, FAILED), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def keep(out_dir, version=None, releases=None):
    """The update files of the installer's version (windows.json's, or `version`) in data/apk/out/updates for the site,
    checked, from beside this code, data/apk/pc-client-updates, or the release; returns what they are (updates.json), or
    None when there are none to be had. Refused files never replace the ones handed out before."""
    apk_dir = os.path.dirname(os.path.abspath(out_dir))
    version = version or str((windows_client.current(out_dir) or {}).get("version") or "")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
        # No installer, or one put there by hand without its version: no release to hand out the updates of.
        return kept(out_dir)
    have = kept(out_dir)
    if have and have.get("version") == version:
        # Up to date: whatever went wrong before (a refused kit, a fetch that failed) is no longer so.
        _forget_failure(apk_dir)
        return have
    os.makedirs(out_dir, exist_ok=True)
    staged = tempfile.mkdtemp(dir=out_dir, prefix=".updates-new-")
    taken = None
    try:
        source = None
        for where, label in ((os.path.join(HERE, KIT), "beside the code"), (os.path.join(apk_dir, KIT), "data/apk")):
            if os.path.isfile(os.path.join(where, signing.sums_name(version))):
                source, taken = label, where
                for name in os.listdir(where):
                    # Copied: a refused copy stays where it was put, for whoever put it there to see.
                    if os.path.isfile(os.path.join(where, name)):
                        shutil.copyfile(os.path.join(where, name), os.path.join(staged, name))
                break
        if source is None:
            if windows_client.fresh(os.path.join(apk_dir, FAILED), RETRY_AFTER):
                # A try failed lately: the network is likely still without a way out.
                return have
            source = "the release"
            _fetch(version, staged, releases or runtime.RELEASES)
        about = verify(staged, version)
        # Only the files the release names: whatever else was beside them is no part of what the site hands out.
        for name in os.listdir(staged):
            if name not in about["files"]:
                os.remove(os.path.join(staged, name))
        about.update(source=source, kept_at=datetime.datetime.now().replace(microsecond=0).isoformat())
        # Readable by the site as the rest of data/apk/out is (mkdtemp makes a folder its owner's alone): a host install
        # or a cluster may run the site as another user than the builder.
        os.chmod(staged, 0o755)
        _swap(out_dir, staged, about)
    except Exception as e:  # noqa: BLE001 - refused, no internet, a full disk: what the site handed out stays
        why = str(e) if isinstance(e, (signing.Unsigned, runtime.RuntimeError_)) else f"{type(e).__name__}: {e}"
        log(f"builder: no updates for PC clients of {version} ({why})")
        _note(apk_dir, why)
        return have
    finally:
        shutil.rmtree(staged, ignore_errors=True)
    _forget_failure(apk_dir)
    if taken == os.path.join(apk_dir, KIT):
        # The copy put in data/apk is taken: it would only wait there to be taken again.
        shutil.rmtree(taken, ignore_errors=True)
    log(f"builder: updates for PC clients of {version}, from {source}")
    return about


def _forget_failure(apk_dir):
    """The note of a try that did not work goes: what it said is no longer so."""
    try:
        os.remove(os.path.join(apk_dir, FAILED))
    except OSError:
        pass
