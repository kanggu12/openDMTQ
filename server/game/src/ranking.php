<?php
/*
 * The in-game rankings: this month's, from the log of every play (PlayLog). The game counts down to the moment
 * they start anew (odq_month_start()); the web pages and a player's own best keep every month.
 */

require_once __DIR__ . '/db.php';
require_once __DIR__ . '/content.php';
require_once __DIR__ . '/util.php';

/*
 * The pattern ids (charts) a ranking counts: those of one line ($line 3, 4 or 5), optionally of one
 * song only. An empty list means "none", never "all".
 */
function odq_patterns($line, $songId = NULL)
{
    $ids = [];
    foreach (odq_songs() as $song) {
        // Only the asked song, when one is asked.
        if ($songId !== NULL && (int)($song['song_id'] ?? -1) !== $songId) {
            continue;
        }
        foreach ($song['song_patterns'] ?? [] as $pattern) {
            // Every difficulty of the asked line counts.
            if ((int)($pattern['line'] ?? 0) === $line) {
                $ids[] = (int)$pattern['pattern_id'];
            }
        }
    }
    return $ids;
}

/*
 * Where this month's rankings begin: the first of the month at midnight UTC (09:00 in Korea). The game's
 * ranking screens say how long until the rankings start anew and count down to that moment, in UTC, so
 * the boards start anew then and the countdown is true.
 */
function odq_month_start()
{
    return gmmktime(0, 0, 0, (int)gmdate('n'), 1, (int)gmdate('Y'));
}

/*
 * Ranked players for a set of charts this month: [[guid, score], ...], best first. A player's score is
 * the sum of their best scores this month on those charts, from the log of every play (PlayLog); for the
 * total ranking ($patterns null) every chart counts. Ties go to the older account, as on the web. Players
 * who did not play these charts this month are not ranked. The web rankings and a player's own best (MAX
 * SCORE, NEW RECORD) keep every month: they come from the best scores (Play), not from here.
 *
 * PlayLog.user_id is the player's guid (the game saves with it); after a transfer code a second Member
 * row shares the guid, so players are matched by guid, not by Member.id. The log is read through its indexes
 * with the time of the play in them: by the player (PlayLog_user), or for a chart of its own (PlayLog_chart).
 */
function odq_board($patterns)
{
    // A line or song with no charts in the list has nobody ranked.
    if ($patterns !== NULL && !$patterns) {
        return [];
    }
    // The chart filter, from ints only (safe to write into the query).
    $filter = $patterns === NULL ? '' : ' AND l.pattern_id IN (' . implode(',', array_map('intval', $patterns)) . ')';
    // Each player's best on each chart this month, each stored score capped (odq_sql_score) so that old
    // forged rows cannot overflow the sum; then those added up per player.
    $sql = 'SELECT guid, SUM(best) AS score FROM ('
        . 'SELECT l.user_id AS guid, MAX(' . odq_sql_score('l.score') . ') AS best FROM PlayLog l'
        . ' WHERE l.played_at >= :since'
        // Only players who still have an account, without the server's own check account.
        . ' AND l.user_id IN (SELECT CAST(guid AS INTEGER) FROM Member WHERE udid IS NOT :check)'
        . $filter
        . ' GROUP BY l.user_id, l.pattern_id)'
        . ' GROUP BY guid ORDER BY score DESC, guid ASC';
    $q = odq_db()->prepare($sql);
    // A database problem (or one older than the play log) ranks nobody rather than breaking the reply.
    if (!$q) {
        return [];
    }
    $q->bindValue(':since', odq_month_start(), SQLITE3_INTEGER);
    $q->bindValue(':check', OPENDMTQ_CHECK_UDID, SQLITE3_TEXT);
    $r = $q->execute();
    $board = [];
    while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
        $board[] = [(int)$row['guid'], (int)$row['score']];
    }
    return $board;
}

/*
 * Name and partner/add-on icons of the given players: guid => [name, slot_item1, slot_item2].
 * With two Member rows on one guid (a transfer), the row whose id is the guid wins.
 */
function odq_profiles(array $guids)
{
    $guids = array_values(array_unique(array_map('intval', $guids)));
    if (!$guids) {
        return [];
    }
    // Ints only, so they can be written into the query.
    $sql = 'SELECT CAST(guid AS INTEGER) AS guid, id, nickname, slot_item1, slot_item2 FROM Member'
        . ' WHERE CAST(guid AS INTEGER) IN (' . implode(',', $guids) . ')'
        . ' ORDER BY (id = CAST(guid AS INTEGER)) DESC, id ASC';
    $r = @odq_db()->query($sql);
    $out = [];
    while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
        $guid = (int)$row['guid'];
        // The first row per guid is the preferred one (see ORDER BY).
        if (isset($out[$guid])) {
            continue;
        }
        // A nickname is blank until the player sets one; the web pages say "Player <n>" then too.
        $name = trim((string)$row['nickname']);
        $out[$guid] = [$name !== '' ? $name : "Player $guid", (int)$row['slot_item1'], (int)$row['slot_item2']];
    }
    return $out;
}

/*
 * Reply rows for the given board positions (0-based indexes into $board).
 * Shape: Web.ScoresWithLevel (rank, fluctuation, guid, score, slot_item1, slot_item2, lev,
 * display_name); profile_img is the one extra key the official server always sent.
 */
function odq_rows(array $board, array $indexes)
{
    // Names and icons for just these players.
    $profiles = odq_profiles(array_map(fn($i) => $board[$i][0], $indexes));
    $rows = [];
    foreach ($indexes as $i) {
        [$guid, $score] = $board[$i];
        // A player whose Member row vanished meanwhile still gets a name.
        [$name, $slot1, $slot2] = $profiles[$guid] ?? ["Player $guid", 0, 0];
        $rows[] = [
            // Position on the board, 1 for the best.
            'rank' => $i + 1,
            // Rank change since the last ranking: this server keeps no history.
            'fluctuation' => 0,
            'guid' => odq_int32($guid),
            'score' => odq_int32($score),
            'slot_item1' => odq_int32($slot1),
            'slot_item2' => odq_int32($slot2),
            'lev' => OPENDMTQ_LEVEL,
            'display_name' => $name,
            'profile_img' => '',
        ];
    }
    return $rows;
}

/* Board positions $from..$to (1-based ranks, inclusive), at most OPENDMTQ_PAGE_MAX of them. */
function odq_page(array $board, $from, $to)
{
    $from = max(1, $from);
    $to = min(count($board), $to, $from + OPENDMTQ_PAGE_MAX - 1);
    return $to >= $from ? range($from - 1, $to - 1) : [];
}

/* The board position of $guid, or null when that player is not ranked. */
function odq_position(array $board, $guid)
{
    foreach ($board as $i => [$g, $_]) {
        if ($g === $guid) {
            return $i;
        }
    }
    return NULL;
}

/*
 * The charts a song ranking counts ($line 3, 4 or 5), or an empty list for anything else.
 * A song's ranking on a line sums each player's best score on every difficulty of that line.
 */
function odq_song_patterns($songId, $line)
{
    return in_array($line, OPENDMTQ_LINES, true) ? odq_patterns($line, $songId) : [];
}

/*
 * game.getLineTopRankWithLevel [line, fromRank, toRank, guids]: the TOTAL RANKING screen (line 0 for
 * TOTAL, 3/4/5 for its 2/3/4 LINE tabs) and, with guids holding the player's own guid, their own
 * rank (the top bar's RANK and "MY RANK"). The client picks a player's row by guid, so the reply is
 * the asked ranks followed by the asked players' rows that are not among them.
 * Shape: Web.GetLineTopRankWithLevelResponse {ranks: [ScoresWithLevel], rank_day: "YYYYMMDD"}.
 */
function odq_line_top_rank(array $params)
{
    $line = odq_int($params, 0, 0);
    // The day the ranking is for: rankings here are live, so today.
    $reply = ['ranks' => [], 'rank_day' => date('Ymd')];
    try {
        // Line 0 counts every chart; 3, 4 and 5 their line's; any other line nothing.
        $patterns = $line === 0 ? NULL : (in_array($line, OPENDMTQ_LINES, true) ? odq_patterns($line) : []);
        $board = odq_board($patterns);
        // The asked ranks.
        $indexes = odq_page($board, odq_int($params, 1, 1), odq_int($params, 2, 1));
        // Then the asked players (normally the player's own guid), when ranked and not listed yet.
        $guids = (isset($params[3]) && is_array($params[3])) ? $params[3] : [];
        foreach (array_slice($guids, 0, OPENDMTQ_PAGE_MAX) as $guid) {
            $i = is_numeric($guid) ? odq_position($board, (int)$guid) : NULL;
            if ($i !== NULL && !in_array($i, $indexes, true)) {
                $indexes[] = $i;
            }
        }
        $reply['ranks'] = odq_rows($board, $indexes);
    } catch (Throwable $e) {
        // Never break the batch: the player sees an empty ranking instead.
        error_log('opendmtq: getLineTopRankWithLevel: ' . $e->getMessage());
    }
    return $reply;
}

/*
 * game.getLineScoreRangeWithLevel [songId, line, fromRank, count]: a song's ranking on one line (the
 * song's RANK screen, the loading screen's top 5, the result screen's RANKINGS). The fourth value
 * is a count, not a last rank (the client sends toRank - fromRank + 1).
 * Shape: Web.GetLineScoreRangeWithLevelResponse {scores: [ScoresWithLevel]}.
 */
function odq_song_rank_range(array $params)
{
    $reply = ['scores' => []];
    try {
        $board = odq_board(odq_song_patterns(odq_int($params, 0, 0), odq_int($params, 1, 0)));
        $from = odq_int($params, 2, 1);
        $count = max(0, odq_int($params, 3, 0));
        $reply['scores'] = $count > 0 ? odq_rows($board, odq_page($board, $from, $from + $count - 1)) : [];
    } catch (Throwable $e) {
        error_log('opendmtq: getLineScoreRangeWithLevel: ' . $e->getMessage());
    }
    return $reply;
}

/*
 * game.getLineScoreMyRankWithLevel [guid, songId, line]: the player's own row in a song's ranking
 * ("MY RANK" on the song's RANK screen); no row when the player is not ranked (OUT OF RANK).
 * Shape: Web.getLineScoreMyRankWithLevelResponse {scores: [ScoresWithLevel]}.
 */
function odq_song_my_rank(array $params)
{
    $reply = ['scores' => []];
    try {
        $board = odq_board(odq_song_patterns(odq_int($params, 1, 0), odq_int($params, 2, 0)));
        $i = odq_position($board, odq_int($params, 0, -1));
        $reply['scores'] = $i === NULL ? [] : odq_rows($board, [$i]);
    } catch (Throwable $e) {
        error_log('opendmtq: getLineScoreMyRankWithLevel: ' . $e->getMessage());
    }
    return $reply;
}

/*
 * game.getLineScoreMyRankWithNext [guid, songId, line]: after a play, the player's row and the row
 * of the player one place above (the result screen shows the points still needed to pass them, and
 * "RANK CHANGED" when the rank improved). The client takes the last row that is not the player's
 * as the one to beat, so the order is: the player above, then the player.
 * Shape: Web.GetLineScoreMyRankWithNextResponse {scores: [ScoresWithLevel]}.
 */
function odq_song_my_rank_with_next(array $params)
{
    $reply = ['scores' => []];
    try {
        $board = odq_board(odq_song_patterns(odq_int($params, 1, 0), odq_int($params, 2, 0)));
        $i = odq_position($board, odq_int($params, 0, -1));
        // Unranked: no rows. First place: only the player's own.
        $reply['scores'] = $i === NULL ? [] : odq_rows($board, $i > 0 ? [$i - 1, $i] : [$i]);
    } catch (Throwable $e) {
        error_log('opendmtq: getLineScoreMyRankWithNext: ' . $e->getMessage());
    }
    return $reply;
}
