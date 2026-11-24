"""The launcher's pages, as the site's: a title in the wide face and a line under it (heading), then cards. Each builder
fills the page's column.

A setting row changes the remembered state right away (app.changed); the player reads the settings at the next PLAY,
so nothing changes under a game that is running.
"""

import logging
import os
import re
import threading
import tkinter as tk

from PIL import ImageTk

from opendmtq_client import actions, apps, art, dialogs, displays, i18n, keys, maintenance, player, theme, updates, widgets
from opendmtq_client import server as srv
from opendmtq_client import state as st
from opendmtq_client import values as choices

log = logging.getLogger("opendmtq_client")

# ------------------------------------------------------------------------------------------- headings

# Each page's title, in English in both languages as the site's page titles and the game's menus are.
TITLES = {"play": "PLAY", "screen": "SCREEN", "sound": "SOUND", "controls": "CONTROLS", "online": "ONLINE",
          "help": "HELP", "about": "LAUNCHER"}


def heading(app, page):
    """A page's title and the line under it, what the page is for. PLAY has its title alone: its head card, right under
    it, is the line (the server it plays on, large, and the sign-in), where a line naming the server said it twice."""
    if page == "play":
        return TITLES[page], ""
    return TITLES[page], app.words(page + ".sub")


def main_button(app, parent, text, command):
    """A page's main action (Connect, Sign in, the app's download, the launcher's update) as a button: lit in lime while
    PLAY is not, and quiet beside a lit PLAY, so that a screen has one lime main action. It follows PLAY as PLAY
    changes (app._paint_play); the guide's steps, which have no PLAY, light it."""
    button = widgets.Button(parent, app.ui, text, command, kind="secondary" if app.play_lit() else "primary")
    app.main_buttons.append(button)
    return button


def _card(parent, ui, title, last=False, fill=False):
    """A card with its title, stacked under the ones before it with the site's gap between cards. `fill`: as tall as
    its place (a card in a row of two, drawn as tall as the other)."""
    card = widgets.Card(parent, ui, title)
    if fill:
        card.pack(fill="both", expand=True, pady=(0, 0 if last else ui.px(CARD_GAP)))
    else:
        card.pack(fill="x", pady=(0, 0 if last else ui.px(CARD_GAP)))
    return card


# The gap between two cards (the site's --gap is 20 px; the window is smaller than a page).
CARD_GAP = 16


def _holder(parent, bg=None):
    """The frame a card of Sections is made in: no colour of its own, as its card covers it whole. A frame in the
    field's colour was put on the screen a moment before its card and painted flat over the page's picture until the
    card came (a dark slab where the connection test's card was about to show); with none, the screen paints nothing
    for it and the page shows under it until its card does. Told apart by what it holds (widgets.ScrollArea's field,
    widgets.Card's cut). `bg`: a row's holder inside a card, in the card's own colour (rows are made with their
    parent's)."""
    holder = tk.Frame(parent, bg=bg or "")
    holder.odq_holder = bg is None
    return holder


class Sections:
    """A page's cards, each made by its own builder from what it shows (its key, a function of the launcher's state):
    refresh() makes again only the cards whose key changed, each in its own place, the others as they were. An answer
    that came (a server connected, a sign-in, a download done, a game that ended) changes its own card, never the page
    drawn again (client/tests/ui/flicker.py)."""

    def __init__(self, parent, ui, after=None, first_gap=0, bg=None, lines=False):
        self.parent, self.ui, self.after = parent, ui, after
        # The holders' colour: none on the page's field (_holder), a card's own for rows made again inside a card.
        self.bg = bg
        # `lines`: rows of one card, a faint line between two shown rows with a row's room either side of it (as a
        # card's RowList has), instead of the cards' gap.
        self.lines = lines
        # The gap above the first card on show (logical pixels): 0 where the cards start the page, a card's gap where
        # they come under something else of it (PLAY's records under its two columns).
        self.first_gap = first_gap
        # Each card: its holder frame (in the page's order), its key, its builder, the key it was made for, and the
        # gap above it now.
        self.items = []

    def add(self, key, build, expand=False):
        """A card at the end, made now: `build(holder)` makes it in its holder, `key()` says what it shows. `expand`:
        the holder takes the height left to its column (the PLAY page's Last game)."""
        holder = _holder(self.parent, self.bg)
        item = {"holder": holder, "key": key, "build": build, "made": object(), "gap": None, "expand": expand}
        self.items.append(item)
        self._make(item)
        return holder

    def _make(self, item):
        """The card made (again) in its holder; the holder shown in its place while it holds something. A card on show is
        made anew in a holder of its own laid over it, then put in its place: the old card stays on the screen until the
        new one is drawn whole, never a gap where it was."""
        holder = item["holder"]
        if holder.winfo_children() and holder.winfo_ismapped():
            self._swap(item)
            return
        for child in holder.winfo_children():
            child.destroy()
        item["build"](holder)
        if not self.lines:
            # The gap between two cards is the holders' (_gaps), not the cards' own: a card made last today may have
            # another under it tomorrow. (Rows keep their own room between them: a form's field rows.)
            for child in holder.pack_slaves():
                child.pack_configure(pady=0)
        # What it was made for, as the state is once it is made (a builder may start work that changes it).
        item["made"] = item["key"]()
        shown = bool(holder.winfo_children())
        if shown and not holder.winfo_manager():
            later = [i["holder"] for i in self.items[self.items.index(item) + 1:] if i["holder"].winfo_manager()]
            fill = {"fill": "both", "expand": True} if item["expand"] else {"fill": "x"}
            if later:
                holder.pack(before=later[0], **fill)
            else:
                holder.pack(**fill)
        elif not shown and holder.winfo_manager():
            holder.pack_forget()
        if not shown:
            # Packed again later with its gap set afresh.
            item["gap"] = None
        self._gaps()

    def _swap(self, item):
        """The card on show made anew over it, laid out and drawn there, then put in its place (_make)."""
        self._put(self._over(item))

    def _over(self, item):
        """The new card for `item` made in a holder of its own laid over the old one (as wide as it, as tall as it asks),
        so that it is laid out and drawn while the old one is still under it. Returns (item, the new holder)."""
        old = item["holder"]
        fresh = _holder(self.parent, self.bg)
        fresh.place(in_=old, x=0, y=0, relwidth=1.0)
        item["build"](fresh)
        if not self.lines:
            for child in fresh.pack_slaves():
                child.pack_configure(pady=0)
        return item, fresh

    def _put(self, made, laid=False):
        """The new holder in the old one's place, with its packing, and the old one gone: one change of the page's
        layout. `laid`: the new one was laid out already (refresh lays out all of them at once)."""
        item, fresh = made
        old = item["holder"]
        if not laid:
            fresh.update_idletasks()
        info = old.pack_info()
        fresh.place_forget()
        info.pop("in", None)
        fresh.pack(before=old, **info)
        old.destroy()
        item["holder"] = fresh
        item["made"] = item["key"]()
        if not fresh.winfo_children():
            # The card went (nothing to show now): its place goes too.
            fresh.pack_forget()
            item["gap"] = None
        self._gaps()

    def _gaps(self):
        """The cards' gap above each shown card but the first; for rows (lines), the faint line before each shown row
        but the first, right before it, and none before a row that is not shown."""
        first = True
        for item in self.items:
            holder = item["holder"]
            line = item.get("line")
            if not holder.winfo_manager():
                if line is not None and line.winfo_exists() and line.winfo_manager():
                    line.pack_forget()
                continue
            if self.lines:
                wanted = 0
                if first:
                    if line is not None and line.winfo_exists() and line.winfo_manager():
                        line.pack_forget()
                else:
                    if line is None or not line.winfo_exists():
                        line = item["line"] = tk.Frame(self.parent, bg=theme.DIVIDER, height=1)
                    slaves = self.parent.pack_slaves()
                    where = slaves.index(holder)
                    if not line.winfo_manager() or where == 0 or slaves[where - 1] is not line:
                        # Packed again only when it is not right before its row already (a row made anew over the old
                        # one takes the old one's place, after its line).
                        line.pack(fill="x", before=holder, pady=self.ui.px(widgets.ROW_GAP))
            else:
                wanted = self.ui.px(self.first_gap) if first else self.ui.px(CARD_GAP)
            if item["gap"] != wanted:
                holder.pack_configure(pady=(wanted, 0))
                item["gap"] = wanted
            first = False

    def refresh(self):
        """Each card whose key changed made again in its place; True when any was. The cards on show that change are
        made over their old ones first, all of them laid out and drawn together, then all put in place at once: one
        change of the page's layout whatever the number of cards."""
        changed = False
        over = []
        for item in self.items:
            if not item["holder"].winfo_exists():
                return changed
            if item["key"]() != item["made"]:
                changed = True
                if item["holder"].winfo_children() and item["holder"].winfo_ismapped():
                    over.append(self._over(item))
                else:
                    self._make(item)
        if over:
            self.parent.update_idletasks()
            for made in over:
                self._put(made, laid=True)
        if changed and self.after is not None:
            # What the page does once a card of it is made again (its names' column fitted to the new rows).
            self.after()
        return changed

# The names of the setting rows the PC brings to a page or takes from it (the game's log once the game has run, Repair and
# Uninstall in an installed launcher): counted in the page's names' column whether shown or not (widgets.fit_names), so
# that none of them moves the controls when it comes. The rows a choice brings (a window's size, the counter's corner,
# the upscaler) are made with their page, hidden while they do not apply, and counted as they are.
ROWS_THAT_COME = {
    "help": ("help.player_log", "help.repair.row", "help.uninstall.row"),
    # The server card's rows that come and go with the sign-in and the other servers.
    "online": ("online.address", "online.account.signed", "online.id", "online.password", "online.app", "online.others"),
}


def rows_that_come(page):
    """The names of ROWS_THAT_COME[page] in both languages, for widgets.fit_names."""
    return [words for key in ROWS_THAT_COME.get(page, ()) for words in i18n.TEXT[key] if words]


def _columns(parent, ui, weights=(3, 2), gap_above=0, bg=theme.BG, stack_below=None):
    """Cards side by side: a frame for each column, as wide as its share of the row less the gaps; one under another
    when the row is narrower than STACK_BELOW (the smallest window, beside the menu column). The shares come from the
    row's own width alone: a grid that sized them from what they hold would loop for ever, as the text in each wraps to
    the width it is given and so asks for what it got (one pixel going back and forth between the columns). `bg`: the
    page's field, or a card's deck for lists side by side in a card; `stack_below` another width for those."""
    row = tk.Frame(parent, bg=bg)
    row.pack(fill="x", pady=(ui.px(gap_above), 0))
    columns = []
    for i in range(len(weights)):
        column = tk.Frame(row, bg=bg)
        columns.append(column)
    laid = {"stacked": None}

    def fit(event):
        stacked = event.width < ui.px(stack_below or STACK_BELOW)
        if stacked != laid["stacked"]:
            # Laid out again only when the arrangement changes: the cells' places, then their widths below.
            laid["stacked"] = stacked
            for i, column in enumerate(columns):
                if stacked:
                    column.grid(row=i, column=0, sticky="nsew", padx=0, pady=(ui.px(CARD_GAP) if i else 0, 0))
                else:
                    column.grid(row=0, column=i, sticky="nsew", padx=(ui.px(CARD_GAP) if i else 0, 0), pady=0)
        if stacked:
            row.columnconfigure(0, minsize=event.width, weight=0)
            for i in range(1, len(weights)):
                row.columnconfigure(i, minsize=0, weight=0)
            return
        room = max(1, event.width - ui.px(CARD_GAP) * (len(weights) - 1))
        given = 0
        for i, weight in enumerate(weights):
            width = room * weight // sum(weights) if i < len(weights) - 1 else room - given
            given += width
            row.columnconfigure(i, minsize=width + (ui.px(CARD_GAP) if i else 0), weight=0)

    row.bind("<Configure>", fit)
    # Side by side until the row is laid out (the first <Configure> settles it).
    for i, column in enumerate(columns):
        column.grid(row=0, column=i, sticky="nsew", padx=(ui.px(CARD_GAP) if i else 0, 0))
    row.odq_stacked = lambda: bool(laid["stacked"])
    return columns


# A row of cards side by side narrower than this (logical pixels) puts them one under another.
STACK_BELOW = 760


# ---------------------------------------------------------------------------------------------- PLAY


def server_silent(app):
    """True when the last ready check that came back found the server PLAY plays on not answering (app.shown_checks:
    it stays while the next check is made, so that the server card does not change back and forth meanwhile)."""
    return any(c.key == "server" and not c.ok and not c.blocks for c in (app.shown_checks or ()))


# The page's head card's cut corners (logical pixels): its top one deeper than a card's 16, and its foot's, the hero of
# the page.
HEAD_CUT, HEAD_FOOT = 24, 12
# The room inside the player's plate on the head card, at its sides and over and under its line (logical pixels).
PLATE_PADX, PLATE_PADY = 10, 4


def server_state(app):
    """How the server PLAY plays on stands as the last ready check found it, for the head's light: "ok" (it answers),
    "change" (it does not), or "wait" (no check has come back yet)."""
    if server_silent(app):
        return "change"
    if any(c.key == "server" and c.ok for c in (app.shown_checks or ())):
        return "ok"
    return "wait"


def _server_card(app, parent):
    """PLAY's head, the page's hero: the server it plays on, its light (lime while it answers, a yellow ring while it
    does not) and its name large, its address under it, then the player on a plate (the sign-in's lamp and words: who
    is signed in, or that the sign-in ended); its button at the right on the block's middle (Connect, Sign in, or the
    player's page on the site). While the server does not answer, the plate says so (a sign-in cannot reach it then:
    Sign in stays plain, never the screen's lime action). A larger cut than a card's, as the page's first card."""
    ui, w, px = app.ui, app.words, app.ui.px
    # The hero's surface: a step nearer than the deck, its edge's light brighter, its corners cut deeper than a card's
    # and the foot's too, the family's silhouette at the page's head.
    card = widgets.Card(parent, ui, cut=HEAD_CUT, foot=HEAD_FOOT, fill=theme.PANEL_HI, rim=theme.RIM_HI)
    card.pack(fill="x")
    server = app.state.server()
    bg = card.fill
    line = tk.Frame(card.body, bg=bg)
    line.pack(fill="x")
    if server is None:
        # No server yet: what to do, and Connect, the screen's main action.
        button = main_button(app, line, w("play.connect"), lambda: app.nav_go("online"))
        button.pack(side="right", padx=(px(16), 0))
        widgets.label(line, ui, w("play.no_server"), wrap_margin=0).pack(side="left", fill="x", expand=True)
        return
    signed, silent = app.state.signed_in(server), server_silent(app)
    if not signed and silent:
        # The way to the sign-in all the same, plain while the server cannot take one.
        button = widgets.Button(line, ui, w("online.signin"), lambda: app.nav_go("online"))
    elif not signed:
        button = main_button(app, line, w("online.signin"), lambda: app.nav_go("online"))
    else:
        # The player's page on the site in the PC's browser, signed in already by a one-time link the server makes for
        # this sign-in (app.open_my_page): plain, as PLAY is the screen's main action.
        button = widgets.Button(line, ui, w("play.mypage"), app.open_my_page)
    # At the block's right, on its middle (pack's own), the room of a gutter before it.
    button.pack(side="right", padx=(px(16), 0))
    words = tk.Frame(line, bg=bg)
    words.pack(side="left", fill="x", expand=True)
    # The server's light before its name, on the name's middle: whether it answers, as the last ready check found it.
    name_line = tk.Frame(words, bg=bg)
    name_line.pack(fill="x")
    state = server_state(app)
    colour = {"ok": theme.OK, "change": theme.WARN, "wait": theme.FAINT}[state]
    widgets.lamp(name_line, ui, colour, bg=bg, hollow=state != "ok").pack(side="left", padx=(0, px(8)))
    if st.has_own_name(server):
        # Its name, large, and its address under it, from the name's own left edge.
        widgets.label(name_line, ui, server["name"], font=ui.fonts.head, wrap_margin=0).pack(side="left", fill="x",
                                                                                            expand=True)
        address = widgets.label(words, ui, server["url"], font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0)
        address.pack(fill="x", pady=(px(2), 0))
    else:
        # A server with no name of its own calls itself by its address: said once, in the name's place.
        widgets.label(name_line, ui, server["url"], font=ui.fonts.head, wrap_margin=0).pack(side="left", fill="x",
                                                                                           expand=True)
    if silent:
        # What stands in the way first: the server does not answer (the ready check's Server row leads to the test).
        said, tone = w("play.server_down"), "change"
    else:
        said = (w("play.signed", account=server["account"]) if signed else
                w("play.not_signed", account=server["account"]) if server.get("account") else w("play.no_account"))
        tone = "ok" if signed else "change"
    _player_plate(app, words, said, tone).pack(anchor="w", pady=(px(10), 0))


def _player_plate(app, words_frame, said, tone):
    """The player on a plate under the head's name: a small plate let into the hero as a field is (the inputs' dark),
    its corner cut as a card's, the sign-in's lamp and its words on one line (wrapping within the head's words when
    long), as a name plate is set on a game's player card."""
    ui, px = app.ui, app.ui.px
    surface = theme.FIELD
    plate = tk.Frame(words_frame, bg=surface)
    light = widgets.lamp(plate, ui, {"ok": theme.OK, "change": theme.WARN, "bad": theme.BAD}[tone], bg=surface,
                         hollow=tone == "change")
    light.pack(side="left", anchor="n", padx=(px(PLATE_PADX), 0), pady=(px(PLATE_PADY), px(PLATE_PADY)))
    # The words' line on the lamp's middle, as a ready-check row's (widgets.check_line).
    middle = px(PLATE_PADY) + light.winfo_reqheight() / 2.0
    top = max(0, int(round(middle - ui.fonts.body.metrics("linespace") / 2.0)))
    text = tk.Label(plate, text=said, font=ui.fonts.body, fg=theme.TEXT, bg=surface, justify="left", anchor="w")
    text.pack(side="left", anchor="n", padx=(px(6), px(PLATE_PADX)), pady=(top, 0))

    def fit(event=None):
        # As wide as the words take, up to the head's words' room less the plate's own: a long line wraps there.
        room = words_frame.winfo_width() - light.winfo_reqwidth() - px(6 + 2 * PLATE_PADX)
        if room > 1 and str(text.cget("wraplength")) != str(room):
            text.configure(wraplength=room)

    words_frame.bind("<Configure>", fit, add="+")
    # The plate's cut corner, as small as the plate (the page's cards' form at its size).
    cut = px(8)
    beyond = words_frame.cget("bg")
    corner = tk.Label(plate, bd=0, highlightthickness=0, bg=beyond)
    picture = art.corner(cut, surface, beyond)
    corner.odq_image = ImageTk.PhotoImage(picture, master=plate)
    corner.odq_picture = picture
    corner.configure(image=corner.odq_image)
    corner.place(relx=1.0, x=-cut, y=0, width=cut, height=cut)
    return plate


def build_play(app, parent):
    ui = app.ui
    # The page's head: the server it plays on and the sign-in there (Sections: made again only when what it shows
    # changed, in its own place).
    head = Sections(parent, ui)
    head.add(lambda: _server_key(app), lambda holder: _server_card(app, holder))
    # Then the ready check and how the last game went, side by side and one height (3:2, the ready check's rows the
    # wider), one under another in a narrow window. The ready check is made once: its rows follow each check in place
    # (refresh_checks).
    left, right = _columns(parent, ui, weights=(3, 2), gap_above=CARD_GAP)
    ready = Sections(left, ui)
    ready.add(lambda: None, lambda holder: _ready_card(app, holder), expand=True)
    last = Sections(right, ui)
    last.add(lambda: repr(sorted((app.state.last_session or {}).items())), lambda holder: _last_card(app, holder),
             expand=True)
    # The signed-in player's records on the server under them, across the page (none while not signed in).
    records = Sections(parent, ui, first_gap=CARD_GAP)
    records.add(lambda: records_key(app), lambda holder: _records_card(app, holder))
    # Each part made again in place when what it shows changed; the page's update follows all of them.
    app.page_follow = lambda: any([part.refresh() for part in (head, ready, last, records)])
    # Made again each time the page shows: a sign-in can have ended, or an app come, since the last one. Until it
    # comes back, the box says it is being made.
    app.refresh_checks()
    refresh_checks(app)
    app.refresh_records()


def checks_card(app, parent, title, recheck=True, fill=False):
    """A ready check's card (PLAY's, Help's, the guide's last step's): a checklist, a row a check filled in when the
    worker thread finishes it (refresh_checks), its title led by the whole check's light (lime when every row is fine,
    a yellow ring when one will change, red when one stops PLAY), Check again at the title's right end."""
    ui, w = app.ui, app.words
    # A status panel: its title and its light on the header strip.
    card = widgets.Card(parent, ui, title, strip=theme.STRIP_HEAD)
    card.pack(fill="both" if fill else "x", expand=bool(fill))
    # Before the title, on its line's middle: the light the rows' worst state gives (refresh_checks sets it).
    light = tk.Label(card.head, bd=0, bg=card.head.cget("bg"))
    light.pack(side="left", before=card.title, padx=(0, ui.px(8)))
    app.check_light = light
    _paint_check_light(app, None)
    if recheck:
        widgets.Button(card.head, ui, w("help.recheck"), lambda: app.refresh_checks(force=True)).pack(side="right")
    app.check_box = tk.Frame(card.body, bg=theme.PANEL)
    app.check_box.pack(fill="x")
    return card


def _paint_check_light(app, state):
    """The ready check's light in a state: "ok", "change", "bad", or None (no check has come back yet: a faint ring)."""
    light = getattr(app, "check_light", None)
    if light is None or not light.winfo_exists() or getattr(light, "odq_state", "") == state:
        return
    colour, hollow = {"ok": (theme.OK, False), "change": (theme.WARN, True), "bad": (theme.BAD, False),
                      None: (theme.FAINT, True)}[state]
    picture = art.lamp(colour, app.ui.scale, bg=light.cget("bg"), hollow=hollow, lead=False)
    light.odq_image = ImageTk.PhotoImage(picture, master=light)
    light.odq_picture = picture
    light.configure(image=light.odq_image)
    light.odq_state = state


def _ready_card(app, holder):
    """PLAY's ready check (checks_card), as tall as the last game beside it."""
    checks_card(app, holder, app.words("play.ready"), fill=True)


def _server_key(app):
    """What the PLAY page's server card shows: the server, its name, its sign-in, whether it answers."""
    server = app.state.server()
    if server is None:
        return None
    return (server["url"], server["name"], st.has_own_name(server), app.state.signed_in(server), server.get("account"),
            server_silent(app), server_state(app))


# How many of each of the records' lists PLAY shows: the rest is on the player's page on the site.
RECORDS_SHOWN = 3


def records_key(app):
    """What PLAY's records card shows: the records the server gave for the sign-in in use, or None (not signed in, not
    asked yet, or a server from before records)."""
    key, kept = app.records_key(), app.records
    if key is None or kept is None or kept["key"] != key or kept["answer"] is None:
        return None
    return key, repr(kept["answer"])


def _records_card(app, holder):
    """PLAY's My records: the signed-in player's latest plays and best records on the server, side by side (one under the
    other in a narrow window), each with the chart, the score after the keyboard's mark when a keyboard played it, and
    the player's place on that chart; one line instead for an account linked to no player, or one with no plays."""
    if records_key(app) is None:
        return
    ui, w = app.ui, app.words
    answer = app.records["answer"]
    # A scoreboard: a status panel's strip, its two corners cut as the game's panels (the last game's), its scores in the
    # game's wide face.
    card = widgets.Card(holder, ui, w("play.records"), foot=True, strip=theme.STRIP_HEAD)
    card.pack(fill="x")
    if answer["player"] is None:
        # The site's account has no game player linked to it on this server (the owner links them).
        widgets.label(card.body, ui, w("play.records.unlinked", account=answer["account"] or app.records["key"][1]),
                      fg=theme.MUTED, wrap_margin=0).pack(fill="x")
        return
    if not answer["recent"] and not answer["best"]:
        widgets.label(card.body, ui, w("play.records.none"), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
        return
    left, right = _columns(card.body, ui, weights=(1, 1), bg=theme.PANEL, stack_below=RECORDS_STACK_BELOW)
    keys = False
    for column, title, rows, recent in ((left, w("play.records.recent"), answer["recent"], True),
                                        (right, w("play.records.best"), answer["best"], False)):
        widgets.label(column, ui, title, font=ui.fonts.body_bold, bg=theme.PANEL).pack(anchor="w",
                                                                                         pady=(0, ui.px(FORM_LABEL_GAP)))
        if not rows:
            widgets.label(column, ui, w("play.records.none"), fg=theme.MUTED, bg=theme.PANEL, wrap_margin=0).pack(fill="x")
        for i, row in enumerate(rows[:RECORDS_SHOWN]):
            if i:
                widgets.divider(column, ui, pady=CHECK_GAP)
            _record_row(app, column, row, recent)
            keys = keys or row["keys"]
    if keys:
        # What the keyboard's mark means, said once for every row that has it (never only by hover): at the strip's right
        # end, a key to the board as a scoreboard has one, its words on the title's baseline.
        legend = tk.Frame(card.head, bg=card.head.cget("bg"))
        _keys_mark(app, legend, bg=legend.cget("bg")).pack(side="left")
        said = widgets.label(legend, ui, w("play.records.keys"), font=ui.fonts.small, fg=theme.MUTED)
        said.pack(side="left", padx=(ui.px(6), 0))
        # The title stands on the middle of the strip's line (a button's height, pack's own centring): its baseline
        # there, and the key's words' top put on it (the mark on their middle, as it is in the legend).
        title, small = card.title, ui.fonts.small
        title_edge = (title.winfo_reqheight() - ui.fonts.card_title.metrics("linespace")) // 2
        baseline = (ui.px(widgets.Button.HEIGHT) - title.winfo_reqheight()) // 2 + title_edge + \
            ui.fonts.card_title.metrics("ascent")
        said_edge = (said.winfo_reqheight() - small.metrics("linespace")) // 2
        legend.pack(side="right", anchor="n", pady=(max(0, baseline - said_edge - small.metrics("ascent")), 0))


# The records' two lists stand side by side down to this width of the card's body (logical pixels): each list's rows then
# have room for a long title beside the score.
RECORDS_STACK_BELOW = 640


def _keys_mark(app, parent, bg=theme.PANEL):
    """The keyboard's mark as a label (art.keys_mark), the site's own, in the hints' colour on the card's deck (or on
    `bg`: the records' header strip)."""
    picture = art.keys_mark(theme.MUTED, app.ui.scale, bg=bg)
    image = ImageTk.PhotoImage(picture, master=parent)
    mark = tk.Label(parent, image=image, bg=bg, bd=0)
    # Kept on the label: Tk drops a picture the moment Python forgets it.
    mark.odq_image, mark.odq_picture = image, picture
    return mark


def _record_row(app, parent, row, recent):
    """One record, a scoreboard's line: the song's title, under it the chart and when (a play's new record said, in the
    colour of what went well), and at the right end the score in the game's wide face (the keyboard's mark before it)
    over the place on that chart. The title and the score on one baseline, the second lines on another, whatever the
    two faces' heights."""
    ui, w = app.ui, app.words
    title_font, score_font, small = ui.fonts.body, ui.fonts.score, ui.fonts.small
    # The first lines' tops that put the title's and the score's baselines on one line (the taller ascent sets it).
    title_top = max(0, score_font.metrics("ascent") - title_font.metrics("ascent"))
    score_top = max(0, title_font.metrics("ascent") - score_font.metrics("ascent"))
    # And the second lines' tops, the lower of the two first lines' feet for both.
    left_foot = title_top + title_font.metrics("linespace")
    right_foot = score_top + score_font.metrics("linespace")
    line = tk.Frame(parent, bg=theme.PANEL)
    line.pack(fill="x")
    end = tk.Frame(line, bg=theme.PANEL)
    end.pack(side="right", anchor="n", padx=(ui.px(12), 0))
    figure = tk.Frame(end, bg=theme.PANEL)
    figure.pack(anchor="e", pady=(score_top, 0))
    if row["keys"]:
        _keys_mark(app, figure).pack(side="left", padx=(0, ui.px(6)))
    # The score as the game's result screens set one, in the wide face, its digits right-aligned in the column.
    tk.Label(figure, text="{:,}".format(row["score"]), font=score_font, fg=theme.TEXT, bg=theme.PANEL).pack(side="left")
    if row["rank"]:
        place = tk.Label(end, text=w("play.records.place", n=row["rank"], all=max(row["players"], row["rank"])),
                         font=small, fg=theme.MUTED, bg=theme.PANEL)
        place.pack(anchor="e", pady=(max(0, left_foot - right_foot), 0))
        # Its room puts it on the second line's baseline (tests/ui/spacing.py takes it for no gap of the scale).
        place.odq_aligned = True
    words = tk.Frame(line, bg=theme.PANEL)
    words.pack(side="left", fill="x", expand=True)
    title = row["title"] or w("play.records.chart", id=row.get("chart", ""))
    widgets.label(words, ui, title, bg=theme.PANEL, wrap_margin=0).pack(fill="x", pady=(title_top, 0))
    # The chart as the launcher names a mode everywhere else ("3 LINE Hard 9", as How to play and Controls say it).
    sub = [whole_modes(choices.chart_words(row["chart_name"]))] if row["chart_name"] else []
    if row["at"]:
        sub.append(w.say(i18n.ago(row["at"])))
    if not recent and row["grade"]:
        sub.append(w("play.records.grade", grade=row["grade"]))
    new = recent and row["new_record"]
    if sub or new:
        second = tk.Frame(words, bg=theme.PANEL)
        second.pack(fill="x", pady=(max(0, right_foot - left_foot), 0))
        # Its room puts it on the place's baseline (tests/ui/spacing.py takes it for no gap of the scale).
        second.odq_aligned = True
        if sub:
            tk.Label(second, text="  ·  ".join(sub), font=small, fg=theme.MUTED, bg=theme.PANEL).pack(side="left")
        if new:
            # The player's own new record, in the colour of what went well: the one word of the list in colour.
            tk.Label(second, text=("  ·  " if sub else "") + w("play.records.new"), font=small, fg=theme.OK,
                     bg=theme.PANEL).pack(side="left")


def _last_card(app, holder):
    """The PLAY page's Last game, a result panel as the game sets one: how long it played as a figure in the game's wide
    face, how it ended under it, the state's colour only where it means something (a red light when the game closed by
    itself or could not start, nothing for a game closed as it should be); the player's log one press away after a
    crash. Its two corners cut, as the game's panels are; as tall as the ready check beside it, the result on the
    middle of the room under its strip, as a result is shown on its own."""
    ui, w, px = app.ui, app.words, app.ui.px
    # A status panel's strip, and the foot cut a game's panels have.
    last = widgets.Card(holder, ui, w("play.last"), foot=True, strip=theme.STRIP_HEAD)
    last.pack(fill="both", expand=True)
    record = app.state.last_session or {}
    if record.get("crashed") or record.get("failed_start"):
        # The reason is in the player's log: one press away, on the card's own line at its title's right end (as Help
        # has Check again).
        widgets.Button(last.head, ui, w("status.open_log"), app.open_player_log).pack(side="right")
    # The result as one block on the middle of the body's room (pack centres what it does not stretch): in one column,
    # where the card is only as tall as the result, at its top.
    result = tk.Frame(last.body, bg=theme.PANEL)
    result.pack(fill="x", expand=True)
    if not record:
        widgets.label(result, ui, w("play.last.none"), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
        return
    if record.get("failed_start"):
        widgets.check_line(result, ui, "bad", w("play.last.failed")).pack(fill="x")
        return
    seconds = record.get("seconds", 0)
    # The figure and its unit on one baseline: the length in whole minutes, or in seconds under a minute.
    figure = tk.Frame(result, bg=theme.PANEL)
    figure.pack(anchor="w")
    number = tk.Label(figure, text=str(seconds // 60 if seconds >= 60 else seconds), font=ui.fonts.figure,
                      fg=theme.TEXT, bg=theme.PANEL)
    number.pack(side="left", anchor="n")
    unit = tk.Label(figure, text=w("play.last.unit.min" if seconds >= 60 else "play.last.unit.s"), font=ui.fonts.body,
                    fg=theme.MUTED, bg=theme.PANEL)
    # Its baseline the figure's: down by the difference of their ascents.
    unit.pack(side="left", anchor="n", padx=(px(6), 0),
              pady=(max(0, ui.fonts.figure.metrics("ascent") - ui.fonts.body.metrics("ascent")), 0))
    if record.get("crashed"):
        widgets.check_line(result, ui, "bad", w("play.last.end.crash")).pack(fill="x", pady=(px(8), 0))
    else:
        widgets.label(result, ui, w("play.last.end.ok"), fg=theme.MUTED, wrap_margin=0).pack(fill="x", pady=(px(8), 0))


# A space that never ends a line (Tk breaks its lines at plain spaces only): inside a LINE mode's name ("2 LINE"), which
# reads as one thing, wherever it shows in a line that wraps (a record's chart, the Controls page's line under the keys).
NO_BREAK = "\u00a0"


def whole_modes(text):
    """`text` with each LINE mode's name in it kept whole on its line ("2 LINE" with a space that never ends one)."""
    return re.sub(r"(\d) LINE\b", "\\1" + NO_BREAK + "LINE", text)


def refresh_checks(app):
    """Fill the ready check (PLAY page, Help page, the guide's last step) from app.checks: a row a line, each with its
    lamp, its name, and at the right end what it is about or the way to fix it. The rows are made again only when what
    they say changed: a check that came back the same (the window asks again every half minute) leaves them be."""
    box = getattr(app, "check_box", None)
    if box is None or not box.winfo_exists():
        return
    ui, w = app.ui, app.words
    # While a check is made (it may ask the server for a few seconds), the last one that came back stays on show: the
    # rows do not blink to "..." and back each time a page asks for one.
    checks = app.checks if app.checks is not None else getattr(app, "shown_checks", None)
    if checks is None:
        _paint_check_light(app, None)
        if getattr(box, "odq_shown", None) != "waiting":
            for child in box.winfo_children():
                child.destroy()
            widgets.label(box, ui, "...", fg=theme.MUTED).pack(anchor="w")
            box.odq_shown = "waiting"
        return
    from opendmtq_client import installed
    # Asked once for every row: whether this launcher was installed, so that its player can be put back by Repair.
    root = installed.root()
    # Whether this PC's sign-in on the server ran out (an account it signed in as before), for the sign-in's row.
    server = app.state.server()
    ended = bool(server and server.get("account") and not app.state.signed_in(server))
    rows = [(check, check_row(check, w, on_play=app.page == "play" and app.guide is None, in_guide=app.guide is not None,
                              installed=bool(root), ended=ended)) for check in checks]
    # The whole check's light, its worst row's: a problem, then something that will change, else fine.
    states = [row["state"] for _check, row in rows]
    _paint_check_light(app, "bad" if "bad" in states else "change" if "change" in states else "ok")
    # What the rows say, in the window's language: the same as on show, nothing is made again.
    shown = tuple((check.key, w("check." + check.key), tuple(sorted(row.items()))) for check, row in rows)
    if getattr(box, "odq_shown", None) == shown:
        return
    for child in box.winfo_children():
        child.destroy()
    box.odq_shown = shown
    # The names' column of the rows: the widest name a row with a value or a way to fix it may have, in either language
    # (a game that is open says it across the row), so that the values stand on one line by their names, whichever
    # rows show.
    column = widgets.check_names(ui, [words for key in CHECK_NAMES for words in i18n.TEXT["check." + key] if words])
    for i, (check, row) in enumerate(rows):
        if i:
            widgets.divider(box, ui, pady=CHECK_GAP)
        # The row's way on: Repair runs here, a page name opens that page (none in the guide, which has no menu).
        action = None
        if row["go"] == "repair":
            # Repair runs on the click, under its own dialog.
            action = lambda: maintenance.repair_program(app)
        elif row["go"] == "test":
            # The connection test, on the Online page.
            action = app.test_from_play
        elif row["go"]:
            # The page it names, as the menu would open it.
            action = lambda p=row["go"]: app.nav_go(p)
        widgets.check_line(box, ui, row["state"], w("check." + check.key), row["link"], action,
                           value=row["value"], column=column).pack(fill="x")


# The room either side of the faint line between two rows of a list in a card (the ready check, Help's lines, the
# Controls page's lines), in logical pixels: on the launcher's spacing scale.
CHECK_GAP = 8
# The ready check's rows that carry a value or a way to fix it after their name (actions.ready_lines' keys): their names
# make the rows' names column (the game being open says it alone, across its row).
CHECK_NAMES = ("player", "server", "account", "app", "app_update")


def check_row(check, w, on_play=False, in_guide=False, installed=False, ended=False):
    """How a ready-check row says one check: {"state": "ok", "change" or "bad", "value": what the row says of it, or
    None, "link": the link's words or None, "go": "repair", a page's name or None}. A row that is not fine says what is
    wrong as its value, and the way to fix it follows (main showed a lamp and "ONLINE ›" alone for a sign-in or an app
    that is not there). A link is named after where it leads, as Help's lines name their pages: the page's name in the
    menu ("ONLINE ›"), the connection test, or Repair, which runs at once. `ended`: the sign-in this PC had on the server
    ran out (or its password changed), where none was ever made otherwise."""
    row = {"state": "ok", "value": None, "link": None, "go": None}
    if not check.ok and check.key == "player" and installed:
        # The player comes with the launcher: the installed one puts it back from its package, at once.
        row.update(state="bad", value=w("check.player.none"), link=w("check.player.repair"), go="repair")
    elif not check.ok and check.key == "player":
        # A copied folder: installing brings the player back, and no page here can.
        row.update(state="bad", value=w("check.player.missing"))
    elif check.ok:
        # What it is about, which a player wants to confirm: the server, the account, the app's date. The PLAY page's
        # server card above already names the server and the account.
        about = ("app",) if on_play else ("server", "account", "app")
        if check.key in about:
            row["value"] = check.detail
    elif check.play_fixes:
        # PLAY does these by itself; the row only says it will.
        row.update(state="change", value=w("play.will_get"))
    elif not check.blocks and check.key == "server":
        # The server does not answer: PLAY still plays this PC's app; the connection test says where the way to it stops
        # (none in the guide, which has no Online page to show it on).
        row.update(state="change", value=w("check.server.down"))
        if not in_guide:
            row.update(link=w("check.server.test"), go="test")
    else:
        # What stops PLAY is a problem; the rest will change once the player sees to it.
        row["state"] = "bad" if check.key in actions.BLOCKING else "change"
        # What is wrong, in a word: no server chosen, no sign-in (or one that ended), no app on this PC; a newer app on
        # the server says its date, as the app's own row does.
        row["value"] = {"server": w("check.server.none"),
                        "account": w("check.account.ended" if ended else "check.account.none"),
                        "app": w("check.app.none"),
                        "app_update": check.detail}.get(check.key)
        if check.page and not in_guide:
            # The page that sees to it, by the menu's own name; the guide has no menu to go to, so no link there.
            row.update(link=TITLES[check.page], go=check.page)
    return row


# -------------------------------------------------------------------------------------------- Screen


def screen_rows(app, parent, full=True, frames_in=None):
    """The Screen page's settings in their cards, which the guide's SOUND & SCREEN shows too (full=False: the ones a
    first start needs, in one card of the screen in `frames_in`, beside the volumes: the display's mode first, then the
    frames; a card of the mode alone across the step held a single setting). Every row is made once: a choice changes
    its own control, the hints that follow from it and the rows it brings or takes (shown or hidden in place,
    widgets.RowList), never the page (client/tests/ui/flicker.py)."""
    ui, w, v = app.ui, app.words, app.state.values
    display = displays.main_display(app.root)
    found = displays.connected()
    rows = {}

    def setter(name, value):
        app.changed(name, value)
        # The rows and hints that follow from it, in place.
        follow()

    # The groups side by side where the page is wide, one height (one under another in a narrow window): on the page,
    # Display and Quality, then Frames across the page under them; in the guide, the screen's one card beside the
    # volumes.
    if full:
        left, right = _columns(parent, ui, weights=(1, 1))
        card = _card(left, ui, w("screen.display"), last=True, fill=True)
    else:
        card = _card(frames_in, ui, w("guide.sound.screen"), last=True, fill=True)
    shown = widgets.RowList(card.body, ui)
    shown.pack(fill="x")
    slot = shown.add()
    # Its hint keeps the room of the longer of the two (widgets.keep_room): a window brings the window's size with it.
    rows["mode"] = widgets.setting_row(
        slot.body, ui, w("screen.mode"),
        lambda p: widgets.Segmented(p, ui, [("fullscreen", w("screen.mode.fullscreen")), ("window", w("screen.mode.window"))],
                                    v["display"], lambda value: setter("display", value)),
        w("screen.mode.hint." + v["display"]), hints=[w("screen.mode.hint." + m) for m in ("fullscreen", "window")])
    rows["mode"].pack(fill="x")
    if full:
        # Sizes that fit the display with room for the title bar and the taskbar (values.fits, which --set window= uses
        # too); fitted always stays.
        sizes = [size for size in choices.WINDOW_SIZES if choices.fits(size, display)]
        if v["window"] not in sizes:
            # A size set on the command line keeps its row.
            sizes.append(v["window"])
        options = [(size, w("screen.size.auto") if size == "auto" else size.replace("x", " × ")) for size in sizes]
        rows["size_slot"] = shown.add(shown=v["display"] == "window")
        widgets.setting_row(rows["size_slot"].body, ui, w("screen.size"),
                            lambda p: widgets.Select(p, ui, options, v["window"], lambda size: setter("window", size),
                                                     width=22),
                            w("screen.size.hint")).pack(fill="x")
        slot = shown.add()
        widgets.label(slot.body, ui, displays_line(w, display, found), font=ui.fonts.small, fg=theme.MUTED,
                      wrap_margin=0).pack(fill="x")
    # The frame limits: the display's own rate, every rate up to the fastest display's, and no limit (fps_options).
    # The main display's rate as it runs a game (game_rate), for the hints when the displays are not listed.
    hz = game_rate(display)
    if full:
        # Quality beside Display, made before Frames: Tab goes as the page reads, the pair, then the line under it.
        quality = _card(right, ui, w("screen.picture"), last=True, fill=True)
        card = widgets.Card(parent, ui, w("screen.frames"))
        card.pack(fill="x", pady=(ui.px(CARD_GAP), 0))
        frames = widgets.RowList(card.body, ui)
        frames.pack(fill="x")
    else:
        # The guide's frames in the same card's rows, under the mode.
        quality = None
        frames = shown
    rows["vsync"] = widgets.setting_row(
        frames.add().body, ui, w("screen.vsync"),
        lambda p: widgets.Toggle(p, ui, v["vsync"] == "on", lambda on: setter("vsync", "on" if on else "off")), " ")
    rows["vsync"].pack(fill="x")
    rows["fps"] = widgets.setting_row(
        frames.add().body, ui, w("screen.fps"),
        lambda p: widgets.Select(p, ui, fps_options(w, found, hz, v["fps"]), v["fps"], lambda f: setter("fps", f),
                                 width=22), " ")
    rows["fps"].pack(fill="x")
    # The frame counter over the game, on or off; while on, its corner (the bottom right unless another is picked). Its
    # hint keeps the room of the longer of the two, as Mode's does: on brings the corner's row.
    rows["counter"] = widgets.setting_row(
        frames.add().body, ui, w("screen.counter"),
        lambda p: widgets.Toggle(p, ui, v["show_fps"] == "on", lambda on: setter("show_fps", "on" if on else "off")),
        " ", hints=[w("screen.counter.hint." + state) for state in ("on", "off")])
    rows["counter"].pack(fill="x")
    options = [(corner, w("screen.counter.position." + corner)) for corner in choices.FPS_POSITION]
    rows["corner_slot"] = frames.add(shown=v["show_fps"] == "on")
    widgets.setting_row(rows["corner_slot"].body, ui, w("screen.counter.position"),
                        lambda p: widgets.Select(p, ui, options, v["fps_position"],
                                                 lambda corner: setter("fps_position", corner), width=22),
                        w("screen.counter.position.hint")).pack(fill="x")
    if full:
        picture = widgets.RowList(quality.body, ui)
        picture.pack(fill="x")
        options = [(scale, w("screen.scale.full") if scale == "100" else "%s%%" % scale) for scale in choices.RENDER_SCALE]
        widgets.setting_row(picture.add().body, ui, w("screen.scale"),
                            lambda p: widgets.Select(p, ui, options, v["render_scale"],
                                                     lambda scale: setter("render_scale", scale), width=22),
                            w("screen.scale.hint")).pack(fill="x")
        # What makes the picture of a lower scale the area's size, there only below 100 %; its hint says what the
        # chosen one does.
        options = [(kind, w("screen.upscaler." + kind)) for kind in choices.UPSCALER]
        rows["upscaler_slot"] = picture.add(shown=v["render_scale"] != "100")
        rows["upscaler"] = widgets.setting_row(
            rows["upscaler_slot"].body, ui, w("screen.upscaler"),
            lambda p: widgets.Select(p, ui, options, v["upscaler"], lambda kind: setter("upscaler", kind), width=22), " ")
        rows["upscaler"].pack(fill="x")
        # The edges smoothed, at any scale; its hint says what the chosen one does.
        options = [(kind, w("screen.aa." + kind)) for kind in choices.ANTI_ALIASING]
        rows["aa"] = widgets.setting_row(
            picture.add().body, ui, w("screen.aa"),
            lambda p: widgets.Select(p, ui, options, v["anti_aliasing"], lambda kind: setter("anti_aliasing", kind),
                                     width=22), " ")
        rows["aa"].pack(fill="x")

    def follow():
        """The hints and the rows that follow from the settings as they are now, in place."""
        values = app.state.values
        if not rows["mode"].winfo_exists():
            # The page went (another page, the guide's next step) before a late change came.
            return
        rows["mode"].say(w("screen.mode.hint." + values["display"]))
        vsync = values["vsync"] == "on"
        rows["vsync"].say(w("screen.vsync.hint." + ("on" if vsync else "off")))
        rows["fps"].control.set_options(fps_options(w, found, hz, values["fps"]), values["fps"])
        rows["fps"].say(fps_hint(w, vsync, values["fps"], single_rate(found, hz)))
        counter = values["show_fps"] == "on"
        rows["counter"].say(w("screen.counter.hint." + ("on" if counter else "off")))
        frames.show(rows["corner_slot"], counter)
        if full:
            shown.show(rows["size_slot"], values["display"] == "window")
            picture.show(rows["upscaler_slot"], values["render_scale"] != "100")
            rows["upscaler"].say(w("screen.upscaler.hint." + values["upscaler"]))
            rows["aa"].say(w("screen.aa.hint." + values["anti_aliasing"]))

    follow()
    return follow


def game_rate(display):
    """The rate a display runs a game at: the highest of its modes at its size where Windows says its rate is dynamic
    (Windows runs such a panel at 60 Hz while the desktop is still, and at its full rate once a game asks, as the player
    does); otherwise, Windows saying it is not or saying nothing, the rate it is set to now, which the player plays at."""
    if display.get("drr") is True and display.get("top"):
        return display["top"]
    return display.get("hz") or display.get("top")


def displays_line(w, display, found):
    """The line under the display's rows: the main display's size and the rate it runs a game at (with its highest when
    it is set lower), then the other displays' rates when there are others ("Other displays: 180 Hz")."""
    rate = game_rate(display)
    line = w("screen.main", w=display["width"], h=display["height"]) + (w("screen.main.hz", hz=rate) if rate else "")
    top = display.get("top")
    if rate and top and top > rate:
        # Set lower than it can run: what it can run at too.
        line += w("screen.main.up_to", top=top)
    others = [d for d in found if not d.get("main")]
    if others:
        rates = ", ".join("%d Hz" % game_rate(d) for d in others if game_rate(d))
        if rates:
            line += " · " + w("screen.others", rates=rates)
    return line


def single_rate(found, hz):
    """The one rate the hints can name: the main display's game rate (game_rate) when no other display runs at another,
    else None (the game may play on either, and its rate follows the display it is on). `hz` is the main display's when
    the displays are not listed (no Windows to ask)."""
    rates = {game_rate(d) for d in found if game_rate(d)}
    if len(rates) > 1:
        return None
    if rates:
        return rates.pop()
    return hz


def fps_choices(found, current):
    """The frame limits the Screen page offers, as the settings file writes them: the display's own rate (auto), every
    rate up to the fastest connected display's (displays.frame_limits: 160, 165 and 180 Hz displays offer their own),
    and no limit; the `current` one keeps its row all the same (one set on the command line)."""
    offered = ["auto"] + [str(rate) for rate in displays.frame_limits(found)] + ["unlimited"]
    return offered + ([current] if current not in offered else [])


def fps_options(w, found, hz, current):
    """fps_choices as the drop-down's (value, words): the display's rate by its number when one rate is known."""
    rate = single_rate(found, hz)
    auto = w("screen.fps.auto.hz", hz=rate) if rate else w("screen.fps.auto")
    return [(f, auto if f == "auto" else w("screen.fps.unlimited") if f == "unlimited" else w("screen.fps.n", n=f))
            for f in fps_choices(found, current)]


def fps_hint(w, vsync, fps, hz):
    """The frame limit's hint for its value: without VSync, the game holds it itself; with VSync, the display's own
    rate, or on a display whose rate is known, what this limit gives there (exactly, very nearly, or held at the rate:
    values.vsync_refreshes, as the player paces the frames)."""
    if not vsync:
        # The game holds the limit itself; with no limit, it draws its frames without one.
        return w("screen.fps.hint.free.unlimited" if fps == "unlimited" else "screen.fps.hint.free")
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
    or switching VSync on the guide's SOUND & SCREEN, does not throw the page back to its top and the keyboard out of
    it."""
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
    app.page_follow = screen_rows(app, parent)


# --------------------------------------------------------------------------------------------- Sound


def decibels(w, n):
    """A band's level as the Sound page says it: "+3 dB", "0 dB", "-3 dB"."""
    return w("sound.db", sign="+" if n > 0 else "-" if n < 0 else "", n=abs(n))


def last_sound_block(app, parent):
    """How the last game's sound went as the player measured it, the Output card's last block under its own heading:
    its row's lamp marks the gaps; "No game on this PC yet." before the first. Returns follow(), which says it again
    when the result changed (a game that ended while the page is on show)."""
    ui, w = app.ui, app.words
    # Its heading, a list's sub-heading (the labels' face) over the row, as My records heads its lists.
    block = tk.Frame(parent, bg=theme.PANEL)
    tk.Label(block, text=w("sound.last"), font=ui.fonts.body_bold, fg=theme.TEXT, bg=theme.PANEL).pack(
        anchor="w", pady=(0, ui.px(FORM_LABEL_GAP)))
    # The row's own frame under its heading: made again alone.
    box = tk.Frame(block, bg=theme.PANEL)
    box.pack(fill="x")
    block.odq_box = box
    shown = {"result": object()}

    def follow():
        """The row as the result file says it now, made again only when that changed."""
        if not box.winfo_exists():
            return
        result = player.last_sound()
        if result == shown["result"]:
            return
        shown["result"] = result
        for child in box.winfo_children():
            child.destroy()
        row = player.sound_words(w, result)
        if row is None:
            widgets.label(box, ui, w("sound.last.none"), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
            return
        state, words, gaps = row
        widgets.check_line(box, ui, state, words, value=gaps).pack(fill="x")

    follow()
    return block, follow


# The equaliser's three bands stand side by side while its card is at least this wide inside (logical pixels: three
# sliders of BAND_LEAST with their numbers, and the gaps), one under another in a narrower window.
BAND_LEAST = 150
BANDS_ACROSS = 3 * (BAND_LEAST + 70) + 2 * CARD_GAP


def sound_rows(app, parent, full=True, fill=False):
    """The Sound page's settings in their cards, which the guide's SOUND & SCREEN shows too (full=False: the volumes
    alone). On the page, Volume and Output side by side, one height (one under another in a narrow window), the
    equaliser across the page under them: its preset, then its three bands side by side. Made once: a choice changes its
    own control and the hints and controls that follow from it, in place (an equaliser's preset moves its bands, a band
    moved makes it Custom); the devices, when the player lists them, take the place of the line that waited for them.
    Returns follow(), which shows the settings as they are now (values the player's in-game menu wrote back)."""
    ui, w, v = app.ui, app.words, app.state.values
    rows, bands = {}, {}
    if full:
        left, right = _columns(parent, ui, weights=(1, 1))
        card = _card(left, ui, w("sound.volume"), last=True, fill=True)
    else:
        # The guide's: in its place beside the screen's Frames (`fill`: as tall as they are).
        card = _card(parent, ui, w("sound.volume"), last=True, fill=fill)
    volumes = widgets.RowList(card.body, ui)
    volumes.pack(fill="x")
    for name, key in (("volume", "master"), ("music_volume", "music"), ("effects_volume", "effects")):
        rows[name] = widgets.setting_row(
            volumes.add().body, ui, w("sound.volume." + key),
            lambda p, name=name: widgets.Slider(p, ui, v[name], lambda value, name=name: app.changed(name, value),
                                                fill=True),
            w("sound.volume.%s.hint" % key))
        rows[name].pack(fill="x")

    def follow():
        """The controls and hints as the settings are now, in place."""
        values = app.state.values
        if not rows["volume"].winfo_exists():
            # The page went before a late change came.
            return
        for name in choices.VOLUMES:
            rows[name].control.set(values[name])
        if full:
            rows["eq"].control.set(values["eq"])
            rows["eq"].say(w("sound.eq.hint." + values["eq"]))
            for band in choices.EQ_BANDS:
                bands[band].set(values[band])
            rows["mode"].say(w("sound.mode.hint." + values["audio_mode"]))
            rows["buffer"].say(w("sound.buffer.hint." + values["audio_buffer"]))

    if not full:
        return follow

    # The output beside the volumes: the device, how the game has it, its buffer, and how the last game's sound went.
    card = _card(right, ui, w("sound.output"), last=True, fill=True)
    output = widgets.RowList(card.body, ui)
    output.pack(fill="x")
    device_slot = output.add()

    def device_row():
        """The device's row: the line that waits for the player's list, or the drop-down once it came."""
        for child in device_slot.body.winfo_children():
            child.destroy()
        if app.devices is None:
            widgets.setting_row(device_slot.body, ui, w("sound.device"),
                                lambda p: widgets.label(p, ui, w("sound.device.looking"), fg=theme.MUTED)).pack(fill="x")
            return
        values = app.state.values
        options = [("default", w("sound.device.default"))]
        options += [(d["id"], d["name"] + (w("sound.device.now_default") if d["default"] else "")) for d in app.devices]
        if values["audio_device"] != "default" and all(d["id"] != values["audio_device"] for d in app.devices):
            # A device chosen before that is not there now (unplugged): it stays chosen, and says so.
            options.append((values["audio_device"], w("sound.device.gone")))
        # As wide as its row leaves it, a setting's 22 characters at least and a long device name's 34 at most.
        widgets.setting_row(device_slot.body, ui, w("sound.device"),
                            lambda p: widgets.Select(p, ui, options, values["audio_device"],
                                                     lambda d: app.changed("audio_device", d), width=22, most=34),
                            w("sound.device.hint" if app.devices else "sound.device.none")).pack(fill="x")
        # The page's names column counts the new row's name as it counted the one before.
        widgets.fit_names(parent, ui)

    device_row()
    if app.devices is None:
        # Asked once from the player, on a worker thread; the row alone is made again with the answer, while it is on
        # show (another page or step since leaves it be).
        app.load_devices(then=lambda: device_slot.winfo_exists() and device_row())

    def setter(name):
        def chosen(value):
            app.changed(name, value)
            follow()
        return chosen

    rows["mode"] = widgets.setting_row(
        output.add().body, ui, w("sound.mode"),
        lambda p: widgets.Segmented(p, ui, [("shared", w("sound.mode.shared")), ("exclusive", w("sound.mode.exclusive"))],
                                    v["audio_mode"], setter("audio_mode")),
        w("sound.mode.hint." + v["audio_mode"]))
    rows["mode"].pack(fill="x")
    rows["buffer"] = widgets.setting_row(
        output.add().body, ui, w("sound.buffer"),
        lambda p: widgets.Segmented(p, ui, [("low", w("sound.buffer.low")), ("normal", w("sound.buffer.normal")),
                                            ("safe", w("sound.buffer.safe"))], v["audio_buffer"], setter("audio_buffer")),
        w("sound.buffer.hint." + v["audio_buffer"]))
    rows["buffer"].pack(fill="x")
    # Under the output's choices, how the last game's sound went with them, as the player measured it.
    last, follow_last = last_sound_block(app, output.add().body)
    last.pack(fill="x")

    # The equaliser under the pair, across the page: a preset, or the player's own three bands; a preset sets the bands,
    # a band moved makes it Custom.
    card = widgets.Card(parent, ui, w("sound.eq"))
    card.pack(fill="x", pady=(ui.px(CARD_GAP), 0))
    eq = widgets.RowList(card.body, ui)
    eq.pack(fill="x")

    def preset(value):
        app.changed("eq", value)
        follow()

    def band(name, value):
        app.changed(name, value)
        follow()

    rows["eq"] = widgets.setting_row(
        eq.add().body, ui, w("sound.eq.preset"),
        lambda p: widgets.Segmented(p, ui, [(kind, w("sound.eq." + kind)) for kind in choices.EQ], v["eq"], preset),
        w("sound.eq.hint." + v["eq"]))
    rows["eq"].pack(fill="x")
    least, most = choices.EQ_RANGE
    # The three bands side by side, each its name over its slider, as an equaliser's bands stand (one under another
    # while the card is narrower than BANDS_ACROSS).
    columns = _columns(eq.add().body, ui, weights=(1, 1, 1), bg=theme.PANEL, stack_below=BANDS_ACROSS)
    for column, name, key in zip(columns, choices.EQ_BANDS, ("low", "mid", "high")):
        tk.Label(column, text=w("sound.eq." + key), font=ui.fonts.body_bold, fg=theme.TEXT, bg=theme.PANEL).pack(
            anchor="w", pady=(0, ui.px(FORM_LABEL_GAP)))
        bands[name] = widgets.Slider(column, ui, v[name], lambda value, name=name: band(name, value), least=least,
                                     most=most, step=1, say=lambda n: decibels(w, n), fill=True, shortest=BAND_LEAST)
        bands[name].pack(fill="x")

    def follow_all():
        """The settings' controls, then the last game's sound, as they are now."""
        follow()
        follow_last()

    return follow_all


def build_sound(app, parent):
    # Changed in place; the window keeps follow() for values the player's in-game menu writes back (app.took_back).
    app.page_follow = sound_rows(app, parent)


# ------------------------------------------------------------------------------------------ Controls


def build_controls(app, parent):
    # Keyboard play, the page's one card: on or off, and while on, the lanes' keys. What the mouse, a touch screen and
    # the keyboard do in the game is in the PC client's guide (docs/windows-player.md, In the game), not on a page.
    lanes_card(app, parent)


def lanes_card(app, parent):
    """Keyboard play's card: the switch for it, then each LINE mode's lanes with their keys (LaneKeys), in use while it
    is on, with Reset keys at the card's title, and dimmed while it is off: the keys stay on show, so that the card is
    never the switch's alone (a box for one setting, as main's card was with keyboard play off). The switch changes the
    lanes' look in place, the rest of the page as it was."""
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("controls.keys"), last=True)
    on = app.state.values["keyboard"] == "on"
    # The title's line is as tall as a button whether Reset keys is on it or not (widgets.Card): the switch stays where
    # it was, under the pointer that switched it.
    rows = widgets.RowList(card.body, ui)

    def switch(value):
        app.changed("keyboard", "on" if value else "off")
        row.say(w("controls.keys.play.hint." + ("on" if value else "off")))
        table.set_enabled(value)
        table.show_reset(value)

    # Its hint keeps the room of the longer of the two (widgets.keep_room), as the switch brings or takes the lanes.
    row = widgets.setting_row(rows.add().body, ui, w("controls.keys.play"), lambda p: widgets.Toggle(p, ui, on, switch),
                              w("controls.keys.play.hint." + ("on" if on else "off")),
                              hints=[w("controls.keys.play.hint." + state) for state in ("on", "off")])
    row.pack(fill="x")
    rows.pack(fill="x")
    # Where the lanes go, under the switch: on show either way, the switch only changes their look.
    holder = rows.add()
    table = LaneKeys(app, card, holder.body)
    table.set_enabled(on)
    table.show_reset(on)


class LaneKeys:
    """The lanes of each LINE mode, from the top, with their keys: a block for each of 2, 3 and 4 LINE, side by side
    while the card holds them so (one under another in a narrow window with long keys), each lane's number before a box
    for its key and one for a second key (widgets.KeyBox).

    A click on a box (or Enter or Space on it) makes it wait for a key; the key pressed goes in by its place on the
    keyboard (keys.place_of), unless the mode plays it in another box, or no lane takes it: refused in words on the line
    under the table, and the box waits on. Esc keeps what was there, Delete removes one of a lane's two keys, Tab goes
    on to the next control, a click on the waiting box stops the wait. A key taken is saved at once and the page drawn
    again in place, the keyboard on the same box. Reset keys, at the card's title, puts the defaults back. While a box
    waits, Windows' input method is off on the window that gets the keys (keys.typing_off), and a key held down counts
    once: its repeats count from its release on."""

    # The room between two modes' blocks side by side, or one under another, after a lane's number, between a lane's
    # two boxes, and above and under each lane (logical pixels).
    COLUMN_GAP, ROW_GAP, NUMBER_GAP, BOX_GAP, LANE_GAP = 32, 16, 12, 6, 3

    def _flow(self):
        """The modes' blocks side by side when the card holds them so, in three equal columns across the card (each
        block at its column's left edge), else one under another; laid out again only when that changes (the card's
        width alone decides it, never what the blocks are given)."""
        if not self.table.winfo_exists():
            return
        px = self.ui.px
        body = self.card.body
        room = body.winfo_width() - 2 * int(body.cget("padx"))
        if room <= 1:
            # Not laid out yet: once it is, the card's <Configure> asks again.
            room = None
        widths = [block.winfo_reqwidth() for block in self.blocks]
        gaps = px(self.COLUMN_GAP) * (len(self.blocks) - 1)
        # Spread in equal columns when the widest block has its column's room; side by side from the left when only
        # their own widths fit; else one under another (long keys in a narrow window).
        if room is None or len(widths) * max(widths) + gaps <= room:
            flow = "spread"
        elif sum(widths) + gaps <= room:
            flow = "across"
        else:
            flow = "down"
        if flow == self.across:
            return
        self.across = flow
        for block in self.blocks:
            block.grid_forget()
        for i, block in enumerate(self.blocks):
            if flow == "spread":
                # A column each, as wide as the others: the modes spread over the card, never packed into its left part.
                block.grid(row=0, column=i, sticky="nw")
                self.table.columnconfigure(i, weight=1, uniform="modes")
            elif flow == "across":
                block.grid(row=0, column=i, sticky="nw", padx=(px(self.COLUMN_GAP) if i else 0, 0))
                self.table.columnconfigure(i, weight=0, uniform="")
            else:
                block.grid(row=i, column=0, sticky="nw", pady=(px(self.ROW_GAP) if i else 0, 0))
                self.table.columnconfigure(i, weight=0, uniform="")

    def set_enabled(self, on):
        """The lanes in use (keyboard play on) or dimmed, in place: dimmed, the boxes take no key and Tab skips them,
        the names and numbers and the keys in the faintest grey, and the line under them, which says how to change a
        key, goes (a box that waited stops)."""
        self.enabled = bool(on)
        if not self.enabled and self.waiting is not None:
            self.stop()
        for box in self.boxes:
            box.set_enabled(self.enabled)
        for label in self.names:
            label.configure(fg=theme.MUTED if self.enabled else theme.FAINT)
        if self.enabled and not self.line.winfo_manager():
            self.line.pack(fill="x", pady=(self.ui.px(12), 0))
        elif not self.enabled and self.line.winfo_manager():
            self.line.pack_forget()

    def show_reset(self, shown):
        """Reset keys at the card's title while the lanes are in use, gone while keyboard play is off."""
        if shown and not self.reset_button.winfo_manager():
            self.reset_button.pack(side="right")
        elif not shown and self.reset_button.winfo_manager():
            self.reset_button.pack_forget()

    @staticmethod
    def clear(card, holder):
        """The lanes and Reset keys gone from the card (before they are made again)."""
        for child in holder.winfo_children():
            child.destroy()
        for child in card.head.winfo_children():
            if isinstance(child, widgets.Button):
                child.destroy()

    def __init__(self, app, card, holder):
        self.app, self.ui, self.w = app, app.ui, app.words
        self.card, self.holder = card, holder
        ui, w, px = self.ui, self.w, self.ui.px
        values = app.state.values
        # Made in the holder, which keeps its place under the switch: whatever was there before goes first.
        LaneKeys.clear(card, holder)
        # The box that waits for a key, or None.
        self.waiting = None
        # The windows whose input method is off while a box waits (keys.typing_off), given back when the wait ends.
        self.typing = []
        # A plain button, as Check again is on the PLAY page: the screen's lime action stays PLAY's.
        self.reset_button = widgets.Button(card.head, ui, w("controls.keys.reset"), self.reset)
        self.reset_button.pack(side="right")
        # The line between the switch and the table is the card's rows' own (widgets.RowList).
        table = tk.Frame(holder, bg=theme.PANEL)
        table.pack(anchor="w", fill="x")
        self.table = table
        # The page going (another page, a language, the window closing) ends a wait as well: the input method comes back.
        table.bind("<Destroy>", lambda e: self.typing_back() if e.widget is table else None)
        # Whether a box shows what the keyboard prints beside its key's name: the line under the table then says what it is.
        shown = False
        # Every box, in Tab's order (again() finds the one the keyboard was on by its place); the modes' names and the
        # lanes' numbers, dimmed with them; whether the lanes are in use (keyboard play on).
        self.boxes, self.names, self.enabled = [], [], True
        # A block for each mode: its name over its lanes, each lane's number before its boxes. Side by side while the
        # card has the room, one under another when it has not (long keys in a narrow window): _flow().
        self.blocks = []
        # Made mode by mode, each from its top lane: Tab goes down a mode's lanes, then to the next mode.
        for name in choices.LANES:
            block = tk.Frame(table, bg=theme.PANEL)
            self.blocks.append(block)
            # The mode's name, as the game's tabs name it, in the launcher's wide face for English names: the menu's
            # size, never smaller than the keys it heads.
            heading = tk.Label(block, text=choices.mode(name), font=ui.fonts.nav, fg=theme.MUTED, bg=theme.PANEL)
            heading.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, px(6)))
            self.names.append(heading)
            for lane, lane_keys in enumerate(choices.lanes_of(name, values[name])):
                # The lane's number from the top, then its boxes.
                number = tk.Label(block, text=str(lane + 1), font=ui.fonts.body_bold, fg=theme.MUTED, bg=theme.PANEL)
                number.grid(row=lane + 1, column=0, sticky="w", padx=(0, px(self.NUMBER_GAP)))
                self.names.append(number)
                cell = tk.Frame(block, bg=theme.PANEL)
                cell.grid(row=lane + 1, column=1, sticky="w", pady=px(self.LANE_GAP))
                # The lane's keys, then one empty box while it has room for a second.
                for slot in range(min(len(lane_keys) + 1, choices.LANE_KEYS)):
                    key = lane_keys[slot] if slot < len(lane_keys) else None
                    print_ = keys.beside(key, keys.printed(key, app.key_prints)) if key else None
                    shown = shown or print_ is not None
                    box = widgets.KeyBox(cell, ui, key, print_)
                    box.pack(side="left", padx=(px(self.BOX_GAP) if slot else 0, 0))
                    # Which box it is: the mode's setting, the lane from the top, the box in the lane.
                    box.odq_where = (name, lane, slot)
                    self.boxes.append(box)
                    box.bind("<Button-1>", lambda e, b=box: self.clicked(b))
                    box.bind("<KeyPress>", lambda e, b=box: self.pressed(b, e))
                    # A held key's release: its next press counts again (pressed() leaves its repeats out).
                    box.bind("<KeyRelease>", self.released)
                    box.bind("<FocusOut>", lambda e, b=box: self.left(b))
        # Laid out for the card's width now, and again as the window's width changes it.
        self.across = None
        self._flow()
        card.body.bind("<Configure>", lambda e: self._flow(), add="+")
        # What to do, said under the table; what a box waits for, or why a key was refused, said in its place. The
        # line about the grey prints only while a box shows one.
        self.hint = i18n.sentences(w("controls.keys.hint"), w("controls.keys.hint.print") if shown else "")
        self.line = widgets.label(holder, ui, self.hint, font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0)
        self.line.pack(fill="x", pady=(px(12), 0))
        # Tab reaches Reset keys after the boxes: the switch stays the card's first stop whether the lanes are shown or
        # not, so the page drawn again for it keeps the keyboard on it (keep_place finds a control by its place in the
        # order). Tk's Tab goes by the stacking order, so the head goes over everything the card holds, made last.
        # (Misc's own raise: the head is a frame, raised among the card's rows.)
        tk.Misc.tkraise(card.head)

    # ------------------------------------------------------------------------------------- the line under it

    def say(self, text, colour):
        """The line under the table, unless the page went meanwhile (a key's FocusOut as the page is drawn again)."""
        if self.line.winfo_exists():
            # A mode's name in it ("Press a key for lane 1 of 2 LINE") never broken over two lines.
            self.line.configure(text=whole_modes(text), fg=colour)

    def prompt(self, box):
        """What a waiting box waits for: a key for its lane (Esc keeps the one there, Delete takes away one the lane has
        a second of), or a second key."""
        name, lane, slot = box.odq_where
        mode, w = choices.mode(name), self.w
        if box.key is None:
            return w("controls.keys.wait.second", lane=lane + 1, mode=mode)
        lane_keys = choices.lanes_of(name, self.app.state.values[name])[lane]
        return i18n.sentences(w("controls.keys.wait", lane=lane + 1, mode=mode, keyname=box.key),
                              w("controls.keys.wait.delete") if len(lane_keys) > 1 else "")

    # ------------------------------------------------------------------------------------------ the wait

    def wait(self, box):
        """`box` waits for a key, with the keyboard; another box that waited stops."""
        if self.waiting is not None and self.waiting is not box:
            self.waiting.set_waiting(False)
        self.waiting = box
        box.focus_set()
        if not self.typing:
            # The input method off on the window that gets the keys, once for the whole wait (box to box included).
            self.typing = keys.typing_off(box)
        box.set_waiting(True)
        self.say(self.prompt(box), theme.TEXT)

    def typing_back(self):
        """The input method back on the windows a wait took it from: the wait is over."""
        windows, self.typing = self.typing, []
        keys.typing_back(windows)

    def stop(self):
        """No box waits any more: the line says what to do again."""
        box, self.waiting = self.waiting, None
        self.typing_back()
        if box is not None and box.winfo_exists():
            box.set_waiting(False)
        self.say(self.hint, theme.MUTED)

    def released(self, event):
        """A key let go: the key held down since it started a wait or went in counts again at its next press."""
        if event.keycode == self.app.key_held:
            self.app.key_held = None

    def clicked(self, box):
        """A click: the box waits for a key, or a waiting box stops; nothing while the lanes are dimmed."""
        if not getattr(self, "enabled", True):
            return
        if self.waiting is box:
            self.stop()
        else:
            self.wait(box)

    def left(self, box):
        """The keyboard went elsewhere (Tab, another box, another window): the box that waited stops."""
        if self.waiting is box:
            self.stop()

    def pressed(self, box, event):
        """A key pressed on a box: Enter or Space makes a box wait, as a button is pressed; on a waiting box, the key
        for it. "break" for a key the box took, so that nothing else of the window acts on it. A key held down counts
        once: Windows repeats its press with no release, and its repeats would take it, or refuse it, at once."""
        if not getattr(self, "enabled", True):
            # Dimmed: the box takes no key (Tab does not reach it either).
            return None
        if event.keycode == self.app.key_held:
            # The repeat of the key that started the wait or just went in: left out until it is let go.
            return "break"
        # Another key pressed: whatever was held is over, even when its release went to another window.
        self.app.key_held = None
        if self.waiting is not box:
            if event.keysym in ("Return", "KP_Enter", "space"):
                self.wait(box)
                # Held, its repeats would take Space, or refuse Enter, in the box it just made wait.
                self.app.key_held = event.keycode
                return "break"
            # Tab and the rest go their way.
            return None
        if event.keysym in ("Tab", "ISO_Left_Tab"):
            # Tab goes on to the next control (Tk's own binding), the box as it was.
            self.stop()
            return None
        if event.keysym == "Escape":
            self.stop()
            return "break"
        name, lane, slot = box.odq_where
        lanes = choices.lanes_of(name, self.app.state.values[name])
        if event.keysym == "Delete":
            # Delete alone takes a key away (Backspace is refused by its name, as any key no lane takes).
            if box.key is None:
                # The empty box has nothing to take away: it stops waiting.
                self.stop()
                return "break"
            self.change(name, lambda: choices.without_key(name, lanes, lane, slot))
            return "break"
        key = keys.place_of(event)
        if key is None:
            said = keys.label(event)
            self.say(self.w("controls.keys.cannot", keyname=said) if said else self.w("controls.keys.cannot.any"),
                     theme.WARN)
            return "break"
        if event.char:
            # What this PC's layout printed there, for the box to show where Windows cannot be asked (keys.printed).
            self.app.key_prints[key] = event.char
        if self.change(name, lambda: choices.with_key(name, lanes, lane, slot, key), took=(lane, slot, key)):
            # In: held down, its repeats would make the same box wait and take it again, over and over.
            self.app.key_held = event.keycode
        return "break"

    def change(self, name, make, took=None):
        """The lanes `make()` gives saved, and the page drawn again in place with the keyboard on the same box; when it
        refuses (a key another lane plays, a lane's only key), its words on the line, the box still waiting. `took` is
        (lane, box, key) for a key pressed, said in the log once it is in. True once the change is saved."""
        try:
            lanes = make()
        except choices.ChoiceError as e:
            self.say(self.w.error(e), theme.WARN)
            return False
        if took is not None:
            # The key by its place and what this PC prints there: what a player chose, as the window showed it.
            lane, slot, key = took
            log.info("keyboard play: %s lane %d box %d took %s (%r on this keyboard)", choices.mode(name), lane + 1,
                     slot + 1, key, keys.printed(key, self.app.key_prints))
        self.waiting = None
        # The wait is over: the input method back before the page is drawn again.
        self.typing_back()
        self.app.changed(name, choices.lanes_text(lanes))
        self.again()
        return True

    def again(self, where=None):
        """The table made again in its place for keys that changed, the keyboard back on the same box ("reset": on Reset
        keys): only the lanes, the rest of the page as it was."""
        focused = self.app.root.focus_get()
        where = where or getattr(focused, "odq_where", None)
        fresh = LaneKeys(self.app, self.card, self.holder)
        fresh.set_enabled(self.app.state.values["keyboard"] == "on")
        fresh.show_reset(True)
        if where == "reset":
            # Reset keys was pressed: the keyboard stays on it.
            fresh.reset_button.focus_set()
            return
        for box in fresh.boxes:
            if box.odq_where == where:
                box.focus_set()
                break

    def reset(self):
        """Reset keys: each mode's default keys back, saved; the page drawn again in place."""
        self.waiting = None
        # A box that waited stops with the page: the input method back.
        self.typing_back()
        for name in choices.LANES:
            if self.app.state.values[name] != choices.DEFAULTS[name]:
                self.app.changed(name, choices.DEFAULTS[name])
        # Only the lanes made again, the keyboard on Reset keys again (it is the button just pressed).
        self.again(where="reset")


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
        # The address row on show says the answer in place, whoever asked (the guide's SERVER step asks by itself, and
        # its line stayed on "Connecting..." after the server had answered: only a Connect pressed said it).
        said = getattr(app, "address_answered", None)
        if said is not None:
            said()
        if then:
            then()

    threading.Thread(target=work, daemon=True, name="connect").start()


def server_tone(app):
    """The tone of server_line's words: "ok" connected, "bad" a failure, None for a plain note (connecting, the server
    to play on)."""
    check, server = app.server_check, app.state.server()
    if check and check["state"] == "failed":
        return "bad"
    if server and check and check["state"] == "ok" and check["url"] == server["url"]:
        return "ok"
    return None


# How wide the forms' fields are, in characters of the text face: the server's address, the ID and the password.
ADDRESS_CHARS, ACCOUNT_CHARS = 38, 30


# The room between a list's sub-heading and its rows (logical pixels); between one field's row and the next in a form
# (the sign-in's ID and password); above a form's button; between a field and its button beside it; between a row's
# control and what it answers under it; and between a value and the action after it on its line (the account and Sign
# out, the app's date and its button).
FORM_LABEL_GAP, FORM_FIELD_GAP, FORM_BUTTON_GAP, FIELD_BUTTON_GAP, ANSWER_GAP, VALUE_ACTION_GAP = 6, 16, 16, 12, 8, 16


def _surface(parent):
    """The colour a row's frames and words take in `parent`: its own, or a card's deck in a holder that has none (the
    rows a card makes again in place, Sections in lines: their holders show nothing of their own, so that the rows
    before stay on the screen until the new ones are drawn over them)."""
    return parent.cget("bg") or theme.PANEL


def form_row(parent, ui, title, build, top=False):
    """A row of a form (the Online page's server card, the guide's steps): the name in the page's names column, as a
    setting's (widgets.fit_names), and `build(row)`'s control in the next column, on one line by their middles. What the
    control answers (a field's error, how the connection stands, a note) goes under it in the control's column
    (_answer), where a form's feedback belongs to its field. `title` None: a row with no name and no names column, its
    control from the card's own edge (the guide's card of one row, whose title names it)."""
    from opendmtq_client import i18n
    bg = _surface(parent)
    row = tk.Frame(parent, bg=bg)
    row.columnconfigure(1, weight=1)
    # The rows under the control's line in its column, as they are said.
    row.answers = 0
    if title is None:
        # Nothing in the names column, and no room kept for it.
        row.control = build(row)
        row.control.grid(row=0, column=1, sticky="w")
        return row
    # The name in each language the launcher speaks: the page's layout is the same in both, whichever is on show.
    row.odq_names = i18n.every_language(title)
    row.columnconfigure(0, minsize=widgets.name_width(ui, row.odq_names))
    name = tk.Label(row, text=title, font=ui.fonts.body_bold, fg=theme.TEXT, bg=bg, anchor="w")
    row.control = build(row)
    row.control.grid(row=0, column=1, sticky="w")
    if top:
        # A control of several lines (the other servers, each a line as tall as its buttons): the name on the middle of
        # its first line, where it is read from.
        name.grid(row=0, column=0, sticky="nw", padx=(0, ui.px(widgets.LABEL_GAP)),
                  pady=(max(0, int(round((ui.px(widgets.Button.HEIGHT) - ui.fonts.body_bold.metrics("linespace"))
                                         / 2.0))), 0))
    else:
        # The name on the middle of the control's one line (a field's, a button's, words).
        name.grid(row=0, column=0, sticky="w", padx=(0, ui.px(widgets.LABEL_GAP)))
    return row


def _answer(row, ui, make, gap=ANSWER_GAP, fill=True):
    """`make(cell)`'s widget under the row's control in the control's column, `gap` (logical pixels) under what is over
    it: what the control answers, or the next thing it shows (a download's bar, its button). Made in a cell of its own
    as wide as the column, so that words wrap to the column's width, never the row's (they would run past its edge).
    `fill`: across the cell (words), else at its left as wide as it is (a bar, a button)."""
    row.answers += 1
    cell = tk.Frame(row, bg=_surface(row))
    cell.grid(row=row.answers, column=1, sticky="we", pady=(ui.px(gap), 0))
    widget = make(cell)
    if fill:
        widget.pack(fill="x")
    else:
        widget.pack(anchor="w")
    return widget


def _server_line(app, parent):
    """The guide's steps' first line: the server they are about, by its name and address, in a card's own words."""
    ui, w = app.ui, app.words
    server = app.state.server()
    if server is None:
        return
    widgets.label(parent, ui, w("online.signin.on", name=st.label(server)), font=ui.fonts.small, fg=theme.MUTED,
                  wrap_margin=0).pack(fill="x", pady=(0, ui.px(FORM_FIELD_GAP)))


def address_row(app, parent, rerender):
    """The server's address: its field and Connect beside it, and one line under them that says how it stands
    (server_line: connecting, connected, or why not, with its lamp). Returns the field's entry."""
    ui, w = app.ui, app.words
    server = app.state.server()
    holder = {}

    def control(row):
        line = tk.Frame(row, bg=_surface(row))
        field = widgets.Field(line, ui, width=ADDRESS_CHARS, placeholder=w("online.address.example"))
        field.pack(side="left")
        holder["field"], holder["line"] = field, line
        return line

    row = form_row(parent, ui, w("online.address"), control)
    row.pack(fill="x")
    field, line = holder["field"], holder["line"]
    address = field.entry
    in_use = server["url"] if server else ""
    # The field holds what the player typed until it connects or the server in use changes (app.address_draft): a
    # failed Connect keeps it, as the line under it names it, instead of the server in use or nothing coming back.
    address.insert(0, in_use if app.address_draft is None else app.address_draft)
    field.refresh()

    def remember(event=None):
        # What the field holds, kept for the page's next drawing; the address in use again is no draft.
        text = address.get()
        app.address_draft = None if text.strip() == in_use else text

    # Each key the player types (a paste with Ctrl+V too) is in the field by the time the key comes up. A binding of the
    # field's own goes with the field, where a variable traced for it would outlive every page that drew one.
    address.bind("<KeyRelease>", remember, add="+")
    answer = _answer(row, ui, lambda cell: widgets.Said(cell, ui))
    text, _colour = server_line(app)
    tone = server_tone(app)
    answer.set(text, tone)
    # A failure is about what the field holds: its edge says so too.
    field.set_error(tone == "bad")

    def connect():
        if app.busy_now():
            answer.set(w("online.busy"), "warn")
            return
        if not address.get().strip():
            # Nothing typed: said in place, nothing asked.
            answer.set(w("error.server.empty"), "bad")
            field.set_error(True)
            address.focus_set()
            return
        # What is asked is what the field holds: kept for the page drawn again with the answer, which this row says in
        # place as every answer (app.address_answered, called by check_server): once, as a typed address's failure is
        # said once.
        remember()
        check_server(app, address.get(), then=rerender)
        # Said at once, before the server answers.
        answer.set(w("online.connecting"))
        field.set_error(False)

    def answered():
        """The server's answer in place: the line under the field and its edge, and the address as the launcher
        writes it once it connected."""
        if not answer.winfo_exists():
            # The card was made again for another server: the new one shows the answer.
            return
        text, _colour = server_line(app)
        tone = server_tone(app)
        answer.set(text, tone)
        field.set_error(tone == "bad")
        if app.address_draft is None and app.state.current and address.get() != app.state.current:
            address.delete(0, "end")
            address.insert(0, app.state.current)
            field.refresh()

    # Any answer to a server check says itself here, in place (check_server): the guide's own check of the server the
    # installer brought too.
    app.address_answered = answered
    address.bind("<Return>", lambda e: connect())
    address.bind("<KP_Enter>", lambda e: connect())
    # The page's main action is the next step: Connect while there is no server (then Sign in, then the app's download).
    if server:
        connect_button = widgets.Button(line, ui, w("online.connect"), connect)
    else:
        connect_button = main_button(app, line, w("online.connect"), connect)
    connect_button.pack(side="left", padx=(ui.px(FIELD_BUTTON_GAP), 0))
    if not server:
        # Not connected yet: typing goes to the address, Enter connects.
        address.after_idle(address.focus_set)
    return address


def connect_panel(app, parent, rerender):
    """The guide's SERVER step: the server's card, its address row alone."""
    card = _card(parent, app.ui, app.words("online.server"), last=True)
    return address_row(app, card.body, rerender)


def signin_rows(app, parent, rerender, named=True):
    """The sign-in on the current server, as rows: who is signed in and Sign out; or the form: the ID and the password,
    each in its row, the password shown on demand, Sign in under them; Enter in either field signs in. What is wrong
    is said in place, under the field it is about (an empty one, a wrong password), or under the button. `named`
    False: who is signed in without the row's name, in the guide's card whose title says it (Signed in, twice)."""
    ui, w = app.ui, app.words
    server = app.state.server()
    if server is None:
        return
    bg = _surface(parent)
    if app.state.signed_in(server):

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

        def control(row):
            # The account with its lamp, then Sign out right after the account it signs out of.
            line = tk.Frame(row, bg=bg)
            widgets.lamp(line, ui, theme.OK, bg=bg).pack(side="left")
            widgets.label(line, ui, w("online.signed", account=server["account"]), bg=bg).pack(
                side="left", padx=(ui.px(6), 0))
            widgets.Button(line, ui, w("online.signout"), sign_out).pack(side="left", padx=(ui.px(VALUE_ACTION_GAP), 0))
            return line

        form_row(parent, ui, w("online.account.signed") if named else None, control).pack(fill="x")
        return
    fields, said, rows = {}, {}, {}
    for i, (key, secret) in enumerate((("online.id", False), ("online.password", True))):
        made = {}

        def control(row, secret=secret, made=made):
            made["box"] = widgets.Field(row, ui, width=ACCOUNT_CHARS, secret=secret,
                                        reveal=(w("online.password.show"), w("online.password.hide")) if secret
                                        else None)
            return made["box"]

        row = form_row(parent, ui, w(key), control)
        row.pack(fill="x", pady=(ui.px(FORM_FIELD_GAP) if i else 0, 0))
        # Under each field, what is wrong with it, in place (made now, shown once there is something to say), in a cell
        # of the control's column, so that its words wrap to the column's width.
        cell = tk.Frame(row, bg=bg)
        line = widgets.Said(cell, ui)
        line.pack(fill="x")
        line.odq_cell = cell
        fields[key], said[key], rows[key] = made["box"], line, row
    # The ID an installer brought (Play on this PC), else the account signed in before: only the password to type.
    known = server.get("fill") or server.get("account")
    if known:
        fields["online.id"].entry.insert(0, known)

    def say(key, text):
        """What is wrong with one field under it (None: nothing), its edge in the error's colour while it is."""
        line = said[key]
        cell = line.odq_cell
        if text:
            line.set(text, "bad")
            if not cell.winfo_manager():
                cell.grid(row=1, column=1, sticky="we", pady=(ui.px(6), 0))
        elif cell.winfo_manager():
            cell.grid_remove()
        fields[key].set_error(bool(text))

    # Sign in under the fields, in their column, and the line under it that says how the sign-in stands.
    end = form_row(parent, ui, "", lambda row: tk.Frame(row, bg=bg))
    end.pack(fill="x", pady=(ui.px(FORM_BUTTON_GAP), 0))
    buttons = end.control
    message = _answer(end, ui, lambda cell: widgets.Said(cell, ui))
    message.set(w("online.signin.hint"))

    # One sign-in at a time: Enter pressed twice sends one request (the server counts every try).
    asking = {"now": False}

    def sign_in():
        if asking["now"]:
            return
        user, password = fields["online.id"].entry.get(), fields["online.password"].entry.get()
        # An empty field is said under it, nothing asked of the server.
        say("online.id", None if user.strip() else w("error.signin.no_id"))
        say("online.password", None if password else w("error.signin.no_password"))
        if not user.strip() or not password:
            (fields["online.id"] if not user.strip() else fields["online.password"]).entry.focus_set()
            return
        asking["now"] = True
        message.set(w("online.signing"))

        def work():
            try:
                # The sign-in is kept on the window's own thread, before signed_in() saves it there.
                actions.sign_in(app.state, user, password, change=app.post)
                app.post(signed_in)
            except Exception as e:  # noqa: BLE001
                # The server's own words for it go to the log (never the password); the form says it plainly.
                log.info("could not sign in to %s as %s: %s", server["url"], user, e)
                app.post(lambda error=e, text=w.error(e): refused(error, text))

        threading.Thread(target=work, daemon=True, name="sign-in").start()

    def refused(error, text):
        """The server said no: a wrong ID or password under the password, ready to type again; anything else under the
        button."""
        asking["now"] = False
        if not message.winfo_exists():
            return
        password = fields["online.password"].entry
        if getattr(error, "key", None) == "error.signin.wrong":
            say("online.password", text)
            fields["online.id"].set_error(True)
            message.set(w("online.signin.hint"))
        else:
            message.set(text, "bad")
        password.focus_set()
        password.select_range(0, "end")

    def signed_in():
        asking["now"] = False
        # A sign-in is the player's doing: a message kept until then gives way (a sign-in that had ended, say).
        app.user_acted()
        app.state.save()
        app.refresh_checks()
        rerender()

    for box in fields.values():
        box.entry.bind("<Return>", lambda e: sign_in())
        box.entry.bind("<KP_Enter>", lambda e: sign_in())
    # Typing goes to the first empty field; Tab to the next, then Sign in; Enter signs in.
    first = fields["online.password"] if known else fields["online.id"]
    first.entry.after_idle(first.entry.focus_set)
    main_button(app, buttons, w("online.signin"), sign_in).pack(side="left")


def signin_panel(app, parent, rerender):
    """The guide's SIGN IN step: the sign-in's card, its title saying the state (signed in, or the sign-in to make),
    the server it is on in its first line, then the sign-in's rows."""
    ui, w = app.ui, app.words
    server = app.state.server()
    if server is None:
        return
    card = _card(parent, ui, w("online.account.signed" if app.state.signed_in(server) else "online.account"), last=True)
    _server_line(app, card.body)
    signin_rows(app, card.body, rerender, named=False)


def app_row(app, parent, rerender, named=True):
    """The server's app on this PC, as a row: what it has (or that the server has a newer one), what the last look or
    download said, and the download with its progress, or its button. `named` False: without the row's name, in the
    guide's card titled The server's app (main said it twice, over the row and as its name)."""
    ui, w = app.ui, app.words
    server = app.state.server()
    if server is None:
        return
    bg = _surface(parent)
    have = apps.local(server["url"])
    offered = server.get("app")
    newer = bool(have and offered and offered.get("sha256", "").lower() != have["sha256"])
    if have and not newer:
        text, colour = w("online.app.have", date=_date(have)), theme.TEXT
    elif have:
        text, colour = w("online.app.newer", date=_date(offered)), theme.WARN
    else:
        text, colour = w("online.app.none"), theme.WARN
    def control(r):
        # What this PC has, and on the same line the way to get it or a newer one (below, once it is known).
        line = tk.Frame(r, bg=bg)
        widgets.label(line, ui, text, fg=colour, bg=bg).pack(side="left")
        return line

    row = form_row(parent, ui, w("online.app") if named else None, control)
    row.pack(fill="x")
    if app.download is None and app.app_note and not newer:
        # The last look for a newer app found none: said here, where its button is.
        _answer(row, ui, lambda cell: widgets.label(cell, ui, w.say(app.app_note), font=ui.fonts.small, fg=theme.MUTED,
                                                    bg=bg, wrap_margin=0), gap=4)
    if app.download is None and app.download_error:
        # What the last try said (a stop, a sign-in that ended, a line that broke), in the same colour as the status
        # line says it: the guide has no status line to say it.
        said, tone = app.download_error
        _answer(row, ui, lambda cell: widgets.label(cell, ui, w.say(said), font=ui.fonts.small,
                                                    fg=theme.WARN if tone == "warn" else theme.BAD, bg=bg, wrap_margin=0),
                gap=4)
    if app.download is not None:
        # The download under way: its bar, kept moving by the app (app._download_moved), and Cancel.
        bar = _answer(row, ui, lambda cell: widgets.Progress(cell, ui, bg=bg), gap=FORM_BUTTON_GAP, fill=False)
        done, total = app.download["done"], app.download["total"]
        # The status line's words (app.download_words): how far it is, the server asked first, or stopping.
        bar.set(done / float(total) if total else None, w.say(app.download_words()))
        app.download_bar = bar
        stopping = app.download.get("stopping")
        stop = _answer(row, ui, lambda cell: widgets.Button(cell, ui, w("online.stopping") if stopping else
                                                            w("common.cancel"), lambda: halt()),
                       gap=FORM_BUTTON_GAP, fill=False)
        if stopping:
            stop.enable(False)

        def halt():
            # Off at once, saying so: the download stops as soon as the next piece is in.
            app.cancel_download()
            stop.set_text(w("online.stopping"))
            stop.enable(False)
        return
    if not app.state.signed_in(server):
        _answer(row, ui, lambda cell: widgets.label(cell, ui, w("online.app.signin_newer" if have else
                                                                  "online.app.signin"),
                                                    font=ui.fonts.small, fg=theme.MUTED, bg=bg, wrap_margin=0), gap=4)
        return
    words = w("online.app.update") if newer else w("online.app.check") if have else w("online.app.get")
    # Getting an app this PC lacks, or the newer one, is the page's main action; looking for a newer one is not. On the
    # line of what this PC has, after it, as Sign out stands after the account.
    if not have or newer:
        get = main_button(app, row.control, words, lambda: _get(app, rerender))
    else:
        get = widgets.Button(row.control, ui, words, lambda: _get(app, rerender))
    get.pack(side="left", padx=(ui.px(VALUE_ACTION_GAP), 0))


def app_panel(app, parent, rerender):
    """The guide's DOWNLOAD step: the app's card, the server it comes from in its first line, then the app's row."""
    ui, w = app.ui, app.words
    if app.state.server() is None:
        return
    card = _card(parent, ui, w("online.app"), last=True)
    _server_line(app, card.body)
    app_row(app, card.body, rerender, named=False)


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


def test_key(app):
    """What the Online page's test card shows: the test of the server in use (its number), or None."""
    test, server = app.connection_test, app.state.server()
    return test["id"] if test and server and test["url"] == server["url"] else None


# A step's lamp by its state: lime what is fine, a yellow ring what is not as it should be, red what fails, a faint ring
# what waits or was not tried.
TEST_LAMPS = {"ok": (theme.OK, False), "warn": (theme.WARN, True), "bad": (theme.BAD, False),
              "skip": (theme.FAINT, True), "wait": (theme.FAINT, True)}


def test_panel(app, parent):
    """The connection test's card: its verdict at the top, Copy at its title, then a row a step (a lamp, the step's name,
    what it found, how long it took), every step there from the start and each said in place as it ends; with a server
    found on another port, Use this address under the verdict."""
    from PIL import ImageTk
    from opendmtq_client import connection
    test = app.connection_test
    if test_key(app) is None:
        return
    ui, w = app.ui, app.words
    # A status panel, as the ready check: its title led by the test's light (its state as a whole, as the ready check's
    # strip carries the check's), Copy at its right end, the steps under the header strip.
    card = widgets.Card(parent, ui, w("test.title"), strip=theme.STRIP_HEAD)
    card.pack(fill="x")
    shown = test["shown"] = {"rows": {}}
    light = tk.Label(card.head, bd=0, bg=card.head.cget("bg"))
    light.pack(side="left", before=card.title, padx=(0, ui.px(8)))
    shown["light"] = light
    copy = widgets.Button(card.head, ui, w("test.copy"), app.copy_test)
    copy.pack(side="right")
    shown["copy"] = copy
    # The lamps of each state, made once for the card's rows.
    pictures = {}
    for state, (colour, hollow) in TEST_LAMPS.items():
        picture = art.lamp(colour, ui.scale, bg=theme.PANEL, hollow=hollow, lead=False)
        pictures[state] = (picture, ImageTk.PhotoImage(picture, master=card))
    shown["pictures"] = pictures
    # The verdict: what the test found, in words, as the card's first line. The strip's light says its state, once:
    # the verdict's own lamp under it said the same again (and drew a warning as a filled dot).
    verdict = widgets.label(card.body, ui, "", font=ui.fonts.body, fg=theme.MUTED, wrap_margin=0)
    verdict.pack(fill="x")
    shown["verdict"] = verdict
    # Where Use this address comes when the test found the server on another port.
    shown["use"] = tk.Frame(card.body, bg=theme.PANEL)
    widgets.divider(card.body, ui, pady=CHECK_GAP)
    # The steps' names in one column, as wide as the widest of either language.
    names = [words for key in connection.STEPS for words in i18n.TEXT["test." + key]]
    column = widgets.name_width(ui, names)
    for i, key in enumerate(connection.STEPS):
        if i:
            widgets.divider(card.body, ui, pady=TEST_ROW_GAP)
        row = tk.Frame(card.body, bg=theme.PANEL)
        row.pack(fill="x")
        lamp = tk.Label(row, image=pictures["wait"][1], bg=theme.PANEL, bd=0)
        lamp.odq_picture = pictures["wait"][0]
        lamp.pack(side="left", anchor="n", pady=(ui.px(1), 0))
        # The lamp's middle, from the row's top: the name's line has its middle there, as a ready-check row's words do
        # (widgets.check_line), and what it found and how long it took stand on the name's baseline.
        middle = ui.px(1) + lamp.winfo_reqheight() / 2.0
        name_top = max(0, int(round(middle - ui.fonts.body_bold.metrics("linespace") / 2.0)))
        small_top = max(0, name_top + ui.fonts.body_bold.metrics("ascent") - ui.fonts.small.metrics("ascent"))
        # The step's name in the names' column: a frame as wide as the column, as tall as the name.
        holder = tk.Frame(row, bg=theme.PANEL, width=column)
        holder.pack(side="left", anchor="n", padx=(ui.px(6), 0), pady=(name_top, 0))
        name = tk.Label(holder, text=w("test." + key), font=ui.fonts.body_bold, fg=theme.TEXT, bg=theme.PANEL, anchor="w")
        name.pack(anchor="w")
        holder.configure(height=name.winfo_reqheight())
        holder.pack_propagate(False)
        took = tk.Label(row, text="", font=ui.fonts.small, fg=theme.MUTED, bg=theme.PANEL)
        took.pack(side="right", anchor="n", padx=(ui.px(12), 0), pady=(small_top, 0))
        # What it found, beside its name, wrapping in the room left of how long it took.
        found = widgets.label(row, ui, w("test.waiting"), font=ui.fonts.small, fg=theme.MUTED, bg=theme.PANEL,
                              wrap_margin=0, beside=(lamp, holder, took))
        found.pack(side="left", fill="x", expand=True, anchor="n", pady=(small_top, 0))
        shown["rows"][key] = {"lamp": lamp, "name": name, "found": found, "took": took}
    # What ended before the card was made (the page drawn again meanwhile), and the verdict as it stands.
    for step in test["steps"].values():
        test_step_shown(app, test, step)
    test_done_shown(app, test)


# The room either side of the faint line between two steps' rows (logical pixels): tighter than a list's, as a test has
# ten of them.
TEST_ROW_GAP = 6


def test_step_shown(app, test, step):
    """A step's row as it ended, in place: its lamp, what it found, how long it took. Nothing else of the page made again."""
    from opendmtq_client import connection
    shown = test.get("shown")
    row = shown and shown["rows"].get(step.key)
    if not row or not row["lamp"].winfo_exists():
        return
    picture, image = shown["pictures"][step.state]
    row["lamp"].configure(image=image)
    row["lamp"].odq_picture = picture
    # A step not tried shows its grey ring and its name alone: the verdict over the steps says what stopped them, and
    # the same line under each of the steps after it said nothing more (main: "Not tried: a step before it did not get
    # through." eight times over). The copied text keeps its two words (connection.Result.text).
    found = "" if step.state == "skip" else app.words.say(step.said) if step.said else app.words("test.waiting")
    row["found"].configure(text=found, fg=theme.TEXT if step.state == "bad" else theme.MUTED)
    row["took"].configure(text=connection.took(step.ms) if step.ms is not None and step.state != "skip" else "")
    # The time beside the words grew from nothing ("12 ms"), and the row's width did not change to tell the words: they
    # are wrapped again for the room left of it, so that no line of them is wider than that room (Tk would cut it).
    wrap = getattr(row["found"], "odq_wrap", None)
    if wrap is not None:
        wrap(row["found"].master.winfo_width())
    _test_verdict(app, test)


def test_done_shown(app, test):
    """The test's end on its card, in place: the verdict, Copy, and Use this address for a server found on another
    port."""
    shown = test.get("shown")
    if not shown or not shown["verdict"].winfo_exists():
        return
    _test_verdict(app, test)
    result = test["result"]
    shown["copy"].enable(not test["running"] and result is not None)
    use = shown["use"]
    for child in use.winfo_children():
        child.destroy()
    if result is not None and result.moved and not test["running"]:
        # The server's address on the port it answers on, one press away (plain: the page's lime button stays its own
        # main action, the sign-in or the app's download).
        widgets.Button(use, app.ui, app.words("test.use"), lambda: app.use_found_address(result.moved)).pack(anchor="w")
        if not use.winfo_manager():
            use.pack(fill="x", pady=(app.ui.px(FORM_BUTTON_GAP), 0), after=shown["verdict"])
    elif use.winfo_manager():
        use.pack_forget()


def _test_verdict(app, test):
    """The verdict line over the steps, as the test stands: running, or its outcome in the outcome's tone."""
    from opendmtq_client import connection
    shown = test["shown"]
    if test["running"] or test["result"] is None:
        partial = connection.Result(test["url"])
        for step in test["steps"].values():
            partial.steps[connection.STEPS.index(step.key)] = step
        partial.ended = not test["running"]
        said, tone = partial.verdict(), None
    else:
        result = test["result"]
        said = result.verdict()
        tone = "ok" if not result.failed() and not any(s.state == "warn" for s in result.steps) else (
            "bad" if result.failed() and not result.moved else "warn")
    # Muted while it runs, the words' own colour once it ended, the error's colour for a failure.
    shown["verdict"].configure(text=app.words.say(said),
                               fg=theme.MUTED if tone is None and test["running"] else theme.BAD if tone == "bad"
                               else theme.TEXT)
    _paint_test_light(app, shown["light"], tone)


def _paint_test_light(app, light, tone):
    """The connection test's light on its strip, in the verdict's tone as the ready check's light is in its rows' worst:
    lime when all is fine, a yellow ring when something is not as it should be, red when a step failed, a faint ring
    while the test runs. Drawn again only when its tone changed."""
    if not light.winfo_exists() or getattr(light, "odq_state", "") == tone:
        return
    colour, hollow = {"ok": (theme.OK, False), "warn": (theme.WARN, True), "bad": (theme.BAD, False),
                      None: (theme.FAINT, True)}[tone]
    picture = art.lamp(colour, app.ui.scale, bg=light.cget("bg"), hollow=hollow, lead=False)
    light.odq_image = ImageTk.PhotoImage(picture, master=light)
    light.odq_picture = picture
    light.configure(image=light.odq_image)
    light.odq_state = tone


def others_row(app, parent, rerender):
    """The other servers this launcher knows, as a row of the server's card: each by its name and address, with Play
    here and Forget at the row's right end, a faint line between them."""
    ui, w = app.ui, app.words
    others = [s for s in app.state.servers if s["url"] != app.state.current]
    if not others:
        return
    bg = _surface(parent)

    def control(row):
        box = tk.Frame(row, bg=bg)
        for i, s in enumerate(others):
            # One line a server, split by the card's faint lines.
            if i:
                widgets.divider(box, ui, pady=CHECK_GAP)
            line = tk.Frame(box, bg=bg)
            line.pack(fill="x")

            def pick(url=s["url"]):
                if app.busy_now():
                    app.set_status(i18n.Said("online.busy"), "warn")
                    return
                # Another server to play on: what the line said about the one before (an installer's server, a
                # failure) gives way to where PLAY stands on this one once the ready check below answers.
                app.user_acted()
                app.state.current = url
                # The server in use changed: the address field shows it, whatever was typed there before.
                app.address_draft = None
                # What the last server's download said is not this one's.
                app.download_error, app.app_note = None, None
                app.state.save()
                app.refresh_checks()
                rerender()

            # At the line's top, their middle the first line's of the words beside them.
            forget_button = widgets.Button(line, ui, w("online.forget"), lambda s=s: forget_server(app, s, rerender),
                                           kind="danger")
            forget_button.pack(side="right", anchor="n")
            pick_button = widgets.Button(line, ui, w("online.pick"), pick)
            pick_button.pack(side="right", anchor="n", padx=(0, ui.px(8)))
            # Its name and address, or its address once when it has no name of its own: its first line on the
            # buttons' middle, a wrapped second under it.
            named = "%s  ·  %s" % (s["name"], s["url"]) if st.has_own_name(s) else s["url"]
            words = widgets.label(line, ui, named, wrap_margin=16, beside=(forget_button, pick_button))
            words.pack(side="left", fill="x", anchor="n", pady=(max(0, int(round(
                (ui.px(widgets.Button.HEIGHT) - ui.fonts.body.metrics("linespace")) / 2.0))), 0))
        return box

    row = form_row(parent, ui, w("online.others"), control, top=True)
    # Across the control's column: the servers' buttons stand at its right end, one under another.
    row.control.grid_configure(sticky="we")
    row.pack(fill="x")


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


def online_keys(app):
    """What each card of the Online page (and the guide's steps that show them) shows, as keys for Sections: the server
    in use, its sign-in, its app and the download, and the other servers."""
    state = app.state
    server = state.server()
    url = server["url"] if server else None

    def server_key():
        return (url and state.server()["url"], server and state.server()["name"]) if state.server() else None

    def signin_key():
        current = state.server()
        return (current["url"], state.signed_in(current), current.get("account"), current.get("fill")) if current else None

    def app_key():
        current = state.server()
        if current is None:
            return None
        have = apps.local(current["url"])
        download = app.download
        return (current["url"], have and have.get("sha256"), (current.get("app") or {}).get("sha256"),
                state.signed_in(current), download is not None and bool(download.get("stopping")),
                download is None, str(app.download_error), str(app.app_note))

    def others_key():
        return tuple((s["url"], s["name"]) for s in state.servers if s["url"] != state.current)

    return server_key, signin_key, app_key, others_key


def build_online(app, parent):
    """The Online page: one card of the server's rows (its address, the sign-in, its app, the other servers this
    launcher knows), then the connection test's card while a test is on show. Each row made again in place when what it
    shows changed (an answer, a sign-in, a download), the card made again for another server."""
    ui = app.ui
    server_key, signin_key, app_key, others_key = online_keys(app)
    # The card's rows, made again with the card (_online_card sets it).
    inner = {"rows": None}

    def follow():
        """The card (for another server) or its rows, then the test's card, made again where they changed; the rows'
        names column fitted again to the rows on show."""
        changed = cards.refresh()
        rows = inner["rows"]
        if rows is not None and rows.parent.winfo_exists():
            changed = rows.refresh() or changed
        if changed:
            widgets.fit_names(parent, ui, rows_that_come("online"))
        return changed

    # A change of the launcher's state redraws what it changed, while the page is on show.
    again = lambda: app.page == "online" and app.guide is None and follow()  # noqa: E731
    cards = Sections(parent, ui)
    # The server's card is keyed by the server in use only: its title's buttons are that server's; its rows follow.
    cards.add(lambda: (app.state.current,), lambda holder: _online_card(app, holder, again, inner))
    # The connection test of the server in use, made once a test starts and filled in as its steps end (test_panel).
    cards.add(lambda: test_key(app), lambda holder: test_panel(app, holder))
    app.page_follow = follow


def _online_card(app, holder, rerender, inner):
    """The Online page's server card: Test connection and Forget at its title (with a server), then its rows, a faint
    line between them, each made again in place by its own key (Sections in lines)."""
    ui, w = app.ui, app.words
    card = _card(holder, ui, w("online.server"), last=True)
    server = app.state.server()
    if server:
        # At the card's title, apart from Connect: the next server this launcher knows becomes the one PLAY plays on.
        widgets.Button(card.head, ui, w("online.forget"), lambda: forget_server(app, server, rerender),
                       kind="danger").pack(side="right")
        # Beside it, the connection test of this server: its card comes under this one (test_panel).
        widgets.Button(card.head, ui, w("test.button"), app.test_connection).pack(side="right", padx=(0, ui.px(8)))
    server_key, signin_key, app_key, others_key = online_keys(app)
    rows = Sections(card.body, ui, lines=True)
    rows.add(lambda: (app.state.current,), lambda h: address_row(app, h, rerender))
    rows.add(signin_key, lambda h: signin_rows(app, h, rerender))
    rows.add(app_key, lambda h: app_row(app, h, rerender))
    rows.add(others_key, lambda h: others_row(app, h, rerender))
    inner["rows"] = rows


# ---------------------------------------------------------------------------------------------- Help


def _player_log(app):
    """The player's log for the current server's app, and whether it is there (once the game has run with the app)."""
    server = app.state.server()
    have = apps.local(server["url"]) if server else None
    log_file = player.app_log(have)
    return log_file, bool(log_file and os.path.isfile(log_file))


def build_help(app, parent):
    ui = app.ui
    from opendmtq_client import installed
    # The ready check across the page, its rows made again in place when they change (refresh_checks).
    checks = Sections(parent, ui)
    checks.add(lambda: None, lambda holder: _help_checks(app, holder))
    # Then the tools and resetting and removing side by side, one height (one under another in a narrow window). The
    # tools follow the player's log (there once the game has run) and the install.
    left, right = _columns(parent, ui, weights=(1, 1), gap_above=CARD_GAP)
    tools = Sections(left, ui)
    tools.add(lambda: (_player_log(app), installed.root()), lambda holder: _help_tools(app, holder), expand=True)
    remove = Sections(right, ui)
    remove.add(lambda: (installed.root(), bool(installed.root() and installed.updater(installed.root()))),
               lambda holder: _help_remove(app, holder), expand=True)

    def follow():
        """Each card whose rows changed made again in place, and the page's names column fitted to its rows again."""
        changed = any([part.refresh() for part in (checks, tools, remove)])
        if changed:
            widgets.fit_names(parent, ui, rows_that_come("help"))
        return changed

    app.page_follow = follow


def _help_checks(app, parent):
    # The ready check as PLAY has it (its light, Check again: the server asked again too, whatever its last answer).
    checks_card(app, parent, app.words("help.checks"))
    app.refresh_checks()
    refresh_checks(app)


def _help_tools(app, parent):
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("help.tools"), last=True, fill=True)
    log_file, has_log = _player_log(app)
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
    # A report of them all, with this PC's displays, sound and graphics, for whoever helps (report.py).
    widgets.divider(card.body, ui)
    widgets.setting_row(card.body, ui, w("help.report.row"),
                        lambda p: widgets.Button(p, ui, w("help.report"), lambda: maintenance.save_report(app)),
                        w("help.report.hint")).pack(fill="x")
    from opendmtq_client import installed
    root = installed.root()
    if root:
        # Only the installed launcher has a package to put its files back from.
        widgets.divider(card.body, ui)
        widgets.setting_row(card.body, ui, w("help.repair.row"),
                            lambda p: widgets.Button(p, ui, w("help.repair"), lambda: maintenance.repair_program(app)),
                            w("help.repair.hint")).pack(fill="x")


def _help_remove(app, parent):
    ui, w = app.ui, app.words
    from opendmtq_client import installed
    root = installed.root()
    # From the least to the most: the game's data, the launcher's, the program.
    card = _card(parent, ui, w("help.remove"), last=True, fill=True)
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
    # General, one group of rows: the language, the launcher's version with its updates, the first-start guide.
    card = _card(parent, ui, w("about.general"))
    rows = widgets.RowList(card.body, ui)
    rows.pack(fill="x")
    widgets.setting_row(rows.add().body, ui, w("about.language"),
                        lambda p: widgets.Segmented(p, ui, language_options(app), app.state.picked_language or "system",
                                                    app.set_language)).pack(fill="x")
    # The updates' row, made again in place when the look at the start finds a newer launcher; the rows after it as
    # they were.
    sections = Sections(rows.add().body, ui)
    sections.add(lambda: app.update_found and app.update_found.version, lambda holder: _updates_row(app, holder))
    app.page_follow = sections.refresh

    def rerun():
        app.state.guide_done = False
        app.state.save()
        app.show()

    widgets.setting_row(rows.add().body, ui, w("about.guide"),
                        lambda p: widgets.Button(p, ui, w("about.guide.run"), rerun)).pack(fill="x")
    # About, plain and quiet: a step deeper than the deck, no light along its top, its lines in the small words of a
    # page's foot, as the site's footers set them.
    card = widgets.Card(parent, ui, w("about.legal"), fill=theme.QUIET, rim=None)
    card.pack(fill="x")
    for i, key in enumerate(("about.license", "about.notice")):
        if i:
            widgets.divider(card.body, ui, pady=CHECK_GAP)
        widgets.label(card.body, ui, w(key), font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0).pack(fill="x")
    # The notice's second line under its first, as the site's footers have the two.
    widgets.label(card.body, ui, w("about.notice.2"), font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0).pack(
        fill="x", pady=(ui.px(4), 0))


def _updates_row(app, parent):
    """General's updates row: the version and Check for updates in the row's control column, the answer under them
    and Update to vX when one is on offer, in that column too, as a field's answer stands under it."""
    ui, w = app.ui, app.words
    # The version the header shows beside the logo too: the installed one, else the code's.
    version = updates.shown_version()

    def control(row):
        box = tk.Frame(row, bg=theme.PANEL)
        widgets.label(box, ui, w("about.version", v=version)).pack(side="left")
        # A field's gap to its button: the version and its look for a newer one read as one thing.
        widgets.Button(box, ui, w("about.check"), check).pack(side="left", padx=(ui.px(12), 0))
        return box

    # One look at a time: a second press while it asks does nothing.
    checking = {"now": False}

    def check():
        if checking["now"]:
            return
        checking["now"] = True
        for child in slot.winfo_children():
            child.destroy()
        answer.configure(text=w("about.checking"), fg=theme.MUTED)
        if not cell.winfo_manager():
            # The answer and its Update under the version and its button, in the control's column, as a field's answer
            # stands under it (form_row).
            cell.grid(row=1, column=1, sticky="we", pady=(ui.px(ANSWER_GAP), 0))

        def work():
            # The window's own settings: the server PLAY plays on is asked first.
            result = updates.check(app.state)
            app.post(lambda: show(result))

        threading.Thread(target=work, daemon=True, name="updates").start()

    row = widgets.setting_row(parent, ui, w("about.updates"), control, bg=theme.PANEL)
    row.pack(fill="x")
    # The answer and "Update to vX" under the version, in a cell of the control's column (its words wrap to the
    # column's width), taking room only once there is an answer.
    cell = tk.Frame(row, bg=theme.PANEL)
    answer = widgets.label(cell, ui, "", fg=theme.MUTED, wrap_margin=0)
    answer.pack(fill="x")
    slot = tk.Frame(cell, bg=theme.PANEL)
    slot.pack(fill="x")

    def show(result):
        checking["now"] = False
        if not answer.winfo_exists():
            return
        # The server PLAY plays on is named when the answer is its own: what it hands out, or its version as the newest.
        server = result.source is not None and result.source.kind == "server"
        source = result.source.label() if result.source is not None else ""
        text = {
            "not_installed": w("about.not_installed"),
            "no_source": w("about.no_source"),
            "uptodate": w("about.uptodate.from", source=source) if server else w("about.uptodate"),
            # What failed and, by its kind, why: the words for the log are in the launcher's log (updates.check).
            "failed": w.failed("about.update_failed", result.error),
            "refused": w("about.refused", source=source),
            "available": w("about.available.from", v=result.version, source=source) if server
            else w("about.available", v=result.version),
        }[result.kind]
        answer.configure(text=text, fg=theme.BAD if result.kind in ("failed", "refused") else theme.MUTED)
        if result.kind == "available":
            main_button(app, slot, w("about.update_now", v=result.version), lambda: update(result)).pack(
                anchor="w", pady=(ui.px(12), 0))
            if app.update_found is None or app.update_found.version != result.version:
                # Found by this press: the status line says it too, as it says the one the start found.
                app.update_on_offer(result)

    def update(result):
        if not maintenance.update_launcher(app, result):
            # A game from this window or from the command line: the update replaces the player's files under it.
            answer.configure(text=w("about.update_busy"), fg=theme.WARN)

    if app.update_found is not None:
        # The look at the start found a newer launcher: its answer and its update are here without a press.
        cell.grid(row=1, column=1, sticky="we", pady=(ui.px(ANSWER_GAP), 0))
        show(app.update_found)


BUILDERS = {
    "play": build_play, "screen": build_screen, "sound": build_sound, "controls": build_controls,
    "online": build_online, "help": build_help, "about": build_about,
}
