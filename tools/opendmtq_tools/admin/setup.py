"""The setup pages (/opendmtq/admin/setup): a server's first steps in the browser, for an owner who has the game's APK
and its server files and nothing else. Four steps, each done once and checked again on every visit:

  files     the APK and the server files, found on this PC or chosen there, then imported
  address   the address phones use, this PC's own on the local network
  players   an account for each player (the site and the app download open to them only)
  app       the phone app, built for that address, with the QR code and what to do on the phone

On a host install and in the Windows bundle these pages run on the server PC itself, as its user: they look in its
Downloads and on its Desktop, let the owner pick any folder there, run the import, change the address and restart the
server (host/opendmtq_host starts them with OPENDMTQ_HOST_INSTALL=yes). In a container they see only their own
folders: the files and the address are then ./opendmtq import and ./opendmtq host, which the pages name.
"""

import ipaddress
import json
import os
import re
import secrets
import socket
import string
import subprocess
import threading
import time
import urllib.parse

from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for

from .. import importer, patch_apk, songs
from . import accounts, apps, auth, core, jobs
from .core import app, BASE, changed, same_text, t

# ------------------------------------------------------------------------------ where these pages run

# On the server PC itself (a host install, the Windows bundle): its folders can be looked at and imported from.
HOST_INSTALL = os.environ.get("OPENDMTQ_HOST_INSTALL") == "yes"
# In a Kubernetes pod (the cluster sets this in every container): the files and the address are the Helm chart's, not
# ./opendmtq's.
IN_KUBERNETES = bool(os.environ.get("KUBERNETES_SERVICE_HOST"))
# The settings (.env) and the run folder of a host install: the address is changed in the one, a restart asked for in
# the other, and the one-time sign-in that opens these pages the first time is a file there.
ENV_FILE = os.environ.get("OPENDMTQ_ENV_FILE", "")
RUN_DIR = os.environ.get("OPENDMTQ_RUN", "")
SIGNIN_FILE = os.path.join(RUN_DIR, "signin.token") if RUN_DIR else ""
# A one-time sign-in is good for this long after it was made.
SIGNIN_LIFE = 3600
# This process: a restart is over when a new one answers.
STARTED = f"{os.getpid()}-{int(time.time())}"
# The steps, in order, with the words for each.
STEPS = ("files", "address", "players", "app")

# The game's files as people keep them: the client (an APK, alone or in a bundle), the iPhone app often beside it (said
# to be of no use), and archives of the server files, whole or in parts (cli/opendmtq_cli/discover.py looks for them on
# the command line; importer.what_is says what each one is).
# Words the game's files are usually named with: an archive with one of them in its name is taken for the game's.
GAME_WORDS = ("dmtq", "djmax", "technika")
APK_SUFFIX = ".apk"
APP_SUFFIXES = (".apk",) + importer.APK_BUNDLES
IPA_SUFFIX = ".ipa"
ARCHIVE_SUFFIXES = (".rar", ".zip", ".7z")
# This project's own downloads start with its name: the apps it builds, its Windows bundle. They are none of the game's.
OWN = "opendmtq"
# Inside a folder of the game's files: the client's patch folder in the game host's folder (importer.host_folder has the
# other forms).
GAME_DIR = os.path.join("dmqglb.mb.pmang.com", "patch", "phone_new")
# What a file or folder is (importer.what_is), kept by its path, size and time: the lists ask for each again at every
# visit, and an archive's look takes 7-Zip a second. A folder's answer is kept this many seconds only.
WHAT_LIFE = 60
_what = {}
_what_lock = threading.Lock()
# The client in data/apk/base and what it is, kept while the folder and the last build stay as they were.
_base = {"key": None, "client": None}
# A folder listing shows at most this many entries (a Downloads folder can hold thousands).
MAX_LISTED = 400
# Windows file attributes of entries that are no place for the game's files: hidden ones and the system's own (the old
# names such as "Documents and Settings" and "Application Data" among them, which refuse to open).
HIDDEN_OR_SYSTEM = 0x2 | 0x4
# What the look through the usual places found, kept this many seconds: each click in the folder picker draws the page
# again, and the look reads every folder in the home.
SCAN_LIFE = 10
_scan = {"key": None, "at": 0.0, "found": []}
_scan_lock = threading.Lock()
# One job at a time from these pages: an import, a build, or an address change (which restarts the server, and would
# cut off whatever runs).
_busy_lock = threading.Lock()


# ------------------------------------------------------------------------------ the state of each step

def base_client():
    """The client the app is built from and what it is: {"name", "info"}; {"name": None, "unusable": [(name, info)]}
    when data/apk/base holds only APKs that are no client to build from; None when it holds none."""
    base = os.path.join(core.APK, "base")
    try:
        names = sorted(f for f in os.listdir(base) if f.lower().endswith(APK_SUFFIX))
        stats = [(f, os.stat(os.path.join(base, f)).st_size, os.stat(os.path.join(base, f)).st_mtime_ns) for f in names]
        last = os.stat(os.path.join(core.APK, "out", "latest.json")).st_mtime_ns if os.path.isfile(
            os.path.join(core.APK, "out", "latest.json")) else 0
    except OSError:
        return None
    if not names:
        return None
    key = (tuple(stats), last)
    if _base["key"] != key:
        infos = patch_apk.clients(base)
        best, _ = patch_apk.choose(base, infos)
        _base["client"] = ({"name": os.path.basename(best), "info": infos[best]} if best else
                           {"name": None, "unusable": [(os.path.basename(f), i) for f, i in infos.items()]})
        _base["key"] = key
    return _base["client"]


def has_base_apk():
    """True when data/apk/base holds a client to build the app from."""
    client = base_client()
    return bool(client and client["name"])


def app_ready():
    """True when the app on offer is for this server's address and its last build did not fail."""
    offer = next((b for b in apps.builds() if b["current"]), None)
    return bool(offer) and offer["host"] == core.PUBLIC_HOST and not apps.build_error()


def builder_running():
    """True while the app builder the server runs at its start is building for this address: data/apk/out/build.json
    says so, and for no longer than a build can take (after that it was cut off)."""
    try:
        with open(os.path.join(core.APK, "out", "build.json"), encoding="utf-8") as f:
            status = json.load(f)
        return (status.get("state") == "building" and status.get("host") == core.PUBLIC_HOST
                and time.time() - float(status.get("time") or 0) < apps.STALE_BUILD)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def runtime_in_place():
    """True when data/apk/arm32 holds the runtime the app builder adds for phones without 32-bit support."""
    return os.path.isfile(os.path.join(core.APK, "arm32", "bundle.json"))


def runtime_failure():
    """Why the last try to add the runtime did not work (data/apk/runtime-error.txt, which it writes), or nothing."""
    try:
        with open(os.path.join(core.APK, "runtime-error.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def steps_done():
    """Each step's state: {step: True when done}."""
    accounts, _ = auth.accounts_count()
    return {
        # The game's start files, all of them, and a client: songs are optional.
        "files": songs.has_game_data() and not songs.missing_game_files() and has_base_apk(),
        # The address is set as soon as the server runs; it is the owner's to check.
        "address": bool(core.PUBLIC_HOST),
        "players": bool(accounts),
        "app": app_ready(),
    }


def step_words():
    """Each step's name, in the page's language."""
    return {"files": t("setup.step_files"), "address": t("setup.step_address"), "players": t("setup.step_players"),
            "app": t("setup.step_app")}


def setup_complete():
    """True when every step is done (the status page asks the owner to finish otherwise)."""
    return all(steps_done().values())


# ------------------------------------------------------------------------------ the game's files on this PC

def is_game_folder(path):
    """True when path is a folder of the game's server files, in any of the forms the import takes."""
    return importer.is_game_folder(path)


def shown(entry):
    """False for a folder entry that is no place for the game's files: hidden ones, the system's own, and on Windows
    the links it keeps for old programs (which refuse to open)."""
    if entry.name.startswith((".", "$")):
        return False
    if os.name == "nt":
        try:
            # On Windows the listing already carries the attributes: no second look at the disk.
            st = entry.stat(follow_symlinks=False)
        except OSError:
            return False
        if getattr(st, "st_file_attributes", 0) & HIDDEN_OR_SYSTEM:
            return False
        # Junctions and links lead elsewhere, or nowhere this user may go. (OneDrive's folders are neither.)
        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
            return False
    return True


def printable(name):
    """True for a name the page can show: a Linux file system may hold any bytes, which Python keeps as surrogates that
    no page can carry."""
    try:
        name.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def entries(path):
    """The entries of a folder that are shown, in name order, or None when it cannot be read."""
    try:
        with os.scandir(path) as it:
            return sorted((e for e in it if printable(e.name) and shown(e)), key=lambda e: e.name.lower())
    except OSError:
        return None


def clean_path(text):
    """A path as people paste it, made one the system takes: spaces and quotes around it gone (Windows' Copy as path puts
    it in quotes), a file:// address made a path, %USERPROFILE% or ~ worked out, a drive letter alone made its top folder,
    and a path from no drive's top or root taken from the home folder (Downloads/DMTQ). Empty when nothing is left."""
    # No system's paths hold a NUL, and the calls that read folders raise ValueError on one rather than OSError.
    text = (text or "").replace("\0", "").strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    if not text:
        return ""
    # A file's address, as a browser's address bar shows it: file:///C:/Users/..., file://nas/share/..., file:///home/...
    if text.lower().startswith("file:"):
        url = urllib.parse.urlparse(text)
        text = urllib.parse.unquote(url.path)
        if os.name == "nt":
            # The drive comes after the address's own slash; a host before the path is a network share.
            if re.match(r"/[A-Za-z]:", text):
                text = text[1:]
            elif url.netloc and url.netloc.lower() != "localhost":
                text = "//" + url.netloc + text
    text = os.path.expanduser(os.path.expandvars(text))
    if os.name == "nt" and len(text) == 2 and text[1] == ":":
        text += "\\"
    # Relative to the server program's own folder it would mean nothing to the person: their home is where they start.
    if not os.path.isabs(text):
        text = os.path.join(os.path.expanduser("~"), text)
    return os.path.normpath(text)


def too_wide(path):
    """True for a folder too big to look through for the game's files: a drive's top or the home folder itself (the
    import goes four folders down, and opens every archive on the way)."""
    here = os.path.normcase(os.path.normpath(path))
    home = os.path.normcase(os.path.normpath(os.path.expanduser("~")))
    return parent_of(path) is None or here == home or here == os.path.normcase(os.path.dirname(home))


def crumbs(path):
    """The way to a folder from the top of its drive, each step with its own path: [(name, path)]."""
    out = []
    here = os.path.normpath(path)
    while True:
        up = parent_of(here)
        out.append((os.path.basename(here) or here, here))
        if up is None:
            break
        here = up
    return list(reversed(out))


def default_folder():
    """Where the folder picker opens when nothing was asked for: Downloads, where most people's files are, else home."""
    homes = home_folders()
    return next((p for p in homes if os.path.basename(p).lower() == "downloads"), homes[0] if homes else os.path.expanduser("~"))


def is_dir(entry):
    """True for a folder; False also when the entry went away or cannot be looked at."""
    try:
        return entry.is_dir()
    except OSError:
        return False


def is_file(entry):
    """True for a file; False also when the entry went away or cannot be looked at."""
    try:
        return entry.is_file()
    except OSError:
        return False


def game_folder_in(path, listed=None):
    """The folder of the game's server files in path itself or up to two levels down (an archive unpacked into a folder
    of its own, with one more around the game's: a web server's htdocs, say), or None. listed: path's entries when the
    caller has them already."""
    if is_game_folder(path):
        return path
    subs = [e.path for e in (listed if listed is not None else entries(path) or []) if is_dir(e)]
    for sub in subs:
        if is_game_folder(sub):
            return sub
    for sub in subs:
        for e in entries(sub) or []:
            if is_dir(e) and is_game_folder(e.path):
                return e.path
    return None


def look_in(folder, listed=None):
    """What a folder holds of the game's files: {path, apks, archives, tree}, or None when nothing. listed: the
    folder's entries when the caller has them already."""
    if listed is None:
        listed = entries(folder)
    if listed is None:
        return None
    # Not this project's own downloads (its apps, OpenDMTQ-windows.zip), which are very likely in Downloads too.
    files = [e.name for e in listed if is_file(e) and not e.name.lower().startswith(OWN)]
    # Clients: an APK, or a bundle with one in it.
    apks = [n for n in files if n.lower().endswith(APP_SUFFIXES)]
    # Archives named like the game's, or any archive next to an APK: what else would it be. One in parts by its first.
    archives = [n for n in files if importer.archive_role(n) == "first" and not n.lower().endswith(importer.APK_BUNDLES)
                and (any(word in n.lower() for word in GAME_WORDS) or apks)]
    # The iPhone app, named like the game's or beside its files: listed, to be said to be of no use.
    iphone = [n for n in files if n.lower().endswith(IPA_SUFFIX) and (any(word in n.lower() for word in GAME_WORDS)
                                                                      or apks or archives)]
    tree = game_folder_in(folder, listed)
    if not (apks or archives or tree or iphone):
        return None
    return {"path": folder, "apks": apks, "archives": archives, "tree": tree, "iphone": iphone,
            "parts": {n: len(importer.parts_with(n, files)) for n in archives}}


def known_folders():
    """Where Windows keeps this user's Downloads, Desktop and Documents: they can be moved to another drive or into
    OneDrive. Nothing elsewhere, or when Windows does not say."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        import uuid

        class GUID(ctypes.Structure):
            # The layout Windows expects for a folder's id.
            _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

        out = []
        # FOLDERID_Downloads, FOLDERID_Desktop, FOLDERID_Documents.
        for fid in ("374DE290-123F-4565-9164-39C4925E467B", "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
                    "FDD39AD0-238F-46AF-ADB4-6C85480369C7"):
            guid = GUID.from_buffer_copy(uuid.UUID(fid).bytes_le)
            where = ctypes.c_wchar_p()
            # 0 is S_OK; the path Windows hands back is freed with CoTaskMemFree.
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(where)) == 0:
                out.append(where.value)
                ctypes.windll.ole32.CoTaskMemFree(where)
        return [p for p in out if p]
    except (OSError, AttributeError, ValueError):
        return []


def home_folders():
    """The folders people keep files in: their home, Downloads, Desktop and Documents (wherever Windows keeps them),
    and the ones OneDrive keeps."""
    home = os.path.expanduser("~")
    names = ["", "Downloads", "Desktop", "Documents", os.path.join("OneDrive", "Desktop"),
             os.path.join("OneDrive", "Documents"), os.path.join("OneDrive", "바탕 화면"), os.path.join("OneDrive", "문서")]
    out = []
    for p in [os.path.join(home, n) if n else home for n in names] + known_folders():
        if p not in out and os.path.isdir(p):
            out.append(p)
    return out


def found_on_this_pc():
    """The folders with the game's files in the usual places, the most complete first: [look_in() result]. Kept for
    SCAN_LIFE seconds, for the same places: each click in the folder picker draws the page again."""
    tops = home_folders()
    with _scan_lock:
        if _scan["key"] == tops and time.time() - _scan["at"] < SCAN_LIFE:
            return _scan["found"]
        seen, found = set(), []
        for top in tops:
            listed = entries(top)
            if listed is None:
                continue
            # The place itself, with the listing just read, then each folder in it.
            for folder, inside in [(top, listed)] + [(e.path, None) for e in listed if is_dir(e)]:
                # Downloads, the Desktop and Documents are folders of the home as well: each is looked in once.
                if folder in seen:
                    continue
                seen.add(folder)
                hit = look_in(folder, inside)
                if hit:
                    found.append(hit)
        # The same server files folder seen from two places (Downloads, and the folder in it): said once, by the folder
        # with files of its own beside it, else the one nearest to it.
        best = {}
        for h in found:
            if h["tree"]:
                score = (bool(h["apks"] or h["archives"] or h["iphone"]), len(h["path"]))
                if h["tree"] not in best or score > best[h["tree"]][0]:
                    best[h["tree"]] = (score, h)
        for h in found:
            if h["tree"] and best[h["tree"]][1] is not h:
                h["tree"] = None
        found = [h for h in found if h["apks"] or h["archives"] or h["iphone"] or h["tree"]]
        # A folder with both the client and the server files first, then by how much it has; the iPhone app alone last.
        found.sort(key=lambda h: (not (h["apks"] and (h["archives"] or h["tree"])), not (h["apks"] or h["archives"] or h["tree"]),
                                  -(len(h["apks"]) + len(h["archives"]))))
        _scan.update(key=tops, at=time.time(), found=found[:8])
        return _scan["found"]


def drives():
    """The drives of a Windows PC (C:\\ and the others there), or the file system's root elsewhere."""
    if os.name != "nt":
        return ["/"]
    # Asked of Windows, not tried letter by letter: a network drive that is not connected can hang a look for seconds.
    if hasattr(os, "listdrives"):
        try:
            return os.listdrives()
        except OSError:
            pass
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except (OSError, AttributeError):
        return ["C:\\"]
    return [f"{c}:\\" for i, c in enumerate(string.ascii_uppercase) if mask >> i & 1]


def parent_of(path):
    """The folder above path, or None at the top of a drive, a network share or the file system."""
    here = os.path.normpath(path)
    up = os.path.dirname(here)
    return up if up != here else None


def listing(path):
    """A folder for the folder picker: its subfolders and the game's files in it, or None when it cannot be read."""
    listed = entries(path)
    if listed is None:
        return None
    folders, files = [], []
    names = [e.name for e in listed]
    for e in listed:
        try:
            # Each with its full path, joined the system's way.
            if e.is_dir():
                folders.append((e.name, os.path.join(path, e.name)))
            # The game's kinds of file; an archive in parts by its first part, which says how many more there are.
            elif e.name.lower().endswith(APP_SUFFIXES + (IPA_SUFFIX,)) or importer.archive_role(e.name) == "first":
                files.append((e.name, e.stat().st_size, os.path.join(path, e.name)))
        except OSError:
            continue
    return {"path": path, "parent": parent_of(path), "folders": folders[:MAX_LISTED], "files": files[:MAX_LISTED],
            "more": len(folders) > MAX_LISTED or len(files) > MAX_LISTED, "tree": game_folder_in(path, listed),
            "parts": {n: len(importer.parts_with(n, names)) for n, _, _ in files[:MAX_LISTED]}}


def what_is(path):
    """importer.what_is for one file or folder, kept a while (WHAT_LIFE for a folder, while a file stays the same)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    folder = os.path.isdir(path)
    key = (path, 0 if folder else st.st_size, 0 if folder else st.st_mtime_ns)
    with _what_lock:
        hit = _what.get(key)
        if hit and (not folder or time.time() - hit[0] < WHAT_LIFE):
            return hit[1]
    answer = importer.what_is(path)
    with _what_lock:
        # A few hundred at most: a picker's folder of files at a time.
        if len(_what) > 500:
            _what.clear()
        _what[key] = (time.time(), answer)
    return answer


def client_words(info):
    """inspect()'s answer for a client, in the page's words."""
    version = info.get("version") or "?"
    if info["kind"] == "original":
        words = t("setup.what_original", version=version)
    elif info["kind"] == "other server":
        words = t("setup.what_changed", version=version, host=", ".join(info["hosts"]))
    elif info["kind"] == "built here":
        return t("setup.what_built")
    else:
        return t("setup.what_not_game")
    # A client the code edits were not made for plays the same, with a few of its own screens as they were.
    return words if info.get("known") else f"{words}. {t('setup.what_fewer_fixes')}"


def what_words(w):
    """what_is()'s answer in the page's words."""
    if w is None:
        return t("setup.what_gone")
    if w["kind"] == "app":
        return client_words(w["client"])
    if w["kind"] == "server files":
        words = t("setup.what_files", n=w["songs"]) if w["songs"] else t("setup.what_files_no_songs")
        return f"{words}. {t('setup.what_with_app')}" if w["apps"] else words
    return t({"iphone app": "setup.what_ipa", "part": "setup.what_part", "unreadable": "setup.what_unreadable",
              "archive": "setup.what_inner" if w["ok"] else "setup.what_neither"}.get(w["kind"], "setup.what_neither"))


# ------------------------------------------------------------------------------ the address

# Interfaces no phone is on: those of containers, of virtual machines, and tunnels. The command line has the same list
# (cli/opendmtq_cli/env.py): these two packages do not import each other.
VIRTUAL_INTERFACES = re.compile(r"^(docker|br-|veth|virbr|vnet|vboxnet|vmnet|lxdbr|lxcbr|podman|cni|flannel|kube|cali|wg|tun|tap|tailscale|zt)")


def interface_addresses():
    """What `ip` lists on real interfaces (Linux). On a network with no default route, with the computer's name on 127.0.1.1 as
    usual on Debian and Ubuntu, the other two ways below find nothing. Elsewhere there is no `ip`, and they do."""
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"],
                             capture_output=True, text=True, timeout=5, errors="replace").stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = re.findall(r"^\d+:\s+(\S+)\s+inet (\d+\.\d+\.\d+\.\d+)", out, re.M)
    return [address for name, address in found if not VIRTUAL_INTERFACES.match(name)]


def this_pcs_addresses():
    """This computer's IPv4 addresses on its local networks, the one towards the internet first."""
    out = []
    try:
        # Connecting a UDP socket picks the address of the default route and sends nothing.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 53))
            out.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            out.append(info[4][0])
    except OSError:
        pass
    out += interface_addresses()
    good = []
    for a in out:
        try:
            ip = ipaddress.IPv4Address(a)
        except ValueError:
            continue
        # Phones reach private addresses only, never loopback or link-local ones.
        if ip.is_private and not ip.is_loopback and not ip.is_link_local and a not in good:
            good.append(a)
    return good


def address_parts(address):
    """("host", port) of "host" or "host:port" (port 80 when none)."""
    host, sep, port = address.rpartition(":")
    return (host, int(port)) if sep and port.isdigit() else (address, 80)


def save_env(updates):
    """Set keys in .env, keeping every other line as it is (as cli/opendmtq_cli/env.save does)."""
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        lines = []
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in updates and "=" in line:
            lines[i] = f"{key}={updates[key]}"
            done.add(key)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    with open(ENV_FILE + ".tmp", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(ENV_FILE + ".tmp", ENV_FILE)


# ------------------------------------------------------------------------------ the one-time sign-in

def new_signin_key():
    """A one-time sign-in for these pages, kept in the run folder: the host program opens the browser with it, and a
    restart asked for here comes back signed in with it."""
    key = secrets.token_urlsafe(24)
    with open(SIGNIN_FILE + ".tmp", "w", encoding="ascii") as f:
        f.write(key)
    os.replace(SIGNIN_FILE + ".tmp", SIGNIN_FILE)
    return key


def take_signin_key(key):
    """True, once, for the key in the run folder while it is fresh; the file goes either way."""
    if not SIGNIN_FILE or not key:
        return False
    try:
        with open(SIGNIN_FILE, encoding="ascii") as f:
            kept = f.read().strip()
        fresh = time.time() - os.path.getmtime(SIGNIN_FILE) < SIGNIN_LIFE
    except OSError:
        return False
    # Compared as bytes, in constant time: a key with other characters in it is a wrong key, not a crash.
    if not same_text(kept, key):
        return False
    try:
        os.remove(SIGNIN_FILE)
    except OSError:
        pass
    return fresh


def sign_in_owner():
    """Sign this browser in as the owner, as the sign-in page does."""
    session.clear()
    session.permanent = True
    sid = secrets.token_urlsafe(24)
    with auth._sessions_lock:
        auth._sessions.add(sid)
    session.update(ok=True, sid=sid, csrf=secrets.token_urlsafe(24), who=core.ADMIN_USER, stamp="owner")


def from_this_pc():
    """True when the request comes from this computer itself."""
    try:
        return ipaddress.ip_address(auth.client_ip()).is_loopback
    except ValueError:
        return False


# ------------------------------------------------------------------------------ the pages

@app.route(BASE + "/setup/start")
def setup_start():
    """The way in the host program opens the browser with: a one-time key, from this PC only, signs the owner in."""
    if HOST_INSTALL and not from_this_pc():
        # The link is for the server PC's own browser (the key stays unused); anywhere else the password signs in.
        flash(t("setup.key_here_only"), "bad")
        return redirect(url_for("login", next=url_for("setup_page")))
    if not (HOST_INSTALL and take_signin_key(request.args.get("key", ""))):
        flash(t("setup.key_used"), "bad")
        return redirect(url_for("login", next=url_for("setup_page")))
    sign_in_owner()
    changed("setup:signin", auth.client_ip())
    # The step the link names, or (none named) the first one left.
    return redirect(url_for("setup_page", step=request.args.get("step") or None))


@app.route(BASE + "/setup/ping")
def setup_ping():
    """Which process answers: a restart asked for on these pages is over when the answer changes."""
    return jsonify(instance=STARTED)


@app.route(BASE + "/setup")
def setup_page():
    """The setup: the step asked for, or the first one not done."""
    done = steps_done()
    step = request.args.get("step", "")
    if step not in STEPS:
        step = next((s for s in STEPS if not done[s]), "app")
    job_id = request.args.get("job", "")
    job = jobs._jobs.get(job_id)
    view = {"step": step, "done": done, "steps": STEPS, "words": step_words(), "host_install": HOST_INSTALL,
            "kubernetes": IN_KUBERNETES, "job": job_id if job else None, "sep": os.sep}
    if step == "files":
        view["has_data"] = songs.has_game_data()
        # What of it the files given did not have: the game stops at its start without it.
        view["data_missing"] = songs.missing_game_files() if view["has_data"] else []
        view["client"] = base_client()
        view["has_apk"] = has_base_apk()
        view["client_words"] = client_words(view["client"]["info"]) if view["has_apk"] else ""
        view["song_count"] = len(songs.catalog()) if view["has_data"] else 0
        if HOST_INSTALL:
            view["found"] = found_on_this_pc()
            asked = request.args.get("dir", "")
            browse = clean_path(asked) or default_folder()
            view["picked"] = None
            # A file's path opens its folder, with the file marked to import.
            if os.path.isfile(browse):
                view["picked"], browse = os.path.basename(browse), os.path.dirname(browse)
            view["listing"] = listing(browse)
            view["asked"] = asked
            # A folder that cannot be opened: said whether it is not there or not to be read, and the picker opens at the
            # nearest folder above it that can be (a typo near the end leaves the person close to where they meant).
            if view["listing"] is None:
                view["cannot_open"], view["cannot_up"] = browse, parent_of(browse)
                view["not_there"] = not os.path.exists(browse)
                near = parent_of(browse)
                while near and listing(near) is None:
                    near = parent_of(near)
                browse = near or default_folder()
                view["listing"] = listing(browse)
            if view["listing"] is not None:
                view["crumbs"] = crumbs(browse)
            view["drives"] = drives()
            view["homes"] = home_folders()
            view["path_example"] = ("C:\\Users\\you\\Downloads\\DMTQ" if os.name == "nt"
                                    else os.path.join(os.path.expanduser("~"), "Downloads", "DMTQ"))
    elif step == "address":
        view["addresses"] = this_pcs_addresses() if HOST_INSTALL else []
        view["current"] = address_parts(core.PUBLIC_HOST)[0]
        view["port"] = address_parts(core.PUBLIC_HOST)[1]
    elif step == "players":
        count, _ = auth.accounts_count()
        view["accounts"] = count or 0
        # The account just made, with its password: kept on the server for this one page (admin.keep_once).
        view["made"] = accounts.take_once()
        if view["made"]:
            view["message"] = apps.invite_text(apps.friends_address(core.server_health()), view["made"]["name"],
                                          view["made"]["password"])
    elif step == "app":
        view["offer"] = next((b for b in apps.builds() if b["current"]), None)
        # The words for the build button, put back on it when a build fails.
        view["build_word"] = t("app.rebuild") if view["offer"] else t("app.build")
        view["failed"] = apps.build_error()
        # A build these pages started, or the one the server runs at its start (after a new address, say).
        view["running"] = bool(jobs.running_build()) or builder_running()
        # The runtime for phones without 32-bit support: in the app when it is here.
        view["runtime"] = runtime_in_place()
        view["runtime_failed"] = runtime_failure()
        view["has_apk"] = has_base_apk()
        # The QR code of the download page, made with the app (an app from before it has none).
        view["qr"] = os.path.isfile(os.path.join(core.APK, "out", "download-qr.svg"))
    return render_template("setup.html", **view)


def busy():
    """What runs now that another job must wait for, in the page's words, or None: an import, or an app build (these
    pages' own, or the one the server runs at its start)."""
    with jobs._jobs_lock:
        kinds = {j["kind"] for j in jobs._jobs.values() if j["state"] == "running"}
    if "import" in kinds:
        return t("setup.importing")
    if "build" in kinds or builder_running():
        return t("setup.building_now")
    return None


@app.route(BASE + "/setup/what")
def setup_what():
    """What one file or folder on this PC is to the import, in the page's words: the setup's lists ask for each of
    theirs, so that the page shows at once and fills in. On a host install only."""
    if not HOST_INSTALL:
        abort(404)
    try:
        w = what_is(clean_path(request.args.get("path", "")))
        return jsonify(ok=bool(w and w["ok"]), text=what_words(w))
    except Exception:  # noqa: BLE001 - a file nobody foresaw (7-Zip missing, a device, a name the system refuses)
        app.logger.exception("setup/what")
        return jsonify(ok=False, text=t("setup.what_error"))


@app.route(BASE + "/setup/import", methods=["POST"])
def setup_import():
    """Import the game's files from a folder or file on this PC: the APK, the files the game needs to start, and the
    songs when asked; then the song list. On a host install only."""
    if not HOST_INSTALL:
        abort(404)
    path = clean_path(request.form.get("path", ""))
    if not path or not os.path.exists(path):
        flash(t("setup.no_path"), "bad")
        return redirect(url_for("setup_page", step="files"))
    if not os.access(path, os.R_OK) or (os.path.isdir(path) and not os.access(path, os.X_OK)):
        flash(t("setup.cannot_read", path=path), "bad")
        return redirect(url_for("setup_page", step="files", dir=path))
    if os.path.isdir(path) and too_wide(path):
        flash(t("setup.too_wide", path=path), "bad")
        return redirect(url_for("setup_page", step="files", dir=path))
    env = dict(os.environ)
    if os.path.isfile(path):
        # A single file: its folder, and only that file in it.
        env.update(OPENDMTQ_IMPORT_IN=os.path.dirname(path), IMPORT_ONLY=os.path.basename(path))
    else:
        env["OPENDMTQ_IMPORT_IN"] = path
        env.pop("IMPORT_ONLY", None)
    env.update(IMPORT_GAME="yes", IMPORT_SONGS="yes" if request.form.get("songs") == "yes" else "no")
    # The importer, then the song list the site and the game read (as ./opendmtq import does).
    cmds = [core.PYTHON + ["-m", "opendmtq_tools.importer"], core.PYTHON + ["-m", "opendmtq_tools.songs"]]
    # The check and the start under one lock: two clicks, or two pages, cannot start two jobs at once.
    with _busy_lock:
        why = busy()
        if why:
            flash(why, "bad")
            return redirect(url_for("setup_page", step="files"))
        job = jobs.start_job("import", cmds, env=env, path=path)
    changed("setup:import", path)
    return redirect(url_for("setup_page", step="files", job=job))


@app.route(BASE + "/setup/address", methods=["POST"])
def setup_address():
    """Change the address phones use and restart the server for it (host install only): the app is built again for it
    at the start."""
    if not (HOST_INSTALL and ENV_FILE and RUN_DIR):
        abort(404)
    host = request.form.get("host", "").strip()
    port = address_parts(core.PUBLIC_HOST)[1]
    try:
        ip = ipaddress.IPv4Address(host)
        ok = ip.is_private and not ip.is_loopback and not ip.is_link_local
    except ValueError:
        ok = False
    if not ok:
        flash(t("setup.bad_address", host=host), "bad")
        return redirect(url_for("setup_page", step="address"))
    new = host if port == 80 else f"{host}:{port}"
    # The address in use already: nothing to change, and no restart for it.
    if new == core.PUBLIC_HOST:
        return redirect(url_for("setup_page", step="players"))
    with _busy_lock:
        # A restart now would cut off the import or the build that runs.
        why = busy()
        if why:
            flash(why, "bad")
            return redirect(url_for("setup_page", step="address"))
        save_env({"PUBLIC_HOST": new})
        # On the server PC the browser comes back signed in after the restart (these pages' sessions end with it).
        # From anywhere else that link would not open: the sign-in page leads back to the setup instead.
        if from_this_pc():
            back = url_for("setup_start", key=new_signin_key(), step="players")
        else:
            back = url_for("setup_page", step="players")
        with open(os.path.join(RUN_DIR, "restart.request"), "w", encoding="ascii") as f:
            f.write(str(int(time.time())))
    changed("setup:address", host)
    return render_template("setup_restart.html", back=back, instance=STARTED)


@app.route(BASE + "/server/stop", methods=["POST"])
def server_stop():
    """Stop the server (a host install: the Windows bundle, Linux, macOS): the program that runs it stops every part, as
    closing its window or Ctrl+C would. These pages stop with it, so the answer comes first and says how to start again."""
    if not (HOST_INSTALL and RUN_DIR):
        abort(404)
    try:
        with open(os.path.join(RUN_DIR, "stop.request"), "w", encoding="ascii") as f:
            f.write(str(int(time.time())))
    except OSError as e:
        flash(t("server.stop_failed", why=e.strerror or str(e)), "bad")
        return redirect(url_for("maintenance_page"))
    changed("server:stop", auth.client_ip())
    # How to start it again: OpenDMTQ.exe on Windows, the command elsewhere.
    return render_template("server_stopped.html", windows=os.name == "nt")


@app.route(BASE + "/setup/player", methods=["POST"])
def setup_player():
    """An account for a player, made here as on the Accounts page; its ID and password are shown once."""
    name = request.form.get("name", "").strip()
    if not auth.ACCOUNT_NAME.fullmatch(name):
        flash(t("acc.bad_id"), "bad")
        return redirect(url_for("setup_page", step="players"))
    password = auth.account_password()
    if not auth.account_create(name, password, t("setup.made_note")):
        flash(t("acc.taken", name=name), "bad")
        return redirect(url_for("setup_page", step="players"))
    changed("accounts_page:create", name)
    # The password waits on the server for the next page only, never in the session's cookie.
    accounts.keep_once(name, password, t("setup.made_note"), "acc.made")
    return redirect(url_for("setup_page", step="players"))


@app.route(BASE + "/setup/build", methods=["POST"])
def setup_build():
    """Build the phone app for this server's address, as the App page does."""
    if not has_base_apk():
        flash(t("app.no_base"), "bad")
        return redirect(url_for("setup_page", step="app"))
    cmd = core.PYTHON + ["-m", "opendmtq_tools.builder", "--force", "--host", core.PUBLIC_HOST]
    with _busy_lock:
        # One build at a time: the page follows the one running.
        if jobs.running_build() or builder_running():
            return redirect(url_for("setup_page", step="app"))
        # An import first ends: it may be bringing the client in.
        why = busy()
        if why:
            flash(why, "bad")
            return redirect(url_for("setup_page", step="app"))
        job = jobs.start_job("build", cmd, host=core.PUBLIC_HOST)
    changed("app_page:", core.PUBLIC_HOST)
    return redirect(url_for("setup_page", step="app", job=job))


@app.template_filter("setup_url")
def setup_url(path):
    """The setup page with the folder picker at path."""
    return url_for("setup_page", step="files", dir=path) + "#picker"


def short_size(n):
    """A file's size in the words of the pages."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


app.jinja_env.filters["short_size"] = short_size
