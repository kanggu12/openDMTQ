<?php
/*
 * POST /live/end?ids=... with X-Live-Token: the phone ends its stream (the app is closing). 204; 403
 * when live is off or the token is wrong. See docs/live.md.
 */
require __DIR__ . '/../../portal/live_lib.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    header('Allow: POST');
    exit;
}
// Apache answers 413 for a large body (site.conf) but still runs this script, which must then do nothing.
if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 8192) {
    http_response_code(413);
    exit;
}
live_end_stream((int)live_authorize()['guid']);
http_response_code(204);
