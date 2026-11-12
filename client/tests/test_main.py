"""The command line: the same jobs as the window, with y/N before what cannot be undone."""

import contextlib
import io
import json
import os
import sys
import threading
import types
import unittest

import subprocess
import zipfile
from unittest import mock

from opendmtq_client import apps, main, playing, preset, removal
from opendmtq_client import state as st
from opendmtq_client import values as choices
from tests import stub
from tests.base import Folder
from tests.test_removal import GAME, listing, write


class CommandLine(Folder):
    def setUp(self):
        super().setUp()
        self.site = stub.Site().start()

    def tearDown(self):
        self.site.stop()
        super().tearDown()

    def run_main(self, args, stdin=""):
        """main() with these arguments and this standard input; (exit code, what it printed)."""
        out = io.StringIO()
        saved = sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = main.main(args)
        finally:
            sys.stdin = saved
        return code, out.getvalue()

    def test_from_nothing_to_playing(self):
        code, said = self.run_main(["--status"])
        self.assertEqual(code, 1)
        self.assertIn("server: none", said)
        code, said = self.run_main(["--server", self.site.url, "--sign-in", stub.ACCOUNT], stdin=stub.PASSWORD + "\n")
        self.assertEqual(code, 0, said)
        self.assertIn("Signed in as %s" % stub.ACCOUNT, said)
        self.assertNotIn(stub.PASSWORD, said)
        code, said = self.run_main(["--app"])
        self.assertEqual(code, 0, said)
        self.assertIn("Downloaded the app", said)
        code, said = self.run_main(["--set", "fps=144", "--set", "vsync=off", "--set", "render_scale=50", "--set",
                                    "upscaler=fsr1", "--set", "anti_aliasing=cmaa2", "--set", "show_fps=bottom_left",
                                    "--status"])
        self.assertEqual(code, 0, said)
        self.assertIn("fps=144", said)
        # A corner as show_fps's value, as before: the counter on, in that corner.
        self.assertIn("show_fps=on, fps_position=bottom_left", said)
        self.assertNotIn(self.site.cookie, said)
        code, said = self.run_main(["--play"])
        self.assertEqual(code, 0, said)
        # The player's settings file carries them, the upscaler and the anti-aliasing among them.
        for line in ("vsync=off", "render_scale=50", "upscaler=fsr1", "anti_aliasing=cmaa2", "show_fps=bottom_left"):
            self.assertIn(line, self.started()["settings"])

    def test_a_wrong_password(self):
        self.run_main(["--server", self.site.url])
        code, said = self.run_main(["--sign-in", stub.ACCOUNT], stdin="wrong\n")
        self.assertEqual(code, 2)
        self.assertIn("wrong", said)

    def test_an_address_that_is_none(self):
        # The window's check and words: refused before anything is asked, exit 2, no traceback, nothing kept.
        from opendmtq_client import i18n
        from opendmtq_client import server as srv
        for bad in ("not an address", "example .com:8080"):
            code, said = self.run_main(["--server", bad])
            self.assertEqual(code, 2, said)
            self.assertNotIn("Traceback", said)
            words = i18n.Words("en")("error.server.address", address=bad)
            self.assertEqual(said.strip(), words)
        self.assertEqual(st.LauncherState.load().servers, [])
        self.assertEqual(srv.normalize(self.site.url), self.site.url)

    def test_a_bad_setting(self):
        code, said = self.run_main(["--set", "fps=12"])
        self.assertEqual(code, 2)
        self.assertEqual(st.LauncherState.load().values["fps"], "auto")
        # An upscaler the launcher does not offer is refused the same way.
        code, said = self.run_main(["--set", "upscaler=dlss"])
        self.assertEqual(code, 2)
        self.assertEqual(st.LauncherState.load().values["upscaler"], "bilinear")

    def test_the_frame_counter(self):
        # On by its own name at the bottom right; its corner by fps_position; off keeps the corner for the next time; a
        # place that is no corner refused.
        code, said = self.run_main(["--set", "show_fps=on"])
        self.assertEqual(code, 0, said)
        self.assertIn("show_fps=on, fps_position=bottom_right", said)
        code, said = self.run_main(["--set", "fps_position=top_right"])
        self.assertEqual(code, 0, said)
        self.assertEqual(choices.settings_text(st.LauncherState.load().values).count("show_fps=top_right"), 1)
        code, said = self.run_main(["--set", "show_fps=off"])
        self.assertEqual(code, 0, said)
        values = st.LauncherState.load().values
        self.assertEqual((values["show_fps"], values["fps_position"]), ("off", "top_right"))
        code, said = self.run_main(["--set", "fps_position=middle"])
        self.assertEqual(code, 2)
        self.assertEqual(st.LauncherState.load().values["fps_position"], "top_right")

    def test_keyboard_play_and_the_lanes_keys(self):
        # Keyboard play and each LINE mode's keys by --set, checked as the Controls page checks them: the names kept as
        # the player takes them, a refusal said with its reason and that setting left as it was; --status lists them,
        # and PLAY's settings file carries them.
        code, said = self.run_main(["--set", "keyboard=off", "--set", "keys_2line=f/g j", "--set", "keys_4line=1 2 3 4"])
        self.assertEqual(code, 0, said)
        for line in ("keyboard=off", "keys_2line=F/G J", "keys_4line=1 2 3 4"):
            self.assertIn(line, said)
        values = st.LauncherState.load().values
        self.assertEqual((values["keyboard"], values["keys_2line"], values["keys_4line"]), ("off", "F/G J", "1 2 3 4"))
        # A key in two lanes, a key no lane takes, a lane short: each refused with why, nothing of it kept.
        for value, why in (("D F F", "F is in lane 2 and lane 3"), ("D F Enter", "Enter is no key a lane takes"),
                           ("D F", "3 lanes")):
            code, said = self.run_main(["--set", "keys_3line=" + value])
            self.assertEqual(code, 2, said)
            self.assertIn(why, said)
            self.assertNotIn("Traceback", said)
            self.assertEqual(st.LauncherState.load().values["keys_3line"], "D F J")
        code, said = self.run_main(["--set", "keyboard=maybe"])
        self.assertEqual(code, 2, said)
        code, said = self.run_main(["--status"])
        self.assertIn("keyboard=off, keys_2line=F/G J, keys_3line=D F J, keys_4line=1 2 3 4", said)
        # PLAY writes them for the player, after the sound's.
        code, said = self.run_main(["--server", self.site.url, "--sign-in", stub.ACCOUNT, "--set", "keyboard=on"],
                                   stdin=stub.PASSWORD + "\n")
        self.assertEqual(code, 0, said)
        code, said = self.run_main(["--play"])
        self.assertEqual(code, 0, said)
        lines = self.started()["settings"].splitlines()
        self.assertEqual(lines[lines.index("volume=100") + 1:lines.index("volume=100") + 5],
                         ["keyboard=on", "keys_2line=F/G J", "keys_3line=D F J", "keys_4line=1 2 3 4"])

    def test_audio_devices(self):
        code, said = self.run_main(["--audio-devices"])
        self.assertEqual(code, 0)
        self.assertIn("Speakers (made up)  (default)", said)

    def test_reset_asks_first(self):
        self.run_main(["--server", self.site.url, "--sign-in", stub.ACCOUNT], stdin=stub.PASSWORD + "\n")
        self.run_main(["--app"])
        code, said = self.run_main(["--reset"], stdin="n\n")
        self.assertEqual(code, 1)
        self.assertIsNotNone(st.LauncherState.load().server())
        code, said = self.run_main(["--reset", "--yes"])
        self.assertEqual(code, 0)
        self.assertIsNone(st.LauncherState.load().server())
        self.assertFalse(os.path.isdir(apps.folder(self.site.url)))

    def test_forget_asks_first(self):
        self.run_main(["--server", self.site.url])
        code, _ = self.run_main(["--forget", self.site.url], stdin="\n")
        self.assertEqual(code, 1)
        code, _ = self.run_main(["--forget", self.site.url, "--yes"])
        self.assertEqual(code, 0)
        self.assertEqual(st.LauncherState.load().servers, [])

    def test_reset_and_forget_wait_for_the_game(self):
        # A game from the window or another command plays from the server's app, which both delete.
        self.run_main(["--server", self.site.url])
        with mock.patch.object(playing, "running", return_value=True):
            for args in (["--reset", "--yes"], ["--forget", self.site.url, "--yes"]):
                code, said = self.run_main(args)
                self.assertEqual(code, 2, args)
                self.assertIn("Close the game first", said)
        self.assertIsNotNone(st.LauncherState.load().server(self.site.url))

    def test_an_app_kept_with_no_package_name_is_got_again(self):
        # An app an older launcher kept with a package name that is none: --status shows no log for it, and PLAY gets
        # the server's app again before it starts the game (with the server away it does not start: test_actions).
        self.run_main(["--server", self.site.url, "--sign-in", stub.ACCOUNT], stdin=stub.PASSWORD + "\n")
        self.run_main(["--app"])
        details = os.path.join(apps.folder(self.site.url), apps.DETAILS)
        with open(details, encoding="utf-8") as f:
            kept = json.load(f)
        kept["package"] = "../../elsewhere"
        with open(details, "w", encoding="utf-8") as f:
            json.dump(kept, f)
        code, said = self.run_main(["--status"])
        self.assertIn("player log: none yet", said)
        code, said = self.run_main(["--play"])
        self.assertEqual(code, 0, said)
        with open(details, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["package"], self.site.describe()["package"])

    def test_the_installers_server_is_taken_at_start(self):
        # Written with a path after it: the launcher keeps it as it writes every address, so connecting finds the same one.
        preset.hand_over({"url": self.site.url + "/opendmtq/", "name": "From the site"})
        code, said = self.run_main(["--status"])
        self.assertIn("server: From the site (%s)" % self.site.url, said)
        self.assertIsNone(preset.take())
        self.run_main(["--server", self.site.url])
        self.assertEqual([s["url"] for s in st.LauncherState.load().servers], [self.site.url])

    def test_language_guide_and_logs(self):
        # The window's Language choice, "Show it again" and Help's log buttons, from the command line.
        code, said = self.run_main(["--language", "ko", "--guide"])
        self.assertEqual(code, 0, said)
        saved = st.LauncherState.load()
        self.assertEqual(saved.language, "ko")
        self.assertFalse(saved.guide_done)
        code, said = self.run_main(["--status"])
        self.assertIn("language: ko", said)
        self.assertIn("launcher log: ", said)
        self.assertIn("player log: none yet", said)
        # No app yet: no player's log to open, said plainly (and no Explorer from a test).
        code, said = self.run_main(["--open-log", "player"])
        self.assertEqual(code, 2)
        self.assertIn("no player's log yet", said)
        # A launcher log that is not there yet: said, and nothing made in its place.
        logs = os.path.join(st.config_dir(), "logs")
        os.remove(os.path.join(logs, "launcher.log"))
        with mock.patch.object(main, "_logging"):
            code, said = self.run_main(["--open-log", "launcher"])
        self.assertEqual(code, 2)
        self.assertIn("There is no launcher's log yet", said)
        self.assertEqual(os.listdir(logs), [])

    def test_a_known_server_without_its_site(self):
        # Switching to a server this launcher knows works while that server does not answer, as "Play here" does.
        self.run_main(["--server", self.site.url])
        known = self.site.url
        self.site.stop()
        other = stub.Site().start()
        try:
            self.run_main(["--server", other.url])
            code, said = self.run_main(["--server", known])
            self.assertEqual(code, 0, said)
            self.assertEqual(st.LauncherState.load().current, known)
        finally:
            other.stop()
            # tearDown stops self.site: a fresh one, since the first is stopped already.
            self.site = stub.Site().start()

    def test_the_start_up_dialog_in_both_languages(self):
        # The dialog for settings that cannot be read: its words in the language asked, the file named in both.
        broken = st.StateError("cannot read", "C:\\settings.json")
        newer = st.StateError("newer", "C:\\settings.json", newer=True)
        self.assertEqual(main.cannot_start_dialog(broken, "en")[2], "The launcher's settings cannot be read.")
        asked = main.cannot_start_dialog(broken, "ko")
        self.assertEqual(asked[2], "런처 설정을 읽을 수 없습니다.")
        self.assertIn("C:\\settings.json", asked[3])
        self.assertEqual([b[1] for b in asked[4]], ["close", "reset"])
        self.assertEqual([b[1] for b in main.cannot_start_dialog(newer, "ko")[4]], ["close"])

    def test_unknown_arguments_are_refused(self):
        # A mistyped option is said, never ignored; Velopack's own arguments and their values pass.
        out = io.StringIO()
        with contextlib.redirect_stderr(out), self.assertRaises(SystemExit) as caught:
            main.parse(["--stauts"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("--stauts", out.getvalue())
        self.assertTrue(main.parse(["--veloapp-updated", "0.8.0", "--status"]).status)

    def test_changes_wait_for_the_window(self):
        # With the window open, a change here would be written over by the window's own copy: refused, said so.
        saved = main.window_open
        main.window_open = lambda: True
        try:
            code, said = self.run_main(["--set", "fps=144"])
            self.assertEqual(code, 2)
            self.assertIn("window is open", said)
            self.assertEqual(st.LauncherState.load().values["fps"], "auto")
            # Reading is fine.
            code, said = self.run_main(["--status"])
            self.assertIn("settings: ", said)
        finally:
            main.window_open = saved

    def test_back_to_windows_language(self):
        self.run_main(["--language", "ko"])
        self.assertEqual(st.LauncherState.load().picked_language, "ko")
        code, said = self.run_main(["--language", "system"])
        self.assertEqual(code, 0, said)
        self.assertIsNone(st.LauncherState.load().picked_language)
        self.assertIn("language=system", said)

    def test_status_asks_the_server(self):
        # --status asks the server as the window's ready check does: one that stopped answering is said as a warning,
        # and PLAY can still go with the app this PC has (exit 0).
        self.run_main(["--server", self.site.url])
        self.run_main(["--sign-in", stub.ACCOUNT], stdin=stub.PASSWORD + "\n")
        self.run_main(["--app"])
        code, said = self.run_main(["--status"])
        self.assertEqual(code, 0, said)
        self.assertIn("[ok  ] server:", said)
        self.site.stop()
        try:
            code, said = self.run_main(["--status"])
        finally:
            self.site.start()
        self.assertEqual(code, 0, said)
        self.assertIn("[warn] server:", said)

    def test_status_says_a_newer_launcher_on_offer(self):
        # The window's look at its start, from the command line: the launcher's version, and a newer one when the
        # release feed has it; without a network, after a failure or past the time limit, the version alone. The exit
        # code stays PLAY's.
        import time
        from opendmtq_client import __version__, updates
        self.run_main(["--server", self.site.url])
        offer = updates.Result("available", version="9.9.9")
        with mock.patch.object(updates, "check", return_value=offer):
            code, said = self.run_main(["--status"])
        self.assertEqual(code, 1, said)
        self.assertIn("launcher: %s; OpenDMTQ 9.9.9 is available (--update)\n" % __version__, said)
        with mock.patch.object(updates, "check", return_value=updates.Result("failed", error="Network error: io")):
            code, said = self.run_main(["--status"])
        self.assertIn("launcher: %s\n" % __version__, said)
        self.assertNotIn("available", said)
        self.assertNotIn("Network error", said)

        def slow():
            # A feed that answers long after the limit (a network that drops what it is sent).
            time.sleep(3)
            return offer

        with mock.patch.object(updates, "check", side_effect=slow), mock.patch.object(updates, "START_LIMIT", 0.3):
            started = time.monotonic()
            code, said = self.run_main(["--status"])
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertIn("launcher: %s\n" % __version__, said)
        self.assertNotIn("available", said)

    def test_the_servers_it_knows_and_the_guide_skipped(self):
        # Online's list of servers and the guide's "Skip: I set it up myself", from the command line: a PC set up with
        # --server, --sign-in and --app opens on PLAY with --skip-guide.
        code, said = self.run_main(["--servers"])
        self.assertEqual(code, 0, said)
        self.assertIn("No servers yet", said)
        self.run_main(["--server", self.site.url])
        state = st.LauncherState.load()
        state.add_server("http://192.0.2.10:8080", "Other")
        state.current = self.site.url
        state.save()
        code, said = self.run_main(["--servers"])
        lines = [line for line in said.splitlines() if "(" in line]
        self.assertEqual(lines, ["* Stand-in (%s)" % self.site.url, "  Other (http://192.0.2.10:8080)"])
        self.assertFalse(st.LauncherState.load().guide_done)
        code, said = self.run_main(["--skip-guide"])
        self.assertEqual(code, 0, said)
        self.assertTrue(st.LauncherState.load().guide_done)
        # --guide and --skip-guide undo each other, as Launcher's "Show it again" and the guide's Skip do.
        self.run_main(["--guide"])
        self.assertFalse(st.LauncherState.load().guide_done)

    def test_a_window_size_must_fit_the_display(self):
        # --set window= takes what the Screen page offers: a size that fits the main display with room for the title
        # bar and the taskbar, refused otherwise with nothing changed; auto always; any while the display is unknown.
        from opendmtq_client import displays
        with mock.patch.object(displays, "main_display", return_value={"width": 1920, "height": 1080, "hz": 60}):
            code, said = self.run_main(["--set", "window=1920x1080", "--set", "volume=40"])
            self.assertEqual(code, 2)
            self.assertIn("does not fit this 1920 x 1080 display", said)
            self.assertEqual(st.LauncherState.load().values["volume"], 100)
            code, said = self.run_main(["--set", "window=1600x900"])
            self.assertEqual(code, 0, said)
            self.assertEqual(st.LauncherState.load().values["window"], "1600x900")
            code, said = self.run_main(["--set", "window=auto"])
            self.assertEqual(code, 0, said)
        with mock.patch.object(displays, "main_display", return_value={"width": 0, "height": 0, "hz": None}):
            code, said = self.run_main(["--set", "window=3840x2160"])
            self.assertEqual(code, 0, said)
        # Smaller than the game's window holds at Windows' scale on the display (300 % on a 4K one: 1440 x 810): refused
        # with its own words and nothing changed, as the Screen page leaves it out.
        with mock.patch.object(displays, "main_display", return_value={"width": 3840, "height": 2160, "hz": 60, "scale": 3.0}):
            code, said = self.run_main(["--set", "window=1280x720", "--set", "volume=30"])
            self.assertEqual(code, 2)
            self.assertIn("the game's window is at least 1440 x 810 on this display", said)
            self.assertEqual(st.LauncherState.load().values["volume"], 100)
            code, said = self.run_main(["--set", "window=1600x900"])
            self.assertEqual(code, 0, said)

    def test_language_as_a_setting(self):
        # --set language=... is --language's other spelling, as the settings' table lists it: the same three values,
        # anything else refused with nothing changed.
        code, said = self.run_main(["--set", "language=ko", "--set", "volume=40"])
        self.assertEqual(code, 0, said)
        saved = st.LauncherState.load()
        self.assertEqual((saved.picked_language, saved.values["volume"]), ("ko", 40))
        code, said = self.run_main(["--set", "language=system"])
        self.assertIsNone(st.LauncherState.load().picked_language)
        code, said = self.run_main(["--set", "language=fr"])
        self.assertEqual(code, 2)
        self.assertIn("language cannot be 'fr'", said)
        self.assertIsNone(st.LauncherState.load().picked_language)

    def test_the_setting_names_are_in_the_help(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            main.parse(["--help"])
        for name in ("vsync", "fps", "render_scale", "upscaler", "anti_aliasing", "show_fps", "fps_position", "audio_device",
                     "keyboard", "keys_2line", "keys_3line", "keys_4line"):
            self.assertIn(name, out.getvalue())

    def test_a_worker_threads_error_goes_to_the_log(self):
        # The window copy has no console: an error that ends a worker thread is in the launcher's log.
        main._logging()
        self.addCleanup(setattr, threading, "excepthook", threading.__excepthook__)

        def work():
            raise RuntimeError("the disk went away")

        thread = threading.Thread(target=work, name="updates")
        with contextlib.redirect_stderr(io.StringIO()):
            thread.start()
            thread.join()
        with open(os.path.join(st.config_dir(), "logs", "launcher.log"), encoding="utf-8") as f:
            logged = f.read()
        self.assertIn("the updates thread failed", logged)
        self.assertIn("RuntimeError: the disk went away", logged)

    def test_an_update_answer_without_its_release_is_a_failed_check(self):
        # Velopack's answer read where its errors are caught: said as a check that failed, as the Launcher page says
        # it, never an error that ends the check with the page still waiting.
        from opendmtq_client import updates
        answer = types.SimpleNamespace()
        velopack = types.SimpleNamespace(UpdateManager=lambda source: types.SimpleNamespace(
            check_for_updates=lambda: answer, get_current_version=lambda: "0.8.0"))
        with mock.patch.dict(sys.modules, {"velopack": velopack}), \
                mock.patch.object(updates, "UPDATE_SOURCE", "http://updates.test/"):
            self.assertEqual(updates.check().kind, "failed")
            code, said = self.run_main(["--update"])
        self.assertEqual(code, 2)
        self.assertIn("Could not check for updates", said)

    def test_an_update_check_that_fails_is_said_by_its_kind(self):
        # Velopack's own words (here as Wine gave them with no network) stay in the log; the console says what the
        # Launcher page says in English: what failed, and why by its kind.
        from opendmtq_client import updates

        def offline():
            raise RuntimeError("Network error: Http error: io: Nonauthoritative host not found. (os error 11002)")

        velopack = types.SimpleNamespace(UpdateManager=lambda source: types.SimpleNamespace(
            check_for_updates=offline, get_current_version=lambda: "0.8.0"))
        with mock.patch.dict(sys.modules, {"velopack": velopack}), \
                mock.patch.object(updates, "UPDATE_SOURCE", "http://updates.test/"):
            code, said = self.run_main(["--update"])
        self.assertEqual(code, 2)
        self.assertEqual(said.strip(), "Could not check for updates. This PC cannot reach the internet.")
        with open(st.launcher_log(), encoding="utf-8") as f:
            self.assertIn("Nonauthoritative host not found. (os error 11002)", f.read())

    def test_version(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            main.main(["--version"])
        self.assertTrue(out.getvalue().startswith("OpenDMTQ "))


class Maintenance(Folder):
    """--repair, --clear-game-data and --uninstall: Help's buttons, from the command line."""

    # The same way of running main() as above, without running the tests above a second time.
    run_main = CommandLine.run_main

    def setUp(self):
        super().setUp()
        self.site = stub.Site().start()
        # An install as Velopack lays it out: one file of the program, its package, and a stand-in Update.exe.
        self.install = os.path.join(self.home, "OpenDMTQ.Client")
        version = b"<version>0.8.0</version>"
        write(self.install, {"Update.exe": b"MZ", "current/sq.version": version, "current/OpenDMTQ.exe": b"launcher"})
        os.makedirs(os.path.join(self.install, "packages"))
        with zipfile.ZipFile(os.path.join(self.install, "packages", "OpenDMTQ.Client-0.8.0-full.nupkg"), "w") as z:
            z.writestr("lib/app/OpenDMTQ.exe", b"launcher")
        os.environ["OPENDMTQ_INSTALL_ROOT"] = self.install
        self.game = os.path.join(removal.data_root(), "com.example.game")
        write(self.game, GAME)

    def tearDown(self):
        os.environ.pop("OPENDMTQ_INSTALL_ROOT", None)
        self.site.stop()
        super().tearDown()

    def test_repair(self):
        code, said = self.run_main(["--repair"])
        self.assertEqual(code, 0)
        self.assertIn("All 1 files of the program are as installed.", said)
        os.remove(os.path.join(self.install, "current", "OpenDMTQ.exe"))
        code, said = self.run_main(["--repair"])
        self.assertEqual(code, 0)
        self.assertIn("missing: %s" % os.path.join("current", "OpenDMTQ.exe"), said)
        self.assertIn("Start the launcher again", said)
        self.assertTrue(os.path.isfile(os.path.join(self.install, "current", "OpenDMTQ.exe")))
        os.environ.pop("OPENDMTQ_INSTALL_ROOT")
        code, said = self.run_main(["--repair"])
        self.assertEqual(code, 2)
        self.assertIn("installed by OpenDMTQ-Setup.exe", said)

    def test_clear_game_data_asks_first(self):
        code, said = self.run_main(["--clear-game-data"], stdin="n\n")
        self.assertEqual(code, 1)
        self.assertEqual(listing(self.game), set(GAME))
        code, said = self.run_main(["--clear-game-data", "--yes"])
        self.assertEqual(code, 0)
        self.assertEqual(listing(self.game), {"data/android_id"})
        code, said = self.run_main(["--clear-game-data"])
        self.assertEqual((code, said.strip()), (0, "There is no game data on this PC."))

    def test_uninstall_keeps_the_data(self):
        self.run_main(["--server", self.site.url])
        with mock.patch.object(subprocess, "Popen") as popen:
            code, said = self.run_main(["--uninstall"], stdin="y\n")
        self.assertEqual(code, 0)
        self.assertEqual(popen.call_args[0][0][1:], ["--uninstall", "--silent"])
        self.assertEqual(listing(self.game), set(GAME))
        self.assertEqual(st.LauncherState.load().server()["url"], self.site.url)

    def test_uninstall_with_its_data(self):
        self.run_main(["--server", self.site.url])
        write(st.config_dir(), {"notes.txt": b"the player's own"})
        with mock.patch.object(subprocess, "Popen") as popen:
            code, said = self.run_main(["--uninstall", "--delete-data"], stdin="n\n")
        self.assertEqual(code, 1)
        popen.assert_not_called()
        with mock.patch.object(subprocess, "Popen") as popen:
            code, said = self.run_main(["--uninstall", "--delete-data", "--yes"])
        self.assertEqual(code, 0)
        popen.assert_called_once()
        # Velopack's log of this uninstall goes into the install folder, which goes whole after it.
        self.assertEqual(popen.call_args[0][0][1:], ["--uninstall", "--silent", "--log",
                                                     os.path.join(self.install, "uninstall.log")])
        self.assertFalse(os.path.exists(removal.data_root()))
        # The launcher's folder here is one of the test's choosing: the launcher's files went, the other stays.
        self.assertEqual(listing(st.config_dir()), {"notes.txt"})
        # Velopack's uninstall hook writes no log where none is left.
        os.environ["OPENDMTQ_CLIENT_DIR"] = os.path.join(removal.data_root(), "client")
        with self.assertRaises(SystemExit), mock.patch.object(main, "_velopack_hooks", side_effect=SystemExit(0)):
            self.run_main(["--veloapp-uninstall", "0.8.0"])
        self.assertFalse(os.path.exists(removal.data_root()))

    def test_velopacks_hooks_do_what_opendmtq_asks_of_them(self):
        # A stand-in for Velopack's module runs the hook its arguments name, as the real one does, then ends the process:
        # after an update Windows' entry is made quiet again; before an uninstall the card's copy is made.
        done, given = [], {}

        class App:
            def __init__(self):
                self.hooks = {}

            def on_after_update_fast_callback(self, callback):
                self.hooks["--veloapp-updated"] = callback

            def on_before_uninstall_fast_callback(self, callback):
                self.hooks["--veloapp-uninstall"] = callback

            def run(self):
                # Velopack reads the process's arguments: here, the ones this test gives main().
                hook = self.hooks.get(given["argv"][0])
                if hook:
                    hook(given["argv"][1])
                    raise SystemExit(0)

        velopack = types.SimpleNamespace(App=App)
        with mock.patch.dict(sys.modules, {"velopack": velopack}), \
                mock.patch("opendmtq_client.installed.quiet_uninstall", lambda folder=None: done.append("quiet")), \
                mock.patch.object(removal, "card_after_uninstall", lambda program=None: done.append("card")):
            for hook, said in (("--veloapp-updated", "quiet"), ("--veloapp-uninstall", "card")):
                given["argv"] = [hook, "0.9.6"]
                done.clear()
                with self.assertRaises(SystemExit):
                    self.run_main(given["argv"])
                self.assertEqual(done, [said])

    def test_the_card_after_an_uninstall_runs_on_its_own(self):
        # The copy the uninstall hook starts: its card, nothing of Velopack's, no window of the launcher's.
        with mock.patch.object(removal, "show_uninstalled", return_value=0) as card, \
                mock.patch.object(main, "_velopack_hooks") as hooks, mock.patch.object(main.dpi, "aware"):
            code, said = self.run_main(["--uninstalled", "4242"])
        self.assertEqual(code, 0)
        card.assert_called_once_with(4242)
        hooks.assert_not_called()

    def test_uninstall_waits_for_the_window_and_the_game(self):
        with mock.patch.object(main, "window_open", return_value=True), \
                mock.patch.object(subprocess, "Popen") as popen:
            code, said = self.run_main(["--uninstall", "--yes"])
        self.assertEqual(code, 2)
        self.assertIn("window is open", said)
        with mock.patch.object(playing, "running", return_value=True), \
                mock.patch.object(subprocess, "Popen") as popen:
            for job in (["--uninstall", "--yes"], ["--clear-game-data", "--yes"], ["--repair"]):
                code, said = self.run_main(job)
                self.assertEqual(code, 2, job)
                self.assertIn("Close the game first", said)
        popen.assert_not_called()
        self.assertEqual(listing(self.game), set(GAME))

    def test_a_game_started_during_the_question_stops_it(self):
        # Not running when the command starts, running once the player has answered y.
        with mock.patch.object(playing, "running", side_effect=[False, True]), \
                mock.patch.object(subprocess, "Popen") as popen:
            code, said = self.run_main(["--clear-game-data"], stdin="y\n")
        self.assertEqual(code, 2)
        self.assertIn("Close the game first", said)
        self.assertEqual(listing(self.game), set(GAME))
        with mock.patch.object(main, "window_open", side_effect=[False, True]), \
                mock.patch.object(subprocess, "Popen") as popen:
            code, said = self.run_main(["--uninstall", "--delete-data"], stdin="y\n")
        self.assertEqual(code, 2)
        self.assertIn("window is open", said)
        popen.assert_not_called()
        self.assertEqual(listing(self.game), set(GAME))

    def test_a_copied_folder_cannot_uninstall(self):
        os.environ.pop("OPENDMTQ_INSTALL_ROOT")
        code, said = self.run_main(["--uninstall", "--yes"])
        self.assertEqual(code, 2)
        self.assertIn("installed by OpenDMTQ-Setup.exe", said)

    def test_they_run_on_their_own(self):
        for args in (["--repair", "--status"], ["--uninstall", "--clear-game-data"], ["--delete-data"]):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                main.parse(args)


class Stopped(unittest.TestCase):
    """An error nobody expected ends in the launcher's own dialog (stopped.py), never in PyInstaller's box."""

    def failing(self):
        raise RuntimeError("the disk went away")

    def test_the_window_copy_says_it_in_the_launchers_dialog(self):
        from opendmtq_client import stopped
        with mock.patch.object(stopped, "windowed", return_value=True), mock.patch.object(stopped, "show") as show:
            self.assertEqual(stopped.run(self.failing, lambda: "C:\\logs\\launcher.log"), 1)
        error, path = show.call_args[0]
        self.assertEqual((str(error), path), ("the disk went away", "C:\\logs\\launcher.log"))

    def test_the_console_copy_says_it_on_the_console(self):
        from opendmtq_client import stopped
        out = io.StringIO()
        with mock.patch.object(stopped, "windowed", return_value=False), mock.patch.object(stopped, "show") as show, \
                contextlib.redirect_stderr(out):
            self.assertEqual(stopped.run(self.failing, lambda: "launcher.log"), 1)
        show.assert_not_called()
        self.assertIn("OpenDMTQ stopped: the disk went away (the log: launcher.log)", out.getvalue())

    def test_a_chosen_ending_is_no_error(self):
        from opendmtq_client import stopped
        with mock.patch.object(stopped, "show") as show, self.assertRaises(SystemExit):
            stopped.run(lambda: sys.exit(2), lambda: "launcher.log")
        show.assert_not_called()
        self.assertEqual(stopped.run(lambda: 0, lambda: "launcher.log"), 0)
