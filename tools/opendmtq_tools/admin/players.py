"""The Players page: everyone who has played, with what they did, and what the owner can do about a player."""

import collections
import datetime
import hashlib
import io
import os
import shutil
import sqlite3
import tarfile

from flask import flash, redirect, render_template, request, url_for

from . import backups, charts, core, insights, recordings
from .core import ago, app, BASE, changed, db, same_text, t, tp, why


def player_label(con, guid):
    """A player's name as the pages show it: "Player <n>" until one is set."""
    row = con.execute(f"SELECT nickname FROM ({core.PLAYER_ROWS}) WHERE guid = ?", (core.CHECK_UDID, guid)).fetchone()
    return (row["nickname"] or "").strip() if row and (row["nickname"] or "").strip() else tp("player.fallback", id=guid)


def player_seen(con, guid):
    """Who a player number belongs to, as a short token of its device ids; None when nobody has it. The game gives a
    new phone the next free number, so the number of a deleted player comes back: a page left open must not reset or
    delete someone else, after a confirmation that named the one before. The forms send what they saw."""
    rows = con.execute("SELECT udid FROM Member WHERE CAST(guid AS INTEGER) = ? ORDER BY id", (guid,)).fetchall()
    return seen_token([r[0] for r in rows]) if rows else None


def players_seen(con):
    """player_seen of every player, in one look through the table: the list of players needs them all, and the number
    in a text column cannot use an index."""
    udids = collections.defaultdict(list)
    for guid, udid in con.execute("SELECT CAST(guid AS INTEGER), udid FROM Member ORDER BY id"):
        udids[guid].append(udid)
    return {guid: seen_token(found) for guid, found in udids.items()}


def seen_token(udids):
    """The short token of a player's device ids."""
    return hashlib.sha256("\n".join(str(u) for u in udids).encode("utf-8", "replace")).hexdigest()[:16]


@app.route(BASE + "/players")
def players_page():
    with db() as con:
        # The player number is the guid (the Profile links and the actions use it). Scores are
        # summed capped, so rows saved before the server capped them cannot overflow the sum.
        rows = con.execute(
            f"""SELECT m.guid AS id, COALESCE(m.nickname, '') AS nickname, COUNT(p.pattern_id) AS charts,
                       COALESCE(SUM(MIN(MAX(p.score, 0), 2147483647)), 0) AS total
                  FROM ({core.PLAYER_ROWS}) m LEFT JOIN Play p ON p.user_id = m.guid
                 GROUP BY m.guid ORDER BY m.guid""", (core.CHECK_UDID,)).fetchall()
        # Who is switched on, and whose video is coming in now.
        live = recordings.live_rows(con)
        seen = players_seen(con)
        # How each has been playing, for the list's last played column and its small line.
        activity = insights.player_activity(con)
        phones = dict(con.execute("SELECT CAST(guid AS INTEGER), COUNT(*) FROM Member WHERE udid IS NOT ? AND guid IS NOT NULL GROUP BY CAST(guid AS INTEGER)", (core.CHECK_UDID,)).fetchall())
    if request.args.get("csv"):
        return players_csv(rows, activity)
    # The busiest day of anyone in the list: every row's cells are on that one scale.
    busiest = max((n for p in rows for n in activity[p["id"]]["days"]), default=0)
    played = {p["id"]: {"last": activity[p["id"]]["last"], "ago": ago(activity[p["id"]]["last"]) if activity[p["id"]]["last"] else "",
                        "recent": activity[p["id"]]["recent"],
                        "spark": charts.days(activity[p["id"]]["days"], busiest, day_tips(activity[p["id"]]["days"]), tp("players.days_label"))} for p in rows}
    return render_template("players.html", players=rows, live=live, seen=seen, played=played, phones=phones)


def csv_text(value):
    """Someone's own text in a CSV row: quoted, and never read as a formula by a spreadsheet."""
    text = (value or "").strip().replace('"', '""')
    if text[:1] in ("=", "+", "-", "@"):
        text = "'" + text
    return f'"{text}"'


def day_tips(counts):
    """Each of the last days' words for its cell: its date and how many plays."""
    today = datetime.date.today()
    return [tp("players.day_tip", day=(today - datetime.timedelta(days=len(counts) - 1 - i)).strftime("%m-%d"), n=n) for i, n in enumerate(counts)]


def players_csv(rows, activity):
    """The list of players as a file, for a spreadsheet."""
    out = io.StringIO()
    # The mark that tells a spreadsheet on Windows this is UTF-8: without it Korean names come out garbled.
    out.write("\ufeffid,name,charts,total_score,plays_30_days,last_played\n")
    for p in rows:
        a = activity[p["id"]]
        last = datetime.datetime.fromtimestamp(a["last"]).strftime("%Y-%m-%d %H:%M") if a["last"] else ""
        out.write(f'{p["id"]},{csv_text(p["nickname"])},{p["charts"]},{p["total"]},{a["recent"]},{last}\n')
    r = app.response_class(out.getvalue(), mimetype="text/csv; charset=utf-8")
    r.headers["Content-Disposition"] = 'attachment; filename="opendmtq-players.csv"'
    return r


@app.route(BASE + "/players/<int:pid>", methods=["POST"])
def player_action(pid):
    action = request.form.get("action")
    with db() as con:
        # A number nobody has any more, or that has gone to someone else since the page was loaded: nothing changes.
        seen = player_seen(con, pid)
        if seen is None:
            flash(t("players.gone", id=pid), "bad")
            return redirect(url_for("players_page"))
        if not same_text(request.form.get("seen", ""), seen):
            flash(t("err.stale_form"), "bad")
            return redirect(url_for("players_page"))
        # The name the Players page shows, as its confirmations say it; read before anything changes.
        who = player_label(con, pid)
        if action == "rename":
            name = request.form.get("name", "").strip()[:20]
            if name == who:
                flash(t("players.same_name"), "ok")
                return redirect(url_for("players_page"))
            # Every phone of the player (a transfer code leaves two rows with one guid).
            con.execute("UPDATE Member SET nickname = ? WHERE CAST(guid AS INTEGER) = ?", (name or " ", pid))
            changed("player_action:rename", f"{who} → {name or player_label(con, pid)}")
            flash(t("players.renamed", who=who, name=name or player_label(con, pid)), "ok")
        elif action in ("reset", "delete"):
            # What cannot be undone leaves a way back. No copy, no change.
            try:
                with backups._restoring:
                    backups.make_backup("before-player-" + action)
            except (sqlite3.Error, OSError, tarfile.TarError) as e:
                flash(t("bak.failed", detail=why(e)), "bad")
                return redirect(url_for("players_page"))
            con.execute("DELETE FROM Play WHERE user_id = ?", (pid,))
            try:
                con.execute("DELETE FROM PlayLog WHERE user_id = ?", (pid,))
            except sqlite3.OperationalError:
                pass
            # Their achievements go with the records that earned them (a database from before the table has none).
            try:
                con.execute("DELETE FROM AchievementDate WHERE user_id = ?", (pid,))
            except sqlite3.OperationalError:
                pass
            if action == "delete":
                con.execute("DELETE FROM Member WHERE CAST(guid AS INTEGER) = ?", (pid,))
            if action == "delete":
                # No switch or video left behind for a player who is gone.
                try:
                    con.execute("DELETE FROM LiveSwitch WHERE guid = ?", (pid,))
                except sqlite3.OperationalError:
                    pass
                shutil.rmtree(recordings.live_folder(pid), ignore_errors=True)
                # Nor recordings of them.
                shutil.rmtree(os.path.join(recordings.rec_root(), str(int(pid))), ignore_errors=True)
            changed("player_action:" + action, who)
            flash(t("players.deleted", who=who) if action == "delete" else t("players.reset_done", who=who), "ok")
        elif action in ("live-on", "live-off"):
            on = action == "live-on"
            recordings.live_set(con, pid, on)
            changed("player_action:" + action, who)
            flash(t("players.live_on" if on else "players.live_off", who=who), "ok")
    # Switching off: the recording is closed right away.
    if action == "live-off":
        recordings.rec_sweep_now()
    return redirect(url_for("players_page"))
