"""The player for Windows, as the launcher uses it: where it is, the sound devices it can play on, the settings file it
reads, and a game started in it.

The installer puts the player beside the launcher, in player\\ of the installed folder (the release's player for
Windows, unchanged). The launcher starts it for a server's app (apps.py) with the PC settings:

    OpenDMTQ-Player.exe --app <the server's folder> --settings <settings file>

and asks it for the sound devices with --audio-devices (one JSON object a line). The player keeps the game's data and
its own log in %LOCALAPPDATA%\\OpenDMTQ\\<package>, where a phone's app would keep its own.
"""

import json
import logging
import os
import subprocess
import sys
import time

from opendmtq_client import errors, safety
from opendmtq_client import server as srv
from opendmtq_client import state as st
from opendmtq_client import values as choices

log = logging.getLogger("opendmtq_client")

EXE = "OpenDMTQ-Player.exe"
SETTINGS = "player-settings.txt"
# How long the player may take to list the sound devices.
DEVICES_TIMEOUT = 10
# Windows: start a console program without a console window of its own (CREATE_NO_WINDOW).
NO_WINDOW = 0x08000000


def player_path():
    """The player program: OPENDMTQ_PLAYER when set (a developer's build, a test's stand-in), else player\\ beside the
    installed launcher; None when there is none."""
    named = os.environ.get("OPENDMTQ_PLAYER")
    if named:
        return named if os.path.isfile(named) else None
    if getattr(sys, "frozen", False):
        path = os.path.join(os.path.dirname(sys.executable), "player", EXE)
        return path if os.path.isfile(path) else None
    # Run from a checkout: no player beside the code.
    return None


def _command(path):
    """How to run a player: a stand-in script of the tests through this Python, a program as it is."""
    return [sys.executable, path] if path.endswith(".py") else [path]


def audio_devices(path=None):
    """The sound devices the player can play on: [{"id", "name", "default"}], in Windows' order; [] when it cannot
    tell (no player, or none listed)."""
    path = path or player_path()
    if not path:
        return []
    try:
        done = subprocess.run(_command(path) + ["--audio-devices"], capture_output=True, timeout=DEVICES_TIMEOUT,
                              creationflags=NO_WINDOW if sys.platform == "win32" else 0)
    except (OSError, subprocess.SubprocessError) as e:
        # The page then offers Windows' default device alone: the log says why there were no others.
        log.warning("could not list the sound devices with %s: %s", path, e)
        return []
    if done.returncode != 0:
        # The devices it listed before it stopped still count; its last words say why it stopped.
        said = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
        log.warning("the player ended with %d listing the sound devices%s", done.returncode,
                    ": " + said[-1] if said else "")
    devices = []
    for line in done.stdout.decode("utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            # A line that is no device (a word from Windows itself): skipped.
            continue
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
            devices.append({"id": item["id"], "name": str(item.get("name") or item["id"]), "default": bool(item.get("default"))})
    return devices


def settings_path():
    """The settings file the launcher writes before each start."""
    return os.path.join(st.config_dir(), SETTINGS)


def write_settings(values, language=None):
    """The PC settings as the player reads them; returns the file's path. `language` is the launcher's language when the
    player chose one ("en", "ko"): the game and the player's own words (the bar, the question before quitting) then
    speak it instead of Windows' display language. None, the launcher following Windows, leaves it out: the player
    follows Windows too."""
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(choices.settings_text(values))
        if language:
            # On a line of its own after the PC settings: the player reads it as one of them (settings.cpp).
            f.write("language=%s\n" % language)
    os.replace(tmp, path)
    return path


class NotAPackage(errors.Worded):
    """An app on this PC whose package name is none (data_folder): the game does not start with it."""


def data_folder(package):
    """The player's own folder for an app: the game's data, its libraries and player.log. It is made of the app's
    package name, as the player makes it, so only an Android package name will do (server.PACKAGE, the rule a server's
    answer is held to): an app an older launcher kept without that check could name a path, which would lead out of
    OpenDMTQ's folder. NotAPackage for anything else."""
    if not isinstance(package, str) or not srv.PACKAGE.match(package):
        raise NotAPackage("the app on this PC has no proper package name (%r); get the app again" % (package,),
                          "error.app.package")
    return os.path.join(st.local_dir(), "OpenDMTQ", package)


def log_path(package):
    """The player's log for an app (NotAPackage, as data_folder, for a package name that is none)."""
    return os.path.join(data_folder(package), "player.log")


def app_log(have):
    """The player's log for an app this PC has (apps.local), to show or open: None without an app, or with one whose
    package name is none (the game never started with it)."""
    try:
        return log_path(have["package"]) if have else None
    except NotAPackage:
        return None


class Session:
    """A game the launcher started, while it runs and after."""

    def __init__(self, process, app_folder):
        self.process = process
        self.app_folder = app_folder
        self.started = time.time()

    def running(self):
        return self.process.poll() is None


def start(app_folder, settings_file, path=None, log_file=None):
    """Start the game for a server's app (its folder from apps.py) with the PC settings; returns the Session.

    log_file is the player's own log for this app (log_path): the player gets it as its standard output and error. A
    program the windowed launcher starts has none of its own, and without them the player's own lines would have
    nowhere to go; it then also sends them there itself, to the same file.
    """
    path = path or player_path()
    if not path:
        raise FileNotFoundError("the player is not beside the launcher (install it again)")
    if not path.endswith(".py"):
        # The game's window: never on a real screen from a test (a test's stand-in script opens none).
        safety.refuse_windows_in_tests("the game's player")
    output = None
    if log_file:
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            # Appended to, as the player appends: what an earlier game wrote stays.
            output = open(log_file, "ab")
        except OSError:
            # A log that cannot be opened is no reason not to play.
            output = None
    try:
        process = subprocess.Popen(_command(path) + ["--app", app_folder, "--settings", settings_file],
                                   cwd=os.path.dirname(path) or None, close_fds=True, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT if output else None)
    finally:
        # The player has its own copy of the handle now; the launcher's goes.
        if output is not None:
            output.close()
    return Session(process, app_folder)


def finish(session):
    """How a game that ended went: {"seconds", "exit_code", "crashed"}. The player ends with 0 after a game that
    closed normally, 1 when it could not start, and with Windows' code of the fault when it crashed."""
    code = session.process.wait()
    # 1 is the player's own "could not start" (no window, no display, the app's files): no crash, and its log says why.
    return {"seconds": int(time.time() - session.started), "exit_code": code, "crashed": code not in (0, 1),
            "failed_start": code == 1}
