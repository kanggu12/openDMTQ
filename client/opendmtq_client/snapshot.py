"""The launcher's window as a picture, drawn from its own widgets instead of read from the screen.

A dialog shows the window behind it blurred and dimmed. Reading the screen would take a different call on each
platform and could pick up another program's window lying over the launcher; drawing the window from its widgets
gives the same picture everywhere, tests included: each widget's background, the pictures the launcher drew
itself, and text as soft bars of its colour, which look like text out of focus once the dialog blurs them.

A widget can hand over the picture it shows by setting `odq_picture` to a PIL image of its size (the page
header, PLAY); a widget with `odq_skip` set is left out (the dialog itself).
"""

import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageDraw

from opendmtq_client import theme

# How strongly a line of text shows as a bar: letters cover about a third of their line, so a bar of the text's
# colour at this strength carries about the same weight once blurred.
TEXT_ALPHA = 100


def render(root):
    """The window's inside (without its title bar) as an RGB picture of its size in pixels."""
    root.update_idletasks()
    width, height = max(1, root.winfo_width()), max(1, root.winfo_height())
    img = Image.new("RGB", (width, height), _colour(root, root.cget("bg")) or (0, 0, 0))
    try:
        _paint(root, img, _Draw(img), (root.winfo_rootx(), root.winfo_rooty()), (0, 0, width, height))
    finally:
        # The fonts made for this drawing go with it: each is a Tk font until Python forgets it.
        _FONTS.clear()
    return img


class _Draw:
    """The window's picture drawn on in two ways: opaque colours plainly, and the text's soft bars blended (blending
    every fill would cost a third of a drawing)."""

    def __init__(self, img):
        self.plain, self.blend = ImageDraw.Draw(img), ImageDraw.Draw(img, "RGBA")

    def rectangle(self, xy, fill):
        # A colour with its strength (r, g, b, a) blends; (r, g, b) covers.
        (self.blend if len(fill) == 4 else self.plain).rectangle(xy, fill=fill)

    def line(self, points, fill, width):
        (self.blend if len(fill) == 4 else self.plain).line(points, fill=fill, width=width)


def _colour(widget, name):
    """A Tk colour name or #rrggbb as (r, g, b); None for an empty or unknown one."""
    if not name:
        return None
    try:
        r, g, b = widget.winfo_rgb(name)
    except tk.TclError:
        return None
    # Tk answers in 16 bits a channel.
    return r >> 8, g >> 8, b >> 8


def _option(widget, name):
    """A widget option, or None when this kind of widget has no such option (ttk widgets have few)."""
    try:
        return widget.cget(name)
    except tk.TclError:
        return None


def _pixels(widget, value):
    """A Tk screen distance (a number, '4p', an object) in pixels; 0 when there is none."""
    if value in (None, ""):
        return 0
    try:
        return int(round(widget.winfo_fpixels(str(value))))
    except tk.TclError:
        return 0


def _box(widget, origin):
    """The widget's (left, top, right, bottom) in the window's pixels."""
    x, y = widget.winfo_rootx() - origin[0], widget.winfo_rooty() - origin[1]
    return x, y, x + widget.winfo_width(), y + widget.winfo_height()


def _clip(box, clip):
    """The part of `box` inside `clip`, or None when nothing of it is."""
    left, top = max(box[0], clip[0]), max(box[1], clip[1])
    right, bottom = min(box[2], clip[2]), min(box[3], clip[3])
    return (left, top, right, bottom) if left < right and top < bottom else None


def _fill(draw, box, seen, colour):
    """Fill the part of `box` that shows."""
    part = _clip(box, seen)
    if part:
        draw.rectangle([part[0], part[1], part[2] - 1, part[3] - 1], fill=colour)


def _paint(widget, img, draw, origin, clip):
    """Draw each shown child of `widget`, then its children inside it: a child never shows outside its parent."""
    for child in widget.winfo_children():
        if getattr(child, "odq_skip", False) or not child.winfo_ismapped():
            continue
        box = _box(child, origin)
        seen = _clip(box, clip)
        if seen is None:
            continue
        kind = child.winfo_class()
        if kind == "TCombobox":
            # A ttk drop-down has no colour options; it is drawn in the field colours with its value.
            _fill(draw, box, seen, _colour(child, theme.LINE))
            _fill(draw, (box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1), seen, _colour(child, theme.FIELD))
            font = _font(child, _option(child, "font"))
            if font:
                _bars(draw, font, [child.get()], _colour(child, theme.TEXT), (box[0] + 8, box[1], box[2], box[3]),
                      "w", "left", seen, False)
            continue
        picture = getattr(child, "odq_picture", None)
        if callable(picture):
            # A picture made only when a dialog asks (the page area's: the page's height in pixels, kept otherwise).
            picture = picture()
        background = _colour(child, _option(child, "bg"))
        if background and not _covers(picture, box):
            _fill(draw, box, seen, background)
        _border(child, draw, box, seen)
        if picture is not None:
            _picture(img, picture, box, seen)
        if kind == "Label":
            _label_text(child, draw, box, seen)
        elif kind == "Canvas":
            _canvas(child, draw, box, seen)
        elif kind == "Entry":
            _entry_text(child, draw, box, seen)
        _paint(child, img, draw, origin, seen)


def _border(widget, draw, box, seen):
    """The edge Tk draws round a widget with a highlight thickness (buttons, cards, fields)."""
    thickness = _pixels(widget, _option(widget, "highlightthickness"))
    colour = _colour(widget, _option(widget, "highlightbackground"))
    if thickness <= 0 or colour is None:
        return
    for i in range(thickness):
        left, top, right, bottom = box[0] + i, box[1] + i, box[2] - i, box[3] - i
        for strip in ((left, top, right, top + 1), (left, bottom - 1, right, bottom),
                      (left, top, left + 1, bottom), (right - 1, top, right, bottom)):
            _fill(draw, strip, seen, colour)


def _covers(picture, box):
    """Whether a widget's own picture hides all of its box: an opaque one at least as big (its background unseen)."""
    return (picture is not None and picture.mode == "RGB" and picture.width >= box[2] - box[0]
            and picture.height >= box[3] - box[1])


def _picture(img, picture, box, seen):
    """Paste a widget's own picture where it shows: the part that shows cut out first, then made opaque if it is not
    (a page's picture is many times what shows of it)."""
    left, top = seen[0] - box[0], seen[1] - box[1]
    # Never past the picture's own edge: a widget can be bigger than its picture (a switch inside its keyboard ring),
    # and what lies past it is the widget's background, not black.
    right, bottom = min(picture.width, left + seen[2] - seen[0]), min(picture.height, top + seen[3] - seen[1])
    if right <= left or bottom <= top:
        return
    part = picture.crop((left, top, right, bottom))
    if part.mode == "RGB":
        img.paste(part, (seen[0], seen[1]))
        return
    part = part.convert("RGBA")
    img.paste(part.convert("RGB"), (seen[0], seen[1]), part.getchannel("A"))


# The fonts of one drawing by their names: render() empties it when the drawing is done.
_FONTS = {}


def _font(widget, name):
    """A Tk font as a widget names it, made once for each name in a drawing (a few dozen labels share a few fonts)."""
    if not name:
        return None
    key = str(name)
    if key not in _FONTS:
        try:
            _FONTS[key] = tkfont.Font(widget, font=name)
        except tk.TclError:
            _FONTS[key] = None
    return _FONTS[key]


def wrap(font, text, width):
    """The text cut into the lines Tk shows: at newlines, and at spaces where a wrap width is set."""
    lines = []
    for paragraph in text.split("\n"):
        if width <= 0:
            lines.append(paragraph)
            continue
        line = ""
        for word in paragraph.split(" "):
            candidate = word if not line else line + " " + word
            if line and font.measure(candidate) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


def _bars(draw, font, lines, colour, area, anchor, justify, seen, icon):
    """Each line as a bar about as tall as small letters, placed the way Tk places the text in `area`."""
    if colour is None:
        return
    space = font.metrics("linespace")
    widths = [font.measure(line) for line in lines]
    block_w, block_h = max(widths or [0]), space * len(lines)
    left, top, right, bottom = area
    across = "w" if anchor in ("w", "nw", "sw") else ("e" if anchor in ("e", "ne", "se") else "centre")
    down = "n" if anchor in ("n", "nw", "ne") else ("s" if anchor in ("s", "sw", "se") else "centre")
    x = left if across == "w" else (right - block_w if across == "e" else (left + right - block_w) // 2)
    y = top if down == "n" else (bottom - block_h if down == "s" else (top + bottom - block_h) // 2)
    # An icon is one solid glyph; a line of letters is a band through the middle of its height.
    band = (0.2, 0.8) if icon else (0.32, 0.72)
    for i, (line, width) in enumerate(zip(lines, widths)):
        if not line.strip():
            continue
        lx = x + (block_w - width if justify == "right" else (block_w - width) // 2 if justify == "center" else 0)
        bar = (lx, y + i * space + int(space * band[0]), lx + width, y + i * space + int(space * band[1]))
        _fill(draw, bar, seen, colour + (TEXT_ALPHA,))


def _label_text(label, draw, box, seen):
    text = label.cget("text")
    font = _font(label, label.cget("font"))
    if not text or not text.strip() or font is None:
        return
    wrap_px = _pixels(label, label.cget("wraplength"))
    padx, pady = _pixels(label, label.cget("padx")), _pixels(label, label.cget("pady"))
    area = (box[0] + padx, box[1] + pady, box[2] - padx, box[3] - pady)
    _bars(draw, font, wrap(font, text, wrap_px), _colour(label, label.cget("fg")), area, str(label.cget("anchor")),
          str(label.cget("justify")), seen, font.actual("family") == theme.ICONS)


def _entry_text(entry, draw, box, seen):
    text = entry.get()
    if _option(entry, "show"):
        text = _option(entry, "show") * len(text)
    font = _font(entry, _option(entry, "font"))
    if text and font:
        _bars(draw, font, [text], _colour(entry, _option(entry, "fg")), (box[0] + 4, box[1], box[2] - 4, box[3]),
              "w", "left", seen, False)


def _canvas(canvas, draw, box, seen):
    """A canvas's lines and text (its pictures come from odq_picture; its window items are widgets)."""
    dx, dy = box[0] - int(canvas.canvasx(0)), box[1] - int(canvas.canvasy(0))
    for item in canvas.find_all():
        kind = canvas.type(item)
        if kind == "line":
            coords = canvas.coords(item)
            colour = _colour(canvas, canvas.itemcget(item, "fill"))
            if not colour or len(coords) < 4:
                continue
            points = [(coords[i] + dx, coords[i + 1] + dy) for i in range(0, len(coords) - 1, 2)]
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            # Pillow cannot clip a line, so one that reaches out of sight (a scrolled page) is left out.
            if _clip((min(xs), min(ys), max(xs) + 1, max(ys) + 1), seen) != (min(xs), min(ys), max(xs) + 1, max(ys) + 1):
                continue
            draw.line(points, fill=colour, width=max(1, int(float(canvas.itemcget(item, "width")))))
        elif kind == "text":
            font = _font(canvas, canvas.itemcget(item, "font"))
            bounds = canvas.bbox(item)
            if font is None or not bounds:
                continue
            area = (bounds[0] + dx, bounds[1] + dy, bounds[2] + dx, bounds[3] + dy)
            width = int(float(canvas.itemcget(item, "width") or 0))
            justify = canvas.itemcget(item, "justify") or "left"
            _bars(draw, font, wrap(font, canvas.itemcget(item, "text"), width),
                  _colour(canvas, canvas.itemcget(item, "fill")), area, "nw" if justify == "left" else "n", justify,
                  seen, font.actual("family") == theme.ICONS)
