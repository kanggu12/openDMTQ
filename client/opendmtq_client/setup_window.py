"""The installer's window (OpenDMTQ-Setup.exe, and the uninstall Windows' Settings, Apps starts), drawn as the launcher
is: a column down its left with the wordmark, the version and the steps of what it does, the page beside it with its
title in the site's leaning face over the site's field, the page's card, and a strip along the foot with the buttons,
the main one lime (or red to remove for good) and the others quiet.

It has no title bar of Windows' (frameless.py): its own header holds the page's title and, at the top right, the
window's minimise and close buttons in the launcher's quiet metal, and the window's top (the header and the column above
its steps) moves the window.

installer.py decides what each page says and does; this module only draws: SetupWindow.page() starts a page, made off
the screen and shown whole by show_page(), Options a list of choices on it, Progress the work under way, and lines()
what came of it. Nothing here asks the system anything but frameless.py's calls for the window itself.
"""

import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

from opendmtq_client import art, frameless, safety, theme, widgets

# The window's size when the screen has room for it, the column's width and the strip's height along the foot, and the
# room inside the column and the strip (logical pixels).
WIDTH, HEIGHT = 800, 540
COLUMN, FOOT, EDGE = 220, 72, 20
# How far down the page its lit top reaches before it has faded (logical pixels), as on the launcher's pages.
PAGE_LIGHT = 300
# The room between two lines of a card (what came of the work, a card's facts), on the launcher's spacing scale.
LINE_GAP = 12
# The window's own buttons at the right of its header: their size, the room between them, how far down from the window's
# top they start (level with the wordmark's top in the column) and how far in from its right edge (the column's own
# edge, mirrored), and the least room between the page's title and them (logical pixels).
BUTTON, BUTTON_GAP, BUTTON_TOP, BUTTON_RIGHT, TITLE_ROOM = 32, 8, EDGE + 2, EDGE, 16
# The smallest the page's title is drawn where the window is too narrow for it beside the buttons (the site's 42 px
# otherwise).
TITLE_LEAST = 24
# The title's picture in the header: its top (its capitals then start level with the wordmark's and the buttons' top),
# and the room under it, which keeps the letters that reach under the line clear of the header's seam once the page has
# moved (logical pixels).
TITLE_TOP, TITLE_FOOT = 18, 6


def placement(root, px, caption=0):
    """The window's (width, height, x, y) inside the room windows have (the screen less the taskbar), as the launcher's
    window opens: its size where there is room, a third of the way down, never under the taskbar. `caption` is a title
    bar of Windows' to count above it: none, as the window has none (frameless.py), unless taking it off failed."""
    from opendmtq_client import window_room
    return window_room.window_box(window_room.work_area(root), caption, px(WIDTH), px(HEIGHT))


class SetupWindow:
    """The installer's window: `words` (i18n.Words) in `language`, the version it shows beside the wordmark, and what
    closing it does (`on_close`, which may refuse while work is under way)."""

    def __init__(self, words, language, version, title, on_close):
        # A window of its own: never on a real screen from a test.
        safety.refuse_windows_in_tests("the installer's window")
        from opendmtq_client import dialogs
        theme.register_fonts()
        self.words, self.on_close, self.shown = words, on_close, False
        # What the page on show gave the keyboard (focus_later), given it again as the window first shows.
        self.wanted = None
        self.root = tk.Tk()
        # Out of sight until its first page is laid out and Windows' title bar is gone (show()): nothing flashes.
        self.root.withdraw()
        # The window's name on the taskbar, in Alt+Tab and for screen readers, as before.
        self.root.title(title)
        self.root.configure(bg=theme.BG)
        # The mark on the taskbar and in Alt+Tab, as the launcher's.
        dialogs.set_icon(self.root)
        self.scale = theme.scale_of(self.root)
        self.ui = widgets.Ui(self.root, theme.Fonts(self.root, language), self.scale, words)
        # The page's scroll bar in the launcher's dark style.
        widgets.style_ttk(self.ui)
        # Inside the room windows have, with no title bar of Windows' to count: the window has none (show()).
        self.box = placement(self.root, self.ui.px)
        self.root.geometry("%dx%d+%d+%d" % self.box)
        # One size: an installer's window is not made larger or smaller.
        self.root.resizable(False, False)
        # Alt+F4 and the taskbar's Close window ask what the header's close button asks.
        self.root.protocol("WM_DELETE_WINDOW", on_close)
        # Esc answers the page as its quiet button does (Cancel, Close, Back), while it has one.
        self.root.bind("<Escape>", lambda e: self._escape())
        # What moves the window by its top, now that Windows' title bar is gone.
        self.mover = frameless.Mover(self.root)
        self._build(version)

    def show(self):
        """Bring the window up once its first page is laid out: on Windows without Windows' title bar, rounded and
        shadowed where Windows 11 does it (frameless.py), its own buttons named for screen readers; then in front,
        with the keyboard."""
        if self.shown:
            return
        self.shown = True
        # Laid out out of sight: on Windows Tk makes the window it wraps the installer in now, hidden.
        self.root.update_idletasks()
        if frameless.supported():
            if not frameless.apply(self.root, self.box):
                # Windows' title bar stayed: placed again with it counted, so that the strip stays above the taskbar.
                from opendmtq_client.window_room import title_bar_height
                self.box = placement(self.root, self.ui.px, title_bar_height())
                self.root.geometry("%dx%d+%d+%d" % self.box)
            for button in self.header.buttons:
                frameless.name(button, button.words)
        # Shown and raised (Tk's deiconify brings a window to the front on Windows)...
        self.root.deiconify()
        # ...where Tk gives the keyboard to the window itself, dropping what the page asked for while it was out of
        # sight: back to what the page gave it (its main button, its choices), in front.
        if self.wanted is not None and self.wanted.winfo_exists():
            self.wanted.focus_force()

    def focus_later(self, widget):
        """The keyboard to `widget` once the window has drawn what is new (Tk's idle work), and again as the window first
        shows (show())."""
        self.wanted = widget
        self.root.after_idle(lambda: widget.winfo_exists() and widget.focus_set())

    # --------------------------------------------------------------------------------------------- the frame

    def _build(self, version):
        ui, px = self.ui, self.ui.px
        # ---- the column: the wordmark with SETUP and the version beside it, then the steps.
        column = tk.Frame(self.root, bg=theme.STRIP, width=px(COLUMN))
        column.pack(side="left", fill="y")
        # Its own width whatever it holds.
        column.pack_propagate(False)
        # The seam along its right edge, where the page begins.
        tk.Frame(column, bg="#2a3038", width=max(1, px(1))).pack(side="right", fill="y")
        brand = art.brand(self.scale, "v" + version, mark=24, label="SETUP")
        self._brand = ImageTk.PhotoImage(brand, master=column)
        mark = self.mark = tk.Label(column, image=self._brand, bg=theme.STRIP, bd=0)
        # A dialog would draw the window from its widgets: the mark's own picture.
        mark.odq_picture = brand
        mark.pack(side="top", anchor="w", padx=(px(EDGE), 0), pady=(px(EDGE + 2), px(26)))
        self.steps = Steps(column, ui)
        self.steps.pack(side="top", fill="x")
        # ---- the right side: the strip with the buttons along its foot, the page over it.
        right = tk.Frame(self.root, bg=theme.BG)
        right.pack(side="left", fill="both", expand=True)
        strip = tk.Frame(right, bg=theme.STRIP, height=px(FOOT))
        strip.pack(side="bottom", fill="x")
        # One height whatever it holds.
        strip.pack_propagate(False)
        # Its seam along the top, as the column's along its side.
        tk.Frame(strip, bg="#2a3038", height=max(1, px(1))).pack(side="top", fill="x")
        self.strip = tk.Frame(strip, bg=theme.STRIP)
        self.strip.pack(fill="both", expand=True, padx=px(EDGE + 4))
        # The line at the strip's left end (what the work under way is doing, where the log is), and the buttons.
        # Its last short word kept with the one before it, as every line that wraps (widgets.Wrapped).
        self.note = widgets.Wrapped(self.strip, text="", font=ui.fonts.small, fg=theme.MUTED, bg=theme.STRIP,
                                    anchor="w", justify="left")
        # Its room ends the strip's gap before the buttons, however long its words.
        self.note.pack(side="left", fill="x", expand=True, padx=(0, px(16)))
        self.button_row = tk.Frame(self.strip, bg=theme.STRIP)
        self.button_row.pack(side="right")
        # ---- the header along the page's top: the page's title, and the window's minimise and close at its right.
        self.header = Header(right, ui, px(PAGE_LIGHT), self.words, lambda: frameless.minimize(self.root),
                             self.on_close)
        self.header.pack(side="top", fill="x")
        # The page under it, its picture going on from the header's without a seam.
        self.page_area = PageArea(right, ui, offset=self.header.tall, light=px(PAGE_LIGHT),
                                  on_moved=self.header.moved)
        self.page_area.pack(side="top", fill="both", expand=True)
        # The header's picture is the page's first rows: its shards in the same room right of the page's column, and both
        # keep clear of the header's window buttons (the same shards left out of both, never one cut at their seam).
        self.header.room = self.page_area.shard_room
        self.page_area.keep = self.header.button_boxes
        # Tab goes as the window reads its work: the page, the strip's buttons, then the window's own minimise and close
        # (Tk follows the order of making: the strip, made first so that it holds the foot, and the header, made before
        # the page so that it holds the top, are raised after the page in that order).
        tk.Misc.tkraise(strip)
        tk.Misc.tkraise(self.header)
        # The window's top moves the window, as Windows' title bar did: the header (its title and its picture; its
        # buttons are widgets of their own) and the column as far down as the header reaches, its wordmark with it.
        self.mover.bind(self.header)
        for widget in (column, mark):
            self.mover.bind(widget, lambda e: e.y_root - self.root.winfo_rooty() < self.header.tall)
        # The page's buttons (the coming page's while one is made), the ones in the strip now, and what Esc does there.
        self.buttons, self.shown_buttons = [], []
        self.escape = None
        # The page being made off the screen, with what it shows once it takes the old one's place (page()), or None.
        self.coming = None

    def _escape(self):
        """Esc: the page's quiet answer (Cancel, Close, Back), when it has one and nothing is under way."""
        if self.escape is not None:
            self.escape()

    # ----------------------------------------------------------------------------------------------- a page

    def page(self, title, lead, steps, step):
        """A new page: its title and the line under it over the field, the column's steps with `step` lit. Returns the
        frame the page's cards go in, made off the screen while the page on show stays whole on it; the strip's buttons
        and note start empty for it, and what the caller gives it then (set_buttons, say) is kept for it too. Once the
        caller has made it, show_page() puts it in the old one's place whole, with its title, line, steps, buttons and
        note: never the old page taken apart on the screen while the next is made, as the launcher's pages."""
        if self.coming is not None:
            # A page begun before this one and not shown (its caller turned to this one instead) goes unseen.
            self._drop_coming()
        content = self.page_area.new_page()
        self.coming = {"content": content, "title": title, "lead": lead, "steps": (list(steps), step),
                       "buttons": [], "escape": None, "note": ("", theme.MUTED)}
        self.buttons = []
        # At the latest once the window has nothing more to do, should its caller not show it: never a page left made
        # and unseen. The caller shows it itself, in its own turn, so that the page before and its buttons are gone
        # before anything else can reach them (Tk takes a second click waiting in its queue before its idle work).
        self.root.after_idle(self.show_page)
        return content

    def _drop_coming(self):
        """The page being made goes without having shown, its buttons with it."""
        coming, self.coming = self.coming, None
        for button in coming["buttons"]:
            button.destroy()
        coming["content"].destroy()

    def show_page(self):
        """The page made off the screen (page()) takes the place of the one on show, whole: the title in the header,
        the line under it at the page's top, where the title's foot is, the column's steps, the page (the old one leaves
        the screen whole before its widgets go, widgets.ScrollArea.show_page), the strip's buttons and its note. All of
        it is drawn once the turn is over, together."""
        coming, self.coming = self.coming, None
        if coming is None:
            # Shown already (page()'s own late look, after its caller showed it).
            return
        self.header.set_title(coming["title"])
        self.page_area.set_heading("", coming["lead"])
        self.steps.show(*coming["steps"])
        self.page_area.show_page(coming["content"])
        self._put_buttons(coming["buttons"])
        self.escape = coming["escape"]
        self._say(*coming["note"])

    def card(self, parent, title=None, last=True, foot=False):
        """A card on the page, as the launcher's: its title, the cut corner, the site's room inside; `foot`: its foot's
        corner cut too, a result's panel as the launcher's last game (what came of the work)."""
        card = widgets.Card(parent, self.ui, title, foot=foot)
        card.pack(fill="x", pady=(0, 0 if last else self.ui.px(16)))
        return card

    def set_buttons(self, buttons, default=None, escape=None):
        """The strip's buttons from the left: [(words, command, kind)], kind "primary" (lime), "remove" (filled red: the
        main button when it removes for good), "danger" (quiet red) or "secondary" (quiet); the one at `default` takes
        the keyboard (Enter presses it); `escape` is what Esc does. For a page being made (page()), they come with it,
        and the page on show keeps its own until then."""
        made = [widgets.Button(self.button_row, self.ui, words, command, kind=kind) for words, command, kind in buttons]
        if self.coming is not None:
            # Given again while the page is made: the ones given first go unseen.
            for button in self.coming["buttons"]:
                button.destroy()
            self.coming.update(buttons=made, escape=escape)
        else:
            self._put_buttons(made)
            self.escape = escape
        self.buttons = made
        if default is not None and 0 <= default < len(made):
            # After the window is drawn, so that the keyboard lands there and not on the page before it.
            self.focus_later(made[default])
        return made

    def _put_buttons(self, buttons):
        """`buttons` (made in the strip's row) in the strip, in place of the ones there."""
        for button in self.shown_buttons:
            button.destroy()
        px = self.ui.px
        for i, button in enumerate(buttons):
            # The buttons' gap, as on the launcher's pages and dialogs (8, the spacing scale's).
            button.pack(side="left", padx=(px(8) if i else 0, 0))
        self.shown_buttons = list(buttons)

    def say(self, text, colour=theme.MUTED):
        """The line at the strip's left end; for a page being made (page()), said as the page shows."""
        if self.coming is not None:
            self.coming["note"] = (text, colour)
            return
        self._say(text, colour)

    def _say(self, text, colour):
        # Wrapped to what the buttons leave of the strip, so that a long path breaks instead of pushing them off.
        room = max(self.ui.px(120), self.strip.winfo_width() - self.button_row.winfo_reqwidth() - self.ui.px(16))
        self.note.configure(text=text, fg=colour, wraplength=room)

    def notice(self, card):
        """The project's notice at the foot of a page's card, under a divider from what the card holds, its two lines as
        the site's footers and the launcher's About card have them (no words lie on the page's field outside a card)."""
        # The faint line between it and the rows above, as the About card has between its licence and the notice.
        widgets.divider(card, self.ui, pady=12)
        for i, key in enumerate(("about.notice", "about.notice.2")):
            # A line's gap under the first.
            widgets.label(card, self.ui, self.words(key), font=self.ui.fonts.small, fg=theme.MUTED,
                          wrap_margin=0).pack(fill="x", pady=(self.ui.px(4) if i else 0, 0))

    def lines(self, parent, rows):
        """What came of the work, a line each, as the launcher's ready check says a state: [(state, words)], state "ok"
        (a lime dot), "change" (a yellow ring), "bad" (a red dot), or None for a plain line in ash (where a log is)."""
        for i, (state, words) in enumerate(rows):
            # One line under another with the card's gap between rows (LINE_GAP), on the launcher's spacing scale.
            gap = (self.ui.px(LINE_GAP) if i else 0, 0)
            if state is None:
                widgets.label(parent, self.ui, words, font=self.ui.fonts.small, fg=theme.MUTED,
                              wrap_margin=0).pack(fill="x", pady=gap)
            else:
                widgets.check_line(parent, self.ui, state, words).pack(fill="x", pady=gap)

    def run(self):
        self.root.mainloop()


class PageArea(widgets.ScrollArea):
    """The page under the header: the header holds the page's title, so the line under the title starts at the area's
    top, where the title's foot is, as it did under the title on the launcher's pages. Its shards keep clear of the
    header's window buttons as the header's do (`keep`: the header's button_boxes, set once both are made)."""

    TOP = 0
    # The header's button_boxes, set by the window once the header and the page are made.
    keep = None

    def shard_keep(self):
        # The header's buttons as boxes at the page's width (the header is as wide as the page under it).
        return self.keep(max(1, self.canvas.winfo_width())) if self.keep is not None else ()


class Header(tk.Canvas):
    """The page's top: its title as the launcher's pages set theirs (its capitals level with the wordmark's top, on one
    baseline in both languages, a little smaller only where the window is too narrow for it beside the buttons), and the
    window's own minimise and close at its right. At the page's top it shows the page's own picture (the light and the shards, which the page under
    it goes on with); once the page has moved from its top, the strip's solid colour with a seam along its foot, as the
    site's bar does then, so that the cards go under an edge and not into the picture."""

    def __init__(self, parent, ui, light, words, on_minimize, on_close):
        px = ui.px
        # A title in Latin letters, the tallest: the header's height round it, whatever the page and the language, and
        # the baseline every title stands on.
        latin, self.baseline = art.page_title("H", ui.scale)
        self.tall = px(TITLE_TOP) + latin.height + px(TITLE_FOOT)
        super().__init__(parent, height=self.tall, bg=theme.BG, highlightthickness=0, bd=0, takefocus=0)
        self.ui, self.light = ui, light
        # Where the page's shards stand (widgets.ScrollArea.shard_room of the page under it), set once the page is made.
        self.room = None
        # The page's title, whether the page has moved from its top, and the title's picture drawn for a room.
        self.title, self.moved_off, self._titles = "", False, {}
        # Where the title is on the header (for the tests' measures).
        self.title_box = None
        self.buttons = [WindowButton(self, ui, "minimize", on_minimize, words("setup.window.minimize")),
                        WindowButton(self, ui, "close", on_close, words("setup.window.close"))]
        self.bind("<Configure>", lambda e: self._draw())

    def set_title(self, title):
        """Another page's title."""
        if title != self.title:
            self.title = title
            self._draw()

    def moved(self, on):
        """The page has moved from its top (True) or come back to it."""
        if on != self.moved_off:
            self.moved_off = on
            self._draw()

    def places(self, width):
        """Where the buttons go on a header `width` wide: their (x, y), the close button last, at the right end."""
        px = self.ui.px
        size, gap, right = px(BUTTON), px(BUTTON_GAP), width - px(BUTTON_RIGHT)
        return [(right - 2 * size - gap, px(BUTTON_TOP)), (right - size, px(BUTTON_TOP))]

    def button_boxes(self, width):
        """The window buttons on a header `width` wide as boxes on the page (the header is its first rows), each with the
        room a shard keeps from a card round it (widgets.ScrollArea.SHARD_CLEAR): no shard reaches them (art.shard_mask),
        where the big one ran through the close button's cut corner and a slim one pointed at its foot."""
        px = self.ui.px
        size, clear = px(BUTTON), px(widgets.ScrollArea.SHARD_CLEAR)
        return [(x - clear, y - clear, x + size + clear, y + size + clear) for x, y in self.places(width)]

    def _title_picture(self, room):
        """The title's picture and its baseline, at the site's size, or smaller until it fits `room` pixels."""
        key = (self.title, room)
        if key not in self._titles:
            size = 42
            picture, base = art.page_title(self.title, self.ui.scale, size=size)
            while picture.width > room and size > TITLE_LEAST:
                # As much smaller as the room asks, a step at least, never under the least size.
                size = max(TITLE_LEAST, min(size - 1, int(size * room / float(picture.width))))
                picture, base = art.page_title(self.title, self.ui.scale, size=size)
            # One title's pictures kept at a time: the window shows one page.
            self._titles = {key: (picture, base)}
        return self._titles[key]

    def _draw(self):
        px = self.ui.px
        width, height = max(1, self.winfo_width()), self.tall
        if self.moved_off:
            # The strip's colour and its seam along the foot, as the strip along the window's foot has along its top.
            picture = Image.new("RGB", (width, height), art._rgb(theme.STRIP))
            seam = max(1, px(1))
            ImageDraw.Draw(picture).rectangle([0, height - seam, width - 1, height - 1], fill=art._rgb(theme.SEAM))
        else:
            # The page's own picture, its first rows: the page area under it draws the rest (its offset), its shards
            # in the same room.
            picture = art.backdrop(width, height, self.ui.scale, offset=0, top=self.light,
                                   room=self.room() if self.room is not None else None, keep=self.button_boxes(width))
        places = self.places(width)
        self.title_box = self.title_picture = None
        if self.title:
            # Where the launcher's pages put their title (ScrollArea.set_heading), as large as the room before the
            # buttons leaves it, standing on the Latin title's baseline.
            x = px(widgets.ScrollArea.MARGIN) - px(2)
            title, base = self._title_picture(places[0][0] - px(TITLE_ROOM) - x)
            y = px(TITLE_TOP) + self.baseline - base
            picture.paste(title, (x, y), title)
            self.title_box, self.title_picture = (x, y, x + title.width, y + title.height), title
        # Kept for the buttons' faces and for a dialog, which draws the window from its widgets (snapshot.py).
        self.picture = self.odq_picture = picture
        self._image = ImageTk.PhotoImage(picture, master=self)
        self.delete("all")
        self.create_image(0, 0, image=self._image, anchor="nw")
        size = px(BUTTON)
        for button, (x, y) in zip(self.buttons, places):
            button.place(x=x, y=y)
            # Each button over the header's own pixels: its cut corners show them.
            button.set_under(picture.crop((x, y, x + size, y + size)))


class WindowButton(tk.Canvas):
    """One of the window's own buttons in the header, minimise or close (art.window_button): quiet metal, the close button
    red under the pointer; pressed by a click that ends on it, or by Enter or Space once Tab has reached it (its ring
    shows). `words` name it for the tests and, on Windows, for screen readers (frameless.name in SetupWindow.show)."""

    def __init__(self, parent, ui, glyph, command, words):
        size = ui.px(BUTTON)
        super().__init__(parent, width=size, height=size, bg=theme.BG, highlightthickness=0, bd=0, cursor="hand2",
                         takefocus=1)
        self.ui, self.glyph, self.command, self.words = ui, glyph, command, words
        # Its look now: under the pointer or pressed or neither, and whether the keyboard is on it; whether it can be
        # pressed (the close button cannot while the installer works: enable()).
        self.state, self.focused, self.enabled = "normal", False, True
        # The header's pixels it lies on, and its faces drawn over them.
        self.under, self._faces, self._item = None, {}, None
        # The spacing checks measure it as the button it is (tests/ui/spacing.py).
        self.odq_button = True
        self.bind("<Enter>", lambda e: self._paint("hover"))
        self.bind("<Leave>", lambda e: self._paint("normal"))
        self.bind("<ButtonPress-1>", lambda e: self._paint("pressed"))
        self.bind("<ButtonRelease-1>", self._release)
        # The keyboard: Tab brings its ring, Enter or Space press it.
        self.bind("<FocusIn>", lambda e: self._focus(True))
        self.bind("<FocusOut>", lambda e: self._focus(False))
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            self.bind(key, lambda e: self.press())

    def set_under(self, picture):
        """The header's pixels under the button: its faces drawn again over them."""
        self.under, self._faces = picture, {}
        self._paint(self.state)

    def enable(self, on):
        """Pressable, or not: dimmed (flat metal, the faintest glyph, no red under the pointer, the arrow for a pointer,
        Tab past it) while the installer works, as the window cannot close then. A click or a key on it still goes to
        the window's close, which says why it stays (Installer._close)."""
        self.enabled = bool(on)
        self.configure(cursor="hand2" if self.enabled else "arrow", takefocus=1 if self.enabled else 0)
        self._paint("normal")

    def face(self, state, focused):
        """The button's picture in a state, with the keyboard's ring or without."""
        key = (state, focused)
        if key not in self._faces:
            self._faces[key] = art.window_button(self.ui.px(BUTTON), self.glyph, state, focused, self.ui.scale,
                                                 under=self.under)
        return self._faces[key]

    def _paint(self, state):
        self.state = state
        # Dimmed, it keeps its one look whatever the pointer does.
        picture = self.face(state if self.enabled else "disabled", self.focused and self.enabled)
        self._image = ImageTk.PhotoImage(picture, master=self)
        if self._item is None:
            self._item = self.create_image(0, 0, image=self._image, anchor="nw")
        else:
            self.itemconfigure(self._item, image=self._image)
        # A dialog draws the window from its widgets (snapshot.py): the button as it looks now.
        self.odq_picture = picture

    def _focus(self, on):
        self.focused = on
        self._paint(self.state)

    def _release(self, event):
        # Only a release over the button counts, as with the window's other buttons (drag off to change your mind).
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        if not inside:
            self._paint("normal")
            return
        # Drawn first, as the window may go: minimise takes it from under the pointer, and it comes back at rest; a close
        # refused while work is under way leaves it under the pointer still.
        self._paint("normal" if self.glyph == "minimize" else "hover")
        self.command()

    def press(self):
        """What a click does, for the keyboard and the tests."""
        self.command()


class Steps(tk.Canvas):
    """The column's steps of what the installer does (READY, INSTALL, DONE), one under another, as the launcher's guide
    sets its steps: each number large and leaning with its name beside it; the step on show on a raised slab, its
    number lime and its name white (no stripe along the slab: the launcher's menu has none, the slab and the lime
    number say it); the steps taken with their numbers lime; the ones to come grey."""

    # A step's height and the gap between two, the room before its number, the number's column and the slab's cut
    # corner (logical pixels).
    STEP_H, GAP, PAD, NUMBER_W, CUT = 46, 4, 14, 32, 10

    def __init__(self, parent, ui):
        super().__init__(parent, height=1, bg=theme.STRIP, highlightthickness=0, bd=0, takefocus=0)
        self.ui = ui
        self.names, self.index = [], 0
        self.bind("<Configure>", lambda e: self._draw())

    def show(self, names, index):
        """These steps, the one at `index` on show."""
        px = self.ui.px
        self.names, self.index = list(names), index
        height = len(self.names) * px(self.STEP_H) + max(0, len(self.names) - 1) * px(self.GAP)
        self.configure(height=max(1, height))
        self._draw()

    def _draw(self):
        from PIL import Image, ImageDraw
        px = self.ui.px
        width, height = max(1, self.winfo_width()), max(1, int(self.cget("height")))
        self.delete("all")
        picture = Image.new("RGB", (width, height), art._rgb(theme.STRIP))
        draw = ImageDraw.Draw(picture)
        left, right = px(EDGE) - px(6), width - px(EDGE) + px(6) - max(1, px(1))
        texts = []
        for i, name in enumerate(self.names):
            top = i * (px(self.STEP_H) + px(self.GAP))
            bottom = top + px(self.STEP_H)
            done, now = i < self.index, i == self.index
            if now:
                # The slab under the step on show, its top-right corner cut as the cards' are, its lime rule.
                cut = px(self.CUT)
                draw.polygon([(left, top), (right - cut, top), (right - 1, top + cut), (right - 1, bottom - 1),
                              (left, bottom - 1)], fill=art._rgb(theme.PANEL))
            colour = theme.OK if (done or now) else theme.STEP_TO_COME
            numeral = art.numeral(str(i + 1), colour, self.ui.scale, size=24, bg=None)
            nx, ny = left + px(self.PAD), (top + bottom - numeral.height) // 2
            picture.paste(numeral, (nx, ny), numeral)
            texts.append((nx + px(self.NUMBER_W), (top + bottom) // 2, name,
                          theme.TEXT if now else (theme.MUTED if done else theme.FAINT)))
        self._picture = picture
        self._image = ImageTk.PhotoImage(picture, master=self)
        # A dialog would draw the window from its widgets: the column's steps as they look now.
        self.odq_picture = picture
        self.create_image(0, 0, image=self._image, anchor="nw")
        for x, y, name, colour in texts:
            # The names in the launcher's wide face, English in both languages as its menu's.
            self.create_text(x, y, text=name, anchor="w", font=self.ui.fonts.step, fill=colour)


class Options(tk.Frame):
    """A list of choices of which one is chosen, on a card: each a row with its name and a line under it, a ring before
    it, the chosen one on a raised slab with its ring lit (a lime dot: no stripe along it, as the launcher's lists have
    none). A click chooses a row; the keyboard reaches
    the list with Tab (a cyan ring round it), the arrow keys move the choice, Enter does what the page's main button
    does (`on_enter`). `options` are [(value, name, line)]; on_change(value) runs on each new choice."""

    RULE, PAD = 3, 14

    def __init__(self, parent, ui, options, value, on_change, on_enter):
        bg = parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.on_change, self.on_enter = ui, on_change, on_enter
        self.values = [option[0] for option in options]
        self.value = value if value in self.values else self.values[0]
        px = ui.px
        # Its own lamps: a lime dot for the choice, a grey ring for the others.
        self._lamps = {on: ImageTk.PhotoImage(art.lamp(theme.OK if on else theme.FAINT, ui.scale, bg=theme.PANEL_HI if on
                                                       else theme.PANEL, hollow=not on, lead=False), master=self)
                       for on in (True, False)}
        self.rows = {}
        for i, (key, name, line) in enumerate(options):
            row = tk.Frame(self, bg=theme.PANEL, cursor="hand2")
            row.pack(fill="x", pady=(px(6) if i else 0, 0))
            rule = tk.Frame(row, bg=theme.PANEL, width=px(self.RULE))
            rule.pack(side="left", fill="y")
            lamp = tk.Label(row, image=self._lamps[False], bg=theme.PANEL, bd=0)
            # On the middle of the choice's name, the first line of the words beside it (their room above, then half
            # the name's line), as a ready-check row's lamp stands on its words.
            middle = px(10) + ui.fonts.body_bold.metrics("linespace") / 2.0
            lamp.pack(side="left", anchor="n", padx=(px(self.PAD), px(10)),
                      pady=(max(0, int(round(middle - lamp.winfo_reqheight() / 2.0))), 0))
            words = tk.Frame(row, bg=theme.PANEL)
            words.pack(side="left", fill="x", expand=True, pady=px(10), padx=(0, px(self.PAD)))
            title = tk.Label(words, text=name, font=ui.fonts.body_bold, fg=theme.TEXT, bg=theme.PANEL, anchor="w")
            title.pack(fill="x")
            said = widgets.label(words, ui, line, font=ui.fonts.small, fg=theme.MUTED, bg=theme.PANEL, wrap_margin=0)
            said.pack(fill="x", pady=(px(2), 0))
            self.rows[key] = {"row": row, "rule": rule, "lamp": lamp, "words": words, "title": title, "line": said}
            for widget in (row, lamp, words, title, said):
                widget.bind("<Button-1>", lambda e, k=key: self.choose(k))
        # Tab reaches the list; the arrow keys move the choice; Enter does the page's main thing.
        widgets.focus_ring(self, ui, bg)
        self.bind("<Up>", lambda e: self._step(-1))
        self.bind("<Down>", lambda e: self._step(1))
        self.bind("<Return>", lambda e: self.on_enter())
        self.bind("<KP_Enter>", lambda e: self.on_enter())
        self._paint()

    def _paint(self):
        """Each row's look: the chosen one raised with its rule, the others flat."""
        for key, parts in self.rows.items():
            on = key == self.value
            fill = theme.PANEL_HI if on else theme.PANEL
            for name in ("row", "words", "title", "line"):
                parts[name].configure(bg=fill)
            parts["lamp"].configure(bg=fill, image=self._lamps[on])
            # The rule's room keeps the rows' words where they were; it shows the row's own colour.
            parts["rule"].configure(bg=fill)

    def choose(self, value):
        """Choose a row (a click, an arrow key), and say so."""
        if value in self.values and value != self.value:
            self.value = value
            self._paint()
            self.on_change(value)
        # A click puts the keyboard on the list too, so that the arrow keys go on from there.
        self.focus_set()

    def _step(self, by):
        """The choice before or after this one (no wrap at either end)."""
        i = self.values.index(self.value) + by
        if 0 <= i < len(self.values):
            self.choose(self.values[i])
        return "break"

    def set_line(self, value, text):
        """Another line under a row (a size counted after the page showed)."""
        if value in self.rows:
            self.rows[value]["line"].configure(text=text)


class Progress(tk.Frame):
    """The work under way: a bar that fills as the work does, its share in figures at its right, and the work's steps
    under it, each with a lamp: done a lime dot, under way a lime ring, to come a grey ring. set(fraction, step) moves
    it; the bar eases toward the fraction it is given, a little at a time, so that it moves as the work does and never
    jumps back."""

    def __init__(self, parent, ui, steps):
        bg = parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.bg = ui, bg
        px = ui.px
        self.shown, self.target, self.step = 0.0, 0.0, 0
        top = tk.Frame(self, bg=bg)
        top.pack(fill="x")
        self.figure = tk.Label(top, text="0%", font=ui.fonts.body_bold, fg=theme.TEXT, bg=bg, width=5, anchor="e")
        self.figure.pack(side="right")
        self.bar = tk.Label(top, bg=bg, bd=0)
        self.bar.pack(side="left", fill="x", expand=True, padx=(0, px(12)))
        self.bar.bind("<Configure>", lambda e: self._draw_bar())
        # The steps under the bar, the card's gap between them (on the launcher's spacing scale).
        tk.Frame(self, bg=bg, height=px(16)).pack(fill="x")
        self._lamps = {state: ImageTk.PhotoImage(art.lamp(colour, ui.scale, bg=bg, hollow=hollow, lead=False),
                                                 master=self)
                       for state, colour, hollow in (("done", theme.OK, False), ("now", theme.OK, True),
                                                     ("later", theme.FAINT, True))}
        self.rows = []
        for i, name in enumerate(steps):
            row = tk.Frame(self, bg=bg)
            row.pack(fill="x", pady=(px(8) if i else 0, 0))
            lamp = tk.Label(row, image=self._lamps["later"], bg=bg, bd=0)
            lamp.pack(side="left")
            words = tk.Label(row, text=name, font=ui.fonts.body, fg=theme.FAINT, bg=bg, anchor="w")
            words.pack(side="left", padx=(px(8), 0))
            self.rows.append((lamp, words))
        self._paint_steps()
        self._job = self.after(30, self._tick)
        # Its easing stops with it: a timer left behind would call a bar that is gone.
        self.bind("<Destroy>", lambda e: e.widget is self and self._job is not None and self.after_cancel(self._job))

    def set(self, fraction, step):
        """Where the work is: its share done (0 to 1) and the step under way (an index of the steps)."""
        # Never back: a step that measures afresh (a folder emptied before it fills) does not move the bar back.
        self.target = max(self.target, min(1.0, max(0.0, fraction)))
        if step != self.step:
            self.step = step
            self._paint_steps()

    def _tick(self):
        """One frame of the bar's easing toward its target (30 ms)."""
        self._job = None
        if not self.winfo_exists():
            return
        gap = self.target - self.shown
        if gap > 0.0005:
            # A share of what is left each frame, at least a little: quick at first, gentle at the end.
            self.shown = min(self.target, self.shown + max(0.004, gap * 0.18))
            self._draw_bar()
        self._job = self.after(30, self._tick)

    def _draw_bar(self):
        width = self.bar.winfo_width()
        if width <= 1:
            return
        px = self.ui.px
        picture = art.bar(width, px(8), self.shown, theme.OK)
        self._image = ImageTk.PhotoImage(picture, master=self)
        self.bar.configure(image=self._image, height=px(8))
        # A dialog would draw the window from its widgets: the bar as it looks now.
        self.bar.odq_picture = picture
        self.figure.configure(text="%d%%" % int(round(self.shown * 100)))

    def _paint_steps(self):
        for i, (lamp, words) in enumerate(self.rows):
            state = "done" if i < self.step else ("now" if i == self.step else "later")
            lamp.configure(image=self._lamps[state])
            words.configure(fg=theme.TEXT if state == "now" else (theme.MUTED if state == "done" else theme.FAINT))

    def finish(self):
        """All done: every step lit and the bar full."""
        self.target, self.step = 1.0, len(self.rows)
        self._paint_steps()
