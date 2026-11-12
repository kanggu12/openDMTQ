<?php
/*
 * Prepares the database before the server starts: creates it on a first start, picks the journal mode the
 * disk allows, adds what later versions need (tables, indexes), and repairs what older versions or forged
 * results left behind. Safe to run at every start: every step does nothing when there is nothing to do.
 *
 * Usage: php bin/setup-db.php [database file]   (default: OPENDMTQ_DB, else /data/dmtq.db3)
 */

require_once __DIR__ . '/../src/config.php';

// The file named on the command line, else the server's own.
$path = $argv[1] ?? odq_db_path();

/*
 * The game's two tables, as earlier DMTQ servers made them (the column names and types are what the game's
 * data has always been read with): Member holds one row per account and phone, Play each player's best on
 * each chart. A new database gets them here; an existing one keeps its own.
 */
const GAME_TABLES = [
    'CREATE TABLE IF NOT EXISTS Member (id INTEGER, nickname NVARCHAR(255), guid VARCHAR(255), puid VARCHAR(255),
     udid TEXT, code TEXT, slot_item1 INTEGER, slot_item2 INTEGER, slot_item3 INTEGER, slot_item4 INTEGER)',
    'CREATE TABLE IF NOT EXISTS Play (pattern_id INTEGER, user_id INTEGER, score INTEGER, grade CHAR(1),
     isAllCombo CHAR(1), isPerfectPlay CHAR(1), judgement INTEGER)',
];

// The database's folder must be there and writable (the database, its journal and the probe below go there):
// otherwise one line that says so, rather than SQLite's own error, and the server does not start.
$dir = dirname($path);
if (!is_dir($dir) || !is_writable($dir)) {
    fwrite(STDERR, "opendmtq: cannot write the database's folder $dir; mount a writable folder there"
        . " (data/state with Docker Compose)\n");
    exit(1);
}

// A file that is missing or empty (an interrupted first start) is a new database.
$fresh = !is_file($path) || filesize($path) === 0;
if ($fresh) {
    // Built in a scratch file that replaces the target only when complete.
    @unlink("$path.new");
    $new = new SQLite3("$path.new");
    foreach (GAME_TABLES as $sql) {
        $new->exec($sql);
    }
    $new->close();
    rename("$path.new", $path);
    echo "opendmtq: created an empty database at " . basename(dirname($path)) . '/' . basename($path) . "\n";
}

/*
 * Write-ahead mode: readers no longer wait for a commit nor a commit for readers, and a save takes one wait for
 * the disk instead of several. Its shared memory file does not work on every disk (a folder of a Windows drive,
 * some network disks), and there a database in this mode fails on its first use: it is tried on a scratch
 * database in the same folder first. Anywhere it fails the database stays in (or returns to) the older mode,
 * which works everywhere. A restored database may come in either mode. With Litestream (Kubernetes) the
 * database is already in this mode, which it needs.
 */
$probe = dirname($path) . '/.wal-probe.db3';
// The scratch database and every file SQLite may leave next to it.
$clean = function () use ($probe) {
    foreach (['', '-wal', '-shm', '-journal'] as $end) {
        @unlink($probe . $end);
    }
};
$clean();
$works = false;
try {
    $a = @new SQLite3($probe);
    $a->enableExceptions(true);
    $works = $a->querySingle('PRAGMA journal_mode = WAL') === 'wal';
    if ($works) {
        $a->exec('CREATE TABLE t (x)');
        $a->exec('INSERT INTO t VALUES (1)');
        // A second handle must see it: that goes through the shared memory file.
        $b = new SQLite3($probe, SQLITE3_OPEN_READONLY);
        $b->enableExceptions(true);
        $works = (int)$b->querySingle('SELECT x FROM t') === 1;
        $b->close();
    }
    $a->close();
} catch (Throwable $e) {
    $works = false;
}
$clean();

$db = new SQLite3($path);
$db->busyTimeout(5000);
$mode = @$db->querySingle('PRAGMA journal_mode = ' . ($works ? 'WAL' : 'DELETE'));
if (!$works) {
    echo "opendmtq: this disk cannot use SQLite write-ahead mode; database mode: $mode\n";
}

// An older database has the game's tables already; these statements only add them where they are missing.
foreach (GAME_TABLES as $sql) {
    $db->exec($sql);
}

// Every saved play, for the monthly rankings, the achievements' dates and the web pages: the game's own table
// keeps only each player's best. A year of it is kept (below).
$db->exec('CREATE TABLE IF NOT EXISTS PlayLog (id INTEGER PRIMARY KEY, user_id INTEGER, pattern_id INTEGER,
           score INTEGER, grade TEXT, judgement INTEGER, is_record INTEGER, played_at INTEGER)');
$db->exec('CREATE INDEX IF NOT EXISTS PlayLog_time ON PlayLog (played_at)');
// When each player earned each achievement (MY PAGE): the save that earns one stores it, once. Apart from
// PlayLog, which keeps a year: an achievement once earned stays, with its date. Only the admin pages reset or
// delete the rows of a player. The same statement as ACHIEVEMENT_TABLE in the admin pages.
$db->exec('CREATE TABLE IF NOT EXISTS AchievementDate (user_id INTEGER NOT NULL, achievement_id INTEGER NOT NULL,
           earned_at INTEGER NOT NULL, PRIMARY KEY (user_id, achievement_id))');
$db->exec('CREATE INDEX IF NOT EXISTS Play_pattern ON Play (pattern_id, score)');

// Each player has one row per chart. Two saves at the same moment once made two, which the rankings summed:
// such rows become one, the best of each (the same as PLAY_MERGE in the admin pages, for a database restored
// while the server runs), and the unique index below keeps it so.
$db->exec('BEGIN IMMEDIATE');
$db->exec('CREATE TEMP TABLE PlayMerged AS
           SELECT p.pattern_id, p.user_id, MAX(p.score) AS score,
                  (SELECT q.grade FROM Play q WHERE q.pattern_id = p.pattern_id AND q.user_id = p.user_id
                    ORDER BY q.judgement DESC LIMIT 1) AS grade,
                  MAX(p.isAllCombo) AS isAllCombo, MAX(p.isPerfectPlay) AS isPerfectPlay, MAX(p.judgement) AS judgement
             FROM Play p WHERE p.pattern_id IS NOT NULL AND p.user_id IS NOT NULL
            GROUP BY p.pattern_id, p.user_id HAVING COUNT(*) > 1');
$merged = (int)$db->querySingle('SELECT COUNT(*) FROM PlayMerged');
$kept = true;
if ($merged) {
    $kept = $db->exec('DELETE FROM Play WHERE (pattern_id, user_id) IN (SELECT pattern_id, user_id FROM PlayMerged)')
        && $db->exec('INSERT INTO Play (pattern_id, user_id, score, grade, isAllCombo, isPerfectPlay, judgement)
                      SELECT pattern_id, user_id, score, grade, isAllCombo, isPerfectPlay, judgement FROM PlayMerged');
}
@$db->exec('DROP TABLE PlayMerged');
// All of it or nothing: the removal alone would lose the scores.
$db->exec($kept ? 'COMMIT' : 'ROLLBACK');
if ($merged && $kept) {
    echo "opendmtq: merged $merged player and chart pair(s) that had more than one score row\n";
}
$db->exec('CREATE UNIQUE INDEX IF NOT EXISTS Play_one ON Play (pattern_id, user_id)');
// Every in-game ranking adds up scores per player: from this index alone, without reading the table. It does
// what the earlier index on the player alone did too.
$db->exec('CREATE INDEX IF NOT EXISTS Play_board ON Play (user_id, pattern_id, score)');
$db->exec('DROP INDEX IF EXISTS Play_user');
// Every monthly ranking, the game's and the site's, adds up each player's best per chart since the month began: from
// this index alone, without reading the table once per play (the player, the time, the chart and the score are all in
// it). It also does what the index on the player and the time did, which it replaces: under a new name, as one of the
// old name would stay as it was made.
$db->exec('CREATE INDEX IF NOT EXISTS PlayLog_board ON PlayLog (user_id, played_at, pattern_id, score)');
$db->exec('DROP INDEX IF EXISTS PlayLog_user');
// A chart's own ranking, and the admin pages' plays per song and last played: from this index, not the whole log.
$db->exec('CREATE INDEX IF NOT EXISTS PlayLog_chart ON PlayLog (pattern_id, played_at)');
// Every save works out the player's achievements twice, before it and after it (src/achievement.php,
// odq_achievements_held()): their clears counted chart by chart and their best rows with the grade and the two flags.
// From these two indexes alone, in the order they are counted in: without them each save read the table once for
// every play the player had and every chart they had played (on a million plays, 19 ms a save against 1.6).
$db->exec('CREATE INDEX IF NOT EXISTS PlayLog_clears ON PlayLog (user_id, pattern_id, grade)');
$db->exec('CREATE INDEX IF NOT EXISTS Play_held ON Play (user_id, pattern_id, score, grade, isAllCombo, isPerfectPlay)');
$db->exec('CREATE INDEX IF NOT EXISTS Member_id ON Member (id)');
$db->exec('CREATE INDEX IF NOT EXISTS Member_udid ON Member (udid)');
// The live view: the switch per player (the admin writes it), the upload key of the phone, the notice waiting
// to be shown, and whether the player is in a song (the game's requests keep that, src/live.php). The same
// statement as LIVE_TABLE in the admin pages.
$db->exec('CREATE TABLE IF NOT EXISTS LiveSwitch (guid INTEGER PRIMARY KEY, live INTEGER NOT NULL DEFAULT 0,
           token TEXT, toast TEXT, changed_at INTEGER, playing INTEGER NOT NULL DEFAULT 0,
           pattern_id INTEGER, play_at INTEGER)');
// The owner's settings for broadcasts as a whole (whether there are any, what new players start with, the quality): a
// name and its value per row, which the admin pages' Broadcasts page writes and portal/live_lib.php reads. The same
// statement as SETTING_TABLE in the admin pages.
$db->exec('CREATE TABLE IF NOT EXISTS LiveSetting (name TEXT PRIMARY KEY, value TEXT NOT NULL)');
// The accounts of the site, made on the Accounts page of the admin pages and checked by the site's sign-in:
// every page of it is behind that. The same statement as ACCOUNT_TABLE there (which also adds guid).
$db->exec("CREATE TABLE IF NOT EXISTS SiteUser (name TEXT PRIMARY KEY COLLATE NOCASE, pass TEXT NOT NULL,
           note TEXT NOT NULL DEFAULT '', admin INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
           signed_in_at INTEGER, off INTEGER NOT NULL DEFAULT 0)");
// The admin pages' API tokens, made on their Accounts page: only a hash of each, with whose it is. The game and the site
// never read it. The same statement as TOKEN_TABLE in the admin pages (tokens.py).
$db->exec('CREATE TABLE IF NOT EXISTS ApiToken (id TEXT PRIMARY KEY, name TEXT NOT NULL, scope TEXT NOT NULL,
           hash TEXT NOT NULL, admin TEXT NOT NULL COLLATE NOCASE, owner INTEGER NOT NULL DEFAULT 0,
           admin_since INTEGER, created_at INTEGER NOT NULL, used_at INTEGER)');
// Earlier versions logged through triggers (best score only); the save code does it now.
$db->exec('DROP TRIGGER IF EXISTS PlayLog_insert');
$db->exec('DROP TRIGGER IF EXISTS PlayLog_update');
// A year of plays is kept.
$db->exec('DELETE FROM PlayLog WHERE played_at < ' . (time() - 365 * 86400));
// Scores and accuracies outside what a real play gives (stored before the save code clamped them, or restored
// from such a backup) are capped the same way: forged scores made the rankings' sums overflow. The rankings
// cap them as they read too; this keeps every page sane.
$capped = 0;
foreach (['Play', 'PlayLog'] as $t) {
    if (@$db->exec("UPDATE $t SET score = MIN(MAX(score, 0), 2147483647) WHERE score > 2147483647 OR score < 0")) {
        $capped += $db->changes();
    }
    @$db->exec("UPDATE $t SET judgement = MIN(MAX(judgement, 0), 1000) WHERE judgement > 1000 OR judgement < 0");
}
if ($capped) {
    echo "opendmtq: capped $capped score(s) outside 0 to 2147483647 (forged results)\n";
}
// Players' names that are no UTF-8, which another program can have written into the database of an older server (the
// game's own requests only ever bring UTF-8): the game gets U+FFFD in place of their bad bytes (src/rpc.php), the site an
// empty name. Each is stored as UTF-8 once: read as CP949, the Korean encoding older Korean programs wrote, when it is
// that, else with U+FFFD in place of each bad byte, as the game shows it.
$broken = [];
$names = @$db->query('SELECT rowid, nickname FROM Member WHERE nickname IS NOT NULL');
while ($names && ($row = $names->fetchArray(SQLITE3_ASSOC))) {
    // A blob or a number reads as its bytes or digits: only text that is no UTF-8 needs anything.
    if (!mb_check_encoding((string)$row['nickname'], 'UTF-8')) {
        $broken[$row['rowid']] = (string)$row['nickname'];
    }
}
if ($broken) {
    // What mb_scrub() puts in place of a bad byte: the mark JSON_INVALID_UTF8_SUBSTITUTE puts there too.
    mb_substitute_character(0xFFFD);
    $fixed = $korean = 0;
    $write = $db->prepare('UPDATE Member SET nickname = :name WHERE rowid = :row');
    // All of them together, waiting out the game's writers (the busy timeout above).
    $db->exec('BEGIN IMMEDIATE');
    foreach ($broken as $rowid => $name) {
        $cp949 = mb_check_encoding($name, 'CP949');
        $write->bindValue(':name', $cp949 ? mb_convert_encoding($name, 'UTF-8', 'CP949') : mb_scrub($name, 'UTF-8'), SQLITE3_TEXT);
        $write->bindValue(':row', $rowid, SQLITE3_INTEGER);
        // Counted only when written, so that the line below says what happened.
        if ($write->execute()) {
            $fixed++;
            $korean += $cp949 ? 1 : 0;
        }
        $write->reset();
    }
    $db->exec('COMMIT');
    echo "opendmtq: stored $fixed player name(s) that were not UTF-8 as UTF-8, $korean of them from CP949\n";
}
$db->close();
