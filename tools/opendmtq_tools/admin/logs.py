"""The Logs page: the server's requests, every play, and what was changed on these pages."""

import collections
import datetime
import gzip
import hashlib
import io
import os
import re
import sqlite3
import time

from flask import redirect, render_template, request, url_for
from markupsafe import Markup

from . import charts, core, insights, players, recordings, site, song_pages, status
from .core import ago, app, BASE, db, t, tp

LOG_KINDS = {"game": "logs.kind_game", "files": "logs.kind_files", "app": "logs.kind_app", "site": "logs.kind_site",
             "live": "logs.kind_live", "admin": "logs.kind_admin", "other": "logs.kind_other"}


def ip_words(ip):
    """An address as the logs' chart shows it: one from inside the server's own networks is not a visitor's."""
    return f"{ip} ({tp('logs.ip_inside')})" if core.lan_only(ip) else ip


def device_words(name):
    """A device as the logs show it: the words of our own in the page's language, product names as they are."""
    key = {"Game app": "device.app", "Script or bot": "device.bot", "Browser": "device.browser", "Server check": "device.check", "–": "device.unknown"}.get(name)
    return t(key) if key else name

# What the log of changes calls each thing done in these pages: note_changes() writes the page and the form's action,
# which is empty for a form with just the one thing to do.
CHANGE_WORDS = {
    "app_page:": "change.app_build", "app_prune:": "change.app_prune", "app_delete:": "change.app_delete",
    "player_action:rename": "change.player_rename", "player_action:reset": "change.player_reset", "player_action:delete": "change.player_delete",
    "player_action:live-on": "change.live_on", "player_action:live-off": "change.live_off",
    "recordings_page:limits": "change.rec_limits", "recordings_page:delete": "change.rec_delete", "recordings_page:delete-player": "change.rec_delete_player",
    "recordings_page:hide": "change.rec_hide", "recordings_page:show": "change.rec_show",
    "recordings_page:broadcasts-on": "change.live_all_on", "recordings_page:broadcasts-off": "change.live_all_off",
    "recordings_page:settings": "change.live_settings",
    "backups_auto:on": "change.backup_auto_on", "backups_auto:off": "change.backup_auto_off",
    "backups_page:create": "change.backup_make", "backups_page:upload": "change.backup_upload",
    "backup_action:delete": "change.backup_delete", "backup_action:restore": "change.backup_restore",
    "songs_page:upload": "change.song_add", "songs_page:hide": "change.song_hide", "songs_page:show": "change.song_show", "songs_page:remove": "change.song_remove",
    "maintenance_page:on": "change.maint_on", "maintenance_page:off": "change.maint_off",
    "accounts_page:create": "change.acc_create", "accounts_page:password": "change.acc_password",
    "accounts_page:off": "change.acc_off", "accounts_page:on": "change.acc_on", "accounts_page:delete": "change.acc_delete",
    "accounts_page:admin": "change.acc_admin", "accounts_page:player": "change.acc_player", "accounts_page:link": "change.acc_link",
    "accounts_page:token": "change.token_make", "accounts_page:revoke": "change.token_revoke",
    # A token the API refused, as a failed sign-in is noted: by "API", with the address it came from.
    "api:refused": "change.api_refused",
    "login:ok": "change.login_ok", "login:failed": "change.login_failed", "logout:": "change.logout",
    # The setup's steps and the Maintenance page's stop (setup.py): the owner signed in by the server PC's own link, the
    # game's files brought in, the address changed, the server stopped.
    "setup:signin": "change.setup_signin", "setup:import": "change.setup_import", "setup:address": "change.setup_address",
    "server:stop": "change.server_stop",
}


def target_words(what, target):
    """What a line was about, in the page's language where it was noted as the pages' own values: the broadcast settings
    ("on, smooth": what new players start with, and the quality) and the recordings' limits ("25 GB / 40 d"). Anything
    else, and a line in another shape, as it was written."""
    if what == "recordings_page:settings":
        start, _, quality = target.partition(", ")
        if start in ("on", "off") and quality in recordings.QUALITY_WORDS:
            return tp("change.settings_to", start=tp("live.new_on" if start == "on" else "live.new_off"),
                      quality=tp(recordings.QUALITY_WORDS[quality]))
    elif what == "recordings_page:limits":
        m = re.fullmatch(r"([0-9.]+) GB / ([0-9]+) d", target)
        if m:
            return tp("change.limits_to", gb=m.group(1), n=int(m.group(2)))
    return target


def change_view(entry):
    """One line of the change log for the page: when, what in words, on what. The file keeps the page and action as they
    were, so that a new language or new wording also covers what was noted before. What this table does not know (a page
    newer than this table) shows as it was written."""
    what = entry["what"]
    words = t(CHANGE_WORDS[what]) if what in CHANGE_WORDS else what
    # A line says who or what it was about in words of the moment it was written. Older lines hold a number: looked up.
    target = entry.get("target", "")
    if not entry.get("named"):
        try:
            if what.startswith("player_action:") or what == "recordings_page:delete-player":
                with db() as con:
                    target = players.player_label(con, int(target))
            elif what.startswith("songs_page:") and target:
                target = song_pages.song_title(int(target))
        except (ValueError, sqlite3.Error):
            pass
    return dict(entry, ago=ago(entry["at"]), words=words, target=target_words(what, target), who=entry.get("who", ""))


def changes():
    """The log of changes as its tab shows it, newest first: each line with its words in the page's language."""
    return [change_view(c) for c in insights.audit_read(os.path.dirname(core.DB))]


# How many of the newest requests the Requests tab lists.
REQUESTS_SHOWN = 400


def requests_found(q, status, kind):
    """The requests read from the log (oldest first, LogRows), and those the tab's filters leave: a word (q), a result
    (2xx to 5xx, or err) and a kind (LOG_KINDS)."""
    # What was asked for by the requests read here; the health checks are not among them.
    rows = insights.read_log(core.LOGS)
    return rows, [r for r in rows if insights.wanted(r, q, status, kind)]


def requests_day(rows, picked):
    """What the tab's chart and cards look at: the last 24 hours of what the filters leave, by hour (insights.by_hour) and
    as rows, and since when the log counts when only its newest part was read (a time, or None)."""
    since = time.time() - 86400
    # Only the newest part of a busy log is read, which may not reach back that far: the chart says from when it counts.
    covered = rows[0]["at"] if rows and rows.cut and rows[0]["at"] > since else None
    return insights.by_hour(picked), [r for r in picked if r["at"] >= since], covered


@app.route(BASE + "/logs")
def logs_page():
    tab = request.args.get("tab", "requests")
    if tab == "plays":
        return plays_tab()
    if tab == "changes":
        return render_template("logs.html", tab="changes", changes=changes())
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    kind = request.args.get("kind", "")
    rows, picked = requests_found(q, status, kind)
    view = {"tab": "requests", "q": q, "status": status, "kind": kind, "kinds": LOG_KINDS, "rows": picked[-REQUESTS_SHOWN:][::-1], "matched": len(picked), "kept": len(rows)}
    # The list alone, as the page shows it and as it asks for it again while it follows the log (rows_answer).
    listed = render_template("log_rows.html", **view)
    if request.args.get("rows"):
        return rows_answer(listed)
    # The chart and the cards follow the filter as the list does, and all look at the same last 24 hours.
    day, last_day, covered = requests_day(rows, picked)
    covered_from = time.strftime("%m-%d %H:%M", time.localtime(covered)) if covered else ""
    timeline = charts.stacked([(time.strftime("%H", time.localtime(at)) + ":00" if i % 4 == 3 else "",
                                tp("logs.c_hour", hour=time.strftime("%m-%d %H:00", time.localtime(at)), ok=fine, bad=failed), fine, failed)
                               for i, (at, fine, failed) in enumerate(day)], (tp("logs.c_fine"), tp("logs.c_failed")), tp("logs.c_title"))
    failed_total = sum(failed for _, _, failed in day)
    fine_total = sum(fine for _, fine, _ in day)
    view.update({"timeline": timeline, "fine_total": fine_total, "failed_total": failed_total, "covered_from": covered_from,
                 "top_paths": charts.ranked([(path, n, n, None) for path, n in insights.top_pages(last_day)], tp("logs.top_paths")),
                 "top_devices": charts.ranked([(device_words(d), n, n, None) for d, n in insights.top(last_day, "device")], tp("logs.top_devices")),
                 "top_ips": charts.ranked([(ip_words(ip), n, n, None) for ip, n in insights.top(last_day, "ip")], tp("logs.top_ips"))})
    # The list in the page, with the tag the page asks with while it follows (nothing comes back until a request comes in):
    # its ETag as rows_answer() sends it, weak (W/) as the bytes sent may be compressed.
    view.update({"listed": Markup(listed), "listed_tag": f'W/"{rows_tag(listed)}"'})
    return render_template("logs.html", **view)


def rows_tag(listed):
    """What tells one list of requests from another, as the page shows it: the same list, the same tag."""
    return hashlib.sha256(listed.encode("utf-8")).hexdigest()[:32]


def rows_answer(listed):
    """The list alone, for the page's own look at new lines every few seconds (admin.js): 304 and nothing while the page
    has it (it asks with its ETag), else the list, compressed where the browser takes it. It was 263 KB every 4 seconds
    at the most a list shows, on this service's own port, which has nothing else that compresses (through the game server
    Apache would, and leaves what comes compressed as it is)."""
    response = app.response_class(listed, mimetype="text/html")
    response.set_etag(rows_tag(listed), weak=True)
    # The page has this list already: 304, and nothing.
    response = response.make_conditional(request)
    # A new list: compressed for a browser that takes that (its rows repeat a great deal).
    if response.status_code == 200 and "gzip" in request.headers.get("Accept-Encoding", ""):
        response.set_data(gzip.compress(response.get_data(), 6))
        response.headers["Content-Encoding"] = "gzip"
    # Caches keep one answer for each way of asking.
    response.vary.add("Accept-Encoding")
    return response

# How many plays one page of the Plays tab shows.
PLAYS_PAGE = 50


def plays_day(text):
    """A day from the tab's date fields, as its first moment on this server's clock. An edited address, or a day the clock
    cannot count from or to the end of (the first and last a date can hold), counts as not given."""
    try:
        day = datetime.datetime.strptime(text or "", "%Y-%m-%d")
        day.timestamp()
        (day + datetime.timedelta(days=1)).timestamp()
    except (ValueError, OverflowError, OSError):
        return None
    return day


def plays_filter(args=None):
    """What the address narrows the plays by (args: its query, the request's own unless given). Days the wrong way round
    are taken as they were meant."""
    args = request.args if args is None else args
    first, last = plays_day(args.get("from")), plays_day(args.get("to"))
    if first and last and first > last:
        first, last = last, first
    player = args.get("player", "")
    return {"q": args.get("q", "").strip(), "player": int(player) if re.fullmatch(r"[0-9]{1,12}", player) else None,
            "from": first, "to": last}


def plays_shown(wanted):
    """The same filter as the form's values, and for the addresses of the other pages and of the file."""
    return {"q": wanted["q"] or None, "player": wanted["player"],
            "from": wanted["from"].date().isoformat() if wanted["from"] else None,
            "to": wanted["to"].date().isoformat() if wanted["to"] else None}


def plays_players(con):
    """Those with plays in the log, by name, for the tab's list. Two with one name (new players start with the same one) are
    told apart by their number."""
    rows = con.execute(f"SELECT DISTINCT m.guid, m.nickname FROM PlayLog l JOIN ({core.PLAYER_ROWS}) m ON m.guid = l.user_id", (core.CHECK_UDID,)).fetchall()
    named = sorted(((r["guid"], (r["nickname"] or "").strip() or tp("player.fallback", id=r["guid"])) for r in rows), key=lambda p: (p[1].lower(), p[0]))
    names = [name for _, name in named]
    return [(guid, f"{name} ({guid})" if names.count(name) > 1 else name) for guid, name in named]


def plays_where(wanted):
    """What the player and the days narrow the play history to, in SQL: (conditions, values after the check account's)."""
    where, args = [], []
    if wanted["player"] is not None:
        where.append("l.user_id = ?")
        args.append(wanted["player"])
    if wanted["from"]:
        where.append("l.played_at >= ?")
        args.append(int(wanted["from"].timestamp()))
    if wanted["to"]:
        # Through the whole of that day.
        where.append("l.played_at < ?")
        args.append(int((wanted["to"] + datetime.timedelta(days=1)).timestamp()))
    return ("WHERE " + " AND ".join(where) if where else ""), args


def plays_total(con, wanted):
    """How many plays the player and the days leave, counted by the database."""
    where, args = plays_where(wanted)
    return con.execute(f"SELECT COUNT(*) FROM PlayLog l JOIN ({core.PLAYER_ROWS}) m ON m.guid = l.user_id {where}", [core.CHECK_UDID] + args).fetchone()[0]


def plays_days(wanted, played=(), today=None):
    """The days the summary's chart runs over: those asked for, else the last 30; but never past today, and, when days were
    asked for, not from before the first play found (played: the days with plays), so that years asked for around a month
    of plays draw that month. Over three months a column is a week (from a Monday) rather than a day, over two years only
    the last two years are drawn. Returns (first day, last day, days per column)."""
    today = today or datetime.date.today()
    last = min(wanted["to"].date(), today) if wanted["to"] else today
    first = wanted["from"].date() if wanted["from"] else last - datetime.timedelta(days=29)
    if wanted["from"] and played:
        first = max(first, min(played))
    if first > last:
        first, last = last, first
    if (last - first).days >= 92:
        # A week a column, from a Monday; two years of them at most, the last ones: the figures still count all of it.
        first = max(first, last - datetime.timedelta(weeks=103))
        return first - datetime.timedelta(days=first.weekday()), last, 7
    return first, last, 1


class PlaysSum:
    """What a list of plays adds up to: how many, new records, the average accuracy, how many players, the grades, and the
    plays on each day. Fed one play at a time (a word was searched for, which only Python can match), or by the database."""

    def __init__(self):
        self.n, self.records, self.judged, self.people = 0, 0, 0, set()
        self.grades, self.days = collections.Counter(), collections.Counter()

    def add(self, play):
        self.n += 1
        self.records += 1 if play["new"] else 0
        self.judged += play["judgement"] or 0
        self.people.add(play["id"])
        self.grades[play["grade"]] += 1
        self.days[datetime.datetime.fromtimestamp(play["when"]).date()] += 1

    def counted(self, con, wanted):
        """The same, from the database: the whole history at the speed of a count, however long it is."""
        where, args = plays_where(wanted)
        rows = f"FROM PlayLog l JOIN ({core.PLAYER_ROWS}) m ON m.guid = l.user_id {where}"
        values = [core.CHECK_UDID] + args
        n, records, judged = con.execute(f"SELECT COUNT(*), COALESCE(SUM(l.is_record), 0), COALESCE(SUM(l.judgement), 0) {rows}", values).fetchone()
        self.n, self.records, self.judged = n, records, judged
        self.people = {r[0] for r in con.execute(f"SELECT DISTINCT l.user_id {rows}", values)}
        self.grades = collections.Counter(dict(con.execute(f"SELECT l.grade, COUNT(*) {rows} GROUP BY l.grade", values).fetchall()))
        # The day as this machine's clock has it, as fromtimestamp() above does.
        self.days = collections.Counter({datetime.date.fromisoformat(d): c for d, c in con.execute(
            f"SELECT date(l.played_at, 'unixepoch', 'localtime') AS d, COUNT(*) {rows} GROUP BY d", values)})
        return self

    def view(self, wanted):
        """The figures and the two charts, for the page."""
        first, last, step = plays_days(wanted, [d for d, n in self.days.items() if n])
        points, day = [], first
        while day <= last:
            n = sum(self.days[day + datetime.timedelta(days=k)] for k in range(step))
            points.append((day, n))
            day += datetime.timedelta(days=step)
        # About six dates under the columns, the last one's among them.
        every = max(1, -(-len(points) // 6))
        words = "chart.week" if step == 7 else "chart.day"
        # The year in the dates too when the chart crosses one.
        shape = "%Y-%m-%d" if first.year != last.year else "%m-%d"
        days = charts.columns([(d.strftime(shape) if (len(points) - 1 - i) % every == 0 else "", tp(words, day=d.isoformat(), n=n), n)
                               for i, (d, n) in enumerate(points)], tp("sum.c_weeks" if step == 7 else "sum.c_days"))
        order = [g for g in status.GRADE_COLOURS if self.grades.get(g)]
        grades = charts.segments([(g, self.grades[g], self.grades[g]) for g in order], tp("sum.c_grades"), colours=[status.GRADE_COLOURS[g] for g in order])
        # The average as the site and the API round it (site.accuracy).
        return {"n": self.n, "records": self.records, "accuracy": f"{site.accuracy(self.judged / self.n):.1f}" if self.n else "", "people": len(self.people),
                "days": days, "weekly": step == 7, "grades": grades}


def plays_found(con, wanted, limit=-1, offset=0):
    """The plays asked for, newest first, one at a time: the whole history is searched, not held in memory. With a limit,
    that many from offset (for a page with no word to search for)."""
    where, args = plays_where(wanted)
    names = song_pages.chart_names()
    word = wanted["q"].lower()
    rows = con.execute(f"""SELECT l.user_id, m.nickname, l.pattern_id, l.score, l.grade, l.judgement, l.is_record, l.played_at
                             FROM PlayLog l JOIN ({core.PLAYER_ROWS}) m ON m.guid = l.user_id
                            {where}
                            ORDER BY l.played_at DESC, l.id DESC LIMIT ? OFFSET ?""", [core.CHECK_UDID] + args + [limit, offset])
    for r in rows:
        who = (r["nickname"] or "").strip() or tp("player.fallback", id=r["user_id"])
        song, chart = names.get(r["pattern_id"], ("", ""))
        if word and word not in f"{who} {song} {chart}".lower():
            continue
        yield {"id": r["user_id"], "who": who, "song": song, "chart": chart, "score": r["score"], "grade": r["grade"],
               "judgement": r["judgement"], "new": r["is_record"], "when": r["played_at"]}


def plays_csv(found, name="opendmtq-plays.csv"):
    """The plays asked for as a file, all of them and not one page, in the page's order, for a spreadsheet."""
    out = io.StringIO()
    # The mark that tells a spreadsheet on Windows this is UTF-8, as in the players' file.
    out.write("\ufefftime,player_id,player,song,chart,score,grade,accuracy,new_record\n")
    for p in found:
        at = datetime.datetime.fromtimestamp(p["when"]).strftime("%Y-%m-%d %H:%M:%S")
        # The game keeps accuracy in tenths of a percent. What the phone sent is text like any other.
        out.write(f'{at},{p["id"]},{players.csv_text(p["who"])},{players.csv_text(p["song"])},{players.csv_text(p["chart"])},{p["score"]},{players.csv_text(p["grade"])},'
                  f'{(p["judgement"] or 0) / 10:.1f},{1 if p["new"] else 0}\n')
    r = app.response_class(out.getvalue(), mimetype="text/csv; charset=utf-8")
    r.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return r


def plays_page_number(text):
    """The page of plays an address asks for: 1 and up, 1 for anything else."""
    try:
        return max(1, int(text or "1"))
    except ValueError:
        return 1


def plays_file(con, wanted, strict=False):
    """Every play the filter leaves as a file (plays_csv), named for what it holds: the player and the days it was
    narrowed to. Someone without plays (an old address) counts as no player on the page. strict (the API): that player
    stays asked for, and the file holds their plays, which are none."""
    people = plays_players(con)
    if not strict and wanted["player"] not in {guid for guid, _ in people}:
        wanted["player"] = None
    parts = ["opendmtq-plays"] + ([f"player{wanted['player']}"] if wanted["player"] is not None else []) \
        + [d.date().isoformat() for d in (wanted["from"], wanted["to"]) if d]
    return plays_csv(plays_found(con, wanted), "-".join(parts) + ".csv")


def plays_found_page(wanted, page, strict=False):
    """One page of the plays the filter leaves, with what all of them add up to: {plays (this page's, each with at, its
    time in words), people (who has plays), total, last_page, broken (the database could not be read), summed (a
    PlaysSum)}. Someone without plays (an old address) counts as no player on the page, which then lists every play.
    strict (the API): that player stays asked for, and their plays are found, which are none."""
    rows, people = [], []
    total = 0
    broken = False
    summed = PlaysSum()
    try:
        with db() as con:
            people = plays_players(con)
            # Someone without plays (an old address): on the page the whole list, with no name picked in the form; a program
            # that asked for that player (strict) gets what they played.
            if not strict and wanted["player"] not in {guid for guid, _ in people}:
                wanted["player"] = None
            first = (page - 1) * PLAYS_PAGE
            if wanted["q"]:
                # A word: every play is looked at here, each kept only when it is on the page.
                for play in plays_found(con, wanted):
                    if first <= total < first + PLAYS_PAGE:
                        rows.append({**play, "at": datetime.datetime.fromtimestamp(play["when"]).strftime("%Y-%m-%d %H:%M")})
                    total += 1
                    summed.add(play)
            else:
                # No word: the database counts them and gives this page alone, however long the history.
                total = plays_total(con, wanted)
                if total:
                    summed.counted(con, wanted)
                rows = [{**play, "at": datetime.datetime.fromtimestamp(play["when"]).strftime("%Y-%m-%d %H:%M")}
                        for play in plays_found(con, wanted, PLAYS_PAGE, first)]
    except sqlite3.Error:
        broken = True
    return {"plays": rows, "people": people, "total": total, "last_page": max(1, -(-total // PLAYS_PAGE)), "broken": broken, "summed": summed}


def plays_tab():
    """Every play the server has noted, newest first, narrowed by a word, a player and days, a page at a time."""
    wanted = plays_filter()
    page = plays_page_number(request.args.get("page", "1"))
    if request.args.get("csv"):
        # The file; a database that cannot be read gives the tab, which says so.
        try:
            with db() as con:
                return plays_file(con, wanted)
        except sqlite3.Error:
            pass
    found = plays_found_page(wanted, page)
    rows, people, total, broken, summed = found["plays"], found["people"], found["total"], found["broken"], found["summed"]
    shown = plays_shown(wanted)
    last_page = found["last_page"]
    # An old address: the last page there is, not an empty one that says there are no plays.
    if page > last_page:
        return redirect(url_for("logs_page", tab="plays", page=last_page, **shown))
    whose = next((name for guid, name in people if guid == shown["player"]), "")
    return render_template("logs.html", tab="plays", plays=rows, people=people, shown=shown, filtered=any(v is not None for v in shown.values()),
                           broken=broken, total=total, page=page, last_page=last_page, whose=whose,
                           summary=summed.view(wanted) if summed.n and not broken else None)


@app.route(BASE + "/logs/download")
def logs_download():
    """All of the log that is kept, as one file, oldest first."""
    path = os.path.join(core.LOGS, "access.log")
    files = sorted((p for p in (path + ".2", path + ".1", path) if os.path.isfile(p)), key=os.path.getmtime)

    def stream():
        for name in files:
            # One that cannot be read (just rotated away, or its rights changed) is left out, and the rest still comes.
            try:
                with open(name, "rb") as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk:
                            break
                        yield chunk
            except OSError:
                continue
    r = app.response_class(stream(), mimetype="text/plain; charset=utf-8")
    r.headers["Content-Disposition"] = 'attachment; filename="opendmtq-access.log"'
    return r
