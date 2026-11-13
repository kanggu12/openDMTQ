"""Tests for the HTTP API (admin/api.py, docs/api.md): its tokens, every route's answer and at least one refusal of each,
a job followed to its end, uploads and downloads, the OpenAPI document against the routes Flask has, and the table of
every admin page's action and every page of the players' site with the routes that do the same.

Flask is installed in the tools image only; outside it these tests are skipped (CI runs them there)."""

import ast
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import threading
import time
import types
import unittest
import urllib.parse
import zipfile
from unittest import mock

from tests.test_admin import HAVE_FLASK, HOST, Install, member_rows, old_game_database, page_token

if HAVE_FLASK:
    from werkzeug.exceptions import NotFound

    from opendmtq_tools import admin
    from opendmtq_tools.admin import api, api_routes, setup, tokens
    from tests.test_song_files import chart, fpk, jacket

V1 = "/opendmtq/api/v1"
TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADMIN_DIR = os.path.join(TOOLS, "opendmtq_tools", "admin")
PORTAL = os.path.join(TOOLS, "..", "server", "portal")


# ------------------------------------------------------------------------------ a server to ask

def now():
    return int(time.time())


class Server(Install):
    """A server with something of everything, made once (Server.make) and copied for each test: players and plays, the
    songs, two builds, two recordings (one still being made), a backup, a request log, accounts and tokens."""

    template = None
    secrets = {}
    names = {}

    def __init__(self):
        super().__init__()
        # The template's files, when there is one: each test starts from the same server.
        if Server.template:
            shutil.copytree(Server.template, self.root, dirs_exist_ok=True)

    def __enter__(self):
        super().__enter__()
        self._more = mock.patch.multiple(admin.core, LOGS=self.path("state/logs"))
        self._more.start()
        self._content = mock.patch.object(admin.songs, "CONTENT", self.path("content"))
        self._content.start()
        # What earlier tests left in memory: throttled addresses, refused tokens noted, jobs, a held restore.
        admin.auth._failures.clear()
        admin.auth._all_failures.clear()
        api._refused_noted.clear()
        admin.jobs._jobs.clear()
        admin.status._disk_cache.clear()
        return self

    def __exit__(self, *exc):
        self._content.stop()
        self._more.stop()
        # Nothing of this server stays in memory for the tests after it: wrong tokens counted by the sign-in throttle
        # would keep the next tests' sign-ins out.
        admin.auth._failures.clear()
        admin.auth._all_failures.clear()
        api._refused_noted.clear()
        return super().__exit__(*exc)

    def ask(self, method, path, token="owner", **kw):
        """A request to the API with one of the server's tokens (by its name in secrets), a token as it is, or none."""
        headers = dict(kw.pop("headers", {}))
        if token:
            headers["Authorization"] = "Bearer " + Server.secrets.get(token, token)
        return self.client.open(V1 + path, method=method, headers=headers, **kw)

    @classmethod
    def make(cls):
        """The template: built in a server of its own, its files kept in a folder for the whole run."""
        kept = tempfile.mkdtemp()
        with Install() as inst:
            with mock.patch.object(admin.songs, "CONTENT", inst.path("content")), mock.patch.object(admin.core, "LOGS", inst.path("state/logs")):
                cls.fill(inst)
            shutil.copytree(inst.root, kept, dirs_exist_ok=True)
        cls.template = kept

    @classmethod
    def fill(cls, inst):
        db = admin.core.DB
        # Players: Sena (7) and Yuna (8) have played; 9 has no name yet.
        old_game_database(db, [(11, 7, 900000, "S", "Y", "N", 950), (12, 7, 800000, "A", "N", "N", 900), (11, 8, 700000, "B", "N", "N", 850)])
        member_rows(db, [(7, "Sena", "phone-a"), (8, "Yuna", "phone-b"), (9, "", "phone-c")])
        con = sqlite3.connect(db)
        admin.backups.bring_schema_up_to_date(con)
        t = now()
        con.executemany("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [(7, 11, 900000, "S", 950, 1, t - 3600), (7, 12, 800000, "A", 900, 1, t - 7200), (8, 11, 700000, "B", 850, 1, t - 600),
                         (8, 11, 600000, "C", 800, 0, t - 86400 * 3)])
        con.commit()
        con.close()
        # The songs: two imported, with three charts; one added as a package.
        os.makedirs(inst.path("content"))
        inst.write("content/songs.json", json.dumps([
            {"song_id": 1, "name": "paperplanes", "full_name": "Paper Planes", "artist_name": "Ann", "genre": "Pop",
             "song_patterns": [{"pattern_id": 11, "line": 3, "signature": 1, "difficulty": 3}, {"pattern_id": 12, "line": 5, "signature": 2, "difficulty": 7}]},
            {"song_id": 2, "name": "neonrain", "full_name": "Neon Rain", "artist_name": "Bo", "genre": "Rock",
             "song_patterns": [{"pattern_id": 21, "line": 4, "signature": 3, "difficulty": 9}]}]))
        os.makedirs(inst.path("custom/songs/1001"))
        # As add_package writes it: every text field, and the charts with their ids.
        inst.write("custom/songs/1001/song.json", json.dumps({
            "song_id": 1001, "name": "mysong", "has_video": False, "has_preview": False, "full_name": "My Song", "genre": "Pop",
            "artist_name": "Me", "composed_by": "", "singer": "", "feat_by": "", "arranged_by": "", "visualized_by": "",
            "charts": [{"pattern_id": 20001, "line": 5, "signature": 1, "difficulty": 4}]}))
        # The app: the one on offer for this address, one for another, the QR code and the icon; a client to build from.
        inst.app_for(HOST)
        inst.write("apk/out/OpenDMTQ-other.apk", "other app")
        inst.write("apk/out/OpenDMTQ-other.apk.json", json.dumps({"file": "OpenDMTQ-other.apk", "host": "10.0.0.5:8080", "built_at": "2026-11-01T09:00:00"}))
        inst.write("apk/out/download-qr.svg", "<svg/>")
        inst.write("apk/out/app-icon.png", "png")
        os.makedirs(inst.path("apk/base"))
        inst.write("apk/base/client.apk", "apk")
        # Recordings: Sena's, closed ten days ago; Yuna's, still being made.
        cls.names["closed"] = rid = t - 86400 * 10
        rec = admin.recordings.rec_folder(7, rid)
        os.makedirs(rec)
        for name, text in (("0.ts", "aa"), ("1.ts", "bbb"), ("index.m3u8", "#EXTM3U\n#EXTINF:2.000,\n0.ts\n#EXTINF:2.000,\n1.ts\n"),
                           ("meta.json", json.dumps({"guid": 7, "id": rid, "started": rid, "ended": rid + 4, "duration_ms": 4000, "size": 5,
                                                     "songs": [{"title": "Paper Planes", "chart": "2LINE Normal 3", "at": rid + 1}]}))):
            with open(os.path.join(rec, name), "w", encoding="utf-8") as f:
                f.write(text)
        cls.names["open"] = rid2 = t - 60
        rec2 = admin.recordings.rec_folder(8, rid2)
        os.makedirs(rec2)
        for name, text in ((".open", ""), ("segs.log", "0 2000 0 2\n"), ("meta.json", json.dumps({"guid": 8, "id": rid2, "started": rid2}))):
            with open(os.path.join(rec2, name), "w", encoding="utf-8") as f:
                f.write(text)
        # A backup, and the request log.
        cls.names["backup"] = admin.backups.make_backup("admin")
        os.makedirs(inst.path("state/logs"))
        when = time.strftime("%d/%b/%Y:%H:%M:%S +0000", time.gmtime(t - 120))
        inst.write("state/logs/access.log", "".join(
            f'203.0.113.{i} - - [{when}] "GET {path} HTTP/1.1" {code} 10 "-" "{ua}"\n'
            for i, (path, code, ua) in enumerate([("/DMQ/rpc", 200, "UnityPlayer"), ("/opendmtq/", 200, "Chrome"), ("/missing", 404, "curl/8"),
                                                  ("/DMQ/rpc", 500, "UnityPlayer")])))
        # Accounts: an admin and a player.
        admin.auth.account_create("helper", "hunter22", "", True)
        admin.auth.account_create("friend", "hunter22", "a friend")
        # Tokens: the owner's, to write and to read, and the helper's.
        with admin.app.test_request_context():
            helper = admin.auth.account_find("helper")
            for name, scope, who in (("owner", "write", ("admin", True, None)), ("reader", "read", ("admin", True, None)),
                                     ("helper", "write", ("helper", False, helper["created_at"]))):
                row, secret = tokens.make(name, scope, who)
                cls.secrets[name] = secret
                cls.names["token:" + name] = row["id"]


def setUpModule():
    if HAVE_FLASK:
        Server.make()


def tearDownModule():
    if HAVE_FLASK and Server.template:
        shutil.rmtree(Server.template, ignore_errors=True)


# ------------------------------------------------------------------------------ what an answer must be

def shape_problems(value, kind, where="answer"):
    """How value differs from the route table's type kind (api_routes): its fields one by one, none left out that is not
    optional, none more than the shape has. [] when it is what the table says."""
    out = []
    if kind.startswith("[") and kind.endswith("]"):
        if not isinstance(value, list):
            return [f"{where}: not a list"]
        for i, item in enumerate(value):
            out += shape_problems(item, kind[1:-1], f"{where}[{i}]")
        return out
    if kind.startswith("{") and kind.endswith("}"):
        if not isinstance(value, dict):
            return [f"{where}: not an object"]
        for k, item in value.items():
            out += shape_problems(item, kind[1:-1], f"{where}.{k}")
        return out
    basic = {"string": lambda v: isinstance(v, str), "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
             "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool), "boolean": lambda v: isinstance(v, bool),
             "object": lambda v: isinstance(v, dict)}
    if kind in basic:
        return [] if basic[kind](value) else [f"{where}: {value!r} is not {kind}"]
    shape = api_routes.SHAPES[kind]
    if not isinstance(value, dict):
        return [f"{where}: not an object ({kind})"]
    names = {f.name for f in shape.fields}
    if not shape.open:
        out += [f"{where}.{k}: not in {kind}" for k in set(value) - names]
    for f in shape.fields:
        if f.name not in value:
            if not f.optional:
                out.append(f"{where}.{f.name}: missing")
            continue
        v = value[f.name]
        if v is None:
            if not f.nullable:
                out.append(f"{where}.{f.name}: null")
            continue
        if f.enum and v not in f.enum:
            out.append(f"{where}.{f.name}: {v!r} not one of {f.enum}")
        out += shape_problems(v, f.type, f"{where}.{f.name}")
    return out


def song_package(**files):
    """A song package whose files pass their checks (test_song_files makes them), files replaced or added by name."""
    meta = {"name": "newsong", "full_name": "New Song", "charts": [{"line": 5, "signature": 1, "difficulty": 4, "file": "patterns/a"}]}
    members = {"song.json": json.dumps(meta).encode(), "song.fpk": fpk(), "jacket.png": jacket(), "patterns/a": chart()}
    members.update(files)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return out.getvalue()


def quick_jobs(lines=("one", "two")):
    """start_job with its command swapped for one that prints lines and ends: the job without the build."""
    real = admin.jobs.start_job

    def start(kind, cmd, env=None, explain=None, **details):
        return real(kind, [sys.executable, "-c", f"print({chr(10).join(lines)!r})"], env=env, explain=explain, **details)
    return mock.patch.object(admin.jobs, "start_job", start)


def wait_job(inst, job_id, seconds=20):
    """A job, asked for through the API until it is no longer running."""
    end = time.time() + seconds
    while time.time() < end:
        job = inst.ask("GET", f"/jobs/{job_id}").get_json()["job"]
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still running")


def healthy(**fields):
    """The game server's health answer of a server that is well."""
    return {"ok": True, "host": HOST, "songs": 2, "game_data": True, "patch": "1.003.005", "database": True, "players": 3, "apk": None,
            "apk_matches_host": True, "https": False, "role": "api", "writable": True, **fields}


def host_install(inst):
    """The setup's pages as a host install has them: its run folder, its .env and a home folder to look in."""
    for d in ("run", "home/Downloads/game", "home/Desktop"):
        os.makedirs(inst.path(d), exist_ok=True)
    inst.write(".env", f"PUBLIC_HOST={HOST}\nADMIN_PASSWORD=pw\n")
    return [mock.patch.multiple(setup, HOST_INSTALL=True, ENV_FILE=inst.path(".env"), RUN_DIR=inst.path("run"), SIGNIN_FILE=inst.path("run/signin.token")),
            mock.patch.dict(os.environ, {"HOME": inst.path("home"), "USERPROFILE": inst.path("home")})]


# ------------------------------------------------------------------------------ every route

def C(route, method, path, status, code=None, token="owner", setup=None, check=None, **kw):
    """A case: one request to route, the status and refusal code it must answer, what to do first (setup: a function of
    the server, returning patches to hold during the request), and what else to check of the answer (check)."""
    return {"route": route, "method": method, "path": path, "status": status, "code": code, "token": token, "setup": setup, "check": check, "kw": kw}


def no_rebuild(inst):
    return [mock.patch.object(admin.songs, "rebuild")]


def broken_database(inst):
    """A database turned to noise from its start: it opens, and nothing can be read of it."""
    with open(admin.core.DB, "r+b") as f:
        f.write(b"\xff" * 8192)
    return []


def helper_disabled(inst):
    """The helper's account switched off, as another admin would."""
    with sqlite3.connect(admin.core.DB) as con:
        con.execute("UPDATE SiteUser SET off = 1 WHERE name = 'helper'")
    return []


def throttled(inst):
    """This address, after as many wrong passwords as the throttle lets through."""
    for _ in range(admin.auth.PER_IP):
        admin.auth.note_failure("127.0.0.1")
    return []


def restoring(inst):
    """A restore under way: its lock held (run_case gives it back)."""
    admin.backups._restoring.acquire()
    return []


def CASES():
    """Every route's usual answer, and its refusals."""
    closed, opened, backup = Server.names["closed"], Server.names["open"], Server.names["backup"]

    def everyone_touched():
        # (new players start on, the players with no choice of the owner on record): none left after the turn.
        with sqlite3.connect(admin.core.DB) as con:
            players = {r[0] for r in con.execute(admin.core.PLAYER_ROWS, (admin.core.CHECK_UDID,))}
            chosen = {r[0] for r in con.execute("SELECT guid FROM LiveSwitch WHERE changed_at IS NOT NULL")}
        return admin.recordings.live_settings()["new_players"], players - chosen

    def settings(**values):
        # The broadcast settings as the Broadcasts page leaves them: rows of LiveSetting in the database.
        with sqlite3.connect(admin.core.DB) as con:
            admin.recordings.setting_rows(con)
            admin.recordings.write_settings(con, values)
        return []

    def broadcasts_on(inst):
        # Broadcasts on for the server, as the Broadcasts page leaves them (off until then).
        return settings(on=True)

    def broadcasts_off(inst):
        # Broadcasts off for the server, as the owner left them: a server with a player switched on and settings that say
        # nothing yet is one from before the switch, on.
        return settings(on=False)

    def on_air(inst):
        # Yuna's switch on, with a live window that has video, while broadcasts are on.
        broadcasts_on(inst)
        with sqlite3.connect(admin.core.DB) as con:
            con.row_factory = sqlite3.Row
            admin.recordings.live_set(con, 8, True)
        folder = admin.recordings.live_folder(8)
        os.makedirs(folder, exist_ok=True)
        for name, text in (("index.m3u8", "#EXTM3U\n#EXTINF:2.000,\n0.ts\n"), ("0.ts", "seg"),
                           ("stream.json", json.dumps({"ended": False, "updated": now(), "rec": now() - 30}))):
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                f.write(text)
        return []

    def disabled_friend(inst):
        with sqlite3.connect(admin.core.DB) as con:
            con.execute("UPDATE SiteUser SET off = 1 WHERE name = 'friend'")
        return []

    def no_icon(inst):
        os.remove(inst.path("apk/out/app-icon.png"))
        return []

    def with_windows(inst, size=3):
        # The installer for Windows beside the app, as the builder leaves it (windows_client.py): the file, and windows.json
        # describing it at `size`.
        inst.write("apk/out/OpenDMTQ-Setup.exe", "MZ!")
        inst.write("apk/out/windows.json", json.dumps({"file": "OpenDMTQ-Setup.exe", "size": size, "sha256": "0", "version": "0.8.0",
                                                       "copied_at": "2026-11-09T12:00:00"}))
        return []

    def with_windows_half_copied(inst):
        # windows.json says another size than the file has: a copy cut off, which is not handed out.
        return with_windows(inst, size=4)

    def no_qr(inst):
        os.remove(inst.path("apk/out/download-qr.svg"))
        return []

    def offer_unknown(inst):
        inst.write("apk/out/latest.json", "{}")
        return []

    def a_job(inst):
        Server.names["job"] = admin.jobs.start_task("restore", lambda say: say("done"), backup="x.tar.gz")
        return []

    def password_works(t, inst, r):
        t.assertTrue(admin.auth.account_pass_ok(admin.auth.account_find("friend")["pass"], r.get_json()["password"]))

    cases = [
        C("openapi", "GET", "/openapi.json", 200, token=None),
        C("openapi", "POST", "/openapi.json", 405, "method_not_allowed"),
        C("status", "GET", "/status", 200),
        C("status_health", "GET", "/status/health", 200, setup=lambda inst: [mock.patch.object(admin.core, "server_health", lambda fresh=False: healthy())]),
        C("status_health", "GET", "/status/health", 503, "server_down"),
        C("status_health", "GET", "/status/health", 503, "server_unwell",
          setup=lambda inst: [mock.patch.object(admin.core, "server_health", lambda fresh=False: healthy(ok=False, writable=False))]),
        C("status_machine", "GET", "/status/machine", 200),
        C("status_activity", "GET", "/status/activity", 200),
        C("jobs_list", "GET", "/jobs", 200),
        C("job_get", "GET", "/jobs/{job}", 200, setup=a_job),
        C("job_get", "GET", "/jobs/nope", 404, "job_not_found"),
        C("app_get", "GET", "/app", 200, check=lambda t, inst, r: t.assertEqual(r.get_json()["state"], "fits")),
        C("app_get", "GET", "/app", 200, setup=with_windows,
          check=lambda t, inst, r: t.assertEqual((r.get_json()["windows"]["file"], r.get_json()["windows"]["version"]), ("OpenDMTQ-Setup.exe", "0.8.0"))),
        C("app_get", "GET", "/app", 200, setup=with_windows_half_copied,
          check=lambda t, inst, r: t.assertIsNone(r.get_json()["windows"])),
        # The installer as the site hands it out: the file, then this server's address on its end.
        C("app_windows", "GET", "/app/windows", 200, setup=with_windows,
          check=lambda t, inst, r: (t.assertTrue(r.data.startswith(b"MZ!")), t.assertTrue(r.data.endswith(b"OPENDMTQ-PRESET1")),
                                    t.assertIn(b'"url":"http://', r.data))),
        C("app_windows", "GET", "/app/windows", 404, "not_found"),
        C("app_windows", "GET", "/app/windows", 404, "not_found", setup=with_windows_half_copied),
        # A broken download goes on where it stopped (InstallerDownloadTest has the rest): a part, another file, past the end.
        C("app_windows", "GET", "/app/windows", 206, setup=with_windows, headers={"Range": "bytes=0-1"},
          check=lambda t, inst, r: (t.assertEqual(r.data, b"MZ"), t.assertTrue(r.headers["Content-Range"].startswith("bytes 0-1/")))),
        C("app_windows", "GET", "/app/windows", 412, "precondition_failed", setup=with_windows, headers={"If-Match": '"another"'}),
        C("app_windows", "GET", "/app/windows", 416, "range_not_satisfiable", setup=with_windows, headers={"Range": "bytes=100000-"},
          check=lambda t, inst, r: t.assertRegex(r.headers["Content-Range"], r"^bytes \*/\d+$")),
        C("app_icon", "GET", "/app/icon", 200),
        C("app_icon", "GET", "/app/icon", 404, "not_found", setup=no_icon),
        C("builds_list", "GET", "/builds", 200, check=lambda t, inst, r: t.assertEqual(len(r.get_json()["items"]), 2)),
        C("builds_start", "POST", "/builds", 202, json={}, setup=lambda inst: [quick_jobs()]),
        C("builds_start", "POST", "/builds", 400, "bad_host", json={"host": "no such host!"}),
        C("builds_start", "POST", "/builds", 409, "no_client", setup=lambda inst: [mock.patch.object(admin.core, "APK", inst.path("nowhere"))]),
        # An import running: refused in the setup's own words (BuildTest has the real job).
        C("builds_start", "POST", "/builds", 409, "busy", setup=lambda inst: [mock.patch.object(setup, "busy", lambda: admin.core.t("setup.importing"))],
          check=lambda t, inst, r: t.assertEqual(r.get_json()["error"]["message"], "An import is running already: wait for it to end.")),
        C("build_get", "GET", "/builds/OpenDMTQ-x.apk", 200),
        C("build_get", "GET", "/builds/OpenDMTQ-none.apk", 404, "build_not_found"),
        C("build_download", "GET", "/builds/OpenDMTQ-x.apk/download", 200, check=lambda t, inst, r: t.assertEqual(r.data, b"app")),
        C("build_download", "GET", "/builds/..%2Fsecret.apk/download", 404, "not_found"),
        C("build_delete", "DELETE", "/builds/OpenDMTQ-other.apk", 200),
        C("build_delete", "DELETE", "/builds/OpenDMTQ-x.apk", 409, "on_offer"),
        C("builds_prune", "POST", "/builds/prune", 200, check=lambda t, inst, r: t.assertEqual(r.get_json()["deleted"], 1)),
        C("builds_prune", "POST", "/builds/prune", 409, "offer_unknown", setup=offer_unknown),
        C("invite_get", "GET", "/invite", 200, check=lambda t, inst, r: t.assertEqual(r.get_json()["url"], f"http://{HOST}/opendmtq/download.php")),
        C("invite_qr", "GET", "/invite/qr", 200),
        C("invite_qr", "GET", "/invite/qr", 404, "not_found", setup=no_qr),
        C("songs_list", "GET", "/songs", 200, check=lambda t, inst, r: t.assertEqual([s["source"] for s in r.get_json()["items"]], ["imported", "imported", "added"])),
        C("songs_add", "POST", "/songs", 201, setup=no_rebuild, data={"package": (io.BytesIO(song_package()), "new.zip")}, content_type="multipart/form-data"),
        C("songs_add", "POST", "/songs", 400, "no_package", data={"package": (io.BytesIO(b"x"), "new.txt")}, content_type="multipart/form-data"),
        C("songs_add", "POST", "/songs", 422, "package_refused", setup=no_rebuild,
          data={"package": (io.BytesIO(song_package(**{"patterns/a": b"not a chart"})), "bad.zip")}, content_type="multipart/form-data"),
        C("song_get", "GET", "/songs/1", 200),
        C("song_get", "GET", "/songs/999", 404, "song_not_found"),
        C("song_hide", "POST", "/songs/1/hide", 200, setup=no_rebuild),
        C("song_hide", "POST", "/songs/999/hide", 404, "song_not_found", setup=no_rebuild),
        C("song_show", "POST", "/songs/1/show", 200, setup=no_rebuild),
        C("song_show", "POST", "/songs/1/show", 403, "read_only", token="reader"),
        C("song_remove", "DELETE", "/songs/1001", 200, setup=no_rebuild),
        C("song_remove", "DELETE", "/songs/1", 409, "not_added", setup=no_rebuild),
        C("song_remove", "DELETE", "/songs/999", 404, "song_not_found", setup=no_rebuild),
        C("maintenance_get", "GET", "/maintenance", 200),
        C("maintenance_set", "PUT", "/maintenance", 200, json={"message": "Back at nine."},
          check=lambda t, inst, r: t.assertEqual(r.get_json(), {"on": True, "message": "Back at nine."})),
        C("maintenance_set", "PUT", "/maintenance", 400, "bad_field", json={"message": 5}),
        # One limit, the page's: 200 characters, a line break one of them; over it, refused in the page's words.
        C("maintenance_set", "PUT", "/maintenance", 200, json={"message": "x" * 95 + "\r\n" * 10 + "x" * 95},
          check=lambda t, inst, r: t.assertEqual(r.get_json()["message"], "x" * 95 + "\n" * 10 + "x" * 95)),
        C("maintenance_set", "PUT", "/maintenance", 400, "message_too_long", json={"message": "x" * 201},
          check=lambda t, inst, r: t.assertEqual(r.get_json()["error"]["message"], "The message is longer than 200 characters.")),
        C("maintenance_set", "PUT", "/maintenance", 400, "bad_json", data="message=x", content_type="application/x-www-form-urlencoded"),
        C("maintenance_clear", "DELETE", "/maintenance", 200),
        C("maintenance_clear", "DELETE", "/maintenance", 403, "read_only", token="reader"),
        C("server_stop", "POST", "/server/stop", 202, setup=host_install, check=lambda t, inst, r: t.assertTrue(os.path.exists(inst.path("run/stop.request")))),
        C("server_stop", "POST", "/server/stop", 404, "host_only"),
        C("players_list", "GET", "/players", 200, check=lambda t, inst, r: t.assertEqual([p["name"] for p in r.get_json()["items"]], ["Sena", "Yuna", "Player 9"])),
        C("players_download", "GET", "/players/download", 200, check=lambda t, inst, r: t.assertTrue(r.data.startswith(b"\xef\xbb\xbfid,name"))),
        C("player_get", "GET", "/players/7", 200),
        C("player_get", "GET", "/players/99", 404, "player_not_found"),
        C("player_rename", "POST", "/players/7/rename", 200, json={"name": "Riku"}, check=lambda t, inst, r: t.assertEqual(r.get_json()["player"]["name"], "Riku")),
        C("player_rename", "POST", "/players/7/rename", 409, "same_name", json={"name": "Sena"}),
        C("player_rename", "POST", "/players/7/rename?seen=old", 409, "stale", json={"name": "Riku"}),
        C("player_rename", "POST", "/players/7/rename", 400, "bad_field", json={}),
        # Over 20 characters: refused here, where the page cuts it; 20 is taken whole.
        C("player_rename", "POST", "/players/7/rename", 400, "bad_field", json={"name": "x" * 21},
          check=lambda t, inst, r: t.assertIn("longer than 20", r.get_json()["error"]["message"])),
        C("player_rename", "POST", "/players/7/rename", 200, json={"name": "y" * 20},
          check=lambda t, inst, r: t.assertEqual(r.get_json()["player"]["name"], "y" * 20)),
        C("player_reset", "POST", "/players/7/reset", 200, check=lambda t, inst, r: t.assertEqual(r.get_json()["player"]["charts"], 0)),
        C("player_reset", "POST", "/players/99/reset", 404, "player_not_found"),
        C("player_delete", "DELETE", "/players/8", 200),
        C("player_delete", "DELETE", "/players/99", 404, "player_not_found"),
        C("player_live_on", "POST", "/players/7/live", 200, setup=broadcasts_on,
          check=lambda t, inst, r: t.assertEqual(r.get_json()["player"]["broadcast"], "waiting")),
        # With broadcasts off for the server, the switch is kept for then.
        C("player_live_on", "POST", "/players/7/live", 200, setup=broadcasts_off,
          check=lambda t, inst, r: t.assertEqual(r.get_json()["player"]["broadcast"], "held")),
        C("player_live_on", "POST", "/players/99/live", 404, "player_not_found"),
        C("player_live_off", "DELETE", "/players/7/live", 200),
        C("player_live_off", "DELETE", "/players/7/live?seen=0123456789abcdef", 409, "stale"),
        C("accounts_list", "GET", "/accounts", 200, check=lambda t, inst, r: t.assertEqual([a["name"] for a in r.get_json()["items"]], ["friend", "helper"])),
        C("accounts_create", "POST", "/accounts", 201, json={"name": "newbie", "player": 7},
          check=lambda t, inst, r: t.assertTrue(re.fullmatch(r"[a-z2-9]{10}", r.get_json()["password"]))),
        C("accounts_create", "POST", "/accounts", 400, "bad_id", json={"name": "a b"}),
        C("accounts_create", "POST", "/accounts", 409, "id_taken", json={"name": "FRIEND", "password": "hunter22"}),
        C("accounts_create", "POST", "/accounts", 400, "bad_player", json={"name": "newbie", "player": 999}),
        # With admin rights a typed password is 10 at least; one made is as long.
        C("accounts_create", "POST", "/accounts", 400, "bad_password", json={"name": "newbie", "password": "hunter222", "admin": True}),
        C("accounts_create", "POST", "/accounts", 201, json={"name": "newbie", "password": "hunter2222", "admin": True},
          check=lambda t, inst, r: t.assertTrue(r.get_json()["account"]["admin"])),
        # A note over 40 characters: refused, where the page cuts it.
        C("accounts_create", "POST", "/accounts", 400, "bad_field", json={"name": "newbie", "note": "n" * 41}),
        C("accounts_create", "POST", "/accounts", 201, json={"name": "newbie", "note": "n" * 40},
          check=lambda t, inst, r: t.assertEqual(r.get_json()["account"]["note"], "n" * 40)),
        C("account_get", "GET", "/accounts/Friend", 200),
        C("account_get", "GET", "/accounts/nobody", 404, "account_not_found"),
        C("account_password", "POST", "/accounts/friend/password", 200, check=password_works),
        C("account_password", "POST", "/accounts/nobody/password", 404, "account_not_found"),
        C("account_disable", "POST", "/accounts/friend/disable", 200, check=lambda t, inst, r: t.assertFalse(r.get_json()["account"]["enabled"])),
        C("account_disable", "POST", "/accounts/helper/disable", 409, "own_account", token="helper"),
        C("account_enable", "POST", "/accounts/friend/enable", 200, setup=disabled_friend),
        C("account_enable", "POST", "/accounts/friend/enable", 409, "already_so"),
        C("account_make_admin", "POST", "/accounts/friend/make-admin", 200),
        C("account_make_admin", "POST", "/accounts/helper/make-admin", 409, "already_so"),
        C("account_make_player", "POST", "/accounts/helper/make-player", 200),
        C("account_make_player", "POST", "/accounts/friend/make-player", 409, "already_so"),
        C("account_link", "POST", "/accounts/friend/link", 200, json={"player": 7}, check=lambda t, inst, r: t.assertEqual(r.get_json()["account"]["player_name"], "Sena")),
        C("account_link", "POST", "/accounts/friend/link", 400, "bad_player", json={"player": 999}),
        C("account_link", "POST", "/accounts/friend/link", 409, "already_so", json={"player": None}),
        C("account_delete", "DELETE", "/accounts/friend", 200),
        C("account_delete", "DELETE", "/accounts/nobody", 404, "account_not_found"),
        C("tokens_list", "GET", "/tokens", 200, check=lambda t, inst, r: t.assertNotIn("hash", r.get_data(as_text=True))),
        C("tokens_create", "POST", "/tokens", 201, json={"name": "ci", "scope": "read"}),
        C("tokens_create", "POST", "/tokens", 400, "bad_field", json={"name": "ci", "scope": "admin"}),
        C("tokens_create", "POST", "/tokens", 400, "bad_name", json={"name": " ", "scope": "read"}),
        C("token_revoke", "DELETE", "/tokens/{token:reader}", 200),
        C("token_revoke", "DELETE", "/tokens/000000000000", 404, "token_not_found"),
        # The server's broadcasts: off until turned on, then on with a quality the phones are asked for.
        C("broadcasts_get", "GET", "/broadcasts", 200,
          check=lambda t, inst, r: t.assertEqual((r.get_json()["on"], r.get_json()["quality"], len(r.get_json()["qualities"])), (False, "standard", 4))),
        C("broadcasts_get", "GET", "/broadcasts", 401, "no_token", token=None),
        C("broadcasts_set", "PUT", "/broadcasts", 200, json={"on": True, "quality": "smooth"},
          check=lambda t, inst, r: t.assertEqual((r.get_json()["on"], r.get_json()["quality"], r.get_json()["new_players"]), (True, "smooth", False))),
        # New players starting on from now: everyone there counts as chosen for, off, as on the Broadcasts page.
        C("broadcasts_set", "PUT", "/broadcasts", 200, json={"new_players": True}, check=lambda t, inst, r: t.assertEqual(
            everyone_touched(), (True, set()))),
        C("broadcasts_set", "PUT", "/broadcasts", 400, "bad_body", json={}),
        C("broadcasts_set", "PUT", "/broadcasts", 400, "bad_field", json={"quality": "ultra"}),
        C("recordings_list", "GET", "/recordings", 200, check=lambda t, inst, r: t.assertEqual([x["open"] for x in r.get_json()["items"]], [True, False])),
        C("recordings_limits", "GET", "/recordings/limits", 200, check=lambda t, inst, r: t.assertEqual(r.get_json()["cap_gb"], 20)),
        C("recordings_set_limits", "PUT", "/recordings/limits", 200, json={"cap_gb": 50, "days": 90}),
        C("recordings_set_limits", "PUT", "/recordings/limits", 409, "would_delete", json={"cap_gb": 20, "days": 1}),
        C("recordings_set_limits", "PUT", "/recordings/limits", 400, "bad_limits", json={"cap_gb": -1, "days": 30}),
        C("recordings_set_limits", "PUT", "/recordings/limits", 400, "bad_field", json={"cap_gb": 20, "days": 1.5}),
        C("recordings_delete", "POST", "/recordings/delete", 200, json={"items": [f"7/{closed}"]}),
        C("recordings_delete", "POST", "/recordings/delete", 409, "recording_open", json={"player": 8}),
        C("recordings_delete", "POST", "/recordings/delete", 404, "recording_not_found", json={"items": ["../../x", "1/2"]}),
        C("recordings_delete", "POST", "/recordings/delete", 400, "bad_body", json={}),
        C("recording_get", "GET", f"/recordings/7/{closed}", 200,
          check=lambda t, inst, r: t.assertEqual([f["name"] for f in r.get_json()["files"]], ["index.m3u8", "0.ts", "1.ts"])),
        C("recording_get", "GET", "/recordings/7/1", 404, "recording_not_found"),
        C("recording_download", "GET", f"/recordings/7/{closed}/download", 200, check=lambda t, inst, r: t.assertEqual(r.data, b"aabbb")),
        C("recording_download", "GET", f"/recordings/8/{opened}/download", 404, "not_found"),
        C("recording_file", "GET", f"/recordings/7/{closed}/files/index.m3u8", 200),
        C("recording_file", "GET", f"/recordings/7/{closed}/files/meta.json", 404, "not_found"),
        C("recording_hide", "POST", f"/recordings/7/{closed}/hide", 200, check=lambda t, inst, r: t.assertTrue(r.get_json()["recording"]["hidden"])),
        C("recording_hide", "POST", "/recordings/7/1/hide", 404, "recording_not_found"),
        C("recording_show", "POST", f"/recordings/7/{closed}/show", 200),
        C("recording_show", "POST", "/recordings/7/1/show", 404, "recording_not_found"),
        C("recording_delete", "DELETE", f"/recordings/7/{closed}", 200),
        C("recording_delete", "DELETE", f"/recordings/8/{opened}", 409, "recording_open"),
        C("backups_list", "GET", "/backups", 200, check=lambda t, inst, r: t.assertEqual(r.get_json()["items"][0]["kind"], "hand")),
        C("backups_create", "POST", "/backups", 201),
        C("backups_create", "POST", "/backups", 409, "busy", setup=restoring),
        C("backups_upload", "POST", "/backups/upload", 201, content_type="multipart/form-data",
          data=lambda inst: {"file": (open(inst.path(f"backups/{backup}"), "rb"), "moved.tar.gz")}),
        C("backups_upload", "POST", "/backups/upload", 422, "not_backup", content_type="multipart/form-data",
          data=lambda inst: {"file": (io.BytesIO(b"\x1f\x8b\x08\x00no"), "x.tar.gz")}),
        C("backups_upload", "POST", "/backups/upload", 400, "no_file", content_type="multipart/form-data", data={}),
        C("backups_auto_get", "GET", "/backups/auto", 200, check=lambda t, inst, r: t.assertTrue(r.get_json()["on"])),
        C("backups_auto_set", "PUT", "/backups/auto", 200, json={"on": False}, check=lambda t, inst, r: t.assertFalse(r.get_json()["on"])),
        C("backups_auto_set", "PUT", "/backups/auto", 400, "bad_field", json={"on": "yes"}),
        C("backup_download", "GET", f"/backups/{backup}/download", 200, check=lambda t, inst, r: t.assertEqual(r.mimetype, "application/gzip")),
        C("backup_download", "GET", "/backups/none.tar.gz/download", 404, "backup_not_found"),
        # The accounts' password hashes and the signing key are in it: more than a read token's.
        C("backup_download", "GET", f"/backups/{backup}/download", 403, "read_only", token="reader"),
        C("backup_restore", "POST", f"/backups/{backup}/restore", 202),
        C("backup_restore", "POST", "/backups/none.tar.gz/restore", 404, "backup_not_found"),
        C("backup_restore", "POST", f"/backups/{backup}/restore", 409, "busy", setup=restoring),
        C("backup_delete", "DELETE", f"/backups/{backup}", 200),
        C("backup_delete", "DELETE", "/backups/none.tar.gz", 404, "backup_not_found"),
        C("logs_requests", "GET", "/logs/requests?status=err&kind=game", 200, check=lambda t, inst, r: t.assertEqual(r.get_json()["matched"], 1)),
        C("logs_requests", "GET", "/logs/requests?status=bad", 400, "bad_query"),
        C("logs_requests", "GET", "/logs/requests?limit=500", 400, "bad_query"),
        C("logs_requests_download", "GET", "/logs/requests/download", 200, check=lambda t, inst, r: t.assertIn(b"/missing", r.data)),
        C("logs_plays", "GET", "/logs/plays?player=7", 200, check=lambda t, inst, r: t.assertEqual(r.get_json()["total"], 2)),
        C("logs_plays", "GET", "/logs/plays?from=2026-13", 400, "bad_query"),
        # A day the calendar has not.
        C("logs_plays", "GET", "/logs/plays?to=2026-02-30", 400, "bad_query"),
        # A player with no plays gives none (the Plays tab shows every play then).
        C("logs_plays", "GET", "/logs/plays?player=9", 200, check=lambda t, inst, r: t.assertEqual((r.get_json()["total"], r.get_json()["items"]), (0, []))),
        C("logs_plays_download", "GET", "/logs/plays/download?player=8", 200, check=lambda t, inst, r: t.assertEqual(r.data.count(b"\n"), 3)),
        C("logs_plays_download", "GET", "/logs/plays/download?player=9", 200, check=lambda t, inst, r: t.assertEqual(r.data.count(b"\n"), 1)),
        C("logs_plays_download", "GET", "/logs/plays/download?player=abc", 400, "bad_query"),
        C("logs_changes", "GET", "/logs/changes", 200),
        C("setup_get", "GET", "/setup", 200, check=lambda t, inst, r: t.assertEqual((r.get_json()["next"], r.get_json()["files"]["places"]), ("files", []))),
        # On the server PC the files step's places, as the page shows them.
        C("setup_get", "GET", "/setup", 200, setup=host_install,
          check=lambda t, inst, r: t.assertEqual(r.get_json()["files"]["places"], [inst.path("home"), inst.path("home/Downloads"), inst.path("home/Desktop"), "/"])),
        C("setup_found", "GET", "/setup/found", 200, setup=host_install),
        C("setup_found", "GET", "/setup/found", 404, "host_only"),
        C("setup_folder", "GET", "/setup/folder?path=~/Downloads", 200, setup=host_install,
          check=lambda t, inst, r: t.assertEqual(([f["name"] for f in r.get_json()["folders"]], r.get_json()["places"]),
                                                 (["game"], [inst.path("home"), inst.path("home/Downloads"), inst.path("home/Desktop"), "/"]))),
        # A folder that is not there: why, and the nearest folder above it, which the page opens instead.
        C("setup_folder", "GET", "/setup/folder?path=~/Downloads/nowhere/at/all", 404, "cannot_open", setup=host_install,
          check=lambda t, inst, r: t.assertEqual(r.get_json()["error"]["nearest"], inst.path("home/Downloads"))),
        C("setup_folder", "GET", "/setup/folder?path=%5C%5Cnas%5Cshare", 400, "network_path", setup=host_install),
        C("setup_what", "GET", "/setup/what?path=~/Downloads/game", 200, setup=host_install),
        C("setup_what", "GET", "/setup/what", 400, "bad_query", setup=host_install),
        C("setup_what", "GET", "/setup/what?path=//nas/share/game.apk", 400, "network_path", setup=host_install),
        # Any folder the server can read: more than a token that only watches may look through.
        C("setup_folder", "GET", "/setup/folder?path=~/Downloads", 403, "read_only", token="reader", setup=host_install),
        C("setup_what", "GET", "/setup/what?path=~/Downloads/game", 403, "read_only", token="reader", setup=host_install),
        C("setup_import", "POST", "/setup/import", 202, json={"path": "~/Downloads/game"}, setup=lambda inst: host_install(inst) + [quick_jobs()]),
        C("setup_import", "POST", "/setup/import", 404, "path_not_found", json={"path": "~/nowhere"}, setup=host_install),
        C("setup_import", "POST", "/setup/import", 400, "network_path", json={"path": "file://nas/share/DMTQ"}, setup=host_install),
        C("setup_import", "POST", "/setup/import", 404, "host_only", json={"path": "/tmp"}),
        C("setup_address", "PUT", "/setup/address", 202, json={"address": "192.168.0.20"}, setup=host_install,
          check=lambda t, inst, r: t.assertIn("PUBLIC_HOST=192.168.0.20", open(inst.path(".env"), encoding="utf-8").read())),
        C("setup_address", "PUT", "/setup/address", 400, "bad_address", json={"address": "8.8.8.8"}, setup=host_install),
        C("setup_address", "PUT", "/setup/address", 409, "same_address", json={"address": HOST}, setup=host_install),
        C("setup_player", "POST", "/setup/player", 201, json={"name": "newbie"}),
        C("setup_player", "POST", "/setup/player", 400, "bad_id", json={"name": "x"}),
        C("setup_build", "POST", "/setup/build", 202, setup=lambda inst: [quick_jobs(), mock.patch.object(setup, "has_base_apk", lambda: True)]),
        C("setup_build", "POST", "/setup/build", 409, "no_client"),
        C("site_home", "GET", "/site/home", 200, check=lambda t, inst, r: t.assertEqual([p["name"] for p in r.get_json()["top"]], ["Sena", "Yuna"])),
        C("site_songs", "GET", "/site/songs", 200, check=lambda t, inst, r: t.assertEqual([s["title"] for s in r.get_json()["items"]], ["Neon Rain", "Paper Planes"])),
        C("site_song", "GET", "/site/songs/1", 200, check=lambda t, inst, r: t.assertEqual([c["records"] for c in r.get_json()["charts"]], [2, 1])),
        C("site_song", "GET", "/site/songs/999", 404, "song_not_found"),
        C("site_chart_ranking", "GET", "/site/charts/11/ranking", 200, check=lambda t, inst, r: t.assertEqual([p["name"] for p in r.get_json()["items"]], ["Sena", "Yuna"])),
        C("site_chart_ranking", "GET", "/site/charts/999/ranking", 404, "chart_not_found"),
        C("site_rankings", "GET", "/site/rankings?sort=s_count", 200, check=lambda t, inst, r: t.assertEqual([p["id"] for p in r.get_json()["items"]], [7])),
        C("site_rankings", "GET", "/site/rankings?sort=bogus", 400, "bad_query"),
        C("site_rankings_month", "GET", "/site/rankings/month", 200),
        C("site_player", "GET", "/site/players/7", 200, check=lambda t, inst, r: t.assertEqual((r.get_json()["rank"], r.get_json()["grades"]), (1, {"S": 1, "A": 1}))),
        C("site_player", "GET", "/site/players/99", 404, "player_not_found"),
        # A player with no plays has no average accuracy (the site shows a dash), not 0.0.
        C("site_player", "GET", "/site/players/9", 200, check=lambda t, inst, r: t.assertIsNone(r.get_json()["accuracy"])),
        C("site_player_records", "GET", "/site/players/7/records", 200, check=lambda t, inst, r: t.assertEqual(len(r.get_json()["items"]), 2)),
        C("site_player_records", "GET", "/site/players/99/records", 404, "player_not_found"),
        C("site_plays_recent", "GET", "/site/plays/recent?records=true", 200, check=lambda t, inst, r: t.assertEqual(len(r.get_json()["items"]), 3)),
        C("site_plays_recent", "GET", "/site/plays/recent?limit=0", 400, "bad_query"),
        C("site_live", "GET", "/site/live", 200, setup=on_air, check=lambda t, inst, r: t.assertEqual([p["name"] for p in r.get_json()["live"]], ["Yuna"])),
        C("site_live_file", "GET", "/site/live/8/files/index.m3u8", 200, setup=on_air),
        C("site_live_file", "GET", "/site/live/7/files/index.m3u8", 404, "not_found"),
        # The routes that read and have no refusal of their own: what every route refuses, one way or another.
        C("status", "GET", "/status", 401, "no_token", token=None),
        C("status_machine", "GET", "/status/machine", 401, "bad_token", token="odq_000000000000_" + "a" * 43),
        C("status_activity", "GET", "/status/activity", 503, "database_unavailable", setup=broken_database),
        C("jobs_list", "GET", "/jobs", 401, "token_stopped", token="helper", setup=helper_disabled),
        C("app_get", "GET", "/app", 401, "no_token", token=None),
        C("builds_list", "GET", "/builds", 401, "bad_token", token="Bearer"),
        # Throttled: a wrong token is answered 429 (a token that works never is).
        C("invite_get", "GET", "/invite", 429, "throttled", token="odq_000000000000_" + "a" * 43, setup=throttled),
        C("songs_list", "GET", "/songs", 401, "no_token", token=None),
        C("maintenance_get", "GET", "/maintenance", 503, "admin_off", setup=lambda inst: [mock.patch.object(admin.core, "PASSWORD", "")]),
        C("players_list", "GET", "/players", 503, "database_unavailable", setup=broken_database),
        C("players_download", "GET", "/players/download", 401, "no_token", token=None),
        C("accounts_list", "GET", "/accounts", 401, "token_stopped", token="helper", setup=helper_disabled),
        C("tokens_list", "GET", "/tokens", 401, "bad_token", token="odq_" + Server.names["token:owner"] + "_" + "b" * 43),
        C("recordings_list", "GET", "/recordings", 401, "no_token", token=None),
        C("recordings_limits", "GET", "/recordings/limits", 429, "throttled", token="nonsense", setup=throttled),
        C("backups_list", "GET", "/backups", 401, "no_token", token=None),
        C("backups_auto_get", "GET", "/backups/auto", 401, "bad_token", token="odq_000000000000_" + "a" * 43),
        C("logs_requests_download", "GET", "/logs/requests/download", 401, "no_token", token=None),
        C("logs_changes", "GET", "/logs/changes", 401, "token_stopped", token="helper", setup=helper_disabled),
        C("setup_get", "GET", "/setup", 503, "admin_off", setup=lambda inst: [mock.patch.object(admin.core, "PASSWORD", "")]),
        C("site_home", "GET", "/site/home", 503, "database_unavailable", setup=broken_database),
        C("site_songs", "GET", "/site/songs", 401, "no_token", token=None),
        C("site_rankings_month", "GET", "/site/rankings/month", 401, "bad_token", token="odq_000000000000_" + "a" * 43),
        C("site_live", "GET", "/site/live", 401, "no_token", token=None),
    ]
    return cases


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class RoutesTest(unittest.TestCase):
    """Every route: its usual answer, in the shape the route table gives, and its refusals, each on a server of its own."""

    def run_case(self, case):
        with Server() as inst:
            held = (case["setup"] or (lambda inst: []))(inst)
            for patch in held:
                patch.start()
            try:
                path = case["path"].replace("{job}", Server.names.get("job", "none"))
                path = re.sub(r"{token:(\w+)}", lambda m: Server.names["token:" + m.group(1)], path)
                kw = dict(case["kw"])
                if callable(kw.get("data")):
                    kw["data"] = kw["data"](inst)
                r = inst.ask(case["method"], path, token=case["token"], **kw)
                where = f'{case["method"]} {case["path"]} -> {r.status_code} {r.get_data()[:300].decode("utf-8", "replace")}'
                self.assertEqual(r.status_code, case["status"], where)
                route = api_routes.by_name()[case["route"]]
                if case["code"]:
                    self.assertEqual(r.get_json()["error"]["code"], case["code"], where)
                    self.assertEqual(shape_problems(r.get_json(), "Error"), [], where)
                    # Every refusal a route gives is one its table says it has.
                    self.assertIn(case["code"], [code for _, code, _ in api_routes.errors_of(route)] + ["method_not_allowed"], where)
                elif route.download:
                    # One of the types the table gives the route (a playlist's route gives its segments too).
                    self.assertIn(r.mimetype, route.download, where)
                elif route.answer == "object":
                    self.assertIsInstance(r.get_json(), dict)
                else:
                    self.assertEqual(shape_problems(r.get_json(), route.answer), [], where)
                    self.assertEqual(r.status_code, route.status, where)
                if case["check"]:
                    case["check"](self, inst, r)
            finally:
                for patch in held:
                    patch.stop()
                # A restore the case started ends before the next server: its thread holds the lock till then.
                for job in list(admin.jobs._jobs.values()):
                    while job["state"] == "running":
                        time.sleep(0.02)
                if admin.backups._restoring.locked() and case["setup"] is restoring:
                    admin.backups._restoring.release()

    def test_every_route_answers_and_refuses_as_its_table_says(self):
        for case in CASES():
            with self.subTest(route=case["route"], status=case["status"], code=case["code"]):
                self.run_case(case)

    def test_every_route_has_a_case_that_works_and_one_that_is_refused(self):
        cases = CASES()
        for route in api_routes.ROUTES:
            mine = [c for c in cases if c["route"] == route.name]
            self.assertTrue(any(c["status"] < 400 for c in mine), f"{route.name}: no case that works")
            self.assertTrue(any(c["status"] >= 400 for c in mine), f"{route.name}: no case that is refused")
            # Each case asks the route it names (but the one that asks it with another method, to be refused).
            for c in mine:
                if c["status"] != 405:
                    self.assertEqual(c["method"], route.method, route.name)

    def test_without_a_token_every_route_but_the_document_says_401(self):
        with Server() as inst:
            for route in api_routes.ROUTES:
                path = re.sub(r"{(\w+)}", lambda m: "1" if route.param(m.group(1))[0] == "integer" else "x", route.path)
                r = inst.ask(route.method, path, token=None)
                if route.scope is None:
                    self.assertEqual(r.status_code, 200, route.name)
                    continue
                self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (401, "no_token"), route.name)
                self.assertIn("Bearer", r.headers["WWW-Authenticate"])

    def test_a_read_token_reads_and_every_write_refuses_it(self):
        with Server() as inst:
            for route in api_routes.ROUTES:
                path = re.sub(r"{(\w+)}", lambda m: "1" if route.param(m.group(1))[0] == "integer" else "x", route.path)
                r = inst.ask(route.method, path, token="reader")
                # The route's scope decides, whatever its method: a backup's download is a GET of the write scope.
                if route.scope == "write":
                    self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (403, "read_only"), route.name)
                else:
                    self.assertNotIn(r.status_code, (401, 403), route.name)
            self.assertEqual(api_routes.by_name()["backup_download"].scope, "write")
            # The setup's looks at the server PC's folders too: any folder the server can read.
            self.assertEqual({api_routes.by_name()[n].scope for n in ("setup_folder", "setup_what")}, {"write"})

    def test_a_number_past_the_databases_largest_is_no_such_thing(self):
        # Every route with a number in its path: past the largest the database keeps, it matches no route (404), where it
        # once reached the database and failed there (500).
        huge = str(api.INT_MAX + 1)
        with Server() as inst:
            checked = 0
            for route in api_routes.ROUTES:
                if not any(route.param(n)[0] == "integer" for n in route.params()):
                    continue
                path = re.sub(r"{(\w+)}", lambda m: huge if route.param(m.group(1))[0] == "integer" else "x", route.path)
                r = inst.ask(route.method, path, json={"name": "x"} if route.body else None)
                self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (404, "not_found"), route.name)
                checked += 1
            self.assertGreater(checked, 15)
            # The largest itself is a number like any other: no such player. And the number the review tried.
            r = inst.ask("GET", f"/site/players/{api.INT_MAX}")
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (404, "player_not_found"))
            for path in ("/site/players/99999999999999999999", "/site/players/99999999999999999999/records"):
                self.assertEqual(inst.ask("GET", path).status_code, 404, path)
            # In a body, refused before the database is asked.
            r = inst.ask("POST", "/accounts/friend/link", json={"player": 10 ** 30})
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (400, "bad_field"))
            # The document says the range.
            doc = inst.client.get(V1 + "/openapi.json").get_json()
            part = next(p for p in doc["paths"]["/players/{player}"]["get"]["parameters"] if p["name"] == "player")
            self.assertEqual((part["schema"]["minimum"], part["schema"]["maximum"]), (0, api.INT_MAX))


# ------------------------------------------------------------------------------ tokens

@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class TokenTest(unittest.TestCase):
    def test_an_unknown_or_malformed_token_is_401(self):
        with Server() as inst:
            for sent in ("odq_000000000000_" + "a" * 43, "odq_" + Server.names["token:owner"] + "_" + "b" * 43, "nonsense"):
                r = inst.ask("GET", "/status", token=sent)
                self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (401, "bad_token"), sent)
            r = inst.client.get(V1 + "/status", headers={"Authorization": "Basic YWRtaW46cHc="})
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (401, "bad_token"))

    def test_wrong_tokens_count_with_the_sign_in_throttle(self):
        with Server() as inst:
            for _ in range(admin.auth.PER_IP):
                self.assertEqual(inst.ask("GET", "/status", token="odq_000000000000_" + "a" * 43).status_code, 401)
            # A token that works is looked at first, and is never held back: five wrong ones from the same address change
            # nothing for it.
            self.assertEqual(inst.ask("GET", "/status").status_code, 200)
            self.assertEqual(inst.ask("GET", "/status", token="reader").status_code, 200)
            # Another wrong one now waits, and is not counted again (as a sign-in over the limit is not).
            r = inst.ask("GET", "/status", token="odq_000000000000_" + "b" * 43)
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (429, "throttled"))
            self.assertEqual(r.headers["Retry-After"], str(admin.auth.WINDOW))
            self.assertEqual(len(admin.auth._failures["127.0.0.1"]), admin.auth.PER_IP)
            # They count with the sign-in page's: a password from here waits as well.
            self.assertIn("Too many", inst.client.post("/opendmtq/admin/login", data={"name": "admin", "password": "pw"}).get_data(as_text=True))

    def test_refused_tokens_are_in_the_log_of_changes_once_per_address_and_window(self):
        with Server() as inst:
            for _ in range(3):
                inst.ask("GET", "/status", token="odq_000000000000_" + "a" * 43)
            refused = [c for c in inst.ask("GET", "/logs/changes").get_json()["items"] if c["what"] == "api:refused"]
            # As a failed sign-in: by "API", with the address; once in the throttle's window, whatever the flood.
            self.assertEqual([(c["words"], c["who"], c["target"]) for c in refused], [("Refused an API token", "API", "127.0.0.1")])
            # A token that works leaves no line of its own (its last use is on the Accounts page).
            self.assertEqual(len([c for c in inst.ask("GET", "/logs/changes").get_json()["items"] if c["what"] == "api:refused"]), 1)
            # The window over: the next refused token is a line again.
            api._refused_noted["127.0.0.1"] -= admin.auth.WINDOW + 1
            inst.ask("GET", "/status", token="nonsense")
            self.assertEqual(len([c for c in inst.ask("GET", "/logs/changes").get_json()["items"] if c["what"] == "api:refused"]), 2)
            # Never the token itself: the log of changes is a file beside the database.
            with open(os.path.join(os.path.dirname(admin.core.DB), "changes.log"), "rb") as f:
                self.assertNotIn(b"odq_000000000000", f.read())

    def test_a_token_stops_with_its_admins_rights_and_goes_with_the_account(self):
        with Server() as inst:
            self.assertEqual(inst.ask("GET", "/status", token="helper").status_code, 200)
            for action, back in (("disable", "enable"), ("make-player", "make-admin")):
                self.assertEqual(inst.ask("POST", f"/accounts/helper/{action}").status_code, 200)
                r = inst.ask("GET", "/status", token="helper")
                self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (401, "token_stopped"), action)
                self.assertFalse(next(t for t in inst.ask("GET", "/tokens").get_json()["items"] if t["name"] == "helper")["works"])
                self.assertEqual(inst.ask("POST", f"/accounts/helper/{back}").status_code, 200)
                self.assertEqual(inst.ask("GET", "/status", token="helper").status_code, 200, back)
            # Deleted: its tokens go with it, and an account made again under the same ID gets none of them.
            self.assertEqual(inst.ask("DELETE", "/accounts/helper").status_code, 200)
            self.assertEqual(inst.ask("GET", "/status", token="helper").get_json()["error"]["code"], "bad_token")
            self.assertEqual({t["name"] for t in inst.ask("GET", "/tokens").get_json()["items"]}, {"reader", "owner"})

    def test_an_account_made_again_under_the_same_id_is_not_the_tokens_admin(self):
        with Server() as inst:
            # The account goes some other way than the API (a restore of an old backup, say): the token's row stays.
            with sqlite3.connect(admin.core.DB) as con:
                con.execute("DELETE FROM SiteUser WHERE name = 'helper'")
            admin.auth.account_create("helper", "hunter22", "", True)
            # Made later than the first: its own moment, whatever second this test runs in.
            with sqlite3.connect(admin.core.DB) as con:
                con.execute("UPDATE SiteUser SET created_at = created_at + 100 WHERE name = 'helper'")
            r = inst.ask("GET", "/status", token="helper")
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (401, "token_stopped"))

    def test_without_a_password_the_api_is_off_as_the_pages_are(self):
        with Server() as inst, mock.patch.object(admin.core, "PASSWORD", ""):
            r = inst.ask("GET", "/status")
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (503, "admin_off"))
            # The document holds no data and stays.
            self.assertEqual(inst.client.get(V1 + "/openapi.json").status_code, 200)

    def test_only_a_hash_is_kept_and_no_token_is_logged(self):
        with Server() as inst, self.assertLogs(admin.app.logger, "WARNING") as logs:
            secret = Server.secrets["owner"]
            admin.app.logger.warning("a line, so that the log has one")
            inst.ask("GET", "/status", token=secret[:-1] + "x")
            inst.ask("GET", "/nope")
            with open(admin.core.DB, "rb") as f:
                kept = f.read()
            self.assertNotIn(secret.encode(), kept)
            self.assertIn(hashlib.sha256(secret.encode()).hexdigest().encode(), kept)
            self.assertFalse([line for line in logs.output if "odq_" in line])

    def test_a_token_opens_no_page_and_the_api_makes_no_session(self):
        with Server() as inst:
            r = inst.client.get("/opendmtq/admin/players", headers={"Authorization": "Bearer " + Server.secrets["owner"]})
            self.assertEqual(r.status_code, 302)
            self.assertIn("/login", r.headers["Location"])
            r = inst.ask("POST", "/players/7/rename", json={"name": "Riku"})
            self.assertEqual(r.status_code, 200)
            self.assertNotIn("Set-Cookie", r.headers)
            self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_tokens_made_and_revoked_through_the_api(self):
        with Server() as inst:
            r = inst.ask("POST", "/tokens", json={"name": "deploy", "scope": "write"})
            made = r.get_json()
            self.assertEqual((made["token"]["admin"], made["token"]["owner"], made["token"]["works"]), ("admin", True, True))
            self.assertTrue(made["secret"].startswith("odq_" + made["token"]["id"] + "_"))
            self.assertEqual(inst.ask("GET", "/status", token=made["secret"]).status_code, 200)
            # Its last use, to the minute.
            listed = next(t for t in inst.ask("GET", "/tokens").get_json()["items"] if t["id"] == made["token"]["id"])
            self.assertIsNotNone(listed["used_at"])
            # A token can revoke itself.
            self.assertEqual(inst.ask("DELETE", f"/tokens/{made['token']['id']}", token=made["secret"]).status_code, 200)
            self.assertEqual(inst.ask("GET", "/status", token=made["secret"]).status_code, 401)
            # The helper's token makes tokens of the helper's.
            helper = inst.ask("POST", "/tokens", token="helper", json={"name": "theirs", "scope": "read"}).get_json()
            self.assertEqual((helper["token"]["admin"], helper["token"]["owner"]), ("helper", False))

    def test_the_log_of_changes_says_which_admin_and_token(self):
        with Server() as inst:
            inst.ask("POST", "/players/7/rename", json={"name": "Riku"})
            inst.ask("POST", "/tokens", token="helper", json={"name": "ci", "scope": "read"})
            changes = inst.ask("GET", "/logs/changes").get_json()["items"]
            self.assertEqual((changes[1]["what"], changes[1]["words"], changes[1]["target"], changes[1]["who"]),
                             ("player_action:rename", "Renamed a player", "Sena → Riku", "admin (owner)"))
            self.assertEqual((changes[0]["words"], changes[0]["who"]), ("Made an API token", "helper (helper)"))

    def test_a_database_from_before_the_token_table_still_works(self):
        with Server() as inst:
            with sqlite3.connect(admin.core.DB) as con:
                con.execute("DROP TABLE ApiToken")
            inst.sign_in()
            self.assertIn("No tokens yet.", inst.client.get("/opendmtq/admin/accounts").get_data(as_text=True))
            self.assertEqual(inst.ask("GET", "/status").get_json()["error"]["code"], "bad_token")


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class TokenPageTest(unittest.TestCase):
    """The tokens on the Accounts page: made, shown once, listed, revoked."""

    def test_a_token_is_made_shown_once_listed_and_revoked(self):
        with Server() as inst:
            csrf = page_token(inst)
            page = inst.client.post("/opendmtq/admin/accounts", data={"csrf": csrf, "action": "token", "token_name": "my script", "scope": "write"},
                                    follow_redirects=True).get_data(as_text=True)
            secret = re.search(r'<code id="token-secret">(odq_[0-9a-f]{12}_[A-Za-z0-9_-]{43})</code>', page).group(1)
            # The name in quotes: a token's name may have spaces in it.
            self.assertIn("Token “my script” made", page)
            # It works, and it is the owner's.
            self.assertEqual(inst.ask("GET", "/status", token=secret).status_code, 200)
            page = inst.client.get("/opendmtq/admin/accounts").get_data(as_text=True)
            self.assertNotIn(secret, page)
            row = re.search(r"<tr>\s*<td class=\"primary\"[^>]*>my script<span class=\"runtime token-id\">odq_([0-9a-f]{12})_…</span>.*?</tr>", page, re.S)
            self.assertTrue(row, page[page.index('id="tokens"'):][:2000])
            self.assertIn("Read and write", row.group(0))
            self.assertIn("Works", row.group(0))
            page = inst.client.post("/opendmtq/admin/accounts", data={"csrf": csrf, "action": "revoke", "token": row.group(1)},
                                    follow_redirects=True).get_data(as_text=True)
            self.assertIn("The token “my script” is revoked.", page)
            self.assertEqual(inst.ask("GET", "/status", token=secret).status_code, 401)
            changes = inst.client.get("/opendmtq/admin/logs?tab=changes").get_data(as_text=True)
            self.assertIn("Made an API token", changes)
            self.assertIn("Revoked an API token", changes)

    def test_a_name_that_is_none_is_refused_in_both_languages(self):
        with Server() as inst:
            csrf = page_token(inst)
            page = inst.client.post("/opendmtq/admin/accounts", data={"csrf": csrf, "action": "token", "token_name": "", "scope": "read"},
                                    follow_redirects=True).get_data(as_text=True)
            self.assertIn("A token needs a name of 1 to 40 characters.", page)
            inst.client.get("/opendmtq/admin/lang?to=ko")
            page = inst.client.post("/opendmtq/admin/accounts", data={"csrf": csrf, "action": "revoke", "token": "000000000000"},
                                    follow_redirects=True).get_data(as_text=True)
            self.assertIn("없는 토큰입니다.", page)

    def test_an_account_admins_token_is_theirs_and_stops_with_them(self):
        with Server() as inst:
            other = admin.app.test_client()
            other.post("/opendmtq/admin/login", data={"name": "helper", "password": "hunter22"})
            other.get("/opendmtq/admin/accounts")
            with other.session_transaction(path="/opendmtq/admin/") as sess:
                csrf = sess["csrf"]
            page = other.post("/opendmtq/admin/accounts", data={"csrf": csrf, "action": "token", "token_name": "mine", "scope": "read"},
                              follow_redirects=True).get_data(as_text=True)
            secret = re.search(r'<code id="token-secret">([^<]+)</code>', page).group(1)
            mine = next(t for t in inst.ask("GET", "/tokens").get_json()["items"] if t["name"] == "mine")
            self.assertEqual((mine["admin"], mine["owner"], mine["scope"]), ("helper", False, "read"))
            inst.ask("POST", "/accounts/helper/disable")
            self.assertEqual(inst.ask("GET", "/status", token=secret).get_json()["error"]["code"], "token_stopped")
            inst.sign_in()
            self.assertIn("Stopped", inst.client.get("/opendmtq/admin/accounts").get_data(as_text=True))


# ------------------------------------------------------------------------------ jobs, uploads, downloads

@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class JobTest(unittest.TestCase):
    def test_a_build_is_followed_to_its_end(self):
        with Server() as inst, quick_jobs(("working", "built")):
            r = inst.ask("POST", "/builds", json={"host": "http://friend.example.com:8790/"})
            self.assertEqual(r.status_code, 202)
            job = r.get_json()["job"]
            self.assertEqual((job["kind"], job["host"]), ("build", "friend.example.com:8790"))
            self.assertIn(job["state"], ("running", "done"))
            done = wait_job(inst, job["id"])
            self.assertEqual((done["state"], done["log"], done["why"]), ("done", ["working", "built"], None))
            self.assertIn(job["id"], [j["id"] for j in inst.ask("GET", "/jobs").get_json()["items"]])

    def test_a_failed_import_says_why(self):
        with Server() as inst:
            patches = host_install(inst)
            for p in patches:
                p.start()
            real = admin.jobs.start_job

            def fails(kind, cmd, env=None, explain=None, **details):
                return real(kind, [sys.executable, "-c", "print('game files: none found'); print('base APK: none found'); raise SystemExit(1)"],
                            env=env, explain=explain, **details)
            try:
                with mock.patch.object(admin.jobs, "start_job", fails):
                    job = inst.ask("POST", "/setup/import", json={"path": "~/Downloads/game", "songs": False}).get_json()["job"]
                done = wait_job(inst, job["id"])
                self.assertEqual((done["state"], done["path"]), ("failed", inst.path("home/Downloads/game")))
                self.assertEqual(done["why"], "Neither the game's Android app nor its files are there. Choose the folder or archive that holds them.")
            finally:
                for p in patches:
                    p.stop()

    def test_a_restore_is_a_job_and_keeps_todays_tokens(self):
        with Server() as inst:
            # Made after the backup: a restore must not end it.
            made = inst.ask("POST", "/tokens", json={"name": "after", "scope": "write"}).get_json()
            inst.ask("POST", "/players/7/rename", json={"name": "Riku"})
            r = inst.ask("POST", f"/backups/{Server.names['backup']}/restore", token=made["secret"])
            self.assertEqual(r.status_code, 202)
            done = wait_job(inst, r.get_json()["job"]["id"])
            self.assertEqual((done["state"], done["kind"], done["backup"]), ("done", "restore", Server.names["backup"]), done)
            # What the page would say of it, as plain text.
            self.assertTrue(done["log"][0].startswith(f"Restored {Server.names['backup']}. The previous state was saved as "), done["log"])
            # The backup's name is back, and the token made since works.
            self.assertEqual(inst.ask("GET", "/players/7", token=made["secret"]).get_json()["player"]["name"], "Sena")
            changes = inst.ask("GET", "/logs/changes").get_json()["items"]
            self.assertEqual((changes[0]["what"], changes[0]["who"]), ("backup_action:restore", "admin (after)"))

    def test_the_restored_database_has_todays_tokens_before_it_takes_the_live_ones_place(self):
        # The tokens of now go into the restored copy first: no moment in which a revoked token works again, or the token
        # that follows the restore's job is not one of this server's.
        real = admin.backups.swap_in
        seen = []

        def watched(restored):
            # What the copy holds the moment it takes the live database's place.
            con = sqlite3.connect(restored)
            seen.append(sorted(r[0] for r in con.execute("SELECT name FROM ApiToken")))
            con.close()
            return real(restored)

        with Server() as inst:
            made = inst.ask("POST", "/tokens", json={"name": "after", "scope": "write"}).get_json()
            # Revoked since the backup was made: it must not come back.
            self.assertEqual(inst.ask("DELETE", f"/tokens/{Server.names['token:reader']}").status_code, 200)
            with mock.patch.object(admin.backups, "swap_in", watched):
                r = inst.ask("POST", f"/backups/{Server.names['backup']}/restore", token=made["secret"])
                done = wait_job(inst, r.get_json()["job"]["id"])
            self.assertEqual(done["state"], "done", done)
            self.assertEqual(seen, [["after", "helper", "owner"]])
            self.assertEqual(inst.ask("GET", "/status", token="reader").get_json()["error"]["code"], "bad_token")
            self.assertEqual(inst.ask("GET", "/status", token=made["secret"]).status_code, 200)

    def test_a_restore_keeps_todays_accounts(self):
        # An account deleted since the backup stays deleted, a password made since stays the one that works, an account
        # made since stays: who may sign in is today's, as the API's tokens are.
        with Server() as inst:
            self.assertEqual(inst.ask("POST", "/accounts", json={"name": "gone", "password": "hunter22"}).status_code, 201)
            name = inst.ask("POST", "/backups").get_json()["backup"]["name"]
            self.assertEqual(inst.ask("DELETE", "/accounts/gone").status_code, 200)
            new = inst.ask("POST", "/accounts/friend/password").get_json()["password"]
            self.assertEqual(inst.ask("POST", "/accounts", json={"name": "newcomer"}).status_code, 201)
            r = inst.ask("POST", f"/backups/{name}/restore")
            done = wait_job(inst, r.get_json()["job"]["id"])
            self.assertEqual(done["state"], "done", done)
            self.assertEqual([a["name"] for a in inst.ask("GET", "/accounts").get_json()["items"]], ["friend", "helper", "newcomer"])
            self.assertTrue(admin.auth.account_pass_ok(admin.auth.account_find("friend")["pass"], new))
            self.assertFalse(admin.auth.account_pass_ok(admin.auth.account_find("friend")["pass"], "hunter22"))

    def test_a_server_with_no_account_yet_takes_the_backups(self):
        # A move to a new PC: no account of its own yet, and every player of the backup still signs in.
        with Server() as inst:
            name = inst.ask("POST", "/backups").get_json()["backup"]["name"]
            for account in ("friend", "helper"):
                self.assertEqual(inst.ask("DELETE", f"/accounts/{account}").status_code, 200)
            r = inst.ask("POST", f"/backups/{name}/restore")
            self.assertEqual(wait_job(inst, r.get_json()["job"]["id"])["state"], "done")
            self.assertEqual([a["name"] for a in inst.ask("GET", "/accounts").get_json()["items"]], ["friend", "helper"])

    def test_a_restore_that_fails_says_why(self):
        with Server() as inst:
            inst.write("backups/opendmtq-20200101-000000-admin.tar.gz", "not an archive")
            r = inst.ask("POST", "/backups/opendmtq-20200101-000000-admin.tar.gz/restore")
            done = wait_job(inst, r.get_json()["job"]["id"])
            self.assertEqual(done["state"], "failed")
            self.assertIn("Not restored", done["why"])
            self.assertFalse(admin.backups._restoring.locked())


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class FilesTest(unittest.TestCase):
    def test_a_song_package_goes_up_and_shows_in_the_list(self):
        with Server() as inst, mock.patch.object(admin.songs, "rebuild"):
            r = inst.ask("POST", "/songs", data={"package": (io.BytesIO(song_package()), "new.zip")}, content_type="multipart/form-data")
            self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
            song = r.get_json()["song"]
            self.assertEqual((song["title"], song["source"], song["charts"]), ("New Song", "added", 1))
            self.assertIn(song["id"], [s["id"] for s in inst.ask("GET", "/songs").get_json()["items"]])
            changes = inst.ask("GET", "/logs/changes").get_json()["items"]
            self.assertEqual((changes[0]["words"], changes[0]["target"]), ("Added a song", "New Song"))

    def test_an_upload_over_its_limit_is_413_and_read_to_its_end(self):
        with Server() as inst, mock.patch.dict(admin.core.API_LIMITS, {"api_songs_add": 1024}):
            body = (b"--x\r\nContent-Disposition: form-data; name=\"package\"; filename=\"a.zip\"\r\n\r\n" + bytes(8192) + b"\r\n--x--\r\n")
            stream = io.BytesIO(body)
            r = inst.client.post(V1 + "/songs", input_stream=stream, content_length=len(body), content_type="multipart/form-data; boundary=x",
                                 headers={"Authorization": "Bearer " + Server.secrets["owner"]})
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (413, "too_large"))
            self.assertEqual(stream.read(), b"")
        # A body too big for a JSON route too, before anything is read of it from a caller without a token.
        with Server() as inst:
            r = inst.client.post(V1 + "/maintenance", data=b"x" * (admin.core.MAX_SIGNED_OUT + 10), content_type="application/json")
            self.assertEqual(r.status_code, 401)

    def test_a_backup_goes_up_and_comes_down_the_same(self):
        with Server() as inst:
            with open(inst.path(f"backups/{Server.names['backup']}"), "rb") as f:
                original = f.read()
            r = inst.ask("POST", "/backups/upload", data={"file": (io.BytesIO(original), "elsewhere.tar.gz")}, content_type="multipart/form-data")
            name = r.get_json()["backup"]["name"]
            self.assertTrue(name.endswith("-uploaded.tar.gz"))
            r = inst.ask("GET", f"/backups/{name}/download")
            self.assertEqual(r.data, original)
            self.assertIn(name, r.headers["Content-Disposition"])

    def test_downloads_are_the_files_with_their_types(self):
        with Server() as inst:
            r = inst.ask("GET", "/builds/OpenDMTQ-x.apk/download")
            self.assertEqual((r.mimetype, r.data), ("application/vnd.android.package-archive", b"app"))
            self.assertIn("attachment", r.headers["Content-Disposition"])
            r = inst.ask("GET", f"/recordings/7/{Server.names['closed']}/files/0.ts")
            self.assertEqual((r.mimetype, r.data), ("video/mp2t", b"aa"))
            r = inst.ask("GET", "/logs/plays/download")
            self.assertEqual(r.mimetype, "text/csv")
            self.assertTrue(r.data.startswith(b"\xef\xbb\xbftime,player_id"))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class InstallerDownloadTest(unittest.TestCase):
    """GET /app/windows goes on where a broken download stopped, by the rules of the site's /windows (lib.php,
    send_download()): one part asked with Range, kept to the same installer and end by If-Range or If-Match on its ETag,
    which covers the server's details on the installer's end as well as the installer."""

    # The installer: big enough for its last 200 bytes to reach from its own into the end after it.
    INSTALLER = bytes(range(256)) * 20

    def installer(self, inst):
        """The installer beside the app, with windows.json giving its size and hash, as the builder leaves them."""
        # Bytes, which inst.write (text) does not take.
        with open(inst.path("apk/out/OpenDMTQ-Setup.exe"), "wb") as f:
            f.write(self.INSTALLER)
        inst.write("apk/out/windows.json", json.dumps({"file": "OpenDMTQ-Setup.exe", "size": len(self.INSTALLER),
                                                       "sha256": hashlib.sha256(self.INSTALLER).hexdigest(), "version": "0.8.0",
                                                       "copied_at": "2026-11-09T12:00:00"}))

    def test_a_part_goes_on_while_the_installer_and_its_end_stay_the_same(self):
        with Server() as inst:
            self.installer(inst)
            whole = inst.ask("GET", "/app/windows")
            size, tail = len(whole.data), whole.data[len(self.INSTALLER):]
            # What a download manager reads before it trusts a part: parts in bytes, a strong tag of the installer and of
            # its end, the file's time; the whole's length, with no body.
            head = inst.ask("HEAD", "/app/windows")
            tag = head.headers["ETag"]
            self.assertEqual((head.status_code, head.data, head.headers["Content-Length"], head.headers["Accept-Ranges"]),
                             (200, b"", str(size), "bytes"))
            self.assertEqual(tag, f'"{hashlib.sha256(self.INSTALLER).hexdigest()}-{hashlib.sha256(tail).hexdigest()[:16]}"')
            self.assertTrue(head.headers["Last-Modified"].endswith(" GMT"))
            self.assertEqual((whole.status_code, whole.headers["ETag"]), (200, tag))
            # The last 200 bytes, from the installer's own into the server's details after them.
            self.assertLess(size - 200, len(self.INSTALLER))
            part = inst.ask("GET", "/app/windows", headers={"Range": f"bytes={size - 200}-", "If-Range": tag})
            self.assertEqual((part.status_code, part.headers["Content-Range"], part.data),
                             (206, f"bytes {size - 200}-{size - 1}/{size}", whole.data[-200:]))
            # A part of another file: the whole again.
            other = inst.ask("GET", "/app/windows", headers={"Range": "bytes=0-9", "If-Range": '"another"'})
            self.assertEqual((other.status_code, other.data), (200, whole.data))
            # As Android's downloads ask: 412 for another file, the part for this one.
            moved = inst.ask("GET", "/app/windows", headers={"Range": "bytes=0-9", "If-Match": '"another"'})
            self.assertEqual((moved.status_code, moved.get_json()["error"]["code"]), (412, "precondition_failed"))
            same = inst.ask("GET", "/app/windows", headers={"Range": "bytes=0-9", "If-Match": tag})
            self.assertEqual((same.status_code, same.data), (206, whole.data[:10]))
            # Nothing past the end: 416, with the length the next try can go by.
            past = inst.ask("GET", "/app/windows", headers={"Range": f"bytes={size}-"})
            self.assertEqual((past.status_code, past.headers["Content-Range"], past.get_json()["error"]["code"]),
                             (416, f"bytes */{size}", "range_not_satisfiable"))

    def test_the_tag_covers_the_servers_details_on_the_end(self):
        # The same installer for another address is other bytes: a part kept from before is not added to, the whole comes.
        with Server() as inst:
            self.installer(inst)
            tag = inst.ask("HEAD", "/app/windows").headers["ETag"]
            with mock.patch.object(admin.core, "PUBLIC_HOST", "10.0.0.99"):
                moved = inst.ask("GET", "/app/windows", headers={"Range": "bytes=0-9", "If-Range": tag})
            self.assertEqual(moved.status_code, 200)
            self.assertIn(b'"url":"http://10.0.0.99', moved.data)
            # The installer's hash is the same; the end's is not.
            self.assertEqual(moved.headers["ETag"].split("-")[0], tag.split("-")[0])
            self.assertNotEqual(moved.headers["ETag"], tag)

    def test_what_is_not_one_part_of_a_get_gets_the_whole(self):
        # Several parts (multipart answers, which no download manager needs), a last before the first, a HEAD, another
        # unit, no position at all: the whole, as the site answers them.
        with Server() as inst:
            self.installer(inst)
            size = inst.ask("HEAD", "/app/windows").headers["Content-Length"]
            for method, asked in (("GET", "bytes=0-0,5-9"), ("GET", "bytes=5-2"), ("HEAD", "bytes=0-9"), ("GET", "items=0-9"),
                                  ("GET", "bytes=-")):
                with self.subTest(method=method, asked=asked):
                    r = inst.ask(method, "/app/windows", headers={"Range": asked})
                    self.assertEqual((r.status_code, r.headers["Content-Length"]), (200, size))
                    self.assertNotIn("Content-Range", r.headers)

    def test_the_tag_is_made_as_the_site_makes_it(self):
        # What lib.php's download_tag() gives for the same manifest, file and end (PHP 8.3).
        stat = types.SimpleNamespace(st_size=10, st_mtime=1700000000)
        self.assertEqual(admin.apps.download_tag({"sha256": "AB" * 32, "size": 10}, stat, b"xyz"), '"' + "ab" * 32 + '-3608bca1e44ea6c4"')
        # A manifest of another size, with no whole hash or with none: the file's size and time in hex.
        self.assertEqual(admin.apps.download_tag({"sha256": "ab" * 32, "size": 11}, stat, b"xyz"), '"a-6553f100-3608bca1e44ea6c4"')
        self.assertEqual(admin.apps.download_tag({"sha256": "0", "size": 10}, stat, b""), '"a-6553f100"')
        self.assertEqual(admin.apps.download_tag({"size": 10}, stat, b"xyz"), '"a-6553f100-3608bca1e44ea6c4"')


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class LiveListSignTest(unittest.TestCase):
    """GET /site/live gives the sign of its list of recordings (past_rev), as the site's live.php?list=1 does: a client that
    keeps the list, as the live page does, asks for it again only when the sign changed."""

    # The sign of a list with no recording in it: broadcasts off, or every recording hidden.
    NONE = "e3b0c44298fc1c14"

    def broadcasts(self, on):
        """Broadcasts on or off for the server, as the Broadcasts page leaves them (the site shows no recording while off)."""
        with sqlite3.connect(admin.core.DB) as con:
            admin.recordings.setting_rows(con)
            admin.recordings.write_settings(con, {"on": on})

    def test_the_sign_is_the_sites_for_the_same_keys(self):
        # What lib.php's live_past_rev_of() gives for these keys, newest first, and for none (PHP 8.3).
        self.assertEqual(admin.site.past_rev([{"key": "8-1794200000"}, {"key": "7-1794100000"}]), "9099656869752324")
        self.assertEqual(admin.site.past_rev([{"key": "7-1794100000"}]), "3146b2c89f972a6d")
        self.assertEqual(admin.site.past_rev([]), self.NONE)

    def test_it_follows_the_list_as_a_recording_is_hidden_and_shown_again(self):
        closed = Server.names["closed"]
        with Server() as inst:
            self.broadcasts(True)
            # Sena's closed recording is the list (Yuna's is still being made); the sign is of its key.
            first = inst.ask("GET", "/site/live").get_json()
            self.assertEqual([r["key"] for r in first["past"]], [f"7-{closed}"])
            self.assertEqual(first["past_rev"], hashlib.sha256(f"7-{closed}".encode()).hexdigest()[:16])
            # Hidden: another list, another sign; shown again: the first sign again.
            self.assertEqual(inst.ask("POST", f"/recordings/7/{closed}/hide").status_code, 200)
            hidden = inst.ask("GET", "/site/live").get_json()
            self.assertEqual((hidden["past"], hidden["past_rev"]), ([], self.NONE))
            self.assertEqual(inst.ask("POST", f"/recordings/7/{closed}/show").status_code, 200)
            self.assertEqual(inst.ask("GET", "/site/live").get_json()["past_rev"], first["past_rev"])

    def test_with_broadcasts_off_it_is_the_sign_of_no_list(self):
        # As the site's live_past_rev() with broadcasts off: no recording is shown, whatever there is.
        with Server() as inst:
            self.broadcasts(False)
            answer = inst.ask("GET", "/site/live").get_json()
            self.assertEqual((answer["on"], answer["past"], answer["past_rev"]), (False, [], self.NONE))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class OneRecordingTest(unittest.TestCase):
    """A recording's routes read that recording's folder, and a player's delete their recordings, not every one there is
    (rec_all() reads each recording's files)."""

    def test_a_recordings_routes_read_it_alone(self):
        closed = Server.names["closed"]
        with Server() as inst, mock.patch.object(admin.recordings, "rec_all", side_effect=AssertionError("every recording was read")):
            self.assertEqual(inst.ask("GET", f"/recordings/7/{closed}").get_json()["recording"]["key"], f"7/{closed}")
            # Hide and show answer the recording as it is after.
            self.assertTrue(inst.ask("POST", f"/recordings/7/{closed}/hide").get_json()["recording"]["hidden"])
            self.assertFalse(inst.ask("POST", f"/recordings/7/{closed}/show").get_json()["recording"]["hidden"])
            # One that is not there, and one being made that stays.
            self.assertEqual(inst.ask("POST", "/recordings/7/1/hide").status_code, 404)
            self.assertEqual(inst.ask("DELETE", f"/recordings/8/{Server.names['open']}").status_code, 409)
            self.assertEqual(inst.ask("DELETE", f"/recordings/7/{closed}").get_json(), {"deleted": f"7/{closed}"})

    def test_all_of_a_players_is_the_pages_own_action(self):
        # The page's side, and what the action does: test_admin.py.
        with Server() as inst, mock.patch.object(admin.recordings, "rec_delete_player", wraps=admin.recordings.rec_delete_player) as action, \
                mock.patch.object(admin.recordings, "rec_all", side_effect=AssertionError("every recording was read")):
            self.assertEqual(inst.ask("POST", "/recordings/delete", json={"player": 7}).get_json(), {"done": 1, "kept": 0})
            action.assert_called_once_with(7)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class SameFiguresTest(unittest.TestCase):
    """What the pages and the API both show is worked out once (recordings.py, status.facts): the hours of broadcast left,
    each quality's costs, the players' names and the number of recordings."""

    @staticmethod
    def disk(free):
        """A disk of 10 TB with this much free, in the figures shutil.disk_usage answers with."""
        return mock.Mock(total=10 * 1024 ** 4, used=10 * 1024 ** 4 - free, free=free)

    def page(self, inst, address):
        inst.sign_in()
        return inst.client.get(address).get_data(as_text=True)

    def test_the_hours_left_are_the_same_on_the_page_and_in_the_api(self):
        hour = admin.recordings.per_hour("standard")
        # The server's two recordings take 7 bytes: 5 closed, 2 so far of the open one.
        used = 7
        # The limit is what binds (a big disk), the disk is (a small one), and not even an hour fits.
        for cap_gb, free, hours in ((5, 1024 ** 4, (5 * 1024 ** 3 - used) // hour), (20, 3 * hour + 7, 3), (0.5, 1024 ** 4, 0)):
            with Server() as inst, mock.patch.object(shutil, "disk_usage", return_value=self.disk(free)):
                admin.recordings.rec_save_limits(cap_gb, 30)
                limits = inst.ask("GET", "/recordings/limits").get_json()
                self.assertEqual(limits["used"], used)
                api_hours = limits["hours_left"]
                page = self.page(inst, "/opendmtq/admin/recordings")
                shown = re.search(r"About (\d+) h of broadcast still fit", page)
                self.assertEqual(api_hours, hours, cap_gb)
                # The page says the same number, or that less than an hour fits.
                self.assertEqual(int(shown.group(1)) if shown else 0, api_hours, cap_gb)
                self.assertEqual("Less than an hour of broadcast still fits" in page, api_hours == 0, cap_gb)

    def test_each_qualitys_costs_are_the_same_on_the_page_and_in_the_api(self):
        with Server() as inst:
            qualities = inst.ask("GET", "/broadcasts").get_json()["qualities"]
            page = self.page(inst, "/opendmtq/admin/recordings")
        shown = re.findall(r"([\d.]+ [KMG]?B) an hour recorded, ([\d.]+) Mbit/s for each viewer", page)
        self.assertEqual(shown, [(admin.core.human(q["hour_bytes"]), "%.1f" % (q["viewer_bits"] / 1000000)) for q in qualities])
        # In the server's order, each a segment of the server's length.
        self.assertEqual([q["key"] for q in qualities], list(admin.recordings.LIVE_PRESETS))
        self.assertEqual({q["segment"] for q in qualities}, {admin.recordings.SEGMENT})

    def test_the_players_names_are_the_same_on_the_page_and_in_the_api(self):
        with Server() as inst:
            items = inst.ask("GET", "/recordings").get_json()["items"]
            page = self.page(inst, "/opendmtq/admin/recordings")
        # A heading per player on the page, newest recording's player first, as the API lists them.
        self.assertEqual(re.findall(r'<div class="rec-group">\s*<h3>([^<]*)</h3>', page), [r["name"] for r in items])
        self.assertEqual([r["name"] for r in items], ["Yuna", "Sena"])

    def test_the_number_of_recordings_comes_from_one_look_a_minute(self):
        with Server() as inst, mock.patch.object(admin.recordings, "rec_all", wraps=admin.recordings.rec_all) as looks:
            # Broadcasts on: the dashboard's tile then says how many recordings there are.
            with sqlite3.connect(admin.core.DB) as con:
                admin.recordings.setting_rows(con)
                admin.recordings.write_settings(con, {"on": True})
            dashboard = self.page(inst, "/opendmtq/admin/")
            self.assertIn("Recordings: 2", dashboard)
            self.assertEqual(inst.ask("GET", "/status").get_json()["recordings"], 2)
            # The dashboard's disk figures, its count and the API's: every recording read once for all of them.
            self.assertEqual(looks.call_count, 1)
            # A deletion is counted at once, the minute or not.
            inst.ask("DELETE", f"/recordings/7/{Server.names['closed']}")
            self.assertEqual(inst.ask("GET", "/status").get_json()["recordings"], 1)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class KeysTest(unittest.TestCase):
    """The keyboard's mark: the PC client's player says a play was made with the keyboard (its save's X-OpenDMTQ-Keys
    header), and the game server keeps it with the play (PlayLog's keys) and with the best that play set (Play's keys). Every
    answer that lists plays or bests says it (keys), as the site marks them; every answer that lists totals or a month's
    scores counts the bests a keyboard play set (keys_charts), as the site's mark beside a total says."""

    @staticmethod
    def marked(inst):
        """The template server with Sena's best on chart 12 set by a keyboard play, a minute ago: this month's too."""
        with sqlite3.connect(admin.core.DB) as con:
            con.execute("UPDATE Play SET keys = 1 WHERE user_id = 7 AND pattern_id = 12")
            con.execute("UPDATE PlayLog SET keys = 1, played_at = ? WHERE user_id = 7 AND pattern_id = 12", (now() - 60,))

    def test_every_play_and_best_says_whether_the_keyboard_played_it(self):
        with Server() as inst:
            self.marked(inst)
            # A chart's leaderboard, a player's records and their page's plays, the newest plays and records, the home page's.
            board = {p["name"]: p["keys"] for p in inst.ask("GET", "/site/charts/12/ranking").get_json()["items"]}
            self.assertEqual(board, {"Sena": True})
            board = {p["name"]: p["keys"] for p in inst.ask("GET", "/site/charts/11/ranking").get_json()["items"]}
            self.assertEqual(board, {"Sena": False, "Yuna": False})
            records = {r["chart"]: r["keys"] for r in inst.ask("GET", "/site/players/7/records").get_json()["items"]}
            self.assertEqual(records, {11: False, 12: True})
            page = inst.ask("GET", "/site/players/7").get_json()
            self.assertEqual(([(p["chart"], p["keys"]) for p in page["recent"]], page["keys_charts"]), ([(12, True), (11, False)], 1))
            for path in ("/site/plays/recent", "/site/plays/recent?records=true"):
                plays = [(p["player"], p["chart"], p["keys"]) for p in inst.ask("GET", path).get_json()["items"]]
                self.assertEqual(sorted(plays), sorted([(7, 12, True), (7, 11, False), (8, 11, False)] + ([(8, 11, False)] if "records" not in path else [])), path)
            home = inst.ask("GET", "/site/home").get_json()
            self.assertEqual(sorted((p["player"], p["chart"], p["keys"]) for p in home["records"]), [(7, 11, False), (7, 12, True), (8, 11, False)])
            # The admin pages' newest plays and the Plays tab.
            recent = {(p["player"], p["score"]): p["keys"] for p in inst.ask("GET", "/status").get_json()["recent"]}
            self.assertEqual(recent, {(7, 800000): True, (7, 900000): False, (8, 700000): False, (8, 600000): False})
            logged = {(p["player"], p["score"]): p["keys"] for p in inst.ask("GET", "/logs/plays").get_json()["items"]}
            self.assertEqual(logged, recent)
            # The file of plays: the mark as its last column.
            lines = [line.split(",") for line in inst.ask("GET", "/logs/plays/download").get_data(as_text=True).lstrip("﻿").splitlines()]
            self.assertEqual(sorted((line[5], line[-1]) for line in lines), [("600000", "0"), ("700000", "0"), ("800000", "1"), ("900000", "0"), ("score", "keys")])

    def test_every_total_counts_the_bests_a_keyboard_play_set(self):
        with Server() as inst:
            self.marked(inst)
            # Every tab of the rankings, the home page's best players, a player's page.
            ranked = {p["name"]: p["keys_charts"] for p in inst.ask("GET", "/site/rankings").get_json()["items"]}
            self.assertEqual(ranked, {"Sena": 1, "Yuna": 0})
            top = {p["name"]: p["keys_charts"] for p in inst.ask("GET", "/site/home").get_json()["top"]}
            self.assertEqual(top, {"Sena": 1, "Yuna": 0})
            self.assertEqual([inst.ask("GET", f"/site/players/{guid}").get_json()["keys_charts"] for guid in (7, 8, 9)], [1, 0, 0])
            # This month: Sena's best on chart 12 this month is the keyboard's play.
            month = {p["name"]: p["keys_charts"] for p in inst.ask("GET", "/site/rankings/month").get_json()["items"]}
            self.assertEqual(month["Sena"], 1)
            self.assertEqual(month.get("Yuna", 0), 0)

    def test_a_months_best_is_the_play_that_got_there_first(self):
        # A month's score adds up each chart's top score that month: the mark counts a chart when the play that first got to
        # that score was a keyboard play. A better play by touch takes the chart from it, a tie by touch after it does not, and
        # a tie by touch before it keeps the chart by touch.
        with Server() as inst:
            t = now()
            with sqlite3.connect(admin.core.DB) as con:
                con.execute("DELETE FROM PlayLog")
                con.executemany("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at, keys) VALUES (?, ?, ?, 'A', 900, 0, ?, ?)",
                                # Sena: chart 11 by keys then a tie by touch (kept); chart 12 by keys then better by touch (gone).
                                [(7, 11, 500, t - 300, 1), (7, 11, 500, t - 200, 0), (7, 12, 500, t - 300, 1), (7, 12, 600, t - 200, 0),
                                 # Yuna: chart 11 by touch then a tie by keys (by touch); chart 21 by keys only.
                                 (8, 11, 500, t - 300, 0), (8, 11, 500, t - 200, 1), (8, 21, 400, t - 100, 1)])
            month = {p["name"]: p["keys_charts"] for p in inst.ask("GET", "/site/rankings/month").get_json()["items"]}
            self.assertEqual(month, {"Sena": 1, "Yuna": 1})

    def test_a_month_nobody_played_with_the_keyboard_costs_one_look(self):
        # A server where nobody plays with the keyboard pays nothing more for a month's counts: one look at the index of the
        # keyboard's plays finds none, and the statement that reads the month's scores is not even made. An authorizer sees
        # every column a statement reads as SQLite makes the statement.
        with Server():
            con = sqlite3.connect(admin.core.DB)
            read = set()

            def note(action, table, column, *_):
                # Each column read, by its table.
                if action == sqlite3.SQLITE_READ:
                    read.add(f"{table}.{column}")
                return sqlite3.SQLITE_OK

            con.set_authorizer(note)
            counts = admin.site.month_keys(con, admin.site.month_start(), 2 ** 63 - 1, [7, 8])
            con.close()
            self.assertEqual(counts, {})
            # Of the play log, the mark and the time alone: the look, and no score.
            self.assertEqual(sorted(c for c in read if c.startswith("PlayLog.")), ["PlayLog.keys", "PlayLog.played_at"])

    def test_a_month_before_counts_its_first_three_alone(self):
        # The months before show their first three: their counts are asked for them alone, and come from their own plays of
        # that month. Four players played last month, each a best with the keyboard there; the fourth is not asked about.
        with Server() as inst:
            member_rows(admin.core.DB, [(10, "Riku", "phone-d")])
            last = admin.site.month_start(1)
            with sqlite3.connect(admin.core.DB) as con:
                con.execute("DELETE FROM PlayLog")
                con.executemany("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at, keys) VALUES (?, 11, ?, 'A', 900, 1, ?, 1)",
                                [(7, 900, last + 60), (8, 800, last + 120), (9, 700, last + 180), (10, 600, last + 240)])
            # Every month's count as it is asked for: the month's start and the players.
            with mock.patch.object(admin.site, "month_keys", wraps=admin.site.month_keys) as asked:
                answer = inst.ask("GET", "/site/rankings/month").get_json()
            players = {c.args[1]: sorted(c.args[3]) for c in asked.call_args_list}
            self.assertEqual(players[last], [7, 8, 9])
            self.assertEqual([(p["id"], p["keys_charts"]) for p in answer["past_months"][0]["top"]], [(7, 1), (8, 1), (9, 1)])

    def test_a_database_the_server_has_not_brought_up_to_date_says_none_were(self):
        # The admin service can be up before the server after an upgrade: the database has no keyboard's column yet (the
        # server's start adds it). Every answer comes as before, every play and best by touch.
        with Install() as inst, mock.patch.object(admin.songs, "CONTENT", inst.path("content")):
            old_game_database(admin.core.DB, [(11, 7, 900000, "S", "Y", "N", 950)])
            member_rows(admin.core.DB, [(7, "Sena", "phone-a")])
            with sqlite3.connect(admin.core.DB) as con:
                con.execute("CREATE TABLE PlayLog (id INTEGER PRIMARY KEY, user_id INTEGER, pattern_id INTEGER, score INTEGER, "
                            "grade TEXT, judgement INTEGER, is_record INTEGER, played_at INTEGER)")
                con.execute("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at) VALUES (7, 11, 900000, 'S', 950, 1, ?)",
                            (now() - 60,))
            os.makedirs(inst.path("content"))
            inst.write("content/songs.json", json.dumps([{"song_id": 1, "name": "paperplanes", "full_name": "Paper Planes",
                                                          "song_patterns": [{"pattern_id": 11, "line": 3, "signature": 1, "difficulty": 3}]}]))
            # A token to ask with, made as the Accounts page makes one (it adds the tokens' table, which the game never reads).
            with admin.app.test_request_context():
                _, secret = tokens.make("old", "read", ("admin", True, None))
            ask = lambda path: inst.client.get(V1 + path, headers={"Authorization": "Bearer " + secret})
            answers = {path: ask(path) for path in ("/site/charts/11/ranking", "/site/players/7/records", "/site/players/7", "/site/rankings",
                                                    "/site/rankings/month", "/site/home", "/status", "/logs/plays")}
            self.assertEqual({path: r.status_code for path, r in answers.items()}, dict.fromkeys(answers, 200))
            self.assertEqual([p["keys"] for p in answers["/site/charts/11/ranking"].get_json()["items"]], [False])
            self.assertEqual([p["keys"] for p in answers["/site/players/7/records"].get_json()["items"]], [False])
            self.assertEqual([p["keys_charts"] for p in answers["/site/rankings"].get_json()["items"]], [0])
            self.assertEqual([p["keys_charts"] for p in answers["/site/rankings/month"].get_json()["items"]], [0])
            self.assertEqual([p["keys"] for p in answers["/status"].get_json()["recent"]], [False])
            self.assertEqual([p["keys"] for p in answers["/logs/plays"].get_json()["items"]], [False])


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class AsTheSiteCountsTest(unittest.TestCase):
    """The players' site's figures as the site counts them (server/portal): what a player's levels count, and how the
    months of the rankings are named, whatever zone the server's clock is in."""

    def test_a_hidden_song_counts_in_no_level(self):
        # Sena holds records on both charts of Paper Planes (levels 3 and 7). Hidden, the song is in neither number of
        # any level, as on player.php: a level would otherwise say more records than the charts players can see.
        with Server() as inst:
            before = {lv["level"]: (lv["charts"], lv["records"]) for lv in inst.ask("GET", "/site/players/7").get_json()["levels"]}
            self.assertEqual((before[3], before[7]), ((1, 1), (1, 1)))
            listed = admin.site.song_list()
            for song in listed:
                if song["song_id"] == 1:
                    song["hidden_yn"] = "Y"
            inst.write("custom/songList.json", json.dumps(listed))
            after = {lv["level"]: (lv["charts"], lv["records"]) for lv in inst.ask("GET", "/site/players/7").get_json()["levels"]}
            self.assertEqual(after, {k: v for k, v in before.items() if k not in (3, 7)})

    def test_the_average_accuracy_is_rounded_as_the_site_rounds_it(self):
        # To the tenth of a percent with the half up, in whole per-mille: the site cut 967.53 to 96.7 where this said 96.8,
        # and Python's round() takes a half to the even tenth (96.25 to 96.2) where the site's rule takes it up.
        self.assertEqual([admin.site.accuracy(j) for j in (967.53, 967.5, 962.5, 967.4999, 1000, 0)], [96.8, 96.8, 96.3, 96.7, 100.0, 0.0])
        self.assertIsNone(admin.site.accuracy(None))
        # The site's own rule, for the same figures: accuracy() in lib.php, the same floor of the half added.
        lib = os.path.join(PORTAL, "lib.php")
        if os.path.isfile(lib):
            with open(lib, encoding="utf-8") as f:
                self.assertIn("number_format(floor((float)$judgement + 0.5) / 10, 1)", f.read())

    def test_the_months_are_named_in_utc_west_of_it(self):
        # A month's rankings begin at midnight UTC on its first day (the game counts down to it), and the site names the
        # month in UTC too (lib.php month_name()): on a clock in New York that moment is still the evening before, which
        # named every month of the hall of fame one month early there.
        zone = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        try:
            with Server() as inst:
                start = admin.site.month_start(1)
                with sqlite3.connect(admin.core.DB) as con:
                    con.execute("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at) "
                                "VALUES (7, 11, 1000, 'A', 900, 0, ?)", (start + 3600,))
                months = inst.ask("GET", "/site/rankings/month").get_json()["past_months"]
                self.assertEqual(months[0]["month"], time.strftime("%Y-%m", time.gmtime(start)))
                # Where New York's own clock would have put that moment.
                self.assertNotEqual(months[0]["month"], time.strftime("%Y-%m", time.localtime(start)))
        finally:
            if zone is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = zone
            time.tzset()


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class BuildTest(unittest.TestCase):
    """A build waits for an import, and two asked for at once start one builder."""

    def test_a_build_is_refused_while_an_import_runs_on_the_page_and_through_the_api(self):
        with Server() as inst:
            running = threading.Event()
            # An import that runs until this test lets it end.
            job = admin.jobs.start_task("import", lambda say: running.wait(20) and None, path="x")
            try:
                r = inst.ask("POST", "/builds", json={})
                self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "busy"))
                self.assertEqual(r.get_json()["error"]["message"], "An import is running already: wait for it to end.")
                # The App page refuses it the same way, in its own words.
                page = inst.client.post("/opendmtq/admin/app", data={"csrf": page_token(inst), "host": ""}, follow_redirects=True).get_data(as_text=True)
                self.assertIn("An import is running already", page)
                self.assertFalse([j for j in admin.jobs._jobs.values() if j["kind"] == "build"])
            finally:
                running.set()
            wait_job(inst, job)

    def test_two_builds_asked_for_at_once_start_one(self):
        real = admin.jobs.start_job

        def slow(kind, cmd, env=None, explain=None, **details):
            # The moment between the look for a running build and its start, made long: two calls without the lock
            # would both pass it.
            time.sleep(0.3)
            return real(kind, [sys.executable, "-c", "import time; time.sleep(1)"], env=env, explain=explain, **details)

        with Server() as inst, mock.patch.object(admin.jobs, "start_job", slow):
            answers = []

            def ask():
                client = admin.app.test_client()
                answers.append(client.post(V1 + "/builds", json={}, headers={"Authorization": "Bearer " + Server.secrets["owner"]}).status_code)
            threads = [threading.Thread(target=ask) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(sorted(answers), [202, 409])
            self.assertEqual(len([j for j in admin.jobs._jobs.values() if j["kind"] == "build"]), 1)
            for j in list(admin.jobs._jobs.values()):
                wait_job(inst, j["id"])


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class NamesTest(unittest.TestCase):
    """A file's name in an address stays in its folder: no separator of any system, no leading dot, no ".."."""

    LEADING_OUT = ("a\\..\\..\\{}", "C:\\{}", "..\\{}", "x..y{}", ".{}", "a b{}", "C:{}")

    def test_backups_and_builds_take_plain_names_only(self):
        with Server() as inst:
            backups = admin.core.BACKUPS
            for form in self.LEADING_OUT:
                for kind, folder, suffix, routes in (
                        ("backup", backups, ".tar.gz", [("GET", "/backups/{}/download", "backup_not_found"), ("DELETE", "/backups/{}", "backup_not_found"),
                                                        ("POST", "/backups/{}/restore", "backup_not_found")]),
                        ("build", os.path.join(admin.core.APK, "out"), ".apk", [("GET", "/builds/{}/download", "not_found"), ("DELETE", "/builds/{}", "build_not_found")])):
                    name = form.format("OpenDMTQ-y" + suffix if kind == "build" else "z" + suffix)
                    # The file is there, under that very name (Linux takes a backslash in a name): the name alone is refused.
                    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                        f.write("x")
                    for method, path, code in routes:
                        r = inst.ask(method, path.format(urllib.parse.quote(name, safe="")))
                        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (404, code), (method, name))
                    self.assertTrue(os.path.exists(os.path.join(folder, name)), name)
            # The names this server makes go through.
            self.assertEqual(inst.ask("GET", f"/backups/{Server.names['backup']}/download").status_code, 200)

    def test_the_check_itself(self):
        with admin.app.test_request_context():
            for name in ("a\\..\\x.tar.gz", "C:\\x.tar.gz", "C:x.tar.gz", "../x.tar.gz", "..tar.gz", ".x.tar.gz", "x/y.tar.gz", "", "x.zip"):
                with self.assertRaises(NotFound, msg=name):
                    admin.core.safe_name(name, tempfile.gettempdir(), ".tar.gz")


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class PathTest(unittest.TestCase):
    """A path the setup is asked about brings out nothing of the program's environment, and is never another computer's."""

    def test_names_of_settings_in_a_path_stay_as_they_are_written(self):
        with Server() as inst:
            patches = host_install(inst) + [mock.patch.dict(os.environ, {"ODQ_SECRET": "s3cret-value", "ADMIN_PASSWORD": "pw-value"})]
            for p in patches:
                p.start()
            try:
                for typed in ("$ODQ_SECRET", "${ODQ_SECRET}", "%ODQ_SECRET%", "~/$ADMIN_PASSWORD", "%ADMIN_PASSWORD%/x", "$HOME"):
                    for method, path, kw in (("GET", "/setup/what?path=" + urllib.parse.quote(typed), {}),
                                             ("GET", "/setup/folder?path=" + urllib.parse.quote(typed), {}),
                                             ("POST", "/setup/import", {"json": {"path": typed}})):
                        text = inst.ask(method, path, **kw).get_data(as_text=True)
                        self.assertNotIn("s3cret-value", text, (typed, path))
                        self.assertNotIn("pw-value", text, (typed, path))
                # Taken as written: from the home folder, as any path from no top.
                self.assertEqual(setup.clean_path("$ODQ_SECRET"), os.path.join(inst.path("home"), "$ODQ_SECRET"))
                self.assertEqual(setup.clean_path("%ODQ_SECRET%"), os.path.join(inst.path("home"), "%ODQ_SECRET%"))
            finally:
                for p in patches:
                    p.stop()

    def test_a_path_on_another_computer_is_refused_before_anything_looks_at_it(self):
        with Server() as inst:
            patches = host_install(inst)
            for p in patches:
                p.start()
            looked = []
            try:
                with mock.patch.object(setup.os, "stat", lambda *a, **k: looked.append(a) or (_ for _ in ()).throw(OSError())), \
                        mock.patch.object(setup.os, "scandir", lambda *a, **k: looked.append(a) or (_ for _ in ()).throw(OSError())):
                    for typed in ("\\\\server\\share", "//server/share/x", "\\\\?\\UNC\\server\\share", "file://nas/share/DMTQ", "\\/server/share"):
                        for method, path, kw in (("GET", "/setup/what?path=" + urllib.parse.quote(typed), {}),
                                                 ("GET", "/setup/folder?path=" + urllib.parse.quote(typed), {}),
                                                 ("POST", "/setup/import", {"json": {"path": typed}})):
                            r = inst.ask(method, path, **kw)
                            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (400, "network_path"), (typed, path))
                            self.assertEqual(r.get_json()["error"]["message"], "Only folders on this PC open here. Find the folder below.")
                self.assertEqual(looked, [])
            finally:
                for p in patches:
                    p.stop()


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class FilterTest(unittest.TestCase):
    """The Logs page's filters through the API: the words, the days, as its forms send them."""

    def test_the_requests_by_their_words(self):
        with Server() as inst:
            found = inst.ask("GET", "/logs/requests?q=" + urllib.parse.quote("/missing")).get_json()
            self.assertEqual((found["matched"], [r["path"] for r in found["items"]]), (1, ["/missing"]))
            # With the other filters at once, as the form sends all three.
            self.assertEqual(inst.ask("GET", "/logs/requests?q=DMQ&status=5xx&kind=game").get_json()["matched"], 1)

    def test_the_plays_by_their_words_and_days(self):
        with Server() as inst:
            self.assertEqual(inst.ask("GET", "/logs/plays?q=Yuna").get_json()["total"], 2)
            today = datetime.date.today()
            # The last two days hold the three plays of today; four days back, all four.
            both = inst.ask("GET", f"/logs/plays?from={today - datetime.timedelta(days=1)}&to={today}").get_json()
            self.assertEqual(both["total"], 3)
            self.assertEqual(inst.ask("GET", f"/logs/plays?from={today - datetime.timedelta(days=4)}&to={today}").get_json()["total"], 4)
            # Days the wrong way round are taken as they were meant, as on the page.
            self.assertEqual(inst.ask("GET", f"/logs/plays?from={today}&to={today - datetime.timedelta(days=1)}").get_json()["total"], 3)
            # Words and days together, and in the file (Sena's two plays are an hour and two old: within the last two days
            # at any time of the day).
            since = today - datetime.timedelta(days=1)
            self.assertEqual(inst.ask("GET", f"/logs/plays?q=Sena&from={since}&to={today}").get_json()["total"], 2)
            self.assertEqual(inst.ask("GET", f"/logs/plays/download?q=Sena&from={since}&to={today}").data.count(b"\n"), 3)


# ------------------------------------------------------------------------------ what the API says of itself

def openapi_problems(doc):
    """What is wrong with an OpenAPI 3.1 document, as far as its shape goes: [] when nothing."""
    out = []
    if not str(doc.get("openapi", "")).startswith("3.1."):
        out.append("openapi is not 3.1.x")
    if not (doc.get("info", {}).get("title") and doc.get("info", {}).get("version")):
        out.append("info needs a title and a version")
    schemas = doc.get("components", {}).get("schemas", {})
    refs = []

    def walk(node, where):
        if isinstance(node, dict):
            if "$ref" in node:
                refs.append((node["$ref"], where))
            for k, v in node.items():
                walk(v, f"{where}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{where}[{i}]")

    walk(doc, "doc")
    for ref, where in refs:
        if not ref.startswith("#/components/schemas/") or ref.rsplit("/", 1)[1] not in schemas:
            out.append(f"{where}: {ref} leads nowhere")
    ids = []
    tags = {t["name"] for t in doc.get("tags", [])}
    for path, item in doc.get("paths", {}).items():
        if not path.startswith("/"):
            out.append(f"{path}: not a path")
        for method, op in item.items():
            where = f"{method.upper()} {path}"
            if method not in ("get", "put", "post", "delete", "patch"):
                out.append(f"{where}: no such method")
            ids.append(op.get("operationId"))
            if not op.get("summary"):
                out.append(f"{where}: no summary")
            if not set(op.get("tags", [])) <= tags:
                out.append(f"{where}: a tag that is not listed")
            named = set(re.findall(r"{(\w+)}", path))
            params = op.get("parameters", [])
            for p in params:
                if not {"name", "in", "schema"} <= set(p) or p["in"] not in ("path", "query"):
                    out.append(f"{where}: a parameter without name, in or schema")
                if p.get("in") == "path" and not p.get("required"):
                    out.append(f"{where}: path parameter {p.get('name')} not required")
            if {p["name"] for p in params if p.get("in") == "path"} != named:
                out.append(f"{where}: its path parameters are not those of its path")
            body = op.get("requestBody")
            if body and not set(body.get("content", {})) <= {"application/json", "multipart/form-data"}:
                out.append(f"{where}: a body of another type")
            responses = op.get("responses", {})
            if not responses:
                out.append(f"{where}: no responses")
            for code, answer in responses.items():
                if not re.fullmatch(r"[1-5][0-9][0-9]", code) or not answer.get("description"):
                    out.append(f"{where}: response {code} without a status or a description")
    if len(ids) != len(set(ids)) or None in ids:
        out.append("operationIds missing or used twice")
    scheme = doc.get("components", {}).get("securitySchemes", {}).get("token", {})
    if (scheme.get("type"), scheme.get("scheme")) != ("http", "bearer"):
        out.append("no bearer scheme")
    return out


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class DocumentTest(unittest.TestCase):
    def document(self):
        with Server() as inst:
            r = inst.client.get(V1 + "/openapi.json")
            self.assertEqual(r.status_code, 200)
            return r.get_json()

    def test_the_document_is_openapi_3_1_in_shape(self):
        doc = self.document()
        self.assertEqual(openapi_problems(doc), [])
        # Every route has a summary, its parameters, its body and its answers, and says which scope it needs.
        for route in api_routes.ROUTES:
            op = doc["paths"][route.path][route.method.lower()]
            self.assertEqual(op["operationId"], route.name)
            self.assertIn(str(route.status), op["responses"])
            if route.scope:
                self.assertEqual(op["x-scope"], route.scope)
                self.assertIn("401", op["responses"])
            else:
                self.assertEqual(op["security"], [])
            if route.body or route.upload:
                self.assertIn("requestBody", op)

    def test_the_document_lists_exactly_the_routes_flask_has(self):
        doc = self.document()
        listed = {(method.upper(), path) for path, item in doc["paths"].items() for method in item}
        flask = set()
        for rule in admin.app.url_map.iter_rules():
            if rule.rule.startswith(V1 + "/") or rule.rule == V1:
                # A part with its converter (<int(max=...):player>) by its name alone, as the document writes it.
                path = re.sub(r"<(?:\w+(?:\([^)]*\))?:)?(\w+)>", r"{\1}", rule.rule[len(V1):])
                flask |= {(m, path) for m in rule.methods - {"HEAD", "OPTIONS"}}
        self.assertEqual(listed, flask)
        # Nothing else of Flask's is under the API's address.
        self.assertFalse([r.rule for r in admin.app.url_map.iter_rules() if r.rule.startswith("/opendmtq/api") and not r.rule.startswith(V1 + "/")])

    def test_every_route_has_its_handler_and_every_handler_its_route(self):
        self.assertEqual(set(api.HANDLERS), set(api_routes.by_name()))

    def test_unknown_addresses_and_methods_answer_in_the_apis_shape(self):
        with Server() as inst:
            r = inst.ask("GET", "/nope")
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (404, "not_found"))
            r = inst.ask("PATCH", "/builds")
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (405, "method_not_allowed"))
            self.assertEqual(r.headers["Allow"], "GET, POST")


# ------------------------------------------------------------------------------ nothing of the pages without its route

# Every admin page's data, and every action of its forms, with the API routes that give the same or do the same. A key is
# an endpoint (the page, or a form's address), endpoint:action for a form's action, or endpoint?name=value for a page's
# own variants (a tab, a file). What has no route says why.
PAGE_ACTIONS = {
    "dashboard": ["status", "status_machine", "status_activity", "invite_get"],
    "app_page": ["app_get", "builds_list", "builds_start", "job_get"],
    "app_page?built": ["job_get"],
    "app_page?job": ["job_get"],
    "app_page?host": ["builds_start"],
    "invite_qr": ["invite_qr"],
    "app_icon": ["app_icon"],
    "app_prune": ["builds_prune"],
    "app_download": ["build_download"],
    "app_windows": ["app_windows"],
    "app_delete": ["build_delete"],
    "job_status": ["job_get"],
    "songs_page": ["songs_list"],
    # A change to the songs, followed while it runs.
    "songs_page?job": ["job_get"],
    "songs_page:upload": ["songs_add"],
    "songs_page:hide": ["song_hide"],
    "songs_page:show": ["song_show"],
    "songs_page:remove": ["song_remove"],
    "maintenance_page": ["maintenance_get"],
    "maintenance_page:on": ["maintenance_set"],
    "maintenance_page:off": ["maintenance_clear"],
    "server_stop": ["server_stop"],
    "players_page": ["players_list"],
    "players_page?csv": ["players_download"],
    "player_action": ["player_get"],
    "player_action:rename": ["player_rename"],
    "player_action:reset": ["player_reset"],
    "player_action:delete": ["player_delete"],
    "player_action:live-on": ["player_live_on"],
    "player_action:live-off": ["player_live_off"],
    "accounts_page": ["accounts_list", "tokens_list"],
    "accounts_page:create": ["accounts_create"],
    "accounts_page:password": ["account_password"],
    "accounts_page:off": ["account_disable"],
    "accounts_page:on": ["account_enable"],
    "accounts_page:admin": ["account_make_admin"],
    "accounts_page:player": ["account_make_player"],
    "accounts_page:link": ["account_link"],
    "accounts_page:delete": ["account_delete"],
    "accounts_page:token": ["tokens_create"],
    "accounts_page:revoke": ["token_revoke"],
    "recordings_page": ["recordings_list", "recordings_limits", "broadcasts_get"],
    "recordings_page:broadcasts-on": ["broadcasts_set"],
    "recordings_page:broadcasts-off": ["broadcasts_set"],
    "recordings_page:settings": ["broadcasts_set"],
    "recordings_page?watch": ["recording_get", "recording_file"],
    "recordings_page:limits": ["recordings_set_limits"],
    "recordings_page:hide": ["recording_hide"],
    "recordings_page:show": ["recording_show"],
    "recordings_page:delete": ["recording_delete", "recordings_delete"],
    "recordings_page:delete-player": ["recordings_delete"],
    "recording_download": ["recording_download"],
    "recording_media": ["recording_file"],
    "backups_page": ["backups_list", "backups_auto_get"],
    # A backup or a restore of the page's, followed while it runs.
    "backups_page?job": ["job_get"],
    "backups_page:create": ["backups_create"],
    "backups_page:upload": ["backups_upload"],
    "backups_auto": ["backups_auto_set"],
    "backups_auto:on": ["backups_auto_set"],
    "backups_auto:off": ["backups_auto_set"],
    "backup_download": ["backup_download"],
    "backup_action": ["backups_list"],
    "backup_action:delete": ["backup_delete"],
    "backup_action:restore": ["backup_restore"],
    "logs_page": ["logs_requests"],
    "logs_page?rows": ["logs_requests"],
    "logs_page?tab=plays": ["logs_plays"],
    "logs_page?tab=changes": ["logs_changes"],
    "logs_page?csv": ["logs_plays_download"],
    "logs_page?page": ["logs_plays"],
    "logs_page?player": ["logs_plays"],
    "logs_download": ["logs_requests_download"],
    "setup_page": ["setup_get"],
    "setup_page?step=files": ["setup_get", "setup_found", "setup_folder"],
    "setup_page?step=address": ["setup_get"],
    "setup_page?step=players": ["setup_get"],
    "setup_page?step=app": ["setup_get"],
    "setup_page?dir": ["setup_folder"],
    "setup_page?job": ["job_get"],
    "setup_what": ["setup_what"],
    "setup_import": ["setup_import"],
    "setup_address": ["setup_address"],
    "setup_player": ["setup_player"],
    "setup_build": ["setup_build"],
    # Which process answers, during a restart the setup asked for: /status says it too (instance).
    "setup_ping": ["status"],
    "setup_start": "the one-time link that signs a browser in on the server PC: the API takes a token instead",
    "login": "a browser's sign-in: the API takes a token instead",
    "logout": "a browser's sign-out: a token is revoked instead",
    "set_lang": "the pages' language: the API answers in English",
    "old_address": "the pages' old address, which leads to the new one",
    "static": "the pages' own stylesheet and script",
    "public_css": "the site's look, kept for these pages",
    "public_font": "the site's look, kept for these pages",
    "public_favicon": "the site's look, kept for these pages",
    "public_hls": "the video player the Recordings page loads",
}

# Every page of the players' site (server/portal) with the routes that give what it shows; the files that are no page.
SITE_PAGES = {
    "index.php": ["site_home", "site_live"],
    "download.php": ["site_home", "invite_get", "invite_qr", "app_icon"],
    "apk.php": ["build_download"],
    "windows.php": ["app_windows"],
    "icon.php": ["app_icon"],
    "qr.php": ["invite_qr"],
    "songs.php": ["site_songs"],
    "song.php": ["site_song", "site_chart_ranking"],
    "ranking.php": ["site_rankings", "site_rankings_month"],
    "player.php": ["site_player", "site_player_records", "site_plays_recent"],
    "live.php": ["site_live"],
    "live-media.php": ["site_live_file", "recording_file"],
    "health.php": ["status_health"],
    "licenses.php": "the license texts, which are in the repository",
    "login.php": "the site's sign-in: the API takes a token instead",
    "client.php": "the PC client's sign-in by the site's cookie and its look at the app on offer: the API takes a token, and GET /app has the app",
    "lang.php": "the site's language switch: the API answers in English",
    "notfound.php": "the site's page for an address that leads nowhere",
}
SITE_LIBRARIES = {"lib.php", "live_lib.php", "ranking_lib.php", "auth.php", "strings.php"}

# The page each template is, for its forms without an address of their own (they post to the page).
TEMPLATE_PAGES = {"accounts.html": "accounts_page", "app.html": "app_page", "backups.html": "backups_page", "dashboard.html": "dashboard",
                  "logs.html": "logs_page", "maintenance.html": "maintenance_page", "players.html": "players_page",
                  "recordings.html": "recordings_page", "setup.html": "setup_page", "songs.html": "songs_page", "login.html": "login"}

# The arguments of an address that make a page show another of its views (a tab, a step, a file), or follow a job.
VARIANTS = ("tab", "step", "csv", "watch", "dir", "page", "player", "built", "job", "host")

# Every argument a page's address takes, with where the API takes the same: ("query" | "path" | "body", the route, its
# names there), ("view", routes...) for one that chooses which of the page's views shows (the routes that give them), or
# why there is none. The keys: the fields of the pages' GET forms and what the pages' code reads of their address
# (endpoint?name, endpoint?tab=x&name inside a tab), and what the players' site reads (file?name).
GET_ARGS = {
    # The App page: a build to follow or just ended, and the address field kept after a refused build.
    "app_page?job": ("path", "job_get", "job"),
    "app_page?built": ("path", "job_get", "job"),
    "app_page?host": ("body", "builds_start", "host"),
    # A backup, a restore or a change to the songs that its page follows.
    "backups_page?job": ("path", "job_get", "job"),
    "songs_page?job": ("path", "job_get", "job"),
    # The Players page's spreadsheet.
    "players_page?csv": ("view", "players_download"),
    # A change to a player from the Players page: whom the page saw the number belong to, in the address, as the API's
    # writes take it.
    "player_action?seen": ("query", "player_rename", "seen"),
    # The Logs page: its tabs, the Requests tab's filter form, the rows it fetches again while it follows the log.
    "logs_page?tab": ("view", "logs_requests", "logs_plays", "logs_changes"),
    "logs_page?q": ("query", "logs_requests", "q"),
    "logs_page?status": ("query", "logs_requests", "status"),
    "logs_page?kind": ("query", "logs_requests", "kind"),
    "logs_page?rows": ("view", "logs_requests"),
    # The Plays tab: its filter form, its pages and its spreadsheet.
    "logs_page?tab=plays&q": ("query", "logs_plays", "q"),
    "logs_page?tab=plays&player": ("query", "logs_plays", "player"),
    "logs_page?tab=plays&from": ("query", "logs_plays", "from"),
    "logs_page?tab=plays&to": ("query", "logs_plays", "to"),
    "logs_page?tab=plays&page": ("query", "logs_plays", "page"),
    "logs_page?tab=plays&csv": ("view", "logs_plays_download"),
    # The Recordings page's player, on the recording asked for.
    "recordings_page?watch": ("path", "recording_get", "player", "recording"),
    # The setup: its steps, a job to follow, the folder picker's path (its form's field, and the places' links).
    "setup_page?step": ("view", "setup_get"),
    "setup_page?job": ("path", "job_get", "job"),
    "setup_page?dir": ("query", "setup_folder", "path"),
    "setup_page?step=files&dir": ("query", "setup_folder", "path"),
    "setup_what?path": ("query", "setup_what", "path"),
    "setup_start?key": "the one-time link that signs a browser in on the server PC: the API takes a token instead",
    "setup_start?step": "the step that one-time link opens, in a browser",
    "login?next": "the page a browser goes back to after signing in: the API has no sign-in",
    "set_lang?to": "the pages' language: the API answers in English",
    "set_lang?next": "the page a browser goes back to after the language switch",
    # The players' site.
    "index.php?live": ("view", "site_live"),
    "player.php?id": ("path", "site_player", "player"),
    "song.php?id": ("path", "site_song", "song"),
    "song.php?chart": ("path", "site_chart_ranking", "chart"),
    "ranking.php?sort": ("query", "site_rankings", "sort"),
    "live.php?list": ("view", "site_live"),
    "live.php?past": ("view", "site_live"),
    "live.php?p": ("path", "site_live_file", "player"),
    "live.php?r": ("path", "recording_file", "player", "recording"),
    "live_lib.php?ids": "a phone's upload of its broadcast, which only the phone sends, with its own key",
    "login.php?next": "the page a browser goes back to after the site's sign-in: the API has no sign-in",
    "login.php?logout": "the site's sign-out: a token is revoked instead",
    "client.php?about": ("view", "status_health"),
    "client.php?signin": "the PC client's sign-in by the site's cookie: the API takes a token instead",
    "client.php?app": ("view", "app_get"),
    "lang.php?to": "the site's language: the API answers in English",
    "lang.php?next": "the page a browser goes back to after the language switch",
}

# Functions that read a page's address for it, with the page (and its tab) they read it for.
ARG_HELPERS = {"plays_tab": "logs_page?tab=plays", "recordings_view": "recordings_page"}

# What the pages' script (static/admin.js) adds to a page's own address, with the page it does that on: the Logs page's
# look at new requests asks for its rows alone.
SCRIPT_ARGS = {"rows": "logs_page"}


def page_actions():
    """What the admin pages have, as PAGE_ACTIONS keys: every endpoint Flask has for them, every action of every form,
    and every variant of a page its own links and scripts ask for."""
    found = set()
    for rule in admin.app.url_map.iter_rules():
        if not rule.endpoint.startswith("api_"):
            found.add(rule.endpoint)
    templates = os.path.join(ADMIN_DIR, "templates")

    def actions_in(markup):
        """Every action the buttons and fields of a piece of a template name."""
        actions = set()
        for value in re.findall(r'name="action"[^>]*value="([^"]*)"|value="([^"]*)"[^>]*name="action"', markup):
            value = value[0] or value[1]
            # Literal words, or those a {{ ... }} chooses between; "hide {{ name }}" is hide.
            literal = re.sub(r"{{.*?}}", "", value).split()
            actions |= set(literal[:1]) | set(re.findall(r"'([a-z-]+)'", " ".join(re.findall(r"{{(.*?)}}", value))))
        return actions

    for name in sorted(os.listdir(templates)):
        with open(os.path.join(templates, name), encoding="utf-8") as f:
            text = f.read()
        # The forms that send something: their address, and every action their buttons and fields name.
        for form in re.finditer(r"<form\b([^>]*)>(.*?)</form>", text, re.S):
            head, body = form.group(1), form.group(2)
            if 'method="post"' not in head:
                continue
            target = re.search(r"url_for\('(\w+)'", head)
            endpoint = target.group(1) if target else TEMPLATE_PAGES.get(name)
            if endpoint is None:
                raise AssertionError(f"{name}: a form that posts to its page, which TEMPLATE_PAGES does not name")
            found |= {f"{endpoint}:{a}" for a in actions_in(body)} or {endpoint}
        # A button that sends a form to an address of its own (formaction), wherever it is: the Players page's switches,
        # each in its row, all of them the page's one form.
        for button in re.finditer(r"<button\b[^>]*\bformaction=\"\{\{ url_for\('(\w+)'[^>]*>", text):
            found |= {f"{button.group(1)}:{a}" for a in actions_in(button.group(0))} or {button.group(1)}
        # What its scripts add to the page's own address.
        for arg in re.findall(r"searchParams\.set\('(\w+)'", text):
            found.add(f"{TEMPLATE_PAGES.get(name)}?{arg}")
    # What the pages' script adds, on the page SCRIPT_ARGS names (one it does not name fails here).
    with open(os.path.join(ADMIN_DIR, "static", "admin.js"), encoding="utf-8") as f:
        for arg in re.findall(r"searchParams\.set\('(\w+)'", f.read()):
            if arg not in SCRIPT_ARGS:
                raise AssertionError(f"admin.js adds ?{arg}= to a page SCRIPT_ARGS does not name")
            found.add(f"{SCRIPT_ARGS[arg]}?{arg}")
    # A page's own variants: what its links, and the redirects of the pages' code, ask of it by name.
    sources = [os.path.join(templates, n) for n in os.listdir(templates)] + [os.path.join(ADMIN_DIR, n) for n in os.listdir(ADMIN_DIR) if n.endswith(".py")]
    for path in sources:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for link in re.finditer(r"url_for\([\"'](\w+)[\"']((?:, *\w+=[^,)]+)*)", text):
            for arg, value in re.findall(r"(\w+)=([^,)]+)", link.group(2)):
                if arg in ("tab", "step"):
                    # A tab or a step by its name; one chosen at run time is each of them, found by their own names.
                    if value[:1] in "'\"":
                        found.add(f"{link.group(1)}?{arg}={value.strip(chr(39) + chr(34))}")
                elif arg in VARIANTS:
                    found.add(f"{link.group(1)}?{arg}")
    return found


def page_args():
    """What the pages' addresses take, as GET_ARGS keys: every field of the admin pages' GET forms (inside the tab or step
    a hidden field of the form names), every name the admin pages' code reads of its address (request.args, by the page
    whose function reads it), and every name the players' site reads ($_GET)."""
    found = set()
    templates = os.path.join(ADMIN_DIR, "templates")
    for name in sorted(os.listdir(templates)):
        with open(os.path.join(templates, name), encoding="utf-8") as f:
            text = f.read()
        for form in re.finditer(r"<form\b([^>]*)>(.*?)</form>", text, re.S):
            head, body = form.group(1), form.group(2)
            # A form that posts, or a dialog's: no address of a page.
            if re.search(r'method="(post|dialog)"', head):
                continue
            target = re.search(r"url_for\('(\w+)'", head)
            endpoint = target.group(1) if target else TEMPLATE_PAGES[name]
            # A hidden tab or step: the form is that view's, and its own field is the view's choice.
            context = ""
            for field, value in re.findall(r'<input type="hidden" name="(tab|step)" value="([^"{]+)"', body):
                context = f"{field}={value}&"
                found.add(f"{endpoint}?{field}")
            for field in re.findall(r'<(?:input|select|textarea)\b[^>]*\bname="(\w+)"', body):
                if field not in ("tab", "step"):
                    found.add(f"{endpoint}?{context}{field}")
    # The admin pages' code: request.args.get("x") and request.args["x"], by the view function that reads it.
    views = {fn.__name__: endpoint for endpoint, fn in admin.app.view_functions.items() if not endpoint.startswith("api_")}
    for name in sorted(os.listdir(ADMIN_DIR)):
        if not name.endswith(".py") or name.startswith("api"):
            continue
        with open(os.path.join(ADMIN_DIR, name), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                read = None
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
                    read, holder = node.args[0], node.func.value
                elif isinstance(node, ast.Subscript):
                    read, holder = node.slice, node.value
                if read is None or not isinstance(read, ast.Constant) or not isinstance(read.value, str):
                    continue
                if not (isinstance(holder, ast.Attribute) and holder.attr == "args" and isinstance(holder.value, ast.Name) and holder.value.id == "request"):
                    continue
                if fn.name in ARG_HELPERS:
                    page = ARG_HELPERS[fn.name]
                    found.add(f"{page}&{read.value}" if "?" in page else f"{page}?{read.value}")
                elif fn.name in views:
                    found.add(f"{views[fn.name]}?{read.value}")
                else:
                    raise AssertionError(f"{name}: {fn.name} reads ?{read.value}= for no page ARG_HELPERS or Flask names")
    # The players' site, its pages and their libraries.
    if os.path.isdir(PORTAL):
        for name in sorted(os.listdir(PORTAL)):
            if name.endswith(".php"):
                with open(os.path.join(PORTAL, name), encoding="utf-8") as f:
                    found |= {f"{name}?{arg}" for arg in re.findall(r"\$_GET\['(\w+)'\]", f.read())}
    return found


# One piece of a PHP constant's value: a quoted string, the name of another constant, the dot that joins them, or the
# semicolon that ends it. A double-quoted string with a $ in it would put a variable in: it matches nothing here.
PHP_PIECE = re.compile(r"""\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\$]|\\.)*)"|([A-Z_][A-Z0-9_]*)|(\.)|(;))""", re.S)


def php_constant(text, name):
    """A string constant of a PHP file as PHP makes it (const NAME = 'a' . OTHER . "b";): its quoted pieces joined, the
    constants it names put in. Anything else in it fails the test instead of being guessed at."""
    found = re.search(rf"^const {name} = ", text, re.M)
    if not found:
        raise AssertionError(f"no const {name} in the PHP")
    pos, pieces = found.end(), []
    while True:
        piece = PHP_PIECE.match(text, pos)
        if not piece:
            raise AssertionError(f"const {name}: cannot read {text[pos:pos + 40]!r}")
        pos = piece.end()
        single, double, other, dot, end = piece.groups()
        if end:
            return "".join(pieces)
        if dot:
            continue
        if other:
            # Another constant of the same file, as PHP puts it in.
            pieces.append(php_constant(text, other))
        elif single is not None:
            # In single quotes only \' and \\ mean something.
            pieces.append(re.sub(r"\\([\\'])", r"\1", single))
        else:
            # In double quotes, the escapes PHP knows; any other backslash stays as it is, as in PHP.
            pieces.append(re.sub(r'\\([\\"$nt])', lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), double))


# What the game's odq_sql_score('p.score') makes (server/game/src/util.php): the cap every ranking puts on a stored score.
GAME_SCORE_SQL = "MIN(MAX(p.score, 0), 2147483647)"


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class SameQueriesAsTheSiteTest(unittest.TestCase):
    """The players' site (server/portal/ranking_lib.php) and these pages and the API (core.py, site.py) keep their own copies of
    the queries that decide who counts as a player and what a score counts for: the copies must say the same."""

    @staticmethod
    def same(sql):
        """A query as SQLite reads it, for comparing: one space wherever there is any, none at the ends."""
        return re.sub(r"\s+", " ", sql).strip()

    def test_the_shared_queries_are_the_sites(self):
        lib = os.path.join(PORTAL, "ranking_lib.php")
        if not os.path.isfile(lib):
            self.skipTest("the portal is not at hand")
        with open(lib, encoding="utf-8") as f:
            php = f.read()
        # The site's SCORE_SQL is the game's cap of a score (odq_sql_score() in server/game/src/util.php) on p.score: put
        # in as the string it makes, which php_constant() can read, where the site takes it from the game.
        taken = "define('SCORE_SQL', odq_sql_score('p.score'));"
        self.assertIn(taken, php)
        php = php.replace(taken, f"const SCORE_SQL = '{GAME_SCORE_SQL}';")
        ours = {"PLAYER_ROWS": admin.core.PLAYER_ROWS, "SCORE_SQL": admin.site.SCORE_SQL,
                "PLAYER_FIGURES": admin.site.PLAYER_FIGURES, "PLAYER_TOTALS": admin.site.PLAYER_TOTALS,
                # The keyboard's counts beside a total and a month's score, and the month's first look.
                "KEYS_BESTS": admin.site.KEYS_BESTS, "KEYS_IN_MONTH": admin.site.KEYS_IN_MONTH, "MONTH_KEYS": admin.site.MONTH_KEYS}
        for name, query in ours.items():
            # Each on its own: a change to one the others take in shows in all of them.
            with self.subTest(name):
                # PHP binds the check account, a month's bounds and the players asked for by name (:check, :since, :until,
                # :players), Python by place (?).
                theirs = re.sub(r":(?:check|since|until|players)\b", "?", php_constant(php, name))
                self.assertEqual(self.same(query), self.same(theirs))

    def test_the_games_score_cap_is_the_one_read_above(self):
        util = os.path.join(PORTAL, "..", "game", "src", "util.php")
        if not os.path.isfile(util):
            self.skipTest("the game server is not at hand")
        with open(util, encoding="utf-8") as f:
            text = f.read()
        # return "MIN(MAX($column, 0), " . OPENDMTQ_INT_MAX . ')'; with const OPENDMTQ_INT_MAX = 2147483647;
        cap = re.search(r"^const OPENDMTQ_INT_MAX = (\d+);", text, re.M)
        shape = re.search(r"function odq_sql_score\(\$column\)\s*\{\s*return \"MIN\(MAX\(\$column, 0\), \" \. OPENDMTQ_INT_MAX \. '\)';", text)
        self.assertTrue(cap and shape, "odq_sql_score() or OPENDMTQ_INT_MAX changed: GAME_SCORE_SQL must follow")
        self.assertEqual(GAME_SCORE_SQL, f"MIN(MAX(p.score, 0), {cap.group(1)})")


# The game's own monthly board (odq_month_board_sql() in server/game/src/ranking.php), which the site's months are.
GAME_RANKING = os.path.join(PORTAL, "..", "game", "src", "ranking.php")


def game_month_board_sql(text):
    """The statement odq_month_board_sql(NULL) returns (every chart), read from ranking.php as PHP makes it: its quoted
    pieces joined, the game's score cap put in as the string it makes, and no chart filter. Anything else in it fails the
    test instead of being guessed at."""
    found = re.search(r"function odq_month_board_sql\(\?array \$patterns\): string\s*\{(.*?)\n\}", text, re.S)
    if not found:
        raise AssertionError("no odq_month_board_sql() in ranking.php")
    body = found.group(1)
    # Its return statement alone, without the comments between its pieces.
    returned = re.sub(r"^\s*//.*$", "", body[body.index("return ") + len("return "):], flags=re.M)
    # The cap the game puts on a score (checked against util.php above, there on p.score), and no filter: every chart.
    returned = returned.replace("odq_sql_score('l.score')", "'" + GAME_SCORE_SQL.replace("p.score", "l.score") + "'")
    returned = returned.replace("$filter", "''")
    pos, pieces = 0, []
    while True:
        piece = PHP_PIECE.match(returned, pos)
        if not piece:
            raise AssertionError(f"odq_month_board_sql(): cannot read {returned[pos:pos + 40]!r}")
        pos = piece.end()
        single, double, other, dot, end = piece.groups()
        if end:
            return "".join(pieces)
        if dot:
            continue
        if single is None:
            # A constant or a double-quoted piece: not in the statement as it is written today.
            raise AssertionError(f"odq_month_board_sql(): a piece this test does not read: {piece.group(0)!r}")
        # In single quotes only \' and \\ mean something.
        pieces.append(re.sub(r"\\([\\'])", r"\1", single))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class SameMonthAsTheGameTest(unittest.TestCase):
    """The rankings' This month in the API (site.month_players) and the game's own board, run on one database: the same
    players in the same order, with the same scores and chart counts. The site's months are the game's board itself
    (ranking_lib.php), so the API's copy is the one that could drift."""

    def test_the_apis_month_is_the_games_board(self):
        if not os.path.isfile(GAME_RANKING):
            self.skipTest("the game server is not at hand")
        with open(GAME_RANKING, encoding="utf-8") as f:
            board_sql = game_month_board_sql(f.read())
        # A month of thirty days, from its first second to the one before the next month.
        since, until = 1_700_000_000, 1_702_592_000
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "game.db")
            # The game's tables as an older server left them, then brought up to date as a restore does.
            old_game_database(db, [])
            # Players 1 to 4 (3 has no name yet) and the server's own check account (5).
            member_rows(db, [(1, "Ann", "phone-1"), (2, "Bo", "phone-2"), (3, "", "phone-3"), (4, "Cy", "phone-4"),
                             (5, "check", admin.core.CHECK_UDID)])
            con = sqlite3.connect(db)
            admin.backups.bring_schema_up_to_date(con)
            # A transfer code gave Cy a second phone: a second Member row with the same guid.
            con.execute("INSERT INTO Member (id, nickname, guid, udid) VALUES (6, 'Cy', '4', 'phone-6')")
            plays = [
                # Ann: one chart twice (the better play counts) and another on the month's last second.
                (1, 11, 500000, since), (1, 11, 700000, since + 10), (1, 12, 300000, until - 1),
                # Bo: Ann's total on two other charts, so the tie goes to the older account (Ann, the lower guid).
                (2, 21, 600000, since + 5), (2, 22, 400000, since + 6),
                # Player 3: a forged huge score counts as the cap, a negative one as nothing.
                (3, 11, 9_000_000_000, since + 7), (3, 12, -5, since + 8),
                # Cy, from either phone: one player.
                (4, 11, 100000, since + 9), (4, 12, 200000, since + 11),
                # Not this month: a second before it, and at the next month's start.
                (1, 13, 999999, since - 1), (2, 13, 999999, until),
                # The check account, and a guid without an account: never ranked.
                (5, 11, 999999, since + 1), (7, 11, 999999, since + 1),
            ]
            con.executemany("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at) "
                            "VALUES (?, ?, ?, 'A', 0, 0, ?)", plays)
            con.commit()
            # The API's queries read their rows by column name.
            con.row_factory = sqlite3.Row
            game = [tuple(row) for row in con.execute(board_sql, {"since": since, "until": until, "check": admin.core.CHECK_UDID})]
            ours = [(p["id"], p["score"], p["charts"]) for p in admin.site.month_players(con, since, until)]
            con.close()
        # The same board, row for row.
        self.assertEqual(ours, game)
        # And it is the board the plays above make, so that both cannot agree on an empty or a wrong one.
        self.assertEqual(game, [(3, 2147483647, 2), (1, 1000000, 2), (2, 1000000, 2), (4, 300000, 2)])


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class ParityTest(unittest.TestCase):
    """Nothing a person can do or see on the admin pages, or see on the players' site, without a route of the API."""

    def test_every_argument_of_a_pages_address_has_its_place_in_a_route(self):
        found = page_args()
        self.assertEqual(sorted(found - set(GET_ARGS)), [], "arguments of the pages' addresses without a place in the API: add them to GET_ARGS")
        # The table names nothing the pages no longer take (the site's part only where the portal is at hand).
        known = set(GET_ARGS) if os.path.isdir(PORTAL) else {k for k in GET_ARGS if ".php?" not in k}
        self.assertEqual(sorted(known - found), [])
        routes = api_routes.by_name()
        for key, where in GET_ARGS.items():
            if isinstance(where, str):
                continue
            kind, route, *names = where
            if kind == "view":
                # The view's routes, each one that reads.
                for name in [route] + names:
                    self.assertEqual(routes[name].method, "GET", key)
                continue
            places = {"query": [f.name for f in routes[route].query], "path": routes[route].params(), "body": [f.name for f in routes[route].body]}[kind]
            self.assertEqual([n for n in names if n not in places], [], f"{key}: {route} takes no {kind} {names}")

    def test_every_page_action_has_a_route(self):
        found = page_actions()
        self.assertEqual(sorted(found - set(PAGE_ACTIONS)), [], "page actions without a route: add them to the API and to PAGE_ACTIONS")
        # And the table names nothing the pages no longer have.
        self.assertEqual(sorted(set(PAGE_ACTIONS) - found), [])
        routes = api_routes.by_name()
        for key, routed in PAGE_ACTIONS.items():
            if isinstance(routed, list):
                self.assertTrue(routed, key)
                self.assertEqual([r for r in routed if r not in routes], [], key)
            else:
                self.assertIsInstance(routed, str, key)

    def test_every_page_of_the_players_site_has_its_routes(self):
        if not os.path.isdir(PORTAL):
            self.skipTest("the portal is not at hand")
        pages = {name for name in os.listdir(PORTAL) if name.endswith(".php")} - SITE_LIBRARIES
        self.assertEqual(pages, set(SITE_PAGES))
        routes = api_routes.by_name()
        for page, routed in SITE_PAGES.items():
            if isinstance(routed, list):
                self.assertEqual([r for r in routed if r not in routes], [], page)
        # The libraries are no pages: the site's Apache refuses them (server/apache/site.conf, beside the portal in the
        # repository; the tools' image mounts the portal alone).
        conf = os.path.join(PORTAL, "..", "apache", "site.conf")
        if not os.path.isfile(conf):
            return
        with open(conf, encoding="utf-8") as f:
            denied = re.search(r'FilesMatch "\^\(\?:([\w|]+)\)\\\.php\$">\s*Require all denied', f.read())
        self.assertEqual({n + ".php" for n in denied.group(1).split("|")}, SITE_LIBRARIES)

    def test_every_route_is_named_by_a_page_or_is_the_apis_own(self):
        named = {r for v in list(PAGE_ACTIONS.values()) + list(SITE_PAGES.values()) if isinstance(v, list) for r in v}
        # The API's own: its document, its jobs list, and the tokens' and recordings' bulk forms of what the pages do one by one.
        own = {"openapi", "jobs_list", "build_get", "song_get", "account_get", "site_plays_recent"}
        self.assertEqual(sorted(set(api_routes.by_name()) - named - own), [])


if __name__ == "__main__":
    unittest.main()
