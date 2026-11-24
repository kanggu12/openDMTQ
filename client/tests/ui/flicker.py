"""Whether a setting changed in the launcher redraws the window visibly: the screen is filmed while a person changes a
setting (a switch with Space, a drop-down's choice, a row of tabs with an arrow key), and what the film shows between
the screen before and the screen after is counted, with the widgets the change made anew.

A change shows at once as the screen after it: the frames that are neither the screen before nor the one after
(a page half drawn, its cards gone for a moment, text wrapped narrow then wide) are the flicker a person sees. Each
change may make anew only the rows it brings, never the page. Beside the film, what each change does to the page is
noted, the same on a busy machine: no picture cut for the page's field, no frame of its flat colour put on the screen
over its picture, no card taken off the screen for a moment (FieldWatch).

Run inside the opendmtq-client-ui container only (client/tests/ui/run.sh); it refuses anywhere else, because it opens
windows. The film is the virtual screen's own pixels, taken as fast as it gives them (a frame every few ms).

  python tests/ui/flicker.py --lang en|ko [--size 1180x760] [--report FILE]      (from client/)
Exit status 1 when a change flickers or makes anew more than its rows; each change's counts are printed.
"""

import argparse
import importlib.util
import os
import sys
import threading
import time

# Run from client/ (the container mounts the repository and works there).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from opendmtq_client import art, safety, widgets  # noqa: E402

# The screenshots' helpers and the keyboard test's set-up (a launcher signed in with its app), from the files beside.
_here = os.path.dirname(__file__)
_spec = importlib.util.spec_from_file_location("shots", os.path.join(_here, "shots.py"))
shots = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shots)
_spec = importlib.util.spec_from_file_location("keyboard", os.path.join(_here, "keyboard.py"))
keyboard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(keyboard)

# How long the film runs after a change (seconds): the page's late work (its picture behind, a second look at a page
# that got shorter) comes within 0.2 s.
FILM = 0.6
# The frames in between allowed for a change of a value: one, within a 60 Hz display's frame (the control and its hint
# are two windows the X server may show a moment apart; nothing of the page goes blank).
FRAMES_ALLOWED, FRAMES_MS = 1, 17
# For a change that brings or takes a row (or makes a hint a line longer): Tk lays the page out parent by parent, and
# the rows under it move down within this many frames and milliseconds (two of a 60 Hz display's frames, and a margin
# for a busy test machine), never a page or a card emptied as before (7 to 11 frames over 150 ms and more).
MOVING_FRAMES, MOVING_MS = 2, 50
# For an answer that makes one card of a page again with other content (signed out: the sign-in form in place of the
# account), that card alone: its frames while it is laid out, never the page's other cards made again.
CARD_FRAMES, CARD_MS = 8, 250
# Where a frame between is saved as a picture for each change that has one (--frames), or None.
FRAMES_OUT = None
# What the changes do to the page beside the film (FieldWatch), once main() has made it.
FIELD = None


class Film:
    """The window's part of the virtual screen, taken over and over on a thread of its own while the window's thread
    works (Tk lets go of Python's lock while it draws, so the frames come between its steps too)."""

    def __init__(self, box):
        self.box, self.frames, self.times, self._stop = box, [], [], threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        from PIL import ImageGrab
        while not self._stop.is_set():
            frame = ImageGrab.grab(bbox=self.box, xdisplay=os.environ.get("DISPLAY"))
            # Kept as bytes: a frame is told from another by its pixels alone.
            data = frame.tobytes()
            if not self.frames or self.frames[-1] != data:
                self.frames.append(data)
                # When it first showed (the change's time on the screen is from its first frame to its last).
                self.times.append(time.monotonic())
            time.sleep(0.002)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


class FieldWatch:
    """What a change does to the page beside the film's timing, noted while it shows (and unlike the timing, the same on
    a busy machine):
    - a picture made for a frame of the page's field: the page's picture cut again for a frame that moved or grew kept
      the screen half drawn while it was made (16 ms and more when the connection test's card came); the field's
      frames show the page's one picture, placed (widgets.ScrollArea._paint_field);
    - a frame in the field's flat colour put on the screen: a card's holder put there before its card was painted flat
      over the page's picture until the card came; a holder has no colour of its own;
    - a card on the screen before the change taken off it and put back: the page's frame laid out in its old size while
      it waited to grow squeezed the cards under the change off the screen for a moment, and they were drawn again
      when they came back (the cards under the keyboard's lanes); the page's column has room for the page to grow."""

    def __init__(self, app):
        from PIL import ImageTk
        self.app, self.on, self.pictures, self.cards = app, False, [], set()
        real = ImageTk.PhotoImage.__init__
        watch = self

        def made(image, *args, **kwargs):
            # Each Tk image the launcher makes: noted when made for a canvas of the page's field.
            real(image, *args, **kwargs)
            if watch.on and getattr(kwargs.get("master"), "odq_field", False):
                watch.pictures.append("%dx%d" % (image.width(), image.height()))

        ImageTk.PhotoImage.__init__ = made
        # The windows Tk puts on the screen and takes off it, noted in Tcl alone while a change shows (a call into
        # Python for each would slow the very change the film times).
        app.root.tk.eval("set ::odq_noting 0; set ::odq_mapped {}; set ::odq_unmapped {}")
        app.root.tk.eval("bind all <Map> {+if {$::odq_noting} {lappend ::odq_mapped %W}}")
        app.root.tk.eval("bind all <Unmap> {+if {$::odq_noting} {lappend ::odq_unmapped %W}}")

    def _cards_on_show(self):
        """The page's cards on the screen now, each by the widget the page lays out: the card, or the holder it is made
        in (pages.Sections)."""
        found = set()
        for widget in shots.widgets_of(self.app.body.inner):
            if isinstance(widget, widgets.Card) and widget.winfo_ismapped():
                holder = widget.master
                found.add(str(holder if getattr(holder, "odq_holder", False) else widget))
        return found

    def start(self):
        """From now until done(): what the change does to the page."""
        self.pictures = []
        self.cards = self._cards_on_show()
        self.app.root.tk.eval("set ::odq_mapped {}; set ::odq_unmapped {}; set ::odq_noting 1")
        self.on = True

    def done(self):
        """Since start(): the pictures made for the field, the frames in its flat colour put on the screen, and the cards
        on the screen before that were taken off it and are back."""
        self.on = False
        tcl = self.app.root.tk
        tcl.eval("set ::odq_noting 0")
        flat = []
        area = self.app.body
        field = str(area.cget("bg")).lower()
        for path in tcl.splitlist(tcl.eval("set ::odq_mapped")):
            try:
                widget = self.app.root.nametowidget(str(path))
            except KeyError:
                # Gone again before the change ended.
                continue
            if (not widget.winfo_exists() or widget.winfo_class() != "Frame" or not str(widget).startswith(str(area))
                    or isinstance(widget, widgets.Card) or str(widget.cget("bg")).lower() != field):
                continue
            if any(isinstance(round_it, widgets.Card) for round_it in shots._ancestors_of(widget, area)):
                # Inside a card, in the field's colour by chance: the card's own, not the field.
                continue
            if str(widget) not in flat:
                # Once each (a card's new holder is put on the screen over the old one, then in its place).
                flat.append(str(widget))
        # A card there before and after, taken off the screen in between.
        taken = sorted(set(str(path) for path in tcl.splitlist(tcl.eval("set ::odq_unmapped")))
                       & self.cards & self._cards_on_show())
        return self.pictures, flat, taken


# The changes filmed, page by page, as a person makes them: (what it is, the control's kind, its row's name, the key
# pressed on it or the drop-down's choice, whether it brings or takes a row or makes a hint a line longer).
CHANGES = (
    ("screen", (
        ("VSync off (Space)", widgets.Toggle, "screen.vsync", "<space>", False),
        ("VSync on (Space)", widgets.Toggle, "screen.vsync", "<space>", False),
        ("frame limit 120", widgets.Select, "screen.fps", "120", False),
        ("frame limit back", widgets.Select, "screen.fps", "auto", False),
        ("FPS counter on (brings Position)", widgets.Toggle, "screen.counter", "<space>", True),
        ("FPS counter off (takes Position)", widgets.Toggle, "screen.counter", "<space>", True),
        ("render scale 75 (brings Upscaler)", widgets.Select, "screen.scale", "75", True),
        # FSR 1 is the default below 100 % (values.DEFAULTS): another one, so that the choice changes the screen.
        ("upscaler NIS", widgets.Select, "screen.upscaler", "nis", False),
        ("render scale 100 (takes Upscaler)", widgets.Select, "screen.scale", "100", True),
        ("anti-aliasing SMAA", widgets.Select, "screen.aa", "smaa", False),
        ("anti-aliasing off", widgets.Select, "screen.aa", "off", False),
        ("mode window (brings Window size)", widgets.Segmented, "screen.mode", "<Right>", True),
        ("mode full screen (takes it)", widgets.Segmented, "screen.mode", "<Left>", True))),
    ("sound", (
        ("master volume down (arrow)", widgets.Slider, "sound.volume.master", "<Left>", False),
        ("music volume down (arrow)", widgets.Slider, "sound.volume.music", "<Left>", False),
        ("equaliser Bass (arrow)", widgets.Segmented, "sound.eq.preset", "<Right>", True),
        ("low band up (makes it Custom)", widgets.Slider, "sound.eq.low", "<Right>", True),
        ("buffer normal (arrow)", widgets.Segmented, "sound.buffer", "<Right>", True),
        ("buffer low (arrow)", widgets.Segmented, "sound.buffer", "<Left>", True),
        ("mode exclusive (arrow)", widgets.Segmented, "sound.mode", "<Right>", True),
        ("mode shared (arrow)", widgets.Segmented, "sound.mode", "<Left>", True))),
    ("controls", (
        ("keyboard play off (dims the keys)", widgets.Toggle, "controls.keys.play", "<space>", True),
        ("keyboard play on (puts the keys in use)", widgets.Toggle, "controls.keys.play", "<space>", True))),
)


def grab(box):
    from PIL import ImageGrab
    return ImageGrab.grab(bbox=box, xdisplay=os.environ.get("DISPLAY")).tobytes()


def window_box(app):
    # The launcher (its app) or another window of the client's (its Tk root: the installer's).
    root = getattr(app, "root", app)
    root.update()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    return (x, y, x + root.winfo_width(), y + root.winfo_height())


def all_widgets(app):
    return set(shots.widgets_of(app.root))


def run_until(app, seconds):
    # The launcher (its app) or another window's Tk root, as window_box takes either.
    root = getattr(app, "root", app)
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.005)


def measure_change(app, name, act, results, rows_allowed=0, focus=None, moves=False, expect_change=True):
    """Film `act()` (a change as a person makes it) and count: the frames between the screen before and after, and the
    widgets the change made anew. `rows_allowed`: the widgets the change may make (the rows it brings). `focus()` gives
    the control the keyboard is on before the film starts (its ring is no part of the change)."""
    if focus is not None:
        focus().focus_set()
    shots.settle(app)
    run_until(app, 0.3)
    box = window_box(app)
    before_widgets = all_widgets(app)
    before = grab(box)
    if FIELD is not None:
        FIELD.start()
    with Film(box) as film:
        act()
        run_until(app, FILM)
    pictures, flat, taken = FIELD.done() if FIELD is not None else ([], [], [])
    after = grab(box)
    after_widgets = all_widgets(app)
    made = len(after_widgets - before_widgets)
    gone = len(before_widgets - after_widgets)
    between = [f for f in film.frames if f != before and f != after]
    # How long the screen showed frames between: from the first frame that is not the screen before to the first that
    # is the screen after (0 when it went from one to the other at once).
    shown = [t for f, t in zip(film.frames, film.times) if f != before]
    settled = [t for f, t in zip(film.frames, film.times) if f == after]
    span = int(round(1000 * (settled[0] - shown[0]))) if shown and settled and settled[0] >= shown[0] else 0
    changed = before != after
    results.append({"change": name, "moves": moves, "expect_change": expect_change, "frames_between": len(between),
                    "span": span, "made": made, "gone": gone, "changed": changed,
                    "rows_allowed": rows_allowed, "field_pictures": pictures, "flat_frames": flat,
                    "cards_taken": taken})
    if between and FRAMES_OUT:
        # The frame in the middle of the ones between, as a picture: what a person sees for a moment.
        from PIL import Image
        size = (box[2] - box[0], box[3] - box[1])
        for i, frame in enumerate(between):
            Image.frombytes("RGB", size, frame).save(os.path.join(FRAMES_OUT, "%02d-between-%d.png" % (len(results), i)))
        Image.frombytes("RGB", size, before).save(os.path.join(FRAMES_OUT, "%02d-0before.png" % len(results)))
        Image.frombytes("RGB", size, after).save(os.path.join(FRAMES_OUT, "%02d-9after.png" % len(results)))


def control(app, area, kind, title):
    found = keyboard.setting_control(area, kind, title)
    if found is None:
        raise AssertionError("no %s named %r on the page" % (kind.__name__, title))
    return found


def press(widget, key):
    """A key on a control the keyboard is on (measure_change puts it there before the film starts)."""
    widget.event_generate(key)


def choose(select, value):
    """A drop-down's choice as a person makes it: the value, then the drop-down's own event."""
    select.set_value(value)
    select.event_generate("<<ComboboxSelected>>")


def change(app, name, results, find, kind, key, act, rows_allowed=0, canvas=False, moves=False):
    """measure_change for the control of `kind` in the row named by `key`: the keyboard on it first, then `act(it)`."""
    def it():
        found = find(kind, key)
        return found.canvas if canvas else found
    try:
        it()
    except (AssertionError, KeyError) as e:
        # No such control (an older launcher's page): said, and the next change measured.
        results.append({"change": name, "missing": str(e)})
        return
    measure_change(app, name, lambda: act(it()), results, rows_allowed, focus=it, moves=moves)


# The page switches filmed after the changes, each from the page before it, as a person goes down the menu.
SWITCHES = ("help", "about", "play", "screen", "sound", "controls", "online")


def note_order(root):
    """From now on, while ::odq_ordering is set, the order in which the windows of `root`'s window leave the screen and
    go is noted (::odq_order), in Tcl alone: a call into Python for each would slow the very switch filmed. Bound once a
    window (each of the installer's runs has a window of its own)."""
    tcl = root.tk
    if tcl.eval("info exists ::odq_order_bound") == "1":
        return
    tcl.eval("set ::odq_order_bound 1; set ::odq_ordering 0; set ::odq_order {}")
    tcl.eval("bind all <Unmap> {+if {$::odq_ordering} {lappend ::odq_order [list unmap %W]}}")
    tcl.eval("bind all <Destroy> {+if {$::odq_ordering} {lappend ::odq_order [list destroy %W]}}")


def film_switch(root, area, act):
    """A page switch filmed (WIN-242): `act()` makes the next page of the window `root` in its page area `area` (a
    widgets.ScrollArea) as a click on the menu or a page's button does. The frames that showed while act() ran (the
    next page made), which must be none, the page before staying whole on the screen meanwhile (0.11.0 showed its frame
    flat under the old title for as long as the next page took to make: 0.8 s at 150 % on Windows for HELP); the page
    frames of the page before whose widgets went while it was still on the screen (tkinter takes a frame's widgets away
    one by one, each leaving the page's flat frame where it was); the frames between the page before and the page
    after; whether the screen changed. The window is settled first, as a person sees it before the click."""
    run_until(root, 0.3)
    box = window_box(root)
    before = grab(box)
    old = [str(child) for child in area.inner.winfo_children()]
    tcl = root.tk
    note_order(root)
    tcl.eval("set ::odq_order {}; set ::odq_ordering 1")
    with Film(box) as film:
        act()
        # The click's own work done: the frames seen by now showed the page while the next one was made.
        made = time.monotonic()
        run_until(root, FILM)
    tcl.eval("set ::odq_ordering 0")
    after = grab(box)
    during = [f for f, t in zip(film.frames, film.times) if t < made and f != before]
    between = [f for f in film.frames if f != before and f != after]
    order = [tcl.splitlist(item) for item in tcl.splitlist(tcl.eval("set ::odq_order"))]
    torn = []
    for frame in old:
        left = [i for i, (what, path) in enumerate(order) if what == "unmap" and str(path) == frame]
        went = [i for i, (what, path) in enumerate(order) if what == "destroy" and str(path).startswith(frame + ".")]
        if went and (not left or went[0] < left[0]):
            # Its widgets went while it was still on the screen.
            torn.append(frame)
    return {"during": len(during), "torn": torn, "frames_between": len(between), "changed": before != after}


# The faces of the page's controls (WIN-243): each kind's name, the function of art's that draws it (the version before
# kept none and drew in the function the widgets call), and how many of that kind a widget shows at a time (a row of
# tabs one a tab, a slider its track and its knob).
FACES = (
    ("buttons", ("_button_face", "button_face"), lambda w: int(isinstance(w, widgets.Button))),
    ("tabs", ("_tab_face", "tab_face"), lambda w: len(w.keys) if isinstance(w, widgets.Segmented) else 0),
    ("fields", ("_field_face", "field_face"), lambda w: int(isinstance(w, (widgets.Field, widgets.KeyBox)))),
    ("switches", ("_toggle", "toggle"), lambda w: int(isinstance(w, widgets.Toggle))),
    ("knobs", ("_knob", "knob"), lambda w: int(isinstance(w, widgets.Slider))),
    ("tracks", ("_slider_track", "slider_track"), lambda w: int(isinstance(w, widgets.Slider))),
)


def count_faces():
    """From now until restore() is called: each face art draws, counted by its kind (FACES). Returns (the counts, the
    kind's name -> how many drawn, and restore)."""
    drawn, kept = {kind: 0 for kind, _names, _shows in FACES}, []
    for kind, names, _shows in FACES:
        # The function that draws: the kept faces' own drawing where art has one, else the one the widgets call.
        name = names[0] if hasattr(art, names[0]) else names[1]
        real = getattr(art, name)

        def counted(*args, _real=real, _kind=kind, **kwargs):
            # Counted, then drawn as it would have been.
            drawn[_kind] += 1
            return _real(*args, **kwargs)

        setattr(art, name, counted)
        kept.append((name, real))

    def restore():
        for name, real in kept:
            setattr(art, name, real)

    return drawn, restore


def faces_shown(inner):
    """The faces the controls of the page in `inner` show, by kind (FACES)."""
    shown = {kind: 0 for kind, _names, _shows in FACES}
    for widget in shots.widgets_of(inner):
        for kind, _names, shows in FACES:
            shown[kind] += shows(widget)
    return shown


def switch_problems(name, filmed):
    """What film_switch saw that a person must not: frames while the page was made, a page taken apart on the screen,
    a screen that did not change."""
    problems = []
    if filmed["during"]:
        problems.append("%s: %d frames between showed while the page was made" % (name, filmed["during"]))
    for path in filmed["torn"]:
        problems.append("%s: the page before was taken apart on the screen (%s)" % (name, path))
    if not filmed["changed"]:
        problems.append("%s: the screen did not change" % name)
    return problems


def switch_page(app, page, results):
    """A page switch from the menu, filmed (film_switch, WIN-242), with the faces the launcher draws meanwhile counted
    for each kind of control (FACES, WIN-243)."""
    shots.settle(app)
    drawn, restore = count_faces()
    try:
        filmed = film_switch(app.root, app.body, lambda: app.nav_go(page))
    finally:
        restore()
    shown = faces_shown(app.body.inner)
    results.append(dict(filmed, change="menu: %s" % page.upper(), switch=True, drawn=drawn, shown=shown, span=0,
                        made=0, gone=0, moves="switch", rows_allowed=0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="en")
    parser.add_argument("--size", default="1180x760")
    parser.add_argument("--report")
    parser.add_argument("--frames")
    args = parser.parse_args()
    global FRAMES_OUT
    FRAMES_OUT = args.frames
    if FRAMES_OUT:
        os.makedirs(FRAMES_OUT, exist_ok=True)
    if not safety.on_virtual_display():
        sys.exit("refusing: this opens windows; run it through client/tests/ui/run.sh")
    site, state = keyboard.setup(args.lang)
    from opendmtq_client.app import LauncherApp
    app = LauncherApp(state)
    app.root.geometry("%s+0+0" % args.size)
    shots.settle(app)
    w = app.words
    results = []
    # What each change does to the page, noted from the first change on (FieldWatch).
    global FIELD
    FIELD = FieldWatch(app)

    find = lambda kind, key: control(app, app.body, kind, w(key))  # noqa: E731
    for page, changes in CHANGES:
        app.nav_go(page)
        shots.settle(app)
        if page == "sound":
            # The devices come from the player on a worker thread: their row is made when they come.
            shots.settle(app, 6, until=lambda: app.devices is not None)
            shots.settle(app)
        for name, kind, key, how, moves in changes:
            # A key on the control, or a drop-down's choice (a value in place of a key).
            act = (lambda c, k=how: press(c, k)) if how.startswith("<") else (lambda c, v=how: choose(c, v))
            change(app, "%s: %s" % (page, name), results, find, kind, key, act, canvas=kind is widgets.Slider,
                   moves=moves)

    # ---- Answers that change a card of a page, never the page: Help's Check again with nothing changed makes nothing
    # anew; Online's Sign out makes the sign-in card again and leaves the server's and the app's cards as they were.
    app.nav_go("help")
    shots.settle(app)
    recheck = shots.button(app, w("help.recheck"))
    measure_change(app, "help: Check again, nothing changed", lambda: recheck.press(), results, focus=lambda: recheck,
                   expect_change=False)
    app.nav_go("online")
    shots.settle(app)
    kept = [x for x in shots.widgets_of(app.body.inner) if isinstance(x, widgets.Field)]
    sign_out = shots.button(app, w("online.signout"))
    measure_change(app, "online: Sign out, its card alone", lambda: sign_out.press(), results, rows_allowed=60,
                   focus=lambda: sign_out, moves="card")
    if not kept or not all(x.winfo_exists() for x in kept):
        results.append({"change": "online: Sign out", "missing": "the server's card was made again"})

    # ---- The connection test: Test connection makes its card alone (its steps waiting: the test is held at its start),
    # then each step says itself in place, nothing made or gone, until the test ends.
    from opendmtq_client import connection
    gate, real_run = threading.Event(), connection.run

    def held_run(*args, **kwargs):
        gate.wait(10)
        return real_run(*args, **kwargs)

    connection.run = held_run
    try:
        kept = [x for x in shots.widgets_of(app.body.inner) if isinstance(x, widgets.Field)]
        test = shots.button(app, w("test.button"))
        measure_change(app, "online: Test connection, its card alone", lambda: test.press(), results, rows_allowed=150,
                       focus=lambda: test, moves="card")
        if not kept or not all(x.winfo_exists() for x in kept):
            results.append({"change": "online: Test connection", "missing": "the server's card was made again"})
        shots.settle(app)
        before = all_widgets(app)
        gate.set()
        shots.settle(app, 30, until=lambda: not app.connection_test["running"])
        after = all_widgets(app)
        results.append({"change": "online: the test's steps said in place", "moves": False, "expect_change": True,
                        "frames_between": 0, "span": 0, "made": len(after - before), "gone": len(before - after),
                        "changed": True, "rows_allowed": 0})
    finally:
        connection.run = real_run

    # ---- Page switches from the menu, every page in turn (switch_page; film_switch notes the windows' order).
    for page in SWITCHES:
        switch_page(app, page, results)

    for job in app.root.tk.splitlist(app.root.tk.call("after", "info")):
        app.root.after_cancel(job)
    app.root.destroy()
    site.stop()

    problems = []
    lines = []
    for r in results:
        if "missing" in r:
            lines.append("%-48s no such control (%s)" % (r["change"], r["missing"]))
            problems.append("%s: no such control" % r["change"])
            continue
        if r.get("switch"):
            # A page switch (switch_page): none of its frames while the next page is made, the page before whole.
            faces = ", ".join("%s %d/%d" % (kind, r["drawn"][kind], r["shown"][kind]) for kind, _n, _s in FACES
                              if r["drawn"][kind] or r["shown"][kind])
            lines.append("%-48s frames while the page was made %2d, frames between %2d, faces drawn/shown: %s"
                         % (r["change"], r["during"], r["frames_between"], faces or "none"))
            for kind, _names, _shows in FACES:
                if r["drawn"][kind] > r["shown"][kind]:
                    # Each control's other faces wait until it shows them, and a face drawn before is kept (WIN-243).
                    problems.append("%s: %d faces drawn for %d %s (one each at most)" % (
                        r["change"], r["drawn"][kind], r["shown"][kind], kind))
            problems.extend(switch_problems(r["change"], r))
            continue
        lines.append("%-48s frames between %2d over %3d ms, widgets made %3d, gone %3d" % (
            r["change"], r["frames_between"], r["span"], r["made"], r["gone"]))
        frames, ms = {"card": (CARD_FRAMES, CARD_MS), True: (MOVING_FRAMES, MOVING_MS),
                      False: (FRAMES_ALLOWED, FRAMES_MS)}[r["moves"]]
        if r["frames_between"] > frames or r["span"] > ms:
            problems.append("%s: %d frames between the screen before and after, over %d ms" % (
                r["change"], r["frames_between"], r["span"]))
        if r.get("gone", 0) > r["rows_allowed"] and r["change"].endswith("said in place"):
            problems.append("%s: %d widgets gone (none may go)" % (r["change"], r["gone"]))
        if r["made"] > r["rows_allowed"]:
            problems.append("%s: %d widgets made anew (the rows it brings: %d at most)" % (r["change"], r["made"],
                                                                                         r["rows_allowed"]))
        if not r["changed"] and r.get("expect_change", True):
            problems.append("%s: the screen did not change" % r["change"])
        for size in r.get("field_pictures", ()):
            # The page's picture cut again for a frame of its field while the change shows (WIN-240).
            problems.append("%s: a picture made for the page's field while it changed (%s)" % (r["change"], size))
        for path in r.get("flat_frames", ()):
            # A frame put on the screen in the field's flat colour, over the page's picture, until what covers it came.
            problems.append("%s: a frame in the field's flat colour put on the screen (%s)" % (r["change"], path))
        for path in r.get("cards_taken", ()):
            # A card under the change squeezed off the screen for a moment while the page waited to grow (WIN-241).
            problems.append("%s: a card taken off the screen for a moment (%s)" % (r["change"], path))
    report = "flicker %s %s: %d changes, %d problems\n" % (args.lang, args.size, len(results), len(problems))
    report += "".join("  %s\n" % line for line in lines)
    report += "".join("  PROBLEM %s\n" % p for p in problems)
    print(report, end="")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
