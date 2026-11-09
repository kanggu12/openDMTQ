<?php
/* Hands the installer for Windows (the PC client) to a computer's browser (http://<server>/windows), set up for this
   server: its address on the installer's end, which the installer reads to point the launcher here. */
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
// A Windows program, under a file name that says which server it is for, as long as the installer and its end together.
header('Content-Type: application/vnd.microsoft.portable-executable');
header('Content-Disposition: attachment; filename="' . windows_download_name() . '"');
header('Content-Length: ' . (fstat($f)['size'] + strlen($tail)));
header('Cache-Control: no-store');
// A HEAD request (checks, download managers probing) needs the headers only.
if ($_SERVER['REQUEST_METHOD'] === 'HEAD') {
    exit;
}
fpassthru($f);
fclose($f);
echo $tail;
