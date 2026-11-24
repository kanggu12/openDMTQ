"""The launcher's building blocks, drawn to match its theme instead of the Windows defaults.

Tk's stock widgets look like 1990s Windows on a dark background, so the controls here are Labels and Canvases
with images from art.py. Each keeps its own images alive (Tk drops an image the moment Python forgets it).
"""

import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from opendmtq_client import art, theme


class Ui:
    """What every widget needs to draw itself: the root, the fonts, the DPI scale and the words. A page's main button
    and its switches that are on are lit in the site's lime (theme.OK), the one colour for what is in use; links are in
    the words' own colour with a chevron after them (link)."""

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


class Rail(tk.Frame):
    """The column down the window's left side, as openDMT3's launcher has it: the wordmark with the version beside it
    at its top (`brand`, a picture), then the menu (`nav`: the pages, one under another) or the first-start guide's
    steps (`steps`), and at its foot what the window puts there (`foot`: the status and PLAY, or the guide's Back and
    Next), placed over the column's foot by the window so that Tab reaches it after the page. Opaque, on the strip's
    colour, with a seam along its right edge where the page begins."""

    # The column's width, the room inside it either side, above the wordmark, and under it (logical pixels).
    WIDTH, EDGE, TOP, UNDER_BRAND = 248, 18, 22, 24

    def __init__(self, parent, ui, brand, nav=(), on_nav=None, steps=()):
        px = ui.px
        super().__init__(parent, bg=theme.STRIP, width=px(self.WIDTH))
        self.ui = ui
        # Its own width whatever it holds.
        self.pack_propagate(False)
        # The seam along its right edge: the page's field starts after it.
        tk.Frame(self, bg=theme.SEAM, width=max(1, px(1))).pack(side="right", fill="y")
        image = ImageTk.PhotoImage(brand, master=self)
        self.brand = tk.Label(self, image=image, bg=theme.STRIP, bd=0)
        # Kept on the label: Tk drops a picture the moment Python forgets it. A dialog draws the window from it.
        self.brand.odq_image, self.brand.odq_picture = image, brand
        self.brand.pack(side="top", anchor="w", padx=(px(self.EDGE), 0), pady=(px(self.TOP), px(self.UNDER_BRAND)))
        self.list = RailList(self, ui, nav=nav, on_nav=on_nav, steps=steps)
        self.list.pack(side="top", fill="x")

    def inner_width(self):
        """The width of what the column holds between its rooms either side (the foot's buttons, PLAY's slab)."""
        return self.ui.px(self.WIDTH) - 2 * self.ui.px(self.EDGE) - max(1, self.ui.px(1))

    def set_current(self, key):
        """The page on show, lit in the menu."""
        self.list.set_current(key)

    def set_step(self, index):
        """The guide's step on show."""
        self.list.set_step(index)


class RailList(tk.Canvas):
    """The column's list: the menu's pages, or the guide's steps, one under another.

    The menu: each page's name in the wide face, English in both languages as the site's and the game's menus are; ash,
    white under the pointer; the page on show lit, its name in lime on a raised slab with the cards' cut corner (no
    stripe along its edge: the slab and the lime name say it). The keyboard reaches it first: Tab and Shift+Tab move the
    cyan ring along the names, then on to the page; the arrow keys move the ring; Enter or Space opens the page with the
    ring.

    The guide's steps: each step's number large and leaning, its name beside it; the step on show on the raised slab,
    its number in lime and its name white, the steps taken with their numbers in lime, the steps to come grey. They
    take no keyboard (Back and Next move along them)."""

    # A name's height and the gap between two, the room before a name inside its slab, the slab's cut corner, and a
    # step's height (logical pixels).
    ITEM_H, ITEM_GAP, NAME_PAD, CUT, STEP_H = 42, 4, 16, 10, 50
    # The room a step's number takes before its name.
    NUMBER_W = 34

    def __init__(self, parent, ui, nav=(), on_nav=None, steps=()):
        px = ui.px
        self.ui = ui
        self.nav, self.on_nav, self.steps = list(nav), on_nav, list(steps)
        count = len(self.nav) or len(self.steps)
        row = px(self.ITEM_H) if self.nav else px(self.STEP_H)
        height = count * row + max(0, count - 1) * px(self.ITEM_GAP)
        super().__init__(parent, height=height, bg=theme.STRIP, highlightthickness=0, bd=0,
                         takefocus=1 if self.nav else 0)
        # The page on show, the name under the pointer, the name with the keyboard's ring, the guide's step on show.
        self.current, self.hover, self.ring, self.step = None, None, None, 0
        # Each entry's box (x0, y0, x1, y1), known once drawn.
        self.boxes = {}
        self._job = None
        self.bind("<Configure>", lambda e: self._queue())
        if self.nav:
            for key, move in (("<Tab>", 1), ("<Shift-Tab>", -1), ("<ISO_Left_Tab>", -1), ("<Down>", 1), ("<Up>", -1)):
                self.bind(key, lambda e, m=move, k=key: self._move(m, k))
            for key in ("<Return>", "<space>"):
                self.bind(key, lambda e: self._press(self.ring))
            self.bind("<FocusIn>", lambda e: self._focused(True))
            self.bind("<FocusOut>", lambda e: self._focused(False))
            self.bind("<Motion>", self._pointer)
            self.bind("<Leave>", lambda e: self._hover(None))
            self.bind("<Button-1>", lambda e: self._press(self._at(e.y)))
            self.configure(cursor="hand2")

    def _queue(self):
        """Draw again once the size settles (a drag fires many resize events)."""
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(10, self.draw)

    def _entries(self):
        return [key for key, _ in self.nav]

    def _at(self, y):
        """The entry whose box holds height `y`, or None (the gap between two)."""
        for key, (_x0, y0, _x1, y1) in self.boxes.items():
            if y0 <= y < y1:
                return key
        return None

    def draw(self):
        """The list's picture (the slab under the entry on show or under the pointer) and its words over it."""
        from PIL import Image, ImageDraw, ImageTk
        self._job = None
        if not self.winfo_exists():
            return
        px = self.ui.px
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        self.delete("all")
        left, right = px(Rail.EDGE) - px(6), width - px(Rail.EDGE) + px(6)
        picture = Image.new("RGB", (width, height), art._rgb(theme.STRIP))
        draw = ImageDraw.Draw(picture)
        row = px(self.ITEM_H) if self.nav else px(self.STEP_H)
        keys = self._entries() if self.nav else list(range(len(self.steps)))
        self.boxes = {}
        lit = self.current if self.nav else self.step
        for i, key in enumerate(keys):
            top = i * (row + px(self.ITEM_GAP))
            self.boxes[key] = (left, top, right, top + row)
            if key == lit or (self.nav and key == self.hover):
                # The slab: the cards' colour under the entry on show, the hovered rows' under the pointer, its
                # top-right corner cut as the cards' are.
                fill = theme.PANEL if key == lit else theme.PANEL_HI
                cut = px(self.CUT)
                draw.polygon([(left, top), (right - cut, top), (right - 1, top + cut), (right - 1, top + row - 1),
                              (left, top + row - 1)], fill=art._rgb(fill))
        self._numerals = []
        if self.nav:
            for (key, words) in self.nav:
                x0, y0, _x1, y1 = self.boxes[key]
                self.create_text(x0 + px(self.NAME_PAD), (y0 + y1) // 2, text=words, font=self.ui.fonts.nav, anchor="w",
                                 tags=("name", "n-" + key))
        else:
            for i, name in enumerate(self.steps):
                x0, y0, _x1, y1 = self.boxes[i]
                done, now = i < self.step, i == self.step
                colour = theme.OK if (done or now) else theme.STEP_TO_COME
                numeral = art.numeral(str(i + 1), colour, self.ui.scale, size=26, bg=None)
                nx, ny = x0 + px(self.NAME_PAD), (y0 + y1 - numeral.height) // 2
                picture.paste(numeral, (nx, ny), numeral if numeral.mode == "RGBA" else None)
                # The names in one column whatever each number's width.
                self.create_text(nx + px(self.NUMBER_W), (y0 + y1) // 2, text=name, anchor="w",
                                 font=self.ui.fonts.step,
                                 fill=theme.TEXT if now else (theme.MUTED if done else theme.FAINT))
        self._picture = picture
        self._image = ImageTk.PhotoImage(picture, master=self)
        # A dialog draws the window from the widgets (snapshot.py): the list as it looks now.
        self.odq_picture = picture
        self.tag_lower(self.create_image(0, 0, image=self._image, anchor="nw"))
        self._paint()

    def _paint(self):
        """Each name's colour and the keyboard's ring."""
        px = self.ui.px
        self.delete("ring")
        for key, _words in self.nav:
            on = key == self.current
            colour = theme.OK if on else ("#ffffff" if key == self.hover else theme.MUTED)
            self.itemconfigure("n-" + key, fill=colour)
        if self.ring in self.boxes:
            x0, y0, x1, y1 = self.boxes[self.ring]
            width = max(1, px(2))
            self.create_rectangle(x0 + width // 2, y0 + width // 2, x1 - (width + 1) // 2, y1 - (width + 1) // 2,
                                  outline=theme.CYAN, width=width, tags=("ring",))

    def _pointer(self, event):
        key = self._at(event.y)
        if key != self.hover:
            self._hover(key)

    def _hover(self, key):
        if key != self.hover:
            self.hover = key
            # The slab under the pointer is part of the picture.
            self.draw()

    def _press(self, key):
        if key is not None and self.on_nav:
            self.on_nav(key)

    def _focused(self, on):
        """The keyboard came: the ring on the page on show (or the first entry); it went: the ring goes."""
        entries = self._entries()
        if on and entries:
            if self.ring not in entries:
                self.ring = self.current if self.current in entries else entries[0]
        else:
            self.ring = None
        self._paint()

    def _move(self, by, key):
        """The ring along the entries; Tab past the last (Shift+Tab before the first) leaves the list as Tab does."""
        entries = self._entries()
        if not entries or self.ring not in entries:
            return None
        i = entries.index(self.ring) + by
        if 0 <= i < len(entries):
            self.ring = entries[i]
            self._paint()
            return "break"
        if key in ("<Up>", "<Down>"):
            return "break"
        return None

    def set_current(self, key):
        """The page on show: its name lit on its slab."""
        if key != self.current:
            self.current = key
            self.draw()

    def set_step(self, index):
        """The guide's step on show."""
        if index != self.step:
            self.step = index
        self.draw()


# How long a page that came out shorter than its view reaches waits before it is measured again (ms): the rows made
# anew have their sizes within a few, in the same turn of the event loop.
SETTLE = 60
# The steps the picture behind a page is drawn tall in (logical pixels): a page that grows within its step keeps it.
BACKDROP_ROOM = 480
# How far a press must move before it drags the page rather than taps (logical pixels).
PAN_START = 8
# How much taller than its page the column is held (logical pixels): a row or a card that comes is laid out in room the
# page's frame already has. Tk's packer lays a frame's rows out in the frame's old size when the frame has asked to grow
# and its own frame has not yet grown it, so the column at its page's height had the page's last cards squeezed or
# taken off the screen for a moment, and drawn again when they came back (the cards under the keyboard's lanes).
COLUMN_ROOM = 960


class ScrollArea(tk.Frame):
    """The page area, as the site's page: its field with the shards at the edges and the dots in the margins (drawn
    behind on the canvas, art.backdrop), the page's title and a line under it (set_heading), and the page's content in
    a column between margins (`inner`), all scrolling together with the mouse wheel."""

    # The margins either side of the column, the room above the title and under the content, and between the heading
    # and the content (logical pixels, on the spacing scale).
    MARGIN, TOP, BOTTOM, GAP = 32, 20, 20, 20
    # The content column's greatest width (logical pixels): a wider window leaves the room right of it, where the
    # page's shards stand, rather than stretching rows past what a person reads at a glance.
    COLUMN_MAX = 1080
    # The room the shards keep from the content column (logical pixels): they stand in the margin right of it
    # (art.shard_mask), clear of every card and of the heading's words.
    SHARD_CLEAR = 16

    def __init__(self, parent, ui, bg=theme.BG, offset=0, light=None, on_moved=None):
        super().__init__(parent, bg=bg)
        self.ui = ui
        # Where this area starts on the page (under the header, which draws the page's top) and how far the page's
        # lit top reaches; told when the page has moved from its top, or come back to it.
        self.offset, self.light, self.on_moved, self._moved = offset, light, on_moved, None
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Dark.Vertical.TScrollbar")
        # The column, with no colour of its own (an empty background: Tk paints nothing there, nor does the screen when
        # it grows): its page's frame covers it, and where the page grows the picture under it stays on the screen
        # until that frame and its picture reach there, never the field's flat colour for a moment.
        self.inner = tk.Frame(self.canvas, bg="")
        # A card or a frame of the page finds the page's picture through the column (Card, _paint_field).
        self.inner.odq_area = self
        # The page's own field between and round the cards: Tk's frames are opaque, so each frame of the field (the
        # column, its rows, the gaps between cards) shows its part of the page's picture on a canvas of its own laid
        # under what it holds, the page's one picture placed on it so that the frame's part is under the frame
        # (_paint_field). Frame -> that canvas.
        self._field = {}
        # The cards on the page whose cut corner shows the page's picture beyond it (Card._cut_over_field).
        self._cards = []
        px = ui.px
        self._window = self.canvas.create_window((px(self.MARGIN), px(self.TOP)), window=self.inner, anchor="nw")
        # The column's height as last given to it (_relayout): its page's height and COLUMN_ROOM under it. Its page
        # frame fills it; the room shows the page's own picture, past the page's end where the view never reaches.
        self._column_height = 0
        # Held at that height, the column no longer changes size as its page grows or shrinks: a change of size or
        # place of anything in it tells the area instead, once a turn (_column_watch).
        self._watch_line = self._column_watch()
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
        # A press on the page that may become a drag of it (a finger on a touch screen): where it began.
        self._pan = None
        self.canvas.configure(yscrollcommand=self._bar_set)
        # The canvas spans the whole width, its picture behind with it, so the page's backdrop goes on from the header's
        # to the window's edge; the scroll bar lies over its right edge when the page scrolls. The column keeps the bar's
        # room either way: the page then has one width whether it scrolls or not (without it, a page about as tall as
        # the area loops for ever: the bar narrows the page, the narrower page fits, the bar goes, and back).
        self.bar_room = self.bar.winfo_reqwidth()
        self.canvas.pack(fill="both", expand=True)
        # The content's height decides how far it scrolls, and how tall the picture behind it is. The column changes
        # size of its own when the window's width does or when _relayout gives it more room; what changes inside it
        # tells through _column_watch, a frame of the field through _frame_changed, and a new width brings a new
        # picture, which places every frame's part again (_draw_backdrop).
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
        # The column's watch goes from the window's bindings with the area, as the keyboard's line does.
        self.bind("<Destroy>", lambda e: e.widget is self and self._column_unwatch(), add="+")

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
        # The column moved on the page (a heading of another height): its frames show another part of the picture.
        self._paint_field()

    def _column(self, width):
        """The column's width in an area `width` wide: between the margins, less the scroll bar's room, and never wider
        than COLUMN_MAX."""
        return min(width - 2 * self.ui.px(self.MARGIN) - self.bar_room, self.ui.px(self.COLUMN_MAX))

    def shard_room(self):
        """Where the page's shards may stand (art.shard_mask): right of this x, in the page's own pixels, SHARD_CLEAR past
        the content column, down the whole page and in its head alike. Nothing of a card or of the heading's words is
        ever there, whatever the page holds, so the room follows the window's width alone (the picture is drawn again
        for a new width anyway, never for another page)."""
        px = self.ui.px
        return px(self.MARGIN) + max(1, self._column(max(1, self.canvas.winfo_width()))) + px(self.SHARD_CLEAR)

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
        # The column held its page's height and COLUMN_ROOM tall, set again only when less than half the room is left
        # under the page, or twice the room (a page that got much shorter): a row or a card that comes is laid out in
        # the room, the cards under it moved down whole.
        asked, room = self.inner.winfo_reqheight(), self.ui.px(COLUMN_ROOM)
        if not asked + room // 2 <= self._column_height <= asked + 2 * room:
            self._column_height = asked + room
            c.itemconfigure(self._window, height=self._column_height)
        drawn = self._backdrop_size
        if drawn is None or drawn[0] != width or drawn[1] < content:
            # Another width, or a page taller than the picture behind it: drawn once the size settles (a drag fires many
            # resize events). A page as wide that got shorter, or taller within the picture's room, keeps it: a row
            # that comes or goes never waits for the picture (BACKDROP_ROOM).
            if self._backdrop_job is not None:
                self.after_cancel(self._backdrop_job)
            self._backdrop_job = self.after(60, self._draw_backdrop)

    # The events by which something in the column tells it changed size or place, or went.
    COLUMN_EVENTS = ("<Configure>", "<Unmap>", "<Destroy>")

    def _column_watch(self):
        """A line in the window's bindings: a change of size or place, or a widget gone, inside this area's column
        has the area lay its page out again (_relayout) once the turn's work is done, once for all of that turn's
        changes. In Tcl alone until then: a page laid out moves a hundred widgets, and a call into Python for each
        would slow the very change. Returns what _column_unwatch takes it away with."""
        top = self.winfo_toplevel()
        command = self.register(self._column_changed)
        # Set while a look is asked for and until it has been taken: the turn's other changes, and the ones the look
        # itself lays out, ask nothing more.
        flag = "::odq_column_" + command
        # The look runs caught: one that comes after the area went finds its command gone, and Tk would show an error.
        line = ("if {[string first {%s.} %%W] == 0 && ![info exists %s]} {set %s 1; after idle {catch %s; "
                "unset -nocomplain %s}}" % (self.inner, flag, flag, command, flag))
        for sequence in self.COLUMN_EVENTS:
            self.tk.call("bind", top._w, sequence, "+" + line)
        return top, command, line

    def _column_unwatch(self):
        """This area goes: its line leaves the window's bindings, and its command goes with it (as _focus_gone)."""
        top, command, line = self._watch_line
        try:
            for sequence in self.COLUMN_EVENTS:
                script = self.tk.call("bind", top._w, sequence)
                # The binding's lines joined by newlines: this area's out, the others as they were.
                kept = "\n".join(part for part in str(script).split("\n") if part.strip() != line)
                self.tk.call("bind", top._w, sequence, kept)
            self.deletecommand(command)
        except tk.TclError:
            # The window went first, its bindings and commands with it.
            pass

    def _column_changed(self):
        """Something in the column changed size or place, or went. Once Tk has laid out the rest (its waiting work done
        now, so that the page's height is the one it settles on: a card that went is taken off the page a step after
        it tells of it), a page frame new in the column shows the page's picture (a page shown, the guide's next step:
        its frame made after its heading), and the page's height and the column's room follow (_relayout)."""
        if not self.canvas.winfo_exists():
            return
        self.update_idletasks()
        for page in self.inner.winfo_children():
            if page not in self._field:
                # No picture yet: laid out since it was last looked at (a card on it may have had it watched already,
                # its last change of size gone by unseen).
                self._paint_field(page)
        self._relayout()

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
        # Drawn taller than the page by up to BACKDROP_ROOM, to the next whole step: rows that come take that room
        # without a picture drawn again (the field below the page's top is the same all the way down).
        step = self.ui.px(BACKDROP_ROOM)
        height = (height + step - 1) // step * step
        self._backdrop_size = (width, height)
        # The shards in the margin right of the content column (shard_room), which follows the width alone.
        picture = art.backdrop(width, height, self.ui.scale, offset=self.offset, top=self.light, room=self.shard_room())
        # The picture shown until now, kept until every canvas of the field shows the new one: Tk empties an image the
        # moment Python forgets it, and a canvas still showing it would be drawn empty.
        before = getattr(self, "_backdrop_image", None)
        self._backdrop_image = ImageTk.PhotoImage(picture, master=c)
        # A dialog draws the window from the widgets (snapshot.py): the page's picture, its title put on it then.
        self._backdrop_picture = picture
        if self._backdrop_item is None:
            self._backdrop_item = c.create_image(0, 0, image=self._backdrop_image, anchor="nw")
        else:
            c.itemconfigure(self._backdrop_item, image=self._backdrop_image)
        c.tag_lower(self._backdrop_item)
        # The field's frames and the cards' cut corners show their part of the new picture.
        self._paint_field()
        # Shown nowhere now.
        del before

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

    # ------------------------------------------------------------------------------------- the page's own field

    def page_box(self, widget):
        """Where `widget` stands on the page, in the page's picture's own pixels (left, top), or None when it is no
        part of this page's column. Counted from the widgets' places in their parents, so it holds wherever the page is
        scrolled to, and inside a <Configure> of any of them (Tk has moved them by then)."""
        x = y = 0
        found = widget
        while found is not None and found is not self.inner:
            x, y = x + found.winfo_x(), y + found.winfo_y()
            found = found.master
        if found is None:
            return None
        left, top = (int(round(float(v))) for v in self.canvas.coords(self._window))
        return left + x, top + y

    def picture_at(self, widget, x, y, width, height):
        """The page's picture under the box (x, y, width, height) of `widget` (in its own pixels), as an RGB picture of
        that size; None until the picture is drawn, or for a widget of no page. Past the picture's foot (a page grown
        before its picture is drawn again for it), the field's own colour."""
        from PIL import Image
        behind = getattr(self, "_backdrop_picture", None)
        place = self.page_box(widget)
        if behind is None or place is None or width < 1 or height < 1:
            return None
        left, top = place[0] + x, place[1] + y
        picture = Image.new("RGB", (width, height), art._rgb(self.cget("bg")))
        # The part inside the picture, cut out and put in its place (a crop past an edge would come out black).
        box = (max(0, left), max(0, top), min(behind.width, left + width), min(behind.height, top + height))
        if box[0] < box[2] and box[1] < box[3]:
            picture.paste(behind.crop(box), (box[0] - left, box[1] - top))
        return picture

    def _field_frames(self, under):
        """The frames of the page's field from `under` down (the column, or a frame of the field): it and each frame
        under it in the field's colour that is no card and no part of one, each with whether it may show the picture (a
        card's own holder, pages.Sections, may not: its card covers it, and it is told apart by what it holds; nor the
        column, which has no colour of its own and is covered by its page's frame whole)."""
        found, stack = [(under, under is not self.inner and not getattr(under, "odq_holder", False))], [under]
        field = str(self.cget("bg")).lower()
        while stack:
            widget = stack.pop()
            for child in widget.winfo_children():
                if isinstance(child, Card) or getattr(child, "odq_field", False) or child.winfo_class() != "Frame":
                    continue
                if str(child.cget("bg")).lower() != field:
                    # A frame of another colour (a band of its own): no part of the field, nor what it holds.
                    continue
                stack.append(child)
                found.append((child, not getattr(child, "odq_holder", False)))
        return found

    def _covered(self, frame, width, height):
        """Whether one thing `frame` holds covers all of it (the column under its page's frame, a column under its one
        card): nothing of the frame's own shows, so it needs no picture."""
        for child in frame.winfo_children():
            if getattr(child, "odq_field", False) or not child.winfo_ismapped():
                continue
            if (child.winfo_x() <= 0 and child.winfo_y() <= 0 and child.winfo_x() + child.winfo_width() >= width
                    and child.winfo_y() + child.winfo_height() >= height):
                return True
        return False

    def watch(self, frame):
        """`frame` of the field tells when it moves or changes size (_frame_changed), as Tk lays the page out (the
        column's own changes come through _relayout's binding). Once for each frame."""
        if frame is self.inner or getattr(frame, "odq_watched", False):
            return
        frame.odq_watched = True
        frame.bind("<Configure>", lambda e: e.widget is frame and self._frame_changed(frame), add="+")

    def _frame_changed(self, frame):
        """A frame of the field moved or changed size. Only a move moves what it holds on the page: its picture and
        the cards' corners in it are placed again then (_paint_field). One that grew or shrank where it stands keeps
        everything in it where it was on the page, and its canvas, as tall as the page's picture, shows its new foot
        as it is: nothing to do, so that a row that comes costs the page no work at each frame it grows (a card's own
        holder alike; a card that moves in it tells of its own move). A frame with no picture yet is looked at again
        (laid out at last, or no longer covered by the one thing it holds)."""
        if not frame.winfo_exists():
            return
        place = self.page_box(frame)
        pictured = frame in self._field or getattr(frame, "odq_holder", False)
        if pictured and place is not None and place == getattr(frame, "odq_place", None):
            return
        self._paint_field(frame)

    def _paint_field(self, under=None):
        """Each frame of the page's field shows its part of the page's picture where it now stands, and each card's
        cut corner the picture beyond it: everything on the page when the picture is drawn again or the column moves,
        what is under a frame of the field when it moves or changes size (its own <Configure>, which Tk sends while it
        lays the page out, so the new part shows with the frame's new place, never a moment later).

        A frame's canvas shows the page's own picture, the one Tk image this area draws behind the page, placed so that
        the frame's part of it lies under the frame, and the canvas is as wide as the frame and as tall as that
        picture: a frame that grows down shows more of what its canvas already holds, and one that moves only moves the
        picture on its canvas. Nothing is cut or made for it. (A picture cut for each frame had to be cut again, and
        made into a new Tk image the screen copies whole, each time its frame moved or grew past it: 16 ms when the
        connection test's card came, the page half drawn on the screen all that while; and a canvas as tall as its
        frame was drawn again whole at each change of the page's height.)"""
        image = getattr(self, "_backdrop_image", None)
        if image is None or not self.inner.winfo_exists():
            return
        under = under if under is not None and under.winfo_exists() else self.inner
        drawn = self._backdrop_size
        if drawn is not None and drawn[0] != max(1, self.canvas.winfo_width()):
            # The window is being made wider or narrower: the page's picture is drawn again for the new width once the
            # sizes stop changing (_relayout), and that places every picture again; placing the old picture for each
            # step of a drag would only slow the drag.
            return
        for frame, shows in self._field_frames(under):
            self.watch(frame)
            if not shows:
                # A card's holder (or the column): where it stands, for its next <Configure> to tell a move.
                frame.odq_place = self.page_box(frame)
                continue
            width, height = frame.winfo_width(), frame.winfo_height()
            holder = self._field.get(frame)
            if holder is not None and not holder.winfo_exists():
                # Its canvas went with what it held (a frame emptied and filled again): a new one is made.
                holder = None
            if width <= 1 or height <= 1 or (holder is None and self._covered(frame, width, height)):
                # Not laid out yet, or nothing of it shows: no picture (one made before stays, under what covers it).
                continue
            place = self.page_box(frame)
            if holder is None:
                # Laid under everything the frame holds, from its top-left corner: a canvas, which draws again only
                # the part a moved card uncovers. Nothing of the page's own (no words, no keyboard); a press on it
                # moves the page as the field does (_pannable).
                holder = tk.Canvas(frame, bd=0, highlightthickness=0, bg=self.cget("bg"), takefocus=0)
                holder.odq_field = True
                # Under its siblings: Misc's lower, as a canvas's own lower() moves its items, not the canvas.
                tk.Misc.lower(holder)
                holder.odq_item = holder.create_image(0, 0, anchor="nw")
                # The picture it shows, where, and its own size, as last set (each set again only when it changed).
                holder.odq_shown = holder.odq_place = holder.odq_size = None
                # A dialog draws the window from the widgets (snapshot.py): the frame's part of the page's picture,
                # cut when a dialog asks for it.
                holder.odq_picture = lambda frame=frame: self.picture_at(frame, 0, 0, frame.winfo_width(),
                                                                         frame.winfo_height())
                self._field[frame] = holder
            if holder.odq_size != drawn[1]:
                # As tall as the page's picture, whatever the frame's height: the frame shows the part of it under it,
                # and a frame that grows (a row that comes) shows more of it without the canvas changing size, which
                # would have Tk draw all of it again. As wide as the frame, which changes only with the window's width
                # (the page's picture is then drawn again anyway).
                holder.place(x=0, y=0, relwidth=1.0, height=drawn[1], bordermode="outside")
                holder.odq_size = drawn[1]
            if holder.odq_shown is not image:
                # The page's picture drawn again (another width, a page grown past it): the new one.
                holder.itemconfigure(holder.odq_item, image=image)
                holder.odq_shown = image
            if holder.odq_place != place:
                # The picture's own corner as far up and left of the frame as the frame is from the page's corner.
                holder.coords(holder.odq_item, -place[0], -place[1])
                holder.odq_place = place
            # Where it stands, for its next <Configure> to tell a move from a change of size (_frame_changed).
            frame.odq_place = place
        # The frames gone with a page that went, and their pictures with them.
        self._field = {f: v for f, v in self._field.items() if f.winfo_exists()}
        self._cards = [card for card in self._cards if card.winfo_exists()]
        # Then each card under `under` (all of them for the column) cuts its corner again where it now stands.
        inside = str(under) + "."
        for card in self._cards:
            if under is self.inner or str(card).startswith(inside):
                card._cut_over_field()

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
                                      ("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units")),   # X11 wheel down
                                      # A finger (or the mouse) dragged on the page itself moves it, as on a phone.
                                      ("<ButtonPress-1>", self._pan_start), ("<B1-Motion>", self._pan_move),
                                      ("<ButtonRelease-1>", self._pan_end)):
                self._wheel_commands[sequence] = self.bind_all(sequence, handler)

    def _pannable(self, widget):
        """Whether a press on `widget` may move the page: the page's own field, a card, a frame or words that do
        nothing when pressed; never a control (a field, a button, a switch, a slider, a drop-down, a link, a key's box)."""
        if not str(widget).startswith(str(self)):
            return False
        if widget is self.canvas or isinstance(widget, tk.Frame) or getattr(widget, "odq_field", False):
            return True
        if isinstance(widget, tk.Label):
            # Words a press does something on show the pointing hand (links), or take the keyboard.
            try:
                return str(widget.cget("cursor")) != "hand2" and str(widget.cget("takefocus")) in ("", "0")
            except tk.TclError:
                return False
        return False

    def _pan_start(self, event):
        """A press that may become a drag of the page: where it began, and where the page was."""
        self._pan = None
        if self._pannable(event.widget):
            self._pan = {"y": event.y_root, "top": self.canvas.canvasy(0), "moved": False}

    def _pan_move(self, event):
        """The page follows the finger once it has moved further than a tap's wobble."""
        pan = getattr(self, "_pan", None)
        if not pan:
            return
        dy = event.y_root - pan["y"]
        if not pan["moved"] and abs(dy) < self.ui.px(PAN_START):
            return
        pan["moved"] = True
        region = [float(v) for v in str(self.canvas.cget("scrollregion")).split()] if self.canvas.cget("scrollregion") else []
        seen = self.canvas.winfo_height()
        if len(region) != 4 or region[3] <= seen:
            return
        target = max(0.0, min(pan["top"] - dy, region[3] - seen))
        self.canvas.yview_moveto(target / region[3])

    def _pan_end(self, event):
        self._pan = None

    def page_key(self, event):
        """Page Up and Page Down (and Home and End away from a field) move the page by the keyboard: a page whose words
        no control reaches is read to its foot without a mouse."""
        if not self.winfo_viewable():
            return None
        focus = self.focus_get()
        if event.keysym in ("Home", "End") and isinstance(focus, (tk.Entry, ttk.Combobox)):
            # A field's own Home and End.
            return None
        if event.keysym == "Prior":
            self.canvas.yview_scroll(-1, "pages")
        elif event.keysym == "Next":
            self.canvas.yview_scroll(1, "pages")
        elif event.keysym == "Home":
            self.canvas.yview_moveto(0)
        elif event.keysym == "End":
            self.canvas.yview_moveto(1)
        return None

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

    def new_page(self):
        """A frame for a page, made in the column off the screen (not yet laid out in it): the page is made in it while
        the one on show stays whole on the screen, then put in its place (show_page). In the area's own colour, the
        field's."""
        return tk.Frame(self.inner, bg=self.cget("bg"))

    def show_page(self, page):
        """`page` (new_page, made) takes the place of the page on show. The old one leaves the screen whole first, in
        one step, and only then are its widgets taken away: tkinter takes a frame's widgets away one by one, and the
        old page's own frame showed in the field's flat colour where each had been, a slab under the old title for as
        long as the new page then took to make (0.8 s at 150 % on Windows for HELP). The column has no colour of its
        own, so the old page's last look stays on the screen until the new page is drawn over it."""
        old = [child for child in self.inner.winfo_children() if child is not page]
        for child in old:
            # Off the screen whole: one window unmapped, its own and its widgets' look gone with it at once.
            manager = child.winfo_manager()
            if manager:
                getattr(child, manager + "_forget")()
        for child in old:
            # Taken away unseen, its frame no longer on the screen.
            child.destroy()
        # A page starts at its top.
        self.to_top()
        page.pack(fill="both", expand=True)

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

    def update(event=None, width=None):
        # The box's width as laid out, or as a caller knows it will be (a row about to be shown, RowList.show).
        width = width or master.winfo_width()
        if width <= 1 or not widget.winfo_exists():
            return
        # Each widget beside it with its own pack or grid padding: the packer keeps that room for it too.
        taken = sum(b.winfo_reqwidth() + own_padding(b) for b in beside if b.winfo_exists())
        # The label's own edge and padding come on top of its wrapped text: a line that fills the wrap width exactly
        # would otherwise be a few pixels wider than the room, and Tk would cut it.
        room = max(ui.px(120), width - inner_padding(master) - own_padding(widget) - inner_padding(widget) - taken
                   - ui.px(margin))
        if str(widget.cget("wraplength")) != str(room):
            # Only a new width is set: the same one would have Tk lay the label out and draw it again for nothing.
            widget.configure(wraplength=room)
        # A label that may say other words (a choice's own hint) keeps the room of the longest at this width.
        keep_room(widget, room)

    # Start narrow: a label that first asks for its whole line would widen its box, and the box's width would
    # then come from the label instead of the page. Narrow first, the box takes the page's width, then the
    # label grows into it.
    widget.configure(wraplength=ui.px(START_WRAP))
    master.bind("<Configure>", update, add="+")
    widget.after_idle(update)
    # Wrapped for a width the box will have before it is laid out (RowList.show): no moment of narrow text.
    widget.odq_wrap = lambda width: update(width=width)


def keep_room(label, wrap):
    """A label that may say any of several words (label.odq_texts: each choice's own hint) as tall as the longest of
    them wraps to at `wrap` pixels, its words at its top: whichever it says, it takes the same room, and nothing round
    it moves when another is said. A choice that brings a row and says its own hint anew (the Screen page's Mode and
    the window's size) is then laid out once: when the hint had another number of lines, Tk laid the row that came out
    with the hint's old height, then the whole card, the cards beside it and the cards under them again a moment later
    for its new one, and the screen showed the first of the two (three frames between where two are allowed)."""
    texts = getattr(label, "odq_texts", None)
    if not texts or not label.winfo_exists():
        return
    root = label._root()
    probe = getattr(root, "odq_room_probe", None)
    if probe is None or not probe.winfo_exists():
        # Never shown: Tk works out the size of its words all the same, wrapped as the label's would be.
        probe = root.odq_room_probe = tk.Label(root, bd=0, padx=0, pady=0, highlightthickness=0)
    font = label.cget("font")
    # A line's height in the label's face: its words take a whole number of them.
    line = max(1, int(label.tk.call("font", "metrics", font, "-linespace")))
    lines = 1
    for text in texts:
        probe.configure(text=text, font=font, wraplength=wrap)
        lines = max(lines, -(-probe.winfo_reqheight() // line))
    if str(label.cget("height")) != str(lines):
        # Set only when it changes: the same height would have Tk lay the label out again for nothing.
        label.configure(height=lines)


def focus_ring(widget, ui, bg):
    """Reached with Tab: a cyan ring while the widget has the keyboard, the background's colour otherwise."""
    widget.configure(takefocus=1, highlightthickness=max(1, ui.px(2)), highlightbackground=bg,
                     highlightcolor=theme.CYAN)


def link(parent, ui, text, command, fg=None, bg=None, font=None, chevron=True):
    """Words that do something: a click, or Enter or Space once Tab has reached them (a cyan ring shows it). In the
    words' own colour (lime is the screen's main button's alone), with a chevron after them by default; on the parent's
    colour unless told. The chevron is a picture beside the words (chevron_picture), so that the words can change
    (configure(text=...)) and keep it."""
    bg = bg or parent.cget("bg")
    fg, font = fg or theme.TEXT, font or ui.fonts.body_bold
    words = tk.Label(parent, text=text, font=font, fg=fg, bg=bg, cursor="hand2")
    if chevron:
        # After the words, in their colour, as tall as their line: the label is as wide and as tall as when the chevron
        # was a character of the words.
        picture = chevron_picture(words, font, fg, bg)
        image = ImageTk.PhotoImage(picture, master=parent)
        words.configure(image=image, compound="right")
        # Kept on the label: Tk drops a picture the moment Python forgets it. Not named odq_picture: the label is words,
        # not a picture that stands for the whole widget (snapshot.py, the UI checks' lamps).
        words.odq_chevron = (image, picture)
    focus_ring(words, ui, bg)
    for sequence in ("<Button-1>", "<Return>", "<space>"):
        words.bind(sequence, lambda e: command())
    return words


def chevron_picture(label, font, colour, bg):
    """The chevron after a link's words (art.link_chevron), sized from their font as Tk sets it on this screen: its em
    in pixels, its line's ascent and height, its capitals' height; the room before it the two spaces that stood there,
    less the room Tk keeps between the words and a picture beside them (the label's padx)."""
    size = float(font.actual("size"))
    # A size in points (positive) or in pixels (negative), as Tk takes it.
    em = size * label.winfo_fpixels("1p") if size > 0 else -size
    pad = label.winfo_fpixels(str(label.cget("padx")))
    gap = max(0.0, font.measure("  ") - pad)
    return art.link_chevron(em, font.metrics("ascent"), font.metrics("linespace"), em * theme.TEXT_CAP, gap, colour, bg)


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
    """A state's small light (art.lamp), as a label; `hollow` draws it as a ring."""
    from PIL import ImageTk
    picture = art.lamp(colour, ui.scale, bg=bg, hollow=hollow, lead=False)
    image = ImageTk.PhotoImage(picture, master=parent)
    light = tk.Label(parent, image=image, bg=bg, bd=0)
    # Kept on the label: Tk drops a picture the moment Python forgets it. A dialog draws the window from it.
    light.odq_image, light.odq_picture = image, picture
    return light


class Button(tk.Canvas):
    """A button cut at two corners like PLAY. kind: 'primary' (filled with the site's lime, the page's main action),
    'secondary' (quiet metal that lights up under the pointer), 'danger' (metal tinted red, filled red under the
    pointer: removing or starting over, beside the page's own main action), 'remove' (filled red: the screen's main
    action when it removes for good, as the installer's Uninstall, the way a dialog's Delete all is drawn).

    The face is a picture (art.button_face); the words stay Tk text, so they are drawn as crisply as every other label.
    """

    # Each kind's look in art.BUTTON_LOOKS.
    LOOKS = {"primary": "home", "secondary": "neutral", "danger": "danger_quiet", "remove": "danger"}
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
        # Each state's face, without and with the keyboard's ring (a disabled button never has the keyboard), made the
        # first time the button shows it (_face): a page makes a dozen buttons each time it is shown, most of them seen
        # only as they are, and drawing every face of each made the click on the page's name wait for them all (seven
        # pictures a button, a third of HELP's making at 150 %).
        self.face_size, self.faces, self.images = (width, height), {}, {}
        self.face = self.create_image(0, 0, anchor="nw")
        # On the face's middle by the ink of its capitals (or its Hangul), not by Tk's line box (words_top).
        self.parts = [self.create_text(px(18), words_top(fonts.body_bold, text, self, height / 2.0), text=text,
                                       font=fonts.body_bold, anchor="nw")]
        self._paint(self.state if self.enabled else "disabled")

    def _face(self, key):
        """The face of `key` (its state, and whether the keyboard's ring shows) as a Tk image, made when first asked."""
        if key not in self.images:
            state, ring = key
            self.faces[key] = art.button_face(self.face_size, 0, self.look, state, ring, self.ui.scale, bg=self.bg)
            self.images[key] = ImageTk.PhotoImage(self.faces[key], master=self)
        return self.images[key]

    def _paint(self, state):
        self.state = state
        key = (state, self.focused and state != "disabled")
        self.itemconfigure(self.face, image=self._face(key))
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

    def __init__(self, parent, ui, words, command, bg=theme.STRIP, width=None):
        px = ui.px
        # As wide as it is told (the column's room, its keyboard ring inside it), else its own width.
        ring = max(1, px(2))
        slab = (width - 2 * ring) if width else px(self.WIDTH)
        # Every look drawn once: the mouse and the state only swap them.
        self.pictures = {look: art.play_button(slab, px(self.HEIGHT), state=look) for look in self.LOOKS}
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
        self.ui, self.value, self.command, self.bg = ui, bool(value), command, bg
        self.face_size = (ui.px(40), ui.px(22))
        # Each value's picture made the first time the switch shows it (_picture), then kept: a click only swaps them,
        # and a page that makes its switches each time it is shown draws only the one each shows.
        self.pictures, self.images = {}, {}
        self.configure(image=self._picture(self.value))
        # A dialog draws the window behind it from the widgets (snapshot.py): this is the switch's part.
        self.odq_picture = self.pictures[self.value]
        self.bind("<Button-1>", lambda e: self.set(not self.value, notify=True))
        # Tab reaches it; Enter or Space switches it.
        focus_ring(self, ui, bg)
        # The pill shows this far in: the keyboard's ring, then the room round the pill (setting_row lines controls up
        # by it).
        self.odq_inset = int(self.cget("highlightthickness")) + art.TOGGLE_HALO
        self.bind("<Return>", lambda e: self.set(not self.value, notify=True))
        self.bind("<space>", lambda e: self.set(not self.value, notify=True))

    def _picture(self, on):
        """The switch's picture for `on` as a Tk image, made when first asked (art keeps the pictures it drew)."""
        if on not in self.images:
            self.pictures[on] = art.toggle(on, *self.face_size, bg=self.bg)
            self.images[on] = ImageTk.PhotoImage(self.pictures[on], master=self)
        return self.images[on]

    def set(self, value, notify=False):
        self.value = bool(value)
        self.configure(image=self._picture(self.value))
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
        # Each tab's face in a state made the first time the tab shows it (_face), then kept: the pointer and a click
        # only swap them, and a page that makes its rows of tabs each time it is shown draws only the one each tab
        # shows (art keeps the faces it drew).
        self.faces, self.images = {}, {}
        self.items, self.words, self.hover = [], [], None
        for i, ((x0, w), (_key, text)) in enumerate(zip(self.boxes, self.options)):
            # Its face comes with the row's first look (set, below).
            self.items.append(self.canvas.create_image(x0, 0, anchor="nw"))
            # On the tab's middle by the ink of its capitals (or its Hangul), as a button's words are (words_top).
            self.words.append(self.canvas.create_text(x0 + w // 2, words_top(ui.fonts.tab, text, self, px(self.HEIGHT) / 2.0),
                                                      text=text, font=ui.fonts.tab, anchor="n"))
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
        # A dialog draws the window behind it from the widgets (snapshot.py): the row as it looks then, put together
        # only when one asks (_picture).
        self.canvas.odq_picture = self._picture
        self.set(value)

    def _hover(self, i):
        self.hover = i
        self._paint()

    def _state(self, i):
        """The look tab `i` has now: on when chosen, hover under the pointer, else normal."""
        return "on" if self.keys[i] == self.value else ("hover" if i == self.hover else "normal")

    def _face(self, i, state):
        """Tab `i`'s face in `state` as a Tk image, made when first asked."""
        if (i, state) not in self.images:
            self.faces[(i, state)] = art.tab_face(self.boxes[i][1], self.ui.px(self.HEIGHT), state, self.ui.scale,
                                                  bg=self.bg)
            self.images[(i, state)] = ImageTk.PhotoImage(self.faces[(i, state)], master=self)
        return self.images[(i, state)]

    def _paint(self):
        """Each tab's face and words: the chosen one lime with dark words, the one under the pointer lighter."""
        for i in range(len(self.keys)):
            state = self._state(i)
            self.canvas.itemconfigure(self.items[i], image=self._face(i, state))
            self.canvas.itemconfigure(self.words[i], fill=theme.OK_INK if state == "on" else
                                      (theme.TEXT if state == "hover" else theme.MUTED))

    def _picture(self):
        """The row as it looks now, for a dialog (snapshot.py): each tab's face where it is, the rule under them."""
        from PIL import Image
        px = self.ui.px
        picture = Image.new("RGB", (int(self.canvas.cget("width")), int(self.canvas.cget("height"))),
                            art._rgb(self.bg))
        for i in range(len(self.keys)):
            # The faces on show, each drawn when the tab first showed it.
            self._face(i, self._state(i))
            picture.paste(self.faces[(i, self._state(i))], (self.boxes[i][0], 0))
        picture.paste(art._rgb(theme.OK), (0, px(self.HEIGHT), picture.width, picture.height))
        return picture

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


# The characters a slider's number takes at least: an equaliser's band's "-12 dB".
SLIDER_NUMBER = 6
# A slider that takes its row's room (fill): its track at least this long, and at most this (logical pixels). Long
# enough to set a value finely by the mouse, never a line across a wide card.
SLIDER_LEAST, SLIDER_MOST = 200, 360


class Slider(tk.Frame):
    """A slider with its number beside it, from `least` to `most` (0 to 100 for a volume); command(value) runs when the
    drag ends and at each step of the keyboard. Its track is let into the card and runs from the slider's own left edge,
    so it starts on the same line as the controls above and under it; the knob stands on the track, inside its ends. A
    range that goes below zero (an equaliser's band) is lit from its zero, marked on the track. `say(value)` is the
    number's words ("+3 dB"); `step` what an arrow key moves it by."""

    def __init__(self, parent, ui, value, command, bg=None, width=320, least=0, most=100, step=5, say=str, fill=False,
                 shortest=None):
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.command, self.value, self.bg = ui, command, int(value), bg
        self.least, self.most, self.step, self.say = least, most, step, say
        # `fill`: as long as the room its place gives it (setting_row grids it across its control column), between
        # SLIDER_LEAST (or `shortest`, for a range of few steps: an equaliser's band) and SLIDER_MOST; it starts at the
        # least, so that it never asks a card for more than it has.
        self.fill, self.shortest = fill, ui.px(shortest or SLIDER_LEAST)
        self.odq_fill = fill
        self.w, self.h = (self.shortest if fill else ui.px(width)), ui.px(26)
        self.colour = theme.OK
        self.knob_size = ui.px(18)
        # The knob's picture, drawn once (art keeps it for every slider), for the canvas and for a dialog's picture.
        self.knob_picture = art.knob(self.knob_size, ring=self.colour, scale=ui.scale)
        self.knob_img = ImageTk.PhotoImage(self.knob_picture, master=parent)
        self.canvas = tk.Canvas(self, width=self.w, height=self.h, bg=bg, highlightthickness=0, cursor="hand2")
        self.canvas.pack(side="left")
        # As wide as the longest words any slider says ("-12 dB"), so that the slider never moves as its number changes and
        # the numbers of a page's sliders end on one line.
        widest = max(len(say(least)), len(say(most)), len(say(0)), SLIDER_NUMBER)
        self.number = tk.Label(self, text="", font=ui.fonts.body_bold, fg=theme.TEXT, bg=bg, width=widest, anchor="e")
        self.number.pack(side="left", padx=(ui.px(10), 0))
        self.canvas.bind("<Button-1>", self._drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: self.command(self.value))
        # Tab reaches it; the arrow keys move it by a step (Home and End to either end), each step saved as a drag's end.
        focus_ring(self.canvas, ui, bg)
        # A canvas's ring covers its edge: the drawing starts inside it, and the track's left end that far in.
        self.inset = int(self.canvas.cget("highlightthickness"))
        self.odq_inset = self.inset
        for key, to in (("<Left>", lambda v: v - self.step), ("<Right>", lambda v: v + self.step),
                        ("<Down>", lambda v: v - self.step), ("<Up>", lambda v: v + self.step),
                        ("<Home>", lambda v: self.least), ("<End>", lambda v: self.most)):
            # "break": the key is the slider's, never the page's too (Home and End move the page elsewhere).
            self.canvas.bind(key, lambda e, to=to: self._key(to) or "break")
        # A dialog draws the window behind it from the widgets (snapshot.py): the canvas as it looks then, the track
        # and the knob where they are, put together only when one asks (_picture).
        self.canvas.odq_picture = self._picture
        self._draw()
        if fill:
            # Its own width as its place lays it out: the track takes what the number and its gap leave.
            self.bind("<Configure>", self._fit, add="+")

    def _fit(self, event):
        """The track as long as the slider's width leaves it (a fill slider), between SLIDER_LEAST and SLIDER_MOST; drawn
        again only when that changed (the window made wider or narrower)."""
        px = self.ui.px
        room = event.width - self.number.winfo_reqwidth() - px(10) - 2 * self.inset
        track = max(self.shortest, min(px(SLIDER_MOST), room))
        if track != self.w:
            self.w = track
            self.canvas.configure(width=self.w)
            self._draw()

    def _fraction(self, value):
        """Where a value lies along the range, from 0 to 1."""
        return (value - self.least) / float(max(1, self.most - self.least))

    def set(self, value):
        """Show another value (one the player's in-game menu wrote back), saying nothing."""
        value = int(min(self.most, max(self.least, int(value))))
        if value != self.value:
            self.value = value
            self._draw()

    def _key(self, to):
        """A move from the keyboard: the new value, drawn and saved."""
        value = int(min(self.most, max(self.least, to(self.value))))
        if value != self.value:
            self.value = value
            self._draw()
            self.command(self.value)

    def _x(self, value):
        """Where a value's knob sits: its centre a knob's half inside either end of the track, so the knob never
        stands past the track's ends."""
        half = self.knob_size / 2.0
        return getattr(self, "inset", 0) + half + (self.w - 2 * half) * self._fraction(value)

    def _drag(self, event):
        half = self.knob_size / 2.0
        frac = (event.x - getattr(self, "inset", 0) - half) / float(max(1, self.w - 2 * half))
        frac = min(1.0, max(0.0, frac))
        self.value = int(round(self.least + frac * (self.most - self.least)))
        self._draw()

    def _draw(self):
        c, mid = self.canvas, getattr(self, "inset", 0) + self.h // 2
        c.delete("all")
        thick = max(4, self.ui.px(6))
        inset = getattr(self, "inset", 0)
        # The track as a picture let into the card, lit up to the knob's middle from the slider's left edge, or from
        # the range's zero when it goes below it.
        fraction = (self._x(self.value) - inset) / float(self.w)
        origin = (self._x(0) - inset) / float(self.w) if self.least < 0 < self.most else 0.0
        picture = art.slider_track(self.w, thick, fraction, self.colour, self.ui.scale, bg=self.bg, origin=origin)
        self._track_img = ImageTk.PhotoImage(picture, master=c)
        # The track as it is now, for a dialog's picture.
        self.track_picture = picture
        c.create_image(inset, mid, image=self._track_img, anchor="w")
        c.create_image(self._x(self.value), mid, image=self.knob_img)
        self.number.configure(text=self.say(self.value))

    def _picture(self):
        """The canvas as it looks now, for a dialog (snapshot.py): the track and the knob where they are."""
        from PIL import Image
        inset, thick = getattr(self, "inset", 0), max(4, self.ui.px(6))
        mid = inset + self.h // 2
        whole = Image.new("RGB", (self.w + 2 * inset, self.h + 2 * inset), art._rgb(self.bg))
        whole.paste(self.track_picture, (inset, mid - thick // 2))
        knob = self.knob_picture
        whole.paste(knob, (int(self._x(self.value) - self.knob_size / 2.0), mid - self.knob_size // 2), knob)
        return whole


class Select(ttk.Combobox):
    """A drop-down of (value, text) pairs; command(value) runs on a choice. Closed, a field with its chosen words and a
    chevron (ttk's box in the launcher's faces); opened, the launcher's own list (DropList) instead of Tk's: a raised
    surface under the box, its rows in the box's own place for the words, the chosen one marked, the one under the
    pointer or the keyboard lit. Each choice's words start with the same spaces in the closed box (list_pad), and the
    list draws its words where the box's start. The choices are told apart by their place, never by their words."""

    def __init__(self, parent, ui, options, value, command, width=24, most=None):
        self.options, self.ui = list(options), ui
        pad, _ = list_pad(ui)
        super().__init__(parent, values=[pad + t for _, t in self.options], state="readonly", width=width,
                         style="Dark.TCombobox", font=ui.fonts.body)
        self.command = command
        # `most`: as wide as its row leaves it, from `width` characters up to `most` (a sound device's long name in a
        # wide card, the least in a narrow one), set when the row is laid out (_fit_room).
        self.least, self.most = width, most
        if most:
            parent.bind("<Configure>", lambda e: self._fit_room(), add="+")
        # The list while it is open, else None.
        self.droplist = None
        self.set_value(value)
        self.bind("<<ComboboxSelected>>", self._chosen)
        # The launcher's list opens in place of Tk's, by the mouse and by the keys a drop-down opens with.
        self.bind("<ButtonPress-1>", lambda e: self.open() or "break")
        for key in ("<Down>", "<Alt-Down>", "<Return>", "<KP_Enter>", "<space>", "<F4>"):
            self.bind(key, lambda e: self.open() or "break")
        # The arrow up and down while closed step nothing (Tk's would choose without saying so).
        self.bind("<Up>", lambda e: "break")

    def _fit_room(self):
        """The box as wide as its row leaves it right of where it starts, in whole characters between its least and its
        most (Tk sizes a drop-down by characters of its font): set again only when that changed."""
        if not self.winfo_exists() or not self.winfo_ismapped():
            return
        # Its row's width right of where the box starts in it.
        room = self.master.winfo_width() - self.winfo_x()
        # The box's own edge and arrow, and one character's width, as Tk measures a box of `width` characters.
        each = max(1, self.ui.fonts.body.measure("0"))
        edge = self.winfo_reqwidth() - int(self.cget("width")) * each
        chars = max(self.least, min(self.most, (room - edge) // each))
        if chars != int(self.cget("width")):
            self.configure(width=chars)

    def open(self):
        """Open the list under the box (over it when the display has no room under it), the chosen row lit."""
        if self.droplist is not None or str(self.cget("state")) == "disabled":
            return
        self.focus_set()
        self.droplist = DropList(self)

    def closed(self, index=None):
        """The list closed: with the row chosen (`index`), the box shows it and says it was chosen; the keyboard is back
        on the box."""
        self.droplist = None
        if not self.winfo_exists():
            return
        # The keyboard back on the box: the list's window had it, and the system gives it back to nothing by itself.
        self.focus_force()
        if index is not None and index != self.current():
            self.current(index)
            self.event_generate("<<ComboboxSelected>>")

    def set_options(self, options, value):
        """Other choices (the frame limits a display brings), the one shown kept, in place."""
        options = list(options)
        if options != self.options:
            pad, _ = list_pad(self.ui)
            self.options = options
            self.configure(values=[pad + t for _, t in self.options])
        self.set_value(value)

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


class DropList(tk.Toplevel):
    """A drop-down's opened list, in the launcher's design: a raised, opaque surface one seam round, a little room at its
    top and foot, rows as tall as the site's list rows. The chosen row has the lime rule along its left edge and its
    words white; the row under the pointer, or the one the arrow keys reached, is lit (the keyboard's with the cyan ring
    round it). Up to ROWS rows show at once; a longer list scrolls by the wheel and the keys, with a thin bar along its
    right edge. It opens under the box, or over it when the display has no room under it, and inside the display's
    edges whatever the window's place. A click on a row, Enter or Space chooses it; Esc, Tab, a click outside or the
    window going away closes it as it was."""

    # The rows that show at once, a row's height, the room above the first and under the last, the scroll bar's width,
    # the gap between the box and the list (logical pixels).
    ROWS, ROW_H, PAD, BAR, GAP = 8, 34, 6, 4, 4

    def __init__(self, select):
        super().__init__(select)
        self.select, self.ui = select, select.ui
        px = self.ui.px
        # A window of its own with nothing of the system's round it.
        self.overrideredirect(True)
        self.configure(bg=theme.LINE)
        options = select.options
        self.count = len(options)
        self.chosen = select.current() if self.count else -1
        # The row the keyboard or the pointer is on: the chosen one first.
        self.active = max(0, self.chosen)
        self.keyboard = False
        self.top_row = 0
        shown = min(self.ROWS, self.count)
        self.scrolls = self.count > self.ROWS
        # As wide as the box, or wider for the longest words (with the room either side and the mark's).
        font = self.ui.fonts.body
        text_x = px(LIST_TEXT)
        widest = max([font.measure(text) for _, text in options] or [0])
        width = max(select.winfo_width(), text_x + widest + px(LIST_TEXT) + (px(self.BAR) + px(6) if self.scrolls else 0))
        height = 2 * px(self.PAD) + shown * px(self.ROW_H)
        self.edge = max(1, px(1))
        self.canvas = tk.Canvas(self, width=width - 2 * self.edge, height=height - 2 * self.edge, bg=LIST_BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack(padx=self.edge, pady=self.edge)
        self.size = (width, height)
        # The words where the closed box's start: LIST_TEXT inside the seam, which here is the list's own edge.
        self.text_x = text_x
        # Under the box, inside the display that holds it; over the box when there is no room under it.
        from opendmtq_client.window_room import room_at
        left, top = select.winfo_rootx(), select.winfo_rooty()
        room = room_at(select, left, top)
        x = min(max(left, room[0]), room[0] + room[2] - width)
        below = top + select.winfo_height() + px(self.GAP)
        above = top - px(self.GAP) - height
        y = below if below + height <= room[1] + room[3] or above < room[1] else above
        self.opened_above = y == above
        self.geometry("%dx%d+%d+%d" % (width, height, x, y))
        # The chosen row in view, in the list's middle when it can be.
        self._scroll_to(self.active, middle=True)
        self.draw()
        # A press that becomes a drag scrolls the rows, as a finger does on a touch screen; a press that does not move
        # chooses its row when it is let go.
        self._drag = None
        for sequence, handler in (("<Motion>", self._pointer), ("<ButtonRelease-1>", self._release),
                                  ("<ButtonPress-1>", self._drag_start), ("<B1-Motion>", self._drag_move), ("<MouseWheel>", self._wheel),
                                  ("<Button-4>", lambda e: self._scroll(-1)), ("<Button-5>", lambda e: self._scroll(1))):
            self.canvas.bind(sequence, handler)
        for key, move in (("<Down>", 1), ("<Up>", -1), ("<Next>", self.ROWS), ("<Prior>", -self.ROWS)):
            self.bind(key, lambda e, m=move: self._key(m))
        self.bind("<Home>", lambda e: self._key(-self.count))
        self.bind("<End>", lambda e: self._key(self.count))
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            self.bind(key, lambda e: self.choose(self.active))
        self.bind("<Escape>", lambda e: self.close())
        self.bind("<Tab>", lambda e: self.close(then_tab=1))
        self.bind("<Shift-Tab>", lambda e: self.close(then_tab=-1))
        self.bind("<ISO_Left_Tab>", lambda e: self.close(then_tab=-1))
        # A press anywhere outside the list closes it (the grab sends every press to the list, with where it was).
        self.bind("<ButtonPress-1>", self._press_anywhere)
        # The window going away (minimised) or moving closes it too (the list would stay where the box was), and so
        # does the keyboard going to another program.
        top = select.winfo_toplevel()
        self._root_unmap = top.bind("<Unmap>", lambda e: self.close(), add="+")
        self._root_place = (top.winfo_rootx(), top.winfo_rooty(), top.winfo_width(), top.winfo_height())
        self._root_moved = top.bind("<Configure>", lambda e: e.widget is top and self._moved(top), add="+")
        self.after_idle(lambda: self.winfo_exists() and self.bind("<FocusOut>", self._focus_out))
        self.update_idletasks()
        try:
            self.grab_set()
        except tk.TclError:
            # Another grab holds the screen (a dialog): the list still works by the pointer over it.
            pass
        self.focus_set()

    def _rows_box(self, index):
        """The row's (x0, y0, x1, y1) in the canvas, or None when it is scrolled out of view."""
        px = self.ui.px
        i = index - self.top_row
        if not 0 <= i < min(self.ROWS, self.count):
            return None
        width = int(self.canvas.cget("width"))
        right = width - (px(self.BAR) + px(6) if self.scrolls else 0)
        y0 = px(self.PAD) - self.edge + i * px(self.ROW_H)
        return (px(4), y0, right - px(4), y0 + px(self.ROW_H))

    def draw(self):
        """The rows in view, their marks and the scroll bar."""
        px = self.ui.px
        c = self.canvas
        c.delete("all")
        width, height = int(c.cget("width")), int(c.cget("height"))
        # The surface's top edge catches the light, as a raised panel's does.
        c.create_rectangle(0, 0, width, max(1, px(1)), fill=LIST_TOP, width=0)
        for index in range(self.top_row, min(self.count, self.top_row + self.ROWS)):
            x0, y0, x1, y1 = self._rows_box(index)
            lit = index == self.active
            if lit:
                c.create_rectangle(x0, y0, x1, y1, fill=theme.RAIL_UP, width=0)
            if index == self.chosen:
                # The chosen one: the lime rule along its left edge.
                c.create_rectangle(x0, y0 + px(6), x0 + px(3), y1 - px(6), fill=theme.OK, width=0)
            if lit and self.keyboard:
                # The keyboard's place: the cyan ring round the row it reached.
                ring = max(1, px(2))
                c.create_rectangle(x0 + ring // 2, y0 + ring // 2, x1 - (ring + 1) // 2, y1 - (ring + 1) // 2,
                                   outline=theme.CYAN, width=ring)
            colour = theme.TEXT if (lit or index == self.chosen) else theme.MUTED
            c.create_text(self.text_x, (y0 + y1) // 2, text=self.select.options[index][1], anchor="w",
                          font=self.ui.fonts.body_bold if index == self.chosen else self.ui.fonts.body, fill=colour)
        if self.scrolls:
            # The bar: its track faint, its thumb as long as the share in view, where the view is.
            bx1 = width - px(6)
            bx0 = bx1 - px(self.BAR)
            top, bottom = px(self.PAD), height - px(self.PAD)
            c.create_rectangle(bx0, top, bx1, bottom, fill=theme.RAIL, width=0)
            span = bottom - top
            thumb = max(px(18), span * self.ROWS // self.count)
            start = top + (span - thumb) * self.top_row // max(1, self.count - self.ROWS)
            c.create_rectangle(bx0, start, bx1, start + thumb, fill=theme.FAINT, width=0)

    def _scroll_to(self, index, middle=False):
        """The rows scrolled so that `index` is in view (in the middle, when told and the list allows)."""
        if not self.scrolls:
            return
        if middle:
            self.top_row = index - self.ROWS // 2
        elif index < self.top_row:
            self.top_row = index
        elif index >= self.top_row + self.ROWS:
            self.top_row = index - self.ROWS + 1
        self.top_row = max(0, min(self.top_row, self.count - self.ROWS))

    def _scroll(self, rows):
        if self.scrolls:
            self.top_row = max(0, min(self.top_row + rows, self.count - self.ROWS))
            self.draw()

    def _wheel(self, event):
        # Windows' 120 a notch, a row each.
        self._scroll(-1 if event.delta > 0 else 1)

    def _at(self, y):
        for index in range(self.top_row, min(self.count, self.top_row + self.ROWS)):
            _x0, y0, _x1, y1 = self._rows_box(index)
            if y0 <= y < y1:
                return index
        return None

    def _pointer(self, event):
        index = self._at(event.y)
        if index is not None and (index != self.active or self.keyboard):
            self.active, self.keyboard = index, False
            self.draw()

    def _drag_start(self, event):
        self._drag = {"y": event.y_root, "top": self.top_row, "moved": False}

    def _drag_move(self, event):
        drag = self._drag
        if not drag or not self.scrolls:
            return
        dy = event.y_root - drag["y"]
        if not drag["moved"] and abs(dy) < self.ui.px(PAN_START):
            return
        drag["moved"] = True
        rows = int(round(-dy / float(self.ui.px(self.ROW_H))))
        top = max(0, min(drag["top"] + rows, self.count - self.ROWS))
        if top != self.top_row:
            self.top_row = top
            self.draw()

    def _release(self, event):
        dragged = bool(self._drag and self._drag["moved"])
        self._drag = None
        if dragged:
            # A drag scrolled the rows: nothing chosen.
            return
        index = self._at(event.y)
        if index is not None and 0 <= event.x < int(self.canvas.cget("width")):
            self.choose(index)

    def _press_anywhere(self, event):
        """A press with the grab: outside the list's own box closes it; inside, its row is chosen at the release."""
        x, y = event.x_root - self.winfo_rootx(), event.y_root - self.winfo_rooty()
        if not (0 <= x < self.size[0] and 0 <= y < self.size[1]):
            self.close()
            return "break"
        return None

    def _moved(self, top):
        """The window moved or changed its size: the list, placed for where the box was, closes."""
        place = (top.winfo_rootx(), top.winfo_rooty(), top.winfo_width(), top.winfo_height())
        if place != self._root_place:
            self.close()

    def _focus_out(self, event):
        """The keyboard went to another program (the list's own window keeps it while open): the list closes."""
        if event.widget is self and self.focus_get() is None:
            self.close()

    def _key(self, move):
        self.keyboard = True
        self.active = max(0, min(self.count - 1, self.active + move))
        self._scroll_to(self.active)
        self.draw()
        return "break"

    def choose(self, index):
        self.close(index=index)
        return "break"

    def close(self, index=None, then_tab=0):
        """The list gone; the box told what was chosen (or nothing), and the keyboard on it, or on the control Tab goes
        to from it."""
        if not self.winfo_exists():
            return "break"
        # Only this list's lines of the window's bindings go (Python's unbind would take every line with them).
        unbind_one(self.select.winfo_toplevel(), "<Unmap>", self._root_unmap)
        unbind_one(self.select.winfo_toplevel(), "<Configure>", self._root_moved)
        try:
            self.grab_release()
        except tk.TclError:
            pass
        select = self.select
        self.destroy()
        if select.winfo_exists():
            select.closed(index)
            if then_tab:
                target = select.tk_focusNext() if then_tab > 0 else select.tk_focusPrev()
                if target is not None:
                    target.focus_set()
        return "break"


def unbind_one(widget, sequence, command):
    """Take one binding's line (the command bind(..., add="+") gave) out of a widget's binding, the others kept, and
    the command with it."""
    try:
        script = widget.tk.call("bind", widget._w, sequence)
        kept = "\n".join(line for line in str(script).split("\n") if command not in line)
        widget.tk.call("bind", widget._w, sequence, kept)
        widget.deletecommand(command)
    except tk.TclError:
        # The window went first, its bindings and commands with it.
        pass


# The words' own font files by Tk's family and weight, to measure where the eye finds their middle (words_top).
FACE_FILES = {("Pretendard", "normal"): "Pretendard-Regular.ttf", ("Pretendard", "bold"): "Pretendard-Bold.ttf",
              ("Pretendard SemiBold", "normal"): "Pretendard-SemiBold.ttf",
              ("Pretendard SemiBold", "bold"): "Pretendard-SemiBold.ttf"}
# Hangul syllables' ink, over and under the baseline as shares of the em, by face and syllables (measured once each).
_HANGUL_INK = {}


def words_top(font, words, widget, middle):
    """The top at which Tk sets one line of `words` in `font` (a canvas text item anchored at its top) so that the eye
    finds their middle on `middle` (pixels of `widget`'s screen): the middle of the capitals' height for words with
    Latin letters or figures (Pretendard's cap height, theme.TEXT_CAP), of the syllables' ink for Hangul alone. A line
    box centred there (Tk's own centring) stands its capitals half a pixel low at 200 %: a button's words then sit
    under its middle (client/tests/ui/design.py measures it)."""
    import os
    size = float(font.actual("size"))
    # The em in pixels on this screen: a size in points, or in pixels when negative.
    em = size * widget.winfo_fpixels("1p") if size > 0 else -size
    hangul = "".join(ch for ch in words if "가" <= ch <= "힣")
    if hangul and not any(ch.isascii() and ch.isalnum() for ch in words):
        actual = font.actual()
        key = (actual["family"], actual["weight"], hangul)
        if key not in _HANGUL_INK:
            from PIL import ImageFont
            path = os.path.join(theme.FONT_DIR, FACE_FILES.get((actual["family"], actual["weight"]),
                                                               "Pretendard-Regular.ttf"))
            # Measured large, as shares of the em: the same at any size, to a thousandth of it (a pixel's 0.03 at
            # 200 %), so that the whole pixel the words are set on is the nearest to their middle.
            box = ImageFont.truetype(path, 1000).getbbox(hangul, anchor="ls")
            _HANGUL_INK[key] = (-box[1] / 1000.0, box[3] / 1000.0)
        over, under = _HANGUL_INK[key]
        lift = em * (over - under) / 2.0
    else:
        lift = em * theme.TEXT_CAP / 2.0
    # The baseline the eye's middle asks for, less the font's ascent as Tk lays the line out from its top.
    return int(round(middle + lift - font.metrics("ascent")))


# The opened list's surface: opaque, a step lighter than a card, and the light along its top edge.
LIST_BG, LIST_TOP = "#20262d", "#3a434d"


# The room between the widest setting name of a page and the controls' column, in logical pixels (a step of the spacing
# scale: the names' column is the widest name and this).
LABEL_GAP = 16


def name_width(ui, names):
    """How wide a column of setting names must be for `names`: the widest of them in the names' font, and the room after
    it. Measured, never a number fixed for one system's font: Windows draws Pretendard wider than Linux does."""
    return max(ui.fonts.body_bold.measure(name) for name in names) + ui.px(LABEL_GAP)


def setting_row(parent, ui, title, control_factory, hint=None, bg=None, hints=()):
    """A setting: its name on the left, the control on the right of it, the hint underneath. The page fits one column
    for its rows' names afterwards (fit_names); until then the row's own name sets it. `hints`: every hint the row may
    say (each choice's own), for a row whose choice also brings or takes a row: its hint keeps the room of the longest
    (keep_room), so that the row that comes is laid out with everything under it in one pass."""
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
    # ring (and the switch the room round its pill) before what shows, so the others are set in by as much.
    align = max(1, ui.px(2)) + art.TOGGLE_HALO
    # A control that takes its column's room (a slider, a device's drop-down) is laid across it; any other is as wide as
    # it is.
    control.grid(row=0, column=1, sticky="we" if getattr(control, "odq_fill", False) else "w",
                 padx=(max(0, align - getattr(control, "odq_inset", 0)), 0))
    hint_label = None
    if hint:
        hint_label = label(row, ui, hint, font=ui.fonts.small, fg=theme.MUTED, bg=bg, wrap_margin=4)
        # As wide as the row, whatever its words: other words (a choice's own hint, say) are drawn whole in the same box at
        # once, never cut for a moment while the row makes room for them.
        hint_label.grid(row=1, column=0, columnspan=2, sticky="we", pady=(ui.px(4), 0))
    row.control, row.hint = control, hint_label
    if hint_label is not None and hints:
        # Its words at the top of its room (the shorter hints leave the rest of it under them), and every hint it may
        # say known to it, its own first.
        hint_label.configure(anchor="nw")
        hint_label.odq_texts = tuple(dict.fromkeys((hint,) + tuple(hints)))

    def say(text):
        """Another hint under the row (a choice's own), in place."""
        if row.hint is not None and row.hint.cget("text") != text:
            texts = getattr(row.hint, "odq_texts", None)
            if texts is not None and text not in texts:
                # Words it was not told of: its room made for them too before they show.
                row.hint.odq_texts = texts + (text,)
                wrap = row.hint.cget("wraplength")
                keep_room(row.hint, int(row.hint.winfo_fpixels(str(wrap))))
            row.hint.configure(text=text)

    row.say = say
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


# The room over and under a header strip's line (Card's strip), in logical pixels: a list's step, so that the strip
# stays a band over the card's body rather than a block of its own.
STRIP_PAD = 8


class Card(tk.Frame):
    """A panel as the site's cards: the deck's colour, opaque to read on, with the site's glass edge (a hairline all
    round, its top row brighter: theme.HAIRLINE, theme.RIM), the top-right corner cut, the site's 24 px inside, and its
    title in Pretendard Bold with nothing after it. Content goes into `body`; `head` holds the title and anything at its
    right end. On a page's field, what shows beyond the cut is the page's own picture (ScrollArea._paint_field).

    Each card's role gives it its own surface and silhouette from the same few means, one family: a surface a step
    nearer or deeper than the deck (`fill`), the edge's light brighter or none (`rim`), a deeper cut (`cut`) and one at
    its foot (`foot`), a header strip for its title (`strip`). pages.py has the roles: the PLAY page's head, the panels
    that report a state, the results, the quiet About."""

    CUT = 16

    def __init__(self, parent, ui, title=None, pad=24, cut=None, foot=False, fill=None, rim=theme.RIM, strip=None):
        # What lies beyond the cut: the colour of the nearest frame round the card that has one (a card's holder on a
        # page has none of its own, pages._holder: the page's field round it shows).
        round_it, outside = parent, parent.cget("bg")
        while not str(outside) and round_it.master is not None:
            round_it = round_it.master
            outside = round_it.cget("bg")
        # The edge's width: a pixel at 100 %, two at 200 %, as the site's 1 px line is on a screen of that density.
        edge = max(1, ui.px(1))
        # Its surface: the deck (a reading surface, opaque), or the role's own (`fill`: the page's head a step nearer,
        # About a step deeper); `strip`: a header strip of that colour under the edge's light, across the card, holding
        # its title (a status panel's); `rim`: the edge's top row of light (None: the hairline alone, a quiet card).
        self.fill = fill or theme.PANEL
        super().__init__(parent, bg=self.fill, highlightthickness=edge, highlightbackground=theme.HAIRLINE,
                         highlightcolor=theme.HAIRLINE)
        # The edge is the card's own, not a ring inside it (tests/ui/spacing.py measures the padding from the outside).
        self.odq_inset = 0
        self.ui, self.edge, self.outside, self.strip = ui, edge, outside, strip if title else None
        # The room inside the edge: the site's padding counted from the card's outside, so its words stand where they
        # stood before the card had an edge.
        self.body = tk.Frame(self, bg=self.fill, padx=ui.px(pad) - edge, pady=ui.px(pad - 4) - edge)
        # Under a strip, the body's room counted from the strip's foot (no edge there): the edge's width more above it.
        self.body.pack(fill="both", expand=True, pady=(edge if self.strip else 0, 0))
        self.head, self.title = None, None
        if title:
            if self.strip:
                # Across the card, over the body, with the card's padding at its sides and a list's step over and under
                # its line, counted from the card's outside at its top (the edge's light is the strip's top row) and
                # from the strip's foot: the edge's width more room under the line, made by a band along its foot.
                self.head = tk.Frame(self, bg=self.strip, padx=ui.px(pad) - edge, pady=ui.px(STRIP_PAD) - edge)
                self.head.pack(fill="x", before=self.body)
                tk.Frame(self.head, bg=self.strip, height=edge).pack(side="bottom", fill="x")
            else:
                self.head = tk.Frame(self.body, bg=self.fill)
                self.head.pack(fill="x", pady=(0, ui.px(12)))
            surface = self.head.cget("bg")
            self.title = tk.Label(self.head, text=title, font=ui.fonts.card_title, fg=theme.TEXT, bg=surface)
            self.title.pack(side="left")
            # The title's line as tall as a button whether one stands at its right end or not: every card's title on one
            # line with its neighbour's in a row of cards, and what follows it at one depth in every card.
            tk.Frame(self.head, bg=surface, width=1, height=ui.px(Button.HEIGHT)).pack(side="right")
        if rim:
            # The top row of the edge in the brighter rim, over the hairline there (no room of its own).
            light = tk.Frame(self, bg=rim, height=edge)
            light.place(x=0, y=0, relwidth=1.0, height=edge, bordermode="outside")
        # The cut: a small picture over the square corner (over the edge's corner too), the page beyond it, the
        # hairline along the cut. `cut`: its size in logical pixels (the page's head has a larger one).
        self.cut = ui.px(cut or self.CUT)
        self._corner_label = tk.Label(self, bd=0, highlightthickness=0, bg=outside)
        self._corner_label.place(relx=1.0, x=-self.cut, y=0, width=self.cut, height=self.cut, bordermode="outside")
        # Where the corner was last cut for, and what it shows beyond the cut (_cut_over_field).
        self._corner_key, self._corner_shown = None, None
        self._paint_corner(outside)
        # `foot`: its bottom-left corner cut too (True: as deep as the top one; a number: that deep), the diagonal pair a
        # game's panels have (the last game, the records, the page's head), its picture the top one turned half round.
        self._foot_label = None
        if foot:
            self.foot = self.cut if foot is True else ui.px(foot)
            self._foot_label = tk.Label(self, bd=0, highlightthickness=0, bg=outside)
            self._foot_label.place(x=0, rely=1.0, y=-self.foot, width=self.foot, height=self.foot, bordermode="outside")
            self._foot_key, self._foot_shown = None, None
            self._paint_foot(outside)
        # On a page's field (no card round it), the picture beyond the cut follows the card where it stands.
        self.odq_area = None
        holder = parent
        while holder is not None and not isinstance(holder, Card):
            area = getattr(holder, "odq_area", None)
            if area is not None:
                self.odq_area = area
                break
            holder = holder.master
        if self.odq_area is not None and str(outside).lower() == str(self.odq_area.cget("bg")).lower():
            self.odq_area._cards.append(self)
            # Its corner follows the card where it stands: when it moves, and when the page's picture is drawn again.
            self.bind("<Configure>", lambda e: self._cut_over_field(), add="+")
            self._cut_over_field()

    def _corner_picture(self, beyond, half_round=False):
        """A cut corner's picture with `beyond` past the cut: a colour, or the page's picture there (the card's part
        laid over it, made once: art.corner_layer); `half_round`: the bottom-left one, the top-right turned half
        round. The card's own surface inside the cut: its header strip's at the top when it has one."""
        size = self.foot if half_round else self.cut
        inside = self.fill if half_round or not self.strip else self.strip
        if isinstance(beyond, str):
            picture = art.corner(size, inside, beyond, seam=theme.HAIRLINE, seam_width=self.edge)
            return picture.rotate(180) if half_round else picture
        layer = art.corner_layer(size, inside, seam=theme.HAIRLINE, seam_width=self.edge)
        if half_round:
            layer = layer.rotate(180)
        picture = beyond.convert("RGB")
        picture.paste(layer, (0, 0), layer)
        return picture

    def _paint_corner(self, beyond):
        """The top-right corner's picture with `beyond` past the cut (_corner_picture)."""
        picture = self._corner_picture(beyond)
        self._corner = ImageTk.PhotoImage(picture, master=self)
        self._corner_label.configure(image=self._corner)
        # A dialog draws the window from the widgets (snapshot.py): the corner as it shows.
        self._corner_label.odq_picture = picture

    def _paint_foot(self, beyond):
        """The bottom-left corner's picture with `beyond` past its cut (_corner_picture, turned half round)."""
        picture = self._corner_picture(beyond, half_round=True)
        self._foot = ImageTk.PhotoImage(picture, master=self)
        self._foot_label.configure(image=self._foot)
        # As the top corner's, for a dialog's picture of the window.
        self._foot_label.odq_picture = picture

    def _cut_over_field(self):
        """The page's picture beyond the cut, where the card now stands, without the field's faint dots (art.without_dots):
        drawn again only when what shows there changed, which on the plain field it does not, so that a card moved by a
        row that comes above it is not drawn again a moment after the move (client/tests/ui/flicker.py)."""
        area = self.odq_area
        if area is None or not self.winfo_exists() or self.winfo_width() <= 1:
            return
        # Each frame between the card and the page's column tells the page when it moves (a card made anew in a holder
        # of its own, pages.Sections, is moved by its holder, never by itself).
        holder = self.master
        while holder is not None and holder is not area.inner:
            area.watch(holder)
            holder = holder.master
        # Where it stands and how wide, on which picture: the corner is cut again only when one of them changed (the
        # page's field frames ask every card under them each time one of them moves).
        place, backdrop = area.page_box(self), id(getattr(area, "_backdrop_picture", None))
        key = (place, self.winfo_width(), backdrop)
        if self._foot_label is not None:
            self._cut_foot_over_field(area, place, backdrop)
        if key == self._corner_key:
            return
        picture = area.picture_at(self, self.winfo_width() - self.cut, 0, self.cut, self.cut)
        if picture is None:
            return
        self._corner_key = key
        beyond = art.without_dots(picture, self.ui.scale)
        shown = beyond.tobytes()
        if shown == self._corner_shown:
            return
        self._corner_shown = shown
        self._paint_corner(beyond)

    def _cut_foot_over_field(self, area, place, backdrop):
        """The bottom-left corner's cut over the page's picture where the card now stands, as the top one's: drawn
        again only when what shows there changed (a card that grows moves its foot)."""
        key = (place, self.winfo_height(), backdrop)
        if key == self._foot_key:
            return
        picture = area.picture_at(self, 0, self.winfo_height() - self.foot, self.foot, self.foot)
        if picture is None:
            return
        self._foot_key = key
        beyond = art.without_dots(picture, self.ui.scale)
        shown = beyond.tobytes()
        if shown == self._foot_shown:
            return
        self._foot_shown = shown
        self._paint_foot(beyond)


# The room either side of the faint line between two rows of a card's settings (logical pixels): a row's room, on the
# spacing scale.
ROW_GAP = 12


class RowList(tk.Frame):
    """A card's rows, each in a slot of its own with the card's faint line before it, that come and go in place: a choice
    that brings a row (the counter's corner, the upscaler) shows its slot, and one that takes it hides it, the rows
    before and after it as they were. Nothing else of the page is made again, so the window never shows a page half
    drawn (client/tests/ui/flicker.py)."""

    def __init__(self, parent, ui, pady=ROW_GAP):
        super().__init__(parent, bg=parent.cget("bg"))
        self.ui, self.pady = ui, pady
        # The slots in their order, and which of them show.
        self.slots, self.shown = [], {}

    def add(self, shown=True):
        """A new slot at the end: a frame to build its row in (slot.body), its line before it shown as needed."""
        slot = tk.Frame(self, bg=self.cget("bg"))
        slot.line = tk.Frame(slot, bg=theme.DIVIDER, height=1)
        slot.body = tk.Frame(slot, bg=self.cget("bg"))
        slot.body.pack(side="bottom", fill="x")
        self.slots.append(slot)
        self.shown[slot] = False
        self.show(slot, shown)
        return slot

    def show(self, slot, shown):
        """Show or hide one slot; the others stay mapped as they are (a slot taken off the screen and put back would
        show the card empty for a moment)."""
        shown = bool(shown)
        if self.shown.get(slot) == shown:
            return
        self.shown[slot] = shown
        if shown:
            # Its words wrapped for the width it will have (the list's own) before it shows, as a row shown for the
            # first time would otherwise show them wrapped narrow for a moment.
            width = self.winfo_width()
            if width > 1:
                found = [slot]
                while found:
                    widget = found.pop()
                    wrap = getattr(widget, "odq_wrap", None)
                    if wrap is not None and widget.master is not None and widget.master.master is slot.body:
                        wrap(width)
                    found.extend(widget.winfo_children())
            # Packed in its place among the shown ones: before the next shown slot, else after the last.
            index = self.slots.index(slot)
            later = [s for s in self.slots[index + 1:] if self.shown[s]]
            if later:
                slot.pack(fill="x", before=later[0])
            else:
                slot.pack(fill="x")
        else:
            slot.pack_forget()
        self._lines()

    def _lines(self):
        """A line before each shown slot but the first, changed only where it changes."""
        first = True
        for slot in self.slots:
            if not self.shown[slot]:
                continue
            wanted = not first
            if wanted and not slot.line.winfo_manager():
                slot.line.pack(side="top", fill="x", pady=self.ui.px(self.pady))
            elif not wanted and slot.line.winfo_manager():
                slot.line.pack_forget()
            first = False


def check_line(parent, ui, state, text, action_text=None, action=None, bg=theme.PANEL, value=None, column=None):
    """A ready-check row as the site's state rows: a small lamp (a lime dot fine, a yellow ring will change, a red dot a
    problem), the words, then what the row says of its state (`value`) and the way to fix it (a link), the link after
    the value on its line. With `column` (the widest name of the rows it stands among, in pixels: check_names), the
    words keep a names column and the value and the way to fix it stand after it, by their name, as a setting's control
    does; without, right after the words (never at the row's far end, away from the words they belong to)."""
    row = tk.Frame(parent, bg=bg)
    colour = {"ok": theme.OK, "change": theme.WARN, "bad": theme.BAD}[state]
    # What will change is a ring, so that it is told from what is fine by its shape too, not by its colour alone.
    light = lamp(row, ui, colour, bg=bg, hollow=state == "change")
    beside = [light]
    # The lamp's middle, from the row's top: the words' first line and what stands at the right end have their line's
    # middle there, so that they stand on one line whether the words wrap or not (pack centred the words alone, which
    # put a value held at the top two pixels above them, five at 200 %).
    middle = ui.px(1) + light.winfo_reqheight() / 2.0

    def at_middle(widget, font):
        """How far down `widget` goes for its words' line to have its middle on the lamp's."""
        # What the widget keeps above its words: its border, its padding and its keyboard ring.
        edge = sum(int(widget.winfo_fpixels(str(widget.cget(option))))
                   for option in ("borderwidth", "pady", "highlightthickness"))
        return max(0, round(middle - font.metrics("linespace") / 2.0 - edge))

    if column:
        # In a grid: the lamp, the words in the names column (the lamp's gap before them, the column's own room after
        # them), then the value, which wraps in the rest of the row, and the way to fix it after the value (a value and
        # its action on one line, VALUE_LINK apart), or in the value's place when the row says no value.
        light.grid(row=0, column=0, sticky="n", pady=(ui.px(1), 0))
        words = tk.Label(row, text=text, font=ui.fonts.body, fg=theme.TEXT, bg=bg, anchor="w", justify="left")
        fix = link(row, ui, action_text, action, bg=bg) if action_text and action else None
        what = None
        if value:
            # Wrapped in the room right of the names column: the lamp, the words and the link are counted as they stand
            # beside it, the column's own room past the words on top.
            what = label(row, ui, value, fg=theme.MUTED, bg=bg, beside=(light, words) + ((fix,) if fix else ()),
                         wrap_margin=max(0, column - words.winfo_reqwidth()) / max(1.0, ui.scale))
        if what is None and fix is None:
            # Nothing after the words (a game that is open): they take the whole row.
            words.grid(row=0, column=1, columnspan=3, sticky="nw", padx=(ui.px(6), 0),
                       pady=(at_middle(words, ui.fonts.body), 0))
        else:
            words.grid(row=0, column=1, sticky="nw", padx=(ui.px(6), 0), pady=(at_middle(words, ui.fonts.body), 0))
            if what is not None:
                what.grid(row=0, column=2, sticky="nw", pady=(at_middle(what, ui.fonts.body), 0))
            if fix is not None:
                # After the value, VALUE_LINK apart; at the value's place when there is none.
                fix.grid(row=0, column=3 if what is not None else 2, sticky="nw",
                         padx=(ui.px(VALUE_LINK) if what is not None else 0, 0),
                         pady=(at_middle(fix, ui.fonts.body_bold), 0))
        # The names column: the lamp's gap and the widest name with its room after it; the value and the link take the
        # rest, the room left after them at the row's end.
        row.columnconfigure(1, minsize=ui.px(6) + column)
        row.columnconfigure(4, weight=1)
        return row
    light.pack(side="left", anchor="n", pady=(ui.px(1), 0))
    # The words first, then what the row says and the way to fix it right after them, on the words' first line: a
    # value by the words it belongs to, never at the row's far end (the Sound page's last game said "3 gaps" at the
    # card's edge, away from its words).
    words = label(row, ui, text, fg=theme.TEXT, bg=bg, wrap_margin=24, beside=beside)
    words.pack(side="left", anchor="n", padx=(ui.px(6), 0), pady=(at_middle(words, ui.fonts.body), 0))
    if value:
        what = tk.Label(row, text=value, font=ui.fonts.body, fg=theme.MUTED, bg=bg)
        what.pack(side="left", anchor="n", padx=(ui.px(VALUE_LINK), 0), pady=(at_middle(what, ui.fonts.body), 0))
        # The words wrap in the room the value leaves them (its gap counted with it, as its own padding).
        beside.append(what)
    if action_text and action:
        # The way to fix it, reached by the mouse or the keyboard, after the words (and the value).
        fix = link(row, ui, action_text, action, bg=bg)
        fix.pack(side="left", anchor="n", padx=(ui.px(VALUE_LINK), 0), pady=(at_middle(fix, ui.fonts.body_bold), 0))
        beside.append(fix)
    return row


# The room between a state row's value and the way to fix it after it, and between a row's words and its value when the
# row keeps no names column (logical pixels): a value and its action on one line, as the forms keep them (16).
VALUE_LINK = 16


def check_names(ui, names):
    """The names column of state rows (check_line's `column`) for `names`: the widest of them in the words' face, and
    the column's room after it (the spacing scale's 16, as a setting's names column keeps)."""
    return max(ui.fonts.body.measure(name) for name in names) + ui.px(LABEL_GAP)


# Text selected in a field: the launcher's own colours, as a drop-down's chosen row has them, never Windows' blue.
SELECTION = {"selectbackground": theme.RAIL_UP, "selectforeground": theme.TEXT, "selectborderwidth": 0}


def entry(parent, ui, width=18, secret=False):
    """A text field as the site's: a dark field with a one-pixel seam, lime round it while typing."""
    field = tk.Entry(parent, width=width, font=ui.fonts.body, bg=theme.FIELD, fg=theme.TEXT, insertbackground=theme.TEXT,
                     relief="flat", highlightthickness=1, highlightbackground=theme.LINE, highlightcolor=theme.OK,
                     show="\u2022" if secret else "", **SELECTION)
    return field


def box_face(box, state):
    """The face of a text field or a key's box (`box`: its face_size and bg, its faces and images by state) in `state`,
    as a Tk image made the first time the box shows it (art.field_face, which keeps the faces it drew)."""
    if state not in box.images:
        box.faces[state] = art.field_face(box.face_size[0], box.face_size[1], state, box.ui.scale, bg=box.bg)
        box.images[state] = ImageTk.PhotoImage(box.faces[state], master=box)
    return box.images[state]


class Field(tk.Canvas):
    """A text field as the launcher's pages have it: the site's dark field sunk into its card (art.field_face: dark
    edges along its top and left, the light along its foot), the accent round it while it is typed in, brighter edges
    under the pointer, the error's colour round it while what was typed there is refused (set_error); as tall as a
    button, so a field and the buttons beside it stand on one line and one middle. The typing goes to `entry`, a plain Tk
    entry inside it; a click anywhere on the field puts the caret there.

    `placeholder`: words in the faint grey while the field is empty and not typed in (an example of what goes there).
    `reveal`: for a password, (Show, Hide) words at the field's right end that show what was typed and hide it again,
    by the mouse (Tab goes from the password to the button after it)."""

    def __init__(self, parent, ui, width=18, secret=False, placeholder=None, reveal=None):
        self.ui, bg = ui, parent.cget("bg")
        px = ui.px
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, cursor="xterm", takefocus=0)
        # Selected words in the launcher's colours (SELECTION), not Windows' blue.
        self.secret = secret
        self.entry = tk.Entry(self, width=width, font=ui.fonts.body, bg=theme.FIELD, fg=theme.TEXT,
                              insertbackground=theme.TEXT, relief="flat", bd=0, highlightthickness=0,
                              show="\u2022" if secret else "", **SELECTION)
        # The words' room either side of them, and the button's height.
        self.pad = px(10)
        width_px, height_px = self.entry.winfo_reqwidth() + 2 * self.pad, px(Button.HEIGHT)
        self.configure(width=width_px, height=height_px)
        # Each state's face made the first time the field shows it (box_face), then kept: the pointer and the keyboard
        # only swap them, and a page that makes its fields each time it is shown draws only the one each shows (art
        # keeps the faces it drew).
        self.face_size, self.bg, self.faces, self.images = (width_px, height_px), bg, {}, {}
        # Its face comes with the field's first look (_paint, below).
        self.face = self.create_image(0, 0, anchor="nw")
        # Show and Hide at the right end, in the field's own colours: the typing's room ends before them.
        self.reveal_words, self.toggle, room = reveal, None, 0
        if reveal:
            longest = max(ui.fonts.small.measure(words) for words in reveal)
            self.toggle = tk.Label(self, text=reveal[0], font=ui.fonts.small, fg=theme.MUTED, bg=theme.FIELD,
                                   cursor="hand2", width=0, anchor="e")
            # By a tap or a click, and by the keyboard: Tab reaches it after the password (its cyan ring), Enter or
            # Space shows or hides what was typed.
            focus_ring(self.toggle, ui, theme.FIELD)
            for sequence in ("<Button-1>", "<Return>", "<KP_Enter>", "<space>"):
                self.toggle.bind(sequence, lambda e: self.show_typed(self.entry.cget("show") != "") or "break")
            self.toggle.bind("<Enter>", lambda e: self.toggle.configure(fg=theme.TEXT))
            self.toggle.bind("<Leave>", lambda e: self.toggle.configure(fg=theme.MUTED))
            ring = int(self.toggle.cget("highlightthickness"))
            self.create_window(width_px - self.pad + ring, height_px // 2, window=self.toggle, anchor="e",
                               width=longest + 2 * ring)
            room = longest + px(10)
        # The entry in the middle of the face, between its rooms.
        self.create_window(self.pad, height_px // 2, window=self.entry, anchor="w", width=width_px - 2 * self.pad - room)
        # The example in the faint grey over the empty entry, shown while nothing is typed and the field is not typed in.
        self.hint = None
        if placeholder:
            self.hint = tk.Label(self, text=placeholder, font=ui.fonts.body, fg=theme.FAINT, bg=theme.FIELD, bd=0,
                                 cursor="xterm", anchor="w")
            self.hint.bind("<Button-1>", lambda e: (self.entry.focus_set(), self.entry.icursor("end")))
            self.hint_item = self.create_window(self.pad, height_px // 2, window=self.hint, anchor="w")
        self.focused, self.under, self.error = False, False, False
        self.entry.bind("<FocusIn>", lambda e: self._paint(focused=True), add="+")
        self.entry.bind("<FocusOut>", lambda e: self._paint(focused=False), add="+")
        # Typing takes back an error said about what was there.
        self.entry.bind("<Key>", lambda e: e.keysym not in ("Return", "KP_Enter", "Tab") and self.set_error(False),
                        add="+")
        for widget in (self, self.entry) + ((self.toggle,) if self.toggle else ()):
            widget.bind("<Enter>", lambda e: self._paint(under=True), add="+")
            widget.bind("<Leave>", lambda e: self._paint(under=False), add="+")
        # A click on the face beside the words: the caret at their end, as a click past the words in the entry does.
        self.bind("<Button-1>", lambda e: (self.entry.focus_set(), self.entry.icursor("end")))
        self._paint()

    def show_typed(self, on):
        """A password's typing shown (on) or hidden again as dots; the keyboard stays where it was."""
        if not self.secret:
            return
        self.entry.configure(show="" if on else "\u2022")
        if self.toggle is not None:
            self.toggle.configure(text=self.reveal_words[1 if on else 0])

    def set_error(self, on):
        """What was typed here was refused (on: the error's colour all round), or that is over."""
        on = bool(on)
        if on != self.error:
            self.error = on
            self._paint()

    def refresh(self):
        """The example shown or not, after words were put into the entry by the program."""
        self._paint()

    def _paint(self, focused=None, under=None):
        """The face for the field's state: the error's colour while refused, the accent while typed in, brighter edges
        under the pointer, else normal; the example while the field is empty and not typed in."""
        if focused is not None:
            self.focused = focused
        if under is not None:
            self.under = under
        if not self.winfo_exists():
            return
        state = "error" if self.error else "focus" if self.focused else ("hover" if self.under else "normal")
        self.itemconfigure(self.face, image=box_face(self, state))
        # A dialog draws the window behind it from the widgets (snapshot.py): the face as it looks now.
        self.odq_picture = self.faces[state]
        if self.hint is not None:
            empty = not self.entry.get()
            self.itemconfigure(self.hint_item, state="normal" if empty and not self.focused else "hidden")


class Said(tk.Frame):
    """One line that says how something stands, as the site's state rows do: a small lamp in the tone's colour (none
    for a plain note) and the words, wrapping to the line's width; said again in place by set()."""

    TONES = {"ok": theme.OK, "warn": theme.WARN, "bad": theme.BAD}

    def __init__(self, parent, ui, font=None, bg=None):
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.bg = ui, bg
        self.font = font or ui.fonts.small
        self.lamp = tk.Label(self, bg=bg, bd=0)
        self.words = label(self, ui, "", font=self.font, fg=theme.MUTED, bg=bg, wrap_margin=0, beside=(self.lamp,))
        # At the line's top: its first line on the lamp's middle while there is a lamp (set), however many lines it
        # wraps to.
        self.words.pack(side="right", fill="x", expand=True, anchor="n")
        self._pictures = {}
        self.tone = None

    def set(self, text, tone=None):
        """The words and their tone: "ok", "warn", "bad" (with the lamp in that colour, the words in the text's
        colour), or None (no lamp, the words muted). A warning's lamp is a ring, as every lamp of something that is
        not as it should be (the ready check's, the test's steps'): one shape for one state."""
        from PIL import ImageTk
        self.tone = tone
        if tone in self.TONES:
            if tone not in self._pictures:
                picture = art.lamp(self.TONES[tone], self.ui.scale, bg=self.bg, lead=False, hollow=tone == "warn")
                self._pictures[tone] = (picture, ImageTk.PhotoImage(picture, master=self))
            picture, image = self._pictures[tone]
            self.lamp.configure(image=image)
            self.lamp.odq_picture = picture
            if not self.lamp.winfo_manager():
                self.lamp.pack(side="left", anchor="n", padx=(0, self.ui.px(6)), pady=(self.ui.px(1), 0))
                # The words' first line on the lamp's middle, as a ready-check row's (check_line).
                middle = self.ui.px(1) + picture.height / 2.0
                self.words.pack_configure(pady=(max(0, int(round(middle - self.font.metrics("linespace") / 2.0))), 0))
        elif self.lamp.winfo_manager():
            self.lamp.pack_forget()
            self.words.pack_configure(pady=0)
        colour = theme.MUTED if tone is None else (theme.BAD if tone == "bad" else theme.TEXT)
        self.words.configure(text=text, fg=colour)


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
        # Each state's face made the first time the box shows it (box_face), then kept: the pointer and the wait only
        # swap them, and the Controls page, which makes its lanes' boxes each time it is shown, draws only the one
        # each shows (art keeps the faces it drew).
        self.face_size, self.faces, self.images = (width, height), {}, {}
        # Its face comes with the box's first look (_paint, below).
        self.face = self.create_image(self.inset, self.inset, anchor="nw")
        # A dialog draws the window behind it from the widgets (snapshot.py): the box as it looks then, put together
        # only when one asks (_picture).
        self.odq_picture = self._picture
        # The words in the box's middle, the name in the labels' face, the print smaller and grey.
        x, middle = self.inset + (width - words_width) // 2, self.inset + height // 2
        self.create_text(x, middle, text=words, font=name_font, fill=theme.TEXT if key else theme.MUTED, anchor="w")
        if printed:
            self.create_text(x + name_width + px(self.GAP), middle, text=printed, font=print_font, fill=theme.MUTED,
                             anchor="w")
        # Its words' items, in their own colours, for the dimmed look (set_enabled).
        self.words_items = [item for item in self.find_all() if self.type(item) == "text"]
        self.words_colours = [self.itemcget(item, "fill") for item in self.words_items]
        self.enabled = True
        self.bind("<Enter>", lambda e: self._paint(under=True))
        self.bind("<Leave>", lambda e: self._paint(under=False))
        self._paint()

    def set_enabled(self, on):
        """In use (keyboard play on), or dimmed: its words in the faintest grey, no brighter edges under the pointer,
        skipped by Tab and the pointer's hand, as the lanes stand while keyboard play is off (a card of the switch
        alone held a single setting)."""
        self.enabled = bool(on)
        for item, colour in zip(self.words_items, self.words_colours):
            self.itemconfigure(item, fill=colour if self.enabled else theme.FAINT)
        self.configure(takefocus=1 if self.enabled else 0, cursor="hand2" if self.enabled else "arrow")
        self._paint(under=False)

    def set_waiting(self, on):
        """Waiting for a key (the accent round it, the cyan ring away: the accent says where the key goes), or not."""
        self.waiting = bool(on)
        self.configure(highlightcolor=self.bg if self.waiting else theme.CYAN)
        self._paint()

    def _paint(self, under=None):
        """The face for the box's state: the accent while it waits, brighter edges under the pointer, else normal."""
        if under is not None:
            # A dimmed box's edges stay as they are under the pointer: it takes no key now.
            self.under = under and getattr(self, "enabled", True)
        self.state = "focus" if self.waiting else ("hover" if self.under else "normal")
        self.itemconfigure(self.face, image=box_face(self, self.state))

    def _picture(self):
        """The box as it looks now, for a dialog (snapshot.py): the face where it shows, inside the ring's room in the
        card's colour."""
        from PIL import Image
        face = self.faces[self.state]
        whole = Image.new("RGB", (face.width + 2 * self.inset, face.height + 2 * self.inset), art._rgb(self.bg))
        whole.paste(face, (self.inset, self.inset))
        return whole


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
