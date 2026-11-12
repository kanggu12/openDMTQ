<?php
/* Home, for those signed in: what the site is for first, the app (one press away) and the broadcasts (who is on air, the
   newest recordings) while the server has them on, then who leads and the newest records. */
require __DIR__ . '/lib.php';
// A stranger goes to the sign-in page; the page's own look at who is on answers them nothing.
require_sign_in(isset($_GET['live']));

$apk = apk_manifest();
$db = db();
// The page's own look at who is on, every so often: nothing else is worked out for it.
if (isset($_GET['live'])) {
    header('Content-Type: application/json');
    header('Cache-Control: no-store');
    // Broadcasts turned off since the page came: it says so, and the page reloads without them (thumbs.js).
    if (!live_enabled()) {
        header('X-Live: off');
    }
    echo json_encode(live_cards($db), JSON_UNESCAPED_UNICODE);
    exit;
}
// The front page's list: names and totals of the first few, which costs far less than every figure of
// everyone (players()).
$ranked = $db ? top_players($db, 8) : [];
$charts = charts();
$songs = songs_by_id();
// The builder draws the QR code next to the app; older builds have none, and one for another address is no use.
$qr = $apk && $apk['host'] === public_host() && is_file(APK_DIR . '/download-qr.svg');
// The app in one press from here when there is one for this address that this browser can take; otherwise the button
// leads to the download page, which says why not (worked out as there).
$stale = $apk && $apk['host'] !== public_host();
$ready = $apk && !$stale && !in_app_browser();
// No app players can get: the line under the buttons says why, as the download page does (being made, given up on, or
// nothing making one).
$failed = (!$apk || $stale) && build_failed();
$building = (!$apk || $stale) && build_state() === 'building';
// PlayLog.user_id is the player's guid: one name per player, however many phones (PLAYER_ROWS). As many as go well beside
// the list of players, which is short on a server with few.
$records = ($db && has_playlog($db)) ? rows($db,
    "SELECT l.*, m.nickname, m.guid AS mid,
            (SELECT MAX(p.score) FROM PlayLog p WHERE p.user_id = l.user_id AND p.pattern_id = l.pattern_id
              AND (p.played_at < l.played_at OR (p.played_at = l.played_at AND p.id < l.id))) AS before
       FROM PlayLog l JOIN (" . PLAYER_ROWS . ") m ON m.guid = l.user_id
      WHERE l.is_record = 1 ORDER BY l.played_at DESC, l.id DESC LIMIT :shown",
    [':check' => CHECK_UDID, ':shown' => max(3, min(6, (int)round(count($ranked) * 0.8)))]) : [];

// Players on air now: their own section above everything else, only then.
$live = live_cards($db);
// The newest recordings, a row of them under it: those four alone are read.
$past = live_past($db, 4);
// Broadcasts off for the server: nothing of them on the page, neither the way to watch nor the box for them.
$casting = live_enabled();

// The front page's stage: the wall of jackets under the game's playfield, and over it the name and the two things the
// site is for, getting the app and watching the others play. The notes stand where the timeline crosses them (--x, part of the way across).
ob_start();
?>
<section class="stage" id="install" aria-label="OpenDMTQ">
  <div class="wall" aria-hidden="true"><?= jacket_wall(32) ?></div>
  <?php // Clear of the version beside the wordmark. ?>
  <?php foreach ([[0.63, '46%'], [0.71, '22%'], [0.8, '60%'], [0.89, '34%'], [0.95, '72%']] as [$x, $y]): ?>
    <i class="note-on" aria-hidden="true" style="--x:<?= $x ?>;--y:<?= $y ?>"></i>
  <?php endforeach; ?>
  <div class="sweep" aria-hidden="true"></div>
  <div class="wrap stage-in">
    <div class="stage-copy">
      <div class="stage-mark">
        <div class="logo" aria-hidden="true"><span class="o">OPEN</span><span class="m">DMT<b>Q</b></span></div>
        <?= server_version_block() ?>
      </div>
      <h2><?= t('home.title') ?></h2>
      <p class="lead get-app"<?= hidden_on_ios() ?>><?= t('home.lead') ?></p>
      <?php // The app in one press when there is one to give, its size and date under it and the steps a press away.
            // Watching works on any phone or computer: lit, with the count, while someone is on air (thumbs.js keeps it so). ?>
      <div class="stage-acts">
        <a class="button get get-app" href="<?= $ready ? '/apk' : 'download.php' ?>"<?= hidden_on_ios() ?>><?= t('dl.button') ?></a>
        <?php // Live while someone is on air, the broadcasts otherwise; nothing at all with neither (the box under it says so),
              // nor with broadcasts off for the server. ?>
        <?php if ($casting): ?>
        <a class="watch-live<?= $live ? ' on' : '' ?>" id="watch-live" href="live.php" data-past="<?= $past ? '1' : '0' ?>"<?= $live || $past ? '' : ' hidden' ?>><i aria-hidden="true"></i><span class="when-on"><?= t('home.watch') ?></span><span class="when-off"><?= t('home.broadcasts') ?></span><span class="watch-count" id="watch-count"<?= $live ? '' : ' hidden' ?>><?= count($live) ?></span></a>
        <?php endif; ?>
      </div>
      <?php if ($ready): ?>
        <p class="meta stage-meta get-app"<?= hidden_on_ios() ?>><?= t('dl.meta', ['size' => number_format($apk['size'] / 1048576, 1), 'date' => substr($apk['built_at'], 0, 10)]) ?> · <a href="download.php"><?= t('home.howto') ?></a></p>
      <?php elseif (!$apk || $stale): ?>
        <p class="meta stage-meta get-app"<?= hidden_on_ios() ?>><?= t($failed ? 'home.app_failed' : ($building ? 'home.app_wait' : 'build.none')) ?></p>
      <?php endif; ?>
      <?= android_only() ?>
    </div>
    <?php if ($qr): ?>
      <figure class="qr get-app"<?= hidden_on_ios() ?>>
        <img src="qr.php" alt="<?= h(tp('qr.alt')) ?>" width="132" height="132" loading="lazy">
        <figcaption><?= t('qr.caption') ?></figcaption>
      </figure>
    <?php endif; ?>
  </div>
</section>
<?php
$stage = ob_get_clean();
page_header('OpenDMTQ', 'home', '', $stage);
?>
  <?php // Only while the server has broadcasts on. ?>
  <?php if ($casting): ?>
  <?php // The broadcasts, in one box under one heading. Who is on air now comes first, only then: a picture of each,
        // leading to their broadcast, the pictures taken from the stream itself for those signed in to watch (thumbs.js),
        // the others seeing the same cards with no picture. Then the newest recordings to watch again. Before there are
        // any recordings, what shows here; that part goes while someone is on air, the box having them then. ?>
  <section class="card broadcasts" aria-labelledby="casts-title">
    <h2 id="casts-title"><span><span class="on-air-dot" id="on-air-dot" aria-hidden="true"<?= $live ? '' : ' hidden' ?>></span><?= t('home.casts') ?></span><?php if ($past): ?> <a class="more" href="live.php"><?= t('live.more') ?></a><?php endif; ?></h2>
    <div class="thumbs" id="live"<?= $live ? '' : ' hidden' ?>>
      <?php foreach ($live as $c): ?>
        <a class="thumb" data-id="<?= $c['id'] ?>" href="/opendmtq/live.php?p=<?= $c['id'] ?>"><span class="thumb-pic"><span class="live-pill"><i></i>LIVE</span></span><b class="thumb-who"><?= h($c['name']) ?></b><span class="thumb-what"><?= h($c['doing']) ?></span></a>
      <?php endforeach; ?>
    </div>
    <?php if ($past): ?>
      <ul class="past-list" id="replays">
        <?php foreach ($past as $x): ?><?= past_card($x) ?><?php endforeach; ?>
      </ul>
    <?php else: ?>
      <div class="live-empty off-air" id="replays" data-off-air-only="1"<?= $live ? ' hidden' : '' ?>>
        <span class="off-air-word" aria-hidden="true">OFF AIR</span>
        <p class="live-empty-head"><?= t('live.none') ?></p>
        <p class="meta"><?= t('home.live_none') ?></p>
      </div>
    <?php endif; ?>
  </section>
  <script src="<?= asset_url('thumbs.js') ?>"></script>
  <script>liveThumbs.home(<?= json_encode($live, JSON_UNESCAPED_UNICODE | JSON_HEX_TAG) ?>, <?= dl_signed_in() ? 'true' : 'false' ?>, <?= json_encode(['count' => tp('live.count', ['n' => '{n}']), 'nav' => tp('live.nav')], JSON_UNESCAPED_UNICODE | JSON_HEX_TAG) ?>);</script>
  <?php endif; ?>

  <?php // The rest of what goes on: who leads, and the newest records. One box with two lists, each as long as it is. ?>
  <section class="card home-lists">
    <div class="home-list">
      <h2><?= t('top.title') ?><?php if ($ranked): ?> <a class="more" href="ranking.php"><?= t('top.more') ?></a><?php endif; ?></h2>
      <?php if (!$db): ?>
        <?= no_rankings() ?>
      <?php elseif (!$ranked): ?>
        <p class="empty"><?= t('top.empty') ?></p>
      <?php else: ?>
        <ul class="feed ranks">
        <?php // The signed-in account's own player, when linked, marked in the list. ?>
        <?php $me = site_me(); foreach (array_slice($ranked, 0, 8) as $i => $p): ?>
          <li<?= (int)$p['id'] === $me ? ' class="me"' : '' ?>>
            <b class="feed-rank<?= $i < 3 ? ' place-' . ($i + 1) : '' ?>"><?= $i + 1 ?></b>
            <span class="who"><a href="player.php?id=<?= (int)$p['id'] ?>"><?= h($p['name']) ?></a></span>
            <span class="feed-score"><?= number_format($p['total']) ?></span>
          </li>
        <?php endforeach; ?>
        </ul>
      <?php endif; ?>
    </div>
    <div class="home-list" id="records">
      <h2><?= t('rec.title') ?></h2>
      <?php if (!$db): ?>
        <?= no_rankings() ?>
      <?php elseif (!$records): ?>
        <p class="empty"><?= t('rec.empty') ?></p>
      <?php else: ?>
        <ul class="feed">
        <?php foreach ($records as $r):
            [$sid, $line, $diff, $sig] = $charts[(int)$r['pattern_id']] ?? [0, 0, 0, 0];
            $song = $songs[$sid] ?? null; ?>
          <li>
            <?= row_jacket($song, 'feed-jacket') ?>
            <span class="feed-text">
              <span class="who"><a href="player.php?id=<?= (int)$r['mid'] ?>"><?= h(player_name(['nickname' => $r['nickname'], 'id' => $r['mid']])) ?></a></span>
              <span class="what"><?php if ($song): ?><a href="song.php?id=<?= $sid ?>&amp;chart=<?= (int)$r['pattern_id'] ?>"><?= h(song_title($song)) ?></a><span class="what-chart sig<?= (int)$sig ?>"><?= h(chart_label($line, $diff, $sig)) ?></span><?php else: ?><?= t('player.chart', ['id' => (int)$r['pattern_id']]) ?><?php endif; ?></span>
            </span>
            <?php // The grade before the score; under it, how far over their best before (nothing for a first clear). ?>
            <span class="feed-end"><span class="feed-score"><span class="grade g<?= h($r['grade']) ?> feed-grade"><?= h($r['grade']) ?></span><?= number_format($r['score']) ?></span><?php if ($r['before'] !== null && (int)$r['score'] > (int)$r['before']): ?><span class="feed-gain" title="<?= h(tp('rec.up', ['before' => number_format($r['before'])])) ?>">+<?= number_format($r['score'] - $r['before']) ?></span><?php endif; ?><span class="feed-when"><?= h(ago((int)$r['played_at'])) ?></span></span>
          </li>
        <?php endforeach; ?>
        </ul>
      <?php endif; ?>
    </div>
  </section>
<?php page_footer();
