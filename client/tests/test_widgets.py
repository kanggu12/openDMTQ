"""The building blocks' behaviour that needs no window: the wheel and the drop-downs, a touchpad's small turns."""

import unittest

from opendmtq_client import widgets


class Wheel(unittest.TestCase):
    def test_the_wheel_never_changes_a_drop_down(self):
        # Tk's own bindings for every drop-down step its value under the wheel and say it was chosen: all of them go.
        # (tests/ui/shots.py turns a real wheel over the Screen page's drop-downs on a virtual screen.)
        gone = []

        class Root:
            def unbind_class(self, name, sequence):
                gone.append((name, sequence))

        widgets.quiet_combobox_wheel(Root())
        self.assertEqual(set(gone), {("TCombobox", s) for s in ("<MouseWheel>", "<Shift-MouseWheel>", "<Button-4>",
                                                                "<Button-5>")})

    def test_a_touchpads_small_turns_add_up(self):
        # A touchpad sends the wheel a little at a time (here 1/12 of a notch): the page still moves, a step at a time.
        steps = []

        class Canvas:
            def yview_scroll(self, n, what):
                steps.append(n)

        class Area:
            canvas = Canvas()
            _wheel_rest = 0.0

        class Turn:
            delta = -10

        area = Area()
        for _ in range(12):
            widgets.ScrollArea._on_wheel(area, Turn())
        # 12 turns of -10 make one notch down (120): 3 steps, none lost.
        self.assertEqual(sum(steps), 3)
        # A whole notch at once moves 3 steps, as before.
        steps.clear()

        class Notch:
            delta = 120

        widgets.ScrollArea._on_wheel(area, Notch())
        self.assertEqual(steps, [-3])


class Backdrop(unittest.TestCase):
    """The page's picture behind the cards, cut from the top it keeps (art.backdrop), against the same part drawn whole
    (art._whole): the same pixels, at any part of the page, scale and colour."""

    def test_the_kept_top_gives_the_picture_drawn_whole(self):
        from PIL import ImageChops
        from opendmtq_client import art, theme
        art._tops.clear()
        # 1.25: the dots' grid (8 px) does not divide the shards' 1125 rows, so the field under the top must keep it.
        for scale in (1.0, 1.25, 2.0):
            px = lambda n: int(round(n * scale))  # noqa: E731
            width, light = px(240), px(64) + px(260)
            # The header's picture, the guide's taller one, the page under the header, a long page past the shards,
            # and a part below the top altogether; then the site's own reach of the light, in another colour.
            for offset, height, top, accent in ((0, px(64), light, theme.OK), (0, px(128), light, theme.OK),
                                                (px(64), px(600), light, theme.OK), (px(64), px(1300), light, theme.OK),
                                                (px(950), px(90), light, theme.OK), (0, px(700), None, theme.BAD)):
                kept = art.backdrop(width, height, scale, accent, offset=offset, top=top)
                reach = int(top if top is not None else 620 * scale)
                whole = art._whole(width, height, scale, accent, offset, reach)
                # The same size, and no pixel apart (the box where they differ, when they do).
                self.assertEqual(kept.size, whole.size)
                self.assertIsNone(ImageChops.difference(kept, whole).getbbox(), (scale, offset, height, top, accent))
        # A few tops are kept, the newest; one drawn again comes from them.
        self.assertEqual(len(art._tops), art.TOPS_KEPT)
        key = next(reversed(art._tops))
        before = art._tops[key]
        art.backdrop(key[0], 10, key[1], key[2], offset=0, top=key[3])
        self.assertIs(art._tops[key], before)



class BuildPictures(unittest.TestCase):
    """The pictures the Windows build makes from the launcher's drawing code (packaging/windows/assets.py)."""

    def test_the_build_draws_its_pictures(self):
        import importlib.util
        import os
        import shutil
        import sys
        import tempfile
        from PIL import Image
        here = os.path.dirname(os.path.abspath(__file__))
        spec = importlib.util.spec_from_file_location(
            "odq_assets", os.path.join(here, "..", "packaging", "windows", "assets.py"))
        assets = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(assets)
        out = tempfile.mkdtemp(prefix="odq-assets-test-")
        saved = sys.argv
        try:
            sys.argv = ["assets.py", out, "0.8.0"]
            assets.main()
            sizes = {name: Image.open(os.path.join(out, name)).size for name in ("splash.png", "setup-splash.png")}
            self.assertEqual(sizes, {"splash.png": (720, 400), "setup-splash.png": (560, 312)})
            with Image.open(os.path.join(out, "OpenDMTQ.ico")) as icon:
                self.assertIn((256, 256), icon.info["sizes"])
            with open(os.path.join(out, "version-info.txt"), encoding="utf-8") as f:
                self.assertIn("filevers=(0, 8, 0, 0)", f.read())
        finally:
            sys.argv = saved
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
