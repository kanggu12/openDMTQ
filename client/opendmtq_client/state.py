"""What the launcher remembers between runs: the servers it knows and the one it plays on, the sign-in it keeps for
each (the site's cookie, never the password), the PC settings, the language, and how the last game went.

Kept in one small JSON file per Windows user, %LOCALAPPDATA%\\OpenDMTQ\\client\\settings.json, beside the folders it
keeps each server's app in (apps.py) and next to the player's own data (%LOCALAPPDATA%\\OpenDMTQ\\<package>). The
installed program lives elsewhere (%LOCALAPPDATA%\\OpenDMTQ.Client), so an update or a reinstall keeps all of it. Writes
go through a temporary file so a crash never leaves half of it.
"""

import json
import os
import sys
import tempfile
import time

from opendmtq_client import values as choices

FILE_NAME = "settings.json"
# Bumped when a field changes meaning; an older file is read and upgraded, a newer one is refused.
VERSION = 1
LANGUAGES = ("en", "ko")


def system_language():
    """The language Windows is shown in, as the launcher's: "ko" when the user's first display language is Korean,
    "en" for any other, the way the player picks the game's own (arm32/desktop/java_lang.cpp, host_locale). "en" off
    Windows. The tests put their own in its place: none of them depends on the computer's language."""
    if sys.platform != "win32":
        return "en"
    try:
        tag = _windows_display_language()
    except (AttributeError, OSError, ValueError):
        # No answer from Windows: English, the launcher's own first language.
        return "en"
    # "ko-KR", "ko": the language is the part before the first hyphen.
    return "ko" if tag.split("-")[0].lower() == "ko" else "en"


def _windows_display_language():
    """The first of the user's display languages as Windows names it ("ko-KR"), or "ko"/"en" from the older call."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.windll.kernel32
    mui_language_name = 0x8
    count, size = wintypes.ULONG(0), wintypes.ULONG(0)
    # Asked twice: first for the size of the list, then for the list itself (names, each ended by a NUL).
    if kernel.GetUserPreferredUILanguages(mui_language_name, ctypes.byref(count), None, ctypes.byref(size)) and size.value:
        names = ctypes.create_unicode_buffer(size.value)
        if kernel.GetUserPreferredUILanguages(mui_language_name, ctypes.byref(count), names, ctypes.byref(size)) \
                and count.value and names.value:
            # The buffer's value stops at the first NUL: the first language alone.
            return names.value
    # Older Windows: the display language as a number, whose low 10 bits name the language (0x12 is Korean).
    return "ko" if kernel.GetUserDefaultUILanguage() & 0x3FF == 0x12 else "en"


def local_dir():
    """The user's own folder for programs' data: %LOCALAPPDATA% on Windows, the XDG data folder elsewhere."""
    if sys.platform == "win32":
        return os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")


def config_dir():
    """The folder for the launcher's settings, logs and servers' apps.

    OPENDMTQ_CLIENT_DIR overrides it (the tests use a temporary folder); otherwise %LOCALAPPDATA%\\OpenDMTQ\\client,
    beside the player's own folders for each app.
    """
    override = os.environ.get("OPENDMTQ_CLIENT_DIR")
    if override:
        return override
    return os.path.join(local_dir(), "OpenDMTQ", "client")


def launcher_log():
    """The launcher's log, in its folder's logs (main._logging writes it, the two before it beside it): what Help opens,
    --open-log launcher and --status name, and the dialogs for an error say."""
    return os.path.join(config_dir(), "logs", "launcher.log")


class StateError(Exception):
    """The settings file is from a newer launcher (`newer`), or broken beyond reading."""

    def __init__(self, message, path, newer=False):
        super().__init__(message)
        self.path, self.newer = path, newer


def _server(entry):
    """A server as the file keeps it, with every field there (a hand-edited or older entry gets the defaults)."""
    if not isinstance(entry, dict) or not isinstance(entry.get("url"), str) or not entry["url"]:
        raise ValueError("a server without an address")
    app = entry.get("app")
    return {
        "url": entry["url"],                                  # the site's address: http(s)://host[:port]
        "name": str(entry.get("name") or entry["url"]),      # what the server calls itself (client.php?about)
        "address": str(entry.get("address") or ""),          # the host and port its app is built for
        "account": entry.get("account") or None,              # the site account signed in as, or None
        "cookie": entry.get("cookie") or None,                # the site's sign-in cookie for it, or None
        "expires": int(entry.get("expires") or 0),            # when that sign-in ends (Unix time; 0: none)
        "app": app if isinstance(app, dict) else None,        # the server's app as it last described it
    }


class LauncherState:
    """The remembered settings. Each field has a safe default, so a missing file means a first start.

    One thread changes and saves them: the command line's, or the window's own (its worker threads hand every change
    to it, actions.py's `change`), so a save never meets a change half made. Other threads only read them."""

    def __init__(self):
        self.picked_language = None             # the language the player chose; None: Windows' display language
        self.guide_done = False                 # the first-start guide was finished or skipped
        self.values = choices.normalize({})     # the PC settings for the picture and the sound, all filled in
        self.chosen = set()                     # the settings the player chose (from 0.9.3 on), by name
        self.servers = []                       # the servers this launcher knows (see _server)
        self.current = None                     # the address of the one PLAY plays on, or None
        self.last_session = None                # {"seconds", "exit_code", "crashed"} of the last game
        self.discarded = False                  # Delete all removed the folder (removal.py): nothing is written again

    @property
    def language(self):
        """The launcher's language: the one the player chose, else the one Windows is shown in (system_language)."""
        return self.picked_language or system_language()

    @language.setter
    def language(self, value):
        # Setting it is the player's choice, kept from then on; anything but a known language goes back to Windows'.
        self.picked_language = value if value in LANGUAGES else None

    # ------------------------------------------------------------------------------------------- files

    @classmethod
    def path(cls):
        return os.path.join(config_dir(), FILE_NAME)

    @classmethod
    def load(cls, path=None):
        """The saved state, or a fresh one when there is no file yet."""
        path = path or cls.path()
        state = cls()
        if not os.path.isfile(path):
            return state
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise StateError("cannot read %s: %s" % (path, e), path) from None
        if not isinstance(data, dict):
            raise StateError("cannot read %s: not a settings file" % path, path)
        version = data.get("version", 1)
        if not isinstance(version, int) or isinstance(version, bool):
            # A version that is no whole number is damage: a newer launcher writes a larger whole number.
            raise StateError("cannot read %s: its version is %r" % (path, version), path)
        if version > VERSION:
            # A newer launcher wrote it; reading it with old rules could drop what it added.
            raise StateError("%s is from a newer OpenDMTQ; update the launcher" % path, path, newer=True)
        try:
            return cls._from(data, state)
        except (TypeError, AttributeError, ValueError) as e:
            # A field of the wrong kind (a hand-edited file): the same as a file that cannot be read.
            raise StateError("cannot read %s: %s" % (path, e), path) from None

    @classmethod
    def _from(cls, data, state):
        """Fill `state` from a settings file's data (a field of the wrong kind raises)."""
        # Kept only once the player chose one: without it, the launcher follows Windows' display language.
        state.picked_language = data.get("language") if data.get("language") in LANGUAGES else None
        state.guide_done = bool(data.get("guide_done", False))
        # A hand-edited value the launcher does not offer keeps that setting's default, the others stay.
        state.values = choices.normalize(data.get("values") or {}, strict=False)
        chosen = data.get("chosen")
        state.chosen = {name for name in chosen if name in choices.NAMES} if isinstance(chosen, list) else set()
        # The counter's corner as a launcher before 0.9.3 wrote it, its default then, with no word that the player chose
        # it: the default now (another corner was the player's choice, and stays).
        if "fps_position" not in state.chosen and state.values["fps_position"] == choices.OLD_FPS_POSITION:
            state.values["fps_position"] = choices.DEFAULTS["fps_position"]
        state.servers = [_server(entry) for entry in (data.get("servers") or [])]
        current = data.get("current")
        state.current = current if any(s["url"] == current for s in state.servers) else None
        last = data.get("last_session")
        state.last_session = last if isinstance(last, dict) else None
        return state

    def save(self, path=None):
        """Write the state through a temporary file in the same folder, then swap it in."""
        if self.discarded:
            # The player deleted everything OpenDMTQ keeps: writing would bring the folder back, sign-ins and all.
            return
        path = path or self.path()
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        data = {
            "version": VERSION,
            "language": self.picked_language,
            "guide_done": self.guide_done,
            "values": self.values,
            "chosen": sorted(self.chosen),
            "servers": self.servers,
            "current": self.current,
            "last_session": self.last_session,
        }
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".settings-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

    # ------------------------------------------------------------------------------------------- servers

    def server(self, url=None):
        """The server with this address (the current one by default), or None."""
        url = url or self.current
        return next((s for s in self.servers if s["url"] == url), None)

    def add_server(self, url, name=None, address=None):
        """Know a server (or update what it said of itself) and play on it from now on; returns its entry."""
        found = self.server(url)
        if found is None:
            found = _server({"url": url})
            self.servers.append(found)
        if name:
            found["name"] = name
        if address:
            found["address"] = address
        self.current = url
        return found

    def remove_server(self, url):
        """Forget a server, its sign-in with it; the first one left becomes the current one."""
        self.servers = [s for s in self.servers if s["url"] != url]
        if self.current == url:
            self.current = self.servers[0]["url"] if self.servers else None

    def signed_in(self, server=None, now=None):
        """True while the server's sign-in has not run out (the server may still have ended it: a new password)."""
        server = server or self.server()
        return bool(server and server.get("cookie") and server.get("expires", 0) > (now or time.time()))

    def forget_sign_in(self, server=None):
        """The server no longer takes the sign-in (or the player signed out): only the account's name stays, to fill
        the form in again."""
        server = server or self.server()
        if server:
            server["cookie"] = None
            server["expires"] = 0

    def set_value(self, name, value):
        """Change one PC setting; a value the launcher does not offer raises ChoiceError and changes nothing. The setting
        is the player's choice from then on (a corner given as show_fps's value chooses the counter's corner too)."""
        merged = dict(self.values)
        merged[name] = value
        self.values = choices.normalize(merged)
        self.chosen.add(name)
        if name == "show_fps" and str(value).strip().lower() in choices.FPS_POSITION:
            self.chosen.add("fps_position")
