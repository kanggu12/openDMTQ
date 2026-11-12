"""The players' site's look on these pages: its stylesheet, fonts, video player and icon, fetched from the game server
and kept for when it is down."""

import hashlib
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import abort, request

from . import core
from .core import app
from .insights import OWN_AGENT

# The public site's stylesheet, fonts and icon, asked of the game server again after a minute (they change when the
# server is updated). The last good copy of each also waits on the data disk, so these pages keep their look while the
# game server is down, across restarts of this service too. Each is kept as (when it was asked for, its bytes, when they
# last changed).
_css = {}
_CSS_TTL = 60
SITE_COPIES = os.path.join(os.path.dirname(core.DB), "admin-cache")

# How a browser keeps them, as the site's own answers say it (server/apache/site.conf): what the pages name without a
# version (the stylesheet, the icon) is asked for each time, a 304 while it is the same; what has its version in its name
# (the fonts, the video player) is kept a year without asking.
ASK_EACH_TIME = "no-cache"
KEEP = "max-age=31536000, immutable"

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


def _cached(key, url, ctype, keep=ASK_EACH_TIME):
    """The copy of one of the site's files, as a browser gets it: with its ETag and when it last changed, so that asking
    again for the same answers 304 and nothing, and kept as keep says."""
    hit = _css.get(key)
    if not hit or time.time() - hit[0] > _CSS_TTL:
        try:
            # By the pages' own name: the Requests log says these fetches are the admin pages', not a script's.
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": OWN_AGENT}), timeout=3) as r:
                body = r.read()
            # New bytes are new from now; the same bytes keep the moment they last changed.
            changed = hit[2] if hit and hit[1] == body else time.time()
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
            # The copy on the disk changed when its file did.
            changed = hit[2] if hit else _disk_time(key)
        hit = (time.time(), body, changed)
        _css[key] = hit
    response = app.response_class(hit[1], content_type=ctype)
    response.headers["Cache-Control"] = keep
    # The same bytes, the same tag, whichever copy they came from (the server, memory or the disk).
    response.set_etag(hashlib.sha256(hit[1]).hexdigest()[:32])
    # For a browser that asks by the time instead.
    response.last_modified = int(hit[2])
    # A browser that has these bytes already (If-None-Match, If-Modified-Since): 304, without them.
    return response.make_conditional(request)


def _disk_time(key):
    """When the copy of key on the data disk last changed, or now when that cannot be said."""
    try:
        return os.path.getmtime(os.path.join(SITE_COPIES, key))
    except OSError:
        return time.time()


@app.route("/opendmtq/fonts/<name>")
def public_font(name):
    """The site's fonts, for when these pages are served on their own port."""
    if not re.fullmatch(r"dmtq-[a-z0-9-]+\.woff2", name):
        abort(404)
    # Its name says which it is: a font that changes comes under a new name (dmtq-text-1), as the site keeps them.
    return _cached(name, f"{core.SERVER_URL}/opendmtq/fonts/{name}", "font/woff2", KEEP)


@app.route("/opendmtq/style.css")
def public_css():
    """The public site's stylesheet, for when these pages are served on their own port."""
    return _cached("style.css", f"{core.SERVER_URL}/opendmtq/style.css", "text/css")


@app.route("/opendmtq/hls/<name>")
def public_hls(name):
    """The video player the Recordings page loads, for when these pages are served on their own port.
    One copy, the portal's, kept like the stylesheet. Open like the stylesheet too: the session cookie
    only goes to these pages' own address, and this is a published file that the public site serves to anyone."""
    # The player's own name and nothing else (hls-1.5.17.min.js): the name is part of a path on the data disk too,
    # where a backslash is a separator on Windows.
    if not re.fullmatch(r"hls-[0-9.]+\.min\.js", name):
        abort(404)
    # Its version is in its name: kept.
    return _cached(name, f"{core.SERVER_URL}/opendmtq/hls/{name}", "text/javascript", KEEP)


@app.route("/opendmtq/favicon.svg")
def public_favicon():
    """The site's tab icon, for when these pages are served on their own port."""
    return _cached("favicon.svg", f"{core.SERVER_URL}/opendmtq/favicon.svg", "image/svg+xml")
