"""Talking to an OpenDMTQ server: is it one, sign in, what app does it offer, and the app itself.

What the server answers is its site's client.php (server/portal/client.php) and /apk:

  GET  /opendmtq/client.php?about    {"opendmtq", "name", "address", "app"}, no sign-in
  POST /opendmtq/client.php?signin   user, password -> {"account", "expires"} and the site's sign-in cookie
  GET  /opendmtq/client.php?app      the app on offer: {"file", "sha256", "size", "built_at", "label", "package",
                                     "address"} (signed in)
  GET  /apk                          the app (signed in)

Only the standard library (urllib), with short timeouts: the window calls these on a worker thread. The launcher keeps
the cookie the sign-in gives (as a browser does), never the password. No redirect is followed: the site sends a request
without a sign-in to its sign-in page, which here means the sign-in ended.

HTTPS is checked against Windows' own certificate authorities, and for a server that brought its own authority (an
installer downloaded from its site over HTTPS carries it, preset.py) against that one as well, for that server alone.
"""

import hashlib
import http.cookies
import json
import os
import socket
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from opendmtq_client import __version__
from opendmtq_client import state as st
from opendmtq_client.errors import Worded

# Seconds to wait for an answer: a server on the same network answers in milliseconds, a far one in well under this.
TIMEOUT = 10
# The app's download waits longer between pieces: a slow line still moves a piece in this time.
DOWNLOAD_TIMEOUT = 60
# The site's sign-in cookie (server/portal/auth.php).
COOKIE = "opendmtq_dl"
# What the app's download is read in, a piece at a time.
PIECE = 1 << 20
# The servers' own certificate authorities, in the launcher's folder: {site address: PEM text}.
TRUST_FILE = "trust.json"


class ServerError(Worded):
    """The server could not be reached, is no OpenDMTQ server, or refused; worded for the player (i18n.TEXT)."""


class SignedOut(ServerError):
    """The server no longer takes the sign-in (it ran out, or the account has a new password)."""


class Cancelled(Exception):
    """The download was stopped by the player."""


def normalize(address):
    """What the player typed as the site's address: 'example.com:8080' -> 'http://example.com:8080'. Keeps https, and a
    port that is given; drops a path (the site's address is its root)."""
    text = (address or "").strip()
    if not text:
        raise ServerError("type the server's address", "error.server.empty")
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urllib.parse.urlsplit(text)
        # .port raises ValueError for a port that is not a number or out of range.
        port = parts.port
    except ValueError:
        raise ServerError("%r is not an address" % address, "error.server.address", address=address) from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ServerError("%r is not an address" % address, "error.server.address", address=address)
    host = "[%s]" % parts.hostname if ":" in parts.hostname else parts.hostname.lower()
    return "%s://%s%s" % (parts.scheme, host, ":%d" % port if port else "")


def host_port(url):
    """('example.com', 8080) of a site's address, with the scheme's own port when it names none."""
    parts = urllib.parse.urlsplit(url)
    return parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)


class _Stay(urllib.request.HTTPRedirectHandler):
    """Follows no redirect: a redirect comes back as the HTTP error it is."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_Stay)
# The openers for servers with an authority of their own, by (address, authority): made once each, as each context
# reads Windows' certificate stores.
_OWN_OPENERS = {}


def _trust_path():
    """The file of the servers' own authorities."""
    return os.path.join(st.config_dir(), TRUST_FILE)


def _trusted():
    """{site address: PEM text} of the servers that brought their own authority; empty when there is none to read."""
    try:
        with open(_trust_path(), encoding="utf-8") as f:
            found = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(found, dict):
        return {}
    return {k: v for k, v in found.items() if isinstance(k, str) and isinstance(v, str)}


def trust(base, ca):
    """Trusts `ca` (a certificate authority's PEM text) for the server at `base` (a site address as normalize() writes
    it), from now on, beside Windows' own authorities; "" forgets it. Only that server's requests take it."""
    known = _trusted()
    if ca:
        known[base] = ca
    else:
        known.pop(base, None)
    folder = st.config_dir()
    os.makedirs(folder, exist_ok=True)
    # Whole or not at all: written beside it, then put in its place.
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".trust-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(known, f, indent=1)
    os.replace(tmp, _trust_path())


def _opener(base):
    """What a request to `base` goes through: the plain opener, or for a server over HTTPS with an authority of its own,
    one whose certificate check takes that authority as well as Windows' (ssl.create_default_context), with the same
    refusal to follow redirects."""
    ca = _trusted().get(base) if base.startswith("https://") else None
    if not ca:
        return _OPENER
    opener = _OWN_OPENERS.get((base, ca))
    if opener is None:
        context = ssl.create_default_context()
        try:
            context.load_verify_locations(cadata=ca)
        except (ssl.SSLError, ValueError):
            # Not a certificate after all: Windows' authorities alone, as for any other server.
            return _OPENER
        opener = urllib.request.build_opener(_Stay, urllib.request.HTTPSHandler(context=context))
        _OWN_OPENERS[(base, ca)] = opener
    return opener


def _request(url, data=None, cookie=None):
    """A request as the launcher makes it: its own name, the sign-in cookie when it has one."""
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    request.add_header("User-Agent", "OpenDMTQ-client/%s" % __version__)
    if data is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    if cookie:
        request.add_header("Cookie", "%s=%s" % (COOKIE, cookie))
    return request


def _unreachable(base, e):
    """The error for a server that did not answer at all, in plain words for the window (no answer, no such address,
    refused); the system's own text stays in the English sentence, which the log and the command line show."""
    reason = getattr(e, "reason", e)
    if isinstance(reason, socket.gaierror):
        # The name of the address leads nowhere: a typing mistake, or no network.
        key = "error.server.unknown_host"
    elif isinstance(reason, ConnectionRefusedError):
        # The computer is there, but nothing takes the connection: the server is off.
        key = "error.server.refused"
    elif isinstance(reason, TimeoutError) or "timed out" in str(reason):
        # No answer in TIMEOUT seconds.
        key = "error.server.timeout"
    else:
        key = "error.server.unreachable"
    return ServerError("cannot reach %s (%s)" % (base, reason), key, base=base)


def _call(base, path, data=None, cookie=None):
    """One request to the site; (status, its JSON answer, its headers). A status of 400 or more comes back as well."""
    try:
        with _opener(base).open(_request(base + path, data, cookie), timeout=TIMEOUT) as response:
            body, status, headers = response.read(), response.status, response.headers
    except urllib.error.HTTPError as e:
        body, status, headers = e.read(), e.code, e.headers
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise _unreachable(base, e) from None
    try:
        answer = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        answer = None
    return status, answer, headers


def about(base):
    """The server's word on itself: {"opendmtq", "name", "address", "app"}; ServerError unless it is an OpenDMTQ server."""
    status, answer, _ = _call(base, "/opendmtq/client.php?about")
    if status != 200 or not isinstance(answer, dict) or "opendmtq" not in answer:
        # A page that is not the client's answer: another site, or an OpenDMTQ too old to have one.
        raise ServerError("%s is not an OpenDMTQ server for PCs" % base, "error.server.not_opendmtq", base=base)
    return {"opendmtq": str(answer.get("opendmtq") or ""), "name": str(answer.get("name") or base),
            "address": str(answer.get("address") or ""), "app": bool(answer.get("app"))}


def sign_in(base, user, password):
    """Sign in to the site with an account its owner made: {"account", "expires", "cookie"}."""
    data = urllib.parse.urlencode({"user": user, "password": password}).encode("ascii")
    status, answer, headers = _call(base, "/opendmtq/client.php?signin", data)
    code = (answer or {}).get("error") if isinstance(answer, dict) else None
    if status == 401:
        raise ServerError("the ID or the password is wrong", "error.signin.wrong")
    if status == 429:
        raise ServerError("too many tries: wait a minute and try again", "error.signin.throttled")
    if status == 503:
        raise ServerError("the server cannot sign anyone in right now", "error.signin.down")
    if status != 200 or not isinstance(answer, dict) or not answer.get("account"):
        raise ServerError("the server answered %s%s" % (status, " (%s)" % code if code else ""), "error.server.answered",
                          status=status)
    cookie = None
    # The cookie the site sets, as a browser would keep it.
    for line in headers.get_all("Set-Cookie") or []:
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(line)
        except http.cookies.CookieError:
            continue
        if COOKIE in jar and jar[COOKIE].value:
            cookie = jar[COOKIE].value
    if not cookie:
        raise ServerError("the server signed in without a cookie", "error.server.answered", status=status)
    return {"account": str(answer["account"]), "expires": int(answer.get("expires") or 0), "cookie": cookie}


def app_info(base, cookie):
    """The app the server offers for its address; SignedOut when the sign-in ended, ServerError when there is none."""
    status, answer, _ = _call(base, "/opendmtq/client.php?app", cookie=cookie)
    code = answer.get("error") if isinstance(answer, dict) else None
    if status in (302, 303, 403) or code == "signin":
        raise SignedOut("the server no longer takes the sign-in", "error.signin.ended")
    if status == 404:
        raise ServerError("the server has no app yet", "error.app.none")
    if status == 409:
        raise ServerError("the server's app is for another address; its owner builds it again", "error.app.stale")
    if status == 503:
        raise ServerError("the server could not build its app; only its owner can help", "error.app.failed")
    needed = ("file", "sha256", "size", "package")
    if status != 200 or not isinstance(answer, dict) or any(not answer.get(k) for k in needed):
        raise ServerError("the server answered %s" % status, "error.server.answered", status=status)
    # The file name goes into a path: only its last part, as the site hands it out.
    info = dict(answer)
    info["file"] = os.path.basename(str(info["file"]).replace("\\", "/"))
    info["size"] = int(info["size"])
    return info


def download_app(base, cookie, info, folder, progress=None, cancel=None):
    """The app into `folder` under its own name, checked against its size and SHA-256; returns its path.

    progress(done, total) is told as it comes; cancel (a threading.Event) stops it. A part file holds it until it is
    whole and checked, so a stopped or damaged download never takes the app's name.
    """
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, info["file"])
    part = target + ".part"
    digest = hashlib.sha256()
    done = 0
    try:
        with _opener(base).open(_request(base + "/apk", cookie=cookie), timeout=DOWNLOAD_TIMEOUT) as response:
            kind = (response.headers.get("Content-Type") or "").split(";")[0].strip()
            if kind != "application/vnd.android.package-archive":
                # A page instead of the app: the site's own answer for a sign-in that ended or an app being built.
                raise ServerError("the server sent no app", "error.app.not_sent")
            with open(part, "wb") as f:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    piece = response.read(PIECE)
                    if not piece:
                        break
                    f.write(piece)
                    digest.update(piece)
                    done += len(piece)
                    if progress:
                        progress(done, info["size"])
                f.flush()
                os.fsync(f.fileno())
    except urllib.error.HTTPError as e:
        _remove(part)
        if e.code in (302, 303, 403):
            raise SignedOut("the server no longer takes the sign-in", "error.signin.ended") from None
        raise ServerError("the server answered %s" % e.code, "error.server.answered", status=e.code) from None
    except (Cancelled, ServerError):
        _remove(part)
        raise
    except (urllib.error.URLError, OSError, ValueError) as e:
        _remove(part)
        raise _unreachable(base, e) from None
    if done != info["size"] or digest.hexdigest() != str(info["sha256"]).lower():
        # The server changed its app meanwhile, or the line damaged it: nothing is kept.
        _remove(part)
        raise ServerError("the app arrived damaged; try again", "error.app.damaged")
    os.replace(part, target)
    return target


def _remove(path):
    """A file gone, when it is there."""
    try:
        os.remove(path)
    except OSError:
        pass
