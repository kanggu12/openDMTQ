<?php
/*
 * The database's earlier plays for the load test (tests/load/run.sh pipes this to PHP in the server's container): $argv[1]
 * plays by the players listed in /data/load-guids.txt, on charts of the content's song list, spread over the last 90
 * days, then each player's best on each chart as the game keeps it. One transaction, as a server that has run for months
 * would have them; the server's own requests then run on a database of that size.
 */

// How many plays, from the command line (php -- N).
$n = (int)($argv[1] ?? 1000000);
// The players run.sh made through the game's own logins.
$guids = array_map('intval', file('/data/load-guids.txt', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES));
// Every chart of the songs the server offers.
$charts = [];
foreach (json_decode(file_get_contents('/srv/content/songs.json'), true) as $song) {
    foreach ($song['song_patterns'] as $p) {
        $charts[] = (int)$p['pattern_id'];
    }
}
// The same plays on every run, so two runs measure the same database.
mt_srand(5);
$db = new SQLite3('/data/dmtq.db3');
// The server may be answering its health check meanwhile: wait for it rather than fail.
$db->busyTimeout(5000);
$db->exec('BEGIN IMMEDIATE');
$q = $db->prepare('INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at)
                   VALUES (:u, :p, :s, :g, :j, 0, :t)');
$now = time();
for ($i = 0; $i < $n; $i++) {
    // An accuracy in tenths of a percent, and the grade the server gives it (game.php).
    $j = mt_rand(600, 1000);
    $g = $j >= 980 ? 'S' : ($j >= 900 ? 'A' : ($j >= 800 ? 'B' : ($j >= 700 ? 'C' : 'D')));
    $q->bindValue(':u', $guids[mt_rand(0, count($guids) - 1)], SQLITE3_INTEGER);
    $q->bindValue(':p', $charts[mt_rand(0, count($charts) - 1)], SQLITE3_INTEGER);
    $q->bindValue(':s', $j * 900 + mt_rand(0, 899), SQLITE3_INTEGER);
    $q->bindValue(':g', $g, SQLITE3_TEXT);
    $q->bindValue(':j', $j, SQLITE3_INTEGER);
    // Played within the last 90 days, so this month's and earlier months' rankings both have rows.
    $q->bindValue(':t', $now - mt_rand(0, 90 * 86400), SQLITE3_INTEGER);
    $q->execute();
    $q->reset();
}
// Each player's best on each chart, the rows the rankings read.
$db->exec("INSERT OR IGNORE INTO Play (pattern_id, user_id, score, grade, isAllCombo, isPerfectPlay, judgement)
           SELECT pattern_id, user_id, max(score), CASE WHEN max(judgement) >= 980 THEN 'S' WHEN max(judgement) >= 900 THEN 'A'
           WHEN max(judgement) >= 800 THEN 'B' WHEN max(judgement) >= 700 THEN 'C' ELSE 'D' END, 'N', 'N', max(judgement)
           FROM PlayLog GROUP BY pattern_id, user_id");
$db->exec('COMMIT');
// What the database holds now, for the test's log.
echo 'seeded: ' . $db->querySingle('SELECT count(*) FROM PlayLog') . ' plays, ' . $db->querySingle('SELECT count(*) FROM Play')
    . ' bests, ' . count($guids) . " players\n";
