"""What the launcher remembers: reading and writing it, servers and sign-ins, and the installer's hand-over."""

import contextlib
import io
import itertools
import json
import os
import queue
import threading
import time
import types
from unittest import mock

from opendmtq_client import preset
from opendmtq_client import server as srv
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
        # --status shows what the launcher keeps, and its log keeps all it printed: the account, never the sign-in's
        # cookie (the settings file holds it, to stay signed in).
        from opendmtq_client import main
        s = st.LauncherState()
        s.add_server("http://example.test", "Example").update(account="player1", cookie="secret-cookie",
                                                               expires=4000000000)
        s.save()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            main.main(["--status"])
        self.assertIn("signed in: player1", out.getvalue())
        self.assertNotIn("secret-cookie", out.getvalue())
        with open(os.path.join(st.config_dir(), "logs", "launcher.log"), encoding="utf-8") as f:
            self.assertNotIn("secret-cookie", f.read())

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


class WindowThread(Folder):
    """The window saves the state on its own thread while its worker threads ask servers (app.py)."""

    def test_a_save_never_catches_a_connect_half_made(self):
        # The window's Connect (the Online page's and the guide's) gets its answer on a worker thread while the
        # window's thread saves (a setting changed, a language picked, a game that ended). Each answer takes a moment,
        # as a server's does, so it comes among the saves; fifty rounds. A worker that changed the state itself left
        # saves listing the new server while "current" still named the one before, or naming a server without its own
        # name yet: the file half of one change.
        from opendmtq_client import i18n, pages
        state = st.LauncherState()
        # The window's task pump: what the worker threads hand over (app.post), run on this thread.
        tasks = queue.Queue()
        app = types.SimpleNamespace(words=i18n.Words("en"), state=state, post=tasks.put, server_check=None,
                                    download_error=None, app_note=None, user_acted=lambda: None,
                                    refresh_checks=lambda: None)
        rounds = 50

        # Up to 2 ms, a different wait each round: where the answer lands among the saves differs too.
        waits = itertools.cycle([n / 10000.0 for n in range(20)])

        def about(base):
            time.sleep(next(waits))
            # Each server named after its own address: a name that is not its own was saved before it was set.
            return {"opendmtq": "0.8.0", "name": "Club at " + base, "address": base[len("http://"):], "app": True}

        half_made = []
        with mock.patch.object(srv, "about", about):
            for i in range(rounds):
                answered = threading.Event()
                pages.check_server(app, "http://club%d.test" % i, then=answered.set)
                while not answered.is_set():
                    # The window's thread meanwhile: a save, then the task pump's turn.
                    state.save()
                    with open(st.LauncherState.path(), encoding="utf-8") as f:
                        saved = json.load(f)
                    servers = saved["servers"]
                    # Each Connect adds a server and plays on it: a whole save lists it last and names it current.
                    if servers and (saved["current"] != servers[-1]["url"]
                                    or any(s["name"] != "Club at " + s["url"] for s in servers)):
                        half_made.append((i, saved["current"], servers[-1]["url"], servers[-1]["name"]))
                    while not tasks.empty():
                        tasks.get_nowait()()
        self.assertEqual(half_made, [])
        # Every Connect went through, the last one played on.
        self.assertEqual(len(state.servers), rounds)
        self.assertEqual(state.current, "http://club%d.test" % (rounds - 1))

    def test_an_older_ready_check_never_replaces_a_newer_one(self):
        # Help's Check again pressed just before a download ends: the check asked first may answer last (a disk that
        # has not read the app's folder lately). Its answer is about the state before, and stays on screen until the
        # next check if it is taken: only the last check asked is.
        from opendmtq_client import actions
        from opendmtq_client import app as launcher
        state = st.LauncherState()
        tasks = []
        slow = threading.Event()
        asked = []

        def readiness(state):
            # What the check reads when it runs: the server played on then.
            seen = state.current
            asked.append(seen)
            if len(asked) == 1:
                # The first check waits until the second has answered.
                slow.wait(5)
            return [actions.Check("server", True, seen)]

        app = types.SimpleNamespace(state=state, checks=None, checks_asked=0, post=tasks.append, status_sticky=True,
                                    guide=None, check_box=None, _paint_play=lambda: None)
        for name in ("refresh_checks", "_checked"):
            setattr(app, name, getattr(launcher.LauncherApp, name).__get__(app))

        def answers(count):
            # The worker threads' answers handed over (app.post), in the order they came.
            end = time.time() + 5
            while len(tasks) < count and time.time() < end:
                time.sleep(0.005)
            self.assertEqual(len(tasks), count)

        with mock.patch.object(actions, "readiness", readiness):
            state.add_server("http://first.test")
            app.refresh_checks()
            state.add_server("http://second.test")
            app.refresh_checks()
            answers(1)
            slow.set()
            answers(2)
        # The window's task pump runs them as they came: the second check's answer, then the first's.
        for task in tasks:
            task()
        self.assertEqual(asked, ["http://first.test", "http://second.test"])
        self.assertEqual([c.detail for c in app.checks], ["http://second.test"])
