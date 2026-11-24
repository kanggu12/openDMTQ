"""The launcher's rows on the test container's virtual screen: a field and the buttons beside it share one height and
one middle, a field starts where the words above it start, and the controls of a page's settings show from one line.

Run inside the opendmtq-client-ui container only (client/tests/ui/run.sh); it refuses anywhere else, because it opens
windows. The server is the tests' stand-in site (tests/stub.py) on this machine's loopback, the player a stand-in.

  python tests/ui/rows.py --lang en|ko [--size 1180x760]      (from client/)
Exit status 1 when a check fails; each failure is printed.
"""

import argparse
import importlib.util
import os
import sys

# Run from client/ (the container mounts the repository and works there).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from opendmtq_client import safety, widgets  # noqa: E402

# The keyboard checks' set-up (a launcher folder signed in on the stand-in server), from the file beside this one.
_spec = importlib.util.spec_from_file_location("keyboard", os.path.join(os.path.dirname(__file__), "keyboard.py"))
keyboard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(keyboard)
shots = keyboard.shots


def rows_of(area):
    """Each frame of the page that holds a field or a button directly, with those it holds: one row of controls."""
    rows = {}
    for widget in shots.widgets_of(area.inner):
        if isinstance(widget, (widgets.Field, widgets.Button)) and widget.winfo_ismapped():
            rows.setdefault(widget.master, []).append(widget)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="en")
    parser.add_argument("--size", default="1180x760")
    parser.add_argument("--out", default="/tmp/odq-rows")
    args = parser.parse_args()
    out = args.out
    os.makedirs(out, exist_ok=True)
    if not safety.on_virtual_display():
        sys.exit("refusing: this opens windows; run it through client/tests/ui/run.sh")
    import tempfile
    import tkinter as tk
    site, state = keyboard.setup(args.lang)
    # Help as an installed launcher has it: Repair and Uninstall among its rows.
    os.environ["OPENDMTQ_INSTALL_ROOT"] = shots.fake_install(tempfile.mkdtemp())
    from opendmtq_client.app import LauncherApp
    problems = []
    app = LauncherApp(state)
    app.root.geometry("%s+0+0" % args.size)
    shots.settle(app)
    w = app.words

    # ---- Online signed out: the address with Connect beside it; the ID and the password, each under its name, Sign in
    # under them.
    app.state.forget_sign_in()
    app.nav_go("online")
    shots.settle(app)
    rows = [items for items in rows_of(app.body).values() if any(isinstance(x, widgets.Field) for x in items)
            and any(isinstance(x, widgets.Button) for x in items)]
    if len(rows) != 1:
        problems.append("Online: %d rows with a field and a button, not the address's with Connect" % len(rows))
    for items in rows:
        tops = [x.winfo_rooty() for x in items]
        heights = [x.winfo_height() for x in items]
        middles = [top + height / 2.0 for top, height in zip(tops, heights)]
        if max(heights) - min(heights) > 1 or max(middles) - min(middles) > 1:
            problems.append("Online: a row's controls are %r tall with middles at %r" % (heights, middles))
    # Each field in its row of the server card, its name in the names column beside it (DESIGN.md's form rows): every
    # field starts on one line, the control column's, and stands on its name's middle.
    fields = [x for x in shots.widgets_of(app.body.inner) if isinstance(x, widgets.Field) and x.winfo_ismapped()]
    if len(fields) != 3:
        problems.append("Online: %d fields, not the address, the ID and the password" % len(fields))
    starts = sorted({field.winfo_rootx() for field in fields})
    if starts and starts[-1] - starts[0] > 1:
        problems.append("Online: the fields start at %r, not on one line" % starts)
    for field in fields:
        row = field
        while row is not None and not hasattr(row, "odq_names"):
            row = row.master
        names = [x for x in (row.grid_slaves(row=0, column=0) if row is not None else ())
                 if isinstance(x, tk.Label) and x.cget("text")]
        if not names:
            problems.append("Online: a field with no name beside it")
            continue
        name = names[0]
        middle = name.winfo_rooty() + name.winfo_height() / 2.0
        if abs(middle - (field.winfo_rooty() + field.winfo_height() / 2.0)) > 1:
            problems.append("Online: the field of %r stands off its name's middle (%.1f, %.1f)" % (
                name.cget("text"), field.winfo_rooty() + field.winfo_height() / 2.0, middle))

    # ---- The settings' controls of the Screen page (below 100 %, with every row), of the Sound page and of Help's
    # tools: what shows of each starts on one line (a row name longer than the names' column would push its control
    # out of it).
    # Below 100 % for every row; VSync off, as it was measured when a switch that was on had a faint ring of the accent
    # round its pill (the measure starts at the pill either way).
    app.changed("render_scale", "75")
    app.changed("vsync", "off")

    def controls_from_one_line(page, said):
        app.nav_go(page)
        shots.settle(app, 6, until=lambda: app.devices is not None)
        shots.settle(app)
        # The page as a person sees it: each control's first column of pixels that is not the card's own colour, on
        # the line through its middle (the keyboard's ring is the card's colour while it is away). Measured card by card:
        # the page's names column is one, so each card's controls start on one line (two cards side by side have two).
        from PIL import Image
        from opendmtq_client import art, theme
        card = art._rgb(theme.PANEL)
        edges = {}
        for widget in shots.widgets_of(app.body.inner):
            control = getattr(widget, "control", None)
            if control is None or not control.winfo_ismapped():
                continue
            holder = widget
            while holder is not None and not isinstance(holder, widgets.Card):
                holder = holder.master
            # In view first (a page taller than the window), then seen as it is now.
            app.body.show_widget(control)
            app.root.update()
            picture = Image.open(shots.shot(app.root, out, "rows-%s-%s" % (args.lang, page))).convert("RGB")
            x0 = control.winfo_rootx() - app.root.winfo_rootx()
            y0 = control.winfo_rooty() - app.root.winfo_rooty()
            # The leftmost pixel of the control that is not the card's colour, over its whole height: a row of tabs
            # shows first at the foot of its first (slanted) tab, on the rule it stands on.
            seen = None
            for y in range(y0, y0 + control.winfo_height()):
                x = next((x for x in range(x0, x0 + control.winfo_width())
                          if sum(abs(a - b) for a, b in zip(picture.getpixel((x, y)), card)) > 24), None)
                if x is not None and (seen is None or x < seen):
                    seen = x
            edges.setdefault(str(holder), []).append((seen, control.winfo_class()))
        counted = sum(len(found) for found in edges.values())
        if counted < 2:
            problems.append("%s%s: %d controls of settings rows found" % (page, said, counted))
        for found_in in edges.values():
            found = [e[0] for e in found_in if e[0] is not None]
            if len(found) != len(found_in) or (found and max(found) - min(found) > 1):
                problems.append("%s%s: the controls show from %r" % (page, said, sorted(set(found_in))))

    for page in ("screen", "sound", "help", "about", "online"):
        controls_from_one_line(page, "")
    # The Sound page's sliders' numbers end on one line in each card's column: the volumes', and each band's in its own
    # column of the equaliser (once 18 px apart).
    app.nav_go("sound")
    shots.settle(app, 6, until=lambda: app.devices is not None)
    ends = {}
    for x in shots.widgets_of(app.body.inner):
        if isinstance(x, widgets.Slider) and x.winfo_ismapped():
            ends.setdefault((str(x.master.master), x.winfo_rootx()), set()).add(
                x.number.winfo_rootx() + x.number.winfo_width())
    for where, found in ends.items():
        if len(found) != 1:
            problems.append("sound: the sliders' numbers end at %r" % sorted(found))
    # The same with the names drawn wider, as Windows draws Pretendard (its Help's Servers and settings is 135 px where
    # Linux makes it about 128): a column fitted to the names still lines the controls up, where a width fixed for one
    # system's font let the widest name push its control out of the line (Start over 3 px right of the others).
    bold = app.fonts.body_bold
    size = int(bold.cget("size"))
    bold.configure(size=size + 1)
    try:
        for page in ("screen", "sound", "help", "about", "online"):
            controls_from_one_line(page, " with wider names")
    finally:
        bold.configure(size=size)

    # ---- State rows (widgets.check_line: PLAY's ready check and its server card's sign-in): the words' first line and
    # the value or the way to fix it at the right end stand on one line, with its middle on the lamp's (once a value
    # stood 2 px above its words, 5 px at 200 %).
    def edge(widget):
        # What a label keeps above its words: its border, its padding and its keyboard ring.
        return sum(int(widget.winfo_fpixels(str(widget.cget(o)))) for o in ("borderwidth", "pady", "highlightthickness"))

    def state_rows_on_one_line(page):
        app.nav_go(page)
        shots.settle(app)
        found = 0
        for frame in shots.widgets_of(app.body.inner):
            # Packed or gridded (a row with a names column grids its lamp, words and value).
            slaves = [x for x in frame.pack_slaves() + frame.grid_slaves() if x.winfo_ismapped()] \
                if isinstance(frame, tk.Frame) else []
            lamps = [x for x in slaves if hasattr(x, "odq_picture") and isinstance(x, tk.Label)]
            texts = [x for x in slaves if isinstance(x, tk.Label) and x not in lamps and x.cget("text")]
            if len(lamps) != 1 or not texts:
                continue
            found += 1
            light = lamps[0]
            middle = light.winfo_rooty() + light.winfo_height() / 2.0
            for text in texts:
                line = app.root.tk.call("font", "metrics", text.cget("font"), "-linespace")
                at = text.winfo_rooty() + edge(text) + int(line) / 2.0
                if abs(at - middle) > 1:
                    problems.append("%s: the state row's %r has its line's middle at %.1f, the lamp's at %.1f"
                                    % (page, text.cget("text")[:30], at, middle))
        if not found:
            problems.append("%s: no state rows found" % page)

    state_rows_on_one_line("play")
    # Help's checks: their values in their column after the names, on the lamp's line too.
    state_rows_on_one_line("help")

    # ---- What a state row says stands by the words it belongs to (DESIGN.md's state rows): the values of a list's rows
    # start on one line, the column after their names; a row alone has its value right after its words, a value's gap
    # (16) from them, never at the card's far end (the Sound page's last game said "3 gaps" there). A row that leads to
    # a page or a tool says first what is wrong (main: the sign-in and the app showed a lamp and "ONLINE ›" alone).
    def state_rows(page):
        """Each state row on the page (a frame with one lamp and words, made by widgets.check_line), as (row, lamp, its
        labels left to right: the words, the value, the link)."""
        found = []
        for frame in shots.widgets_of(app.body.inner):
            if not isinstance(frame, tk.Frame):
                continue
            slaves = [x for x in frame.pack_slaves() + frame.grid_slaves() if x.winfo_ismapped()]
            lamps = [x for x in slaves if hasattr(x, "odq_picture") and isinstance(x, tk.Label)]
            texts = sorted((x for x in slaves if isinstance(x, tk.Label) and x not in lamps and x.cget("text")),
                           key=lambda x: x.winfo_rootx())
            if len(lamps) == 1 and texts:
                found.append((frame, lamps[0], texts))
        return found

    def values_by_their_names(page, said):
        rows = [r for r in state_rows(page) if len(r[2]) > 1]
        if not rows:
            problems.append("%s%s: no state rows with a value" % (page, said))
        lists = {}
        for frame, _lamp, texts in rows:
            lists.setdefault(str(frame.master), []).append(texts)
        for texts_of in lists.values():
            if len(texts_of) > 1:
                # A list: its values (or links) from one line.
                starts = sorted({texts[1].winfo_rootx() for texts in texts_of})
                if starts[-1] - starts[0] > 1:
                    problems.append("%s%s: a list's values start at %r, not on one line" % (page, said, starts))
                continue
            words, value = texts_of[0][0], texts_of[0][1]
            gap = value.winfo_rootx() - (words.winfo_rootx() + words.winfo_width())
            if abs(gap - app.ui.px(16)) > 1:
                problems.append("%s%s: the value %r stands %d px after its words %r, not 16" % (
                    page, said, value.cget("text")[:20], gap, words.cget("text")[:30]))
        for frame, _lamp, texts in state_rows(page):
            links = [x for x in texts if str(x.cget("cursor")) == "hand2"]
            if links and len(texts) < 3:
                problems.append("%s%s: the state row %r leads to %r and says nothing of what is wrong" % (
                    page, said, texts[0].cget("text")[:30], links[0].cget("text")))

    # The Sound page's last game's sound, as the player leaves it at a game's end.
    from opendmtq_client import apps, player
    from tests.base import SOUND_RESULT
    with open(player.result_path(), "w", encoding="utf-8") as f:
        f.write(SOUND_RESULT.replace("gaps=0\ngame_gaps=0", "gaps=1\ngame_gaps=2"))
    app.nav_go("sound")
    shots.settle(app, 6, until=lambda: app.devices is not None)
    shots.settle(app)
    values_by_their_names("sound", "")
    # In view for its picture, as a person scrolls to it.
    found = [r for r in state_rows("sound") if len(r[2]) > 1]
    if found:
        app.body.show_widget(found[0][0])
        shots.settle(app, 0.5)
    shots.shot(app.root, out, "rows-%s-sound-last-gaps" % args.lang)
    # PLAY and Help with the sign-in gone and no app on this PC: the rows that are not fine, each saying what is wrong
    # before its link (a red row for the app, which PLAY cannot get without a sign-in).
    app.state.forget_sign_in()
    apps.remove(app.state.current)
    app.state.save()
    app.refresh_checks(force=True)
    for page in ("play", "help"):
        app.nav_go(page)
        shots.settle(app)
        values_by_their_names(page, " with no sign-in and no app")
        shots.shot(app.root, out, "rows-%s-%s-not-ready" % (args.lang, page))

    # ---- A choice that brings or takes a row (Mode a window's size, the FPS counter its corner, keyboard play the
    # lanes) keeps its own row as tall whichever is chosen: its hint keeps the room of the longer of its words
    # (widgets.keep_room). Mode's hint in Korean was two lines for full screen and one for a window: the window's size
    # came laid out under the row's old height, then the card, the card beside it and the one under them were laid out
    # again a moment later for its new one (three frames between on the flicker film, where two are allowed).
    def row_keeps_height(page, kind, key, choose, choices):
        app.nav_go(page)
        shots.settle(app)
        control = keyboard.setting_control(app.body, kind, w(key))
        if control is None:
            problems.append("%s: no %r row" % (page, w(key)))
            return
        # The setting's row: the frame that holds the control and its name.
        row = control.master
        heights = {}
        for choice in choices:
            choose(control, choice)
            shots.settle(app)
            heights[choice] = row.winfo_height()
        if len(set(heights.values())) != 1:
            problems.append("%s: the %r row is %s px tall by its choice" % (page, w(key), heights))
        # Back to the first choice, as the page was.
        choose(control, choices[0])
        shots.settle(app)

    def segmented(control, value):
        control.set(value, notify=True)

    def toggle(control, value):
        control.set(value, notify=True)

    row_keeps_height("screen", widgets.Segmented, "screen.mode", segmented, ("fullscreen", "window"))
    row_keeps_height("screen", widgets.Toggle, "screen.counter", toggle, (False, True))
    row_keeps_height("controls", widgets.Toggle, "controls.keys.play", toggle, (True, False))
    for job in app.root.tk.splitlist(app.root.tk.call("after", "info")):
        app.root.after_cancel(job)
    app.root.destroy()
    site.stop()
    print("rows %s %s: %d problems" % (args.lang, args.size, len(problems)))
    for problem in problems:
        print("  " + problem)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
