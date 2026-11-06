<?php
/*
 * The game server's one door: every request of the game, its platform SDK and its window that is not a file
 * comes here (site.conf sends them), and is answered by the part named below. Files (songs, charts, jackets, the
 * client's tables) never come here: Apache serves them from the admin's overlay or the imported content.
 *
 *   /DMQ/rpc                   the game's RPC (src/rpc.php)
 *   /api, /accounts, /apps,    the platform SDK (src/platform.php)
 *   /members, /product,
 *   /inspection/status.json
 *   /www/mobile/help           the customer centre page (pages/help.php)
 *   /score                     the game's window: the player's page of the site (pages/score.php)
 *   /djmaxQ                    an older address of that page
 *
 * The live view's three endpoints (live/) have doors of their own in site.conf, with their own size limits.
 */

require_once __DIR__ . '/src/rpc.php';
require_once __DIR__ . '/src/platform.php';

// The path the client asked for, without the query; letter case matters, as it always did.
$path = (string)parse_url((string)($_SERVER['REQUEST_URI'] ?? '/'), PHP_URL_PATH);
// The raw body: the RPC's signature is made over its exact bytes.
$body = (string)file_get_contents('php://input');

// The RPC, also under its old file name and with anything after it (the client never adds more, others did).
if (preg_match('#^/DMQ/rpc(?:\.php)?(?:/.*)?$#', $path)) {
    [$status, $json] = odq_rpc($body);
    odq_send($status, 'application/json', $json);
    return;
}
if (odq_platform($path, $body)) {
    return;
}
if (preg_match('#^/www/mobile/help(?:\.php)?$#', $path)) {
    require __DIR__ . '/pages/help.php';
    return;
}
if (preg_match('#^/score(?:/|/index\.php)?$#', $path)) {
    require __DIR__ . '/pages/score.php';
    return;
}
// Earlier servers kept a score viewer here; the game's window now opens /score.
if (preg_match('#^/djmaxQ(?:/.*)?$#', $path)) {
    header('Location: /score/', true, 302);
    return;
}
// Anything else: the short answer the client only reads the status of.
odq_send(404, 'text/plain; charset=utf-8', "Not Found\n");
