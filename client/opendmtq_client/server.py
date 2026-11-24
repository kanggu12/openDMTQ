"""Talking to an OpenDMTQ server: is it one, sign in, what app does it offer, and the app itself.

What the server answers is its site's client.php (server/portal/client.php) and /apk:

  GET  /opendmtq/client.php?about    {"opendmtq", "name", "address", "app"}, no sign-in
  POST /opendmtq/client.php?signin   user, password -> {"account", "expires"} and the site's sign-in cookie; 403
                                     {"error": "banned", "reason", "until"} for an account whose player is banned, 403
                                     {"error": "off"} for one switched off on the Accounts page (from 0.11.1), each
                                     after the right password alone
  GET  /opendmtq/client.php?app      the app on offer: {"file", "sha256", "size", "built_at", "label", "package",
                                     "address"} (signed in)
  GET  /apk                          the app (signed in)
  POST /opendmtq/client.php?link     a one-time link that signs a browser in as the same account and opens its player's
                                     page: {"url", "page", "expires"} (signed in; from 0.11)
  GET  /opendmtq/client.php?records  the account's player's latest plays and best records (signed in; from 0.11)
  POST /opendmtq/client.php?claim    device: the PC's game player linked to the account when neither has the other
                                     (signed in; from 0.11.3): {"linked", "now", "player"} or {"linked": false, "why"}

Only the standard library (urllib), with short timeouts: the window calls these on a worker thread. The launcher keeps
the cookie the sign-in gives (as a browser does), never the password. No redirect is followed: the site sends a request
without a sign-in to its sign-in page, which here means the sign-in ended.

HTTPS is checked against Windows' own certificate authorities, and for a server that brought its own authority (an
installer downloaded from its site over HTTPS carries it, preset.py) against that one as well, for that server alone.

Each answer has its deadline (within): a server that sends its answer a byte at a time keeps every single read within
its wait, so a limit counted between reads never ends it. Inside within(seconds) every read of the thread's requests
waits only for what is left of those seconds, whatever it reads (the TLS handshake, the headers, the body).
"""

import contextlib
import hashlib
import http.client
import http.cookies
import json
import os
import re
import socket
import ssl
import tempfile
import threading
import time
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


# What no host's name or address holds: blanks and control characters, which HTTP refuses in an address (http.client's
# InvalidURL, raised only once a request is made), and the marks no name or address uses.
NOT_IN_A_HOST = re.compile(r'[\x00-\x20\x7f<>"{}|\\^`]')


def normalize(address):
    """What the player typed as the site's address: 'example.com:8080' -> 'http://example.com:8080'. Keeps https, and a
    port that is given; drops a path (the site's address is its root). The window's Connect, the guide's SERVER step and
    --server all come through here, so an address that is none is refused the same way and in the same words."""
    text = (address or "").strip()
    if not text:
        raise ServerError("Type the server's address.", "error.server.empty")
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urllib.parse.urlsplit(text)
        # .port raises ValueError for a port that is not a number or out of range.
        port = parts.port
    except ValueError:
        raise _not_an_address(address) from None
    # A host with a blank or a mark no host has in it ("not an address", "example .com") is no address either.
    if parts.scheme not in ("http", "https") or not parts.hostname or NOT_IN_A_HOST.search(parts.hostname):
        raise _not_an_address(address)
    host = "[%s]" % parts.hostname if ":" in parts.hostname else parts.hostname.lower()
    return "%s://%s%s" % (parts.scheme, host, ":%d" % port if port else "")


def _not_an_address(address):
    """The error for what is no site's address. Its English sentence is the window's English words (i18n
    error.server.address), so the command line says what the window says."""
    # The address as the player typed it, without the blanks round it that typing leaves.
    shown = (address or "").strip()
    return ServerError("%s is not an address." % shown, "error.server.address", address=shown)


def host_port(url):
    """('example.com', 8080) of a site's address, with the scheme's own port when it names none."""
    parts = urllib.parse.urlsplit(url)
    return parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)


class _Stay(urllib.request.HTTPRedirectHandler):
    """Follows no redirect: a redirect comes back as the HTTP error it is."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# ---------------------------------------------------------------------------------- one deadline for a whole answer

# The deadline of the answer each thread waits for now (time.monotonic()), or none: within() sets it.
_deadline = threading.local()


class Late(TimeoutError):
    """An answer that had not come whole by its deadline (within)."""


@contextlib.contextmanager
def within(seconds):
    """The answers of the thread's requests made inside, each whole within `seconds` from now: a read waits only for
    what is left of them (an earlier deadline of the same thread stays, being sooner)."""
    before = getattr(_deadline, "at", None)
    at = time.monotonic() + seconds
    _deadline.at = at if before is None else min(before, at)
    try:
        yield
    finally:
        _deadline.at = before


def _wait_left(sock):
    """Before a read of a timed socket: its wait cut to what is left of its thread's deadline, never longer than the
    request's own timeout (kept from the socket's first read); Late once nothing is left. Nothing outside within()."""
    own = getattr(sock, "odq_timeout", False)
    if own is False:
        # The request's own wait for a read, as the connection set it, before any deadline cut it.
        own = sock.odq_timeout = sock.gettimeout()
    at = getattr(_deadline, "at", None)
    if at is None:
        # No deadline: the request's own wait again (a socket a deadline cut earlier waits as it was made to).
        sock.settimeout(own)
        return
    left = at - time.monotonic()
    if left <= 0:
        raise Late("the answer had not come whole in its time")
    sock.settimeout(left if own is None else min(left, own))


class _TimedSocket(socket.socket):
    """A plain connection's socket whose every read waits only for what is left of its thread's deadline."""

    def recv_into(self, buffer, nbytes=0, flags=0):
        _wait_left(self)
        return super().recv_into(buffer, nbytes, flags)


class _TimedTLS(ssl.SSLSocket):
    """The same over TLS (a context's sslsocket_class): the handshake, and every read after it."""

    def do_handshake(self, block=False):
        _wait_left(self)
        return super().do_handshake(block)

    def recv_into(self, buffer, nbytes=None, flags=0):
        _wait_left(self)
        return super().recv_into(buffer, nbytes, flags)


class _Timed(http.client.HTTPConnection):
    """A connection whose socket is a timed one (_TimedSocket), made so as soon as it is connected."""

    def connect(self):
        super().connect()
        plain = self.sock
        # The same connection, its socket's number handed to the timed socket; its wait as the request set it.
        wait = plain.gettimeout()
        self.sock = _TimedSocket(plain.family, plain.type, plain.proto, fileno=plain.detach())
        self.sock.settimeout(wait)


class _TimedHTTPS(http.client.HTTPSConnection, _Timed):
    """The same over HTTPS: HTTPSConnection.connect wraps the timed socket _Timed.connect leaves (the order of the
    classes puts _Timed.connect under it), in a TLS socket of its context's class (_TimedTLS)."""


def _timed_context(context=None):
    """A TLS context (Windows' authorities when none is given) whose sockets are timed ones."""
    context = context or ssl.create_default_context()
    context.sslsocket_class = _TimedTLS
    return context


class _TimedHTTPHandler(urllib.request.HTTPHandler):
    """Plain HTTP over timed connections."""

    def http_open(self, req):
        return self.do_open(_Timed, req)


class _TimedHTTPSHandler(urllib.request.HTTPSHandler):
    """HTTPS over timed connections, with `context` (a _timed_context)."""

    def __init__(self, context):
        super().__init__(context=context)
        self.odq_context = context

    def https_open(self, req):
        return self.do_open(_TimedHTTPS, req, context=self.odq_context)


def build_opener(*handlers, context=None):
    """An opener whose answers keep their deadlines (within), with these handlers and this TLS context (Windows'
    authorities when none is given); one that follows redirects without _Stay among them (GitHub's file store)."""
    return urllib.request.build_opener(_TimedHTTPHandler(), _TimedHTTPSHandler(_timed_context(context)), *handlers)


_OPENER = build_opener(_Stay)
# The openers for servers with an authority of their own, by (address, authority): made once each, as each context
# reads Windows' certificate stores.
_OWN_OPENERS = {}


def _trust_path():
    """The file of the servers' own authorities."""
    return os.path.join(st.config_dir(), TRUST_FILE)


def _trusted():
    """{site address: PEM text} of the servers that brought their own authority; empty when there is none to read."""
    try:
        # utf-8-sig: as saved again by Notepad, with a byte-order mark.
        with open(_trust_path(), encoding="utf-8-sig") as f:
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


def authority(base):
    """The certificate authority trusted for the server at `base` alone (trust), as PEM text; None when there is none."""
    return _trusted().get(base) or None


def _opener(base, ca=None):
    """What a request to `base` goes through: the plain opener, or for a server over HTTPS with an authority of its own,
    one whose certificate check takes that authority as well as Windows' (ssl.create_default_context), with the same
    refusal to follow redirects. `ca`: the authority to take when `base` has none of its own (a server's at its old
    address, asked on another port of the same host: the connection test's look for a server that moved)."""
    ca = (_trusted().get(base) or ca) if base.startswith("https://") else None
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
        opener = build_opener(_Stay, context=context)
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


def _call(base, path, data=None, cookie=None, timeout=TIMEOUT, ca=None):
    """One request to the site; (status, its JSON answer, its headers). A status of 400 or more comes back as well.
    The whole answer comes within `timeout` (within), however it trickles in. `ca`: an authority to check its
    certificate with when `base` has none of its own (_opener)."""
    try:
        with within(timeout):
            try:
                with _opener(base, ca).open(_request(base + path, data, cookie), timeout=timeout) as response:
                    body, status, headers = response.read(), response.status, response.headers
            except urllib.error.HTTPError as e:
                # A refusal's own words come by the same deadline.
                body, status, headers = e.read(), e.code, e.headers
    except http.client.InvalidURL:
        # An address HTTP refuses (one a launcher kept before normalize() looked at hosts): no address, said as such.
        raise _not_an_address(base) from None
    except http.client.HTTPException as e:
        # Something at that address answered, but not in HTTP (another kind of service on that port): no OpenDMTQ
        # server. Neither an OSError nor a ValueError, so it is caught here on its own, its own words kept for the log.
        raise ServerError("%s answered in something other than HTTP (%r)" % (base, e), "error.server.not_opendmtq",
                          base=base) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise _unreachable(base, e) from None
    try:
        answer = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        answer = None
    return status, answer, headers


def about(base, timeout=TIMEOUT, ca=None):
    """The server's word on itself: {"opendmtq", "name", "address", "app"}; ServerError unless it is an OpenDMTQ server.
    `timeout`: how long to wait for its answer (the ready check waits less than a connect). `ca`: an authority to check
    its certificate with when `base` has none of its own (the server's at its old address: a server that moved)."""
    status, answer, _ = _call(base, "/opendmtq/client.php?about", timeout=timeout, ca=ca)
    if status != 200 or not isinstance(answer, dict) or "opendmtq" not in answer:
        # A page that is not the client's answer: an OpenDMTQ from before the PC client (every one since 0.1 answers its
        # health page with its game's patch), or another site.
        if _older_opendmtq(base, ca):
            raise ServerError("%s runs an OpenDMTQ older than 0.8, without the PC client's part" % base,
                              "error.server.too_old", base=base)
        raise ServerError("%s is not an OpenDMTQ server for PCs" % base, "error.server.not_opendmtq", base=base)
    return {"opendmtq": str(answer.get("opendmtq") or ""), "name": str(answer.get("name") or base),
            "address": str(answer.get("address") or ""), "app": bool(answer.get("app"))}


def _older_opendmtq(base, ca=None):
    """True when the site answers OpenDMTQ's health page as every OpenDMTQ does (a JSON object with its game's patch):
    an OpenDMTQ from before the PC client, which has no client.php. `ca` as about() takes it."""
    try:
        status, answer, _ = _call(base, "/opendmtq/health.php", ca=ca)
    except ServerError:
        # It answered the first question and not this one: whatever it is, it is no OpenDMTQ for PCs.
        return False
    return status == 200 and isinstance(answer, dict) and "patch" in answer


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
    if status == 403 and code == "banned":
        # The owner banned the account's player: the owner's reason, and the end when the ban has one (client.php), as
        # the site's sign-in says them.
        reason = str(answer.get("reason") or "")
        until = answer.get("until")
        if isinstance(until, int) and not isinstance(until, bool) and until > 0:
            # This computer's time, in a form both languages read.
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(until))
            raise ServerError("this account cannot sign in until %s: %s" % (when, reason), "error.signin.banned_until",
                              when=when, reason=reason)
        raise ServerError("this account cannot sign in: %s" % reason, "error.signin.banned", reason=reason)
    if status == 403 and code == "off":
        # The account is switched off on the server's Accounts page, said after its right password alone (client.php),
        # as the site's sign-in page says it.
        raise ServerError("this account is disabled and cannot sign in", "error.signin.off")
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


def _signed_out_or(status, answer):
    """SignedOut when the site's answer says the sign-in ended: on to its sign-in page, refused, or its word for it."""
    code = answer.get("error") if isinstance(answer, dict) else None
    if status in (302, 303, 403) or code == "signin":
        raise SignedOut("the server no longer takes the sign-in", "error.signin.ended")


def sign_in_link(base, cookie):
    """A one-time link that signs the PC's browser in to the site as this sign-in and opens the player's page (My page on
    the site): its whole address. SignedOut when the sign-in ended; ServerError error.link.none from a server older than
    such links (0.10 and before), whose site's own address then opens instead; ServerError for anything else."""
    status, answer, _ = _call(base, "/opendmtq/client.php?link", data=b"", cookie=cookie)
    _signed_out_or(status, answer)
    if status == 404:
        raise ServerError("the server makes no sign-in links (it is older than 0.11)", "error.link.none")
    url = answer.get("url") if isinstance(answer, dict) else None
    # A path on the site, as the site makes it: nothing that leads elsewhere is opened.
    if status != 200 or not isinstance(url, str) or not re.fullmatch(r"/opendmtq/login\.php\?once=[A-Za-z0-9_-]{43}", url):
        raise ServerError("the server answered %s" % status, "error.server.answered", status=status)
    return base + url


def _whole(value, least=None):
    """A whole number of an answer, or None for what is none (the site's own lists, read with care: they go on a page)."""
    if isinstance(value, bool) or not isinstance(value, int) or (least is not None and value < least):
        return None
    return value


def _words(value, most=200):
    """Words of an answer for a page, or None: text only, at most `most` characters."""
    return value[:most] if isinstance(value, str) and value.strip() else None


def _record(row):
    """One play or best of the site's records as the PLAY page shows it, or None for what is no record."""
    if not isinstance(row, dict) or _whole(row.get("score")) is None:
        return None
    # The chart's number too: a chart whose song the song list no longer has is named by it ("Chart 61").
    return {"chart": _whole(row.get("chart"), 0), "title": _words(row.get("title")),
            "chart_name": _words(row.get("chart_name"), 60),
            "score": row["score"], "grade": _words(row.get("grade"), 2) or "", "keys": row.get("keys") is True,
            "rank": _whole(row.get("rank"), 1), "players": _whole(row.get("players"), 0) or 0,
            "new_record": row.get("new_record") is True, "at": _whole(row.get("at")) or _whole(row.get("set_at")),
            "all_combo": row.get("all_combo") is True, "perfect_play": row.get("perfect_play") is True}


def records(base, cookie):
    """The signed-in account's player's latest plays and best records, as the site lists them (client.php?records):
    {"account", "player": {"id", "name", "rank"} or None (an account linked to no player), "recent": [...], "best":
    [...]}, each record as _record() reads it; None from a server older than these (0.10 and before). SignedOut when the
    sign-in ended."""
    status, answer, _ = _call(base, "/opendmtq/client.php?records", cookie=cookie)
    _signed_out_or(status, answer)
    if status == 404:
        return None
    if status != 200 or not isinstance(answer, dict):
        raise ServerError("the server answered %s" % status, "error.server.answered", status=status)
    player = answer.get("player") if isinstance(answer.get("player"), dict) else None
    out = {"account": _words(answer.get("account"), 40) or "", "player": None, "recent": [], "best": []}
    if player is not None and _whole(player.get("id"), 0) is not None:
        out["player"] = {"id": player["id"], "name": _words(player.get("name"), 60) or "", "rank": _whole(player.get("rank"), 1)}
        for key in ("recent", "best"):
            listed = answer.get(key) if isinstance(answer.get(key), list) else []
            out[key] = [r for r in (_record(row) for row in listed[:20]) if r is not None]
    return out


def claim_player(base, cookie, device):
    """The signed-in account linked to the game player who plays by `device` on the server (client.php?claim: this PC's
    game's id, which it signs in by), which the server does when the account has no player and that player no account:
    {"linked": True, "now": whether this call made the link} for an account that has its player, or {"linked": False,
    "why": "none" (no player plays by that id yet), "taken" (that player has an account), "owner" or "banned"}. None from
    a server older than such links (0.11.2 and before). SignedOut when the sign-in ended."""
    data = urllib.parse.urlencode({"device": device}).encode("ascii")
    status, answer, _ = _call(base, "/opendmtq/client.php?claim", data=data, cookie=cookie)
    _signed_out_or(status, answer)
    if status == 404:
        return None
    if status != 200 or not isinstance(answer, dict):
        raise ServerError("the server answered %s" % status, "error.server.answered", status=status)
    return {"linked": answer.get("linked") is True, "now": answer.get("now") is True, "why": _words(answer.get("why"), 20) or ""}


# What an Android package name is: the player makes the game's data folder of it, so nothing else may pass (a name with
# a path in it would put the game's data outside OpenDMTQ's folder).
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+\Z")
# Characters no file name of the app may hold: player.conf is one line a setting, and Windows refuses these in a name.
NOT_IN_A_NAME = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')


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
    # The package and the file name go into the player's settings file and its folders: only names that are names.
    if (not PACKAGE.match(str(info["package"])) or NOT_IN_A_NAME.search(info["file"]) or info["file"] in (".", "..")
            or info["size"] <= 0):
        raise ServerError("the server offered an app that has no proper name or size", "error.app.named")
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
    done = told = 0
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
                    # What has come, up to a piece: never a wait for a whole piece, so that a server sending its
                    # answer a few bytes at a time still hears Cancel at once.
                    piece = response.read1(PIECE)
                    if not piece:
                        break
                    done += len(piece)
                    if done > info["size"]:
                        # More than the server said: not the app it described, and no reason to fill the disk with it.
                        raise ServerError("the app arrived damaged; try again", "error.app.damaged")
                    f.write(piece)
                    digest.update(piece)
                    if progress and (done - told >= PIECE or done == info["size"]):
                        # Told a piece at a time, and at the end, as before: the window draws each.
                        told = done
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
    except http.client.HTTPException as e:
        # The answer broke off or came in something other than HTTP: the app did not come whole, and nothing is kept.
        _remove(part)
        raise ServerError("the app arrived damaged (%r); try again" % e, "error.app.damaged") from None
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
