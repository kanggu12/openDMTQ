"""What the players' site shows (server/portal), read the same way for the API (api.py): the songs the server serves, the
rankings, a chart's leaderboard, a player's page, the newest plays and records, who is on air and the past broadcasts.

Every query follows the portal's (lib.php, songs.php, song.php, ranking.php, player.php, index.php, live_lib.php): one row
per player by PLAYER_ROWS (core.py, as PLAYER_ROWS in lib.php), the server's check account left out, scores capped as
SCORE_SQL caps them. Names are the site's, in English: a player without a name is "Player <n>"."""

import calendar
import datetime
import json
import os
import sqlite3
import time
import urllib.parse

from .. import songs
from . import core, recordings, song_pages

# A stored score as the rankings sum it (SCORE_SQL in lib.php): rows saved before the game capped them, or restored from
# an old backup, can be forged and huge, and their sum would overflow.
SCORE_SQL = "MIN(MAX(p.score, 0), 2147483647)"

# One player's figures in Play, as columns of a query on Play p (PLAYER_FIGURES in lib.php).
PLAYER_FIGURES = f"""COUNT(p.pattern_id) AS charts, SUM({SCORE_SQL}) AS total, SUM(p.grade = 'S') AS s_count,
                     SUM(p.isAllCombo = 'Y') AS ac, SUM(p.isPerfectPlay = 'Y') AS perfect,
                     AVG(MIN(MAX(p.judgement, 0), 1000)) AS avg_judgement"""

# Each player's total, from the index alone, only of players who have an account (PLAYER_TOTALS in lib.php).
PLAYER_TOTALS = f"""SELECT p.user_id, SUM({SCORE_SQL}) AS total FROM Play p
                     WHERE p.user_id IN (SELECT guid FROM ({core.PLAYER_ROWS})) GROUP BY p.user_id"""

# The orders the rankings page has, by its tabs: total best score (the default), this month, S grades, perfect plays,
# charts played.
SORTS = ("total", "month", "s_count", "perfect", "charts")

# The difficulty's name, by the song list's signature code, as the game's chart screen calls them.
DIFFICULTIES = {0: "Easy", 1: "Normal", 2: "Hard", 3: "Expert"}

# The grades, best first.
GRADES = ("S", "A", "B", "C", "D", "E", "F")

# What a player's page shows: their last 15 plays, their broadcasts' newest 4, and the last 12 weeks day by day.
RECENT_SHOWN, CASTS_SHOWN, WEEKS = 15, 4, 12

# A leaderboard's places, as a song's page lists them.
BOARD_SHOWN = 100

# A play older than this counts as over whatever the game said (LIVE_SONG_MAX in live_lib.php).
SONG_MAX = 1200

# The recordings a list goes through at most (live_past in lib.php).
PAST_SHOWN = 300

# Seconds since a stream's last upload after which it counts as stopped: its playlist ends (LIVE_STOPPED in live_lib.php).
LIVE_STOPPED = 30


def live_stopped(guid):
    """True when a stream that never said it ended has had no video for LIVE_STOPPED seconds (the phone went silent)."""
    try:
        with open(os.path.join(recordings.live_folder(guid), "stream.json"), encoding="utf-8") as f:
            stream = json.load(f)
        return not stream["ended"] and time.time() - int(stream["updated"]) >= LIVE_STOPPED
    except (OSError, ValueError, KeyError, TypeError):
        return False


def player_name(nickname, guid):
    """A player's name as the site shows it: their own, or "Player <n>" until one is set."""
    return nickname if (nickname or "").strip() else f"Player {int(guid)}"


def song_title(song):
    """A song's name as the site shows it."""
    return (song.get("full_name") or "").strip() or song.get("name", "")


def difficulty_name(signature):
    """The game's name for a chart's difficulty."""
    return DIFFICULTIES.get(signature, f"Type {signature}")


def chart_label(line, difficulty, signature):
    """A chart as the game's mode select names it: 2LINE Hard 5 (the song list's line codes 3, 4 and 5 are 2, 3 and 4 LINE)."""
    return f"{int(line) - 1}LINE {difficulty_name(int(signature))} {int(difficulty)}"


def jacket(song):
    """A song's picture on the server's address: the small web copy when there is one, else the game's own."""
    name = os.path.basename(song.get("name", ""))
    if os.path.isfile(os.path.join(songs.CUSTOM, "thumbs", name + ".jpg")):
        return "/thumbs/" + urllib.parse.quote(song.get("name", ""), safe="") + ".jpg"
    return "/viewImg/eye/" + urllib.parse.quote(song.get("name", ""), safe="") + ".png"


def accuracy(judgement):
    """The game's per-mille judgement as a percentage with one decimal."""
    return round(float(judgement or 0) / 10, 1)


def song_list():
    """The songs the server serves, hidden ones included (the site leaves those out of its lists)."""
    return song_pages.served_song_list()


def songs_by_id():
    """Songs by their id."""
    return {int(s["song_id"]): s for s in song_list() if "song_id" in s}


def chart_map():
    """pattern id -> (song id, line, difficulty, signature), from the list the server serves."""
    return {int(p["pattern_id"]): (int(s["song_id"]), int(p["line"]), int(p["difficulty"]), int(p["signature"]))
            for s in song_list() for p in s.get("song_patterns", [])}


def chart_info(pattern, charts=None, by_id=None):
    """A chart by its pattern id: {chart, song (id), title, chart_name (its words)}; the song's fields are None for a chart
    the server does not list."""
    charts = chart_map() if charts is None else charts
    by_id = songs_by_id() if by_id is None else by_id
    sid, line, diff, sig = charts.get(int(pattern), (0, 0, 0, 0))
    song = by_id.get(sid)
    return {"chart": int(pattern), "song": sid if song else None, "title": song_title(song) if song else None,
            "chart_name": chart_label(line, diff, sig) if song else None}


def has_playlog(con):
    """True when the play log is there (the server makes it at start)."""
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE name = 'PlayLog'").fetchone())


def _figures(row):
    """A player's figures as the API says them."""
    return {"id": int(row["id"]), "name": player_name(row["nickname"], row["id"]), "charts": int(row["charts"] or 0),
            "total": int(row["total"] or 0), "s_count": int(row["s_count"] or 0), "all_combos": int(row["ac"] or 0),
            "perfect_plays": int(row["perfect"] or 0), "accuracy": accuracy(row["avg_judgement"])}


def players(con):
    """Every player with the rankings' figures, best total first, the older account first on a tie; rank among those
    who played (players() in lib.php)."""
    figures = {int(r["user_id"]): r for r in con.execute(f"SELECT p.user_id, {PLAYER_FIGURES} FROM Play p GROUP BY p.user_id")
               if r["user_id"] is not None}
    rows = []
    for r in con.execute(core.PLAYER_ROWS, (core.CHECK_UDID,)):
        f = figures.get(int(r["guid"]))
        rows.append(_figures({"id": r["guid"], "nickname": r["nickname"], "charts": f["charts"] if f else 0, "total": f["total"] if f else 0,
                              "s_count": f["s_count"] if f else 0, "ac": f["ac"] if f else 0, "perfect": f["perfect"] if f else 0,
                              "avg_judgement": f["avg_judgement"] if f else 0}))
    rows.sort(key=lambda p: (-p["total"], p["id"]))
    rank = 0
    for p in rows:
        if p["charts"] > 0:
            rank += 1
            p["rank"] = rank
        else:
            p["rank"] = None
    return rows


def month_start(back=0):
    """Where a month's rankings begin, back months ago (-1: the next): the first of the month at midnight UTC, as the game
    counts down to it."""
    now = datetime.datetime.now(datetime.timezone.utc)
    month, year = now.month - back, now.year
    while month < 1:
        month, year = month + 12, year - 1
    while month > 12:
        month, year = month - 12, year + 1
    return calendar.timegm((year, month, 1, 0, 0, 0))


def month_players(con, since, until):
    """The players of one month, best first, as the game ranks them: the sum of each one's best score per chart in that
    month from the play log, the older account first on a tie (month_players() in lib.php)."""
    rows = con.execute(
        f"""SELECT m.guid AS id, m.nickname, b.score, b.charts FROM (
                SELECT guid, SUM(best) AS score, COUNT(*) AS charts FROM (
                    SELECT l.user_id AS guid, MAX(MIN(MAX(l.score, 0), 2147483647)) AS best FROM PlayLog l
                     WHERE l.played_at >= ? AND l.played_at < ? GROUP BY l.user_id, l.pattern_id)
                 GROUP BY guid) b
              JOIN ({core.PLAYER_ROWS}) m ON m.guid = b.guid
             ORDER BY b.score DESC, m.guid ASC""", (since, until, core.CHECK_UDID)).fetchall()
    return [{"id": int(r["id"]), "name": player_name(r["nickname"], r["id"]), "score": int(r["score"]), "charts": int(r["charts"])} for r in rows]


def rankings(con, sort):
    """The rankings page for one of its tabs (SORTS): the players in its order, only those with some of what is ranked,
    each with their place. This month also says when it starts anew and the first three of the months before."""
    if sort == "month":
        playlog = has_playlog(con)
        listed = month_players(con, month_start(), 2 ** 63 - 1) if playlog else []
        past = []
        for back in range(1, 7):
            top = month_players(con, month_start(back), month_start(back - 1))[:3] if playlog else []
            if top:
                start = datetime.datetime.fromtimestamp(month_start(back), datetime.timezone.utc)
                past.append({"month": start.strftime("%Y-%m"), "start": month_start(back), "end": month_start(back - 1), "top": top})
        for place, p in enumerate(listed, 1):
            p["place"] = place
        return {"sort": sort, "items": listed, "starts_anew": month_start(-1), "past_months": past}
    everyone = [p for p in players(con) if p["charts"] > 0]
    key = {"total": "total", "s_count": "s_count", "perfect": "perfect_plays", "charts": "charts"}[sort]
    # Then by total, then the older account first, as on every other page.
    everyone.sort(key=lambda p: (-p[key], -p["total"], p["id"]))
    listed = [p for p in everyone if p[key] > 0]
    for place, p in enumerate(listed, 1):
        p["place"] = place
    return {"sort": sort, "items": listed}


def player_figures(con, guid):
    """One player as players() has them, rank included, or None for somebody who is no player (player_figures() in
    lib.php)."""
    row = con.execute(
        f"""SELECT m.guid AS id, m.nickname, COALESCE(a.charts, 0) AS charts, COALESCE(a.total, 0) AS total,
                   COALESCE(a.s_count, 0) AS s_count, COALESCE(a.ac, 0) AS ac, COALESCE(a.perfect, 0) AS perfect,
                   COALESCE(a.avg_judgement, 0) AS avg_judgement
              FROM ({core.PLAYER_ROWS}) m
              LEFT JOIN (SELECT p.user_id, {PLAYER_FIGURES} FROM Play p WHERE p.user_id = ? GROUP BY p.user_id) a
                ON a.user_id = m.guid
             WHERE m.guid = ?""", (core.CHECK_UDID, guid, guid)).fetchone()
    if not row:
        return None
    out = _figures(row)
    out["rank"] = None
    if out["charts"] > 0:
        # Those ahead of them: a higher total, or the same total and a lower id.
        ahead = con.execute(f"SELECT COUNT(*) FROM ({PLAYER_TOTALS}) WHERE total > ? OR (total = ? AND user_id < ?)",
                            (core.CHECK_UDID, out["total"], out["total"], guid)).fetchone()[0]
        out["rank"] = int(ahead) + 1
    return out


def _play(row, charts, by_id):
    """A play from the play log as the site lists it."""
    return dict(chart_info(row["pattern_id"], charts, by_id), score=int(row["score"] or 0), grade=row["grade"],
                accuracy=accuracy(row["judgement"]), new_record=bool(row["is_record"]), at=int(row["played_at"] or 0))


def player_page(con, guid):
    """A player's page (player.php): their figures and rank, their best records' grades and marks, the last weeks day by
    day, their records by level, their last plays and their newest broadcasts. None for somebody who is no player."""
    me = player_figures(con, guid)
    if not me:
        return None
    charts, by_id = chart_map(), songs_by_id()
    best = con.execute("SELECT * FROM Play WHERE user_id = ? ORDER BY score DESC", (guid,)).fetchall()
    playlog = has_playlog(con)
    recent = [_play(r, charts, by_id) for r in con.execute(
        "SELECT * FROM PlayLog WHERE user_id = ? ORDER BY played_at DESC, id DESC LIMIT ?", (guid, RECENT_SHOWN))] if playlog else []
    grades = {}
    for r in best:
        grades[r["grade"]] = grades.get(r["grade"], 0) + 1
    # The last weeks, a column per week from Monday, as the page's grid: plays per day on this server's clock.
    today = datetime.date.today()
    first = today - datetime.timedelta(days=today.weekday()) - datetime.timedelta(weeks=WEEKS - 1)
    since = int(time.mktime(first.timetuple()))
    days = {}
    if playlog:
        for (at,) in con.execute("SELECT played_at FROM PlayLog WHERE user_id = ? AND played_at >= ?", (guid, since)):
            day = datetime.date.fromtimestamp(int(at)).isoformat()
            days[day] = days.get(day, 0) + 1
    # Their records by the chart's level, out of all the charts of that level the server's songs have.
    levels = {}
    for sid, _line, diff, _sig in charts.values():
        if sid in by_id and diff > 0:
            levels.setdefault(diff, {"level": diff, "charts": 0, "records": 0, "grades": {}})["charts"] += 1
    for r in best:
        diff = charts.get(int(r["pattern_id"] or 0), (0, 0, 0, 0))[2]
        if diff in levels:
            levels[diff]["records"] += 1
            levels[diff]["grades"][r["grade"]] = levels[diff]["grades"].get(r["grade"], 0) + 1
    casts = [x for x in live_past(con) if x["player"] == guid][:CASTS_SHOWN]
    return dict(me, grades={g: grades[g] for g in GRADES if grades.get(g)}, records=len(best), recent=recent,
                activity={"since": first.isoformat(), "days": days}, levels=[levels[k] for k in sorted(levels)], broadcasts=casts)


def player_records(con, guid):
    """A player's best records, best score first, each with when it was set (the newest play that set a record on its
    chart; None for records older than the play log). None for somebody who is no player."""
    if not player_figures(con, guid):
        return None
    charts, by_id = chart_map(), songs_by_id()
    set_at = {}
    if has_playlog(con):
        set_at = {int(r[0]): int(r[1]) for r in con.execute(
            "SELECT pattern_id, MAX(played_at) FROM PlayLog WHERE user_id = ? AND is_record = 1 GROUP BY pattern_id", (guid,))}
    return [dict(chart_info(r["pattern_id"], charts, by_id), score=int(r["score"] or 0), grade=r["grade"],
                 all_combo=r["isAllCombo"] == "Y", perfect_play=r["isPerfectPlay"] == "Y", accuracy=accuracy(r["judgement"]),
                 set_at=set_at.get(int(r["pattern_id"] or 0)))
            for r in con.execute("SELECT * FROM Play WHERE user_id = ? ORDER BY score DESC", (guid,))]


def song_records(con):
    """Records per song (players with a record on its charts, counted by player as the site counts them)."""
    charts = chart_map()
    out = {}
    for pattern, n in con.execute(f"SELECT p.pattern_id, COUNT(*) FROM Play p WHERE p.user_id IN (SELECT guid FROM ({core.PLAYER_ROWS})) GROUP BY p.pattern_id",
                                  (core.CHECK_UDID,)):
        sid = charts.get(int(pattern or 0), (0,))[0]
        out[sid] = out.get(sid, 0) + int(n)
    return out


def _song(song, records=None):
    """A song as the site's song list has it."""
    out = {"id": int(song["song_id"]), "name": song.get("name", ""), "title": song_title(song), "artist": song.get("artist_name", ""),
           "genre": song.get("genre", ""), "jacket": jacket(song), "hidden": song.get("hidden_yn", "N") == "Y"}
    if records is not None:
        out["records"] = records
    return out


def song_page_list(con):
    """The site's song list (songs.php): every song players can see, by title as the site sorts it, with how many records
    its charts have. con may be None (no database): no counts then."""
    counts = song_records(con) if con is not None else {}
    listed = [s for s in song_list() if s.get("hidden_yn", "N") != "Y"]
    # As strcasecmp sorts them: letter case aside, byte by byte.
    listed.sort(key=lambda s: song_title(s).encode("utf-8").lower())
    return [_song(s, counts.get(int(s["song_id"]), 0) if con is not None else None) for s in listed]


def song_page(con, song_id):
    """One song's page (song.php): the song, with every chart in the game's order (lines, then the difficulty's kind, then
    its level) and how many records each has. None for a song the server does not list."""
    song = songs_by_id().get(song_id)
    if not song:
        return None
    patterns = sorted(song.get("song_patterns", []), key=lambda p: (p["line"], p["signature"], p["difficulty"]))
    ids = [int(p["pattern_id"]) for p in patterns]
    counts = {}
    if ids:
        marks = ",".join("?" * len(ids))
        counts = {int(r[0]): int(r[1]) for r in con.execute(
            f"SELECT p.pattern_id, COUNT(*) FROM Play p JOIN ({core.PLAYER_ROWS}) m ON m.guid = p.user_id WHERE p.pattern_id IN ({marks}) GROUP BY p.pattern_id",
            [core.CHECK_UDID] + ids)}
    return {"song": _song(song), "credits": {k: song.get(k, "") for k in ("composed_by", "singer", "feat_by", "arranged_by", "visualized_by")},
            "charts": [{"chart": int(p["pattern_id"]), "line": int(p["line"]) - 1, "difficulty": difficulty_name(int(p["signature"])),
                        "level": int(p["difficulty"]), "chart_name": chart_label(p["line"], p["difficulty"], p["signature"]),
                        "records": counts.get(int(p["pattern_id"]), 0)} for p in patterns]}


def board(con, pattern):
    """A chart's leaderboard (song.php): the best 100, by score, then accuracy, then the older account. None for a
    chart the server does not list."""
    info = chart_info(pattern)
    if info["song"] is None:
        return None
    rows = con.execute(
        f"""SELECT p.*, m.nickname, m.guid AS mid FROM Play p JOIN ({core.PLAYER_ROWS}) m ON m.guid = p.user_id
             WHERE p.pattern_id = ? ORDER BY p.score DESC, p.judgement DESC, p.user_id ASC LIMIT ?""",
        (core.CHECK_UDID, pattern, BOARD_SHOWN)).fetchall()
    items = [{"place": i, "player": int(r["mid"]), "name": player_name(r["nickname"], r["mid"]), "score": int(r["score"] or 0),
              "grade": r["grade"], "all_combo": r["isAllCombo"] == "Y", "perfect_play": r["isPerfectPlay"] == "Y",
              "accuracy": accuracy(r["judgement"])} for i, r in enumerate(rows, 1)]
    return dict(info, items=items)


def top_players(con, limit):
    """The best players who have played, in the order of the rankings: id, name and total only (top_players() in
    lib.php, as the home page lists them)."""
    rows = con.execute(f"""SELECT m.guid AS id, m.nickname, a.total FROM ({PLAYER_TOTALS}) a JOIN ({core.PLAYER_ROWS}) m ON m.guid = a.user_id
                            ORDER BY a.total DESC, m.guid ASC LIMIT ?""", (core.CHECK_UDID, core.CHECK_UDID, limit)).fetchall()
    return [{"id": int(r["id"]), "name": player_name(r["nickname"], r["id"]), "total": int(r["total"] or 0)} for r in rows]


def recent_plays(con, limit, records_only=False, player=None):
    """The newest plays, newest first; with records_only the newest new records, each with the player's best before it (as
    the home page lists them). player: one player's only."""
    if not has_playlog(con):
        return []
    charts, by_id = chart_map(), songs_by_id()
    where, args = ["1"], [core.CHECK_UDID]
    if records_only:
        where.append("l.is_record = 1")
    if player is not None:
        where.append("l.user_id = ?")
        args.append(player)
    rows = con.execute(
        f"""SELECT l.*, m.nickname, m.guid AS mid,
                   (SELECT MAX(p.score) FROM PlayLog p WHERE p.user_id = l.user_id AND p.pattern_id = l.pattern_id
                     AND (p.played_at < l.played_at OR (p.played_at = l.played_at AND p.id < l.id))) AS before
              FROM PlayLog l JOIN ({core.PLAYER_ROWS}) m ON m.guid = l.user_id
             WHERE {" AND ".join(where)} ORDER BY l.played_at DESC, l.id DESC LIMIT ?""", args + [limit]).fetchall()
    return [dict(_play(r, charts, by_id), player=int(r["mid"]), name=player_name(r["nickname"], r["mid"]),
                 best_before=int(r["before"]) if r["before"] is not None else None) for r in rows]


def live_now(con):
    """Who is on air now, as the site's cards show them (live_cards() in lib.php): the switch on and video coming in, with
    what they are doing (a song and its chart while in one) and for how long the broadcast has run (seconds). Nobody while
    broadcasts are off for the server."""
    if not recordings.live_settings()["on"]:
        return []
    try:
        rows = con.execute(f"""SELECT l.guid, l.playing, l.pattern_id, l.play_at, m.nickname
                                 FROM LiveSwitch l JOIN ({core.PLAYER_ROWS}) m ON m.guid = l.guid
                                WHERE l.live = 1 ORDER BY l.guid""", (core.CHECK_UDID,)).fetchall()
    except sqlite3.OperationalError:
        # A database from before the live view: nobody is on air.
        return []
    charts, by_id = chart_map(), songs_by_id()
    out = []
    for r in rows:
        guid = int(r["guid"])
        if not recordings.live_streaming(guid):
            continue
        song = chart = None
        if r["playing"] and time.time() - int(r["play_at"] or 0) < SONG_MAX:
            info = chart_info(r["pattern_id"] or 0, charts, by_id)
            song, chart = info["title"], info["chart_name"]
        try:
            with open(os.path.join(recordings.live_folder(guid), "stream.json"), encoding="utf-8") as f:
                began = int(json.load(f).get("rec") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            began = 0
        out.append({"player": guid, "name": player_name(r["nickname"], guid), "song": song, "chart": chart,
                    "seconds": max(1, int(time.time()) - began) if began else 0})
    return out


def live_past(con):
    """The recordings players may watch, newest first (live_past() in lib.php): closed and not hidden, each with its
    player, start, length and songs (the moment each begins, in seconds from the start; -1 for an older recording that
    did not note it). None while broadcasts are off for the server, as the site shows none."""
    if not recordings.live_settings()["on"]:
        return []
    names = {int(r["guid"]): r["nickname"] for r in con.execute(core.PLAYER_ROWS, (core.CHECK_UDID,))}
    jackets = {song_title(s): jacket(s) for s in song_list()}
    out = []
    for r in [r for r in recordings.rec_all() if not r["open"] and not r["hidden"]][:PAST_SHOWN]:
        started = int(r.get("started") or r["id"])
        listed = [{"title": str(s.get("title", "")), "chart": str(s.get("chart", "")),
                   "at": max(0, int(s["at"]) - started) if "at" in s else -1, "jacket": jackets.get(str(s.get("title", "")))}
                  for s in r.get("songs", []) if isinstance(s, dict)]
        out.append({"key": f"{r['guid']}-{r['id']}", "player": int(r["guid"]), "name": player_name(names.get(int(r["guid"]), ""), r["guid"]),
                    "started": started, "seconds": int(int(r.get("duration_ms") or 0) / 1000 + 0.5), "songs": listed})
    return out


def home(con):
    """The home page (index.php): the app on offer for this address, the best players (8), the newest records (as many as
    sit well beside them), who is on air and the newest recordings."""
    top = top_players(con, 8)
    shown = max(3, min(6, int(len(top) * 0.8 + 0.5)))
    try:
        with open(os.path.join(core.APK, "out", "latest.json"), encoding="utf-8") as f:
            apk = json.load(f)
        apk = apk if isinstance(apk, dict) and os.path.isfile(os.path.join(core.APK, "out", os.path.basename(str(apk.get("file", ""))))) else None
    except (OSError, ValueError):
        apk = None
    app_info = {"file": apk.get("file"), "host": apk.get("host"), "built_at": apk.get("built_at"), "size": apk.get("size"),
                "for_this_address": apk.get("host") == core.PUBLIC_HOST} if apk else None
    return {"app": app_info, "top": top, "records": recent_plays(con, shown, records_only=True), "live": live_now(con),
            "past": live_past(con)[:4]}
