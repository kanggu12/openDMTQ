"""The launcher's design as a person sees it, measured on the screen against what its design decides: how a page's
cards are composed, the roles of its words, its buttons, and the page's own picture round the cards.

- composition: where two columns of cards fit, a page never shows three or more cards all at the column's full width
  one under another (a plain list of boxes); no card holds a single control with at most one line of words beside it
  (a box for one button), nor one setting's row alone (its name and its description are the row's own).
- text: every label in one of the type scale's fonts; a heading (a card's title, the first label over a group) never
  smaller than the words it heads; a button's words on its middle by the ink of their capitals, or of their Hangul
  syllables, within half a pixel.
- buttons: each role one height everywhere (the pages' and the dialogs' alike), as wide as its words and the same room
  either side, never stretched.
- background: no shard of the page's picture within SHARD_CLEAR of the content column under the page's heading, or of
  any card, anywhere down the page (the shards scroll with the cards: the page's own coordinates hold at every scroll
  position), nor of the window's own buttons; no edge of the lit top's panes under the page's heading.
- surfaces: each card's surface and silhouette by its role: a card that reports a state with its title on a header
  strip, a result with its foot's corner cut too, About a step deeper without the light along its top, the page's head
  (the hero) a step nearer with a brighter light and deeper cuts, every other card the deck with its top-right corner
  cut, the calm reading surface of settings.

shots.py runs it on every screen and state it shows, at every size and in both languages; setup_shots.py on the
installer's pages; the dialogs' part on every dialog it opens. It reads the widgets' places and fonts from Tk, never
from the code that put them there.

  problems = design.check(root, ui, name)          (a list of words, empty when all is well)
  problems = design.check_dialog(dialog, name)
"""

import os
import tkinter as tk
import tkinter.font as tkfont

from opendmtq_client import art, theme, widgets

# Two columns of cards where the page's content column is at least this wide (logical pixels): the launcher's default
# window and every larger one.
TWO_COLUMNS = 760
# A plain list: this many cards or more, every one of them as wide as the column, one under another.
PLAIN_LIST = 3
# A box for one control: a card whose own content (its title and the actions at its title's right end aside) is one
# control and at most this many lines of words.
LONE_WORDS = 1
# The room a shard keeps from the content column under the heading, and from every card (logical pixels).
SHARD_CLEAR = 16
# A shard's pixel counts from this much of its light (of 255): fainter, it does not show on the field.
SHARD_SEEN = 4
# The room either side of a button's words (logical pixels), the same for every button.
BUTTON_SIDE = 18
# Each role's height (logical pixels): the main action, a plain one, one that removes, the window's own icons, PLAY.
ROLE_HEIGHT = {"main": 36, "plain": 36, "danger": 36, "icon": 32, "play": 50}
# How far a button's words may stand from its middle (pixels of the screen): half a pixel, the least the eye sees.
CENTRE_SLACK = 0.5
# A pixel either way: Tk rounds a scaled size to whole pixels.
SLACK = 1
# A slider's least length (logical pixels): a volume's (0 to 100), and a range of few steps' (an equaliser's band).
SLIDER_LEAST, BAND_LEAST = 200, 150
# The cards that report a state, by their titles' words (the words' keys): each a status panel, its title and its
# state on a header strip of theme.STRIP_HEAD across the card.
STATUS_PANELS = ("play.ready", "help.checks", "play.last", "play.records", "test.title")
# Of those, the results: their foot's corner cut too, as deep as the top one (the diagonal pair a game's panels have).
RESULTS = ("play.last", "play.records")
# A quiet card, by its title: theme.QUIET, a step deeper than the deck, and no light along its top.
QUIET_CARDS = ("about.legal",)
# Of the status panels, the ones that report a list of checks as a whole: their state's light on their strip, before the
# title (the ready check's; the connection test had none).
STATE_LIGHTS = ("play.ready", "help.checks", "test.title")
# A card's cut corner (logical pixels), and the page's head's two: its top one and its foot's.
CUT, HERO_CUTS = 16, (24, 12)


# ----------------------------------------------------------------------------------------------------- the widgets

def _all(root):
    """Every widget under `root` (root first), without recursion."""
    found, stack = [], [root]
    while stack:
        widget = stack.pop()
        found.append(widget)
        try:
            stack.extend(widget.winfo_children())
        except tk.TclError:
            # Gone while the screen was read.
            continue
    return found


def _mapped(widget):
    """Whether the widget is on the screen (shown, and every frame round it shown too)."""
    try:
        return bool(widget.winfo_ismapped() and widget.winfo_viewable())
    except tk.TclError:
        return False


def _inside(widget, outer):
    """Whether `outer` is round `widget`."""
    parent = widget.master
    while parent is not None:
        if parent is outer:
            return True
        parent = parent.master
    return False


def _is_control(widget):
    """Whether a widget is one control a person works (a button, a field, a key's box, a switch, a row of tabs, a
    slider, a drop-down, words that act): counted once, whatever it is made of."""
    if isinstance(widget, (widgets.Button, widgets.Field, widgets.KeyBox, widgets.Toggle, widgets.Segmented,
                           widgets.Slider)):
        return True
    if getattr(widget, "odq_button", False):
        # Any other that says it is one (the installer's window buttons).
        return True
    try:
        if widget.winfo_class() == "TCombobox":
            return True
        # Words that act (a link: the pointer's hand over it, and the keyboard reaches it).
        return isinstance(widget, tk.Label) and str(widget.cget("cursor")) == "hand2" and \
            str(widget.cget("takefocus")) not in ("", "0")
    except tk.TclError:
        return False


def _controls_and_words(top, leave_out=()):
    """The controls under `top` and its labels of words that are no part of a control, each on the screen; widgets
    under any of `leave_out` are not counted."""
    controls, words = [], []
    stack = [top]
    while stack:
        widget = stack.pop()
        try:
            children = widget.winfo_children()
        except tk.TclError:
            continue
        for child in children:
            if child in leave_out or not _mapped(child):
                continue
            if _is_control(child):
                # One control, whatever it holds (a slider's number, a field's entry, a password's Show).
                controls.append(child)
                continue
            if isinstance(child, tk.Label) and str(child.cget("text")).strip():
                words.append(child)
            stack.append(child)
    return controls, words


def _page_areas(root):
    """The page areas on the screen (the launcher's page, the guide's step, the installer's page)."""
    return [w for w in _all(root) if isinstance(w, widgets.ScrollArea) and _mapped(w)]


def _cards(area):
    """The cards of a page area's page, the ones on the screen, in their order down the page (a card in another card
    is part of it)."""
    found = [w for w in _all(area.inner) if isinstance(w, widgets.Card) and w.winfo_ismapped()
             and not any(isinstance(a, widgets.Card) for a in _ancestors(w, area.inner))]
    return sorted(found, key=lambda card: (card.winfo_rooty(), card.winfo_rootx()))


def _ancestors(widget, stop):
    """The widgets round `widget` up to `stop` (not counted)."""
    found, parent = [], widget.master
    while parent is not None and parent is not stop:
        found.append(parent)
        parent = parent.master
    return found


def _title(card):
    """A card's title label (the first label of its head), or None."""
    head = getattr(card, "head", None)
    if head is None:
        return None
    return next((x for x in head.winfo_children() if isinstance(x, tk.Label) and str(x.cget("text")).strip()), None)


# --------------------------------------------------------------------------------------------------- composition

def composition(root, ui, name):
    """No plain list of full-width boxes where two columns fit; no card for a single control."""
    problems = []
    for area in _page_areas(root):
        column = area.inner.winfo_width()
        cards = _cards(area)
        if column >= ui.px(TWO_COLUMNS) and len(cards) >= PLAIN_LIST:
            # As wide as the column: within a pixel of it.
            full = [card for card in cards if card.winfo_width() >= column - SLACK]
            if len(full) == len(cards):
                problems.append("%s: a plain list of %d full-width cards (%s)" % (
                    name, len(cards), ", ".join(_said(card) for card in cards)))
        for card in cards:
            # Its own content: its body, less its head (the title and the actions at the title's right end).
            head = getattr(card, "head", None)
            controls, words = _controls_and_words(card.body, leave_out=(head,) if head is not None else ())
            if len(controls) == 1 and len(words) <= LONE_WORDS:
                problems.append("%s: the card %s holds a single control (%s)%s" % (
                    name, _said(card), _said(controls[0]),
                    " and the words %r" % str(words[0].cget("text"))[:40] if words else ""))
            # The card's title said once: no row's name in it says it again (the guide's DOWNLOAD and SIGN IN cards were
            # titled The server's app and Signed in over a row of the same name).
            title = _title(card)
            if title is not None:
                again = [w for w in words if w is not title and str(w.cget("text")) == str(title.cget("text"))]
                if again:
                    problems.append("%s: the card %s says its title again in its rows" % (name, _said(card)))
            # A setting's row is one setting, its name and its description its own: a card that holds one such row and
            # nothing else is a box for one setting (main let the Controls page's card of the switch alone pass, and
            # the guide's card of the display's mode alone, by counting the row's name as a second line).
            rows = [w for w in _all(card.body) if _is_setting_row(w) and _mapped(w)]
            if len(rows) == 1:
                outside = [w for w in controls + words if not _inside(w, rows[0])]
                if not outside:
                    problems.append("%s: the card %s holds a single setting (%s)" % (
                        name, _said(card), _said(rows[0].control)))
    return problems


def _is_setting_row(widget):
    """Whether a widget is a setting's row (widgets.setting_row: its name, its control, the description it says under
    them), read from what the row keeps: its control, its description and the way it says another."""
    return all(hasattr(widget, name) for name in ("odq_names", "control", "hint", "say"))


def _said(widget):
    """A widget as a person would point at it, for the problems' words."""
    if isinstance(widget, widgets.Card):
        title = _title(widget)
        if title is not None:
            return repr(str(title.cget("text"))[:30])
        _controls, words = _controls_and_words(widget.body)
        return "without a title (%r)" % (str(words[0].cget("text"))[:30] if words else "")
    words = getattr(widget, "words", None)
    if isinstance(words, str):
        return "%s %r" % (type(widget).__name__, words[:30])
    try:
        text = str(widget.cget("text"))
    except tk.TclError:
        text = ""
    return "%s %r" % (type(widget).__name__, text[:30]) if text else type(widget).__name__


# ---------------------------------------------------------------------------------------------------------- text

# The fonts' files, by Tk's family and weight, to measure the ink of their letters as Tk draws them.
FONT_FILES = {("Pretendard", "normal"): "Pretendard-Regular.ttf", ("Pretendard", "bold"): "Pretendard-Bold.ttf",
              ("Pretendard SemiBold", "normal"): "Pretendard-SemiBold.ttf",
              ("Pretendard SemiBold", "bold"): "Pretendard-SemiBold.ttf",
              ("DMTQ Wide", "normal"): "DMTQWide-ExtraBold.ttf", ("DMTQ Wide", "bold"): "DMTQWide-ExtraBold.ttf"}
# Measured with the font file drawn this many times larger, then scaled back: a fortieth of a pixel is seen.
INK_SCALE = 40
# The ink bands measured so far: (file, size in pixels, kind) -> (top, bottom) from the baseline.
_bands = {}


def _font(widget, option="font", item=None):
    """The Tk font of a label (or a canvas's text item), as a Font object."""
    spec = widget.itemcget(item, "font") if item is not None else widget.cget(option)
    try:
        return tkfont.nametofont(str(spec))
    except tk.TclError:
        return tkfont.Font(widget, font=spec)


def _px(font, widget):
    """A font's em in pixels on this screen (its size in points, or in pixels when negative)."""
    size = float(font.actual("size"))
    return size * widget.winfo_fpixels("1p") if size > 0 else -size


def _band(font, widget, words):
    """Where the ink of `words` that the eye centres on lies, from the baseline down (top, bottom), in pixels: the
    capitals' height for Latin letters and figures (the font's own cap height), the syllables' ink for Hangul, the
    ink itself for words of neither (a +)."""
    from PIL import ImageFont
    actual = font.actual()
    path = os.path.join(theme.FONT_DIR, FONT_FILES.get((actual["family"], actual["weight"]), "Pretendard-Regular.ttf"))
    em = _px(font, widget)
    hangul = "".join(ch for ch in words if "가" <= ch <= "힣")
    latin = any(ch.isascii() and ch.isalnum() for ch in words)
    kind = "hangul" if hangul and not latin else ("caps" if latin else "ink")
    # Kept by what was measured: the capitals' band is the face's own, the syllables' and the ink's the words' own.
    key = (path, round(em, 3), kind, hangul if kind == "hangul" else words if kind == "ink" else "")
    if key not in _bands:
        big = ImageFont.truetype(path, em * INK_SCALE)
        if kind == "caps":
            from fontTools.ttLib import TTFont
            face = TTFont(path)
            cap = face["OS/2"].sCapHeight / float(face["head"].unitsPerEm)
            _bands[key] = (-cap * em, 0.0)
        else:
            box = big.getbbox(hangul or words, anchor="ls")
            _bands[key] = (box[1] / INK_SCALE, box[3] / INK_SCALE)
    return _bands[key]


def _canvas_text_middle(canvas, item):
    """The middle of a canvas text item's eye band (_band) on the canvas, in its pixels."""
    font = _font(canvas, item=item)
    box = canvas.bbox(item)
    # Tk lays a line of text out from its top: the baseline is its ascent under the box's top.
    baseline = box[1] + font.metrics("ascent")
    top, bottom = _band(font, canvas, canvas.itemcget(item, "text"))
    return baseline + (top + bottom) / 2.0


def text(root, ui, name):
    """The type scale's fonts only; no heading smaller than what it heads; buttons' words on their middles."""
    problems = []
    fonts = {str(getattr(ui.fonts, n)) for n in dir(ui.fonts) if isinstance(getattr(ui.fonts, n), tkfont.Font)}
    labels = [w for w in _all(root) if isinstance(w, tk.Label) and _mapped(w) and str(w.cget("text")).strip()]
    for label in labels:
        if str(label.cget("font")) not in fonts:
            problems.append("%s: the words %r are in a font of no role (%s)" % (
                name, str(label.cget("text"))[:40], label.cget("font")))
    problems.extend(_headings(root, name))
    problems.extend(_buttons_centred(root, ui, name))
    problems.extend(_lines(root, name))
    return problems


def _edge(label):
    """What a label keeps above its words: its border, its padding and its keyboard ring (pixels)."""
    return sum(int(label.winfo_fpixels(str(label.cget(o)))) for o in ("borderwidth", "pady", "highlightthickness"))


def _lines(root, name):
    """On a card's line, words beside words stand on one baseline (their first lines), and a lamp beside words on their
    first line's middle, within a pixel: a step's name and what it found, a value by its name, a state's lamp by its
    words, a status panel's light by its title on its strip. Measured card by card, between labels whose first lines
    share the card's height."""
    problems = []
    for card in [w for w in _all(root) if isinstance(w, widgets.Card) and _mapped(w)]:
        texts, lamps = [], []
        for w in _all(card):
            if not isinstance(w, tk.Label) or not _mapped(w):
                continue
            if w.winfo_manager() == "place":
                # A picture laid over a corner (a cut), never one that leads a line.
                continue
            if any(_is_control(a) for a in _ancestors(w, card)):
                # Part of a control (a password's Show inside its field): the control's own, measured with it.
                continue
            if str(w.cget("text")).strip() and not str(w.cget("image")):
                font = _font(w)
                top = w.winfo_rooty() + _edge(w)
                # The first line's box: its top, its baseline and its foot.
                texts.append((w, top, top + font.metrics("ascent"), top + font.metrics("linespace")))
            elif str(w.cget("image")) and not str(w.cget("text")).strip() \
                    and w.winfo_height() < 3 * _font(w).metrics("linespace"):
                # A small picture without words that leads a line: a state's lamp, the keyboard's mark.
                lamps.append(w)
        for i, (a, top_a, base_a, foot_a) in enumerate(texts):
            for b, top_b, base_b, foot_b in texts[i + 1:]:
                beside = a.winfo_rootx() + a.winfo_width() <= b.winfo_rootx() or \
                    b.winfo_rootx() + b.winfo_width() <= a.winfo_rootx()
                # On one line: side by side, their first lines' boxes sharing some of their height (rows of a card
                # stand apart by a hairline's room, so words of two rows never share any).
                shared = min(foot_a, foot_b) - max(top_a, top_b)
                if beside and shared > 0 and abs(base_a - base_b) >= 1:
                    problems.append("%s: the words %r and %r beside them stand on baselines %d px apart" % (
                        name, str(a.cget("text"))[:30], str(b.cget("text"))[:30], abs(base_a - base_b)))
        for lamp in lamps:
            middle = lamp.winfo_rooty() + lamp.winfo_height() / 2.0
            for w, top, base, foot in texts:
                beside = lamp.winfo_rootx() + lamp.winfo_width() <= w.winfo_rootx()
                near = w.winfo_rootx() - (lamp.winfo_rootx() + lamp.winfo_width()) < 3 * (foot - top)
                if beside and near and top - 1 <= middle <= foot + 1 and abs(middle - (top + foot) / 2.0) > 1:
                    problems.append("%s: a lamp stands %.1f px off the middle of %r beside it" % (
                        name, middle - (top + foot) / 2.0, str(w.cget("text"))[:30]))
    return problems


def _size_of(widget):
    """The font size (points) of a label, or the largest of a canvas's text items; None for neither."""
    try:
        if isinstance(widget, tk.Label) and str(widget.cget("text")).strip():
            return abs(float(_font(widget).actual("size")))
        if isinstance(widget, tk.Canvas):
            sizes = [abs(float(_font(widget, item=i).actual("size"))) for i in widget.find_all()
                     if widget.type(i) == "text" and str(widget.itemcget(i, "text")).strip()
                     and widget.itemcget(i, "state") != "hidden"]
            return max(sizes) if sizes else None
    except tk.TclError:
        return None
    return None


def _figure(widget):
    """Whether a label's words are a figure (the game's wide face: a result's length, a score): figures have a role of
    their own, as large as a result asks, and head nothing."""
    try:
        return isinstance(widget, tk.Label) and "Wide" in _font(widget).actual("family") and \
            any(ch.isdigit() for ch in str(widget.cget("text")))
    except tk.TclError:
        return False


def _largest_under(widget):
    """The largest font size (points) of any words under `widget`, itself counted, figures aside (_figure)."""
    sizes = [s for s in (_size_of(w) for w in _all(widget) if _mapped(w) and not _figure(w)) if s is not None]
    return max(sizes) if sizes else None


def _below(heading):
    """What stands under a heading in its container: the widgets packed after it down the container, or gridded in the
    rows under it; [] when it heads nothing (a name beside its control)."""
    parent = heading.master
    try:
        if heading.winfo_manager() == "grid":
            row = int(heading.grid_info()["row"])
            return [w for w in parent.grid_slaves() if int(w.grid_info()["row"]) > row and _mapped(w)]
        if heading.winfo_manager() == "pack":
            slaves = parent.pack_slaves()
            if heading.pack_info().get("side", "top") != "top":
                return []
            index = slaves.index(heading)
            return [w for w in slaves[index + 1:] if _mapped(w) and w.pack_info().get("side", "top") == "top"]
    except (tk.TclError, ValueError):
        return []
    return []


def _headings(root, name):
    """A card's title not smaller than anything its card holds; the first label over a group (in a heading's face:
    bold, semibold, or the wide face) not smaller than the words in the group."""
    problems = []
    for card in [w for w in _all(root) if isinstance(w, widgets.Card) and _mapped(w)]:
        title = _title(card)
        if title is None:
            continue
        size = _size_of(title)
        rest = [w for w in card.body.winfo_children() if w is not card.head and _mapped(w)]
        largest = max([s for s in (_largest_under(w) for w in rest) if s is not None] or [0])
        if size is not None and largest > size:
            problems.append("%s: the card %r has words larger (%g pt) than its title (%g pt)" % (
                name, str(title.cget("text"))[:30], largest, size))
    # The cards' titles are measured above, against their whole cards.
    titles = {_title(card) for card in _all(root) if isinstance(card, widgets.Card)}
    heading_faces = ("bold", "semibold", "wide")
    for label in [w for w in _all(root) if isinstance(w, tk.Label) and _mapped(w) and str(w.cget("text")).strip()]:
        actual = _font(label).actual()
        face = "wide" if "Wide" in actual["family"] else ("semibold" if "SemiBold" in actual["family"] else
                                                           actual["weight"])
        if face not in heading_faces or label in titles:
            continue
        under = _below(label)
        if not under:
            continue
        # Only the first in its container heads it: a label after others is a row of the group, not its heading.
        try:
            first = label.winfo_manager() == "grid" and int(label.grid_info()["row"]) == 0 or \
                label.winfo_manager() == "pack" and label.master.pack_slaves()[0] is label
        except (tk.TclError, IndexError):
            first = False
        if not first:
            continue
        size = _size_of(label)
        largest = max([s for s in (_largest_under(w) for w in under) if s is not None] or [0])
        if size is not None and largest > size:
            problems.append("%s: the heading %r (%g pt) is smaller than the words under it (%g pt)" % (
                name, str(label.cget("text"))[:30], size, largest))
    return problems


def _buttons_centred(root, ui, name):
    """Each button's and each tab's words on its face's middle (_band), within CENTRE_SLACK."""
    problems = []
    for widget in [w for w in _all(root) if _mapped(w)]:
        if isinstance(widget, widgets.Button):
            # The face is the whole canvas; its words are its text item.
            middle = widget.winfo_height() / 2.0
            for item in getattr(widget, "parts", ()):
                if widget.type(item) == "text":
                    off = _canvas_text_middle(widget, item) - middle
                    if abs(off) > CENTRE_SLACK:
                        problems.append("%s: the button %r has its words %.2f px %s its middle" % (
                            name, widget.words, abs(off), "under" if off > 0 else "over"))
        elif isinstance(widget, widgets.Segmented):
            # Each tab's face is the row's height less the rule under it.
            middle = ui.px(widgets.Segmented.HEIGHT) / 2.0
            for item in widget.words:
                off = _canvas_text_middle(widget.canvas, item) - middle
                if abs(off) > CENTRE_SLACK:
                    problems.append("%s: the tab %r has its words %.2f px %s its middle" % (
                        name, widget.canvas.itemcget(item, "text"), abs(off), "under" if off > 0 else "over"))
    return problems


# ------------------------------------------------------------------------------------------------------- buttons

def _role(button):
    """A button's role (ROLE_HEIGHT) by its look."""
    return {"home": "main", "neutral": "plain", "danger_quiet": "danger", "danger": "main"}.get(button.look, "plain")


def buttons(root, ui, name):
    """Every button of its role's height, as wide as its words and the same room either side, never stretched; every
    slider long enough for its range."""
    problems = []
    for widget in [w for w in _all(root) if _mapped(w)]:
        if isinstance(widget, widgets.Button):
            role = _role(widget)
            if abs(widget.winfo_height() - ui.px(ROLE_HEIGHT[role])) > SLACK:
                problems.append("%s: the %s button %r is %d px tall, not %d" % (
                    name, role, widget.words, widget.winfo_height(), ui.px(ROLE_HEIGHT[role])))
            words = ui.fonts.body_bold.measure(widget.words)
            if abs(widget.winfo_width() - (words + 2 * ui.px(BUTTON_SIDE))) > SLACK:
                problems.append("%s: the button %r is %d px wide, its words and %d px either side %d" % (
                    name, widget.words, widget.winfo_width(), ui.px(BUTTON_SIDE), words + 2 * ui.px(BUTTON_SIDE)))
        elif getattr(widget, "odq_button", False):
            size = ui.px(ROLE_HEIGHT["icon"])
            if abs(widget.winfo_height() - size) > SLACK or abs(widget.winfo_width() - size) > SLACK:
                problems.append("%s: the window's %r button is %dx%d, not %dx%d" % (
                    name, getattr(widget, "words", ""), widget.winfo_width(), widget.winfo_height(), size, size))
        elif isinstance(widget, widgets.Slider):
            # Long enough to set its value finely by the mouse: a volume's 0 to 100 on 200 px at least, a range of few
            # steps (an equaliser's band, -12 to 12 dB) on 150.
            track = widget.canvas.winfo_width() - 2 * int(widget.canvas.cget("highlightthickness"))
            least = ui.px(SLIDER_LEAST if widget.most - widget.least >= 50 else BAND_LEAST)
            if track < least - SLACK:
                problems.append("%s: a slider of %s to %s is %d px long, less than %d" % (
                    name, widget.least, widget.most, track, least))
        elif isinstance(widget, widgets.PlaySlab):
            # The slab inside its keyboard ring.
            ring = int(widget.cget("highlightthickness"))
            if abs(widget.winfo_height() - 2 * ring - ui.px(ROLE_HEIGHT["play"])) > SLACK:
                problems.append("%s: PLAY is %d px tall, not %d" % (name, widget.winfo_height() - 2 * ring,
                                                                    ui.px(ROLE_HEIGHT["play"])))
    return problems


# A button's look by its role (DESIGN.md's controls by role): the main action's lime, the red of removing for good as a
# main action, the plain metal, and the metal tinted red of a quiet removal. A look of no role (main's yellow) is none.
ROLE_LOOKS = {"home": "main", "danger": "main", "neutral": "plain", "danger_quiet": "danger"}


def check_dialog(dialog, name):
    """A dialog's buttons as the pages' (role height, words and the same room either side) and their words on their
    middles; each in a look of a role, and one main button at most (lime, or red where it removes for good)."""
    problems = []
    ui, c = dialog.ui, dialog.canvas
    for words, _value, look in dialog.buttons:
        if look not in ROLE_LOOKS:
            problems.append("%s: the dialog's button %r is drawn %r, a look of no role" % (name, words, look))
    mains = [b[0] for b in dialog.buttons if ROLE_LOOKS.get(b[2]) == "main"]
    if len(mains) > 1:
        problems.append("%s: the dialog has %d main buttons: %r" % (name, len(mains), mains))
    for i, (left, top, right, bottom) in enumerate(dialog._boxes):
        words = dialog.buttons[i][0]
        if abs((bottom - top) - ui.px(ROLE_HEIGHT["plain"])) > SLACK:
            problems.append("%s: the dialog's button %r is %d px tall, the pages' %d" % (
                name, words, bottom - top, ui.px(ROLE_HEIGHT["plain"])))
        wide = ui.fonts.dialog_button.measure(words) + 2 * ui.px(BUTTON_SIDE)
        if abs((right - left) - wide) > SLACK:
            problems.append("%s: the dialog's button %r is %d px wide, its words and %d px either side %d" % (
                name, words, right - left, ui.px(BUTTON_SIDE), wide))
        # Its words: the text item drawn for it.
        for item in c.find_withtag("button%d" % i):
            if c.type(item) == "text":
                off = _canvas_text_middle(c, item) - (dialog.origin[1] + (top + bottom) / 2.0)
                if abs(off) > CENTRE_SLACK:
                    problems.append("%s: the dialog's button %r has its words %.2f px %s its middle" % (
                        name, words, abs(off), "under" if off > 0 else "over"))
    return problems


# ---------------------------------------------------------------------------------------------------- background

def _site_shards(width, height, scale, offset):
    """The shards as the page drew them before its design gave them their own room (art.FACETS stretched to the page's
    width, 900 tall, fading downwards): what a launcher without art.shard_mask draws, so that this check sees it."""
    from PIL import Image, ImageDraw
    span = int(900 * scale)
    mask = Image.new("L", (width, height), 0)
    if offset >= span:
        return mask
    k = 2
    big = Image.new("L", (width * k, span * k), 0)
    for opacity, points in art.FACETS:
        layer = Image.new("L", big.size, 0)
        ImageDraw.Draw(layer).polygon([(x / 1440.0 * width * k, y / 900.0 * span * k) for x, y in points],
                                      fill=int(255 * opacity))
        big = Image.composite(layer, big, layer)
    big = big.resize((width, span), Image.LANCZOS)
    down = Image.linear_gradient("L").resize((1, span)).point(lambda v: 255 - v)
    big = Image.composite(big, Image.new("L", big.size, 0), down.resize((width, span)))
    mask.paste(big.crop((0, offset, width, min(span, offset + height))), (0, 0))
    return mask


def _site_panes(width, height, scale, offset, reach):
    """The lit top's two panes as the page drew them before they had a reach of their own (faded out with the accent's
    light, `reach` down: 324 px on the launcher's pages), from `offset` down: what a launcher without art.pane_mask
    draws, so that this check sees it."""
    import math
    from PIL import Image, ImageDraw
    mask = Image.new("L", (width, height), 0)
    if offset >= reach:
        return mask
    fade = Image.new("L", (1, reach), 0)
    for y in range(reach):
        t = y / float(max(1, reach))
        fade.putpixel((0, y), 255 if t < 0.45 else int(255 * max(0.0, (1 - t) / 0.55)))
    fade = fade.resize((width, reach))
    panes = Image.new("L", (width, reach), 0)
    draw = ImageDraw.Draw(panes)
    full = int(620 * scale)
    for angle, alpha, share, from_right in ((115, 14, 0.22, False), (245, 10, 0.16, True)):
        rad = math.radians(angle)
        normal = (math.sin(rad), -math.cos(rad))
        length = abs(width * normal[0]) + abs(full * normal[1])
        origin = (width, 0) if from_right else (0, 0)
        polygon = art._half_plane((width, reach), normal, share * length + origin[0] * normal[0])
        if len(polygon) >= 3:
            draw.polygon(polygon, fill=alpha)
    light = Image.composite(panes, Image.new("L", panes.size, 0), fade)
    mask.paste(light.crop((0, offset, width, min(reach, offset + height))), (0, 0))
    return mask


# A pane's pixel counts from this much of white's share (of 255): fainter, it does not show on the field.
PANE_SEEN = 2


def panes(root, ui, name):
    """No edge of the lit top's two pale panes under the page's heading: their light (art.pane_mask, or as main drew
    it) none within SHARD_CLEAR of the content column's top, down the page and across the column and its clear room
    (main's ran through the heading, ended on the first card's top edge and showed again between the cards)."""
    problems = []
    for area in _page_areas(root):
        picture = getattr(area, "_backdrop_picture", None)
        if picture is None:
            continue
        width, height = picture.size
        if hasattr(art, "pane_mask"):
            mask = art.pane_mask(width, height, ui.scale, area.offset)
        else:
            mask = _site_panes(width, height, ui.scale, area.offset, int(area.light or 620 * ui.scale))
        clear = ui.px(SHARD_CLEAR)
        left = int(round(float(area.canvas.coords(area._window)[0])))
        box = (max(0, left - clear), max(0, int(area._content_top) - clear),
               min(width, left + area.inner.winfo_width() + clear), height)
        hit = mask.crop(box).point(lambda v: 255 if v >= PANE_SEEN else 0)
        if hit.getbbox():
            found = hit.getbbox()
            problems.append("%s: the lit top's panes reach %d px into the content column's top and its room (page "
                            "pixels %r)" % (name, found[3], (found[0] + box[0], found[1] + box[1],
                                                               found[2] + box[0], found[3] + box[1])))
    return problems


def _shards(width, height, scale, offset, room, keep):
    """The shards a picture of the page draws from `offset` down (art.shard_mask), the boxes it keeps them from given
    as the launcher gives them (none to a launcher that keeps none)."""
    if keep:
        return art.shard_mask(width, height, scale, offset, room, keep)
    return art.shard_mask(width, height, scale, offset, room)


def background(root, ui, name):
    """No shard within SHARD_CLEAR of the content column under the heading, or of any card, down the whole page, or of
    the window's own buttons (the installer's header, whose picture is the page's first rows)."""
    from PIL import Image
    problems = []
    for area in _page_areas(root):
        picture = getattr(area, "_backdrop_picture", None)
        if picture is None:
            continue
        width, height = picture.size
        # The shards the area drew, by the drawing's own geometry.
        kept_clear = area.shard_keep() if hasattr(area, "shard_keep") else ()
        if hasattr(art, "shard_mask"):
            mask = _shards(width, height, ui.scale, area.offset, area.shard_room(), kept_clear)
        else:
            mask = _site_shards(width, height, ui.scale, area.offset)
        seen = mask.point(lambda v: 255 if v >= SHARD_SEEN else 0)
        if not seen.getbbox():
            continue
        clear = ui.px(SHARD_CLEAR)
        # Where nothing of a shard may be, in the page's own pixels: the column under the heading, and every card.
        keep = Image.new("L", (width, height), 0)
        left = int(round(float(area.canvas.coords(area._window)[0])))
        right = left + area.inner.winfo_width()
        keep.paste(255, (max(0, left - clear), max(0, int(area._content_top) - clear), min(width, right + clear), height))
        for card in _cards(area):
            place = area.page_box(card)
            if place is None:
                continue
            keep.paste(255, (max(0, place[0] - clear), max(0, place[1] - clear),
                             min(width, place[0] + card.winfo_width() + clear),
                             min(height, place[1] + card.winfo_height() + clear)))
        from PIL import ImageChops
        hit = ImageChops.multiply(seen, keep)
        box = hit.getbbox()
        if box:
            problems.append("%s: %d px of the page's shards stand within %d px of the content column or a card "
                            "(page pixels %r)" % (name, hit.histogram()[255], SHARD_CLEAR, box))
    # The window's own buttons in a header that shows the page's first rows (main: the big shard's edge ran through
    # the close button's cut corner, and a slim one's tip pointed at its foot, on every page of the installer).
    for button in [w for w in _all(root) if getattr(w, "odq_button", False) and _mapped(w)]:
        header = button.master
        if getattr(header, "moved_off", False) or not hasattr(art, "shard_mask"):
            # Drawn as the strip's own colour once the page has moved from its top: no shards there then.
            continue
        width, tall = max(1, header.winfo_width()), max(1, header.winfo_height())
        room = getattr(header, "room", None)
        boxes = header.button_boxes(width) if hasattr(header, "button_boxes") else ()
        seen = _shards(width, tall, ui.scale, 0, room() if room is not None else None, boxes).point(
            lambda v: 255 if v >= SHARD_SEEN else 0)
        clear = ui.px(SHARD_CLEAR)
        x, y = button.winfo_rootx() - header.winfo_rootx(), button.winfo_rooty() - header.winfo_rooty()
        box = (max(0, x - clear), max(0, y - clear), min(width, x + button.winfo_width() + clear),
               min(tall, y + button.winfo_height() + clear))
        hit = seen.crop(box)
        if hit.getbbox():
            problems.append("%s: %d px of the page's shards stand within %d px of the window's %r button" % (
                name, hit.histogram()[255], SHARD_CLEAR, getattr(button, "words", "")))
    return problems


# ---------------------------------------------------------------------------------------------------------- all

# ------------------------------------------------------------------------------------------------ the cards' forms

def corner(card, foot=False):
    """The side (pixels) of the picture over a card's cut corner, the top-right one (or its foot's, the bottom-left),
    or 0 for a square corner: read from the picture laid over that corner of the card."""
    width, height = card.winfo_width(), card.winfo_height()
    for child in card.winfo_children():
        if not (isinstance(child, tk.Label) and str(child.cget("image")) and child.winfo_manager() == "place"):
            continue
        x, y, w, h = child.winfo_x(), child.winfo_y(), child.winfo_width(), child.winfo_height()
        if foot and x <= 0 and abs(y + h - height) <= SLACK:
            return w
        if not foot and y <= 0 and abs(x + w - width) <= SLACK:
            return w
    return 0


def top_light(card):
    """The colour of the row of light along a card's top edge (laid over it, across the card), or None."""
    for child in card.winfo_children():
        if isinstance(child, tk.Frame) and child.winfo_manager() == "place" and child.winfo_y() <= 0 \
                and child.winfo_width() >= card.winfo_width() - SLACK:
            return str(child.cget("bg")).lower()
    return None


def strip(card):
    """A card's header strip: the frame holding its title when it stands across the card over its body (not in it),
    or None."""
    title = _title(card)
    if title is None or title.master.master is not card:
        return None
    return title.master


def hero(card, ui):
    """What keeps `card` from being the page's head as the hero (DESIGN.md): words, or "" when it is one."""
    surface, light = str(card.cget("bg")).lower(), top_light(card)
    cuts = (corner(card), corner(card, foot=True))
    if surface != theme.PANEL_HI.lower() or light != theme.RIM_HI.lower() or \
            cuts != tuple(ui.px(n) for n in HERO_CUTS):
        return "its surface %s, the light along its top %s, its cuts %d and %d px" % ((surface, light) + cuts)
    return ""


def surfaces(root, ui, name):
    """Each card's surface and silhouette by its role, read from the card as it stands."""
    problems = []
    roles = {ui.words(key): key for key in STATUS_PANELS + QUIET_CARDS}
    deck, quiet = theme.PANEL.lower(), theme.QUIET.lower()
    for area in _page_areas(root):
        for index, card in enumerate(_cards(area)):
            title = _title(card)
            words = str(title.cget("text")) if title is not None else ""
            key = roles.get(words)
            surface, light, head = str(card.cget("bg")).lower(), top_light(card), strip(card)
            said = _said(card)
            if key in STATUS_PANELS:
                # Its title and its state on a strip a step deeper than the deck, across the card's width.
                inner = card.winfo_width() - 2 * int(card.cget("highlightthickness"))
                if head is None or str(head.cget("bg")).lower() != theme.STRIP_HEAD.lower() or \
                        head.winfo_width() < inner - SLACK:
                    problems.append("%s: the card %s reports a state without its header strip" % (name, said))
            elif head is not None:
                problems.append("%s: the card %s has a header strip and reports no state" % (name, said))
            if key in STATE_LIGHTS and head is not None:
                title_x = title.winfo_rootx()
                lights = [x for x in head.winfo_children() if isinstance(x, tk.Label) and _mapped(x)
                          and str(x.cget("image")) and not str(x.cget("text")).strip() and x.winfo_rootx() < title_x]
                if not lights:
                    problems.append("%s: the card %s carries no light of its state on its strip" % (name, said))
            if key in RESULTS and corner(card, foot=True) != corner(card):
                problems.append("%s: the card %s is a result without its foot's corner cut (%d px, its top's %d)" % (
                    name, said, corner(card, foot=True), corner(card)))
            if key in QUIET_CARDS:
                if surface != quiet or light is not None:
                    problems.append("%s: the card %s is not quiet: its surface %s, the light along its top %s" % (
                        name, said, surface, light))
            elif index == 0 and surface != deck:
                # A surface of its own at a page's head: the hero's, and the hero's whole form with it.
                if hero(card, ui):
                    problems.append("%s: the page's head card is not the hero: %s" % (name, hero(card, ui)))
            elif surface != deck or light != theme.RIM.lower() or corner(card) != ui.px(CUT):
                problems.append("%s: the card %s is not on the deck: its surface %s, the light along its top %s, its "
                                "cut %d px" % (name, said, surface, light, corner(card)))
    return problems


def lamps(root, ui, name):
    """One shape for one state: a lamp in the warning's yellow is a ring, as the ready check's, the test's steps' and the
    installer's are (the connection test's verdict and the status line drew a filled dot for a warning). Read from each
    lamp's own picture (odq_picture), its middle the card's colour, not the yellow."""
    problems = []
    warn = art._rgb(theme.WARN)
    for label in [w for w in _all(root) if isinstance(w, tk.Label) and _mapped(w)]:
        picture = getattr(label, "odq_picture", None)
        if picture is None or str(label.cget("text")).strip() or picture.width > 4 * ui.px(7) + 4:
            # Words, a picture that is no lamp (a corner, a mark, a field), or none.
            continue
        rgb = picture.convert("RGB")
        background = rgb.getpixel((rgb.width - 1, 0))
        # The dot: the pixels away from the picture's own background, its middle the middle of their box.
        box = _ink_box(rgb, background)
        if box is None:
            continue
        middle = rgb.getpixel(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))
        if all(abs(a - b) <= 24 for a, b in zip(middle, warn)):
            problems.append("%s: a warning's lamp is a filled dot, not a ring (beside %r)" % (
                name, next((str(x.cget("text"))[:30] for x in label.master.winfo_children()
                            if isinstance(x, tk.Label) and str(x.cget("text")).strip()), "")))
    return problems


def _ink_box(picture, background):
    """The box of the pixels of `picture` that differ from `background` by more than a few levels, or None."""
    from PIL import Image, ImageChops
    plain = Image.new("RGB", picture.size, background)
    diff = ImageChops.difference(picture, plain).convert("L").point(lambda v: 255 if v > 16 else 0)
    return diff.getbbox()


def check(root, ui, name):
    """Every measure above on the screen as it shows now."""
    root.update_idletasks()
    problems = []
    problems.extend(composition(root, ui, name))
    problems.extend(text(root, ui, name))
    problems.extend(buttons(root, ui, name))
    problems.extend(background(root, ui, name))
    problems.extend(panes(root, ui, name))
    problems.extend(surfaces(root, ui, name))
    problems.extend(lamps(root, ui, name))
    return sorted(set(problems))
