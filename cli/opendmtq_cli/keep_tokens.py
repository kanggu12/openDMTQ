"""The API's tokens kept across `./opendmtq restore`, as the admin pages' restore keeps them: the restored database gets
the server's tokens of now, and none of the backup's. An old backup must not bring back a token revoked since, nor end
one made since.

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


if __name__ == "__main__":
    # Said on the way, for the restore's log: how many tokens stay. Never the tokens themselves.
    print(f"API tokens kept: {keep(sys.argv[1], sys.argv[2])}")
