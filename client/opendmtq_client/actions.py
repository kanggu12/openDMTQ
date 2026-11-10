"""What the launcher's buttons do, without any window: check, connect, sign in, get the app, play.

The window and the command line (OpenDMTQ-cmd.exe) both call these, so a button and its command always run the same
checks.
"""

import logging
import os
import subprocess
import sys

from opendmtq_client import apps, player, playing, safety
from opendmtq_client import server as srv

log = logging.getLogger("opendmtq_client")


class Check:
    """One line of the ready check: whether it is fine, what it says, which page fixes it, and whether PLAY does."""

    def __init__(self, key, ok, detail, page=None, play_fixes=False):
        self.key = key                  # a stable name for the line (the words, the tests and the Help page use it)
        self.ok = ok                    # True: nothing to do
        self.detail = detail            # what it is about, in plain words (a name, an address, a file)
        self.page = page                # the page that fixes it, or None
        self.play_fixes = play_fixes    # PLAY does it by itself (downloads the app it lacks)


# Ready-check lines that stop PLAY until the player fixes them, unless PLAY fixes them by itself.
BLOCKING = ("player", "server", "app", "running")
# The words of a server that did not answer at all (server._unreachable): PLAY then starts this PC's app, and says so.
UNREACHED = ("error.server.unreachable", "error.server.timeout", "error.server.refused", "error.server.unknown_host")


class NotReady(Exception):
    """PLAY cannot go: the lines of the ready check that stop it."""

    def __init__(self, checks):
        super().__init__("; ".join("%s: %s" % (c.key, c.detail) for c in checks))
        self.checks = checks


def can_play(checks):
    """True when no line of the ready check stops PLAY: the window and --play decide the same way."""
    return not stopping(checks)


def stopping(checks):
    """The lines that stop PLAY."""
    return [c for c in checks if not c.ok and c.key in BLOCKING and not c.play_fixes]


def readiness(state):
    """The ready check on the PLAY page and of --status, in the order a player would fix things."""
    lines = []
    path = player.player_path()
    # The player comes with the launcher: without it, installing again is the fix.
    lines.append(Check("player", bool(path), path or "not found", page="help"))
    server = state.server()
    if server is None:
        return lines + [Check("server", False, "no server chosen", page="online")]
    lines.append(Check("server", True, "%s (%s)" % (server["name"], server["url"]), page="online"))
    signed = state.signed_in(server)
    lines.append(Check("account", signed, server.get("account") or "not signed in", page="online"))
    have = apps.local(server["url"])
    if have:
        offered = server.get("app") or {}
        newer = bool(offered.get("sha256")) and offered["sha256"].lower() != have["sha256"]
        # A newer app the server offered at the last look: PLAY gets it first when the sign-in still holds.
        lines.append(Check("app", True, when(have), page="online") if not newer else
                     Check("app_update", False, when(offered), page="online", play_fixes=signed))
    else:
        # No app yet: PLAY downloads it when signed in, else the sign-in comes first (Online).
        lines.append(Check("app", False, "not downloaded", page="online", play_fixes=signed))
    if playing.running():
        # One game at a time: the player's data is the same folder.
        lines.append(Check("running", False, "a game is running"))
    return lines


def when(details):
    """When an app was built, as a person reads it ('2026-11-09 01:02'); its file name when its server said nothing."""
    built = str((details or {}).get("built_at") or "")
    return built[:16].replace("T", " ") if built else str((details or {}).get("file") or "")


def connect(state, address):
    """Find the server at an address the player typed (or an installer brought) and play on it from now on; returns
    what it said of itself. A server already known keeps its sign-in."""
    base = srv.normalize(address)
    found = srv.about(base)
    state.add_server(base, found["name"], found["address"])
    return found


def sign_in(state, user, password):
    """Sign in to the current server; the launcher keeps the cookie it gives, never the password."""
    server = state.server()
    if server is None:
        raise srv.ServerError("connect to a server first", "error.server.none")
    answer = srv.sign_in(server["url"], user.strip(), password)
    server.update(account=answer["account"], cookie=answer["cookie"], expires=answer["expires"])
    return answer


def sign_out(state):
    """Forget the current server's sign-in (the account's ID stays, to fill the form in again)."""
    state.forget_sign_in()


def forget(state, url):
    """Forget a server, its sign-in and its app on this PC (Online's Forget, --forget); the next server known becomes
    the one PLAY plays on when it was this one. The caller asks first, and saves."""
    state.remove_server(url)
    apps.remove(url)


def reset(state):
    """Start over (Help's Start over, --reset): every server's app on this PC goes, and the state is a first start's,
    the guide next; the language stays as it was, chosen or Windows'. The caller asks first, and saves."""
    from opendmtq_client import state as st
    for server in list(state.servers):
        apps.remove(server["url"])
    picked = state.picked_language
    state.__dict__.update(st.LauncherState().__dict__)
    state.picked_language = picked


def check_app(state):
    """The app the current server offers now, kept with the server; SignedOut forgets the sign-in."""
    server = state.server()
    if server is None:
        raise srv.ServerError("connect to a server first", "error.server.none")
    if not state.signed_in(server):
        raise srv.SignedOut("sign in to the server first", "error.signin.needed")
    try:
        info = srv.app_info(server["url"], server["cookie"])
    except srv.SignedOut:
        state.forget_sign_in(server)
        raise
    server["app"] = info
    return info


def get_app(state, info=None, progress=None, cancel=None):
    """The current server's app on this PC, downloaded when it lacks it or a newer one is on offer; returns it."""
    server = state.server()
    info = info or check_app(state)
    if apps.current(server["url"], info):
        return apps.local(server["url"])
    try:
        path = srv.download_app(server["url"], server["cookie"], info, apps.folder(server["url"]), progress, cancel)
    except srv.SignedOut:
        state.forget_sign_in(server)
        raise
    log.info("downloaded the app of %s (%d bytes)", server["url"], info["size"])
    return apps.install(server["url"], info, path)


def play(state, report=lambda step, done=None, total=None: None, cancel=None):
    """Get ready and start the game: the newest app when the server can be asked, the settings file, the player.

    report(step, done, total) is told each step as it starts ("app", "download" with its progress, "offline" when the
    server did not answer, "starting"). A server that cannot be reached, or a sign-in that ended, still plays the app
    this PC has; an app the server says is built for its old address does not start (it would not reach the server).
    Returns the Session.
    """
    checks = readiness(state)
    if not can_play(checks):
        raise NotReady(stopping(checks))
    server = state.server()
    if state.signed_in(server):
        report("app")
        try:
            info = check_app(state)
            if not apps.current(server["url"], info):
                get_app(state, info, lambda done, total: report("download", done, total), cancel)
        except srv.SignedOut:
            # The game itself needs no site sign-in: the app this PC has plays, the Online page asks to sign in again.
            log.info("the server no longer takes the sign-in; playing the app this PC has")
            if apps.local(server["url"]) is None:
                raise
        except srv.ServerError as e:
            log.warning("could not ask %s for its app: %s", server["url"], e)
            if e.key == "error.app.stale" or apps.local(server["url"]) is None:
                # No app here, or one for the server's old address: the server's own words say why, nothing starts.
                raise
            if e.key in UNREACHED:
                # Played all the same, from this PC's app, which may be older than the server's: said so.
                report("offline")
    report("starting")
    settings = player.write_settings(state.values)
    have = apps.local(server["url"])
    session = player.start(apps.folder(server["url"]), settings, log_file=player.log_path(have["package"]))
    log.info("started the game for %s (process %d)", server["url"], session.process.pid)
    return session


def finish(state, session):
    """Note how a game that ended went (the PLAY page shows it)."""
    record = player.finish(session)
    state.last_session = record
    log.info("the game ended after %d s with %s", record["seconds"], record["exit_code"])
    return record


def open_folder(path):
    """Show a folder in Explorer, made first when it is still to come."""
    safety.refuse_windows_in_tests("Explorer")
    os.makedirs(path, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)
        return
    subprocess.Popen(["xdg-open", path])


def show_file(path):
    """Show a file in Explorer, selected among its folder's other files. False when the file is not there: nothing is
    made in its place (a folder of that name would stand where the file is to be written)."""
    if not os.path.isfile(path):
        return False
    safety.refuse_windows_in_tests("Explorer")
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])
    return True
