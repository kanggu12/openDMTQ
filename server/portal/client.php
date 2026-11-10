<?php
/* What the PC client (the launcher, client/opendmtq_client) asks the site, as JSON:

     GET  client.php?about    whether this is an OpenDMTQ server, and its name and address (no sign-in)
     POST client.php?signin   an account's ID and password (user, password): the site's sign-in cookie, as the sign-in
                              page gives a browser, which the launcher keeps instead of the password
     GET  client.php?app      the app on offer for this address, to download from /apk (signed in)

   The app itself comes from /apk with the cookie, as a phone's browser gets it. */
require __DIR__ . '/lib.php';

/* One answer as JSON with its status, and the end. Never kept by a cache: each says how things stand now. */
function answer(int $status, array $body): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

// A browser's request from another site (it says so) is no launcher's: nobody's browser gets signed in from elsewhere.
// The same rule as the sign-in page's (auth.php).
if (from_another_site()) {
    answer(403, ['error' => 'cross-site']);
}

if (isset($_GET['about'])) {
    $m = apk_manifest();
    // The app is there for this address, and the builder has not given up on it.
    $app = $m && $m['host'] === public_host() && !build_failed();
    answer(200, ['opendmtq' => server_version()[0], 'name' => server_name(), 'address' => public_host(), 'app' => (bool)$app]);
}

if (isset($_GET['signin'])) {
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        answer(405, ['error' => 'post']);
    }
    $user = trim((string)($_POST['user'] ?? ''));
    $password = (string)($_POST['password'] ?? '');
    // As the sign-in page does it (login.php): the same throttle, the same check, the same cookie.
    if (!site_sign_in_works()) {
        answer(503, ['error' => 'down']);
    }
    // For the account named: one with admin rights counts toward the limit for the whole server as well.
    $attempt = dl_attempt_begin($user);
    if ($attempt === null) {
        answer(429, ['error' => 'throttled']);
    }
    $who = site_check($user, $password);
    if ($who === null) {
        // A wrong password takes a second, as on the sign-in page.
        sleep(1);
        answer(401, ['error' => 'wrong']);
    }
    dl_attempt_succeeded($attempt);
    dl_sign_in($who);
    answer(200, ['account' => $who, 'expires' => time() + DL_DAYS * 86400]);
}

if (isset($_GET['app'])) {
    if (!dl_signed_in()) {
        answer(403, ['error' => 'signin']);
    }
    $m = apk_manifest();
    if (!$m) {
        answer(build_failed() ? 503 : 404, ['error' => build_failed() ? 'failed' : 'none']);
    }
    // Built for another address: it cannot reach this server (the builder is making the one for this address).
    if ($m['host'] !== public_host()) {
        answer(build_failed() ? 503 : 409, ['error' => build_failed() ? 'failed' : 'stale']);
    }
    answer(200, ['file' => basename((string)$m['file']), 'sha256' => (string)($m['sha256'] ?? ''), 'size' => (int)($m['size'] ?? 0),
        'built_at' => (string)($m['built_at'] ?? ''), 'label' => (string)($m['label'] ?? app_name()), 'package' => (string)($m['package'] ?? ''),
        'address' => public_host()]);
}

answer(404, ['error' => 'unknown']);
