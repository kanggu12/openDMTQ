"""Live broadcasts and the Recordings page: each player's switch, what is on air, the limits and the files."""

import datetime
import json
import os
import re
import secrets
import shutil
import sqlite3
import time

from flask import abort, flash, redirect, render_template, request, send_file, url_for

from . import core, players, status
from .core import Refused, app, BASE, changed, db, t

# The live view: the owner's switch per player, the phone's upload key, the notice waiting to be shown
# ("on" or "off") and whether the player is in a song. The server makes this table at start
# (server/game/bin/setup-db.php, the same statement); a database restored from before it needs it here too.
LIVE_TABLE = """CREATE TABLE IF NOT EXISTS LiveSwitch (guid INTEGER PRIMARY KEY, live INTEGER NOT NULL DEFAULT 0,
                   token TEXT, toast TEXT, changed_at INTEGER, playing INTEGER NOT NULL DEFAULT 0,
                   pattern_id INTEGER, play_at INTEGER)"""

# Recordings of live broadcasts, and the limits the server keeps them to (LIVE_REC_* in
# server/portal/live_lib.php, which closes them and enforces the limits; this file lists, hides and
# deletes them and sets the limits).
REC_LIMITS_DEFAULT = {"cap_gb": 20, "days": 30}

# Seconds since a stream's last upload under which it counts as live now (LIVE_LISTED in
# server/portal/live_lib.php).
LIVE_LISTED = 15

# What an hour of broadcast takes on the disk, about (rec.about says so): for how long the recordings' room lasts.
REC_PER_HOUR = 1024 ** 3


def live_folder(guid):
    """A player's stream folder, next to the database (guid is always an int)."""
    return os.path.join(os.path.dirname(core.DB), "live", str(int(guid)))


def live_streaming(guid):
    """True when the player's phone uploaded video in the last seconds and has not ended the stream
    (what the server writes in stream.json, as its portal reads it)."""
    try:
        with open(os.path.join(live_folder(guid), "stream.json"), encoding="utf-8") as f:
            stream = json.load(f)
        return not stream["ended"] and time.time() - stream["updated"] < LIVE_LISTED
    except (OSError, ValueError, KeyError, TypeError):
        return False


def live_set(con, guid, on):
    """Switch a player's live view. On: a new upload key, and a notice for the phone. Off: the key is
    gone (the phone's next upload is refused and it stops), and so is the video on disk at once."""
    con.execute(LIVE_TABLE)
    row = con.execute("SELECT live, toast FROM LiveSwitch WHERE guid = ?", (guid,)).fetchone()
    # Already so (a form sent twice): no new key, no second notice.
    if bool(row and row["live"]) == on:
        return
    # A notice the phone has not read yet is simply taken back when the switch is flipped back: the
    # player never learned of the change. Otherwise the phone is told.
    pending = row["toast"] if row else None
    toast = "" if pending in ("on", "off") else ("on" if on else "off")
    token = secrets.token_hex(16) if on else None
    con.execute("""INSERT INTO LiveSwitch (guid, live, token, toast, changed_at) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (guid) DO UPDATE SET live = excluded.live, token = excluded.token,
                       toast = excluded.toast, changed_at = excluded.changed_at""",
                (guid, int(on), token, toast, int(time.time())))
    if not on:
        # The live window goes; the recording stays, and the server's next sweep closes it.
        shutil.rmtree(live_folder(guid), ignore_errors=True)
        for rec in rec_all():
            if rec["guid"] == guid and rec["open"]:
                with open(os.path.join(rec["dir"], ".close-now"), "a", encoding="utf-8"):
                    pass


def rec_root():
    """The recordings' folder, next to the database (data/state/live-rec)."""
    return os.path.join(os.path.dirname(core.DB), "live-rec")


def rec_folder(guid, rid):
    """One recording's folder (both are always ints, so it cannot name another place)."""
    return os.path.join(rec_root(), str(int(guid)), str(int(rid)))


def rec_limits():
    """The owner's limits: total size in GB, age in days."""
    try:
        with open(os.path.join(rec_root(), "limits.json"), encoding="utf-8") as f:
            return {**REC_LIMITS_DEFAULT, **json.load(f)}
    except (OSError, ValueError, TypeError):
        return dict(REC_LIMITS_DEFAULT)


def rec_save_limits(cap_gb, days):
    """Saved so that the server reads the old limits or the new ones, never half of a file."""
    os.makedirs(rec_root(), exist_ok=True)
    path = os.path.join(rec_root(), "limits.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"cap_gb": cap_gb, "days": days}, f)
    os.replace(path + ".tmp", path)


def rec_over_limits(cap_gb, days):
    """The closed recordings these limits would delete, the same pick as the server's sweep (live_rec_enforce in
    server/portal/live_lib.php): too old, then the oldest first until the total fits."""
    now = time.time()
    gone, closed, total = [], [], 0
    for rec in rec_all():
        ended = rec.get("ended") or rec["started"]
        if rec["open"]:
            total += rec["size"] or 0
        elif now - ended > days * 86400:
            gone.append(rec)
        else:
            closed.append((ended, rec["id"], rec))
            total += rec["size"] or 0
    for _, _, rec in sorted(closed, key=lambda c: c[:2]):
        if total <= cap_gb * 1024 ** 3:
            break
        gone.append(rec)
        total -= rec["size"] or 0
    return gone


def rec_all():
    """Every recording, newest first. An open one has only its start in meta.json: its length and size
    come from its list of segments so far."""
    out = []
    root = rec_root()
    for guid in os.listdir(root) if os.path.isdir(root) else []:
        folder = os.path.join(root, guid)
        # Only the folders the server makes.
        if not guid.isdigit() or not os.path.isdir(folder):
            continue
        for rid in os.listdir(folder):
            rec = os.path.join(folder, rid)
            if not rid.isdigit() or not os.path.isdir(rec):
                continue
            try:
                with open(os.path.join(rec, "meta.json"), encoding="utf-8") as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                meta = {}
            item = {"started": int(rid), "duration_ms": 0, "size": 0, "songs": [], **meta,
                    "guid": int(guid), "id": int(rid), "dir": rec,
                    "open": os.path.exists(os.path.join(rec, ".open")),
                    "hidden": os.path.exists(os.path.join(rec, ".hidden"))}
            if item["open"]:
                try:
                    with open(os.path.join(rec, "segs.log"), encoding="utf-8") as f:
                        lines = [line.split() for line in f]
                    item["duration_ms"] = sum(int(x[1]) for x in lines if len(x) == 4)
                    item["size"] = sum(int(x[3]) for x in lines if len(x) == 4)
                except (OSError, ValueError):
                    pass
            out.append(item)
    out.sort(key=lambda r: r["id"], reverse=True)
    return out


def rec_remove(guid, rid):
    """Deletes a closed recording. A running one stays (its phone is still writing to it): False."""
    rec = rec_folder(guid, rid)
    if os.path.exists(os.path.join(rec, ".open")):
        return False
    shutil.rmtree(rec, ignore_errors=True)
    status._disk_cache.clear()
    # The player's folder goes with their last one (fails, as meant, while others remain).
    try:
        os.rmdir(os.path.dirname(rec))
    except OSError:
        pass
    return True


def rec_sweep_now():
    """Has the server run its sweep now, not within the minute: it closes recordings and keeps the limits
    (server/portal/live_lib.php). A server that is down does so when it is back."""
    try:
        os.remove(os.path.join(os.path.dirname(core.DB), "live", ".swept"))
    except OSError:
        pass
    core.server_health(fresh=True)


def rec_length(ms):
    """A recording's length as the portal shows it: 4:05, or 1:04:05."""
    sec = round((ms or 0) / 1000)
    return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"

app.jinja_env.filters["rec_length"] = rec_length

app.jinja_env.filters["rec_date"] = lambda t: datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")


def live_rows(con):
    """Who is switched on: {guid: streaming now}. A database without the table has nobody."""
    try:
        return {r[0]: live_streaming(r[0]) for r in con.execute("SELECT guid FROM LiveSwitch WHERE live = 1")}
    except sqlite3.OperationalError:
        return {}


@app.route(BASE + "/recordings", methods=["GET", "POST"])
def recordings_page():
    if request.method == "POST":
        return recordings_action()
    return recordings_view()


def recordings_view(pending=None):
    """The page; pending holds limits waiting for the owner's yes, because of what they would delete."""
    # The names as the players page has them; a player's recordings stay together, newest first.
    try:
        with db() as con:
            names = {r["guid"]: (r["nickname"] or "").strip() for r in con.execute(core.PLAYER_ROWS, (core.CHECK_UDID,))}
    except sqlite3.Error:
        names = {}
    recs = rec_all()
    groups = {}
    for rec in recs:
        groups.setdefault(rec["guid"], []).append(rec)
    limits = rec_limits()
    # The one to watch in the page: closed ones only, the open one has no playlist yet.
    watch = next((r for r in recs if f"{r['guid']}/{r['id']}" == request.args.get("watch") and not r["open"]), None)
    return render_template("recordings.html", groups=groups, names=names, limits=limits, watch=watch, pending=pending,
                           used=sum(r["size"] for r in recs), cap=limits["cap_gb"] * 1024 ** 3, per_hour=REC_PER_HOUR,
                           free=shutil.disk_usage(os.path.dirname(core.DB)).free)


def recordings_action():
    """The forms of the recordings page. Unknown or malformed names are ignored."""
    action = request.form.get("action", "")
    if action == "limits":
        try:
            removed = set_limits(request.form.get("cap_gb", ""), request.form.get("days", ""), request.form.get("confirmed") == "1")
        except Refused as e:
            # Lower limits delete at once, for good: first the page says how much, and asks.
            if e.code == "would_delete":
                return recordings_view(e.extra["pending"])
            flash(e.words, e.tone)
            return redirect(url_for("recordings_page"))
        flash(t("rec.limits_removed", n=removed) if removed else t("rec.limits_saved"), "ok")
        return redirect(url_for("recordings_page"))
    # "hide 7/1798000000": one row's button. The rest name their recordings in the check boxes.
    verb, _, one = action.partition(" ")
    names = [one] if one else request.form.getlist("sel")
    # "delete-player 7": all of theirs.
    if verb == "delete-player":
        names = [f"{r['guid']}/{r['id']}" for r in rec_all() if str(r["guid"]) == one]
    done, kept = act_on(verb, names)
    word = {"hide": "rec.done_hide", "show": "rec.done_show"}.get(verb, "rec.done_delete")
    if done or kept:
        flash(t(word, n=done) + (t("rec.kept", n=kept) if kept else ""), "ok" if done else "bad")
    else:
        # A page left open: someone or the limits got there first.
        flash(t("rec.nothing"), "bad")
    return redirect(url_for("recordings_page"))


def set_limits(cap_gb, days, confirmed):
    """The recordings' limits, as the Recordings page's form sends them: a total size in GB (a number, as text or not) and
    an age in whole days. Lower limits delete recordings at once and for good: unless confirmed, they are refused with
    what they would delete (pending, for the page's question). Returns how many recordings they deleted."""
    try:
        cap_gb, days = float(str(cap_gb)), int(str(days))
        if not (0.001 <= cap_gb <= 1000000 and 1 <= days <= 36500):
            raise ValueError
    except ValueError:
        raise Refused(400, "bad_limits", t("rec.bad_limits"))
    over = rec_over_limits(cap_gb, days)
    if over and not confirmed:
        size = sum(r["size"] for r in over)
        raise Refused(409, "would_delete", message=core.plain(t("rec.limits_confirm", n=len(over), size=core.human(size)))
                      + ' Send "confirm": true to save them.', pending={"cap_gb": cap_gb, "days": days, "n": len(over), "size": size})
    rec_save_limits(cap_gb, days)
    changed("recordings_page:limits", f"{cap_gb:g} GB / {days} d")
    rec_sweep_now()
    return len(over)


def act_on(verb, names):
    """Hides (hide), shows (show) or deletes (delete, delete-player) recordings by their names ("7/1798000000"); names that
    are malformed or name no recording are left out. A recording still being made is kept. Returns (done, kept)."""
    done = kept = 0
    who = set()
    for name in names:
        m = re.fullmatch(r"(\d{1,12})/(\d{1,12})", name)
        if not m or not os.path.isdir(rec_folder(*m.groups())):
            continue
        who.add(int(m.group(1)))
        marker = os.path.join(rec_folder(*m.groups()), ".hidden")
        if verb == "hide":
            with open(marker, "a", encoding="utf-8"):
                pass
        elif verb == "show":
            if os.path.exists(marker):
                os.remove(marker)
        elif verb in ("delete", "delete-player"):
            if not rec_remove(*m.groups()):
                kept += 1
                continue
        else:
            continue
        done += 1
    if done:
        # Whose, by name as it is now, and how many: the numbers the files go by say nothing to anyone.
        try:
            with db() as con:
                whose = ", ".join(players.player_label(con, guid) for guid in sorted(who))
        except sqlite3.Error:
            whose = ", ".join(str(guid) for guid in sorted(who))
        changed(f"recordings_page:{verb}", f"{whose} ({done})")
    return done, kept


@app.route(BASE + "/recordings/<int:guid>/<int:rid>/download")
def recording_download(guid, rid):
    """The whole recording as one MPEG-TS file, read as it is sent."""
    rec = rec_folder(guid, rid)
    try:
        with open(os.path.join(rec, "index.m3u8"), encoding="utf-8") as f:
            parts = [os.path.join(rec, line.strip()) for line in f if re.fullmatch(r"\d{1,12}\.ts", line.strip())]
        with open(os.path.join(rec, "meta.json"), encoding="utf-8") as f:
            started = int(json.load(f)["started"])
        length = sum(os.path.getsize(p) for p in parts)
    except (OSError, ValueError, KeyError):
        abort(404)
    # The file's name in plain letters: nicknames may hold anything.
    stamp = datetime.datetime.fromtimestamp(started).strftime("%Y%m%d-%H%M")

    def body():
        for part in parts:
            with open(part, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    yield chunk

    return app.response_class(body(), mimetype="video/mp2t", headers={
        "Content-Length": str(length), "Content-Disposition": f'attachment; filename="opendmtq-player{guid}-{stamp}.ts"'})


@app.route(BASE + "/recordings/<int:guid>/<int:rid>/<name>")
def recording_media(guid, rid, name):
    """The playlist and segments for watching in the page, behind this service's sign-in (guard above)."""
    if not re.fullmatch(r"index\.m3u8|\d{1,12}\.ts", name):
        abort(404)
    path = os.path.join(rec_folder(guid, rid), name)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="application/vnd.apple.mpegurl" if name == "index.m3u8" else "video/mp2t",
                     max_age=0)
