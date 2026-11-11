"""The Songs and Maintenance pages: the song list with its plays, song packages, what is hidden, the notice. Each form's work
is a function (add_package, set_hidden, remove, set_notice) that the API calls as well (api.py)."""

import collections
import json
import os
import sqlite3
import tempfile
import time

from flask import flash, redirect, render_template, request, session, url_for

from .. import songs
from . import core, jobs
from .core import Refused, ago, app, BASE, changed, db, t, tp, why


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


def listed_songs():
    """Every song as the Songs page lists it (songs.catalog(): hidden, added or imported), with its plays over the last 30
    days (plays), its share of the most played song's (share) and when it was last played at all (last_at, 0 for never).
    None when the list cannot be read at all: no client data yet."""
    try:
        listed = songs.catalog()
    except (OSError, ValueError):
        listed = []
    # How much each is played: which are worth keeping and which only fill the list. The bar's full length is the most played.
    plays = song_plays()
    most = max((p["n"] for p in plays.values()), default=0)
    for s in listed:
        p = plays.get(s["song_id"], {"n": 0, "last": 0})
        s.update(plays=p["n"], share=p["n"] / most if most else 0, last_at=p["last"])
    return listed


@app.route(BASE + "/songs", methods=["GET", "POST"])
def songs_page():
    if request.method == "POST":
        action = request.form.get("action")
        try:
            # Each makes the song list again, which takes a while with many songs: a job, which the page follows when it
            # takes longer than its form waits (jobs.answer). The package itself comes with the request.
            if action == "upload":
                return jobs.answer(jobs.start_page_task("songs", page_work(action, path=save_package(request.files.get("package")))), "songs_page")
            if action in ("hide", "show", "remove"):
                return jobs.answer(jobs.start_page_task("songs", page_work(action, song_id=int(request.form["song_id"]))), "songs_page")
        except Refused as e:
            flash(e.words, e.tone)
        except (ValueError, KeyError) as e:
            # A form with no song, or not a number for one.
            flash(core.said(e), "bad")
        except Exception as e:  # noqa: BLE001 - anything else still gets a readable answer
            flash(failed(e).words, "bad")
        return redirect(url_for("songs_page"))
    # A change of this page's that took longer than its form waited: followed here until it ends, then what it said, on
    # the page without it.
    wanted = request.args.get("job", "")
    if wanted and jobs.nothing_to_follow(wanted):
        return redirect(url_for("songs_page"))
    # A song whose tile image could not be made still plays; the owner should know why it looks bare.
    for failure in songs.tile_failures():
        flash(t("songs.no_tile", reason=failure), "bad")
    # No client data yet (the game's files were not imported): the page says so instead of failing. Without songs it
    # says how they come.
    listed = listed_songs()
    # Without the client data the game cannot start (the page says so above the list), but the songs imported on their
    # own are there all the same: listed, not hidden as if the import had not worked.
    no_game_data = not songs.has_game_data()
    for s in listed:
        s["last"] = ago(s["last_at"]) if s["last_at"] else ""
    return render_template("songs.html", songs=listed, no_tree=False, no_game_data=no_game_data, job=wanted or None)


def page_work(action, song_id=None, path=None):
    """The work of one of the Songs page's forms, as its job runs it (jobs.start_page_task): a package saved from the
    request (path), or a song to hide, show or remove. It returns what the page says of it, and whether it worked."""
    def work(say):
        try:
            if action == "upload":
                rec = add_saved(path)
                return [("ok", t("songs.done_add", title=rec["full_name"], id=rec["song_id"], n=len(rec["charts"])))], True
            if action in ("hide", "show"):
                title = set_hidden(song_id, action == "hide")
                return [("ok", t("songs.done_hide" if action == "hide" else "songs.done_show", title=title))], True
            return [("ok", t("songs.done_remove", title=remove(song_id)))], True
        except Refused as e:
            # A refusal of its own words: nothing changed.
            return [(e.tone, e.words)], e.tone == "ok"
        except Exception as e:  # noqa: BLE001 - anything else still gets a readable answer
            return [("bad", failed(e).words)], False
    return work


def failed(e):
    """What a song's action that failed for a reason of its own says (the page and the API alike): the reason, which the
    log has in full. Called while the exception is being handled."""
    app.logger.exception("song action failed")
    return Refused(500, "song_action_failed", t("songs.failed", detail=why(e)))


def add_package(storage):
    """Adds a song package, as the Songs page's form does: the file uploaded (a .zip). Returns the new song's record."""
    return add_saved(save_package(storage))


def save_package(storage):
    """A song package that came with a request, saved where the work that adds it can read it after the request has
    ended (the page's job): the file's path, which add_saved removes. Refused: no .zip file."""
    if not storage or not storage.filename.lower().endswith(".zip"):
        raise Refused(400, "no_package", tp("songs.choose"))
    # A name of its own in the temporary folder: the request's own copy goes when the request ends, the job reads it later.
    fd, path = tempfile.mkstemp(suffix=".zip")
    # Only the name is wanted: saving opens it again.
    os.close(fd)
    try:
        storage.save(path)
    except BaseException:
        # Half a file (a full disk) is nobody's to read.
        os.remove(path)
        raise
    return path


def add_saved(path):
    """Adds the song package save_package kept at path, and removes that file. Returns the new song's record."""
    try:
        rec = songs.add_package(path)
    except songs.SongError as e:
        # A song that was refused: the reason alone does not say that nothing was added.
        raise Refused(422, "package_refused", t("songs.add_failed", reason=core.said(e)))
    finally:
        os.remove(path)
    changed("songs_page:upload", rec["full_name"])
    return rec


def set_hidden(song_id, hide):
    """Hides a song from the game's song list and the site, or shows it again. Returns its title. Refused: hiding a song
    there is not, or a song list that could not be made with it (then nothing changed)."""
    title = song_title(song_id)
    try:
        songs.set_hidden(song_id, hide)
    except songs.SongError as e:
        raise Refused(404 if e.key == "songs.no_such" else 500, "song_not_found" if e.key == "songs.no_such" else "song_action_failed",
                      core.said(e))
    changed("songs_page:" + ("hide" if hide else "show"), title)
    return title


def remove(song_id):
    """Removes an added song (the game's own songs can only be hidden). Returns its title."""
    title = song_title(song_id)
    try:
        songs.remove_song(song_id)
    except songs.SongError as e:
        if e.key != "song.not_added":
            raise Refused(500, "song_action_failed", core.said(e))
        # A song of the game's own, or none at all.
        known = any(s["song_id"] == song_id for s in listed_catalog())
        raise Refused(409 if known else 404, "not_added" if known else "song_not_found", core.said(e))
    changed("songs_page:remove", title)
    return title


def listed_catalog():
    """songs.catalog(), or nothing when it cannot be read."""
    try:
        return songs.catalog()
    except (OSError, ValueError):
        return []


def song_title(song_id):
    """A song's title for a message; its number when it cannot be found."""
    try:
        return next((s["title"] for s in songs.catalog() if s["song_id"] == song_id), str(song_id))
    except (OSError, ValueError):
        return str(song_id)


# The most a maintenance message holds, in characters: a few lines on a phone, where the site shows it on every page while
# it is on. The page's field stops there, and a longer one from anywhere is refused in the same words.
MAINT_MAX = 200


@app.route(BASE + "/maintenance", methods=["GET", "POST"])
def maintenance_page():
    # What sessions before this version kept in the cookie: the last message is kept with the server's settings now.
    session.pop("maintenance_message", None)
    if request.method == "POST":
        on = request.form.get("action") == "on"
        message = request.form.get("message", "")
        try:
            was_on = set_notice(on, message)
        except Refused as e:
            # Too long: the page again with what was typed, to shorten, and why.
            flash(e.words, e.tone)
            return render_template("maintenance.html", on=songs.maintenance()[0], message=message, max=MAINT_MAX), e.status
        flash(t("maint.off" if not on else "maint.updated" if was_on else "maint.on"), "ok")
        return redirect(url_for("maintenance_page"))
    on, message = songs.maintenance()
    # Off: the field holds the message used last, for the next time, until something else is typed.
    return render_template("maintenance.html", on=on, message=message or core.settings().get("maintenance_message", ""), max=MAINT_MAX)


def set_notice(on, message):
    """Turns the in-game maintenance notice on with this message (or the usual one when it is empty), or off, for the page
    and the API alike: a message of more than MAINT_MAX characters is refused, and nothing changes. The message turned on
    is kept with the server's settings, the field's words for the next time. Returns whether it was on before."""
    # A line break is one character, however the browser sent it (a form's are CR LF), and spaces at the ends are none.
    message = (message or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if on and len(message) > MAINT_MAX:
        raise Refused(400, "message_too_long", t("maint.too_long", max=MAINT_MAX))
    was_on = songs.maintenance()[0]
    songs.set_maintenance(on, message, core.PUBLIC_HOST)
    if on:
        # On the server, not in the browser's cookie: a long message made the session cookie near the browsers' limit.
        core.save_settings(maintenance_message=message)
    changed("maintenance_page:" + ("on" if on else "off"))
    return was_on
