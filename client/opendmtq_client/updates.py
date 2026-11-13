"""Updates of the installed launcher and its player, through Velopack (the installer's own update channel).

Only a launcher installed by OpenDMTQ-Setup.exe can update itself; one run from source or from a copied folder says so
instead. Where releases are published is set when the launcher is built: client/packaging/windows/build.sh writes the
OPENDMTQ_UPDATE_SOURCE it was given (a GitHub repository URL, an HTTP folder or a local folder) into update-source.txt
next to this module. A build made without one has no update address and says so. The same variable at run time takes
its place, for trying a feed out. Every call here may be slow (network), so the window runs them on a worker thread.
"""

import logging
import os
import threading
import time

log = logging.getLogger("opendmtq_client")

# How long the look for a newer launcher at each start waits for the release feed, in seconds: past it the launcher
# says nothing, as it says nothing offline. Velopack's GitHub source takes no time limit of its own.
START_LIMIT = 10

SOURCE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "update-source.txt")


def _update_source():
    """The release feed: the variable when it is set, else the one written in at build time, else none."""
    if os.environ.get("OPENDMTQ_UPDATE_SOURCE"):
        return os.environ["OPENDMTQ_UPDATE_SOURCE"].strip()
    try:
        with open(SOURCE_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


UPDATE_SOURCE = _update_source()


class Result:
    """What a check found: kind is 'none', 'not_installed', 'no_source', 'uptodate', 'available' or 'failed'. A failed
    check's `error` is Velopack's own words for it, for the log: a person reads it by its kind (i18n Words.failed)."""

    def __init__(self, kind, version=None, info=None, error=None):
        self.kind, self.version, self.info, self.error = kind, version, info, error


def _manager():
    """The Velopack update manager, or None when the launcher was not installed by its setup."""
    if not UPDATE_SOURCE:
        return None
    import velopack
    source = UPDATE_SOURCE
    # A GitHub repository URL reads the repository's releases; anything else is a feed folder or URL.
    if source.startswith("https://github.com/"):
        source = velopack.GithubSource(source, None, False)
    return velopack.UpdateManager(source)


def current_version():
    """The installed version, or None outside an installed launcher."""
    try:
        import velopack
        return velopack.UpdateManager(UPDATE_SOURCE or ".").get_current_version()
    except Exception:  # noqa: BLE001  (not installed: run from source or a copied folder)
        return None


def shown_version():
    """The version the launcher shows, beside the logo, on the Launcher page and on the command line: the installed one,
    else the code's own (a run from source or from a copied folder). One source for all of them, so that after an
    update none of them says an older number than the others."""
    # Imported here: the package's __init__ reads the version once, and this module is imported by it indirectly.
    from opendmtq_client import __version__
    # Velopack's installed version first: what the installer put in and the updates moved on.
    return current_version() or __version__


def check():
    """Ask the release feed whether a newer version exists."""
    try:
        import velopack  # noqa: F401  (only to know whether the update library is there)
    except ImportError:
        return Result("not_installed")
    if not UPDATE_SOURCE:
        return Result("no_source")
    try:
        manager = _manager()
        info = manager.check_for_updates()
        if not info:
            return Result("uptodate")
        # Read here too: an answer without the release it offers is a failed check, said as one, never an error that
        # ends the worker thread with the Launcher page still saying it is checking.
        return Result("available", version=info.TargetFullRelease.Version, info=info)
    except Exception as e:  # noqa: BLE001
        text = str(e)
        # Velopack refuses outside an installation: a state of this copy, which the page says as such.
        if "not installed" in text.lower() or "locator" in text.lower():
            return Result("not_installed")
        # Velopack's own words ("Network error: Http error: io: ...") are for the log; the page and --update say the
        # failure by its kind.
        log.warning("could not check for updates: %s", text)
        return Result("failed", error=text)


class Look:
    """The look for a newer launcher that each start makes (the window's, --status's): check() on a thread of its own,
    started at once, so that what the start does meanwhile waits for nothing. Nothing is downloaded or installed."""

    def __init__(self, limit=None):
        # The time it may take (START_LIMIT, read now), counted from now: a start that asks for the answer later waits
        # only for what is left.
        self.started, self.limit = time.monotonic(), START_LIMIT if limit is None else limit
        self._result, self._done = None, threading.Event()
        threading.Thread(target=self._look, daemon=True, name="update-look").start()

    def _look(self):
        try:
            self._result = check()
        finally:
            # Answered, whatever the answer: newer() stops waiting.
            self._done.set()

    def newer(self):
        """The newer version on offer (check()'s result, kind "available"), or None for anything else: up to date, no
        network, a failure, a launcher not installed, or no answer within the time limit (the look goes on, and its
        late answer is dropped)."""
        left = self.limit - (time.monotonic() - self.started)
        if not self._done.wait(max(0.0, left)):
            log.info("no answer about updates within %d s at the start: nothing said", self.limit)
            return None
        result = self._result
        return result if result is not None and result.kind == "available" else None


def apply(result):
    """Download the update and hand it to Velopack, which puts it in once this program has ended and then starts
    the new launcher. The caller ends the program right after.

    Velopack applies it silently: the launcher's own dialog has said what happens, and Velopack's would be a
    plain system window with a progress bar.
    """
    manager = _manager()
    manager.download_updates(result.info)
    # A note for the next start: Velopack says nothing when a silent update fails, so the new start compares.
    _note_pending(result.version)
    manager.wait_exit_then_apply_updates(result.info, silent=True, restart=True)


PENDING = "update-pending.json"


def _note_pending(version):
    import json
    from opendmtq_client import __version__
    from opendmtq_client import state as st
    os.makedirs(st.config_dir(), exist_ok=True)
    with open(os.path.join(st.config_dir(), PENDING), "w", encoding="utf-8") as f:
        json.dump({"to": version, "from": current_version() or __version__}, f)


def outcome():
    """After an update was handed to Velopack: ("updated", version) or ("not_updated", version, this version),
    once; None when no update was waiting."""
    import json
    from opendmtq_client import __version__
    from opendmtq_client import state as st
    path = os.path.join(st.config_dir(), PENDING)
    try:
        with open(path, encoding="utf-8") as f:
            note = json.load(f)
    except (OSError, ValueError):
        return None
    try:
        os.remove(path)
    except OSError:
        pass
    now = current_version() or __version__
    target = str(note.get("to", ""))
    if target and now == target:
        return ("updated", target)
    return ("not_updated", target, now)
