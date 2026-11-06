<?php
/* The app's own launcher icon, as the builder took it out of the app: for the download page's last step. */
require __DIR__ . '/lib.php';
require_sign_in(true);

$icon = APK_DIR . '/app-icon.png';
if (!is_file($icon)) {
    http_response_code(404);
    exit;
}
header('Content-Type: image/png');
header('Cache-Control: private, max-age=86400');
readfile($icon);
