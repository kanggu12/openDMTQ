"""Keyboard play's settings: the lanes' keys of each LINE mode as the launcher keeps them and writes them for the
player, the checks the Controls page and --set share, and a key's place read from a press in the window."""

import types
import unittest
from unittest import mock

from opendmtq_client import i18n, keys
from opendmtq_client import values as choices

# The contract with the player (arm32/desktop/settings.cpp reads it): each key by the US layout's key at its place.
CONTRACT = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + tuple("0123456789") + (
    "Space", "Semicolon", "Quote", "Comma", "Period", "Slash", "LeftBracket", "RightBracket", "Backslash", "Minus",
    "Equals", "Grave")


def refused(name, value):
    """The ChoiceError a value of a keys setting raises, or None when it is taken."""
    try:
        choices.normalize({name: value})
    except choices.ChoiceError as e:
        return e
    return None


class Contract(unittest.TestCase):
    def test_the_names_are_the_players(self):
        # Every name the player takes, and no other: the launcher writes no key the player cannot bind.
        self.assertEqual(sorted(choices.KEY_NAMES), sorted(CONTRACT))
        # One place a name, one name a place.
        self.assertEqual(len(set(choices.SCAN.values())), len(CONTRACT))

    def test_each_name_is_its_place_on_the_us_layout(self):
        # Set 1 scan codes, as Windows gives them in a key's message and as Linux numbers its keys: the rows of a US
        # keyboard from the digits down, and Space.
        rows = (("1234567890", 0x02), ("QWERTYUIOP", 0x10), ("ASDFGHJKL", 0x1E), ("ZXCVBNM", 0x2C))
        for letters, first in rows:
            for i, name in enumerate(letters):
                self.assertEqual(choices.SCAN[name], first + i, name)
        for name, scan in (("Minus", 0x0C), ("Equals", 0x0D), ("LeftBracket", 0x1A), ("RightBracket", 0x1B),
                           ("Semicolon", 0x27), ("Quote", 0x28), ("Grave", 0x29), ("Backslash", 0x2B),
                           ("Comma", 0x33), ("Period", 0x34), ("Slash", 0x35), ("Space", 0x39)):
            self.assertEqual(choices.SCAN[name], scan, name)
        # And back: a place to its name.
        self.assertEqual(choices.BY_SCAN[0x21], "F")
        self.assertNotIn(0x56, choices.BY_SCAN)

    def test_the_defaults(self):
        # On, with the home row's keys under the index and middle fingers: the lanes from the top left to right.
        filled = choices.normalize({})
        self.assertEqual(filled["keyboard"], "on")
        self.assertEqual((filled["keys_2line"], filled["keys_3line"], filled["keys_4line"]), ("F J", "D F J", "D F J K"))
        # Every one of them is a setting the launcher keeps and lists (--set, --status) and writes for the player.
        for name in ("keyboard", "keys_2line", "keys_3line", "keys_4line"):
            self.assertIn(name, choices.NAMES)
            self.assertIn(name, choices.ORDER)


class Parsing(unittest.TestCase):
    def test_names_in_any_case_and_spacing_are_kept_as_the_player_names_them(self):
        for name, value, kept in (("keys_2line", "f j", "F J"), ("keys_2line", "  F   J ", "F J"),
                                  ("keys_3line", "d/e f j", "D/E F J"), ("keys_3line", "space SEMICOLON leftbracket",
                                                                         "Space Semicolon LeftBracket"),
                                  ("keys_4line", "1/q 2/w 3/e 4/r", "1/Q 2/W 3/E 4/R")):
            self.assertEqual(choices.normalize({name: value})[name], kept, value)

    def test_a_key_may_play_in_every_mode(self):
        # The modes are apart: F in 2 LINE and in 3 LINE is no clash.
        filled = choices.normalize({"keys_2line": "F J", "keys_3line": "F J K", "keys_4line": "F J K L"})
        self.assertEqual(filled["keys_3line"], "F J K")

    def test_the_lanes_are_counted(self):
        # As many lanes as the mode has, from the top: fewer or more refused, empty too.
        for name, value in (("keys_2line", "F"), ("keys_2line", "D F J"), ("keys_3line", "D F"),
                            ("keys_4line", "D F J"), ("keys_4line", ""), ("keys_3line", "   ")):
            error = refused(name, value)
            self.assertIsNotNone(error, (name, value))
            self.assertEqual(error.key, "error.keys.lanes", (name, value))
            self.assertIn("%d lanes" % choices.LANES[name], str(error))

    def test_a_lane_has_one_key_or_two(self):
        for value in ("F/G/H J", "F/ J", "/F J", "F//G J"):
            error = refused("keys_2line", value)
            self.assertEqual(error.key, "error.keys.lane", value)

    def test_a_name_the_player_does_not_take(self):
        # Keys outside the list (Enter, the arrows), the printed signs in place of the names, and nonsense.
        for value, key in (("F Enter", "Enter"), ("F ;", ";"), ("Up J", "Up"), ("F Ö", "Ö"), ("F KeyJ", "KeyJ")):
            error = refused("keys_2line", value)
            self.assertEqual(error.key, "error.keys.name", value)
            self.assertEqual(error.params["keyname"], key)
            # The sentence lists what a lane takes.
            self.assertIn("LeftBracket", str(error))

    def test_a_key_twice_in_one_mode(self):
        # In two lanes, or twice in one: refused, naming the key and where.
        error = refused("keys_2line", "F F")
        self.assertEqual((error.key, error.params["keyname"]), ("error.keys.twice", "F"))
        self.assertIn("lane 1 and lane 2", str(error))
        error = refused("keys_4line", "D F J/d K")
        self.assertEqual((error.key, error.params["keyname"]), ("error.keys.twice", "D"))
        error = refused("keys_3line", "D F/F J")
        self.assertEqual((error.key, error.params["keyname"]), ("error.keys.twice_in_lane", "F"))

    def test_keyboard_play_is_on_or_off(self):
        self.assertEqual(choices.normalize({"keyboard": "OFF"})["keyboard"], "off")
        self.assertIsNotNone(refused("keyboard", "maybe"))

    def test_a_bad_value_kept_in_a_file_keeps_the_default(self):
        # A hand-edited launcher file: the default for that one, the others as they were.
        filled = choices.normalize({"keys_3line": "F F F", "keys_2line": "A L"}, strict=False)
        self.assertEqual((filled["keys_3line"], filled["keys_2line"]), ("D F J", "A L"))

    def test_every_refusal_has_its_words(self):
        # The window says each in its language, with what the error names filled in: Korean words of their own, never
        # the English sentence the command line prints.
        for name, value in (("keys_2line", "F"), ("keys_2line", "F/G/H J"), ("keys_2line", "F Enter"),
                            ("keys_2line", "F F"), ("keys_3line", "D F/F J")):
            error = refused(name, value)
            english, korean = i18n.Words("en").error(error), i18n.Words("ko").error(error)
            self.assertTrue(english and korean, (name, value))
            self.assertNotEqual(korean, english, (name, value))
            self.assertNotEqual(korean, str(error), (name, value))
            for said in (english, korean):
                self.assertNotIn("{", said, (name, value))
                # The key the refusal is about, where it is about one.
                if "keyname" in error.params:
                    self.assertIn(error.params["keyname"], said, (name, value))


class Lanes(unittest.TestCase):
    def test_a_lanes_key_set_from_the_card(self):
        lanes = choices.lanes_of("keys_3line", "D F J")
        self.assertEqual(lanes, (("D",), ("F",), ("J",)))
        # Its own key, another, then a second key.
        self.assertEqual(choices.with_key("keys_3line", lanes, 1, 0, "F"), lanes)
        self.assertEqual(choices.lanes_text(choices.with_key("keys_3line", lanes, 1, 0, "K")), "D K J")
        self.assertEqual(choices.lanes_text(choices.with_key("keys_3line", lanes, 1, 1, "G")), "D F/G J")

    def test_a_key_another_lane_plays_is_refused(self):
        lanes = choices.lanes_of("keys_4line", "D F J/U K")
        for lane, slot, key, plays in ((0, 0, "F", 2), (0, 1, "U", 3), (3, 1, "D", 1), (1, 1, "F", 2)):
            with self.assertRaises(choices.ChoiceError) as caught:
                choices.with_key("keys_4line", lanes, lane, slot, key)
            error = caught.exception
            self.assertEqual(error.key, "error.keys.taken")
            self.assertEqual((error.params["keyname"], error.params["lane"], error.params["mode"]), (key, plays, "4 LINE"))
        # Nothing of it changed.
        self.assertEqual(choices.lanes_text(lanes), "D F J/U K")

    def test_a_second_key_taken_away(self):
        lanes = choices.lanes_of("keys_2line", "F/G J")
        self.assertEqual(choices.lanes_text(choices.without_key("keys_2line", lanes, 0, 1)), "F J")
        # The first one taken away: the second plays the lane alone.
        self.assertEqual(choices.lanes_text(choices.without_key("keys_2line", lanes, 0, 0)), "G J")
        # A lane's only key stays: a lane keeps one at least.
        with self.assertRaises(choices.ChoiceError) as caught:
            choices.without_key("keys_2line", lanes, 1, 0)
        self.assertEqual(caught.exception.key, "error.keys.one")

    def test_the_mode_as_the_game_names_it(self):
        self.assertEqual([choices.mode(name) for name in choices.LANES], ["2 LINE", "3 LINE", "4 LINE"])


class SettingsFile(unittest.TestCase):
    def test_the_player_gets_them_after_the_sound(self):
        text = choices.settings_text({"keyboard": "off", "keys_2line": "f/g j", "keys_4line": "1 2 3 4"})
        lines = [line for line in text.splitlines() if not line.startswith("#")]
        # After the volume, in the player's order, in the names it takes.
        self.assertEqual(lines[lines.index("volume=100") + 1:],
                         ["keyboard=off", "keys_2line=F/G J", "keys_3line=D F J", "keys_4line=1 2 3 4"])


def press(keycode, keysym="", char=""):
    """A key press as Tk hands it to a binding."""
    return types.SimpleNamespace(keycode=keycode, keysym=keysym, char=char)


class Presses(unittest.TestCase):
    def test_a_place_on_x11(self):
        # The X server's key codes are Linux's key numbers plus 8, the scan codes on the main block: F, ;, Space, and
        # the numpad's / (a place of its own), Shift and Enter, which no lane takes.
        with mock.patch.object(keys.sys, "platform", "linux"):
            for code, name in ((41, "F"), (47, "Semicolon"), (65, "Space"), (49, "Grave"), (51, "Backslash"),
                               (106, None), (50, None), (36, None), (94, None)):
                self.assertEqual(keys.place_of(press(code)), name, code)

    def test_a_place_on_windows_by_the_layout_in_use(self):
        # Windows gives the virtual key, which the layout in use made of the place: the place back from it, through
        # the layout. A French layout's A is at the US Q's place; the numpad's / comes back marked extended.
        layout = {0x41: 0x10, 0x46: 0x21, 0x6F: 0xE035, 0x10: 0x2A, 0xBA: 0x27}
        with mock.patch.object(keys.sys, "platform", "win32"), \
                mock.patch.object(keys, "_vk_to_scan", lambda vk: layout.get(vk, 0)):
            self.assertEqual(keys.place_of(press(0x41)), "Q")
            self.assertEqual(keys.place_of(press(0x46)), "F")
            self.assertEqual(keys.place_of(press(0xBA)), "Semicolon")
            self.assertIsNone(keys.place_of(press(0x6F)))
            self.assertIsNone(keys.place_of(press(0x10)))
            # A key an input method held (VK_PROCESSKEY) or one without a place: none.
            self.assertIsNone(keys.place_of(press(0xE5)))

    def test_what_the_layout_prints_there(self):
        # Off Windows, what Tk said at a press in this run; nothing for a place not pressed yet.
        with mock.patch.object(keys.sys, "platform", "linux"):
            self.assertEqual(keys.printed("Semicolon", {"Semicolon": ";"}), ";")
            self.assertIsNone(keys.printed("Quote", {"Semicolon": ";"}))
        # On Windows, the layout in use, asked for the place's unshifted character: a German keyboard's ö at the US
        # semicolon's place; a dead key's mark (the top bit) is no part of the character; nothing there is none.
        chars = {0x27: 0xBA, 0x29: 0xDC, 0x10: 0x51}
        prints = {0xBA: ord("Ö"), 0xDC: 0x80000000 | ord("^"), 0x51: ord("Q")}
        with mock.patch.object(keys.sys, "platform", "win32"), \
                mock.patch.object(keys, "_scan_to_vk", lambda scan: chars.get(scan, 0)), \
                mock.patch.object(keys, "_vk_to_char", lambda vk: prints.get(vk, 0)):
            self.assertEqual(keys.printed("Semicolon"), "Ö")
            self.assertEqual(keys.printed("Grave"), "^")
            self.assertEqual(keys.printed("Q"), "Q")
            self.assertIsNone(keys.printed("Quote"))

    def test_what_a_box_shows_beside_the_name(self):
        # The print when it says more than the name: a sign, another layout's letter; not a letter that is the name,
        # nor a space.
        self.assertEqual(keys.beside("Semicolon", ";"), ";")
        self.assertEqual(keys.beside("Q", "a"), "A")
        self.assertIsNone(keys.beside("F", "f"))
        self.assertIsNone(keys.beside("Space", " "))
        self.assertIsNone(keys.beside("F", None))
        self.assertIsNone(keys.beside("F", "\x1b"))

    def test_a_refused_key_named_in_words(self):
        # The keys a person reaches for first, named as their caps name them; another sign as it prints; else none.
        for keysym, char, said in (("Return", "\r", "Enter"), ("KP_Enter", "\r", "Enter"), ("Shift_L", "", "Shift"),
                                   ("Control_R", "", "Ctrl"), ("Alt_L", "", "Alt"), ("Up", "", "↑"), ("F5", "", "F5"),
                                   ("KP_1", "1", "Num 1"), ("less", "<", "<"), ("Hangul", "", None)):
            self.assertEqual(keys.label(press(0, keysym, char)), said, keysym)


if __name__ == "__main__":
    unittest.main()
