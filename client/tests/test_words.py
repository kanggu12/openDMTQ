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
# Strings in the code shaped as words' keys that are none: a file's name (apps.py, report.py).
NOT_WORDS = {"app.json", "about.txt"}


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
        # The last game's sound: each way the player can have had the device.
        from opendmtq_client import player
        for mode in player.RESULT_MODES:
            self.assertIn("sound.last.mode." + mode, i18n.TEXT)

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



class ButtonRoles(unittest.TestCase):
    def test_no_button_is_yellow(self):
        # A button's colour is its role's (DESIGN.md: main lime, red where it removes for good, metal for the rest): no
        # look of art.BUTTON_LOOKS is filled with the warning's yellow, and every dialog's main button is lime or red
        # (main had a yellow look for a dialog's Keep data and the cannot-start window's Start over, with no role).
        from opendmtq_client import art, dialogs
        warn = theme.WARN.lower()
        for look, colours in art.BUTTON_LOOKS.items():
            for state in ("normal", "hover", "pressed"):
                self.assertNotIn(warn, [c.lower() for c in colours[state]], (look, state))
        for kind, style in dialogs.KINDS.items():
            self.assertIn(style["button"], ("home", "danger"), kind)


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

    def test_no_usage_advice_in_the_words(self):
        # What a player must do to go on stays (try again, sign in, the log that says why); how to set or use the game,
        # or whom to ask, is theirs to decide: the Help page's tips and the errors' "ask the server's admin" went.
        for key, (en, ko) in i18n.TEXT.items():
            for phrase in ("server's admin whether", "Ask the server's admin", "Tell the server's admin",
                           "Is the server on", "check the address", "Try a window", "If the sound breaks"):
                self.assertNotIn(phrase, en, key)
            for phrase in ("서버 관리자에게 물어보세요", "서버 관리자에게 알려 주세요", "켜져 있는지 확인하세요", "소리가 끊기면"):
                self.assertNotIn(phrase, ko, key)

    def test_no_card_or_line_of_usage(self):
        # A page shows what to do now and the state; how to use the game is in the players' guide (docs/play.md, On a
        # Windows PC): no How to play on PLAY or the guide's last step, no mouse, touch screen and keyboard cards on
        # Controls, no card of what to do when the game does not start on Help, no line on Sound about the in-game menu
        # (main had them all).
        usage = re.compile(r"(play\.how|help\.trouble|controls\.(mouse|click|drag|wheel|touch|fingers|edges|bar|"
                           r"keyboard|esc|menu|minimise|alt_f4|typing))\b")
        self.assertEqual([k for k in i18n.TEXT if usage.match(k)], [])
        self.assertNotIn("in-game menu", i18n.TEXT["sound.sub"][0])
        self.assertNotIn("메뉴", i18n.TEXT["sound.sub"][1])

    def test_a_setting_says_what_it_does_never_what_may_go_wrong(self):
        # The Screen page's lines say what a choice does (main: VSync off "with possible tearing", no limit "uses the
        # processor in full", cautions the owner's rules leave out of the product); no limit says what it does.
        for key in [k for k in i18n.TEXT if k.startswith(("screen.", "sound."))]:
            en, ko = i18n.TEXT[key]
            # "no tearing" is what VSync on does; tearing that may come is a caution.
            self.assertIsNone(re.search(r"(?i)tearing|processor|in full", en.replace("no tearing", "")), key)
            for phrase in ("찢어질 수", "프로세서", "최대로 씁니다"):
                self.assertNotIn(phrase, ko, key)
        self.assertIn("screen.fps.hint.free.unlimited", i18n.TEXT)

    def test_a_name_takes_its_own_room_in_both_languages(self):
        # A setting's or a form's name keeps room for its words in both languages, its own entry's: Online's 서버 주소 is
        # also the report's words for "the servers' addresses", which main counted too, so Korean forms stood 39 px
        # wider than English ones and the page moved as the language changed.
        for language in ("en", "ko"):
            w = i18n.Words(language)
            self.assertEqual(i18n.every_language(w("online.address")), sorted(i18n.TEXT["online.address"]), language)
            # Filled in, words are no entry's own: looked up by their words, as before.
            self.assertEqual(i18n.every_language(w("online.to_play", name="Club")), [w("online.to_play", name="Club")])

    def test_one_korean_sentence_says_one_thing(self):
        # A Korean sentence two keys share says the same as both their English ones: main said "아직 플레이 기록이 없습니다."
        # for the records' "No plays recorded yet." and for the last game's "No game yet.", so the Korean PLAY page said
        # there were no records beside the records it listed. Names and buttons aside (연결 테스트 for the test and its
        # button, 로그인 for Sign-in and Sign in): Korean names them alike.
        said = {}
        for key, (en, ko) in i18n.TEXT.items():
            if re.search(r"[.?!]$", ko.strip()):
                said.setdefault(ko, {})[key] = en
        for ko, keys in said.items():
            self.assertEqual(len(set(keys.values())), 1, (ko, keys))
        # The last game says this PC; the records keep their own sentence.
        self.assertNotEqual(i18n.TEXT["play.last.none"][1], i18n.TEXT["play.records.none"][1])
        self.assertIn("이 PC", i18n.TEXT["play.last.none"][1])

    def test_a_download_is_said_as_a_download(self):
        # The owner's word for downloading is 다운로드 (main kept 받다 in twenty lines: "새 앱 받기" beside "앱 다운로드",
        # the guide's "앱 받기", "받은 앱", "받다 만 파일"). 받다 stays only for a server that takes a connection or a sign-in.
        for key, (_en, ko) in i18n.TEXT.items():
            for found in re.finditer("받", ko):
                self.assertTrue(ko[:found.start()].endswith(("연결을 ", "로그인을 ", "로그인을 더 이상 ")), (key, ko))
        self.assertEqual(i18n.TEXT["guide.download.title"][1], "앱 다운로드")

    def test_the_server_is_run_by_its_owner(self):
        # Where the words point a player to the person who runs the server, that person is its owner (소유자), as the docs
        # and the site say (main: "the server's admin", "서버 관리자"). Windows' administrator rights stay 관리자 권한.
        for key, (en, ko) in i18n.TEXT.items():
            self.assertIsNone(re.search(r"(?i)\b(server's|its) admin\b", en), key)
            self.assertNotIn("서버 관리자", ko, key)
        for key in ("online.signin.hint", "guide.power.need.1", "guide.server.text", "error.server.too_old"):
            self.assertIn("owner", i18n.TEXT[key][0], key)
            self.assertIn("소유자", i18n.TEXT[key][1], key)

    def test_english_as_a_person_writes_it(self):
        # main's English read as translated: "All 5 asks answered: 3 ms in the middle", "18 ms out", "it is no OpenDMTQ
        # server for PCs", "without the part for PCs", "where the game leaves room there", and "Files put back: 1. Some
        # are the launcher's own" for one file.
        for key, (en, _ko) in i18n.TEXT.items():
            for phrase in ("asks answered", "None of the asks", "in the middle", "it is no ", "the part for PCs",
                           "leaves room there", "Some are the"):
                self.assertNotIn(phrase, en, key)
            # A sound's delay to the device's output says so: never "18 ms out".
            self.assertIsNone(re.search(r"\bms out\b", en), key)
        # One file put back, said as one.
        self.assertTrue(i18n.TEXT["help.repair.done.restart.one"][0].startswith("One file put back"))

    def test_one_title_for_one_thing(self):
        # The Sound page's card of the last game's sound and PLAY's Last game are two things, with two titles (main
        # called both Last game, 지난 플레이).
        for i in (0, 1):
            self.assertNotEqual(i18n.TEXT["sound.last"][i], i18n.TEXT["play.last"][i])

    def test_the_uninstall_says_what_it_removes(self):
        # The installer's and the uninstall's lines say what they do, as a person writes it: "Removes OpenDMTQ from this
        # PC", never "OpenDMTQ goes from this PC" or "they go too" (main).
        for key, (en, _ko) in i18n.TEXT.items():
            self.assertIsNone(re.search(r"\bgoes (back )?from\b|\bgo too\b|\bgo\.|^Gone:|only the program goes|"
                                        r"\{size\} goes", en), (key, en))

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

    def test_the_owners_notice_word_for_word(self):
        # The notice's two lines in the launcher's About page and the installer are the site's footer's, word for word,
        # in both languages (the second, "OpenDMTQ contains no game data", was missing); the bundle's README has it too.
        root = os.path.join(PACKAGE, "..", "..")
        with open(os.path.join(root, "server", "portal", "strings.php"), encoding="utf-8") as f:
            site = re.findall(r"'foot\.line([12])' => '((?:[^'\\]|\\.)*)'", f.read())
        self.assertEqual(len(site), 4)
        for (line, words), lang in zip(site, ("en", "en", "ko", "ko")):
            key = "about.notice" if line == "1" else "about.notice.2"
            self.assertEqual(i18n.TEXT[key][0 if lang == "en" else 1], words.replace("\\'", "'"), key)
        with open(os.path.join(root, "host", "windows", "README.txt"), encoding="utf-8") as f:
            self.assertIn(i18n.TEXT["about.notice.2"][0], " ".join(f.read().split()))
        # Used by both windows: the About page and the installer's own notice.
        for name in ("pages.py", "setup_window.py"):
            with open(os.path.join(PACKAGE, name), encoding="utf-8") as f:
                self.assertIn('"about.notice.2"', f.read(), name)

    def test_the_address_example_is_on_a_new_servers_port(self):
        # A new server is on 8791: the example in an empty address field shows that port, as the server's own pages name
        # it (cli/opendmtq_cli/env.py DEFAULT_PORT).
        for example in i18n.TEXT["online.address.example"]:
            self.assertTrue(example.endswith(":8791"), example)

    def test_no_file_name_a_player_never_has(self):
        # Players get the installer as the site or a release names it (opendmtq-pc-client-...-setup....exe): the words
        # say "the installer", never the build's own OpenDMTQ-Setup.exe.
        for key, pair in i18n.TEXT.items():
            for text in pair:
                self.assertNotIn("OpenDMTQ-Setup", text, key)

    def test_the_bar_over_the_game_is_said_as_it_is(self):
        # The bar holds Sound, minimise, full screen and X, and comes down by the pointer, a finger or the mouse drawing
        # it down: the players' guide says it with the rest of how to play on a PC (the launcher's pages say nothing of
        # usage), the keys of each LINE mode as the Controls page names them among it; the PC's needs name the keyboard.
        with open(os.path.join(PACKAGE, "..", "..", "docs", "play.md"), encoding="utf-8") as f:
            play = " ".join(f.read().split())
        windows = play[play.index("## On a Windows PC"):play.index("## Updates and other devices")]
        for words in ("**Sound**", "drawn down", "full screen", "**X**", "**Esc**", "F J in 2 LINE", "D F J in 3 LINE",
                      "D F J K in 4 LINE", "**Controls**", "a click is a tap"):
            self.assertIn(words, windows)
        en, ko = i18n.TEXT["guide.power.need.2"]
        self.assertIn("keyboard", en)
        self.assertIn("키보드", ko)
        # The player's own guide (its README.txt) says the same, and that Esc does nothing in a song.
        with open(os.path.join(PACKAGE, "..", "..", "arm32", "desktop", "README-windows.txt"), encoding="utf-8") as f:
            guide = " ".join(f.read().split())
        self.assertIn("Sound, minimise, full screen, and X to quit", guide)
        self.assertNotIn("pauses a song", guide)


class KoreanParticles(unittest.TestCase):
    def test_a_particle_after_a_sign_a_letter_or_a_digit_is_attached(self):
        # "/로 이은", "PLAY를", "2 LINE에서", "{name}에서": a particle goes against what it follows, with no space, as
        # Korean writes it after Latin letters, digits and signs ("/ 로" read as a stray word).
        particle = re.compile(r"[/A-Za-z0-9}] (로|으로|를|을|와|과|에서|에게|에|은|는|이|가)(?=[ .,)]|$)")
        for key, (_en, ko) in i18n.TEXT.items():
            self.assertIsNone(particle.search(ko), key)

    def test_a_server_responds_and_a_sound_plays(self):
        # As a Korean product says it: a server 응답합니다, the game's sound 재생합니다 or 들려줍니다, frames are drawn
        # (화면을 그립니다), a file is 선택해 두었습니다 (main: 답합니다, 답함, 소리를 냅니다, 프레임을 내보냅니다, 선택되어
        # 있습니다, read as translated).
        for key, (_en, ko) in i18n.TEXT.items():
            # 답 alone for an answer, never inside 응답.
            self.assertIsNone(re.search(r"(?<!응)답(합니다|하지|이 없|함|한 것)", ko), key)
            for old in ("어느 질문에도", "무언가 답", "냅니다", "낼 장치", "선택되어 있습니다", "PC용 부분"):
                self.assertNotIn(old, ko, key)

    def test_no_mechanical_particles(self):
        # "(으)로", "을(를)" and the like read as a form being filled in: the words are put so that none is needed.
        for key, (_en, ko) in i18n.TEXT.items():
            self.assertIsNone(re.search(r"\((으|을|를|이|가|은|는|와|과)\)|(을|이|은|와)\((를|가|는|과)\)", ko), key)

    def test_one_korean_word_for_each_thing(self):
        # One word for each thing, as the admin pages say it: a sign-in that ran out is 만료, a game that closed on its
        # own 예기치 않게 종료, this PC's id 기기 ID, the Music volume 음악 and the Custom preset 커스텀 (the in-game panel
        # says the same), a button 버튼 as the site and the game's own pages say it.
        for key, (_en, ko) in i18n.TEXT.items():
            for old in ("로그인이 끝났", "저절로 닫", "플레이어 ID", "배경음", "바쁜 PC", "잠시만요", "단추", "자기 주소", "사운드 장치"):
                self.assertNotIn(old, ko, key)
        # A sound device is 소리 장치 on the Sound page and in Help's report line alike (main: 사운드 장치 there); Back is
        # 뒤로 in the guide and in the installer (main: 이전 in the installer); forgetting a server has a word of its own
        # (main: 지우기, as Clear game data's button).
        self.assertIn("소리 장치", i18n.TEXT["help.report.hint"][1])
        self.assertEqual(i18n.TEXT["setup.previous"][1], i18n.TEXT["guide.back"][1])
        self.assertNotEqual(i18n.TEXT["online.forget"][1], i18n.TEXT["help.clear.confirm"][1])
        self.assertEqual(i18n.TEXT["sound.volume.music"][1], "음악")
        self.assertEqual(i18n.TEXT["sound.eq.custom"][1], "커스텀")
        with open(os.path.join(PACKAGE, "..", "..", "arm32", "desktop", "overlay_win32.cpp"), encoding="utf-8") as f:
            panel = f.read()
        self.assertIn('L"마스터", L"음악", L"효과음"', panel)
        self.assertIn('L"트레블", L"커스텀"}', panel)


if __name__ == "__main__":
    unittest.main()
