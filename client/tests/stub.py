"""A stand-in for an OpenDMTQ server's site, as the PC client talks to it (server/portal/client.php and /apk), on a
port of this machine for one test: its answers follow the real site's, and a test changes how it behaves.

No game file is used: the "app" is a few made-up bytes.
"""

import hashlib
import http.server
import json
import threading
import time
import urllib.parse

ACCOUNT, PASSWORD = "player1", "pass-1234"
# Accounts whose player the owner banned, with the password above: one until a set time, one until lifted (client.php's
# 403 with the owner's reason).
BANNED = {"banned1": 1999999999, "banned2": None}
# An account switched off on the server's Accounts page, with the password above: client.php's 403 {"error": "off"},
# given after the right password alone (a wrong one is 401, as for any account), as the server answers it.
OFF = "off1"
# How often the server looks whether stop() wants it to end (seconds): stop() waits for that look, and at
# serve_forever's own half second it was most of the unit tests' time, once per test with a site.
POLL = 0.01
# The made-up app: what /apk hands out, and its description.
APP = b"PK\x03\x04 made-up app " * 4096
# A one-time link's token as the site makes one (43 letters of base64url).
LINK_TOKEN = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v"


def made_up_records(now=None):
    """A player's records as client.php?records answers them, with made-up songs: plays and bests with the keyboard and
    without, a new record, places on their charts; their times from `now` (this moment by default)."""
    now = int(now if now is not None else time.time())
    def row(title, chart, score, grade, keys, rank, players, **more):
        return dict({"chart": 100 + rank, "title": title, "chart_name": chart, "score": score, "grade": grade, "keys": keys,
                     "rank": rank, "players": players}, **more)
    return {"account": ACCOUNT, "player": {"id": 7, "name": "SENA", "rank": 2, "total": 4212345, "charts": 12},
            "page": "/opendmtq/player.php?id=7",
            "recent": [row("Neon Rain", "3LINE Hard 9", 987654, "S", True, 1, 4, new_record=True, at=now - 300),
                       row("Paper Planes", "2LINE Normal 5", 812300, "A", False, 2, 6, new_record=False, at=now - 3 * 3600),
                       row("Glass Garden of the Long Afternoon", "4LINE Expert 12", 645120, "B", True, 3, 3,
                           new_record=False, at=now - 2 * 86400)],
            "best": [row("Neon Rain", "3LINE Hard 9", 987654, "S", True, 1, 4, all_combo=True, perfect_play=False,
                         set_at=now - 300),
                     row("Midnight Tram", "4LINE Hard 10", 954210, "S", False, 2, 5, all_combo=False, perfect_play=False,
                         set_at=now - 5 * 86400),
                     row("Paper Planes", "2LINE Normal 5", 812300, "A", False, 2, 6, all_combo=False, perfect_play=False,
                         set_at=None)]}


class Site:
    """The stand-in site; start() serves it, stop() ends it. Its fields change how it answers."""

    def __init__(self):
        self.app = APP
        self.cookie = "1999999999.%s.%s" % (ACCOUNT.encode().hex(), "ab" * 32)
        self.signed_cookies = {self.cookie}
        self.app_state = "ok"          # "ok", "none", "stale", "failed"
        self.apk_kind = "application/vnd.android.package-archive"
        self.damage = False            # /apk hands out other bytes than the description says
        self.requests = []             # (method, path, cookie) of each request
        self.old = False               # an OpenDMTQ from before the PC client: no client.php, its health page only
        self.records = made_up_records()   # client.php?records' answer; None: a server from before records (404)
        self.links = True              # client.php?link answers; False: a server from before one-time links (404)
        # client.php?claim (tests/game/claim.php reads the real one's answers): the players by the id their game signs
        # in by, the player the account is linked to (None: none), the players another account has, and whether it
        # answers at all (False: a server from before such links, 404).
        self.devices = {}
        self.linked = None
        self.taken = set()
        self.claims = True
        self.version = "0.8.0"         # the OpenDMTQ version client.php?about says
        # What its health page answers, as the real one does (server/portal/health.php), and the owner's maintenance
        # notice the game asks for at its start (/inspection/status.json).
        self.health = {"ok": True, "patch": "1.003.005", "game_data": True, "database": True, "writable": True}
        self.maintenance = False
        self.broadcasts = False        # broadcasts on for the server (/live/state)
        # The client data's list of files for its patch, as the game downloads it (its first bytes).
        self.listing = b"\x02" + b"patch list " * 300

    def describe(self):
        return {"file": "opendmtq-phone-app-2026.11.09-android-127.0.0.1-8080.apk", "sha256": hashlib.sha256(self.app).hexdigest(),
                "size": len(self.app), "built_at": "2026-11-09T01:02:03", "label": "TECHNIKA Q (127.0.0.1:8080)",
                "package": "app.example.stand.in", "address": "127.0.0.1:8080"}

    def start(self):
        site = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                # Quiet: the test's own output only.
                pass

            def _cookie(self):
                jar = self.headers.get("Cookie") or ""
                for part in jar.split(";"):
                    name, _, value = part.strip().partition("=")
                    if name == "opendmtq_dl":
                        return value
                return None

            def _json(self, status, body, headers=()):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                for k, v in headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _signed(self):
                return self._cookie() in site.signed_cookies

            def do_GET(self):
                site.requests.append(("GET", self.path, self._cookie()))
                if site.old and self.path.startswith("/opendmtq/client.php"):
                    # The page is not there before 0.8: the site's own not-found.
                    return self._json(404, {"error": "not found"})
                if self.path == "/opendmtq/health.php":
                    # What every OpenDMTQ answers: its game server's state and the game's patch.
                    return self._json(200 if site.health.get("ok") else 503, site.health)
                if self.path == "/opendmtq/client.php?about":
                    return self._json(200, {"opendmtq": site.version, "name": "Stand-in", "address": "127.0.0.1:8080",
                                            "app": site.app_state == "ok"})
                if self.path == "/inspection/status.json":
                    return self._json(200, {"value": {"open_yn": "Y" if site.maintenance else "N", "disable_apps": [],
                                                      "non_kill_apps": []}, "result_code": "000", "resulr_msg": "API_OK"})
                if self.path == "/live/state?ids=0":
                    # What the player asks between songs, for nobody's number.
                    return self._json(200, {"on": False, "fps": 30, "height": 720, "bitrate": 2000000, "segment": 2,
                                            "switch": False, "broadcasts": site.broadcasts, "toast": "", "toast_id": 0,
                                            "toast_kind": ""})
                if self.path == "/opendmtq/client.php?records":
                    if site.records is None:
                        return self._json(404, {"error": "unknown"})
                    if not self._signed():
                        return self._json(403, {"error": "signin"})
                    return self._json(200, site.records)
                if self.path == "/opendmtq/client.php?app":
                    if not self._signed():
                        return self._json(403, {"error": "signin"})
                    if site.app_state != "ok":
                        status = {"none": 404, "stale": 409, "failed": 503}[site.app_state]
                        return self._json(status, {"error": site.app_state})
                    return self._json(200, site.describe())
                if self.path == "/apk":
                    if not self._signed():
                        # The site's own answer: on to its sign-in page.
                        self.send_response(302)
                        self.send_header("Location", "/opendmtq/login.php?next=%2Fapk")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    data = site.app if not site.damage else site.app[:-1] + b"X"
                    self.send_response(200)
                    self.send_header("Content-Type", site.apk_kind)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                # Any other page: the site's HTML.
                data = b"<html>not the client's</html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_HEAD(self):
                # The heads the connection test asks for: the client data's list of the patch, and the app signed in.
                site.requests.append(("HEAD", self.path, self._cookie()))
                patch = site.health.get("patch")
                if self.path == "/patch/phone_new/%s/android/patch_new.csv.lz4" % patch:
                    kind, length = "application/octet-stream", len(site.listing)
                elif self.path == "/apk" and self._signed():
                    kind, length = site.apk_kind, len(site.app)
                elif self.path == "/apk":
                    self.send_response(302)
                    self.send_header("Location", "/opendmtq/login.php?next=%2Fapk")
                    self.end_headers()
                    return
                else:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(length))
                self.end_headers()

            def do_POST(self):
                site.requests.append(("POST", self.path, self._cookie()))
                length = int(self.headers.get("Content-Length") or 0)
                form = urllib.parse.parse_qs(self.rfile.read(length).decode())
                if self.path == "/opendmtq/client.php?link":
                    if not site.links:
                        return self._json(404, {"error": "unknown"})
                    if not self._signed():
                        return self._json(403, {"error": "signin"})
                    return self._json(200, {"url": "/opendmtq/login.php?once=" + LINK_TOKEN,
                                            "page": "/opendmtq/player.php?id=7", "expires": 1999999999})
                if self.path == "/opendmtq/client.php?claim":
                    # As the real one answers (server/portal/client.php client_claim): the account's player as it is,
                    # or the player of the id linked now, or why not.
                    if not site.claims:
                        return self._json(404, {"error": "unknown"})
                    if not self._signed():
                        return self._json(403, {"error": "signin"})
                    if site.linked is not None:
                        return self._json(200, {"linked": True, "now": False,
                                                "player": {"id": site.linked, "name": "Player %d" % site.linked}})
                    player = site.devices.get(form.get("device", [""])[0])
                    if player is None or player in site.taken:
                        return self._json(200, {"linked": False, "why": "none" if player is None else "taken"})
                    site.linked = player
                    return self._json(200, {"linked": True, "now": True, "player": {"id": player, "name": "Player %d" % player}})
                if self.path != "/opendmtq/client.php?signin":
                    return self._json(404, {"error": "none"})
                if form.get("user", [""])[0] in BANNED and form.get("password", [""])[0] == PASSWORD:
                    return self._json(403, {"error": "banned", "reason": "Made-up scores", "until": BANNED[form["user"][0]]})
                if form.get("user", [""])[0] == OFF and form.get("password", [""])[0] == PASSWORD:
                    return self._json(403, {"error": "off"})
                if form.get("user", [""])[0] != ACCOUNT or form.get("password", [""])[0] != PASSWORD:
                    return self._json(401, {"error": "wrong"})
                cookie = "opendmtq_dl=%s; expires=Fri, 01-Jan-2049 00:00:00 GMT; path=/; httponly; samesite=Lax" % site.cookie
                return self._json(200, {"account": ACCOUNT, "expires": 1999999999}, [("Set-Cookie", cookie)])

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": POLL}, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
