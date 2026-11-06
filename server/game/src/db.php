<?php
/*
 * The database every part of the server shares (data/state/dmtq.db3): one handle per request, the tables the
 * game's own data lives in, and the lookups of a player that most methods start with. The tables and their
 * columns are the game's: Member and Play keep the names, types and quirks of the tables earlier DMTQ servers used,
 * so that databases from those servers and from earlier OpenDMTQ versions open unchanged.
 */

require_once __DIR__ . '/config.php';

/*
 * The request's database handle, opened on first use. Writers wait up to five seconds for each other instead
 * of failing at once ("database is locked"), and in write-ahead mode a commit waits for the disk once.
 */
function odq_db(): SQLite3
{
    static $db = null;
    if ($db === null) {
        $db = new SQLite3(odq_db_path());
        // Several phones save at the same moment: wait for the other writer rather than fail.
        $db->busyTimeout(5000);
        odq_tune_db($db);
    }
    return $db;
}

/*
 * Settings of one database handle. SQLite's write-ahead mode (bin/setup-db.php turns it on where the disk
 * allows it) needs no second wait for the disk per commit: a crash of the program loses nothing, a power cut
 * at worst the last moments' commits and never the file. In the older rollback mode the same setting could
 * damage the file on a power cut, so it is left at its default there.
 */
function odq_tune_db(SQLite3 $db): void
{
    if (@$db->querySingle('PRAGMA journal_mode') === 'wal') {
        @$db->exec('PRAGMA synchronous = NORMAL');
    }
}

/*
 * The first row of Member whose $column equals $value, as an associative array, or null. "First" is in rowid
 * order: a transfer code can give two rows one guid, and the game has always read the older one.
 */
function odq_member_by(string $column, $value): ?array
{
    // Only the three columns the game looks players up by; never a name from a request.
    if (!in_array($column, ['guid', 'puid', 'code'], true)) {
        return null;
    }
    $q = @odq_db()->prepare("SELECT * FROM Member WHERE $column = :v ORDER BY rowid LIMIT 1");
    if (!$q) {
        return null;
    }
    // Bound as the type it came as: the columns hold text, and SQLite compares a number with them as text.
    $q->bindValue(':v', $value, odq_sqlite_type($value));
    $r = @$q->execute();
    $row = $r ? $r->fetchArray(SQLITE3_ASSOC) : false;
    return $row ?: null;
}

/*
 * The SQLite type a value is bound as, the way PHP's own guess goes: ints and booleans as integers, floats as
 * reals, null as NULL, anything else as text. The columns' affinity then decides how it is stored.
 */
function odq_sqlite_type($value): int
{
    if (is_int($value) || is_bool($value)) {
        return SQLITE3_INTEGER;
    }
    if (is_float($value)) {
        return SQLITE3_FLOAT;
    }
    if ($value === null) {
        return SQLITE3_NULL;
    }
    return SQLITE3_TEXT;
}

/*
 * A value as PHP turns it into text when it is written into a string ("5" for 5, "" for null and false, "1"
 * for true). Lists and objects, which no client sends where text is expected, become "".
 */
function odq_text($value): string
{
    if (is_array($value) || is_object($value)) {
        return '';
    }
    return (string)$value;
}

/*
 * A value as PHP turns it into an int with (int): the leading digits of a string ("12ab" is 12), 0 for
 * anything without them, for null and for lists.
 */
function odq_intval($value): int
{
    if (is_array($value) || is_object($value)) {
        return 0;
    }
    return (int)$value;
}
