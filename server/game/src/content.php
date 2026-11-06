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

/* The highest song id in the list, 0 without songs. */
function odq_max_song_id(): int
{
    $max = 0;
    foreach (odq_songs() as $song) {
        $max = max($max, (int)($song['song_id'] ?? 0));
    }
    return $max;
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
