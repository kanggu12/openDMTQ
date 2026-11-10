"""Tests for .env handling and address detection."""

import os
import stat
import tempfile
import unittest
from unittest import mock

from opendmtq_cli import env

# The repository: the host program is beside the command line in it.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ParseTest(unittest.TestCase):
    def test_compose_compatible_forms(self):
        text = '# comment\r\nPUBLIC_HOST="192.168.0.5"\r\nexport TZ=Asia/Seoul\nBAD LINE\nEMPTY=\n'
        self.assertEqual(env.parse(text), {"PUBLIC_HOST": "192.168.0.5", "TZ": "Asia/Seoul", "EMPTY": ""})

    def test_inline_comment_on_unquoted_value(self):
        self.assertEqual(env.parse("PUBLIC_HOST=192.168.0.5 # home\nNAME='a #b'"),
                         {"PUBLIC_HOST": "192.168.0.5", "NAME": "a #b"})

    def test_single_quotes_and_spaces(self):
        self.assertEqual(env.parse("PUBLIC_HOST = '10.0.0.7' "), {"PUBLIC_HOST": "10.0.0.7"})


class SaveTest(unittest.TestCase):
    def test_updates_in_place_and_keeps_comments(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w") as f:
                f.write("# keep me\nPUBLIC_HOST=1.1.1.1\nRESTART=no\n")
            env.save(path, {"PUBLIC_HOST": "192.168.0.9", "NEW": "x"})
            with open(path) as f:
                self.assertEqual(f.read(), "# keep me\nPUBLIC_HOST=192.168.0.9\nRESTART=no\nNEW=x\n")

    def test_owner_only(self):
        # It holds the admin and download passwords.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            env.save(path, {"ADMIN_PASSWORD": "x"})
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            # A file written by an earlier version, readable by everyone.
            os.chmod(path, 0o644)
            env.save(path, {"ADMIN_USER": "y"})
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


    def test_the_host_installs_keys_are_owner_only(self):
        # The download sign-in's key and the setup's one-time sign-in, as a host install writes them: whoever reads one
        # signs in as anyone, or opens the setup.
        import importlib
        import sys
        with tempfile.TemporaryDirectory() as d:
            key = os.path.join(d, "download.key")
            env.write_private(key, "k")
            self.assertEqual(stat.S_IMODE(os.stat(key).st_mode), 0o600)
            # A sibling an earlier write left, readable by everyone: narrowed as it is written.
            with open(key + ".tmp", "w") as f:
                f.write("old")
            os.chmod(key + ".tmp", 0o644)
            env.write_private(key, "k2")
            self.assertEqual(stat.S_IMODE(os.stat(key).st_mode), 0o600)
            with open(key) as f:
                self.assertEqual(f.read(), "k2")
            # The host program's one-time link writes its key so (its paths module sets the root in the environment:
            # put back after).
            with mock.patch.dict(os.environ), mock.patch.object(sys, "path", [os.path.join(ROOT, "host")] + sys.path):
                server = importlib.import_module("opendmtq_host.server")
            with mock.patch.object(server, "RUN", d):
                link = server.setup_link({})
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(d, "signin.token")).st_mode), 0o600)
            with open(os.path.join(d, "signin.token")) as f:
                self.assertTrue(link.endswith("key=" + f.read()))

    def test_a_first_start_on_windows_writes_it_too(self):
        # Windows' Python (3.12 in the bundle) has neither os.fchmod nor os.getuid: the first start of OpenDMTQ.exe,
        # with no .env yet, writes one through here (tests/windows/wine.sh starts it so as well).
        gone = {name: getattr(os, name) for name in ("fchmod", "getuid") if hasattr(os, name)}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            try:
                for name in gone:
                    delattr(os, name)
                env.save(path, {"PUBLIC_HOST": "192.168.0.9", "ADMIN_PASSWORD": "x"})
            finally:
                for name, value in gone.items():
                    setattr(os, name, value)
            with open(path) as f:
                self.assertIn("ADMIN_PASSWORD=x", f.read())


class HostTest(unittest.TestCase):
    def test_check_host(self):
        for good in ("192.168.219.100", "myhome.example.com", "myhome.example.com:8790", "10.0.0.5:8080"):
            self.assertIsNone(env.check_host(good), good)
        for bad in ("", "localhost", "127.0.0.1", "999.1.1.1", "169.254.1.1", "0.0.0.0",
                    "bad_name", "a.b:99999", "host:abc"):
            self.assertIsNotNone(env.check_host(bad), bad)

    def test_lan_only_and_join(self):
        self.assertTrue(env.is_lan_only("192.168.0.10"))
        self.assertFalse(env.is_lan_only("myhome.example.com:8790"))
        self.assertEqual(env.join("a.example", 80), "a.example")
        self.assertEqual(env.join("a.example", 8790), "a.example:8790")

    def test_listen_port(self):
        self.assertEqual(env.listen_port({}), 80)
        self.assertEqual(env.listen_port({"LISTEN_PORT": "8790"}), 8790)

    def test_with_no_way_out_the_address_comes_from_the_machine_itself(self):
        # A closed network may have no gateway: there is no route to ask about, and the setup must not stop for that.
        output = ("1: lo    inet 127.0.0.1/8 scope host lo\n"
                  "3: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0\n"
                  "4: br-1a2b3c    inet 172.20.0.1/16 scope global br-1a2b3c\n"
                  "7: eth0    inet 10.20.30.40/24 brd 10.20.30.255 scope global eth0\n")
        self.assertEqual(env.interface_addresses(output), ["127.0.0.1", "10.20.30.40"])
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout=output)):
            self.assertEqual(env.own_private_address(), "10.20.30.40")

    def test_with_several_real_interfaces_it_does_not_guess(self):
        # A wrong guess builds an app for an address no phone reaches: whoever is at the terminal says which, with --host.
        output = ("2: eth0    inet 10.20.0.5/24 scope global eth0\n"
                  "3: wlan0    inet 192.168.0.5/24 scope global wlan0\n")
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout=output)):
            self.assertIsNone(env.own_private_address())

    def test_a_virtual_machines_interface_is_no_answer(self):
        output = ("2: eth0    inet 10.20.0.5/24 scope global eth0\n"
                  "3: vboxnet0    inet 192.168.56.1/24 scope global vboxnet0\n"
                  "4: vmnet8    inet 192.168.40.1/24 scope global vmnet8\n"
                  "5: lxdbr0    inet 10.100.0.1/24 scope global lxdbr0\n"
                  "6: podman0    inet 10.88.0.1/16 scope global podman0\n"
                  "7: wg0    inet 10.8.0.2/24 scope global wg0\n")
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout=output)):
            self.assertEqual(env.own_private_address(), "10.20.0.5")

    def test_an_address_the_machine_still_has_is_its_own_on_any_network(self):
        # Two networks: the one chosen for the phones need not be the likeliest, and following "it moved" would break them.
        output = ("2: eth0    inet 10.0.0.5/24 scope global eth0\n"
                  "3: wlan0    inet 192.168.0.7/24 scope global wlan0\n")
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout=output)):
            self.assertTrue(env.has_address("10.0.0.5"))
        with mock.patch("subprocess.run", side_effect=FileNotFoundError), \
                mock.patch.object(env.socket, "gethostbyname_ex", return_value=("pc", [], ["192.168.0.7", "10.0.0.5"])):
            self.assertTrue(env.has_address("10.0.0.5"))
            self.assertFalse(env.has_address("10.0.0.6"))

    def test_a_computers_name_that_cannot_be_looked_up_stops_nothing(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError), mock.patch.object(env.socket, "gethostname", return_value="x..local"):
            self.assertIsNone(env.own_private_address())
            self.assertFalse(env.has_address("10.0.0.5"))

    def test_without_ip_it_asks_the_machines_own_name(self):
        # Windows and macOS. The usual home and office ranges come before those Hyper-V and WSL get.
        with mock.patch("subprocess.run", side_effect=FileNotFoundError), \
                mock.patch.object(env.socket, "gethostbyname_ex", return_value=("pc", [], ["172.28.16.1", "192.168.0.7"])):
            self.assertEqual(env.own_private_address(), "192.168.0.7")

    def test_what_a_phone_cannot_reach_is_no_answer(self):
        self.assertIsNone(env.best_private(["127.0.0.1", "169.254.10.20", "8.8.8.8"]))
        self.assertIsNone(env.best_private([]))
        self.assertEqual(env.best_private(["172.16.5.5"]), "172.16.5.5")

    def test_route_source(self):
        out = "1.1.1.1 via 192.168.0.1 dev eth0 src 192.168.0.20 uid 0 \n    cache \n"
        self.assertEqual(env.route_source(out), "192.168.0.20")
        self.assertIsNone(env.route_source(""))


class WindowsDriveTest(unittest.TestCase):
    MOUNTS = ("none /mnt/wsl tmpfs rw,relatime 0 0\n"
              "drivers /usr/lib/wsl/drivers 9p ro,aname=drivers;fmask=222 0 0\n"
              "/dev/sdc / ext4 rw,relatime 0 0\n"
              "C:\\134 /mnt/c 9p rw,noatime,aname=drvfs;path=C:\\;uid=0 0 0\n"
              "D:\\134 /mnt/my\\040drive drvfs rw,noatime 0 0\n")

    def test_clone_on_a_windows_drive(self):
        self.assertTrue(env.windows_drive("/mnt/c/Users/me/OpenDMTQ", self.MOUNTS))
        self.assertTrue(env.windows_drive("/mnt/my drive/OpenDMTQ", self.MOUNTS))

    def test_clone_inside_wsl(self):
        for path in ("/home/me/OpenDMTQ", "/mnt/cache/OpenDMTQ", "/usr/lib/wsl/drivers/x"):
            self.assertFalse(env.windows_drive(path, self.MOUNTS), path)


class HttpsAddressTest(unittest.TestCase):
    def test_the_port_is_always_written(self):
        # HTTPS shares the plain port: a port-80 server is https://host:80/, not the default 443.
        from opendmtq_cli import env
        self.assertEqual(env.https_address("192.168.0.10"), "192.168.0.10:80")
        self.assertEqual(env.https_address("myhome.example.com:8790"), "myhome.example.com:8790")


class WslNatTest(unittest.TestCase):
    def test_a_home_network_in_172_is_not_nat_in_mirrored_mode(self):
        # KT home gateways hand out 172.30.1.x: in mirrored mode that is the PC's real LAN address.
        from unittest import mock
        from opendmtq_cli import env
        with mock.patch.object(env, "is_wsl", return_value=True), \
                mock.patch.object(env, "wsl_networking_mode", return_value="mirrored"):
            self.assertFalse(env.wsl_nat_address("172.30.1.23"))
        with mock.patch.object(env, "is_wsl", return_value=True), \
                mock.patch.object(env, "wsl_networking_mode", return_value="nat"):
            self.assertTrue(env.wsl_nat_address("172.30.1.23"))

if __name__ == "__main__":
    unittest.main()
