<?php
/* Shared facts for the portal pages: server address, content, database, and the latest APK. */

// Who is live: the menu on every page says so.
require_once __DIR__ . '/live_lib.php';

// Where everything is: the game server's settings, which every part of the server shares.
require_once __DIR__ . '/../game/src/config.php';
// The database, and the folder the APK builder writes to.
if (!defined('DB')) {
    define('DB', odq_db_path());
}
define('APK_DIR', odq_apk_dir());
// Account the self-check logs in with; never listed as a player.
const CHECK_UDID = 'opendmtq-check';
// The sign-in: who a browser is signed in as, and the gate of every page with content.
require_once __DIR__ . '/auth.php';

/* ---------------------------------------------------------------------- language */

// The chosen language, shared with the admin pages (LANG_COOKIE in tools/opendmtq_tools/admin): a year.
const LANG_COOKIE = 'opendmtq_lang';
const LANG_DAYS = 365;

/* The page language: what the visitor chose in the switch (lang.php), else English. The browser's language does not
   decide: everyone first sees the same site, and the switch is on every page. */
function lang(): string
{
    static $lang = null;
    if ($lang === null) {
        $chosen = (string)($_COOKIE[LANG_COOKIE] ?? '');
        $lang = $chosen === 'ko' ? 'ko' : 'en';
    }
    return $lang;
}

// Every text of the site, in each language: a file of its own, since it is most of the site's words.
require_once __DIR__ . '/strings.php';

/* The text for $key in the page language (English when Korean lacks it), with {name} filled in
   from $vars, escaped. Placeholders without a value stay, for scripts that fill them later. */
function t(string $key, array $vars = []): string
{
    $text = STRINGS[lang()][$key] ?? STRINGS['en'][$key] ?? $key;
    $fill = [];
    foreach ($vars as $name => $value) {
        $fill['{' . $name . '}'] = h($value);
    }
    return strtr($text, $fill);
}

/* The address the game is sent to. */
function public_host(): string
{
    return getenv('PUBLIC_HOST') ?: ($_SERVER['PUBLIC_HOST'] ?? '');
}

/* The version of OpenDMTQ this server runs, as ["2026.11.02", "c1371df"] (the date and commit of its code, which the CLI
   passes on), or as far as it is known: ["1.2.0", ""] from a released image, ["", ""] with nothing passed on. */
function server_version(): array
{
    $v = trim((string)getenv('OPENDMTQ_VERSION'));
    return array_pad(explode('-', $v, 2), 2, '');
}

/* The version beside the big wordmark. Nothing when it is not known. */
function server_version_block(): string
{
    [$version, $commit] = server_version();
    if ($version === '') {
        return '';
    }
    // The commit is of no use to a player: for whoever asks, under the pointer.
    return '<div class="server-ver"' . ($commit !== '' ? ' title="' . h($commit) . '"' : '') . '><span>SERVER</span><b>v' . h($version) . '</b></div>';
}

/* The server's name in the app's title, as patch_apk.server_name() decides for this address: SERVER_NAME,
   or the address exactly as set, port included (several servers can share a host). */
function server_name(): string
{
    // The process's own environment: to plain getenv(), under Apache, SERVER_NAME is the visitor's host name.
    return trim((string)getenv('SERVER_NAME', true)) ?: public_host();
}

/* The app's name on players' devices. Plain text: t() escapes what it fills in. */
function app_name(): string
{
    return 'TECHNIKA Q (' . server_name() . ')';
}

/* The app's name as HTML, styled as a name (style.css .app-name): the title, then the server's name in pieces
   that stay whole, so a long address wraps after a dot or before the port and never at a hyphen. */
function app_name_html(): string
{
    $pieces = preg_split('/(?<=[.\s])|(?=:\d+$)/u', server_name(), -1, PREG_SPLIT_NO_EMPTY);
    $parts = array_map(fn($piece) => '<span>' . h($piece) . '</span>', $pieces ?: [server_name()]);
    return '<span class="app-name">TECHNIKA Q <span class="addr">(' . implode('<wbr>', $parts) . ')</span></span>';
}

/* True when the address is a private IPv4 address: phones must share the server's network. */
function lan_only(string $address): bool
{
    $host = preg_replace('/:\d+$/', '', $address);
    return filter_var($host, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)
        && !filter_var($host, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE);
}

/* Manifest of the newest patched APK, or null when none was built yet. */
function apk_manifest(): ?array
{
    $raw = @file_get_contents(APK_DIR . '/latest.json');
    $m = $raw ? json_decode($raw, true) : null;
    // Only trust a manifest whose file is really there.
    return ($m && is_file(APK_DIR . '/' . basename($m['file']))) ? $m : null;
}

/* True when the builder gave up on the app for this address (data/apk/out/build.json says failed,
   or still says building long after any build ends): waiting for it is pointless. With no such
   file (an older builder) the portal keeps waiting as before. */
function build_failed(): bool
{
    $s = json_decode((string)@file_get_contents(APK_DIR . '/build.json'), true);
    if (!is_array($s) || ($s['host'] ?? null) !== public_host()) {
        return false;
    }
    return ($s['state'] ?? '') === 'failed'
        || (($s['state'] ?? '') === 'building' && time() - (int)($s['time'] ?? 0) > 15 * 60);
}

// What players read when it did, on the home page and at /apk, is t('build.failed').

// What the admin page writes into the notice when the owner leaves the message empty.
const DEFAULT_NOTICE = 'The server is under maintenance. Please try again later.';

/* The maintenance message while the admin's in-game notice is on, or null when it is off. */
function maintenance_notice(): ?string
{
    static $notice = false;
    if ($notice === false) {
        // The admin page writes the notice into the overlay; the game shows this page at start.
        $raw = @file_get_contents(odq_custom_dir() . '/web/inspection/noti.html');
        // The message is the page's one paragraph, HTML-escaped.
        $notice = $raw === false ? null
            : (preg_match('#<p>(.*)</p>#s', $raw, $m) ? trim(html_entity_decode($m[1], ENT_QUOTES, 'UTF-8')) : '');
    }
    return $notice;
}

/* Number of songs the server offers (added ones included, hidden ones not). */
function song_count(): int
{
    return count(array_filter(song_list(), fn($s) => ($s['hidden_yn'] ?? 'N') !== 'Y'));
}

/* True when the game data is there: the manifest of the client's data folder, in the admin's overlay or the content. */
function game_data_present(): bool
{
    return odq_served_file('patch/phone_new/' . odq_patch_id() . '/android/patch_new.csv.lz4') !== null;
}

/* Patch version the server announces to the game at boot (the client's data folder, service.getInfo). */
function patch_version(): string
{
    return odq_patch_id();
}

/* Read-only handle on the game database, or null if it is missing, empty or not readable. */
function db(): ?SQLite3
{
    try {
        if (!is_file(DB) || filesize(DB) === 0) {
            return null;
        }
        $db = new SQLite3(DB, SQLITE3_OPEN_READONLY);
        $db->busyTimeout(2000);
        // Failures come back as false (PHP 8's default for SQLite3; asking for it is deprecated).
        // A file that is not a database, or lacks the game's tables, counts as unavailable.
        return @$db->querySingle('SELECT 1 FROM Member LIMIT 1') !== false ? $db : null;
    } catch (Exception $e) {
        return null;
    }
}

/* In place of a list of players or records while db() has no database (a damaged or unreadable
   file): saying nobody played yet would be wrong. */
function no_rankings(): string
{
    return '<p class="meta">' . t('unavailable') . '</p>';
}

/* One row per player (guid, nickname), to join with Play and PlayLog, whose user_id is the
   player's guid: the game saves with it. Member rows that share a guid (a transfer code links a
   second phone to the same player) count once, with the row whose id is the guid, else the oldest,
   as the in-game rankings pick it (opendmtq_profiles()). The server's check account and rows
   without a guid are left out. Bind :check to CHECK_UDID. */
const PLAYER_ROWS = "SELECT guid, nickname FROM (
        SELECT CAST(guid AS INTEGER) AS guid, nickname,
               ROW_NUMBER() OVER (PARTITION BY CAST(guid AS INTEGER)
                                  ORDER BY (id = CAST(guid AS INTEGER)) DESC, id ASC) AS pick
          FROM Member WHERE udid IS NOT :check AND guid IS NOT NULL)
     WHERE pick = 1";

/* A stored score (column p.score) as the rankings sum it. The game now caps what it saves, but
   rows saved before (or restored from an old backup) can be forged and huge, and SQLite's SUM()
   stops with "integer overflow" past 2^63, which emptied every ranking. Capped at the most the
   game can show, no sum of them comes near that. */
const SCORE_SQL = 'MIN(MAX(p.score, 0), 2147483647)';

/* Number of players, cheap enough for every health probe. */
function player_count(SQLite3 $db): int
{
    $q = $db->prepare('SELECT COUNT(*) FROM (' . PLAYER_ROWS . ')');
    if (!$q) {
        return 0;
    }
    $q->bindValue(':check', CHECK_UDID);
    $r = $q->execute();
    return $r ? (int)$r->fetchArray(SQLITE3_NUM)[0] : 0;
}

/* The figures of one player's rows in Play, as columns of a query on `Play p`. */
const PLAYER_FIGURES = "COUNT(p.pattern_id) AS charts,
                SUM(" . SCORE_SQL . ") AS total,
                SUM(p.grade = 'S') AS s_count,
                SUM(p.isAllCombo = 'Y') AS ac,
                SUM(p.isPerfectPlay = 'Y') AS perfect,
                AVG(MIN(MAX(p.judgement, 0), 1000)) AS avg_judgement";

/* Each player's total, from the index alone (Play_board): what a list of names and totals or a rank
   needs, a third of the cost of the other figures. Only players who have an account count. */
const PLAYER_TOTALS = "SELECT p.user_id, SUM(" . SCORE_SQL . ") AS total FROM Play p
          WHERE p.user_id IN (SELECT guid FROM (" . PLAYER_ROWS . ")) GROUP BY p.user_id";

/* Every player with ranking figures, best total first. Best score per chart is what counts. The
   id is the player's guid (for most players also their Member id), as player.php takes it. Scores are
   added up first and matched to names here: the same join in SQL took twice as long. */
function players(SQLite3 $db): array
{
    $figures = [];
    foreach (rows($db, "SELECT p.user_id, " . PLAYER_FIGURES . " FROM Play p GROUP BY p.user_id") as $row) {
        $figures[(int)$row['user_id']] = $row;
    }
    // What a player who has not played shows.
    $none = ['charts' => 0, 'total' => 0, 's_count' => 0, 'ac' => 0, 'perfect' => 0, 'avg_judgement' => 0];
    $rows = [];
    foreach (rows($db, PLAYER_ROWS, [':check' => CHECK_UDID]) as $row) {
        $id = (int)$row['guid'];
        $mine = array_merge($none, array_intersect_key($figures[$id] ?? [], $none));
        $rows[] = ['id' => $id, 'nickname' => $row['nickname']] + $mine;
    }
    // Highest total first, the older account on a tie, as the in-game rankings.
    usort($rows, fn($a, $b) => [$b['total'], $a['id']] <=> [$a['total'], $b['id']]);
    // One rank for every page: position by total score, then by id, among players who played.
    $rank = 0;
    foreach ($rows as &$row) {
        $row['name'] = player_name($row);
        $row['rank'] = $row['charts'] > 0 ? ++$rank : null;
    }
    return $rows;
}

/* Where a month's rankings begin, $back months ago (-1: the next): the first of the month at midnight UTC, the moment
   the game's own ranking screens count down to ("until the ranking resets"). */
function month_start(int $back = 0): int
{
    // gmmktime() takes a month before January or after December into the year before or after.
    return gmmktime(0, 0, 0, (int)gmdate('n') - $back, 1, (int)gmdate('Y'));
}

/* A moment of the server's clock in the page's words: "1 Dec at 09:00", "12월 1일 9:00". */
function month_moment(int $at): string
{
    // The month and the day are held together by a no-break space, so that a line never ends between them ("1" / "Dec").
    return lang() === 'ko' ? date('n', $at) . "월\u{00A0}" . date('j', $at) . '일 ' . date('G:i', $at) : date('j', $at) . "\u{00A0}" . date('M', $at) . ' at ' . date('H:i', $at);
}

/* A month by its first moment, in the page's words: "October 2026", "2026년 10월". */
function month_name(int $at): string
{
    return lang() === 'ko' ? date('Y', $at) . '년 ' . date('n', $at) . '월' : date('F Y', $at);
}

/* The players of one month (from $since to before $until), best first, as the game ranks them: the sum of each one's
   best score per chart in that month, from the play log, each score capped as SCORE_SQL caps it; the older account
   first on a tie. id, name, score, charts. */
function month_players(SQLite3 $db, int $since, int $until): array
{
    $rows = rows($db,
        "SELECT m.guid AS id, m.nickname, b.score, b.charts FROM (
             SELECT guid, SUM(best) AS score, COUNT(*) AS charts FROM (
                 SELECT l.user_id AS guid, MAX(MIN(MAX(l.score, 0), 2147483647)) AS best FROM PlayLog l
                  WHERE l.played_at >= :since AND l.played_at < :until GROUP BY l.user_id, l.pattern_id)
              GROUP BY guid) b
           JOIN (" . PLAYER_ROWS . ") m ON m.guid = b.guid
          ORDER BY b.score DESC, m.guid ASC",
        [':since' => $since, ':until' => $until, ':check' => CHECK_UDID]);
    foreach ($rows as &$row) {
        $row['name'] = player_name($row);
    }
    return $rows;
}

/* The months before this one, newest first, each with its first three: [[month's name, players], ...]. Only months
   anybody played in, $count months back at most. */
function past_months(SQLite3 $db, int $count = 6): array
{
    $out = [];
    for ($back = 1; $back <= $count; $back++) {
        $top = array_slice(month_players($db, month_start($back), month_start($back - 1)), 0, 3);
        if ($top) {
            $out[] = [month_name(month_start($back)), $top];
        }
    }
    return $out;
}

/* The best players who have played, in the order of players(): id, name and total only. */
function top_players(SQLite3 $db, int $limit): array
{
    $rows = rows($db,
        "SELECT m.guid AS id, m.nickname, a.total FROM (" . PLAYER_TOTALS . ") a
           JOIN (" . PLAYER_ROWS . ") m ON m.guid = a.user_id
          ORDER BY a.total DESC, m.guid ASC LIMIT :limit",
        [':check' => CHECK_UDID, ':limit' => $limit]);
    foreach ($rows as &$row) {
        $row['name'] = player_name($row);
    }
    return $rows;
}

/* One player as players() has them, rank included, without working out everybody's figures; null for
   somebody who is no player. */
function player_figures(SQLite3 $db, int $guid): ?array
{
    $row = rows($db,
        "SELECT m.guid AS id, m.nickname, COALESCE(a.charts, 0) AS charts, COALESCE(a.total, 0) AS total,
                COALESCE(a.s_count, 0) AS s_count, COALESCE(a.ac, 0) AS ac, COALESCE(a.perfect, 0) AS perfect,
                COALESCE(a.avg_judgement, 0) AS avg_judgement
           FROM (" . PLAYER_ROWS . ") m
           LEFT JOIN (SELECT p.user_id, " . PLAYER_FIGURES . " FROM Play p WHERE p.user_id = :guid GROUP BY p.user_id) a
             ON a.user_id = m.guid
          WHERE m.guid = :guid",
        [':check' => CHECK_UDID, ':guid' => $guid])[0] ?? null;
    if (!$row) {
        return null;
    }
    $row['name'] = player_name($row);
    $row['rank'] = null;
    if ($row['charts'] > 0) {
        // Those ahead of them: a higher total, or the same total and a lower id.
        $ahead = rows($db, "SELECT COUNT(*) AS n FROM (" . PLAYER_TOTALS . ") WHERE total > :total OR (total = :total AND user_id < :guid)",
            [':check' => CHECK_UDID, ':total' => (int)$row['total'], ':guid' => $guid]);
        $row['rank'] = (int)($ahead[0]['n'] ?? 0) + 1;
    }
    return $row;
}

/* HTML-escape. */
function h($s): string
{
    return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8');
}

/* ---------------------------------------------------------------------- songs and charts */

/* The song list the server serves: the admin's merged copy when there is one. */
function song_list(): array
{
    static $list = null;
    if ($list === null) {
        $raw = (string)@file_get_contents(odq_song_list_path());
        // The shipped file starts with a byte-order mark.
        $list = json_decode(preg_replace('/^\xEF\xBB\xBF/', '', $raw), true) ?: [];
    }
    return $list;
}

/* Songs by id. */
function songs_by_id(): array
{
    static $map = null;
    if ($map === null) {
        $map = [];
        foreach (song_list() as $s) {
            $map[(int)$s['song_id']] = $s;
        }
    }
    return $map;
}

/* pattern_id => [song_id, line, difficulty, signature]. */
function charts(): array
{
    static $map = null;
    if ($map === null) {
        $map = [];
        foreach (song_list() as $s) {
            foreach ($s['song_patterns'] ?? [] as $p) {
                $map[(int)$p['pattern_id']] = [(int)$s['song_id'], (int)$p['line'], (int)$p['difficulty'], (int)$p['signature']];
            }
        }
    }
    return $map;
}

/* The game's name for a chart's difficulty (the song list's signature code), in every language. */
function difficulty_name(int $signature): string
{
    // As the game's chart screen and result screen call them. Few songs have an Easy chart.
    $names = [0 => 'Easy', 1 => 'Normal', 2 => 'Hard', 3 => 'Expert'];
    return $names[$signature] ?? "Type $signature";
}

/* "2LINE Hard 5" style label for a chart, in the words of the game's mode select. The song list's line codes 3, 4 and 5 are the game's 2, 3
   and 4 LINE modes (as the in-game rankings and the tree's score viewers read them). */
function chart_label(int $line, int $difficulty, int $signature): string
{
    return ($line - 1) . "LINE " . difficulty_name($signature) . " $difficulty";
}

/* Song display name. */
function song_title(array $s): string
{
    return trim($s['full_name'] ?? '') ?: $s['name'];
}

/* A past broadcast as a card (live_past()'s entry): the first song's jacket with how long it is, then who, what and
   when, leading to it on the live page. The home page and a player's page show them alike. */
function past_card(array $x): string
{
    $pic = $x['pic'] ? '<img src="' . h($x['pic']) . '" alt="" loading="lazy" decoding="async"' . JACKET_ONERROR . '>' : '';
    return '<li><a class="past" href="live.php?r=' . h($x['key']) . '"><span class="past-pic">' . $pic . '<span class="past-len">' . h($x['length']) . '</span></span>'
        . '<span class="past-text"><b class="who">' . h($x['name']) . '</b><span class="doing" title="' . h($x['find']) . '">' . h($x['doing']) . '</span>'
        . '<span class="past-when" title="' . h($x['when']) . '">' . h($x['ago']) . '</span></span></a></li>';
}

/* Jacket image URL for a song: the small web copy when there is one, else the game's PNG. */
function jacket(array $s): string
{
    if (is_file(odq_custom_dir() . '/thumbs/' . basename($s['name']) . '.jpg')) {
        return '/thumbs/' . rawurlencode($s['name']) . '.jpg';
    }
    return '/viewImg/eye/' . rawurlencode($s['name']) . '.png';
}

/* For a jacket's <img>: a song with no picture shows the box's dark background, not the browser's broken
   image mark (an empty one-pixel image takes its place). */
const JACKET_ONERROR = " onerror=\"this.onerror=null;this.src='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'\"";

/* Accuracy from the game's per-mille judgement value. */
function accuracy($judgement): string
{
    return number_format(((int)$judgement) / 10, 1) . '%';
}

/* Player display name (blank until set in game). Plain text: escape it where it is printed. */
function player_name(array $row): string
{
    // The fallback name is only a number, so filling it in unescaped (strtr below) is safe.
    return trim((string)($row['nickname'] ?? '')) !== '' ? $row['nickname']
        : strtr(STRINGS[lang()]['player'], ['{id}' => (int)$row['id']]);
}

/* Relative time like "3 h ago" or "3시간 전", with no-break spaces: it never splits across lines.
   Plain text without markup or entities, so it can be escaped like any other value. */
function ago(?int $t): string
{
    if (!$t) {
        return '';
    }
    $d = time() - $t;
    // The table's spaces become no-break spaces, the number goes in unescaped (it is only digits).
    $say = fn(string $key, int $n = 0): string => str_replace(' ', "\u{a0}", strtr(STRINGS[lang()][$key], ['{n}' => $n]));
    if ($d < 60) {
        return $say('ago.now');
    }
    foreach ([[86400 * 30, 'ago.mo'], [86400, 'ago.d'], [3600, 'ago.h'], [60, 'ago.min']] as [$unit, $key]) {
        if ($d >= $unit) {
            return $say($key, intdiv($d, $unit));
        }
    }
    return '';
}

/* True when the PlayLog table exists (created by the api at start). */
function has_playlog(SQLite3 $db): bool
{
    return (bool)@$db->querySingle("SELECT 1 FROM sqlite_master WHERE name = 'PlayLog'");
}

/* Run a prepared query; returns all rows as associative arrays. */
function rows(SQLite3 $db, string $sql, array $params = []): array
{
    $q = $db->prepare($sql);
    if (!$q) {
        return [];
    }
    foreach ($params as $k => $v) {
        $q->bindValue($k, $v, is_int($v) ? SQLITE3_INTEGER : SQLITE3_TEXT);
    }
    $r = $q->execute();
    $out = [];
    while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
        $out[] = $row;
    }
    return $out;
}

/* ---------------------------------------------------------------------- page frame */

/* The top bar: the wordmark, the sections, how the server is, the language, signing in. On phones held upright the
   sections go to a bar at the thumb (style.css). $active is home, ranking, songs, live or download ('' for a page of no section,
   like the 404 page); $refresh a meta refresh ("20", or "1;url=/apk"); $stage what stands above the page at full width
   (the front page's stage). */
function page_header(string $title, string $active = '', string $refresh = '', string $stage = ''): void
{
    // Someone who has not signed in sees the sign-in and nothing of what is inside: no sections, no count of who is on
    // air, no word on how the server is. require_sign_in() keeps them to the pages without content.
    $inside = dl_signed_in();
    $db = $inside ? db() : null;
    // The page's language is in the cookie, so caches must keep one copy per language.
    header('Vary: Cookie');
    header('Content-Language: ' . lang());
    // Who is on air: a small count on LIVE, on every page and every width.
    $on_air = $db ? count(live_on_air($db)) : 0;
    $live_label = 'LIVE' . ($on_air ? ' <span class="onair" title="' . h(t('live.count', ['n' => $on_air])) . '">' . $on_air . '</span>' : '');
    // The sections stay in the display face's English, as in the game's menus.
    // What the site is for comes first, watching and getting the app; then the rest.
    $sections = [
        'home' => ['HOME', '/opendmtq/'],
        'live' => [$live_label, '/opendmtq/live.php'],
        'download' => ['DOWNLOAD', '/opendmtq/download.php'],
        'ranking' => ['RANKINGS', '/opendmtq/ranking.php'],
        'songs' => ['SONGS', '/opendmtq/songs.php'],
    ];
    $links = '';
    foreach ($sections as $key => [$label, $href]) {
        $links .= '<a href="' . $href . '"' . ($key === $active ? ' class="on" aria-current="true"' : '') . '>' . $label . '</a>';
    }
    // Maintenance (the in-game notice is on) comes before anything else: players cannot get in.
    $notice = $inside ? maintenance_notice() : null;
    [$state, $status] = !$inside ? ['ok', ''] : ($notice !== null ? ['maint', t('state.maint')] : ($db ? ['ok', ''] : ['down', t('state.down')]));
    // What a page shows depends on being signed in: Back after signing out must not bring it up from a cache.
    header('Cache-Control: private, no-store');
    echo '<!doctype html><html lang="' . lang() . '"><head><meta charset="utf-8">';
    echo '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">';
    echo '<meta name="theme-color" content="#11151a">';
    if ($refresh !== '') {
        echo '<meta http-equiv="refresh" content="' . h($refresh) . '">';
    }
    echo '<title>' . h($title === 'OpenDMTQ' ? $title : "$title · OpenDMTQ") . '</title>';
    echo '<link rel="icon" href="/opendmtq/favicon.svg" type="image/svg+xml">';
    echo '<link rel="stylesheet" href="/opendmtq/style.css">';
    // A page just arriving: what it measures fills in once and the player's own row glows once (style.css,
    // "motion"). The class goes after 1.6 s, so that nothing the page redraws later moves again.
    echo '<script>document.documentElement.classList.add("arriving");setTimeout(()=>document.documentElement.classList.remove("arriving"),1600)</script></head>';
    echo '<body data-section="' . h($active) . '"' . ($inside ? '' : ' class="signed-out"') . '><div class="facets" aria-hidden="true"></div>';
    // Only what is wrong is said: one word with a light, in English like the menus (the page's language for screen readers),
    // and a plain sentence under the bar. A server that is fine has nothing to announce.
    $word = ['ok' => '', 'maint' => 'MAINTENANCE', 'down' => 'OFFLINE'][$state];
    echo '<header class="bar"><div class="wrap bar-in"><a class="logo" href="/opendmtq/"><span class="o">OPEN</span><span class="m">DMT<b>Q</b></span></a>';
    echo $inside ? '<nav class="nav" aria-label="' . h(t('nav.aria')) . '">' . $links . '</nav>' : '';
    echo '<div class="bar-end">' . ($word !== '' ? '<span class="state ' . $state . '" role="img" aria-label="' . h(strip_tags($status)) . '" title="' . h(strip_tags($status)) . '"><i></i>' . $word . '</span>' : '') . lang_switch() . '</div></div></header>';
    echo $inside ? '<nav class="tabbar" aria-label="' . h(t('nav.aria')) . '">' . $links . '</nav>' : '';
    if ($state !== 'ok') {
        $own = $notice !== null && $notice !== '' && $notice !== DEFAULT_NOTICE;
        $says = $state === 'down' ? t('state.down_long') : ($own ? t('home.maint_own', ['notice' => $notice]) : t('home.maint'));
        echo '<div class="site-alert ' . $state . '" role="status"><p class="wrap">' . $says . '</p></div>';
    }
    // The page's name as its top heading, for screen readers and outlines; what shows is the masthead or the stage.
    echo '<h1 class="page-title">' . h($title) . '</h1>' . $stage . '<main class="wrap">';
}

/* A section's name at the head of its page, in the game's way, with one plain sentence beside it. The word is what the
   menu calls the section; the page's real name is its h1, for screen readers. */
function masthead(string $word, string $line = ''): string
{
    return '<div class="masthead"><p class="word" aria-hidden="true">' . h($word) . '</p>' . ($line !== '' ? '<p>' . $line . '</p>' : '') . '</div>';
}

/* What stands in for a page's content when there is nothing to show: a song or a player that is not there, an address that
   leads nowhere. All look the same: the number big when it is one, what happened, the way back ($links as for way_out()). */
function lost(string $title, string $text, array $links, bool $code = true): string
{
    return '<section class="lost">' . ($code ? '<span class="lost-code" aria-hidden="true">404</span>' : '') . '<h2>' . $title . '</h2>'
        . ($text !== '' ? '<p>' . $text . '</p>' : '') . ($links ? way_out($links) : '') . '</section>';
}

/* The jackets behind the front page: $count songs, a different set now and then, of those players can see. */
function jacket_wall(int $count): string
{
    $songs = array_values(array_filter(song_list(), fn($s) => ($s['hidden_yn'] ?? 'N') !== 'Y'));
    shuffle($songs);
    $out = '';
    foreach (array_slice($songs, 0, $count) as $s) {
        $out .= '<img src="' . h(jacket($s)) . '" alt="" decoding="async" loading="lazy"' . JACKET_ONERROR . '>';
    }
    return $out;
}

/* The small jacket of a list's row. */
function row_jacket(?array $song, string $class = 'row-jacket'): string
{
    return $song ? '<img class="' . $class . '" src="' . h(jacket($song)) . '" alt="" decoding="async" loading="lazy"' . JACKET_ONERROR . '>' : '<span class="' . $class . '"></span>';
}

/* The language switch on the bar, on every page: both languages in their own words. It comes back to this address,
   through lang.php. Signing in stands next to it. */
function lang_switch(): string
{
    $back = rawurlencode(safe_next((string)($_SERVER['REQUEST_URI'] ?? '/opendmtq/')));
    $out = '<nav class="lang-switch" aria-label="' . h(t('lang.label')) . '">';
    // Two keys; each language's own name for those who cannot read the other one's key.
    foreach (['ko' => ['KOR', '한국어'], 'en' => ['ENG', 'English']] as $code => [$key, $word]) {
        $out .= '<a lang="' . $code . '" title="' . $word . '" aria-label="' . $word . '" href="/opendmtq/lang.php?to=' . $code . '&amp;next=' . $back . '"'
            . ($code === lang() ? ' class="on" aria-current="true"' : '') . '>' . $key . '</a>';
    }
    $out .= '</nav>';
    // Sign-in, on every page but the sign-in page itself, in the page's own words. Signed in: whose account it is (on a
    // screen with room for it), and the way out.
    if (basename((string)($_SERVER['SCRIPT_NAME'] ?? '')) !== 'login.php') {
        $who = site_user();
        // Whose account it is, as the game's lobby shows a player: a round badge with the first letter of the name, then
        // the name and, small under it, the place in the rankings and the account's ID (an owner may have several
        // accounts). An account linked to its game player shows that player and leads to their page; any other shows its
        // ID alone. Not a key: the way out beside it is the only key there. A phone has room for the badge alone.
        $me = $who !== null ? site_me() : null;
        $db = $me !== null ? db() : null;
        $fig = $db ? player_figures($db, $me) : null;
        $name = $fig ? (string)$fig['name'] : (string)$who;
        $first = mb_strtoupper(mb_substr($name, 0, 1));
        $badge = '<span class="who-badge" aria-hidden="true">' . h($first !== '' ? $first : '?') . '</span>';
        $sub = $fig ? '<span class="who-sub">' . ($fig['rank'] ? h(t('player.rank_short', ['n' => $fig['rank']])) . ' · ' : '') . h((string)$who) . '</span>' : '';
        $text = '<span class="who-text"><span class="who-name">' . h($name) . '</span>' . $sub . '</span>';
        // Its words again in its title, for the badge alone (below 1100 px) under the pointer.
        $title = h($name . ($fig ? ' · ' . ($fig['rank'] ? t('player.rank_short', ['n' => $fig['rank']]) . ' · ' : '') . $who : ''));
        $label = $fig ? '<a class="auth-who" href="/opendmtq/player.php?id=' . $me . '" aria-label="' . h($name) . '" title="' . $title . '">' . $badge . $text . '</a>'
                      : '<span class="auth-who" title="' . $title . '">' . $badge . $text . '</span>';
        $out .= $who !== null
            ? '<form class="auth-form" method="post" action="/opendmtq/login.php?logout=1">' . $label . '<button class="auth">' . t('nav.signout') . '</button></form>'
            : '<a class="auth sign-in" href="/opendmtq/login.php?next=' . $back . '">' . t('nav.signin') . '</a>';
    }
    return $out;
}

/*
 * The players on air as the pages show them: number, name and what they are doing. $db may be null.
 */
function live_cards(?SQLite3 $db): array
{
    $now = $db ? live_now($db) : [];
    if (!$now) {
        return [];
    }
    $charts = charts();
    $songs = songs_by_id();
    $out = [];
    foreach ($now as $r) {
        // The chart being played, when the game's requests say so and the song is known.
        $doing = t('live.choosing');
        $song = $chart = '';
        [$sid, $line, $diff, $sig] = $charts[(int)$r['pattern_id']] ?? [0, 0, 0, 0];
        if (live_in_song($r) && isset($songs[$sid])) {
            $song = song_title($songs[$sid]);
            $chart = chart_label($line, $diff, $sig);
            $doing = "$song · $chart";
        }
        // The recording this broadcast goes into is named after the moment it began. How long ago, not when: the
        // viewer's clock need not agree with this one.
        $began = (int)(live_stream((int)$r['guid'])['rec'] ?? 0);
        $out[] = ['id' => (int)$r['guid'], 'name' => player_name(['nickname' => $r['nickname'], 'id' => $r['guid']]), 'doing' => $doing,
                  'song' => $song, 'chart' => $chart, 'age' => $began ? max(1, time() - $began) : 0];
    }
    return $out;
}

/* The recordings players may watch, newest first: key, player, how long, when, and its songs with where each begins and
   the first one's jacket. Closed and not hidden only, read fresh each time, so one the owner hides or deletes goes from
   the next look on. */
function live_past(?SQLite3 $db): array
{
    $recs = array_filter(live_rec_all(), fn($r) => !$r['open'] && !$r['hidden']);
    if (!$db || !$recs) {
        return [];
    }
    usort($recs, fn($a, $b) => $b['id'] <=> $a['id']);
    $names = [];
    foreach (rows($db, 'SELECT guid, nickname FROM (' . PLAYER_ROWS . ')', [':check' => CHECK_UDID]) as $m) {
        $names[(int)$m['guid']] = $m['nickname'];
    }
    // A recording notes its songs by title: the way to their jackets.
    $jackets = [];
    foreach (song_list() as $song) {
        $jackets[song_title($song)] = jacket($song);
    }
    $out = [];
    // As many as anyone would page through; the page shows them a screenful at a time.
    foreach (array_slice($recs, 0, 300) as $r) {
        $sec = (int)round((int)$r['duration_ms'] / 1000);
        $length = $sec >= 3600 ? sprintf('%d:%02d:%02d', $sec / 3600, $sec / 60 % 60, $sec % 60) : sprintf('%d:%02d', $sec / 60, $sec % 60);
        $songs = [];
        foreach ($r['songs'] as $song) {
            // A song without its moment (an older recording) goes on the list without a place to jump to.
            $at = isset($song['at']) ? max(0, (int)$song['at'] - (int)$r['started']) : -1;
            // With its jacket, found by the song's name as the card's picture is: the list under the picture shows it.
            // And the chart's difficulty, from the game's word for it in the chart's name, for its colour there (-1: none).
            $label = (string)($song['chart'] ?? '');
            $sig = preg_match('/\b(Easy|Normal|Hard|Expert)\b/', $label, $word) ? array_search($word[1], ['Easy', 'Normal', 'Hard', 'Expert'], true) : -1;
            $songs[] = ['title' => (string)$song['title'], 'chart' => $label, 'at' => $at,
                        'jacket' => $jackets[(string)$song['title']] ?? '', 'sig' => $sig];
        }
        $titles = array_values(array_unique(array_column($songs, 'title')));
        $line = $titles ? implode(', ', array_slice($titles, 0, 3)) . (count($titles) > 3 ? ' +' . (count($titles) - 3) : '') : t('live.choosing');
        // What a search goes through: every song, not the three that fit on the card.
        $find = implode(' ', $titles);
        $out[] = ['key' => $r['guid'] . '-' . $r['id'], 'id' => (int)$r['guid'], 'name' => player_name(['nickname' => $names[(int)$r['guid']] ?? '', 'id' => $r['guid']]),
                  'doing' => $line, 'find' => $find, 'length' => $length, 'seconds' => $sec, 'started' => (int)$r['started'], 'when' => date('Y-m-d H:i', (int)$r['started']), 'ago' => ago((int)$r['started']),
                  'songs' => $songs, 'pic' => $titles ? ($jackets[$titles[0]] ?? '') : ''];
    }
    return $out;
}

/* A small LIVE link for next to a player's name, while that player is on air ('' otherwise). Asks
   nothing itself: the menu has already asked who is on air for this page. */
function live_mark(?SQLite3 $db, int $guid): string
{
    if (!$db || !isset(live_on_air($db)[$guid])) {
        return '';
    }
    return ' <a class="live-mark" href="/opendmtq/live.php?p=' . $guid . '" title="' . h(t('live.watch')) . '">LIVE</a>';
}

/* Footer: what this site is, in two short lines, then the server's patch and the ways on: the license, and the admin
   pages when they are on this port (as entrypoint.sh decides it). */
function page_footer(): void
{
    $admin = getenv('ADMIN_URL') && (getenv('ADMIN_ON_PUBLIC_PORT') ?: 'yes') === 'yes';
    echo '</main><footer class="foot"><div class="wrap foot-in"><div class="foot-note"><p>' . t('foot.line1') . '</p><p>' . t('foot.line2') . '</p></div>'
        // The same three as the admin pages' footer, in the same order: the server's patch, the license, the way to the other
        // side (here the admin pages, when they are on this port).
        . '<nav class="foot-keys" aria-label="' . h(t('foot.links')) . '"><span class="foot-tag">' . t('foot.patch', ['v' => patch_version()]) . '</span>'
        . '<a class="key" aria-label="' . h(t('foot.license')) . '" href="/opendmtq/licenses.php">LICENSE</a>'
        . ($admin ? '<a class="key" aria-label="' . h(t('foot.admin')) . '" href="/opendmtq/admin/">ADMIN</a>' : '')
        . '</nav></div></footer>'
        // The bar is glass once the page has moved, and has no surface of its own at the very top.
        . "<script>(()=>{const b=document.querySelector('.bar'),f=()=>b.classList.toggle('under',scrollY>2);addEventListener('scroll',f,{passive:true});f()})()</script>"
        . '</body></html>';
}

/* A row of buttons that leads away from a page with nothing to show (a 404, a missing song): a big
   enough target, unlike a bare text link. $links is [[href, label from STRINGS], ...]. */
function way_out(array $links): string
{
    $out = '<div class="btn-line">';
    foreach ($links as [$href, $label]) {
        $out .= '<a class="btn" href="' . h($href) . '">' . $label . '</a>';
    }
    return $out . '</div>';
}

/* The app whose own browser shows this page (links shared in its chats and feeds open there), or
   null. Such a browser may not hand the download to Android, and a sign-in there stays there. */
function in_app_browser(): ?string
{
    $ua = (string)($_SERVER['HTTP_USER_AGENT'] ?? '');
    $apps = ['KakaoTalk' => '/KAKAOTALK/i', 'NAVER' => '/NAVER\(inapp/i', 'Band' => '/\bBAND\b/i',
             'Instagram' => '/Instagram/i', 'LINE' => '/\bLine\//i', 'Facebook' => '/FBAN|FBAV|FB_IAB|FB4A/'];
    foreach ($apps as $app => $pattern) {
        if (preg_match($pattern, $ua)) {
            return $app;
        }
    }
    return null;
}

/* The main button inside an in-app browser: it reopens $path (a page of this site) in the phone's
   own browser. KakaoTalk and LINE have their own links for that; the others get Android's link to
   Chrome, and where an app ignores it, its menu has the same choice. */
function open_in_browser(string $app, string $path): string
{
    // The same way this page was reached: over HTTPS, where the server has it.
    $scheme = visit_is_https() ? 'https' : 'http';
    $url = $scheme . '://' . public_host() . $path;
    if ($app === 'KakaoTalk') {
        $href = 'kakaotalk://web/openExternal?url=' . rawurlencode($url);
    } elseif ($app === 'LINE') {
        $href = $url . (strpos($url, '?') === false ? '?' : '&') . 'openExternalBrowser=1';
    } else {
        $href = 'intent://' . public_host() . $path . '#Intent;scheme=' . $scheme . ';package=com.android.chrome;end';
    }
    // The app by the name the page's language knows it by (카카오톡 on Korean pages).
    $name = STRINGS[lang()]['app.' . $app] ?? $app;
    // An iPhone has no Android link to Chrome: the app's own menu is the way to Safari (KakaoTalk's and LINE's links work).
    if (on_ios() && $app !== 'KakaoTalk' && $app !== 'LINE') {
        return '<p class="meta">' . t('inapp.ios', ['app' => $name]) . '</p>';
    }
    return '<a class="button" href="' . h($href) . '">' . t('inapp.button') . '</a>'
        . '<p class="meta">' . t('inapp.text', ['app' => $name])
        . (strpos($href, 'intent:') === 0 ? ' ' . t('inapp.menu') : '')
        . '</p>';
}

/* True on an iPhone, iPad or iPod, which cannot run the game. iPads that present themselves as a
   Mac are caught by android_only() in the page. */
function on_ios(): bool
{
    return (bool)preg_match('/iPhone|iPad|iPod/', (string)($_SERVER['HTTP_USER_AGENT'] ?? ''));
}

/* The note that takes the place of the download and its install steps (every .get-app block) on an
   iPhone or iPad: the game is for Android only. The server shows it to what says it is iOS; the
   page itself to an iPad that says it is a Mac (its touch screen gives it away). */
function android_only(): string
{
    return '<p class="warn ios-note"' . (on_ios() ? '' : ' hidden') . '>' . t('ios') . '</p>'
        . '<script>if (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1) {'
        . ' for (const e of document.querySelectorAll(".get-app")) e.hidden = true;'
        . ' for (const e of document.querySelectorAll(".ios-note")) e.hidden = false; }</script>';
}

/* " hidden" for the blocks only Android visitors need (download, install steps, QR code) when the
   visitor says it is an iPhone or iPad. */
function hidden_on_ios(): string
{
    return on_ios() ? ' hidden' : '';
}

/* The game's AC and PP marks, with what they stand for as a tooltip. */
function mark(string $kind): string
{
    return '<span class="mark ' . $kind . '" title="' . h(strip_tags(t('mark.' . $kind))) . '">' . strtoupper($kind) . '</span>';
}

/* Grade with AC/PP marks, as small labels. */
function grade_cell(array $r): string
{
    $out = '<span class="grade g' . h($r['grade']) . '">' . h($r['grade']) . '</span>';
    if (($r['isPerfectPlay'] ?? 'N') === 'Y') {
        $out .= ' ' . mark('pp');
    } elseif (($r['isAllCombo'] ?? 'N') === 'Y') {
        $out .= ' ' . mark('ac');
    }
    return $out;
}

/* ---------------------------------------------------------------------- download sign-in */

// Cookie that asks the download page to start the download once (just signed in from a download link).
const DL_START_COOKIE = 'opendmtq_dl_start';

/* Have the download page start the download on its next visit. */
function dl_request_start(): void
{
    setcookie(DL_START_COOKIE, '1', ['expires' => time() + 300, 'path' => '/opendmtq/', 'httponly' => true, 'samesite' => 'Lax']);
}

/* True once after dl_request_start(): the cookie goes, so a reload (or a phone browser restoring
   the tab) does not download the app again. Call before any output. */
function dl_take_start(): bool
{
    if (empty($_COOKIE[DL_START_COOKIE])) {
        return false;
    }
    setcookie(DL_START_COOKIE, '', ['expires' => 1, 'path' => '/opendmtq/', 'httponly' => true, 'samesite' => 'Lax']);
    return true;
}

// Sign-in failures of the last ten minutes, for the throttle below, in the server's scratch folder.
define('DL_ATTEMPTS', odq_run_dir() . '/download-signin.json');

/* Sign-in attempts: at most 10 failures in ten minutes from one address (the edge proxy passes
   each visitor's own), and every failure waits a second (login.php). No limit for the whole server:
   the whole site is behind this sign-in, and such a limit would let anyone lock everyone out.

   An attempt takes its place in the count before the password is compared, under a lock, so
   attempts sent at the same moment cannot all pass the check before any is counted; a right
   password gives the place back (dl_attempt_succeeded()). Returns the attempt's id, or null when
   this address is throttled. */
function dl_attempt_begin(): ?string
{
    $ip = (string)($_SERVER['REMOTE_ADDR'] ?? '?');
    $id = bin2hex(random_bytes(8));
    $granted = false;
    $counted = dl_attempts(function (array $fails) use ($ip, $id, &$granted): array {
        $mine = count(array_filter($fails, fn($f) => ($f[1] ?? '') === $ip));
        if ($mine >= 10) {
            return $fails;
        }
        $granted = true;
        $fails[] = [time(), $ip, $id];
        return $fails;
    });
    // Nowhere to count (the run folder is not writable): let it through, as before the throttle.
    return ($granted || !$counted) ? $id : null;
}

/* The password was right: the attempt is not a failure. */
function dl_attempt_succeeded(string $id): void
{
    dl_attempts(fn(array $fails): array => array_filter($fails, fn($f) => ($f[2] ?? '') !== $id));
}

/* Runs $change on the failures of the last ten minutes ([[time, address, attempt id], ...]) and
   saves what it returns, all under an exclusive lock on the file. False when the file cannot be
   used. */
function dl_attempts(callable $change): bool
{
    $h = @fopen(DL_ATTEMPTS, 'c+');
    if (!$h) {
        return false;
    }
    if (!flock($h, LOCK_EX)) {
        fclose($h);
        return false;
    }
    $now = time();
    // Only entries of the last ten minutes (an older file held bare times, or [time, address]).
    $fails = array_filter((array)json_decode((string)stream_get_contents($h), true),
        fn($f) => is_array($f) && $now - (int)($f[0] ?? 0) < 600);
    $fails = array_values($change(array_values($fails)));
    // Rewritten in place while the lock is held, so no other attempt reads it half-written.
    ftruncate($h, 0);
    rewind($h);
    fwrite($h, json_encode($fails));
    fflush($h);
    flock($h, LOCK_UN);
    fclose($h);
    return true;
}
