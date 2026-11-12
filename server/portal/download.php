<?php
/* The app's download page: the download (.apk), the steps after it, and help. The home page leads here. */
require __DIR__ . '/lib.php';
// For those signed in only (a stranger goes to the sign-in page and comes back here).
require_sign_in();

$host = public_host();
$apk = apk_manifest();
// Built for another address: the phone would install a client that cannot find this server.
$stale = $apk && $apk['host'] !== $host;
// No app for this address: whether the builder is making one now, or gave up on it (waiting would not help then).
$building = (!$apk || $stale) && build_state() === 'building';
$failed = (!$apk || $stale) && build_failed();
// The builder draws the QR code next to the app; older builds have none.
$qr = $apk && !$stale && is_file(APK_DIR . '/download-qr.svg');
// Built with the arm32 runtime: phones without 32-bit support can install and play it too.
$any_phone = $apk && !empty($apk['runtime']);
// Links shared in messengers open in the app's own browser, which may not hand the download to Android.
$in_app = in_app_browser();
// An app a phone can get right now: only then do the install steps, which start from its button, apply.
$ready = $apk && !$stale && !$failed && !$in_app;
// Just signed in from a download link: this page starts the download (once; see dl_take_start).
$start = dl_take_start() && $apk && !$stale && !$in_app && !on_ios();
// The installer for Windows (the PC client), set up for this server as it is handed out, when the server has it.
$win = windows_client();

// The download starts after a second, so the page that says so is on screen first. While the
// builder is making the app (none yet, or one for the old address), check again on its own; only then.
page_header(t('dl.title'), 'download', $start ? '1;url=/apk' : ($building ? '20' : ''));
?>
  <?= masthead('DOWNLOAD') ?>
  <section class="card" id="install">
    <?php // The centrepiece: the button and the QR code side by side, then the steps across the whole box. ?>
    <div class="install-head">
      <div class="install-main">
      <div class="get-app"<?= hidden_on_ios() ?>>
      <?php if ($in_app): ?>
        <?= open_in_browser($in_app, '/opendmtq/download.php') ?>
      <?php elseif ($failed): ?>
        <p class="warn" role="status"><?= t('build.failed') ?></p>
      <?php elseif ($building): ?>
        <?php // Being made now: for this address for the first time, or again for a new one. ?>
        <p class="warn" role="status"><?= t($stale ? 'build.stale' : 'build.wait') ?></p>
      <?php elseif (!$apk || $stale): ?>
        <?php // None for this address, and nothing making one: said once, no waiting. ?>
        <p class="warn" role="status"><?= t('build.none') ?></p>
      <?php else: ?>
        <?php if ($start): ?>
          <p class="done" role="status"><?= t('dl.starting') ?></p>
        <?php endif; ?>
        <a class="button get" href="/apk"><?= t('dl.button') ?></a>
        <p class="meta"><?= t('dl.meta', ['size' => number_format($apk['size'] / 1048576, 1), 'date' => substr($apk['built_at'], 0, 10)]) ?></p>
      <?php endif; ?>
      <?php // Before anyone signs in for it too, and as plain as the rest of the page: this is what decides whether to go on. ?>
      <p class="for-android"><?= t('home.android') ?></p>
      </div>
      <?= android_only() ?>
      </div>
      <?php if ($qr): ?>
        <figure class="qr get-app"<?= hidden_on_ios() ?>>
          <img src="qr.php" alt="<?= h(tp('qr.alt')) ?>" width="132" height="132">
          <figcaption><?= t('qr.caption') ?></figcaption>
        </figure>
      <?php endif; ?>
    </div>
    <?php // What to do after the button: three steps in order, then the cases that are not every player's,
          // then help folded away. ?>
    <div class="get-app"<?= hidden_on_ios() ?>>
        <?php if ($apk && !$any_phone): ?>
          <p class="warn"><?= t('dl.32bit') ?></p>
        <?php endif; ?>
        <?php if ($ready): ?>
          <?php // Each step with the screen it meets on the phone, drawn small: the file as the phone lists it, Android's switch
                // that lets the browser install, and the app's own icon to look for among the others. A step's words are
                // one paragraph: the step is a column with its screen at the foot, and in a column each bold word or code
                // loose in it would stand on a line of its own. ?>
          <ol class="steps">
            <li><p class="step-text"><?= t('step.download') ?></p>
              <div class="screen" aria-hidden="true"><span class="screen-row"><span class="screen-file">APK</span><span class="screen-text"><b><?= h($apk['file']) ?></b><small><?= number_format($apk['size'] / 1048576, 1) ?> MB</small></span></span></div>
            </li>
            <li><p class="step-text"><?= t('step.install') ?></p>
              <div class="screen" aria-hidden="true"><span class="screen-title"><?= t('screen.unknown') ?></span><span class="screen-row"><span class="screen-text"><b><?= t(preg_match('/SamsungBrowser/', (string)($_SERVER['HTTP_USER_AGENT'] ?? '')) ? 'screen.samsung' : 'screen.chrome') ?></b><small><?= t('screen.allow') ?></small></span><span class="screen-switch"></span></span></div>
            </li>
            <li><p class="step-text"><?= strtr(t('step.play'), ['{app}' => app_name_html()]) ?></p>
              <div class="screen screen-home" aria-hidden="true"><?php if (is_file(APK_DIR . '/app-icon.png')): ?><span class="screen-icon"><img src="icon.php" alt="" width="56" height="56"></span><?php endif; ?><?= app_name_html() ?></div>
            </li>
          </ol>
          <ul class="notes">
            <li><?= t(lan_only($host) ? 'step.lan' : 'step.net') ?> <?= t('note.songs') ?></li>
            <li><?= t('note.update') ?></li>
            <li><?= t('note.other') ?></li>
          </ul>
        <?php endif; ?>
        <details class="help" id="help">
          <summary><?= t('help.title') ?></summary>
          <ul>
            <li><?= t('help.other') ?></li>
            <?php if ($apk && !$any_phone): ?>
              <li><?= t('help.32bit') ?></li>
            <?php elseif ($any_phone): ?>
              <li><?= t('help.compat') ?></li>
            <?php endif; ?>
          </ul>
        </details>
    </div>
  </section>
  <?php if ($win): ?>
    <?php // A computer plays too: the same app, through the PC client, which this download sets up for this server. ?>
    <section class="card" id="computer">
      <h2><?= t('pc.title') ?></h2>
      <a class="button get" href="/windows"><?= t('pc.button') ?></a>
      <?php /* The version when the installer came with one (a release's); a copy put there by hand has its size only. */ ?>
      <?php $win_version = (string)($win['version'] ?? ''); $win_mb = number_format($win['size'] / 1048576, 1); ?>
      <p class="meta"><?= $win_version !== '' ? t('pc.meta', ['size' => $win_mb, 'version' => $win_version]) : t('pc.meta_size', ['size' => $win_mb]) ?></p>
      <p><?= t('pc.steps', ['address' => public_host()]) ?></p>
      <p class="meta"><?= t('pc.needs') ?></p>
    </section>
  <?php endif; ?>
<?php page_footer();
