"""The PC client for Windows that the site hands to players: OpenDMTQ-Setup.exe, the installer of the launcher and the
player (client/packaging/windows/build.sh makes it, and a release ships it beside this code). The same file serves every
server: as it is handed out, this server's address goes on its end (preset()), which the installer reads from its own
file to set the launcher up for this server. Players then sign in from the launcher, which downloads the app.

The installer comes from the first of: the copy beside this code (a release's tools image and the Windows bundle have
one); one in data/apk (put there by hand or by a host install's kit, for a server without internet, or fetched there
before); the project's latest release, fetched into data/apk when there is none, as the runtime for newer phones is
(runtime.py). A copy in data/apk a week old gives way to the latest release's, and stays when that cannot be had. A
fetch that fails is not tried again for a day: a server without internet would wait for it at every start. Without any
copy, the site offers none.

The builder copies it into data/apk/out, where the portal reads it, and describes it in windows.json there (keep()).
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import struct
import time
import urllib.request

from . import runtime

HERE = os.path.dirname(os.path.abspath(__file__))
# The installer as a release ships it, and the file beside it that says its version.
SETUP_NAME = "OpenDMTQ-Setup.exe"
VERSION_NAME = SETUP_NAME + ".version"
# What data/apk/out holds for the portal and the admin pages: the installer, and what it is.
MANIFEST = "windows.json"
# The latest release's installer, for a server that has none.
RELEASE_URL = "https://github.com/kanggu12/openDMTQ/releases/latest/download/" + SETUP_NAME
# In data/apk: why the last fetch failed. The file's own time says when, and so when the next one may be tried.
FAILED = "client-windows-error.txt"
# How long a failed fetch keeps the next one off: each try waits for an answer (runtime.TIMEOUT) on a network with no way out.
RETRY_AFTER = 24 * 60 * 60
# How old a copy in data/apk gets before the latest release's is fetched in its place: a copy fetched once would otherwise
# never change, whatever later releases bring. It stays as it is when the fetch fails (and the next try is a day later).
REFRESH_AFTER = 7 * 24 * 60 * 60
# The installer's end as handed out: the server's details (JSON), their length (4 bytes, little-endian), and this mark,
# which the installer looks for in its file's last bytes (client/opendmtq_client reads it the same way).
MAGIC = b"OPENDMTQ-PRESET1"
PRESET_FORMAT = 1
# What 0.6 and 0.7 kept in data/apk for their player for Windows: the player without an app (fetched from a release or
# put there by hand), a fetch of it cut off, and why the last fetch failed. Of no use since the installer: they go.
OLD_IN_APK = ("opendmtq-player-windows.zip", "opendmtq-player-windows.zip.part", "player-windows-error.txt")
# The largest certificate authority's file taken as one (own_ca()): a certificate is two kilobytes or so.
CA_LIMIT = 16 * 1024
# The smallest file that can be the installer: a damaged or cut-off download is far below it.
SMALLEST = 1 << 20


def remove(path):
    """A file gone, when it is there; one that cannot be removed stays, as nothing here depends on its going."""
    try:
        os.remove(path)
    # Already gone, or held (a scanner on Windows): the next run tries again.
    except OSError:
        pass


def whole(path):
    """True when the file looks like the installer as a release ships it: a Windows program (its first bytes MZ) of a
    believable size, with no server's details on its end yet (those are added as it is handed out)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(2)
            f.seek(max(0, size - len(MAGIC)))
            end = f.read(len(MAGIC))
    # No such file, or one this run cannot read.
    except OSError:
        return False
    return head == b"MZ" and size >= SMALLEST and end != MAGIC


def version_beside(path):
    """The version written beside an installer (its .version file), or "" when none says."""
    try:
        with open(path + ".version", encoding="utf-8") as f:
            return f.read().strip()
    # None written: a copy put there by hand.
    except OSError:
        return ""


def bundled(path=None):
    """The installer beside this code and its version, or (None, None) when there is none or it is damaged."""
    path = path or os.path.join(HERE, SETUP_NAME)
    if not whole(path):
        return None, None
    return path, version_beside(path)


def release_version(url):
    """The version a release download's final address names (GitHub sends /releases/latest/download/... on to
    /releases/download/v1.2.3/...), or ""."""
    m = re.search(r"/releases/download/v?([0-9][0-9A-Za-z.+-]*)/", url)
    return m.group(1) if m else ""


def fetch(url, path):
    """The latest release's installer to `path`, through a file beside it that takes its name once whole and checked, with
    its version beside it: a copy already there stays when the download fails or brings a damaged one."""
    print(f"builder: fetching the installer for Windows from {url}", flush=True)
    part = path + ".part"
    try:
        with urllib.request.urlopen(url, timeout=runtime.TIMEOUT) as r, open(part, "wb") as out:
            shutil.copyfileobj(r, out)
            # Where the redirects ended: the release's own address, which names its version.
            version = release_version(r.geturl())
        # Read whole before it replaces anything: a file damaged on its way is no installer.
        if not whole(part):
            raise ValueError(f"{SETUP_NAME} from {url} is damaged")
        os.replace(part, path)
        with open(path + ".version", "w", encoding="utf-8") as f:
            f.write(version + "\n")
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
    """The installer to hand out, and its version: the copy beside this code, else the one in `apk_dir` (data/apk), else
    the latest release's, fetched there. A copy in `apk_dir` a week old gives way to the latest release's when that can
    be had, and after a fetch that failed none is tried for a day. (None, None) when there is none to be had."""
    path, version = bundled()
    if path:
        return path, version
    placed = os.path.join(apk_dir, SETUP_NAME)
    # What a fetch cut off at its worst left behind (a container killed before it could tidy up): the installer's size.
    remove(placed + ".part")
    path, version = bundled(placed)
    # Damaged (a copy cut short, a disk that failed): out of the way, so that a whole one can take its place.
    if not path and os.path.exists(placed):
        print(f"builder: {SETUP_NAME} in data/apk is damaged; it is removed", flush=True)
        remove(placed)
    # A copy recent enough: no need to ask the release for a newer one.
    if path and fresh(placed, REFRESH_AFTER):
        return path, version
    # A fetch failed lately: the network is likely still without a way out, and each try waits for an answer.
    failed = os.path.join(apk_dir, FAILED)
    if fresh(failed, RETRY_AFTER):
        if not path:
            print("builder: no installer for Windows (the last fetch failed less than a day ago)", flush=True)
        return path, version
    try:
        fetch(RELEASE_URL, placed)
    except Exception as e:  # noqa: BLE001 - no internet, no release with one, a damaged download: what there was stays
        print(f"builder: could not fetch the installer for Windows ({e}); the next try is in a day", flush=True)
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


def current(out_dir):
    """windows.json, when it is there and readable."""
    try:
        with open(os.path.join(out_dir, MANIFEST), encoding="utf-8") as f:
            made = json.load(f)
    except (OSError, ValueError):
        return None
    return made if isinstance(made, dict) else None


def offered(out_dir):
    """What the site hands out (windows.json), when its installer is there at the size it says; else None."""
    made = current(out_dir)
    if not made:
        return None
    path = os.path.join(out_dir, os.path.basename(str(made.get("file", ""))))
    try:
        return made if os.path.getsize(path) == made.get("size") else None
    # Gone (removed by hand, a disk replaced): nothing to offer.
    except OSError:
        return None


def sha256(path):
    """A file's SHA-256, read a megabyte at a time."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def clear_parts(out_dir):
    """What a run cut off left in data/apk/out (the builder killed, the PC turned off): an installer half copied, and
    windows.json half written. Each would stay for good: no later run writes under the same name."""
    for name in (SETUP_NAME + ".part", MANIFEST + ".part"):
        remove(os.path.join(out_dir, name))


def keep(out_dir, installer=None):
    """Puts the installer in `out_dir` (data/apk/out) for the portal, with windows.json, unless the one there is the same
    file; older players for Windows (the zips of 0.6 and 0.7, each the size of the app, and what those versions kept in
    data/apk for them) go. Returns the installer's file name, or None when there is none to be had. `installer`: an
    installer to use rather than the one find() gives."""
    # First what an earlier run left half made: this run may stop before it gets to its own.
    clear_parts(out_dir)
    # The players for Windows that came with the app in them, from before the installer, and one of them half made: gone.
    for old in (os.listdir(out_dir) if os.path.isdir(out_dir) else []):
        if old.endswith(("-windows.zip", "-windows.zip.part")):
            remove(os.path.join(out_dir, old))
    # And what those versions kept in data/apk for them.
    for old in OLD_IN_APK:
        remove(os.path.join(os.path.dirname(os.path.abspath(out_dir)), old))
    path, version = bundled(installer) if installer else find(os.path.dirname(os.path.abspath(out_dir)))
    if not path:
        return None
    target = os.path.join(out_dir, SETUP_NAME)
    digest = sha256(path)
    have = current(out_dir)
    # Up to date: this file, at this version, and still there whole.
    if have and have.get("file") == SETUP_NAME and have.get("sha256") == digest and have.get("version") == version and offered(out_dir):
        return SETUP_NAME
    part = target + ".part"
    details_part = os.path.join(out_dir, MANIFEST + ".part")
    try:
        os.makedirs(out_dir, exist_ok=True)
        shutil.copyfile(path, part)
        os.replace(part, target)
        details = {"file": SETUP_NAME, "size": os.path.getsize(target), "sha256": digest, "version": version,
                   "copied_at": datetime.datetime.now().replace(microsecond=0).isoformat()}
        with open(details_part, "w", encoding="utf-8") as f:
            json.dump(details, f, indent=2)
        os.replace(details_part, os.path.join(out_dir, MANIFEST))
    finally:
        # Whatever stopped it (a full disk, the builder stopped): nothing half made stays.
        for left in (part, details_part):
            remove(left)
    return SETUP_NAME


def site_url(https, host):
    """The address players reach the site by, as the installer and the launcher keep it (site_url_for() in
    server/portal/lib.php makes the same): the scheme and the server's public address. An address without a port is on
    port 80 (server/entrypoint.sh), and HTTPS answers on that same port: over HTTPS the port is named, or the address
    would mean 443, where nothing answers."""
    if https and not re.search(r":\d+$", host):
        host += ":80"
    return ("https" if https else "http") + "://" + host


def own_ca(folder=None):
    """The server's own certificate authority as PEM text, which signs the certificate its HTTPS answers with (made by
    tls.py, offered at /ca.crt): the launcher trusts it for this server alone. "" without one (no HTTPS, or HTTPS from a
    router with a certificate of its own). The folder is where the site reads it too (OPENDMTQ_HTTPS, else /srv/https)."""
    path = os.path.join(folder or os.environ.get("OPENDMTQ_HTTPS") or "/srv/https", "ca.crt")
    try:
        with open(path, "rb") as f:
            # A certificate is two kilobytes or so: anything far larger is no certificate.
            data = f.read(CA_LIMIT + 1)
    except OSError:
        return ""
    text = data.decode("ascii", "replace").strip()
    # Only a certificate, whole (an empty or half-written file is none).
    if len(data) > CA_LIMIT or not text.startswith("-----BEGIN CERTIFICATE-----") or not text.endswith("-----END CERTIFICATE-----"):
        return ""
    return text


def preset(url, name, ca=""):
    """The end that goes on the installer as this server hands it out: the server's address as players reach its site
    (`url`, scheme and host with its port), its name and, for an address over HTTPS, its own certificate authority (`ca`,
    PEM text, left out when ""), read back by the installer (client/opendmtq_client)."""
    details = {"version": PRESET_FORMAT, "url": url, "name": name}
    if ca:
        details["ca"] = ca
    data = json.dumps(details, ensure_ascii=False, separators=(",", ":")).encode()
    return data + struct.pack("<I", len(data)) + MAGIC


def download_name(host):
    """The file name the installer is handed out under: the server's address in it, as the app's own name has it
    (OpenDMTQ-Setup-example.com-8080.exe)."""
    return "OpenDMTQ-Setup-" + re.sub(r"[^A-Za-z0-9.-]", "-", host) + ".exe"
