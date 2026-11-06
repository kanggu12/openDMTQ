<?php
/*
 * Storing achievements while another writer holds the database (tests/game/protocol.sh runs this inside the server
 * image, on the throwaway server's database): the store gives up after the one wait for the lock, stores nothing and
 * warns about nothing; once the lock is free, the same store keeps every row. A save that earns achievements while a
 * backup or another phone's save holds the lock must never leave PHP warnings in the log, nor wait once per row.
 *
 * Usage: php tests/game/lock.php <database file>      (exit status 0 when every check passed)
 */

// The server's own code: the image's, or a host install's (OPENDMTQ_APP names its server/ folder).
require_once (getenv('OPENDMTQ_APP') ?: '/opt/opendmtq') . '/game/src/achievement.php';

// The database under test: the one the throwaway server runs on.
putenv('OPENDMTQ_DB=' . $argv[1]);

// Any warning or notice is a failure, also one the code silenced with @ (PHP 8 still calls the handler for those, with
// a lower error_reporting(); they are left alone here, as they never reach the log).
$complaints = [];
set_error_handler(function (int $level, string $message) use (&$complaints): bool {
    // Silenced with @: not logged, so not a complaint.
    if (!(error_reporting() & $level)) {
        return false;
    }
    $complaints[] = $message;
    return true;
});

// One line per check, as protocol.py prints them; the count of failures decides the exit status.
$failures = 0;
function check(string $name, bool $ok, string $detail = ''): void
{
    global $failures;
    if (!$ok) {
        $failures++;
    }
    echo ($ok ? 'PASS ' : 'FAIL ') . $name . ($detail !== '' ? " | $detail" : '') . "\n";
}

// A player no test uses (achievements are stored per player), and two of the game's achievement ids.
$guid = 990001;
$times = [11 => time(), 13 => time()];
// How many of this player's achievements are stored.
$stored = function () use ($guid): int {
    $db = new SQLite3(getenv('OPENDMTQ_DB'));
    return (int)$db->querySingle("SELECT COUNT(*) FROM AchievementDate WHERE user_id = $guid");
};

// Another writer: a second connection takes the write lock and keeps it while the store runs.
$holder = new SQLite3($argv[1]);
$holder->exec('BEGIN IMMEDIATE');
$start = microtime(true);
odq_store_achievements($guid, $times);
$waited = microtime(true) - $start;
// One wait for the lock (odq_db() waits 5 s), not one per row: the two rows would take 15 s.
check('with the lock taken, the store gives up after one wait', $waited > 4 && $waited < 8, sprintf('%.1f s', $waited));
$holder->exec('ROLLBACK');
$holder->close();
check('with the lock taken, nothing is stored', $stored() === 0);
check('with the lock taken, PHP warns about nothing', !$complaints, implode('; ', $complaints));

// The lock is free: the same store keeps both rows, again without a warning (only this step's count).
$complaints = [];
odq_store_achievements($guid, $times);
check('with the lock free, every row is stored', $stored() === 2);
check('with the lock free, PHP warns about nothing', !$complaints, implode('; ', $complaints));

exit($failures ? 1 : 0);
