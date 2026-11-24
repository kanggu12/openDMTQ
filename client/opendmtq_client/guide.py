"""The first-start guide: six steps from nothing to the first song, one question each.

POWER ON (language, what is needed), SERVER (the server's address, or the one the installer brought), SIGN IN (the ID
and password its owner made), DOWNLOAD (that server's app), SOUND & SCREEN (the volumes, the display's mode and the
frames), STAGE START (the ready check, then PLAY). Each step's question is its page's title, its few words under it, and
the steps go down the launcher's column, the one on show lit; while Next waits, a line at the foot of the step's card
says for what.
Every choice is the same setting the launcher's pages show, so the guide never knows anything the pages do not.
"""

import tkinter as tk

from opendmtq_client import apps, pages, theme, widgets

# Step keys name the words in i18n (guide.<key>.name, .sub, .title); the number shown is the place in this list.
STEPS = ("power", "server", "login", "download", "sound", "stage")
# The few words each step says under its question, in the page's heading.
LEADS = {"power": "guide.power.text", "server": "guide.server.text", "login": "guide.login.text",
         "download": "guide.download.text", "stage": "guide.stage.text"}
# What Next waits for on the steps that make it wait, said while it does (waits_for).
NEEDS = {"server": "guide.need.server", "login": "guide.need.login", "download": "guide.need.download"}

# The room over that line at the foot of the step's card (logical pixels: a row's gap, as the forms keep between parts).
NEED_GAP = 16


def waits_for(step, can, busy=False):
    """The words' key of the line that says what Next waits for on `step`, or None: none once Next can go on (`can`),
    none while the step's own work is under way (`busy`: a server being asked, the app downloading), whose card says
    what it is doing, and none on a step that never makes Next wait."""
    if can or busy:
        return None
    return NEEDS.get(step)


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
        app, ui, px, w = self.app, self.app.ui, self.app.ui.px, self.app.words
        root = app.root
        # The launcher's column: the wordmark and the version, then the six steps down the side, as the site's
        # numbered steps.
        self.rail = app.make_rail(root, steps=[w("guide.%s.name" % key) for key in STEPS])
        # The step's page: its question as the page's title over the site's field, its few words under it.
        self.body = app.make_page(root)
        # The column's foot: Skip, then Back and Next (PLAY on the last step, under Back), made after the page so that
        # Tab goes the page, then Skip, Back and Next.
        foot = app.make_foot(self.rail)
        # Leaving the guide for the launcher: a quiet link over the buttons, which the keyboard reaches too (shown by
        # show(), which leaves it out on the last step, where PLAY is the way on and the setting up is done).
        self.skip = skip = widgets.link(foot, ui, w("guide.skip"), lambda: self.finish(play=False), fg=theme.MUTED,
                                        font=app.fonts.small, chevron=False)
        self.buttons = tk.Frame(foot, bg=theme.STRIP)
        self.buttons.pack(side="top", fill="x")
        self.back_button = widgets.Button(self.buttons, ui, w("guide.back"), self.back)
        self.back_button.pack(side="left")
        self.next_button = widgets.Button(self.buttons, ui, w("guide.next"), self.next, kind="primary")
        self.next_button.pack(side="right")
        # The last step's PLAY: the launcher's own lime slab under Back (not packed until then).
        self.play_slab = widgets.PlaySlab(foot, ui, w("bottom.play"), self.next, width=self.rail.inner_width())
        self.foot = foot
        self.show(self.index)

    # ------------------------------------------------------------------------------------- steps

    def show(self, index):
        self.index = index
        app, w = self.app, self.app.words
        # A progress bar of the page that went: the download's progress waits for the next one.
        app.download_bar = None
        # The step that went took its own update with it (SOUND & SCREEN sets its own).
        app.page_follow = None
        key = STEPS[index]
        # The step made off the screen while the one on show stays whole on it, then put in its place with its title,
        # its step in the column and its buttons, all at once (widgets.ScrollArea.show_page), as a page is.
        content = self.body.new_page()
        # The step's cards, each made again in place when what it shows changes (pages.Sections): an answer from the
        # server, a sign-in, a download that ended change their own card, never the step drawn again.
        self.sections = pages.Sections(content, app.ui)
        getattr(self, "_" + key)(content)
        # What Next waits for is said at the foot of the step's last card, inside it with the card's own padding
        # (_update_next makes the line there, again when the card is made anew).
        self.content = content
        # One column for the names of the step's settings, as a page has (pages.ROWS_THAT_COME names the guide's own as
        # "guide:<step>", apart from the pages' names).
        widgets.fit_names(content, app.ui, pages.rows_that_come("guide:" + key))
        # The step's question as the page's title, in the player's language (the strip above names the step), and its
        # few words under it.
        lead = LEADS.get(key)
        self.body.set_heading(w("guide.%s.title" % key), w(lead) if lead else "")
        self.rail.set_step(index)
        self.back_button.enable(index > 0)
        last = index == len(STEPS) - 1
        # Next on every step but the last, where the big PLAY takes its place under Back; Skip over them on every step
        # but the last too, as the last one sets nothing up that Skip would leave undone.
        px = self.app.ui.px
        if last:
            self.next_button.pack_forget()
            self.skip.pack_forget()
            self.play_slab.pack(side="top", anchor="w", pady=(px(16), 0))
        else:
            self.play_slab.pack_forget()
            self.next_button.pack(side="right")
            if not self.skip.winfo_manager():
                self.skip.pack(side="top", anchor="w", before=self.buttons, pady=(0, px(10)))
        self._update_next()
        # Then the step in place of the one on show, drawn with its title, its step and its buttons in one turn.
        self.body.show_page(content)

    def redraw(self):
        """The step on show follows a change (an answer came, a sign-in, a download that ended): its cards whose
        content changed made again in their places, Next and the line about what it waits for as things stand."""
        if self.app.guide is not self:
            return
        sections = getattr(self, "sections", None)
        if sections is not None and sections.parent.winfo_exists():
            sections.refresh()
            self._update_next()
            return
        pages.keep_place(self.body, self.app.root, lambda: self.show(self.index))

    def _can_go_on(self):
        """SERVER needs a server that answered; SIGN IN a sign-in; DOWNLOAD the app; the last step what PLAY needs."""
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
        # The line under the step's card: what Next waits for while it waits, nothing once it can go on.
        key = STEPS[self.index]
        busy = self.checking if key == "server" else (self.app.download is not None if key == "download" else False)
        need = waits_for(key, can, busy)
        line = self._need_line(make=bool(need))
        if line is not None:
            if need:
                line.set(self.app.words(need))
                if not line.winfo_manager():
                    # The last thing in the card, a row's gap under what is over it.
                    line.pack(fill="x", pady=(self.app.ui.px(NEED_GAP), 0))
            elif line.winfo_manager():
                line.pack_forget()
        # The last step's PLAY lit when the ready check lets it go, dark and still otherwise.
        self.play_slab.set("ready" if can else "waiting")

    def _need_line(self, make):
        """The line that says what Next waits for, at the foot of the step's last card: the one there, or a new one when
        `make` (the card was made anew since, or the step just showed). None when the step has no card."""
        content = getattr(self, "content", None)
        if content is None or not content.winfo_exists():
            return None
        found, cards = [content], []
        while found:
            widget = found.pop(0)
            if isinstance(widget, widgets.Card):
                cards.append(widget)
                continue
            found.extend(widget.winfo_children())
        if not cards:
            return None
        # The last card down the step.
        card = max(cards, key=lambda c: (c.winfo_y() + c.master.winfo_y(), cards.index(c)))
        line = getattr(card, "odq_need", None)
        if (line is None or not line.winfo_exists()) and make:
            line = card.odq_need = widgets.Said(card.body, self.app.ui)
        return line if line is not None and line.winfo_exists() else None

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
        # One card: the language as a setting's row, then where the app comes from and what is needed, each under its
        # sub-heading, a faint line between the three.
        card = pages._card(parent, ui, None, last=True)
        widgets.setting_row(card.body, ui, w("about.language"),
                            lambda p: widgets.Segmented(p, ui, pages.language_options(app),
                                                        app.state.picked_language or "system", self._language)).pack(
            fill="x")
        for title, lines in (("guide.power.notice.title", ("guide.power.notice",)),
                             ("guide.power.need", ("guide.power.need.1", "guide.power.need.2"))):
            widgets.divider(card.body, ui, pady=widgets.ROW_GAP)
            # A fact to know, nothing to beware of: its sub-heading in the labels' face, its lines under it.
            tk.Label(card.body, text=w(title), font=ui.fonts.body_bold, fg=theme.TEXT, bg=theme.PANEL).pack(
                anchor="w", pady=(0, ui.px(pages.FORM_LABEL_GAP)))
            for i, key in enumerate(lines):
                widgets.label(card.body, ui, w(key), fg=theme.MUTED, wrap_margin=0).pack(
                    fill="x", pady=(ui.px(4) if i else 0, 0))

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
        # The address, Connect, and one line under them: connecting, connected, or why not (in place).
        self.sections.add(lambda: (app.state.current,), lambda holder: pages.connect_panel(app, holder, self.redraw))

    # ------------------------------------------------------------------------------ 3 SIGN IN

    def _login(self, parent):
        app = self.app
        _server_key, signin_key, _app_key, _others = pages.online_keys(app)
        self.sections.add(signin_key, lambda holder: pages.signin_panel(app, holder, self.redraw))

    # ----------------------------------------------------------------------------- 4 DOWNLOAD

    def _download(self, parent):
        app = self.app
        server = app.state.server()
        if server is not None and app.download is None and apps.local(server["url"]) is None and not self.download_tried:
            # The app is what this step is for: its download starts by itself, once.
            self.download_tried = True
            app.get_app(done_then=lambda error: self.redraw())
        _server_key, _signin, app_key, _others = pages.online_keys(app)
        self.sections.add(app_key, lambda holder: pages.app_panel(app, holder, self.redraw))

    # -------------------------------------------------------------------------- 5 SOUND & SCREEN

    def _sound(self, parent):
        app = self.app
        # The same rows as the Sound and Screen pages, the ones a first start needs: the volumes and the screen (the
        # display's mode, then the frames) side by side, one height (one under another in a narrow window, the volumes
        # first, in view without scrolling in the smallest window).
        left, right = pages._columns(parent, app.ui, weights=(1, 1))
        sound = pages.sound_rows(app, left, full=False, fill=True)
        screen = pages.screen_rows(app, parent, full=False, frames_in=right)
        # What the player's in-game menu writes back shows here as on the pages (app.took_back).
        app.page_follow = lambda: (sound(), screen())

    # ------------------------------------------------------------------------- 6 STAGE START

    def _stage(self, parent):
        app, w = self.app, self.app.words
        # The ready check before the first song, the step's one card, its light as PLAY's (no Check again: the step
        # asks again by itself).
        pages.checks_card(app, parent, w("play.ready"), recheck=False)
        app.refresh_checks()
        pages.refresh_checks(app)

    def checks_changed(self):
        """The ready check came back (app._checked): the last step's PLAY follows it."""
        self._update_next()
