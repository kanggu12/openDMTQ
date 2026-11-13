<?php
/*
 * The keyboard's mark, as the game server keeps it: tests/game/protocol.sh runs this inside the throwaway server, after the
 * contract. The PC client's player sends X-OpenDMTQ-Keys: 1 with a save when a lane key was pressed during the song, and
 * no such header otherwise. The play's own row in PlayLog keeps the mark, and the player's best row in Play keeps the mark
 * of the play that set its score: a new best by touch clears it, a new best by keys sets it, a worse play or a tie leaves
 * it. Only the value 1 marks. The game itself sees no difference: the same replies, rankings and own scores, while the
 * database alone tells the two plays apart. A database from before the mark gets the column at the next start, every row
 * a play by touch, and a change of the column still raises the rankings' change number.
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
 * One call of the game's RPC, signed as the game signs it: [HTTP status, the call's reply ({result, error, id}) or null when
 * it answered none]. $keys: the X-OpenDMTQ-Keys header's value, or null for none.
 */
function rpc(string $base, string $method, array $params, ?string $keys = null): array
{
    // One call in a list, as the game sends its batches, signed over the body alone.
    $body = json_encode([['id' => 1, 'method' => $method, 'params' => $params]]);
    $headers = "Content-Type: application/json\r\nFp: " . md5(OPENDMTQ_SECRET_KEY . $body) . "\r\n";
    // The PC client's header, when this request had one.
    if ($keys !== null) {
        $headers .= "X-OpenDMTQ-Keys: $keys\r\n";
    }
    // A POST whose answer is read whatever its status.
    $context = stream_context_create(['http' => ['method' => 'POST', 'content' => $body, 'header' => $headers,
        'ignore_errors' => true, 'timeout' => 15]]);
    $raw = @file_get_contents("$base/DMQ/rpc", false, $context);
    // The status from the reply's first line ("HTTP/1.1 200 OK"), 0 when nothing came back.
    $status = isset($http_response_header[0]) ? (int)(explode(' ', $http_response_header[0])[1] ?? 0) : 0;
    // The first call's reply, as the batch answers in order.
    $reply = json_decode((string)$raw, true);
    return [$status, $reply[0] ?? null];
}

/*
 * A play saved as the result screen sends it, signed as the game signs it: $notes notes at 100 % and $breaks breaks, on
 * $chart, by $player. $keys: the X-OpenDMTQ-Keys header's value, or null for none. The save's result, or null when it
 * answered none.
 */
function save(string $base, int $chart, int $notes, int $breaks, ?string $keys, int $player = KEYS_PLAYER): ?array
{
    // Place 1 the breaks, 12 the notes judged 100 %; the counts in between none (game.php reads 1 to 12).
    $stat = array_fill(0, 13, 0);
    [$stat[1], $stat[12]] = [$breaks, $notes];
    // The save's parameters as the result screen sends them: the player, the chart, the counts, the max combo and the rest.
    [, $reply] = rpc($base, 'game.savePlayResult', [$player, $chart, $stat, $notes, 0, [0, 0, 0], [0, 0, 0], 't'], $keys);
    return $reply['result'] ?? null;
}

/*
 * A save's result as the game reads it, but for when each achievement was earned (reg_date): two saves a moment apart can
 * fall in two seconds, which the client shows and nothing else reads.
 */
function as_read(?array $result): ?array
{
    // Every achievement the save earned, without the moment it was earned.
    foreach ($result['new_achievements'] ?? [] as $i => $earned) {
        unset($result['new_achievements'][$i]['reg_date']);
    }
    return $result;
}

/* The mark of $player's newest play on $chart (PlayLog) and of their best there (Play), as [log, best]; null for none. */
function marks(SQLite3 $db, int $chart, int $player = KEYS_PLAYER): array
{
    // The newest play's row, then the best's.
    $log = $db->querySingle("SELECT keys FROM PlayLog WHERE user_id = $player AND pattern_id = $chart ORDER BY id DESC LIMIT 1");
    $best = $db->querySingle("SELECT keys FROM Play WHERE user_id = $player AND pattern_id = $chart");
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
check("a worse play without the header is marked as played by touch, and the best keeps the keyboard's mark",
    ($worse['is_new_record'] ?? null) === false && marks($db, $a) === [0, 1], json_encode([$worse, marks($db, $a)]));
// The same score again by touch: no new best, so the best stays the keyboard's, which got there first.
$tie = save($base, $a, 100, 0, null);
check("a tie by touch leaves the best to the keyboard's play that got there first",
    ($tie['is_new_record'] ?? null) === false && marks($db, $a) === [0, 1], json_encode([$tie, marks($db, $a)]));
// Better by touch: 200 notes at 100 %, 85,000, over the keyboard's 65,000.
$better = save($base, $a, 200, 0, null);
check("a new best by touch clears the best's mark", ($better['is_new_record'] ?? null) === true && marks($db, $a) === [0, 0],
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

// The game sees no difference. Two new players, the older account first, play song 6's 2LINE NORMAL (chart 46) the same
// way, one with the header and one without, then a worse play of each with the header the other way round. Their replies
// are the same, and so are their rows on the game's rankings and their own scores; the database alone tells them apart.
// Their ids, the keyboard's player the older account, and the chart, which no other check plays.
[$keyed, $touched, $song6] = [9102, 9103, 46];
// Their accounts, as the game's login makes them: a save for an id without one is refused.
foreach ([$keyed => 'Kei', $touched => 'Tou'] as $guid => $name) {
    $db->exec("INSERT INTO Member (id, nickname, guid, puid, udid, code) VALUES ($guid, '$name', '$guid', '$guid', 'protocol-keys-$guid', 'keys$guid')");
}
// 100 notes at 100 %, each with the ALL COMBO and PERFECT PLAY bonuses: 65,000.
[$status_k, $by_keys] = rpc($base, 'game.savePlayResult', [$keyed, $song6, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100], 100, 0, [0, 0, 0], [0, 0, 0], 't'], '1');
[$status_t, $by_touch] = rpc($base, 'game.savePlayResult', [$touched, $song6, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100], 100, 0, [0, 0, 0], [0, 0, 0], 't'], null);
check('a save with X-OpenDMTQ-Keys: 1 is answered as the same save without it, and only that play is marked',
    $status_k === 200 && $status_t === 200 && isset($by_keys['result'], $by_touch['result'])
    && ($by_keys['error'] ?? null) === null && ($by_touch['error'] ?? null) === null
    && as_read($by_keys['result']) === as_read($by_touch['result']) && ($by_keys['result']['is_new_record'] ?? null) === true
    && marks($db, $song6, $keyed) === [1, 1] && marks($db, $song6, $touched) === [0, 0],
    json_encode([$status_k, $status_t, $by_keys['error'] ?? null, $by_touch['error'] ?? null, marks($db, $song6, $keyed), marks($db, $song6, $touched)]));
// Worse, the header the other way round: 90 notes at 100 % and 10 breaks, no new best.
$again_k = save($base, $song6, 90, 10, null, $keyed);
$again_t = save($base, $song6, 90, 10, '1', $touched);
check('and a worse play with it as one without it, each play marked as its request said and each best as it was',
    as_read($again_k) === as_read($again_t) && ($again_k['is_new_record'] ?? null) === false
    && marks($db, $song6, $keyed) === [0, 1] && marks($db, $song6, $touched) === [1, 0],
    json_encode([$again_k['is_new_record'] ?? null, $again_t['is_new_record'] ?? null, marks($db, $song6, $keyed), marks($db, $song6, $touched)]));
// The game's ranking of song 6's 2LINE, its first five places as [rank, name, score], and each one's own scores but for
// their own id: the two tie at 65,000, the older account first, as any two players.
[, $ranked] = rpc($base, 'game.getLineScoreRangeWithLevel', [6, 3, 1, 5]);
$board = array_map(fn($r) => [$r['rank'], $r['display_name'], $r['score']], $ranked['result']['scores'] ?? []);
// Each one's own scores, their id taken out: all the rest must be the same.
$own = [];
foreach ([$keyed, $touched] as $guid) {
    [, $mine] = rpc($base, 'game.getOwnPatternScore', [$guid]);
    $own[] = array_map(fn($r) => array_diff_key($r, ['guid' => 0]), $mine['result'] ?? []);
}
check("the game's rankings and own scores show the keyboard's play as any other, the database alone telling the two apart",
    $board === [[1, 'Kei', 65000], [2, 'Tou', 65000]] && $own[0] === $own[1] && $own[0] !== []
    && $db->querySingle("SELECT GROUP_CONCAT(keys) FROM (SELECT keys FROM Play WHERE pattern_id = $song6 AND user_id IN ($keyed, $touched) ORDER BY user_id)") === '1,0',
    json_encode([$board, $own]));
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
