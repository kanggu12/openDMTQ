<?php
/* The site's sign-in: who a browser is signed in as, the gate of every page with content, and signing in and out.
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
    // With its admin rights (guesses at such an account's password count for the whole server, lib.php's
    // dl_attempt_begin()) and the game player it is linked to; a table from before the link has no such column yet (the
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
