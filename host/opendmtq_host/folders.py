"""The data folders, and the environment of the server's programs and of the tools."""

import functools
import os
import subprocess
import tempfile

from .paths import APP, BUNDLE, DATA, ENV_FILE, LOGS, PYTHON, RUN, WINDOWS
from .output import die
from .programs import find_programs
from .settings import admin_port, listen_port, settings

# The folders the server and the tools write, created before anything runs.
FOLDERS = ("content", "state", os.path.join("state", "logs"), os.path.join("apk", "base"), os.path.join("apk", "out"),
           "custom", "backups", os.path.join("https", "public"))


def make_folders():
    """data/ and its folders, and this install's run folder."""
    for sub in FOLDERS:
        os.makedirs(os.path.join(DATA, sub), exist_ok=True)
    os.makedirs(RUN, exist_ok=True)


def slashes(path):
    """A path with forward slashes: Apache's configuration and PHP take them on Windows too, and need no escaping."""
    return path.replace("\\", "/")


def server_env(values, found):
    """The environment of the server's programs (Apache with PHP, the PHP scripts): the folders, as site.conf and the
    PHP code read them, and the server's settings."""
    e = dict(os.environ)
    e.update({
        # The code: server/ holds game/ and portal/ as the image's /opt/opendmtq does.
        "OPENDMTQ_APP": slashes(os.path.join(APP, "server")),
        "OPENDMTQ_CONTENT": slashes(os.path.join(DATA, "content")),
        "OPENDMTQ_CUSTOM": slashes(os.path.join(DATA, "custom")),
        "OPENDMTQ_STATE": slashes(os.path.join(DATA, "state")),
        "OPENDMTQ_DB": slashes(os.path.join(DATA, "state", "dmtq.db3")),
        "OPENDMTQ_APK_OUT": slashes(os.path.join(DATA, "apk", "out")),
        "OPENDMTQ_HTTPS": slashes(os.path.join(DATA, "https", "public")),
        "OPENDMTQ_RUN": slashes(RUN),
        # What the game and the pages are told.
        "PUBLIC_HOST": values["PUBLIC_HOST"],
        "SERVER_NAME": values.get("SERVER_NAME", ""),
        "LIVE_DEFAULT": values.get("LIVE_DEFAULT", "off"),
        "OPENDMTQ_VERSION": version(),
        # One server for everything; the admin pages behind it, on this machine.
        "ROLE": "api",
        "ADMIN_URL": f"http://127.0.0.1:{admin_port(values)}",
        "ADMIN_ON_PUBLIC_PORT": values.get("ADMIN_ON_PUBLIC_PORT", "yes"),
    })
    if WINDOWS and BUNDLE:
        # Apache loads PHP, and PHP its extensions, whose own DLLs (SQLite's, Apache's) Windows looks for on the PATH.
        rt = os.path.join(BUNDLE, "runtime")
        e["PATH"] = os.pathsep.join([os.path.join(rt, "php"), os.path.join(rt, "apache", "bin"), e.get("PATH", "")])
    return e


def tools_env(values, found):
    """The environment of the tools (import, app builder, song list) and the admin pages: where data/ is, the programs
    they call, and the server's address."""
    e = dict(os.environ)
    e.update({
        "OPENDMTQ_DATA": DATA,
        "OPENDMTQ_APK": os.path.join(DATA, "apk"),
        "OPENDMTQ_DB": os.path.join(DATA, "state", "dmtq.db3"),
        "OPENDMTQ_LOGS": LOGS,
        "OPENDMTQ_BACKUPS": os.path.join(DATA, "backups"),
        "OPENDMTQ_CONTENT": os.path.join(DATA, "content"),
        "OPENDMTQ_CUSTOM": os.path.join(DATA, "custom"),
        # The server's certificate authority's public folder, as the server reads it (server_env): the installer the admin
        # pages hand out carries the authority where there is one.
        "OPENDMTQ_HTTPS": os.path.join(DATA, "https", "public"),
        # The programs the app builder and the import call.
        "OPENDMTQ_JAVA": found.get("java") or "java",
        "OPENDMTQ_KEYTOOL": found.get("keytool") or "keytool",
        "OPENDMTQ_APKTOOL": found.get("apktool") or "",
        "OPENDMTQ_SIGNER": found.get("signer") or "",
        "OPENDMTQ_7ZIP": found.get("7zip") or "7zz",
        "OPENDMTQ_WORK": os.path.join(tempfile.gettempdir(), "opendmtq-apk"),
        # The server, as the admin pages reach it (status, styles, fonts).
        "SERVER_URL": f"http://127.0.0.1:{listen_port(values)}",
        "PUBLIC_HOST": values.get("PUBLIC_HOST", ""),
        "SERVER_NAME": values.get("SERVER_NAME", ""),
        "BASE_APK": values.get("BASE_APK", ""),
        # What new players start with until the owner chooses on the Broadcasts page, as the server reads it.
        "LIVE_DEFAULT": values.get("LIVE_DEFAULT", "off"),
        "ADMIN_USER": values.get("ADMIN_USER", ""),
        "ADMIN_PASSWORD": values.get("ADMIN_PASSWORD", ""),
        "OPENDMTQ_VERSION": version(),
        # The setup pages (tools/opendmtq_tools/admin/setup.py) run on this PC: they may look at its folders, change
        # the settings and ask this program for a restart (watch() below), and take the one-time sign-in from the run
        # folder.
        "OPENDMTQ_HOST_INSTALL": "yes",
        "OPENDMTQ_ENV_FILE": ENV_FILE,
        "OPENDMTQ_RUN": RUN,
    })
    return e


# Once: the watch below asks for the programs' environments every two seconds, and this may have to ask git.
@functools.lru_cache(maxsize=None)
def version():
    """The version the pages show: a release's number from the VERSION file (the Windows bundle's, or the one the
    one-command install writes, "0.2.0"), else a clone's as with Docker (the command line's system.code_version()): the
    release at its tag ("0.9.3"), past it the release and the commit ("0.9.3-16e0b56"); a copy with no git, the release
    alone, as Docker shows it too. The pages put a v before the first part and keep what follows the first dash for the
    pointer, so this is never git describe's "v0.2.0-3-g655895c"."""
    try:
        with open(os.path.join(APP, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        pass

    def git_says(*args):
        # One line from git, or '' when it fails or this is no checkout.
        try:
            r = subprocess.run(["git", "-C", APP, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        except (OSError, subprocess.SubprocessError):
            return ""
        return r.stdout.strip() if r.returncode == 0 else ""
    # The release the tree names: its Helm chart's appVersion, which each release sets.
    release = ""
    try:
        with open(os.path.join(APP, "deploy", "helm", "opendmtq", "Chart.yaml"), encoding="utf-8") as f:
            release = next((line.split(":", 1)[1].strip().strip('"') for line in f if line.startswith("appVersion:")), "")
    except OSError:
        pass
    commit = git_says("rev-parse", "--short=7", "HEAD")
    # No commit to name (no .git, or no git to ask): the release alone, or none for a tree that names none.
    if not commit:
        return release
    # A tree from before its chart named the release: the date and commit of its code.
    if not release:
        return git_says("log", "-1", "--format=%cd-%h", "--date=format:%Y.%m.%d")
    # At the release's own commit (its tag): the release alone.
    at_tag = git_says("rev-parse", "-q", "--verify", f"refs/tags/v{release}^{{commit}}") == git_says("rev-parse", "HEAD")
    return release if at_tag else f"{release}-{commit}"


def php_command(found):
    """The PHP command line program, with the bundle's php.ini on Windows (elsewhere the system's own applies)."""
    return [found["php"]] + (["-c", os.path.join(RUN, "php.ini")] if WINDOWS else [])


def tool(module, *args, values=None, found=None, extra=None, check=False):
    """Run one of the tools (opendmtq_tools.<module>) with this install's Python, in the foreground. Returns its
    exit status."""
    values = values if values is not None else settings()
    found = found or find_programs()
    e = tools_env(values, found)
    e.update(extra or {})
    r = subprocess.run(PYTHON + ["-m", f"opendmtq_tools.{module}", *args], env=e)
    if check and r.returncode != 0:
        die(f"{module} failed (see above)")
    return r.returncode
