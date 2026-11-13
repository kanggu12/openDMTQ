"""The words and the look: every key the code uses exists in both languages with the same gaps, every glyph is in the
bundled font, and every colour of text reads at 4.5:1 or more on what it sits on."""

import ast
import os
import re
import string
import unittest
from unittest import mock

from opendmtq_client import i18n, theme

PACKAGE = os.path.join(os.path.dirname(__file__), "..", "opendmtq_client")
# Strings in the code shaped as words' keys that are none: a file's name (apps.py).
NOT_WORDS = {"app.json"}


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
        # Every string in the code shaped as a key whose first part is one the words use: in w("..."), in a tuple of
        # rows a loop says, as an error's key. A key named anywhere but in w("...") itself would show as the raw key.
        firsts = {key.split(".")[0] for key in i18n.TEXT}
        used = set()
        for name in os.listdir(PACKAGE):
            if not name.endswith(".py") or name == "i18n.py":
                continue
            with open(os.path.join(PACKAGE, name), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            used.update(node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                        and isinstance(node.value, str) and re.fullmatch(r"[a-z_]+(?:\.[a-z0-9_]+)+", node.value)
                        and node.value.split(".")[0] in firsts)
        # The scan reads something: the words of every page are in it.
        self.assertGreater(len(used), 250)
        missing = sorted(k for k in used - NOT_WORDS if k not in i18n.TEXT)
        self.assertEqual(missing, [])
        # Keys the code builds: the page headers, the checks, the guide's steps, the installer's work, the hints by value.
        from opendmtq_client import app, guide, installer
        for page in app.NAV:
            if page != "play":
                self.assertIn(page + ".sub", i18n.TEXT)
        for key in ("player", "server", "account", "app", "app_update", "running"):
            self.assertIn("check." + key, i18n.TEXT)
        for step in guide.STEPS:
            for part in ("name", "title"):
                self.assertIn("guide.%s.%s" % (step, part), i18n.TEXT)
        for action in installer.WORK:
            self.assertIn("setup.work." + action, i18n.TEXT)
            self.assertIn("setup.work.%s.line" % action, i18n.TEXT)
        for key in ("screen.mode.hint.fullscreen", "screen.mode.hint.window", "screen.vsync.hint.on",
                    "screen.vsync.hint.off", "screen.fps.hint.vsync", "screen.fps.hint.vsync_rate",
                    "screen.fps.hint.free", "sound.mode.hint.shared", "sound.mode.hint.exclusive",
                    "sound.buffer.hint.low", "sound.buffer.hint.normal", "sound.buffer.hint.safe"):
            self.assertIn(key, i18n.TEXT)

    def test_a_key_with_no_words_is_an_error_in_a_test(self):
        # The tests reach every page and dialog: a word left out stops them, where a player would see the raw key.
        with self.assertRaises(KeyError):
            i18n.Words("en")("play.no_such_words")
        # A player sees the key itself, the launcher going on.
        with mock.patch.dict(os.environ, {"OPENDMTQ_TESTING": "0", "OPENDMTQ_VIRTUAL_DISPLAY": "0"}):
            self.assertEqual(i18n.Words("ko")("play.no_such_words"), "play.no_such_words")

    def test_errors_have_their_words(self):
        from opendmtq_client import server as srv
        error = srv.ServerError("cannot reach x", "error.server.unreachable", base="http://x", reason="refused")
        self.assertIn("http://x", i18n.Words("ko").error(error))
        self.assertEqual(i18n.Words("en").error(ValueError("plain")), "plain")

    def test_another_programs_failure_is_said_by_its_kind(self):
        # Velopack's and the system's own words, as they come on Windows (and under Wine), on Linux, and from Python:
        # each read as the kind a person can do something about, the rest as none (only the log has those words).
        from opendmtq_client import errors
        cases = (
            ("Network error: Http error: io: Nonauthoritative host not found. (os error 11002)", "network"),
            ("Network error: Http error: io: No such host is known. (os error 11001)", "network"),
            ("Network error: Http error: io: failed to lookup address information: Temporary failure in name "
             "resolution", "network"),
            ("Network error: Http error: io: A connection attempt failed because the connected party did not properly "
             "respond after a period of time (os error 10060)", "no_answer"),
            ("Network error: Http error: timeout: global", "no_answer"),
            ("Error: IO error: There is not enough space on the disk. (os error 112)", "disk_full"),
            # Velopack's setup's own line for a disk short of room, as it wrote it under Wine on a 150 MB disk.
            ("An error has occurred: OpenDMTQ requires at least 187.19 MB disk space to be installed. There is only "
             "57.59 MB available.", "disk_full"),
            ("[Errno 28] No space left on device: '/tmp/x'", "disk_full"),
            ("IO error: The process cannot access the file because it is being used by another process. (os error 32)",
             "in_use"),
            ("IO error: Access is denied. (os error 5)", "denied"),
            (PermissionError(13, "Permission denied"), "denied"),
            ("Checksum did not match for OpenDMTQ.Client-0.9.4-full.nupkg", None),
            ("Extracting files in user folders", None),
            ("", None),
        )
        for failure, kind in cases:
            self.assertEqual(errors.fault(failure), kind, failure)
        # Work that asks nothing over the network (Velopack's setup) is never said to have failed for the network.
        self.assertIsNone(errors.fault("timed out waiting for the lock", network=False))
        self.assertEqual(errors.fault("timed out (os error 112)", network=False), "disk_full")
        # In each language, what failed, then why; Velopack's words in neither.
        for language in ("en", "ko"):
            w = i18n.Words(language)
            said = w.failed("about.update_failed", cases[0][0])
            self.assertEqual(said, w("about.update_failed") + " " + w("fault.network"))
            self.assertNotIn("11002", said)
            self.assertEqual(w.failed("about.update_failed", "Checksum did not match"), w("about.update_failed"))

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
        for text in (theme.TEXT, theme.MUTED, theme.FAINT, theme.OK, theme.WARN, theme.BAD, theme.CYAN):
            for surface in surfaces:
                self.assertGreaterEqual(contrast(text, surface), 4.5, (text, surface))

    def test_ink_reads_on_each_sections_fill(self):
        # Every page is the site's lime: PLAY's word and a chosen tab's on it.
        self.assertGreaterEqual(contrast(theme.OK_INK, theme.OK), 4.5)
        from opendmtq_client import art
        for look, colours in art.BUTTON_LOOKS.items():
            for state in ("normal", "hover", "pressed"):
                words = colours.get("hover_text", colours["text"]) if state != "normal" else colours["text"]
                for fill in colours[state]:
                    self.assertGreaterEqual(contrast(words, fill), 4.5, (look, state, fill))
            # Disabled words on the disabled face.
            for fill in colours["disabled"]:
                self.assertGreaterEqual(contrast(theme.FAINT, fill), 4.5, (look, "disabled", fill))



class Wording(unittest.TestCase):
    def test_a_unit_after_a_number_has_a_space(self):
        # "53 MB", "{total} MB", "{hz} Hz" in both languages, as the rest of the product writes them: never "103.2MB".
        for key, pair in i18n.TEXT.items():
            for text in pair:
                self.assertIsNone(re.search(r"[0-9}](KB|MB|GB|Hz|fps)\b", text), (key, text))

    def test_a_log_is_a_log_and_records_are_records(self):
        # Korean says 로그 for a log and keeps 기록 for play records: "게임 로그 열기" opens a log, "기록은 서버에 그대로
        # 있습니다" is about the player's records, and one word for both read as the same thing.
        for key, (en, ko) in i18n.TEXT.items():
            if re.search(r"\blogs?\b", en):
                self.assertIn("로그", ko, key)
                self.assertNotIn("기록", ko, key)

    def test_one_word_for_signing_in(self):
        # Sign in on every button, card and step: never "log in" beside it (Korean says 로그인 for both).
        for key, (en, _ko) in i18n.TEXT.items():
            self.assertNotRegex(en, r"(?i)\blog ?in\b", key)

    def test_a_help_line_does_not_name_the_page_its_link_names(self):
        # The link at the line's right end says SCREEN or SOUND: the line itself says what to do there.
        for key, page in (("help.trouble.2", "SCREEN"), ("help.trouble.3", "SOUND")):
            for text in i18n.TEXT[key]:
                self.assertNotIn(page, text, key)

    def test_the_korean_vsync_hints_say_the_state_they_show_in(self):
        # Shown while VSync is on (or off): "켜면" (once turned on) would say it is off.
        for key in ("screen.fps.hint.vsync", "screen.fps.hint.vsync.above", "screen.fps.hint.vsync_rate"):
            self.assertNotIn("켜면", i18n.TEXT[key][1], key)
        self.assertNotIn("끄면", i18n.TEXT["screen.fps.hint.free"][1])

    def test_no_shortcut_the_player_does_not_take(self):
        # F11 and Alt+Enter left the player (the bar's full screen button and the Screen page switch it): no word of
        # them on any page, in either language.
        for key, pair in i18n.TEXT.items():
            for text in pair:
                self.assertNotRegex(text, r"F11|Alt\+Enter", key)


class KoreanParticles(unittest.TestCase):
    def test_no_mechanical_particles(self):
        # "(으)로", "을(를)" and the like read as a form being filled in: the words are put so that none is needed.
        for key, (_en, ko) in i18n.TEXT.items():
            self.assertIsNone(re.search(r"\((으|을|를|이|가|은|는|와|과)\)|(을|이|은|와)\((를|가|는|과)\)", ko), key)


if __name__ == "__main__":
    unittest.main()
