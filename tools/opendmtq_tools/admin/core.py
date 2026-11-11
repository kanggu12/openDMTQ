"""What every admin page shares: the settings, the Flask application, the languages, the database handle, the game
server's health, the words for errors and the note of what changed.

Run: gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 opendmtq_tools.admin:app
(one worker: build jobs and the sign-in throttle live in memory)
"""

import contextlib
import datetime
import errno
import hmac
import html
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

from flask import Flask, Request, abort, flash, g, has_request_context, jsonify, redirect, render_template, request, session, url_for
from markupsafe import Markup

from .. import songs, strings
from . import insights

# Container paths, mounted by compose (or the Kubernetes sidecar).
DB = os.environ.get("OPENDMTQ_DB", "/data/dmtq.db3")
LOGS = os.environ.get("OPENDMTQ_LOGS", "/data/logs")
APK = os.environ.get("OPENDMTQ_APK", "/apk")

# Python for the tools these pages run: this service's own (python3 in the image, the install's own on a host install),
# isolated from the user's environment (-I), and writing UTF-8 whatever the system's code page (-X utf8): on Windows a
# folder name the code page lacks would stop the import otherwise.
PYTHON = [sys.executable, "-I", "-X", "utf8"]
BACKUPS = os.environ.get("OPENDMTQ_BACKUPS", "/backups")
SERVER_URL = os.environ.get("SERVER_URL", "http://server:8080")
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
CHECK_UDID = "opendmtq-check"

# One row per player: scores are saved under the guid, and a transfer code gives a second phone's
# Member row the same guid. The same pick as the public site (portal/ranking_lib.php PLAYER_ROWS); the
# check account is left out.
PLAYER_ROWS = """SELECT guid, nickname FROM (
        SELECT CAST(guid AS INTEGER) AS guid, nickname,
               ROW_NUMBER() OVER (PARTITION BY CAST(guid AS INTEGER)
                                  ORDER BY (id = CAST(guid AS INTEGER)) DESC, id ASC) AS pick
          FROM Member WHERE udid IS NOT ? AND guid IS NOT NULL)
     WHERE pick = 1"""

# The owner's own admin account, from .env. It signs in without the database, so that these pages can still restore
# one that is damaged.
ADMIN_USER = os.environ.get("ADMIN_USER", "") or "admin"

# Settings of these pages themselves, kept with the database.
SETTINGS = os.path.join(os.path.dirname(DB), "admin-settings.json")

# A backup carries the added songs, so it may be much bigger than one song package.
MAX_BACKUP = 1024 * 1024 * 1024

# What a visitor who has not signed in may send: the sign-in form is a few hundred bytes.
MAX_SIGNED_OUT = 16 * 1024

# The most of a refused upload read and thrown away so that its answer arrives (too_large()). Past this
# the connection simply closes.
MAX_DISCARD = 8 * 1024 * 1024 * 1024

# The API (api.py): its address, beside these pages' own, and the version in it. A later version that changes what a route
# answers would come in beside this one.
API = "/opendmtq/api"
API_V1 = API + "/v1"

# What one request to the API may send: a JSON body is a few hundred bytes. The routes that take a file have their own
# limit, the page's for the same file: api.py names them here (endpoint: bytes), with the ones whose file waits on the
# backups disk.
API_MAX_JSON = 1024 * 1024
API_LIMITS = {}
API_TO_BACKUPS = set()


def is_api(path):
    """True for an address of the API: the pages' rules (sign-in, form tokens, the page's language) are not its rules."""
    return path == API or path.startswith(API + "/")


def in_api():
    """True while a request to the API is answered."""
    return has_request_context() and is_api(request.path)


class AdminRequest(Request):
    """Upload limits per page: the backup upload takes more than a song package, and nothing big
    is read for a visitor without the password (this limit also stops a chunked body, which has no
    length to check first)."""

    @property
    def max_content_length(self):
        # The API: a caller whose token has not passed sends nothing big either; past it, each route's own limit.
        if is_api(self.path):
            return API_LIMITS.get(self.endpoint, API_MAX_JSON) if g.get("api_token") else MAX_SIGNED_OUT
        if not auth.signed_in():
            return MAX_SIGNED_OUT
        return MAX_BACKUP if self.endpoint == "backups_page" else songs.MAX_PACKAGE

    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        # A backup waits on the backups disk, not in this container's /tmp (memory, shared with builds). The API's upload
        # of one too.
        if self.endpoint == "backups_page" or self.endpoint in API_TO_BACKUPS:
            os.makedirs(BACKUPS, exist_ok=True)
            return tempfile.TemporaryFile(dir=BACKUPS)
        return super()._get_file_stream(total_content_length, content_type, filename, content_length)


class Refused(Exception):
    """An action that did not happen, and why, for a page and the API alike (each action is one function both call).
    words: what the page says, made in the page's language (English on the API), or None where the page says nothing
    (it was so already). status and code: what the API answers. message: the API's own sentence where the page has no
    words. tone: the page's colour for the words ("bad", or "ok" where nothing went wrong). extra: what a page needs to
    answer it (the address typed, limits waiting for a yes)."""

    def __init__(self, status, code, words=None, message=None, tone="bad", **extra):
        super().__init__(code)
        self.status, self.code, self.words, self.message, self.tone, self.extra = status, code, words, message, tone, extra

    def sentence(self):
        """The API's message: its own sentence, else the page's words as plain text."""
        return self.message or plain(self.words)


def plain(words):
    """Words made for a page as plain text: their markup out, what it escaped back (a name with a < in it stays one)."""
    return html.unescape(re.sub(r"<[^>]+>", "", str(words or "")))


def json_error(status, code, message, headers=None, extra=None):
    """The API's answer to what it cannot do: {"error": {"code", "message"}} with its status, and extra's fields beside
    them where an error has more to say (the folder the setup's picker opens instead, say)."""
    response = jsonify(error={"code": code, "message": message, **(extra or {})})
    response.status_code = status
    for name, value in (headers or {}).items():
        response.headers[name] = value
    return response

# Where these pages live: under the players' site's own address, so that the server has one tree (/opendmtq for the
# players, /opendmtq/admin for the owner). Until 2026-11 they were at /admin, which now leads here (old_address()).
BASE = "/opendmtq/admin"

app = Flask(__name__, static_url_path=BASE + "/static")

app.request_class = AdminRequest

# A notice that is on points players at noti.html on the server's address; after an address change
# it must point at the new one.
try:
    _on, _message = songs.maintenance()
    if _on and PUBLIC_HOST:
        songs.set_maintenance(True, _message, PUBLIC_HOST)
except OSError:
    pass

# Sessions last until the service restarts; a new secret each start signs everyone out.
app.secret_key = secrets.token_bytes(32)

# Lax, not Strict: a link from the public site (plain HTTP, to these pages over HTTPS, which browsers
# count as another site) must arrive signed in. Every POST carries the CSRF token all the same.
# (Upload limits come from AdminRequest, not MAX_CONTENT_LENGTH.)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_PATH=BASE, PERMANENT_SESSION_LIFETIME=datetime.timedelta(hours=12))


def form_page():
    """The admin page a form was sent from (many forms post to an address with no page of its
    own), or the dashboard."""
    path = urllib.parse.urlsplit(request.referrer or "").path
    return path if path.startswith(BASE + "/") and path != BASE + "/login" else url_for("dashboard")


def same_text(a, b):
    """Constant-time comparison of two texts. compare_digest refuses a str with anything but ASCII in it: a
    password typed with the Korean keyboard on must be a wrong password, not a crash."""
    return hmac.compare_digest(a.encode("utf-8", "replace"), b.encode("utf-8", "replace"))

# The chosen language, shared with the portal: the same cookie name and path as LANG_COOKIE in
# server/portal/lib.php, and cookies do not care about ports.
LANG_COOKIE = "opendmtq_lang"
LANG_DAYS = 365


# Who acts, and in which language, in the work of a form that runs as a job (jobs.start_page_task): it runs in a thread of
# its own, after the request that started it has ended.
_acting = threading.local()


@contextlib.contextmanager
def acting_as(language, who):
    """Inside, in this thread: lang() is language and changed() notes the change by who, as in the request that started
    the job."""
    _acting.lang, _acting.who = language, who
    try:
        yield
    finally:
        _acting.lang = _acting.who = None


def lang():
    """The page language: what the visitor chose in the switch, else English. The browser's language does not decide:
    the switch is on every page. A job of a form speaks the language of the request that started it (acting_as). Outside
    a request otherwise (a test, a command's job), English. The API speaks English to every caller."""
    if getattr(_acting, "lang", None):
        return _acting.lang
    if not has_request_context() or in_api():
        return "en"
    return "ko" if request.cookies.get(LANG_COOKIE) == "ko" else "en"


def t(key, **values):
    """The text for key in the page language, as HTML: the table's own markup stays and every value is
    escaped. Fit for flash() and {{ }} in the pages. A count of one takes the words for one (strings.raw_text)."""
    raw = strings.raw_text(lang(), key, values)
    return key if raw is None else Markup(raw).format(**values)


def tp(key, **values):
    """The same as plain text, unescaped, for what is not HTML: confirm() dialogs and scripts, through
    |tojson. Only for those: escaping happens nowhere else on this path."""
    return strings.text(lang(), key, **values)


def said(e):
    """What an exception says in the page language: song errors have words of ours, others their own."""
    return t(e.key, **e.values) if isinstance(e, songs.SongError) else str(e)


def server_name():
    """The server's name in the app's title, as patch_apk.server_name() decides for this address:
    SERVER_NAME, or the address exactly as set, port included (several servers can share a host)."""
    return os.environ.get("SERVER_NAME", "").strip() or PUBLIC_HOST


def lan_only(address):
    """True for a private IPv4 address: phones must share the server's network, and the site stays on plain HTTP there."""
    host = re.sub(r":\d+$", "", address)
    return bool(re.fullmatch(r"(10\.\d+|192\.168|172\.(1[6-9]|2\d|3[01])|127\.\d+)\.\d+\.\d+", host))


def site_scheme(health):
    """How visitors reach the public site by its address, as the server itself sends them there (plain_pages in
    server/entrypoint.sh): over HTTPS where it has that, except on a local network address."""
    return "https" if (health or {}).get("https") and not lan_only(PUBLIC_HOST) else "http"


def app_name():
    """The app's name on players' devices."""
    return f"TECHNIKA Q ({server_name()})"


def app_name_html(label=None):
    """An app's name as HTML, styled as a name (.app-name in the portal's style.css): the title, then the
    server's name in pieces that stay whole, so a long address wraps after a dot or before the port and
    never at a hyphen. Without a label, this server's app."""
    label = label or app_name()
    title, _, rest = label.partition(" (")
    pieces = [p for p in re.split(r"(?<=[.\s])|(?=:\d+$)", rest.removesuffix(")")) if p]
    parts = Markup("<wbr>").join(Markup("<span>{}</span>").format(p) for p in pieces)
    if not rest:
        return Markup('<span class="app-name">{}</span>').format(label)
    return Markup('<span class="app-name">{} <span class="addr">({})</span></span>').format(title, parts)


# With or without its slash, as one rule: a second rule for "/admin" would make the router redirect between them, and the
# sign-in gate (guard()) would send that visit to the sign-in page instead.
@app.route("/admin/", defaults={"rest": ""}, methods=["GET", "HEAD", "POST"], strict_slashes=False)
@app.route("/admin/<path:rest>", methods=["GET", "HEAD", "POST"])
def old_address(rest):
    """These pages' address until 2026-11 (/admin/...): the same page at its address now (BASE), with its query. 308 keeps
    a form's POST a POST with its body, and is permanent, so a bookmark or a link learns the new address."""
    target = f"{BASE}/{rest}"
    if request.query_string:
        target += "?" + request.query_string.decode("latin-1")
    return redirect(target, 308)


@app.route(BASE + "/lang")
def set_lang():
    """The language switch: remembers the choice and goes back to the page it was pressed on."""
    target = request.args.get("next", "")
    # Only local paths under these pages' address, never another site.
    response = redirect(target if target.startswith(BASE + "/") else url_for("dashboard"), 303)
    if request.args.get("to") in strings.STRINGS:
        response.set_cookie(LANG_COOKIE, request.args["to"], max_age=LANG_DAYS * 86400, path="/", samesite="Lax",
                            httponly=True)
    return response


@app.after_request
def vary_by_language(response):
    """The same address has two languages, so caches keep one copy of each."""
    response.vary.add("Cookie")
    # Back after signing out must not bring a signed-in page out of the browser's cache.
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store"
    return response


# What every answer of these pages and their API tells the browser. No page of theirs is ever framed, by them or by the
# site: another site's frame could put an admin's clicks on buttons it hides (DENY). A file is what its type says,
# never what the browser guesses from its bytes (nosniff). A link to another address takes no address of these pages
# with it, a recording's or a player's (same-origin).
SECURITY_HEADERS = {"X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin"}


@app.after_request
def security_headers(response):
    """SECURITY_HEADERS on every answer, unless the answer set one of its own."""
    for name, value in SECURITY_HEADERS.items():
        # setdefault: a value an answer chose for itself stays.
        response.headers.setdefault(name, value)
    return response


# The types of the pages' own files (static/), which Flask takes from the system's list. Under nosniff a browser runs a
# script only when it is sent as one, and on Windows that list comes from the registry, where some programs make .js
# text/plain: admin.js would then never run there.
STATIC_TYPES = {".js": "text/javascript", ".css": "text/css"}


def static_types():
    """Puts STATIC_TYPES over what the system says. Called once here, before any request is answered."""
    for ending, kind in STATIC_TYPES.items():
        # add_type reads the system's list first when nothing has yet, so this comes after it and stays.
        mimetypes.add_type(kind, ending)


static_types()


def public_url():
    """Where links to the public site point. Through the server (it passes /opendmtq/admin on), the site is
    on the same address. On the admin's own port, it is the site's port on the host this page was
    opened with: the server PC reaches that without the router looping back to the public name."""
    if request.headers.get("X-Forwarded-Host"):
        return ""
    port = re.search(r":\d+$", PUBLIC_HOST)
    return "http://" + re.sub(r":\d+$", "", request.host) + (port.group(0) if port else "")


@app.context_processor
def template_globals():
    health = server_health()
    return {"csrf": session.get("csrf", ""), "is_signed_in": auth.signed_in(), "public_host": PUBLIC_HOST, "public_url": public_url(),
            "max_upload": songs.MAX_PACKAGE, "max_backup": MAX_BACKUP,
            "server_ok": bool(health and health.get("ok")), "server_problem": server_problem(health),
            "server_waiting": waiting_for_files(health),
            # Who is signed in, for the bar, and the server's patch, for the footer (the health answer has it).
            "who": str(session.get("who", "")) if auth.signed_in() else "", "who_owner": session.get("stamp") == "owner",
            "patch": (health or {}).get("patch") or "",
            "t": t, "tp": tp, "lang": lang(),
            # On the server PC itself (a host install, the Windows bundle): the pages can import from its folders, through
            # the setup's first step (admin/setup.py).
            "host_install": setup.HOST_INSTALL,
            # On Kubernetes: nothing on these pages starts or stops the server's parts.
            "kubernetes": setup.IN_KUBERNETES,
            "app_name_html": app_name_html, "device_words": logs.device_words}


def read_text(raw):
    """A text of the database as these pages and the API read it: UTF-8, with any byte that is no part of it read as
    U+FFFD. A player's name in an older server's database can hold such bytes (the game stored what the phone sent), and
    Python's strict reading would stop every page and answer that reads it ("Could not decode to UTF-8")."""
    return raw.decode("utf-8", "replace")


def db():
    # An existing file only: a page asked for while the database is away must not leave an empty one in its place, which
    # would then be taken for the database, and backed up as it.
    con = sqlite3.connect(f"file:{urllib.parse.quote(DB)}?mode=rw", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    # Texts read leniently (read_text): about 40 ns more a text than the strict default, which no page notices.
    con.text_factory = read_text
    return con

# The last answer of the game server's health check: (time, answer or None). Every page's header
# shows it, so it is asked at most every HEALTH_TTL seconds; the dashboard always asks.
_health = (0.0, None)
HEALTH_TTL = 15


def server_health(fresh=False):
    global _health
    if fresh or time.time() - _health[0] > HEALTH_TTL:
        try:
            with urllib.request.urlopen(f"{SERVER_URL}/opendmtq/health.php", timeout=3) as r:
                _health = (time.time(), json.load(r))
        except urllib.error.HTTPError as e:
            # A 503 from the health page is an answer: the server runs and says what is wrong in the body.
            try:
                _health = (time.time(), json.load(e))
            except ValueError:
                _health = (time.time(), None)
            finally:
                e.close()
        except (OSError, ValueError):
            _health = (time.time(), None)
    return _health[1]


def server_problem(health):
    """What a server that answers says is wrong, in the page's words; None when it is well or does not answer."""
    if not health or health.get("ok"):
        return None
    if not health.get("database"):
        return t("health.no_db")
    if health.get("writable") is False:
        return t("health.read_only")
    if health.get("game_data") is False:
        return t("health.no_game_data")
    return t("health.other")


def waiting_for_files(health):
    """True when the game server answers and lacks only the game's files: a server being set up, not a broken one. The
    pages then point to the setup's first step instead of raising the alarm."""
    return (bool(health) and not health.get("ok") and health.get("game_data") is False and bool(health.get("database"))
            and health.get("writable") is not False)


def safe_name(name, folder, suffix):
    """A plain file name inside folder, or 404. Only the letters, digits and signs the names made here have (backups and
    builds alike): no separator of any system (a backslash and a drive's colon lead out of the folder on Windows), no
    leading dot and no "..", so that a name always stays in folder."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name or "") or name.startswith(".") or ".." in name or not name.endswith(suffix):
        abort(404)
    path = os.path.join(folder, name)
    if not os.path.isfile(path):
        abort(404)
    return path


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            # One decimal, without a trailing ".0" (300 MB, 84.5 MB).
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f}".removesuffix(".0") + f" {unit}"
        n /= 1024

app.jinja_env.filters["human"] = human


def private_file(path, encoding=None):
    """A new file at path, readable by this user only (backups hold the signing key; .env the passwords): open for
    bytes, or for text in encoding when given."""
    # Binary on Windows too, where files open as text unless told: the text wrapper does its own line ends.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    # O_CREAT's mode only applies to a new file; one being replaced is narrowed too (Windows has no such modes:
    # there the file is as private as the folder it is in).
    if hasattr(os, "fchmod"):
        os.fchmod(fd, 0o600)
    return os.fdopen(fd, "w", encoding=encoding) if encoding else os.fdopen(fd, "wb")


def discard_body():
    """Reads what is left of a refused upload. Through the game server, an answer sent while the body
    is still coming ends in a closed connection, which Apache turns into a 502, instead of the page
    that says why. Only for those who signed in (guard() answers everyone else first, without reading)."""
    stream = request.environ.get("wsgi.input")
    left = MAX_DISCARD
    try:
        while stream and left > 0:
            chunk = stream.read(min(left, 1024 * 1024))
            if not chunk:
                break
            left -= len(chunk)
    except OSError:
        # The sender gave up: nobody is left to answer anyway.
        pass


@app.errorhandler(413)
def too_large(_err):
    # The API: in its own words, the rest of the body read first only for a caller whose token passed (as for a page).
    if in_api():
        if g.get("api_token"):
            discard_body()
        return json_error(413, "too_large", plain(t("err.too_large", max=human(request.max_content_length))))
    # The upload pages check the size before sending; this catches the rest.
    if request.endpoint == "login":
        return tp("err.too_large_signin"), 413
    discard_body()
    flash(t("err.too_large", max=human(request.max_content_length)), "bad")
    return redirect(request.path)


def why(e):
    """A failure in the page's words. What it says exactly goes to the log: the system's text is English, and of
    little use on a phone."""
    app.logger.warning("admin: %s: %s", e.__class__.__name__, e)
    if isinstance(e, OSError) and e.errno == errno.ENOSPC:
        return tp("err.disk_full")
    if isinstance(e, sqlite3.OperationalError) and "locked" in str(e):
        return tp("err.db_busy")
    if isinstance(e, (tarfile.TarError, EOFError, zlib.error)):
        return tp("err.bad_archive")
    return tp("err.see_log")


@app.errorhandler(sqlite3.Error)
def database_failed(e):
    # The database is missing, damaged or not this game's. The dashboard and the backups stay reachable from here.
    app.logger.exception("database failure on %s", request.path)
    if in_api():
        return json_error(503, "database_unavailable", plain(t("err.db_text")))
    return render_template("error.html", title=t("err.db_title"), text=t("err.db_text")), 503


@app.errorhandler(500)
def internal_error(_err):
    if in_api():
        return json_error(500, "internal_error", plain(t("err.text")))
    return render_template("error.html", title=t("err.title"), text=t("err.text")), 500


@app.errorhandler(405)
def wrong_method(err):
    # The API: which methods the address has, as HTTP says (the Allow header).
    if in_api():
        allowed = ", ".join(sorted(m for m in (getattr(err, "valid_methods", None) or []) if m not in ("HEAD", "OPTIONS")))
        return json_error(405, "method_not_allowed", f"This address takes {allowed or 'other methods'}.", {"Allow": allowed})
    # An address for a form's button, opened as a page (from the history, or typed): the same page, with the way back.
    return render_template("notfound.html"), 405


@app.errorhandler(404)
def not_found(err):
    # The API: a route it does not have, or a thing it does not know (abort(404) where a file is not there).
    if in_api():
        return json_error(404, "not_found", "There is nothing at this address.")
    # An address that leads nowhere gets the admin's own page (styled, readable on a phone), with the
    # way back. Visitors who are not signed in never get here: guard() sends them to the sign-in page.
    return render_template("notfound.html"), 404


@app.errorhandler(400)
def bad_request(err):
    # A body that cannot be read (a broken upload): the API says so in its own shape; a page keeps Flask's own answer.
    if in_api():
        return json_error(400, "bad_request", "The request could not be read.")
    return err


def ago(when):
    """How long ago a moment was, as the portal says it."""
    d = int(time.time() - when)
    for unit, key in ((86400 * 30, "ago.mo"), (86400, "ago.d"), (3600, "ago.h"), (60, "ago.min")):
        if d >= unit:
            return tp(key, n=d // unit)
    return tp("ago.now")


def settings():
    """The console's own settings: a daily backup is on unless turned off."""
    out = {"auto_backup": True}
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            out.update(json.load(f))
    except (OSError, ValueError):
        pass
    return out


def save_settings(**changes):
    now = settings()
    now.update(changes)
    with open(SETTINGS + ".tmp", "w", encoding="utf-8") as f:
        json.dump(now, f)
    os.replace(SETTINGS + ".tmp", SETTINGS)


# The record of changes (the Logs page's third tab). Written where a change has really happened, not guessed afterwards from
# the answer: a refused form, a failed upload or a question back to the owner also come back as a page or a redirect.
def acting_who():
    """Who acts in this request, as the log of changes names them: the admin signed in, or through the API the admin whose
    token it was, with the token's name (api.py sets api_who)."""
    if in_api():
        return g.get("api_who", "")
    return str(session.get("who", "")) if session.get("ok") else ""


def changed(what, target=""):
    """Notes a change that has happened, at the end of the request: what is the page and the form's action, target the words
    for who or what it was about, as they are now. No values beyond those: no passwords, no messages. Through the API the
    same page and action, by the admin whose token it was. In a form's job, after its request has ended, at once, by
    whoever sent the form (acting_as)."""
    if not has_request_context():
        insights.audit_note(os.path.dirname(DB), what, target[:100], who=getattr(_acting, "who", None) or "")
        return
    g.changes = getattr(g, "changes", []) + [(what, target[:100], acting_who())]


@app.after_request
def note_changes(response):
    for what, target, who in getattr(g, "changes", []):
        insights.audit_note(os.path.dirname(DB), what, target, who=who)
    return response


# The modules these helpers call, last: they take the names above from this module as it now stands.
from . import auth, logs, setup  # noqa: E402
