<?php
/* Overall ranking: best score per chart, summed. */
require __DIR__ . '/lib.php';
// For those signed in only (a stranger goes to the sign-in page and comes back here).
require_sign_in();

$db = db();
$everyone = array_values(array_filter($db ? players($db) : [], fn($p) => $p['charts'] > 0));
// Sort keys a visitor can pick (with their tab labels); total best score is the default. "This month" is the game's
// own ranking, which starts anew each month.
$sorts = ['total' => t('nav.total'), 'month' => t('nav.month'), 's_count' => t('nav.s'), 'perfect' => t('nav.perfect'), 'charts' => t('nav.charts')];
$sort = is_string($_GET['sort'] ?? null) && isset($sorts[$_GET['sort']]) ? $_GET['sort'] : 'total';
$month = $sort === 'month';
$past_months = [];
if ($month) {
    // This month's players as the game ranks them (month_players() orders them), and the first three of the months
    // before, for the hall of fame under the table.
    $players = ($db && has_playlog($db)) ? month_players($db, odq_month_start(), PHP_INT_MAX) : [];
    $past_months = ($db && has_playlog($db)) ? past_months($db) : [];
} else {
    // Then by total, then the older account first (lower id), as on every other page: PHP 7.4's sort
    // is not stable, so equal players would otherwise swap places between visits.
    usort($everyone, fn($a, $b) => [$b[$sort], $b['total'], $a['id']] <=> [$a[$sort], $a['total'], $b['id']]);
    // Only those who have some of what is being ranked: a list of noughts is no ranking, and none of them is second.
    $players = array_values(array_filter($everyone, fn($p) => $p[$sort] > 0));
}
// A number column's classes: the column the list is sorted by is marked (and kept on phones); the
// optional ones leave narrow screens.
$col = fn(string $key, bool $optional = false) => 'r' . ($key === $sort ? ' sorted' : ($optional ? ' opt' : ''));
// The game's abbreviations in the header, with what they stand for (also in the line under the table).
$abbr = fn(string $term, string $key) => '<abbr title="' . h(t($key)) . '">' . $term . '</abbr>';

// The value of the chosen order, as the podium shows it under the name.
$value = function (array $p) use ($sort, $month): string {
    return number_format($month ? $p['score'] : $p[$sort]);
};
// The first three stand on the podium, however few there are, and the table goes on from the fourth.
// The signed-in account's own player, when linked: their place is marked wherever it shows.
$me = site_me();
$podium = array_slice($players, 0, 3);
$rest = array_slice($players, 3);
$first_rank = 4;

page_header(t('rank.title'), 'ranking');
?>
  <?php // This month's line says when it starts anew, in the server's own time. ?>
  <?= masthead('RANKINGS', $month ? t('rank.line.month', ['when' => h(month_moment(odq_month_start(-1)))]) : t('rank.line.' . $sort)) ?>
  <?php // Nothing to put in order: no tabs above the message. ?>
  <?php if ($everyone): ?>
    <p class="tabs">
      <?php foreach ($sorts as $key => $label): ?>
        <a href="?sort=<?= $key ?>"<?= $key === $sort ? ' class="on" aria-current="true"' : '' ?>><?= $label ?></a>
      <?php endforeach; ?>
    </p>
  <?php endif; ?>
  <?php if ($podium): ?>
    <div class="podium" style="--places:<?= count($podium) ?>">
      <?php foreach ($podium as $i => $p): ?>
        <?php // The whole box leads to the player (the name's link stretches over it); a LIVE mark leads to their broadcast. ?>
        <div class="pod <?= ['first', 'second', 'third'][$i] ?><?= (int)$p['id'] === $me ? ' me' : '' ?>">
          <span class="pod-place place-<?= $i + 1 ?>"><?= $i + 1 ?></span>
          <span class="pod-who"><a class="pod-name" href="player.php?id=<?= (int)$p['id'] ?>"><?= h($p['name']) ?></a><?= live_mark($db, (int)$p['id']) ?></span>
          <span class="pod-score"><?= $value($p) ?></span>
          <span class="pod-sub"><?= $sorts[$sort] ?></span>
        </div>
      <?php endforeach; ?>
    </div>
  <?php endif; ?>
  <?php // With everyone on the podium, nothing is left for a box under it. ?>
  <?php if (!$db || !$players || $rest): ?>
  <section class="card">
    <?php if (!$db): ?>
      <?= no_rankings() ?>
    <?php elseif (!$everyone): ?>
      <div class="empty"><p><?= t('rank.empty') ?></p><div class="btn-line"><a class="btn btn-primary" href="/opendmtq/download.php"><?= t('nav.download') ?></a></div></div>
    <?php elseif (!$players): ?>
      <?php // What nobody has yet, by its name. ?>
      <p class="empty"><?= t(isset(STRINGS['en']['rank.none_' . $sort]) ? 'rank.none_' . $sort : 'rank.none') ?></p>
    <?php elseif ($month): ?>
      <?php // This month: the score and the charts played this month, nothing of every month. ?>
      <div class="table-scroll">
      <table class="board">
        <thead><tr><th class="rank">#</th><th class="name"><?= t('th.player') ?></th><th class="r sorted"><?= t('th.month') ?></th><th class="r"><?= t('th.charts') ?></th></tr></thead>
        <tbody>
        <?php foreach ($rest as $i => $p): ?>
          <tr<?= (int)$p['id'] === $me ? ' class="me"' : '' ?>>
            <td class="rank"><?= $first_rank + $i ?></td>
            <td class="name"><a href="player.php?id=<?= (int)$p['id'] ?>"><?= h($p['name']) ?></a><?= live_mark($db, (int)$p['id']) ?></td>
            <td class="r sorted"><?= number_format($p['score']) ?></td>
            <td class="r"><?= (int)$p['charts'] ?></td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
      </div>
    <?php else: ?>
      <div class="table-scroll">
      <table class="board">
        <thead><tr><th class="rank">#</th><th class="name"><?= t('th.player') ?></th><th class="<?= $col('total') ?>"><?= t('th.total') ?></th><th class="<?= $col('charts', true) ?>"><?= t('th.charts') ?></th><th class="<?= $col('s_count', true) ?>"><?= $abbr('S', 'abbr.s') ?></th><th class="r opt"><?= $abbr('AC', 'abbr.ac') ?></th><th class="<?= $col('perfect', true) ?>"><?= $abbr('PP', 'abbr.pp') ?></th><th class="r opt"><?= t('th.avg') ?></th></tr></thead>
        <tbody>
        <?php foreach ($rest as $i => $p): ?>
          <tr<?= (int)$p['id'] === $me ? ' class="me"' : '' ?>>
            <td class="rank"><?= $first_rank + $i ?></td>
            <td class="name"><a href="player.php?id=<?= (int)$p['id'] ?>"><?= h($p['name']) ?></a><?= live_mark($db, (int)$p['id']) ?></td>
            <td class="<?= $col('total') ?>"><?= number_format($p['total']) ?></td>
            <td class="<?= $col('charts', true) ?>"><?= (int)$p['charts'] ?></td>
            <td class="<?= $col('s_count', true) ?>"><?= (int)$p['s_count'] ?></td>
            <td class="r opt"><?= (int)$p['ac'] ?></td>
            <td class="<?= $col('perfect', true) ?>"><?= (int)$p['perfect'] ?></td>
            <td class="r opt"><?= accuracy($p['avg_judgement']) ?></td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
      </div>
      <?php // These columns leave narrow screens (.opt), and their legend with them. ?>
      <p class="meta legend opt"><?= t('rank.legend') ?></p>
    <?php endif; ?>
  </section>
  <?php endif; ?>
  <?php // The hall of fame: each month before, newest first, with its first three. ?>
  <?php if ($past_months): ?>
  <section class="card">
    <h2><?= t('rank.past') ?></h2>
    <div class="past-months">
      <?php foreach ($past_months as [$name, $top]): ?>
        <div class="past-month">
          <h3><?= h($name) ?></h3>
          <ol class="past-top">
            <?php foreach ($top as $i => $p): ?>
              <li<?= (int)$p['id'] === $me ? ' class="me"' : '' ?>><span class="past-place place-<?= $i + 1 ?>"><?= $i + 1 ?></span><a href="player.php?id=<?= (int)$p['id'] ?>"><?= h($p['name']) ?></a><b><?= number_format($p['score']) ?></b></li>
            <?php endforeach; ?>
          </ol>
        </div>
      <?php endforeach; ?>
    </div>
  </section>
  <?php endif; ?>
<?php page_footer();
