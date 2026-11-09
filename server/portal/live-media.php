<?php
/*
 * The live view's playlist and segments, for signed-in visitors only:
 * /opendmtq/live-media.php/<guid>/index.m3u8 and /opendmtq/live-media.php/<guid>/<n>.ts. The files
 * sit outside anything Apache serves; the playlist names its segments relatively, so they come back
 * through here. Recordings the same way, /opendmtq/live-media.php/rec/<guid>/<id>/..., only those the
 * owner has not hidden.
 */
require __DIR__ . '/lib.php';

// The same sign-in as the app download.
if (!dl_signed_in()) {
    http_response_code(403);
    exit;
}
// Broadcasts off for the whole server: none is shown, live or recorded, whatever is on the disk.
if (!live_enabled()) {
    http_response_code(404);
    exit;
}
// A recording: exactly these shapes as well. Gone as soon as the owner hides or deletes it.
if (preg_match('#^/rec/(\d{1,12})/(\d{1,12})/(index\.m3u8|\d{1,12}\.ts)$#', (string)($_SERVER['PATH_INFO'] ?? ''), $m)) {
    $rec = live_rec_path((int)$m[1], (int)$m[2]);
    $path = "$rec/$m[3]";
    if (!is_file($path) || is_file("$rec/.open") || is_file("$rec/.hidden")) {
        http_response_code(404);
        exit;
    }
    header('Content-Type: ' . ($m[3] === 'index.m3u8' ? 'application/vnd.apple.mpegurl' : 'video/mp2t'));
    // The list is asked for each time: a recording may be hidden a moment from now, and then nobody new gets to it. Its
    // segments never change: this browser keeps them, so that going back in a recording costs the server's connection
    // nothing. Not shared caches: they are behind the sign-in.
    header('Cache-Control: ' . ($m[3] === 'index.m3u8' ? 'no-store' : 'private, max-age=86400, immutable'));
    header('Content-Length: ' . filesize($path));
    readfile($path);
    exit;
}
// Exactly these two shapes: a number and a file name made of digits. Nothing else reaches the disk.
if (!preg_match('#^/(\d{1,12})/(index\.m3u8|\d{1,12}\.ts)$#', (string)($_SERVER['PATH_INFO'] ?? ''), $m)) {
    http_response_code(404);
    exit;
}
[, $guid, $file] = $m;
$guid = (int)$guid;
// Once the owner switches live off, nothing more is shown, also of what is still on disk.
$db = db();
$on = $db ? @$db->querySingle("SELECT live FROM LiveSwitch WHERE guid = $guid") : null;
if (!$on) {
    http_response_code(404);
    exit;
}
$path = live_folder($guid) . "/$file";
if (!is_file($path)) {
    http_response_code(404);
    exit;
}
if ($file === 'index.m3u8') {
    $m3u = (string)@file_get_contents($path);
    // A phone that went silent never says the stream ended: after a while players are told, instead
    // of waiting for more.
    $s = live_stream($guid);
    if ($s && !$s['ended'] && time() - (int)$s['updated'] >= LIVE_STOPPED) {
        $m3u .= "#EXT-X-ENDLIST\n";
    }
    header('Content-Type: application/vnd.apple.mpegurl');
    // Changes with every segment.
    header('Cache-Control: no-store');
    header('Content-Length: ' . strlen($m3u));
    echo $m3u;
    exit;
}
header('Content-Type: video/mp2t');
// A segment's number is never reused, so it may be kept for a moment; not by shared caches.
header('Cache-Control: private, max-age=60');
header('Content-Length: ' . filesize($path));
readfile($path);
