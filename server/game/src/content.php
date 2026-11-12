<?php
/*
 * What the server knows of the game's content: the songs it offers and the few facts of the client's own
 * tables that some replies need (which charts cost MAX POINT, which items a player owns). OpenDMTQ ships none
 * of it. The operator's files bring it: the songs they import, the tables of their app. The tools turn those
 * into two files the server only reads:
 *
 *   custom/songList.json   the song list (tools/opendmtq_tools/songs.py, rebuild())
 *   custom/catalog.json    facts from the client's tables (the same rebuild())
 *
 * A server without songs has an empty list and an empty catalog, and every reply that uses them says so.
 */

require_once __DIR__ . '/config.php';

/*
 * The song list, decoded once per request: a list of the game's song objects (song_id, name, full_name, ...,
 * song_patterns). Each object keeps its keys in the file's order, which game.getSongList sends on unchanged.
 * An unreadable or missing list is an empty one.
 */
function odq_songs(): array
{
    // Static: one request may need it several times (a ranking, then the achievements).
    static $songs = null;
    if ($songs === null) {
        $raw = (string)@file_get_contents(odq_song_list_path());
        // A list written by a Windows editor may start with a byte-order mark, which json_decode() refuses.
        $songs = json_decode(preg_replace('/^\xEF\xBB\xBF/', '', $raw), true);
        if (!is_array($songs)) {
            $songs = [];
        }
    }
    return $songs;
}

/*
 * What most requests need of the song list without decoding its 200 KB each time: every chart's line and difficulty
 * ('kinds': pattern id => [line, signature]), the charts of each line ('lines': line => [pattern ids]) and of each song's
 * line ('songs': song id => line => [pattern ids]), each in the list's order, and the highest song id ('max'). Worked out
 * from the list once and kept as a PHP file in the run folder, named after the list file's identity (its inode, size
 * and time: the tools put a whole new file in its place, so a changed list is another file), which PHP's opcache keeps
 * compiled: a save or a ranking then reads it in microseconds where decoding the list took one to three milliseconds.
 * Without a run folder to write to, it is worked out from the list each time.
 */
function odq_song_index(): array
{
    // Static: a save asks several times (its chart, the achievements before it and after it).
    static $index = null;
    if ($index !== null) {
        return $index;
    }
    $stat = @stat(odq_song_list_path());
    $file = $stat ? odq_run_dir() . '/songs/index-' . $stat['ino'] . '-' . $stat['size'] . '-' . $stat['mtime'] . '.php' : null;
    if ($file !== null && is_file($file)) {
        // The file this very code wrote (below): an array of whole numbers, nothing else.
        $kept = @include $file;
        if (is_array($kept) && isset($kept['kinds'], $kept['lines'], $kept['songs'], $kept['max'])) {
            return $index = $kept;
        }
    }
    $index = ['kinds' => [], 'lines' => [], 'songs' => [], 'max' => 0];
    foreach (odq_songs() as $song) {
        $id = (int)($song['song_id'] ?? 0);
        $index['max'] = max($index['max'], $id);
        foreach ($song['song_patterns'] ?? [] as $pattern) {
            $chart = (int)($pattern['pattern_id'] ?? 0);
            $line = (int)($pattern['line'] ?? 0);
            // A chart the list leaves undescribed counts as no line and no difficulty.
            $index['kinds'][$chart] = [$line, (int)($pattern['signature'] ?? -1)];
            $index['lines'][$line][] = $chart;
            // By the id the song has in the list, -1 for one without: no request asks for that one.
            $index['songs'][(int)($song['song_id'] ?? -1)][$line][] = $chart;
        }
    }
    if ($file !== null) {
        // Written whole under another name, then put in place: a request that includes it never reads half of it.
        @mkdir(dirname($file), 0700, true);
        $part = $file . '.' . getmypid();
        if (@file_put_contents($part, '<?php return ' . var_export($index, true) . ';') !== false && @rename($part, $file)) {
            // The indexes of earlier lists go: one list, one index.
            foreach (glob(dirname($file) . '/index-*.php') ?: [] as $old) {
                if ($old !== $file) {
                    @unlink($old);
                }
            }
        } else {
            @unlink($part);
        }
    }
    return $index;
}

/* The highest song id in the list, 0 without songs. */
function odq_max_song_id(): int
{
    return odq_song_index()['max'];
}

/*
 * Facts from the client's tables that replies need, decoded once per request:
 *   point_charts    [{pattern_id, song_id, point_type, point_value}, ...]  charts unlocked with MAX POINT
 *   items           [item id, ...]  everything a player owns from the start (partners, skins, notes, levels)
 *   unlock_product  {...}  the level unlock product the shop's unlock screen shows
 * Missing (no tables yet): empty lists, no product.
 */
function odq_catalog(): array
{
    static $catalog = null;
    if ($catalog === null) {
        $data = json_decode((string)@file_get_contents(odq_custom_dir() . '/catalog.json'), true);
        $catalog = is_array($data) ? $data : [];
        // Every part present, whatever the file had.
        $catalog += ['point_charts' => [], 'items' => [], 'unlock_product' => null];
    }
    return $catalog;
}

/*
 * The song a phone downloads on its very first start, before the player picks any: the first song of the
 * list (the game's own first song, id 1, when the list has it). None on a server without songs.
 */
function odq_first_song(): ?array
{
    $first = null;
    foreach (odq_songs() as $song) {
        $id = (int)($song['song_id'] ?? 0);
        // Hidden songs are not offered, so not downloaded either.
        if ($id <= 0 || ($song['hidden_yn'] ?? 'N') === 'Y') {
            continue;
        }
        if ($first === null || $id < (int)$first['song_id']) {
            $first = $song;
        }
    }
    return $first;
}
