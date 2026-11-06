<?php
/*
 * Small rules the replies share: how a request's numbers are read, and the limits of what the client can read
 * back. The client reads every number as a 32-bit int and stops on a larger one.
 */

// The level every player has: the server gives everyone the highest (game.getUserAsset), and the rankings show it.
const OPENDMTQ_LEVEL = 99;
// The largest number the client can read.
const OPENDMTQ_INT_MAX = 2147483647;
// The most rows one ranking reply carries (the client asks for 20 at a time).
const OPENDMTQ_PAGE_MAX = 100;
// The line codes the song list and the client use: 3, 4 and 5 are the 2, 3 and 4 LINE tabs.
const OPENDMTQ_LINES = [3, 4, 5];

/* A parameter as an int, $default when it is missing or not a number. */
function odq_int(array $params, $index, $default)
{
    // Numbers may come as JSON numbers or numeric strings.
    return (isset($params[$index]) && is_numeric($params[$index])) ? (int)$params[$index] : $default;
}

/* An int the client can read: clamped to its 32-bit range. */
function odq_int32($value)
{
    return (int)max(-OPENDMTQ_INT_MAX - 1, min(OPENDMTQ_INT_MAX, (int)$value));
}

/*
 * $value as an int between $min and $max. Anything that is not a finite number (a string, NAN or
 * INF from an absurd result) counts as $min.
 */
function odq_clamp($value, $min, $max)
{
    // NAN and INF are floats that is_numeric() accepts; neither is a usable value.
    if (!is_numeric($value) || (is_float($value) && !is_finite($value))) {
        return $min;
    }
    // Compare as numbers first, so a float beyond PHP's int range clamps instead of wrapping.
    return (int)max($min, min($max, $value));
}

/*
 * A play's score as game.savePlayResult may store it. The
 * client computes the judgement counts and nothing checks them, so a forged result could store any
 * number: the client reads scores as 32-bit ints, and SQLite's SUM() stops with "integer overflow"
 * past 2^63, which emptied every ranking. A real chart scores well under a million.
 */
function odq_clamp_score($score)
{
    return odq_clamp($score, 0, OPENDMTQ_INT_MAX);
}

/*
 * One stored score as the rankings sum it, as SQL: rows saved before scores were clamped (or
 * restored from such a backup) count as the most the client can show, never as an overflow.
 * The sum of every chart's capped score stays far inside SQLite's 64-bit range.
 */
function odq_sql_score($column)
{
    return "MIN(MAX($column, 0), " . OPENDMTQ_INT_MAX . ')';
}
