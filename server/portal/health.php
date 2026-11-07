<?php
/* Machine-readable status for the container healthcheck and `opendmtq doctor`. */
require __DIR__ . '/lib.php';

header('Content-Type: application/json');
header('Cache-Control: no-store');

// This page is asked every 30 seconds whoever else is around: the live view's cleanup can count on it.
live_sweep();

$db = db();
$apk = apk_manifest();
$host = public_host();
$status = [
    'host' => $host,
    'songs' => song_count(),
    // The client data (the client's tables and the images of its screens): without it the game cannot start, with no
    // songs it starts with an empty song list, which is a server that works.
    'game_data' => game_data_present(),
    'patch' => patch_version(),
    'database' => $db !== null,
    'players' => $db ? player_count($db) : null,
    'apk' => $apk ? ['file' => $apk['file'], 'host' => $apk['host'], 'built_at' => $apk['built_at']] : null,
    // The phone can only reach this server if the APK was built for the current address.
    'apk_matches_host' => $apk ? $apk['host'] === $host : null,
];
// Whether visitors are sent to HTTPS, as plain_pages in entrypoint.sh decides it (the admin pages write the site's address so).
$status['https'] = (is_file(odq_https_dir() . '/ca.crt') && !is_file(odq_https_dir() . '/edge-plain')) || getenv('ROUTER_TLS') === 'yes';
// Asset replicas serve files only and have no database of their own.
$status['role'] = getenv('ROLE') ?: 'api';
// The game writes players and scores: a database this server cannot write (data/state owned by
// another user) answers every read and silently loses every save.
$status['writable'] = $status['role'] === 'assets' ? null : (is_writable(DB) && is_writable(dirname(DB)));
$status['ok'] = ($status['role'] === 'assets' || ($status['database'] && $status['writable'])) && $status['game_data'] && $host !== '';
// Unhealthy answers with 503 so the healthcheck fails on it.
http_response_code($status['ok'] ? 200 : 503);
echo json_encode($status, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), "\n";
