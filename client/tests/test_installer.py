"""The installer's choices, without its window: what it asks, and the server it brings."""

import os
import tempfile
import unittest

from opendmtq_client import i18n, installer, preset
from opendmtq_client import state as st
from tests.base import Folder


class Installer(unittest.TestCase):
    def test_versions_order_as_semver(self):
        order = ["0.7.0", "0.8.0-rc.1", "0.8.0-rc.2", "0.8.0", "0.8.1", "1.0.0"]
        self.assertEqual(sorted(reversed(order), key=installer.version_key), order)

    def test_what_an_installed_pc_is_offered(self):
        # This installer's version against the one installed: Update first when this one is newer (no Repair then: it
        # would update), Open first otherwise, then Repair for the same version, going back for an older one, and
        # Uninstall last every time.
        self.assertEqual(installer.maintenance("0.10.0", "0.11.0"), ["update", "open", "uninstall"])
        self.assertEqual(installer.maintenance("0.11.0", "0.11.0"), ["open", "repair", "uninstall"])
        self.assertEqual(installer.maintenance("0.12.0", "0.11.0"), ["open", "back", "uninstall"])
        self.assertEqual(installer.maintenance("0.11.0-rc.1", "0.11.0"), ["update", "open", "uninstall"])

    def test_velopacks_setup_read_as_it_writes(self):
        # Its log, as 0.10.0's setup wrote it under Wine: the steps it goes through, the program's size and the
        # package's, read as they come, a line not ended yet waiting for its end.
        folder = tempfile.mkdtemp()
        log = os.path.join(folder, "setup.log")
        lines = ["[setup:448] [11:47:52] [INFO] Starting Velopack Setup (1.2.161)\n",
                 "[setup:448] [11:47:52] [INFO] Bundle offset = 7546368, length = 41322990\n",
                 "[setup:448] [11:47:52] [INFO] There is 312.75 GB free space available at destination, this package "
                 "requires 187.49 MB.\n",
                 "[setup:448] [11:47:52] [INFO] Extracting 1032 app files to '...current'...\n",
                 "[setup:448] [11:47:54] [INFO] Creating shortcuts...\n",
                 "[setup:448] [11:47:54] [INFO] Running --veloapp-install hook...\n"]
        reader = installer.SetupLog(log)
        # Not written yet: the setup is starting.
        self.assertEqual(reader.read(), 0)
        with open(log, "w", encoding="utf-8") as f:
            f.write("".join(lines[:3]) + lines[3][:20])
        self.assertEqual(reader.read(), 0)
        self.assertEqual((reader.required, reader.bundle), (187.49 * (1 << 20), 41322990))
        with open(log, "a", encoding="utf-8") as f:
            f.write(lines[3][20:])
        self.assertEqual(reader.read(), 1)
        # The copy's share follows the program's files: half of them there, about half of the copy's span.
        os.makedirs(os.path.join(folder, "current"))
        target = reader.required - reader.bundle
        with open(os.path.join(folder, "current", "half.bin"), "wb") as f:
            f.write(b"\0" * int(target / 2))
        share = reader.share(folder)
        self.assertAlmostEqual(share, 0.06 + (0.92 - 0.06) * 0.5, places=2)
        with open(log, "a", encoding="utf-8") as f:
            f.write(lines[4] + lines[5])
        self.assertEqual(reader.read(), 3)
        self.assertEqual(reader.share(folder), 0.96)

    def test_the_installed_version_as_notepad_leaves_it(self):
        # Velopack's sq.version saved again by hand: a byte order mark, Windows' line ends, spaces, quotes.
        folder = tempfile.mkdtemp()
        os.makedirs(os.path.join(folder, "current"))
        for text in ('\ufeff<?xml version="1.0"?>\r\n<package>\r\n  <version> 0.11.0 </version>\r\n</package>\r\n',
                     '<version>"0.11.0"</version>', "<version>0.11.0</version>"):
            with open(os.path.join(folder, "current", "sq.version"), "w", encoding="utf-8", newline="") as f:
                f.write(text)
            self.assertEqual(installer.installed_version(folder), "0.11.0", repr(text))
        self.assertIsNone(installer.installed_version(os.path.join(folder, "none")))

    def test_every_step_and_stage_has_its_words(self):
        # The keys the window builds from a step's or a stage's name, in both languages.
        for key in installer.STEP_KEYS:
            self.assertTrue(all(i18n.TEXT["setup.step." + key]), key)
        for key in installer.STAGE_KEYS:
            self.assertTrue(all(i18n.TEXT["setup.stage." + key]), key)
        for action in installer.WORK:
            self.assertTrue(all(i18n.TEXT["setup.work.%s.line" % action]), action)

    def test_a_long_program_path_breaks_after_its_separators(self):
        # The Install page's Program row: lines no wider than the room, each ending after a \ (Tk breaks a line at
        # spaces only, so main cut "OpenDMT / Q.Client" in two on a long user folder at 150 %), a folder's name whole.
        class Font:
            # A made-up font: every character 7 px wide.
            def measure(self, text):
                return 7 * len(text)

        path = r"C:\Users\a-long-user-name\AppData\Local\Temp\odq-test\lad\OpenDMTQ.Client"
        lines = installer.path_lines(Font(), path, 7 * 45).split("\n")
        self.assertEqual(lines, ["C:\\Users\\a-long-user-name\\AppData\\Local\\Temp\\",
                                 "odq-test\\lad\\OpenDMTQ.Client"])
        # A path that fits stays one line; the separators of Linux's paths too.
        self.assertEqual(installer.path_lines(Font(), path, 7 * 200), path)
        self.assertEqual(installer.path_lines(Font(), "/tmp/abc/local/OpenDMTQ.Client", 7 * 20),
                         "/tmp/abc/local/\nOpenDMTQ.Client")

    def test_the_server_from_its_own_file(self):
        folder = tempfile.mkdtemp()
        exe = os.path.join(folder, "OpenDMTQ-Setup.exe")
        with open(exe, "wb") as f:
            f.write(b"MZ" + b"\0" * 100 + preset.tail("http://club.test:8790", "Club"))
        saved = os.environ.get("OPENDMTQ_SETUP_FILE")
        os.environ["OPENDMTQ_SETUP_FILE"] = exe
        try:
            self.assertEqual(installer.brought(), {"url": "http://club.test:8790", "name": "Club"})
        finally:
            if saved is None:
                os.environ.pop("OPENDMTQ_SETUP_FILE")
            else:
                os.environ["OPENDMTQ_SETUP_FILE"] = saved

    def test_the_server_is_named_once(self):
        # Its name and its address, or its address alone when it calls itself by its address (main said that server
        # twice on the Install page: "192.168.1.10:8791  ·  http://192.168.1.10:8791").
        self.assertEqual(installer.server_words({"url": "http://192.168.1.10:8791", "name": "Club Night"}),
                         "Club Night  ·  http://192.168.1.10:8791")
        for name in ("192.168.1.10:8791", "192.168.1.10", "http://192.168.1.10:8791", ""):
            self.assertEqual(installer.server_words({"url": "http://192.168.1.10:8791", "name": name}),
                             "http://192.168.1.10:8791", name)

    def test_the_install_folder_is_apart_from_the_players_data(self):
        saved = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = os.path.join(os.sep, "local")
        try:
            self.assertEqual(os.path.basename(installer.app_dir()), "OpenDMTQ.Client")
        finally:
            if saved is None:
                os.environ.pop("LOCALAPPDATA")
            else:
                os.environ["LOCALAPPDATA"] = saved


class Language(Folder):
    """The installer speaks the launcher's language: its saved choice, else Windows' display language."""

    def setUp(self):
        super().setUp()
        self.saved_language = st.system_language
        # Windows' display language stands in: the test never depends on this computer's.
        st.system_language = lambda: "ko"

    def tearDown(self):
        st.system_language = self.saved_language
        super().tearDown()

    def test_windows_language_without_a_launcher(self):
        self.assertEqual(installer.language(), "ko")
        st.system_language = lambda: "en"
        self.assertEqual(installer.language(), "en")

    def test_the_launchers_choice_wins(self):
        s = st.LauncherState()
        s.language = "en"
        s.save()
        self.assertEqual(installer.language(), "en")

    def test_the_launchers_choice_as_notepad_leaves_it(self):
        # The launcher's settings saved again by hand: a byte order mark, Windows' line ends, the language in capitals
        # with spaces round it. Still the player's choice, never Windows' language instead.
        s = st.LauncherState()
        s.language = "en"
        s.save()
        with open(st.LauncherState.path(), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('"language": "en"', text)
        with open(st.LauncherState.path(), "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write(text.replace('"language": "en"', '"language": " EN "'))
        self.assertEqual(installer.language(), "en")

    def test_unreadable_settings_fall_back_to_windows(self):
        os.makedirs(st.config_dir(), exist_ok=True)
        with open(st.LauncherState.path(), "w") as f:
            f.write("{not json")
        self.assertEqual(installer.language(), "ko")



class BuiltWithout(unittest.TestCase):
    """The installer's build leaves modules out (client/packaging/windows/setup.spec, excludes): its code must start
    without them, or the installer dies before its window (11-10: preset.py took server.py and its http along)."""

    def test_the_installer_starts_without_the_modules_its_build_leaves_out(self):
        import re
        import subprocess
        import sys
        here = os.path.dirname(os.path.abspath(__file__))
        spec = os.path.join(here, "..", "packaging", "windows", "setup.spec")
        with open(spec, encoding="utf-8") as f:
            listed = re.search(r"excludes=\[([^\]]*)\]", f.read(), re.S).group(1)
        left_out = re.findall(r'"([A-Za-z0-9_.]+)"', listed)
        self.assertIn("http", left_out)
        # Each left-out module made unimportable (None in sys.modules), then the installer's own code imported.
        code = ("import sys\n"
                "for name in %r: sys.modules[name] = None\n"
                "from opendmtq_client import installer, preset, dialogs, removal, installed, setup_window\n"
                "removal.everything_size(), removal.game_data_size(), removal.leftovers()\n" % (left_out,))
        run = subprocess.run([sys.executable, "-c", code], cwd=os.path.join(here, ".."), capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])

if __name__ == "__main__":
    unittest.main()
