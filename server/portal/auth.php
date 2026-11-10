<?php
/* The site's sign-in: who a browser is signed in as, the gate of every page with content, signing in and out, and the
   limit on wrong passwords.
   Accounts are made on the admin pages' Accounts page; nobody makes their own. Apart from lib.php so that the game's own
   window (/score, server/game/pages/score.php) can be put behind it too without loading the portal's pages into it. */

// Where everything is: the game server's settings, which every part of the server shares.
require_once __DIR__ . '/../game/src/config.php';
// The game database (lib.php names the same file so).
if (!defined('DB')) {
    define('DB', odq_db_path());
}

/* The database, read-only, for the sign-in alone: null while there is none to read. One handle per page. */
function site_db(): ?SQLite3
{
    static $db = false;
    if ($db === false) {
        $db = null;
        try {
            if (is_file(DB) && filesize(DB) > 0) {
                $handle = new SQLite3(DB, SQLITE3_OPEN_READONLY);
                $handle->busyTimeout(2000);
                // Failures come back as false (PHP 8's default for SQLite3; asking for it is deprecated).
                $db = $handle;
            }
        } catch (Exception $e) {
            $db = null;
        }
    }
    return $db;
}

// Cookie that marks a browser as signed in to the site (30 days): when it ends, whose account it is, and a signature
// over both and the account's password as kept, so that a new password, or the account switched off or deleted, ends it.
const DL_COOKIE = 'opendmtq_dl';
const DL_DAYS = 30;
// Rounds of the stand-in check for an ID that is not there: as many as the admin pages give a password (ACCOUNT_ROUNDS).
const SITE_ROUNDS = 120000;

/* True when this visit came over HTTPS (the edge proxy says so, and entrypoint.sh passes that on to PHP). */
function visit_is_https(): bool
{
    return ($_SERVER['HTTPS'] ?? '') === 'on';
}

// The server's own secret for signing the cookie, made at start (by entrypoint.sh in the image, api only; by the host
// program on a host install).
define('DL_SECRET', odq_state_dir() . '/download.key');

/* Key that signs the cookie: from the server's own secret, so that a cookie seen on the network (plain HTTP) lets nobody
   test password guesses offline, and nobody without the server's files can make one. Empty without the secret: then
   nobody can be signed in. */
function dl_key(): string
{
    static $key = null;
    if ($key === null) {
        $secret = trim((string)@file_get_contents(DL_SECRET));
        $key = $secret !== '' ? hash_hmac('sha256', 'opendmtq-site', $secret, true) : '';
    }
    return $key;
}

/* An account by its ID, whatever the letter case: ['name', 'pass', 'off', 'admin', 'guid'] as the admin pages keep it
   (their Accounts page makes them; nobody makes their own), or null. */
function site_account(string $name): ?array
{
    $db = site_db();
    if (!$db || !preg_match('/^[A-Za-z0-9._-]{3,20}$/', $name)) {
        return null;
    }
    // With its admin rights (guesses at such an account's password count for the whole server, dl_attempt_begin()
    // below) and the game player it is linked to; a table from before the link has no such column yet (the
    // admin pages add it), and then no player.
    $q = @$db->prepare('SELECT name, pass, off, admin, guid FROM SiteUser WHERE name = :name') ?: @$db->prepare('SELECT name, pass, off, admin, NULL AS guid FROM SiteUser WHERE name = :name');
    if (!$q) {
        // No table yet: no accounts.
        return null;
    }
    $q->bindValue(':name', $name, SQLITE3_TEXT);
    $r = @$q->execute();
    $row = $r ? $r->fetchArray(SQLITE3_ASSOC) : false;
    return $row ?: null;
}

/* Whether $password is the one kept as $stored: PBKDF2-SHA256, as the admin pages write it (account_hash()). */
function site_pass_ok(string $stored, string $password): bool
{
    $p = explode('$', $stored);
    if (count($p) !== 4 || $p[0] !== 'pbkdf2_sha256' || !ctype_digit($p[1]) || (int)$p[1] < 1000 || (int)$p[1] > 5000000
        || !ctype_xdigit($p[2]) || strlen($p[2]) % 2 !== 0 || strlen($p[3]) !== 64) {
        return false;
    }
    return hash_equals($p[3], hash_pbkdf2('sha256', $password, (string)hex2bin($p[2]), (int)$p[1], 64));
}

/* The account an ID and a password sign in as (its ID as kept), or null. As slow for an ID that is not there as for one
   that is, so that the time taken does not tell which IDs there are. */
function site_check(string $name, string $password): ?string
{
    $row = site_account($name);
    $ok = site_pass_ok($row ? (string)$row['pass'] : 'pbkdf2_sha256$' . SITE_ROUNDS . '$' . str_repeat('0', 32) . '$' . str_repeat('0', 64), $password);
    return $row && $ok && !$row['off'] && dl_key() !== '' ? (string)$row['name'] : null;
}

/* The cookie's signature: when it ends, whose it is, and the account's password as kept. */
function dl_mac(string $expires, string $name, string $pass): string
{
    return hash_hmac('sha256', "$expires|$name|$pass", dl_key());
}

/* The account this browser is signed in as, or null: a cookie that has not run out, of an account that is there and on,
   signed with its password as it is now. Worked out once per page. */
function site_user(): ?string
{
    static $who = false;
    if ($who === false) {
        $who = null;
        $c = (string)($_COOKIE[DL_COOKIE] ?? '');
        if (dl_key() !== '' && preg_match('/^(\d{10})\.((?:[0-9a-f]{2}){3,20})\.([0-9a-f]{64})$/', $c, $m) && (int)$m[1] >= time()) {
            $row = site_account((string)hex2bin($m[2]));
            if ($row && !$row['off'] && hash_equals(dl_mac($m[1], (string)$row['name'], (string)$row['pass']), $m[3])) {
                $who = (string)$row['name'];
            }
        }
    }
    return $who;
}

/* The game player the signed-in account is (the owner linked them on the Accounts page), or null. */
function site_me(): ?int
{
    $who = site_user();
    $row = $who !== null ? site_account($who) : null;
    return $row && $row['guid'] !== null ? (int)$row['guid'] : null;
}

/* True when this browser may see the site and download: signed in to an account. */
function dl_signed_in(): bool
{
    return site_user() !== null;
}

/* The site's pages are for those signed in: anyone else goes to the sign-in page, which brings them back to the page
   they asked for. What a page's own script asks for ($json) answers 403 instead. Open without it:
   the sign-in page and its language switch, the licenses, the page for addresses that lead nowhere, the health check,
   and the game's own paths, which are not the site's. Call before any output. */
function require_sign_in(bool $json = false): void
{
    if (dl_signed_in()) {
        return;
    }
    // Neither the refusal nor the way to the sign-in may stay in a cache past signing in.
    header('Cache-Control: no-store');
    if ($json) {
        http_response_code(403);
        exit;
    }
    header('Location: /opendmtq/login.php?next=' . rawurlencode(safe_next((string)($_SERVER['REQUEST_URI'] ?? '/opendmtq/'))), true, 302);
    exit;
}

/* Mark this browser as signed in to the account $name (as site_check() gave it), and note when, for the owner's list. */
function dl_sign_in(string $name): void
{
    $row = site_account($name);
    if (!$row) {
        return;
    }
    $expires = (string)(time() + DL_DAYS * 86400);
    setcookie(DL_COOKIE, $expires . '.' . bin2hex((string)$row['name']) . '.' . dl_mac($expires, (string)$row['name'], (string)$row['pass']),
        ['expires' => (int)$expires, 'path' => '/', 'httponly' => true, 'samesite' => 'Lax', 'secure' => visit_is_https()]);
    // A database this page cannot write does not stop the sign-in.
    try {
        $db = new SQLite3(DB);
        $db->busyTimeout(2000);
        // Failures come back as false (PHP 8's default for SQLite3; asking for it is deprecated).
        $q = @$db->prepare('UPDATE SiteUser SET signed_in_at = :at WHERE name = :name');
        if ($q) {
            $q->bindValue(':at', time(), SQLITE3_INTEGER);
            $q->bindValue(':name', (string)$row['name'], SQLITE3_TEXT);
            @$q->execute();
        }
        $db->close();
    } catch (Exception $e) {
    }
}

/* Forget the sign-in. */
function dl_sign_out(): void
{
    setcookie(DL_COOKIE, '', ['expires' => 1, 'path' => '/', 'httponly' => true, 'samesite' => 'Lax', 'secure' => visit_is_https()]);
}

/* True when the browser says this request comes from a page of another site, which may not sign anyone in or out: a form
   there would sign a visitor in to an account of its own choosing, or out. Asked of every sign-in and sign-out. */
function from_another_site(): bool
{
    // What a browser says about where the request comes from: only this site's own pages, or the visitor's own typing
    // and bookmarks, are this site.
    $site = $_SERVER['HTTP_SEC_FETCH_SITE'] ?? null;
    if ($site !== null) {
        return $site !== 'same-origin' && $site !== 'none';
    }
    // A browser too old to say that still names the page a form came from (Origin). A request that names neither (the PC
    // client, a script) comes from no other site's page.
    $origin = $_SERVER['HTTP_ORIGIN'] ?? null;
    if ($origin === null) {
        return false;
    }
    // That page's host against the one this request was sent to, ports aside (a proxy in front may leave the port out).
    // A page with no origin of its own ("null") names no host at all.
    $from = strtolower((string)parse_url((string)$origin, PHP_URL_HOST));
    $here = strtolower((string)preg_replace('/:\d+$/', '', (string)($_SERVER['HTTP_HOST'] ?? '')));
    return $from === '' || $from !== $here;
}

/* ---------------------------------------------------------------------- wrong passwords

   How many guesses a sign-in takes: the sign-in page's (login.php) and the PC client's (client.php) alike, beside the
   accounts they are guesses at. */

// Sign-in failures of the last ten minutes, for the throttle below, in the server's scratch folder.
define('DL_ATTEMPTS', odq_run_dir() . '/download-signin.json');
// Failures in ten minutes: from one address, and at accounts with admin rights from all addresses together (as many as
// the admin pages' own sign-in allows through the server: OVERALL in tools/opendmtq_tools/admin/auth.py).
const DL_PER_ADDRESS = 10;
const DL_ADMIN_OVERALL = 30;

/* Sign-in attempts, for the account named $name: at most DL_PER_ADDRESS failures in ten minutes from one address (the
   edge proxy passes each visitor's own), and every failure waits a second (login.php). For the whole server, a limit on
   the accounts with admin rights alone: they open the admin pages too, whose own sign-in holds guesses from everywhere
   together to DL_ADMIN_OVERALL, and this sign-in must not be the way around that. No such limit on the other accounts:
   the whole site is behind this sign-in, and it would let anyone lock every player out.

   An attempt takes its place in the count before the password is compared, under a lock, so
   attempts sent at the same moment cannot all pass the check before any is counted; a right
   password gives the place back (dl_attempt_succeeded()). Returns the attempt's id, or null when
   this address, or the account's admin rights, is throttled. */
function dl_attempt_begin(string $name = ''): ?string
{
    $ip = (string)($_SERVER['REMOTE_ADDR'] ?? '?');
    $id = bin2hex(random_bytes(8));
    // Whether the name typed is an account with admin rights, switched off or not: a guess at its password is one all the same.
    $row = site_account($name);
    $admin = $row !== null && !empty($row['admin']);
    $granted = false;
    $counted = dl_attempts(function (array $fails) use ($ip, $id, $admin, &$granted): array {
        $mine = count(array_filter($fails, fn($f) => ($f[1] ?? '') === $ip));
        // The failures at accounts with admin rights, from anywhere (entries from before this count carry no such mark).
        $at_admins = count(array_filter($fails, fn($f) => !empty($f[3])));
        if ($mine >= DL_PER_ADDRESS || ($admin && $at_admins >= DL_ADMIN_OVERALL)) {
            return $fails;
        }
        $granted = true;
        $fails[] = [time(), $ip, $id, $admin ? 1 : 0];
        return $fails;
    });
    // Nowhere to count (the run folder is not writable): let it through, as before the throttle.
    return ($granted || !$counted) ? $id : null;
}

/* The password was right: the attempt is not a failure. */
function dl_attempt_succeeded(string $id): void
{
    dl_attempts(fn(array $fails): array => array_filter($fails, fn($f) => ($f[2] ?? '') !== $id));
}

/* Runs $change on the failures of the last ten minutes ([[time, address, attempt id, 1 when at an
   account with admin rights], ...]) and saves what it returns, all under an exclusive lock on the
   file. False when the file cannot be used. */
function dl_attempts(callable $change): bool
{
    $h = @fopen(DL_ATTEMPTS, 'c+');
    if (!$h) {
        return false;
    }
    if (!flock($h, LOCK_EX)) {
        fclose($h);
        return false;
    }
    $now = time();
    // Only entries of the last ten minutes (an older file held bare times, or [time, address]).
    $fails = array_filter((array)json_decode((string)stream_get_contents($h), true),
        fn($f) => is_array($f) && $now - (int)($f[0] ?? 0) < 600);
    $fails = array_values($change(array_values($fails)));
    // Rewritten in place while the lock is held, so no other attempt reads it half-written.
    ftruncate($h, 0);
    rewind($h);
    fwrite($h, json_encode($fails));
    fflush($h);
    flock($h, LOCK_UN);
    fclose($h);
    return true;
}

/* Whether signing in can work at all: the accounts can be read and the server's secret is there. Otherwise the sign-in
   page says so, instead of calling a right password wrong. */
function site_sign_in_works(): bool
{
    $db = site_db();
    return $db !== null && dl_key() !== '' && @$db->querySingle('SELECT COUNT(*) FROM SiteUser') !== false;
}

/* A local path to return to after signing in; anything else goes home. */
function safe_next(string $next): string
{
    return (preg_match('#^/(?!/)[A-Za-z0-9/_.?=&%-]*$#', $next)) ? $next : '/opendmtq/';
}
