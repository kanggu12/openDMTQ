<?php
/*
 * GET /live/state?ids=<id1>,<id2>,...&lang=ko|en: what the phone's runtime polls. Whether the owner
 * shows this player live, the upload key and settings while so, and a one-line notice to show once,
 * between songs. See docs/live.md.
 */
require __DIR__ . '/../../portal/live_lib.php';

// The notices, by what the owner did. Shown by the game in the phone's own language.
const TOASTS = [
    'ko' => ['on' => '웹에서 이 플레이를 방송합니다', 'off' => '방송이 꺼졌습니다'],
    'en' => ['on' => 'Your play is now broadcast on the web', 'off' => 'Your broadcast is off'],
];

// What the stream should be, for the phone's encoder; the same whether on or off.
$reply = ['on' => false, 'fps' => 30, 'height' => 720, 'bitrate' => 2000000, 'segment' => 2, 'toast' => ''];

$db = live_db();
$row = $db ? live_player($db, live_ids((string)($_GET['ids'] ?? ''))) : null;
// LIVE_DEFAULT=on: a player whose switch nobody has touched yet has it on, with the usual notice. A row can
// exist before that, from song tracking; only the admin pages set changed_at, and what they set stays.
if ($row && !$row['live'] && getenv('LIVE_DEFAULT', true) === 'on') {
    $rw = live_db(true);
    $token = bin2hex(random_bytes(16));
    $q = $rw ? @$rw->prepare("INSERT INTO LiveSwitch (guid, live, token, toast, changed_at) VALUES (:g, 1, :t, 'on', :now)
                              ON CONFLICT (guid) DO UPDATE SET live = 1, token = excluded.token, toast = 'on',
                                  changed_at = excluded.changed_at
                              WHERE LiveSwitch.live = 0 AND LiveSwitch.changed_at IS NULL") : false;
    if ($q) {
        $q->bindValue(':g', (int)$row['guid'], SQLITE3_INTEGER);
        $q->bindValue(':t', $token, SQLITE3_TEXT);
        $q->bindValue(':now', time(), SQLITE3_INTEGER);
        if (@$q->execute() && $rw->changes() === 1) {
            $row['live'] = 1;
            $row['token'] = $token;
            $row['toast'] = 'on';
        }
    }
}
if ($row) {
    if ($row['live'] && (string)$row['token'] !== '') {
        $reply['on'] = true;
        $reply['token'] = $row['token'];
    }
    // A notice waits while the player is in a song, and is handed out once: only the request whose
    // update really cleared it returns it, also when two polls cross.
    if ($row['toast'] !== '' && !live_in_song($row)) {
        $rw = live_db(true);
        $q = $rw ? @$rw->prepare("UPDATE LiveSwitch SET toast = '' WHERE guid = :g AND toast = :t") : false;
        if ($q) {
            $q->bindValue(':g', (int)$row['guid'], SQLITE3_INTEGER);
            $q->bindValue(':t', $row['toast'], SQLITE3_TEXT);
            if (@$q->execute() && $rw->changes() === 1) {
                $lang = ($_GET['lang'] ?? '') === 'ko' ? 'ko' : 'en';
                $reply['toast'] = TOASTS[$lang][$row['toast']] ?? '';
            }
        }
    }
}
// Leftovers of stopped streams go now and then; phones poll even when nobody watches.
live_sweep();

header('Content-Type: application/json');
header('Cache-Control: no-store');
// The Korean stays readable in the reply.
echo json_encode($reply, JSON_UNESCAPED_UNICODE);
