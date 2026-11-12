<?php
/*
 * The achievements (MY PAGE): which a player has, worked out from what the server knows, and when each was
 * earned. The save that earns one stores it with its date (AchievementDate).
 */

require_once __DIR__ . '/db.php';
require_once __DIR__ . '/content.php';
require_once __DIR__ . '/util.php';

/*
 * The game's achievements, as its table quest_achievement has them (patch 1.003.005: 34, ids 1 to 35 without 28):
 * id => [condition type, condition value, condition count, condition special, points]. What the server can tell of
 * each, by type:
 * - QUEST: reaching level <value>. The server gives every player level 99, so all of them.
 * - TOTAL_MPOINT: holding <value> MAX POINT. The server gives everyone 999,999, so all of them.
 * - LINE: a first clear on line <value> (3: 2LINE, 4: 3LINE), from the best scores (Play).
 * - ALL_COMBO, PERFECT: one ALL COMBO, one PERFECT PLAY, from the best scores.
 * - SIGNATURE: <count> clears of difficulty <value> (1 NORMAL, 2 HARD, 3 EXPERT), from the play log.
 * - TOTAL_SCORE: a TOTAL SCORE of <value>, the sum of the best scores of all time: the web's all-time total. The
 *   in-game total ranking counts this month's plays only, and an achievement once earned stays earned.
 * - EFFECTOR, ITEM_USE, BREAK: nowhere on the server, so never earned.
 * A clear is a play graded above F (the server keeps no life gauge). An achievement once earned stays earned: the
 * save that earns one stores it with its date (AchievementDate, odq_new_achievements()), and a stored one is
 * held whatever the records give now (the play log keeps a year).
 */
const OPENDMTQ_ACHIEVEMENTS = [
    1 => ['QUEST', 10, 1, '', 10], 2 => ['QUEST', 20, 1, '', 15], 3 => ['QUEST', 30, 1, '', 20], 4 => ['QUEST', 40, 1, '', 25],
    5 => ['QUEST', 50, 1, '', 30], 6 => ['QUEST', 60, 1, '', 35], 7 => ['QUEST', 70, 1, '', 50], 8 => ['QUEST', 80, 1, '', 60],
    9 => ['QUEST', 90, 1, '', 70], 10 => ['QUEST', 99, 1, '', 99],
    11 => ['LINE', 3, 1, '', 5], 12 => ['LINE', 4, 1, '', 5], 13 => ['ALL_COMBO', 1, 1, '', 30], 14 => ['PERFECT', 1, 1, '', 50],
    15 => ['EFFECTOR', 1, 10, 'fi,no,no fi2,no,no', 15], 16 => ['EFFECTOR', 1, 10, 'fo,no,no fo2,no,no', 20],
    17 => ['EFFECTOR', 1, 10, 'no,no,all', 15], 18 => ['EFFECTOR', 1, 10, 'no,all,no', 10],
    19 => ['TOTAL_MPOINT', 10000, 1, '', 25], 20 => ['TOTAL_MPOINT', 50000, 1, '', 50], 21 => ['TOTAL_MPOINT', 100000, 1, '', 80],
    22 => ['ITEM_USE', 1, 1, 'FP', 5], 23 => ['SIGNATURE', 1, 50, '', 30], 24 => ['SIGNATURE', 2, 50, '', 40],
    25 => ['SIGNATURE', 3, 50, '', 50], 26 => ['BREAK', 1, 1, '', 15], 27 => ['ITEM_USE', 1, 1, 'GR', 10],
    29 => ['TOTAL_SCORE', 1000000, 1, '', 20], 30 => ['TOTAL_SCORE', 2000000, 1, '', 40], 31 => ['TOTAL_SCORE', 4000000, 1, '', 50],
    32 => ['TOTAL_SCORE', 7500000, 1, '', 65], 33 => ['TOTAL_SCORE', 10000000, 1, '', 70], 34 => ['TOTAL_SCORE', 15000000, 1, '', 75],
    35 => ['TOTAL_SCORE', 30000000, 1, '', 99],
];
// What the server gives every player (game.getUserAsset), for the level and MAX POINT achievements.
const OPENDMTQ_MAX_POINT = 999999;

/*
 * game.getAchievementCount []: how many achievements the game has and the points of all of them, which
 * MY PAGE measures a player's share against. Shape: {total_achievement_count, total_achievement_point_sum}.
 */
function odq_achievement_count(array $params)
{
    return ['total_achievement_count' => count(OPENDMTQ_ACHIEVEMENTS),
            'total_achievement_point_sum' => array_sum(array_column(OPENDMTQ_ACHIEVEMENTS, 4))];
}

/*
 * What each chart is, for the achievements: pattern id => [line, signature], from the list the server serves, hidden songs
 * included. A save asks first whether its chart is one of them (odq_game_save_play()).
 */
function odq_chart_kinds()
{
    // From the song list's index (content.php), which a save, the achievements before and after it and MY PAGE all read
    // without decoding the list.
    return odq_song_index()['kinds'];
}

/*
 * The achievements a player has stored, each with when it was earned: achievement id => unix time. The save that
 * earns one writes it (odq_new_achievements()); only the admin pages' reset and delete remove them. One small
 * read by the table's key. Empty without the table (a database from before it, until the server's next start).
 */
function odq_stored_achievements($guid)
{
    $stored = [];
    $db = odq_db();
    // A missing table is no error here: nothing is stored yet.
    $q = $db ? @$db->prepare('SELECT achievement_id, earned_at FROM AchievementDate WHERE user_id = :g') : false;
    if ($q) {
        $q->bindValue(':g', (int)$guid, SQLITE3_INTEGER);
        $r = @$q->execute();
        while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
            $stored[(int)$row['achievement_id']] = (int)$row['earned_at'];
        }
    }
    return $stored;
}

/* The statement for a player's best rows as the achievements count them (:g, the guid): from Play_held alone. */
function odq_held_best_sql(): string
{
    return 'SELECT pattern_id, ' . odq_sql_score('score') . ' AS score, grade, isAllCombo, isPerfectPlay FROM Play WHERE user_id = :g';
}

/* The statement for a player's clears counted chart by chart (:g, the guid): from PlayLog_clears alone, in its order. */
function odq_held_clears_sql(): string
{
    return "SELECT pattern_id, COUNT(*) AS n FROM PlayLog WHERE user_id = :g AND grade != 'F' GROUP BY pattern_id";
}

/*
 * The achievements a player has: those stored, and those their records give by the rules above, from three quick reads:
 * what is stored, their best scores (Play) and their clears counted chart by chart (PlayLog, grouped). That is all a
 * save needs, before it and after it, to tell what it earned, so it reads no more. A stored one is held whatever the
 * records give now, so it is never named as new again. Returns [their ids, in the game's order; what dating them
 * needs]: 'stored' (odq_stored_achievements()), and 'combo' and 'perfect', the charts whose best row holds the
 * flag (pattern id => true; a save sets a flag once and never clears it).
 */
function odq_achievements_held($guid)
{
    // What is stored: held for good, with the date it was earned.
    $stored = odq_stored_achievements($guid);
    // What each chart is: its line and its difficulty.
    $charts = odq_chart_kinds();
    // Their best scores: the lines they cleared, the charts with ALL COMBO or PERFECT PLAY, and their total.
    $cleared_lines = $combo = $perfect = [];
    $total = 0;
    $db = odq_db();
    $q = $db ? $db->prepare(odq_held_best_sql()) : false;
    if ($q) {
        $q->bindValue(':g', (int)$guid, SQLITE3_INTEGER);
        $r = $q->execute();
        while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
            $pattern = (int)$row['pattern_id'];
            // The TOTAL SCORE: every chart's best, capped as the rankings cap it.
            $total += (int)$row['score'];
            // The charts with each flag, which the dates of those two achievements are worked out from.
            if ($row['isAllCombo'] === 'Y') {
                $combo[$pattern] = true;
            }
            if ($row['isPerfectPlay'] === 'Y') {
                $perfect[$pattern] = true;
            }
            // A best above F is a clear of the chart's line.
            if ($row['grade'] !== 'F' && isset($charts[$pattern])) {
                $cleared_lines[$charts[$pattern][0]] = true;
            }
        }
    }
    // Their clears by difficulty, from every play the log has.
    $clears = [];
    $q = $db ? $db->prepare(odq_held_clears_sql()) : false;
    if ($q) {
        $q->bindValue(':g', (int)$guid, SQLITE3_INTEGER);
        $r = @$q->execute();
        while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
            // The chart's difficulty; a chart the list does not know counts as none.
            $signature = $charts[(int)$row['pattern_id']][1] ?? -1;
            $clears[$signature] = ($clears[$signature] ?? 0) + (int)$row['n'];
        }
    }
    // Each achievement: stored, or earned by those figures, by its condition type.
    $ids = [];
    foreach (OPENDMTQ_ACHIEVEMENTS as $id => [$type, $value, $count]) {
        $earned = isset($stored[$id])
            || ($type === 'QUEST' && OPENDMTQ_LEVEL >= $value)
            || ($type === 'TOTAL_MPOINT' && OPENDMTQ_MAX_POINT >= $value)
            || ($type === 'LINE' && isset($cleared_lines[$value]))
            || ($type === 'ALL_COMBO' && $combo)
            || ($type === 'PERFECT' && $perfect)
            || ($type === 'SIGNATURE' && ($clears[$value] ?? 0) >= $count)
            || ($type === 'TOTAL_SCORE' && $total >= $value);
        if ($earned) {
            $ids[] = $id;
        }
    }
    return [$ids, ['stored' => $stored, 'combo' => $combo, 'perfect' => $perfect]];
}

/*
 * When a player earned each of the achievements $ids (with $held from odq_achievements_held()), as unix times,
 * for those with no stored date yet: what the server held before it stored them, and a player's achievements until
 * their next save stores them. Worked out from their play log replayed in the order it was played, so that a later
 * play does not move the estimate either:
 * - QUEST, TOTAL_MPOINT (held from the start): their first play.
 * - LINE: their first clear of a chart of that line.
 * - SIGNATURE: their <count>-th clear of that difficulty.
 * - TOTAL_SCORE: when the sum of their best scores, raised play by play as the log has them, first reached the step.
 * - PERFECT: their first play at a rate of 100 % (a judgement of 1000 in the log). That is exactly a PERFECT PLAY: the
 *   save's rate stays under 1000 when any note is judged below the top, the very notes that keep the flag off.
 * - ALL_COMBO: the log keeps no break count, and a best row's flag stays once set while its score may come from a
 *   later play without one. So: the first play of the earliest played chart that holds the flag, on or before the
 *   real date (which only a stored date has: the save that earned it stores its own time).
 * Where the log has no such play (plays from before it, or older than the year it keeps): their first play in the
 * log; now, for a player it has nothing of.
 * Read only when a date is missing: the whole log of the player is read.
 */
function odq_achievement_estimates($guid, array $ids, array $held)
{
    // What each chart is: its line and its difficulty.
    $charts = odq_chart_kinds();
    // What the replay looks for: the clear counts the difficulties' achievements need, and the TOTAL SCORE steps.
    $needed = $steps = [];
    foreach (OPENDMTQ_ACHIEVEMENTS as [$type, $value, $count]) {
        if ($type === 'SIGNATURE') {
            $needed[$value][$count] = true;
        } elseif ($type === 'TOTAL_SCORE') {
            $steps[] = $value;
        }
    }
    // The steps from the lowest: the running sum only grows, so it reaches them in this order.
    sort($steps);
    // What the replay finds: the first play; per line its first clear; per difficulty when each needed count came;
    // per chart its first play; the first play at 100 %; per TOTAL SCORE step when the sum reached it.
    $first = $perfect_first = 0;
    $line_first = $clears = $count_at = $chart_first = $step_at = $best = [];
    $sum = 0;
    $db = odq_db();
    // Their log in the order it was played; two plays in one second keep the order they were saved in.
    $q = $db ? $db->prepare('SELECT pattern_id, ' . odq_sql_score('score') . ' AS score, grade, judgement, played_at FROM PlayLog WHERE user_id = :g ORDER BY played_at, id') : false;
    if ($q) {
        $q->bindValue(':g', (int)$guid, SQLITE3_INTEGER);
        $r = @$q->execute();
        while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
            $pattern = (int)$row['pattern_id'];
            $when = (int)$row['played_at'];
            // The first play of all, and of this chart.
            $first = $first ?: $when;
            $chart_first[$pattern] = $chart_first[$pattern] ?? $when;
            // The first play without a note judged below the top.
            if ((int)$row['judgement'] >= 1000) {
                $perfect_first = $perfect_first ?: $when;
            }
            // A clear: the first of its line, and one more of its difficulty (noting when a needed count came).
            if ($row['grade'] !== 'F') {
                [$line, $signature] = $charts[$pattern] ?? [0, -1];
                $line_first[$line] = $line_first[$line] ?? $when;
                $clears[$signature] = ($clears[$signature] ?? 0) + 1;
                if (isset($needed[$signature][$clears[$signature]])) {
                    $count_at[$signature][$clears[$signature]] = $when;
                }
            }
            // The running TOTAL SCORE: this chart's best so far replaces its earlier best in the sum.
            $score = (int)$row['score'];
            if ($score > ($best[$pattern] ?? 0)) {
                $sum += $score - ($best[$pattern] ?? 0);
                $best[$pattern] = $score;
            }
            // Every step the sum has now reached, from the lowest left.
            while ($steps && $sum >= $steps[0]) {
                $step_at[array_shift($steps)] = $when;
            }
        }
    }
    // The first play of the earliest played of these charts, 0 when the log has none of them.
    $earliest = function (array $flagged) use ($chart_first) {
        $found = array_intersect_key($chart_first, $flagged);
        return $found ? min($found) : 0;
    };
    // Each achievement's time by its condition type; without one, the first play the log has, or now.
    $times = [];
    foreach ($ids as $id) {
        [$type, $value, $count] = OPENDMTQ_ACHIEVEMENTS[$id];
        if ($type === 'LINE') {
            $when = $line_first[$value] ?? 0;
        } elseif ($type === 'SIGNATURE') {
            $when = $count_at[$value][$count] ?? 0;
        } elseif ($type === 'TOTAL_SCORE') {
            $when = $step_at[$value] ?? 0;
        } elseif ($type === 'PERFECT') {
            $when = $perfect_first ?: $earliest($held['perfect']);
        } elseif ($type === 'ALL_COMBO') {
            $when = $earliest($held['combo']);
        } else {
            // QUEST and TOTAL_MPOINT: held from the start, so their first play.
            $when = $first;
        }
        $times[$id] = $when ?: ($first ?: time());
    }
    return $times;
}

/*
 * When a player earned each of the achievements $ids, as unix times: the stored date where there is one (it wins),
 * the estimate from the log for the others (odq_achievement_estimates()), which is read only when one has no
 * stored date.
 */
function odq_achievement_times($guid, array $ids, array $held)
{
    $times = $missing = [];
    foreach ($ids as $id) {
        if (isset($held['stored'][$id])) {
            $times[$id] = $held['stored'][$id];
        } else {
            $missing[] = $id;
        }
    }
    // The others, estimated; a player whose achievements are all stored has their log left unread.
    if ($missing) {
        $times += odq_achievement_estimates($guid, $missing, $held);
    }
    return $times;
}

/*
 * Stores when a player earned achievements ($times: id => unix time), each once: a row already there keeps its date
 * (INSERT OR IGNORE), so the first save to store one decides it for good. One transaction for them all. A database
 * that cannot take it now (no table yet, a lock past the wait) leaves them for the player's next save.
 */
function odq_store_achievements($guid, array $times)
{
    $db = odq_db();
    if (!$db || !$times) {
        return;
    }
    // One commit for every row, not one per row. Without the write lock (another writer kept it past the wait) nothing
    // is tried: each row on its own would wait as long again, and the player's next save stores them.
    if (!@$db->exec('BEGIN IMMEDIATE')) {
        return;
    }
    $q = @$db->prepare('INSERT OR IGNORE INTO AchievementDate (user_id, achievement_id, earned_at) VALUES (:g, :a, :t)');
    if ($q) {
        foreach ($times as $id => $when) {
            $q->bindValue(':g', (int)$guid, SQLITE3_INTEGER);
            $q->bindValue(':a', (int)$id, SQLITE3_INTEGER);
            $q->bindValue(':t', (int)$when, SQLITE3_INTEGER);
            @$q->execute();
            // The same statement again for the next row; a row that failed reports its error here again.
            @$q->reset();
        }
    }
    // What went in is kept; a failed row stays missing and is stored at the player's next save.
    @$db->exec('COMMIT');
}

/*
 * game.getOwnAchievementList [guid]: the achievements a player has, by the rules above, each with the date it was
 * earned (odq_achievement_times()). Shape: {own_achievements: [{achievement_id, reg_date "YYYYmmddHHMMSS"}]}.
 * Reads only: what has no stored date yet is estimated here and stored by the player's next save.
 */
function odq_own_achievements(array $params)
{
    $guid = odq_int($params, 0, 0);
    // What they have, and when each came.
    [$ids, $held] = odq_achievements_held($guid);
    $times = odq_achievement_times($guid, $ids, $held);
    // In the game's order (by id), with the date as the game reads it (the server's zone).
    $own = [];
    foreach ($ids as $id) {
        $own[] = ['achievement_id' => $id, 'reg_date' => date('YmdHis', $times[$id])];
    }
    return ['own_achievements' => $own];
}

/*
 * The ids of the achievements a player has now; before a save (game.savePlayResult), to tell what it earned. Empty
 * when they cannot be worked out: the save goes on, and the reply then names what the player has as new only
 * if it can be read afterwards, which is then the truth for them too.
 */
function odq_achievement_ids($guid)
{
    try {
        // The ids alone: no dates, which would read the whole play log on every save.
        return odq_achievements_held((int)$guid)[0];
    } catch (Throwable $e) {
        return [];
    }
}

/*
 * After a save: the achievements it earned (those the player has now and did not have before it), for the save's
 * reply, where the game shows each as it would its own. The client's Web.NewAchievement, whose JSON names were read
 * from its attribute code: achievement_id, obtain_point, condition_type, condition_value, condition_count,
 * condition_special, play_count, reg_date, complete_yn. Always a list (the client stops on a missing one). A
 * player who had nothing before (it could not be read) earns nothing here, so that the reply never lists every
 * achievement as new at once.
 * It is also where the dates are stored (AchievementDate), the only place: what this save earned gets this save's
 * time, which is now, as the reply is made (the play's row in the log was written a moment before, with the same
 * second or the one before it). Anything else the player has with no stored date yet (held before the table was
 * there) gets its estimate from the log, once. reg_date is the stored date, which MY PAGE gives from then on, so the
 * list the game merges the reply into and the one it reads next agree. With everything stored and nothing earned,
 * which is most saves, this reads no more than odq_achievements_held() and writes nothing.
 */
function odq_new_achievements($guid, array $had)
{
    try {
        if (!$had) {
            return [];
        }
        // What the player has now, and what of it is stored: the stored ones were read along with the rest.
        [$ids, $held] = odq_achievements_held((int)$guid);
        // What this save earned (the player did not have it before), and what they had with no stored date yet.
        $earned = $missing = [];
        foreach ($ids as $id) {
            if (!in_array($id, $had, true)) {
                $earned[] = $id;
            } elseif (!isset($held['stored'][$id])) {
                $missing[] = $id;
            }
        }
        // Most saves: nothing new, and nothing to store.
        if (!$earned && !$missing) {
            return [];
        }
        // What this save earned, at this save's time; the rest at the times the log gives them.
        $now = time();
        $times = array_fill_keys($earned, $now);
        if ($missing) {
            $times += odq_achievement_estimates((int)$guid, $missing, $held);
        }
        odq_store_achievements((int)$guid, $times);
        if (!$earned) {
            return [];
        }
        // The dates as stored: a save at the same moment may have stored one of these first, and its date stands.
        $stored = odq_stored_achievements((int)$guid);
        $new = [];
        foreach ($earned as $id) {
            [$type, $value, $count, $special, $points] = OPENDMTQ_ACHIEVEMENTS[$id];
            $new[] = ['achievement_id' => $id, 'obtain_point' => $points, 'condition_type' => $type, 'condition_value' => $value,
                      'condition_count' => $count, 'condition_special' => $special, 'play_count' => $count,
                      'reg_date' => date('YmdHis', $stored[$id] ?? $now), 'complete_yn' => 'Y'];
        }
        return $new;
    } catch (Throwable $e) {
        error_log('opendmtq: new achievements: ' . $e->getMessage());
        return [];
    }
}
