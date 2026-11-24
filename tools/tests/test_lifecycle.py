"""The Server page and what it does (admin/lifecycle.py): its state on each install, restart and uninstall asked of the
server's program, the repair (repair.py), the data part by part and deleting it (server_data.py), the list of the
program's files (manifest.py), and the same through the API.

Flask is installed in the tools image only; outside it the page's tests are skipped (CI runs them there). The data, the
repair's steps and the list need only the standard library."""

import contextlib
import hashlib
import html
import importlib.util
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest import mock

from opendmtq_tools import manifest, owner, repair, server_data

HAVE_FLASK = importlib.util.find_spec("flask") is not None
if HAVE_FLASK:
    from opendmtq_tools import admin
    from tests.test_admin import Install


def write(path, data=b"x"):
    """A file with its folders."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def layout_in(root):
    """The data's layout under root, as a host install has it."""
    return server_data.Layout({"OPENDMTQ_DB": os.path.join(root, "state", "dmtq.db3"), "OPENDMTQ_APK": os.path.join(root, "apk"),
                               "OPENDMTQ_BACKUPS": os.path.join(root, "backups"), "OPENDMTQ_CUSTOM": os.path.join(root, "custom"),
                               "OPENDMTQ_LOGS": os.path.join(root, "state", "logs"),
                               "OPENDMTQ_CONTENT": os.path.join(root, "content")})


def server_with_data(root):
    """A server's data with something in every part: players and plays, an account and a token, a closed recording and one
    still being made, an added song, an app, two backups, logs, the game's files and the signing key."""
    os.makedirs(os.path.join(root, "state"), exist_ok=True)
    con = sqlite3.connect(os.path.join(root, "state", "dmtq.db3"))
    con.executescript("""CREATE TABLE Member (id INTEGER PRIMARY KEY, nickname TEXT);
        CREATE TABLE Play (user_id INTEGER, score INTEGER);
        CREATE TABLE SiteUser (name TEXT PRIMARY KEY COLLATE NOCASE, pass TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
                               admin INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL DEFAULT 0, signed_in_at INTEGER,
                               off INTEGER NOT NULL DEFAULT 0, guid INTEGER);
        CREATE TABLE ApiToken (id TEXT PRIMARY KEY, name TEXT NOT NULL, scope TEXT NOT NULL, hash TEXT NOT NULL,
                               admin TEXT NOT NULL COLLATE NOCASE, owner INTEGER NOT NULL DEFAULT 0, admin_since INTEGER,
                               created_at INTEGER NOT NULL, used_at INTEGER);
        CREATE TABLE BoardStamp (n INTEGER NOT NULL);
        INSERT INTO Member VALUES (1, 'one'), (2, 'two');
        INSERT INTO Play VALUES (1, 900000), (2, 800000);
        INSERT INTO SiteUser (name, pass) VALUES ('player1', 'x');
        INSERT INTO ApiToken (id, name, scope, hash, admin, created_at) VALUES ('000000000001', 'nightly', 'write', 'h', 'admin', 1);
        INSERT INTO BoardStamp VALUES (7);""")
    con.commit()
    con.close()
    write(os.path.join(root, "state", "live-rec", "1", "1800000000", "0.ts"), b"r" * 1000)
    write(os.path.join(root, "state", "live-rec", "2", "1800000100", ".open"), b"")
    write(os.path.join(root, "state", "live-rec", "limits.json"), b'{"cap_gb": 20}')
    write(os.path.join(root, "custom", "songs", "301", "song.json"), json.dumps({"name": "added"}).encode())
    write(os.path.join(root, "custom", "thumbs", "added.jpg"))
    write(os.path.join(root, "custom", "ids.json"), b"{}")
    write(os.path.join(root, "apk", "out", "OpenDMTQ-x.apk"), b"a" * 5000)
    write(os.path.join(root, "apk", "out", "latest.json"), b"{}")
    write(os.path.join(root, "apk", "keystore", "key.jks"), b"k")
    write(os.path.join(root, "backups", "opendmtq-20260101-000000-manual.tar.gz"), b"b" * 300)
    write(os.path.join(root, "backups", "opendmtq-20260102-000000-daily.tar.gz"), b"b" * 300)
    write(os.path.join(root, "state", "logs", "access.log"), b"GET /\n" * 50)
    write(os.path.join(root, "state", "logs", "access.log.1"), b"GET /\n" * 50)
    write(os.path.join(root, "state", "changes.log"), b'{"what": "login:ok"}\n')
    write(os.path.join(root, "content", "web", "patch", "file.csv"), b"g" * 2000)
    write(os.path.join(root, "apk", "base", "client.apk"), b"c" * 3000)


class DataTest(unittest.TestCase):
    """server_data.py: each part's size, and each part deleted as the Server page and the command lines delete it, while a
    server may run (ADM-110)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        server_with_data(self.root)
        self.layout = layout_in(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def test_every_part_is_counted(self):
        sizes = server_data.sizes(self.layout)
        self.assertEqual(list(sizes), list(server_data.PARTS))
        self.assertEqual(sizes["recordings"]["bytes"], 1000 + len(b'{"cap_gb": 20}'))
        self.assertEqual(sizes["apps"]["bytes"], 5002)
        self.assertEqual(sizes["backups"]["bytes"], 600)
        self.assertEqual(sizes["game"]["bytes"], 5000)
        self.assertTrue(all(info["can_delete"] for info in sizes.values()))

    def test_a_file_linked_twice_counts_once(self):
        # A broadcast's piece is in its stream and in its recording.
        os.link(self.path("state", "live-rec", "1", "1800000000", "0.ts"), self.path("state", "live-rec", "1", "1800000000", "1.ts"))
        self.assertEqual(server_data.sizes(self.layout)["recordings"]["bytes"], 1000 + len(b'{"cap_gb": 20}'))

    def test_the_database_loses_its_rows_and_keeps_its_tables_and_tokens(self):
        done = server_data.delete(self.layout, ["database"], say=lambda line: None)
        self.assertEqual(done, {"database": True})
        con = sqlite3.connect(self.path("state", "dmtq.db3"))
        try:
            counts = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in ("Member", "Play", "SiteUser", "ApiToken", "BoardStamp")}
        finally:
            con.close()
        self.assertEqual(counts, {"Member": 0, "Play": 0, "SiteUser": 0, "ApiToken": 1, "BoardStamp": 1})

    def test_a_recording_being_made_stays_and_so_do_the_limits(self):
        server_data.delete(self.layout, ["recordings"], say=lambda line: None)
        self.assertFalse(os.path.exists(self.path("state", "live-rec", "1")))
        self.assertTrue(os.path.exists(self.path("state", "live-rec", "2", "1800000100", ".open")))
        self.assertTrue(os.path.exists(self.path("state", "live-rec", "limits.json")))

    def test_added_songs_go_with_their_tiles_and_their_ids_stay(self):
        server_data.delete(self.layout, ["songs"], say=lambda line: None, rebuild=False)
        self.assertFalse(os.path.exists(self.path("custom", "songs")))
        self.assertFalse(os.path.exists(self.path("custom", "thumbs", "added.jpg")))
        self.assertTrue(os.path.exists(self.path("custom", "ids.json")))

    def test_apps_go_and_the_signing_key_stays(self):
        server_data.delete(self.layout, ["apps"], say=lambda line: None)
        self.assertEqual(os.listdir(self.path("apk", "out")), [])
        self.assertTrue(os.path.exists(self.path("apk", "keystore", "key.jks")))

    def test_backups_go_but_the_one_kept(self):
        server_data.delete(self.layout, ["backups"], keep=["opendmtq-20260102-000000-daily.tar.gz"], say=lambda line: None)
        self.assertEqual(os.listdir(self.path("backups")), ["opendmtq-20260102-000000-daily.tar.gz"])

    def test_logs_are_emptied_in_place_and_their_old_copies_go(self):
        server_data.delete(self.layout, ["logs"], say=lambda line: None)
        self.assertEqual(os.path.getsize(self.path("state", "logs", "access.log")), 0)
        self.assertFalse(os.path.exists(self.path("state", "logs", "access.log.1")))
        self.assertEqual(os.path.getsize(self.path("state", "changes.log")), 0)

    def test_the_game_files_go_and_their_folders_stay(self):
        server_data.delete(self.layout, ["game"], say=lambda line: None)
        self.assertEqual(os.listdir(self.path("content")), [])
        self.assertEqual(os.listdir(self.path("apk", "base")), [])

    def test_a_part_it_cannot_write_is_left_as_it_is(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root writes anywhere")
        os.chmod(self.path("content"), 0o555)
        try:
            self.assertFalse(server_data.sizes(self.layout)["game"]["can_delete"])
            self.assertEqual(server_data.delete(self.layout, ["game"], say=lambda line: None), {"game": False})
            self.assertTrue(os.path.exists(self.path("content", "web")))
        finally:
            os.chmod(self.path("content"), 0o755)

    def test_no_such_part(self):
        with self.assertRaises(ValueError):
            server_data.delete(self.layout, ["everything"])

    def test_the_backup_holds_the_database_the_key_and_the_added_songs(self):
        name = server_data.backup(self.layout)
        with tarfile.open(self.path("backups", name)) as tar:
            names = tar.getnames()
        self.assertIn("dmtq.db3", names)
        self.assertIn("keystore/key.jks", names)
        self.assertIn("custom/songs/301/song.json", names)
        if os.name == "posix":
            self.assertEqual(os.stat(self.path("backups", name)).st_mode & 0o077, 0)

    def test_the_command_backs_up_first_and_keeps_that_backup(self):
        with mock.patch.dict(os.environ, {"OPENDMTQ_DB": self.layout.db, "OPENDMTQ_APK": self.layout.apk,
                                          "OPENDMTQ_BACKUPS": self.layout.backups, "OPENDMTQ_CUSTOM": self.layout.custom,
                                          "OPENDMTQ_LOGS": self.layout.logs, "OPENDMTQ_CONTENT": self.layout.content}):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                self.assertEqual(server_data.main(["delete", "backups", "--backup"]), 0)
        made = [line.split(" ", 1)[1] for line in out.getvalue().splitlines() if line.startswith("backup ")]
        self.assertEqual(os.listdir(self.path("backups")), made)


class ManifestTest(unittest.TestCase):
    """manifest.py: the list of the program's files, what differs from it, and each one put back from the release's own
    code (SRV-45)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "OpenDMTQ")
        write(os.path.join(self.root, "opendmtq"), b"#!/usr/bin/env python3\n")
        write(os.path.join(self.root, "host", "opendmtq_host", "cli.py"), b"print('cli')\n")
        write(os.path.join(self.root, "server", "portal", "login.php"), b"<?php\n")
        # What is no program file: the settings, the data, this install's own folder, Python's caches.
        write(os.path.join(self.root, ".env"), b"ADMIN_PASSWORD=x\n")
        write(os.path.join(self.root, "data", "state", "dmtq.db3"), b"db")
        write(os.path.join(self.root, "host", "opendmtq_host", "__pycache__", "cli.cpython-312.pyc"), b"pyc")

    def tearDown(self):
        self._tmp.cleanup()

    def release(self):
        """The release's code as GitHub's archive has it: one folder on top."""
        archive = os.path.join(self._tmp.name, "release.tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            for rel in ("opendmtq", "host/opendmtq_host/cli.py", "server/portal/login.php"):
                tar.add(os.path.join(self.root, *rel.split("/")), arcname=f"openDMTQ-0.11.0/{rel}")
        return "file://" + archive

    def test_the_list_has_the_program_and_nothing_else(self):
        listed = os.path.join(self.root, ".host", "manifest.sha256")
        manifest.write(self.root, listed)
        entries = manifest.read(listed)
        self.assertEqual(sorted(entries), ["host/opendmtq_host/cli.py", "opendmtq", "server/portal/login.php"])
        self.assertEqual(entries["opendmtq"], hashlib.sha256(b"#!/usr/bin/env python3\n").hexdigest())
        self.assertEqual(manifest.find(self.root), listed)
        self.assertEqual(manifest.check(self.root, entries), ([], []))

    def test_sha256sum_lines_read_the_same(self):
        # What host/get.sh writes: sha256sum's "./path".
        listed = os.path.join(self._tmp.name, "list")
        with open(listed, "w", encoding="utf-8") as f:
            f.write(f"{hashlib.sha256(b'#!/usr/bin/env python3' + bytes([10])).hexdigest()}  ./opendmtq\n")
        self.assertEqual(list(manifest.read(listed)), ["opendmtq"])

    def test_what_is_missing_or_changed_is_found_and_put_back(self):
        url = self.release()
        listed = os.path.join(self.root, ".host", "manifest.sha256")
        manifest.write(self.root, listed)
        entries = manifest.read(listed)
        os.remove(os.path.join(self.root, "server", "portal", "login.php"))
        write(os.path.join(self.root, "host", "opendmtq_host", "cli.py"), b"broken")
        missing, changed = manifest.check(self.root, entries)
        self.assertEqual((missing, changed), (["server/portal/login.php"], ["host/opendmtq_host/cli.py"]))
        put = manifest.put_back(self.root, entries, missing + changed, url)
        self.assertEqual(sorted(put), ["host/opendmtq_host/cli.py", "server/portal/login.php"])
        self.assertEqual(manifest.check(self.root, entries), ([], []))

    def test_the_repair_puts_them_back_from_the_release_or_says_which(self):
        url = self.release()
        manifest.write(self.root, os.path.join(self.root, ".host", "manifest.sha256"))
        write(os.path.join(self.root, "host", "opendmtq_host", "cli.py"), b"broken")
        # No release to ask (no VERSION, no copy given): said by name.
        with mock.patch.dict(os.environ, {"OPENDMTQ_TARBALL": ""}):
            self.assertEqual(repair.files(self.root, ""), ("bad", "host/opendmtq_host/cli.py"))
        with mock.patch.dict(os.environ, {"OPENDMTQ_TARBALL": url}):
            self.assertEqual(repair.files(self.root, "0.11.0"), ("fixed", "host/opendmtq_host/cli.py"))
        self.assertEqual(repair.files(self.root, "0.11.0")[0], "ok")

    def test_an_install_without_a_list_is_skipped(self):
        self.assertEqual(repair.files(self.root, "0.11.0"), ("skip", ""))


class RepairStepsTest(unittest.TestCase):
    """repair.py's steps that need no admin pages: the folders, the database, the owner's sign-in, the app (SRV-46)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        server_with_data(self.root)
        self.layout = layout_in(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_folders_are_made_again(self):
        import shutil
        shutil.rmtree(os.path.join(self.root, "backups"))
        state, detail = repair.folders(self.layout)
        self.assertEqual(state, "fixed")
        self.assertIn("backups", detail)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "backups")))
        self.assertEqual(repair.folders(self.layout), ("ok", ""))

    def test_a_damaged_database_is_said(self):
        self.assertEqual(repair.database(self.layout), ("ok", ""))
        with open(self.layout.db, "r+b") as f:
            f.seek(100)
            f.write(b"\xff" * 4000)
        self.assertEqual(repair.database(self.layout)[0], "bad")

    def test_the_owner_sign_in_is_written_from_the_password(self):
        self.assertEqual(repair.owner_file(self.layout, "admin", "pw"), ("fixed", ""))
        self.assertEqual(repair.owner_file(self.layout, "admin", "pw"), ("ok", ""))
        with open(os.path.join(self.root, "state", "owner.pass"), encoding="utf-8") as f:
            name, stored = f.read().splitlines()
        self.assertEqual(name, "admin")
        self.assertTrue(owner.password_ok(stored, "pw"))
        self.assertEqual(repair.owner_file(self.layout, "admin", ""), ("skip", ""))

    def test_the_app_for_this_address_or_not(self):
        write(os.path.join(self.root, "apk", "out", "latest.json"), json.dumps({"file": "OpenDMTQ-x.apk", "host": "192.168.1.10"}).encode())
        self.assertEqual(repair.app(self.layout, "192.168.1.10"), ("ok", "OpenDMTQ-x.apk"))
        self.assertEqual(repair.app(self.layout, "192.168.1.20"), ("bad", "other_address"))
        os.remove(os.path.join(self.root, "apk", "out", "OpenDMTQ-x.apk"))
        self.assertEqual(repair.app(self.layout, "192.168.1.10"), ("bad", "missing"))
        os.remove(os.path.join(self.root, "apk", "base", "client.apk"))
        self.assertEqual(repair.app(self.layout, "192.168.1.10"), ("skip", ""))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class ServerPageTest(unittest.TestCase):
    """The Server page on each install, and what it asks of the server's program (ADM-108, ADM-109, ADM-111)."""

    def host(self, inst):
        """These pages as a host install has them: the run folder the server's program reads."""
        run = inst.path("run")
        os.makedirs(run, exist_ok=True)
        return mock.patch.multiple(admin.setup, HOST_INSTALL=True, RUN_DIR=run)

    def test_in_containers_it_says_the_commands(self):
        with Install() as inst:
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
        self.assertIn("./opendmtq down", page)
        self.assertIn("./opendmtq restart", page)
        self.assertIn("./opendmtq uninstall", page)
        self.assertNotIn('action="/opendmtq/admin/server/restart"', page)
        self.assertNotIn('action="/opendmtq/admin/server/uninstall"', page)
        # The one address, on the server's own port: never another.
        self.assertIn("http://192.168.0.10/opendmtq/admin/", page)

    def test_it_names_where_these_pages_open(self):
        # On a local network address at the address phones use; on the public port over HTTPS (--admin-public); else on
        # the server PC alone, never through a proxy, said with what opens them from elsewhere where something does.
        cases = ((("192.168.0.10:8791", "yes", False, False), "http://192.168.0.10:8791/opendmtq/admin/", None),
                 (("game.example.com:8790", "yes", False, False), "https://game.example.com:8790/opendmtq/admin/", None),
                 (("game.example.com:8790", "no", False, False), "http://localhost:8790/opendmtq/admin/",
                  "--admin-public</code> puts them on the public port over HTTPS."),
                 (("game.example.com:8790", "yes", True, False), "http://localhost:8790/opendmtq/admin/",
                  "A visit that comes through a proxy, one on this PC too, is one from elsewhere.</p>"),
                 (("game.example.com:8790", "no", False, True), "http://localhost:8000/opendmtq/admin/",
                  "to port 8000 of the api pod opens them."))
        for (host, public, host_install, kubernetes), address, words in cases:
            with Install() as inst, mock.patch.object(admin.core, "PUBLIC_HOST", host), \
                    mock.patch.dict(os.environ, {"ADMIN_ON_PUBLIC_PORT": public}), \
                    mock.patch.multiple(admin.setup, HOST_INSTALL=host_install, IN_KUBERNETES=kubernetes):
                inst.sign_in()
                page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertIn(f"<code>{address}</code>", page, host)
            if words:
                self.assertIn(words, page, host)
            else:
                self.assertNotIn('id="admin-local"', page, host)

    def test_what_the_pages_show_of_the_server_the_api_gives(self):
        # The data the pages show, not only their actions: the uninstall card's list on the Server page (as GET /server's
        # removes, item for item, on each install), and the site's download page's notice of a move to this address
        # (GET /server's moved, while the page says it: a month, to the address served now).
        with Install() as inst:
            server_with_data(inst.root)
            with admin.app.test_request_context():
                _, token = admin.tokens.make("test", "write", ("admin", True, None))
            headers = {"Authorization": f"Bearer {token}"}
            inst.sign_in()
            for host_install in (False, True):
                with mock.patch.multiple(admin.setup, HOST_INSTALL=host_install, RUN_DIR=inst.path("run")):
                    os.makedirs(inst.path("run"), exist_ok=True)
                    page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
                    listed = re.search(r'<ul class="removes">(.*?)</ul>', page, re.S)
                    removes = inst.client.get("/opendmtq/api/v1/server", headers=headers).get_json()["removes"]
                    self.assertEqual(listed.group(1).count("<li>"), len(removes), host_install)
            state = os.path.dirname(admin.core.DB)
            self.assertIsNone(inst.client.get("/opendmtq/api/v1/server", headers=headers).get_json()["moved"])
            with open(os.path.join(state, "address-moved.json"), "w", encoding="utf-8") as f:
                json.dump({"from": "192.168.0.10", "to": admin.core.PUBLIC_HOST, "at": int(time.time())}, f)
            self.assertEqual(inst.client.get("/opendmtq/api/v1/server", headers=headers).get_json()["moved"]["from"], "192.168.0.10")
            # To another address than the one served, or a month old: what the page no longer says.
            with open(os.path.join(state, "address-moved.json"), "w", encoding="utf-8") as f:
                json.dump({"from": "192.168.0.10", "to": admin.core.PUBLIC_HOST, "at": int(time.time()) - 31 * 86400}, f)
            self.assertIsNone(inst.client.get("/opendmtq/api/v1/server", headers=headers).get_json()["moved"])

    def test_on_a_host_install_it_restarts_stops_and_uninstalls(self):
        with Install() as inst, self.host(inst):
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            for action in ("restart", "stop", "uninstall", "repair", "data"):
                self.assertIn(f'action="/opendmtq/admin/server/{action}"', page, action)
            # Restart: asked of the program, and the page waits for the pages to answer again.
            with inst.client.session_transaction("/opendmtq/admin/") as s:
                token = s["csrf"]
            r = inst.client.post("/opendmtq/admin/server/restart", data={"csrf": token})
            self.assertEqual(r.status_code, 200)
            self.assertIn('id="restart-wait"', r.get_data(as_text=True))
            self.assertTrue(os.path.exists(inst.path("run/restart.request")))

    def test_an_uninstall_needs_the_word(self):
        with Install() as inst, self.host(inst):
            inst.sign_in()
            with inst.client.session_transaction("/opendmtq/admin/") as s:
                token = s["csrf"]
            r = inst.client.post("/opendmtq/admin/server/uninstall", data={"csrf": token, "confirm": "yes"})
            self.assertEqual(r.status_code, 302)
            self.assertFalse(os.path.exists(inst.path("run/uninstall.request")))
            r = inst.client.post("/opendmtq/admin/server/uninstall", data={"csrf": token, "confirm": "제거", "keep": "yes"})
            self.assertEqual(r.status_code, 200)
            self.assertIn('id="stop-wait"', r.get_data(as_text=True))
            with open(inst.path("run/uninstall.request"), encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"keep_data": True})

    def test_in_containers_restart_and_uninstall_are_not_there(self):
        with Install() as inst:
            inst.sign_in()
            with inst.client.session_transaction("/opendmtq/admin/") as s:
                token = s["csrf"]
            self.assertEqual(inst.client.post("/opendmtq/admin/server/restart", data={"csrf": token}).status_code, 404)
            self.assertEqual(inst.client.post("/opendmtq/admin/server/uninstall", data={"csrf": token, "confirm": "uninstall"}).status_code, 404)

    def test_the_stopped_page_names_the_one_address_and_follows_the_stop(self):
        with Install() as inst, self.host(inst):
            inst.sign_in()
            with inst.client.session_transaction("/opendmtq/admin/") as s:
                token = s["csrf"]
            page = inst.client.post("/opendmtq/admin/server/stop", data={"csrf": token}).get_data(as_text=True)
        self.assertIn('id="stop-wait"', page)
        self.assertIn("http://192.168.0.10/", page)
        self.assertIn('data-ping="/opendmtq/admin/setup/ping"', page)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class PortMoveTest(unittest.TestCase):
    """Moving the server to another port from the Server page and the API (API-43): .env's LISTEN_PORT and the port in
    PUBLIC_HOST, from the next start; refused in words for a port another program holds, the one it is on, no port, and
    where the command line does it (the command named)."""

    def host(self, inst):
        """A host install's pages, with its .env as a server set up on 8791 has it."""
        env_file = inst.path(".env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=pw\n")
        return mock.patch.multiple(admin.setup, HOST_INSTALL=True, RUN_DIR=inst.path("run"), ENV_FILE=env_file)

    def token(self, inst):
        """A token for the API, on a server's database (the tokens' table is in it)."""
        server_with_data(inst.root)
        with admin.app.test_request_context():
            _, token = admin.tokens.make("test", "write", ("admin", True, None))
        return {"Authorization": f"Bearer {token}"}

    def test_a_move_from_the_page_takes_effect_at_the_next_start(self):
        with Install() as inst, self.host(inst), mock.patch.object(admin.core, "PUBLIC_HOST", "192.168.0.10:8791"), \
                mock.patch.object(admin.lifecycle, "port_free", lambda port: True):
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertIn("Port 8791 carries everything", page)
            self.assertIn('action="/opendmtq/admin/server/port"', page)
            with inst.client.session_transaction("/opendmtq/admin/") as s:
                csrf = s["csrf"]
            r = inst.client.post("/opendmtq/admin/server/port", data={"csrf": csrf, "port": "8792"})
            self.assertEqual(r.status_code, 302)
            with open(inst.path(".env"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "PUBLIC_HOST=192.168.0.10:8792\nLISTEN_PORT=8792\nADMIN_PASSWORD=pw\n")
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            # Said, and kept in sight until the next start: where it will be.
            self.assertIn("From the server's next start it answers here: http://192.168.0.10:8792/", page)
            self.assertIn("From the next start: http://192.168.0.10:8792/", page)

    def test_the_card_names_the_servers_own_port_and_a_forward_to_it(self):
        # A server whose address names a router's own port (8443, forwarded to its own 8791, as the move off port 80 keeps
        # it): the card names its own port, the one the form moves, and the line under it the port the phones' app calls
        # and where it goes; where these pages open on the server PC is on its own port too; the API gives both (ADM-180;
        # main named 8443 as the server's port and localhost:8443, where nothing answers).
        with Install() as inst, self.host(inst), mock.patch.object(admin.core, "PUBLIC_HOST", "game.example.com:8443"), \
                mock.patch.dict(os.environ, {"LISTEN_PORT": "8791", "ADMIN_ON_PUBLIC_PORT": "no"}), \
                mock.patch.object(admin.lifecycle, "port_free", lambda port: port != 8791):
            # .env as the move off port 80 leaves it behind a router: the router's port in the address, its own beside it.
            with open(inst.path(".env"), "w", encoding="utf-8") as f:
                f.write("PUBLIC_HOST=game.example.com:8443\nLISTEN_PORT=8791\nADMIN_ON_PUBLIC_PORT=no\nADMIN_PASSWORD=pw\n")
            headers = self.token(inst)
            inst.sign_in()
            for lang, lead, line in (
                    ("en", "Port 8791 carries everything: the game, the players' site, these pages and the API. On another port",
                     "The phones' app calls http://game.example.com:8443/, and its port 8443 is forwarded to port 8791 of this server."),
                    ("ko", "8791번 포트 하나로 게임, 플레이어 사이트, 이 관리자 페이지, API가 모두 열립니다. 다른 포트로 옮기면",
                     "휴대폰 앱은 http://game.example.com:8443/로 접속하고, 그 8443번 포트가 이 서버의 8791번 포트로 포워딩됩니다.")):
                inst.client.set_cookie("opendmtq_lang", lang)
                page = html.unescape(inst.client.get("/opendmtq/admin/server").get_data(as_text=True))
                self.assertIn(lead, page)
                self.assertIn(f'<p class="meta" id="port-forwarded">{line}</p>', page)
                self.assertNotIn("8443 carries", page)
                self.assertNotIn("8443번 포트 하나로", page)
                self.assertIn('placeholder="8791"', page)
                self.assertIn("http://localhost:8791/opendmtq/admin/", page)
                self.assertNotIn("localhost:8443", page)
            got = inst.client.get("/opendmtq/api/v1/server", headers=headers).get_json()
            self.assertEqual((got["port"], got["public_port"], got["address"]), (8791, 8443, "http://game.example.com:8443/"))
            # The form takes the server's own port as the one it is on (main took it for another program's).
            r = inst.client.post("/opendmtq/api/v1/server/port", json={"port": 8791}, headers=headers)
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "same_port"))
        # Where the address names the server's own port: the card as it was, no line under it, both the same in the API.
        with Install() as inst, self.host(inst), mock.patch.object(admin.core, "PUBLIC_HOST", "192.168.0.10:8791"), \
                mock.patch.dict(os.environ, {"LISTEN_PORT": "8791"}):
            headers = self.token(inst)
            inst.sign_in()
            page = html.unescape(inst.client.get("/opendmtq/admin/server").get_data(as_text=True))
            self.assertIn("Port 8791 carries everything: the game, the players' site, these pages and the API. The phones' app calls it.", page)
            self.assertNotIn('id="port-forwarded"', page)
            got = inst.client.get("/opendmtq/api/v1/server", headers=headers).get_json()
            self.assertEqual((got["port"], got["public_port"]), (8791, 8791))

    def test_what_is_refused_is_said(self):
        with Install() as inst, self.host(inst), mock.patch.object(admin.core, "PUBLIC_HOST", "192.168.0.10:8791"):
            headers = self.token(inst)
            with mock.patch.object(admin.lifecycle, "port_free", lambda port: False):
                taken = inst.client.post("/opendmtq/api/v1/server/port", json={"port": 8792}, headers=headers)
            self.assertEqual((taken.status_code, taken.get_json()["error"]["code"]), (409, "port_taken"))
            self.assertIn("Port 8792 is taken on this computer by another program", taken.get_json()["error"]["message"])
            # A port below 1024 that this computer keeps from the server's user: said so, never as another program's.
            with mock.patch.object(admin.lifecycle, "port_free", lambda port: False), \
                    mock.patch.object(admin.lifecycle, "port_allowed", lambda port: False):
                kept = inst.client.post("/opendmtq/api/v1/server/port", json={"port": 80}, headers=headers)
            self.assertEqual((kept.status_code, kept.get_json()["error"]["code"]), (409, "port_not_allowed"))
            self.assertIn("keeps ports below 1024, port 80 among them", kept.get_json()["error"]["message"])
            same = inst.client.post("/opendmtq/api/v1/server/port", json={"port": 8791}, headers=headers)
            self.assertEqual(same.get_json()["error"]["code"], "same_port")
            bad = inst.client.post("/opendmtq/api/v1/server/port", json={"port": 70000}, headers=headers)
            self.assertEqual((bad.status_code, bad.get_json()["error"]["code"]), (400, "bad_port"))
            # Nothing written by any of them.
            with open(inst.path(".env"), encoding="utf-8") as f:
                self.assertIn("LISTEN_PORT=8791", f.read())
            with mock.patch.object(admin.lifecycle, "port_free", lambda port: True):
                moved = inst.client.post("/opendmtq/api/v1/server/port", json={"port": 8792}, headers=headers)
            self.assertEqual(moved.get_json(), {"port": 8792, "address": "http://192.168.0.10:8792/", "from_next_start": True})
            self.assertEqual(inst.client.get("/opendmtq/api/v1/server", headers=headers).get_json()["next_address"], "http://192.168.0.10:8792/")

    def test_a_move_off_port_80_is_said_once_and_the_owners_port_80_is_kept(self):
        # At its first start with this version a server set up on port 80 moved to 8791 (cli/opendmtq_cli/env.py): the
        # Server page says it once, the API names the port it left each time; the page's own move to port 80 is the
        # owner's choice, which the next start keeps (PORT_80=chosen).
        with Install() as inst, self.host(inst), mock.patch.object(admin.core, "PUBLIC_HOST", "192.168.0.10:8791"), \
                mock.patch.object(admin.lifecycle, "port_free", lambda port: True):
            headers = self.token(inst)
            with open(os.path.join(os.path.dirname(admin.core.DB), "port-moved.json"), "w", encoding="utf-8") as f:
                json.dump({"from": 80, "to": 8791, "address": "192.168.0.10:8791", "at": 1, "said": ["start", "status"]}, f)
            inst.sign_in()
            words = "The server moved from port 80 to 8791 at its first start with this version: http://192.168.0.10:8791/."
            self.assertIn(words, inst.client.get("/opendmtq/admin/server").get_data(as_text=True))
            self.assertNotIn(words, inst.client.get("/opendmtq/admin/server").get_data(as_text=True))
            for _ in range(2):
                self.assertEqual(inst.client.get("/opendmtq/api/v1/server", headers=headers).get_json()["moved_from"], 80)
            with inst.client.session_transaction("/opendmtq/admin/") as s:
                csrf = s["csrf"]
            inst.client.post("/opendmtq/admin/server/port", data={"csrf": csrf, "port": "80"})
            with open(inst.path(".env"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "PUBLIC_HOST=192.168.0.10\nLISTEN_PORT=80\nADMIN_PASSWORD=pw\nPORT_80=chosen\n")

    def test_a_move_off_port_80_behind_a_router_says_where_its_forward_goes(self):
        # An exposed server moved off port 80: its public port moved with its own (the router forwards the new one), or
        # it was the router's own and stays with the address (DEP-91, ADM-176); said once, in both languages.
        cases = (({"from": 80, "to": 8791, "address": "game.example.com:8791"},
                  "The server moved from port 80 to 8791 at its first start with this version: http://game.example.com:8791/. "
                  "Phones install the app again from that address, and PCs connect to it. "
                  "On the router, forward TCP 8791 to port 8791 of this PC in place of port 80.",
                  "이 버전으로 처음 시작할 때 서버가 80번 포트에서 8791번 포트로 옮겨졌습니다: http://game.example.com:8791/. "
                  "휴대폰은 이 주소에서 앱을 다시 설치하고, PC는 이 주소로 연결합니다. "
                  "공유기에서 TCP 8791번 포트를 이 PC의 80번 포트 대신 8791번 포트로 포워딩하세요."),
                 ({"from": 80, "to": 8791, "address": "game.example.com:8443"},
                  "The server moved from port 80 to 8791 at its first start with this version; its address stays "
                  "http://game.example.com:8443/. On the router, forward TCP 8443 to port 8791 of this PC in place of port 80.",
                  "이 버전으로 처음 시작할 때 서버가 80번 포트에서 8791번 포트로 옮겨졌습니다. 주소는 http://game.example.com:8443/ "
                  "그대로입니다. 공유기에서 TCP 8443번 포트를 이 PC의 80번 포트 대신 8791번 포트로 포워딩하세요."))
        for moved, english, korean in cases:
            for lang, words in (("en", english), ("ko", korean)):
                with Install() as inst, self.host(inst), mock.patch.object(admin.core, "PUBLIC_HOST", moved["address"]):
                    with open(os.path.join(os.path.dirname(admin.core.DB), "port-moved.json"), "w", encoding="utf-8") as f:
                        json.dump(dict(moved, at=1, said=["start"]), f)
                    inst.client.set_cookie("opendmtq_lang", lang)
                    inst.sign_in()
                    page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
                    shown = re.search(r'<p class="setup-state" id="moved-80"><span class="lamp ok"></span>(.*?)</p>', page, re.S)
                    self.assertIsNotNone(shown, lang)
                    self.assertEqual(shown.group(1), words)
                    self.assertNotIn('id="moved-80"', inst.client.get("/opendmtq/admin/server").get_data(as_text=True))

    def test_in_containers_the_command_line_does_it(self):
        with Install() as inst:
            r = inst.client.post("/opendmtq/api/v1/server/port", json={"port": 8792}, headers=self.token(inst))
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "by_command"))
            self.assertIn("./opendmtq port <port>", r.get_json()["error"]["message"])
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertIn("./opendmtq port &lt;port&gt;", page)
            self.assertNotIn('action="/opendmtq/admin/server/port"', page)

    def test_on_kubernetes_the_command_moves_the_service_with_the_address(self):
        # The release's own values stay under --reuse-values, a router.service.port 80 of a values file from before 0.11.0
        # among them: the command names the Service's port with the address's, or the Service's alone where the address
        # names a port forwarded to it (DEP-110; main's set publicHost alone, and the Service went back to 80). The page,
        # GET /server's commands and the setup's change of address say the same.
        own = "helm upgrade opendmtq <chart> -n games --reuse-values --set publicHost=game.example.com:<port> --set router.service.port=<port>"
        alone = "helm upgrade opendmtq <chart> -n games --reuse-values --set router.service.port=<port>"
        for public, listen, command in (("game.example.com:8791", "8791", own), ("game.example.com:8443", "8791", alone)):
            with Install() as inst, mock.patch.object(admin.setup, "IN_KUBERNETES", True), \
                    mock.patch.object(admin.core, "PUBLIC_HOST", public), \
                    mock.patch.dict(os.environ, {"LISTEN_PORT": listen, "POD_NAMESPACE": "games"}):
                headers = self.token(inst)
                inst.sign_in()
                page = html.unescape(inst.client.get("/opendmtq/admin/server").get_data(as_text=True))
                self.assertIn(f'<pre class="log cmd">{command}</pre>', page, public)
                self.assertEqual(inst.client.get("/opendmtq/api/v1/server", headers=headers).get_json()["commands"]["port"],
                                 command)
                setup_page = html.unescape(inst.client.get("/opendmtq/admin/setup?step=address").get_data(as_text=True))
                self.assertIn(f"--set publicHost=<address>:{public.rsplit(':', 1)[1]} --set router.service.port={listen}</pre>",
                              setup_page, public)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class AppNameTest(unittest.TestCase):
    """The app's name (TECHNIKA Q and the server's name) from the Server page and the API (ADM-196, API-96): SERVER_NAME in
    .env, from the next start, when the app is built again with it; refused in words for what .env or the app cannot
    take and the name it has already, and where the command line does it (the command named)."""

    def host(self, inst, env_text="PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=pw\n"):
        """A host install's pages, with its .env as a server set up on 8791 has it."""
        env_file = inst.path(".env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write(env_text)
        return mock.patch.multiple(admin.setup, HOST_INSTALL=True, RUN_DIR=inst.path("run"), ENV_FILE=env_file)

    def token(self, inst):
        """A token for the API, on a server's database (the tokens' table is in it)."""
        server_with_data(inst.root)
        with admin.app.test_request_context():
            _, token = admin.tokens.make("test", "write", ("admin", True, None))
        return {"Authorization": f"Bearer {token}"}

    def env(self, inst):
        with open(inst.path(".env"), encoding="utf-8") as f:
            return f.read()

    def test_a_new_name_from_the_page_takes_effect_at_the_next_start(self):
        with Install() as inst, self.host(inst), mock.patch.object(admin.core, "PUBLIC_HOST", "192.168.0.10:8791"), \
                mock.patch.dict(os.environ, {"SERVER_NAME": ""}):
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            # What phones show now, and the form with the address standing in for a name not given.
            self.assertIn("On phones the app is called TECHNIKA Q (192.168.0.10:8791)", page)
            self.assertIn('action="/opendmtq/admin/server/name"', page)
            self.assertIn('placeholder="192.168.0.10:8791"', page)
            with inst.client.session_transaction("/opendmtq/admin/") as s:
                csrf = s["csrf"]
            r = inst.client.post("/opendmtq/admin/server/name", data={"csrf": csrf, "name": "  Living Room "})
            self.assertEqual((r.status_code, r.headers["Location"].rsplit("/", 1)[-1]), (302, "server#name"))
            self.assertEqual(self.env(inst), "PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=pw\nSERVER_NAME=Living Room\n")
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            # Said, and kept in sight until the next start, the field holding the name to come.
            self.assertIn("Saved. The app is called TECHNIKA Q (Living Room) from the server's next start", page)
            self.assertIn("From the next start: TECHNIKA Q (Living Room)", page)
            self.assertIn('value="Living Room"', page)
            # In the log of changes, in words.
            log = admin.insights.audit_read(inst.path("state"))
            self.assertEqual((log[0]["what"], log[0]["target"]), ("server:name", "TECHNIKA Q (192.168.0.10:8791) > TECHNIKA Q (Living Room)"))
            # The server started again with it: nothing waits any more.
            with mock.patch.dict(os.environ, {"SERVER_NAME": "Living Room"}):
                page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
                self.assertIn("On phones the app is called TECHNIKA Q (Living Room)", page)
                self.assertNotIn("From the next start:", page)
                # Back to none: the address names the app again.
                inst.client.post("/opendmtq/admin/server/name", data={"csrf": csrf, "name": ""})
                self.assertIn("SERVER_NAME=\n", self.env(inst))
                self.assertIn("From the next start: TECHNIKA Q (192.168.0.10:8791)", inst.client.get("/opendmtq/admin/server").get_data(as_text=True))

    def test_what_is_refused_is_said_and_the_api_does_the_same(self):
        # A server started with the name its .env gives it.
        with Install() as inst, self.host(inst, "PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nSERVER_NAME=Den\n"), \
                mock.patch.object(admin.core, "PUBLIC_HOST", "192.168.0.10:8791"), mock.patch.dict(os.environ, {"SERVER_NAME": "Den"}):
            headers = self.token(inst)
            for name in ('My "server"', "a$b", "x#y", "back\\slash", "tick`", "x" * 81, "line\nbreak"):
                r = inst.client.post("/opendmtq/api/v1/server/name", json={"name": name}, headers=headers)
                self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (400, "bad_name" if len(name) <= 80 else "bad_field"), name)
            same = inst.client.post("/opendmtq/api/v1/server/name", json={"name": "Den"}, headers=headers)
            self.assertEqual((same.status_code, same.get_json()["error"]["code"]), (409, "same_name"))
            self.assertIn("The app is called TECHNIKA Q (Den) already.", same.get_json()["error"]["message"])
            # Nothing written by any of them.
            self.assertEqual(self.env(inst), "PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nSERVER_NAME=Den\n")
            renamed = inst.client.post("/opendmtq/api/v1/server/name", json={"name": "거실 서버"}, headers=headers)
            self.assertEqual(renamed.get_json(), {"name": "거실 서버", "app_name": "TECHNIKA Q (거실 서버)", "from_next_start": True})
            got = inst.client.get("/opendmtq/api/v1/server", headers=headers).get_json()
            self.assertEqual((got["name"], got["app_name"], got["next_name"]), ("Den", "TECHNIKA Q (Den)", "거실 서버"))
            # The page refuses the same in its words, under the field, before anything is sent (pattern and maxlength).
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertRegex(page, r'name="name" maxlength="80" pattern="[^"]+" [^>]*data-bad="A name here is at most 80 characters')

    def test_in_containers_the_command_line_does_it(self):
        with Install() as inst:
            r = inst.client.post("/opendmtq/api/v1/server/name", json={"name": "Den"}, headers=self.token(inst))
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "by_command"))
            self.assertIn("./opendmtq name <name>", r.get_json()["error"]["message"])
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertIn("./opendmtq name &lt;name&gt;", page)
            self.assertNotIn('action="/opendmtq/admin/server/name"', page)
            with mock.patch.object(admin.setup, "IN_KUBERNETES", True):
                page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertIn("--reuse-values --set serverName=&lt;name&gt;", page)

    def test_the_app_page_leads_to_the_server_page_for_it(self):
        # The App page no longer says to edit .env: where the name comes from, and the Server page that changes it.
        with Install() as inst, self.host(inst):
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/app").get_data(as_text=True)
            self.assertIn('set on the <a href="/opendmtq/admin/server#name">Server</a> page.', page)
            self.assertNotIn("SERVER_NAME", page)
            self.assertNotIn("<code>.env</code>", page)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class WithoutTheProgramTest(unittest.TestCase):
    """A host install's pages started without its program's run folder or .env (by hand, as the pages' suite once did):
    each card says where it is done, the install's own command, never a lead with nothing after it (ADM-197)."""

    def test_each_card_names_the_installs_own_command(self):
        for kind, cli in (("host", "opendmtq"), ("windows", "OpenDMTQ.exe")):
            with Install() as inst, mock.patch.multiple(admin.setup, HOST_INSTALL=True, RUN_DIR="", ENV_FILE=""), \
                    mock.patch.object(admin.lifecycle, "install_kind", lambda kind=kind: kind):
                inst.sign_in()
                page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            for command in (f"{cli} uninstall", f"{cli} port &lt;port&gt;", f"{cli} name &lt;name&gt;", f"{cli} password"):
                self.assertIn(command, page, kind)
            # The uninstall card's list, with the command after it.
            self.assertRegex(page, r'<ul class="removes">.*?</ul>\s*<pre class="log cmd">' + re.escape(f"{cli} uninstall"), kind)
            self.assertNotIn('action="/opendmtq/admin/server/restart"', page)
            if kind == "host":
                self.assertIn("opendmtq stop\nopendmtq restart", page)
                self.assertIn("the first command stops the server, the second restarts it:", page)
            else:
                self.assertIn("closing the server's window stops it, and OpenDMTQ.exe starts it again.", page)
            # The folder it would remove, which these pages do not know here: said without an empty name.
            self.assertIn("<li>Its folder, with everything in it</li>", page, kind)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class OwnerPasswordTest(unittest.TestCase):
    """The owner's password on the Server page and the API (ADM-124, API-54): on a host install and the Windows bundle,
    written to .env and taken at once, the owner's sign-in for the site written again with it, this sign-in kept and the
    owner's others ended; only the owner changes it; with Docker Compose and Kubernetes the commands that do it."""

    NEW = "Xk3vQ9pLm2Rt7w"

    def host(self, inst):
        """A host install's pages, with its .env as a server set up on 8791 has it."""
        env_file = inst.path(".env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=pw\n")
        return mock.patch.multiple(admin.setup, HOST_INSTALL=True, RUN_DIR=inst.path("run"), ENV_FILE=env_file)

    def post(self, inst, client, password, again=None):
        """The Server page's form, as the owner's browser sends it."""
        with client.session_transaction("/opendmtq/admin/") as s:
            csrf = s["csrf"]
        return client.post("/opendmtq/admin/server/password",
                           data={"csrf": csrf, "password": password, "password2": password if again is None else again})

    def env(self, inst):
        with open(inst.path(".env"), encoding="utf-8") as f:
            return f.read()

    def test_changed_here_and_taken_at_once(self):
        with Install() as inst, self.host(inst):
            inst.sign_in()
            # A second browser of the owner's, signed in before the change.
            other = admin.app.test_client()
            self.assertEqual(other.post("/opendmtq/admin/login", data={"name": "admin", "password": "pw"}).status_code, 302)
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertIn('id="password"', page)
            self.assertIn('action="/opendmtq/admin/server/password"', page)
            r = self.post(inst, inst.client, self.NEW)
            self.assertEqual((r.status_code, r.headers["Location"].endswith("/opendmtq/admin/server#password")), (302, True))
            # In .env, the rest of it as it was; taken by this service now.
            self.assertEqual(self.env(inst), f"PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD={self.NEW}\n")
            self.assertEqual(admin.core.PASSWORD, self.NEW)
            # The owner's sign-in for the players' site, written again with the new one.
            with open(inst.path("state/owner.pass"), encoding="utf-8") as f:
                lines = f.read().splitlines()
            self.assertTrue(admin.auth.account_pass_ok(lines[1], self.NEW))
            self.assertFalse(admin.auth.account_pass_ok(lines[1], "pw"))
            # This sign-in goes on, with the words of what was done; the other one ended, and says why.
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertIn("The owner's password is changed: <code>admin</code> signs in with the new one", page)
            ended = other.get("/opendmtq/admin/")
            self.assertEqual(ended.status_code, 302)
            self.assertIn("/opendmtq/admin/login", ended.headers["Location"])
            self.assertIn("your account was changed", other.get(ended.headers["Location"]).get_data(as_text=True))
            # The old password signs in no more, the new one does.
            fresh = admin.app.test_client()
            self.assertEqual(fresh.post("/opendmtq/admin/login", data={"name": "admin", "password": "pw"}).status_code, 200)
            self.assertEqual(fresh.post("/opendmtq/admin/login", data={"name": "admin", "password": self.NEW}).status_code, 302)
            # In the log of changes, without the password.
            notes = [c for c in admin.insights.audit_read(inst.path("state")) if c["what"] == "server:password"]
            self.assertEqual([c["target"] for c in notes], ["admin"])
            with open(inst.path("state/changes.log"), encoding="utf-8") as f:
                self.assertNotIn(self.NEW, f.read())

    def test_an_owners_sign_in_from_before_ends_too(self):
        # A sign-in an older version made keeps no stamp of the password: it ends with a change made after it began.
        with Install() as inst, self.host(inst):
            inst.sign_in()
            old = admin.app.test_client()
            old.post("/opendmtq/admin/login", data={"name": "admin", "password": "pw"})
            with old.session_transaction("/opendmtq/admin/") as s:
                del s["pw"]
            self.assertEqual(old.get("/opendmtq/admin/").status_code, 200)
            # The change at least a second after it began.
            with mock.patch("time.time", return_value=time.time() + 5):
                self.post(inst, inst.client, self.NEW)
            self.assertEqual(old.get("/opendmtq/admin/").status_code, 302)

    def test_what_is_refused_is_said_and_nothing_changes(self):
        with Install() as inst, self.host(inst):
            inst.sign_in()
            for password, again, words in (("short", None, "10 to 64 characters"), ("Xk3vQ9pL$m2Rt7w", None, "10 to 64 characters"),
                                           ("with a space here", None, "10 to 64 characters"), (self.NEW, "Xk3vQ9pLm2Rt7x", "not the same"),
                                           ("", None, "Type the new password")):
                self.post(inst, inst.client, password, again)
                page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
                self.assertIn(words, page, password)
                self.assertIn("ADMIN_PASSWORD=pw\n", self.env(inst), password)
                self.assertEqual(admin.core.PASSWORD, "pw")

    def test_only_the_owner(self):
        with Install() as inst, self.host(inst):
            server_with_data(inst.root)
            # An account with admin rights opens these pages, but the owner's password is not its to change.
            self.assertTrue(admin.auth.account_create("keeper", "keeper-password-1", "", True))
            keeper = admin.app.test_client()
            self.assertEqual(keeper.post("/opendmtq/admin/login", data={"name": "keeper", "password": "keeper-password-1"}).status_code, 302)
            page = keeper.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertIn("Only the owner changes it", page)
            self.assertNotIn('action="/opendmtq/admin/server/password"', page)
            self.post(inst, keeper, self.NEW)
            self.assertIn("ADMIN_PASSWORD=pw\n", self.env(inst))
            # Its token cannot either; the owner's can, and still works afterwards.
            with admin.app.test_request_context():
                _, theirs = admin.tokens.make("theirs", "write", ("keeper", False, admin.auth.account_find("keeper")["created_at"]))
                _, owners = admin.tokens.make("owners", "write", ("admin", True, None))
            refused = inst.client.post("/opendmtq/api/v1/server/password", json={"password": self.NEW}, headers={"Authorization": f"Bearer {theirs}"})
            self.assertEqual((refused.status_code, refused.get_json()["error"]["code"]), (403, "owner_only"))
            self.assertIn("ADMIN_PASSWORD=pw\n", self.env(inst))
            done = inst.client.post("/opendmtq/api/v1/server/password", json={"password": self.NEW}, headers={"Authorization": f"Bearer {owners}"})
            self.assertEqual((done.status_code, done.get_json()), (200, {"changed": True, "user": "admin"}))
            self.assertIn(f"ADMIN_PASSWORD={self.NEW}\n", self.env(inst))
            self.assertEqual(inst.client.get("/opendmtq/api/v1/server", headers={"Authorization": f"Bearer {owners}"}).status_code, 200)
            bad = inst.client.post("/opendmtq/api/v1/server/password", json={"password": "a$b"}, headers={"Authorization": f"Bearer {owners}"})
            self.assertEqual((bad.status_code, bad.get_json()["error"]["code"]), (400, "bad_password"))

    def test_a_restart_of_the_admin_service_keeps_the_new_password(self):
        # The host program starts a stopped admin service again with the settings it read at its own start: the service
        # takes the owner's password from .env as it is now, not the one it was handed. Before, the old one came back, and
        # the service wrote it into the site's copy too.
        with Install() as inst, self.host(inst):
            inst.sign_in()
            self.post(inst, inst.client, self.NEW)
            handed = {"OPENDMTQ_HOST_INSTALL": "yes", "OPENDMTQ_ENV_FILE": inst.path(".env"), "ADMIN_PASSWORD": "pw"}
            # The service's own start, in a process of its own, with what the host program hands it.
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            folders = {"OPENDMTQ_DB": inst.path("state/dmtq.db3"), "OPENDMTQ_LOGS": inst.path("logs"),
                       "OPENDMTQ_BACKUPS": inst.path("backups"), "OPENDMTQ_APK": inst.path("apk"), "OPENDMTQ_RUN": inst.path("run")}
            start = ("import sys; sys.path.insert(0, sys.argv[1]); from opendmtq_tools import admin; "
                     "print(admin.core.PASSWORD)")
            r = subprocess.run([sys.executable, "-I", "-B", "-c", start, here], env={**os.environ, **folders, **handed},
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.stdout.strip().splitlines()[-1:], [self.NEW], r.stderr[-2000:])
            # The site's copy written with the new one, not the old.
            with open(inst.path("state/owner.pass"), encoding="utf-8") as f:
                self.assertTrue(admin.auth.account_pass_ok(f.read().splitlines()[1], self.NEW))
            with mock.patch.dict(os.environ, handed):
                self.assertEqual(admin.core.configured_password(), self.NEW)
            # .env as Notepad and a hand may leave it: a byte order mark, export, quotes; the last line that sets it.
            with open(inst.path(".env"), "w", encoding="utf-8") as f:
                f.write("\ufeffADMIN_PASSWORD=first-one-1\nexport ADMIN_PASSWORD=\"second one 2\"\n")
            with mock.patch.dict(os.environ, handed):
                self.assertEqual(admin.core.configured_password(), "second one 2")
            # Docker Compose and Kubernetes start the service anew with .env's or the Secret's: what it is handed.
            with mock.patch.dict(os.environ, {"ADMIN_PASSWORD": "handed-one-1", "OPENDMTQ_HOST_INSTALL": ""}):
                self.assertEqual(admin.core.configured_password(), "handed-one-1")

    def test_what_cannot_be_written_puts_back_what_was(self):
        with Install() as inst, self.host(inst):
            inst.sign_in()
            # .env cannot be written (a full disk): refused in words, nothing changed.
            def no_room(updates):
                raise OSError(28, "No space left on device")
            with mock.patch.object(admin.setup, "save_env", no_room):
                self.post(inst, inst.client, self.NEW)
            self.assertIn("The password was not changed: .env could not be written", inst.client.get("/opendmtq/admin/server").get_data(as_text=True))
            self.assertEqual(admin.core.PASSWORD, "pw")
            # The site's copy (owner.pass) cannot be written: refused in words, .env and these pages as they were.
            with mock.patch.object(admin.auth, "owner_file_write", lambda: "failed"):
                self.post(inst, inst.client, self.NEW)
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertIn("The password was not changed", page)
            self.assertIn("ADMIN_PASSWORD=pw\n", self.env(inst))
            self.assertEqual(admin.core.PASSWORD, "pw")
            # The settings' file cannot take the moment of the change: the change stands, and this sign-in goes on.
            def full(**changes):
                raise OSError(28, "No space left on device")
            with mock.patch.object(admin.core, "save_settings", full):
                r = self.post(inst, inst.client, self.NEW)
            self.assertEqual(r.status_code, 302)
            self.assertIn(f"ADMIN_PASSWORD={self.NEW}\n", self.env(inst))
            page = inst.client.get("/opendmtq/admin/server")
            self.assertEqual(page.status_code, 200)
            self.assertIn("password is changed", page.get_data(as_text=True))

    def test_two_changes_of_env_at_once_both_stay(self):
        # Two writers of .env in this service at the same moment (the Server page's port and password from two browsers):
        # both changes stay. Before, each wrote the file as it had read it, and one change was lost.
        with Install() as inst, self.host(inst):
            gate = threading.Barrier(2)
            real_open = open

            def reading(path, *args, **kwargs):
                # Both writers held where they read .env, should they read it at once.
                if path == admin.setup.ENV_FILE and not args and kwargs.get("encoding") == "utf-8-sig":
                    try:
                        gate.wait(timeout=0.5)
                    except threading.BrokenBarrierError:
                        pass
                return real_open(path, *args, **kwargs)
            with mock.patch.object(admin.setup, "open", reading, create=True):
                one = threading.Thread(target=admin.setup.save_env, args=({"FIRST_KEY": "one"},))
                two = threading.Thread(target=admin.setup.save_env, args=({"SECOND_KEY": "two"},))
                one.start()
                two.start()
                one.join()
                two.join()
            text = self.env(inst)
            self.assertIn("FIRST_KEY=one\n", text)
            self.assertIn("SECOND_KEY=two\n", text)
            # No writer's file left beside it.
            self.assertEqual([n for n in os.listdir(inst.root) if n.startswith(".env.")], [])

    def test_sign_out_everywhere_else_ends_the_admin_pages_sign_ins(self):
        # The site's MY PAGE writes the moment from which the account's sign-ins count (signed_out_at; the owner's in
        # owner-signed-out): its sign-ins to these pages made before it end too.
        with Install() as inst, self.host(inst):
            server_with_data(inst.root)
            self.assertTrue(admin.auth.account_create("keeper", "keeper-password-1", "", True))
            keeper = admin.app.test_client()
            keeper.post("/opendmtq/admin/login", data={"name": "keeper", "password": "keeper-password-1"})
            self.assertEqual(keeper.get("/opendmtq/admin/").status_code, 200)
            inst.sign_in()
            self.assertEqual(inst.client.get("/opendmtq/admin/").status_code, 200)
            with sqlite3.connect(inst.path("state/dmtq.db3")) as con:
                con.execute("UPDATE SiteUser SET signed_out_at = ? WHERE name = 'keeper'", (int(time.time()) + 1,))
            self.assertEqual(keeper.get("/opendmtq/admin/").status_code, 302)
            # The owner's own, from its file; a sign-in made after it goes on.
            with open(inst.path("state/owner-signed-out"), "w", encoding="ascii") as f:
                f.write(str(int(time.time()) + 1))
            self.assertEqual(inst.client.get("/opendmtq/admin/").status_code, 302)
            later = admin.app.test_client()
            with mock.patch("time.time", return_value=time.time() + 5):
                later.post("/opendmtq/admin/login", data={"name": "admin", "password": "pw"})
                self.assertEqual(later.get("/opendmtq/admin/").status_code, 200)

    def test_a_password_changed_outside_these_pages_ends_the_owners_older_sign_ins(self):
        # The command line's password (./opendmtq password, opendmtq password on the server PC) or a hand changes .env, and
        # the service starts again: the site's copy written over the old one, and the moment noted, so that an owner's
        # sign-in without the password's stamp (an older version's) ends too. Before, nothing noted it.
        with Install() as inst:
            inst.sign_in()
            with inst.client.session_transaction("/opendmtq/admin/") as s:
                # As an older version's sign-in: no stamp of the password, begun a minute ago.
                s.pop("pw", None)
                sid = s["sid"]
            with admin.auth._sessions_lock:
                admin.auth._sessions[sid] -= 60
            self.assertEqual(inst.client.get("/opendmtq/admin/").status_code, 200)
            # The first start writes the file anew: nothing to note. The same password at the next start keeps it.
            admin.core.save_settings(owner_password_at=None)
            with contextlib.suppress(FileNotFoundError):
                os.remove(admin.auth.owner_file())
            self.assertEqual(admin.auth.owner_file_at_start(), "written")
            self.assertFalse(admin.core.settings().get("owner_password_at"))
            self.assertEqual(admin.auth.owner_file_at_start(), "kept")
            self.assertFalse(admin.core.settings().get("owner_password_at"))
            self.assertEqual(inst.client.get("/opendmtq/admin/").status_code, 200)
            # A new one in .env at this start: the moment noted, and the older sign-in ends.
            with mock.patch.object(admin.core, "PASSWORD", self.NEW):
                self.assertEqual(admin.auth.owner_file_at_start(), "written")
                self.assertTrue(admin.core.settings().get("owner_password_at"))
                self.assertEqual(inst.client.get("/opendmtq/admin/").status_code, 302)

    def test_in_containers_the_command_line_does_it(self):
        with Install() as inst:
            server_with_data(inst.root)
            with admin.app.test_request_context():
                _, token = admin.tokens.make("owners", "write", ("admin", True, None))
            r = inst.client.post("/opendmtq/api/v1/server/password", json={"password": self.NEW}, headers={"Authorization": f"Bearer {token}"})
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "by_command"))
            self.assertIn("./opendmtq password", r.get_json()["error"]["message"])
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertIn("./opendmtq password", page)
            self.assertNotIn('action="/opendmtq/admin/server/password"', page)
        # Kubernetes: the Secret the chart named, and the restart that takes it.
        with Install() as inst, mock.patch.object(admin.setup, "IN_KUBERNETES", True), \
                mock.patch.dict(os.environ, {"OPENDMTQ_RELEASE": "home", "POD_NAMESPACE": "games", "OPENDMTQ_ADMIN_SECRET": "home-opendmtq-admin"}):
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertIn("kubectl -n games create secret generic home-opendmtq-admin --from-literal=ADMIN_PASSWORD=&lt;password&gt;", page)
            self.assertIn("kubectl -n games rollout restart deploy -l app.kubernetes.io/instance=home", page)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class DeletePartCommandTest(unittest.TestCase):
    """ADM-166: a part of the data these pages cannot delete names the command that does on the server PC, the install's
    own with the part's name (it named Docker Compose's for the game files on every install, whatever the part)."""

    def test_each_install_names_its_own_command_and_the_part(self):
        for kind, want in (("docker", "./opendmtq delete-data recordings"), ("windows", "OpenDMTQ.exe delete-data recordings"),
                           ("host", "opendmtq delete-data recordings")):
            with mock.patch.object(admin.lifecycle, "install_kind", lambda kind=kind: kind):
                self.assertEqual(admin.lifecycle.delete_part_command("recordings"), want, kind)
        # Kubernetes deletes the data's volumes whole: its command for every part.
        with mock.patch.object(admin.lifecycle, "install_kind", lambda: "kubernetes"):
            self.assertIn("delete pvc", admin.lifecycle.delete_part_command("game"))

    def test_the_page_and_the_api_say_it_for_that_part_alone(self):
        with Install() as inst, mock.patch.object(admin.lifecycle, "install_kind", lambda: "host"):
            sizes = {part: {"bytes": 1, "can_delete": part != "logs"} for part in server_data.PARTS}
            with mock.patch.object(server_data, "sizes", lambda layout: sizes):
                parts = {p["part"]: p for p in admin.lifecycle.data_parts()}
                self.assertEqual(parts["logs"]["command"], "opendmtq delete-data logs")
                self.assertTrue(all(p["command"] == "" for name, p in parts.items() if name != "logs"))
                inst.sign_in()
                page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
                self.assertIn("<code>opendmtq delete-data logs</code>", page)
                self.assertNotIn("./opendmtq delete-data game", page)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class DeleteAndRepairTest(unittest.TestCase):
    """Deleting the data and the repair from the page and the API, as jobs (ADM-110, ADM-112, API-45, API-46)."""

    def setUp(self):
        self.inst = Install().__enter__()
        server_with_data(self.inst.root)
        # The admin pages' paths onto this test's data (Install's own patch covers the database, the apps and backups).
        self.extra = mock.patch.dict(os.environ, {"OPENDMTQ_DB": self.inst.path("state/dmtq.db3"), "OPENDMTQ_APK": self.inst.path("apk"),
                                                  "OPENDMTQ_BACKUPS": self.inst.path("backups"),
                                                  "OPENDMTQ_CUSTOM": self.inst.path("custom"),
                                                  "OPENDMTQ_LOGS": self.inst.path("state/logs"),
                                                  "OPENDMTQ_CONTENT": self.inst.path("content")})
        self.extra.start()
        self.inst.sign_in()
        with self.inst.client.session_transaction("/opendmtq/admin/") as s:
            self.csrf = s["csrf"]

    def tearDown(self):
        self.extra.stop()
        self.inst.__exit__(None, None, None)
        # The jobs are the service's, kept in memory: the other tests start with none.
        for job in list(admin.jobs._jobs.values()):
            job["ended"].wait(30)
        admin.jobs._jobs.clear()

    def wait(self, job_id):
        job = admin.jobs._jobs[job_id]
        self.assertTrue(job["ended"].wait(30))
        return job

    def test_the_page_lists_each_part_with_its_size(self):
        page = self.inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
        for part in server_data.PARTS:
            self.assertIn(f'value="{part}"', page)
        self.assertIn("4.9 KB", page)

    def test_without_the_word_nothing_goes(self):
        r = self.inst.client.post("/opendmtq/admin/server/data", data={"csrf": self.csrf, "part": "apps", "backup": "yes"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(os.path.exists(self.inst.path("apk/out/OpenDMTQ-x.apk")))

    def test_a_backup_first_then_the_parts_ticked(self):
        r = self.inst.client.post("/opendmtq/admin/server/data", data={"csrf": self.csrf, "part": ["database", "backups"],
                                                                     "backup": "yes", "confirm": "delete"})
        self.assertEqual(r.status_code, 302)
        backups = os.listdir(self.inst.path("backups"))
        # The backup made first stays; the two before it went.
        self.assertEqual(len(backups), 1)
        self.assertIn("before-delete", backups[0])
        con = sqlite3.connect(self.inst.path("state/dmtq.db3"))
        try:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM Member").fetchone()[0], 0)
        finally:
            con.close()
        with open(self.inst.path("state/changes.log"), encoding="utf-8") as f:
            self.assertIn("server:delete-data", f.read())

    def test_the_api_deletes_with_the_word_and_counts_the_parts(self):
        with admin.app.test_request_context():
            _, token = admin.tokens.make("test", "write", ("admin", True, None))
        headers = {"Authorization": f"Bearer {token}"}
        listed = self.inst.client.get("/opendmtq/api/v1/server/data", headers=headers).get_json()
        self.assertEqual([p["part"] for p in listed["items"]], list(server_data.PARTS))
        refused = self.inst.client.post("/opendmtq/api/v1/server/data/delete", json={"parts": ["apps"], "confirm": "no"}, headers=headers)
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.get_json()["error"]["code"], "not_confirmed")
        answer = self.inst.client.post("/opendmtq/api/v1/server/data/delete", json={"parts": ["apps"], "backup": False, "confirm": "delete"},
                                       headers=headers)
        self.assertEqual(answer.status_code, 202)
        self.assertEqual(self.wait(answer.get_json()["job"]["id"])["state"], "done")
        self.assertEqual(os.listdir(self.inst.path("apk/out")), [])
        state = self.inst.client.get("/opendmtq/api/v1/server", headers=headers).get_json()
        self.assertEqual(state["install"], "docker")
        self.assertFalse(state["runs_itself"])
        self.assertEqual(state["commands"]["uninstall"], "./opendmtq uninstall")
        self.assertEqual(self.inst.client.post("/opendmtq/api/v1/server/uninstall", json={"confirm": "uninstall"}, headers=headers).status_code, 404)

    def test_neither_runs_beside_a_restore(self):
        # A restore holds backups._restoring as long as it runs: the deletion and the repair are refused meanwhile (both
        # went ahead before), and while a repair runs a restore and a backup wait for it.
        with admin.app.test_request_context():
            _, token = admin.tokens.make("test", "write", ("admin", True, None))
        headers = {"Authorization": f"Bearer {token}"}
        self.assertTrue(admin.backups._restoring.acquire(blocking=False))
        try:
            for path, body in (("/server/data/delete", {"parts": ["apps"], "backup": False, "confirm": "delete"}),
                               ("/server/repair", None)):
                r = self.inst.client.post("/opendmtq/api/v1" + path, json=body, headers=headers)
                self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "busy"), path)
            self.assertTrue(os.listdir(self.inst.path("apk/out")))
        finally:
            admin.backups._restoring.release()
        # A repair held mid-way: a restore and a backup made now are refused until it ends.
        going, go_on = threading.Event(), threading.Event()
        real_run = admin.lifecycle.repairing.run

        def slow_run(*args, **kw):
            going.set()
            go_on.wait(20)
            return real_run(*args, **kw)
        with mock.patch.object(admin.lifecycle.repairing, "run", slow_run):
            r = self.inst.client.post("/opendmtq/api/v1/server/repair", headers=headers)
            self.assertEqual(r.status_code, 202)
            self.assertTrue(going.wait(20))
            backup = sorted(os.listdir(self.inst.path("backups")))[0]
            with admin.app.test_request_context():
                with self.assertRaises(admin.core.Refused) as refused:
                    admin.backups.start_restore(backup)
                self.assertEqual(refused.exception.code, "busy")
                with self.assertRaises(admin.core.Refused):
                    admin.backups.create()
            go_on.set()
            self.wait(r.get_json()["job"]["id"])
        # Ended: the lock is free again.
        self.assertTrue(admin.backups._restoring.acquire(blocking=False))
        admin.backups._restoring.release()

    def test_the_repair_makes_folders_and_the_owner_sign_in_again(self):
        import shutil
        shutil.rmtree(self.inst.path("backups"))
        os.makedirs(self.inst.path("backups"))
        shutil.rmtree(self.inst.path("state/live-rec"))
        with mock.patch.object(admin.apps, "start_build", return_value=("job1", "192.168.0.10")) as build:
            r = self.inst.client.post("/opendmtq/admin/server/repair", data={"csrf": self.csrf})
            self.assertEqual(r.status_code, 302)
            job = max(admin.jobs.listing(), key=lambda j: j["started"])
            self.wait(job["id"])
        said = " ".join(words for _, words in job["said"])
        self.assertIn("made again", said)
        self.assertTrue(os.path.isdir(self.inst.path("state/live-rec")))
        self.assertTrue(os.path.exists(self.inst.path("state/owner.pass")))
        # latest.json names no app: built again, as the App page builds it.
        build.assert_called_once()


if __name__ == "__main__":
    unittest.main()
