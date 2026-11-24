"""The connection test (connection.py, Online's Test connection, --test-server): each step against a stand-in for what a
player meets, a server that works, a port nobody listens on, another service there, an OpenDMTQ too old, a sign-in that
ended, a certificate this PC does not trust, a server that moved to 8791; and the command line's twin."""

import contextlib
import io
import os
import socket
import socketserver
import threading
from unittest import mock

from opendmtq_client import connection, i18n, main
from opendmtq_client import server as srv
from opendmtq_client import state as st
from tests import stub
from tests.base import Folder

EN, KO = i18n.Words("en"), i18n.Words("ko")


def closed_port():
    """A port of this machine that nothing listens on (taken a moment, then given back)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Other(socketserver.ThreadingTCPServer):
    """Another service on a port: it answers anything with a line that is no HTTP, as a mail or a shell server does."""

    allow_reuse_address = True

    def __init__(self):
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.sendall(b"SSH-2.0-OpenSSH_9.6\r\n")

        super().__init__(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.serve_forever, kwargs={"poll_interval": stub.POLL}, daemon=True).start()


class Web(socketserver.ThreadingTCPServer):
    """Another web server on a port: every page an HTML page, as a web server that took a port after OpenDMTQ left it."""

    allow_reuse_address = True

    def __init__(self):
        import http.server

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                # Quiet: the test's own output only.
                pass

            def do_GET(self):
                data = b"<!doctype html><title>It works</title>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        super().__init__(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server_address[1]
        threading.Thread(target=self.serve_forever, kwargs={"poll_interval": stub.POLL}, daemon=True).start()

    def stop(self):
        self.shutdown()
        self.server_close()


class ConnectionTest(Folder):
    def setUp(self):
        super().setUp()
        self.site = stub.Site().start()
        self.state = st.LauncherState()
        self.state.add_server(self.site.url, "Stand-in")

    def tearDown(self):
        self.site.stop()
        super().tearDown()

    def run_test(self, address=None, signed=True):
        """The test of `address` (the stand-in's by default), with the launcher's sign-in to it or none: (the result,
        its steps by key, the steps as they were told)."""
        if signed:
            from opendmtq_client import actions
            actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)
        told = []
        result = connection.run(address or self.site.url, self.state.server(address or self.site.url), report=told.append)
        return result, {s.key: s for s in result.steps}, told

    def said(self, step, words=EN):
        return words.say(step.said)

    def test_a_server_that_works(self):
        result, steps, told = self.run_test()
        self.assertEqual([s.key for s in told], list(connection.STEPS))
        self.assertEqual({k: s.state for k, s in steps.items()},
                         dict.fromkeys(connection.STEPS, "ok") | {"version": "warn"})
        self.assertFalse(result.failed())
        host, port = srv.host_port(self.site.url)
        self.assertEqual(self.said(steps["address"]), "%s: http, host 127.0.0.1, port %d." % (self.site.url, port))
        self.assertEqual(self.said(steps["lookup"]), "127.0.0.1 is an address: nothing to look up.")
        self.assertEqual(self.said(steps["port"]), "Port %d of 127.0.0.1 takes the connection." % port)
        self.assertEqual(self.said(steps["server"]), "Stand-in, OpenDMTQ 0.8.0.")
        self.assertEqual(self.said(steps["signin"]), "Signed in as player1 until 2033-05-18.")
        self.assertEqual(self.said(steps["game"]), "The game server answers: patch 1.003.005.")
        self.assertEqual(self.said(steps["broadcasts"]), "Broadcasts are off for the server.")
        self.assertRegex(self.said(steps["downloads"]),
                         r"^The app \(0\.1 MB\) and the client data's list \(3 KB\) are there to download\.$")
        # Every ask answered: the median and the fastest and slowest, or one figure when they are one.
        self.assertRegex(self.said(steps["round_trip"]),
                         r"^All 5 asks answered: (\d+ ms in the middle, from \d+ to \d+ ms|\d+ ms each)\.$")
        # Heads alone for the downloads: nothing downloaded whole.
        self.assertNotIn(("GET", "/apk", self.site.cookie), self.site.requests)
        self.assertIn(("HEAD", "/apk", self.site.cookie), self.site.requests)
        # The version: the launcher's own against the server's, said with both.
        self.assertIn("The server runs 0.8.0", self.said(steps["version"]))
        # The verdict: the server answers, and the first thing not as it should be, in words of its own that say the
        # server once (main: "The server answers. Version: The server runs 0.8.0, ...").
        from opendmtq_client import __version__
        self.assertEqual(EN.say(result.verdict()),
                         "The server answers; it runs 0.8.0, older than this launcher's %s." % __version__)
        self.assertEqual(KO.say(result.verdict()),
                         "서버가 응답합니다. 이 런처(%s)보다 오래된 0.8.0 버전입니다." % __version__)
        # Each step's time, the copy's text with every step, in both languages.
        self.assertTrue(all(s.ms is not None for s in result.steps))
        text = result.text(EN)
        self.assertIn("Connection test of %s" % self.site.url, text)
        self.assertEqual(len(text.splitlines()), 2 + len(connection.STEPS))
        self.assertIn("게임 서버가 응답합니다(패치 1.003.005).", result.text(KO))

    def test_a_warnings_verdict_says_the_server_once(self):
        # Each warning with words of its own over the steps: the server named once, never its step's name before a
        # sentence that names it again. Another warning keeps "the server answers" with its step and what it found.
        from opendmtq_client import __version__
        cases = (("version", "newer", dict(server="9.0.0", launcher=__version__),
                  "The server answers; it runs 9.0.0, newer than this launcher's %s." % __version__,
                  "서버가 응답합니다. 이 런처(%s)보다 새로운 9.0.0 버전입니다." % __version__),
                 ("version", "unknown", dict(launcher=__version__),
                  "The server answers without saying its version; this launcher is %s." % __version__,
                  "서버가 응답하지만 버전을 알려 주지 않습니다. 이 런처는 %s 버전입니다." % __version__),
                 ("signin", "none", {}, "The server answers; this PC is not signed in to it.",
                  "서버가 응답합니다. 이 PC에서 이 서버에 로그인하지 않았습니다."),
                 ("game", "maintenance", dict(patch="1.003.005"),
                  "The server answers; its game server is under maintenance (patch 1.003.005).",
                  "서버가 응답하지만 게임 서버가 점검 중입니다(패치 1.003.005)."),
                 ("round_trip", "ok", dict(n=4, of=5, median=3, fast=2, slow=5),
                  "The server answers. Round trip: 4 of 5 asks answered: 3 ms in the middle, from 2 to 5 ms.",
                  "서버가 응답합니다. 응답 시간: 5번 중 4번 응답: 중앙값 3 ms, 2~5 ms."))
        for step, key, values, english, korean in cases:
            result = connection.Result("http://192.0.2.20")
            result.step(step).done("warn", key, 1.0, **values)
            self.assertEqual(EN.say(result.verdict()), english, key)
            self.assertEqual(KO.say(result.verdict()), korean, key)

    def test_the_round_trip_says_each_figure_once(self):
        # All five answered, some, none; the fastest and the slowest one figure when they are one (main: "1~1 ms").
        cases = (([1.2, 2.0, 1.9, 4.6, 2.2], "ok", "All 5 asks answered: 2 ms in the middle, from 1 to 5 ms.",
                  "5번 모두 응답: 중앙값 2 ms, 1~5 ms."),
                 ([1.0, 1.2, 0.9, 1.1, 1.3], "ok", "All 5 asks answered: 1 ms each.", "5번 모두 응답: 각 1 ms."),
                 ([3.0, 7.0, 5.0], "warn", "3 of 5 asks answered: 5 ms in the middle, from 3 to 7 ms.",
                  "5번 중 3번 응답: 중앙값 5 ms, 3~7 ms."),
                 ([2.0, 2.4], "warn", "2 of 5 asks answered: 2 ms each.", "5번 중 2번 응답: 각 2 ms."),
                 ([], "bad", "None of the asks was answered.", "한 번도 응답하지 않았습니다."))
        for times, state, english, korean in cases:
            got, key, values = connection.round_trip(times)
            said = i18n.Said("test.round_trip." + key, **values)
            self.assertEqual((got, EN.say(said), KO.say(said)), (state, english, korean), times)

    def test_the_same_version_and_broadcasts_on(self):
        from opendmtq_client import __version__
        self.site.version, self.site.broadcasts = __version__, True
        result, steps, _ = self.run_test()
        self.assertEqual(steps["version"].state, "ok")
        self.assertEqual(self.said(steps["broadcasts"]), "Broadcasts are on for the server.")
        self.assertEqual(EN.say(result.verdict()), "The server answers, and so does everything the game uses.")
        self.assertEqual(KO.say(result.verdict()), "서버와 게임이 쓰는 기능이 모두 응답합니다.")

    def test_a_port_nobody_listens_on(self):
        port, probed = closed_port(), (closed_port(),)
        with mock.patch.object(connection, "PORTS", probed):
            result, steps, _ = self.run_test("http://127.0.0.1:%d" % port, signed=False)
        self.assertEqual(steps["port"].state, "bad")
        self.assertEqual(self.said(steps["port"]),
                         "127.0.0.1 refuses the connection on port %d, and no OpenDMTQ server answers on ports %d to %d "
                         "either." % (port, probed[0], probed[-1]))
        # What comes after a port that does not answer is not tried, and says so.
        self.assertEqual([steps[k].state for k in connection.STEPS[3:]], ["skip"] * 7)
        self.assertEqual(self.said(steps["round_trip"]), "Not tried: a step before it did not get through.")
        self.assertTrue(result.failed())
        self.assertIsNone(result.moved)

    def test_a_server_moved_to_8791_is_found(self):
        # A launcher set up for port 80 of a server updated to 0.11.0, which moved to 8791 (here the stand-in's port, among
        # the ports a new server takes).
        host, port = srv.host_port(self.site.url)
        old = closed_port()
        with mock.patch.object(connection, "PORTS", (closed_port(), port)):
            result, steps, _ = self.run_test("http://127.0.0.1:%d" % old, signed=False)
        self.assertEqual(result.moved, self.site.url)
        self.assertEqual(self.said(steps["port"]), "127.0.0.1 refuses the connection on port %d. An OpenDMTQ server "
                                                   "answers at %s." % (old, self.site.url))
        self.assertEqual(EN.say(result.verdict()), "Nothing answers at http://127.0.0.1:%d. An OpenDMTQ server answers at "
                                                   "%s." % (old, self.site.url))
        self.assertEqual(KO.say(result.verdict()), "http://127.0.0.1:%d에서는 응답이 없고, %s에서 OpenDMTQ 서버가 응답합니다."
                         % (old, self.site.url))
        # The ports a new server takes: 8791 and the next ones, never 80.
        self.assertEqual(connection.PORTS, tuple(range(8791, 8800)))

    def test_moving_to_the_server_found_keeps_the_sign_in(self):
        from opendmtq_client import actions, apps
        # A launcher that knows the server at its old address alone, signed in there.
        old = "http://127.0.0.1:%d" % closed_port()
        self.state = st.LauncherState()
        self.state.add_server(old, "Stand-in")
        self.state.server(old).update(account=stub.ACCOUNT, cookie=self.site.cookie, expires=1999999999)
        os.makedirs(apps.folder(old))
        actions.move_server(self.state, old, self.site.url)
        self.assertEqual(self.state.current, self.site.url)
        self.assertTrue(self.state.signed_in())
        self.assertEqual(self.state.server()["account"], stub.ACCOUNT)
        # Its app was built for the old address: it goes.
        self.assertFalse(os.path.exists(apps.folder(old)))
        self.assertEqual([s["url"] for s in self.state.servers], [self.site.url])

    def test_another_service_on_the_port(self):
        other = Other()
        try:
            result, steps, _ = self.run_test("http://127.0.0.1:%d" % other.server_address[1], signed=False)
        finally:
            other.shutdown()
            other.server_close()
        self.assertEqual(steps["port"].state, "ok")
        self.assertEqual((steps["server"].state, self.said(steps["server"])),
                         ("bad", "Something answers on the port, and it is no OpenDMTQ server for PCs."))
        self.assertTrue(result.failed())

    def test_another_web_server_on_the_old_port_and_the_server_moved(self):
        # The server moved to 8791 and a web server took the port the launcher knows it by: the move is looked for all
        # the same, and the server found there is offered.
        _host, port = srv.host_port(self.site.url)
        web = Web()
        try:
            with mock.patch.object(connection, "PORTS", (closed_port(), port)):
                result, steps, _ = self.run_test(web.url, signed=False)
        finally:
            web.stop()
        self.assertEqual(result.moved, self.site.url)
        self.assertEqual((steps["server"].state, self.said(steps["server"])),
                         ("bad", "Something answers on the port, and it is no OpenDMTQ server for PCs. An OpenDMTQ server "
                                 "answers at %s." % self.site.url))
        self.assertEqual(self.said(steps["server"], KO), "포트에서 응답은 오지만 PC용 OpenDMTQ 서버가 아닙니다. %s에서 "
                                                         "OpenDMTQ 서버가 응답합니다." % self.site.url)
        self.assertEqual(EN.say(result.verdict()), "Another server answers at %s. An OpenDMTQ server answers at %s."
                         % (web.url, self.site.url))
        self.assertEqual(KO.say(result.verdict()), "%s에서는 다른 서버가 응답하고, %s에서 OpenDMTQ 서버가 응답합니다."
                         % (web.url, self.site.url))
        self.assertEqual([steps[k].state for k in connection.STEPS[4:]], ["skip"] * 6)

    def test_a_network_this_pc_cannot_reach(self):
        # No way from this PC to the address (no route, the network down): said as such at once, not as a wait of 5 s.
        port, probed = closed_port(), closed_port()
        unreachable = OSError(101, "Network is unreachable")
        with mock.patch.object(connection, "PORTS", (probed,)), \
                mock.patch.object(socket, "create_connection", side_effect=unreachable):
            result, steps, _ = self.run_test("http://127.0.0.1:%d" % port, signed=False)
        self.assertEqual(steps["port"].state, "bad")
        self.assertEqual(self.said(steps["port"]),
                         "127.0.0.1 cannot be reached from this PC on port %d ([Errno 101] Network is unreachable), and no "
                         "OpenDMTQ server answers on ports %d to %d either." % (port, probed, probed))
        self.assertEqual(self.said(steps["port"], KO),
                         "이 PC에서 127.0.0.1의 %d 포트에 연결할 수 없습니다([Errno 101] Network is unreachable). %d~%d "
                         "포트에서도 OpenDMTQ 서버가 응답하지 않습니다." % (port, probed, probed))
        self.assertIsNone(result.moved)

    def test_an_opendmtq_too_old_for_pcs(self):
        self.site.old = True
        result, steps, _ = self.run_test(signed=False)
        self.assertEqual(self.said(steps["server"]), "An OpenDMTQ older than 0.8 answers, without the part for PCs.")
        self.assertEqual(steps["version"].state, "skip")

    def test_a_sign_in_that_ended(self):
        from opendmtq_client import actions
        actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)
        self.site.signed_cookies.clear()
        result, steps, _ = self.run_test(signed=False)
        self.assertEqual(steps["signin"].state, "bad")
        self.assertEqual(self.said(steps["signin"]), "The server no longer takes the sign-in of player1.")
        self.assertEqual(self.said(steps["signin"], KO), "서버가 player1 계정의 로그인을 더 이상 받지 않습니다.")
        # Nothing of the launcher's is changed by a test: the sign-in it keeps stays until the window's own look.
        self.assertEqual(self.state.server()["cookie"], self.site.cookie)
        # Not signed in at all: said, and the app's download waits for one.
        self.state.forget_sign_in()
        result, steps, _ = self.run_test(signed=False)
        self.assertEqual((steps["signin"].state, self.said(steps["signin"])), ("warn", "Not signed in to this server on this PC."))
        self.assertEqual(self.said(steps["downloads"]), "The client data's list (3 KB) is there to download; the app "
                                                        "downloads after a sign-in.")

    def test_the_servers_app_said_as_found(self):
        # Signed in while the server builds its app, builds it again for a new address, or could not build it: the sign-in
        # holds, and the app's state is said as it was found, nothing more.
        for state, said in (("none", "The server is building its app (about 20 seconds)."),
                            ("stale", "The server's address changed, and it is building its app again."),
                            ("failed", "The server could not build its app.")):
            self.site.app_state = state
            _, steps, _ = self.run_test()
            self.assertEqual((steps["signin"].state, self.said(steps["signin"])),
                             ("ok", "Signed in as %s. %s" % (stub.ACCOUNT, said)))
        self.assertEqual(self.said(steps["signin"], KO), "%s 계정으로 로그인되어 있습니다. 서버가 앱을 만들지 못했습니다." % stub.ACCOUNT)

    def test_the_game_under_maintenance_and_down(self):
        # The owner's maintenance notice, as the game asks for it at its start.
        self.site.maintenance = True
        _, steps, _ = self.run_test()
        self.assertEqual((steps["game"].state, self.said(steps["game"])),
                         ("warn", "The game server answers, under maintenance: patch 1.003.005."))
        self.site.maintenance = False
        # What the health page says of a server that cannot serve the game, each in words.
        for health, said in (({"game_data": False}, "The game server answers without its client data: the game cannot start."),
                             ({"database": False}, "The game server answers without its database."),
                             ({"writable": False}, "The game server cannot write its database: plays are not kept."),
                             ({"host": ""}, "The game server answers with no address of its own set.")):
            self.site.health = dict({"ok": False, "patch": "1.003.005", "game_data": True, "database": True, "writable": True,
                                     "host": "192.168.1.10:8791"}, **health)
            _, steps, _ = self.run_test()
            self.assertEqual((steps["game"].state, self.said(steps["game"])), ("bad", said))
        # The last of them in Korean.
        self.assertEqual(self.said(steps["game"], KO), "게임 서버에 서버 주소가 정해져 있지 않습니다.")

    def test_not_an_address_and_a_name_that_leads_nowhere(self):
        result, steps, _ = self.run_test("not an address", signed=False)
        self.assertEqual(self.said(steps["address"]), "not an address is not an address.")
        self.assertEqual(steps["lookup"].state, "skip")
        with mock.patch.object(socket, "getaddrinfo", side_effect=socket.gaierror(-2, "Name or service not known")):
            result, steps, _ = self.run_test("http://no-such-server.example:8791", signed=False)
        self.assertEqual(self.said(steps["lookup"]),
                         "no-such-server.example leads to no address ([Errno -2] Name or service not known).")
        self.assertEqual(self.said(steps["lookup"], KO),
                         "no-such-server.example에 해당하는 주소가 없습니다([Errno -2] Name or service not known).")

    def test_the_last_result_is_kept_for_the_report(self):
        result, _, _ = self.run_test()
        kept = connection.last()
        self.assertEqual(kept.url, self.site.url)
        self.assertEqual(kept.text(EN), result.text(EN))
        from opendmtq_client import report
        path, _left = report.make(self.state, path=os.path.join(self.home, "r.zip"), devices=[])
        import zipfile
        with zipfile.ZipFile(path) as z:
            kept_text = z.read("system/connection-test.txt").decode()
        # In the report, the server's address left out as everywhere.
        self.assertIn("Connection test of <server>", kept_text)
        self.assertIn("[ok  ] Game server", kept_text)

    def test_the_command_line(self):
        def run_main(args):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = main.main(args)
            return code, out.getvalue()

        self.state.save()
        code, said = run_main(["--test-server"])
        self.assertEqual(code, 0, said)
        for line in ("[ok  ] Address: %s: http" % self.site.url, "[ok  ] Game server: The game server answers: patch 1.003.005.",
                     "[warn] Sign-in: Not signed in to this server on this PC."):
            self.assertIn(line, said)
        # A port nobody listens on: the steps after it skipped, the exit code 1.
        with mock.patch.object(connection, "PORTS", (closed_port(),)):
            code, said = run_main(["--test-server", "127.0.0.1:%d" % closed_port()])
        self.assertEqual(code, 1, said)
        self.assertIn("[skip] Round trip: Not tried", said)
        self.assertIn("[fail] Port: 127.0.0.1 refuses the connection", said)
        # No server known and none given: said, 2.
        st.LauncherState().save()
        code, said = run_main(["--test-server"])
        self.assertEqual(code, 2)
        self.assertIn("No server to test", said)


class Https(Folder):
    """A server over HTTPS with a certificate of its own authority (test_server.OwnAuthority's), and another authority."""

    def setUp(self):
        super().setUp()
        from tests.test_server import OwnAuthority
        self.https = OwnAuthority("test_its_own_authority_is_trusted_for_it")
        self.https.setUp()

    def tearDown(self):
        self.https.tearDown()
        super().tearDown()


class Certificate(Https):
    """Over HTTPS: the server's own authority trusted for it alone, or a certificate this PC does not trust."""

    def test_a_certificate_this_pc_does_not_trust(self):
        result = connection.run(self.https.base, None)
        step = result.step("server")
        self.assertEqual((step.state, step.said.key), ("bad", "test.server.certificate"))
        self.assertIn("This PC does not trust the certificate the server answers HTTPS with", EN.say(step.said))
        self.assertIn("CERTIFICATE_VERIFY_FAILED", EN.say(step.said))

    def test_the_servers_own_authority(self):
        srv.trust(self.https.base, self.https.authority(self.https.mine))
        result = connection.run(self.https.base, None)
        self.assertEqual(EN.say(result.step("server").said), "Over HTTPS, OpenDMTQ 0.8.0, over HTTPS with the server's own "
                                                             "certificate, trusted for this server alone.")


class MovedOverHttps(Https):
    """A server over HTTPS with its own authority that moved to another port of the same host (8791 and the ports a new
    server takes): found with the authority the launcher trusts for its old address, and Use this address takes the
    authority along to the new one."""

    def setUp(self):
        super().setUp()
        # The address the launcher knew it by, before its port moved: nothing there now, its authority trusted there.
        self.old = "https://127.0.0.1:%d" % closed_port()
        self.ca = self.https.authority(self.https.mine)
        srv.trust(self.old, self.ca)

    def test_found_with_the_authority_of_its_old_address(self):
        with mock.patch.object(connection, "PORTS", (closed_port(), self.https.port)):
            result = connection.run(self.old, None)
        self.assertEqual(result.moved, self.https.base)
        self.assertEqual(EN.say(result.verdict()), "Nothing answers at %s. An OpenDMTQ server answers at %s."
                         % (self.old, self.https.base))
        # The authority stays the old address's alone until the move is chosen: the test changes nothing it keeps.
        self.assertEqual(srv._trusted(), {self.old: self.ca})

    def test_another_servers_authority_finds_nothing(self):
        # The old address's authority vouches for no other server's certificate on the new port.
        srv.trust(self.old, self.https.authority(self.https.other))
        with mock.patch.object(connection, "PORTS", (self.https.port,)):
            result = connection.run(self.old, None)
        self.assertIsNone(result.moved)

    def test_use_this_address_takes_the_authority_along(self):
        from opendmtq_client import actions
        state = st.LauncherState()
        state.add_server(self.old, "Over HTTPS")
        actions.move_server(state, self.old, self.https.base)
        self.assertEqual(state.current, self.https.base)
        # Trusted for the address it plays on now, and no longer for the one it left.
        self.assertEqual(srv._trusted(), {self.https.base: self.ca})
        self.assertEqual(srv.about(self.https.base)["name"], "Over HTTPS")
        # A test of the new address afterwards: the server's own certificate, trusted for it.
        result = connection.run(self.https.base, None)
        self.assertEqual(result.step("server").said.key, "test.server.ok_https_own")

    def test_another_program_with_its_own_certificate_on_the_old_port(self):
        # Another program took the old port, answering HTTPS with a certificate of its own authority, which the old
        # address's (the server's) does not vouch for; the server answers on a port a new server takes: offered there.
        other = OtherHttps(self.https.other)
        try:
            srv.trust(other.base, self.ca)
            with mock.patch.object(connection, "PORTS", (self.https.port,)):
                result = connection.run(other.base, None)
        finally:
            other.stop()
        self.assertEqual(result.moved, self.https.base)
        step = result.step("server")
        self.assertEqual((step.state, step.said.key), ("bad", "test.server.certificate_moved"))
        self.assertTrue(EN.say(step.said).endswith("An OpenDMTQ server answers at %s." % self.https.base), EN.say(step.said))
        self.assertEqual(EN.say(result.verdict()), "Another server answers at %s. An OpenDMTQ server answers at %s."
                         % (other.base, self.https.base))


class OtherHttps:
    """Another program over HTTPS on a port of its own, with the certificate of the authority in `folder` (tls.ensure's)."""

    def __init__(self, folder):
        import http.server
        import ssl

        class About(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                # Quiet: the test's own output only.
                pass

            def do_GET(self):
                data = b"<!doctype html><title>It works</title>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(os.path.join(folder, "serve", "server.crt"), os.path.join(folder, "serve", "server.key"))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), About)
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        self.base = "https://127.0.0.1:%d" % self.port
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": stub.POLL}, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class UseThisAddress(Folder):
    """Use this address in the window: the server moved to the address found, the status line saying so and the test
    of the new address started, all in one task of the window's own thread, so that nothing the window does between
    them (a ready check's answer, the next frame a test or a person looks at) finds PLAY on the new address under the
    words of the old one."""

    def window(self, state):
        """A stand-in for the window with Use this address's own methods and the status line's, its tasks kept in order
        (app.post) for the test to run one at a time; nothing drawn, no ready check or test run."""
        import types
        from opendmtq_client import app as launcher
        app = types.SimpleNamespace(
            state=state, busy=False, download=None, session=None, words=i18n.Words("en"), status_message=None,
            status_tone="normal", status_action=None, status_transient=False, status_sticky=False, update_found=None,
            checks=[], address_draft="typed", download_error=None, app_note=None, connection_test={"running": False},
            tasks=[], tests=[], _paint_status=lambda: None, refresh_checks=lambda force=False: None,
            follow_page=lambda *pages: None)
        app.post = app.tasks.append
        app.test_connection = lambda: app.tests.append(state.current)
        for name in ("use_found_address", "_moved", "set_status", "user_acted", "_say_state", "busy_now", "_game_open",
                     "files_in_use", "ready", "server_answers"):
            setattr(app, name, getattr(launcher.LauncherApp, name).__get__(app))
        app.text = lambda: launcher.LauncherApp.status_text.fget(app)
        return app

    def test_the_move_and_its_words_come_in_one_task(self):
        site = stub.Site().start()
        self.addCleanup(site.stop)
        old = "http://127.0.0.1:%d" % closed_port()
        state = st.LauncherState()
        state.add_server(old, "Stand-in")
        app = self.window(state)
        app.use_found_address(site.url)
        # The worker asks the new address, then hands its changes over: wait for it to be done.
        for thread in [t for t in threading.enumerate() if t.name == "move"]:
            thread.join(10)
        self.assertTrue(app.tasks)
        # The window's task pump, a task at a time: once PLAY is on the new address, the line says so already, and
        # the new address's test has started.
        for task in list(app.tasks):
            task()
            if state.current == site.url:
                # In the launcher's words for the server it plays on now (its name, as PLAY's line names it).
                self.assertEqual(app.status_message.key, "test.used")
                self.assertEqual(app.text(), EN("test.used", name=state.server()["name"]))
                self.assertEqual(app.tests, [site.url])
        self.assertEqual(state.current, site.url)
        self.assertIsNone(app.address_draft)

    def test_not_while_a_game_from_the_command_line_plays_from_the_old_app(self):
        # The old address's app goes with the move: while a game the command line started plays from it (playing.py,
        # which this window's own busy state knows nothing of), the move waits, as Forget of the server in use does
        # (main moved and deleted the app under the game).
        from opendmtq_client import apps, playing
        site = stub.Site().start()
        self.addCleanup(site.stop)
        old = "http://127.0.0.1:%d" % closed_port()
        state = st.LauncherState()
        state.add_server(old, "Stand-in")
        os.makedirs(apps.folder(old))
        app = self.window(state)
        with mock.patch.object(playing, "running", return_value=True):
            app.use_found_address(site.url)
        for thread in [t for t in threading.enumerate() if t.name == "move"]:
            thread.join(10)
        for task in list(app.tasks):
            task()
        self.assertEqual(app.status_message.key, "online.busy")
        self.assertEqual(state.current, old)
        self.assertTrue(os.path.isdir(apps.folder(old)))
