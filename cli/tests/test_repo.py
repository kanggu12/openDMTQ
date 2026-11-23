"""Tests for repository settings that a clone depends on."""

import argparse
import ast
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.dom.minidom
from unittest import mock

from opendmtq_cli import system

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))



class TestCasesTest(unittest.TestCase):
    """docs/test-cases.md keeps up with the tests it points at."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "docs", "test-cases.md"), encoding="utf-8") as f:
            cls.text = f.read()
        # A table row: ID, scenario, expected, checked by, stage.
        cls.rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in cls.text.splitlines()
                    if re.match(r"\| [A-Z]+-\d+ \|", line)]

    def test_there_are_cases_and_each_row_has_its_five_columns(self):
        self.assertGreater(len(self.rows), 60)
        for row in self.rows:
            self.assertEqual(len(row), 5, row)

    def test_every_id_is_used_once(self):
        ids = [row[0] for row in self.rows]
        self.assertEqual(sorted(ids), sorted(set(ids)))

    def test_every_stage_is_one_the_document_explains(self):
        for row in self.rows:
            self.assertIn(row[4], ("unit", "ui", "qa", "hand"), row[0])

    def test_only_what_a_person_does_may_point_at_nothing(self):
        for row in self.rows:
            if row[4] != "hand":
                self.assertTrue(row[3], row[0])

    def test_every_pointer_finds_its_file_and_its_words(self):
        for row in self.rows:
            for pointer in re.findall(r"`([^`#]+)#([^`]+)`", row[3]):
                path = os.path.join(ROOT, pointer[0])
                self.assertTrue(os.path.isfile(path), f"{row[0]}: no {pointer[0]}")
                with open(path, encoding="utf-8") as f:
                    self.assertIn(pointer[1], f.read(), f"{row[0]}: {pointer[0]} does not say this")

    def test_every_test_file_is_in_some_case(self):
        # The unit tests of the three Python packages: the tools, the command line and the PC client. The docs say each
        # of their files is in a row, so a new one fails here until it is.
        for pattern in ("tools/tests/test_*.py", "cli/tests/test_*.py", "client/tests/test_*.py"):
            for path in glob.glob(os.path.join(ROOT, pattern)):
                name = os.path.relpath(path, ROOT).replace(os.sep, "/")
                self.assertIn(name, self.text, f"{name} is in no test case")


class ApiDocsTest(unittest.TestCase):
    """docs/api.md keeps up with the API's route table (tools/opendmtq_tools/admin/api_routes.py, which the API registers its
    routes from): every route is in it, its reference is the one the table makes, and it names no route there is not."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        # Loaded from its path: the admin package itself needs Flask, the table only the standard library.
        spec = importlib.util.spec_from_file_location("api_routes", os.path.join(ROOT, "tools", "opendmtq_tools", "admin", "api_routes.py"))
        cls.table = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.table)
        with open(os.path.join(ROOT, "docs", "api.md"), encoding="utf-8") as f:
            cls.text = f.read()

    def route_for(self, path, method=None):
        """The route a path names (its parts may be values or {names}), with this method when given; None when none does."""
        path = path.split("?", 1)[0].rstrip(".,:")
        for route in self.table.ROUTES:
            pattern = "^" + re.sub(r"\\\{\w+\\\}", "[^/]+", re.escape(route.path)) + "$"
            if re.match(pattern, path) and (method is None or route.method == method):
                return route
        return None

    def test_every_route_is_in_the_docs(self):
        for route in self.table.ROUTES:
            self.assertIn(f"`{route.method} {route.path}`", self.text, route.name)

    def test_the_reference_is_the_one_the_table_makes(self):
        start, end = self.text.index(self.table.REFERENCE_START), self.text.index(self.table.REFERENCE_END)
        made = self.table.reference()
        self.assertEqual(self.text[start:end + len(self.table.REFERENCE_END)] + "\n", made,
                         "run: python3 tools/opendmtq_tools/admin/api_routes.py docs/api.md")

    def test_the_docs_name_no_route_there_is_not(self):
        base = self.table.BASE
        # A method and a path ("POST /builds"), an address under the API's own, and the examples' $API/...
        named = [(m, p[len(base):] if p.startswith(base) else p) for m, p in re.findall(r"\b(GET|POST|PUT|DELETE|PATCH) (/[^\s`)\"'<]*)", self.text)]
        named += [(None, p) for p in re.findall(re.escape(base) + r"(/[^\s`)\"'<]*)", self.text)]
        named += [(None, p) for p in re.findall(r"\$API(/[^\s`)\"'<]*)", self.text)]
        self.assertGreater(len(named), 100)
        for method, path in named:
            # The API's own address alone is no route.
            if path.split("?", 1)[0] in ("/", ""):
                continue
            self.assertIsNotNone(self.route_for(path, method), f"{method or ''} {path}")


class DashesTest(unittest.TestCase):
    def test_no_dash_on_the_pages(self):
        # The pages a person reads, the players' site and the admin pages, and their words: no en or em dash, an empty
        # value's mark among them (it was an en dash in five places), as the words of the project are written.
        paths = []
        for folder, kinds in (("server/portal", ("*.php", "*.js", "*.css")), ("server/game", ("*.php",)),
                              ("tools/opendmtq_tools/admin/templates", ("*.html",)),
                              ("tools/opendmtq_tools/admin/static", ("*.js", "*.css"))):
            for kind in kinds:
                paths += glob.glob(os.path.join(ROOT, folder, "**", kind), recursive=True)
        paths.append(os.path.join(ROOT, "tools", "opendmtq_tools", "strings.py"))
        self.assertGreater(len(paths), 40)
        for path in paths:
            if path.endswith(".min.js"):
                continue
            with open(path, encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    self.assertNotRegex(line, "[\u2013\u2014]", f"{os.path.relpath(path, ROOT)}:{n}")


class DownloadWordTest(unittest.TestCase):
    def test_the_owners_word_for_getting_the_app(self):
        # Getting the app or a file is "다운로드" in every Korean string, the site's, the admin pages', the launcher's and
        # the player's (the owner's word, "앱 다운로드"; 내려받기 had taken its place in 48 of them).
        paths = [os.path.join(ROOT, *p.split("/")) for p in (
            "server/portal/strings.php", "tools/opendmtq_tools/strings.py", "client/opendmtq_client/i18n.py")]
        paths += glob.glob(os.path.join(ROOT, "arm32", "desktop", "*.cpp")) + glob.glob(os.path.join(ROOT, "arm32", "desktop", "*.h"))
        for path in paths:
            with open(path, encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    self.assertNotIn("내려받", line, f"{os.path.relpath(path, ROOT)}:{n}")


class AdviceTest(unittest.TestCase):
    def test_no_usage_advice_in_the_pages_and_the_programs(self):
        # The pages, the command line, the host program and the bundle's guide say what a person must do to go on, never
        # how to use the tool or whom to ask (the owner's rule): the phrases that did are gone. The README and the docs
        # keep "use only files you have the right to use".
        paths = [os.path.join(ROOT, *p.split("/")) for p in (
            "server/portal/strings.php", "tools/opendmtq_tools/strings.py", "host/windows/README.txt")]
        paths += glob.glob(os.path.join(ROOT, "cli", "opendmtq_cli", "*.py"))
        paths += glob.glob(os.path.join(ROOT, "host", "opendmtq_host", "*.py"))
        phrases = ("right to use", "(recommended)", "(추천)", "check it before the app is built", "Tell the server's admin",
                   "tell the server's admin", "use an older phone", "서버 관리자에게 알려", "오래된 폰이나 태블릿을 쓰세요",
                   "If nothing changes in a few minutes", "make sure your firewall", "Clone it inside WSL",
                   "DHCP reservation", "is safer", "이용할 권리가 있는 파일만")
        for path in paths:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            for phrase in phrases:
                # The license's own words say what the license gives (lic.game): a fact, not advice.
                kept = text.replace("it gives no right to use them", "")
                self.assertNotIn(phrase, kept, f"{os.path.relpath(path, ROOT)}: {phrase}")


class PlayerRateTest(unittest.TestCase):
    def test_the_readme_says_the_players_own_limit(self):
        # The player takes any frame limit up to its own most (arm32/desktop/settings.cpp) and follows the display's
        # rate with VSync: the README names that most, never a cap of the display it was measured on (it said 240 Hz).
        with open(os.path.join(ROOT, "arm32", "desktop", "settings.cpp"), encoding="utf-8") as f:
            most = re.search(r"number\(value, 30, (\d+), n\)", f.read()).group(1)
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            text = " ".join(f.read().split())
        self.assertIn(f"up to {most} frames a second", text)
        self.assertNotRegex(text, r"up to \d+ Hz")


class SecurityModelTest(unittest.TestCase):
    def test_it_says_which_visits_count_as_the_server_pcs_under_docker_engine(self):
        # Measured on Docker Engine: a browser on the server PC that opens localhost, a container of the same machine on
        # any network that opens the PC's address or its network's gateway, and a TCP tunnel on the PC all reach the
        # server from the stack network's gateway, which the server takes for the server PC's own (server/entrypoint.sh
        # LOCAL_FROM, and Play on this PC: this_pc.py). The security model says so, and what keeps the admin pages to the
        # PC then (ADM-179; main's said only that a proxy's headers make a visit one from elsewhere).
        with open(os.path.join(ROOT, "docs", "architecture.md"), encoding="utf-8") as f:
            model = " ".join(re.search(r"## Security model\n(.*?)\n## ", f.read(), re.S).group(1).split())
        for words in ("a container of the same machine on any Docker network", "a TCP tunnel or stream proxy running on the PC",
                      "for the admin pages of an exposed server and for Play on this PC", "What keeps the admin pages to the server PC then",
                      "the sign-in", "stands before every page and every API call either way"):
            self.assertIn(words, model)
        # The rule the words describe, where the code keeps it.
        with open(os.path.join(ROOT, "server", "entrypoint.sh"), encoding="utf-8") as f:
            self.assertIn("Require ip $LOCAL_FROM", f.read())
        with open(os.path.join(ROOT, "tools", "opendmtq_tools", "admin", "this_pc.py"), encoding="utf-8") as f:
            self.assertIn("ip == auth.stack_gateway()", f.read())


class WindowsLinesTest(unittest.TestCase):
    def test_the_guides_count_the_windows_lines_as_the_block_has_them(self):
        # The guides say "the same N lines" of the Windows install's PowerShell block: as many as it has (they said four
        # after it grew to five).
        with open(os.path.join(ROOT, "docs", "install.md"), encoding="utf-8") as f:
            block = re.search(r"```powershell\n(.*?)```", f.read(), re.S).group(1)
        count = len([line for line in block.splitlines() if line.strip()])
        word = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}[count]
        for name in ("docs/install.md", "docs/faq.md", "README.md", "tests/windows/update.sh"):
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                for said in re.findall(r"\b(three|four|five|six|seven) lines\b", f.read()):
                    self.assertEqual(said, word, name)


class DocVersionsTest(unittest.TestCase):
    """.github/doc_versions.py: the README's quick start and the guides download the release the chart names, by the
    names its files have, so that a line copied from them fetches what it says."""

    @classmethod
    def setUpClass(cls):
        # The script lives outside any package (in .github/), so it is loaded from its path, as release_notes.py is.
        import importlib.util
        spec = importlib.util.spec_from_file_location("doc_versions", os.path.join(ROOT, ".github", "doc_versions.py"))
        cls.versions = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.versions)

    def tree(self, d, chart, readme, guide=""):
        """A tree of its own: the chart at a version, a README and one guide, and the script the one-line install runs."""
        from pathlib import Path
        root = Path(d)
        (root / "deploy" / "helm" / "opendmtq").mkdir(parents=True)
        (root / "deploy" / "helm" / "opendmtq" / "Chart.yaml").write_text(
            f'apiVersion: v2\nversion: {chart}\nappVersion: "{chart}"\n', encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "install.md").write_text(guide, encoding="utf-8")
        (root / "host").mkdir()
        (root / "host" / "get.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (root / "README.md").write_text(readme, encoding="utf-8")
        # The changelog keeps each release's own names: never read.
        (root / "CHANGELOG.md").write_text("opendmtq-server-0.1.0-windows-x64.zip\n", encoding="utf-8")
        return root

    def test_the_tree_names_the_release_its_chart_carries(self):
        from pathlib import Path
        self.assertEqual(self.versions.stale(Path(ROOT)), [])

    def test_the_quick_start_downloads_that_release(self):
        # The quick start's lines name the chart's release, so the check above has lines to check: the Windows server's
        # zip from the release's own address, and the one-line install's script at the release's tag.
        from pathlib import Path
        version = self.versions.chart_version(Path(ROOT))
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            quick = f.read().split("\n## Quick start\n", 1)[1].split("\n## ", 1)[0]
        base = "https://github.com/kanggu12/openDMTQ/releases/download"
        self.assertIn(f"curl.exe -fLO {base}/v{version}/opendmtq-server-{version}-windows-x64.zip", quick)
        self.assertIn(f"tar.exe -xf opendmtq-server-{version}-windows-x64.zip", quick)
        self.assertIn(f"curl -fsSL https://raw.githubusercontent.com/kanggu12/openDMTQ/v{version}/host/get.sh | sh", quick)

    def test_another_release_or_a_file_it_has_not_is_named_and_written_over(self):
        import tempfile
        old = ("curl.exe -fLO https://github.com/kanggu12/openDMTQ/releases/download/v1.9.0/opendmtq-server-1.9.0-windows-x64.zip\n"
               "curl -fsSL https://raw.githubusercontent.com/kanggu12/openDMTQ/v1.9.0/host/get.sh | sh\n")
        # The guides' stand-in for any release, another project's release, and a release's file that is not there.
        guide = ("V=1.2.3: opendmtq-phone-runtime-1.2.3-android-arm64-armv7.zip\n"
                 "https://github.com/iBotPeaches/Apktool/releases/download/v2.12.1/apktool_2.12.1.jar\n"
                 "https://github.com/kanggu12/openDMTQ/releases/download/v2.0.0/opendmtq-server-2.0.0-linux.zip\n")
        with tempfile.TemporaryDirectory() as d:
            root = self.tree(d, "2.0.0", old, guide)
            found = self.versions.stale(root)
            # Each line of the README once for its other release, and the file release 2.0.0 does not have.
            self.assertEqual([(p, n, what) for p, n, what, _ in found],
                             [("README.md", 1, "1.9.0"), ("README.md", 2, "1.9.0"),
                              ("docs/install.md", 3, "opendmtq-server-2.0.0-linux.zip")])
            # The run fails, saying each place with its fix, as the release's gate shows it.
            import contextlib
            import io
            said = io.StringIO()
            with contextlib.redirect_stderr(said):
                self.assertEqual(self.versions.main(["--root", d]), 1)
            self.assertIn("README.md:1 names 1.9.0: the chart is 2.0.0 (.github/doc_versions.py --write)", said.getvalue())
            # --write puts the chart's version in the README, and leaves the stand-in, the other project and the
            # changelog as they were.
            self.assertEqual(self.versions.write(root), ["README.md"])
            readme = (root / "README.md").read_text(encoding="utf-8")
            self.assertEqual(readme, old.replace("1.9.0", "2.0.0"))
            self.assertEqual((root / "docs" / "install.md").read_text(encoding="utf-8"), guide)
            self.assertIn("0.1.0", (root / "CHANGELOG.md").read_text(encoding="utf-8"))
            # The file that is not there stays to be put right by hand.
            self.assertEqual(len(self.versions.stale(root)), 1)
            # A link to the tree's own script at the tag: the script has to be in the tree.
            (root / "host" / "get.sh").unlink()
            self.assertIn(("README.md", 2, "host/get.sh", "the tree has no such file"), self.versions.stale(root))


class FiguresTest(unittest.TestCase):
    """The guides' figures name what the program has now: no setting it reads no more (ADMIN_PORT, the admin pages' own
    port before 0.11.0), no loopback address with a port, no build's file name a player never has."""

    def test_no_old_names_in_the_figures(self):
        for path in glob.glob(os.path.join(ROOT, "docs", "images", "*.svg")):
            with open(path, encoding="utf-8") as f:
                words = " ".join(re.findall(r">([^<]+)<", f.read()))
            for old in ("ADMIN_PORT", "127.0.0.1:", "OpenDMTQ-Setup.exe"):
                self.assertNotIn(old, words, os.path.basename(path))


class DesignTest(unittest.TestCase):
    """What the markup asks of the stylesheets, including pages no test reaches with a browser (an error page, a rare state)."""

    # A script's handle, or a level with the base look: no rule of their own, by design.
    HANDLES = {"get-app", "vod-only", "sortable", "c0"}

    @staticmethod
    def rules(*paths):
        """Every class a selector of these stylesheets names."""
        names = set()
        for path in paths:
            with open(os.path.join(ROOT, path), encoding="utf-8") as f:
                css = re.sub(r"/\*.*?\*/", "", f.read(), flags=re.S)
            for selector in re.findall(r"([^{}]+)\{", css):
                names.update(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", selector))
        return names

    @staticmethod
    def used(*patterns):
        """Every class the markup and scripts name, by file. A name glued to a template's value (c<?= $n ?>) is not a whole name."""
        found = {}
        for pattern in patterns:
            for path in glob.glob(os.path.join(ROOT, pattern)):
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                values = re.findall(r"""class(?:Name)?\s*=\s*\\?"([^"]*)\"""", text) + re.findall(r"""class(?:Name)?\s*=\s*'([^']*)'""", text)
                values += re.findall(r"""classList\.(?:add|toggle|remove)\(['"]([\w-]+)['"]""", text)
                for value in values:
                    # Python and PHP blocks may hold spaces: taken out whole, leaving a mark where a value goes.
                    value = re.sub(r"<\?=.*?\?>|\{\{.*?\}\}|\{%.*?%\}|\$\{.*?\}|\{[\w.]+\}|'\s*\.\s*.*?\.\s*'", "\0", value)
                    for name in value.split():
                        if "\0" not in name and re.fullmatch(r"-?[_a-zA-Z][\w-]*", name):
                            found.setdefault(name, set()).add(os.path.basename(path))
        return found

    def test_every_class_in_the_markup_has_a_style(self):
        portal = self.used("server/portal/*.php", "server/portal/*.js")
        rules = self.rules("server/portal/style.css")
        missing = {name: files for name, files in portal.items() if name not in rules and name not in self.HANDLES}
        self.assertEqual(missing, {}, "the public site")
        admin_pages = self.used("tools/opendmtq_tools/admin/templates/*.html", "tools/opendmtq_tools/admin/static/*.js", "tools/opendmtq_tools/admin/*.py")
        rules |= self.rules("tools/opendmtq_tools/admin/static/admin.css")
        missing = {name: files for name, files in admin_pages.items() if name not in rules and name not in self.HANDLES}
        self.assertEqual(missing, {}, "the admin pages")

    # Where a glow belongs to the site's own forms: the timeline's bright bar sweeping the front page, and its copy
    # crossing a song's jacket under the pointer (the game's Technika timeline, with its blue light).
    GLOWS_OF_THE_GAME = (".sweep", ".song-pic::after")

    @staticmethod
    def shadows(path):
        """Each shadow a stylesheet casts: (selector, the shadow's own words, inset or not, its numbers)."""
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            css = re.sub(r"/\*.*?\*/", "", f.read(), flags=re.S)
        found = []
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            for value in re.findall(r"(?:box|text)-shadow\s*:\s*([^;]+)", body):
                # One shadow after another, split at the commas that are no colour's own (rgba(...), color-mix(...)).
                depth, part, parts = 0, "", []
                for ch in value:
                    depth += {"(": 1, ")": -1}.get(ch, 0)
                    if ch == "," and depth == 0:
                        parts.append(part)
                        part = ""
                    else:
                        part += ch
                parts.append(part)
                for shadow in (p.strip() for p in parts if p.strip()):
                    words = re.sub(r"\([^)]*\)", "()", shadow).split()
                    numbers = [float(w[:-2] if w.endswith("px") else w) for w in words
                               if re.fullmatch(r"-?[\d.]+(px)?", w)]
                    found.append((selector.strip(), shadow, "inset" in words, numbers))
        return found

    def test_no_glow_round_a_state_and_no_stripe_along_a_box(self):
        # The site's and the admin pages' look without what reads as made by rote: a light of a state's colour blurred
        # round a dot, a field, a letter, a frame or a knob (0 0 and a blur: the dot's colour says the state), a wide
        # faint ring standing for one round a field with the focus (0 0 0 and 4 px or more: the field's own edge says
        # it), and a stripe of colour along a box's left edge (inset Npx 0 0: the box's own words say what it is).
        glows, stripes = [], []
        for path in ("server/portal/style.css", "tools/opendmtq_tools/admin/static/admin.css"):
            for selector, shadow, inset, numbers in self.shadows(path):
                blurred = len(numbers) >= 3 and numbers[0] == 0 and numbers[1] == 0 and numbers[2] > 0
                # A ring's colour as faint as a glow's: a mix of 30 % or less with nothing, or an alpha of .3 or less
                # (a ring drawn apart from a badge, at full strength, is the badge's own edge).
                mix = re.search(r"(\d+)%\s*,\s*transparent\)", shadow)
                alpha = re.search(r"rgba\([^)]*,\s*([\d.]+)\s*\)", shadow)
                faint = (mix is not None and int(mix.group(1)) <= 30) or (alpha is not None and float(alpha.group(1)) <= 0.3)
                haloed = (not inset and faint and len(numbers) >= 4 and numbers[0] == 0 and numbers[1] == 0
                          and numbers[2] == 0 and numbers[3] >= 4)
                if (blurred or haloed) and not any(form in selector for form in self.GLOWS_OF_THE_GAME):
                    glows.append("%s: %s { %s }" % (os.path.basename(path), selector, shadow))
                if inset and len(numbers) >= 2 and numbers[0] >= 2 and numbers[1] == 0 and (len(numbers) < 3 or numbers[2] == 0):
                    stripes.append("%s: %s { %s }" % (os.path.basename(path), selector, shadow))
        self.assertEqual(glows, [], "glows round a state")
        self.assertEqual(stripes, [], "stripes along a box's edge")


class FreshCloneTest(unittest.TestCase):
    """What a new clone runs before anything has made its .env."""

    def test_install_script_starts_without_settings(self):
        if not shutil.which("bash"):
            self.skipTest("no bash")
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "cli"))
            shutil.copy(os.path.join(ROOT, "cli", "install.sh"), os.path.join(d, "cli"))
            r = subprocess.run(["bash", "-c", f'source "{d}/cli/install.sh"; printf %s "$UNIT"'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "/etc/systemd/system/opendmtq.service")

    def test_install_script_names_the_unit_after_this_copy(self):
        if not shutil.which("bash"):
            self.skipTest("no bash")
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "cli"))
            shutil.copy(os.path.join(ROOT, "cli", "install.sh"), os.path.join(d, "cli"))
            with open(os.path.join(d, ".env"), "w") as f:
                f.write("PUBLIC_HOST=192.168.0.10\nCOMPOSE_PROJECT_NAME=opendmtq2\n")
            r = subprocess.run(["bash", "-c", f'source "{d}/cli/install.sh"; printf %s "$UNIT"'], capture_output=True, text=True)
            self.assertEqual(r.stdout, "/etc/systemd/system/opendmtq2.service")


class UninstallTest(unittest.TestCase):
    """install.sh --uninstall only takes away what is this copy's."""

    def uninstall(self, unit_dir, repo_in_unit):
        unit = os.path.join(unit_dir, "opendmtq.service")
        with open(unit, "w") as f:
            f.write(f"[Service]\nWorkingDirectory={repo_in_unit}\n")
        script = f"""source "{ROOT}/cli/install.sh"
            UNIT="{unit}"; LINK="{unit_dir}/link"; SUDO=""
            systemctl() {{ echo "systemctl $*"; }}
            main --uninstall"""
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        return r, os.path.exists(unit)

    def test_another_copys_unit_stays(self):
        with tempfile.TemporaryDirectory() as d:
            r, there = self.uninstall(d, "/somewhere/else")
            self.assertTrue(there)
            self.assertNotIn("systemctl disable", r.stdout)
            self.assertIn("another copy", r.stdout)

    def test_its_own_unit_goes(self):
        with tempfile.TemporaryDirectory() as d:
            r, there = self.uninstall(d, ROOT)
            self.assertFalse(there)
            self.assertIn("systemctl disable", r.stdout)


class FirewallScriptTest(unittest.TestCase):
    def test_it_only_touches_this_servers_rule(self):
        # A second copy on the PC has a rule of its own; a wildcard would cut phones off from it.
        with open(os.path.join(ROOT, "cli", "firewall.ps1"), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("OpenDMTQ (TCP *)", text)
        self.assertIn("$Replaces", text)


class ServiceUnitTest(unittest.TestCase):
    def test_a_path_with_spaces_stays_one_word(self):
        with open(os.path.join(ROOT, "cli", "install.sh"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('ExecStart="$REPO/opendmtq" up', text)
        self.assertIn('ExecStop="$REPO/opendmtq" down', text)


class HostServiceTest(unittest.TestCase):
    """./opendmtq service on a host install: the unit (Linux) and the agent (macOS) keep a path whole, whatever is in it."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "host"))
        from opendmtq_host import commands
        cls.commands = commands

    def test_a_path_with_spaces_and_signs_stays_one_word(self):
        home = "/home/a/My Games 100%/openDMTQ"
        unit = self.commands.systemd_unit("/usr/bin/python3", home + "/host/opendmtq_host", home)
        self.assertIn('ExecStart="/usr/bin/python3" "/home/a/My Games 100%%/openDMTQ/host/opendmtq_host" run --log-to-file',
                      unit)
        self.assertIn("WorkingDirectory=/home/a/My Games 100%%/openDMTQ\n", unit)
        plist = self.commands.launchd_plist("/opt/py", "/Users/a/R&D <1>/openDMTQ/host", "/Users/a/R&D <1>/openDMTQ")
        xml.dom.minidom.parseString(plist)
        self.assertIn("<string>/Users/a/R&amp;D &lt;1&gt;/openDMTQ/host</string>", plist)


class HostBuilderLineTest(unittest.TestCase):
    """The line a host install's window (the Windows bundle's above all) gives the app builder's end at a start, in words:
    on a first start, the wait for the game files rather than an exit status."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "host"))
        from opendmtq_host import server
        cls.server = server

    def setUp(self):
        # A data folder of the test's own, as a first start has it: no game files, no app.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = tmp.name
        os.makedirs(os.path.join(self.data, "apk", "base"))
        os.makedirs(os.path.join(self.data, "apk", "out"))

    def outcome(self, code):
        with mock.patch.object(self.server, "DATA", self.data):
            return self.server.builder_outcome(code)

    def test_a_first_start_waits_for_the_game_files(self):
        # The builder ends with 1 when there is no client to build from (patch_apk.find_base): said as the wait it is.
        self.assertEqual(self.outcome(1), "the phone app waits for the game files: it is built once they are imported")
        self.assertNotIn("status", self.outcome(1))

    def test_the_end_of_a_build_in_words(self):
        self.assertEqual(self.outcome(0), "the phone app is ready")
        # With a client there, a failure is one: the builder's own reason, as build.json keeps it for the admin pages.
        with open(os.path.join(self.data, "apk", "base", "client.apk"), "wb") as f:
            f.write(b"PK")
        self.assertTrue(self.outcome(1).startswith("the phone app could not be built (the details are in "))
        with open(os.path.join(self.data, "apk", "out", "build.json"), "w", encoding="utf-8") as f:
            f.write('{"state": "failed", "error": "apktool.jar failed (exit status 1)"}')
        self.assertTrue(self.outcome(1).startswith("the phone app could not be built: apktool.jar failed (exit status 1) "
                                                   "(the details are in "))


class HostStatusAppLineTest(unittest.TestCase):
    """The status's line for the phone app on a host install: before the game files are in, the wait for them, as the
    window's line at a start says it (builder_outcome); a build that failed with a client there is said as failed."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "host"))
        from opendmtq_host import commands
        cls.commands = commands

    def setUp(self):
        # A data folder of the test's own, as a first start leaves it: no game files, no app, the builder's last end failed.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = tmp.name
        os.makedirs(os.path.join(self.data, "apk", "base"))

    def app_line(self):
        lines = []
        with mock.patch.object(self.commands, "DATA", self.data), \
                mock.patch.object(self.commands, "say", lambda text: lines.append(text)), \
                mock.patch.object(self.commands, "settings", lambda: {"PUBLIC_HOST": "192.168.0.20"}), \
                mock.patch.object(self.commands, "health", lambda values: None), \
                mock.patch.object(self.commands, "app_manifest", lambda: None), \
                mock.patch.object(self.commands, "build_status", lambda: {"state": "failed"}):
            self.commands.cmd_status(None)
        # The line without the left edge every line of the window shares.
        return next(line.strip() for line in lines if line.strip().startswith("Phone app"))

    def test_before_the_game_files_the_app_waits_for_them(self):
        # A first start's builder ends without a client to build from: no failure to show.
        self.assertEqual(self.app_line(), "Phone app    waits for the game files: built once they are imported")

    def test_a_build_that_failed_with_a_client_there_is_said_as_failed(self):
        with open(os.path.join(self.data, "apk", "base", "client.apk"), "wb") as f:
            f.write(b"PK")
        self.assertEqual(self.app_line(), "Phone app    not built yet (failed)")


class HostPlayersLineTest(unittest.TestCase):
    """Where a host install's window says players go (the setup's end, OpenDMTQ.exe apk): the phones, and the PC client
    once the site offers its installer, in the Download page's own words."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "host"))
        from opendmtq_host import commands
        cls.commands = commands

    def setUp(self):
        # A data folder of the test's own: an app, and no installer beside it yet.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = tmp.name
        os.makedirs(os.path.join(self.data, "apk", "out"))

    def said(self):
        lines = []
        with mock.patch.object(self.commands, "DATA", self.data), \
                mock.patch.object(self.commands, "say", lambda text: lines.append(text)), \
                mock.patch.object(self.commands, "tell", lambda text: lines.append(text)), \
                mock.patch.object(self.commands, "tool", lambda *a, **k: 0):
            self.commands.show_address({"PUBLIC_HOST": "192.168.0.20:8080"})
        return "\n".join(lines)

    def test_where_players_go_names_the_pc_client_once_the_site_offers_it(self):
        # No installer beside the app yet: the phones' line alone, as the site has no button for a PC either.
        said = self.said()
        self.assertIn("On a phone on the same Wi-Fi, open http://192.168.0.20:8080/, sign in, and tap Download app (.apk).",
                      said)
        self.assertNotIn("Windows PC", said)
        # The builder put the installer there (windows.json and its file at that size): the PC's line, with the button's
        # own words on the Download page.
        out = os.path.join(self.data, "apk", "out")
        with open(os.path.join(out, "OpenDMTQ-Setup-192.168.0.20-8080.exe"), "wb") as f:
            f.write(b"MZ" * 10)
        with open(os.path.join(out, "windows.json"), "w", encoding="utf-8") as f:
            f.write('{"file": "OpenDMTQ-Setup-192.168.0.20-8080.exe", "size": 20}')
        self.assertIn("On a Windows PC on the same network, open the same address, sign in, and choose Download the "
                      "installer (.exe): it installs the PC client, set up for this server.", self.said())
        # One cut short is not offered by the site, nor said here.
        with open(os.path.join(out, "windows.json"), "w", encoding="utf-8") as f:
            f.write('{"file": "OpenDMTQ-Setup-192.168.0.20-8080.exe", "size": 999}')
        self.assertNotIn("Windows PC", self.said())


class HostPortsTest(unittest.TestCase):
    """A host install's ports (host/opendmtq_host/settings.py): one for the server, the admin service's own elsewhere on
    loopback, never the same (DEP-44)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "host"))
        from opendmtq_host import settings
        cls.settings = settings

    def test_a_new_install_takes_8791(self):
        with mock.patch.object(self.settings, "bindable", lambda port, address="0.0.0.0": True):
            self.assertEqual(self.settings.choose_port(), 8791)
        with mock.patch.object(self.settings, "bindable", lambda port, address="0.0.0.0": port != 8791):
            self.assertEqual(self.settings.choose_port(), 8792)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux's own rule for a closed connection's port")
    def test_a_port_a_stopped_server_answered_on_is_free(self):
        # A server that answered on a port and stopped leaves the connections it closed (TIME_WAIT, about a minute): the
        # port is free for the next start, as Apache and the admin service bind it; a program listening there holds it.
        import socket
        import threading
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", 0))
        server.listen()
        port = server.getsockname()[1]

        def answer():
            # The server closes first, as an HTTP server does after its answer.
            visit, _ = server.accept()
            visit.recv(100)
            visit.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
            visit.close()
        serving = threading.Thread(target=answer)
        serving.start()
        with socket.create_connection(("127.0.0.1", port)) as visitor:
            visitor.sendall(b"GET / HTTP/1.0\r\n\r\n")
            visitor.recv(100)
            serving.join()
        # Still listening: held.
        self.assertFalse(self.settings.bindable(port))
        server.close()
        # Stopped: free, though its closed connection lingers.
        self.assertTrue(self.settings.bindable(port))

    def test_the_admin_service_never_takes_the_servers_port(self):
        # Its own port is chosen at the start and kept in the run folder, never read from .env: an install from before
        # 0.11.0 has ADMIN_PORT=8791 there, where nothing answers any more (its admin pages are on the one port).
        with tempfile.TemporaryDirectory() as run, mock.patch.object(self.settings, "RUN", run):
            old = {"PUBLIC_HOST": "192.168.0.10", "LISTEN_PORT": "80", "ADMIN_PORT": "8791"}
            self.assertEqual(self.settings.admin_port(old), 18791)
            moved = {"PUBLIC_HOST": "192.168.0.10:18791", "LISTEN_PORT": "18791", "ADMIN_PORT": "8791"}
            self.assertNotIn(self.settings.admin_port(moved), (18791, 8791))
            # Taken by another program: the next free one, which every part then reads.
            with mock.patch.object(self.settings, "bindable", lambda port, address="0.0.0.0": port != 18791):
                self.assertEqual(self.settings.choose_admin_port(old), 18792)
            self.assertEqual(self.settings.admin_port(old), 18792)

    def test_an_old_admin_port_leaves_env(self):
        # ADMIN_PORT and ADMIN_BIND of a server set up before 0.11.0 go at its first start; nothing else changes.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("# kept\r\nPUBLIC_HOST=192.168.0.2\r\nLISTEN_PORT=80\r\nADMIN_PASSWORD=x\r\nADMIN_PORT=8791\r\n"
                        "ADMIN_BIND=127.0.0.1\r\n")
            with mock.patch.object(self.settings, "ENV_FILE", path):
                values = self.settings.forget_old_admin_port()
            self.assertEqual(values, {"PUBLIC_HOST": "192.168.0.2", "LISTEN_PORT": "80", "ADMIN_PASSWORD": "x"})
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "# kept\nPUBLIC_HOST=192.168.0.2\nLISTEN_PORT=80\nADMIN_PASSWORD=x\n")

    def test_a_move_to_another_port_and_one_another_program_holds(self):
        # The host program's port command (OpenDMTQ.exe port, ./opendmtq port on a host install): from the next start.
        from opendmtq_host import commands
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("PUBLIC_HOST=192.168.0.10\nLISTEN_PORT=80\nADMIN_PASSWORD=x\n")
            said = []
            with mock.patch.object(commands, "ENV_FILE", path), mock.patch.object(self.settings, "ENV_FILE", path), \
                    mock.patch.object(commands, "say", said.append), mock.patch.object(commands, "tell", said.append), \
                    mock.patch.object(commands, "ok", said.append):
                with mock.patch.object(self.settings, "bindable", lambda port, address="0.0.0.0": False), \
                        self.assertRaises(SystemExit):
                    commands.cmd_port(argparse.Namespace(port=8791))
                with open(path, encoding="utf-8") as f:
                    self.assertIn("LISTEN_PORT=80\n", f.read())
                with mock.patch.object(self.settings, "bindable", lambda port, address="0.0.0.0": True):
                    self.assertEqual(commands.cmd_port(argparse.Namespace(port=8791)), 0)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=x\n")
            self.assertTrue(any("at its next start: http://192.168.0.10:8791/" in line for line in said), said)

    def test_a_server_on_port_80_moves_at_its_start(self):
        # The Windows bundle or a host install set up before 0.11.0 on port 80: its start moves it to the port its admin
        # pages had (8791 here, the first free one after it when taken), says so once, notes the move for the download
        # page and for status and the Server page; `port 80` by its owner stays.
        from opendmtq_host import commands
        for text, busy, want in (("PUBLIC_HOST=192.168.0.10\nADMIN_PASSWORD=x\nADMIN_PORT=8791\n", set(), 8791),
                                 ("PUBLIC_HOST=192.168.0.10\nLISTEN_PORT=80\nADMIN_PASSWORD=x\n", {8791}, 8792)):
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, ".env")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                said = []
                with mock.patch.object(self.settings, "ENV_FILE", path), mock.patch.object(self.settings, "DATA", d), \
                        mock.patch.object(self.settings, "ok", said.append), \
                        mock.patch.object(self.settings, "tell", said.append), \
                        mock.patch.object(self.settings, "bindable", lambda port, address="0.0.0.0": port not in busy):
                    self.assertTrue(self.settings.leave_port_80())
                    values = self.settings.settings()
                    self.assertEqual((values["PUBLIC_HOST"], values["LISTEN_PORT"]), (f"192.168.0.10:{want}", str(want)))
                    self.assertIn(f"The server moved from port 80 to {want}: http://192.168.0.10:{want}/", said)
                    # Once: the next start leaves it where it is.
                    self.assertFalse(self.settings.leave_port_80())
                with open(os.path.join(d, "state", "address.json"), encoding="utf-8") as f:
                    self.assertEqual(json.load(f), {"host": "192.168.0.10"})
                # status says it once.
                lines = []
                with mock.patch.object(commands, "DATA", d), mock.patch.object(commands, "settings", lambda: values), \
                        mock.patch.object(commands, "health", lambda values: None), \
                        mock.patch.object(commands, "say", lines.append), mock.patch.object(commands, "tell", lines.append):
                    commands.cmd_status(argparse.Namespace())
                    commands.cmd_status(argparse.Namespace())
                self.assertEqual(sum(f"moved from port 80 to {want}" in line for line in lines), 1, lines)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=x\n")
            with mock.patch.object(commands, "ENV_FILE", path), mock.patch.object(self.settings, "ENV_FILE", path), \
                    mock.patch.object(self.settings, "DATA", d), mock.patch.object(commands, "ok", lambda m: None), \
                    mock.patch.object(commands, "tell", lambda m: None), \
                    mock.patch.object(self.settings, "bindable", lambda port, address="0.0.0.0": True):
                self.assertEqual(commands.cmd_port(argparse.Namespace(port=80)), 0)
                self.assertFalse(self.settings.leave_port_80())
                self.assertEqual(self.settings.settings()["LISTEN_PORT"], "80")

    def test_an_exposed_host_install_on_port_80_moves_and_the_router_is_told(self):
        # The Windows bundle or a host install exposed before 0.11.0 on port 80: its public port moves with its own and the
        # router is told to forward the new one; one forwarded from another public port keeps that port and the address,
        # the forward going to the new port (DEP-91; main rewrote the public port too and said nothing of the router).
        from opendmtq_host import commands
        for text, address, lines in (
                ("PUBLIC_HOST=game.example.com\nLISTEN_PORT=80\nADMIN_PASSWORD=x\n", "game.example.com:8791",
                 ["The server moved from port 80 to 8791: http://game.example.com:8791/",
                  "On the router(s), forward TCP 8791 to port 8791 of this PC in place of port 80.",
                  "Phones install the app again from that address (the site's download page says so), and PCs connect to it."]),
                ("PUBLIC_HOST=game.example.com:8443\nLISTEN_PORT=80\nADMIN_PASSWORD=x\n", "game.example.com:8443",
                 ["The server moved from port 80 to 8791; its address stays http://game.example.com:8443/",
                  "On the router(s), forward TCP 8443 to port 8791 of this PC in place of port 80."])):
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, ".env")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                said = []
                with mock.patch.object(self.settings, "ENV_FILE", path), mock.patch.object(self.settings, "DATA", d), \
                        mock.patch.object(self.settings, "ok", said.append), \
                        mock.patch.object(self.settings, "tell", said.append), \
                        mock.patch.object(self.settings, "bindable", lambda port, address="0.0.0.0": True):
                    self.assertTrue(self.settings.leave_port_80())
                    values = self.settings.settings()
                    self.assertFalse(self.settings.leave_port_80())
                self.assertEqual((values["PUBLIC_HOST"], values["LISTEN_PORT"]), (address, "8791"))
                self.assertEqual(said, lines)
                # status once, in one paragraph.
                out = []
                with mock.patch.object(commands, "DATA", d), mock.patch.object(commands, "settings", lambda: values), \
                        mock.patch.object(commands, "health", lambda values: None), \
                        mock.patch.object(commands, "say", out.append), mock.patch.object(commands, "tell", out.append):
                    commands.cmd_status(argparse.Namespace())
                self.assertIn(lines[0] + ". " + lines[1], out[-1])

    def test_each_command_reaches_its_own(self):
        # The host program's command line: start is start and port is port (a sub-command's name must not stand in for
        # the whole line's parser).
        from opendmtq_host import cli
        called = []
        with mock.patch.object(cli.os, "geteuid", return_value=1000, create=True), \
                mock.patch.object(cli, "cmd_start", lambda args: called.append(("start", None))), \
                mock.patch.object(cli, "cmd_port", lambda args: called.append(("port", args.port))):
            for line in (["start"], ["port", "8792"], ["port"]):
                cli.main(line)
        self.assertEqual(called, [("start", None), ("port", 8792), ("port", None)])

    def test_the_addresses_named_are_on_the_one_port(self):
        lan = {"PUBLIC_HOST": "192.168.0.10:8791", "LISTEN_PORT": "8791", "ADMIN_PORT": "18791"}
        self.assertEqual(self.settings.site_url(lan), "http://192.168.0.10:8791/")
        self.assertEqual(self.settings.admin_url(lan), "http://192.168.0.10:8791/opendmtq/admin/")
        exposed = {"PUBLIC_HOST": "game.example.com:8790", "LISTEN_PORT": "8790", "ADMIN_PORT": "18791"}
        self.assertEqual(self.settings.admin_url(exposed), "http://localhost:8790/opendmtq/admin/")


@unittest.skipUnless(shutil.which("helm"), "needs helm")
class HelmPortTest(unittest.TestCase):
    """The chart's one port (DEP-47, DEP-70): the router Service listens on the port in publicHost, the one the phones'
    app calls, worked out from the values alone (helm template, an upgrade and a GitOps tool agree): a publicHost that
    names no port, as an install from before 0.11.0 has it, is on 8791, and the app is built for that address and the
    notes name it; router.service.port wins."""

    def rendered(self, *sets):
        chart = os.path.join(ROOT, "deploy", "helm", "opendmtq")
        out = subprocess.run(["helm", "template", "t", chart, "-f", os.path.join(ROOT, "deploy", "kind", "values.yaml"),
                              "--set", "router.service.port=null"] + [a for s in sets for a in ("--set", s)],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def service_port(self, *sets):
        # The router's own Service: named as the release, no part after it.
        for doc in self.rendered(*sets).split("\n---"):
            if "kind: Service" in doc and re.search(r"^  name: t-opendmtq$", doc, re.M):
                return int(re.search(r"^ +port: (\d+)$", doc, re.M).group(1))
        self.fail("no router Service")

    def test_the_service_takes_the_port_phones_call(self):
        self.assertEqual(self.service_port("publicHost=192.168.1.10"), 8791)
        self.assertEqual(self.service_port("publicHost=192.168.1.10:8791"), 8791)
        self.assertEqual(self.service_port("publicHost=game.example.com:8790"), 8790)
        self.assertEqual(self.service_port("publicHost=192.168.1.10:8791", "router.service.port=9000"), 9000)

    def test_port_80_of_values_from_before_0_11_is_no_port_of_its_own(self):
        # A values file from before 0.11.0 names router.service.port 80 (its default) beside a publicHost without a port:
        # the Service moves to 8791 with the app and every URL, not left on 80 while they call 8791 (DEP-90; main put the
        # Service on 80 and the app on 8791). Port 80 named in publicHost stays, and so does another public port.
        self.assertEqual(self.service_port("publicHost=192.168.1.10", "router.service.port=80"), 8791)
        out = self.rendered("publicHost=192.168.1.10", "router.service.port=80", "builder.enabled=true")
        self.assertEqual(set(re.findall(r"name: PUBLIC_HOST, value: \"?([^\"}\s]+)", out)), {"192.168.1.10:8791"})
        self.assertEqual(self.service_port("publicHost=192.168.1.10:80", "router.service.port=80"), 80)
        self.assertEqual(self.service_port("publicHost=192.168.1.10:80"), 80)
        self.assertEqual(self.service_port("publicHost=game.example.com:8443", "router.service.port=80"), 80)
        # The same from a values file as that version's chart wrote its defaults (port: 80 under router.service).
        with tempfile.TemporaryDirectory() as d:
            old = os.path.join(d, "values.yaml")
            with open(old, "w", encoding="utf-8") as f:
                f.write("router:\n  replicas: 2\n  service:\n    type: LoadBalancer\n    port: 80\n    nodePort: null\n")
            chart = os.path.join(ROOT, "deploy", "helm", "opendmtq")
            done = subprocess.run(["helm", "template", "t", chart, "-f", os.path.join(ROOT, "deploy", "kind", "values.yaml"), "-f", old,
                                   "--set", "publicHost=game.example.com"], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('PUBLIC_HOST, value: "game.example.com:8791"', done.stdout)
        self.assertRegex(done.stdout, r"(?m)^ +port: 8791$")
        self.assertNotRegex(done.stdout, r"(?m)^ +port: 80$")

    def test_a_public_host_without_a_port_is_on_8791_everywhere(self):
        # Every container is given the address with its port (the builder makes the app for it), and nothing names 80.
        out = self.rendered("publicHost=192.168.1.10", "builder.enabled=true")
        hosts = re.findall(r"name: PUBLIC_HOST, value: \"?([^\"}\s]+)", out)
        self.assertTrue(hosts, "no PUBLIC_HOST")
        self.assertEqual(set(hosts), {"192.168.1.10:8791"})
        self.assertNotRegex(out, r"192\.168\.1\.10(:80)?[/\"]")


class HostAdminConfTest(unittest.TestCase):
    """The admin pages' part of a host install's Apache settings (host/opendmtq_host/apache.py): the API goes where the pages
    go, and nowhere they do not."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "host"))
        from opendmtq_host import apache
        cls.apache = apache

    def test_on_a_local_network_address_the_pages_and_the_api_are_passed_on(self):
        # The admin service's own port, as the start chose it (an ADMIN_PORT from before 0.11.0 is not read).
        with mock.patch.object(self.apache, "admin_port", lambda values: 18791):
            conf = self.apache.admin_conf({"PUBLIC_HOST": "192.168.0.10", "ADMIN_PORT": "8791"})
        self.assertIn('ProxyPass "/opendmtq/admin" "http://127.0.0.1:18791/opendmtq/admin" timeout=900', conf)
        self.assertIn('ProxyPass "/opendmtq/api" "http://127.0.0.1:18791/opendmtq/api" timeout=900', conf)
        self.assertNotIn("8791/", conf.replace("18791/", ""))
        self.assertNotIn("Require all denied", conf)

    def test_on_an_internet_address_or_kept_off_the_port_the_server_pc_only(self):
        # Still on the one port, for the server PC's own visits (Apache's "local"), and refused to anyone else with the
        # address that works (DEP-44).
        for values in ({"PUBLIC_HOST": "game.example.com:8790", "LISTEN_PORT": "8790"},
                       {"PUBLIC_HOST": "192.168.0.10:8790", "LISTEN_PORT": "8790", "ADMIN_ON_PUBLIC_PORT": "no"}):
            conf = self.apache.admin_conf(dict(values, ADMIN_PORT="18791"))
            self.assertIn('ProxyPass "/opendmtq/admin" "http://127.0.0.1:18791/opendmtq/admin" timeout=900', conf)
            self.assertIn('<LocationMatch "^/(opendmtq/)?admin(/|$)">', conf)
            self.assertIn('<LocationMatch "^/opendmtq/api(/|$)">', conf)
            self.assertEqual(conf.count("Require local"), 2, values)
            # Never a visit a proxy passes on, though it comes from loopback; and no header marks the server PC's own.
            self.assertEqual(conf.count('Require expr "-z %{HTTP:X-Forwarded-For} && -z %{HTTP:Forwarded}'), 2, values)
            self.assertNotIn("X-Server-PC yes", conf)
            self.assertIn("http://localhost:8790/opendmtq/admin/", conf)
            self.assertNotIn("18791/opendmtq/admin/\"", conf)


class VirtualInterfacesTest(unittest.TestCase):
    def test_the_command_line_and_the_admin_pages_skip_the_same_ones(self):
        # Two packages that do not import each other: an interface on one list only gives an address on one screen only.
        lists = []
        for rel in (("cli", "opendmtq_cli", "env.py"), ("tools", "opendmtq_tools", "admin", "setup.py")):
            with open(os.path.join(ROOT, *rel), encoding="utf-8") as f:
                lists.append(re.search(r"^VIRTUAL_INTERFACES = (.*)$", f.read(), re.M).group(1))
        self.assertEqual(lists[0], lists[1])


class ClosedNetworkGuideTest(unittest.TestCase):
    """docs/closed-network.md has to name what the code asks for: a version moved in one place leaves a guide that fails on a
    network where nobody can look anything up."""

    @staticmethod
    def read(*path):
        with open(os.path.join(ROOT, *path), encoding="utf-8") as f:
            return f.read()

    def test_it_names_all_a_server_fetches(self):
        guide = self.read("docs", "closed-network.md")
        install = self.read("host", "install.sh")
        # The system's packages, as host/install.sh asks for them.
        packages = re.search(r"^APT_PACKAGES=\((.*?)^\)", install, re.S | re.M).group(1).split()
        self.assertGreater(len(packages), 10)
        for package in packages:
            self.assertIn(package, guide)
        # The pinned programs for Linux.
        for url in re.findall(r"^(?:APKTOOL|SIGNER|SEVENZIP_LINUX_X64)_URL=(\S+)", install, re.M):
            self.assertIn(url, guide)
        # Under the names the script looks for them by, in the folder carried in.
        for name in ("apktool.jar", "uber-apk-signer.jar", "7zip.tar.xz"):
            self.assertIn(f"/{name}", install)
            self.assertIn(f"`{name}`", guide)
        self.assertIn("host/install.sh --from", guide)
        # The images: the edge proxy's in compose.yaml, the chart's own in its values.
        compose = self.read("compose.yaml")
        self.assertIn(re.search(r"image: (nginxinc/nginx-unprivileged:\S+)", compose).group(1), guide)
        values = self.read("deploy", "helm", "opendmtq", "values.yaml")
        for repository, tag in re.findall(r'repository: (\S+)\n\s+(?:#.*\n\s+)?tag: "([^"]+)"', values):
            self.assertIn(f"{repository}:{tag}", guide)
        # The runtime's and the installer's files, under the names a release gives them, which runtime.py,
        # windows_client.py and host/install.sh look for.
        self.assertIn('RELEASE_NAME = "opendmtq-phone-runtime-{version}-android-arm64-armv7.zip"',
                      self.read("tools", "opendmtq_tools", "runtime.py"))
        self.assertIn("`opendmtq-phone-runtime-1.2.3-android-arm64-armv7.zip`", guide)
        self.assertIn("'opendmtq-phone-runtime-*-android-arm64-armv7.zip'", install)
        self.assertIn('RELEASE_NAME = "opendmtq-pc-client-{version}-windows-x64-setup.exe"',
                      self.read("tools", "opendmtq_tools", "windows_client.py"))
        self.assertIn("`opendmtq-pc-client-1.2.3-windows-x64-setup.exe`", guide)
        self.assertIn("'opendmtq-pc-client-*-windows-x64-setup.exe'", install)


class LicenseTest(unittest.TestCase):
    """The project's license, as the file and the texts that describe it have it."""

    def read(self, path):
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            return f.read()

    def test_the_file_is_the_mit_license(self):
        text = self.read("LICENSE")
        self.assertTrue(text.startswith("MIT License\n"))
        self.assertIn("Copyright (c) 2026 J.-G. Kang (kanggu12)", text)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', text)

    def test_every_place_that_names_it_says_the_same(self):
        # The README's License section, the notice, the third-party list and the runtime's own notices name it alike.
        for path in ("README.md", "docs/notice.md", "docs/THIRD_PARTY_NOTICES.md", "arm32/NOTICES.txt"):
            self.assertIn("MIT License", self.read(path), path)

    def test_the_readme_license_section_keeps_the_owners_sentence(self):
        # The README's License section carries the sentence the site's footers carry, word for word.
        text = self.read("README.md")
        section = text.split("\n## License\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("OpenDMTQ contains no game data. If the copyright holder requests it, this project may be made "
                      "private or shut down", " ".join(section.split()))
        # The third-party parts are listed in the file the README points at, which exists.
        self.assertIn("docs/THIRD_PARTY_NOTICES.md", section)
        self.assertTrue(os.path.exists(os.path.join(ROOT, "docs", "THIRD_PARTY_NOTICES.md")))
        self.assertIn("MIT License", self.read("server/portal/strings.php"))

    def test_the_site_shows_the_same_text(self):
        # The server's image is built from server/ alone, so the page has a copy of its own.
        self.assertEqual(self.read("LICENSE"), self.read("server/portal/LICENSE"))


class ReleaseNotesTest(unittest.TestCase):
    """.github/release_notes.py, which release.yml runs before it builds a release: one version, and notes for it."""

    @classmethod
    def setUpClass(cls):
        # The script lives outside any package (in .github/), so it is loaded from its path.
        import importlib.util
        spec = importlib.util.spec_from_file_location("release_notes", os.path.join(ROOT, ".github", "release_notes.py"))
        cls.notes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.notes)

    def run_notes(self, tag):
        """The script's exit code, what it printed (the notes) and what it complained of, for this tree."""
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        # Captured as release.yml sees them: the notes on stdout go to a file, the problems on stderr to the log.
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.notes.main([tag, "--root", ROOT])
        return code, out.getvalue(), err.getvalue()

    def test_the_chart_in_the_tree_has_its_notes_in_the_changelog(self):
        # Between releases the tree names the last one: tagging it again must pass, so the files never drift apart.
        chart, app = self.notes.chart_versions(self.notes.ROOT)
        self.assertEqual(chart, app)
        code, out, err = self.run_notes("v" + chart)
        self.assertEqual(code, 0, err)
        # The notes are the section's body: its headings, not the version's own heading.
        self.assertIn("### ", out)
        self.assertNotIn(f"## [{chart}]", out)

    def test_another_number_or_no_notes_stops_the_release_before_anything_is_built(self):
        code, out, err = self.run_notes("v9.9.9")
        self.assertEqual(code, 1)
        # Nothing on stdout, so release.yml has no notes to publish by mistake.
        self.assertEqual(out, "")
        # Both problems at once, each with its fix, so one run says all there is to change.
        self.assertIn("set both to 9.9.9", err)
        self.assertIn("CHANGELOG.md has no notes for 9.9.9", err)
        # A tag that is no version at all (a branch name pushed as a tag, say) stops too.
        self.assertEqual(self.run_notes("latest")[0], 1)

    def test_a_section_ends_at_the_next_version_or_the_links(self):
        text = ("## [Unreleased]\n\n## [1.1.0] - 2026-01-02\n\n### Added\n\n- b\n\n"
                "## [1.0.0] - 2026-01-01\n\n- a\n\n[1.1.0]: https://example.com/1.1.0\n")
        # A middle section stops at the next heading; the last one stops before the link list.
        self.assertEqual(self.notes.section(text, "1.1.0"), "### Added\n\n- b")
        self.assertEqual(self.notes.section(text, "1.0.0"), "- a")
        # An empty [Unreleased] has no notes, and a version that is not there has none either.
        self.assertEqual(self.notes.section(text, "Unreleased"), "")
        self.assertIsNone(self.notes.section(text, "0.9.0"))

    def test_the_notes_have_each_paragraph_and_item_on_one_line(self):
        # GitHub shows a release's line breaks as they are: the changelog's wrapping would break its sentences.
        wrapped = ("### Added\n\n- one item\n  goes on here\n  - a nested one\n    with its own end\n- two\n\n"
                   "A paragraph\nin two lines.\n\n```text\nkept\nas it is\n```\n| a | b |\n| 1 | 2 |")
        self.assertEqual(self.notes.unwrap(wrapped),
                         "### Added\n\n- one item goes on here\n  - a nested one with its own end\n- two\n\n"
                         "A paragraph in two lines.\n\n```text\nkept\nas it is\n```\n| a | b |\n| 1 | 2 |")
        # The notes this tree would publish: no line goes on from the one before.
        chart, _ = self.notes.chart_versions(self.notes.ROOT)
        out = self.run_notes("v" + chart)[1]
        self.assertFalse([line for line in out.splitlines() if line.startswith("  ") and not line.lstrip().startswith("- ")])


class HostVersionTest(unittest.TestCase):
    """The version a host install's pages show: a release's number, else a clone's release, and past its tag its commit. Never git
    describe's v1.2.3-4-gabcdef0: the pages put a v before the first part, and showed vv1.2.3."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "host"))
        from opendmtq_host import folders
        cls.folders = folders

    def version(self, app):
        # Without its cache, for a folder of the test's choosing.
        with mock.patch.object(self.folders, "APP", app):
            return self.folders.version.__wrapped__()

    def test_a_release_names_itself_by_its_number(self):
        # The Windows bundle's VERSION file, and the one host/get.sh writes for the release it fetched.
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "VERSION"), "w", encoding="utf-8") as f:
                f.write("0.2.0\n")
            self.assertEqual(self.version(d), "0.2.0")

    def test_a_clone_by_its_release_and_past_it_the_commit(self):
        # A clone that git can read: CI's Python 3.9 container mounts one and has no git, and gives an empty version. The
        # release its chart names, with the commit when it is past that release's tag: the same as Docker shows for it
        # (the command line's code_version()), not a date that a release's own install never shows.
        if not shutil.which("git") or subprocess.run(["git", "-C", ROOT, "rev-parse"], capture_output=True).returncode:
            self.skipTest("not a git checkout")
        from opendmtq_cli import system
        mine = self.version(ROOT)
        # Seven hex digits of the commit, or more when seven would name two objects of the clone (git lengthens it then).
        self.assertRegex(mine, r"^\d+\.\d+\.\d+(-[0-9a-f]{7,})?$")
        self.assertTrue(mine.startswith(system.release_of(ROOT)), mine)
        with mock.patch.object(system, "ROOT", ROOT):
            self.assertEqual(system.code_version(), mine)

    def test_at_a_releases_tag_the_release_alone(self):
        # git as a clone of the release's own commit answers it, and as one past it.
        from opendmtq_cli import system
        head = "d5e201c16a43a7460d26f6081da00e0fa8c59b77"
        for tagged, expected in ((head, "0.9.3"), ("1" * 40, "0.9.3-d5e201c")):
            answers = {("rev-parse", "--short=7", "HEAD"): "d5e201c", ("rev-parse", "HEAD"): head,
                       ("rev-parse", "-q", "--verify", "refs/tags/v0.9.3^{commit}"): tagged}

            def git(cmd, *args, **kwargs):
                # Only git, with -C and a folder before what it is asked.
                return subprocess.CompletedProcess(cmd, 0, answers[tuple(cmd[3:])] + "\n", "")
            with self.subTest(expected), mock.patch.object(system, "release_of", return_value="0.9.3"), \
                    mock.patch.object(system.subprocess, "run", git):
                self.assertEqual(system.code_version(), expected)
            with self.subTest("host " + expected), tempfile.TemporaryDirectory() as d, mock.patch.object(self.folders.subprocess, "run", git):
                os.makedirs(os.path.join(d, "deploy", "helm", "opendmtq"))
                with open(os.path.join(d, "deploy", "helm", "opendmtq", "Chart.yaml"), "w", encoding="utf-8") as f:
                    f.write('apiVersion: v2\nversion: 0.9.3\nappVersion: "0.9.3"\n')
                self.assertEqual(self.version(d), expected)

    def test_a_copy_with_neither_shows_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.version(d), "")

    def test_a_copy_without_git_shows_the_release_it_names(self):
        # A release's source archive, GitHub's Download ZIP, the copy carried to a closed network: no .git, and the pages
        # show the release its chart names, as host/get.sh writes it to a release's VERSION. The same with git missing.
        from opendmtq_cli import system

        def no_checkout(cmd, *args, **kwargs):
            # git as it answers outside a checkout.
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: not a git repository\n")

        def no_git(cmd, *args, **kwargs):
            # No git on the PATH at all.
            raise FileNotFoundError(cmd[0])
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "deploy", "helm", "opendmtq"))
            with open(os.path.join(d, "deploy", "helm", "opendmtq", "Chart.yaml"), "w", encoding="utf-8") as f:
                f.write('apiVersion: v2\nversion: 0.9.6\nappVersion: "0.9.6"\n')
            for answer in (no_checkout, no_git):
                with self.subTest(answer.__name__), mock.patch.object(system, "ROOT", d), \
                        mock.patch.object(system.subprocess, "run", answer):
                    self.assertEqual(system.code_version(), "0.9.6")
                # The host install's own, for the same files.
                with self.subTest("host " + answer.__name__), mock.patch.object(self.folders.subprocess, "run", answer):
                    self.assertEqual(self.version(d), "0.9.6")
            # And what compose passes to the containers, from which the pages read it.
            with mock.patch.object(system, "ROOT", d), mock.patch.object(system, "ENV_FILE", os.path.join(d, ".env")), \
                    mock.patch.object(system.subprocess, "run", no_checkout):
                self.assertEqual(system.compose_env()["OPENDMTQ_VERSION"], "0.9.6")
        # A copy that names no release either: none, as before.
        with tempfile.TemporaryDirectory() as d, mock.patch.object(system, "ROOT", d), \
                mock.patch.object(system.subprocess, "run", no_checkout):
            self.assertEqual(system.code_version(), "")


class LineEndingTest(unittest.TestCase):
    def test_scripts_keep_lf_on_every_checkout(self):
        # Git for Windows checks text out with CRLF unless told otherwise; a CRLF shebang line
        # ("python3\r") stops ./opendmtq, and the server image runs entrypoint.sh as copied.
        if not shutil.which("git") or subprocess.run(["git", "-C", ROOT, "rev-parse"], capture_output=True).returncode:
            self.skipTest("not a git checkout")
        files = ["opendmtq", "cli/install.sh", "host/get.sh", "server/entrypoint.sh", "server/edge/start.sh", "deploy/kind/up.sh", "tests/live/sound/run.sh", "tests/live/sound/card.sh",
                 "tests/ha/failover.sh"]
        out = subprocess.run(["git", "-C", ROOT, "check-attr", "eol", "--", *files],
                             capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            self.assertTrue(line.endswith(": eol: lf"), line)
        out = subprocess.run(["git", "-C", ROOT, "check-attr", "binary", "--", "docs/images/rankings.png"],
                             capture_output=True, text=True, check=True).stdout
        self.assertTrue(out.strip().endswith(": binary: set"), out)


class PythonVersionTest(unittest.TestCase):
    def test_the_command_line_parses_as_python_3_9(self):
        # README and install.sh ask for Python 3.9 or newer; the tests themselves run on whatever the
        # machine has. (Syntax only: newer library calls need a run on 3.9, which CI does.)
        for path in [os.path.join(ROOT, "opendmtq")] + sorted(glob.glob(os.path.join(ROOT, "cli", "opendmtq_cli", "*.py"))):
            with open(path, encoding="utf-8") as f:
                source = f.read()
            try:
                ast.parse(source, filename=path, feature_version=(3, 9))
            except SyntaxError as e:
                self.fail(f"{os.path.relpath(path, ROOT)} needs a Python newer than 3.9: {e}")


def service(compose, name):
    """The lines of one service in compose.yaml (two spaces in, up to the next service)."""
    lines = compose.splitlines()
    start = lines.index(f"  {name}:")
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"  \S", lines[i])), len(lines))
    return "\n".join(lines[start:end])


class OwnPortTest(unittest.TestCase):
    def test_the_admin_pages_are_told_the_servers_own_port(self):
        # The Server page names the server's own port, which the address may not carry (a router's own port in it,
        # forwarded to the server's): Docker Compose gives the admin service the port the edge publishes, and a host
        # install's program the one the server serves (ADM-180; main gave neither, and the page named the address's).
        with open(os.path.join(ROOT, "compose.yaml"), encoding="utf-8") as f:
            compose = f.read()
        published = re.search(r'"\$\{BIND_ADDRESS:-0\.0\.0\.0\}:(\$\{LISTEN_PORT:-\d+\}):8790"', service(compose, "edge")).group(1)
        self.assertIn(f"\n      LISTEN_PORT: {published}\n", service(compose, "admin"))
        sys.path.insert(0, os.path.join(ROOT, "host"))
        from opendmtq_host import folders
        given = folders.tools_env({"PUBLIC_HOST": "game.example.com:8443", "LISTEN_PORT": "8791"}, {})
        self.assertEqual((given["LISTEN_PORT"], given["PUBLIC_HOST"]), ("8791", "game.example.com:8443"))


class ChildOutputTest(unittest.TestCase):
    """What runs on a Windows PC reads other programs' output as UTF-8 (-X utf8), and those programs write in Windows'
    language and code page: strict decoding would stop this program on the first Korean word from tasklist or Java. Only
    a real Windows in another language shows it, so it is checked here."""

    def test_every_text_read_of_a_child_program_can_take_any_byte(self):
        # The app's build reads the signer's output through pack_arm64.run_signer, the import 7-Zip's in importer.py.
        for rel in ("host/opendmtq_host/server.py", "host/opendmtq_host/folders.py", "tools/opendmtq_tools/importer.py",
                    "tools/opendmtq_tools/pack_arm64.py", "tools/opendmtq_tools/admin/jobs.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                text = f.read()
            calls = re.findall(r"subprocess\.(?:run|Popen)\((?:[^()]|\([^()]*\))*\)", text)
            reads = [call for call in calls if "text=True" in call]
            # Every one in the file was seen: a call this pattern cannot follow must not pass unlooked at.
            self.assertEqual(len(reads), text.count("text=True"), rel)
            self.assertTrue(reads, rel)
            for call in reads:
                self.assertIn('errors="replace"', call, f"{rel}: {call}")


class ImporterTest(unittest.TestCase):
    """The import opens the owner's archives with 7-Zip: what its container must not see."""

    def test_the_keys_backups_database_and_downloads_are_hidden(self):
        with open(os.path.join(ROOT, "compose.yaml"), encoding="utf-8") as f:
            block = service(f.read(), "importer")
        # An empty tmpfs over each folder it has no business in; data/apk/base comes back on top.
        for hidden in ("/data/https:", "/data/backups:", "/data/state:", "/data/custom:", "/data/apk:"):
            self.assertIn(f"- {hidden}", block)
        self.assertIn("- ./data/apk/base:/data/apk/base", block)
        # None of the other services' wider views.
        self.assertNotIn("./data/apk:/apk", block)
        self.assertNotIn("./data/custom:/custom", block)
        # No network either: nothing to fetch, nobody to reach.
        self.assertIn("\n    network_mode: none\n", block)

    def test_the_hidden_folders_exist_before_it_runs(self):
        # Docker would make a missing mount point as root, inside data/: ./opendmtq makes them first.
        for folder in ("https", "backups", "state", "custom", "apk", os.path.join("apk", "base")):
            self.assertIn(folder, system.DATA_DIRS)


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class ServiceUserTest(unittest.TestCase):
    """install.sh --service: the user its unit runs ./opendmtq up as (unit_user, with id, stat, sudo
    and docker faked)."""

    def unit_user(self, owner, sudo_user="jin", docker_ok=True, state=True):
        """(exit status, printed user, stderr) for data/state owned by uid owner."""
        with tempfile.TemporaryDirectory() as repo:
            if state:
                os.makedirs(os.path.join(repo, "data", "state"))
            script = f"""
                source "{ROOT}/cli/install.sh"
                REPO="{repo}"
                stat() {{ echo {owner}; }}
                id() {{
                  case "$*" in
                    -un) echo root ;;
                    "-u jin"|"-g jin") echo 1000 ;;
                    "-u root"|"-g root") echo 0 ;;
                    "-nu 1000") echo jin ;;
                    -nu*) return 1 ;;
                    *) command id "$@" ;;
                  esac
                }}
                sudo() {{ shift 2; "$@"; }}
                docker() {{ {"true" if docker_ok else "false"}; }}
                unit_user
            """
            env = {k: v for k, v in os.environ.items() if k != "SUDO_USER"}
            if sudo_user:
                env["SUDO_USER"] = sudo_user
            r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
        return r.returncode, r.stdout.strip(), r.stderr

    def test_data_left_to_www_data_by_a_run_as_root_runs_as_root(self):
        # sudo ./opendmtq setup handed data/ to uid 33; the unit as jin would stop at every boot.
        self.assertEqual(self.unit_user(owner=33)[:2], (0, "root"))

    def test_the_users_own_install_runs_as_the_user(self):
        self.assertEqual(self.unit_user(owner=1000)[:2], (0, "jin"))

    def test_a_user_without_docker_is_refused(self):
        code, _, err = self.unit_user(owner=1000, docker_ok=False)
        self.assertEqual(code, 1)
        self.assertIn("cannot use Docker", err)

    def test_data_of_another_user_is_refused_with_the_fix(self):
        code, _, err = self.unit_user(owner=1001)
        self.assertEqual(code, 1)
        self.assertIn("chown -R 1000:1000", err)

    def test_root_installing_for_a_users_install_runs_as_that_user(self):
        self.assertEqual(self.unit_user(owner=1000, sudo_user=None)[:2], (0, "jin"))

    def test_before_setup_the_installing_user(self):
        self.assertEqual(self.unit_user(owner=0, state=False)[:2], (0, "jin"))


if __name__ == "__main__":
    unittest.main()
