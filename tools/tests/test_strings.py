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
# Quoted file names in the sources look like keys too.
FILE_ENDINGS = (".html", ".json", ".md", ".fpk", ".webm", ".py", ".css", ".log", ".png", ".jpg", ".zip")


def values_in(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def used_keys():
    """Every key the admin's Python, its templates and songs.py ask for."""
    # The admin's modules (its pages and the setup), songs.py, and every template.
    sources = [read(os.path.join(ADMIN, name)) for name in sorted(os.listdir(ADMIN)) if name.endswith(".py")]
    sources.append(read(os.path.join(TOOLS, "opendmtq_tools", "songs.py")))
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
        self.assertEqual(set(strings.STRINGS["en"]) - used_keys(), set())

    def test_the_korean_follows_the_house_rules(self):
        for key, text in strings.STRINGS["ko"].items():
            self.assertIsNone(LOOSE_JOSA.search(text), f"{key}: a josa with a space before it: {text}")
        for table in strings.STRINGS.values():
            for key, text in table.items():
                self.assertNotIn(EM_DASH, text, key)

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
            self.assertNotIn("owner", text, key)


if __name__ == "__main__":
    unittest.main()
