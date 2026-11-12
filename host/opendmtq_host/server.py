"""The running server: Apache with PHP, the admin pages and the database keeper, watched and started again."""

import glob
import json
import logging
import logging.handlers
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from opendmtq_cli import env
from .paths import ADMIN_WAIT, APP, CLI, DATA, LOGS, PYTHON, ROOT, RUN, START_WAIT, WINDOWS
from .output import die, say, warn
from .programs import programs
from .settings import admin_port, listen_port, require_settings, settings
from .folders import php_command, server_env, tool, tools_env
from .apache import write_configs

# The PHP program that keeps one database handle open while the server runs (server/entrypoint.sh says why: a save
# then waits for the disk once instead of twice).
KEEPER = ('$db = new SQLite3($argv[1]); $db->busyTimeout(5000); '
          '@$db->querySingle("SELECT 1 FROM sqlite_master LIMIT 1"); while (true) { sleep(86400); }')


def end_with_this_program():
    """Make every program started from here end when this one ends, however it ends.

    Windows: this process joins a job object that ends all of its processes when the last handle to it closes, which
    happens when this process ends, its window closed included; the programs started later are in it too, Apache's
    worker process with them, which would otherwise keep the port. Linux asks the kernel per program instead (see
    die_with_parent); macOS has neither, and a start ends what an earlier run left (end_leftovers)."""
    if not WINDOWS:
        return
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Handles are 64 bits: without these declarations ctypes passes and returns them as 32-bit ints, and they break.
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.SetInformationJobObject.restype = wintypes.BOOL
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.AssignProcessToJobObject.restype = wintypes.BOOL

    class Basic(ctypes.Structure):
        # JOBOBJECT_BASIC_LIMIT_INFORMATION
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION: the basic limits, IO counters (six 64-bit counts) and memory figures.
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_ulonglong * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    job = k32.CreateJobObjectW(None, None)
    info = Extended()
    # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    info.BasicLimitInformation.LimitFlags = 0x2000
    # JobObjectExtendedLimitInformation is information class 9.
    if not job or not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) \
            or not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
        logging.warning("could not tie the server's programs to this window (error %d)", ctypes.get_last_error())
    # The handle stays open (and the job alive) for as long as this process runs.
    end_with_this_program.job = job


def die_with_parent():
    """Linux: the program being started gets SIGTERM when this one ends, even when this one is killed outright."""
    import ctypes
    # prctl(PR_SET_PDEATHSIG, SIGTERM)
    ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM, 0, 0, 0)


def child_setup():
    """In a program being started, before it runs (Linux and macOS). A process group of its own: Apache's shutdown
    signals its whole group, which would otherwise be this program and every other one too (a restart would stop the
    server), and Ctrl+C in a terminal then reaches this program alone, which stops the others in order. On Linux it
    also ends with this program."""
    os.setpgid(0, 0)
    if sys.platform.startswith("linux"):
        die_with_parent()


def spawn(cmd, env_vars, log):
    """Start one of the server's programs in the background, its output into the log. It shares this program's
    window on Windows, so Ctrl+C and closing the window reach it as well."""
    extra = {} if WINDOWS else {"preexec_fn": child_setup}
    return subprocess.Popen(cmd, env=env_vars, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **extra)


def stop_process(p, name, timeout=15, asked=True):
    """Ask a program to stop, and end it when it does not. On Windows nothing asks it: Ctrl+C and the window's closing
    reach it as they reach this program (asked), and a stop of this program's own (a restart) ends it at once."""
    if p is None or p.poll() is not None:
        return
    try:
        if not WINDOWS:
            # SIGTERM on Linux and macOS: Apache stops its workers, the builder notes where it stopped.
            p.send_signal(signal.SIGTERM)
            p.wait(timeout)
        elif asked:
            p.wait(5)
        else:
            raise subprocess.TimeoutExpired(p.args, 0)
    except (OSError, subprocess.TimeoutExpired):
        end_tree(p)
    logging.info("%s stopped", name)


def end_tree(p):
    """End a program and the programs it started. On Windows Apache's worker is a process of its own that outlives its
    parent and keeps the port: taskkill /T ends both."""
    if WINDOWS:
        # CREATE_NO_WINDOW: no console flashing up for it.
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=0x08000000)
    else:
        p.kill()
    try:
        p.wait(5)
    except subprocess.TimeoutExpired:
        # taskkill could not: the process itself at least.
        p.kill()
        p.wait(5)


def end_leftovers():
    """End the programs an earlier run left behind when it was killed outright (macOS has nothing like the job object
    or Linux's parent death signal): Apache by its pid file, the others by the list a run keeps."""
    if WINDOWS:
        return
    for pid in leftover_pids():
        try:
            os.kill(pid, signal.SIGTERM)
            logging.info("ended process %d, left by an earlier run", pid)
        except OSError:
            pass


def leftover_pids():
    """The processes an earlier run noted (run/children.json, Apache's pid file) that still run this install's
    programs."""
    pids = []
    try:
        with open(os.path.join(RUN, "children.json"), encoding="utf-8") as f:
            pids += [int(p) for p in json.load(f)]
    except (OSError, ValueError, TypeError):
        pass
    try:
        with open(os.path.join(RUN, "httpd.pid"), encoding="ascii") as f:
            pids.append(int(f.read().strip()))
    except (OSError, ValueError):
        pass
    # Only processes whose command names this install's files: a pid may have been reused by anything since.
    return [p for p in dict.fromkeys(pids) if p != os.getpid() and ROOT in command_of(p)]


def command_of(pid):
    """The command line of a process, or "" when there is none (or it cannot be read)."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        pass
    try:
        # macOS has no /proc.
        return subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, encoding="utf-8",
                              errors="replace").stdout
    except OSError:
        return ""


def health(values, timeout=3):
    """The server's health page, as a dict, or None when nothing answers."""
    try:
        url = f"http://127.0.0.1:{listen_port(values)}/opendmtq/health.php"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        # 503: up, and saying what is missing.
        try:
            return json.loads(e.read())
        except ValueError:
            return None
    except (OSError, ValueError):
        return None


def wait_healthy(values, timeout=START_WAIT, gone=None):
    """Wait for the server to answer; its health, or None when it never did. gone: asked at each look, True when what
    was started has ended, so that nobody waits out the time for a server that is no longer coming."""
    end = time.time() + timeout
    while time.time() < end:
        h = health(values)
        if h is not None:
            return h
        if gone and gone():
            return None
        time.sleep(1)
    return None


def builder_outcome(code):
    """The window's line for the app builder's end at a start, in words: a first start has no game files yet, and the
    builder ending without them is the wait for them (the setup's first step imports them, and the app is built then),
    never a failure to show by its exit status."""
    if code == 0:
        # Built, or already the app for this address (build.json says which; the admin pages show it).
        return "the phone app is ready"
    if not glob.glob(os.path.join(DATA, "apk", "base", "*.apk")):
        # No game client to build from: the import brings it (setup.py have_base_apk() looks the same way).
        return "the phone app waits for the game files: it is built once they are imported"
    try:
        # The builder's own reason, as the admin pages show it, from the status it wrote as it ended.
        with open(os.path.join(DATA, "apk", "out", "build.json"), encoding="utf-8") as f:
            reason = json.load(f).get("error")
    except (OSError, ValueError, AttributeError):
        # No status to read: the log has the builder's own lines.
        reason = None
    # Where the builder's own lines went (Server.log), for the details the window has no room for.
    where = os.path.join(LOGS, "programs.log")
    if reason:
        return f"the phone app could not be built: {reason} (the details are in {where})"
    return f"the phone app could not be built (the details are in {where})"


def announce_when_up(server, open_the_setup):
    """Say when the server first answers, and only then open the setup in the browser (its pages take their look from
    the server). The first start can be slow, as an antivirus looks at every new program, so this goes on looking for
    as long as the server runs and says once that it still does. It runs beside Server.watch(), which meanwhile starts
    again a program that stops, and gives up when one keeps stopping."""
    started = time.time()
    said = False
    # Until asked to stop, a look a second (each may take as long as health() allows).
    while not server.stopping.wait(1):
        # The settings as they are now: a restart may have changed them.
        values = server.values
        if health(values) is not None:
            logging.info("serving http://%s/ (admin pages: http://localhost:%d/opendmtq/admin/)",
                         values["PUBLIC_HOST"], admin_port(values))
            if open_the_setup:
                # The setup in the browser, signed in by a one-time link: the files, the address, the players, the app.
                open_setup(values)
            return
        # Once, past the time a start usually takes: what is going on, and where to read more.
        if not said and time.time() - started > START_WAIT:
            said = True
            logging.warning("no answer from the server after %d s, still waiting. The first start can be slow while an "
                            "antivirus checks Apache; the details are in %s", START_WAIT,
                            os.path.join(LOGS, "server.log"))


class Server:
    """The running server: Apache with PHP, the admin pages and the database keeper, watched and started again when one
    of them stops by itself."""

    def __init__(self, values, found):
        self.values, self.found = values, found
        self.procs = {}
        # The app builder's run, while there is one (a restart ends it: its address is no longer the server's).
        self.builder = None
        # The program that kept stopping when watch() gave up on it; cmd_run says so once everything has stopped.
        self.gave_up = None
        # True when the admin pages asked for the stop (stop.request in the run folder).
        self.stopped_by_page = False
        self.stopping = threading.Event()
        # Every program's output goes to one log beside the server's, kept to 3 files of 10 MB.
        os.makedirs(LOGS, exist_ok=True)
        self.log = open(os.path.join(LOGS, "programs.log"), "ab", buffering=0)

    def commands(self):
        """The programs to run, by name: (command, environment)."""
        senv = server_env(self.values, self.found)
        tenv = tools_env(self.values, self.found)
        db = os.path.join(DATA, "state", "dmtq.db3")
        conf = os.path.join(RUN, "httpd.conf")
        httpd = [self.found["httpd"], "-f", conf] + ([] if WINDOWS else ["-DFOREGROUND"])
        admin = PYTHON + ["-m", "waitress", f"--listen=127.0.0.1:{admin_port(self.values)}", "--threads=8",
                          "opendmtq_tools.admin:app"]
        return {
            "keeper": (php_command(self.found) + ["-r", KEEPER, db], senv),
            "admin": (admin, tenv),
            "apache": (httpd, senv),
        }

    def prepare(self):
        """What a start does before the server runs (server/entrypoint.sh in the image): the database, the song list,
        the live view's folders, the download sign-in key, Apache's configuration."""
        senv = server_env(self.values, self.found)
        db = os.path.join(DATA, "state", "dmtq.db3")
        # Apache's configuration first: on Windows it brings the php.ini the database's setup needs.
        write_configs(self.values, self.found)
        # The site's document root: empty, every path has its own door (site.conf). Git keeps no empty folder, so a
        # clone has none; the image makes its own.
        os.makedirs(os.path.join(APP, "server", "game", "public"), exist_ok=True)
        # The database: created on a first start, its journal mode picked for this disk, repairs and additions.
        r = subprocess.run(php_command(self.found) + [os.path.join(APP, "server", "game", "bin", "setup-db.php"), db],
                           env=senv, stdout=self.log, stderr=subprocess.STDOUT)
        if r.returncode != 0:
            die(f"the database could not be prepared (see {os.path.join(LOGS, 'programs.log')})")
        # The song list and the client's tables, from what was imported and added.
        tool("songs", values=self.values, found=self.found)
        # The live view's window starts empty; the recordings stay.
        live = os.path.join(DATA, "state", "live")
        shutil.rmtree(live, ignore_errors=True)
        os.makedirs(live, exist_ok=True)
        os.makedirs(os.path.join(DATA, "state", "live-rec"), exist_ok=True)
        # The key that signs the download sign-in cookie, made once (portal/auth.php): readable by this user only, as
        # whoever reads it could sign in to the site as anyone. Apache runs as this user, and still reads it.
        key = os.path.join(DATA, "state", "download.key")
        if not os.path.isfile(key) or os.path.getsize(key) == 0:
            env.write_private(key, secrets.token_hex(32))
        elif not WINDOWS:
            # One made before it was kept so: narrowed now (Windows has no such modes; its folder keeps it).
            os.chmod(key, 0o600)
        # Apache checks its configuration before it starts: a problem is reported here, readable.
        # Apache writes in the system's code page, this program reads UTF-8: its message must not stop this one.
        r = subprocess.run([self.found["httpd"], "-t", "-f", os.path.join(RUN, "httpd.conf")], env=senv,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            die("Apache refused its configuration: " + (r.stderr or r.stdout).strip())

    def start(self):
        """Start every program; the app builder runs once beside them."""
        for name, (cmd, e) in self.commands().items():
            self.procs[name] = spawn(cmd, e, self.log)
            logging.info("%s started (pid %d)", name, self.procs[name].pid)
        self.note_children()
        # The phone app for this address, built when it is missing or out of date (the builder decides).
        threading.Thread(target=self.build_app, daemon=True).start()

    def build_app(self):
        """The app builder, as at every start with Docker Compose: it writes data/apk/out/build.json as it goes."""
        self.builder = spawn(PYTHON + ["-m", "opendmtq_tools.builder"], tools_env(self.values, self.found), self.log)
        logging.info(builder_outcome(self.builder.wait()))

    def watch(self):
        """Until asked to stop: a program that stopped by itself is started again, at most five times a minute."""
        restarts = []
        while not self.stopping.wait(2):
            # Stop, asked on the admin pages (Maintenance): as Ctrl+C or the window's closing would.
            stop = os.path.join(RUN, "stop.request")
            if os.path.exists(stop):
                try:
                    os.remove(stop)
                except OSError:
                    pass
                logging.info("stopping, as asked on the admin pages")
                self.stopped_by_page = True
                self.stopping.set()
                break
            asked = os.path.join(RUN, "restart.request")
            if os.path.exists(asked):
                os.remove(asked)
                self.restart()
                continue
            for name, (cmd, e) in self.commands().items():
                p = self.procs.get(name)
                if p is not None and p.poll() is None:
                    continue
                # Restarts of the last minute only.
                restarts = [t for t in restarts if time.time() - t < 60]
                if len(restarts) >= 5:
                    self.gave_up = name
                    self.stopping.set()
                    break
                restarts.append(time.time())
                logging.warning("%s stopped (status %s); starting it again", name, p.returncode if p else "?")
                self.procs[name] = spawn(cmd, e, self.log)
                self.note_children()

    def restart(self):
        """Every program stopped and started again with the settings in .env as they are now (the setup pages changed
        the address): the app builder then makes the app for it."""
        logging.info("starting again with the new settings")
        # A build for the old address first: the new start builds for the new one.
        stop_process(self.builder, "app builder", asked=False)
        for name in ("apache", "admin", "keeper"):
            stop_process(self.procs.get(name), name, asked=False)
        self.values = settings()
        self.prepare()
        self.start()
        logging.info("serving http://%s/", self.values["PUBLIC_HOST"])

    def note_children(self):
        """The programs' processes, for the next start to end should this run be killed outright (end_leftovers)."""
        with open(os.path.join(RUN, "children.json"), "w", encoding="utf-8") as f:
            json.dump([p.pid for p in self.procs.values()], f)

    def stop(self):
        """Stop every program, Apache first (no new requests), the database keeper last."""
        self.stopping.set()
        # On Windows Ctrl+C and the window's closing reach every program, as they reach this one; a stop asked on the
        # admin pages reaches none of them, so they are ended at once rather than waited for.
        asked = not self.stopped_by_page
        for name in ("apache", "admin", "keeper"):
            stop_process(self.procs.get(name), name, asked=asked)
        # A build part-way stops too (it says so in build.json), rather than run on without the server.
        stop_process(self.builder, "app builder", asked=asked)
        self.log.close()


def pid_file():
    """Where a server started in the background notes its process."""
    return os.path.join(RUN, "host.pid")


def running_pid():
    """The process of this install's running server, or None."""
    try:
        with open(pid_file(), encoding="ascii") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    if WINDOWS:
        # tasklist answers for a process that exists; there is no signal 0 on Windows. It answers in Windows' language
        # and code page, this program reads UTF-8: only the number is looked at, so the rest may come through as it will.
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
        return pid if str(pid) in out else None
    # A process of this program, not whatever got the number since.
    return pid if "opendmtq_host" in command_of(pid) else None


def setup_logging(to_file):
    """This program's own messages: to the terminal, or (in the background) to data/state/logs/host.log, kept to 3
    files of 10 MB."""
    os.makedirs(LOGS, exist_ok=True)
    if to_file:
        handler = logging.handlers.RotatingFileHandler(os.path.join(LOGS, "host.log"), maxBytes=10 * 1024 * 1024,
                                                       backupCount=2, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def check_address(values):
    """Warn when the local network address phones use is no longer this computer's: a router may hand out a new one
    after a restart, and the players' app still calls the old one."""
    host, port = env.split(values["PUBLIC_HOST"])
    now = env.detect_host()
    if not env.is_lan_only(values["PUBLIC_HOST"]) or not now or now == host or env.check_host(now) or env.has_address(host):
        return
    say("")
    warn(f"this computer's address is now {now}, but the players' app calls {host}. To move the server, run "
         f"{CLI} host {env.join(now, port)} (the app is built again; players install it over the old one). A fixed "
         "address for this computer in the router's settings (a DHCP reservation) keeps it from changing.")
    say("")


def check_folder():
    """The install's folder must be writable (data/ is in it); on Windows, better outside OneDrive."""
    probe = os.path.join(ROOT, ".write-test")
    try:
        with open(probe, "w", encoding="ascii") as f:
            f.write("ok")
        os.remove(probe)
    except OSError:
        die(f"OpenDMTQ cannot write in {ROOT}. Move the OpenDMTQ folder to one of your own (for example "
            "C:\\OpenDMTQ or your Documents) and start it there.")
    if WINDOWS and "onedrive" in ROOT.lower():
        warn("OpenDMTQ is in a OneDrive folder: OneDrive may hold its database while it syncs. A folder outside "
             "OneDrive, such as C:\\OpenDMTQ, is safer.")


def cmd_run(args, values=None, found=None):
    """Run the server in the foreground until Ctrl+C, a stop signal or (Windows) the window closing."""
    found = found or programs()
    values = values or require_settings()
    check_folder()
    if running_pid() and running_pid() != os.getpid():
        die("OpenDMTQ is already running in another window: use that one, or close it first" if WINDOWS else
            f"the server already runs ({CLI} stop stops it)")
    setup_logging(getattr(args, "log_to_file", False))
    check_address(values)
    # What an earlier run left, and this run's programs tied to it.
    end_leftovers()
    end_with_this_program()
    # What the admin pages asked of an earlier run that ended before it read it (its window closed at once): not this
    # run's to do, or a stop asked then would end this run as it starts.
    for left in ("stop.request", "restart.request"):
        try:
            os.remove(os.path.join(RUN, left))
        except OSError:
            pass
    with open(pid_file(), "w", encoding="ascii") as f:
        f.write(str(os.getpid()))
    server = Server(values, found)
    server.prepare()
    server.start()
    # SIGTERM (systemd, launchd, stop) ends the run like Ctrl+C.
    if not WINDOWS:
        signal.signal(signal.SIGTERM, lambda *_: server.stopping.set())
    # The first answer is awaited beside the watch, in a thread that ends with the first answer or with the server.
    threading.Thread(target=announce_when_up, args=(server, getattr(args, "open_setup", False)), daemon=True).start()
    try:
        server.watch()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        try:
            os.remove(pid_file())
        except OSError:
            pass
    if server.stopped_by_page:
        say("Stopped from the admin pages. " + ("Start OpenDMTQ.exe to run it again." if WINDOWS else
                                                 f"{CLI} start runs it again."))
    if server.gave_up:
        # Why the server is gone, and what usually causes it. die() keeps the Windows window open to read it, and the
        # command that started a background server shows this line from the log.
        cause = (f"Often another program holds port {listen_port(values)} (another web server, Skype) or an antivirus "
                 "blocks Apache. " if server.gave_up == "apache" else "")
        die(f"{server.gave_up} keeps stopping. {cause}The details are in {os.path.join(LOGS, 'server.log')} and "
            f"{os.path.join(LOGS, 'programs.log')}")
    return 0


def setup_link(values):
    """A one-time link that opens the setup pages signed in: its key goes into the run folder, where they take it once
    (it works from this PC only, for an hour)."""
    key = secrets.token_urlsafe(24)
    # Readable by this user only: for an hour it opens the setup signed in, to whoever can read it on this PC.
    env.write_private(os.path.join(RUN, "signin.token"), key)
    return f"http://localhost:{admin_port(values)}/opendmtq/admin/setup/start?key={key}"


def admin_answers(values):
    """True when the admin pages answer: the setup's question about which process runs, which needs no sign-in."""
    try:
        url = f"http://127.0.0.1:{admin_port(values)}/opendmtq/admin/setup/ping"
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except (OSError, ValueError):
        return False


def open_setup(values):
    """The setup pages in this computer's browser, with their one-time link and the way in from another computer
    written out as well: a browser may say it opened and show nothing (a session over SSH, a screen no longer there)."""
    # The pages start beside Apache, which answered first: a browser that came now could find nobody there. A short
    # wait at most, since the link printed below still works once they are up.
    for _ in range(ADMIN_WAIT):
        if admin_answers(values):
            break
        time.sleep(1)
    url = setup_link(values)
    say("")
    say("Finish the setup in the browser: the game's files, the address, the players' accounts and the app.")
    # A browser only where one can show: Windows, macOS, or a desktop session on Linux. Without one, Python would start
    # a text browser in this terminal.
    if WINDOWS or sys.platform == "darwin" or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        import webbrowser
        webbrowser.open(url)
    say(f"If no browser opened, open this link in one on this computer (it works once, for an hour): {url}")
    say(f"From another computer: http://{values['PUBLIC_HOST']}/opendmtq/admin/setup, user "
        f"{values.get('ADMIN_USER') or 'admin'}, password {values.get('ADMIN_PASSWORD')} (kept in .env).")
