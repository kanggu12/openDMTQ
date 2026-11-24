"""Tests for the commands that change the address, the port or the firewall, and for what they print."""

import io
import json
import os
import re
import subprocess
import sys
import time
import unittest
from unittest import mock

from opendmtq_cli import app, checks, discover, env, system

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
        # An address without a port keeps the server's port: port 80 only when named, and then the owner's own choice.
        with Sandbox("PUBLIC_HOST=192.168.0.10:8080\nLISTEN_PORT=8080\n") as sb:
            self.assertEqual(sb.call(app.cmd_host, address="192.168.0.20", base=None), 0, sb.output())
            self.assertEqual(sb.env()["PUBLIC_HOST"], "192.168.0.20:8080")
            self.assertEqual(sb.env()["LISTEN_PORT"], "8080")
        with Sandbox() as sb:
            self.assertEqual(sb.call(app.cmd_host, address="192.168.0.20:8080", base=None), 0, sb.output())
            self.assertEqual(sb.env()["LISTEN_PORT"], "8080")
        with Sandbox("PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\n") as sb:
            self.assertEqual(sb.call(app.cmd_host, address="192.168.0.20:80", base=None), 0, sb.output())
            self.assertEqual((sb.env()["PUBLIC_HOST"], sb.env()["LISTEN_PORT"], sb.env()["PORT_80"]),
                             ("192.168.0.20", "80", "chosen"))

    def test_same_address_repairs_the_port(self):
        # The address takes the port the server listens on.
        with Sandbox("PUBLIC_HOST=192.168.0.20\nLISTEN_PORT=8790\n", detected="192.168.0.20") as sb:
            self.assertEqual(sb.call(app.cmd_host, address="192.168.0.20", base=None), 0, sb.output())
            self.assertEqual((sb.env()["PUBLIC_HOST"], sb.env()["LISTEN_PORT"]), ("192.168.0.20:8790", "8790"))

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

    def test_the_end_says_what_happens_and_the_certificate_only_on_the_internet(self):
        # What happens, not what to keep from doing: an update over the app keeps the device's account. The browser's
        # word about the server's own certificate only where the site is on HTTPS, a server set up for the internet.
        for text, internet in (("PUBLIC_HOST=192.168.0.10\n", False), (EXPOSED, True)):
            with self.subTest(internet=internet), Sandbox(text) as sb:
                game_data(sb)
                code, _ = self.setup(sb, no_firewall=True)
                self.assertEqual(code, 0, sb.output())
                self.assertIn("Later updates install over this one, which keeps the device's account.", sb.output())
                self.assertNotIn("uninstall", sb.output())
                self.assertNotIn("go on past", sb.output())
                self.assertEqual("own certificate, which browsers warn about once" in sb.output(), internet, sb.output())

    def test_no_firewall_asks_windows_nothing(self):
        # Not even whether the rule is there: PowerShell is not started at all.
        with Sandbox(wsl=True) as sb:
            sb.windows_reachable()
            game_data(sb)
            code, _ = self.setup(sb, no_firewall=True)
            self.assertEqual(code, 0, sb.output())
            self.assertEqual(sb.scripts, [])
            self.assertIn("skipped the firewall", sb.output())

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

    def test_admin_pages_stay_on_the_one_port_on_this_pc(self):
        # Exposed without --admin-public: on the server's one port, as localhost on this PC; no port of their own (DEP-42).
        with Sandbox("PUBLIC_HOST=192.168.0.10\nADMIN_PORT=9791\n") as sb:
            self.assertEqual(self.expose(sb), 0, sb.output())
            self.assertIn("http://localhost:8790/opendmtq/admin/", sb.output())
            self.assertNotIn("9791", sb.output())
            self.assertNotIn("8791", sb.output())

    def test_on_docker_desktop_they_are_said_to_be_off(self):
        with Sandbox("PUBLIC_HOST=192.168.0.10\n") as sb:
            sb.docker_desktop = True
            self.assertEqual(self.expose(sb), 0, sb.output())
            self.assertIn("admin pages: off (Docker Desktop cannot tell", sb.output())
            self.assertNotIn("localhost", sb.output())

    def test_on_rootless_docker_too_and_the_server_takes_no_visit_as_its_own(self):
        # Rootless Docker's port driver hands the server every visit from one address, as Docker Desktop does: the admin
        # pages are off without --admin-public, said at expose and in up's addresses, and the server is told to take no
        # visit as the server PC's (ADMIN_LOCAL=none).
        with Sandbox("PUBLIC_HOST=192.168.0.10\nADMIN_PASSWORD=x\n") as sb:
            sb.rootless = True
            game_data(sb)
            self.assertEqual(self.expose(sb), 0, sb.output())
            self.assertIn("admin pages: off (rootless Docker cannot tell this PC's visits from the internet's; "
                          "./opendmtq expose myhome.example.com --admin-public puts them on the public port over HTTPS)",
                          sb.output())
            before = len(sb.output())
            with mock.patch.object(app.time, "sleep"):
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            self.assertIn("Admin pages    off (rootless Docker", sb.output()[before:])
            self.assertNotIn("localhost", sb.output())
        with mock.patch.object(app.system, "_docker_info", lambda: "Ubuntu 24.04|[\"name=seccomp\",\"name=rootless\"]"):
            self.assertEqual(app.system.cannot_tell(), "rootless Docker")
            self.assertEqual(app.system.compose_env()["ADMIN_LOCAL"], "none")
        with mock.patch.object(app.system, "_docker_info", lambda: "Docker Desktop|[\"name=seccomp\"]"):
            self.assertEqual(app.system.compose_env()["ADMIN_LOCAL"], "none")
        with mock.patch.object(app.system, "_docker_info", lambda: "Ubuntu 24.04|[\"name=seccomp\"]"):
            self.assertIsNone(app.system.cannot_tell())
            self.assertEqual(app.system.compose_env()["ADMIN_LOCAL"], "gateway")

    def test_on_docker_engine_a_proxys_visit_is_said_to_be_one_from_elsewhere(self):
        with Sandbox("PUBLIC_HOST=192.168.0.10\n") as sb:
            self.assertEqual(self.expose(sb), 0, sb.output())
            self.assertIn("http://localhost:8790/opendmtq/admin/ on this PC (a visit through a proxy is one from "
                          "elsewhere: --admin-public puts them on the public port over HTTPS)", sb.output())

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
            self.assertEqual((e["PUBLIC_HOST"], e["LISTEN_PORT"], e["ADMIN_ON_PUBLIC_PORT"]), ("192.168.0.20:8791", "8791", "yes"))
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


class PortCommandTest(unittest.TestCase):
    """./opendmtq port: the server's one port shown, or moved from its next start (LISTEN_PORT and the port in
    PUBLIC_HOST), with what then happens to the phones said; a port another program holds refused in words (API-43)."""

    SET_UP = "PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=x\n"

    def test_shown(self):
        with Sandbox(self.SET_UP) as sb:
            self.assertEqual(sb.call(app.cmd_port, port=None), 0)
            self.assertIn("port 8791", sb.output())

    def test_moved_from_the_next_start(self):
        with Sandbox(self.SET_UP) as sb:
            self.assertEqual(sb.call(app.cmd_port, port=8792), 0, sb.output())
            e = sb.env()
            self.assertEqual((e["PUBLIC_HOST"], e["LISTEN_PORT"]), ("192.168.0.10:8792", "8792"))
            self.assertIn("at its next start: http://192.168.0.10:8792/", sb.output())
            self.assertIn("Players install the new app over the old one", sb.output())
            # Nothing restarted or built now: the next start does it.
            self.assertEqual(sb.compose_calls, [])

    def test_a_port_another_program_holds_is_refused(self):
        with Sandbox(self.SET_UP) as sb:
            sb.busy_ports = {8792}
            self.assertEqual(sb.call(app.cmd_port, port=8792), 1)
            self.assertIn("port 8792 is taken on this computer by another program", sb.output())
            self.assertEqual(sb.env()["LISTEN_PORT"], "8791")

    def test_behind_a_router_its_forward_is_said_and_a_routers_own_port_stays(self):
        # An internet address on the server's own port moves with it, and the router is told to forward the new one; one
        # that names a router's own port (8443, forwarded to 8791) stays with the app phones have, LISTEN_PORT moving
        # alone and the forward of 8443 going to the new port (DEP-113; main rewrote the router's port into the address).
        for env_text, address, said, phones in (
                ("PUBLIC_HOST=game.example.com:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=x\n", "game.example.com:9000",
                 "On the router(s), forward TCP 9000 to port 9000 of this PC, in place of the forward of TCP 8791.",
                 "Players install the new app over the old one"),
                ("PUBLIC_HOST=game.example.com:8443\nLISTEN_PORT=8791\nADMIN_PASSWORD=x\n", "game.example.com:8443",
                 "On the router(s), forward TCP 8443 to port 9000 of this PC in place of port 8791.",
                 "phones keep the app they have")):
            with Sandbox(env_text) as sb:
                self.assertEqual(sb.call(app.cmd_port, port=9000), 0, sb.output())
                self.assertEqual((sb.env()["PUBLIC_HOST"], sb.env()["LISTEN_PORT"]), (address, "9000"))
                self.assertEqual(sb.output().count(said), 1, sb.output())
                self.assertIn(phones, sb.output())
                if address.endswith(":8443"):
                    self.assertIn("at its next start; its address stays http://game.example.com:8443/", sb.output())
                    self.assertNotIn("builds the app", sb.output())

    def test_the_one_it_is_on_and_no_port(self):
        with Sandbox(self.SET_UP) as sb:
            self.assertEqual(sb.call(app.cmd_port, port=8791), 0)
            self.assertIn("on port 8791 already", sb.output())
            self.assertEqual(sb.call(app.cmd_port, port=70000), 1)
            self.assertEqual(sb.env()["LISTEN_PORT"], "8791")


class PasswordCommandTest(unittest.TestCase):
    """./opendmtq password: the owner's password (ADMIN_PASSWORD in .env) typed twice on a terminal, or one made; the
    running admin service started again with it, as it reads it at its start; one Docker Compose would read otherwise
    refused (SRV-57)."""

    SET_UP = "PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=old-password-1\n"

    def test_one_made_without_a_terminal(self):
        with Sandbox(self.SET_UP) as sb:
            self.assertEqual(sb.call(app.cmd_password), 0, sb.output())
            made = sb.env()["ADMIN_PASSWORD"]
            # Sixteen of setup's own letters, said once, and nothing else of .env changed.
            self.assertRegex(made, r"^[A-Za-z0-9_-]{16}$")
            self.assertIn(f"The new password: {made}", sb.output())
            self.assertEqual(sb.env()["LISTEN_PORT"], "8791")
            # Not running: from the next start, nothing started now.
            self.assertIn("from the server's next start", sb.output())
            self.assertEqual(sb.compose_calls, [])

    def test_the_running_admin_service_takes_it(self):
        with Sandbox(self.SET_UP) as sb:
            sb.state = "running"
            self.assertEqual(sb.call(app.cmd_password), 0, sb.output())
            # The admin container made again with the new .env, and nothing else.
            self.assertEqual(sb.compose_calls, [("up", "-d", "--force-recreate", "admin")])
            self.assertIn("for the admin pages and the players' site", sb.output())

    def test_typed_twice_on_a_terminal(self):
        with Sandbox(self.SET_UP) as sb, mock.patch("sys.stdin.isatty", return_value=True), \
                mock.patch("getpass.getpass", side_effect=["Xk3vQ9pLm2Rt7w", "Xk3vQ9pLm2Rt7w"]):
            self.assertEqual(sb.call(app.cmd_password), 0, sb.output())
            self.assertEqual(sb.env()["ADMIN_PASSWORD"], "Xk3vQ9pLm2Rt7w")
            # A typed password is not printed back.
            self.assertNotIn("Xk3vQ9pLm2Rt7w", sb.output())

    def test_refused_and_nothing_changed(self):
        # One Docker Compose would read as something else ($ names a variable there), one too short, two that differ.
        for typed in (["abc$defghijk"], ["short"], ["Xk3vQ9pLm2Rt7w", "Xk3vQ9pLm2Rt7x"]):
            with Sandbox(self.SET_UP) as sb, mock.patch("sys.stdin.isatty", return_value=True), \
                    mock.patch("getpass.getpass", side_effect=typed):
                self.assertEqual(sb.call(app.cmd_password), 1, typed)
                self.assertEqual(sb.env()["ADMIN_PASSWORD"], "old-password-1", typed)
                self.assertEqual(sb.compose_calls, [])

    def test_before_setup(self):
        with Sandbox(env_text=None) as sb:
            self.assertEqual(sb.call(app.cmd_password), 1)
            self.assertIn("setup", sb.output())

    def test_the_same_rule_as_the_admin_pages(self):
        # One rule for a new owner's password, here and on the Server page (lifecycle.py).
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools",
                               "opendmtq_tools", "admin", "lifecycle.py"), encoding="utf-8") as f:
            pages = re.search(r'OWNER_PASSWORD = re\.compile\((r".*?")\)', f.read()).group(1)
        self.assertEqual(eval(pages), env.OWNER_PASSWORD)  # noqa: S307 - a literal read from our own source


class HostPasswordCommandTest(unittest.TestCase):
    """opendmtq password on a host install (OpenDMTQ.exe password on Windows), the way in when the owner's password is
    lost: the same as ./opendmtq password, with a running server started again on Linux and macOS, and on Windows the
    window to close and open again said (SRV-57)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "host"))
        from opendmtq_host import commands
        cls.commands = commands

    def run_password(self, running=None, windows=False, typed=None):
        """The command on a host install's .env: (exit status, .env after, what it said, whether it restarted)."""
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env_file = os.path.join(tmp.name, ".env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=old-password-1\n")
        said, restarted = [], []
        patches = [mock.patch.object(self.commands, "ENV_FILE", env_file),
                   mock.patch.object(self.commands, "require_settings", lambda: env.load(env_file)),
                   mock.patch.object(self.commands, "running_pid", lambda: running),
                   mock.patch.object(self.commands, "WINDOWS", windows),
                   mock.patch.object(self.commands, "cmd_restart", lambda args: restarted.append(True)),
                   mock.patch.object(self.commands, "say", said.append),
                   mock.patch.object(self.commands, "ok", said.append),
                   mock.patch.object(self.commands, "tell", said.append),
                   mock.patch.object(self.commands, "die", lambda msg, code=1: (said.append(msg), sys.exit(code))),
                   mock.patch("sys.stdin", io.StringIO()),
                   mock.patch("sys.stdin.isatty", return_value=typed is not None),
                   mock.patch("getpass.getpass", side_effect=typed or [])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        try:
            code = self.commands.cmd_password(None)
        except SystemExit as e:
            code = e.code
        return code, env.load(env_file), " ".join(said), bool(restarted)

    def test_one_made_and_a_running_server_started_again(self):
        code, values, said, restarted = self.run_password(running=4242)
        self.assertEqual(code, 0)
        self.assertRegex(values["ADMIN_PASSWORD"], r"^[A-Za-z0-9_-]{16}$")
        self.assertIn(f"The new password: {values['ADMIN_PASSWORD']}", said)
        self.assertTrue(restarted)

    def test_on_windows_the_window_is_said(self):
        code, values, said, restarted = self.run_password(running=4242, windows=True, typed=["Xk3vQ9pLm2Rt7w", "Xk3vQ9pLm2Rt7w"])
        self.assertEqual((code, values["ADMIN_PASSWORD"], restarted), (0, "Xk3vQ9pLm2Rt7w", False))
        self.assertIn("start OpenDMTQ.exe again", said)
        self.assertNotIn("Xk3vQ9pLm2Rt7w", said)

    def test_refused_and_nothing_changed(self):
        code, values, said, restarted = self.run_password(running=None, typed=["abc#defghijk"])
        self.assertEqual((code, values["ADMIN_PASSWORD"], restarted), (1, "old-password-1", False))
        self.assertIn("10 to 64 characters", said)


class HostNameCommandTest(unittest.TestCase):
    """opendmtq name on a host install (OpenDMTQ.exe name on Windows), the twin of the Server page's Change the name: the
    app's name shown, or SERVER_NAME in .env changed from the next start, with a running server started again on Linux
    and macOS, and on Windows the window to close and open again said; a name .env cannot take refused (CLI-70)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "host"))
        from opendmtq_host import commands
        cls.commands = commands

    def run_name(self, name, running=None, windows=False, env_text="PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\n"):
        """The command on a host install's .env: (exit status, .env after, what it said, whether it restarted)."""
        import argparse
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env_file = os.path.join(tmp.name, ".env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write(env_text)
        said, restarted = [], []
        patches = [mock.patch.object(self.commands, "ENV_FILE", env_file),
                   mock.patch.object(self.commands, "require_settings", lambda: env.load(env_file)),
                   mock.patch.object(self.commands, "running_pid", lambda: running),
                   mock.patch.object(self.commands, "WINDOWS", windows),
                   mock.patch.object(self.commands, "cmd_restart", lambda args: restarted.append(True)),
                   mock.patch.object(self.commands, "say", said.append),
                   mock.patch.object(self.commands, "ok", said.append),
                   mock.patch.object(self.commands, "tell", said.append),
                   mock.patch.object(self.commands, "die", lambda msg, code=1: (said.append(msg), sys.exit(code)))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        try:
            code = self.commands.cmd_name(argparse.Namespace(name=name))
        except SystemExit as e:
            code = e.code
        return code, env.load(env_file), " ".join(said), bool(restarted)

    def test_shown_with_the_address_while_it_has_none(self):
        code, values, said, restarted = self.run_name(None)
        self.assertEqual((code, restarted), (0, False))
        self.assertIn("TECHNIKA Q (192.168.0.10:8791) on phones", said)

    def test_changed_from_the_next_start_and_a_running_server_started_again(self):
        code, values, said, restarted = self.run_name("Living Room", running=4242)
        self.assertEqual((code, values["SERVER_NAME"], restarted), (0, "Living Room", True))
        self.assertIn("the app is called TECHNIKA Q (Living Room) from the server's next start", said)
        # Back to none: the address names the app.
        code, values, said, restarted = self.run_name("", env_text="PUBLIC_HOST=192.168.0.10:8791\nSERVER_NAME=Living Room\n")
        self.assertEqual((code, values.get("SERVER_NAME"), restarted), (0, "", False))
        self.assertIn("TECHNIKA Q (192.168.0.10:8791) from the server's next start", said)

    def test_on_windows_the_window_is_said(self):
        code, values, said, restarted = self.run_name("거실 서버", running=4242, windows=True)
        self.assertEqual((code, values["SERVER_NAME"], restarted), (0, "거실 서버", False))
        self.assertIn("start OpenDMTQ.exe again", said)

    def test_refused_and_nothing_changed(self):
        for name in ('My "server"', "a$b", "x" * 81, "tab\there"):
            code, values, said, restarted = self.run_name(name, running=4242)
            self.assertEqual((code, values.get("SERVER_NAME"), restarted), (1, None, False), name)
        self.assertIn("at most 80 characters", said)
        # The one it has already: nothing to do.
        code, values, said, restarted = self.run_name("Den", env_text="PUBLIC_HOST=192.168.0.10:8791\nSERVER_NAME=Den\n")
        self.assertEqual((code, restarted), (0, False))
        self.assertIn("already", said)

    def test_the_command_line_has_it(self):
        # Registered as the other host commands are, with its name optional (run as a normal user, as the command asks).
        from opendmtq_host import cli
        with mock.patch.object(self.commands, "require_settings", lambda: {"PUBLIC_HOST": "192.168.0.10:8791"}), \
                mock.patch.object(self.commands, "say") as said, mock.patch("os.geteuid", return_value=1000, create=True):
            self.assertEqual(cli.main(["name"]), 0)
        self.assertIn("TECHNIKA Q (192.168.0.10:8791)", said.call_args[0][0])


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

    def test_up_names_the_admin_pages_on_the_one_port(self):
        # Kept off the public port: on this PC, on the server's own port, and up waits for them there.
        with Sandbox("PUBLIC_HOST=192.168.0.10:8790\nLISTEN_PORT=8790\nADMIN_ON_PUBLIC_PORT=no\nADMIN_PORT=9791\n"
                     "ADMIN_PASSWORD=x\n") as sb:
            game_data(sb)
            with mock.patch.object(app.time, "sleep"):
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            self.assertIn("http://localhost:8790/opendmtq/admin/", sb.output())
            self.assertIn("http://127.0.0.1:8790/opendmtq/admin/login", sb.urls)
            self.assertNotIn("9791", sb.output())

    def test_an_owners_id_the_site_does_not_take_is_said_at_the_start(self):
        # ADMIN_USER of an e-mail address, a space, Hangul or more than 40 characters opens the admin pages (40 at most)
        # and never the players' site: up says so with the rule, under the owner's sign-in (CLI-95; main said nothing).
        for user in ("kang@home.example", "owner one", "김세나", "x" * 41):
            with Sandbox(f"PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_USER={user}\nADMIN_PASSWORD=x\n") as sb:
                game_data(sb)
                with mock.patch.object(app.time, "sleep"):
                    self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
                self.assertIn(f"ADMIN_USER={user} cannot sign in to the players' site: an ID there is 1 to 40 letters "
                              "(A-Z, a-z), digits, '.', '_' or '-'; change it in .env, then start the server again",
                              sb.output(), user)
        with Sandbox("PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_USER=kang.home_2-x\nADMIN_PASSWORD=x\n") as sb:
            game_data(sb)
            with mock.patch.object(app.time, "sleep"):
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            self.assertNotIn("cannot sign in", sb.output())

    def test_bind_address_is_where_up_waits_and_what_the_link_says(self):
        # BIND_ADDRESS, as docs/troubleshooting.md has a Linux owner set it, publishes the port on that address alone
        # (CLI-92; main waited on 127.0.0.1, where nothing answered, for 30 s and said the admin pages were not answering,
        # and printed http://localhost:<port>/ for an exposed server, which answered nothing either).
        # A local network server: a visit on plain HTTP to that address is sent to the HTTPS door (the sandbox answers
        # it as a real server does), so up asks the admin service itself, and the link is the address phones use.
        lan = "PUBLIC_HOST=192.168.0.10:8790\nLISTEN_PORT=8790\nBIND_ADDRESS=192.168.0.10\nADMIN_PASSWORD=x\n"
        with Sandbox(lan) as sb:
            game_data(sb)
            sb.programs[("docker", "exec")] = done(0)
            with mock.patch.object(app.time, "sleep"):
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            self.assertEqual([u for u in sb.urls if u.endswith("/opendmtq/admin/login")], [])
            self.assertIn("http://192.168.0.10:8790/opendmtq/admin/", sb.output())
            self.assertNotIn("not answering", sb.output())
        # The same while the admin service has not started: said once the wait is over.
        with Sandbox(lan) as sb:
            game_data(sb)
            sb.programs[("docker", "exec")] = done(1)
            with mock.patch.object(app.time, "sleep"):
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            self.assertIn("admin pages are not answering yet", sb.output())
        # Exposed, the pages kept to the server PC: a visit from this PC to that address counts as one from elsewhere, so
        # this PC has no door to them; up asks the admin service itself, and the link says how to have them.
        exposed = ("PUBLIC_HOST=game.example.com:8790\nLISTEN_PORT=8790\nADMIN_ON_PUBLIC_PORT=no\nBIND_ADDRESS=192.168.0.10\n"
                   "ADMIN_PASSWORD=x\n")
        with Sandbox(exposed) as sb:
            game_data(sb)
            sb.programs[("docker", "exec")] = done(0)
            with mock.patch.object(app.time, "sleep"):
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            self.assertEqual([u for u in sb.urls if u.endswith("/opendmtq/admin/login")], [])
            self.assertIn("off (the port is published on 192.168.0.10 alone, where a visit from this PC counts as one from "
                          "elsewhere; ./opendmtq expose game.example.com --admin-public puts them on the public port over HTTPS)",
                          sb.output())
            self.assertNotIn("localhost:8790", sb.output())
            self.assertNotIn("not answering", sb.output())
        # On loopback alone: the link and the wait there.
        with Sandbox(exposed.replace("BIND_ADDRESS=192.168.0.10", "BIND_ADDRESS=127.0.0.1")) as sb:
            game_data(sb)
            with mock.patch.object(app.time, "sleep"):
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            self.assertIn("http://127.0.0.1:8790/opendmtq/admin/login", sb.urls)
            self.assertIn("http://localhost:8790/opendmtq/admin/ on this PC", sb.output())

    def test_a_server_on_port_80_moves_to_its_admin_pages_port(self):
        # Set up before 0.11.0 on port 80 (no LISTEN_PORT, an address without a port): up moves it to the port its admin
        # pages had, here 9791 and then 8791 (the first free after a taken one), as `port` moves one; the site's start
        # then notes the move from the address served before, and status and the Server page say it once each.
        for env_text, busy, want in (("PUBLIC_HOST=192.168.0.10\nADMIN_PORT=9791\nADMIN_PASSWORD=x\n", set(), 9791),
                                     ("PUBLIC_HOST=192.168.0.10\nLISTEN_PORT=80\nADMIN_PASSWORD=x\n", {8791}, 8792)):
            with Sandbox(env_text) as sb:
                game_data(sb)
                sb.busy_ports = busy
                with mock.patch.object(app.time, "sleep"):
                    self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
                self.assertEqual((sb.env()["PUBLIC_HOST"], sb.env()["LISTEN_PORT"]), (f"192.168.0.10:{want}", str(want)))
                self.assertNotIn("ADMIN_PORT", sb.env())
                self.assertIn(f"The server moved from port 80 to {want}: http://192.168.0.10:{want}/", sb.output())
                self.assertIn(f"server up: http://192.168.0.10:{want}/", sb.output())
                with open(sb.path("data/state/address.json"), encoding="utf-8") as f:
                    self.assertEqual(json.load(f), {"host": "192.168.0.10"})
                # status once, then no more.
                for said in (True, False):
                    before = len(sb.output())
                    self.assertEqual(sb.call(app.cmd_status), 0)
                    self.assertEqual(f"moved from port 80 to {want}" in sb.output()[before:], said)
                # Started again: nothing more moves, and nothing more says so.
                before = len(sb.output())
                with mock.patch.object(app.time, "sleep"):
                    self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
                self.assertNotIn("moved", sb.output()[before:])
                self.assertEqual(sb.env()["LISTEN_PORT"], str(want))

    def test_a_move_off_port_80_is_whole_or_not_made(self):
        # data/state handed to www-data by an earlier run with sudo, the server now started by its owner: the move wrote
        # .env, then died on the notes with a traceback, and the next start no longer moved, so nothing ever said it (DEP-112).
        # Now the way to take data/ back comes first and nothing moves; notes that cannot be written leave .env as it was.
        env_text = "PUBLIC_HOST=192.168.0.10\nADMIN_PORT=8791\nADMIN_PASSWORD=x\n"
        with Sandbox(env_text) as sb, mock.patch.object(system.os, "getuid", return_value=1000), \
                mock.patch.object(system.os, "getgid", return_value=1000):
            game_data(sb)
            # data/state as the earlier run left it: there, and not this user's.
            os.makedirs(sb.path("data/state"), exist_ok=True)
            self.assertEqual(sb.call(app.cmd_up), 1, sb.output())
            self.assertIn("data/state belongs to uid 0, but the server runs as uid 1000", sb.output())
            self.assertIn("sudo chown -R 1000:1000", sb.output())
            self.assertEqual(sb.read(".env"), env_text.encode())
            self.assertFalse(os.path.exists(sb.path("data/state/port-moved.json")))
        with Sandbox(env_text) as sb, \
                mock.patch.object(app.env, "note_move_off_80", side_effect=PermissionError(13, "Permission denied")):
            game_data(sb)
            self.assertEqual(sb.call(app.cmd_up), 1, sb.output())
            self.assertIn("the move off port 80 could not be noted in data/state (Permission denied); nothing moved yet",
                          sb.output())
            self.assertEqual(sb.read(".env"), env_text.encode())

    def test_an_exposed_server_on_port_80_moves_and_the_router_is_told(self):
        # Exposed before 0.11.0 with `expose NAME --port 80`: its public port was its own and moves with it, and the start
        # says the router's forward goes to the new port; a public port that differs from its own (a router forwarding
        # 8443 to port 80) is the router's and stays, with the app and its address, the forward going to the new port
        # (DEP-91; main rewrote the public port too and said nothing of the router). Never back to 80 after.
        for env_text, address, said in (
                ("PUBLIC_HOST=game.example.com\nLISTEN_PORT=80\nADMIN_ON_PUBLIC_PORT=no\nADMIN_PASSWORD=x\n", "game.example.com:8791",
                 ["The server moved from port 80 to 8791: http://game.example.com:8791/",
                  "On the router(s), forward TCP 8791 to port 8791 of this PC, in place of the forward of TCP 80.",
                  "Phones install the app again from that address (the site's download page says so), and PCs connect to it."]),
                ("PUBLIC_HOST=game.example.com:8443\nLISTEN_PORT=80\nADMIN_ON_PUBLIC_PORT=no\nADMIN_PASSWORD=x\n", "game.example.com:8443",
                 ["The server moved from port 80 to 8791; its address stays http://game.example.com:8443/",
                  "On the router(s), forward TCP 8443 to port 8791 of this PC in place of port 80."])):
            with Sandbox(env_text) as sb:
                game_data(sb)
                with mock.patch.object(app.time, "sleep"):
                    self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
                self.assertEqual((sb.env()["PUBLIC_HOST"], sb.env()["LISTEN_PORT"]), (address, "8791"))
                for line in said:
                    self.assertEqual(sb.output().count(line), 1, (line, sb.output()))
                if address.endswith(":8443"):
                    self.assertNotIn("Phones install the app again", sb.output())
                # status once, in one paragraph, with the router's line.
                before = len(sb.output())
                self.assertEqual(sb.call(app.cmd_status), 0)
                self.assertIn(said[0] + ". " + said[1], sb.output()[before:])
                # The next start moves nothing and says nothing more.
                before = len(sb.output())
                with mock.patch.object(app.time, "sleep"):
                    self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
                self.assertNotIn("moved", sb.output()[before:])
                self.assertEqual((sb.env()["PUBLIC_HOST"], sb.env()["LISTEN_PORT"]), (address, "8791"))

    def test_the_old_admin_container_frees_the_port_first(self):
        # Its admin pages still published on 127.0.0.1:8791 by the release before: that port is this server's to take,
        # and their container goes before up makes the edge that takes it.
        with Sandbox("PUBLIC_HOST=192.168.0.10\nADMIN_PASSWORD=x\n") as sb:
            game_data(sb)
            sb.busy_ports, sb.admin_port = {8791}, 8791
            with mock.patch.object(app.time, "sleep"):
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            self.assertEqual(sb.env()["LISTEN_PORT"], "8791")
            self.assertIn(("rm", "-sf", "admin"), sb.compose_calls)
            self.assertLess(sb.compose_calls.index(("rm", "-sf", "admin")),
                            next(i for i, c in enumerate(sb.compose_calls) if c[0] == "up"))

    def test_port_80_by_the_owners_choice_stays(self):
        # `port 80` marks the choice; a port the owner chose that is not 80 stays too.
        with Sandbox("PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=x\n") as sb:
            game_data(sb)
            self.assertEqual(sb.call(app.cmd_port, port=80), 0, sb.output())
            self.assertEqual((sb.env()["PUBLIC_HOST"], sb.env()["LISTEN_PORT"], sb.env()["PORT_80"]),
                             ("192.168.0.10", "80", "chosen"))
            with mock.patch.object(app.time, "sleep"):
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            self.assertEqual(sb.env()["LISTEN_PORT"], "80")
            self.assertNotIn("moved", sb.output())
            # Another port after it: the mark goes.
            self.assertEqual(sb.call(app.cmd_port, port=9000), 0, sb.output())
            self.assertNotIn("PORT_80", sb.env())
        with Sandbox("PUBLIC_HOST=192.168.0.10:9000\nLISTEN_PORT=9000\nADMIN_PORT=8791\nADMIN_PASSWORD=x\n") as sb:
            game_data(sb)
            with mock.patch.object(app.time, "sleep"):
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            self.assertEqual(sb.env()["LISTEN_PORT"], "9000")

    def test_the_firewall_rule_follows_a_move_off_port_80(self):
        # On WSL the rule for phones moves with the port, from 80 to the new one, as `port` moves it.
        with Sandbox("PUBLIC_HOST=192.168.0.10\nADMIN_PASSWORD=x\n", wsl=True) as sb:
            game_data(sb)
            sb.windows_reachable()
            with mock.patch.object(app.time, "sleep"), mock.patch.object(app.system, "run_firewall_script",
                                                                        return_value=None) as script:
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            script.assert_called_once_with(port=8791, internet=False, replaces=80)
        # Behind a router that keeps its own public port: the rule is for the server's own new port, from anywhere.
        with Sandbox("PUBLIC_HOST=game.example.com:8443\nLISTEN_PORT=80\nADMIN_ON_PUBLIC_PORT=no\nADMIN_PASSWORD=x\n", wsl=True) as sb:
            game_data(sb)
            sb.windows_reachable()
            with mock.patch.object(app.time, "sleep"), mock.patch.object(app.system, "run_firewall_script",
                                                                        return_value=None) as script:
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            script.assert_called_once_with(port=8791, internet=True, replaces=80)

    def test_up_with_no_firewall_leaves_the_rule_at_a_move(self):
        # --no-firewall leaves Windows' firewall alone at a move off port 80 too, as setup's does: a test of the move on
        # a WSL machine never replaces the rule of a server that runs there.
        with Sandbox("PUBLIC_HOST=192.168.0.10\nADMIN_PASSWORD=x\n", wsl=True) as sb:
            game_data(sb)
            sb.windows_reachable()
            with mock.patch.object(app.time, "sleep"), mock.patch.object(app.system, "run_firewall_script") as script:
                self.assertEqual(sb.call(app.cmd_up, no_firewall=True), 0, sb.output())
            script.assert_not_called()
            self.assertEqual(sb.env()["LISTEN_PORT"], "8791")
            self.assertIn("The server moved from port 80 to 8791", sb.output())
        # And the command line takes it.
        with mock.patch.object(app, "cmd_up", return_value=0) as up:
            self.assertEqual(app.main(["up", "--no-firewall"]), 0)
        self.assertTrue(up.call_args.args[0].no_firewall)

    def test_up_status_and_setup_name_one_admin_address(self):
        # up, status and the setup's end all name the admin pages on the server's one port, at the address phones use,
        # with where the password is (CLI-21). (up and the setup's end in their block of addresses, status on its admin
        # line.)
        wanted = "http://192.168.0.10:8791/opendmtq/admin/"
        with Sandbox("PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=x\n") as sb:
            game_data(sb)
            with mock.patch.object(app.time, "sleep"):
                self.assertEqual(sb.call(app.cmd_up), 0, sb.output())
            self.assertEqual(sb.call(app.cmd_status), 0, sb.output())
            with mock.patch.object(app, "cmd_up"), mock.patch.object(checks, "end_to_end", return_value=0):
                self.assertEqual(sb.call(app.cmd_setup, host=None, source=None, rebuild_apk=False, no_firewall=True), 0,
                                 sb.output())
            self.assertEqual(sb.output().count(wanted), 3, sb.output())
            self.assertEqual(sb.output().count("ADMIN_PASSWORD in .env"), 3, sb.output())
            self.assertEqual(sb.output().count("/opendmtq/admin/"), 3, sb.output())
            self.assertNotIn("localhost", sb.output())
            # The setup's end gives the password itself, beside where it is kept, as a host install's setup does (CLI-93;
            # main named only where it was kept); up and status name where it is kept.
            self.assertEqual(len(re.findall(r"Password +x  \(kept as ADMIN_PASSWORD in \.env\)", sb.output())), 1, sb.output())

    def test_help_keeps_deploy_out_of_the_newcomers_list(self):
        # deploy is a maintainer's command for a live server: under a heading of its own after the list, and it still
        # answers, with its own help.
        # As a person runs it: the command line's own program, in a process of its own.
        program = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "opendmtq")
        shown = subprocess.run([sys.executable, program, "--help"], capture_output=True, text=True, timeout=60)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        # The list ends at argparse's heading of the options: "options:" from Python 3.10, "optional arguments:" before.
        listed, after = re.split(r"\n(?:options|optional arguments):\n", shown.stdout, maxsplit=1)
        self.assertIn("    setup ", listed)
        self.assertNotIn("deploy", listed)
        self.assertIn("for a live server's maintainers", after)
        self.assertIn("  deploy    put this commit on the live server", after)
        shown = subprocess.run([sys.executable, program, "deploy", "--help"], capture_output=True, text=True, timeout=60)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("--no-gates", shown.stdout)

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
