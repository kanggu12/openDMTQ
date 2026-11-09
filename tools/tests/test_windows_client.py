"""The installer for Windows beside the app: where it comes from (the copy beside the code, one in data/apk, the latest
release), what a damaged copy, a failed fetch or a stop leave, how it is described in windows.json, and the server's
address it carries on its end as it is handed out."""

import contextlib
import io
import json
import os
import struct
import tempfile
import time
import unittest
from unittest import mock

from opendmtq_tools import windows_client


# A certificate authority's certificate as tls.py writes it: a made-up body, never used to connect.
CA = "-----BEGIN CERTIFICATE-----\nMIIBszCCAVmgAwIBAgIUQmFkZ2Vy+/made/up=\nAAAA\n-----END CERTIFICATE-----"


def installer(path, body=b"the installer", version=None):
    """An installer as a release ships it, at the smallest size the builder takes: a Windows program's first bytes, then
    `body` and padding. `version`: the .version file beside it, as a release or a fetch writes it."""
    with open(path, "wb") as f:
        f.write(b"MZ" + body + bytes(windows_client.SMALLEST))
    if version is not None:
        with open(path + ".version", "w", encoding="utf-8") as f:
            f.write(version + "\n")
    return path


def written_ago(path, days=0, hours=0):
    """A file's time set back, as if it had been written that long ago."""
    when = time.time() - days * 24 * 3600 - hours * 3600
    os.utime(path, (when, when))


class Answer(io.BytesIO):
    """What urlopen gives for a download that worked: the body, and the address the redirects ended at."""

    def __init__(self, body, url):
        super().__init__(body)
        self.url = url

    def geturl(self):
        return self.url


class Place:
    """data/apk in a temporary folder, with its out folder, and the code's folder with nothing beside the code."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.apk = self._tmp.name
        self.out = os.path.join(self.apk, "out")
        self.code = os.path.join(self.apk, "code")
        os.makedirs(self.out)
        os.makedirs(self.code)
        # Nothing beside the code unless a test puts it there, and no way out to the internet unless a test opens one.
        self._patches = [mock.patch.object(windows_client, "HERE", self.code),
                         mock.patch.object(windows_client.urllib.request, "urlopen", side_effect=OSError("no way out")),
                         contextlib.redirect_stdout(io.StringIO())]
        for p in self._patches:
            p.__enter__()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.__exit__(*exc)
        self._tmp.cleanup()


class WholeTest(unittest.TestCase):
    def test_an_installer_as_released_is_whole(self):
        with Place() as p:
            self.assertTrue(windows_client.whole(installer(os.path.join(p.apk, "a.exe"))))

    def test_what_is_not_the_installer_is_not_whole(self):
        with Place() as p:
            small = os.path.join(p.apk, "small.exe")
            with open(small, "wb") as f:
                f.write(b"MZ cut off")
            # Not a Windows program at all (an error page saved under the name), cut off, handed out with a server's
            # address on its end, or not there.
            page = os.path.join(p.apk, "page.exe")
            with open(page, "wb") as f:
                f.write(b"<html>" + bytes(windows_client.SMALLEST))
            handed = installer(os.path.join(p.apk, "handed.exe"))
            with open(handed, "ab") as f:
                f.write(windows_client.preset("http://example.com:8080", "example.com:8080"))
            for path in (small, page, handed, os.path.join(p.apk, "none.exe")):
                with self.subTest(path=os.path.basename(path)):
                    self.assertFalse(windows_client.whole(path))


class FindTest(unittest.TestCase):
    def test_the_copy_beside_the_code_comes_first(self):
        with Place() as p:
            beside = installer(os.path.join(p.code, windows_client.SETUP_NAME), version="1.2.3")
            installer(os.path.join(p.apk, windows_client.SETUP_NAME), version="1.0.0")
            self.assertEqual(windows_client.find(p.apk), (beside, "1.2.3"))

    def test_a_copy_in_data_apk_is_used_while_recent(self):
        with Place() as p:
            placed = installer(os.path.join(p.apk, windows_client.SETUP_NAME), version="1.0.0")
            self.assertEqual(windows_client.find(p.apk), (placed, "1.0.0"))
            # Without its version file (a copy put there by hand): no version to tell.
            os.remove(placed + ".version")
            self.assertEqual(windows_client.find(p.apk), (placed, ""))

    def test_a_week_old_copy_gives_way_to_the_latest_release(self):
        with Place() as p:
            placed = installer(os.path.join(p.apk, windows_client.SETUP_NAME), body=b"old", version="1.0.0")
            written_ago(placed, days=8)
            newer = Answer(b"MZnew" + bytes(windows_client.SMALLEST), "https://github.com/o/r/releases/download/v1.1.0/OpenDMTQ-Setup.exe")
            with mock.patch.object(windows_client.urllib.request, "urlopen", return_value=newer) as urlopen:
                self.assertEqual(windows_client.find(p.apk), (placed, "1.1.0"))
            self.assertEqual(urlopen.call_args.args[0], windows_client.RELEASE_URL)
            with open(placed, "rb") as f:
                self.assertEqual(f.read(5), b"MZnew")

    def test_a_week_old_copy_stays_when_the_release_cannot_be_had(self):
        with Place() as p:
            placed = installer(os.path.join(p.apk, windows_client.SETUP_NAME), version="1.0.0")
            written_ago(placed, days=8)
            self.assertEqual(windows_client.find(p.apk), (placed, "1.0.0"))
            # Why, for whoever looks, and no new try within the day.
            with open(os.path.join(p.apk, windows_client.FAILED), encoding="utf-8") as f:
                self.assertIn("no way out", f.read())
            with mock.patch.object(windows_client.urllib.request, "urlopen") as urlopen:
                windows_client.find(p.apk)
            urlopen.assert_not_called()

    def test_a_day_after_a_failed_fetch_it_is_tried_again(self):
        with Place() as p:
            windows_client.find(p.apk)
            failed = os.path.join(p.apk, windows_client.FAILED)
            self.assertTrue(os.path.isfile(failed))
            written_ago(failed, days=1, hours=1)
            fetched = Answer(b"MZ" + bytes(windows_client.SMALLEST), "https://github.com/o/r/releases/download/v2.0.0/OpenDMTQ-Setup.exe")
            with mock.patch.object(windows_client.urllib.request, "urlopen", return_value=fetched):
                path, version = windows_client.find(p.apk)
            self.assertEqual((os.path.basename(path), version), (windows_client.SETUP_NAME, "2.0.0"))
            # It worked: the failure's note goes.
            self.assertFalse(os.path.exists(failed))

    def test_a_damaged_download_replaces_nothing(self):
        with Place() as p:
            placed = installer(os.path.join(p.apk, windows_client.SETUP_NAME), body=b"good", version="1.0.0")
            written_ago(placed, days=8)
            cut = Answer(b"MZ cut off", "https://github.com/o/r/releases/download/v1.1.0/OpenDMTQ-Setup.exe")
            with mock.patch.object(windows_client.urllib.request, "urlopen", return_value=cut):
                self.assertEqual(windows_client.find(p.apk), (placed, "1.0.0"))
            with open(placed, "rb") as f:
                self.assertEqual(f.read(6), b"MZgood")
            self.assertFalse(os.path.exists(placed + ".part"))

    def test_a_damaged_copy_goes(self):
        with Place() as p:
            placed = os.path.join(p.apk, windows_client.SETUP_NAME)
            with open(placed, "wb") as f:
                f.write(b"MZ cut off")
            self.assertEqual(windows_client.find(p.apk), (None, None))
            self.assertFalse(os.path.exists(placed))

    def test_the_version_comes_from_the_release_address(self):
        self.assertEqual(windows_client.release_version("https://github.com/o/r/releases/download/v0.8.0/OpenDMTQ-Setup.exe"), "0.8.0")
        self.assertEqual(windows_client.release_version("https://example.com/OpenDMTQ-Setup.exe"), "")


class KeepTest(unittest.TestCase):
    def test_the_installer_goes_beside_the_app_with_its_description(self):
        with Place() as p:
            installer(os.path.join(p.code, windows_client.SETUP_NAME), version="0.8.0")
            self.assertEqual(windows_client.keep(p.out), windows_client.SETUP_NAME)
            made = windows_client.current(p.out)
            target = os.path.join(p.out, windows_client.SETUP_NAME)
            self.assertEqual((made["file"], made["size"], made["sha256"], made["version"]),
                             (windows_client.SETUP_NAME, os.path.getsize(target), windows_client.sha256(target), "0.8.0"))
            self.assertEqual(windows_client.offered(p.out), made)

    def test_the_same_installer_is_not_copied_again(self):
        with Place() as p:
            installer(os.path.join(p.code, windows_client.SETUP_NAME), version="0.8.0")
            windows_client.keep(p.out)
            first = windows_client.current(p.out)["copied_at"]
            with mock.patch.object(windows_client.shutil, "copyfile") as copy:
                windows_client.keep(p.out)
            copy.assert_not_called()
            self.assertEqual(windows_client.current(p.out)["copied_at"], first)

    def test_a_new_installer_takes_the_old_ones_place(self):
        with Place() as p:
            beside = installer(os.path.join(p.code, windows_client.SETUP_NAME), body=b"one", version="0.8.0")
            windows_client.keep(p.out)
            installer(beside, body=b"two", version="0.8.1")
            windows_client.keep(p.out)
            with open(os.path.join(p.out, windows_client.SETUP_NAME), "rb") as f:
                self.assertEqual(f.read(5), b"MZtwo")
            self.assertEqual(windows_client.current(p.out)["version"], "0.8.1")

    def test_the_zips_from_before_the_installer_go(self):
        # 0.6 and 0.7 made a zip with the app in it for each app, each the size of the app.
        with Place() as p:
            for name in ("OpenDMTQ-a-v2026.11.07-windows.zip", "OpenDMTQ-a-v2026.11.08-windows.zip",
                         "OpenDMTQ-a-v2026.11.09-windows.zip.part"):
                with open(os.path.join(p.out, name), "wb") as f:
                    f.write(b"PK")
            installer(os.path.join(p.code, windows_client.SETUP_NAME), version="0.8.0")
            windows_client.keep(p.out)
            self.assertEqual(sorted(os.listdir(p.out)), [windows_client.SETUP_NAME, windows_client.MANIFEST])

    def test_what_0_7_kept_in_data_apk_for_its_player_goes(self):
        # The player without an app, a fetch of it cut off, and why the last fetch failed: gone, also with no installer
        # to be had; anything else in data/apk stays.
        with Place() as p:
            for name in ("opendmtq-player-windows.zip", "opendmtq-player-windows.zip.part", "player-windows-error.txt",
                         "base.apk"):
                with open(os.path.join(p.apk, name), "wb") as f:
                    f.write(b"PK")
            windows_client.keep(p.out)
            self.assertEqual(sorted(n for n in os.listdir(p.apk) if os.path.isfile(os.path.join(p.apk, n))),
                             ["base.apk", windows_client.FAILED])

    def test_none_to_be_had_offers_none(self):
        with Place() as p:
            self.assertIsNone(windows_client.keep(p.out))
            self.assertIsNone(windows_client.offered(p.out))

    def test_what_a_cut_off_run_left_goes(self):
        with Place() as p:
            for name in (windows_client.SETUP_NAME + ".part", windows_client.MANIFEST + ".part"):
                with open(os.path.join(p.out, name), "wb") as f:
                    f.write(b"half")
            windows_client.keep(p.out)
            self.assertEqual(os.listdir(p.out), [])

    def test_a_stop_while_copying_leaves_nothing_half_made(self):
        with Place() as p:
            installer(os.path.join(p.code, windows_client.SETUP_NAME), version="0.8.0")

            def stopped(src, dst):
                # Half the file written, then the builder stopped (SIGTERM as docker stop sends it).
                with open(dst, "wb") as f:
                    f.write(b"MZ half")
                raise SystemExit("stopped part-way (the builder was stopped)")
            with mock.patch.object(windows_client.shutil, "copyfile", stopped), self.assertRaises(SystemExit):
                windows_client.keep(p.out)
            self.assertEqual(os.listdir(p.out), [])

    def test_an_installer_not_there_at_its_size_is_not_offered(self):
        with Place() as p:
            installer(os.path.join(p.code, windows_client.SETUP_NAME), version="0.8.0")
            windows_client.keep(p.out)
            with open(os.path.join(p.out, windows_client.SETUP_NAME), "ab") as f:
                f.write(b"more")
            self.assertIsNone(windows_client.offered(p.out))
            os.remove(os.path.join(p.out, windows_client.SETUP_NAME))
            self.assertIsNone(windows_client.offered(p.out))


class PresetTest(unittest.TestCase):
    def test_the_end_reads_back_as_the_installer_reads_it(self):
        tail = windows_client.preset("https://example.com:8790", "example.com:8790")
        # The mark last, the length before it, and the details before that.
        self.assertEqual(tail[-16:], windows_client.MAGIC)
        length = struct.unpack("<I", tail[-20:-16])[0]
        details = json.loads(tail[-20 - length:-20].decode())
        self.assertEqual(details, {"version": 1, "url": "https://example.com:8790", "name": "example.com:8790"})
        self.assertEqual(len(tail), length + 20)

    def test_a_name_in_any_language_stays_whole(self):
        tail = windows_client.preset("http://192.168.0.10:8080", "우리 서버")
        length = struct.unpack("<I", tail[-20:-16])[0]
        self.assertEqual(json.loads(tail[-20 - length:-20].decode())["name"], "우리 서버")

    def test_over_https_the_port_is_always_named(self):
        # HTTPS answers on the game's port: an address without one is on port 80, never 443.
        self.assertEqual(windows_client.site_url(True, "example.com"), "https://example.com:80")
        self.assertEqual(windows_client.site_url(True, "example.com:8790"), "https://example.com:8790")
        self.assertEqual(windows_client.site_url(True, "example.com:443"), "https://example.com:443")
        self.assertEqual(windows_client.site_url(False, "example.com"), "http://example.com")
        self.assertEqual(windows_client.site_url(False, "192.168.0.10:8080"), "http://192.168.0.10:8080")

    def test_the_servers_own_authority_goes_with_an_https_address(self):
        tail = windows_client.preset("https://example.com:80", "example.com", CA)
        length = struct.unpack("<I", tail[-20:-16])[0]
        details = json.loads(tail[-20 - length:-20].decode())
        self.assertEqual(details, {"version": 1, "url": "https://example.com:80", "name": "example.com", "ca": CA})
        # None given: no field at all, as before.
        self.assertNotIn(b'"ca"', windows_client.preset("http://example.com", "example.com"))

    def test_the_authority_is_read_only_when_it_is_a_whole_certificate(self):
        with tempfile.TemporaryDirectory() as d:
            # None there: no HTTPS of the server's own.
            self.assertEqual(windows_client.own_ca(d), "")
            path = os.path.join(d, "ca.crt")
            for bad in (b"", b"not a certificate", CA[:40].encode(), b"-----BEGIN CERTIFICATE-----\n" + b"A" * 20000
                        + b"\n-----END CERTIFICATE-----\n"):
                with open(path, "wb") as f:
                    f.write(bad)
                self.assertEqual(windows_client.own_ca(d), "", bad[:30])
            # A whole one, as tls.py writes it (a line end after it): the text without the line end.
            with open(path, "wb") as f:
                f.write(CA.encode() + b"\n")
            self.assertEqual(windows_client.own_ca(d), CA)
            # The folder the server reads it from, unless one is given.
            with mock.patch.dict(os.environ, {"OPENDMTQ_HTTPS": d}):
                self.assertEqual(windows_client.own_ca(), CA)

    def test_the_download_name_says_the_server(self):
        self.assertEqual(windows_client.download_name("example.com:8790"), "OpenDMTQ-Setup-example.com-8790.exe")
        self.assertEqual(windows_client.download_name("192.168.0.10:8080"), "OpenDMTQ-Setup-192.168.0.10-8080.exe")


if __name__ == "__main__":
    unittest.main()
