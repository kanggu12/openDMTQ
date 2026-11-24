<?php
/* The site's sign-in page: every page of the site is behind it (require_sign_in() in lib.php), the app download too.
   An account's ID and password, made on the admin pages' Accounts page; nobody makes their own. */
require __DIR__ . '/lib.php';

$next = safe_next((string)($_GET['next'] ?? $_POST['next'] ?? '/opendmtq/'));

// Signing out: forget the cookie and go home. A form on this site only: a link or a form elsewhere does nothing.
if (isset($_GET['logout'])) {
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && !from_another_site()) {
        dl_sign_out();
    }
    header('Location: /opendmtq/', true, 303);
    exit;
}
// The message to show, as a key of STRINGS (in the page's language).
$error = '';
// A ban's own words, made with its reason, shown in place of the message's key for a banned player's account.
$banned = '';
// A one-time link (the PC client's My page on the site, the admin API's): this browser signed in to its account, once,
// in the minute after it was made, whoever it was signed in as, then on to its page. Not from another site's page, which
// would sign a visitor in to an account of its own choosing; an account that is off now signs in nobody.
if (isset($_GET['once'])) {
    $link = from_another_site() ? null : once_take((string)$_GET['once']);
    $row = $link !== null ? site_account($link['account']) : null;
    // The ban of the player the account is linked to, as the sign-in form checks it (banned since the link was made, or a
    // link the admin API made for a banned player's account).
    $ban = $row !== null ? site_ban($row) : null;
    if ($row !== null && !$row['off'] && dl_key() !== '' && $ban === null) {
        dl_sign_in((string)$row['name']);
        header('Cache-Control: no-store');
        header('Location: ' . $link['next'], true, 303);
        exit;
    }
    // Used, run out or refused: the sign-in page says so, above its form (signed in already, on to the page as below); an
    // account switched off says that it is, and a banned player's account why, in the owner's words, as the form does.
    $error = $row !== null && $row['off'] ? 'signin.off' : ($ban !== null ? 'signin.banned' : 'signin.once_used');
    $banned = $ban !== null && !$row['off'] ? site_ban_words($ban) : '';
}
// Already signed in (this form sent again, a back button): on to the page, but not into a second
// download; the install box has the button.
if (dl_signed_in()) {
    header('Location: ' . ($next === '/apk' ? '/opendmtq/download.php' : ($next === '/windows' ? '/opendmtq/download.php#computer' : $next)));
    exit;
}

// A sign-in form on another site: nobody is signed in to an account that site chose, nothing it sent is read or counted,
// and the browser gets this sign-in page, empty.
if ($_SERVER['REQUEST_METHOD'] === 'POST' && from_another_site()) {
    header('Location: /opendmtq/login.php?next=' . rawurlencode($next), true, 303);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    // The ID as typed, without the space a phone's keyboard may add after a word.
    $user = trim((string)($_POST['user'] ?? ''));
    $password = (string)($_POST['password'] ?? '');
    if ($user === '' || $password === '') {
        // Sent with a field empty (the page's own check, forms.js, stops that first): said as that check says it, and no
        // guess at any password, so not counted toward the limit.
        $error = $user === '' ? 'signin.missing_id' : 'signin.missing_password';
    } elseif (!site_sign_in_works()) {
        // Nothing to check the password against: the server's trouble, said as such, and not counted as a guess.
        $error = 'signin.down';
    } elseif (($attempt = dl_attempt_begin($user)) === null) {
        // Counted before the password is compared, so a burst of guesses cannot pass the limit together; for the account
        // typed, whose admin rights put it under a limit for the whole server too.
        $error = 'signin.throttled';
    } elseif (($row = site_password_row($user, $password)) !== null && $row['off']) {
        // The right password of an account switched off on the Accounts page: not a guess, and no sign-in; said in its own
        // words, to whoever knows the password alone (a wrong one is told only that it is wrong).
        dl_attempt_succeeded($attempt);
        $error = 'signin.off';
    } elseif (($who = $row !== null ? (string)$row['name'] : null) !== null && ($ban = site_ban($row)) !== null) {
        // The right password of a banned player's account: not a guess, and no sign-in; the owner's reason says why.
        dl_attempt_succeeded($attempt);
        $error = 'signin.banned';
        $banned = site_ban_words($ban);
    } elseif ($who !== null) {
        // A right password is not a failure.
        dl_attempt_succeeded($attempt);
        // From a download link: the download itself would leave this filled form on screen, so the
        // install box takes over and starts it.
        if ($next === '/apk') {
            dl_request_start();
            $next = '/opendmtq/download.php';
        }
        // From the link for computers: the download page's part for them, where its button is.
        if ($next === '/windows') {
            $next = '/opendmtq/download.php#computer';
        }
        dl_sign_in($who);
        header('Location: ' . $next, true, 303);
        exit;
    } else {
        // The attempt stays counted as a failure. Slow down guessing.
        sleep(1);
        $error = 'signin.wrong';
    }
}

// On the way to a broadcast, the page speaks of watching instead of the download.
$for_live = strpos($next, '/opendmtq/live.php') === 0;
// Only the way to the download is about installing; from the header's link it just signs in.
$for_install = $next === '/apk';
// The page's colour: the live section's on the way to a broadcast, the site's own otherwise.
$from = $for_live ? 'live' : '';
page_header(t('signin.title'), $from);
?>
  <?php // The front door: the wordmark big and what this is, then the sign-in under them. ?>
  <div class="door">
    <div class="logo door-mark" aria-hidden="true"><span class="o">OPEN</span><span class="m">DMT<b>Q</b></span></div>
    <p class="door-line"><?= t('home.title') ?></p>
  </div>
  <section class="card signin">
    <h2><?= t($for_live ? 'live.signin' : ($for_install ? 'dl.signin' : 'signin.title')) ?></h2>
    <p class="signin-lead"><?= t('signin.lead') ?></p>
    <?php // The game is for Android; signing in, and watching a broadcast, works on an iPhone as well. ?>
    <?php if ($app = in_app_browser()): ?>
      <?= open_in_browser($app, '/opendmtq/login.php?next=' . rawurlencode($next)) ?>
    <?php else: ?>
      <?php // On the way to the download: what an iPhone or iPad can and cannot do, above the form (it can still sign in to
            // watch). Shown to an iPad that says it is a Mac by the note's own script. ?>
      <?= $for_install ? android_only() : '' ?>
      <div>
      <?php $missing = in_array($error, ['signin.missing_id', 'signin.missing_password'], true) ? $error : ''; ?>
      <?php // A field the server found empty says so under itself; anything else (a wrong password, too many tries) above
            // the form, in the box. ?>
      <?php if ($error && !$missing): ?>
        <?php // An error, in red: the yellow box is for notices (maintenance, the app being built). ?>
        <p class="error" role="alert"><?= $banned !== '' ? $banned : t($error) ?></p>
      <?php endif; ?>
      <?php // Each field's words when it is left empty come from the site's own check (forms.js), in the page's language and
            // look, under the field, not from the browser's bubbles (novalidate): each field's words in its data-missing. A
            // wrong password takes a second to answer: the button shows that it is working meanwhile (forms.js too). The ID
            // last used on this browser comes back in its field (data-remember, forms.js), and the focus then goes to the
            // password. ?>
      <form method="post" action="login.php?next=<?= h(rawurlencode($next)) ?>" class="signin-form" novalidate data-remember="site">
        <input type="hidden" name="next" value="<?= h($next) ?>">
        <?php // The ID is in Latin letters: the email keyboard (Latin, not Hangul), no capitals or corrections. The field the
              // server found empty is marked, and has the focus. ?>
        <div class="field">
          <label for="signin-user"><?= t('signin.id') ?></label>
          <span class="slot"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4.5 20c1.4-3.7 4.3-5.6 7.5-5.6s6.1 1.9 7.5 5.6"/></svg><input id="signin-user" name="user" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" inputmode="email" lang="en" required data-missing="<?= h(tp('signin.missing_id')) ?>"<?= $missing === 'signin.missing_id' ? ' aria-invalid="true" aria-describedby="signin-user-error" autofocus' : '' ?> value="<?= h($_POST['user'] ?? '') ?>"></span>
          <?php if ($missing === 'signin.missing_id'): ?><span class="field-error" id="signin-user-error" role="alert"><?= t($missing) ?></span><?php endif; ?>
        </div>
        <?php // Show, in the field, lets the password be read as typed (forms.js; without scripts it stays hidden, as does the
              // button). ?>
        <div class="field">
          <label for="signin-password"><?= t('signin.password') ?></label>
          <span class="slot pw"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10.5" width="14" height="10" rx="1.5"/><path d="M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3"/></svg><input id="signin-password" name="password" type="password" autocomplete="current-password" required data-missing="<?= h(tp('signin.missing_password')) ?>"<?= $missing === 'signin.missing_password' ? ' aria-invalid="true" aria-describedby="signin-password-error"' : '' ?><?= $error && $missing !== 'signin.missing_id' ? ' autofocus' : '' ?>><button type="button" class="pw-toggle" aria-controls="signin-password" aria-label="<?= h(tp('signin.show')) ?> <?= h(tp('signin.password')) ?>" data-show="<?= h(tp('signin.show')) ?>" data-hide="<?= h(tp('signin.hide')) ?>" data-show-label="<?= h(tp('signin.show')) ?> <?= h(tp('signin.password')) ?>" data-hide-label="<?= h(tp('signin.hide')) ?> <?= h(tp('signin.password')) ?>" hidden><?= t('signin.show') ?></button></span>
          <?php if ($missing === 'signin.missing_password'): ?><span class="field-error" id="signin-password-error" role="alert"><?= t($missing) ?></span><?php endif; ?>
        </div>
        <button class="button" type="submit"><?= t('signin.button') ?></button>
      </form>
      </div>
    <?php endif; ?>
  </section>
  <?php // The form's own check (shared with any form marked novalidate), by its version as the other scripts. ?>
  <script src="<?= asset_url('forms.js') ?>" defer></script>
<?php page_footer();
