"""What the pages say that needs no window: a ready-check row's state and its link (pages.check_row), the lamp's shape,
and How to play's keyboard line as the settings have it (pages.keys_line)."""

import unittest

from opendmtq_client import actions, art, i18n, pages, theme
from opendmtq_client import values as choices

EN, KO = i18n.Words("en"), i18n.Words("ko")


class CheckRow(unittest.TestCase):
    def test_a_link_is_named_after_the_page_it_opens(self):
        # The sign-in ended (it does not stop PLAY) and the app is missing (it does): each row's link is the menu's own
        # name of the page that sees to it, as Help's lines name theirs, never a bare Fix.
        for check in (actions.Check("account", False, "player1", page="online"),
                      actions.Check("app", False, "none", page="online")):
            row = pages.check_row(check, EN)
            self.assertEqual((row["link"], row["go"]), ("ONLINE", "online"), check.key)
        # The same in Korean: the menu stays English in both languages, and so does its name on the link.
        self.assertEqual(pages.check_row(actions.Check("account", False, "player1", page="online"), KO)["link"], "ONLINE")

    def test_what_stops_play_is_a_problem_the_rest_will_change(self):
        # The app missing stops PLAY (red); a sign-in that ended does not (yellow, a ring).
        self.assertEqual(pages.check_row(actions.Check("app", False, "none", page="online"), EN)["state"], "bad")
        self.assertEqual(pages.check_row(actions.Check("account", False, "player1", page="online"), EN)["state"],
                         "change")

    def test_the_guide_has_no_menu_to_go_to(self):
        # On STAGE START a row says what is wrong with no link: the guide has no page to open.
        row = pages.check_row(actions.Check("account", False, "player1", page="online"), EN, in_guide=True)
        self.assertEqual((row["state"], row["link"], row["go"]), ("change", None, None))

    def test_the_installed_player_is_put_back_by_repair(self):
        # A player missing from an installed launcher: Repair, which runs at once, in the guide too.
        for in_guide in (False, True):
            row = pages.check_row(actions.Check("player", False, "missing"), EN, in_guide=in_guide, installed=True)
            self.assertEqual((row["state"], row["link"], row["go"]), ("bad", EN("check.player.repair"), "repair"))
        # A copied folder: nothing here can bring it back, so the row says what to do and has no link.
        row = pages.check_row(actions.Check("player", False, "missing"), EN)
        self.assertEqual((row["link"], row["value"]), (None, EN("check.player.missing")))

    def test_what_play_does_and_a_silent_server_have_no_link(self):
        # PLAY downloads the app by itself; a server that does not answer leaves PLAY its app on this PC.
        fetched = pages.check_row(actions.Check("app", False, "none", page="online", play_fixes=True), EN)
        self.assertEqual((fetched["state"], fetched["value"], fetched["link"]), ("change", EN("play.will_get"), None))
        silent = pages.check_row(actions.Check("server", False, "no answer", page="online", blocks=False), EN)
        self.assertEqual((silent["state"], silent["value"], silent["link"]), ("change", EN("check.server.down"), None))

    def test_a_fine_row_names_what_it_is_about(self):
        # On PLAY the server card above names the server and the account: only the app's date at the row's end.
        server = actions.Check("server", True, "Club (http://192.0.2.20)")
        self.assertIsNone(pages.check_row(server, EN, on_play=True)["value"])
        self.assertEqual(pages.check_row(server, EN)["value"], "Club (http://192.0.2.20)")


class Lamp(unittest.TestCase):
    def test_will_change_is_a_ring(self):
        # The filled dot's middle is its colour; the ring's middle is the card behind it, so the shape says it too.
        dot = art.lamp(theme.WARN, 1.0, bg=theme.PANEL)
        ring = art.lamp(theme.WARN, 1.0, bg=theme.PANEL, hollow=True)
        middle = (dot.width // 2, dot.height // 2)
        warn = tuple(int(theme.WARN[i:i + 2], 16) for i in (1, 3, 5))
        panel = tuple(int(theme.PANEL[i:i + 2], 16) for i in (1, 3, 5))
        self.assertEqual(dot.getpixel(middle)[:3], warn)
        # The ring's middle is the panel with at most a faint glow over it, far from the lamp's colour.
        self.assertLess(sum(abs(a - b) for a, b in zip(ring.getpixel(middle)[:3], panel)), 90)
        self.assertEqual(ring.size, dot.size)


class KeysLine(unittest.TestCase):
    def test_the_keys_as_the_settings_have_them(self):
        # Keyboard play on with its defaults: each LINE mode's keys from the top lane, in both languages, the Korean
        # particle against the mode's name.
        values = choices.normalize({})
        self.assertEqual(pages.keys_line(EN, values),
                         "Keys play the lanes from the top: F J in 2 LINE, D F J in 3 LINE, D F J K in 4 LINE.")
        self.assertEqual(pages.keys_line(KO, values),
                         "키로 위에서부터 줄을 칩니다: 2 LINE에서 F J, 3 LINE에서 D F J, 4 LINE에서 D F J K.")

    def test_keys_set_on_controls_or_by_set_follow(self):
        # Keys as the Controls page or --set leaves them (a lane's second key after a /): the line says those.
        values = choices.normalize({"keys_2line": "D/S K", "keys_4line": "A S K L"})
        self.assertEqual(pages.keys_line(EN, values),
                         "Keys play the lanes from the top: D/S K in 2 LINE, D F J in 3 LINE, A S K L in 4 LINE.")

    def test_off_says_it_is_off(self):
        # Keyboard play off: one line saying so (the link beside it leads to the Controls page).
        values = choices.normalize({"keyboard": "off"})
        self.assertEqual(pages.keys_line(EN, values), "Keyboard play is off.")
        self.assertEqual(pages.keys_line(KO, values), "키보드 플레이가 꺼져 있습니다.")

    def test_the_line_names_no_page_its_link_names(self):
        # The link at the line's right end says CONTROLS: the line itself never does, as Help's lines keep to.
        for values in (choices.normalize({}), choices.normalize({"keyboard": "off"})):
            for w in (EN, KO):
                self.assertNotIn(pages.TITLES["controls"], pages.keys_line(w, values))

    def test_how_to_play_goes_on_as_before(self):
        # After the keys: the touch screen, the mouse, then Esc and the bar's X, on PLAY and on STAGE START alike.
        self.assertEqual(pages.HOW_TO_PLAY, ("play.how.1", "play.how.2", "play.how.3"))


if __name__ == "__main__":
    unittest.main()
