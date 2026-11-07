"""Tests for the setup pages (admin/setup.py): the one-time sign-in the host program opens them with, the game's files
found and picked on this PC, the import, the address and its restart, the players' accounts and the app.

Flask is installed in the tools image only; outside it these tests are skipped (CI runs them there).
"""

import json
import ntpath
import os
import re
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

from tests.test_admin import HAVE_FLASK, HOST, Install, old_game_database

if HAVE_FLASK:
    from opendmtq_tools import admin
    from opendmtq_tools.admin import setup

BASE = "/opendmtq/admin"


class HostInstall(Install):
    """The admin pages as a host install runs them: on the server PC, with its settings file, its run folder and a home
    folder of its own (where the game's files are looked for)."""

    def __init__(self, host_install=True):
        super().__init__()
        self.host_install = host_install
        for d in ("run", "home/Downloads", "home/Desktop", "apk/base"):
            os.makedirs(self.path(d), exist_ok=True)
        self.write(".env", f"# The owner's own note stays.\nPUBLIC_HOST={HOST}\nADMIN_PASSWORD=pw\n")
        old_game_database(self.path("state/dmtq.db3"), [])

    def __enter__(self):
        super().__enter__()
        self._setup = mock.patch.multiple(
            setup, HOST_INSTALL=self.host_install, ENV_FILE=self.path(".env"), RUN_DIR=self.path("run"),
            SIGNIN_FILE=self.path("run/signin.token"))
        self._setup.start()
        # A file written as apk/base/client.apk stands for the original client (test_clients looks at real ones); what
        # the pages kept of the last look goes with the test.
        def inspect(path):
            if os.path.basename(path) == "client.apk":
                return {"kind": "original", "version": "1.3.4", "hosts": [], "known": True}
            return {"kind": "not the game", "version": None, "hosts": [], "known": False}
        # The patcher's own name for it, and the import's.
        self._client = mock.patch.multiple(setup.patch_apk, inspect=inspect)
        self._client_import = mock.patch.multiple(setup.importer, inspect=inspect)
        self._client.start()
        self._client_import.start()
        setup._base.update(key=None, client=None)
        setup._what.clear()
        # Where expanduser("~") points: the folders setup looks in.
        self._home = mock.patch.dict(os.environ, {"HOME": self.path("home"), "USERPROFILE": self.path("home")})
        self._home.start()
        return self

    def __exit__(self, *exc):
        self._home.stop()
        self._client_import.stop()
        self._client.stop()
        self._setup.stop()
        return super().__exit__(*exc)

    def key(self, key="KEY-1234567890", age=0):
        """A one-time sign-in in the run folder, as the host program writes it, made age seconds ago."""
        path = self.path("run/signin.token")
        self.write("run/signin.token", key)
        then = time.time() - age
        os.utime(path, (then, then))
        return key

    def csrf(self):
        """The form token of this browser's session (signed in first)."""
        self.client.get(BASE + "/setup")
        with self.client.session_transaction(path=BASE + "/") as sess:
            return sess["csrf"]

    def page(self, url, **kw):
        return self.client.get(url, **kw).get_data(as_text=True)


def game_folder(root):
    """A folder of the game's server files as an archive of them unpacks: the patch folder and the song list."""
    os.makedirs(os.path.join(root, setup.GAME_DIR))
    os.makedirs(os.path.join(root, "_info"))
    with open(os.path.join(root, "_info", "songList.json"), "w", encoding="utf-8") as f:
        f.write("[]")
    return root


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class OneTimeSignInTest(unittest.TestCase):
    """The host program opens the browser signed in: a key in the run folder, taken once, from this PC only."""

    def test_the_key_signs_in_once(self):
        with HostInstall() as inst:
            key = inst.key()
            r = inst.client.get(BASE + f"/setup/start?key={key}")
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r.headers["Location"].endswith(BASE + "/setup"), r.headers["Location"])
            self.assertIn("Set up your server", inst.page(BASE + "/setup"))
            # Used up: the file is gone, and a second browser gets the sign-in page with the reason.
            self.assertFalse(os.path.exists(inst.path("run/signin.token")))
            other = admin.app.test_client()
            r = other.get(BASE + f"/setup/start?key={key}")
            self.assertIn("/login", r.headers["Location"])
            self.assertIn("That sign-in link was used already", other.get(r.headers["Location"]).get_data(as_text=True))

    def test_the_key_can_name_the_step_to_open(self):
        with HostInstall() as inst:
            r = inst.client.get(BASE + f"/setup/start?key={inst.key()}&step=players")
            self.assertTrue(r.headers["Location"].endswith(BASE + "/setup?step=players"), r.headers["Location"])

    def test_a_wrong_or_old_key_or_another_pc_does_not_sign_in(self):
        with HostInstall() as inst:
            inst.key("RIGHT-KEY")
            self.assertIn("/login", inst.client.get(BASE + "/setup/start?key=WRONG").headers["Location"])
            # A wrong key leaves the right one for the right link.
            self.assertTrue(os.path.exists(inst.path("run/signin.token")))
            self.assertIn("/login", inst.client.get(BASE + "/setup/start").headers["Location"])
            # From a phone on the network: the key is for the browser on the server PC.
            r = inst.client.get(BASE + "/setup/start?key=RIGHT-KEY", environ_base={"REMOTE_ADDR": "192.168.0.20"})
            self.assertIn("/login", r.headers["Location"])
            # Older than an hour: refused, and gone.
            inst.key("OLD-KEY", age=setup.SIGNIN_LIFE + 5)
            self.assertIn("/login", inst.client.get(BASE + "/setup/start?key=OLD-KEY").headers["Location"])
            self.assertFalse(os.path.exists(inst.path("run/signin.token")))
            # None of it signed in.
            self.assertIn("/login", inst.client.get(BASE + "/setup").headers["Location"])

    def test_from_another_pc_the_link_says_where_it_works_and_stays_usable(self):
        with HostInstall() as inst:
            inst.key("RIGHT-KEY")
            away = {"REMOTE_ADDR": "192.168.0.20"}
            r = inst.client.get(BASE + "/setup/start?key=RIGHT-KEY", environ_base=away)
            self.assertIn("works only on the server PC", inst.page(r.headers["Location"], environ_base=away))
            # Not used up: the browser on the server PC still signs in with it.
            self.assertEqual(inst.client.get(BASE + "/setup/start?key=RIGHT-KEY").status_code, 302)
            self.assertFalse(os.path.exists(inst.path("run/signin.token")))
            self.assertEqual(inst.client.get(BASE + "/setup").status_code, 200)

    def test_a_key_with_other_characters_is_a_wrong_key_not_an_error(self):
        with HostInstall() as inst:
            inst.key("RIGHT-KEY")
            r = inst.client.get(BASE + "/setup/start?key=%ED%82%A4")
            self.assertEqual(r.status_code, 302)
            self.assertIn("/login", r.headers["Location"])

    def test_in_a_container_there_is_no_key_to_sign_in_with(self):
        with HostInstall(host_install=False) as inst:
            r = inst.client.get(BASE + f"/setup/start?key={inst.key()}")
            self.assertIn("/login", r.headers["Location"])

    def test_the_setup_pages_need_a_sign_in_but_the_restarts_question(self):
        with HostInstall() as inst:
            for url in ("/setup", "/setup?step=app"):
                self.assertIn("/login", inst.client.get(BASE + url).headers["Location"], url)
            r = inst.client.post(BASE + "/setup/import", data={"path": "/"})
            self.assertNotEqual(r.status_code, 200)
            # Which process answers: nothing more, and it changes with a restart.
            r = inst.client.get(BASE + "/setup/ping")
            self.assertEqual(r.get_json(), {"instance": setup.STARTED})


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class StepsTest(unittest.TestCase):
    """Four steps, the first one not done opened by default, and the status page asking until all are done."""

    def test_a_new_server_opens_at_the_files_and_the_status_page_asks_for_the_setup(self):
        with HostInstall() as inst:
            inst.sign_in()
            page = inst.page(BASE + "/setup")
            self.assertIn("The game's files", page)
            self.assertIn('aria-current="step"', page)
            self.assertIn("The server is not set up yet. Next step: Game files.", inst.page(BASE + "/"))
            # A step can be opened again by its name; an unknown one is the first left.
            self.assertIn("The address phones use", inst.page(BASE + "/setup?step=address"))
            self.assertIn("The game's files", inst.page(BASE + "/setup?step=nothing"))

    def test_a_server_with_everything_says_so_and_the_status_page_stops_asking(self):
        with HostInstall() as inst, mock.patch.object(admin.songs, "has_game_data", lambda: True):
            inst.write("apk/base/client.apk", "PK")
            inst.app_for(HOST)
            inst.sign_in()
            admin.auth.account_create("player1", "secret-1")
            self.assertEqual(setup.steps_done(), {"files": True, "address": True, "players": True, "app": True})
            page = inst.page(BASE + "/setup")
            self.assertIn("Your server is set up.", page)
            self.assertIn(f"The app for {HOST} is ready.", page)
            self.assertNotIn("not set up yet", inst.page(BASE + "/"))

    def test_game_data_with_files_missing_is_not_done_and_says_what_to_do(self):
        # The files given lacked some of the game's own: the game would stop at its start without a word.
        with HostInstall() as inst, mock.patch.object(admin.songs, "has_game_data", lambda: True):
            inst.write("apk/base/client.apk", "PK")
            inst.write("custom/missing-game-files.json", json.dumps(["dlc/d3_a0.unity3d", "dlc/d_i0.unity3d"]))
            inst.sign_in()
            self.assertFalse(setup.steps_done()["files"])
            page = inst.page(BASE + "/setup?step=files")
            self.assertIn("2 of its files are missing (dlc/d3_a0.unity3d, ...)", page)
            self.assertIn("Import the game data again.", page)

    def test_a_server_waiting_for_its_files_is_pointed_to_the_setup_not_called_down(self):
        waiting = {"ok": False, "game_data": False, "database": True, "writable": True, "songs": 0, "host": HOST}
        with HostInstall() as inst, mock.patch.object(admin.core, "server_health", lambda fresh=False: waiting):
            inst.sign_in()
            page = inst.page(BASE + "/")
            self.assertIn("The game cannot start yet:", page)
            self.assertIn(f'href="{BASE}/setup?step=files">Import them in the setup</a>', page)
            self.assertIn('<span class="num warnc">No game files</span>', page)
            self.assertNotIn("OFFLINE", page)
            self.assertNotIn("site-alert down", page)
            # The setup's own pages say it in their first step.
            self.assertNotIn("The game cannot start yet", inst.page(BASE + "/setup?step=files"))
        # A database that cannot be written is a problem whatever else is missing.
        broken = dict(waiting, writable=False)
        with HostInstall() as inst, mock.patch.object(admin.core, "server_health", lambda fresh=False: broken):
            inst.sign_in()
            page = inst.page(BASE + "/")
            self.assertIn("site-alert down", page)
            self.assertIn("OFFLINE", page)

    def test_an_app_for_another_address_is_not_the_app_step_done(self):
        with HostInstall() as inst:
            inst.app_for("192.168.0.99")
            self.assertFalse(setup.app_ready())
            inst.app_for(HOST)
            self.assertTrue(setup.app_ready())


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class FilesOnThisPcTest(unittest.TestCase):
    """The game's files in the places people keep files, and a folder picker for anywhere else."""

    def test_the_downloads_folder_is_looked_in_and_the_complete_folder_comes_first(self):
        with HostInstall() as inst:
            # An APK alone on the Desktop, and the APK with the server files in a folder in Downloads.
            inst.write("home/Desktop/technika-q.apk", "PK")
            os.makedirs(inst.path("home/Downloads/DMTQ"))
            inst.write("home/Downloads/DMTQ/game.apk", "PK")
            game_folder(inst.path("home/Downloads/DMTQ/dmtq"))
            # An archive that is nothing of the game's, beside nothing of the game's.
            os.makedirs(inst.path("home/Downloads/holiday"))
            inst.write("home/Downloads/holiday/photos.zip", "PK")
            found = setup.found_on_this_pc()
            self.assertEqual([f["path"] for f in found],
                             [inst.path("home/Downloads/DMTQ"), inst.path("home/Desktop")])
            self.assertEqual(found[0]["tree"], inst.path("home/Downloads/DMTQ/dmtq"))
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=files")
            self.assertIn("game.apk", page)
            self.assertIn(f'name="path" value="{inst.path("home/Downloads/DMTQ")}"', page)
            self.assertNotIn("photos.zip", page)

    def test_archives_named_like_the_games_are_found_on_their_own(self):
        with HostInstall() as inst:
            inst.write("home/Downloads/dmtq-files.zip", "PK")
            inst.write("home/Downloads/Technika files.rar", "Rar!")
            inst.write("home/Downloads/tax.zip", "PK")
            hit = setup.look_in(inst.path("home/Downloads"))
            self.assertEqual(hit["archives"], ["dmtq-files.zip", "Technika files.rar"])
            self.assertEqual(hit["apks"], [])

    def test_the_forms_people_have_them_in_are_found(self):
        with HostInstall() as inst:
            # A bundle, an archive in parts (by its first part, with how many more), the iPhone app beside them; this
            # project's own app is none of the game's.
            os.makedirs(inst.path("home/Downloads/DMTQ"))
            for name in ("game.xapk", "server-files.7z.001", "server-files.7z.002", "server-files.7z.003", "game.ipa",
                         "OpenDMTQ-192.168.0.10-v2026.11.01.apk"):
                inst.write(f"home/Downloads/DMTQ/{name}", "x")
            hit = setup.look_in(inst.path("home/Downloads/DMTQ"))
            self.assertEqual(hit["apks"], ["game.xapk"])
            self.assertEqual(hit["archives"], ["server-files.7z.001"])
            self.assertEqual(hit["parts"], {"server-files.7z.001": 2})
            self.assertEqual(hit["iphone"], ["game.ipa"])
            seen = setup.listing(inst.path("home/Downloads/DMTQ"))
            self.assertEqual([n for n, _, _ in seen["files"]],
                             ["game.ipa", "game.xapk", "OpenDMTQ-192.168.0.10-v2026.11.01.apk", "server-files.7z.001"])
            self.assertEqual(seen["parts"]["server-files.7z.001"], 2)
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=files")
            self.assertIn("2 more parts", page)
            self.assertNotIn("server-files.7z.002", page)

    def test_the_iphone_app_alone_is_found_to_be_said_of_no_use(self):
        with HostInstall() as inst:
            inst.write("home/Downloads/TECHNIKA Q.ipa", "x")
            self.assertEqual(setup.look_in(inst.path("home/Downloads"))["iphone"], ["TECHNIKA Q.ipa"])

    def test_the_server_files_in_another_form_are_found(self):
        with HostInstall() as inst:
            # The game host's folder under another name, with no song list beside it.
            www = inst.path("home/Downloads/server/www")
            os.makedirs(os.path.join(www, "patch", "phone_new"))
            os.makedirs(os.path.join(www, "DMQ", "Songs", "7"))
            inst.write("home/Downloads/server/www/DMQ/Songs/7/7.fpk", "m")
            self.assertEqual(setup.game_folder_in(inst.path("home/Downloads/server")), www)

    def test_the_patch_folder_alone_is_found_and_whole_files_beside_it_first(self):
        with HostInstall() as inst:
            # The patch folder copied out by itself: the game data alone, seen from Downloads and from its own folder,
            # and said once, by its own.
            os.makedirs(inst.path("home/Downloads/patch/phone_new/1.003.005/android/table/us"))
            downloads = inst.path("home/Downloads")
            self.assertEqual(setup.game_folder_in(downloads), downloads)
            self.assertEqual([f["tree"] for f in setup.found_on_this_pc()], [inst.path("home/Downloads/patch")])
            # The whole files beside it: they are what an import of Downloads takes, and what is shown.
            www = inst.path("home/Downloads/server/www")
            os.makedirs(os.path.join(www, "patch", "phone_new"))
            os.makedirs(os.path.join(www, "DMQ", "Songs", "7"))
            inst.write("home/Downloads/server/www/DMQ/Songs/7/7.fpk", "m")
            self.assertEqual(setup.game_folder_in(downloads), www)
            # A folder that holds the patch folder is looked into: the whole files may be beside it there.
            stuff = inst.path("home/Documents/stuff")
            os.makedirs(os.path.join(stuff, "patch", "phone_new", "1.003.005", "android", "table"))
            os.makedirs(os.path.join(stuff, "server", "dmqglb.mb.pmang.com", "patch", "phone_new"))
            self.assertEqual(setup.game_folder_in(inst.path("home/Documents")), os.path.join(stuff, "server"))
            # A folder gone since it was found is still told apart from the others, by its own path.
            self.assertEqual(setup.same_files(inst.path("home/gone")), os.path.normpath(inst.path("home/gone")))

    def test_the_game_data_and_the_songs_alone_are_found_and_named(self):
        with HostInstall() as inst:
            # The patch folder copied out, and the songs' folder with their jackets in a folder of their own.
            os.makedirs(inst.path("home/Downloads/DMTQ/game data/patch/phone_new/1.003.005/android/table/us"))
            os.makedirs(inst.path("home/Downloads/DMTQ/songs/DMQ/Songs/1"))
            inst.write("home/Downloads/DMTQ/songs/DMQ/Songs/1/1.fpk", "m")
            inst.write("home/Downloads/DMTQ/game.apk", "PK")
            found = setup.look_in(inst.path("home/Downloads/DMTQ"))
            self.assertEqual((found["tree"], found["tree_kind"], found["songs_tree"]),
                             (inst.path("home/Downloads/DMTQ/game data"), "game", inst.path("home/Downloads/DMTQ/songs")))
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=files")
            self.assertIn("Game data folder: " + inst.path("home/Downloads/DMTQ/game data"), page)
            self.assertIn("Songs folder: " + inst.path("home/Downloads/DMTQ/songs"), page)
            self.assertIn("The songs", page)
            # In the picker, the songs' folder says what it holds.
            self.assertIn("This folder holds the game's songs.", inst.page(BASE + "/setup?step=files&dir="
                                                                            + inst.path("home/Downloads/DMTQ/songs")))
            self.assertEqual(setup.what_words(setup.what_is(inst.path("home/Downloads/DMTQ/songs"))), "Songs alone: 1 songs")

    def test_each_file_is_said_for_what_it_is(self):
        with HostInstall() as inst:
            inst.write("home/Downloads/client.apk", "PK")
            inst.write("home/Downloads/other.apk", "PK")
            inst.write("home/Downloads/game.ipa", "x")
            inst.write("home/Downloads/files.7z.002", "x")
            inst.write("home/Downloads/broken.zip", "not an archive")
            www = inst.path("home/Downloads/server/www")
            os.makedirs(os.path.join(www, "patch", "phone_new"))
            for song in ("1", "2"):
                os.makedirs(os.path.join(www, "DMQ", "Songs", song))
                inst.write(f"home/Downloads/server/www/DMQ/Songs/{song}/{song}.fpk", "m")
            inst.sign_in()

            def said(rel):
                r = inst.client.get(BASE + "/setup/what", query_string={"path": inst.path(rel)})
                return r.get_json()
            self.assertEqual(said("home/Downloads/client.apk"), {"ok": True, "text": "Android app 1.3.4, original: ready"})
            self.assertEqual(said("home/Downloads/other.apk"), {"ok": False, "text": "Another app, not the game"})
            self.assertFalse(said("home/Downloads/game.ipa")["ok"])
            self.assertIn("iPhone app", said("home/Downloads/game.ipa")["text"])
            self.assertIn("first part", said("home/Downloads/files.7z.002")["text"])
            self.assertEqual(said("home/Downloads/server/www"), {"ok": True, "text": "Server files with 2 songs"})
            self.assertEqual(said("home/Downloads/gone.apk"), {"ok": False, "text": "Not there any more"})
            with mock.patch.object(setup.importer, "archive_paths", lambda path, say=True: []):
                self.assertIn("Cannot be read", said("home/Downloads/broken.zip")["text"])

    def test_a_client_changed_for_another_server_is_said_with_its_server(self):
        with HostInstall() as inst:
            inst.sign_in()
            changed = {"kind": "other server", "version": "1.3.5", "hosts": ["play.example.net"], "known": True}
            for name, info, words in (
                    ("changed.apk", changed, "Android app 1.3.5, changed for another server (play.example.net): pointed at this one"),
                    # A version the screen fixes were not made for says so.
                    ("older.apk", {**changed, "version": "1.3.2", "known": False},
                     "Android app 1.3.2, changed for another server (play.example.net): pointed at this one. "
                     "A few screen fixes are made for 1.3.5 and 1.3.4 only.")):
                # A file each: the page keeps what it said of a path for a while.
                inst.write(f"home/Downloads/{name}", "PK")
                with mock.patch.object(setup.importer, "inspect", lambda path: info):
                    text = inst.client.get(BASE + "/setup/what", query_string={"path": inst.path(f"home/Downloads/{name}")}).get_json()
                self.assertEqual(text, {"ok": True, "text": words})

    def test_the_client_in_place_is_said_for_what_it_is(self):
        with HostInstall() as inst:
            inst.sign_in()
            inst.write("apk/base/client.apk", "PK")
            self.assertIn("Android app 1.3.4, original: ready", inst.page(BASE + "/setup?step=files"))
            # Only APKs that are no client: named, with what to do.
            os.remove(inst.path("apk/base/client.apk"))
            inst.write("apk/base/friend.apk", "PK")
            page = inst.page(BASE + "/setup?step=files")
            self.assertIn("None to build from: friend.apk", page)
            self.assertFalse(setup.steps_done()["files"])

    def test_the_two_kinds_of_file_are_explained(self):
        with HostInstall() as inst:
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=files")
            self.assertIn("The game's Android app", page)
            self.assertIn(".xapk", page)
            self.assertIn("patch/phone_new", page)

    def test_a_path_is_taken_as_people_paste_it(self):
        with mock.patch.dict(os.environ, {"DMTQ_TEST_HOME": "/home/x"}):
            self.assertEqual(setup.clean_path('  "/home/x/Downloads/DMTQ"  '), "/home/x/Downloads/DMTQ")
            self.assertEqual(setup.clean_path("'/home/x/a b/'"), "/home/x/a b")
            self.assertEqual(setup.clean_path("$DMTQ_TEST_HOME/Downloads"), "/home/x/Downloads")
            self.assertEqual(setup.clean_path('""'), "")
            self.assertEqual(setup.clean_path("   "), "")
            # A browser's address for a file, its spaces written as %20.
            self.assertEqual(setup.clean_path("file:///home/x/my%20files/DMTQ"), "/home/x/my files/DMTQ")
        home = os.path.expanduser("~")
        self.assertEqual(setup.clean_path("~/Downloads"), os.path.join(home, "Downloads"))
        # From no top: from the home folder, not from wherever the server program runs.
        self.assertEqual(setup.clean_path("Downloads/DMTQ"), os.path.join(home, "Downloads", "DMTQ"))
        # Windows' own forms, as its paths work.
        with mock.patch("os.path", ntpath), mock.patch.object(setup.os, "name", "nt"), \
                mock.patch.dict(os.environ, {"USERPROFILE": "C:\\Users\\me"}):
            self.assertEqual(setup.clean_path('"C:\\Users\\me\\Downloads\\"'), "C:\\Users\\me\\Downloads")
            self.assertEqual(setup.clean_path("D:"), "D:\\")
            self.assertEqual(setup.clean_path("Downloads\\DMTQ"), "C:\\Users\\me\\Downloads\\DMTQ")
            self.assertEqual(setup.clean_path("file:///C:/Users/me/My%20Files"), "C:\\Users\\me\\My Files")
            self.assertEqual(setup.clean_path("file://nas/share/DMTQ"), "\\\\nas\\share\\DMTQ")

    def test_a_whole_drive_or_the_home_is_too_wide_to_import(self):
        with HostInstall() as inst:
            self.assertTrue(setup.too_wide("/"))
            self.assertTrue(setup.too_wide(inst.path("home")))
            self.assertFalse(setup.too_wide(inst.path("home/Downloads")))
            inst.sign_in()
            r = inst.client.post(BASE + "/setup/import", data={"csrf": inst.csrf(), "path": inst.path("home"), "songs": "yes"})
            self.assertEqual(r.status_code, 302)
            self.assertIn("whole drive or home folder", inst.page(r.headers["Location"]))
            self.assertEqual(admin.jobs._jobs, {})

    def test_a_folder_that_cannot_be_read_is_said_before_any_import(self):
        with HostInstall() as inst:
            inst.sign_in()
            with mock.patch.object(setup.os, "access", lambda path, mode: False):
                r = inst.client.post(BASE + "/setup/import", data={"csrf": inst.csrf(), "path": inst.path("home/Downloads")})
            self.assertIn("cannot be read by this program", inst.page(r.headers["Location"]))

    def test_the_picker_is_open_from_the_start_at_downloads_with_the_way_there(self):
        with HostInstall() as inst:
            os.makedirs(inst.path("home/Downloads/DMTQ"))
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=files")
            self.assertIn('class="setup-crumbs"', page)
            self.assertIn('aria-current="location">Downloads</b>', page)
            self.assertIn(">DMTQ</a>", page)
            # The field holds where the picker is, to change or copy.
            self.assertIn(f'name="dir" value="{inst.path("home/Downloads")}"', page)

    def test_a_typed_file_opens_its_folder_with_the_file_marked(self):
        with HostInstall() as inst:
            os.makedirs(inst.path("home/Downloads/DMTQ"))
            inst.write("home/Downloads/DMTQ/game.apk", "PK")
            inst.sign_in()
            page = inst.page(BASE + "/setup", query_string={"step": "files", "dir": f'"{inst.path("home/Downloads/DMTQ/game.apk")}"'})
            self.assertIn('class="file picked" id="picked"', page)
            self.assertIn('aria-current="location">DMTQ</b>', page)

    def test_a_path_no_system_has_is_taken_without_an_error(self):
        with HostInstall() as inst:
            inst.sign_in()
            # A NUL, as only a made-up address carries one: the page comes, as do the import's and the look's answers.
            r = inst.client.get(BASE + "/setup", query_string={"step": "files", "dir": "/home\0/x"})
            self.assertEqual(r.status_code, 200)
            r = inst.client.post(BASE + "/setup/import", data={"csrf": inst.csrf(), "path": "\0"})
            self.assertEqual(r.status_code, 302)
            self.assertEqual(admin.jobs._jobs, {})
            answer = inst.client.get(BASE + "/setup/what", query_string={"path": "\0"}).get_json()
            self.assertFalse(answer["ok"])

    def test_a_path_with_nothing_there_says_so(self):
        with HostInstall() as inst:
            inst.sign_in()
            gone = inst.path("home/Downloads/nowhere/deeper")
            page = inst.page(BASE + "/setup", query_string={"step": "files", "dir": gone})
            self.assertIn(f"Nothing is at {gone}", page)
            # The picker opens at the nearest folder above it that is there.
            self.assertIn('aria-current="location">Downloads</b>', page)

    def test_a_file_the_import_cannot_look_at_still_gets_an_answer(self):
        with HostInstall() as inst:
            inst.write("home/Downloads/odd.zip", "x")
            inst.sign_in()
            with mock.patch.object(setup.importer, "what_is", side_effect=FileNotFoundError("7zz")):
                answer = inst.client.get(BASE + "/setup/what", query_string={"path": inst.path("home/Downloads/odd.zip")}).get_json()
            self.assertEqual(answer, {"ok": False, "text": "Could not be checked"})

    @unittest.skipIf(os.name == "nt", "a name of any bytes is a Linux file system's")
    def test_a_name_no_page_can_show_is_left_out_and_the_page_still_comes(self):
        with HostInstall() as inst:
            folder = inst.path("home/Downloads")
            with open(os.path.join(os.fsencode(folder), b"game-\xff.zip"), "wb") as f:
                f.write(b"PK")
            inst.write("home/Downloads/game.apk", "PK")
            inst.sign_in()
            r = inst.client.get(BASE + "/setup", query_string={"step": "files", "dir": folder})
            self.assertEqual(r.status_code, 200)
            self.assertIn("game.apk", r.get_data(as_text=True))

    def test_this_projects_own_download_is_not_taken_for_the_games_files(self):
        with HostInstall() as inst:
            inst.write("home/Downloads/OpenDMTQ-windows.zip", "PK")
            self.assertIsNone(setup.look_in(inst.path("home/Downloads")))

    def test_the_picker_lists_folders_and_the_games_files_and_hides_the_rest(self):
        with HostInstall() as inst:
            top = inst.path("home/Downloads")
            os.makedirs(os.path.join(top, "Music"))
            os.makedirs(os.path.join(top, ".cache"))
            inst.write("home/Downloads/game.apk", "PK" * 600)
            inst.write("home/Downloads/notes.txt", "x")
            seen = setup.listing(top)
            self.assertEqual([n for n, _ in seen["folders"]], ["Music"])
            self.assertEqual([(n, size) for n, size, _ in seen["files"]], [("game.apk", 1200)])
            self.assertEqual(seen["parent"], inst.path("home"))
            self.assertIsNone(setup.listing(inst.path("home/nowhere")))
            # The root has no folder above it.
            self.assertIsNone(setup.listing("/")["parent"])
            inst.sign_in()
            page = inst.page(BASE + f"/setup?step=files&dir={top}")
            self.assertIn("1 KB", page)
            self.assertIn("Up one folder", page)
            self.assertNotIn("notes.txt", page)
            self.assertNotIn(".cache", page)

    def test_the_picker_says_when_a_folder_holds_the_song_files(self):
        with HostInstall() as inst:
            tree = game_folder(inst.path("home/Downloads/dmtq"))
            inst.sign_in()
            self.assertIn("This folder holds the game's server files.", inst.page(BASE + f"/setup?step=files&dir={tree}"))
            self.assertEqual(setup.game_folder_in(inst.path("home/Downloads")), tree)

    def test_a_folder_that_cannot_be_opened_says_so_with_the_way_up(self):
        with HostInstall() as inst:
            inst.sign_in()
            locked = inst.path("home/Downloads/locked")
            os.makedirs(locked)
            # A folder there that this program may not read; the picker opens the folder above it.
            real = setup.listing
            with mock.patch.object(setup, "listing", side_effect=lambda path: None if path == locked else real(path)):
                page = inst.page(BASE + "/setup", query_string={"step": "files", "dir": locked})
            self.assertIn("cannot be opened: there is no permission for it", page)
            self.assertIn("Up one folder", page)

    def test_the_top_of_a_drive_has_no_way_up(self):
        self.assertIsNone(setup.parent_of("/"))
        self.assertEqual(setup.parent_of("/home/"), "/")
        # As Windows' paths work: "C:" alone would be the program's own folder on that drive.
        with mock.patch("os.path", ntpath):
            self.assertIsNone(setup.parent_of("C:\\"))
            self.assertEqual(setup.parent_of("C:\\Users"), "C:\\")
            self.assertIsNone(setup.parent_of("\\\\nas\\share\\"))

    def test_each_folder_is_looked_in_once(self):
        with HostInstall() as inst, mock.patch.object(setup, "look_in", wraps=setup.look_in) as looked:
            os.makedirs(inst.path("home/Documents"))
            setup.found_on_this_pc()
            folders = [c.args[0] for c in looked.call_args_list]
            # Downloads is a place of its own and a folder of the home.
            self.assertEqual(len(folders), len(set(folders)))
            self.assertIn(inst.path("home/Downloads"), folders)

    def test_the_look_through_the_usual_places_is_kept_a_little_while(self):
        with HostInstall() as inst, mock.patch.object(setup, "look_in", wraps=setup.look_in) as looked:
            setup.found_on_this_pc()
            count = looked.call_count
            setup.found_on_this_pc()
            self.assertEqual(looked.call_count, count)
            # Older than that: looked at again.
            with mock.patch.object(setup, "SCAN_LIFE", 0):
                setup.found_on_this_pc()
            self.assertGreater(looked.call_count, count)

    def test_more_files_than_are_listed_is_said_too(self):
        with HostInstall() as inst, mock.patch.object(setup, "MAX_LISTED", 2):
            for n in range(3):
                inst.write(f"home/Downloads/{n}.zip", "PK")
            self.assertTrue(setup.listing(inst.path("home/Downloads"))["more"])

    def test_the_songs_page_leads_to_the_import_on_this_pc(self):
        with HostInstall() as inst, mock.patch.object(admin.songs, "has_game_data", lambda: True), \
                mock.patch.object(admin.songs, "base_song_list", lambda: []):
            inst.sign_in()
            page = inst.page(BASE + "/songs")
            self.assertIn("Import yours from a folder on this PC", page)
            self.assertIn(f'href="{BASE}/setup?step=files">Choose the folder</a>', page)
        # In a container the command line does it, as the page says.
        with HostInstall(host_install=False) as inst, mock.patch.object(admin.songs, "has_game_data", lambda: True), \
                mock.patch.object(admin.songs, "base_song_list", lambda: []):
            inst.sign_in()
            page = inst.page(BASE + "/songs")
            self.assertIn("./opendmtq import --songs", page)
            self.assertNotIn("Choose the folder", page)

    def test_on_kubernetes_the_pages_name_the_charts_way(self):
        with HostInstall(host_install=False) as inst, mock.patch.object(setup, "IN_KUBERNETES", True):
            inst.sign_in()
            self.assertIn("runs on Kubernetes", inst.page(BASE + "/setup?step=files"))
            address = inst.page(BASE + "/setup?step=address")
            self.assertIn("helm upgrade", address)
            self.assertNotIn("./opendmtq host", address)

    def test_in_a_container_the_page_names_the_command_instead(self):
        with HostInstall(host_install=False) as inst:
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=files")
            self.assertIn("./opendmtq import --songs", page)
            self.assertNotIn("Found on this PC", page)
            self.assertEqual(inst.client.post(BASE + "/setup/import", data={"csrf": inst.csrf(), "path": "/"}).status_code, 404)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class ImportTest(unittest.TestCase):
    """The import: the importer and the song list, as a job the page follows."""

    def run_import(self, inst, path, **form):
        started = {}

        def start_job(kind, cmd, env=None, **details):
            started.update(kind=kind, cmd=cmd, env=env, details=details)
            return "job1"

        with mock.patch.object(admin.jobs, "start_job", start_job):
            r = inst.client.post(BASE + "/setup/import", data={"csrf": inst.csrf(), "path": path, **form})
        return r, started

    def test_a_folder_is_imported_with_the_songs_and_the_list_is_made_after(self):
        with HostInstall() as inst:
            inst.sign_in()
            folder = inst.path("home/Downloads")
            r, job = self.run_import(inst, folder, songs="yes")
            self.assertEqual(r.status_code, 302)
            self.assertIn("job=job1", r.headers["Location"])
            self.assertEqual(job["kind"], "import")
            self.assertEqual([c[-1] for c in job["cmd"]], ["opendmtq_tools.importer", "opendmtq_tools.songs"])
            self.assertEqual(job["env"]["OPENDMTQ_IMPORT_IN"], folder)
            self.assertEqual((job["env"]["IMPORT_GAME"], job["env"]["IMPORT_SONGS"]), ("yes", "yes"))
            self.assertNotIn("IMPORT_ONLY", job["env"])

    def test_a_single_file_is_its_folder_with_only_that_file(self):
        with HostInstall() as inst:
            inst.sign_in()
            inst.write("home/Downloads/client.apk", "PK")
            _, job = self.run_import(inst, inst.path("home/Downloads/client.apk"))
            self.assertEqual(job["env"]["OPENDMTQ_IMPORT_IN"], inst.path("home/Downloads"))
            self.assertEqual(job["env"]["IMPORT_ONLY"], "client.apk")
            # The box unticked: no songs.
            self.assertEqual(job["env"]["IMPORT_SONGS"], "no")

    def test_a_path_that_is_gone_or_a_second_import_is_refused(self):
        with HostInstall() as inst:
            inst.sign_in()
            r, job = self.run_import(inst, inst.path("home/gone"))
            self.assertEqual(job, {})
            self.assertIn("That folder or file is not there any more.", inst.page(r.headers["Location"]))
            with admin.jobs._jobs_lock:
                admin.jobs._jobs["busy"] = {"id": "busy", "kind": "import", "state": "running", "log": [], "started": 0}
            try:
                r, job = self.run_import(inst, inst.path("home/Downloads"))
                self.assertEqual(job, {})
                self.assertIn("An import is running already", inst.page(r.headers["Location"]))
            finally:
                with admin.jobs._jobs_lock:
                    admin.jobs._jobs.pop("busy", None)

    def test_the_page_follows_a_running_import(self):
        with HostInstall() as inst:
            inst.write("home/Desktop/client.apk", "PK")
            inst.sign_in()
            with admin.jobs._jobs_lock:
                admin.jobs._jobs["imp"] = {"id": "imp", "kind": "import", "state": "running", "log": [], "started": 0}
            try:
                page = inst.page(BASE + "/setup?step=files&job=imp")
                self.assertIn("Importing. The songs take some minutes.", page)
                self.assertIn(f'fetch("{BASE}/jobs/imp")', page)
                # Its import buttons wait for it.
                self.assertRegex(page, r'data-again\s+disabled')
            finally:
                with admin.jobs._jobs_lock:
                    admin.jobs._jobs.pop("imp", None)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class AddressTest(unittest.TestCase):
    """The address phones use: one of this PC's own, written to .env, then a restart the host program does."""

    def choose(self, inst, host):
        return inst.client.post(BASE + "/setup/address", data={"csrf": inst.csrf(), "host": host})

    def test_another_address_of_this_pc_is_saved_and_the_server_asked_to_start_again(self):
        with HostInstall() as inst, mock.patch.object(setup, "this_pcs_addresses", lambda: [HOST, "10.0.0.5"]):
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=address")
            self.assertIn('<option value="10.0.0.5">10.0.0.5</option>', page)
            r = self.choose(inst, "10.0.0.5")
            self.assertEqual(r.status_code, 200)
            with open(inst.path(".env"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "# The owner's own note stays.\nPUBLIC_HOST=10.0.0.5\nADMIN_PASSWORD=pw\n")
            self.assertTrue(os.path.exists(inst.path("run/restart.request")))
            # The page waits for the new process, then signs in again with a new key, at the players' step.
            body = r.get_data(as_text=True)
            with open(inst.path("run/signin.token"), encoding="ascii") as f:
                key = f.read()
            self.assertIn(f'{BASE}/setup/start?key={key}\\u0026step=players', body)
            self.assertIn(setup.STARTED, body)

    def test_nothing_else_starts_while_an_import_runs(self):
        running = {"j": {"id": "j", "kind": "import", "state": "running", "log": [], "started": time.time()}}
        with HostInstall() as inst, mock.patch.object(setup, "this_pcs_addresses", lambda: [HOST, "10.0.0.5"]):
            inst.sign_in()
            inst.write("apk/base/client.apk", "PK")
            csrf = inst.csrf()
            with mock.patch.dict(admin.jobs._jobs, running):
                # A restart now would cut the import off.
                r = inst.client.post(BASE + "/setup/address", data={"csrf": csrf, "host": "10.0.0.5"})
                self.assertIn("An import is running", inst.page(r.headers["Location"]))
                self.assertFalse(os.path.exists(inst.path("run/restart.request")))
                with open(inst.path(".env"), encoding="utf-8") as f:
                    self.assertIn(f"PUBLIC_HOST={HOST}\n", f.read())
                # The import may be bringing the client in: the build waits too.
                with mock.patch.object(admin.jobs, "start_job", side_effect=AssertionError("started")):
                    r = inst.client.post(BASE + "/setup/build", data={"csrf": csrf})
                    self.assertIn("An import is running", inst.page(r.headers["Location"]))

    def test_the_address_in_use_already_needs_no_restart(self):
        with HostInstall() as inst:
            inst.sign_in()
            r = self.choose(inst, HOST)
            self.assertEqual(r.status_code, 302)
            self.assertIn("step=players", r.headers["Location"])
            self.assertFalse(os.path.exists(inst.path("run/restart.request")))

    def test_from_another_pc_the_restart_leads_back_through_the_sign_in(self):
        with HostInstall() as inst:
            inst.sign_in()
            csrf = inst.csrf()
            r = inst.client.post(BASE + "/setup/address", data={"csrf": csrf, "host": "10.0.0.5"},
                                 environ_base={"REMOTE_ADDR": "192.168.0.20"})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(os.path.exists(inst.path("run/restart.request")))
            # No one-time link: it would not open from there.
            self.assertFalse(os.path.exists(inst.path("run/signin.token")))
            self.assertNotIn("/setup/start", r.get_data(as_text=True))

    def test_no_address_found_says_what_to_do(self):
        with HostInstall() as inst, mock.patch.object(setup, "this_pcs_addresses", lambda: []):
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=address")
            self.assertIn("No network address found", page)
            self.assertNotIn("only address", page)

    def test_the_port_stays_as_it_was(self):
        with HostInstall() as inst, mock.patch.object(admin.core, "PUBLIC_HOST", f"{HOST}:8790"):
            inst.sign_in()
            self.choose(inst, "10.0.0.5")
            with open(inst.path(".env"), encoding="utf-8") as f:
                self.assertIn("PUBLIC_HOST=10.0.0.5:8790\n", f.read())

    def test_an_address_phones_cannot_reach_is_refused(self):
        with HostInstall() as inst:
            inst.sign_in()
            for host in ("127.0.0.1", "169.254.3.4", "8.8.8.8", "my-pc", ""):
                r = self.choose(inst, host)
                self.assertEqual(r.status_code, 302, host)
                self.assertIn("is not an address on the server PC", inst.page(r.headers["Location"]), host)
            self.assertFalse(os.path.exists(inst.path("run/restart.request")))
            with open(inst.path(".env"), encoding="utf-8") as f:
                self.assertIn(f"PUBLIC_HOST={HOST}\n", f.read())

    def test_in_a_container_the_address_is_the_command_lines(self):
        with HostInstall(host_install=False) as inst:
            inst.sign_in()
            self.assertIn("./opendmtq host &lt;address&gt;", inst.page(BASE + "/setup?step=address"))
            self.assertEqual(self.choose(inst, "10.0.0.5").status_code, 404)

    def test_only_private_addresses_of_this_pc_are_offered(self):
        class Probe:
            def __init__(self, *a):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def connect(self, where):
                pass

            def getsockname(self):
                return ("192.168.0.10", 50000)

        infos = [(2, 1, 6, "", (a, 0)) for a in ("127.0.1.1", "192.168.0.10", "169.254.1.1", "10.0.0.5", "8.8.8.8")]
        with mock.patch.object(setup.socket, "socket", Probe), mock.patch.object(setup.socket, "getaddrinfo", lambda *a: infos), \
                mock.patch.object(setup, "interface_addresses", lambda: []):
            self.assertEqual(setup.this_pcs_addresses(), ["192.168.0.10", "10.0.0.5"])

    def test_with_no_way_out_the_computers_interfaces_still_say(self):
        # No default route, and its name on 127.0.1.1, as usual on Debian and Ubuntu: the page used to say it found no address.
        listed = ("2: eth0    inet 192.168.0.10/24 scope global eth0\n"
                  "3: docker0    inet 172.17.0.1/16 scope global docker0\n"
                  "4: vboxnet0    inet 192.168.56.1/24 scope global vboxnet0\n")
        with mock.patch.object(setup.socket, "socket", side_effect=OSError("no route")), \
                mock.patch.object(setup.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.1.1", 0))]), \
                mock.patch.object(setup.subprocess, "run", return_value=mock.Mock(stdout=listed)):
            self.assertEqual(setup.this_pcs_addresses(), ["192.168.0.10"])

    def test_the_settings_file_keeps_its_other_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("A=1\n# note\nPUBLIC_HOST=old\n")
            with mock.patch.object(setup, "ENV_FILE", path):
                setup.save_env({"PUBLIC_HOST": "10.0.0.5", "NEW": "x"})
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "A=1\n# note\nPUBLIC_HOST=10.0.0.5\nNEW=x\n")


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class StopTest(unittest.TestCase):
    """Stopping the server from the admin pages (Maintenance)."""

    def test_on_this_pc_the_page_asks_the_program_to_stop_and_says_how_to_start_again(self):
        with HostInstall() as inst:
            inst.sign_in()
            page = inst.page(BASE + "/maintenance")
            self.assertIn("Stop the server", page)
            self.assertIn('data-ask="', page)
            r = inst.client.post(BASE + "/server/stop", data={"csrf": inst.csrf()})
            self.assertEqual(r.status_code, 200)
            # Here, not Windows: the command starts it again (the Wine test reads the Windows words).
            self.assertIn("./opendmtq start", r.get_data(as_text=True))
            self.assertNotIn("OpenDMTQ.exe", r.get_data(as_text=True))
            self.assertTrue(os.path.isfile(inst.path("run/stop.request")))

    def test_a_stop_that_cannot_be_asked_says_why_and_what_to_do(self):
        with HostInstall() as inst:
            inst.sign_in()
            # The run folder gone from under the pages: the request cannot be written.
            with mock.patch.object(setup, "RUN_DIR", inst.path("gone/run")):
                r = inst.client.post(BASE + "/server/stop", data={"csrf": inst.csrf()})
            self.assertEqual(r.status_code, 302)
            page = inst.page(r.headers["Location"])
            self.assertIn("could not be asked to stop", page)
            self.assertIn("Stop it on the server PC instead", page)

    def test_without_the_form_token_nothing_stops(self):
        with HostInstall() as inst:
            inst.sign_in()
            r = inst.client.post(BASE + "/server/stop", data={"csrf": "wrong"})
            self.assertNotEqual(r.status_code, 200)
            self.assertFalse(os.path.exists(inst.path("run/stop.request")))

    def test_in_containers_the_page_names_the_command_instead(self):
        with HostInstall(host_install=False) as inst:
            inst.sign_in()
            page = inst.page(BASE + "/maintenance")
            self.assertIn("./opendmtq down", page)
            self.assertNotIn("Stop the server", page)
            self.assertEqual(inst.client.post(BASE + "/server/stop", data={"csrf": inst.csrf()}).status_code, 404)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class PlayersTest(unittest.TestCase):
    """An account for each player: made on the page, its password shown once."""

    def make(self, inst, name):
        return inst.client.post(BASE + "/setup/player", data={"csrf": inst.csrf(), "name": name})

    def test_an_account_is_made_and_its_password_shown_once(self):
        with HostInstall() as inst:
            inst.sign_in()
            self.assertEqual(self.make(inst, "player1").status_code, 302)
            page = inst.page(BASE + "/setup?step=players")
            self.assertIn("The account player1 is ready", page)
            password = re.search(r'<dd><code>([^<]+)</code></dd>', page).group(1)
            self.assertIn("ID: player1", page)
            self.assertIn("Accounts so far: 1.", page)
            # Shown once: the next visit has the form only.
            self.assertNotIn(password, inst.page(BASE + "/setup?step=players"))
            con = sqlite3.connect(admin.core.DB)
            try:
                self.assertEqual(con.execute("SELECT note FROM SiteUser WHERE name = 'player1'").fetchone(),
                                 ("made in the setup",))
            finally:
                con.close()

    def test_the_password_never_goes_into_the_sessions_cookie(self):
        with HostInstall() as inst:
            inst.sign_in()
            self.make(inst, "player2")
            with inst.client.session_transaction(path=BASE + "/") as sess:
                kept = json.dumps(dict(sess))
            page = inst.page(BASE + "/setup?step=players")
            password = re.search(r'<dd><code>([^<]+)</code></dd>', page).group(1)
            self.assertNotIn(password, kept)

    def test_a_bad_or_taken_id_is_refused(self):
        with HostInstall() as inst:
            inst.sign_in()
            self.make(inst, "player1")
            # Its password, shown once, is seen.
            inst.page(BASE + "/setup?step=players")
            for name in ("player1", "x", "has space", "admin"):
                r = self.make(inst, name)
                self.assertEqual(r.status_code, 302, name)
                self.assertNotIn("is ready", inst.page(r.headers["Location"]), name)
            self.assertEqual(admin.auth.accounts_count()[0], 1)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class AppStepTest(unittest.TestCase):
    """The app for this address, built as the App page builds it, and what to do on the phone."""

    def build(self, inst):
        started = {}

        def start_job(kind, cmd, env=None, **details):
            started.update(kind=kind, cmd=cmd, details=details)
            return "b1"

        with mock.patch.object(admin.jobs, "start_job", start_job):
            r = inst.client.post(BASE + "/setup/build", data={"csrf": inst.csrf()})
        return r, started

    def test_the_build_is_for_this_servers_address(self):
        with HostInstall() as inst:
            inst.write("apk/base/client.apk", "PK")
            inst.sign_in()
            r, job = self.build(inst)
            self.assertIn("job=b1", r.headers["Location"])
            self.assertEqual(job["kind"], "build")
            self.assertEqual(job["cmd"][-4:], ["opendmtq_tools.builder", "--force", "--host", HOST])

    def test_no_client_no_build(self):
        with HostInstall() as inst:
            inst.sign_in()
            r, job = self.build(inst)
            self.assertEqual(job, {})
            page = inst.page(r.headers["Location"])
            self.assertRegex(page, r'data-again data-label="[^"]*"\s+disabled')
            # On this PC the first step imports it.
            self.assertIn(f'<a href="{BASE}/setup?step=files">Import it in the first step</a>', page)

    def test_a_build_that_failed_for_want_of_a_client_is_the_setups_line_not_an_alarm(self):
        with HostInstall() as inst:
            # The builder at the start of a server with nothing imported yet, a minute before the setup.
            inst.status(state="failed", error="no base APK in data/apk/base", time=int(time.time()) - 60)
            inst.sign_in()
            page = inst.page(BASE + "/")
            self.assertIn("The server is not set up yet", page)
            self.assertNotIn("alert bad", page)
            self.assertNotIn("no base APK in data/apk/base", inst.page(BASE + "/setup?step=app"))
            # The client imported since: that failure was for want of it and says nothing now, here or on the status
            # page.
            inst.write("apk/base/client.apk", "PK")
            with mock.patch.object(admin.songs, "has_game_data", lambda: True):
                self.assertNotIn("alert bad", inst.page(BASE + "/"))
                self.assertNotIn("no base APK in data/apk/base", inst.page(BASE + "/setup?step=app"))
                # A build that fails after it is the owner's to know, with why.
                inst.status(state="failed", error="smali: expected 1 match(es), found 0", time=int(time.time()) + 2)
                self.assertIn("alert bad", inst.page(BASE + "/"))
                self.assertIn("The last build failed: smali: expected 1 match(es), found 0",
                              inst.page(BASE + "/setup?step=app"))

    def test_a_failure_with_no_app_on_offer_does_not_promise_one(self):
        with HostInstall() as inst:
            inst.write("apk/base/client.apk", "PK")
            inst.status(state="failed", error="smali: expected 1 match(es), found 0", time=int(time.time()) + 2)
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=app")
            self.assertIn("The last build failed: smali", page)
            self.assertNotIn("Players still get this one", page)

    def test_nothing_is_asked_about_the_runtime_for_newer_phones(self):
        # The builder gets it by itself: nobody should have to know it exists.
        with HostInstall() as inst:
            inst.write("apk/base/client.apk", "PK")
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=app")
            self.assertNotIn('name="runtime"', page)
            self.assertNotIn("Pixel 7", page)
            started = {}

            def start_job(kind, cmd, env=None, **details):
                started.update(cmd=cmd)
                return "job1"

            with mock.patch.object(admin.jobs, "start_job", start_job):
                inst.client.post(BASE + "/setup/build", data={"csrf": inst.csrf()})
            self.assertIn("opendmtq_tools.builder", started["cmd"])

    def test_a_failed_try_at_the_runtime_is_said_on_the_page(self):
        with HostInstall() as inst:
            inst.write("apk/runtime-error.txt", "could not fetch it: no network")
            inst.sign_in()
            self.assertIn("could not fetch it: no network", inst.page(BASE + "/setup?step=app"))

    def test_with_the_runtime_in_place_the_page_says_so(self):
        with HostInstall() as inst:
            os.makedirs(inst.path("apk/arm32"))
            inst.write("apk/arm32/bundle.json", "{}")
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=app")
            self.assertIn("runs on newer phones too", page)
            self.assertNotIn('name="runtime"', page)

    def test_in_a_container_too_a_failure_says_what_to_do(self):
        with HostInstall(host_install=False) as inst:
            inst.write("apk/runtime-error.txt", "could not fetch it: no network")
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=app")
            self.assertIn("could not fetch it: no network", page)
            self.assertIn("opendmtq-arm32-runtime.zip", page)

    def test_a_build_already_running_is_followed_not_started_again(self):
        with HostInstall() as inst, mock.patch.object(admin.jobs, "running_build", lambda: {"id": "b0"}):
            inst.write("apk/base/client.apk", "PK")
            inst.sign_in()
            _, job = self.build(inst)
            self.assertEqual(job, {})

    def test_the_servers_own_build_is_followed_and_not_started_twice(self):
        with HostInstall() as inst:
            inst.write("apk/base/client.apk", "PK")
            # The builder the server runs at its start, part-way.
            inst.status(state="building")
            inst.sign_in()
            _, job = self.build(inst)
            self.assertEqual(job, {})
            page = inst.page(BASE + "/setup?step=app")
            self.assertIn("Building the app.", page)
            self.assertIn("location.reload()", page)
            self.assertRegex(page, r'data-again data-label="[^"]*"\s+disabled')
            # A status left by a run that was cut off is no build, and neither is one for another address.
            inst.status(state="building", time=int(time.time()) - admin.apps.STALE_BUILD - 5)
            self.assertFalse(setup.builder_running())
            inst.status(state="building", host="192.168.0.99")
            self.assertFalse(setup.builder_running())

    def test_an_app_built_from_a_client_since_removed_still_counts_and_only_a_new_build_needs_it(self):
        with HostInstall() as inst:
            inst.app_for(HOST)
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=app")
            # Ready, said once: not "no app yet" beside it.
            self.assertIn(f"The app for {HOST} is ready.", page)
            self.assertNotIn("No Android app of the game yet", page)
            self.assertIn("The app above still works", page)

    def test_with_the_app_ready_the_page_shows_the_phones_steps_and_the_code(self):
        with HostInstall() as inst:
            inst.write("apk/base/client.apk", "PK")
            inst.app_for(HOST)
            inst.sign_in()
            page = inst.page(BASE + "/setup?step=app")
            self.assertIn(f"Open http://{HOST}/ in the browser.", page)
            self.assertNotIn("<img", page.split('class="setup-phone"')[1].split("</div>")[0])
            # With the code the build made: the code too.
            inst.write("apk/out/download-qr.svg", "<svg/>")
            page = inst.page(BASE + "/setup?step=app")
            self.assertIn(f"Open http://{HOST}/ in the browser, or scan this code.", page)
            self.assertIn('alt="QR code of the app\'s download page"', page)


if __name__ == "__main__":
    unittest.main()
