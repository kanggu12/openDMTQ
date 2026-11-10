"""The first-start guide: six steps from nothing to the first song, one question each.

POWER ON (language, what is needed), SERVER (the server's address, or the one the installer brought), LOG IN (the ID and
password its owner made), DOWNLOAD (that server's app), SOUND CHECK (screen and sound), STAGE START (the ready check,
then PLAY). Every choice is the same setting the launcher's pages show, so the guide never knows anything the pages do
not.
"""

import tkinter as tk

from opendmtq_client import apps, pages, theme, widgets

# Step keys name the words in i18n (guide.<key>.name, .sub, .title); the number shown is the place in this list.
STEPS = ("power", "server", "login", "download", "sound", "stage")
# The few words each step says under its question, in the page's heading.
LEADS = {"power": "guide.power.text", "server": "guide.server.text", "login": "guide.login.text",
         "download": "guide.download.text", "stage": "guide.stage.text"}


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
        from opendmtq_client.app import BAR_HEIGHT, EDGE
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        root = app.root
        # The launcher's header: the wordmark and the version, leaving the guide at the other end, and the six steps
        # across under them, as the site's numbered steps.
        self.header = app.make_header(root, steps=[w("guide.%s.name" % key) for key in STEPS])
        # The bar along the foot: where the guide is, Back, and Next (PLAY on the last step).
        bottom = tk.Frame(root, bg=theme.STRIP)
        bottom.pack(side="bottom", fill="x")
        # The launcher's bar height on every step: Next and the last step's PLAY sit in the same bar.
        bar = tk.Frame(bottom, bg=theme.STRIP, height=px(BAR_HEIGHT))
        bar.pack(fill="x", padx=px(EDGE), pady=px(12))
        bar.pack_propagate(False)
        self.counter = tk.Label(bar, text="", font=app.fonts.step if w.language == "en" else app.fonts.body_bold,
                                fg=theme.MUTED, bg=theme.STRIP)
        self.counter.pack(side="left")
        self.next_button = widgets.Button(bar, ui, w("guide.next"), self.next, kind="primary")
        self.next_button.pack(side="right")
        # The last step's PLAY: the launcher's own lime slab in place of Next (not packed until then).
        self.play_slab = widgets.PlaySlab(bar, ui, w("bottom.play"), self.next)
        self.back_button = widgets.Button(bar, ui, w("guide.back"), self.back)
        self.back_button.pack(side="right", padx=(0, px(10)))
        # Leaving the guide for the launcher: a quiet link before Back, which the keyboard reaches too.
        skip = widgets.link(bar, ui, w("guide.skip"), lambda: self.finish(play=False), fg=theme.MUTED,
                            font=app.fonts.small, chevron=False)
        skip.pack(side="right", padx=(0, px(18)))
        # The step's page: its name as the page's title over the site's field, its question under it.
        self.body = app.make_page(root, self.header)
        self.show(self.index)

    # ------------------------------------------------------------------------------------- steps

    def show(self, index):
        self.index = index
        app, w = self.app, self.app.words
        for child in self.body.inner.winfo_children():
            child.destroy()
        # A progress bar of the page that went: the download's progress waits for the next one.
        app.download_bar = None
        key = STEPS[index]
        # The step's name as the page's title, in English as the site's titles; its question and its few words under it.
        question, lead = w("guide.%s.title" % key), LEADS.get(key)
        if lead:
            question += (" " if question.endswith(("?", ".", "!")) else ". ") + w(lead)
        self.body.set_heading(w("guide.%s.name" % key), question)
        content = tk.Frame(self.body.inner, bg=theme.BG)
        content.pack(fill="both", expand=True)
        getattr(self, "_" + key)(content)
        self.header.set_step(index)
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
        # The last step's PLAY lit when the ready check lets it go, dark and still otherwise.
        self.play_slab.set("ready" if can else "waiting")

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
        app, ui, w = self.app, self.app.ui, self.app.words
        # The language on a card of its own, its row's name saying what it is.
        card = pages._card(parent, ui, None)
        widgets.setting_row(card.body, ui, w("about.language"),
                            lambda p: widgets.Segmented(p, ui, pages.language_options(app),
                                                        app.state.picked_language or "system", self._language)).pack(
            fill="x")
        # Where the app comes from: a plain card, a fact to know, nothing to beware of.
        card = pages._card(parent, ui, w("guide.power.notice.title"))
        widgets.label(card.body, ui, w("guide.power.notice"), wrap_margin=0).pack(fill="x")
        card = pages._card(parent, ui, w("guide.power.need"), last=True)
        for i, key in enumerate(("guide.power.need.1", "guide.power.need.2")):
            if i:
                widgets.divider(card.body, ui, pady=9)
            widgets.label(card.body, ui, w(key), wrap_margin=0).pack(fill="x")

    def _language(self, language):
        """Switching language rebuilds the guide in the other language, on the same step ("system": Windows')."""
        self.app.state.language = None if language == "system" else language
        self.app.state.save()
        self.app._setup_fonts()
        for child in self.app.root.winfo_children():
            child.destroy()
        # build() shows the step the guide is on (self.index), once.
        self.build()

    # ------------------------------------------------------------------------------ 2 SERVER

    def _server(self, parent):
        app = self.app
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
        app = self.app
        pages.signin_panel(app, parent, self.redraw)

    # ----------------------------------------------------------------------------- 4 DOWNLOAD

    def _download(self, parent):
        app = self.app
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
        tk.Frame(parent, bg=theme.BG, height=px(pages.CARD_GAP)).pack(fill="x")
        pages.sound_rows(app, parent, self.redraw, full=False)

    # ------------------------------------------------------------------------- 6 STAGE START

    def _stage(self, parent):
        app, ui, w = self.app, self.app.ui, self.app.words
        card = pages._card(parent, ui, w("play.ready"), last=True)
        app.check_box = tk.Frame(card.body, bg=theme.PANEL)
        app.check_box.pack(fill="x")
        app.refresh_checks()
        pages.refresh_checks(app)

    def checks_changed(self):
        """The ready check came back (app._checked): the last step's PLAY follows it."""
        self._update_next()
