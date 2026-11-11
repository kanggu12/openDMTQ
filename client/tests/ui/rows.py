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
    import tkinter as tk
    site, state = keyboard.setup(args.lang)
    from opendmtq_client.app import LauncherApp
    problems = []
    app = LauncherApp(state)
    app.root.geometry("%s+0+0" % args.size)
    shots.settle(app)
    w = app.words

    # ---- Online signed out: the address with Connect and Forget, the ID and the password with Sign in.
    app.state.forget_sign_in()
    app.nav_go("online")
    shots.settle(app)
    rows = [items for items in rows_of(app.body).values() if any(isinstance(x, widgets.Field) for x in items)]
    if len(rows) != 2:
        problems.append("Online: %d rows with a field, not the address's and the sign-in's" % len(rows))
    for items in rows:
        tops = [x.winfo_rooty() for x in items]
        heights = [x.winfo_height() for x in items]
        middles = [top + height / 2.0 for top, height in zip(tops, heights)]
        if max(heights) - min(heights) > 1 or max(middles) - min(middles) > 1:
            problems.append("Online: a row's controls are %r tall with middles at %r" % (heights, middles))
    # Each field starts where the words over it start (its label, in the grid cell above it).
    for field in [x for items in rows for x in items if isinstance(x, widgets.Field)]:
        info = field.grid_info()
        above = [x for x in field.master.grid_slaves(row=int(info["row"]) - 1, column=int(info["column"]))
                 if isinstance(x, tk.Label)]
        if not above:
            problems.append("Online: a field with no words over it")
            continue
        # Where the label's words begin: past its own edge (border, padding, ring), as Tk draws them.
        words = above[0]
        start = words.winfo_rootx() + sum(int(words.winfo_fpixels(str(words.cget(o))))
                                          for o in ("borderwidth", "padx", "highlightthickness"))
        if abs(field.winfo_rootx() - start) > 1:
            problems.append("Online: a field starts at %d, its words %r at %d" % (field.winfo_rootx(),
                                                                                 words.cget("text"), start))

    # ---- The settings' controls of the Screen page (below 100 %, with every row) and of the Sound page: what shows of
    # each starts on one line (a switch's and a row of tabs' rooms for the keyboard's ring left out).
    # Below 100 % for every row; VSync off, as a switch that is on has a faint halo of the accent round its pill, which
    # reaches past where the pill starts.
    app.changed("render_scale", "75")
    app.changed("vsync", "off")
    for page in ("screen", "sound"):
        app.nav_go(page)
        shots.settle(app, 6, until=lambda: app.devices is not None)
        shots.settle(app)
        # The page as a person sees it: each control's first column of pixels that is not the card's own colour, on
        # the line through its middle (the keyboard's ring is the card's colour while it is away).
        from PIL import Image
        from opendmtq_client import art, theme
        card = art._rgb(theme.PANEL)
        edges = []
        for widget in shots.widgets_of(app.body.inner):
            control = getattr(widget, "control", None)
            if control is None or not control.winfo_ismapped():
                continue
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
            edges.append((seen, control.winfo_class()))
        found = [e[0] for e in edges if e[0] is not None]
        if len(found) < 3 or len(found) != len(edges) or max(found) - min(found) > 1:
            problems.append("%s: the controls show from %r" % (page, sorted(set(edges))))
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
