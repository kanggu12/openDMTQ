"""Talking to a server: its word on itself, the sign-in, its app and the app's download, against a stand-in site."""

import os
import socket
import threading
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
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

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
