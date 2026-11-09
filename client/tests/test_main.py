"""The command line: the same jobs as the window, with y/N before what cannot be undone."""

import contextlib
import io
import os
import sys

from opendmtq_client import apps, main, preset
from opendmtq_client import state as st
from tests import stub
from tests.base import Folder


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
        code, said = self.run_main(["--set", "fps=144", "--set", "vsync=off", "--status"])
        self.assertEqual(code, 0, said)
        self.assertIn("fps=144", said)
        self.assertNotIn(self.site.cookie, said)
        code, said = self.run_main(["--play"])
        self.assertEqual(code, 0, said)
        self.assertIn("vsync=off", self.started()["settings"])

    def test_a_wrong_password(self):
        self.run_main(["--server", self.site.url])
        code, said = self.run_main(["--sign-in", stub.ACCOUNT], stdin="wrong\n")
        self.assertEqual(code, 2)
        self.assertIn("wrong", said)

    def test_a_bad_setting(self):
        code, said = self.run_main(["--set", "fps=12"])
        self.assertEqual(code, 2)
        self.assertEqual(st.LauncherState.load().values["fps"], "auto")

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

    def test_the_setting_names_are_in_the_help(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            main.parse(["--help"])
        for name in ("vsync", "fps", "render_scale", "audio_device"):
            self.assertIn(name, out.getvalue())

    def test_version(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            main.main(["--version"])
        self.assertTrue(out.getvalue().startswith("OpenDMTQ "))
