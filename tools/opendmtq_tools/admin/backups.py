"""Backups: made by hand or every day, kept to a limit, downloaded, brought in and restored. Each form's work is a function
(create, upload, delete, restore_backup, set_auto) that the API calls as well (api.py)."""

import datetime
import hashlib
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
import threading
import time
import zlib

from flask import flash, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import NotFound

from .. import songs
from . import auth, core, insights, jobs, recordings, status, tokens, webhooks
from .core import Refused, ago, app, BASE, changed, db, private_file, safe_name, t, tp, why

# Backups made here are kept up to this many, like the CLI's.
KEEP_BACKUPS = 30

# Added songs' music and video hardly compress: with more of them than this, a backup stores everything as it is (gzip
# level 0, still a .tar.gz every tool opens) instead of spending seconds on them while the page waits.
STORE_ONLY_FROM = 64 * 1024 * 1024

# The ones the server makes by itself each day: the latest few.
KEEP_AUTO_BACKUPS = 7

# What a database restored while the server runs needs that the server only does at its start
# (server/game/bin/setup-db.php, the same statements): the play history, and one row per player and chart, the
# best of each, with the indexes the rankings read. A backup from an older version has none of it. A merged row's
# keyboard mark is the top score's, as the play that set that score marked it.
PLAY_MERGE = """CREATE TEMP TABLE PlayMerged AS
    SELECT p.pattern_id, p.user_id, MAX(p.score) AS score,
           (SELECT q.grade FROM Play q WHERE q.pattern_id = p.pattern_id AND q.user_id = p.user_id
             ORDER BY q.judgement DESC LIMIT 1) AS grade,
           MAX(p.isAllCombo) AS isAllCombo, MAX(p.isPerfectPlay) AS isPerfectPlay, MAX(p.judgement) AS judgement,
           (SELECT q.keys FROM Play q WHERE q.pattern_id = p.pattern_id AND q.user_id = p.user_id
             ORDER BY q.score DESC LIMIT 1) AS keys
      FROM Play p WHERE p.pattern_id IS NOT NULL AND p.user_id IS NOT NULL
     GROUP BY p.pattern_id, p.user_id HAVING COUNT(*) > 1;
DELETE FROM Play WHERE (pattern_id, user_id) IN (SELECT pattern_id, user_id FROM PlayMerged);
INSERT INTO Play (pattern_id, user_id, score, grade, isAllCombo, isPerfectPlay, judgement, keys)
    SELECT pattern_id, user_id, score, grade, isAllCombo, isPerfectPlay, judgement, keys FROM PlayMerged;
DROP TABLE PlayMerged;"""

# The tables that keep the keyboard's mark (a play made with the PC client's keys, which the game server's save stores:
# server/game/src/game.php): the play's own row and the best it set.
KEYS_TABLES = ("Play", "PlayLog")

# When each player earned each achievement (MY PAGE): the game server's save stores one when a play earns it
# (server/game/src/achievement.php), and it stays while the play log keeps only a year. The server creates the table
# at its start (server/game/bin/setup-db.php, the same statement); a restored database gets it with SCHEMA. A player's
# reset or deletion takes their rows.
ACHIEVEMENT_TABLE = """CREATE TABLE IF NOT EXISTS AchievementDate (user_id INTEGER NOT NULL, achievement_id INTEGER NOT NULL,
        earned_at INTEGER NOT NULL, PRIMARY KEY (user_id, achievement_id))"""

# The rankings' change number and its triggers, as the server makes them at its start (server/game/bin/setup-db.php, the
# same statements): a restored database gets them with SCHEMA, so that the boards the server keeps (src/ranking.php)
# are worked out again after any change made to it.
BOARD_STAMP = "CREATE TABLE IF NOT EXISTS BoardStamp (n INTEGER NOT NULL);\n" \
    "INSERT INTO BoardStamp (n) SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM BoardStamp);\n" + "".join(
        f"CREATE TRIGGER IF NOT EXISTS {table}_stamp_{change.lower()} AFTER {change} ON {table} "
        "BEGIN UPDATE BoardStamp SET n = n + 1; END;\n"
        for table in ("PlayLog", "Play", "Member") for change in ("INSERT", "UPDATE", "DELETE"))

# A player's game state (game.py, server/game/src/player.php): their currencies, experience and own unlimited switch, the
# items they bought or were given or had taken, the products a level unlock opened, their purchases, a ban, and the server's
# game settings. The same statements as setup-db.php's: a restored database gets them with SCHEMA.
GAME_TABLES = (
    "CREATE TABLE IF NOT EXISTS PlayerState (guid INTEGER PRIMARY KEY, mpoint INTEGER NOT NULL, qpoint INTEGER NOT NULL, "
    "exp INTEGER NOT NULL, unlimited INTEGER NOT NULL DEFAULT 0, changed_at INTEGER)",
    "CREATE TABLE IF NOT EXISTS PlayerItem (guid INTEGER NOT NULL, item_id INTEGER NOT NULL, owned INTEGER NOT NULL, "
    "how TEXT NOT NULL, at INTEGER NOT NULL, PRIMARY KEY (guid, item_id))",
    "CREATE TABLE IF NOT EXISTS PlayerUnlock (guid INTEGER NOT NULL, product_id INTEGER NOT NULL, at INTEGER NOT NULL, "
    "PRIMARY KEY (guid, product_id))",
    "CREATE TABLE IF NOT EXISTS PlayerPurchase (id INTEGER PRIMARY KEY, guid INTEGER NOT NULL, product_id INTEGER NOT NULL, "
    "item_id INTEGER NOT NULL, currency TEXT NOT NULL, price INTEGER NOT NULL, paid INTEGER NOT NULL, at INTEGER NOT NULL)",
    "CREATE INDEX IF NOT EXISTS PlayerPurchase_guid ON PlayerPurchase (guid, at)",
    "CREATE TABLE IF NOT EXISTS PlayerBan (guid INTEGER PRIMARY KEY, reason TEXT NOT NULL, since INTEGER NOT NULL, "
    "until INTEGER, by TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE IF NOT EXISTS GameSetting (name TEXT PRIMARY KEY, value TEXT NOT NULL)",
)

# The game's sign-ins (server/game/src/signin.php, the same statements): the access token each platform login handed out,
# as its SHA-256, and the key the game's login gave for it, which a player's own game signs with. A restore keeps today's,
# as it keeps the API's tokens: every game signed in goes on as it was, and none the backup held signs anything now.
SIGN_IN_TABLE = (
    "CREATE TABLE IF NOT EXISTS SignIn (access TEXT PRIMARY KEY, puid TEXT NOT NULL, at INTEGER NOT NULL, key TEXT, "
    "guid INTEGER, play_token TEXT, play_pattern INTEGER, play_at INTEGER)",
    "CREATE INDEX IF NOT EXISTS SignIn_puid ON SignIn (puid, at)",
    "CREATE INDEX IF NOT EXISTS SignIn_guid ON SignIn (guid)",
)
# Its columns, in order: what a restore copies of each sign-in.
SIGN_IN_COLUMNS = ("access", "puid", "at", "key", "guid", "play_token", "play_pattern", "play_at")


def sign_ins(con):
    """con's game sign-ins, as tuples of SIGN_IN_COLUMNS (none from a database from before them)."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'SignIn'").fetchone():
        return []
    return [tuple(r) for r in con.execute(f"SELECT {', '.join(SIGN_IN_COLUMNS)} FROM SignIn")]


def put_sign_ins(con, rows):
    """con's game sign-ins made exactly rows (another database's): the table made where it is not, its own gone."""
    for sql in SIGN_IN_TABLE:
        con.execute(sql)
    con.execute("DELETE FROM SignIn")
    con.executemany(f"INSERT INTO SignIn ({', '.join(SIGN_IN_COLUMNS)}) VALUES ({', '.join('?' for _ in SIGN_IN_COLUMNS)})", rows)

SCHEMA = """CREATE TABLE IF NOT EXISTS PlayLog (id INTEGER PRIMARY KEY, user_id INTEGER, pattern_id INTEGER,
        score INTEGER, grade TEXT, judgement INTEGER, is_record INTEGER, played_at INTEGER,
        keys INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS PlayLog_time ON PlayLog (played_at);
CREATE INDEX IF NOT EXISTS PlayLog_board ON PlayLog (user_id, played_at, pattern_id, score);
DROP INDEX IF EXISTS PlayLog_user;
CREATE INDEX IF NOT EXISTS PlayLog_chart ON PlayLog (pattern_id, played_at);
CREATE INDEX IF NOT EXISTS PlayLog_clears ON PlayLog (user_id, pattern_id, grade);
CREATE INDEX IF NOT EXISTS PlayLog_records ON PlayLog (played_at, id) WHERE is_record = 1;
CREATE INDEX IF NOT EXISTS Play_keys ON Play (user_id) WHERE keys = 1;
CREATE INDEX IF NOT EXISTS PlayLog_keys ON PlayLog (played_at, user_id, pattern_id) WHERE keys = 1;
CREATE INDEX IF NOT EXISTS Play_held ON Play (user_id, pattern_id, score, grade, isAllCombo, isPerfectPlay);
CREATE INDEX IF NOT EXISTS Play_pattern ON Play (pattern_id, score);
CREATE UNIQUE INDEX IF NOT EXISTS Play_one ON Play (pattern_id, user_id);
CREATE INDEX IF NOT EXISTS Play_board ON Play (user_id, pattern_id, score);
DROP INDEX IF EXISTS Play_user;
CREATE INDEX IF NOT EXISTS Member_id ON Member (id);
CREATE INDEX IF NOT EXISTS Member_udid ON Member (udid);
CREATE INDEX IF NOT EXISTS Member_guid ON Member (guid);
CREATE INDEX IF NOT EXISTS Member_puid ON Member (puid);
""" + auth.ACCOUNT_TABLE + ";\n" + ACHIEVEMENT_TABLE + ";\n" + BOARD_STAMP + "".join(sql + ";\n" for sql in GAME_TABLES)


def backup_files():
    """The archives in the backups folder as (name, when made), newest first; none when it cannot be read."""
    try:
        return sorted(((n, os.path.getmtime(os.path.join(core.BACKUPS, n))) for n in os.listdir(core.BACKUPS) if n.endswith(".tar.gz")),
                      key=lambda b: b[1], reverse=True)
    except OSError:
        return []


# What a backup's name starts with: what it is, in the release's files' order and in lower case
# (opendmtq-server-backup-20261117-120000-manual.tar.gz). Those made before 0.11.0 start with "opendmtq-", and 0.11.0's
# first builds wrote "OpenDMTQ-Server-Backup-": all are this server's backups.
BACKUP_PREFIX = "opendmtq-server-backup-"


def made_backups(names):
    """The backups among names that this server made (not one brought in by hand, which stays until deleted by hand),
    oldest first by the time in their names, whichever way they are named."""
    made = [n for n in names if n.lower().startswith("opendmtq-") and n.endswith(".tar.gz") and not n.endswith("-uploaded.tar.gz")]
    return by_stamp(made)


def by_stamp(names):
    """Backups' names oldest first by the time in them (20261117-120000): the names from 0.11.0 on sort before the older
    ones letter by letter, so the whole name would put a new backup first in line to go."""
    return sorted(names, key=lambda n: (m.group(0) if (m := re.search(r"\d{8}-\d{6}", n)) else "", n))


def new_backup_path(reason):
    """A name no archive has yet: two in one second must not overwrite each other (a restore's safety copy, the
    very archive it is restoring)."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(core.BACKUPS, f"{BACKUP_PREFIX}{stamp}-{reason}.tar.gz")
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(core.BACKUPS, f"{BACKUP_PREFIX}{stamp}-{reason}-{n}.tar.gz")
    return path


# What a backup and a restore work on, in folders of their own beside the backups (on the disk that holds them, where the
# archive itself goes or comes from): never in this service's /tmp, a tmpfs in memory with Docker Compose (1.5 GB,
# compose.yaml) and an emptyDir with a limit in the Helm chart, which a database or the added songs may outgrow. Hidden,
# and no .tar.gz: never on the list. One a stopped service left is cleared at its next start (clear_partial_backups).
WORK_PREFIXES = (".backing-up-", ".restoring-")


def work_folder(prefix):
    """A folder of its own for a backup's or a restore's work, beside the backups (WORK_PREFIXES), removed with all in it
    when the work ends: a TemporaryDirectory there."""
    os.makedirs(core.BACKUPS, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=core.BACKUPS, prefix=prefix)


def make_backup(reason, protect=None):
    """Database (online snapshot) and signing key in one archive, like `opendmtq backup`. The
    pruning never removes protect (the archive a restore is reading)."""
    os.makedirs(core.BACKUPS, exist_ok=True)
    path = new_backup_path(reason)
    # Under another name until it is whole: a restart or a full disk must not leave half an archive that counts as the
    # newest backup, on the list with a Restore button.
    partial = path + ".part"
    # The database's snapshot beside the archive it goes into, not in /tmp (WORK_PREFIXES).
    with work_folder(WORK_PREFIXES[0]) as tmp:
        snap = os.path.join(tmp, "dmtq.db3")
        src, dst = sqlite3.connect(core.DB, timeout=5), sqlite3.connect(snap)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        # A damaged database copies without a word. As a backup it would push a good one out, so it does not become one.
        check = sqlite3.connect(snap)
        try:
            if check.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("database disk image is malformed")
        finally:
            check.close()
        try:
            level = 0 if insights.folder_size(os.path.join(songs.CUSTOM, "songs")) > STORE_ONLY_FROM else 6
            with private_file(partial) as out, tarfile.open(fileobj=out, mode="w:gz", compresslevel=level) as tar:
                tar.add(snap, arcname="dmtq.db3")
                if os.path.isdir(os.path.join(core.APK, "keystore")):
                    tar.add(os.path.join(core.APK, "keystore"), arcname="keystore")
                # Added songs and hidden flags: the database's records refer to their ids. The folder itself goes
                # in even when empty: it says that this server had none then, and a restore removes later ones.
                folder = tarfile.TarInfo("custom")
                folder.type, folder.mode, folder.mtime = tarfile.DIRTYPE, 0o755, int(time.time())
                tar.addfile(folder)
                for name in ("songs", "hidden.json", "ids.json"):
                    item = os.path.join(songs.CUSTOM, name)
                    if os.path.exists(item):
                        tar.add(item, arcname=f"custom/{name}")
        except (OSError, tarfile.TarError):
            if os.path.exists(partial):
                os.remove(partial)
            raise
    os.replace(partial, path)
    # The disk's picture on the status page counts again.
    status._disk_cache.clear()
    # One brought here by hand stays until it is deleted by hand: nothing else would make it again.
    files = made_backups(os.listdir(core.BACKUPS))
    for old in files[:-KEEP_BACKUPS]:
        if old != protect:
            os.remove(os.path.join(core.BACKUPS, old))
    return os.path.basename(path)


def keys_columns(con):
    """The keyboard's mark (KEYS_TABLES' column keys) added to the tables of a database from before it, with 0 in every row
    they have: every older play and best reads as one made by touch, and the server's next save can store the mark. As
    the server's start adds it (server/game/bin/setup-db.php). A table the database does not have yet is left to SCHEMA,
    which makes it with the column."""
    for table in KEYS_TABLES:
        # The table's columns: none when there is no such table.
        columns = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
        if columns and "keys" not in columns:
            con.execute(f"ALTER TABLE {table} ADD COLUMN keys INTEGER NOT NULL DEFAULT 0")


def bring_schema_up_to_date(con):
    """A database restored while the server runs: what the server would do with it at its next start."""
    # The keyboard's column first: the merge reads it, and SCHEMA's indexes of the keyboard's rows are made on it.
    keys_columns(con)
    con.executescript("BEGIN IMMEDIATE;" + PLAY_MERGE + "COMMIT;" + SCHEMA)
    auth.account_table(con)
    tokens.token_table(con)


def database_is_damaged():
    """True when the live file cannot be read as a database at all. A lock or a busy disk is not damage."""
    try:
        con = sqlite3.connect(core.DB, timeout=5)
        try:
            return con.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok"
        finally:
            con.close()
    except sqlite3.OperationalError:
        return False
    except sqlite3.DatabaseError:
        return True


def set_damaged_aside():
    """The damaged database out of the way but kept: the only way back there is. Its log and journal go with it,
    since SQLite would otherwise apply them to the restored file. The kept file's name."""
    kept = f"{os.path.basename(core.DB)}.damaged-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    os.replace(core.DB, os.path.join(os.path.dirname(core.DB), kept))
    for suffix in ("-wal", "-shm", "-journal"):
        if os.path.exists(core.DB + suffix):
            os.replace(core.DB + suffix, os.path.join(os.path.dirname(core.DB), kept + suffix))
    return kept


def check_restorable(path):
    """Refuses a database that would break the server: read and migrated as a copy, the same statements as the live
    one will see and what the pages read, before anything of the live one changes."""
    with sqlite3.connect(path) as con:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError(tp("bak.damaged"))
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not {"Member", "Play"} <= tables:
            raise ValueError(tp("bak.not_game"))
        try:
            bring_schema_up_to_date(con)
            con.execute(f"SELECT COUNT(*) FROM ({core.PLAYER_ROWS})", (core.CHECK_UDID,)).fetchone()
            con.execute("SELECT pattern_id, user_id, score, grade, isAllCombo, isPerfectPlay, judgement FROM Play LIMIT 1").fetchone()
        except sqlite3.Error as e:
            raise ValueError(tp("bak.not_game")) from e
    con.close()

def has_players(con):
    """True when the database holds a player of the game (the server's own check account aside); False for none, or for a
    database without the game's tables (one set up a moment ago, before the game server made them)."""
    try:
        return con.execute(f"SELECT 1 FROM ({core.PLAYER_ROWS}) LIMIT 1", (core.CHECK_UDID,)).fetchone() is not None
    except sqlite3.Error:
        return False


# One restore at a time: the page can be open in two tabs, and the service has one process.
_restoring = threading.Lock()


def key_digest_in(archive):
    """SHA-256 of the signing key a backup archive holds, or None."""
    try:
        with tarfile.open(archive) as tar:
            member = next((m for m in tar.getmembers() if m.name == "keystore/opendmtq.jks" and m.isfile()), None)
            return hashlib.sha256(tar.extractfile(member).read()).hexdigest() if member else None
    except (tarfile.TarError, OSError):
        return None


def current_key_digest():
    try:
        with open(os.path.join(core.APK, "keystore", "opendmtq.jks"), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


@app.route(BASE + "/backups/auto", methods=["POST"])
def backups_auto():
    """Turns the daily backup on or off."""
    on = set_auto(request.form.get("action") == "on")
    flash(t("bak.auto_on" if on else "bak.auto_off"), "ok")
    return redirect(url_for("backups_page"))


def set_auto(on):
    """Turns the daily backup on or off. Returns whether it is on now."""
    core.save_settings(auto_backup=on)
    changed("backups_auto:" + ("on" if core.settings()["auto_backup"] else "off"))
    return core.settings()["auto_backup"]


@app.route(BASE + "/backups", methods=["GET", "POST"])
def backups_page():
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                # A job: with gigabytes of added songs it takes a while, which the page then follows (jobs.answer).
                return jobs.answer(jobs.start_page_task("backup", made_now), "backups_page")
            if action == "upload":
                flash(t("bak.uploaded", name=upload(request.files.get("file"))), "ok")
        except Refused as e:
            flash(e.words, e.tone)
        return redirect(url_for("backups_page"))
    # A backup or a restore of this page's that took longer than its form waited: followed here until it ends, then what
    # it said, on the page without it.
    wanted = request.args.get("job", "")
    if wanted and jobs.nothing_to_follow(wanted):
        return redirect(url_for("backups_page"))
    files = listing()
    daily, next_due = dailies(files)
    # The daily backups kept, as their places: the newest on the right, the empty ones at the left.
    slots = [None] * (KEEP_AUTO_BACKUPS - len(daily)) + daily[::-1]
    next_at = datetime.datetime.fromtimestamp(next_due).strftime("%m-%d %H:%M") if next_due else ""
    return render_template("backups.html", files=files, auto=core.settings().get("auto_backup"), slots=slots, next_at=next_at,
                           others=len(files) - len(daily), job=wanted or None, job_kind=jobs._jobs[wanted]["kind"] if wanted else None)


def made_now(say):
    """Back up now, as its job (jobs.start_page_task): what the page says of it, and whether it worked."""
    try:
        return [("ok", t("bak.created", name=create()))], True
    except Refused as e:
        return [(e.tone, e.words)], False


def listing():
    """The backups, newest first: name, size, when made (and how long ago, for the page), and its kind (a key of the
    page's words)."""
    files = []
    for name, made in backup_files():
        try:
            files.append({"name": name, "size": os.path.getsize(os.path.join(core.BACKUPS, name)), "made": made, "ago": ago(made), "kind": backup_kind(name)})
        except OSError:
            # Deleted a moment ago.
            pass
    return files


def dailies(files):
    """The daily backups kept (newest first, as many as are kept), and when the next one comes, or None when it is due
    already: a day after the newest backup made here (an uploaded one does not count), at the first look after it (every
    half an hour), if the game's data changed meanwhile."""
    daily = [f for f in files if f["kind"] == "bak.kind_auto"][:KEEP_AUTO_BACKUPS]
    made_here = [f["made"] for f in files if f["kind"] != "bak.kind_uploaded"]
    due = max(made_here) + 86400 if made_here else None
    return daily, (due if due and due > time.time() else None)


def create():
    """Makes a backup now: its name. Refused while a restore runs (it would be a backup of something half put back), and
    when it cannot be made (a locked database, a full disk), with no half-made archive left behind."""
    if not _restoring.acquire(blocking=False):
        raise Refused(409, "busy", t("bak.busy"))
    try:
        name = make_backup("admin")
    except (sqlite3.Error, OSError, tarfile.TarError) as e:
        raise Refused(500, "backup_failed", t("bak.failed", detail=why(e)))
    finally:
        _restoring.release()
    changed("backups_page:create", name)
    return name


def upload(storage):
    """Brings in a backup archive (.tar.gz) from elsewhere: its name here. Only what could be restored joins the list; a
    closer look comes when it is restored."""
    if not storage or not storage.filename.endswith(".tar.gz"):
        raise Refused(400, "no_file", t("bak.choose"))
    path = new_backup_path("uploaded")
    name = os.path.basename(path)
    try:
        os.makedirs(core.BACKUPS, exist_ok=True)
        with private_file(path) as out:
            storage.save(out)
        try:
            with tarfile.open(path) as archive:
                archive.getmember("dmtq.db3")
        except (tarfile.TarError, KeyError, EOFError):
            os.remove(path)
            raise Refused(422, "not_backup", t("bak.not_backup"))
    except OSError as e:
        # Half a file (a full disk) must not join the list as a backup.
        if os.path.exists(path):
            os.remove(path)
        raise Refused(500, "upload_failed", t("bak.upload_failed", detail=why(e)))
    changed("backups_page:upload", name)
    return name


def backup_kind(name):
    """How a backup came to be, from its file's name, as a key of the page's words."""
    if "-auto" in name:
        return "bak.kind_auto"
    if "-uploaded" in name:
        return "bak.kind_uploaded"
    if "-before-" in name:
        return "bak.kind_before"
    if "-deploy" in name:
        return "bak.kind_deploy"
    return "bak.kind_hand"


@app.route(BASE + "/backups/<name>/download")
def backup_download(name):
    return send_file(safe_name(name, core.BACKUPS, ".tar.gz"), as_attachment=True)


@app.route(BASE + "/backups/<name>", methods=["POST"])
def backup_action(name):
    action = request.form.get("action")
    try:
        if action == "delete":
            delete(name)
            flash(t("bak.deleted", name=name), "ok")
        elif action == "restore":
            # A job, as through the API: a restore can take longer than a request may wait (jobs.answer).
            return jobs.answer(start_restore(name), "backups_page")
        else:
            # Any other button on a backup that is gone says so too; one that is there changes nothing.
            backup_path(name)
    except Refused as e:
        flash(e.words, e.tone)
    return redirect(url_for("backups_page"))


def start_restore(name):
    """Starts restoring a backup as a job, for the Backups page and the API alike: the job's id. It says what the page says
    of a restore (restore_backup), and notes the change by whoever asked for it. Refused: no such backup, or a restore
    running already."""
    path = backup_path(name)
    # One restore at a time: the lock is taken here and given back by the job when it ends.
    if not _restoring.acquire(blocking=False):
        raise Refused(409, "busy", t("bak.busy"))

    def work(say):
        # The lock is given back whatever happens.
        try:
            said, done = restore_backup(name, path)
        finally:
            _restoring.release()
        # The log of changes: only a restore that happened.
        if done:
            changed("backup_action:restore", name)
        return said, done

    try:
        return jobs.start_page_task("restore", work, backup=name)
    except Exception:
        # No job to give the lock back: given back here.
        _restoring.release()
        raise


def backup_path(name):
    """A backup's archive by its name. Refused: no such backup (deleted meanwhile, or a name that is none)."""
    try:
        return safe_name(name, core.BACKUPS, ".tar.gz")
    except NotFound:
        raise Refused(404, "backup_not_found", t("bak.gone"))


def delete(name):
    """Deletes a backup."""
    os.remove(backup_path(name))
    changed("backup_action:delete", name)


# How far a restore moves the rankings' change number past the live database's: more saves than a server takes in the time
# a restore takes, so that nothing the server kept before the restore, nor kept from the live database while the restore
# ran, has a number as high as the restored database's.
STAMP_MARGIN = 1_000_000


def board_stamp(con):
    """The rankings' change number in con (BoardStamp), 0 for a database without one."""
    try:
        row = con.execute("SELECT n FROM BoardStamp").fetchone()
    except sqlite3.OperationalError:
        # An older database, before the table: no number yet.
        return 0
    # The table without its row counts as 0, as the server's start makes the row with 0.
    return int(row[0]) if row and row[0] is not None else 0


def move_board_stamp(copy, live):
    """The restored copy's change number set past every number the live database has used. The server keeps each
    ranking with the number it was worked out at and takes it while the database's number is not higher
    (server/game/src/ranking.php, odq_kept()): the backup's own number, lower, let it go on showing the boards of before
    the restore. The copy has the table already: check_restorable() brought it up to date."""
    copy.execute("UPDATE BoardStamp SET n = MAX(n, ?) + ?", (live, STAMP_MARGIN))


def swap_in(restored):
    """The restored database in the live one's place. SQLite's online backup copies it into the live one, so the server
    keeps running and sees the restored data on its next request."""
    src, dst = sqlite3.connect(restored), sqlite3.connect(core.DB, timeout=10)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()


def restore_backup(name, path):
    """Puts an archive's database and added songs in place, as the page's Restore does. Returns what to say of it, in the
    page's words, [(tone, words)], and whether it was restored: the caller notes the change (a page in its request, the
    API's job when it ends). The caller holds _restoring."""
    # Unpacked beside the backups, where the archive itself is (WORK_PREFIXES): the database and every added song may be
    # larger than this service's /tmp, and a restore failed there saying the disk was full.
    try:
        work = work_folder(WORK_PREFIXES[1])
    except OSError as e:
        return [("bad", t("bak.not_restored", detail=why(e)))], False
    with work as tmp:
        try:
            with tarfile.open(path) as tar:
                member = next((m for m in tar.getmembers() if m.name == "dmtq.db3" and m.isfile()), None)
                if not member:
                    raise ValueError(tp("bak.no_db"))
                tar.extract(member, tmp)
                # Added songs, if the backup has them: plain files and folders under custom/ only.
                extra = [m for m in tar.getmembers() if (m.name == "custom" or m.name.startswith("custom/")) and ".." not in m.name
                         and (m.isfile() or m.isdir())]
                tar.extractall(tmp, members=extra)
            restored = os.path.join(tmp, "dmtq.db3")
            check_restorable(restored)
        except ValueError as e:
            return [("bad", t("bak.not_restored", detail=str(e)))], False
        except sqlite3.DatabaseError:
            return [("bad", t("bak.not_restored", detail=tp("bak.damaged")))], False
        except (tarfile.TarError, OSError, EOFError, zlib.error) as e:
            return [("bad", t("bak.not_restored", detail=why(e)))], False
        # The way back first. A live database too damaged to copy is the case a backup is for: kept as a file instead.
        saved = kept = None
        try:
            saved = make_backup("before-restore", protect=name)
        except (sqlite3.Error, OSError, tarfile.TarError) as e:
            if not (isinstance(e, sqlite3.DatabaseError) and database_is_damaged()):
                # Nothing has changed yet, and nothing changes without the way back.
                return [("bad", t("bak.not_saved", detail=why(e)))], False
            kept = set_damaged_aside()
        try:
            # Who is shown live is today's decision, not the backup's: an old backup must not start
            # broadcasting anyone. The switches and the broadcast settings as they are now go back in below. So are the
            # API's tokens: an old backup must not bring back one that was revoked, nor end one made since (the one that
            # asked for this restore). Tokens are made and revoked under tokens.LOCK: none comes or goes between this look
            # and the swap. The site's accounts too: an old backup must not bring back an account deleted since, nor an
            # old password, nor end an account made since. The chats' webhooks too, as they are now, under their own lock: an
            # old backup must not bring back one deleted since (its chat would hear from this server again), and nothing
            # the restored database's queue holds is sent again (webhooks.put).
            with tokens.LOCK, webhooks.LOCK:
                switches, settings, kept_tokens, kept_accounts, kept_hooks = [], [], [], [], []
                # The game's sign-ins of now (none from a live database set aside as damaged).
                kept_sign_ins = []
                # The live database's rankings' change number (0 when it is set aside as damaged and cannot be read).
                live_stamp = 0
                # Whether today's server has nothing of its own yet: no player and no account (a new PC), or its
                # database set aside as damaged. It then keeps the backup's webhooks, as it keeps the backup's accounts.
                empty = True
                if not kept:
                    with db() as con:
                        kept_sign_ins = sign_ins(con)
                        live_stamp = board_stamp(con)
                        recordings.live_table(con)
                        switches = con.execute("SELECT * FROM LiveSwitch").fetchall()
                        settings = sorted(recordings.setting_rows(con).items())
                        tokens.token_table(con)
                        kept_tokens = con.execute("SELECT * FROM ApiToken").fetchall()
                        # The table as the pages keep it (its guid column added to an older one), then every account.
                        auth.account_table(con)
                        kept_accounts = con.execute(f"SELECT {', '.join(auth.ACCOUNT_COLUMNS)} FROM SiteUser").fetchall()
                        kept_hooks = webhooks.kept(con)
                        # A server with webhooks, accounts or players of its own is no new one: its webhooks as they are
                        # now, none among them too (the owner deleted them, and their chats hear nothing more from here).
                        empty = not kept_hooks and not kept_accounts and not has_players(con)
                # Today's tokens and accounts go into the restored copy while it is still apart from the server: the
                # database that takes the live one's place has them from its first moment (a damaged one set aside
                # leaves no tokens).
                copy = sqlite3.connect(restored)
                try:
                    with copy:
                        tokens.put(copy, kept_tokens)
                        # Today's game sign-ins: every game signed in goes on signing as it did.
                        put_sign_ins(copy, kept_sign_ins)
                        # Today's webhooks, and the loop's memory and queue gone: its next look starts from the restored
                        # data as it is, sending nothing of it. A server with nothing of its own yet keeps the backup's
                        # webhooks instead (a move to a new PC keeps the chats the owner set), their queue gone all the
                        # same.
                        webhooks.put(copy, webhooks.kept(copy) if empty else kept_hooks)
                        # A server with no account (a new PC, or a damaged database set aside) has none to keep: the
                        # backup's accounts come with it then, or a move to a new PC would leave every player out.
                        if kept_accounts:
                            auth.put_accounts(copy, kept_accounts)
                        # Past the live number before the copy goes live: from the server's first look at it, no board
                        # it kept before is taken for the restored data's.
                        move_board_stamp(copy, live_stamp)
                finally:
                    copy.close()
                swap_in(restored)
            with db() as con:
                bring_schema_up_to_date(con)
                recordings.live_table(con)
                con.execute("DELETE FROM LiveSwitch")
                con.executemany("INSERT INTO LiveSwitch (guid, live, token, toast, toast_id, maint_seen, changed_at, playing, "
                                "pattern_id, play_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                [(r["guid"], r["live"], r["token"], r["toast"], r["toast_id"], r["maint_seen"], r["changed_at"],
                                  r["playing"], r["pattern_id"], r["play_at"]) for r in switches])
                # The settings as they were today, the backup's gone: a restore never turns broadcasts on.
                con.execute(recordings.SETTING_TABLE)
                con.execute("DELETE FROM LiveSetting")
                con.executemany("INSERT INTO LiveSetting (name, value) VALUES (?, ?)", settings)
        except (sqlite3.Error, OSError) as e:
            app.logger.exception("restore of %s failed", name)
            return [("bad", t("bak.restore_failed", detail=why(e), saved=saved or kept))], False
        restored_custom = os.path.join(tmp, "custom")
        if os.path.isdir(restored_custom):
            # The added songs, hidden flags and ids, and the song list made for them, under the songs' lock in one go: an
            # add or a hide on the Songs page, or a start's rebuild, waits until both are done (songs.put_back).
            not_rebuilt = songs.put_back(restored_custom)
            if not_rebuilt:
                # Without client data there is nothing to merge them with yet; the database is back all the same.
                app.logger.warning("restore: songs not rebuilt: %s", not_rebuilt)
    said = [("ok", t("bak.restored_damaged", name=name, kept=kept) if kept else t("bak.restored", name=name, saved=saved))]
    # The signing key stays this server's. A backup from another server (a move to a new PC)
    # needs its key, or its players' phones cannot update; only the CLI puts a key back.
    theirs = key_digest_in(path)
    if theirs and theirs != current_key_digest():
        # Where the key comes back from: Docker Compose's command line has restore --with-key; a host install and the
        # Windows bundle have no such command, so they are told of the key's folder in the archive instead.
        from . import setup
        said.append(("bad", t("bak.other_key_host" if setup.HOST_INSTALL else "bak.other_key", name=name)))
    return said, True

# A backup a day, by itself, while the owner has that on: only when something changed since the last one, and at most the
# latest few of these are kept. One thread, from the moment this service starts: nobody needs to open a page for it, as after
# the PC restarted by itself.
# Why the last look could not make one, for the status page; empty once one works.
_auto_failure = ""


def auto_backup_due(now, newest, last_change):
    """Is a daily backup due: the newest is a day old or more (or there is none), and the database has changed since."""
    return newest is None or (now - newest >= 86400 and last_change > newest)


def auto_backup_once():
    """One look: make the backup if it is due. Quietly: the page shows the result in its list."""
    if not core.settings().get("auto_backup"):
        return None
    made = [b for b in backup_files() if "-uploaded" not in b[0]]
    try:
        last_change = max(os.path.getmtime(core.DB + end) for end in ("", "-wal") if os.path.exists(core.DB + end))
    except (OSError, ValueError):
        return None
    if not auto_backup_due(time.time(), made[0][1] if made else None, last_change):
        return None
    # Not in the middle of a restore: that would be a backup of something half put back. The next look tries again.
    if not _restoring.acquire(blocking=False):
        return None
    try:
        name = make_backup("auto")
    finally:
        _restoring.release()
    autos = by_stamp(b[0] for b in backup_files() if b[0].endswith("-auto.tar.gz"))
    for old in autos[:-KEEP_AUTO_BACKUPS]:
        os.remove(os.path.join(core.BACKUPS, old))
    return name


def clear_partial_backups():
    """What a stopped service left of an archive it was writing, or of a backup's or a restore's work beside the backups
    (WORK_PREFIXES). Only old ones: `opendmtq backup` writes .part files too, and another of this service's processes may
    be at work."""
    try:
        for name in os.listdir(core.BACKUPS):
            path = os.path.join(core.BACKUPS, name)
            if time.time() - os.path.getmtime(path) <= 3600:
                continue
            if name.endswith(".part"):
                os.remove(path)
            elif name.startswith(WORK_PREFIXES) and os.path.isdir(path):
                # A folder with what it unpacked: all of it.
                shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def _auto_loop():
    global _auto_failure
    clear_partial_backups()
    while True:
        time.sleep(1800)
        try:
            auto_backup_once()
            _auto_failure = ""
        except Exception as e:  # pylint: disable=broad-except
            # The next look tries again; the status page says so, and when the newest backup is getting old.
            _auto_failure = why(e)
            app.logger.warning("automatic backup: %s", _auto_failure)

threading.Thread(target=_auto_loop, name="daily-backup", daemon=True).start()
