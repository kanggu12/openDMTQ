"""Clear game data, Delete all and Uninstall, on folders of the test's own (removal.py)."""

import os
import stat
import subprocess
import tempfile
import types
from unittest import mock

from opendmtq_client import apps, main, removal, safety
from opendmtq_client import state as st
from tests.base import Folder

# A game's folder as the player leaves it: its libraries, its data with the id, and its log.
GAME = {
    "lib/libgame.so": b"l" * 3000,
    "data/android_id": b"0123456789abcdef",
    "data/internal/shared_prefs/game.xml": b"<map/>",
    "data/external/files/song.bin": b"s" * 5000,
    "data/cwd/.keep": b"",
    "player.log": b"started\n",
}


def write(root, files):
    """Files under a folder, with what is in them."""
    for name, data in files.items():
        path = os.path.join(root, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)


def listing(root):
    """Every file under a folder, by its name inside it."""
    found = set()
    for folder, _dirs, files in os.walk(root):
        for name in files:
            found.add(os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/"))
    return found


class Removal(Folder):
    def setUp(self):
        super().setUp()
        # The launcher's folder where an installed launcher has it: inside OpenDMTQ's folder, beside the games'.
        os.environ.pop("OPENDMTQ_CLIENT_DIR", None)
        os.environ.pop("OPENDMTQ_INSTALL_ROOT", None)
        self.root = removal.data_root()
        self.game = os.path.join(self.root, "com.example.game")
        write(self.game, GAME)
        state = st.LauncherState()
        state.add_server("http://127.0.0.1:1", "Somewhere")
        state.save()

    def tearDown(self):
        os.environ.pop("OPENDMTQ_INSTALL_ROOT", None)
        super().tearDown()

    def test_the_folders_are_the_tests_own(self):
        self.assertTrue(self.root.startswith(self.home + os.sep))
        self.assertEqual(st.config_dir(), os.path.join(self.root, "client"))
        self.assertEqual(removal.game_folders(), [self.game])

    def test_clearing_keeps_the_id_alone(self):
        everything_but_the_id = sum(len(v) for k, v in GAME.items() if k != "data/android_id")
        self.assertEqual(removal.game_data_size(), everything_but_the_id)
        self.assertEqual(removal.clear_game_data(), [])
        # The id this PC plays by, as it was, and nothing else of the game's.
        self.assertEqual(listing(self.game), {"data/android_id"})
        with open(os.path.join(self.game, "data", "android_id"), "rb") as f:
            self.assertEqual(f.read(), GAME["data/android_id"])
        self.assertEqual(removal.game_data_size(), 0)
        # The launcher's own folder is no game's.
        self.assertEqual(st.LauncherState.load().server()["name"], "Somewhere")

    def test_a_link_goes_and_what_it_points_at_stays(self):
        outside = os.path.join(self.home, "elsewhere")
        write(outside, {"keep.txt": b"mine"})
        os.symlink(outside, os.path.join(self.game, "data", "external", "linked"))
        # Counted as nothing, as what it leads to stays.
        self.assertEqual(removal.game_data_size(), sum(len(v) for k, v in GAME.items() if k != "data/android_id"))
        self.assertEqual(removal.clear_game_data(), [])
        self.assertFalse(os.path.lexists(os.path.join(self.game, "data", "external", "linked")))
        self.assertEqual(listing(outside), {"keep.txt"})

    def test_what_cannot_go_is_said_and_the_rest_goes(self):
        held = os.path.join(self.game, "data", "external", "files", "song.bin")
        real = removal._unlink

        def unlink(path):
            # Windows' answer for a file another program has open.
            if path == held:
                raise PermissionError(13, "in use", path)
            real(path)

        with mock.patch.object(removal, "_unlink", unlink):
            failed = removal.clear_game_data()
        # The file, once: not again for each folder it keeps in place.
        self.assertEqual(failed, [held])
        self.assertEqual(listing(self.game), {"data/android_id", "data/external/files/song.bin"})

    def test_delete_all_takes_every_folder_of_opendmtq(self):
        apps_folder = apps.folder("http://127.0.0.1:1")
        write(apps_folder, {"app.apk": b"a" * 100})
        self.assertGreater(removal.everything_size(), removal.game_data_size())
        self.assertEqual(removal.delete_everything(), [])
        self.assertFalse(os.path.exists(self.root))
        self.assertEqual(os.listdir(os.path.dirname(self.root)), [])

    def test_delete_all_in_a_folder_of_ones_own_choice(self):
        # OPENDMTQ_CLIENT_DIR names a folder that may hold other files: only the launcher's go.
        own = os.path.join(self.home, "chosen")
        os.environ["OPENDMTQ_CLIENT_DIR"] = own
        st.LauncherState().save()
        main._logging()
        write(own, {"notes.txt": b"the player's own"})
        self.assertEqual(removal.delete_everything(), [])
        self.assertEqual(listing(own), {"notes.txt"})
        self.assertFalse(os.path.exists(self.root))

    def test_the_launchers_files_are_its_own(self):
        # Everything the launcher wrote in its folder while it ran: the settings, the log, a server's app.
        main._logging()
        write(apps.folder("http://127.0.0.1:1"), {"app.apk": b"a", apps.CONF: b"apk=app.apk", apps.DETAILS: b"{}"})
        own = st.config_dir()
        found = {os.path.relpath(p, own) for p in removal._own_paths(own)}
        self.assertEqual(found, {st.FILE_NAME, os.path.join("logs", "launcher.log"),
                                 os.path.join("servers", "127.0.0.1-1")})
        # A file the player put there is not.
        self.assertFalse(removal._own("notes.txt"))

    def test_a_shared_folder_keeps_other_programs_files(self):
        # OPENDMTQ_CLIENT_DIR naming a folder other programs use too: their logs and folders stay.
        own = os.path.join(self.home, "shared")
        os.environ["OPENDMTQ_CLIENT_DIR"] = own
        st.LauncherState().save()
        main._logging()
        write(apps.folder("http://127.0.0.1:1"), {"app.apk": b"a", apps.CONF: b"apk=app.apk"})
        write(own, {"logs/other.log": b"theirs", "servers/other/data.bin": b"theirs"})
        self.assertEqual(removal.delete_everything(), [])
        self.assertEqual(listing(own), {"logs/other.log", "servers/other/data.bin"})

    def test_a_linked_data_folder_keeps_the_id(self):
        # The game's data moved to another disk, a link left in its place: cleared behind the link, the id kept there.
        in_place = removal.everything_size()
        elsewhere = os.path.join(self.home, "other-disk", "data")
        os.makedirs(os.path.dirname(elsewhere))
        os.rename(os.path.join(self.game, "data"), elsewhere)
        os.symlink(elsewhere, os.path.join(self.game, "data"))
        self.assertEqual(removal.game_data_size(), sum(len(v) for k, v in GAME.items() if k != "data/android_id"))
        # Delete all takes what is behind the link (below), so the size it says counts it as if it were in place.
        self.assertEqual(removal.everything_size(), in_place)
        self.assertEqual(removal.clear_game_data(), [])
        self.assertTrue(os.path.islink(os.path.join(self.game, "data")))
        self.assertEqual(listing(elsewhere), {"android_id"})
        with open(os.path.join(self.game, "data", "android_id"), "rb") as f:
            self.assertEqual(f.read(), GAME["data/android_id"])
        # Delete all takes what is behind the link too.
        self.assertEqual(removal.delete_everything(), [])
        self.assertEqual(listing(elsewhere), set())

    def test_a_junction_in_a_listing_is_a_link(self):
        # Windows lists a junction as a folder: its reparse tag alone says it leads elsewhere, so it is counted as a
        # link (nothing), never walked into. The listing's entries stood in for, as this runs on Linux too.
        class Entry:
            def __init__(self, tag):
                self.tag = tag

            def is_symlink(self):
                return False

            def stat(self, follow_symlinks=True):
                return types.SimpleNamespace(st_mode=stat.S_IFDIR, st_reparse_tag=self.tag)

        with mock.patch.object(removal.os, "name", "nt"):
            self.assertTrue(removal._entry_is_link(Entry(removal.JUNCTION)))
            self.assertFalse(removal._entry_is_link(Entry(0)))

    def test_nothing_is_written_after_delete_all(self):
        state = st.LauncherState.load()
        removal.delete_everything()
        # The window's copy, sign-ins and all, marked as the window marks it after Delete all.
        state.discarded = True
        state.save()
        self.assertFalse(os.path.exists(self.root))

    def test_no_log_comes_back_after_delete_all(self):
        main._logging()
        removal.delete_everything()
        # Velopack's uninstall hook starts the launcher once more: it writes no log where none is left.
        main._logging(make=False)
        removal.log.info("the uninstall hook")
        self.assertFalse(os.path.exists(self.root))

    def test_sizes_are_said_plainly(self):
        self.assertEqual(removal.megabytes(1), "1 KB")
        self.assertEqual(removal.megabytes(640 * 1024), "640 KB")
        self.assertEqual(removal.megabytes(85 << 20), "85 MB")
        self.assertEqual(removal.megabytes(1288490189), "1.2 GB")

    def test_a_test_never_deletes_outside_the_temporary_folder(self):
        # The accident this guards against: a test that left the real folders in place. Here the temporary folder is
        # said to be another one, which puts this test's own folders outside it.
        elsewhere = tempfile.mkdtemp(prefix="odq-other-temp-")
        try:
            with mock.patch.object(tempfile, "gettempdir", lambda: elsewhere):
                for remove in (removal.clear_game_data, removal.delete_everything):
                    with self.assertRaises(safety.DeleteRefused):
                        remove()
            # Nothing went.
            self.assertEqual(listing(self.game), set(GAME))
            self.assertEqual(st.LauncherState.load().server()["name"], "Somewhere")
        finally:
            os.rmdir(elsewhere)

    def test_the_temporary_folder_itself_is_refused(self):
        with self.assertRaises(safety.DeleteRefused):
            safety.refuse_deleting_in_tests(tempfile.gettempdir())
        safety.refuse_deleting_in_tests(self.home)


class Uninstall(Folder):
    def setUp(self):
        super().setUp()
        # An install folder as Velopack lays it out, with a stand-in Update.exe.
        self.install = os.path.join(self.home, "OpenDMTQ.Client")
        write(self.install, {"Update.exe": b"MZ", "current/sq.version": b"<version>0.8.0</version>"})
        os.environ["OPENDMTQ_INSTALL_ROOT"] = self.install

    def tearDown(self):
        os.environ.pop("OPENDMTQ_INSTALL_ROOT", None)
        super().tearDown()

    def test_velopacks_uninstaller_starts_on_its_own(self):
        with mock.patch.object(subprocess, "Popen") as popen:
            removal.uninstall()
        command, = popen.call_args[0]
        self.assertEqual(command, [os.path.join(self.install, "Update.exe"), "--uninstall", "--silent"])
        # Not from inside the folder that is going.
        cwd = popen.call_args[1]["cwd"]
        self.assertFalse(os.path.abspath(cwd).startswith(self.install))

    def test_a_copied_folder_has_no_uninstaller(self):
        os.environ.pop("OPENDMTQ_INSTALL_ROOT")
        with mock.patch.object(subprocess, "Popen") as popen:
            with self.assertRaises(removal.RemovalError) as caught:
                removal.uninstall()
        self.assertEqual(caught.exception.key, "error.uninstall.not_installed")
        popen.assert_not_called()

    def test_an_install_folder_outside_the_temporary_one_is_refused(self):
        elsewhere = tempfile.mkdtemp(prefix="odq-other-temp-")
        try:
            with mock.patch.object(tempfile, "gettempdir", lambda: elsewhere), \
                    mock.patch.object(subprocess, "Popen") as popen:
                with self.assertRaises(safety.DeleteRefused):
                    removal.uninstall()
            popen.assert_not_called()
        finally:
            os.rmdir(elsewhere)


class WindowFlow(Folder):
    """Help's Uninstall with Delete all as the window runs it, its dialogs and Velopack's uninstaller stood in for."""

    def test_closing_the_window_after_delete_all_writes_nothing(self):
        import types
        from opendmtq_client import dialogs, i18n, maintenance
        os.environ.pop("OPENDMTQ_CLIENT_DIR", None)
        state = st.LauncherState()
        state.add_server("http://127.0.0.1:1", "Somewhere")
        state.save()
        write(os.path.join(removal.data_root(), "com.example.game"), GAME)
        app = types.SimpleNamespace(words=i18n.Words("en"), state=state, files_in_use=lambda: False,
                                    set_status=lambda *a, **k: None)
        said = []

        def tell(app, kind, title, message, detail=None, ok=None):
            # The player closes the window while this dialog is up: what the window's close does.
            said.append(message)
            app.state.save()

        with mock.patch.object(dialogs, "choose", return_value="all"), mock.patch.object(dialogs, "tell", tell), \
                mock.patch.object(maintenance, "_in_background",
                                  lambda app, words, glyph, job, then: then(job(), None)), \
                mock.patch.object(removal, "uninstall", side_effect=OSError("Update.exe did not start")):
            maintenance.uninstall_program(app)
        self.assertEqual(said, [app.words("help.uninstall.failed")])
        self.assertFalse(os.path.exists(removal.data_root()))

    def test_start_over_and_forget_wait_for_a_game_from_the_command_line(self):
        # Every tool that deletes waits while a game runs, also one the command line started (app.files_in_use), which
        # the page's own busy state (PLAY, a download, this window's game) does not know of.
        from opendmtq_client import app as launcher, dialogs, i18n, maintenance, pages, playing
        state = st.LauncherState()
        state.add_server("http://127.0.0.1:1", "Somewhere")
        os.makedirs(apps.folder("http://127.0.0.1:1"))
        said = []
        app = types.SimpleNamespace(words=i18n.Words("en"), state=state, busy=False, download=None, session=None,
                                    set_status=lambda text, tone="normal", **kw: said.append(text))
        for name in ("_game_open", "busy_now", "files_in_use"):
            setattr(app, name, getattr(launcher.LauncherApp, name).__get__(app))
        with mock.patch.object(playing, "running", return_value=True), \
                mock.patch.object(dialogs, "ask", side_effect=AssertionError("asked")):
            self.assertEqual((app.busy_now(), app.files_in_use()), (False, True))
            maintenance.start_over(app)
            pages.forget_server(app, state.server(), lambda: None)
        self.assertEqual(said, [app.words("help.reset.busy"), app.words("online.busy")])
        self.assertIsNotNone(state.server("http://127.0.0.1:1"))
        self.assertTrue(os.path.isdir(apps.folder("http://127.0.0.1:1")))

    def test_clear_counts_in_the_background_then_asks_with_the_size(self):
        # The count is work in the background like the clearing (through a game's thousands of files the window would
        # stop answering), and the question after it says what it found.
        from opendmtq_client import dialogs, i18n, maintenance
        os.environ.pop("OPENDMTQ_CLIENT_DIR", None)
        game = os.path.join(removal.data_root(), "com.example.game")
        write(game, GAME)
        app = types.SimpleNamespace(words=i18n.Words("en"), state=st.LauncherState(), files_in_use=lambda: False,
                                    page="online", set_status=lambda *a, **k: None)
        jobs, asked = [], []

        def background(app, words, glyph, job, then):
            # Run at once, in order, each job named as the dialog over it would be shown.
            jobs.append(job.__name__)
            then(job(), None)

        def ask(app, kind, title, message, detail, confirm, cancel=None, glyph=None):
            asked.append(detail)
            return True

        with mock.patch.object(maintenance, "_in_background", background), mock.patch.object(dialogs, "ask", ask):
            maintenance.clear_game_data(app)
        self.assertEqual(jobs, ["game_data_size", "clear_game_data"])
        size = removal.megabytes(sum(len(v) for k, v in GAME.items() if k != "data/android_id"))
        self.assertEqual(asked, [app.words("help.clear.detail", size=size)])
        self.assertEqual(listing(game), {"data/android_id"})
