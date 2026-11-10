"""A stand-in for an OpenDMTQ server's site, as the PC client talks to it (server/portal/client.php and /apk), on a
port of this machine for one test: its answers follow the real site's, and a test changes how it behaves.

No game file is used: the "app" is a few made-up bytes.
"""

import hashlib
import http.server
import json
import threading
import urllib.parse

ACCOUNT, PASSWORD = "player1", "pass-1234"
# How often the server looks whether stop() wants it to end (seconds): stop() waits for that look, and at
# serve_forever's own half second it was most of the unit tests' time, once per test with a site.
POLL = 0.01
# The made-up app: what /apk hands out, and its description.
APP = b"PK\x03\x04 made-up app " * 4096


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

    def describe(self):
        return {"file": "OpenDMTQ-127.0.0.1-8080-v2026.11.09.apk", "sha256": hashlib.sha256(self.app).hexdigest(),
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
                    return self._json(200, {"ok": True, "patch": "1.003.005", "maintenance": False})
                if self.path == "/opendmtq/client.php?about":
                    return self._json(200, {"opendmtq": "0.8.0", "name": "Stand-in", "address": "127.0.0.1:8080",
                                            "app": site.app_state == "ok"})
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

            def do_POST(self):
                site.requests.append(("POST", self.path, self._cookie()))
                length = int(self.headers.get("Content-Length") or 0)
                form = urllib.parse.parse_qs(self.rfile.read(length).decode())
                if self.path != "/opendmtq/client.php?signin":
                    return self._json(404, {"error": "none"})
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
