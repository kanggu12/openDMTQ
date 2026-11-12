"""Finding the game's files without asking: by what they are, not by one copy's file names."""

import os
import tempfile
import unittest
from unittest import mock

from opendmtq_cli import discover


def touch(folder, *names):
    """Empty files in folder."""
    for name in names:
        open(os.path.join(folder, name), "wb").close()


def unpacked(folder, name):
    """A folder of the client data and the song data, unpacked under this name, with the song list an old server
    kept."""
    tree = os.path.join(folder, name)
    os.makedirs(os.path.join(tree, discover.GAME_DIR))
    os.makedirs(os.path.join(tree, "_info"))
    touch(tree, os.path.join("_info", "songList.json"))
    return tree


class MatchesTest(unittest.TestCase):
    def test_the_server_files_and_any_client_beside_them(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "dmtq-files.rar", "game.apk", "photos.zip", "OpenDMTQ-10.0.0.5-v2026.11.01.apk", "OpenDMTQ-windows.zip")
            unpacked(d, "unpacked")
            # Not this server's own app, and not an archive with nothing of the game's in its name.
            self.assertEqual(discover.matches(d), ["game.apk", "dmtq-files.rar", "unpacked"])

    def test_a_client_alone_counts_only_when_named_like_the_game(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "game.apk", "some-app.apk")
            self.assertEqual(discover.matches(d), [])
            touch(d, "Technika Q.apk")
            self.assertEqual(discover.matches(d), ["Technika Q.apk"])

    def test_letter_case_does_not_matter(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "DJMAX-FILES.ZIP")
            self.assertEqual(discover.matches(d), ["DJMAX-FILES.ZIP"])

    def test_the_forms_people_have_them_in(self):
        with tempfile.TemporaryDirectory() as d:
            # A bundle, an archive in parts by its first part only, an archive of the old kind in parts.
            touch(d, "technika.xapk", "dmtq.7z.001", "dmtq.7z.002", "djmax.part1.rar", "djmax.part2.rar", "dmtq-old.rar",
                  "dmtq-old.r00")
            self.assertEqual(discover.matches(d), ["technika.xapk", "djmax.part1.rar", "dmtq-old.rar", "dmtq.7z.001"])

    def test_the_server_files_folder_without_its_song_list_or_under_another_name(self):
        with tempfile.TemporaryDirectory() as d:
            host = os.path.join(d, "only", discover.HOST)
            os.makedirs(os.path.join(host, discover.PATCH_DIR))
            www = os.path.join(d, "www")
            os.makedirs(os.path.join(www, discover.PATCH_DIR))
            os.makedirs(os.path.join(www, "DMQ"))
            content = os.path.join(d, "content")
            os.makedirs(os.path.join(content, "web", discover.PATCH_DIR))
            os.makedirs(os.path.join(content, "web", "viewImg"))
            touch(d, "game.apk")
            self.assertEqual(discover.matches(d), ["game.apk", "content", "only", "www"])
            # A patch folder of another program is not the game's.
            other = os.path.join(d, "tool")
            os.makedirs(os.path.join(other, discover.PATCH_DIR))
            self.assertFalse(discover.is_game_folder(other))

    def test_the_patch_folder_by_itself_is_the_game_data(self):
        with tempfile.TemporaryDirectory() as d:
            # phone_new in patch/, by itself, and in a folder of another name: each with a client version's tables.
            table = os.path.join("1.003.005", "android", "table", "us")
            for where in ("a/patch/phone_new", "b/phone_new", "c/files/phone_new"):
                os.makedirs(os.path.join(d, where, table))
            for chosen in ("a", "a/patch", "b/phone_new", "c/files/phone_new"):
                self.assertTrue(discover.is_game_folder(os.path.join(d, chosen)), chosen)
            # The folder of another name is not the patch folder: the phone_new in it is, one folder down.
            self.assertFalse(discover.is_game_folder(os.path.join(d, "c", "files")))
            self.assertEqual(discover.matches(os.path.join(d, "c", "files")), ["phone_new"])
            # Another program's: a name alone, or the iPhone's tables only.
            os.makedirs(os.path.join(d, "app", "phone_new", "1.0", "ios", "table"))
            os.makedirs(os.path.join(d, "app", "phone_new", "latest", "android", "table"))
            self.assertFalse(discover.is_game_folder(os.path.join(d, "app")))
            self.assertFalse(discover.is_game_folder(os.path.join(d, "app", "phone_new")))

    def test_the_songs_alone(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "songs", "DMQ", "Songs", "1"))
            touch(os.path.join(d, "songs", "DMQ", "Songs", "1"), "1.fpk")
            self.assertEqual(discover.game_folder_kind(os.path.join(d, "songs")), "songs")
            self.assertEqual(discover.game_folder_kind(os.path.join(d, "songs", "DMQ")), "songs")
            self.assertEqual(discover.matches(d), ["songs"])
            # A DMQ folder without the songs' music is not the game's.
            os.makedirs(os.path.join(d, "tool", "DMQ", "Songs"))
            self.assertIsNone(discover.game_folder_kind(os.path.join(d, "tool")))

    def test_the_whole_files_unpacked_in_downloads_are_not_taken_for_their_parts(self):
        with tempfile.TemporaryDirectory() as d:
            downloads = os.path.join(d, "Downloads")
            host = os.path.join(downloads, discover.HOST)
            os.makedirs(os.path.join(host, discover.PATCH_DIR, "1.003.005", "android", "table"))
            os.makedirs(os.path.join(host, "DMQ", "Songs", "1"))
            touch(os.path.join(host, "DMQ", "Songs", "1"), "1.fpk")
            os.makedirs(os.path.join(host, "static"))
            # Its own patch and DMQ folders are none of the forms apart: the whole folder is, from Downloads.
            self.assertEqual(discover.matches(host), [])
            with mock.patch.object(discover, "candidate_dirs", lambda: [downloads]):
                self.assertEqual(discover.find(), [(downloads, [discover.HOST])])

    def test_a_folder_that_cannot_be_read_holds_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(discover.matches(os.path.join(d, "gone")), [])


class FindTest(unittest.TestCase):
    def test_the_folder_with_the_client_and_the_server_files_comes_first(self):
        with tempfile.TemporaryDirectory() as d:
            home = os.path.join(d, "home")
            downloads = os.path.join(home, "Downloads")
            whole = os.path.join(downloads, "game")
            os.makedirs(whole)
            desktop = os.path.join(home, "Desktop")
            os.makedirs(desktop)
            # Two clients alone on the Desktop, one of each in a folder in Downloads.
            touch(desktop, "technika-1.apk", "technika-2.apk")
            touch(whole, "game.apk")
            unpacked(whole, "files")
            saved = os.environ.copy()
            os.environ.pop("SUDO_USER", None)
            os.environ["HOME"] = home
            cwd = os.getcwd()
            try:
                os.chdir(d)
                found = discover.find()
            finally:
                os.chdir(cwd)
                os.environ.clear()
                os.environ.update(saved)
            self.assertEqual(found[0], (whole, ["game.apk", "files"]))
            self.assertIn((desktop, ["technika-1.apk", "technika-2.apk"]), found)

    def test_a_folder_found_again_inside_the_one_that_lists_it_is_one_place(self):
        # Downloads with the client and a DMTQ folder, DMTQ with the game host's folder alone: DMTQ was found again,
        # one folder down, with nothing but what Downloads' import reads in it, and setup asked which of the two.
        with tempfile.TemporaryDirectory() as d:
            downloads = os.path.join(d, "Downloads")
            dmtq = os.path.join(downloads, "DMTQ")
            os.makedirs(os.path.join(dmtq, discover.HOST, discover.PATCH_DIR))
            os.makedirs(os.path.join(dmtq, discover.HOST, "DMQ"))
            touch(downloads, "game.apk")
            with mock.patch.object(discover, "candidate_dirs", lambda: [downloads]):
                self.assertEqual(discover.find(), [(downloads, ["game.apk", "DMTQ"])])
            # With a file of its own beside (an archive the import of Downloads would not open): two places still.
            touch(dmtq, "dmtq-songs.7z")
            with mock.patch.object(discover, "candidate_dirs", lambda: [downloads]):
                self.assertEqual(sorted(folder for folder, _ in discover.find()), [downloads, dmtq])

    def test_whole_server_files_come_before_the_patch_folder_alone(self):
        with tempfile.TemporaryDirectory() as d:
            # A client and the patch folder copied out in Downloads; a client and the whole files' archive on the Desktop.
            downloads = os.path.join(d, "Downloads")
            desktop = os.path.join(d, "Desktop")
            os.makedirs(os.path.join(downloads, "phone_new", "1.003.005", "android", "table"))
            os.makedirs(desktop)
            touch(downloads, "dmtq.apk")
            touch(desktop, "dmtq.apk", "DMTQ_server.rar")
            with mock.patch.object(discover, "candidate_dirs", lambda: [downloads, desktop]):
                found = discover.find()
            self.assertEqual([folder for folder, _ in found], [desktop, downloads])


if __name__ == "__main__":
    unittest.main()
