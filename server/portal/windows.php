<?php
/* Hands the installer for Windows (the PC client) to a computer's browser (http://<server>/windows), set up for this
   server: its address on the installer's end, which the installer reads to point the launcher here. Whole, or from where
   a broken download stopped. */
require __DIR__ . '/lib.php';

// Locked like the app: through the sign-in page, and back to the download page.
if (!dl_signed_in()) {
    header('Location: /opendmtq/login.php?next=' . rawurlencode('/windows'));
    exit;
}
$w = windows_client();
// None on this server: the download page says what there is.
if (!$w) {
    header('Location: /opendmtq/download.php');
    exit;
}
$path = APK_DIR . '/' . basename((string)$w['file']);
// Opened now: the length said and the bytes sent are the same file's, even if the builder swaps it meanwhile.
$f = @fopen($path, 'rb');
if (!$f) {
    header('Location: /opendmtq/download.php');
    exit;
}
$tail = windows_preset();
// A Windows program, under a file name that says which server it is for: the installer and its end as one file, whole or
// the part a broken download asks for to go on, while it is still this installer with this end (its tag covers both).
send_download($f, 'application/vnd.microsoft.portable-executable', windows_download_name(), download_tag($w, fstat($f), $tail), $tail);
