"""The API's tokens and the site's accounts kept across `./opendmtq restore`, as the admin pages' restore keeps them: the
restored database gets the server's tokens and accounts of now, and none of the backup's. An old backup must not bring
back a token revoked since, an account deleted since or an old password, nor end what was made since. A server with no
account yet (a new machine) takes the backup's accounts.

The restore runs this in the tools container, beside the database (backup.restore copies it there), before the restored
database takes the live one's place:

    python3 keep_tokens.py <the live database> <the restored database>

The standard library only, and Python 3.9 (the command line's oldest): the container runs it from the folder of the
restore, and the tests import it.
"""

import os
import sqlite3
import sys

# The table, as the server makes it (server/game/bin/setup-db.php, tools/opendmtq_tools/admin/tokens.py): for a restored
# database from before it.
TOKEN_TABLE = """CREATE TABLE IF NOT EXISTS ApiToken (id TEXT PRIMARY KEY, name TEXT NOT NULL, scope TEXT NOT NULL,
                 hash TEXT NOT NULL, admin TEXT NOT NULL COLLATE NOCASE, owner INTEGER NOT NULL DEFAULT 0,
                 admin_since INTEGER, created_at INTEGER NOT NULL, used_at INTEGER)"""

# Its columns, in order: what is copied of each token.
COLUMNS = ("id", "name", "scope", "hash", "admin", "owner", "admin_since", "created_at", "used_at")

# The accounts' table, as the server makes it (server/game/bin/setup-db.php, tools/opendmtq_tools/admin/auth.py), for a
# restored database from before it; the admin pages add the game player's column, guid, to it (ACCOUNT_GUID).
ACCOUNT_TABLE = """CREATE TABLE IF NOT EXISTS SiteUser (name TEXT PRIMARY KEY COLLATE NOCASE, pass TEXT NOT NULL,
                   note TEXT NOT NULL DEFAULT '', admin INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
                   signed_in_at INTEGER, off INTEGER NOT NULL DEFAULT 0)"""
ACCOUNT_GUID = "ALTER TABLE SiteUser ADD COLUMN guid INTEGER"

# What is copied of each account, as the admin pages' restore copies it (auth.ACCOUNT_COLUMNS there).
ACCOUNT_COLUMNS = ("name", "pass", "note", "admin", "created_at", "signed_in_at", "off", "guid")


def tokens_now(live):
    """The live database's tokens, as rows of COLUMNS. None when there are none to know of: no database yet (a new
    machine), one without the table, or one that cannot be read (damaged): the restored database then keeps none."""
    if not os.path.isfile(live):
        return None
    try:
        con = sqlite3.connect(live)
        try:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ApiToken'").fetchone():
                return None
            return con.execute(f"SELECT {', '.join(COLUMNS)} FROM ApiToken").fetchall()
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return None


def keep(live, restored):
    """Gives the restored database the live one's tokens, and only them: the table made when it has none. Returns how many
    were kept. A restored file that is no database is left as it is (the restore checked the archive already)."""
    rows = tokens_now(live) or []
    try:
        con = sqlite3.connect(restored)
    except sqlite3.Error:
        return 0
    try:
        with con:
            con.execute(TOKEN_TABLE)
            # The backup's own tokens go: a token's life is today's, whatever the backup held.
            con.execute("DELETE FROM ApiToken")
            con.executemany(f"INSERT INTO ApiToken ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})", rows)
    except sqlite3.DatabaseError:
        # No database to put them in (the restore's own checks stand before this): nothing to keep.
        return 0
    finally:
        con.close()
    return len(rows)


def accounts_now(live):
    """The live database's accounts, as dicts of their columns. None when there are none to keep: no database yet (a new
    machine), one without the table or without an account (a server not yet in use), or one that cannot be read
    (damaged): the restored database then keeps the backup's, or a move to a new machine would leave every player out."""
    if not os.path.isfile(live):
        return None
    try:
        con = sqlite3.connect(live)
        try:
            # The columns it has: a table made before the game player's column has no guid.
            have = [r[1] for r in con.execute("PRAGMA table_info(SiteUser)")]
            if not have:
                return None
            rows = con.execute(f"SELECT {', '.join(have)} FROM SiteUser").fetchall()
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return None
    return [dict(zip(have, r)) for r in rows] or None


def keep_accounts(live, restored):
    """Gives the restored database the live one's accounts, and only them: the table made when it has none, with the game
    player's column. Returns how many were kept, or None when the backup's stay (accounts_now)."""
    rows = accounts_now(live)
    if rows is None:
        return None
    try:
        con = sqlite3.connect(restored)
    except sqlite3.Error:
        return None
    try:
        with con:
            con.execute(ACCOUNT_TABLE)
            if "guid" not in {r[1] for r in con.execute("PRAGMA table_info(SiteUser)")}:
                con.execute(ACCOUNT_GUID)
            # The backup's own accounts go: who may sign in, and with which password, is today's.
            con.execute("DELETE FROM SiteUser")
            # Each account with the columns it came with: a live table without guid leaves it empty (not linked).
            con.executemany(f"INSERT INTO SiteUser ({', '.join(ACCOUNT_COLUMNS)}) VALUES ({', '.join('?' for _ in ACCOUNT_COLUMNS)})",
                            [tuple(r.get(c) for c in ACCOUNT_COLUMNS) for r in rows])
    except sqlite3.DatabaseError:
        # No database to put them in (the restore's own checks stand before this): nothing kept.
        return None
    finally:
        con.close()
    return len(rows)


def keep_all(live, restored):
    """Both, as the restore runs this file: (tokens kept, accounts kept or None when the backup's stay)."""
    return keep(live, restored), keep_accounts(live, restored)


if __name__ == "__main__":
    # Said on the way, for the restore's log: how many tokens and accounts stay. Never the tokens or passwords themselves.
    tokens, accounts = keep_all(sys.argv[1], sys.argv[2])
    print(f"API tokens kept: {tokens}")
    print("accounts: the backup's (this server has none)" if accounts is None else f"accounts kept: {accounts}")
