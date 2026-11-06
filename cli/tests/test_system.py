"""Tests for reaching Windows from WSL: finding PowerShell, reading its output, running the firewall
script elevated."""

import contextlib
import io
import os
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

    def test_no_images_is_a_failure_that_names_the_internet(self):
        with mock.patch("sys.stderr", io.StringIO()) as err, self.assertRaises(SystemExit):
            self.build(images_here=False)
        self.assertIn("the first build needs the internet", err.getvalue())


class FirewallScriptTest(unittest.TestCase):
    def run_script(self, temp, result="exit 0\r\n", **kwargs):
        """run_firewall_script with Windows faked; returns (its result, the elevating script)."""
        scripts = []

        def fake(script, timeout=60):
            scripts.append(script)
            if "GetTempPath" in script:
                return subprocess.CompletedProcess([], 0, temp + "\r\n", "")
            return subprocess.CompletedProcess([], 0, result, "")

        with tempfile.TemporaryDirectory() as d, mock.patch.object(system, "powershell", fake), \
                mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, d + "\n", "")):
            out = system.run_firewall_script(**kwargs)
        return out, [s for s in scripts if "Start-Process" in s][0]

    def test_the_copy_is_there_for_the_elevated_run_and_gone_after_it(self):
        with tempfile.TemporaryDirectory() as d:
            copy = os.path.join(d, "opendmtq-firewall.ps1")
            during = []

            def fake(script, timeout=60):
                if "GetTempPath" in script:
                    return subprocess.CompletedProcess([], 0, "C:\\Temp\\\r\n", "")
                # The elevated run reads the copy, so it must exist at this moment.
                during.append(os.path.isfile(copy))
                return subprocess.CompletedProcess([], 0, "exit 0\r\n", "")

            with mock.patch.object(system, "powershell", fake), \
                    mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, d + "\n", "")):
                self.assertIsNone(system.run_firewall_script(port=80))
            self.assertEqual(during, [True])
            self.assertFalse(os.path.exists(copy), "the script must not stay in the Windows temp folder")

    def test_temp_folder_with_a_space_is_quoted(self):
        _, script = self.run_script("C:\\Users\\John Doe\\AppData\\Local\\Temp\\", port=8790, internet=True)
        self.assertIn("'\"C:\\Users\\John Doe\\AppData\\Local\\Temp\\opendmtq-firewall.ps1\"'", script)
        self.assertIn("'-Port','8790'", script)
        self.assertIn("'-Internet'", script)

    def test_temp_folder_with_a_quote_is_escaped(self):
        _, script = self.run_script("C:\\Users\\O'Brien\\AppData\\Local\\Temp\\", port=80)
        self.assertIn("'\"C:\\Users\\O''Brien\\AppData\\Local\\Temp\\opendmtq-firewall.ps1\"'", script)

    def test_a_failed_script_is_a_failure(self):
        # powershell.exe -File on a missing file exits -196608; WSL keeps the low 8 bits, which are 0.
        out, _ = self.run_script("C:\\Temp\\", result="exit -196608\r\n", port=80)
        self.assertIsInstance(out, str, "a failure must not read as success")

    def test_success(self):
        out, _ = self.run_script("C:\\Temp\\", port=80)
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
