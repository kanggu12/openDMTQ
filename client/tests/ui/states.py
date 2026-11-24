"""States the launcher's screens are in that shots.py's walk through the pages never reaches, each shot and measured as
every screen is (shots.measure: text cut off, spacing, the design), with what each must say:

- the connection test's every verdict: all fine, a newer server, maintenance, no client data, a database it cannot
  write, the app being built, a sign-in that ended, none, a server too old, nothing answering: the card's strip carries
  the test's light, a failure's verdict is its step's finding without the step's name before it, and the steps a
  failure left untried show their ring and their name alone;
- the server gone under an open, ready window: the test said, and at once the status line and PLAY's ready check say the
  server does not answer (main kept "Ready to play." and the Server row lit until the window's next look);
- the sign-in refused: a ban until a time, a ban until lifted, an account switched off, each said under Sign in;
- PLAY pressed while the server builds its app, with none on this PC;
- the start after an update handed to Velopack: one that went in and one that did not, said on the status line.

Run inside the opendmtq-client-ui container only (client/tests/ui/run.sh); it refuses anywhere else, because it opens
windows. The server is the tests' stand-in site (tests/stub.py) on this machine's loopback, the player a stand-in.

  python tests/ui/states.py --out DIR [--lang en|ko] [--size 1180x760]      (from client/)
Exit status 1 when a check fails; the problems are printed and written to DIR/problems-states-<tag>.txt.
"""

import argparse
import importlib.util
import json
import os
import socket
import sys
import tempfile
import tkinter as tk

# Run from client/ (the container mounts the repository and works there).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from opendmtq_client import safety  # noqa: E402
from tests import stub  # noqa: E402
from tests.base import FAKE_PLAYER  # noqa: E402

# The screens' measures and helpers, from the file beside this one.
_spec = importlib.util.spec_from_file_location("shots", os.path.join(os.path.dirname(__file__), "shots.py"))
shots = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shots)


def labels(root):
    """The words on show in the window, in no order."""
    return [w.cget("text") for w in shots.widgets_of(root) if isinstance(w, tk.Label) and w.winfo_ismapped()
            and w.cget("text")]


def closed_port():
    """A port of this machine nobody listens on."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--size", default="1180x760")
    args = parser.parse_args()
    if not safety.on_virtual_display():
        sys.exit("refusing: this opens windows; run it through client/tests/ui/run.sh")
    shots.FIELD_OUT = args.out
    os.makedirs(args.out, exist_ok=True)
    # The collector on the window's thread only (shots.collect at each settle), as shots.py runs.
    import gc
    gc.disable()
    home = tempfile.mkdtemp()
    os.environ["HOME"] = home
    os.makedirs(os.path.join(home, "Downloads"))
    os.environ["OPENDMTQ_CLIENT_DIR"] = os.path.join(home, "client")
    os.environ["XDG_DATA_HOME"] = os.path.join(home, "local")
    player = os.path.join(home, "player", "fake_player.py")
    os.makedirs(os.path.dirname(player))
    with open(player, "w", encoding="utf-8") as f:
        f.write(FAKE_PLAYER)
    os.environ["OPENDMTQ_PLAYER"] = player
    os.environ["OPENDMTQ_INSTALL_ROOT"] = shots.fake_install(home)
    site = stub.Site().start()
    from opendmtq_client import __version__, actions, apps, connection, updates
    from opendmtq_client import state as st
    from opendmtq_client.app import LauncherApp
    tag = "%s-%s" % (args.lang, args.size)
    problems = []

    def launcher():
        """The launcher signed in on the stand-in, with its app, past the guide, at the run's size."""
        s = st.LauncherState()
        s.language = args.lang
        s.add_server(site.url, "Stand-in")
        s.guide_done = True
        s.save()
        actions.sign_in(s, stub.ACCOUNT, stub.PASSWORD)
        actions.get_app(s)
        s.save()
        made = LauncherApp(s)
        made.root.geometry("%s+0+0" % args.size)
        shots.take_keyboard(made)
        return made

    def close(made):
        """A window closed, its timers first (they would call widgets that are gone)."""
        for job in made.root.tk.splitlist(made.root.tk.call("after", "info")):
            made.root.after_cancel(job)
        made.root.destroy()

    app = launcher()
    w = app.words

    def snap(name):
        shots.settle(app)
        full = "%s_%s" % (tag, name)
        shots.shot(app.root, args.out, full)
        shots.measure(app, full, problems)
        return full

    def run_test(name):
        """Test connection on the Online page, its card in view once the test ended; then what every verdict's card
        must say."""
        app.connection_test = None
        app.go("online")
        shots.settle(app)
        shots.button(app, w("test.button")).press()
        shots.settle(app, 30, until=lambda: app.connection_test is not None and not app.connection_test["running"])
        shots.settle(app)
        card = shots.card_titled(app, w("test.title"))
        if card is None:
            problems.append("%s_%s: no connection test card" % (tag, name))
            return None
        app.body.show_widget(card)
        full = snap(name)
        result = app.connection_test["result"]
        shown = [x.cget("text") for x in shots.widgets_of(card) if isinstance(x, tk.Label) and x.winfo_ismapped()]
        # The steps a failure left untried: their ring and their name, no line each (main: "Not tried: a step before it
        # did not get through." under every one of them).
        if any(s.state == "skip" for s in result.steps) and w("test.skip") in shown:
            problems.append("%s: the steps not tried each say %r" % (full, w("test.skip")))
        # A failure's verdict: what its step found, never the step's name before it again.
        failed = next((s for s in result.steps if s.state == "bad"), None)
        if failed is not None and not result.moved:
            verdict = w.say(result.verdict())
            if verdict.startswith(w("test." + failed.key) + ":") or verdict != w.say(failed.said):
                problems.append("%s: the verdict %r is not what its step found" % (full, verdict[:60]))
        return result

    def reset_site():
        site.version = __version__
        site.maintenance = False
        site.broadcasts = False
        site.old = False
        site.app_state = "ok"
        site.health = {"ok": True, "patch": "1.003.005", "game_data": True, "database": True, "writable": True}
        site.signed_cookies = {site.cookie}

    # ---- the connection test, verdict by verdict
    reset_site()
    run_test("test-all-ok")
    site.version = "99.0.0"
    run_test("test-newer")
    reset_site()
    site.maintenance = True
    run_test("test-maintenance")
    reset_site()
    site.health.update(ok=False, game_data=False)
    run_test("test-no-data")
    reset_site()
    site.health.update(writable=False)
    run_test("test-read-only")
    reset_site()
    site.broadcasts = True
    site.app_state = "none"
    run_test("test-app-building")
    reset_site()
    site.signed_cookies = set()
    run_test("test-signin-ended")
    reset_site()
    actions.sign_out(app.state)
    app.state.save()
    run_test("test-signed-out")
    # Signed in again as before, for what follows.
    actions.sign_in(app.state, stub.ACCOUNT, stub.PASSWORD)
    app.state.save()
    reset_site()
    site.old = True
    run_test("test-too-old")
    reset_site()
    # Nothing answers anywhere: the server's address on a closed port, and no port of the search answering.
    before = app.state.current
    nowhere = closed_port()
    gone = "http://127.0.0.1:%d" % nowhere
    app.state.add_server(gone, "Gone")
    app.state.current = gone
    real_ports = connection.PORTS
    connection.PORTS = (nowhere,)
    try:
        run_test("test-nothing")
        app.go("play")
        shots.settle(app, 12)
        snap("play-nothing")
    finally:
        connection.PORTS = real_ports
        app.state.servers = [x for x in app.state.servers if x["url"] != gone]
        app.state.current = before
        app.state.save()
        app.connection_test = None
        app.refresh_checks(force=True)
        shots.settle(app)

    # ---- the server goes away under an open, ready window: the test that finds it gone says so on the status line and
    # in PLAY's ready check at once, before the window's own next look.
    other = stub.Site().start()
    try:
        actions.connect(app.state, other.url)
        actions.sign_in(app.state, stub.ACCOUNT, stub.PASSWORD)
        actions.get_app(app.state)
        app.state.save()
        app.refresh_checks(force=True)
        app.go("play")
        shots.settle(app, 8)
        if app.status_text != w("status.ready"):
            problems.append("%s_server-gone: before it went the status line says %r" % (tag, app.status_text))
        other.stop()
        app.connection_test = None
        app.go("online")
        shots.settle(app)
        shots.button(app, w("test.button")).press()
        shots.settle(app, 30, until=lambda: app.connection_test is not None and not app.connection_test["running"])
        # The ready check made again with the test's finding: no new look at the server needed (a moment's settle).
        shots.settle(app, 3)
        snap("server-gone-test")
        if app.status_text != w("status.server_down"):
            problems.append("%s_server-gone: after the test found it gone the status line says %r, not %r" % (
                tag, app.status_text, w("status.server_down")))
        app.go("play")
        shots.settle(app, 3)
        full = snap("server-gone-play")
        if w("check.server.down") not in labels(app.root):
            problems.append("%s: PLAY's ready check does not say the server is not answering" % full)
    finally:
        app.state.servers = [x for x in app.state.servers if x["url"] != other.url]
        app.state.current = before
        app.state.save()
        app.connection_test = None
        app.refresh_checks(force=True)
        shots.settle(app)

    # ---- the sign-in refused: each said under Sign in, in the window's words.
    for who, name, key in (("banned1", "signin-banned-until", "error.signin.banned_until"),
                           ("banned2", "signin-banned", "error.signin.banned"),
                           (stub.OFF, "signin-off", "error.signin.off")):
        app.state.forget_sign_in()
        app.state.save()
        app.go("online")
        shots.settle(app)
        fields = shots.entries(app)
        if len(fields) < 3:
            problems.append("%s_%s: no sign-in form (%d fields)" % (tag, name, len(fields)))
            continue
        fields[1].delete(0, "end")
        fields[1].insert(0, who)
        fields[2].delete(0, "end")
        fields[2].insert(0, stub.PASSWORD)
        shots.button(app, w("online.signin")).press()
        shots.settle(app, 8)
        full = snap(name)
        # The refusal's words start as its words do, up to their first gap (a time and a reason fill them).
        from opendmtq_client import i18n
        start = i18n.TEXT[key][1 if args.lang == "ko" else 0].split("{")[0].strip()
        if not any(text.startswith(start) for text in labels(app.root)):
            problems.append("%s: the refusal is not said (%r)" % (full, start))

    # ---- PLAY while the server builds its app, with none on this PC
    actions.sign_in(app.state, stub.ACCOUNT, stub.PASSWORD)
    app.state.save()
    site.app_state = "none"
    apps.remove(app.state.current)
    app.refresh_checks(force=True)
    app.go("play")
    shots.settle(app, 8)
    snap("play-no-app")
    app.play()
    shots.settle(app, 10)
    snap("play-app-building")
    reset_site()
    close(app)

    # ---- the start after an update handed to Velopack: the note it leaves, then the window as it opens.
    installed = updates.current_version() or __version__
    for name, target, key in (("restart-updated", installed, "status.updated"),
                              ("restart-not-updated", "9.9.9", "status.not_updated")):
        os.makedirs(st.config_dir(), exist_ok=True)
        with open(os.path.join(st.config_dir(), updates.PENDING), "w", encoding="utf-8") as f:
            json.dump({"to": target, "from": "0.11.1"}, f)
        app = launcher()
        w = app.words
        shots.settle(app, 8)
        full = snap(name)
        said = w(key, v=target, now=installed)
        if app.status_text != said:
            problems.append("%s: the status line says %r, not %r" % (full, app.status_text, said))
        close(app)
    site.stop()
    with open(os.path.join(args.out, "problems-states-%s.txt" % tag), "w", encoding="utf-8") as f:
        f.write("\n".join(problems) + ("\n" if problems else ""))
    print("states %s: %d problems" % (tag, len(problems)))
    for problem in problems:
        print("  " + problem)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
