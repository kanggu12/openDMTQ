"""The first-start guide: six steps from nothing to the first song, one question each.

POWER ON (language, what is needed), SERVER (the server's address, or the one the installer brought), LOG IN (the ID and
password its owner made), DOWNLOAD (that server's app), SOUND CHECK (screen and sound), STAGE START (the ready check,
then PLAY). Every choice is the same setting the launcher's pages show, so the guide never knows anything the pages do
not.
"""

import tkinter as tk

from PIL import ImageTk

from opendmtq_client import apps, art, pages, theme, widgets

# Step keys name the words in i18n (guide.<key>.name, .sub, .title); the number shown is the place in this list.
STEPS = ("power", "server", "login", "download", "sound", "stage")


class Guide:
    def __init__(self, app):
        self.app = app
        self.index = 0                  # the step on show
        # Whether a server was asked, and what it answered, is the window's (app.server_check), shared with Online.
        self.auto_asked = None          # the server the guide asked by itself (once: a typed address's answer stays)
        self.download_tried = False     # the download step started its download once already

    # ------------------------------------------------------------------------------------- frame

    @property
    def checking(self):
        """A server is being asked now."""
        check = self.app.server_check
        return bool(check and check["state"] == "checking")

    def build(self):
        from opendmtq_client.app import BAR_HEIGHT, LOGO_PAD, SIDE_WIDTH
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        root = app.root
        # The menu column of the launcher, as wide, with the logo at the same size and place.
        side = tk.Frame(root, bg=theme.SIDEBAR, width=px(SIDE_WIDTH))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        # The guide is PLAY's way in: the site's lime throughout.
        ui.use_section("play")
        app.make_logo(side).pack(anchor="w", padx=px(LOGO_PAD), pady=(px(LOGO_PAD), px(20)))
        tk.Label(side, text=w("guide.heading"), font=app.fonts.kicker, fg=theme.OK,
                 bg=theme.SIDEBAR).pack(anchor="w", padx=px(LOGO_PAD + 4))
        self.step_rows = []
        steps_box = tk.Frame(side, bg=theme.SIDEBAR)
        steps_box.pack(fill="x", padx=px(LOGO_PAD + 4), pady=(px(22), 0))
        for i, key in enumerate(STEPS):
            self.step_rows.append(self._step_row(steps_box, i, key))
        # Leaving the guide for the launcher: a link the keyboard reaches too.
        skip = widgets.link(side, ui, w("guide.skip"), lambda: self.finish(play=False), fg=theme.MUTED,
                            bg=theme.SIDEBAR, font=app.fonts.small, chevron=False)
        skip.pack(side="bottom", pady=px(22))
        right = tk.Frame(root, bg=theme.BG)
        right.pack(side="left", fill="both", expand=True)
        self.header = tk.Canvas(right, height=px(150), bg=theme.BG, highlightthickness=0)
        self.header.pack(fill="x")
        self.header.bind("<Configure>", lambda e: self._draw_header())
        bottom = tk.Frame(right, bg=theme.PANEL)
        bottom.pack(side="bottom", fill="x")
        tk.Frame(bottom, bg=theme.LINE, height=1).pack(fill="x")
        # The launcher's bar height on every step: Next and the last step's PLAY sit in the same bar.
        bar = tk.Frame(bottom, bg=theme.PANEL, height=px(BAR_HEIGHT))
        bar.pack(fill="x", padx=px(24), pady=px(12))
        bar.pack_propagate(False)
        self.counter = tk.Label(bar, text="", font=app.fonts.section, fg=theme.MUTED, bg=theme.PANEL)
        self.counter.pack(side="left")
        self.next_button = widgets.Button(bar, ui, w("guide.next"), self.next, kind="primary", icon="next")
        self.next_button.pack(side="right")
        # The last step's PLAY: the launcher's own lime slab in place of Next.
        self.play_slab = self._make_play(bar)
        self.back_button = widgets.Button(bar, ui, w("guide.back"), self.back, icon="back")
        self.back_button.pack(side="right", padx=(0, px(10)))
        self.body = widgets.ScrollArea(right, ui)
        self.body.pack(fill="both", expand=True)
        self.show(self.index)

    def _make_play(self, parent):
        """PLAY as the launcher's bottom bar shows it, for the guide's last step (not packed until then)."""
        app, px = self.app, self.app.ui.px
        size = (px(212), px(50))
        self._play_pictures = {s: art.play_button(*size, state=s) for s in ("normal", "hover", "pressed", "disabled")}
        self._play_images = {s: ImageTk.PhotoImage(p, master=app.root) for s, p in self._play_pictures.items()}
        slab = tk.Label(parent, image=self._play_images["normal"], text=app.words("bottom.play"), compound="center",
                        font=app.fonts.display_big, fg=theme.SECTION_COLOURS["home"]["ink"], bg=theme.PANEL, bd=0,
                        takefocus=1, highlightthickness=max(1, px(2)), highlightbackground=theme.PANEL,
                        highlightcolor=theme.CYAN)
        slab.odq_enabled = False
        slab.bind("<Enter>", lambda e: self._paint_play("hover"))
        slab.bind("<Leave>", lambda e: self._paint_play())
        slab.bind("<Button-1>", lambda e: self._paint_play("pressed"))
        # Only a release over the slab counts, like a real button (drag off to cancel).
        slab.bind("<ButtonRelease-1>", lambda e: self._released(e))
        # The keyboard presses it as the mouse does.
        slab.bind("<Return>", lambda e: self.next())
        slab.bind("<space>", lambda e: self.next())
        return slab

    def _released(self, event):
        """The mouse's button came up: PLAY when it is still over the slab, else only its look back."""
        if 0 <= event.x < self.play_slab.winfo_width() and 0 <= event.y < self.play_slab.winfo_height():
            self.next()
        else:
            self._paint_play()

    def _paint_play(self, mouse=None):
        """The slab lit when the ready check lets PLAY go, dark and still otherwise."""
        slab = self.play_slab
        look = (mouse or "normal") if slab.odq_enabled else "disabled"
        slab.odq_picture = self._play_pictures[look]
        slab.configure(image=self._play_images[look], cursor="hand2" if slab.odq_enabled else "arrow",
                       fg=theme.SECTION_COLOURS["home"]["ink"] if slab.odq_enabled else theme.FAINT)

    def _step_row(self, parent, i, key):
        app, px = self.app, self.app.ui.px
        row = tk.Frame(parent, bg=theme.SIDEBAR)
        row.pack(fill="x", pady=(0, px(14)))
        # A box of one size for the number and for the tick that replaces it, so the names beside never move.
        box = tk.Frame(row, bg=theme.RAIL, width=px(26), height=px(26))
        box.pack(side="left")
        box.pack_propagate(False)
        number = tk.Label(box, text=str(i + 1), font=app.fonts.display, fg=theme.MUTED, bg=theme.RAIL)
        number.pack(fill="both", expand=True)
        number.box = box
        names = tk.Frame(row, bg=theme.SIDEBAR)
        names.pack(side="left", padx=(px(12), 0))
        big = tk.Label(names, text=app.words("guide.%s.name" % key), font=app.fonts.display, fg=theme.MUTED,
                       bg=theme.SIDEBAR)
        big.pack(anchor="w")
        small = tk.Label(names, text=app.words("guide.%s.sub" % key), font=app.fonts.small, fg=theme.FAINT,
                         bg=theme.SIDEBAR)
        small.pack(anchor="w")
        return number, big, small

    def _paint_steps(self):
        ink = theme.SECTION_COLOURS["home"]["ink"]
        for i, (number, big, small) in enumerate(self.step_rows):
            if i < self.index:
                number.configure(text=theme.ICON["check"], font=self.app.fonts.icon_small, bg=theme.OK, fg=ink)
            elif i == self.index:
                number.configure(text=str(i + 1), font=self.app.fonts.display, bg=theme.OK, fg=ink)
            else:
                number.configure(text=str(i + 1), font=self.app.fonts.display, bg=theme.RAIL, fg=theme.MUTED)
            number.box.configure(bg=number.cget("bg"))
            big.configure(fg=theme.TEXT if i <= self.index else theme.MUTED)
            small.configure(fg=theme.MUTED if i <= self.index else theme.FAINT)

    def _draw_header(self):
        c, px, w = self.header, self.app.ui.px, self.app.words
        width, height = c.winfo_width(), c.winfo_height()
        if width < 50:
            return
        key = STEPS[self.index]
        title = w("guide.%s.title" % key)
        # The step's title is part of the picture, in leaning chrome like the launcher's pages.
        picture = art.header(width, height, seed=3 + 10 * self.index, title=title, scale=self.app.scale,
                             title_at=(32, 92))
        self._header_img = ImageTk.PhotoImage(picture, master=c)
        c.odq_picture = picture
        c.delete("all")
        c.create_image(0, 0, image=self._header_img, anchor="nw")
        c.create_text(px(32), px(48), text="%d · %s" % (self.index + 1, w("guide.%s.name" % key)),
                      font=self.app.fonts.kicker, fill=theme.OK, anchor="w")

    # ------------------------------------------------------------------------------------- steps

    def show(self, index):
        self.index = index
        app, px, w = self.app, self.app.ui.px, self.app.words
        for child in self.body.inner.winfo_children():
            child.destroy()
        # A progress bar of the page that went: the download's progress waits for the next one.
        app.download_bar = None
        content = tk.Frame(self.body.inner, bg=theme.BG)
        content.pack(fill="both", expand=True, padx=px(32), pady=(px(20), px(28)))
        getattr(self, "_" + STEPS[index])(content)
        self._paint_steps()
        self.counter.configure(text=w("guide.step", n=index + 1, total=len(STEPS)).upper()
                               if w.language == "en" else w("guide.step", n=index + 1, total=len(STEPS)))
        self.back_button.enable(index > 0)
        last = index == len(STEPS) - 1
        # Next on every step but the last, where the big PLAY takes its place.
        if last:
            self.next_button.pack_forget()
            self.play_slab.pack(side="right", before=self.back_button)
        else:
            self.play_slab.pack_forget()
            self.next_button.pack(side="right", before=self.back_button)
        self._update_next()
        self.body.to_top()
        self._draw_header()

    def redraw(self):
        """The step on show, drawn again (an answer came)."""
        if self.app.guide is self:
            self.show(self.index)

    def _can_go_on(self):
        """SERVER needs a server that answered; LOG IN a sign-in; DOWNLOAD the app; the last step what PLAY needs."""
        state, key = self.app.state, STEPS[self.index]
        server = state.server()
        if key == "server":
            check = self.app.server_check
            return bool(server and check and check["state"] == "ok" and check["url"] == server["url"])
        if key == "login":
            return state.signed_in(server)
        if key == "download":
            return server is not None and self.app.download is None and apps.local(server["url"]) is not None
        if key == "stage":
            return self.app.ready()
        return True

    def _update_next(self):
        can = self._can_go_on()
        self.next_button.enable(can)
        self.play_slab.odq_enabled = can
        self._paint_play()

    def next(self):
        if self.index == len(STEPS) - 1:
            if self._can_go_on():
                self.finish(play=True)
        elif self._can_go_on():
            self.show(self.index + 1)

    def back(self):
        if self.index > 0:
            self.show(self.index - 1)

    def finish(self, play):
        """Leave the guide for the launcher, and start the game when the last step's PLAY was pressed."""
        self.app.cancel_download()
        self.app.state.guide_done = True
        self.app.state.save()
        self.app.page = "play"
        self.app.show()
        if play:
            # The ready check runs first; PLAY waits for nothing else.
            self.app.root.after(400, self.app.play)

    # ---------------------------------------------------------------------------- 1 POWER ON

    def _power(self, parent):
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        widgets.label(parent, ui, w("guide.power.text"), wrap_margin=0).pack(fill="x", pady=(0, px(18)))
        widgets.setting_row(parent, ui, w("about.language"),
                            lambda p: widgets.Segmented(p, ui, pages.language_options(app),
                                                        app.state.picked_language or "system", self._language)).pack(
            fill="x", pady=(0, px(20)))
        # Where the app comes from: a plain card, a fact to know, nothing to beware of; titled as the card under it.
        notice = widgets.Card(parent, ui)
        notice.pack(fill="x", pady=(0, px(16)))
        widgets.section(notice.body, ui, w("guide.power.notice.title"), bg=theme.PANEL).pack(fill="x", pady=(0, px(10)))
        widgets.label(notice.body, ui, w("guide.power.notice"), bg=theme.PANEL, wrap_margin=0).pack(fill="x")
        card = widgets.Card(parent, ui)
        card.pack(fill="x")
        widgets.section(card.body, ui, w("guide.power.need"), bg=theme.PANEL).pack(fill="x", pady=(0, px(10)))
        for key in ("guide.power.need.1", "guide.power.need.2"):
            row = tk.Frame(card.body, bg=theme.PANEL)
            row.pack(fill="x", pady=(0, px(6)))
            mark = tk.Label(row, text=theme.ICON["check"], font=app.fonts.icon_small, fg=theme.OK, bg=theme.PANEL)
            mark.pack(side="left", anchor="n")
            widgets.label(row, ui, w(key), bg=theme.PANEL, wrap_margin=0, beside=(mark,)).pack(
                side="left", padx=(px(8), 0))

    def _language(self, language):
        """Switching language rebuilds the guide in the other language, on the same step ("system": Windows')."""
        index = self.index
        self.app.state.language = None if language == "system" else language
        self.app.state.save()
        self.app._setup_fonts()
        for child in self.app.root.winfo_children():
            child.destroy()
        self.build()
        self.show(index)

    # ------------------------------------------------------------------------------ 2 SERVER

    def _server(self, parent):
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        widgets.label(parent, ui, w("guide.server.text"), wrap_margin=0).pack(fill="x", pady=(0, px(16)))
        server, check = app.state.server(), app.server_check
        if (server is not None and not self.checking and self.auto_asked != server["url"]
                and (check is None or check["url"] != server["url"])):
            # A server the installer brought, or one from before: asked once by itself, so its name shows and Next can
            # go on. Once only: after that, the answer on show is the one to the address the player typed.
            self.auto_asked = server["url"]
            pages.check_server(app, server["url"], then=self.redraw)
        # The address, Connect, and one line under them: connecting, connected, or why not.
        pages.connect_panel(app, parent, self.redraw)

    # ------------------------------------------------------------------------------- 3 LOG IN

    def _login(self, parent):
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        widgets.label(parent, ui, w("guide.login.text"), wrap_margin=0).pack(fill="x", pady=(0, px(16)))
        pages.signin_panel(app, parent, self.redraw)

    # ----------------------------------------------------------------------------- 4 DOWNLOAD

    def _download(self, parent):
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        widgets.label(parent, ui, w("guide.download.text"), wrap_margin=0).pack(fill="x", pady=(0, px(16)))
        server = app.state.server()
        if server is not None and app.download is None and apps.local(server["url"]) is None and not self.download_tried:
            # The app is what this step is for: its download starts by itself, once.
            self.download_tried = True
            app.get_app(done_then=lambda error: self.redraw())
        pages.app_panel(app, parent, self.redraw)

    # -------------------------------------------------------------------------- 5 SOUND CHECK

    def _sound(self, parent):
        app, px = self.app, self.app.ui.px
        # The same rows as the Screen and Sound pages, the ones a first start needs.
        pages.screen_rows(app, parent, self.redraw, full=False)
        tk.Frame(parent, bg=theme.BG, height=px(6)).pack(fill="x")
        pages.sound_rows(app, parent, self.redraw, full=False)

    # ------------------------------------------------------------------------- 6 STAGE START

    def _stage(self, parent):
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        widgets.label(parent, ui, w("guide.stage.text"), wrap_margin=0).pack(fill="x", pady=(0, px(16)))
        card = widgets.Card(parent, ui)
        card.pack(fill="x")
        widgets.section(card.body, ui, w("play.ready"), bg=theme.PANEL).pack(fill="x", pady=(0, px(12)))
        app.check_box = tk.Frame(card.body, bg=theme.PANEL)
        app.check_box.pack(fill="x")
        app.refresh_checks()
        pages.refresh_checks(app)

    def checks_changed(self):
        """The ready check came back (app._checked): the last step's PLAY follows it."""
        self._update_next()
