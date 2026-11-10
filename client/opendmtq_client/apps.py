"""Each server's app on this PC: a folder of its own, servers\\<host>-<port> in the launcher's folder, holding the APK
the server built for its address and player.conf, which names it for the player (player --app <folder>; the player
reads it as arm32/desktop/own_folder.cpp says).

    player.conf    name=<the app's label>  package=<its package>  apk=<its file name>
    app.json       what the server said of it (its SHA-256, size and date), checked when it came

One app per server: a newer one replaces it, the older file goes once the new one is whole and checked.
"""

import json
import logging
import os
import re
import sys
import tempfile

from opendmtq_client import safety
from opendmtq_client import server as srv
from opendmtq_client import state as st

log = logging.getLogger("opendmtq_client")

CONF = "player.conf"
DETAILS = "app.json"


def key(url):
    """The folder name for a server's address: its host and port ('example.com-8080'), in letters a path keeps."""
    host, port = srv.host_port(url)
    return "%s-%d" % (re.sub(r"[^A-Za-z0-9.-]", "-", host.strip("[]")) or "server", port)


def folder(url):
    """The server's folder in the launcher's (made when an app first comes)."""
    return os.path.join(st.config_dir(), "servers", key(url))


def _write(path, text):
    """A small file written whole or not at all."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".write-")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def local(url):
    """The app this PC has for the server: what the server said of it when it came, with "path"; None without one (or
    with one whose file has gone)."""
    base = folder(url)
    try:
        with open(os.path.join(base, DETAILS), encoding="utf-8") as f:
            details = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(details, dict) or not details.get("file"):
        return None
    path = os.path.join(base, os.path.basename(str(details["file"])))
    # The file itself, at the size it came at: one cut short or replaced by hand is no app to start.
    try:
        if os.path.getsize(path) != int(details.get("size") or -1):
            return None
    except (OSError, ValueError):
        return None
    if not os.path.isfile(os.path.join(base, CONF)):
        return None
    return dict(details, path=path)


def current(url, info):
    """True when this PC has the app the server offers (`info`, from server.app_info)."""
    have = local(url)
    return bool(have and str(have.get("sha256", "")).lower() == str(info.get("sha256", "")).lower())


def conf_text(info):
    """player.conf for an app: its name (the window's title), its package and its file."""
    # One line each: a label with a line break in it would end its own line early.
    name = " ".join(str(info.get("label") or "OpenDMTQ").split())
    return ("# The app this player runs, as the OpenDMTQ launcher got it from its server.\n"
            "name=%s\npackage=%s\napk=%s\n" % (name, info["package"], info["file"]))


def install(url, info, path):
    """Make the downloaded, checked app at `path` the server's app: player.conf and app.json name it, and any other
    APK in the folder goes."""
    base = folder(url)
    os.makedirs(base, exist_ok=True)
    keep = {"file": info["file"], "sha256": str(info["sha256"]).lower(), "size": int(info["size"]),
            "built_at": info.get("built_at") or "", "label": info.get("label") or "", "package": info["package"]}
    # The new app's names first, then the old file out: a stop in between leaves an app that starts.
    _write(os.path.join(base, CONF), conf_text(info))
    _write(os.path.join(base, DETAILS), json.dumps(keep, indent=2, ensure_ascii=False))
    for name in os.listdir(base):
        if name.lower().endswith(".apk") and name != info["file"]:
            try:
                os.remove(os.path.join(base, name))
            except OSError:
                # Held by a player still running: it goes with the next app.
                pass
    return local(url)


def remove(url):
    """The server's folder gone: its app and what named it (the player's own data stays in its folder). What cannot go
    (an app a game still has open) stays, and the log says so."""
    import shutil
    path = folder(url)
    if not os.path.lexists(path):
        # A server this PC never had an app from.
        return
    # A test deletes only in a folder of its own (safety.py).
    safety.refuse_deleting_in_tests(path)

    def failed(function, where, error):
        # Python 3.12 hands the error (onexc), earlier ones its (type, value, traceback) (onerror).
        log.warning("could not delete %s: %s", where, error[1] if isinstance(error, tuple) else error)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=failed)
    else:
        shutil.rmtree(path, onerror=failed)
