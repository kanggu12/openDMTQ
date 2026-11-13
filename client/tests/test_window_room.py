"""Where the launcher's window opens: inside the work area (the screen less the taskbar), its title bar and frame
counted, so that the strip with PLAY at its foot is never under the taskbar. Plain numbers, no window."""

import re
import types
import unittest
from unittest import mock

from opendmtq_client import window_room


def foot(box, caption):
    """Where a window of `box` (width, height, x, y) ends, its title bar and frame (`caption`) counted."""
    _w, h, _x, y = box
    return y + caption + h


class WindowBox(unittest.TestCase):
    def test_a_laptop_at_150_percent_keeps_play_above_the_taskbar(self):
        # 1920x1080 at 150 %: the window asks for 1770x1140 of the screen's own pixels, Windows 11's taskbar takes the
        # bottom 72 (48 at 100 %) and the title bar with its frame about 45. Centred on the whole screen it ended near
        # 1067, under the taskbar from 1008.
        box = window_room.window_box((0, 0, 1920, 1008), 45, 1770, 1140)
        self.assertLessEqual(foot(box, 45), 1008)
        # As wide as the share of the room allows, centred across it.
        self.assertEqual(box[0], int(1920 * window_room.SHARE))
        self.assertEqual(box[2], (1920 - box[0]) // 2)

    def test_a_small_laptop_at_100_percent(self):
        # 1366x768 with a 48 px taskbar and a 31 px title bar: the window shorter, all of it above the taskbar.
        box = window_room.window_box((0, 0, 1366, 720), 31, 1180, 760)
        self.assertLessEqual(foot(box, 31), 720)
        # The room's share less the title bar: what is left for the window's own area.
        self.assertEqual(box[1], int(720 * window_room.SHARE) - 31)

    def test_a_large_screen_keeps_the_wanted_size(self):
        # 2560x1440 with its taskbar: room enough, so the window is the size asked for, a third of the spare height above.
        self.assertEqual(window_room.window_box((0, 0, 2560, 1392), 31, 1180, 760),
                         (1180, 760, (2560 - 1180) // 2, (1392 - 791) // 3))

    def test_a_taskbar_on_the_left_or_at_the_top(self):
        # A work area that starts past 0 (the taskbar on the left, or at the top): the window inside it all the same.
        w, h, x, y = window_room.window_box((62, 40, 1858, 1040), 31, 1180, 760)
        self.assertGreaterEqual(x, 62)
        self.assertGreaterEqual(y, 40)
        self.assertLessEqual(x + w, 62 + 1858)
        self.assertLessEqual(y + 31 + h, 40 + 1040)

    def test_no_title_bar_to_count_off_windows(self):
        # Linux, where the tests run: nothing of Windows' to ask, 0 counted, the screen Tk sees.
        if window_room.sys.platform == "win32":
            self.skipTest("Windows has a title bar to count")
        self.assertEqual(window_room.title_bar_height(), 0)
        screen = types.SimpleNamespace(winfo_screenwidth=lambda: 1920, winfo_screenheight=lambda: 1200)
        self.assertEqual(window_room.work_area(screen), (0, 0, 1920, 1200))


class LauncherWindow(unittest.TestCase):
    def test_the_launcher_opens_inside_the_work_area(self):
        # The launcher's own sizing (LauncherApp._size_window) on that laptop: a screen of 1920x1080 at 150 % whose work
        # area ends at 1008. Its window, title bar counted, ends above the taskbar.
        from opendmtq_client import app as app_module
        placed = {}

        class Root:
            """The parts of Tk's root the sizing asks and sets."""

            def winfo_screenwidth(self):
                return 1920

            def winfo_screenheight(self):
                return 1080

            def geometry(self, text):
                placed["geometry"] = text

            def minsize(self, width, height):
                placed["minsize"] = (width, height)

        # 150 %: px() turns the launcher's logical pixels into the screen's.
        fake = types.SimpleNamespace(root=Root(), ui=types.SimpleNamespace(px=lambda n: int(round(n * 1.5))))
        with mock.patch.object(window_room, "work_area", return_value=(0, 0, 1920, 1008)), \
                mock.patch.object(window_room, "title_bar_height", return_value=45):
            app_module.LauncherApp._size_window(fake)
        w, h, x, y = map(int, re.fullmatch(r"(\d+)x(\d+)\+(\d+)\+(\d+)", placed["geometry"]).groups())
        self.assertLessEqual(foot((w, h, x, y), 45), 1008)
        # The smallest size it can be dragged to is never larger than the window itself, either way.
        self.assertLessEqual(placed["minsize"][0], w)
        self.assertLessEqual(placed["minsize"][1], h)


if __name__ == "__main__":
    unittest.main()
