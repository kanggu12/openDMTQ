<?php
/* Hands the newest patched APK to a phone browser (http://<server>/apk). */
require __DIR__ . '/lib.php';

// Locked downloads go through the sign-in page and come back here.
if (!dl_signed_in()) {
    header('Location: /opendmtq/login.php?next=' . rawurlencode('/apk'));
    exit;
}

/* No app to hand out: a page that says why in player words ($message: HTML from t()), with the way
   back home. */
function no_app(int $code, string $message): void
{
    http_response_code($code);
    page_header(t('apk.title'), 'download');
    echo '<section class="card signin"><h2>' . t('apk.title') . '</h2><p class="warn" role="status">' . $message
        . '</p>' . way_out([['/opendmtq/download.php', t('apk.back')]]) . '</section>';
    page_footer();
    exit;
}

$m = apk_manifest();
// When the builder gave up on this address, only the owner can help.
if (!$m) {
    no_app(404, build_failed() ? t('build.failed') : t('apk.notyet'));
}
// An app built for another address cannot reach this server; do not hand it out.
if ($m['host'] !== public_host()) {
    no_app(409, build_failed() ? t('build.failed') : t('apk.stale'));
}
$path = APK_DIR . '/' . basename($m['file']);
// The type Android's installer expects, and a file name that says which server it is for.
header('Content-Type: application/vnd.android.package-archive');
header('Content-Disposition: attachment; filename="' . basename($m['file']) . '"');
header('Content-Length: ' . filesize($path));
header('Cache-Control: no-store');
// A HEAD request (checks, download managers probing) needs the headers only.
if ($_SERVER['REQUEST_METHOD'] === 'HEAD') {
    exit;
}
readfile($path);
