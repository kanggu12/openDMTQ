"""Talking to a server: its word on itself, the sign-in, its app and the app's download, against a stand-in site."""

import os
import socket
import threading
import time
import urllib.error
from unittest import mock

from opendmtq_client import server as srv
from tests import stub
from tests.base import Folder


class Addresses(Folder):
    def test_addresses_are_read_as_players_type_them(self):
        self.assertEqual(srv.normalize("example.test:8080"), "http://example.test:8080")
        self.assertEqual(srv.normalize(" HTTPS://Example.test/opendmtq/ "), "https://example.test")
        self.assertEqual(srv.normalize("http://192.168.0.10"), "http://192.168.0.10")
        for bad in ("", "ftp://x", "http://", "x:99999"):
            with self.assertRaises(srv.ServerError, msg=bad):
                srv.normalize(bad)

    def test_an_address_with_a_blank_is_none(self):
        # Refused here, the one check the window and the command line share, never later as HTTP's own raw words; the
        # error's English sentence is the window's English words, and Korean has its own.
        from opendmtq_client import i18n
        for bad in ("not an address", "example .com:8080", "http://exa\x0bmple.com", "club.test: 8790", "a<b>.test"):
            with self.assertRaises(srv.ServerError, msg=bad) as caught:
                srv.normalize(bad)
            self.assertEqual(caught.exception.key, "error.server.address", bad)
            self.assertEqual(str(caught.exception), i18n.Words("en").error(caught.exception), bad)
            self.assertNotIn("control characters", i18n.Words("ko").error(caught.exception), bad)
        self.assertEqual(str(caught.exception), "a<b>.test is not an address.")

    def test_an_address_http_refuses_is_said_as_none(self):
        # A server kept before the check above (a blank in its host) asked all the same: the address is said to be none,
        # not Python's "URL can't contain control characters".
        with self.assertRaises(srv.ServerError) as caught:
            srv.about("http://not an address")
        self.assertEqual(caught.exception.key, "error.server.address")

    def test_a_service_that_is_no_http_is_no_server(self):
        # Something on the port that answers in its own way (here a line and the end, as an SSH server greets): HTTP's
        # own BadStatusLine becomes "not an OpenDMTQ server", never an error the window would print raw.
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        def greet():
            connection, _ = listener.accept()
            connection.recv(1024)
            connection.sendall(b"SSH-2.0-stand-in\r\n")
            connection.close()

        threading.Thread(target=greet, daemon=True).start()
        try:
            with self.assertRaises(srv.ServerError) as caught:
                srv._call("http://127.0.0.1:%d" % listener.getsockname()[1], "/opendmtq/client.php?about")
        finally:
            listener.close()
        self.assertEqual(caught.exception.key, "error.server.not_opendmtq")

    def test_host_and_port(self):
        self.assertEqual(srv.host_port("http://example.test"), ("example.test", 80))
        self.assertEqual(srv.host_port("https://example.test"), ("example.test", 443))
        self.assertEqual(srv.host_port("http://example.test:8790"), ("example.test", 8790))


class Talking(Folder):
    def setUp(self):
        super().setUp()
        self.site = stub.Site().start()

    def tearDown(self):
        self.site.stop()
        super().tearDown()

    def test_about(self):
        found = srv.about(self.site.url)
        self.assertEqual(found["name"], "Stand-in")
        self.assertTrue(found["app"])

    def test_another_site_is_no_server(self):
        with self.assertRaises(srv.ServerError) as caught:
            srv.about(self.site.url + "/elsewhere")
        self.assertEqual(caught.exception.key, "error.server.not_opendmtq")

    def test_an_older_opendmtq_is_said_as_such(self):
        # An OpenDMTQ from before the PC client has no client.php, but answers its health page as every one does.
        self.site.old = True
        with self.assertRaises(srv.ServerError) as caught:
            srv.about(self.site.url)
        self.assertEqual(caught.exception.key, "error.server.too_old")
        self.assertEqual(caught.exception.params["base"], self.site.url)

    def test_nobody_there(self):
        # Port 9 refuses on most machines, but under WSL nothing answers at all: a second is wait enough for that.
        with mock.patch.object(srv, "TIMEOUT", 1), self.assertRaises(srv.ServerError) as caught:
            srv.about("http://127.0.0.1:9")
        # Refused, or no answer at all, as this computer's network has it: either way the server was not reached.
        self.assertIn(caught.exception.key, ("error.server.refused", "error.server.timeout", "error.server.unreachable"))

    def test_why_a_server_was_not_reached_in_plain_words(self):
        # The window says it plainly; the system's own text stays in the English sentence for the log.
        cases = ((urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")), "error.server.unknown_host"),
                 (urllib.error.URLError(ConnectionRefusedError(10061, "refused")), "error.server.refused"),
                 (urllib.error.URLError(socket.timeout("timed out")), "error.server.timeout"),
                 (TimeoutError("timed out"), "error.server.timeout"),
                 (urllib.error.URLError(OSError("network is down")), "error.server.unreachable"))
        for error, key in cases:
            said = srv._unreachable("http://club.test", error)
            self.assertEqual(said.key, key)
            self.assertNotIn("reason", said.params)
            self.assertIn(str(getattr(error, "reason", error)), str(said))

    def test_sign_in(self):
        answer = srv.sign_in(self.site.url, stub.ACCOUNT, stub.PASSWORD)
        self.assertEqual(answer["account"], stub.ACCOUNT)
        self.assertEqual(answer["cookie"], self.site.cookie)
        with self.assertRaises(srv.ServerError) as caught:
            srv.sign_in(self.site.url, stub.ACCOUNT, "wrong")
        self.assertEqual(caught.exception.key, "error.signin.wrong")

    def test_a_banned_account_is_told_why(self):
        # The owner banned the account's player: the owner's reason, with the end when the ban has one.
        with self.assertRaises(srv.ServerError) as caught:
            srv.sign_in(self.site.url, "banned1", stub.PASSWORD)
        self.assertEqual(caught.exception.key, "error.signin.banned_until")
        self.assertEqual(caught.exception.params, {"when": time.strftime("%Y-%m-%d %H:%M", time.localtime(1999999999)),
                                                   "reason": "Made-up scores"})
        with self.assertRaises(srv.ServerError) as caught:
            srv.sign_in(self.site.url, "banned2", stub.PASSWORD)
        self.assertEqual((caught.exception.key, caught.exception.params), ("error.signin.banned", {"reason": "Made-up scores"}))

    def test_a_disabled_account_is_told_so_after_its_right_password(self):
        # An account the owner switched off on the Accounts page: told so in the launcher's own words, as the site's
        # sign-in page says it, once its password is right; a wrong password is only wrong, as for any account.
        from opendmtq_client import i18n
        with self.assertRaises(srv.ServerError) as caught:
            srv.sign_in(self.site.url, stub.OFF, stub.PASSWORD)
        self.assertEqual(caught.exception.key, "error.signin.off")
        self.assertEqual(i18n.Words("en").error(caught.exception), "This account is disabled and cannot sign in.")
        self.assertEqual(i18n.Words("ko").error(caught.exception), "이 계정은 비활성화되어 로그인할 수 없습니다.")
        # The command line's sentence, as the window's English words say it.
        self.assertEqual(str(caught.exception), "this account is disabled and cannot sign in")
        with self.assertRaises(srv.ServerError) as caught:
            srv.sign_in(self.site.url, stub.OFF, "wrong")
        self.assertEqual(caught.exception.key, "error.signin.wrong")

    def test_app_needs_the_sign_in(self):
        with self.assertRaises(srv.SignedOut):
            srv.app_info(self.site.url, "not-a-cookie")
        info = srv.app_info(self.site.url, self.site.cookie)
        self.assertEqual(info["size"], len(stub.APP))

    def test_no_app(self):
        for state, key in (("none", "error.app.none"), ("stale", "error.app.stale"), ("failed", "error.app.failed")):
            self.site.app_state = state
            with self.assertRaises(srv.ServerError) as caught:
                srv.app_info(self.site.url, self.site.cookie)
            self.assertEqual(caught.exception.key, key)

    def test_download(self):
        info = srv.app_info(self.site.url, self.site.cookie)
        seen = []
        path = srv.download_app(self.site.url, self.site.cookie, info, os.path.join(self.home, "app"),
                                progress=lambda done, total: seen.append((done, total)))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), stub.APP)
        self.assertEqual(seen[-1], (len(stub.APP), len(stub.APP)))

    def test_a_damaged_download_leaves_nothing(self):
        info = srv.app_info(self.site.url, self.site.cookie)
        self.site.damage = True
        folder = os.path.join(self.home, "app")
        with self.assertRaises(srv.ServerError) as caught:
            srv.download_app(self.site.url, self.site.cookie, info, folder)
        self.assertEqual(caught.exception.key, "error.app.damaged")
        self.assertEqual(os.listdir(folder), [])

    def test_a_sign_in_that_ended_mid_way(self):
        info = srv.app_info(self.site.url, self.site.cookie)
        self.site.signed_cookies.clear()
        with self.assertRaises(srv.SignedOut):
            srv.download_app(self.site.url, self.site.cookie, info, os.path.join(self.home, "app"))

    def test_an_app_without_a_proper_name_is_refused(self):
        # The package becomes the player's data folder and the file name a line of its settings: names only.
        for field, value in (("package", "..\\..\\Startup"), ("package", "app"), ("file", "x.apk\npackage=evil"),
                             ("file", "C:x.apk"), ("size", -5)):
            described = self.site.describe
            self.site.describe = lambda field=field, value=value, described=described: dict(described(), **{field: value})
            try:
                with self.assertRaises(srv.ServerError) as caught:
                    srv.app_info(self.site.url, self.site.cookie)
                self.assertEqual(caught.exception.key, "error.app.named", (field, value))
            finally:
                self.site.describe = described

    def test_a_download_longer_than_said_stops(self):
        info = srv.app_info(self.site.url, self.site.cookie)
        # The server says the app is smaller than what it sends.
        info["size"] = len(stub.APP) // 2
        folder = os.path.join(self.home, "app")
        seen = []
        with self.assertRaises(srv.ServerError) as caught:
            srv.download_app(self.site.url, self.site.cookie, info, folder, progress=lambda d, t: seen.append(d))
        self.assertEqual(caught.exception.key, "error.app.damaged")
        self.assertEqual(os.listdir(folder), [])
        # It stopped at the size said: nothing past it was taken in.
        self.assertLessEqual(max(seen or [0]), info["size"])

    def test_a_page_instead_of_the_app(self):
        info = srv.app_info(self.site.url, self.site.cookie)
        self.site.apk_kind = "text/html"
        with self.assertRaises(srv.ServerError) as caught:
            srv.download_app(self.site.url, self.site.cookie, info, os.path.join(self.home, "app"))
        self.assertEqual(caught.exception.key, "error.app.not_sent")

    def test_a_cancelled_download_leaves_nothing(self):
        info = srv.app_info(self.site.url, self.site.cookie)
        stop = threading.Event()
        stop.set()
        folder = os.path.join(self.home, "app")
        with self.assertRaises(srv.Cancelled):
            srv.download_app(self.site.url, self.site.cookie, info, folder, cancel=stop)
        self.assertEqual(os.listdir(folder), [])

    def test_no_password_is_sent_again(self):
        srv.sign_in(self.site.url, stub.ACCOUNT, stub.PASSWORD)
        srv.app_info(self.site.url, self.site.cookie)
        # After the sign-in only the cookie goes: one POST in all.
        self.assertEqual(sum(1 for m, _, _ in self.site.requests if m == "POST"), 1)


# The server's own tool for its HTTPS certificates (tools/opendmtq_tools/tls.py), to make an authority and a certificate
# as a real server has them; the launcher's tests run beside the repository's other folders.
TLS_TOOL = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "opendmtq_tools", "tls.py")


def _tls_tool():
    """tls.py as a module, or None where it or openssl is not there."""
    import importlib.util
    import shutil
    if not os.path.isfile(TLS_TOOL) or not shutil.which("openssl"):
        return None
    spec = importlib.util.spec_from_file_location("odq_tls_for_tests", TLS_TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OwnAuthority(Folder):
    """A server over HTTPS with a certificate of its own authority, as the edge of a Docker Compose server answers: the
    launcher trusts it with that authority, for that server's address alone, and refuses it with another or none."""

    def setUp(self):
        super().setUp()
        import http.server
        import ssl
        tls = _tls_tool()
        if tls is None:
            self.skipTest("needs openssl and tools/opendmtq_tools/tls.py")
        # This server's authority and certificate, for 127.0.0.1, and another server's authority.
        self.mine, self.other = os.path.join(self.home, "https"), os.path.join(self.home, "other")
        tls.ensure(self.mine, "127.0.0.1")
        tls.ensure(self.other, "127.0.0.1")

        class About(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                # Quiet: the test's own output only.
                pass

            def do_GET(self):
                data = b'{"opendmtq": "0.8.0", "name": "Over HTTPS", "address": "127.0.0.1", "app": false}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(os.path.join(self.mine, "serve", "server.crt"), os.path.join(self.mine, "serve", "server.key"))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), About)
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        self.base = "https://127.0.0.1:%d" % self.port
        # Stopped within the stand-in site's look (stub.POLL), not serve_forever's own half second.
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": stub.POLL}, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def authority(self, folder):
        with open(os.path.join(folder, "public", "ca.crt"), encoding="utf-8") as f:
            return f.read().strip()

    def test_its_own_authority_is_trusted_for_it(self):
        srv.trust(self.base, self.authority(self.mine))
        self.assertEqual(srv.about(self.base)["name"], "Over HTTPS")

    def refused(self, base):
        """The request to `base` fails on the certificate, and nothing else."""
        with self.assertRaises(srv.ServerError) as caught:
            srv.about(base)
        self.assertIn("CERTIFICATE_VERIFY_FAILED", str(caught.exception))

    def test_without_it_or_with_another_it_is_refused(self):
        # Windows' own authorities alone do not know it.
        self.refused(self.base)
        # Another server's authority vouches for nothing here.
        srv.trust(self.base, self.authority(self.other))
        self.refused(self.base)

    def test_an_authority_is_for_its_own_server_alone(self):
        srv.trust(self.base, self.authority(self.mine))
        # The same machine under another address is another server to the launcher: the authority does not go with it.
        self.refused("https://localhost:%d" % self.port)
        # Forgotten, it is refused again.
        srv.trust(self.base, "")
        self.refused(self.base)

    def test_an_installer_that_brought_it_makes_it_trusted(self):
        from opendmtq_client import preset
        preset.hand_over({"url": self.base, "name": "Over HTTPS", "ca": self.authority(self.mine)})
        self.assertEqual(preset.take()["ca"], self.authority(self.mine))
        self.assertEqual(srv.about(self.base)["name"], "Over HTTPS")


class Trickling:
    """A server that sends its answer a byte at a time, each within any read's wait (DRIP seconds apart), for at most
    LASTS seconds, then closes: its headers at once and its body trickling ("body", the app's download's too), or its
    status line and headers trickling ("head"); over HTTPS with the certificate in `tls` (tls.ensure's folder)."""

    DRIP, LASTS = 0.1, 5.0

    def __init__(self, what="body", tls=None, kind="application/json", size=2 << 20):
        import http.server
        trickle = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                # Quiet: the test's own output only.
                pass

            def do_HEAD(self):
                # The connection test's heads of its downloads: the headers alone, trickling as asked.
                self.do_GET(body=False)

            def do_GET(self, body=True):
                head = ("HTTP/1.1 200 OK\r\nContent-Type: %s\r\nContent-Length: %d\r\n\r\n" % (kind, size)).encode()
                started = time.monotonic()
                try:
                    if what == "body":
                        # The status line and the headers at once, as a server that answers starts to.
                        self.wfile.write(head)
                        rest = b"x" * size if body else b""
                    else:
                        rest = head + (b"x" * size if body else b"")
                    for i in range(len(rest)):
                        if time.monotonic() - started > trickle.LASTS:
                            break
                        self.wfile.write(rest[i:i + 1])
                        self.wfile.flush()
                        time.sleep(trickle.DRIP)
                except OSError:
                    # The launcher went: nothing more to send.
                    pass
                # Never the rest: the connection ends with the answer cut short.
                self.close_connection = True

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        if tls is not None:
            import ssl
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(os.path.join(tls, "serve", "server.crt"), os.path.join(tls, "serve", "server.key"))
            self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.base = "%s://127.0.0.1:%d" % ("https" if tls else "http", self.httpd.server_address[1])
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": stub.POLL}, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def timed(job):
    """How a job went and how long it took: (seconds, what it returned or the error it raised)."""
    started = time.monotonic()
    try:
        out = job()
    except Exception as e:  # noqa: BLE001  (the test looks at which)
        out = e
    return time.monotonic() - started, out


class Deadlines(Folder):
    """One deadline for a whole answer (server.within): a server that trickles its answer a byte at a time, each byte
    within any read's wait, is given up at the wait of the answer, whether its body trickles, or its status line and
    headers, over plain HTTP or HTTPS; and the app's download, which may take as long as it needs, hears Cancel at
    once while pieces trickle in (main: each went on for as long as the server trickled, here 5 s)."""

    def trickling(self, **kw):
        server = Trickling(**kw)
        self.addCleanup(server.stop)
        return server

    def given_up(self, server, wait=1):
        """The server's word on itself asked with a wait of `wait` seconds: given up in time, said as no answer in time."""
        took, out = timed(lambda: srv.about(server.base, timeout=wait))
        self.assertLess(took, wait + 1.0, out)
        self.assertIsInstance(out, srv.ServerError)
        self.assertEqual(out.key, "error.server.timeout", out)

    def test_an_answer_whose_body_trickles_in(self):
        self.given_up(self.trickling(what="body"))

    def test_an_answer_whose_headers_trickle_in(self):
        self.given_up(self.trickling(what="head"))

    def test_over_https_too(self):
        tls = _tls_tool()
        if tls is None:
            self.skipTest("needs openssl and tools/opendmtq_tools/tls.py")
        folder = os.path.join(self.home, "https")
        tls.ensure(folder, "127.0.0.1")
        server = self.trickling(what="body", tls=folder)
        with open(os.path.join(folder, "public", "ca.crt"), encoding="utf-8") as f:
            srv.trust(server.base, f.read().strip())
        self.given_up(server)

    def test_the_connection_tests_heads_of_the_downloads(self):
        # The downloads step asks for heads alone: headers that trickle in are given up at the step's wait too.
        from opendmtq_client import connection
        server = self.trickling(what="head")
        with mock.patch.object(srv, "TIMEOUT", 1):
            took, out = timed(lambda: connection._head(server.base, "/apk"))
        self.assertLess(took, 2.0, out)
        self.assertEqual(out[0], False)

    def test_an_answer_in_time_is_taken_as_before(self):
        # The deadline cuts each read's wait to what is left of it, nothing more: a server that answers is read whole,
        # and outside a deadline a socket waits as its request said.
        site = stub.Site().start()
        self.addCleanup(site.stop)
        self.assertEqual(srv.about(site.url, timeout=1)["name"], "Stand-in")
        self.assertIsNone(getattr(srv._deadline, "at", None))

    def test_the_apps_download_hears_cancel_while_pieces_trickle_in(self):
        server = self.trickling(what="body", kind="application/vnd.android.package-archive", size=2 << 20)
        info = {"file": "app.apk", "size": 2 << 20, "sha256": "0" * 64, "package": "app.example.stand.in"}
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        took, out = timed(lambda: srv.download_app(server.base, "", info, os.path.join(self.home, "app"), cancel=cancel))
        self.assertIsInstance(out, srv.Cancelled)
        self.assertLess(took, 1.5)
        self.assertEqual(os.listdir(os.path.join(self.home, "app")), [])
