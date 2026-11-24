"""The launcher window: the menu column down its left (the wordmark and the version, the pages, and at its foot the
status and PLAY), and the page beside it.

Slow work (asking the server, downloading its app, listing the sound devices, update checks) runs on worker threads;
they hand results back through a queue the window empties every 50 ms, because Tk may only be touched from the thread
that created it. Their changes to the remembered state go the same way (actions.py's `change`): the window's thread
alone changes and saves it, so a save never catches a change half made.
"""

import logging
import queue
import threading
import tkinter as tk

from opendmtq_client import actions, art, i18n, player, safety, theme, widgets
from opendmtq_client import server as srv
from opendmtq_client import state as st

log = logging.getLogger("opendmtq_client")

# The menu, left to right, in English in both languages as the site's and the game's menus are.
NAV = ("play", "screen", "sound", "controls", "online", "help", "about")
# The pages that show what a game changes (the last game, the last game's sound, the player's log, the app PLAY got
# first): drawn again when a game ends while one of them is on show. The others show settings, which a game leaves as
# they were.
GAME_PAGES = ("play", "sound", "help", "online")
# The room under the column's foot (PLAY, the guide's buttons) to the window's edge, and how far a lamp sits down to stand
# on the status's first line (logical pixels).
FOOT_UNDER, STATUS_LAMP_DROP = 20, 3
# How far down the page its lit top reaches before it has faded (logical pixels): the site's top light.
PAGE_LIGHT = 324
# How often the window looks for a server an installer left while it is open, in turns of the 50 ms task pump (2 s).
PRESET_EVERY = 40
# How long the server's last answer to the ready check stands (seconds): the PLAY and Help pages ask for a check each
# time they show, and the server is asked again only after this, or when the player presses Check again.
REACH_FOR = 30
# How often the window looks again by itself, while it is on screen and nothing is under way (seconds): whether the
# server answers, whether it still takes the sign-in, whether it has a newer app. Each change is said as it comes, every
# time (a server that stopped answering, came back and stopped again is said each time).
WATCH_EVERY = 60
# How often the window looks for a newer launcher after the look at its start (seconds): one found later is said too.
UPDATE_EVERY = 6 * 3600


class LauncherApp:
    """The whole launcher: owns the Tk root, the remembered state and the game while it runs."""

    def __init__(self, state, root=None):
        # The launcher's own window: never on a real screen from a test.
        safety.refuse_windows_in_tests("the launcher window")
        self.state = state
        # Fonts must be registered before Tk measures any text.
        theme.register_fonts()
        self.root = root or tk.Tk()
        from opendmtq_client import frameless, titlebar
        # On Windows out of sight until Windows' title bar is drawn dark (titlebar.py, after the first page below):
        # nothing shows in Windows' light bar first.
        self.hidden_first = root is None and frameless.supported()
        if self.hidden_first:
            self.root.withdraw()
        self.root.title("OpenDMTQ")
        self.root.configure(bg=theme.BG)
        # The mark in the title bar and on the taskbar, in place of Tk's feather.
        from opendmtq_client import dialogs
        dialogs.set_icon(self.root)
        self.tasks = queue.Queue()      # functions from worker threads, run on the Tk thread
        self.session = None             # the running game, while it runs
        self.checks = None              # the last ready check (None: being made)
        self.shown_checks = None        # the last ready check that came back, shown while the next one is made
        self.checks_asked = 0           # ready checks started in this run (show() looks whether a page started one)
        self.page = "play"              # the page on show
        self.busy = False               # PLAY is getting ready (asking the server, downloading its app)
        # What the status line says: the message (i18n.Said, said again in the window's language each time it is
        # drawn, or plain text) and its tone.
        self.status_message, self.status_tone = None, "normal"
        self.status_sticky = False      # a message that stays until the player does something (an update's outcome, a
        #                                 sign-in that ended, a stopped download): the ready check does not replace it
        self.quit_after_game = False    # the window was closed while the game ran
        self.dialog = None              # the dialog on show (dialogs.py), while one is
        self.devices = None             # the sound devices the player lists (None: not asked yet)
        self.key_prints = {}            # what Tk said each place pressed on the Controls page prints, by its key's name
        #                                 (keys.printed: the boxes show it in grey where Windows' layout cannot be asked)
        self.key_held = None            # the key code of a key held down on the Controls page since it started a wait or
        #                                 went in: its repeats are left out until it is let go (pages.LaneKeys.pressed)
        self.download = None            # the app's download under way: {"done", "total", "cancel"}
        self.download_bar = None        # the page's progress bar for it, while one is on show
        self.download_error = None      # (i18n.Said, tone): how the last download ended badly (the page shows it)
        self.app_note = None            # what the last look for a newer app found when it found none (an i18n.Said)
        self.status_transient = False   # the status line says something passing, which the ready check may replace
        self.status_action = None       # (i18n.Said, function): a link after the status line, or None
        self.keep_open = False          # work that closing would cut short is under way (the launcher's update, a
        #                                 repair, a count or a deletion): the window stays until it ends
        self.play_offline = False       # PLAY went on with this PC's app because the server did not answer
        self.server_check = None        # the last time a server was asked in this run: {"url", "state", "error"}
        self.address_draft = None       # what the player typed in a server's address field and has not connected to
        #                                 yet (None: the field shows the server in use); kept over the page's redraws
        self.main_buttons = []          # the page's main-action buttons (pages.main_button): lime while PLAY is not
        self.server_reached = None      # the ready check's last answer from the server: {"url", "reached", "at"}
        self.update_found = None        # a newer launcher the look at the start found (updates.Result), or None
        self.pumps = 0                  # turns of the task pump, for the slower look for an installer's server
        self.page_follow = None         # the page's (or the guide's step's) own update for settings changed from
        #                                 outside: the Sound page's controls for what the in-game menu wrote back
        self.took_mtime = None          # the settings file's time when the window last looked at it (took_back)
        self.records = None             # the last records the server gave for the sign-in in use: {"key": (address,
        #                                 account), "answer": server.records' answer or None, "at"}; None before any
        self.records_asked = None       # the sign-in whose records are being asked for now, or None
        self.connection_test = None     # the connection test of this run: {"id", "url", "running", "steps": {key: Step},
        #                                 "result"}; its card on the Online page fills in as its steps end
        self.test_runs = 0              # connection tests started in this run (each card is made for one)
        self._setup_fonts()
        self._size_window()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        # A step of the window that fails is said in the launcher's own dialog, never silently.
        self.root.report_callback_exception = self.step_failed
        self.failure_said = False       # the first such failure of this run was said (the next ones go to the log)
        # Shown again while a game runs (the window was closed, then OpenDMTQ started again): it stays after the game.
        self.root.bind("<Map>", self._mapped, add="+")
        # Page Up and Page Down move the page on show by the keyboard (Home and End too, away from a field).
        for key in ("<Prior>", "<Next>", "<Home>", "<End>"):
            self.root.bind(key, self._page_key, add="+")
        # Back to the front (after a game, from another window): the sound the player's in-game menu set comes back.
        self.root.bind("<FocusIn>", lambda e: self.took_back(), add="+")
        # The displays and their rates, once a start, in the log: what the Screen page's frame limits come from (each
        # display's rate now, its highest at its size, and whether Windows runs it at a dynamic rate).
        from opendmtq_client import displays
        for line in displays.describe(displays.connected()):
            log.info("display: %s", line)
        self.root.after(50, self._pump)
        self.show()
        if self.hidden_first:
            # Laid out out of sight, which makes Tk's wrapper round the window; its title bar dark, then shown and in
            # front (Tk's deiconify brings a window to the front on Windows).
            self.root.update_idletasks()
            titlebar.dark(self.root)
            self.root.deiconify()
        self._update_outcome()
        # At the start, then every UPDATE_EVERY: whether a newer launcher is on offer, said on the Launcher page and the
        # status line when it is.
        self.look_for_update()
        # The server, the sign-in and the server's app looked at again by themselves (watch).
        self.root.after(WATCH_EVERY * 1000, self._watch_tick)

    # --------------------------------------------------------------------------------------- frame

    def _setup_fonts(self):
        """Fonts, words and DPI scale for the current language (a language change rebuilds them)."""
        self.scale = theme.scale_of(self.root)
        self.words = i18n.Words(self.state.language)
        self.fonts = theme.Fonts(self.root, self.state.language)
        self.ui = widgets.Ui(self.root, self.fonts, self.scale, self.words)
        widgets.style_ttk(self.ui)

    def _size_window(self):
        """1180x760 at 100 % scaling, never more than 92 % of the room windows have (on Windows the work area: the
        screen less the taskbar, the title bar counted too), centred across it and a third of the way down."""
        from opendmtq_client.window_room import title_bar_height, window_box, work_area
        px = self.ui.px
        # The box in the work area, so that the strip with PLAY at the window's foot never sits under the taskbar.
        w, h, x, y = window_box(work_area(self.root), title_bar_height(), px(1180), px(760))
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        # The smallest size the pages are made for, or the window's own when the room is smaller still.
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
        asked = self.checks_asked
        self.go(self.page)
        if self.checks_asked == asked:
            # The page did not ask for the ready check itself (PLAY and Help do): the bar's PLAY needs one too.
            self.refresh_checks()

    def _build_main(self):
        ui, px = self.ui, self.ui.px
        # ---- the column down the left: the wordmark and the version, the menu, and at its foot the status and PLAY
        # Each name in the menu as its page's title (pages.TITLES).
        from opendmtq_client import pages
        self.rail = self.make_rail(self.root, nav=[(key, pages.TITLES[key]) for key in NAV], on_nav=self.nav_go)
        # ---- the page: its title and its cards over the site's field (widgets.ScrollArea)
        self.body = self.make_page(self.root)
        # ---- the column's foot, made after the page so that Tab goes the menu, the page, then the foot
        foot = self.make_foot(self.rail)
        # The status: its lamp in its tone's colour and its words, a link under them when there is something to open
        # (the player's log after a crash); then PLAY under it all.
        from PIL import ImageTk
        self._status_lamps = {tone: art.lamp(colour, self.scale, bg=theme.STRIP, lead=False) for tone, colour in
                              (("normal", theme.FAINT), ("ok", theme.OK), ("warn", theme.WARN), ("bad", theme.BAD))}
        self._status_images = {tone: ImageTk.PhotoImage(p, master=self.root) for tone, p in self._status_lamps.items()}
        status = tk.Frame(foot, bg=theme.STRIP)
        status.pack(side="top", fill="x")
        self.status_glyph = tk.Label(status, image=self._status_images["normal"], bg=theme.STRIP, bd=0)
        self.status_glyph.pack(side="left", anchor="n", pady=(px(STATUS_LAMP_DROP), 0))
        lamp_width = self._status_lamps["normal"].width
        self.status_label = tk.Label(status, text="", font=self.fonts.small, fg=theme.MUTED, bg=theme.STRIP,
                                     justify="left", anchor="w",
                                     wraplength=self.rail.inner_width() - lamp_width - px(6))
        self.status_label.pack(side="left", fill="x", padx=(px(6), 0))
        # The link under the words, in the status's own column, when the message has one (_paint_status): its words set
        # then, its chevron made once with it.
        self.status_link = widgets.link(foot, ui, "", lambda: self.status_link.odq_action and self.status_link.odq_action(),
                                        fg=theme.TEXT, bg=theme.STRIP, font=self.fonts.small)
        self.status_link.odq_action = None
        self.status_link_place = (lamp_width + px(6) - int(self.status_link.cget("highlightthickness")))
        # PLAY: the lime slab on the column's own colour, as wide as the column holds, the same as the guide's last
        # step shows.
        self.play_button = widgets.PlaySlab(foot, ui, self.words("bottom.play"), self.play,
                                            width=self.rail.inner_width())
        self.play_button.pack(side="bottom", anchor="w", pady=(px(16), 0))
        # Lit or not as things stand now, before the page under it is drawn: a page's main button is lime only while
        # PLAY is not (pages.main_button reads it).
        self._paint_play()
        self._paint_status()

    def make_rail(self, parent, nav=(), on_nav=None, steps=()):
        """The column down the window's left (widgets.Rail): the wordmark with the version beside it (art.brand), then
        the menu, or the guide's steps."""
        from opendmtq_client import updates
        # The version the Launcher page shows too: the installed one, else the code's (updates.shown_version).
        rail = widgets.Rail(parent, self.ui, art.brand(self.scale, "v" + updates.shown_version()), nav=nav,
                            on_nav=on_nav, steps=steps)
        rail.pack(side="left", fill="y")
        return rail

    def make_foot(self, rail):
        """The column's foot (the status and PLAY, or the guide's Back and Next): a frame of the window's own, placed
        over the column's foot, so that Tab reaches it after the page (Tk's Tab follows the order things were made in)."""
        px = self.ui.px
        foot = tk.Frame(self.root, bg=theme.STRIP)
        foot.place(in_=rail, x=px(widgets.Rail.EDGE), rely=1.0, y=-px(FOOT_UNDER), anchor="sw",
                   width=rail.inner_width())
        # What it is to the UI checks (tests/ui/spacing.py): the column's foot, measured with the column round it.
        foot.odq_foot = rail
        return foot

    def make_page(self, parent):
        """The page area beside the column: the page's picture behind from its top, its title and its cards."""
        page = widgets.ScrollArea(parent, self.ui, offset=0, light=self.ui.px(PAGE_LIGHT))
        page.pack(side="left", fill="both", expand=True)
        return page

    def user_acted(self):
        """The player did something: a message kept until then (status_sticky) gives way now to where PLAY stands, as
        the last ready check says it. An outcome (a game that ended, an installer's server, a failure) is about the
        moment it came; once the player has moved on, the line says the state again instead of an outcome that may no
        longer hold (another server chosen since, a cause gone). What the player does next says its own words after
        this, as each action sets the line."""
        if self.status_sticky:
            self.status_sticky = False
            self._say_state()

    def _say_state(self):
        """The status line says where PLAY stands, from the last ready check: no server, something to fix, or ready.
        Not while a message is kept (status_sticky), work is under way (busy_now) or no check has come back yet (the
        one on its way says it)."""
        if self.status_sticky or self.busy_now() or self.checks is None:
            return
        if self.state.server() is None:
            self.set_status(i18n.Said("status.no_server"), "warn")
        elif not self.ready():
            self.set_status(i18n.Said("status.fix_first"), "warn")
        elif not self.server_answers():
            # Ready all the same: PLAY starts the app this PC has, which may be older than the server's.
            self.set_status(i18n.Said("status.server_down"), "warn")
        elif not self.signed_in_now():
            # Ready all the same, without the sign-in the ready check's yellow Sign-in row says: PLAY starts the app this
            # PC has (a sign-in that ended, or none yet, as the PLAY page's server card says it).
            ended = bool(self.state.server().get("account"))
            self.set_status(i18n.Said("status.signin_ended" if ended else "status.not_signed"), "warn")
        elif self.update_found is not None:
            # Ready, with a newer launcher on offer: said with its update, as the Launcher page's button does it. PLAY
            # lit at the foot says that it is ready.
            v = self.update_found.version
            self.set_status(i18n.Said("about.available", v=v), "normal",
                            action=(i18n.Said("about.update_now", v=v), self.update_now))
        else:
            # Ready: nothing more to say, whatever the line said before (a passing note, an outcome given way).
            self.set_status(i18n.Said("status.ready"), "normal")

    def _page_key(self, event):
        """A page key for the page area on show: the guide's step, or the launcher's page."""
        area = self.guide.body if self.guide is not None else getattr(self, "body", None)
        if area is not None and area.winfo_exists():
            area.page_key(event)

    def follow_page(self, *pages):
        """The page on show updated for a change of the launcher's state, in place: its own update (page_follow: the
        cards whose content changed made again) when it has one, else drawn again where it was. Only when it is one of
        `pages` (any page when none is named); the guide's step follows its own way."""
        from opendmtq_client import pages as page_module
        if self.guide is not None:
            self.guide.redraw()
            return
        if pages and self.page not in pages:
            return
        if self.page_follow is not None:
            self.page_follow()
        else:
            page_module.redraw_in_place(self, self.page)

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
        # One lime main action on the screen: the page's main buttons go quiet while PLAY is lit, and light up while
        # it is not (the ones of pages drawn since are gone from the list).
        self.main_buttons = [b for b in self.main_buttons if b.winfo_exists()]
        for button in self.main_buttons:
            button.set_kind("secondary" if self.play_lit() else "primary")

    def play_lit(self):
        """PLAY is lit at the window's foot, the screen's one lime main action (the guide's steps have no PLAY)."""
        slab = getattr(self, "play_button", None)
        return self.guide is None and slab is not None and slab.winfo_exists() and slab.state == "ready"

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
            self.set_status(i18n.Said("status.fix_first"), "warn")
            self._paint_play()
            return
        self.busy = True
        self.play_offline = False
        self._paint_play()
        self.set_status(i18n.Said("status.app_check"), "normal")
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
                # What the server offers and a sign-in that ended are changes to the state: made on this thread.
                session = actions.play(self.state, report=report, cancel=cancel, change=self.post)
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
            self.set_status(i18n.Said("status.app_check"), "normal")
        else:
            # Starting: with this PC's app, said so, when the server did not answer.
            self.set_status(i18n.Said("status.offline" if self.play_offline else "status.starting"),
                            "warn" if self.play_offline else "normal")

    def _play_downloading(self, done, total, cancel):
        """PLAY is downloading the app: the same download state as Online's button, so its page shows the bar and
        Cancel, and the status line its progress."""
        if self.download is None:
            self.download = {"done": 0, "total": total, "cancel": cancel, "before": None}
            self.download_error, self.app_note = None, None
            self._paint_play()
            if self.guide is None and self.page == "online":
                # The page's app card draws the bar and Cancel for it.
                self.follow_page("online")
        self._download_moved(done, total)

    def _play_cancelled(self):
        """PLAY's download was stopped: nothing started, and the page and the status line say so alike."""
        self.busy = False
        self.download = None
        self.download_error = (i18n.Said("status.download_cancelled"), "warn")
        self.set_status(self.download_error[0], "warn", sticky=True)
        self._paint_play()
        self.refresh_checks()
        if self.guide is None:
            self.follow_page("online", "play")

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
            self.set_status(i18n.Said("status.offline"), "warn", sticky=True)
        else:
            self.set_status(i18n.Said("status.playing"), "ok")
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
        sound = dict(self.state.values)
        # The sound the in-game menu set during the game is taken back with the game's end, then kept (actions.finish).
        record = actions.finish(self.state, self.session)
        self.state.save()
        self.session = None
        if self.quit_after_game:
            # The window was closed while the game ran: it goes now.
            self.root.destroy()
            return
        self.root.deiconify()
        crashed, failed = record["crashed"], record.get("failed_start")
        if crashed or failed:
            # What went wrong is in the player's log: the status line opens it.
            self.set_status(i18n.Said("status.failed_start" if failed else "status.crashed"), "bad",
                            action=(i18n.Said("status.open_log"), self.open_player_log), sticky=True)
        else:
            # Kept until the player does something: the ready check that follows does not take its place at once.
            self.set_status(i18n.Said("status.ended", time=i18n.span(record["seconds"])), "ok", sticky=True)
        self.refresh_checks()
        # PLAY says at once that the game is over, never PLAYING until the ready check comes back (a few seconds with
        # the server away): lit as before the game, and the check's answer says more when it comes.
        self._paint_play()
        if self.guide is None:
            # The page on show follows the game's end where it shows what a game changes, in place: the last game on
            # PLAY, the player's log on Help, the app on Online (a newer one PLAY got first).
            self.follow_page(*GAME_PAGES)
        followed = self.guide is None and self.page in GAME_PAGES
        if self.state.values != sound and self.page_follow is not None and not followed:
            # The sound the in-game menu set, on the page on show (the Sound page, the guide's step), in place.
            self.page_follow()
        # The game's plays are on the server now: PLAY's records asked for again.
        self.refresh_records(force=True)

    def open_player_log(self):
        """Show the player's log for the current server's app (Explorer, the file selected); the Help page when there
        is no log yet (no app, or the game has not run with it)."""
        from opendmtq_client import apps
        server = self.state.server()
        path = player.app_log(apps.local(server["url"]) if server else None)
        if path is None or not actions.show_file(path):
            self.go("help")

    def _mapped(self, event):
        """The window came back on screen: a close while the game ran is taken back."""
        if event.widget is self.root and self.root.state() == "normal":
            self.quit_after_game = False

    def _failed(self, error):
        self.busy = False
        self.download = None
        self.set_status(i18n.Said("status.error", error=error), "bad", sticky=True)
        self._paint_play()
        self.refresh_checks()

    def _signed_out(self):
        """The server stopped taking the sign-in before this PC had its app: sign in again (Online)."""
        self.busy = False
        self.download = None
        self.state.save()
        # Kept until the player does something: the ready check that follows does not replace it.
        self.set_status(i18n.Said("status.signed_out"), "warn", sticky=True)
        self.refresh_checks()
        self._paint_play()

    def records_key(self):
        """The sign-in the records are for: (the server's address, the account), or None while not signed in."""
        server = self.state.server()
        if server is None or not self.state.signed_in(server):
            return None
        return server["url"], server.get("account")

    def refresh_records(self, force=False):
        """The PLAY page's records asked of the server on a worker thread, for the sign-in in use: the last answer stands
        for REACH_FOR seconds unless `force` (a game that ended). The page follows when they come; nothing is asked while
        not signed in."""
        import time
        key = self.records_key()
        if key is None or self.records_asked == key:
            return
        kept = self.records
        if not force and kept is not None and kept["key"] == key and time.time() - kept["at"] < REACH_FOR:
            return
        self.records_asked = key

        def work():
            try:
                # A sign-in that ended is forgotten on the window's thread, as every change is.
                answer, error = actions.records(self.state, change=self.post), None
            except Exception as e:  # noqa: BLE001  (logged; the card keeps what it showed)
                log.info("could not ask %s for the records: %s", key[0], e)
                answer, error = None, e
            self.post(lambda: self._records_came(key, answer, error))

        threading.Thread(target=work, daemon=True, name="records").start()

    def _records_came(self, key, answer, error):
        """The records' answer: kept for the sign-in it is for, and the PLAY page's card follows. A failure keeps what
        was shown (the server away for a moment); a sign-in that ended is said as the watch says it."""
        import time
        self.records_asked = None
        if isinstance(error, srv.SignedOut):
            self.state.save()
            self.set_status(i18n.Said("status.signed_out"), "warn", sticky=True)
            self.refresh_checks()
        elif error is None:
            self.records = {"key": key, "answer": answer, "at": time.time()}
        if self.guide is None:
            self.follow_page("play")

    def open_my_page(self):
        """My page on the site: a one-time link the server makes for this sign-in, opened in the PC's browser on a worker
        thread (the server is asked first); said on the status line."""
        if self.busy:
            return
        self.user_acted()
        self.set_status(i18n.Said("status.mypage"), "normal")

        def work():
            try:
                url, error = actions.my_page(self.state, change=self.post), None
            except Exception as e:  # noqa: BLE001  (said on the status line, never swallowed)
                log.info("could not open the player's page on the site: %s", e)
                url, error = None, e
            self.post(lambda: self._my_page_came(url, error))

        threading.Thread(target=work, daemon=True, name="my-page").start()

    def _my_page_came(self, url, error):
        """The link came (or not): the browser opens it, and the status line says how it went."""
        if isinstance(error, srv.SignedOut):
            self.state.save()
            self.set_status(i18n.Said("status.signed_out"), "warn", sticky=True)
            self.refresh_checks()
            self.follow_page("play")
            return
        if error is not None:
            self.set_status(i18n.Said("status.error", error=error), "bad", sticky=True)
            return
        try:
            actions.open_url(url)
        except OSError as e:
            # No browser to open it with: said, the address in the log.
            log.warning("could not open %s: %s", url.split("?", 1)[0], e)
            self.set_status(i18n.Said("status.error", error=e), "bad", sticky=True)
            return
        # The link works once: never in the log; the page it opens is said instead. A server older than such links opens
        # its site's own address, whose sign-in comes first.
        linked = "once=" in url
        log.info("opened %s on the site in the browser", "the player's page" if linked else "the site's address")
        self.set_status(i18n.Said("status.mypage.opened" if linked else "status.site.opened"), "ok", transient=True)

    def test_connection(self):
        """The connection test of the server PLAY plays on (connection.py), on a worker thread: its card on the Online page
        is made at once with every step waiting, and each step's row says what it found as it ends, in place."""
        server = self.state.server()
        if server is None or (self.connection_test and self.connection_test["running"]):
            return
        self.user_acted()
        self.test_runs += 1
        test = {"id": self.test_runs, "url": server["url"], "running": True, "steps": {}, "result": None}
        self.connection_test = test
        self.follow_page("online")
        # The server's entry as it is now: its sign-in is asked with its cookie, nothing of it changed.
        entry = dict(server)
        from opendmtq_client import connection

        def work():
            try:
                result = connection.run(test["url"], entry,
                                        report=lambda step: self.post(lambda: self._test_step(test, step)))
            except Exception:  # noqa: BLE001  (logged; the card says the test ended where it stopped)
                log.exception("the connection test failed")
                result = None
            self.post(lambda: self._test_done(test, result))

        threading.Thread(target=work, daemon=True, name="connection-test").start()

    def _test_step(self, test, step):
        """A step of the test ended: kept, and its row on the card says it, in place."""
        from opendmtq_client import pages
        test["steps"][step.key] = step
        pages.test_step_shown(self, test, step)

    def _test_done(self, test, result):
        """The test ended: its result kept and its verdict said on the card (with the address of a server found on
        another port to use), its lines in the log."""
        from opendmtq_client import pages
        test["running"], test["result"] = False, result
        if result is not None:
            for line in result.text(i18n.Words("en")).splitlines():
                log.info("connection test: %s", line)
        pages.test_done_shown(self, test)

    def copy_test(self):
        """Copy: the whole result of the test on show as text, in the window's language, on the clipboard."""
        test = self.connection_test
        if not test or test["result"] is None:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(test["result"].text(self.words))
        self.set_status(i18n.Said("test.copied"), "ok", transient=True)

    def use_found_address(self, found):
        """The test's Use this address: the server PLAY plays on moves to the address it was found at (its sign-in kept;
        its app, built for the old address, goes), asked of the server first on a worker thread. Not while that app is
        in use: downloading, or playing from this window or the command line (files_in_use, as Forget asks)."""
        if self.files_in_use():
            self.set_status(i18n.Said("online.busy"), "warn")
            return
        self.user_acted()
        old = self.state.current

        def work():
            try:
                # The entry moved on the window's own thread together with what follows it (saved, said, tested again):
                # one task, so that nothing the window does in between finds PLAY on the new address under the old
                # address's words.
                actions.move_server(self.state, old, found,
                                    change=lambda move: self.post(lambda: self._moved(found, move)))
            except Exception as e:  # noqa: BLE001  (said on the status line)
                log.info("could not move to %s: %s", found, e)
                self.post(lambda error=e: self.set_status(i18n.Said("status.error", error=error), "bad", sticky=True))

        threading.Thread(target=work, daemon=True, name="move").start()

    def _moved(self, found, move):
        """The move made (`move`, actions.move_server's change), then said, saved, and the test run again on the new
        address, in the same task."""
        move()
        self.state.save()
        self.address_draft = None
        self.download_error, self.app_note = None, None
        self.refresh_checks(force=True)
        self.connection_test = None
        self.follow_page("online", "play")
        # The test again, of the new address; said after it starts (its start is the player's doing, which would give the
        # line back to the ready check).
        self.test_connection()
        # The server by its name, as the PLAY page's line names it (its address when it has no name of its own).
        self.set_status(i18n.Said("test.used", name=self.state.server()["name"]), "ok", sticky=True)

    def test_from_play(self):
        """PLAY's Server row, when the server does not answer: the Online page, and the test of it."""
        self.nav_go("online")
        self.test_connection()

    def look_for_update(self):
        """The look for a newer launcher at the start (updates.Look): on a worker thread, with its time limit. A newer one
        is said on the Launcher page and the status line, with its update; anything else (no network, a failure, no
        answer in time) says nothing. Nothing is installed by itself."""
        from opendmtq_client import updates

        def work():
            # The window's own settings: the server PLAY plays on is asked first (updates.check).
            found = updates.Look(state=self.state).newer()
            if found is not None and (self.update_found is None or found.version != self.update_found.version):
                # A newer one than the one said before, or the first: said (each newer version once it comes).
                self.post(lambda: self._update_on_offer(found))

        threading.Thread(target=work, daemon=True, name="update-look").start()
        # Again later: a launcher left open for days hears of a version that came meanwhile.
        try:
            self.root.after(UPDATE_EVERY * 1000, self.look_for_update)
        except tk.TclError:
            # The window went.
            pass

    def _watch_tick(self):
        """Every WATCH_EVERY: the window's own look (watch), while it is on screen with nothing under way."""
        try:
            self.root.after(WATCH_EVERY * 1000, self._watch_tick)
        except tk.TclError:
            return
        if self.guide is not None or self.dialog is not None or self.busy_now() or self.root.state() != "normal":
            # The guide asks the server itself; a dialog, work under way or a window out of sight waits for the next.
            return
        self.watch()

    def watch(self, then=None):
        """Look again, on a worker thread: whether the server answers, and while signed in, whether it still takes the
        sign-in and what app it offers (actions.check_app, its changes made on the window's thread); then the ready
        check, which says on the status line and the pages what changed. A sign-in the server no longer takes is said
        as it ends, each time it does. `then` runs on the window's thread after (the tests)."""
        server = self.state.server()
        if server is None:
            return
        signed_before = self.state.signed_in(server)

        def work():
            import time
            reached = actions.reach(self.state)
            # The answer kept for the ready check that follows, as its own asking would keep it.
            self.server_reached = {"url": server["url"], "reached": reached, "at": time.time()}
            ended = False
            if reached is True and signed_before:
                try:
                    actions.check_app(self.state, change=self.post)
                except srv.SignedOut:
                    ended = True
                except Exception:  # noqa: BLE001  (any failure leaves things as they were; the next look asks again)
                    log.info("the watch could not ask %s for its app", server["url"], exc_info=True)
            self.post(lambda: self._watched(ended, then))

        threading.Thread(target=work, daemon=True, name="watch").start()

    def _watched(self, ended, then):
        """The watch's answers: a sign-in that ended said (kept until the player acts), the ready check made again
        (its answers say the rest), the page on show following what changed."""
        if ended:
            log.info("the server no longer takes the sign-in")
            self.state.save()
            self.set_status(i18n.Said("status.signed_out"), "warn", sticky=True)
        self.refresh_checks()
        if self.guide is None:
            self.follow_page("play", "online", "help")
        if then:
            then()

    def _update_on_offer(self, result):
        """A newer launcher is on offer, found at the start: the Launcher page, on show, draws its answer and its update;
        the status line says it (update_on_offer)."""
        from opendmtq_client import updates
        log.info("OpenDMTQ %s is available (this is %s)", result.version, updates.shown_version())
        self.update_on_offer(result)
        if self.guide is None:
            self.follow_page("about")

    def update_on_offer(self, result):
        """Keep a newer launcher on offer (found at the start or by the Launcher page's Check for updates): the status
        line says it, with its update, whenever PLAY is ready (_say_state)."""
        self.update_found = result
        self._say_state()

    def update_now(self):
        """The status line's Update to vX: the Launcher page's own update (maintenance.update_launcher), refused while a
        game runs, as the page refuses it."""
        from opendmtq_client import maintenance
        if self.update_found is None:
            # The link goes with the notice: without an update on offer there is none to press.
            return
        self.user_acted()
        if not maintenance.update_launcher(self, self.update_found):
            # A game from this window or from the command line: the update replaces the player's files under it.
            self.set_status(i18n.Said("about.update_busy"), "warn")

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
            self.set_status(i18n.Said("status.updated", v=outcome[1]), "ok", sticky=True)
        else:
            log.warning("the update to %s was not installed (this is %s)", outcome[1], outcome[2])
            self.set_status(i18n.Said("status.not_updated", v=outcome[1], now=outcome[2]), "warn", sticky=True)

    # ----------------------------------------------------------------------------------- pages

    def go(self, page):
        """Show a page: its title and the line under it, and its cards. The page is made off the screen while the one
        on show stays whole on it, then takes its place with the menu's light and its title, all at once
        (widgets.ScrollArea.show_page): never a page half made on the screen while the rest of it is made."""
        from opendmtq_client import pages
        self.page = page
        self.download_bar = None
        # The page that went took its own update with it; the new one sets its own (Screen, Sound).
        self.page_follow = None
        content = self.body.new_page()
        pages.BUILDERS[page](self, content)
        # One column for the names of the page's settings, its cards' and both languages' widest (Help, Screen, Sound).
        widgets.fit_names(content, self.ui, pages.rows_that_come(page))
        # The menu lights the page's name, and the page's title and the line under it come, drawn with the page.
        self.rail.set_current(page)
        title, description = pages.heading(self, page)
        self.body.set_heading(title, description)
        self.body.show_page(content)

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
        taken now, as a start would take it, and said on the status line only when it changed something: a server
        added, or another one played on. The server already known and in use (the usual case: an installer from the
        site this launcher plays on) changes nothing, and says nothing."""
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
        known = self.state.server(url)
        # Its name as the launcher knows it, to tell whether the installer's changes it.
        named = known["name"] if known else None
        self.state.add_server(url, brought["name"])
        if busy and before:
            # The game or a download uses the current server: the installer's waits on the Online page.
            self.state.current = before
        switched = self.state.current != before
        # The ID Play on this PC brought (the owner's): in that server's sign-in form while it is not signed in.
        filled = self.state.fill_account(url, brought.get("account"))
        if filled:
            log.info("the installer left the ID %s to sign in with", brought["account"])
        if known is not None and not switched and not filled and named == self.state.server(url)["name"]:
            # Known, and the one in use already (or kept from being, while busy): nothing to save or to say.
            log.info("the installer left the server %s, known already", url)
            return
        self.state.save()
        log.info("took the server %s an installer left", url)
        if switched:
            # Another server in use: the address field shows it, whatever was typed there before.
            self.address_draft = None
        if known is None:
            # Added: played on from now on, or, while the game or a download uses the current one, waiting on Online.
            key = "status.preset" if switched else "status.preset.later"
            self.set_status(i18n.Said(key, name=brought["name"]), "ok", sticky=True)
        elif switched:
            # Known before, another one in use: the installer's is the one played on from now on.
            self.set_status(i18n.Said("status.preset.switched", name=brought["name"]), "ok", sticky=True)
        self.refresh_checks()
        self.follow_page("play", "online")

    def refresh_checks(self, force=False):
        """Make the ready check again on a worker thread, the server asked whether it answers (its last answer used for
        REACH_FOR seconds, unless `force`: Check again); the PLAY page and button follow it."""
        self.checks = None
        self.checks_asked += 1
        # Which check this is: only the last one asked is taken when it answers.
        asked = self.checks_asked

        def work():
            try:
                checks = actions.readiness(self.state, reached=self._reach(force))
            except Exception as e:  # noqa: BLE001
                log.exception("ready check failed")
                checks = [actions.Check("server", False, str(e), page="online")]
            self.post(lambda: self._checked(checks, asked))

        threading.Thread(target=work, daemon=True, name="check").start()

    def _reach(self, force):
        """Whether the server PLAY plays on answers (actions.reach), on the ready check's worker thread: asked again
        when its last answer is older than REACH_FOR seconds, is about another server, or `force` says so."""
        import time
        server = self.state.server()
        if server is None:
            return None
        seen = self.server_reached
        if not force and seen and seen["url"] == server["url"] and time.time() - seen["at"] < REACH_FOR:
            return seen["reached"]
        reached = actions.reach(self.state)
        # Kept for the next checks (one dict swapped in whole: a check on another thread reads either one or the other).
        self.server_reached = {"url": server["url"], "reached": reached, "at": time.time()}
        return reached

    def server_answers(self):
        """False when the last ready check found the server PLAY plays on not answering."""
        return not any(c.key == "server" and not c.ok and not c.blocks for c in (self.checks or ()))

    def signed_in_now(self):
        """False when the last ready check found no sign-in to the server PLAY plays on (its Sign-in row a yellow ring)."""
        return not any(c.key == "account" and not c.ok for c in (self.checks or ()))

    def _checked(self, checks, asked):
        if asked != self.checks_asked:
            # A check asked before the last one, answering after it: about the state before, so the last one's answer,
            # on its way, is the one to show.
            return
        self.checks = checks
        self.shown_checks = checks
        self._say_state()
        self._paint_play()
        # The PLAY page, the Help page and the guide's last step each show the check when they are on screen.
        from opendmtq_client import pages
        pages.refresh_checks(self)
        if self.guide is None and self.page == "play" and self.page_follow is not None:
            # PLAY's server card says whether the server answers: made again when that changed, the rest as it was.
            self.page_follow()
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
        self.set_status(i18n.Said("status.app_check"), "normal")
        self._paint_play()

        def progress(done, total):
            self.post(lambda: self._download_moved(done, total))

        def work():
            try:
                # The app's details and a sign-in that ended are changed on the window's thread, as every change is.
                actions.get_app(self.state, progress=progress, cancel=cancel, change=self.post)
                self.post(lambda: self._download_ended(None, done_then))
            except srv.Cancelled:
                self.post(lambda: self._download_ended("cancelled", done_then))
            except Exception as e:  # noqa: BLE001  (shown, never swallowed)
                log.exception("the app's download failed")
                self.post(lambda error=e: self._download_ended(error, done_then))

        threading.Thread(target=work, daemon=True, name="download").start()

    def download_words(self):
        """What the download under way is doing, for the status line and the page's bar alike: stopping (said until it
        has stopped, whatever pieces still come in), asking the server while the size is not known yet, or how far."""
        if self.download.get("stopping"):
            return i18n.Said("status.stopping")
        done, total = self.download["done"], self.download["total"]
        if not total:
            return i18n.Said("status.app_check")
        return i18n.Said("status.downloading", done=i18n.mb(done), total=i18n.mb(total))

    def _download_moved(self, done, total):
        if self.download is None:
            return
        self.download.update(done=done, total=total)
        message = self.download_words()
        self.set_status(message, "normal")
        if self.download_bar is not None and self.download_bar.winfo_exists():
            self.download_bar.set(done / float(total) if total else None, self.words.say(message))

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
                self.app_note = i18n.Said("online.app.newest")
                self.set_status(i18n.Said("status.newest"), "normal", transient=True)
            else:
                self.set_status(i18n.Said("status.app_ready"), "ok", transient=True)
        else:
            # The page and the status line say it alike, in the same tone: a stop or a sign-in that ended in the
            # warning colour, a failure in the error colour. Kept until the player does something.
            if error == "cancelled":
                self.download_error = (i18n.Said("status.download_cancelled"), "warn")
            elif isinstance(error, srv.SignedOut):
                self.download_error = (i18n.Said("status.signed_out"), "warn")
            else:
                self.download_error = (i18n.Said("status.error", error=error), "bad")
            self.set_status(self.download_error[0], self.download_error[1], sticky=True)
        self.refresh_checks()
        if done_then:
            done_then(error)
        elif self.guide is None:
            self.follow_page("online", "play")

    def cancel_download(self):
        """Stop the download under way: said at once, done as soon as the next piece is in."""
        if self.download is not None and not self.download.get("stopping"):
            self.download["cancel"].set()
            self.download["stopping"] = True
            self.set_status(i18n.Said("status.stopping"), "normal")

    # ---------------------------------------------------------------------------------- status

    def set_status(self, message, tone="normal", action=None, transient=False, sticky=False):
        """The bottom line: a message in a tone (i18n.Said, said in the window's language each time the line is drawn,
        so a switch of language says it again; or plain text), an optional link after it (message, function). A
        transient line gives way to the ready check's own words when it comes back; a sticky one stays until the
        player does something (user_acted)."""
        self.status_message, self.status_tone = message, tone
        self.status_action, self.status_transient, self.status_sticky = action, transient, sticky
        self._paint_status()

    @property
    def status_text(self):
        """What the status line says now, in the window's language."""
        return self.words.say(self.status_message)

    def _paint_status(self):
        if not hasattr(self, "status_label") or not self.status_label.winfo_exists():
            return
        # The lamp in the tone's colour, as the site shows a state.
        self.status_glyph.configure(image=self._status_images[self.status_tone])
        self.status_glyph.odq_picture = self._status_lamps[self.status_tone]
        self.status_label.configure(text=self.status_text, fg=theme.TEXT if self.status_tone != "normal" else theme.MUTED)
        # The link under the words: shown with an action, gone without one.
        if self.status_action:
            message, function = self.status_action
            # The words alone: the chevron after them is the link's own picture (widgets.link).
            self.status_link.configure(text=self.words.say(message))
            self.status_link.odq_action = function
            if not self.status_link.winfo_manager():
                self.status_link.pack(side="top", anchor="w", padx=(self.status_link_place, 0),
                                      pady=(self.ui.px(4), 0))
        elif self.status_link.winfo_manager():
            self.status_link.pack_forget()

    # ------------------------------------------------------------------------------- changes

    def changed(self, name, value):
        """A PC setting changed on a page: remember it, and write the settings file the player reads (it reads it at the
        next PLAY; its in-game menu writes the sound's settings back into it)."""
        self.state.set_value(name, value)
        self.state.save()
        self.write_settings()
        self.user_acted()
        self.set_status(i18n.Said("status.saved"), "normal")

    def write_settings(self):
        """The player's settings file as the launcher's settings are now; a failure is logged, the next PLAY writes it
        again."""
        try:
            player.write_settings(self.state.values, self.state.picked_language)
            self.took_mtime = self._settings_mtime()
        except OSError:
            log.exception("could not write the player's settings")

    @staticmethod
    def _settings_mtime():
        """The player's settings file's time, or None while there is none."""
        import os
        try:
            return os.stat(player.settings_path()).st_mtime_ns
        except OSError:
            return None

    def took_back(self):
        """The sound's settings the player's in-game menu wrote back into its settings file since the launcher last
        wrote or read it (values.took_back): kept as the launcher's own, and the page on show updated in place. Asked
        each time the window comes back to the front; a file the window has seen as it is now is not read again."""
        mtime = self._settings_mtime()
        if mtime is None or mtime == self.took_mtime:
            return
        self.took_mtime = mtime
        import os
        try:
            kept = os.stat(st.LauncherState.path()).st_mtime_ns
        except OSError:
            kept = None
        if kept is not None and mtime <= kept:
            # Written before the launcher last kept its settings (by the launcher itself, or by the command line's
            # --set, which keeps them after): nothing in it the launcher does not have.
            return
        if not actions.take_back(self.state):
            return
        self.state.save()
        if self.page_follow is not None:
            self.page_follow()

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
        try:
            dialogs.tell(self, "error", self.words("stopped.title"), self.words("failed.message"),
                         self.words("failed.detail", error=self.words.error(error), path=st.launcher_log()))
        except tk.TclError:
            # The window went while the dialog was opening.
            pass

    def close(self):
        """Close the launcher. A game playing keeps going: the launcher hides until it ends, then goes."""
        if self.keep_open:
            # The update is downloading (the launcher closes by itself once it is in Velopack's hands), or a repair, a
            # count or a deletion is under way: each would stop half done.
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
