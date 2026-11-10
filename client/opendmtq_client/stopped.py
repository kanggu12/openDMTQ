"""What an error nobody expected ends in: the launcher's own dialog, never Python's or PyInstaller's plain box.

OpenDMTQ.exe and OpenDMTQ-Setup.exe have no console, and PyInstaller shows a plain Windows box with a traceback for an
error that ends the program. run() catches it first: the error goes to the log, then the launcher's dialog says it in
the player's language, with where the log is. The console copy, OpenDMTQ-cmd.exe, says the same on the console.
"""

import logging
import sys

log = logging.getLogger("opendmtq_client")


def windowed():
    """True for a program with no console to print to (the window copy and the installer)."""
    return sys.stdout is None or sys.stderr is None


def run(main, log_path):
    """main() as the programs start it; its exit code, or 1 after an error nobody expected. `log_path()` names the log
    the error went to (asked only then: finding it may itself need what failed)."""
    try:
        return main()
    except SystemExit:
        # A chosen ending (argparse's, a job's): not an error.
        raise
    except Exception as e:  # noqa: BLE001  (any error at all: said in the launcher's dialog, never in PyInstaller's box)
        log.exception("stopped by an error")
        try:
            path = log_path()
        except Exception:  # noqa: BLE001  (where the log is cannot be said: the error itself still is)
            path = "?"
        if not windowed():
            print("OpenDMTQ stopped: %s (the log: %s)" % (e, path), file=sys.stderr)
            return 1
        try:
            show(e, path)
        except Exception:  # noqa: BLE001  (Tk itself failing: there is nothing left to show it with)
            log.exception("could not show the error")
        return 1


def show(error, path):
    """The launcher's dialog for an error that ended the program, in a window of its own, in Windows' language (the
    launcher's settings may be what failed)."""
    from opendmtq_client import dialogs, i18n
    from opendmtq_client import state as st
    language = st.system_language()
    w = i18n.Words(language)
    dialogs.standalone("error", w("stopped.title"), w("stopped.message"),
                       w("stopped.detail", error=w.error(error), path=path),
                       [(w("start.close"), "close", "home")], 0, "close", language=language)
