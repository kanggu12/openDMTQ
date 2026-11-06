<?php
/*
 * The live view follows who is in a song: /live/state holds a notice back until the song is over, and the portal
 * shows the song being played. The game's own requests around a song tell it (docs/live.md).
 */

require_once __DIR__ . '/db.php';

/*
 * Whether a live player is in a song, for /live/state (a notice waits until the song is over) and the
 * portal (the song being played). The game makes no requests during a song, so its requests around
 * one tell (seen in a capture of client 1.3.4):
 * - game.getPreviewPlayInfo [guid, patternId] opens a play, game.getPatternUrl follows at once;
 * - game.savePlayResult [guid, patternId, ...] closes it, savePlayResultFailLog closes a failed one;
 * - a song the player quit sends no result: the next menu request says the play is over. The first
 *   ones come in the same batch as getPreviewPlayInfo, so only those some seconds later count.
 * The guid is the first parameter of all of these.
 *
 * Only players with a row that matters are written: a game request costs at most one extra read for
 * everybody else. Nothing here may ever get in the way of the game's reply.
 */
function odq_live_seen($method, $params)
{
    // Requests that open a play, close one, or only happen in the menus.
    static $kinds = [
        'game.getPreviewPlayInfo' => 'open', 'game.getPatternUrl' => 'open',
        'game.savePlayResult' => 'close', 'game.savePlayResultFailLog' => 'close',
        'game.getUserAsset' => 'menu', 'game.getOwnSongList' => 'menu', 'game.getOwnPatternScore' => 'menu',
        'game.getOwnQuestList' => 'menu', 'game.getLineScoreMyRankWithLevel' => 'menu', 'game.setSlotItem' => 'menu',
        'shop.getOwnItemList' => 'menu', 'shop.getUnlockedProductList' => 'menu', 'memo.getMemoList' => 'menu',
    ];
    // Seconds after a play opens during which a menu request still belongs to its start.
    $start_grace = 10;
    try {
        if (!is_string($method) || !isset($kinds[$method]) || !is_array($params)) {
            return;
        }
        $list = array_values($params);
        $guid = isset($list[0]) && is_numeric($list[0]) ? (int)$list[0] : 0;
        if ($guid <= 0) {
            return;
        }
        // The request's handle, with its wait for other writers. Before the table exists (a restored
        // old database) the statements fail and nobody is followed.
        $db = odq_db();
        $kind = $kinds[$method];
        if ($kind === 'open') {
            // For everyone, not only players switched on: the owner may switch one on during a song,
            // and the notice must wait for its end then too. Only for real players, so that made-up
            // numbers cannot fill the table.
            $pattern = isset($list[1]) && is_numeric($list[1]) ? (int)$list[1] : 0;
            $now = time();
            // The two requests that open a play come together: the second finds it written and costs
            // a read, not a commit. A play opened again later (a retry) does write.
            $row = @$db->querySingle("SELECT playing, pattern_id, play_at FROM LiveSwitch WHERE guid = $guid", true);
            if ($row && $row['playing'] && (int)$row['pattern_id'] === $pattern && $now - (int)$row['play_at'] <= $start_grace) {
                return;
            }
            @$db->exec("INSERT INTO LiveSwitch (guid, playing, pattern_id, play_at)
                        SELECT $guid, 1, $pattern, $now WHERE EXISTS (SELECT 1 FROM Member WHERE guid = $guid)
                        ON CONFLICT (guid) DO UPDATE SET playing = 1, pattern_id = $pattern, play_at = $now");
            return;
        }
        $row = @$db->querySingle("SELECT playing, play_at FROM LiveSwitch WHERE guid = $guid", true);
        if ($row && $row['playing'] && ($kind === 'close' || time() - (int)$row['play_at'] > $start_grace)) {
            @$db->exec("UPDATE LiveSwitch SET playing = 0 WHERE guid = $guid");
        }
    } catch (Throwable $e) {
    }
}

