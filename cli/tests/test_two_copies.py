"""Two copies of the repository on one machine are two servers: they must not take over each other's containers or ports."""

import os
import tempfile
import unittest
from unittest import mock

from opendmtq_cli import app, env, system

from .sandbox import Sandbox


REAL_FIRST_BUILD_NOTICE = system.first_build_notice


def other_copy():
    """A folder that looks like another copy of the repository."""
    folder = tempfile.TemporaryDirectory()
    with open(os.path.join(folder.name, "compose.yaml"), "w"):
        pass
    return folder


class NameTest(unittest.TestCase):
    def setUp(self):
        # Once per command in real life; every test is a new command.
        system._project_checked = False

    def test_containers_follow_the_name_in_env(self):
        with Sandbox(env_text="COMPOSE_PROJECT_NAME=opendmtq2\n"):
            self.assertEqual(system.container(), "opendmtq2-server")
            self.assertEqual(system.container("edge"), "opendmtq2-edge")

    def test_the_default_name_without_a_setting(self):
        with Sandbox():
            self.assertEqual(system.container("builder"), "opendmtq-builder")

    def test_compose_gets_the_name_from_env_over_the_shell(self):
        with Sandbox(env_text="COMPOSE_PROJECT_NAME=opendmtq3\n"), mock.patch.dict(os.environ, {"COMPOSE_PROJECT_NAME": "other"}):
            self.assertEqual(system.compose_env()["COMPOSE_PROJECT_NAME"], "opendmtq3")

    def test_no_containers_anywhere_keeps_the_name(self):
        with Sandbox() as sb, mock.patch.object(system, "project_folder", return_value=None):
            system.ensure_own_project()
            self.assertNotIn("COMPOSE_PROJECT_NAME", env.load(sb.env_file))

    def test_its_own_containers_keep_the_name(self):
        with Sandbox() as sb, mock.patch.object(system, "project_folder", side_effect=lambda name: sb.root):
            system.ensure_own_project()
            self.assertNotIn("COMPOSE_PROJECT_NAME", env.load(sb.env_file))

    def test_a_running_other_copy_means_the_next_name(self):
        other = other_copy()
        with Sandbox() as sb, mock.patch.object(system, "project_folder",
                                                side_effect=lambda name: other.name if name == "opendmtq" else None):
            system.ensure_own_project()
            self.assertEqual(env.load(sb.env_file)["COMPOSE_PROJECT_NAME"], "opendmtq2")
        other.cleanup()

    def test_the_next_name_skips_those_taken_too(self):
        other = other_copy()
        with Sandbox() as sb, mock.patch.object(system, "project_folder",
                                                side_effect=lambda name: other.name if name in ("opendmtq", "opendmtq2") else None):
            system.ensure_own_project()
            self.assertEqual(env.load(sb.env_file)["COMPOSE_PROJECT_NAME"], "opendmtq3")
        other.cleanup()

    def test_a_folder_that_cannot_be_seen_counts_as_another_copy(self):
        # Another user's, another WSL distribution's, or this copy's before it moved: nothing here can tell them apart, and
        # taking over the first two would replace a running server.
        with Sandbox() as sb, mock.patch.object(system, "project_folder",
                                                side_effect=lambda name: "/nowhere/OpenDMTQ" if name == "opendmtq" else None):
            system.ensure_own_project()
            self.assertEqual(env.load(sb.env_file)["COMPOSE_PROJECT_NAME"], "opendmtq2")
            self.assertIn("docker compose -p opendmtq down", sb.output())

    def test_looking_up_a_container_comes_after_the_check(self):
        # A backup here must not reach the other copy's database under the shared name.
        other = other_copy()
        with Sandbox(), mock.patch.object(system, "project_folder",
                                          side_effect=lambda name: other.name if name == "opendmtq" else None):
            self.assertEqual(system.container(), "opendmtq2-server")
        other.cleanup()

    def test_checked_once_per_command(self):
        with Sandbox(), mock.patch.object(system, "project_folder", return_value=None) as asked:
            system.ensure_own_project()
            system.ensure_own_project()
            self.assertEqual(asked.call_count, 1)


class PortTest(unittest.TestCase):
    def setUp(self):
        system._project_checked = False

    def new_server(self, sb, busy):
        """A machine where these ports are taken by something other than this server."""
        sb.busy_ports = set(busy)

    def test_a_new_server_takes_port_80_when_free(self):
        with Sandbox(env_text=None) as sb:
            self.assertEqual(app.ensure_env(), "192.168.0.10")
            self.assertNotIn("LISTEN_PORT", env.load(sb.env_file))

    def test_a_new_server_moves_off_a_taken_port_80(self):
        with Sandbox(env_text=None) as sb:
            self.new_server(sb, {80})
            self.assertEqual(app.ensure_env(), "192.168.0.10:8080")
            values = env.load(sb.env_file)
            self.assertEqual(values["PUBLIC_HOST"], "192.168.0.10:8080")
            self.assertEqual(values["LISTEN_PORT"], "8080")
            self.assertIsNone(env.port_problem(values))

    def test_and_past_the_next_ports_when_taken_too(self):
        with Sandbox(env_text=None) as sb:
            self.new_server(sb, {80, 8080, 8081})
            self.assertEqual(app.ensure_env(), "192.168.0.10:8082")

    def test_a_public_address_gets_the_port_too(self):
        # A machine on the internet by itself: what phones call and what is published have to agree.
        with Sandbox(env_text=None, detected="93.184.216.34") as sb:
            self.new_server(sb, {80})
            self.assertEqual(app.ensure_env(), "93.184.216.34:8080")
            self.assertEqual(env.load(sb.env_file)["LISTEN_PORT"], "8080")

    def test_port_80_held_by_this_server_itself_stays(self):
        # Its .env is gone while it runs: its own edge answers on 80.
        with Sandbox(env_text=None) as sb:
            sb.busy_ports = {80}
            sb.edge_port = 80
            self.assertEqual(app.ensure_env(), "192.168.0.10")

    def test_going_back_from_the_internet_moves_off_a_taken_port_80(self):
        # Its own edge runs on the exposed port; port 80 is the other copy's.
        with Sandbox(env_text="PUBLIC_HOST=game.example.com:8790\nLISTEN_PORT=8790\n") as sb:
            sb.busy_ports = {80, 8790}
            sb.edge_port = 8790
            chosen = app.ensure_env(reset={"PUBLIC_HOST": "", "LISTEN_PORT": ""})
            self.assertEqual(chosen, "192.168.0.10:8080")
            self.assertEqual(env.load(sb.env_file)["LISTEN_PORT"], "8080")

    def test_going_back_writes_port_80_when_free(self):
        with Sandbox(env_text="PUBLIC_HOST=game.example.com:8790\nLISTEN_PORT=8790\n") as sb:
            self.assertEqual(app.ensure_env(reset={"PUBLIC_HOST": "", "LISTEN_PORT": ""}), "192.168.0.10")
            self.assertEqual(env.load(sb.env_file)["LISTEN_PORT"], "80")

    def test_wsl_nat_address_is_refused_with_a_port_too(self):
        with Sandbox(env_text=None, detected="172.24.1.2", wsl=True) as sb, \
                mock.patch.object(env, "wsl_networking_mode", return_value="nat"):
            self.new_server(sb, {80})
            self.assertEqual(sb.call(lambda args: app.ensure_env()), 1)
            self.assertFalse(os.path.exists(sb.env_file))

    def test_a_server_already_set_up_stays_where_it_is(self):
        # Its own port answers while it runs, and the phones' app has that address in it.
        with Sandbox() as sb:
            sb.busy_ports = {80}
            self.assertEqual(app.ensure_env(), "192.168.0.10")
            self.assertNotIn("LISTEN_PORT", env.load(sb.env_file))

    def test_a_port_named_in_env_is_kept(self):
        with Sandbox(env_text="LISTEN_PORT=9000\n") as sb:
            sb.busy_ports = {9000}
            self.assertEqual(app.ensure_env(), "192.168.0.10:9000")

    def test_an_address_given_by_hand_is_kept(self):
        with Sandbox(env_text=None) as sb:
            sb.busy_ports = {80}
            self.assertEqual(app.ensure_env("192.168.0.10"), "192.168.0.10")

    def test_admin_port_moves_off_a_taken_one(self):
        with Sandbox() as sb:
            sb.busy_ports = {8791, 8792}
            app.ensure_admin_port()
            self.assertEqual(env.load(sb.env_file)["ADMIN_PORT"], "8793")

    def test_admin_port_stays_while_it_is_our_own(self):
        with Sandbox() as sb:
            sb.state = "running"
            sb.busy_ports = {8791}
            app.ensure_admin_port()
            self.assertNotIn("ADMIN_PORT", env.load(sb.env_file))

    def test_admin_port_named_in_env_is_kept(self):
        with Sandbox(env_text="PUBLIC_HOST=192.168.0.10\nADMIN_PORT=9001\n") as sb:
            sb.busy_ports = {9001, 8791}
            app.ensure_admin_port()
            self.assertEqual(env.load(sb.env_file)["ADMIN_PORT"], "9001")


class OfflineBuildTest(unittest.TestCase):
    """A LAN server whose router lost the internet still starts: a build asks a registry even when nothing changed."""

    def build(self, code, present, first=False):
        result = mock.Mock(returncode=code, stdout="", stderr="no such host")
        with Sandbox(), mock.patch.object(system, "compose", return_value=result) as compose, \
                mock.patch.object(system, "first_build_notice", return_value=first), \
                mock.patch.object(system, "images_present", return_value=present):
            system.build("server")
        return compose

    def test_a_failed_build_with_images_here_goes_on(self):
        self.assertEqual(self.build(1, True).call_count, 1)

    def test_a_failed_build_without_images_stops(self):
        with self.assertRaises(SystemExit):
            self.build(1, False)

    def test_a_failed_first_build_stops(self):
        with self.assertRaises(SystemExit):
            self.build(1, True, first=True)

    def test_up_does_not_build_a_second_time(self):
        with Sandbox() as sb:
            sb.write("data/content/web/patch/phone_new/1.003.005/android/patch_new.csv.lz4", b"")
            sb.state = "running"
            with mock.patch.object(system, "build") as build, mock.patch.object(app, "wait_healthy", return_value={"songs": 1, "players": 0}), \
                    mock.patch.object(app.checks, "https_problem", return_value=None), mock.patch.object(app.checks, "http", return_value=(200, b"")):
                sb.call(app.cmd_up)
            build.assert_called_once()
            ups = [c for c in sb.compose_calls if c and c[0] == "up"]
            self.assertTrue(ups)
            self.assertFalse([c for c in ups if "--build" in c])


class ImageTest(unittest.TestCase):
    def test_each_copy_builds_its_own_images(self):
        # With one tag, a restart of the first copy would run whatever the second one built last.
        with Sandbox(env_text="COMPOSE_PROJECT_NAME=opendmtq2\n"), mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            with mock.patch.object(system, "first_build_notice", REAL_FIRST_BUILD_NOTICE):
                system.first_build_notice()
            self.assertIn("opendmtq2-server:local", run.call_args[0][0])


class DetectTest(unittest.TestCase):
    def test_without_the_ip_command_the_socket_says(self):
        # macOS has no `ip`.
        with mock.patch("subprocess.run", side_effect=FileNotFoundError), mock.patch.object(env, "socket_source", return_value="192.168.0.7"):
            self.assertEqual(env.detect_host(), "192.168.0.7")

    def test_the_route_comes_first(self):
        out = mock.Mock(stdout="1.1.1.1 via 192.168.0.1 dev eth0 src 192.168.0.20 uid 0\n")
        with mock.patch("subprocess.run", return_value=out), mock.patch.object(env, "socket_source", return_value="10.0.0.1"):
            self.assertEqual(env.detect_host(), "192.168.0.20")


if __name__ == "__main__":
    unittest.main()
