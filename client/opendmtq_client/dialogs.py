"""Dialogs drawn inside the launcher's window, as the site's cards.

The launcher asks and tells in a card over its window instead of Windows' message boxes: the window behind is blurred
and dimmed (drawn from its widgets by snapshot.py, so nothing is read from the screen), the card is the site's frosted
gunmetal with its top-right corner cut, the question in Pretendard Bold beside a small lamp, and the site's buttons at
its foot. The lamp and the main button take the colour of what the dialog is about: red to remove something for good,
yellow for a big change, lime to tell. Buttons say what they do. Esc cancels, Enter presses the button with the ring,
Tab and the arrow keys move the ring.

ask() and tell() wait for the answer like a message box. A window of its own (when the launcher cannot open, so
there is no window to draw over) comes from standalone().
"""

import logging
import re
import sys
import tkinter as tk

from PIL import ImageTk

from opendmtq_client import art, safety, snapshot, theme

log = logging.getLogger("opendmtq_client")

# Each kind: the colour of its lamp and of the light along a progress track, and the look of its main button
# (art.BUTTON_LOOKS).
KINDS = {
    "danger": {"accent": theme.BAD, "button": "danger"},
    "warn": {"accent": theme.WARN, "button": "warn"},
    "info": {"accent": theme.OK, "button": "home"},
    "error": {"accent": theme.BAD, "button": "home"},
}

# Sizes in pixels at 100 % scaling.
WIDTH = 480         # the card, when the window has room
MARGIN = 24         # the least room between the card and the window's edge
PAD = 28            # inside the card (the site's 24 px, and a little more for a card on its own)
CUT = 16            # the cut corner
BUTTON = 40         # a button's height
BUTTON_MIN = 110    # a button's least width
GAP = 10            # between two buttons
RISE = 14           # how far the panel rises as it appears
FRAMES = 8          # the rise, one frame every 16 ms


def _motion_on():
    """False when Windows is set to show no animations (Settings > Accessibility > Animation effects)."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        on = ctypes.c_int(1)
        # SPI_GETCLIENTAREAANIMATION
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)
        return bool(on.value)
    except (AttributeError, OSError):
        return True


def path_breaks(font, text, width):
    """`text` with a line break inside each word wider than `width` (a path has no spaces), after one of its folders'
    separators: a path then breaks between its folders, never inside a name that fits on a line."""
    lines = []
    for line in text.split("\n"):
        words = []
        for word in line.split(" "):
            if font.measure(word) <= width:
                words.append(word)
                continue
            # The separator stays at the end of the part before it.
            parts = re.split(r"(?<=[\\/])", word)
            chunks, chunk = [], ""
            for part in parts:
                if chunk and font.measure(chunk + part) > width:
                    chunks.append(chunk)
                    chunk = part
                else:
                    chunk += part
            chunks.append(chunk)
            words.append("\n".join(chunks))
        lines.append(" ".join(words))
    return "\n".join(lines)


class Dialog:
    """One dialog over `root`. buttons: [(words, value, look)]; `default` has the ring at first; `cancel` is the
    value Esc, closing the window or a rebuild of the window give. `window` draws the scene behind for a size
    (the launcher's own window by default)."""

    def __init__(self, root, ui, kind, title, message, detail=None, buttons=(), default=0, cancel=None,
                 window=None, on_close=None, progress=False):
        self.root, self.ui = root, ui
        self.style = KINDS[kind]
        self.title, self.message, self.detail = title, message, detail
        self.buttons = list(buttons)
        self.focus, self.hover, self.pressed = default, None, None
        self.cancel_value, self.result, self.closed = cancel, cancel, False
        self.window = window or (lambda width, height: snapshot.render(self.root))
        self.on_close = on_close
        # A dialog for work under way shows a moving light along a track where the buttons would be.
        self.progress = progress
        self.done = tk.BooleanVar(root, False)
        self.size = None
        self.generation = 0
        self._jobs = set()
        self._resize_job = None
        self._before = root.focus_get()
        self.canvas = tk.Canvas(root, highlightthickness=0, bd=0, bg=theme.BG, takefocus=1)
        # Left out of the window's picture: the dialog never draws itself behind itself.
        self.canvas.odq_skip = True
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        # Above every other widget of the window (a Canvas's own lift() moves its items; tkraise moves it).
        tk.Misc.tkraise(self.canvas)
        self._bind()
        root.update_idletasks()
        self._draw(rise=_motion_on())
        self._take_input()

    # --------------------------------------------------------------------------------------------- drawing

    def _layout(self, width, height):
        """Where everything goes, in the card's own pixels; the text items are made here to measure them."""
        px, fonts, c = self.ui.px, self.ui.fonts, self.canvas
        panel_w = max(px(280), min(px(WIDTH), width - 2 * px(MARGIN)))
        lamp_room = px(18)
        text_w = panel_w - 2 * px(PAD) - lamp_room
        y = px(PAD)
        # The question in Pretendard Bold, after the lamp; what it means under it in ash.
        message = c.create_text(px(PAD) + lamp_room, y, text=path_breaks(fonts.dialog_title, self.message, text_w),
                                font=fonts.dialog_title, fill=theme.TEXT,
                                width=text_w, justify="left", anchor="nw", tags=("card", "words"))
        lamp_y = y + fonts.dialog_title.metrics("linespace") // 2
        y = c.bbox(message)[3]
        detail = None
        if self.detail:
            y += px(8)
            detail = c.create_text(px(PAD) + lamp_room, y, text=path_breaks(fonts.body, self.detail, text_w),
                                   font=fonts.body, fill=theme.MUTED,
                                   width=text_w, justify="left", anchor="nw", tags=("card", "words"))
            y = c.bbox(detail)[3]
        y += px(24)
        if self.progress:
            track = (px(PAD), y + px(3), panel_w - px(PAD), y + px(9))
            y += px(12) + px(PAD) - px(6)
            return {"panel": (panel_w, y), "lamp": (px(PAD) + px(4), lamp_y), "message": message,
                    "detail": detail, "buttons": [], "button_w": 0, "track": track}
        count = len(self.buttons)
        widest = max([fonts.dialog_button.measure(b[0]) for b in self.buttons] or [0])
        button_w = max(px(BUTTON_MIN), widest + px(40))
        room = panel_w - 2 * px(PAD)
        button_w = min(button_w, (room - (count - 1) * px(GAP)) // max(1, count))
        row_w = count * button_w + (count - 1) * px(GAP)
        # At the card's foot on the right, the main one last, as the site's forms end.
        start = panel_w - px(PAD) - row_w
        buttons = [(start + i * (button_w + px(GAP)), y) for i in range(count)]
        y += px(BUTTON) + px(PAD) - px(4)
        return {"panel": (panel_w, y), "lamp": (px(PAD) + px(4), lamp_y), "message": message,
                "detail": detail, "buttons": buttons, "button_w": button_w}

    def _draw(self, rise=False):
        """Draw the whole dialog for the canvas's present size (again after the window is resized)."""
        c, px, scale = self.canvas, self.ui.px, self.ui.scale
        width, height = max(1, self.root.winfo_width()), max(1, self.root.winfo_height())
        self.size = (width, height)
        # A rise still running belongs to the old drawing: it stops moving anything.
        self.generation += 1
        c.delete("all")
        lay = self._layout(width, height)
        panel_w, panel_h = lay["panel"]
        # A little above the middle, where a reader looks first; never off the top.
        x0, y0 = (width - panel_w) // 2, max(px(12), int((height - panel_h) * 0.44))
        behind = self.window(width, height)
        if behind.size != (width, height):
            behind = behind.resize((width, height))
        box = (x0, y0, panel_w, panel_h)
        scene, soft = art.dialog_scene(behind, box, px(CUT), self.style["accent"], scale)
        panel = art.dialog_panel(scene, soft, box, px(CUT), scale)
        # The lamp in the dialog's colour, drawn into the card.
        light = art.lamp(self.style["accent"], scale)
        lx, ly = lay["lamp"]
        panel.paste(light, (lx - light.width // 2, ly - light.height // 2), light)
        self._scene, self._panel = ImageTk.PhotoImage(scene, master=c), ImageTk.PhotoImage(panel, master=c)
        c.create_image(0, 0, image=self._scene, anchor="nw", tags=("scene",))
        c.create_image(0, 0, image=self._panel, anchor="nw", tags=("card", "panel"))
        # The buttons: one picture for each look, drawn over the card's own pixels.
        margin = max(5, int(round(6 * scale)))
        self._images, self._items, self._boxes = [], [], []
        for i, ((words, _value, look), (bx, by)) in enumerate(zip(self.buttons, lay["buttons"])):
            under = panel.crop((bx - margin, by - margin, bx + lay["button_w"] + margin, by + px(BUTTON) + margin))
            images = {(state, ring): ImageTk.PhotoImage(
                art.button_face(under.size, margin, look, state, ring, scale, under=under), master=c)
                for state in ("normal", "hover", "pressed") for ring in (False, True)}
            tag = "button%d" % i
            picture = c.create_image(bx - margin, by - margin, image=images[("normal", False)], anchor="nw",
                                     tags=("card", tag))
            c.create_text(bx + lay["button_w"] // 2, by + px(BUTTON) // 2, text=words,
                          font=self.ui.fonts.dialog_button, fill=art.BUTTON_LOOKS[look]["text"],
                          tags=("card", tag, "words"))
            self._images.append(images)
            self._items.append(picture)
            self._boxes.append((bx, by, bx + lay["button_w"], by + px(BUTTON)))
            for event, handler in (("<Enter>", self._enter), ("<Leave>", self._leave),
                                   ("<ButtonPress-1>", self._press), ("<ButtonRelease-1>", self._release)):
                c.tag_bind(tag, event, lambda e, i=i, h=handler: h(i, e))
        if lay.get("track"):
            self._track(lay["track"])
        c.tag_raise("words")
        self.origin = (x0, y0)
        self.panel_size = (panel_w, panel_h)
        c.move("card", x0, y0)
        for i in range(len(self.buttons)):
            self._paint(i)
        if rise:
            c.move("card", 0, px(RISE))
            self._rise(self.generation, 0, px(RISE))

    def _track(self, track):
        """The progress track and its light: thin slices fading in and out, moved along every frame."""
        c = self.canvas
        left, top, right, bottom = track
        c.create_rectangle(left, top, right, bottom, fill=theme.RAIL, width=0, tags=("card", "track"))
        accent, rail = art._rgb(self.style["accent"]), art._rgb(theme.RAIL)
        self._slices = []
        count = 24
        for i in range(count):
            # Brightest in the middle of the light, the track's own colour at its ends.
            k = 1 - abs((i + 0.5) / count * 2 - 1)
            colour = "#%02x%02x%02x" % tuple(int(r + (a - r) * k) for a, r in zip(accent, rail))
            self._slices.append(c.create_rectangle(left, top, left, bottom, fill=colour, width=0, tags=("card",)))
        self._light = {"at": 0.0}
        self._sweep(self.generation)

    def _sweep(self, generation):
        """Move the light one step (it runs only while work is going on, and stops with the dialog)."""
        if self.closed or generation != self.generation or not self.canvas.winfo_exists():
            return
        # Where the track is now (the card may still be rising).
        left, top, right, bottom = self.canvas.coords(self.canvas.find_withtag("track")[0])
        span = right - left
        width = span * 0.34
        self._light["at"] = (self._light["at"] + span / 70.0) % (span + width)
        start = left - width + self._light["at"]
        step = width / len(self._slices)
        for i, item in enumerate(self._slices):
            x0 = max(left, min(right, start + i * step))
            x1 = max(left, min(right, start + (i + 1) * step + 1))
            self.canvas.coords(item, x0, top, x1, bottom)
        self._later(16, self._sweep, generation)

    def _rise(self, generation, frame, offset):
        """Ease the panel up into place, quickly at first and slowing at the end."""
        if self.closed or generation != self.generation or not self.canvas.winfo_exists():
            return
        frame += 1
        t = frame / float(FRAMES)
        left = int(round(self.ui.px(RISE) * (1 - t) ** 3))
        self.canvas.move("card", 0, left - offset)
        if frame < FRAMES:
            self._later(16, self._rise, generation, frame, left)

    def _paint(self, i):
        look = "pressed" if self.pressed == i else ("hover" if self.hover == i else "normal")
        self.canvas.itemconfigure(self._items[i], image=self._images[i][(look, self.focus == i)])

    # ------------------------------------------------------------------------------------------- input

    def _bind(self):
        c = self.canvas
        # Work under way (a progress dialog) cannot be cancelled from the keyboard.
        c.bind("<Escape>", lambda e: None if self.progress else self.close(self.cancel_value))
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            c.bind(key, lambda e: self.choose(self.focus))
        for key, step in (("<Tab>", 1), ("<Right>", 1), ("<Shift-Tab>", -1), ("<ISO_Left_Tab>", -1), ("<Left>", -1)):
            c.bind(key, lambda e, s=step: self.move(s))
        # The page underneath must not scroll while the dialog is up.
        for wheel in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            c.bind(wheel, lambda e: "break")
        c.bind("<Configure>", self._resized)
        c.bind("<Destroy>", self._destroyed)

    def _take_input(self):
        """Keyboard and mouse go to the dialog only, once it is on screen."""
        if self.closed or not self.canvas.winfo_exists():
            return
        if not self.canvas.winfo_viewable():
            self._later(20, self._take_input)
            return
        try:
            self.canvas.grab_set()
        except tk.TclError:
            # Another program holds the grab for a moment; try again shortly.
            self._later(50, self._take_input)
        self.canvas.focus_set()

    def _later(self, ms, fn, *args):
        """A timer on the dialog's canvas, remembered so closing the dialog cancels it."""
        job = self.canvas.after(ms, lambda: (self._jobs.discard(job), fn(*args)))
        self._jobs.add(job)
        return job

    def _cancel_jobs(self):
        for job in list(self._jobs):
            try:
                self.canvas.after_cancel(job)
            except tk.TclError:
                pass
        self._jobs.clear()

    def move(self, step):
        """Move the ring to the next or the previous button."""
        if self.buttons:
            old, self.focus = self.focus, (self.focus + step) % len(self.buttons)
            self._paint(old)
            self._paint(self.focus)
        return "break"

    def _enter(self, i, event):
        self.hover = i
        self.canvas.configure(cursor="hand2")
        self._paint(i)

    def _leave(self, i, event):
        self.hover = None
        self.canvas.configure(cursor="")
        self._paint(i)

    def _press(self, i, event):
        self.pressed = i
        self._paint(i)

    def _release(self, i, event):
        """A click counts when it ends over the same button (drag off to change your mind)."""
        self.pressed = None
        x, y = self.canvas.canvasx(event.x) - self.origin[0], self.canvas.canvasy(event.y) - self.origin[1]
        left, top, right, bottom = self._boxes[i]
        if left <= x < right and top <= y < bottom:
            self.choose(i)
        elif not self.closed:
            self._paint(i)

    def choose(self, i):
        if 0 <= i < len(self.buttons):
            self.close(self.buttons[i][1])
        return "break"

    # ----------------------------------------------------------------------------------------- closing

    def close(self, value):
        if self.closed:
            return
        self.closed, self.result = True, value
        self._cancel_jobs()
        try:
            self.canvas.grab_release()
            self.canvas.destroy()
        except tk.TclError:
            pass
        try:
            self.done.set(True)
            if self._before is not None and self._before.winfo_exists():
                self._before.focus_set()
        except tk.TclError:
            # The window itself is going.
            pass
        if self.on_close:
            self.on_close(value)

    def _destroyed(self, event):
        """The window was rebuilt or closed under the dialog: that answers as a cancel."""
        if event.widget is self.canvas and not self.closed:
            self.closed = True
            self._cancel_jobs()
            try:
                self.done.set(True)
            except tk.TclError:
                pass

    def _resized(self, event):
        # Before the first drawing (self.size unset) the size is about to be drawn anyway.
        if self.closed or self.size is None or (event.width, event.height) == self.size:
            return
        if self._resize_job is not None:
            self.canvas.after_cancel(self._resize_job)
        # Drawn again once the size settles (a drag sends many sizes).
        self._resize_job = self._later(80, self._redraw)

    def _redraw(self):
        self._resize_job = None
        if not self.closed and self.canvas.winfo_exists():
            self._draw()

    def wait(self):
        """Wait (the window keeps working) until the dialog is answered; returns the answer."""
        if not self.closed:
            try:
                self.root.wait_variable(self.done)
            except tk.TclError:
                pass
        return self.result

    # ------------------------------------------------------------------------------------------ checks

    def layout_problems(self):
        """Text or buttons outside the panel, text over the buttons, the panel outside the window: for the UI
        tests, which measure the dialog like the pages."""
        c, problems = self.canvas, []
        x0, y0 = self.origin
        panel = (x0, y0, x0 + self.panel_size[0], y0 + self.panel_size[1])
        width, height = self.size
        if panel[0] < 0 or panel[1] < 0 or panel[2] > width or panel[3] > height:
            problems.append("dialog: the panel does not fit the window (%r in %dx%d)" % (panel, width, height))
        tops = [y0 + b[1] for b in self._boxes]
        for item in c.find_withtag("words"):
            box = c.bbox(item)
            text = c.itemcget(item, "text")[:40]
            if box[0] < panel[0] or box[2] > panel[2] or box[1] < panel[1] or box[3] > panel[3]:
                problems.append("dialog: text outside the panel: %r" % text)
            if "button" not in " ".join(c.gettags(item)) and tops and box[3] > min(tops):
                problems.append("dialog: text runs into the buttons: %r" % text)
        for i, (left, top, right, bottom) in enumerate(self._boxes):
            words = self.buttons[i][0]
            if self.ui.fonts.dialog_button.measure(words) > right - left - 2 * self.ui.px(10):
                problems.append("dialog: button words do not fit: %r" % words)
        return problems


def _buttons(words, kind, confirm, cancel):
    return [(cancel or words("common.cancel"), False, "neutral"), (confirm, True, KINDS[kind]["button"])]


def ask(app, kind, title, message, detail, confirm, cancel=None):
    """Ask before doing something; True when the player chose `confirm`. Removing for good starts on Cancel, so
    Enter alone never removes anything; other questions start on their main button."""
    dialog = Dialog(app.root, app.ui, kind, title, message, detail, _buttons(app.words, kind, confirm, cancel),
                    default=0 if kind == "danger" else 1, cancel=False)
    app.dialog = dialog
    try:
        return bool(dialog.wait())
    finally:
        app.dialog = None


def choose(app, kind, title, message, detail, answers):
    """Ask a question with more than one way to go on: `answers` are [(words, value, look)] after Cancel. Returns the
    value chosen, or None for Cancel. It starts on Cancel, so Enter alone does nothing."""
    buttons = [(app.words("common.cancel"), None, "neutral")] + list(answers)
    dialog = Dialog(app.root, app.ui, kind, title, message, detail, buttons, default=0, cancel=None)
    app.dialog = dialog
    try:
        return dialog.wait()
    finally:
        app.dialog = None


def tell(app, kind, title, message, detail=None, ok=None):
    """Tell the player something that needs reading before going on (one button)."""
    dialog = Dialog(app.root, app.ui, kind, title, message, detail,
                    [(ok or app.words("common.ok"), True, KINDS[kind]["button"])], default=0, cancel=True)
    app.dialog = dialog
    try:
        dialog.wait()
    finally:
        app.dialog = None


def window_root(title="OpenDMTQ", language="en"):
    """A window of its own for dialogs, when there is no launcher window to draw over: (root, ui)."""
    safety.refuse_windows_in_tests("a dialog window")
    from opendmtq_client import i18n, widgets
    theme.register_fonts()
    root = tk.Tk()
    root.title(title)
    root.configure(bg=theme.BG)
    set_icon(root)
    scale = theme.scale_of(root)
    ui = widgets.Ui(root, theme.Fonts(root, language), scale, i18n.Words(language))
    px = ui.px
    width, height = px(WIDTH) + 2 * px(MARGIN) + px(40), px(400)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry("%dx%d+%d+%d" % (width, height, (sw - width) // 2, (sh - height) // 3))
    root.resizable(False, False)
    # Shown once before a dialog is drawn, so the window has its real size to draw for.
    root.update()
    # The person just started it: it takes the keyboard, so Enter and Esc answer it at once.
    root.focus_force()
    return root, ui


def fit(root, ui, dialog):
    """Make a window of its own as tall as its dialog's panel, with the same room above and below."""
    px = ui.px
    height = dialog.panel_size[1] + 2 * px(MARGIN) + px(16)
    if height != root.winfo_height():
        root.geometry("%dx%d" % (root.winfo_width(), height))


def set_icon(root):
    """The window's own icon (the mark) instead of Tk's feather, in the title bar and on the taskbar."""
    try:
        root.odq_icon = ImageTk.PhotoImage(art.mark(64), master=root)
        root.iconphoto(True, root.odq_icon)
    except tk.TclError:
        pass


def window(kind, title, message, detail=None, buttons=(), default=0, cancel=None, language="en"):
    """A dialog in a window of its own, over the site's shards, for when the launcher cannot open its window. Returns
    (root, dialog); the window closes itself once the dialog is answered."""
    root, ui = window_root(language=language)
    dialog = Dialog(root, ui, kind, title, message, detail, buttons, default=default, cancel=cancel,
                    window=lambda w, h: art.backdrop(w, h, ui.scale), on_close=lambda value: root.destroy())
    fit(root, ui, dialog)
    root.protocol("WM_DELETE_WINDOW", lambda: dialog.close(cancel))
    return root, dialog


def standalone(kind, title, message, detail=None, buttons=(), default=0, cancel=None, language="en"):
    """window() and wait for the answer: the chosen button's value (`cancel` when the window is closed)."""
    root, dialog = window(kind, title, message, detail, buttons, default, cancel, language)
    root.mainloop()
    return dialog.result
