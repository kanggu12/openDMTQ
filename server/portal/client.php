<?php
/* What the PC client (the launcher, client/opendmtq_client) asks the site, as JSON:

     GET  client.php?about    whether this is an OpenDMTQ server, and its name and address (no sign-in)
     POST client.php?signin   an account's ID and password (user, password): the site's sign-in cookie, as the sign-in
                              page gives a browser, which the launcher keeps instead of the password; 403 {"error":
                              "banned", ...} for a banned player's account, 403 {"error": "off"} for an account switched
                              off on the Accounts page (both said only after the right password)
     GET  client.php?app      the app on offer for this address, to download from /apk (signed in)
     POST client.php?link     a one-time link that signs a browser in to the same account and opens the player's page
                              (My page on the site): {"url", "page", "expires"} (signed in)
     GET  client.php?records  the account's player's latest plays and best records, each with its place on the chart
                              and the keyboard's mark, as the player's page lists them (signed in)
     POST client.php?claim    device: the PC's game player linked to the account, at the launcher's first PLAY, when
                              the account has no player and that player no account (client_claim): {"linked", "now",
                              "player"} or {"linked": false, "why"} (signed in; from 0.11.3)

   The app itself comes from /apk with the cookie, as a phone's browser gets it. */
require __DIR__ . '/lib.php';

// How many of each list the launcher's PLAY page shows: a few, the rest is on the player's page.
const CLIENT_RECORDS = 5;

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
    // The account the ID and the password are right for, on or switched off (site_password_row, as login.php asks it).
    $row = site_password_row($user, $password);
    if ($row !== null && $row['off']) {
        // The right password of an account switched off on the Accounts page: not a guess, and no sign-in; answered in
        // its own word, to whoever knows the password alone (a wrong one is told only that it is wrong), as the sign-in
        // page says it. The launcher shows its own line for it (server.py, error.signin.off).
        dl_attempt_succeeded($attempt);
        answer(403, ['error' => 'off']);
    }
    $who = $row !== null ? (string)$row['name'] : null;
    if ($who === null) {
        // A wrong password takes a second, as on the sign-in page.
        sleep(1);
        answer(401, ['error' => 'wrong']);
    }
    dl_attempt_succeeded($attempt);
    // A banned player's account: no sign-in, with the owner's reason and the end when there is one (Unix time, or null).
    $ban = site_ban($row);
    if ($ban !== null) {
        answer(403, ['error' => 'banned', 'reason' => $ban['reason'], 'until' => $ban['until']]);
    }
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

if (isset($_GET['link'])) {
    // A link is a sign-in: asked for with a POST, as client.php?signin is.
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        answer(405, ['error' => 'post']);
    }
    $who = site_user();
    if ($who === null) {
        answer(403, ['error' => 'signin']);
    }
    // MY PAGE, the account's own page: its game player's profile, plays and records when the account is linked to one,
    // and the account's settings in any case (the owner's account, linked to no player, included).
    $page = '/opendmtq/me.php';
    $token = once_issue($who, $page);
    if ($token === null) {
        answer(503, ['error' => 'down']);
    }
    answer(200, ['url' => '/opendmtq/login.php?once=' . $token, 'page' => $page, 'expires' => time() + ONCE_LIFE]);
}

if (isset($_GET['records'])) {
    $who = site_user();
    if ($who === null) {
        answer(403, ['error' => 'signin']);
    }
    $me = site_me();
    $db = db();
    // An account linked to no game player has no records of its own to show: said so, with nothing in the lists.
    $figures = ($me !== null && $db) ? player_figures($db, $me) : null;
    if ($me === null || !$figures) {
        answer(200, ['account' => $who, 'player' => null, 'recent' => [], 'best' => []]);
    }
    answer(200, ['account' => $who, 'player' => ['id' => $me, 'name' => (string)$figures['name'], 'rank' => $figures['rank'],
        'total' => (int)$figures['total'], 'charts' => (int)$figures['charts']], 'page' => '/opendmtq/player.php?id=' . $me]
        + client_records($db, $me));
}

if (isset($_GET['claim'])) {
    // A link is a change: asked for with a POST, as client.php?signin is.
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        answer(405, ['error' => 'post']);
    }
    $who = site_user();
    if ($who === null) {
        answer(403, ['error' => 'signin']);
    }
    $claimed = client_claim($who, (string)($_POST['device'] ?? ''));
    if ($claimed === null) {
        answer(503, ['error' => 'down']);
    }
    answer(200, $claimed);
}

answer(404, ['error' => 'unknown']);

/* The signed-in account $who linked to the game player who plays by $device on this server, at the PC client's first
   PLAY: $device is the id the PC's game signs in by (its platform login's udid), which makes whoever holds it that player
   in the game. Linked only when the account has no player and that player has no account either; never the owner's
   account (kept in .env, linked to no player) or a banned player's. One statement makes the link and checks both, so
   that two launchers at once never link one player twice. ['linked' => true, 'now' => true when this call made it,
   'player' => ['id', 'name']] for an account that has its player; ['linked' => false, 'why' => 'none' (no player plays by
   that id yet), 'taken' (another account has that player), 'owner' or 'banned']; null when the database cannot be
   written. A link made goes in the admin pages' log of changes, as MY PAGE's changes do. */
function client_claim(string $who, string $device): ?array
{
    // The database that writes and the change log's line, as MY PAGE has them.
    require_once __DIR__ . '/me_lib.php';
    $owner = site_owner();
    if ($owner !== null && strcasecmp($owner['name'], $who) === 0) {
        return ['linked' => false, 'why' => 'owner'];
    }
    $db = me_db_write();
    if ($db === null) {
        return null;
    }
    // The player of a name, as the site names one: a new player's blank nickname as its number.
    $named = function (int $guid) use ($db): array {
        $row = rows($db, 'SELECT nickname FROM Member WHERE CAST(guid AS INTEGER) = :g ORDER BY (id = :g) DESC, id ASC LIMIT 1',
            [':g' => $guid])[0] ?? [];
        return ['id' => $guid, 'name' => player_name(['nickname' => $row['nickname'] ?? '', 'id' => $guid])];
    };
    $mine = rows($db, 'SELECT guid FROM SiteUser WHERE name = :name', [':name' => $who])[0] ?? null;
    if ($mine === null) {
        // Not an account of the table (it went a moment ago): nothing to link.
        return ['linked' => false, 'why' => 'none'];
    }
    if ($mine['guid'] !== null) {
        // Linked already, by the owner or an earlier PLAY: as it is.
        return ['linked' => true, 'now' => false, 'player' => $named((int)$mine['guid'])];
    }
    // The player the game of this id signs in as, as its platform login finds the account (the first row of the id), a
    // player of the server's (never the server's own check account); an id of no form a phone or a PC gives is nobody's.
    $found = preg_match('/^[A-Za-z0-9_-]{1,64}$/', $device) ? rows($db,
        'SELECT CAST(guid AS INTEGER) AS guid FROM Member WHERE udid = :u AND udid IS NOT :check AND guid IS NOT NULL ORDER BY rowid LIMIT 1',
        [':u' => $device, ':check' => CHECK_UDID])[0] ?? null : null;
    if ($found === null || (int)$found['guid'] <= 0) {
        return ['linked' => false, 'why' => 'none'];
    }
    $guid = (int)$found['guid'];
    if (odq_ban_of($guid, $db) !== null) {
        // Linked, the account would be refused as the player is: the owner links one by hand on the Accounts page.
        return ['linked' => false, 'why' => 'banned'];
    }
    $q = @$db->prepare('UPDATE SiteUser SET guid = :g WHERE name = :name AND guid IS NULL
                         AND NOT EXISTS (SELECT 1 FROM SiteUser WHERE guid = :g)');
    if (!$q) {
        return null;
    }
    $q->bindValue(':g', $guid, SQLITE3_INTEGER);
    $q->bindValue(':name', $who, SQLITE3_TEXT);
    if (!@$q->execute()) {
        return null;
    }
    if ($db->changes() === 1) {
        $player = $named($guid);
        me_note('site:claim', $who . ' > ' . $player['name'], $who);
        return ['linked' => true, 'now' => true, 'player' => $player];
    }
    // Not made: the account got its player meanwhile (another launcher's PLAY), or that player has an account.
    $mine = rows($db, 'SELECT guid FROM SiteUser WHERE name = :name', [':name' => $who])[0] ?? null;
    return $mine !== null && $mine['guid'] !== null ? ['linked' => true, 'now' => false, 'player' => $named((int)$mine['guid'])]
        : ['linked' => false, 'why' => 'taken'];
}

/* A player's latest plays and best records as the PC client shows them, CLIENT_RECORDS of each: the chart (its song's
   title and its name in the game's words), the score, the grade, whether the keyboard played it, and the player's place
   on that chart's leaderboard (as song.php ranks it: by score, then accuracy, then the older account) out of how many
   have a record there; a play also when it was and whether it set a record, a best when it was set (null for records
   older than the play log). */
function client_records(SQLite3 $db, int $me): array
{
    $charts = charts();
    $songs = songs_by_id();
    // The chart as a list names it; a chart the song list has no more stays by its number.
    $chart = function (int $pid) use ($charts, $songs): array {
        [$sid, $line, $diff, $sig] = $charts[$pid] ?? [0, 0, 0, 0];
        $song = $songs[$sid] ?? null;
        return ['chart' => $pid, 'title' => $song ? song_title($song) : null,
            'chart_name' => $song ? chart_label($line, $diff, $sig) : null];
    };
    // Each chart's place once, from the player's best there: [place, how many have a record].
    $places = [];
    $place = function (int $pid) use ($db, $me, &$places): array {
        if (!isset($places[$pid])) {
            $mine = rows($db, 'SELECT score, judgement FROM Play WHERE user_id = :me AND pattern_id = :pid', [':me' => $me, ':pid' => $pid])[0] ?? null;
            $all = rows($db, "SELECT COUNT(*) AS n FROM Play p JOIN (" . PLAYER_ROWS . ") m ON m.guid = p.user_id WHERE p.pattern_id = :pid",
                [':check' => CHECK_UDID, ':pid' => $pid])[0]['n'] ?? 0;
            $ahead = $mine === null ? null : rows($db,
                "SELECT COUNT(*) AS n FROM Play p JOIN (" . PLAYER_ROWS . ") m ON m.guid = p.user_id
                  WHERE p.pattern_id = :pid AND (p.score > :score OR (p.score = :score AND p.judgement > :j)
                        OR (p.score = :score AND p.judgement = :j AND p.user_id < :me))",
                [':check' => CHECK_UDID, ':pid' => $pid, ':score' => (int)$mine['score'], ':j' => (int)$mine['judgement'], ':me' => $me])[0]['n'] ?? 0;
            $places[$pid] = [$ahead === null ? null : (int)$ahead + 1, (int)$all];
        }
        return $places[$pid];
    };
    $recent = [];
    if (has_playlog($db)) {
        foreach (rows($db, 'SELECT * FROM PlayLog WHERE user_id = :me ORDER BY played_at DESC, id DESC LIMIT ' . CLIENT_RECORDS, [':me' => $me]) as $r) {
            [$rank, $of] = $place((int)$r['pattern_id']);
            $recent[] = $chart((int)$r['pattern_id']) + ['score' => (int)$r['score'], 'grade' => (string)$r['grade'],
                'keys' => !empty($r['keys']), 'new_record' => (bool)$r['is_record'], 'at' => (int)$r['played_at'],
                'rank' => $rank, 'players' => $of];
        }
    }
    // When each best was set: the newest play that set a record on its chart.
    $set_at = [];
    if (has_playlog($db)) {
        foreach (rows($db, 'SELECT pattern_id, MAX(played_at) AS at FROM PlayLog WHERE user_id = :me AND is_record = 1 GROUP BY pattern_id', [':me' => $me]) as $r) {
            $set_at[(int)$r['pattern_id']] = (int)$r['at'];
        }
    }
    $best = [];
    foreach (rows($db, 'SELECT * FROM Play WHERE user_id = :me ORDER BY score DESC, pattern_id ASC LIMIT ' . CLIENT_RECORDS, [':me' => $me]) as $r) {
        [$rank, $of] = $place((int)$r['pattern_id']);
        $best[] = $chart((int)$r['pattern_id']) + ['score' => (int)$r['score'], 'grade' => (string)$r['grade'],
            'keys' => !empty($r['keys']), 'all_combo' => ($r['isAllCombo'] ?? 'N') === 'Y',
            'perfect_play' => ($r['isPerfectPlay'] ?? 'N') === 'Y', 'set_at' => $set_at[(int)$r['pattern_id']] ?? null,
            'rank' => $rank, 'players' => $of];
    }
    return ['recent' => $recent, 'best' => $best];
}
