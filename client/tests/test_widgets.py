"""The building blocks' behaviour that needs no window: the wheel and the drop-downs, a touchpad's small turns, the
pictures the cards and states are drawn with."""

import math
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



# How far a pixel the pictures leave as the card may be from the card's colour: the smoothing's tail, never a glow.
LEVEL = 2


class Glass(unittest.TestCase):
    """The pictures the launcher draws without the glows that said nothing (a halo round a state's lamp, a ring of the
    accent round a switch that is on), and a card's cut that shows the page's own picture beyond it."""

    def test_a_lamp_is_its_dot_alone(self):
        from opendmtq_client import art, theme
        for scale in (1.0, 2.0):
            for hollow in (False, True):
                lamp = art.lamp(theme.OK, scale, bg=theme.PANEL, hollow=hollow)
                c = lamp.width / 2.0
                # Past the dot's edge (3.5 px at 100 %) by the reach of its smoothing (Lanczos, three pixels): the card,
                # but for a level or two of the smoothing's tail (the glow was tens of levels there).
                reach = 3.5 * scale + 3
                panel = tuple(int(theme.PANEL[i:i + 2], 16) for i in (1, 3, 5))
                for x in range(lamp.width):
                    for y in range(lamp.height):
                        if (x + 0.5 - c) ** 2 + (y + 0.5 - c) ** 2 > reach ** 2:
                            got = lamp.getpixel((x, y))[:3]
                            self.assertLessEqual(max(abs(a - b) for a, b in zip(got, panel)), LEVEL,
                                                 (scale, hollow, x, y, got))
                # The room the lamp takes is as it was, so the words beside it stand where they stood.
                self.assertEqual(lamp.size, (int(math.ceil(21 * scale)),) * 2)

    def test_a_lamp_that_starts_a_line_has_its_dot_on_the_lines_edge(self):
        # A state's row starts with its lamp: the dot's smoothed edge in the picture's first column of pixels, where the
        # words over and under the row start (the room before it left the dot 7 px in from them); the room after it and
        # its height as a lamp's, so that the words beside it stand on its middle as before.
        from opendmtq_client import art, theme
        panel = tuple(int(theme.PANEL[i:i + 2], 16) for i in (1, 3, 5))
        for scale in (1.0, 1.5, 2.0):
            for hollow in (False, True):
                whole = art.lamp(theme.OK, scale, bg=theme.PANEL, hollow=hollow)
                lead = art.lamp(theme.OK, scale, bg=theme.PANEL, hollow=hollow, lead=False)
                middle = lead.height // 2
                # Its first column holds the dot's edge (no longer the card's colour on the dot's middle line).
                first = lead.getpixel((0, middle))[:3]
                self.assertGreater(max(abs(a - b) for a, b in zip(first, panel)), LEVEL, (scale, hollow, first))
                # As tall as a lamp, narrower by the room before the dot alone.
                self.assertEqual(lead.height, whole.height)
                self.assertEqual(whole.width - lead.width, int(math.floor(whole.width / 2.0 - 3.5 * scale)),
                                 (scale, hollow))

    def test_a_korean_title_takes_the_room_of_an_english_one(self):
        # The guide's questions in Korean are set in Pretendard, a little smaller than the wide face: their picture is as
        # tall as an English one's and stands on its baseline, so that a step's heading takes the same room in either
        # language (main: 6 px less in Korean, the cards moving up as the language changed, and the line under it 2 px
        # from its letters), at 100 %, 150 % and 200 %; the letters inside the picture, their foot clear of its edge.
        from opendmtq_client import art
        for scale in (1.0, 1.5, 2.0):
            english, base = art.page_title("Which server?", scale)
            for korean_words in ("어느 서버인가요?", "1스테이지 준비 끝"):
                korean, korean_base = art.page_title(korean_words, scale)
                self.assertEqual((korean.height, korean_base), (english.height, base), (scale, korean_words))
                ink = korean.split()[-1].getbbox()
                self.assertGreater(ink[1], 0, (scale, korean_words))
                self.assertLess(ink[3], korean.height, (scale, korean_words))

    def test_the_lit_tops_panes_end_above_every_pages_content(self):
        # The two pale panes of the page's lit top fade out by PANES_REACH, over every page's heading and above its
        # content (main: 324 px down, their edges through the heading, on the first card's top edge and between cards),
        # at 100 % and 200 %, in every part of the page; the light there still, faint, at the top.
        from opendmtq_client import art
        for scale in (1.0, 2.0):
            reach = int(round(art.PANES_REACH * scale))
            for width in (int(932 * scale), int(1352 * scale)):
                mask = art.pane_mask(width, int(760 * scale), scale, 0)
                self.assertIsNone(mask.crop((0, reach, width, mask.height)).getbbox(), (scale, width))
                self.assertIsNotNone(mask.crop((0, 0, width, reach)).getbbox(), (scale, width))
                self.assertIsNone(art.pane_mask(width, 100, scale, reach).getbbox(), (scale, width))
            # Above the PLAY page's content, the highest (its title alone over its cards) and its clear room.
            self.assertLessEqual(art.PANES_REACH, 85 - 16)

    def test_the_pages_shards_stand_right_of_their_room(self):
        # The launcher's page gives its shards a room: right of the content column and its clear room (ScrollArea's
        # shard_room). Nothing of them left of it at any width or scale, every part of the page; and some of them in it
        # (the window's own picture keeps its green), the site's own where the margin is wider than they are.
        from PIL import ImageChops
        from opendmtq_client import art
        for scale in (1.0, 2.0):
            px = lambda n: int(round(n * scale))  # noqa: E731
            for width, room in ((px(932), px(904)), (px(712), px(684)), (px(1352), px(1128))):
                for offset, height in ((0, px(760)), (px(300), px(700)), (px(950), px(100))):
                    mask = art.shard_mask(width, height, scale, offset, room)
                    self.assertIsNone(mask.crop((0, 0, room, height)).getbbox(), (scale, width, room, offset))
                top = art.shard_mask(width, px(760), scale, 0, room)
                self.assertIsNotNone(top.crop((room, 0, width, px(760))).getbbox(), (scale, width, room))
            # Wide enough a margin: the site's right-hand shards as the site has them (the same mask, the room left).
            width = px(1440)
            fitted = art.shard_mask(width, px(900), scale, 0, px(1000))
            site = art.shard_mask(width, px(900), scale, 0, None)
            site.paste(0, (0, 0, px(1000), px(900)))
            self.assertIsNone(ImageChops.difference(fitted, site).getbbox(), scale)

    def test_a_switch_that_is_on_has_no_ring_round_it(self):
        from opendmtq_client import art, theme
        on = art.toggle(True, 40, 22, bg=theme.PANEL)
        panel = tuple(int(theme.PANEL[i:i + 2], 16) for i in (1, 3, 5))
        ring = art.TOGGLE_HALO
        # The room round the pill: the card's colour on every side, at the middle of each edge (but for a level of the
        # pill's smoothing; the ring was a third of the way to lime there).
        for point in ((0, on.height // 2), (on.width - 1, on.height // 2), (on.width // 2, 0),
                      (on.width // 2, on.height - 1)):
            got = on.getpixel(point)[:3]
            self.assertLessEqual(max(abs(a - b) for a, b in zip(got, panel)), LEVEL, (point, got))
        self.assertEqual(on.size, (40 + 2 * ring, 22 + 2 * ring))

    def test_beyond_the_cut_the_field_without_its_dots(self):
        # What a card shows past its cut: the field's own colour where the page is the dotted field alone, at any part
        # of the page and scale (so a card moved over it keeps its corner), and the page's light where there is some.
        from PIL import Image
        from opendmtq_client import art, theme
        field = tuple(int(theme.BG[i:i + 2], 16) for i in (1, 3, 5))
        for scale in (1.0, 1.5, 2.0):
            for offset in (0, 7, 913):
                plain = art.without_dots(art._field(40, 40, scale, offset), scale)
                self.assertEqual(set(plain.getdata()), {field}, (scale, offset))
        lit = Image.new("RGB", (40, 40), (90, 160, 40))
        self.assertEqual(set(art.without_dots(lit, 1.0).getdata()), {(90, 160, 40)})

    def test_the_cut_shows_the_page_beyond_it(self):
        from PIL import Image
        from opendmtq_client import art, theme
        panel = tuple(int(theme.PANEL[i:i + 2], 16) for i in (1, 3, 5))
        for size, edge in ((16, 1), (32, 2)):
            # A picture of the page with something in every pixel (a colour per place), as the shards and dots are.
            page = Image.new("RGB", (size, size))
            page.putdata([((x * 13) % 256, (y * 29) % 256, (x * y) % 256) for y in range(size) for x in range(size)])
            # Drawn whole, and as a card lays its corner over the page where it stands (the card's part made once).
            layer = art.corner_layer(size, theme.PANEL, seam=theme.HAIRLINE, seam_width=edge)
            laid = page.copy()
            laid.paste(layer, (0, 0), layer)
            for corner in (art.corner(size, theme.PANEL, page, seam=theme.HAIRLINE, seam_width=edge), laid):
                for x in range(size):
                    for y in range(size):
                        if x - y > 2 + 2 * edge:
                            # Beyond the cut, clear of its line: the page's own pixel.
                            self.assertEqual(corner.getpixel((x, y)), page.getpixel((x, y)), (size, x, y))
                        elif y - x > 2 + 2 * edge:
                            # Inside: the card.
                            self.assertEqual(corner.getpixel((x, y)), panel, (size, x, y))


class LastWords(unittest.TestCase):
    def test_a_short_last_word_is_kept_with_the_one_before_it(self):
        # Tk breaks a line at a plain space only: a paragraph's short last word bound to the word before it never stands
        # alone on its last line ("volume.", "stays.", "않습니다." did), paragraph by paragraph, in both languages; a
        # long last word (a path, an address) and a paragraph of two words are left as they are.
        nb = widgets.NO_BREAK
        self.assertEqual(widgets.keep_last_words("as a share of the master volume."),
                         "as a share of the master" + nb + "volume.")
        self.assertEqual(widgets.keep_last_words("게임 데이터는 그대로 둡니다.\n두 번째 줄의 마지막 말입니다."),
                         "게임 데이터는 그대로" + nb + "둡니다.\n두 번째 줄의 마지막" + nb + "말입니다.")
        self.assertEqual(widgets.keep_last_words("The log is C:\\Users\\player\\AppData\\Local\\setup.log"),
                         "The log is C:\\Users\\player\\AppData\\Local\\setup.log")
        self.assertEqual(widgets.keep_last_words("no gaps"), "no gaps")
        self.assertEqual(widgets.keep_last_words(""), "")


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
