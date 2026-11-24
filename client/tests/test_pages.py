"""What the pages say that needs no window: a ready-check row's state and its link (pages.check_row), the lamp's shape,
and a LINE mode's name kept whole on its line where it shows (pages.whole_modes)."""

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

    def test_what_play_does_has_no_link_and_a_silent_server_leads_to_the_test(self):
        # PLAY downloads the app by itself; a server that does not answer leaves PLAY its app on this PC, and its row leads
        # to the connection test (on the Online page; the guide, which has none, says it does not answer).
        fetched = pages.check_row(actions.Check("app", False, "none", page="online", play_fixes=True), EN)
        self.assertEqual((fetched["state"], fetched["value"], fetched["link"]), ("change", EN("play.will_get"), None))
        silent = pages.check_row(actions.Check("server", False, "no answer", page="online", blocks=False), EN)
        self.assertEqual((silent["state"], silent["value"], silent["link"], silent["go"]),
                         ("change", EN("check.server.down"), EN("check.server.test"), "test"))
        silent = pages.check_row(actions.Check("server", False, "no answer", page="online", blocks=False), EN, in_guide=True)
        self.assertEqual((silent["state"], silent["value"], silent["link"]), ("change", EN("check.server.down"), None))

    def test_a_row_that_is_not_fine_says_what_is_wrong_before_its_link(self):
        # Each row that is not fine says its state in words as its value, the way to fix it after it (main showed a lamp
        # and "ONLINE ›" alone for the sign-in and the app, and "Test connection ›" alone for a server that does not
        # answer: the status line sent a player to a check that named no problem), in both languages, on PLAY, Help and
        # the guide (which has no link).
        cases = ((actions.Check("account", False, "not signed in", page="online"), False, "check.account.none"),
                 (actions.Check("account", False, "player1", page="online"), True, "check.account.ended"),
                 (actions.Check("app", False, "not downloaded", page="online"), False, "check.app.none"),
                 (actions.Check("server", False, "no server chosen", page="online"), False, "check.server.none"),
                 (actions.Check("server", False, "no answer", page="online", blocks=False), False, "check.server.down"))
        for check, ended, key in cases:
            for words in (EN, KO):
                for on_play, in_guide in ((True, False), (False, False), (False, True)):
                    row = pages.check_row(check, words, on_play=on_play, in_guide=in_guide, ended=ended)
                    self.assertEqual(row["value"], words(key), (key, words.language, in_guide))
                    self.assertEqual(row["link"] is None, in_guide, (key, words.language, in_guide))
        # A newer app on the server that PLAY cannot get yet says its date, as the app's own row does.
        newer = actions.Check("app_update", False, "2026-11-20 01:02", page="online")
        self.assertEqual(pages.check_row(newer, EN)["value"], "2026-11-20 01:02")
        # The installed launcher's missing player: what is wrong, then Repair.
        row = pages.check_row(actions.Check("player", False, "missing"), KO, installed=True)
        self.assertEqual((row["value"], row["link"]), (KO("check.player.none"), KO("check.player.repair")))

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
        # The ring's middle is the panel, far from the lamp's colour.
        self.assertLess(sum(abs(a - b) for a, b in zip(ring.getpixel(middle)[:3], panel)), 90)
        self.assertEqual(ring.size, dot.size)


class WholeModes(unittest.TestCase):
    def test_a_modes_name_never_breaks_over_two_lines(self):
        # Tk breaks a line at a plain space: "2 LINE" keeps one that never ends a line wherever it shows in a line that
        # wraps, a record's chart on PLAY and the Controls page's line under the keys, in both languages (How to play
        # broke "2 / LINE" in a narrow card, at every size, before it went).
        self.assertEqual(pages.whole_modes("3 LINE Hard 9  ·  5 min ago"),
                         "3" + pages.NO_BREAK + "LINE Hard 9  ·  5 min ago")
        for w in (EN, KO):
            for name in choices.LANES:
                said = pages.whole_modes(w("controls.keys.wait", lane=1, mode=choices.mode(name), keyname="F"))
                self.assertIn(choices.mode(name).replace(" ", pages.NO_BREAK), said, w.language)
                self.assertNotIn(choices.mode(name), said, w.language)
        # Anything else as it is.
        self.assertEqual(pages.whole_modes("Lane 2 of the song"), "Lane 2 of the song")


if __name__ == "__main__":
    unittest.main()
