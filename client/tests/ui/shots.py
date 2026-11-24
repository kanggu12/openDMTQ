"""Open the launcher on the test container's virtual screen, go through the first-start guide and every page, save a
screenshot of each, and measure the layout: text cut off, controls past the window's edge, labels never wrapped.

Run inside the opendmtq-client-ui container only (client/tests/ui/run.sh); it refuses anywhere else, because it opens
windows. The server is the tests' stand-in site (tests/stub.py) on this machine's loopback, the player a stand-in
script: no game file is used.

  python tests/ui/shots.py --out DIR [--lang en|ko] [--size 1180x760]      (from client/)
Exit status 1 when the layout check finds a problem; the problems are printed and written to DIR/problems-<tag>.txt.
"""

import argparse
import logging
import os
import re
import subprocess
import sys
import tempfile
import time

# Run from client/ (the container mounts the repository and works there).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from opendmtq_client import safety, widgets  # noqa: E402
from tests import stub  # noqa: E402
from tests.base import FAKE_PLAYER  # noqa: E402

# The boxes' room, from the file beside this one.
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("spacing", os.path.join(os.path.dirname(__file__), "spacing.py"))
spacing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spacing)
# The page's design (tests/ui/design.py): its cards' composition, its words' roles, its buttons, its picture round the
# cards.
_spec = importlib.util.spec_from_file_location("design", os.path.join(os.path.dirname(__file__), "design.py"))
design = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(design)

# What the launcher logs in this run, line by line (its file handler is set up by main(), which the run skips).
LOGGED = []


class Kept(logging.Handler):
    def emit(self, record):
        LOGGED.append(record.getMessage())


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
        if cls == "Entry" and str(w.cget("selectbackground")) != widgets.SELECTION["selectbackground"]:
            # Selected words in a field in the launcher's colours, never the system's blue.
            problems.append("%s: a field selects in %s" % (name, w.cget("selectbackground")))
    if root is app.root:
        lime_check(app, name, problems)
        # The boxes and the room round them (tests/ui/spacing.py): nothing touching, words inside their padding, the
        # gaps on the launcher's scale.
        problems.extend(spacing.check(root, app.ui, name))
        # The page's own picture between and round the cards, never a slab of the field's flat colour over it.
        field_check(app, name, problems, root)
        # The design (tests/ui/design.py): no plain list of boxes nor a box for one control, the words in their roles,
        # the buttons by theirs, no shard of the picture at the column or a card.
        problems.extend(design.check(root, app.ui, name))


# Of the page's field (between and round the cards, under the page's title), how much may differ from the picture the
# page drew behind it: none, but for a stray pixel where a box's edge meets it (a share of the field's pixels).
FIELD_DIFFERS = 0.0005
# How far a pixel may be from the picture's and still be its pixel (levels of 255): none on a 24-bit screen.
FIELD_LEVELS = 2
# Where a screen whose field differs is saved with the differing pixels in magenta (main() sets it to --out).
FIELD_OUT = None


def field_check(app, name, problems, root):
    """The page's field shows the window's own background, as the page drew it (widgets.ScrollArea's picture: the
    field, its lit top, the shards at its edges, the dots): on the screen, every pixel of the page area that is no
    card, no part of the page's title, and not the scroll bar must be the picture's pixel there, wherever the page is
    scrolled to. A frame of the field in a flat colour over the picture (the black slab under the cards that 0.11.0
    had) fails it, as does a card's cut corner showing a colour where the picture is."""
    from PIL import Image, ImageChops, ImageGrab
    for area in [w for w in widgets_of(root) if isinstance(w, widgets.ScrollArea)]:
        if not area.winfo_viewable():
            continue
        # The picture is drawn a moment after the page settles (ScrollArea._relayout): waited for.
        end = time.time() + 3
        while getattr(area, "_backdrop_job", None) is not None and time.time() < end:
            root.update()
            time.sleep(0.02)
        root.update()
        behind = getattr(area, "_backdrop_picture", None)
        if behind is None:
            problems.append("%s: the page area drew no picture behind its page" % name)
            continue
        c = area.canvas
        x0, y0, width, height = c.winfo_rootx(), c.winfo_rooty(), c.winfo_width(), c.winfo_height()
        top = int(c.canvasy(0))
        shot = ImageGrab.grab(bbox=(x0, y0, x0 + width, y0 + height), xdisplay=os.environ.get("DISPLAY")).convert("RGB")
        wanted = Image.new("RGB", (width, height), (0, 0, 0))
        wanted.paste(behind.crop((0, top, min(behind.width, width), min(behind.height, top + height))), (0, 0))
        # The field: from under the page's title down (the title and the line under it are drawn over the picture).
        mask = Image.new("L", (width, height), 0)
        mask.paste(255, (0, max(0, int(area._content_top) - top), width, height))
        # Less every card (its own face and edge; its cut corner is measured with the field, below), the scroll bar,
        # and whatever else stands on the field that is not one of the field's own frames or their pictures.
        cut_corners = []
        for w in widgets_of(area.inner):
            if w is area.inner or not w.winfo_ismapped():
                continue
            if getattr(w, "odq_field", False) or (w.winfo_class() == "Frame" and not isinstance(w, widgets.Card)
                                                  and _field_frame(w, area)):
                continue
            if any(isinstance(a, widgets.Card) for a in _ancestors_of(w, area.inner)):
                # Inside a card: the card's box covers it.
                continue
            box = (w.winfo_rootx() - x0, w.winfo_rooty() - y0, w.winfo_rootx() - x0 + w.winfo_width(),
                   w.winfo_rooty() - y0 + w.winfo_height())
            mask.paste(0, box)
            if isinstance(w, widgets.Card) and getattr(w, "cut", 0):
                cut_corners.append((box, w.cut, getattr(w, "edge", 1)))
        if area.bar.winfo_ismapped():
            mask.paste(0, (area.bar.winfo_rootx() - x0, 0, width, height))
        # Each card's corner past its cut, clear of the cut's own line and its smoothing: the picture beyond, without the
        # field's faint dots (art.without_dots: a card that moves over the plain field keeps the same corner).
        from PIL import ImageDraw
        from opendmtq_client import art
        draw = ImageDraw.Draw(mask)
        for box, cut, edge in cut_corners:
            square = (box[2] - cut, box[1], box[2], box[1] + cut)
            if not (square[0] >= 0 and square[1] >= 0 and square[2] <= width and square[3] <= height):
                # A corner the page's scroll cuts: measured where it shows whole.
                continue
            wanted.paste(art.without_dots(wanted.crop(square), app.ui.scale), square[:2])
            right, top_y = box[2], box[1]
            draw.polygon([(right - cut + 2 + edge, top_y), (right - 1, top_y), (right - 1, top_y + cut - 3 - edge)],
                         fill=255)
        # Counted from the masks' histograms (each pixel 0 or 255): a page at 200 % has millions of them.
        counted = mask.histogram()[255]
        if not counted:
            continue
        # A pixel differs when any of its three colours is more than FIELD_LEVELS from the picture's.
        diff = ImageChops.difference(shot, wanted)
        diff = ImageChops.lighter(ImageChops.lighter(diff.getchannel(0), diff.getchannel(1)), diff.getchannel(2))
        off = ImageChops.multiply(diff.point(lambda v: 255 if v > FIELD_LEVELS else 0), mask)
        differing = off.histogram()[255]
        if differing > counted * FIELD_DIFFERS:
            where = off.getbbox()
            if FIELD_OUT:
                marked = shot.copy()
                marked.paste((255, 0, 255), (0, 0), off)
                marked.save(os.path.join(FIELD_OUT, "%s-field.png" % re.sub(r"[^A-Za-z0-9_.-]", "_", name)))
            problems.append("%s: the page's field is not the window's picture in %d of %d pixels (around %r)" % (
                name, differing, counted, where))


def _ancestors_of(widget, stop):
    """The widgets round `widget` up to `stop` (not counted)."""
    found, parent = [], widget.master
    while parent is not None and parent is not stop:
        found.append(parent)
        parent = parent.master
    return found


def _field_frame(frame, area):
    """Whether `frame` is one of the page's field frames (no card's, in the field's colour): it shows the picture."""
    if any(isinstance(a, widgets.Card) for a in _ancestors_of(frame, area.inner)):
        return False
    try:
        return str(frame.cget("bg")).lower() == str(area.cget("bg")).lower()
    except Exception:
        return False


def lime_check(app, name, problems):
    """One lime main action on a screen: of PLAY lit at the foot and the page's lit lime buttons (the guide's Next among
    them), never more than one; and no words that act in lime (a link is in the words' own colour, widgets.link: four
    lime links beside a lime button once made five lime things on PLAY)."""
    import tkinter as tk
    from opendmtq_client import theme
    lit = []
    for w in widgets_of(app.root):
        if not w.winfo_ismapped():
            continue
        if isinstance(w, widgets.Button) and w.look == widgets.Button.LOOKS["primary"] and w.enabled:
            lit.append(w.words)
        elif isinstance(w, widgets.PlaySlab) and w.state == "ready":
            lit.append("PLAY")
        elif isinstance(w, tk.Label) and str(w.cget("cursor")) == "hand2" and \
                str(w.cget("fg")).lower() == theme.OK.lower():
            problems.append("%s: the link %r is lime" % (name, w.cget("text")))
    if len(lit) > 1:
        problems.append("%s: %d lime main actions: %r" % (name, len(lit), lit))


def shot(root, out, name):
    """Screenshot of a window, through the X server (what a person would see)."""
    root.update()
    time.sleep(0.25)
    root.update()
    top = root.wm_frame()
    target = os.path.join(out, name + ".png")
    subprocess.run(["import", "-window", top if top and top != "0x0" else str(root.winfo_id()), target], check=True)
    return target


def collect():
    """Python's collector run on the window's thread (main() turns its own runs off): what it frees may be the
    window's (a dialog's Tk variable, whose end asks Tk), and while no Tk main loop runs, as here, where the tests turn
    the window by update(), a worker thread that freed one would wait a second for each and fail. In the launcher the
    main loop runs, and a worker thread's call reaches Tk through it."""
    import gc
    gc.collect()


def settle(app, seconds=8.0, until=None):
    """Let worker threads (the ready check, the server's answers, a download) finish and reach the window."""
    collect()
    end = time.time() + seconds
    while time.time() < end:
        app.root.update()
        # The page's picture behind is drawn a moment after the page (widgets.ScrollArea): a shot waits for it.
        body = getattr(app.guide, "body", None) if getattr(app, "guide", None) is not None else getattr(app, "body", None)
        busy = (app.checks is None or app.download is not None or getattr(app, "records_asked", None) is not None or
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


def dialog_problems(dialog, name):
    """A dialog's own layout check (dialogs.Dialog.layout_problems) and its room (spacing.check_dialog)."""
    return (["%s: %s" % (name, p) for p in dialog.layout_problems()] + spacing.check_dialog(dialog, name)
            + design.check_dialog(dialog, name))


def through_dialog(app, out, name, press, answer, problems, extra=None, seconds=10.0):
    """Press a page button that asks first, as a person would; screenshot and measure the question it opens (after the
    work some buttons do first under a dialog that says so, such as counting what would go), then answer it with
    `answer(dialog)`. Returns what the dialog answered (None when none opened)."""
    seen, end = {}, time.time() + seconds

    def look():
        dialog = app.dialog
        if dialog is None or dialog.progress:
            # No question yet: the work before it may still be under way.
            if time.time() < end:
                app.root.after(100, look)
            else:
                problems.append("%s: the button opened no dialog" % name)
                seen["done"] = True
            return
        seen["dialog"] = dialog
        wait_out(app.root, 0.4)
        shot(app.root, out, name)
        problems.extend(dialog_problems(dialog, name))
        if extra:
            extra(dialog)
        answer(dialog)
        seen["done"] = True

    app.root.after(300, look)
    press()
    # A question asked after work on a worker thread comes once press() has returned: the window goes on until it was
    # seen and answered.
    while "done" not in seen and time.time() < end + 1:
        app.root.update()
        time.sleep(0.02)
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


def typed_address_check(app, out, name, problems, site_url):
    """A Connect that fails keeps what was typed in the address field, and the line under it names that address in the
    window's words, never Python's: an address with a blank (refused before anything is asked), then one nobody
    answers at. A Connect that works shows the server's address again, written as the launcher writes it. Works on the
    page on show (the guide's SERVER step or Online), whose first field is the address."""
    import tkinter as tk
    w = app.words
    for typed in ("not an address", "127.0.0.1:1"):
        field = entries(app)[0]
        field.delete(0, "end")
        field.insert(0, typed)
        # Connect, as a person presses it.
        button(app, w("online.connect")).press()
        settle(app, 12, until=lambda: not (app.server_check and app.server_check["state"] == "checking"))
        settle(app)
        field = entries(app)[0]
        if field.get() != typed:
            problems.append("%s: a failed Connect left %r in the address field, not %r" % (name, field.get(), typed))
        check = app.server_check or {}
        said = w.error(check["error"]) if check.get("state") == "failed" else None
        if typed == "not an address" and said != w("error.server.address", address=typed):
            problems.append("%s: an address with a blank was answered %r" % (name, said))
        if said is not None and typed != "not an address" and "http://127.0.0.1:1" not in said:
            problems.append("%s: the failure does not name the address typed: %r" % (name, said))
        shown = [x.cget("text") for x in widgets_of(app.root) if isinstance(x, tk.Label) and x.winfo_ismapped()]
        if said not in shown:
            problems.append("%s: the line under the address does not say %r" % (name, said))
        if any("control characters" in text or "Traceback" in text for text in shown):
            problems.append("%s: Python's own words on the page" % name)
        if typed == "not an address":
            shot(app.root, out, name + "-typed")
            measure(app, name + "-typed", problems)
    # Back to the server it was on: the field shows its address again, nothing typed kept.
    field = entries(app)[0]
    field.delete(0, "end")
    field.insert(0, site_url)
    button(app, w("online.connect")).press()
    settle(app, 12, until=lambda: not (app.server_check and app.server_check["state"] == "checking"))
    settle(app)
    kept = getattr(app, "address_draft", None)
    if kept is not None or entries(app)[0].get() != app.state.current:
        problems.append("%s: after a Connect that worked the field shows %r (kept %r)" % (name, entries(app)[0].get(),
                                                                                        kept))


def guide_check(app, site, out, tag, problems):
    """The first-start guide, step by step, as a person goes through it: the server the installer brought answers,
    the sign-in form is filled in, the download runs, then the screen and sound and the ready check."""
    import tkinter as tk

    from opendmtq_client import guide as guide_module
    guide = app.guide
    w = app.words
    for i, key in enumerate(guide_module.STEPS):
        if i:
            guide.next()
        settle(app)
        name = "%s_guide%d-%s" % (tag, i + 1, key)
        if key == "server":
            # A failed Connect keeps what was typed, said in plain words; then the server the installer brought again.
            typed_address_check(app, out, name, problems, site.url)
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
            if not any(line.startswith("could not sign in to %s as %s" % (site.url, stub.ACCOUNT)) for line in LOGGED):
                problems.append("%s: the refused sign-in is not in the log" % tag)
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
        seen = shot(app.root, out, name)
        measure(app, name, problems)
        if key == "sound":
            # The volume first, whole in view without scrolling, at every size down to the smallest window.
            area = guide.body
            slider = next((x for x in widgets_of(area.inner) if isinstance(x, widgets.Slider)), None)
            top, bottom = area.canvas.winfo_rooty(), area.canvas.winfo_rooty() + area.canvas.winfo_height()
            if (slider is None or area.canvas.canvasy(0) != 0 or slider.winfo_rooty() < top
                    or slider.winfo_rooty() + slider.winfo_height() > bottom):
                problems.append("%s: the volume is not in view without scrolling" % name)
        if key == "stage":
            slab_check(app.root, guide.play_slab, seen, name, problems)
            # The ready check alone before the first song: no card of how to play (usage is in the docs).
            titles = [card_title(card) for card in page_cards(guide.body)]
            if titles != [w("play.ready")]:
                problems.append("%s: the step's cards are %r" % (name, titles))
            # PLAY is the way on from the last step: no Skip beside it.
            if any(isinstance(x, tk.Label) and x.cget("text") == app.words("guide.skip") and x.winfo_ismapped()
                   for x in widgets_of(app.root)):
                problems.append("%s: Skip beside PLAY on the last step" % name)
        if not guide.next_button.enabled:
            problems.append("%s: Next stays off on the %s step" % (tag, key))
    return guide


def slab_check(root, slab, picture, name, problems):
    """PLAY's slab on its bar, in the screenshot as a person sees it: its keyboard ring's place along each side and the
    corner its cut leaves show the bar's own colour, never a frame of another round the slab."""
    from PIL import Image
    from opendmtq_client import theme
    if slab.focus_get() is slab:
        # The keyboard is on it: its cyan ring is meant to show.
        return
    x, y = slab.winfo_rootx() - root.winfo_rootx(), slab.winfo_rooty() - root.winfo_rooty()
    width, height = slab.winfo_width(), slab.winfo_height()
    bar = tuple(int(theme.STRIP[i:i + 2], 16) for i in (1, 3, 5))
    with Image.open(picture) as image:
        image = image.convert("RGB")
        spots = ((x, y + height // 2), (x + width - 1, y + height // 2), (x + width // 2, y),
                 (x + width // 2, y + height - 1), (x + 3, y + 3))
        others = sorted({image.getpixel(spot) for spot in spots} - {bar})
    if others:
        problems.append("%s: PLAY's slab sits in a frame of another colour than its bar's: %r" % (name, others))


def play_fits(app, name, tag, problems):
    """The PLAY page in the state on show, at its top, at the window's own size and larger: every button and link of it
    in view without scrolling (at 1180x760 in English, Check again and Open the game log once went half under the
    bottom bar after a game that closed by itself). At the smallest window, 960x640, the page may scroll for the Last
    game card's button."""
    import tkinter as tk
    # Its cards one under another, none stretched, none of usage (play_cards_check).
    play_cards_check(app, name, problems)
    area = app.body
    c = area.canvas
    area.to_top()
    app.root.update()
    # The window's height in logical pixels, as it is now (a check before may have made it the smallest).
    if app.root.winfo_height() / app.ui.scale < 700:
        return
    top, bottom = c.winfo_rooty(), c.winfo_rooty() + c.winfo_height()
    actions = 0
    for widget in widgets_of(area.inner):
        if not widget.winfo_ismapped():
            continue
        # A button, or words that do something (a link: the pointer's hand over it, widgets.link).
        if not (isinstance(widget, widgets.Button) or
                (isinstance(widget, tk.Label) and str(widget.cget("cursor")) == "hand2")):
            continue
        actions += 1
        if widget.winfo_rooty() < top or widget.winfo_rooty() + widget.winfo_height() > bottom:
            words = getattr(widget, "words", None) or widget.cget("text")
            problems.append("%s: %r is out of view until the page scrolls" % (name, words))
    if not actions:
        # The check looked at something: PLAY has Check again at least.
        problems.append("%s: no button on the PLAY page to look at" % name)


def card_titled(app, title):
    """The card on the page with this title (the way a person finds it), or None."""
    for widget in widgets_of(app.body.inner):
        if isinstance(widget, widgets.Card) and widget.head is not None and any(
                child.winfo_class() == "Label" and child.cget("text") == title for child in widget.head.winfo_children()):
            return widget
    return None


def card_title(card):
    """A card's title as its head shows it (its first label), or None for a card without one."""
    if card.head is None:
        return None
    return next((x.cget("text") for x in card.head.winfo_children() if x.winfo_class() == "Label"), None)


def page_cards(area):
    """The cards on show in a page area, in their order down the page."""
    cards = [x for x in widgets_of(area.inner) if isinstance(x, widgets.Card) and x.winfo_ismapped()]
    return sorted(cards, key=lambda card: card.winfo_rooty())


def play_head(app):
    """PLAY's head card: the first card down the page (it has no title: the server's name heads it)."""
    cards = page_cards(app.body)
    return cards[0] if cards else None


def play_cards_check(app, name, problems):
    """The PLAY page as its design composes it (DESIGN.md of the 0.11.1 design pass): its head card first, across the
    page, with no title of its own, the server's name heading it in the head's face (the page's largest words); then the
    ready check and the last game side by side and one height, the ready check the wider, where the page has two
    columns, one under another and each as tall as what it holds where it has one; then My records across the page
    when signed in. No card that only says how to play (the owner's rule: a page shows what to do now and the state;
    usage is in the docs): main had its cards one under another, a plain list (and How to play before that)."""
    import tkinter as tk
    w = app.words
    app.root.update()
    cards = page_cards(app.body)
    titles = [card_title(card) for card in cards]
    if titles not in ([None, w("play.ready"), w("play.last")], [None, w("play.ready"), w("play.last"),
                                                                w("play.records")]):
        problems.append("%s: PLAY's cards are %r" % (name, titles))
        return
    column = app.body.inner.winfo_width()
    head, ready, last = cards[:3]
    across = [card for card in (head,) + tuple(cards[3:]) if abs(card.winfo_width() - column) > 1]
    if across:
        problems.append("%s: %s not across the page" % (name, ", ".join(repr(card_title(c)) for c in across)))
    # The head is the page's hero, whatever it says (a server or none, signed in or not): a step nearer than the deck,
    # a brighter light along its top, its top corner cut deeper and its foot's cut too (design.hero).
    why = design.hero(head, app.ui)
    if why:
        problems.append("%s: PLAY's head card is not the page's hero: %s" % (name, why))
    if app.state.server() is not None:
        # The head's first words: the server's name (or its address, when it has no name), in the head's face.
        first = next((x for x in widgets_of(head.body) if isinstance(x, tk.Label) and x.winfo_ismapped()
                      and str(x.cget("text")).strip()), None)
        if first is None or str(first.cget("font")) != str(app.fonts.head):
            problems.append("%s: the head card's first words %r are not in the head's face" % (
                name, first.cget("text") if first is not None else None))
    if column >= app.ui.px(design.TWO_COLUMNS):
        if abs(ready.winfo_rooty() - last.winfo_rooty()) > 1 or abs(ready.winfo_height() - last.winfo_height()) > 1:
            problems.append("%s: the ready check (y %d, %d tall) and the last game (y %d, %d tall) are not side by side "
                            "at one height" % (name, ready.winfo_rooty(), ready.winfo_height(), last.winfo_rooty(),
                                               last.winfo_height()))
        if not (ready.winfo_rootx() < last.winfo_rootx() and ready.winfo_width() > last.winfo_width()):
            problems.append("%s: the ready check is not the wider card, left of the last game" % name)
    else:
        if len({card.winfo_rootx() for card in cards}) > 1:
            problems.append("%s: PLAY's cards stand side by side in a window of one column" % name)
        for card in cards:
            if card.winfo_height() > card.winfo_reqheight() + 1:
                problems.append("%s: the %r card is stretched %d px past what it holds" % (
                    name, card_title(card), card.winfo_height() - card.winfo_reqheight()))


# The cards each page that has only these shows, in their order: what the page does and shows, none that only tells how
# to use something (main had the mouse, the touch screen and the keyboard on Controls, and what to do when the game does
# not start on Help).
PAGE_CARDS = {"controls": ("controls.keys",), "help": ("help.checks", "help.tools", "help.remove")}


def cards_check(app, page, name, problems):
    """The cards of a page in PAGE_CARDS, as it shows them."""
    if page not in PAGE_CARDS:
        return
    titles = [card_title(card) for card in page_cards(app.body)]
    if titles != [app.words(key) for key in PAGE_CARDS[page]]:
        problems.append("%s: the page's cards are %r" % (name, titles))


def sound_last_check(app, out, tag, problems):
    """The Sound page's last game's sound, the Output card's last block under its own heading, after the output's
    choices: "No game on this PC yet." before the first game; after one, the player's result (last-game-sound.txt
    beside the settings file, as the player writes it) as one row, its lamp lime with no gaps and a ring with some, said
    again when a game ends while the page is on show; in view as a person scrolls to it, measured as every screen is."""
    import tkinter as tk
    from opendmtq_client import i18n
    from tests.base import SOUND_RESULT
    w = app.words
    # The card's file beside the settings file, as the player writes it (named here, not taken from the launcher's code:
    # a launcher without the card fails this check rather than the check itself).
    path = os.path.join(os.environ["OPENDMTQ_CLIENT_DIR"], "last-game-sound.txt")
    if os.path.exists(path):
        os.remove(path)
    app.go("sound")
    settle(app, 6, until=lambda: app.devices is not None)
    settle(app)
    title = w("sound.last") if "sound.last" in i18n.TEXT else "Last game" if w.language == "en" else "지난 플레이"

    def block():
        """What its heading heads: the frame round the heading, and the rows under it."""
        heading = next((x for x in widgets_of(app.body.inner) if isinstance(x, tk.Label) and x.winfo_ismapped()
                        and x.cget("text") == title), None)
        return heading.master if heading is not None else None

    found = block()
    if found is None:
        problems.append("%s_sound: no last game's sound on the Sound page" % tag)
        return
    output = card_titled(app, w("sound.output"))
    if output is None or not str(found).startswith(str(output) + "."):
        problems.append("%s_sound: the last game's sound is not in the Output card" % tag)

    def said():
        """The words under its heading, in order."""
        return [x.cget("text") for child in found.winfo_children() if not (isinstance(child, tk.Label)
                                                                           and child.cget("text") == title)
                for x in widgets_of(child) if x.winfo_class() == "Label" and x.cget("text")]

    if said() != [w("sound.last.none")]:
        problems.append("%s_sound: before a game the last game's sound says %r" % (tag, said()))
    # The row's words in each language: how the device was had, then the gaps.
    row = "Shared, 10 ms period, 18 ms output delay" if w.language == "en" else "공유, 주기 10 ms, 출력 지연 18 ms"
    cases = (("none", None, None),
             ("ok", SOUND_RESULT, [row, "no gaps" if w.language == "en" else "끊김 없음"]),
             ("gaps", SOUND_RESULT.replace("gaps=0\ngame_gaps=0", "gaps=1\ngame_gaps=2"),
              [row, "3 gaps" if w.language == "en" else "끊김 3번"]))
    for kind, text, want in cases:
        if text is not None:
            # As the player leaves it at a game's end, then the window's own follow-up of a game that ended.
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            app.follow_page("play", "sound", "help", "online")
            settle(app, 1)
            found = block()
            if found is None:
                problems.append("%s_sound_last_%s: the last game's sound went" % (tag, kind))
                return
            if sorted(said()) != sorted(want):
                problems.append("%s_sound_last_%s: it says %r, not %r" % (tag, kind, said(), want))
            lamps = [x for x in widgets_of(found) if getattr(x, "odq_picture", None) is not None]
            if len(lamps) != 1:
                problems.append("%s_sound_last_%s: %d lamps on its row (want 1)" % (tag, kind, len(lamps)))
        # In view, as a person scrolls to it.
        app.body.show_widget(found)
        settle(app, 0.5)
        name = "%s_sound_last_%s" % (tag, kind)
        shot(app.root, out, name)
        measure(app, name, problems)
    os.remove(path)
    app.follow_page("sound")
    settle(app, 0.5)


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
    collecting = gc.isenabled()
    gc.disable()
    try:
        before = commands()
        for _ in range(50):
            app.body.event_generate("<Enter>")
            app.body.event_generate("<Leave>")
        after = commands()
    finally:
        # As it was: main() keeps the collector to the window's thread (collect()).
        if collecting:
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
        app.rail.event_generate(sequence, x=5, y=5)
    try:
        app.rail.event_generate("<MouseWheel>", delta=-120, x=5, y=5)
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
        seen = shot(app.root, out, name)
        measure(app, name, problems)
        if page == "play":
            slab_check(app.root, app.play_button, seen, name, problems)
            play_fits(app, name, tag, problems)
        cards_check(app, page, name, problems)
        menu_mark_check(app, page, name, problems)
        if page == "screen":
            # After its shot: the wheel scrolls the page (the header turns into the dark bar).
            wheel_check(app, problems)


def menu_mark_check(app, page, name, problems):
    """The menu's page on show is its slab and its lime name, with no stripe of lime along the slab's edge (a box's
    side stripe says nothing the slab does not): the menu's own picture, a few pixels in from the slab's left edge, is
    the slab's colour there."""
    from opendmtq_client import theme
    menu = app.rail.list
    picture = getattr(menu, "odq_picture", None)
    box = menu.boxes.get(page) if hasattr(menu, "boxes") else None
    if picture is None or box is None:
        problems.append("%s: the menu drew no slab for the page on show" % name)
        return
    lime = tuple(int(theme.OK[i:i + 2], 16) for i in (1, 3, 5))
    middle = (box[1] + box[3]) // 2
    for x in range(box[0], box[0] + app.ui.px(4)):
        if picture.getpixel((x, middle))[:3] == lime:
            problems.append("%s: a stripe of lime along the menu's page on show" % name)
            return


def whole_rows_at_top(app, area):
    """The page area scrolled back, when its top edge cuts a line of text or a control, just far enough that it cuts
    none (to the gap above what it cut): the part in view starts with whole lines, as little of the page's foot given
    up for it as can be."""
    import tkinter as tk
    from tkinter import ttk
    c = area.canvas
    for _ in range(6):
        app.root.update_idletasks()
        top = c.canvasy(0)
        # Where the page's own pixel 0 is on the screen.
        origin = c.winfo_rooty() - top
        cut = None
        for widget in widgets_of(area.inner):
            # The things a person reads or uses: words, pictures, drop-downs, fields, the canvases of switches,
            # sliders, rows of tabs and buttons (a frame round them is no line of its own).
            if not widget.winfo_ismapped() or not isinstance(widget, (tk.Label, ttk.Combobox, tk.Entry, tk.Canvas)):
                continue
            if getattr(widget, "odq_field", False):
                # The page's own field under the cards (its picture on a canvas): no line a person reads.
                continue
            start = widget.winfo_rooty() - origin
            if start < top < start + widget.winfo_height():
                cut = start if cut is None else min(cut, start)
        if cut is None:
            return
        region = float(str(c.cget("scrollregion")).split()[3])
        c.yview_moveto(max(0.0, cut - app.ui.px(2)) / region)


def redraw_check(app, problems, tag):
    """The Screen page drawn again for a choice keeps its place: scrolled to the Quality card, the render scale chosen
    from the keyboard to 100 % takes the upscaler's row away and back below it, and neither throws the page back to its
    top nor the keyboard off the render scale's drop-down."""
    import tkinter as tk

    from opendmtq_client import widgets as wd
    w = app.words
    area = app.body

    def scale_select():
        # The drop-down in the row named Render scale.
        for widget in widgets_of(area.inner):
            if isinstance(widget, wd.Select) and getattr(widget.master, "control", None) is widget:
                names = [c.cget("text") for c in widget.master.winfo_children() if isinstance(c, tk.Label)]
                if w("screen.scale") in names:
                    return widget
        return None

    def upscaler_shown():
        return any(isinstance(c, tk.Label) and c.cget("text") == w("screen.upscaler") and c.winfo_ismapped()
                   for c in widgets_of(area.inner))

    for value, shown in (("100", False), ("75", True)):
        select = scale_select()
        if select is None:
            problems.append("%s: no render scale drop-down on the Screen page" % tag)
            return
        select.focus_set()
        settle(app)
        before = area.canvas.yview()[0]
        # Chosen as the keyboard chooses: the value set, then the drop-down's own event.
        select.set_value(value)
        select.event_generate("<<ComboboxSelected>>")
        settle(app)
        after = area.canvas.yview()[0]
        focused = app.root.focus_get()
        if upscaler_shown() != shown:
            problems.append("%s: render scale %s: the upscaler's row %s" % (tag, value, "missing" if shown else "still shown"))
        if before > 0 and after == 0:
            problems.append("%s: render scale %s: the page went back to its top (was at %.2f)" % (tag, value, before))
        if focused is not scale_select():
            problems.append("%s: render scale %s: the keyboard left the drop-down (now on %r)" % (tag, value, focused))


def opened_list_check(app, out, tag, problems):
    """A drop-down opened (the Screen page's frame limit, the longest list), as a person sees and uses it: the list is
    the launcher's own (widgets.DropList), under the box and inside the screen; its words start where the closed box's
    words do (the same column of pixels); the chosen row carries the lime rule; a list longer than its rows scrolls (End
    brings the last row into view, the bar along its edge); the arrow keys light a row with the cyan ring, Esc closes it
    as it was, Enter chooses; and with the box near the screen's foot the list opens over it, never past the edge. The
    list is a window of its own over the launcher's: the shots are of the screen where they are."""
    from PIL import Image
    w = app.words
    area = app.body
    select = None
    for widget in widgets_of(area.inner):
        if isinstance(widget, widgets.Select) and getattr(widget.master, "control", None) is widget:
            names = [c.cget("text") for c in widget.master.winfo_children() if c.winfo_class() == "Label"]
            if w("screen.fps") in names:
                select = widget
    if select is None:
        problems.append("%s: no frame limit drop-down on the Screen page to open" % tag)
        return
    area.show_widget(select)
    app.root.update()
    before = select.current()
    # Opened as a person opens it: a press on the box.
    select.event_generate("<ButtonPress-1>", x=5, y=5)
    wait_out(app.root, 0.4)
    found = select.droplist
    if found is None or not found.winfo_exists():
        problems.append("%s: a press on the frame limit's box opened no list" % tag)
        return
    try:
        geometry = lambda path: [int(app.root.tk.call("winfo", k, path)) for k in ("rootx", "rooty", "width", "height")]  # noqa: E731
        lx, ly, lw, lh = geometry(str(found))
        cx, cy, cw, ch = geometry(str(select))
        screen = (app.root.winfo_screenwidth(), app.root.winfo_screenheight())
        problems.extend(spacing.check_list(found, app.ui, "%s_screen-list-open" % tag))
        if lx < 0 or ly < 0 or lx + lw > screen[0] or ly + lh > screen[1]:
            problems.append("%s: the opened list reaches past the screen (%d,%d %dx%d)" % (tag, lx, ly, lw, lh))
        if not ly >= cy + ch:
            problems.append("%s: the opened list is not under its box with room for it under" % tag)
        if lw < cw:
            problems.append("%s: the opened list (%d px) is narrower than its box (%d px)" % (tag, lw, cw))
        # The window's part of the screen with the list in it.
        rx, ry, rw, rh = geometry(str(app.root))
        bottom = max(ry + rh, ly + lh)
        target = os.path.join(out, "%s_screen-list-open.png" % tag)
        subprocess.run(["import", "-window", "root", "-crop", "%dx%d+%d+%d" % (rw, bottom - ry, rx, ry), target],
                       check=True)
        with Image.open(target) as image:
            image = image.convert("RGB")

            def ink(x_from, x_to, y_from, y_to):
                # The first column, from the left, with a pixel of the words' light.
                for x in range(x_from, x_to):
                    if any(sum(image.getpixel((x - rx, y - ry))) > 300 for y in range(y_from, y_to)):
                        return x
                return None

            closed = ink(cx + 2, cx + cw // 2, cy + 4, cy + ch - 4)
            row = found._rows_box(found.chosen)
            canvas_x, canvas_y = found.canvas.winfo_rootx(), found.canvas.winfo_rooty()
            if row is None:
                problems.append("%s: the chosen row is not in view in the opened list" % tag)
            else:
                # Past the chosen row's lime rule (3 logical pixels at the row's left edge), where its words are.
                opened = ink(canvas_x + row[0] + app.ui.px(4), canvas_x + row[2] // 2, canvas_y + row[1] + 4,
                             canvas_y + row[3] - 4)
                if closed is None or opened is None or abs(closed - opened) > 1:
                    problems.append("%s: the opened list's words start at %r, the closed box's at %r" % (
                        tag, opened and opened - cx, closed and closed - cx))
                rule = image.getpixel((canvas_x + row[0] + 1 - rx, canvas_y + (row[1] + row[3]) // 2 - ry))
                from opendmtq_client import theme
                if rule != tuple(int(theme.OK[i:i + 2], 16) for i in (1, 3, 5)):
                    problems.append("%s: the chosen row has no lime rule (%r)" % (tag, rule))
        if found.count > found.ROWS:
            if not found.scrolls:
                problems.append("%s: a list of %d rows does not scroll" % (tag, found.count))
            # End: the last row lit and in view, with the keyboard's ring.
            found.event_generate("<End>")
            app.root.update()
            if found.active != found.count - 1 or found._rows_box(found.count - 1) is None or not found.keyboard:
                problems.append("%s: End in the opened list did not bring its last row into view" % tag)
            shot_list = os.path.join(out, "%s_screen-list-end.png" % tag)
            subprocess.run(["import", "-window", "root", "-crop", "%dx%d+%d+%d" % (lw, lh, lx, ly), shot_list],
                           check=True)
        # Esc: closed as it was, the keyboard on the box.
        found.event_generate("<Escape>")
        app.root.update()
        if select.droplist is not None or found.winfo_exists():
            problems.append("%s: Esc did not close the opened list" % tag)
        if select.current() != before:
            problems.append("%s: Esc changed the frame limit" % tag)
        if app.root.focus_get() is not select:
            problems.append("%s: after Esc the keyboard is on %r, not the drop-down" % (tag, app.root.focus_get()))
        # Down then Enter by the keyboard: the next row chosen, said as a choice; then back as it was.
        select.event_generate("<Down>")
        wait_out(app.root, 0.2)
        if select.droplist is None:
            problems.append("%s: Down on the box opened no list" % tag)
        else:
            select.droplist.event_generate("<Down>")
            select.droplist.event_generate("<Return>")
            app.root.update()
            if select.current() != min(before + 1, len(select.options) - 1):
                problems.append("%s: Down and Enter in the list chose row %d, not %d" % (tag, select.current(),
                                                                                     before + 1))
            select.set_value(select.options[before][0])
            select.event_generate("<<ComboboxSelected>>")
            app.root.update()
        # Near the screen's foot: the list opens over its box, inside the screen.
        place = app.root.geometry()
        rx, ry, rw, rh = geometry(str(app.root))
        offset = select.winfo_rooty() - ry
        app.root.geometry("+%d+%d" % (rx, screen[1] - offset - ch - app.ui.px(20)))
        wait_out(app.root, 0.3)
        select.event_generate("<ButtonPress-1>", x=5, y=5)
        wait_out(app.root, 0.3)
        found = select.droplist
        if found is None:
            problems.append("%s: no list opened near the screen's foot" % tag)
        else:
            lx, ly, lw, lh = geometry(str(found))
            if ly + lh > screen[1] or ly < 0 or not found.opened_above:
                problems.append("%s: near the screen's foot the list reaches %d px of %d (over its box: %s)" % (
                    tag, ly + lh, screen[1], found.opened_above))
            found.close()
        app.root.geometry(place)
        wait_out(app.root, 0.3)
    finally:
        if select.droplist is not None:
            select.droplist.close()
        app.root.update()


def counter_check(app, problems, tag):
    """The FPS counter switched from the keyboard on the Screen page: Space on its toggle turns it on, its Position row
    comes under it; Space again turns it off, the row goes; the keyboard stays on the toggle each time, and the corner
    chosen before stays chosen."""
    import tkinter as tk

    from opendmtq_client import widgets as wd
    w = app.words
    area = app.body

    def counter_toggle():
        # The toggle in the row named FPS counter.
        for widget in widgets_of(area.inner):
            if isinstance(widget, wd.Toggle) and getattr(widget.master, "control", None) is widget:
                names = [c.cget("text") for c in widget.master.winfo_children() if isinstance(c, tk.Label)]
                if w("screen.counter") in names:
                    return widget
        return None

    def position_shown():
        return any(isinstance(c, tk.Label) and c.cget("text") == w("screen.counter.position") and c.winfo_ismapped()
                   for c in widgets_of(area.inner))

    corner = app.state.values["fps_position"]
    for on in (not (app.state.values["show_fps"] == "on"), app.state.values["show_fps"] == "on"):
        toggle = counter_toggle()
        if toggle is None:
            problems.append("%s: no FPS counter toggle on the Screen page" % tag)
            return
        toggle.focus_set()
        settle(app)
        # Pressed as the keyboard presses it.
        toggle.event_generate("<space>")
        settle(app)
        if (app.state.values["show_fps"] == "on") != on:
            problems.append("%s: Space on the FPS counter did not turn it %s" % (tag, "on" if on else "off"))
        if position_shown() != on:
            problems.append("%s: FPS counter %s: the Position row %s" % (tag, "on" if on else "off", "missing" if on else "still shown"))
        if app.root.focus_get() is not counter_toggle():
            problems.append("%s: FPS counter %s: the keyboard left the toggle (now on %r)" % (tag, "on" if on else "off", app.root.focus_get()))
    if app.state.values["fps_position"] != corner:
        problems.append("%s: switching the FPS counter changed its corner (%s, was %s)" % (tag, app.state.values["fps_position"], corner))


def keys_fit(app, name, problems):
    """The keys card's table whole inside its card: as wide as it asks to be (a narrower one cuts its last column off,
    inside the card, where measure() looks only at the window's edge), and every box inside the card's room."""
    app.root.update()
    card = card_titled(app, app.words("controls.keys"))
    boxes = [x for x in widgets_of(app.body.inner) if isinstance(x, widgets.KeyBox) and x.winfo_ismapped()]
    if card is None or not boxes:
        return
    # A box, its lane, its mode's block, then the table of the blocks.
    table = boxes[0].master.master.master
    if table.winfo_reqwidth() > table.winfo_width() + 1:
        problems.append("%s: the keys' table is %d px wide where it needs %d" % (name, table.winfo_width(),
                                                                                table.winfo_reqwidth()))
    # The card's room: inside its padding (Card's 24 logical pixels).
    right = card.winfo_rootx() + card.winfo_width() - app.ui.px(24)
    for box in boxes:
        if box.winfo_rootx() + box.winfo_width() > right + 1:
            problems.append("%s: the box of %s lane %d reaches %d px past its card's room" % (
                name, box.odq_where[0], box.odq_where[1] + 1, box.winfo_rootx() + box.winfo_width() - right))


def keys_check(app, out, tag, problems):
    """The Controls page's keyboard play as a person uses it, by the mouse and the keys (X11's key codes, Linux's key
    numbers plus 8, as the virtual screen sends them): a box clicked waits; a key another lane of the mode plays, and one
    no lane takes, refused in words with nothing changed and the box still waiting; Esc keeps; a key on a lane's empty
    box goes in as its second by its place, with what the keyboard prints there beside it, saved, the keyboard on that
    box; Delete takes it away and refuses a lane's only key; Reset keys; the switch off and on, the keyboard on it. Its
    states shot and measured (waiting, refused, a second key, every lane on two long keys with Windows' prints beside
    them, off), and the table's boxes on one middle in a lane, beside its number, and from one line in a column."""
    from opendmtq_client import theme
    from opendmtq_client import values as choices
    w = app.words
    app.go("controls")
    settle(app)

    def box(name, lane, slot):
        """The box of a mode's lane, as the page has it now."""
        for widget in widgets_of(app.body.inner):
            if isinstance(widget, widgets.KeyBox) and widget.odq_where == (name, lane, slot):
                return widget
        return None

    def boxes():
        return [x for x in widgets_of(app.body.inner) if isinstance(x, widgets.KeyBox) and x.winfo_ismapped()]

    def line():
        """The line under the table: the last thing its card's body holds."""
        found = boxes()
        # A box, its lane, its mode's block, the table, then what holds the table and the line under it.
        return found[0].master.master.master.master.pack_slaves()[-1] if found else None

    def press(target, code, keysym):
        """A key pressed with the keyboard on `target`, as the virtual screen sends it."""
        target.focus_set()
        app.root.update()
        target.event_generate("<KeyPress>", keycode=code, keysym=keysym)
        settle(app)

    def click(target):
        target.event_generate("<Button-1>", x=5, y=5)
        settle(app)

    def said(text, colour, what):
        from opendmtq_client import pages
        found = line()
        # Its words as the page sets them: a mode's name in them kept whole on the line (pages.whole_modes).
        text = pages.whole_modes(text)
        if found is None or found.cget("text") != text or str(found.cget("fg")).lower() != colour.lower():
            problems.append("%s: %s: the line under the keys says %r in %s" % (
                tag, what, found and found.cget("text"), found and found.cget("fg")))

    hint = w("controls.keys.hint")
    # ---- the table: 9 lanes' keys and their empty boxes; each lane's boxes on one middle with its number; each mode's
    # boxes from one line.
    if len(boxes()) != 18:
        problems.append("%s: the keys card has %d boxes, not 18 (9 lanes, each a key and an empty box)" % (tag, len(boxes())))
        return
    # Each mode's block: each lane's boxes and its number on one middle, the mode's first boxes from one line.
    for name in choices.LANES:
        mine = [b for b in boxes() if b.odq_where[0] == name]
        block = mine[0].master.master
        for lane in range(choices.LANES[name]):
            middles = [b.winfo_rooty() + b.winfo_height() / 2.0 for b in mine if b.odq_where[1] == lane]
            middles += [n.winfo_rooty() + n.winfo_height() / 2.0 for n in block.grid_slaves(row=lane + 1, column=0)]
            if max(middles) - min(middles) > 1:
                problems.append("%s: %s lane %d's boxes and number have middles at %r" % (tag, choices.mode(name),
                                                                                          lane + 1, middles))
        starts = {b.winfo_rootx() for b in mine if b.odq_where[2] == 0}
        if len(starts) != 1:
            problems.append("%s: the column of %s starts at %r" % (tag, choices.mode(name), sorted(starts)))
    said(hint, theme.MUTED, "at first")
    # ---- a box clicked waits for a key.
    target = box("keys_3line", 0, 0)
    click(target)
    target = box("keys_3line", 0, 0)
    if not target.waiting or app.root.focus_get() is not target:
        problems.append("%s: a click did not make 3 LINE's first box wait with the keyboard" % tag)
    said(w("controls.keys.wait", lane=1, mode="3 LINE", keyname="D"), theme.TEXT, "waiting")
    shot(app.root, out, tag + "_controls-waiting")
    measure(app, tag + "_controls-waiting", problems)
    keys_fit(app, tag + "_controls-waiting", problems)
    # ---- J, which 3 LINE's third lane plays: refused, nothing changed, the box still waiting.
    press(target, 44, "j")
    said(w("error.keys.taken", keyname="J", lane=3, mode="3 LINE"), theme.WARN, "J on 3 LINE's first lane")
    if app.state.values["keys_3line"] != "D F J" or not box("keys_3line", 0, 0).waiting:
        problems.append("%s: a key another lane plays changed %r or stopped the wait" % (tag, app.state.values["keys_3line"]))
    shot(app.root, out, tag + "_controls-refused")
    measure(app, tag + "_controls-refused", problems)
    keys_fit(app, tag + "_controls-refused", problems)
    # ---- Enter, which no lane takes: refused by its name; then Esc keeps D and stops the wait.
    press(box("keys_3line", 0, 0), 36, "Return")
    said(w("controls.keys.cannot", keyname="Enter"), theme.WARN, "Enter on a waiting box")
    press(box("keys_3line", 0, 0), 9, "Escape")
    said(hint, theme.MUTED, "after Esc")
    if box("keys_3line", 0, 0).waiting or app.state.values["keys_3line"] != "D F J":
        problems.append("%s: Esc did not keep the box as it was" % tag)
    # ---- a second key: the semicolon's place on 2 LINE's first lane, what it prints beside its name, saved.
    click(box("keys_2line", 0, 1))
    said(w("controls.keys.wait.second", lane=1, mode="2 LINE"), theme.TEXT, "the empty box waiting")
    press(box("keys_2line", 0, 1), 47, "semicolon")
    second = box("keys_2line", 0, 1)
    if app.state.values["keys_2line"] != "F/Semicolon J" or second is None or (second.key, second.printed) != (
            "Semicolon", ";"):
        problems.append("%s: the semicolon's place as 2 LINE's second key gave %r, its box %r" % (
            tag, app.state.values["keys_2line"], second and (second.key, second.printed)))
    elif app.root.focus_get() is not second or app.status_text != w("status.saved"):
        problems.append("%s: after a key went in the keyboard is on %r, the status line says %r" % (
            tag, app.root.focus_get(), app.status_text))
    shot(app.root, out, tag + "_controls-second")
    measure(app, tag + "_controls-second", problems)
    keys_fit(app, tag + "_controls-second", problems)
    # ---- Delete takes it away; on a lane's only key it is refused.
    click(box("keys_2line", 0, 1))
    press(box("keys_2line", 0, 1), 119, "Delete")
    if app.state.values["keys_2line"] != "F J":
        problems.append("%s: Delete on a second key left %r" % (tag, app.state.values["keys_2line"]))
    click(box("keys_2line", 1, 0))
    press(box("keys_2line", 1, 0), 119, "Delete")
    said(w("error.keys.one", lane=2, mode="2 LINE"), theme.WARN, "Delete on a lane's only key")
    press(box("keys_2line", 1, 0), 9, "Escape")
    # ---- another key in a box's place, then Reset keys puts every default back.
    click(box("keys_4line", 3, 0))
    press(box("keys_4line", 3, 0), 46, "l")
    if app.state.values["keys_4line"] != "D F J L":
        problems.append("%s: L on 4 LINE's last lane gave %r" % (tag, app.state.values["keys_4line"]))
    button(app, w("controls.keys.reset")).press()
    settle(app)
    if any(app.state.values[name] != choices.DEFAULTS[name] for name in choices.LANES):
        problems.append("%s: Reset keys left %r" % (tag, [app.state.values[name] for name in choices.LANES]))
    # ---- every lane on two long keys, with what Windows' layout prints beside each (the US layout's here), at the
    # window's size: nothing cut off or past its edge.
    app.key_prints.update(choices.US_PRINT)
    longest = ["LeftBracket/RightBracket", "Semicolon/Quote", "Backslash/Equals", "Comma/Period"]
    for name, count in choices.LANES.items():
        app.changed(name, " ".join(longest[:count]))
    app.go("controls")
    settle(app)
    shot(app.root, out, tag + "_controls-long")
    measure(app, tag + "_controls-long", problems)
    keys_fit(app, tag + "_controls-long", problems)
    # The same with the names drawn wider, as Windows draws Pretendard (rows.py's measure of it): still in the window.
    bold = app.fonts.body_bold
    size = int(bold.cget("size"))
    bold.configure(size=size + 1)
    try:
        app.go("controls")
        settle(app)
        # The names' face alone made larger to draw its words wider: the sizes between faces are no longer the launcher's,
        # so a heading in another face measured against them says nothing here (design.py's headings, measured on every
        # other screen).
        found = []
        measure(app, tag + "_controls-long with wider names", found)
        problems.extend(p for p in found if "is smaller than the words under it" not in p)
        keys_fit(app, tag + "_controls-long with wider names", problems)
    finally:
        bold.configure(size=size)
    app.key_prints.clear()
    for name in choices.LANES:
        app.changed(name, choices.DEFAULTS[name])
    # ---- the switch, by the keyboard: off takes the table and Reset keys away, on brings them back, the keyboard on
    # the switch each time, and the switch where it was (under the pointer that switched it).
    app.go("controls")
    settle(app)
    card = card_titled(app, w("controls.keys"))
    for on in (False, True):
        switch = next((x for x in widgets_of(card) if isinstance(x, widgets.Toggle)), None) if card else None
        if switch is None:
            problems.append("%s: no switch on the keys card" % tag)
            return
        switch.focus_set()
        settle(app)
        before = switch.winfo_rooty()
        switch.event_generate("<space>")
        settle(app)
        card = card_titled(app, w("controls.keys"))
        focus = app.root.focus_get()
        if isinstance(focus, widgets.Toggle) and abs(focus.winfo_rooty() - before) > 1:
            problems.append("%s: keyboard play %s: the switch moved %d px" % (tag, "on" if on else "off",
                                                                            focus.winfo_rooty() - before))
        shown = len(boxes())
        reset_shown = any(isinstance(x, widgets.Button) and x.words == w("controls.keys.reset") and x.winfo_ismapped()
                          for x in widgets_of(app.body.inner))
        if app.state.values["keyboard"] != ("on" if on else "off") or (shown == 18) != on or reset_shown != on:
            problems.append("%s: keyboard play %s: %r, %d boxes, Reset keys %s" % (
                tag, "on" if on else "off", app.state.values["keyboard"], shown, "shown" if reset_shown else "gone"))
        if not isinstance(focus, widgets.Toggle):
            problems.append("%s: keyboard play %s: the keyboard left the switch (now on %r)" % (tag, "on" if on else "off", focus))
        if not on:
            shot(app.root, out, tag + "_controls-off")
            measure(app, tag + "_controls-off", problems)
    app.go("controls")
    settle(app)


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
    # Below 100 %: the upscaler's row and its hint, with an anti-aliasing chosen (the longest hint of each).
    app.changed("render_scale", "50")
    app.changed("upscaler", "fsr1")
    app.changed("anti_aliasing", "smaa")
    # The FPS counter on, with its corner's row under it (the longest corner's name).
    app.changed("show_fps", "on")
    app.changed("fps_position", "bottom_right")
    app.go("screen")
    settle(app)
    # Scrolled to its end, where the Quality card is, then back to the top of the row the window's top edge would cut:
    # no line of text half out of sight under the header (docs/images/client-screen.png is this screen in English at
    # 1180x760).
    from opendmtq_client import widgets as wd
    for area in [w for w in widgets_of(app.root) if isinstance(w, wd.ScrollArea) and w.winfo_ismapped()]:
        area.canvas.yview_moveto(1)
        settle(app)
        whole_rows_at_top(app, area)
    settle(app)
    shot(app.root, out, tag + "_screen-upscaler")
    measure(app, tag + "_screen-upscaler", problems)
    redraw_check(app, problems, tag)
    counter_check(app, problems, tag)
    opened_list_check(app, out, tag, problems)
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
    # Cancel, and the page drawn again before the download has stopped: its bar says what the status line says.
    app.cancel_download()
    app.go("online")
    app.root.update()
    said = app.download_bar.words.cget("text") if app.download_bar is not None else None
    if said != w("status.stopping") or app.status_text != said:
        problems.append("%s: the page's download bar says %r while the download stops" % (tag, said))
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
        if page == "play":
            play_fits(app, "%s_play-signed-out" % tag, tag, problems)
            # The status line says what the ready check's yellow Sign-in row says (main: "Ready to play.").
            if app.status_text != w("status.signin_ended") or app.status_tone != "warn":
                problems.append("%s_play-signed-out: the status line says %r beside a sign-in that ended" % (
                    tag, app.status_text))
    # A game that closed by itself.
    app.state.last_session = {"seconds": 754, "exit_code": 3221225477, "crashed": True}
    app.set_status(w("status.crashed"), "bad", action=(w("status.open_log"), app.open_player_log))
    app.go("play")
    settle(app)
    shot(app.root, out, tag + "_play-crashed")
    measure(app, tag + "_play-crashed", problems)
    play_fits(app, tag + "_play-crashed", tag, problems)
    # The same with the sign-in that still holds, as most players find the page after such a game: the server's name,
    # its address and the line of its account, Sign in gone; then a game that could not start at all.
    from opendmtq_client import actions as acts
    acts.sign_in(app.state, stub.ACCOUNT, stub.PASSWORD)
    app.state.save()
    app.go("play")
    settle(app)
    shot(app.root, out, tag + "_play-crashed-signed-in")
    measure(app, tag + "_play-crashed-signed-in", problems)
    play_fits(app, tag + "_play-crashed-signed-in", tag, problems)
    app.state.last_session = {"seconds": 2, "exit_code": 1, "failed_start": True}
    app.set_status(w("status.failed_start"), "bad", action=(w("status.open_log"), app.open_player_log))
    app.go("play")
    settle(app)
    shot(app.root, out, tag + "_play-failed-start")
    measure(app, tag + "_play-failed-start", problems)
    play_fits(app, tag + "_play-failed-start", tag, problems)
    # Signed out again, and the game that closed by itself, for what follows (an installer's server, a server without a
    # name of its own).
    app.state.forget_sign_in()
    app.state.last_session = {"seconds": 754, "exit_code": 3221225477, "crashed": True}
    app.state.save()
    # A server an installer leaves while the window is open: the window takes it within a few seconds and says so.
    from opendmtq_client import preset
    before = app.state.current
    preset.hand_over({"url": "http://192.0.2.20:8790", "name": "Club"})
    settle(app, 6, until=lambda: app.state.server("http://192.0.2.20:8790") is not None)
    app.go("play")
    settle(app)
    shot(app.root, out, tag + "_play-preset")
    measure(app, tag + "_play-preset", problems)
    play_fits(app, tag + "_play-preset", tag, problems)
    if app.state.server("http://192.0.2.20:8790") is None or w("status.preset", name="Club") != app.status_text:
        problems.append("%s: the window did not take the installer's server (%r)" % (tag, app.status_text))
    # The same server again (an installer from the site of the server in use, "Open OpenDMTQ"): taken, and as nothing
    # changed, nothing said; then the stand-in, known but not in use: played on, and said as a switch, not an addition.
    from opendmtq_client import state as st
    handed = os.path.join(st.config_dir(), preset.FILE_NAME)
    for url, name, said in (("http://192.0.2.20:8790", "Club", None), (before, "Stand-in", "status.preset.switched")):
        # Kept until something says otherwise (a ready check coming back meanwhile does not replace it).
        app.set_status("(the line before)", "normal", sticky=True)
        preset.hand_over({"url": url, "name": name})
        settle(app, 6, until=lambda: not os.path.exists(handed))
        settle(app)
        expected = "(the line before)" if said is None else w(said, name=name)
        if os.path.exists(handed) or app.status_text != expected or app.state.current != url:
            problems.append("%s: the installer's %s, known, made the line say %r (playing on %s)"
                            % (tag, name, app.status_text, app.state.current))
    # Back to the stand-in server for the dialogs that follow.
    app.state.remove_server("http://192.0.2.20:8790")
    app.state.current = before
    app.state.save()
    app.refresh_checks()
    unnamed_check(app, out, tag, problems)


def records_check(app, site, out, tag, problems):
    """PLAY signed in: My records under the columns (the stand-in's made-up plays: a long title, the keyboard's mark, a
    new record, places on the charts), My page on the site on the server card opening the one-time link in the browser,
    then the records of an account linked to no player and of one with no plays; signed out, neither."""
    import tkinter as tk
    from opendmtq_client import actions as acts
    w = app.words
    opened = []
    real_open = acts.open_url
    acts.open_url = opened.append
    try:
        app.records = None
        app.go("play")
        settle(app)
        name = tag + "_play-records"
        shot(app.root, out, name)
        measure(app, name, problems)
        play_fits(app, name, tag, problems)
        card = card_titled(app, w("play.records"))
        shown = [x.cget("text") for x in widgets_of(app.root) if isinstance(x, tk.Label) and x.winfo_ismapped()]
        if card is None:
            problems.append("%s: no My records card on PLAY signed in" % name)
        for words in (w("play.records.recent"), w("play.records.best"), "987,654", w("play.records.place", n=1, all=4),
                      "Glass Garden of the Long Afternoon", w("play.records.keys")):
            if words not in shown:
                problems.append("%s: PLAY's records do not say %r" % (name, words))
        # Three of each list, no more: the rest is on the site.
        if shown.count("812,300") != 2:
            problems.append("%s: the records' lists do not each show three rows" % name)
        # A chart's mode as How to play and Controls name it: "3 LINE Hard 9" (main: "3LINE Hard 9" on the same page).
        # Its name kept whole on its line, with a space that never ends one (pages.whole_modes).
        from opendmtq_client import pages
        glued = [t for t in shown if re.search(r"\dLINE|\d LINE", t)]
        if glued or not any(t.startswith("3" + pages.NO_BREAK + "LINE Hard 9") for t in shown):
            problems.append("%s: PLAY's records name the charts %r" % (name, glued or shown))
        # The page at its end, where the card is whole.
        app.body.canvas.yview_moveto(1.0)
        settle(app)
        shot(app.root, out, name + "-end")
        app.body.to_top()
        settle(app)
        # My page on the site: the server's one-time link opened, said on the status line.
        button(app, w("play.mypage")).press()
        settle(app, 6, until=lambda: bool(opened))
        settle(app)
        if opened != [site.url + "/opendmtq/login.php?once=" + stub.LINK_TOKEN]:
            problems.append("%s: My page on the site opened %r" % (name, opened))
        if app.status_text != w("status.mypage.opened"):
            problems.append("%s: after My page on the site the status line says %r" % (name, app.status_text))
        shot(app.root, out, tag + "_play-mypage")
        measure(app, tag + "_play-mypage", problems)
        # A server older than one-time links: its site's address opened, and the status line says the site opened.
        site.links = False
        opened.clear()
        button(app, w("play.mypage")).press()
        settle(app, 6, until=lambda: bool(opened))
        settle(app)
        site.links = True
        if opened != [site.url + "/opendmtq/"] or app.status_text != w("status.site.opened"):
            problems.append("%s: My page on the site of a server older than its links opened %r, said %r"
                            % (name, opened, app.status_text))
        # An account linked to no player, then one with no plays: one line each.
        for variant, answer, said in (("unlinked", {"account": stub.ACCOUNT, "player": None, "recent": [], "best": []},
                                       w("play.records.unlinked", account=stub.ACCOUNT)),
                                      ("none", dict(stub.made_up_records(), recent=[], best=[]), w("play.records.none"))):
            site.records = answer
            app.refresh_records(force=True)
            settle(app)
            vname = "%s_play-records-%s" % (tag, variant)
            shot(app.root, out, vname)
            measure(app, vname, problems)
            if said not in [x.cget("text") for x in widgets_of(app.root) if isinstance(x, tk.Label) and x.winfo_ismapped()]:
                problems.append("%s: the records card does not say %r" % (vname, said))
        site.records = stub.made_up_records()
        app.refresh_records(force=True)
        settle(app)
    finally:
        acts.open_url = real_open


def test_check(app, site, out, tag, problems):
    """The connection test on the Online page: Test connection, its card filled in step by step (a row a step, every
    one said), its verdict, Copy; a server that moved to another port found there, with Use this address, which plays
    on it; PLAY's Server row leading to the test while the server does not answer."""
    import tkinter as tk
    from opendmtq_client import connection
    w = app.words
    app.go("online")
    settle(app)
    button(app, w("test.button")).press()
    settle(app, 30, until=lambda: app.connection_test is not None and not app.connection_test["running"])
    settle(app)
    name = tag + "_online-test"
    card = card_titled(app, w("test.title"))
    if card is None:
        problems.append("%s: no connection test card" % name)
        return
    app.body.show_widget(card)
    settle(app)
    shot(app.root, out, name)
    measure(app, name, problems)
    shown = [x.cget("text") for x in widgets_of(card) if isinstance(x, tk.Label) and x.winfo_ismapped()]
    for key in connection.STEPS:
        if w("test." + key) not in shown:
            problems.append("%s: the card has no row for %s" % (name, key))
    if w("test.waiting") in shown:
        problems.append("%s: a step still waits after the test ended" % name)
    # Copy: the whole result on the clipboard, in the window's language.
    button(app, w("test.copy")).press()
    settle(app)
    copied = app.root.clipboard_get()
    if not copied.startswith(w("test.text.title", url=site.url, at="")[:20]) or len(copied.splitlines()) != 12:
        problems.append("%s: Copy copied %r" % (name, copied[:80]))
    # A server that moved: the launcher's address on a port nobody listens on, the stand-in's port among those a new
    # server takes.
    before = app.state.current
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
    old = "http://127.0.0.1:%d" % closed
    app.state.add_server(old, "Stand-in")
    app.state.servers = [x for x in app.state.servers if x["url"] != before]
    app.refresh_checks(force=True)
    real_ports = connection.PORTS
    connection.PORTS = (closed + 1, int(site.url.rsplit(":", 1)[1]))
    try:
        app.go("play")
        settle(app, 12)
        name = tag + "_play-server-down"
        shot(app.root, out, name)
        measure(app, name, problems)
        # The server card says the server does not answer, and its Sign in, which cannot reach it, is not the screen's
        # lime main action (main said only "Not signed in yet." beside a lime Sign in).
        server_card = play_head(app)
        said = [x.cget("text") for x in widgets_of(server_card) if isinstance(x, tk.Label)] if server_card else []
        lime = [x.words for x in widgets_of(server_card) if isinstance(x, widgets.Button)
                and x.look == widgets.Button.LOOKS["primary"]] if server_card else []
        if w("play.server_down") not in said or lime:
            problems.append("%s: the server card says %r with %r lime" % (name, said, lime))
        # The ready check's Server row leads to the test.
        link = [x for x in widgets_of(app.body.inner) if isinstance(x, tk.Label) and x.cget("text").startswith(
            w("check.server.test"))]
        if not link:
            problems.append("%s: the Server row does not lead to the connection test" % name)
        else:
            link[0].event_generate("<Button-1>")
        settle(app, 30, until=lambda: app.connection_test is not None and not app.connection_test["running"])
        settle(app)
        name = tag + "_online-test-moved"
        card = card_titled(app, w("test.title"))
        if app.page != "online" or card is None:
            problems.append("%s: the Server row did not open the test on the Online page" % name)
            return
        app.body.show_widget(card)
        settle(app)
        shot(app.root, out, name)
        measure(app, name, problems)
        button(app, w("test.use")).press()
        settle(app, 12, until=lambda: app.state.current == site.url)
        settle(app, 30, until=lambda: app.connection_test is not None and not app.connection_test["running"])
        # Said with the server's name, as PLAY's line names it (main named its address).
        if app.state.current != site.url or "Stand-in" not in app.status_text or site.url in app.status_text:
            problems.append("%s: Use this address left PLAY on %s (%r)" % (name, app.state.current, app.status_text))
        other_web_check(app, site, out, tag, problems, closed)
    finally:
        connection.PORTS = real_ports
        # The stand-in again for what follows, signed in as before.
        if app.state.server(before) is None:
            app.state.add_server(before, "Stand-in")
        app.state.current = before
        from opendmtq_client import actions as acts
        acts.sign_in(app.state, stub.ACCOUNT, stub.PASSWORD)
        app.state.save()
        app.connection_test = None
        app.refresh_checks(force=True)
        settle(app)


def other_web_check(app, site, out, tag, problems, closed):
    """The connection test when another web server answers where the launcher knows the server, which answers on a port
    a new server takes: the OpenDMTQ server step's longer words (wrapped beside the step's time, none cut), the verdict
    that another server answers there, and Use this address. Leaves PLAY on the stand-in, as test_check had it."""
    import http.server
    import socketserver
    import threading
    import tkinter as tk
    from opendmtq_client import connection
    w = app.words

    class Page(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            # Quiet: the suite's own output only.
            pass

        def do_GET(self):
            data = b"<!doctype html><title>It works</title>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    web = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=web.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    other = "http://127.0.0.1:%d" % web.server_address[1]
    try:
        app.state.add_server(other, "Stand-in")
        app.state.servers = [x for x in app.state.servers if x["url"] != site.url]
        connection.PORTS = (closed + 1, int(site.url.rsplit(":", 1)[1]))
        app.refresh_checks(force=True)
        app.go("online")
        settle(app)
        button(app, w("test.button")).press()
        settle(app, 30, until=lambda: app.connection_test is not None and not app.connection_test["running"])
        settle(app)
        name = tag + "_online-test-other"
        card = card_titled(app, w("test.title"))
        if card is None:
            problems.append("%s: no connection test card" % name)
            return
        app.body.show_widget(card)
        settle(app)
        shot(app.root, out, name)
        measure(app, name, problems)
        shown = [x.cget("text") for x in widgets_of(card) if isinstance(x, tk.Label) and x.winfo_ismapped()]
        for words in (w("test.verdict.moved_other", url=other, found=site.url),
                      w("test.server.not_opendmtq_moved", url=site.url)):
            if words not in shown:
                problems.append("%s: the card does not say %r" % (name, words))
        button(app, w("test.use")).press()
        settle(app, 12, until=lambda: app.state.current == site.url)
        settle(app, 30, until=lambda: app.connection_test is not None and not app.connection_test["running"])
        # Said with the server's name, as PLAY's line names it.
        if app.state.current != site.url or app.status_text != w("test.used", name=app.state.server()["name"]):
            problems.append("%s: Use this address left PLAY on %s (%r)" % (name, app.state.current, app.status_text))
    finally:
        web.shutdown()
        web.server_close()


def report_check(app, out, tag, problems):
    """Help's Save a report: the zip made under a dialog that says so, shown chosen in its folder, then a dialog that names
    it and says what was left out; the zip in the user's Downloads, under the report's name."""
    import zipfile
    from opendmtq_client import actions as acts
    w = app.words
    shown = []
    real_show = acts.show_file
    acts.show_file = lambda path: shown.append(path) or True
    try:
        app.go("help")
        settle(app)
        name = tag + "_dialog-report"
        through_dialog(app, out, name, button(app, w("help.report")).press,
                       lambda d: d.canvas.event_generate("<Return>"), problems, seconds=20.0)
        settle(app)
        made = shown[0] if shown else None
        downloads = os.path.join(os.environ["HOME"], "Downloads")
        if not made or os.path.dirname(made) != downloads or not zipfile.is_zipfile(made):
            problems.append("%s: the report was not shown in Downloads as a zip (%r)" % (name, made))
        elif not re.fullmatch(r"opendmtq-report-\d{8}-\d{6}\.zip", os.path.basename(made)):
            problems.append("%s: the report is named %r" % (name, os.path.basename(made)))
    finally:
        acts.show_file = real_show


def unnamed_check(app, out, tag, problems):
    """A server with no name of its own (a site without SERVER_NAME calls itself by its address): its address once on
    the PLAY page's card and in Help's ready check, never "192.0.2.5:8080" over "http://192.0.2.5:8080"."""
    import tkinter as tk
    import urllib.parse
    server = app.state.server()
    name, netloc = server["name"], urllib.parse.urlsplit(server["url"]).netloc
    server["name"] = netloc
    try:
        for page in ("play", "help"):
            app.go(page)
            settle(app)
            texts = [x.cget("text") for x in widgets_of(app.body.inner)
                     if isinstance(x, tk.Label) and x.winfo_ismapped()]
            said = [t for t in texts if netloc in t]
            if said != [server["url"]]:
                problems.append("%s: a server without a name is named on %s as %r" % (tag, page, said))
            if page == "play":
                shot(app.root, out, "%s_play-unnamed" % tag)
                measure(app, "%s_play-unnamed" % tag, problems)
                play_fits(app, "%s_play-unnamed" % tag, tag, problems)
    finally:
        server["name"] = name
        app.state.save()


def take_keyboard(app):
    """The window holds the keyboard, as Windows gives it to a window it opens. On the virtual screen, with no window
    manager, the keyboard goes to whatever lies under the pointer, which sits at the screen's middle (960, 600): just past
    a window 960 wide at the screen's corner, whose keys then went nowhere."""
    app.root.update()
    app.root.focus_force()
    app.root.update()


def window_size_check(app, tag, w, h, problems):
    """The window is as large as the run asked for (--size), in the screen's pixels."""
    app.root.update()
    got = (app.root.winfo_width(), app.root.winfo_height())
    if got != (w, h):
        problems.append("%s: the window is %dx%d, not the %dx%d asked for" % (tag, got[0], got[1], w, h))


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

    # The run's own window size, which the resize below leaves for a moment.
    size = (app.root.winfo_width(), app.root.winfo_height())

    def resized(dialog):
        app.root.geometry("960x640")
        wait_out(app.root, 0.6)
        shot(app.root, out, "%s_dialog-forget-960" % tag)
        problems.extend(dialog_problems(dialog, "%s_dialog-forget-960" % tag))
        if dialog.size != (app.root.winfo_width(), app.root.winfo_height()):
            problems.append("%s: the dialog was not drawn again after a resize" % tag)
    answer = through_dialog(app, out, "%s_dialog-forget-click" % tag, forget[0].press,
                            lambda d: click_button(d, 1), problems, extra=resized)
    if answer is not True or len(app.state.servers) != 1:
        problems.append("%s: clicking Forget did not forget the server (answer %r)" % (tag, answer))
    # Back at the run's own size: the dialogs after this are drawn and shot at the size their names say (they were drawn
    # at 960x640 under the run's name).
    app.root.geometry("%dx%d" % size)
    settle(app)
    if (app.root.winfo_width(), app.root.winfo_height()) != size:
        problems.append("%s: after the resize the window stayed %dx%d, not %dx%d: the dialogs after it are shot at another"
                        " size" % (tag, app.root.winfo_width(), app.root.winfo_height(), size[0], size[1]))
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
                            w("about.updating.detail"), progress=True)
    wait_out(app.root, 0.6)
    shot(app.root, out, "%s_dialog-updating" % tag)
    problems.extend(dialog_problems(dialog, "%s_dialog-updating" % tag))
    dialog.canvas.event_generate("<Escape>")
    wait_out(app.root, 0.1)
    if dialog.closed:
        problems.append("%s: Esc closed the update under way" % tag)
    dialog.close(None)
    update_failures_check(app, out, tag, problems)
    update_on_offer_check(app, out, tag, problems)


def update_on_offer_check(app, out, tag, problems):
    """The look for a newer launcher at the start, with no press: a look that fails (no network) or finds the launcher
    up to date says nothing; one that finds a newer one on the server PLAY plays on says it on the status line with its
    update while PLAY is ready, and the Launcher page shows its answer, naming the server, and its Update button without
    Check for updates. The link does what the page's button does (maintenance.update_launcher). A stand-in for the
    check answers (updates.check: what it finds is client/tests/test_updates.py's)."""
    from unittest import mock

    from opendmtq_client import actions, maintenance, updates
    w = app.words
    # What the stand-in check finds: "fail" (no network), None (up to date) or a version on offer from the server.
    feed = {"says": "fail"}

    def check(state=None):
        if feed["says"] == "fail":
            return updates.Result("failed", error="<urlopen error [Errno 11001] getaddrinfo failed>")
        if feed["says"] is None:
            return updates.Result("uptodate")
        server = app.state.server()
        return updates.Result("available", version=feed["says"], source=updates.Source("server", server["url"], server))
    # The run's own window size again (the dialogs' check made it the smallest), and PLAY ready, as a player who starts
    # the launcher finds it: signed in again on the stand-in server, the line kept from the checks before given way.
    app.root.geometry("%s+0+0" % tag.split("-", 1)[1])
    if not app.state.signed_in():
        actions.sign_in(app.state, stub.ACCOUNT, stub.PASSWORD)
        app.state.save()
    app.user_acted()
    app.update_found = None
    with mock.patch.object(updates, "check", check):
        for says in ("fail", None):
            feed["says"] = says
            app.go("play")
            app.refresh_checks(force=True)
            settle(app)
            app.look_for_update()
            wait_out(app.root, 1.0)
            settle(app)
            if app.update_found is not None or app.status_text != w("status.ready") or app.status_link.winfo_manager():
                problems.append("%s: a look at the start that %s said %r" % (
                    tag, "failed" if says else "found nothing newer", app.status_text))
        feed["says"] = "9.9.9"
        app.look_for_update()
        end = time.time() + 5
        while app.update_found is None and time.time() < end:
            app.root.update()
            time.sleep(0.02)
        settle(app)
        shot(app.root, out, "%s_play-update" % tag)
        measure(app, "%s_play-update" % tag, problems)
        play_fits(app, "%s_play-update" % tag, tag, problems)
        link = app.status_link.cget("text") if app.status_link.winfo_manager() else None
        if app.status_text != w("about.available", v="9.9.9") or not (link or "").startswith(
                w("about.update_now", v="9.9.9")):
            problems.append("%s: a newer launcher at the start made the status line say %r, its link %r"
                            % (tag, app.status_text, link))
        # The link starts the Launcher page's own update, and nothing else does.
        pressed = []
        with mock.patch.object(maintenance, "update_launcher", lambda app_, result: pressed.append(result.version)):
            if app.status_link.odq_action:
                app.status_link.odq_action()
        if pressed != ["9.9.9"]:
            problems.append("%s: the status line's update started %r" % (tag, pressed))
        app.go("about")
        settle(app)
        shot(app.root, out, "%s_about-update" % tag)
        measure(app, "%s_about-update" % tag, problems)
        try:
            button(app, w("about.update_now", v="9.9.9"))
        except AssertionError:
            problems.append("%s: the Launcher page shows no update for the newer launcher found at the start" % tag)
        # Its answer names the server it comes from.
        import tkinter as tk
        named = w("about.available.from", v="9.9.9", source=updates.Source("server", app.state.server()["url"],
                                                                           app.state.server()).label())
        if named not in [x.cget("text") for x in widgets_of(app.root) if isinstance(x, tk.Label)]:
            problems.append("%s: the Launcher page does not name the server the update comes from" % tag)
    app.update_found = None
    app.go("play")
    settle(app)


def update_failures_check(app, out, tag, problems):
    """The Launcher page's update when it fails, said in the page's language, the system's own words in the log only: a
    check with no network (as Windows says it), a release its project did not sign (refused, in the colour of a fault),
    then an update whose download finds the disk full. Stand-ins for the check and the update answer (updates.check and
    apply: what they do is client/tests/test_updates.py's)."""
    import tkinter as tk
    from unittest import mock

    from opendmtq_client import theme, updates
    w = app.words
    said = {"check": "fail"}
    server = app.state.server()
    source = updates.Source("server", server["url"], server)

    def check(state=None):
        if said["check"] == "fail":
            return updates.Result("failed", error="<urlopen error [Errno 11001] getaddrinfo failed>")
        if said["check"] == "refused":
            return updates.Result("refused", error="opendmtq-9.9.9-sha256sums.txt is not signed by the OpenDMTQ project",
                                  source=source)
        return updates.Result("available", version="9.9.9", source=source)

    def apply(result, tell=None, run=None):
        try:
            raise OSError(28, "There is not enough space on the disk. (os error 112)")
        except OSError as e:
            raise updates.UpdateError("the update to 9.9.9 could not be downloaded", "error.update.download",
                                      v="9.9.9") from e

    with mock.patch.object(updates, "check", check), mock.patch.object(updates, "apply", apply):
        app.go("about")
        settle(app)
        button(app, w("about.check")).press()
        expected = w("about.update_failed") + " " + w("fault.network")
        end = time.time() + 5
        while time.time() < end and not any(isinstance(x, tk.Label) and x.cget("text") == expected
                                            for x in widgets_of(app.root)):
            app.root.update()
            time.sleep(0.02)
        shot(app.root, out, "%s_about-update-offline" % tag)
        measure(app, "%s_about-update-offline" % tag, problems)
        texts = [x.cget("text") for x in widgets_of(app.root) if isinstance(x, tk.Label)]
        if expected not in texts or any("os error" in t or "Errno" in t for t in texts):
            problems.append("%s: a check with no network said %r" % (tag, [t for t in texts if "update" in t.lower()
                                                                          or "업데이트" in t]))
        # A release its project did not sign: refused, the fact said in the colour of a fault.
        said["check"] = "refused"
        button(app, w("about.check")).press()
        expected = w("about.refused", source=source.label())
        end = time.time() + 5
        while time.time() < end and not any(isinstance(x, tk.Label) and x.cget("text") == expected
                                            for x in widgets_of(app.root)):
            app.root.update()
            time.sleep(0.02)
        shot(app.root, out, "%s_about-update-refused" % tag)
        measure(app, "%s_about-update-refused" % tag, problems)
        refused = [x for x in widgets_of(app.root) if isinstance(x, tk.Label) and x.cget("text") == expected]
        if not refused or refused[0].cget("fg") != theme.BAD:
            problems.append("%s: a refused update said %r" % (tag, [x.cget("text") for x in widgets_of(app.root)
                                                                     if isinstance(x, tk.Label) and "OpenDMTQ" in x.cget("text")]))
        # Then one on offer, whose download finds the disk full: the dialog says so in plain words.
        said["check"] = None
        button(app, w("about.check")).press()
        end = time.time() + 5
        while time.time() < end:
            try:
                update = button(app, w("about.update_now", v="9.9.9"))
                break
            except AssertionError:
                app.root.update()
                time.sleep(0.02)
        else:
            problems.append("%s: the update on offer showed no button" % tag)
            return
        failed = next_dialog(app, out, "%s_dialog-update-failed" % tag, problems,
                             lambda d: not d.progress and d.message == w("about.apply_failed"),
                             lambda d: d.canvas.event_generate("<Return>"))
        update.press()
        wait_out(app.root, 2.0)
        dialog = failed.get("dialog")
        if dialog is None or dialog.detail != w("error.update.download", v="9.9.9") + " " + w("fault.disk_full"):
            problems.append("%s: a full disk during the update said %r" % (tag, dialog and dialog.detail))


def page_shorter_check(app, tag, problems):
    """A page at its foot that gets shorter for good (a card gone) still ends at its foot once it has settled: the page
    area waits a moment before it shrinks under the view (a page made anew in part is short only for a moment), and
    shrinks then. Help drawn again after it."""
    area = app.body
    area.canvas.yview_moveto(1.0)
    settle(app)
    cards = [c for c in widgets_of(area.inner) if isinstance(c, widgets.Card)]
    # The last card gone with what holds it on the page (pages.Sections keeps each card in a holder of its own).
    content = area.inner.winfo_children()[0]
    gone = cards[-1] if cards[-1].master is content else cards[-1].master
    gone.destroy()
    wait_out(app.root, 0.5)
    region = [float(v) for v in str(area.canvas.cget("scrollregion")).split()]
    seen = area.canvas.winfo_height()
    content = area._content_top + area.inner.winfo_reqheight() + app.ui.px(area.BOTTOM)
    if abs(region[3] - max(seen, content)) > 1 or abs(area.canvas.canvasy(0) + seen - region[3]) > 1:
        problems.append("%s: a page shorter for good ends at %d, its view at %d" % (tag, region[3],
                                                                                    area.canvas.canvasy(0) + seen))
    app.go("help")
    settle(app)


def game_end_check(app, out, tag, problems):
    """A game that ends with Help on show: at once, before the ready check comes back (made slow here, as with the
    server away), PLAY is no longer PLAYING and Help shows the game's log (its row, and the line that points at it)."""
    import tkinter as tk

    from opendmtq_client import actions
    w = app.words
    app.go("help")
    settle(app)
    seen, slow = {}, {"on": False}
    real_readiness = actions.readiness

    def readiness(*args, **kw):
        # A check started after the game: three seconds, as a server that does not answer keeps the window waiting.
        if slow["on"]:
            time.sleep(3)
        return real_readiness(*args, **kw)

    real_watch = app._watch

    def watch():
        real_watch()
        if app.session is None and "after" not in seen:
            # The moment the game has ended: what PLAY and the page say before the slow check answers.
            texts = [x.cget("text") for x in widgets_of(app.root) if isinstance(x, tk.Label) and x.winfo_exists()]
            seen["after"] = (app.play_button.state, app.checks is None, texts)

    actions.readiness, app._watch = readiness, watch
    try:
        app.play()
        end = time.time() + 15
        while time.time() < end and app.session is None:
            app.root.update()
            time.sleep(0.02)
        slow["on"] = True
        while time.time() < end and "after" not in seen:
            app.root.update()
            time.sleep(0.02)
        wait_out(app.root, 0.4)
        shot(app.root, out, "%s_help-after-game" % tag)
    finally:
        actions.readiness, app._watch = real_readiness, real_watch
    if "after" not in seen:
        problems.append("%s: the game did not end in the window" % tag)
        return
    state, waiting, texts = seen["after"]
    if state == "playing" or not waiting:
        problems.append("%s: when the game ended PLAY was %r (ready check back: %r)" % (tag, state, not waiting))
    if w("help.player_log") not in texts:
        problems.append("%s: when the game ended Help did not show its log: %r" % (tag, [t for t in texts if t][:12]))
    settle(app, 8)


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
        problems.extend(dialog_problems(dialog, name))
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
    # The work under way, as the dialogs show it, with the line under it that says what comes of it.
    from opendmtq_client import maintenance as tools
    for key in ("help.repair.working", "help.uninstall.working", "help.counting"):
        detail = w(tools.WORKING_DETAIL[key]) if key in tools.WORKING_DETAIL else None
        dialog = dialogs.Dialog(app.root, app.ui, "info", w(key), w(key), detail=detail, progress=True)
        wait_out(app.root, 0.6)
        shot(app.root, out, "%s_dialog-%s" % (tag, key.replace(".", "-")))
        problems.extend(dialog_problems(dialog, "%s_dialog-%s" % (tag, key)))
        dialog.close(None)
    # Repair with a file of the launcher missing: put back, and said to need a restart. The page at its foot first, where
    # the tools are: the ready check that comes back after the repair leaves it there. Help taller than the window has a
    # foot below its top; at 1600x1000 it shows whole, and stays at its top.
    os.remove(os.path.join(install, "current", "OpenDMTQ.exe"))
    app.body.canvas.yview_moveto(1.0)
    settle(app)
    before = app.body.canvas.canvasy(0)
    # Whether the page reaches past its view (the page area's scroll region is the page, or the view when it is shorter).
    tall = float(str(app.body.canvas.cget("scrollregion")).split()[3]) > app.body.canvas.winfo_height() + 1
    done = next_dialog(app, out, "%s_dialog-repaired" % tag, problems, lambda d: not d.progress,
                       lambda d: d.canvas.event_generate("<Return>"))
    button(app, w("help.repair")).press()
    wait_out(app.root, 2.0)
    settle(app)
    dialog = done.get("dialog")
    # One file put back, the launcher's own: said as one (main: "Files put back: 1. Some are the launcher's own", and
    # no words of their own for one file, which this check then finds missing rather than stopping at).
    from opendmtq_client import i18n
    one = w("help.repair.done.restart.one") if "help.repair.done.restart.one" in i18n.TEXT else None
    if dialog is None or one is None or dialog.detail != one:
        problems.append("%s: the repair said %r" % (tag, dialog and dialog.detail))
    if not os.path.isfile(os.path.join(install, "current", "OpenDMTQ.exe")):
        problems.append("%s: the repair did not put the launcher's file back" % tag)
    if (tall and before <= 0) or abs(app.body.canvas.canvasy(0) - before) > 1:
        problems.append("%s: closing the repair's answer moved Help from %d px to %d" % (tag, before,
                                                                                         app.body.canvas.canvasy(0)))
    page_shorter_check(app, tag, problems)
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
    from opendmtq_client import dialogs, i18n, stopped
    w = i18n.Words(lang)
    error = OSError(28, "No space left on device", "C:\\Users\\player\\AppData\\Local\\OpenDMTQ\\client\\settings.json")
    # The window stopped.show opens, its buttons too (Open the log folder, then Close).
    root, dialog = dialogs.window(*stopped.dialog(w, error,
                                                  "C:\\Users\\player\\AppData\\Local\\OpenDMTQ\\client\\logs\\launcher.log"),
                                  language=lang)
    wait_out(root, 1.0)
    shot(root, out, "%s_stopped" % tag)
    problems.extend(dialog_problems(dialog, "%s_stopped" % tag))
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
    problems.extend(dialog_problems(dialog, "%s_cannot-start" % tag))
    dialog.canvas.event_generate("<Escape>")
    root.update()
    if not dialog.closed or dialog.result != "close":
        problems.append("%s: Esc did not answer the start-up dialog (closed %r, answer %r)"
                        % (tag, dialog.closed, dialog.result))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--size", default="1180x760")
    args = parser.parse_args()
    global FIELD_OUT
    FIELD_OUT = args.out
    if not safety.on_virtual_display():
        sys.exit("refusing: this opens windows; run it through client/tests/ui/run.sh")
    os.makedirs(args.out, exist_ok=True)
    # The collector runs on the window's thread only (collect(), at each settle()), never in a worker thread's middle.
    import gc
    gc.disable()
    home = tempfile.mkdtemp()
    os.environ["HOME"] = home
    # The user's Downloads, where Help's Save a report puts the zip, as Windows has it.
    os.makedirs(os.path.join(home, "Downloads"))
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
    # The launcher's log kept here, every line of it, to look for what it should say.
    logging.getLogger("opendmtq_client").addHandler(Kept())
    logging.getLogger("opendmtq_client").setLevel(logging.INFO)
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
    take_keyboard(app)
    import traceback

    def callback_error(kind, value, tb):
        problems.append("callback error: %s" % "".join(traceback.format_exception_only(kind, value)).strip())
        traceback.print_exception(kind, value, tb)

    app.root.report_callback_exception = callback_error
    guide = guide_check(app, site, args.out, tag, problems)
    guide.finish(play=False)
    settle(app)
    # The window at the size asked, on a screen at this run's scaling: a screen that reads another number of dots to the
    # inch scales the launcher, and the smallest window then is no longer the smallest the launcher allows.
    window_size_check(app, tag, w, h, problems)
    pages_check(app, args.out, tag, problems)
    # PLAY's records and My page on the site, signed in after the guide; Help's Save a report.
    records_check(app, site, args.out, tag, problems)
    report_check(app, args.out, tag, problems)
    # The connection test on the Online page, and from PLAY's Server row when the server does not answer.
    test_check(app, site, args.out, tag, problems)
    # The Sound page's Last game card, before a game and after one with and without gaps.
    sound_last_check(app, args.out, tag, problems)
    # Keyboard play on the Controls page, its states and its keys.
    keys_check(app, args.out, tag, problems)
    # Online's address field after a failed Connect, as the guide's SERVER step above.
    app.go("online")
    settle(app)
    typed_address_check(app, args.out, "%s_online" % tag, problems, site.url)
    wheel_bindings_check(app, problems)
    variants_check(app, site, args.out, tag, problems)
    app.root.geometry("%dx%d+0+0" % (w, h))
    settle(app)
    dialogs_check(app, args.out, tag, problems)
    # Last of the window's checks: the game it starts makes the player's log, which the clearing above would count. Signed
    # in as the dialogs' check leaves it: PLAY's records are asked for again once the game has ended, wherever it ends.
    asked = lambda: sum(1 for r in site.requests if r[1] == "/opendmtq/client.php?records")  # noqa: E731
    before = asked()
    game_end_check(app, args.out, tag, problems)
    settle(app, 8, until=lambda: asked() > before)
    if not app.state.signed_in() or asked() <= before:
        problems.append("%s: PLAY's records were not asked for again after a game (signed in: %r)"
                        % (tag, app.state.signed_in()))
    # Jobs the window still has waiting would fire into the next window's event loop once it is gone.
    for job in app.root.tk.splitlist(app.root.tk.call("after", "info")):
        app.root.after_cancel(job)
    app.root.destroy()
    standalone_check(args.out, tag, args.lang, problems)
    stopped_check(args.out, tag, args.lang, problems)
    # The installer in this language (Windows' display language, with no launcher installed yet).
    # The installer's window is measured by tests/ui/setup_shots.py.
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
