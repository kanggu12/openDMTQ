"""Tests for backups and restores: what an archive holds and who can read it, what a restore keeps,
and that the server stops and comes back."""

import io
import os
import sqlite3
import stat
import tarfile
import tempfile
import unittest
from unittest import mock

from opendmtq_cli import app, backup

from .sandbox import Sandbox, done


# The sandbox replaces it (its archives hold a few bytes for a database); the real one, for the tests of it.
REAL_DATABASE_PROBLEM = backup.database_problem
tempfile_folder = tempfile.TemporaryDirectory


def thirty(sb):
    """Thirty archives, as many as are kept; returns their names, oldest first."""
    return [sb.archive(f"data/backups/opendmtq-202601{i:02d}-120000-manual.tar.gz", {"dmtq.db3": f"old {i}".encode()})
            for i in range(1, 31)]


class CreateTest(unittest.TestCase):
    def test_reports_the_archive_when_songs_were_added(self):
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"db")
            sb.write("data/custom/ids.json", "{}")
            self.assertEqual(sb.call(app.cmd_backup), 0, sb.output())
            self.assertRegex(sb.output(), r"backup data/backups/opendmtq-\d{8}-\d{6}-manual\.tar\.gz")

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
