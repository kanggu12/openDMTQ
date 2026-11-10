"""Nothing a test runs opens a window on a real screen."""

import os
import shutil
import tempfile
import unittest

from opendmtq_client import actions, player, safety


class Safety(unittest.TestCase):
    def test_windows_are_refused_in_tests(self):
        saved = os.environ.pop("OPENDMTQ_VIRTUAL_DISPLAY", None)
        try:
            with self.assertRaises(safety.WindowRefused):
                safety.refuse_windows_in_tests("a window")
            with self.assertRaises(safety.WindowRefused):
                actions.open_folder(os.getcwd())
            # The real player, a program where the tests run a stand-in script, is refused before it starts.
            with self.assertRaises(safety.WindowRefused):
                player.start(os.getcwd(), "settings.txt", path=os.path.abspath(__file__).replace(".py", ".exe"))
        finally:
            if saved is not None:
                os.environ["OPENDMTQ_VIRTUAL_DISPLAY"] = saved

    def test_the_window_refuses_too(self):
        saved = os.environ.pop("OPENDMTQ_VIRTUAL_DISPLAY", None)
        try:
            from opendmtq_client import state as st
            from opendmtq_client.app import LauncherApp
            with self.assertRaises(safety.WindowRefused):
                LauncherApp(st.LauncherState())
        finally:
            if saved is not None:
                os.environ["OPENDMTQ_VIRTUAL_DISPLAY"] = saved


if __name__ == "__main__":
    unittest.main()


class Explorer(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="odq-explorer-test-")
        self.saved = os.environ.pop("OPENDMTQ_VIRTUAL_DISPLAY", None)

    def tearDown(self):
        if self.saved is not None:
            os.environ["OPENDMTQ_VIRTUAL_DISPLAY"] = self.saved
        shutil.rmtree(self.home, ignore_errors=True)

    def test_a_file_that_is_not_there_is_not_made(self):
        missing = os.path.join(self.home, "player.log")
        self.assertFalse(actions.show_file(missing))
        # Not a folder in its place either, which would stand where the player writes its log.
        self.assertFalse(os.path.exists(missing))
        open(missing, "w").close()
        with self.assertRaises(safety.WindowRefused):
            actions.show_file(missing)

    def test_a_folder_is_made_only_when_explorer_may_open(self):
        folder = os.path.join(self.home, "logs")
        with self.assertRaises(safety.WindowRefused):
            actions.open_folder(folder)
        self.assertFalse(os.path.exists(folder))


class Deleting(unittest.TestCase):
    def test_outside_a_test_nothing_is_refused(self):
        saved = os.environ.pop("OPENDMTQ_TESTING")
        try:
            safety.refuse_deleting_in_tests(os.path.expanduser("~"))
        finally:
            os.environ["OPENDMTQ_TESTING"] = saved
        with self.assertRaises(safety.DeleteRefused):
            safety.refuse_deleting_in_tests(os.path.expanduser("~"))
