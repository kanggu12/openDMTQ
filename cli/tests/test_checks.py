"""Tests for `opendmtq doctor`: each mismatch that leaves phones unable to connect or update fails."""

import hashlib
import json
import os
import time
import unittest
from unittest import mock

from opendmtq_cli import app, checks, env

from .sandbox import Sandbox


def install(sb, key=b"key", signed_with=None):
    """A complete install: game data, base APK, a running server, and an app built for .env's
    address and signed with signed_with (the key in data/apk/keystore by default)."""
    host = sb.env()["PUBLIC_HOST"]
    sb.write("data/content/web/patch/phone_new/1.003.005/android/patch_new.csv.lz4", b"")
    sb.write("data/apk/base/client.apk", b"apk")
    if key is not None:
        sb.write("data/apk/keystore/opendmtq.jks", key)
    sb.write("data/apk/out/OpenDMTQ-x.apk", b"app")
    sb.write("data/apk/out/latest.json", json.dumps({
        "file": "OpenDMTQ-x.apk", "host": host, "runtime": None,
        "key_sha256": hashlib.sha256(signed_with or key).hexdigest()}))
    sb.state = "running"


class DoctorTest(unittest.TestCase):
    def test_a_complete_install_passes(self):
        with Sandbox() as sb:
            install(sb)
            self.assertEqual(checks.doctor(), 0, sb.output())

    def test_an_app_signed_with_another_key_fails(self):
        # restore --with-key put the old key back, but /apk still offers the app signed with the new one.
        with Sandbox() as sb:
            install(sb, key=b"old key", signed_with=b"key made by setup")
            self.assertEqual(checks.doctor(), 1, sb.output())
            self.assertIn("./opendmtq apk", sb.output())

    def test_a_missing_key_fails(self):
        with Sandbox() as sb:
            install(sb, key=None, signed_with=b"lost key")
            self.assertEqual(checks.doctor(), 1, sb.output())
            self.assertIn("--with-key", sb.output())

    def test_a_stopped_edge_fails(self):
        with Sandbox() as sb:
            install(sb)
            sb.edge = "exited"
            self.assertEqual(checks.doctor(), 1, sb.output())
            self.assertIn("edge proxy", sb.output())

    def test_a_broken_https_door_fails(self):
        with Sandbox() as sb:
            install(sb)
            sb.https = "HTTPS does not answer on port 80"
            self.assertEqual(checks.doctor(), 1, sb.output())
            self.assertIn("HTTPS does not answer", sb.output())

    def test_lan_address_and_listen_port_must_agree(self):
        # The app calls port 80 (no port in the address), the server listens on 8790.
        with Sandbox("PUBLIC_HOST=192.168.0.20\nLISTEN_PORT=8790\n", detected="192.168.0.20") as sb:
            install(sb)
            self.assertEqual(checks.doctor(), 1, sb.output())
            self.assertIn("8790", sb.output())

    def test_a_port_in_the_lan_address_is_not_a_new_address(self):
        with Sandbox("PUBLIC_HOST=192.168.0.10:8080\nLISTEN_PORT=8080\n") as sb:
            install(sb)
            self.assertEqual(checks.doctor(), 0, sb.output())
            self.assertNotIn("now uses", sb.output())

    def test_docker_desktop_nat_address_is_not_offered_as_the_new_one(self):
        # WSL in NAT mode with Docker Desktop: phones use the Windows address, WSL routes from 172.x.
        with Sandbox(detected="172.22.80.5", wsl=True) as sb:
            install(sb)
            checks.doctor()
            self.assertNotIn("172.22.80.5", sb.output())

    def test_repository_on_a_windows_drive_is_flagged(self):
        with Sandbox() as sb:
            install(sb)
            with mock.patch.object(env, "windows_drive", return_value=True, create=True):
                checks.doctor()
            self.assertIn("Windows drive", sb.output())


def game_server(host):
    """checks.http in place of a working server on 127.0.0.1:80 that sends phones to host."""
    def answer(url, data=None, json_body=None, method=None, timeout=10, headers=None):
        prefix = "http://127.0.0.1:80"
        if not url.startswith(prefix + "/"):
            return 0, b""
        path = url[len(prefix):]
        if path == "/opendmtq/health.php":
            return 200, json.dumps({"ok": True, "host": host}).encode()
        if path == "/DMQ/rpc":
            results = {
                "service.getInfo": {"api_url": f"http://{host}/DMQ/rpc", "file_server_url": f"http://{host}/",
                                    "event_url": f"http://{host}/event/", "file_manage_ver": "1.003.005"},
                "user.loginV2": {"guid": "7"},
                "game.getSongUrl": {"pmang": [f"http://{host}/DMQ/Songs/1/1.fpk"]},
                "game.getPatternUrl": f"http://{host}/DMQ/Patterns/1",
            }
            return 200, json.dumps([{"id": 1, "result": results[json_body[0]["method"]]}]).encode()
        if path.endswith("/login_dmq"):
            return 200, json.dumps({"value": {"access_token": "token"}}).encode()
        files = {"/DMQ/Patterns/1", "/apk"} | {f"/DMQ/Songs/{i}/{i}.fpk" for i in (1, 2)} \
            | {f"/viewImg/eye/{name}.png" for name in ("paperplanes", "neonrain")}
        return (200, b"") if path in files else (404, b"")
    return answer


class EndToEndTest(unittest.TestCase):
    def test_a_working_server_passes_every_step(self):
        # The walk reaches the song files and the download, all on this machine's server.
        with Sandbox() as sb:
            sb.write("data/content/songs.json",
                     json.dumps([{"song_id": 1, "name": "paperplanes"}, {"song_id": 2, "name": "neonrain"}]))
            sb.state = "running"
            # The download is behind the site's sign-in: a stranger is sent to it.
            to_sign_in = lambda method, path, *a, **k: (302, {"Location": "/opendmtq/login.php?next=%2Fapk"}, b"") if path == "/apk" else (404, {}, b"")
            with mock.patch.object(checks, "http", game_server("192.168.0.10")), mock.patch.object(checks, "_raw", to_sign_in):
                self.assertEqual(checks.end_to_end(), 0, sb.output())
            self.assertIn("all 2 songs", sb.output())

    def test_lan_address_and_listen_port_must_agree(self):
        # Every request of the walk goes to LISTEN_PORT, so only this check can see it.
        with Sandbox("PUBLIC_HOST=192.168.0.20\nLISTEN_PORT=8790\n") as sb:
            sb.state = "running"
            # Nothing answers RPC here; the walk stops after the boot call.
            self.assertGreaterEqual(checks.end_to_end(), 2, sb.output())
            self.assertIn("8790", sb.output())


class BuildStatusTest(unittest.TestCase):
    """The builder's last run (data/apk/out/build.json): when it failed, ./opendmtq up stops on it and
    the portal may tell players to ask the owner, so doctor and status say why."""

    def status(self, sb, **fields):
        sb.write("data/apk/out/build.json", json.dumps({"host": sb.env()["PUBLIC_HOST"], "time": int(time.time()),
                                                        **fields}))

    def test_doctor_says_why_there_is_no_app(self):
        # "run ./opendmtq apk" alone would fail the same way.
        with Sandbox() as sb:
            install(sb)
            os.remove(sb.path("data/apk/out/latest.json"))
            self.status(sb, state="failed", error="data/apk/base holds different clients; choose one with "
                                                  "BASE_APK=<file name> in .env: a.apk, b.apk")
            self.assertEqual(checks.doctor(), 1, sb.output())
            self.assertIn("holds different clients", sb.output())

    def test_doctor_says_when_the_game_data_came_without_its_screens(self):
        with Sandbox() as sb:
            install(sb)
            sb.write("data/custom/missing-game-files.json", json.dumps(["dlc/d3_a0.unity3d"]))
            self.assertGreaterEqual(checks.doctor(), 1, sb.output())
            self.assertIn("of the game's own files are missing (dlc/d3_a0.unity3d", sb.output())
            self.assertIn("Import the whole server files again", sb.output())

    def test_doctor_fails_on_a_failed_rebuild(self):
        # An app for this address exists, but rebuilding it failed: every up stops on that.
        with Sandbox() as sb:
            install(sb)
            self.status(sb, state="failed", error="smali ExternalSDK.smali: expected 1 match(es), found 0")
            self.assertEqual(checks.doctor(), 1, sb.output())
            self.assertIn("expected 1 match(es), found 0", sb.output())
            self.assertIn("phones still get OpenDMTQ-x.apk", sb.output())

    def test_a_build_cut_off_long_ago_is_a_failure(self):
        with Sandbox() as sb:
            install(sb)
            self.status(sb, state="building", time=int(time.time()) - checks.STALE_BUILD - 60)
            self.assertEqual(checks.doctor(), 1, sb.output())
            self.assertIn("stopped part-way", sb.output())

    def test_a_build_under_way_or_done_is_no_problem(self):
        with Sandbox() as sb:
            install(sb)
            self.status(sb, state="building")
            self.assertEqual(checks.doctor(), 0, sb.output())
            self.status(sb, state="done")
            self.assertEqual(checks.doctor(), 0, sb.output())

    def test_a_failure_for_another_address_is_not_this_ones(self):
        with Sandbox() as sb:
            install(sb)
            sb.write("data/apk/out/build.json", json.dumps({"state": "failed", "host": "10.0.0.1", "error": "x"}))
            self.assertEqual(checks.doctor(), 0, sb.output())

    def test_status_shows_a_failed_build(self):
        with Sandbox() as sb:
            install(sb)
            self.status(sb, state="failed", error="signing failed")
            sb.call(app.cmd_status)
            self.assertIn("FAILED: signing failed", sb.output())


class WordingTest(unittest.TestCase):
    def test_an_app_without_the_runtime_is_for_phones_that_run_32_bit_apps(self):
        # It runs on 64-bit phones that still run 32-bit apps too, not on 32-bit phones only.
        with Sandbox() as sb:
            install(sb)
            checks.doctor()
            self.assertIn("phones that still run 32-bit apps", sb.output())
            self.assertNotIn("32-bit phones only", sb.output())


if __name__ == "__main__":
    unittest.main()
