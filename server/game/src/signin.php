<?php
/*
 * Whose game a call comes from. What the game carries per sign-in, as it really sends it: the platform's login hands the
 * phone an access token (platform.php), the game's own login (user.loginV2) takes it and hands back the key the game signs
 * with (SECRET_KEY), and every request after it carries Fp, MD5 of that key and the request's body (before its login the
 * game signs with an empty key). The server hands each sign-in a key of its own and keeps it (SignIn, with the access token
 * as its SHA-256 and the player), so that a signature tells which player's game made a request:
 *
 *   - the game's login takes only an access token the platform's login handed out for the account it names;
 *   - a request with a call that spends or earns a player's currency, or changes what the player has or shows (a chart's
 *     start, a save, the shop, the items equipped, the name, the transfer code's two calls: odq_signed_call()), is taken
 *     only signed with the key of a sign-in of the very player that call names;
 *   - a save earns MAX POINT and experience only for the play its sign-in started last (game.getPreviewPlayInfo's
 *     game_token, which the save sends back), and only once.
 *
 * What the server cannot tell apart: the platform's login trusts the phone's device id, so whoever has a phone's device id
 * signs in as its player; and a player's own game, or anyone who reads its requests (the game speaks plain HTTP), can send
 * results and purchases for that player that no play made. Each account keeps its newest sign-ins (OPENDMTQ_SIGN_INS):
 * a phone signs in at every start of the game.
 */

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/db.php';

// The sign-ins an account keeps, its newest: more phones of one player, and a game left open while others start.
const OPENDMTQ_SIGN_INS = 8;

// The table of the sign-ins, as the start step makes it (bin/setup-db.php) and the platform's login makes it where it is not
// (a database from before it, restored while the server runs). access: the SHA-256 of the access token, in hex; key: the key
// the game login handed out for it (null before); guid: the player that login gave; play_*: the play the game started last.
const OPENDMTQ_SIGN_IN_TABLE = [
    'CREATE TABLE IF NOT EXISTS SignIn (access TEXT PRIMARY KEY, puid TEXT NOT NULL, at INTEGER NOT NULL, key TEXT, guid INTEGER,
     play_token TEXT, play_pattern INTEGER, play_at INTEGER)',
    'CREATE INDEX IF NOT EXISTS SignIn_puid ON SignIn (puid, at)',
    'CREATE INDEX IF NOT EXISTS SignIn_guid ON SignIn (guid)',
];

/* Makes the sign-ins' table where it is not: true when it is there. */
function odq_sign_in_table(SQLite3 $db): bool
{
    foreach (OPENDMTQ_SIGN_IN_TABLE as $sql) {
        if (!@$db->exec($sql)) {
            return false;
        }
    }
    return true;
}

/*
 * Notes the access token the platform's login hands out for the account $puid, in the caller's transaction on $db; the
 * account's sign-ins before its newest OPENDMTQ_SIGN_INS go. Throws when the database does not take it: no token is handed
 * out that the game's login would refuse.
 */
function odq_sign_in_note(SQLite3 $db, string $puid, string $access): void
{
    if (!odq_sign_in_table($db)) {
        throw new RuntimeException($db->lastErrorMsg());
    }
    $w = $db->prepare('INSERT INTO SignIn (access, puid, at) VALUES (:a, :p, :now)');
    // Kept as its SHA-256: the database never holds a token that signs in.
    $w->bindValue(':a', hash('sha256', $access), SQLITE3_TEXT);
    $w->bindValue(':p', $puid, SQLITE3_TEXT);
    $w->bindValue(':now', time(), SQLITE3_INTEGER);
    if (!@$w->execute()) {
        throw new RuntimeException($db->lastErrorMsg());
    }
    // The account's older sign-ins, past its newest ones (this one among them).
    $d = $db->prepare('DELETE FROM SignIn WHERE puid = :p AND access NOT IN
                       (SELECT access FROM SignIn WHERE puid = :p ORDER BY at DESC, rowid DESC LIMIT ' . OPENDMTQ_SIGN_INS . ')');
    $d->bindValue(':p', $puid, SQLITE3_TEXT);
    if (!@$d->execute()) {
        throw new RuntimeException($db->lastErrorMsg());
    }
}

/* True when the platform's login handed out the access token $access for the account $puid (the game's login takes no
   other). */
function odq_sign_in_known(string $access, string $puid): bool
{
    $q = @odq_db()->prepare('SELECT 1 FROM SignIn WHERE access = :a AND puid = :p');
    if (!$q) {
        return false;
    }
    $q->bindValue(':a', hash('sha256', $access), SQLITE3_TEXT);
    $q->bindValue(':p', $puid, SQLITE3_TEXT);
    $r = @$q->execute();
    return $r !== false && $r->fetchArray(SQLITE3_NUM) !== false;
}

/*
 * The game's login of the access token $access (one the platform's login handed out) as player $guid: the key the game is
 * to sign with, made at its first login and the same at each login after it with that token (the game logs in twice at its
 * start, with the same token); null when the database does not take it.
 */
function odq_sign_in_key(string $access, int $guid): ?string
{
    $db = odq_db();
    $q = @$db->prepare('SELECT key FROM SignIn WHERE access = :a');
    if (!$q) {
        return null;
    }
    $q->bindValue(':a', hash('sha256', $access), SQLITE3_TEXT);
    $r = @$q->execute();
    $row = $r ? $r->fetchArray(SQLITE3_ASSOC) : false;
    // The read ended before the write below: a read still open holds this handle's view of the database from its start,
    // and its write then fails at once ("database is locked") whenever another phone's sign-in wrote meanwhile, where it
    // would wait its turn (eight phones signing in at once lost some of their sign-ins).
    if ($r) {
        $r->finalize();
    }
    if (!$row) {
        return null;
    }
    // A key of its own for this sign-in: 32 hex characters, random.
    $key = is_string($row['key']) && $row['key'] !== '' ? $row['key'] : bin2hex(random_bytes(16));
    $w = @$db->prepare('UPDATE SignIn SET key = :k, guid = :g WHERE access = :a');
    if (!$w) {
        return null;
    }
    $w->bindValue(':k', $key, SQLITE3_TEXT);
    $w->bindValue(':g', $guid, SQLITE3_INTEGER);
    $w->bindValue(':a', hash('sha256', $access), SQLITE3_TEXT);
    return @$w->execute() ? $key : null;
}

// The calls of a player's that the game's signature guards besides the shop's and the saves': a chart's start, which takes
// its price; the items the player equips; the transfer code's two calls, the one that shows the player's code and the one
// that moves the phone's account onto a code's player; the name the player picks.
const OPENDMTQ_SIGNED_CALLS = ['game.getpreviewplayinfo', 'game.setslotitem', 'user.getconnectuuid', 'user.setconnectuuid', 'user.setnickname'];

/*
 * The calls the game's signature guards (a request with one of them is refused whole without it, rpc.php): a chart's start;
 * a save and its log; every call of the shop; the items equipped; the transfer code's calls; the player's name. Each names
 * its player first, and is taken only signed with the key of a sign-in of that player (the game signs every request after
 * its login).
 */
function odq_signed_call(string $method): bool
{
    return in_array($method, OPENDMTQ_SIGNED_CALLS, true) || strpos($method, 'game.saveplayresult') === 0 || strpos($method, 'shop.') === 0;
}

/* The request's body and its signature (the Fp header), as rpc.php gave them to odq_signed_by_own_game(): [body, given]. */
function odq_request_signature(?string $body = null, ?string $given = null): array
{
    static $kept = ['', ''];
    if ($body !== null) {
        $kept = [$body, (string)$given];
    }
    return $kept;
}

/*
 * The sign-in of player $guid whose key signed $body with $given (MD5 of the key and the body, in hex, as the game signs):
 * its access (the SHA-256 the platform's login noted), or null for none.
 */
function odq_signing_sign_in(int $guid, string $body, string $given): ?string
{
    if ($guid <= 0 || $given === '') {
        return null;
    }
    // At most the account's newest eight, by the index on the player (SignIn_guid).
    $q = @odq_db()->prepare('SELECT access, key FROM SignIn WHERE guid = :g AND key IS NOT NULL');
    if (!$q) {
        return null;
    }
    $q->bindValue(':g', $guid, SQLITE3_INTEGER);
    $r = @$q->execute();
    $found = null;
    while ($found === null && $r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
        // Compared in constant time.
        if (hash_equals(md5($row['key'] . $body), $given)) {
            $found = (string)$row['access'];
        }
    }
    // Ended before the request's writes (a read left open holds this handle's view of the database).
    if ($r) {
        $r->finalize();
    }
    return $found;
}

/*
 * True when this request was signed by a sign-in of player $guid, whatever its calls (the live view takes a player's state
 * from that player's own game alone, live.php): the sign-in odq_signed_by_own_game() found for a guarded call, or else the
 * request's signature checked against the player's sign-ins, once per player and request.
 */
function odq_request_signed_by(int $guid): bool
{
    // What a request was found to be signed by, by player and by the request's body and signature (one process may answer
    // more than one request, as a test does).
    static $seen = [];
    $sign_in = odq_request_sign_in();
    if ($sign_in !== null) {
        return $sign_in['guid'] === $guid;
    }
    [$body, $given] = odq_request_signature();
    $which = $guid . ' ' . md5($body) . ' ' . $given;
    if (!array_key_exists($which, $seen)) {
        $seen[$which] = odq_signing_sign_in($guid, $body, $given) !== null;
    }
    return $seen[$which];
}

/* The sign-in that signed this request, ['access', 'guid'], when one did (odq_signed_by_own_game() found it); else null. */
function odq_request_sign_in(?array $found = null, bool $set = false): ?array
{
    static $sign_in = null;
    if ($set) {
        $sign_in = $found;
    }
    return $sign_in;
}

/*
 * True when the request $body, with its signature $given (the Fp header), may run its calls $calls: none of them is one the
 * signature guards for a player (a guarded call that names nobody, id 0 or none, changes nobody's state and runs as any
 * call does), or each such call names one player, one of whose sign-ins' keys signed the body. Notes the sign-in that
 * signed it for the request (odq_request_sign_in()).
 */
function odq_signed_by_own_game(string $body, $calls, string $given): bool
{
    odq_request_sign_in(null, true);
    // Kept for the checks a call may make later of whose game signed it (odq_request_signed_by()).
    odq_request_signature($body, $given);
    if (!is_array($calls)) {
        return true;
    }
    // The players the guarded calls name, as the handlers read them (odq_intval()).
    $players = [];
    foreach ($calls as $call) {
        $method = is_array($call) && isset($call['method']) && is_string($call['method']) ? ltrim(strtolower($call['method']), '\\') : '';
        $params = is_array($call) && is_array($call['params'] ?? null) ? array_values($call['params']) : [];
        $guid = odq_intval($params[0] ?? null);
        if ($method !== '' && odq_signed_call($method) && $guid > 0) {
            $players[$guid] = true;
        }
    }
    if (!$players) {
        return true;
    }
    // One signature for the whole request, from one sign-in: a request of the game's names one player.
    if (count($players) !== 1 || $given === '') {
        return false;
    }
    $guid = array_key_first($players);
    // The game's signature: MD5 of the key of one of the player's sign-ins and the body.
    $access = odq_signing_sign_in($guid, $body, $given);
    if ($access === null) {
        return false;
    }
    odq_request_sign_in(['access' => $access, 'guid' => $guid], true);
    return true;
}

/*
 * A play started by this request's sign-in (game.getPreviewPlayInfo) for player $guid on chart $pattern: its token, new and
 * random, which the game sends back with the play's save, kept with the sign-in until a save pays for it. A sign-in starts
 * one play at a time: a new start takes the place of the last.
 */
function odq_play_start(int $guid, int $pattern): string
{
    // 36 hex characters, as the official server's tokens were.
    $token = bin2hex(random_bytes(18));
    $sign_in = odq_request_sign_in();
    if ($sign_in !== null && $sign_in['guid'] === $guid) {
        $w = @odq_db()->prepare('UPDATE SignIn SET play_token = :t, play_pattern = :p, play_at = :now WHERE access = :a');
        if ($w) {
            $w->bindValue(':t', $token, SQLITE3_TEXT);
            $w->bindValue(':p', $pattern, SQLITE3_INTEGER);
            $w->bindValue(':now', time(), SQLITE3_INTEGER);
            $w->bindValue(':a', $sign_in['access'], SQLITE3_TEXT);
            @$w->execute();
        }
    }
    return $token;
}

/*
 * In the caller's transaction on $db: true when the save of player $guid on chart $pattern with the token $token is of the
 * play this request's sign-in started last, and that play is not paid for yet; it is paid then (its token taken), so a
 * second save of it earns nothing.
 */
function odq_play_take(SQLite3 $db, int $guid, int $pattern, $token): bool
{
    $sign_in = odq_request_sign_in();
    if ($sign_in === null || $sign_in['guid'] !== $guid || !is_string($token) || $token === '') {
        return false;
    }
    $w = $db->prepare('UPDATE SignIn SET play_token = NULL WHERE access = :a AND play_token = :t AND play_pattern = :p');
    $w->bindValue(':a', $sign_in['access'], SQLITE3_TEXT);
    $w->bindValue(':t', $token, SQLITE3_TEXT);
    $w->bindValue(':p', $pattern, SQLITE3_INTEGER);
    if (!@$w->execute()) {
        throw new RuntimeException($db->lastErrorMsg());
    }
    return $db->changes() === 1;
}
