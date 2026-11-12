"""Tests for reaching Windows from WSL: finding PowerShell, reading its output, running the firewall
script elevated."""

import base64
import contextlib
import io
import os
import re
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from opendmtq_cli import system

from .sandbox import Sandbox


def fake_program(folder, body):
    """An executable shell script standing in for powershell.exe."""
    path = os.path.join(folder, "powershell.exe")
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


class PowerShellTest(unittest.TestCase):
    def test_found_when_windows_is_not_on_path(self):
        # sudo resets PATH (secure_path), and appendWindowsPath=false leaves Windows out of it.
        with tempfile.TemporaryDirectory() as d:
            exe = fake_program(d, "echo ok\n")
            with mock.patch("shutil.which", return_value=None), \
                    mock.patch.object(system, "WINDOWS_POWERSHELL", exe, create=True):
                r = system.powershell("Write-Output ok")
        self.assertIsNotNone(r)
        self.assertEqual(r.stdout.strip(), "ok")

    def test_output_in_a_windows_code_page_is_read(self):
        # A Korean profile folder, printed in code page 949 as Windows PowerShell does by default.
        with tempfile.TemporaryDirectory() as d:
            exe = fake_program(d, r"printf 'C:\\Users\\\307\321\\AppData\\Local\\Temp\\\r\n'" + "\n")
            with mock.patch("shutil.which", return_value=exe):
                r = system.powershell("[IO.Path]::GetTempPath()")
        self.assertIsNotNone(r)
        self.assertTrue(r.stdout.startswith("C:\\Users\\"), r.stdout)

    def test_scripts_ask_for_utf8_output(self):
        with tempfile.TemporaryDirectory() as d:
            exe = fake_program(d, 'echo "$4"\n')
            with mock.patch("shutil.which", return_value=exe):
                r = system.powershell("[IO.Path]::GetTempPath()")
        self.assertIn("[Console]::OutputEncoding", r.stdout)


class NoInternetBuildTest(unittest.TestCase):
    """Docker asks for the base images' current versions even when nothing changed, so a build
    fails with no internet. Images already here are enough to start; with none there is no server."""

    def build(self, times=1, images_here=True):
        """system.build with every compose build failing; returns what it printed."""
        failed = subprocess.CompletedProcess([], 1, "", "failed to resolve source metadata")
        out = io.StringIO()
        with mock.patch.object(system, "compose", return_value=failed), \
                mock.patch.object(system, "first_build_notice", return_value=False), \
                mock.patch.object(system, "images_present", return_value=images_here), \
                mock.patch.object(system, "_offline_said", False), contextlib.redirect_stdout(out):
            for _ in range(times):
                system.build("server")
        return out.getvalue()

    def test_images_already_here_are_used_and_it_is_said_once(self):
        self.assertEqual(self.build(times=2).count("using the ones already built"), 1)

    def test_named_images_are_not_built(self):
        # A release's images, brought to a server without internet: building would only fail there.
        names = "OPENDMTQ_SERVER_IMAGE=ghcr.io/x/server:1\nOPENDMTQ_TOOLS_IMAGE=ghcr.io/x/tools:1\n"
        with Sandbox(env_text=names), mock.patch.object(system, "compose") as compose, \
                mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
            system.build("server", "builder", "admin")
            system.build("tools", profile="tools")
        compose.assert_not_called()
        self.assertIn(["docker", "image", "inspect", "ghcr.io/x/server:1"], [c.args[0] for c in run.call_args_list])

    def test_a_named_image_that_is_not_here_says_what_to_do(self):
        with Sandbox(env_text="OPENDMTQ_SERVER_IMAGE=ghcr.io/x/server:1\n"), mock.patch.object(system, "compose") as compose, \
                mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1)), \
                mock.patch("sys.stderr", io.StringIO()) as err, self.assertRaises(SystemExit):
            system.build("server")
        compose.assert_not_called()
        self.assertIn("docker load", err.getvalue())

    def test_the_first_builds_notice_is_said_once(self):
        # A first setup builds the tools image (for the import) and the server's after it (for up): both are a first
        # build, shown as one, and the notice that it takes minutes was said twice.
        built = subprocess.CompletedProcess([], 0, "", "")
        out = io.StringIO()
        # No .env (no image named in it), and docker knowing neither image: the real notice, not the sandbox's stand-in.
        with tempfile.TemporaryDirectory() as d, mock.patch.object(system, "ENV_FILE", os.path.join(d, ".env")), \
                mock.patch.object(system, "compose", return_value=built) as compose, \
                mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1)), \
                mock.patch.object(system, "_first_build_said", False), contextlib.redirect_stdout(out):
            system.build("tools", profile="tools")
            system.build("server", "builder", "admin")
        self.assertEqual(out.getvalue().count("First run: building"), 1, out.getvalue())
        # Both builds still show their output, as a first build does (no --quiet).
        self.assertEqual([c.args for c in compose.call_args_list],
                         [("--profile", "tools", "build", "tools"), ("build", "server", "builder", "admin")])

    def test_no_images_is_a_failure_that_names_the_internet(self):
        with mock.patch("sys.stderr", io.StringIO()) as err, self.assertRaises(SystemExit):
            self.build(images_here=False)
        self.assertIn("the first build needs the internet", err.getvalue())


class FirewallScriptTest(unittest.TestCase):
    def run_script(self, result="exit 0\r\n", **kwargs):
        """run_firewall_script with Windows faked; returns (its result, the elevating script, the command the elevated
        PowerShell runs, decoded)."""
        scripts = []

        def fake(script, timeout=60):
            scripts.append(script)
            return subprocess.CompletedProcess([], 0, result, "")

        with mock.patch.object(system, "powershell", fake), mock.patch("subprocess.run") as ran:
            out = system.run_firewall_script(**kwargs)
        # Nothing else is run for it: no copy of the script to put anywhere.
        ran.assert_not_called()
        [script] = scripts
        encoded = re.search(r"'-EncodedCommand','([A-Za-z0-9+/=]+)'", script).group(1)
        return out, script, base64.b64decode(encoded).decode("utf-16-le")

    def test_the_script_goes_in_the_elevated_command_not_in_a_file(self):
        # A copy in the user's temp folder could be swapped by any program of that user while Windows asks for
        # permission. The elevated PowerShell runs what its own command line holds: every line of the script's code.
        _, script, command = self.run_script(port=80)
        self.assertNotIn("-File", script)
        with open(os.path.join(system.ROOT, "cli", "firewall.ps1"), encoding="utf-8") as f:
            code = [line.strip() for line in f.read().splitlines() if line.strip() and not line.strip().startswith("#")]
        self.assertEqual(command.splitlines()[1:-1], code)
        self.assertTrue(command.startswith("& {\n"))

    def test_its_parameters_go_with_it(self):
        _, _, command = self.run_script(port=8790, internet=True, replaces=80)
        self.assertTrue(command.endswith("\n} -Port 8790 -Internet -Replaces 80"), command[-60:])
        _, _, command = self.run_script(port=8790, remove=True, replaces=8790)
        self.assertTrue(command.endswith("\n} -Port 8790 -Remove"), command[-60:])

    def test_the_elevated_command_line_stays_short(self):
        # ShellExecute, which elevates it, cuts its parameters at 2,048 characters on some Windows versions.
        _, script, _ = self.run_script(port=65535, internet=True, remove=True, replaces=65534)
        arguments = re.search(r"-ArgumentList (.*?); 'exit '", script).group(1)
        self.assertLess(len(" ".join(a.strip("'") for a in arguments.split(","))), 2048)

    def test_without_powershell_it_says_so(self):
        with mock.patch.object(system, "powershell", lambda script, timeout=60: None):
            self.assertIn("cannot reach Windows PowerShell", system.run_firewall_script(port=80))

    def test_a_failed_script_is_a_failure(self):
        # powershell.exe on a command it cannot start exits -196608; WSL keeps the low 8 bits, which are 0.
        out, _, _ = self.run_script(result="exit -196608\r\n", port=80)
        self.assertIsInstance(out, str, "a failure must not read as success")

    def test_success(self):
        out, _, _ = self.run_script(port=80)
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
