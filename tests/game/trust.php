<?php
/*
 * What a call may change of a player's game state, and whose game may make it: tests/game/protocol.sh runs this inside the
 * throwaway server, after tests/game/state.php, with the stand-in catalog it wrote (custom/catalog.json: chart 61 costs 350
 * MAX POINT, product 50001 is a pack of 2,500 MAX POINT for 10 Q, the note 90002 nobody has at first). Each player signs in
 * as the game does (the platform's login by the phone's device id, then the game's own login) and signs its requests with
 * the key that login gave it:
 *
 *   - a banned player's call is refused whatever form its id takes ("9402x", " 9402", 9402.0), nothing bought;
 *   - unlimited currency: a pack of MAX POINT bought with Q gives nothing, as it takes nothing;
 *   - game.setSlotItem equips the player's own items only: one nobody gave them, one the owner took, one no catalog has
 *     leave their slot empty;
 *   - the game's login takes only an access token the platform's login handed out, and gives each sign-in a key of its own;
 *   - a chart's start, which takes its price, and a save are taken only signed with the key of that very player's sign-in:
 *     not unsigned, not with the key every player once had, not with another player's;
 *   - a save earns MAX POINT and experience once for the play its sign-in started, and nothing without one;
 *   - the transfer code's two calls, the name and the items equipped are the player's own game's alone; a transfer code is
 *     random, never one made from the player's number (such a code is replaced at a start, and never shown or taken), and
 *     moves a phone onto the player under the player's name;
 *   - the live view takes a song's start and its end from the player's own game alone;
 *   - a player's number is never handed out again, and a sign-in whose account is gone signs nobody in.
 *
 * Usage: php tests/game/trust.php <database file> <base address of the server>      (exit status 0 when every check passed)
 */

$app = getenv('OPENDMTQ_APP') ?: '/opt/opendmtq';
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

$db = new SQLite3($path);
// The server is running on the same database: wait for its writers rather than fail.
$db->busyTimeout(5000);
// Players no other check uses, each with an account as the platform's login makes one, by a device id of its own.
foreach ([9401 => 'Ana', 9402 => 'Ben', 9403 => 'Cy', 9404 => 'Dee', 9405 => 'Fin', 9406 => 'Gus', 9407 => 'Hob'] as $id => $name) {
    $db->exec("INSERT INTO Member (id, nickname, guid, puid, udid, code) VALUES ($id, '$name', '$id', '$id', 'trust-$id', 'trustcode$id')");
}

/* A POST of $body to the server's own address with $headers: [status, body]. */
function post(string $url, string $body, array $headers): array
{
    $context = stream_context_create(['http' => ['method' => 'POST', 'content' => $body, 'ignore_errors' => true, 'timeout' => 15,
        'header' => implode("\r\n", $headers) . "\r\n"]]);
    $raw = @file_get_contents($url, false, $context);
    // The status from the reply's first line ("HTTP/1.1 200 OK"), 0 when nothing came back.
    $status = isset($http_response_header[0]) ? (int)(explode(' ', $http_response_header[0])[1] ?? 0) : 0;
    return [$status, (string)$raw];
}

/*
 * A phone's sign-in as the game makes it: the platform's login with the phone's device id, then the game's own login with
 * the access token it gave. [the player id, the key the login reply gave the game to sign with], or [0, ''].
 */
function sign_in(string $base, string $udid): array
{
    [, $raw] = post("$base/api/accounts/v3/global/login_dmq", "app_id=576&udid=$udid&device_cd=ANDROID",
        ['Content-Type: application/x-www-form-urlencoded']);
    $token = json_decode($raw, true)['value']['access_token'] ?? '';
    // The game's login, signed with the empty key the game has before its first login, as the game sends it.
    [, $reply] = batch($base, '', [['user.loginV2', [$token, ' ', '', '1.3.4', 'ANDROID', 'KR']]]);
    $result = $reply[0]['result'] ?? [];
    return [(int)($result['guid'] ?? 0), (string)($result['SECRET_KEY'] ?? '')];
}

/* The calls of one request as the game sends them, signed with $key: [HTTP status, the replies ({result, error, id}) in order]. */
function batch(string $base, string $key, array $calls): array
{
    $list = [];
    foreach ($calls as $i => [$method, $params]) {
        $list[] = ['id' => $i, 'method' => $method, 'params' => $params];
    }
    $body = json_encode($list);
    [$status, $raw] = post("$base/DMQ/rpc", $body, ['Content-Type: application/json', 'Fp: ' . md5($key . $body)]);
    return [$status, json_decode($raw, true) ?: []];
}

/* One call, signed with $key: its reply ({result, error, id}), or null. */
function call(string $base, string $key, string $method, array $params): ?array
{
    return batch($base, $key, [[$method, $params]])[1][0] ?? null;
}

/* A player's state as the admin pages keep it (game.py write_state): MAX, Q, experience, their own unlimited switch. */
function keep(SQLite3 $db, int $guid, int $mpoint, int $qpoint, int $exp, int $unlimited = 0): void
{
    $db->exec("INSERT INTO PlayerState (guid, mpoint, qpoint, exp, unlimited, changed_at) VALUES ($guid, $mpoint, $qpoint, $exp, $unlimited, " . time() . ")
               ON CONFLICT (guid) DO UPDATE SET mpoint = excluded.mpoint, qpoint = excluded.qpoint, exp = excluded.exp, unlimited = excluded.unlimited");
}

/* What the player keeps, as the database has it: "MAX/Q". */
function kept(SQLite3 $db, int $guid): string
{
    return (string)$db->querySingle("SELECT mpoint || '/' || qpoint FROM PlayerState WHERE guid = $guid");
}

// The players' sign-ins, before any ban: each one's own key.
$keys = [];
foreach ([9401, 9402, 9403, 9404, 9405, 9406, 9407] as $guid) {
    [$got, $key] = sign_in($base, "trust-$guid");
    $keys[$guid] = $key;
    check("a player signs in as the game does, and the login gives the game a key to sign with ($guid)", $got === $guid && $key !== '',
        json_encode([$got, $key]));
}

// ------------------------------------------------------------------ GAME-100: a ban, whatever form the id takes

keep($db, 9402, 1000, 1000, 0);
$db->exec("INSERT INTO PlayerBan (guid, reason, since, until, by) VALUES (9402, 'Made-up scores', " . time() . ", NULL, 'admin')");
foreach (['9402x', ' 9402', 9402.0, '9402'] as $form) {
    // A purchase of the pack of MAX POINT for Q, then the balance, in one request as the game sends a purchase.
    [$status, $r] = batch($base, $keys[9402], [['shop.buyProductByQPoint', [$form, 50001, 0]], ['game.getUserAsset', [$form]]]);
    check('GAME-100 a banned player\'s call is refused with the id as ' . json_encode($form) . ': the purchase and the balance alike',
        $status === 200 && ($r[0]['error']['code'] ?? null) === 'SVC.05403' && ($r[1]['error']['code'] ?? null) === 'SVC.05403',
        json_encode([$status, $r[0]['error'] ?? $r[0]['result'] ?? null, $r[1]['error'] ?? null]));
}
check('GAME-100 nothing was bought for the banned player and nothing was paid', kept($db, 9402) === '1000/1000'
    && (int)$db->querySingle('SELECT COUNT(*) FROM PlayerPurchase WHERE guid = 9402') === 0,
    kept($db, 9402) . ' ' . $db->querySingle('SELECT COUNT(*) FROM PlayerPurchase WHERE guid = 9402'));

// ------------------------------------------------------------------ GAME-101: unlimited currency and a pack of MAX POINT

keep($db, 9403, 1000, 1000, 0, 1);
for ($i = 0; $i < 3; $i++) {
    call($base, $keys[9403], 'shop.buyProductByQPoint', [9403, 50001, 0]);
}
check('GAME-101 unlimited: a pack of MAX POINT bought with Q takes nothing and gives nothing, each purchase kept with nothing paid',
    kept($db, 9403) === '1000/1000' && $db->querySingle("SELECT COUNT(*) || ' ' || SUM(paid) FROM PlayerPurchase WHERE guid = 9403") === '3 0',
    kept($db, 9403) . ' ' . $db->querySingle("SELECT COUNT(*) || ' ' || SUM(paid) FROM PlayerPurchase WHERE guid = 9403"));
$db->exec('UPDATE PlayerState SET unlimited = 0 WHERE guid = 9403');
$asset = call($base, $keys[9403], 'game.getUserAsset', [9403])['result'] ?? [];
check('GAME-101 unlimited off again: the game is told the balance the player had before',
    ($asset['mpoint'] ?? null) === 1000 && ($asset['amt_total'] ?? null) === '1000', json_encode($asset));
// Without unlimited the pack is paid for and gives its amount, as before.
call($base, $keys[9403], 'shop.buyProductByQPoint', [9403, 50001, 0]);
check('GAME-101 without unlimited the pack takes its 10 Q and gives its 2,500 MAX POINT', kept($db, 9403) === '3500/990', kept($db, 9403));

// ------------------------------------------------------------------ GAME-102: equipping the player's own items only

// 30001 and 100001 everyone has (the catalog's items); 90001 the owner gave Dee; 30002 the owner took from Dee; 90002 nobody
// has at first; 123456 no catalog has.
$db->exec("INSERT INTO PlayerItem (guid, item_id, owned, how, at) VALUES (9404, 90001, 1, 'given', " . time() . "), (9404, 30002, 0, 'taken', " . time() . ")");
$slots = fn() => $db->querySingle("SELECT coalesce(slot_item1, 'null') || ',' || coalesce(slot_item2, 'null') || ',' || coalesce(slot_item3, 'null') || ',' || coalesce(slot_item4, 'null') FROM Member WHERE guid = '9404'");
$set = call($base, $keys[9404], 'game.setSlotItem', [9404, 30001, 0, 90001, 100001]);
check("GAME-102 the player's own items are equipped as sent: one everyone has, one given, an empty slot",
    $slots() === '30001,null,90001,100001' && ($set['result'] ?? null) === ['slot_item1' => 30001, 'slot_item2' => 0, 'slot_item3' => 90001, 'slot_item4' => 100001],
    $slots() . ' ' . json_encode($set));
$set = call($base, $keys[9404], 'game.setSlotItem', [9404, 30002, 123456, 90002, '100001']);
check('GAME-102 an item the owner took, one no catalog has and one nobody gave leave their slots empty, said so in the reply',
    $slots() === 'null,null,null,100001' && ($set['result'] ?? null) === ['slot_item1' => null, 'slot_item2' => null, 'slot_item3' => null, 'slot_item4' => '100001'],
    $slots() . ' ' . json_encode($set));
$equipped = call($base, $keys[9404], 'game.getUserAsset', [9404])['result'] ?? [];
check('GAME-102 the game is told the slots as they were kept', array_key_exists('slot_item1', $equipped) && array_key_exists('slot_item3', $equipped)
    && [$equipped['slot_item1'], $equipped['slot_item3'], $equipped['slot_item4'] ?? 'x'] === [null, null, 100001], json_encode($equipped));

// ------------------------------------------------------------------ GAME-103: the game's login, and each sign-in's own key

check('GAME-103 each sign-in gets a key of its own, none of them the key every player was once given',
    count(array_unique($keys)) === count($keys) && !in_array(OPENDMTQ_SECRET_KEY, $keys, true) && strlen($keys[9405]) === 32, json_encode($keys));
// A token the platform's login never handed out: Fin's puid with a random part of somebody's choosing.
$made_up = '9405|576|IPHONE|KR|' . str_repeat('0', 40) . '|' . time() . '000';
$refused = call($base, '', 'user.loginV2', [$made_up, ' ', '', '1.3.4', 'ANDROID', 'KR']);
check("GAME-103 the game's login refuses an access token the platform's login did not hand out, with a code the game does not know",
    ($refused['error']['code'] ?? null) === 'SVC.05401' && ($refused['result'] ?? null) === null, json_encode($refused));
// Another account's real token with Fin's puid put in front: no token of Fin's either.
[, $raw] = post("$base/api/accounts/v3/global/login_dmq", 'app_id=576&udid=trust-9406&device_cd=ANDROID', ['Content-Type: application/x-www-form-urlencoded']);
$gus_token = (string)(json_decode($raw, true)['value']['access_token'] ?? '');
$swapped = call($base, '', 'user.loginV2', ['9405' . substr($gus_token, strpos($gus_token, '|')), ' ', '', '1.3.4', 'ANDROID', 'KR']);
check("GAME-103 nor another account's token with this account's id put in it",
    ($swapped['error']['code'] ?? null) === 'SVC.05401', json_encode($swapped));
// The game logs in twice at its start with the same token: the same key both times.
$again = call($base, '', 'user.loginV2', [$gus_token, ' ', '', '1.3.4', 'ANDROID', 'KR'])['result'] ?? [];
$twice = call($base, $again['SECRET_KEY'] ?? '', 'user.loginV2', [$gus_token, ' ', '', '1.3.4', 'ANDROID', 'KR'])['result'] ?? [];
check('GAME-103 a second login with the same token gives the same key, signed with it as the game signs the second',
    ($again['SECRET_KEY'] ?? '') !== '' && ($again['SECRET_KEY'] ?? '') === ($twice['SECRET_KEY'] ?? null), json_encode([$again, $twice]));
$keys[9406] = (string)($again['SECRET_KEY'] ?? '');

// ------------------------------------------------------------------ GAME-104: a chart's start is the player's own game's

// Chart 61 costs 350 MAX POINT (the stand-in catalog). Fin holds 1,000.
keep($db, 9405, 1000, 1000, 644);
$start = json_encode([['id' => 0, 'method' => 'game.getPreviewPlayInfo', 'params' => [9405, 61]]]);
$tries = [
    'unsigned' => [],
    'signed with the key every player was once given' => ['Fp: ' . md5(OPENDMTQ_SECRET_KEY . $start)],
    "signed with another player's own key" => ['Fp: ' . md5($keys[9406] . $start)],
];
foreach ($tries as $how => $fp) {
    // Three times each, as anyone who reaches the address could.
    $statuses = [];
    for ($i = 0; $i < 3; $i++) {
        [$statuses[]] = post("$base/DMQ/rpc", $start, array_merge(['Content-Type: application/json'], $fp));
    }
    check("GAME-104 a chart's start for another player's id, $how, is refused whole and takes nothing",
        $statuses === [403, 403, 403] && kept($db, 9405) === '1000/1000', json_encode($statuses) . ' ' . kept($db, 9405));
}
$own = call($base, $keys[9405], 'game.getPreviewPlayInfo', [9405, 61]);
$token = (string)($own['result']['game_token'] ?? '');
check("GAME-104 the player's own game starts it: the price taken once, and a token of the play's own",
    kept($db, 9405) === '650/1000' && strlen($token) === 36 && ctype_xdigit($token), kept($db, 9405) . ' ' . json_encode($own['error'] ?? null));

// ------------------------------------------------------------------ GAME-105: a save earns once, for the play started

/* A save as the result screen sends it, by $guid on $chart with the play's token: 100 notes at 100 %. [status, its reply]. */
function save_with(string $base, string $key, int $guid, int $chart, string $token): array
{
    [$status, $r] = batch($base, $key, [['game.savePlayResult', [$guid, $chart, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100], 100, 0, [0, 0, 0], [0, 0, 0], $token]]]);
    return [$status, $r[0] ?? null];
}
// The play started above, saved by Fin's own game: NEW RECORD, 150 MAX POINT and 10 experience, the price paid once.
[$status, $saved] = save_with($base, $keys[9405], 9405, 61, $token);
check('GAME-105 the play started, saved: a new record, 150 MAX POINT and 10 experience, the price paid once',
    $status === 200 && ($saved['result']['is_new_record'] ?? null) === true && ($saved['result']['mpoint'] ?? null) === 150
    && ($saved['result']['exp'] ?? null) === 10 && kept($db, 9405) === '800/1000', json_encode([$status, $saved]) . ' ' . kept($db, 9405));
// The same save again (a retry, or a copy of it): kept as a play, nothing earned.
[$status, $again] = save_with($base, $keys[9405], 9405, 61, $token);
check('GAME-105 the same save again is kept as a play and earns nothing', $status === 200 && ($again['result']['is_success'] ?? null) === true
    && ($again['result']['mpoint'] ?? null) === 0 && ($again['result']['exp'] ?? null) === 0 && kept($db, 9405) === '800/1000',
    json_encode($again) . ' ' . kept($db, 9405));
// A save of no play started (as the finding's made-up saves were): kept, nothing earned; 64 of them in one request too.
$many = [];
for ($i = 0; $i < 64; $i++) {
    $many[] = ['game.savePlayResult', [9405, 55, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100], 100, 0, [0, 0, 0], [0, 0, 0], 'x']];
}
[$status, $r] = batch($base, $keys[9405], $many);
check('GAME-105 64 saves of no play started, in one request, earn nothing', $status === 200 && count($r) === 64
    && kept($db, 9405) === '800/1000' && (int)$db->querySingle('SELECT exp FROM PlayerState WHERE guid = 9405') === 654,
    "$status " . count($r) . ' ' . kept($db, 9405));
// Two starts, then the first one's save: a sign-in starts one play at a time, the last; its save earns once.
$first = (string)(call($base, $keys[9405], 'game.getPreviewPlayInfo', [9405, 55])['result']['game_token'] ?? '');
$second = (string)(call($base, $keys[9405], 'game.getPreviewPlayInfo', [9405, 55])['result']['game_token'] ?? '');
[, $old] = save_with($base, $keys[9405], 9405, 55, $first);
[, $new] = save_with($base, $keys[9405], 9405, 55, $second);
check("GAME-105 of two starts only the last one's save earns, once", $first !== $second && ($old['result']['mpoint'] ?? null) === 0
    && ($new['result']['mpoint'] ?? null) === 150 && kept($db, 9405) === '950/1000', json_encode([$old['result']['mpoint'] ?? null, $new['result']['mpoint'] ?? null]) . ' ' . kept($db, 9405));
// Another player's game, naming Fin: refused whole, whatever its token.
$third = (string)(call($base, $keys[9405], 'game.getPreviewPlayInfo', [9405, 55])['result']['game_token'] ?? '');
[$status] = save_with($base, $keys[9406], 9405, 55, $third);
check("GAME-105 a save for another player, signed with one's own key, is refused whole", $status === 403 && kept($db, 9405) === '950/1000',
    "$status " . kept($db, 9405));
// A player the owner deleted while their game was in: the save is theirs, and handled without a popup as before.
$hob_token = (string)(call($base, $keys[9407], 'game.getPreviewPlayInfo', [9407, 55])['result']['game_token'] ?? '');
$db->exec("DELETE FROM Member WHERE guid = '9407'");
[$status, $gone] = save_with($base, $keys[9407], 9407, 55, $hob_token);
check('GAME-105 the save of a player deleted while their game was in is handled without a popup (SVC.05008) and kept nowhere',
    $status === 200 && ($gone['error']['code'] ?? null) === 'SVC.05008' && (int)$db->querySingle('SELECT COUNT(*) FROM Play WHERE user_id = 9407') === 0,
    json_encode([$status, $gone]));

// ------------------------------------------------------------------ GAME-140: the transfer code, the name and the items are the player's own game's

/* The calls of one request with no signature at all, as anyone who reaches the address can send them: [status, replies]. */
function unsigned(string $base, array $calls): array
{
    $list = [];
    foreach ($calls as $i => [$method, $params]) {
        $list[] = ['id' => $i, 'method' => $method, 'params' => $params];
    }
    [$status, $raw] = post("$base/DMQ/rpc", json_encode($list), ['Content-Type: application/json']);
    return [$status, json_decode($raw, true) ?: []];
}

/* What the database has of a player's account, by their first row: "name/code/slots" (each slot's item or null). */
function account(SQLite3 $db, int $guid): string
{
    return (string)$db->querySingle("SELECT nickname || '/' || coalesce(code, 'null') || '/' || coalesce(slot_item1, 'null') || ','
        || coalesce(slot_item2, 'null') FROM Member WHERE guid = '$guid' ORDER BY rowid LIMIT 1");
}

/* A transfer code made from a number, as servers before 0.11.3 made every code: the last ten hex digits of MD5("CODE_" . n). */
function code_of_number(int $number, string $prefix = 'CODE_'): string
{
    return substr(md5($prefix . $number), -10);
}

// Ivy and Jon: two phones of their own, new accounts as the platform's login makes them, each signed in as the game does.
[$ivy, $ivy_key] = sign_in($base, 'trust-ivy');
[$jon, $jon_key] = sign_in($base, 'trust-jon');
$db->exec("UPDATE Member SET nickname = 'Ivy', slot_item1 = 30001 WHERE guid = '$ivy'");
$db->exec("UPDATE Member SET nickname = 'Jon' WHERE guid = '$jon'");
$ivy_before = account($db, $ivy);
$jon_code = (string)$db->querySingle("SELECT code FROM Member WHERE guid = '$jon'");
// Each of the four calls naming Ivy, sent by someone other than Ivy's game: unsigned, and signed with Jon's own key.
$others = [
    'user.getConnectUuid' => [$ivy, 'ANDROID'],
    'user.setNickname' => [$ivy, 'renamed-by-anyone'],
    'game.setSlotItem' => [$ivy, 30002, 0, 0, 0],
    'user.setConnectUuid' => [$ivy, $jon_code, 'ANDROID'],
];
foreach ($others as $method => $params) {
    [$open, $open_reply] = unsigned($base, [[$method, $params]]);
    [$jons, $jons_reply] = batch($base, $jon_key, [[$method, $params]]);
    check("GAME-140 $method naming another player is refused whole, unsigned and signed with one's own key: nothing shown, nothing changed",
        $open === 403 && $open_reply === [] && $jons === 403 && $jons_reply === [] && account($db, $ivy) === $ivy_before,
        json_encode([$open, $open_reply, $jons, $jons_reply, account($db, $ivy), $ivy_before]));
}
// Ivy's own game: her code shown, her name and her items changed.
$shown = call($base, $ivy_key, 'user.getConnectUuid', [$ivy, 'ANDROID'])['result']['uuid'] ?? null;
$named = call($base, $ivy_key, 'user.setNickname', [$ivy, 'Ivy2'])['result'] ?? null;
$slots = call($base, $ivy_key, 'game.setSlotItem', [$ivy, 30002, 0, 0, 0])['result']['slot_item1'] ?? null;
check("GAME-140 the player's own game is shown the code, picks the name and equips the items",
    $shown === explode('/', $ivy_before)[1] && $named === true && $slots === 30002 && account($db, $ivy) === "Ivy2/$shown/30002,null",
    json_encode([$shown, $named, $slots, account($db, $ivy)]));

// ------------------------------------------------------------------ GAME-141: a transfer code is random, never made from the number

// A third new account, through the old SDK's path too (whose codes once lacked the underscore).
[, $raw] = post("$base/accounts/v3/global/login_dmq", 'app_id=576&udid=trust-old-path&device_cd=IPHONE', ['Content-Type: application/x-www-form-urlencoded']);
$old_path = (int)explode('|', (string)(json_decode($raw, true)['value']['access_token'] ?? ''))[0];
$codes = [];
foreach ([$ivy, $jon, $old_path] as $guid) {
    $codes[$guid] = (string)$db->querySingle("SELECT code FROM Member WHERE guid = '$guid'");
}
$made = array_filter($codes, fn($code, $guid) => in_array($code, [code_of_number($guid), code_of_number($guid, 'CODE')], true), ARRAY_FILTER_USE_BOTH);
check('GAME-141 a new account\'s transfer code is ten lowercase hex digits of its own, none made from its number (both logins\' paths)',
    $old_path > 0 && count(array_unique($codes)) === 3 && !$made && count(array_filter($codes, fn($c) => preg_match('/^[0-9a-f]{10}$/', $c) === 1)) === 3,
    json_encode([$codes, array_keys($made)]));

// ------------------------------------------------------------------ GAME-142: the account move, by the player's own games

// Ivy's old phone shows her code; Kim's new phone (a new account) types it: Kim's phone becomes Ivy at its next sign-in.
[$kim, $kim_key] = sign_in($base, 'trust-kim');
$moved = call($base, $kim_key, 'user.setConnectUuid', [$kim, $shown, 'ANDROID']);
[$now, $now_key] = sign_in($base, 'trust-kim');
$asset = call($base, $now_key, 'game.getUserAsset', [$ivy])['result'] ?? [];
check("GAME-142 a new phone's own game types the code its owner was shown, and at its next sign-in it is that player, signing as them",
    ($moved['result']['status'] ?? null) === 'SUCCESS' && $now === $ivy && $now_key !== '' && array_key_exists('mpoint', $asset),
    json_encode([$moved, $now, $asset]));
// The name the game shows on its top bar, which it asks by its own account (the phone's puid, Kim's number): the player's.
$shown_name = call($base, $now_key, 'user.getUsersByPuid', [[(string)$kim], ['display_name']])['result'] ?? null;
check("GAME-142 and the moved phone shows the player's name, as the rankings do, not the name its own account had",
    $shown_name === [['display_name' => 'Ivy2']], json_encode($shown_name));
// Jon, with a code worked out from Ivy's number as every code once was, signed with his own key: no move.
$tried = [];
foreach ([code_of_number($ivy), code_of_number($ivy, 'CODE')] as $guess) {
    $tried[] = call($base, $jon_key, 'user.setConnectUuid', [$jon, $guess, 'ANDROID'])['error']['code'] ?? 'taken';
}
[$jon_now] = sign_in($base, 'trust-jon');
check('GAME-142 a code worked out from a player\'s number is no code: refused (SVC.05001), and the phone stays its own player',
    $tried === ['SVC.05001', 'SVC.05001'] && $jon_now === $jon, json_encode([$tried, $jon_now]));

// ------------------------------------------------------------------ GAME-143: codes made from numbers, replaced at a start and never taken

// Three accounts as a database of an earlier server has them: two codes made from the number (with and without the
// underscore), one of another form. Lee and Mae sign in as the game does.
[$lee, $lee_key] = sign_in($base, 'trust-lee');
[$mae] = sign_in($base, 'trust-mae');
[$ned] = sign_in($base, 'trust-ned');
$db->exec("UPDATE Member SET code = '" . code_of_number($lee) . "' WHERE guid = '$lee'");
$db->exec("UPDATE Member SET code = '" . code_of_number($mae, 'CODE') . "' WHERE guid = '$mae'");
$db->exec("UPDATE Member SET code = 'nedscode01' WHERE guid = '$ned'");
// Before any start: Lee's own game is shown a new random code, never the one made from the number; Mae's is taken by nobody.
$lee_shown = call($base, $lee_key, 'user.getConnectUuid', [$lee, 'ANDROID'])['result']['uuid'] ?? null;
$mae_taken = call($base, $kim_key, 'user.setConnectUuid', [$kim, code_of_number($mae, 'CODE'), 'ANDROID'])['error']['code'] ?? 'taken';
check('GAME-143 before a start, the player\'s own game is shown a random code in place of one made from the number, and nobody can type such a code',
    is_string($lee_shown) && preg_match('/^[0-9a-f]{10}$/', $lee_shown) === 1 && $lee_shown !== code_of_number($lee)
    && (string)$db->querySingle("SELECT code FROM Member WHERE guid = '$lee'") === $lee_shown && $mae_taken === 'SVC.05001',
    json_encode([$lee_shown, $mae_taken]));
// The next start of the server (its start step, as at every start): each code made from a number replaced, the other kept.
$db->exec("UPDATE Member SET code = '" . code_of_number($lee) . "' WHERE guid = '$lee'");
exec('php ' . escapeshellarg("$app/game/bin/setup-db.php") . ' ' . escapeshellarg($path) . ' 2>&1', $said, $code);
$after = [];
foreach ([$lee, $mae, $ned] as $guid) {
    $after[$guid] = (string)$db->querySingle("SELECT code FROM Member WHERE guid = '$guid'");
}
check('GAME-143 a start gives each account whose code was made from its number a random one, says how many, and keeps any other code',
    $code === 0 && preg_match('/^[0-9a-f]{10}$/', $after[$lee]) === 1 && $after[$lee] !== code_of_number($lee)
    && preg_match('/^[0-9a-f]{10}$/', $after[$mae]) === 1 && $after[$mae] !== code_of_number($mae, 'CODE') && $after[$ned] === 'nedscode01'
    && (bool)preg_grep('/new random transfer code/', $said), json_encode([$code, $after, $said]));

// ------------------------------------------------------------------ GAME-144: the live view follows the player's own game

// Pia: in no song. A chart's address asked by anyone (unsigned), as the game asks it right after a start.
[$pia, $pia_key] = sign_in($base, 'trust-pia');
$playing = fn() => (string)$db->querySingle("SELECT coalesce(max(playing), 0) || ' ' || coalesce(max(pattern_id), 0) FROM LiveSwitch WHERE guid = $pia");
[$status] = unsigned($base, [['game.getPatternUrl', [$pia, 61, 'n', 'ANDROID']]]);
check('GAME-144 a chart\'s address, asked unsigned for a player, puts nobody in a song', $status === 200 && $playing() === '0 0', "$status " . $playing());
// Her own game starts a chart: in a song.
call($base, $pia_key, 'game.getPreviewPlayInfo', [$pia, 1]);
$in = $playing();
// A minute into the song, a menu call for her from anyone else, unsigned and signed with Jon's key: still in it.
$db->exec("UPDATE LiveSwitch SET play_at = play_at - 60 WHERE guid = $pia");
unsigned($base, [['game.getUserAsset', [$pia]]]);
batch($base, $jon_key, [['game.getUserAsset', [$pia]]]);
$still = $playing();
// Her own game's next menu call after the song: out of it.
call($base, $pia_key, 'game.getUserAsset', [$pia]);
check("GAME-144 the player's own start puts them in a song, and only their own game's next call after it takes them out",
    $in === '1 1' && $still === '1 1' && $playing() === '0 1', json_encode([$in, $still, $playing()]));

// ------------------------------------------------------------------ GAME-145: a player's number is never handed out again

// Quinn, the newest player, with a sign-in of their game; then their account gone (as the Players page deletes a player, or a
// database of before left it without its sign-ins going): the next new phone's number is past Quinn's.
[$quinn] = sign_in($base, 'trust-quinn');
[, $raw] = post("$base/api/accounts/v3/global/login_dmq", 'app_id=576&udid=trust-quinn&device_cd=ANDROID', ['Content-Type: application/x-www-form-urlencoded']);
$quinn_token = (string)(json_decode($raw, true)['value']['access_token'] ?? '');
$db->exec("DELETE FROM Member WHERE guid = '$quinn'");
[$next] = sign_in($base, 'trust-after-quinn');
check('GAME-145 the newest player gone, a new phone gets a number past theirs, and the highest number handed out is kept',
    $quinn > 0 && $next === $quinn + 1 && (int)@$db->querySingle('SELECT MAX(last) FROM MemberNumber') === $next,
    json_encode([$quinn, $next, @$db->querySingle('SELECT MAX(last) FROM MemberNumber')]));
// Quinn's sign-in of before, its account gone: the game's login refuses it, and makes no account with Quinn's number.
$refused = call($base, '', 'user.loginV2', [$quinn_token, ' ', '', '1.3.4', 'ANDROID', 'KR']);
check("GAME-145 a sign-in whose account is gone is refused by the game's login (SVC.05401), no account made with its number",
    ($refused['error']['code'] ?? null) === 'SVC.05401' && (int)$db->querySingle("SELECT COUNT(*) FROM Member WHERE guid = '$quinn'") === 0,
    json_encode([$refused, $db->querySingle("SELECT COUNT(*) FROM Member WHERE guid = '$quinn'")]));

exit($failures ? 1 : 0);
