"""What the admin's status and log pages show: plays over time, who plays when, what the server's log says. Read-only."""

import collections
import datetime
import json
import os
import re
import sqlite3
import threading
import time

# The same one row per player as the rest of the admin pages (PLAYER_ROWS): passed in, to keep one copy of it.

DAY = 86400


def _local_day(t):
    return datetime.datetime.fromtimestamp(t).date()


def plays_by_day(con, days=30, now=None):
    """Plays on each of the last days, oldest first, with the days nobody played: [(date, count), ...]."""
    now = now or time.time()
    since = now - days * DAY
    counts = collections.Counter()
    try:
        # Counted by the database, on this server's clock as _local_day counts: a month can be many thousands of plays.
        for day, n in con.execute("SELECT date(played_at, 'unixepoch', 'localtime'), COUNT(*) FROM PlayLog WHERE played_at > ? GROUP BY 1", (since,)):
            counts[datetime.date.fromisoformat(day)] = n
    except sqlite3.OperationalError:
        pass
    today = _local_day(now)
    return [(today - datetime.timedelta(days=n), counts[today - datetime.timedelta(days=n)]) for n in range(days - 1, -1, -1)]


def plays_by_hour(con, days=28, now=None):
    """Plays by day of the week (Monday first) and hour, over the last weeks: seven lists of 24."""
    now = now or time.time()
    grid = [[0] * 24 for _ in range(7)]
    try:
        for weekday, hour, n in con.execute(
                """SELECT strftime('%w', played_at, 'unixepoch', 'localtime'), strftime('%H', played_at, 'unixepoch', 'localtime'), COUNT(*)
                     FROM PlayLog WHERE played_at > ? GROUP BY 1, 2""", (now - days * DAY,)):
            # The database counts the week from Sunday; the grid starts on Monday.
            grid[(int(weekday) + 6) % 7][int(hour)] = n
    except sqlite3.OperationalError:
        pass
    return grid


def grade_counts(con):
    """Best records at each grade, S first; only the grades there are."""
    order = ["S", "A", "B", "C", "D", "E", "F"]
    found = dict(con.execute("SELECT grade, COUNT(*) FROM Play WHERE grade IS NOT NULL GROUP BY grade").fetchall())
    return [(g, found[g]) for g in order if found.get(g)]


def top_players(con, rows_sql, check, days=30, limit=6, now=None):
    """Who played the most over the last days: [(guid, name, plays), ...]."""
    now = now or time.time()
    try:
        return [(r[0], (r[1] or "").strip(), r[2]) for r in con.execute(
            f"""SELECT m.guid, m.nickname, COUNT(*) AS n FROM PlayLog l JOIN ({rows_sql}) m ON m.guid = l.user_id
                 WHERE l.played_at > ? GROUP BY m.guid ORDER BY n DESC, m.guid LIMIT ?""", (check, now - days * DAY, limit))]
    except sqlite3.OperationalError:
        return []


def top_songs(con, chart_names, days=30, limit=6, now=None):
    """Which songs were played the most over the last days: [(title, plays), ...]. Charts of one song count together."""
    now = now or time.time()
    counts = collections.Counter()
    try:
        for pattern, n in con.execute("SELECT pattern_id, COUNT(*) FROM PlayLog WHERE played_at > ? GROUP BY pattern_id", (now - days * DAY,)):
            title = chart_names.get(pattern, ("", ""))[0]
            if title:
                counts[title] += n
    except sqlite3.OperationalError:
        pass
    return counts.most_common(limit)


def player_activity(con, days=14, now=None):
    """Per player: when they last played, plays in the last 30 days, and one count per day of the last days, oldest first."""
    now = now or time.time()
    today = _local_day(now)
    out = collections.defaultdict(lambda: {"last": None, "recent": 0, "days": [0] * days})
    try:
        for guid, n in con.execute("SELECT user_id, COUNT(*) FROM PlayLog WHERE played_at > ? GROUP BY user_id", (now - 30 * DAY,)):
            out[guid]["recent"] = n
        # By the day on this server's clock, counted by the database. One day more than asked for: a day reaches back
        # further than that many times 24 hours from now, up to a whole day.
        for guid, day, n in con.execute(
                "SELECT user_id, date(played_at, 'unixepoch', 'localtime'), COUNT(*) FROM PlayLog WHERE played_at > ? GROUP BY 1, 2",
                (now - (days + 1) * DAY,)):
            back = (today - datetime.date.fromisoformat(day)).days
            # (A play dated after today: a clock that was wrong then. It counts for the plays, not for a day here.)
            if 0 <= back < days:
                out[guid]["days"][days - 1 - back] = n
        for guid, at in con.execute("SELECT user_id, MAX(played_at) FROM PlayLog GROUP BY user_id"):
            out[guid]["last"] = at
    except sqlite3.OperationalError:
        pass
    return out


def folder_size(path):
    """All the bytes under a folder; 0 if it is not there."""
    total = 0
    for base, _, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


# ------------------------------------------------------------------------------------------- the request log

# Apache's combined format, as server/apache/opendmtq.conf writes it.
LINE = re.compile(r'^(?P<ip>\S+) \S+ \S+ \[(?P<when>[^\]]+)\] "(?P<req>[^"]*)" (?P<status>\d{3}) (?P<size>\S+)(?: "(?P<ref>[^"]*)" "(?P<ua>[^"]*)")?')
# How much of each of the two newest log files is read for a page: its tail. A busy day's log is larger (broadcast segments),
# and then the page says from when it counts (LogRows.cut).
READ_BYTES = 3_000_000


class LogRows(list):
    """The requests read from the log, oldest first; cut says that older ones were left out for the size."""
    cut = False


def kind_of(path):
    """What a request was for, in the words of the log page's filter."""
    if path.startswith(("/DMQ", "/api", "/accounts", "/members", "/product", "/apps", "/djmaxQ", "/score", "/static", "/www")):
        return "game"
    if path.startswith(("/patch", "/viewImg", "/thumbs")):
        return "files"
    if path == "/apk" or path.startswith("/apk?") or path == "/ca.crt":
        return "app"
    if path.startswith("/live") or path.startswith("/opendmtq/live"):
        return "live"
    # The admin pages, at their address and at the old one that leads there.
    if path.startswith(("/opendmtq/admin", "/admin")):
        return "admin"
    if path == "/" or path.startswith("/opendmtq"):
        return "site"
    return "other"


def device_of(ua):
    """The caller's kind of device in a word or two, for a person reading the list."""
    if not ua or ua == "-":
        return "–"
    # ./opendmtq check, walking the game's path with its own name.
    if ua == "opendmtq":
        return "Server check"
    if "Dalvik" in ua or "UnityPlayer" in ua or "okhttp" in ua:
        return "Game app"
    if re.search(r"bot|crawl|spider|curl|wget|python|scan|zgrab|masscan|Go-http", ua, re.I):
        return "Script or bot"
    browser = "Samsung Internet" if "SamsungBrowser" in ua else "KakaoTalk" if "KAKAOTALK" in ua else "Edge" if "Edg/" in ua else \
        "Chrome" if "Chrome" in ua else "Firefox" if "Firefox" in ua else "Safari" if "Safari" in ua else "Browser"
    system = "Android" if "Android" in ua else "iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua else "Windows" if "Windows" in ua else \
        "Mac" if "Mac OS" in ua else "Linux" if "Linux" in ua else ""
    return f"{browser} ({system})" if system else browser


# What was read of each log file, kept between requests: the Logs page looks for new lines every few seconds, and a busy
# log is megabytes. Per file: its identity, its first bytes (a file written anew from the start is another file), how
# far it was read, the bytes of a line still being written, and the rows with the byte each began at.
_tails = {}
_tails_lock = threading.Lock()


def _blank_row(line):
    """A line in another format (an older log, a hand-edited one): shown as it is."""
    return {"ip": "", "at": 0, "time": "", "method": "", "path": line, "status": 0, "size": 0, "ref": "", "ua": "",
            "kind": "other", "device": "–", "line": line}


def _tail_rows(name):
    """One log file's newest READ_BYTES as [(byte offset, row)], oldest first, and whether its start was left out.
    Only what was written since the last call is read."""
    with open(name, "rb") as f:
        st = os.fstat(f.fileno())
        head = f.read(64)
        kept = _tails.get(name)
        if kept and kept["ino"] == st.st_ino and kept["head"] == head and kept["end"] <= st.st_size:
            # The same file, grown or as it was: the new bytes, after the unfinished line of last time.
            rows, frm, carry = list(kept["rows"]), kept["end"], kept["carry"]
            skip_first = False
        else:
            # Another file, or one written anew: its tail, whose first line may be cut.
            frm = max(0, st.st_size - READ_BYTES)
            rows, carry, skip_first = [], b"", frm > 0
        f.seek(frm)
        data = carry + f.read(max(0, st.st_size - frm))
    # Where data begins in the file: the carried bytes came just before frm.
    pos = frm - len(carry)
    # Whole lines only; the bytes after the last line break are carried to the next call.
    done = data.rfind(b"\n") + 1
    for raw in data[:done].splitlines(keepends=True):
        if skip_first:
            skip_first = False
        else:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            row = parse_line(line) or _blank_row(line)
            # Not the server's own health checks, and not what Apache writes for a connection that closed without
            # asking for anything (408 and no request line): neither is something anybody asked for.
            if not row["path"].startswith("/opendmtq/health.php") and row["path"] not in ("-", "- -"):
                rows.append((pos, row))
        pos += len(raw)
    # How far the file was read: the carried bytes come again with the next call's new ones, not from the file.
    end = frm + len(data) - len(carry)
    # The newest READ_BYTES of the file and no more, however long the page has been following it.
    first = max(0, end - READ_BYTES)
    if rows and rows[0][0] < first:
        rows = [r for r in rows if r[0] >= first]
    _tails[name] = {"ino": st.st_ino, "head": head, "end": end, "carry": data[done:], "rows": rows}
    return rows, first > 0


def read_log(folder):
    """The newest requests, oldest first, as dictionaries. rotatelogs -n 3 writes access.log, then .1, then .2, then
    access.log again, so the file being written can be any of them: the newest two by time, each one's tail."""
    path = os.path.join(folder, "access.log")
    files = [p for p in (path, path + ".1", path + ".2") if os.path.isfile(p)]
    rows = LogRows()
    rows.cut = len(files) > 2
    for name in sorted(files, key=os.path.getmtime)[-2:]:
        # One that cannot be read (just rotated away, or its rights changed) leaves the page working with the other.
        try:
            with _tails_lock:
                tail, cut = _tail_rows(name)
        except OSError:
            _tails.pop(name, None)
            continue
        rows.cut = rows.cut or cut
        rows.extend(row for _, row in tail)
    return rows


def parse_line(line):
    m = LINE.match(line)
    if not m:
        return None
    method, _, rest = m.group("req").partition(" ")
    path = rest.rsplit(" ", 1)[0] if rest else m.group("req")
    try:
        when = datetime.datetime.strptime(m.group("when"), "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        return None
    size = m.group("size")
    return {"ip": m.group("ip"), "at": when.timestamp(), "time": when.strftime("%m-%d %H:%M:%S"), "method": method, "path": path,
            "status": int(m.group("status")), "size": int(size) if size.isdigit() else 0, "ref": m.group("ref") or "",
            "ua": m.group("ua") or "", "kind": kind_of(path), "device": device_of(m.group("ua") or ""), "line": line}


def status_class(status):
    return f"{status // 100}xx"


def wanted(row, q="", status="", kind=""):
    """Does a request pass the page's filters? status: 2xx, 3xx, 4xx, 5xx, or err for anything that went wrong."""
    if status == "err" and row["status"] < 400:
        return False
    if status and status != "err" and status_class(row["status"]) != status:
        return False
    if kind and row["kind"] != kind:
        return False
    return not q or q.lower() in row["line"].lower()


def by_hour(rows, hours=24, now=None):
    """Requests per hour over the last hours, oldest first: [(hour start, fine, failed), ...]. Scripts probing the
    server for files it does not have are not its failures (they end in 404 by the hundred): only 5xx and the game's and
    the app's own 4xx count as failed."""
    now = now or time.time()
    start = int(now // 3600 - hours + 1) * 3600
    fine, failed = [0] * hours, [0] * hours
    for r in rows:
        slot = int((r["at"] - start) // 3600)
        if 0 <= slot < hours:
            if r["status"] >= 500 or (r["status"] >= 400 and r["kind"] in ("game", "files", "app", "live")):
                failed[slot] += 1
            else:
                fine[slot] += 1
    return [(start + i * 3600, fine[i], failed[i]) for i in range(hours)]


def top(rows, key, limit=6):
    return collections.Counter(r[key] for r in rows).most_common(limit)


# What a page brings along by itself: a chart of what people ask for would otherwise be a list of the site's fonts.
STATIC_FILE = re.compile(r"\.(css|js|svg|png|jpe?g|gif|ico|woff2?|ts|m3u8|map)$")


def top_pages(rows, limit=6):
    """What was asked for the most: pages and the game's requests, each once whatever its query."""
    paths = (r["path"].split("?", 1)[0] for r in rows)
    return collections.Counter(p for p in paths if p != "-" and not STATIC_FILE.search(p)).most_common(limit)


# ------------------------------------------------------------------------------------------- what was changed here

# Kept small and in two files: a few hundred kilobytes at most, however long the server runs.
AUDIT_MAX = 256 * 1024


def audit_note(folder, what, target="", named=True, who=""):
    """One line in the record of changes made in these pages. Never gets in the way of the change itself. named: the target
    is in words as they are at this moment (lines from before that hold a number, looked up when shown). who: the account
    that made it, empty for what nobody signed in did (a failed sign-in)."""
    path = os.path.join(folder, "changes.log")
    try:
        os.makedirs(folder, exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > AUDIT_MAX:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": int(time.time()), "what": what, "target": target, "named": named, "who": who}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def audit_read(folder, limit=200):
    """The latest changes, newest first."""
    out = []
    for name in ("changes.log.1", "changes.log"):
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
        except OSError:
            pass
    return out[::-1][:limit]
