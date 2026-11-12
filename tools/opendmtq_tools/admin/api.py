"""OpenDMTQ's HTTP API, at /opendmtq/api/v1 beside the admin pages: everything the admin pages show and do, and what the
players' site shows, as JSON (docs/api.md).

The routes come from the route table (api_routes.py), which also makes the OpenAPI document and the reference in the docs.
Each route here calls the same function as the page with that action (accounts.create, players.act, backups.create...):
a page and the API cannot differ. A token on every request (Authorization: Bearer odq_...), made on the Accounts page or
through the API: read tokens answer GET only, write tokens everything. No session, no cookie, no form token. Refusals
answer {"error": {"code", "message"}}."""

import datetime
import json
import math
import os
import re
import shutil
import sqlite3
import threading
import time

from flask import g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from .. import songs
from . import accounts, api_routes, apps, auth, backups, core, insights, jobs, logs, players, recordings, setup, site, song_pages, tokens
# The status page's module by another name: the route's handler is called status.
from . import status as status_page
from .core import Refused, app, changed, db, json_error, plain, tp

# The handlers by their name in the route table.
HANDLERS = {}

# The methods a read token may use: those that change nothing.
READS = ("GET", "HEAD", "OPTIONS")

# The OpenAPI document's address: the one route that answers without a token, as it holds no data.
OPENAPI = core.API_V1 + "/openapi.json"

# How long a throttled caller is told to wait (Retry-After): the sign-in throttle's window.
RETRY_AFTER = str(auth.WINDOW)

# Refused tokens noted in the log of changes, by address: when each address's last line was written (note_refused).
_refused_noted = {}
_refused_lock = threading.Lock()

# The largest whole number the database keeps (SQLite's 64-bit integers). A number past it in a path is no player,
# song or recording (404), and in a body it is refused (400): handed to the database it would only fail.
INT_MAX = api_routes.INT_MAX

# The scope each route takes, by its endpoint: a read token is refused on a write route, whatever its method (a
# backup's download, and the setup's looks at the server PC's folders, are GETs that take a write token).
SCOPES = {"api_" + route.name: route.scope for route in api_routes.ROUTES}

# The routes that take a file, with the page's limit for the same file (core.AdminRequest reads these); a backup waits on
# the backups disk while it comes, as on the Backups page.
core.API_LIMITS.update({"api_songs_add": songs.MAX_PACKAGE, "api_backups_upload": core.MAX_BACKUP})
core.API_TO_BACKUPS.add("api_backups_upload")


def handler(fn):
    """Registers fn as the handler of the route with its name (api_routes.ROUTES)."""
    HANDLERS[fn.__name__] = fn
    return fn


# ------------------------------------------------------------------------------ the token

@app.before_request
def check_token():
    """Every request to the API but the OpenAPI document needs a token that works, and a write needs a write token. The
    token is looked at first: one that works is never held back by the sign-in throttle, whatever else came from the same
    address. A wrong one counts as a failed sign-in there (auth.py), so that guessing one stays as slow as guessing a
    password, and over the throttle's limit wrong ones are answered 429."""
    if not core.is_api(request.path):
        return None
    if request.path == OPENAPI and request.method in ("GET", "HEAD"):
        return None
    # No password for the admin pages: they are off, and the API with them.
    if not core.PASSWORD:
        return json_error(503, "admin_off", "The admin pages have no password (ADMIN_PASSWORD in .env), so the API is off too.")
    sent = request.headers.get("Authorization", "")
    if not sent.strip():
        return json_error(401, "no_token", "Send a token: Authorization: Bearer <token>. Tokens are made on the admin pages' Accounts page.",
                          {"WWW-Authenticate": 'Bearer realm="OpenDMTQ API"'})
    scheme, _, token = sent.strip().partition(" ")
    try:
        row = tokens.check(token.strip()) if scheme.lower() == "bearer" else None
    except sqlite3.Error:
        return json_error(503, "database_unavailable", plain(core.t("err.db_text")))
    if row is None:
        ip = auth.client_ip()
        # Over the limit: answered without another count, as a sign-in over it is not counted either.
        if auth.throttled(ip):
            return json_error(429, "throttled", "Too many wrong tokens or passwords from here lately. Try again later.",
                              {"Retry-After": RETRY_AFTER})
        # A guess, or a token revoked or mistyped: counted, and in the log of changes by its address alone (the token
        # itself is never written anywhere).
        auth.note_failure(ip)
        note_refused(ip)
        return json_error(401, "bad_token", "That token is not one of this server's: it was revoked, or it is mistyped.",
                          {"WWW-Authenticate": 'Bearer realm="OpenDMTQ API", error="invalid_token"'})
    if not row["works"]:
        return json_error(401, "token_stopped", f"The token's admin ({row['admin']}) cannot use the admin pages now: their account is "
                          "disabled or has no admin rights.", {"WWW-Authenticate": 'Bearer realm="OpenDMTQ API", error="invalid_token"'})
    # The route's own scope; an address no route has (answered 404 or 405 next) by its method.
    needs = SCOPES.get(request.endpoint) or ("read" if request.method in READS else "write")
    if needs == "write" and row["scope"] != "write":
        return json_error(403, "read_only", "This is a read token, and this route takes a write token: every change, a "
                          "backup's download, and a look at the server PC's folders.")
    # Who acts, for the log of changes (core.changed): the admin, and which of their tokens.
    g.api_token, g.api_who = row, f"{row['admin']} ({row['name']})"
    tokens.touch(row)
    return None


def note_refused(ip):
    """A refused token in the log of changes, as the sign-in page notes a failed sign-in: by "API", with the address it
    came from. At most once per address in the throttle's window, so that a flood of guesses cannot fill the log."""
    now = time.time()
    with _refused_lock:
        # Addresses whose window has passed are forgotten: this stays as small as the throttle's own count.
        for old in [a for a, at in _refused_noted.items() if now - at >= auth.WINDOW]:
            del _refused_noted[old]
        if ip in _refused_noted:
            return
        _refused_noted[ip] = now
    # Who acted, for core.changed: no admin is known, only that it came through the API.
    g.api_who = "API"
    changed("api:refused", ip)


@app.after_request
def private_answers(response):
    """The API's answers are this server's own data: never kept by a cache on the way."""
    if core.is_api(request.path):
        response.headers["Cache-Control"] = "no-store"
    return response


def acting():
    """Who acts, as the Accounts page's actions take it: (ID, owner)."""
    return g.api_token["admin"], g.api_token["owner"]


# ------------------------------------------------------------------------------ what a request sends

def bad(code, message):
    """A request that cannot be done as sent."""
    return Refused(400, code, message=message)


def check_value(field, value, where):
    """value as field asks for it, or Refused (400): its type, null, its values."""
    if value is None:
        if field.nullable:
            return None
        raise bad(where, f"{field.name} cannot be null.")
    kind = field.type
    ok = {"string": lambda v: isinstance(v, str),
          "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
          "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v),
          "boolean": lambda v: isinstance(v, bool),
          "[string]": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v)}[kind](value)
    if not ok:
        raise bad(where, f"{field.name} must be {'a list of strings' if kind == '[string]' else 'an ' + kind if kind == 'integer' else 'a ' + kind}.")
    # A whole number the database can keep: a larger one would make the lookup there fail with no answer.
    if kind == "integer" and not -INT_MAX - 1 <= value <= INT_MAX:
        raise bad(where, f"{field.name} is out of range.")
    if field.enum and value not in field.enum:
        raise bad(where, f"{field.name} must be one of: {', '.join(field.enum)}.")
    # Text the page would cut to its field's length is refused here instead: a program is told, a person sees the field.
    if field.max_length is not None and len(value) > field.max_length:
        raise bad(where, f"{field.name} is longer than {field.max_length} characters.")
    return value


def read_body(route):
    """The JSON body a route takes, checked field by field: unknown fields and missing ones are refused. A route whose
    every field is optional also takes no body at all."""
    if not route.body:
        return {}
    raw = request.get_data(cache=True)
    if not raw.strip():
        data = {}
    else:
        if not request.is_json:
            raise bad("bad_json", "Send the body as JSON (Content-Type: application/json).")
        try:
            data = json.loads(raw)
        except ValueError:
            raise bad("bad_json", "The body is not JSON.")
    if not isinstance(data, dict):
        raise bad("bad_json", "The body must be a JSON object.")
    fields = {f.name: f for f in route.body}
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise bad("bad_field", f"Unknown field: {', '.join(unknown)}. This route takes {', '.join(fields)}.")
    out = {}
    for name, field in fields.items():
        if name not in data:
            if not field.optional:
                raise bad("bad_field", f"{name} is missing.")
            continue
        out[name] = check_value(field, data[name], "bad_field")
    return out


def read_query(route):
    """The query a route takes, each value of its type: integers in digits, booleans as true or false."""
    out = {}
    for field in route.query:
        raw = request.args.get(field.name)
        if raw is None:
            if not field.optional:
                raise bad("bad_query", f"?{field.name}= is missing.")
            continue
        if field.type == "integer":
            if not re.fullmatch(r"[0-9]{1,12}", raw):
                raise bad("bad_query", f"?{field.name}= must be a whole number.")
            value = int(raw)
        elif field.type == "boolean":
            if raw.lower() not in ("true", "false", "1", "0"):
                raise bad("bad_query", f"?{field.name}= must be true or false.")
            value = raw.lower() in ("true", "1")
        else:
            value = raw
        out[field.name] = check_value(field, value, "bad_query")
    return out


def dispatch(route, **params):
    """One request to a route: its query and body checked, its handler called with them and the path's own parts, and
    what it gives back as JSON (or the file it gives). A refusal answers as the route table says."""
    # A number in the path past the largest the database keeps names nothing there: answered as an address that leads
    # nowhere, whatever the method (a converter's own limit would answer some methods 405).
    if any(isinstance(v, int) and v > INT_MAX for v in params.values()):
        return json_error(404, "not_found", "There is nothing at this address.")
    try:
        args = dict(params, **read_query(route), **read_body(route))
        answer = HANDLERS[route.name](args)
    except Refused as e:
        # With what the route table names for the error besides its words (the folder the picker opens instead, say).
        return json_error(e.status, e.code, e.sentence(), extra={k: v for k, v in e.extra.items() if k in api_routes.ERROR_FIELDS})
    if isinstance(answer, tuple):
        body, code = answer
        response = jsonify(body)
        response.status_code = code
        return response
    if isinstance(answer, dict):
        return jsonify(answer)
    return answer


def register():
    """Each route of the table as a Flask rule under /opendmtq/api/v1: {name} parts of type integer as <int:name>, others
    as one part of the path. The endpoint is api_<name>."""
    for route in api_routes.ROUTES:
        rule = core.API_V1 + re.sub(r"{(\w+)}", lambda m: f"<int:{m.group(1)}>" if route.param(m.group(1))[0] == "integer"
                                    else f"<{m.group(1)}>", route.path)

        # The route is bound now (a default value): a closure would see only the loop's last one.
        def view(_route=route, **params):
            return dispatch(_route, **params)

        app.add_url_rule(rule, endpoint="api_" + route.name, view_func=view, methods=[route.method])


def the_file(storage_field):
    """The file a route's upload sent (None when there is none). Read before anything else: a body over the route's
    limit is refused (413) here, as on the pages."""
    return request.files.get(storage_field)


# ------------------------------------------------------------------------------ status

@handler
def openapi(args):
    """GET /openapi.json: the OpenAPI document, made from the route table each time, so it cannot differ from the routes."""
    return api_routes.openapi(os.environ.get("OPENDMTQ_VERSION") or "1")


def game_server(health):
    """The game server's health as the status page reads it."""
    problem = core.server_problem(health)
    return {"answering": health is not None, "ok": bool(health and health.get("ok")), "problem": plain(problem) if problem else None,
            "waiting_for_files": core.waiting_for_files(health), "health": health}


def build_view(b):
    """A build of the app."""
    return {"file": b["file"], "address": b["host"], "built_at": b["built_at"], "size": b["size"], "sha256": b["sha256"],
            "runtime": b["runtime"], "label": b["label"], "on_offer": b["current"], "made_at": int(b["mtime"])}


@handler
def status(args):
    """GET /status: what the Status page shows, from the same facts (status.facts) and the same list of what needs a look."""
    f = status_page.facts()
    health, saved, build, usage = f["health"], f["saved"], f["build"], f["usage"]
    use = status_page.disk_use(usage)
    attention = status_page.attention(health, f["counts"], saved, f["backup_age"], f["maintenance"], build, f["failed"], usage)
    return {
        "version": os.environ.get("OPENDMTQ_VERSION") or None, "address": core.PUBLIC_HOST, "instance": setup.STARTED,
        "game_server": game_server(health), "counts": f["counts"],
        "recent": [{"player": r["id"], "name": str(r["who"]), "song": r["song"], "chart": r["chart"], "score": r["score"], "grade": r["grade"],
                    "new_record": bool(r["new"]), "at": r["at"]} for r in f["recent"]],
        "backups": {"newest": saved[0][0] if saved else None, "newest_at": int(saved[0][1]) if saved else None,
                    "daily": bool(core.settings().get("auto_backup")), "daily_failure": backups._auto_failure or None},
        "app": {"on_offer": build_view(build) if build else None, "build_error": plain(f["failed"]) if f["failed"] else None,
                "other_address": (health or {}).get("apk_matches_host") is False},
        "maintenance": f["maintenance"], "recordings": f["recordings"],
        "disk": {"total": usage.total, "used": usage.used, "free": usage.free,
                 "parts": {"recordings": use["recordings"], "backups": use["backups"], "builds": use["builds"], "songs": use["songs"],
                           "database": use["db"], "game": use["game"], "rest": use["rest"], "other": use["other"], "free": use["free"]}},
        "attention": [{"level": level, "text": plain(text), "link": link} for level, text, link, _ in attention],
    }


@handler
def status_health(args):
    """GET /status/health: the game server asked now, past the pages' short cache. 503 while it is not well, so a
    monitor needs only the status."""
    health = core.server_health(fresh=True)
    if health is None:
        raise Refused(503, "server_down", message="The game server does not answer.")
    if not health.get("ok"):
        raise Refused(503, "server_unwell", message=plain(core.server_problem(health)))
    return health


@handler
def status_machine(args):
    """GET /status/machine: the Status page's machine figures, for the disk the database is on."""
    return status_page.machine_figures(shutil.disk_usage(os.path.dirname(core.DB)))


@handler
def status_activity(args):
    """GET /status/activity: the numbers behind the Status page's charts; days as dates, the same in any language."""
    with db() as con:
        a = status_page.activity(con)
    return {"days": [{"day": d.isoformat(), "plays": n} for d, n in a["days"]], "hours": a["hours"],
            "players": [{"player": guid, "name": name or tp("player.fallback", id=guid), "plays": n} for guid, name, n in a["players"]],
            "songs": [{"title": title, "plays": n} for title, n in a["songs"]],
            "grades": [{"grade": grade, "records": n} for grade, n in a["grades"]]}


# ------------------------------------------------------------------------------ jobs

@handler
def jobs_list(args):
    """GET /jobs: the jobs this service keeps, as the pages' job views see them."""
    return {"items": [jobs.view(j) for j in jobs.listing()]}


@handler
def job_get(args):
    """GET /jobs/{job}: one job, which a caller asks for after a 202 until it ends."""
    job = jobs._jobs.get(args["job"])
    if not job:
        raise Refused(404, "job_not_found", message="There is no such job. Jobs are forgotten when the admin service starts again.")
    return {"job": jobs.view(job)}


def started(job_id):
    """The answer to what started a job: 202 with the job."""
    return {"job": jobs.view(jobs._jobs[job_id])}, 202


# ------------------------------------------------------------------------------ the app and its builds

@handler
def app_get(args):
    """GET /app: the top of the App page: the build players get, whether it fits this address, a build running now."""
    listed = apps.builds()
    offer, state, failed = apps.offer_state(listed)
    running = jobs.running_build()
    return {"name": core.app_name(), "address": core.PUBLIC_HOST, "on_offer": build_view(offer) if offer else None,
            "state": {"on": "fits", "wait": "rebuild_failed", "bad": "other_address"}[state[0]] if state else None,
            "says": plain(state[1]) if state else None, "build_error": plain(failed) if failed else None,
            "icon": os.path.isfile(os.path.join(core.APK, "out", "app-icon.png")), "windows": windows_view(apps.windows_offer(offer)),
            "building": jobs.view(running) if running else None}


def windows_view(made):
    """The installer for Windows as the API shows it (WindowsInstaller), or None."""
    if not made:
        return None
    return {"file": made["file"], "size": made["size"], "sha256": made["sha256"], "version": made.get("version") or None,
            "copied_at": made.get("copied_at")}


@handler
def app_windows(args):
    """GET /app/windows: the App page's Download for Windows (apps.windows_download), as the site hands it out."""
    if not apps.windows_offer():
        raise Refused(404, "not_found", message="This server keeps no installer for Windows.")
    return apps.windows_download()


def kept_file(*parts, mimetype):
    """A file the builder keeps in data/apk/out, or 404."""
    path = os.path.join(core.APK, "out", *parts)
    if not os.path.isfile(path):
        raise Refused(404, "not_found", message="It is not there.")
    return send_file(path, mimetype=mimetype, max_age=0)


@handler
def app_icon(args):
    """GET /app/icon: the launcher icon the builder kept, as the App page shows it."""
    return kept_file("app-icon.png", mimetype="image/png")


@handler
def builds_list(args):
    """GET /builds: the App page's list of builds."""
    return {"items": [build_view(b) for b in apps.builds()]}


@handler
def builds_start(args):
    """POST /builds: the App page's Build (apps.start_build): the same checks, the same job."""
    job, _ = apps.start_build(args.get("host") or "")
    return started(job)


def find_build(name):
    """A build by its file name, or 404."""
    b = next((b for b in apps.builds() if b["file"] == name), None)
    if not b:
        raise Refused(404, "build_not_found", plain(core.t("app.gone")))
    return b


@handler
def build_get(args):
    """GET /builds/{file}: one build of the list."""
    return {"build": build_view(find_build(args["file"]))}


@handler
def build_download(args):
    """GET /builds/{file}/download: the App page's download link (apps.download)."""
    return apps.download(args["file"])


@handler
def build_delete(args):
    """DELETE /builds/{file}: the App page's Delete (apps.delete), which keeps the build on offer."""
    apps.delete(args["file"])
    return {"deleted": args["file"]}


@handler
def builds_prune(args):
    """POST /builds/prune: the App page's Delete old builds (apps.prune)."""
    n, freed = apps.prune()
    return {"deleted": n, "freed": freed}


@handler
def invite_get(args):
    """GET /invite: the address the invite message sends players to, and whether its QR code was made."""
    return {"url": apps.friends_address(core.server_health()), "qr": os.path.isfile(os.path.join(core.APK, "out", "download-qr.svg"))}


@handler
def invite_qr(args):
    """GET /invite/qr: that address's QR code, as the builder made it."""
    return kept_file("download-qr.svg", mimetype="image/svg+xml")


# ------------------------------------------------------------------------------ songs

def song_view(s):
    """A song as the Songs page lists it."""
    return {"id": s["song_id"], "name": s["name"], "title": s["title"], "artist": s["artist"], "charts": s["charts"],
            "hidden": s["hidden"], "source": "added" if s["added"] else "imported", "plays": s["plays"],
            "last_played": s["last_at"] or None}


def find_song(song_id):
    """A song of the Songs page's list, or 404."""
    s = next((s for s in song_pages.listed_songs() if s["song_id"] == song_id), None)
    if not s:
        raise Refused(404, "song_not_found", plain(core.t("songs.no_such", id=song_id)))
    return s


def song_work(fn, *values):
    """A song's action, as the Songs page answers one: a reason of its own (a full disk) in the page's words."""
    try:
        return fn(*values)
    except (Refused, HTTPException):
        raise
    except Exception as e:  # noqa: BLE001 - anything else still gets a readable answer, as on the page
        raise song_pages.failed(e)


@handler
def songs_list(args):
    """GET /songs: the Songs page's list (song_pages.listed_songs), with the page's warnings as fields."""
    return {"items": [song_view(s) for s in song_pages.listed_songs()], "client_data": songs.has_game_data(),
            "tile_failures": [str(x) for x in songs.tile_failures()]}


@handler
def songs_add(args):
    """POST /songs: the Songs page's Add (song_pages.add_package): the same size limit and the same checks of each file."""
    package = the_file("package")
    rec = song_work(song_pages.add_package, package)
    return {"song": song_view(find_song(rec["song_id"]))}, 201


@handler
def song_get(args):
    """GET /songs/{song}: one song of the list."""
    return {"song": song_view(find_song(args["song"]))}


@handler
def song_hide(args):
    """POST /songs/{song}/hide: the Songs page's Hide (song_pages.set_hidden). A hidden song stays hidden and the
    answer is the same, as on the page."""
    title = song_work(song_pages.set_hidden, args["song"], True)
    return {"id": args["song"], "title": title, "hidden": True}


@handler
def song_show(args):
    """POST /songs/{song}/show: the Songs page's Show, the other way."""
    title = song_work(song_pages.set_hidden, args["song"], False)
    return {"id": args["song"], "title": title, "hidden": False}


@handler
def song_remove(args):
    """DELETE /songs/{song}: the Songs page's Remove (song_pages.remove), for added songs only."""
    song_work(song_pages.remove, args["song"])
    return {"deleted": str(args["song"])}


# ------------------------------------------------------------------------------ the notice, and stopping

def notice():
    """The maintenance notice as the game reads it."""
    on, message = songs.maintenance()
    return {"on": on, "message": message}


@handler
def maintenance_get(args):
    """GET /maintenance: the Maintenance page's notice."""
    return notice()


@handler
def maintenance_set(args):
    """PUT /maintenance: the Maintenance page's On, with its message (song_pages.set_notice, which refuses a long one)."""
    song_pages.set_notice(True, args.get("message") or "")
    return notice()


@handler
def maintenance_clear(args):
    """DELETE /maintenance: the Maintenance page's Off."""
    song_pages.set_notice(False, "")
    return notice()


@handler
def server_stop(args):
    """POST /server/stop: the Maintenance page's Stop the server (setup.stop_server). 202: the answer leaves before the
    server stops."""
    setup.stop_server()
    return {"stopping": True}, 202


# ------------------------------------------------------------------------------ players

def player_views(only=None):
    """The players as the Players page lists them (only: one number's)."""
    rows, live, seen, activity, phones = players.player_rows()
    # Broadcasts off for the server: a switch that is on is held for then (the Players page's "held").
    held = not recordings.live_settings()["on"]
    out = []
    for p in rows:
        if only is not None and p["id"] != only:
            continue
        a = activity[p["id"]]
        out.append({"id": p["id"], "name": p["nickname"].strip() or tp("player.fallback", id=p["id"]), "nickname": p["nickname"].strip(),
                    "charts": p["charts"], "total": p["total"], "last_played": a["last"], "plays_30_days": a["recent"], "days": list(a["days"]),
                    "phones": phones.get(p["id"], 0),
                    "broadcast": "held" if held and p["id"] in live else "on_air" if live.get(p["id"]) else "waiting" if p["id"] in live else "off",
                    "seen": seen.get(p["id"], "")})
    return out


def one_player(guid):
    """A player as the Players page lists them, or 404."""
    found = player_views(guid)
    if not found:
        raise Refused(404, "player_not_found", message=f"There is no player {guid}.")
    return found[0]


@handler
def players_list(args):
    """GET /players: the Players page's list (players.player_rows)."""
    return {"items": player_views()}


@handler
def players_download(args):
    """GET /players/download: the Players page's spreadsheet, the same file."""
    rows, _, _, activity, _ = players.player_rows()
    return players.players_csv(rows, activity)


@handler
def player_get(args):
    """GET /players/{player}: one row of the list."""
    return {"player": one_player(args["player"])}


@handler
def player_rename(args):
    """POST /players/{player}/rename: the Players page's Rename (players.act), ?seen= as the page's form sends it."""
    players.act(args["player"], "rename", args.get("seen"), args["name"])
    return {"player": one_player(args["player"])}


@handler
def player_reset(args):
    """POST /players/{player}/reset: the Players page's Reset scores, which makes a backup first: its name comes back."""
    done = players.act(args["player"], "reset", args.get("seen"))
    return {"player": one_player(args["player"]), "backup": done["backup"]}


@handler
def player_delete(args):
    """DELETE /players/{player}: the Players page's Delete, which makes a backup first."""
    done = players.act(args["player"], "delete", args.get("seen"))
    return {"deleted": args["player"], "backup": done["backup"]}


@handler
def player_live_on(args):
    """POST /players/{player}/live: the Players page's broadcast switch, on."""
    players.act(args["player"], "live-on", args.get("seen"))
    return {"player": one_player(args["player"])}


@handler
def player_live_off(args):
    """DELETE /players/{player}/live: the broadcast switch, off."""
    players.act(args["player"], "live-off", args.get("seen"))
    return {"player": one_player(args["player"])}


# ------------------------------------------------------------------------------ accounts

def account_rows():
    """Every account, and the game's players to link one to, as the Accounts page reads them."""
    with db() as con:
        auth.account_table(con)
        choices = auth.game_players(con)
        rows = con.execute("SELECT name, note, admin, created_at, signed_in_at, off, guid FROM SiteUser ORDER BY name COLLATE NOCASE").fetchall()
    return rows, choices


def account_view(row, choices):
    """An account."""
    names = dict(choices)
    return {"name": row["name"], "note": row["note"], "admin": bool(row["admin"]), "enabled": not row["off"], "created_at": row["created_at"],
            "signed_in_at": row["signed_in_at"], "player": row["guid"], "player_name": names.get(row["guid"]) if row["guid"] is not None else None}


def one_account(name):
    """An account, or 404."""
    rows, choices = account_rows()
    row = next((r for r in rows if r["name"].lower() == name.lower()), None)
    if not row:
        raise Refused(404, "account_not_found", plain(core.t("acc.gone", name=name)))
    return account_view(row, choices)


def with_password(name, password):
    """An account with its password and the message to send its player, as the Accounts page shows them once."""
    account = one_account(name)
    return {"account": account, "password": password,
            "message": apps.invite_text(apps.friends_address(core.server_health()), account["name"], password)}


@handler
def accounts_list(args):
    """GET /accounts: the Accounts page's list, with the players an account can be linked to."""
    rows, choices = account_rows()
    return {"items": [account_view(r, choices) for r in rows], "owner": core.ADMIN_USER,
            "players": [{"id": guid, "name": name} for guid, name in choices]}


@handler
def accounts_create(args):
    """POST /accounts: the Accounts page's form (accounts.create). The password, typed or made, is in this answer only."""
    name = (args["name"] or "").strip()
    password = args.get("password") or ""
    # Typed once here: an API call has no slip of the finger to catch. A note over 40 characters was refused already.
    made = accounts.create(name, password, password, (args.get("note") or "").strip(), bool(args.get("admin")), args.get("player"))
    return with_password(name, made), 201


@handler
def account_get(args):
    """GET /accounts/{account}: one account of the list."""
    return {"account": one_account(args["account"])}


@handler
def account_password(args):
    """POST /accounts/{account}/password: the Accounts page's New password (accounts.change), in this answer only."""
    done = accounts.change(args["account"], "password", acting())
    return with_password(done["name"], done["password"])


def account_change(action):
    """The handler of an account's button: off, on, admin or player."""
    def run(args):
        # The same change as the page's button, then the account as it is after it.
        done = accounts.change(args["account"], action, acting())
        return {"account": one_account(done["name"])}
    return run


HANDLERS["account_disable"] = account_change("off")
HANDLERS["account_enable"] = account_change("on")
HANDLERS["account_make_admin"] = account_change("admin")
HANDLERS["account_make_player"] = account_change("player")


@handler
def account_link(args):
    """POST /accounts/{account}/link: the Accounts page's choice of the player an account is (accounts.link)."""
    name, _, _ = accounts.link(args["account"], args["player"])
    return {"account": one_account(name)}


@handler
def account_delete(args):
    """DELETE /accounts/{account}: the Accounts page's Delete, which takes the account's tokens with it."""
    done = accounts.change(args["account"], "delete", acting())
    return {"deleted": done["name"]}


# ------------------------------------------------------------------------------ tokens

def token_view(row):
    """A token: never its hash, never the token."""
    return {k: row[k] for k in ("id", "name", "scope", "admin", "owner", "created_at", "used_at", "works")}


@handler
def tokens_list(args):
    """GET /tokens: the tokens on the Accounts page."""
    return {"items": [token_view(r) for r in tokens.listing()]}


@handler
def tokens_create(args):
    """POST /tokens: a token for the admin whose token asks, as the Accounts page makes one for the admin signed in.
    The token is in this answer only."""
    row, secret = tokens.make(args["name"], args["scope"], (g.api_token["admin"], g.api_token["owner"], g.api_token["admin_since"]))
    return {"token": token_view(row), "secret": secret}, 201


@handler
def token_revoke(args):
    """DELETE /tokens/{token}: the Accounts page's Revoke."""
    tokens.revoke(args["token"])
    return {"deleted": args["token"]}


# ------------------------------------------------------------------------------ recordings

def recording_view(r, names):
    """A recording, as the Recordings page lists it."""
    return {"key": f"{r['guid']}/{r['id']}", "player": r["guid"], "id": r["id"], "name": names.get(r["guid"]) or tp("player.fallback", id=r["guid"]),
            "started": int(r.get("started") or r["id"]), "ended": int(r["ended"]) if r.get("ended") and not r["open"] else None,
            "duration_ms": int(r.get("duration_ms") or 0), "size": int(r.get("size") or 0),
            "songs": [{"title": str(s.get("title", "")), "chart": str(s.get("chart", "")), "at": int(s["at"]) if s.get("at") is not None else None}
                      for s in r.get("songs", []) if isinstance(s, dict)],
            "open": r["open"], "hidden": r["hidden"]}


def find_recording(guid, rid):
    """A recording, or 404. Only its own folder is read, not every recording's."""
    r = recordings.rec_item(guid, rid)
    if not r:
        raise Refused(404, "recording_not_found", plain(core.t("rec.nothing")))
    return r


@handler
def recordings_list(args):
    """GET /recordings: the Recordings page's list, with the page's names (recordings.player_names)."""
    names = recordings.player_names()
    return {"items": [recording_view(r, names) for r in recordings.rec_all()]}


def limits_view():
    """The limits, and what the recordings take of the disk, as the Recordings page shows them: the same function
    (recordings.rec_room), at the quality the phones are asked for now."""
    return recordings.rec_room()


@handler
def recordings_limits(args):
    """GET /recordings/limits: the Recordings page's limits, and what still fits."""
    return limits_view()


def broadcasts_view():
    """The Broadcasts page's settings, as it shows them: on or off, what new players start with, the quality and each
    quality's costs, and who is switched on and on air."""
    settings = recordings.live_settings()
    try:
        with db() as con:
            counts = recordings.live_counts(con)
    except sqlite3.Error:
        counts = {"switched_on": 0, "on_air": 0}
    # Each quality's costs, as the page lists them (the same function).
    qualities = recordings.quality_costs()
    return {"on": settings["on"], "new_players": settings["new_players"], "quality": settings["quality"], "qualities": qualities,
            "switched_on": counts["switched_on"], "on_air": counts["on_air"] if settings["on"] else 0}


@handler
def broadcasts_get(args):
    """GET /broadcasts: the Broadcasts page's settings (broadcasts_view)."""
    return broadcasts_view()


@handler
def broadcasts_set(args):
    """PUT /broadcasts: turns broadcasts on or off for the server, sets what new players start with and the quality, as the
    Broadcasts page's two forms do (recordings.live_settings_save). What is left out stays as it is."""
    if not any(name in args for name in ("on", "new_players", "quality")):
        raise bad("bad_body", "Send on, new_players or quality.")
    recordings.live_settings_save(on=args.get("on"), new_players=args.get("new_players"), quality=args.get("quality"))
    return broadcasts_view()


@handler
def recordings_set_limits(args):
    """PUT /recordings/limits: the Recordings page's limits (recordings.set_limits). Limits that would delete
    recordings answer 409 until confirm is true, as the page asks first."""
    deleted = recordings.set_limits(str(args["cap_gb"]), str(args["days"]), bool(args.get("confirm")))
    return dict(limits_view(), deleted=deleted)


def recordings_done(done, kept):
    """What an action on recordings did, refused when it did nothing: none there, or all still being made."""
    if not done and not kept:
        raise Refused(404, "recording_not_found", plain(core.t("rec.nothing")))
    if not done:
        raise Refused(409, "recording_open", message="They are still being made: a recording can be deleted once it is closed.")
    return {"done": done, "kept": kept}


@handler
def recordings_delete(args):
    """POST /recordings/delete: the Recordings page's Delete selected, or all of a player's."""
    if ("items" in args) == ("player" in args):
        raise bad("bad_body", "Send items (the recordings) or player (all of theirs), one of the two.")
    if "player" in args:
        # The page's "Delete all" itself: the same function, so the two cannot pick differently.
        return recordings_done(*recordings.rec_delete_player(args["player"]))
    return recordings_done(*recordings.act_on("delete", args["items"]))


@handler
def recording_get(args):
    """GET /recordings/{player}/{recording}: one recording, with its files in the order its playlist names them."""
    r = find_recording(args["player"], args["recording"])
    files = []
    if not r["open"]:
        folder = recordings.rec_folder(r["guid"], r["id"])
        try:
            with open(os.path.join(folder, "index.m3u8"), encoding="utf-8") as f:
                parts = [line.strip() for line in f if re.fullmatch(r"\d{1,12}\.ts", line.strip())]
            files = [{"name": n, "size": os.path.getsize(os.path.join(folder, n))} for n in ["index.m3u8"] + parts
                     if os.path.isfile(os.path.join(folder, n))]
        except OSError:
            files = []
    return {"recording": recording_view(r, recordings.player_names()), "files": files}


@handler
def recording_download(args):
    """GET /recordings/{player}/{recording}/download: the Recordings page's download as one file."""
    return recordings.recording_download(args["player"], args["recording"])


@handler
def recording_file(args):
    """GET /recordings/{player}/{recording}/files/{part}: what the page's player plays (recordings.recording_media)."""
    return recordings.recording_media(args["player"], args["recording"], args["part"])


def recording_flag(verb):
    """The handler of a recording's Hide or Show."""
    def run(args):
        # 404 for a recording that is not there, before the page's action, which would only find nothing to do.
        find_recording(args["player"], args["recording"])
        recordings_done(*recordings.act_on(verb, [f"{args['player']}/{args['recording']}"]))
        return {"recording": recording_view(find_recording(args["player"], args["recording"]), recordings.player_names())}
    return run


HANDLERS["recording_hide"] = recording_flag("hide")
HANDLERS["recording_show"] = recording_flag("show")


@handler
def recording_delete(args):
    """DELETE /recordings/{player}/{recording}: the Recordings page's Delete of one."""
    key = f"{args['player']}/{args['recording']}"
    find_recording(args["player"], args["recording"])
    recordings_done(*recordings.act_on("delete", [key]))
    return {"deleted": key}


# ------------------------------------------------------------------------------ backups

KINDS = {"bak.kind_auto": "daily", "bak.kind_uploaded": "uploaded", "bak.kind_before": "before", "bak.kind_deploy": "deploy", "bak.kind_hand": "hand"}


def backup_view(f):
    """A backup."""
    return {"name": f["name"], "size": f["size"], "made": int(f["made"]), "kind": KINDS[f["kind"]]}


def one_backup(name):
    """A backup of the list, or 404."""
    f = next((f for f in backups.listing() if f["name"] == name), None)
    if not f:
        raise Refused(404, "backup_not_found", plain(core.t("bak.gone")))
    return backup_view(f)


@handler
def backups_list(args):
    """GET /backups: the Backups page's list."""
    return {"items": [backup_view(f) for f in backups.listing()]}


@handler
def backups_create(args):
    """POST /backups: the Backups page's Back up now (backups.create). It is done when it answers: 201 with the backup."""
    return {"backup": one_backup(backups.create())}, 201


@handler
def backups_upload(args):
    """POST /backups/upload: the Backups page's Upload (backups.upload): the same limit, the same check that it is a
    backup."""
    archive = the_file("file")
    return {"backup": one_backup(backups.upload(archive))}, 201


def daily_view():
    """The daily backup, as the Backups page shows it."""
    daily, next_due = backups.dailies(backups.listing())
    return {"on": bool(core.settings().get("auto_backup")), "kept": [f["name"] for f in daily], "next": int(next_due) if next_due else None,
            "failure": backups._auto_failure or None}


@handler
def backups_auto_get(args):
    """GET /backups/auto: the Backups page's daily backup."""
    return daily_view()


@handler
def backups_auto_set(args):
    """PUT /backups/auto: the daily backup's switch."""
    backups.set_auto(args["on"])
    return daily_view()


@handler
def backup_download(args):
    """GET /backups/{backup}/download: the Backups page's download."""
    return send_file(backups.backup_path(args["backup"]), as_attachment=True, mimetype="application/gzip", download_name=args["backup"])


@handler
def backup_restore(args):
    """POST /backups/{backup}/restore: the Backups page's Restore, the same job (backups.start_restore): a restore can
    take longer than a request may wait. What the page would say goes into the job's log, in English."""
    return started(backups.start_restore(args["backup"]))


@handler
def backup_delete(args):
    """DELETE /backups/{backup}: the Backups page's Delete."""
    backups.delete(args["backup"])
    return {"deleted": args["backup"]}


# ------------------------------------------------------------------------------ logs

@handler
def logs_requests(args):
    """GET /logs/requests: the Logs page's Requests tab, with its filters."""
    rows, picked = logs.requests_found((args.get("q") or "").strip(), args.get("status", ""), args.get("kind", ""))
    limit = args.get("limit", logs.REQUESTS_SHOWN)
    if not 1 <= limit <= logs.REQUESTS_SHOWN:
        raise bad("bad_query", f"?limit= must be 1 to {logs.REQUESTS_SHOWN}.")
    day, last_day, covered = logs.requests_day(rows, picked)
    return {"items": [{"at": int(r["at"]), "address": r["ip"], "method": r["method"], "path": r["path"], "status": r["status"], "size": r["size"],
                       "referrer": r["ref"], "agent": r["ua"], "kind": r["kind"], "device": r["device"], "line": r["line"]}
                      for r in picked[-limit:][::-1]],
            "matched": len(picked), "kept": len(rows), "covered_from": int(covered) if covered else None,
            "hours": [{"at": int(at), "fine": fine, "failed": failed} for at, fine, failed in day],
            "top_paths": [{"name": p, "requests": n} for p, n in insights.top_pages(last_day)],
            "top_devices": [{"name": d, "requests": n} for d, n in insights.top(last_day, "device")],
            "top_addresses": [{"name": ip, "requests": n} for ip, n in insights.top(last_day, "ip")]}


@handler
def logs_requests_download(args):
    """GET /logs/requests/download: the Requests tab's download, the same file."""
    return logs.logs_download()


def is_day(text):
    """True for a day of the calendar written YYYY-MM-DD (2026-02-30 is none)."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return False
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def plays_wanted(args):
    """The Plays tab's filter from the query, as the page reads its own address. A day that is none is refused here,
    where the page would only leave it out of the filter."""
    for day in ("from", "to"):
        if day in args and not is_day(args[day]):
            raise bad("bad_query", f"?{day}= must be a day, YYYY-MM-DD.")
    return logs.plays_filter({"q": args.get("q", ""), "player": str(args["player"]) if "player" in args else "",
                              "from": args.get("from"), "to": args.get("to")})


@handler
def logs_plays(args):
    """GET /logs/plays: the Logs page's Plays tab, a page at a time, with its filters. A player with no plays gives none
    (strict), where the tab lists every play."""
    wanted = plays_wanted(args)
    page = logs.plays_page_number(str(args.get("page", 1)))
    found = logs.plays_found_page(wanted, page, strict=True)
    if found["broken"]:
        raise Refused(503, "database_unavailable", plain(core.t("err.db_text")))
    # Past the last page: the last page there is, as the tab's own address leads there.
    if page > found["last_page"]:
        page = found["last_page"]
        found = logs.plays_found_page(wanted, page, strict=True)
    summed = found["summed"]
    summary = None
    if summed.n:
        summary = {"plays": summed.n, "records": summed.records, "accuracy": site.accuracy(summed.judged / summed.n), "players": len(summed.people),
                   "grades": [{"grade": g_, "plays": summed.grades[g_]} for g_ in site.GRADES if summed.grades.get(g_)],
                   "days": [{"day": d.isoformat(), "plays": n} for d, n in sorted(summed.days.items()) if n]}
    return {"items": [{"player": p["id"], "name": str(p["who"]), "song": p["song"], "chart": p["chart"], "score": p["score"], "grade": p["grade"],
                       "accuracy": site.accuracy(p["judgement"] or 0), "new_record": bool(p["new"]), "at": p["when"]} for p in found["plays"]],
            "total": found["total"], "page": page, "pages": found["last_page"],
            "players": [{"id": guid, "name": name} for guid, name in found["people"]], "summary": summary}


@handler
def logs_plays_download(args):
    """GET /logs/plays/download: the Plays tab's spreadsheet of what its filters find; a player with no plays gives an
    empty one (strict)."""
    wanted = plays_wanted(args)
    with db() as con:
        return logs.plays_file(con, wanted, strict=True)


@handler
def logs_changes(args):
    """GET /logs/changes: the Logs page's Changes tab."""
    return {"items": [{"at": c["at"], "what": c["what"], "words": plain(c["words"]), "target": str(c["target"]), "who": c["who"]}
                      for c in logs.changes()]}


# ------------------------------------------------------------------------------ the setup

@handler
def setup_get(args):
    """GET /setup: where the setup is: each step done or not, and what each step's page shows."""
    done = setup.steps_done()
    client = setup.base_client()
    has_data = songs.has_game_data()
    offer = next((b for b in apps.builds() if b["current"]), None)
    failed = apps.build_error()
    return {
        "steps": done, "next": next((s for s in setup.STEPS if not done[s]), None), "host_install": setup.HOST_INSTALL,
        "kubernetes": setup.IN_KUBERNETES,
        "files": {"client": client["name"] if client and client["name"] else None,
                  "client_says": plain(setup.client_words(client["info"])) if client and client["name"] else None,
                  "unusable": [n for n, _ in client["unusable"]] if client and not client["name"] else [],
                  "client_data": has_data, "missing": songs.missing_game_files() if has_data else [],
                  "songs": len(song_pages.listed_catalog()) if has_data else 0,
                  # The places the files step's picker goes to in one step, where the page shows them: on the server PC.
                  "places": setup.places() if setup.HOST_INSTALL else []},
        "address": {"address": core.PUBLIC_HOST, "port": setup.address_parts(core.PUBLIC_HOST)[1],
                    "choices": setup.this_pcs_addresses() if setup.HOST_INSTALL else []},
        "accounts": auth.accounts_count()[0] or 0,
        "app": {"on_offer": build_view(offer) if offer else None, "build_error": plain(failed) if failed else None,
                "building": bool(jobs.running_build()) or setup.builder_running(), "client": setup.has_base_apk(),
                "runtime": setup.runtime_in_place(), "runtime_error": setup.runtime_failure() or None,
                "qr": os.path.isfile(os.path.join(core.APK, "out", "download-qr.svg"))},
    }


def host_only():
    """Refused where the setup cannot look at the server PC's folders: anywhere but a host install."""
    if not setup.HOST_INSTALL:
        raise Refused(404, "host_only", message=setup.HOST_ONLY)


@handler
def setup_found(args):
    """GET /setup/found: the files the setup finds on the server PC (a host install only, as the setup's search)."""
    host_only()
    return {"items": [{"path": h["path"], "apps": h["apks"], "archives": h["archives"], "iphone": h["iphone"], "folder": h["tree"],
                       "folder_kind": h["tree_kind"], "songs_folder": h["songs_tree"], "parts": h["parts"]} for h in setup.found_on_this_pc()]}


@handler
def setup_folder(args):
    """GET /setup/folder: the setup's folder picker, one folder at a time (a host install only)."""
    host_only()
    # A path on another computer is refused here (400 network_path), before anything looks at it.
    path = setup.clean_path(args.get("path", "")) or setup.default_folder()
    picked = None
    # A file's path opens its folder, with the file marked, as the picker does.
    if os.path.isfile(path):
        picked, path = os.path.basename(path), os.path.dirname(path)
    listed = setup.listing(path)
    if listed is None:
        # Why, as the page says it, and the folder the page opens instead.
        raise Refused(404, "cannot_open", plain(core.t("setup.not_there" if not os.path.exists(path) else "setup.cannot_open_path", path=path)),
                      nearest=setup.nearest_open(path))
    return {"path": listed["path"], "parent": listed["parent"], "folders": [{"name": n, "path": p} for n, p in listed["folders"]],
            "files": [{"name": n, "size": size, "path": p, "parts": listed["parts"].get(n, 0)} for n, size, p in listed["files"]],
            "more": listed["more"], "folder": listed["tree"], "folder_kind": listed["tree_kind"], "songs_folder": listed["songs_tree"],
            "picked": picked, "places": setup.places()}


@handler
def setup_what(args):
    """GET /setup/what: what the setup says of a path before it is imported (a host install only)."""
    host_only()
    path = setup.clean_path(args["path"])
    try:
        w = setup.what_is(path)
        return {"path": path, "ok": bool(w and w["ok"]), "text": plain(setup.what_words(w))}
    except Exception:  # noqa: BLE001 - a file nobody foresaw, as on the page
        app.logger.exception("api setup/what")
        return {"path": path, "ok": False, "text": plain(core.t("setup.what_error"))}


@handler
def setup_import(args):
    """POST /setup/import: the setup's Import (setup.import_files), the same job. The Songs page's import of the song
    data from a folder is this one too."""
    return started(setup.import_files(args["path"], args.get("songs", True)))


@handler
def setup_address(args):
    """PUT /setup/address: the setup's address step (setup.change_address). The server starts again: 202, with the
    instance that changes once it has."""
    new = setup.change_address(args["address"])
    return {"address": new, "restarting": True, "instance": setup.STARTED}, 202


@handler
def setup_player(args):
    """POST /setup/player: the setup's first player (setup.make_player), with the password and the message to send."""
    name = (args["name"] or "").strip()
    return with_password(name, setup.make_player(name)), 201


@handler
def setup_build(args):
    """POST /setup/build: the setup's app step (setup.start_build)."""
    return started(setup.start_build())


# ------------------------------------------------------------------------------ the players' site

@handler
def site_home(args):
    """GET /site/home: what the site's home page shows (index.php)."""
    with db() as con:
        return site.home(con)


@handler
def site_songs(args):
    """GET /site/songs: the site's song list (songs.php)."""
    # As the site: the songs without counts while the database cannot be read.
    try:
        with db() as con:
            return {"items": site.song_page_list(con)}
    except sqlite3.Error:
        return {"items": site.song_page_list(None)}


@handler
def site_song(args):
    """GET /site/songs/{song}: a song's page on the site (song.php): its charts, with each one's best."""
    with db() as con:
        page = site.song_page(con, args["song"])
    if not page:
        raise Refused(404, "song_not_found", message=f"There is no song {args['song']}.")
    return page


@handler
def site_chart_ranking(args):
    """GET /site/charts/{chart}/ranking: a chart's leaderboard, as song.php shows it."""
    with db() as con:
        b = site.board(con, args["chart"])
    if not b:
        raise Refused(404, "chart_not_found", message=f"There is no chart {args['chart']}.")
    return b


@handler
def site_rankings(args):
    """GET /site/rankings: the site's rankings (ranking.php), in the order asked."""
    with db() as con:
        return site.rankings(con, args.get("sort", "total"))


@handler
def site_rankings_month(args):
    """GET /site/rankings/month: this month's ranking, as the game ranks it, and the months before."""
    with db() as con:
        out = site.rankings(con, "month")
    return {"items": out["items"], "starts_anew": out["starts_anew"], "past_months": out["past_months"]}


@handler
def site_player(args):
    """GET /site/players/{player}: a player's page on the site (player.php)."""
    with db() as con:
        page = site.player_page(con, args["player"])
    if not page:
        raise Refused(404, "player_not_found", message=f"There is no player {args['player']}.")
    return page


@handler
def site_player_records(args):
    """GET /site/players/{player}/records: a player's best on each chart, as player.php lists them."""
    with db() as con:
        items = site.player_records(con, args["player"])
    if items is None:
        raise Refused(404, "player_not_found", message=f"There is no player {args['player']}.")
    return {"items": items}


@handler
def site_plays_recent(args):
    """GET /site/plays/recent: the site's newest plays; only new records, or one player's, when asked."""
    limit = args.get("limit", 20)
    if not 1 <= limit <= 100:
        raise bad("bad_query", "?limit= must be 1 to 100.")
    with db() as con:
        return {"items": site.recent_plays(con, limit, bool(args.get("records")), args.get("player"))}


@handler
def site_live(args):
    """GET /site/live: the site's broadcasts (live.php): who is on air now, and the past ones players may watch, with the
    sign of that list the live page compares (past_rev, as live.php?list=1 gives it)."""
    with db() as con:
        past = site.live_past(con)
        # With broadcasts off for the server the site shows none, and says why. The sign is of the list sent, as the site's
        # is with the list: the two always go together.
        return {"on": recordings.live_settings()["on"], "live": site.live_now(con), "past": past, "past_rev": site.past_rev(past)}


@handler
def site_live_file(args):
    """GET /site/live/{player}/files/{part}: a broadcast's playlist and segments, as live-media.php gives them to
    the site."""
    guid, part = args["player"], args["part"]
    # Exactly the two shapes live-media.php takes: nothing else of the folder comes out.
    if not re.fullmatch(r"index\.m3u8|\d{1,12}\.ts", part):
        raise Refused(404, "not_found", message="No such file.")
    with db() as con:
        try:
            on = con.execute("SELECT live FROM LiveSwitch WHERE guid = ?", (guid,)).fetchone()
        except sqlite3.OperationalError:
            on = None
    # Once the owner switches the broadcast off, or broadcasts for the whole server, nothing more is shown, also of what is
    # still on disk.
    path = os.path.join(recordings.live_folder(guid), part)
    if not (on and on[0]) or not recordings.live_settings()["on"] or not os.path.isfile(path):
        raise Refused(404, "not_found", message="That broadcast is off, or the file is not there.")
    if part != "index.m3u8":
        return send_file(path, mimetype="video/mp2t", max_age=60)
    with open(path, encoding="utf-8") as f:
        playlist = f.read()
    # A phone that went silent never says the stream ended: after a while players are told, instead of waiting for more.
    if site.live_stopped(guid):
        playlist += "#EXT-X-ENDLIST\n"
    return app.response_class(playlist, mimetype="application/vnd.apple.mpegurl")


register()
