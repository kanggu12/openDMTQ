<?php
/*
 * The keyboard's mark, as the game server keeps it: tests/game/protocol.sh runs this inside the throwaway server, after the
 * contract. The PC client's player sends X-OpenDMTQ-Keys: 1 with a save when a lane key was pressed during the song, and
 * no such header otherwise. The play's own row in PlayLog keeps the mark, and the player's best row in Play keeps the mark
 * of the play that set its score: a new best by touch clears it, a new best by keys sets it, a worse play or a tie leaves
 * it. Only the value 1 marks. A database from before the mark gets the column at the next start, every row a play by
 * touch, and a change of the column still raises the rankings' change number.
 *
 * Usage: php tests/game/keys.php <database file> <base address of the server>      (exit status 0 when every check passed)
 */

// The server's own code: the image's, or a host install's (OPENDMTQ_APP names its server/ folder). Its start step, and the
// key the game signs its requests with.
$app = getenv('OPENDMTQ_APP') ?: '/opt/opendmtq';
$setup = "$app/game/bin/setup-db.php";
require_once "$app/game/src/config.php";
[$_, $path, $base] = $argv;

// One line per check, as protocol.py prints them; the count of failures decides the exit status.
$failures = 0;
function check(string $name, bool $ok, string $detail = ''): void
{
    global $failures;
    if (!$ok) {
        $failures++;
    }
    echo ($ok ? 'PASS ' : 'FAIL ') . $name . ($detail !== '' && !$ok ? " | $detail" : '') . "\n";
}

// A player no other check uses, with an account as the game's login makes one (a save for an id without one is refused).
const KEYS_PLAYER = 9101;
$db = new SQLite3($path);
// The server is running on the same database: wait for its writers rather than fail.
$db->busyTimeout(5000);
$db->exec("INSERT INTO Member (id, nickname, guid, puid, udid, code) VALUES (" . KEYS_PLAYER . ", 'Kay', '" . KEYS_PLAYER
    . "', '" . KEYS_PLAYER . "', 'protocol-keys', 'keyscode01')");

/*
 * A play saved as the result screen sends it, signed as the game signs it: $notes notes at 100 % and $breaks breaks, on
 * $chart. $keys: the X-OpenDMTQ-Keys header's value, or null for none. The save's result, or null when it answered none.
 */
function save(string $base, int $chart, int $notes, int $breaks, ?string $keys): ?array
{
    // Place 1 the breaks, 12 the notes judged 100 %; the counts in between none (game.php reads 1 to 12).
    $stat = array_fill(0, 13, 0);
    [$stat[1], $stat[12]] = [$breaks, $notes];
    $body = json_encode([['id' => 1, 'method' => 'game.savePlayResult',
        'params' => [KEYS_PLAYER, $chart, $stat, $notes, 0, [0, 0, 0], [0, 0, 0], 't']]]);
    $headers = "Content-Type: application/json\r\nFp: " . md5(OPENDMTQ_SECRET_KEY . $body) . "\r\n";
    // The PC client's header, when this play had one.
    if ($keys !== null) {
        $headers .= "X-OpenDMTQ-Keys: $keys\r\n";
    }
    $context = stream_context_create(['http' => ['method' => 'POST', 'content' => $body, 'header' => $headers,
        'ignore_errors' => true, 'timeout' => 15]]);
    $reply = json_decode((string)@file_get_contents("$base/DMQ/rpc", false, $context), true);
    return $reply[0]['result'] ?? null;
}

/* The mark of the player's newest play on $chart (PlayLog) and of their best there (Play), as [log, best]; null for none. */
function marks(SQLite3 $db, int $chart): array
{
    $g = KEYS_PLAYER;
    $log = $db->querySingle("SELECT keys FROM PlayLog WHERE user_id = $g AND pattern_id = $chart ORDER BY id DESC LIMIT 1");
    $best = $db->querySingle("SELECT keys FROM Play WHERE user_id = $g AND pattern_id = $chart");
    return [$log, $best];
}

// The two columns, as every start leaves them: whole numbers that are never null, 0 when nothing says otherwise.
foreach (['Play', 'PlayLog'] as $table) {
    $column = null;
    $columns = $db->query("PRAGMA table_info($table)");
    while ($columns && ($c = $columns->fetchArray(SQLITE3_ASSOC))) {
        $column = $c['name'] === 'keys' ? $c : $column;
    }
    check("$table has the keyboard's column: a whole number, never null, 0 unless a save says otherwise",
        $column !== null && $column['type'] === 'INTEGER' && (int)$column['notnull'] === 1 && $column['dflt_value'] === '0',
        json_encode($column));
}

// Charts of song 5 of the stand-in songs (make_content.php numbers nine charts a song): no other check plays them.
[$a, $b, $c] = [37, 38, 39];
// A first play with the keyboard: 100 notes at 100 %, 65,000.
$first = save($base, $a, 100, 0, '1');
check('a first play with the header X-OpenDMTQ-Keys: 1 is saved, its play and its best marked',
    ($first['is_new_record'] ?? null) === true && marks($db, $a) === [1, 1], json_encode([$first, marks($db, $a)]));
// Worse, by touch: 90 notes at 100 % and 10 breaks.
$worse = save($base, $a, 90, 10, null);
check('a worse play without the header is marked as played by touch, and the best keeps the keyboard\'s mark',
    ($worse['is_new_record'] ?? null) === false && marks($db, $a) === [0, 1], json_encode([$worse, marks($db, $a)]));
// The same score again by touch: no new best, so the best stays the keyboard's, which got there first.
$tie = save($base, $a, 100, 0, null);
check('a tie by touch leaves the best to the keyboard\'s play that got there first',
    ($tie['is_new_record'] ?? null) === false && marks($db, $a) === [0, 1], json_encode([$tie, marks($db, $a)]));
// Better by touch: 200 notes at 100 %, 85,000, over the keyboard's 65,000.
$better = save($base, $a, 200, 0, null);
check('a new best by touch clears the best\'s mark', ($better['is_new_record'] ?? null) === true && marks($db, $a) === [0, 0],
    json_encode([$better, marks($db, $a)]));
// The other way round on another chart: a first play by touch, then a better one with the keyboard.
save($base, $b, 90, 10, null);
$by_keys = save($base, $b, 100, 0, '1');
check('a new best with the keyboard after one by touch marks the best',
    ($by_keys['is_new_record'] ?? null) === true && marks($db, $b) === [1, 1], json_encode([$by_keys, marks($db, $b)]));
// The header with another value is no keyboard's: 0, and a word.
$zero = save($base, $c, 100, 0, '0');
$word = save($base, $c, 100, 0, 'yes');
$logged = $db->querySingle('SELECT GROUP_CONCAT(keys) FROM (SELECT keys FROM PlayLog WHERE user_id = ' . KEYS_PLAYER
    . " AND pattern_id = $c ORDER BY id)");
check('a header with another value than 1 marks nothing', $zero !== null && $word !== null && $logged === '0,0'
    && marks($db, $c) === [0, 0], json_encode([$logged, marks($db, $c)]));
// Every play of the player: one row each, the keyboard's two marked, in the order they were made.
$all = $db->querySingle('SELECT GROUP_CONCAT(keys) FROM (SELECT keys FROM PlayLog WHERE user_id = ' . KEYS_PLAYER . ' ORDER BY id)');
check('every play is logged with its own mark', $all === '1,0,0,0,0,1,0,0', (string)$all);
$db->close();

// A database as the release before this mark left it: the tables without the column, a best, two plays, the rankings'
// change number with its triggers. In a scratch folder of the container, with the server's own start step.
$old = sys_get_temp_dir() . '/keys-before.db3';
@unlink($old);
$o = new SQLite3($old);
$o->exec('CREATE TABLE Member (id INTEGER, nickname NVARCHAR(255), guid VARCHAR(255), puid VARCHAR(255), udid TEXT, code TEXT,
          slot_item1 INTEGER, slot_item2 INTEGER, slot_item3 INTEGER, slot_item4 INTEGER)');
$o->exec('CREATE TABLE Play (pattern_id INTEGER, user_id INTEGER, score INTEGER, grade CHAR(1), isAllCombo CHAR(1),
          isPerfectPlay CHAR(1), judgement INTEGER)');
$o->exec('CREATE TABLE PlayLog (id INTEGER PRIMARY KEY, user_id INTEGER, pattern_id INTEGER, score INTEGER, grade TEXT,
          judgement INTEGER, is_record INTEGER, played_at INTEGER)');
$o->exec("INSERT INTO Member (id, nickname, guid, udid) VALUES (5, 'Old', '5', 'old-phone')");
$o->exec("INSERT INTO Play VALUES (1, 5, 300, 'A', 'N', 'N', 900)");
$o->exec("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at)
          VALUES (5, 1, 200, 'B', 800, 1, " . (time() - 60) . "), (5, 1, 300, 'A', 900, 1, " . time() . ')');
$o->close();
exec('php ' . escapeshellarg($setup) . ' ' . escapeshellarg($old) . ' 2>&1', $said, $code);
$o = new SQLite3($old);
$read = [$o->querySingle('SELECT GROUP_CONCAT(keys) FROM Play'), $o->querySingle('SELECT GROUP_CONCAT(keys) FROM (SELECT keys FROM PlayLog ORDER BY id)')];
check('a database from before the mark gets the column at the next start, every best and play read as one by touch',
    $code === 0 && $read === ['0', '0,0'], "exit $code, " . json_encode([$read, $said]));
// The rankings' change number follows a change of the mark too: the boards kept with it are worked out again.
$was = (int)$o->querySingle('SELECT n FROM BoardStamp');
$o->exec('UPDATE Play SET keys = 1');
$o->exec('UPDATE PlayLog SET keys = 1 WHERE id = 2');
check("a change of the mark raises the rankings' change number, in Play and in PlayLog",
    (int)$o->querySingle('SELECT n FROM BoardStamp') === $was + 2, $was . ' -> ' . $o->querySingle('SELECT n FROM BoardStamp'));
$o->close();
// A second start leaves it as it is: the column is there once.
exec('php ' . escapeshellarg($setup) . ' ' . escapeshellarg($old) . ' 2>&1', $said, $code);
$o = new SQLite3($old, SQLITE3_OPEN_READONLY);
check('the next start leaves the column and the marks as they are', $code === 0
    && $o->querySingle('SELECT GROUP_CONCAT(keys) FROM Play') === '1', "exit $code");
$o->close();
@unlink($old);

exit($failures ? 1 : 0);
