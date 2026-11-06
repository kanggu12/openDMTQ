<?php
/*
 * GET /score/?access_token=<the platform token>&locale=..: the page the game opens in its own window (the
 * event_url of service.getInfo). The site's sign-in first, as every page with players' scores on it; then the
 * player's own page of the site, found by the token's puid (its first part). Without a token, or for a puid the
 * server does not know, the site's rankings.
 */

require_once __DIR__ . '/../../portal/auth.php';
require_once __DIR__ . '/../src/db.php';

// A stranger goes to the sign-in page and comes back here; the game's window keeps the sign-in as a browser does.
require_sign_in();
// The token arrives URL-encoded once more than PHP's own decoding undoes ("5%7C576%7C...").
$token = rawurldecode((string)($_GET['access_token'] ?? ''));
$puid = explode('|', $token)[0];
$member = $puid !== '' ? odq_member_by('puid', $puid) : null;
header('Cache-Control: no-store');
if ($member) {
    header('Location: /opendmtq/player.php?id=' . (int)$member['guid'], true, 302);
} else {
    header('Location: /opendmtq/ranking.php', true, 302);
}
