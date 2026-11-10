<?php
/* Hands the newest patched APK to a phone browser (http://<server>/apk), whole or from where a broken download stopped. */
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
// Opened now, as windows.php opens the installer: the length said and the bytes sent are the same file's, even if the
// builder swaps in a new build meanwhile (its size, then its bytes by name, could have been two files').
$f = @fopen($path, 'rb');
// Gone since the manifest was read: a new build is taking its place.
if (!$f) {
    no_app(404, build_failed() ? t('build.failed') : t('apk.notyet'));
}
// The type Android's installer expects, and a file name that says which server it is for: whole, or the part a broken
// download asks for to go on, while it is still this build (its SHA-256 says so).
send_download($f, 'application/vnd.android.package-archive', basename($m['file']), download_tag($m, fstat($f)));
