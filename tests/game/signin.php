<?php
/*
 * The site's sign-in for the owner, a banned player's one-time link and an account switched off: tests/game/protocol.sh
 * runs this inside the throwaway server, after the contract, on its database and state folder, at its own address.
 *
 *   - the owner's ID, of every length the server takes for it (1 to 40 of A-Z, a-z, 0-9, . _ -, as owner.pass keeps it):
 *     the sign-in form's cookie signs the owner in on the next page;
 *   - a one-time link of an account whose player is banned now signs nobody in, and the sign-in page says why, with the
 *     owner's reason, as the form does;
 *   - an account switched off on the Accounts page, with the right password, is told so in its own words and the try is
 *     no failure; with a wrong password it is told only that it is wrong;
 *   - the same through the PC client's sign-in (client.php?signin): answered that the account is off after its right
 *     password, with no cookie and no failure counted, and only that a wrong password is wrong.
 *
 * Usage: php tests/game/signin.php <database file> <base address of the server>      (exit status 0 when every check passed)
 */

$app = getenv('OPENDMTQ_APP') ?: '/opt/opendmtq';
// The site's own sign-in code, for one-time links made as the PC client's and the admin API's are (once_issue()).
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
    // The status from the reply's first line ("HTTP/1.1 303 See Other"), 0 when nothing came back.
    $status = isset($http_response_header[0]) ? (int)(explode(' ', $http_response_header[0])[1] ?? 0) : 0;
    return [$status, $http_response_header ?? [], (string)$raw];
}

/* The site's sign-in cookie a reply sets, as "name=value", or ''. */
function signin_cookie(array $headers): string
{
    foreach ($headers as $h) {
        if (preg_match('/^Set-Cookie:\s*(opendmtq_dl=[^;]+)/i', $h, $m) && $m[1] !== 'opendmtq_dl=') {
            return $m[1];
        }
    }
    return '';
}

/* The owner's sign-in as the admin pages write it beside the database (owner.pass): the ID, then the password as kept. */
function write_owner(string $id, string $password): void
{
    $salt = random_bytes(16);
    file_put_contents(odq_state_dir() . '/owner.pass', $id . "\npbkdf2_sha256\$1000\$" . bin2hex($salt) . '$'
        . hash_pbkdf2('sha256', $password, $salt, 1000, 64) . "\n");
}

$state = odq_state_dir();
// What the server had of the owner's sign-in before, put back at the end: this server's other checks may read it.
$had = @file_get_contents("$state/owner.pass");

// ------------------------------------------------------------------ SRV-80: the owner's ID of every length it may have

foreach (['j', 'jg', 'own', 'admin', str_repeat('o', 20), 'the-owner-of-this-server', str_repeat('O', 40)] as $id) {
    write_owner($id, 'owner-pass');
    [$status, $headers] = visit('POST', "$base/opendmtq/login.php?next=%2Fopendmtq%2Fme.php", ['user' => $id, 'password' => 'owner-pass']);
    $cookie = signin_cookie($headers);
    // MY PAGE opens for whoever is signed in (200), and sends anyone else to the sign-in (302).
    [$next] = visit('GET', "$base/opendmtq/me.php", [], $cookie);
    check('SRV-80 the owner signs in to the site with an ID of ' . strlen($id) . (strlen($id) === 1 ? ' character' : ' characters')
        . ' and stays signed in on the next page',
        $status === 303 && $cookie !== '' && $next === 200, "$status $next " . ($cookie !== '' ? 'cookie' : 'no cookie'));
}

// ------------------------------------------------------------------ SRV-81: a one-time link of a banned player's account

$db = new SQLite3($path);
// The server is running on the same database: wait for its writers rather than fail.
$db->busyTimeout(5000);
// A player no other check uses, banned with a reason and an end, and an account linked to them as the Accounts page makes
// one: the table with the player's column the admin pages add (auth.py account_table()).
$db->exec("INSERT INTO Member (id, nickname, guid, puid, udid, code) VALUES (9411, 'Eve', '9411', '9411', 'signin-9411', 'signincode1')");
$db->exec("INSERT INTO PlayerBan (guid, reason, since, until, by) VALUES (9411, 'Made-up scores', " . time() . ', ' . (time() + 86400) . ", 'admin')");
$columns = [];
$r = $db->query('PRAGMA table_info(SiteUser)');
while ($row = $r->fetchArray(SQLITE3_ASSOC)) {
    $columns[] = $row['name'];
}
if (!in_array('guid', $columns, true)) {
    $db->exec('ALTER TABLE SiteUser ADD COLUMN guid INTEGER');
}
$salt = bin2hex(random_bytes(16));
$hash = 'pbkdf2_sha256$1000$' . $salt . '$' . hash_pbkdf2('sha256', 'evepass', (string)hex2bin($salt), 1000, 64);
$db->exec("INSERT OR REPLACE INTO SiteUser (name, pass, note, admin, created_at, off, guid) VALUES ('evesite', '$hash', '', 0, " . time() . ", 0, 9411)");
// A link as the PC client's My page on the site asks for one, opened in a browser signed in to nothing.
$token = once_issue('evesite', '/opendmtq/me.php');
[$status, $headers, $page] = visit('GET', "$base/opendmtq/login.php?once=" . rawurlencode((string)$token));
check("SRV-81 a one-time link of a banned player's account signs nobody in",
    $token !== null && $status === 200 && signin_cookie($headers) === '', "$status " . (signin_cookie($headers) !== '' ? 'cookie set' : 'no cookie'));
check('SRV-81 and the sign-in page says the account cannot sign in until the end, with the owner\'s reason',
    strpos($page, 'This account cannot sign in until') !== false && strpos($page, 'Made-up scores') !== false, substr(strip_tags($page), 0, 300));
// The same link of the account once the ban has ended: signed in, on to its page.
$db->exec('UPDATE PlayerBan SET until = ' . (time() - 1) . ' WHERE guid = 9411');
$token = once_issue('evesite', '/opendmtq/me.php');
[$status, $headers] = visit('GET', "$base/opendmtq/login.php?once=" . rawurlencode((string)$token));
check('SRV-81 once the ban has ended, a link signs the browser in and goes on to its page',
    $status === 303 && signin_cookie($headers) !== '', "$status " . (signin_cookie($headers) !== '' ? 'cookie set' : 'no cookie'));

// ------------------------------------------------------------------ SRV-82: an account switched off on the Accounts page

// An account as the Accounts page leaves one it switched off (off 1), with its password as the site keeps it.
$salt = bin2hex(random_bytes(16));
$hash = 'pbkdf2_sha256$1000$' . $salt . '$' . hash_pbkdf2('sha256', 'offpass', (string)hex2bin($salt), 1000, 64);
$db->exec("INSERT OR REPLACE INTO SiteUser (name, pass, note, admin, created_at, off) VALUES ('offsite', '$hash', '', 0, " . time() . ', 1)');
// More tries with the right password than the sign-in lets one address fail in ten minutes (DL_PER_ADDRESS): none of
// them is a failure, so the last is answered as the first.
$said = [];
for ($i = 0; $i <= DL_PER_ADDRESS; $i++) {
    [$status, $headers, $page] = visit('POST', "$base/opendmtq/login.php", ['user' => 'offsite', 'password' => 'offpass']);
    $said[] = strpos($page, 'This account is disabled and cannot sign in.') !== false ? 'off'
        : (strpos($page, 'Too many failed sign-ins') !== false ? 'throttled' : (strpos($page, 'Wrong ID or password.') !== false ? 'wrong' : "$status"));
}
check('SRV-82 an account switched off, with the right password, is told so in its own words and signed in nowhere',
    $said[0] === 'off' && $status === 200 && signin_cookie($headers) === '', implode(' ', $said));
check('SRV-82 and the right password is no failure: past as many tries as one address may fail, still told the same',
    end($said) === 'off', implode(' ', $said));
[, , $page] = visit('POST', "$base/opendmtq/login.php", ['user' => 'offsite', 'password' => 'not-its-password']);
check('SRV-82 a wrong password is told only that it is wrong, as for any account', strpos($page, 'Wrong ID or password.') !== false
    && strpos($page, 'disabled') === false, substr(strip_tags($page), 0, 200));
[, , $page] = visit('POST', "$base/opendmtq/login.php", ['user' => 'offsite', 'password' => 'offpass'], 'opendmtq_lang=ko');
check('SRV-82 in Korean too', strpos($page, '이 계정은 비활성화되어 로그인할 수 없습니다.') !== false, substr(strip_tags($page), 0, 200));

// ------------------------------------------------------------------ SRV-100: a one-time link of an account switched off

// A link made a moment before (as the PC client's My page on the site and the admin API's POST /site/link make one) of the
// account switched off above, opened at once in a browser signed in to nothing, in both languages.
foreach (['en' => 'This account is disabled and cannot sign in.', 'ko' => '이 계정은 비활성화되어 로그인할 수 없습니다.'] as $lang => $words) {
    $token = once_issue('offsite', '/opendmtq/me.php');
    [$status, $headers, $page] = visit('GET', "$base/opendmtq/login.php?once=" . rawurlencode((string)$token), [], "opendmtq_lang=$lang");
    check("SRV-100 a one-time link of an account switched off signs nobody in, and the page says the account is disabled ($lang)",
        $token !== null && $status === 200 && signin_cookie($headers) === '' && strpos($page, $words) !== false
        && strpos($page, $lang === 'en' ? 'was used already' : '이미 쓰였거나') === false, "$status " . substr(strip_tags($page), 0, 300));
}

// ------------------------------------------------------------------ WIN-288: the PC client's sign-in of an account switched off

// The launcher signs in through client.php?signin, under the sign-in page's own limit on failures: the account switched
// off above, its right password more times than one address may fail in ten minutes, each try said as its status, its
// error word and whether it set the site's cookie; then a wrong password.
$said = [];
for ($i = 0; $i <= DL_PER_ADDRESS; $i++) {
    [$status, $headers, $body] = visit('POST', "$base/opendmtq/client.php?signin", ['user' => 'offsite', 'password' => 'offpass']);
    $said[] = $status . ' ' . ((json_decode($body, true) ?: [])['error'] ?? '-') . (signin_cookie($headers) !== '' ? ' cookie' : '');
}
check("WIN-288 the PC client's sign-in of an account switched off, with the right password, is answered that it is off, "
    . 'with no sign-in cookie', $said[0] === '403 off', implode(', ', $said));
check('WIN-288 and the right password is no failure: past as many tries as one address may fail, still answered the same',
    end($said) === '403 off', implode(', ', $said));
[$status, , $body] = visit('POST', "$base/opendmtq/client.php?signin", ['user' => 'offsite', 'password' => 'not-its-password']);
check("WIN-288 the PC client's sign-in with a wrong password is answered only that it is wrong, as for any account",
    $status === 401 && ((json_decode($body, true) ?: [])['error'] ?? '') === 'wrong', "$status $body");

// The owner's sign-in as it was.
if ($had === false) {
    @unlink("$state/owner.pass");
} else {
    file_put_contents("$state/owner.pass", $had);
}
exit($failures ? 1 : 0);
