"""OpenDMTQ's installer: the launcher's own dialogs around Velopack's setup.

Velopack's setup (bundled as velopack-setup.exe) does the work: it puts the launcher and the player in
%LocalAppData%\\OpenDMTQ.Client, makes the shortcuts and the uninstall entry, and keeps the update packages. Run with
--silent it shows nothing and asks nothing, so every question and every message comes from here instead, in the shape
of the game's popups like the launcher's: install, update, repair or go back a version, close a launcher that is open
first, wait while a game is running, and what went wrong if it failed. When it is done the launcher starts. It speaks
the launcher's language: the player's choice when a launcher has one saved, else the language Windows is shown in.

An installer a server's site handed out has that server on its end (preset.py): the dialogs name it, and the launcher
plays on it from its first start.

  OpenDMTQ-Setup.exe                         the dialogs
  OpenDMTQ-Setup.exe --silent [--no-start]   no dialog: install or update, then start the launcher
"""

import glob
import logging
import logging.handlers
import os
import re
import subprocess
import sys
import tempfile
import time

from opendmtq_client import __version__, i18n, preset

log = logging.getLogger("opendmtq_client.installer")

# Velopack's setup, next to this program inside the frozen installer (sys._MEIPASS) or given by a test.
SETUP_NAME = "velopack-setup.exe"
# How long Velopack's setup may take before the installer stops waiting for it.
SETUP_LIMIT = 300
# Velopack's logs of earlier runs kept in the temporary folder.
LOGS_KEPT = 5
# The installer's own log in the temporary folder (with the one before it, .1, past its size), and Velopack's setup's log
# of each run beside it, by the time it started: what Help's Delete all takes from there too (removal.leftovers).
LOG_NAME = "OpenDMTQ-setup.log"
RUN_LOG = "OpenDMTQ-setup-%s.log"


def log_folder():
    """Where the installer writes its logs and Velopack's setup's: the temporary folder (a test names its own)."""
    return tempfile.gettempdir()


def run_log():
    """A new run's log for Velopack's setup, named by the time it starts."""
    return os.path.join(log_folder(), RUN_LOG % time.strftime("%Y%m%d-%H%M%S"))


def is_log(name):
    """Whether a file in the log folder is one of the installer's: its own log and the one before it, or a run's."""
    run_start, run_end = RUN_LOG.split("%s")
    return (name == LOG_NAME or name.startswith(LOG_NAME + ".")
            or (name.startswith(run_start) and name.endswith(run_end)))


def app_dir():
    """Where Velopack installs for this Windows user: its package id's folder, apart from the player's data in
    %LOCALAPPDATA%\\OpenDMTQ, so that installing, updating or removing the program never touches that."""
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "OpenDMTQ.Client")


def installed_version(folder=None):
    """The version installed for this user (Velopack's current\\sq.version), or None."""
    path = os.path.join(folder or app_dir(), "current", "sq.version")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            found = re.search(r"<version>\s*([^<\s]+)\s*</version>", f.read())
    except OSError:
        return None
    return found.group(1) if found else None


def version_key(text):
    """A key that orders versions as Semantic Versioning does: 1.2.3-rc.1 < 1.2.3-rc.2 < 1.2.3 (build data after
    + is ignored)."""
    core, _, pre = (text or "0").partition("+")[0].partition("-")
    numbers = tuple(int(n) if n.isdigit() else 0 for n in (core.split(".") + ["0", "0"])[:3])
    if not pre:
        # A release comes after every pre-release of it.
        return numbers, 1, ()
    # Pre-release parts: numbers before words, numbers by value, words by their letters.
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return numbers, 0, parts


def launcher_open():
    """True while a launcher window is open (its mutex exists); False on other systems."""
    from opendmtq_client import mutex
    return mutex.exists(mutex.LAUNCHER)


def game_running():
    """True while a launcher says a game it started is running (playing.py)."""
    from opendmtq_client import playing
    return playing.running()


def setup_path():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.environ.get("OPENDMTQ_VELOPACK_SETUP") or os.path.join(base, SETUP_NAME)


def own_file():
    """The installer's own file, whose end may name a server: the program itself once frozen (OPENDMTQ_SETUP_FILE
    names one for the tests)."""
    return os.environ.get("OPENDMTQ_SETUP_FILE") or (sys.executable if getattr(sys, "frozen", False) else None)


def brought():
    """The server this installer is set up for ({"url", "name"}), or None for a release's own."""
    path = own_file()
    return preset.read(path) if path else None


def failure_line(log_path):
    """The last error Velopack wrote in its log, in its own words (None when there is none): for the installer's log,
    and for the dialog to say by its kind (i18n Words.fault), never as it is."""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = [line.strip() for line in f if "[ERROR]" in line]
    except OSError:
        return None
    if not lines:
        return None
    # "[12:00:13] [ERROR] Something": the message after the level.
    return lines[-1].split("[ERROR]", 1)[1].strip()[:300] or None


def start_launcher():
    """Start the installed launcher the way its shortcut does (Velopack's stub picks the current version)."""
    stub = os.path.join(app_dir(), "OpenDMTQ.exe")
    log.info("starting %s", stub)
    subprocess.Popen([stub], cwd=app_dir(), close_fds=True)


def run_setup(log_path):
    """Start Velopack's setup without a window; returns the process."""
    flags = 0x08000000 if sys.platform == "win32" else 0      # CREATE_NO_WINDOW
    return subprocess.Popen([setup_path(), "--silent", "--log", log_path], creationflags=flags, close_fds=True)


def language():
    """The language the dialogs speak: the launcher's (its player's choice, else Windows'), or Windows' when the
    launcher's settings cannot be read."""
    from opendmtq_client import state as st
    try:
        return st.LauncherState.load().language
    except st.StateError:
        # Settings the installer cannot read (the launcher asks about them at its own start): Windows' language.
        return st.system_language()


def _sentences(*parts):
    """Sentences joined by a space, the empty ones left out."""
    return " ".join(p for p in parts if p)


def plan(have, here, running, server=None, words=None):
    """What to ask, from the version installed (None: none), this installer's, whether a launcher is open, and the
    server this installer is set up for (None: a release's own), in `words`' language (English without).

    Returns (kind, tab, question, detail, action words, action), or None for "repair or open".
    action is what the work under way is called: install, update or back.
    """
    w = words or i18n.Words("en")
    closing = w("setup.closing") if running else ""
    # The server an installer from a site brings: the launcher plays on it from its first start.
    on = w("setup.for", name=server["name"]) if server else ""
    if have is None:
        return ("info", w("setup.tab"), w("setup.install.ask", v=here), _sentences(w("setup.install.detail"), on),
                w("setup.install"), "install")
    if version_key(have) < version_key(here):
        return ("info", w("setup.tab.update"), w("setup.update.ask", v=here),
                _sentences(w("setup.update.detail", have=have), on, closing), w("setup.update"), "update")
    if version_key(have) > version_key(here):
        return ("warn", w("setup.tab"), w("setup.back.ask"),
                _sentences(w("setup.back.detail", have=have, here=here), on, closing), w("setup.back", here=here),
                "back")
    return None


# The work under way, by action: the words of its tab and of its line (i18n setup.work.*).
WORK = ("install", "update", "repair", "back")


class Installer:
    """The installer's window: one dialog after another in a window of its own."""

    def __init__(self):
        from opendmtq_client import dialogs
        self.dialogs = dialogs
        # The launcher's language, decided once for every dialog of this run.
        lang = language()
        self.words = i18n.Words(lang)
        self.root, self.ui = dialogs.window_root(title=self.words("setup.window"), language=lang)
        self.dialog = None
        self.process = None
        self.started_at = None
        self.action = "install"
        # The failure on show (why, title), shown again after its log was opened.
        self.failure = None
        # The server this installer brings, read once from its own file.
        self.server = brought()
        self.log_path = run_log()
        self.root.protocol("WM_DELETE_WINDOW", self._close_window)
        self.ask()

    def show(self, kind, title, message, detail, buttons=(), default=0, cancel=None, progress=False):
        """Replace the dialog on show with another, the window fitted to it."""
        from opendmtq_client import art
        if self.dialog is not None:
            self.dialog.on_close = None
            self.dialog.close(None)
        self.dialog = self.dialogs.Dialog(self.root, self.ui, kind, title, message, detail, buttons, default=default,
                                          cancel=cancel, progress=progress,
                                          window=lambda w, h: art.backdrop(w, h, self.ui.scale), on_close=self._answered)
        self.dialogs.fit(self.root, self.ui, self.dialog)

    def ask(self):
        have, running = installed_version(), launcher_open()
        log.info("installed %s, this %s, launcher open %s, set up for %s", have, __version__, running,
                 self.server["url"] if self.server else "no server")
        w = self.words
        if have is not None and game_running():
            # Velopack replaces the player's files: the game playing from them would lose them mid-song.
            self.show("warn", w("setup.tab"), w("setup.game"), w("setup.game.detail"),
                      [(w("setup.close"), "cancel", "neutral"), (w("setup.again"), "again", "home")], default=1,
                      cancel="cancel")
            return
        asked = plan(have, __version__, running, self.server, w)
        if asked is None:
            detail = _sentences(w("setup.repair.detail"), w("setup.for", name=self.server["name"]) if self.server else "",
                                w("setup.repair.closing") if running else "")
            self.show("info", w("setup.tab"), w("setup.installed", v=__version__), detail,
                      [(w("setup.repair"), "repair", "neutral"), (w("setup.open"), "open", "home")], default=1,
                      cancel="cancel")
            return
        kind, tab, question, detail, words, action = asked
        self.show(kind, tab, question, detail,
                  [(w("setup.cancel"), "cancel", "neutral"), (words, action, "home" if kind == "info" else kind)],
                  default=1, cancel="cancel")

    def _hand_over(self):
        """The server this installer brings, left for the launcher to take at its next start."""
        if self.server is None:
            return
        try:
            preset.hand_over(self.server)
            log.info("left the server %s for the launcher", self.server["url"])
        except OSError:
            # Without it the launcher still starts: its guide asks for the server's address instead.
            log.exception("could not leave the server for the launcher")

    def _answered(self, value):
        if value in WORK:
            self.install(value)
        elif value == "again":
            self.ask()
        elif value == "open":
            self._hand_over()
            self._start_or_say(wait=0)
        elif value == "log":
            try:
                os.startfile(self.log_path)
            except (AttributeError, OSError):
                log.exception("could not open %s", self.log_path)
            # The window stays, with the same failure and its Try again, while the log is read.
            self.failed(*self.failure)
        else:
            self.root.destroy()

    def _start_or_say(self, wait=1400):
        """Start the launcher and close (after `wait` ms, time to read the end); if it cannot start, say so
        instead of leaving an empty window."""
        try:
            start_launcher()
        except OSError as e:
            # The system's own words in the log; the dialog says why by its kind, when it is one.
            log.exception("could not start the launcher")
            self.failed(self.words.failed("setup.not_started.detail", e, network=False),
                        title=self.words("setup.not_started"))
            return
        self.root.after(wait, self.root.destroy)

    def install(self, action):
        self.action = action
        w = self.words
        # Before the launcher can start: it takes the server at its first start.
        self._hand_over()
        self.show("info", w("setup.work." + action), w("setup.work.%s.line" % action, v=__version__),
                  w("setup.work.detail"), progress=True)
        try:
            self.process = run_setup(self.log_path)
        except OSError as e:
            # The system's own words in the log; the dialog says why by its kind, when it is one.
            log.exception("could not start Velopack's setup")
            self.failed(self.words.failed("setup.no_setup", e, network=False))
            return
        self.started_at = time.time()
        self.root.after(100, self._wait)

    def _wait(self):
        code = self.process.poll()
        if code is None:
            if time.time() - self.started_at > SETUP_LIMIT:
                # A setup that hangs never ends on its own: stop it and say so.
                log.error("Velopack's setup did not finish in %d s", SETUP_LIMIT)
                self.process.kill()
                self.failed(self.words("setup.too_long", m=SETUP_LIMIT // 60))
                return
            self.root.after(100, self._wait)
            return
        log.info("Velopack's setup ended with %s", code)
        found = installed_version()
        if code != 0:
            # Velopack's last error line, in its own (English) words, goes to this log; the dialog says it by its kind
            # in the installer's language (a full disk, a file in use, no permission), else only that it failed and
            # where Velopack's log is. Its setup asks nothing over the network: no network kind is read into it.
            line = failure_line(self.log_path)
            log.error("Velopack's setup failed: %s", line or "no error line in its log")
            self.failed(self.words.fault(line, network=False))
            return
        if found != __version__:
            self.failed(self.words("setup.wrong_version", found=found, here=__version__))
            return
        self.show("info", self.words("setup.tab.done"), self.words("setup.done", v=__version__),
                  self.words("setup.starting"), progress=True)
        self._start_or_say()

    def failed(self, why, title=None):
        """What went wrong (`why`: plain words, or "" when there is no more to say than the title), with Try again as
        the main answer and the way to Velopack's log when there is one."""
        w = self.words
        title = title or w("setup.failed")
        self.failure = (why, title)
        if os.path.isfile(self.log_path):
            # Why, then where the log is, each on its own line.
            detail = "\n".join(part for part in (why, w("setup.failed.log", path=self.log_path)) if part)
            self.show("error", w("setup.tab"), title, detail,
                      [(w("setup.close"), "close", "neutral"), (w("setup.open_log"), "log", "neutral"),
                       (w("setup.retry"), "again", "home")], default=2, cancel="close")
        else:
            self.show("error", w("setup.tab"), title, why or None,
                      [(w("setup.close"), "close", "neutral"), (w("setup.retry"), "again", "home")], default=1,
                      cancel="close")

    def _close_window(self):
        if self.process is not None and self.process.poll() is None:
            # Velopack is writing files: the window stays until it is done (or the time limit stops it).
            return
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def _logging():
    """The installer's own log next to Velopack's, in the temporary folder, with a size cap; Velopack's logs of
    earlier runs beyond the last few are removed."""
    folder = log_folder()
    handler = logging.handlers.RotatingFileHandler(os.path.join(folder, LOG_NAME), maxBytes=200_000,
                                                   backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger("opendmtq_client")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Each run's name starts with its year (RUN_LOG), so the oldest come first.
    runs = sorted(glob.glob(os.path.join(folder, RUN_LOG % "2*")))
    for old in runs[:-LOGS_KEPT]:
        try:
            os.remove(old)
        except OSError:
            pass


def _close_splash():
    """The picture PyInstaller shows while the installer unpacks itself goes as soon as Python runs."""
    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Sharp at any Windows scaling, as the launcher: set before the first dialog opens.
    from opendmtq_client import dpi
    dpi.aware()
    _close_splash()
    _logging()
    log.info("OpenDMTQ setup %s: %s", __version__, " ".join(argv))
    if "--silent" in argv:
        # No dialog: Velopack's own silent install, then the launcher, as the dialogs would do; the server this
        # installer brings goes to the launcher first.
        server = brought()
        if server is not None:
            try:
                preset.hand_over(server)
            except OSError:
                log.exception("could not leave the server for the launcher")
        if game_running():
            # As the dialog does: Velopack would replace the player's files under the game.
            log.error("a game is running: the silent install waits for it to close (run it again then)")
            return 3
        path = run_log()
        setup = None
        try:
            setup = run_setup(path)
            code = setup.wait(timeout=SETUP_LIMIT)
            if code == 0 and "--no-start" not in argv:
                start_launcher()
        except (OSError, subprocess.TimeoutExpired):
            log.exception("the silent install failed")
            if setup is not None and setup.poll() is None:
                # Past the time limit: Velopack's setup is stopped, not left running behind a finished installer.
                setup.kill()
            return 2
        return code
    Installer().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
