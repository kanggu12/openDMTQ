"""The installer's window (OpenDMTQ-Setup.exe, and the uninstall Windows' Settings, Apps opens) on the test container's
virtual screen: every page and state it shows, a screenshot of each, and the layout measured as the launcher's pages
are (text cut off, a control past the window's edge or squeezed, a line running under the strip with the buttons).
Its own header, in place of Windows' title bar, on every page: the minimise and close buttons at its top right, in
the launcher's quiet metal (the close button red under the pointer, never lime), clear of the title; Tab reaching them
after the strip's buttons with their ring, Enter, Space and a click pressing them; its top moving the window; the close
button refused while work is under way and closing the window when none is; and the window an error ends the installer
in, moved by its shards and its card.

Run inside the opendmtq-client-ui container only (client/tests/ui/run.sh); it refuses anywhere else, because it opens
windows. Nothing is installed or removed: Velopack's setup and uninstaller are stand-ins that write what the real ones
write (a log, the program's folder filling or emptying) in a folder of the run's own.

  python tests/ui/setup_shots.py --out DIR [--lang en|ko] [--tag TAG]      (from client/)
Exit status 1 when the layout check finds a problem; the problems are printed and written to DIR/setup-problems-*.txt.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from unittest import mock

# Run from client/ (the container mounts the repository and works there).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from opendmtq_client import safety  # noqa: E402

# The launcher's measure of boxes and room, and its film of a page switch, from the files beside this one.
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("spacing", os.path.join(os.path.dirname(__file__), "spacing.py"))
spacing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spacing)
# The launcher's design measures (tests/ui/design.py), the installer's pages measured by them as the launcher's are.
_spec = importlib.util.spec_from_file_location("design", os.path.join(os.path.dirname(__file__), "design.py"))
design = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(design)
_spec = importlib.util.spec_from_file_location("flicker", os.path.join(os.path.dirname(__file__), "flicker.py"))
flicker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(flicker)

# Velopack's setup's log as it writes it, line by line (its real words, a run of 0.10.0's under Wine).
SETUP_LOG = """[setup:448] [11:47:52] [INFO] Starting Velopack Setup (1.2.161)
[setup:448] [11:47:52] [INFO] Reading bundle header...
[setup:448] [11:47:52] [INFO] Bundle offset = 7546368, length = 41322990
[setup:448] [11:47:52] [INFO] There is 312.75 GB free space available at destination, this package requires 187.49 MB.
[setup:448] [11:47:52] [INFO] Preparing and cleaning installation directory...
[setup:448] [11:47:52] [INFO] Extracting Update.exe...
[setup:448] [11:47:52] [INFO] Copying nupkg to packages directory...
[setup:448] [11:47:52] [INFO] Extracting 1032 app files to '"C:\\\\users\\\\player\\\\AppData\\\\Local\\\\OpenDMTQ.Client\\\\current"'...
"""


class Process:
    """A stand-in for a program the installer starts and waits for: running until `ends` (a time), then `code`."""

    def __init__(self, seconds, code=0, during=None):
        self.ends, self.code, self.during = time.time() + seconds, code, during

    def poll(self):
        if self.during is not None:
            self.during()
        return None if time.time() < self.ends else self.code

    def kill(self):
        self.ends = 0


def widgets_of(widget):
    yield widget
    for child in widget.winfo_children():
        yield from widgets_of(child)


def measure(window, name, problems):
    """The page as a person sees it: no text cut off, nothing past the window's right edge or under the strip along its
    foot, no button squeezed, every line of text inside its card."""
    import tkinter as tk
    from opendmtq_client import widgets
    root = window.root
    root.update()
    right = root.winfo_rootx() + root.winfo_width()
    strip_top = window.strip.master.winfo_rooty()
    for w in widgets_of(root):
        if not w.winfo_ismapped():
            continue
        cls = w.winfo_class()
        if cls == "Label" and w.cget("text") and w.winfo_reqwidth() > w.winfo_width() + 2:
            problems.append("%s: text cut off: %r (needs %d px, has %d)" % (name, w.cget("text")[:60],
                                                                            w.winfo_reqwidth(), w.winfo_width()))
        if cls in ("Label", "Frame", "Canvas") and w.winfo_width() > 1 and w.winfo_viewable():
            if w.winfo_rootx() + w.winfo_width() > right + 1:
                problems.append("%s: past the right edge: %s %r" % (name, cls, (w.cget("text") if cls == "Label"
                                                                                else "")[:40]))
        if isinstance(w, widgets.Button) and w.winfo_width() + 1 < w.winfo_reqwidth():
            problems.append("%s: button squeezed: %r" % (name, w.words))
        if isinstance(w, tk.Label) and w.cget("text") and str(w).startswith(str(window.page_area.inner)):
            # Text of the page lies above the strip once the page is scrolled to it: the page area ends there.
            area = window.page_area.canvas
            if w.winfo_rooty() + w.winfo_height() > area.winfo_rooty() + area.winfo_height() + 1 \
                    and area.yview() == (0.0, 1.0):
                problems.append("%s: text under the strip: %r" % (name, w.cget("text")[:40]))
    if window.page_area.canvas.winfo_rooty() + window.page_area.canvas.winfo_height() > strip_top + 1:
        problems.append("%s: the page runs under the strip" % name)
    # At the window's own size (800 x 540, at any scaling) a page fits it whole: no scroll bar (main's choose page with
    # the launcher and the game both open ran its card under the strip, a scroll bar at its edge). A small screen's
    # smaller window may scroll.
    from opendmtq_client import setup_window
    px = window.ui.px
    if (root.winfo_width(), root.winfo_height()) == (px(setup_window.WIDTH), px(setup_window.HEIGHT)) and \
            window.page_area.bar.winfo_ismapped():
        problems.append("%s: the page needs a scroll bar at the window's own size" % name)
    # The launcher's own measure of boxes and room (tests/ui/spacing.py): nothing touching, words inside their card's
    # padding, the gaps on the spacing scale.
    problems.extend(spacing.check(root, window.ui, name))
    # The design's measures: the words in their roles, the buttons by theirs, no shard at the page's card.
    problems.extend(design.check(root, window.ui, name))
    # The header the installer draws instead of Windows' title bar.
    problems.extend(header_problems(window, name))


def near(pixel, colour, slack):
    """A pixel within `slack` of a colour (#rrggbb) on each channel."""
    from opendmtq_client import art
    return all(abs(a - b) <= slack for a, b in zip(pixel, art._rgb(colour)))


def header_problems(window, name):
    """The header in place of Windows' title bar: its minimise and close at the top right, level with the wordmark's
    top, the right size and room apart, clear of the page's title; quiet metal at rest, the close button red under the
    pointer, never the lime of the screen's one main button; the title's letters clear of the header's foot."""
    from opendmtq_client import setup_window, theme, widgets
    found, root, px = [], window.root, window.ui.px
    header = getattr(window, "header", None)
    buttons = list(getattr(header, "buttons", []))
    if [getattr(b, "glyph", None) for b in buttons] != ["minimize", "close"]:
        return ["%s: the header has no minimise and close buttons of its own" % name]
    size = px(setup_window.BUTTON)
    ox, oy = root.winfo_rootx(), root.winfo_rooty()
    places = [(b.winfo_rootx() - ox, b.winfo_rooty() - oy, b.winfo_width(), b.winfo_height()) for b in buttons]
    for button, (x, y, w, h) in zip(buttons, places):
        if not button.winfo_ismapped():
            found.append("%s: the %s button is not shown" % (name, button.glyph))
        if (w, h) != (size, size):
            found.append("%s: the %s button is %dx%d, not %d square" % (name, button.glyph, w, h, size))
    # Level with the wordmark's top in the column, the close button the column's own room in from the right edge, the
    # minimise button the buttons' gap before it.
    mark_top = window.mark.winfo_rooty() - oy
    for button, (x, y, w, h) in zip(buttons, places):
        if y != mark_top or y != px(setup_window.BUTTON_TOP):
            found.append("%s: the %s button's top is at %d, the wordmark's at %d" % (name, button.glyph, y, mark_top))
    if places[1][0] + size != root.winfo_width() - px(setup_window.BUTTON_RIGHT):
        found.append("%s: the close button ends %d px from the window's right edge" % (
            name, root.winfo_width() - places[1][0] - size))
    if places[1][0] - (places[0][0] + size) != px(setup_window.BUTTON_GAP):
        found.append("%s: %d px between minimise and close" % (name, places[1][0] - places[0][0] - size))
    # The page's title ends the title's room before the buttons, and its letters end clear of the header's foot.
    if header.title_box is None:
        found.append("%s: the header shows no title" % name)
    else:
        if header.title_box[2] + px(setup_window.TITLE_ROOM) > buttons[0].winfo_x():
            found.append("%s: the title reaches %d px of the minimise button" % (
                name, buttons[0].winfo_x() - header.title_box[2]))
        ink = header.title_picture.split()[-1].getbbox()
        if header.title_box[1] + ink[3] > header.tall - max(1, px(1)) - px(spacing.LEAST_TEXT_GAP):
            found.append("%s: the title's letters reach %d px of the header's foot" % (
                name, header.tall - header.title_box[1] - ink[3]))
    # Their looks: quiet metal at rest (no lime, no red), the close button red under the pointer and minimise metal.
    for button in buttons:
        rest = button.face("normal", False)
        middle = rest.getpixel((size // 4, size * 5 // 8))
        if not near(middle, theme.RAIL_UP, 8):
            found.append("%s: the %s button at rest is #%02x%02x%02x, not quiet metal" % ((name, button.glyph) + middle))
        for state in ("normal", "hover", "pressed"):
            for ring in (False, True):
                if any(near(p, theme.OK, 40) for p in button.face(state, ring).getdata()):
                    found.append("%s: the %s button is lime %s" % (name, button.glyph, state))
    hover = [b.face("hover", False).getpixel((size // 4, size * 5 // 8)) for b in buttons]
    if near(hover[0], theme.BAD, 40) or not near(hover[1], theme.BAD, 8):
        found.append("%s: under the pointer minimise is %s and close %s" % (name, hover[0], hover[1]))
    # The screen keeps its one main button: never more than one lime button anywhere in the window, nor a lime one
    # beside the filled red of removing for good.
    lime = [w for w in widgets_of(root) if isinstance(w, widgets.Button) and w.look in ("home", "danger")
            and w.winfo_ismapped()]
    if len(lime) > 1:
        found.append("%s: %d main buttons" % (name, len(lime)))
    return found


def shot(root, out, name):
    """Screenshot of the window, through the X server (what a person would see)."""
    root.update()
    time.sleep(0.3)
    root.update()
    target = os.path.join(out, name + ".png")
    subprocess.run(["import", "-window", str(root.winfo_id()), target], check=True)
    return target


def settle(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def stopped_window(args, tag, problems):
    """The window an error that ends the installer is said in (stopped.py), as the installer opens it: without Windows'
    title bar on Windows, so its shards and its card move it (here by its geometry); its buttons are pressed, never
    dragged; measured as the launcher's dialogs are."""
    from opendmtq_client import dialogs, i18n, stopped
    w = i18n.Words(args.lang)
    log_path = "C:\\Users\\player\\AppData\\Local\\Temp\\OpenDMTQ-setup.log"
    error = OSError(28, "No space left on device", log_path)
    name = "setup-%s_stopped" % tag
    try:
        root, dialog = dialogs.window(*stopped.dialog(w, error, log_path), language=args.lang, frameless=True)
    except TypeError as e:
        # A launcher from before the installer drew its own header: its dialog window keeps Windows' title bar.
        problems.append("%s: the installer's error window cannot come without a title bar (%s)" % (name, e))
        return
    settle(root, 1.0)
    shot(root, args.out, name)
    problems.extend(spacing.check_dialog(dialog, name))
    # Its buttons as the launcher's dialogs' and pages' are.
    problems.extend(design.check_dialog(dialog, name))
    canvas, start = dialog.canvas, (root.winfo_rootx(), root.winfo_rooty())

    def drag(x, y, dx, dy):
        rx, ry = canvas.winfo_rootx() + x, canvas.winfo_rooty() + y
        canvas.event_generate("<Motion>", x=x, y=y, rootx=rx, rooty=ry)
        canvas.event_generate("<ButtonPress-1>", x=x, y=y, rootx=rx, rooty=ry)
        canvas.event_generate("<B1-Motion>", x=x + dx, y=y + dy, rootx=rx + dx, rooty=ry + dy)
        settle(root, 0.4)
        moved = (root.winfo_rootx() - start[0], root.winfo_rooty() - start[1])
        canvas.event_generate("<ButtonRelease-1>", x=x + dx, y=y + dy, rootx=rx + dx, rooty=ry + dy)
        settle(root, 0.4)
        return moved

    # By the shards round the card, then back by the card's words.
    if drag(6, 6, 30, 20) != (30, 20):
        problems.append("%s: a drag on the shards did not move the window" % name)
    x0, y0 = dialog.origin
    if drag(x0 + dialog.ui.px(dialogs.PAD) + 4, y0 + dialog.ui.px(dialogs.PAD) + 4, -30, -20) != (0, 0):
        problems.append("%s: a drag on the card did not move the window back" % name)
    # A press on its last button (Close), dragged off it: the window stays where it is, and the button, let go off
    # itself, answers nothing (a person changing their mind), as on the launcher's dialogs.
    left, top, right, bottom = dialog._boxes[-1]
    if drag(x0 + (left + right) // 2, y0 + (top + bottom) // 2, 0, -dialog.ui.px(60)) != (0, 0) or dialog.closed:
        problems.append("%s: a press on its Close moved it, or answered when let go off it" % name)
    # Then Enter answers it as Close does, and the window goes (as shots.py's stopped_check closes the launcher's): the
    # keyboard on the card first, which the presses made by hand above leave elsewhere on this screen with no window
    # manager (Tk sends a key to the window with the keyboard).
    dialog.canvas.focus_force()
    settle(root, 0.2)
    dialog.canvas.event_generate("<Return>")
    root.update()
    if not dialog.closed or dialog.result != dialog.buttons[-1][1]:
        problems.append("%s: Enter did not answer it as its Close (%r)" % (name, dialog.result))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    if not safety.on_virtual_display():
        sys.exit("refusing: this opens windows; run it through client/tests/ui/run.sh")
    os.makedirs(args.out, exist_ok=True)
    home = tempfile.mkdtemp()
    local = os.path.join(home, "local")
    for name, value in (("HOME", home), ("LOCALAPPDATA", local), ("XDG_DATA_HOME", local),
                        ("OPENDMTQ_CLIENT_DIR", os.path.join(local, "OpenDMTQ", "client"))):
        os.environ[name] = value
    from opendmtq_client import __version__, installer, removal
    from opendmtq_client import state as st
    # The launcher's language as the player chose it.
    state = st.LauncherState()
    state.language = args.lang
    state.save()
    tag = "%s%s" % (args.lang, ("-" + args.tag) if args.tag else "")
    problems = []
    folder = installer.app_dir()

    def program(version):
        """An install folder as Velopack lays one out, of `version`, with a few files of the program."""
        os.makedirs(os.path.join(folder, "current", "player"), exist_ok=True)
        with open(os.path.join(folder, "current", "sq.version"), "w") as f:
            f.write("<version>%s</version>" % version)
        with open(os.path.join(folder, "Update.exe"), "wb") as f:
            f.write(b"MZ" + b"\0" * 4000)
        with open(os.path.join(folder, "current", "player", "OpenDMTQ-Player.exe"), "wb") as f:
            f.write(b"MZ" + b"\0" * 400000)

    def data():
        """The launcher's settings and a game's data, so that the uninstall has sizes to say."""
        game = os.path.join(removal.data_root(), "com.example.game", "data")
        os.makedirs(game, exist_ok=True)
        with open(os.path.join(game, "android_id"), "w") as f:
            f.write("0123456789abcdef")
        with open(os.path.join(game, "songs.bin"), "wb") as f:
            f.write(b"\0" * (3 << 20))

    def run(name, make, steps=()):
        """Open the window as `make()` makes it, take each step (a function of the window and the installer), then a
        screenshot and the measures; the window closed after."""
        if not os.path.isfile(st.LauncherState.path()):
            # Delete everything took the launcher's settings, the player's language with them: given back, so that
            # every page is seen in the run's language.
            kept = st.LauncherState()
            kept.language = args.lang
            kept.save()
        made = make()
        window = made.window
        settle(window.root, 1.0)
        full = "setup-%s_%s" % (tag, name)
        try:
            for step in steps:
                step(made)
                settle(window.root, 0.6)
            shot(window.root, args.out, full)
            measure(window, full, problems)
        except tk.TclError as e:
            # A window that went when it should have stayed (its step says why): nothing left to look at.
            problems.append("%s: the window went: %s" % (full, e))
            return
        try:
            # Its timers first (a bar's easing, a look at the work): they would call widgets that are gone.
            for job in window.root.tk.splitlist(window.root.tk.call("after", "info")):
                window.root.after_cancel(job)
            window.root.destroy()
        except Exception:  # noqa: BLE001  (a page that closed itself already)
            pass

    patches = [mock.patch.object(installer, "launcher_open", return_value=False),
               mock.patch.object(installer, "game_running", return_value=False),
               mock.patch.object(installer, "start_launcher"),
               mock.patch.object(installer, "own_entry"),
               mock.patch.object(installer, "brought", return_value={"url": "http://192.168.1.10:8790",
                                                                      "name": "Club Night"})]
    for patch in patches:
        patch.start()

    # ---- a PC without OpenDMTQ: Install, its progress, its end.
    import shutil
    shutil.rmtree(folder, ignore_errors=True)
    run("install", installer.Installer)

    # A long user folder: the Program row's lines each end after a separator, a folder's name never cut (main broke
    # "OpenDMT / Q.Client" on Windows at 150 %).
    long_folder = os.path.join(home, "a-user-folder-whose-name-runs-long", "AppData", "Local", "Temp", "odq-test",
                               "OpenDMTQ.Client")

    def program_row(made):
        import tkinter.font as tkfont
        settle(made.root, 0.5)
        label = next((w for w in widgets_of(made.root) if w.winfo_class() == "Label" and w.winfo_ismapped()
                      and w.cget("text").replace("\n", "") == long_folder), None)
        if label is None:
            problems.append("setup-%s: the Install page does not show the long folder whole" % tag)
            return
        font = tkfont.Font(made.root, font=label.cget("font"))
        lines = label.cget("text").split("\n")
        wrap = int(label.winfo_fpixels(str(label.cget("wraplength"))))
        if len(lines) < 2 or any(not line.endswith(os.sep) for line in lines[:-1]) or \
                any(font.measure(line) > wrap for line in lines):
            problems.append("setup-%s: the long folder's lines are %r in %d px" % (tag, lines, wrap))

    run("install-long-folder", lambda: installer.Installer(folder=long_folder), [program_row])

    # A server that calls itself by its address (no name of its own): said once (main: "192.168.1.10:8791  ·
    # http://192.168.1.10:8791").
    def server_once(made):
        said = [w.cget("text") for w in widgets_of(made.root) if w.winfo_class() == "Label" and w.winfo_ismapped()]
        rows = [text for text in said if "192.168.1.10" in text]
        if rows != ["http://192.168.1.10:8791"]:
            problems.append("setup-%s: a server with no name of its own is said as %r" % (tag, rows))

    with mock.patch.object(installer, "brought", return_value={"url": "http://192.168.1.10:8791",
                                                               "name": "192.168.1.10:8791"}):
        run("install-unnamed", installer.Installer, [server_once])

    def setup_runs(path):
        """Velopack's setup as it runs: its log written (to the path the installer names), the program's folder filling
        a little at each look."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(SETUP_LOG)

        def fill():
            program(__version__)
            chunk = os.path.join(folder, "current", "chunk.bin")
            if not os.path.exists(chunk) or os.path.getsize(chunk) < (110 << 20):
                with open(chunk, "ab") as f:
                    f.write(b"\0" * (8 << 20))

        return Process(60, 0, during=fill)

    def close_while_busy(made):
        """The close button while Velopack's setup is under way: the window stays, as it did for Windows' X."""
        if not hasattr(made.window, "header"):
            problems.append("setup-%s: the window has no header of its own (%s)" % (tag, "close_while_busy"))
            return
        button = made.window.header.buttons[1]
        rx, ry = button.winfo_rootx() + 16, button.winfo_rooty() + 16
        if not made.busy:
            problems.append("setup-%s: the install was not under way when its close button was pressed" % tag)
        button.event_generate("<ButtonPress-1>", x=16, y=16, rootx=rx, rooty=ry)
        button.event_generate("<ButtonRelease-1>", x=16, y=16, rootx=rx, rooty=ry)
        try:
            alive = bool(made.root.winfo_exists())
        except tk.TclError:
            alive = False
        if not alive:
            problems.append("setup-%s: the close button closed the window while the install was under way" % tag)
            return
        settle(made.root, 0.3)
        # Said: the close button dimmed while the work goes on, and a press of it (or Alt+F4) answered on the strip's
        # line (main: the button looked pressable and nothing answered).
        from opendmtq_client import i18n
        if getattr(button, "enabled", True):
            problems.append("setup-%s: the close button looks pressable while the install is under way" % tag)
        said = made.words("setup.busy.close") if "setup.busy.close" in i18n.TEXT else None
        if said is None or made.window.note.cget("text") != said:
            problems.append("setup-%s: a close while the install is under way is answered with %r" % (
                tag, made.window.note.cget("text")))

    with mock.patch.object(installer, "run_setup", setup_runs):
        run("installing", installer.Installer, [lambda made: made.work("install"), lambda made: settle(made.root, 1.5),
                                                close_while_busy])
    shutil.rmtree(folder, ignore_errors=True)
    with mock.patch.object(installer, "run_setup", lambda path: Process(0.3, 0, during=lambda: program(__version__))):
        run("installed", installer.Installer, [lambda made: made.work("install"), lambda made: settle(made.root, 2.0)])
    # ---- a PC with OpenDMTQ: the same version, an older one (Update), a newer one (go back).
    program(__version__)
    run("choose", installer.Installer)

    # The keyboard alone (P1: nothing reachable only by the pointer): Tab goes the choices, then the strip's buttons;
    # the arrow keys move the choice; Enter on the choices does the main button's; Esc on the uninstall's page goes
    # back, on the first page closes the window.
    def keys(made):
        from opendmtq_client import setup_window
        root = made.root
        settle(root, 0.5)
        focus = root.focus_get()
        if not isinstance(focus, setup_window.Options):
            problems.append("setup-%s: the choices do not have the keyboard at first (%r)" % (tag, focus))
            return
        order = [focus]
        widget = focus
        for _ in range(4):
            widget = widget.tk_focusNext()
            if widget is None or widget in order:
                break
            order.append(widget)
        words = [getattr(w, "words", None) for w in order[1:]]
        if words[:2] != [made.words("setup.close"), made.words("setup.open")]:
            problems.append("setup-%s: Tab goes %r after the choices" % (tag, words))
        for key in ("<Down>", "<Down>"):
            focus.event_generate(key)
        if focus.value != "uninstall":
            problems.append("setup-%s: the arrow keys did not reach Uninstall (%s)" % (tag, focus.value))
        focus.event_generate("<Return>")
        settle(root, 0.5)
        if made.flow[0][1] != "data":
            problems.append("setup-%s: Enter on Uninstall did not open the uninstall's page" % tag)
        root.event_generate("<Escape>")
        settle(root, 0.5)
        if made.flow[0][0] != "choose":
            problems.append("setup-%s: Esc on the uninstall's page did not go back (%r)" % (tag, made.flow))

    run("choose-keys", installer.Installer, [keys])

    # The window's own buttons and its top, in place of Windows' title bar (WIN-220).
    def press_at(widget, x, y, dx=0, dy=0):
        """A press of the pointer on `widget` at (x, y), moved by (dx, dy) and let go, as a person drags or clicks."""
        rx, ry = widget.winfo_rootx() + x, widget.winfo_rooty() + y
        widget.event_generate("<Enter>", x=x, y=y, rootx=rx, rooty=ry)
        widget.event_generate("<ButtonPress-1>", x=x, y=y, rootx=rx, rooty=ry)
        if dx or dy:
            widget.event_generate("<B1-Motion>", x=x + dx, y=y + dy, rootx=rx + dx, rooty=ry + dy)
        widget.event_generate("<ButtonRelease-1>", x=x + dx, y=y + dy, rootx=rx + dx, rooty=ry + dy)

    def moves(made):
        """The header and the column's top move the window; the steps under them and the window's buttons do not."""
        if not hasattr(made.window, "header"):
            problems.append("setup-%s: the window has no header of its own (%s)" % (tag, "moves"))
            return
        root, window = made.root, made.window
        settle(root, 0.3)
        start = (root.winfo_rootx(), root.winfo_rooty())
        header = window.header
        press_at(header, header.winfo_width() // 2, header.tall - 4, 40, 30)
        settle(root, 0.5)
        if (root.winfo_rootx(), root.winfo_rooty()) != (start[0] + 40, start[1] + 30):
            problems.append("setup-%s: a drag on the header moved the window from %r to %r, not by (40, 30)" % (
                tag, start, (root.winfo_rootx(), root.winfo_rooty())))
        # Back by the wordmark at the column's top.
        press_at(window.mark, 10, 10, -40, -30)
        settle(root, 0.5)
        if (root.winfo_rootx(), root.winfo_rooty()) != start:
            problems.append("setup-%s: a drag on the wordmark did not move the window back (%r, not %r)" % (
                tag, (root.winfo_rootx(), root.winfo_rooty()), start))
        # The steps, under the header's reach, and a press on the window's own buttons move nothing.
        with mock.patch.object(root, "iconify"):
            for widget in (window.steps, window.header.buttons[0]):
                press_at(widget, 12, 12, 40, 30)
                settle(root, 0.5)
                if (root.winfo_rootx(), root.winfo_rooty()) != start:
                    problems.append("setup-%s: a drag on %s moved the window" % (tag, type(widget).__name__))
                    root.geometry("+%d+%d" % start)
                    settle(root, 0.5)

    def window_keys(made):
        """Tab reaches minimise, then close, after the strip's buttons, each with its ring; Enter and a click on
        minimise minimise; the close button's answer is the window's own, what Alt+F4 and the taskbar's Close ask."""
        if not hasattr(made.window, "header"):
            problems.append("setup-%s: the window has no header of its own (%s)" % (tag, "window_keys"))
            return
        from opendmtq_client import theme
        root, window = made.root, made.window
        buttons = window.header.buttons
        settle(root, 0.3)
        widget, order = window.buttons[-1], []
        for _ in range(3):
            widget = widget.tk_focusNext()
            order.append(widget)
        if order[:2] != buttons:
            problems.append("setup-%s: Tab goes %r after the strip's buttons" % (
                tag, [getattr(w, "words", type(w).__name__) for w in order]))
        for button in buttons:
            button.focus_set()
            settle(root, 0.3)
            ring = [p for p in button.odq_picture.getdata() if near(p, theme.CYAN, 30)]
            if not button.focused or len(ring) < 20:
                problems.append("setup-%s: the %s button shows no ring with the keyboard" % (tag, button.glyph))
        with mock.patch.object(root, "iconify") as iconify:
            buttons[0].focus_set()
            settle(root, 0.2)
            buttons[0].event_generate("<Return>")
            settle(root, 0.3)
            press_at(buttons[0], 16, 16)
            settle(root, 0.3)
        if iconify.call_count != 2:
            problems.append("setup-%s: Enter and a click on minimise minimised %d times, not twice" % (
                tag, iconify.call_count))
        if buttons[1].command != made._close or window.on_close != made._close:
            problems.append("setup-%s: the close button does not do what closing the window does" % tag)
        if [b.words for b in buttons] != [made.words("setup.window.minimize"), made.words("setup.window.close")]:
            problems.append("setup-%s: the buttons are named %r" % (tag, [b.words for b in buttons]))

    def close_under_pointer(made):
        """The pointer over the close button, the keyboard on the page: the button red, for the picture."""
        if not hasattr(made.window, "header"):
            problems.append("setup-%s: the window has no header of its own (%s)" % (tag, "close_under_pointer"))
            return
        made.window.buttons[-1].focus_set()
        button = made.window.header.buttons[1]
        button.event_generate("<Enter>", x=16, y=16)

    run("header", installer.Installer, [moves, window_keys, close_under_pointer])

    def ring_on_minimise(made):
        if hasattr(made.window, "header"):
            made.window.header.buttons[0].focus_set()

    run("header-keys", installer.Installer, [ring_on_minimise])

    # The close button on a page with nothing under way closes the window, as the title bar's X did.
    made = installer.Installer()
    settle(made.root, 1.0)
    # Its timers first, as run() does before it closes a window: Tcl's one event loop would call them from the next one.
    for job in made.root.tk.splitlist(made.root.tk.call("after", "info")):
        made.root.after_cancel(job)
    if hasattr(made.window, "header"):
        made.window.header.buttons[1].focus_set()
        settle(made.root, 0.2)
        made.window.header.buttons[1].event_generate("<space>")
    try:
        alive = bool(made.root.winfo_exists())
    except tk.TclError:
        # Tk itself gone with its window: closed, as it should be.
        alive = False
    if alive:
        problems.append("setup-%s: Space on the close button left the window open" % tag)
        made.root.destroy()
    # The notices follow the PC each time: a launcher opened while the page shows says so, closed again it goes; the
    # game too.
    notice = {"launcher": False, "game": False}

    def said(made):
        return [w.cget("text") for w in widgets_of(made.root) if w.winfo_class() == "Label" and w.winfo_ismapped()]

    def flip(made, what, on, expect):
        notice[what] = on
        settle(made.root, 1.6)
        words = made.words("setup.closing" if what == "launcher" else "setup.notice.game")
        if notice["launcher"] and notice["game"] and expect:
            # Both open (the launcher's line wanted): their one line, which keeps the page within its window (a launcher
            # without such a line said them in two, and this check finds its one line missing).
            from opendmtq_client import i18n
            words = made.words("setup.notice.both") if "setup.notice.both" in i18n.TEXT else None
        if (words in said(made)) != expect:
            problems.append("setup-%s: the notice that the %s is open %s after it %s" % (
                tag, what, "did not show" if expect else "stayed", "opened" if on else "closed"))

    def choose(made, value):
        """A choice made on the page, as the arrow keys or a click make it."""
        from opendmtq_client import setup_window
        options = next(x for x in widgets_of(made.root) if isinstance(x, setup_window.Options))
        options.choose(value)

    with mock.patch.object(installer, "launcher_open", lambda: notice["launcher"]), \
            mock.patch.object(installer, "game_running", lambda: notice["game"]):
        # Opening OpenDMTQ closes nothing: the launcher's line is not there while it is chosen, open or not (main said
        # "The launcher is open: it closes first." then too); Repair closes it, and the line comes and goes with it.
        run("choose-notices", installer.Installer,
            [lambda made: flip(made, "launcher", True, False), lambda made: choose(made, "repair"),
             lambda made: flip(made, "launcher", True, True), lambda made: flip(made, "launcher", False, False),
             lambda made: flip(made, "launcher", True, True), lambda made: flip(made, "game", True, True)])
        notice.update(launcher=False, game=False)
        # Waiting for the game: once it closes, the work goes on by itself.
        started = []
        notice["game"] = True
        with mock.patch.object(installer, "run_setup", lambda path: (started.append(path), Process(60, 0))[1]):
            run("game-waits", installer.Installer, [lambda made: made.work("repair"),
                                                    lambda made: (notice.update(game=False), settle(made.root, 1.6))])
        if not started:
            problems.append("setup-%s: the repair did not go on once the game closed" % tag)
    program("0.0.1")
    run("choose-update", installer.Installer)
    program("99.0.0")
    run("choose-older", installer.Installer)
    program(__version__)
    # Repair's end.
    with mock.patch.object(installer, "run_setup", lambda path: Process(0.3, 0)):
        run("repaired", installer.Installer, [lambda made: made.work("repair"), lambda made: settle(made.root, 2.0)])
    # A failure, with its log.
    def setup_fails(path):
        """Velopack's setup ending with an error line in its log, as a full disk ends it."""
        with open(path, "w", encoding="utf-8") as f:
            f.write("[setup:448] [11:47:52] [ERROR] There is not enough space on the disk.\n")
        return Process(0.2, 1)

    with mock.patch.object(installer, "run_setup", setup_fails):
        run("failed", installer.Installer, [lambda made: made.work("repair"), lambda made: settle(made.root, 1.5)])
    # The game open: the work waits for it, the column at the work's own step and the words its own (main showed
    # CHOOSE and OPEN, the first choice's, and "Installing replaces the game program" for a repair).
    def waits_for_the_game(made, action, steps):
        made.work(action)
        settle(made.root, 0.6)
        shown = [w.cget("text") for w in widgets_of(made.root) if w.winfo_class() == "Label" and w.winfo_ismapped()]
        if made.flow != (steps, 1) or made.words("setup.game." + action) not in shown:
            problems.append("setup-%s: %s waiting for the game shows %r, saying %r" % (tag, action, made.flow, shown))

    with mock.patch.object(installer, "game_running", return_value=True):
        run("game-open", installer.Installer,
            [lambda made: waits_for_the_game(made, "repair", ("choose", "repair", "done"))])
        program("0.0.1")
        run("game-open-update", installer.Installer,
            [lambda made: waits_for_the_game(made, "update", ("choose", "update", "done"))])
        program(__version__)
    # ---- Uninstall: the choice with the sizes, the work, both ends.
    data()

    def to_uninstall(made):
        made.uninstall_page()

    def red_main_button(made):
        """The uninstall's main button, Uninstall, filled red as a dialog's Delete all (main drew it in the quiet
        red-tinted metal, which read as off beside the quiet Cancel: a page with no main button)."""
        last = made.window.buttons[-1]
        # The look a dialog's Delete all has (art.BUTTON_LOOKS["danger"]), the quiet one being danger_quiet.
        if last.words != made.words("setup.do.uninstall") or last.look != "danger":
            problems.append("setup-%s: the uninstall page's %r is drawn %s, not filled red" % (tag, last.words, last.look))

    run("uninstall", installer.Installer, [to_uninstall, lambda made: settle(made.root, 1.5), red_main_button])

    def uninstaller(seconds):
        def started(root_folder):
            def empty():
                # Velopack's uninstaller as it goes: the program's folder emptied, then gone.
                shutil.rmtree(os.path.join(folder, "current"), ignore_errors=True)
            return Process(seconds, 0, during=empty)
        return started

    for choice, name in (("keep", "uninstalled-keep"), ("all", "uninstalled-all")):
        program(__version__)
        data()
        with mock.patch.object(removal, "start_uninstaller", uninstaller(0.4)):
            run(name, installer.Installer, [to_uninstall, lambda made: settle(made.root, 1.5),
                                            lambda made, c=choice: made.uninstall(c),
                                            lambda made: settle(made.root, 3.0)])
    program(__version__)
    data()
    with mock.patch.object(removal, "start_uninstaller", uninstaller(30)):
        run("uninstalling", installer.Installer, [to_uninstall, lambda made: settle(made.root, 1.5),
                                                  lambda made: made.uninstall("all"),
                                                  lambda made: settle(made.root, 0.8)])
    # Windows' Settings, Apps: the uninstall alone.
    program(__version__)
    run("apps-uninstall", lambda: installer.Installer(start="uninstall", folder=folder),
        [lambda made: settle(made.root, 1.5), red_main_button])

    # ---- The page switches filmed as the launcher's menu is (WIN-244, flicker.film_switch): the page before stays
    # whole on the screen while the next one is made, and leaves it whole before its widgets go (main took its widgets
    # away one by one on the screen, the page's flat frame showing where each had been, as the launcher's pages did).
    setup = {"fails": False}

    def setup_stand_in(path):
        """Velopack's setup for the switches: one that cannot start (its file missing), or one that runs a minute."""
        if setup["fails"]:
            raise OSError(2, "No such file or directory", "Setup.exe")
        return Process(60, 0)

    def switches(steps):
        """A window as the installer opens it, each (name, act(made)) of `steps` filmed as a switch of its page, then
        the window closed (its timers first, as run() does). The page before's buttons are gone once the switch's own
        work is done: a second click waiting in Tk's queue, which Tk takes before its idle work, reaches nothing (a
        double click on Install started Velopack's setup once)."""
        made = installer.Installer()
        settle(made.root, 1.0)
        for name, act in steps:
            before, left = list(made.window.buttons), []

            def switch(act=act, before=before, left=left):
                act(made)
                # The switch's own turn over: what of the page before's buttons is still there.
                left.extend(button.words for button in before if button.winfo_exists())

            filmed = flicker.film_switch(made.root, made.window.page_area, switch)
            problems.extend(flicker.switch_problems("setup-%s: the page switch %s" % (tag, name), filmed))
            if left:
                problems.append("setup-%s: the page switch %s: the page before's buttons still there after its work "
                                "(%s)" % (tag, name, ", ".join(left)))
        for job in made.root.tk.splitlist(made.root.tk.call("after", "info")):
            made.root.after_cancel(job)
        try:
            made.root.destroy()
        except tk.TclError:
            # A timer's command, cancelled through the window above, is deleted again by the widget that made it (the
            # bar's easing): the window is gone all the same, as run() finds.
            pass

    with mock.patch.object(installer, "run_setup", setup_stand_in):
        # On a PC with OpenDMTQ: to the uninstall's page and back, a repair whose setup cannot start (its progress,
        # then what went wrong, in one turn), Try again, then a repair under way.
        switches([("choose to uninstall", lambda made: made.uninstall_page()),
                  ("uninstall to choose", lambda made: made.ask()),
                  ("choose to failed", lambda made: (setup.update(fails=True), made.work("repair"))),
                  ("failed to choose", lambda made: (setup.update(fails=False), made._again())),
                  ("choose to repairing", lambda made: made.work("repair"))])
        # On a PC without it: Install.
        shutil.rmtree(folder, ignore_errors=True)
        switches([("install to installing", lambda made: made.work("install"))])
    for patch in patches:
        patch.stop()
    stopped_window(args, tag, problems)
    report = os.path.join(args.out, "setup-problems-%s.txt" % tag)
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(problems) + ("\n" if problems else ""))
    print("setup %s: %d problems" % (tag, len(problems)))
    for problem in problems:
        print("  " + problem)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
