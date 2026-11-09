"""The words and the look: every key the code uses exists in both languages with the same gaps, every glyph is in the
bundled font, and every colour of text reads at 4.5:1 or more on what it sits on."""

import os
import re
import string
import unittest

from opendmtq_client import i18n, theme

PACKAGE = os.path.join(os.path.dirname(__file__), "..", "opendmtq_client")


def _luminance(colour):
    """WCAG's relative luminance of #rrggbb."""
    rgb = [int(colour.lstrip("#")[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class Words(unittest.TestCase):
    def test_both_languages_with_the_same_gaps(self):
        for key, (en, ko) in i18n.TEXT.items():
            self.assertTrue(en and ko, key)
            gaps = lambda text: sorted(f[1] for f in string.Formatter().parse(text) if f[1])  # noqa: E731
            self.assertEqual(gaps(en), gaps(ko), key)

    def test_every_key_the_code_uses_exists(self):
        used = set()
        for name in os.listdir(PACKAGE):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(PACKAGE, name), encoding="utf-8") as f:
                source = f.read()
            # w("key"), self.words("key"), app.words("key") and the like: plain keys only (built ones are checked below).
            used.update(re.findall(r'(?:\bw|words)\("([a-z_]+(?:\.[a-z0-9_]+)+)"', source))
        missing = sorted(k for k in used if k not in i18n.TEXT)
        self.assertEqual(missing, [])
        # Keys the code builds: the nav names, the page headers, the checks, the guide's steps, the hints by value.
        from opendmtq_client import app, guide
        for page in app.NAV:
            self.assertIn("nav." + page, i18n.TEXT)
            if page != "play":
                self.assertIn(page + ".title", i18n.TEXT)
                self.assertIn(page + ".sub", i18n.TEXT)
        for key in ("player", "server", "account", "app", "app_update", "running"):
            self.assertIn("check." + key, i18n.TEXT)
        for step in guide.STEPS:
            for part in ("name", "sub", "title"):
                self.assertIn("guide.%s.%s" % (step, part), i18n.TEXT)
        for key in ("screen.mode.hint.fullscreen", "screen.mode.hint.window", "screen.vsync.hint.on",
                    "screen.vsync.hint.off", "screen.fps.hint.vsync", "screen.fps.hint.free", "sound.mode.hint.shared",
                    "sound.mode.hint.exclusive", "sound.buffer.hint.low", "sound.buffer.hint.normal",
                    "sound.buffer.hint.safe"):
            self.assertIn(key, i18n.TEXT)

    def test_errors_have_their_words(self):
        from opendmtq_client import server as srv
        error = srv.ServerError("cannot reach x", "error.server.unreachable", base="http://x", reason="refused")
        self.assertIn("http://x", i18n.Words("ko").error(error))
        self.assertEqual(i18n.Words("en").error(ValueError("plain")), "plain")

    def test_no_dashes_in_the_words(self):
        for key, pair in i18n.TEXT.items():
            for text in pair:
                self.assertNotIn("—", text, key)


class Look(unittest.TestCase):
    def test_glyphs_are_in_the_font(self):
        from fontTools.ttLib import TTFont
        cmap = TTFont(theme.ICON_FILE).getBestCmap()
        for name, glyph in theme.ICON.items():
            self.assertIn(ord(glyph), cmap, name)

    def test_fonts_are_there(self):
        for name in theme.FONT_FILES:
            self.assertTrue(os.path.isfile(os.path.join(theme.FONT_DIR, name)), name)
        for path in (theme.WIDE_ITALIC_FILE, theme.HANGUL_TITLE_FILE, theme.ICON_FILE):
            self.assertTrue(os.path.isfile(path), path)

    def test_text_reads_on_every_surface(self):
        surfaces = (theme.BG, theme.SIDEBAR, theme.PANEL, theme.PANEL_HI)
        for text in (theme.TEXT, theme.MUTED, theme.FAINT, theme.OK, theme.WARN, theme.BAD, theme.CYAN, theme.VIOLET,
                     theme.AMBER):
            for surface in surfaces:
                self.assertGreaterEqual(contrast(text, surface), 4.5, (text, surface))

    def test_ink_reads_on_each_sections_fill(self):
        for name, colours in theme.SECTION_COLOURS.items():
            self.assertGreaterEqual(contrast(colours["ink"], colours["fill"]), 4.5, name)
        from opendmtq_client import art
        for look, colours in art.BUTTON_LOOKS.items():
            for state in ("normal", "hover", "pressed"):
                words = colours.get("hover_text", colours["text"]) if state != "normal" else colours["text"]
                for fill in colours[state]:
                    self.assertGreaterEqual(contrast(words, fill), 4.5, (look, state, fill))
            # Disabled words on the disabled face.
            for fill in colours["disabled"]:
                self.assertGreaterEqual(contrast(theme.FAINT, fill), 4.5, (look, "disabled", fill))


if __name__ == "__main__":
    unittest.main()


class KoreanParticles(unittest.TestCase):
    def test_no_mechanical_particles(self):
        # "(으)로", "을(를)" and the like read as a form being filled in: the words are put so that none is needed.
        for key, (_en, ko) in i18n.TEXT.items():
            self.assertIsNone(re.search(r"\((으|을|를|이|가|은|는|와|과)\)|(을|이|은|와)\((를|가|는|과)\)", ko), key)
