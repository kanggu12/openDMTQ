<?php
/* One player: totals, grade spread, recent plays and best records. */
require __DIR__ . '/lib.php';
// For those signed in only (a stranger goes to the sign-in page and comes back here).
require_sign_in();

// The player's guid, as players() lists them (for most players also their Member id): Play and
// PlayLog keep scores under it, whichever phone played.
$id = (int)($_GET['id'] ?? 0);
$db = db();
$me = $db ? player_figures($db, $id) : null;
if (!$me) {
    // Without a database the player may well exist: unavailable for now, not unknown.
    http_response_code($db ? 404 : 503);
}
// Rank among players with at least one chart, by total score.
$rank = $me['rank'] ?? null;
$best = $me ? rows($db, "SELECT * FROM Play WHERE user_id = :id ORDER BY score DESC", [':id' => $id]) : [];
$recent = ($me && has_playlog($db)) ? rows($db, "SELECT * FROM PlayLog WHERE user_id = :id ORDER BY played_at DESC, id DESC LIMIT 15", [':id' => $id]) : [];
$grades = array_count_values(array_column($best, 'grade'));
$charts = charts();
$songs = songs_by_id();
// When each best record was set: the newest play that set a record on its chart. Records older than
// the play log have no time.
$set_at = [];
if ($me && has_playlog($db)) {
    foreach (rows($db, "SELECT pattern_id, MAX(played_at) AS at FROM PlayLog WHERE user_id = :id AND is_record = 1
                         GROUP BY pattern_id", [':id' => $id]) as $r) {
        $set_at[(int)$r['pattern_id']] = (int)$r['at'];
    }
}

/* Song and chart cells for a pattern id. $when, a play's time, joins the chart under the title,
   where phones show both instead of their own columns. */
function chart_cells(int $pid, array $charts, array $songs, string $when = ''): string
{
    [$sid, $line, $diff, $sig] = $charts[$pid] ?? [0, 0, 0, 0];
    $song = $songs[$sid] ?? null;
    $at = $when !== '' ? h($when) : '';
    if (!$song) {
        return '<td class="jk">' . row_jacket(null) . '</td><td class="song-cell">' . t('player.chart', ['id' => $pid]) . ($at ? '<span class="chart-sub">' . $at . '</span>' : '') . '</td><td class="chart"></td>';
    }
    // The chart has its own column, and goes under the title on phones.
    $label = h(chart_label($line, $diff, $sig));
    return '<td class="jk">' . row_jacket($song) . '</td><td class="song-cell"><a href="song.php?id=' . $sid . '&amp;chart=' . $pid . '">' . h(song_title($song)) . '</a>'
        . '<span class="chart-sub">' . $label . ($at ? ' · ' . $at : '') . '</span></td><td class="chart">' . $label . '</td>';
}

// How they have been playing: plays per day over the last twelve weeks, and their records by LINE mode.
$weeks = 12;
$days_back = [];
if ($me && has_playlog($db)) {
    // From the first day the grid shows: what lies before it is neither in its sum nor in its colours.
    $since = strtotime('-' . ($weeks - 1) . ' weeks', strtotime('today') - ((int)date('N') - 1) * 86400);
    foreach (rows($db, "SELECT played_at FROM PlayLog WHERE user_id = :id AND played_at >= :since", [':id' => $id, ':since' => $since]) as $r) {
        $key = date('Y-m-d', (int)$r['played_at']);
        $days_back[$key] = ($days_back[$key] ?? 0) + 1;
    }
}
// Their records by the chart's level, as the game's own song select shows how far one has come through a level: for each
// level the server's songs have, how many of its charts they hold a record on, split by grade, out of all of them.
$levels = [];
foreach ($charts as [$sid, , $diff]) {
    if (isset($songs[$sid]) && $diff > 0) {
        $levels[$diff]['all'] = ($levels[$diff]['all'] ?? 0) + 1;
    }
}
foreach ($best as $r) {
    $diff = $charts[(int)$r['pattern_id']][2] ?? 0;
    if (isset($levels[$diff])) {
        $levels[$diff]['grades'][$r['grade']] = ($levels[$diff]['grades'][$r['grade']] ?? 0) + 1;
    }
}
ksort($levels);
// Their broadcasts, the newest few: on the live page all of them, narrowed to them. Only those four are read.
$casts = $me ? live_past($db, 4, $id) : [];

/* The last weeks as a grid, a column per week from Monday to Sunday, the newest at the right: one colour, stronger with
   more plays that day. Over the columns the month where one begins, and under them what the colours mean. */
function activity_grid(array $counts, int $weeks): string
{
    $top = $counts ? max($counts) : 0;
    // The Monday of this week, then back. PHP's N: Monday 1 to Sunday 7.
    $monday = strtotime('today') - ((int)date('N') - 1) * 86400;
    $cells = '';
    $months = '';
    $month = '';
    for ($week = $weeks - 1; $week >= 0; $week--) {
        // The first column of each month has its name; the first of the grid too, so that the grid says where it starts.
        $first = strtotime('-' . $week . ' weeks', $monday);
        $name = lang() === 'ko' ? date('n', $first) . '월' : date('M', $first);
        $months .= '<span>' . ($name !== $month ? h($name) : '') . '</span>';
        $month = $name;
        for ($day = 0; $day < 7; $day++) {
            $at = strtotime('+' . $day . ' days', strtotime('-' . $week . ' weeks', $monday));
            if ($at > time()) {
                $cells .= '<i class="none"></i>';
                continue;
            }
            $key = date('Y-m-d', $at);
            $n = $counts[$key] ?? 0;
            $step = !$n || !$top ? 0 : 1 + min(4, (int)(4 * $n / $top));
            $cells .= '<i class="c' . $step . '" data-tip="' . h(t('player.day_plays', ['day' => $key, 'n' => $n])) . '"></i>';
        }
    }
    $steps = '';
    for ($step = 0; $step <= 5; $step++) {
        $steps .= '<i class="c' . $step . '"></i>';
    }
    return '<div class="activity-months" aria-hidden="true">' . $months . '</div>'
        . '<div class="activity" role="img" aria-label="' . h(strip_tags(t('player.activity'))) . '">' . $cells . '</div>'
        . '<div class="activity-key" aria-hidden="true">' . t('player.fewer') . '<span class="activity-steps">' . $steps . '</span>' . t('player.more') . '</div>';
}

$missing = $db ? t('player.notfound') : t('player.unavailable');
page_header($me ? $me['name'] : strip_tags($missing), 'ranking');
if (!$me): ?>
  <?= $db ? lost($missing, t('nf.text'), [['/opendmtq/ranking.php', t('go.rankings')]]) : lost($missing, t('unavailable'), [], false) ?>
<?php page_footer(); exit; endif; ?>
  <section class="card">
    <div class="playerhead">
      <?php if ($rank): ?><span class="playerhead-place<?= $rank <= 3 ? ' place-' . (int)$rank : '' ?>" title="<?= h(strip_tags(t('player.rank', ['n' => $rank]))) ?>"><?= t('player.rank_short', ['n' => (int)$rank]) ?></span><?php endif; ?>
      <h2><?= h($me['name']) ?><?= live_mark($db, $id) ?></h2>
      <div class="stats">
        <div class="stat"><span class="lbl"><?= t('player.total') ?></span><span class="num"><?= number_format($me['total']) ?></span></div>
        <div class="stat"><span class="lbl"><?= t('player.charts') ?></span><span class="num"><?= (int)$me['charts'] ?></span></div>
        <div class="stat"><span class="lbl"><?= t('player.avg') ?></span><span class="num"><?= $me['charts'] > 0 ? accuracy($me['avg_judgement']) : '–' ?></span></div>
      </div>
    </div>
    <?php if ($best): ?>
      <?php // How many charts at each grade: a gauge in the grades' colours, the counts under it. Only the grades and marks
            // the player has: a row of zeros tells nothing. ?>
      <div class="grade-bar" aria-hidden="true">
        <?php foreach (['S', 'A', 'B', 'C', 'D', 'E', 'F'] as $g): if (!empty($grades[$g])): ?>
          <i class="grade g<?= $g ?>" style="flex:<?= (int)$grades[$g] ?>;background:var(--g);text-shadow:none;padding:0"></i>
        <?php endif; endforeach; ?>
      </div>
      <p class="grades">
        <?php foreach (['S', 'A', 'B', 'C', 'D', 'E', 'F'] as $g): if (!empty($grades[$g])): ?>
          <span class="g-item"><span class="grade g<?= $g ?>"><?= $g ?></span><?= (int)$grades[$g] ?></span>
        <?php endif; endforeach; ?>
        <?php if ($me['ac'] > 0): ?>
          <span class="g-item"><?= mark('ac') ?><?= (int)$me['ac'] ?></span>
        <?php endif; ?>
        <?php if ($me['perfect'] > 0): ?>
          <span class="g-item"><?= mark('pp') ?><?= (int)$me['perfect'] ?></span>
        <?php endif; ?>
      </p>
    <?php endif; ?>
  </section>
  <?php if ($casts): ?>
    <section class="card">
      <h2><?= t('live.past') ?> <a class="more" href="live.php?who=<?= $id ?>"><?= t('live.more') ?></a></h2>
      <ul class="past-list"><?php foreach ($casts as $x): ?><?= past_card($x) ?><?php endforeach; ?></ul>
    </section>
  <?php endif; ?>
  <?php if ($best): ?>
    <div class="two">
      <section class="card">
        <h2><?= t('player.activity') ?> <span class="meta-inline"><?= t('player.activity_sum', ['n' => array_sum($days_back)]) ?></span></h2>
        <?= activity_grid($days_back, $weeks) ?>
      </section>
      <?php // A row per level: the bar as long as the level's charts, filled with their records in the grades' colours (the
            // card above names them), what is left the rail's. ?>
      <section class="card">
        <h2><?= t('player.levels') ?></h2>
        <div class="levels">
          <?php foreach ($levels as $lv => $l): $held = array_sum($l['grades'] ?? []); ?>
            <div class="level" data-tip="<?= h(strip_tags(t('player.level_tip', ['lv' => $lv, 'n' => $held, 'all' => $l['all']]))) ?>">
              <span class="level-name">Lv <?= (int)$lv ?></span>
              <span class="level-bar" data-layout-ok="segments by grade"><?php foreach (['S', 'A', 'B', 'C', 'D', 'E', 'F'] as $g): if (!empty($l['grades'][$g])): ?><i class="g<?= $g ?>" style="width:<?= round(100 * $l['grades'][$g] / $l['all'], 2) ?>%"></i><?php endif; endforeach; ?></span>
              <b><?= $held ?><small> / <?= (int)$l['all'] ?></small></b>
            </div>
          <?php endforeach; ?>
        </div>
      </section>
    </div>
  <?php endif; ?>
  <?php // Both lists have the same columns at fixed widths (style.css table.plays): jacket, song, chart, score, mark,
        // time. So the two cards' columns line up, one above the other. ?>
  <div class="stack">
    <?php // Nothing played at all: one box says so, not one for each list. ?>
    <?php if (!$recent && !$best): ?>
    <section class="card"><p class="empty"><?= t('player.recent_empty') ?></p></section>
    <?php else: ?>
    <section class="card">
      <h2><?= t('player.recent') ?></h2>
      <?php if (!$recent): ?>
        <p class="empty"><?= t('player.recent_empty') ?></p>
      <?php else: ?>
        <div class="table-scroll"><table class="compact plays"><tbody>
        <?php foreach ($recent as $r): $when = ago((int)$r['played_at']); ?>
          <tr><?= chart_cells((int)$r['pattern_id'], $charts, $songs, $when) ?><td class="r"><?= number_format($r['score']) ?></td><td class="flag"><?= $r['is_record'] ? '<span class="mark new" title="' . h(t('mark.new')) . '">NEW</span>' : '' ?></td><td class="meta-inline when"><?= h($when) ?></td></tr>
        <?php endforeach; ?>
        </tbody></table></div>
      <?php endif; ?>
    </section>
    <section class="card">
      <h2><?= t('player.best') ?><?= count($best) > 30 ? ' <span class="meta-inline">' . t('player.best_of', ['shown' => 30, 'all' => count($best)]) . '</span>' : '' ?></h2>
      <?php if (!$best): ?>
        <p class="empty"><?= t('player.best_empty') ?></p>
      <?php else: ?>
        <div class="table-scroll"><table class="compact plays"><tbody>
        <?php foreach (array_slice($best, 0, 30) as $r): $when = ago($set_at[(int)$r['pattern_id']] ?? null); ?>
          <tr><?= chart_cells((int)$r['pattern_id'], $charts, $songs, $when) ?><td class="r"><?= number_format($r['score']) ?></td><td class="flag"><?= grade_cell($r) ?></td><td class="meta-inline when"><?= h($when) ?></td></tr>
        <?php endforeach; ?>
        </tbody></table></div>
      <?php endif; ?>
    </section>
    <?php endif; ?>
  </div>
  <script src="/opendmtq/tips.js" defer></script>
<?php page_footer();
