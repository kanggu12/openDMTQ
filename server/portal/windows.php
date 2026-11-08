<?php
/* Hands the player for Windows, with this server's app in it, to a computer's browser (http://<server>/windows). */
require __DIR__ . '/lib.php';

// Locked like the app: through the sign-in page, and back to the download page.
if (!dl_signed_in()) {
    header('Location: /opendmtq/login.php?next=' . rawurlencode('/windows'));
    exit;
}
$m = apk_manifest();
$w = windows_player();
// None for this address (no player on this server, or the app is being built again): the download page says what
// there is.
if (!$m || $m['host'] !== public_host() || !$w) {
    header('Location: /opendmtq/download.php');
    exit;
}
$path = APK_DIR . '/' . basename($w['file']);
// A zip, under a file name that says which server it is for.
header('Content-Type: application/zip');
header('Content-Disposition: attachment; filename="' . basename($w['file']) . '"');
header('Content-Length: ' . filesize($path));
header('Cache-Control: no-store');
// A HEAD request (checks, download managers probing) needs the headers only.
if ($_SERVER['REQUEST_METHOD'] === 'HEAD') {
    exit;
}
readfile($path);
