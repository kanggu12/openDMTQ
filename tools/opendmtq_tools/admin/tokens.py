"""The API's tokens (api.py): made on the Accounts page or through the API, each for the admin who made it, kept in the
server's database as a hash only. A token works while that admin may open these pages: the owner's (.env) while the pages
have a password, an account's while it is enabled with admin rights. Deleting the account deletes its tokens; a token
ends for good when it is revoked."""

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time

from flask import session

from . import auth, core
from .core import Refused, changed, db, t

# The table. The server makes it at start (server/game/bin/setup-db.php, the same statement); a database from before it
# (or restored from an older backup) gets it here, before every use. admin is the ID of who made it, owner 1 for the
# owner's account in .env, admin_since when that account was made: an account deleted and made again under the same ID is
# someone else, whose tokens these are not.
TOKEN_TABLE = """CREATE TABLE IF NOT EXISTS ApiToken (id TEXT PRIMARY KEY, name TEXT NOT NULL, scope TEXT NOT NULL,
                 hash TEXT NOT NULL, admin TEXT NOT NULL COLLATE NOCASE, owner INTEGER NOT NULL DEFAULT 0,
                 admin_since INTEGER, created_at INTEGER NOT NULL, used_at INTEGER)"""

# What a token may do: read only answers GET, write answers everything.
SCOPES = ("read", "write")

# A token as it is sent: odq_, the id that names it in lists (12 hex digits), _, then 32 random bytes (43 letters of
# base64url). Anything else is no token of ours and is refused before the database is asked.
SHAPE = re.compile(r"odq_([0-9a-f]{12})_([A-Za-z0-9_-]{43})")

# A token's name: what it is for, as the owner wrote it; as long as an account's note.
NAME_MAX = 40

# When a token was last used is written at most this often (seconds): a script that asks every second must not make
# every request a write to the database.
USED_EVERY = 60

# Held while a token is made or revoked, and by a restore from its look at today's tokens until the restored database is
# in place (backups.restore_backup): no token comes or goes in between, to be lost or brought back by it. Taken before
# the database, as the restore takes it.
LOCK = threading.RLock()

# The table's columns, in order, for copying its rows into another database (put).
COLUMNS = ("id", "name", "scope", "hash", "admin", "owner", "admin_since", "created_at", "used_at")


def token_table(con):
    """The tokens' table as it is now: made when there is none."""
    con.execute(TOKEN_TABLE)


def put(con, rows):
    """con's tokens made exactly rows (read from another database, all of the table's columns): the table made when that
    database has none, and whatever tokens it had gone. A restore gives the restored database today's tokens with it."""
    token_table(con)
    con.execute("DELETE FROM ApiToken")
    con.executemany(f"INSERT INTO ApiToken ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})",
                    [tuple(r[c] for c in COLUMNS) for r in rows])


def digest(token):
    """What the table keeps of a token: its SHA-256. The token itself is never stored, logged or shown again."""
    return hashlib.sha256(token.encode("ascii", "replace")).hexdigest()


def acting_admin():
    """Who makes a token on the Accounts page: (ID, owner, when the account was made) of the admin signed in."""
    who = str(session.get("who", ""))
    if session.get("stamp") == "owner":
        return who, True, None
    row = auth.account_find(who)
    return (row["name"], False, row["created_at"]) if row else (who, False, None)


def make(name, scope, admin):
    """A new token for admin ((ID, owner, since), as acting_admin() gives it): its row and the token itself, which only
    this answer has. Refused: a name that is empty or too long, a scope that is neither read nor write."""
    name = (name or "").strip()
    if not 1 <= len(name) <= NAME_MAX:
        raise Refused(400, "bad_name", t("tok.bad_name"))
    if scope not in SCOPES:
        raise Refused(400, "bad_scope", t("tok.bad_scope"))
    who, owner, since = admin
    # Not while a restore swaps the database (LOCK): the new token would be lost with the old database.
    with LOCK, db() as con:
        token_table(con)
        # A new id, whatever ids there are: twelve hex digits are many, but never two tokens with one.
        while True:
            token_id = secrets.token_hex(6)
            if not con.execute("SELECT 1 FROM ApiToken WHERE id = ?", (token_id,)).fetchone():
                break
        token = f"odq_{token_id}_{secrets.token_urlsafe(32)}"
        now = int(time.time())
        con.execute("INSERT INTO ApiToken (id, name, scope, hash, admin, owner, admin_since, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (token_id, name, scope, digest(token), who, 1 if owner else 0, since, now))
    # In the log of changes by its name: never the token.
    changed("accounts_page:token", name)
    row = {"id": token_id, "name": name, "scope": scope, "admin": who, "owner": bool(owner), "created_at": now, "used_at": None}
    return dict(row, works=works(row)), token


def works(row, account=False):
    """True while a token's admin may open these pages, as a sign-in's would (auth.signed_in): the owner's while the
    pages have a password, an account's while it is there, enabled, with admin rights, and the same account (made when the
    token's was). account: the admin's row when the caller has it already (False: looked up here)."""
    if row["owner"]:
        return bool(core.PASSWORD)
    if account is False:
        account = auth.account_find(row["admin"])
    return bool(account and account["admin"] and not account["off"] and account["created_at"] == row.get("admin_since"))


def listing():
    """Every token, newest first, with whether it works now: never its hash."""
    with db() as con:
        token_table(con)
        rows = [dict(r) for r in con.execute("SELECT id, name, scope, admin, owner, admin_since, created_at, used_at FROM ApiToken "
                                             "ORDER BY created_at DESC, id")]
        # Each admin's account once, for every token of theirs.
        auth.account_table(con)
        accounts = {r["name"].lower(): r for r in con.execute("SELECT name, admin, off, created_at FROM SiteUser")}
    for row in rows:
        row["owner"] = bool(row["owner"])
        row["works"] = works(row, accounts.get(row["admin"].lower()))
    return rows


def find(token_id):
    """One token's row as listing() has it, or None."""
    return next((row for row in listing() if row["id"] == token_id), None)


def revoke(token_id):
    """Ends a token for good: its name. Refused: there is no such token (revoked already, or never made)."""
    # Not while a restore swaps the database (LOCK): the old database would bring the token back.
    with LOCK, db() as con:
        token_table(con)
        row = con.execute("SELECT name FROM ApiToken WHERE id = ?", (str(token_id),)).fetchone()
        if not row:
            raise Refused(404, "token_not_found", t("tok.gone"))
        con.execute("DELETE FROM ApiToken WHERE id = ?", (str(token_id),))
    changed("accounts_page:revoke", row["name"])
    return row["name"]


def drop_for(con, name):
    """An account's tokens, gone with the account (in the same transaction): the ID may be given to someone else later."""
    token_table(con)
    con.execute("DELETE FROM ApiToken WHERE owner = 0 AND admin = ?", (name,))


def check(sent):
    """The token sent, looked up: its row (with works) when it is one of ours, None when it is not (malformed, unknown, or
    its secret wrong). The secret's hash is compared in constant time; the id alone finds the row."""
    m = SHAPE.fullmatch(sent or "")
    if not m:
        return None
    with db() as con:
        token_table(con)
        row = con.execute("SELECT id, name, scope, hash, admin, owner, admin_since, created_at, used_at FROM ApiToken WHERE id = ?",
                          (m.group(1),)).fetchone()
    if not row or not hmac.compare_digest(row["hash"], digest(sent)):
        return None
    row = {k: row[k] for k in row.keys() if k != "hash"}
    row["owner"] = bool(row["owner"])
    row["works"] = works(row)
    return row


def touch(row):
    """Notes that a token was used now, at most every USED_EVERY seconds. A database that is busy does not stop the
    request: the time is only for the list."""
    now = int(time.time())
    if row.get("used_at") and now - row["used_at"] < USED_EVERY:
        return
    try:
        with db() as con:
            con.execute("UPDATE ApiToken SET used_at = ? WHERE id = ?", (now, row["id"]))
    except sqlite3.OperationalError:
        pass
