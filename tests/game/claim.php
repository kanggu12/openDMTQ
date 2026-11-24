<?php
/*
 * The PC client's link of a site account to the PC's game player (client.php?claim, at the launcher's first PLAY):
 * tests/game/protocol.sh runs this inside the throwaway server, after the contract, on its database and state folder, at
 * its own address.
 *
 *   - an account linked to no player, signed in, names the id its PC's game signs in by: linked to that player, said
 *     once as made now, then as linked already, and the link in the admin pages' log of changes;
 *   - another account naming the same player is refused (the player has an account), and keeps no player;
 *   - an id no player plays by, one of no form, the server's own check account's: nobody;
 *   - a banned player, and the owner's account (kept in .env, linked to no player), are never linked;
 *   - not signed in: refused as every signed-in answer is; asked without a POST: refused;
 *   - the account's records (client.php?records) are its player's from then on.
 *
 * Usage: php tests/game/claim.php <database file> <base address of the server>      (exit status 0 when every check passed)
 */

$app = getenv('OPENDMTQ_APP') ?: '/opt/opendmtq';
// The site's own sign-in code: the owner's file beside the database (odq_state_dir()).
require_once "$app/portal/auth.php";
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

/* A request to the server's own address, redirects not followed: [status, the reply's headers, body]. */
function visit(string $method, string $url, array $fields = [], string $cookie = ''): array
{
    $headers = ['Content-Type: application/x-www-form-urlencoded'];
    if ($cookie !== '') {
        $headers[] = "Cookie: $cookie";
    }
    $context = stream_context_create(['http' => ['method' => $method, 'content' => http_build_query($fields), 'ignore_errors' => true,
        'timeout' => 15, 'follow_location' => 0, 'header' => implode("\r\n", $headers) . "\r\n"]]);
    $raw = @file_get_contents($url, false, $context);
    // The status from the reply's first line ("HTTP/1.1 200 OK"), 0 when nothing came back.
    $status = isset($http_response_header[0]) ? (int)(explode(' ', $http_response_header[0])[1] ?? 0) : 0;
    return [$status, $http_response_header ?? [], (string)$raw];
}

/* The PC client's sign-in (client.php?signin) as the launcher makes it: the site's cookie it sets, as "name=value". */
function sign_in(string $base, string $user, string $password): string
{
    [, $headers] = visit('POST', "$base/opendmtq/client.php?signin", ['user' => $user, 'password' => $password]);
    foreach ($headers as $h) {
        if (preg_match('/^Set-Cookie:\s*(opendmtq_dl=[^;]+)/i', $h, $m) && $m[1] !== 'opendmtq_dl=') {
            return $m[1];
        }
    }
    return '';
}

/* client.php?claim as the launcher asks it: [status, the answer]. */
function claim(string $base, string $cookie, string $device, string $method = 'POST'): array
{
    [$status, , $body] = visit($method, "$base/opendmtq/client.php?claim", ['device' => $device], $cookie);
    return [$status, json_decode($body, true) ?: []];
}

/* The account's player as the accounts' table keeps it (null for none). */
function linked_to(SQLite3 $db, string $name): ?int
{
    $q = $db->prepare('SELECT guid FROM SiteUser WHERE name = :name');
    $q->bindValue(':name', $name, SQLITE3_TEXT);
    $row = $q->execute()->fetchArray(SQLITE3_ASSOC);
    return $row && $row['guid'] !== null ? (int)$row['guid'] : null;
}

$db = new SQLite3($path);
// The server is running on the same database: wait for its writers rather than fail.
$db->busyTimeout(5000);
$columns = [];
$r = $db->query('PRAGMA table_info(SiteUser)');
while ($row = $r->fetchArray(SQLITE3_ASSOC)) {
    $columns[] = $row['name'];
}
if (!in_array('guid', $columns, true)) {
    $db->exec('ALTER TABLE SiteUser ADD COLUMN guid INTEGER');
}
// Players no other check uses, as the platform login makes them (a new player's blank nickname), each with the id its
// game signs in by, the form the PC's game keeps (sixteen hex digits): one to link, one banned.
$db->exec("INSERT INTO Member (id, nickname, guid, puid, udid, code) VALUES (9611, ' ', '9611', '9611', '0a1b2c3d4e5f6071', 'claimcode1')");
$db->exec("INSERT INTO Member (id, nickname, guid, puid, udid, code) VALUES (9612, 'Banned PC', '9612', '9612', '0a1b2c3d4e5f6072', 'claimcode2')");
$db->exec("INSERT INTO PlayerBan (guid, reason, since, until, by) VALUES (9612, 'Made-up scores', " . time() . ', NULL, ' . "'admin')");
// Accounts linked to no player, as the setup's Players step and the Accounts page make them.
foreach (['claimer', 'second', 'third'] as $name) {
    $salt = bin2hex(random_bytes(16));
    $hash = 'pbkdf2_sha256$1000$' . $salt . '$' . hash_pbkdf2('sha256', 'claimpass', (string)hex2bin($salt), 1000, 64);
    $db->exec("INSERT OR REPLACE INTO SiteUser (name, pass, note, admin, created_at, off) VALUES ('$name', '$hash', '', 0, " . time() . ', 0)');
}
$state = odq_state_dir();
$log = "$state/changes.log";
$before = is_file($log) ? count(file($log)) : 0;

// ------------------------------------------------------------------ WIN-440: an account with no player and its PC's player

$cookie = sign_in($base, 'claimer', 'claimpass');
[$status, $answer] = claim($base, $cookie, '0a1b2c3d4e5f6071');
check("WIN-440 the PC client's first PLAY links an account with no player to its PC's game player, said as made now",
    $status === 200 && ($answer['linked'] ?? null) === true && ($answer['now'] ?? null) === true && ($answer['player']['id'] ?? 0) === 9611
    && linked_to($db, 'claimer') === 9611, "$status " . json_encode($answer));
check('WIN-440 a new player, its nickname blank, is named as the site names one', ($answer['player']['name'] ?? '') === 'Player 9611',
    json_encode($answer));
$lines = is_file($log) ? array_slice(file($log, FILE_IGNORE_NEW_LINES), $before) : [];
$noted = array_values(array_filter(array_map(fn($l) => json_decode($l, true), $lines), fn($e) => ($e['what'] ?? '') === 'site:claim'));
check("WIN-440 and the link goes in the admin pages' log of changes, by the account, naming its player",
    count($noted) === 1 && $noted[0]['who'] === 'claimer' && $noted[0]['target'] === 'claimer > Player 9611', json_encode($noted));
[$status, $answer] = claim($base, $cookie, '0a1b2c3d4e5f6071');
check('WIN-440 asked again: linked already, nothing made again',
    $status === 200 && ($answer['linked'] ?? null) === true && ($answer['now'] ?? null) === false && ($answer['player']['id'] ?? 0) === 9611,
    "$status " . json_encode($answer));
[$status, , $body] = visit('GET', "$base/opendmtq/client.php?records", [], $cookie);
check("WIN-440 the account's records are its player's from then on", $status === 200 && ((json_decode($body, true) ?: [])['player']['id'] ?? 0) === 9611,
    "$status $body");

// ------------------------------------------------------------------ WIN-441: who is never linked

$second = sign_in($base, 'second', 'claimpass');
[$status, $answer] = claim($base, $second, '0a1b2c3d4e5f6071');
check('WIN-441 another account naming a player who has an account is refused, and keeps no player',
    $status === 200 && ($answer['linked'] ?? null) === false && ($answer['why'] ?? '') === 'taken' && linked_to($db, 'second') === null,
    "$status " . json_encode($answer));
$nobody = [];
foreach (['0a1b2c3d4e5f6079', '../../etc', '', str_repeat('a', 65), OPENDMTQ_CHECK_UDID] as $device) {
    [$status, $answer] = claim($base, $second, $device);
    $nobody[] = $status . ' ' . ($answer['why'] ?? json_encode($answer));
}
check('WIN-441 an id no player plays by, one of no form, the server\'s own check account\'s: nobody',
    $nobody === array_fill(0, 5, '200 none') && linked_to($db, 'second') === null, implode(', ', $nobody));
$third = sign_in($base, 'third', 'claimpass');
[$status, $answer] = claim($base, $third, '0a1b2c3d4e5f6072');
check("WIN-441 a banned player is never linked to an account by the PC client",
    $status === 200 && ($answer['why'] ?? '') === 'banned' && linked_to($db, 'third') === null, "$status " . json_encode($answer));
// The owner's account, as the admin pages write it beside the database (owner.pass): the ID, then the password as kept.
$had = @file_get_contents("$state/owner.pass");
$salt = random_bytes(16);
file_put_contents("$state/owner.pass", "claimowner\npbkdf2_sha256\$1000\$" . bin2hex($salt) . '$' . hash_pbkdf2('sha256', 'owner-pass', $salt, 1000, 64) . "\n");
$owner = sign_in($base, 'claimowner', 'owner-pass');
[$status, $answer] = claim($base, $owner, '0a1b2c3d4e5f6079');
check("WIN-441 the owner's account, kept in .env and linked to no player, is never linked",
    $owner !== '' && $status === 200 && ($answer['why'] ?? '') === 'owner', ($owner !== '' ? 'signed in ' : 'not signed in ') . "$status " . json_encode($answer));
if ($had === false) {
    @unlink("$state/owner.pass");
} else {
    file_put_contents("$state/owner.pass", $had);
}
[$status, $answer] = claim($base, '', '0a1b2c3d4e5f6071');
[$get] = claim($base, $cookie, '0a1b2c3d4e5f6071', 'GET');
check('WIN-441 not signed in: refused as every signed-in answer is; asked without a POST: refused',
    $status === 403 && ($answer['error'] ?? '') === 'signin' && $get === 405, "$status " . json_encode($answer) . " GET $get");

exit($failures ? 1 : 0);
