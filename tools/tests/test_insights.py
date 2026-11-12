"""Tests for what the admin's status and log pages work out: the plays, the request log, the record of changes."""

import datetime
import importlib.util
import json
import os
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

# The admin package makes its Flask application as it is imported (admin/__init__.py), so this module needs Flask, not
# only markupsafe: both are in the tools image only.
HAVE_FLASK = importlib.util.find_spec("flask") is not None
if HAVE_FLASK:
    from opendmtq_tools.admin import insights

PHONE = "Dalvik/2.1.0 (Linux; U; Android 14)"
CHROME = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36"


def line(path="/opendmtq/", status=200, size="512", ua=CHROME, ip="10.0.0.5", when="02/Nov/2026:20:05:46 +0900", method="GET"):
    """A line as Apache's combined format writes it."""
    return f'{ip} - - [{when}] "{method} {path} HTTP/1.1" {status} {size} "-" "{ua}"'


def row(path="/opendmtq/", status=200, at=0.0, **fields):
    """A parsed request, at a given time."""
    parsed = insights.parse_line(line(path, status, **fields))
    parsed["at"] = at
    return parsed


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class RequestLogTest(unittest.TestCase):
    def test_a_line_is_read_whole(self):
        r = insights.parse_line(line("/apk?x=1", 206, "1048576", PHONE))
        self.assertEqual((r["ip"], r["method"], r["path"], r["status"], r["size"]), ("10.0.0.5", "GET", "/apk?x=1", 206, 1048576))
        self.assertEqual((r["kind"], r["device"]), ("app", "Game app"))
        self.assertEqual(r["time"], "11-02 20:05:46")

    def test_no_body_is_size_zero(self):
        self.assertEqual(insights.parse_line(line(size="-"))["size"], 0)

    def test_what_is_not_a_log_line_is_none(self):
        for bad in ("", "something else", '1.2.3.4 - - [not a date] "GET / HTTP/1.1" 200 1 "-" "-"'):
            self.assertIsNone(insights.parse_line(bad))

    def test_what_a_request_was_for(self):
        for path, kind in (("/DMQ/rpc", "game"), ("/api/accounts", "game"), ("/patch/x", "files"), ("/thumbs/a.jpg", "files"), ("/viewImg/eye/a.png", "files"),
                           ("/apk", "app"), ("/apk?t=1", "app"), ("/ca.crt", "app"), ("/live/upload", "live"), ("/opendmtq/live.php", "live"),
                           ("/admin/", "admin"), ("/opendmtq/admin/", "admin"), ("/opendmtq/admin/players", "admin"), ("/", "site"), ("/opendmtq/", "site"), ("/wp-login.php", "other")):
            self.assertEqual(insights.kind_of(path), kind, path)

    def test_what_kind_of_device(self):
        for ua, device in ((PHONE, "Game app"), ("-", "–"), ("", "–"), ("opendmtq", "Server check"), ("opendmtq-admin", "Admin pages"),
                           ("curl/8.0", "Script or bot"), ("python-requests/2", "Script or bot"), ("Python-urllib/3.12", "Script or bot"), (CHROME, "Chrome (Android)"),
                           ("Mozilla/5.0 (Windows NT 10.0) Chrome/130 Safari/537 Edg/130", "Edge (Windows)"), ("Mozilla/5.0 (iPhone) Safari/604", "Safari (iPhone)")):
            self.assertEqual(insights.device_of(ua), device, ua)

    def test_the_page_filters(self):
        fine, broken, script = row("/DMQ/rpc", 200), row("/DMQ/rpc", 500), row("/.env", 404)
        self.assertTrue(insights.wanted(fine))
        self.assertTrue(insights.wanted(broken, status="err"))
        self.assertFalse(insights.wanted(fine, status="err"))
        self.assertTrue(insights.wanted(script, status="4xx"))
        self.assertFalse(insights.wanted(script, status="5xx"))
        self.assertTrue(insights.wanted(fine, kind="game"))
        self.assertFalse(insights.wanted(script, kind="game"))
        self.assertTrue(insights.wanted(fine, q="DMQ/RPC"))
        self.assertFalse(insights.wanted(fine, q="nothing like this"))

    def test_a_script_looking_for_files_is_not_a_failure_of_the_server(self):
        # Half-way through an hour, so that all of these fall in the same one.
        now = 1_800_000_000 + 1800
        rows = [row("/.env", 404, now - 10), row("/DMQ/rpc", 404, now - 10), row("/opendmtq/", 500, now - 10), row("/opendmtq/", 200, now - 10),
                row("/opendmtq/", 200, now - 90000)]
        hours = insights.by_hour(rows, now=now)
        self.assertEqual(len(hours), 24)
        self.assertEqual(hours[-1][1:], (2, 2))
        self.assertEqual(sum(h[1] + h[2] for h in hours[:-1]), 0)

    def test_the_newest_two_log_files_are_read_and_health_checks_left_out(self):
        with tempfile.TemporaryDirectory() as folder:
            for name, age, text in (("access.log.2", 300, "oldest"), ("access.log", 200, "middle"), ("access.log.1", 100, "newest")):
                path = os.path.join(folder, name)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(line(f"/{text}") + "\n" + line("/opendmtq/health.php") + "\n")
                os.utime(path, (time.time() - age, time.time() - age))
            self.assertEqual([r["path"] for r in insights.read_log(folder)], ["/middle", "/newest"])

    def test_a_line_in_another_format_still_shows(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "access.log"), "w", encoding="utf-8") as f:
                f.write("a line of some older log\n")
            rows = insights.read_log(folder)
            self.assertEqual((rows[0]["path"], rows[0]["status"], rows[0]["kind"]), ("a line of some older log", 0, "other"))

    def test_no_log_yet(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(insights.read_log(folder), [])

    def test_a_connection_that_asked_for_nothing_is_no_request(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "access.log"), "w", encoding="utf-8") as f:
                f.write('172.29.0.1 - - [02/Nov/2026:10:00:00 +0900] "-" 408 - "-" "-"\n' + line("/opendmtq/") + "\n")
            self.assertEqual([r["path"] for r in insights.read_log(folder)], ["/opendmtq/"])

    def test_a_log_too_long_to_read_whole_says_so(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "access.log"), "w", encoding="utf-8") as f:
                f.write(line("/opendmtq/") + "\n")
            self.assertFalse(insights.read_log(folder).cut)
            with mock.patch.object(insights, "READ_BYTES", 10):
                self.assertTrue(insights.read_log(folder).cut)

    def test_a_log_followed_as_it_grows_reads_only_what_came_and_misses_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "access.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write(line("/one") + "\n" + line("/two") + "\n")
            self.assertEqual([r["path"] for r in insights.read_log(folder)], ["/one", "/two"])
            # A whole line and half of the next, as Apache may be writing it when the page looks.
            third, fourth = line("/three"), line("/four")
            with open(path, "a", encoding="utf-8") as f:
                f.write(third + "\n" + fourth[:20])
            self.assertEqual([r["path"] for r in insights.read_log(folder)], ["/one", "/two", "/three"])
            with open(path, "a", encoding="utf-8") as f:
                f.write(fourth[20:] + "\n")
            followed = [r["path"] for r in insights.read_log(folder)]
            # The same rows as a first look at the whole file.
            insights._tails.clear()
            self.assertEqual(followed, [r["path"] for r in insights.read_log(folder)])
            self.assertEqual(followed, ["/one", "/two", "/three", "/four"])

    def test_a_log_written_anew_is_read_anew(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "access.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write(line("/before") + "\n")
            insights.read_log(folder)
            # rotatelogs starts the same name over: other first bytes, and here a longer file than before.
            with open(path, "w", encoding="utf-8") as f:
                f.write(line("/after-a-long-while") + "\n" + line("/and-more") + "\n")
            self.assertEqual([r["path"] for r in insights.read_log(folder)], ["/after-a-long-while", "/and-more"])

    def test_what_people_asked_for_is_pages_not_what_pages_bring_along(self):
        rows = [{"path": p} for p in ("/opendmtq/style.css", "/opendmtq/fonts/a.woff2", "/opendmtq/song.php?id=1", "/opendmtq/song.php?id=2", "/opendmtq/")]
        self.assertEqual(insights.top_pages(rows), [("/opendmtq/song.php", 2), ("/opendmtq/", 1)])


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class ChangesTest(unittest.TestCase):
    def test_newest_first_and_a_broken_line_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            insights.audit_note(folder, "first:x", "a")
            with open(os.path.join(folder, "changes.log"), "a", encoding="utf-8") as f:
                f.write("not json\n")
            insights.audit_note(folder, "second:y", "b")
            self.assertEqual([c["what"] for c in insights.audit_read(folder)], ["second:y", "first:x"])

    def test_the_record_stays_small_however_long_it_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            target = "x" * 1000
            for i in range(int(3 * insights.AUDIT_MAX / 1000)):
                insights.audit_note(folder, f"change:{i}", target)
            size = sum(os.path.getsize(os.path.join(folder, name)) for name in os.listdir(folder))
            self.assertEqual(sorted(os.listdir(folder)), ["changes.log", "changes.log.1"])
            self.assertLess(size, 2 * insights.AUDIT_MAX + 4000)
            # The latest is there, and the list asked for stays its length.
            latest = insights.audit_read(folder, limit=5)
            self.assertEqual(len(latest), 5)
            self.assertEqual(latest[0]["what"], f"change:{int(3 * insights.AUDIT_MAX / 1000) - 1}")

    def test_a_disk_problem_does_not_stop_the_change(self):
        with tempfile.NamedTemporaryFile() as a_file:
            # A folder that cannot exist, under a file.
            insights.audit_note(os.path.join(a_file.name, "sub"), "change:x")
            self.assertEqual(insights.audit_read(os.path.join(a_file.name, "sub")), [])


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class PlaysTest(unittest.TestCase):
    NOW = datetime.datetime(2026, 11, 2, 20, 0).timestamp()
    # One row per player: the same shape as the admin's PLAYER_ROWS, with its one parameter.
    ROWS = "SELECT guid, nickname FROM Member WHERE udid IS NOT ?"

    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript("""CREATE TABLE Member (guid INTEGER, nickname TEXT, udid TEXT);
            CREATE TABLE Play (pattern_id INTEGER, user_id INTEGER, grade TEXT);
            CREATE TABLE PlayLog (user_id INTEGER, pattern_id INTEGER, played_at INTEGER);""")
        self.con.executemany("INSERT INTO Member VALUES (?, ?, ?)", [(1, "Sena", "a"), (2, " ", "b"), (3, "Check", "check")])

    def plays(self, *rows):
        self.con.executemany("INSERT INTO PlayLog VALUES (?, ?, ?)", rows)

    def test_every_day_is_there_even_with_no_plays(self):
        self.plays((1, 1, self.NOW - 60), (1, 1, self.NOW - 120), (1, 1, self.NOW - 2 * insights.DAY))
        days = insights.plays_by_day(self.con, days=5, now=self.NOW)
        self.assertEqual([n for _, n in days], [0, 0, 1, 0, 2])
        self.assertEqual(days[-1][0], datetime.date(2026, 11, 2))

    def test_when_people_play_by_weekday_and_hour(self):
        self.plays((1, 1, self.NOW - 60), (1, 1, self.NOW - 30 * insights.DAY))
        grid = insights.plays_by_hour(self.con, now=self.NOW)
        # 2 November 2026 is a Monday; 19:59 local.
        self.assertEqual(grid[0][19], 1)
        self.assertEqual(sum(map(sum, grid)), 1)

    def test_grades_in_their_order_only_those_there_are(self):
        self.con.executemany("INSERT INTO Play VALUES (?, ?, ?)", [(1, 1, "B"), (2, 1, "S"), (3, 1, "S"), (4, 1, None)])
        self.assertEqual(insights.grade_counts(self.con), [("S", 2), ("B", 1)])

    def test_who_plays_most_leaves_out_the_check_account_and_old_plays(self):
        self.plays((1, 1, self.NOW - 60), (1, 2, self.NOW - 60), (2, 1, self.NOW - 60), (3, 1, self.NOW - 60), (2, 1, self.NOW - 60 * insights.DAY))
        self.assertEqual(insights.top_players(self.con, self.ROWS, "check", now=self.NOW), [(1, "Sena", 2), (2, "", 1)])

    def test_charts_of_a_song_count_together(self):
        self.plays((1, 1, self.NOW - 60), (1, 2, self.NOW - 60), (1, 3, self.NOW - 60), (1, 99, self.NOW - 60))
        names = {1: ("One", "2L"), 2: ("One", "3L"), 3: ("Two", "2L")}
        self.assertEqual(insights.top_songs(self.con, names, now=self.NOW), [("One", 2), ("Two", 1)])

    def test_a_players_activity(self):
        self.plays((1, 1, self.NOW - 60), (1, 1, self.NOW - insights.DAY), (1, 1, self.NOW - 90 * insights.DAY))
        activity = insights.player_activity(self.con, days=3, now=self.NOW)
        self.assertEqual(activity[1]["recent"], 2)
        self.assertEqual(activity[1]["last"], self.NOW - 60)
        self.assertEqual(activity[1]["days"], [0, 1, 1])
        # Somebody nobody has seen.
        self.assertEqual(activity[42], {"last": None, "recent": 0, "days": [0, 0, 0]})

    def test_a_database_from_before_the_play_history(self):
        self.con.execute("DROP TABLE PlayLog")
        self.assertEqual(sum(n for _, n in insights.plays_by_day(self.con, days=3, now=self.NOW)), 0)
        self.assertEqual(sum(map(sum, insights.plays_by_hour(self.con, now=self.NOW))), 0)
        self.assertEqual(insights.top_players(self.con, self.ROWS, "check", now=self.NOW), [])
        self.assertEqual(insights.top_songs(self.con, {}, now=self.NOW), [])
        self.assertEqual(insights.player_activity(self.con, now=self.NOW)[1]["last"], None)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class FolderSizeTest(unittest.TestCase):
    def test_all_the_bytes_under_a_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, "a", "b"))
            for name, size in (("one", 10), (os.path.join("a", "b", "two"), 32)):
                with open(os.path.join(folder, name), "wb") as f:
                    f.write(b"x" * size)
            self.assertEqual(insights.folder_size(folder), 42)
            self.assertEqual(insights.folder_size(os.path.join(folder, "nothing")), 0)


if __name__ == "__main__":
    unittest.main()
