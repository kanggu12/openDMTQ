"""Tests for backups and restores: what an archive holds and who can read it, what a restore keeps,
and that the server stops and comes back."""

import io
import json
import os
import re
import sqlite3
import stat
import tarfile
import tempfile
import unittest
from unittest import mock

from opendmtq_cli import app, backup, keep_tokens

from .sandbox import REPO, Sandbox, done


# The sandbox replaces it (its archives hold a few bytes for a database); the real one, for the tests of it.
REAL_DATABASE_PROBLEM = backup.database_problem
tempfile_folder = tempfile.TemporaryDirectory


def thirty(sb):
    """Thirty archives, as many as are kept; returns their names, oldest first."""
    return [sb.archive(f"data/backups/opendmtq-202601{i:02d}-120000-manual.tar.gz", {"dmtq.db3": f"old {i}".encode()})
            for i in range(1, 31)]


# The table of the highest player number handed out, as the game server makes it (server/game/src/account.php,
# OPENDMTQ_NUMBER_TABLE), for the tests' databases.
NUMBER_TABLE = "CREATE TABLE IF NOT EXISTS MemberNumber (last INTEGER NOT NULL)"


def put_back_said(why_not=None):
    """The tools container's `songs put-back` when done, as it prints it (tools/opendmtq_tools/songs.py, main()): the songs
    back, and their song list made, or why not."""
    said = {"put_back": "/in/custom", "rebuilt": why_not is None, "why_not": why_not}
    return done(0, json.dumps(said) + "\n")


class CreateTest(unittest.TestCase):
    def test_reports_the_archive_when_songs_were_added(self):
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"db")
            sb.write("data/custom/ids.json", "{}")
            self.assertEqual(sb.call(app.cmd_backup), 0, sb.output())
            # Named for what it is, in the release's files' order and in lower case (API-42, DEP-57).
            self.assertRegex(sb.output(), r"backup data/backups/opendmtq-server-backup-\d{8}-\d{6}-manual\.tar\.gz")

    def test_the_newest_are_kept_whichever_way_they_are_named(self):
        # Thirty named before 0.11.0, then one named now: the oldest old one goes, never the new one, whatever the
        # names' order letter by letter.
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"db")
            names = thirty(sb)
            path = backup.create("manual")
            kept = sb.backups()
            self.assertIn(os.path.basename(path), kept)
            self.assertNotIn(names[0], kept)
            self.assertIn(names[1], kept)

    def test_one_named_in_capitals_by_0_11_0s_first_builds_counts_by_its_time(self):
        # Thirty named before 0.11.0, the newest of them in capitals as 0.11.0's first builds named them, then one now:
        # the oldest goes, the one in capitals stays as one of the newest.
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"db")
            names = thirty(sb)
            capitals = sb.archive("data/backups/OpenDMTQ-Server-Backup-20260201-120000-manual.tar.gz", {"dmtq.db3": b"c"})
            backup.create("manual")
            kept = sb.backups()
            self.assertIn(capitals, kept)
            self.assertNotIn(names[0], kept)
            self.assertNotIn(names[1], kept)

    def test_a_disk_that_fills_up_leaves_no_half_archive(self):
        # Under the final name it would be listed as the newest backup and push a good one out.
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"db")
            with mock.patch("tarfile.TarFile.add", side_effect=OSError(28, "No space left on device")):
                with self.assertRaises(OSError):
                    backup.create("stop")
            self.assertEqual(os.listdir(os.path.join(sb.data, "backups")), [])

    def test_archive_and_its_folder_are_private(self):
        # Archives hold the signing key, its password and the passwords from .env.
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"db")
            # A folder from an earlier version, readable by everyone.
            os.makedirs(os.path.join(sb.data, "backups"), mode=0o755)
            path = backup.create("manual")
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o700)


class RealDatabaseTest(unittest.TestCase):
    """With real SQLite files, for what the file's side files and contents decide."""

    def database(self, path, rows=1):
        """A small game database; the connection is left open and in write-ahead mode."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        con = sqlite3.connect(path)
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA wal_autocheckpoint = 0")
        con.execute("CREATE TABLE Member (id)")
        con.execute("CREATE TABLE Play (pattern_id, user_id, score)")
        con.executemany("INSERT INTO Play VALUES (?, 1, 100)", [(i,) for i in range(rows)])
        con.commit()
        return con

    def test_a_stopped_server_left_commits_in_the_log(self):
        # A container's last handle is killed, not closed: recent scores are only in dmtq.db3-wal.
        with Sandbox() as sb:
            con = self.database(os.path.join(sb.data, "state", "dmtq.db3"), rows=5)
            self.assertTrue(os.path.getsize(backup.DB + "-wal") > 0)
            path = backup.create("stop")
            con.close()
            with tarfile.open(path) as tar:
                tar.extract("dmtq.db3", sb.root, filter="data")
            out = sqlite3.connect(os.path.join(sb.root, "dmtq.db3"))
            self.assertEqual(out.execute("SELECT COUNT(*) FROM Play").fetchone()[0], 5)
            out.close()

    def test_restore_removes_the_old_log(self):
        # Left there, SQLite would apply the old database's log to the restored file.
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            sb.write("data/state/dmtq.db3-wal", b"old log")
            sb.write("data/state/dmtq.db3-shm", b"old index")
            sb.write("data/state/dmtq.db3-journal", b"old journal")
            name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": b"old"})
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            self.assertEqual(sb.read("data/state/dmtq.db3"), b"old")
            for end in ("-wal", "-shm", "-journal"):
                self.assertFalse(os.path.exists(backup.DB + end), end)

    def with_tokens(self, con, *ids):
        """API tokens in a database, as the admin pages keep them (their ids only matter here)."""
        con.execute(keep_tokens.TOKEN_TABLE)
        con.executemany("INSERT INTO ApiToken (id, name, scope, hash, admin, owner, created_at) VALUES (?, 'n', 'read', 'h', 'admin', 1, 1)",
                        [(i,) for i in ids])
        con.commit()

    def archived(self, sb, tokens=None):
        """A backup archive of an older database, with these API tokens (None: from before their table)."""
        with tempfile_folder() as tmp:
            old = self.database(os.path.join(tmp, "old.db3"))
            if tokens is not None:
                self.with_tokens(old, *tokens)
            # Its last connection closed: everything is in the file itself.
            old.close()
            with open(os.path.join(tmp, "old.db3"), "rb") as f:
                content = f.read()
        return sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": content})

    def tokens_in(self, path):
        """The ids of the API tokens in a database."""
        con = sqlite3.connect(path)
        try:
            return sorted(r[0] for r in con.execute("SELECT id FROM ApiToken"))
        finally:
            con.close()

    def test_a_restore_keeps_todays_api_tokens(self):
        # A token revoked since the backup stays revoked, one made since keeps working: as the admin pages' restore does.
        with Sandbox() as sb:
            # Five plays now, against the backup's one.
            live = self.database(backup.DB, rows=5)
            # Made since, and still only in the live database's log: the newest is read from there.
            self.with_tokens(live, "made_since")
            name = self.archived(sb, tokens=["revoked_since"])
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            live.close()
            self.assertEqual(self.tokens_in(backup.DB), ["made_since"])
            self.assertEqual(sb.tokens_kept, 1)
            # The restored database itself, its plays, is the backup's.
            con = sqlite3.connect(backup.DB)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM Play").fetchone()[0], 1)
            con.close()
            # Nothing of the job is left beside the database.
            self.assertFalse(os.path.exists(os.path.join(sb.data, "state", ".restoring.db3")))

    def test_a_restore_keeps_todays_game_sign_ins(self):
        # A game signed in now goes on signing after the restore with the key its login gave it; the backup's sign-ins
        # sign nothing: as the admin pages' restore does.
        with Sandbox() as sb:
            live = self.database(backup.DB)
            for statement in keep_tokens.SIGN_IN_TABLE:
                live.execute(statement)
            live.execute("INSERT INTO SignIn (access, puid, at, key, guid) VALUES ('today', '7', 2, 'k2', 7)")
            live.commit()
            live.close()
            with tempfile_folder() as tmp:
                old = self.database(os.path.join(tmp, "old.db3"))
                # The backup's player 7, its account as the platform's login makes it (server/game/src/platform.php).
                self.with_players(old, ("7", "7"))
                for statement in keep_tokens.SIGN_IN_TABLE:
                    old.execute(statement)
                old.execute("INSERT INTO SignIn (access, puid, at, key, guid) VALUES ('from_the_backup', '7', 1, 'k1', 7)")
                old.commit()
                old.close()
                with open(os.path.join(tmp, "old.db3"), "rb") as f:
                    content = f.read()
            name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": content})
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            con = sqlite3.connect(backup.DB)
            self.assertEqual(con.execute("SELECT access, key, guid FROM SignIn").fetchall(), [("today", "k2", 7)])
            con.close()

    @staticmethod
    def with_players(con, *pairs):
        """Players in a game database as the game server makes them: (puid, guid) each, as text."""
        for column in ("guid", "puid"):
            con.execute(f"ALTER TABLE Member ADD COLUMN {column} TEXT")
        con.executemany("INSERT INTO Member (id, puid, guid) VALUES (?, ?, ?)", [(int(p), p, g) for p, g in pairs])
        con.commit()

    def test_a_restore_never_takes_the_highest_player_number_back(self):
        # As the admin pages' restore (CLI-96): the larger of today's highest number handed out and the backup's, the
        # table made for a backup from before it.
        for backup_last, today, want in ((9, 12, 12), (None, 12, 12), (20, 12, 20)):
            with Sandbox() as sb:
                live = self.database(backup.DB)
                live.execute(NUMBER_TABLE)
                live.execute("INSERT INTO MemberNumber (last) VALUES (?)", (today,))
                live.commit()
                live.close()
                with tempfile_folder() as tmp:
                    old = self.database(os.path.join(tmp, "old.db3"))
                    if backup_last is not None:
                        old.execute(NUMBER_TABLE)
                        old.execute("INSERT INTO MemberNumber (last) VALUES (?)", (backup_last,))
                        old.commit()
                    old.close()
                    with open(os.path.join(tmp, "old.db3"), "rb") as f:
                        content = f.read()
                name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": content})
                self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
                con = sqlite3.connect(backup.DB)
                self.assertEqual(con.execute("SELECT last FROM MemberNumber").fetchall(), [(want,)], (backup_last, today))
                con.close()

    def test_a_restore_keeps_only_the_sign_ins_of_players_the_backup_has(self):
        # As the admin pages' restore: a player of the backup's and an account of its not logged in yet stay; a player made
        # since (the server gives their number to the next new phone) and an account moved onto another player since
        # go (CLI-91; main kept every sign-in of now).
        with Sandbox() as sb:
            live = self.database(backup.DB)
            for statement in keep_tokens.SIGN_IN_TABLE:
                live.execute(statement)
            live.executemany("INSERT INTO SignIn (access, puid, at, key, guid) VALUES (?, ?, 2, ?, ?)",
                             [("player 7", "7", "k7", 7), ("account 9, no login yet", "9", None, None),
                              ("player 12", "12", "k12", 12), ("account 8 as player 7", "8", "k8", 7)])
            live.commit()
            live.close()
            with tempfile_folder() as tmp:
                old = self.database(os.path.join(tmp, "old.db3"))
                self.with_players(old, ("7", "7"), ("8", "8"), ("9", "9"))
                old.close()
                with open(os.path.join(tmp, "old.db3"), "rb") as f:
                    content = f.read()
            name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": content})
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            con = sqlite3.connect(backup.DB)
            self.assertEqual(sorted(r[0] for r in con.execute("SELECT access FROM SignIn")), ["account 9, no login yet", "player 7"])
            con.close()

    def test_a_backup_from_before_the_tokens_gets_their_table(self):
        with Sandbox() as sb:
            live = self.database(backup.DB)
            self.with_tokens(live, "today")
            live.close()
            name = self.archived(sb, tokens=None)
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            self.assertEqual(self.tokens_in(backup.DB), ["today"])

    def test_a_restore_on_a_new_machine_brings_no_tokens_back(self):
        # Nothing live to keep: the backup's tokens are not this server's tokens of now.
        with Sandbox() as sb:
            name = self.archived(sb, tokens=["from_the_backup"])
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            self.assertEqual(self.tokens_in(backup.DB), [])

    def with_accounts(self, con, *accounts):
        """Site accounts in a database, as the admin pages keep them: (ID, password hash) each."""
        con.execute(keep_tokens.ACCOUNT_TABLE)
        con.execute(keep_tokens.ACCOUNT_GUID)
        con.executemany("INSERT INTO SiteUser (name, pass, created_at, guid) VALUES (?, ?, 1, 7)", accounts)
        con.commit()

    def accounts_in(self, path):
        """The accounts of a database: (ID, password hash, guid) each."""
        con = sqlite3.connect(path)
        try:
            return sorted(con.execute("SELECT name, pass, guid FROM SiteUser").fetchall())
        finally:
            con.close()

    def test_a_restore_keeps_todays_accounts(self):
        # An account deleted since the backup stays deleted, a password changed since stays changed, one made since
        # stays: who may sign in is today's, as the admin pages' restore keeps it.
        with Sandbox() as sb:
            with tempfile_folder() as tmp:
                old = self.database(os.path.join(tmp, "old.db3"))
                self.with_accounts(old, ("deleted_since", "h1"), ("sena", "old password"))
                old.close()
                with open(os.path.join(tmp, "old.db3"), "rb") as f:
                    name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": f.read()})
            live = self.database(backup.DB, rows=5)
            self.with_accounts(live, ("sena", "new password"), ("made_since", "h2"))
            live.close()
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            self.assertEqual(self.accounts_in(backup.DB), [("made_since", "h2", 7), ("sena", "new password", 7)])
            self.assertEqual(sb.accounts_kept, 2)

    def test_a_server_with_no_account_yet_takes_the_backups(self):
        # A move to a new machine: nothing of its own to keep, and every player of the backup still signs in.
        with Sandbox() as sb:
            with tempfile_folder() as tmp:
                old = self.database(os.path.join(tmp, "old.db3"))
                self.with_accounts(old, ("sena", "h1"))
                old.close()
                with open(os.path.join(tmp, "old.db3"), "rb") as f:
                    name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": f.read()})
            live = self.database(backup.DB)
            self.with_accounts(live)
            live.close()
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            self.assertEqual(self.accounts_in(backup.DB), [("sena", "h1", 7)])
            self.assertIsNone(sb.accounts_kept)

    def test_the_accounts_table_is_the_one_the_server_makes(self):
        # Three copies of one statement, as for the tokens: the server's start, the admin pages, and this restore.
        def words(text):
            return " ".join(text.split())
        with open(os.path.join(REPO, "tools", "opendmtq_tools", "admin", "auth.py"), encoding="utf-8") as f:
            pages = f.read()
        with open(os.path.join(REPO, "server", "game", "bin", "setup-db.php"), encoding="utf-8") as f:
            server = re.search(r'\$db->exec\("(CREATE TABLE IF NOT EXISTS SiteUser .*?)"\);', f.read(), re.S).group(1)
        self.assertEqual(words(keep_tokens.ACCOUNT_TABLE), words(server))
        # The pages' own has the game player's column in it, which an older table gets added (ACCOUNT_GUID).
        made = re.search(r'ACCOUNT_TABLE = """(.*?)"""', pages, re.S).group(1)
        self.assertEqual(words(keep_tokens.ACCOUNT_TABLE)[:-1] + ", guid INTEGER)", words(made))
        self.assertIn(f'"{keep_tokens.ACCOUNT_GUID}"', pages)
        # The sign-out moment's column, which all three add to an older table in the same words.
        self.assertIn(f'"{keep_tokens.ACCOUNT_SIGNED_OUT}"', pages)
        with open(os.path.join(REPO, "server", "game", "bin", "setup-db.php"), encoding="utf-8") as f:
            self.assertIn(f"'{keep_tokens.ACCOUNT_SIGNED_OUT}'", f.read())
        self.assertIn(f"ACCOUNT_COLUMNS = {keep_tokens.ACCOUNT_COLUMNS!r}".replace("'", '"'), pages)

    def with_webhooks(self, con, *urls, queued=True):
        """Webhooks in a database, as the admin pages keep them, with what their loop knew and a message waiting for each."""
        for statement in keep_tokens.WEBHOOK_TABLES:
            con.execute(statement)
        con.executemany("INSERT INTO Webhook (url, kind, lang, events, made_at) VALUES (?, 'slack', 'en', 'maint_on', 1)", [(u,) for u in urls])
        if queued:
            con.execute("""INSERT INTO WebhookState (name, value) VALUES ('state', '{"gen": "old", "rev": 3, "cursor": 1, "air": {"7": {"began": 1, "rec": 1, "name": "Sena", "seen": 1}}}')""")
            con.execute("INSERT INTO WebhookTop (pattern_id, user_id, score) VALUES (11, 7, 900000)")
            con.executemany("INSERT INTO WebhookMessage (hook, key, kind, event, made_at, next_at) VALUES (?, ?, 'maint_on', '{}', 1, 1)",
                            [(i + 1, f"maint_on:{i}") for i in range(len(urls))])
        con.commit()

    def webhooks_in(self, path):
        """A database's webhooks by address, and how many rows its loop's state, chart #1s and queue hold."""
        con = sqlite3.connect(path)
        try:
            return (sorted(r[0] for r in con.execute("SELECT url FROM Webhook")),
                    [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("WebhookState", "WebhookTop", "WebhookMessage")])
        finally:
            con.close()

    def test_a_restore_keeps_todays_webhooks_and_sends_nothing_of_the_backups(self):
        # A webhook deleted since stays deleted, one added since stays; what the backup's loop knew (who was on air) and
        # had waiting goes, so that the restored database is looked at anew and nothing old is sent: as the admin pages'
        # restore does it.
        with Sandbox() as sb:
            with tempfile_folder() as tmp:
                old = self.database(os.path.join(tmp, "old.db3"))
                self.with_webhooks(old, "https://chat.example/hooks/deleted-since")
                old.close()
                with open(os.path.join(tmp, "old.db3"), "rb") as f:
                    name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": f.read()})
            live = self.database(backup.DB, rows=5)
            self.with_webhooks(live, "https://chat.example/hooks/added-since", queued=False)
            live.close()
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            self.assertEqual(self.webhooks_in(backup.DB), (["https://chat.example/hooks/added-since"], [0, 0, 0]))
            self.assertEqual(sb.webhooks_kept, 1)

    def backup_with_a_webhook(self, sb):
        """A backup whose database has a webhook, what its loop knew and a message waiting: the archive's name."""
        with tempfile_folder() as tmp:
            old = self.database(os.path.join(tmp, "old.db3"))
            self.with_webhooks(old, "https://chat.example/hooks/from-the-backup")
            old.close()
            with open(os.path.join(tmp, "old.db3"), "rb") as f:
                return sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": f.read()})

    def test_a_restore_on_a_server_with_players_and_no_webhooks_brings_none_back(self):
        # Every webhook deleted since on a server in use: none comes back, its chat hears nothing more from here.
        with Sandbox() as sb:
            name = self.backup_with_a_webhook(sb)
            live = self.database(backup.DB)
            live.execute("INSERT INTO Member (id) VALUES (7)")
            live.commit()
            live.close()
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            self.assertEqual(self.webhooks_in(backup.DB), ([], [0, 0, 0]))
            self.assertEqual(sb.webhooks_kept, 0)

    def test_a_server_with_nothing_of_its_own_takes_the_backups_webhooks(self):
        # A move to a new machine (no webhook, account or player yet): the backup's webhooks come with it, as its accounts
        # do, and nothing it had waiting is sent (ADM-171; main dropped them).
        with Sandbox() as sb:
            name = self.backup_with_a_webhook(sb)
            self.database(backup.DB).close()
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            self.assertEqual(self.webhooks_in(backup.DB), (["https://chat.example/hooks/from-the-backup"], [0, 0, 0]))
            self.assertIsNone(sb.webhooks_kept)
        # Nothing at all yet (no database): the same.
        with Sandbox() as sb:
            name = self.backup_with_a_webhook(sb)
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            self.assertEqual(self.webhooks_in(backup.DB), (["https://chat.example/hooks/from-the-backup"], [0, 0, 0]))

    def test_the_webhooks_tables_are_the_ones_the_admin_pages_make(self):
        # Two copies of each statement: the admin pages' (webhooks.py, which makes them) and this restore's.
        def words(text):
            return " ".join(text.split())
        with open(os.path.join(REPO, "tools", "opendmtq_tools", "admin", "webhooks.py"), encoding="utf-8") as f:
            pages = f.read()
        made = [re.search(rf'{name} = """(.*?)"""', pages, re.S) or re.search(rf'{name} = "(.*?)"\n', pages, re.S)
                for name in ("HOOK_TABLE", "MESSAGE_TABLE", "STATE_TABLE", "TOP_TABLE")]
        self.assertEqual([words(t) for t in keep_tokens.WEBHOOK_TABLES], [words(m.group(1)) for m in made])
        self.assertIn(f"COLUMNS = {keep_tokens.WEBHOOK_COLUMNS!r}".replace("'", '"'), pages)

    def test_the_tokens_table_is_the_one_the_server_makes(self):
        # Three copies of one statement: the server's start, the admin pages, and this restore.
        def words(text):
            return " ".join(text.split())
        with open(os.path.join(REPO, "tools", "opendmtq_tools", "admin", "tokens.py"), encoding="utf-8") as f:
            pages = re.search(r'TOKEN_TABLE = """(.*?)"""', f.read(), re.S).group(1)
        with open(os.path.join(REPO, "server", "game", "bin", "setup-db.php"), encoding="utf-8") as f:
            server = re.search(r"\$db->exec\('(CREATE TABLE IF NOT EXISTS ApiToken .*?)'\);", f.read(), re.S).group(1)
        self.assertEqual(words(keep_tokens.TOKEN_TABLE), words(pages))
        self.assertEqual(words(keep_tokens.TOKEN_TABLE), words(server))

    def problem_of(self, content):
        with Sandbox() as sb:
            name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": content})
            return REAL_DATABASE_PROBLEM(os.path.join(sb.data, "backups", name))

    def test_what_a_restore_refuses(self):
        self.assertIn("cannot be read", self.problem_of(b"this is no database, and long enough to read as one"))
        with tempfile_folder() as tmp:
            con = sqlite3.connect(os.path.join(tmp, "other.db3"))
            con.execute("CREATE TABLE something (x)")
            con.commit()
            con.close()
            with open(os.path.join(tmp, "other.db3"), "rb") as f:
                self.assertIn("game database", self.problem_of(f.read()))

    def test_a_good_database_passes(self):
        with tempfile_folder() as tmp:
            self.database(os.path.join(tmp, "good.db3")).close()
            with open(os.path.join(tmp, "good.db3"), "rb") as f:
                self.assertIsNone(self.problem_of(f.read()))

    def test_an_archive_whose_bytes_changed_after_it_was_made_is_refused(self):
        # Read to its end before anything changes: its gzip check (a byte of it changed, or its second half gone) says the
        # archive is not the one that was made, which tar alone, stopping at its own end, never read (CLI-90; main restored
        # a changed one). The same archive as it was made passes.
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": b"the backup's database " * 300})
            path = os.path.join(sb.data, "backups", name)
            with open(path, "rb") as f:
                good = f.read()
            for what, data in (("its check", good[:-8] + bytes([good[-8] ^ 0xFF]) + good[-7:]),
                               ("its second half gone", good[: len(good) // 2])):
                with open(path, "wb") as f:
                    f.write(data)
                self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 1, what)
                self.assertIn(f"{name} cannot be restored: it changed or was cut short after it was made", sb.output(), what)
                self.assertEqual(sb.read("data/state/dmtq.db3"), b"current", what)
                self.assertEqual(sb.backups(), [name], what)
            with open(path, "wb") as f:
                f.write(good)
            self.assertIsNone(backup.changed_since_made(path))
            # A file that is no gzip stream at all is tar's to refuse, as before.
            with open(path, "wb") as f:
                f.write(b"not an archive")
            self.assertIsNone(backup.changed_since_made(path))

    def test_a_refused_archive_changes_nothing(self):
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": b"not a database"})
            with mock.patch.object(backup, "database_problem", REAL_DATABASE_PROBLEM):
                self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 1)
            self.assertEqual(sb.read("data/state/dmtq.db3"), b"current")
            self.assertEqual(sb.backups(), [name])


class PermissionTest(unittest.TestCase):
    def test_files_of_another_user_get_the_way_out_not_a_traceback(self):
        # data/ after a run with sudo, then ./opendmtq backup as a user.
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"db")
            with mock.patch("os.chmod", side_effect=PermissionError(13, "Permission denied", "data/backups")), \
                    mock.patch("sys.stdout", io.TextIOWrapper(io.BytesIO())):
                with self.assertRaises(SystemExit) as stop:
                    app.main(["backup"])
            self.assertEqual(stop.exception.code, 1)
            self.assertIn("sudo chown", sb.err.getvalue())


class RestoreTest(unittest.TestCase):
    def test_restoring_the_oldest_of_thirty_keeps_it(self):
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            names = thirty(sb)
            self.assertEqual(sb.call(app.cmd_restore, name=names[0], with_key=False), 0, sb.output())
            self.assertEqual(sb.read("data/state/dmtq.db3"), b"old 1")
            self.assertIn(names[0], sb.backups())

    def test_a_misspelt_name_changes_nothing(self):
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            names = thirty(sb)
            self.assertEqual(sb.call(app.cmd_restore, name="opendmtq-2026O101-120000-manual.tar.gz", with_key=False), 1)
            # No safety copy was needed, so none pushed the oldest out.
            self.assertEqual(sb.backups(), sorted(names))
            self.assertEqual(sb.read("data/state/dmtq.db3"), b"current")

    def test_on_a_fresh_clone(self):
        # Moving to a new machine: the archive was copied over and nothing has run yet.
        with Sandbox(env_text=None) as sb:
            name = sb.archive("moved/opendmtq-20260101-120000-manual.tar.gz",
                              {"dmtq.db3": b"old", "keystore/opendmtq.jks": b"old key"})
            self.assertFalse(os.path.exists(sb.data))
            self.assertEqual(sb.call(app.cmd_restore, name=sb.path("moved/" + name), with_key=True), 0, sb.output())
            self.assertEqual(sb.read("data/state/dmtq.db3"), b"old")
            self.assertEqual(sb.read("data/apk/keystore/opendmtq.jks"), b"old key")
            # No base APK yet: the first build (setup) signs with the restored key.
            self.assertNotIn("builder", [t[0] for t in sb.tool_calls])
            self.assertIn("setup", sb.output())

    def test_a_restored_key_rebuilds_the_app_the_server_offers(self):
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            sb.write("data/apk/base/client.apk", b"apk")
            sb.write("data/apk/keystore/opendmtq.jks", b"key made by setup")
            name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz",
                              {"dmtq.db3": b"old", "keystore/opendmtq.jks": b"old key"})
            sb.state = "running"
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=True), 0, sb.output())
            self.assertEqual(sb.read("data/apk/keystore/opendmtq.jks"), b"old key")
            # The builder rebuilds because the key changed; it is not forced.
            self.assertIn(("builder", (), {}), sb.tool_calls)
            self.assertEqual(sb.state, "running")

    def test_a_failed_rebuild_is_reported(self):
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            sb.write("data/apk/base/client.apk", b"apk")
            name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz",
                              {"dmtq.db3": b"old", "keystore/opendmtq.jks": b"old key"})
            sb.tools["builder"] = lambda args, extra: 1
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=True), 1)

    def test_a_server_that_does_not_come_back_is_reported(self):
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": b"old"})
            sb.state = "running"
            with mock.patch.object(app, "wait_healthy", return_value=None):
                self.assertNotEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0)
            self.assertIn("logs", sb.output())


class RestoreSongsTest(unittest.TestCase):
    """A backup's added songs, hidden flags and ids go back as the admin pages' restore puts them back: through the tools
    container's songs.put_back, which copies them and makes their song list in one go under the songs' lock. The command
    line copies none of them itself, where an add or a hide on the admin pages (up through a restore) could come between."""

    def archive_with_songs(self, sb):
        """A backup with an added song, hidden flags and ids, whose files and folders only their owner may read (as one
        from another server may have them); returns its file name."""
        path = sb.path("data/backups/opendmtq-20260101-120000-manual.tar.gz")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with tarfile.open(path, "w:gz") as tar:
            # The folders first, as an archive lists them, custom/ itself among them (create() always writes it).
            for folder in ("custom", "custom/songs", "custom/songs/1001"):
                info = tarfile.TarInfo(folder)
                info.type, info.mode = tarfile.DIRTYPE, 0o700
                tar.addfile(info)
            # Then the database and the songs' files.
            for name, data in (("dmtq.db3", b"old"), ("custom/songs/1001/song.json", b'{"song_id": 1001}'),
                               ("custom/hidden.json", b"[2]"), ("custom/ids.json", b'{"song": 1001}')):
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), 0o600
                tar.addfile(info, io.BytesIO(data))
        return os.path.basename(path)

    def test_the_songs_go_back_through_the_tools_container_and_are_not_copied_here(self):
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            # Today's songs: another added song, another hidden one.
            sb.write("data/custom/songs/1002/song.json", '{"song_id": 1002}')
            sb.write("data/custom/hidden.json", "[5]")
            name = self.archive_with_songs(sb)
            seen = {}

            def put_back(args, extra_env):
                """The container's job, looked at when it starts: what it is asked, and what it finds at /in."""
                folder = os.path.join(extra_env["IMPORT_FROM"], "custom")
                seen["args"], seen["from"] = args, extra_env["IMPORT_FROM"]
                # The mode of everything it would read, the folder itself as ".".
                paths = [folder] + [os.path.join(d, n) for d, dirs, files in os.walk(folder) for n in dirs + files]
                seen["modes"] = {os.path.relpath(p, folder): stat.S_IMODE(os.stat(p).st_mode) for p in paths}
                # Today's flags as they were: nothing copied them before the job.
                seen["today"] = sb.read("data/custom/hidden.json")
                # The database is the backup's already: the songs follow it.
                seen["database"] = sb.read("data/state/dmtq.db3")
                # What the module prints when it put them back and made their list.
                return put_back_said()

            sb.tools["songs"] = put_back
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            # Nothing to say about the songs: they are back with their list.
            self.assertNotIn("song list", sb.output())
            # One job, in the container that sees all of data/ (the importer's has no data/custom), asked to put back the
            # archive's custom/ as /in shows it: the archive unpacked under data/, where Docker can mount it from.
            self.assertEqual([call for call in sb.tool_services if call[0] == "songs"], [("songs", "tools")])
            self.assertEqual(seen["args"], ("put-back", "/in/custom"))
            self.assertEqual(os.path.dirname(seen["from"]), sb.data)
            # Every folder and file readable by the container's user, whoever unpacked them.
            self.assertEqual(seen["modes"], {".": 0o755, "songs": 0o755, "songs/1001": 0o755, "songs/1001/song.json": 0o644,
                                             "hidden.json": 0o644, "ids.json": 0o644})
            self.assertEqual(seen["today"], b"[5]")
            self.assertEqual(seen["database"], b"old")
            # And still today's after the restore: here (with the container's job only looked at) nothing copied them.
            self.assertEqual(sb.read("data/custom/hidden.json"), b"[5]")
            self.assertTrue(os.path.isfile(sb.path("data/custom/songs/1002/song.json")))
            self.assertFalse(os.path.exists(sb.path("data/custom/songs/1001")))
            # The unpacked archive goes once the restore is done.
            self.assertFalse(os.path.exists(seen["from"]))

    def test_songs_that_could_not_go_back_stop_the_restore_and_say_how_to_try_again(self):
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            name = self.archive_with_songs(sb)
            sb.state = "running"
            # put_back's copy failed in the container: it ends with 1 and its traceback.
            sb.tools["songs"] = lambda args, extra_env: done(1, "", "Traceback (most recent call last):\nshutil.Error: made up\n")
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 1)
            # The traceback is shown, then what to do.
            self.assertIn("shutil.Error: made up", sb.output())
            self.assertIn(f"could not be put back (see above); its database is restored. Restore it again: ./opendmtq restore {name}",
                          sb.output())
            # The server is started again all the same, on the backup's database.
            self.assertEqual(sb.state, "running")
            self.assertEqual(sb.read("data/state/dmtq.db3"), b"old")

    def test_a_tools_image_from_before_put_back_does_not_pass_for_a_restore_of_the_songs(self):
        # An image older than the command line (built before an update that found no internet to build again, or named in
        # .env) knows no put-back: it ignores the words, makes today's song list, and ends with 0.
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            name = self.archive_with_songs(sb)
            sb.tools["songs"] = lambda args, extra_env: done(0, '{"added": 1, "hidden": 1, "client_files": []}\n')
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 1)
            self.assertIn(f"the tools image is older than this command line and did not put the added songs in {name} back",
                          sb.output())
            self.assertIn(f"then restore again: ./opendmtq restore {name}", sb.output())
            # What the old module said, for whoever looks into it.
            self.assertIn('{"added": 1', sb.output())

    def test_a_song_list_that_could_not_be_made_is_said_and_the_restore_goes_through(self):
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            name = self.archive_with_songs(sb)
            sb.tools["songs"] = lambda args, extra_env: put_back_said(why_not="made up reason")
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            self.assertIn("the added songs are back, but their song list was not made anew (made up reason); ./opendmtq up makes it",
                          sb.output())

    def test_an_archive_outside_the_backups_folder_is_named_by_its_path_to_try_again(self):
        # A backup copied over from another PC and restored where it lies: `restore` finds it by its path alone.
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            name = self.archive_with_songs(sb)
            moved = sb.path("moved/" + name)
            os.renames(os.path.join(sb.data, "backups", name), moved)
            sb.tools["songs"] = lambda args, extra_env: 1
            self.assertEqual(sb.call(app.cmd_restore, name=moved, with_key=False), 1)
            self.assertIn(f"Restore it again: ./opendmtq restore {moved}", sb.output())

    def test_a_backup_without_the_custom_folder_leaves_todays_songs_alone(self):
        # A backup of a version from before added songs: it says nothing about them, so today's stay.
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"current")
            sb.write("data/custom/hidden.json", "[5]")
            name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": b"old"})
            self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            self.assertNotIn("songs", [call[0] for call in sb.tool_calls])
            self.assertEqual(sb.read("data/custom/hidden.json"), b"[5]")


class DownTest(unittest.TestCase):
    def test_stops_even_when_the_online_snapshot_fails(self):
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"db")
            sb.state = "running"
            # The server's 64 MB /tmp is too small for a large database.
            sb.programs[("docker", "exec")] = done(1, "", "disk I/O error")
            sb.call(app.cmd_down)
            self.assertIn(("down",), sb.compose_calls)
            self.assertIsNone(sb.state)
            self.assertEqual(len(sb.backups()), 1, sb.output())


if __name__ == "__main__":
    unittest.main()
