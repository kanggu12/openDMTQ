<?php
/*
 * What the server hands out with a player's account: its number, never handed out again, and its transfer code, which
 * nobody else can work out.
 *
 *   - the number is the player id the game knows the account by (guid) and the platform's account id (puid), at first
 *     the same. Numbers only go up: the highest ever handed out is kept (MemberNumber, one row), so a deleted player's
 *     number never comes back to someone else's phone, whose game the deleted player's sign-ins would sign for and whose
 *     records the deleted player's site account would show.
 *   - the transfer code is what a player types on another phone (user.php's user.setConnectUuid) to move that phone's
 *     account onto their player. It is random: earlier servers made it from the account's number (the last ten hex
 *     digits of an MD5 of "CODE_" or "CODE" and the number), and the number is on every ranking, which gave anyone that
 *     player. Such a code is replaced at a start (bin/setup-db.php), and the transfer code's calls never hand one out nor
 *     take one.
 */

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/db.php';

// The table that keeps the highest player number handed out: one row, as the start step makes it (bin/setup-db.php) and
// a new account's platform login where it is not (a database restored from before it while the server runs).
const OPENDMTQ_NUMBER_TABLE = 'CREATE TABLE IF NOT EXISTS MemberNumber (last INTEGER NOT NULL)';

/*
 * The highest number the database shows was handed out, apart from MemberNumber: the players' row numbers, and the
 * players named by a sign-in of the game or by a site account linked to a player, whose Member rows may be gone (a
 * player deleted before their sign-ins went with them, or one a restore took away). Each read is its own, so that a
 * table or a column a database does not have yet counts as nothing.
 */
function odq_numbers_seen(SQLite3 $db): int
{
    $highest = 0;
    // Each by an index, or of a small table: Member_id and SignIn_guid (setup-db.php, signin.php), the site's accounts.
    foreach (['SELECT MAX(id) FROM Member', 'SELECT MAX(guid) FROM SignIn', 'SELECT MAX(guid) FROM SiteUser'] as $sql) {
        // False for a table or a column that is not there, null for an empty table.
        $seen = @$db->querySingle($sql);
        $highest = max($highest, (int)$seen);
    }
    return $highest;
}

/*
 * Makes MemberNumber where it is not, with the highest number the database shows was handed out (odq_numbers_seen()).
 * True when it is there.
 */
function odq_number_table(SQLite3 $db): bool
{
    if (!@$db->exec(OPENDMTQ_NUMBER_TABLE)) {
        return false;
    }
    // Its one row, only where there is none: a number kept before stays as it is.
    if (@$db->querySingle('SELECT COUNT(*) FROM MemberNumber') === 0) {
        return (bool)@$db->exec('INSERT INTO MemberNumber (last) VALUES (' . odq_numbers_seen($db) . ')');
    }
    return true;
}

/*
 * The number of a new account, in the caller's transaction on $db: one past the highest ever handed out, and past every
 * number the database still shows (a row added by another program, a sign-in of a player a restore took away), kept as
 * the highest from now on. Throws when the database does not take it: no account is made with a number not kept.
 */
function odq_next_number(SQLite3 $db): int
{
    if (!odq_number_table($db)) {
        throw new RuntimeException($db->lastErrorMsg());
    }
    $next = max((int)@$db->querySingle('SELECT MAX(last) FROM MemberNumber'), odq_numbers_seen($db)) + 1;
    if (!@$db->exec("UPDATE MemberNumber SET last = $next")) {
        throw new RuntimeException($db->lastErrorMsg());
    }
    return $next;
}

/*
 * A new transfer code: ten lowercase hex digits, the form codes have always had, from the system's random source, and
 * one no account has (a code names one player: user.setConnectUuid takes the first row with it).
 */
function odq_new_code(SQLite3 $db): string
{
    $q = $db->prepare('SELECT 1 FROM Member WHERE code = :c LIMIT 1');
    // A few tries at most: of 2^40 codes, two alike come about once in a thousand million among a thousand players.
    for ($try = 0; $try < 8; $try++) {
        $code = bin2hex(random_bytes(5));
        if ($q === false) {
            return $code;
        }
        $q->bindValue(':c', $code, SQLITE3_TEXT);
        $r = @$q->execute();
        $taken = $r !== false && $r->fetchArray(SQLITE3_NUM) !== false;
        // The read ended before any write of the caller's: a read left open holds its view of the database.
        if ($r) {
            $r->finalize();
        }
        $q->reset();
        if (!$taken) {
            return $code;
        }
    }
    return $code;
}

/*
 * True when $code is one made from one of the account's numbers ($member: its row of Member, with id, guid and puid), as
 * earlier servers made every code: the last ten hex digits of an MD5 of "CODE_" (or, on the old login's path, "CODE")
 * and the number. Anyone who knows the number works such a code out.
 */
function odq_code_from_number($code, array $member): bool
{
    // Only text of that length can be one.
    if (!is_string($code) || strlen($code) !== 10) {
        return false;
    }
    foreach (['id', 'guid', 'puid'] as $column) {
        // Each number as text, as it was written into the MD5 ("CODE_" . 9415).
        $number = $member[$column] ?? null;
        if ($number === null || $number === '' || is_array($number)) {
            continue;
        }
        foreach (['CODE_', 'CODE'] as $prefix) {
            if (hash_equals(substr(md5($prefix . $number), -10), strtolower($code))) {
                return true;
            }
        }
    }
    return false;
}

/*
 * Every account whose transfer code was made from one of its numbers gets a random one in its place, in one
 * transaction on $db (the start step's, bin/setup-db.php): the number of codes replaced, or -1 when the database did not
 * take it (nothing replaced then).
 */
function odq_replace_number_codes(SQLite3 $db): int
{
    // The rows to change, read whole before any write (a read open during the writes would hold the old view).
    $found = [];
    $r = @$db->query('SELECT rowid, id, guid, puid, code FROM Member WHERE code IS NOT NULL');
    while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
        if (odq_code_from_number($row['code'], $row)) {
            $found[] = (int)$row['rowid'];
        }
    }
    if ($r) {
        $r->finalize();
    }
    if (!$found) {
        return 0;
    }
    if (!@$db->exec('BEGIN IMMEDIATE')) {
        return -1;
    }
    $w = $db->prepare('UPDATE Member SET code = :c WHERE rowid = :r');
    foreach ($found as $rowid) {
        // Unique among the codes there are, the new ones of this loop among them (each written before the next is made).
        $w->bindValue(':c', odq_new_code($db), SQLITE3_TEXT);
        $w->bindValue(':r', $rowid, SQLITE3_INTEGER);
        if (!@$w->execute()) {
            @$db->exec('ROLLBACK');
            return -1;
        }
        $w->reset();
    }
    return @$db->exec('COMMIT') ? count($found) : -1;
}
