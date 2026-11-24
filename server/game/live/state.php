<?php
/*
 * GET /live/state?ids=<id1>,<id2>,...&lang=ko|en: what the phone's runtime and the PC player poll. Whether this player
 * is on air (their own switch and the server's), the upload key and settings while so, and a two-line notice to show once,
 * between songs, after every change of either switch; a ban's notice at once, and its words in every answer while it
 * lasts. See docs/live.md.
 */
require __DIR__ . '/../../portal/live_lib.php';

// The notices, by what changed, in the phone's own language: a short title, then where the broadcast and its recording can
// be watched (the site's LIVE page, named by the server's name as the site shows it), or what the server's switch means
// for it. A player hears of every change of their own switch, and of every change of the server's while their own is on:
// "on" and "off" are their own switch flipped while broadcasts are on for the server; "wait" and "held" the same while
// they are off (nothing goes out until the server's are on again); "end" is the server's switch turned off under a player
// switched on. The server's switch turned on under a player switched on is "on" too. "off_unrecorded" is "off" for a
// broadcast with nothing of it to watch again (the admin pages choose it as they switch the player off: no recording
// since the switch went on, or only ones the owner hid), so that its second line says so rather than where a replay
// would be. Phones show both lines in their toast; the PC player draws the first as the title of its card and the second
// under it.
const TOASTS = [
    'ko' => ['on' => "이 플레이를 방송하고 있어요\n%s 사이트 LIVE에서 지금도, 끝난 뒤에도 볼 수 있어요",
             'off' => "방송을 마쳤어요\n%s 사이트 LIVE에서 다시 볼 수 있어요",
             'off_unrecorded' => "방송을 마쳤어요\n다시 볼 영상은 없어요",
             'end' => "방송을 마쳤어요\n이 서버의 방송이 꺼졌어요",
             'wait' => "내 방송이 켜졌어요\n이 서버의 방송이 켜지면 시작해요",
             'held' => "내 방송이 꺼졌어요\n이 서버의 방송이 켜져도 방송하지 않아요"],
    'en' => ['on' => "Broadcasting your play\nWatch it now or later under LIVE on %s",
             'off' => "Your broadcast has ended\nWatch the replay under LIVE on %s",
             'off_unrecorded' => "Your broadcast has ended\nThere is no replay of it",
             'end' => "Your broadcast has ended\nBroadcasts are off on this server",
             'wait' => "Your broadcast is switched on\nIt starts once broadcasts are on for this server",
             'held' => "Your broadcast is switched off\nIt stays off when broadcasts come back on for this server"],
];

// The maintenance notice's changes, told to the players in the game too, between songs: the game itself looks for a notice
// only as it starts, so a player already in it would hear of none. Turned on, a new message while on (with the message, or
// the line below when the owner gave none), and ended.
const MAINT_TOASTS = [
    'ko' => ['maint_on' => "점검 중이에요\n%s", 'maint_changed' => "점검 공지가 바뀌었어요\n%s",
             'maint_off' => "점검이 끝났어요\n평소처럼 플레이할 수 있어요"],
    'en' => ['maint_on' => "Under maintenance\n%s", 'maint_changed' => "Maintenance notice updated\n%s",
             'maint_off' => "Maintenance is over\nThe server is open as usual"],
];
// A banned player's notice, as the ban is made (the admin pages, tools/opendmtq_tools/admin/game.py ban()) and at each
// request of the game's the server refuses (src/player.php odq_ban_notice()): the title, then the owner's reason, with when
// the ban ends where it has an end. The same words go in every answer while the ban lasts ("ban"), for the PC player's
// card, which stays over the game for as long as the game is refused.
const BAN_TOAST = ['ko' => "이 서버에서 플레이할 수 없어요\n%s", 'en' => "You cannot play on this server\n%s"];
const BAN_UNTIL = ['ko' => '%s · %s까지', 'en' => '%s · until %s'];

/* The second line of a banned player's notice: the reason, and the end in the server's zone when the ban has one. */
function live_ban_line(array $ban, string $lang): string
{
    // One line, as the notice has room for: the owner's reason with its line breaks as spaces.
    $reason = trim(preg_replace('/\s+/u', ' ', $ban['reason']) ?? '');
    if ($ban['until'] === null) {
        return $reason;
    }
    $when = $lang === 'ko' ? date('n월 j일 H:i', $ban['until']) : date('M j, H:i', $ban['until']);
    return sprintf(BAN_UNTIL[$lang], $reason, $when);
}

// The line under the title of a notice turned on without a message of the owner's own (DEFAULT_NOTICE, lib.php).
const MAINT_PLAIN = ['ko' => '점검이 끝나면 여기서 다시 알려 드려요', 'en' => 'You will hear here when it is over'];
const MAINT_DEFAULT = 'The server is under maintenance. Please try again later.';
// An end older than this is no news, even to a player it was told to who was away from the game meanwhile: nothing said.
const MAINT_FRESH = 1800;

// Broadcasts on or off for the whole server: while off, nobody is on, whatever their own switch says.
$enabled = live_enabled();
// What the stream should be, for the phone's encoder, by the owner's quality; the same whether on or off. Then what the
// player's own switch and the server's say, and the notice waiting, if any: its words, its number (higher for each new
// one, so a player can tell a new notice from one it showed, even with the same words) and its kind (a key of TOASTS).
$reply = ['on' => false] + live_stream_settings()
    + ['switch' => false, 'broadcasts' => $enabled, 'toast' => '', 'toast_id' => 0, 'toast_kind' => ''];

/*
 * Hands out the player's waiting notice once, in the phone's language, as [words, number, kind]: only the request whose
 * update really cleared it returns it, also when two polls cross. A newer notice written meanwhile (another number) stays
 * for the next poll. A notice of the broadcast waits while the player is in a song, and while the player is banned (it
 * would speak of a broadcast that cannot go out then: it comes after the ban, unless a newer one took its place); a ban's
 * notice comes at once, in a song too, since the game's next request is refused whatever it plays.
 */
function live_take_toast(array $row, ?array $ban = null): array
{
    if ($row['toast'] === '') {
        return ['', 0, ''];
    }
    // A ban's notice only while the ban lasts: one lifted meanwhile is no news.
    if ($row['toast'] === 'ban' && $ban === null) {
        return ['', 0, ''];
    }
    // Any other notice: not in a song, and not while the player is banned.
    if ($row['toast'] !== 'ban' && ($ban !== null || live_in_song($row))) {
        return ['', 0, ''];
    }
    $rw = live_db(true);
    $q = $rw ? @$rw->prepare("UPDATE LiveSwitch SET toast = '' WHERE guid = :g AND toast = :t AND toast_id = :n") : false;
    if (!$q) {
        return ['', 0, ''];
    }
    $q->bindValue(':g', (int)$row['guid'], SQLITE3_INTEGER);
    $q->bindValue(':t', $row['toast'], SQLITE3_TEXT);
    $q->bindValue(':n', (int)$row['toast_id'], SQLITE3_INTEGER);
    if (!@$q->execute() || $rw->changes() !== 1) {
        return ['', 0, ''];
    }
    $lang = ($_GET['lang'] ?? '') === 'ko' ? 'ko' : 'en';
    if ($row['toast'] === 'ban') {
        return [sprintf(BAN_TOAST[$lang], live_ban_line($ban, $lang)), (int)$row['toast_id'], 'ban'];
    }
    if (!isset(TOASTS[$lang][$row['toast']])) {
        return ['', 0, ''];
    }
    // The server's name as the site shows it, from the site's own server_name(): its library is loaded for a notice
    // handed out alone, which is rare, and not for every poll.
    require_once __DIR__ . '/../../portal/lib.php';
    return [sprintf(TOASTS[$lang][$row['toast']], server_name()), (int)$row['toast_id'], (string)$row['toast']];
}

/*
 * Hands out the newest change of the maintenance notice once to this player, as [words, number, kind]: marked in the same
 * write as the player's notice number goes up, so two polls that cross hand it out once. Waits while the player is in a
 * song, as the player's own notices do. A player with no row of the live view yet gets one (switch off, untouched).
 */
function live_take_maintenance(array $row): array
{
    $m = live_maintenance();
    if ($m === null || (int)$row['maint_seen'] >= (int)$m['id'] || live_in_song($row)) {
        return ['', 0, ''];
    }
    // An end long past is no news: nothing said, nothing marked.
    if ($m['kind'] === 'off' && time() - (int)($m['at'] ?? 0) > MAINT_FRESH) {
        return ['', 0, ''];
    }
    // An end is news only to a player this maintenance was told to: one whose game was handed the change that turned it
    // on or a new message of it, numbered from "since" on (songs.py's stamp). A player who comes into the game after it
    // ended, or who heard nothing of it (in a song all through it), never met it: nothing said, nothing marked. A stamp
    // from an older server names no "since": as before.
    if ($m['kind'] === 'off' && is_int($m['since'] ?? null) && (int)$row['maint_seen'] < $m['since']) {
        return ['', 0, ''];
    }
    $rw = live_db(true);
    $q = $rw ? @$rw->prepare("INSERT INTO LiveSwitch (guid, live, toast_id, maint_seen) VALUES (:g, 0, 1, :m)
                              ON CONFLICT (guid) DO UPDATE SET toast_id = LiveSwitch.toast_id + 1, maint_seen = excluded.maint_seen
                              WHERE LiveSwitch.maint_seen < excluded.maint_seen") : false;
    if (!$q) {
        return ['', 0, ''];
    }
    $q->bindValue(':g', (int)$row['guid'], SQLITE3_INTEGER);
    $q->bindValue(':m', (int)$m['id'], SQLITE3_INTEGER);
    if (!@$q->execute() || $rw->changes() !== 1) {
        return ['', 0, ''];
    }
    $number = (int)@$rw->querySingle('SELECT toast_id FROM LiveSwitch WHERE guid = ' . (int)$row['guid']);
    $lang = ($_GET['lang'] ?? '') === 'ko' ? 'ko' : 'en';
    $kind = 'maint_' . $m['kind'];
    // The owner's message on one line under the title; the plain line when they wrote none.
    $message = trim(preg_replace('/\s+/u', ' ', (string)($m['message'] ?? '')) ?? '');
    $message = $message === '' || $message === MAINT_DEFAULT ? MAINT_PLAIN[$lang] : $message;
    return [sprintf(MAINT_TOASTS[$lang][$kind], $message), $number, $kind];
}

$db = live_db();
$row = $db ? live_player($db, live_ids((string)($_GET['ids'] ?? ''))) : null;
// A banned player (src/player.php): never on air, and their switch left as it is for when the ban ends.
$ban = $row ? odq_ban_of((int)$row['guid'], $db) : null;
// New players start switched on when the owner says so (the Broadcasts page, or LIVE_DEFAULT=on before the owner chose),
// with broadcasts on for the server or off: a player whose switch nobody has touched yet has it on, and hears so ("on",
// or "wait" while the server's are off). A row can exist before that, from song tracking; only the admin pages set
// changed_at, and what they set stays.
if ($row && $ban === null && !$row['live'] && live_settings()['new_players']) {
    $rw = live_db(true);
    $token = bin2hex(random_bytes(16));
    $kind = $enabled ? 'on' : 'wait';
    $q = $rw ? @$rw->prepare("INSERT INTO LiveSwitch (guid, live, token, toast, toast_id, changed_at) VALUES (:g, 1, :t, :k, 1, :now)
                              ON CONFLICT (guid) DO UPDATE SET live = 1, token = excluded.token, toast = excluded.toast,
                                  toast_id = LiveSwitch.toast_id + 1, changed_at = excluded.changed_at
                              WHERE LiveSwitch.live = 0 AND LiveSwitch.changed_at IS NULL") : false;
    if ($q) {
        $q->bindValue(':g', (int)$row['guid'], SQLITE3_INTEGER);
        $q->bindValue(':t', $token, SQLITE3_TEXT);
        $q->bindValue(':k', $kind, SQLITE3_TEXT);
        $q->bindValue(':now', time(), SQLITE3_INTEGER);
        if (@$q->execute() && $rw->changes() === 1) {
            // The row as written, its notice's number included.
            $row = live_player($rw, live_ids((string)($_GET['ids'] ?? ''))) ?? $row;
        }
    }
}
if ($row) {
    $reply['switch'] = (bool)$row['live'];
    // On air only with both switches on and no ban; the key goes with it.
    if ($enabled && $ban === null && $row['live'] && (string)$row['token'] !== '') {
        $reply['on'] = true;
        $reply['token'] = $row['token'];
    }
    // The notice waiting for this player, if any, once; with none, the maintenance notice's newest change, once.
    [$reply['toast'], $reply['toast_id'], $reply['toast_kind']] = live_take_toast($row, $ban);
    if ($reply['toast'] === '') {
        [$reply['toast'], $reply['toast_id'], $reply['toast_kind']] = live_take_maintenance($row);
    }
    // The ban's notice in every answer while the ban lasts, in the phone's language, and "" while there is none: the PC
    // player keeps its card over the game for as long as this says so and takes it down at the first answer without it.
    // Only for a player the ids name: an answer that names nobody says nothing of a ban either way (no key at all).
    $lang = ($_GET['lang'] ?? '') === 'ko' ? 'ko' : 'en';
    $reply['ban'] = $ban === null ? '' : sprintf(BAN_TOAST[$lang], live_ban_line($ban, $lang));
}
// Leftovers of stopped streams go now and then; phones poll even when nobody watches.
live_sweep();

header('Content-Type: application/json');
header('Cache-Control: no-store');
// The Korean stays readable in the reply.
echo json_encode($reply, JSON_UNESCAPED_UNICODE);
