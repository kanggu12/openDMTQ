"""The status page: what needs a look, the numbers and charts, and the machine's own load and memory."""

import collections
import json
import os
import shutil
import sqlite3
import threading
import time

from flask import render_template, url_for

from .. import songs, windows_client
from . import apps, auth, backups, charts, core, insights, recordings, song_pages
from .core import ago, app, BASE, db, human, t, tp


def recent_plays(con, limit=6):
    """The newest plays, for the dashboard: who, which song and chart, score, grade, whether it was played with the keyboard
    (keyboard) and when."""
    names = song_pages.chart_names()
    try:
        # Every column of the play: the keyboard's mark is one of them where the game server has added it.
        rows = con.execute(f"""SELECT l.*, m.nickname
                                FROM PlayLog l JOIN ({core.PLAYER_ROWS}) m ON m.guid = l.user_id
                               ORDER BY l.played_at DESC, l.id DESC LIMIT ?""", (core.CHECK_UDID, limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    # The moment as well as how long ago: the API gives the time.
    return [{"id": r["user_id"], "who": (r["nickname"] or "").strip() or tp("player.fallback", id=r["user_id"]),
             "song": names.get(r["pattern_id"], ("", ""))[0], "chart": names.get(r["pattern_id"], ("", ""))[1],
             "score": r["score"], "grade": r["grade"], "new": r["is_record"], "keyboard": core.by_keys(r),
             "ago": ago(r["played_at"]), "at": r["played_at"]} for r in rows]


def attention(health, counts, saved, backup_age, on, build, failed, usage):
    """What the owner may want to look at, in plain words, each with the way to it: (severity, text, link, link's words)."""
    out = []
    # A server not set up yet: the setup first (admin/setup.py). Its steps cover the files, the accounts and the app, so
    # the lines below about those wait until it is done.
    from .setup import STEPS, step_words, steps_done
    steps = steps_done()
    setting_up = not all(steps.values())
    if setting_up:
        # The step the setup opens at: the first not done.
        step = next(s for s in STEPS if not steps[s])
        out.append(("warn", t("alert.setup", step=step_words()[step]), url_for("setup_page"), t("setup.continue")))
    # Every account is disabled: nobody can get in. (With no account at all the setup is not done, and its line above
    # leads to its players' step.)
    total, usable = auth.accounts_count()
    if total and not usable:
        out.append(("warn", t("alert.accounts_off"), url_for("accounts_page"), t("nav.accounts")))
    # (A server that is down says so on every page: base.html.)
    # Without a client the builder fails at every start: the setup's line above says what is missing.
    if failed and steps["files"]:
        out.append(("bad", t("alert.build_failed"), url_for("app_page"), t("nav.app")))
    elif not build and not setting_up:
        out.append(("warn", t("alert.no_app"), url_for("app_page"), t("nav.app")))
    elif (health or {}).get("apk_matches_host") is False:
        out.append(("warn", t("alert.app_other"), url_for("app_page"), t("nav.app")))
    if usage.free < 5 * 1024 ** 3 or usage.free / usage.total < 0.05:
        out.append(("bad", t("alert.disk", free=human(usage.free)), url_for("recordings_page"), t("nav.recordings")))
    if backups._auto_failure:
        out.append(("bad", t("alert.auto_failed", detail=backups._auto_failure), url_for("backups_page"), t("nav.backups")))
    if not saved:
        # Nothing worth a backup before the setup is done.
        if not setting_up:
            out.append(("warn", t("alert.no_backup"), "backup-now", t("bak.now")))
    elif backup_age > 7 * 86400:
        out.append(("warn", t("alert.old_backup", ago=ago(time.time() - backup_age)), url_for("backups_page"), t("nav.backups")))
    if on:
        out.append(("warn", t("alert.maintenance"), url_for("maintenance_page"), t("nav.maintenance")))
    return out

# How much each kind of thing takes on the disk changes slowly, and counting it means walking folders (a folder's bytes:
# insights.folder_size).
_disk_cache = {}


# Where the site's certificate authority is kept for the pages (compose mounts data/https/public there): ours, and small.
HTTPS = os.environ.get("OPENDMTQ_HTTPS") or "/srv/https"
# OpenDMTQ's own parts of the data disk, in the order the status page draws them, each with its words: the game's files
# brought in, the recordings, the apps for players with what the builder keeps to make them, the backups, the database,
# the songs added here, and the rest of what it keeps (logs, settings, the site's copies of the jackets, a broadcast's
# pieces on their way, the certificate).
OWN_PARTS = (("game", "disk.game"), ("recordings", "disk.rec"), ("builds", "disk.app"), ("backups", "disk.bak"),
             ("db", "disk.db"), ("songs", "disk.song"), ("rest", "disk.rest"))


def disk_counts():
    """The slow figures of the data disk: the bytes of everything OpenDMTQ keeps on it, by its parts (OWN_PARTS: game,
    recordings, builds, backups, db, songs and rest), each folder walked as it is (insights.folder_size: on this disk
    alone, a file linked twice once), and how many recordings there are (recording_count). Counted at most every minute,
    and again after a backup is made or a recording deleted (they empty _disk_cache)."""
    # A copy, taken at once: another request may empty the cache while this one reads it.
    seen = dict(_disk_cache)
    if time.time() - seen.get("at", 0) <= 60:
        return seen
    state = os.path.dirname(core.DB)
    # The disk the database is on: the status page's disk. A folder on another one (a Kubernetes volume of its own) is
    # no part of it.
    try:
        disk = os.stat(state).st_dev
    except OSError:
        disk = None
    linked = set()
    size = lambda path, skip=(): insights.folder_size(path, device=disk, seen=linked, skip=skip)
    db_files = [core.DB + end for end in ("", "-wal", "-shm")]
    rec, base, added = recordings.rec_root(), os.path.join(core.APK, "base"), os.path.join(songs.CUSTOM, "songs")
    # The recordings themselves: a folder per player, named by their number (recordings.folder_number). The owner's limits
    # (limits.json) and anything else in that folder are no recording: they go with the rest, as the Broadcasts page counts.
    try:
        players = [os.path.join(rec, name) for name in os.listdir(rec) if recordings.folder_number(name) is not None]
    except OSError:
        players = []
    fresh = {"at": time.time(),
             # The imported client data and song data, and the game's client the app is built from.
             "game": size(songs.CONTENT) + size(base),
             "recordings": sum(size(folder) for folder in players),
             # data/apk but the client: the apps for players, the installer for Windows, the runtime for newer phones,
             # the signing key.
             "builds": size(core.APK, skip=[base]),
             "backups": size(core.BACKUPS),
             "db": sum(size(f) for f in db_files),
             "songs": size(added),
             # The state folder's and the custom folder's rest (the recordings' folder but the recordings), and the
             # certificate.
             "rest": size(state, skip=players + db_files) + size(songs.CUSTOM, skip=[added]) + size(HTTPS),
             # How many recordings: reading each one is the slow part, done here with the rest.
             "recording_count": recordings.rec_totals()[0]}
    _disk_cache.update(fresh)
    return fresh


def disk_use(usage):
    """What takes the data disk, in bytes: OpenDMTQ's parts (OWN_PARTS), other (what is not ours, still part of the
    whole) and free (disk_counts(), with the disk's own figures)."""
    counted = disk_counts()
    use = {name: counted[name] for name, _ in OWN_PARTS}
    # The rest of what the disk holds is not ours, and still part of the whole: without it the free part reads far too big.
    return dict(use, other=max(0, usage.used - sum(use.values())), free=usage.free)


def disk_parts(usage):
    """What takes the data disk: [(name, bytes, shown)], for the status page (disk_use, in words): OpenDMTQ's parts, then
    what is not ours and what is free."""
    use = disk_use(usage)
    known = list((key, name) for name, key in OWN_PARTS) + [("disk.other", "other"), ("disk.free", "free")]
    return [(t(key), use[name], human(use[name])) for key, name in known]

# The machine the server runs on, for the status page: its processors, memory, swap, load and how long it has been up.
# Read from /proc, which inside a container describes the machine itself (WSL's, or a Kubernetes node). A thread looks
# every MACHINE_EVERY seconds; every five minutes it keeps one point: the processors' average and peak, the memory in use,
# and how the game server answered. A day of points, also in a small file next to the database so that the graphs outlive
# a restart; the file never holds more than that day.
MACHINE_EVERY = 10
MACHINE_POINT = 300
MACHINE_KEEP = 288
_machine = {"now": {}, "points": collections.deque(maxlen=MACHINE_KEEP), "since": time.time()}
_machine_lock = threading.Lock()


def machine_file():
    return os.path.join(os.path.dirname(core.DB), "admin-machine.json")


def read_cpu():
    """(all, idle, waiting for the disk) since the machine started, in the kernel's ticks, from /proc/stat's first line."""
    with open("/proc/stat", encoding="ascii") as f:
        values = [int(v) for v in f.readline().split()[1:9]]
    return sum(values), values[3] + values[4], values[4]


def read_memory():
    """MemTotal, MemAvailable, SwapTotal and SwapFree in bytes, from /proc/meminfo."""
    out = {}
    with open("/proc/meminfo", encoding="ascii") as f:
        for line in f:
            name, _, rest = line.partition(":")
            if name in ("MemTotal", "MemAvailable", "MemFree", "SwapTotal", "SwapFree"):
                out[name] = int(rest.split()[0]) * 1024
    out.setdefault("MemAvailable", out.get("MemFree", 0))
    return out


def game_state():
    """How the game server answered just now: ok, warn (maintenance on) or bad (no answer, or an unwell one)."""
    health = core.server_health(fresh=True)
    if not health or not health.get("ok"):
        return "bad"
    return "warn" if songs.maintenance()[0] else "ok"


def _machine_loop():
    """The thread: the processors every MACHINE_EVERY seconds, a point every MACHINE_POINT."""
    try:
        with open(machine_file(), encoding="utf-8") as f:
            kept = json.load(f).get("points", [])
        with _machine_lock:
            _machine["points"].extend(p for p in kept if isinstance(p, dict) and time.time() - p.get("at", 0) < MACHINE_KEEP * MACHINE_POINT)
            if _machine["points"]:
                _machine["since"] = _machine["points"][0]["at"]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    last, busy, waits, started = None, [], [], time.time()
    while True:
        try:
            now = read_cpu()
            if last and now[0] > last[0]:
                total = now[0] - last[0]
                busy.append(100 * (total - (now[1] - last[1])) / total)
                waits.append(100 * (now[2] - last[2]) / total)
                with _machine_lock:
                    _machine["now"].update(cpu=busy[-1], wait=waits[-1])
            last = now
        except (OSError, ValueError, IndexError):
            last = None
        if time.time() - started >= MACHINE_POINT and busy:
            try:
                memory = read_memory()
                used = 100 * (memory["MemTotal"] - memory["MemAvailable"]) / memory["MemTotal"] if memory.get("MemTotal") else None
            except (OSError, ValueError):
                used = None
            point = {"at": int(time.time()), "cpu": round(sum(busy) / len(busy), 1), "peak": round(max(busy), 1),
                     "wait": round(sum(waits) / len(waits), 1), "mem": None if used is None else round(used, 1), "game": game_state()}
            with _machine_lock:
                _machine["points"].append(point)
                kept = list(_machine["points"])
            # The day so far, whole or not at all: a restart reads the old file or the new one.
            try:
                with open(machine_file() + ".tmp", "w", encoding="utf-8") as f:
                    json.dump({"points": kept}, f)
                os.replace(machine_file() + ".tmp", machine_file())
            except OSError:
                pass
            busy, waits, started = [], [], time.time()
        time.sleep(MACHINE_EVERY)


def duration_words(seconds):
    """How long, in the largest two units: 3 d 4 h, 5 h 12 min, 9 min."""
    seconds = int(seconds)
    d, h, m = seconds // 86400, seconds // 3600 % 24, seconds // 60 % 60
    if d:
        return tp("dur.dh", d=d, h=h)
    return tp("dur.hm", h=h, m=m) if h else tp("dur.m", m=m)


def machine_view(usage):
    """The status page's resources: the figures now as rows, and the last day as two charts and the game server's strip."""
    with _machine_lock:
        now = dict(_machine["now"])
        points = list(_machine["points"])
        since = _machine["since"]
    view = {"cores": os.cpu_count() or 1, "rows": []}
    try:
        memory = read_memory()
    except (OSError, ValueError):
        memory = {}
    try:
        with open("/proc/loadavg", encoding="ascii") as f:
            load = f.read().split()[:3]
    except OSError:
        load = None
    try:
        with open("/proc/uptime", encoding="ascii") as f:
            view["up"] = duration_words(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError):
        view["up"] = ""
    # One row each: its name, how full (0 to 1, or None), and the figure in words.
    cpu = now.get("cpu")
    view["rows"].append(("CPU", None if cpu is None else cpu / 100, tp("m.measuring") if cpu is None else f"{cpu:.0f}%"))
    if memory.get("MemTotal"):
        used = memory["MemTotal"] - memory["MemAvailable"]
        view["rows"].append((tp("m.mem"), used / memory["MemTotal"], tp("m.of", used=human(used), total=human(memory["MemTotal"]))))
    if memory.get("SwapTotal"):
        used = memory["SwapTotal"] - memory.get("SwapFree", 0)
        view["rows"].append((tp("m.swap"), used / memory["SwapTotal"], tp("m.of", used=human(used), total=human(memory["SwapTotal"]))))
    if usage.total:
        view["rows"].append((tp("m.disk"), usage.used / usage.total, tp("m.of", used=human(usage.used), total=human(usage.total))))
    if load:
        view["rows"].append((tp("m.load"), None, tp("m.load_val", a=load[0], b=load[1], c=load[2])))
    view["meters"] = [(name, charts.meter(share, f"{name}: {words}") if share is not None or name == "CPU" else "", words) for name, share, words in view["rows"]]
    # The last day in five-minute slots ending now, each with the point that fell in it, if any.
    end = time.time()
    slots = [None] * MACHINE_KEEP
    for p in points:
        back = int((end - p["at"]) // MACHINE_POINT)
        if 0 <= back < MACHINE_KEEP:
            slots[MACHINE_KEEP - 1 - back] = p
    def when(i):
        return time.strftime("%H:%M", time.localtime(end - (MACHINE_KEEP - 1 - i) * MACHINE_POINT))
    # An hour on the axis every six.
    def axis(i):
        moment = time.localtime(end - (MACHINE_KEEP - 1 - i) * MACHINE_POINT)
        return time.strftime("%H:00", moment) if moment.tm_hour % 6 == 0 and moment.tm_min < 5 else ""
    # Recording for less than a day: since when. In the first hour the charts are all but empty, so they say it themselves,
    # in the middle of the plot, and the line under the card waits until there is a line to see.
    view["collecting"] = time.strftime("%H:%M", time.localtime(since)) if len(points) < MACHINE_KEEP and end - since < MACHINE_KEEP * MACHINE_POINT else ""
    view["early"] = bool(view["collecting"]) and sum(1 for p in slots if p) < 12
    note = tp("m.collecting", time=view["collecting"]) if view["early"] else ""
    view["cpu_chart"] = charts.area([(axis(i), tp("m.tip_cpu", time=when(i), avg=p["cpu"], peak=p["peak"]) if p else "", p["cpu"] if p else None)
                                     for i, p in enumerate(slots)], tp("m.c_cpu"), note=note)
    view["mem_chart"] = charts.area([(axis(i), tp("m.tip_mem", time=when(i), p=p["mem"]) if p and p.get("mem") is not None else "", p.get("mem") if p else None)
                                     for i, p in enumerate(slots)], tp("m.c_mem"), note=note)
    # The game server in half hours: the worst it was in each, or nothing known.
    worst = {"bad": 3, "warn": 2, "ok": 1}
    words = {"ok": "m.k_ok", "warn": "m.k_warn", "bad": "m.k_bad", "none": "m.k_none"}
    cells, answered, asked = [], 0, 0
    for half in range(48):
        inside = [p for p in slots[half * 6:half * 6 + 6] if p and p.get("game") in worst]
        state = max((p["game"] for p in inside), key=worst.get) if inside else "none"
        answered += sum(p["game"] != "bad" for p in inside)
        asked += len(inside)
        start = time.strftime("%H:%M", time.localtime(end - (48 - half) * 1800))
        cells.append((state, tp("m.tip_game", time=start, state=tp(words[state]))))
    view["game_strip"] = charts.strip(cells, tp("m.c_game"), (tp("m.ago24"), tp("m.now")),
                                      [(state, tp(words[state])) for state in ("ok", "warn", "bad", "none")])
    view["answered"] = round(100 * answered / asked, 1) if asked else None
    return view

def machine_figures(usage):
    """The machine's resources as the status page reads them, as numbers: processors, how long it has been up (seconds),
    the processors' use now and the share waiting for the disk (percent, None while measuring), memory and swap and the
    disk (bytes), the load (1, 5 and 15 minutes), and the last day's points (one every five minutes: average and peak
    processor use, waiting, memory in use, and how the game server answered: ok, warn or bad), since when they are kept."""
    with _machine_lock:
        now = dict(_machine["now"])
        points = [dict(p) for p in _machine["points"]]
        since = _machine["since"]
    try:
        memory = read_memory()
    except (OSError, ValueError):
        memory = {}
    try:
        with open("/proc/loadavg", encoding="ascii") as f:
            load = [float(v) for v in f.read().split()[:3]]
    except (OSError, ValueError):
        load = None
    try:
        with open("/proc/uptime", encoding="ascii") as f:
            up = int(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError):
        up = None
    total, avail = memory.get("MemTotal"), memory.get("MemAvailable", 0)
    swap = memory.get("SwapTotal")
    return {"cores": os.cpu_count() or 1, "uptime": up, "cpu": now.get("cpu"), "cpu_wait": now.get("wait"),
            "memory": {"total": total, "used": total - avail} if total else None,
            "swap": {"total": swap, "used": swap - memory.get("SwapFree", 0)} if swap else None,
            "disk": {"total": usage.total, "used": usage.used, "free": usage.free}, "load": load,
            "since": int(since), "points": points}


threading.Thread(target=_machine_loop, name="machine", daemon=True).start()

# Grades in the game's own colours; each block also has its letter, so colour is not all that tells them apart.
GRADE_COLOURS = {"S": "#78cf2e", "A": "#2fa8e0", "B": "#a783f2", "C": "#d9a11a", "D": "#e07a3c", "E": "#5c6773", "F": "#46505b"}


def counts_of(con):
    """The status page's numbers: players, records (best results), plays in the last 24 hours and 7 days, players who
    played in the last 7 days, players on air now."""
    counts = {}
    counts["players"] = con.execute(f"SELECT COUNT(*) FROM ({core.PLAYER_ROWS})", (core.CHECK_UDID,)).fetchone()[0]
    counts["records"] = con.execute("SELECT COUNT(*) FROM Play").fetchone()[0]
    try:
        counts["plays_today"] = con.execute(
            "SELECT COUNT(*) FROM PlayLog WHERE played_at > strftime('%s','now') - 86400").fetchone()[0]
        counts["plays_week"] = con.execute(
            "SELECT COUNT(*) FROM PlayLog WHERE played_at > strftime('%s','now') - 604800").fetchone()[0]
        counts["active_week"] = con.execute(
            "SELECT COUNT(DISTINCT user_id) FROM PlayLog WHERE played_at > strftime('%s','now') - 604800").fetchone()[0]
    except sqlite3.OperationalError:
        counts["plays_today"] = counts["plays_week"] = counts["active_week"] = 0
    # On air now, and whether broadcasts are on at all: nobody is on air while they are off.
    counts["broadcasts"] = recordings.live_settings()["on"]
    counts["live"] = sum(recordings.live_rows(con).values()) if counts["broadcasts"] else 0
    return counts


def activity(con):
    """What the status page's charts draw, as figures: plays on each of the last 30 days, by weekday (Monday first) and
    hour over the last 4 weeks, who played most and the most played songs over 30 days, and best records by grade."""
    return {"days": insights.plays_by_day(con), "hours": insights.plays_by_hour(con),
            "players": insights.top_players(con, core.PLAYER_ROWS, core.CHECK_UDID),
            "songs": insights.top_songs(con, song_pages.chart_names()), "grades": insights.grade_counts(con)}


def facts():
    """What the status page says, as data: the game server's health (asked now), the numbers (None when the database
    cannot be read), the newest plays, the charts' figures, the disk, the backups made here, the notice, the app on offer,
    why its last build failed and how many recordings there are."""
    health = core.server_health(fresh=True)
    try:
        with db() as con:
            counts = counts_of(con)
            recent = recent_plays(con)
            figures = activity(con)
    except sqlite3.Error:
        counts, recent, figures = None, [], None
    usage = shutil.disk_usage(os.path.dirname(core.DB))
    # When the newest was made; older than a week reads as a warning. An uploaded archive backs up nothing of
    # this server's present state, so it does not count.
    saved = [b for b in backups.backup_files() if "-uploaded" not in b[0]]
    backup_age = time.time() - saved[0][1] if saved else None
    on, _ = songs.maintenance()
    build = next((b for b in apps.builds() if b["current"]), None)
    # The players' page asks them to tell the owner when the app could not be built: here is why. A
    # failed rebuild is shown too, above the earlier app that phones still get.
    failed = apps.build_error()
    return {"health": health, "counts": counts, "recent": recent, "figures": figures, "usage": usage, "saved": saved,
            "backup_age": backup_age, "maintenance": on, "build": build, "failed": failed,
            # Counted with the disk's figures (disk_counts): every recording is read at most once a minute for both.
            "recordings": disk_counts()["recording_count"]}


@app.route(BASE + "/")
def dashboard():
    f = facts()
    health, counts, recent, usage, saved, backup_age, on, build, failed = (
        f["health"], f["counts"], f["recent"], f["usage"], f["saved"], f["backup_age"], f["maintenance"], f["build"], f["failed"])
    charts_view = {}
    if f["figures"]:
        days, grades = f["figures"]["days"], f["figures"]["grades"]
        day_names = [t(d) for d in ("day.mon", "day.tue", "day.wed", "day.thu", "day.fri", "day.sat", "day.sun")]
        charts_view = {
            "days": charts.columns([(d.strftime("%m-%d") if i % 5 == 4 else "", tp("chart.day", day=d.isoformat(), n=n), n) for i, (d, n) in enumerate(days)], tp("dash.c_days")),
            "days_total": sum(n for _, n in days),
            "spark": charts.spark([n for _, n in days[-7:]], tp("dash.plays_week", n=counts["plays_week"])),
            "heat": charts.heatmap(f["figures"]["hours"], day_names, lambda day, hour, n: tp("chart.hour", day=day, hour=hour, n=n), tp("dash.c_when"), (tp("chart.fewer"), tp("chart.more"))),
            "who": charts.ranked([((name or tp("player.fallback", id=guid)), n, n, f"{core.public_url()}/opendmtq/player.php?id={guid}") for guid, name, n in f["figures"]["players"]], tp("dash.c_who")),
            "songs": charts.ranked([(title, n, n, None) for title, n in f["figures"]["songs"]], tp("dash.c_songs")),
            "grades": charts.segments([(g, n, n) for g, n in grades], tp("dash.c_grades"), colours=[GRADE_COLOURS[g] for g, _ in grades]),
        }
    disk = disk_parts(usage)
    # The whole disk with OpenDMTQ's part as one, then that part alone at its own scale: on a big disk its pieces would be
    # slivers of a pixel.
    own = disk[:len(OWN_PARTS)]
    own_total = sum(p[1] for p in own)
    disk_chart = charts.segments([(tp("disk.ours"), own_total, human(own_total))] + disk[len(OWN_PARTS):], tp("dash.c_disk"),
                                 colours=[charts.OURS, charts.OTHER, charts.QUIET])
    # Each part a step of the plain light, the rest the last step: no hue, as the other meters (colour marks a state).
    disk_own = charts.segments(own, tp("dash.c_disk_own", size=human(own_total)),
                               colours=list(charts.LIGHTS[:len(OWN_PARTS)])) if own_total else ""
    # The button is for the owner, from where this page was opened; the message is for a friend, who needs the address all
    # phones use (localhost or a link without a host is no use to them).
    invite_url = f"{core.public_url()}/opendmtq/download.php"
    return render_template("dashboard.html", health=health, counts=counts, usage=usage,
                           last_backup=saved[0][0] if saved else None, build=build, build_failed=failed,
                           app_other_host=(health or {}).get("apk_matches_host") is False,
                           maintenance=on, recent=recent, recordings=f["recordings"],
                           backup_ago=ago(time.time() - backup_age) if saved else None,
                           backup_old=saved and backup_age > 7 * 86400, chart=charts_view, disk_chart=disk_chart, disk_own=disk_own,
                           disk_own_total=human(own_total) if own_total else "", machine=machine_view(usage),
                           attention=attention(health, counts, saved, backup_age, on, build, failed, usage),
                           invite_url=invite_url,
                           site_url=windows_client.site_url(core.site_scheme(health) == "https", core.PUBLIC_HOST),
                           qr=os.path.isfile(os.path.join(core.APK, "out", "download-qr.svg")) and bool(build) and (health or {}).get("apk_matches_host") is not False,
                           version=(os.environ.get("OPENDMTQ_VERSION") or ""))
