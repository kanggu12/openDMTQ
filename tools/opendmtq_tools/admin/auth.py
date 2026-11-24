"""Who may come in: the sign-in with an ID and a password (the owner's from .env, or an account with admin rights), the
accounts' passwords, the CSRF token on every form and the throttle on failed sign-ins."""

import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import abort, flash, redirect, render_template, request, session, url_for

from .. import owner
from . import core
from .core import app, BASE, changed, db, same_text, t, tp

# The site's accounts: the only way into the public site's pages and, with admin rights, into these. Made on the
# Accounts page and nowhere else: nobody makes their own. The portal reads the same table (server/portal/lib.php:
# site_check, site_user), so a password is kept as PBKDF2-SHA256, which PHP checks with what it has built in. The
# server makes the table at start (server/game/bin/setup-db.php, the same statement); a database restored from before it
# needs it here too.
ACCOUNT_TABLE = """CREATE TABLE IF NOT EXISTS SiteUser (name TEXT PRIMARY KEY COLLATE NOCASE, pass TEXT NOT NULL,
                   note TEXT NOT NULL DEFAULT '', admin INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
                   signed_in_at INTEGER, off INTEGER NOT NULL DEFAULT 0, guid INTEGER)"""

# guid: the game player the account is, as the owner linked them on the Accounts page (NULL: not linked).
# Rounds of a password's hash: slow enough to make guessing the passwords of a stolen database costly, quick enough for
# a sign-in (about a tenth of a second). The portal's SITE_ROUNDS is the same number.
ACCOUNT_ROUNDS = 120000

# An ID: Latin letters, digits and . _ -, which every phone's keyboard has and no address mangles.
ACCOUNT_NAME = re.compile(r"[A-Za-z0-9._-]{3,20}")

# Made passwords: letters and digits nobody confuses when reading them off a phone (no 0 and o, no 1, l and i).
ACCOUNT_LETTERS = "abcdefghjkmnpqrstuvwxyz23456789"
_failures = {}
_all_failures = []
_failures_lock = threading.Lock()

# Per address: five failures per ten minutes. Overall: thirty per ten minutes, after which every
# sign-in waits, so guessing stays slow even when all visitors look alike (behind Docker's proxy
# they can all appear as one address).
PER_IP, OVERALL, WINDOW = 5, 30, 600

_server_addresses = (0.0, set())


def server_addresses():
    """Addresses the game server reaches this service from: the host in SERVER_URL, looked up again
    after a minute (a re-created container gets a new one)."""
    global _server_addresses
    if time.time() - _server_addresses[0] > 60:
        host = urllib.parse.urlsplit(core.SERVER_URL).hostname or ""
        try:
            found = {info[4][0] for info in socket.getaddrinfo(host, None)}
        except OSError:
            found = set()
        _server_addresses = (time.time(), found)
    return _server_addresses[1]


_stack_gateway = (0.0, None)


def stack_gateway():
    """The gateway of this service's own network (its default route's, from the kernel's table), looked up again after a
    minute: in Docker Compose the stack network's, the address Docker Engine passes the server PC's own visits on from (the
    server takes them so too: server/entrypoint.sh LOCAL_FROM). None where the system has no such table (Windows, macOS)
    or no default route."""
    global _stack_gateway
    if time.time() - _stack_gateway[0] > 60:
        found = None
        try:
            with open("/proc/net/route", encoding="ascii") as f:
                for line in f.read().splitlines()[1:]:
                    fields = line.split()
                    # The default route (destination 0) through a gateway: its address in hexadecimal, its bytes in
                    # reverse order, as the entrypoint reads it.
                    if len(fields) > 2 and fields[1] == "00000000" and fields[2] != "00000000":
                        found = socket.inet_ntoa(bytes.fromhex(fields[2])[::-1])
                        break
        except (OSError, ValueError):
            found = None
        _stack_gateway = (time.time(), found)
    return _stack_gateway[1]


def client_ip():
    """The visitor's address. Through the game server, X-Real-IP: Apache sets it from the
    connection (the edge passes the visitor's address on) and overwrites whatever the client sent.
    On this service's own port the header is the client's own and is ignored."""
    sent = request.headers.get("X-Real-IP")
    if sent and request.remote_addr in server_addresses():
        return sent
    return request.remote_addr or "?"

# Sign-ins that are still valid (an id in each session cookie, with when it runs out): signing out ends one for good,
# which a signed cookie alone cannot do. Kept beside the database too (admin-sessions.json, readable by this user only),
# so that a restart of the server, a stop and a start, or the setup's own restart signs nobody out.
_sessions = {}
_sessions_lock = threading.Lock()


def _sessions_file():
    """Where the valid sign-ins are kept: beside the database."""
    return os.path.join(os.path.dirname(core.DB), "admin-sessions.json")


def _sessions_load():
    """The sign-ins kept by the last run, those not run out yet. Called with the lock held, or before any request."""
    _sessions.clear()
    try:
        with open(_sessions_file(), encoding="utf-8") as f:
            kept = json.load(f)
    except (OSError, ValueError):
        return
    now = time.time()
    if isinstance(kept, dict):
        _sessions.update({sid: until for sid, until in kept.items()
                          if isinstance(sid, str) and isinstance(until, (int, float)) and until > now})


def _sessions_save():
    """Writes the valid sign-ins, the ones run out left behind. Called with the lock held. Quietly does nothing when the
    folder cannot be written: the sign-ins then last as long as this run, as they did before."""
    now = time.time()
    for sid in [sid for sid, until in _sessions.items() if until <= now]:
        del _sessions[sid]
    path = _sessions_file()
    try:
        fd = os.open(path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_sessions, f)
        os.replace(path + ".new", path)
    except OSError:
        pass


def session_begin():
    """A new sign-in's id, kept as valid for as long as the session cookie lasts."""
    sid = secrets.token_urlsafe(24)
    with _sessions_lock:
        _sessions[sid] = time.time() + core.app.permanent_session_lifetime.total_seconds()
        _sessions_save()
    return sid


def session_end(sid):
    """Ends a sign-in for good (signing out)."""
    with _sessions_lock:
        if _sessions.pop(sid, None) is not None:
            _sessions_save()


def _session_valid(sid):
    """True while the sign-in sid has not been ended and has not run out. Called with the lock held."""
    until = _sessions.get(sid)
    return until is not None and until > time.time()


# The sign-ins the last run left, at start.
_sessions_load()


def owner_stamp():
    """What an owner's session keeps of the owner's password, so that a new one (the Server page's change) ends the owner's
    other sign-ins: a keyed hash of it, which the browser, which can read its cookie, cannot test guesses against without
    the key the cookie is signed with."""
    return hmac.new(core.app.secret_key, core.PASSWORD.encode("utf-8", "replace"), hashlib.sha256).hexdigest()[:20]


def _session_began():
    """When this browser's sign-in to these pages began: its end less the sessions' life. Called with the lock held."""
    return _sessions.get(session.get("sid"), 0) - core.app.permanent_session_lifetime.total_seconds()


def owner_signed_out_at():
    """The moment the owner pressed Sign out everywhere else on the site's MY PAGE (owner-signed-out beside the database,
    which the site writes: the owner has no row in the accounts' table), or None."""
    try:
        with open(os.path.join(os.path.dirname(core.DB), "owner-signed-out"), encoding="ascii") as f:
            at = f.read().strip()
    except OSError:
        return None
    return int(at) if at.isdigit() else None


def _owner_session_current():
    """True while an owner's session was made with the owner's password as it is now, and began after the owner's last Sign
    out everywhere else. One from before sessions kept the password's stamp (an older version's) counts until the password
    is changed after it began. Called with the sessions' lock held."""
    began = _session_began()
    cut = owner_signed_out_at()
    if cut and began < cut:
        return False
    kept = session.get("pw")
    if kept is not None:
        return same_text(str(kept), owner_stamp())
    changed_at = core.settings().get("owner_password_at")
    return not changed_at or began >= changed_at


def signed_in():
    sid = session.get("sid")
    with _sessions_lock:
        if not (session.get("ok") and _session_valid(sid)):
            return False
        # The owner's account lives in .env and lasts as long as the session made with its password as it is now (a new
        # one, on the Server page, ends the others). Any other admin's ends with their account, their admin rights or
        # their password, at the next page they open.
        if session.get("stamp") == "owner":
            return _owner_session_current()
        began = _session_began()
    row = account_find(session.get("who", ""))
    if not (row and row["admin"] and not row["off"] and same_text(account_stamp(row["pass"]), session.get("stamp", ""))):
        return False
    # The account's Sign out everywhere else on the site's MY PAGE ends its sign-ins to these pages made before it too.
    cut = row["signed_out_at"] if "signed_out_at" in row.keys() else None
    return not (cut and began < cut)


def _account_ended():
    """The session itself is still good, but the account it is for is not (disabled, deleted, a new password, a restore;
    for the owner, a new password on the Server page)."""
    sid = session.get("sid")
    with _sessions_lock:
        return bool(session.get("ok") and _session_valid(sid) and (session.get("stamp") != "owner" or not _owner_session_current()))


def _prune(now):
    for ip in list(_failures):
        _failures[ip] = [t for t in _failures[ip] if now - t < WINDOW]
        if not _failures[ip]:
            del _failures[ip]
    _all_failures[:] = [t for t in _all_failures if now - t < WINDOW]


def throttled(ip):
    """True when this address, or everyone together, failed too often recently. The overall limit
    only counts for visits through the game server, the server PC's own among them: on this
    service's own port (Kubernetes' port-forward) the owner is not locked out by guesses from the
    internet. No header a visit brings exempts it."""
    now = time.time()
    through_server = request.remote_addr in server_addresses()
    with _failures_lock:
        _prune(now)
        return len(_failures.get(ip, [])) >= PER_IP or (through_server and len(_all_failures) >= OVERALL)


def note_failure(ip):
    with _failures_lock:
        _failures.setdefault(ip, []).append(time.time())
        _all_failures.append(time.time())


@app.before_request
def guard():
    """Sign-in required everywhere but the sign-in page; CSRF token on every POST."""
    # The API has no sign-in, no session and no forms: a token on every request, which api.py checks (its own
    # before_request, after this one). No session cookie is read or made for it.
    if core.is_api(request.path):
        return None
    # The old address leads to the new one before anything else (old_address()): a redirect, nothing read or shown.
    # The setup's one-time key (it signs in by itself) and its look at which process answers during a restart, too.
    if request.endpoint in ("login", "static", "public_css", "public_font", "public_favicon", "public_hls", "set_lang", "old_address",
                            "setup_start", "setup_ping"):
        return None
    if not signed_in():
        # A page's own look in the background (the status page's tiles, the log as it follows): a plain refusal. A message
        # queued for it would be used up there, and the owner would come to the sign-in with no word why.
        if request.headers.get("X-Requested-With") == "fetch":
            return ("", 401)
        # A sign-in that ended: its account changed (disabled, deleted, a new password, a restore), the service restarted or
        # someone signed out in another tab, or a form came without one (then what it sent did not count). The page says
        # which, and what it had to say before stays (a restore that worked says so).
        if session.get("ok") or request.method != "GET":
            why = "login.account_changed" if _account_ended() else ("login.expired" if request.method == "GET" else "login.expired_post")
            kept = session.get("_flashes", [])
            session.clear()
            if kept:
                session["_flashes"] = kept
            flash(t(why), "bad")
        # After signing in again, a form's sender goes back to its page, not to the form's address. A page keeps its query.
        return redirect(url_for("login", next=request.full_path.rstrip("?") if request.method == "GET" else core.form_page()))
    if request.method == "POST":
        sent = request.form.get("csrf") or request.headers.get("X-CSRF", "")
        # A backup's upload the backups disk could not hold while its form was read (core.AdminRequest): said in words.
        # Nothing was taken, so nothing needs the form's token.
        if request.upload_failed is not None:
            flash(t("bak.upload_failed", detail=core.why(request.upload_failed)), "bad")
            return redirect(core.form_page())
        if not same_text(sent, session.get("csrf", "")):
            # A page left open across signing out and in again: it reloads with a valid form.
            flash(t("err.stale_form"), "bad")
            return redirect(core.form_page())
    return None


def account_hash(password, salt=None):
    """A password as the accounts table keeps it: pbkdf2_sha256$<rounds>$<salt, hex>$<hash, hex>."""
    salt = secrets.token_bytes(16) if salt is None else salt
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ACCOUNT_ROUNDS)
    return f"pbkdf2_sha256${ACCOUNT_ROUNDS}${salt.hex()}${digest.hex()}"


def account_pass_ok(stored, password):
    """Whether password is the one stored, as account_hash wrote it (with the rounds it was written with)."""
    parts = (stored or "").split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256" or not parts[1].isdigit() or not 1000 <= int(parts[1]) <= 5000000:
        return False
    try:
        salt = bytes.fromhex(parts[2])
    except ValueError:
        return False
    # A password typed with the Korean keyboard on is a wrong password, not a crash.
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8", "replace"), salt, int(parts[1]))
    return hmac.compare_digest(digest.hex(), parts[3])

# What an ID that is not there is checked against: as slow as one that is, so that the time taken does not tell which
# IDs there are.
_NOBODY = account_hash(secrets.token_urlsafe(12))


def account_password():
    """A password for a new account, or a new one for an account: ten of ACCOUNT_LETTERS, about 50 bits."""
    return "".join(secrets.choice(ACCOUNT_LETTERS) for _ in range(10))


def account_stamp(stored):
    """What a session keeps of an account's password so that a new password ends it: not the hash itself, which the
    browser could read out of its cookie."""
    return hashlib.sha256(stored.encode("utf-8")).hexdigest()[:20]


def account_find(name):
    """An account by its ID, whatever the letter case, as a row; None when there is none or no database to ask."""
    if not ACCOUNT_NAME.fullmatch(name or ""):
        return None
    try:
        with db() as con:
            return con.execute("SELECT * FROM SiteUser WHERE name = ?", (name,)).fetchone()
    except sqlite3.Error:
        return None


def account_table(con):
    """The accounts' table as it is now: made when there is none, and the game player's column added to one made before
    it (a database from before, or restored from an older backup)."""
    con.execute(ACCOUNT_TABLE)
    have = {r[1] for r in con.execute("PRAGMA table_info(SiteUser)")}
    if "guid" not in have:
        con.execute("ALTER TABLE SiteUser ADD COLUMN guid INTEGER")
    # The moment from which the account's sign-ins to the site count (MY PAGE's Sign out everywhere else, which the site
    # writes): a table from before it gets it empty, and every sign-in counts. The server's start adds it too
    # (server/game/bin/setup-db.php).
    if "signed_out_at" not in have:
        con.execute("ALTER TABLE SiteUser ADD COLUMN signed_out_at INTEGER")


# The accounts' columns: what a restore copies of each (put_accounts), guid and the sign-out moment with them.
ACCOUNT_COLUMNS = ("name", "pass", "note", "admin", "created_at", "signed_in_at", "off", "guid", "signed_out_at")


def put_accounts(con, rows):
    """con's accounts made exactly rows (read from another database, every column of ACCOUNT_COLUMNS): the table made
    when that database has none, and whatever accounts it had gone. A restore gives the restored database today's
    accounts with it, as it does the API's tokens (tokens.put): an old backup must not bring back an account deleted
    since, nor a password changed since."""
    account_table(con)
    con.execute("DELETE FROM SiteUser")
    con.executemany(f"INSERT INTO SiteUser ({', '.join(ACCOUNT_COLUMNS)}) VALUES ({', '.join('?' for _ in ACCOUNT_COLUMNS)})",
                    [tuple(r[c] for c in ACCOUNT_COLUMNS) for r in rows])


def game_players(con):
    """Every player of the game (not the server's own check account), by name, for linking an account to one:
    [(guid, name)]. Two with one name are told apart by their number, as on the Plays tab."""
    rows = con.execute(f"SELECT guid, nickname FROM ({core.PLAYER_ROWS})", (core.CHECK_UDID,)).fetchall()
    named = sorted(((r["guid"], (r["nickname"] or "").strip() or tp("player.fallback", id=r["guid"])) for r in rows), key=lambda p: (p[1].lower(), p[0]))
    names = [name for _, name in named]
    return [(guid, f"{name} ({guid})" if names.count(name) > 1 else name) for guid, name in named]


def player_choice(value, players):
    """The player a form's choice names: None for none, the guid of one of players, or False for anything else."""
    if value in ("", None):
        return None
    if str(value).isdigit() and int(value) in {guid for guid, _ in players}:
        return int(value)
    return False


def account_create(name, password, note="", admin_rights=False, guid=None):
    """Makes an account, linked to the game player guid when given; False when its ID is taken (by an account, or by
    the owner's)."""
    if name.lower() == core.ADMIN_USER.lower():
        return False
    try:
        with db() as con:
            account_table(con)
            con.execute("INSERT INTO SiteUser (name, pass, note, admin, created_at, guid) VALUES (?, ?, ?, ?, ?, ?)",
                        (name, account_hash(password), note, 1 if admin_rights else 0, int(time.time()), guid))
        return True
    except sqlite3.IntegrityError:
        return False


def accounts_count():
    """How many accounts there are, and how many of them can sign in to the site; (None, None) when the database cannot
    say."""
    try:
        with db() as con:
            account_table(con)
            return tuple(con.execute("SELECT COUNT(*), COALESCE(SUM(off = 0), 0) FROM SiteUser").fetchone())
    except sqlite3.Error:
        return None, None


def admin_check(name, password):
    """Who an ID and a password sign in as on these pages: (ID, stamp) for the owner (.env) or for an account with admin
    rights that is on; None otherwise. Every way through does the same slow work, so that the time tells nothing."""
    if same_text(name.lower(), core.ADMIN_USER.lower()):
        account_pass_ok(_NOBODY, password)
        return (core.ADMIN_USER, "owner") if core.PASSWORD and same_text(password, core.PASSWORD) else None
    row = account_find(name)
    ok = account_pass_ok(row["pass"] if row else _NOBODY, password)
    if row and ok and row["admin"] and not row["off"]:
        return row["name"], account_stamp(row["pass"])
    # The right password of a site account without admin rights (or one turned off): told so, not called wrong.
    if row and ok:
        return False
    return None


# The owner's account for the players' site too: the site signs people in with the accounts' table, which has no row
# for the owner (that account lives in .env, here). This file gives the site the owner's ID and password as the table
# would keep them, so the ID and password the console and .env name open both doors. Beside the database, readable by
# this user only; rewritten when the password in .env changed, kept otherwise (its salt with it, so a sign-in on the
# site outlives a restart).
def owner_file():
    """Where the owner's account for the site is kept: owner.pass beside the database."""
    return os.path.join(os.path.dirname(core.DB), "owner.pass")


def owner_file_write():
    """Writes owner_file() for the owner's account as it is in .env now (removed when no password is set). Quietly does
    nothing when the folder cannot be written: the admin pages still work, and the site keeps its own accounts."""
    # The file's own rules (owner.py, which the repair uses too), with these pages' own way of keeping a password.
    # Returns what it did ("kept", "written", "removed", "failed"), which the repair reports.
    return owner.write_file(owner_file(), core.ADMIN_USER, core.PASSWORD, account_hash, account_pass_ok)


def owner_file_at_start():
    """owner_file_write() as this service starts. Written over one that was there: the owner's password changed in .env
    since the last start (the command line's password, or .env edited by hand), and the owner's sign-ins to these pages
    from before the change end with it, as the Server page's change ends them: those without the password's stamp too (the
    moment of the change, owner_password_at). Returns what owner_file_write() did."""
    existed = os.path.exists(owner_file())
    done = owner_file_write()
    if done == "written" and existed:
        try:
            core.save_settings(owner_password_at=int(time.time()))
        except OSError:
            # The stamped sign-ins end anyway (their stamp is of the old password).
            pass
    return done


# At start: the owner signs in to the site with what .env says from the first page on.
owner_file_at_start()
# An owner's ID the site does not take: said in the log at the start, as the Status page says it (status.attention).
if not owner.OWNER_ID.fullmatch(core.ADMIN_USER):
    app.logger.warning("the owner's ID %r cannot sign in to the players' site: an ID there is 1 to 40 letters (A-Z, a-z), "
                       "digits, '.', '_' or '-'; change ADMIN_USER and start the server again", core.ADMIN_USER)


@app.route(BASE + "/login", methods=["GET", "POST"])
def login():
    if not core.PASSWORD:
        return render_template("login.html", disabled=True)
    # Already signed in: nothing to do here.
    if request.method == "GET" and signed_in():
        target = request.args.get("next", "")
        return redirect(target if target.startswith(BASE + "/") else url_for("dashboard"))
    name = ""
    if request.method == "POST":
        # A sign-in form is a few hundred bytes; refuse anything bigger before reading it.
        if (request.content_length or 0) > 4096:
            abort(413)
        ip = client_ip()
        # The ID as typed, for the form again after a wrong password, and for the log of changes.
        name = request.form.get("name", "").strip()[:40]
        who = None if throttled(ip) else admin_check(name, request.form.get("password", ""))
        if throttled(ip):
            # Noted too: a sign-in that is refused for this reason must show in the log of changes.
            changed("login:throttled", f"{name}, {ip}" if name else ip)
            flash(t("login.throttled"), "bad")
        elif who is False:
            # The site's account, right password, but not one of these pages' accounts.
            note_failure(ip)
            changed("login:no_rights", f"{name}, {ip}")
            flash(t("login.no_rights"), "bad")
        elif who:
            session.clear()
            session.permanent = True
            sid = session_begin()
            session.update(ok=True, sid=sid, csrf=secrets.token_urlsafe(24), who=who[0], stamp=who[1])
            # The owner's: what of the owner's password it was made with, which a new one ends (owner_stamp()).
            if who[1] == "owner":
                session["pw"] = owner_stamp()
            # When an account last came in, for the list of accounts (the owner's is not in it).
            if who[1] != "owner":
                try:
                    with db() as con:
                        con.execute("UPDATE SiteUser SET signed_in_at = ? WHERE name = ?", (int(time.time()), who[0]))
                except sqlite3.Error:
                    pass
            changed("login:ok", f"{who[0]}, {ip}")
            target = request.args.get("next", "")
            # Only local paths under these pages' address, never another site.
            return redirect(target if target.startswith(BASE + "/") else url_for("dashboard"))
        else:
            note_failure(ip)
            changed("login:failed", f"{name}, {ip}" if name else ip)
            flash(t("login.wrong"), "bad")
    return render_template("login.html", disabled=False, name=name)


@app.route(BASE + "/logout", methods=["POST"])
def logout():
    # The cookie may have been copied: this sign-in no longer counts anywhere.
    session_end(session.get("sid"))
    session.clear()
    changed("logout:", client_ip())
    flash(t("login.signed_out"), "ok")
    return redirect(url_for("login"))
