<?php
/*
 * The site's rankings: who counts as a player and what a score counts for, every player's figures and rank, and the
 * months, which are the game's own monthly board (odq_month_board() in server/game/src/ranking.php) with the players'
 * names. lib.php loads this file for every page; it is never a page of its own (server/apache/site.conf).
 */

// The game's monthly board, the one its ranking screens show, and the rules the site's own lists share with it.
require_once __DIR__ . '/../game/src/ranking.php';

// The game's check account (./opendmtq check logs in with it): never listed as a player, as it is never ranked.
const CHECK_UDID = OPENDMTQ_CHECK_UDID;

/* The home page's newest records (:shown of them, players with an account only, :check binding PLAYER_ROWS), each with
   the player's best on that chart before it: the newest rows with is_record from their own index (PlayLog_records,
   server/game/bin/setup-db.php), not the whole log read back from its newest play. tests/game/protocol.sh checks the plan
   SQLite makes of it. */
function recent_records_sql(): string
{
    return "SELECT l.*, m.nickname, m.guid AS mid,
            (SELECT MAX(p.score) FROM PlayLog p WHERE p.user_id = l.user_id AND p.pattern_id = l.pattern_id
              AND (p.played_at < l.played_at OR (p.played_at = l.played_at AND p.id < l.id))) AS before
       FROM PlayLog l JOIN (" . PLAYER_ROWS . ") m ON m.guid = l.user_id
      WHERE l.is_record = 1 ORDER BY l.played_at DESC, l.id DESC LIMIT :shown";
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
   as the in-game rankings pick it (odq_profiles()). The server's check account and rows
   without a guid are left out. Bind :check to CHECK_UDID. */
const PLAYER_ROWS = "SELECT guid, nickname FROM (
        SELECT CAST(guid AS INTEGER) AS guid, nickname,
               ROW_NUMBER() OVER (PARTITION BY CAST(guid AS INTEGER)
                                  ORDER BY (id = CAST(guid AS INTEGER)) DESC, id ASC) AS pick
          FROM Member WHERE udid IS NOT :check AND guid IS NOT NULL)
     WHERE pick = 1";

/* A stored score (column p.score) as the rankings sum it: the game's own cap (odq_sql_score() in game/src/util.php),
   which its monthly board puts on every score too. The game now caps what it saves, but rows saved before (or restored
   from an old backup) can be forged and huge, and SQLite's SUM() stops with "integer overflow" past 2^63, which emptied
   every ranking. Capped at the most the game can show, no sum of them comes near that. */
define('SCORE_SQL', odq_sql_score('p.score'));

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

/* Every player's figures in Play by guid (PLAYER_FIGURES' columns), worked out once and kept while nothing in the log, the
   bests or the players changes (odq_kept() in server/game/src/ranking.php): a look at the rankings costs no more than
   reading them. */
function play_figures(SQLite3 $db): array
{
    return odq_kept($db, 'site figures', function () use ($db) {
        $figures = [];
        foreach (rows($db, "SELECT p.user_id, " . PLAYER_FIGURES . " FROM Play p GROUP BY p.user_id") as $row) {
            $figures[(int)$row['user_id']] = $row;
        }
        return $figures;
    });
}

/* How many of each player's bests a keyboard play set (Play's keys, which the game server's save keeps: game/src/game.php),
   by guid: the mark on a total. From the index of the keyboard's bests alone (Play_keys, server/game/bin/setup-db.php), so
   that a server where nobody plays with the keyboard reads nothing for it. tests/game/protocol.sh checks the plan. */
const KEYS_BESTS = "SELECT p.user_id, COUNT(*) AS n FROM Play p WHERE p.keys = 1 GROUP BY p.user_id";

/* For one month's board (from :since to before :until), how many of the charts it counts had a keyboard play as each
   player's best that month: the month's top score on the chart, the play that got there first (as a best row keeps the
   play that set it), capped as the board caps it. Only the charts a player played with the keyboard that month are looked
   at, from the index of the keyboard's plays (PlayLog_keys); each one's best from that player's plays of that chart
   (PlayLog_clears): the + before the times keeps SQLite from reading the whole chart's month instead (PlayLog_chart), every
   player's plays of it. tests/game/protocol.sh checks the plan SQLite makes of it. */
const MONTH_KEYS = "SELECT k.user_id, COUNT(*) AS n FROM (
        SELECT DISTINCT l.user_id, l.pattern_id FROM PlayLog l
         WHERE l.keys = 1 AND l.played_at >= :since AND l.played_at < :until) k
     WHERE (SELECT b.keys FROM PlayLog b
             WHERE b.user_id = k.user_id AND b.pattern_id = k.pattern_id AND +b.played_at >= :since AND +b.played_at < :until
             ORDER BY MIN(MAX(b.score, 0), 2147483647) DESC, b.played_at, b.id LIMIT 1) = 1
     GROUP BY k.user_id";

/* Players' counts by guid from one of the two statements above, kept by $name while nothing in the log, the bests or the
   players changes (odq_kept()), as the totals beside them are. Players with none are left out. */
function keys_counts(SQLite3 $db, string $name, string $sql, array $params = []): array
{
    return odq_kept($db, $name, function () use ($db, $sql, $params) {
        $counts = [];
        foreach (rows($db, $sql, $params) as $row) {
            $counts[(int)$row['user_id']] = (int)$row['n'];
        }
        return $counts;
    });
}

/* How many of each player's bests a keyboard play set, by guid (KEYS_BESTS): what the totals of every month count. */
function keys_bests(SQLite3 $db): array
{
    return keys_counts($db, 'site keys', KEYS_BESTS);
}

/* How many of the charts of each player's month (from $since to before $until) had a keyboard play as its best, by guid
   (MONTH_KEYS): what a month's score counts. */
function month_keys(SQLite3 $db, int $since, int $until): array
{
    return keys_counts($db, 'month keys ' . json_encode([$since, $until]), MONTH_KEYS, [':since' => $since, ':until' => $until]);
}

/* Each player's total (PLAYER_TOTALS) by guid, players with an account only, kept as play_figures() is. */
function play_totals(SQLite3 $db): array
{
    return odq_kept($db, 'site totals', function () use ($db) {
        $totals = [];
        foreach (rows($db, PLAYER_TOTALS, [':check' => CHECK_UDID]) as $row) {
            $totals[(int)$row['user_id']] = (int)$row['total'];
        }
        return $totals;
    });
}

/* Every player with ranking figures, best total first. Best score per chart is what counts. The
   id is the player's guid (for most players also their Member id), as player.php takes it. Scores are
   added up first and matched to names here: the same join in SQL took twice as long. keys: how many of
   their bests a keyboard play set. */
function players(SQLite3 $db): array
{
    $figures = play_figures($db);
    // How many of each one's bests a keyboard play set: the mark beside their figures.
    $keys = keys_bests($db);
    // What a player who has not played shows.
    $none = ['charts' => 0, 'total' => 0, 's_count' => 0, 'ac' => 0, 'perfect' => 0, 'avg_judgement' => 0];
    $rows = [];
    foreach (rows($db, PLAYER_ROWS, [':check' => CHECK_UDID]) as $row) {
        $id = (int)$row['guid'];
        $mine = array_merge($none, array_intersect_key($figures[$id] ?? [], $none));
        $rows[] = ['id' => $id, 'nickname' => $row['nickname'], 'keys' => $keys[$id] ?? 0] + $mine;
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

/* A moment of the server's clock in the page's words: "1 Dec at 09:00", "12월 1일 9:00". */
function month_moment(int $at): string
{
    // The month and the day are held together by a no-break space, so that a line never ends between them ("1" / "Dec").
    return lang() === 'ko' ? date('n', $at) . "월\u{00A0}" . date('j', $at) . '일 ' . date('G:i', $at) : date('j', $at) . "\u{00A0}" . date('M', $at) . ' at ' . date('H:i', $at);
}

/* A month by its first moment (odq_month_start()), in the page's words: "October 2026", "2026년 10월". Named in UTC, as its
   bounds are: west of UTC that first moment is still the evening before on the server's clock (October's is 30 September
   at 20:00 in New York), which would name every month of the hall of fame one month early. */
function month_name(int $at): string
{
    // gmdate(): the month the rankings count, whatever zone the server keeps (TZ, entrypoint.sh).
    return lang() === 'ko' ? gmdate('Y', $at) . '년 ' . gmdate('n', $at) . '월' : gmdate('F Y', $at);
}

/* The players of one month (from $since to before $until), best first: the game's own board of that month, every chart
   (odq_month_board()), so that the site ranks a month as the game does, with the names as every page shows them.
   id, name, score, charts, and keys: how many of those charts had a keyboard play as the month's best. */
function month_players(SQLite3 $db, int $since, int $until): array
{
    // The site's own read-only handle: the board only reads.
    $board = odq_month_board($db, $since, $until, NULL);
    // Nobody played that month: no names to look up.
    if (!$board) {
        return [];
    }
    // One name per player, as every list of the site picks it (PLAYER_ROWS); every player on the board has one.
    $names = [];
    foreach (rows($db, PLAYER_ROWS, [':check' => CHECK_UDID]) as $m) {
        $names[(int)$m['guid']] = $m['nickname'];
    }
    // How many of the charts each one's score counts had a keyboard play as that month's best: the mark beside the score.
    $keys = month_keys($db, $since, $until);
    $rows = [];
    foreach ($board as [$guid, $score, $charts]) {
        $row = ['id' => $guid, 'nickname' => $names[$guid] ?? '', 'score' => $score, 'charts' => $charts, 'keys' => $keys[$guid] ?? 0];
        // "Player <n>" in the page's language for a player without a name.
        $row['name'] = player_name($row);
        $rows[] = $row;
    }
    return $rows;
}

/* The months before this one, newest first, each with its first three: [[month's name, players], ...]. Only months
   anybody played in, $count months back at most. */
function past_months(SQLite3 $db, int $count = 6): array
{
    $out = [];
    for ($back = 1; $back <= $count; $back++) {
        $top = array_slice(month_players($db, odq_month_start($back), odq_month_start($back - 1)), 0, 3);
        if ($top) {
            $out[] = [month_name(odq_month_start($back)), $top];
        }
    }
    return $out;
}

/* The best players who have played, in the order of players(): id, name, total, and how many of their bests a keyboard
   play set. */
function top_players(SQLite3 $db, int $limit): array
{
    // Highest total first, the older account on a tie, as players() and the in-game rankings.
    $totals = play_totals($db);
    $order = array_keys($totals);
    usort($order, fn($a, $b) => [$totals[$b], $a] <=> [$totals[$a], $b]);
    $first = array_slice($order, 0, max(0, $limit));
    // Their names as they are now: one row per player (PLAYER_ROWS), read for these alone.
    $names = [];
    foreach (rows($db, PLAYER_ROWS, [':check' => CHECK_UDID]) as $row) {
        $names[(int)$row['guid']] = $row['nickname'];
    }
    // How many of each one's bests a keyboard play set, as the rankings mark them.
    $keys = keys_bests($db);
    $rows = [];
    foreach ($first as $guid) {
        // A player whose account went since the totals were kept is left out, as the join left them out.
        if (!array_key_exists($guid, $names)) {
            continue;
        }
        $row = ['id' => $guid, 'nickname' => $names[$guid], 'total' => $totals[$guid], 'keys' => $keys[$guid] ?? 0];
        $row['name'] = player_name($row);
        $rows[] = $row;
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
        $total = (int)$row['total'];
        $ahead = 0;
        foreach (play_totals($db) as $other => $their) {
            $ahead += ($their > $total || ($their === $total && $other < $guid)) ? 1 : 0;
        }
        $row['rank'] = $ahead + 1;
    }
    return $row;
}
