"""The players' site's look on these pages: its stylesheet, fonts, video player and icon, fetched from the game server
and kept for when it is down."""

import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import abort

from . import core
from .core import app

# The public site's stylesheet, fonts and icon, asked for again after a minute (they change when the
# server is updated). The last good copy of each also waits on the data disk, so these pages keep
# their look while the game server is down, across restarts of this service too.
_css = {}
_CSS_TTL = 60
SITE_COPIES = os.path.join(os.path.dirname(core.DB), "admin-cache")

# Before any copy exists (a first start with the server down), a small stylesheet of our own.
FALLBACK_CSS = os.path.join(os.path.dirname(__file__), "static", "fallback.css")


def _disk_copy(key, body=None):
    """The copy of key on the data disk (None if there is none); with body, save that instead."""
    path = os.path.join(SITE_COPIES, key)
    try:
        if body is None:
            with open(path, "rb") as f:
                return f.read()
        os.makedirs(SITE_COPIES, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=SITE_COPIES, prefix=".tmp-")
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        # Swapped in whole: a reader never gets half a stylesheet.
        os.replace(tmp, path)
    except OSError:
        # Not writable (or not there): the copy in memory still serves while this service runs.
        pass
    return None


def _cached(key, url, ctype):
    hit = _css.get(key)
    if not hit or time.time() - hit[0] > _CSS_TTL:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                body = r.read()
            if not hit or hit[1] != body:
                _disk_copy(key, body)
        except OSError:
            # Down: the last copy, from memory or the disk; the server is asked again in a minute.
            body = hit[1] if hit else _disk_copy(key)
            if body is None:
                if key != "style.css":
                    abort(404)
                with open(FALLBACK_CSS, "rb") as f:
                    return f.read(), 200, {"Content-Type": ctype, "Cache-Control": "no-store"}
        hit = (time.time(), body)
        _css[key] = hit
    return hit[1], 200, {"Content-Type": ctype, "Cache-Control": f"max-age={_CSS_TTL}"}


@app.route("/opendmtq/fonts/<name>")
def public_font(name):
    """The site's fonts, for when these pages are served on their own port."""
    if not re.fullmatch(r"dmtq-[a-z0-9-]+\.woff2", name):
        abort(404)
    return _cached(name, f"{core.SERVER_URL}/opendmtq/fonts/{name}", "font/woff2")


@app.route("/opendmtq/style.css")
def public_css():
    """The public site's stylesheet, for when these pages are served on their own port."""
    return _cached("style.css", f"{core.SERVER_URL}/opendmtq/style.css", "text/css")


@app.route("/opendmtq/hls/<name>")
def public_hls(name):
    """The video player the Recordings page loads, for when these pages are served on their own port.
    One copy, the portal's, kept like the stylesheet. Open like the stylesheet too: the session cookie
    only goes to these pages' own address, and this is a published file that the public site serves to anyone."""
    if not name.startswith("hls-") or not name.endswith(".min.js") or "/" in name:
        abort(404)
    return _cached(name, f"{core.SERVER_URL}/opendmtq/hls/{name}", "text/javascript")


@app.route("/opendmtq/favicon.svg")
def public_favicon():
    """The site's tab icon, for when these pages are served on their own port."""
    return _cached("favicon.svg", f"{core.SERVER_URL}/opendmtq/favicon.svg", "image/svg+xml")
