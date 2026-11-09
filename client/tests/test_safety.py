"""Nothing a test runs opens a window on a real screen."""

import os
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
