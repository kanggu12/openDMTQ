<?php
/*
 * GET /live/state?ids=<id1>,<id2>,...&lang=ko|en: what the phone's runtime polls. Whether the owner
 * shows this player live, the upload key and settings while so, and a two-line notice to show once,
 * between songs. See docs/live.md.
 */
require __DIR__ . '/../../portal/live_lib.php';

// The notices, by what the owner did, in the phone's own language: a short title, then where the broadcast and its
// recording can be watched (the site's LIVE page, named by the server's name as the site shows it). "on" and "off" follow
// the player's own switch; "end" is for a player on air when the owner turned broadcasts off for the whole server, whose
// site then shows nothing of them. Phones show both lines in their toast; the PC player draws the first as the title of
// its card and the second under it.
const TOASTS = [
    'ko' => ['on' => "지금 이 플레이를 라이브로 방송하고 있어요\n%s 사이트의 LIVE에서 지금도, 끝난 뒤에도 볼 수 있어요",
             'off' => "방송을 마쳤어요\n지난 방송은 %s 사이트의 LIVE에서 다시 볼 수 있어요",
             'end' => "방송을 마쳤어요\n이 서버의 방송이 지금은 꺼져 있어요"],
    'en' => ['on' => "Your play is live now\nWatch it live or later under LIVE on %s",
             'off' => "Your broadcast has ended\nWatch the replay under LIVE on %s",
             'end' => "Your broadcast has ended\nBroadcasts are off on this server for now"],
];

// What the stream should be, for the phone's encoder, by the owner's quality; the same whether on or off.
$reply = ['on' => false] + live_stream_settings() + ['toast' => ''];

/*
 * Hands out the player's waiting notice once, in the phone's language: only the request whose update really cleared it
 * returns it, also when two polls cross. It waits while the player is in a song. `$only` limits it to that notice.
 */
function live_take_toast(array $row, ?string $only = null): string
{
    if ($row['toast'] === '' || ($only !== null && $row['toast'] !== $only) || live_in_song($row)) {
        return '';
    }
    $rw = live_db(true);
    $q = $rw ? @$rw->prepare("UPDATE LiveSwitch SET toast = '' WHERE guid = :g AND toast = :t") : false;
    if (!$q) {
        return '';
    }
    $q->bindValue(':g', (int)$row['guid'], SQLITE3_INTEGER);
    $q->bindValue(':t', $row['toast'], SQLITE3_TEXT);
    if (!@$q->execute() || $rw->changes() !== 1) {
        return '';
    }
    $lang = ($_GET['lang'] ?? '') === 'ko' ? 'ko' : 'en';
    // The server's name as the site shows it, from the site's own server_name(): its library is loaded for a notice
    // handed out alone, which is rare, and not for every poll.
    require_once __DIR__ . '/../../portal/lib.php';
    return isset(TOASTS[$lang][$row['toast']]) ? sprintf(TOASTS[$lang][$row['toast']], server_name()) : '';
}

// Broadcasts off for the whole server: off for everyone, and nothing else written. The switches stay as they are. A
// player who was on air when the owner turned broadcasts off hears once that it ended, and that broadcasts are off for
// now (the admin pages leave that notice, "end"); one whose switch is on hears of it again once broadcasts are back on.
if (!live_enabled()) {
    $db = live_db();
    $row = $db ? live_player($db, live_ids((string)($_GET['ids'] ?? ''))) : null;
    if ($row) {
        $reply['toast'] = live_take_toast($row, 'end');
    }
    // Leftovers of the streams that stopped go all the same.
    live_sweep();
    header('Content-Type: application/json');
    header('Cache-Control: no-store');
    echo json_encode($reply, JSON_UNESCAPED_UNICODE);
    exit;
}

$db = live_db();
$row = $db ? live_player($db, live_ids((string)($_GET['ids'] ?? ''))) : null;
// New players start switched on when the owner says so (the Broadcasts page, or LIVE_DEFAULT=on before the owner chose):
// a player whose switch nobody has touched yet has it on, with the usual notice. A row can exist before that, from song
// tracking; only the admin pages set changed_at, and what they set stays.
if ($row && !$row['live'] && live_settings()['new_players']) {
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
    // The notice waiting for this player, if any, once.
    $reply['toast'] = live_take_toast($row);
}
// Leftovers of stopped streams go now and then; phones poll even when nobody watches.
live_sweep();

header('Content-Type: application/json');
header('Cache-Control: no-store');
// The Korean stays readable in the reply.
echo json_encode($reply, JSON_UNESCAPED_UNICODE);
