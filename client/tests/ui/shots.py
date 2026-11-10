"""Open the launcher on the test container's virtual screen, go through the first-start guide and every page, save a
screenshot of each, and measure the layout: text cut off, controls past the window's edge, labels never wrapped.

Run inside the opendmtq-client-ui container only (client/tests/ui/run.sh); it refuses anywhere else, because it opens
windows. The server is the tests' stand-in site (tests/stub.py) on this machine's loopback, the player a stand-in
script: no game file is used.

  python tests/ui/shots.py --out DIR [--lang en|ko] [--size 1180x760]      (from client/)
Exit status 1 when the layout check finds a problem; the problems are printed and written to DIR/problems-<tag>.txt.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time

# Run from client/ (the container mounts the repository and works there).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from opendmtq_client import safety, widgets  # noqa: E402
from tests import stub  # noqa: E402
from tests.base import FAKE_PLAYER  # noqa: E402


def widgets_of(widget):
    yield widget
    for child in widget.winfo_children():
        yield from widgets_of(child)


def wrap_of(w):
    """A label's wrap width in pixels (Tk returns a screen distance object)."""
    return int(w.winfo_fpixels(str(w.cget("wraplength"))))


def measure(app, name, problems, root=None):
    """Text cut off (a label narrower than its text without wrapping) and widgets past the window's right edge."""
    import tkinter as tk
    root = root or app.root
    root.update()
    right = root.winfo_rootx() + root.winfo_width()
    for w in widgets_of(root):
        if not w.winfo_ismapped():
            continue
        cls = w.winfo_class()
        if cls == "Label" and w.cget("text"):
            # Tk shrinks a label when room runs out and cuts its text; the required width says how much it wanted.
            if w.winfo_reqwidth() > w.winfo_width() + 2:
                problems.append("%s: text cut off: %r (needs %d px, has %d)" % (name, w.cget("text")[:60],
                                                                                w.winfo_reqwidth(), w.winfo_width()))
        if cls in ("Label", "Frame", "Canvas", "TCombobox", "Entry") and w.winfo_width() > 1:
            if w.winfo_rootx() + w.winfo_width() > right + 1 and w.winfo_viewable():
                problems.append("%s: past the right edge: %s %r" % (name, cls, (w.cget("text") if cls == "Label" else "")[:40]))
        if isinstance(w, tk.Label) and wrap_of(w) == app.ui.px(widgets.START_WRAP) and len(w.cget("text")) > 20:
            # Still at its start width: its box never told it the real room.
            problems.append("%s: wrapping never set: %r" % (name, w.cget("text")[:60]))
        if isinstance(w, widgets.Button) and w.winfo_width() + 1 < w.winfo_reqwidth():
            problems.append("%s: button squeezed: %r (needs %d px, has %d)" % (name, w.words, w.winfo_reqwidth(),
                                                                              w.winfo_width()))
        if isinstance(w, tk.Label) and wrap_of(w):
            parent = w.nametowidget(w.winfo_parent())
            if w.winfo_width() > parent.winfo_width() + 2:
                problems.append("%s: wrapped text wider than its box: %r" % (name, w.cget("text")[:60]))


def shot(root, out, name):
    """Screenshot of a window, through the X server (what a person would see)."""
    root.update()
    time.sleep(0.25)
    root.update()
    top = root.wm_frame()
    target = os.path.join(out, name + ".png")
    subprocess.run(["import", "-window", top if top and top != "0x0" else str(root.winfo_id()), target], check=True)
    return target


def settle(app, seconds=8.0, until=None):
    """Let worker threads (the ready check, the server's answers, a download) finish and reach the window."""
    end = time.time() + seconds
    while time.time() < end:
        app.root.update()
        # The page's picture behind is drawn a moment after the page (widgets.ScrollArea): a shot waits for it.
        body = getattr(app.guide, "body", None) if getattr(app, "guide", None) is not None else getattr(app, "body", None)
        busy = (app.checks is None or app.download is not None or
                (body is not None and body.winfo_exists() and body._backdrop_job is not None))
        guide = getattr(app, "guide", None)
        if guide is not None and guide.checking:
            busy = True
        if until is not None:
            busy = busy or not until()
        if not busy:
            break
        time.sleep(0.05)
    app.root.update()


def wait_out(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def button(app, words):
    """The page's button with these words (the way a person finds it)."""
    for w in widgets_of(app.root):
        if isinstance(w, widgets.Button) and w.words == words and w.winfo_ismapped():
            return w
    raise AssertionError("no button %r on the page" % words)


def entries(app):
    import tkinter as tk
    return [w for w in widgets_of(app.root) if isinstance(w, tk.Entry) and w.winfo_ismapped()]


def through_dialog(app, out, name, press, answer, problems, extra=None):
    """Press a page button that asks first, as a person would; screenshot and measure the dialog it opens, then answer
    it with `answer(dialog)`. Returns what the dialog answered (None when none opened)."""
    seen = {}

    def look():
        dialog = app.dialog
        if dialog is None:
            problems.append("%s: the button opened no dialog" % name)
            return
        seen["dialog"] = dialog
        wait_out(app.root, 0.4)
        shot(app.root, out, name)
        problems.extend("%s: %s" % (name, p) for p in dialog.layout_problems())
        if extra:
            extra(dialog)
        answer(dialog)

    app.root.after(300, look)
    press()
    dialog = seen.get("dialog")
    # The same dialog: work the answer started may show a dialog of its own.
    if dialog is not None and app.dialog is dialog:
        problems.append("%s: the dialog stayed after its answer" % name)
    return dialog.result if dialog is not None else None


def click_button(dialog, i):
    """Move the pointer onto a dialog button and click it, through the X server's events."""
    left, top, right, bottom = dialog._boxes[i]
    x, y = dialog.origin[0] + (left + right) // 2, dialog.origin[1] + (top + bottom) // 2
    c = dialog.canvas
    c.event_generate("<Motion>", x=x, y=y, warp=True)
    c.update()
    c.event_generate("<ButtonPress-1>", x=x, y=y)
    c.event_generate("<ButtonRelease-1>", x=x, y=y)


def guide_check(app, site, out, tag, problems):
    """The first-start guide, step by step, as a person goes through it: the server the installer brought answers,
    the sign-in form is filled in, the download runs, then the screen and sound and the ready check."""
    from opendmtq_client import guide as guide_module
    guide = app.guide
    w = app.words
    for i, key in enumerate(guide_module.STEPS):
        if i:
            guide.next()
        settle(app)
        name = "%s_guide%d-%s" % (tag, i + 1, key)
        if key == "login":
            shot(app.root, out, name + "-form")
            measure(app, name + "-form", problems)
            # A wrong password first: the form says so and stays.
            fields = entries(app)
            fields[0].delete(0, "end")
            fields[0].insert(0, stub.ACCOUNT)
            fields[1].insert(0, "wrong")
            button(app, w("online.signin")).press()
            # The answer comes on a worker thread; the form shows it.
            wait_out(app.root, 1.5)
            shot(app.root, out, name + "-wrong")
            measure(app, name + "-wrong", problems)
            fields = entries(app)
            fields[1].delete(0, "end")
            fields[1].insert(0, stub.PASSWORD)
            button(app, w("online.signin")).press()
            settle(app, 6, until=lambda: app.state.signed_in())
            if not app.state.signed_in():
                problems.append("%s: the guide's sign-in did not sign in" % tag)
        if key == "download":
            settle(app, 20, until=lambda: app.download is None)
            # The step drawn again with its answer.
            settle(app)
        shot(app.root, out, name)
        measure(app, name, problems)
        if not guide.next_button.enabled:
            problems.append("%s: Next stays off on the %s step" % (tag, key))
    return guide


def wheel_check(app, problems):
    """The wheel over a drop-down scrolls the page and leaves the setting as it was (Tk's own drop-down bindings would
    step its value and say it was chosen)."""
    import tkinter as tk
    from opendmtq_client import widgets as wd
    selects = [w for w in widgets_of(app.root) if isinstance(w, wd.Select) and w.winfo_ismapped()]
    if not selects:
        problems.append("no drop-down on the Screen page to turn the wheel over")
        return
    before = dict(app.state.values)
    for select in selects:
        for sequence in ("<Button-4>", "<Button-5>"):
            select.event_generate(sequence, x=5, y=5)
        try:
            select.event_generate("<MouseWheel>", delta=-120, x=5, y=5)
        except tk.TclError:
            # A Tk without wheel events to make: X11's buttons above are the wheel there.
            pass
        app.root.update()
    if app.state.values != before:
        problems.append("the wheel changed a setting: %r -> %r" % (before, app.state.values))


def wheel_bindings_check(app, problems):
    """The page area binds the wheel for the whole window while the pointer is over it: its commands do not pile up as
    the pointer comes and goes, and after a rebuild of the window (a language switch) a turn of the wheel calls nothing
    that is gone (callback_error records any error it raises)."""
    import gc
    import tkinter as tk
    root = app.root
    commands = lambda: len(root.tk.splitlist(root.tk.call("info", "commands")))  # noqa: E731
    # The pointer away from the window, so that only the crossings made here reach the page area.
    root.event_generate("<Motion>", warp=True, x=-400, y=-400)
    root.update()
    # Counted with no update between: timers that come and go (the task pump) would move the count. Python's collector
    # runs first and then waits: freeing an old page's pictures (each one a Tcl command too) would move it as well.
    gc.collect()
    gc.disable()
    try:
        before = commands()
        for _ in range(50):
            app.body.event_generate("<Enter>")
            app.body.event_generate("<Leave>")
        after = commands()
    finally:
        gc.enable()
    if after != before:
        problems.append("the page area's wheel left %d Tcl commands after 50 crossings" % (after - before))
    # The pointer over the page, then the window rebuilt in the other language with the pointer away: the first turn of
    # the wheel comes before the new page area has seen the pointer.
    app.body.event_generate("<Enter>")
    # The commands the wheel's bindings call now (each binding's script runs "[command %# ...]"): the page area's own.
    held = [root.tk.call("bind", "all", s).split("[", 1)[1].split(" ", 1)[0]
            for s in ("<MouseWheel>", "<Button-4>", "<Button-5>") if "[" in root.tk.call("bind", "all", s)]
    if len(held) != 3:
        problems.append("the page area bound %d of the wheel's 3 events for the pointer over it" % len(held))
    # Gone with the page area, or they would keep the area that is gone alive, its pictures with it. Looked for at once
    # after the area's own <Destroy> (bindings run in the order they were made): later, a command of the rebuilt window
    # may have the same name, as a name is the address of a function Python has freed and given to a new one.
    old, seen = app.body, {}

    def gone(event):
        if event.widget is old:
            seen["left"] = [c for c in held if root.tk.call("info", "commands", c)]

    old.bind("<Destroy>", gone, add="+")
    language = app.state.picked_language
    app.set_language("ko" if language == "en" else "en")
    settle(app)
    if "left" not in seen:
        problems.append("the language switch did not rebuild the page area")
    elif seen["left"]:
        problems.append("the wheel's commands outlived the page area: %r" % seen["left"])
    errors = len(problems)
    for sequence in ("<Button-4>", "<Button-5>"):
        app.header.event_generate(sequence, x=5, y=5)
    try:
        app.header.event_generate("<MouseWheel>", delta=-120, x=5, y=5)
    except tk.TclError:
        # A Tk without wheel events to make: X11's buttons above are the wheel there.
        pass
    root.update()
    if len(problems) != errors:
        problems.append("a turn of the wheel after a language switch failed")
    # Back in the run's own language for what follows.
    app.set_language(language)
    settle(app)


def pages_check(app, out, tag, problems):
    from opendmtq_client.app import NAV
    for page in NAV:
        app.go(page)
        settle(app)
        if page == "sound":
            # The devices come from the player on a worker thread: the page is drawn again with them.
            settle(app, 6, until=lambda: app.devices is not None)
            settle(app)
        name = "%s_%s" % (tag, page)
        shot(app.root, out, name)
        measure(app, name, problems)
        if page == "screen":
            # After its shot: the wheel scrolls the page (the header turns into the dark bar).
            wheel_check(app, problems)


def variants_check(app, site, out, tag, problems):
    """Pages in their other states: a window's size row, a download under way, signed out, other servers, a crash."""
    w = app.words
    app.changed("display", "window")
    app.go("screen")
    settle(app)
    shot(app.root, out, tag + "_screen-window")
    measure(app, tag + "_screen-window", problems)
    app.changed("vsync", "off")
    app.go("screen")
    settle(app)
    shot(app.root, out, tag + "_screen-free")
    measure(app, tag + "_screen-free", problems)
    # A download under way, drawn from its numbers (the real one is in the guide).
    import threading
    app.download = {"done": 47 << 20, "total": 103 << 20, "cancel": threading.Event()}
    # PLAY waits while it runs, as app.get_app makes it.
    app._paint_play()
    app.go("online")
    app.root.update()
    app._download_moved(47 << 20, 103 << 20)
    shot(app.root, out, tag + "_online-downloading")
    measure(app, tag + "_online-downloading", problems)
    app.download = None
    app._paint_play()
    app.set_status(w("status.ready"), "normal")
    # Signed out, and another server known.
    app.state.forget_sign_in()
    app.state.servers.append({"url": "http://192.0.2.10:8080", "name": "가나다라마바사아 서버 이름이 아주 긴 서버",
                              "address": "192.0.2.10:8080", "account": None, "cookie": None, "expires": 0, "app": None})
    app.state.save()
    for page in ("online", "play"):
        app.go(page)
        settle(app)
        shot(app.root, out, "%s_%s-signed-out" % (tag, page))
        measure(app, "%s_%s-signed-out" % (tag, page), problems)
    # A game that closed by itself.
    app.state.last_session = {"seconds": 754, "exit_code": 3221225477, "crashed": True}
    app.set_status(w("status.crashed"), "bad", action=(w("status.open_log"), app.open_player_log))
    app.go("play")
    settle(app)
    shot(app.root, out, tag + "_play-crashed")
    measure(app, tag + "_play-crashed", problems)
    # A server an installer leaves while the window is open: the window takes it within a few seconds and says so.
    from opendmtq_client import preset
    before = app.state.current
    preset.hand_over({"url": "http://192.0.2.20:8790", "name": "Club"})
    settle(app, 6, until=lambda: app.state.server("http://192.0.2.20:8790") is not None)
    app.go("play")
    settle(app)
    shot(app.root, out, tag + "_play-preset")
    measure(app, tag + "_play-preset", problems)
    if app.state.server("http://192.0.2.20:8790") is None or w("status.preset", name="Club") != app.status_text:
        problems.append("%s: the window did not take the installer's server (%r)" % (tag, app.status_text))
    # Back to the stand-in server for the dialogs that follow.
    app.state.remove_server("http://192.0.2.20:8790")
    app.state.current = before
    app.state.save()
    app.refresh_checks()


def dialogs_check(app, out, tag, problems):
    """The launcher's questions, opened from their pages, answered by key and by click, at a resize too."""
    from opendmtq_client import dialogs
    w = app.words
    app.go("online")
    settle(app)
    # One for the server in use (its card), one for the other server (the last card): this checks the other's.
    forget = [x for x in widgets_of(app.root) if isinstance(x, widgets.Button) and x.words == w("online.forget")]
    if len(forget) != 2:
        problems.append("%s: expected two Forget buttons on Online, found %d" % (tag, len(forget)))
        return
    forget = forget[1:]

    def ring_moves(dialog):
        dialog.canvas.event_generate("<Tab>")
        wait_out(app.root, 0.1)
        shot(app.root, out, "%s_dialog-forget-ring" % tag)
        if dialog.focus != 1:
            problems.append("%s: Tab did not move the ring to Forget" % tag)
        dialog.canvas.event_generate("<ISO_Left_Tab>")
    answer = through_dialog(app, out, "%s_dialog-forget" % tag, forget[0].press,
                            lambda d: d.canvas.event_generate("<Escape>"), problems, extra=ring_moves)
    if answer is not False:
        problems.append("%s: Esc on the forget dialog answered %r" % (tag, answer))
    answer = through_dialog(app, out, "%s_dialog-forget-enter" % tag, forget[0].press,
                            lambda d: d.canvas.event_generate("<Return>"), problems)
    if answer is not False or len(app.state.servers) != 2:
        problems.append("%s: Enter on the forget dialog forgot the server (answer %r)" % (tag, answer))

    def resized(dialog):
        app.root.geometry("960x640")
        wait_out(app.root, 0.6)
        shot(app.root, out, "%s_dialog-forget-960" % tag)
        problems.extend("%s_dialog-forget-960: %s" % (tag, p) for p in dialog.layout_problems())
        if dialog.size != (app.root.winfo_width(), app.root.winfo_height()):
            problems.append("%s: the dialog was not drawn again after a resize" % tag)
    answer = through_dialog(app, out, "%s_dialog-forget-click" % tag, forget[0].press,
                            lambda d: click_button(d, 1), problems, extra=resized)
    if answer is not True or len(app.state.servers) != 1:
        problems.append("%s: clicking Forget did not forget the server (answer %r)" % (tag, answer))
    # Start over asks first; Esc keeps everything.
    app.go("help")
    settle(app)
    answer = through_dialog(app, out, "%s_dialog-reset" % tag, button(app, w("help.reset")).press,
                            lambda d: d.canvas.event_generate("<Escape>"), problems)
    if answer is not False or app.state.server() is None:
        problems.append("%s: Esc on the start-over dialog answered %r" % (tag, answer))
    maintenance_check(app, out, tag, problems)
    # A step of the window that fails: said once in the launcher's dialog, and the window goes on.
    seen = next_dialog(app, out, "%s_dialog-step-failed" % tag, problems, lambda d: d.message == w("failed.message"),
                       lambda d: d.canvas.event_generate("<Return>"))
    app.step_failed(RuntimeError, RuntimeError("could not read C:\\Users\\player\\AppData\\Local\\OpenDMTQ\\client"
                                                "\\servers\\example.com-8080\\app.json"), None)
    wait_out(app.root, 1.0)
    if "dialog" not in seen or not app.failure_said:
        problems.append("%s: a failed step of the window was not said" % tag)
    # The update under way.
    app.go("about")
    settle(app)
    dialog = dialogs.Dialog(app.root, app.ui, "info", w("about.updating.title"), w("about.updating.message", v="9.9.9"),
                            w("about.updating.detail"), progress=True, glyph="update")
    wait_out(app.root, 0.6)
    shot(app.root, out, "%s_dialog-updating" % tag)
    problems.extend("%s_dialog-updating: %s" % (tag, p) for p in dialog.layout_problems())
    dialog.canvas.event_generate("<Escape>")
    wait_out(app.root, 0.1)
    if dialog.closed:
        problems.append("%s: Esc closed the update under way" % tag)
    dialog.close(None)


def fake_install(home):
    """A folder laid out as Velopack's install, with its package: Help shows Repair and Uninstall as in an installed
    launcher, and Repair has something to compare."""
    import zipfile
    root = os.path.join(home, "OpenDMTQ.Client")
    files = {"OpenDMTQ.exe": b"launcher", "player/opendmtq-player.exe": b"player"}
    os.makedirs(os.path.join(root, "packages"))
    with zipfile.ZipFile(os.path.join(root, "packages", "OpenDMTQ.Client-0.8.0-full.nupkg"), "w") as z:
        for name, data in files.items():
            z.writestr("lib/app/" + name, data)
    for name, data in list(files.items()) + [("sq.version", b"<version>0.8.0</version>")]:
        path = os.path.join(root, "current", *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    # Not a program: starting it fails, which is the uninstall's failure to show.
    with open(os.path.join(root, "Update.exe"), "wb") as f:
        f.write(b"MZ")
    return root


def next_dialog(app, out, name, problems, want, answer, seconds=5.0):
    """Wait for the dialog `want(dialog)` picks (one opened by work on a worker thread), screenshot and measure it, then
    answer it. Returns a dict that holds it under "dialog" once it came."""
    seen, end = {}, time.time() + seconds

    def look():
        dialog = app.dialog
        if dialog is None or not want(dialog):
            if time.time() < end:
                app.root.after(100, look)
            else:
                problems.append("%s: the dialog never came" % name)
            return
        seen["dialog"] = dialog
        wait_out(app.root, 0.4)
        shot(app.root, out, name)
        problems.extend("%s: %s" % (name, p) for p in dialog.layout_problems())
        answer(dialog)

    app.root.after(100, look)
    return seen


def maintenance_check(app, out, tag, problems):
    """Help's Repair, Clear game data and Uninstall: each question, the work under way, and what comes after."""
    from opendmtq_client import dialogs, removal
    from opendmtq_client import state as st
    w = app.words
    install = os.environ["OPENDMTQ_INSTALL_ROOT"]
    # The game's folder with an id and some data.
    game = os.path.join(st.local_dir(), "OpenDMTQ", "com.example.game")
    song = os.path.join(game, "data", "external", "song.bin")
    os.makedirs(os.path.dirname(song), exist_ok=True)
    with open(os.path.join(game, "data", "android_id"), "w") as f:
        f.write("0123456789abcdef")
    with open(song, "wb") as f:
        f.write(b"s" * (3 << 20))
    app.go("help")
    settle(app)
    # The page's foot, where the tools and Reset and remove are.
    app.body.canvas.yview_moveto(1.0)
    wait_out(app.root, 0.6)
    shot(app.root, out, "%s_help-foot" % tag)
    answer = through_dialog(app, out, "%s_dialog-clear" % tag, button(app, w("help.clear.confirm")).press,
                            lambda d: d.canvas.event_generate("<Escape>"), problems)
    if answer is not False or not os.path.isfile(song):
        problems.append("%s: Esc on the clear dialog answered %r" % (tag, answer))

    def three_ways(dialog):
        if len(dialog.buttons) != 3 or dialog.focus != 0:
            problems.append("%s: the uninstall dialog has %d buttons, the ring on %r"
                            % (tag, len(dialog.buttons), dialog.focus))
    answer = through_dialog(app, out, "%s_dialog-uninstall" % tag, button(app, w("help.uninstall")).press,
                            lambda d: d.canvas.event_generate("<Escape>"), problems, extra=three_ways)
    if answer is not None or not os.path.isfile(song):
        problems.append("%s: Esc on the uninstall dialog answered %r" % (tag, answer))
    # Keep data, with an uninstaller that does not start: said, and the window stays.
    failed = next_dialog(app, out, "%s_dialog-uninstall-failed" % tag, problems,
                         lambda d: d.message == w("help.uninstall.failed"), lambda d: d.canvas.event_generate("<Return>"))
    through_dialog(app, out, "%s_dialog-uninstall-keep" % tag, button(app, w("help.uninstall")).press,
                   lambda d: click_button(d, 1), problems)
    if "dialog" not in failed or not app.root.winfo_exists():
        problems.append("%s: an uninstaller that did not start was not said" % tag)
    # The work under way, as the dialogs show it.
    for key, glyph in (("help.repair.working", "restore"), ("help.uninstall.working", "delete")):
        dialog = dialogs.Dialog(app.root, app.ui, "info", w(key), w(key), progress=True, glyph=glyph)
        wait_out(app.root, 0.6)
        shot(app.root, out, "%s_dialog-%s" % (tag, key.replace(".", "-")))
        problems.extend("%s_dialog-%s: %s" % (tag, key, p) for p in dialog.layout_problems())
        dialog.close(None)
    # Repair with a file of the launcher missing: put back, and said to need a restart.
    os.remove(os.path.join(install, "current", "OpenDMTQ.exe"))
    done = next_dialog(app, out, "%s_dialog-repaired" % tag, problems, lambda d: not d.progress,
                       lambda d: d.canvas.event_generate("<Return>"))
    button(app, w("help.repair")).press()
    wait_out(app.root, 2.0)
    dialog = done.get("dialog")
    if dialog is None or dialog.detail != w("help.repair.done.restart", n=1):
        problems.append("%s: the repair said %r" % (tag, dialog and dialog.detail))
    if not os.path.isfile(os.path.join(install, "current", "OpenDMTQ.exe")):
        problems.append("%s: the repair did not put the launcher's file back" % tag)
    # Clear game data, for real: the id alone stays.
    cleared = removal.game_data_size()
    through_dialog(app, out, "%s_dialog-clear-yes" % tag, button(app, w("help.clear.confirm")).press,
                   lambda d: click_button(d, 1), problems)
    wait_out(app.root, 2.0)
    left = sorted(os.path.relpath(os.path.join(f, n), game) for f, _d, names in os.walk(game) for n in names)
    if left != [os.path.join("data", "android_id")] or cleared != 3 << 20:
        problems.append("%s: clearing left %r (counted %d bytes)" % (tag, left, cleared))
    if app.status_text != w("help.clear.done", size="3 MB"):
        problems.append("%s: the status line said %r after clearing" % (tag, app.status_text))
    shot(app.root, out, "%s_help-cleared" % tag)


def stopped_check(out, tag, lang, problems):
    """The window an error nobody expected ends in (stopped.py), with a long path in it."""
    from opendmtq_client import dialogs, i18n
    w = i18n.Words(lang)
    error = OSError(28, "No space left on device", "C:\\Users\\player\\AppData\\Local\\OpenDMTQ\\client\\settings.json")
    root, dialog = dialogs.window("error", w("stopped.title"), w("stopped.message"),
                                  w("stopped.detail", error=w.error(error),
                                    path="C:\\Users\\player\\AppData\\Local\\OpenDMTQ\\client\\logs\\launcher.log"),
                                  [(w("start.close"), "close", "home")], 0, "close", language=lang)
    wait_out(root, 1.0)
    shot(root, out, "%s_stopped" % tag)
    problems.extend("%s_stopped: %s" % (tag, p) for p in dialog.layout_problems())
    dialog.canvas.event_generate("<Return>")
    root.update()
    if not dialog.closed or dialog.result != "close":
        problems.append("%s: Enter did not close the stopped dialog (answer %r)" % (tag, dialog.result))


def standalone_check(out, tag, lang, problems):
    """The window the launcher shows when it cannot read its settings (main._cannot_start)."""
    from opendmtq_client import dialogs, main
    from opendmtq_client import state as st
    # The same dialog main._cannot_start shows, in this language.
    error = st.StateError("cannot read", "C:\\Users\\player\\AppData\\Local\\OpenDMTQ\\client\\settings.json")
    root, dialog = dialogs.window(*main.cannot_start_dialog(error, lang), language=lang)
    wait_out(root, 1.0)
    shot(root, out, "%s_cannot-start" % tag)
    problems.extend("%s_cannot-start: %s" % (tag, p) for p in dialog.layout_problems())
    dialog.canvas.event_generate("<Escape>")
    root.update()
    if not dialog.closed or dialog.result != "close":
        problems.append("%s: Esc did not answer the start-up dialog (closed %r, answer %r)"
                        % (tag, dialog.closed, dialog.result))


def installer_check(out, tag, lang, problems):
    """The installer's dialogs around a stand-in for Velopack's setup: every question, one set up for a server, the
    work under way, the end with the server handed to the launcher, a failure, and a game running. Velopack itself runs
    in the Wine end-to-end test (client/tests/windows). With no launcher installed yet, they speak the language Windows
    is shown in: here `lang`, standing in for it."""
    from opendmtq_client import __version__, i18n, installer, preset
    from opendmtq_client import state as st
    st.system_language = lambda: lang
    w = i18n.Words(lang)
    home = tempfile.mkdtemp()
    os.environ["LOCALAPPDATA"] = home
    os.environ["OPENDMTQ_CLIENT_DIR"] = os.path.join(home, "OpenDMTQ", "client")
    app = os.path.join(home, "OpenDMTQ.Client")
    os.makedirs(os.path.join(app, "current"))
    # The installed launcher's stub: here a script that only leaves a mark that it ran.
    stub_exe = os.path.join(app, "OpenDMTQ.exe")
    with open(stub_exe, "w") as f:
        f.write("#!/bin/sh\ntouch '%s/started'\n" % home)
    os.chmod(stub_exe, 0o755)
    # An installer a site handed out: the server on its end.
    setup_file = os.path.join(home, "OpenDMTQ-Setup-club.test-8790.exe")
    with open(setup_file, "wb") as f:
        f.write(b"MZ" + bytes(4096) + preset.tail("http://club.test:8790", "Club 서버"))

    def fake_setup(code, version):
        """A stand-in for Velopack's setup that takes a second, then installs `version` or fails."""
        path = os.path.join(home, "setup-%d.sh" % code)
        with open(path, "w") as f:
            f.write("#!/bin/sh\nsleep 1\n")
            if code == 0:
                f.write("printf '<version>%s</version>' > '%s/current/sq.version'\n" % (version, app))
            else:
                f.write("echo '[12:00:01] [ERROR] Not enough space on the disk.' >> \"$3\"\n")
            f.write("exit %d\n" % code)
        os.chmod(path, 0o755)
        os.environ["OPENDMTQ_VELOPACK_SETUP"] = path

    def installed(version):
        sq = os.path.join(app, "current", "sq.version")
        if version is None:
            if os.path.exists(sq):
                os.remove(sq)
        else:
            with open(sq, "w") as f:
                f.write("<version>%s</version>" % version)

    def run_until(inst, seconds, until=lambda: False):
        end = time.time() + seconds
        while time.time() < end and not until():
            try:
                inst.root.update()
            except Exception:  # noqa: BLE001  (the window closed itself)
                return
            time.sleep(0.02)

    # A version below this one, for the update it offers (whatever this build's version is).
    major, minor, patch = installer.version_key(__version__)[0]
    older = ("%d.%d.%d" % (major, minor, patch - 1) if patch else "%d.%d.0" % (major, minor - 1) if minor else
             "%d.0.0" % (major - 1) if major else "0.0.0")
    for name, have, running, from_site in (("fresh", None, False, False), ("fresh-server", None, False, True),
                                           ("update", older, True, True), ("same", __version__, False, False),
                                           ("newer", "9.0.0", False, False)):
        installed(have)
        installer.launcher_open = lambda running=running: running
        if from_site:
            os.environ["OPENDMTQ_SETUP_FILE"] = setup_file
        else:
            os.environ.pop("OPENDMTQ_SETUP_FILE", None)
        inst = installer.Installer()
        run_until(inst, 0.6)
        shot(inst.root, out, "%s_setup-%s" % (tag, name))
        problems.extend("%s_setup-%s: %s" % (tag, name, p) for p in inst.dialog.layout_problems())
        inst.dialog.canvas.event_generate("<Escape>")
        run_until(inst, 0.3)
    # Install from a site's installer: the work under way, then the end, the server handed over, the launcher started.
    installed(None)
    fake_setup(0, __version__)
    os.environ["OPENDMTQ_SETUP_FILE"] = setup_file
    inst = installer.Installer()
    run_until(inst, 0.5)
    inst.dialog.canvas.event_generate("<Return>")
    run_until(inst, 0.5)
    shot(inst.root, out, "%s_setup-working" % tag)
    problems.extend("%s_setup-working: %s" % (tag, p) for p in inst.dialog.layout_problems())
    run_until(inst, 2.0, until=lambda: inst.process.poll() is not None)
    run_until(inst, 0.4)
    shot(inst.root, out, "%s_setup-done" % tag)
    run_until(inst, 2.0)
    if not os.path.exists(os.path.join(home, "started")):
        problems.append("%s: the installer did not start the launcher" % tag)
    if installer.installed_version() != __version__:
        problems.append("%s: the stand-in setup did not install" % tag)
    if preset.take() != {"url": "http://club.test:8790", "name": "Club 서버"}:
        problems.append("%s: the installer did not hand its server to the launcher" % tag)
    # A failure: Velopack's last error line and where the log is.
    installed(None)
    fake_setup(1, __version__)
    inst = installer.Installer()
    run_until(inst, 0.5)
    inst.dialog.canvas.event_generate("<Return>")
    run_until(inst, 2.5, until=lambda: inst.process is not None and inst.process.poll() is not None)
    run_until(inst, 0.6)
    shot(inst.root, out, "%s_setup-failed" % tag)
    problems.extend("%s_setup-failed: %s" % (tag, p) for p in inst.dialog.layout_problems())
    if "Not enough space" not in (inst.dialog.detail or ""):
        problems.append("%s: the failure did not show Velopack's error: %r" % (tag, inst.dialog.detail))
    inst.root.destroy()
    # A game running: the installer waits instead of replacing the player under it.
    installed(older)
    installer.game_running = lambda: True
    inst = installer.Installer()
    run_until(inst, 0.5)
    shot(inst.root, out, "%s_setup-game-running" % tag)
    problems.extend("%s_setup-game-running: %s" % (tag, p) for p in inst.dialog.layout_problems())
    if inst.dialog.message != w("setup.game"):
        problems.append("%s: the installer did not wait for the game: %r" % (tag, inst.dialog.message))
    inst.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--size", default="1180x760")
    args = parser.parse_args()
    if not safety.on_virtual_display():
        sys.exit("refusing: this opens windows; run it through client/tests/ui/run.sh")
    os.makedirs(args.out, exist_ok=True)
    home = tempfile.mkdtemp()
    os.environ["HOME"] = home
    os.environ["OPENDMTQ_CLIENT_DIR"] = os.path.join(home, "client")
    os.environ["XDG_DATA_HOME"] = os.path.join(home, "local")
    player = os.path.join(home, "player", "fake_player.py")
    os.makedirs(os.path.dirname(player))
    with open(player, "w", encoding="utf-8") as f:
        f.write(FAKE_PLAYER)
    os.environ["OPENDMTQ_PLAYER"] = player
    # Help as an installed launcher shows it: with Repair and Uninstall.
    os.environ["OPENDMTQ_INSTALL_ROOT"] = fake_install(home)
    site = stub.Site().start()
    from opendmtq_client import state as st
    from opendmtq_client.app import LauncherApp
    problems = []
    w, h = (int(x) for x in args.size.split("x"))
    tag = "%s-%s" % (args.lang, args.size)
    # ---- a first start with the server an installer from its site brought
    s = st.LauncherState()
    s.language = args.lang
    s.add_server(site.url, "Stand-in")
    s.save()
    app = LauncherApp(s)
    app.root.geometry("%dx%d+0+0" % (w, h))
    import traceback

    def callback_error(kind, value, tb):
        problems.append("callback error: %s" % "".join(traceback.format_exception_only(kind, value)).strip())
        traceback.print_exception(kind, value, tb)

    app.root.report_callback_exception = callback_error
    guide = guide_check(app, site, args.out, tag, problems)
    guide.finish(play=False)
    settle(app)
    pages_check(app, args.out, tag, problems)
    wheel_bindings_check(app, problems)
    variants_check(app, site, args.out, tag, problems)
    app.root.geometry("%dx%d+0+0" % (w, h))
    settle(app)
    dialogs_check(app, args.out, tag, problems)
    # Jobs the window still has waiting would fire into the next window's event loop once it is gone.
    for job in app.root.tk.splitlist(app.root.tk.call("after", "info")):
        app.root.after_cancel(job)
    app.root.destroy()
    standalone_check(args.out, tag, args.lang, problems)
    stopped_check(args.out, tag, args.lang, problems)
    # The installer in this language (Windows' display language, with no launcher installed yet).
    installer_check(args.out, tag, args.lang, problems)
    site.stop()
    with open(os.path.join(args.out, "problems-%s.txt" % tag), "w", encoding="utf-8") as f:
        f.write("\n".join(problems) + ("\n" if problems else ""))
    shots = len([n for n in os.listdir(args.out) if n.startswith(tag + "_") and n.endswith(".png")])
    print("%s: %d screens, %d problems" % (tag, shots, len(problems)))
    for p in problems:
        print("  " + p)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
