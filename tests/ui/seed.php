<?php
/*
 * Players and plays for the pages' tests, written straight into the database the server made: the game's own requests
 * are not in the stand-in game files (make_content.php). The names are chosen for what the pages must cope with: Korean, the
 * longest name of wide letters, none at all, a player with no plays.
 *
 * Usage: docker exec -i <server container> php < seed.php
 */

// The server's database, the songs on offer, and the same results on every run.
$db = new SQLite3('/data/dmtq.db3');
$db->busyTimeout(5000);
$songs = json_decode((string)file_get_contents('/srv/content/songs.json'), true);
$charts = [];
foreach ($songs as $song) {
    foreach ($song['song_patterns'] as $chart) {
        $charts[] = (int)$chart['pattern_id'];
    }
}
mt_srand(11);

// Name, how well they play (share of the best judgement) and how many plays.
$players = [
    ['Sena', 0.97, 40], ['민호', 0.93, 30], ['유나', 0.88, 25], [str_repeat('W', 20), 0.8, 20], ['가나다라마바사아자차카타파하거너', 0.72, 15],
    ['abcdefghijklmnop', 0.6, 10], ['Doyun', 0.55, 6], ['', 0.5, 5], ['Riku', 0.45, 1], ['NoPlaysYet', 0, 0],
];
$now = time();
$db->exec('BEGIN');
foreach ($players as $i => [$name, $skill, $plays]) {
    $id = $i + 1;
    // The device id is what broadcasts are uploaded under (feed.py).
    $member = $db->prepare('INSERT INTO Member (id, nickname, guid, puid, udid, code) VALUES (:id, :name, :guid, :puid, :udid, :code)');
    $member->bindValue(':id', $id);
    $member->bindValue(':name', $name);
    $member->bindValue(':guid', (string)$id);
    $member->bindValue(':puid', "puid-$id");
    $member->bindValue(':udid', "ui-$id");
    $member->bindValue(':code', "code$id");
    $member->execute();
    $best = [];
    for ($n = 0; $n < $plays; $n++) {
        $pattern = $charts[mt_rand(0, count($charts) - 1)];
        // Judgement in tenths of a percent; the score follows it, the grade too.
        $judgement = min(1000, (int)round(1000 * $skill + mt_rand(-40, 40)));
        $score = 60 * $judgement + mt_rand(0, 900);
        $grade = $judgement >= 950 ? 'S' : ($judgement >= 900 ? 'A' : ($judgement >= 800 ? 'B' : ($judgement >= 700 ? 'C' : 'D')));
        // Spread over twelve weeks, a third of them this week and a few today: what the charts of time must show.
        $ago = $n % 3 === 0 ? mt_rand(0, 6 * 86400) : ($n % 7 === 0 ? mt_rand(0, 20 * 3600) : mt_rand(0, 80 * 86400));
        $isRecord = !isset($best[$pattern]) || $score > $best[$pattern][0];
        if ($isRecord) {
            $best[$pattern] = [$score, $grade, $judgement];
        }
        $db->exec("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at)
                   VALUES ($id, $pattern, $score, '$grade', $judgement, " . ($isRecord ? 1 : 0) . ', ' . ($now - $ago) . ')');
    }
    foreach ($best as $pattern => [$score, $grade, $judgement]) {
        // Some all combos and perfect plays, for the marks.
        $combo = $judgement >= 960 ? 'Y' : 'N';
        $perfect = $judgement >= 990 ? 'Y' : 'N';
        $db->exec("INSERT INTO Play (pattern_id, user_id, score, grade, isAllCombo, isPerfectPlay, judgement)
                   VALUES ($pattern, $id, $score, '$grade', '$combo', '$perfect', $judgement)");
    }
}
$db->exec('COMMIT');
echo 'seed: ' . count($players) . ' players, ' . $db->querySingle('SELECT COUNT(*) FROM PlayLog') . " plays\n";
