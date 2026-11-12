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

    def test_keyboard_play_kept_and_read_again(self):
        # Kept as chosen, in the names the player takes; a file from before keyboard play has its defaults; a value
        # edited by hand that no lane takes keeps that setting's default, the others as they were.
        s = st.LauncherState()
        s.set_value("keys_3line", "s/d f j")
        s.set_value("keyboard", "off")
        s.save()
        again = st.LauncherState.load()
        self.assertEqual((again.values["keys_3line"], again.values["keyboard"]), ("S/D F J", "off"))
        self.assertTrue({"keys_3line", "keyboard"} <= again.chosen)
        for written, read in (({"volume": 40}, ("on", "F J", "D F J K")),
                              ({"keys_2line": "F F", "keys_4line": "Q W E R"}, ("on", "F J", "Q W E R"))):
            with open(st.LauncherState.path(), "w", encoding="utf-8") as f:
                json.dump({"version": 1, "values": written}, f)
            values = st.LauncherState.load().values
            self.assertEqual((values["keyboard"], values["keys_2line"], values["keys_4line"]), read, written)

    def test_the_counters_corner_from_before_0_9_3(self):
        # A launcher before 0.9.3 wrote its default corner, the top left, whether or not the player chose it: read as no
        # choice, the bottom right now. Another corner was the player's choice and stays.
        os.makedirs(os.path.dirname(st.LauncherState.path()), exist_ok=True)
        for written, read in (("top_left", "bottom_right"), ("top_right", "top_right"), ("bottom_left", "bottom_left"),
                              ("bottom_right", "bottom_right")):
            with open(st.LauncherState.path(), "w", encoding="utf-8") as f:
                json.dump({"version": 1, "values": {"show_fps": "on", "fps_position": written}}, f)
            self.assertEqual(st.LauncherState.load().values["fps_position"], read, written)
        # The top left chosen from now on stays: the file says the player chose it.
        s = st.LauncherState()
        s.set_value("fps_position", "top_left")
        s.save()
        self.assertEqual(st.LauncherState.load().values["fps_position"], "top_left")
        # So does one chosen as show_fps's value (as --set takes it).
        s = st.LauncherState()
        s.set_value("show_fps", "top_left")
        s.save()
        again = st.LauncherState.load()
        self.assertEqual((again.values["show_fps"], again.values["fps_position"]), ("on", "top_left"))
        # The counter turned on alone chooses no corner: the default's.
        s = st.LauncherState()
        s.set_value("show_fps", "on")
        s.save()
        self.assertEqual(st.LauncherState.load().values["fps_position"], "bottom_right")
        self.assertEqual(sorted(st.LauncherState.load().chosen), ["show_fps"])

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

    def test_a_server_without_a_name_is_said_by_its_address_once(self):
        # A site without SERVER_NAME answers its address (PUBLIC_HOST) for its name; an entry kept without a name has
        # its address for one: the address alone then, not "192.168.0.5:8080 (http://192.168.0.5:8080)".
        s = st.LauncherState()
        named = s.add_server("http://club.test:8790", "Club", "club.test:8790")
        self.assertTrue(st.has_own_name(named))
        self.assertEqual(st.label(named), "Club (http://club.test:8790)")
        for name, address in (("192.0.2.5:8080", "192.0.2.5:8080"), ("http://192.0.2.5:8080", ""),
                              ("192.0.2.5", ""), ("Site.Test:8080", "site.test:8080"), ("", "")):
            url = "http://site.test:8080" if "Site" in name else "http://192.0.2.5:8080"
            server = st._server({"url": url, "name": name, "address": address})
            self.assertFalse(st.has_own_name(server), name)
            self.assertEqual(st.label(server), url, name)

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

        def readiness(state, reached=None):
            # What the check reads when it runs: the server played on then.
            seen = state.current
            asked.append(seen)
            if len(asked) == 1:
                # The first check waits until the second has answered.
                slow.wait(5)
            return [actions.Check("server", True, seen)]

        # The server is not asked here (actions.reach): whether it answers is not what this test is about.
        app = types.SimpleNamespace(state=state, checks=None, checks_asked=0, post=tasks.append, status_sticky=True,
                                    guide=None, check_box=None, _paint_play=lambda: None, _reach=lambda force: None)
        for name in ("refresh_checks", "_checked", "_say_state"):
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


class StatusLine(Folder):
    """The window's status line: what it keeps gives way once the player does something, and says itself again in the
    language the window switches to."""

    def window(self, state, checks):
        """A stand-in for the window with the status line's own methods, the last ready check `checks`, no work under
        way and nothing drawn."""
        from opendmtq_client import app as launcher, i18n
        app = types.SimpleNamespace(state=state, checks=checks, busy=False, download=None, session=None,
                                    words=i18n.Words("en"), status_message=None, status_tone="normal",
                                    status_action=None, status_transient=False, status_sticky=False,
                                    update_found=None, _paint_status=lambda: None)
        for name in ("set_status", "user_acted", "_say_state", "ready", "busy_now", "_game_open", "server_answers",
                     "update_on_offer", "update_now"):
            setattr(app, name, getattr(launcher.LauncherApp, name).__get__(app))
        # The line's words as the window draws them (a property of the window's class).
        app.text = lambda: launcher.LauncherApp.status_text.fget(app)
        return app

    def test_an_outcome_gives_way_once_the_player_acts(self):
        # An installer's server taken while the window was open says "you play on it from now on"; the player then
        # picks another server (Online's Play here, which is acting): the line no longer claims the first.
        from opendmtq_client import actions, i18n
        state = st.LauncherState()
        state.add_server("http://stand.in", "Stand-in")
        state.add_server("http://club.test", "Club")
        app = self.window(state, [actions.Check("server", True, "Club")])
        app.set_status(i18n.Said("status.preset", name="Club"), "ok", sticky=True)
        self.assertIn("Club", app.text())
        state.current = "http://stand.in"
        app.user_acted()
        self.assertEqual((app.status_message.key, app.status_tone), ("status.ready", "normal"))
        # A red outcome gives way the same way: a failure is about its moment, not about every page after it.
        app.set_status(i18n.Said("status.error", error=srv.ServerError("x", "error.app.failed")), "bad", sticky=True)
        app.user_acted()
        self.assertEqual(app.status_message.key, "status.ready")

    def test_what_is_kept_waits_for_the_player(self):
        # The ready check that comes right after an outcome (a game that ended) does not take its place: only the
        # player doing something does.
        from opendmtq_client import actions, i18n
        state = st.LauncherState()
        state.add_server("http://stand.in", "Stand-in")
        app = self.window(state, [actions.Check("server", True, "Stand-in")])
        app.set_status(i18n.Said("status.ended", time=i18n.span(130)), "ok", sticky=True)
        app._say_state()
        self.assertEqual(app.text(), "The game closed after 2 min.")
        # Work under way says its own words: the state is not said over them.
        app.user_acted()
        app.busy = True
        app.set_status(i18n.Said("status.app_check"), "normal")
        app._say_state()
        self.assertEqual(app.status_message.key, "status.app_check")

    def test_a_newer_launcher_is_said_while_play_is_ready(self):
        # The look at the start found one: the line says it, with its update, in PLAY's ready state; a state to fix and
        # a kept outcome come first, and it comes back once they give way.
        from opendmtq_client import actions, i18n, updates
        state = st.LauncherState()
        state.add_server("http://stand.in", "Stand-in")
        app = self.window(state, [actions.Check("server", True, "Stand-in")])
        app.set_status(i18n.Said("status.ended", time=i18n.span(130)), "ok", sticky=True)
        app.update_on_offer(updates.Result("available", version="9.9.9"))
        self.assertEqual(app.text(), "The game closed after 2 min.")
        app.user_acted()
        self.assertEqual(app.text(), "OpenDMTQ 9.9.9 is available.")
        words, action = app.status_action
        self.assertEqual(app.words.say(words), "Update to 9.9.9")
        # Something to fix first: said instead, the update waiting for PLAY to be ready again.
        app.checks = [actions.Check("app", False, "none on this PC", page="online")]
        app._say_state()
        self.assertEqual(app.status_message.key, "status.fix_first")
        self.assertIsNone(app.status_action)

    def test_a_kept_line_says_itself_again_in_the_new_language(self):
        # The window switched to Korean redraws its line from what it kept, not from the English sentence it showed.
        from opendmtq_client import actions, i18n
        state = st.LauncherState()
        state.add_server("http://stand.in", "Stand-in")
        app = self.window(state, [actions.Check("server", True, "Stand-in")])
        app.set_status(i18n.Said("status.error", error=srv.ServerError("x", "error.app.failed")), "bad", sticky=True)
        english = app.text()
        app.words = i18n.Words("ko")
        self.assertNotEqual(app.text(), english)
        self.assertEqual(app.text(), i18n.Words("ko")("error.app.failed"))
        # A span of time inside the words is said in the new language too.
        app.set_status(i18n.Said("status.ended", time=i18n.span(130)), "ok", sticky=True)
        self.assertEqual(app.text(), i18n.Words("ko")("status.ended", time=i18n.Words("ko")("common.minutes", m=2)))

    def test_a_server_that_does_not_answer_is_said_while_play_can_go(self):
        # Ready with the app this PC has, the server not answering: the line says so, in the warning's tone.
        from opendmtq_client import actions
        state = st.LauncherState()
        state.add_server("http://stand.in", "Stand-in")
        down = actions.Check("server", False, "Cannot reach it.", page="online", blocks=False)
        app = self.window(state, [down, actions.Check("app", True, "2026-11-09")])
        app._say_state()
        self.assertEqual((app.status_message.key, app.status_tone), ("status.server_down", "warn"))
