"""The launcher's pages, as the site's: a title in the wide face and a line under it (heading), then cards. Each builder
fills the page's column.

A setting row changes the remembered state right away (app.changed); the player reads the settings at the next PLAY,
so nothing changes under a game that is running.
"""

import logging
import os
import threading
import tkinter as tk

from opendmtq_client import actions, apps, dialogs, displays, player, theme, updates, widgets
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


def _card(parent, ui, title, last=False):
    """A card with its title, stacked under the ones before it with the site's gap between cards."""
    card = widgets.Card(parent, ui, title)
    card.pack(fill="x", pady=(0, 0 if last else ui.px(CARD_GAP)))
    return card


# The gap between two cards (the site's --gap is 20 px; the window is smaller than a page).
CARD_GAP = 16


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


def _busy(app):
    """True while the game runs or PLAY or a download is under way: the server and its app stay as they are then."""
    return app.busy or app.download is not None or (app.session is not None and app.session.running())


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
        widgets.Button(line, ui, w("play.connect"), lambda: app.nav_go("online"), kind="primary").pack(side="right")
        return
    signed = app.state.signed_in(server)
    if not signed:
        widgets.Button(line, ui, w("online.signin"), lambda: app.nav_go("online"), kind="primary").pack(
            side="right", anchor="n")
    words = tk.Frame(line, bg=theme.PANEL)
    words.pack(side="left", fill="x", expand=True)
    widgets.label(words, ui, server["name"], font=ui.fonts.body_bold, wrap_margin=0).pack(fill="x")
    widgets.label(words, ui, server["url"], font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0).pack(fill="x")
    widgets.divider(card.body, ui)
    account = (w("play.signed", account=server["account"]) if signed else
               w("play.not_signed", account=server["account"]) if server.get("account") else w("play.no_account"))
    state = widgets.check_line(card.body, ui, "ok" if signed else "change", account)
    state.pack(fill="x")


def build_play(app, parent):
    ui, w = app.ui, app.words
    _server_card(app, parent)
    left, right = _columns(parent, ui)
    # Left: the ready check, filled in when the worker thread finishes it, as tall as the column.
    ready = widgets.Card(left, ui, w("play.ready"))
    ready.pack(fill="both", expand=True)
    app.check_box = tk.Frame(ready.body, bg=theme.PANEL)
    app.check_box.pack(fill="x")
    # Right: how to play, and how the last game went.
    how = _card(right, ui, w("play.how"))
    for i, key in enumerate(("play.how.1", "play.how.2", "play.how.3")):
        if i:
            widgets.divider(how.body, ui, pady=8)
        widgets.label(how.body, ui, w(key), wrap_margin=0).pack(fill="x")
    last = _card(right, ui, w("play.last"), last=True)
    widgets.label(last.body, ui, _last_session(app), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
    record = app.state.last_session or {}
    if record.get("crashed") or record.get("failed_start"):
        # The reason is in the player's log: one press away from where it says the game stopped.
        widgets.Button(last.body, ui, w("status.open_log"), app.open_player_log).pack(anchor="w", pady=(ui.px(12), 0))
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
    if app.checks is None:
        widgets.label(box, ui, "...", fg=theme.MUTED).pack(anchor="w")
        return
    from opendmtq_client import installed
    for i, check in enumerate(app.checks):
        if i:
            widgets.divider(box, ui, pady=9)
        name, value, action, fix = w("check." + check.key), None, None, w("play.fix")
        if not check.ok and check.key == "player" and installed.root():
            # The player comes with the launcher: the installed one puts it back from its package.
            state, fix, action = "bad", w("check.player.repair"), lambda: repair_program(app)
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
        # Sizes that fit the display with room for the title bar and the taskbar; fitted always stays.
        sizes = [s for s in choices.WINDOW_SIZES if s == "auto" or (choices.size_of(s)[0] <= display["width"] and
                                                                  choices.size_of(s)[1] + 80 <= display["height"])]
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
    # The VSync hint about fractions of the rate only means something for a number of frames.
    numbered = v["fps"] not in ("auto", "unlimited")
    fps_hint = ("vsync" if numbered else "vsync_rate") if vsync else "free"
    options = [(f, rate if f == "auto" else w("screen.fps.unlimited") if f == "unlimited" else w("screen.fps.n", n=f))
               for f in choices.FPS]
    widgets.divider(card.body, ui)
    widgets.setting_row(card.body, ui, w("screen.fps"),
                        lambda p: widgets.Select(p, ui, options, v["fps"], set_and_redraw("fps"), width=22),
                        w("screen.fps.hint." + fps_hint)).pack(fill="x")
    if not full:
        return
    card = _card(parent, ui, w("screen.picture"), last=True)
    options = [(s, w("screen.scale.full") if s == "100" else "%s%%" % s) for s in choices.RENDER_SCALE]
    widgets.setting_row(card.body, ui, w("screen.scale"),
                        lambda p: widgets.Select(p, ui, options, v["render_scale"],
                                                 lambda s: app.changed("render_scale", s), width=22),
                        w("screen.scale.hint")).pack(fill="x")


def build_screen(app, parent):
    screen_rows(app, parent, lambda: app.go("screen"))


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
    sound_rows(app, parent, lambda: app.page == "sound" and app.go("sound"))


# ------------------------------------------------------------------------------------------ Controls


def build_controls(app, parent):
    ui, w = app.ui, app.words
    groups = (("controls.mouse", ("controls.click", "controls.drag", "controls.wheel")),
              ("controls.touch", ("controls.fingers", "controls.edges")),
              ("controls.keyboard", ("controls.esc", "controls.menu", "controls.f11", "controls.typing")))
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
        return check["text"], theme.BAD
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
            actions.connect(app.state, address)
            app.post(lambda: answered({"url": app.state.current, "state": "ok"}))
        except Exception as e:  # noqa: BLE001  (ServerError, or anything else: shown, never a silent stop)
            # The system's own words for it go to the log; the window says it plainly.
            log.info("could not connect to %s: %s", address, e)
            app.post(lambda text=w.error(e): answered({"url": address, "state": "failed", "text": text}))

    def answered(check):
        app.server_check = check
        if check["state"] == "ok":
            # Another server, or the same one again: what the last download said is not about it.
            app.download_error, app.app_note = None, None
            app.user_acted()
            app.state.save()
            app.refresh_checks()
        if then:
            then()

    threading.Thread(target=work, daemon=True, name="connect").start()


def connect_panel(app, parent, rerender, bg=theme.BG, forget=False):
    """The server's card: its address and Connect, and one line under them (server_line). With `forget`, the server in
    use can be forgotten there too (the Online page; the guide only connects)."""
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("online.server"))
    parent, bg = card.body, theme.PANEL
    row = tk.Frame(parent, bg=bg)
    row.pack(fill="x")
    tk.Label(row, text=w("online.address"), font=ui.fonts.small, fg=theme.MUTED, bg=bg).grid(row=0, column=0, sticky="w")
    address = widgets.entry(row, ui, width=34)
    address.grid(row=1, column=0, sticky="w", padx=(0, ui.px(12)), ipady=ui.px(4))
    server = app.state.server()
    address.insert(0, server["url"] if server else "")
    text, colour = server_line(app)
    answer = widgets.label(parent, ui, text, font=ui.fonts.small, fg=colour, bg=bg, wrap_margin=0)
    answer.pack(fill="x", pady=(ui.px(8), 0))

    def connect():
        if _busy(app):
            answer.configure(text=w("online.busy"), fg=theme.WARN)
            return
        check_server(app, address.get(), then=rerender)
        # Said at once, before the server answers.
        answer.configure(text=w("online.connecting"), fg=theme.MUTED)

    address.bind("<Return>", lambda e: connect())
    widgets.Button(row, ui, w("online.connect"), connect, kind="primary").grid(row=1, column=1, sticky="w")
    if server and forget:
        # After Connect, apart from it: the next server this launcher knows becomes the one PLAY plays on.
        widgets.Button(row, ui, w("online.forget"), lambda: forget_server(app, server, rerender),
                       kind="danger").grid(row=1, column=2, sticky="w", padx=(ui.px(8), 0))
    if not server:
        # Not connected yet: typing goes to the address, Enter connects.
        address.after_idle(address.focus_set)
    return address


def signin_panel(app, parent, rerender, bg=theme.BG):
    """The sign-in on the current server: who is signed in and Sign out, or the ID and password and Sign in."""
    ui, w = app.ui, app.words
    server = app.state.server()
    if server is None:
        return
    card = _card(parent, ui, w("online.account"))
    parent, bg = card.body, theme.PANEL
    if app.state.signed_in(server):
        signed = tk.Frame(parent, bg=bg)
        signed.pack(fill="x")
        widgets.lamp(signed, ui, theme.OK, bg=bg).pack(side="left")

        def sign_out():
            if _busy(app):
                # The download or the game uses the sign-in now: it stays until they are over.
                app.set_status(w("online.busy"), "warn")
                return
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
        field = widgets.entry(form, ui, width=16, secret=secret)
        field.grid(row=1, column=col, sticky="w", padx=(0, ui.px(12)), ipady=ui.px(4))
        fields[key] = field
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
                actions.sign_in(app.state, user, password)
                app.post(signed_in)
            except Exception as e:  # noqa: BLE001
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
        app.state.save()
        app.refresh_checks()
        rerender()

    for field in fields.values():
        field.bind("<Return>", lambda e: sign_in())
    # Typing goes to the first empty field; Tab to the next; Enter signs in.
    first = fields["online.password"] if server.get("account") else fields["online.id"]
    first.after_idle(first.focus_set)
    widgets.Button(form, ui, w("online.signin"), sign_in, kind="primary").grid(row=1, column=2, sticky="w")
    message.pack(fill="x", pady=(ui.px(8), 0))


def app_panel(app, parent, rerender, bg=theme.BG):
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
        widgets.label(parent, ui, app.app_note, font=ui.fonts.small, fg=theme.MUTED, bg=bg, wrap_margin=0).pack(
            fill="x", pady=(0, ui.px(10)))
    if app.download is None and app.download_error:
        # What the last try said (a stop, a sign-in that ended, a line that broke), in the same colour as the status
        # line says it: the guide has no status line to say it.
        said, tone = app.download_error
        widgets.label(parent, ui, said, font=ui.fonts.small, fg=theme.WARN if tone == "warn" else theme.BAD, bg=bg,
                      wrap_margin=0).pack(fill="x", pady=(0, ui.px(10)))
    if app.download is not None:
        # The download under way: its bar, kept moving by the app (app._download_moved), and Cancel.
        bar = widgets.Progress(parent, ui, bg=bg)
        bar.pack(anchor="w", pady=(0, ui.px(10)))
        done, total = app.download["done"], app.download["total"]
        bar.set(done / float(total) if total else None, w("status.app_check") if not total else
                w("status.downloading", done="%.1f" % (done / 1048576.0), total="%.1f" % (total / 1048576.0)))
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
    widgets.Button(buttons, ui, words, lambda: _get(app, rerender), kind="primary" if not have or newer else
                   "secondary").pack(side="left")


def _date(details):
    """The day an app was built, as its server said ('2026-11-08'); its file name when it said none."""
    built = str((details or {}).get("built_at") or "")
    return built[:10] if built else str((details or {}).get("file") or "")


def _get(app, rerender):
    """Ask the server for its app and download it when this PC lacks it; the page shows the progress."""
    if _busy(app):
        app.set_status(app.words("online.busy"), "warn")
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
            if _busy(app):
                app.set_status(w("online.busy"), "warn")
                return
            app.state.current = url
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
        widgets.label(line, ui, "%s  ·  %s" % (s["name"], s["url"]), wrap_margin=12,
                      beside=(forget_button, pick_button)).pack(side="left", fill="x")


def forget_server(app, server, rerender):
    """Forget a server, its sign-in and its app on this PC, after a question that names it."""
    w = app.words
    in_use = server["url"] == app.state.current
    if in_use and _busy(app):
        # Its app is downloading or playing.
        app.set_status(w("online.busy"), "warn")
        return
    # The question short, the server it is about named in the line under it.
    if not dialogs.ask(app, "danger", w("online.forget.title"), w("online.forget.ask"),
                       w("online.forget.detail", name=server["name"]), w("online.forget")):
        return
    app.state.remove_server(server["url"])
    apps.remove(server["url"])
    if in_use:
        # What the last download and the last look said was about the server that is gone.
        app.download_error, app.app_note = None, None
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
    # Check again at the title's right end.
    widgets.Button(card.head, ui, w("help.recheck"), app.refresh_checks).pack(side="right")
    app.check_box = tk.Frame(card.body, bg=theme.PANEL)
    app.check_box.pack(fill="x")
    app.refresh_checks()
    refresh_checks(app)
    card = _card(parent, ui, w("help.trouble"))
    # Each line with the page it names one press away.
    server = app.state.server()
    have = apps.local(server["url"]) if server else None
    # The first line points at the player's log below, which is there once the game has run with the app.
    log_file = player.log_path(have["package"]) if have else None
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
    logs = os.path.join(st.config_dir(), "logs")
    widgets.setting_row(card.body, ui, w("help.logs"),
                        lambda p: widgets.Button(p, ui, w("common.open"), lambda: actions.open_folder(logs)),
                        w("help.logs.hint")).pack(fill="x")
    from opendmtq_client import installed
    root = installed.root()
    if root:
        # Only the installed launcher has a package to put its files back from.
        widgets.divider(card.body, ui)
        widgets.setting_row(card.body, ui, w("help.repair"),
                            lambda p: widgets.Button(p, ui, w("help.repair"), lambda: repair_program(app)),
                            w("help.repair.hint")).pack(fill="x")
    # From the least to the most: the game's data, the launcher's, the program.
    card = _card(parent, ui, w("help.remove"), last=True)
    widgets.setting_row(card.body, ui, w("help.clear"),
                        lambda p: widgets.Button(p, ui, w("help.clear.confirm"), lambda: clear_game_data(app),
                                                 kind="danger"),
                        w("help.clear.hint")).pack(fill="x")
    widgets.divider(card.body, ui)

    def start_over():
        if _busy(app):
            app.set_status(w("help.reset.busy"), "warn")
            return
        if not dialogs.ask(app, "danger", w("help.reset.title"), w("help.reset.ask"), w("help.reset.detail"),
                           w("help.reset.confirm"), glyph="restore"):
            return
        for s in list(app.state.servers):
            apps.remove(s["url"])
        fresh = st.LauncherState()
        # The language stays as it was, chosen or Windows': the guide that follows speaks it.
        fresh.picked_language = app.state.picked_language
        app.state.__dict__.update(fresh.__dict__)
        app.state.save()
        app.devices = None
        app.page = "play"
        app.show()

    widgets.setting_row(card.body, ui, w("help.reset"),
                        lambda p: widgets.Button(p, ui, w("help.reset"), start_over, kind="danger"),
                        w("help.reset.hint")).pack(fill="x")
    if root and installed.updater(root):
        # Velopack's uninstaller is what takes the program; a copied folder is deleted as any folder.
        widgets.divider(card.body, ui)
        widgets.setting_row(card.body, ui, w("help.uninstall"),
                            lambda p: widgets.Button(p, ui, w("help.uninstall"), lambda: uninstall_program(app),
                                                     kind="danger"),
                            w("help.uninstall.hint")).pack(fill="x")


def _in_background(app, message, glyph, job, then):
    """Run job() on a worker thread under a dialog that says what is under way, then then(result, error) on the
    window's thread with the dialog gone. The window is not closed meanwhile: the work would stop half done."""
    app.dialog = dialogs.Dialog(app.root, app.ui, "info", message, message, progress=True, glyph=glyph)
    app.updating = True

    def work():
        try:
            result, error = job(), None
        except Exception as e:  # noqa: BLE001  (shown in a dialog, never swallowed)
            log.exception("%s failed", job.__name__)
            result, error = None, e
        app.post(lambda: finished(result, error))

    def finished(result, error):
        app.updating = False
        if app.dialog is not None:
            app.dialog.close(None)
            app.dialog = None
        then(result, error)

    threading.Thread(target=work, daemon=True, name=job.__name__).start()


def _not_now(app):
    """True, said on the status line, while the game runs or PLAY or a download is under way: the files these tools
    change are in use then. A game started from the command line counts too."""
    from opendmtq_client import playing
    if _busy(app) or playing.running():
        app.set_status(app.words("help.reset.busy"), "warn")
        return True
    return False


def repair_program(app):
    """Repair: the program's files compared with the installed package, what is missing or changed put back."""
    from opendmtq_client import repair
    w = app.words
    if _not_now(app):
        return

    def done(result, error):
        if error is not None:
            dialogs.tell(app, "error", w("help.repair"), w("help.repair.failed"), w.error(error))
        elif result.failed:
            dialogs.tell(app, "warn", w("help.repair"), w("help.repair.partly"),
                         w("help.repair.partly.detail", n=result.restored, failed=len(result.failed)))
        elif result.restored:
            # The running launcher goes on with the files it loaded; its next start reads the ones put back.
            detail = "help.repair.done.restart" if result.needs_restart else "help.repair.done.detail"
            dialogs.tell(app, "info", w("help.repair"), w("help.repair.done"), w(detail, n=result.restored))
        else:
            dialogs.tell(app, "info", w("help.repair"), w("help.repair.fine"),
                         w("help.repair.fine.detail", n=result.checked))
        # The player may be back.
        app.refresh_checks()

    _in_background(app, w("help.repair.working"), "restore", repair.run, done)


def clear_game_data(app):
    """Clear game data: the games' folders emptied but for the id this PC plays by, after a question that says how
    much goes."""
    from opendmtq_client import removal
    w = app.words
    if _not_now(app):
        return
    # Counted at the press: the game adds to its data each time it runs.
    size = removal.game_data_size()
    if not size:
        app.set_status(w("help.clear.none"), "normal", transient=True)
        return
    said = removal.megabytes(size)
    if not dialogs.ask(app, "danger", w("help.clear"), w("help.clear.ask"), w("help.clear.detail", size=said),
                       w("help.clear.confirm"), glyph="delete"):
        return

    def done(failed, error):
        if error is not None:
            dialogs.tell(app, "error", w("help.clear"), w("help.clear.partly"), w.error(error))
        elif failed:
            dialogs.tell(app, "warn", w("help.clear"), w("help.clear.partly"),
                         w("help.clear.partly.detail", n=len(failed), path=failed[0]))
        # The player's log went with the rest: its row comes back once the game has run.
        if app.page == "help":
            app.go("help")
        if error is None and not failed:
            # Said after the page is drawn again, whose ready check would otherwise take the line at once.
            app.set_status(w("help.clear.done", size=said), "ok", sticky=True)

    _in_background(app, w("help.clear.working"), "delete", removal.clear_game_data, done)


def uninstall_program(app):
    """Uninstall: a question with two ways, the data kept or deleted with the program; then Velopack's uninstaller
    starts and the window closes for it."""
    from opendmtq_client import removal
    w = app.words
    if _not_now(app):
        return
    size = removal.megabytes(removal.everything_size())
    # Cancel first and the ring on it: Enter alone removes nothing.
    choice = dialogs.choose(app, "danger", w("help.uninstall"), w("help.uninstall.ask"),
                            w("help.uninstall.detail", size=size),
                            [(w("help.uninstall.keep"), "keep", "warn"), (w("help.uninstall.all"), "all", "danger")],
                            glyph="delete")

    def start():
        try:
            removal.uninstall()
        except Exception as e:  # noqa: BLE001  (Update.exe that did not start: said, and the window stays)
            log.exception("the uninstaller did not start")
            dialogs.tell(app, "error", w("help.uninstall"), w("help.uninstall.failed"),
                         w("help.uninstall.failed.detail", error=w.error(e)))
            return
        app.leave()

    def deleted(failed, error):
        if error is not None:
            # Nothing is uninstalled after a deletion that stopped half way: the player can choose again.
            dialogs.tell(app, "error", w("help.uninstall"), w("help.uninstall.failed"), w.error(error))
            return
        if failed:
            dialogs.tell(app, "warn", w("help.uninstall"), w("help.uninstall.left"),
                         w("help.uninstall.left.detail", n=len(failed), folder=removal.data_root()))
        start()

    if choice == "keep":
        # Written before the uninstaller starts: it closes what runs from the program's folder, this window too.
        app.state.save()
        start()
    elif choice == "all":
        _in_background(app, w("help.uninstall.working"), "delete", removal.delete_everything, deleted)


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
            "failed": w("about.update_failed", error=result.error),
            "available": w("about.available", v=result.version),
        }[result.kind]
        answer.configure(text=text, fg=theme.BAD if result.kind == "failed" else theme.MUTED)
        if result.kind == "available":
            widgets.Button(slot, ui, w("about.update_now", v=result.version), lambda: update(result),
                           kind="primary").pack(anchor="w", pady=(ui.px(10), 0))

    def update(result):
        from opendmtq_client import playing
        # A game from this window or from the command line: the update replaces the player's files under it.
        if _busy(app) or playing.running():
            # The update replaces the player's files: a game playing from them would lose them mid-song.
            answer.configure(text=w("about.update_busy"), fg=theme.WARN)
            return
        # The launcher's own dialog says what happens while the update downloads; then the launcher closes and Velopack
        # puts the update in without a window of its own and starts the new launcher.
        app.dialog = dialogs.Dialog(app.root, app.ui, "info", w("about.updating.title"),
                                    w("about.updating.message", v=result.version), w("about.updating.detail"),
                                    progress=True, glyph="update")

        # The window stays until the update is in Velopack's hands: closing it now would end the download.
        app.updating = True

        def work():
            try:
                updates.apply(result)
            except Exception as e:  # noqa: BLE001  (shown, never swallowed)
                log.exception("the update failed")
                app.post(lambda text=str(e): failed(text))
                return
            log.info("closing for the update to %s", result.version)
            app.post(done)

        def done():
            app.updating = False
            app.close()

        def failed(text):
            app.updating = False
            if app.dialog is not None:
                app.dialog.close(None)
                app.dialog = None
            dialogs.tell(app, "error", w("about.update_failed.title"), w("about.apply_failed", error=text))

        threading.Thread(target=work, daemon=True, name="update").start()

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
