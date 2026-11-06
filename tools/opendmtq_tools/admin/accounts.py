"""The Accounts page: the sign-ins of the site and of these pages, and each new password shown once."""

import secrets
import sqlite3
import threading
import time

from flask import flash, redirect, render_template, request, session, url_for

from . import apps, auth, core
from .core import ago, app, BASE, changed, db, t, why

# A new account's password, or a new password, shown on the next page only: never in the session's cookie (the browser
# keeps that) and never twice. Waits ten minutes at most. In memory: the service runs one process.
_shown = {}
_shown_lock = threading.Lock()


def keep_once(name, password, note, word):
    """Keeps an account's password for the next page to show, once: the session holds only the way to it."""
    now = time.time()
    token = secrets.token_urlsafe(16)
    with _shown_lock:
        for old in [k for k, v in _shown.items() if now - v["at"] > 600]:
            del _shown[old]
        _shown[token] = {"name": name, "password": password, "note": note, "word": word, "at": now}
    session["shown"] = token


def take_once():
    """The account keep_once kept for this page, once and for ten minutes at most, or None."""
    with _shown_lock:
        shown = _shown.pop(session.pop("shown", ""), None)
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
    rows, broken, players = [], False, []
    try:
        with db() as con:
            auth.account_table(con)
            # The game's players, to link an account to the one it is.
            players = auth.game_players(con)
            # When each last signed in, as long ago as that was; the moment itself under the pointer.
            rows = [dict(r, last=ago(r["signed_in_at"]) if r["signed_in_at"] else "")
                    for r in con.execute("SELECT name, note, admin, created_at, signed_in_at, off, guid FROM SiteUser ORDER BY name COLLATE NOCASE")]
    except sqlite3.Error:
        broken = True
    message = apps.invite_text(apps.friends_address(core.server_health()), shown["name"], shown["password"]) if shown else ""
    return render_template("accounts.html", accounts=rows, broken=broken, shown=shown, message=message, owner=core.ADMIN_USER, players=players)


def accounts_action():
    """The forms of the Accounts page. An ID that is not there, or a form left open while someone else changed it, is
    said so; nothing that changes nothing goes into the log of changes."""
    action = request.form.get("action", "")
    name = request.form.get("name", "").strip()
    if action == "create":
        password = request.form.get("password", "")
        note = request.form.get("note", "").strip()[:40]
        if not auth.ACCOUNT_NAME.fullmatch(name):
            flash(t("acc.bad_id"), "bad")
        elif password and not 6 <= len(password) <= 64:
            flash(t("acc.bad_password"), "bad")
        elif password and request.form.get("password2", "") != password:
            flash(t("acc.mismatch"), "bad")
        elif (guid := account_player(request.form.get("player", ""))) is False:
            flash(t("acc.bad_player"), "bad")
        else:
            # An empty password field: one is made, easy to read off a phone.
            password = password or auth.account_password()
            if auth.account_create(name, password, note, request.form.get("admin") == "1", guid):
                changed("accounts_page:create", name)
                return show_once(name, password, note, "acc.made")
            flash(t("acc.taken", name=name), "bad")
        return redirect(url_for("accounts_page"))
    row = auth.account_find(name)
    if not row or action not in ("password", "off", "on", "delete", "admin", "player", "link"):
        flash(t("acc.gone", name=name), "bad")
        return redirect(url_for("accounts_page"))
    name = row["name"]
    # The game player the account is: any account, the one these pages are open with too.
    if action == "link":
        return account_link(row)
    # The account these pages are open with: a new password for it keeps this sign-in (the session takes the new one).
    # Disabling it, deleting it or changing its rights is for another admin, or the owner.
    own = session.get("stamp") != "owner" and name.lower() == str(session.get("who", "")).lower()
    if own and action != "password":
        flash(t("acc.self", name=name), "bad")
        return redirect(url_for("accounts_page"))
    # Enabling what is enabled, giving rights it has: nothing happens.
    if (action == "off" and row["off"]) or (action == "on" and not row["off"]) \
            or (action == "admin" and row["admin"]) or (action == "player" and not row["admin"]):
        return redirect(url_for("accounts_page"))
    password = auth.account_password() if action == "password" else ""
    stored = auth.account_hash(password) if password else ""
    try:
        with db() as con:
            if action == "password":
                con.execute("UPDATE SiteUser SET pass = ? WHERE name = ?", (stored, name))
            elif action == "delete":
                con.execute("DELETE FROM SiteUser WHERE name = ?", (name,))
            elif action in ("admin", "player"):
                con.execute("UPDATE SiteUser SET admin = ? WHERE name = ?", (1 if action == "admin" else 0, name))
            else:
                con.execute("UPDATE SiteUser SET off = ? WHERE name = ?", (1 if action == "off" else 0, name))
    except sqlite3.Error as e:
        flash(t("err.db_title") + f": {why(e)}", "bad")
        return redirect(url_for("accounts_page"))
    if own:
        session["stamp"] = auth.account_stamp(stored)
    changed(f"accounts_page:{action}", name)
    if action == "password":
        return show_once(name, password, row["note"], "acc.new_done")
    flash(t({"off": "acc.done_off", "on": "acc.done_on", "delete": "acc.done_delete", "admin": "acc.done_admin", "player": "acc.done_player"}[action], name=name), "ok")
    return redirect(url_for("accounts_page"))


def account_player(value):
    """The player a form picked: None for none, a player's guid, or False when it names no player there is."""
    try:
        with db() as con:
            return auth.player_choice(value, auth.game_players(con))
    except sqlite3.Error:
        return False if value else None


def account_link(row):
    """Links an account to the game player it is, or unlinks it; nothing when it is so already."""
    name = row["name"]
    guid = account_player(request.form.get("player", ""))
    if guid is False:
        flash(t("acc.bad_player"), "bad")
        return redirect(url_for("accounts_page"))
    if guid == (row["guid"] if "guid" in row.keys() else None):
        return redirect(url_for("accounts_page"))
    try:
        with db() as con:
            auth.account_table(con)
            con.execute("UPDATE SiteUser SET guid = ? WHERE name = ?", (guid, name))
            player = dict(auth.game_players(con)).get(guid, "")
    except sqlite3.Error as e:
        flash(t("err.db_title") + f": {why(e)}", "bad")
        return redirect(url_for("accounts_page"))
    changed("accounts_page:link", name)
    flash(t("acc.done_link", name=name, player=player) if guid is not None else t("acc.done_unlink", name=name), "ok")
    return redirect(url_for("accounts_page"))
