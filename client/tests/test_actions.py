"""What the buttons do, without a window: the ready check, connecting, signing in, the app, PLAY, and the player."""

import json
import os

from opendmtq_client import actions, apps, player
from opendmtq_client import server as srv
from opendmtq_client import state as st
from tests import stub
from tests.base import Folder


class Actions(Folder):
    def setUp(self):
        super().setUp()
        self.site = stub.Site().start()
        self.state = st.LauncherState()

    def tearDown(self):
        self.site.stop()
        super().tearDown()

    def keys(self, checks):
        return {c.key: c for c in checks}

    def test_the_ready_check_from_nothing(self):
        checks = self.keys(actions.readiness(self.state))
        self.assertTrue(checks["player"].ok)
        self.assertFalse(checks["server"].ok)
        self.assertFalse(actions.can_play(list(checks.values())))

    def test_no_player_stops_play(self):
        os.environ["OPENDMTQ_PLAYER"] = os.path.join(self.home, "nothing.exe")
        checks = self.keys(actions.readiness(self.state))
        self.assertFalse(checks["player"].ok)
        self.assertFalse(actions.can_play(list(checks.values())))

    def test_from_connecting_to_playing(self):
        actions.connect(self.state, self.site.url.replace("http://", ""))
        self.assertEqual(self.state.server()["name"], "Stand-in")
        # Connected, signed out, no app: PLAY cannot get the app by itself yet.
        self.assertFalse(actions.can_play(actions.readiness(self.state)))
        actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)
        checks = self.keys(actions.readiness(self.state))
        # Signed in: PLAY gets the app it lacks.
        self.assertTrue(checks["app"].play_fixes)
        self.assertTrue(actions.can_play(list(checks.values())))
        steps = []
        session = actions.play(self.state, report=lambda step, done=None, total=None: steps.append(step))
        record = actions.finish(self.state, session)
        self.assertIn("download", steps)
        self.assertFalse(record["crashed"])
        started = self.started()
        folder = apps.folder(self.state.current)
        self.assertEqual(started["args"][:2], ["--app", folder])
        self.assertIn("display=fullscreen", started["settings"])
        # The server's folder: the app and player.conf naming it, as the player reads it.
        with open(os.path.join(folder, "player.conf"), encoding="utf-8") as f:
            conf = f.read()
        info = self.site.describe()
        self.assertIn("package=%s\n" % info["package"], conf)
        self.assertIn("apk=%s\n" % info["file"], conf)
        self.assertTrue(apps.current(self.state.current, info))
        # The player's standard output went to its own log for the app.
        with open(player.log_path(info["package"]), encoding="utf-8") as f:
            self.assertIn("stand-in player: started", f.read())

    def test_a_newer_app_replaces_the_old_one(self):
        actions.connect(self.state, self.site.url)
        actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)
        first = actions.get_app(self.state)
        self.site.app = stub.APP + b"newer"
        info = actions.check_app(self.state)
        # The ready check sees the newer one the server offered; PLAY gets it.
        checks = self.keys(actions.readiness(self.state))
        self.assertIn("app_update", checks)
        self.assertTrue(checks["app_update"].play_fixes)
        second = actions.get_app(self.state, info)
        self.assertEqual(second["sha256"], info["sha256"])
        # One app in the folder, the same file name (the server's name for it did not change).
        self.assertEqual([n for n in os.listdir(apps.folder(self.state.current)) if n.endswith(".apk")],
                         [first["file"]])

    def test_play_with_the_app_it_has_when_the_server_is_away(self):
        actions.connect(self.state, self.site.url)
        actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)
        actions.get_app(self.state)
        self.site.stop()
        self.site = stub.Site().start()  # another port: the old address answers no more
        session = actions.play(self.state)
        actions.finish(self.state, session)
        self.assertIsNotNone(self.started())

    def test_a_sign_in_that_ended_still_plays_the_app_it_has(self):
        actions.connect(self.state, self.site.url)
        actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)
        actions.get_app(self.state)
        self.site.signed_cookies.clear()
        session = actions.play(self.state)
        actions.finish(self.state, session)
        self.assertIsNotNone(self.started())
        self.assertFalse(self.state.signed_in())

    def test_a_crash_is_noted(self):
        actions.connect(self.state, self.site.url)
        actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)
        os.environ["FAKE_PLAYER_EXIT"] = str(0xC0000005 & 0x7F)
        record = actions.finish(self.state, actions.play(self.state))
        self.assertTrue(record["crashed"])
        self.assertTrue(self.state.last_session["crashed"])

    def test_an_app_for_the_old_address_does_not_start(self):
        # The server is building its app again for a new address: the app this PC has would not reach it.
        actions.connect(self.state, self.site.url)
        actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)
        actions.get_app(self.state)
        self.site.app_state = "stale"
        with self.assertRaises(srv.ServerError) as caught:
            actions.play(self.state)
        self.assertEqual(caught.exception.key, "error.app.stale")
        self.assertIsNone(self.started())

    def test_a_server_that_does_not_answer_plays_this_pcs_app(self):
        actions.connect(self.state, self.site.url)
        actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)
        actions.get_app(self.state)
        # The server goes away: PLAY starts the app this PC has, and says the server did not answer.
        self.site.stop()
        steps = []
        try:
            session = actions.play(self.state, report=lambda step, done=None, total=None: steps.append(step))
            actions.finish(self.state, session)
        finally:
            # tearDown stops self.site: a fresh one, since this one is stopped already.
            self.site = stub.Site().start()
        self.assertIn("offline", steps)
        self.assertIsNotNone(self.started())

    def test_could_not_start_is_no_crash(self):
        # 1 is the player's own "could not start": told apart from a crash, which ends with Windows' fault code.
        actions.connect(self.state, self.site.url)
        actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)
        os.environ["FAKE_PLAYER_EXIT"] = "1"
        record = actions.finish(self.state, actions.play(self.state))
        self.assertFalse(record["crashed"])
        self.assertTrue(record["failed_start"])

    def test_play_refuses_when_not_ready(self):
        with self.assertRaises(actions.NotReady):
            actions.play(self.state)

    def test_audio_devices(self):
        devices = player.audio_devices()
        self.assertEqual([d["name"] for d in devices], ["Speakers (made up)", "Headphones (made up)"])
        self.assertTrue(devices[0]["default"])

    def test_no_player_lists_no_devices(self):
        self.assertEqual(player.audio_devices(os.path.join(self.home, "none.py")), [])

    def test_sign_in_needs_a_server(self):
        with self.assertRaises(srv.ServerError):
            actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)

    def test_the_cookie_is_kept_not_the_password(self):
        actions.connect(self.state, self.site.url)
        actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)
        self.state.save()
        with open(st.LauncherState.path(), encoding="utf-8") as f:
            kept = f.read()
        self.assertNotIn(stub.PASSWORD, kept)
        self.assertEqual(json.loads(kept)["servers"][0]["cookie"], self.site.cookie)
