<?php
/*
 * Live view: the player's switch, the phone's segments and the HLS playlist. Used by the phone's
 * endpoints (web/dmqglb.mb.pmang.com/live/*.php) and by the portal's live pages, in one place
 * because they must agree on what "live now" means. See docs/live.md.
 *
 * On disk, for each player: /data/live/<guid>/
 *   <n>.ts       one MPEG-TS segment; n counts up for good (the phone's seq restarts with the app)
 *   index.m3u8   the playlist viewers load; names the segments relatively
 *   stream.json  what the next upload needs to carry the playlist on
 *   .lock        taken while any of these change
 *
 * Each broadcast is also kept as a recording, /data/live-rec/<guid>/<id>/ (id: its start, epoch seconds):
 *   <n>.ts       hard links to the segments above, so a recording costs an upload no second write
 *   segs.log     one line per segment: n, milliseconds, 1 after a break, bytes
 *   songs.log    one line per song: pattern id, when it started
 *   meta.json    player, times, length, size, songs; complete once the recording is closed
 *   index.m3u8   the VOD playlist, written at closing
 *   .open        there until the recording is closed; .close-now asks the next sweep to close it
 *   .hidden      the owner hid it from players
 * The admin pages (tools/opendmtq_tools/admin) read these files, and delete and hide recordings.
 */

// Where everything is: the game server's settings, which every part of the server shares.
require_once __DIR__ . '/../game/src/config.php';
// The stream folders (data/state/live on the host) and the game database.
define('LIVE_DIR', odq_state_dir() . '/live');
define('LIVE_DB', odq_db_path());
// The server's own check account never goes live, as it is never ranked.
const LIVE_CHECK_UDID = 'opendmtq-check';
// One segment at most: what the Apache limit in site.conf allows as well.
const LIVE_MAX_BODY = 4194304;
// One segment at least: ten MPEG-TS packets. A real segment is far above this (every video frame takes
// a packet of its own, so a second of video alone is thirty); tiny ones could only flood the lists.
const LIVE_MIN_BODY = 1880;
// Segments in the playlist.
const LIVE_WINDOW = 6;
// Segments kept on disk past the window: a viewer who loaded the playlist just before an upload may
// still be fetching the oldest one it named.
const LIVE_KEEP_PAST_WINDOW = 2;
// Seconds since the last upload: listed as live under the first; after the second the stream counts
// as stopped (the phone died, or lost its connection) and the next upload starts a new one.
const LIVE_LISTED = 15;
const LIVE_STOPPED = 30;
// Seconds after which a stream's leftovers are removed.
const LIVE_RETAIN = 300;
// Seconds between sweeps for those leftovers.
const LIVE_SWEEP_EVERY = 60;
// A play older than this counts as over whatever the game said: no song lasts this long, and a phone
// that died in a song sends nothing more.
const LIVE_SONG_MAX = 1200;
// The recordings, and limits.json with the owner's limits (the admin pages write it).
define('LIVE_REC_DIR', odq_state_dir() . '/live-rec');
// Seconds of silence after which a recording is closed: the next upload starts a new one.
const LIVE_REC_GAP = 300;
// The limits until the owner sets others: total size in GB, age in days.
const LIVE_REC_CAP_GB = 20;
const LIVE_REC_DAYS = 30;
// Bytes always left free on the disk, whatever the size limit says: the game's database lives there.
const LIVE_REC_RESERVE = 1073741824;
// Segments in one recording, an hour at two seconds each; the next upload goes on in a new one, so a long broadcast
// is kept as hour-long recordings, each easy to find a song in and to delete on its own. Keeps the
// lists the cleanup reads to a size it can always handle.
const LIVE_REC_MAX_SEGS = 1800;
// Seconds a player who ended a broadcast must wait from that broadcast's start before uploads are
// recorded again. A real broadcast is longer than this; only looping end and upload runs into it.
const LIVE_REC_MIN_START = 30;
// Recordings kept at most: the oldest go past this, however small they are.
const LIVE_REC_MAX_COUNT = 2000;

/* The game database, or null while it cannot be opened. Read-only unless $write. */
function live_db(bool $write = false): ?SQLite3
{
    try {
        $db = new SQLite3(LIVE_DB, $write ? SQLITE3_OPEN_READWRITE : SQLITE3_OPEN_READONLY);
        // Waits out a game save; the phone's requests are not urgent enough to fail over one.
        $db->busyTimeout(2000);
        // Failures come back as false (PHP 8's default for SQLite3): a database from before the table existed reads as "off".
        return $db;
    } catch (Exception $e) {
        return null;
    }
}

/* The device ids in a request's ids=a,b,c: only plausible ones, and not too many of them. */
function live_ids(string $raw): array
{
    $ids = [];
    foreach (array_slice(explode(',', $raw), 0, 16) as $id) {
        // Bound as SQL values, so the check is not what keeps them safe; it only drops junk early.
        if (preg_match('/^[A-Za-z0-9._:-]{1,128}$/', $id)) {
            $ids[] = $id;
        }
    }
    return array_values(array_unique($ids));
}

/*
 * The player these device ids belong to: ['guid', 'live', 'token', 'toast', 'playing', 'play_at'],
 * or null when no account has any of them. A phone can match several rows: a second phone's row
 * shares its player's guid, and old ids may have made old accounts. A player the owner shows live
 * (or who still has a line to read) comes first, so a forgotten old account never hides that; then
 * the row PLAYER_ROWS prefers (its id is the guid, else the oldest).
 */
function live_player(SQLite3 $db, array $ids): ?array
{
    if (!$ids) {
        return null;
    }
    // One placeholder per id.
    $marks = [];
    foreach ($ids as $i => $_) {
        $marks[] = ":id$i";
    }
    $q = @$db->prepare("SELECT CAST(m.guid AS INTEGER) AS guid, COALESCE(l.live, 0) AS live, l.token,
                               COALESCE(l.toast, '') AS toast, COALESCE(l.playing, 0) AS playing, l.play_at,
                               l.pattern_id
                          FROM Member m LEFT JOIN LiveSwitch l ON l.guid = CAST(m.guid AS INTEGER)
                         WHERE m.udid IN (" . implode(',', $marks) . ") AND m.udid IS NOT :check AND m.guid IS NOT NULL
                         ORDER BY COALESCE(l.live, 0) DESC, COALESCE(l.toast, '') <> '' DESC,
                                  m.id = CAST(m.guid AS INTEGER) DESC, m.id ASC
                         LIMIT 1");
    // No such table yet: nobody can be live.
    if (!$q) {
        return null;
    }
    foreach ($ids as $i => $id) {
        $q->bindValue(":id$i", $id, SQLITE3_TEXT);
    }
    $q->bindValue(':check', LIVE_CHECK_UDID, SQLITE3_TEXT);
    $r = @$q->execute();
    $row = $r ? $r->fetchArray(SQLITE3_ASSOC) : false;
    // A guid that is no number casts to 0: not a player.
    return ($row && (int)$row['guid'] > 0) ? $row : null;
}

/* True while the player is in a song, by the game's own requests (odq_live_seen() in server/game/src/live.php keeps
   the two columns). */
function live_in_song(array $row): bool
{
    return !empty($row['playing']) && time() - (int)$row['play_at'] < LIVE_SONG_MAX;
}

/*
 * The player an upload or end request is allowed for: the ids must name a player who is live, and
 * the token must be that player's. Answers 403 and stops the script otherwise, which tells the phone
 * to stop. Returns the player's row (live_player).
 */
function live_authorize(): array
{
    $db = live_db();
    $row = $db ? live_player($db, live_ids((string)($_GET['ids'] ?? ''))) : null;
    $sent = (string)($_SERVER['HTTP_X_LIVE_TOKEN'] ?? '');
    if (!$row || !$row['live'] || (string)$row['token'] === '' || !hash_equals((string)$row['token'], $sent)) {
        http_response_code(403);
        exit;
    }
    return $row;
}

/* ---------------------------------------------------------------------- the stream on disk */

/* A player's stream folder; $guid is always an int, so it cannot name another place. */
function live_folder(int $guid): string
{
    return LIVE_DIR . "/$guid";
}

/* A stream's stream.json as an array, or null when there is none. */
function live_stream(int $guid): ?array
{
    $s = json_decode((string)@file_get_contents(live_folder($guid) . '/stream.json'), true);
    return is_array($s) ? $s : null;
}

/* Runs $change while holding the player's lock and returns what it returns; false without a usable
   folder. Uploads and the end of a stream can arrive at once. */
function live_locked(int $guid, callable $change)
{
    $dir = live_folder($guid);
    // The folder goes when the owner switches live off: made again by the next allowed upload.
    if (!is_dir($dir) && !@mkdir($dir, 0750, true) && !is_dir($dir)) {
        return false;
    }
    $h = @fopen("$dir/.lock", 'c');
    if (!$h || !flock($h, LOCK_EX)) {
        return false;
    }
    $out = $change($dir);
    flock($h, LOCK_UN);
    fclose($h);
    return $out;
}

/* Writes a file so that a reader sees the old one or the whole new one, never part of one. */
function live_write(string $path, string $data): bool
{
    $tmp = $path . '.' . getmypid() . '.tmp';
    if (@file_put_contents($tmp, $data) !== strlen($data) || !@rename($tmp, $path)) {
        @unlink($tmp);
        return false;
    }
    return true;
}

/* Saves stream.json and the playlist made from it. */
function live_save(string $dir, array $s): bool
{
    // Version 3 for decimal durations. The target only ever grows within a stream, as HLS requires.
    $m3u = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:{$s['target']}\n";
    $first = $s['segs'][0]['n'] ?? $s['next'];
    $m3u .= "#EXT-X-MEDIA-SEQUENCE:$first\n#EXT-X-DISCONTINUITY-SEQUENCE:{$s['disc_seq']}\n";
    foreach ($s['segs'] as $seg) {
        if ($seg['disc']) {
            $m3u .= "#EXT-X-DISCONTINUITY\n";
        }
        $m3u .= sprintf("#EXTINF:%.3f,\n%d.ts\n", $seg['dur'] / 1000, $seg['n']);
    }
    if ($s['ended']) {
        $m3u .= "#EXT-X-ENDLIST\n";
    }
    return live_write("$dir/stream.json", json_encode($s)) && live_write("$dir/index.m3u8", $m3u);
}

/*
 * Adds one segment. $seq is the phone's number, restarting at 0 with the app; $dur_ms its length;
 * $song the [pattern id, start] being played, if any. False when it could not be stored.
 */
function live_add_segment(int $guid, int $seq, int $dur_ms, string $body, ?array $song = null): bool
{
    // Whether this upload closed a recording: the limits are then looked at, after the lock is let go
    // (they may need another player's lock, and two uploads waiting for each other would never end).
    $closed = false;
    $stored = live_locked($guid, function (string $dir) use ($guid, $seq, $dur_ms, $body, $song, &$closed): bool {
        $now = time();
        $blank = ['next' => 1, 'last_seq' => null, 'target' => 1, 'disc_seq' => 0, 'ended' => false, 'updated' => 0, 'segs' => []];
        $s = json_decode((string)@file_get_contents("$dir/stream.json"), true);
        $s = is_array($s) ? $s : $blank;
        // The same number again: a retry after a lost reply, already stored.
        if ($s['last_seq'] === $seq && !$s['ended'] && $now - $s['updated'] < LIVE_STOPPED) {
            return true;
        }
        // A long silence starts over: nobody should get minutes-old video first. The numbering goes
        // on, so a viewer's player cannot mistake a new segment for an old one.
        if ($s['segs'] && $now - $s['updated'] >= LIVE_STOPPED) {
            foreach ($s['segs'] as $seg) {
                $s['disc_seq'] += $seg['disc'] ? 1 : 0;
            }
            // The first new segment is a break from whatever a viewer still holds.
            $s['disc_seq']++;
            $s['segs'] = [];
            // Nor is any of the old video kept for it.
            foreach (glob("$dir/*.ts") ?: [] as $f) {
                @unlink($f);
            }
            $s['target'] = 1;
            $s['last_seq'] = null;
            $s['ended'] = false;
        }
        // A break in the video: the app restarted (back to 0), segments were skipped, or the stream had
        // ended and goes on. The player must not expect the timestamps to run on.
        $disc = $s['segs'] && ($s['ended'] || $seq !== $s['last_seq'] + 1);
        $n = (int)$s['next'];
        if (!live_write("$dir/$n.ts", $body)) {
            return false;
        }
        // Before 'updated' moves on: the recording looks at how long the silence was.
        $s = live_rec_note($guid, $s, $dir, $n, $seq, $dur_ms, strlen($body), $song, $now, $closed);
        $s['segs'][] = ['n' => $n, 'dur' => $dur_ms, 'disc' => (bool)$disc];
        $s['next'] = $n + 1;
        $s['last_seq'] = $seq;
        $s['ended'] = false;
        $s['updated'] = $now;
        // HLS: every duration, rounded, fits the target.
        $s['target'] = max((int)$s['target'], (int)round($dur_ms / 1000), 1);
        // Slide the window. A segment leaving it with a break counts, so players keep their place.
        while (count($s['segs']) > LIVE_WINDOW) {
            $old = array_shift($s['segs']);
            $s['disc_seq'] += $old['disc'] ? 1 : 0;
            @unlink("$dir/" . ($old['n'] - LIVE_KEEP_PAST_WINDOW) . '.ts');
        }
        return live_save($dir, $s);
    }) === true;
    if ($closed) {
        live_rec_enforce();
    }
    return $stored;
}

/* True when the disk is too full for one more segment: the upload is refused before anything is
   written, whatever the recordings' limits have got to so far. */
function live_disk_low(): bool
{
    foreach ([LIVE_DIR, LIVE_REC_DIR] as $dir) {
        $free = @disk_free_space($dir);
        if ($free !== false && $free < LIVE_REC_RESERVE + LIVE_MAX_BODY) {
            return true;
        }
    }
    return false;
}

/* The phone says the stream is over: players stop waiting for more. */
function live_end_stream(int $guid): void
{
    // Nothing was ever uploaded: there is no playlist to end (and no folder to make for it).
    if (!live_stream($guid)) {
        return;
    }
    $closed = false;
    live_locked($guid, function (string $dir) use ($guid, &$closed): void {
        $s = json_decode((string)@file_get_contents("$dir/stream.json"), true);
        if (is_array($s) && !$s['ended']) {
            // The broadcast is over, so is its recording; uploading again starts a new one, but not
            // straight after a very short one: looping end and upload must not make recordings.
            if (!empty($s['rec'])) {
                live_rec_close($guid, (int)$s['rec']);
                $closed = true;
                $s['rec_hold'] = (int)($s['rec_opened'] ?? 0) + LIVE_REC_MIN_START;
            }
            $s['rec'] = 0;
            $s['ended'] = true;
            live_save($dir, $s);
        }
    });
    if ($closed) {
        live_rec_enforce();
    }
}

/* ---------------------------------------------------------------------- the recordings */

/* A recording's folder; both numbers are always ints, so it cannot name another place. */
function live_rec_path(int $guid, int $id): string
{
    return LIVE_REC_DIR . "/$guid/$id";
}

/* Starts a recording for this player; its id, or 0 when none could be made (the broadcast goes on). */
function live_rec_open(int $guid, int $now): int
{
    // The id is the start; in the same second as another one, the next free number.
    for ($id = $now; $id < $now + 5; $id++) {
        $rec = live_rec_path($guid, $id);
        if (@mkdir($rec, 0750, true)) {
            touch("$rec/.open");
            live_write("$rec/meta.json", json_encode(['guid' => $guid, 'id' => $id, 'started' => $now]));
            return $id;
        }
    }
    return 0;
}

/*
 * Keeps a stored segment in the broadcast's recording, starting one when needed. Nothing here may
 * cost the upload much (one link, one or two short appends), or fail it: a broken recording must not
 * stop the broadcast. Returns the stream's state with the recording's noted.
 */
function live_rec_note(int $guid, array $s, string $dir, int $n, int $seq, int $dur_ms, int $size, ?array $song, int $now, bool &$closed): array
{
    $id = (int)($s['rec'] ?? 0);
    // Closed in the meantime by the sweep, or deleted by the owner.
    if ($id && !is_file(live_rec_path($guid, $id) . '/.open')) {
        $id = 0;
    }
    // Silent for so long that this counts as another broadcast, or as long as one recording may be.
    if ($id && ($now - (int)$s['updated'] >= LIVE_REC_GAP || (int)($s['rec_segs'] ?? 0) >= LIVE_REC_MAX_SEGS)) {
        live_rec_close($guid, $id);
        $closed = true;
        $id = 0;
    }
    $going_on = $id > 0;
    if (!$going_on) {
        // Ended a moment after starting: the broadcast goes on, unrecorded until the wait is over.
        if ($now < (int)($s['rec_hold'] ?? 0)) {
            $s['rec'] = 0;
            return $s;
        }
        $id = live_rec_open($guid, $now);
        // A new recording lists the song in progress again.
        $s['song_at'] = 0;
        $s['rec_seq'] = null;
        $s['rec_segs'] = 0;
        $s['rec_opened'] = $now;
        if (!$id) {
            $s['rec'] = 0;
            return $s;
        }
    }
    $rec = live_rec_path($guid, $id);
    // Same disk, so a link; a copy only where the disk cannot do that.
    if (!@link("$dir/$n.ts", "$rec/$n.ts") && !@copy("$dir/$n.ts", "$rec/$n.ts")) {
        $s['rec'] = $id;
        return $s;
    }
    // A break wherever the numbers do not follow on (the live window's own check resets with silence).
    $break = $going_on && $seq !== (int)($s['rec_seq'] ?? -2) + 1 ? 1 : 0;
    @file_put_contents("$rec/segs.log", "$n $dur_ms $break $size\n", FILE_APPEND);
    $s['rec'] = $id;
    $s['rec_seq'] = $seq;
    $s['rec_segs'] = (int)($s['rec_segs'] ?? 0) + 1;
    if ($song && (int)$song[1] !== (int)($s['song_at'] ?? 0)) {
        @file_put_contents("$rec/songs.log", (int)$song[0] . ' ' . (int)$song[1] . "\n", FILE_APPEND);
        $s['song_at'] = (int)$song[1];
    }
    return $s;
}

/* The bytes a recording's segs.log adds up to, read a line at a time: whatever its length, this needs no
   more memory than one line. */
function live_rec_size(string $path): int
{
    $size = 0;
    $f = @fopen($path, 'r');
    while ($f && ($line = fgets($f)) !== false) {
        $size += (int)substr($line, (int)strrpos($line, ' ') + 1);
    }
    if ($f) {
        fclose($f);
    }
    return $size;
}

/* A short file of lines of whole numbers, as lists of ints. */
function live_rec_lines(string $path): array
{
    $out = [];
    foreach (@file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) ?: [] as $line) {
        $out[] = array_map('intval', explode(' ', $line));
    }
    return $out;
}

/* The songs of a closed recording: title, chart and start of each. Only known songs; two requests a
   moment apart for one start count once. Empty when the game's lists cannot be read. */
function live_rec_songs(string $rec): array
{
    $lines = live_rec_lines("$rec/songs.log");
    if (!$lines) {
        return [];
    }
    try {
        // The endpoints do not load the portal's library, which knows the song lists.
        require_once __DIR__ . '/lib.php';
        $charts = charts();
        $songs = songs_by_id();
        $out = [];
        $last = [0, 0];
        foreach ($lines as [$pattern, $at]) {
            $same = $pattern === $last[0] && $at - $last[1] < 10;
            $last = [$pattern, $at];
            [$sid, $line, $diff, $sig] = $charts[$pattern] ?? [0, 0, 0, 0];
            if (!$same && isset($songs[$sid])) {
                $out[] = ['title' => song_title($songs[$sid]), 'chart' => chart_label($line, $diff, $sig), 'at' => $at];
            }
        }
        return $out;
    } catch (Throwable $e) {
        return [];
    }
}

/*
 * Closes a recording: the VOD playlist and the finished meta.json. One without any segment is removed.
 * Nothing happens to a recording already closed. Call it holding the player's lock (an upload may be
 * adding to it otherwise); the limits are the caller's to look at, after letting that lock go. The list
 * is read a line at a time, so its length costs memory only for the playlist's text.
 */
function live_rec_close(int $guid, int $id): void
{
    $rec = live_rec_path($guid, $id);
    if (!is_file("$rec/.open")) {
        return;
    }
    $target = 1;
    $dur = 0;
    $size = 0;
    $count = 0;
    $body = '';
    $f = @fopen("$rec/segs.log", 'r');
    while ($f && ($line = fgets($f)) !== false) {
        [$n, $ms, $break, $bytes] = array_map('intval', explode(' ', trim($line))) + [0, 0, 0, 0];
        // HLS: every duration, rounded, fits the target.
        $target = max($target, (int)round($ms / 1000));
        $dur += $ms;
        $size += $bytes;
        $count++;
        $body .= ($break ? "#EXT-X-DISCONTINUITY\n" : '') . sprintf("#EXTINF:%.3f,\n%d.ts\n", $ms / 1000, $n);
    }
    if ($f) {
        fclose($f);
    }
    if (!$count) {
        live_rec_remove($rec);
        return;
    }
    live_write("$rec/index.m3u8", "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-TARGETDURATION:$target\n"
        . "#EXT-X-MEDIA-SEQUENCE:0\n$body#EXT-X-ENDLIST\n");
    $meta = json_decode((string)@file_get_contents("$rec/meta.json"), true);
    live_write("$rec/meta.json", json_encode([
        'guid' => $guid, 'id' => $id, 'started' => (int)($meta['started'] ?? $id),
        // The last segment's arrival, whenever the closing itself happens.
        'ended' => (int)@filemtime("$rec/segs.log"), 'duration_ms' => $dur, 'size' => $size, 'segments' => $count,
        'songs' => live_rec_songs($rec),
    ], JSON_UNESCAPED_UNICODE));
    @unlink("$rec/.close-now");
    // Last: the recording counts as closed only with everything above in place.
    @unlink("$rec/.open");
}

/* Removes a recording's folder, and its player's folder with the last one. */
function live_rec_remove(string $rec): void
{
    foreach (@scandir($rec) ?: [] as $f) {
        if ($f !== '.' && $f !== '..') {
            @unlink("$rec/$f");
        }
    }
    @rmdir($rec);
    @rmdir(dirname($rec));
}

/*
 * Every recording: its meta.json with 'dir', 'open' and 'hidden' added. An open one's size comes from
 * its segment list, as its meta.json is not finished. Folder names are checked to be the numbers this
 * code makes.
 */
function live_rec_all(): array
{
    $out = [];
    foreach (glob(LIVE_REC_DIR . '/*/*', GLOB_ONLYDIR) ?: [] as $rec) {
        if (!preg_match('#/(\d+)/(\d+)$#', $rec, $m)) {
            continue;
        }
        $meta = json_decode((string)@file_get_contents("$rec/meta.json"), true);
        $meta = is_array($meta) ? $meta : [];
        $meta += ['guid' => (int)$m[1], 'id' => (int)$m[2], 'started' => (int)$m[2], 'songs' => [], 'duration_ms' => 0];
        $meta['dir'] = $rec;
        $meta['open'] = is_file("$rec/.open");
        $meta['hidden'] = is_file("$rec/.hidden");
        if ($meta['open']) {
            $meta['size'] = live_rec_size("$rec/segs.log");
        }
        $out[] = $meta;
    }
    return $out;
}

/*
 * Keeps the recordings within the owner's limits, the oldest going first: too old, then over the total
 * size or LIVE_REC_MAX_COUNT. A running recording is never cut. While the total is still over the limit
 * the largest running ones are closed instead (their next upload starts a new one) and go as the oldest
 * next time, so the disk cannot fill however long and however many phones stay on. The disk's free space
 * counts as a limit as well. One pass at a time; a pass that finds another running leaves it to that one
 * (or to the next sweep). Call it holding no player's lock: closing takes one.
 */
function live_rec_enforce(): void
{
    $pass = @fopen(LIVE_REC_DIR . '/.enforce', 'c');
    if (!$pass || !flock($pass, LOCK_EX | LOCK_NB)) {
        return;
    }
    $limits = json_decode((string)@file_get_contents(LIVE_REC_DIR . '/limits.json'), true);
    $cap = (float)($limits['cap_gb'] ?? LIVE_REC_CAP_GB) * 1073741824;
    $days = (float)($limits['days'] ?? LIVE_REC_DAYS);
    $total = 0;
    $closed = [];
    $open = [];
    foreach (live_rec_all() as $r) {
        if ($r['open']) {
            $open[] = $r;
            $total += (int)$r['size'];
        } elseif (time() - (int)($r['ended'] ?? $r['started']) > $days * 86400) {
            live_rec_remove($r['dir']);
        } else {
            $closed[] = $r;
            $total += (int)($r['size'] ?? 0);
        }
    }
    $free = @disk_free_space(LIVE_REC_DIR);
    if ($free !== false) {
        $cap = min($cap, $total + $free - LIVE_REC_RESERVE);
    }
    usort($closed, fn($a, $b) => [$a['ended'] ?? $a['started'], $a['id']] <=> [$b['ended'] ?? $b['started'], $b['id']]);
    $count = count($closed) + count($open);
    foreach ($closed as $r) {
        if ($total <= $cap && $count <= LIVE_REC_MAX_COUNT) {
            break;
        }
        live_rec_remove($r['dir']);
        $total -= (int)($r['size'] ?? 0);
        $count--;
    }
    // Closing frees nothing yet: it counts as gone here, so that only as many close as needed.
    usort($open, fn($a, $b) => (int)$b['size'] <=> (int)$a['size']);
    foreach ($open as $r) {
        if ($total <= $cap) {
            break;
        }
        $guid = (int)$r['guid'];
        $id = (int)$r['id'];
        live_locked($guid, function () use ($guid, $id): void {
            live_rec_close($guid, $id);
        });
        $total -= (int)$r['size'];
    }
    flock($pass, LOCK_UN);
    fclose($pass);
}

/*
 * Removes what stopped streams left behind, at most once a minute whoever asks (the container's health
 * check asks every 30 seconds): segments older than LIVE_RETAIN, and a whole folder once its stream has
 * been silent that long. Live segments never get that old: the window moves on long before. The hard
 * links keep them in the recordings. Then the recordings: closing the finished, and the limits.
 */
function live_sweep(): void
{
    $mark = LIVE_DIR . '/.swept';
    // The mark's age says whether it is time (none yet: it is).
    if (!is_dir(LIVE_DIR) || time() - (int)@filemtime($mark) < LIVE_SWEEP_EVERY || !@touch($mark)) {
        return;
    }
    foreach (glob(LIVE_DIR . '/*', GLOB_ONLYDIR) ?: [] as $dir) {
        // Only the folders this code makes.
        if (!preg_match('#/\d+$#', $dir)) {
            continue;
        }
        $left = 0;
        foreach (glob("$dir/*") ?: [] as $f) {
            $old = time() - (int)@filemtime($f) >= LIVE_RETAIN;
            if ($old) {
                @unlink($f);
            } else {
                $left++;
            }
        }
        // Nothing recent at all: the lock file and the folder go too.
        if ($left === 0) {
            @unlink("$dir/.lock");
            @rmdir($dir);
        }
    }
    // Recordings left open by a phone that vanished, or that the owner's switch ended.
    foreach (live_rec_all() as $r) {
        if (!$r['open']) {
            continue;
        }
        $dir = $r['dir'];
        $done = function () use ($dir): bool {
            clearstatcache();
            return is_file("$dir/.close-now")
                || time() - (int)(@filemtime("$dir/segs.log") ?: @filemtime("$dir/.open")) >= LIVE_REC_GAP;
        };
        if ($done()) {
            $guid = (int)$r['guid'];
            $id = (int)$r['id'];
            // Under the player's lock, looking again: an upload may have got in first.
            live_locked($guid, function () use ($guid, $id, $done): void {
                if ($done()) {
                    live_rec_close($guid, $id);
                }
            });
        }
    }
    live_rec_enforce();
}

/*
 * The players on air now, as [guid => true]: the owner's switch on, last upload under LIVE_LISTED
 * seconds ago, stream not ended. The menu asks on every page and the rankings once per name, so this
 * is the one query for all of them: asked once per request, then remembered.
 */
function live_on_air(SQLite3 $db): array
{
    static $on = null;
    if ($on !== null) {
        return $on;
    }
    $on = [];
    live_sweep();
    // No such table in a database from before the live view: nobody is on air.
    $r = @$db->query("SELECT guid FROM LiveSwitch WHERE live = 1");
    while ($r && ($row = $r->fetchArray(SQLITE3_NUM))) {
        $s = live_stream((int)$row[0]);
        if ($s && !$s['ended'] && time() - (int)$s['updated'] < LIVE_LISTED) {
            $on[(int)$row[0]] = true;
        }
    }
    return $on;
}

/*
 * The players on air with their names and what they play, for the home and live pages: each is
 * ['guid', 'nickname', 'playing', 'pattern_id', 'play_at']. Nickname as stored; callers show it through
 * player_name(). The name query (lib.php's PLAYER_ROWS) runs only while someone is on air.
 */
function live_now(SQLite3 $db): array
{
    $on = live_on_air($db);
    if (!$on) {
        return [];
    }
    $q = @$db->prepare("SELECT l.guid, l.playing, l.pattern_id, l.play_at, m.nickname
                          FROM LiveSwitch l JOIN (" . PLAYER_ROWS . ") m ON m.guid = l.guid
                         WHERE l.live = 1 ORDER BY l.guid");
    if (!$q) {
        return [];
    }
    $q->bindValue(':check', LIVE_CHECK_UDID, SQLITE3_TEXT);
    $r = @$q->execute();
    $out = [];
    while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
        if (isset($on[(int)$row['guid']])) {
            $out[] = $row;
        }
    }
    return $out;
}
