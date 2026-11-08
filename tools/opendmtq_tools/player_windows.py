"""The player for Windows that the site hands to players: the player (opendmtq-player-windows.zip, which
arm32/bundle_windows.sh makes and a release ships beside this code), with the app this server built and player.conf,
which names that app.

The builder keeps it in step with the app: one zip beside the APK in data/apk/out, named after it
(OpenDMTQ-<address>-v<date>-windows.zip), made again when the app or the player changes, older ones removed. What it
holds is in windows.json there, for the portal (server/portal/lib.php) and the admin pages.

The player comes from the first of: the copy beside this code (a release's tools image and the Windows bundle have one);
one in data/apk (put there by hand or by a host install's kit, for a server without internet, or fetched there before);
the project's latest release, fetched into data/apk when there is none, as the runtime for newer phones is (runtime.py).
A copy in data/apk a week old gives way to the latest release's, and stays when that cannot be had. A fetch that fails
is not tried again for a day: a server without internet would wait for it at every start. Without any copy, there is
no zip, and the site offers none.
"""

import datetime
import hashlib
import json
import os
import shutil
import time
import urllib.request
import zipfile
import zlib

from . import runtime

HERE = os.path.dirname(os.path.abspath(__file__))
# The player as a release ships it, and the version it carries (its bundle.json).
ZIP_NAME = "opendmtq-player-windows.zip"
# The one folder the player's zip holds, which players unpack where they like.
FOLDER = "OpenDMTQ-Player"
# What the zip beside the APK holds, for the portal and the admin pages.
MANIFEST = "windows.json"
# The zips' own ending, which tells them from the APKs in the same folder.
SUFFIX = "-windows.zip"
# The latest release's player, for a server that has none.
RELEASE_URL = "https://github.com/kanggu12/openDMTQ/releases/latest/download/" + ZIP_NAME
# In data/apk: why the last fetch failed. The file's own time says when, and so when the next one may be tried.
FAILED = "player-windows-error.txt"
# How long a failed fetch keeps the next one off: each try waits for an answer (runtime.TIMEOUT) on a network with no way out.
RETRY_AFTER = 24 * 60 * 60
# How old a copy in data/apk gets before the latest release's is fetched in its place: a copy fetched once would otherwise
# never change, whatever later releases bring. It stays as it is when the fetch fails (and the next try is a day later).
REFRESH_AFTER = 7 * 24 * 60 * 60
# What a damaged zip can raise as it is read: the zip's own error, and the decompressor's for what it cannot read (zlib's
# for a damaged stream, EOFError for one cut short), as runtime.py reads its zip. KeyError and TypeError: no version in it.
DAMAGED = (OSError, KeyError, TypeError, ValueError, AttributeError, EOFError, RuntimeError, zipfile.BadZipFile, zlib.error)


def bundled(path=None):
    """The player zip and its version, or (None, None) when there is none or it is damaged."""
    path = path or os.path.join(HERE, ZIP_NAME)
    if not os.path.isfile(path):
        return None, None
    try:
        with zipfile.ZipFile(path) as z:
            # A zip whose files do not match their checksums is no player to hand out.
            if z.testzip() is not None:
                return None, None
            return path, json.loads(z.read("bundle.json"))["version"]
    # A damaged file does not always look like a bad zip: testzip() passes the decompressor's own errors on.
    except DAMAGED:
        return None, None


def remove(path):
    """A file gone, when it is there; one that cannot be removed stays, as nothing here depends on its going."""
    try:
        os.remove(path)
    # Already gone, or held (a scanner on Windows): the next run tries again.
    except OSError:
        pass


def fetch(url, path):
    """The latest release's player to `path`, through a file beside it that takes its name once whole and checked: a copy
    already there stays when the download fails or brings a damaged one."""
    print(f"builder: fetching the player for Windows from {url}", flush=True)
    part = path + ".part"
    try:
        with urllib.request.urlopen(url, timeout=runtime.TIMEOUT) as r, open(part, "wb") as out:
            shutil.copyfileobj(r, out)
        # Read whole before it replaces anything: a file damaged on its way is no player.
        if bundled(part)[0] is None:
            raise ValueError(f"{ZIP_NAME} from {url} is damaged")
        os.replace(part, path)
    finally:
        # What a cut-off or damaged download left (a stop of the builder too: SystemExit passes through here).
        remove(part)


def fresh(path, limit):
    """True when the file was written less than `limit` seconds ago. A time in the future (a clock that was wrong) is not
    fresh: it would hold the next fetch off for as long as the clock was wrong."""
    try:
        age = time.time() - os.path.getmtime(path)
    # No such file: nothing fresh.
    except OSError:
        return False
    return 0 <= age < limit


def find(apk_dir):
    """The player to make the site's zip with, and its version: the copy beside this code, else the one in `apk_dir`
    (data/apk), else the latest release's, fetched there. A copy in `apk_dir` a week old gives way to the latest release's
    when that can be had, and after a fetch that failed none is tried for a day. (None, None) when there is none to be
    had."""
    path, version = bundled()
    if path:
        return path, version
    placed = os.path.join(apk_dir, ZIP_NAME)
    # What a fetch cut off at its worst left behind (a container killed before it could tidy up): the size of the player.
    remove(placed + ".part")
    path, version = bundled(placed)
    # Damaged (a copy cut short, a disk that failed): out of the way, so that a whole one can take its place.
    if not path and os.path.exists(placed):
        print(f"builder: {ZIP_NAME} in data/apk is damaged; it is removed", flush=True)
        remove(placed)
    # A copy recent enough: no need to ask the release for a newer one.
    if path and fresh(placed, REFRESH_AFTER):
        return path, version
    # A fetch failed lately: the network is likely still without a way out, and each try waits for an answer.
    failed = os.path.join(apk_dir, FAILED)
    if fresh(failed, RETRY_AFTER):
        if not path:
            print("builder: no player for Windows (the last fetch failed less than a day ago)", flush=True)
        return path, version
    try:
        fetch(RELEASE_URL, placed)
    except Exception as e:  # noqa: BLE001 - no internet, no release with one, a damaged download: what there was stays
        print(f"builder: could not fetch the player for Windows ({e}); the next try is in a day", flush=True)
        try:
            # Why, for whoever looks; the file's time keeps the next try off for a day.
            with open(failed, "w", encoding="utf-8") as f:
                f.write(f"{e}\n")
        # A folder this run cannot write to: it said why above, and tries again at the next start.
        except OSError:
            pass
        return path, version
    # It worked: what went wrong the last time is no longer so.
    remove(failed)
    return bundled(placed)


def name_for(apk_file):
    """The zip's file name: the APK's, which says the server's address and the day it was built."""
    stem = apk_file[:-4] if apk_file.endswith(".apk") else apk_file
    return stem + SUFFIX


def current(out_dir):
    """windows.json, when it is there and readable."""
    try:
        with open(os.path.join(out_dir, MANIFEST), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def matches(made, manifest):
    """True when windows.json (`made`) describes a zip made from the app latest.json (`manifest`) offers: the same file and
    the same contents. A build again on the same day for the same address has the same file name, and another app in it.
    `manifest` may be a build as the App page lists it (admin/apps.py), which has the same two fields. A hash missing on
    either side counts as empty, as the portal reads it (server/portal/lib.php)."""
    if not isinstance(made, dict) or not isinstance(manifest, dict):
        return False
    return made.get("apk") == manifest.get("file") and (made.get("apk_sha256") or "") == (manifest.get("sha256") or "")


def player_conf(manifest):
    """player.conf: the app's name (its label on phones), its package and its APK's file name, which the player reads
    (arm32/desktop/own_folder.cpp)."""
    name = manifest.get("label") or "OpenDMTQ"
    return ("# The app this player runs, as this OpenDMTQ server built it.\n"
            f"name={name}\npackage={manifest['package']}\napk={manifest['file']}\n")


def sha256(path):
    """A file's SHA-256, read a megabyte at a time."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def clear_parts(out_dir):
    """What a run cut off left in data/apk/out (the builder killed, the PC turned off): a zip half made, as big as the app or
    bigger, and windows.json half written. Each would stay for good: no later run writes under the same name unless the app
    is the same."""
    try:
        names = os.listdir(out_dir)
    # No folder yet: nothing left in it.
    except OSError:
        return
    for name in names:
        if name.endswith(SUFFIX + ".part") or name == MANIFEST + ".part":
            remove(os.path.join(out_dir, name))


def keep(out_dir, manifest, player=None):
    """Makes the zip for the app latest.json (`manifest`) describes, unless the one there is for this app and this
    player, and removes older ones. Returns the zip's file name, or None when there is no player to make it with or
    no app. `player`: a player zip to use rather than the one find() gives."""
    # First what an earlier run left half made: this run may stop before it gets to its own.
    clear_parts(out_dir)
    # No app, or one without what player.conf needs: nothing to make, and nothing to fetch for.
    if not manifest or not manifest.get("file") or not manifest.get("package"):
        return None
    apk = os.path.join(out_dir, os.path.basename(manifest["file"]))
    if not os.path.isfile(apk):
        return None
    path, version = bundled(player) if player else find(os.path.dirname(os.path.abspath(out_dir)))
    if not path:
        return None
    name = name_for(os.path.basename(manifest["file"]))
    target = os.path.join(out_dir, name)
    have = current(out_dir)
    # Up to date: made from this app (its name and its hash) with this player, and still there.
    if have and have.get("file") == name and matches(have, manifest) and have.get("player") == version and os.path.isfile(target):
        return name
    part = target + ".part"
    details_part = os.path.join(out_dir, MANIFEST + ".part")
    try:
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as dst:
            for info in src.infolist():
                # The version is for the builder to read: the player has no use for it.
                if info.filename == "bundle.json":
                    continue
                dst.writestr(info, src.read(info))
            conf = zipfile.ZipInfo(f"{FOLDER}/player.conf", datetime.datetime.now().timetuple()[:6])
            conf.compress_type = zipfile.ZIP_DEFLATED
            conf.external_attr = 0o644 << 16
            dst.writestr(conf, player_conf(manifest))
            # An APK is compressed already: it goes in as it is, which takes no time.
            dst.write(apk, f"{FOLDER}/{os.path.basename(manifest['file'])}", compress_type=zipfile.ZIP_STORED)
        os.replace(part, target)
        details = {"file": name, "size": os.path.getsize(target), "sha256": sha256(target), "apk": manifest["file"],
                   "apk_sha256": manifest.get("sha256"), "player": version,
                   "built_at": datetime.datetime.now().replace(microsecond=0).isoformat()}
        with open(details_part, "w", encoding="utf-8") as f:
            json.dump(details, f, indent=2)
        os.replace(details_part, os.path.join(out_dir, MANIFEST))
    finally:
        # Whatever stopped it (a full disk, the builder stopped): nothing half made stays. A zip moved in place whose
        # windows.json could not follow is made again by the next run: windows.json names the earlier app or player, or
        # there is none.
        for left in (part, details_part):
            remove(left)
    # Only the zip for the app on offer stays: each is the size of the app.
    for other in os.listdir(out_dir):
        if other.endswith(SUFFIX) and other != name:
            remove(os.path.join(out_dir, other))
    return name
