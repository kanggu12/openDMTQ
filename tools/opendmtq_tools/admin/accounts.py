"""The Accounts page: the sign-ins of the site and of these pages, and each new password shown once; the API's tokens too.
Each form's work is a function of its own (create, change, link, and tokens.make and tokens.revoke), which the API calls
as well (api.py): the page and the API cannot differ."""

import secrets
import sqlite3
import threading
import time

from flask import flash, redirect, render_template, request, session, url_for

from . import apps, auth, core, tokens
from .core import Refused, ago, app, BASE, changed, db, t, why

# A new account's password, or a new password, shown on the next page only: never in the session's cookie (the browser
# keeps that) and never twice. Waits ten minutes at most. In memory: the service runs one process. A new API token waits
# here the same way.
_shown = {}
_shown_lock = threading.Lock()

# The buttons of an account's row, by the form's action.
ACTIONS = ("password", "off", "on", "delete", "admin", "player")


def keep_once(name, password, note, word):
    """Keeps an account's password for the next page to show, once: the session holds only the way to it."""
    _keep("shown", {"name": name, "password": password, "note": note, "word": word})


def _keep(key, shown):
    """Keeps what one page is to show once, under key in the session: ten minutes at most, in memory only."""
    now = time.time()
    token = secrets.token_urlsafe(16)
    with _shown_lock:
        for old in [k for k, v in _shown.items() if now - v["at"] > 600]:
            del _shown[old]
        _shown[token] = dict(shown, at=now)
    session[key] = token


def take_once(key="shown"):
    """The account keep_once kept for this page (or the token kept under key), once and for ten minutes at most, or None."""
    with _shown_lock:
        shown = _shown.pop(session.pop(key, ""), None)
    return shown if shown and time.time() - shown["at"] <= 600 else None


def show_once(name, password, note, word):
    """Has the Accounts page show this account's password and the message for its owner, once."""
    keep_once(name, password, note, word)
    return redirect(url_for("accounts_page"))


@app.route(BASE + "/accounts", methods=["GET", "POST"])
def accounts_page():
    """The site's accounts: made here and nowhere else, each with its ID and password, some with admin rights."""
    if request.method == "POST":
        return accounts_action()
    shown = take_once()
    # A token just made: shown here once, as a new password is.
    shown_token = take_once("shown_token")
    rows, broken, players, listed_tokens = [], False, [], []
    try:
        with db() as con:
            auth.account_table(con)
            # The game's players, to link an account to the one it is.
            players = auth.game_players(con)
            # When each last signed in, as long ago as that was; the moment itself under the pointer.
            rows = [dict(r, last=ago(r["signed_in_at"]) if r["signed_in_at"] else "")
                    for r in con.execute("SELECT name, note, admin, created_at, signed_in_at, off, guid FROM SiteUser ORDER BY name COLLATE NOCASE")]
        # The API's tokens, with when each was last used, as long ago as that was.
        listed_tokens = [dict(r, last=ago(r["used_at"]) if r["used_at"] else "") for r in tokens.listing()]
    except sqlite3.Error:
        broken = True
    message = apps.invite_text(apps.friends_address(core.server_health()), shown["name"], shown["password"]) if shown else ""
    return render_template("accounts.html", accounts=rows, broken=broken, shown=shown, message=message, owner=core.ADMIN_USER, players=players,
                           tokens=listed_tokens, shown_token=shown_token, scopes=tokens.SCOPES)


def accounts_action():
    """The forms of the Accounts page. An ID that is not there, or a form left open while someone else changed it, is
    said so; nothing that changes nothing goes into the log of changes."""
    action = request.form.get("action", "")
    name = request.form.get("name", "").strip()
    # The API's tokens: made for the admin signed in, shown once; revoked by their id.
    if action == "token":
        try:
            row, token = tokens.make(request.form.get("token_name", ""), request.form.get("scope", ""), tokens.acting_admin())
        except Refused as e:
            flash(e.words, e.tone)
            return redirect(url_for("accounts_page"))
        _keep("shown_token", {"name": row["name"], "scope": row["scope"], "token": token})
        return redirect(url_for("accounts_page"))
    if action == "revoke":
        try:
            flash(t("tok.revoked", name=tokens.revoke(request.form.get("token", ""))), "ok")
        except Refused as e:
            flash(e.words, e.tone)
        return redirect(url_for("accounts_page"))
    if action == "create":
        note = request.form.get("note", "").strip()[:40]
        try:
            password = create(name, request.form.get("password", ""), request.form.get("password2", ""), note,
                              request.form.get("admin") == "1", request.form.get("player", ""))
        except Refused as e:
            flash(e.words, e.tone)
            return redirect(url_for("accounts_page"))
        return show_once(name, password, note, "acc.made")
    # The game player the account is: any account, the one these pages are open with too.
    if action == "link":
        try:
            name, guid, player = link(name, request.form.get("player", ""))
        except Refused as e:
            # Linked to that player already: nothing to say.
            if e.words is not None:
                flash(e.words, e.tone)
            return redirect(url_for("accounts_page"))
        flash(t("acc.done_link", name=name, player=player) if guid is not None else t("acc.done_unlink", name=name), "ok")
        return redirect(url_for("accounts_page"))
    try:
        done = change(name, action if action in ACTIONS else "", page_acting())
    except Refused as e:
        # Enabling what is enabled, giving rights it has: nothing happens, and nothing is said.
        if e.words is not None:
            flash(e.words, e.tone)
        return redirect(url_for("accounts_page"))
    # The account these pages are open with: a new password for it keeps this sign-in (the session takes the new one).
    if done["own"]:
        session["stamp"] = auth.account_stamp(done["stored"])
    if action == "password":
        return show_once(done["name"], done["password"], done["note"], "acc.new_done")
    flash(t({"off": "acc.done_off", "on": "acc.done_on", "delete": "acc.done_delete", "admin": "acc.done_admin", "player": "acc.done_player"}[action],
            name=done["name"]), "ok")
    return redirect(url_for("accounts_page"))


def page_acting():
    """Who acts on the Accounts page: (ID, owner) of the admin signed in."""
    return str(session.get("who", "")), session.get("stamp") == "owner"


def create(name, password, password2, note, admin_rights, player):
    """Makes an account, as the Accounts page's form does: an ID, a password typed (twice) or, empty, made here, a note,
    admin rights or not, and the game player it is (a guid, or empty for none). Returns the password."""
    if not auth.ACCOUNT_NAME.fullmatch(name):
        raise Refused(400, "bad_id", t("acc.bad_id"))
    if password and not 6 <= len(password) <= 64:
        raise Refused(400, "bad_password", t("acc.bad_password"))
    if password and password2 != password:
        raise Refused(400, "password_mismatch", t("acc.mismatch"))
    guid = account_player(player)
    if guid is False:
        raise Refused(400, "bad_player", t("acc.bad_player"))
    # An empty password field: one is made, easy to read off a phone.
    password = password or auth.account_password()
    if not auth.account_create(name, password, note, admin_rights, guid):
        raise Refused(409, "id_taken", t("acc.taken", name=name))
    changed("accounts_page:create", name)
    return password


def change(name, action, acting):
    """One of an account's buttons: a new password (password), off, on, delete, admin (give admin rights) or player (take
    them away). acting: (ID, owner) of who does it: an admin cannot disable, delete or demote their own account, which is
    for another admin or the owner. Returns {name, password (new, or empty), note, stored (its hash), own}."""
    row = auth.account_find(name)
    if not row or action not in ACTIONS:
        raise Refused(404, "account_not_found", t("acc.gone", name=name))
    name = row["name"]
    who, owner = acting
    own = not owner and name.lower() == who.lower()
    if own and action != "password":
        raise Refused(409, "own_account", t("acc.self", name=name))
    # Enabling what is enabled, giving rights it has: nothing happens, and nothing goes into the log of changes.
    already = {"off": (row["off"], f"The account {name} is disabled already."),
               "on": (not row["off"], f"The account {name} is enabled already."),
               "admin": (row["admin"], f"The account {name} has admin rights already."),
               "player": (not row["admin"], f"The account {name} has no admin rights.")}
    if action in already and already[action][0]:
        raise Refused(409, "already_so", message=already[action][1])
    password = auth.account_password() if action == "password" else ""
    stored = auth.account_hash(password) if password else ""
    try:
        with db() as con:
            if action == "password":
                con.execute("UPDATE SiteUser SET pass = ? WHERE name = ?", (stored, name))
            elif action == "delete":
                con.execute("DELETE FROM SiteUser WHERE name = ?", (name,))
                # Its API tokens with it: the ID may go to someone else later.
                tokens.drop_for(con, name)
            elif action in ("admin", "player"):
                con.execute("UPDATE SiteUser SET admin = ? WHERE name = ?", (1 if action == "admin" else 0, name))
            else:
                con.execute("UPDATE SiteUser SET off = ? WHERE name = ?", (1 if action == "off" else 0, name))
    except sqlite3.Error as e:
        raise Refused(503, "database_unavailable", t("err.db_title") + f": {why(e)}")
    changed(f"accounts_page:{action}", name)
    return {"name": name, "password": password, "note": row["note"], "stored": stored, "own": own}


def account_player(value):
    """The player a form picked: None for none, a player's guid, or False when it names no player there is."""
    try:
        with db() as con:
            return auth.player_choice(value, auth.game_players(con))
    except sqlite3.Error:
        return False if value else None


def link(name, value):
    """Links an account to the game player it is (value: a guid), or unlinks it (empty). Returns (the account's ID as
    kept, guid or None, the player's name). Refused: no such account, no such player, or linked so already (nothing to say
    then)."""
    row = auth.account_find(name)
    if not row:
        raise Refused(404, "account_not_found", t("acc.gone", name=name))
    name = row["name"]
    guid = account_player(value)
    if guid is False:
        raise Refused(400, "bad_player", t("acc.bad_player"))
    if guid == (row["guid"] if "guid" in row.keys() else None):
        raise Refused(409, "already_so", message=f"The account {name} is linked so already.")
    try:
        with db() as con:
            auth.account_table(con)
            con.execute("UPDATE SiteUser SET guid = ? WHERE name = ?", (guid, name))
            player = dict(auth.game_players(con)).get(guid, "")
    except sqlite3.Error as e:
        raise Refused(503, "database_unavailable", t("err.db_title") + f": {why(e)}")
    changed("accounts_page:link", name)
    return name, guid, player
