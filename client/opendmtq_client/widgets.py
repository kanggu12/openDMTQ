"""The launcher's building blocks, drawn to match its theme instead of the Windows defaults.

Tk's stock widgets look like 1990s Windows on a dark background, so the controls here are Labels and Canvases
with images from art.py. Each keeps its own images alive (Tk drops an image the moment Python forgets it).
"""

import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from opendmtq_client import art, theme


class Ui:
    """What every widget needs to draw itself: the root, the fonts, the DPI scale, the words, and the section the
    page on show belongs to (its colour lights the page's main buttons, switches and links)."""

    def __init__(self, root, fonts, scale, words):
        self.root = root
        self.fonts = fonts
        self.scale = scale
        self.words = words
        self.section_name = "home"
        self.section = theme.SECTION_COLOURS["home"]

    def px(self, n):
        """Logical pixels (at 100 % scaling) to real pixels on this screen."""
        return int(round(n * self.scale))

    def use_section(self, page):
        """Widgets made from now on take the colour of `page`'s section."""
        self.section_name = theme.PAGE_SECTIONS.get(page, "home")
        self.section = theme.SECTION_COLOURS[self.section_name]


def style_ttk(ui):
    """Dark styles for the few ttk widgets used (the drop-down list and the scroll bar)."""
    s = ttk.Style(ui.root)
    # 'clam' is the built-in theme that honours colours on every platform.
    s.theme_use("clam")
    s.configure("Dark.TCombobox", fieldbackground=theme.FIELD, background=theme.PANEL_HI, foreground=theme.TEXT,
                arrowcolor=theme.TEXT, bordercolor=theme.LINE, lightcolor=theme.LINE, darkcolor=theme.LINE,
                selectbackground=theme.FIELD, selectforeground=theme.TEXT, padding=ui.px(6))
    s.map("Dark.TCombobox", fieldbackground=[("readonly", theme.FIELD)], foreground=[("readonly", theme.TEXT)],
          bordercolor=[("focus", theme.CYAN)], arrowcolor=[("disabled", theme.FAINT)])
    # The list that drops down is a plain Tk listbox; its colours come from the option database.
    ui.root.option_add("*TCombobox*Listbox.background", theme.FIELD)
    ui.root.option_add("*TCombobox*Listbox.foreground", theme.TEXT)
    ui.root.option_add("*TCombobox*Listbox.selectBackground", theme.RAIL_UP)
    ui.root.option_add("*TCombobox*Listbox.selectForeground", theme.TEXT)
    ui.root.option_add("*TCombobox*Listbox.font", ui.fonts.body)
    quiet_combobox_wheel(ui.root)
    s.configure("Dark.Vertical.TScrollbar", background=theme.RAIL, troughcolor=theme.BG, bordercolor=theme.BG,
                lightcolor=theme.RAIL, darkcolor=theme.RAIL, arrowcolor=theme.MUTED, gripcount=0,
                arrowsize=ui.px(12))
    s.map("Dark.Vertical.TScrollbar", background=[("active", theme.RAIL_UP)])


# The wheel's events, as Windows (MouseWheel) and X11 (buttons 4 and 5) send them.
WHEEL = ("<MouseWheel>", "<Shift-MouseWheel>", "<Button-4>", "<Button-5>")


def quiet_combobox_wheel(root):
    """The wheel scrolls the page and never a drop-down's value. Tk's own bindings for every drop-down step its value
    under the pointer and say it was chosen, so scrolling a page past a setting would change that setting unseen; the
    page's own scrolling (ScrollArea, bound for all widgets) stays."""
    for sequence in WHEEL:
        root.unbind_class("TCombobox", sequence)


class ScrollArea(tk.Frame):
    """A frame whose content scrolls with the mouse wheel; `inner` is where the page goes."""

    def __init__(self, parent, ui, bg=theme.BG):
        super().__init__(parent, bg=bg)
        self.ui = ui
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Dark.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        # The part of the wheel's turning that has not made a whole step yet (a touchpad sends it a little at a time).
        self._wheel_rest = 0.0
        self.canvas.configure(yscrollcommand=self._bar_set)
        # The bar's room is kept when there is no bar, by a plain strip as wide as it: the page then has one width
        # whether it scrolls or not. Without it, a page about as tall as the area loops for ever: the bar narrows the
        # page, the narrower page fits, the bar goes, the wider page no longer fits, the bar comes back.
        self.spacer = tk.Frame(self, bg=bg, width=self.bar.winfo_reqwidth())
        self.spacer.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        # The content's height decides how far it scrolls.
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        # The content is always as wide as the visible area, so text wraps instead of running off.
        self.canvas.bind("<Configure>", self._on_resize)
        # The wheel scrolls whatever is under the pointer, so bind only while the pointer is over this area.
        self.bind("<Enter>", lambda e: self._wheel(True))
        self.bind("<Leave>", lambda e: self._wheel(False))

    def _bar_set(self, first, last):
        """Show the scroll bar only when the content is taller than the area, in the room the strip keeps for it."""
        # The strip as wide as the bar, so swapping one for the other never moves the page.
        self.spacer.configure(width=self.bar.winfo_reqwidth())
        if float(first) <= 0.0 and float(last) >= 1.0:
            if self.bar.winfo_manager():
                self.spacer.pack(side="right", fill="y", before=self.canvas)
                self.bar.pack_forget()
        elif not self.bar.winfo_manager():
            self.bar.pack(side="right", fill="y", before=self.canvas)
            self.spacer.pack_forget()
        self.bar.set(first, last)

    def _on_resize(self, event):
        # The content is exactly as wide as the visible area; labels wrap to their own box (follow_width).
        self.canvas.itemconfigure(self._window, width=event.width)

    def _wheel(self, on):
        if on:
            self.bind_all("<MouseWheel>", self._on_wheel)          # Windows and macOS
            self.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))   # X11 wheel up
            self.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))    # X11 wheel down
        else:
            self.unbind_all("<MouseWheel>")
            self.unbind_all("<Button-4>")
            self.unbind_all("<Button-5>")

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


def link(parent, ui, text, command, fg=None, bg=theme.BG, font=None, chevron=True):
    """Words that do something: a click, or Enter or Space once Tab has reached them (a cyan ring shows it). In the
    page's colour with a chevron after them by default."""
    words = tk.Label(parent, text=text + ("  " + theme.ICON["chevron"] if chevron else ""),
                     font=font or ui.fonts.body_bold, fg=fg or ui.section["accent"], bg=bg, cursor="hand2")
    focus_ring(words, ui, bg)
    for sequence in ("<Button-1>", "<Return>", "<space>"):
        words.bind(sequence, lambda e: command())
    return words


def label(parent, ui, text, font=None, fg=theme.TEXT, bg=theme.BG, wrap_margin=None, beside=(), **kw):
    """A text label in the theme; with wrap_margin it wraps at its box's width minus that margin."""
    w = tk.Label(parent, text=text, font=font or ui.fonts.body, fg=fg, bg=bg, justify="left", anchor="w", **kw)
    if wrap_margin is not None:
        follow_width(ui, w, wrap_margin, beside)
    return w


def section(parent, ui, text, bg=theme.BG):
    """A section heading: small wide capitals and a thin rule to the right edge."""
    row = tk.Frame(parent, bg=bg)
    words = text.upper() if ui.words.language == "en" else text
    tk.Label(row, text=words, font=ui.fonts.section, fg=theme.MUTED, bg=bg).pack(side="left")
    rule = tk.Frame(row, bg=theme.LINE, height=max(1, ui.px(1)))
    rule.pack(side="left", fill="x", expand=True, padx=(ui.px(12), 0), pady=(ui.px(2), 0))
    return row


class Button(tk.Canvas):
    """A button cut at two corners like PLAY. kind: 'primary' (filled with the section's colour, the page's main
    action), 'secondary' (quiet metal that lights up under the pointer), 'danger' (metal tinted red, filled red
    under the pointer: removing or starting over).

    The face is a picture (art.button_face); the glyph and the words stay Tk text, so they are drawn as crisply as
    every other label and can use two fonts.
    """

    LOOKS = {"secondary": "neutral", "danger": "danger_quiet"}

    def __init__(self, parent, ui, text, command, kind="secondary", icon=None):
        self.ui, self.icon, self.bg = ui, icon, parent.cget("bg")
        self.look = art.SECTION_LOOKS[ui.section_name] if kind == "primary" else self.LOOKS[kind]
        super().__init__(parent, bg=self.bg, highlightthickness=0, bd=0, cursor="hand2")
        self.command, self.enabled, self.words, self.state = command, True, None, "normal"
        self.focused = False            # the keyboard is on it: its face shows the ring
        colours = art.BUTTON_LOOKS[self.look]
        self.text_colour = {"normal": colours["text"], "hover": colours.get("hover_text", colours["text"]),
                            "pressed": colours.get("hover_text", colours["text"]), "disabled": theme.FAINT}
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

    def set_text(self, text):
        """Show other words (the guide's last Next becomes PLAY): the button takes the width they need."""
        if text == self.words:
            return
        self.words = text
        fonts, px = self.ui.fonts, self.ui.px
        glyph_w = fonts.icon_small.measure(theme.ICON[self.icon]) if self.icon else 0
        left = px(13) if self.icon else px(16)
        width = left + (glyph_w + px(7) if self.icon else 0) + fonts.body_bold.measure(text) + px(16)
        height = px(34)
        self.configure(width=width, height=height)
        self.delete("all")
        # Each state's face, without and with the keyboard's ring (a disabled button never has the keyboard).
        self.faces = {(state, ring): art.button_face((width, height), 0, self.look, state, ring, self.ui.scale,
                                                     bg=self.bg)
                      for state in ("normal", "hover", "pressed", "disabled") for ring in (False, True)
                      if not (ring and state == "disabled")}
        self.images = {key: ImageTk.PhotoImage(face, master=self) for key, face in self.faces.items()}
        self.face = self.create_image(0, 0, image=self.images[("normal", False)], anchor="nw")
        self.parts = []
        x = left
        if self.icon:
            self.parts.append(self.create_text(x, height // 2, text=theme.ICON[self.icon], font=fonts.icon_small,
                                               anchor="w"))
            x += glyph_w + px(7)
        self.parts.append(self.create_text(x, height // 2, text=text, font=fonts.body_bold, anchor="w"))
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


class Toggle(tk.Label):
    """An on/off switch; command(new_value) runs after each click."""

    def __init__(self, parent, ui, value, command, bg=theme.BG):
        super().__init__(parent, bg=bg, cursor="hand2", bd=0)
        self.ui, self.value, self.command = ui, bool(value), command
        size = (ui.px(42), ui.px(23))
        # Both pictures are made once; a click only swaps them.
        colour = ui.section["fill"]
        self.pictures = {True: art.toggle(True, *size, colour=colour, knob=ui.section["ink"]),
                         False: art.toggle(False, *size)}
        self.images = {on: ImageTk.PhotoImage(p, master=parent) for on, p in self.pictures.items()}
        self.configure(image=self.images[self.value])
        # A dialog draws the window behind it from the widgets (snapshot.py): this is the switch's part.
        self.odq_picture = self.pictures[self.value]
        self.bind("<Button-1>", lambda e: self.set(not self.value, notify=True))
        # Tab reaches it; Enter or Space switches it.
        focus_ring(self, ui, bg)
        self.bind("<Return>", lambda e: self.set(not self.value, notify=True))
        self.bind("<space>", lambda e: self.set(not self.value, notify=True))

    def set(self, value, notify=False):
        self.value = bool(value)
        self.configure(image=self.images[self.value])
        self.odq_picture = self.pictures[self.value]
        if notify:
            self.command(self.value)


class Segmented(tk.Frame):
    """A row of choices of which one is on, like the site's tabs."""

    def __init__(self, parent, ui, options, value, command, bg=theme.BG):
        super().__init__(parent, bg=theme.LINE, padx=1, pady=1)
        self.ui, self.command, self.labels, self.value = ui, command, {}, value
        self.keys = [key for key, _ in options]
        # Tab reaches the row; the arrow keys move the choice.
        focus_ring(self, ui, parent.cget("bg"))
        self.bind("<Left>", lambda e: self._step(-1))
        self.bind("<Right>", lambda e: self._step(1))
        for key, text in options:
            lab = tk.Label(self, text=text, font=ui.fonts.body_bold, padx=ui.px(16), pady=ui.px(6), cursor="hand2")
            lab.pack(side="left", padx=(0, 1))
            lab.bind("<Button-1>", lambda e, k=key: self.set(k, notify=True))
            self.labels[key] = lab
        self.set(value)

    def set(self, value, notify=False):
        self.value = value
        for key, lab in self.labels.items():
            on = key == value
            lab.configure(bg=self.ui.section["fill"] if on else theme.RAIL,
                          fg=self.ui.section["ink"] if on else theme.MUTED)
        if notify:
            self.command(value)

    def _step(self, by):
        """The choice before or after this one, as the keyboard moves it (no wrap at either end)."""
        i = self.keys.index(self.value) + by if self.value in self.keys else 0
        if 0 <= i < len(self.keys) and self.keys[i] != self.value:
            self.set(self.keys[i], notify=True)


class Slider(tk.Frame):
    """A 0-100 slider with its number beside it; command(value) runs when the drag ends."""

    def __init__(self, parent, ui, value, command, bg=theme.BG, width=320):
        super().__init__(parent, bg=bg)
        self.ui, self.command, self.value = ui, command, int(value)
        self.w, self.h = ui.px(width), ui.px(26)
        self.colour = ui.section["accent"]
        self.knob_img = ImageTk.PhotoImage(art.knob(ui.px(18), ring=self.colour), master=parent)
        self.canvas = tk.Canvas(self, width=self.w, height=self.h, bg=bg, highlightthickness=0, cursor="hand2")
        self.canvas.pack(side="left")
        self.number = tk.Label(self, text="", font=ui.fonts.body_bold, fg=theme.TEXT, bg=bg, width=4, anchor="e")
        self.number.pack(side="left", padx=(ui.px(10), 0))
        self.canvas.bind("<Button-1>", self._drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: self.command(self.value))
        # Tab reaches it; the arrow keys move it by 5 (Home and End to either end), each step saved as a drag's end is.
        focus_ring(self.canvas, ui, bg)
        # A canvas's ring covers its edge: the drawing starts inside it.
        self.inset = int(self.canvas.cget("highlightthickness"))
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
        """Where a value sits on the track (the knob's centre stays inside the canvas, inside its ring)."""
        pad = self.ui.px(10)
        return getattr(self, "inset", 0) + pad + (self.w - 2 * pad) * value / 100.0

    def _drag(self, event):
        pad = self.ui.px(10)
        frac = (event.x - getattr(self, "inset", 0) - pad) / float(max(1, self.w - 2 * pad))
        self.value = int(round(min(1.0, max(0.0, frac)) * 100))
        self._draw()

    def _draw(self):
        c, mid = self.canvas, getattr(self, "inset", 0) + self.h // 2
        c.delete("all")
        thick = max(2, self.ui.px(4))
        # The empty track, then the filled part up to the knob.
        c.create_line(self._x(0), mid, self._x(100), mid, fill=theme.RAIL, width=thick, capstyle="round")
        c.create_line(self._x(0), mid, self._x(self.value), mid, fill=self.colour, width=thick, capstyle="round")
        c.create_image(self._x(self.value), mid, image=self.knob_img)
        self.number.configure(text=str(self.value))


class Select(ttk.Combobox):
    """A drop-down of (value, text) pairs; command(value) runs on a choice."""

    def __init__(self, parent, ui, options, value, command, width=24):
        self.options = list(options)
        super().__init__(parent, values=[t for _, t in self.options], state="readonly", width=width,
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


# The width of a setting's name column, in logical pixels: the longest names of the Screen and Sound pages and a gap.
LABEL_COLUMN = 150


def setting_row(parent, ui, title, control_factory, hint=None, bg=theme.BG):
    """A setting: its name on the left, the control on the right of it, the hint underneath."""
    row = tk.Frame(parent, bg=bg)
    row.columnconfigure(1, weight=1)
    # One width for every row's name, so the controls of a page start on one line (a longer name still fits).
    row.columnconfigure(0, minsize=ui.px(LABEL_COLUMN))
    tk.Label(row, text=title, font=ui.fonts.body_bold, fg=theme.TEXT, bg=bg, anchor="w",
             width=0).grid(row=0, column=0, sticky="w", padx=(0, ui.px(18)))
    control = control_factory(row)
    control.grid(row=0, column=1, sticky="w")
    hint_label = None
    if hint:
        hint_label = label(row, ui, hint, font=ui.fonts.small, fg=theme.MUTED, bg=bg, wrap_margin=4)
        hint_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(ui.px(4), 0))
    row.control, row.hint = control, hint_label
    return row


class Card(tk.Frame):
    """A panel with a 1-pixel seam and its top-right corner cut, like the site's panels; put content into `body`."""

    CUT = 14

    def __init__(self, parent, ui, pad=18):
        outside = parent.cget("bg")
        super().__init__(parent, bg=theme.LINE, padx=1, pady=1)
        self.body = tk.Frame(self, bg=theme.PANEL, padx=ui.px(pad), pady=ui.px(pad - 2))
        self.body.pack(fill="both", expand=True)
        # The cut: a small picture over the frame's square corner, the page's colour beyond the seam.
        cut = ui.px(self.CUT)
        picture = art.corner(cut, theme.PANEL, outside, theme.LINE)
        self._corner = ImageTk.PhotoImage(picture, master=self)
        corner = tk.Label(self, image=self._corner, bd=0, highlightthickness=0, bg=outside)
        corner.odq_picture = picture
        corner.place(relx=1.0, x=-cut, y=0, width=cut, height=cut)


def check_line(parent, ui, state, text, action_text=None, action=None, bg=theme.PANEL):
    """A ready-check line: a coloured glyph (ok, will change, problem), the words, and an optional link."""
    row = tk.Frame(parent, bg=bg)
    glyph, colour = {"ok": ("ok", theme.OK), "change": ("info", theme.WARN), "bad": ("error", theme.BAD)}[state]
    icon = tk.Label(row, text=theme.ICON[glyph], font=ui.fonts.icon_small, fg=colour, bg=bg)
    icon.pack(side="left", anchor="n")
    beside = [icon]
    if action_text and action:
        # The way to fix it, reached by the mouse or the keyboard.
        fix = link(row, ui, action_text, action, bg=bg)
        fix.pack(side="right", anchor="n")
        beside.append(fix)
    words = label(row, ui, text, fg=theme.TEXT if state != "ok" else theme.MUTED, bg=bg, wrap_margin=24,
                  beside=beside)
    words.pack(side="left", fill="x", padx=(ui.px(8), 0))
    return row


def entry(parent, ui, width=18, secret=False):
    """A text field in the theme: dark inside, a cyan edge while typing."""
    field = tk.Entry(parent, width=width, font=ui.fonts.body, bg=theme.FIELD, fg=theme.TEXT, insertbackground=theme.TEXT,
                     relief="flat", highlightthickness=1, highlightbackground=theme.LINE, highlightcolor=theme.CYAN,
                     show="\u2022" if secret else "")
    return field


class Progress(tk.Frame):
    """A progress bar with its words under it (a download): set(fraction, text) moves it; fraction None shows the
    track alone, for work whose size is not known yet."""

    def __init__(self, parent, ui, width=420, bg=theme.BG):
        super().__init__(parent, bg=bg)
        self.ui, self.bg = ui, bg
        self.w, self.h = ui.px(width), ui.px(8)
        self.colour = ui.section["accent"]
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
