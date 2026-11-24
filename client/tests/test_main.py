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


# Put before the stand-in player's own lines: when menu.txt is beside it, the in-game menu's changes (its name=value
# lines) written into the settings file it was given, a moment into the game, as the player writes them.
IN_GAME_MENU = """\
import os, sys, time
_menu = os.path.join(os.path.dirname(os.path.abspath(__file__)), "menu.txt")
if "--settings" in sys.argv and os.path.isfile(_menu):
    time.sleep(0.05)
    _path = sys.argv[sys.argv.index("--settings") + 1]
    _changed = dict(line.split("=", 1) for line in open(_menu, encoding="utf-8").read().split())
    _kept = [line for line in open(_path, encoding="utf-8").read().splitlines() if line.split("=")[0] not in _changed]
    with open(_path + ".tmp", "w", encoding="utf-8", newline="\\n") as f:
        f.write("\\n".join(_kept + ["%s=%s" % item for item in _changed.items()]) + "\\n")
    os.replace(_path + ".tmp", _path)
"""


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

    def test_a_disabled_account(self):
        # Switched off on the server's Accounts page: said in the window's English words, exit 2, no sign-in kept.
        self.run_main(["--server", self.site.url])
        code, said = self.run_main(["--sign-in", stub.OFF], stdin=stub.PASSWORD + "\n")
        self.assertEqual(code, 2, said)
        self.assertIn("this account is disabled and cannot sign in", said)
        self.assertNotIn("wrong", said)
        self.assertFalse(st.LauncherState.load().server().get("cookie"))

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
        self.assertEqual(st.LauncherState.load().values["upscaler"], "fsr1")

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
        # Off as --set left it; on again.
        self.assertEqual(st.LauncherState.load().values["keyboard"], "off")
        code, said = self.run_main(["--set", "keyboard=on"])
        self.assertEqual(code, 0, said)
        self.assertEqual(st.LauncherState.load().values["keyboard"], "on")
        # PLAY writes them for the player, after the sound's.
        code, said = self.run_main(["--server", self.site.url, "--sign-in", stub.ACCOUNT, "--set", "keyboard=on"],
                                   stdin=stub.PASSWORD + "\n")
        self.assertEqual(code, 0, said)
        code, said = self.run_main(["--play"])
        self.assertEqual(code, 0, said)
        lines = self.started()["settings"].splitlines()
        self.assertEqual(lines[lines.index("eq_high=0") + 1:lines.index("eq_high=0") + 5],
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

    def test_the_id_play_on_this_pc_brings_is_filled_in_until_a_sign_in(self):
        # The server PC's own installer (Play on this PC) brings the owner's ID with the server: the sign-in has it to
        # fill in, --status says no sign-in yet (none ended), and the first sign-in that works takes its place.
        preset.hand_over({"url": self.site.url, "name": "From the site", "account": stub.ACCOUNT})
        code, said = self.run_main(["--status"])
        self.assertIn("signed in: no\n", said + "\n")
        self.assertNotIn("ended", said)
        server = st.LauncherState.load().server()
        self.assertEqual((server["fill"], server["account"]), (stub.ACCOUNT, None))
        code, said = self.run_main(["--sign-in", stub.ACCOUNT], stdin=stub.PASSWORD + "\n")
        self.assertEqual(code, 0, said)
        server = st.LauncherState.load().server()
        self.assertEqual((server["fill"], server["account"]), (None, stub.ACCOUNT))
        # Brought again while that sign-in holds: it stays as it is.
        preset.hand_over({"url": self.site.url, "name": "From the site", "account": "admin"})
        self.run_main(["--status"])
        self.assertIsNone(st.LauncherState.load().server()["fill"])

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

    def test_status_says_the_last_games_sound(self):
        # The last game's sound as the player wrote it beside the settings (last-game-sound.txt), as the Sound page's
        # Last game card says it; none before the first game, and gaps marked.
        from tests.base import SOUND_RESULT
        from opendmtq_client import player
        code, said = self.run_main(["--status"])
        self.assertIn("last game: none yet", said)
        os.makedirs(os.path.dirname(player.result_path()), exist_ok=True)
        with open(player.result_path(), "w", encoding="utf-8") as f:
            f.write(SOUND_RESULT)
        code, said = self.run_main(["--status"])
        self.assertIn("last game: Shared, 10 ms period, 18 ms out, no gaps", said)
        with open(player.result_path(), "w", encoding="utf-8") as f:
            f.write(SOUND_RESULT.replace("game_gaps=0", "game_gaps=4"))
        code, said = self.run_main(["--status"])
        self.assertIn("last game: Shared, 10 ms period, 18 ms out, 4 gaps", said)
        # No sound device: said alone.
        with open(player.result_path(), "w", encoding="utf-8") as f:
            f.write(SOUND_RESULT.replace("mode=shared\n", "mode=none\n"))
        code, said = self.run_main(["--status"])
        self.assertIn("last game: No sound device\n", said)

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

    def test_an_update_answer_of_no_shape_foreseen_is_a_failed_check(self):
        # Whatever the feed's answer is, the check ends: said as a check that failed, as the Launcher page says it,
        # never an error that ends the check with the page still waiting.
        from opendmtq_client import updates
        velopack = types.SimpleNamespace(UpdateManager=lambda source: types.SimpleNamespace(
            get_current_version=lambda: "0.8.0"))
        with mock.patch.dict(sys.modules, {"velopack": velopack}), \
                mock.patch.object(updates, "UPDATE_SOURCE", "http://updates.test/kanggu12/openDMTQ"), \
                mock.patch.object(updates, "_latest_tag", side_effect=AttributeError("no such field")):
            self.assertEqual(updates.check().kind, "failed")
            code, said = self.run_main(["--update"])
        self.assertEqual(code, 2)
        self.assertIn("Could not check for updates", said)

    def test_an_update_check_that_fails_is_said_by_its_kind(self):
        # Python's own words for no network, as Windows gives them (getaddrinfo's 11001), stay in the log; the console
        # says what the Launcher page says in English: what failed, and why by its kind.
        import socket
        import urllib.error
        from opendmtq_client import updates
        offline = urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
        velopack = types.SimpleNamespace(UpdateManager=lambda source: types.SimpleNamespace(
            get_current_version=lambda: "0.8.0"))
        with mock.patch.dict(sys.modules, {"velopack": velopack}), \
                mock.patch.object(updates, "UPDATE_SOURCE", "http://updates.test/kanggu12/openDMTQ"), \
                mock.patch.object(updates, "_latest_tag", side_effect=offline):
            code, said = self.run_main(["--update"])
        self.assertEqual(code, 2)
        self.assertEqual(said.strip(), "Could not check for updates. This PC cannot reach the internet.")
        with open(st.launcher_log(), encoding="utf-8") as f:
            self.assertIn("[Errno 11001] getaddrinfo failed", f.read())

    def test_update_names_its_server_and_says_a_refusal(self):
        # CLI-40: --update as the Launcher page: the server PLAY plays on first, named when the update is its own, and a
        # release its project did not sign said in the window's words, with nothing put in.
        from opendmtq_client import updates
        self.run_main(["--server", self.site.url])
        server = st.LauncherState.load().server()
        source = updates.Source("server", server["url"], server)
        velopack = types.SimpleNamespace(UpdateManager=lambda source: types.SimpleNamespace(
            get_current_version=lambda: "0.8.0"))
        with mock.patch.dict(sys.modules, {"velopack": velopack}), \
                mock.patch.object(updates, "release", side_effect=updates.Refused("not signed")):
            code, said = self.run_main(["--update"])
        self.assertEqual(code, 2)
        self.assertIn("is not signed by the OpenDMTQ project, so the launcher does not install it.", said)
        self.assertIn(source.label(), said)
        offer = updates.Result("available", version="9.9.9", source=source)
        with mock.patch.object(updates, "check", return_value=offer), \
                mock.patch.object(updates, "apply", side_effect=updates.UpdateError(
                    "x", "error.update.unsigned", v="9.9.9", source=source.label())):
            code, said = self.run_main(["--update", "--yes"])
        self.assertEqual(code, 2)
        self.assertIn("OpenDMTQ 9.9.9 is available from %s" % source.label(), said)
        self.assertIn("The update to 9.9.9 from %s is not signed by the OpenDMTQ project, so it was not installed."
                      % source.label(), said)

    def test_version(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            main.main(["--version"])
        self.assertTrue(out.getvalue().startswith("OpenDMTQ "))


class Twins(Folder):
    """The window's buttons that had no OpenDMTQ-cmd.exe twin: PLAY's My records and My page on the site, the Controls
    page's Reset keys, and the connection test's Use this address (main: no option for any of them)."""

    # main() as CommandLine runs it, without CommandLine's own tests run again here.
    run_main = CommandLine.run_main

    def setUp(self):
        super().setUp()
        self.site = stub.Site().start()
        self.addCleanup(self.site.stop)

    def signed_in(self):
        code, said = self.run_main(["--server", self.site.url, "--sign-in", stub.ACCOUNT], stdin=stub.PASSWORD + "\n")
        self.assertEqual(code, 0, said)

    def test_my_records(self):
        # Each list under its name, each record as the PLAY page shows it: the chart, the score, the keyboard's mark, the
        # place on the chart, when, and a play's new record or a best's grade.
        self.signed_in()
        recent, best = self.site.records["recent"][0], self.site.records["best"][0]
        code, said = self.run_main(["--records"])
        self.assertEqual(code, 0, said)
        self.assertIn("Recent plays: %s: 3 LINE Hard 9, 987,654, Keyboard play, #1 of 4, 5 min ago, New record"
                      % recent["title"], said)
        self.assertIn("Best records: %s: 3 LINE Hard 9, 987,654, Keyboard play, #1 of 4, 5 min ago, Grade S"
                      % best["title"], said)
        self.assertEqual(said.count("Recent plays: "), len(self.site.records["recent"]))
        # A chart whose song the song list no longer has: by its number, as the page names it.
        self.site.records["recent"][0] = dict(recent, title=None)
        code, said = self.run_main(["--records"])
        self.assertIn("Recent plays: Chart %d: 3 LINE Hard 9" % recent["chart"], said)
        # An account linked to no player: the page's one line.
        self.site.records = {"account": stub.ACCOUNT, "player": None, "recent": [], "best": []}
        code, said = self.run_main(["--records"])
        self.assertEqual((code, said.strip().splitlines()[-1]), (0, "%s is not linked to a player on this server."
                                                                  % stub.ACCOUNT))
        # A server older than records, and no sign-in: said, nothing else.
        self.site.records = None
        code, said = self.run_main(["--records"])
        self.assertEqual(code, 2, said)
        self.assertIn("keeps no records for PCs", said)
        self.run_main(["--sign-out"])
        code, said = self.run_main(["--records"])
        self.assertEqual(code, 2, said)
        self.assertIn("sign in to the server first", said)

    def test_my_page_on_the_site(self):
        # The one-time link the server makes, opened in the browser and never printed or logged; a server older than
        # such links: its site's own address.
        from opendmtq_client import actions
        self.signed_in()
        opened = []
        with mock.patch.object(actions, "open_url", opened.append):
            code, said = self.run_main(["--my-page"])
            self.assertEqual(code, 0, said)
            self.assertEqual(opened, [self.site.url + "/opendmtq/login.php?once=" + stub.LINK_TOKEN])
            self.assertIn("Your page on the site is open in the browser.", said)
            self.site.links = False
            code, said = self.run_main(["--my-page"])
            self.assertEqual((code, opened[-1]), (0, self.site.url + "/opendmtq/"))
            self.assertIn("The server's site is open in the browser.", said)
        with open(st.launcher_log(), encoding="utf-8") as f:
            self.assertNotIn(stub.LINK_TOKEN, f.read())
        # No browser to open it with: said, exit 2.
        self.site.links = True
        with mock.patch.object(actions, "open_url", side_effect=OSError("no browser")):
            code, said = self.run_main(["--my-page"])
        self.assertEqual(code, 2, said)
        self.assertIn("The browser did not open: no browser", said)
        self.assertNotIn(stub.LINK_TOKEN, said)
        # A sign-in that ended: said, and forgotten as the window forgets it.
        self.site.signed_cookies.clear()
        code, said = self.run_main(["--my-page"])
        self.assertEqual(code, 2, said)
        self.assertFalse(st.LauncherState.load().signed_in())

    def test_reset_keys(self):
        # Each LINE mode's keys back to their defaults, said as --set says them, and in the player's settings file at once.
        from opendmtq_client import player
        self.run_main(["--set", "keys_2line=f/g j", "--set", "keys_4line=1 2 3 4"])
        code, said = self.run_main(["--reset-keys"])
        self.assertEqual(code, 0, said)
        self.assertIn("keys_2line=F J, keys_3line=D F J, keys_4line=D F J K", said)
        values = st.LauncherState.load().values
        self.assertEqual([values[name] for name in choices.LANES], [choices.DEFAULTS[name] for name in choices.LANES])
        with open(player.settings_path(), encoding="utf-8") as f:
            self.assertIn("keys_2line=F J\n", f.read())
        # Refused while the window is open, as every change is.
        with mock.patch.object(main, "window_open", lambda: True):
            code, said = self.run_main(["--reset-keys"])
        self.assertEqual(code, 2, said)
        self.assertIn("window is open", said)

    def test_use_found_needs_what_the_last_test_found(self):
        # No test yet, or the last one found the server where it is: nothing to use, said with the step before.
        self.run_main(["--server", self.site.url])
        code, said = self.run_main(["--use-found"])
        self.assertEqual(code, 2, said)
        self.assertIn("found it at no other address: test it first (--test-server)", said)
        code, said = self.run_main(["--test-server", "--use-found"])
        self.assertEqual(code, 2, said)
        self.assertEqual(st.LauncherState.load().current, self.site.url)

    def test_use_found_moves_the_server_with_its_sign_in(self):
        # The test finds the server on another port of its host (its old port closed): --use-found plays on it there,
        # its sign-in kept and its app for the old address gone; refused while a game plays from that app, and while the
        # window is open.
        from opendmtq_client import connection
        from tests.test_connection import closed_port
        old = "http://127.0.0.1:%d" % closed_port()
        state = st.LauncherState()
        state.add_server(old, "Stand-in")
        state.server(old).update(account=stub.ACCOUNT, cookie=self.site.cookie, expires=1999999999)
        state.save()
        os.makedirs(apps.folder(old))
        port = int(self.site.url.rsplit(":", 1)[1])
        with mock.patch.object(connection, "PORTS", (closed_port(), port)):
            code, said = self.run_main(["--test-server"])
        self.assertEqual(code, 1, said)
        self.assertIn("An OpenDMTQ server answers at %s." % self.site.url, said)
        with mock.patch.object(playing, "running", return_value=True):
            code, said = self.run_main(["--use-found"])
        self.assertEqual(code, 2, said)
        self.assertIn("Close the game first", said)
        with mock.patch.object(main, "window_open", lambda: True):
            code, said = self.run_main(["--use-found"])
        self.assertEqual(code, 2, said)
        self.assertEqual(st.LauncherState.load().current, old)
        code, said = self.run_main(["--use-found"])
        self.assertEqual(code, 0, said)
        self.assertIn("Moved to Stand-in (%s): PLAY plays on it from now on." % self.site.url, said)
        state = st.LauncherState.load()
        self.assertEqual((state.current, [s["url"] for s in state.servers]), (self.site.url, [self.site.url]))
        self.assertTrue(state.signed_in())
        self.assertFalse(os.path.isdir(apps.folder(old)))
        # In a report, the name and the address where --use-found's line has them.
        from opendmtq_client import report
        path, _left = report.make(state, path=os.path.join(self.home, "r.zip"), devices=[])
        with zipfile.ZipFile(path) as z:
            log = z.read("launcher/launcher.log").decode("utf-8")
        self.assertIn("Moved to <server name> (<server>): PLAY plays on it from now on.", log)


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
        # The installer as players have it, never the build's own file name.
        self.assertIn("in the launcher the installer put on this PC", said)

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
        # Velopack's log of this uninstall goes into the install folder, which goes whole after it: nothing of
        # OpenDMTQ's stays but the data the player keeps.
        self.assertEqual(popen.call_args[0][0][1:], ["--uninstall", "--silent", "--log",
                                                     os.path.join(self.install, "uninstall.log")])
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
        # after an update Windows' entry is made OpenDMTQ's own again; its uninstall asks nothing more of OpenDMTQ (the
        # installer's own uninstall asked and says what went), so no hook is given for it.
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
                # A hook's process ends here whether or not OpenDMTQ gave one, as Velopack ends it.
                if given["argv"][0].startswith("--veloapp-"):
                    raise SystemExit(0)

        velopack = types.SimpleNamespace(App=App)
        with mock.patch.dict(sys.modules, {"velopack": velopack}), \
                mock.patch("opendmtq_client.installed.own_entry", lambda folder=None: done.append("own")):
            for hook, said in (("--veloapp-updated", ["own"]), ("--veloapp-uninstall", [])):
                given["argv"] = [hook, "0.9.6"]
                done.clear()
                with self.assertRaises(SystemExit):
                    self.run_main(given["argv"])
                self.assertEqual(done, said)

    def test_windows_apps_opens_the_installers_own_uninstall(self):
        # Windows' Settings, Apps runs the installed launcher with --uninstall-window: it starts its copy outside the
        # program's folder and ends; the copy (--uninstall-from FOLDER) is the installer's own uninstall, then goes a
        # few seconds after it. Neither runs Velopack's start-up handling, makes Windows' entry again, nor asks for the
        # launcher's settings.
        from opendmtq_client import installed, installer
        with mock.patch.object(removal, "start_uninstall_window") as copy, \
                mock.patch.object(main, "_velopack_hooks") as hooks, mock.patch.object(main, "_own_entry") as entry, \
                mock.patch.object(main.dpi, "aware"):
            code, said = self.run_main([installed.UNINSTALL_WINDOW])
        self.assertEqual(code, 0)
        copy.assert_called_once_with(self.install)
        hooks.assert_not_called()
        entry.assert_not_called()
        from opendmtq_client import stopped
        with mock.patch.object(installer, "uninstall_main", return_value=0) as uninstall, \
                mock.patch.object(removal, "remove_later") as later, \
                mock.patch.object(main, "_velopack_hooks") as hooks, mock.patch.object(main.dpi, "aware"), \
                mock.patch.object(stopped, "FRAMELESS", False):
            code, said = self.run_main([main.UNINSTALL_FROM, self.install])
            # The installer's own window: an error that ends it is said without Windows' title bar (stopped.py).
            self.assertTrue(stopped.FRAMELESS)
        self.assertEqual(code, 0)
        uninstall.assert_called_once_with(self.install)
        later.assert_called_once_with(os.path.dirname(os.path.abspath(sys.executable)))
        hooks.assert_not_called()
        # A launcher Windows did not install has nothing to uninstall: said in the log, nothing copied.
        os.environ.pop("OPENDMTQ_INSTALL_ROOT")
        with mock.patch.object(removal, "start_uninstall_window") as copy, mock.patch.object(main.dpi, "aware"):
            code, said = self.run_main([installed.UNINSTALL_WINDOW])
        self.assertEqual(code, 2)
        copy.assert_not_called()

    def test_the_uninstalls_own_runs_make_no_log_folder(self):
        # The copy from Windows' Apps may run after the data was deleted: its log is written only where its folder is.
        from opendmtq_client import installer
        import shutil
        shutil.rmtree(removal.data_root(), ignore_errors=True)
        from opendmtq_client import stopped
        with mock.patch.object(installer, "uninstall_main", return_value=0), \
                mock.patch.object(removal, "remove_later"), mock.patch.object(main.dpi, "aware"), \
                mock.patch.object(stopped, "FRAMELESS", False):
            self.run_main([main.UNINSTALL_FROM, self.install])
        self.assertFalse(os.path.exists(os.path.dirname(st.launcher_log())))

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
        self.assertIn("in the launcher the installer put on this PC", said)

    def test_a_bad_setting_anywhere_changes_none(self):
        # Every --set is checked before any is applied, as window= is: a refusal in the second leaves the first as it
        # was, and nothing is said as changed.
        code, said = self.run_main(["--set", "keys_4line=1 2 3 4", "--set", "keys_2line=F F"])
        self.assertEqual(code, 2, said)
        values = st.LauncherState.load().values
        self.assertEqual((values["keys_4line"], values["keys_2line"]), ("D F J K", "F J"))
        self.assertNotIn("keys_4line=1 2 3 4", said)
        # The same for the picture's and the sound's settings before a bad one.
        code, said = self.run_main(["--set", "volume=40", "--set", "fps=12"])
        self.assertEqual(code, 2, said)
        self.assertEqual(st.LauncherState.load().values["volume"], 100)
        # All good: all applied, in order.
        code, said = self.run_main(["--set", "volume=40", "--set", "keys_2line=d k"])
        self.assertEqual(code, 0, said)
        values = st.LauncherState.load().values
        self.assertEqual((values["volume"], values["keys_2line"]), (40, "D K"))

    def test_the_sound_settings_one_by_one(self):
        # Master, music, effects and the equaliser by --set, each said back; a band set alone makes the equaliser custom;
        # --status lists them all; the player's settings file has them at once, as the window writes it at a change.
        from opendmtq_client import player
        code, said = self.run_main(["--set", "music_volume=40", "--set", "effects_volume=70", "--set", "eq=bass"])
        self.assertEqual(code, 0, said)
        for line in ("music_volume=40", "effects_volume=70", "eq=bass"):
            self.assertIn(line, said)
        code, said = self.run_main(["--set", "eq_low=-3"])
        self.assertEqual(code, 0, said)
        values = st.LauncherState.load().values
        self.assertEqual((values["eq"], values["eq_low"], values["eq_mid"]), ("custom", -3, 0))
        with open(player.settings_path(), encoding="utf-8") as f:
            written = f.read().splitlines()
        for line in ("music_volume=40", "effects_volume=70", "eq=custom", "eq_low=-3", "eq_mid=0", "eq_high=0"):
            self.assertIn(line, written)
        code, said = self.run_main(["--status"])
        for name in ("music_volume=40", "effects_volume=70", "eq=custom", "eq_low=-3", "eq_mid=0", "eq_high=0"):
            self.assertIn(name, said)
        # Out of range, and the frame limit as any rate in the player's range (a 160 Hz display's own).
        code, said = self.run_main(["--set", "eq_high=13"])
        self.assertEqual(code, 2, said)
        code, said = self.run_main(["--set", "fps=160"])
        self.assertEqual(code, 0, said)
        self.assertEqual(st.LauncherState.load().values["fps"], "160")

    def test_the_sound_set_in_the_game_stays_after_it(self):
        # --play's game, in which the in-game menu sets master 29 and the bass preset: the stand-in writes them into the
        # settings file it was given as the player does (the whole file again, through a rename). They are the
        # launcher's when the game ends, and the next --play gives them to the player again.
        code, said = self.run_main(["--server", self.site.url, "--sign-in", stub.ACCOUNT], stdin=stub.PASSWORD + "\n")
        self.assertEqual(code, 0, said)
        menu = os.path.join(os.path.dirname(self.player), "menu.txt")
        with open(menu, "w", encoding="utf-8") as f:
            f.write("volume=29\neq=bass\neq_low=6\neq_mid=0\neq_high=0\n")
        with open(self.player, encoding="utf-8") as f:
            stand_in = f.read()
        with open(self.player, "w", encoding="utf-8") as f:
            f.write(IN_GAME_MENU + stand_in)
        code, said = self.run_main(["--play"])
        self.assertEqual(code, 0, said)
        values = st.LauncherState.load().values
        self.assertEqual((values["volume"], values["eq"], values["eq_low"]), (29, "bass", 6))
        # The next game's menu sets nothing: the player is given what the last one left.
        os.remove(menu)
        code, said = self.run_main(["--play"])
        self.assertEqual(code, 0, said)
        for line in ("volume=29", "eq=bass", "eq_low=6"):
            self.assertIn(line, self.started()["settings"].splitlines())

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

    def test_the_stopped_window_opens_the_logs_folder(self):
        # The launcher is gone, so Help's Open is out of reach: the window has Open the log folder, quiet, then Close,
        # lit (one lime button), which Enter and the window's X answer.
        from opendmtq_client import actions, dialogs, i18n, stopped
        w = i18n.Words("en")
        kind, _title, _message, _detail, buttons, default, cancel = stopped.dialog(w, OSError("x"), "C:\\logs\\l.log")
        self.assertEqual(kind, "error")
        self.assertEqual(buttons, [("Open the log folder", "logs", "neutral"), ("Close", "close", "home")])
        self.assertEqual((buttons[default][1], cancel), ("close", "close"))
        # Where finding the log failed too ("?"), Close alone: no folder to open.
        self.assertEqual([b[1] for b in stopped.dialog(w, OSError("x"), "?")[4]], ["close"])
        # The answer opens the folder the log is in, and nothing else.
        with mock.patch.object(dialogs, "standalone", return_value="logs"), \
                mock.patch.object(actions, "open_folder") as opened:
            stopped.show(OSError("x"), os.path.join("logs", "launcher.log"))
        opened.assert_called_once_with("logs")
        # Close opens nothing.
        with mock.patch.object(dialogs, "standalone", return_value="close"), \
                mock.patch.object(actions, "open_folder") as opened:
            stopped.show(OSError("x"), os.path.join("logs", "launcher.log"))
        opened.assert_not_called()

    def test_the_installers_stopped_window_has_no_title_bar(self):
        # The installer's window has no title bar of Windows' (frameless.py), and the window an error ends it in has
        # none either; the launcher's keeps its own.
        from opendmtq_client import dialogs, stopped

        def fails():
            raise OSError("x")

        for given, frameless in (({}, False), ({"frameless": True}, True)):
            with mock.patch.object(stopped, "windowed", return_value=True), \
                    mock.patch.object(dialogs, "standalone", return_value="close") as standalone, \
                    self.assertLogs("opendmtq_client", "ERROR"):
                self.assertEqual(stopped.run(fails, lambda: "setup.log", **given), 1)
            self.assertEqual(standalone.call_args.kwargs["frameless"], frameless)
        # The uninstall Windows' Apps opens is the installer's own window too (main sets it for that run).
        with mock.patch.object(stopped, "FRAMELESS", True), mock.patch.object(stopped, "windowed", return_value=True), \
                mock.patch.object(dialogs, "standalone", return_value="close") as standalone, \
                self.assertLogs("opendmtq_client", "ERROR"):
            stopped.run(fails, lambda: "launcher.log")
        self.assertTrue(standalone.call_args.kwargs["frameless"])

    def test_the_programs_entries_ask_for_their_own_stopped_windows(self):
        # OpenDMTQ-Setup.exe's entry asks for the stopped window without a title bar; OpenDMTQ.exe's for the launcher's.
        import runpy
        from opendmtq_client import stopped
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "packaging", "windows")
        for name, frameless in (("setup_entry.py", True), ("entry.py", False)):
            with mock.patch.object(stopped, "run", return_value=0) as run, self.assertRaises(SystemExit) as ended:
                runpy.run_path(os.path.join(here, name))
            with self.subTest(name):
                self.assertEqual(ended.exception.code, 0)
                self.assertEqual(run.call_args.kwargs.get("frameless", False), frameless)
