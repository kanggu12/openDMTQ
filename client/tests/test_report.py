"""A report for whoever helps (report.py, Help's Save a report and --report): what goes in, and that nothing that names a
person or signs in comes out, wherever it was written."""

import contextlib
import io
import json
import os
import re
import zipfile
from unittest import mock

from opendmtq_client import apps, i18n, player, report
from opendmtq_client import state as st
from tests.base import Folder

# A server as a launcher keeps one, signed in, and a second it knows: every value here must stay out of the report.
SERVER = "http://192.168.1.10:8791"
OTHER = "https://club.example.test:8443"
ACCOUNT, OTHER_ACCOUNT = "sena", "player"
COOKIE = "1999999999.%s.%s" % (ACCOUNT.encode().hex(), "cd" * 32)
API_TOKEN = "odq_0123456789ab_" + "A" * 43
DEVICE = "9f86d081884c7d65"
PACKAGE = "app.example.stand.in"
# What today's settings no longer name: a server forgotten since (by its address, its host alone, its name, its app's file
# and folder here), one on the network by a name without a dot, an address typed that never answered, one tested once,
# a name's addresses, an ID typed wrong, another ID signed in with once.
FORGOTTEN, FORGOTTEN_NAME = "http://dmtq.forgotten.test:8791", "Old Place"
LAN = "http://gamepc:8791"
TYPED = "10.20.30.40:8791"
UNKNOWN = "http://198.51.100.9:8791"
WRONG_ID, ONCE_ID = "sena kim", "mina.k"


class Played(Folder):
    """A launcher after a day of playing: two servers known, signed in to one, its logs, the game's folder and log."""

    def setUp(self):
        super().setUp()
        self.state = st.LauncherState()
        self.state.add_server(OTHER, "Midnight Club", "club.example.test:8443")
        self.state.server(OTHER).update(account=OTHER_ACCOUNT)
        self.state.add_server(SERVER, "Sena's Room", "192.168.1.10:8791")
        self.state.server().update(account=ACCOUNT, cookie=COOKIE, expires=1999999999)
        self.state.save()
        # The test's own folder as the user's home: the user's name is its folder's name.
        home = mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home, "USERNAME": os.path.basename(self.home)})
        home.start()
        self.addCleanup(home.stop)
        # The launcher's log as a day of playing leaves it: the server, the sign-in, the user's folders, an update's
        # address with a key, and the other server's ID where an ID is a word of the log's own too.
        logs = os.path.dirname(st.launcher_log())
        os.makedirs(logs)
        local = os.path.join(self.home, "AppData", "Local")
        with open(st.launcher_log(), "w", encoding="utf-8") as f:
            f.write("\n".join([
                "2026-11-17 09:00:00 INFO MainThread OpenDMTQ 0.11.0 started: --sign-in %s" % ACCOUNT,
                "2026-11-17 09:00:01 INFO sign-in could not sign in to %s as %s: the ID or the password is wrong" % (SERVER, ACCOUNT),
                "2026-11-17 09:00:02 INFO download downloaded the app of %s (1024 bytes)" % SERVER,
                "2026-11-17 09:00:03 INFO MainThread starting %s" % os.path.join(local, "OpenDMTQ.Client", "OpenDMTQ.exe"),
                "2026-11-17 09:00:04 INFO MainThread the player's folder is %s" % os.path.join(local, "OpenDMTQ", "servers",
                                                                                              "192.168.1.10-8791"),
                "2026-11-17 09:00:05 INFO update-look asked https://updates.example.test/feed?token=s3cr3t&os=win",
                "2026-11-17 09:00:06 INFO MainThread a header Cookie: opendmtq_dl=%s" % COOKIE,
                "2026-11-17 09:00:07 INFO MainThread an API token %s" % API_TOKEN,
                "2026-11-17 09:00:08 INFO MainThread the player said: player: FMOD output: 48000 Hz",
                "2026-11-17 09:00:09 INFO MainThread connected to Midnight Club at club.example.test:8443 (%s)" % OTHER,
            ]) + "\n")
        with open(st.launcher_log() + ".1", "w", encoding="utf-8") as f:
            f.write("an older log, signed in as %s on %s\n" % (ACCOUNT, SERVER))
        # The game's folder with this PC's player id, and the game's log: its address, its device id, what was typed.
        game = player.data_folder(PACKAGE)
        os.makedirs(os.path.join(game, "data"))
        with open(os.path.join(game, "data", "android_id"), "w", encoding="utf-8") as f:
            f.write(DEVICE + "\n")
        apps_folder = apps.folder(SERVER)
        os.makedirs(apps_folder)
        with open(os.path.join(apps_folder, apps.DETAILS), "w", encoding="utf-8") as f:
            json.dump({"file": "opendmtq-phone-app-2026.11.09-android-192.168.1.10-8791.apk", "sha256": "0" * 64,
                       "size": 4, "package": PACKAGE}, f)
        with open(os.path.join(apps_folder, "opendmtq-phone-app-2026.11.09-android-192.168.1.10-8791.apk"), "wb") as f:
            f.write(b"PK\x03\x04")
        with open(os.path.join(apps_folder, apps.CONF), "w", encoding="utf-8") as f:
            f.write("package=%s\n" % PACKAGE)
        with open(player.log_path(PACKAGE), "w", encoding="utf-8") as f:
            f.write("old line\n" * 10 + "player: platform login udid=%s at http://192.168.1.10:8791/api\n" % DEVICE
                    + 'player: typed "Sena Kim"\nplayer: live: upload to http://192.168.1.10:8791/live/up?key=abcdef&n=1\n')
        player.write_settings(self.state.values, "ko")

    def make(self, **kw):
        """The report made into the test's folder, and its files as text."""
        path, left = report.make(self.state, path=os.path.join(self.home, "out", "report.zip"),
                                 devices=[{"id": "{0.0.0.00000000}.{aaaa}", "name": "Speakers (made up)", "default": True}],
                                 **kw)
        with zipfile.ZipFile(path) as z:
            return path, left, {name: z.read(name).decode("utf-8") for name in z.namelist()}


class Report(Played):
    def test_what_goes_in(self):
        path, _left, files = self.make()
        self.assertEqual(sorted(files), ["about.txt", "launcher/launcher.log", "launcher/launcher.log.1", "player/player.log",
                                         "settings/player-settings.txt", "settings/settings.json", "system/displays.txt",
                                         "system/sound.txt"])
        about = files["about.txt"]
        for line in ("launcher: ", "player: ", "Windows: ", "graphics: ", "Left out, each replaced by a word"):
            self.assertIn(line, about)
        self.assertIn("Speakers (made up) (default)", files["system/sound.txt"])
        self.assertIn("language=ko", files["settings/player-settings.txt"])
        # The PC's settings as they are, the server's sign-in out.
        self.assertEqual(json.loads(files["settings/settings.json"])["values"]["volume"], self.state.values["volume"])

    def test_nothing_that_names_a_person_or_signs_in_comes_out(self):
        _path, left, files = self.make()
        everything = "\n".join(files.values())
        for private in (SERVER, "192.168.1.10", "192.168.1.10-8791", OTHER, "club.example.test", "Sena's Room",
                        "Midnight Club", COOKIE, API_TOKEN, "s3cr3t", "abcdef", DEVICE, "Sena Kim",
                        os.path.basename(self.home), "as " + ACCOUNT, "--sign-in " + ACCOUNT, '"account": "player"'):
            self.assertNotIn(private, everything, private)
        # Each in its place, by the word for it: the log reads as before.
        log = files["launcher/launcher.log"]
        self.assertIn("could not sign in to <server> as <account>: the ID or the password is wrong", log)
        self.assertIn("started: --sign-in <account>", log)
        self.assertIn(os.path.join(os.path.dirname(self.home), "<user>", "AppData", "Local", "OpenDMTQ.Client"), log)
        self.assertIn(os.path.join("servers", "<server>"), log)
        self.assertIn("?token=<token>&os=win", log)
        self.assertIn("opendmtq_dl=<cookie>", log)
        self.assertIn("connected to <server name> at <server> (<server>)", log)
        game = files["player/player.log"]
        self.assertIn("udid=<device id> at <server>/api", game)
        self.assertIn('typed "<typed>"', game)
        self.assertIn("key=<token>&n=1", game)
        # An ID that is a word of the logs' own is left out only where an ID is written: "player:" stays.
        self.assertIn("player: FMOD output", log)
        # The settings' servers in their order: the other one first, then the one signed in, its cookie out.
        other, server = json.loads(files["settings/settings.json"])["servers"]
        self.assertEqual((server["url"], server["account"], server["cookie"], server["expires"], server["name"]),
                         ("<server>", "<account>", "<cookie>", "<cookie>", "<server name>"))
        self.assertEqual((other["url"], other["account"], other["cookie"]), ("<server>", "<account>", None))
        # What was left out, kind by kind, as the window and --report say it.
        self.assertEqual([kind for kind, _n in left], ["user", "account", "server", "server_name", "cookie", "token",
                                                        "device", "typed"])
        self.assertIn("<device id> device: ", files["about.txt"])
        self.assertEqual(report.left_words(i18n.Words("en"), left[:3]),
                         "your Windows user name in paths, your site ID, the servers' addresses")
        self.assertEqual(report.left_words(i18n.Words("ko"), left[:3]), "경로 속 Windows 사용자 이름, 사이트 아이디, 서버 주소")
        self.assertEqual(report.left_words(i18n.Words("en"), []), "nothing of the kind was found")

    def test_a_sound_device_named_after_a_person(self):
        # Windows names a Bluetooth headset's outputs as its owner's phone named it, in English with the curly apostrophe
        # a phone writes, or the straight one, and in Korean; a second device of a name gets "2- " before it. The owner's
        # name is left out of the list of devices and of the player's log naming the device it opened (main kept both
        # whole); a device named after nobody stays as it was, and so does the same name as a word of a log's own.
        devices = [{"id": "{0.0.0.00000000}.{bbbb}", "name": "Headphones (Sena Kim’s AirPods Pro)", "default": True},
                   {"id": "{0.0.0.00000000}.{cccc}", "name": "Headset (Sena Kim's AirPods Pro Hands-Free AG Audio)",
                    "default": False},
                   {"id": "{0.0.0.00000000}.{dddd}", "name": "헤드폰(김세나의 Galaxy Buds2 Pro)", "default": False},
                   {"id": "{0.0.0.00000000}.{eeee}", "name": "Speakers (2- Max's Speaker)", "default": False},
                   {"id": "{0.0.0.00000000}.{ffff}", "name": "Speakers (Realtek(R) Audio)", "default": False}]
        with open(player.log_path(PACKAGE), "a", encoding="utf-8") as f:
            f.write('player: sound: the game\'s OpenAL asked for the device default and opened "OpenAL Soft on '
                    'Headphones (Sena Kim’s AirPods Pro)"\nplayer: frame rate max 240 Hz\n')
        path, left = report.make(self.state, path=os.path.join(self.home, "out", "people.zip"), devices=devices)
        with zipfile.ZipFile(path) as z:
            files = {name: z.read(name).decode("utf-8") for name in z.namelist()}
        everything = "\n".join(files.values())
        for private in ("Sena Kim", "김세나", "Max's"):
            self.assertNotIn(private, everything, private)
        sound = files["system/sound.txt"]
        for line in ("Headphones (<name>’s AirPods Pro) (default)", "Headset (<name>'s AirPods Pro Hands-Free AG Audio)",
                     "헤드폰(<name>의 Galaxy Buds2 Pro)", "Speakers (2- <name>'s Speaker)", "Speakers (Realtek(R) Audio)"):
            self.assertIn(line, sound)
        self.assertIn('opened "OpenAL Soft on Headphones (<name>’s AirPods Pro)"', files["player/player.log"])
        # Where the name stands as the device's owner, nowhere else.
        self.assertIn("player: frame rate max 240 Hz", files["player/player.log"])
        # Said with what else was left out, by its own words, in both languages.
        self.assertIn(("person", 5), left)
        self.assertIn("<name> person: 5", files["about.txt"])
        self.assertEqual(report.left_words(i18n.Words("en"), [("person", 5)]), "people's names in sound devices' names")
        self.assertEqual(report.left_words(i18n.Words("ko"), [("person", 5)]), "소리 장치 이름 속 사람 이름")

    def test_only_the_end_of_a_long_game_log(self):
        with open(player.log_path(PACKAGE), "w", encoding="utf-8") as f:
            f.write("an old game's line\n" * 60000 + "the last game's line\n")
        _path, _left, files = self.make()
        game = files["player/player.log"]
        self.assertLessEqual(len(game.encode()), report.PLAYER_LOG_TAIL)
        self.assertTrue(game.endswith("the last game's line\n"))
        # From a line's start: no half line at its top.
        self.assertTrue(game.startswith("an old game's line\n"))

    def test_written_whole_or_not_at_all(self):
        with mock.patch.object(zipfile.ZipFile, "writestr", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                self.make()
        self.assertEqual(os.listdir(os.path.join(self.home, "out")), [])

    def test_its_name_says_what_it_is_and_when_in_lower_case(self):
        name = os.path.basename(report.default_path(now=1795400000))
        self.assertRegex(name, r"^opendmtq-report-\d{8}-\d{6}\.zip$")
        self.assertEqual(name, name.lower())

    def test_without_an_app_or_a_server_it_still_says_what_there_is(self):
        self.state = st.LauncherState()
        path, left, files = self.make()
        self.assertNotIn("player/player.log", files)
        self.assertIn("about.txt", files)
        self.assertIsInstance(left, list)
        self.assertTrue(os.path.isfile(path))

    def run_main(self, args):
        """main() with these arguments; (exit code, what it printed)."""
        from opendmtq_client import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = main.main(args)
        return code, out.getvalue()

    def test_the_saved_connection_test_of_any_address(self):
        # The last test was of an address this launcher does not know (--test-server ADDRESS), a name it looked up, and
        # of the known server with the kept ID right before a period ("Signed in as sena. The server is building ...").
        from opendmtq_client import connection
        result = connection.Result(UNKNOWN)
        result.step("address").done("ok", "ok", 1, url=UNKNOWN, scheme="http", host="198.51.100.9", port=8791)
        result.step("lookup").done("ok", "ok", 1, host="lan.example.test", addresses="203.0.113.77, 2001:db8::77")
        result.step("server").done("ok", "ok", 4, name="Far Hall", version="0.11.0")
        result.step("signin").done("ok", "app_building", 5, account=ACCOUNT)
        result.step("broadcasts").done("bad", "no_answer", 5, error="cannot reach %s (timed out)" % UNKNOWN)
        result.ended = True
        connection.save(result)
        _path, _left, files = self.make()
        kept = files["system/connection-test.txt"]
        for private in ("198.51.100.9", "lan.example.test", "203.0.113.77", "2001:db8::77", "Far Hall", ACCOUNT):
            self.assertNotIn(private, kept, private)
        # Each in its place, by the word for it: the test reads as before.
        self.assertIn("Connection test of <server>", kept)
        self.assertIn("<server> is at <server>, <server>.", kept)
        self.assertIn("<server name>, OpenDMTQ 0.11.0.", kept)
        self.assertIn("Signed in as <account>. The server is building its app", kept)
        self.assertIn("cannot reach <server> (timed out)", kept)

    def test_the_command_line(self):
        # A folder: the report's own name in it.
        os.makedirs(os.path.join(self.home, "out"))
        code, said = self.run_main(["--report", os.path.join(self.home, "out")])
        self.assertEqual(code, 0, said)
        made = os.listdir(os.path.join(self.home, "out"))
        self.assertEqual(len(made), 1)
        self.assertRegex(made[0], r"^opendmtq-report-\d{8}-\d{6}\.zip$")
        self.assertIn("Saved the report: %s" % os.path.join(self.home, "out", made[0]), said)
        self.assertIn("Left out: your Windows user name in paths, your site ID, the servers' addresses", said)
        # A file named: that file, a zip by its name too.
        code, said = self.run_main(["--report", os.path.join(self.home, "mine.zip")])
        self.assertEqual(code, 0, said)
        self.assertTrue(zipfile.is_zipfile(os.path.join(self.home, "mine.zip")))
        code, said = self.run_main(["--report", os.path.join(self.home, "problem")])
        self.assertTrue(zipfile.is_zipfile(os.path.join(self.home, "problem.zip")), said)
        # Allowed while the window is open: it changes nothing the window keeps.
        with mock.patch("opendmtq_client.main.window_open", lambda: True):
            code, said = self.run_main(["--report", os.path.join(self.home, "again.zip")])
        self.assertEqual(code, 0, said)
        self.assertNotIn("window is open", said)
        # In --help, with the jobs of help and upkeep.
        with self.assertRaises(SystemExit):
            self.run_main(["--help"])


class EveryForm(Played):
    """Every site ID and every server's address and name left out by where and how the launcher writes them, whatever they
    are: also those today's settings no longer know (a server forgotten, an address typed, an ID typed wrong), in the
    logs before this one too. The lines are as the launcher and the game write them (a real launcher.log and player.log
    of a run under Wine read for their forms), with made-up values."""

    def logged(self, *lines, name="launcher.log"):
        """Lines added to one of the launcher's logs, each with the log's own time stamp, level and thread."""
        with open(os.path.join(os.path.dirname(st.launcher_log()), name), "a", encoding="utf-8") as f:
            f.write("".join("2026-11-17 07:57:13,%03d %s\n" % (i, line) for i, line in enumerate(lines)))

    def test_ids_by_their_place(self):
        self.logged(
            # --sign-in's own line, its ID right before the sentence's period.
            "INFO MainThread Signed in as %s." % ACCOUNT,
            # --status: the sign-in, and the ready check's account line (also one that ended).
            "INFO MainThread signed in: %s" % ACCOUNT,
            "INFO MainThread signed in: no (%s, ended)" % ONCE_ID,
            "INFO MainThread   [ok  ] account: %s" % ACCOUNT,
            "INFO MainThread   [warn] account: not signed in",
            # A sign-in the window could not make, the ID as typed (a blank in it), on a server forgotten since.
            "INFO sign-in could not sign in to %s as %s: the ID or the password is wrong" % (FORGOTTEN, WRONG_ID),
            # An installer's ID, and the command line's arguments as the first line says them.
            "INFO MainThread the installer brought the ID %s to sign in with" % ONCE_ID,
            "INFO MainThread OpenDMTQ 0.11.1 started: --server %s --sign-in=%s" % (TYPED, ONCE_ID))
        self.logged("INFO MainThread an older log, signed in as %s on %s" % (ONCE_ID, FORGOTTEN), name="launcher.log.2")
        _path, _left, files = self.make()
        everything = "\n".join(files.values())
        for private in (ACCOUNT + ".", "signed in: " + ACCOUNT, "account: " + ACCOUNT, ONCE_ID, "sena kim", "as sena"):
            self.assertNotIn(private, everything, private)
        log = files["launcher/launcher.log"]
        for line in ("Signed in as <account>.", "signed in: <account>", "signed in: no (<account>, ended)",
                     "[ok  ] account: <account>", "[warn] account: not signed in",
                     "could not sign in to <server> as <account>: the ID or the password is wrong",
                     "the installer brought the ID <account> to sign in with", "--sign-in=<account>"):
            self.assertIn(line, log)
        self.assertIn("signed in as <account> on <server>", files["launcher/launcher.log.2"])

    def test_servers_today_s_settings_do_not_know(self):
        self.logged(
            # An address typed in the window that did not answer, and one given to --test-server.
            "INFO connect could not connect to %s: cannot reach http://%s (timed out)" % (TYPED, TYPED),
            "INFO MainThread OpenDMTQ 0.11.1 started: --test-server 203.0.113.5:8791",
            # A name on the network without a dot, an IPv6 address in brackets with its port and one bare.
            "WARNING update-look could not ask %s for its version: cannot reach %s (timed out)" % (LAN, LAN),
            "INFO MainThread connection test: [ok  ] Name lookup  gamepc is at 192.168.1.20.",
            "INFO play started the game for http://[2001:db8::10]:8791 (process 732)",
            "INFO MainThread connection test: [ok  ] Name lookup  v6.example.test is at 2001:db8::10, fd00::7.")
        # A server forgotten since, in the oldest log: --server's line, --servers', --status's and its ready check's, its
        # app's file and folder, a start while it did not answer.
        self.logged(
            "INFO MainThread Connected to %s (%s)." % (FORGOTTEN_NAME, FORGOTTEN),
            "INFO MainThread * %s (%s)" % (FORGOTTEN_NAME, FORGOTTEN),
            "INFO MainThread server: %s (%s)" % (FORGOTTEN_NAME, FORGOTTEN),
            "INFO MainThread   [ok  ] server: %s (%s)" % (FORGOTTEN_NAME, FORGOTTEN),
            "INFO MainThread app: opendmtq-phone-app-2026.11.17-android-dmtq.forgotten.test-8791.apk (2026-11-17T07:52:36)",
            "INFO MainThread cleared C:\\Users\\x\\AppData\\Local\\OpenDMTQ\\client\\servers\\dmtq.forgotten.test-8791",
            "INFO MainThread %s did not answer; playing on it as known (%s)." % (FORGOTTEN_NAME, FORGOTTEN),
            "INFO MainThread connection test: [ok  ] OpenDMTQ server  %s, OpenDMTQ 0.11.0." % FORGOTTEN_NAME,
            name="launcher.log.2")
        # The game's own line for its broadcasts' server, as the player writes it.
        with open(player.log_path(PACKAGE), "a", encoding="utf-8") as f:
            f.write("player: live: asks dmtq.forgotten.test:8791\n")
        _path, _left, files = self.make()
        everything = "\n".join(files.values())
        for private in ("10.20.30.40", "203.0.113.5", "gamepc", "192.168.1.20", "2001:db8::10", "fd00::7",
                        "v6.example.test", "dmtq.forgotten.test", FORGOTTEN_NAME):
            self.assertNotIn(private, everything, private)
        log, old = files["launcher/launcher.log"], files["launcher/launcher.log.2"]
        for line in ("could not connect to <server>: cannot reach <server> (timed out)", "--test-server <server>",
                     "could not ask <server> for its version", "Name lookup  <server> is at <server>.",
                     "started the game for <server> (process 732)", "<server> is at <server>, <server>."):
            self.assertIn(line, log)
        for line in ("Connected to <server name> (<server>).", "* <server name> (<server>)",
                     "server: <server name> (<server>)", "[ok  ] server: <server name> (<server>)",
                     "opendmtq-phone-app-2026.11.17-android-<server>.apk", "\\servers\\<server>",
                     "<server name> did not answer; playing on it as known (<server>).",
                     "OpenDMTQ server  <server name>, OpenDMTQ 0.11.0."):
            self.assertIn(line, old)
        self.assertIn("player: live: asks <server>", files["player/player.log"])

    def test_an_ipv4_address_in_ipv6s_form_is_left_out_whole(self):
        # A name looked up to an IPv4 address in IPv6's form for one (::ffff: and the address), as Windows' lookup can
        # give it: in the test the launcher saved and in its log's line of it, the whole address goes, none of its parts
        # left behind (main left "<server>.168.7.20"); a version of five parts stays as it is.
        from opendmtq_client import connection
        mapped = "::ffff:192.168.7.20"
        result = connection.Result("http://lanbox.example.test:8791")
        result.step("address").done("ok", "ok", 1, url="http://lanbox.example.test:8791", scheme="http",
                                    host="lanbox.example.test", port=8791)
        result.step("lookup").done("ok", "ok", 1, host="lanbox.example.test", addresses=mapped)
        result.ended = True
        connection.save(result)
        self.logged("INFO connection-test connection test: [ok  ] Name lookup  lanbox.example.test is at %s.  (3 ms)" % mapped,
                    "INFO MainThread player: v1.2.3.4.5 and ::ffff:1.2.3.4.5")
        _path, _left, files = self.make()
        everything = "\n".join(files.values())
        for private in ("168.7.20", "192.168.7", "::ffff:192"):
            self.assertNotIn(private, everything, private)
        self.assertIn("Name lookup  <server> is at <server>.  (3 ms)", files["launcher/launcher.log"])
        self.assertIn("<server> is at <server>.", files["system/connection-test.txt"])
        self.assertIn("player: v1.2.3.4.5 and ::ffff:1.2.3.4.5", files["launcher/launcher.log"])

    def test_the_connection_tests_lines_however_they_are_worded(self):
        # Every line of the test that holds an ID, a server's name or a host, as the window logs it and as --test-server
        # says it, with values no settings know: each is left out by the words around it, the words as they are now.
        from opendmtq_client import connection, i18n
        values = {"account": "zed.k_9", "name": "Hidden Hall", "host": "quiet.example.test"}
        lines = []
        for key, (english, _korean) in sorted(i18n.TEXT.items()):
            fields = set(re.findall(r"\{(\w+)\}", english))
            if not key.startswith("test.") or not fields & set(values):
                continue
            words = english.format(**{f: values.get(f, "1") for f in fields})
            step = key.split(".")[1]
            named = i18n.TEXT.get("test." + step, ("",))[0] if step in connection.STEPS else ""
            lines += ["INFO MainThread connection test: [ok  ] %s  %s" % (named.ljust(16), words),
                      "INFO MainThread   [ok  ] %s: %s  (12 ms)" % (named, words)]
        self.assertGreater(len(lines), 20)
        self.logged(*lines)
        _path, _left, files = self.make()
        log = files["launcher/launcher.log"]
        for private in values.values():
            self.assertNotIn(private, log, private)

    def test_what_names_no_one_reads_as_before(self):
        # Times, versions, keys, a sound device's id, file names with dots and the project's own address on GitHub are no
        # server's: they stay as they were.
        kept = ["INFO MainThread OpenDMTQ 0.11.1 started",
                "INFO MainThread settings: keys_2line=F/Semicolon J/Q, keys_3line=D F J",
                "WARNING update-look could not check for updates: <urlopen error [Errno 11002] getaddrinfo failed>",
                "WARNING update-look refused the update to 0.11.2 from https://github.com/example/opendmtq: not signed",
                "INFO MainThread display: \\\\.\\DISPLAY1 (main): 1920 x 1080, now at 59.951 Hz",
                "INFO MainThread repair: current\\player\\libEGL.dll",
                "INFO MainThread player: v0.11.0-4f4acaf4 (built 2026-11-17T07:52:36), audio {0.0.0.00000000}.{aaaa}",
                "INFO MainThread the game ended after 163 s with 0"]
        self.logged(*kept)
        _path, _left, files = self.make()
        log = files["launcher/launcher.log"]
        for line in kept:
            self.assertIn(line, log)
        self.assertIn("2026-11-17 07:57:13,000 INFO", log)
