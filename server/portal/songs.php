<?php
/* Song catalog with jackets; each song links to its leaderboards. */
require __DIR__ . '/lib.php';
// For those signed in only (a stranger goes to the sign-in page and comes back here).
require_sign_in();

$db = db();
// Plays per song, through the chart map.
$plays = [];
if ($db) {
    $charts = charts();
    // Players who have a record on each chart, counted by guid like the rest of the portal: Play's
    // user_id is the guid, and PLAYER_ROWS already leaves the check account out.
    foreach (rows($db, "SELECT p.pattern_id, COUNT(*) AS n FROM Play p WHERE p.user_id IN (SELECT guid FROM (" . PLAYER_ROWS . "))
                         GROUP BY p.pattern_id", [':check' => CHECK_UDID]) as $r) {
        $sid = $charts[(int)$r['pattern_id']][0] ?? 0;
        $plays[$sid] = ($plays[$sid] ?? 0) + (int)$r['n'];
    }
}
$songs = array_filter(song_list(), fn($s) => ($s['hidden_yn'] ?? 'N') !== 'Y');
usort($songs, fn($a, $b) => strcasecmp(song_title($a), song_title($b)));

page_header(t('songs.title'), 'songs');
?>
  <?= masthead('SONGS') ?>
  <?php // data-of: how the count reads while a search narrows the list ({shown} of {all}); data-all and data-one: without
        // a search, for many songs and for one. ?>
  <?php if (!$songs): ?><section class="card"><p class="empty"><?= t('songs.none') ?></p></section><?php endif; ?>
  <div class="songs-tools"<?= $songs ? '' : ' hidden' ?>>
    <input class="search" id="search" type="search" placeholder="<?= h(tp('songs.search')) ?>" aria-label="<?= h(tp('songs.search_label')) ?>" oninput="filterSongs(this.value)">
    <span class="meta-inline" id="song-count" role="status" data-of="<?= h(tp('songs.of')) ?>" data-all="<?= h(tp('songs.all')) ?>" data-one="<?= h(tp('songs.all', ['n' => 1])) ?>"><?= t('songs.all', ['n' => count($songs)]) ?></span>
  </div>
  <p class="empty" id="no-match" role="status" hidden><?= t('songs.nomatch') ?></p>
  <div class="songs" id="songs">
    <?php foreach ($songs as $s): $n = (int)($plays[(int)$s['song_id']] ?? 0); ?>
      <a class="song" href="song.php?id=<?= (int)$s['song_id'] ?>" title="<?= h(song_title($s) . ' · ' . $s['artist_name']) ?>" data-k="<?= h(strtolower(song_title($s) . ' ' . $s['artist_name'] . ' ' . $s['genre'])) ?>">
        <span class="song-pic"><img loading="lazy" decoding="async" src="<?= h(jacket($s)) ?>" alt=""<?= JACKET_ONERROR ?>></span>
        <span class="t"><?= h(song_title($s)) ?></span>
        <span class="a"><?= h($s['artist_name']) ?></span>
        <?php // Only songs somebody has a record on say so; the line stays, so that all tiles of a row end together. ?>
        <span class="p"><?= $db && $n > 0 ? ($n === 1 ? t('records.one') : t('records.many', ['n' => $n])) : '' ?></span>
      </a>
    <?php endforeach; ?>
  </div>
  <script>
    // Client-side filter; the list is small enough to keep in the page. The count follows it, and
    // a search that finds nothing says so.
    function filterSongs(q) {
      q = q.trim().toLowerCase();
      const all = document.querySelectorAll('#songs .song');
      const count = document.getElementById('song-count');
      let shown = 0;
      for (const el of all) {
        const hit = !q || el.dataset.k.includes(q);
        el.style.display = hit ? '' : 'none';
        shown += hit;
      }
      // The page's own wording for "12 of 191" (data-of), filled in here.
      count.textContent = q ? count.dataset.of.replace('{shown}', shown).replace('{all}', all.length)
        : all.length === 1 ? count.dataset.one : count.dataset.all.replace('{n}', all.length);
      document.getElementById('no-match').hidden = shown > 0;
    }
  </script>
<?php page_footer();
