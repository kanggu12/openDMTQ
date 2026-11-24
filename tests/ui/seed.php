<?php
/*
 * Players and plays for the pages' tests, written straight into the database the server made: the game's own requests
 * are not in the stand-in game files (make_content.php). The names are chosen for what the pages must cope with: Korean, the
 * longest name of wide letters, none at all, a player with no plays. Two play on the PC client with the keyboard: 민호 always,
 * 유나 every fourth play, which the game server marks (keys) on the play and on the best it sets; everyone else plays by
 * touch, Sena among them, whose pages must show no keyboard at all.
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

// Name, how well they play (share of the best judgement), how many plays, and which of them were played with the keyboard:
// every how many plays, and from which (none for 0). Not drawn from the random numbers, which stay as they were; and not in
// step with the plays' times below (every third play this week), so that a player's keyboard plays are this week's and older.
$players = [
    ['Sena', 0.97, 40, [0, 0]], ['민호', 0.93, 30, [1, 0]], ['유나', 0.88, 25, [4, 1]], [str_repeat('W', 20), 0.8, 20, [0, 0]],
    ['가나다라마바사아자차카타파하거너', 0.72, 15, [0, 0]], ['abcdefghijklmnop', 0.6, 10, [0, 0]], ['Doyun', 0.55, 6, [0, 0]], ['', 0.5, 5, [0, 0]],
    ['Riku', 0.45, 1, [0, 0]], ['NoPlaysYet', 0, 0, [0, 0]],
];
$now = time();
$db->exec('BEGIN');
foreach ($players as $i => [$name, $skill, $plays, [$every, $from]]) {
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
        // Played with the keyboard: 1 on the play, and on the best when this play sets it, as the game server keeps them.
        $keys = $every && $n % $every === $from ? 1 : 0;
        if ($isRecord) {
            $best[$pattern] = [$score, $grade, $judgement, $keys];
        }
        $db->exec("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at, keys)
                   VALUES ($id, $pattern, $score, '$grade', $judgement, " . ($isRecord ? 1 : 0) . ', ' . ($now - $ago) . ", $keys)");
    }
    foreach ($best as $pattern => [$score, $grade, $judgement, $keys]) {
        // Some all combos and perfect plays, for the marks.
        $combo = $judgement >= 960 ? 'Y' : 'N';
        $perfect = $judgement >= 990 ? 'Y' : 'N';
        $db->exec("INSERT INTO Play (pattern_id, user_id, score, grade, isAllCombo, isPerfectPlay, judgement, keys)
                   VALUES ($pattern, $id, $score, '$grade', '$combo', '$perfect', $judgement, $keys)");
    }
}
$db->exec('COMMIT');

// The players' game state as the admin pages and the game leave it (src/player.php, admin/game.py): 민호 with a balance of
// his own at level 12 and two things bought; a player with a long name (not one the broadcasts' feed puts on air: a ban
// keeps a player off it) banned for a week with the longest reason there may be, his currency unlimited, an item given and
// one taken, a purchase made while unlimited. What the owner did about him, as the admin pages note it in the log of
// changes (his player's page lists it).
$db->exec("INSERT INTO PlayerState (guid, mpoint, qpoint, exp, unlimited, changed_at) VALUES (2, 1234567, 45, 644, 0, $now), (6, 2000, 9, 5669, 1, $now)");
$db->exec("INSERT INTO PlayerItem (guid, item_id, owned, how, at) VALUES (2, 90001, 1, 'bought', $now), (6, 90002, 1, 'given', $now), (6, 30001, 0, 'taken', $now)");
// Sena's slots as game.setSlotItem keeps them: a partner and a skin the stand-in catalog has names for, a note it has
// none for (MY PAGE shows the names, and the number where there is none).
$db->exec("UPDATE Member SET slot_item1 = 30001, slot_item2 = 0, slot_item3 = 90001, slot_item4 = 100001 WHERE guid = 1");
$db->exec("INSERT INTO PlayerPurchase (guid, product_id, item_id, currency, price, paid, at) VALUES
           (2, 90001, 90001, 'max', 2000, 2000, " . ($now - 7200) . "), (2, 1050001, 50001, 'q', 10, 10, " . ($now - 3600) . "),
           (6, 100002, 100002, 'max', 25000, 0, " . ($now - 600) . ")");
$reason = str_repeat('Made-up scores on the monthly rankings, sent from a program and not from the game. ', 3);
$db->exec("INSERT INTO PlayerBan (guid, reason, since, until, by) VALUES (6, '" . substr(trim($reason), 0, 200) . "', $now, " . ($now + 7 * 86400) . ", 'admin')");
$log = '';
foreach ([['player_game:max', 'W: 999,999 → 2,000', 999999, 2000], ['player_game:unlimited-on', 'W', false, true],
          ['player_game:ban', 'W: Made-up scores', false, true]] as $n => [$what, $target, $before, $after]) {
    $log .= json_encode(['at' => $now - 300 + $n, 'what' => $what, 'target' => str_replace('W', 'abcdefghijklmnop', $target), 'named' => true,
                         'who' => 'admin', 'player' => 6, 'before' => $before, 'after' => $after], JSON_UNESCAPED_UNICODE) . "\n";
}
file_put_contents('/data/changes.log', $log, FILE_APPEND);
// The kind of device each signs in from, as the platform's login notes it (src/device.php): the two who play with the
// keyboard on the PC client, the rest on phones, and the one with no plays never signed in since it came (no kind): the
// Accounts page's lists name each with it.
$db->exec('CREATE TABLE IF NOT EXISTS PlayerDevice (puid TEXT PRIMARY KEY, kind TEXT NOT NULL, at INTEGER NOT NULL)');
foreach (array_keys($players) as $i) {
    if ($i + 1 !== 10) {
        $db->exec("INSERT OR REPLACE INTO PlayerDevice (puid, kind, at) VALUES ('puid-" . ($i + 1) . "', '" . (in_array($i + 1, [2, 3], true) ? 'pc' : 'android') . "', $now)");
    }
}
echo 'seed: ' . count($players) . ' players, ' . $db->querySingle('SELECT COUNT(*) FROM PlayLog') . " plays\n";
