"""The sound the player's in-game menu sets during a game stays the launcher's own after the game: the window takes it
back when the game ends, shows it on the Sound page when it comes back to the front, keeps it in its settings, and the
next PLAY gives it to the player again; the same when the window was closed while the game ran (the next start has it).

Run inside the opendmtq-client-ui container only (client/tests/ui/run.sh); it refuses anywhere else, because it opens
windows. The server is the tests' stand-in site (tests/stub.py) on this machine's loopback, the player a stand-in that
writes its settings file back during the game the way the real player's in-game menu does.

  python tests/ui/sound_back.py --lang en|ko      (from client/)
Exit status 1 when a setting the player wrote during a game was lost; each failure is printed.
"""

import argparse
import importlib.util
import json
import os
import sys
import time

# Run from client/ (the container mounts the repository and works there).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from opendmtq_client import safety  # noqa: E402

# The keyboard checks' set-up (a launcher signed in on the stand-in server, its app on this PC), from the file beside.
_spec = importlib.util.spec_from_file_location("keyboard", os.path.join(os.path.dirname(__file__), "keyboard.py"))
keyboard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(keyboard)
shots = keyboard.shots

# A stand-in for the player: it notes the settings file it was started with (each start a line of started.jsonl beside
# it), then, when sound.json beside it names changes, writes them into that file as the player's in-game menu does (the
# whole file again, through a temporary file and a rename), and stays a moment, as a game being played does.
PLAYER = '''\
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
if args == ["--audio-devices"]:
    sys.exit(0)
path = args[args.index("--settings") + 1]
with open(path, encoding="utf-8") as f:
    text = f.read()
with open(os.path.join(here, "started.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"settings": text}) + "\\n")
changes = os.path.join(here, "sound.json")
if os.path.isfile(changes):
    with open(changes, encoding="utf-8") as f:
        wanted = json.load(f)
    os.remove(changes)
    # A moment into the game, the in-game menu moved: every line as it was but the changed ones.
    time.sleep(0.5)
    lines = [line for line in text.splitlines() if line.partition("=")[0] not in wanted]
    lines += ["%s=%s" % item for item in sorted(wanted.items())]
    with open(path + ".tmp", "w", encoding="utf-8", newline="\\n") as f:
        f.write("\\n".join(lines) + "\\n")
    os.replace(path + ".tmp", path)
time.sleep(4)
sys.exit(0)
'''


def stderr_kept():
    """The process's standard error (Tcl writes its background errors there, beyond Python's reach) into a file of its
    own from now on; returns a function that gives it back and returns what was written meanwhile, echoed as it was."""
    import tempfile
    kept = tempfile.TemporaryFile()
    sys.stderr.flush()
    saved = os.dup(2)
    os.dup2(kept.fileno(), 2)

    def back():
        sys.stderr.flush()
        os.dup2(saved, 2)
        os.close(saved)
        kept.seek(0)
        text = kept.read().decode("utf-8", "replace")
        sys.stderr.write(text)
        return text

    return back


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="en")
    args = parser.parse_args()
    if not safety.on_virtual_display():
        sys.exit("refusing: this opens windows; run it through client/tests/ui/run.sh")
    site, state = keyboard.setup(args.lang)
    player = os.environ["OPENDMTQ_PLAYER"]
    here = os.path.dirname(player)
    with open(player, "w", encoding="utf-8") as f:
        f.write(PLAYER)
    from opendmtq_client import state as st
    from opendmtq_client import widgets
    from opendmtq_client.app import LauncherApp
    problems = []

    def change_in_game(**values):
        """What the stand-in's in-game menu sets during its next game."""
        with open(os.path.join(here, "sound.json"), "w", encoding="utf-8") as f:
            json.dump(values, f)

    def last_start():
        """The settings file the stand-in was last started with, as {name: value}."""
        with open(os.path.join(here, "started.jsonl"), encoding="utf-8") as f:
            text = json.loads(f.read().splitlines()[-1])["settings"]
        return dict(line.partition("=")[::2] for line in text.splitlines() if "=" in line and not line.startswith("#"))

    def play_through(app, close_meanwhile=False):
        """PLAY pressed, the game waited for until it ends (or, closed meanwhile, until the window goes)."""
        app.play()
        end = time.time() + 30
        while time.time() < end and app.session is None:
            app.root.update()
            time.sleep(0.02)
        if app.session is None:
            problems.append("the game did not start")
            return
        if close_meanwhile:
            # The window's X while the game runs: it hides, and goes when the game ends.
            if not app._game_open():
                problems.append("the game ended before the window could be closed during it")
            app.close()
        while time.time() < end:
            try:
                app.root.update()
            except Exception:  # noqa: BLE001  (the window went: tkinter says so by an error)
                return
            if app.session is None:
                return
            time.sleep(0.02)
        problems.append("the game did not end in the window")

    def sound_page_shows(app):
        """The Sound page's three volume sliders, as shown."""
        app.nav_go("sound")
        shots.settle(app)
        return [x.value for x in shots.widgets_of(app.body.inner) if isinstance(x, widgets.Slider)][:3]

    # What Tcl writes from here on, looked at in the end.
    back = stderr_kept()
    # ---- A game in which the in-game menu sets master 29, music 40 and the bass preset; the window comes back after.
    app = LauncherApp(state)
    app.root.geometry("1180x760+0+0")
    shots.settle(app)
    app.nav_go("sound")
    shots.settle(app)
    change_in_game(volume=29, music_volume=40, eq="bass", eq_low=6, eq_mid=0, eq_high=0)
    play_through(app)
    # Back to the front, as Windows gives the window the keyboard again after the game.
    app.root.event_generate("<FocusIn>")
    shots.settle(app)
    values = app.state.values
    if (values["volume"], values["music_volume"], values["eq"]) != (29, 40, "bass"):
        problems.append("after the game the launcher has volume %s, music %s, eq %s, not 29, 40, bass" % (
            values["volume"], values["music_volume"], values["eq"]))
    kept = st.LauncherState.load().values
    if (kept["volume"], kept["music_volume"], kept["eq"]) != (29, 40, "bass"):
        problems.append("after the game the launcher's saved settings have volume %s, music %s, eq %s" % (
            kept["volume"], kept["music_volume"], kept["eq"]))
    shown = sound_page_shows(app)
    if shown[:2] != [29, 40]:
        problems.append("after the game the Sound page shows %s for master and music, not 29 and 40" % shown[:2])
    # ---- The next PLAY gives the player what its menu set, not the launcher's settings from before the game.
    play_through(app)
    given = last_start()
    if (given.get("volume"), given.get("music_volume"), given.get("eq")) != ("29", "40", "bass"):
        problems.append("the next PLAY gave the player volume=%s music_volume=%s eq=%s" % (
            given.get("volume"), given.get("music_volume"), given.get("eq")))
    # ---- The window closed while the game runs: it goes at the game's end, and the next start has what was set.
    change_in_game(volume=55)
    play_through(app, close_meanwhile=True)
    kept = st.LauncherState.load()
    if kept.values["volume"] != 55:
        problems.append("closed during the game: the next start has volume %s, not 55" % kept.values["volume"])
    again = LauncherApp(kept)
    again.root.geometry("1180x760+0+0")
    shots.settle(again)
    again.root.event_generate("<FocusIn>")
    shots.settle(again)
    play_through(again)
    if last_start().get("volume") != "55":
        problems.append("closed during the game: the next PLAY gave the player volume=%s" % last_start().get("volume"))
    try:
        again.root.destroy()
    except Exception:  # noqa: BLE001  (gone already)
        pass
    site.stop()
    # An error Tcl met in the background (a timer of a window that went, firing into the next window's loop: main
    # printed "bgerror failed to handle background error ... invalid command name ..._pump" and passed).
    written = back()
    for line in written.splitlines():
        if "bgerror" in line or "invalid command name" in line or "Error in bgerror" in line:
            problems.append("Tcl said in the background: %s" % line.strip())
    for line in problems:
        print("FAIL", args.lang, line)
    print("sound_back %s: %d problems" % (args.lang, len(problems)))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
