<?php
/*
 * What the server hands out with a player's account: its transfer code, which nobody else can work out. The transfer code
 * is what a player types on another phone (user.php's user.setConnectUuid) to move that phone's account onto their
 * player. It is random: earlier servers made it from the account's number (the last ten hex digits of an MD5 of "CODE_"
 * or "CODE" and the number), and the number is on every ranking, which gave anyone that player. Such a code is replaced at
 * a start (bin/setup-db.php), and the transfer code's calls never hand one out nor take one.
 */

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/db.php';

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
