"""Tests for repository settings that a clone depends on."""

import ast
import glob
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


class HostAdminConfTest(unittest.TestCase):
    """The admin pages' part of a host install's Apache settings (host/opendmtq_host/apache.py): the API goes where the pages
    go, and nowhere they do not."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "host"))
        from opendmtq_host import apache
        cls.apache = apache

    def test_on_a_local_network_address_the_pages_and_the_api_are_passed_on(self):
        conf = self.apache.admin_conf({"PUBLIC_HOST": "192.168.0.10", "ADMIN_PORT": "8791"})
        self.assertIn('ProxyPass "/opendmtq/admin" "http://127.0.0.1:8791/opendmtq/admin" timeout=900', conf)
        self.assertIn('ProxyPass "/opendmtq/api" "http://127.0.0.1:8791/opendmtq/api" timeout=900', conf)
        self.assertNotIn("Require all denied", conf)

    def test_on_an_internet_address_or_kept_off_the_port_both_are_refused(self):
        for values in ({"PUBLIC_HOST": "game.example.com:8790"}, {"PUBLIC_HOST": "192.168.0.10", "ADMIN_ON_PUBLIC_PORT": "no"}):
            conf = self.apache.admin_conf(dict(values, ADMIN_PORT="8791"))
            self.assertNotIn("ProxyPass", conf, values)
            self.assertIn('<LocationMatch "^/(opendmtq/)?admin(/|$)">', conf)
            self.assertIn('<LocationMatch "^/opendmtq/api(/|$)">', conf)
            self.assertEqual(conf.count("Require all denied"), 2, values)


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
        # The runtime's file, under the name runtime.py looks for.
        self.assertIn('ZIP_NAME = "opendmtq-arm32-runtime.zip"', self.read("tools", "opendmtq_tools", "runtime.py"))
        self.assertIn("opendmtq-arm32-runtime.zip", guide)


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
        for path in ("README.md", "docs/notice.md", "arm32/NOTICES.txt"):
            self.assertIn("MIT License", self.read(path), path)
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
    """The version a host install's pages show: a release's number, else the date and commit of a clone. Never git
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

    def test_a_clone_by_the_date_and_commit_of_its_code(self):
        # A clone that git can read: CI's Python 3.9 container mounts one and has no git, and gives an empty version.
        if not shutil.which("git") or subprocess.run(["git", "-C", ROOT, "rev-parse"], capture_output=True).returncode:
            self.skipTest("not a git checkout")
        self.assertRegex(self.version(ROOT), r"^\d{4}\.\d\d\.\d\d-[0-9a-f]{7,}$")

    def test_a_copy_with_neither_shows_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.version(d), "")


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
