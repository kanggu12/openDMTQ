"""Start the launcher, or do one of its jobs from the command line.

  OpenDMTQ.exe                          the launcher window (the first-start guide the first time)
  OpenDMTQ.exe --status                 print the server, the sign-in, the app, the ready check and a newer launcher on
                                        offer (exit 0: PLAY can go)
  OpenDMTQ.exe --test-server [ADDRESS]  test the connection to the server PLAY plays on (or ADDRESS), step by step, each
                                        with what it found and how long it took (exit 0: every step passed, 1: one
                                        failed)
  OpenDMTQ.exe --server URL             connect to a server and play on it from now on
  OpenDMTQ.exe --use-found              move the server PLAY plays on to the address the last connection test found
                                        it at (Online's Use this address: its sign-in goes with it, its old app goes)
  OpenDMTQ.exe --sign-in ID             sign in to the server (the password from standard input, or asked for)
  OpenDMTQ.exe --sign-out               forget the sign-in
  OpenDMTQ.exe --app                    download the server's app, or a newer one
  OpenDMTQ.exe --records                PLAY's My records: the player's latest plays and best records on the server
  OpenDMTQ.exe --my-page                PLAY's My page on the site, opened in the browser signed in
  OpenDMTQ.exe --set name=value ...     change a PC setting (values.py names them; keyboard play's keys as
                                        keys_3line="D F J")
  OpenDMTQ.exe --reset-keys             each LINE mode's keys back to their defaults (the Controls page's Reset keys)
  OpenDMTQ.exe --audio-devices          list the sound devices the player can play on
  OpenDMTQ.exe --language en|ko|system  the launcher's language (system: Windows' display language)
  OpenDMTQ.exe --guide                  open the first-start guide again at the next start of the window
  OpenDMTQ.exe --skip-guide             the window opens on its pages, the first-start guide done (the guide's Skip)
  OpenDMTQ.exe --servers                list the servers this launcher knows, the one PLAY plays on marked *
  OpenDMTQ.exe --open-log player|launcher   show the player's or the launcher's log in Explorer
  OpenDMTQ.exe --report FILE            save a report for whoever helps (a zip: the logs, the settings, the displays, the
                                        sound devices, Windows and the graphics card; names, addresses and sign-ins left
                                        out); FILE may be a folder, where it takes the report's own name
  OpenDMTQ.exe --play                   get ready and start the game, no window; returns when the game ends
  OpenDMTQ.exe --forget URL [--yes]     forget a server, its sign-in and its app on this PC
  OpenDMTQ.exe --reset [--yes]          start over: forget the servers, the sign-ins, the apps and the settings
  OpenDMTQ.exe --update [--yes]         look for a newer launcher and install it (it restarts)
  OpenDMTQ.exe --repair                 put back the program's files that are missing or changed
  OpenDMTQ.exe --clear-game-data [--yes]    delete the game's data on this PC; this PC stays the same player
  OpenDMTQ.exe --uninstall [--delete-data] [--yes]  uninstall OpenDMTQ; --delete-data deletes its data on this PC too

The console copy OpenDMTQ-cmd.exe takes the same arguments and prints to the terminal. Several jobs in one command run
in the order above (--server, then --sign-in, then --app, then --play; --test-server before --use-found); --repair,
--clear-game-data and --uninstall run on their own. While the launcher's window is open, the jobs that change what it
keeps (--set, --reset-keys, --reset, --forget, --language, --guide, --server, --use-found, --sign-in, --sign-out,
--uninstall) are refused: the window would write its own copy over them. --repair, --clear-game-data and --uninstall are
refused while a game runs: it uses the files they change; so are --reset, --forget and --use-found of the server whose
app it plays.
"""

import argparse
import getpass
import logging
import logging.handlers
import os
import sys
import threading

from opendmtq_client import __version__, actions, apps, console, dpi, i18n, player, preset
from opendmtq_client import server as srv
from opendmtq_client import state as st
from opendmtq_client import values as choices

log = logging.getLogger("opendmtq_client")
# The launcher window's mutex while this process holds it (_single_instance): the window is open.
_window_mutex = None
# Windows' Settings, Apps runs the launcher with UNINSTALL_WINDOW (installed.own_entry): it copies itself out of the
# program's folder and starts the copy with UNINSTALL_FROM and the install folder (removal.start_uninstall_window), which
# shows the installer's own uninstall (installer.uninstall_main). Nothing else runs it with either.
UNINSTALL_FROM = "--uninstall-from"


def _velopack_hooks(argv):
    """Let Velopack handle its install, update and uninstall events; it exits the process for those.

    OpenDMTQ does one thing in them: after an update, Windows' entry in Settings, Apps made OpenDMTQ's own again
    (Velopack has just written its own again: installed.own_entry). Its uninstall needs nothing more: the installer's
    own uninstall (installer.py) has asked and says what went. When Velopack itself fails in one, the failure is logged
    and the process ends as a finished hook would: the installer does not report a partly failed install over it.
    """
    try:
        import velopack
    except ImportError:
        # Run from source or a copied folder: there is no installer around.
        return
    try:
        app = velopack.App()
        # Each is a fast hook, which Velopack ends the process after: what it does must take moments.
        app.on_after_update_fast_callback(lambda version: _hook("the update's", _own_entry))
        app.run()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001  (a Rust panic arrives as a BaseException, which Exception misses)
        log.exception("Velopack start-up hook failed")
        if any(a.startswith("--veloapp-") for a in argv):
            sys.exit(0)


def _hook(name, job):
    """A hook's work, its failure in the log: Velopack's binding prints a hook's error where no one sees it, then ends
    the process as if it had worked, and the install, update or uninstall goes on either way."""
    try:
        job()
    except Exception:  # noqa: BLE001  (logged; nothing of OpenDMTQ's hook may stop Velopack's work)
        log.exception("%s hook failed", name)


def _own_entry():
    """Windows' entry for OpenDMTQ in Settings, Apps made OpenDMTQ's own (installed.own_entry), its failure in the log:
    an entry that stays as Velopack wrote it uninstalls with Velopack's own window and keeps the data, nothing else."""
    from opendmtq_client import installed
    try:
        installed.own_entry()
    except Exception:  # noqa: BLE001  (the registry refusing: the launcher starts all the same)
        log.exception("could not make Windows' uninstall of OpenDMTQ its own")


def _uninstall_window(argv):
    """--uninstall-window, from Windows' Settings, Apps: the launcher copies itself out of the program's folder and
    starts the copy, which shows the installer's own uninstall (removal.start_uninstall_window); this one ends at once.
    --uninstall-from FOLDER: that copy, the uninstall itself (installer.uninstall_main), then the copy removed a few
    seconds after it ends (removal.remove_later). Returns the exit code."""
    from opendmtq_client import installed, installer, removal
    dpi.aware()
    if argv[0] == installed.UNINSTALL_WINDOW:
        root = installed.root()
        if root is None:
            # A copied folder or a checkout: nothing Windows installed to uninstall.
            log.warning("--uninstall-window from a launcher OpenDMTQ-Setup.exe did not install")
            return 2
        removal.start_uninstall_window(root)
        return 0
    # The installer's own window from here on: an error that ends it is said in a window like it, without Windows'
    # title bar (stopped.py).
    from opendmtq_client import stopped
    stopped.FRAMELESS = True
    code = installer.uninstall_main(argv[1])
    removal.remove_later(os.path.dirname(os.path.abspath(sys.executable)))
    return code


def _logging(make=True):
    """One log file with a size cap: 1 MB, the two previous ones kept, nothing older. With `make` False the log is
    written only where its folder already is (Velopack's uninstall hook, which runs after Delete all has removed it)."""
    path = st.launcher_log()
    folder = os.path.dirname(path)
    root = logging.getLogger("opendmtq_client")
    if not make and not os.path.isdir(folder):
        # Something still listens, so that Python does not print what is logged to the console itself.
        root.addHandler(logging.NullHandler())
        return
    os.makedirs(folder, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    handler.odq_log = True
    root.setLevel(logging.INFO)
    # One file handler at a time, even when main() runs more than once in a process (the tests do).
    for old in [h for h in root.handlers if getattr(h, "odq_log", False)]:
        root.removeHandler(old)
        old.close()
    root.addHandler(handler)
    # A worker thread's error that nothing caught goes to the same log.
    threading.excepthook = _thread_failed


def _thread_failed(args):
    """An error nobody caught that ended a worker thread: in the log, as the window copy has no console to print it on
    (a page would wait for its answer with nothing said anywhere), and on the console too when there is one."""
    if issubclass(args.exc_type, SystemExit):
        # A thread that chose to end.
        return
    log.error("the %s thread failed", args.thread.name if args.thread is not None else "?",
              exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.__excepthook__(args)


def _single_instance():
    """True when no other launcher window is open; otherwise bring that one forward and return False."""
    from opendmtq_client import mutex
    global _window_mutex
    # The mutex lives as long as the first launcher; a second one finds it held already.
    _window_mutex, held_before = mutex.hold(mutex.LAUNCHER)
    if not held_before:
        return True
    # Not this launcher's to keep: the other window's stays open as long as it is.
    mutex.release(_window_mutex)
    _window_mutex = None
    import ctypes
    hwnd = ctypes.windll.user32.FindWindowW(None, "OpenDMTQ")
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 9)        # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    return False


def _say(text, error=False, shown=None):
    """Print for the console copy; the window copy has no console, so everything also goes to the log. `shown` is the
    same words as the console shows them (console.py's colours and columns), when they differ from the log's."""
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        # In a terminal that shows colours, the console's look (an error in the problems' red); anywhere else (a pipe, a
        # file, a script reading it) the log's words, which stay the same from one version to the next.
        designed = console.colour_on(stream)
        out = (shown if shown is not None else console.paint(text, "bad", stream=stream) if error else text) \
            if designed else text
        # Flushed at once: --update hands the process to Velopack, which ends it without Python's own exit.
        print(out, file=stream, flush=True)
    (log.error if error else log.info)(text)


def _show(text):
    """Print what only a terminal's look has (a title, a part's name, a blank line): not for the log, nor a pipe."""
    if sys.stdout is not None and console.colour_on():
        print(text, flush=True)


def _leave_own_console():
    """Close the console that Windows opened for this program alone (no other program shares it: a double click, not a
    terminal it was typed in); what would be printed goes to the log, as for the window copy. True when it went."""
    if sys.platform != "win32" or sys.stdout is None:
        return False
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        processes = (ctypes.c_uint32 * 4)()
        # The programs sharing this console: one (this one) when Windows made it for this start.
        if kernel32.GetConsoleProcessList(processes, 4) != 1:
            return False
        kernel32.FreeConsole()
    except (AttributeError, OSError):
        return False
    # Nothing left to print to: the window copy's ways (dialogs, the log) from now on.
    sys.stdout = sys.stderr = None
    log.info("the console copy started with no job: its console closed, the window opens")
    return True


def _windowed():
    """True for the window copy (OpenDMTQ.exe): it has no console, so a printed error is never seen."""
    return sys.stdout is None or sys.stderr is None


def _cannot_start(error):
    """The window copy cannot read its settings: say so in a dialog instead of closing without a word.

    A broken file can be set aside (kept next to it, with the time in its name) to start again from the guide; a file
    from a newer launcher is left alone, because only that launcher reads it right.
    """
    from opendmtq_client import dialogs
    # The settings that would say the player's language cannot be read: Windows' display language.
    language = st.system_language()
    asked = cannot_start_dialog(error, language)
    if error.newer:
        dialogs.standalone(*asked, language=language)
        return False
    answer = dialogs.standalone(*asked, language=language)
    if answer != "reset":
        return False
    import time
    aside = "%s.broken-%s" % (error.path, time.strftime("%Y%m%d-%H%M%S"))
    try:
        os.replace(error.path, aside)
        log.info("set the unreadable settings aside as %s", aside)
    except FileNotFoundError:
        # Another start of the launcher set it aside a moment ago.
        log.info("the unreadable settings were already set aside")
    return True


def cannot_start_dialog(error, language):
    """The dialog for settings the launcher cannot read, as standalone()'s arguments: (kind, title, message, detail,
    buttons, default, cancel). A newer launcher's file is left alone; a broken one can be set aside to start over."""
    from opendmtq_client import i18n
    w = i18n.Words(language)
    if error.newer:
        return ("error", w("start.title"), w("start.newer"), w("start.newer.detail", path=error.path),
                [(w("start.close"), "close", "home")], 0, "close")
    return ("error", w("start.title"), w("start.broken"), w("start.broken.detail", path=error.path),
            [(w("start.close"), "close", "neutral"), (w("start.over"), "reset", "warn")], 1, "close")


def _ask(question, yes):
    """y/N before something that cannot be undone; --yes answers for the player."""
    if yes:
        return True
    try:
        answer = input(question + " [y/N] ") if sys.stdin else "n"
    except EOFError:
        answer = "n"
    return answer.strip().lower() in ("y", "yes")


def _update(yes):
    """--update: the same check as the Launcher page, then the same update (the launcher restarts into it)."""
    from opendmtq_client import updates
    # The window's English words for a failure: what failed and, by its kind, why (Velopack's own are in the log).
    w = i18n.Words("en")
    result = updates.check()
    # The server PLAY plays on is named when the answer is its own (updates.py: the server first, GitHub second).
    server = result.source is not None and result.source.kind == "server"
    source = result.source.label() if result.source is not None else ""
    if result.kind != "available":
        said = {"not_installed": "Updates work in the launcher the installer put on this PC.",
                "no_source": "No update address is set for this build.",
                "uptodate": ("This is the newest version for %s (%s)." % (source, updates.shown_version()) if server
                             else "This is the newest version (%s)." % updates.shown_version()),
                "failed": w.failed("about.update_failed", result.error),
                "refused": w("about.refused", source=source)}
        _say(said.get(result.kind, result.kind), error=result.kind in ("failed", "refused"))
        return 0 if result.kind == "uptodate" else 2
    _say("OpenDMTQ %s is available%s (this is %s)." % (result.version, " from %s" % source if server else "",
                                                       updates.shown_version()))
    from opendmtq_client import playing
    if playing.running():
        # The update replaces the player's files: a game playing from them would lose them mid-song.
        _say("Close the game first: the update replaces the player's files.", error=True)
        return 2
    if not _ask("Update now? The launcher closes and starts again.", yes):
        _say("Nothing changed.")
        return 1
    try:
        # Downloads and checks it, then hands over to Velopack, which waits for this process to end, puts the update in
        # and starts the new launcher. When the delta package does not give the package signed, the whole one comes.
        updates.apply(result, tell=lambda what: _say("The whole update is downloading."))
    except updates.UpdateError as e:
        # Refused or not downloaded: the window's words for it, and why when a download failed by a kind of its own.
        log.exception("--update failed")
        _say(i18n.sentences(w.error(e), w.fault(e.__cause__) if e.__cause__ is not None else ""), error=True)
        return 2
    except Exception as e:  # noqa: BLE001  (shown and logged, never swallowed)
        # Velopack's own words, with where they came from, in the log; on the console the window's words.
        log.exception("--update failed")
        _say(w.failed("about.apply_failed", e), error=True)
        return 2
    _say("Updating: the launcher starts again in a few seconds.")
    return 0


def _maintain(args):
    """--repair, --clear-game-data, --uninstall: Help's buttons of the same names, with the same questions as y/N."""
    from opendmtq_client import playing
    if playing.running():
        # The player's files and the game's data are open while it plays.
        _say("Close the game first: it uses the files this changes.", error=True)
        return 2
    if args.repair:
        return _repair()
    if args.clear_game_data:
        return _clear_game_data(args.yes)
    return _uninstall(args.delete_data, args.yes)


def _started_meanwhile(window=False):
    """A game running, before the y/N or one started while it waited (or, for the uninstall, the launcher's window
    opened): said, and True."""
    from opendmtq_client import playing
    if playing.running():
        _say("Close the game first: it uses the files this changes.", error=True)
        return True
    if window and window_open():
        _say("The launcher's window is open: make this change there, or close the window first.", error=True)
        return True
    return False


def _repair():
    """--repair: the program's files compared with the installed package, what is missing or changed put back."""
    from opendmtq_client import repair
    try:
        result = repair.run()
    except (repair.RepairError, OSError) as e:
        _say(str(e), error=True)
        return 2
    # Each file named, as the log names it.
    for kind, names in (("missing", result.missing), ("changed", result.changed)):
        for name in names:
            _say("  %s: %s%s" % (kind, name, " (not put back)" if name in result.failed else ""))
    if result.failed:
        _say("Put back %d files; %d could not be. Run the installer again and choose Repair."
             % (result.restored, len(result.failed)), error=True)
        return 1
    if result.restored:
        _say("Put back %d files.%s" % (result.restored, " Start the launcher again: some are its own."
                                       if result.needs_restart else ""))
    else:
        _say("All %d files of the program are as installed." % result.checked)
    return 0


def _clear_game_data(yes):
    """--clear-game-data: the games' folders emptied but for the id this PC plays by."""
    from opendmtq_client import removal
    size = removal.game_data_size()
    if not size:
        _say("There is no game data on this PC.")
        return 0
    if not _ask("Delete the game's data on this PC (%s)? It downloads again, and this PC stays the same player."
                % removal.megabytes(size), yes):
        _say("Nothing changed.")
        return 1
    if _started_meanwhile():
        return 2
    failed = removal.clear_game_data()
    for path in failed:
        _say("  in use, left in place: %s" % path, error=True)
    if failed:
        return 1
    _say("Cleared the game's data (%s)." % removal.megabytes(size))
    return 0


def _uninstall(delete_data, yes):
    """--uninstall: Velopack's uninstaller, after the data on this PC went too with --delete-data."""
    from opendmtq_client import removal
    try:
        removal.can_uninstall()
    except removal.RemovalError as e:
        _say(str(e), error=True)
        return 2
    if delete_data:
        question = ("Uninstall OpenDMTQ and delete its settings, sign-ins and game data on this PC (%s)? A later "
                    "install is a new player." % removal.megabytes(removal.everything_size()))
    else:
        question = "Uninstall OpenDMTQ? Its settings, sign-ins and game data stay for a later install."
    if not _ask(question, yes):
        _say("Nothing changed.")
        return 1
    if _started_meanwhile(window=True):
        return 2
    code = 0
    if delete_data:
        failed = removal.delete_everything()
        for path in failed:
            _say("  in use, left in place: %s" % path, error=True)
        code = 1 if failed else 0
    # Said before the uninstaller starts: it closes what runs from the program's folder, this console copy too.
    _say("Uninstalling: OpenDMTQ is gone from this PC in a few seconds. Your records stay on the servers.")
    try:
        # After --delete-data, Velopack's log of the uninstall goes with the program too (removal.uninstall).
        removal.uninstall(delete_all=delete_data)
    except OSError as e:
        _say("The uninstaller did not start: %s" % e, error=True)
        return 2
    return code


def _status(state):
    """--status: where PLAY plays, what it has, the ready check, and the launcher with a newer one on offer (the window's
    look at its start, with the same time limit); 0 when PLAY can go. Laid out in parts, each under its name, the
    names and values in columns (console.py); the log has each line as words."""
    from opendmtq_client import updates
    # Started first, so that it asks for updates while the server is asked: the two waits overlap.
    look = updates.Look(state=state)
    this = updates.shown_version()
    _show(console.title(this))
    server = state.server()
    pairs = []
    if server is None:
        pairs.append(("server", "none (connect with --server URL)", "warn"))
    else:
        # Its name and address, or its address once when it has no name of its own (as the ready check's line says it).
        pairs.append(("server", st.label(server)))
        signed = state.signed_in(server)
        pairs.append(("signed in", server["account"] if signed else "no" + (
            " (%s, ended)" % server["account"] if server.get("account") else ""), None if signed else "warn"))
        have = apps.local(server["url"])
        pairs.append(("app", "%s (%s)" % (have["file"], have.get("built_at") or "?") if have else "none on this PC",
                      None if have else "warn"))
    pairs.append(("language", "%s%s" % (state.language, "" if state.picked_language else " (Windows' display language)")))
    _part("PLAY", pairs)
    # The server asked as the window's ready check asks it: one that does not answer is said, and does not stop PLAY.
    checks = actions.readiness(state, reached=actions.reach(state))
    _show(console.heading("Ready check"))
    width = max(len(c.key) for c in checks) if checks else 0
    for c in checks:
        kind = "ok" if c.ok else ("play" if c.play_fixes else "todo" if c.blocks else "warn")
        _say("  [%s] %s: %s" % (console.MARKS[kind][0].ljust(4), c.key, c.detail),
             shown="  %s %s  %s" % (console.mark(kind), console.paint(c.key.ljust(width), "muted"), c.detail))
    _show(console.heading("Settings"))
    items = ["%s=%s" % (k, state.values[k]) for k in choices.NAMES]
    _say("settings: " + ", ".join(items), shown=console.words(items))
    # The last game's sound as the player measured it, as the Sound page's Last game card says it (the command line's
    # words are English).
    said = player.sound_words(i18n.Words("en"), player.last_sound())
    last = ", ".join(part for part in said[1:] if part) if said else "none yet"
    # Gaps marked as the window's lamp marks them (a ring there, a warning's mark here).
    _part("Sound", [("last game", last, None if not said or said[0] == "ok" else "warn")])
    # Where the logs are, as Help's Open buttons show them.
    _part("Logs", [("%s log" % name, path or "none yet (no app on this PC)") for name, path in _log_paths(state).items()])
    # The launcher's version, and a newer one when the look found it (nothing more without a network or an answer in
    # time); it changes nothing of the exit code, which is about PLAY.
    newer = look.newer()
    offer = "; OpenDMTQ %s is available (--update)" % newer.version if newer else ""
    _show("")
    _say("launcher: %s%s" % (this, offer), shown=console.rows([("launcher", this + offer, "ok" if newer else None)]))
    return 0 if actions.can_play(checks) else 1


def _part(name, pairs):
    """A part of what --status prints: its name, then its names and values in two columns; each line in the log as
    "name: value"."""
    _show(console.heading(name))
    for pair in pairs:
        _say("%s: %s" % (pair[0], pair[1]), shown=console.rows([pair], indent=2))


def _log_paths(state):
    """The launcher's log, and the player's for the current server's app (None while there is no app)."""
    server = state.server()
    have = apps.local(server["url"]) if server else None
    return {"launcher": st.launcher_log(), "player": player.app_log(have)}


def _password(prompt):
    """The password: a line from standard input when it is not a terminal (a script's pipe), else asked for unseen."""
    if sys.stdin is not None and not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\r\n")
    return getpass.getpass(prompt)


def _say_downloading(done, total):
    """How far a download is, in the window's numbers (i18n.mb), for --app and --play: in a terminal one bar that
    moves in place, its last state left on its line when it is done; elsewhere a line each time, as the log has them."""
    words = "  downloading: %s of %s MB" % (i18n.mb(done), i18n.mb(total))
    if sys.stdout is not None and console.colour_on():
        line = console.bar(done, total, "  Downloading the app") + "  %s of %s MB" % (i18n.mb(done), i18n.mb(total))
        print("\r" + line, end="\n" if total and done >= total else "", flush=True)
        log.info(words)
        return
    _say(words)


def _get_app(state):
    """--app: the server's app on this PC, downloaded when it lacks it or the server has a newer one."""
    seen = {"step": -1}

    def progress(done, total):
        # A line every tenth of the way: the output may well be a log file.
        step = int(10 * done / total) if total else 0
        if step != seen["step"]:
            seen["step"] = step
            _say_downloading(done, total)

    info = actions.check_app(state)
    if apps.current(state.server()["url"], info):
        _say("The app of %s is on this PC already." % actions.when(info))
        return
    have = actions.get_app(state, info, progress)
    _say("Downloaded the app of %s: %s" % (actions.when(have), have["file"]))


def _play(state):
    """--play: as the window's PLAY, with the game's end waited for (the installer waits for it meanwhile)."""
    from opendmtq_client import playing
    # The 8 MB step of the download said last: the pieces come in as they arrive, a megabyte or a little more each.
    said = {"step": -1}

    def report(step, done=None, total=None):
        if step == "download":
            # A line about every 8 MB, and the last.
            if done == total or done // (8 << 20) != said["step"]:
                said["step"] = done // (8 << 20)
                _say_downloading(done, total)
        else:
            _say("  " + {"app": "asking the server for its app", "starting": "starting the game",
                         "offline": "the server did not answer: the game starts with the app on this PC"}.get(step, step))

    session = actions.play(state, report=report)
    state.save()
    w = i18n.Words("en")
    if session.linked:
        # The site account and this PC's game player linked by this PLAY: said once, in the window's words.
        _say(w("status.linked", account=session.linked))
    _say("The game is running (process %d)." % session.process.pid)
    # The installer waits while a game runs (playing.py); held until it ends.
    playing.hold()
    record = actions.finish(state, session)
    playing.release()
    # The game's first start on this PC gave the id it signs in by: the account and that player linked now, said once
    # after how the game ended, as the window says it.
    linked, ended = None, None
    try:
        linked = None if session.linked else actions.link_player(state)
    except srv.SignedOut as e:
        # The sign-in ended meanwhile (forgotten): said after the game's end, which keeps its own exit code.
        ended = e
    state.save()
    if record.get("failed_start"):
        # The player's own "could not start": its log says why.
        _say("The game could not start. The player's log says why: %s" % _log_paths(state)["player"], error=True)
        code = 1
    else:
        _say("The game ended after %d s%s." % (record["seconds"], " (it closed by itself, code %s)" % record["exit_code"]
                                               if record["crashed"] else ""))
        code = 0 if not record["crashed"] else 1
    if linked:
        _say(w("status.linked", account=linked))
    if ended is not None:
        _say(str(ended), error=True)
    return code


def parse(argv):
    p = argparse.ArgumentParser(
        prog="OpenDMTQ", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="OpenDMTQ %s, the launcher for PCs. Without a job, the launcher's window opens; each job here does "
                    "what a button of the window does." % __version__,
        epilog="Several jobs in one command run in order: --server, --sign-in, --app, then --play.")
    p.add_argument("--version", action="version", version="OpenDMTQ " + __version__)
    # The jobs in parts, as the window's pages have them: what PLAY needs, the PC's settings, then help and upkeep.
    play = p.add_argument_group("play")
    play.add_argument("--status", action="store_true",
                      help="print the server, the sign-in, the app, the ready check and a newer launcher on offer")
    play.add_argument("--play", action="store_true", help="get ready and start the game")
    play.add_argument("--test-server", nargs="?", const="", metavar="ADDRESS",
                      help="test the connection to the server PLAY plays on, or to ADDRESS: each step with what it found "
                           "and how long it took (exit 0 when every step passes, 1 when one fails)")
    play.add_argument("--records", action="store_true",
                      help="PLAY's My records: the signed-in player's latest plays and best records on the server")
    play.add_argument("--my-page", action="store_true",
                      help="PLAY's My page on the site: the player's page opened in the browser, signed in already")
    online = p.add_argument_group("server and sign-in")
    online.add_argument("--server", metavar="URL", help="connect to the server at this address and play on it")
    online.add_argument("--use-found", action="store_true",
                        help="move the server PLAY plays on to the address the last connection test found it at "
                             "(Online's Use this address): its sign-in goes with it, its app for the old address goes")
    online.add_argument("--sign-in", metavar="ID", help="sign in to the server (the password from standard input)")
    online.add_argument("--sign-out", action="store_true", help="forget the sign-in")
    online.add_argument("--app", action="store_true", help="download the server's app, or a newer one")
    online.add_argument("--servers", action="store_true",
                        help="list the servers this launcher knows, the one PLAY plays on marked *")
    online.add_argument("--forget", metavar="URL", help="forget a server, its sign-in and its app")
    settings = p.add_argument_group("settings")
    settings.add_argument("--set", metavar="NAME=VALUE", action="append", default=[],
                          help="change a PC setting: " + ", ".join(choices.NAMES) + " (show_fps=on|off; "
                               "fps_position=top_left|top_right|bottom_left|bottom_right, the counter's corner, "
                               "bottom_right unless chosen; fps=auto|unlimited|30 to 1000; volume, music_volume, "
                               "effects_volume=0 to 100; eq=flat|bass|vocal|treble|custom, eq_low, eq_mid, "
                               "eq_high=-12 to 12 dB, a band set alone making the equaliser custom; keyboard=on|off, "
                               "keyboard play; keys_2line=\"F J\", keys_3line=\"D F J\", keys_4line=\"D F J K\": the lanes "
                               "from the top separated by spaces, a lane's keys one or two joined by /, each named as "
                               "the US layout's key at its place)")
    settings.add_argument("--reset-keys", action="store_true",
                          help="each LINE mode's keys back to their defaults (the Controls page's Reset keys)")
    settings.add_argument("--audio-devices", action="store_true", help="list the sound devices the player can play on")
    settings.add_argument("--language", choices=st.LANGUAGES + ("system",),
                          help="the launcher's language (system: Windows' display language)")
    settings.add_argument("--guide", action="store_true", help="open the first-start guide again at the next start")
    settings.add_argument("--skip-guide", action="store_true",
                          help="open the window on its pages next time, the first-start guide done (as the guide's "
                               "Skip)")
    upkeep = p.add_argument_group("help and upkeep")
    upkeep.add_argument("--open-log", choices=("player", "launcher"), help="show the player's or the launcher's log")
    upkeep.add_argument("--report", metavar="FILE",
                        help="save a report for whoever helps: one zip with the logs, the settings, the displays, the "
                             "sound devices, Windows and the graphics card, the user's name, the servers' addresses and "
                             "the sign-ins left out (FILE may be a folder)")
    upkeep.add_argument("--update", action="store_true", help="look for a newer launcher and install it")
    upkeep.add_argument("--repair", action="store_true", help="put back the program's files that are missing or changed")
    upkeep.add_argument("--clear-game-data", action="store_true",
                        help="delete the game's data on this PC (this PC stays the same player)")
    upkeep.add_argument("--reset", action="store_true",
                        help="forget the servers, the sign-ins, the apps and the settings")
    upkeep.add_argument("--uninstall", action="store_true", help="uninstall OpenDMTQ from this PC")
    upkeep.add_argument("--delete-data", action="store_true",
                        help="with --uninstall: delete the settings, sign-ins and game data on this PC too")
    upkeep.add_argument("--yes", action="store_true",
                        help="do not ask before --forget, --reset, --update, --clear-game-data or --uninstall")
    # Velopack passes its own --veloapp-* arguments (each with its value); they are handled before this parser runs and
    # are let through here. Anything else unknown is a mistake, said as argparse says it (exit code 2).
    args, unknown = p.parse_known_args(argv)
    rest, after_velopack = [], False
    for item in unknown:
        if item.startswith("--veloapp-"):
            after_velopack = True
        elif after_velopack and not item.startswith("-"):
            # The value of the --veloapp-* argument before it.
            after_velopack = False
        else:
            rest.append(item)
            after_velopack = False
    if rest:
        p.error("unrecognized arguments: %s" % " ".join(rest))
    if args.delete_data and not args.uninstall:
        p.error("--delete-data goes with --uninstall")
    alone = [args.repair, args.clear_game_data, args.uninstall]
    others = _jobs(args, maintenance=False)
    if sum(map(bool, alone)) > 1 or (any(alone) and others):
        p.error("--repair, --clear-game-data and --uninstall each run on their own")
    return args


def _writes(args):
    """Whether the command line changes what the launcher keeps (refused while its window is open)."""
    return any((args.set, args.reset, args.forget, args.language, args.guide, args.server, args.sign_in,
                args.sign_out, args.uninstall, args.skip_guide, args.use_found, args.reset_keys))


def window_open():
    """True while a launcher window is open (the mutex _single_instance makes); False off Windows."""
    from opendmtq_client import installer
    return installer.launcher_open()


def _jobs(args, maintenance=True):
    """Whether the command line asks for any job (none: the window); with `maintenance` False, any but --repair,
    --clear-game-data and --uninstall."""
    return any((args.status, args.server, args.sign_in, args.sign_out, args.app, args.set, args.audio_devices,
                args.language, args.guide, args.open_log, args.play, args.forget, args.reset, args.update,
                args.skip_guide, args.servers, args.report, args.test_server is not None, args.use_found,
                args.records, args.my_page, args.reset_keys)) or (
        maintenance and any((args.repair, args.clear_game_data, args.uninstall)))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # The log first, so a failure in Velopack's own start-up handling is written down too. Not in the uninstall hook
    # after Delete all, nor in the card after an uninstall: the folder it was in may be gone, and a log would make it
    # again.
    from opendmtq_client import installed
    # The uninstall's own runs (from Windows' Settings, Apps) keep to a log folder that is there already: the data the
    # player chooses to delete may be gone, and a log would make it again.
    uninstalling = argv[:1] == [installed.UNINSTALL_WINDOW] or (argv[:1] == [UNINSTALL_FROM] and len(argv) == 2)
    _logging(make=not (uninstalling or any(a.startswith("--veloapp-uninstall") for a in argv)))
    # The arguments as given: the password never is one (it comes from standard input).
    log.info("OpenDMTQ %s started%s", __version__, (": " + " ".join(argv)) if argv else "")
    if uninstalling:
        # Before Velopack's start-up handling and the entry: the program's folder is about to go.
        return _uninstall_window(argv)
    _velopack_hooks(argv)
    # Windows' entry in Settings, Apps made OpenDMTQ's own at each start too: an install or an update made before this
    # launcher could, or one whose hook did not run (installed.own_entry).
    _own_entry()
    args = parse(argv)
    jobs = _jobs(args)
    if jobs and _writes(args) and window_open():
        # The window keeps its own copy of the settings and writes it back: a change made here would be lost.
        _say("The launcher's window is open: make this change there, or close the window first.", error=True)
        return 2
    if args.repair or args.clear_game_data or args.uninstall:
        # Before the settings are read: none of this needs them, and after --delete-data a save would bring them back.
        return _maintain(args)
    if not jobs:
        # The console copy started with no job (a double click on OpenDMTQ-cmd.exe): the window opens as from the
        # shortcut, and the console Windows opened for it goes, never a black box beside the launcher.
        _leave_own_console()
        # The window copy: sharp at any scaling and only once, settled before any window (a dialog too) opens.
        dpi.aware()
        if not _single_instance():
            return 0
    try:
        state = st.LauncherState.load()
    except st.StateError as e:
        _say(str(e), error=True)
        if not (_windowed() and not jobs and _cannot_start(e)):
            return 2
        state = st.LauncherState.load()
    # A server an installer brought: the one to play on from now on (the guide's server step checks it). With the
    # window open, the window takes it (app._take_preset).
    brought = None if jobs and window_open() else preset.take()
    if brought is not None:
        try:
            # Written as the launcher writes every address, so that connecting to it later finds this same entry.
            url = srv.normalize(brought["url"])
        except srv.ServerError:
            # An address the launcher cannot read: the guide asks for one instead.
            url = None
            log.warning("the installer brought an address that is none: %r", brought["url"])
        if url:
            state.add_server(url, brought["name"])
            # The ID Play on this PC brought (the owner's): in the sign-in form, while that server is not signed in.
            if state.fill_account(url, brought.get("account")):
                log.info("the installer brought the ID %s to sign in with", brought["account"])
            state.save()
            log.info("the installer brought the server %s", url)
    try:
        return _run(state, args, jobs)
    except (srv.ServerError, choices.ChoiceError, actions.NotReady, player.NotAPackage, FileNotFoundError) as e:
        _say(str(e), error=True)
        return 2
    finally:
        # Whatever a job changed stays, also after a failure further on (a server added, a sign-in that ended).
        if jobs:
            state.save()


def _language_set(args):
    """--set language=VALUE is --language's other spelling, as the settings' table lists it with the pages' settings:
    taken out of --set into --language, checked as --language checks it."""
    rest = []
    for item in args.set:
        name, _, value = item.partition("=")
        if name.strip() != "language":
            rest.append(item)
            continue
        value = value.strip().lower()
        if value not in st.LANGUAGES + ("system",):
            raise choices.ChoiceError("language cannot be %r: it is en, ko or system" % value, "error.choice",
                                      name="language", value=value)
        args.language = value
    args.set = rest


def _window_fits(args):
    """--set window=WxH refused for a size the Screen page leaves out: smaller than the game's window holds at Windows'
    scale on the main display, or larger than it with room for the window's title bar and the taskbar (values.fits, the
    page's own check). Checked before anything is changed."""
    from opendmtq_client import displays
    for item in args.set:
        name, _, value = item.partition("=")
        if name.strip() != "window":
            continue
        display = displays.main_display()
        size = value.strip().lower()
        if choices.too_small(size, display):
            # Smaller than the game's window holds at Windows' scale on this display: the player would open it larger.
            least = "%d x %d" % choices.smallest_on(display)
            raise choices.ChoiceError("window cannot be %s: the game's window is at least %s on this display"
                                      % (value.strip(), least), "error.window.too_small", size=value.strip(), least=least)
        if not choices.fits(size, display):
            raise choices.ChoiceError("window cannot be %s: it does not fit this %d x %d display with the window's title "
                                      "bar and the taskbar" % (value.strip(), display["width"], display["height"]),
                                      "error.window.too_big", size=value.strip(), w=display["width"],
                                      h=display["height"])


def _check_settings(state, args):
    """Every --set checked before any is applied, as window= is (_window_fits): one the launcher does not take, wherever
    it stands in the line, refuses them all, and nothing of them is kept. Each is checked over the ones before it, as
    they would be applied (a corner given as show_fps's value moves fps_position with it)."""
    trial = dict(state.values)
    for item in args.set:
        name, _, value = item.partition("=")
        trial[name.strip()] = value.strip()
        if name.strip() in choices.EQ_BANDS:
            # As state.set_value takes a band: the equaliser the player's own from then on.
            trial["eq"] = "custom"
        # As state.set_value checks it: the whole set normalized, a ChoiceError for the value it does not take.
        trial = choices.normalize(trial)


def _test_server(state, address):
    """--test-server [ADDRESS]: the window's connection test (connection.py) of ADDRESS, or of the server PLAY plays on,
    in the window's English words: a title, the verdict, then each step as it ends with its mark, its name, what it found
    and how long it took. 0 when every step passed, 1 when one failed, 2 with no server to test."""
    from opendmtq_client import connection
    w = i18n.Words("en")
    if not address:
        if state.server() is None:
            _say("No server to test: connect with --server URL, or give the address (--test-server ADDRESS).", error=True)
            return 2
        address = state.current
    try:
        # A server this launcher knows: its sign-in is tested too.
        known = state.server(srv.normalize(address))
    except srv.ServerError:
        known = None
    _show(console.heading(w("test.title")))
    width = max(len(w("test." + key)) for key in connection.STEPS)
    marks = {"ok": "ok", "warn": "warn", "bad": "fail", "skip": "skip"}

    def said(step):
        mark = marks.get(step.state, "skip")
        found = w.say(step.said) if step.said else ""
        took = "  (%s)" % connection.took(step.ms) if step.ms is not None and step.state != "skip" else ""
        _say("  [%s] %s: %s%s" % (console.MARKS[mark][0].ljust(4), w("test." + step.key), found, took),
             shown="  %s %s  %s%s" % (console.mark(mark), console.paint(w("test." + step.key).ljust(width), "muted"),
                                      found, console.paint(took, "faint")))

    result = connection.run(address, known, report=said)
    _show("")
    _say(w.say(result.verdict()), error=result.failed() and not result.moved)
    return 1 if result.failed() else 0


def _report(state, target):
    """--report FILE: Help's Save a report, into FILE (a folder: the report's own name in it); the file and what was left
    out said, in the window's English words."""
    from opendmtq_client import report
    path = os.path.abspath(target)
    if os.path.isdir(path):
        # A folder: the name the window gives it, for this moment.
        path = os.path.join(path, os.path.basename(report.default_path()))
    elif not path.lower().endswith(".zip"):
        # A zip by its name too, as Windows opens it.
        path += ".zip"
    path, left = report.make(state, path=path)
    _say("Saved the report: %s" % path)
    _say("Left out: %s." % report.left_words(i18n.Words("en"), left))


def _servers(state):
    """--servers: every server this launcher knows, as Online lists them, the one PLAY plays on first and marked *."""
    if not state.servers:
        _say("No servers yet (connect with --server URL).")
        return
    for server in sorted(state.servers, key=lambda s: s["url"] != state.current):
        current = server["url"] == state.current
        # The one PLAY plays on marked, in lime in a terminal.
        _say("%s %s" % ("*" if current else " ", st.label(server)),
             shown="%s %s" % (console.paint("*", "ok") if current else " ", console.paint(st.label(server), bold=current)))


def _use_found(state):
    """--use-found: Online's Use this address. The server PLAY plays on moves to the address its last connection test
    found it at (another port of its host), asked there first, its sign-in and its own authority taken along; its app,
    built for the old address, goes (actions.move_server). Refused when the last test found no such address, and while a
    game plays from that app. 0 when it moved, 2 when not."""
    from opendmtq_client import connection
    if state.server() is None:
        _say("No server to move: connect with --server URL.", error=True)
        return 2
    tested = connection.last()
    if tested is None or tested.url != state.current or not tested.moved:
        # The window offers Use this address only on such a test's card: here the test is the step before.
        _say("The last connection test of %s found it at no other address: test it first (--test-server)."
             % state.current, error=True)
        return 2
    if _started_meanwhile():
        return 2
    found = actions.move_server(state, state.current, tested.moved)
    # The server by its name and its new address, as --server's line says one (the report knows both by this line).
    _say("Moved to %s (%s): PLAY plays on it from now on." % (found["name"], state.current))
    return 0


def _record_words(w, row, recent):
    """One record as PLAY's My records shows it, in `w`'s words: its chart ("3 LINE Hard 9"), the score, the keyboard's
    mark when a keyboard played it, the player's place on that chart, when, and a play's new record or a best's grade."""
    parts = [choices.chart_words(row["chart_name"])] if row["chart_name"] else []
    parts.append("{:,}".format(row["score"]))
    if row["keys"]:
        parts.append(w("play.records.keys"))
    if row["rank"]:
        parts.append(w("play.records.place", n=row["rank"], all=max(row["players"], row["rank"])))
    if row["at"]:
        parts.append(w.say(i18n.ago(row["at"])))
    if not recent and row["grade"]:
        parts.append(w("play.records.grade", grade=row["grade"]))
    if recent and row["new_record"]:
        parts.append(w("play.records.new"))
    return parts


def _records(state):
    """--records: PLAY's My records, the signed-in account's player's latest plays and best records on the server, each
    list under its name and each record as the PLAY page shows it (_record_words), in the window's English words; the
    page's one line for an account linked to no player. 0 when the server answered, 2 for a server older than records."""
    w = i18n.Words("en")
    answer = actions.records(state)
    if answer is None:
        _say("%s keeps no records for PCs (an OpenDMTQ older than 0.11)." % state.current, error=True)
        return 2
    if answer["player"] is None:
        # The site account has no game player linked to it on this server.
        _say(w("play.records.unlinked", account=answer["account"] or state.server()["account"]))
        return 0
    for title, rows, recent in ((w("play.records.recent"), answer["recent"], True),
                                (w("play.records.best"), answer["best"], False)):
        _show(console.heading(title))
        if not rows:
            _say("%s: %s" % (title, w("play.records.none")), shown="  " + w("play.records.none"))
            continue
        names = [row["title"] or w("play.records.chart", id=row.get("chart") or "") for row in rows]
        width = max(len(name) for name in names)
        for name, row in zip(names, rows):
            said = ", ".join(_record_words(w, row, recent))
            # In a terminal the titles in a column, bold; in the log and a pipe, each list's name first.
            _say("%s: %s: %s" % (title, name, said), shown="  %s  %s" % (console.paint(name.ljust(width), bold=True), said))
    return 0


def _my_page(state):
    """--my-page: PLAY's My page on the site, opened in the PC's browser signed in already (a one-time link the server
    makes for this sign-in; a server older than such links, its site's own address), said as the window says it. The
    link signs a browser in once: it is never printed or logged. 0 when the browser opened it, 2 when not."""
    w = i18n.Words("en")
    url = actions.my_page(state)
    try:
        actions.open_url(url)
    except OSError as e:
        # No browser to open it with: said, the address without its link in the log.
        log.warning("could not open %s: %s", url.split("?", 1)[0], e)
        _say("The browser did not open: %s" % e, error=True)
        return 2
    _say(w("status.mypage.opened" if "once=" in url else "status.site.opened"))
    return 0


def _run(state, args, jobs):
    """The jobs the command line asked for, in order; else the window."""
    if args.update:
        return _update(args.yes)
    _language_set(args)
    _window_fits(args)
    # Every --set checked here, before anything of the line is changed.
    _check_settings(state, args)
    if args.reset:
        # Every server's app goes: refused while a game plays from one, as the window's Start over is.
        if _started_meanwhile():
            return 2
        if not _ask("Forget every server, sign-in, downloaded app and setting?", args.yes):
            _say("Nothing changed.")
            return 1
        if _started_meanwhile():
            return 2
        actions.reset(state)
        _say("Started over: the launcher opens its first-start guide next time.")
        return 0
    if args.forget:
        url = srv.normalize(args.forget)
        if state.server(url) is None:
            _say("This launcher does not know %s." % url, error=True)
            return 2
        # The server in use: a game may be playing from its app, which goes too (Online's Forget waits as well).
        in_use = url == state.current
        if in_use and _started_meanwhile():
            return 2
        if not _ask("Forget %s, its sign-in and its app on this PC?" % url, args.yes):
            _say("Nothing changed.")
            return 1
        if in_use and _started_meanwhile():
            return 2
        actions.forget(state, url)
        _say("Forgot %s." % url)
    for item in args.set:
        name, _, value = item.partition("=")
        state.set_value(name.strip(), value.strip())
        # A corner given as show_fps's value is the counter on in that corner: both settings said.
        said = [name.strip()] + (["fps_position"] if name.strip() == "show_fps" else [])
        _say(", ".join("%s=%s" % (n, state.values[n]) for n in said))
    if args.reset_keys:
        # The Controls page's Reset keys: each LINE mode's keys back to their defaults, said as --set says them.
        for name in choices.LANES:
            state.set_value(name, choices.DEFAULTS[name])
        _say(", ".join("%s=%s" % (name, state.values[name]) for name in choices.LANES))
    if args.set or args.reset_keys:
        # The player's settings file as they are now, as the window writes it at each change: the player's in-game
        # menu writes its sound back into it, and the window takes from it only what is newer than its own settings.
        player.write_settings(state.values, state.picked_language)
    if args.language:
        # "system": no choice kept, Windows' display language from now on.
        state.language = None if args.language == "system" else args.language
        _say("language=%s" % (state.picked_language or "system (%s now)" % state.language))
    if args.guide:
        # The window opens on the guide next time, as Launcher's "Show it again" does.
        state.guide_done = False
        _say("The window opens the first-start guide next time.")
    if args.skip_guide:
        # The guide done, as its "Skip: I set it up myself" leaves it: a PC set up from the command line opens on PLAY.
        state.guide_done = True
        _say("The window opens on its pages next time, without the first-start guide.")
    if args.server:
        # No address at all: refused by the window's own check, in its words, before the server is asked anything.
        url = srv.normalize(args.server)
        try:
            found = actions.connect(state, url)
            _say("Connected to %s (%s)." % (found["name"], state.current))
        except srv.ServerError:
            known = state.server(url)
            if known is None:
                raise
            # A server this launcher knows plays without asking it, as Online's "Play here" does.
            state.current = known["url"]
            _say("%s did not answer; playing on it as known (%s)." % (known["name"], known["url"]))
    if args.use_found:
        if args.test_server is not None:
            # The test first, as the window's Use this address follows its test: the address it finds is the one used.
            _test_server(state, args.test_server)
            args.test_server = None
        code = _use_found(state)
        if code:
            return code
    if args.sign_out:
        actions.sign_out(state)
        _say("Signed out.")
    if args.sign_in:
        answer = actions.sign_in(state, args.sign_in, _password("Password for %s: " % args.sign_in))
        _say("Signed in as %s." % answer["account"])
    if args.app:
        _get_app(state)
    if args.records:
        code = _records(state)
        if code:
            return code
    if args.my_page:
        code = _my_page(state)
        if code:
            return code
    if args.audio_devices:
        devices = player.audio_devices()
        if not devices:
            _say("The player listed no sound devices (the game plays through Windows' default output).")
        for d in devices:
            # Its name (the default one marked in lime), its id under it in grey, as --set audio_device= takes it.
            _say("%s%s\n    %s" % (d["name"], "  (default)" if d["default"] else "", d["id"]),
                 shown="%s%s\n    %s" % (console.paint(d["name"], bold=True),
                                          console.paint("  (default)", "ok") if d["default"] else "",
                                          console.paint(d["id"], "muted")))
    if args.open_log:
        path = _log_paths(state)[args.open_log]
        if path is None:
            _say("There is no player's log yet: the current server's app is not on this PC.", error=True)
            return 2
        if not os.path.isfile(path):
            # Nothing is made in its place: the player writes its log itself when the game first starts.
            _say("There is no %s's log yet: %s" % (args.open_log, path), error=True)
            return 2
        _say(path)
        actions.show_file(path)
    if args.servers:
        _servers(state)
    if args.report:
        _report(state, args.report)
    if args.test_server is not None:
        return _test_server(state, args.test_server)
    if args.status:
        return _status(state)
    if args.play:
        return _play(state)
    if jobs:
        return 0
    from opendmtq_client.app import LauncherApp
    LauncherApp(state).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
