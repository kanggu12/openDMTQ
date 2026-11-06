<?php
/*
 * POST /live/upload?ids=...&seq=<n>&dur=<ms> with X-Live-Token: one MPEG-TS segment from the phone.
 * 204 stored; 403 live is off or the token is wrong (the phone then stops); 400, 411 or 413 a bad request;
 * 503 it could not be stored now (the next one may be). See docs/live.md.
 */
require __DIR__ . '/../../portal/live_lib.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    header('Allow: POST');
    exit;
}
// Who first: a stranger learns nothing about the rest, and nothing of theirs is looked at.
$player = live_authorize();
$guid = (int)$player['guid'];
// Whole numbers only: seq ends up in the playlist's logic and dur in its durations.
$seq = filter_var($_GET['seq'] ?? null, FILTER_VALIDATE_INT, ['options' => ['min_range' => 0, 'max_range' => 2147483647]]);
$dur = filter_var($_GET['dur'] ?? null, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1, 'max_range' => 30000]]);
if ($seq === false || $dur === false) {
    http_response_code(400);
    exit;
}
// The length up front: chunked bodies are refused, because Apache cuts one off at its limit and hands
// PHP the part that fits (it answers 413 itself, yet the script would store that part).
$length = (int)($_SERVER['CONTENT_LENGTH'] ?? -1);
if ($length < 0) {
    http_response_code(411);
    exit;
}
// Apache refuses bigger ones first (site.conf) but still runs this script.
if ($length > LIVE_MAX_BODY) {
    http_response_code(413);
    exit;
}
// A disk nearly full: not read, not written. The phone tries again with its next segment.
if (live_disk_low()) {
    http_response_code(503);
    exit;
}
$body = (string)file_get_contents('php://input', false, null, 0, LIVE_MAX_BODY);
// The connection broke along the way: a cut segment would stall every viewer's player.
if (strlen($body) !== $length) {
    http_response_code(400);
    exit;
}
// MPEG-TS starts with a sync byte: anything else cannot be played. Too little to be video is refused too.
if (strlen($body) < LIVE_MIN_BODY || $body[0] !== "\x47") {
    http_response_code(400);
    exit;
}
// The song being played, for the recording's list.
$song = live_in_song($player) ? [(int)$player['pattern_id'], (int)$player['play_at']] : null;
if (!live_add_segment($guid, $seq, $dur, $body, $song)) {
    http_response_code(503);
    exit;
}
http_response_code(204);
