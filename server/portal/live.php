<?php
/*
 * The live page, behind the same sign-in as the app download: who is playing live now, and one of
 * them on video (hls.js over the playlist from live-media.php), then past broadcasts. ?p=<guid> links to
 * one player's stream (the page then waits for them if they are off air), ?r=<guid>-<id> to a recording;
 * ?list=1 answers the page's own polling as JSON: who is on and the sign of the recordings' list, and with &past=1 that
 * list itself.
 */
require __DIR__ . '/lib.php';

// Not signed in: the page comes back after signing in (the list answers nothing).
if (!dl_signed_in()) {
    if (isset($_GET['list'])) {
        http_response_code(403);
        exit;
    }
    // Back to what was linked; only these two shapes, built anew.
    $pick = (int)($_GET['p'] ?? 0);
    $rec = preg_match('/^\d{1,12}-\d{1,12}$/', (string)($_GET['r'] ?? '')) ? $_GET['r'] : '';
    $back = $rec !== '' ? "?r=$rec" : ($pick ? "?p=$pick" : '');
    header('Location: /opendmtq/login.php?next=' . rawurlencode('/opendmtq/live.php' . $back));
    exit;
}

// Broadcasts off for the whole server: the page says so in the site's own way, with the way home. Its own look at who is
// on says it too, and the page then loads again to show this.
if (!live_enabled()) {
    if (isset($_GET['list'])) {
        header('Content-Type: application/json');
        header('Cache-Control: no-store');
        echo json_encode(['live' => [], 'off' => true]);
        exit;
    }
    // No section: LIVE is not in the menu while broadcasts are off. The same box as for a live page with nobody on air,
    // with what is off and the way home.
    page_header(t('live.off_title'));
    echo '<section class="card live-empty off-air live-off"><span class="off-air-word" aria-hidden="true">OFF AIR</span>'
        . '<p class="live-empty-head">' . t('live.off_title') . '</p><p class="meta">' . t('live.off_text') . '</p>'
        . way_out([['/opendmtq/', t('go.home')]]) . '</section>';
    page_footer();
    exit;
}

$db = db();
$cards = live_cards($db);
if (isset($_GET['list'])) {
    header('Content-Type: application/json');
    header('Cache-Control: no-store');
    // Who is on, every few seconds, for each viewer, with the sign of the recordings' list (live_past_rev(), from their
    // folders alone); the list itself, a file each to read and 60 KB compressed at 300, only when the page asks, which it
    // does when that sign changed. Then the sign of the list sent, so that the page holds the two together.
    if (isset($_GET['past'])) {
        $past = live_past($db);
        echo json_encode(['live' => $cards, 'past' => $past, 'past_rev' => live_past_rev_of(array_column($past, 'key'))], JSON_UNESCAPED_UNICODE);
    } else {
        echo json_encode(['live' => $cards, 'past_rev' => live_past_rev($db)], JSON_UNESCAPED_UNICODE);
    }
    exit;
}
$past = live_past($db);
// A recording asked for by name, a player asked for by name (a real one: the page waits for them while
// they are off air), else the first one on.
$replay = preg_match('/^\d{1,12}-\d{1,12}$/', (string)($_GET['r'] ?? '')) ? (string)$_GET['r'] : '';
$want = (int)($_GET['p'] ?? 0);
$wanted = '';
if ($want > 0 && $db) {
    foreach (rows($db, 'SELECT nickname FROM (' . PLAYER_ROWS . ') WHERE guid = :id', [':check' => CHECK_UDID, ':id' => $want]) as $m) {
        $wanted = player_name(['nickname' => $m['nickname'], 'id' => $want]);
    }
}
$pinned = $wanted !== '';
$ids = array_column($cards, 'id');
$current = $pinned ? $want : ($ids[0] ?? 0);

// With nobody on air, the box says when someone last was, and how the last two weeks went: a cell a day, stronger with
// more minutes on air, from the recordings that are kept.
$air_days = [];
for ($back = 13; $back >= 0; $back--) {
    $air_days[date('Y-m-d', strtotime("-$back day"))] = ['min' => 0, 'n' => 0, 'who' => []];
}
foreach ($past as $x) {
    $day = date('Y-m-d', (int)$x['started']);
    if (isset($air_days[$day])) {
        $air_days[$day]['min'] += intdiv((int)$x['seconds'], 60);
        $air_days[$day]['n']++;
        $air_days[$day]['who'][$x['name']] = true;
    }
}
$air_most = max(array_column($air_days, 'min')) ?: 0;

// A recording that is there: the page starts out as it will be, with the box for it in place, and not with "nobody is
// on" until the script has come over a slow connection.
$replaying = in_array($replay, array_column($past, 'key'), true);
$player = $cards || $replaying;
// A recording is not a live broadcast: the tab and the heading say which it is (the page keeps them up to date).
page_header($replay !== '' ? t('live.replay') : t('live.title'), 'live');
?>
  <?php // The section's name, in the player's terms: a recording is not a live broadcast. The page keeps it up to date. ?>
  <?php // The line beside the name only where there is something to watch: not over a recording, nor over an empty page. ?>
  <div id="mast"<?= $replay !== '' ? ' class="is-replay"' : '' ?>><?= masthead($replay !== '' ? 'REPLAY' : 'LIVE', $replay === '' && ($cards || $past) ? t('live.line') : '') ?></div>
  <?php // The watch page: the picture with what belongs to it, and beside it (under it on a phone) who else is on and the
        // past broadcasts. With nothing on screen the list takes the whole width. ?>
  <div class="watch<?= $player ? ' has-player' : '' ?>" id="watch">
    <section class="live-page">
      <div id="live-none" class="card live-empty off-air"<?= $player ? ' hidden' : '' ?>>
        <span class="off-air-word" aria-hidden="true">OFF AIR</span>
        <p class="live-empty-head"><?= t('live.none') ?></p>
        <?php if ($past): $last = $past[0]; ?>
          <p class="last-air"><?= t('live.last', ['name' => h($last['name']), 'ago' => h($last['ago']), 'min' => max(1, (int)round($last['seconds'] / 60))]) ?> <a href="?r=<?= h($last['key']) ?>"><?= t('live.watch_again') ?></a></p>
          <div class="air-days" role="img" aria-label="<?= h(strip_tags(t('live.days'))) ?>">
            <?php foreach ($air_days as $day => $d):
                $step = !$d['min'] || !$air_most ? ($d['n'] ? 1 : 0) : 1 + min(4, intdiv(4 * $d['min'], $air_most));
                $words = $d['n'] ? t('live.day_tip', ['day' => substr($day, 5), 'n' => $d['n'], 'min' => $d['min'], 'who' => implode(', ', array_keys($d['who']))])
                                 : t('live.day_none', ['day' => substr($day, 5)]); ?>
              <i class="c<?= $step ?>" data-tip="<?= h(strip_tags($words)) ?>"></i>
            <?php endforeach; ?>
          </div>
          <div class="air-days-ends" aria-hidden="true"><span><?= t('live.days_ago') ?></span><span><?= t('live.today') ?></span></div>
        <?php endif; ?>
        <p class="meta"><?= t('live.when') ?></p>
        <p class="meta"><?= t('live.phones') ?></p>
      </div>
      <?php if ($pinned): ?>
        <p class="card live-empty" id="live-wait" hidden><?= t('live.waiting', ['name' => $wanted]) ?></p>
      <?php endif; ?>
      <p class="warn" id="live-msg" role="status" hidden></p>
      <?php // A broadcast that ended while it was on screen: who, and where it can be seen again. ?>
      <div class="card live-empty" id="live-ended" hidden>
        <p class="live-empty-head" id="ended-word"></p>
        <p class="meta"><?= t('live.ended_hint') ?></p>
      </div>
      <?php // One player for both, with the site's own controls: a broadcast has no timeline, a recording has (see liveMode()). ?>
      <div class="live-stage<?= $player ? ' waiting' : '' ?>" id="live-stage"<?= $player ? '' : ' hidden' ?>>
        <video class="live-video" id="live-video" playsinline<?= $player ? '' : ' hidden' ?>></video>
        <?php // On the picture: the mark that stays (LIVE, or REPLAY for a recording) and how long a broadcast has run. Who it
              // is and what they play are right under the picture; they come onto it only in full screen, where nothing is
              // under it, and step back with the controls so as not to sit on the game. ?>
        <div class="live-top" id="live-top" hidden>
          <span class="live-pill" id="top-pill"><i></i><span id="pill-word">LIVE</span></span>
          <span class="live-clock" id="live-clock" title="<?= h(t('live.since')) ?>"></span>
          <button type="button" class="go-live" id="go-live" hidden><?= t('live.go_live') ?></button>
          <span class="live-title"><b id="top-who"></b><span id="top-what"></span></span>
        </div>
        <?php // Connection details, on the picture when asked for: what to read out when something plays badly. ?>
        <dl class="live-stats" id="live-stats" hidden></dl>
        <?php // A short word on the picture: where a double tap went, what the speed is now. ?>
        <div class="live-flash" id="live-flash" aria-hidden="true"></div>
        <?php // The network is gone and what was in hand has played: the picture says so, and the player goes on asking. ?>
        <div class="live-lost" id="live-lost" role="status" hidden><?= t('live.reconnecting') ?></div>
        <?php // Where this viewer left off, for a few seconds, with the way back to the start. ?>
        <div class="live-resume" id="live-resume" role="status" hidden><span id="resume-word"></span> <button type="button" class="link-btn" id="resume-restart"><?= t('live.restart') ?></button></div>
        <?php // A recording that came to its end: what next. ?>
        <div class="live-end" id="live-end" hidden>
          <button type="button" class="btn btn-primary" id="end-again"><?= t('live.again') ?></button>
          <a class="btn" id="end-next" hidden><?= t('live.next') ?></a>
        </div>
        <div class="live-ctl" id="live-ctl" hidden>
          <div class="ctl-track" id="ctl-track" hidden>
            <input type="range" class="ctl-seek" id="ctl-seek" min="0" max="1000" step="1" value="0" aria-label="<?= h(t('live.ctl_seek')) ?>">
            <div class="ctl-marks" id="ctl-marks" aria-hidden="true"></div>
            <span class="ctl-bubble" id="ctl-bubble" hidden><img class="bubble-pic" id="bubble-pic" alt="" width="36" height="36" hidden><span class="bubble-text" id="bubble-text"></span></span>
          </div>
          <div class="ctl-row">
            <button type="button" id="ctl-play"></button>
            <button type="button" id="ctl-back" class="vod-only" hidden></button>
            <button type="button" id="ctl-fwd" class="vod-only" hidden></button>
            <button type="button" id="ctl-mute"></button>
            <input type="range" id="ctl-vol" min="0" max="1" step="0.05" value="1" aria-label="<?= h(t('live.ctl_volume')) ?>">
            <span class="ctl-time" id="ctl-time" hidden></span>
            <span class="ctl-gap"></span>
            <button type="button" id="ctl-rate" class="vod-only ctl-word" aria-label="<?= h(t('live.ctl_speed')) ?>" title="<?= h(t('live.ctl_speed')) ?>" hidden>1×</button>
            <button type="button" id="ctl-stats"></button>
            <button type="button" id="ctl-pip" hidden></button>
            <button type="button" id="ctl-wide"></button>
            <button type="button" id="ctl-full"></button>
          </div>
        </div>
      </div>
      <p class="meta" id="live-muted" hidden><?= t('live.muted') ?></p>
      <?php // Who this is: under the picture, leading to their profile. ?>
      <div class="live-info" id="live-info" hidden>
        <div class="live-facts"><a class="live-name" id="info-name"></a><span class="live-doing" id="info-doing"></span></div>
        <div class="live-acts">
          <button type="button" class="btn btn-sm" id="info-share" data-done="<?= h(t('live.copied')) ?>"><?= t('live.share') ?></button>
          <a class="btn btn-sm" id="info-profile"><?= t('live.profile_btn') ?></a>
        </div>
      </div>
      <?php // The songs of a recording, each a jump to where it begins. ?>
      <div class="card live-chapters" id="live-chapters" hidden>
        <h3><?= t('live.songs') ?></h3>
        <ol class="chapters" id="chapter-list"></ol>
      </div>
    </section>
    <aside class="watch-side">
      <section class="card" id="live-others" hidden>
        <h2><span><span class="on-air-dot" aria-hidden="true"></span><?= t('live.others_side') ?></span></h2>
        <div class="thumbs" id="live-list"></div>
      </section>
      <section class="card" id="live-past"<?= $past ? '' : ' hidden' ?>>
        <h2><?= t('live.past') ?> <span class="meta-inline" id="past-count"><?= count($past) ?></span></h2>
        <div class="past-tools">
          <input class="input" id="past-search" type="search" placeholder="<?= h(t('live.search')) ?>" aria-label="<?= h(t('live.search_label')) ?>">
          <select class="input" id="past-who" aria-label="<?= h(t('live.player_label')) ?>"><option value=""><?= t('live.all_players') ?></option></select>
        </div>
        <p class="empty" id="past-none" role="status" hidden><?= t('live.nomatch') ?></p>
        <?php // Here from the start, so that the box is not empty until the script has come. The script makes the same. ?>
        <ul class="past-list" id="past-list">
          <?php foreach (array_slice($past, 0, 24) as $x): $on = $x['key'] === $replay; ?>
            <li><a class="past<?= $on ? ' on' : '' ?>" href="?r=<?= h($x['key']) ?>" data-key="<?= h($x['key']) ?>"><span class="past-pic"><?php if ($x['pic']): ?><img src="<?= h($x['pic']) ?>" alt="" loading="lazy" decoding="async"<?= JACKET_ONERROR ?>><?php endif; ?><span class="past-len"><?= h($x['length']) ?></span></span><span class="past-text"><b class="who"><?= h($x['name']) ?></b><span class="doing" title="<?= h($x['find']) ?>"><?= h($x['doing']) ?></span><span class="past-when" title="<?= h($x['when']) ?>"><?= h($x['ago']) ?></span></span></a></li>
          <?php endforeach; ?>
        </ul>
        <?php // A screenful at a time: a month of broadcasts is a long list. ?>
        <div class="btn-line past-more" id="past-more"<?= count($past) > 24 ? '' : ' hidden' ?>><button type="button" class="btn btn-sm"><?= t('live.more_past') ?></button></div>
      </section>
    </aside>
  </div>
  <?php // hls.js at an exact version, served from here: a server on a local network without internet
        // must play video too. Copied as it was published (see hls/LICENSE, docs/architecture.md). ?>
  <script src="/opendmtq/hls/hls-1.5.17.min.js"></script>
  <script src="<?= asset_url('thumbs.js') ?>"></script>
  <script src="<?= asset_url('tips.js') ?>" defer></script>
  <?php // What the server knows at page load (with the sign of its list of recordings, which the page's looks compare),
        // and the page's words, for the page's script (live.js): data, never run. JSON_HEX_TAG keeps a name with
        // </script> in it from ending the block. ?>
  <script type="application/json" id="live-data"><?= json_encode(['cards' => $cards, 'past' => $past, 'past_rev' => live_past_rev_of(array_column($past, 'key')), 'current' => $current, 'pinned' => $pinned, 'replay' => $replay,
      'words' => ['title' => t('live.title'), 'replay' => t('live.replay'), 'ended' => t('live.ended'), 'ended_of' => t('live.ended_of', ['name' => '{name}']), 'reconnecting' => t('live.reconnecting'), 'count' => t('live.count', ['n' => '{n}']), 'nav' => t('live.nav'), 'profile' => t('live.profile', ['name' => '{name}']), 'gone' => t('live.gone'), 'unsupported' => t('live.unsupported'), 'watch' => t('live.watch'), 'playing' => t('live.playing'), 'ctl_play' => t('live.ctl_play'), 'ctl_pause' => t('live.ctl_pause'), 'ctl_mute' => t('live.ctl_mute'), 'ctl_unmute' => t('live.ctl_unmute'), 'ctl_full' => t('live.ctl_full'), 'ctl_exit' => t('live.ctl_exit'), 'ctl_back' => t('live.ctl_back'), 'ctl_fwd' => t('live.ctl_fwd'), 'ctl_pip' => t('live.ctl_pip'), 'ctl_wide' => t('live.ctl_theater'), 'ctl_stats' => t('live.ctl_stats'), 'resume' => t('live.resume', ['time' => '{time}']), 'share' => t('live.share'), 'stats_size' => t('live.stats_size'), 'stats_buffer' => t('live.stats_buffer'), 'stats_rate' => t('live.stats_rate'), 'stats_stream' => t('live.stats_stream'), 'stats_frames' => t('live.stats_frames'), 'stats_behind' => t('live.stats_behind')]], JSON_UNESCAPED_UNICODE | JSON_HEX_TAG) ?></script>
  <?php // The script itself, the same for every visit: its address changes with the file (asset_url()), so that a browser
        // that kept it gets the new one with a new page. ?>
  <script src="<?= asset_url('live.js') ?>"></script>
<?php page_footer();
