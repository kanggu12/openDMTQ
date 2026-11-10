"""Tests for the admin pages: what the dashboard says about the builder's last run, and the copies of
the public site's stylesheet, fonts and icon kept for when the game server is down.

Flask is installed in the tools image only; outside it these tests are skipped (CI runs them there).
"""

import csv
import datetime
import errno
import hashlib
import importlib.util
import io
import json
import mimetypes
import os
import re
import sqlite3
import tarfile
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest import mock

HAVE_FLASK = importlib.util.find_spec("flask") is not None
if HAVE_FLASK:
    from opendmtq_tools import admin

HOST = "192.168.0.10"


class Install:
    """The folders the admin service works on, in a temporary folder, and a signed-in test client."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        for d in ("state", "apk/out", "backups", "custom"):
            os.makedirs(os.path.join(self.root, d))

    def path(self, rel):
        return os.path.join(self.root, rel)

    def write(self, rel, text):
        with open(self.path(rel), "w", encoding="utf-8") as f:
            f.write(text)

    def status(self, **fields):
        """data/apk/out/build.json as the builder writes it."""
        self.write("apk/out/build.json", json.dumps({"host": HOST, "time": int(time.time()), **fields}))

    def app_for(self, host):
        """An app the public page offers, built for host."""
        self.write("apk/out/OpenDMTQ-x.apk", "app")
        self.write("apk/out/latest.json", json.dumps({"file": "OpenDMTQ-x.apk", "host": host,
                                                      "built_at": "2026-11-01T08:00:00"}))

    def __enter__(self):
        self._patch = mock.patch.multiple(
            admin.core, DB=self.path("state/dmtq.db3"), APK=self.path("apk"), BACKUPS=self.path("backups"),
            PUBLIC_HOST=HOST, PASSWORD="pw", SETTINGS=self.path("state/admin-settings.json"),
            server_health=lambda fresh=False: None)
        self._patch.start()
        self._copies = mock.patch.object(admin.assets, "SITE_COPIES", self.path("state/admin-cache"))
        self._copies.start()
        self._songs = mock.patch.object(admin.songs, "CUSTOM", self.path("custom"))
        self._songs.start()
        self.client = admin.app.test_client()
        return self

    def sign_in(self):
        r = self.client.post("/opendmtq/admin/login", data={"name": "admin", "password": "pw"})
        assert r.status_code == 302, r.status_code

    def __exit__(self, *exc):
        self._songs.stop()
        self._copies.stop()
        self._patch.stop()
        # Copies kept in memory belong to this install only.
        admin.assets._css.clear()
        self._tmp.cleanup()
        return False


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")

class LogsPageTest(unittest.TestCase):
    def page(self, files):
        """The logs page over these files: name to (text, age in seconds)."""
        with Install() as inst, mock.patch.object(admin.core, "LOGS", inst.path("state")):
            now = time.time()
            for name, (text, age) in files.items():
                inst.write(f"state/{name}", text)
                os.utime(inst.path(f"state/{name}"), (now - age, now - age))
            inst.sign_in()
            return inst.client.get("/opendmtq/admin/logs").get_data(as_text=True)

    def test_a_small_file_keeps_its_first_line(self):
        self.assertIn("first-request", self.page({"access.log": ("first-request\n", 0)}))

    def test_the_file_being_written_can_be_any_of_the_three(self):
        # rotatelogs -n 3 goes on to access.log.1 when access.log is full: the page must not freeze at that point.
        page = self.page({"access.log": ("old-request\n", 100), "access.log.1": ("new-request\n", 0)})
        self.assertIn("new-request", page)
        self.assertIn("old-request", page)
        # In the list itself (the charts above it count them too).
        rows = page[page.index('id="log-rows"'):]
        self.assertLess(rows.index("new-request"), rows.index("old-request"))

    def test_the_oldest_file_is_left_out(self):
        # It is about to be overwritten, and the two newest are what the page has room for.
        page = self.page({"access.log": ("a-request\n", 50), "access.log.1": ("b-request\n", 0), "access.log.2": ("c-request\n", 100)})
        self.assertNotIn("c-request", page)

class BuildStatusTest(unittest.TestCase):
    def dashboard(self, inst):
        inst.sign_in()
        return inst.client.get("/opendmtq/admin/").get_data(as_text=True)

    def test_a_failed_rebuild_shows_with_the_app_phones_still_get(self):
        # The app for this address exists, but the last rebuild (a new patcher, base APK, runtime
        # bundle or key) failed: every ./opendmtq up stops on it, so the owner must see why.
        with Install() as inst:
            inst.app_for(HOST)
            inst.status(state="failed", error="smali ExternalSDK.smali: expected 1 match(es), found 0")
            page = self.dashboard(inst)
            self.assertIn("expected 1 match(es), found 0", page)
            self.assertIn("OpenDMTQ-x.apk", page)

    def test_a_build_cut_off_long_ago_counts_as_failed(self):
        # The portal tells players after fifteen minutes that the app could not be built; the owner's
        # page must not say only that none was built yet.
        with Install() as inst:
            inst.status(state="building", time=int(time.time()) - admin.apps.STALE_BUILD - 60)
            self.assertIn("stopped part-way", admin.apps.build_error())

    def test_a_build_under_way_is_no_failure(self):
        with Install() as inst:
            inst.status(state="building")
            self.assertIsNone(admin.apps.build_error())

    def test_another_address_is_not_this_one(self):
        with Install() as inst:
            inst.write("apk/out/build.json", json.dumps({"state": "failed", "host": "10.0.0.1", "error": "x"}))
            self.assertIsNone(admin.apps.build_error())

    def build_command(self, inst, host):
        """The command the App page starts for a build for host."""
        inst.sign_in()
        # The session cookie is for the admin pages' address only.
        with inst.client.session_transaction("/opendmtq/admin/") as session:
            csrf = session["csrf"]
        base = inst.path("apk/base")
        os.makedirs(base, exist_ok=True)
        inst.write("apk/base/client.apk", "apk")
        with mock.patch.object(admin.jobs, "start_job", return_value="job") as start:
            inst.client.post("/opendmtq/admin/app", data={"csrf": csrf, "host": host})
        return start.call_args[0][1]

    def test_a_build_for_this_address_goes_through_the_builder(self):
        # So that build.json tells its outcome: a failure shown above would otherwise stay after a
        # build made here succeeded.
        with Install() as inst:
            cmd = self.build_command(inst, HOST)
            self.assertIn("opendmtq_tools.builder", cmd)
            self.assertIn("--force", cmd)

    def test_a_build_for_another_address_keeps_the_public_app(self):
        with Install() as inst:
            cmd = self.build_command(inst, "friend.example.com")
            self.assertIn("opendmtq_tools.patch_apk", cmd)
            self.assertIn("--keep-latest", cmd)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class AppPageTest(unittest.TestCase):
    """The App page: the app players get, said once at the top, and every other build with why it is not that one."""

    @staticmethod
    def build(inst, name, host, when, offered=False):
        """A build as the patcher leaves one: the file and its manifest; the offered one is latest.json too."""
        inst.write(f"apk/out/{name}", "app")
        manifest = json.dumps({"file": name, "host": host, "built_at": when, "label": f"TECHNIKA Q ({host})"})
        inst.write(f"apk/out/{name}.json", manifest)
        if offered:
            inst.write("apk/out/latest.json", manifest)

    @staticmethod
    def page(inst):
        inst.sign_in()
        return inst.client.get("/opendmtq/admin/app").get_data(as_text=True)

    def test_no_app_yet_says_so_and_offers_a_build(self):
        with Install() as inst:
            page = self.page(inst)
            self.assertIn("No app yet. Build one for this server.", page)
            self.assertIn("No other builds.", page)
            # Nothing to download, and nothing to clear away.
            self.assertNotIn("/opendmtq/admin/app/download/", page)
            self.assertNotIn("/opendmtq/admin/app/prune", page)

    def test_the_offered_app_is_at_the_top_and_the_others_say_why_not(self):
        with Install() as inst:
            self.build(inst, "OpenDMTQ-old.apk", HOST, "2026-10-01T08:00:00")
            self.build(inst, "OpenDMTQ-friend.apk", "10.0.0.5:8080", "2026-10-15T08:00:00")
            self.build(inst, "OpenDMTQ-new.apk", HOST, "2026-11-01T08:00:00", offered=True)
            page = self.page(inst)
            top, others = page.split("Build for another address", 1)
            # At the top: the offered one, right for this server.
            self.assertIn("OpenDMTQ-new.apk", top)
            self.assertIn(f"Up to date for {HOST}", top)
            self.assertIn('class="lamp on"', top)
            self.assertNotIn("OpenDMTQ-old.apk", top)
            # Below: the two others, each with its reason, and the offered one not again.
            self.assertIn("Replaced by a newer build", others)
            self.assertIn("Another address <code>10.0.0.5:8080</code>", others)
            self.assertNotIn("OpenDMTQ-new.apk", others.split("</table>")[0])
            self.assertIn("/opendmtq/admin/app/prune", others)

    def test_a_build_under_way_is_followed_from_its_log_box(self):
        # admin.js (followJob) follows a job from what its log box says: no script of the page's own, which stopped for good
        # at the first look that failed on the network.
        with Install() as inst:
            self.build(inst, "OpenDMTQ-new.apk", HOST, "2026-11-01T08:00:00", offered=True)
            with admin.jobs._jobs_lock:
                admin.jobs._jobs["b1"] = {"id": "b1", "kind": "build", "state": "running", "log": [], "started": time.time()}
            try:
                inst.sign_in()
                page = inst.client.get("/opendmtq/admin/app?job=b1").get_data(as_text=True)
                self.assertIn('<pre class="log" id="log" data-job="/opendmtq/admin/jobs/b1" data-done="/opendmtq/admin/app?built=b1" '
                              'data-gone="/opendmtq/admin/app">', page)
                self.assertNotIn("fetch(", page)
                # Both build buttons wait for it, and say what they say again if it fails.
                self.assertEqual(re.findall(r'data-again data-label="([^"]*)" disabled', page), ["Build again", "Build"])
                # Signed out meanwhile, the page's own look gets a plain 401 (the page then reloads to the sign-in), not
                # the sign-in page to read as the job.
                inst.client.post("/opendmtq/admin/logout", data={"csrf": self.csrf(inst)})
                r = inst.client.get("/opendmtq/admin/jobs/b1", headers={"X-Requested-With": "fetch"})
                self.assertEqual(r.status_code, 401)
            finally:
                with admin.jobs._jobs_lock:
                    admin.jobs._jobs.pop("b1", None)

    def test_an_offered_app_for_another_address_is_a_problem_at_the_top(self):
        with Install() as inst:
            self.build(inst, "OpenDMTQ-moved.apk", "10.0.0.1", "2026-11-01T08:00:00", offered=True)
            page = self.page(inst)
            self.assertIn('class="lamp bad"', page)
            self.assertIn("Made for another address (10.0.0.1)", page)

    def test_a_failed_rebuild_shows_beside_the_app_players_still_get(self):
        with Install() as inst:
            self.build(inst, "OpenDMTQ-new.apk", HOST, "2026-11-01T08:00:00", offered=True)
            inst.status(state="failed", error="no base APK")
            page = self.page(inst)
            self.assertIn('class="lamp wait"', page)
            self.assertIn("The last build failed (no base APK). Players still get this one.", page)

    def test_the_installer_for_windows_shows_when_the_builder_kept_one(self):
        with Install() as inst:
            self.build(inst, "OpenDMTQ-new.apk", HOST, "2026-11-01T08:00:00", offered=True)
            # None kept yet: no line and no button, and its address answers 404.
            self.assertNotIn("/opendmtq/admin/app/windows", self.page(inst))
            self.assertEqual(inst.client.get("/opendmtq/admin/app/windows").status_code, 404)
            # A copy cut off (windows.json says another size) is not handed out.
            inst.write("apk/out/OpenDMTQ-Setup.exe", "MZ!")
            inst.write("apk/out/windows.json", json.dumps({"file": "OpenDMTQ-Setup.exe", "size": 4, "sha256": "0", "version": "0.8.0",
                                                           "copied_at": "2026-11-09T08:01:00"}))
            self.assertNotIn("/opendmtq/admin/app/windows", self.page(inst))
            self.assertEqual(inst.client.get("/opendmtq/admin/app/windows").status_code, 404)
            # The builder's: the line, the button, and the installer set up for this server.
            inst.write("apk/out/windows.json", json.dumps({"file": "OpenDMTQ-Setup.exe", "size": 3, "sha256": "0", "version": "0.8.0",
                                                           "copied_at": "2026-11-09T08:01:00"}))
            page = self.page(inst)
            self.assertIn("The site also offers the installer for Windows, set up for this server", page)
            self.assertIn("/opendmtq/admin/app/windows", page)
            r = inst.client.get("/opendmtq/admin/app/windows")
            self.assertEqual((r.status_code, r.mimetype), (200, "application/vnd.microsoft.portable-executable"))
            self.assertTrue(r.data.startswith(b"MZ!") and r.data.endswith(b"OPENDMTQ-PRESET1"))
            # Under a name that says which server it is for, and as long as it is.
            self.assertIn("OpenDMTQ-Setup-", r.headers["Content-Disposition"])
            self.assertEqual(int(r.headers["Content-Length"]), len(r.data))

    def test_over_https_the_installer_carries_the_address_with_its_port_and_the_servers_own_authority(self):
        ca = "-----BEGIN CERTIFICATE-----\nMIIBmadeup/+=\n-----END CERTIFICATE-----"
        with Install() as inst, tempfile.TemporaryDirectory() as https:
            self.build(inst, "OpenDMTQ-new.apk", HOST, "2026-11-01T08:00:00", offered=True)
            inst.write("apk/out/OpenDMTQ-Setup.exe", "MZ!")
            inst.write("apk/out/windows.json", json.dumps({"file": "OpenDMTQ-Setup.exe", "size": 3, "sha256": "0", "version": "0.8.0",
                                                           "copied_at": "2026-11-09T08:01:00"}))
            with open(os.path.join(https, "ca.crt"), "w", encoding="utf-8") as f:
                f.write(ca + "\n")
            # An internet address on port 80 whose server has HTTPS of its own.
            with mock.patch.object(admin.core, "PUBLIC_HOST", "game.example.net"), \
                    mock.patch.object(admin.core, "server_health", lambda fresh=False: {"ok": True, "https": True}), \
                    mock.patch.dict(os.environ, {"OPENDMTQ_HTTPS": https}):
                inst.sign_in()
                r = inst.client.get("/opendmtq/admin/app/windows")
                details = json.loads(r.data[3:-20].decode())
                self.assertEqual(details, {"version": 1, "url": "https://game.example.net:80", "name": "game.example.net", "ca": ca})
            # Over plain HTTP the authority stays out: there is nothing for it to vouch for.
            with mock.patch.object(admin.core, "PUBLIC_HOST", "game.example.net"), \
                    mock.patch.object(admin.core, "server_health", lambda fresh=False: {"ok": True, "https": False}), \
                    mock.patch.dict(os.environ, {"OPENDMTQ_HTTPS": https}):
                r = inst.client.get("/opendmtq/admin/app/windows")
                self.assertEqual(json.loads(r.data[3:-20].decode()), {"version": 1, "url": "http://game.example.net",
                                                                      "name": "game.example.net"})

    def test_the_icon_shows_only_when_the_builder_kept_one_and_only_signed_in(self):
        with Install() as inst:
            self.build(inst, "OpenDMTQ-new.apk", HOST, "2026-11-01T08:00:00", offered=True)
            self.assertNotIn("/opendmtq/admin/app/icon.png", self.page(inst))
            self.assertEqual(inst.client.get("/opendmtq/admin/app/icon.png").status_code, 404)
            inst.write("apk/out/app-icon.png", "png")
            self.assertIn("/opendmtq/admin/app/icon.png", self.page(inst))
            r = inst.client.get("/opendmtq/admin/app/icon.png")
            self.assertEqual((r.status_code, r.mimetype), (200, "image/png"))
            # Signed out, it is one more admin page: the sign-in first.
            inst.client.post("/opendmtq/admin/logout", data={"csrf": self.csrf(inst)})
            self.assertNotEqual(inst.client.get("/opendmtq/admin/app/icon.png").status_code, 200)

    @staticmethod
    def csrf(inst):
        with inst.client.session_transaction("/opendmtq/admin/") as session:
            return session["csrf"]


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class SiteCopiesTest(unittest.TestCase):
    """The admin pages' own port links the public site's stylesheet; the game server serves it."""

    def test_the_last_copy_serves_while_the_server_is_down(self):
        with Install() as inst:
            with mock.patch("urllib.request.urlopen", mock.mock_open(read_data=b"body { color: red }")):
                self.assertEqual(inst.client.get("/opendmtq/style.css").get_data(), b"body { color: red }")
            # A restart of this service forgets the copy in memory; the one on disk remains.
            admin.assets._css.clear()
            down = urllib.error.URLError("server is down")
            with mock.patch("urllib.request.urlopen", side_effect=down):
                self.assertEqual(inst.client.get("/opendmtq/style.css").get_data(), b"body { color: red }")

    def test_without_any_copy_the_own_stylesheet_serves(self):
        with Install() as inst, mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            r = inst.client.get("/opendmtq/style.css")
            self.assertEqual(r.status_code, 200)
            with open(admin.assets.FALLBACK_CSS, "rb") as f:
                self.assertEqual(r.get_data(), f.read())
            # A font has no stand-in, and nothing is written for a miss.
            self.assertEqual(inst.client.get("/opendmtq/fonts/dmtq-condensed-500.woff2").status_code, 404)
            self.assertFalse(os.path.exists(inst.path("state/admin-cache")))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class LiveSwitchTest(unittest.TestCase):
    """The owner's switch: what it leaves for the phone, and the video it removes."""

    def _switch(self, inst, *flips):
        """Flip the switch of player 7 in order; the row afterwards."""
        con = sqlite3.connect(inst.path("state/dmtq.db3"))
        con.row_factory = sqlite3.Row
        for on in flips:
            admin.recordings.live_set(con, 7, on)
        con.commit()
        row = con.execute("SELECT * FROM LiveSwitch WHERE guid = 7").fetchone()
        con.close()
        return row

    def _stream(self, inst, **fields):
        """A stream folder as the server leaves it."""
        folder = admin.recordings.live_folder(7)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "stream.json"), "w", encoding="utf-8") as f:
            json.dump({"ended": False, "updated": int(time.time()), **fields}, f)
        return folder

    def test_on_makes_a_key_and_a_notice(self):
        with Install() as inst:
            row = self._switch(inst, True)
            self.assertEqual((row["live"], row["toast"]), (1, "on"))
            self.assertEqual(len(row["token"]), 32)

    def test_each_switch_on_makes_a_new_key(self):
        with Install() as inst:
            first = self._switch(inst, True)["token"]
            self.assertNotEqual(self._switch(inst, False, True)["token"], first)

    def test_a_form_sent_twice_changes_nothing(self):
        with Install() as inst:
            first = self._switch(inst, True)["token"]
            self.assertEqual(self._switch(inst, True)["token"], first)

    def test_off_removes_the_key_and_the_video(self):
        with Install() as inst:
            self._switch(inst, True)
            folder = self._stream(inst)
            row = self._switch(inst, False)
            self.assertEqual((row["live"], row["token"]), (0, None))
            self.assertFalse(os.path.exists(folder))

    def test_a_notice_not_yet_read_is_taken_back(self):
        with Install() as inst:
            self.assertEqual(self._switch(inst, True, False)["toast"], "")

    def test_streaming_only_while_uploads_arrive(self):
        with Install() as inst:
            self.assertFalse(admin.recordings.live_streaming(7))
            self._stream(inst)
            self.assertTrue(admin.recordings.live_streaming(7))
            self._stream(inst, ended=True)
            self.assertFalse(admin.recordings.live_streaming(7))
            self._stream(inst, updated=int(time.time()) - admin.recordings.LIVE_LISTED - 1)
            self.assertFalse(admin.recordings.live_streaming(7))

    def test_a_database_without_the_table_has_nobody_live(self):
        with Install() as inst:
            con = sqlite3.connect(inst.path("state/dmtq.db3"))
            self.assertEqual(admin.recordings.live_rows(con), {})
            con.close()


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class BroadcastsTest(unittest.TestCase):
    """The server's broadcasts on the Broadcasts page: off until turned on, what turning them on and off does to the
    players' switches, their notices, the live windows and the recordings, and the settings the phones are asked for."""

    def _token(self, inst):
        inst.sign_in()
        # As a browser gets it: from a page's form.
        page = inst.client.get("/opendmtq/admin/recordings").get_data(as_text=True)
        return re.search(r'name="csrf" value="([^"]+)"', page).group(1)

    def _switched_on(self, inst, *guids):
        """Players switched on, as the Players page leaves them."""
        with sqlite3.connect(inst.path("state/dmtq.db3")) as con:
            con.row_factory = sqlite3.Row
            for guid in guids:
                admin.recordings.live_set(con, guid, True)

    def _settings(self, **values):
        """Broadcast settings as the owner left them (rows of LiveSetting), in a database made for it when there is none."""
        with sqlite3.connect(admin.core.DB) as con:
            admin.recordings.setting_rows(con)
            admin.recordings.write_settings(con, values)

    def _settings_off(self):
        """Broadcasts off as the owner left them."""
        self._settings(on=False)

    def _rows(self):
        """The settings' rows as they are in the database."""
        with sqlite3.connect(admin.core.DB) as con:
            return dict(con.execute("SELECT name, value FROM LiveSetting").fetchall())

    def _toasts(self, inst):
        """Each player's notice waiting for the phone."""
        with sqlite3.connect(inst.path("state/dmtq.db3")) as con:
            return dict(con.execute("SELECT guid, toast FROM LiveSwitch ORDER BY guid").fetchall())

    def test_off_until_turned_on_and_the_page_says_so(self):
        with Install() as inst:
            self.assertEqual(admin.recordings.live_settings(), {"on": False, "new_players": False, "quality": "standard"})
            self._token(inst)
            page = inst.client.get("/opendmtq/admin/recordings").get_data(as_text=True)
            self.assertIn("Broadcasts are off", page)
            self.assertIn('value="broadcasts-on"', page)
            # Every quality with what it costs, the one in use chosen.
            self.assertEqual(len(re.findall(r'name="quality"', page)), 4)
            self.assertIn('value="standard" checked', page)

    def test_live_default_on_is_what_new_players_start_with_until_the_owner_chooses(self):
        with Install(), mock.patch.dict(os.environ, {"LIVE_DEFAULT": "on"}):
            old_game_database(admin.core.DB, [])
            self.assertTrue(admin.recordings.live_settings()["new_players"])
            # The first look writes whether broadcasts are on, not what new players start with.
            self.assertEqual(self._rows(), {"on": "1"})
            # The owner's choice comes first once made.
            self._settings(new_players=False)
            self.assertFalse(admin.recordings.live_settings()["new_players"])

    def test_a_server_from_before_the_switch_stays_on_when_it_broadcast(self):
        with Install() as inst:
            # A player switched on before the switch existed: on, and written down in the database.
            self._switched_on(inst, 7)
            self.assertTrue(admin.recordings.live_settings()["on"])
            self.assertEqual(self._rows(), {"on": "1"})
        with Install() as inst:
            # Nobody switched on, no LIVE_DEFAULT: a new server, off; a player switched on later leaves it off.
            old_game_database(admin.core.DB, [])
            self.assertFalse(admin.recordings.live_settings()["on"])
            self._switched_on(inst, 7)
            self.assertFalse(admin.recordings.live_settings()["on"])
        with Install(), mock.patch.dict(os.environ, {"LIVE_DEFAULT": "on"}):
            # LIVE_DEFAULT=on is a server that broadcast too.
            old_game_database(admin.core.DB, [])
            self.assertTrue(admin.recordings.live_settings()["on"])
        with Install():
            # No database yet (before the server's first start): off, and nothing made.
            self.assertFalse(admin.recordings.live_settings()["on"])
            self.assertFalse(os.path.exists(admin.core.DB))

    def test_turning_on_tells_those_switched_on_and_off_takes_every_window_down(self):
        with Install() as inst:
            # The owner's settings exist and say off (a server from before the switch would be on with players on).
            self._settings_off()
            self._switched_on(inst, 7, 8)
            csrf = self._token(inst)
            r = inst.client.post("/opendmtq/admin/recordings", data={"csrf": csrf, "action": "broadcasts-on"}, follow_redirects=True)
            self.assertIn("Broadcasts are on.", r.get_data(as_text=True))
            self.assertTrue(admin.recordings.live_settings()["on"])
            # Each player switched on is told, once, between songs.
            self.assertEqual(self._toasts(inst), {7: "on", 8: "on"})
            # A live window and a recording running when broadcasts go off: the window goes, the recording is closed.
            folder = admin.recordings.live_folder(7)
            os.makedirs(folder, exist_ok=True)
            # Player 7 on air now: an upload a moment ago, not ended.
            with open(os.path.join(folder, "stream.json"), "w", encoding="utf-8") as f:
                json.dump({"ended": False, "updated": time.time()}, f)
            rec = admin.recordings.rec_folder(7, 1800000000)
            os.makedirs(rec)
            open(os.path.join(rec, ".open"), "w", encoding="utf-8").close()
            r = inst.client.post("/opendmtq/admin/recordings", data={"csrf": csrf, "action": "broadcasts-off"}, follow_redirects=True)
            self.assertIn("Broadcasts are off.", r.get_data(as_text=True))
            self.assertFalse(admin.recordings.live_settings()["on"])
            self.assertFalse(os.path.exists(folder))
            self.assertTrue(os.path.exists(os.path.join(rec, ".close-now")))
            # The player on air hears once that the broadcast ended and that broadcasts are off for now; no other notice
            # waits while broadcasts are off, and the switches stay.
            self.assertEqual(self._toasts(inst), {7: "end", 8: ""})
            with sqlite3.connect(inst.path("state/dmtq.db3")) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM LiveSwitch WHERE live = 1").fetchone()[0], 2)

    def test_the_settings_form_saves_both_and_refuses_a_quality_there_is_not(self):
        with Install() as inst:
            old_game_database(admin.core.DB, [])
            csrf = self._token(inst)
            inst.client.post("/opendmtq/admin/recordings", data={"csrf": csrf, "action": "settings", "new_players": "on", "quality": "sharp"})
            self.assertEqual(admin.recordings.live_settings(), {"on": False, "new_players": True, "quality": "sharp"})
            r = inst.client.post("/opendmtq/admin/recordings", data={"csrf": csrf, "action": "settings", "new_players": "off", "quality": "ultra"},
                                 follow_redirects=True)
            self.assertIn("No such quality.", r.get_data(as_text=True))
            self.assertEqual(admin.recordings.live_settings(), {"on": False, "new_players": True, "quality": "sharp"})
            # The change in the log of changes, in words, with what it set.
            page = inst.client.get("/opendmtq/admin/logs?tab=changes").get_data(as_text=True)
            self.assertIn("Changed the broadcast settings", page)
            self.assertIn("on, sharp", page)

    def test_the_players_page_and_the_status_page_say_when_broadcasts_are_off(self):
        with Install() as inst:
            old_game_database(admin.core.DB, [])
            member_rows(admin.core.DB, [(7, "Sena", "phone-a")])
            self._settings_off()
            self._switched_on(inst, 7)
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/players").get_data(as_text=True)
            self.assertIn("Broadcasts are off for the whole server", page)
            self.assertIn("Switched on", page)
            dash = inst.client.get("/opendmtq/admin/").get_data(as_text=True)
            self.assertIn("Broadcasts are off", dash)
            self._settings(on=True)
            page = inst.client.get("/opendmtq/admin/players").get_data(as_text=True)
            self.assertNotIn("Broadcasts are off for the whole server", page)
            self.assertIn("Waiting", page)

    def test_new_players_starting_on_leaves_everyone_there_as_they_are(self):
        with Install() as inst:
            old_game_database(admin.core.DB, [])
            member_rows(admin.core.DB, [(7, "Sena", "phone-a"), (8, "Yuna", "phone-b"), (9, "Check", admin.core.CHECK_UDID)])
            self._settings_off()
            # Player 8 has a row from song tracking only (no choice of the owner): as untouched as player 7.
            with sqlite3.connect(admin.core.DB) as con:
                admin.recordings.setting_rows(con)
                con.execute(admin.recordings.LIVE_TABLE)
                con.execute("INSERT INTO LiveSwitch (guid, playing) VALUES (8, 0)")
            csrf = self._token(inst)
            inst.client.post("/opendmtq/admin/recordings", data={"csrf": csrf, "action": "settings", "new_players": "on", "quality": "standard"})
            self.assertTrue(admin.recordings.live_settings()["new_players"])
            # Both count as chosen for now, off: the server switches on only those who come after. The check account
            # is no player.
            with sqlite3.connect(admin.core.DB) as con:
                rows = con.execute("SELECT guid, live, changed_at IS NOT NULL FROM LiveSwitch ORDER BY guid").fetchall()
            self.assertEqual(rows, [(7, 0, 1), (8, 0, 1)])
            # The same form again changes nobody's time: only the turn to "start on" marks them.
            with sqlite3.connect(admin.core.DB) as con:
                before = con.execute("SELECT guid, changed_at FROM LiveSwitch ORDER BY guid").fetchall()
            member_rows(admin.core.DB, [(10, "New", "phone-c")])
            inst.client.post("/opendmtq/admin/recordings", data={"csrf": csrf, "action": "settings", "new_players": "on", "quality": "sharp"})
            with sqlite3.connect(admin.core.DB) as con:
                self.assertEqual(con.execute("SELECT guid, changed_at FROM LiveSwitch ORDER BY guid").fetchall(), before)

    def test_the_qualities_are_the_servers(self):
        # LIVE_QUALITY in server/portal/live_lib.php, which serves them to the phones: the same names and numbers.
        with open(os.path.join(os.path.dirname(__file__), "..", "..", "server", "portal", "live_lib.php"), encoding="utf-8") as f:
            php = f.read()
        found = {m.group(1): {"height": int(m.group(2)), "fps": int(m.group(3)), "bitrate": int(m.group(4))}
                 for m in re.finditer(r"'(\w+)' => \['height' => (\d+), 'fps' => (\d+), 'bitrate' => (\d+)\]", php)}
        self.assertEqual(found, admin.recordings.LIVE_PRESETS)
        self.assertIn("const LIVE_QUALITY_DEFAULT = '%s';" % admin.recordings.QUALITY_DEFAULT, php)
        # A segment's length, which the API gives with each quality.
        self.assertIn("const LIVE_SEGMENT = %d;" % admin.recordings.SEGMENT, php)
        # Within what the phones' encoders take (arm32/src/live.cpp clamps to these).
        for q in admin.recordings.LIVE_PRESETS.values():
            self.assertTrue(5 <= q["fps"] <= 60 and 144 <= q["height"] <= 1080 and 100000 <= q["bitrate"] <= 20000000, q)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class RecordingsTest(unittest.TestCase):
    """What the admin does to recordings. The server closes them and keeps the limits (tests/live)."""

    def _rec(self, guid=7, rid=1800000000, opened=False):
        """A recording's folder as the server leaves it."""
        rec = admin.recordings.rec_folder(guid, rid)
        os.makedirs(rec)
        files = (("0.ts", "aa"), ("1.ts", "bbb"), ("index.m3u8", "#EXTM3U\n#EXTINF:2.000,\n0.ts\n#EXTINF:2.000,\n1.ts\n"),
                 ("meta.json", json.dumps({"started": rid, "ended": rid + 4, "duration_ms": 4000, "size": 5, "songs": []})))
        for name, text in files:
            with open(os.path.join(rec, name), "w", encoding="utf-8") as f:
                f.write(text)
        if opened:
            open(os.path.join(rec, ".open"), "w", encoding="utf-8").close()
            with open(os.path.join(rec, "segs.log"), "w", encoding="utf-8") as f:
                f.write("0 2000 0 2\n1 2500 0 3\n")
        return rec

    def _token(self, inst):
        inst.sign_in()
        # As a browser gets it: from a page's form.
        page = inst.client.get("/opendmtq/admin/recordings").get_data(as_text=True)
        return re.search(r'name="csrf" value="([^"]+)"', page).group(1)

    def test_limits_default_and_save(self):
        with Install():
            self.assertEqual(admin.recordings.rec_limits(), {"cap_gb": 20, "days": 30})
            admin.recordings.rec_save_limits(5.5, 7)
            self.assertEqual(admin.recordings.rec_limits(), {"cap_gb": 5.5, "days": 7})

    def test_nonsense_limits_are_refused(self):
        with Install() as inst:
            csrf = self._token(inst)
            for cap, days in (("-1", "30"), ("x", "30"), ("1", "0"), ("1", "1.5")):
                inst.client.post("/opendmtq/admin/recordings", data={"csrf": csrf, "action": "limits", "cap_gb": cap, "days": days})
                self.assertEqual(admin.recordings.rec_limits(), {"cap_gb": 20, "days": 30})

    def test_an_open_recording_counts_from_its_list_and_stays_when_deleted(self):
        with Install():
            rec = self._rec(opened=True)
            item = admin.recordings.rec_all()[0]
            self.assertEqual((item["open"], item["duration_ms"], item["size"]), (True, 4500, 5))
            self.assertFalse(admin.recordings.rec_remove(7, 1800000000))
            self.assertTrue(os.path.isdir(rec))

    def test_one_recording_and_one_players_are_read_on_their_own(self):
        with Install():
            self._rec(7, 1800000000)
            self._rec(7, 1800000200, opened=True)
            self._rec(8, 1800000100)
            # What the server never makes: a player's number with a leading zero, a file in place of a recording, and
            # the limits beside the players.
            os.makedirs(os.path.join(admin.recordings.rec_root(), "07", "1800000300"))
            with open(os.path.join(admin.recordings.rec_root(), "7", "1800000400"), "w", encoding="utf-8") as f:
                f.write("not a recording")
            admin.recordings.rec_save_limits(20, 30)
            every = admin.recordings.rec_all()
            # Newest first across the players, and the three recordings only.
            self.assertEqual([(r["guid"], r["id"]) for r in every], [(7, 1800000200), (8, 1800000100), (7, 1800000000)])
            # Each one read alone is what the whole list has for it, the open one's figures from its segments too.
            for r in every:
                self.assertEqual(admin.recordings.rec_item(r["guid"], r["id"]), r)
            # A player's own, in the same order.
            self.assertEqual(admin.recordings.rec_player(7), [r for r in every if r["guid"] == 7])
            # Nothing where there is no recording: none of that number, a file, a player without any.
            self.assertIsNone(admin.recordings.rec_item(7, 1))
            self.assertIsNone(admin.recordings.rec_item(7, 1800000400))
            self.assertEqual(admin.recordings.rec_player(9), [])

    def test_switching_a_player_off_reads_their_recordings_only(self):
        # The switch is flipped inside a write to the database, which the game's saves wait for: nobody else's
        # recordings are read meanwhile.
        with Install() as inst:
            mine = self._rec(7, 1800000000, opened=True)
            theirs = self._rec(8, 1800000100, opened=True)
            con = sqlite3.connect(inst.path("state/dmtq.db3"))
            con.row_factory = sqlite3.Row
            admin.recordings.live_set(con, 7, True)
            with mock.patch.object(admin.recordings, "rec_all", side_effect=AssertionError("every recording was read")):
                admin.recordings.live_set(con, 7, False)
            con.close()
            # Theirs is asked to close; the other player's, still on air, is not.
            self.assertTrue(os.path.exists(os.path.join(mine, ".close-now")))
            self.assertFalse(os.path.exists(os.path.join(theirs, ".close-now")))

    def test_delete_all_is_the_shared_action(self):
        # The page's "Delete all" and the API's {"player": n} are one function (the API's side: test_api.py).
        with Install() as inst:
            self._rec(7, 1800000000)
            self._rec(7, 1800000200, opened=True)
            self._rec(8, 1800000100)
            csrf = self._token(inst)
            with mock.patch.object(admin.recordings, "rec_delete_player", wraps=admin.recordings.rec_delete_player) as action:
                page = inst.client.post("/opendmtq/admin/recordings", data={"csrf": csrf, "action": "delete-player 7"},
                                        follow_redirects=True).get_data(as_text=True)
                # A number the server would not make names nobody, and does not reach it.
                inst.client.post("/opendmtq/admin/recordings", data={"csrf": csrf, "action": "delete-player 07"})
            action.assert_called_once_with(7)
            # The closed one went, the one being made stayed, and the page says both.
            self.assertEqual([(r["guid"], r["id"]) for r in admin.recordings.rec_all()], [(7, 1800000200), (8, 1800000100)])
            self.assertIn("Recordings deleted: 1.", page)
            self.assertIn("1 still recording, kept.", page)

    def test_switching_off_keeps_the_recording_and_asks_to_close_it(self):
        with Install() as inst:
            con = sqlite3.connect(inst.path("state/dmtq.db3"))
            con.row_factory = sqlite3.Row
            admin.recordings.live_set(con, 7, True)
            rec = self._rec(opened=True)
            admin.recordings.live_set(con, 7, False)
            con.close()
            self.assertTrue(os.path.exists(os.path.join(rec, ".close-now")))
            self.assertTrue(os.path.exists(os.path.join(rec, "0.ts")))

    def test_download_is_the_segments_in_order(self):
        with Install() as inst:
            self._rec()
            inst.sign_in()
            r = inst.client.get("/opendmtq/admin/recordings/7/1800000000/download")
            self.assertEqual(r.get_data(), b"aabbb")
            self.assertEqual(r.headers["Content-Length"], "5")
            self.assertIn("opendmtq-player7-", r.headers["Content-Disposition"])

    def test_only_media_comes_out_and_only_signed_in(self):
        with Install() as inst:
            self._rec()
            self.assertEqual(inst.client.get("/opendmtq/admin/recordings/7/1800000000/0.ts").status_code, 302)
            self.assertEqual(inst.client.get("/opendmtq/admin/recordings/7/1800000000/download").status_code, 302)
            inst.sign_in()
            self.assertEqual(inst.client.get("/opendmtq/admin/recordings/7/1800000000/0.ts").status_code, 200)
            for name in ("meta.json", "segs.log", ".open", "..%2f..%2f..%2fdmtq.db3"):
                self.assertEqual(inst.client.get(f"/opendmtq/admin/recordings/7/1800000000/{name}").status_code, 404, name)

    def test_hide_show_delete_and_junk_names(self):
        with Install() as inst:
            rec = self._rec()
            self._rec(rid=1800000100)
            csrf = self._token(inst)

            def post(**fields):
                return inst.client.post("/opendmtq/admin/recordings", data={"csrf": csrf, **fields})

            post(action="hide 7/1800000000")
            self.assertTrue(os.path.exists(os.path.join(rec, ".hidden")))
            post(action="show 7/1800000000")
            self.assertFalse(os.path.exists(os.path.join(rec, ".hidden")))
            post(action="delete ../../dmtq")
            post(action="delete", sel=["1/2/3", "x"])
            self.assertEqual(len(admin.recordings.rec_all()), 2)
            post(action="delete", sel=["7/1800000000"])
            self.assertEqual([r["id"] for r in admin.recordings.rec_all()], [1800000100])
            post(action="delete-player 7")
            self.assertEqual(admin.recordings.rec_all(), [])
            self.assertFalse(os.path.exists(os.path.dirname(rec)))

    def test_no_token_no_change(self):
        with Install() as inst:
            self._rec()
            inst.sign_in()
            inst.client.post("/opendmtq/admin/recordings", data={"action": "delete 7/1800000000"})
            self.assertEqual(len(admin.recordings.rec_all()), 1)

    def test_the_language_is_english_until_the_switch_is_pressed(self):
        with Install() as inst:
            client = inst.client
            # A Korean browser starts in English like every other.
            self.assertIn('<html lang="en"', client.get("/opendmtq/admin/login", headers={"Accept-Language": "ko-KR,ko;q=0.9"}).get_data(as_text=True))
            r = client.get("/opendmtq/admin/lang?to=ko&next=/opendmtq/admin/login")
            self.assertEqual((r.status_code, r.headers["Location"]), (303, "/opendmtq/admin/login"))
            korean = client.get("/opendmtq/admin/login", headers={"Accept-Language": "en"}).get_data(as_text=True)
            self.assertIn('<html lang="ko"', korean)
            self.assertIn("관리자 로그인", korean)
            # Nowhere but this service, and only a language there is.
            self.assertNotIn("example", client.get("/opendmtq/admin/lang?to=ko&next=https://example.com/").headers["Location"])
            self.assertNotIn("Set-Cookie", client.get("/opendmtq/admin/lang?to=fr&next=/opendmtq/admin/login").headers)

    def test_the_old_address_leads_to_the_new_one(self):
        # The pages' address until 2026-11 (/admin), in bookmarks and old links: the same page at /opendmtq/admin, with its
        # query, before any sign-in (a redirect shows nothing). A form's POST stays a POST (308), and only here: the new
        # address answers as before.
        with Install() as inst:
            client = inst.client
            for old, new in (("/admin", "/opendmtq/admin/"), ("/admin/", "/opendmtq/admin/"),
                             ("/admin/players?sort=total", "/opendmtq/admin/players?sort=total"), ("/admin/login", "/opendmtq/admin/login")):
                r = client.get(old)
                self.assertEqual((r.status_code, r.headers["Location"]), (308, new), old)
            r = client.post("/admin/login", data={"name": "admin", "password": "wrong"})
            self.assertEqual((r.status_code, r.headers["Location"]), (308, "/opendmtq/admin/login"))
            self.assertEqual(client.get("/opendmtq/admin/login").status_code, 200)

    def test_every_page_answers_in_korean(self):
        with Install() as inst:
            con = sqlite3.connect(inst.path("state/dmtq.db3"))
            con.execute("CREATE TABLE Member (id INTEGER, guid TEXT, nickname TEXT, udid TEXT)")
            con.execute("INSERT INTO Member VALUES (7, '7', 'Seven', 'x')")
            con.execute("CREATE TABLE Play (user_id INTEGER, pattern_id INTEGER, score INTEGER)")
            con.commit()
            con.close()
            inst.sign_in()
            inst.client.get("/opendmtq/admin/lang?to=ko")
            for path in ("/opendmtq/admin/", "/opendmtq/admin/app", "/opendmtq/admin/songs", "/opendmtq/admin/players", "/opendmtq/admin/recordings", "/opendmtq/admin/backups", "/opendmtq/admin/maintenance", "/opendmtq/admin/logs", "/opendmtq/admin/nope"):
                page = inst.client.get(path).get_data(as_text=True)
                self.assertIn('<html lang="ko"', page, path)
                self.assertIn("로그아웃", page, path)

    def test_the_app_name_is_the_address_as_set_or_server_name(self):
        with mock.patch.object(admin.core, "PUBLIC_HOST", "myhome.example.com:8790"), mock.patch.dict(os.environ, {"SERVER_NAME": ""}):
            self.assertEqual(admin.core.app_name(), "TECHNIKA Q (myhome.example.com:8790)")
        with mock.patch.object(admin.core, "PUBLIC_HOST", "192.168.0.10"), mock.patch.dict(os.environ, {"SERVER_NAME": ""}):
            self.assertEqual(admin.core.app_name(), "TECHNIKA Q (192.168.0.10)")
        with mock.patch.dict(os.environ, {"SERVER_NAME": " HAC "}):
            self.assertEqual(admin.core.app_name(), "TECHNIKA Q (HAC)")

    def test_a_long_app_name_breaks_only_between_whole_pieces(self):
        with mock.patch.object(admin.core, "PUBLIC_HOST", "myhome.example.com:8790"), mock.patch.dict(os.environ, {"SERVER_NAME": ""}):
            html = str(admin.core.app_name_html())
        self.assertIn("<span>myhome.</span><wbr><span>example.</span><wbr><span>com</span><wbr><span>:8790</span>", html)
        self.assertIn('class="app-name"', html)
        # A name of the operator's choosing goes in as text.
        self.assertIn("&lt;b&gt;", str(admin.core.app_name_html("TECHNIKA Q (<b>)")))

    def test_a_backup_holds_no_recording(self):
        with Install() as inst:
            self._rec()
            sqlite3.connect(inst.path("state/dmtq.db3")).close()
            name = admin.backups.make_backup("test")
            with tarfile.open(inst.path(f"backups/{name}")) as tar:
                self.assertFalse([n for n in tar.getnames() if "live" in n or n.endswith(".ts")])


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class OverLimitUploadTest(unittest.TestCase):
    def post_too_large(self, inst, path):
        """An upload over the limit with its token, as a browser that skips the page's check sends it."""
        inst.sign_in()
        inst.client.get(path)
        with inst.client.session_transaction(path="/opendmtq/admin/") as sess:
            token = sess["csrf"]
        body = (b"--x\r\nContent-Disposition: form-data; name=\"csrf\"\r\n\r\n" + token.encode()
                + b"\r\n--x\r\nContent-Disposition: form-data; name=\"package\"; filename=\"a.zip\"\r\n\r\n" + bytes(4096) + b"\r\n--x--\r\n")
        stream = io.BytesIO(body)
        with mock.patch.object(admin.songs, "MAX_PACKAGE", 1024):
            response = inst.client.post(path, input_stream=stream, content_length=len(body),
                                        content_type="multipart/form-data; boundary=x")
        return response, stream

    def test_the_body_is_read_before_the_answer(self):
        # Answered with the body unread, gunicorn closes the connection while Apache is still sending
        # it, and the owner gets a 502 instead of the page that says why.
        with Install() as inst:
            response, stream = self.post_too_large(inst, "/opendmtq/admin/songs")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(stream.read(), b"", "the refused body was left unread")
            # Any page shows the message; this one needs no client data.
            self.assertIn("upload limit", inst.client.get("/opendmtq/admin/backups").get_data(as_text=True))


def old_game_database(path, rows):
    """A database as an older version backed it up: no play history, no later indexes, and rows that
    two saves at one moment made twice."""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE Member (id INTEGER, nickname TEXT, guid TEXT, puid TEXT, udid TEXT, code TEXT, "
                "slot_item1 INTEGER, slot_item2 INTEGER, slot_item3 INTEGER, slot_item4 INTEGER)")
    con.execute("CREATE TABLE Play (pattern_id INTEGER, user_id INTEGER, score INTEGER, grade TEXT, "
                "isAllCombo TEXT, isPerfectPlay TEXT, judgement INTEGER)")
    con.executemany("INSERT INTO Play VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class RestoreSchemaTest(unittest.TestCase):
    def restore(self, inst, rows):
        """Restores a backup of an older version's database on the admin page."""
        snap = inst.path("old.db3")
        old_game_database(snap, rows)
        with tarfile.open(inst.path("backups/opendmtq-20200101-000000-manual.tar.gz"), "w:gz") as tar:
            tar.add(snap, arcname="dmtq.db3")
        # The database being replaced, in the mode the server keeps it in.
        con = sqlite3.connect(admin.core.DB)
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("CREATE TABLE Member (id, nickname, guid, udid)")
        con.execute("CREATE TABLE Play (pattern_id, user_id, score)")
        con.close()
        inst.sign_in()
        inst.client.get("/opendmtq/admin/backups")
        with inst.client.session_transaction(path="/opendmtq/admin/") as sess:
            token = sess["csrf"]
        return inst.client.post("/opendmtq/admin/backups/opendmtq-20200101-000000-manual.tar.gz",
                                data={"csrf": token, "action": "restore"})

    def test_the_broadcast_settings_stay_as_they_are_today(self):
        # A backup made while broadcasts were on, at another quality: restored on the admin pages, the settings stay
        # today's, as the switches do. A restore never turns broadcasts on.
        with Install() as inst:
            snap = inst.path("old.db3")
            old_game_database(snap, [])
            with sqlite3.connect(snap) as con:
                admin.recordings.setting_rows(con)
                admin.recordings.write_settings(con, {"on": True, "quality": "light"})
            with tarfile.open(inst.path("backups/opendmtq-20200101-000000-manual.tar.gz"), "w:gz") as tar:
                tar.add(snap, arcname="dmtq.db3")
            old_game_database(admin.core.DB, [])
            with sqlite3.connect(admin.core.DB) as con:
                admin.recordings.setting_rows(con)
                admin.recordings.write_settings(con, {"on": False, "quality": "sharp"})
            inst.sign_in()
            inst.client.get("/opendmtq/admin/backups")
            with inst.client.session_transaction(path="/opendmtq/admin/") as sess:
                token = sess["csrf"]
            r = inst.client.post("/opendmtq/admin/backups/opendmtq-20200101-000000-manual.tar.gz",
                                 data={"csrf": token, "action": "restore"})
            self.assertEqual(r.status_code, 302)
            self.assertEqual(admin.recordings.live_settings(), {"on": False, "new_players": False, "quality": "sharp"})

    def test_an_older_backup_gets_what_the_server_needs(self):
        # The server keeps running, so what its start would add must not wait for a restart: plays
        # went unlogged, and duplicates stayed in every ranking's sum.
        with Install() as inst:
            self.restore(inst, [(1, 7, 100, "B", "N", "N", 800), (1, 7, 300, "A", "Y", "N", 900), (2, 7, 50, "C", "N", "N", 700)])
            con = sqlite3.connect(admin.core.DB)
            self.assertEqual(con.execute("SELECT pattern_id, score, grade, isAllCombo, judgement FROM Play ORDER BY 1").fetchall(),
                             [(1, 300, "A", "Y", 900), (2, 50, "C", "N", 700)])
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
            self.assertLessEqual({"PlayLog", "Play_one", "Play_board", "LiveSwitch", "LiveSetting", "AchievementDate"}, names)
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            con.close()


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class BackupFailureTest(unittest.TestCase):
    def test_a_failed_backup_is_said_on_the_page_and_leaves_no_archive(self):
        with Install() as inst:
            sqlite3.connect(admin.core.DB).close()
            inst.sign_in()
            inst.client.get("/opendmtq/admin/backups")
            with inst.client.session_transaction(path="/opendmtq/admin/") as sess:
                token = sess["csrf"]
            # The disk fills while the archive is written.
            with mock.patch.object(admin.backups.tarfile.TarFile, "add", side_effect=OSError(errno.ENOSPC, "No space left on device")):
                response = inst.client.post("/opendmtq/admin/backups", data={"csrf": token, "action": "create"})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(os.listdir(admin.core.BACKUPS), [])
            self.assertIn("the disk is full", inst.client.get("/opendmtq/admin/backups").get_data(as_text=True))



@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class ChangeLogPageTest(unittest.TestCase):
    """The log of what was changed in these pages: in words, under names."""

    def database(self, install):
        con = sqlite3.connect(install.path("state/dmtq.db3"))
        con.executescript("""CREATE TABLE Member (id INTEGER, nickname TEXT, guid TEXT, puid TEXT, udid TEXT, code TEXT,
                             slot_item1 INTEGER, slot_item2 INTEGER, slot_item3 INTEGER, slot_item4 INTEGER);
                             INSERT INTO Member (id, nickname, guid, udid) VALUES (7, 'Doyun', '7', 'a');""")
        con.close()

    def test_a_known_change_in_words_and_the_player_by_name(self):
        with Install() as install:
            self.database(install)
            # A line from before lines held names: the number is looked up.
            admin.insights.audit_note(install.path("state"), "player_action:live-on", "7", named=False)
            install.sign_in()
            page = install.client.get("/opendmtq/admin/logs?tab=changes").get_data(as_text=True)
            self.assertIn("Turned broadcasting on", page)
            self.assertIn("Doyun", page)
            self.assertNotIn("player_action", page)

    def test_the_same_in_korean(self):
        with Install() as install:
            self.database(install)
            admin.insights.audit_note(install.path("state"), "player_action:live-off", "7")
            install.sign_in()
            install.client.set_cookie("opendmtq_lang", "ko")
            self.assertIn("방송 끔", install.client.get("/opendmtq/admin/logs?tab=changes").get_data(as_text=True))

    def test_every_change_a_page_can_note_has_its_words(self):
        # The forms' actions in the templates, as note_changes() writes them under their pages.
        for what, key in admin.logs.CHANGE_WORDS.items():
            for lang in ("en", "ko"):
                self.assertIn(key, admin.strings.STRINGS[lang], what)
        templates = os.path.join(os.path.dirname(admin.__file__), "templates")
        pages = {"players.html": "player_action", "backups.html": "backups_page", "songs.html": "songs_page", "maintenance.html": "maintenance_page",
                 "recordings.html": "recordings_page"}
        for name, page in pages.items():
            with open(os.path.join(templates, name), encoding="utf-8") as f:
                for action in re.findall(r'name="action" value="([a-z-]+)[ "]', f.read()):
                    # On a saved backup, its own page.
                    owner = "backup_action" if page == "backups_page" and action in ("delete", "restore") else page
                    self.assertIn(f"{owner}:{action}", admin.logs.CHANGE_WORDS, name)

    def test_something_unknown_stays_as_it_was_written(self):
        with Install() as install:
            admin.insights.audit_note(install.path("state"), "new_page:new-thing", "name")
            install.sign_in()
            page = install.client.get("/opendmtq/admin/logs?tab=changes").get_data(as_text=True)
            self.assertIn("new_page:new-thing", page)
            self.assertIn("name", page)

    def test_a_target_that_is_not_a_number_does_not_stop_the_page(self):
        with Install() as install:
            self.database(install)
            admin.insights.audit_note(install.path("state"), "player_action:rename", "not a number")
            admin.insights.audit_note(install.path("state"), "songs_page:hide", "not a number")
            install.sign_in()
            self.assertEqual(install.client.get("/opendmtq/admin/logs?tab=changes").status_code, 200)

    def test_a_form_that_was_sent_is_noted_a_page_that_was_read_is_not(self):
        with Install() as install:
            install.sign_in()
            install.client.get("/opendmtq/admin/backups")
            self.assertEqual([c["what"] for c in admin.insights.audit_read(install.path("state"))], ["login:ok"])
            csrf = re.search(r'name="csrf" value="([^"]*)"', install.client.get("/opendmtq/admin/backups").get_data(as_text=True)).group(1)
            install.client.post("/opendmtq/admin/backups/auto", data={"csrf": csrf, "action": "on"})
            self.assertEqual([c["what"] for c in admin.insights.audit_read(install.path("state"))], ["backups_auto:on", "login:ok"])

    def test_what_did_not_happen_is_not_noted(self):
        with Install() as install:
            self.database(install)
            install.sign_in()
            csrf = re.search(r'name="csrf" value="([^"]*)"', install.client.get("/opendmtq/admin/backups").get_data(as_text=True)).group(1)
            state = install.path("state")
            def noted():
                return [c["what"] for c in admin.insights.audit_read(state) if not c["what"].startswith("log")]
            # A form from a page that has gone stale, a player or a backup that is not there, a file that is no backup.
            install.client.post("/opendmtq/admin/players/7", data={"csrf": "stale", "action": "delete", "seen": "x"})
            install.client.post("/opendmtq/admin/players/99", data={"csrf": csrf, "action": "delete", "seen": "x"})
            install.client.post("/opendmtq/admin/backups/nothing.tar.gz", data={"csrf": csrf, "action": "restore"})
            install.client.post("/opendmtq/admin/backups", data={"csrf": csrf, "action": "upload", "file": (io.BytesIO(b"no"), "x.tar.gz")}, content_type="multipart/form-data")
            # The same name again, and a song package that is none.
            with sqlite3.connect(install.path("state/dmtq.db3")) as con:
                seen = admin.players.player_seen(con, 7)
            install.client.post("/opendmtq/admin/players/7", data={"csrf": csrf, "action": "rename", "name": "Doyun", "seen": seen})
            install.client.post("/opendmtq/admin/songs", data={"csrf": csrf, "action": "upload", "package": (io.BytesIO(b"no"), "x.zip")}, content_type="multipart/form-data")
            self.assertEqual(noted(), [])

    def test_a_rename_keeps_both_names_after_the_next_one(self):
        with Install() as install:
            self.database(install)
            install.sign_in()
            csrf = re.search(r'name="csrf" value="([^"]*)"', install.client.get("/opendmtq/admin/backups").get_data(as_text=True)).group(1)
            with sqlite3.connect(install.path("state/dmtq.db3")) as con:
                seen = admin.players.player_seen(con, 7)
            install.client.post("/opendmtq/admin/players/7", data={"csrf": csrf, "action": "rename", "name": "Riku", "seen": seen})
            install.client.post("/opendmtq/admin/players/7", data={"csrf": csrf, "action": "rename", "name": "Sena", "seen": seen})
            page = install.client.get("/opendmtq/admin/logs?tab=changes").get_data(as_text=True)
            self.assertIn("Doyun → Riku", page)
            self.assertIn("Riku → Sena", page)

    def test_a_sign_in_and_a_failed_one_are_noted(self):
        with Install() as install:
            install.client.post("/opendmtq/admin/login", data={"name": "admin", "password": "wrong"})
            install.sign_in()
            page = install.client.get("/opendmtq/admin/logs?tab=changes").get_data(as_text=True)
            self.assertIn("Failed sign-in", page)
            self.assertIn("Signed in", page)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class InviteTest(unittest.TestCase):
    @staticmethod
    def message(install, name, **get):
        """The message to send with a new account, as the Accounts page shows it right after making it."""
        if not os.path.exists(admin.core.DB):
            old_game_database(admin.core.DB, [])
        csrf = page_token(install)
        install.client.post("/opendmtq/admin/accounts", data={"csrf": csrf, "action": "create", "name": name, "password": "", "note": ""}, **get)
        return install.client.get("/opendmtq/admin/accounts", **get).get_data(as_text=True)

    def test_the_message_has_the_address_friends_use_wherever_the_page_was_opened(self):
        with Install() as install:
            install.sign_in()
            # On the server PC by its own port, and through the server.
            for name, headers in (("friend1", {}), ("friend2", {"X-Forwarded-Host": HOST})):
                page = self.message(install, name, base_url="http://localhost:8791", headers=headers)
                self.assertIn(f"download the app (.apk): http://{HOST}/opendmtq/download.php", page, headers)
                self.assertIn(f"ID: {name}", page)
                self.assertNotIn("(.apk): http://localhost", page)
                self.assertNotIn("(.apk): /opendmtq", page)

    def test_the_message_says_https_where_the_site_is_on_it(self):
        with Install() as install, mock.patch.multiple(admin.core, PUBLIC_HOST="play.example.com:8790", server_health=lambda fresh=False: {"ok": True, "https": True}):
            install.sign_in()
            self.assertIn("(.apk): https://play.example.com:8790/opendmtq/download.php", self.message(install, "friend1"))
        # Not on a local address, where the server itself keeps visitors on plain HTTP.
        with Install() as install, mock.patch.multiple(admin.core, server_health=lambda fresh=False: {"ok": True, "https": True}):
            install.sign_in()
            self.assertIn(f"(.apk): http://{HOST}/", self.message(install, "friend1"))

    def test_with_the_server_down_the_page_offers_no_dead_link(self):
        with Install() as install:
            install.sign_in()
            page = install.client.get("/opendmtq/admin/", base_url="http://localhost:8791").get_data(as_text=True)
            self.assertNotIn('href="http://localhost/opendmtq/download.php"', page)
            self.assertNotIn("Players can get in", page)

    def test_the_owners_own_button_stays_on_the_address_in_use(self):
        with Install() as install, mock.patch.object(admin.core, "server_health", lambda fresh=False: {"ok": True}):
            # An app players can get: only then does the status page lead to its download page.
            install.app_for(HOST)
            install.sign_in()
            page = install.client.get("/opendmtq/admin/", base_url="http://localhost:8791").get_data(as_text=True)
            self.assertIn('href="http://localhost/opendmtq/download.php"', page)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class DeviceWordsTest(unittest.TestCase):
    def test_our_own_words_follow_the_language_product_names_do_not(self):
        with admin.app.test_request_context(headers={"Cookie": "opendmtq_lang=ko"}):
            self.assertEqual(str(admin.logs.device_words("Script or bot")), "스크립트 또는 봇")
            self.assertEqual(str(admin.logs.device_words("Chrome (Android)")), "Chrome (Android)")
        with admin.app.test_request_context():
            self.assertEqual(str(admin.logs.device_words("Game app")), "Game app")


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class AutoBackupTest(unittest.TestCase):
    NOW = 1_800_000_000

    def test_due_once_a_day_and_only_after_a_change(self):
        day = 86400
        for newest, changed, due in ((None, 0, True), (self.NOW - 100, self.NOW - 50, False), (self.NOW - day, self.NOW - 50, True),
                                     (self.NOW - day, self.NOW - 2 * day, False)):
            self.assertEqual(admin.backups.auto_backup_due(self.NOW, newest, changed), due, (newest, changed))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class PlayersFileTest(unittest.TestCase):
    def rows(self, name):
        return [{"id": 1, "nickname": name, "charts": 2, "total": 300}], {1: {"last": None, "recent": 0}}

    def test_a_name_is_never_read_as_a_formula(self):
        with admin.app.test_request_context():
            for name in ("=1+1", "+cmd", "-2", "@x"):
                body = admin.players.players_csv(*self.rows(name)).get_data(as_text=True)
                self.assertIn(f"1,\"'{name}\",2,300", body)

    def test_a_quote_in_a_name_stays_in_its_field(self):
        with admin.app.test_request_context():
            body = admin.players.players_csv(*self.rows('a"b')).get_data(as_text=True)
            self.assertIn('1,"a""b",2,300', body)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class SafetyTest(unittest.TestCase):
    """What the daily backup and the forms must not do to what is there."""

    def database(self, install, good=True):
        path = install.path("state/dmtq.db3")
        con = sqlite3.connect(path)
        con.executescript("""CREATE TABLE Member (id INTEGER, nickname TEXT, guid TEXT, puid TEXT, udid TEXT, code TEXT);
                             CREATE TABLE Play (pattern_id INTEGER, user_id INTEGER, score INTEGER, grade TEXT, isAllCombo TEXT, isPerfectPlay TEXT, judgement INTEGER);
                             CREATE TABLE PlayLog (id INTEGER PRIMARY KEY, user_id INTEGER, pattern_id INTEGER, score INTEGER, grade TEXT, judgement INTEGER, is_record INTEGER, played_at INTEGER);
                             INSERT INTO Member (id, nickname, guid, udid) VALUES (7, 'Doyun', '7', 'a');
                             INSERT INTO Play VALUES (1, 7, 100, 'S', 'N', 'N', 900);""")
        con.close()
        if not good:
            # Pages past the first turned to noise: the file still opens and copies, and is not a database any more.
            with open(path, "r+b") as f:
                f.seek(4096)
                f.write(b"\xff" * 4096)
        return path

    def test_a_damaged_database_does_not_become_a_backup(self):
        with Install() as install:
            self.database(install, good=False)
            with self.assertRaises(sqlite3.DatabaseError):
                admin.backups.make_backup("auto")
            self.assertEqual(os.listdir(install.path("backups")), [])

    def test_a_good_one_does_and_leaves_no_partial_file(self):
        with Install() as install:
            self.database(install)
            name = admin.backups.make_backup("admin")
            self.assertEqual(os.listdir(install.path("backups")), [name])

    def test_a_backup_cut_off_half_way_is_not_on_the_list(self):
        with Install() as install:
            self.database(install)
            with open(os.path.join(install.path("backups"), "opendmtq-20260101-000000-auto.tar.gz.part"), "wb") as f:
                f.write(b"half")
            self.assertEqual(admin.backups.backup_files(), [])

    def test_a_page_does_not_leave_an_empty_database_behind(self):
        with Install() as install:
            install.sign_in()
            install.client.get("/opendmtq/admin/players")
            self.assertFalse(os.path.exists(install.path("state/dmtq.db3")))

    def test_the_daily_backup_does_not_wait_for_a_visitor(self):
        self.assertIn("daily-backup", [thread.name for thread in threading.enumerate()])

    def test_a_reset_makes_a_backup_first(self):
        with Install() as install:
            self.database(install)
            install.sign_in()
            csrf = re.search(r'name="csrf" value="([^"]*)"', install.client.get("/opendmtq/admin/backups").get_data(as_text=True)).group(1)
            with sqlite3.connect(install.path("state/dmtq.db3")) as con:
                seen = admin.players.player_seen(con, 7)
            install.client.post("/opendmtq/admin/players/7", data={"csrf": csrf, "action": "reset", "seen": seen})
            self.assertTrue(any("-before-player-reset" in name for name in os.listdir(install.path("backups"))))
            with sqlite3.connect(install.path("state/dmtq.db3")) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM Play").fetchone()[0], 0)

    def test_a_reset_or_a_deletion_takes_the_players_achievements(self):
        # Stored achievements stay whatever the records say, so the records going must take them too: the player's
        # own rows, and nobody else's.
        for action in ("reset", "delete"):
            with Install() as install:
                self.database(install)
                with sqlite3.connect(install.path("state/dmtq.db3")) as con:
                    con.execute(admin.backups.ACHIEVEMENT_TABLE)
                    con.executemany("INSERT INTO AchievementDate VALUES (?, ?, ?)", [(7, 1, 1800000000), (7, 13, 1800000100), (8, 1, 1800000200)])
                    seen = admin.players.player_seen(con, 7)
                install.sign_in()
                csrf = re.search(r'name="csrf" value="([^"]*)"', install.client.get("/opendmtq/admin/backups").get_data(as_text=True)).group(1)
                install.client.post("/opendmtq/admin/players/7", data={"csrf": csrf, "action": action, "seen": seen})
                with sqlite3.connect(install.path("state/dmtq.db3")) as con:
                    self.assertEqual(con.execute("SELECT user_id, achievement_id FROM AchievementDate").fetchall(), [(8, 1)], action)

    def test_no_build_is_deleted_while_it_is_not_clear_which_is_on_offer(self):
        with Install() as install:
            install.sign_in()
            csrf = re.search(r'name="csrf" value="([^"]*)"', install.client.get("/opendmtq/admin/backups").get_data(as_text=True)).group(1)
            install.write("apk/out/OpenDMTQ-x.apk", "app")
            install.write("apk/out/latest.json", "{}")
            install.client.post("/opendmtq/admin/app/prune", data={"csrf": csrf})
            self.assertTrue(os.path.exists(install.path("apk/out/OpenDMTQ-x.apk")))

    def test_the_players_file_says_it_is_utf8(self):
        with Install() as install:
            self.database(install)
            install.sign_in()
            self.assertEqual(install.client.get("/opendmtq/admin/players?csv=1").data[:3], b"\xef\xbb\xbf")

    def test_every_pages_title_is_only_a_name(self):
        with Install() as install:
            self.database(install)
            install.sign_in()
            for page in ("players", "maintenance", "songs", "backups", "recordings", "app", "logs", ""):
                html = install.client.get(f"/opendmtq/admin/{page}").get_data(as_text=True)
                title = html.split("<title>", 1)[1].split("</title>", 1)[0]
                self.assertNotIn("<", title, page)
                self.assertLess(len(title), 60, page)

    def test_signing_out_is_said_as_what_went_well(self):
        with Install() as install:
            install.sign_in()
            csrf = re.search(r'name="csrf" value="([^"]*)"', install.client.get("/opendmtq/admin/backups").get_data(as_text=True)).group(1)
            page = install.client.post("/opendmtq/admin/logout", data={"csrf": csrf}, follow_redirects=True).get_data(as_text=True)
            self.assertIn('class="done"', page)
            self.assertNotIn('class="error"', page)

    def test_every_answer_forbids_frames_and_sniffing_and_keeps_its_address_home(self):
        # The values themselves, not the module's table: a change there must change this test too.
        wanted = {"X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin"}
        with Install() as install:
            client = install.client
            # Before signing in: the sign-in page, the way there from a page, a file of the pages, the API refusing.
            answers = {"sign-in page": client.get("/opendmtq/admin/login"), "redirect": client.get("/opendmtq/admin/"),
                       "static file": client.get("/opendmtq/admin/static/admin.js"),
                       "API": client.get("/opendmtq/api/v1/status")}
            install.sign_in()
            # Signed in: a page, and an address with nothing at it.
            answers["page"] = client.get("/opendmtq/admin/backups")
            answers["not found"] = client.get("/opendmtq/admin/nothing-here")
            for what, r in answers.items():
                # Closed once looked at: a file's answer holds the file open until then.
                with r:
                    for name, value in wanted.items():
                        # Once each: a second, different value would leave a browser to choose.
                        self.assertEqual(r.headers.getlist(name), [value], f"{what}: {name}")

    def test_the_pages_script_and_stylesheets_keep_their_types_whatever_the_system_says(self):
        # On Windows Python takes the types from the registry, where some programs make .js text/plain; under nosniff a
        # browser would not run admin.js. The same list here, as such a registry leaves it, then the service's own types.
        before = {ending: mimetypes.types_map.get(ending) for ending in (".js", ".css")}
        try:
            for ending in before:
                mimetypes.add_type("text/plain", ending)
            with Install() as install:
                # The mistake shows first: without the service's own types the script goes out as plain text.
                with install.client.get("/opendmtq/admin/static/admin.js") as r:
                    self.assertEqual(r.mimetype, "text/plain")
                # What the service does as it starts.
                admin.core.static_types()
                for name, kind in (("admin.js", "text/javascript"), ("admin.css", "text/css"), ("fallback.css", "text/css")):
                    with install.client.get(f"/opendmtq/admin/static/{name}") as r:
                        self.assertEqual(r.mimetype, kind, name)
        finally:
            # The list as it was, for the tests after this one.
            for ending, kind in before.items():
                mimetypes.add_type(kind, ending)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class PlayerMessageTest(unittest.TestCase):
    def act(self, inst, **form):
        inst.sign_in()
        inst.client.get("/opendmtq/admin/backups")
        with inst.client.session_transaction(path="/opendmtq/admin/") as sess:
            form["csrf"] = sess["csrf"]
        # What the form holds: who the page was loaded for.
        page = inst.client.get("/opendmtq/admin/players").get_data(as_text=True)
        form["seen"] = re.search(r'name="seen" value="([^"]+)"', page).group(1)
        inst.client.post("/opendmtq/admin/players/7", data=form)
        return inst.client.get("/opendmtq/admin/backups").get_data(as_text=True)

    def member(self, name):
        con = sqlite3.connect(admin.core.DB)
        con.execute("CREATE TABLE Member (id, nickname, guid, udid)")
        con.execute("CREATE TABLE Play (pattern_id, user_id, score)")
        con.execute("INSERT INTO Member VALUES (7, ?, '7', 'u')", (name,))
        con.commit()
        con.close()

    def test_messages_use_the_name(self):
        with Install() as inst:
            self.member("Sena")
            self.assertIn("Sena renamed to Yuna.", self.act(inst, action="rename", name="Yuna"))
        with Install() as inst:
            self.member("Sena")
            self.assertIn("Scores of Sena reset.", self.act(inst, action="reset"))
        with Install() as inst:
            self.member("Sena")
            self.assertIn("Sena deleted.", self.act(inst, action="delete"))

    def test_no_name_yet_says_the_number(self):
        with Install() as inst:
            self.member(" ")
            self.assertIn("Scores of Player 7 reset.", self.act(inst, action="reset"))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class VideoPlayerCopyTest(unittest.TestCase):
    def test_the_recordings_page_uses_no_other_site(self):
        with Install() as inst:
            inst.sign_in()
            source = open(os.path.join(os.path.dirname(admin.__file__), "templates", "recordings.html"), encoding="utf-8").read()
            self.assertNotIn("https://", source)
            self.assertIn("/opendmtq/hls/hls-", source)

    def test_on_its_own_port_it_comes_from_the_server_and_stays(self):
        # No sign-in: the session cookie only goes to the admin pages' address, so the page's browser sends none here.
        with Install() as inst:
            with mock.patch("urllib.request.urlopen", mock.mock_open(read_data=b"var Hls;")):
                r = inst.client.get("/opendmtq/hls/hls-1.5.17.min.js")
            self.assertEqual((r.status_code, r.get_data()), (200, b"var Hls;"))
            admin.assets._css.clear()
            # The server is down now: the copy on the data disk serves.
            with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
                self.assertEqual(inst.client.get("/opendmtq/hls/hls-1.5.17.min.js").get_data(), b"var Hls;")
                self.assertEqual(inst.client.get("/opendmtq/hls/other.js").status_code, 404)
            # Nothing but the player's own name: a backslash is a separator on Windows, where the copy is a file too.
            with mock.patch("urllib.request.urlopen") as asked:
                for name in ("hls-..%5C..%5Cx.min.js", "hls-1.5.17.min.js%5Cx.min.js", "hls-a.min.js", "hls-.min.jsx"):
                    self.assertEqual(inst.client.get("/opendmtq/hls/" + name).status_code, 404, name)
            asked.assert_not_called()


def member_rows(path, rows):
    """Members in a game database that has its tables: (id, nickname, udid)."""
    con = sqlite3.connect(path)
    con.executemany("INSERT INTO Member (id, nickname, guid, udid) VALUES (?, ?, CAST(? AS TEXT), ?)",
                    [(i, name, i, udid) for i, name, udid in rows])
    con.commit()
    con.close()


def page_token(inst):
    """The sign-in, and the form token as a browser gets it."""
    inst.sign_in()
    inst.client.get("/opendmtq/admin/backups")
    with inst.client.session_transaction(path="/opendmtq/admin/") as sess:
        return sess["csrf"]


def backup_of(inst, name, make):
    """An archive in the backups folder holding the database make(path) writes."""
    snap = inst.path("snap.db3")
    make(snap)
    with tarfile.open(inst.path(f"backups/{name}"), "w:gz") as tar:
        tar.add(snap, arcname="dmtq.db3")
    os.remove(snap)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class RecordingLimitsAskFirstTest(unittest.TestCase):
    def _rec(self, rid):
        rec = admin.recordings.rec_folder(7, rid)
        os.makedirs(rec)
        with open(os.path.join(rec, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({"started": rid, "ended": rid + 4, "duration_ms": 4000, "size": 5 * 1024 ** 3, "songs": []}, f)

    def test_limits_that_would_delete_ask_first(self):
        # A typo in a field deleted recordings at once, with no question, though every other delete asks.
        now = int(time.time())
        with Install() as inst:
            self._rec(now - 86400 * 10)
            self._rec(now - 3600)
            csrf = page_token(inst)
            page = inst.client.post("/opendmtq/admin/recordings", data={"csrf": csrf, "action": "limits", "cap_gb": "20", "days": "1"}).get_data(as_text=True)
            self.assertEqual(admin.recordings.rec_limits()["days"], 30, "saved without the yes")
            self.assertEqual(len(admin.recordings.rec_all()), 2)
            self.assertIn('name="confirmed"', page)
            self.assertRegex(page, r"1 \(5(\.0+)? GB\)")
            inst.client.post("/opendmtq/admin/recordings", data={"csrf": csrf, "action": "limits", "cap_gb": "20", "days": "1", "confirmed": "1"})
            self.assertEqual(admin.recordings.rec_limits()["days"], 1)

    def test_limits_that_delete_nothing_just_save(self):
        now = int(time.time())
        with Install() as inst:
            self._rec(now - 3600)
            csrf = page_token(inst)
            inst.client.post("/opendmtq/admin/recordings", data={"csrf": csrf, "action": "limits", "cap_gb": "50", "days": "90"})
            self.assertEqual(admin.recordings.rec_limits(), {"cap_gb": 50, "days": 90})

    def test_over_the_total_goes_oldest_first(self):
        now = int(time.time())
        with Install():
            self._rec(now - 7200)
            self._rec(now - 3600)
            self.assertEqual([r["id"] for r in admin.recordings.rec_over_limits(6, 30)], [now - 7200])

    def test_enter_in_a_check_box_presses_no_delete_button(self):
        # The form's first button is what Enter presses: it was a player's "delete all".
        with Install() as inst:
            self._rec(int(time.time()) - 3600)
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/recordings").get_data(as_text=True)
            # The list's own form: the first plain one after the limits' (the broadcasts' settings come before both).
            form = page[page.index('<form method="post">', page.index('class="rec-limits"')):]
            self.assertIn("disabled", form[:form.index("</button>")])


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class PlayerNumbersComeBackTest(unittest.TestCase):
    def setup(self, inst):
        old_game_database(admin.core.DB, [])
        member_rows(admin.core.DB, [(7, "Sena", "phone-a")])

    def seen(self, inst):
        page = inst.client.get("/opendmtq/admin/players").get_data(as_text=True)
        return re.search(r'name="seen" value="([^"]+)"', page).group(1)

    def test_a_stale_page_does_not_touch_the_next_owner_of_a_number(self):
        with Install() as inst:
            self.setup(inst)
            csrf = page_token(inst)
            old = self.seen(inst)
            # Deleted, and a new phone gets the same number while the page stays open.
            con = sqlite3.connect(admin.core.DB)
            con.execute("DELETE FROM Member")
            con.execute("INSERT INTO Play VALUES (1, 7, 900, 'A', 'N', 'N', 900)")
            con.commit()
            con.close()
            member_rows(admin.core.DB, [(7, "New", "phone-b")])
            r = inst.client.post("/opendmtq/admin/players/7", data={"csrf": csrf, "action": "reset", "seen": old})
            self.assertEqual(r.status_code, 302)
            con = sqlite3.connect(admin.core.DB)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM Play").fetchone()[0], 1, "the new player's score went")
            con.close()

    def test_a_number_nobody_has_says_so(self):
        with Install() as inst:
            self.setup(inst)
            csrf = page_token(inst)
            inst.client.post("/opendmtq/admin/players/5555", data={"csrf": csrf, "action": "live-on", "seen": "x"})
            page = inst.client.get("/opendmtq/admin/players").get_data(as_text=True)
            self.assertIn("Player 5555 is no longer there", page)
            con = sqlite3.connect(admin.core.DB)
            has = con.execute("SELECT name FROM sqlite_master WHERE name = 'LiveSwitch'").fetchone()
            self.assertFalse(has and con.execute("SELECT COUNT(*) FROM LiveSwitch WHERE guid = 5555").fetchone()[0])
            con.close()

    def test_a_player_without_a_name_row_does_not_break_the_page(self):
        with Install() as inst:
            old_game_database(admin.core.DB, [])
            member_rows(admin.core.DB, [(7, None, "phone-a")])
            inst.sign_in()
            self.assertEqual(inst.client.get("/opendmtq/admin/players").status_code, 200)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class RestoreRefusesAndRescuesTest(unittest.TestCase):
    NAME = "opendmtq-20200101-000000-manual.tar.gz"

    def post(self, inst, csrf):
        return inst.client.post(f"/opendmtq/admin/backups/{self.NAME}", data={"csrf": csrf, "action": "restore"})

    def test_a_damaged_live_database_can_be_restored(self):
        # The safety copy cannot be made of a file that is no database: refusing left no way out.
        with Install() as inst:
            backup_of(inst, self.NAME, lambda p: (old_game_database(p, []), member_rows(p, [(7, "Sena", "a")])))
            csrf = page_token(inst)
            with open(admin.core.DB, "wb") as f:
                f.write(b"this is no database" * 100)
            self.post(inst, csrf)
            con = sqlite3.connect(admin.core.DB)
            self.assertEqual(con.execute("SELECT nickname FROM Member").fetchall(), [("Sena",)])
            con.close()
            kept = [n for n in os.listdir(os.path.dirname(admin.core.DB)) if ".damaged-" in n]
            self.assertEqual(len(kept), 1)
            with open(os.path.join(os.path.dirname(admin.core.DB), kept[0]), "rb") as f:
                self.assertTrue(f.read().startswith(b"this is no database"))
            self.assertIn(kept[0], inst.client.get("/opendmtq/admin/backups").get_data(as_text=True))

    def test_an_archive_with_the_wrong_columns_changes_nothing(self):
        # The right table names over the wrong columns replaced the live database, then a bare 500.
        def wrong(path):
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE Member (a, b)")
            con.execute("CREATE TABLE Play (a, b)")
            con.commit()
            con.close()
        with Install() as inst:
            backup_of(inst, self.NAME, wrong)
            old_game_database(admin.core.DB, [])
            member_rows(admin.core.DB, [(7, "Sena", "a")])
            csrf = page_token(inst)
            self.assertEqual(self.post(inst, csrf).status_code, 302)
            r = inst.client.get("/opendmtq/admin/players")
            self.assertEqual(r.status_code, 200)
            self.assertIn("Not restored", r.get_data(as_text=True))
            con = sqlite3.connect(admin.core.DB)
            self.assertEqual(con.execute("SELECT nickname FROM Member").fetchall(), [("Sena",)])
            con.close()

    def test_a_cut_off_archive_is_said_in_the_pages_language(self):
        with Install() as inst:
            old_game_database(admin.core.DB, [])
            with open(inst.path(f"backups/{self.NAME}"), "wb") as f:
                f.write(b"\x1f\x8b\x08\x00garbage")
            csrf = page_token(inst)
            inst.client.get("/opendmtq/admin/lang?to=ko")
            self.assertEqual(self.post(inst, csrf).status_code, 302)
            page = inst.client.get("/opendmtq/admin/backups").get_data(as_text=True)
            self.assertIn("복원하지 않았습니다: 이 파일은 읽을 수 있는 백업이 아닙니다", page)

    def test_a_backup_of_no_songs_takes_later_flags_away(self):
        # With nothing in custom/ the archive said nothing about it: hidden flags from after it stayed.
        with Install() as inst:
            old_game_database(admin.core.DB, [])
            name = admin.backups.make_backup("manual")
            with tarfile.open(inst.path(f"backups/{name}")) as tar:
                self.assertIn("custom", tar.getnames())
            with open(inst.path("custom/hidden.json"), "w", encoding="utf-8") as f:
                json.dump([5], f)
            csrf = page_token(inst)
            with mock.patch.object(admin.songs, "rebuild"):
                inst.client.post(f"/opendmtq/admin/backups/{name}", data={"csrf": csrf, "action": "restore"})
            self.assertFalse(os.path.exists(inst.path("custom/hidden.json")))

    def test_two_backups_in_one_second_keep_both(self):
        with Install():
            old_game_database(admin.core.DB, [])
            with mock.patch.object(admin.backups.datetime, "datetime") as clock:
                clock.now.return_value.strftime.return_value = "20260101-000000"
                first, second = admin.backups.make_backup("manual"), admin.backups.make_backup("manual")
            self.assertNotEqual(first, second)
            self.assertEqual(len(os.listdir(admin.core.BACKUPS)), 2)

    def test_one_restore_at_a_time(self):
        with Install() as inst:
            backup_of(inst, self.NAME, lambda p: old_game_database(p, []))
            old_game_database(admin.core.DB, [])
            csrf = page_token(inst)
            with admin.backups._restoring:
                self.post(inst, csrf)
            self.assertIn("Another restore is running", inst.client.get("/opendmtq/admin/backups").get_data(as_text=True))

    def test_a_failed_upload_leaves_no_backup(self):
        with Install() as inst:
            csrf = page_token(inst)
            with mock.patch("werkzeug.datastructures.FileStorage.save", side_effect=OSError(errno.ENOSPC, "full")):
                r = inst.client.post("/opendmtq/admin/backups", data={"csrf": csrf, "action": "upload", "file": (io.BytesIO(b"x" * 10), "a.tar.gz")},
                                     content_type="multipart/form-data")
            self.assertEqual(r.status_code, 302)
            self.assertEqual(os.listdir(admin.core.BACKUPS), [])
            self.assertIn("the disk is full", inst.client.get("/opendmtq/admin/backups").get_data(as_text=True))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class SignInWithAnyTextTest(unittest.TestCase):
    def test_a_password_in_korean_is_wrong_not_a_crash(self):
        with Install() as inst:
            r = inst.client.post("/opendmtq/admin/login", data={"name": "admin", "password": "비밀번호"})
            self.assertEqual(r.status_code, 200)
            self.assertIn("Wrong ID or password", r.get_data(as_text=True))

    def test_a_korean_password_can_be_the_password(self):
        with Install() as inst, mock.patch.object(admin.core, "PASSWORD", "비밀번호"):
            self.assertEqual(inst.client.post("/opendmtq/admin/login", data={"name": "admin", "password": "비밀번호"}).status_code, 302)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class DashboardTilesTest(unittest.TestCase):
    def page(self, inst):
        inst.sign_in()
        return inst.client.get("/opendmtq/admin/").get_data(as_text=True)

    def tile(self, page, label):
        """The tile with this label: its big line and its small line, without markup."""
        at = page.index(f'<span class="lbl">{label}</span>')
        part = page[at:page.index("</section>", at)]
        part = part[:min(x for x in (part.find("</a>"), part.find("</div>")) if x > 0)]
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", part)).strip()

    def test_the_numbers(self):
        with Install() as inst:
            old_game_database(admin.core.DB, [(1, 7, 100, "B", "N", "N", 800), (2, 7, 50, "C", "N", "N", 700), (1, 8, 9, "C", "N", "N", 1)])
            member_rows(admin.core.DB, [(7, "Sena", "a"), (8, "Yuna", "b")])
            con = sqlite3.connect(admin.core.DB)
            admin.backups.bring_schema_up_to_date(con)
            now = int(time.time())
            con.executemany("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at) VALUES (?, 1, 1, 'A', 1, 0, ?)",
                            [(7, now - 60), (7, now - 3600), (8, now - 90000)])
            con.commit()
            con.close()
            page = self.page(inst)
            self.assertIn("Players 2 Records: 3", self.tile(page, "Players"))
            self.assertIn("Plays, last 24 h 2", self.tile(page, "Plays, last 24 h"))

    def test_the_plays_tile_leads_to_the_plays(self):
        # It used to lead to the request log, which lists no plays.
        with Install() as inst:
            old_game_database(admin.core.DB, [])
            page = self.page(inst)
            at = page.index('<span class="lbl">Plays, last 24 h</span>')
            self.assertTrue(page[:at].rstrip().endswith('<a class="stat" href="/opendmtq/admin/logs?tab=plays">'))

    def test_the_newest_backup_is_a_backup_of_this_server(self):
        with Install() as inst:
            old_game_database(admin.core.DB, [])
            made = inst.path("backups/opendmtq-20200101-000000-admin.tar.gz")
            for name, age in (("opendmtq-20200101-000000-admin.tar.gz", 86400 * 30), ("zzz-notes.txt", 0), ("opendmtq-20991231-000000-uploaded.tar.gz", 0)):
                path = inst.path(f"backups/{name}")
                open(path, "w", encoding="utf-8").close()
                os.utime(path, (time.time() - age, time.time() - age))
            tile = self.tile(self.page(inst), "Backups")
            self.assertIn(os.path.basename(made), tile)

    def test_an_unreadable_backups_folder_does_not_take_the_page_down(self):
        with Install() as inst:
            old_game_database(admin.core.DB, [])
            inst.sign_in()
            real = os.listdir

            def listing(path="."):
                if path == admin.core.BACKUPS:
                    raise PermissionError(errno.EACCES, "no")
                return real(path)
            with mock.patch.object(admin.backups.os, "listdir", listing):
                self.assertEqual(inst.client.get("/opendmtq/admin/").status_code, 200)

    def test_an_unreadable_database_is_said_not_no_plays(self):
        with Install() as inst:
            with open(admin.core.DB, "wb") as f:
                f.write(b"no database" * 200)
            page = self.page(inst)
            self.assertIn("The game database cannot be read", page)
            self.assertNotIn("No plays yet", page)

    def test_a_problem_the_server_reports_is_not_silence(self):
        answer = {"ok": False, "database": True, "writable": False, "songs": 193, "patch": "1", "host": HOST}
        with Install() as inst, mock.patch.object(admin.core, "server_health", lambda fresh=False: answer):
            old_game_database(admin.core.DB, [])
            page = self.page(inst)
            self.assertIn("It cannot write to its database", page)
            self.assertNotIn("is not answering", page)

    def test_the_health_page_s_503_is_an_answer(self):
        body = json.dumps({"ok": False, "database": False}).encode()
        error = urllib.error.HTTPError("http://x/", 503, "down", {}, io.BytesIO(body))
        saved = admin.core._health
        try:
            with mock.patch.object(admin.core.urllib.request, "urlopen", side_effect=error):
                self.assertEqual(admin.core.server_health(fresh=True)["database"], False)
        finally:
            admin.core._health = saved

    def test_an_app_for_another_address_is_a_problem(self):
        answer = {"ok": True, "database": True, "songs": 1, "patch": "1", "apk_matches_host": False}
        with Install() as inst, mock.patch.object(admin.core, "server_health", lambda fresh=False: answer):
            old_game_database(admin.core.DB, [])
            inst.app_for("10.0.0.1")
            self.assertIn("built for another address", self.page(inst))

    def test_english_counts_read_right_for_one(self):
        with Install() as inst:
            old_game_database(admin.core.DB, [(1, 7, 100, "B", "N", "N", 800)])
            self.assertNotIn("1 records", self.page(inst))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class PagesThatCannotWorkSaySoTest(unittest.TestCase):
    def test_no_database_gives_the_admin_s_own_page(self):
        with Install() as inst:
            inst.sign_in()
            inst.client.get("/opendmtq/admin/lang?to=ko")
            r = inst.client.get("/opendmtq/admin/players")
            self.assertEqual(r.status_code, 503)
            page = r.get_data(as_text=True)
            self.assertIn('class="bar"', page)
            self.assertIn("데이터베이스를 읽을 수 없습니다", page)

    def test_no_game_data_is_said_on_the_songs_page(self):
        # Without the client data the game cannot start: the page says how it comes, instead of failing.
        with Install() as inst, mock.patch.object(admin.songs, "has_game_data", return_value=False):
            inst.sign_in()
            r = inst.client.get("/opendmtq/admin/songs")
            self.assertEqual(r.status_code, 200)
            self.assertIn("No client data yet", r.get_data(as_text=True))

    def test_no_songs_yet_is_said_on_the_songs_page(self):
        # The client data without songs is a server that works: the page says how songs come, as a note, not an error.
        with Install() as inst, mock.patch.object(admin.songs, "has_game_data", return_value=True), \
                mock.patch.object(admin.songs, "base_song_list", return_value=[]):
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/songs").get_data(as_text=True)
            self.assertIn('class="flash note"', page)
            self.assertIn("No songs yet", page)

    def test_hiding_a_song_that_does_not_exist_changes_nothing(self):
        with Install() as inst, mock.patch.object(admin.songs, "base_song_list", return_value=[]), mock.patch.object(admin.songs, "rebuild"):
            csrf = page_token(inst)
            inst.client.post("/opendmtq/admin/songs", data={"csrf": csrf, "action": "hide", "song_id": "987654"})
            self.assertFalse(os.path.exists(inst.path("custom/hidden.json")))
            self.assertIn("There is no song 987654", inst.client.get("/opendmtq/admin/songs").get_data(as_text=True))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class SongPlaysTest(unittest.TestCase):
    """The songs page's plays: a song's charts count together over the last 30 days, with when it was last played at all."""

    def test_plays_count_by_song_and_an_unplayed_one_has_a_dash(self):
        with Install() as inst, mock.patch.object(admin.songs, "CONTENT", inst.path("content")), \
                mock.patch.object(admin.songs, "has_game_data", return_value=True):
            # Three songs: one with two charts, one played only before the 30 days, one never.
            listed = [{"song_id": 1, "name": "paperplanes", "full_name": "Paper Planes", "song_patterns": [
                          {"pattern_id": 11, "line": 3, "signature": 0, "difficulty": 1}, {"pattern_id": 12, "line": 5, "signature": 2, "difficulty": 5}]},
                      {"song_id": 2, "name": "neonrain", "full_name": "Neon Rain", "song_patterns": [{"pattern_id": 21, "line": 3, "signature": 1, "difficulty": 3}]},
                      {"song_id": 3, "name": "quiet", "full_name": "Quiet", "song_patterns": [{"pattern_id": 31, "line": 3, "signature": 1, "difficulty": 3}]}]
            os.makedirs(inst.path("content"))
            inst.write("content/songs.json", json.dumps(listed))
            old_game_database(admin.core.DB, [])
            con = sqlite3.connect(admin.core.DB)
            admin.backups.bring_schema_up_to_date(con)
            now = time.time()
            con.executemany("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at) VALUES (7, ?, 1, 'A', 900, 0, ?)",
                            [(11, now - 3600), (12, now - 7200), (12, now - 86400), (21, now - 40 * 86400)])
            con.commit()
            con.close()
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/songs").get_data(as_text=True)
            # Each row's song and the plays its cell sorts by.
            counts = dict(re.findall(r'song\.php\?id=(\d+)">[^<]*</a>.*?data-v="(\d+)"', page, re.S))
            self.assertEqual(counts, {"1": "3", "2": "0", "3": "0"})
            # The one played before the 30 days says when; the most played has the full bar.
            self.assertIn("played 1 mo ago", page)
            self.assertIn('<i style="width: 100.0%"></i>', page)
            # Never played: a dash, no bar.
            self.assertEqual(page.count('<span class="plays-none">'), 1)


class PlaysTabTest(unittest.TestCase):
    """The Logs page's Plays tab: what it narrows by, and the file."""

    @staticmethod
    def at(text):
        return int(datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S").timestamp())

    def server(self, inst, plays):
        """A server with these plays: (player, chart, score, judgement, when as text)."""
        old_game_database(admin.core.DB, [])
        member_rows(admin.core.DB, [(7, "Sena", "a"), (8, "=Yuna", "b"), (9, "Twin", "c"), (10, "Twin", "d"), (11, 'Q"uote', "e"), (12, "Idle", "f")])
        inst.write("custom/songList.json", json.dumps([
            {"name": "Paper Planes", "song_patterns": [{"pattern_id": 1, "line": 3, "signature": 0, "difficulty": 1}]},
            {"name": "-Neon Rain", "song_patterns": [{"pattern_id": 2, "line": 5, "signature": 2, "difficulty": 5}]}]))
        con = sqlite3.connect(admin.core.DB)
        admin.backups.bring_schema_up_to_date(con)
        con.executemany("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at) VALUES (?, ?, ?, 'A', ?, ?, ?)",
                        [(who, chart, score, judgement, 1 if score == 777 else 0, self.at(when)) for who, chart, score, judgement, when in plays])
        con.commit()
        con.close()
        inst.sign_in()

    @staticmethod
    def page(inst, query=""):
        return inst.client.get(f"/opendmtq/admin/logs?tab=plays&{query}").get_data(as_text=True)

    @staticmethod
    def total(page):
        return int(re.search(r'<h2>Plays <span class="meta-inline">(\d+)</span>', page).group(1))

    @staticmethod
    def names(page):
        return re.findall(r'<td class="primary"><a [^>]*>([^<]*)</a>', page)

    @staticmethod
    def rows(page):
        """How many plays the page lists: each row has its time."""
        return page.count('class="date">')

    # Around the first of October, a second to each side of it.
    EDGES = [(7, 1, 1, 900, "2026-09-30 23:59:59"), (7, 1, 2, 900, "2026-10-01 00:00:00"), (7, 1, 3, 900, "2026-10-01 23:59:59"), (7, 1, 4, 900, "2026-10-02 00:00:00")]

    def test_a_player_narrows_it_to_theirs(self):
        with Install() as inst:
            self.server(inst, [(7, 1, 1, 900, "2026-10-01 10:00:00"), (9, 1, 2, 900, "2026-10-01 11:00:00"), (9, 2, 3, 900, "2026-10-01 12:00:00")])
            page = self.page(inst, "player=9")
            self.assertEqual(self.total(page), 2)
            # Their name once over the list, and in no row: every row is theirs.
            self.assertIn("Plays of Twin", page)
            self.assertEqual(self.names(page), [])
            self.assertEqual(self.rows(page), 2)
            # The form says who is picked.
            self.assertIn('<option value="9" selected>', page)

    def test_the_list_is_those_with_plays_told_apart_when_they_share_a_name(self):
        with Install() as inst:
            self.server(inst, [(7, 1, 1, 900, "2026-10-01 10:00:00"), (9, 1, 2, 900, "2026-10-01 11:00:00"), (10, 1, 3, 900, "2026-10-01 12:00:00")])
            options = re.findall(r'<option value="(\d*)"[^>]*>([^<]*)</option>', self.page(inst))
            self.assertEqual(options, [("", "Any player"), ("7", "Sena"), ("9", "Twin (9)"), ("10", "Twin (10)")])

    def test_a_day_counts_whole_on_both_ends(self):
        with Install() as inst:
            self.server(inst, self.EDGES)
            self.assertEqual(self.total(self.page(inst, "from=2026-10-01&to=2026-10-01")), 2)
            self.assertEqual(self.total(self.page(inst, "from=2026-10-01")), 3)
            self.assertEqual(self.total(self.page(inst, "to=2026-10-01")), 3)

    def test_days_the_wrong_way_round_are_taken_as_meant(self):
        with Install() as inst:
            self.server(inst, self.EDGES)
            page = self.page(inst, "from=2026-10-02&to=2026-10-01")
            self.assertEqual(self.total(page), 3)
            # And the form shows them the right way round.
            self.assertIn('name="from" value="2026-10-01"', page)
            self.assertIn('name="to" value="2026-10-02"', page)

    def test_what_cannot_be_read_counts_as_not_given(self):
        with Install() as inst:
            self.server(inst, self.EDGES)
            for query in ("from=2026-13-45", "to=nonsense", "from=0001-01-01", "to=9999-12-31", "player=abc", "player=-1", "player=999", "player=12", "page=x", "page=-3"):
                with self.subTest(query):
                    r = inst.client.get(f"/opendmtq/admin/logs?tab=plays&{query}")
                    self.assertEqual(r.status_code, 200)
                    self.assertEqual(self.total(r.get_data(as_text=True)), 4)

    def test_a_word_goes_with_the_rest_and_stays_as_typed(self):
        with Install() as inst:
            self.server(inst, [(7, 1, 1, 900, "2026-10-01 10:00:00"), (7, 2, 2, 900, "2026-10-01 11:00:00"), (9, 1, 3, 900, "2026-10-01 12:00:00"), (7, 1, 4, 900, "2026-11-01 12:00:00")])
            page = self.page(inst, "q=PAPER&player=7&to=2026-10-31")
            self.assertEqual(self.total(page), 1)
            self.assertIn('value="PAPER"', page)

    def test_the_other_pages_and_the_file_keep_the_filter(self):
        with Install() as inst:
            self.server(inst, [(7, 1, n, 900, f"2026-10-01 10:{n // 60:02d}:{n % 60:02d}") for n in range(120)] + [(9, 1, 1, 900, "2026-10-01 11:00:00")])
            page = self.page(inst, "player=7&from=2026-10-01")
            self.assertEqual(self.total(page), 120)
            links = re.findall(r'href="(/opendmtq/admin/logs\?[^"]*)"', page.replace("&amp;", "&"))
            older = next(link for link in links if "page=2" in link)
            the_file = next(link for link in links if "csv=1" in link)
            for link in (older, the_file):
                self.assertIn("player=7", link)
                self.assertIn("from=2026-10-01", link)
            next_page = inst.client.get(older).get_data(as_text=True)
            self.assertEqual(self.total(next_page), 120)
            self.assertIn("Plays of Sena", next_page)
            self.assertEqual(self.rows(next_page), min(admin.logs.PLAYS_PAGE, 120 - admin.logs.PLAYS_PAGE))
            self.assertEqual(inst.client.get(the_file).get_data(as_text=True).count("Twin"), 0)

    def test_a_page_past_the_end_is_the_last_page(self):
        with Install() as inst:
            self.server(inst, [(7, 1, n, 900, f"2026-10-01 10:{n // 60:02d}:{n % 60:02d}") for n in range(120)])
            r = inst.client.get("/opendmtq/admin/logs?tab=plays&player=7&page=99")
            self.assertEqual(r.status_code, 302)
            self.assertIn("page=3", r.headers["Location"])
            self.assertIn("player=7", r.headers["Location"])
            self.assertEqual(self.rows(inst.client.get(r.headers["Location"]).get_data(as_text=True)), 20)

    def test_the_summary_counts_all_that_the_filter_found(self):
        with Install() as inst:
            # Three plays by two players over two days, one a new record (777), and one in June: counted by the database,
            # and, with a word to search for (every chart's name has LINE), added up as the plays are matched.
            self.server(inst, [(7, 1, 777, 900, "2026-10-01 10:00:00"), (7, 2, 5, 800, "2026-10-01 11:00:00"), (9, 1, 6, 700, "2026-10-02 12:00:00"),
                               (9, 1, 8, 700, "2026-06-02 12:00:00")])
            for query in ("from=2026-10-01&to=2026-10-02", "q=line&from=2026-10-01&to=2026-10-02"):
                with self.subTest(query):
                    page = self.page(inst, query)
                    figures = dict(re.findall(r"<dt>([^<]+)</dt><dd>([^<]+)</dd>", page))
                    self.assertEqual(figures, {"Plays": "3", "New records": "1", "Average accuracy": "80.0%", "Players": "2"})
                    # A column for each of the two days asked for, saying what it counts.
                    self.assertIn('data-tip="Plays on 2026-10-01: 2"', page)
                    self.assertIn('data-tip="Plays on 2026-10-02: 1"', page)
                    self.assertIn("Plays per day", page)
            # Plays over more than three months: a column is a week, from its Monday.
            page = self.page(inst, "from=2026-06-01&to=2026-10-02")
            self.assertIn("Plays per week", page)
            self.assertIn('data-tip="Plays in the week of 2026-09-28: 3"', page)
            self.assertIn('data-tip="Plays in the week of 2026-06-01: 1"', page)
            # Years asked for around them: the chart runs from the first play to today, not over the empty years.
            page = self.page(inst, "from=2020-01-01&to=2030-12-31")
            self.assertIn('data-tip="Plays in the week of 2026-06-01: 1"', page)
            self.assertNotRegex(page, r'data-tip="Plays in the week of (20[01]|202[0-5]|2026-0[1-5]|202[7-9]|2030)')
            # One player: no count of players.
            self.assertNotIn("<dt>Players</dt>", self.page(inst, "player=7"))

    def test_the_file_is_everything_the_filter_leaves_not_one_page(self):
        with Install() as inst:
            self.server(inst, [(7, 1, n, 958, f"2026-10-01 10:{n // 60:02d}:{n % 60:02d}") for n in range(120)] + [(9, 1, 1, 900, "2026-10-01 11:00:00")])
            r = inst.client.get("/opendmtq/admin/logs?tab=plays&csv=1&player=7")
            self.assertEqual(r.mimetype, "text/csv")
            # The file's name says what it holds.
            self.assertIn("opendmtq-plays-player7.csv", r.headers["Content-Disposition"])
            text = r.get_data(as_text=True)
            # The mark that tells a spreadsheet on Windows this is UTF-8.
            self.assertTrue(text.startswith("﻿"))
            rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
            self.assertEqual(rows[0], ["time", "player_id", "player", "song", "chart", "score", "grade", "accuracy", "new_record"])
            self.assertEqual(len(rows), 121)
            # Newest first, as on the page, accuracy as a percentage.
            self.assertEqual(rows[1], ["2026-10-01 10:01:59", "7", "Sena", "Paper Planes", "2LINE Easy 1", "119", "A", "95.8", "0"])

    def test_nothing_in_the_file_is_read_as_a_formula(self):
        with Install() as inst:
            self.server(inst, [(8, 2, 777, 900, "2026-10-01 10:00:00"), (11, 1, 1, 900, "2026-10-01 09:00:00")])
            rows = list(csv.reader(io.StringIO(inst.client.get("/opendmtq/admin/logs?tab=plays&csv=1").get_data(as_text=True).lstrip("﻿"))))
            self.assertEqual(rows[1][2:4], ["'=Yuna", "'-Neon Rain"])
            self.assertEqual(rows[1][-1], "1")
            # A quote in a name stays in its field.
            self.assertEqual(rows[2][2], 'Q"uote')

    def test_a_filter_that_leaves_nothing_says_so_and_offers_the_way_back(self):
        with Install() as inst:
            self.server(inst, self.EDGES)
            page = self.page(inst, "q=nobody")
            self.assertIn("Nothing logged for this filter.", page)
            self.assertIn("Clear filter", page)
            self.assertNotIn("csv=1", page)

    def test_a_server_without_plays_has_nothing_to_narrow(self):
        with Install() as inst:
            self.server(inst, [])
            page = self.page(inst)
            self.assertIn("No plays yet", page)
            self.assertNotIn("plays-filters", page)
            self.assertNotIn("csv=1", page)

    def test_an_unreadable_database_is_said_not_no_plays(self):
        with Install() as inst:
            inst.sign_in()
            with open(admin.core.DB, "wb") as f:
                f.write(b"no database" * 200)
            page = self.page(inst)
            self.assertIn("Database not readable", page)
            self.assertNotIn("No plays yet", page)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class AccountLinkTest(unittest.TestCase):
    """An account linked to the game player it is: picked when it is made, changed or taken away later."""

    @staticmethod
    def server(inst):
        old_game_database(admin.core.DB, [])
        member_rows(admin.core.DB, [(7, "Sena", "a"), (9, "Twin", "c"), (10, "Twin", "d")])
        inst.sign_in()

    @staticmethod
    def post(inst, **fields):
        data = {"csrf": page_token(inst), **fields}
        return inst.client.post("/opendmtq/admin/accounts", data=data, follow_redirects=True).get_data(as_text=True)

    def test_a_player_picked_when_made_then_changed_then_taken_away(self):
        with Install() as inst:
            self.server(inst)
            self.post(inst, action="create", name="sena", password="hunter22", password2="hunter22", player="7")
            self.assertEqual(AccountsTest.row("sena")["guid"], 7)
            # The page lists every player, two with one name told apart, and shows whom the account is.
            page = inst.client.get("/opendmtq/admin/accounts").get_data(as_text=True)
            self.assertIn(">Twin (9)</option>", page)
            self.assertIn('<option value="7" selected>Sena</option>', page)
            page = self.post(inst, action="link", name="sena", player="9")
            self.assertEqual(AccountsTest.row("sena")["guid"], 9)
            self.assertIn("sena is linked to Twin (9).", page)
            page = self.post(inst, action="link", name="sena", player="")
            self.assertIsNone(AccountsTest.row("sena")["guid"])
            self.assertIn("sena is no longer linked to a player.", page)

    def test_a_player_there_is_not_is_refused(self):
        with Install() as inst:
            self.server(inst)
            self.assertIn("No such player.", self.post(inst, action="create", name="nobody", password="hunter22", password2="hunter22", player="999"))
            self.assertIsNone(AccountsTest.row("nobody"))
            self.post(inst, action="create", name="sena", password="hunter22", password2="hunter22", player="7")
            self.assertIn("No such player.", self.post(inst, action="link", name="sena", player="abc"))
            self.assertEqual(AccountsTest.row("sena")["guid"], 7)

    def test_a_table_from_before_the_link_gets_its_column(self):
        with Install() as inst:
            self.server(inst)
            con = sqlite3.connect(admin.core.DB)
            con.execute("DROP TABLE IF EXISTS SiteUser")
            con.execute("""CREATE TABLE SiteUser (name TEXT PRIMARY KEY COLLATE NOCASE, pass TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
                           admin INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, signed_in_at INTEGER, off INTEGER NOT NULL DEFAULT 0)""")
            con.execute("INSERT INTO SiteUser (name, pass, created_at) VALUES ('old', 'x', 1)")
            con.commit()
            con.close()
            self.assertEqual(inst.client.get("/opendmtq/admin/accounts").status_code, 200)
            self.assertIsNone(AccountsTest.row("old")["guid"])
            self.post(inst, action="link", name="old", player="7")
            self.assertEqual(AccountsTest.row("old")["guid"], 7)


class AccountsTest(unittest.TestCase):
    """The site's accounts: made on the Accounts page and nowhere else; an ID and a password to sign in with."""

    @staticmethod
    def server(inst):
        old_game_database(admin.core.DB, [])
        inst.sign_in()

    @staticmethod
    def make(inst, **fields):
        """The Accounts page's form; the page it leads to."""
        csrf = page_token(inst)
        data = {"csrf": csrf, "action": "create", "name": "", "password": "", "note": "", **fields}
        # A typed password is typed twice, as the form asks, unless the test says otherwise.
        data.setdefault("password2", data["password"])
        return inst.client.post("/opendmtq/admin/accounts", data=data, follow_redirects=True).get_data(as_text=True)

    @staticmethod
    def act(inst, action, name):
        csrf = page_token(inst)
        return inst.client.post("/opendmtq/admin/accounts", data={"csrf": csrf, "action": action, "name": name}, follow_redirects=True).get_data(as_text=True)

    @staticmethod
    def row(name):
        con = sqlite3.connect(admin.core.DB)
        con.row_factory = sqlite3.Row
        try:
            return con.execute("SELECT * FROM SiteUser WHERE name = ?", (name,)).fetchone()
        finally:
            con.close()

    def test_a_password_is_kept_as_the_site_checks_it(self):
        with Install() as inst:
            self.server(inst)
            self.make(inst, name="Sena", password="hunter22", note="Sena's phone")
            kind, rounds, salt, digest = self.row("Sena")["pass"].split("$")
            # PBKDF2-SHA256 as PHP's hash_pbkdf2 computes it (server/portal/lib.php: site_pass_ok).
            self.assertEqual((kind, int(rounds)), ("pbkdf2_sha256", admin.auth.ACCOUNT_ROUNDS))
            self.assertEqual(hashlib.pbkdf2_hmac("sha256", b"hunter22", bytes.fromhex(salt), int(rounds)).hex(), digest)
            self.assertTrue(admin.auth.account_pass_ok(self.row("Sena")["pass"], "hunter22"))
            self.assertFalse(admin.auth.account_pass_ok(self.row("Sena")["pass"], "hunter23"))

    def test_an_empty_password_field_makes_one_and_it_shows_once(self):
        with Install() as inst:
            self.server(inst)
            page = self.make(inst, name="yuna")
            shown = re.search(r"<code>([a-z2-9]{10})</code>", page)
            self.assertTrue(shown, page[:400])
            self.assertTrue(admin.auth.account_pass_ok(self.row("yuna")["pass"], shown.group(1)))
            # The message to send has the ID and the password; the next page has neither.
            self.assertIn("ID: yuna", page)
            self.assertNotIn(shown.group(1), inst.client.get("/opendmtq/admin/accounts").get_data(as_text=True))

    def test_a_typed_password_has_to_be_typed_the_same_twice(self):
        with Install() as inst:
            self.server(inst)
            self.assertIn("The two passwords are not the same.", self.make(inst, name="sena", password="hunter22", password2="hunter23"))
            self.assertIsNone(self.row("sena"))
            self.make(inst, name="sena", password="hunter22", password2="hunter22")
            self.assertTrue(admin.auth.account_pass_ok(self.row("sena")["pass"], "hunter22"))

    def test_what_cannot_be_an_id_or_a_password_is_refused(self):
        with Install() as inst:
            self.server(inst)
            self.assertIn("An ID is 3 to 20", self.make(inst, name="a b"))
            self.assertIn("An ID is 3 to 20", self.make(inst, name="민호"))
            self.assertIn("A password is 6 to 64", self.make(inst, name="short", password="12345"))
            # With admin rights a typed password is 10 at least: it opens these pages, and the site's sign-in takes it too.
            self.assertIn("With admin rights a password is 10 to 64", self.make(inst, name="helper", password="hunter222", admin="1"))
            self.assertIsNone(self.row("helper"))
            self.make(inst, name="Sena", password="hunter22")
            # The same ID in other letters, and the owner's own ID, are taken.
            self.assertIn("is taken", self.make(inst, name="SENA", password="hunter22"))
            self.assertIn("is taken", self.make(inst, name="Admin", password="hunter22"))
            con = sqlite3.connect(admin.core.DB)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM SiteUser").fetchone()[0], 1)
            con.close()

    def test_admin_rights_open_these_pages_and_a_site_account_does_not(self):
        with Install() as inst:
            self.server(inst)
            self.make(inst, name="helper", password="hunter2222", admin="1")
            self.make(inst, name="friend", password="hunter22")
            other = admin.app.test_client()
            self.assertEqual(other.post("/opendmtq/admin/login", data={"name": "friend", "password": "hunter22"}).status_code, 200)
            self.assertEqual(other.post("/opendmtq/admin/login", data={"name": "HELPER", "password": "hunter2222"}).status_code, 302)
            self.assertEqual(other.get("/opendmtq/admin/players").status_code, 200)
            self.assertIsNotNone(self.row("helper")["signed_in_at"])

    def test_a_new_password_or_switching_off_ends_an_admins_session(self):
        with Install() as inst:
            self.server(inst)
            self.make(inst, name="helper", password="hunter2222", admin="1")
            other = admin.app.test_client()
            other.post("/opendmtq/admin/login", data={"name": "helper", "password": "hunter2222"})
            self.act(inst, "password", "helper")
            self.assertEqual(other.get("/opendmtq/admin/players").status_code, 302)
            # A new password: the old one no longer signs in.
            self.assertEqual(other.post("/opendmtq/admin/login", data={"name": "helper", "password": "hunter2222"}).status_code, 200)
            # Switched off: an admin signed in with it is out at the next page.
            self.make(inst, name="second", password="hunter2222", admin="1")
            third = admin.app.test_client()
            third.post("/opendmtq/admin/login", data={"name": "second", "password": "hunter2222"})
            self.assertEqual(third.get("/opendmtq/admin/players").status_code, 200)
            self.act(inst, "off", "second")
            self.assertEqual(self.row("second")["off"], 1)
            self.assertEqual(third.get("/opendmtq/admin/players").status_code, 302)
            self.act(inst, "on", "second")
            self.act(inst, "delete", "second")
            self.assertIsNone(self.row("second"))

    def test_an_admin_keeps_their_sign_in_with_a_new_password_and_cannot_lock_themselves_out(self):
        with Install() as inst:
            self.server(inst)
            self.make(inst, name="helper", password="hunter2222", admin="1")
            other = admin.app.test_client()
            other.post("/opendmtq/admin/login", data={"name": "helper", "password": "hunter2222"})
            token = lambda: other.get("/opendmtq/admin/accounts").get_data(as_text=True).split('name="csrf" value="')[1].split('"')[0]
            # Their own new password: shown, and they stay signed in with it.
            page = other.post("/opendmtq/admin/accounts", data={"csrf": token(), "action": "password", "name": "HELPER"}, follow_redirects=True).get_data(as_text=True)
            shown = re.search(r"<code>([a-z2-9]{10})</code>", page)
            self.assertTrue(shown and admin.auth.account_pass_ok(self.row("helper")["pass"], shown.group(1)), page[:300])
            self.assertEqual(other.get("/opendmtq/admin/players").status_code, 200)
            # Disabling, deleting or taking away their own rights: refused, and nothing changes.
            for action in ("off", "delete", "player"):
                page = other.post("/opendmtq/admin/accounts", data={"csrf": token(), "action": action, "name": "helper"}, follow_redirects=True).get_data(as_text=True)
                self.assertIn("You are signed in with helper", page, action)
            row = self.row("helper")
            self.assertEqual((row["off"], row["admin"]), (0, 1))

    def test_rights_can_be_given_and_taken_away(self):
        with Install() as inst:
            self.server(inst)
            self.make(inst, name="friend", password="hunter22")
            self.act(inst, "admin", "friend")
            self.assertEqual(self.row("friend")["admin"], 1)
            other = admin.app.test_client()
            self.assertEqual(other.post("/opendmtq/admin/login", data={"name": "friend", "password": "hunter22"}).status_code, 302)
            self.act(inst, "player", "friend")
            self.assertEqual(self.row("friend")["admin"], 0)
            # Without the rights, the next page is the sign-in, which says why.
            r = other.get("/opendmtq/admin/players", follow_redirects=True)
            self.assertIn("Signed out: your account was changed.", r.get_data(as_text=True))
            page = inst.client.get("/opendmtq/admin/logs?tab=changes").get_data(as_text=True)
            self.assertIn("Gave admin rights", page)
            self.assertIn("Removed admin rights", page)

    def test_the_owner_signs_in_without_the_database(self):
        with Install() as inst:
            with open(admin.core.DB, "wb") as f:
                f.write(b"no database" * 200)
            self.assertEqual(inst.client.post("/opendmtq/admin/login", data={"name": "admin", "password": "pw"}).status_code, 302)
            self.assertEqual(inst.client.get("/opendmtq/admin/backups").status_code, 200)

    def test_the_log_of_changes_says_what_was_done_and_nothing_twice(self):
        with Install() as inst:
            self.server(inst)
            self.make(inst, name="Sena", password="hunter22")
            self.act(inst, "off", "Sena")
            self.act(inst, "off", "Sena")
            self.act(inst, "password", "Sena")
            self.act(inst, "delete", "Sena")
            page = inst.client.get("/opendmtq/admin/logs?tab=changes").get_data(as_text=True)
            for words in ("Made an account", "Switched an account off", "Made a new password", "Deleted an account"):
                self.assertIn(words, page)
            self.assertEqual(page.count("Switched an account off"), 1)

    def test_with_no_account_the_status_page_leads_to_the_setups_players_step(self):
        from opendmtq_tools.admin import setup
        # Everything else in place: the game's files and the app for this address.
        done = mock.patch.multiple(setup, has_base_apk=lambda: True, app_ready=lambda: True)
        with Install() as inst, done, mock.patch.object(admin.songs, "has_game_data", lambda: True):
            self.server(inst)
            page = inst.client.get("/opendmtq/admin/").get_data(as_text=True)
            self.assertIn("The server is not set up yet. Next step: Players.", page)
            self.assertIn('href="/opendmtq/admin/setup">Continue the setup</a>', page)
            # The setup opens at the step that is left.
            self.assertIn("Accounts for the players", inst.client.get("/opendmtq/admin/setup").get_data(as_text=True))
            self.make(inst, name="Sena", password="hunter22")
            self.assertNotIn("The server is not set up yet", inst.client.get("/opendmtq/admin/").get_data(as_text=True))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class FormChecksTest(unittest.TestCase):
    """A form's own checks are the page's (admin.js), in its look and its language: the browser's bubble would show in the
    browser's language, outside the design. The server checks the same again."""

    # A field the browser would check: one it must have, a pattern, a least value or length, a date or a number.
    RULE = re.compile(r'\brequired\b|\bpattern="|\bmin="|\bminlength="|type="(?:date|number)"')

    def test_every_field_with_a_rule_is_checked_by_the_page_in_its_words(self):
        templates = os.path.join(os.path.dirname(admin.__file__), "templates")
        checked = 0
        for name in sorted(os.listdir(templates)):
            with open(os.path.join(templates, name), encoding="utf-8") as f:
                text = f.read()
            for form in re.finditer(r"<form\b([^>]*)>(.*?)</form>", text, re.S):
                for field in re.findall(r"<(?:input|select|textarea)\b[^>]*>", form.group(2)):
                    if 'type="hidden"' in field or not self.RULE.search(field):
                        continue
                    checked += 1
                    # The form leaves the check to the page, and the field has the words for it, as plain text.
                    self.assertIn("novalidate", form.group(1), f"{name}: {field}")
                    self.assertRegex(field, r"""data-bad="\{\{ tp\('[\w.]+'\) \}\}\"""", f"{name}: {field}")
        # The sign-in's two, the account's ID and passwords, a token's name, the setup's ID, the other address, the two
        # files, the recordings' limits and the plays' days: none of them left out.
        self.assertEqual(checked, 14)

    def test_the_words_are_in_the_pages_language(self):
        with Install() as inst:
            old_game_database(admin.core.DB, [])
            inst.client.set_cookie("opendmtq_lang", "ko")
            self.assertIn('data-bad="아이디와 비밀번호를 입력하세요."', inst.client.get("/opendmtq/admin/login").get_data(as_text=True))
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/accounts").get_data(as_text=True)
            self.assertIn('data-bad="아이디는 영문, 숫자, 점(.), 하이픈(-), 밑줄(_)로 3~20자입니다."', page)
            self.assertIn('data-bad="토큰 이름은 1~40자입니다."', page)

    def test_the_server_still_refuses_what_the_page_would_not_send(self):
        # A browser without the page's script, or a request of another program: the server's own words, as before.
        with Install() as inst:
            old_game_database(admin.core.DB, [])
            inst.sign_in()
            page = inst.client.post("/opendmtq/admin/accounts", data={"csrf": page_token(inst), "action": "create", "name": "x"},
                                    follow_redirects=True).get_data(as_text=True)
            self.assertIn("An ID is 3 to 20 Latin letters, digits, dots, dashes or underscores.", page)
