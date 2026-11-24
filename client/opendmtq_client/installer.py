"""OpenDMTQ's installer: the launcher's own window around Velopack's setup and uninstaller.

Velopack's setup (bundled as velopack-setup.exe) does the install's work: it puts the launcher and the player in
%LocalAppData%\\OpenDMTQ.Client, makes the shortcuts and the uninstall entry, and keeps the update packages. Run with
--silent it shows nothing and asks nothing, so every question and every message comes from here instead, in the
launcher's look (setup_window.py): on a PC without OpenDMTQ, Install; on one with it, what to do: open it, repair it,
update it (or go back to this installer's older version), or uninstall it, with the data kept or deleted, each with its
size. The work shows its progress as Velopack does it (its log and the program's folder), and ends on a page that says
what came of it. It speaks the launcher's language: the player's choice when a launcher has one saved, else the
language Windows is shown in.

Windows' Settings, Apps opens the same uninstall (uninstall_main), from a copy of the launcher outside the program's
folder (removal.start_uninstall_window); Velopack's uninstaller underneath, with nothing on screen of its own.

An installer a server's site handed out has that server on its end (preset.py): the install page names it, and the
launcher plays on it from its first start.

  OpenDMTQ-Setup.exe                         the window
  OpenDMTQ-Setup.exe --silent [--no-start]   no window: install or update, then start the launcher
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

from opendmtq_client import __version__, i18n, installed, preset

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
        # utf-8-sig and any line ends: a file saved again by Notepad starts with a byte order mark and ends its lines
        # with CR LF.
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            found = re.search(r"<version>\s*([^<\s]+)\s*</version>", f.read())
    except OSError:
        return None
    # Quotes round it (an edit by hand) are no part of the version.
    version = found.group(1).strip("\"'") if found else None
    return version or None


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


def own_entry():
    """Windows' entry for the program just installed made OpenDMTQ's own (installed.own_entry: its uninstall opens the
    installer's own), a failure in the log only: the install itself is done and good either way."""
    try:
        installed.own_entry(app_dir())
    except Exception:  # noqa: BLE001  (the registry refusing: Velopack's own uninstall then, nothing else)
        log.exception("could not make Windows' uninstall of OpenDMTQ its own")


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


# The steps Velopack's setup goes through, as its log says them (each a line's start or a part of it), and the share of
# the bar each step starts at: getting ready, copying the program (most of the time: the bar follows the files as they
# land), making the shortcuts, finishing (the install hook).
SETUP_STEPS = (("ready", 0.0, ()),
               ("copy", 0.06, ("Extracting Update.exe", "Extracting stub", "Copying nupkg", "Extracting ")),
               ("shortcuts", 0.92, ("Creating shortcuts",)),
               ("finish", 0.96, ("Starting process install hook", "Running --veloapp-install hook")))
# The work the installer does with Velopack's setup, by action: the words of its line (i18n setup.work.<action>.line).
WORK = ("install", "update", "repair", "back")
# The steps down the window's column (i18n setup.step.<key>) and the stages of the work under way (setup.stage.<key>).
STEP_KEYS = ("ready", "install", "choose", "repair", "update", "open", "data", "uninstall", "done")
STAGE_KEYS = tuple(name for name, _start, _marks in SETUP_STEPS) + ("remove", "data", "logs")
# How often the window looks at the work (ms), and how long the program's folder may take to go after Velopack's
# uninstaller ends (seconds): it removes the folder a few seconds after itself.
POLL, FOLDER_GONE = 150, 60
# How often a page looks at the PC's state again (ms): a launcher or a game opened or closed, another version installed.
WATCH = 1000


def maintenance(have, here):
    """What a PC with OpenDMTQ `have` installed is offered by this installer of version `here`, in order, the first
    chosen at first: Update first when this installer is newer (no Repair then: it would update); Open first otherwise,
    then Repair for the same version, or going back to this installer's older one; Uninstall last."""
    if version_key(here) > version_key(have):
        return ["update", "open", "uninstall"]
    if version_key(here) < version_key(have):
        return ["open", "back", "uninstall"]
    return ["open", "repair", "uninstall"]


def server_words(server):
    """The server an installer brings, as its Install page names it: its name and its address after it, or its address
    alone when it has no name of its own (a site without SERVER_NAME calls itself by its address, which was said twice:
    "192.168.1.10:8791  ·  http://192.168.1.10:8791")."""
    from opendmtq_client import state as st
    return "%s  ·  %s" % (server["name"], server["url"]) if st.has_own_name(server) else server["url"]


def path_lines(font, path, room):
    """A path as lines no wider than `room` pixels in `font` (a Tk font), each broken after a separator (\\ or /), a
    folder's name kept whole; a name wider than the room alone has a line of its own (Tk then wraps it where it must)."""
    # The path's parts, each with the separator after it, and the last part.
    parts = re.findall(r"[^\\/]*[\\/]|[^\\/]+$", path)
    lines, line = [], ""
    for part in parts:
        if line and font.measure(line + part) > room:
            # The part goes on the next line: this one ends after a separator.
            lines.append(line)
            line = part
        else:
            line += part
    lines.append(line)
    return "\n".join(lines)


class SetupLog:
    """Where Velopack's setup is, read from its log as it writes it: the step it is on (SETUP_STEPS), how big the
    program is once installed (its "this package requires N MB"), and the size of its package inside the installer (the
    "length" of its bundle), so that the copy's share follows the files landing in the program's folder."""

    def __init__(self, path):
        self.path, self.offset, self.rest = path, 0, ""
        self.step, self.required, self.bundle = 0, None, None

    def read(self):
        """The lines written since the last read: the step and the sizes they say. Returns the step's index."""
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                data = f.read()
                self.offset = f.tell()
        except OSError:
            # Not written yet: the setup is still starting.
            return self.step
        text = self.rest + data.decode("utf-8", "replace")
        lines = text.split("\n")
        # A line not ended yet waits for the rest of it.
        self.rest = lines.pop()
        for line in lines:
            found = re.search(r"this package requires ([0-9.]+) MB", line)
            if found:
                self.required = float(found.group(1)) * (1 << 20)
            found = re.search(r"Bundle offset = \d+, length = (\d+)", line)
            if found:
                self.bundle = int(found.group(1))
            for i, (_name, _start, marks) in enumerate(SETUP_STEPS):
                # Only ever forward: a line of an earlier step written late changes nothing.
                if i > self.step and any(mark in line for mark in marks):
                    self.step = i
        return self.step

    def share(self, folder):
        """The bar's share for the step the setup is on, the copy's measured by the program's files in `folder` (its
        current folder) against the program's size, the package's own copy left out."""
        name, start, _marks = SETUP_STEPS[self.step]
        if name != "copy" or not self.required:
            return start
        target = self.required - (self.bundle or 0)
        if target <= 0:
            return start
        from opendmtq_client import removal
        done = removal.program_size(os.path.join(folder, "current"))
        # Up to the next step's start, never past it while the files still come.
        end = SETUP_STEPS[self.step + 1][1]
        return start + (end - start) * min(0.99, done / float(target))


class Installer:
    """The installer's window and what it does, page by page. `start`: "ask" (OpenDMTQ-Setup.exe: Install, or what to
    do on a PC with OpenDMTQ) or "uninstall" (Windows' Settings, Apps: the uninstall's own page, for the program in
    `folder`)."""

    @property
    def busy(self):
        """Whether work is under way (Velopack's setup or uninstaller, the data being deleted): the window stays until
        it ends."""
        return getattr(self, "_busy", False)

    @busy.setter
    def busy(self, on):
        # The header's close button dimmed while it is (it cannot close the window then), pressable again after. Set
        # before a page switch of the same turn, never after it: the switch is its turn's last work (setup_window's
        # show_page), and the button's new look made after it showed the switch on the screen before that turn's end.
        self._busy = bool(on)
        header = getattr(getattr(self, "window", None), "header", None)
        if header is not None:
            header.buttons[1].enable(not self._busy)

    def __init__(self, start="ask", folder=None):
        from opendmtq_client import setup_window
        self.ui_module = setup_window
        # The launcher's language, decided once for every page of this run.
        lang = language()
        self.words = i18n.Words(lang)
        self.window = setup_window.SetupWindow(self.words, lang, __version__, self.words("setup.window"), self._close)
        self.root, self.ui = self.window.root, self.window.ui
        # The work under way (Velopack's setup or uninstaller), and whether anything is under way at all (a deletion on
        # a worker thread has no process): the window stays until it ends.
        self.process, self.busy = None, False
        # What the work is (install, update, repair, back, uninstall), and the failure on show (why, title), shown
        # again after its log was opened.
        self.action, self.failure = "install", None
        # The program's folder: this user's install, or the one Windows' Apps names.
        self.folder = folder or app_dir()
        # Started from Windows' Apps: the uninstall alone, its steps from YOUR DATA.
        self.from_apps = start == "uninstall"
        # The server this installer brings, read once from its own file (none from Windows' Apps).
        self.server = None if self.from_apps else brought()
        self.log_path = run_log()
        # The data's sizes for the uninstall's page: (settings and sign-ins, game data), counted on a worker thread.
        self.sizes = None
        # What the page on show looks at again every second (the PC's state as it changes: a launcher opened or closed,
        # a game started or ended, another version installed meanwhile), or None; each page sets its own.
        self.watch = None
        self.root.after(WATCH, self._tick)
        if self.from_apps:
            self.uninstall_page()
        else:
            self.ask()
        # On the screen once its first page is there, with no title bar of Windows' (setup_window.SetupWindow.show).
        self.window.show()

    # ------------------------------------------------------------------------------------------------ pages

    def _page(self, title, lead, steps, step):
        """A new page with these steps down the column (their keys under setup.step), `step` on show, made off the
        screen until its builder shows it (self.window.show_page()). Kept, so that a page that comes of the work
        (waiting for the game, a failure) shows the same steps where the work was."""
        w = self.words
        self.flow = (steps, step)
        # The page that went took its look at the PC with it.
        self.watch = None
        return self.window.page(title, lead, [w("setup.step." + key) for key in steps], step)

    def _tick(self):
        """Once a second: the page on show looks at the PC again (self.watch)."""
        try:
            if self.watch is not None:
                self.watch()
        except Exception:  # noqa: BLE001  (a look that fails is tried again at the next tick; it changes nothing)
            log.exception("could not look at the PC's state")
        if self.root.winfo_exists():
            self.root.after(WATCH, self._tick)

    def _notices(self, parent, closes=lambda: True):
        """The lines at a choice page's foot that say what is open now (the launcher, the game), kept up to date every
        second: shown each time it opens, gone each time it closes. The launcher's line only while what is chosen closes
        it (`closes()`: repairing, updating, uninstalling; never opening it). Returns the function that brings them up
        to date, which a change of the choice calls too."""
        import tkinter as tk
        from opendmtq_client import theme
        frame = tk.Frame(parent, bg=theme.PANEL)
        frame.pack(fill="x")
        shown = {"rows": None}
        w = self.words

        def update():
            rows = []
            closing, game = closes() and launcher_open(), game_running()
            if closing and game:
                # Both in one line: the page fits its window whole (two lines and their gap ran the card under the
                # strip, a scroll bar at the window's edge).
                rows.append(("change", w("setup.notice.both")))
            elif closing:
                rows.append(("change", w("setup.closing")))
            elif game:
                rows.append(("change", w("setup.notice.game")))
            if rows == shown["rows"] or not frame.winfo_exists():
                return
            shown["rows"] = rows
            for child in frame.winfo_children():
                child.destroy()
            if rows:
                # Under the choices, apart from them by the card's gap between rows.
                holder = tk.Frame(frame, bg=theme.PANEL)
                holder.pack(fill="x", pady=(self.ui.px(16), 0))
                self.window.lines(holder, rows)

        update()
        return update

    def ask(self):
        """The first page: Install on a PC without OpenDMTQ, else what to do with the one installed."""
        have, running = installed_version(self.folder), launcher_open()
        log.info("installed %s, this %s, launcher open %s, set up for %s", have, __version__, running,
                 self.server["url"] if self.server else "no server")
        if have is None:
            self.install_page()
        else:
            self.choose_page(have, running)

    def install_page(self):
        """Install: what goes where, and the server it plays on when this installer brings one."""
        w = self.words
        content = self._page(w("setup.title.install"), w("setup.lead.install", v=__version__),
                             ("ready", "install", "done"), 0)
        card = self.window.card(content, w("setup.card.install"))
        # The program's folder broken only after its separators (path_lines), never inside a folder's name.
        rows = [(w("setup.row.program"), self.folder, True), (w("setup.row.shortcuts"), w("setup.row.shortcuts.where")),
                (w("setup.row.rights"), w("setup.row.rights.what"))]
        if self.server:
            rows.append((w("setup.row.server"), server_words(self.server)))
        self._facts(card.body, rows)
        # The project's notice at the card's foot, as the site and the launcher have it.
        self.window.notice(card.body)
        self.window.set_buttons([(w("setup.cancel"), self.root.destroy, "secondary"),
                                 (w("setup.install"), lambda: self.work("install"), "primary")],
                                default=1, escape=self.root.destroy)
        # Made: in the place of the page before, whole.
        self.window.show_page()
        # Installed meanwhile (another installer, an update): the page for an installed PC instead.
        self.watch = lambda: installed_version(self.folder) is not None and self.ask()

    def _facts(self, parent, rows):
        """A card's facts, a line each: the name in the names' column, what it is beside it. A row (name, value, True)
        holds a path, broken into lines after its separators (path_lines)."""
        import tkinter as tk
        from opendmtq_client import theme, widgets
        px = self.ui.px
        names = [row[0] for row in rows]
        width = widgets.name_width(self.ui, names)
        for i, row in enumerate(rows):
            name, value, path = row[0], row[1], len(row) > 2 and row[2]
            line = tk.Frame(parent, bg=theme.PANEL)
            # One under another with the card's gap between lines (setup_window.LINE_GAP).
            line.pack(fill="x", pady=(px(self.ui_module.LINE_GAP) if i else 0, 0))
            line.columnconfigure(0, minsize=width)
            line.columnconfigure(1, weight=1)
            tk.Label(line, text=name, font=self.ui.fonts.body_bold, fg=theme.TEXT, bg=theme.PANEL, anchor="w").grid(
                row=0, column=0, sticky="nw")
            said = widgets.label(line, self.ui, value, fg=theme.MUTED, bg=theme.PANEL, wrap_margin=0)
            said.grid(row=0, column=1, sticky="we")

            def fit(event, label=said, text=value, room=width, path=path):
                # What the row has beside the names' column: a long value wraps there, never under the names.
                wrap = max(px(120), event.width - room)
                if path:
                    # Its lines as wide as that room, each ending after a separator (Tk breaks at spaces only, and cut
                    # a long folder's name in two).
                    label.configure(text=path_lines(self.ui.fonts.body, text, wrap))
                label.configure(wraplength=wrap)

            line.bind("<Configure>", fit, add="+")

    def choose_page(self, have, running=False):
        """What to do with the OpenDMTQ installed: open it, repair it or update it (or go back to this installer's
        older version), or uninstall it."""
        from opendmtq_client import setup_window
        w = self.words
        keys = maintenance(have, __version__)
        newer, older = "update" in keys, "back" in keys
        said = {"update": (w("setup.opt.update", v=__version__), w("setup.opt.update.line", have=have, v=__version__)),
                "open": (w("setup.opt.open"), w("setup.opt.open.line")),
                "back": (w("setup.opt.back", v=__version__), w("setup.opt.back.line", have=have, v=__version__)),
                "repair": (w("setup.opt.repair"), w("setup.opt.repair.line", v=__version__)),
                "uninstall": (w("setup.opt.uninstall"), w("setup.opt.uninstall.line"))}
        options = [(key,) + said[key] for key in keys]
        title = w("setup.title.installed", v=have)
        lead = w("setup.lead.newer", have=have, v=__version__) if (newer or older) else w("setup.lead.installed")
        # The steps follow the choice: what it does, and the uninstall's own step for the data.
        steps_of = {"open": ("choose", "open"), "repair": ("choose", "repair", "done"),
                    "update": ("choose", "update", "done"), "back": ("choose", "install", "done"),
                    "uninstall": ("choose", "data", "uninstall", "done")}
        main_words = {"open": w("setup.open"), "repair": w("setup.repair"), "update": w("setup.update"),
                      "back": w("setup.back", here=__version__), "uninstall": w("setup.next")}
        content = self._page(title, lead, steps_of[options[0][0]], 0)
        card = self.window.card(content, w("setup.card.choose"))
        chosen = {"value": options[0][0]}

        def changed(value):
            chosen["value"] = value
            # The steps of what is chosen, kept for the pages its work may come to (waiting for the game, a failure).
            self.flow = (steps_of[value], 0)
            self.window.steps.show([w("setup.step." + key) for key in steps_of[value]], 0)
            main_button.set_text(main_words[value])
            # The launcher's line follows the choice: opening the launcher closes nothing.
            notices()

        def go():
            value = chosen["value"]
            if value == "open":
                self.open_launcher()
            elif value == "uninstall":
                self.uninstall_page()
            else:
                self.work(value)

        options_list = setup_window.Options(card.body, self.ui, options, options[0][0], changed, go)
        options_list.pack(fill="x")
        # Repairing, updating and uninstalling close the launcher's window first (Velopack ends what runs from the
        # program's folder), and wait for the game: said where the choice is made, each time either opens or closes,
        # the launcher's line while what is chosen closes it.
        notices = self._notices(card.body, closes=lambda: chosen["value"] != "open")

        def look():
            if installed_version(self.folder) != have:
                # Another version installed meanwhile, or none: the page for what is there now.
                self.ask()
            else:
                notices()

        self.watch = look
        buttons = self.window.set_buttons([(w("setup.close"), self.root.destroy, "secondary"),
                                           (main_words[options[0][0]], go, "primary")],
                                          escape=self.root.destroy)
        main_button = buttons[1]
        # The keyboard on the choices first: the arrow keys move them, Enter does the main button's.
        self.window.focus_later(options_list)
        # Made: in the place of the page before, whole.
        self.window.show_page()

    def uninstall_page(self):
        """Uninstall: the data kept or deleted, each with its size (counted on a worker thread), then Uninstall."""
        from opendmtq_client import removal, setup_window
        w = self.words
        steps, step = (("data", "uninstall", "done"), 0) if self.from_apps else (("choose", "data", "uninstall", "done"), 1)
        lead = w("setup.lead.uninstall")
        content = self._page(w("setup.title.uninstall"), lead, steps, step)
        card = self.window.card(content, w("setup.card.data"))
        counting = w("setup.data.counting")
        choice = {"value": "keep"}
        options_list = setup_window.Options(card.body, self.ui, [("keep", w("setup.data.keep"), counting),
                                                                 ("all", w("setup.data.all"), counting)],
                                            "keep", lambda value: choice.update(value=value),
                                            lambda: self.uninstall(choice["value"]))
        options_list.pack(fill="x")
        # The launcher closes first and the game is waited for: said each time either opens or closes.
        notices = self._notices(card.body)

        def look():
            if installed_version(self.folder) is None:
                # Uninstalled meanwhile (from Help, the command line or another installer): nothing left to uninstall.
                if self.from_apps:
                    self.failed(w("setup.not_installed", folder=self.folder))
                else:
                    self.ask()
            else:
                notices()

        self.watch = look
        back = (w("setup.cancel"), self.root.destroy) if self.from_apps else (w("setup.previous"), self.ask)
        self.window.set_buttons([(back[0], back[1], "secondary"),
                                 (w("setup.do.uninstall"), lambda: self.uninstall(choice["value"]), "remove")],
                                escape=back[1])
        # The keyboard on the choices first, as on the page before it.
        self.window.focus_later(options_list)
        # Made: in the place of the page before, whole.
        self.window.show_page()

        def counted(sizes):
            self.sizes = sizes
            if not options_list.winfo_exists():
                # The page went before the count came (Back).
                return
            settings, game = sizes
            if not settings and not game:
                # Nothing to keep or delete: one line says so, and Uninstall takes the program alone.
                options_list.set_line("keep", w("setup.data.none"))
                options_list.set_line("all", w("setup.data.none"))
                return
            folder = removal.data_root()
            options_list.set_line("keep", w("setup.data.keep.line", settings=removal.megabytes(settings),
                                            game=removal.megabytes(game), folder=folder))
            options_list.set_line("all", w("setup.data.all.line", total=removal.megabytes(settings + game)))

        self._in_background(self._count, counted)

    @staticmethod
    def _count():
        """The data's sizes: (the launcher's settings, sign-ins, logs and servers' apps, the games' data), as Delete
        everything would free them (removal.everything_size, game_data_size)."""
        from opendmtq_client import removal
        total = removal.everything_size() if os.path.isdir(removal.data_root()) else 0
        game = removal.game_data_size() if total else 0
        return max(0, total - game), game

    def _in_background(self, job, then):
        """job() on a worker thread, then(result) on the window's thread (Tk may only be touched from its own)."""
        import threading
        found = {}

        def work():
            try:
                found["result"] = job()
            except Exception:  # noqa: BLE001  (a count that fails says nothing more than counting)
                log.exception("%s failed", job.__name__)
                found["result"] = None

        def wait():
            if thread.is_alive():
                self.root.after(POLL, wait)
            elif found.get("result") is not None:
                then(found["result"])

        thread = threading.Thread(target=work, daemon=True, name=job.__name__)
        thread.start()
        self.root.after(POLL, wait)

    def wait_page(self, message, detail, again, flow=None):
        """Work that waits for the game to close: what and why, the column at the work's step (`flow`: (steps, step),
        else the page's own); once the game has closed the work goes on by itself (`again`), as the words say. Close
        leaves it undone."""
        w = self.words
        steps, step = flow or getattr(self, "flow", (("ready",), 0))
        content = self._page(w("setup.title.wait"), message, steps, step)
        card = self.window.card(content)
        self.window.lines(card.body, [("change", detail)])
        self.window.say(w("setup.waiting"))
        self.window.set_buttons([(w("setup.close"), self.root.destroy, "secondary")], default=0,
                                escape=self.root.destroy)
        # Made: in the place of the page before, whole.
        self.window.show_page()
        # The game looked at every second: closed, the work starts.
        self.watch = lambda: not game_running() and again()

    def progress_page(self, title, lead, steps, step, stages):
        """The work under way: the column's steps at the work's, and the card with its progress and its stages. Made
        off the screen: the caller shows it once the work has started, in the same turn."""
        w = self.words
        content = self._page(title, lead, steps, step)
        card = self.window.card(content)
        progress = self.ui_module.Progress(card.body, self.ui, [w("setup.stage." + key) for key in stages])
        progress.pack(fill="x")
        self.window.say(w("setup.working.stay"))
        # Shown by the caller once the work has started (self.window.show_page()), or the page of its failure instead.
        return progress

    def done_page(self, title, lead, steps, rows, open_button=True):
        """What came of it: a line each, and Open OpenDMTQ as the main answer when there is a launcher to open."""
        w = self.words
        content = self._page(title, lead, steps, len(steps) - 1)
        # What came of the work: a result's panel, its foot's corner cut as the launcher's last game.
        card = self.window.card(content, foot=True)
        self.window.lines(card.body, rows)
        if open_button:
            self.window.set_buttons([(w("setup.close"), self.root.destroy, "secondary"),
                                     (w("setup.open"), self.open_launcher, "primary")], default=1,
                                    escape=self.root.destroy)
        else:
            self.window.set_buttons([(w("setup.close"), self.root.destroy, "primary")], default=0,
                                    escape=self.root.destroy)
        # Made: in the place of the page before, whole.
        self.window.show_page()

    def failed(self, why, title=None):
        """What went wrong (`why`: plain words, or "" when the title says it all), with Try again as the main answer
        and the way to the log when there is one."""
        w = self.words
        title = title or self._failed_title()
        self.failure = (why, title)
        self.busy = False
        steps, step = getattr(self, "flow", (("ready",), 0))
        content = self._page(w("setup.title.failed"), title, steps, step)
        # What came of the work, as the end page's.
        card = self.window.card(content, foot=True)
        rows = [("bad", why)] if why else []
        log_file = self.log_path if os.path.isfile(self.log_path) else None
        if log_file:
            rows.append((None, w("setup.failed.log", path=log_file)))
        if rows:
            self.window.lines(card.body, rows)
        buttons = [(w("setup.close"), self.root.destroy, "secondary")]
        if log_file:
            buttons.append((w("setup.open_log"), self._open_log, "secondary"))
        buttons.append((w("setup.retry"), self._again, "primary"))
        self.window.set_buttons(buttons, default=len(buttons) - 1, escape=self.root.destroy)
        # Made: in the place of the page before, whole.
        self.window.show_page()

    def _failed_title(self):
        w = self.words
        return {"update": w("setup.failed.update"), "repair": w("setup.failed.repair"),
                "uninstall": w("setup.failed.uninstall")}.get(self.action, w("setup.failed"))

    def _open_log(self):
        try:
            os.startfile(self.log_path)
        except (AttributeError, OSError):
            log.exception("could not open %s", self.log_path)

    def _again(self):
        """Try again: the page the work was started from."""
        if self.action == "uninstall":
            self.uninstall_page()
        else:
            self.ask()

    # ------------------------------------------------------------------------------------- install, repair

    def work(self, action):
        """Install, update, repair or go back: Velopack's setup without a window, its progress on the page."""
        self.action = action
        w = self.words
        # The column's steps of this work: on a PC without OpenDMTQ READY, INSTALL, DONE; else from the choice.
        steps = ("ready", "install", "done") if action == "install" else (
            ("choose", {"back": "install"}.get(action, action), "done"))
        if installed_version(self.folder) is not None and game_running():
            # Velopack replaces the player's files: the game playing from them would lose them mid-song. Said in the
            # work's own words (going back to an older version installs it), at the work's step.
            why = {"update": "setup.game.update", "repair": "setup.game.repair"}.get(action, "setup.game.install")
            self.wait_page(w("setup.game"), w(why), lambda: self.work(action), flow=(steps, 1))
            return
        # Before the launcher can start: it takes the server at its first start.
        self._hand_over()
        titles = {"install": "setup.title.installing", "back": "setup.title.installing",
                  "update": "setup.title.updating", "repair": "setup.title.repairing"}
        lead = w("setup.work.%s.line" % action, v=__version__)
        self.progress = self.progress_page(w(titles[action]), lead, steps, 1, [name for name, _s, _m in SETUP_STEPS])
        self.setup_log = SetupLog(self.log_path)
        try:
            self.process = run_setup(self.log_path)
        except OSError as e:
            # The system's own words in the log; the page says why by its kind, when it is one.
            log.exception("could not start Velopack's setup")
            self.failed(self.words.failed("setup.no_setup", e, network=False))
            return
        # The work under way: the window's close button dimmed, then its page in the place of the page before, whole,
        # in this same turn (the page before's buttons gone with it, so that a second click on Install waiting in Tk's
        # queue reaches nothing). The switch last, as the busy setter says.
        self.busy = True
        self.window.show_page()
        self.started_at = time.time()
        self.root.after(POLL, self._wait_setup)

    def _wait_setup(self):
        """Velopack's setup under way: the page follows its log and the files landing; then what came of it."""
        step = self.setup_log.read()
        self.progress.set(self.setup_log.share(self.folder), step)
        code = self.process.poll()
        if code is None:
            if time.time() - self.started_at > SETUP_LIMIT:
                # A setup that hangs never ends on its own: stop it and say so.
                log.error("Velopack's setup did not finish in %d s", SETUP_LIMIT)
                self.process.kill()
                self.failed(self.words("setup.too_long", m=SETUP_LIMIT // 60))
                return
            self.root.after(POLL, self._wait_setup)
            return
        self.busy = False
        log.info("Velopack's setup ended with %s", code)
        if code != 0:
            # Velopack's last error line, in its own (English) words, goes to this log; the page says it by its kind
            # in the installer's language (a full disk, a file in use, no permission), else only that it failed and
            # where Velopack's log is. Its setup asks nothing over the network: no network kind is read into it.
            line = failure_line(self.log_path)
            log.error("Velopack's setup failed: %s", line or "no error line in its log")
            self.failed(self.words.fault(line, network=False))
            return
        found = installed_version(self.folder)
        if found != __version__:
            self.failed(self.words("setup.wrong_version", found=found, here=__version__))
            return
        # Velopack's setup has written Windows' entry in Settings, Apps last: made OpenDMTQ's own now, so that an
        # uninstall there opens the installer's own uninstall (installed.own_entry).
        own_entry()
        self.progress.finish()
        # The bar filled before the page changes (the last of its easing, a few frames).
        self.root.after(400, self._installed)

    def _installed(self):
        w = self.words
        action = self.action
        if action == "repair":
            lead, rows = w("setup.done.repaired", v=__version__), [("ok", w("setup.done.stayed"))]
        elif action == "update":
            lead, rows = w("setup.done.updated", v=__version__), [("ok", w("setup.done.stayed"))]
        else:
            lead = w("setup.done", v=__version__)
            rows = [("ok", w("setup.done.program", folder=self.folder)), ("ok", w("setup.done.shortcuts"))]
            if self.server:
                rows.append(("ok", w("setup.done.server", name=self.server["name"])))
            if action == "back":
                rows.append(("ok", w("setup.done.stayed")))
        steps = ("ready", "install", "done") if action == "install" else (
            ("choose", {"back": "install"}.get(action, action), "done"))
        self.done_page(w("setup.title.done"), lead, steps, rows)

    def open_launcher(self):
        """Open OpenDMTQ: the installed launcher, the server this installer brings handed over first; the window closes
        once it has started, or says why it did not."""
        self._hand_over()
        try:
            start_launcher()
        except OSError as e:
            # The system's own words in the log; the page says why by its kind, when it is one.
            log.exception("could not start the launcher")
            self.failed(self.words.failed("setup.not_started.detail", e, network=False),
                        title=self.words("setup.not_started"))
            return
        self.root.after(300, self.root.destroy)

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

    # -------------------------------------------------------------------------------------------- uninstall

    def uninstall(self, choice):
        """Uninstall: Velopack's uninstaller takes the program, its shortcuts and Windows' entry; then the data when
        `choice` is "all", and OpenDMTQ's logs outside its folders either way. The page shows each as it goes."""
        from opendmtq_client import removal
        self.action = "uninstall"
        w = self.words
        # The column's steps of the uninstall, at its own step (from Windows' Apps it starts at YOUR DATA).
        steps, step = (("data", "uninstall", "done"), 1) if self.from_apps else (("choose", "data", "uninstall", "done"), 2)
        if game_running():
            # The player's files go: the game playing from them would lose them mid-song.
            self.wait_page(w("setup.game"), w("setup.game.uninstall"), lambda: self.uninstall(choice),
                           flow=(steps, step))
            return
        if not installed.updater(self.folder):
            self.failed(w("setup.not_installed", folder=self.folder))
            return
        stages = ["remove"] + (["data"] if choice == "all" else []) + ["logs"]
        self.uninstall_steps = steps
        self.progress = self.progress_page(w("setup.title.uninstalling"), w("setup.lead.uninstall"), steps, step, stages)
        self.choice, self.stages = choice, stages
        self.program_bytes = max(1, removal.program_size(self.folder))
        try:
            self.process = removal.start_uninstaller(self.folder)
        except OSError as e:
            log.exception("could not start Velopack's uninstaller")
            self.failed(w("setup.failed.start_uninstaller", error=w.error(e)))
            return
        # The work under way: the window's close button dimmed, then its page in the place of the page before, whole,
        # in this same turn (the switch last, as the busy setter says).
        self.busy = True
        self.window.show_page()
        self.started_at = time.time()
        self.ended_at = None
        self.root.after(POLL, self._wait_uninstaller)

    def _wait_uninstaller(self):
        """Velopack's uninstaller under way: the bar follows the program's folder as it empties, then the folder's going."""
        from opendmtq_client import removal
        # The removal's share of the bar: up to its end, the rest the data's and the logs'.
        span = 0.7 if self.choice == "all" else 0.9
        left = removal.program_size(self.folder)
        self.progress.set(span * (1.0 - min(1.0, left / float(self.program_bytes))), 0)
        code = self.process.poll()
        if code is None:
            if time.time() - self.started_at > SETUP_LIMIT:
                log.error("Velopack's uninstaller did not finish in %d s", SETUP_LIMIT)
                self.process.kill()
                self.failed(self.words("setup.too_long", m=SETUP_LIMIT // 60))
                return
            self.root.after(POLL, self._wait_uninstaller)
            return
        if code != 0:
            log.error("Velopack's uninstaller ended with %s", code)
            self.failed(self.words("setup.failed.uninstaller", code=code))
            return
        # Its program goes a few seconds after the uninstaller itself: waited for, then the data and the logs.
        self.ended_at = self.ended_at or time.time()
        if os.path.isdir(os.path.join(self.folder, "current")):
            if time.time() - self.ended_at < FOLDER_GONE:
                self.root.after(POLL, self._wait_uninstaller)
                return
            log.error("the program stayed in %s after the uninstaller", self.folder)
            self.failed(self.words("setup.failed.program_stayed", folder=self.folder))
            return
        log.info("Velopack's uninstaller is done: the program, its shortcuts and its entry are gone")
        self._delete_data()

    def _delete_data(self):
        """The data when chosen (removal.delete_everything, its bytes as they go), and OpenDMTQ's logs outside its
        folders either way, on a worker thread; then what came of it."""
        import threading
        from opendmtq_client import removal
        state = {"gone": 0, "failed": None}
        total = sum(self.sizes) if self.sizes else 0
        all_data = self.choice == "all"

        def gone(size):
            state["gone"] += size

        def work():
            failed = []
            try:
                if all_data:
                    failed = removal.delete_everything(gone=gone)
                else:
                    # The logs this run and the launcher hold are closed first: an open file would stay.
                    removal.close_log()
                    removal._delete_leftovers(failed)
            except Exception as e:  # noqa: BLE001  (said on the page, never swallowed)
                failed = [str(e)]
            state["failed"] = failed

        def follow():
            if state["failed"] is None:
                if all_data and total:
                    self.progress.set(0.7 + 0.25 * min(1.0, state["gone"] / float(total)), 1)
                self.root.after(POLL, follow)
                return
            self.busy = False
            self.progress.finish()
            self.root.after(400, lambda: self._uninstalled(state["failed"], total))

        self.progress.set(0.7 if all_data else 0.9, 1 if all_data else len(self.stages) - 1)
        threading.Thread(target=work, daemon=True, name="delete").start()
        self.root.after(POLL, follow)

    def _uninstalled(self, failed, total):
        """The end: what went, what stayed, and what could not go."""
        from opendmtq_client import removal
        w = self.words
        rows = [("ok", w("uninstalled.gone"))]
        if self.choice == "all":
            rows.append(("ok", w("setup.done.deleted", size=removal.megabytes(total)) if total else
                         w("uninstalled.nothing")))
        elif total:
            rows.append(("ok", w("uninstalled.kept", size=removal.megabytes(total), folder=removal.data_root())))
        else:
            rows.append(("ok", w("uninstalled.nothing")))
        if failed:
            rows.append(("change", w("setup.done.left", n=len(failed), folder=removal.data_root())))
        self.done_page(w("setup.title.done"), w("uninstalled.done"), self.uninstall_steps, rows, open_button=False)

    # ---------------------------------------------------------------------------------------------- the window

    def _close(self):
        if self.busy:
            # Velopack is writing or removing files, or the data is being deleted: the window stays until it is done
            # (or the time limit stops it), and says so where the work's line is (main answered the close button and
            # Alt+F4 with nothing at all).
            self.window.say(self.words("setup.busy.close"))
            return
        self.root.destroy()

    def run(self):
        self.window.run()


def uninstall_main(folder):
    """Windows' Settings, Apps' uninstall, in the launcher's copy outside the program's folder (main.py
    --uninstall-from): the installer's own uninstall for the program in `folder`. Returns the exit code."""
    log.info("the uninstall from Windows' Apps for %s", folder)
    Installer(start="uninstall", folder=folder).run()
    return 0


def _logging():
    """The installer's own log next to Velopack's, in the temporary folder, with a size cap; Velopack's logs of
    earlier runs beyond the last few are removed."""
    folder = log_folder()
    handler = logging.handlers.RotatingFileHandler(os.path.join(folder, LOG_NAME), maxBytes=200_000,
                                                   backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    # Closed with the launcher's own before the uninstall deletes OpenDMTQ's logs, this one among them
    # (removal.close_log): a file held open would stay.
    handler.odq_log = True
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
            if code == 0:
                # As the window does once Velopack's setup is done: Windows' entry made OpenDMTQ's own.
                own_entry()
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
