"""A player's game state on the admin pages: what the game keeps of a player besides their scores (the two currencies its
top bar shows, MAX POINT and Q; the experience their level comes from; the items they have; whether their currency is
unlimited; a ban), the server's own game settings, and every change with who made it and from what to what. The same
tables and rules as the game server's (server/game/src/player.php), which the game's requests go through. The player's
page (player.html) and the API (api.py) call the same functions, as every page does."""

import datetime
import json
import os
import shutil
import sqlite3
import tarfile
import time

from flask import flash, redirect, render_template, request, url_for

from .. import songs
from . import backups, core, players, recordings
from .core import Refused, app, BASE, changed, db, same_text, t, tp, why

# The experience each level starts at, as the client's own level table has it (client 1.3.4, its experience column): level 1 at
# 0, level 99 at 130,408. The game's top bar draws the share of the way from the player's level to the next, so the level
# and the experience must agree: the experience is kept and the level worked out of it, a level set here sets the
# experience to that level's start. The same table as OPENDMTQ_LEVEL_EXP in player.php.
LEVEL_EXP = (
    0, 10, 30, 60, 100, 150, 210, 280, 360, 450, 545, 644, 748, 857, 972, 1093, 1219, 1352, 1492, 1639, 1793, 1954, 2004,
    2182, 2369, 2565, 2771, 2988, 3215, 3453, 3704, 3967, 4243, 4533, 4837, 5157, 5493, 5845, 6215, 6607, 7023, 7464, 7931,
    8426, 8951, 9508, 10081, 10683, 11314, 11978, 12674, 13406, 14174, 14980, 15827, 16716, 17650, 18630, 19610, 20630,
    21690, 22792, 23939, 25132, 26372, 27662, 29003, 29803, 31400, 33061, 34789, 36585, 38453, 40396, 42417, 44518, 46704,
    47904, 50404, 53004, 55708, 58520, 61445, 64487, 67650, 70940, 74361, 77919, 81620, 85469, 89471, 93634, 97963, 102465,
    107148, 108648, 114569, 120904, 130408,
)
# The highest level, and the most experience kept: level 99's start, past which nothing the game shows changes.
LEVEL_TOP = 99
EXP_MAX = LEVEL_EXP[-1]
# The most of a currency a player may hold: what the game's top bar shows whole (player.php OPENDMTQ_POINTS_MAX).
POINTS_MAX = 99_999_999
# What the game is told a player with unlimited currency has, of each (player.php OPENDMTQ_POINTS_UNLIMITED).
POINTS_UNLIMITED = 99_999_999
# What a player starts with until the owner sets other values: what every player had before any of this was kept.
START = {"start_mpoint": 999_999, "start_qpoint": 999_999, "start_level": LEVEL_TOP}
# The longest reason a ban keeps: two lines of the in-game notice.
BAN_REASON_MAX = 200
# How long a ban may be set for here, in days, at most: ten years is as good as no end, which is a choice of its own.
BAN_DAYS_MAX = 3650
# The ends the page offers for a ban, in days (0: until it is lifted).
BAN_ENDS = (0, 1, 3, 7, 30)
# The two currencies by the word the pages and the API use: their column in PlayerState.
CURRENCIES = {"max": "mpoint", "q": "qpoint"}
# The kinds of item a player equips, as songs.py lists them (catalog.json "gear"), with the top bar's slot each one sits in
# (Member.slot_item1 to 4): taken from a player while equipped, the slot is emptied, so that the game shows its own default.
GEAR_SLOTS = {"C": 1, "F": 2, "N": 3, "K": 4}
# Each kind's words on the player's page, as MY PAGE's inventory names them (strings.py).
KIND_WORDS = {"C": "game.kind_partner", "F": "game.kind_addon", "N": "game.kind_note", "K": "game.kind_skin"}
# The words beside an item for how the player came to have it, when it is not as everyone has it: bought in the game's
# shop, or given on these pages.
HOW_WORDS = {"bought": "game.how_bought", "given": "game.how_given"}

# The tables, as setup-db.php makes them (the same statements), kept with the backups' schema, which a restored database
# gets: a database restored from before them gets them here too.
GAME_TABLES = backups.GAME_TABLES


def game_tables(con):
    """Makes the tables where a database has not got them yet (one from before them, restored)."""
    for sql in GAME_TABLES:
        con.execute(sql)


# ------------------------------------------------------------------------------------------------------- the rules

def level_of(exp):
    """The level of a player with exp experience: the highest whose start it has reached, 1 to 99."""
    level = 1
    for i, start in enumerate(LEVEL_EXP):
        if exp >= start:
            level = i + 1
    return min(level, LEVEL_TOP)


def level_exp(level):
    """The experience a level starts at: what a player set to that level has."""
    return LEVEL_EXP[max(1, min(LEVEL_TOP, int(level))) - 1]


def within(value, low, high):
    """value as an int from low to high; anything that is no whole number as low (what another program wrote)."""
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return low


def whole(value):
    """A whole number as a page's field or the API sends it ("1,000" and " 25 " too), or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value if value is not None else "").replace(",", "").replace("_", "").strip()
    return int(text) if text.lstrip("-").isdigit() else None


def settings(con):
    """The server's game settings: {unlimited, start_mpoint, start_qpoint, start_level}, as player.php reads them."""
    out = {"unlimited": False, **START}
    try:
        rows = dict(con.execute("SELECT name, value FROM GameSetting").fetchall())
    except sqlite3.OperationalError:
        rows = {}
    out["unlimited"] = rows.get("unlimited") == "1"
    if "start_level" in rows:
        out["start_level"] = within(rows["start_level"], 1, LEVEL_TOP)
    for name in ("start_mpoint", "start_qpoint"):
        if name in rows:
            out[name] = within(rows[name], 0, POINTS_MAX)
    return out


def state(con, pid, game=None):
    """A player's game state: {mpoint, qpoint, exp, level, own_unlimited, unlimited (theirs or the server's), kept (a row of
    theirs exists), shown_mpoint and shown_qpoint (what the game is told), level_start and level_next (the experience their
    level starts and the next one starts at, the next None at the top), gauge (0 to 1, the top bar's)}. Without a row, the
    server's start values (game: settings(), when the caller has them)."""
    game = game or settings(con)
    try:
        row = con.execute("SELECT mpoint, qpoint, exp, unlimited FROM PlayerState WHERE guid = ?", (pid,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    if row:
        out = {"mpoint": within(row["mpoint"], 0, POINTS_MAX), "qpoint": within(row["qpoint"], 0, POINTS_MAX),
               "exp": within(row["exp"], 0, EXP_MAX), "own_unlimited": row["unlimited"] == 1, "kept": True}
    else:
        out = {"mpoint": game["start_mpoint"], "qpoint": game["start_qpoint"], "exp": level_exp(game["start_level"]),
               "own_unlimited": False, "kept": False}
    out["level"] = level_of(out["exp"])
    out["unlimited"] = out["own_unlimited"] or game["unlimited"]
    out["shown_mpoint"] = POINTS_UNLIMITED if out["unlimited"] else out["mpoint"]
    out["shown_qpoint"] = POINTS_UNLIMITED if out["unlimited"] else out["qpoint"]
    # The gauge as the game draws it (its level table works out the share): full at the top level.
    out["level_start"] = LEVEL_EXP[out["level"] - 1]
    out["level_next"] = LEVEL_EXP[out["level"]] if out["level"] < LEVEL_TOP else None
    out["gauge"] = 1.0 if out["level_next"] is None else (out["exp"] - out["level_start"]) / (out["level_next"] - out["level_start"])
    return out


def write_state(con, pid, values):
    """Keeps a player's state with the values given changed ({mpoint, qpoint, exp, unlimited}): a player without a row gets
    one from the server's start values first, as the game server makes one."""
    now = state(con, pid)
    row = {"mpoint": now["mpoint"], "qpoint": now["qpoint"], "exp": now["exp"], "unlimited": int(now["own_unlimited"])}
    row.update(values)
    con.execute("""INSERT INTO PlayerState (guid, mpoint, qpoint, exp, unlimited, changed_at) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (guid) DO UPDATE SET mpoint = excluded.mpoint, qpoint = excluded.qpoint, exp = excluded.exp,
                       unlimited = excluded.unlimited, changed_at = excluded.changed_at""",
                (pid, row["mpoint"], row["qpoint"], row["exp"], int(row["unlimited"]), int(time.time())))


def catalog():
    """What the client's tables give the server (custom/catalog.json, songs.py): the items everyone has, the shop's
    products, the items a player equips by kind, and those items' names as the game shows them in each language. Empty
    parts without the client's tables."""
    try:
        with open(os.path.join(songs.CUSTOM, "catalog.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    return {"items": data.get("items") or [], "products": data.get("products") or {}, "gear": data.get("gear") or {},
            "names": data.get("names") or {}}


def item_name(cat, item, name=""):
    """An item's name as the game shows it in the page's language (the catalog's names), else the item table's own (name),
    else its number in words."""
    return (cat.get("names") or {}).get(core.lang(), {}).get(str(item)) or name or tp("game.item_n", id=item)


def owned_items(con, pid, cat=None):
    """The items a player has: every item everyone has (the catalog's), but those taken from them, and those they bought
    or were given. {item id: how} with how "everyone", "bought", "given" (player.php odq_owned_items())."""
    cat = cat or catalog()
    out = {int(i): "everyone" for i in cat["items"]}
    try:
        rows = con.execute("SELECT item_id, owned, how FROM PlayerItem WHERE guid = ?", (pid,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for r in rows:
        if r["owned"] == 1:
            out[r["item_id"]] = r["how"]
        else:
            out.pop(r["item_id"], None)
    return out


def gear(con, pid, cat=None):
    """The items a player equips, by kind (C partners, F add-ons, N note skins, K skins), each as {id, name, owned, how}:
    what the player's page lists to give and take."""
    cat = cat or catalog()
    have = owned_items(con, pid, cat)
    out = []
    for kind in GEAR_SLOTS:
        # Each item with the key of its words for how it came, when it came some way of its own (HOW_WORDS).
        items = [{"id": int(i), "name": item_name(cat, i, name), "owned": int(i) in have, "how": have.get(int(i), ""),
                  "how_words": HOW_WORDS.get(have.get(int(i), ""))} for i, name in cat["gear"].get(kind, [])]
        out.append({"kind": kind, "words": KIND_WORDS[kind], "items": items, "owned": sum(1 for i in items if i["owned"])})
    return out


def ban_of(con, pid):
    """A player's ban while it lasts: {reason, since, until (None: until lifted), by}, or None (player.php odq_ban_of())."""
    try:
        row = con.execute("SELECT reason, since, until, by FROM PlayerBan WHERE guid = ?", (pid,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row or (row["until"] is not None and row["until"] <= time.time()):
        return None
    return {"reason": row["reason"], "since": row["since"], "until": row["until"], "by": row["by"]}


def banned(con):
    """Every ban that lasts, newest first: [{id, name, reason, since, until, by, seen}]."""
    try:
        rows = con.execute("SELECT guid, reason, since, until, by FROM PlayerBan WHERE until IS NULL OR until > ? "
                           "ORDER BY since DESC", (int(time.time()),)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"id": r["guid"], "name": players.player_label(con, r["guid"]), "reason": r["reason"], "since": r["since"],
             "until": r["until"], "by": r["by"], "seen": players.player_seen(con, r["guid"]) or ""} for r in rows]


def purchases(con, pid, limit=20):
    """A player's latest purchases in the game, newest first: [{at, product, item, name, currency, price, paid}]."""
    cat = catalog()
    names = {i: n for kind in cat["gear"].values() for i, n in kind}

    def name_of(row):
        """What was bought, in words: a pack of MAX POINT by its amount, a level unlock by its product, an item by its name."""
        product = cat["products"].get(str(row["product_id"])) or {}
        if product.get("kind") == "M":
            return tp("game.pack", amount=number(product.get("amount", 0)))
        if product.get("kind") == "L":
            return tp("game.unlock", id=row["product_id"])
        return item_name(cat, row["item_id"], names.get(row["item_id"], ""))

    try:
        rows = con.execute("SELECT at, product_id, item_id, currency, price, paid FROM PlayerPurchase WHERE guid = ? "
                           "ORDER BY at DESC, id DESC LIMIT ?", (pid, limit)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    return [{"at": r["at"], "product": r["product_id"], "item": r["item_id"], "name": name_of(r), "currency": r["currency"],
             "price": r["price"], "paid": r["paid"]} for r in rows]


def history(pid, limit=40):
    """What was changed about a player on these pages and through the API, newest first: the lines of the log of changes
    that name them (core.changed's player), each with its words in the page's language (the Logs page's table)."""
    from . import logs
    lines = [c for c in core.insights.audit_read(os.path.dirname(core.DB), limit=2000) if c.get("player") == pid]
    return [logs.change_view(c) for c in lines[:limit]]


# ------------------------------------------------------------------------------------------------------- the changes

def player_or_refuse(con, pid, seen):
    """The player's name as the pages say it, or Refused: a number nobody has (404) or that is someone else's now (409)."""
    now_seen = players.player_seen(con, pid)
    if now_seen is None:
        raise Refused(404, "player_not_found", t("players.gone", id=pid))
    if seen is not None and not same_text(seen, now_seen):
        raise Refused(409, "stale", t("err.stale_form"))
    return players.player_label(con, pid)


def number(n):
    """A figure as the game shows it: with thousands separators."""
    return f"{n:,}"


def change_currency(pid, currency, how, amount, seen=None):
    """Sets a player's MAX POINT or Q (currency "max" or "q") to amount, or adds amount to it, or takes amount from it (how
    "set", "add", "take"). Within what the game shows: 0 to 99,999,999 after the change, and amount a whole number. Returns
    {who, before, after}."""
    if currency not in CURRENCIES or how not in ("set", "add", "take"):
        raise Refused(400, "bad_field", t("game.bad_action"))
    n = whole(amount)
    if n is None or n < 0 or n > POINTS_MAX or (how != "set" and n == 0):
        raise Refused(400, "bad_amount", t("game.bad_amount"))
    with db() as con:
        game_tables(con)
        con.execute("BEGIN IMMEDIATE")
        who = player_or_refuse(con, pid, seen)
        before = state(con, pid)[CURRENCIES[currency]]
        after = n if how == "set" else before + n if how == "add" else before - n
        if after > POINTS_MAX:
            raise Refused(400, "too_much", t("game.too_much", n=number(after), most=number(POINTS_MAX)))
        if after < 0:
            raise Refused(400, "too_little", t("game.too_little", n=number(before)))
        write_state(con, pid, {CURRENCIES[currency]: after})
        changed("player_game:" + currency, f"{who}: {number(before)} → {number(after)}", player=pid, before=before, after=after)
    return {"who": who, "before": before, "after": after}


def change_unlimited(pid, on, seen=None):
    """A player's own unlimited switch: on, the game is told they have 99,999,999 of each currency and nothing is taken by a
    purchase or a chart, which are kept as usual; their own balance stays as it is underneath. Returns {who, before, after}."""
    with db() as con:
        game_tables(con)
        con.execute("BEGIN IMMEDIATE")
        who = player_or_refuse(con, pid, seen)
        before = state(con, pid)["own_unlimited"]
        if before != bool(on):
            write_state(con, pid, {"unlimited": int(bool(on))})
            changed("player_game:unlimited-" + ("on" if on else "off"), who, player=pid, before=before, after=bool(on))
    return {"who": who, "before": before, "after": bool(on)}


def change_level(pid, level=None, exp=None, seen=None):
    """Sets a player's level (its experience goes to that level's start) or their experience (the level follows it):
    level 1 to 99, experience 0 to 130,408 (level 99's start). Returns {who, before, after}: (level, experience) each."""
    lv, xp = whole(level), whole(exp)
    if (level is None) == (exp is None):
        raise Refused(400, "level_or_exp", t("game.level_or_exp"))
    if level is not None and (lv is None or not 1 <= lv <= LEVEL_TOP):
        raise Refused(400, "bad_level", t("game.bad_level"))
    if exp is not None and (xp is None or not 0 <= xp <= EXP_MAX):
        raise Refused(400, "bad_exp", t("game.bad_exp"))
    with db() as con:
        game_tables(con)
        con.execute("BEGIN IMMEDIATE")
        who = player_or_refuse(con, pid, seen)
        now = state(con, pid)
        new_exp = level_exp(lv) if level is not None else xp
        before, after = (now["level"], now["exp"]), (level_of(new_exp), new_exp)
        if after != before:
            write_state(con, pid, {"exp": new_exp})
            # Set as a level or as an experience: the change says which.
            changed("player_game:level" if level is not None else "player_game:exp",
                    f"{who}: Lv.{before[0]} ({number(before[1])}) → Lv.{after[0]} ({number(after[1])})", player=pid,
                    before=list(before), after=list(after))
    return {"who": who, "before": before, "after": after}


def change_item(pid, item, give, seen=None):
    """Gives a player an item they equip (a partner, add-on, note skin or skin of the catalog), or takes it from them; an
    item they have equipped, taken, is unequipped too, so that the game shows its own default in its place. Returns {who,
    name, owned}."""
    cat = catalog()
    kinds = {int(i): (kind, name) for kind, items in cat["gear"].items() for i, name in items if kind in GEAR_SLOTS}
    iid = whole(item)
    if iid is None or iid not in kinds:
        raise Refused(404, "item_not_found", t("game.no_item", id=item))
    kind, name = kinds[iid]
    # As the game shows it in the page's language (the change log keeps the words of the page it was made on).
    name = item_name(cat, iid, name)
    with db() as con:
        game_tables(con)
        con.execute("BEGIN IMMEDIATE")
        who = player_or_refuse(con, pid, seen)
        has = iid in owned_items(con, pid, cat)
        if has == bool(give):
            return {"who": who, "name": name, "owned": has}
        con.execute("""INSERT INTO PlayerItem (guid, item_id, owned, how, at) VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT (guid, item_id) DO UPDATE SET owned = excluded.owned, how = excluded.how, at = excluded.at""",
                    (pid, iid, int(bool(give)), "given" if give else "taken", int(time.time())))
        if not give:
            # Out of its slot on every phone of the player: the game shows its default there.
            slot = f"slot_item{GEAR_SLOTS[kind]}"
            con.execute(f"UPDATE Member SET {slot} = NULL WHERE CAST(guid AS INTEGER) = ? AND {slot} = ?", (pid, iid))
        changed("player_game:" + ("give" if give else "take"), f"{who}: {name}", player=pid, before=has, after=bool(give), item=iid)
    return {"who": who, "name": name, "owned": bool(give)}


def end_broadcast(pid):
    """A player's broadcast ends now, as the switch off ends it: the live window goes and the recording is closed and kept.
    Their switch stays as it is."""
    shutil.rmtree(recordings.live_folder(pid), ignore_errors=True)
    for rec in recordings.rec_player(pid):
        if rec["open"]:
            with open(os.path.join(rec["dir"], ".close-now"), "a", encoding="utf-8"):
                pass
    recordings.rec_sweep_now()


def ban(pid, reason, days=0, until=None, seen=None):
    """Bans a player, with the owner's reason and an end: days from now (0 or none: until it is lifted) or until (a Unix
    time, the API's). The game refuses their sign-in and each request of theirs, showing the reason over the game; the site
    and the PC client refuse their accounts; their broadcast ends. A ban already there is replaced. Returns {who, until}."""
    words = " ".join((reason or "").split())
    if not words:
        raise Refused(400, "no_reason", t("game.no_reason"))
    if len(words) > BAN_REASON_MAX:
        raise Refused(400, "bad_reason", t("game.long_reason", most=BAN_REASON_MAX))
    now = int(time.time())
    if until is not None:
        end = whole(until)
        if end is None or end <= now:
            raise Refused(400, "bad_until", t("game.bad_until"))
        # No further off than the longest ban the page sets in days: past that a date is past what the log's words and
        # the database's numbers hold (a year after 9999, a number past 64 bits), and a request would end in an error.
        if end > now + BAN_DAYS_MAX * 86400:
            raise Refused(400, "bad_until", t("game.far_until", most=BAN_DAYS_MAX))
    else:
        d = whole(days) if days not in (None, "") else 0
        if d is None or not 0 <= d <= BAN_DAYS_MAX:
            raise Refused(400, "bad_days", t("game.bad_days", most=BAN_DAYS_MAX))
        end = now + d * 86400 if d else None
    with db() as con:
        game_tables(con)
        con.execute("BEGIN IMMEDIATE")
        who = player_or_refuse(con, pid, seen)
        before = ban_of(con, pid)
        con.execute("""INSERT INTO PlayerBan (guid, reason, since, until, by) VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT (guid) DO UPDATE SET reason = excluded.reason, since = excluded.since, until = excluded.until,
                           by = excluded.by""", (pid, words, now, end, core.acting_who()))
        # Told in the game as it is made: the ban's notice waits for the player's game, which asks for the broadcast's
        # state every few seconds (server/game/live/state.php hands it out then, in a song too, in the game's language),
        # as a refused sign-in leaves it. A new number each time, in place of a notice not read yet. The live view's table
        # as it is now first, for a database restored from before it.
        recordings.live_table(con)
        con.execute("""INSERT INTO LiveSwitch (guid, live, toast, toast_id) VALUES (?, 0, 'ban', 1)
                       ON CONFLICT (guid) DO UPDATE SET toast = 'ban', toast_id = LiveSwitch.toast_id + 1""", (pid,))
        changed("player_game:ban", f"{who}: {words}" + (f" · {datetime.datetime.fromtimestamp(end):%Y-%m-%d %H:%M}" if end else ""),
                player=pid, before=bool(before), after=True)
    end_broadcast(pid)
    return {"who": who, "until": end}


def unban(pid, seen=None):
    """Lifts a player's ban: they sign in again, to the game and the site. A ban's notice they have not seen yet goes with it.
    Returns {who, was} (was: whether a ban lasted)."""
    with db() as con:
        game_tables(con)
        con.execute("BEGIN IMMEDIATE")
        who = player_or_refuse(con, pid, seen)
        was = ban_of(con, pid) is not None
        # A ban that ran out by itself is tidied away too.
        con.execute("DELETE FROM PlayerBan WHERE guid = ?", (pid,))
        try:
            con.execute("UPDATE LiveSwitch SET toast = '' WHERE guid = ? AND toast = 'ban'", (pid,))
        except sqlite3.OperationalError:
            pass
        if was:
            changed("player_game:unban", who, player=pid, before=True, after=False)
    return {"who": who, "was": was}


def reset_game(pid, seen=None):
    """A player's game state back to what a new player starts with (the server's start values, the items everyone has, no
    purchases), their scores, achievements, name and ban as they are. A backup first, as for the Players page's resets.
    Returns {who, backup}."""
    with db() as con:
        who = player_or_refuse(con, pid, seen)
    try:
        with backups._restoring:
            backup = backups.make_backup("before-player-game-reset")
    except (sqlite3.Error, OSError, tarfile.TarError) as e:
        raise Refused(500, "backup_failed", t("bak.failed", detail=why(e)))
    with db() as con:
        game_tables(con)
        con.execute("BEGIN IMMEDIATE")
        who = player_or_refuse(con, pid, seen)
        for table in ("PlayerState", "PlayerItem", "PlayerUnlock", "PlayerPurchase"):
            con.execute(f"DELETE FROM {table} WHERE guid = ?", (pid,))
        changed("player_game:reset", who, player=pid)
    return {"who": who, "backup": backup}


def forget(con, pid):
    """Everything of a player's game state, as they are deleted (players.act's delete, in its transaction)."""
    game_tables(con)
    for table in ("PlayerState", "PlayerItem", "PlayerUnlock", "PlayerPurchase", "PlayerBan"):
        con.execute(f"DELETE FROM {table} WHERE guid = ?", (pid,))


def save_settings(unlimited=None, start_mpoint=None, start_qpoint=None, start_level=None):
    """Changes the server's game settings given: unlimited currency for every player, and what a new player starts with.
    New start values reach new players alone: every player there is now keeps what they have (a row of their own is kept
    for each with the values before). Returns the settings after."""
    given = {}
    for name, value, high in (("start_mpoint", start_mpoint, POINTS_MAX), ("start_qpoint", start_qpoint, POINTS_MAX),
                              ("start_level", start_level, LEVEL_TOP)):
        if value is None:
            continue
        n = whole(value)
        low = 1 if name == "start_level" else 0
        if n is None or not low <= n <= high:
            # The words the player's page gives the same field: a currency's, or the level's.
            raise Refused(400, "bad_" + name, t("game.bad_level") if name == "start_level" else t("game.bad_amount"))
        given[name] = n
    with db() as con:
        game_tables(con)
        con.execute("BEGIN IMMEDIATE")
        was = settings(con)
        now = {**was, **given}
        if unlimited is not None:
            now["unlimited"] = bool(unlimited)
        if any(now[k] != was[k] for k in given):
            # Everyone there now keeps what they have: a row of their own, from the values before, for each without one.
            con.execute(f"""INSERT INTO PlayerState (guid, mpoint, qpoint, exp, unlimited, changed_at)
                            SELECT guid, ?, ?, ?, 0, ? FROM ({core.PLAYER_ROWS}) WHERE guid > 0 ON CONFLICT (guid) DO NOTHING""",
                        (was["start_mpoint"], was["start_qpoint"], level_exp(was["start_level"]), int(time.time()), core.CHECK_UDID))
            for k in given:
                con.execute("INSERT INTO GameSetting (name, value) VALUES (?, ?) ON CONFLICT (name) DO UPDATE SET value = excluded.value",
                            (k, str(now[k])))
            changed("game_settings:start", f"MAX {number(was['start_mpoint'])} / Q {number(was['start_qpoint'])} / Lv.{was['start_level']} → "
                    f"MAX {number(now['start_mpoint'])} / Q {number(now['start_qpoint'])} / Lv.{now['start_level']}")
        if now["unlimited"] != was["unlimited"]:
            con.execute("INSERT INTO GameSetting (name, value) VALUES ('unlimited', ?) ON CONFLICT (name) DO UPDATE SET value = excluded.value",
                        ("1" if now["unlimited"] else "0",))
            changed("game_settings:unlimited-" + ("on" if now["unlimited"] else "off"))
    return now


# ------------------------------------------------------------------------------------------------------- the page

def player_view(pid):
    """Everything the player's page shows of a player: their row of the Players page, their game state, items, ban,
    purchases and changes; 404 for a number nobody has."""
    found = players.player_rows(only=pid)[0]
    if not found:
        raise Refused(404, "player_not_found", t("players.gone", id=pid))
    with db() as con:
        game = settings(con)
        view = {"id": pid, "name": players.player_label(con, pid), "nickname": (found[0]["nickname"] or "").strip(),
                "seen": players.player_seen(con, pid) or "", "state": state(con, pid, game), "gear": gear(con, pid),
                "ban": ban_of(con, pid), "purchases": purchases(con, pid), "game": game,
                "charts": found[0]["charts"], "total": found[0]["total"]}
    view["history"] = history(pid)
    return view


@app.route(BASE + "/players/<int:pid>")
def player_page(pid):
    try:
        view = player_view(pid)
    except Refused as e:
        flash(e.words, e.tone)
        return redirect(url_for("players_page"))
    return render_template("player.html", p=view, ends=BAN_ENDS, top=LEVEL_TOP, most=POINTS_MAX, exp_max=EXP_MAX)


@app.route(BASE + "/players/<int:pid>/game", methods=["POST"])
def player_game_action(pid):
    """The player's page's forms: action currency (with currency, how, amount), unlimited-on and -off, level, exp, give and
    take (item), ban (reason, days), unban, reset."""
    f = request.form
    action = f.get("action", "")
    # Whom the page saw the number belong to: in its address (the page's buttons) or in the form. Neither: refused as stale.
    seen = request.args.get("seen") or f.get("seen", "")
    try:
        if action == "currency":
            done = change_currency(pid, f.get("currency", ""), f.get("how", ""), f.get("amount", ""), seen)
            key = "game.max_done" if f.get("currency") == "max" else "game.q_done"
            flash(t(key, who=done["who"], n=number(done["after"])), "ok")
        elif action in ("unlimited-on", "unlimited-off"):
            done = change_unlimited(pid, action == "unlimited-on", seen)
            flash(t("game.unlimited_on_done" if action == "unlimited-on" else "game.unlimited_off_done", who=done["who"]), "ok")
        elif action in ("level", "exp"):
            done = change_level(pid, level=f.get("level") if action == "level" else None, exp=f.get("exp") if action == "exp" else None, seen=seen)
            flash(t("game.level_done", who=done["who"], level=done["after"][0], exp=number(done["after"][1])), "ok")
        elif action in ("give", "take"):
            # The item in the button's own address (one form for every item) or in the form, as a program may send it.
            done = change_item(pid, request.args.get("item") or f.get("item", ""), action == "give", seen)
            flash(t("game.given" if action == "give" else "game.taken", who=done["who"], name=done["name"]), "ok")
        elif action == "ban":
            done = ban(pid, f.get("reason", ""), f.get("days", "0"), seen=seen)
            flash(t("game.banned_until" if done["until"] else "game.banned", who=done["who"],
                    when=datetime.datetime.fromtimestamp(done["until"]).strftime("%Y-%m-%d %H:%M") if done["until"] else ""), "ok")
        elif action == "unban":
            done = unban(pid, seen)
            flash(t("game.unbanned", who=done["who"]), "ok")
        elif action == "reset":
            done = reset_game(pid, seen)
            flash(t("game.reset_done", who=done["who"]), "ok")
        else:
            raise Refused(400, "bad_action", t("game.bad_action"))
    except Refused as e:
        flash(e.words, e.tone)
        # A number nobody has now: back to the list.
        if e.code == "player_not_found":
            return redirect(url_for("players_page"))
    # Back where the form was: the list of bans on the Players page, or the player's page.
    if f.get("back") == "players":
        return redirect(url_for("players_page"))
    return redirect(url_for("player_page", pid=pid))


@app.route(BASE + "/players/game", methods=["POST"])
def game_settings_action():
    """The Players page's game card: unlimited currency for every player on or off, and what new players start with."""
    f = request.form
    action = f.get("action", "")
    try:
        if action in ("unlimited-on", "unlimited-off"):
            save_settings(unlimited=action == "unlimited-on")
            flash(t("game.all_on_done" if action == "unlimited-on" else "game.all_off_done"), "ok")
        elif action == "start":
            now = save_settings(start_mpoint=f.get("start_mpoint"), start_qpoint=f.get("start_qpoint"), start_level=f.get("start_level"))
            flash(t("game.start_done", mpoint=number(now["start_mpoint"]), qpoint=number(now["start_qpoint"]), level=now["start_level"]), "ok")
        else:
            raise Refused(400, "bad_action", t("game.bad_action"))
    except Refused as e:
        flash(e.words, e.tone)
    return redirect(url_for("players_page") + "#game")
