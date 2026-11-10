"""The launcher window: the menu column, the page header, the page, and the bottom bar with PLAY.

Slow work (asking the server, downloading its app, listing the sound devices, update checks) runs on worker threads;
they hand results back through a queue the window empties every 50 ms, because Tk may only be touched from the thread
that created it.
"""

import logging
import os
import queue
import threading
import tkinter as tk

from opendmtq_client import __version__, actions, art, i18n, player, safety, theme, widgets
from opendmtq_client import server as srv
from opendmtq_client import state as st

log = logging.getLogger("opendmtq_client")

# The menu, left to right, in English in both languages as the site's and the game's menus are.
NAV = ("play", "screen", "sound", "controls", "online", "help", "about")
NAV_WORDS = {"play": "PLAY", "screen": "SCREEN", "sound": "SOUND", "controls": "CONTROLS", "online": "ONLINE",
             "help": "HELP", "about": "LAUNCHER"}
# The room at the window's left and right ends (logical pixels), the same in the guide.
EDGE = 28
# The bottom bar's height inside its padding: PLAY's slab and its keyboard ring, on every page and every guide step.
BAR_HEIGHT = 54
# How often the window looks for a server an installer left while it is open, in turns of the 50 ms task pump (2 s).
PRESET_EVERY = 40


class LauncherApp:
    """The whole launcher: owns the Tk root, the remembered state and the game while it runs."""

    def __init__(self, state, root=None):
        # The launcher's own window: never on a real screen from a test.
        safety.refuse_windows_in_tests("the launcher window")
        self.state = state
        # Fonts must be registered before Tk measures any text.
        theme.register_fonts()
        self.root = root or tk.Tk()
        self.root.title("OpenDMTQ")
        self.root.configure(bg=theme.BG)
        # The mark in the title bar and on the taskbar, in place of Tk's feather.
        from opendmtq_client import dialogs
        dialogs.set_icon(self.root)
        self.tasks = queue.Queue()      # functions from worker threads, run on the Tk thread
        self.session = None             # the running game, while it runs
        self.checks = None              # the last ready check (None: being made)
        self.page = "play"              # the page on show
        self.busy = False               # PLAY is getting ready (asking the server, downloading its app)
        self.status_text, self.status_tone = "", "normal"
        self.status_sticky = False      # a message that stays until the player does something (an update's outcome, a
        #                                 sign-in that ended, a stopped download): the ready check does not replace it
        self.quit_after_game = False    # the window was closed while the game ran
        self.dialog = None              # the dialog on show (dialogs.py), while one is
        self.devices = None             # the sound devices the player lists (None: not asked yet)
        self.download = None            # the app's download under way: {"done", "total", "cancel"}
        self.download_bar = None        # the page's progress bar for it, while one is on show
        self.download_error = None      # (words, tone) of the last download that did not end well (the page shows it)
        self.app_note = None            # what the last look for a newer app found when it found none (the page shows it)
        self.status_transient = False   # the status line says something passing, which the ready check may replace
        self.status_action = None       # (words, function): a link after the status line, or None
        self.updating = False           # the launcher's own update or a repair is under way (the window stays until then)
        self.play_offline = False       # PLAY went on with this PC's app because the server did not answer
        self.server_check = None        # the last time a server was asked in this run: {"url", "state", "text"}
        self.pumps = 0                  # turns of the task pump, for the slower look for an installer's server
        self._setup_fonts()
        self._size_window()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        # A step of the window that fails is said in the launcher's own dialog, never silently.
        self.root.report_callback_exception = self.step_failed
        self.failure_said = False       # the first such failure of this run was said (the next ones go to the log)
        # Shown again while a game runs (the window was closed, then OpenDMTQ started again): it stays after the game.
        self.root.bind("<Map>", self._mapped, add="+")
        self.root.after(50, self._pump)
        self.show()
        self._update_outcome()

    # --------------------------------------------------------------------------------------- frame

    def _setup_fonts(self):
        """Fonts, words and DPI scale for the current language (a language change rebuilds them)."""
        self.scale = theme.scale_of(self.root)
        self.words = i18n.Words(self.state.language)
        self.fonts = theme.Fonts(self.root, self.state.language)
        self.ui = widgets.Ui(self.root, self.fonts, self.scale, self.words)
        widgets.style_ttk(self.ui)

    def _size_window(self):
        """1180x760 at 100 % scaling, never more than 92 % of the screen, centred."""
        px = self.ui.px
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(px(1180), int(sw * 0.92)), min(px(760), int(sh * 0.92))
        self.root.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, max(0, (sh - h) // 3)))
        self.root.minsize(min(px(960), w), min(px(640), h))

    def show(self):
        """Build the guide on a first start, else the launcher itself."""
        for child in self.root.winfo_children():
            child.destroy()
        # The page's progress bar went with the widgets: the download's progress waits for the next one.
        self.download_bar = None
        if not self.state.guide_done:
            from opendmtq_client import guide
            self.guide = guide.Guide(self)
            self.guide.build()
            return
        self.guide = None
        self._build_main()
        self.go(self.page)
        self.refresh_checks()

    def _build_main(self):
        ui, px = self.ui, self.ui.px
        # ---- the header bar: the wordmark and the version, then the menu (as the site's top bar)
        self.header = self.make_header(self.root, nav=[(key, NAV_WORDS[key]) for key in NAV], on_nav=self.nav_go)
        # ---- the strip along the foot: what is going on at the left, PLAY at the right
        bottom = tk.Frame(self.root, bg=theme.STRIP)
        bottom.pack(side="bottom", fill="x")
        # One height whatever it holds, as the guide's bar.
        bar = tk.Frame(bottom, bg=theme.STRIP, height=px(BAR_HEIGHT))
        bar.pack(fill="x", padx=px(EDGE), pady=px(12))
        bar.pack_propagate(False)
        # PLAY: the lime slab on the bar's own colour, the same as the guide's last step shows.
        self.play_button = widgets.PlaySlab(bar, ui, self.words("bottom.play"), self.play)
        self.play_button.pack(side="right")
        # The status's lamp in its tone's colour, then its words.
        from PIL import ImageTk
        self._status_lamps = {tone: art.lamp(colour, self.scale, bg=theme.STRIP) for tone, colour in
                              (("normal", theme.FAINT), ("ok", theme.OK), ("warn", theme.WARN), ("bad", theme.BAD))}
        self._status_images = {tone: ImageTk.PhotoImage(p, master=self.root) for tone, p in self._status_lamps.items()}
        self.status_glyph = tk.Label(bar, image=self._status_images["normal"], bg=theme.STRIP, bd=0)
        self.status_glyph.pack(side="left")
        self.status_label = tk.Label(bar, text="", font=self.fonts.body, fg=theme.MUTED, bg=theme.STRIP,
                                     justify="left", anchor="w", wraplength=px(560))
        self.status_label.pack(side="left", padx=(px(4), px(12)))
        # A link after the words when there is something to open (the player's log after a crash): the words and the
        # chevron come with the message (_paint_status).
        self.status_link = widgets.link(bar, ui, "", lambda: self.status_link.odq_action and self.status_link.odq_action(),
                                        fg=theme.TEXT, bg=theme.STRIP, chevron=False)
        self.status_link.odq_action = None
        # ---- the page: its title and its cards over the site's field (widgets.ScrollArea)
        self.body = self.make_page(self.root, self.header)
        self._paint_status()

    def make_header(self, parent, nav=(), on_nav=None, link=None, steps=()):
        """The bar across the window's top, as the site's (widgets.Header): the wordmark with PC after it and the
        version beside it (art.brand), then the menu; the guide's has its steps under them instead."""
        header = widgets.Header(parent, self.ui, art.brand(self.scale, "v" + __version__), nav=nav, on_nav=on_nav,
                                link=link, steps=steps)
        header.pack(side="top", fill="x")
        return header

    def make_page(self, parent, header):
        """The page area under a header: the page's backdrop goes on from where the header's ends, and the header turns
        into the dark bar once the page has moved."""
        page = widgets.ScrollArea(parent, self.ui, offset=int(header.cget("height")),
                                  light=self.ui.px(widgets.Header.HEIGHT) + self.ui.px(widgets.Header.LIGHT),
                                  on_moved=header.set_under)
        page.pack(fill="both", expand=True)
        return page

    def user_acted(self):
        """The player did something: a message kept until then (status_sticky) may give way now."""
        self.status_sticky = False

    def nav_go(self, page):
        """A page chosen from the menu (a click, or Enter or Space)."""
        self.user_acted()
        self.go(page)

    # -------------------------------------------------------------------------------------- PLAY

    def _paint_play(self):
        """PLAY follows the state: PLAYING while the game is open, waiting while it gets ready, downloads or has
        something to fix first, else lit (widgets.PlaySlab lights it further under the mouse)."""
        if not hasattr(self, "play_button") or not self.play_button.winfo_exists():
            # The guide is on show: it has no PLAY bar.
            return
        if self._game_open():
            self.play_button.set("playing", self.words("bottom.playing"))
        elif self.busy_now() or not self.ready():
            self.play_button.set("waiting", self.words("bottom.play"))
        else:
            self.play_button.set("ready", self.words("bottom.play"))

    def _game_open(self):
        """The game this window started is running."""
        return self.session is not None and self.session.running()

    def busy_now(self):
        """True while PLAY gets ready, the app downloads or the game this window started runs: the server, its sign-in
        and its app stay as they are until then."""
        return self.busy or self.download is not None or self._game_open()

    def files_in_use(self):
        """True while busy_now(), and while a game started from the command line runs (playing.py): the player's
        files, the servers' apps and the game's data, which Repair, Clear game data, Uninstall, Start over and Forget
        change or delete, are in use then."""
        from opendmtq_client import playing
        return self.busy_now() or playing.running()

    def ready(self):
        """True when nothing stops PLAY (the player, a server, its app or a sign-in to get it, no game running)."""
        if not self.checks:
            return self.state.server() is not None
        return actions.can_play(self.checks)

    def play(self):
        """Get the newest app on a worker thread when the server can be asked, then start the game."""
        if self.busy_now():
            return
        self.user_acted()
        if not self.ready():
            self.set_status(self.words("status.fix_first"), "warn")
            self._paint_play()
            return
        self.busy = True
        self.play_offline = False
        self._paint_play()
        self.set_status(self.words("status.app_check"), "normal")
        # PLAY's own download is the app's download like any other: its bar and Cancel on the Online page.
        cancel = threading.Event()

        def report(step, done=None, total=None):
            # Each step in order through the window's queue, so "offline" is known before "starting" is shown.
            if step == "download":
                self.post(lambda: self._play_downloading(done, total, cancel))
            elif step == "offline":
                self.post(lambda: setattr(self, "play_offline", True))
            else:
                self.post(lambda: self._play_step(step))

        def work():
            try:
                session = actions.play(self.state, report=report, cancel=cancel)
                self.post(lambda: self._started(session))
            except srv.Cancelled:
                log.info("PLAY's download was stopped")
                self.post(self._play_cancelled)
            except srv.SignedOut:
                log.info("the server no longer takes the sign-in, and this PC has no app")
                self.post(self._signed_out)
            except Exception as e:  # noqa: BLE001  (any failure is shown, never swallowed)
                log.exception("PLAY failed")
                # Python forgets e when the except block ends; the message is taken now, the window shows it later.
                self.post(lambda error=e: self._failed(error))

        threading.Thread(target=work, daemon=True, name="play").start()

    def _play_step(self, step):
        """What PLAY is doing now, on the status line."""
        if step == "app":
            self.set_status(self.words("status.app_check"), "normal")
        else:
            # Starting: with this PC's app, said so, when the server did not answer.
            self.set_status(self.words("status.offline" if self.play_offline else "status.starting"),
                            "warn" if self.play_offline else "normal")

    def _play_downloading(self, done, total, cancel):
        """PLAY is downloading the app: the same download state as Online's button, so its page shows the bar and
        Cancel, and the status line its progress."""
        if self.download is None:
            self.download = {"done": 0, "total": total, "cancel": cancel, "before": None}
            self.download_error, self.app_note = None, None
            self._paint_play()
            if self.guide is None and self.page == "online":
                # The page draws the bar and Cancel for it.
                self.go("online")
        self._download_moved(done, total)

    def _play_cancelled(self):
        """PLAY's download was stopped: nothing started, and the page and the status line say so alike."""
        self.busy = False
        self.download = None
        self.download_error = (self.words("status.download_cancelled"), "warn")
        self.set_status(self.download_error[0], "warn", sticky=True)
        self._paint_play()
        self.refresh_checks()
        if self.guide is None and self.page in ("online", "play"):
            self.go(self.page)

    def _started(self, session):
        from opendmtq_client import playing
        self.busy = False
        self.session = session
        # A download PLAY made is over and in place.
        self.download, self.download_error = None, None
        self.state.save()
        # The installer waits while this is held: replacing the player's files now would pull them from under the game.
        playing.hold()
        if self.play_offline:
            # Said until the game ends: the app may be older than the server's.
            self.set_status(self.words("status.offline"), "warn", sticky=True)
        else:
            self.set_status(self.words("status.playing"), "ok")
        self._paint_play()
        # Out of the way while the game has the screen; it comes back when the game closes.
        self.root.iconify()
        self.root.after(1000, self._watch)

    def _watch(self):
        if self._game_open():
            self.root.after(1000, self._watch)
            return
        from opendmtq_client import playing
        playing.release()
        record = actions.finish(self.state, self.session)
        self.state.save()
        self.session = None
        if self.quit_after_game:
            # The window was closed while the game ran: it goes now.
            self.root.destroy()
            return
        self.root.deiconify()
        minutes = record["seconds"] // 60
        span = self.words("common.minutes", m=minutes) if minutes else self.words("common.seconds", s=record["seconds"])
        crashed, failed = record["crashed"], record.get("failed_start")
        if crashed or failed:
            # What went wrong is in the player's log: the status line opens it.
            self.set_status(self.words("status.failed_start" if failed else "status.crashed"), "bad",
                            action=(self.words("status.open_log"), self.open_player_log), sticky=True)
        else:
            self.set_status(self.words("status.ended", time=span), "ok")
        self.refresh_checks()
        if self.page == "play":
            self.go("play")

    def open_player_log(self):
        """Show the player's log for the current server's app (Explorer, the file selected); the Help page when there
        is no log yet (no app, or the game has not run with it)."""
        from opendmtq_client import apps
        server = self.state.server()
        have = apps.local(server["url"]) if server else None
        if have is None or not actions.show_file(player.log_path(have["package"])):
            self.go("help")

    def _mapped(self, event):
        """The window came back on screen: a close while the game ran is taken back."""
        if event.widget is self.root and self.root.state() == "normal":
            self.quit_after_game = False

    def _failed(self, error):
        self.busy = False
        self.download = None
        self.set_status(self.words("status.error", error=self.words.error(error)), "bad", sticky=True)
        self._paint_play()
        self.refresh_checks()

    def _signed_out(self):
        """The server stopped taking the sign-in before this PC had its app: sign in again (Online)."""
        self.busy = False
        self.download = None
        self.state.save()
        # Kept until the player does something: the ready check that follows does not replace it.
        self.set_status(self.words("status.signed_out"), "warn", sticky=True)
        self.refresh_checks()
        self._paint_play()

    def _update_outcome(self):
        """Say whether the update handed to Velopack at the last close went in (a silent update says nothing)."""
        from opendmtq_client import updates
        try:
            outcome = updates.outcome()
        except Exception:  # noqa: BLE001  (a note that cannot be read is no reason to stop the launcher)
            log.exception("could not read the update note")
            return
        if outcome is None:
            return
        if outcome[0] == "updated":
            self.set_status(self.words("status.updated", v=outcome[1]), "ok", sticky=True)
        else:
            log.warning("the update to %s was not installed (this is %s)", outcome[1], outcome[2])
            self.set_status(self.words("status.not_updated", v=outcome[1], now=outcome[2]), "warn", sticky=True)

    # ----------------------------------------------------------------------------------- pages

    def go(self, page):
        """Show a page: its title and the line under it, and its cards."""
        from opendmtq_client import pages
        self.page = page
        # Every page in the site's lime; the menu lights its name.
        self.ui.use_section(page)
        self.header.set_current(page)
        for child in self.body.inner.winfo_children():
            child.destroy()
        self.download_bar = None
        content = tk.Frame(self.body.inner, bg=theme.BG)
        content.pack(fill="both", expand=True)
        title, description = pages.heading(self, page)
        self.body.set_heading(title, description)
        pages.BUILDERS[page](self, content)
        self.body.to_top()

    # ------------------------------------------------------------------------------ background

    def post(self, fn):
        """Run fn on the Tk thread (the only thread that may touch the window)."""
        self.tasks.put(fn)

    def _pump(self):
        """Run what the worker threads handed over. One failing task is logged and the rest still run: without this the
        window would stop taking results for good (PLAY stuck as busy, nothing shown)."""
        self.pumps += 1
        if self.pumps % PRESET_EVERY == 0:
            try:
                self._take_preset()
            except Exception:  # noqa: BLE001  (a server file that cannot be taken is no reason to stop the window)
                log.exception("could not take the server an installer left")
        while True:
            try:
                task = self.tasks.get_nowait()
            except queue.Empty:
                break
            try:
                task()
            except Exception:  # noqa: BLE001
                log.exception("a task for the window failed")
        self.root.after(50, self._pump)

    def _take_preset(self):
        """A server an installer left while this window is open (its "Open OpenDMTQ" with a launcher already open):
        taken now, as a start would take it, and said on the status line."""
        from opendmtq_client import preset
        brought = preset.take()
        if brought is None:
            return
        try:
            url = srv.normalize(brought["url"])
        except srv.ServerError:
            log.warning("the installer left an address that is none: %r", brought["url"])
            return
        busy = self.busy_now()
        before = self.state.current
        self.state.add_server(url, brought["name"])
        if busy and before:
            # The game or a download uses the current server: the new one waits on the Online page.
            self.state.current = before
        self.state.save()
        log.info("took the server %s an installer left", url)
        key = "status.preset.later" if busy and before else "status.preset"
        self.set_status(self.words(key, name=brought["name"]), "ok", sticky=True)
        self.refresh_checks()
        if self.guide is not None:
            self.guide.redraw()
        elif self.page in ("play", "online"):
            self.go(self.page)

    def refresh_checks(self):
        """Make the ready check again on a worker thread; the PLAY page and button follow it."""
        self.checks = None

        def work():
            try:
                checks = actions.readiness(self.state)
            except Exception as e:  # noqa: BLE001
                log.exception("ready check failed")
                checks = [actions.Check("server", False, str(e), page="online")]
            self.post(lambda: self._checked(checks))

        threading.Thread(target=work, daemon=True, name="check").start()

    def _checked(self, checks):
        self.checks = checks
        # A message kept until the player does something (a sign-in that ended, a stopped download) stays.
        quiet = self.status_sticky
        if not quiet and not self.busy_now():
            if self.state.server() is None:
                self.set_status(self.words("status.no_server"), "warn")
            elif not self.ready():
                self.set_status(self.words("status.fix_first"), "warn")
            elif self.status_transient or self.status_tone not in ("ok", "bad"):
                # Nothing to say beyond being ready (a passing "the app is here" included).
                self.set_status(self.words("status.ready"), "normal")
        self._paint_play()
        # The PLAY page, the Help page and the guide's last step each show the check when they are on screen.
        from opendmtq_client import pages
        pages.refresh_checks(self)
        if self.guide is not None:
            # The guide's last step: its PLAY follows the check.
            self.guide.checks_changed()

    def load_devices(self, then=None):
        """Ask the player for the sound devices once, on a worker thread; then() runs on the window's thread after."""
        if self.devices is not None:
            if then:
                then()
            return

        def work():
            found = player.audio_devices()
            self.post(lambda: self._devices_loaded(found, then))

        threading.Thread(target=work, daemon=True, name="devices").start()

    def _devices_loaded(self, found, then):
        self.devices = found
        if then:
            then()

    # ---------------------------------------------------------------------------- the app's download

    def get_app(self, done_then=None):
        """Download the current server's app on a worker thread, its progress on the page and in the status line."""
        if self.download is not None or self.busy:
            return
        self.user_acted()
        from opendmtq_client import apps
        server = self.state.server()
        # The app this PC had before: the same one after means the server had nothing newer.
        before = apps.local(server["url"]) if server else None
        cancel = threading.Event()
        self.download = {"done": 0, "total": None, "cancel": cancel, "before": before}
        self.download_error = None
        self.app_note = None
        self.set_status(self.words("status.app_check"), "normal")
        self._paint_play()

        def progress(done, total):
            self.post(lambda: self._download_moved(done, total))

        def work():
            try:
                actions.get_app(self.state, progress=progress, cancel=cancel)
                self.post(lambda: self._download_ended(None, done_then))
            except srv.Cancelled:
                self.post(lambda: self._download_ended("cancelled", done_then))
            except Exception as e:  # noqa: BLE001  (shown, never swallowed)
                log.exception("the app's download failed")
                self.post(lambda error=e: self._download_ended(error, done_then))

        threading.Thread(target=work, daemon=True, name="download").start()

    def _download_moved(self, done, total):
        if self.download is None:
            return
        self.download.update(done=done, total=total)
        # Stopping: said until the download has stopped, whatever pieces still come in.
        text = (self.words("status.stopping") if self.download.get("stopping") else
                self.words("status.downloading", done=_mb(done), total=_mb(total)))
        self.set_status(text, "normal")
        if self.download_bar is not None and self.download_bar.winfo_exists():
            self.download_bar.set(done / float(total) if total else None, text)

    def _download_ended(self, error, done_then):
        from opendmtq_client import apps
        before = (self.download or {}).get("before")
        self.download = None
        self.state.save()
        if error is None:
            self.download_error = None
            server = self.state.server()
            after = apps.local(server["url"]) if server else None
            if before and after and before.get("sha256") == after.get("sha256"):
                # Nothing newer: the page says so where the button was pressed (the guide has no status line).
                self.app_note = self.words("online.app.newest")
                self.set_status(self.words("status.newest"), "normal", transient=True)
            else:
                self.set_status(self.words("status.app_ready"), "ok", transient=True)
        else:
            # The page and the status line say it alike, in the same tone: a stop or a sign-in that ended in the
            # warning colour, a failure in the error colour. Kept until the player does something.
            if error == "cancelled":
                self.download_error = (self.words("status.download_cancelled"), "warn")
            elif isinstance(error, srv.SignedOut):
                self.download_error = (self.words("status.signed_out"), "warn")
            else:
                self.download_error = (self.words("status.error", error=self.words.error(error)), "bad")
            self.set_status(self.download_error[0], self.download_error[1], sticky=True)
        self.refresh_checks()
        if done_then:
            done_then(error)
        elif self.guide is None and self.page in ("online", "play"):
            self.go(self.page)

    def cancel_download(self):
        """Stop the download under way: said at once, done as soon as the next piece is in."""
        if self.download is not None and not self.download.get("stopping"):
            self.download["cancel"].set()
            self.download["stopping"] = True
            self.set_status(self.words("status.stopping"), "normal")

    # ---------------------------------------------------------------------------------- status

    def set_status(self, text, tone="normal", action=None, transient=False, sticky=False):
        """The bottom line: words in a tone, an optional link after them (words, function). A transient line gives way
        to the ready check's own words when it comes back; a sticky one stays until the player does something."""
        self.status_text, self.status_tone = text, tone
        self.status_action, self.status_transient, self.status_sticky = action, transient, sticky
        self._paint_status()

    def _paint_status(self):
        if not hasattr(self, "status_label") or not self.status_label.winfo_exists():
            return
        # The lamp in the tone's colour, as the site shows a state.
        self.status_glyph.configure(image=self._status_images[self.status_tone])
        self.status_glyph.odq_picture = self._status_lamps[self.status_tone]
        self.status_label.configure(text=self.status_text, fg=theme.TEXT if self.status_tone != "normal" else theme.MUTED)
        # The link after the words: shown with an action, gone without one.
        if self.status_action:
            words, function = self.status_action
            self.status_link.configure(text=words + "  " + theme.ICON["chevron"])
            self.status_link.odq_action = function
            if not self.status_link.winfo_manager():
                self.status_link.pack(side="left", after=self.status_label, padx=(0, self.ui.px(12)))
        elif self.status_link.winfo_manager():
            self.status_link.pack_forget()

    # ------------------------------------------------------------------------------- changes

    def changed(self, name, value):
        """A PC setting changed on a page: remember it (the player reads it at the next PLAY)."""
        self.state.set_value(name, value)
        self.state.save()
        self.user_acted()
        self.set_status(self.words("status.saved"), "normal")

    def set_language(self, language):
        """Switch the words and fonts: the whole window is rebuilt in the other language. "system" follows Windows'
        display language again (the state keeps no choice then)."""
        self.state.language = None if language == "system" else language
        self.state.save()
        self._setup_fonts()
        self.show()

    def step_failed(self, kind, error, trace):
        """A step of the window raised an error nobody expected: logged, and the first of the run said in a dialog with
        where the log is. The window goes on."""
        log.error("a step of the window failed", exc_info=(kind, error, trace))
        if self.failure_said or self.dialog is not None:
            return
        self.failure_said = True
        from opendmtq_client import dialogs
        logs = os.path.join(st.config_dir(), "logs", "launcher.log")
        try:
            dialogs.tell(self, "error", self.words("stopped.title"), self.words("failed.message"),
                         self.words("failed.detail", error=self.words.error(error), path=logs))
        except tk.TclError:
            # The window went while the dialog was opening.
            pass

    def close(self):
        """Close the launcher. A game playing keeps going: the launcher hides until it ends, then goes."""
        if self.updating:
            # The update is downloading (the launcher closes by itself once it is in Velopack's hands), or a repair is
            # writing the program's files.
            return
        if self.dialog is not None:
            # Closing the window answers an open question with Cancel.
            self.dialog.close(self.dialog.cancel_value)
        self.cancel_download()
        self.state.save()
        if self._game_open():
            self.quit_after_game = True
            self.root.withdraw()
            return
        self.root.destroy()

    def leave(self):
        """Close at once for an uninstall, writing nothing: the caller saved what stays before the uninstaller started,
        and after Delete all a write would make the deleted folder again."""
        if self.dialog is not None:
            self.dialog.close(self.dialog.cancel_value)
        self.cancel_download()
        try:
            self.root.destroy()
        except tk.TclError:
            # The player closed the window already, while a dialog before this was up.
            pass

    def run(self):
        self.root.mainloop()


def _mb(n):
    """Bytes as megabytes, one decimal ('103.2'); '?' when not known."""
    return "?" if n is None else "%.1f" % (n / 1048576.0)
