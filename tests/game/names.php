<?php
/*
 * Players' names that are no UTF-8, as the database of an older server can hold them (another program wrote them, a
 * Korean one in CP949 for one): tests/game/protocol.sh runs this inside the throwaway server, after the contract. The
 * start batch of a phone that sees such a name in a ranking still comes back whole, as JSON, with U+FFFD in place of
 * each bad byte (one such name once emptied the reply for everybody who saw it); the next start's setup-db.php then
 * stores each name as UTF-8: from CP949 when it reads as that, else with U+FFFD in place of the bad bytes.
 *
 * Usage: php tests/game/names.php <database file> <base address of the server>      (exit status 0 when every check passed)
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

// Two players no other check uses: 홍길동 as CP949 writes it, and a name that ends in a byte no text has.
const CP949 = 9001;
const BROKEN = 9002;
$names = [CP949 => "\xC8\xAB\xB1\xE6\xB5\xBF", BROKEN => "Name\xC0"];
$db = new SQLite3($path);
// The server is running on the same database: wait for its writers rather than fail.
$db->busyTimeout(5000);
$member = $db->prepare('INSERT INTO Member (id, nickname, guid, puid, udid, code) VALUES (:id, :name, :guid, :guid, :udid, :code)');
$play = $db->prepare('INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at)
                      VALUES (:id, 1, 1000, \'F\', 100, 1, :at)');
foreach ($names as $id => $name) {
    $member->bindValue(':id', $id, SQLITE3_INTEGER);
    // Text with the bytes as they are: SQLite keeps them, as it kept them for the older server.
    $member->bindValue(':name', $name, SQLITE3_TEXT);
    $member->bindValue(':guid', (string)$id, SQLITE3_TEXT);
    $member->bindValue(':udid', "protocol-name-$id", SQLITE3_TEXT);
    // A transfer code, as every account has one: the start batch asks for it.
    $member->bindValue(':code', substr(md5("protocol-name-$id"), -10), SQLITE3_TEXT);
    $member->execute();
    $member->reset();
    // A play of this month: the player is on this month's TOTAL ranking, which every start batch lists.
    $play->bindValue(':id', $id, SQLITE3_INTEGER);
    $play->bindValue(':at', time(), SQLITE3_INTEGER);
    $play->execute();
    $play->reset();
}
$db->close();

/*
 * The start batch of the player with the broken name, as a phone sends it after its login, signed as the game signs it
 * (its shop calls need that): [HTTP status, the body, the body as JSON or null].
 */
function start_batch(string $base): array
{
    $g = BROKEN;
    $calls = [['game.getLineTopRankWithLevel', [0, 1, 20, [$g]]], ['game.getAchievementCount', []], ['board.getNoticeList', ['US', 0, 4]],
        ['user.getConnectUuid', [$g, 'ANDROID']], ['memo.getMemoList', [$g, 0, 50]], ['game.getUserAsset', [$g]], ['game.getOwnSongList', [$g]],
        ['shop.getOwnItemList', [$g]], ['game.getOwnAchievementList', [$g]], ['game.getOwnQuestList', [$g]], ['game.getOwnPatternScore', [$g]],
        ['shop.getUnlockedProductList', [$g]], ['game.getFirstResourceSongList', []], ['user.getUsersByPuid', [[(string)$g], ['display_name']]]];
    $list = [];
    foreach ($calls as $i => [$method, $params]) {
        $list[] = ['id' => $i, 'method' => $method, 'params' => $params];
    }
    $body = json_encode($list);
    // The answer whatever its status (ignore_errors), and its status line.
    $context = stream_context_create(['http' => ['method' => 'POST', 'content' => $body, 'ignore_errors' => true, 'timeout' => 15,
        'header' => "Content-Type: application/json\r\nFp: " . md5(OPENDMTQ_SECRET_KEY . $body) . "\r\n"]]);
    $answer = (string)@file_get_contents("$base/DMQ/rpc", false, $context);
    // PHP puts the answer's header lines here, its status line first.
    $status = preg_match('#^HTTP/\S+ (\d+)#', $http_response_header[0] ?? '', $m) ? (int)$m[1] : 0;
    return [$status, $answer, json_decode($answer, true)];
}

/* The names a reply gives the two players, by guid: the TOTAL ranking's (first call) and the player's own (last call). */
function names_in(array $reply): array
{
    $out = [];
    foreach ($reply[0]['result']['ranks'] ?? [] as $row) {
        if (in_array($row['guid'], [CP949, BROKEN], true)) {
            $out[$row['guid']] = $row['display_name'];
        }
    }
    $out['own'] = $reply[13]['result'][0]['display_name'] ?? null;
    return $out;
}

/* True when the batch came back as it must: 200, a JSON list of its 14 replies, none of them an error. */
function whole(array $batch): bool
{
    [$status, , $reply] = $batch;
    return $status === 200 && is_array($reply) && array_is_list($reply) && count($reply) === 14
        && !array_filter($reply, fn($r) => ($r['error'] ?? null) !== null);
}

$batch = start_batch($base);
check('a start batch that lists a name that is no UTF-8 comes back whole, as JSON', whole($batch),
    "HTTP $batch[0], " . strlen($batch[1]) . ' bytes: ' . substr($batch[1], 0, 120));
// Each bad byte becomes U+FFFD: what the game shows is the name with a mark where it lost a letter.
$seen = is_array($batch[2]) ? names_in($batch[2]) : [];
check('the name goes out with U+FFFD in place of the bad byte, in the ranking and as the player\'s own',
    ($seen[BROKEN] ?? null) === "Name\u{FFFD}" && $seen['own'] === "Name\u{FFFD}" && is_string($seen[CP949] ?? null), json_encode($seen));

// The next start: the server's own step, which runs before every start.
exec('php ' . escapeshellarg($setup) . ' ' . escapeshellarg($path) . ' 2>&1', $said, $code);
$db = new SQLite3($path, SQLITE3_OPEN_READONLY);
$stored = [];
foreach ([CP949, BROKEN] as $id) {
    $stored[$id] = $db->querySingle('SELECT nickname FROM Member WHERE id = ' . $id);
}
$db->close();
check('the next start stores a name in CP949 as UTF-8, and another with U+FFFD in place of its bad byte, and says so',
    $code === 0 && $stored === [CP949 => '홍길동', BROKEN => "Name\u{FFFD}"]
    && in_array('opendmtq: stored 2 player name(s) that were not UTF-8 as UTF-8, 1 of them from CP949', $said, true),
    // The stored bytes in hex: text that is no UTF-8 cannot be written as JSON.
    "exit $code, stored " . json_encode(array_map(fn($v) => $v === null ? null : bin2hex($v), $stored)) . ', said '
    . json_encode($said, JSON_INVALID_UTF8_SUBSTITUTE));
$batch = start_batch($base);
$seen = is_array($batch[2]) ? names_in($batch[2]) : [];
check('then the ranking shows the CP949 name as it was meant', whole($batch) && ($seen[CP949] ?? null) === '홍길동', json_encode($seen));

exit($failures ? 1 : 0);
