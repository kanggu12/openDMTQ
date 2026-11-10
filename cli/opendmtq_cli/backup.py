"""Backups of everything that cannot be downloaded again: the database, the signing key, .env.

A backup is one .tar.gz in data/backups. The newest KEEP are kept.
"""

import datetime
import hashlib
import os
import shutil
import sqlite3
import subprocess
import tarfile
import time
import tempfile
import zlib

from . import system
from .system import DATA, ENV_FILE

BACKUPS = os.path.join(DATA, "backups")
DB = os.path.join(DATA, "state", "dmtq.db3")
KEYSTORE = os.path.join(DATA, "apk", "keystore")
# Enough history to go back a few weeks of daily use; each archive is a few KB.
KEEP = 30
# Past this many bytes of added songs a backup is stored without compression (their music and video hardly shrink):
# the same limit as STORE_ONLY_FROM in tools/opendmtq_tools/admin.
STORE_ONLY_FROM = 64 * 1024 * 1024
# Where a restore makes the restored database ready, in the container, beside the live one: on the same disk, so that it
# takes the live one's place in one rename.
RESTORING = "/data/state/.restoring.db3"


def _snapshot_db(dest):
    """Consistent copy of the database into dest, even while the server writes to it."""
    if system.container_state() == "running":
        # SQLite's online backup, run by the server's own PHP inside the container. The copy goes
        # next to the database (data/state), not into the container's 64 MB /tmp, which a large
        # database does not fit.
        snap = "/data/.opendmtq-backup.db3"
        r = subprocess.run(["docker", "exec", system.container(), "php", "-r",
                            f'$s = new SQLite3("/data/dmtq.db3", SQLITE3_OPEN_READONLY); $s->busyTimeout(5000); $d = new SQLite3("{snap}");'
                            # backup() only warns when it fails, and an empty file would pass as the backup.
                            'if (!$s->backup($d)) {{ exit(1); }} $d->close();'.replace("{{", "{").replace("}}", "}")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            subprocess.run(["docker", "exec", system.container(), "rm", "-f", snap], capture_output=True)
            system.die(f"database backup failed: {r.stderr.strip() or r.stdout.strip()}")
        # Stream it out (whoever owns data/state), then remove the copy.
        with open(dest, "wb") as out:
            subprocess.run(["docker", "exec", system.container(), "cat", snap], stdout=out, check=True)
        subprocess.run(["docker", "exec", system.container(), "rm", "-f", snap], capture_output=True)
    else:
        _copy_stopped_db(dest)


def _copy_stopped_db(dest):
    """Copy of a database nothing is writing to. The file alone may not be all of it: a server that
    stopped leaves recent commits in dmtq.db3-wal (write-ahead mode, see server/game/bin/setup-db.php), and one
    that crashed in the middle of a commit leaves the way back in dmtq.db3-journal. So the copy gets
    those files too, and SQLite makes it whole, in the copy's own folder, touching nothing of the
    original."""
    shutil.copyfile(DB, dest)
    sides = [end for end in ("-wal", "-journal") if os.path.isfile(DB + end)]
    for end in sides:
        shutil.copyfile(DB + end, dest + end)
    if not sides:
        return
    try:
        con = sqlite3.connect(dest)
        try:
            # A first read applies a journal; the checkpoint moves the log into the file.
            con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        finally:
            con.close()
    except sqlite3.Error as e:
        # A damaged database still gets its copy: this may be the safety copy of a restore that is
        # about to replace it, which must not be stopped by the very damage it is there to repair.
        system.warn(f"the database could not be made whole for the backup ({e}); copied as it is")


def create(reason="manual", protect=None):
    """Write one backup; returns its path, or None when there is nothing to back up yet.

    protect is an archive the pruning must keep: the one a restore is about to read.
    """
    if not os.path.isfile(DB):
        return None
    # Archives hold the signing key, its password and .env's passwords: owner only.
    os.makedirs(BACKUPS, exist_ok=True)
    os.chmod(BACKUPS, 0o700)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = os.path.join(BACKUPS, f"opendmtq-{stamp}-{reason}.tar.gz")
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = os.path.join(tmp, "dmtq.db3")
        _snapshot_db(db_copy)
        # Under another name until it is whole: on a full disk, half an archive would be listed as the newest backup and
        # push a good one out.
        partial = archive + ".part"
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            # Added songs' music and video hardly compress: with many of them the archive stores everything as it is
            # (gzip level 0, still a .tar.gz), as the admin pages' backups do.
            songs = os.path.join(DATA, "custom", "songs")
            size = sum(os.path.getsize(os.path.join(d, n)) for d, _, names in os.walk(songs) for n in names)
            level = 0 if size > STORE_ONLY_FROM else 6
            with os.fdopen(fd, "wb") as f, tarfile.open(fileobj=f, mode="w:gz", compresslevel=level) as tar:
                os.fchmod(fd, 0o600)
                tar.add(db_copy, arcname="dmtq.db3")
                # The key that lets new APKs install over old ones: a new key is a new app next to the old one.
                if os.path.isdir(KEYSTORE):
                    tar.add(KEYSTORE, arcname="keystore")
                if os.path.isfile(ENV_FILE):
                    tar.add(ENV_FILE, arcname="env")
                # Added songs and hidden flags: the database's records refer to their ids. The folder itself goes in
                # even when empty: it says that this server had none then, and a restore removes later ones.
                folder = tarfile.TarInfo("custom")
                folder.type, folder.mode, folder.mtime = tarfile.DIRTYPE, 0o755, int(time.time())
                tar.addfile(folder)
                for name in ("songs", "hidden.json", "ids.json"):
                    item = os.path.join(DATA, "custom", name)
                    if os.path.exists(item):
                        tar.add(item, arcname=f"custom/{name}")
        except BaseException:
            if os.path.exists(partial):
                os.remove(partial)
            raise
        os.replace(partial, archive)
    # Run as root, the archive goes to the container user like the rest of data/ (the admin pages
    # list, download and restore it).
    system.own_data_dirs(subs=("backups",))
    prune(protect)
    return archive


def prune(protect=None):
    """Keep the newest KEEP backups, and protect (a path) whatever its age."""
    keep = os.path.abspath(protect) if protect else None
    # One brought in by hand on the admin page stays until it is deleted by hand: nothing else would make it again.
    files = sorted(f for f in os.listdir(BACKUPS) if f.startswith("opendmtq-") and f.endswith(".tar.gz") and not f.endswith("-uploaded.tar.gz"))
    for old in files[:-KEEP]:
        if os.path.abspath(os.path.join(BACKUPS, old)) != keep:
            os.remove(os.path.join(BACKUPS, old))


def locate(name):
    """The archive to restore: a name from `opendmtq backups`, or the path of one copied here.

    Stops, before anything has changed, when there is no such file or it holds no database.
    """
    path = os.path.join(BACKUPS, name)
    if os.sep in name or not os.path.isfile(path):
        path = os.path.abspath(os.path.expanduser(name))
    if not os.path.isfile(path):
        system.die(f"no such backup: {name} (./opendmtq backups lists them)")
    try:
        with tarfile.open(path) as tar:
            has_db = any(m.name == "dmtq.db3" and m.isfile() for m in tar.getmembers())
    except (tarfile.TarError, OSError, EOFError, zlib.error) as e:
        system.die(f"{name} is not a backup archive ({e})")
    if not has_db:
        system.die(f"{name} holds no database")
    # The server cannot start on anything else, and the current database would already be replaced.
    problem = database_problem(path)
    if problem:
        system.die(f"{name} cannot be restored: {problem}")
    return path


def database_problem(archive):
    """Why the database in an archive is not one a server can use, or None. As the admin pages check."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            with tarfile.open(archive) as tar:
                member = next(m for m in tar.getmembers() if m.name == "dmtq.db3" and m.isfile())
                with tar.extractfile(member) as src, open(os.path.join(tmp, "dmtq.db3"), "wb") as out:
                    shutil.copyfileobj(src, out)
            con = sqlite3.connect(os.path.join(tmp, "dmtq.db3"))
            try:
                if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    return "its database is damaged"
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            finally:
                con.close()
        except (sqlite3.Error, OSError, tarfile.TarError, EOFError, zlib.error) as e:
            return f"its database cannot be read ({e})"
    return None if {"Member", "Play"} <= tables else "it does not hold a game database"


def listing():
    """Backup file names, newest first."""
    if not os.path.isdir(BACKUPS):
        return []
    return sorted((f for f in os.listdir(BACKUPS) if f.endswith(".tar.gz")), reverse=True)


def restore(name, with_key=False):
    """Put a backup's database back; also its signing key if asked, or if this install has none."""
    path = name if os.path.isabs(name) else os.path.join(BACKUPS, name)
    if not os.path.isfile(path):
        system.die(f"no such backup: {path}")
    # On a new machine nothing has created data/ yet. Create the folders the copy job mounts too:
    # Docker would create a missing one as root, and the key could then not be copied in.
    for sub in ("state", "apk", "custom", "server"):
        os.makedirs(os.path.join(DATA, sub), exist_ok=True)
    # Under data/, not /tmp: Docker installed as a snap cannot mount /tmp into containers.
    with tempfile.TemporaryDirectory(dir=DATA, prefix=".restore-") as tmp:
        with tarfile.open(path) as tar:
            # Only plain members with the names we wrote; never follow paths out of tmp.
            members = [m for m in tar.getmembers()
                       if (m.isfile() or m.isdir()) and not m.name.startswith("/") and ".." not in m.name]
            tar.extractall(tmp, members=members)
        db = os.path.join(tmp, "dmtq.db3")
        if not os.path.isfile(db):
            system.die(f"{path} holds no database")
        # The API's tokens and the site's accounts of now go into the restored database (keep_tokens.py), run by the
        # container from here.
        shutil.copyfile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "keep_tokens.py"), os.path.join(tmp, "keep_tokens.py"))
        # The copying container runs unprivileged; let it read the extracted files.
        os.chmod(tmp, 0o755)
        os.chmod(db, 0o644)
        os.chmod(os.path.join(tmp, "keep_tokens.py"), 0o644)
        # Written through a container so it works whoever owns data/state. The restored file is made ready beside the
        # live one first: today's API tokens and accounts read from the live database (through its log, which holds the
        # newest) and put in it. Then the old database's own log and journal go, as SQLite would apply them to the
        # restored file and damage it, and the restored file takes the live one's place in one step.
        system.compose("--profile", "tools", "run", "--rm", "--no-deps", "--entrypoint", "sh",
                       "tools", "-c", f"mkdir -p /data/state && cp /in/dmtq.db3 {RESTORING} "
                       f"&& python3 /in/keep_tokens.py /data/state/dmtq.db3 {RESTORING} "
                       "&& rm -f /data/state/dmtq.db3-wal /data/state/dmtq.db3-shm /data/state/dmtq.db3-journal "
                       f"&& mv {RESTORING} /data/state/dmtq.db3",
                       extra_env={"IMPORT_FROM": tmp}, capture=True)
        # Added songs travel with the records that refer to them.
        custom = os.path.join(tmp, "custom")
        if os.path.isdir(custom):
            for name in ("songs", "hidden.json", "ids.json"):
                src, dst = os.path.join(custom, name), os.path.join(DATA, "custom", name)
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                elif os.path.exists(dst):
                    os.remove(dst)
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                elif os.path.exists(src):
                    shutil.copyfile(src, dst)
            system.own_data_dirs()
            # Regenerate the overlay and song list for the restored songs. Without client data (a new machine) there is
            # nothing to merge them with yet; `up` does it after the import.
            import glob
            if glob.glob(os.path.join(DATA, "content", "web", "patch", "phone_new", "*", "android", "patch_new.csv.lz4")):
                system.tool("songs")
        # Without --with-key a key is restored only where none exists, because replacing a live key
        # means apps built since cannot be updated. (The pre-restore backup keeps the current one.)
        ks = os.path.join(tmp, "keystore")
        if os.path.isdir(ks) and (with_key or not os.path.isdir(KEYSTORE)):
            shutil.rmtree(KEYSTORE, ignore_errors=True)
            shutil.copytree(ks, KEYSTORE)
            system.own_data_dirs()
            return True
        if os.path.isdir(ks) and key_digest(ks) != key_digest(KEYSTORE):
            # A backup from another server (a move to a new PC): its players' phones only take an
            # update signed with the key in the backup.
            system.warn(f"{os.path.basename(path)} holds another signing key than this server's. If this is a "
                        "move from another PC, its players' phones can only update with that key: restore "
                        f"again with ./opendmtq restore {os.path.basename(path)} --with-key")
    return False


def key_digest(folder):
    """SHA-256 of the signing key in a keystore folder, or None."""
    try:
        with open(os.path.join(folder, "opendmtq.jks"), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None
