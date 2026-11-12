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

    def test_what_it_asks(self):
        self.assertEqual(installer.plan(None, "0.8.0", False)[5], "install")
        self.assertEqual(installer.plan("0.7.0", "0.8.0", True)[5], "update")
        self.assertEqual(installer.plan("0.9.0", "0.8.0", False)[5], "back")
        self.assertIsNone(installer.plan("0.8.0", "0.8.0", False))

    def test_it_names_the_server_it_brings(self):
        asked = installer.plan(None, "0.8.0", False, {"url": "http://club.test", "name": "Club"})
        # What it sets up, said: OpenDMTQ, to play on that server.
        self.assertIn("This installer sets OpenDMTQ to play on Club.", asked[3])

    def test_it_asks_in_korean(self):
        w = i18n.Words("ko")
        asked = installer.plan(None, "0.8.0", False, {"url": "http://club.test", "name": "Club"}, w)
        self.assertEqual(asked[2], "OpenDMTQ 0.8.0 버전을 설치할까요?")
        self.assertIn("이 설치 파일은 OpenDMTQ가 Club에서 플레이하도록 설정합니다.", asked[3])
        asked = installer.plan("0.7.0", "0.8.0", True, None, w)
        self.assertEqual((asked[1], asked[4]), ("업데이트", "업데이트"))
        self.assertIn("열려 있는 런처는 먼저 닫힙니다.", asked[3])
        self.assertEqual(installer.plan("0.9.0", "0.8.0", False, None, w)[4], "0.8.0 버전 설치")

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
                "from opendmtq_client import installer, preset, dialogs\n" % (left_out,))
        run = subprocess.run([sys.executable, "-c", code], cwd=os.path.join(here, ".."), capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])

if __name__ == "__main__":
    unittest.main()
