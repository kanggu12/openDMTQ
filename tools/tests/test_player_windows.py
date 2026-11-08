"""The player for Windows beside the app: the player's zip with this server's app and player.conf added, made again when
either changes, one at a time; where the player comes from, and what a damaged copy, a failed fetch or a full disk leave."""

import errno
import io
import json
import os
import tempfile
import time
import unittest
import zipfile
import zlib
from unittest import mock

from opendmtq_tools import player_windows


def player(path, version="v1-aaaa1111"):
    """A player zip as arm32/bundle_windows.sh makes it, small."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("OpenDMTQ-Player/OpenDMTQ-Player.exe", b"MZ the player")
        z.writestr("OpenDMTQ-Player/runtime/arm32-agent", b"\x7fELF the agent")
        z.writestr("OpenDMTQ-Player/licenses/NOTICES.txt", "---- OpenDMTQ")
        z.writestr("bundle.json", json.dumps({"version": version}))
    return path


def app(out, name="OpenDMTQ-192.168.0.10-8080-v2026.11.08.apk", body=b"PK an app"):
    """An app the builder made, and its latest.json as the builder writes it."""
    with open(os.path.join(out, name), "wb") as f:
        f.write(body)
    manifest = {"file": name, "host": "192.168.0.10:8080", "sha256": player_windows.sha256(os.path.join(out, name)),
                "label": "TECHNIKA Q (192.168.0.10:8080)", "package": "com.example.app.s1234"}
    with open(os.path.join(out, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    return manifest


def damage_compressed(path):
    """Zeros over the first bytes of each file's compressed data, the zip's own records left whole: what reads it finds the
    damage in the decompressor (zlib's own error), as with a copy a disk or a download damaged."""
    with open(path, "rb") as f:
        whole = bytearray(f.read())
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
    for info in infos:
        # A file's data starts after its local header (30 bytes) and its name; these have no extra field.
        at = info.header_offset + 30 + len(info.filename)
        whole[at:at + 8] = bytes(8)
    with open(path, "wb") as f:
        f.write(whole)
    return path


def written_ago(path, days=0, hours=0):
    """A file's time set back, as if it had been written that long ago."""
    when = time.time() - days * 24 * 3600 - hours * 3600
    os.utime(path, (when, when))


class KeepTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        os.makedirs(self.out)
        self.player = player(os.path.join(self.tmp.name, player_windows.ZIP_NAME))

    def test_the_zip_holds_the_player_the_app_and_its_name(self):
        m = app(self.out)
        name = player_windows.keep(self.out, m, self.player)
        self.assertEqual(name, "OpenDMTQ-192.168.0.10-8080-v2026.11.08-windows.zip")
        with zipfile.ZipFile(os.path.join(self.out, name)) as z:
            names = set(z.namelist())
            conf = z.read("OpenDMTQ-Player/player.conf").decode()
            stored = z.getinfo("OpenDMTQ-Player/" + m["file"]).compress_type
            self.assertEqual(z.read("OpenDMTQ-Player/" + m["file"]), b"PK an app")
        # The player's files, the app beside them, and no version file: that one is the builder's.
        self.assertEqual(names, {"OpenDMTQ-Player/OpenDMTQ-Player.exe", "OpenDMTQ-Player/runtime/arm32-agent",
                                 "OpenDMTQ-Player/licenses/NOTICES.txt", "OpenDMTQ-Player/player.conf", "OpenDMTQ-Player/" + m["file"]})
        # The lines the player reads (arm32/desktop/own_folder.cpp).
        self.assertIn("name=TECHNIKA Q (192.168.0.10:8080)\n", conf)
        self.assertIn("package=com.example.app.s1234\n", conf)
        self.assertIn("apk=" + m["file"] + "\n", conf)
        # The app is compressed already.
        self.assertEqual(stored, zipfile.ZIP_STORED)
        details = player_windows.current(self.out)
        self.assertEqual((details["file"], details["apk"], details["player"]), (name, m["file"], "v1-aaaa1111"))
        self.assertEqual(details["sha256"], player_windows.sha256(os.path.join(self.out, name)))
        self.assertEqual(details["size"], os.path.getsize(os.path.join(self.out, name)))

    def test_made_once_for_the_same_app_and_player(self):
        m = app(self.out)
        name = player_windows.keep(self.out, m, self.player)
        path = os.path.join(self.out, name)
        os.utime(path, (1, 1))
        player_windows.keep(self.out, m, self.player)
        self.assertEqual(os.path.getmtime(path), 1)

    def test_made_again_for_another_player_or_app(self):
        m = app(self.out)
        name = player_windows.keep(self.out, m, self.player)
        os.utime(os.path.join(self.out, name), (1, 1))
        player(self.player, "v2-bbbb2222")
        player_windows.keep(self.out, m, self.player)
        self.assertNotEqual(os.path.getmtime(os.path.join(self.out, name)), 1)
        self.assertEqual(player_windows.current(self.out)["player"], "v2-bbbb2222")
        # A new app for another address: its own zip, and the old one goes.
        m2 = app(self.out, "OpenDMTQ-192.168.0.20-8080-v2026.11.09.apk", b"PK another app")
        name2 = player_windows.keep(self.out, m2, self.player)
        self.assertEqual(sorted(f for f in os.listdir(self.out) if f.endswith(player_windows.SUFFIX)), [name2])

    def test_nothing_without_a_player_or_an_app(self):
        m = app(self.out)
        self.assertIsNone(player_windows.keep(self.out, m, os.path.join(self.tmp.name, "none.zip")))
        self.assertIsNone(player_windows.keep(self.out, None, self.player))
        os.remove(os.path.join(self.out, m["file"]))
        self.assertIsNone(player_windows.keep(self.out, m, self.player))
        self.assertEqual([f for f in os.listdir(self.out) if f.endswith(player_windows.SUFFIX)], [])

    def test_a_damaged_player_is_none(self):
        with open(self.player, "r+b") as f:
            f.seek(40)
            f.write(b"damage")
        self.assertEqual(player_windows.bundled(self.player), (None, None))

    def test_damaged_compressed_data_is_no_player(self):
        # The zip's records whole, its data not: the decompressor's own error, which testzip() passes on, used to escape
        # bundled() and stop find() before it could fetch a whole copy.
        damage_compressed(self.player)
        with zipfile.ZipFile(self.player) as z, self.assertRaises(zlib.error):
            z.testzip()
        self.assertEqual(player_windows.bundled(self.player), (None, None))

    def test_a_full_disk_leaves_nothing_half_made(self):
        # ENOSPC while the app goes into the zip: no .part stays, a file the size of the app.
        m = app(self.out)

        # What a full disk says to a write.
        def full(*args, **kwargs):
            raise OSError(errno.ENOSPC, "No space left on device")
        with mock.patch.object(zipfile.ZipFile, "write", full), self.assertRaises(OSError):
            player_windows.keep(self.out, m, self.player)
        # The app and its manifest, and nothing else.
        self.assertEqual(sorted(os.listdir(self.out)), sorted([m["file"], "latest.json"]))
        # And while windows.json is written: the zip is in place, nothing describes it, and the next run makes both.
        with mock.patch.object(player_windows.json, "dump", full), self.assertRaises(OSError):
            player_windows.keep(self.out, m, self.player)
        self.assertEqual([f for f in os.listdir(self.out) if f.endswith(".part")], [])
        self.assertIsNone(player_windows.current(self.out))
        # The disk with room again: both made.
        name = player_windows.keep(self.out, m, self.player)
        self.assertEqual(player_windows.current(self.out)["file"], name)

    def test_what_a_cut_off_run_left_goes(self):
        # A run killed half-way (its container killed, the PC turned off): its zip and its windows.json stayed for good.
        for name in ("OpenDMTQ-192.168.0.10-8080-v2026.11.01-windows.zip.part", "windows.json.part"):
            with open(os.path.join(self.out, name), "wb") as f:
                f.write(b"half")
        # Even when there is no app to make a zip for.
        self.assertIsNone(player_windows.keep(self.out, None, self.player))
        self.assertEqual(os.listdir(self.out), [])

    def test_one_made_for_an_app_built_again_the_same_day_does_not_match(self):
        # The same address on the same day: the same file name, another app. The portal, the App page and the API go by
        # matches(), which reads the hash too.
        m = app(self.out)
        player_windows.keep(self.out, m, self.player)
        self.assertTrue(player_windows.matches(player_windows.current(self.out), m))
        m2 = app(self.out, body=b"PK the app built again")
        self.assertEqual(m2["file"], m["file"])
        self.assertFalse(player_windows.matches(player_windows.current(self.out), m2))
        # The builder makes it again, from the new app.
        player_windows.keep(self.out, m2, self.player)
        self.assertTrue(player_windows.matches(player_windows.current(self.out), m2))
        with zipfile.ZipFile(os.path.join(self.out, player_windows.current(self.out)["file"])) as z:
            self.assertEqual(z.read("OpenDMTQ-Player/" + m2["file"]), b"PK the app built again")


class FindTest(unittest.TestCase):
    """Where the player comes from: beside the code, then data/apk, then the latest release."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.apk_dir = os.path.join(self.tmp.name, "apk")
        os.makedirs(self.apk_dir)
        # No copy beside the code, as in a checkout of the source.
        patcher = mock.patch.object(player_windows, "HERE", os.path.join(self.tmp.name, "code"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_beside_the_code_first(self):
        os.makedirs(player_windows.HERE)
        player(os.path.join(player_windows.HERE, player_windows.ZIP_NAME), "v-code")
        player(os.path.join(self.apk_dir, player_windows.ZIP_NAME), "v-placed")
        self.assertEqual(player_windows.find(self.apk_dir)[1], "v-code")

    def test_then_the_one_in_data_apk(self):
        player(os.path.join(self.apk_dir, player_windows.ZIP_NAME), "v-placed")
        with mock.patch.object(player_windows, "fetch") as fetch:
            self.assertEqual(player_windows.find(self.apk_dir)[1], "v-placed")
        fetch.assert_not_called()

    def test_then_the_latest_release(self):
        def download(url, path):
            self.assertEqual(url, player_windows.RELEASE_URL)
            player(path, "v-release")
        with mock.patch.object(player_windows, "fetch", side_effect=download):
            self.assertEqual(player_windows.find(self.apk_dir)[1], "v-release")

    def test_none_without_internet(self):
        with mock.patch.object(player_windows, "fetch", side_effect=OSError("no network")):
            self.assertEqual(player_windows.find(self.apk_dir), (None, None))

    def test_a_cut_off_download_leaves_nothing(self):
        class Cut:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                raise OSError("cut off")
        target = os.path.join(self.apk_dir, player_windows.ZIP_NAME)
        with mock.patch("urllib.request.urlopen", return_value=Cut()), self.assertRaises(OSError):
            player_windows.fetch("https://example.invalid/x.zip", target)
        self.assertEqual(os.listdir(self.apk_dir), [])

    def test_a_damaged_download_replaces_nothing(self):
        # The copy there stays, and the damaged one is not left beside it.
        target = player(os.path.join(self.apk_dir, player_windows.ZIP_NAME), "v-placed")
        # The release's file as a download that damaged it brings it.
        with open(damage_compressed(player(os.path.join(self.tmp.name, "bad.zip"), "v-bad")), "rb") as f:
            body = f.read()
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body)), self.assertRaises(ValueError):
            player_windows.fetch("https://example.invalid/x.zip", target)
        self.assertEqual(player_windows.bundled(target)[1], "v-placed")
        self.assertEqual(os.listdir(self.apk_dir), [player_windows.ZIP_NAME])

    def test_a_damaged_copy_in_data_apk_goes_and_the_next_fetch_replaces_it(self):
        # A copy whose data a disk damaged: it goes even when the fetch for a whole one fails.
        placed = damage_compressed(player(os.path.join(self.apk_dir, player_windows.ZIP_NAME), "v-placed"))
        with mock.patch.object(player_windows, "fetch", side_effect=OSError("no network")):
            self.assertEqual(player_windows.find(self.apk_dir), (None, None))
        self.assertFalse(os.path.exists(placed))
        # A day later, with the release in reach.
        written_ago(os.path.join(self.apk_dir, player_windows.FAILED), hours=25)
        with mock.patch.object(player_windows, "fetch", side_effect=lambda url, path: player(path, "v-release")):
            self.assertEqual(player_windows.find(self.apk_dir), (placed, "v-release"))

    def test_after_a_failed_fetch_no_other_for_a_day(self):
        # On a network with no way out each try waits for an answer: it used to be at every start of the server.
        with mock.patch.object(player_windows, "fetch", side_effect=OSError("no network")) as fetch:
            self.assertEqual(player_windows.find(self.apk_dir), (None, None))
            self.assertEqual(player_windows.find(self.apk_dir), (None, None))
        self.assertEqual(fetch.call_count, 1)
        stamp = os.path.join(self.apk_dir, player_windows.FAILED)
        with open(stamp, encoding="utf-8") as f:
            self.assertIn("no network", f.read())
        # A day later it tries again; one that works takes the stamp away.
        written_ago(stamp, hours=25)
        with mock.patch.object(player_windows, "fetch", side_effect=lambda url, path: player(path, "v-release")) as fetch:
            self.assertEqual(player_windows.find(self.apk_dir)[1], "v-release")
        fetch.assert_called_once()
        self.assertFalse(os.path.exists(stamp))

    def test_a_copy_a_week_old_gives_way_to_the_latest_release(self):
        placed = player(os.path.join(self.apk_dir, player_windows.ZIP_NAME), "v-placed")
        # Six days old: as it is, with no fetch.
        written_ago(placed, days=6)
        with mock.patch.object(player_windows, "fetch") as fetch:
            self.assertEqual(player_windows.find(self.apk_dir), (placed, "v-placed"))
        fetch.assert_not_called()
        # Eight days: the latest release's in its place.
        written_ago(placed, days=8)
        with mock.patch.object(player_windows, "fetch", side_effect=lambda url, path: player(path, "v-release")) as fetch:
            self.assertEqual(player_windows.find(self.apk_dir), (placed, "v-release"))
        fetch.assert_called_once()

    def test_a_week_old_copy_stays_when_the_fetch_fails_and_the_next_try_is_a_day_later(self):
        # Eight days old with no release in reach (a closed network): the copy goes on being used, and one try is all a
        # day gets.
        placed = player(os.path.join(self.apk_dir, player_windows.ZIP_NAME), "v-placed")
        written_ago(placed, days=8)
        with mock.patch.object(player_windows, "fetch", side_effect=OSError("no network")) as fetch:
            self.assertEqual(player_windows.find(self.apk_dir), (placed, "v-placed"))
            self.assertEqual(player_windows.find(self.apk_dir), (placed, "v-placed"))
        self.assertEqual(fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
