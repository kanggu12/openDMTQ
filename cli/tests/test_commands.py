"""Tests for the commands that change the address, the port or the firewall, and for what they print."""

import io
import json
import os
import time
import unittest
from unittest import mock

from opendmtq_cli import app, checks, discover

from .sandbox import Sandbox, done

EXPOSED = "PUBLIC_HOST=myhome.example.com:8790\nLISTEN_PORT=8790\nADMIN_ON_PUBLIC_PORT=no\n"
# wait_builder as written, before the sandbox replaces it.
REAL_WAIT_BUILDER = app.wait_builder


def game_data(sb):
    sb.write("data/content/web/patch/phone_new/1.003.005/android/patch_new.csv.lz4", b"")
    sb.write("data/apk/base/client.apk", b"apk")


class DeployTest(unittest.TestCase):
    """./opendmtq deploy: what stops it, and the order of what it does."""

    # What each outside program answers: a clean tree at a commit, passed gates, nobody playing.
    GOOD_RUNS = "arm32=completed/success\ntest=completed/success\nui=completed/skipped"

    def programs(self, dirty="", runs=GOOD_RUNS, status="success", signed_in=True):
        def run_program(cmd, timeout=60, cwd=None):
            if cmd[0] == "git":
                return done(stdout=dirty if "status" in cmd else "abc1234")
            if not signed_in:
                return done(1, stderr="not signed in")
            if "check-runs" in cmd[2]:
                return done(stdout=runs)
            return done(stdout=status)
        return mock.patch.object(app.system, "run_program", run_program)

    def deploy(self, sb, playing=0, **flags):
        """The command with the server's answers and steps replaced; the steps it took are noted in sb.steps."""
        sb.steps = []
        sb.state = "running"
        options = {"now": False, "no_gates": False, **flags}
        with mock.patch.object(app, "players_now", return_value=playing), \
                mock.patch.object(app.backup, "create", side_effect=lambda why: sb.steps.append(f"backup {why}") or "x/backup.tar.gz"), \
                mock.patch.object(app.system, "build", side_effect=lambda *services, strict=False: sb.steps.append(f"build strict={strict}")), \
                mock.patch.object(app, "cmd_up", side_effect=lambda args: sb.steps.append("up")), \
                mock.patch.object(app.checks, "end_to_end", side_effect=lambda: sb.steps.append("check") or sb.check_failures):
            return sb.call(app.cmd_deploy, **options)

    def test_a_commit_that_passed_goes_live_with_a_backup_first_and_a_check_after(self):
        with Sandbox() as sb, self.programs():
            sb.check_failures = 0
            self.assertEqual(self.deploy(sb), 0, sb.output())
            self.assertEqual(sb.steps, ["build strict=True", "backup deploy", "up", "check"])

    def test_changes_that_are_not_committed_stop_it(self):
        with Sandbox() as sb, self.programs(dirty=" M server/portal/style.css"):
            sb.check_failures = 0
            self.assertEqual(self.deploy(sb), 1)
            self.assertIn("not committed", sb.output())
            self.assertEqual(sb.steps, [])

    def test_ci_that_failed_stops_it(self):
        with Sandbox() as sb, self.programs(runs="test=completed/failure"):
            sb.check_failures = 0
            self.assertEqual(self.deploy(sb), 1)
            self.assertIn("test is completed/failure", sb.output())
            self.assertEqual(sb.steps, [])

    def test_ci_still_running_stops_it(self):
        with Sandbox() as sb, self.programs(runs="ui=in_progress/null"):
            sb.check_failures = 0
            self.assertEqual(self.deploy(sb), 1)
            self.assertIn("ui is in_progress", sb.output())

    def test_a_commit_ci_has_not_seen_stops_it(self):
        with Sandbox() as sb, self.programs(runs=""):
            sb.check_failures = 0
            self.assertEqual(self.deploy(sb), 1)
            self.assertIn("CI has not run", sb.output())

    def test_no_local_gate_stops_it(self):
        with Sandbox() as sb, self.programs(status="null"):
            sb.check_failures = 0
            self.assertEqual(self.deploy(sb), 1)
            self.assertIn("tests/qa.sh", sb.output())

    def test_github_out_of_reach_stops_it_and_says_so(self):
        with Sandbox() as sb, self.programs(signed_in=False):
            sb.check_failures = 0
            self.assertEqual(self.deploy(sb), 1)
            self.assertIn("gh signed in", sb.output())

    def test_no_gates_is_said_out_loud(self):
        with Sandbox() as sb, self.programs(signed_in=False):
            sb.check_failures = 0
            self.assertEqual(self.deploy(sb, no_gates=True), 0, sb.output())
            self.assertIn("not asking", sb.output())

    def test_someone_in_a_song_stops_it_before_anything_is_touched(self):
        with Sandbox() as sb, self.programs():
            sb.check_failures = 0
            self.assertEqual(self.deploy(sb, playing=2), 1)
            self.assertIn("2 player(s) in a song", sb.output())
            self.assertEqual(sb.steps, ["build strict=True"])

    def test_now_goes_ahead_during_a_song(self):
        with Sandbox() as sb, self.programs():
            sb.check_failures = 0
            self.assertEqual(self.deploy(sb, playing=2, now=True), 0, sb.output())
            self.assertEqual(sb.steps, ["build strict=True", "backup deploy", "up", "check"])

    def test_a_failed_check_after_says_the_way_back(self):
        with Sandbox() as sb, self.programs():
            sb.check_failures = 3
            self.assertEqual(self.deploy(sb), 1)
            self.assertIn("The way back", sb.output())


class HostTest(unittest.TestCase):
    def test_refuses_internet_addresses(self):
        # They need expose's protections: download password, admin pages off the internet.
        for address in ("1.1.1.1", "myhome.example.com", "myhome.example.com:8790"):
            with Sandbox() as sb:
                self.assertEqual(sb.call(app.cmd_host, address=address, base=None), 1, address)
                self.assertIn("expose", sb.output())
                self.assertEqual(sb.env()["PUBLIC_HOST"], "192.168.0.10")
                self.assertEqual(sb.tool_calls, [])

    def test_refuses_to_leave_an_exposed_server_half_exposed(self):
        with Sandbox(EXPOSED, detected="192.168.0.20") as sb:
            self.assertEqual(sb.call(app.cmd_host, address="192.168.0.20", base=None), 1)
            self.assertIn("expose --off", sb.output())
            self.assertEqual(sb.env()["PUBLIC_HOST"], "myhome.example.com:8790")

    def test_lan_address_brings_its_port(self):
        with Sandbox("PUBLIC_HOST=192.168.0.10:8080\nLISTEN_PORT=8080\n") as sb:
            self.assertEqual(sb.call(app.cmd_host, address="192.168.0.20", base=None), 0, sb.output())
            self.assertEqual(sb.env()["PUBLIC_HOST"], "192.168.0.20")
            self.assertEqual(sb.env()["LISTEN_PORT"], "80")
        with Sandbox() as sb:
            self.assertEqual(sb.call(app.cmd_host, address="192.168.0.20:8080", base=None), 0, sb.output())
            self.assertEqual(sb.env()["LISTEN_PORT"], "8080")

    def test_same_address_repairs_the_port(self):
        with Sandbox("PUBLIC_HOST=192.168.0.20\nLISTEN_PORT=8790\n", detected="192.168.0.20") as sb:
            self.assertEqual(sb.call(app.cmd_host, address="192.168.0.20", base=None), 0, sb.output())
            self.assertEqual(sb.env()["LISTEN_PORT"], "80")

    def test_a_server_that_does_not_come_back_is_reported(self):
        with Sandbox() as sb:
            sb.state = "running"
            with mock.patch.object(app, "wait_healthy", return_value=None):
                self.assertEqual(sb.call(app.cmd_host, address="192.168.0.20", base=None), 1)
            self.assertIn("logs", sb.output())


class SetupTest(unittest.TestCase):
    def setup(self, sb, **args):
        options = dict(host=None, source=None, rebuild_apk=False, no_firewall=False, songs=None)
        options.update(args)
        with mock.patch.object(app, "cmd_up"), mock.patch.object(checks, "end_to_end", return_value=0) as walk:
            code = sb.call(app.cmd_setup, **options)
        return code, walk

    def test_host_option_refuses_internet_addresses(self):
        with Sandbox(env_text=None) as sb, mock.patch.object(discover, "find", return_value=[]):
            code, _ = self.setup(sb, host="1.1.1.1")
            self.assertEqual(code, 1)
            self.assertIn("expose", sb.output())
            self.assertFalse(os.path.exists(sb.env_file))

    def test_found_files_are_imported_by_name(self):
        # Not the rest of the Downloads folder: other archives, other clients.
        with Sandbox() as sb:
            folder = os.path.dirname(sb.write("Downloads/dmtq-files.rar", b"rar"))
            sb.write("Downloads/game.apk", b"apk")
            sb.tools["importer"] = lambda args, extra: game_data(sb)
            found = [(folder, ["game.apk", "dmtq-files.rar"])]
            with mock.patch.object(discover, "find", return_value=found):
                code, _ = self.setup(sb, no_firewall=True)
            self.assertEqual(code, 0, sb.output())
            module, _, extra = sb.tool_calls[0]
            self.assertEqual(module, "importer")
            self.assertEqual(extra["IMPORT_FROM"], folder)
            self.assertEqual(extra["IMPORT_ONLY"].split("/"), ["game.apk", "dmtq-files.rar"])

    def test_nothing_found_says_the_names_it_takes(self):
        # An archive whose name has none of the game's words (game-files.7z) is passed over: the message says what the
        # search takes, and where more is said, instead of only that nothing was found.
        with Sandbox() as sb, mock.patch.object(discover, "find", return_value=[]):
            code, _ = self.setup(sb, no_firewall=True)
            self.assertEqual(code, 1)
            self.assertIn("names contain dmtq, djmax or technika", sb.output())
            self.assertIn("./opendmtq setup --from <folder>", sb.output())
            self.assertIn('docs/troubleshooting.md, "Setup cannot find the game files"', sb.output())
            # Nothing was imported.
            self.assertEqual(sb.tool_calls, [])

    def test_firewall_trouble_does_not_stop_setup(self):
        # sudo resets PATH, so powershell.exe may not be found; the rest of setup still applies.
        with Sandbox(wsl=True) as sb:
            game_data(sb)
            code, walk = self.setup(sb)
            self.assertEqual(code, 0, sb.output())
            walk.assert_called_once()
            self.assertIn("firewall", sb.output())

    def test_wsl_nat_address_mentions_the_windows_address(self):
        # With Docker Desktop, ports published in NAT mode answer on the Windows address.
        with Sandbox(env_text=None, detected="172.22.80.5", wsl=True) as sb:
            code, _ = self.setup(sb)
            self.assertEqual(code, 1)
            self.assertIn("--host", sb.output())


class ExposeTest(unittest.TestCase):
    def expose(self, sb, name="myhome.example.com", port=8790, **args):
        options = dict(name=name, port=port, off=False, no_firewall=True, admin_public=False)
        options.update(args)
        return sb.call(app.cmd_expose, **options)

    def test_waits_for_the_server_on_the_new_port(self):
        with Sandbox() as sb:
            game_data(sb)
            sb.state = "running"
            self.assertEqual(self.expose(sb, port=18790), 0, sb.output())
            health = [u for u in sb.urls if u.endswith("/opendmtq/health.php")]
            self.assertTrue(health, sb.output())
            self.assertTrue(all(u.startswith("http://127.0.0.1:18790/") for u in health), health)

    def test_unchanged_address_prints_only_what_applies(self):
        with Sandbox(EXPOSED) as sb:
            game_data(sb)
            sb.state = "running"
            sb.built = False
            self.assertEqual(self.expose(sb), 0, sb.output())
            self.assertNotIn("forward TCP", sb.output())
            self.assertNotIn("new app", sb.output())

    def test_new_address_explains_the_router_and_the_phones(self):
        with Sandbox() as sb:
            game_data(sb)
            sb.state = "running"
            sb.built = True
            self.assertEqual(self.expose(sb), 0, sb.output())
            self.assertIn("forward TCP 8790", sb.output())
            self.assertIn("new app", sb.output())

    def test_admin_address_follows_admin_port(self):
        with Sandbox("PUBLIC_HOST=192.168.0.10\nADMIN_PORT=9791\n") as sb:
            self.assertEqual(self.expose(sb), 0, sb.output())
            self.assertIn("localhost:9791/opendmtq/admin/", sb.output())
            self.assertNotIn("8791", sb.output())

    def test_a_server_that_does_not_come_back_is_reported(self):
        with Sandbox() as sb:
            game_data(sb)
            sb.state = "running"
            with mock.patch.object(app, "wait_healthy", return_value=None):
                self.assertEqual(self.expose(sb), 1)

    def test_off_without_an_address_changes_nothing(self):
        # The exposed server keeps running; a .env without an address would leave no command,
        # ./opendmtq down included, able to reach it.
        with Sandbox(EXPOSED, detected=None) as sb:
            sb.state = "running"
            self.assertEqual(self.expose(sb, name=None, off=True, host=None), 1)
            self.assertEqual(sb.env()["PUBLIC_HOST"], "myhome.example.com:8790")
            self.assertEqual(sb.env()["ADMIN_ON_PUBLIC_PORT"], "no")
            self.assertIn("./opendmtq expose --off --host", sb.output())
            self.assertEqual(sb.compose_calls, [])

    def test_off_under_docker_desktop_names_the_way_back(self):
        # WSL in NAT mode: the detected address is WSL's own, which phones cannot reach.
        with Sandbox(EXPOSED, detected="172.28.1.5", wsl=True) as sb:
            self.assertEqual(self.expose(sb, name=None, off=True, host=None), 1)
            self.assertEqual(sb.env()["PUBLIC_HOST"], "myhome.example.com:8790")
            self.assertIn("./opendmtq expose --off --host", sb.output())

    def test_off_goes_back_to_the_local_network(self):
        with Sandbox(EXPOSED, detected="192.168.0.20") as sb:
            self.assertEqual(self.expose(sb, name=None, off=True, host=None), 0, sb.output())
            e = sb.env()
            self.assertEqual((e["PUBLIC_HOST"], e["LISTEN_PORT"], e["ADMIN_ON_PUBLIC_PORT"]), ("192.168.0.20", "80", "yes"))
            # No shared site password any more: the site's accounts are made on the admin pages.
            self.assertNotIn("PORTAL_PASSWORD", e)

    def test_router_forward_under_docker_desktop_names_the_windows_address(self):
        # setup was given the Windows LAN address (--host); WSL itself has a NAT address no router reaches.
        with Sandbox("PUBLIC_HOST=192.168.0.10\n", detected="172.28.1.5", wsl=True) as sb:
            game_data(sb)
            sb.state = "running"
            self.assertEqual(self.expose(sb), 0, sb.output())
            self.assertIn("forward TCP 8790 to this PC (192.168.0.10)", sb.output())
            self.assertNotIn("172.28.1.5", sb.output())


class FirewallTest(unittest.TestCase):
    def test_before_setup_opens_nothing(self):
        # Without an address the rule's scope is unknown; it must not default to "from anywhere".
        with Sandbox(env_text=None, wsl=True) as sb:
            sb.windows_reachable()
            self.assertEqual(sb.call(app.cmd_firewall, remove=False), 1)
            self.assertFalse([s for s in sb.scripts if "Start-Process" in s])
            self.assertIn("setup", sb.output())


class ImportTest(unittest.TestCase):
    def test_a_server_that_does_not_come_back_is_reported(self):
        with Sandbox() as sb:
            sb.state = "running"
            folder = os.path.dirname(sb.write("Downloads/game.apk", b"apk"))
            with mock.patch.object(app, "wait_healthy", return_value=None):
                self.assertEqual(sb.call(app.cmd_import, path=folder), 1)
            self.assertIn("logs", sb.output())

    def test_the_game_data_comes_and_the_songs_only_when_asked(self):
        # The songs are an import of their own: a server starts with the client data alone, and an empty song list.
        with Sandbox() as sb:
            folder = os.path.dirname(sb.write("Downloads/game.apk", b"apk"))
            self.assertEqual(sb.call(app.cmd_import, path=folder), 0, sb.output())
            self.assertEqual((sb.tool_calls[-1][2]["IMPORT_GAME"], sb.tool_calls[-1][2]["IMPORT_SONGS"]), ("yes", "no"))
            self.assertEqual(sb.call(app.cmd_import, path=folder, songs=True), 0, sb.output())
            self.assertEqual((sb.tool_calls[-1][2]["IMPORT_GAME"], sb.tool_calls[-1][2]["IMPORT_SONGS"]), ("yes", "yes"))
            self.assertEqual(sb.call(app.cmd_import, path=folder, songs=True, no_game_data=True), 0, sb.output())
            self.assertEqual((sb.tool_calls[-1][2]["IMPORT_GAME"], sb.tool_calls[-1][2]["IMPORT_SONGS"]), ("no", "yes"))

    def test_the_songs_folder_itself_is_read_with_the_folder_around_it(self):
        # DMQ by itself: the jackets (viewImg) and the song list (_info) are beside it, so its folder is mounted.
        with Sandbox() as sb:
            sb.write("Downloads/server/DMQ/Songs/1/1.fpk", b"m")
            dmq = sb.path("Downloads/server/DMQ")
            self.assertEqual(sb.call(app.cmd_import, path=dmq, songs=True, no_game_data=True), 0, sb.output())
            extra = sb.tool_calls[-1][2]
            self.assertEqual((extra["IMPORT_FROM"], extra["IMPORT_ONLY"]), (os.path.dirname(dmq), "DMQ"))

    def test_an_earlier_tree_in_data_is_read_where_it_is(self):
        # data/server of an earlier OpenDMTQ: linked into data/content on the same disk, not copied through a mount.
        with Sandbox() as sb:
            tree = os.path.dirname(sb.write("data/server/_info/songList.json", "[]"))
            self.assertEqual(sb.call(app.cmd_import, path=os.path.dirname(tree), songs=True), 0, sb.output())
            self.assertEqual(sb.tool_calls[-1][2].get("IMPORT_DATA"), "server")

    def test_runs_where_it_cannot_see_the_keys(self):
        # 7-Zip opens the owner's archives: the compose service "importer" hides data/https, the
        # signing key, the backups and the database from it.
        with Sandbox() as sb:
            folder = os.path.dirname(sb.write("Downloads/game.apk", b"apk"))
            self.assertEqual(sb.call(app.cmd_import, path=folder), 0, sb.output())
            self.assertIn(("importer", "importer"), sb.tool_services)


class AddressChangeTest(unittest.TestCase):
    """Import and restore keep the saved address when this machine now uses another one: the server
    would move there without a new app for the phones. ./opendmtq host moves it and builds the app."""

    def yes_on_a_terminal(self):
        """stdin a terminal, and Enter (yes) to any question; returns the two patches."""
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        return mock.patch("sys.stdin", Terminal()), mock.patch("builtins.input", return_value="")

    def test_import_keeps_the_address(self):
        with Sandbox(detected="192.168.0.23") as sb:
            sb.state = "running"
            folder = os.path.dirname(sb.write("Downloads/game.apk", b"apk"))
            terminal, enter = self.yes_on_a_terminal()
            with terminal, enter as asked:
                self.assertEqual(sb.call(app.cmd_import, path=folder), 0, sb.output())
            asked.assert_not_called()
            self.assertEqual(sb.env()["PUBLIC_HOST"], "192.168.0.10")
            self.assertIn("./opendmtq host 192.168.0.23", sb.output())

    def test_restore_keeps_the_address(self):
        with Sandbox(detected="192.168.0.23") as sb:
            name = sb.archive("data/backups/opendmtq-20260101-120000-manual.tar.gz", {"dmtq.db3": b"db"})
            terminal, enter = self.yes_on_a_terminal()
            with terminal, enter as asked:
                self.assertEqual(sb.call(app.cmd_restore, name=name, with_key=False), 0, sb.output())
            asked.assert_not_called()
            self.assertEqual(sb.env()["PUBLIC_HOST"], "192.168.0.10")


class BuilderOutcomeTest(unittest.TestCase):
    """What up and expose report about the builder: its status file (build.json) from this run, or
    else this run's own output."""

    def wait(self, sb, status=None, exit_code="0", stdout="", stderr="", since=None):
        if status is not None:
            sb.write("data/apk/out/build.json", json.dumps(status))
        sb.programs[("docker", "wait")] = done(0, exit_code + "\n")
        sb.programs[("docker", "logs")] = done(0, stdout, stderr)
        try:
            return REAL_WAIT_BUILDER(since) if since is not None else REAL_WAIT_BUILDER()
        except SystemExit as e:
            return e

    def test_a_failed_build_says_why(self):
        with Sandbox() as sb:
            now = time.time()
            result = self.wait(sb, {"state": "failed", "host": "192.168.0.10", "time": int(now),
                                    "error": "signing failed"}, exit_code="1", since=now)
            self.assertIsInstance(result, SystemExit)
            self.assertIn("the app build failed: signing failed", sb.output())

    def test_a_new_app_is_reported_as_built(self):
        with Sandbox() as sb:
            now = time.time()
            self.assertIs(self.wait(sb, {"state": "done", "host": "192.168.0.10", "time": int(now),
                                         "file": "OpenDMTQ-x.apk"}, since=now), True)
            self.assertIn("app built: data/apk/out/OpenDMTQ-x.apk", sb.output())

    def test_an_earlier_runs_status_is_not_this_ones(self):
        with Sandbox() as sb:
            now = time.time()
            earlier = {"state": "done", "host": "192.168.0.10", "time": int(now) - 3600, "file": "OpenDMTQ-old.apk"}
            self.assertIs(self.wait(sb, earlier, stdout="builder: app for http://192.168.0.10/ is up to date\n",
                                    since=now), False)
            self.assertIn("is up to date", sb.output())
            self.assertNotIn("OpenDMTQ-old.apk", sb.output())

    def test_the_builders_complaints_are_not_its_outcome(self):
        # docker logs prints the builder's stderr after all of its stdout: a complaint there (it could
        # not write build.json) is not the last thing this run did.
        with Sandbox() as sb:
            built = self.wait(sb, stdout="builder: building (patcher updated (1.2.0 -> 1.3.0))\n"
                                         "done     data/apk/out/OpenDMTQ-x.apk\n",
                              stderr="builder: cannot write /apk/out/build.json: [Errno 28] No space left on device\n")
            self.assertIs(built, True)
            self.assertIn("app built: data/apk/out/OpenDMTQ-x.apk", sb.output())
            self.assertNotIn("cannot write", sb.output())


class UpTest(unittest.TestCase):
    def test_a_stopped_edge_is_named(self):
        # The health check goes through the edge proxy; when that one stopped (a certificate it
        # could not use, say), the server's own log shows nothing wrong.
        with Sandbox() as sb:
            game_data(sb)
            sb.edge = "exited"
            with mock.patch.object(app, "wait_healthy", return_value=None):
                self.assertEqual(sb.call(app.cmd_up), 1)
            self.assertIn("logs edge", sb.output())

    def test_a_data_folder_that_cannot_be_made_is_explained(self):
        # data/ made www-data's by an earlier run with sudo, and a folder this version mounts is new.
        with Sandbox() as sb:
            game_data(sb)
            real = os.makedirs

            def refuse(path, *args, **kwargs):
                if path.endswith(os.path.join("data", "https")):
                    raise PermissionError(13, "Permission denied", path)
                return real(path, *args, **kwargs)

            with mock.patch("os.makedirs", refuse):
                self.assertEqual(sb.call(app.cmd_up), 1)
            self.assertIn("chown -R", sb.output())


class ApkTest(unittest.TestCase):
    def test_a_chosen_base_is_kept_for_later_builds(self):
        # With several clients in data/apk/base the builder would otherwise stop on them at the next
        # start, or go back to the one BASE_APK names.
        with Sandbox() as sb:
            sb.write("data/apk/base/a.apk", b"a")
            sb.write("data/apk/base/b.apk", b"b")
            self.assertEqual(sb.call(app.cmd_apk, base="b.apk"), 0, sb.output())
            self.assertEqual(sb.env().get("BASE_APK"), "b.apk")
            module, args, _ = sb.tool_calls[0]
            self.assertEqual((module, args), ("builder", ("--force",)))

    def test_a_misspelt_base_changes_nothing(self):
        with Sandbox() as sb:
            sb.write("data/apk/base/a.apk", b"a")
            self.assertEqual(sb.call(app.cmd_apk, base="b.apk"), 1)
            self.assertNotIn("BASE_APK", sb.env())
            self.assertIn("there: a.apk", sb.output())
            self.assertEqual(sb.tool_calls, [])


class MessageTest(unittest.TestCase):
    def test_builder_up_to_date_line(self):
        with Sandbox() as sb:
            sb.programs[("docker", "wait")] = done(0, "0\n")
            sb.programs[("docker", "logs")] = done(0, "builder: app for http://192.168.0.10/ is up to date\n")
            REAL_WAIT_BUILDER()
            self.assertIn("app for http://192.168.0.10/ is up to date", sb.output())
            self.assertNotIn("app: app", sb.output())

    def test_exposed_apk_message_does_not_say_same_wifi(self):
        with Sandbox(EXPOSED) as sb:
            self.assertEqual(sb.call(app.cmd_apk, base=None), 0, sb.output())
            self.assertNotIn("same Wi-Fi", sb.output())

    def test_up_names_the_admin_port_in_use(self):
        with Sandbox("PUBLIC_HOST=192.168.0.10\nADMIN_ON_PUBLIC_PORT=no\nADMIN_PORT=9791\nADMIN_PASSWORD=x\n") as sb:
            game_data(sb)
            with mock.patch.object(app.time, "sleep"):
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            self.assertIn("http://localhost:9791/opendmtq/admin/", sb.output())
            self.assertIn("http://127.0.0.1:9791/opendmtq/admin/login", sb.urls)

    def test_up_status_and_setup_name_one_admin_address(self):
        # With the pages on the public port too (the default), up named that address and the setup's end another, and
        # status none: all three now name the one on this PC, with where its password is, and nothing else of the pages.
        wanted = "http://localhost:9791/opendmtq/admin/ on this PC  (ID admin, password: ADMIN_PASSWORD in .env)"
        with Sandbox("PUBLIC_HOST=192.168.0.10\nADMIN_PORT=9791\nADMIN_PASSWORD=x\n") as sb:
            game_data(sb)
            with mock.patch.object(app.time, "sleep"):
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            self.assertEqual(sb.call(app.cmd_status), 0, sb.output())
            with mock.patch.object(app, "cmd_up"), mock.patch.object(checks, "end_to_end", return_value=0):
                self.assertEqual(sb.call(app.cmd_setup, host=None, source=None, rebuild_apk=False, no_firewall=True), 0,
                                 sb.output())
            self.assertEqual(sb.output().count(wanted), 3, sb.output())
            self.assertEqual(sb.output().count("/opendmtq/admin/"), 3, sb.output())

    def test_setup_firewall_hint_names_the_port(self):
        with Sandbox("PUBLIC_HOST=192.168.0.10:8080\nLISTEN_PORT=8080\n") as sb:
            game_data(sb)
            with mock.patch.object(app, "cmd_up"), mock.patch.object(checks, "end_to_end", return_value=0):
                self.assertEqual(sb.call(app.cmd_setup, host=None, source=None, rebuild_apk=False,
                                         no_firewall=False), 0, sb.output())
            self.assertIn("TCP 8080", sb.output())
            self.assertNotIn("TCP 80 ", sb.output())

    def test_logs_follow_ends_quietly_on_ctrl_c(self):
        with Sandbox() as sb:
            def interrupted(*args, **kwargs):
                raise KeyboardInterrupt
            with mock.patch.object(app.system, "compose", interrupted):
                try:
                    code = sb.call(app.cmd_logs, follow=True, tail=100, service="server")
                except KeyboardInterrupt:
                    self.fail("Ctrl-C ended in a traceback")
            self.assertEqual(code, 0)




class RuntimeTest(unittest.TestCase):
    """The builder adds the runtime for newer phones and for broadcasts by itself: nobody should have to know it exists. The
    command is for the newest one after an update, and for one made from this source."""

    def test_an_app_without_it_is_said_with_the_reason(self):
        with Sandbox() as sb:
            sb.write("data/apk/out/latest.json", '{"file": "a.apk", "host": "192.168.0.10"}')
            sb.write("data/apk/runtime-error.txt", "could not fetch it: no way out")
            self.assertTrue(checks.app_lacks_runtime())
            self.assertIn("could not fetch it: no way out", checks.no_runtime_notice())
            self.assertIn("docs/closed-network.md", checks.no_runtime_notice())
            sb.write("data/apk/out/latest.json", '{"file": "a.apk", "host": "192.168.0.10", "runtime": "v1"}')
            self.assertFalse(checks.app_lacks_runtime())
        with Sandbox():
            # No app yet: the build's own failure says what there is to say.
            self.assertFalse(checks.app_lacks_runtime())

    def test_setup_has_no_step_for_it(self):
        with Sandbox() as sb, mock.patch.object(app.system, "run_bundle") as bundle:
            game_data(sb)
            with mock.patch.object(app, "cmd_up"), mock.patch.object(checks, "end_to_end", return_value=0), \
                 mock.patch.object(app, "open_firewall"), mock.patch.object(app, "apk_host", return_value=sb.env().get("PUBLIC_HOST")):
                self.assertEqual(sb.call(app.cmd_setup, source=None, host=None, rebuild_apk=False, no_firewall=True), 0, sb.output())
            bundle.assert_not_called()
            self.assertNotIn("Runtime", sb.output())
            self.assertIn("5/5", sb.output())

    def test_the_command_takes_the_newest_one_and_then_builds_the_app(self):
        done = mock.Mock(returncode=0)
        with Sandbox() as sb, mock.patch.object(app.system, "tool", return_value=done) as tool, \
                mock.patch.object(app.system, "run_bundle") as bundle, mock.patch.object(app, "cmd_apk") as apk:
            self.assertEqual(sb.call(app.cmd_runtime, build=False), 0, sb.output())
            tool.assert_called_once_with("runtime", "--refresh")
            bundle.assert_not_called()
            apk.assert_called_once()

    def test_when_it_cannot_be_had_the_app_stays_as_it_is(self):
        with Sandbox() as sb, mock.patch.object(app.system, "tool", return_value=mock.Mock(returncode=1)), \
                mock.patch.object(app, "cmd_apk") as apk:
            self.assertEqual(sb.call(app.cmd_runtime, build=False), 1, sb.output())
            apk.assert_not_called()
            self.assertIn("--build", sb.output())

    def test_a_release_image_would_replace_one_made_from_source_so_it_says_so_first(self):
        with Sandbox("PUBLIC_HOST=192.168.0.10\nOPENDMTQ_TOOLS_IMAGE=ghcr.io/x/tools:1\n") as sb, \
                mock.patch.object(app.system, "run_bundle") as bundle, mock.patch.object(app, "cmd_apk") as apk:
            self.assertEqual(sb.call(app.cmd_runtime, build=True), 1, sb.output())
            bundle.assert_not_called()
            apk.assert_not_called()
            self.assertIn("OPENDMTQ_TOOLS_IMAGE", sb.output())

    def test_it_can_be_made_from_this_source(self):
        with Sandbox() as sb, mock.patch.object(app.system, "run_bundle", return_value=0) as bundle, \
                mock.patch.object(app.system, "tool") as tool, mock.patch.object(app, "cmd_apk") as apk:
            self.assertEqual(sb.call(app.cmd_runtime, build=True), 0, sb.output())
            bundle.assert_called_once()
            tool.assert_not_called()
            apk.assert_called_once()
        with Sandbox() as sb, mock.patch.object(app.system, "run_bundle", return_value=1), mock.patch.object(app, "cmd_apk") as apk:
            self.assertEqual(sb.call(app.cmd_runtime, build=True), 1, sb.output())
            apk.assert_not_called()


if __name__ == "__main__":
    unittest.main()
