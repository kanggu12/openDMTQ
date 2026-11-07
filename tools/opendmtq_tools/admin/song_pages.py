"""The Songs and Maintenance pages: the song list with its plays, song packages, what is hidden, the notice."""

import collections
import json
import os
import sqlite3
import tempfile
import time

from flask import flash, redirect, render_template, request, session, url_for

from .. import songs
from . import core
from .core import ago, app, BASE, changed, db, t, tp, why


def served_song_list():
    """The song list the server serves: its own (with added songs) when there is one, else the game's; none if neither reads."""
    try:
        with open(os.path.join(songs.CUSTOM, "songList.json"), encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        try:
            return songs.base_song_list()
        except (OSError, ValueError):
            return []


def chart_names():
    """pattern id -> (song title, chart name as the portal writes it), from the list the server serves."""
    kinds = {0: "Easy", 1: "Normal", 2: "Hard", 3: "Expert"}
    return {p["pattern_id"]: ((s.get("full_name") or s.get("name") or "").strip(),
                              f"{p['line'] - 1}LINE {kinds.get(p['signature'], p['signature'])} {p['difficulty']}")
            for s in served_song_list() for p in s.get("song_patterns", [])}


def song_plays(days=30):
    """Per song id: its plays over the last days (all its charts together) and when it was last played at all. Empty
    when the game's database cannot be read: the songs page works without it."""
    owner = {p["pattern_id"]: s.get("song_id") for s in served_song_list() for p in s.get("song_patterns", [])}
    out = collections.defaultdict(lambda: {"n": 0, "last": 0})
    try:
        with db() as con:
            for pattern, n in con.execute("SELECT pattern_id, COUNT(*) FROM PlayLog WHERE played_at > ? GROUP BY pattern_id", (time.time() - days * 86400,)):
                if owner.get(pattern) is not None:
                    out[owner[pattern]]["n"] += n
            for pattern, last in con.execute("SELECT pattern_id, MAX(played_at) FROM PlayLog GROUP BY pattern_id"):
                if owner.get(pattern) is not None:
                    out[owner[pattern]]["last"] = max(out[owner[pattern]]["last"], last)
    except (sqlite3.Error, OSError):
        return {}
    return dict(out)


@app.route(BASE + "/songs", methods=["GET", "POST"])
def songs_page():
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "upload":
                f = request.files.get("package")
                if not f or not f.filename.lower().endswith(".zip"):
                    raise ValueError(tp("songs.choose"))
                with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
                    f.save(tmp.name)
                    rec = songs.add_package(tmp.name)
                changed("songs_page:upload", rec["full_name"])
                flash(t("songs.done_add", title=rec["full_name"], id=rec["song_id"], n=len(rec["charts"])), "ok")
            elif action in ("hide", "show"):
                title = song_title(int(request.form["song_id"]))
                songs.set_hidden(int(request.form["song_id"]), action == "hide")
                changed("songs_page:" + action, title)
                flash(t("songs.done_hide" if action == "hide" else "songs.done_show", title=title), "ok")
            elif action == "remove":
                title = song_title(int(request.form["song_id"]))
                songs.remove_song(int(request.form["song_id"]))
                changed("songs_page:remove", title)
                flash(t("songs.done_remove", title=title), "ok")
        except (songs.SongError, ValueError, KeyError) as e:
            # An added song that was refused: the reason alone does not say that nothing was added.
            flash(t("songs.add_failed", reason=core.said(e)) if action == "upload" and isinstance(e, songs.SongError) else core.said(e), "bad")
        except Exception as e:  # noqa: BLE001 - anything else still gets a readable answer
            app.logger.exception("song action failed")
            flash(t("songs.failed", detail=why(e)), "bad")
        return redirect(url_for("songs_page"))
    # A song whose tile image could not be made still plays; the owner should know why it looks bare.
    for failure in songs.tile_failures():
        flash(t("songs.no_tile", reason=failure), "bad")
    # No game data yet (the game's files were not imported): the page says so instead of failing. Without songs it says
    # how they come.
    try:
        listed = songs.catalog()
    except (OSError, ValueError):
        listed = []
    # Without the game data the game cannot start (the page says so above the list), but the songs imported on their
    # own are there all the same: listed, not hidden as if the import had not worked.
    no_game_data = not songs.has_game_data()
    # How much each is played: which are worth keeping and which only fill the list. The bar's full length is the most played.
    plays = song_plays()
    most = max((p["n"] for p in plays.values()), default=0)
    for s in listed:
        p = plays.get(s["song_id"], {"n": 0, "last": 0})
        s.update(plays=p["n"], share=p["n"] / most if most else 0, last=ago(p["last"]) if p["last"] else "")
    return render_template("songs.html", songs=listed, no_tree=False, no_game_data=no_game_data)


def song_title(song_id):
    """A song's title for a message; its number when it cannot be found."""
    try:
        return next((s["title"] for s in songs.catalog() if s["song_id"] == song_id), str(song_id))
    except (OSError, ValueError):
        return str(song_id)


@app.route(BASE + "/maintenance", methods=["GET", "POST"])
def maintenance_page():
    if request.method == "POST":
        on = request.form.get("action") == "on"
        message = request.form.get("message", "").strip()
        was_on = songs.maintenance()[0]
        songs.set_maintenance(on, message, core.PUBLIC_HOST)
        changed("maintenance_page:" + ("on" if on else "off"))
        # Back on next time with what it said: in the field for the next time, until something else is typed.
        session["maintenance_message"] = message
        flash(t("maint.off" if not on else "maint.updated" if was_on else "maint.on"), "ok")
        return redirect(url_for("maintenance_page"))
    on, message = songs.maintenance()
    return render_template("maintenance.html", on=on, message=message or session.get("maintenance_message", ""))
