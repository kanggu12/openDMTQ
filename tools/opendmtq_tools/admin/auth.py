"""Who may come in: the sign-in with an ID and a password (the owner's from .env, or an account with admin rights), the
accounts' passwords, the CSRF token on every form and the throttle on failed sign-ins."""

import hashlib
import hmac
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


def client_ip():
    """The visitor's address. Through the game server, X-Real-IP: Apache sets it from the
    connection (the edge passes the visitor's address on) and overwrites whatever the client sent.
    On this service's own port the header is the client's own and is ignored."""
    sent = request.headers.get("X-Real-IP")
    if sent and request.remote_addr in server_addresses():
        return sent
    return request.remote_addr or "?"

# Sign-ins that are still valid (an id in each session cookie): signing out ends one for good, which
# a signed cookie alone cannot do. In memory, as the service runs one process; a restart signs
# everyone out.
_sessions = set()
_sessions_lock = threading.Lock()


def signed_in():
    sid = session.get("sid")
    with _sessions_lock:
        if not (session.get("ok") and sid in _sessions):
            return False
    # The owner's account lives in .env and lasts as long as the session. Any other admin's ends with their account,
    # their admin rights or their password, at the next page they open.
    if session.get("stamp") == "owner":
        return True
    row = account_find(session.get("who", ""))
    return bool(row and row["admin"] and not row["off"] and same_text(account_stamp(row["pass"]), session.get("stamp", "")))


def _account_ended():
    """The session itself is still good, but the account it is for is not (disabled, deleted, a new password, a restore)."""
    sid = session.get("sid")
    with _sessions_lock:
        return bool(session.get("ok") and sid in _sessions and session.get("stamp") != "owner")


def _prune(now):
    for ip in list(_failures):
        _failures[ip] = [t for t in _failures[ip] if now - t < WINDOW]
        if not _failures[ip]:
            del _failures[ip]
    _all_failures[:] = [t for t in _all_failures if now - t < WINDOW]


def throttled(ip):
    """True when this address, or everyone together, failed too often recently. The overall limit
    only counts for visits through the game server: on this service's own port (the server PC, by
    default) the owner is not locked out by guesses from the internet."""
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
    if "guid" not in {r[1] for r in con.execute("PRAGMA table_info(SiteUser)")}:
        con.execute("ALTER TABLE SiteUser ADD COLUMN guid INTEGER")


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
    return None


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
            flash(t("login.throttled"), "bad")
        elif who:
            session.clear()
            session.permanent = True
            sid = secrets.token_urlsafe(24)
            with _sessions_lock:
                _sessions.add(sid)
            session.update(ok=True, sid=sid, csrf=secrets.token_urlsafe(24), who=who[0], stamp=who[1])
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
    with _sessions_lock:
        _sessions.discard(session.get("sid"))
    session.clear()
    changed("logout:", client_ip())
    flash(t("login.signed_out"), "ok")
    return redirect(url_for("login"))
