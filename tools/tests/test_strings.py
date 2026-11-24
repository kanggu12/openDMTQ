"""The texts of the admin pages (strings.py): both languages have every key the code uses, with the same
values to fill in, and the Korean follows the house rules. The portal's table too: the gate and CI mount server/portal
beside tools/ in the tools image for it."""

import os
import re
import string
import unittest

from opendmtq_tools import songs, strings

TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADMIN = os.path.join(TOOLS, "opendmtq_tools", "admin")
PORTAL_LIB = os.path.join(TOOLS, "..", "server", "portal", "lib.php")
PORTAL_STRINGS = os.path.join(TOOLS, "..", "server", "portal", "strings.php")
# A josa after a Latin word, a number or a placeholder, with a space in between.
LOOSE_JOSA = re.compile(r"[A-Za-z0-9})] (?:은|는|이|가|을|를|의|에|에서|에게|로|으로|와|과|도|만)(?![가-힣])")
HANGUL = re.compile(r"[가-힣]")
EM_DASH = "—"
# The site's lines MY PAGE shows the owner alone, of their own account: the only ones of the site that say "owner".
OWNER_ONLY = ("me.owner_player", "me.rights_owner", "me.owner_line", "me.owner_pw")
# Quoted file names in the sources look like keys too.
FILE_ENDINGS = (".html", ".json", ".md", ".fpk", ".webm", ".py", ".css", ".log", ".png", ".jpg", ".zip")


def values_in(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def used_keys():
    """Every key the admin's Python, its templates, songs.py and song_files.py ask for."""
    # The admin's modules (its pages and the setup), songs.py and the song file checks it raises from, and every
    # template.
    sources = [read(os.path.join(ADMIN, name)) for name in sorted(os.listdir(ADMIN)) if name.endswith(".py")]
    sources += [read(os.path.join(TOOLS, "opendmtq_tools", name)) for name in ("songs.py", "song_files.py")]
    templates = os.path.join(ADMIN, "templates")
    sources += [read(os.path.join(templates, name)) for name in sorted(os.listdir(templates))]
    found = set()
    for source in sources:
        found.update(re.findall(r"""\btp?\(\s*["']([\w.]+)["']""", source))
        found.update(re.findall(r"""SongError\(\s*"([\w.]+)\"""", source))
    # The ones chosen by a condition or kept in a list: any quoted word that looks like a key of the table.
    known_groups = {key.split(".")[0] for key in strings.STRINGS["en"]}
    for source in sources:
        for key in re.findall(r"""["']((?:[a-z]+)\.[a-z_0-9]+)["']""", source):
            if key.split(".")[0] in known_groups and not key.endswith(FILE_ENDINGS):
                found.add(key)
    return found


class AdminStrings(unittest.TestCase):
    def test_both_languages_have_the_same_keys(self):
        en, ko = set(strings.STRINGS["en"]), set(strings.STRINGS["ko"])
        self.assertEqual(en - ko, set(), "missing in Korean")
        self.assertEqual(ko - en, set(), "missing in English")

    def test_both_languages_fill_in_the_same_values(self):
        for key, text in strings.STRINGS["en"].items():
            self.assertEqual(values_in(text), values_in(strings.STRINGS["ko"][key]), key)

    def test_every_key_the_code_uses_exists(self):
        used = used_keys()
        self.assertGreater(len(used), 100)
        self.assertEqual(used - set(strings.STRINGS["en"]), set())

    def test_every_key_in_the_table_is_used(self):
        # A key's words for one ({key}.one) are used wherever the key is, with its count.
        used = used_keys()
        self.assertEqual({k for k in strings.STRINGS["en"] if k not in used and k.removesuffix(".one") not in used}, set())

    def test_the_words_for_one_go_with_a_count(self):
        # Each {key}.one stands for its key's words when {n} is 1: that key counts with {n}, and the words for one fill in
        # the same values but the count.
        for lang, table in strings.STRINGS.items():
            for key, words in table.items():
                if key.endswith(".one"):
                    base = table.get(key.removesuffix(".one"), "")
                    self.assertIn("{n}", base, f"{lang} {key}")
                    self.assertEqual(values_in(words) | {"n"}, values_in(base) | {"n"}, f"{lang} {key}")
        self.assertEqual(strings.text("en", "setup.song_count", n=1), "1 song")
        self.assertEqual(strings.text("en", "setup.song_count", n=2), "2 songs")
        self.assertEqual(strings.text("ko", "setup.song_count", n=1), "1곡")

    def test_the_korean_follows_the_house_rules(self):
        for key, text in strings.STRINGS["ko"].items():
            self.assertIsNone(LOOSE_JOSA.search(text), f"{key}: a josa with a space before it: {text}")
        for table in strings.STRINGS.values():
            for key, text in table.items():
                self.assertNotIn(EM_DASH, text, key)

    def test_one_term_for_one_thing_and_no_fallback_particles(self):
        # The admin pages name each thing one way (관리자 페이지, 일일 백업, 휴대폰, 앱을 만들다), never put a particle as a
        # form's fallback after a value ("(으)로", "은(는)", "을(를)"), and say a sign-in ran out as 만료.
        for key, text in strings.STRINGS["ko"].items():
            for old in ("관리 페이지", "매일 백업", "빌드", "로그인이 끝났", "(으)로", "은(는)", "을(를)", "돌아서 ", "돕니다"):
                self.assertNotIn(old, text, key)
            self.assertIsNone(re.search(r"(?<!휴대)(?<!아이)폰", text), key)

    def test_the_notices_page_and_its_cards_share_one_word(self):
        # The menu's word for the Notices page is its cards' (공지), as the game's own toast says it, and the setup goes on
        # in the words a Korean reader uses (ADM-195).
        ko = strings.STRINGS["ko"]
        self.assertEqual(ko["nav.notices"], "공지")
        for key in ("notices.title", "maint.heading", "notice.heading"):
            self.assertIn("공지", ko[key], key)
        for key, text in ko.items():
            for old in ("점검 안내", "이어 하기"):
                self.assertNotIn(old, text, key)
        self.assertEqual(ko["setup.continue"], "설정 계속하기")

    def test_the_pages_carry_no_usage_text(self):
        # A screen shows what to do now and the state; how to use something is the docs' (ADM-201): no steps of how to
        # install and play on a phone in the setup, no card of how to play from a Windows PC, nothing of how the game
        # earns and spends a currency, nothing of how a program sends an API token.
        for lang, table in strings.STRINGS.items():
            for key in ("setup.phone_title", "setup.phone_open", "setup.phone_open_url", "setup.phone_signin",
                        "setup.phone_install", "setup.phone_play", "setup.qr_alt", "here.elsewhere_title", "game.max_how",
                        "game.q_how"):
                self.assertNotIn(key, table, f"{lang} {key}")
            self.assertNotIn("Authorization", table["tok.lead"], lang)
            self.assertNotIn("EXP", table["game.level_lead"], lang)

    def test_a_song_error_reads_in_english_and_keeps_its_key(self):
        e = songs.SongError("song.missing", name="song.fpk")
        self.assertEqual(str(e), "song.fpk is missing")
        self.assertEqual(strings.text("ko", e.key, **e.values), "song.fpk 파일이 없습니다")

    def test_a_key_nobody_has_comes_back_as_it_is(self):
        self.assertEqual(strings.text("ko", "no.such.key"), "no.such.key")


@unittest.skipUnless(os.path.isfile(PORTAL_LIB), "the portal is not at hand")
class PortalStrings(unittest.TestCase):
    def setUp(self):
        table = read(PORTAL_STRINGS)
        en_at, ko_at = table.index("'en' => ["), table.index("'ko' => [")
        line = re.compile(r"""^\s+'([\w.]+)' => (['"])(.*)\2,$""", re.M)
        self.en = {m.group(1): m.group(3) for m in line.finditer(table, en_at, ko_at)}
        self.ko = {m.group(1): m.group(3) for m in line.finditer(table, ko_at)}

    def test_both_languages_have_the_same_keys_and_values(self):
        self.assertEqual(set(self.en), set(self.ko))
        for key, text in self.en.items():
            self.assertEqual(set(re.findall(r"{(\w+)}", text)), set(re.findall(r"{(\w+)}", self.ko[key])), key)

    def test_the_words_for_one_go_with_a_count(self):
        # A page's t('key', ['n' => 1]) takes {key}.one (t_table() in lib.php): its key counts with {n}.
        for table in (self.en, self.ko):
            for key, text in table.items():
                if key.endswith(".one"):
                    self.assertIn("{n}", table.get(key.removesuffix(".one"), ""), key)

    def test_the_site_carries_no_usage_text(self):
        # The download page has the steps and what must be so to go on, no notes or folded help of how the app and the game
        # go on (play.md and troubleshooting.md have them), and of the PC client what it runs on, not how it is played;
        # MY PAGE has its account's state, not who sets what or where a control is (ADM-201).
        for key in ("note.songs", "note.update", "note.other", "step.net", "help.title", "help.other", "help.32bit",
                    "help.compat", "me.decided"):
            self.assertNotIn(key, self.en, key)
            self.assertNotIn(key, self.ko, key)
        self.assertEqual((self.en["pc.needs"], self.ko["pc.needs"]), ("It runs on 64-bit Windows 10 or 11.", "64비트 Windows 10이나 11에서 실행됩니다."))
        for table in (self.en, self.ko):
            self.assertNotIn("KOR / ENG", table["me.language_now"])

    def test_an_account_without_admin_rights_says_so(self):
        # MY PAGE's row of the admin pages, for an account that has no rights there: said as that (ADM-195).
        self.assertEqual((self.en["me.rights_no"], self.ko["me.rights_no"]), ("No admin rights", "관리자 권한 없음"))

    def test_the_server_name_is_read_from_the_process_environment(self):
        # Under Apache, plain getenv('SERVER_NAME') is the visitor's host name, not the setting.
        self.assertIn("getenv('SERVER_NAME', true)", read(PORTAL_LIB))

    def test_every_key_the_pages_use_exists(self):
        portal = os.path.dirname(PORTAL_LIB)
        for name in os.listdir(portal):
            if name.endswith(".php"):
                for key in re.findall(r"""\bt\(\s*'([\w.]*\w)'""", read(os.path.join(portal, name))):
                    self.assertIn(key, self.en, name)

    def test_the_korean_follows_the_house_rules(self):
        for key, text in self.ko.items():
            self.assertIsNone(LOOSE_JOSA.search(text), f"{key}: {text}")
            self.assertNotIn(EM_DASH, text, key)
            # A tablet counts: "폰" alone only in the words that name both, or a phone in particular.
            if "폰" in text.replace("아이폰", "").replace("폰과 태블릿", "").replace("폰이나 태블릿", ""):
                self.fail(f"{key}: {text}")
        for key, text in self.en.items():
            self.assertNotIn(EM_DASH, text, key)

    def test_the_owner_is_called_the_owner(self):
        # One word for the owner, the admin pages' (소유자, Owner): MY PAGE's lines for the owner's own account too, never
        # "the server's own account" (ADM-194).
        # The table's own text, its quotes escaped as PHP writes them in single quotes.
        plain = lambda text: text.replace("\\'", "'")
        for key in OWNER_ONLY:
            self.assertIn("owner's account", plain(self.en[key]), key)
            self.assertIn("소유자 계정", self.ko[key], key)
        for table in (self.en, self.ko):
            for key, text in table.items():
                self.assertNotIn("server's own account", plain(text), key)
                self.assertNotIn("서버 자체의 계정", text, key)

    def test_the_person_who_runs_the_server_is_its_owner(self):
        # Where the site points a player to the person who runs the server (whose ID and password they sign in with, who
        # links their account and switches their broadcasts), it is the server's owner, the word of the docs, the admin
        # pages and the launcher: never "the server's admin" (서버 관리자), which named the person by the pages' word. The
        # admin pages themselves (관리자 페이지) and admin rights keep theirs (PAGE-105).
        plain = lambda text: text.replace("\\'", "'")
        for key, text in self.en.items():
            self.assertNotIn("server's admin", plain(text), key)
        for key, text in self.ko.items():
            self.assertNotIn("서버 관리자", text, key)
            self.assertIsNone(re.search(r"관리자(?:가|에게|는|께)", text), f"{key}: {text}")
        for key in ("signin.lead", "me.not_linked", "me.cast_switch"):
            self.assertIn("server's owner", plain(self.en[key]), key)
            self.assertIn("서버 소유자", self.ko[key], key)


if __name__ == "__main__":
    unittest.main()
