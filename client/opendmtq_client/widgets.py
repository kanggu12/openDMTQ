"""The launcher's building blocks, drawn to match its theme instead of the Windows defaults.

Tk's stock widgets look like 1990s Windows on a dark background, so the controls here are Labels and Canvases
with images from art.py. Each keeps its own images alive (Tk drops an image the moment Python forgets it).
"""

import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from opendmtq_client import art, theme


class Ui:
    """What every widget needs to draw itself: the root, the fonts, the DPI scale and the words. Every page's main
    buttons, switches and links are lit in the site's lime (theme.OK), the one colour for what is in use."""

    def __init__(self, root, fonts, scale, words):
        self.root = root
        self.fonts = fonts
        self.scale = scale
        self.words = words

    def px(self, n):
        """Logical pixels (at 100 % scaling) to real pixels on this screen."""
        return int(round(n * self.scale))


def style_ttk(ui):
    """Dark styles for the few ttk widgets used (the drop-down list and the scroll bar)."""
    s = ttk.Style(ui.root)
    # 'clam' is the built-in theme that honours colours on every platform.
    s.theme_use("clam")
    # A drop-down as the site's select: a dark field with a one-pixel seam and a light chevron; lime round it while it
    # has the keyboard, as the site's fields.
    # Its words begin where they always have, LIST_TEXT logical pixels inside its seam: the room before them is the
    # style's padding and the spaces before each choice (list_pad), which its opened list's rows have too, so that the
    # words of the two line up (Select).
    _pad, pad_width = list_pad(ui)
    s.configure("Dark.TCombobox", fieldbackground=theme.FIELD, background=theme.FIELD, foreground=theme.TEXT,
                arrowcolor=theme.MUTED, bordercolor=theme.LINE, lightcolor=theme.FIELD, darkcolor=theme.FIELD,
                selectbackground=theme.FIELD, selectforeground=theme.TEXT,
                padding=(ui.px(LIST_TEXT) - pad_width, ui.px(4)), arrowsize=ui.px(13))
    s.map("Dark.TCombobox", fieldbackground=[("readonly", theme.FIELD)], foreground=[("readonly", theme.TEXT)],
          background=[("active", theme.FIELD), ("readonly", theme.FIELD)],
          bordercolor=[("focus", theme.OK), ("hover", "#55606c")], arrowcolor=[("disabled", theme.FAINT),
                                                                              ("hover", theme.TEXT)])
    # The list that drops down is a plain Tk listbox; its colours come from the option database. No border or ring of
    # its own: the frame round it (below) draws the seam and keeps the room inside it.
    ui.root.option_add("*TCombobox*Listbox.background", theme.FIELD)
    ui.root.option_add("*TCombobox*Listbox.foreground", theme.TEXT)
    ui.root.option_add("*TCombobox*Listbox.selectBackground", theme.RAIL_UP)
    ui.root.option_add("*TCombobox*Listbox.selectForeground", theme.TEXT)
    ui.root.option_add("*TCombobox*Listbox.font", ui.fonts.body)
    ui.root.option_add("*TCombobox*Listbox.borderWidth", 0)
    ui.root.option_add("*TCombobox*Listbox.highlightThickness", 0)
    ui.root.option_add("*TCombobox*Listbox.relief", "flat")
    # The frame round the opened list: the field's seam as its edge, and inside it room as the closed box has before its
    # words, so that each row's words start where the box's do (its own spaces, list_pad, then the same) and the row
    # under the pointer is lit inside that room instead of from edge to edge; a little room above the first and under
    # the last row too.
    # Its seam as thick as the closed box's (the face's own edge, combobox_faces), so that inside it the room before the
    # words is the closed box's padding again.
    edge = max(1, ui.px(1))
    side = ui.px(LIST_TEXT) - pad_width
    s.configure("ComboboxPopdownFrame", background=theme.FIELD, bordercolor=theme.LINE, lightcolor=theme.LINE,
                darkcolor=theme.LINE, relief="solid", borderwidth=edge)
    # A frame's room inside it, and the width of its edge, are the frame's own options, which ttk takes from the option
    # database when it makes the list's frame at the first opening (a style's padding does not reach a frame). The clam
    # theme's border keeps one pixel more inside its edge than the edge's width (measured: the list's words came 1 px
    # right of the box's at 100 % and at 200 %), so the room at the sides is a pixel less.
    ui.root.option_add("*TCombobox*TFrame.padding", "%d %d %d %d" % (max(0, side - 1), ui.px(4), max(0, side - 1),
                                                                     ui.px(4)))
    ui.root.option_add("*TCombobox*TFrame.borderWidth", edge)
    quiet_combobox_wheel(ui.root)
    # Labels draw their words from their own edge, as fields and buttons draw theirs: Tk's own room round a label's
    # words (its border and padding, 3 px on Windows) would set every card's words in from the fields under them.
    ui.root.option_add("*Label.borderWidth", 0)
    ui.root.option_add("*Label.padX", 0)
    ui.root.option_add("*Label.padY", 0)
    combobox_faces(ui, s)
    s.configure("Dark.Vertical.TScrollbar", background=theme.RAIL, troughcolor=theme.BG, bordercolor=theme.BG,
                lightcolor=theme.RAIL, darkcolor=theme.RAIL, arrowcolor=theme.MUTED, gripcount=0,
                arrowsize=ui.px(12))
    s.map("Dark.Vertical.TScrollbar", background=[("active", theme.RAIL_UP)])


# Where a drop-down's words start, closed and opened: this many logical pixels inside its one-pixel seam.
LIST_TEXT = 10


def list_pad(ui):
    """The spaces each choice of a drop-down starts with, and their width: the room before a row's words in its opened
    list, where a Tk listbox has none of its own and lights a row from edge to edge (Select). As many spaces of the
    words' font as come nearest to 6 logical pixels, the rest of LIST_TEXT being padding (style_ttk), so that a lit
    row starts that much before its words."""
    space = max(1, ui.fonts.body.measure(" "))
    count = max(0, int(round(ui.px(6) / float(space))))
    pad = " " * count
    return pad, ui.fonts.body.measure(pad) if pad else 0


def combobox_faces(ui, style):
    """The drop-down's face as the text field's (art.field_face, sunk into its card) and its arrow a chevron on it, as
    ttk image elements with a state each; made once for each scale (Tk keeps an element by its name)."""
    from PIL import ImageTk
    name = "Odq%d" % int(round(ui.scale * 100))
    if name + ".Combobox.field" not in style.element_names():
        px = ui.px
        # The face is stretched between its edges: drawn a little larger than its corners, cut into nine by `border`.
        size, edge = (px(40), px(Button.HEIGHT)), px(6)
        faces = {state: ImageTk.PhotoImage(art.field_face(size[0], size[1], state, ui.scale), master=ui.root)
                 for state in ("normal", "hover", "focus", "disabled")}
        arrows = {state: ImageTk.PhotoImage(art.chevron(px(26), px(20), colour, ui.scale), master=ui.root)
                  for state, colour in (("normal", theme.MUTED), ("hover", theme.TEXT), ("disabled", theme.FAINT))}
        # Kept on the root: Tk drops a picture the moment Python forgets it.
        ui.root.odq_combobox_faces = getattr(ui.root, "odq_combobox_faces", []) + [faces, arrows]
        # Its padding the edge alone: the words' own room is the style's padding, and the face's height a button's.
        style.element_create(name + ".Combobox.field", "image", faces["normal"], ("focus", faces["focus"]),
                             ("disabled", faces["disabled"]), ("hover", faces["hover"]), border=edge,
                             padding=max(1, px(1)), sticky="nsew")
        style.element_create(name + ".Combobox.downarrow", "image", arrows["normal"], ("disabled", arrows["disabled"]),
                             ("hover", arrows["hover"]), sticky="")
    style.layout("Dark.TCombobox", [(name + ".Combobox.field", {"sticky": "nswe", "children": [
        (name + ".Combobox.downarrow", {"side": "right", "sticky": "ns"}),
        ("Combobox.padding", {"expand": "1", "sticky": "nswe", "children": [
            ("Combobox.textarea", {"sticky": "nswe"})]})]})])


# The wheel's events, as Windows (MouseWheel) and X11 (buttons 4 and 5) send them.
WHEEL = ("<MouseWheel>", "<Shift-MouseWheel>", "<Button-4>", "<Button-5>")


def quiet_combobox_wheel(root):
    """The wheel scrolls the page and never a drop-down's value. Tk's own bindings for every drop-down step its value
    under the pointer and say it was chosen, so scrolling a page past a setting would change that setting unseen; the
    page's own scrolling (ScrollArea, bound for all widgets) stays."""
    for sequence in WHEEL:
        root.unbind_class("TCombobox", sequence)


class Header(tk.Canvas):
    """The bar across the window's top, as the site's: on the page's own backdrop at the top (it continues into the page
    under it), a dark bar with a line under it once the page has moved. At its left the wordmark and the version
    (`brand`, a picture), then the menu: names in the wide face, ash, white under the pointer, the one in use lime with a
    3 px rule at the bar's foot. At its right end an optional link. Under them, for the guide, its steps.

    The menu takes the keyboard first: Tab and Shift+Tab move along it, then on to the page; Enter or Space opens the
    entry with the cyan ring, the arrow keys move the ring.
    """

    # The bar's height, its room at either end and round each name (logical pixels), the reach of the page's lit top.
    HEIGHT, EDGE, NAME_PAD, STEPS_H, LIGHT = 64, 28, 13, 64, 260

    def __init__(self, parent, ui, brand, nav=(), on_nav=None, link=None, steps=()):
        self.ui = ui
        px = ui.px
        height = px(self.HEIGHT) + (px(self.STEPS_H) if steps else 0)
        super().__init__(parent, height=height, bg=theme.BG, highlightthickness=0, bd=0,
                         takefocus=1 if nav or link else 0)
        self.brand_picture = brand
        self.nav, self.on_nav, self.link, self.steps = list(nav), on_nav, link, list(steps)
        self.current, self.hover, self.ring, self.under, self.step = None, None, None, False, 0
        self._job = None
        # Each entry's box on the bar, known once it is drawn.
        self.boxes = {}
        self.bind("<Configure>", lambda e: self._queue())
        for key, move in (("<Tab>", 1), ("<Shift-Tab>", -1), ("<ISO_Left_Tab>", -1), ("<Right>", 1), ("<Left>", -1)):
            self.bind(key, lambda e, m=move, k=key: self._move(m, k))
        for key in ("<Return>", "<space>"):
            self.bind(key, lambda e: self._press(self.ring))
        self.bind("<FocusIn>", lambda e: self._focused(True))
        self.bind("<FocusOut>", lambda e: self._focused(False))

    # The entries the keyboard and the pointer reach: the menu's, then the link at the right end.
    def _entries(self):
        return [key for key, _ in self.nav] + (["link"] if self.link else [])

    def _queue(self):
        """Draw again once the size settles (a drag fires many resize events)."""
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(30, self.draw)

    def draw(self):
        from PIL import Image, ImageTk
        self._job = None
        if not self.winfo_exists():
            return
        px, scale = self.ui.px, self.ui.scale
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        self.delete("all")
        if self.under:
            # Once the page has moved: the site's bar under, dark, with a line along its foot.
            picture = Image.new("RGB", (width, height), art._rgb(theme.STRIP))
            picture.paste(art._rgb("#2a3038"), (0, height - 1, width, height))
        else:
            # At the top: the page's own backdrop, its top part (the page area draws the rest from here down).
            picture = art.backdrop(width, height, scale, top=px(self.HEIGHT) + px(self.LIGHT))
        picture = picture.copy()
        brand = self.brand_picture
        bx, by = px(self.EDGE), (px(self.HEIGHT) - brand.height) // 2
        picture.paste(brand, (bx, by), brand)
        self._picture = picture
        self._image = ImageTk.PhotoImage(picture, master=self)
        # A dialog draws the window from the widgets (snapshot.py): the bar as it looks now.
        self.odq_picture = picture
        self.create_image(0, 0, image=self._image, anchor="nw")
        # The menu after the wordmark, a step smaller where the window is too narrow for it in one line.
        x = bx + brand.width + px(22)
        font, pad = self.ui.fonts.nav, px(self.NAME_PAD)
        right_room = (self.ui.fonts.small.measure(self.link[0]) + px(self.EDGE) + px(24)) if self.link else px(self.EDGE)
        need = sum(font.measure(words) + 2 * pad for _, words in self.nav)
        if x + need + right_room > width:
            font, pad = self.ui.fonts.nav_small, px(8)
        self.boxes = {}
        for key, words in self.nav:
            w = font.measure(words) + 2 * pad
            self.boxes[key] = (x, 0, x + w, px(self.HEIGHT))
            self.create_text(x + w // 2, px(self.HEIGHT) // 2, text=words, font=font, tags=("name", "n-" + key))
            for event, handler in (("<Enter>", lambda e, k=key: self._hover(k)), ("<Leave>", lambda e: self._hover(None)),
                                   ("<Button-1>", lambda e, k=key: self._press(k))):
                self.tag_bind("n-" + key, event, handler)
            x += w
        if self.link:
            words, _command = self.link
            lx = width - px(self.EDGE)
            item = self.create_text(lx, px(self.HEIGHT) // 2, text=words, font=self.ui.fonts.small, anchor="e",
                                    tags=("name", "n-link"))
            x0, y0, x1, y1 = self.bbox(item)
            self.boxes["link"] = (x0 - px(6), y0 - px(6), x1 + px(6), y1 + px(6))
            for event, handler in (("<Enter>", lambda e: self._hover("link")), ("<Leave>", lambda e: self._hover(None)),
                                   ("<Button-1>", lambda e: self._press("link"))):
                self.tag_bind("n-link", event, handler)
        if self.steps:
            self._draw_steps(width)
        self._paint()

    def _draw_steps(self, width):
        """The guide's six steps across, as the site's numbered steps: each number big and leaning, its name, a line
        under; the one on show lit, the ones done in lime, the ones to come in the seam's grey."""
        from PIL import ImageTk
        px, scale = self.ui.px, self.ui.scale
        left, right = px(self.EDGE), width - px(self.EDGE)
        top = px(self.HEIGHT) + px(4)
        cell = (right - left - (len(self.steps) - 1) * px(8)) / float(len(self.steps))
        self._numerals = []
        for i, name in enumerate(self.steps):
            done, now = i < self.step, i == self.step
            x = left + i * (cell + px(8))
            colour = theme.OK if (done or now) else theme.STEP_TO_COME
            picture = art.numeral(str(i + 1), colour, scale, bg=None)
            image = ImageTk.PhotoImage(picture, master=self)
            self._numerals.append(image)
            self.create_image(x, top, image=image, anchor="nw")
            self._picture.paste(picture, (int(x), int(top)), picture if picture.mode == "RGBA" else None)
            self.create_text(x + picture.width + px(6), top + picture.height - px(6), text=name, anchor="sw",
                             font=self.ui.fonts.step,
                             fill=theme.TEXT if now else (theme.MUTED if done else theme.FAINT))
            thick = px(3) if now else px(2)
            y = top + picture.height + px(8)
            self.create_rectangle(x, y, x + cell, y + thick, width=0,
                                  fill=theme.OK if (done or now) else theme.LINE)

    def _paint(self):
        """Each name's colour, the rule under the page in use, and the keyboard's ring."""
        px = self.ui.px
        self.delete("rule", "ring")
        for key, _words in self.nav:
            on = key == self.current
            colour = theme.OK if on else ("#ffffff" if key == self.hover else theme.MUTED)
            self.itemconfigure("n-" + key, fill=colour)
            if on and key in self.boxes:
                x0, _y0, x1, y1 = self.boxes[key]
                self.create_rectangle(x0 + px(8), y1 - px(3), x1 - px(8), y1, fill=theme.OK, width=0, tags=("rule",))
        if self.link:
            self.itemconfigure("n-link", fill="#ffffff" if self.hover == "link" else theme.MUTED)
        if self.ring in self.boxes:
            x0, y0, x1, y1 = self.boxes[self.ring]
            inset = px(10) if self.ring != "link" else 0
            self.create_rectangle(x0 + px(2), y0 + inset, x1 - px(2), y1 - inset, outline=theme.CYAN,
                                  width=max(1, px(2)), tags=("ring",))

    def _hover(self, key):
        self.hover = key
        self._paint()

    def _press(self, key):
        if key is None:
            return
        if key == "link":
            self.link[1]()
        elif self.on_nav:
            self.on_nav(key)

    def _focused(self, on):
        """The keyboard came: the ring on the page in use (or the first entry); it went: the ring goes."""
        entries = self._entries()
        if on and entries:
            if self.ring not in entries:
                self.ring = self.current if self.current in entries else entries[0]
        else:
            self.ring = None
        self._paint()

    def _move(self, by, key):
        """The ring along the entries; Tab past the last (Shift+Tab before the first) leaves the bar as Tab does."""
        entries = self._entries()
        if not entries or self.ring not in entries:
            return None
        i = entries.index(self.ring) + by
        if 0 <= i < len(entries):
            self.ring = entries[i]
            self._paint()
            return "break"
        if key in ("<Left>", "<Right>"):
            return "break"
        return None

    def set_current(self, key):
        """The page on show: its name lit, with the rule under it."""
        self.current = key
        self._paint()

    def set_under(self, under):
        """The page has moved (the bar is drawn dark, with its line) or is back at its top."""
        if under != self.under:
            self.under = under
            self.draw()

    def set_step(self, index):
        """The guide's step on show."""
        self.step = index
        self.draw()


# How long a page that came out shorter than its view reaches waits before it is measured again (ms): the rows made
# anew have their sizes within a few, in the same turn of the event loop.
SETTLE = 60


class ScrollArea(tk.Frame):
    """The page area, as the site's page: its field with the shards at the edges and the dots in the margins (drawn
    behind on the canvas, art.backdrop), the page's title and a line under it (set_heading), and the page's content in
    a column between margins (`inner`), all scrolling together with the mouse wheel."""

    # The margins either side of the column, the room above the title and under the content (logical pixels).
    MARGIN, TOP, BOTTOM, GAP = 32, 20, 28, 18

    def __init__(self, parent, ui, bg=theme.BG, offset=0, light=None, on_moved=None):
        super().__init__(parent, bg=bg)
        self.ui = ui
        # Where this area starts on the page (under the header, which draws the page's top) and how far the page's
        # lit top reaches; told when the page has moved from its top, or come back to it.
        self.offset, self.light, self.on_moved, self._moved = offset, light, on_moved, None
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Dark.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        px = ui.px
        self._window = self.canvas.create_window((px(self.MARGIN), px(self.TOP)), window=self.inner, anchor="nw")
        # The heading's items (the title's picture, the line under it) and where the content starts under them.
        self._heading, self._content_top = [], px(self.TOP)
        self._backdrop_job, self._backdrop_size, self._backdrop_item = None, None, None
        # The scrolled region's height as last set, and a shorter page waiting to be measured again before the region
        # shrinks (_relayout).
        self._region_height, self._shrink_job = 0, None
        # A dialog draws the window from the widgets (snapshot.py): this area's part is made when one asks.
        self.canvas.odq_picture = self._picture_on_show
        # The part of the wheel's turning that has not made a whole step yet (a touchpad sends it a little at a time).
        self._wheel_rest = 0.0
        self.canvas.configure(yscrollcommand=self._bar_set)
        # The canvas spans the whole width, its picture behind with it, so the page's backdrop goes on from the header's
        # to the window's edge; the scroll bar lies over its right edge when the page scrolls. The column keeps the bar's
        # room either way: the page then has one width whether it scrolls or not (without it, a page about as tall as
        # the area loops for ever: the bar narrows the page, the narrower page fits, the bar goes, and back).
        self.bar_room = self.bar.winfo_reqwidth()
        self.canvas.pack(fill="both", expand=True)
        # The content's height decides how far it scrolls, and how tall the picture behind it is.
        self.inner.bind("<Configure>", lambda e: self._relayout())
        # The column is as wide as the area less its margins, so text wraps instead of running off.
        self.canvas.bind("<Configure>", self._on_resize)
        # The wheel scrolls whatever is under the pointer, so bind only while the pointer is over this area. Each binding
        # is a Tcl command that holds this area: its commands go when the pointer leaves and when the area itself goes (a
        # rebuild of the window), or they would pile up, keep the area alive, and a turn of the wheel after a rebuild
        # would call a canvas that is gone. Sequence -> the command bound to it.
        self._wheel_commands = {}
        self.bind("<Enter>", lambda e: self._wheel(True))
        self.bind("<Leave>", lambda e: self._wheel(False))
        self.bind("<Destroy>", lambda e: e.widget is self and self._wheel(False), add="+")
        # A control the keyboard reaches (Tab) below or above the part of the page in view comes into view: the window's
        # own binding for <FocusIn> hears every widget of the window take the keyboard, and this area answers for its
        # own. Its line goes from that binding when the area goes (a rebuild of the window), as the wheel's do.
        self._focus_command = self.register(self._focus_came)
        self._focus_line = "%s %%W" % self._focus_command
        root = self._root()
        root.tk.call("bind", root._w, "<FocusIn>", "+" + self._focus_line)
        self.bind("<Destroy>", lambda e: e.widget is self and self._focus_gone(), add="+")
        # A shorter page's second look goes with the area: its timer would call a command that went with it.
        self.bind("<Destroy>", lambda e: e.widget is self and self._shrink_job is not None
                  and self.after_cancel(self._shrink_job), add="+")

    def _bar_set(self, first, last):
        """Show the scroll bar only when the content is taller than the area, in the room the strip keeps for it; tell
        the header when the page has moved from its top."""
        moved = float(first) > 0.0
        if self.on_moved is not None and moved != self._moved:
            self._moved = moved
            self.on_moved(moved)
        if float(first) <= 0.0 and float(last) >= 1.0:
            if self.bar.winfo_manager():
                self.bar.place_forget()
        elif not self.bar.winfo_manager():
            # Over the canvas's right edge, in the room the column keeps for it.
            self.bar.place(relx=1.0, y=0, relheight=1.0, anchor="ne")
        self.bar.set(first, last)

    def set_heading(self, title, description=""):
        """The page's title as the site's masthead (art.page_title) and one plain line under it, in the margin's place
        above the content; "" for none."""
        from PIL import ImageTk
        px, c = self.ui.px, self.canvas
        for item in self._heading:
            c.delete(item)
        self._heading = []
        y = px(self.TOP)
        if title:
            picture, _baseline = art.page_title(title, self.ui.scale)
            self._title_image = ImageTk.PhotoImage(picture, master=c)
            # A dialog draws the window from the widgets (snapshot.py): the title's picture goes with the canvas's.
            self._title_picture = picture
            self._heading.append(c.create_image(px(self.MARGIN) - px(2), y, image=self._title_image, anchor="nw"))
            y += picture.height
        if description:
            self._heading.append(c.create_text(px(self.MARGIN), y + px(2), text=description, anchor="nw",
                                               font=self.ui.fonts.body, fill=theme.MUTED,
                                               width=max(px(200), self._column(c.winfo_width()))))
        self._place_content()

    def _place_content(self):
        """The content's top under the heading as it now wraps (the line under the title takes more lines in a
        narrower window), and the scrolled height after it."""
        px, c = self.ui.px, self.canvas
        y = px(self.TOP)
        if self._heading:
            y = c.bbox(self._heading[-1])[3]
        self._content_top = y + (px(self.GAP) if self._heading else 0)
        c.coords(self._window, px(self.MARGIN), self._content_top)
        self._relayout()

    def _column(self, width):
        """The column's width in an area `width` wide: between the margins, less the scroll bar's room."""
        return width - 2 * self.ui.px(self.MARGIN) - self.bar_room

    def _on_resize(self, event):
        px = self.ui.px
        # The column between the margins; labels wrap to their own box (follow_width).
        self.canvas.itemconfigure(self._window, width=max(1, self._column(event.width)))
        for item in self._heading:
            if self.canvas.type(item) == "text":
                self.canvas.itemconfigure(item, width=max(px(200), self._column(event.width)))
        self._place_content()

    def _relayout(self, settled=False):
        """The scrolled height: the content and the room under it, at least the area's own height; the picture behind
        drawn again for it (a moment later, once the sizes stop changing).

        A page that comes out shorter than where the part in view reaches keeps its height until it is measured again
        a moment later (_settle): part of a page made anew, as the ready check's rows each time the check comes back,
        is laid out once before its new rows have their size, and the canvas keeps its view inside its region, so a
        page scrolled to its foot would move up by those rows for good (Help after Repair: 88 px). `settled`: measured
        again, the page is as short as it says."""
        c = self.canvas
        width, seen = max(1, c.winfo_width()), max(1, c.winfo_height())
        bottom = self._content_top + self.inner.winfo_reqheight() + self.ui.px(self.BOTTOM)
        content = max(seen, bottom)
        height = content
        # Where the part in view ends on the page.
        reach = int(c.canvasy(0)) + seen
        if content < reach and not settled:
            # Shorter than the view reaches: the region stays as it was until the page has settled.
            height = max(content, self._region_height)
            if self._shrink_job is None:
                self._shrink_job = self.after(SETTLE, self._settle)
        elif self._shrink_job is not None:
            # As tall as the view reaches again (the rows have their size): nothing left to measure.
            self.after_cancel(self._shrink_job)
            self._shrink_job = None
        self._region_height = height
        c.configure(scrollregion=(0, 0, width, height))
        if self._backdrop_size != (width, content):
            if self._backdrop_job is not None:
                self.after_cancel(self._backdrop_job)
            self._backdrop_job = self.after(60, self._draw_backdrop)

    def _settle(self):
        """The page measured again once its sizes have settled: as short as it is now, the region follows, and a view
        past its new foot moves up to it."""
        self._shrink_job = None
        if not self.canvas.winfo_exists():
            return
        # Every size the page is still working out, worked out first: what is measured is the page as it stays.
        self.update_idletasks()
        self._relayout(settled=True)

    def _draw_backdrop(self):
        from PIL import ImageTk
        self._backdrop_job = None
        c = self.canvas
        if not c.winfo_exists():
            return
        width, seen = max(1, c.winfo_width()), max(1, c.winfo_height())
        height = max(seen, self._content_top + self.inner.winfo_reqheight() + self.ui.px(self.BOTTOM))
        self._backdrop_size = (width, height)
        picture = art.backdrop(width, height, self.ui.scale, offset=self.offset, top=self.light)
        self._backdrop_image = ImageTk.PhotoImage(picture, master=c)
        # A dialog draws the window from the widgets (snapshot.py): the page's picture, its title put on it then.
        self._backdrop_picture = picture
        if self._backdrop_item is None:
            self._backdrop_item = c.create_image(0, 0, image=self._backdrop_image, anchor="nw")
        else:
            c.itemconfigure(self._backdrop_item, image=self._backdrop_image)
        c.tag_lower(self._backdrop_item)

    def _picture_on_show(self):
        """The picture a dialog draws for this area (snapshot.py), made when one asks: the part of the page's picture
        on show, as far down as the page is scrolled, with the title's picture where it now is. A copy of the whole
        page's picture kept for it would hold the page's height again (13.6 MB at 200 %)."""
        behind = getattr(self, "_backdrop_picture", None)
        if behind is None:
            return None
        c = self.canvas
        top = min(int(c.canvasy(0)), behind.height - 1)
        # Never past the picture's edge (a resize not drawn for yet): the canvas's own colour shows there.
        picture = behind.crop((0, top, min(behind.width, max(1, c.winfo_width())),
                               min(behind.height, top + max(1, c.winfo_height()))))
        title = getattr(self, "_title_picture", None)
        if title is not None and self._heading and c.type(self._heading[0]) == "image":
            x, y = (int(v) for v in c.coords(self._heading[0]))
            picture.paste(title, (x, y - top), title)
        return picture

    def _wheel(self, on):
        """The wheel bound for the whole window to this area (on), or no longer (off); the last binding's commands go
        either way, so that a second <Enter> without a <Leave> leaves nothing behind."""
        root = self._root()
        for sequence, command in self._wheel_commands.items():
            try:
                # The window's binding goes only while it still calls this area's command (its script runs
                # "[command %# ...]"): a new page area the pointer reached first has bound the wheel to itself since.
                if "[%s " % command in self.tk.call("bind", "all", sequence):
                    self.unbind_all(sequence)
                # Deleted through the root: Python 3.12 keeps bind_all's commands on the root's own list to delete when
                # the window closes, and a command deleted behind its back would make that close fail.
                root.deletecommand(command)
            except tk.TclError:
                # The command is gone already: the window closed first, its bindings and commands with it.
                pass
        self._wheel_commands = {}
        if on:
            for sequence, handler in (("<MouseWheel>", self._on_wheel),                                # Windows, macOS
                                      ("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units")),  # X11 wheel up
                                      ("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))):  # X11 wheel down
                self._wheel_commands[sequence] = self.bind_all(sequence, handler)

    def _on_wheel(self, event):
        # Windows reports 120 a notch (3 steps), a touchpad much less at a time: what does not make a whole step yet is
        # kept for the next turn instead of being dropped.
        self._wheel_rest += -event.delta / 40.0
        steps = int(self._wheel_rest)
        if steps:
            self._wheel_rest -= steps
            self.canvas.yview_scroll(steps, "units")

    def to_top(self):
        self.canvas.yview_moveto(0)

    def _focus_came(self, path):
        """A widget of the window took the keyboard (`path`, Tk's name for it): one on this page is shown."""
        try:
            widget = self.nametowidget(path)
        except KeyError:
            # Not one of this program's widgets as Python knows them (a drop-down's own list): nothing to show.
            return
        # The widget that has the keyboard alone: Tk says <FocusIn> to each frame round it as well, and showing a frame
        # as tall as the page would throw the page to its foot.
        if widget is not self.focus_get():
            return
        # Only what lies on this page: the menu, the bottom bar and a dialog have places of their own.
        if str(widget).startswith(str(self.inner) + "."):
            self.show_widget(widget)

    def _focus_gone(self):
        """This area goes: its line leaves the window's <FocusIn> binding, and its command goes with it."""
        root = self._root()
        try:
            script = root.tk.call("bind", root._w, "<FocusIn>")
            # The binding's script is its lines joined by newlines: this area's line out, the others as they were.
            kept = "\n".join(line for line in str(script).split("\n") if line.strip() != self._focus_line)
            root.tk.call("bind", root._w, "<FocusIn>", kept)
            # Deleted through this area, which made it (register): its own list of commands to delete loses it too, so
            # Tk is not asked to delete it a second time when the area finishes going.
            self.deletecommand(self._focus_command)
        except tk.TclError:
            # The window went first, its bindings and commands with it.
            pass

    def show_widget(self, widget):
        """Scroll so that `widget`, inside this page, is in view with a little room round it; nothing when it is."""
        c = self.canvas
        if not (widget.winfo_exists() and c.winfo_exists()) or not widget.winfo_ismapped():
            return
        region = [float(v) for v in str(c.cget("scrollregion")).split()] if c.cget("scrollregion") else []
        seen = c.winfo_height()
        if len(region) != 4 or region[3] <= seen:
            # The whole page is in view: nothing to scroll.
            return
        # The widget's top and foot on the page (the scrolled region's own pixels), from where it is on screen.
        top = widget.winfo_rooty() - c.winfo_rooty() + c.canvasy(0)
        bottom = top + widget.winfo_height()
        view = c.canvasy(0)
        room = self.ui.px(24)
        if top - room < view:
            target = top - room
        elif bottom + room > view + seen:
            target = bottom + room - seen
        else:
            return
        # Never past either end of the page.
        target = max(0.0, min(target, region[3] - seen))
        c.yview_moveto(target / region[3])


# A wrapping label's width before its box is laid out (follow_width).
START_WRAP = 120


def follow_width(ui, widget, margin=0, beside=()):
    """Keep a label's wrap width equal to its box's width, less the widgets beside it on the same line.

    The box (the label's master) gets its width from the page above it, never from the label, so the wrap
    width settles in one pass whatever the window size.
    """
    master = widget.master

    def inner_padding(w):
        """The room a frame keeps inside its edge (its own padx and border) on both sides."""
        total = 0
        for option in ("padx", "bd", "highlightthickness"):
            try:
                # Tk returns screen distances as objects; winfo_pixels turns any of them into pixels.
                total += w.winfo_pixels(str(w.cget(option)))
            except tk.TclError:
                # Not every widget has every option (a Canvas has no padx).
                pass
        return 2 * total

    def own_padding(w):
        """The space the label's own pack or grid padding takes on both sides."""
        try:
            info = w.pack_info() if w.winfo_manager() == "pack" else w.grid_info()
        except tk.TclError:
            return 0
        pad = info.get("padx", 0)
        if isinstance(pad, (tuple, list)):
            # (left, right), as given to pack or grid.
            return sum(w.winfo_pixels(str(p)) for p in pad)
        return 2 * w.winfo_pixels(str(pad))

    def update(event=None):
        width = master.winfo_width()
        if width <= 1 or not widget.winfo_exists():
            return
        taken = sum(b.winfo_reqwidth() for b in beside if b.winfo_exists())
        # The label's own edge and padding come on top of its wrapped text: a line that fills the wrap width exactly
        # would otherwise be a few pixels wider than the room, and Tk would cut it.
        room = width - inner_padding(master) - own_padding(widget) - inner_padding(widget) - taken - ui.px(margin)
        widget.configure(wraplength=max(ui.px(120), room))

    # Start narrow: a label that first asks for its whole line would widen its box, and the box's width would
    # then come from the label instead of the page. Narrow first, the box takes the page's width, then the
    # label grows into it.
    widget.configure(wraplength=ui.px(START_WRAP))
    master.bind("<Configure>", update, add="+")
    widget.after_idle(update)


def focus_ring(widget, ui, bg):
    """Reached with Tab: a cyan ring while the widget has the keyboard, the background's colour otherwise."""
    widget.configure(takefocus=1, highlightthickness=max(1, ui.px(2)), highlightbackground=bg,
                     highlightcolor=theme.CYAN)


def link(parent, ui, text, command, fg=None, bg=None, font=None, chevron=True):
    """Words that do something: a click, or Enter or Space once Tab has reached them (a cyan ring shows it). In the
    page's colour with a chevron after them by default; on the parent's colour unless told."""
    bg = bg or parent.cget("bg")
    words = tk.Label(parent, text=text + ("  " + theme.ICON["chevron"] if chevron else ""),
                     font=font or ui.fonts.body_bold, fg=fg or theme.OK, bg=bg, cursor="hand2")
    focus_ring(words, ui, bg)
    for sequence in ("<Button-1>", "<Return>", "<space>"):
        words.bind(sequence, lambda e: command())
    return words


def label(parent, ui, text, font=None, fg=theme.TEXT, bg=None, wrap_margin=None, beside=(), **kw):
    """A text label in the theme, on its parent's colour unless told; with wrap_margin it wraps at its box's width minus
    that margin."""
    bg = bg or parent.cget("bg")
    w = tk.Label(parent, text=text, font=font or ui.fonts.body, fg=fg, bg=bg, justify="left", anchor="w", **kw)
    if wrap_margin is not None:
        follow_width(ui, w, wrap_margin, beside)
    return w


def divider(parent, ui, bg=theme.DIVIDER, pady=12):
    """The faint line between two rows of a card (white at 7.5 % on the deck)."""
    line = tk.Frame(parent, bg=bg, height=1)
    line.pack(fill="x", pady=ui.px(pady))
    return line


def lamp(parent, ui, colour, bg=theme.PANEL, hollow=False):
    """A state's small light with its glow (art.lamp), as a label; `hollow` draws it as a ring."""
    from PIL import ImageTk
    picture = art.lamp(colour, ui.scale, bg=bg, hollow=hollow)
    image = ImageTk.PhotoImage(picture, master=parent)
    light = tk.Label(parent, image=image, bg=bg, bd=0)
    # Kept on the label: Tk drops a picture the moment Python forgets it. A dialog draws the window from it.
    light.odq_image, light.odq_picture = image, picture
    return light


class Button(tk.Canvas):
    """A button cut at two corners like PLAY. kind: 'primary' (filled with the site's lime, the page's main action),
    'secondary' (quiet metal that lights up under the pointer), 'danger' (metal tinted red, filled red under the
    pointer: removing or starting over).

    The face is a picture (art.button_face); the words stay Tk text, so they are drawn as crisply as every other label.
    """

    # Each kind's look in art.BUTTON_LOOKS.
    LOOKS = {"primary": "home", "secondary": "neutral", "danger": "danger_quiet"}
    # The site's control height for buttons in a page (between its 34 px and 42 px ones).
    HEIGHT = 36

    def __init__(self, parent, ui, text, command, kind="secondary"):
        self.ui, self.bg = ui, parent.cget("bg")
        super().__init__(parent, bg=self.bg, highlightthickness=0, bd=0, cursor="hand2")
        self.command, self.enabled, self.words, self.state = command, True, None, "normal"
        self.focused = False            # the keyboard is on it: its face shows the ring
        self._take_look(kind)
        self.set_text(text)
        self.bind("<Enter>", lambda e: self._paint("hover" if self.enabled else "disabled"))
        self.bind("<Leave>", lambda e: self._paint("normal" if self.enabled else "disabled"))
        self.bind("<ButtonPress-1>", lambda e: self.enabled and self._paint("pressed"))
        self.bind("<ButtonRelease-1>", self._click)
        # The keyboard presses it as the mouse does: Tab to it (its face shows a ring), then Enter or Space. The ring is
        # part of the face: a canvas's own highlight would cover the face's edge and change the button's size.
        self.configure(takefocus=1)
        self.bind("<FocusIn>", lambda e: self._focus(True))
        self.bind("<FocusOut>", lambda e: self._focus(False))
        self.bind("<Return>", lambda e: self.press())
        self.bind("<space>", lambda e: self.press())

    def _take_look(self, kind):
        """The kind's look and its words' colour in each state."""
        self.look = self.LOOKS[kind]
        colours = art.BUTTON_LOOKS[self.look]
        self.text_colour = {"normal": colours["text"], "hover": colours.get("hover_text", colours["text"]),
                            "pressed": colours.get("hover_text", colours["text"]), "disabled": theme.FAINT}

    def set_kind(self, kind):
        """Another kind (a page's main action lit in lime, or quiet while PLAY is the lit one), its faces drawn
        again."""
        if self.LOOKS[kind] == self.look:
            return
        self._take_look(kind)
        # Drawn again for the same words: set_text draws only for words it does not show yet.
        words, self.words = self.words, None
        self.set_text(words)

    def set_text(self, text):
        """Show other words (the guide's last Next becomes PLAY): the button takes the width they need."""
        if text == self.words:
            return
        self.words = text
        fonts, px = self.ui.fonts, self.ui.px
        # The words with the site's room either side of them.
        width = px(18) + fonts.body_bold.measure(text) + px(18)
        height = px(self.HEIGHT)
        self.configure(width=width, height=height)
        self.delete("all")
        # Each state's face, without and with the keyboard's ring (a disabled button never has the keyboard).
        self.faces = {(state, ring): art.button_face((width, height), 0, self.look, state, ring, self.ui.scale,
                                                     bg=self.bg)
                      for state in ("normal", "hover", "pressed", "disabled") for ring in (False, True)
                      if not (ring and state == "disabled")}
        self.images = {key: ImageTk.PhotoImage(face, master=self) for key, face in self.faces.items()}
        self.face = self.create_image(0, 0, image=self.images[("normal", False)], anchor="nw")
        self.parts = [self.create_text(px(18), height // 2, text=text, font=fonts.body_bold, anchor="w")]
        self._paint(self.state if self.enabled else "disabled")

    def _paint(self, state):
        self.state = state
        key = (state, self.focused and state != "disabled")
        self.itemconfigure(self.face, image=self.images[key])
        for part in self.parts:
            self.itemconfigure(part, fill=self.text_colour[state])
        # A dialog draws the window behind it from the widgets (snapshot.py): this is the button's part.
        self.odq_picture = self.faces[key]

    def _focus(self, on):
        """The keyboard came or went: the face with or without its ring."""
        self.focused = on
        self._paint(self.state)

    def _click(self, event):
        # Only a release over the button counts, like a real button (drag off to cancel).
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        if not self.enabled:
            return
        self._paint("hover" if inside else "normal")
        if inside and self.command:
            self.command()

    def press(self):
        """What a click does, for the keyboard and the tests."""
        if self.enabled and self.command:
            self.command()

    def enable(self, on):
        self.enabled = on
        # Off, it is skipped by Tab as well as by the mouse.
        self.configure(cursor="hand2" if on else "arrow", takefocus=1 if on else 0)
        self._paint("normal" if on else "disabled")


class PlaySlab(tk.Label):
    """PLAY, as the launcher's bottom bar and the guide's last step show it: the lime slab with its corners cut
    (art.play_button), its word in the site's wide letters in the dark ink that reads on lime. It sits on the bar's own
    colour, its cut corners and its keyboard ring's place too, so the slab alone shows.

    set() says what PLAY can do: "ready" (lit, and lit further under the mouse), "waiting" (dark and still: something
    to fix first, or work under way) or "playing" (the game is open). command() runs on a click released over it (drag
    off to cancel), and on Enter or Space once Tab has reached it (a cyan ring)."""

    LOOKS = ("normal", "hover", "pressed", "disabled", "playing")
    # The slab's size (logical pixels).
    WIDTH, HEIGHT = 212, 50

    def __init__(self, parent, ui, words, command, bg=theme.STRIP):
        px = ui.px
        # Every look drawn once: the mouse and the state only swap them.
        self.pictures = {look: art.play_button(px(self.WIDTH), px(self.HEIGHT), state=look) for look in self.LOOKS}
        self.images = {look: ImageTk.PhotoImage(p, master=parent) for look, p in self.pictures.items()}
        super().__init__(parent, image=self.images["normal"], text=words, compound="center", font=ui.fonts.display_big,
                         fg=theme.OK_INK, bg=bg, cursor="hand2", bd=0, takefocus=1,
                         highlightthickness=max(1, px(2)), highlightbackground=bg, highlightcolor=theme.CYAN)
        self.command, self.words, self.state, self.mouse = command, words, "ready", None
        # A dialog draws the window behind it from the widgets (snapshot.py): the slab's own picture.
        self.odq_picture = self.pictures["normal"]
        self.bind("<Enter>", lambda e: self._mouse("hover"))
        self.bind("<Leave>", lambda e: self._mouse(None))
        self.bind("<Button-1>", lambda e: self._mouse("pressed"))
        self.bind("<ButtonRelease-1>", self._released)
        for key in ("<Return>", "<space>"):
            self.bind(key, lambda e: self.command())

    def set(self, state, words=None):
        """What PLAY can do now ("ready", "waiting" or "playing"), and its word when that changes too (PLAYING)."""
        self.state = state
        if words is not None:
            self.words = words
        self._paint()

    def _mouse(self, look):
        self.mouse = look
        self._paint()

    def _released(self, event):
        """The mouse's button came up: the command when it is still over the slab, else only its look back."""
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        self.mouse = "hover" if inside else None
        self._paint()
        if inside:
            self.command()

    def _paint(self):
        """The look follows the state first, then the mouse."""
        if self.state == "ready":
            look, ink = self.mouse or "normal", theme.OK_INK
        elif self.state == "playing":
            # PLAYING is read (4.5:1 and more on its slab).
            look, ink = "playing", theme.MUTED
        else:
            # A PLAY that waits is the dimmest text.
            look, ink = "disabled", theme.FAINT
        self.odq_picture = self.pictures[look]
        self.configure(image=self.images[look], text=self.words, fg=ink,
                       cursor="hand2" if self.state == "ready" else "arrow")


class Toggle(tk.Label):
    """An on/off switch as the site's (art.toggle); command(new_value) runs after each click."""

    def __init__(self, parent, ui, value, command, bg=None):
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg, cursor="hand2", bd=0)
        self.ui, self.value, self.command = ui, bool(value), command
        size = (ui.px(40), ui.px(22))
        # Both pictures are made once; a click only swaps them.
        self.pictures = {on: art.toggle(on, *size, bg=bg) for on in (True, False)}
        self.images = {on: ImageTk.PhotoImage(p, master=parent) for on, p in self.pictures.items()}
        self.configure(image=self.images[self.value])
        # A dialog draws the window behind it from the widgets (snapshot.py): this is the switch's part.
        self.odq_picture = self.pictures[self.value]
        self.bind("<Button-1>", lambda e: self.set(not self.value, notify=True))
        # Tab reaches it; Enter or Space switches it.
        focus_ring(self, ui, bg)
        # The pill shows this far in: the keyboard's ring, then the halo's room (setting_row lines controls up by it).
        self.odq_inset = int(self.cget("highlightthickness")) + art.TOGGLE_HALO
        self.bind("<Return>", lambda e: self.set(not self.value, notify=True))
        self.bind("<space>", lambda e: self.set(not self.value, notify=True))

    def set(self, value, notify=False):
        self.value = bool(value)
        self.configure(image=self.images[self.value])
        self.odq_picture = self.pictures[self.value]
        if notify:
            self.command(self.value)


class Segmented(tk.Frame):
    """A row of choices of which one is on, as the site's tabs: trapezoids in rail metal standing on a lime rule, the
    chosen one filled lime with dark words (art.tab_face). The words are Tk's, crisp at any scale."""

    # Each tab's room either side of its words, its height, the gap between tabs and the rule under them.
    PAD, HEIGHT, GAP, RULE = 20, 32, 3, 2

    def __init__(self, parent, ui, options, value, command, bg=None):
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.command, self.value, self.bg = ui, command, value, bg
        self.options = list(options)
        self.keys = [key for key, _ in self.options]
        px = ui.px
        widths = [ui.fonts.tab.measure(text) + 2 * px(self.PAD) for _, text in self.options]
        self.boxes, x = [], 0
        for w in widths:
            self.boxes.append((x, w))
            x += w + px(self.GAP)
        total = x - px(self.GAP)
        height = px(self.HEIGHT) + px(self.RULE)
        self.canvas = tk.Canvas(self, width=total, height=height, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.canvas.pack()
        # The faces for each tab and state, made once: a click only swaps them.
        self.faces = {(i, state): art.tab_face(w, px(self.HEIGHT), state, ui.scale, bg=bg)
                      for i, (_x, w) in enumerate(self.boxes) for state in ("normal", "hover", "on")}
        self.images = {key: ImageTk.PhotoImage(face, master=self) for key, face in self.faces.items()}
        self.items, self.words, self.hover = [], [], None
        for i, ((x0, w), (_key, text)) in enumerate(zip(self.boxes, self.options)):
            self.items.append(self.canvas.create_image(x0, 0, image=self.images[(i, "normal")], anchor="nw"))
            self.words.append(self.canvas.create_text(x0 + w // 2, px(self.HEIGHT) // 2, text=text, font=ui.fonts.tab))
            for item in (self.items[-1], self.words[-1]):
                self.canvas.tag_bind(item, "<Button-1>", lambda e, k=self.keys[i]: self.set(k, notify=True))
                self.canvas.tag_bind(item, "<Enter>", lambda e, i=i: self._hover(i))
                self.canvas.tag_bind(item, "<Leave>", lambda e: self._hover(None))
        # The rule the tabs stand on, in lime.
        self.canvas.create_rectangle(0, px(self.HEIGHT), total, height, fill=theme.OK, width=0)
        # Tab reaches the row; the arrow keys move the choice.
        focus_ring(self, ui, bg)
        # The tabs show this far in: the keyboard's ring (setting_row lines controls up by it).
        self.odq_inset = int(self.cget("highlightthickness"))
        self.bind("<Left>", lambda e: self._step(-1))
        self.bind("<Right>", lambda e: self._step(1))
        self.set(value)

    def _hover(self, i):
        self.hover = i
        self._paint()

    def _paint(self):
        """Each tab's face and words: the chosen one lime with dark words, the one under the pointer lighter."""
        for i, key in enumerate(self.keys):
            state = "on" if key == self.value else ("hover" if i == self.hover else "normal")
            self.canvas.itemconfigure(self.items[i], image=self.images[(i, state)])
            self.canvas.itemconfigure(self.words[i], fill=theme.OK_INK if state == "on" else
                                      (theme.TEXT if state == "hover" else theme.MUTED))
        # A dialog draws the window behind it from the widgets (snapshot.py): the row as it looks now.
        from PIL import Image
        px = self.ui.px
        picture = Image.new("RGB", (int(self.canvas.cget("width")), int(self.canvas.cget("height"))),
                            art._rgb(self.bg))
        for i, key in enumerate(self.keys):
            state = "on" if key == self.value else ("hover" if i == self.hover else "normal")
            picture.paste(self.faces[(i, state)], (self.boxes[i][0], 0))
        picture.paste(art._rgb(theme.OK), (0, px(self.HEIGHT), picture.width, picture.height))
        self.canvas.odq_picture = picture

    def set(self, value, notify=False):
        self.value = value
        self._paint()
        if notify:
            self.command(value)

    def _step(self, by):
        """The choice before or after this one, as the keyboard moves it (no wrap at either end)."""
        i = self.keys.index(self.value) + by if self.value in self.keys else 0
        if 0 <= i < len(self.keys) and self.keys[i] != self.value:
            self.set(self.keys[i], notify=True)


class Slider(tk.Frame):
    """A 0-100 slider with its number beside it; command(value) runs when the drag ends. Its track is let into the card
    and runs from the slider's own left edge, so it starts on the same line as the controls above and under it; the knob
    stands on the track, inside its ends."""

    def __init__(self, parent, ui, value, command, bg=None, width=320):
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.command, self.value, self.bg = ui, command, int(value), bg
        self.w, self.h = ui.px(width), ui.px(26)
        self.colour = theme.OK
        self.knob_size = ui.px(18)
        self.knob_img = ImageTk.PhotoImage(art.knob(self.knob_size, ring=self.colour, scale=ui.scale), master=parent)
        self.canvas = tk.Canvas(self, width=self.w, height=self.h, bg=bg, highlightthickness=0, cursor="hand2")
        self.canvas.pack(side="left")
        self.number = tk.Label(self, text="", font=ui.fonts.body_bold, fg=theme.TEXT, bg=bg, width=4, anchor="e")
        self.number.pack(side="left", padx=(ui.px(10), 0))
        self.canvas.bind("<Button-1>", self._drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: self.command(self.value))
        # Tab reaches it; the arrow keys move it by 5 (Home and End to either end), each step saved as a drag's end is.
        focus_ring(self.canvas, ui, bg)
        # A canvas's ring covers its edge: the drawing starts inside it, and the track's left end that far in.
        self.inset = int(self.canvas.cget("highlightthickness"))
        self.odq_inset = self.inset
        for key, to in (("<Left>", lambda v: v - 5), ("<Right>", lambda v: v + 5), ("<Down>", lambda v: v - 5),
                        ("<Up>", lambda v: v + 5), ("<Home>", lambda v: 0), ("<End>", lambda v: 100)):
            self.canvas.bind(key, lambda e, to=to: self._key(to))
        self._draw()

    def _key(self, to):
        """A move from the keyboard: the new value, drawn and saved."""
        value = int(min(100, max(0, to(self.value))))
        if value != self.value:
            self.value = value
            self._draw()
            self.command(self.value)

    def _x(self, value):
        """Where a value's knob sits: its centre a knob's half inside either end of the track, so the knob never
        stands past the track's ends."""
        half = self.knob_size / 2.0
        return getattr(self, "inset", 0) + half + (self.w - 2 * half) * value / 100.0

    def _drag(self, event):
        half = self.knob_size / 2.0
        frac = (event.x - getattr(self, "inset", 0) - half) / float(max(1, self.w - 2 * half))
        self.value = int(round(min(1.0, max(0.0, frac)) * 100))
        self._draw()

    def _draw(self):
        c, mid = self.canvas, getattr(self, "inset", 0) + self.h // 2
        c.delete("all")
        thick = max(4, self.ui.px(6))
        # The track as a picture let into the card, lit up to the knob's middle, from the slider's left edge.
        fraction = (self._x(self.value) - getattr(self, "inset", 0)) / float(self.w)
        picture = art.slider_track(self.w, thick, fraction, self.colour, self.ui.scale, bg=self.bg)
        self._track_img = ImageTk.PhotoImage(picture, master=c)
        inset = getattr(self, "inset", 0)
        c.create_image(inset, mid, image=self._track_img, anchor="w")
        c.create_image(self._x(self.value), mid, image=self.knob_img)
        # A dialog draws the window behind it from the widgets (snapshot.py): the canvas as it looks now, the track and
        # the knob where they are.
        from PIL import Image
        whole = Image.new("RGB", (self.w + 2 * inset, self.h + 2 * inset), art._rgb(self.bg))
        whole.paste(picture, (inset, mid - thick // 2))
        knob = art.knob(self.knob_size, ring=self.colour, scale=self.ui.scale)
        whole.paste(knob, (int(self._x(self.value) - self.knob_size / 2.0), mid - self.knob_size // 2), knob)
        c.odq_picture = whole
        self.number.configure(text=str(self.value))


class Select(ttk.Combobox):
    """A drop-down of (value, text) pairs; command(value) runs on a choice. Each choice's words start with the same
    spaces (list_pad), closed and in the opened list, so that the two line up: the list's rows have no room of their
    own before their words, and the closed box's padding is less by as much (style_ttk). The choices are told apart by
    their place, never by their words."""

    def __init__(self, parent, ui, options, value, command, width=24):
        self.options = list(options)
        pad, _ = list_pad(ui)
        super().__init__(parent, values=[pad + t for _, t in self.options], state="readonly", width=width,
                         style="Dark.TCombobox", font=ui.fonts.body)
        self.command = command
        self.set_value(value)
        self.bind("<<ComboboxSelected>>", self._chosen)

    def set_value(self, value):
        for i, (v, _) in enumerate(self.options):
            if v == value:
                self.current(i)
                return
        if self.options:
            self.current(0)

    def _chosen(self, event):
        self.selection_clear()
        self.command(self.options[self.current()][0])


# The room between a setting's name and its control, in logical pixels.
LABEL_GAP = 18


def name_width(ui, names):
    """How wide a column of setting names must be for `names`: the widest of them in the names' font, and the room after
    it. Measured, never a number fixed for one system's font: Windows draws Pretendard wider than Linux does."""
    return max(ui.fonts.body_bold.measure(name) for name in names) + ui.px(LABEL_GAP)


def setting_row(parent, ui, title, control_factory, hint=None, bg=None):
    """A setting: its name on the left, the control on the right of it, the hint underneath. The page fits one column
    for its rows' names afterwards (fit_names); until then the row's own name sets it."""
    from opendmtq_client import i18n
    bg = bg or parent.cget("bg")
    row = tk.Frame(parent, bg=bg)
    row.columnconfigure(1, weight=1)
    # The name in each language the launcher speaks: the page's layout is the same in both, whichever is on show.
    row.odq_names = i18n.every_language(title)
    row.columnconfigure(0, minsize=name_width(ui, row.odq_names))
    tk.Label(row, text=title, font=ui.fonts.body_bold, fg=theme.TEXT, bg=bg, anchor="w",
             width=0).grid(row=0, column=0, sticky="w", padx=(0, ui.px(LABEL_GAP)))
    control = control_factory(row)
    # Every control's visible left edge on one line: a switch, a row of tabs and a slider keep room for the keyboard's
    # ring (and the switch for its halo) before what shows, so the others are set in by as much.
    align = max(1, ui.px(2)) + art.TOGGLE_HALO
    control.grid(row=0, column=1, sticky="w", padx=(max(0, align - getattr(control, "odq_inset", 0)), 0))
    hint_label = None
    if hint:
        hint_label = label(row, ui, hint, font=ui.fonts.small, fg=theme.MUTED, bg=bg, wrap_margin=4)
        hint_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(ui.px(4), 0))
    row.control, row.hint = control, hint_label
    return row


def fit_names(container, ui, more=()):
    """One column for the names of every setting row under `container` (a page, or a step of the guide), as wide as the
    widest of them in either language and of `more` (the names of rows a choice brings or takes on that page, counted
    whether shown or not), so that the controls of a page start on one line and stay there as rows come and go. Returns
    the column's width (0 for a page without settings)."""
    rows, found = [], [container]
    # Every widget under the container, without recursion (cards, their bodies, the rows in them).
    while found:
        widget = found.pop()
        if hasattr(widget, "odq_names"):
            rows.append(widget)
        found.extend(widget.winfo_children())
    names = [name for row in rows for name in row.odq_names] + list(more)
    if not names:
        return 0
    width = name_width(ui, names)
    for row in rows:
        row.columnconfigure(0, minsize=width)
    return width


class Card(tk.Frame):
    """A panel as the site's cards: the deck's colour with no border, the top-right corner cut, the site's 24 px inside,
    and its title in Pretendard Bold with nothing after it. Content goes into `body`; `head` holds the title and
    anything at its right end."""

    CUT = 16

    def __init__(self, parent, ui, title=None, pad=24):
        outside = parent.cget("bg")
        super().__init__(parent, bg=theme.PANEL)
        self.body = tk.Frame(self, bg=theme.PANEL, padx=ui.px(pad), pady=ui.px(pad - 4))
        self.body.pack(fill="both", expand=True)
        self.head = None
        if title:
            self.head = tk.Frame(self.body, bg=theme.PANEL)
            self.head.pack(fill="x", pady=(0, ui.px(12)))
            tk.Label(self.head, text=title, font=ui.fonts.card_title, fg=theme.TEXT, bg=theme.PANEL).pack(side="left")
        # The cut: a small picture over the square corner, the page's colour beyond it.
        cut = ui.px(self.CUT)
        picture = art.corner(cut, theme.PANEL, outside)
        self._corner = ImageTk.PhotoImage(picture, master=self)
        corner = tk.Label(self, image=self._corner, bd=0, highlightthickness=0, bg=outside)
        corner.odq_picture = picture
        corner.place(relx=1.0, x=-cut, y=0, width=cut, height=cut)


def check_line(parent, ui, state, text, action_text=None, action=None, bg=theme.PANEL, value=None):
    """A ready-check row as the site's state rows: a small lamp (a lime dot fine, a yellow ring will change, a red dot a
    problem), the words, and at the right end the value or the way to fix it."""
    row = tk.Frame(parent, bg=bg)
    colour = {"ok": theme.OK, "change": theme.WARN, "bad": theme.BAD}[state]
    # What will change is a ring, so that it is told from what is fine by its shape too, not by its colour alone.
    light = lamp(row, ui, colour, bg=bg, hollow=state == "change")
    light.pack(side="left", anchor="n", pady=(ui.px(1), 0))
    beside = [light]
    if action_text and action:
        # The way to fix it, reached by the mouse or the keyboard.
        fix = link(row, ui, action_text, action, bg=bg)
        fix.pack(side="right", anchor="n")
        beside.append(fix)
    elif value:
        what = tk.Label(row, text=value, font=ui.fonts.body, fg=theme.MUTED, bg=bg)
        what.pack(side="right", anchor="n")
        beside.append(what)
    words = label(row, ui, text, fg=theme.TEXT, bg=bg, wrap_margin=24, beside=beside)
    words.pack(side="left", fill="x", padx=(ui.px(6), 0))
    return row


# Text selected in a field: the launcher's own colours, as a drop-down's chosen row has them, never Windows' blue.
SELECTION = {"selectbackground": theme.RAIL_UP, "selectforeground": theme.TEXT, "selectborderwidth": 0}


def entry(parent, ui, width=18, secret=False):
    """A text field as the site's: a dark field with a one-pixel seam, lime round it while typing."""
    field = tk.Entry(parent, width=width, font=ui.fonts.body, bg=theme.FIELD, fg=theme.TEXT, insertbackground=theme.TEXT,
                     relief="flat", highlightthickness=1, highlightbackground=theme.LINE, highlightcolor=theme.OK,
                     show="\u2022" if secret else "", **SELECTION)
    return field


class Field(tk.Canvas):
    """A text field as the launcher's pages have it: the site's dark field sunk into its card (art.field_face: dark
    edges along its top and left, the light along its foot), the accent round it while it is typed in, brighter edges
    under the pointer; as tall as a button, so a field and the buttons beside it stand on one line and one middle. The
    typing goes to `entry`, a plain Tk entry inside it; a click anywhere on the field puts the caret there."""

    def __init__(self, parent, ui, width=18, secret=False):
        self.ui, bg = ui, parent.cget("bg")
        px = ui.px
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, cursor="xterm", takefocus=0)
        # Selected words in the launcher's colours (SELECTION), not Windows' blue.
        self.entry = tk.Entry(self, width=width, font=ui.fonts.body, bg=theme.FIELD, fg=theme.TEXT,
                              insertbackground=theme.TEXT, relief="flat", bd=0, highlightthickness=0,
                              show="\u2022" if secret else "", **SELECTION)
        # The words' room either side of them, and the button's height.
        self.pad = px(10)
        width_px, height_px = self.entry.winfo_reqwidth() + 2 * self.pad, px(Button.HEIGHT)
        self.configure(width=width_px, height=height_px)
        self.faces = {state: art.field_face(width_px, height_px, state, ui.scale, bg=bg)
                      for state in ("normal", "hover", "focus")}
        self.images = {state: ImageTk.PhotoImage(face, master=self) for state, face in self.faces.items()}
        self.face = self.create_image(0, 0, image=self.images["normal"], anchor="nw")
        # The entry in the middle of the face, between its rooms.
        self.create_window(self.pad, height_px // 2, window=self.entry, anchor="w", width=width_px - 2 * self.pad)
        self.focused, self.under = False, False
        self.entry.bind("<FocusIn>", lambda e: self._paint(focused=True), add="+")
        self.entry.bind("<FocusOut>", lambda e: self._paint(focused=False), add="+")
        for widget in (self, self.entry):
            widget.bind("<Enter>", lambda e: self._paint(under=True), add="+")
            widget.bind("<Leave>", lambda e: self._paint(under=False), add="+")
        # A click on the face beside the words: the caret at their end, as a click past the words in the entry does.
        self.bind("<Button-1>", lambda e: (self.entry.focus_set(), self.entry.icursor("end")))
        self._paint()

    def _paint(self, focused=None, under=None):
        """The face for the field's state: the accent while typed in, brighter edges under the pointer, else normal."""
        if focused is not None:
            self.focused = focused
        if under is not None:
            self.under = under
        state = "focus" if self.focused else ("hover" if self.under else "normal")
        self.itemconfigure(self.face, image=self.images[state])
        # A dialog draws the window behind it from the widgets (snapshot.py): the face as it looks now.
        self.odq_picture = self.faces[state]


class KeyBox(tk.Canvas):
    """A lane's key as the Controls page shows it: a box let into its card as a text field is (art.field_face), as tall
    as a button, the key's name in it and, in grey after the name, what this PC's keyboard prints at its place when that
    says more (keys.beside); an empty box shows a grey + (a second key to add). While it waits for a key (set_waiting)
    the accent goes round it, as round a field while it is typed in; under the pointer its edges are brighter; Tab
    reaches it, the keyboard's cyan ring round it while it has the keyboard and does not wait."""

    # The room either side of the words, as a field keeps it, and between the name and what the keyboard prints (logical
    # pixels).
    PAD, GAP = 10, 6

    def __init__(self, parent, ui, key=None, printed=None):
        self.ui, self.bg = ui, parent.cget("bg")
        px = ui.px
        super().__init__(parent, bg=self.bg, highlightthickness=0, bd=0, cursor="hand2")
        # The key it shows (None: the empty box), and the grey print beside it (None: nothing more to say).
        self.key, self.printed = key, printed
        self.waiting, self.under = False, False
        # Tab reaches it: the ring round it is the canvas's own, so its drawing starts inside the ring.
        focus_ring(self, ui, self.bg)
        self.inset = int(self.cget("highlightthickness"))
        self.odq_inset = self.inset
        name_font, print_font = ui.fonts.body_bold, ui.fonts.small
        words = key or "+"
        # The words' width: the name, then the print after its gap.
        name_width = name_font.measure(words)
        words_width = name_width + (px(self.GAP) + print_font.measure(printed) if printed else 0)
        height = px(Button.HEIGHT)
        # A key of one letter is a square box, as a key's cap; a longer name widens it.
        width = max(height, words_width + 2 * px(self.PAD))
        self.configure(width=width, height=height)
        # Each state's face, made once: the pointer and the wait only swap them.
        self.faces = {state: art.field_face(width, height, state, ui.scale, bg=self.bg)
                      for state in ("normal", "hover", "focus")}
        self.images = {state: ImageTk.PhotoImage(face, master=self) for state, face in self.faces.items()}
        self.face = self.create_image(self.inset, self.inset, image=self.images["normal"], anchor="nw")
        # The words in the box's middle, the name in the labels' face, the print smaller and grey.
        x, middle = self.inset + (width - words_width) // 2, self.inset + height // 2
        self.create_text(x, middle, text=words, font=name_font, fill=theme.TEXT if key else theme.MUTED, anchor="w")
        if printed:
            self.create_text(x + name_width + px(self.GAP), middle, text=printed, font=print_font, fill=theme.MUTED,
                             anchor="w")
        self.bind("<Enter>", lambda e: self._paint(under=True))
        self.bind("<Leave>", lambda e: self._paint(under=False))
        self._paint()

    def set_waiting(self, on):
        """Waiting for a key (the accent round it, the cyan ring away: the accent says where the key goes), or not."""
        self.waiting = bool(on)
        self.configure(highlightcolor=self.bg if self.waiting else theme.CYAN)
        self._paint()

    def _paint(self, under=None):
        """The face for the box's state: the accent while it waits, brighter edges under the pointer, else normal."""
        if under is not None:
            self.under = under
        state = "focus" if self.waiting else ("hover" if self.under else "normal")
        self.itemconfigure(self.face, image=self.images[state])
        # A dialog draws the window behind it from the widgets (snapshot.py): the face where it shows, inside the ring's
        # room in the card's colour.
        from PIL import Image
        face = self.faces[state]
        whole = Image.new("RGB", (face.width + 2 * self.inset, face.height + 2 * self.inset), art._rgb(self.bg))
        whole.paste(face, (self.inset, self.inset))
        self.odq_picture = whole


class Progress(tk.Frame):
    """A progress bar with its words under it (a download): set(fraction, text) moves it; fraction None shows the
    track alone, for work whose size is not known yet."""

    def __init__(self, parent, ui, width=420, bg=None):
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.bg = ui, bg
        self.w, self.h = ui.px(width), ui.px(8)
        self.colour = theme.OK
        self.picture = tk.Label(self, bg=bg, bd=0)
        self.picture.pack(anchor="w")
        self.words = tk.Label(self, text="", font=ui.fonts.small, fg=theme.MUTED, bg=bg, anchor="w", justify="left")
        self.words.pack(anchor="w", pady=(ui.px(6), 0))
        self.fraction = None
        self.set(None, "")

    def set(self, fraction, text):
        """Show `fraction` (0 to 1, or None) done, and the words under the bar."""
        self.fraction = fraction
        picture = art.bar(self.w, self.h, fraction or 0.0, self.colour)
        # Kept on the widget: Tk drops a picture the moment Python forgets it.
        self.image = ImageTk.PhotoImage(picture, master=self)
        self.picture.configure(image=self.image)
        # A dialog draws the window behind it from the widgets (snapshot.py): this is the bar's part.
        self.picture.odq_picture = picture
        self.words.configure(text=text)
