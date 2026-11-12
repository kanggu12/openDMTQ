<?php
/* One song: every chart with its leaderboard. */
require __DIR__ . '/lib.php';
// For those signed in only (a stranger goes to the sign-in page and comes back here).
require_sign_in();

$id = (int)($_GET['id'] ?? 0);
$song = songs_by_id()[$id] ?? null;
if (!$song) {
    http_response_code(404);
}
$db = db();
$patterns = $song['song_patterns'] ?? [];
// Lines first, then difficulty: 2L Easy, 2L Normal, ... like the game's song select.
usort($patterns, fn($a, $b) => [$a['line'], $a['signature'], $a['difficulty']] <=> [$b['line'], $b['signature'], $b['difficulty']]);
$ids = array_map(fn($p) => (int)$p['pattern_id'], $patterns);
// Records per chart, for the tabs and the chart shown first. Players by guid like the rest of the
// portal: Play's user_id is the guid, and PLAYER_ROWS already leaves the check account out.
$counts = [];
if ($db && $ids) {
    foreach (rows($db, "SELECT p.pattern_id, COUNT(*) AS n FROM Play p JOIN (" . PLAYER_ROWS . ") m ON m.guid = p.user_id
                         WHERE p.pattern_id IN (" . implode(',', $ids) . ")
                         GROUP BY p.pattern_id", [':check' => CHECK_UDID]) as $r) {
        $counts[(int)$r['pattern_id']] = (int)$r['n'];
    }
}
$pick = (int)($_GET['chart'] ?? 0);
// Only this song's charts. Without one (or with another song's), the first chart anybody has a
// record on, else the first chart.
if (!in_array($pick, $ids, true)) {
    $pick = array_values(array_filter($ids, fn($i) => !empty($counts[$i])))[0] ?? ($ids[0] ?? 0);
}
// The board's player number is the guid, as player.php takes it.
$board = ($db && $song) ? rows($db,
    "SELECT p.*, m.nickname, m.guid AS mid FROM Play p JOIN (" . PLAYER_ROWS . ") m ON m.guid = p.user_id
      WHERE p.pattern_id = :pid ORDER BY p.score DESC, p.judgement DESC, p.user_id ASC LIMIT 100",
    [':pid' => $pick, ':check' => CHECK_UDID]) : [];
// The charts by LINE mode, in the order above: one row of tabs per mode.
$by_line = [];
foreach ($patterns as $p) {
    $by_line[(int)$p['line']][] = $p;
}

page_header($song ? song_title($song) : t('song.notfound'), 'songs');
if (!$song): ?>
  <?= lost(t('song.notfound'), t('nf.text'), [['/opendmtq/songs.php', t('go.songs')]]) ?>
<?php page_footer(); exit; endif; ?>
  <section class="songhead">
    <img class="songhead-back" src="<?= h(jacket($song)) ?>" alt=""<?= JACKET_ONERROR ?>>
    <img class="songhead-pic" src="<?= h(jacket($song)) ?>" alt=""<?= JACKET_ONERROR ?>>
    <div class="songhead-text">
      <h2><?= h(song_title($song)) ?></h2>
      <dl>
        <div><dt><?= t('song.artist') ?></dt><dd><?= h($song['artist_name']) ?></dd></div>
        <?php if (trim((string)$song['genre']) !== ''): ?><div><dt><?= t('song.genre') ?></dt><dd><?= h($song['genre']) ?></dd></div><?php endif; ?>
        <?php if ($song['visualized_by']): ?><div><dt>BGA</dt><dd><?= h($song['visualized_by']) ?></dd></div><?php endif; ?>
      </dl>
    </div>
  </section>
  <section class="card">
    <?php // One row per LINE mode, its Easy, Normal, Hard and Expert chart each in its own column
          // (style.css .charts .sigN), so the difficulties line up from row to row at every width. ?>
    <div class="tabs charts">
      <?php foreach ($by_line as $line => $list): ?>
        <div class="chart-row">
          <span class="chart-line"><?= (int)$line - 1 ?>LINE</span>
          <?php foreach ($list as $p):
              $pid = (int)$p['pattern_id'];
              // Each chart's record count after its name; none for a chart nobody played.
              $n = $counts[$pid] ?? 0;
              $records = t('records', ['n' => $n]);
              // What a screen reader says: the whole name, as the other pages write it.
              $label = chart_label($p['line'], $p['difficulty'], $p['signature']); ?>
            <a class="sig<?= (int)$p['signature'] ?><?= $pid === $pick ? ' on' : '' ?>" href="?id=<?= $id ?>&amp;chart=<?= $pid ?>" aria-label="<?= h($label) ?><?= $n ? ', ' . $records : '' ?>"<?= $n ? ' title="' . $records . '"' : '' ?>><?= difficulty_name((int)$p['signature']) ?> <?= (int)$p['difficulty'] ?><?= $n ? '<span class="n">' . $records . '</span>' : '' ?></a>
          <?php endforeach; ?>
        </div>
      <?php endforeach; ?>
    </div>
    <?php if (!$db): ?>
      <?= no_rankings() ?>
    <?php elseif (!$board): ?>
      <p class="empty"><?= t('song.empty') ?></p>
    <?php else: ?>
      <div class="table-scroll">
      <table class="board">
        <thead><tr><th class="rank">#</th><th class="name"><?= t('th.player') ?></th><th class="r"><?= t('th.score') ?></th><th><?= t('th.grade') ?></th><th class="r acc"><?= t('th.accuracy') ?></th></tr></thead>
        <tbody>
        <?php foreach ($board as $i => $r): ?>
          <tr>
            <td class="rank"><?= $i + 1 ?></td>
            <td class="name"><a href="player.php?id=<?= (int)$r['mid'] ?>"><?= h(player_name(['nickname' => $r['nickname'], 'id' => $r['mid']])) ?></a></td>
            <?php // A best a keyboard play set has the keyboard's mark before its score. ?>
            <td class="r"><?= keys_mark($r) ?><?= number_format($r['score']) ?></td>
            <td><?= grade_cell($r) ?></td>
            <td class="r acc"><?= accuracy($r['judgement']) ?></td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
      </div>
    <?php endif; ?>
  </section>
<?php page_footer();
