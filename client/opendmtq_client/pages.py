"""The launcher's pages, as the site's: a title in the wide face and a line under it (heading), then cards. Each builder
fills the page's column.

A setting row changes the remembered state right away (app.changed); the player reads the settings at the next PLAY,
so nothing changes under a game that is running.
"""

import logging
import os
import threading
import tkinter as tk

from opendmtq_client import actions, apps, dialogs, displays, i18n, maintenance, player, theme, updates, widgets
from opendmtq_client import server as srv
from opendmtq_client import state as st
from opendmtq_client import values as choices

log = logging.getLogger("opendmtq_client")

# ------------------------------------------------------------------------------------------- headings

# Each page's title, in English in both languages as the site's page titles and the game's menus are.
TITLES = {"play": "PLAY", "screen": "SCREEN", "sound": "SOUND", "controls": "CONTROLS", "online": "ONLINE",
          "help": "HELP", "about": "LAUNCHER"}


def heading(app, page):
    """A page's title and the line under it: PLAY's says where it plays, the others what the page is for."""
    if page == "play":
        server = app.state.server()
        return TITLES[page], (app.words("play.on", name=server["name"]) if server else app.words("app.tagline"))
    return TITLES[page], app.words(page + ".sub")


def main_button(app, parent, text, command):
    """A page's main action (Connect, Sign in, the app's download, the launcher's update) as a button: lit in lime while
    PLAY is not, and quiet beside a lit PLAY, so that a screen has one lime main action. It follows PLAY as PLAY
    changes (app._paint_play); the guide's steps, which have no PLAY, light it."""
    button = widgets.Button(parent, app.ui, text, command, kind="secondary" if app.play_lit() else "primary")
    app.main_buttons.append(button)
    return button


def _card(parent, ui, title, last=False):
    """A card with its title, stacked under the ones before it with the site's gap between cards."""
    card = widgets.Card(parent, ui, title)
    card.pack(fill="x", pady=(0, 0 if last else ui.px(CARD_GAP)))
    return card


# The gap between two cards (the site's --gap is 20 px; the window is smaller than a page).
CARD_GAP = 16

# The names of the setting rows a choice or the PC brings to a page or takes from it (a window's size, the counter's
# corner, the upscaler; the game's log once the game has run, Repair and Uninstall in an installed launcher): counted in
# the page's names' column whether shown or not (widgets.fit_names), so that none of them moves the controls when it comes.
ROWS_THAT_COME = {
    "screen": ("screen.size", "screen.counter.position", "screen.upscaler"),
    "help": ("help.player_log", "help.repair.row", "help.uninstall.row"),
    # The guide's SOUND CHECK: the Screen page's first rows, the counter's corner among them.
    "guide:sound": ("screen.counter.position",),
}


def rows_that_come(page):
    """The names of ROWS_THAT_COME[page] in both languages, for widgets.fit_names."""
    return [words for key in ROWS_THAT_COME.get(page, ()) for words in i18n.TEXT[key] if words]


def _columns(parent, ui, weights=(3, 2)):
    """Cards side by side: a frame for each column, as wide as its share of the row less the gaps. The shares come from
    the row's own width alone: a grid that sized them from what they hold would loop for ever, as the text in each
    wraps to the width it is given and so asks for what it got (one pixel going back and forth between the columns)."""
    row = tk.Frame(parent, bg=theme.BG)
    row.pack(fill="x")
    columns = []
    for i in range(len(weights)):
        column = tk.Frame(row, bg=theme.BG)
        column.grid(row=0, column=i, sticky="nsew", padx=(ui.px(CARD_GAP) if i else 0, 0))
        columns.append(column)

    def fit(event):
        room = max(1, event.width - ui.px(CARD_GAP) * (len(weights) - 1))
        given = 0
        for i, weight in enumerate(weights):
            width = room * weight // sum(weights) if i < len(weights) - 1 else room - given
            given += width
            row.columnconfigure(i, minsize=width + (ui.px(CARD_GAP) if i else 0), weight=0)

    row.bind("<Configure>", fit)
    return columns


# ---------------------------------------------------------------------------------------------- PLAY


def _server_card(app, parent):
    """Where PLAY plays: the server, its address, and the account signed in there."""
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("play.server"))
    server = app.state.server()
    line = tk.Frame(card.body, bg=theme.PANEL)
    line.pack(fill="x")
    if server is None:
        widgets.label(line, ui, w("play.no_server"), fg=theme.MUTED, wrap_margin=0).pack(side="left", fill="x",
                                                                                         expand=True)
        main_button(app, line, w("play.connect"), lambda: app.nav_go("online")).pack(side="right")
        return
    signed = app.state.signed_in(server)
    if not signed:
        main_button(app, line, w("online.signin"), lambda: app.nav_go("online")).pack(side="right", anchor="n")
    words = tk.Frame(line, bg=theme.PANEL)
    words.pack(side="left", fill="x", expand=True)
    if st.has_own_name(server):
        # Its name, and its address under it.
        widgets.label(words, ui, server["name"], font=ui.fonts.body_bold, wrap_margin=0).pack(fill="x")
        widgets.label(words, ui, server["url"], font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0).pack(fill="x")
    else:
        # A server with no name of its own calls itself by its address: said once, in the name's place.
        widgets.label(words, ui, server["url"], font=ui.fonts.body_bold, wrap_margin=0).pack(fill="x")
    widgets.divider(card.body, ui)
    account = (w("play.signed", account=server["account"]) if signed else
               w("play.not_signed", account=server["account"]) if server.get("account") else w("play.no_account"))
    state = widgets.check_line(card.body, ui, "ok" if signed else "change", account)
    state.pack(fill="x")


def build_play(app, parent):
    ui, w = app.ui, app.words
    _server_card(app, parent)
    left, right = _columns(parent, ui)
    # Left: the ready check, filled in when the worker thread finishes it, as tall as the column so that the row's
    # cards end on one line; Check again stands at its foot, so the room the column gives it lies between the rows and
    # their button instead of under everything.
    ready = widgets.Card(left, ui, w("play.ready"))
    ready.pack(fill="both", expand=True)
    foot = tk.Frame(ready.body, bg=theme.PANEL)
    foot.pack(side="bottom", fill="x", pady=(ui.px(16), 0))
    widgets.Button(foot, ui, w("help.recheck"), lambda: app.refresh_checks(force=True)).pack(anchor="w")
    app.check_box = tk.Frame(ready.body, bg=theme.PANEL)
    app.check_box.pack(fill="x")
    # Right: how to play, and how the last game went, the last as tall as what is left of the column (when the ready
    # check is the taller), its button at its foot.
    how = _card(right, ui, w("play.how"))
    for i, key in enumerate(("play.how.1", "play.how.2", "play.how.3")):
        if i:
            widgets.divider(how.body, ui, pady=8)
        widgets.label(how.body, ui, w(key), wrap_margin=0).pack(fill="x")
    last = widgets.Card(right, ui, w("play.last"))
    last.pack(fill="both", expand=True)
    record = app.state.last_session or {}
    if record.get("crashed") or record.get("failed_start"):
        # The reason is in the player's log: one press away from where it says the game stopped.
        widgets.Button(last.body, ui, w("status.open_log"), app.open_player_log).pack(side="bottom", anchor="w",
                                                                                      pady=(ui.px(12), 0))
    widgets.label(last.body, ui, _last_session(app), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
    # Made again each time the page shows: a sign-in can have ended, or an app come, since the last one. Until it
    # comes back, the box says it is being made.
    app.refresh_checks()
    refresh_checks(app)


def _last_session(app):
    record, w = app.state.last_session, app.words
    if not record:
        return w("play.last.none")
    minutes = record.get("seconds", 0) // 60
    span = w("common.minutes", m=minutes) if minutes else w("common.seconds", s=record.get("seconds", 0))
    if record.get("failed_start"):
        return w("play.last.failed")
    return w("play.last.crash" if record.get("crashed") else "play.last.ok", time=span)


def refresh_checks(app):
    """Fill the ready check (PLAY page, Help page, the guide's last step) from app.checks: a row a line, each with its
    lamp, its name, and at the right end what it is about or the way to fix it."""
    box = getattr(app, "check_box", None)
    if box is None or not box.winfo_exists():
        return
    for child in box.winfo_children():
        child.destroy()
    ui, w = app.ui, app.words
    # While a check is made (it may ask the server for a few seconds), the last one that came back stays on show: the
    # rows do not blink to "..." and back each time a page asks for one.
    checks = app.checks if app.checks is not None else getattr(app, "shown_checks", None)
    if checks is None:
        widgets.label(box, ui, "...", fg=theme.MUTED).pack(anchor="w")
        return
    from opendmtq_client import installed
    for i, check in enumerate(checks):
        if i:
            widgets.divider(box, ui, pady=9)
        name, value, action, fix = w("check." + check.key), None, None, w("play.fix")
        if not check.ok and check.key == "player" and installed.root():
            # The player comes with the launcher: the installed one puts it back from its package.
            state, fix, action = "bad", w("check.player.repair"), lambda: maintenance.repair_program(app)
        elif not check.ok and check.key == "player":
            # A copied folder: installing brings the player back, and no page here can.
            state, value = "bad", w("check.player.missing")
        elif check.ok:
            state = "ok"
            # What it is about, which a player wants to confirm: the server, the account, the app's date. The PLAY
            # page's server card above already names the server and the account.
            about = ("app",) if app.page == "play" and app.guide is None else ("server", "account", "app")
            if check.key in about:
                value = check.detail
        elif check.play_fixes:
            # PLAY does these by itself; the row only says it will.
            state, value = "change", w("play.will_get")
        elif not check.blocks and check.key == "server":
            # The server does not answer: nothing to fix on this PC, and PLAY still plays this PC's app.
            state, value = "change", w("check.server.down")
        else:
            state = "bad" if check.key in actions.BLOCKING else "change"
            action = (lambda p=check.page: app.nav_go(p)) if check.page and app.guide is None else None
        widgets.check_line(box, ui, state, name, fix if action else None, action, value=value).pack(fill="x")


# -------------------------------------------------------------------------------------------- Screen


def screen_rows(app, parent, redraw, full=True):
    """The Screen page's settings in their cards, which the guide's SOUND CHECK shows too (full=False: the ones a first
    start needs)."""
    ui, w, v = app.ui, app.words, app.state.values
    display = displays.main_display(app.root)
    mode = v["display"]

    def set_and_redraw(name):
        def setter(value):
            app.changed(name, value)
            # The rows and hints that follow depend on it: draw the page again.
            redraw()
        return setter

    card = _card(parent, ui, w("screen.display"))
    widgets.setting_row(card.body, ui, w("screen.mode"),
                        lambda p: widgets.Segmented(p, ui, [("fullscreen", w("screen.mode.fullscreen")),
                                                            ("window", w("screen.mode.window"))], mode,
                                                    set_and_redraw("display")),
                        w("screen.mode.hint." + mode)).pack(fill="x")
    if mode == "window" and full:
        # Sizes that fit the display with room for the title bar and the taskbar (values.fits, which --set window= uses
        # too); fitted always stays.
        sizes = [s for s in choices.WINDOW_SIZES if choices.fits(s, display)]
        if v["window"] not in sizes:
            # A size set on the command line keeps its row.
            sizes.append(v["window"])
        options = [(s, w("screen.size.auto") if s == "auto" else s.replace("x", " × ")) for s in sizes]
        widgets.divider(card.body, ui)
        widgets.setting_row(card.body, ui, w("screen.size"),
                            lambda p: widgets.Select(p, ui, options, v["window"], lambda s: app.changed("window", s),
                                                     width=22),
                            w("screen.size.hint")).pack(fill="x")
    hz = display.get("hz")
    if full:
        widgets.divider(card.body, ui)
        widgets.label(card.body, ui, w("screen.main", w=display["width"], h=display["height"]) + (
            w("screen.main.hz", hz=hz) if hz else ""), font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0).pack(
            fill="x")
    card = _card(parent, ui, w("screen.frames"), last=not full)
    vsync = v["vsync"] == "on"
    widgets.setting_row(card.body, ui, w("screen.vsync"),
                        lambda p: widgets.Toggle(p, ui, vsync,
                                                 lambda on: set_and_redraw("vsync")("on" if on else "off")),
                        w("screen.vsync.hint." + ("on" if vsync else "off"))).pack(fill="x")
    rate = w("screen.fps.auto.hz", hz=hz) if hz else w("screen.fps.auto")
    # With VSync on a display whose rate is known, the limits above that rate are left out: VSync holds the game at the
    # display's rate whatever the limit (values.vsync_refreshes, the player's own arithmetic). A limit set before (with
    # VSync off, or on the command line) keeps its row, and its hint says so.
    options = [(f, rate if f == "auto" else w("screen.fps.unlimited") if f == "unlimited" else w("screen.fps.n", n=f))
               for f in fps_choices(vsync, hz, v["fps"])]
    widgets.divider(card.body, ui)
    widgets.setting_row(card.body, ui, w("screen.fps"),
                        lambda p: widgets.Select(p, ui, options, v["fps"], set_and_redraw("fps"), width=22),
                        fps_hint(w, vsync, v["fps"], hz)).pack(fill="x")
    # The frame counter over the game, on or off; while on, its corner (the bottom right unless another is picked). Drawn
    # again on a change: the corner's row is there only while the counter is on.
    counter = v["show_fps"] == "on"
    widgets.divider(card.body, ui)
    widgets.setting_row(card.body, ui, w("screen.counter"),
                        lambda p: widgets.Toggle(p, ui, counter,
                                                 lambda on: set_and_redraw("show_fps")("on" if on else "off")),
                        w("screen.counter.hint." + ("on" if counter else "off"))).pack(fill="x")
    if counter:
        options = [(c, w("screen.counter.position." + c)) for c in choices.FPS_POSITION]
        widgets.divider(card.body, ui)
        widgets.setting_row(card.body, ui, w("screen.counter.position"),
                            lambda p: widgets.Select(p, ui, options, v["fps_position"],
                                                     lambda c: app.changed("fps_position", c), width=22),
                            w("screen.counter.position.hint")).pack(fill="x")
    if not full:
        return
    card = _card(parent, ui, w("screen.picture"), last=True)
    options = [(s, w("screen.scale.full") if s == "100" else "%s%%" % s) for s in choices.RENDER_SCALE]
    # Drawn again on a change: the upscaler's row is there only below 100 %.
    widgets.setting_row(card.body, ui, w("screen.scale"),
                        lambda p: widgets.Select(p, ui, options, v["render_scale"], set_and_redraw("render_scale"),
                                                 width=22),
                        w("screen.scale.hint")).pack(fill="x")
    if v["render_scale"] != "100":
        # What makes the picture of a lower scale the area's size; its hint says what the chosen one does.
        options = [(u, w("screen.upscaler." + u)) for u in choices.UPSCALER]
        widgets.divider(card.body, ui)
        widgets.setting_row(card.body, ui, w("screen.upscaler"),
                            lambda p: widgets.Select(p, ui, options, v["upscaler"], set_and_redraw("upscaler"), width=22),
                            w("screen.upscaler.hint." + v["upscaler"])).pack(fill="x")
    # The edges smoothed, at any scale; its hint says what the chosen one does.
    options = [(a, w("screen.aa." + a)) for a in choices.ANTI_ALIASING]
    kind = v["anti_aliasing"]
    widgets.divider(card.body, ui)
    widgets.setting_row(card.body, ui, w("screen.aa"),
                        lambda p: widgets.Select(p, ui, options, v["anti_aliasing"], set_and_redraw("anti_aliasing"),
                                                 width=22),
                        w("screen.aa.hint." + kind)).pack(fill="x")


def fps_choices(vsync, hz, current):
    """The frame limits the Screen page offers: all of them, but with VSync on a display whose rate is known none above
    that rate (VSync holds the game at it whatever the limit); the `current` one keeps its row all the same."""
    offered = [f for f in choices.FPS if not (vsync and hz) or not choices.above_rate(hz, f)]
    return offered + ([current] if current not in offered else [])


def fps_hint(w, vsync, fps, hz):
    """The frame limit's hint for its value: without VSync, the game holds it itself; with VSync, the display's own
    rate, or on a display whose rate is known, what this limit gives there (exactly, very nearly, or held at the rate:
    values.vsync_refreshes, as the player paces the frames)."""
    if not vsync:
        return w("screen.fps.hint.free")
    if fps == "auto":
        return w("screen.fps.hint.vsync_rate")
    if not hz:
        return w("screen.fps.hint.vsync")
    if choices.above_rate(hz, fps):
        # Above the display's rate: every refresh, no more.
        return w("screen.fps.hint.vsync.above", hz=hz)
    refreshes = choices.vsync_refreshes(hz, fps)
    if refreshes:
        # Each frame the same number of refreshes: the rate a whole fraction of the display's.
        return w("screen.fps.hint.vsync.exact", hz=hz, fps=int(round(hz / float(refreshes))))
    return w("screen.fps.hint.vsync.near", hz=hz, n=fps)


def _focus_order(widget):
    """The widgets under `widget` that take the keyboard, in the order Tab visits them (the page's packing order)."""
    found = []
    for child in widget.winfo_children():
        # A widget that takes the keyboard (a drop-down, a toggle, a segment) is one stop; what is inside it is not.
        # Asked of Tk itself: a widget may have a `keys` of its own, and one without the option takes no keyboard.
        try:
            takes = str(child.cget("takefocus"))
        except tk.TclError:
            takes = ""
        if takes not in ("", "0"):
            found.append(child)
        else:
            found.extend(_focus_order(child))
    return found


def keep_place(area, root, rebuild):
    """A page area drawn again by `rebuild()` for a change (a choice that adds or removes rows, an answer that came),
    keeping where it was scrolled to and the control the keyboard was on: choosing a buffer at the Sound page's foot,
    or switching VSync on the guide's SOUND CHECK, does not throw the page back to its top and the keyboard out of it."""
    top = area.canvas.yview()[0]
    before = _focus_order(area.inner)
    focused = root.focus_get()
    index = before.index(focused) if focused in before else None
    rebuild()
    # Laid out first, so that the scroll's place is measured on the new page's height.
    root.update_idletasks()
    area.canvas.yview_moveto(top)
    if index is not None:
        # The rows before the changed one are the same, so the same place in the order is the same control.
        after = _focus_order(area.inner)
        if index < len(after):
            after[index].focus_set()


def redraw_in_place(app, page):
    """A page of the launcher drawn again in place (keep_place)."""
    keep_place(app.body, app.root, lambda: app.go(page))


def build_screen(app, parent):
    screen_rows(app, parent, lambda: redraw_in_place(app, "screen"))


# --------------------------------------------------------------------------------------------- Sound


def sound_rows(app, parent, redraw, full=True):
    """The Sound page's settings in their cards, which the guide's SOUND CHECK shows too (full=False: the volume
    alone)."""
    ui, w, v = app.ui, app.words, app.state.values
    card = _card(parent, ui, w("sound.volume"), last=not full)
    widgets.setting_row(card.body, ui, w("sound.volume.game"),
                        lambda p: widgets.Slider(p, ui, v["volume"], lambda val: app.changed("volume", val)),
                        w("sound.volume.hint")).pack(fill="x")
    if not full:
        return
    card = _card(parent, ui, w("sound.output"), last=True)
    if app.devices is None:
        # Asked once from the player, on a worker thread; the page is drawn again with the answer.
        widgets.setting_row(card.body, ui, w("sound.device"),
                            lambda p: widgets.label(p, ui, w("sound.device.looking"), fg=theme.MUTED)).pack(fill="x")
        app.load_devices(then=redraw)
    else:
        options = [("default", w("sound.device.default"))]
        options += [(d["id"], d["name"] + (w("sound.device.now_default") if d["default"] else "")) for d in app.devices]
        if v["audio_device"] != "default" and all(d["id"] != v["audio_device"] for d in app.devices):
            # A device chosen before that is not there now (unplugged): it stays chosen, and says so.
            options.append((v["audio_device"], w("sound.device.gone")))
        widgets.setting_row(card.body, ui, w("sound.device"),
                            lambda p: widgets.Select(p, ui, options, v["audio_device"],
                                                     lambda d: app.changed("audio_device", d), width=34),
                            w("sound.device.hint" if app.devices else "sound.device.none")).pack(fill="x")

    def set_and_redraw(name):
        def setter(value):
            app.changed(name, value)
            redraw()
        return setter

    mode = v["audio_mode"]
    widgets.divider(card.body, ui)
    widgets.setting_row(card.body, ui, w("sound.mode"),
                        lambda p: widgets.Segmented(p, ui, [("shared", w("sound.mode.shared")),
                                                            ("exclusive", w("sound.mode.exclusive"))], mode,
                                                    set_and_redraw("audio_mode")),
                        w("sound.mode.hint." + mode)).pack(fill="x")
    buffer = v["audio_buffer"]
    widgets.divider(card.body, ui)
    widgets.setting_row(card.body, ui, w("sound.buffer"),
                        lambda p: widgets.Segmented(p, ui, [("low", w("sound.buffer.low")),
                                                            ("normal", w("sound.buffer.normal")),
                                                            ("safe", w("sound.buffer.safe"))], buffer,
                                                    set_and_redraw("audio_buffer")),
                        w("sound.buffer.hint." + buffer)).pack(fill="x")


def build_sound(app, parent):
    # Drawn again in place for a choice and for the devices when they come (only while the page is still on show).
    sound_rows(app, parent, lambda: app.page == "sound" and redraw_in_place(app, "sound"))


# ------------------------------------------------------------------------------------------ Controls


def build_controls(app, parent):
    ui, w = app.ui, app.words
    # The game's bar over it in each group by the way it comes: the pointer, a finger, and the keys it does not take.
    groups = (("controls.mouse", ("controls.click", "controls.drag", "controls.wheel", "controls.menu",
                                  "controls.minimise")),
              ("controls.touch", ("controls.fingers", "controls.edges", "controls.bar")),
              ("controls.keyboard", ("controls.esc", "controls.alt_f4", "controls.typing")))
    for n, (title, keys) in enumerate(groups):
        card = _card(parent, ui, w(title), last=n == len(groups) - 1)
        for i, key in enumerate(keys):
            # One line each, split by the card's faint lines.
            if i:
                widgets.divider(card.body, ui, pady=9)
            widgets.label(card.body, ui, w(key), wrap_margin=0).pack(fill="x")


# -------------------------------------------------------------------------------------------- Online


def server_line(app):
    """The one line under the server's address: (words, colour). Before the server was asked in this run, the server
    PLAY plays on; then "connecting", what it answered, or why it did not (app.server_check)."""
    w, server, check = app.words, app.state.server(), app.server_check
    if check and check["state"] == "checking":
        return w("online.connecting"), theme.MUTED
    if check and check["state"] == "failed" and not check.get("seen"):
        if not server or check["url"] != server["url"]:
            # An address the player typed, not the server in use: said this once, then the line is the server's again.
            check["seen"] = True
        return w.error(check["error"]), theme.BAD
    if server and check and check["state"] == "ok" and check["url"] == server["url"]:
        return w("online.connected", name=server["name"]), theme.OK
    if server:
        return w("online.to_play", name=server["name"]), theme.MUTED
    return "", theme.MUTED


def check_server(app, address, then=None):
    """Ask the server at `address` whether it is an OpenDMTQ server, on a worker thread, and play on it when it is.
    app.server_check follows (checking, ok, failed); then() runs on the window's thread after either answer."""
    w = app.words
    try:
        # Kept as the launcher writes every address, so the answer matches the server it is about.
        address = srv.normalize(address)
    except srv.ServerError:
        # Not an address: actions.connect says so, below.
        pass
    app.server_check = {"url": address, "state": "checking"}

    def work():
        try:
            # Known and played on from the window's own thread (app.post), before answered() below runs there.
            actions.connect(app.state, address, change=app.post)
            app.post(lambda: answered({"url": app.state.current, "state": "ok"}))
        except Exception as e:  # noqa: BLE001  (ServerError, or anything else: shown, never a silent stop)
            # The system's own words for it go to the log; the window says it plainly.
            log.info("could not connect to %s: %s", address, e)
            app.post(lambda error=e: answered({"url": address, "state": "failed", "error": error}))

    def answered(check):
        app.server_check = check
        if check["state"] == "ok":
            # Connected: the field shows the server in use again, as the launcher writes its address.
            app.address_draft = None
            # Another server, or the same one again: what the last download said is not about it.
            app.download_error, app.app_note = None, None
            app.user_acted()
            app.state.save()
            app.refresh_checks()
        if then:
            then()

    threading.Thread(target=work, daemon=True, name="connect").start()


def connect_panel(app, parent, rerender, forget=False):
    """The server's card: its address and Connect, and one line under them (server_line). With `forget`, the server in
    use can be forgotten there too (the Online page; the guide only connects)."""
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("online.server"))
    parent, bg = card.body, theme.PANEL
    row = tk.Frame(parent, bg=bg)
    row.pack(fill="x")
    tk.Label(row, text=w("online.address"), font=ui.fonts.small, fg=theme.MUTED, bg=bg).grid(row=0, column=0, sticky="w")
    field = widgets.Field(row, ui, width=34)
    field.grid(row=1, column=0, sticky="w", padx=(0, ui.px(12)))
    address = field.entry
    server = app.state.server()
    in_use = server["url"] if server else ""
    # The field holds what the player typed until it connects or the server in use changes (app.address_draft): a
    # failed Connect keeps it, as the line under it names it, instead of the server in use or nothing coming back.
    address.insert(0, in_use if app.address_draft is None else app.address_draft)

    def remember(event=None):
        # What the field holds, kept for the page's next drawing; the address in use again is no draft.
        text = address.get()
        app.address_draft = None if text.strip() == in_use else text

    # Each key the player types (a paste with Ctrl+V too) is in the field by the time the key comes up. A binding of the
    # field's own goes with the field, where a variable traced for it would outlive every page that drew one.
    address.bind("<KeyRelease>", remember, add="+")
    text, colour = server_line(app)
    answer = widgets.label(parent, ui, text, font=ui.fonts.small, fg=colour, bg=bg, wrap_margin=0)
    answer.pack(fill="x", pady=(ui.px(8), 0))

    def connect():
        if app.busy_now():
            answer.configure(text=w("online.busy"), fg=theme.WARN)
            return
        # What is asked is what the field holds: kept for the page drawn again with the answer.
        remember()
        check_server(app, address.get(), then=rerender)
        # Said at once, before the server answers.
        answer.configure(text=w("online.connecting"), fg=theme.MUTED)

    address.bind("<Return>", lambda e: connect())
    # The page's main action is the next step: Connect while there is no server (then Sign in, then the app's download).
    if server:
        connect_button = widgets.Button(row, ui, w("online.connect"), connect)
    else:
        connect_button = main_button(app, row, w("online.connect"), connect)
    connect_button.grid(row=1, column=1, sticky="w")
    if server and forget:
        # After Connect, apart from it: the next server this launcher knows becomes the one PLAY plays on.
        widgets.Button(row, ui, w("online.forget"), lambda: forget_server(app, server, rerender),
                       kind="danger").grid(row=1, column=2, sticky="w", padx=(ui.px(8), 0))
    if not server:
        # Not connected yet: typing goes to the address, Enter connects.
        address.after_idle(address.focus_set)
    return address


def signin_panel(app, parent, rerender):
    """The sign-in on the current server: who is signed in and Sign out, or the ID and password and Sign in."""
    ui, w = app.ui, app.words
    server = app.state.server()
    if server is None:
        return
    # The card's title says the state: signed in, or the sign-in to make.
    card = _card(parent, ui, w("online.account.signed" if app.state.signed_in(server) else "online.account"))
    parent, bg = card.body, theme.PANEL
    if app.state.signed_in(server):
        signed = tk.Frame(parent, bg=bg)
        signed.pack(fill="x")
        widgets.lamp(signed, ui, theme.OK, bg=bg).pack(side="left")

        def sign_out():
            if app.busy_now():
                # The download or the game uses the sign-in now: it stays until they are over.
                app.set_status(i18n.Said("online.busy"), "warn")
                return
            app.user_acted()
            actions.sign_out(app.state)
            app.state.save()
            app.refresh_checks()
            rerender()

        # Sign out right after the account it signs out of.
        widgets.label(signed, ui, w("online.signed", account=server["account"]), bg=bg).pack(
            side="left", padx=(ui.px(6), 0))
        widgets.Button(signed, ui, w("online.signout"), sign_out).pack(side="left", padx=(ui.px(16), 0))
        return
    form = tk.Frame(parent, bg=bg)
    form.pack(anchor="w")
    fields = {}
    for col, (key, secret) in enumerate((("online.id", False), ("online.password", True))):
        tk.Label(form, text=w(key), font=ui.fonts.small, fg=theme.MUTED, bg=bg).grid(row=0, column=col, sticky="w")
        box = widgets.Field(form, ui, width=16, secret=secret)
        box.grid(row=1, column=col, sticky="w", padx=(0, ui.px(12)))
        fields[key] = box.entry
    if server.get("account"):
        # The account signed in before: only the password to type again.
        fields["online.id"].insert(0, server["account"])
    message = widgets.label(parent, ui, w("online.signin.hint"), font=ui.fonts.small, fg=theme.MUTED, bg=bg,
                            wrap_margin=0)

    # One sign-in at a time: Enter pressed twice sends one request (the server counts every try).
    asking = {"now": False}

    def sign_in():
        if asking["now"]:
            return
        asking["now"] = True
        message.configure(text=w("online.signing"), fg=theme.MUTED)
        user, password = fields["online.id"].get(), fields["online.password"].get()

        def work():
            try:
                # The sign-in is kept on the window's own thread, before signed_in() saves it there.
                actions.sign_in(app.state, user, password, change=app.post)
                app.post(signed_in)
            except Exception as e:  # noqa: BLE001
                # The server's own words for it go to the log (never the password); the form says it plainly.
                log.info("could not sign in to %s as %s: %s", server["url"], user, e)
                app.post(lambda text=w.error(e): refused(text))

        threading.Thread(target=work, daemon=True, name="sign-in").start()

    def refused(text):
        """The server said no: what it said, and the password ready to type again."""
        asking["now"] = False
        if not message.winfo_exists():
            return
        message.configure(text=text, fg=theme.BAD)
        password = fields["online.password"]
        password.focus_set()
        password.select_range(0, "end")

    def signed_in():
        asking["now"] = False
        # A sign-in is the player's doing: a message kept until then gives way (a sign-in that had ended, say).
        app.user_acted()
        app.state.save()
        app.refresh_checks()
        rerender()

    for field in fields.values():
        field.bind("<Return>", lambda e: sign_in())
    # Typing goes to the first empty field; Tab to the next; Enter signs in.
    first = fields["online.password"] if server.get("account") else fields["online.id"]
    first.after_idle(first.focus_set)
    main_button(app, form, w("online.signin"), sign_in).grid(row=1, column=2, sticky="w")
    message.pack(fill="x", pady=(ui.px(8), 0))


def app_panel(app, parent, rerender):
    """The server's app on this PC: what it has, what the server offers, and the download with its progress."""
    ui, w = app.ui, app.words
    server = app.state.server()
    if server is None:
        return
    card = _card(parent, ui, w("online.app"))
    parent, bg = card.body, theme.PANEL
    have = apps.local(server["url"])
    offered = server.get("app")
    newer = bool(have and offered and offered.get("sha256", "").lower() != have["sha256"])
    if have and not newer:
        text, colour = w("online.app.have", date=_date(have)), theme.TEXT
    elif have:
        text, colour = w("online.app.newer", date=_date(offered)), theme.WARN
    else:
        text, colour = w("online.app.none"), theme.WARN
    widgets.label(parent, ui, text, fg=colour, bg=bg, wrap_margin=0).pack(fill="x", pady=(0, ui.px(10)))
    if app.download is None and app.app_note and not newer:
        # The last look for a newer app found none: said here, where its button is.
        widgets.label(parent, ui, w.say(app.app_note), font=ui.fonts.small, fg=theme.MUTED, bg=bg, wrap_margin=0).pack(
            fill="x", pady=(0, ui.px(10)))
    if app.download is None and app.download_error:
        # What the last try said (a stop, a sign-in that ended, a line that broke), in the same colour as the status
        # line says it: the guide has no status line to say it.
        said, tone = app.download_error
        widgets.label(parent, ui, w.say(said), font=ui.fonts.small, fg=theme.WARN if tone == "warn" else theme.BAD,
                      bg=bg, wrap_margin=0).pack(fill="x", pady=(0, ui.px(10)))
    if app.download is not None:
        # The download under way: its bar, kept moving by the app (app._download_moved), and Cancel.
        bar = widgets.Progress(parent, ui, bg=bg)
        bar.pack(anchor="w", pady=(0, ui.px(10)))
        done, total = app.download["done"], app.download["total"]
        # The status line's words (app.download_words): how far it is, the server asked first, or stopping.
        bar.set(done / float(total) if total else None, w.say(app.download_words()))
        app.download_bar = bar
        stopping = app.download.get("stopping")
        stop = widgets.Button(parent, ui, w("online.stopping") if stopping else w("common.cancel"), lambda: halt())
        stop.pack(anchor="w")
        if stopping:
            stop.enable(False)

        def halt():
            # Off at once, saying so: the download stops as soon as the next piece is in.
            app.cancel_download()
            stop.set_text(w("online.stopping"))
            stop.enable(False)
        return
    if not app.state.signed_in(server):
        widgets.label(parent, ui, w("online.app.signin_newer" if have else "online.app.signin"), font=ui.fonts.small,
                      fg=theme.MUTED, bg=bg, wrap_margin=0).pack(fill="x")
        return
    buttons = tk.Frame(parent, bg=bg)
    buttons.pack(anchor="w")
    words = w("online.app.update") if newer else w("online.app.check") if have else w("online.app.get")
    # Getting an app this PC lacks, or the newer one, is the page's main action; looking for a newer one is not.
    if not have or newer:
        get = main_button(app, buttons, words, lambda: _get(app, rerender))
    else:
        get = widgets.Button(buttons, ui, words, lambda: _get(app, rerender))
    get.pack(side="left")


def _date(details):
    """The day an app was built, as its server said ('2026-11-08'); its file name when it said none."""
    built = str((details or {}).get("built_at") or "")
    return built[:10] if built else str((details or {}).get("file") or "")


def _get(app, rerender):
    """Ask the server for its app and download it when this PC lacks it; the page shows the progress."""
    if app.busy_now():
        app.set_status(i18n.Said("online.busy"), "warn")
        return
    app.get_app(done_then=lambda error: rerender())
    rerender()


def known_servers(app, parent, rerender):
    """The other servers this launcher knows: play on one of them instead, or forget one."""
    ui, w = app.ui, app.words
    others = [s for s in app.state.servers if s["url"] != app.state.current]
    if not others:
        return
    card = _card(parent, ui, w("online.others"), last=True)
    for i, s in enumerate(others):
        # One row a server, split by the card's faint lines.
        if i:
            widgets.divider(card.body, ui, pady=9)
        line = tk.Frame(card.body, bg=theme.PANEL)
        line.pack(fill="x")

        def pick(url=s["url"]):
            if app.busy_now():
                app.set_status(i18n.Said("online.busy"), "warn")
                return
            # Another server to play on: what the line said about the one before (an installer's server, a failure)
            # gives way to where PLAY stands on this one once the ready check below answers.
            app.user_acted()
            app.state.current = url
            # The server in use changed: the address field shows it, whatever was typed there before.
            app.address_draft = None
            # What the last server's download said is not this one's.
            app.download_error, app.app_note = None, None
            app.state.save()
            app.refresh_checks()
            rerender()

        forget_button = widgets.Button(line, ui, w("online.forget"), lambda s=s: forget_server(app, s, rerender),
                                       kind="danger")
        forget_button.pack(side="right")
        pick_button = widgets.Button(line, ui, w("online.pick"), pick)
        pick_button.pack(side="right", padx=(0, ui.px(8)))
        # Its name and address, or its address once when it has no name of its own.
        named = "%s  ·  %s" % (s["name"], s["url"]) if st.has_own_name(s) else s["url"]
        widgets.label(line, ui, named, wrap_margin=12, beside=(forget_button, pick_button)).pack(side="left", fill="x")


def forget_server(app, server, rerender):
    """Forget a server, its sign-in and its app on this PC, after a question that names it."""
    w = app.words
    in_use = server["url"] == app.state.current
    if in_use and app.files_in_use():
        # Its app is downloading or playing, from this window or the command line.
        app.set_status(i18n.Said("online.busy"), "warn")
        return
    # The question short, the server it is about named in the line under it.
    if not dialogs.ask(app, "danger", w("online.forget.title"), w("online.forget.ask"),
                       w("online.forget.detail", name=server["name"]), w("online.forget")):
        return
    # The player's doing: a line kept about the server that goes gives way.
    app.user_acted()
    actions.forget(app.state, server["url"])
    if in_use:
        # What the last download and the last look said was about the server that is gone; the address field shows
        # the server in use now.
        app.download_error, app.app_note, app.address_draft = None, None, None
    app.state.save()
    app.refresh_checks()
    rerender()


def build_online(app, parent):
    rerender = lambda: app.page == "online" and app.go("online")  # noqa: E731  (the page drawn again)
    connect_panel(app, parent, rerender, forget=True)
    signin_panel(app, parent, rerender)
    app_panel(app, parent, rerender)
    known_servers(app, parent, rerender)


# ---------------------------------------------------------------------------------------------- Help


def build_help(app, parent):
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("help.checks"))
    # Check again at the title's right end: the server asked again too, whatever its last answer.
    widgets.Button(card.head, ui, w("help.recheck"), lambda: app.refresh_checks(force=True)).pack(side="right")
    app.check_box = tk.Frame(card.body, bg=theme.PANEL)
    app.check_box.pack(fill="x")
    app.refresh_checks()
    refresh_checks(app)
    card = _card(parent, ui, w("help.trouble"))
    # Each line with the page it names one press away.
    server = app.state.server()
    have = apps.local(server["url"]) if server else None
    # The first line points at the player's log below, which is there once the game has run with the app.
    log_file = player.app_log(have)
    has_log = bool(log_file and os.path.isfile(log_file))
    first = "help.trouble.1" if has_log else "help.trouble.1.none"
    for i, (key, page) in enumerate(((first, None), ("help.trouble.2", "screen"), ("help.trouble.3", "sound"),
                                     ("help.trouble.4", None))):
        if i:
            widgets.divider(card.body, ui, pady=9)
        line = tk.Frame(card.body, bg=theme.PANEL)
        line.pack(fill="x")
        beside = ()
        if page:
            # The page the line names, by the menu's own name, reached by the mouse or the keyboard.
            to = widgets.link(line, ui, TITLES[page], lambda p=page: app.nav_go(p))
            to.pack(side="right", anchor="n")
            beside = (to,)
        widgets.label(line, ui, w(key), wrap_margin=12, beside=beside).pack(side="left", fill="x")
    card = _card(parent, ui, w("help.tools"))
    if has_log:
        widgets.setting_row(card.body, ui, w("help.player_log"),
                            lambda p: widgets.Button(p, ui, w("common.open"), lambda: actions.show_file(log_file)),
                            w("help.player_log.hint")).pack(fill="x")
        widgets.divider(card.body, ui)
    # The launcher's log's folder: its older logs are there beside it.
    logs = os.path.dirname(st.launcher_log())
    widgets.setting_row(card.body, ui, w("help.logs"),
                        lambda p: widgets.Button(p, ui, w("common.open"), lambda: actions.open_folder(logs)),
                        w("help.logs.hint")).pack(fill="x")
    from opendmtq_client import installed
    root = installed.root()
    if root:
        # Only the installed launcher has a package to put its files back from.
        widgets.divider(card.body, ui)
        widgets.setting_row(card.body, ui, w("help.repair.row"),
                            lambda p: widgets.Button(p, ui, w("help.repair"), lambda: maintenance.repair_program(app)),
                            w("help.repair.hint")).pack(fill="x")
    # From the least to the most: the game's data, the launcher's, the program.
    card = _card(parent, ui, w("help.remove"), last=True)
    widgets.setting_row(card.body, ui, w("help.clear.row"),
                        lambda p: widgets.Button(p, ui, w("help.clear.confirm"), lambda: maintenance.clear_game_data(app),
                                                 kind="danger"),
                        w("help.clear.hint")).pack(fill="x")
    widgets.divider(card.body, ui)

    widgets.setting_row(card.body, ui, w("help.reset.row"),
                        lambda p: widgets.Button(p, ui, w("help.reset"), lambda: maintenance.start_over(app), kind="danger"),
                        w("help.reset.hint")).pack(fill="x")
    if root and installed.updater(root):
        # Velopack's uninstaller is what takes the program; a copied folder is deleted as any folder.
        widgets.divider(card.body, ui)
        widgets.setting_row(card.body, ui, w("help.uninstall.row"),
                            lambda p: widgets.Button(p, ui, w("help.uninstall"), lambda: maintenance.uninstall_program(app),
                                                     kind="danger"),
                            w("help.uninstall.hint")).pack(fill="x")


# --------------------------------------------------------------------------------------------- About


def language_options(app):
    """The language choices: Windows' own (no choice kept), English, Korean."""
    return [("system", app.words("about.language.system")), ("en", "English"), ("ko", "한국어")]


def build_about(app, parent):
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("about.general"))
    widgets.setting_row(card.body, ui, w("about.language"),
                        lambda p: widgets.Segmented(p, ui, language_options(app), app.state.picked_language or "system",
                                                    app.set_language)).pack(fill="x")
    card = _card(parent, ui, w("about.updates"))
    from opendmtq_client import __version__
    version = updates.current_version() or __version__
    box = tk.Frame(card.body, bg=theme.PANEL)
    box.pack(fill="x")
    widgets.label(box, ui, w("about.version", v=version), font=ui.fonts.body_bold).pack(side="left")
    # The answer and "Update to vX" under the version, taking room only once there is an answer.
    result = tk.Frame(card.body, bg=theme.PANEL)
    answer = widgets.label(result, ui, "", fg=theme.MUTED, wrap_margin=0)
    slot = tk.Frame(result, bg=theme.PANEL)

    # One look at a time: a second press while it asks does nothing.
    checking = {"now": False}

    def check():
        if checking["now"]:
            return
        checking["now"] = True
        for child in slot.winfo_children():
            child.destroy()
        answer.configure(text=w("about.checking"), fg=theme.MUTED)
        if not answer.winfo_manager():
            answer.pack(fill="x", pady=(ui.px(10), 0))
            slot.pack(fill="x")

        def work():
            result = updates.check()
            app.post(lambda: show(result))

        threading.Thread(target=work, daemon=True, name="updates").start()

    def show(result):
        checking["now"] = False
        if not answer.winfo_exists():
            return
        text = {
            "not_installed": w("about.not_installed"),
            "no_source": w("about.no_source"),
            "uptodate": w("about.uptodate"),
            # What failed and, by its kind, why: Velopack's own words are in the launcher's log (updates.check).
            "failed": w.failed("about.update_failed", result.error),
            "available": w("about.available", v=result.version),
        }[result.kind]
        answer.configure(text=text, fg=theme.BAD if result.kind == "failed" else theme.MUTED)
        if result.kind == "available":
            main_button(app, slot, w("about.update_now", v=result.version), lambda: update(result)).pack(
                anchor="w", pady=(ui.px(10), 0))

    def update(result):
        if not maintenance.update_launcher(app, result):
            # A game from this window or from the command line: the update replaces the player's files under it.
            answer.configure(text=w("about.update_busy"), fg=theme.WARN)

    widgets.Button(box, ui, w("about.check"), check).pack(side="left", padx=(ui.px(16), 0))
    result.pack(fill="x")
    card = _card(parent, ui, w("about.guide"))

    def rerun():
        app.state.guide_done = False
        app.state.save()
        app.show()

    widgets.Button(card.body, ui, w("about.guide.run"), rerun).pack(anchor="w")
    card = _card(parent, ui, w("about.legal"), last=True)
    for i, key in enumerate(("about.license", "about.notice")):
        if i:
            widgets.divider(card.body, ui, pady=9)
        widgets.label(card.body, ui, w(key), fg=theme.MUTED, wrap_margin=0).pack(fill="x")


BUILDERS = {
    "play": build_play, "screen": build_screen, "sound": build_sound, "controls": build_controls,
    "online": build_online, "help": build_help, "about": build_about,
}
