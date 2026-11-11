"""The launcher with the keyboard alone, on the test container's virtual screen: the order Tab goes in, a control Tab
reaches below the part of the page in view coming into view, and a choice that draws its page again keeping the page's
place and the keyboard's control (the Sound page and the guide's SOUND CHECK, as the Screen page does).

Run inside the opendmtq-client-ui container only (client/tests/ui/run.sh); it refuses anywhere else, because it opens
windows. The server is the tests' stand-in site (tests/stub.py) on this machine's loopback, the player a stand-in.

  python tests/ui/keyboard.py --lang en|ko      (from client/)
Exit status 1 when a check fails; each failure is printed.
"""

import argparse
import importlib.util
import os
import sys
import tempfile

# Run from client/ (the container mounts the repository and works there).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from opendmtq_client import safety, widgets  # noqa: E402
from tests import stub  # noqa: E402
from tests.base import FAKE_PLAYER  # noqa: E402

# The screenshots' helpers (settle, the way a person finds a button), from the file beside this one.
_spec = importlib.util.spec_from_file_location("shots", os.path.join(os.path.dirname(__file__), "shots.py"))
shots = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shots)


def name_of(widget):
    """A widget as a person would name it, for the failures' words."""
    import tkinter as tk
    if isinstance(widget, widgets.Button):
        return "button %r" % widget.words
    if isinstance(widget, widgets.PlaySlab):
        return "PLAY"
    if isinstance(widget, widgets.Header):
        return "the menu"
    if isinstance(widget, tk.Label) and widget.cget("text"):
        return "link %r" % widget.cget("text")
    return widget.winfo_class()


def tab_order(start, most=60):
    """The widgets Tab visits after `start`, by Tk's own traversal (tk_focusNext, what the Tab binding calls), until it
    comes round again."""
    seen, widget = [], start
    for _ in range(most):
        widget = widget.tk_focusNext()
        if widget is None or widget in seen or widget is start:
            break
        seen.append(widget)
    return seen


def in_view(area, widget):
    """Whether `widget` lies whole in the part of the page area in view."""
    top = area.canvas.winfo_rooty()
    return widget.winfo_rooty() >= top and widget.winfo_rooty() + widget.winfo_height() <= top + area.canvas.winfo_height()


def setup(lang):
    """A launcher folder of its own with the stand-in server known, signed in and its app downloaded."""
    home = tempfile.mkdtemp()
    for name, value in (("HOME", home), ("OPENDMTQ_CLIENT_DIR", os.path.join(home, "client")),
                        ("XDG_DATA_HOME", os.path.join(home, "local")), ("LOCALAPPDATA", os.path.join(home, "local"))):
        os.environ[name] = value
    player = os.path.join(home, "player", "fake_player.py")
    os.makedirs(os.path.dirname(player))
    with open(player, "w", encoding="utf-8") as f:
        f.write(FAKE_PLAYER)
    os.environ["OPENDMTQ_PLAYER"] = player
    site = stub.Site().start()
    from opendmtq_client import actions
    from opendmtq_client import state as st
    state = st.LauncherState()
    state.language = lang
    actions.connect(state, site.url)
    actions.sign_in(state, stub.ACCOUNT, stub.PASSWORD)
    actions.get_app(state)
    state.guide_done = True
    state.save()
    return site, state


def setting_control(area, kind, title):
    """The control of `kind` in the setting row named `title` on the page area."""
    import tkinter as tk
    for widget in shots.widgets_of(area.inner):
        if isinstance(widget, kind):
            names = [c.cget("text") for c in widget.master.winfo_children() if isinstance(c, tk.Label)]
            if title in names:
                return widget
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="en")
    args = parser.parse_args()
    if not safety.on_virtual_display():
        sys.exit("refusing: this opens windows; run it through client/tests/ui/run.sh")
    site, state = setup(args.lang)
    from opendmtq_client.app import LauncherApp
    problems = []
    app = LauncherApp(state)
    # The smallest window: the most pages scroll there.
    app.root.geometry("960x640+0+0")
    shots.settle(app)
    w = app.words

    # ---- Tab's order on the Online page: the menu, then the page's controls, then PLAY at the foot.
    app.nav_go("online")
    shots.settle(app)
    order = tab_order(app.header)
    page = [x for x in order if str(x).startswith(str(app.body.inner) + ".")]
    if not order or not page or order.index(page[0]) != 0 or order[-1] is not app.play_button:
        problems.append("Online: Tab goes %s, not the page then PLAY" % " -> ".join(name_of(x) for x in order))

    # ---- A control below the part of the page in view comes into view when Tab reaches it.
    app.changed("render_scale", "75")
    app.nav_go("screen")
    shots.settle(app)
    area = app.body
    below = [x for x in tab_order(app.header) if str(x).startswith(str(area.inner) + ".") and not in_view(area, x)]
    if not below:
        problems.append("Screen at 960x640: no control below the part in view to reach (the check checks nothing)")
    for widget in below:
        widget.focus_set()
        app.root.update()
        if not in_view(area, widget):
            problems.append("Screen: %s reached by Tab stayed out of view" % name_of(widget))
    app.changed("render_scale", "100")

    # ---- The Sound page: the buffer stepped with the keyboard at the page's foot keeps the page's place and the
    # keyboard on the buffer, so the next key steps it again.
    app.nav_go("sound")
    shots.settle(app, 6, until=lambda: app.devices is not None)
    shots.settle(app)
    area = app.body
    area.canvas.yview_moveto(1.0)
    shots.settle(app)
    buffer = setting_control(area, widgets.Segmented, w("sound.buffer"))
    buffer.focus_set()
    app.root.update()
    # Where the page is scrolled to, in pixels (a fraction moves with the page's height by a pixel or so).
    before = area.canvas.canvasy(0)
    buffer.event_generate("<Left>")
    shots.settle(app)
    focus = app.root.focus_get()
    if before <= 0 or abs(area.canvas.canvasy(0) - before) > 1:
        problems.append("Sound: stepping the buffer moved the page from %d px to %d" % (before,
                                                                                       area.canvas.canvasy(0)))
    if not isinstance(focus, widgets.Segmented) or focus.value != "low":
        problems.append("Sound: after the buffer's step the keyboard is on %r" % (focus,))
    else:
        focus.event_generate("<Right>")
        shots.settle(app)
        if app.state.values["audio_buffer"] != "normal":
            problems.append("Sound: a second step of the buffer did nothing (%s)" % app.state.values["audio_buffer"])

    # ---- The guide's SOUND CHECK: VSync switched with Space keeps the step's place and the keyboard.
    app.state.guide_done = False
    app.state.save()
    app.show()
    shots.settle(app)
    for _ in range(4):
        app.guide.next()
        shots.settle(app)
    area = app.guide.body
    area.canvas.yview_moveto(1.0)
    shots.settle(app)
    toggle = next((x for x in shots.widgets_of(area.inner) if isinstance(x, widgets.Toggle)), None)
    toggle.focus_set()
    app.root.update()
    before = area.canvas.canvasy(0)
    vsync = app.state.values["vsync"]
    toggle.event_generate("<space>")
    shots.settle(app)
    focus = app.root.focus_get()
    if app.state.values["vsync"] == vsync:
        problems.append("SOUND CHECK: Space did not switch VSync")
    if before <= 0 or abs(area.canvas.canvasy(0) - before) > 1:
        problems.append("SOUND CHECK: switching VSync moved the step from %d px to %d" % (before,
                                                                                         area.canvas.canvasy(0)))
    if not isinstance(focus, widgets.Toggle):
        problems.append("SOUND CHECK: after VSync's switch the keyboard is on %r" % (focus,))

    # ---- The guide's Tab order: the step's page, then the bar left to right (Skip, Back, Next).
    app.guide.back()
    shots.settle(app)
    order = tab_order(app.guide.header)
    bar = [x for x in order if not str(x).startswith(str(app.guide.body.inner) + ".")]
    names = [name_of(x) for x in bar]
    expected = ["link %r" % w("guide.skip"), "button %r" % w("guide.back"), "button %r" % w("guide.next")]
    if names[-3:] != expected or any(not str(x).startswith(str(app.guide.body.inner) + ".")
                                     for x in order[:len(order) - len(bar)]):
        problems.append("guide: Tab goes %s" % " -> ".join(name_of(x) for x in order))
    for job in app.root.tk.splitlist(app.root.tk.call("after", "info")):
        app.root.after_cancel(job)
    app.root.destroy()
    site.stop()
    print("keyboard %s: %d problems" % (args.lang, len(problems)))
    for problem in problems:
        print("  " + problem)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
