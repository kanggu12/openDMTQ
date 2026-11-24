"""Tests for repository settings that a clone depends on."""

import argparse
import io
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


class GuidesFactsTest(unittest.TestCase):
    def test_the_guides_state_facts_not_advice(self):
        # DEP-134: the README and the guides say what is so, and what a reader must do to go on as the step; no
        # recommendation, warning or advice beside it (the owner's rule, as AdviceTest holds the pages and programs to it).
        # main recommended two cores and 4 GB in three places and Android 8 in a table, warned that passwords would then
        # cross the internet in clear, said to copy the database never by hand and to edit .env by hand only for what no
        # command sets, and passed on what another project's guide recommends. The test cases say what a test saw.
        phrases = (r"(?<!install-)\brecommend", r"\bnever by hand\b", r"\bby hand only\b", r"\bwould then\b",
                   r"\bKnown kind issue\b", r"\bat your own risk\b", r"\bmake sure\b")
        guides = [p for p in glob.glob(os.path.join(ROOT, "docs", "*.md")) if not p.endswith("test-cases.md")]
        self.assertGreater(len(guides), 15)
        for path in [os.path.join(ROOT, "README.md")] + guides:
            with open(path, encoding="utf-8") as f:
                text = " ".join(f.read().split())
            for phrase in phrases:
                self.assertIsNone(re.search(phrase, text, re.I), f"{os.path.relpath(path, ROOT)}: {phrase}")
        # The facts that stood behind them stay: the memory the app's build takes, and the requests two cores answer.
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            self.assertIn("the app's build takes up to 1.6 GB of it for half a minute", " ".join(f.read().split()))
        with open(os.path.join(ROOT, "docs", "install.md"), encoding="utf-8") as f:
            self.assertIn("on two cores it answers hundreds of game requests a second", " ".join(f.read().split()))


class HeadlessSetupTest(unittest.TestCase):
    def test_the_install_guide_says_where_the_files_go_on_a_computer_without_a_screen(self):
        # DEP-135: on a computer without a screen the setup's address opens in another computer's browser, and the setup
        # there looks in the server's own folders only: the Linux steps say so, and how the files get there or are named
        # (main said only that the address is printed, and a first owner found no way to the files).
        with open(os.path.join(ROOT, "docs", "install.md"), encoding="utf-8") as f:
            text = f.read()
        linux = " ".join(text.split("\n## Linux or macOS\n", 1)[1].split("\n## ", 1)[0].split())
        for words in ("which another computer's browser opens", "looks for the game's files in the server's own folders only",
                      "they go onto it first", "`./opendmtq setup --from <folder>` imports them from wherever they are on it"):
            self.assertIn(words, linux)
        # The flag the guide names is the host program's own.
        with open(os.path.join(ROOT, "host", "opendmtq_host", "cli.py"), encoding="utf-8") as f:
            self.assertIn('s.add_argument("--from", dest="from_folder"', f.read())


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
        # Docker's lines clone that release's source by its tag, not the main branch.
        self.assertIn(f"git clone --branch v{version} --depth 1 https://github.com/kanggu12/openDMTQ.git && cd openDMTQ",
                      quick)

    def test_the_docker_way_follows_the_release(self):
        # DEP-131: a clone of the source is of one release, as the downloads are: the install guide clones the chart's
        # release by its tag and updates to a release's tag, and no page tells an owner to pull a branch (main's clone
        # followed the main branch, so a new server ran the commits past the release, and git pull took it further).
        from pathlib import Path
        version = self.versions.chart_version(Path(ROOT))
        with open(os.path.join(ROOT, "docs", "install.md"), encoding="utf-8") as f:
            docker = f.read().split("\n## Docker\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn(f"git clone --branch v{version} --depth 1 https://github.com/kanggu12/openDMTQ.git && cd openDMTQ\n",
                      docker)
        self.assertIn(f"git fetch origin tag v{version} && git checkout -q v{version}\n./opendmtq up\n", docker)
        pages = [os.path.join(ROOT, "README.md"), os.path.join(ROOT, ".github", "SECURITY.md")]
        # The guides an owner follows: the test cases say what main did, in its words.
        pages += [p for p in glob.glob(os.path.join(ROOT, "docs", "*.md")) if not p.endswith("test-cases.md")]
        for path in pages:
            with open(path, encoding="utf-8") as f:
                self.assertNotIn("git pull", f.read(), os.path.relpath(path, ROOT))
        # Another release's clone and update are said with their fix, and --write puts the chart's in their place.
        import tempfile
        old = ("git clone --branch v1.9.0 --depth 1 https://github.com/kanggu12/openDMTQ.git && cd openDMTQ\n"
               "git fetch origin tag v1.9.0 && git checkout -q v1.9.0\n")
        with tempfile.TemporaryDirectory() as d:
            root = self.tree(d, "2.0.0", old)
            self.assertEqual([(p, n, what) for p, n, what, _ in self.versions.stale(root)],
                             [("README.md", 1, "1.9.0"), ("README.md", 2, "1.9.0")])
            self.assertEqual(self.versions.write(root), ["README.md"])
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), old.replace("1.9.0", "2.0.0"))
            self.assertEqual(self.versions.stale(root), [])

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


class PlayersGuideTest(unittest.TestCase):
    """DEP-132: each guide is for its reader. The PC client's guide is the players': how the player draws, sounds, lays
    its pieces out and was measured is the architecture's (main's guide had all of it, 11,372 words); and the move of a
    server off port 80 with 0.11.0 is told once, in the install guide, which the other guides link to."""

    @staticmethod
    def read(*parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            return f.read()

    def test_the_players_guide_leaves_the_internals_to_the_architecture(self):
        guide = " ".join(self.read("docs", "windows-player.md").split())
        architecture = " ".join(self.read("docs", "architecture.md").split())
        # The machine it was measured on, the player's threads and passes, its switches for measuring, and the
        # translator's name: in the architecture, and none of them in the players' guide.
        for words in ("RTX 4090", "Ryzen 9 9950X", "render thread", "UI thread", "framebuffer of the player's own",
                      "EXT_disjoint_timer_query", "ARM32_STATS", "PLAYER_OFFSCREEN", "PLAYER_TRACE_KEYS", "Dynarmic",
                      "v-blank virtualization", "pixel buffer", "stats: glass", "table of methods", "29 to 36 ms"):
            self.assertIn(words, architecture, words)
            if words != "29 to 36 ms":
                self.assertNotIn(words, guide, words)
        # What players read stays theirs: the settings' table the launcher's tests hold it to, and the project's key.
        self.assertIn("| `upscaler` | `fsr1`, `nis`, `bilinear` | Upscaler, below 100 % |", guide)
        self.assertIn("8ead95551a5d5d216dca12de20138465d4cfbcec48ec2b2611c9e49fc47b77d7", guide)
        self.assertIn("[the picture](architecture.md#the-picture)", guide)

    def test_the_move_off_port_80_is_told_in_the_install_guide(self):
        # A paragraph or list item that tells of the move (port 80 and 0.11.0 together) links to the install guide's
        # telling, in every guide but the install guide itself, the chart's own (its values move it), the API's and the
        # tests' references; the Windows bundle's plain text guide does not tell it (its window does).
        skip = ("install.md", "kubernetes.md", "api.md", "testing.md", "test-cases.md")
        found = []
        for path in [os.path.join(ROOT, "README.md")] + sorted(glob.glob(os.path.join(ROOT, "docs", "*.md"))):
            if os.path.basename(path) in skip:
                continue
            with open(path, encoding="utf-8") as f:
                for block in re.split(r"\n\s*\n|\n(?=\s*[-*] |\s*\d+\. )", f.read()):
                    if re.search(r"\bport 80\b", block) and "0.11.0" in block and "install.md#the-servers-port" not in block:
                        found.append(os.path.relpath(path, ROOT) + ": " + " ".join(block.split())[:80])
        self.assertEqual(found, [])
        readme = " ".join(self.read("host", "windows", "README.txt").split())
        self.assertFalse(re.search(r"port 80\b.*0\.11\.0", readme))
        # Where it is told, it is told whole: the port it goes to, phones, a PC client, a router, and port 80 by choice.
        told = " ".join(self.read("docs", "install.md").split("\n## The server's port\n", 1)[1].split("\n## ", 1)[0].split())
        for words in ("before 0.11.0 on port 80 moves off it", "every phone installs it again",
                      "a PC client set up for the old port finds the new one", "the router then forwards the new port",
                      "so does one on port 80 by `port 80`"):
            self.assertIn(words, told)


class OneWordingTest(unittest.TestCase):
    """DEP-133: a fact the guides say in more than one place, said the same: the host program's commands as its own
    command line has them (the lists left out name), and where each setup looks for the game's files (the guides named
    three places, two or four for the same setup)."""

    @staticmethod
    def flat(*parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            return " ".join(f.read().split())

    def test_the_host_programs_commands_are_listed_whole(self):
        with open(os.path.join(ROOT, "host", "opendmtq_host", "cli.py"), encoding="utf-8") as f:
            commands = set(re.findall(r'add_parser\("([a-z-]+)"', f.read()))
        self.assertIn("name", commands)
        # The troubleshooting guide's list of those that are not for Docker Compose only, and the architecture's of the
        # host program's own: each the program's commands, no more and no less.
        lists = {
            "troubleshooting": re.search(r"The commands other than (.*?) \(`expose`", self.flat("docs", "troubleshooting.md")),
            "architecture": re.search(r"Its commands are (.*?); the others", self.flat("docs", "architecture.md")),
        }
        for where, found in lists.items():
            self.assertIsNotNone(found, where)
            self.assertEqual(set(re.findall(r"`([a-z-]+)`", found.group(1))), commands, where)

    def test_each_setup_looks_in_the_same_places_in_every_guide(self):
        # The setup in the browser (the Windows bundle, a host install) and the one in the terminal (Docker), as
        # tools/opendmtq_tools/admin/setup.py home_folders() and cli/opendmtq_cli/discover.py candidate_dirs() look.
        browser = "your home folder, Downloads, the Desktop and Documents (OneDrive's too), one folder down in each"
        terminal = ("the current folder, Downloads and the Desktop (under WSL, every Windows user's too), one folder down "
                    "in each")
        for name in ("install.md", "troubleshooting.md"):
            text = self.flat("docs", name)
            self.assertIn(browser, text, name)
            self.assertIn(terminal, text, name)
        for name in ("admin.md", "songs.md"):
            self.assertIn(browser, self.flat("docs", name), name)
        self.assertIn(browser.split(", one folder")[0], self.flat("host", "windows", "README.txt"))
        # The places the code has, so that a new one is said in the guides too.
        with open(os.path.join(ROOT, "tools", "opendmtq_tools", "admin", "setup.py"), encoding="utf-8") as f:
            self.assertIn('names = ["", "Downloads", "Desktop", "Documents", os.path.join("OneDrive", "Desktop"),', f.read())
        with open(os.path.join(ROOT, "cli", "opendmtq_cli", "discover.py"), encoding="utf-8") as f:
            code = f.read()
        self.assertIn("dirs = [os.getcwd()]", code)
        self.assertIn('glob.glob("/mnt/c/Users/*")', code)
        # The shorter lists the guides had, nowhere (the test cases say what a test sees, in its words).
        guides = [p for p in glob.glob(os.path.join(ROOT, "docs", "*.md")) if not p.endswith("test-cases.md")]
        for path in [os.path.join(ROOT, "README.md")] + guides:
            with open(path, encoding="utf-8") as f:
                text = " ".join(f.read().split())
            for old in ("in Downloads, on the Desktop and in Documents", "in Downloads or on the Desktop by a name",
                        "in Downloads and on the Desktop, and on Windows"):
                self.assertNotIn(old, text, os.path.relpath(path, ROOT))

    def test_the_account_transfer_is_told_in_the_games_own_words(self):
        # DEP-139: the game's OPTION shows the player's TRANSFER CODE, and the arrow beside it opens the transfer code's
        # input on the other device, which takes it with Select and starts the game again as that player (under Wine,
        # GAME-148's run). The phone's and the PC's guides say so (main named two buttons the game has not).
        for page in ("play.md", "windows-player.md"):
            with open(os.path.join(ROOT, "docs", page), encoding="utf-8") as f:
                text = " ".join(f.read().split())
            self.assertIn("**OPTION** shows its **TRANSFER CODE**", text, page)
            self.assertIn("the arrow beside the code opens the transfer code's input, which takes it with **Select**", text, page)
            for gone in ("CONNECT ACCOUNT", "RESTORE DATA"):
                self.assertNotIn(gone, text, page)


class OriginalNamesTest(unittest.TestCase):
    """DEP-130: the README and the guides, their figures among them, name none of the game's own: its original hosts,
    its platform and SDK, its app's package and another edition, its data files, its code, its songs (the owner's rule).
    They say what each is for instead. DEP-137: every other text file of the repository (code, comments, tests, fixtures,
    scripts, other guides) names none of them either, but for the client data's own files and the protocol's own keys,
    which the code must name to serve and read them; a name the code must use is in client_marks.py's table, encoded.
    The words are kept here as digests only, so that this file names none of them."""

    # The first 16 hex digits of the SHA-256 of each word in lower case. NAMES, refused in every file: the original
    # hosts' labels and the platform's, the SDK's name, the original app's package, another edition of the game, and
    # classes, namespaces, methods and fields of the game's code, of its platform's SDK and of its own plugins, the
    # shipped bundle the added songs' tiles are made from (the songs' code reads its name from client_marks), and the
    # client data's bundles and the original server's pictures and their folders that the code looks for or that tests
    # took as examples (the game server reads its pictures' paths from client_names.php).
    NAMES = {
        "d6346b9af21aa4ed", "2afe30a2bd45057c", "80db63946107faba", "368d8e31a31df004", "2ae3f64dcdf74642",
        "699b0abdb612e9e7", "3949fb706769665e", "21e87c9ee4d3d311", "10190bd54cc85dab", "a72c2dc8615e4f9c",
        "3f0a5df004ed8c37", "e35a09609cd77109", "0f46de540331dd14", "30cd4a85fc09f695", "80c8afd70c8ca8d9",
        "66499da637f97267", "ca4ad6efe36dc03c", "e15796bd9e3f785f", "69a2af1bb770167d", "8c5adbbbe569b129",
        "28d9f7f04d91d12f", "bd8481b1ad66b328", "b10e4f1ece4b571e", "9bba163aae0165ab", "ebf31e02252fec8e",
        "139c5e9d74ccd696", "58500ef45cfff001", "5d9781cd523dc098", "a6c25d6a6132ea0a", "032e06177f33d612",
        "a00e8cd128b19c05", "658eddd1c535648d", "994b2b87279cca43", "1c685bc3313b2bac", "32a9fbe79ce90c19",
        "15bb5105e341825c", "cac7bbb7b05a86e1", "5ac8842856b4642c", "599f06e47e6c98fa", "d02ad212e4b923f5",
        "ea7d325704aae6e0", "085758866bafc839", "45f82add335a4e84", "ff9fe74e651359f4", "a059d5a3311523d2",
        "e2021168280ad242", "27cff103a57227e4", "e27e7a215113fff9", "a6faad178c4d3037", "d707471e11bc2920",
        "6c48b84ce1677c6a", "26286318a778dc27", "0ae9bb2b7c69db7a", "97e1000e4c7d506c", "d520944fb3e43fca",
        "e0ab14225016f86a", "aa832ceb753844fa", "a311be37dd5a6251", "847053d2d1ee9ccb", "cd00aac3857131aa",
        "d5a2ed90ad0b6d1f", "a8d2797dad014303", "1b216a676ccd4fd2", "033cd5b89a9c3784", "993ed6cc230cf757",
        "a2837efea8c83966", "558833f8e0152483", "99d92d53c18fa744",
    }
    # DATA, refused in the pages only: the client's table files and a column of one, and the patch manifest's name, the
    # protocol's own names, which the server serves and the tools read by them.
    DATA = {
        "190f7a024f816eba", "33e2bdae3386546f", "0769a2191e4774ff", "dafda178f5d5db6a", "cf6b2f2c19b0716c",
        "03dc667a2453fa27", "fe60034562453c6d", "d24c7811fc74d2c0",
    }
    # The words the pages refuse.
    REFUSED = NAMES | DATA
    # The protocol's own keys among NAMES (a key of the game's reply with a song's addresses): kept where one stands quoted
    # whole, as the code reads and writes it.
    KEYS = {"2afe30a2bd45057c"}
    # A word quoted whole, with either quote.
    QUOTED = re.compile(r"""(['"])([a-z0-9_]+)\1""")
    # A word as the digests were made of it: letters and digits, alone or joined by underscores as a file's or a
    # table's name joins them (each part is looked at too).
    WORD = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")
    # A song by its id in the game's own names for its tiles: a bundle (d3_e and the id) or a sprite (e, the id, _).
    SONG_ID = re.compile(r"\bd3_e\d|\be\d+_[a-z]")

    @staticmethod
    def pages():
        """The README, every guide and every figure of the guides: what the project shows a person."""
        found = [os.path.join(ROOT, "README.md")]
        found += sorted(glob.glob(os.path.join(ROOT, "docs", "*.md")))
        found += sorted(glob.glob(os.path.join(ROOT, "docs", "images", "*.svg")))
        return found

    @staticmethod
    def tree():
        """Every file of the repository but the pages: its tracked files where git can tell them (the repository a clone
        of its own), else every file under it but the folders it ignores (CI's Python 3.9 container has no git, and an
        export may lie in another repository)."""
        pages = set(OriginalNamesTest.pages())
        top = subprocess.run(["git", "-C", ROOT, "rev-parse", "--show-toplevel"], capture_output=True, text=True) if shutil.which("git") else None
        if top is not None and top.returncode == 0 and os.path.realpath(top.stdout.strip()) == os.path.realpath(ROOT):
            out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], capture_output=True, check=True).stdout
            found = [os.path.join(ROOT, rel) for rel in out.decode("utf-8").split("\0") if rel]
        else:
            found = []
            for folder, dirs, files in os.walk(ROOT):
                # The folders .gitignore leaves out at the top (game data, scratch, a host install's own), and git's own.
                dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules")
                           and not (folder == ROOT and d in (".git", "_work", "data", ".host"))]
                found += [os.path.join(folder, name) for name in files]
        return sorted(path for path in found if path not in pages and os.path.isfile(path))

    @classmethod
    def refused(cls, text, tree=False):
        """The numbers of the lines of text that name a refused word: in a page one of REFUSED, or a song by its id; in any
        other file (tree) one of NAMES, but a protocol key quoted whole."""
        import hashlib
        refused = cls.NAMES if tree else cls.REFUSED
        # Each word's digest once: a long file repeats its words.
        digests = {}

        def digest(word):
            if word not in digests:
                digests[word] = hashlib.sha256(word.encode()).hexdigest()[:16]
            return digests[word]

        lines = []
        for number, line in enumerate(text.lower().splitlines(), 1):
            if tree:
                # A protocol key quoted whole is the protocol's own: out of the line before its words are read.
                line = cls.QUOTED.sub(lambda m: "" if digest(m.group(2)) in cls.KEYS else m.group(0), line)
            words = set()
            for found in cls.WORD.findall(line):
                # The whole word and each of its parts: a table's file and a name's label alike.
                words.add(found)
                words.update(found.split("_"))
            if any(digest(w) in refused for w in words) or (not tree and cls.SONG_ID.search(line)):
                lines.append(number)
        return lines

    def test_the_guides_name_none_of_the_games_own(self):
        pages = self.pages()
        self.assertGreater(len(pages), 40)
        found = []
        for path in pages:
            with open(path, encoding="utf-8") as f:
                lines = self.refused(f.read())
            if lines:
                # The page and its lines, never the word: this file says none of them.
                found.append(f"{os.path.relpath(path, ROOT)}: lines {lines}")
        self.assertEqual(found, [], "these name the game's own (a host, the platform, the app's package, a data file, "
                                    "its code or a song's id): say what it is for instead")

    def test_the_check_finds_what_it_is_for(self):
        # Made of parts, so that this file holds none of the words whole: an original host's address, a class and a
        # method of the game's code, a table file of the client data, a tile bundle and a sprite by a song's id. Each is
        # found; the same lines with the words they now use, and the messenger whose name begins as another edition's
        # word, are not.
        made = ["https://" + "dmq" + "glb.mb." + "pm" + "ang.com/DMQ/rpc", "Play" + "SongSlotView." + "Apply" + "DiscInfo",
                "the " + "song_" + "song table", "dlc/" + "d3" + "_e12.unity3d", "e12" + "_somesong",
                "Kak" + "ao edition"]
        self.assertEqual(self.refused("\n".join(made)), [1, 2, 3, 4, 5, 6])
        kept = ["https://<the game's host>/DMQ/rpc", "where the list fills in a song's slot", "the tables of songs",
                "a bundle numbered by its song id", "e<song id>", "Kak" + "aoTalk and LINE", "user.loginV2 and SVC.05008"]
        self.assertEqual(self.refused("\n".join(kept)), [])

    def test_the_rest_of_the_tree_names_none_of_the_games_own(self):
        files = self.tree()
        self.assertGreater(len(files), 500)
        found = []
        for path in files:
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, OSError):
                # A picture, a font or an archive: no words to read.
                continue
            lines = self.refused(text, tree=True)
            if lines:
                # The file and its lines, never the word: this file says none of them.
                found.append(f"{os.path.relpath(path, ROOT)}: lines {lines}")
        self.assertEqual(found, [], "these name the game's own (a host, the platform, the app's package, its code or its "
                                    "SDK's): say what it is for, and keep a name the code must use in client_marks.py")

    def test_the_tree_check_finds_what_it_is_for(self):
        # Made of parts, as above: the SDK's class by its path, the game's input class looked up by name, the key of a
        # song's addresses quoted whole in a reply, the same key read unquoted, a table file the server serves by its
        # name, the shipped bundle the added songs' tiles are made from, and a made-up atlas's bundle past the shipped
        # ones. The first two, the fourth and the sixth are found; the quoted key, the protocol's own, the table file
        # and the made-up bundle are not.
        code = ['jvm::define("com/' + "pm" + "ang" + 'plus/unity3d/Facade");', 'klass("", "DMQ' + 'Input");',
                "return ['" + "pm" + "ang' => $files];", "url." + "pm" + "ang", 'open("song' + '_song.csv")',
                'TILE = "dlc/d3_e' + '33.unity3d"', 'made = "dlc/d3_e900.unity3d"']
        self.assertEqual(self.refused("\n".join(code), tree=True), [1, 2, 4, 6])
        # The same lines in a page: the quoted key, the table file and any atlas's bundle by its number are refused there.
        self.assertEqual(self.refused("\n".join(code)), [1, 2, 3, 4, 5, 6, 7])


class ClientNamesTest(unittest.TestCase):
    """DEP-138: the names the runtime and the player look up in the game's code and define for its SDKs are those of the
    patcher's table of the client's names (tools/opendmtq_tools/client_marks.py), encoded: arm32/src/client_names.h is
    what the table makes, each of its names decodes as client_names::text() decodes it to the table's, and the C++ that
    looks them up holds none of them as it is. The same for the original server's pictures the game server offers
    (server/game/src/client_names.php, read by game.php by their role). A failure says which by its constant or its
    role, never by the name."""

    # The C++ that looks the names up, or defines them for the game's Java calls.
    USERS = ("arm32/desktop/keyplay.cpp", "arm32/desktop/soundmix.cpp", "arm32/desktop/platform_sdk.cpp",
             "arm32/desktop/sdk.cpp", "arm32/src/live.cpp", "arm32/src/tweaks.cpp", "arm32/shim/shim.cpp")

    @staticmethod
    def marks():
        """client_marks.py on its own, by its path (it needs the standard library only; the tools' package around it
        needs what a test machine may not have)."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("client_marks", os.path.join(ROOT, "tools", "opendmtq_tools", "client_marks.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def header():
        with open(os.path.join(ROOT, "arm32", "src", "client_names.h"), encoding="utf-8") as f:
            return f.read()

    def test_the_header_is_the_tables(self):
        self.assertEqual(self.header(), self.marks().cpp_header(),
                         "write it again from tools/: python3 -m opendmtq_tools.client_marks --cpp > ../arm32/src/client_names.h")

    def test_each_name_decodes_to_the_tables(self):
        import hashlib
        # Each constant and its hex digits, a long name's pieces joined as the compiler joins them.
        held = {const: "".join(re.findall(r'"([0-9a-f]*)"', body))
                for const, body in re.findall(r"constexpr const char (k\w+)\[\] =([^;]*);", self.header())}
        names = [(const, name) for const, _, name in self.marks().PLAYER if const]
        self.assertEqual(sorted(held), sorted(const for const, _ in names))
        self.assertGreater(len(names), 60)
        for const, name in names:
            raw = bytes.fromhex(held[const])
            # As client_names::text() reads it: each byte XORed with 0x5c plus its place (mod 256).
            text = bytes(b ^ ((0x5C + i) & 0xFF) for i, b in enumerate(raw)).decode("utf-8")
            # Compared by digest, so that a failure prints no name.
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), hashlib.sha256(name.encode()).hexdigest(), const)

    def test_the_servers_pictures_are_the_tables(self):
        import base64
        import hashlib
        marks = self.marks()
        with open(os.path.join(ROOT, "server", "game", "src", "client_names.php"), encoding="utf-8") as f:
            php = f.read()
        self.assertEqual(php, marks.php_text(),
                         "write it again from tools/: python3 -m opendmtq_tools.client_marks --php > ../server/game/src/client_names.php")
        # The paths as PHP decodes them (base64 of a JSON object, its pieces joined), by digest against the table's.
        pieces = php.split("const ODQ_CLIENT_PATHS", 1)[1].split(";", 1)[0]
        held = json.loads(base64.b64decode("".join(re.findall(r"'([A-Za-z0-9+/=]+)'", pieces))))
        self.assertEqual(sorted(held), sorted(marks.SERVER_PICTURES))
        for role, path in marks.SERVER_PICTURES.items():
            self.assertEqual(hashlib.sha256(held[role].encode()).hexdigest(), hashlib.sha256(path.encode()).hexdigest(), role)
        # The game server reads each by its role and holds none as it is.
        with open(os.path.join(ROOT, "server", "game", "src", "game.php"), encoding="utf-8") as f:
            game = f.read()
        self.assertEqual([role for role, path in marks.SERVER_PICTURES.items() if path in game], [])
        for role in marks.SERVER_PICTURES:
            self.assertIn(f"odq_client_path('{role}')", game)

    def test_the_code_that_looks_them_up_holds_none_as_it_is(self):
        names = [(const, name) for const, _, name in self.marks().PLAYER if const]
        for rel in self.USERS:
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                text = f.read()
            self.assertIn('#include "client_names.h"', text, rel)
            # A name quoted as it is, by its constant.
            self.assertEqual([const for const, name in names if f'"{name}"' in text], [], rel)


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

    def test_a_move_behind_a_router_says_its_forward_and_keeps_a_routers_own_port(self):
        # The host program's port command on an internet address (DEP-113): on the server's own port the address moves with
        # it and the router's new forward is said; a router's own port (8443) stays, with the app phones have, LISTEN_PORT
        # moving alone and the forward of 8443 going on to it (main said nothing of the router and rewrote 8443).
        from opendmtq_host import commands
        for text, address, line, phones in (
                ("PUBLIC_HOST=game.example.com:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=x\n", "game.example.com:9000",
                 "On the router(s), forward TCP 9000 to port 9000 of this PC, in place of the forward of TCP 8791.",
                 "the app is built again for the new address then"),
                ("PUBLIC_HOST=game.example.com:8443\nLISTEN_PORT=8791\nADMIN_PASSWORD=x\n", "game.example.com:8443",
                 "On the router(s), forward TCP 8443 to port 9000 of this PC in place of port 8791.",
                 "phones keep the app they have")):
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, ".env")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                said = []
                with mock.patch.object(commands, "ENV_FILE", path), mock.patch.object(self.settings, "ENV_FILE", path), \
                        mock.patch.object(commands, "say", said.append), mock.patch.object(commands, "tell", said.append), \
                        mock.patch.object(commands, "ok", said.append), \
                        mock.patch.object(self.settings, "bindable", lambda port, address="0.0.0.0": True):
                    self.assertEqual(commands.cmd_port(argparse.Namespace(port=9000)), 0)
                    values = self.settings.settings()
                self.assertEqual((values["PUBLIC_HOST"], values["LISTEN_PORT"]), (address, "9000"))
                self.assertIn(line, said)
                self.assertTrue(any(phones in s for s in said), said)

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
                  "On the router(s), forward TCP 8791 to port 8791 of this PC, in place of the forward of TCP 80.",
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


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("curl") and shutil.which("tar"), "the Linux line")
class GetScriptTest(unittest.TestCase):
    """host/get.sh, the README's Linux line, run by sh on a release whose own install and command are stand-ins: what it
    says on a first run and on an update, and on a system without sudo (DEP-115, DEP-116)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        # The person running it: a user (the line refuses root), as `id` says.
        self.stubs = os.path.join(self.root, "stubs")
        os.makedirs(self.stubs)
        self.stub("id", '#!/bin/sh\ncase "$1" in -u) echo 1000 ;; -un) echo player ;; *) echo "uid=1000(player)" ;; esac\n')
        # And sudo, as a desktop Linux has it, in a folder of its own: the system without it leaves that folder out. The
        # line only looks for it (the stand-in install below asks nothing of it), so a call to it is said and fails;
        # without it the line stops where a machine with no sudo stops (a CI job's container has none).
        self.sudo = os.path.join(self.root, "sudo")
        self.stub("sudo", '#!/bin/sh\necho "sudo was asked: $*" >&2\nexit 1\n', self.sudo)

    def stub(self, name, text, folder=None):
        path = os.path.join(folder or self.stubs, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, 0o755)

    def release(self):
        """A copy of OpenDMTQ as GitHub hands out a release (one folder on top): its install says whether the setup follows
        and marks the install done; its command says what it was asked."""
        top = os.path.join(self.root, "src", "openDMTQ-x")
        self.stub("install.sh", '#!/bin/sh\nmkdir -p .host && touch .host/installed\n'
                  'echo "install: the setup follows: ${OPENDMTQ_SETUP_FOLLOWS:-no}"\n', os.path.join(top, "host"))
        self.stub("opendmtq", '#!/bin/sh\necho "opendmtq $*"\n', top)
        tarball = os.path.join(self.root, "release.tar.gz")
        subprocess.run(["tar", "-C", os.path.join(self.root, "src"), "-czf", tarball, "openDMTQ-x"], check=True)
        return tarball

    def line(self, path=None, tag=None):
        """The line run as a pipe runs it: (its exit code, what it printed)."""
        env = {"HOME": self.root, "PATH": path or f"{self.stubs}:{self.sudo}:{os.environ['PATH']}", "OPENDMTQ_DIR": os.path.join(self.root, "openDMTQ"),
               "OPENDMTQ_TARBALL": "file://" + self.release()}
        if tag:
            env["OPENDMTQ_TARBALL_TAG"] = tag
        with open(os.path.join(ROOT, "host", "get.sh"), "rb") as script:
            done = subprocess.run(["sh"], stdin=script, capture_output=True, text=True, env=env, timeout=120)
        return done.returncode, done.stdout + done.stderr

    def test_it_says_the_release_and_the_update_and_no_next_step_the_setup_takes(self):
        # First run: the release it downloads; install.sh is told the setup follows (it said "Next: ./opendmtq setup" in the
        # middle, then the line ran the setup itself). Again with a newer release: from which to which, once.
        code, said = self.line(tag="v1.0.0")
        self.assertEqual(code, 0, said)
        self.assertIn(f"Downloading OpenDMTQ 1.0.0 into {self.root}/openDMTQ", said)
        self.assertIn("install: the setup follows: yes", said)
        self.assertTrue(said.rstrip().endswith("opendmtq setup"), said)
        code, said = self.line(tag="v1.1.0")
        self.assertEqual(code, 0, said)
        self.assertIn("opendmtq stop", said)
        self.assertIn(f"Updating OpenDMTQ in {self.root}/openDMTQ from 1.0.0 to 1.1.0", said)
        self.assertNotIn("Downloading", said)
        code, said = self.line(tag="v1.1.0")
        self.assertIn(f"Downloading OpenDMTQ 1.1.0 into {self.root}/openDMTQ again", said)

    def test_a_system_without_sudo_is_told_how_to_have_it_before_anything_is_downloaded(self):
        # Debian's minimal install has no sudo: main went on to the packages and ended with "sudo: command not found"
        # (exit 127). Every program of this system but sudo, and the stand-in id.
        bare = os.path.join(self.root, "bare")
        os.makedirs(bare)
        for folder in ("/usr/local/bin", "/usr/bin", "/bin"):
            for name in os.listdir(folder) if os.path.isdir(folder) else []:
                if name != "sudo" and not os.path.lexists(os.path.join(bare, name)):
                    os.symlink(os.path.join(folder, name), os.path.join(bare, name))
        code, said = self.line(path=f"{self.stubs}:{bare}", tag="v1.0.0")
        self.assertEqual(code, 1, said)
        self.assertIn("this system has no sudo, which installs the system's packages for player. As root: apt-get install "
                      "sudo, then usermod -aG sudo player; sign in again as player and run this again", said)
        self.assertNotIn("Downloading", said)
        self.assertFalse(os.path.exists(os.path.join(self.root, "openDMTQ")))


@unittest.skipIf(sys.platform in ("win32", "darwin"), "the Linux start with the computer")
class HostServiceTest(unittest.TestCase):
    """A host install's start with the computer on a Linux without systemd (a container, a system with another init):
    `service` and `uninstall` say so in words and go on, where they ended with a traceback (CLI-94)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "host"))
        from opendmtq_host import commands, remove
        cls.commands, cls.remove = commands, remove

    def test_service_says_there_is_no_systemd_and_writes_nothing(self):
        # main wrote the unit, then died with FileNotFoundError: 'systemctl'.
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch.object(shutil, "which", lambda name: None), \
                mock.patch.object(self.commands.subprocess, "run", side_effect=FileNotFoundError(2, "No such file", "systemctl")):
            with self.assertRaises(SystemExit) as stop, mock.patch("sys.stdout", io.StringIO()) as err:
                self.commands.cmd_service(argparse.Namespace(remove=False))
            self.assertEqual(stop.exception.code, 1)
            self.assertIn("this system has no systemd (no systemctl), which starts the server with the computer here; "
                          "nothing was set up.", err.getvalue())
            self.assertFalse(os.path.exists(os.path.join(home, ".config", "systemd", "user", "opendmtq.service")))

    def test_a_unit_systemd_does_not_take_is_said_and_taken_away(self):
        # systemd there, but no session of this user's: its own words, and no unit left behind saying it starts at boot.
        refused = subprocess.CompletedProcess([], 1, "", "Failed to connect to bus: No medium found\n")
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch.object(shutil, "which", lambda name: "/usr/bin/" + name), \
                mock.patch.object(self.commands.subprocess, "run", return_value=refused):
            with self.assertRaises(SystemExit), mock.patch("sys.stdout", io.StringIO()) as err:
                self.commands.cmd_service(argparse.Namespace(remove=False))
            self.assertIn("systemd did not take the unit (Failed to connect to bus: No medium found); nothing was set up.",
                          err.getvalue())
            self.assertFalse(os.path.exists(os.path.join(home, ".config", "systemd", "user", "opendmtq.service")))

    def test_uninstall_takes_the_unit_away_without_systemd(self):
        # main died at systemctl halfway through the uninstall: the server stopped, its folder and command left.
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch.object(shutil, "which", lambda name: None), \
                mock.patch.object(self.remove.subprocess, "run", side_effect=FileNotFoundError(2, "No such file", "systemctl")), \
                mock.patch.object(self.remove, "in_folder", lambda text: True), mock.patch.object(self.remove, "ok", lambda m: None):
            unit = os.path.join(home, ".config", "systemd", "user", "opendmtq.service")
            os.makedirs(os.path.dirname(unit))
            with open(unit, "w", encoding="utf-8") as f:
                f.write("[Service]\n")
            self.remove.remove_service()
            self.assertFalse(os.path.exists(unit))


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

    @staticmethod
    def server_page_sets(case):
        """The --set words of the Server page's Kubernetes port command (tools/opendmtq_tools/admin/lifecycle.py,
        kube_port_command), for an address on the Service's own port ("own") or one forwarded to it ("forwarded"), with
        a made-up host and port 9000 in place of its placeholders."""
        with open(os.path.join(ROOT, "tools", "opendmtq_tools", "admin", "lifecycle.py"), encoding="utf-8") as f:
            body = re.search(r"\ndef kube_port_command\(.*?\n(?=\n\S)", f.read(), re.S).group(0)
        # The two returns, the forward's first (its words name no publicHost).
        lines = re.findall(r'return f"\{upgrade\}([^"]*)"', body)
        line = lines[0] if case == "forwarded" else lines[1]
        return [s.replace("{host}", "game.example.com").replace("<port>", "9000") for s in re.findall(r"--set (\S+)", line)]

    def test_the_server_pages_port_command_moves_a_release_installed_from_old_values(self):
        # A release installed with a values file of before 0.11.0 (router.service.port: 80, its default then, and a
        # publicHost without a port): the chart has it on 8791 (DEP-90); the Server page's command, which --reuse-values
        # runs with that file's values kept (-f here), moves the Service with the address to the new port, and every
        # container is told both (DEP-110; main's command set publicHost alone and put the Service back on 80).
        with tempfile.TemporaryDirectory() as d:
            old = os.path.join(d, "values.yaml")
            with open(old, "w", encoding="utf-8") as f:
                f.write("router:\n  replicas: 2\n  service:\n    type: LoadBalancer\n    port: 80\n    nodePort: null\n")
            chart = os.path.join(ROOT, "deploy", "helm", "opendmtq")

            def render(sets):
                done = subprocess.run(["helm", "template", "t", chart, "-f", os.path.join(ROOT, "deploy", "kind", "values.yaml"),
                                       "-f", old, "--set", "publicHost=game.example.com"] + [a for s in sets for a in ("--set", s)],
                                      capture_output=True, text=True, timeout=120)
                self.assertEqual(done.returncode, 0, done.stderr)
                service = next(doc for doc in done.stdout.split("\n---") if "kind: Service" in doc
                               and re.search(r"^  name: t-opendmtq$", doc, re.M))
                return (int(re.search(r"^ +port: (\d+)$", service, re.M).group(1)),
                        set(re.findall(r"name: PUBLIC_HOST, value: \"?([^\"}\s]+)", done.stdout)),
                        set(re.findall(r"name: LISTEN_PORT, value: \"?(\d+)", done.stdout)))

            self.assertEqual(render([]), (8791, {"game.example.com:8791"}, {"8791"}))
            sets = self.server_page_sets("own")
            self.assertIn("router.service.port=9000", sets)
            self.assertEqual(render(sets), (9000, {"game.example.com:9000"}, {"9000"}))
            # The forward's: the Service alone, the address and the app as they were.
            forwarded = self.server_page_sets("forwarded")
            self.assertEqual(forwarded, ["router.service.port=9000"])
            self.assertEqual(render(["publicHost=game.example.com:8443"] + forwarded), (9000, {"game.example.com:8443"}, {"9000"}))

    def test_the_server_and_its_admin_pages_are_told_the_services_own_port(self):
        # The Server page's port card names the server's own port, the Service's, also where publicHost names another
        # that a router forwards to it (DEP-111; main gave the pods no LISTEN_PORT, so the card named publicHost's).
        out = self.rendered("publicHost=game.example.com:8443", "router.service.port=8791")
        self.assertEqual(re.findall(r"name: LISTEN_PORT, value: \"?(\d+)", out), ["8791", "8791"])
        self.assertEqual(set(re.findall(r"name: PUBLIC_HOST, value: \"?([^\"}\s]+)", out)), {"game.example.com:8443"})


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


class OwnerIdRuleTest(unittest.TestCase):
    def test_the_command_line_the_admin_pages_and_the_site_take_one_owners_id(self):
        # The owner's ID as the players' site takes it, the same in the three places that say or take it (CLI-95, ADM-228).
        with open(os.path.join(ROOT, "tools", "opendmtq_tools", "owner.py"), encoding="utf-8") as f:
            tools = re.search(r'^OWNER_ID = re\.compile\(r"(.*)"\)$', f.read(), re.M).group(1)
        with open(os.path.join(ROOT, "cli", "opendmtq_cli", "env.py"), encoding="utf-8") as f:
            cli = re.search(r'^OWNER_ID = r"(.*)"$', f.read(), re.M).group(1)
        with open(os.path.join(ROOT, "server", "portal", "auth.php"), encoding="utf-8") as f:
            site = re.search(r"preg_match\('/\^(.*?)\$/', \$lines\[0\]\)", f.read()).group(1)
        self.assertEqual({tools, cli, site}, {"[A-Za-z0-9._-]{1,40}"})


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


class GuestTestRunnersTest(unittest.TestCase):
    """The runtime's guest test programs, run by four runners: a phone's (arm32/test.sh), a desktop Linux host's
    (test_desktop.sh), the Windows layer's under Wine (test_windows.sh) and on Windows itself (test_windows.ps1, CI's
    arm32-windows-real). Windows itself went without the futex and atomics tests for two weeks, so that the layer's waits,
    wakes, requeues and the end of a wait it makes by itself were checked under Wine alone; and on the layer the futex
    test's lostsignal phase skipped itself where that end was gone, and passed."""

    @staticmethod
    def shell_programs(name):
        # The programs of a shell runner's loop ("for test in ...; do"), each as its words: a program and its arguments.
        with open(os.path.join(ROOT, "arm32", name), encoding="utf-8") as f:
            loop = re.search(r"for test in (.*?); do", f.read(), re.S).group(1)
        import shlex
        return [entry.split() for entry in shlex.split(loop.replace("\\\n", " "))]

    @staticmethod
    def powershell_programs():
        # The programs of arm32/test_windows.ps1's list ($tests = @(...)).
        with open(os.path.join(ROOT, "arm32", "test_windows.ps1"), encoding="utf-8") as f:
            text = f.read()
        return re.findall(r"'([^']+)'", re.search(r"\$tests = @\((.*?)\)", text, re.S).group(1)), text

    def test_windows_itself_runs_every_program_the_other_runners_run(self):
        windows, _ = self.powershell_programs()
        for runner in ("test.sh", "test_desktop.sh", "test_windows.sh"):
            programs = [words[0] for words in self.shell_programs(runner)]
            # The same programs as often, in the same order.
            self.assertEqual(windows, programs, runner)

    def test_on_the_windows_layer_the_futex_test_must_run_its_lostsignal_phase(self):
        # Both Windows runners give the futex test the word that the layer ends a wait by itself, and want the phase's
        # ok line: a skip of it fails there.
        futexes = [words for words in self.shell_programs("test_windows.sh") if words[0] == "futexes"]
        self.assertEqual(futexes, [["futexes", "--waits-end-alone"]])
        with open(os.path.join(ROOT, "arm32", "test_windows.sh"), encoding="utf-8") as f:
            self.assertIn('[ "$1" = futexes ] && ! echo "$out" | grep -q "^ok   lostsignal"', f.read())
        _, ps1 = self.powershell_programs()
        self.assertIn("if ($test -eq 'futexes') { $arguments += '--waits-end-alone' }", ps1)
        self.assertIn("if ($test -eq 'futexes') { $ok = $ok -and ($run.Text -match '(?m)^ok\\s+lostsignal') }", ps1)
        # On Linux, where the kernel never ends such a wait by itself, the phase cannot run: no runner there says so.
        for runner in ("test.sh", "test_desktop.sh"):
            self.assertIn(["futexes"], self.shell_programs(runner), runner)


class OverlayFacesTest(unittest.TestCase):
    """The player's overlay draws its words in faces it loads into private font collections. On Windows, Font::GetFamily
    hands back such a collection's own family, and the FontFamily it fills deletes that family when it goes: the next words
    drawn in the face read freed memory and the player ends (an access violation the moment the FPS counter first drew,
    in 0.11.2 before its release). Wine's GDI+ copies the family instead, so only a real Windows shows it: it is checked
    here."""

    def test_the_overlay_never_reads_a_fonts_family_back(self):
        found = []
        for path in sorted(glob.glob(os.path.join(ROOT, "arm32", "desktop", "*.cpp")) + glob.glob(os.path.join(ROOT, "arm32", "desktop", "*.h"))):
            with open(path, encoding="utf-8") as f:
                # Code alone: a comment may name it (glasstest.cpp says why it reads faces back by their pixels).
                code = [line.split("//", 1)[0] for line in f.read().splitlines()]
            found += [f"{os.path.relpath(path, ROOT)}:{n}" for n, line in enumerate(code, 1) if re.search(r"\bGetFamily\(", line)]
        self.assertEqual(found, [], "Font::GetFamily on a private collection's font frees its family on Windows")


class OverlayThreadsTest(unittest.TestCase):
    """A GDI+ object is not to be used from two threads at once: Windows' GDI+ refuses or worse where Wine's lets it pass.
    The overlay sets its words on the painter's thread; its UI thread asks where the frame counter stands (whether the
    sound panel covers it) twice a second, and before 0.11.2's release it measured the counter's words for that with GDI+,
    on the one picture and format the painter measured with. Only a real Windows shows what that does: it is checked
    here."""

    def setUp(self):
        with open(os.path.join(ROOT, "arm32", "desktop", "overlay_win32.cpp"), encoding="utf-8") as f:
            self.code = f.read()

    def body(self, head):
        # A function's body, from its head to the line that closes it, without its comments.
        start = self.code.index(head)
        end = self.code.index("\n}\n", start)
        return "\n".join(line.split("//", 1)[0] for line in self.code[start:end].splitlines())

    def test_the_ui_thread_lays_the_counter_out_without_gdiplus(self):
        body = self.body("bool counter_under_panel() {")
        for call in ("fps_metrics(", "counter_faces(", "measure(", "font(", "wide_font(", "counter_small("):
            self.assertNotIn(call, body)
        self.assertIn("counter_file_faces(", body)

    def test_measuring_keeps_its_gdiplus_objects_per_thread(self):
        for head in ("const StringFormat& tight() {", "RectF measure(const std::wstring& text, const Font& f) {"):
            body = self.body(head)
            self.assertIn("thread_local", body, head)
            self.assertNotRegex(body, r"\bstatic\b", head)

    def test_words_are_set_on_the_painters_thread_alone(self):
        # A measure() or a font() added to any other function the UI thread runs (the hit tests, the counter's and the
        # notice's places, the window procedures) passed every check before and showed only on a real Windows. Now the
        # functions that make fonts and measure and draw words refuse any thread but the one that claimed the words, the
        # painter (overlay_glass.h's claim_words), before touching a GDI+ object: glasstest proves the faces' half under
        # Wine and on Windows; this holds the overlay's half to it.
        for head in ("RectF measure(const std::wstring& text, const Font& f) {", "void say(Graphics& g, const std::wstring& text,",
                     "void say_centred(Graphics& g, const std::wstring& text,"):
            first = [line.strip() for line in self.body(head).splitlines()[1:] if line.strip()][0]
            self.assertTrue(first.startswith("if (!words_here("), f"{head} {first}")
        # The painter claims them before it paints anything, and the probe, which draws on its own thread, before it draws.
        loop = self.body("void painter_loop() {")
        self.assertLess(loop.index("claim_words();"), loop.index("paint_question("))
        for head in ("void test_save(", "void test_motion("):
            self.assertIn("claim_words();", self.body(head)[:400], head)
        # The faces' own functions refuse first too.
        with open(os.path.join(ROOT, "arm32", "desktop", "overlay_glass.cpp"), encoding="utf-8") as f:
            glass = f.read()
        for head in ("std::unique_ptr<Font> font(Weight weight, float px, bool korean) {", "std::unique_ptr<Font> wide_font(float px) {",
                     "float face_ascent(Weight weight, float px, bool korean) {", "float wide_ascent(float px) {"):
            start = glass.index(head)
            body = "\n".join(line.split("//", 1)[0] for line in glass[start:glass.index("\n}\n", start)].splitlines()[1:])
            first = [line.strip() for line in body.splitlines() if line.strip()][0]
            self.assertTrue(first.startswith("if (!words_here("), f"{head} {first}")


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
