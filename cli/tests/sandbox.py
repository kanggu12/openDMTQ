"""A throwaway install for command tests.

The repository root is a temporary folder, and everything that reaches outside the process is a
recorder: docker compose and the tools container, other programs, PowerShell, HTTP, the terminal.
A command that tries to run any other program fails the test instead of touching this machine.
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from unittest import mock

from opendmtq_cli import app, backup, checks, env, system

# The real repository, for files a command reads from it (the firewall script).
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def done(code=0, stdout="", stderr=""):
    """A finished program's result."""
    return subprocess.CompletedProcess([], code, stdout, stderr)


class Sandbox:
    def __init__(self, env_text="PUBLIC_HOST=192.168.0.10\n", detected="192.168.0.10", wsl=False):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.data = os.path.join(self.root, "data")
        self.env_file = os.path.join(self.root, ".env")
        if env_text is not None:
            self.write(".env", env_text)
        os.makedirs(os.path.join(self.root, "cli"))
        shutil.copyfile(os.path.join(REPO, "cli", "firewall.ps1"), os.path.join(self.root, "cli", "firewall.ps1"))
        self.detected = detected
        self.wsl = wsl
        # Ports something else on the machine answers on, and the one this server's own edge publishes.
        self.busy_ports = set()
        self.edge_port = None
        # What `docker inspect` says about the server container, and whether its portal answers.
        self.state = None
        self.healthy = True
        # What the HTTPS probe reports (None: the door answers with a fitting certificate).
        self.https = None
        # The edge container's state (the public port).
        self.edge = "running"
        # What the server-side builder reports: True when it built a new app.
        self.built = False
        self.compose_calls, self.tool_calls, self.urls, self.scripts = [], [], [], []
        self.tool_services = []
        # Tool module -> function(args, extra_env) run in its place, returning its exit code.
        self.tools = {}
        # Program name prefix -> result, for the programs a command may run.
        self.programs = {("docker", "info"): done(0, "29.0.0\n"), ("docker", "exec"): done(0),
                         # WSL in NAT mode, as the tests that pass wsl=True picture it.
                         ("wslinfo", "--networking-mode"): done(0, "nat\n")}
        # Windows side: None while PowerShell cannot be reached (see windows_reachable).
        self.windows_temp = None
        self.out, self.err = io.StringIO(), io.StringIO()

    # ------------------------------------------------------------------ files

    def path(self, rel):
        return os.path.join(self.root, rel)

    def write(self, rel, content):
        path = self.path(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb" if isinstance(content, bytes) else "w") as f:
            f.write(content)
        return path

    def read(self, rel):
        with open(self.path(rel), "rb") as f:
            return f.read()

    def env(self):
        return env.load(self.env_file)

    def archive(self, rel, members):
        """A backup archive at rel holding {name: bytes}; returns its file name."""
        path = self.path(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with tarfile.open(path, "w:gz") as tar:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return os.path.basename(path)

    def backups(self):
        folder = os.path.join(self.data, "backups")
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    def output(self):
        return self.out.getvalue() + self.err.getvalue()

    def windows_reachable(self):
        """PowerShell answers, and its temp folder is a folder in the sandbox."""
        self.windows_temp = os.path.join(self.root, "wintemp")
        os.makedirs(self.windows_temp)
        self.programs[("wslpath",)] = done(0, self.windows_temp + "\n")

    def call(self, fn, **args):
        """Run a command function; returns its exit status (a SystemExit's included)."""
        try:
            return fn(argparse.Namespace(**args)) or 0
        except SystemExit as e:
            return e.code

    # ------------------------------------------------------------------ recorders

    def _compose(self, *args, extra_env=None, check=True, capture=False):
        self.compose_calls.append(args)
        words = " ".join(args)
        if "cp /in/dmtq.db3 /data/state/dmtq.db3" in words:
            # The restore's copy job.
            os.makedirs(os.path.join(self.data, "state"), exist_ok=True)
            # What the job's own shell line says it removes first, removed here too.
            for end in ("-wal", "-shm", "-journal"):
                if f"/data/state/dmtq.db3{end}" in words:
                    with contextlib.suppress(FileNotFoundError):
                        os.remove(os.path.join(self.data, "state", "dmtq.db3" + end))
            shutil.copyfile(os.path.join(extra_env["IMPORT_FROM"], "dmtq.db3"),
                            os.path.join(self.data, "state", "dmtq.db3"))
        elif args[0] == "down":
            self.state = None
        elif args[0] == "stop":
            self.state = "exited"
        elif args[0] == "start" or (args[0] == "up" and "server" in args):
            self.state = "running"
        return done()

    def _tool(self, module, *args, extra_env=None, as_invoker=False, service="tools"):
        self.tool_calls.append((module, args, dict(extra_env or {})))
        # The compose service each module ran in (the import has one of its own).
        self.tool_services.append((module, service))
        fn = self.tools.get(module)
        return done((fn(args, extra_env or {}) if fn else 0) or 0)

    def _run(self, cmd, *args, **kwargs):
        for prefix, result in self.programs.items():
            if tuple(cmd[:len(prefix)]) == prefix:
                return result
        # This copy's version, for the pages: no git checkout in a test's folder.
        if cmd[:1] == ["git"] and "log" in cmd:
            return done(1)
        raise AssertionError(f"a test ran an unexpected program: {cmd}")

    def _http(self, url, data=None, json_body=None, method=None, timeout=10, headers=None):
        self.urls.append(url)
        if url.endswith("/opendmtq/health.php"):
            if not self.healthy:
                return 0, b""
            host = self.env().get("PUBLIC_HOST", "")
            return 200, json.dumps({"ok": True, "host": host, "songs": 1, "players": 0,
                                    "patch": "1.003.005"}).encode()
        if url.endswith("/opendmtq/admin/login"):
            return 200, b""
        return 0, b""

    def _powershell(self, script, timeout=60):
        self.scripts.append(script)
        if self.windows_temp is None:
            return None
        if "GetTempPath" in script:
            return done(0, "C:\\Users\\player\\AppData\\Local\\Temp\\\r\n")
        if "Get-NetFirewallRule" in script:
            return done(0, "none\r\n")
        # The elevated run of cli/firewall.ps1.
        return done(0, "exit 0\r\n")

    # ------------------------------------------------------------------ context

    def __enter__(self):
        self._stack = contextlib.ExitStack()
        s = self._stack
        paths = dict(ROOT=self.root, ENV_FILE=self.env_file, DATA=self.data)
        s.enter_context(mock.patch.multiple(
            system, **paths, compose=self._compose, tool=self._tool, container_state=lambda service="server": self.state if service in ("server", "admin") else self.edge,
            require_docker=lambda: None, own_data_dirs=lambda *a, **k: None, first_build_notice=lambda: False,
            powershell=self._powershell, port_busy=lambda port: port in self.busy_ports, project_folder=lambda name: None,
            edge_holds=lambda port: port == self.edge_port))
        s.enter_context(mock.patch.multiple(app, **paths, wait_builder=lambda since=None: self.built))
        s.enter_context(mock.patch.multiple(
            backup, DATA=self.data, ENV_FILE=self.env_file, BACKUPS=os.path.join(self.data, "backups"),
            DB=os.path.join(self.data, "state", "dmtq.db3"), KEYSTORE=os.path.join(self.data, "apk", "keystore"),
            # The tests' archives hold a few bytes for a database; RealDatabaseTest checks the real thing.
            database_problem=lambda archive: None))
        s.enter_context(mock.patch.multiple(checks, DATA=self.data, ENV_FILE=self.env_file, http=self._http,
                                            https_problem=lambda host: self.https))
        s.enter_context(mock.patch.multiple(env, detect_host=lambda: self.detected, has_address=lambda address: False, is_wsl=lambda: self.wsl))
        s.enter_context(mock.patch("subprocess.run", self._run))
        # No prompts: a test's stdin is not a terminal.
        s.enter_context(mock.patch("sys.stdin", io.StringIO()))
        s.enter_context(contextlib.redirect_stdout(self.out))
        s.enter_context(contextlib.redirect_stderr(self.err))
        return self

    def __exit__(self, *exc):
        self._stack.close()
        self._tmp.cleanup()
        return False
