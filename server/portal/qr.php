<?php
/* The download QR code the APK patcher drew, for the portal on a PC screen. */
require __DIR__ . '/lib.php';
// The way to the app, for those signed in only.
require_sign_in(true);

$svg = APK_DIR . '/download-qr.svg';
if (!is_file($svg)) {
    http_response_code(404);
    exit;
}
header('Content-Type: image/svg+xml');
header('Cache-Control: no-store');
readfile($svg);
