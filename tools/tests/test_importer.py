"""Tests for the importer: what it looks at (a whole folder, or only the files it is given), what it takes from a game
files folder (the game's data files, in two parts, and never its programs), and how it puts them in place."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from unittest import mock

from opendmtq_tools import importer


def game_folder(root, songs=(1, 2)):
    """A small tree of the client data and the song data: the client's patch folder, songs with their charts and
    jackets, the song list, and what must never come along (programs, a database, notes)."""
    files = {
        "_info/songList.json": json.dumps([{"song_id": s, "name": f"song{s}"} for s in songs]),
        "_info/dmtq.db3": "a database of someone else's players",
        "_vendor/controller/GameController.php": "<?php // someone else's program",
        "dmqglb.mb.pmang.com/DMQ/rpc.php": "<?php // someone else's program",
        "dmqglb.mb.pmang.com/DMQ/Songs.txt": "a note",
        "dmqglb.mb.pmang.com/DMQ/Patterns/Patterns.zip": "every chart again",
        "dmqglb.mb.pmang.com/patch/phone_new/1.003.005/android/patch_new.csv.lz4": "manifest",
        "dmqglb.mb.pmang.com/patch/phone_new/1.003.005/android/table/us/song_song.csv.lz4": "table",
        "dmqglb.mb.pmang.com/patch/phone_new/1.003.005/android/dlc/d3_a0.unity3d.lz4": "screen images",
        "dmqglb.mb.pmang.com/patch/phone_new/1.003.005/android/dlc/d3_e0.unity3d.lz4": "song tiles",
        "dmqglb.mb.pmang.com/patch/phone_new/1.003.005/android/preview/song1.p.opus.lz4": "preview",
        "dmqglb.mb.pmang.com/static/dmq/banner/x/howtoplay_play.png": "how to play",
        "dmqglb.mb.pmang.com/viewImg/news/phone1.png": "news",
        "dmqglb.mb.pmang.com/viewImg/eye/Song1.png": "jacket in another case",
    }
    for s in songs:
        files[f"dmqglb.mb.pmang.com/DMQ/Songs/{s}/{s}.fpk"] = "music"
        files[f"dmqglb.mb.pmang.com/DMQ/Patterns/{s}"] = "chart"
        files[f"dmqglb.mb.pmang.com/DMQ/Patterns/{s}_EARPHONE"] = "chart"
    for rel, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        with open(os.path.join(root, rel), "w") as f:
            f.write(text)


def content_files(data):
    """Every file of data/content, by its path there."""
    out = set()
    for d, _, files in os.walk(os.path.join(data, "content")):
        for f in files:
            out.add(os.path.relpath(os.path.join(d, f), os.path.join(data, "content")).replace(os.sep, "/"))
    return out


class LeftoverTest(unittest.TestCase):
    def test_what_a_killed_run_left_goes(self):
        # Gigabytes each, and nothing else ever removes them.
        with tempfile.TemporaryDirectory() as d:
            old = os.path.join(d, ".extract-abc")
            os.makedirs(os.path.join(old, "half"))
            keep = os.path.join(d, "state")
            os.makedirs(keep)
            with mock.patch.object(importer, "DATA", d):
                importer.import_game_files([], {"game"})
            self.assertFalse(os.path.exists(old))
            self.assertTrue(os.path.isdir(keep))


class PartsTest(unittest.TestCase):
    """The two parts of a game files folder, each on its own."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.src = os.path.join(tmp.name, "in")
        self.data = os.path.join(tmp.name, "data")
        game_folder(self.src)
        os.makedirs(self.data)
        for patcher in (mock.patch.object(importer, "DATA", self.data), mock.patch.object(importer, "log", lambda msg: None)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_game_data_alone_has_no_song(self):
        # The whole patch folder, every song's preview and tiles with it: the songs' files are their folder, their
        # jackets and their list.
        self.assertTrue(importer.import_game_files([self.src], {"game"}))
        self.assertEqual(content_files(self.data), {
            "web/patch/phone_new/1.003.005/android/patch_new.csv.lz4",
            "web/patch/phone_new/1.003.005/android/table/us/song_song.csv.lz4",
            "web/patch/phone_new/1.003.005/android/dlc/d3_a0.unity3d.lz4",
            "web/patch/phone_new/1.003.005/android/dlc/d3_e0.unity3d.lz4",
            "web/patch/phone_new/1.003.005/android/preview/song1.p.opus.lz4",
            "web/static/dmq/banner/x/howtoplay_play.png",
            "web/viewImg/news/phone1.png",
        })

    def test_the_songs_come_with_their_list_and_files(self):
        self.assertTrue(importer.import_game_files([self.src], {"songs"}))
        got = content_files(self.data)
        self.assertEqual(got, {
            "songs.json",
            "web/DMQ/Songs/1/1.fpk", "web/DMQ/Songs/2/2.fpk",
            "web/DMQ/Patterns/1", "web/DMQ/Patterns/1_EARPHONE", "web/DMQ/Patterns/2", "web/DMQ/Patterns/2_EARPHONE",
            # The jacket as it was, and under the name the song list gives it (Windows ignored the case).
            "web/viewImg/eye/Song1.png", "web/viewImg/eye/song1.png",
        })
        with open(os.path.join(self.data, "content", "songs.json")) as f:
            self.assertEqual([s["song_id"] for s in json.load(f)], [1, 2])

    def test_never_a_program_a_database_or_a_note(self):
        importer.import_game_files([self.src], {"game", "songs"})
        for rel in content_files(self.data):
            self.assertFalse(rel.endswith((".php", ".db3", ".txt", ".zip")), rel)

    def test_songs_imported_later_keep_the_game_data(self):
        importer.import_game_files([self.src], {"game"})
        game = content_files(self.data)
        importer.import_game_files([self.src], {"songs"})
        self.assertTrue(game <= content_files(self.data))
        self.assertIn("web/DMQ/Songs/1/1.fpk", content_files(self.data))

    def test_a_running_server_keeps_seeing_the_folder(self):
        # The server has data/content mounted: the folder itself must stay, only what is in it changes.
        importer.import_game_files([self.src], {"game"})
        content = os.path.join(self.data, "content")
        before = os.stat(content).st_ino
        importer.import_game_files([self.src], {"songs"})
        self.assertEqual(os.stat(content).st_ino, before)
        self.assertFalse(os.path.exists(os.path.join(self.data, "content.new")))

    def test_a_folder_without_game_files_is_not_taken(self):
        empty = os.path.join(self.data, "..", "empty")
        os.makedirs(empty)
        self.assertFalse(importer.import_game_files([empty], {"game", "songs"}))
        self.assertEqual(content_files(self.data), set())


@unittest.skipUnless(hasattr(os, "symlink"), "needs links")
class LinksTest(unittest.TestCase):
    """A link named like one of the game's files, or a linked folder, in the folder chosen: left out wherever it points.
    data/content is served to every phone, and a link could hand it the server's key or the owner's own files."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.src = os.path.join(tmp.name, "in")
        self.host = os.path.join(self.src, importer.HOST)
        self.data = os.path.join(tmp.name, "data")
        game_folder(self.src)
        # A file outside the folder chosen, as the server's own key is: in data/, beside the content.
        self.secret = os.path.join(self.data, "state", "download.key")
        os.makedirs(os.path.dirname(self.secret))
        with open(self.secret, "w") as f:
            f.write("the server's key")
        self.said = []
        for patcher in (mock.patch.object(importer, "DATA", self.data), mock.patch.object(importer, "log", self.said.append)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def link(self, rel, target):
        """Puts a link at rel in the game host's folder, in place of what is there."""
        path = os.path.join(self.host, rel)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        elif os.path.lexists(path):
            os.remove(path)
        os.symlink(target, path)

    def served(self):
        """What every file of data/content holds."""
        out = []
        for rel in content_files(self.data):
            with open(os.path.join(self.data, "content", rel), errors="replace") as f:
                out.append(f.read())
        return out

    def test_a_link_to_a_file_outside_the_folder_is_left_out(self):
        # A picture and a song's music named as the game names them, each a link to the key.
        self.link("static/dmq/banner/x/howtoplay_play.png", self.secret)
        self.link("DMQ/Songs/2/2.fpk", self.secret)
        self.assertTrue(importer.import_game_files([self.src], {"game", "songs"}))
        got = content_files(self.data)
        self.assertNotIn("web/static/dmq/banner/x/howtoplay_play.png", got)
        self.assertNotIn("web/DMQ/Songs/2/2.fpk", got)
        self.assertNotIn("the server's key", self.served())
        # Everything else came as it would have, and the owner is told why two files did not.
        self.assertIn("web/DMQ/Songs/1/1.fpk", got)
        self.assertIn("web/viewImg/news/phone1.png", got)
        self.assertIn("  left out 2 link(s): the game's files and folders are never links", self.said)

    def test_a_linked_folder_is_left_out_with_all_it_holds(self):
        # The owner's own pictures, in a folder outside: linked in as a folder of news pictures, and as the whole
        # folder of the pictures of HOW TO PLAY.
        outside = os.path.join(self.tmp, "photos")
        write(outside, {"phone2.png": "the owner's photo", "dmq/banner/x/howtoplay_play.png": "the owner's photo"})
        self.link("viewImg/news2", outside)
        self.link("static", outside)
        self.assertTrue(importer.import_game_files([self.src], {"game"}))
        got = content_files(self.data)
        self.assertFalse([rel for rel in got if rel.startswith(("web/viewImg/news2/", "web/static/"))], got)
        self.assertNotIn("the owner's photo", self.served())
        self.assertIn("web/viewImg/news/phone1.png", got)

    def test_a_link_inside_the_folder_is_left_out_too(self):
        # Pointing at a file of the folder itself: no game file is a link, wherever it points.
        self.link("viewImg/news/phone2.png", os.path.join(self.host, "viewImg", "news", "phone1.png"))
        importer.import_game_files([self.src], {"game"})
        self.assertNotIn("web/viewImg/news/phone2.png", content_files(self.data))

    def test_a_song_list_that_is_a_link_is_left_out(self):
        # A list of songs that is a link to a file outside: the list is made from the game's own tables instead.
        other = os.path.join(self.data, "state", "list.json")
        with open(other, "w") as f:
            json.dump([{"song_id": 1, "name": "the server's key"}], f)
        os.remove(os.path.join(self.src, "_info", "songList.json"))
        os.symlink(other, os.path.join(self.src, "_info", "songList.json"))
        self.assertTrue(importer.import_game_files([self.src], {"game", "songs"}))
        self.assertIn("  left out the song list songList.json: a link", self.said)
        with open(os.path.join(self.data, "content", "songs.json")) as f:
            self.assertNotIn("the server's key", f.read())

    def test_the_folder_chosen_may_be_a_link_itself(self):
        # The owner may reach the game's files through a link of their own: what is in it still comes.
        chosen = os.path.join(self.tmp, "chosen")
        os.symlink(self.src, chosen)
        self.assertTrue(importer.import_game_files([chosen], {"game", "songs"}))
        self.assertIn("web/DMQ/Songs/2/2.fpk", content_files(self.data))


class OnlyTest(unittest.TestCase):
    def run_main(self, only, environ=None):
        """importer.main over a folder with three downloads; returns (exit code, files it considered, parts asked)."""
        seen, asked = [], []

        def take(candidates, parts, chosen=()):
            seen.extend(candidates)
            asked.append(sorted(parts))
            return True

        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in")
            os.makedirs(src)
            for name in ("dmtq-files.rar", "game.apk", "another-game.zip"):
                open(os.path.join(src, name), "wb").close()
            with mock.patch.multiple(importer, IN=src, DATA=os.path.join(d, "data"), import_game_files=take,
                                     import_apks=lambda candidates: 0, log=lambda msg: None), \
                    mock.patch.dict(os.environ, {"IMPORT_ONLY": only, **(environ or {})}):
                with self.assertRaises(SystemExit) as e:
                    importer.main()
            return e.exception.code, sorted(os.path.relpath(p, src) for p in seen), asked

    def apks(self, kinds):
        """import_apks over loose APKs that inspect() takes for the given kinds: (how many kept, log, data/apk/base)."""
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in")
            os.makedirs(src)
            for name in kinds:
                with open(os.path.join(src, name), "w") as f:
                    f.write(name)
            infos = {name: {"kind": kind, "version": "1.3.5", "hosts": ["play.example.net"], "known": False}
                     for name, kind in kinds.items()}
            said = []
            with mock.patch.multiple(importer, DATA=os.path.join(d, "data"), log=said.append,
                                     inspect=lambda p: infos[os.path.basename(p)]):
                kept = importer.import_apks([os.path.join(src, n) for n in kinds])
            return kept, said, sorted(os.listdir(os.path.join(d, "data", "apk", "base")))

    def test_a_client_changed_for_another_server_is_kept_and_said_so(self):
        kept, said, base = self.apks({"changed.apk": "other server"})
        self.assertEqual((kept, base), (1, ["changed.apk"]))
        self.assertTrue(any("changed.apk" in line and "another server (play.example.net)" in line for line in said), said)

    def test_an_app_built_by_opendmtq_is_named_for_what_it_is(self):
        kept, said, base = self.apks({"friends-server.apk": "built here"})
        self.assertEqual((kept, base), (0, []))
        self.assertTrue(any("friends-server.apk" in line and "OpenDMTQ built" in line for line in said), said)

    def test_the_split_parts_of_a_bundle_are_left_out_without_a_word(self):
        kept, said, base = self.apks({"base.apk": "original", "config.armeabi_v7a.apk": "not the game"})
        self.assertEqual((kept, base), (1, ["base.apk"]))
        self.assertFalse(any("config." in line for line in said), said)

    def test_another_app_is_named_for_what_it_is(self):
        kept, said, _ = self.apks({"music-player.apk": "not the game"})
        self.assertEqual(kept, 0)
        self.assertTrue(any("music-player.apk" in line and "not the game's Android client" in line for line in said), said)

    def test_the_iphone_app_alone_is_named_for_what_it_is(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in")
            os.makedirs(src)
            open(os.path.join(src, "game.ipa"), "wb").close()
            said = []
            with mock.patch.multiple(importer, IN=src, DATA=os.path.join(d, "data"), import_game_files=lambda c, p, chosen=(): False,
                                     log=said.append), mock.patch.dict(os.environ, {"IMPORT_ONLY": ""}):
                with self.assertRaises(SystemExit):
                    importer.main()
            self.assertTrue(any("game.ipa" in line and "Android app (.apk) is needed" in line for line in said), said)

    def test_a_damaged_archive_does_not_keep_the_client_out(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in")
            os.makedirs(src)
            for name in ("broken.zip", "game.apk"):
                open(os.path.join(src, name), "wb").close()

            def fails(cmd, **kw):
                raise subprocess.CalledProcessError(2, cmd)

            said = []
            original = {"kind": "original", "version": "1.3.4", "hosts": [], "known": True}
            with mock.patch.multiple(importer, DATA=os.path.join(d, "data"), archive_paths=lambda p: ["inside/client.apk"],
                                     inspect=lambda p: original, sha256=lambda p: p, log=said.append), \
                    mock.patch.object(importer.subprocess, "run", fails):
                kept = importer.import_apks([os.path.join(src, "broken.zip"), os.path.join(src, "game.apk")])
            self.assertEqual(kept, 1)
            self.assertTrue(os.path.exists(os.path.join(d, "data", "apk", "base", "game.apk")))
            self.assertTrue(any("broken.zip" in line and "could not unpack" in line for line in said), said)

    def test_a_damaged_archive_gives_way_to_the_next(self):
        with tempfile.TemporaryDirectory() as d:
            data = os.path.join(d, "data")
            os.makedirs(data)
            src = os.path.join(d, "in")
            os.makedirs(src)
            # The one named like the game's comes first, and is damaged; the other holds the files too.
            paths = [os.path.join(src, n) for n in ("files.zip", "dmtq.rar")]
            for path in paths:
                open(path, "wb").close()
            tried = []

            def run(cmd, **kw):
                tried.append(os.path.basename(cmd[6]))
                if cmd[6].endswith("dmtq.rar"):
                    raise subprocess.CalledProcessError(2, cmd)
                return mock.Mock(returncode=0)

            said = []
            listing = [importer.SONG_LIST, importer.GAME_DIR + "/a"]
            with mock.patch.multiple(importer, DATA=data, IN=src, archive_paths=lambda p: listing, keep_others=lambda *a, **kw: None,
                                     collect=lambda *a, **k: {}, install_content=lambda *a: None, report=lambda *a: None,
                                     log=said.append), \
                    mock.patch.object(importer.subprocess, "run", run):
                self.assertTrue(importer.import_game_files(paths, {"game"}))
            self.assertEqual(tried, ["dmtq.rar", "files.zip"])
            self.assertTrue(any("dmtq.rar" in line and "could not unpack" in line for line in said), said)
            # Nothing left behind by the one that failed.
            self.assertEqual([n for n in os.listdir(data) if n.startswith(".extract-")], [])

    def test_a_listing_with_backslashes_is_read_as_any_other(self):
        # Windows' 7-Zip writes "Path = dmtq\\_info\\songList.json".
        listing = "Path = x.zip\nPath = dmtq\\_info\\songList.json\nPath = dmtq\\" + importer.GAME_DIR.replace("/", "\\") + "\\a\n"
        with mock.patch.object(importer.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=listing)):
            paths = importer.archive_paths("windows-listing.zip")
        self.assertEqual(importer.game_prefix(paths), "dmtq/")

    def test_several_named_files(self):
        # What setup's search matched in Downloads, and nothing else there.
        code, seen, _ = self.run_main("dmtq-files.rar/game.apk")
        self.assertEqual(code, 0)
        self.assertEqual(seen, ["dmtq-files.rar", "game.apk"])

    def test_one_named_file(self):
        code, seen, _ = self.run_main("game.apk")
        self.assertEqual((code, seen), (0, ["game.apk"]))

    def test_the_songs_only_when_asked(self):
        self.assertEqual(self.run_main("game.apk")[2], [["game"]])
        self.assertEqual(self.run_main("game.apk", {"IMPORT_SONGS": "yes"})[2], [["game", "songs"]])
        self.assertEqual(self.run_main("game.apk", {"IMPORT_SONGS": "yes", "IMPORT_GAME": "no"})[2], [["songs"]])


def tables(host, songs, charts):
    """The client's song tables in a game host's folder, as plain CSV: songs [(id, name)], charts [(pattern id, song id)]."""
    table = os.path.join(host, "patch/phone_new/1.003.005/android/table/us")
    os.makedirs(table, exist_ok=True)
    with open(os.path.join(table, "song_song.csv"), "w", encoding="utf-8") as f:
        f.write(",".join(importer.SONG_FIELDS) + "\n")
        for sid, name in songs:
            row = {k: "" for k in importer.SONG_FIELDS}
            row.update(song_id=str(sid), name=name, full_name=name.title(), cost_game_point="100", flag="0")
            f.write(",".join(row[k] for k in importer.SONG_FIELDS) + "\n")
    with open(os.path.join(table, "song_songPattern.csv"), "w", encoding="utf-8") as f:
        f.write("pattern_id,song_id,line,difficulty,signature\n")
        for pid, sid in charts:
            f.write(f"{pid},{sid},4,1,2\n")


def write(root, files):
    """Files under root: {path: text}."""
    for rel, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        with open(os.path.join(root, rel), "w") as f:
            f.write(text)


class FormsTest(unittest.TestCase):
    """The client data and the song data in the forms people have them: without the old server's song list, in a folder
    of another name, as an OpenDMTQ server's content."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.data = os.path.join(tmp.name, "data")
        os.makedirs(self.data)
        self.said = []
        for patcher in (mock.patch.object(importer, "DATA", self.data), mock.patch.object(importer, "log", self.said.append)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def songs(self):
        with open(os.path.join(self.data, "content", "songs.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_without_a_song_list_it_is_made_from_the_game_tables_for_the_songs_there(self):
        host = os.path.join(self.tmp, "in", importer.HOST)
        # Three songs in the tables, two with their music here; of the first's charts one has its file.
        tables(host, [(1, "first"), (2, "second"), (3, "third")], [(11, 1), (12, 1), (21, 2)])
        write(host, {"DMQ/Songs/1/1.fpk": "m", "DMQ/Songs/2/2.fpk": "m", "DMQ/Patterns/11": "c", "DMQ/Patterns/21": "c"})
        self.assertTrue(importer.import_game_files([os.path.join(self.tmp, "in")], {"game", "songs"}))
        got = self.songs()
        self.assertEqual([s["song_id"] for s in got], [1, 2])
        self.assertEqual(got[0]["name"], "first")
        self.assertEqual(got[0]["cost_game_point"], 100)
        self.assertEqual([c["pattern_id"] for c in got[0]["song_patterns"]], [11])
        self.assertEqual(set(got[0]), set(importer.SONG_FIELDS) | {"song_patterns"})
        self.assertTrue(any("made from the game's own tables (2 songs" in line for line in self.said), self.said)

    def test_the_game_host_folder_under_another_name(self):
        www = os.path.join(self.tmp, "in", "server", "www")
        tables(www, [(1, "first")], [(11, 1)])
        write(www, {"DMQ/Songs/1/1.fpk": "m", "DMQ/Patterns/11": "c", "viewImg/news/phone1.png": "n"})
        self.assertTrue(importer.is_game_folder(www))
        self.assertTrue(importer.import_game_files([www], {"game", "songs"}))
        self.assertIn("web/viewImg/news/phone1.png", content_files(self.data))
        self.assertEqual([s["song_id"] for s in self.songs()], [1])

    def test_an_opendmtq_servers_content_with_its_song_list(self):
        content = os.path.join(self.tmp, "in", "content")
        write(content, {"web/DMQ/Songs/1/1.fpk": "m", "web/DMQ/Patterns/1": "c",
                        "web/patch/phone_new/1.003.005/android/patch_new.csv.lz4": "manifest",
                        "songs.json": json.dumps([{"song_id": 1, "name": "kept"}])})
        self.assertTrue(importer.import_game_files([content], {"game", "songs"}))
        self.assertEqual(self.songs(), [{"song_id": 1, "name": "kept"}])
        self.assertIn("web/patch/phone_new/1.003.005/android/patch_new.csv.lz4", content_files(self.data))

    def test_a_patch_folder_of_another_program_is_not_the_game(self):
        other = os.path.join(self.tmp, "in", "some-app")
        write(other, {"patch/phone_new/notes.txt": "x", "docs/readme.txt": "y"})
        self.assertFalse(importer.is_game_folder(other))
        self.assertFalse(importer.import_game_files([other], {"game", "songs"}))

    def test_inside_an_archive_the_folder_is_found_with_or_without_its_list(self):
        listing = ["pack/www/patch/phone_new/1.003.005/android/a", "pack/www/DMQ/Songs/1/1.fpk"]
        self.assertEqual(importer.tree_in(listing), ("pack/www/", None))
        self.assertEqual(importer.tree_in(listing + ["pack/_info/songList.json"]), ("pack/www/", "pack/_info/songList.json"))
        content = ["c/web/patch/phone_new/1/android/a", "c/web/viewImg/x.png", "c/songs.json"]
        self.assertEqual(importer.tree_in(content), ("c/web/", "c/songs.json"))
        self.assertIsNone(importer.tree_in(["tool/patch/phone_new/readme.txt", "tool/bin/x"]))
        # The game host's own name counts on its own, and the nearest the top wins.
        self.assertEqual(importer.tree_in([importer.GAME_DIR + "/a", "old/" + importer.GAME_DIR + "/a"])[0], importer.HOST + "/")


class GameDataAloneTest(unittest.TestCase):
    """The client's patch folder copied by itself, in each form it is copied in: the client data alone. It keeps the
    server's songs, and whole files beside it come first."""

    # What the client data of game_folder() is in its patch folder: all of that folder, every song's preview and tiles
    # with it; not the pictures of HOW TO PLAY and of the news beside it.
    GAME_DATA = {"web/patch/phone_new/1.003.005/android/patch_new.csv.lz4",
                 "web/patch/phone_new/1.003.005/android/table/us/song_song.csv.lz4",
                 "web/patch/phone_new/1.003.005/android/dlc/d3_a0.unity3d.lz4",
                 "web/patch/phone_new/1.003.005/android/dlc/d3_e0.unity3d.lz4",
                 "web/patch/phone_new/1.003.005/android/preview/song1.p.opus.lz4"}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.data = os.path.join(tmp.name, "data")
        os.makedirs(self.data)
        self.whole = os.path.join(tmp.name, "whole")
        game_folder(self.whole)
        self.said = []
        for patcher in (mock.patch.object(importer, "DATA", self.data), mock.patch.object(importer, "log", self.said.append)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def copy_patch(self, rel):
        """The whole files' patch folder (phone_new) copied to rel under the test's folder."""
        shutil.copytree(os.path.join(self.whole, importer.GAME_DIR), os.path.join(self.tmp, rel))

    def test_each_form_of_the_patch_folder_by_itself_is_the_game_data(self):
        # The folder chosen, and where its phone_new is: in patch/, the patch folder itself, phone_new itself.
        for chosen, patch in (("a", "a/patch/phone_new"), ("b/patch", "b/patch/phone_new"), ("c/phone_new", "c/phone_new")):
            with self.subTest(chosen=chosen):
                self.copy_patch(patch)
                path = os.path.join(self.tmp, chosen)
                self.assertTrue(importer.is_game_folder(path))
                self.assertEqual(importer.what_is(path), {"kind": "server files", "ok": True, "songs": 0,
                                                          "song_list": False, "apps": []})
                shutil.rmtree(os.path.join(self.data, "content"), ignore_errors=True)
                self.assertTrue(importer.import_game_files([path], {"game"}))
                self.assertEqual(content_files(self.data), self.GAME_DATA)

    def test_the_folder_chosen_counts_by_what_is_in_it(self):
        # Mounted as /in, the chosen folder's own name is gone: phone_new itself, or the patch folder around it.
        for name, rel in (("in", "in"), ("in2", "in2/phone_new")):
            with self.subTest(rel=rel):
                self.copy_patch(rel)
                chosen = os.path.join(self.tmp, name)
                self.assertEqual(importer.what_is(chosen)["kind"], "other")
                self.assertEqual(importer.what_is(chosen, chosen=True)["kind"], "server files")
                shutil.rmtree(os.path.join(self.data, "content"), ignore_errors=True)
                with mock.patch.object(importer, "IN", chosen), \
                        mock.patch.dict(os.environ, {"IMPORT_ONLY": "", "IMPORT_DATA": "", "IMPORT_CHECK": "",
                                                     "IMPORT_GAME": "yes", "IMPORT_SONGS": "no"}):
                    with self.assertRaises(SystemExit) as e:
                        importer.main()
                self.assertEqual(e.exception.code, 0)
                self.assertEqual(content_files(self.data), self.GAME_DATA)

    def test_phone_new_in_a_folder_of_another_name_is_found_below_it(self):
        # The patch folder renamed: the folder chosen is none of the game's, the phone_new in it is.
        self.copy_patch("files/client data/phone_new")
        chosen = os.path.join(self.tmp, "files")
        self.assertFalse(importer.is_game_folder(os.path.join(chosen, "client data")))
        self.assertTrue(importer.import_game_files(list(importer.walk(chosen)), {"game"}))
        self.assertEqual(content_files(self.data), self.GAME_DATA)

    def test_over_a_whole_import_it_replaces_the_patch_folder_only(self):
        # The setup asks for the songs unless told not to: files without any must not empty the song list. Nor does the
        # patch folder take the client data's other pictures (HOW TO PLAY, the news) with it.
        importer.import_game_files([self.whole], {"game", "songs"})
        before = content_files(self.data)
        self.assertIn("web/DMQ/Songs/1/1.fpk", before)
        self.assertIn("web/static/dmq/banner/x/howtoplay_play.png", before)
        self.copy_patch("only/patch/phone_new")
        # A newer patch folder: a table more, the screens' bundle gone.
        write(os.path.join(self.tmp, "only"), {"patch/phone_new/1.003.005/android/table/us/song_new.csv.lz4": "table"})
        os.remove(os.path.join(self.tmp, "only/patch/phone_new/1.003.005/android/dlc/d3_a0.unity3d.lz4"))
        self.assertTrue(importer.import_game_files([os.path.join(self.tmp, "only")], {"game", "songs"}))
        self.assertEqual(content_files(self.data),
                         before - {"web/patch/phone_new/1.003.005/android/dlc/d3_a0.unity3d.lz4"}
                         | {"web/patch/phone_new/1.003.005/android/table/us/song_new.csv.lz4"})
        self.assertIn("songs: none there, the songs on the server stay as they are", self.said)
        # Asked for the songs alone, it takes nothing at all.
        after = content_files(self.data)
        self.assertTrue(importer.import_game_files([os.path.join(self.tmp, "only")], {"songs"}))
        self.assertEqual(content_files(self.data), after)

    def test_whole_files_without_the_songs_folder_keep_the_servers_songs_too(self):
        # The host folder copied without DMQ (the songs are most of its size), its song list beside it.
        importer.import_game_files([self.whole], {"game", "songs"})
        songs = {f for f in content_files(self.data) if importer.part_of(f) == "songs"}
        lean = os.path.join(self.tmp, "lean")
        shutil.copytree(self.whole, lean, ignore=lambda d, names: ["DMQ"] if d.endswith(importer.HOST) else [])
        self.assertTrue(importer.import_game_files([lean], {"game", "songs"}))
        self.assertTrue(songs <= content_files(self.data))
        with open(os.path.join(self.data, "content", "songs.json"), encoding="utf-8") as f:
            self.assertEqual([s["song_id"] for s in json.load(f)], [1, 2])

    def test_a_song_list_with_an_empty_songs_folder_comes_in(self):
        # As the pages' stand-in files have it: the songs' folder there, empty, and the list beside the folder.
        stand_in = os.path.join(self.tmp, "stand-in")
        write(stand_in, {importer.SONG_LIST: json.dumps([{"song_id": 7, "name": "listed"}]),
                         importer.HOST + "/patch/phone_new/1.003.005/android/patch_new.csv.lz4": "manifest"})
        os.makedirs(os.path.join(stand_in, importer.HOST, "DMQ", "Songs"))
        self.assertTrue(importer.import_game_files([stand_in], {"game", "songs"}))
        with open(os.path.join(self.data, "content", "songs.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), [{"song_id": 7, "name": "listed"}])

    def test_whole_files_beside_it_come_first(self):
        # A patch folder copied out on its own, and the whole files unpacked further down.
        down = os.path.join(self.tmp, "Downloads")
        self.copy_patch("Downloads/patch/phone_new")
        game_folder(os.path.join(down, "unpacked", "server"))
        candidates = list(importer.walk(down))
        self.assertIn(os.path.join(down, "unpacked", "server"), candidates)
        self.assertTrue(importer.import_game_files(candidates, {"game", "songs"}))
        self.assertIn("web/DMQ/Songs/1/1.fpk", content_files(self.data))
        self.assertIn("web/static/dmq/banner/x/howtoplay_play.png", content_files(self.data))

    def test_a_phone_new_folder_of_another_program_is_not_the_game(self):
        # A client version's folder with its Android tables is what counts: not a name alone, not the iPhone's.
        other = os.path.join(self.tmp, "app")
        write(other, {"phone_new/1.0/android/readme.txt": "x", "patch/phone_new/2.0/ios/table/x": "y",
                      "phone_new/latest/android/table/x": "z"})
        for path in (other, os.path.join(other, "phone_new"), os.path.join(other, "patch")):
            self.assertFalse(importer.is_game_folder(path), path)

    def test_the_song_list_in_the_folder_with_the_songs(self):
        # The game host's folders copied into one of another name, the song list's folder with them.
        mine = os.path.join(self.tmp, "mine")
        shutil.copytree(os.path.join(self.whole, importer.HOST), mine)
        write(mine, {importer.SONG_LIST: json.dumps([{"song_id": 2, "name": "listed"}])})
        self.assertTrue(importer.what_is(mine)["song_list"])
        self.assertTrue(importer.import_game_files([mine], {"game", "songs"}))
        with open(os.path.join(self.data, "content", "songs.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), [{"song_id": 2, "name": "listed"}])

    def test_inside_an_archive_the_patch_folder_alone_and_the_song_list_in_the_folder(self):
        table = "1.003.005/android/table/us/song_song.csv.lz4"
        self.assertEqual(importer.tree_in(["files/patch/phone_new/" + table]), ("files/", None))
        self.assertEqual(importer.tree_in(["patch/phone_new/" + table]), ("", None))
        self.assertEqual(importer.tree_in(["phone_new/" + table, "phone_new/1.003.005/android/patch_new.csv.lz4"]),
                         ("phone_new/", None))
        self.assertEqual(importer.tree_in(["x/phone_new/" + table]), ("x/phone_new/", None))
        # Not without its own folder (the version folders at the top), nor without the Android tables.
        self.assertIsNone(importer.tree_in([table]))
        self.assertIsNone(importer.tree_in(["tool/phone_new/1.0/android/readme.txt", "tool/phone_new/2.0/ios/table/x"]))
        listing = ["pack/www/patch/phone_new/1.003.005/android/a", "pack/www/DMQ/Songs/1/1.fpk", "pack/www/_info/songList.json"]
        self.assertEqual(importer.tree_in(listing), ("pack/www/", "pack/www/_info/songList.json"))


class SongsAloneTest(unittest.TestCase):
    """The songs copied by themselves (their DMQ folder, with the jackets' viewImg and the song list or without): they
    come in on their own, onto the client data the server has, or with it from another place, and replace only what
    they have."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.data = os.path.join(tmp.name, "data")
        os.makedirs(self.data)
        self.said = []
        for patcher in (mock.patch.object(importer, "DATA", self.data), mock.patch.object(importer, "log", self.said.append)):
            patcher.start()
            self.addCleanup(patcher.stop)
        # The client data alone, with the client's song tables (two songs) and every song's preview and tiles.
        self.game = os.path.join(self.tmp, "Downloads", "game")
        tables(os.path.join(self.game), [(1, "first"), (2, "second")], [(11, 1), (12, 1), (21, 2)])
        write(self.game, {"patch/phone_new/1.003.005/android/patch_new.csv.lz4": "manifest",
                          "patch/phone_new/1.003.005/android/preview/first.p.opus.lz4": "preview",
                          "patch/phone_new/1.003.005/android/dlc/d3_e0.unity3d.lz4": "tiles"})
        # The songs alone: their folder, and their jackets.
        self.songs = os.path.join(self.tmp, "Downloads", "songs")
        write(self.songs, {"DMQ/Songs/1/1.fpk": "m", "DMQ/Songs/2/2.fpk": "m", "DMQ/Patterns/11": "c",
                           "DMQ/Patterns/21": "c", "viewImg/eye/first.png": "j", "viewImg/eye/second.png": "j"})

    def listed(self):
        with open(os.path.join(self.data, "content", "songs.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_after_the_game_data_the_songs_come_in_on_their_own(self):
        self.assertTrue(importer.import_game_files([self.game], {"game", "songs"}))
        game = content_files(self.data)
        self.assertIn("web/patch/phone_new/1.003.005/android/preview/first.p.opus.lz4", game)
        self.assertEqual(importer.what_is(self.songs)["kind"], "songs")
        self.assertTrue(importer.import_game_files([self.songs], {"game", "songs"}))
        self.assertIn("client data: none there, the client data on the server stays as it is", self.said)
        # The list from the server's own tables, for the songs and the charts whose files came.
        self.assertEqual([(s["song_id"], [c["pattern_id"] for c in s["song_patterns"]]) for s in self.listed()],
                         [(1, [11]), (2, [21])])
        self.assertEqual(content_files(self.data), game | {
            "songs.json", "web/DMQ/Songs/1/1.fpk", "web/DMQ/Songs/2/2.fpk", "web/DMQ/Patterns/11", "web/DMQ/Patterns/21",
            "web/viewImg/eye/first.png", "web/viewImg/eye/second.png"})

    def test_the_game_data_and_the_songs_from_two_places_in_one_import(self):
        downloads = os.path.join(self.tmp, "Downloads")
        self.assertTrue(importer.import_game_files(list(importer.walk(downloads)), {"game", "songs"}))
        got = content_files(self.data)
        self.assertIn("web/patch/phone_new/1.003.005/android/patch_new.csv.lz4", got)
        self.assertIn("web/DMQ/Songs/2/2.fpk", got)
        self.assertEqual([s["song_id"] for s in self.listed()], [1, 2])

    def test_the_songs_folder_itself_with_the_jackets_beside_it(self):
        importer.import_game_files([self.game], {"game"})
        self.assertTrue(importer.import_game_files([os.path.join(self.songs, "DMQ")], {"songs"}))
        self.assertIn("web/viewImg/eye/second.png", content_files(self.data))
        self.assertEqual([s["song_id"] for s in self.listed()], [1, 2])

    def test_songs_without_jackets_keep_the_servers(self):
        importer.import_game_files([self.game], {"game"})
        importer.import_game_files([self.songs], {"songs"})
        shutil.rmtree(os.path.join(self.songs, "viewImg"))
        os.remove(os.path.join(self.songs, "DMQ", "Songs", "2", "2.fpk"))
        self.assertTrue(importer.import_game_files([self.songs], {"songs"}))
        got = content_files(self.data)
        self.assertIn("web/viewImg/eye/second.png", got)
        self.assertNotIn("web/DMQ/Songs/2/2.fpk", got)
        self.assertEqual([s["song_id"] for s in self.listed()], [1])

    def test_the_folder_chosen_counts_by_what_is_in_it(self):
        # Mounted as /in, the songs' folder has lost its name.
        importer.import_game_files([self.game], {"game"})
        chosen = os.path.join(self.tmp, "in")
        shutil.copytree(os.path.join(self.songs, "DMQ"), chosen)
        self.assertEqual(importer.what_is(chosen)["kind"], "other")
        self.assertEqual(importer.what_is(chosen, chosen=True)["songs"], 2)
        self.assertTrue(importer.import_game_files(list(importer.walk(chosen)), {"songs"}, chosen=[chosen]))
        self.assertEqual([s["song_id"] for s in self.listed()], [1, 2])

    def test_without_the_game_data_the_songs_wait_for_it(self):
        # No list of their own, and no tables on the server to make one from: nothing comes in, and the import says why.
        self.assertFalse(importer.import_game_files([self.songs], {"songs"}))
        self.assertFalse(os.path.exists(os.path.join(self.data, "content", "songs.json")))
        self.assertTrue(any("import the client data first" in line for line in self.said), self.said)
        # With a list of their own they come in, and wait for the client data.
        write(self.songs, {importer.SONG_LIST: json.dumps([{"song_id": 1, "name": "first"}])})
        self.assertTrue(importer.import_game_files([self.songs], {"songs"}))
        self.assertEqual(self.listed(), [{"song_id": 1, "name": "first"}])

    def test_a_songs_folder_of_another_program_is_not_the_games(self):
        other = os.path.join(self.tmp, "tool")
        write(other, {"DMQ/readme.txt": "x", "DMQ/Songs/notes.txt": "y"})
        self.assertEqual(importer.what_is(other)["kind"], "other")
        self.assertFalse(importer.import_game_files([other], {"songs"}))

    def test_the_patch_folder_alone_with_pictures_beside_it_replaces_the_patch_folder_only(self):
        # A copy of the game host's folder without DMQ and viewImg: the patch folder alone, with HOW TO PLAY's pictures.
        whole = os.path.join(self.tmp, "whole")
        game_folder(whole)
        importer.import_game_files([whole], {"game", "songs"})
        live = os.path.join(self.data, "content", "web", "static", "dmq", "banner", "x", "howtoplay_play.png")
        before = os.stat(live).st_ino
        lean = os.path.join(self.tmp, "lean")
        shutil.copytree(os.path.join(whole, importer.HOST, "patch"), os.path.join(lean, "patch"))
        write(lean, {"static/dmq/banner/x/howtoplay_play.png": "another picture"})
        self.assertTrue(importer.import_game_files([lean], {"game"}))
        # The server's own picture stays, and the import wrote nothing through to it.
        with open(live) as f:
            self.assertEqual(f.read(), "how to play")
        self.assertEqual(os.stat(live).st_ino, before)

    def test_in_an_archive_listing(self):
        listing = ["pack/DMQ/Songs/1/1.fpk", "pack/DMQ/Patterns/11", "pack/viewImg/eye/first.png", "pack/_info/songList.json"]
        self.assertEqual(importer.songs_tree_in(listing), ("pack/", "pack/_info/songList.json"))
        self.assertEqual(importer.songs_tree_in(["DMQ/Songs/1/1.fpk"]), ("", None))
        self.assertIsNone(importer.songs_tree_in(["DMQ/Songs/1/2.fpk", "DMQ/readme.txt"]))
        # The whole files are the whole files, with their songs.
        self.assertIsNone(importer.patch_alone_in(listing))


class CheckTest(unittest.TestCase):
    """import --check: what each file is, and nothing imported."""

    def test_the_songs_alone_are_said_for_what_they_are(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in")
            write(src, {"songs/DMQ/Songs/1/1.fpk": "m", "songs/DMQ/Songs/2/2.fpk": "m"})
            said = []
            with mock.patch.multiple(importer, IN=src, DATA=d, log=said.append), \
                    mock.patch.dict(os.environ, {"IMPORT_ONLY": "", "IMPORT_CHECK": "yes"}):
                with self.assertRaises(SystemExit):
                    importer.main()
            self.assertEqual(said, ["ok   songs: the song data alone, 2 songs, for the client data imported apart, "
                                    "no song list (made from the game's own tables)"])

    def test_the_game_data_alone_is_said_once_for_what_it_is(self):
        with tempfile.TemporaryDirectory() as d:
            whole = os.path.join(d, "whole")
            game_folder(whole)
            src = os.path.join(d, "in")
            # The folder chosen holds a folder that holds the patch folder: one thing, said once.
            shutil.copytree(os.path.join(whole, importer.GAME_DIR), os.path.join(src, "client", "patch", "phone_new"))
            said = []
            with mock.patch.multiple(importer, IN=src, DATA=d, log=said.append), \
                    mock.patch.dict(os.environ, {"IMPORT_ONLY": "", "IMPORT_CHECK": "yes"}):
                with self.assertRaises(SystemExit) as e:
                    importer.main()
            self.assertEqual(e.exception.code, 0)
            self.assertEqual(said, ["ok   client: the client data without song data: the game starts, with nothing to play yet"])

    def test_each_file_is_said_for_what_it_is_and_nothing_comes_in(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in")
            data = os.path.join(d, "data")
            os.makedirs(data)
            game_folder(os.path.join(src, "files"))
            write(src, {"game.apk": "a", "changed.apk": "b", "game.ipa": "c", "parts.7z.002": "d", "notes.txt": "e"})
            infos = {"game.apk": {"kind": "original", "version": "1.3.4", "hosts": [], "known": True},
                     "changed.apk": {"kind": "other server", "version": "1.3.5", "hosts": ["play.example.net"], "known": False}}
            said = []
            with mock.patch.multiple(importer, IN=src, DATA=data, log=said.append, inspect=lambda p: infos[os.path.basename(p)]), \
                    mock.patch.dict(os.environ, {"IMPORT_ONLY": "", "IMPORT_CHECK": "yes"}):
                with self.assertRaises(SystemExit) as e:
                    importer.main()
            self.assertEqual(e.exception.code, 0)
            text = "\n".join(said)
            self.assertIn("ok   files: the client data and the song data, 2 songs", text)
            self.assertIn("ok   game.apk: client 1.3.4, original", text)
            self.assertIn("ok   changed.apk: client 1.3.5, changed for another server (play.example.net)", text)
            self.assertIn("no   game.ipa: the iPhone app", text)
            self.assertIn("parts.7z.002: a part of an archive in parts", text)
            self.assertNotIn("notes.txt", text)
            # Nothing imported.
            self.assertEqual(os.listdir(data), [])


class ArchiveRoleTest(unittest.TestCase):
    def test_whole_archives_and_first_parts_are_opened_later_parts_are_not(self):
        first = ["a.zip", "a.7z", "a.RAR", "a.7z.001", "a.zip.001", "a.part1.rar", "a.part01.rar", "a.xapk", "a.apks"]
        part = ["a.7z.002", "a.part2.rar", "a.part02.rar", "a.r00", "a.z01"]
        for name in first:
            self.assertEqual(importer.archive_role(name), "first", name)
        for name in part:
            self.assertEqual(importer.archive_role(name), "part", name)
        for name in ("a.apk", "a.ipa", "a.txt", "a.001"):
            self.assertIsNone(importer.archive_role(name), name)


@unittest.skipUnless(shutil.which(importer.SEVENZIP), "needs 7-Zip (the tools image has it)")
class ArchiveFormsTest(unittest.TestCase):
    """Real archives, made with the same 7-Zip: one in parts, one inside another, an APK bundle."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.data = os.path.join(tmp.name, "data")
        self.src = os.path.join(tmp.name, "in")
        os.makedirs(self.data)
        os.makedirs(self.src)
        importer._listed.clear()
        for patcher in (mock.patch.object(importer, "DATA", self.data), mock.patch.object(importer, "log", lambda msg: None)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def pack(self, archive, folder, *extra):
        """An archive of folder's contents (7-Zip's own command line, as a user's 7-Zip makes them)."""
        subprocess.run([importer.SEVENZIP, "a", "-bso0", "-bsp0", *extra, archive, "."], cwd=folder, check=True)

    def files(self):
        tree = os.path.join(self.tmp, "tree")
        game_folder(tree)
        # Something big enough to split, that does not pack small.
        with open(os.path.join(tree, importer.HOST, "DMQ/Songs/1/1.fpk"), "wb") as f:
            f.write(os.urandom(300_000))
        return tree

    def test_an_archive_in_parts_through_its_first_part(self):
        self.pack(os.path.join(self.src, "dmtq.7z"), self.files(), "-v100k")
        names = sorted(os.listdir(self.src))
        self.assertGreater(len(names), 2, names)
        self.assertEqual([importer.archive_role(n) for n in names], ["first"] + ["part"] * (len(names) - 1))
        self.assertTrue(importer.import_game_files([os.path.join(self.src, n) for n in names], {"game", "songs"}))
        self.assertIn("web/DMQ/Songs/1/1.fpk", content_files(self.data))

    def test_an_archive_in_parts_with_one_missing_is_said_and_skipped(self):
        self.pack(os.path.join(self.src, "dmtq.7z"), self.files(), "-v100k")
        os.remove(os.path.join(self.src, "dmtq.7z.002"))
        self.assertFalse(importer.import_game_files(sorted(os.path.join(self.src, n) for n in os.listdir(self.src)), {"game"}))
        self.assertEqual(content_files(self.data), set())

    def test_an_archive_inside_another(self):
        inner = os.path.join(self.tmp, "inner")
        os.makedirs(inner)
        self.pack(os.path.join(inner, "server-files.7z"), self.files())
        self.pack(os.path.join(self.src, "download.zip"), inner)
        self.assertTrue(importer.import_game_files([os.path.join(self.src, "download.zip")], {"game", "songs"}))
        self.assertIn("web/DMQ/Songs/2/2.fpk", content_files(self.data))
        self.assertEqual([n for n in os.listdir(self.data) if n.startswith(".extract-")], [])

    def test_the_patch_folder_alone_in_an_archive(self):
        # phone_new by itself, packed as a file manager packs a folder: with the folder at the top.
        alone = os.path.join(self.tmp, "alone")
        shutil.copytree(os.path.join(self.files(), importer.GAME_DIR), os.path.join(alone, "phone_new"))
        archive = os.path.join(self.src, "client-data.zip")
        self.pack(archive, alone, "-tzip")
        self.assertEqual(importer.what_is(archive)["songs"], 0)
        self.assertTrue(importer.import_game_files([archive], {"game", "songs"}))
        self.assertEqual(content_files(self.data), GameDataAloneTest.GAME_DATA)

    def test_whole_files_in_an_archive_before_a_patch_folder_alone_beside_it(self):
        tree = self.files()
        self.pack(os.path.join(self.src, "dmtq.7z"), tree)
        shutil.copytree(os.path.join(tree, importer.GAME_DIR), os.path.join(self.src, "patch", "phone_new"))
        self.assertTrue(importer.import_game_files(list(importer.walk(self.src)), {"game", "songs"}))
        self.assertIn("web/DMQ/Songs/1/1.fpk", content_files(self.data))

    def test_whole_files_in_an_archive_inside_an_archive_before_a_patch_folder_alone(self):
        tree = self.files()
        inner = os.path.join(self.tmp, "inner")
        os.makedirs(inner)
        self.pack(os.path.join(inner, "server-files.7z"), tree)
        self.pack(os.path.join(self.src, "download.zip"), inner)
        shutil.copytree(os.path.join(tree, importer.GAME_DIR), os.path.join(self.src, "patch", "phone_new"))
        self.assertTrue(importer.import_game_files(list(importer.walk(self.src)), {"game", "songs"}))
        self.assertIn("web/DMQ/Songs/1/1.fpk", content_files(self.data))

    def test_the_songs_alone_in_an_archive_onto_the_game_data(self):
        tree = self.files()
        importer.import_game_files([os.path.join(tree, importer.HOST, "patch")], {"game"})
        songs = os.path.join(self.tmp, "songs")
        shutil.copytree(os.path.join(tree, importer.HOST, "DMQ"), os.path.join(songs, "DMQ"))
        shutil.copytree(os.path.join(tree, importer.HOST, "viewImg"), os.path.join(songs, "viewImg"))
        shutil.copytree(os.path.join(tree, "_info"), os.path.join(songs, "_info"))
        archive = os.path.join(self.src, "songs.zip")
        self.pack(archive, songs, "-tzip")
        self.assertEqual(importer.what_is(archive)["kind"], "songs")
        self.assertTrue(importer.import_game_files([archive], {"game", "songs"}))
        got = content_files(self.data)
        self.assertIn("web/DMQ/Songs/1/1.fpk", got)
        self.assertIn("web/viewImg/eye/Song1.png", got)
        self.assertIn("web/patch/phone_new/1.003.005/android/patch_new.csv.lz4", got)
        # The song list that came with them, in their folder.
        with open(os.path.join(self.data, "content", "songs.json"), encoding="utf-8") as f:
            self.assertEqual([s["song_id"] for s in json.load(f)], [1, 2])
        # Programs and notes in the songs' folder stay out.
        self.assertNotIn("web/DMQ/rpc.php", got)

    def test_one_archive_with_the_patch_folder_alone_and_the_songs_alone(self):
        tree = self.files()
        both = os.path.join(self.tmp, "both")
        shutil.copytree(os.path.join(tree, importer.GAME_DIR), os.path.join(both, "dmtq", "phone_new"))
        shutil.copytree(os.path.join(tree, importer.HOST, "DMQ"), os.path.join(both, "dmtq", "DMQ"))
        archive = os.path.join(self.src, "parts.zip")
        self.pack(archive, both, "-tzip")
        self.assertTrue(importer.import_game_files([archive], {"game", "songs"}))
        got = content_files(self.data)
        self.assertIn("web/patch/phone_new/1.003.005/android/patch_new.csv.lz4", got)
        self.assertIn("web/DMQ/Songs/1/1.fpk", got)

    def test_parts_inside_an_archive_in_an_archive_do_not_keep_the_parts_outside_out(self):
        # The patch folder alone outside, the songs alone in an archive inside an archive: both come in.
        tree = self.files()
        shutil.copytree(os.path.join(tree, importer.GAME_DIR), os.path.join(self.src, "phone_new"))
        songs = os.path.join(self.tmp, "songs")
        shutil.copytree(os.path.join(tree, importer.HOST, "DMQ"), os.path.join(songs, "DMQ"))
        inner = os.path.join(self.tmp, "inner")
        os.makedirs(inner)
        self.pack(os.path.join(inner, "songs.zip"), songs, "-tzip")
        self.pack(os.path.join(self.src, "dmtq-songs.zip"), inner, "-tzip")
        self.assertTrue(importer.import_game_files(list(importer.walk(self.src)), {"game", "songs"}))
        got = content_files(self.data)
        self.assertIn("web/patch/phone_new/1.003.005/android/patch_new.csv.lz4", got)

    def test_the_client_in_an_apk_bundle(self):
        bundle = os.path.join(self.tmp, "bundle")
        write(bundle, {"base.apk": "client", "config.arm64_v8a.apk": "split", "manifest.json": "{}"})
        self.pack(os.path.join(self.src, "game.xapk"), bundle, "-tzip")
        infos = {"base.apk": "original", "config.arm64_v8a.apk": "not the game"}
        with mock.patch.object(importer, "inspect",
                               lambda p: {"kind": infos[os.path.basename(p)], "version": "1.3.4", "hosts": [], "known": True}):
            self.assertEqual(importer.import_apks([os.path.join(self.src, "game.xapk")]), 1)
        self.assertEqual(os.listdir(os.path.join(self.data, "apk", "base")), ["base.apk"])

    def test_a_link_in_an_archive_is_left_out(self):
        # A zip whose picture is a link: 7-Zip restores a link that stays in the extraction (one that leaves it, it
        # refuses), and the import leaves it out whatever it points at.
        tree = self.files()
        archive = os.path.join(self.src, "dmtq.zip")
        with zipfile.ZipFile(archive, "w") as z:
            for d, _, names in os.walk(tree):
                for name in names:
                    z.write(os.path.join(d, name), os.path.relpath(os.path.join(d, name), tree))
            # The link, as a zip made on Linux or macOS stores one: the file type in the high bits, its target as the data.
            link = zipfile.ZipInfo(importer.HOST + "/static/dmq/banner/x/linked.png")
            link.create_system = 3
            link.external_attr = 0o120777 << 16
            z.writestr(link, "howtoplay_play.png")
        self.assertTrue(importer.import_game_files([archive], {"game", "songs"}))
        got = content_files(self.data)
        self.assertIn("web/static/dmq/banner/x/howtoplay_play.png", got)
        self.assertNotIn("web/static/dmq/banner/x/linked.png", got)


if __name__ == "__main__":
    unittest.main()
