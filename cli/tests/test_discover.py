"""Finding the game's files without asking: by what they are, not by one copy's file names."""

import os
import tempfile
import unittest

from opendmtq_cli import discover


def touch(folder, *names):
    """Empty files in folder."""
    for name in names:
        open(os.path.join(folder, name), "wb").close()


def unpacked(folder, name):
    """A folder of the game's server files, unpacked under this name, with the song list an old server kept."""
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


if __name__ == "__main__":
    unittest.main()
