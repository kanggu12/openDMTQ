"""The launcher's pages. Each builder fills the page area; HEADERS gives each page's header words.

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

# ------------------------------------------------------------------------------------------- headers


def _plain_header(key):
    """A page header: the launcher's own kicker above the page's title (the title already names the page), then a line."""
    def words(app):
        return app.words("play.kicker"), app.words(key + ".title"), app.words(key + ".sub")
    return words


def _play_header(app):
    """PLAY's header: the game's name in chrome, and the server it plays on under it."""
    server = app.state.server()
    sub = app.words("play.on", name=server["name"]) if server else app.words("app.tagline")
    return app.words("play.kicker"), app.words("play.title"), sub


HEADERS = {"play": _play_header}
HEADERS.update({key: _plain_header(key) for key in ("screen", "sound", "controls", "online", "help", "about")})


def _gap(parent, ui, height=18):
    """Vertical space between blocks, in logical pixels."""
    tk.Frame(parent, bg=parent["bg"], height=ui.px(height)).pack(fill="x")


def _busy(app):
    """True while the game runs or PLAY or a download is under way: the server and its app stay as they are then."""
    return app.busy or app.download is not None or (app.session is not None and app.session.running())


# ---------------------------------------------------------------------------------------------- PLAY


def _server_card(app, parent):
    """Where PLAY plays: the server, the account signed in, and the app this PC has of it."""
    ui, w = app.ui, app.words
    card = widgets.Card(parent, ui)
    card.pack(fill="x", pady=(0, ui.px(16)))
    server = app.state.server()
    line = tk.Frame(card.body, bg=theme.PANEL)
    line.pack(fill="x")
    tk.Label(line, text=theme.ICON["server"], font=ui.fonts.icon, fg=ui.section["accent"], bg=theme.PANEL).pack(
        side="left", anchor="n")
    words = tk.Frame(line, bg=theme.PANEL)
    words.pack(side="left", fill="x", expand=True, padx=(ui.px(10), ui.px(12)))
    if server is None:
        widgets.label(words, ui, w("play.no_server"), fg=theme.WARN, bg=theme.PANEL, wrap_margin=0).pack(fill="x")
        widgets.Button(line, ui, w("play.connect"), lambda: app.go("online"), kind="primary", icon="online").pack(
            side="right")
        return
    widgets.label(words, ui, server["name"], font=ui.fonts.body_bold, bg=theme.PANEL, wrap_margin=0).pack(fill="x")
    widgets.label(words, ui, server["url"], font=ui.fonts.small, fg=theme.MUTED, bg=theme.PANEL, wrap_margin=0).pack(
        fill="x")
    signed = app.state.signed_in(server)
    account = (w("play.signed", account=server["account"]) if signed else
               w("play.not_signed", account=server["account"]) if server.get("account") else w("play.no_account"))
    widgets.label(words, ui, account, font=ui.fonts.small, fg=theme.MUTED if signed else theme.WARN, bg=theme.PANEL,
                  wrap_margin=0).pack(fill="x", pady=(ui.px(6), 0))
    if not signed:
        widgets.Button(line, ui, w("online.signin"), lambda: app.go("online"), icon="login").pack(side="right")


def build_play(app, parent):
    ui, w = app.ui, app.words
    _server_card(app, parent)
    row = tk.Frame(parent, bg=theme.BG)
    row.pack(fill="x")
    row.columnconfigure(0, weight=3, uniform="cards")
    row.columnconfigure(1, weight=2, uniform="cards")
    # Left: the ready check, filled in when the worker thread finishes it.
    ready = widgets.Card(row, ui)
    ready.grid(row=0, column=0, sticky="nsew", padx=(0, ui.px(16)))
    widgets.section(ready.body, ui, w("play.ready"), bg=theme.PANEL).pack(fill="x", pady=(0, ui.px(12)))
    app.check_box = tk.Frame(ready.body, bg=theme.PANEL)
    app.check_box.pack(fill="x")
    # Right: how to play, and how the last game went.
    how = widgets.Card(row, ui)
    how.grid(row=0, column=1, sticky="nsew")
    widgets.section(how.body, ui, w("play.how"), bg=theme.PANEL).pack(fill="x", pady=(0, ui.px(10)))
    for key in ("play.how.1", "play.how.2", "play.how.3"):
        widgets.label(how.body, ui, w(key), bg=theme.PANEL, fg=theme.TEXT, wrap_margin=0).pack(
            fill="x", pady=(0, ui.px(6)))
    _gap(how.body, ui, 10)
    widgets.section(how.body, ui, w("play.last"), bg=theme.PANEL).pack(fill="x", pady=(0, ui.px(10)))
    widgets.label(how.body, ui, _last_session(app), bg=theme.PANEL, fg=theme.MUTED, wrap_margin=0).pack(fill="x")
    record = app.state.last_session or {}
    if record.get("crashed") or record.get("failed_start"):
        # The reason is in the player's log: one press away from where it says the game stopped.
        widgets.Button(how.body, ui, w("status.open_log"), app.open_player_log, icon="file").pack(
            anchor="w", pady=(ui.px(10), 0))
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
    """Fill the ready check (PLAY page, Help page, the guide's last step) from app.checks."""
    box = getattr(app, "check_box", None)
    if box is None or not box.winfo_exists():
        return
    for child in box.winfo_children():
        child.destroy()
    ui, w = app.ui, app.words
    if app.checks is None:
        widgets.label(box, ui, "...", bg=theme.PANEL, fg=theme.MUTED).pack(anchor="w")
        return
    for check in app.checks:
        name = w("check." + check.key)
        if not check.ok and check.key == "player":
            # The player comes with the launcher: installing again brings it back, and no page here can.
            state, action = "bad", None
            name = "%s  ·  %s" % (name, w("check.player.missing"))
        elif check.ok:
            state, action = "ok", None
            # What it is about, which a player wants to confirm: the server, the account, the app's date. The PLAY
            # page's server card above already names the server and the account.
            about = ("app",) if app.page == "play" and app.guide is None else ("server", "account", "app")
            if check.key in about:
                name = "%s  ·  %s" % (name, check.detail)
        elif check.play_fixes:
            # PLAY does these by itself; the line only says it will.
            state, action = "change", None
            name = "%s  ·  %s" % (name, w("play.will_get"))
        else:
            state = "bad" if check.key in actions.BLOCKING else "change"
            action = (lambda p=check.page: app.go(p)) if check.page and app.guide is None else None
        widgets.check_line(box, ui, state, name, w("play.fix") if action else None, action).pack(
            fill="x", pady=(0, ui.px(7)))


# -------------------------------------------------------------------------------------------- Screen


def screen_rows(app, parent, redraw, full=True):
    """The Screen page's settings, which the guide's SOUND CHECK shows too (full=False: the ones a first start needs)."""
    ui, w, v = app.ui, app.words, app.state.values
    display = displays.main_display(app.root)
    widgets.section(parent, ui, w("screen.display")).pack(fill="x", pady=(0, ui.px(14)))
    mode = v["display"]

    def set_and_redraw(name):
        def setter(value):
            app.changed(name, value)
            # The rows and hints that follow depend on it: draw the page again.
            redraw()
        return setter

    widgets.setting_row(parent, ui, w("screen.mode"),
                        lambda p: widgets.Segmented(p, ui, [("fullscreen", w("screen.mode.fullscreen")),
                                                            ("window", w("screen.mode.window"))], mode,
                                                    set_and_redraw("display")),
                        w("screen.mode.hint." + mode)).pack(fill="x", pady=(0, ui.px(16)))
    if mode == "window" and full:
        # Sizes that fit the display with room for the title bar and the taskbar; fitted always stays.
        sizes = [s for s in choices.WINDOW_SIZES if s == "auto" or (choices.size_of(s)[0] <= display["width"] and
                                                                  choices.size_of(s)[1] + 80 <= display["height"])]
        if v["window"] not in sizes:
            # A size set on the command line keeps its row.
            sizes.append(v["window"])
        options = [(s, w("screen.size.auto") if s == "auto" else s.replace("x", " × ")) for s in sizes]
        widgets.setting_row(parent, ui, w("screen.size"),
                            lambda p: widgets.Select(p, ui, options, v["window"], lambda s: app.changed("window", s),
                                                     width=22),
                            w("screen.size.hint")).pack(fill="x", pady=(0, ui.px(16)))
    hz = display.get("hz")
    if full:
        widgets.label(parent, ui, w("screen.main", w=display["width"], h=display["height"]) + (
            w("screen.main.hz", hz=hz) if hz else ""), font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0).pack(
            fill="x", pady=(0, ui.px(16)))
        _gap(parent, ui, 6)
    widgets.section(parent, ui, w("screen.frames")).pack(fill="x", pady=(0, ui.px(14)))
    vsync = v["vsync"] == "on"
    widgets.setting_row(parent, ui, w("screen.vsync"),
                        lambda p: widgets.Toggle(p, ui, vsync,
                                                 lambda on: set_and_redraw("vsync")("on" if on else "off")),
                        w("screen.vsync.hint." + ("on" if vsync else "off"))).pack(fill="x", pady=(0, ui.px(16)))
    rate = w("screen.fps.auto.hz", hz=hz) if hz else w("screen.fps.auto")
    # The VSync hint about fractions of the rate only means something for a number of frames.
    numbered = v["fps"] not in ("auto", "unlimited")
    fps_hint = ("vsync" if numbered else "vsync_rate") if vsync else "free"
    options = [(f, rate if f == "auto" else w("screen.fps.unlimited") if f == "unlimited" else w("screen.fps.n", n=f))
               for f in choices.FPS]
    widgets.setting_row(parent, ui, w("screen.fps"),
                        lambda p: widgets.Select(p, ui, options, v["fps"], set_and_redraw("fps"), width=22),
                        w("screen.fps.hint." + fps_hint)).pack(fill="x", pady=(0, ui.px(16)))
    if not full:
        return
    _gap(parent, ui, 6)
    widgets.section(parent, ui, w("screen.picture")).pack(fill="x", pady=(0, ui.px(14)))
    options = [(s, w("screen.scale.full") if s == "100" else "%s%%" % s) for s in choices.RENDER_SCALE]
    widgets.setting_row(parent, ui, w("screen.scale"),
                        lambda p: widgets.Select(p, ui, options, v["render_scale"],
                                                 lambda s: app.changed("render_scale", s), width=22),
                        w("screen.scale.hint")).pack(fill="x", pady=(0, ui.px(16)))


def build_screen(app, parent):
    screen_rows(app, parent, lambda: app.go("screen"))


# --------------------------------------------------------------------------------------------- Sound


def sound_rows(app, parent, redraw, full=True):
    """The Sound page's settings, which the guide's SOUND CHECK shows too (full=False: the volume alone)."""
    ui, w, v = app.ui, app.words, app.state.values
    widgets.section(parent, ui, w("sound.volume")).pack(fill="x", pady=(0, ui.px(14)))
    widgets.setting_row(parent, ui, w("sound.volume.game"),
                        lambda p: widgets.Slider(p, ui, v["volume"], lambda val: app.changed("volume", val)),
                        w("sound.volume.hint")).pack(fill="x", pady=(0, ui.px(18)))
    if not full:
        return
    widgets.section(parent, ui, w("sound.output")).pack(fill="x", pady=(0, ui.px(14)))
    if app.devices is None:
        # Asked once from the player, on a worker thread; the page is drawn again with the answer.
        widgets.setting_row(parent, ui, w("sound.device"),
                            lambda p: widgets.label(p, ui, w("sound.device.looking"), fg=theme.MUTED)).pack(
            fill="x", pady=(0, ui.px(16)))
        app.load_devices(then=redraw)
    else:
        options = [("default", w("sound.device.default"))]
        options += [(d["id"], d["name"] + (w("sound.device.now_default") if d["default"] else "")) for d in app.devices]
        if v["audio_device"] != "default" and all(d["id"] != v["audio_device"] for d in app.devices):
            # A device chosen before that is not there now (unplugged): it stays chosen, and says so.
            options.append((v["audio_device"], w("sound.device.gone")))
        widgets.setting_row(parent, ui, w("sound.device"),
                            lambda p: widgets.Select(p, ui, options, v["audio_device"],
                                                     lambda d: app.changed("audio_device", d), width=34),
                            w("sound.device.hint" if app.devices else "sound.device.none")).pack(
            fill="x", pady=(0, ui.px(16)))

    def set_and_redraw(name):
        def setter(value):
            app.changed(name, value)
            redraw()
        return setter

    mode = v["audio_mode"]
    widgets.setting_row(parent, ui, w("sound.mode"),
                        lambda p: widgets.Segmented(p, ui, [("shared", w("sound.mode.shared")),
                                                            ("exclusive", w("sound.mode.exclusive"))], mode,
                                                    set_and_redraw("audio_mode")),
                        w("sound.mode.hint." + mode)).pack(fill="x", pady=(0, ui.px(16)))
    buffer = v["audio_buffer"]
    widgets.setting_row(parent, ui, w("sound.buffer"),
                        lambda p: widgets.Segmented(p, ui, [("low", w("sound.buffer.low")),
                                                            ("normal", w("sound.buffer.normal")),
                                                            ("safe", w("sound.buffer.safe"))], buffer,
                                                    set_and_redraw("audio_buffer")),
                        w("sound.buffer.hint." + buffer)).pack(fill="x", pady=(0, ui.px(16)))


def build_sound(app, parent):
    sound_rows(app, parent, lambda: app.page == "sound" and app.go("sound"))


# ------------------------------------------------------------------------------------------ Controls


def build_controls(app, parent):
    ui, w = app.ui, app.words
    for section, glyph, keys in (("controls.mouse", "controls", ("controls.click", "controls.drag", "controls.wheel")),
                                 ("controls.touch", "touch", ("controls.fingers", "controls.edges")),
                                 ("controls.keyboard", "keyboard", ("controls.esc", "controls.menu", "controls.f11", "controls.typing"))):
        widgets.section(parent, ui, w(section)).pack(fill="x", pady=(0, ui.px(12)))
        for key in keys:
            row = tk.Frame(parent, bg=theme.BG)
            row.pack(fill="x", pady=(0, ui.px(7)))
            mark = tk.Label(row, text=theme.ICON[glyph], font=ui.fonts.icon_small, fg=ui.section["accent"], bg=theme.BG)
            mark.pack(side="left", anchor="n")
            widgets.label(row, ui, w(key), wrap_margin=0, beside=(mark,)).pack(side="left", fill="x",
                                                                              padx=(ui.px(10), 0))
        _gap(parent, ui, 10)


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


def connect_panel(app, parent, rerender, bg=theme.BG):
    """The server: its address and Connect, and one line under them (server_line)."""
    ui, w = app.ui, app.words
    widgets.section(parent, ui, w("online.server"), bg=bg).pack(fill="x", pady=(0, ui.px(12)))
    row = tk.Frame(parent, bg=bg)
    row.pack(fill="x")
    tk.Label(row, text=w("online.address"), font=ui.fonts.small, fg=theme.MUTED, bg=bg).grid(row=0, column=0, sticky="w")
    address = widgets.entry(row, ui, width=34)
    address.grid(row=1, column=0, sticky="w", padx=(0, ui.px(12)), ipady=ui.px(4))
    server = app.state.server()
    address.insert(0, server["url"] if server else "")
    text, colour = server_line(app)
    answer = widgets.label(parent, ui, text, font=ui.fonts.small, fg=colour, bg=bg, wrap_margin=0)
    answer.pack(fill="x", pady=(ui.px(6), ui.px(12)))

    def connect():
        if _busy(app):
            answer.configure(text=w("online.busy"), fg=theme.WARN)
            return
        check_server(app, address.get(), then=rerender)
        # Said at once, before the server answers.
        answer.configure(text=w("online.connecting"), fg=theme.MUTED)

    address.bind("<Return>", lambda e: connect())
    widgets.Button(row, ui, w("online.connect"), connect, kind="primary", icon="online").grid(row=1, column=1, sticky="w")
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
    widgets.section(parent, ui, w("online.account"), bg=bg).pack(fill="x", pady=(ui.px(6), ui.px(12)))
    if app.state.signed_in(server):
        signed = tk.Frame(parent, bg=bg)
        signed.pack(fill="x")
        mark = tk.Label(signed, text=theme.ICON["ok"], font=ui.fonts.icon_small, fg=theme.OK, bg=bg)
        mark.pack(side="left")

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
            side="left", padx=(ui.px(8), 0))
        widgets.Button(signed, ui, w("online.signout"), sign_out, icon="logout").pack(side="left", padx=(ui.px(16), 0))
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
    widgets.Button(form, ui, w("online.signin"), sign_in, kind="primary", icon="login").grid(row=1, column=2, sticky="w")
    message.pack(fill="x", pady=(ui.px(8), 0))


def app_panel(app, parent, rerender, bg=theme.BG):
    """The server's app on this PC: what it has, what the server offers, and the download with its progress."""
    ui, w = app.ui, app.words
    server = app.state.server()
    if server is None:
        return
    widgets.section(parent, ui, w("online.app"), bg=bg).pack(fill="x", pady=(ui.px(10), ui.px(12)))
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
                   "secondary", icon="download").pack(side="left")


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
    widgets.section(parent, ui, w("online.others")).pack(fill="x", pady=(ui.px(14), ui.px(12)))
    for s in others:
        line = tk.Frame(parent, bg=theme.PANEL, padx=ui.px(14), pady=ui.px(8))
        line.pack(fill="x", pady=(0, ui.px(6)))

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

        def forget(url=s["url"], name=s["name"]):
            # The question short, the server it is about named in the line under it.
            if not dialogs.ask(app, "danger", w("online.forget.title"), w("online.forget.ask"),
                               w("online.forget.detail", name=name), w("online.forget")):
                return
            app.state.remove_server(url)
            apps.remove(url)
            app.state.save()
            app.refresh_checks()
            rerender()

        forget_button = widgets.Button(line, ui, w("online.forget"), forget, kind="danger", icon="delete")
        forget_button.pack(side="right")
        pick_button = widgets.Button(line, ui, w("online.pick"), pick)
        pick_button.pack(side="right", padx=(0, ui.px(8)))
        widgets.label(line, ui, "%s  ·  %s" % (s["name"], s["url"]), bg=theme.PANEL, wrap_margin=12,
                      beside=(forget_button, pick_button)).pack(side="left", fill="x")


def build_online(app, parent):
    rerender = lambda: app.page == "online" and app.go("online")  # noqa: E731  (the page drawn again)
    connect_panel(app, parent, rerender)
    signin_panel(app, parent, rerender)
    app_panel(app, parent, rerender)
    known_servers(app, parent, rerender)


# ---------------------------------------------------------------------------------------------- Help


def build_help(app, parent):
    ui, w = app.ui, app.words
    card = widgets.Card(parent, ui)
    card.pack(fill="x")
    head = tk.Frame(card.body, bg=theme.PANEL)
    head.pack(fill="x", pady=(0, ui.px(12)))
    widgets.section(head, ui, w("help.checks"), bg=theme.PANEL).pack(side="left", fill="x", expand=True)
    widgets.Button(head, ui, w("help.recheck"), app.refresh_checks, icon="refresh").pack(side="right",
                                                                                         padx=(ui.px(12), 0))
    app.check_box = tk.Frame(card.body, bg=theme.PANEL)
    app.check_box.pack(fill="x")
    app.refresh_checks()
    refresh_checks(app)
    _gap(parent, ui, 22)
    widgets.section(parent, ui, w("help.trouble")).pack(fill="x", pady=(0, ui.px(12)))
    # Each line with the page it names one press away.
    server = app.state.server()
    have = apps.local(server["url"]) if server else None
    # The first line points at the player's log below, which is there once the game has an app to run.
    first = "help.trouble.1" if have else "help.trouble.1.none"
    for key, page in ((first, None), ("help.trouble.2", "screen"), ("help.trouble.3", "sound"),
                      ("help.trouble.4", None)):
        line = tk.Frame(parent, bg=theme.BG)
        line.pack(fill="x", pady=(0, ui.px(6)))
        beside = ()
        if page:
            # The page the line names, reached by the mouse or the keyboard.
            to = widgets.link(line, ui, w("nav." + page), lambda p=page: app.nav_go(p))
            to.pack(side="right", anchor="n")
            beside = (to,)
        widgets.label(line, ui, w(key), wrap_margin=12, beside=beside).pack(side="left", fill="x")
    _gap(parent, ui, 14)
    widgets.section(parent, ui, w("help.tools")).pack(fill="x", pady=(0, ui.px(14)))
    if have:
        log_file = player.log_path(have["package"])
        widgets.setting_row(parent, ui, w("help.player_log"),
                            lambda p: widgets.Button(p, ui, w("common.open"), lambda: actions.open_folder(log_file),
                                                     icon="file"),
                            w("help.player_log.hint")).pack(fill="x", pady=(0, ui.px(16)))
    logs = os.path.join(st.config_dir(), "logs")
    widgets.setting_row(parent, ui, w("help.logs"),
                        lambda p: widgets.Button(p, ui, w("common.open"), lambda: actions.open_folder(logs),
                                                 icon="folder"),
                        w("help.logs.hint")).pack(fill="x", pady=(0, ui.px(16)))

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

    widgets.setting_row(parent, ui, w("help.reset"),
                        lambda p: widgets.Button(p, ui, w("help.reset"), start_over, kind="danger", icon="restore"),
                        w("help.reset.hint")).pack(fill="x", pady=(0, ui.px(16)))


# --------------------------------------------------------------------------------------------- About


def language_options(app):
    """The language choices: Windows' own (no choice kept), English, Korean."""
    return [("system", app.words("about.language.system")), ("en", "English"), ("ko", "한국어")]


def build_about(app, parent):
    ui, w = app.ui, app.words
    widgets.section(parent, ui, w("about.general")).pack(fill="x", pady=(0, ui.px(14)))
    widgets.setting_row(parent, ui, w("about.language"),
                        lambda p: widgets.Segmented(p, ui, language_options(app), app.state.picked_language or "system",
                                                    app.set_language)).pack(fill="x", pady=(0, ui.px(18)))
    widgets.section(parent, ui, w("about.updates")).pack(fill="x", pady=(0, ui.px(14)))
    from opendmtq_client import __version__
    version = updates.current_version() or __version__
    box = tk.Frame(parent, bg=theme.BG)
    box.pack(fill="x", pady=(0, ui.px(8)))
    widgets.label(box, ui, w("about.version", v=version), font=ui.fonts.body_bold).pack(side="left")
    # The answer and "Update to vX" under the version, taking room only once there is an answer.
    result = tk.Frame(parent, bg=theme.BG)
    answer = widgets.label(result, ui, "", fg=theme.MUTED, wrap_margin=0)
    slot = tk.Frame(result, bg=theme.BG)

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
            answer.pack(fill="x", pady=(ui.px(4), ui.px(10)))
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
                           kind="primary", icon="update").pack(anchor="w", pady=(0, ui.px(12)))

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

    widgets.Button(box, ui, w("about.check"), check, icon="update").pack(side="left", padx=(ui.px(16), 0))
    result.pack(fill="x", pady=(0, ui.px(4)))
    widgets.section(parent, ui, w("about.guide")).pack(fill="x", pady=(ui.px(4), ui.px(14)))

    def rerun():
        app.state.guide_done = False
        app.state.save()
        app.show()

    widgets.Button(parent, ui, w("about.guide.run"), rerun, icon="history").pack(anchor="w", pady=(0, ui.px(18)))
    widgets.section(parent, ui, w("about.legal")).pack(fill="x", pady=(0, ui.px(12)))
    for key in ("about.license", "about.notice"):
        widgets.label(parent, ui, w(key), fg=theme.MUTED, wrap_margin=0).pack(fill="x", pady=(0, ui.px(8)))


BUILDERS = {
    "play": build_play, "screen": build_screen, "sound": build_sound, "controls": build_controls,
    "online": build_online, "help": build_help, "about": build_about,
}
