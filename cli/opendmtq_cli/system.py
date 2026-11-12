"""Running things: docker compose, Windows PowerShell (from WSL), and console output."""

import base64
import os
import shutil
import socket
import subprocess
import sys

from .env import load as load_env
from .env import save as save_env

# Repository root (two levels above this file), or the folder the host program names: the Windows bundle keeps its
# settings and data/ beside its programs (host/opendmtq_host sets it).
ROOT = os.environ.get("OPENDMTQ_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_FILE = os.path.join(ROOT, ".env")
DATA = os.path.join(ROOT, "data")
# What this copy's containers are called, unless .env says otherwise (COMPOSE_PROJECT_NAME).
DEFAULT_PROJECT = "opendmtq"


def firewall_rule_name(port):
    """Display name of the Windows firewall rule cli/firewall.ps1 creates for a port."""
    return f"OpenDMTQ (TCP {port})"

# Colour only on a terminal.
_TTY = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def ok(msg):
    print(f"  {_c('32', 'ok')}    {msg}")


def warn(msg):
    print(f"  {_c('33', 'warn')}  {msg}")


def fail(msg):
    print(f"  {_c('31', 'FAIL')}  {msg}")


def step(msg):
    print(_c("1", f"\n== {msg}"))


def count(n, one, many=None):
    """A number with its word, the word for one when it is 1: "1 file", "2 files"."""
    return f"{n} {one if n == 1 else (many or one + 's')}"


def die(msg, code=1):
    print(_c("31", f"error: {msg}"), file=sys.stderr)
    raise SystemExit(code)


def run_ids():
    """uid/gid the containers run as: the invoking user, or www-data (33) when that is root."""
    uid, gid = os.getuid(), os.getgid()
    # Never run the containers as root, even when the CLI itself is run as root.
    return (33, 33) if uid == 0 else (uid, gid)


# Folders compose.yaml mounts from data/. All are made before any container starts: Docker would
# make a missing one as root, and the containers, which run as the invoking user, could then not
# write there.
DATA_DIRS = ("state", "apk", os.path.join("apk", "base"), os.path.join("apk", "out"), "custom", "content",
             "backups", "https", os.path.join("https", "public"), os.path.join("https", "serve"))


def make_data_dirs():
    """Every folder the containers mount, owned by the user they run as."""
    for sub in DATA_DIRS:
        try:
            os.makedirs(os.path.join(DATA, sub), exist_ok=True)
        except PermissionError:
            # data/ belongs to another user (an earlier run with sudo made it www-data's), and a folder
            # this version mounts is not there yet: say how to take it back, not a traceback.
            uid, gid = run_ids()
            die(data_owner_problem() or f"cannot create data/{sub} as uid {os.getuid()} (data/ belongs to another "
                f"user: an earlier run with sudo?). Take it back once: sudo chown -R {uid}:{gid} {DATA}")
    own_data_dirs()


def data_owner_problem():
    """None when the containers (running as run_ids()) own data/state, else what to do. A run
    as root hands data/ to www-data; the containers of a later run as a user then cannot write
    the database, and the server answers but keeps no player or score."""
    try:
        owner = os.stat(os.path.join(DATA, "state")).st_uid
    except OSError:
        return None
    uid, gid = run_ids()
    if os.getuid() == 0 or owner == uid:
        return None
    return (f"data/state belongs to uid {owner}, but the server runs as uid {uid} and could not save players "
            f"or scores (an earlier run with sudo?). Take it back once: sudo chown -R {uid}:{gid} {DATA}")


def own_data_dirs(uid=None, gid=None, subs=("state", "apk", "content", "backups", "custom", "https")):
    """When run as root, hand data/ to the container user, which writes, replaces and deletes there.

    With uid/gid given, hand the named folders to that owner instead (used around the import).
    """
    if os.getuid() != 0:
        return
    if uid is None:
        uid, gid = run_ids()
    os.makedirs(DATA, exist_ok=True)
    os.chown(DATA, uid, gid)
    for sub in subs:
        top = os.path.join(DATA, sub)
        os.makedirs(top, exist_ok=True)
        for d, dirs, files in os.walk(top):
            os.chown(d, uid, gid, follow_symlinks=False)
            for f in files:
                os.chown(os.path.join(d, f), uid, gid, follow_symlinks=False)


def host_timezone():
    """IANA zone name of this machine (for dates in file names), UTC when unknown."""
    if os.environ.get("TZ"):
        return os.environ["TZ"]
    link = os.path.realpath("/etc/localtime")
    return link.split("zoneinfo/", 1)[1] if "zoneinfo/" in link else "UTC"


def code_version():
    """This copy's version as the pages show it, the same for the same code however it was installed (the host install's
    folders.version(), the Windows bundle's build.sh): the release at its tag ("0.9.3"), past it the release and the
    commit ("0.9.3-16e0b56"), which the pages show as v0.9.3 with the commit under the pointer. The release is the one the
    tree names (release_of()). A copy with no git (a release's source archive, GitHub's Download ZIP, the one carried to a
    closed network) is the release it names, as host/get.sh writes it to a release's VERSION; '' when it names none."""
    def git_says(*args):
        # One line from git, or '' when it fails or this is no checkout.
        try:
            r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return ""
        return r.stdout.strip() if r.returncode == 0 else ""
    commit = git_says("rev-parse", "--short=7", "HEAD")
    if not commit:
        # No commit to name (no .git, or no git to ask): the release alone, which the tree's chart names.
        return release_of(ROOT)
    release = release_of(ROOT)
    # A tree from before its chart named the release: the date and commit of its code, as such trees always said.
    if not release:
        return git_says("log", "-1", "--format=%cd-%h", "--date=format:%Y.%m.%d")
    # At the release's own commit (its tag, wherever it was fetched from): the release alone.
    at_tag = git_says("rev-parse", "-q", "--verify", f"refs/tags/v{release}^{{commit}}") == git_says("rev-parse", "HEAD")
    return release if at_tag else f"{release}-{commit}"


def release_of(root):
    """The release a tree is, or comes after: the appVersion of its Helm chart (deploy/helm/opendmtq/Chart.yaml), which
    each release sets. '' when the tree has none."""
    try:
        with open(os.path.join(root, "deploy", "helm", "opendmtq", "Chart.yaml"), encoding="utf-8") as f:
            for line in f:
                # appVersion: "0.9.3"
                if line.startswith("appVersion:"):
                    return line.split(":", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def git(*args):
    """A git command's output in this copy; empty when it fails or this is no checkout."""
    r = run_program(["git", "-C", str(ROOT), *args])
    return r.stdout.strip() if r and r.returncode == 0 else ""


def run_program(cmd, timeout=60, cwd=None):
    """Another program's result, its output captured; None when it is not there or does not finish in time."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return None


def compose_env(extra=None):
    """Environment for docker compose: the caller's, plus our uid/gid so tool output is ours."""
    env = dict(os.environ)
    uid, gid = run_ids()
    env["OPENDMTQ_UID"] = str(uid)
    env["OPENDMTQ_GID"] = str(gid)
    env["TZ"] = host_timezone()
    env["OPENDMTQ_VERSION"] = code_version()
    # .env decides, also over a name left in the caller's shell: the CLI looks containers up by this one.
    env["COMPOSE_PROJECT_NAME"] = project()
    # Container create/start chatter is noise here; errors still reach stderr. In the environment, not as compose's
    # --progress flag: the Compose of Docker 23 has no such flag and stops at it, and ignores a variable it does not know.
    env["COMPOSE_PROGRESS"] = "quiet"
    env.update(extra or {})
    return env


def require_docker():
    """Stop with an install hint when Docker is missing."""
    if not shutil.which("docker"):
        die("Docker is not installed or not on PATH: https://docs.docker.com/engine/install/. "
            "To run without it: host/install.sh, then ./opendmtq setup")


def image_names():
    """This copy's two images: those .env names (a release's, brought here, docs/closed-network.md), or those built here."""
    values = load_env(ENV_FILE)
    return [values.get("OPENDMTQ_SERVER_IMAGE") or f"{project()}-server:local",
            values.get("OPENDMTQ_TOOLS_IMAGE") or f"{project()}-tools:local"]


_first_build_said = False


def first_build_notice():
    """Say so before the first image build, which takes a few minutes with no other output. True while an image is still
    to be built for the first time; the words once per command, which builds the tools image first and the server's
    after."""
    global _first_build_said
    r = subprocess.run(["docker", "image", "inspect", *image_names()], capture_output=True)
    if r.returncode != 0:
        if not _first_build_said:
            print("  First run: building the server and tools images. This takes a few minutes.", flush=True)
            _first_build_said = True
        return True
    return False


def project():
    """The compose project of this copy of the repository: its containers are <project>-<service>."""
    return load_env(ENV_FILE).get("COMPOSE_PROJECT_NAME") or DEFAULT_PROJECT


def container(service="server"):
    """The name of one of this copy's containers. Asked before anything is looked up by it: under another copy's name, a
    backup or a restore here would reach that copy's database."""
    ensure_own_project()
    return f"{project()}-{service}"


def project_folder(name):
    """The folder of the copy whose containers carry this project name, or None when no container does."""
    try:
        r = subprocess.run(["docker", "inspect", "-f", '{{index .Config.Labels "com.docker.compose.project.working_dir"}}',
                            f"{name}-server"], capture_output=True, text=True)
    except OSError:
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def held_elsewhere(name):
    """The other copy's folder when containers under this project name came from anywhere but here, else None. A folder
    that cannot be seen from here still counts: it may be another user's or another WSL distribution's, and taking over
    those containers would replace a running server."""
    folder = project_folder(name)
    if not folder or os.path.realpath(folder) == os.path.realpath(ROOT):
        return None
    return folder


_project_checked = False


def ensure_own_project():
    """Before compose touches anything: two copies under one project name would replace each other's containers. Nothing
    but the containers' names hangs on it (data stays in this folder), so this copy just takes the next free name."""
    global _project_checked
    if _project_checked:
        return
    _project_checked = True
    current = project()
    other = held_elsewhere(current)
    if not other:
        return
    number = 2
    while held_elsewhere(f"{DEFAULT_PROJECT}{number}"):
        number += 1
    name = f"{DEFAULT_PROJECT}{number}"
    save_env(ENV_FILE, {"COMPOSE_PROJECT_NAME": name})
    ok(f"the server in {other} is called {current}: this one is {name} (COMPOSE_PROJECT_NAME in .env)")
    # A copy that moved leaves its containers behind, under the folder it had.
    if not os.path.isdir(other):
        print(f"  If {other} was this copy before it moved, stop what it left running: docker compose -p {current} down")


def compose(*args, extra_env=None, check=True, capture=False):
    """Run `docker compose <args>` in the repository."""
    require_docker()
    ensure_own_project()
    cmd = ["docker", "compose", *args]
    r = subprocess.run(cmd, cwd=ROOT, env=compose_env(extra_env), text=True,
                       capture_output=capture)
    if check and r.returncode != 0:
        if capture:
            sys.stderr.write(r.stdout + r.stderr)
        die(f"`docker compose {' '.join(args)}` failed (exit {r.returncode})")
    return r


# The setting in .env that names the image a service runs in place of the one built here.
NAMED_IMAGES = {"server": "OPENDMTQ_SERVER_IMAGE", "builder": "OPENDMTQ_TOOLS_IMAGE", "admin": "OPENDMTQ_TOOLS_IMAGE",
                "tools": "OPENDMTQ_TOOLS_IMAGE"}


def build(*services, profile=None, strict=False):
    """Build images, or confirm they are up to date. With no network (a LAN server whose router lost the internet, a
    registry down) a build fails even when nothing changed, as Docker asks for the base images' current versions: images
    already here are good enough then, and the server still starts. strict: not for a deploy, which would run the old code
    under the new commit's name. An image .env names is not built: it only has to be here."""
    values = load_env(ENV_FILE)
    named = {values.get(NAMED_IMAGES.get(service, "")) for service in services} - {None, ""}
    if named:
        require_docker()
        for image in sorted(named):
            if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode != 0:
                die(f"the image {image}, named in .env, is not here: docker load or docker pull it first (docs/closed-network.md)")
    services = [service for service in services if not values.get(NAMED_IMAGES.get(service, ""))]
    if not services:
        return
    first = first_build_notice()
    words = (["--profile", profile] if profile else []) + ["build"] + ([] if first else ["--quiet"]) + list(services)
    r = compose(*words, check=False, capture=not first)
    if r.returncode == 0:
        return
    if first or strict or not images_present():
        if not first:
            sys.stderr.write((r.stdout or "") + (r.stderr or ""))
        die(f"could not build the images (exit {r.returncode}); the first build needs the internet")
    # One command can build more than once (the server's images, then the tools'): one warning is enough.
    global _offline_said
    if not _offline_said:
        warn("could not check the images for updates (no internet?); using the ones already built")
        _offline_said = True


_offline_said = False


def images_present():
    """Both of this copy's images are here."""
    return subprocess.run(["docker", "image", "inspect", *image_names()], capture_output=True).returncode == 0


_tools_built = False


def tool(module, *args, extra_env=None, as_invoker=False, service="tools", capture=False):
    """Run one tools-container module (opendmtq_tools.<module>).

    as_invoker runs it with the caller's own uid, even root: the import must read the user's
    folder, which (on WSL's /mnt/c, for one) only that user can read. It still has no
    capabilities and a read-only view of the input.

    service is the compose service to run it in: "tools" sees all of data/; "importer" (for the
    import, which unpacks the owner's archives) sees the folder it imports from, data/content and
    data/apk/base, while the keys, the backups, the database and what phones download are hidden
    from it.

    capture keeps its output (stdout and stderr in the result) instead of showing it, for a caller
    that reads what the module says it did.
    """
    global _tools_built
    # Build (or confirm up to date) once per command, quietly, instead of on every run.
    if not _tools_built:
        make_data_dirs()
        # Shown the first time (minutes), quiet when it only confirms the cache.
        build("tools", profile="tools")
        _tools_built = True
    env = dict(extra_env or {})
    if as_invoker:
        env.update(OPENDMTQ_UID=str(os.getuid()), OPENDMTQ_GID=str(os.getgid()))
        # The import writes data/content and data/apk/base; let the invoking user own them meanwhile.
        own_data_dirs(os.getuid(), os.getgid(), subs=("content", os.path.join("apk", "base")))
    r = compose("--profile", "tools", "run", "--rm", service,
                f"opendmtq_tools.{module}", *args, extra_env=env, check=False, capture=capture)
    if as_invoker:
        # Whatever it wrote goes back to the container user.
        own_data_dirs()
    return r


def run_bundle():
    """arm32/bundle.sh, with its output on the screen. Its exit status."""
    require_docker()
    return subprocess.run([os.path.join(ROOT, "arm32", "bundle.sh"), os.path.join(DATA, "apk", "arm32")], check=False).returncode


def container_state(service="server"):
    """'running', another docker state, or None when this copy has no such container."""
    require_docker()
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", container(service)],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def port_busy(port):
    """True when something on this machine already answers on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def edge_holds(port):
    """True when this copy's own edge proxy is what answers on the port."""
    r = subprocess.run(["docker", "port", container("edge"), "8790/tcp"], capture_output=True, text=True)
    return r.returncode == 0 and any(line.rsplit(":", 1)[-1].strip() == str(port) for line in r.stdout.splitlines())


def free_port(start):
    """The first port from `start` on that nothing answers on."""
    port = start
    while port < 65535 and port_busy(port):
        port += 1
    return port


# Where Windows keeps PowerShell, for when it is not on PATH: sudo resets PATH, and
# appendWindowsPath=false in /etc/wsl.conf leaves Windows out of it.
WINDOWS_POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


def powershell(script, timeout=60):
    """Run PowerShell on the Windows side of WSL; returns CompletedProcess or None if unavailable."""
    exe = shutil.which("powershell.exe") or (WINDOWS_POWERSHELL if os.path.isfile(WINDOWS_POWERSHELL) else None)
    if not exe:
        return None
    # PowerShell writes in the console's code page (949 on a Korean Windows, for one); ask for UTF-8
    # so names outside ASCII, like a profile folder's, come through. Anything else is replaced, not fatal.
    script = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; " + script
    try:
        r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return subprocess.CompletedProcess(r.args, r.returncode, r.stdout.decode("utf-8", "replace"),
                                       r.stderr.decode("utf-8", "replace"))


def _ps_text(text):
    """text as a PowerShell string literal."""
    return "'" + text.replace("'", "''") + "'"


def firewall_rule_present(port, internet):
    """True when the Windows rule for the port exists with the right scope; None when unknown."""
    r = powershell(f"$r = Get-NetFirewallRule -DisplayName '{firewall_rule_name(port)}' -EA SilentlyContinue | "
                   "? Enabled -eq 'True'; if ($r) { ($r | Get-NetFirewallAddressFilter).RemoteAddress } "
                   "else { 'none' }")
    if r is None or r.returncode != 0:
        return None
    scope = r.stdout.strip()
    # Exposed needs "Any"; LAN-only needs "LocalSubnet" (an "Any" rule would also work, but is wider).
    return scope == ("Any" if internet else "LocalSubnet")


def firewall_command(port=80, internet=False, remove=False, replaces=None):
    """cli/firewall.ps1 as one PowerShell command, with its parameters: the script as a script block, called with them as
    -File would pass them (its param() block takes them, its exit codes end the PowerShell that runs it). Its comment and
    blank lines are left out, the code as it is: the command goes on the elevated PowerShell's command line, through
    ShellExecute, whose parameters some Windows versions cut at 2,048 characters."""
    with open(os.path.join(ROOT, "cli", "firewall.ps1"), encoding="utf-8") as f:
        # Each line without the spaces around it (a line's ending backtick stays its last character).
        lines = [line.strip() for line in f.read().splitlines()]
    code = [line for line in lines if line and not line.startswith("#")]
    # Numbers made numbers here and switches by name: nothing typed reaches the command.
    params = ["-Port", str(int(port))]
    if internet:
        params.append("-Internet")
    if remove:
        params.append("-Remove")
    if replaces and int(replaces) != int(port):
        params += ["-Replaces", str(int(replaces))]
    return "& {\n" + "\n".join(code) + "\n} " + " ".join(params)


def run_firewall_script(port=80, internet=False, remove=False, replaces=None):
    """Run cli/firewall.ps1 elevated (Windows shows one UAC prompt). replaces: the port this server used until now.

    The script goes inside the elevated PowerShell's own command (-EncodedCommand), never as a file: a copy in the
    user's temp folder could be swapped by any program of the same user while Windows asks for permission, and the
    swap would run as administrator.

    Returns None on success, else what went wrong (with the way to do it by hand).
    """
    by_hand = "run cli/firewall.ps1 as administrator yourself"
    try:
        command = firewall_command(port, internet, remove, replaces)
    except OSError as e:
        return f"cannot read cli/firewall.ps1 ({e}); {by_hand}"
    # PowerShell takes an encoded command as Base64 of its UTF-16LE text: one argument, no quoting, nothing to read
    # from anywhere else.
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    script_args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]
    # The exit code comes back as text: WSL keeps only its low 8 bits, and PowerShell's own failures
    # (-196608 for a command it cannot start) would read as 0.
    r = powershell("try { $p = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden "
                   f"-ArgumentList {','.join(_ps_text(a) for a in script_args)}; 'exit ' + $p.ExitCode }} "
                   "catch { 'declined' }", timeout=300)
    if r is None:
        return f"cannot reach Windows PowerShell from here; {by_hand}"
    result = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    if result == "exit 0":
        return None
    if result == "declined":
        return f"Windows did not get administrator permission (declined?); {by_hand}"
    return f"cli/firewall.ps1 failed ({result or 'no answer from PowerShell'}); {by_hand}"
