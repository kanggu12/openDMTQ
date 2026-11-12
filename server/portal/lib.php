<?php
/* Shared facts for the portal pages: server address, content, database, and the latest APK. */

// Who is live: the menu on every page says so.
require_once __DIR__ . '/live_lib.php';

// Where everything is: the game server's settings, which every part of the server shares.
require_once __DIR__ . '/../game/src/config.php';
// The game server's small rules, for where a month's rankings begin (odq_month_start()): the in-game rankings' own bounds.
require_once __DIR__ . '/../game/src/util.php';
// The database, and the folder the APK builder writes to.
if (!defined('DB')) {
    define('DB', odq_db_path());
}
define('APK_DIR', odq_apk_dir());
// The rankings: who counts as a player (CHECK_UDID, PLAYER_ROWS) and what a score counts for, the players' figures, and
// the months as the game's own board has them.
require_once __DIR__ . '/ranking_lib.php';
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

/* The table's text for $key in the page language (English when Korean lacks it, the key itself when neither has it), as
   it stands in the table. A count of one ({n} is 1) takes the words the table has for one ({key}.one) where it has them:
   English says "1 play", not "1 plays". */
function t_table(string $key, array $vars): string
{
    // The count as the page prints it: a number, or a placeholder a script fills in later (never one then).
    $one = isset($vars['n']) && (string)$vars['n'] === '1';
    // The words for one first, in the page's language, then in English, as for any other text.
    if ($one && isset(STRINGS[lang()][$key . '.one'])) {
        return STRINGS[lang()][$key . '.one'];
    }
    return STRINGS[lang()][$key] ?? STRINGS['en'][$key] ?? $key;
}

/* The text for $key in the page language as HTML, with {name} filled in from $vars, escaped: print it as it is, never
   through h() again. Placeholders without a value stay, for scripts that fill them later. */
function t(string $key, array $vars = []): string
{
    $fill = [];
    foreach ($vars as $name => $value) {
        // Escaped here, once: a name with & or < in it reads as itself.
        $fill['{' . $name . '}'] = h($value);
    }
    return strtr(t_table($key, $vars), $fill);
}

/* The same text as plain text, for what is not HTML: an attribute (escape it there, once, with h()) or a script's words
   (JSON). The table's own markup goes and its entities are read back; the values go in as they are. */
function tp(string $key, array $vars = []): string
{
    // The table's markup (<b>, <code>) is for HTML only; &nbsp; and the like become the characters they stand for.
    $text = html_entity_decode(strip_tags(t_table($key, $vars)), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    $fill = [];
    foreach ($vars as $name => $value) {
        // As they are: whoever prints this escapes it, once.
        $fill['{' . $name . '}'] = (string)$value;
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

/* The installer for Windows (the PC client) the site hands out, as tools/opendmtq_tools/windows_client.py describes it in
   windows.json beside the app; null when there is none (a server without it) or its file is not there whole. */
function windows_client(): ?array
{
    $raw = @file_get_contents(APK_DIR . '/windows.json');
    $w = $raw === false ? null : json_decode($raw, true);
    // The installer itself, at the size windows.json gives it: a file half copied or gone is no installer to hand out.
    $path = is_array($w) ? APK_DIR . '/' . basename((string)($w['file'] ?? '')) : '';
    if (!is_array($w) || !preg_match('/\.exe$/', $path) || !is_file($path) || filesize($path) !== (int)($w['size'] ?? -1)) {
        return null;
    }
    return $w;
}

/* The address players reach this site by, as the installer and the launcher keep it: the scheme of this visit (the edge
   proxy says HTTPS) and the server's public address, port included (site_url_for()). */
function site_url(): string
{
    return site_url_for(visit_is_https(), public_host());
}

/* An address of the site (windows_client.py's site_url() makes the same): the scheme and the public address. An address
   without a port is on port 80 (entrypoint.sh), and HTTPS answers on that same port: over HTTPS the port is named, or the
   address would mean 443, where nothing answers. */
function site_url_for(bool $https, string $host): string
{
    if ($https && !preg_match('/:\d+$/', $host)) {
        $host .= ':80';
    }
    return ($https ? 'https' : 'http') . '://' . $host;
}

/* The server's own certificate authority as PEM text (windows_client.py's own_ca() reads the same): what signs the
   certificate this site's HTTPS answers with, which the launcher trusts for this server alone. '' without one, or with a
   file that is no whole certificate. */
function server_ca(): string
{
    $f = @fopen(odq_https_dir() . '/ca.crt', 'rb');
    if (!$f) {
        return '';
    }
    // A certificate is two kilobytes or so: anything far larger is no certificate.
    $data = (string)fread($f, 16 * 1024 + 1);
    fclose($f);
    $text = trim($data);
    if (strlen($data) > 16 * 1024 || !str_starts_with($text, '-----BEGIN CERTIFICATE-----')
        || !str_ends_with($text, '-----END CERTIFICATE-----')) {
        return '';
    }
    return $text;
}

/* The end that goes on the installer as this site hands it out: this visit's address, the server's name and, over
   HTTPS, the server's own certificate authority (windows_preset_for()). */
function windows_preset(): string
{
    return windows_preset_for(site_url(), server_name(), visit_is_https() ? server_ca() : '');
}

/* The end for an address, a name and a certificate authority ('' leaves it out), as windows_client.py's preset() makes
   it, byte for byte (tests/game/protocol.sh compares the two): the details as JSON, their length in 4 bytes
   (little-endian), and the mark the installer looks for at its file's end. */
function windows_preset_for(string $url, string $name, string $ca = ''): string
{
    $details = ['version' => 1, 'url' => $url, 'name' => $name];
    if ($ca !== '') {
        $details['ca'] = $ca;
    }
    $json = json_encode($details, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    return $json . pack('V', strlen($json)) . 'OPENDMTQ-PRESET1';
}

/* The file name the installer is handed out under, with the server's address in it as the app's own name has it. */
function windows_download_name(): string
{
    return 'OpenDMTQ-Setup-' . preg_replace('/[^A-Za-z0-9.-]/', '-', public_host()) . '.exe';
}

/* A download's ETag, a strong one, as a broken download needs to go on (send_download()): the SHA-256 its manifest gives
   ($manifest: latest.json for the app, windows.json for the installer) when that is a whole hash of a file the size of the
   one opened ($stat, its fstat()); else the file's size and time, as Apache tags a file. With the end the installer gets
   ($tail), that end's hash too: the same installer from another address, or after a new name, is other bytes. */
function download_tag(array $manifest, array $stat, string $tail = ''): string
{
    $sha = strtolower((string)($manifest['sha256'] ?? ''));
    // The builder's hash stays the same through a copy or a restore, which the file's time does not; a manifest of
    // another size describes another file (swapped meanwhile), whose hash this one cannot borrow.
    $tag = preg_match('/^[0-9a-f]{64}$/', $sha) && (int)($manifest['size'] ?? -1) === (int)$stat['size']
        ? $sha : dechex((int)$stat['size']) . '-' . dechex((int)$stat['mtime']);
    // The end's own hash, short: it only has to tell this server's ends apart.
    return '"' . $tag . ($tail !== '' ? '-' . substr(hash('sha256', $tail), 0, 16) : '') . '"';
}

/* Hands out the open file $f with $tail after it as one download ($type, the file name $name), whole or the one part a
   broken download asks for to go on where it stopped: Accept-Ranges, the ETag $tag (download_tag()) and the file's time
   say what it is; Range asks for a part (206), If-Range for it only while the file is still that one (else the whole),
   If-Match, which Android's own downloads send instead, for nothing but that one (else 412); a part past the end is 416.
   One part per request: several (multipart answers, which no download manager needs) get the whole, as HTTP allows.
   A HEAD gets the headers alone. Ends the request. */
function send_download($f, string $type, string $name, string $tag, string $tail = ''): void
{
    $stat = fstat($f);
    // The file's bytes and the end after them: one length, one range of positions.
    $file_size = (int)$stat['size'];
    $size = $file_size + strlen($tail);
    $modified = gmdate('D, d M Y H:i:s', (int)$stat['mtime']) . ' GMT';
    // The type Android's installer (or Windows) expects, and a file name that says which server it is for.
    header('Content-Type: ' . $type);
    header('Content-Disposition: attachment; filename="' . $name . '"');
    // Behind the sign-in, and never kept: a download manager keeps its own part, checked by the tag below.
    header('Cache-Control: no-store');
    header('Accept-Ranges: bytes');
    header('ETag: ' . $tag);
    header('Last-Modified: ' . $modified);
    // If-Match: going on is only right for the file it began with; another one under this address now is 412, and the
    // download starts again from nothing. "*" is any file, which there is.
    $match = trim((string)($_SERVER['HTTP_IF_MATCH'] ?? ''));
    if ($match !== '' && $match !== '*' && !in_array($tag, array_map('trim', explode(',', $match)), true)) {
        http_response_code(412);
        exit;
    }
    // The positions to send, first and last: the whole by default.
    [$from, $to] = [0, $size - 1];
    $range = trim((string)($_SERVER['HTTP_RANGE'] ?? ''));
    // If-Range: the part only while the file is the one the part belongs to, by its tag (exactly: strong), or by its time
    // where no end follows the file (an end can change at the same time: a new name for the server).
    $if_range = trim((string)($_SERVER['HTTP_IF_RANGE'] ?? ''));
    $same = $if_range === '' || $if_range === $tag || ($tail === '' && $if_range === $modified);
    // Ranges are for GET alone (a HEAD answers for the whole), of one part: bytes=first-last, first- or -how many last.
    if ($range !== '' && $same && $_SERVER['REQUEST_METHOD'] === 'GET' && preg_match('/^bytes=(\d*)-(\d*)$/', $range, $m)
        && ($m[1] !== '' || $m[2] !== '')) {
        if ($m[1] === '') {
            // The last bytes: as many as asked, or the whole when that is more. None at all is no part.
            $last = (int)$m[2];
            $from = $last > 0 ? max(0, $size - $last) : $size;
        } else {
            // From a position on, to one or the end; a last before the first is no range at all (the whole goes).
            $from = (int)$m[1];
            $to = $m[2] === '' ? $size - 1 : min((int)$m[2], $size - 1);
            if ($m[2] !== '' && (int)$m[2] < $from) {
                [$from, $to] = [0, $size - 1];
                $range = '';
            }
        }
        // Nothing of the file in the part asked for: 416, with the length the next try can go by.
        if ($range !== '' && $from >= $size) {
            http_response_code(416);
            header('Content-Range: bytes */' . $size);
            exit;
        }
        // The part itself: 206, and where it lies in the whole.
        if ($range !== '') {
            http_response_code(206);
            header("Content-Range: bytes $from-$to/$size");
        }
    }
    header('Content-Length: ' . ($to - $from + 1));
    // A HEAD request (checks, download managers probing) needs the headers only.
    if ($_SERVER['REQUEST_METHOD'] === 'HEAD') {
        exit;
    }
    // The file's share of the part, straight from the open file (the same one whose length went out above).
    if ($from < $file_size) {
        stream_copy_to_stream($f, fopen('php://output', 'wb'), min($to, $file_size - 1) - $from + 1, $from);
    }
    // And the end's share, where the part reaches past the file.
    if ($to >= $file_size) {
        $start = max($from, $file_size) - $file_size;
        echo substr($tail, $start, $to - $file_size - $start + 1);
    }
    fclose($f);
    exit;
}

/* What the builder is doing about the app for this address, from what it last wrote (data/apk/out/build.json):
   'building' while a build for it runs, 'failed' when it gave up on it (or still says building long after any build
   ends), '' when no build for it is going on (no such file, a build for another address, or one that is done). Only
   'building' is worth waiting for: the pages say so and look again, and say plainly otherwise. */
function build_state(): string
{
    $s = json_decode((string)@file_get_contents(APK_DIR . '/build.json'), true);
    // Another address's build, or none written: nothing is being done for this one.
    if (!is_array($s) || ($s['host'] ?? null) !== public_host()) {
        return '';
    }
    $state = (string)($s['state'] ?? '');
    // A build that said it began fifteen minutes ago and never ended was cut off (STALE_BUILD in builder.py).
    if ($state === 'building') {
        return time() - (int)($s['time'] ?? 0) > 15 * 60 ? 'failed' : 'building';
    }
    return $state === 'failed' ? 'failed' : '';
}

/* True when the builder gave up on the app for this address: only the owner can help (t('build.failed')). */
function build_failed(): bool
{
    return build_state() === 'failed';
}

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

/* True when the client data is there: the manifest of the client's data folder, in the admin's overlay or the
   content. */
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

/* The address of one of the site's own files beside this one ($file: style.css, a script, the icon), with its version in
   it: the file's time, which an upgrade changes. A browser keeps such an address a year without asking again (site.conf),
   so that a page never meets the copy of an older version: a new version is a new address. */
function asset_url(string $file): string
{
    return '/opendmtq/' . $file . '?v=' . (int)@filemtime(__DIR__ . '/' . $file);
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

/* Accuracy from the game's per-mille judgement value (an average of them is no whole number), to the tenth of a percent
   with the half rounded up, as the API gives it (accuracy() in tools/opendmtq_tools/admin/site.py): 967.53 is 96.8%. */
function accuracy($judgement): string
{
    // In whole per-mille, a tenth of a percent each: the half goes up, the same in every language that reads the double.
    return number_format(floor((float)$judgement + 0.5) / 10, 1) . '%';
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
    $live_label = 'LIVE' . ($on_air ? ' <span class="onair" title="' . h(tp('live.count', ['n' => $on_air])) . '">' . $on_air . '</span>' : '');
    // The sections stay in the display face's English, as in the game's menus.
    // What the site is for comes first, watching and getting the app; then the rest. With broadcasts off for the server
    // there is nothing to watch, and no LIVE in the menu.
    $sections = ['home' => ['HOME', '/opendmtq/']] + (live_enabled() ? ['live' => [$live_label, '/opendmtq/live.php']] : []) + [
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
    // In plain words, for the light's label and title (escaped once, below).
    [$state, $status] = !$inside ? ['ok', ''] : ($notice !== null ? ['maint', tp('state.maint')] : ($db ? ['ok', ''] : ['down', tp('state.down')]));
    // What a page shows depends on being signed in: Back after signing out must not bring it up from a cache.
    header('Cache-Control: private, no-store');
    echo '<!doctype html><html lang="' . lang() . '"><head><meta charset="utf-8">';
    echo '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">';
    echo '<meta name="theme-color" content="#11151a">';
    if ($refresh !== '') {
        echo '<meta http-equiv="refresh" content="' . h($refresh) . '">';
    }
    echo '<title>' . h($title === 'OpenDMTQ' ? $title : "$title · OpenDMTQ") . '</title>';
    // The icon and the stylesheet by their versions (asset_url()): kept a year, and new with an upgrade's pages.
    echo '<link rel="icon" href="' . asset_url('favicon.svg') . '" type="image/svg+xml">';
    echo '<link rel="stylesheet" href="' . asset_url('style.css') . '">';
    // The faces the top of the page draws with, asked for with the stylesheet: they come in time to be used, and a face
    // that does not is left out for this page (font-display: optional, style.css) rather than moving it later.
    foreach (first_fonts($inside) as $font) {
        echo '<link rel="preload" href="/opendmtq/fonts/' . $font . '" as="font" type="font/woff2" crossorigin>';
    }
    // A page just arriving: what it measures fills in once and the player's own row glows once (style.css,
    // "motion"). The class goes after 1.6 s, so that nothing the page redraws later moves again.
    echo '<script>document.documentElement.classList.add("arriving");setTimeout(()=>document.documentElement.classList.remove("arriving"),1600)</script></head>';
    echo '<body data-section="' . h($active) . '"' . ($inside ? '' : ' class="signed-out"') . '><div class="facets" aria-hidden="true"></div>';
    // Only what is wrong is said: one word with a light, in English like the menus (the page's language for screen readers),
    // and a plain sentence under the bar. A server that is fine has nothing to announce.
    $word = ['ok' => '', 'maint' => 'MAINTENANCE', 'down' => 'OFFLINE'][$state];
    echo '<header class="bar"><div class="wrap bar-in"><a class="logo" href="/opendmtq/"><span class="o">OPEN</span><span class="m">DMT<b>Q</b></span></a>';
    echo $inside ? '<nav class="nav" aria-label="' . h(tp('nav.aria')) . '">' . $links . '</nav>' : '';
    echo '<div class="bar-end">' . ($word !== '' ? '<span class="state ' . $state . '" role="img" aria-label="' . h($status) . '" title="' . h($status) . '"><i></i>' . $word . '</span>' : '') . lang_switch() . '</div></div></header>';
    echo $inside ? '<nav class="tabbar" aria-label="' . h(tp('nav.aria')) . '">' . $links . '</nav>' : '';
    if ($state !== 'ok') {
        $own = $notice !== null && $notice !== '' && $notice !== DEFAULT_NOTICE;
        $says = $state === 'down' ? t('state.down_long') : ($own ? t('home.maint_own', ['notice' => $notice]) : t('home.maint'));
        echo '<div class="site-alert ' . $state . '" role="status"><p class="wrap">' . $says . '</p></div>';
    }
    // The page's name as its top heading, for screen readers and outlines; what shows is the masthead or the stage.
    echo '<h1 class="page-title">' . h($title) . '</h1>' . $stage . '<main class="wrap">';
}

/* The font files a page draws its first screen with (style.css's @font-face): the text face's Latin half, and its Hangul
   half on a page in Korean (an English page asks for it only for a Korean name in it); the wordmark's face and the
   language keys'. Signed in ($inside): the menu's face and the figures' too. Their names are their versions: kept a
   year. */
function first_fonts(bool $inside): array
{
    $fonts = ['dmtq-text-2-latin.woff2', 'dmtq-wide-italic-800.woff2', 'dmtq-wide-700.woff2'];
    if (lang() === 'ko') {
        $fonts[] = 'dmtq-text-2-hangul.woff2';
    }
    return $inside ? array_merge($fonts, ['dmtq-wide-800.woff2', 'dmtq-condensed-700.woff2', 'dmtq-condensed-800.woff2']) : $fonts;
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
    $out = '<nav class="lang-switch" aria-label="' . h(tp('lang.label')) . '">';
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
        $sub = $fig ? '<span class="who-sub">' . ($fig['rank'] ? h(tp('player.rank_short', ['n' => $fig['rank']])) . ' · ' : '') . h((string)$who) . '</span>' : '';
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

// The recordings a list goes through at most: as many as anyone would page through on the live page, which shows them a
// screenful at a time (PAST_SHOWN in tools/opendmtq_tools/admin/site.py).
const LIVE_PAST_SHOWN = 300;

/* The recordings players may watch, as their folders, newest first: [[folder, player, id], ...], closed and not hidden,
   found by their folders' names (which say when each began) and two small looks at each, with nothing read. The first
   LIVE_PAST_SHOWN of them are the list every page shows from; $count of them at most, and with $guid the player's own
   among those. */
function live_past_folders(int $count = LIVE_PAST_SHOWN, int $guid = 0): array
{
    $out = [];
    $listed = 0;
    foreach (live_rec_folders() as [$rec, $player, $id]) {
        // Running and hidden ones are never on the list: two small looks, nothing read.
        if (is_file("$rec/.open") || is_file("$rec/.hidden")) {
            continue;
        }
        // The list ends here, for every page alike.
        if (++$listed > LIVE_PAST_SHOWN) {
            break;
        }
        // A player's page: theirs alone, among the same list.
        if ($guid > 0 && $player !== $guid) {
            continue;
        }
        $out[] = [$rec, $player, $id];
        if (count($out) >= $count) {
            break;
        }
    }
    return $out;
}

/* What the live page's list of recordings (live_past(), all of it) is now, in sixteen letters: a hash of their keys, from
   the folders alone (live_past_folders()). The live page's look every few seconds carries it, and the page asks for the
   list itself, a file to read for each recording, only when it changed: one ended, was hidden, shown again or deleted.
   With broadcasts off or no database, that of an empty list, as live_past() gives none then. */
function live_past_rev(?SQLite3 $db): string
{
    $keys = [];
    if (live_enabled() && $db) {
        foreach (live_past_folders() as [, $player, $id]) {
            // The key as live_past() gives it.
            $keys[] = "$player-$id";
        }
    }
    return live_past_rev_of($keys);
}

/* The hash of a list of recordings by their keys in order (live_past_rev()): live.php hashes the list it sends the same way,
   so that the page can tell the list it has from the one there is now. */
function live_past_rev_of(array $keys): string
{
    return substr(hash('sha256', implode(',', $keys)), 0, 16);
}

/* The recordings players may watch, newest first: key, player, how long, when, and its songs with where each begins and
   the first one's jacket. Closed and not hidden only, read fresh each time, so one the owner hides or deletes goes from
   the next look on. $count of them at most; with $guid, the player's own among the list's LIVE_PAST_SHOWN (those the live
   page has, narrowed to them). Found by their folders' names (live_past_folders()), so that only those shown are read:
   four for the home page out of the thousands a server may keep. */
function live_past(?SQLite3 $db, int $count = LIVE_PAST_SHOWN, int $guid = 0): array
{
    // Broadcasts off for the server: no recording is shown to players either (the admin pages still have them).
    if (!live_enabled() || !$db) {
        return [];
    }
    $recs = [];
    // Each with the player and id its folder is named by, which its address (live-media.php) finds it by, as the API's
    // twin of this list takes them (recordings.rec_all()).
    foreach (live_past_folders($count, $guid) as [$rec, $player, $id]) {
        $recs[] = [$player, $id, live_rec_read($rec, $player, $id)];
    }
    if (!$recs) {
        return [];
    }
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
    // Already no more than the list holds (above).
    foreach ($recs as [$player, $id, $r]) {
        $sec = (int)round((int)$r['duration_ms'] / 1000);
        $length = clock_length($sec);
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
        $out[] = ['key' => "$player-$id", 'id' => $player, 'name' => player_name(['nickname' => $names[$player] ?? '', 'id' => $player]),
                  'doing' => $line, 'find' => $find, 'length' => $length, 'seconds' => $sec, 'started' => (int)$r['started'], 'when' => date('Y-m-d H:i', (int)$r['started']), 'ago' => ago((int)$r['started']),
                  'songs' => $songs, 'pic' => $titles ? ($jackets[$titles[0]] ?? '') : ''];
    }
    return $out;
}

/* How long, as a clock says it and a recording's card shows it: 0:12, 4:05, 1:02:03. */
function clock_length(int $sec): string
{
    // An hour or more takes the hours too; under it, minutes and seconds.
    return $sec >= 3600 ? sprintf('%d:%02d:%02d', intdiv($sec, 3600), intdiv($sec, 60) % 60, $sec % 60)
                        : sprintf('%d:%02d', intdiv($sec, 60), $sec % 60);
}

/* A small LIVE link for next to a player's name, while that player is on air ('' otherwise). Asks
   nothing itself: the menu has already asked who is on air for this page. */
function live_mark(?SQLite3 $db, int $guid): string
{
    if (!$db || !isset(live_on_air($db)[$guid])) {
        return '';
    }
    return ' <a class="live-mark" href="/opendmtq/live.php?p=' . $guid . '" title="' . h(tp('live.watch')) . '">LIVE</a>';
}

/* Footer: what this site is, in two short lines, then the server's patch and the ways on: the license, and the admin
   pages when they are on this port (as entrypoint.sh decides it). */
function page_footer(): void
{
    $admin = getenv('ADMIN_URL') && (getenv('ADMIN_ON_PUBLIC_PORT') ?: 'yes') === 'yes';
    echo '</main><footer class="foot"><div class="wrap foot-in"><div class="foot-note"><p>' . t('foot.line1') . '</p><p>' . t('foot.line2') . '</p></div>'
        // The same three as the admin pages' footer, in the same order: the server's patch, the license, the way to the other
        // side (here the admin pages, when they are on this port).
        . '<nav class="foot-keys" aria-label="' . h(tp('foot.links')) . '"><span class="foot-tag">' . t('foot.patch', ['v' => patch_version()]) . '</span>'
        . '<a class="key" aria-label="' . h(tp('foot.license')) . '" href="/opendmtq/licenses.php">LICENSE</a>'
        . ($admin ? '<a class="key" aria-label="' . h(tp('foot.admin')) . '" href="/opendmtq/admin/">ADMIN</a>' : '')
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
    // As big as the download it stands in for (.button.get).
    return '<a class="button get" href="' . h($href) . '">' . t('inapp.button') . '</a>'
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
    // What works on an iPhone: the rankings, and the broadcasts while the server has them on.
    return '<p class="warn ios-note"' . (on_ios() ? '' : ' hidden') . '>' . t(live_enabled() ? 'ios' : 'ios.nolive') . '</p>'
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
    return '<span class="mark ' . $kind . '" title="' . h(tp('mark.' . $kind)) . '">' . strtoupper($kind) . '</span>';
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
