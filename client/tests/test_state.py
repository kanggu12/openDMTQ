"""What the launcher remembers: reading and writing it, servers and sign-ins, and the installer's hand-over."""

import json
import os

from opendmtq_client import preset
from opendmtq_client import state as st
from tests.base import Folder


class State(Folder):
    def test_a_first_start(self):
        s = st.LauncherState.load()
        self.assertFalse(s.guide_done)
        self.assertEqual(s.servers, [])
        self.assertIsNone(s.server())

    def test_round_trip(self):
        s = st.LauncherState()
        s.language = "ko"
        s.set_value("fps", "144")
        entry = s.add_server("http://example.test:8080", "A server", "example.test:8080")
        entry.update(account="player1", cookie="secret", expires=4000000000)
        s.save()
        again = st.LauncherState.load()
        self.assertEqual(again.language, "ko")
        self.assertEqual(again.values["fps"], "144")
        self.assertEqual(again.server()["name"], "A server")
        self.assertTrue(again.signed_in())

    def test_the_language_follows_windows_until_one_is_picked(self):
        # Windows' display language stands in through system_language: no test depends on this computer's.
        saved = st.system_language
        try:
            st.system_language = lambda: "ko"
            s = st.LauncherState.load()
            self.assertEqual(s.language, "ko")
            s.save()
            with open(st.LauncherState.path(), encoding="utf-8") as f:
                # Nothing picked yet: the file keeps no language, so the launcher goes on following Windows.
                self.assertIsNone(json.load(f)["language"])
            st.system_language = lambda: "en"
            self.assertEqual(st.LauncherState.load().language, "en")
            # A language the player picks wins over Windows' from then on.
            s.language = "ko"
            s.save()
            self.assertEqual(st.LauncherState.load().language, "ko")
        finally:
            st.system_language = saved

    def test_off_windows_the_language_is_english(self):
        if os.name == "nt":
            self.skipTest("Windows answers with its own display language")
        self.assertEqual(st.system_language(), "en")

    def test_a_newer_file_is_refused(self):
        os.makedirs(st.config_dir())
        with open(st.LauncherState.path(), "w") as f:
            json.dump({"version": st.VERSION + 1}, f)
        with self.assertRaises(st.StateError) as caught:
            st.LauncherState.load()
        self.assertTrue(caught.exception.newer)

    def test_a_broken_file_is_refused(self):
        os.makedirs(st.config_dir())
        with open(st.LauncherState.path(), "w") as f:
            f.write("{not json")
        with self.assertRaises(st.StateError) as caught:
            st.LauncherState.load()
        self.assertFalse(caught.exception.newer)

    def test_a_bad_setting_keeps_its_default(self):
        os.makedirs(st.config_dir())
        with open(st.LauncherState.path(), "w") as f:
            json.dump({"version": 1, "values": {"fps": "9000", "volume": 20}}, f)
        s = st.LauncherState.load()
        self.assertEqual(s.values["fps"], "auto")
        self.assertEqual(s.values["volume"], 20)

    def test_sign_in_runs_out_and_is_forgotten(self):
        s = st.LauncherState()
        entry = s.add_server("http://example.test")
        entry.update(account="player1", cookie="c", expires=100)
        self.assertFalse(s.signed_in(now=200))
        self.assertTrue(s.signed_in(now=50))
        s.forget_sign_in()
        self.assertIsNone(s.server()["cookie"])
        # The account's ID stays, to fill the form in again.
        self.assertEqual(s.server()["account"], "player1")

    def test_no_secrets_in_what_is_shown(self):
        s = st.LauncherState()
        s.add_server("http://example.test").update(cookie="secret-cookie", expires=4000000000)
        shown = json.dumps(s.without_secrets())
        self.assertNotIn("secret-cookie", shown)

    def test_removing_the_current_server(self):
        s = st.LauncherState()
        s.add_server("http://a.test")
        s.add_server("http://b.test")
        s.remove_server("http://b.test")
        self.assertEqual(s.current, "http://a.test")
        s.remove_server("http://a.test")
        self.assertIsNone(s.current)

    def test_the_installers_server_is_taken_once(self):
        preset.hand_over({"url": "http://example.test:8790", "name": "Club"})
        self.assertEqual(preset.take(), {"url": "http://example.test:8790", "name": "Club"})
        self.assertIsNone(preset.take())
