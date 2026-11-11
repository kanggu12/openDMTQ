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

// The message to show, as a key of STRINGS (in the page's language).
$error = '';
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
    } elseif (($who = site_check($user, $password)) !== null) {
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
    <?php // The game is for Android; signing in, and watching a broadcast, works on an iPhone as well. ?>
    <?php if ($app = in_app_browser()): ?>
      <?= open_in_browser($app, '/opendmtq/login.php?next=' . rawurlencode($next)) ?>
    <?php else: ?>
      <?php // On the way to the download: what an iPhone or iPad can and cannot do, above the form (it can still sign in to
            // watch). Shown to an iPad that says it is a Mac by the note's own script. ?>
      <?= $for_install ? android_only() : '' ?>
      <div>
      <?php if ($error): ?>
        <?php // An error, in red: the yellow box is for notices (maintenance, the app being built). ?>
        <p class="error" role="alert"><?= t($error) ?></p>
      <?php endif; ?>
      <?php // What a field left empty says comes from the site's own check (forms.js), in the page's language and the
            // error box's look, not from the browser's bubbles (novalidate): each field's words in its data-missing. A
            // wrong password takes a second to answer: the button shows that it is working meanwhile (forms.js too). ?>
      <?php $missing = in_array($error, ['signin.missing_id', 'signin.missing_password'], true) ? $error : ''; ?>
      <form method="post" action="login.php?next=<?= h(rawurlencode($next)) ?>" class="signin-form" novalidate>
        <input type="hidden" name="next" value="<?= h($next) ?>">
        <?php // The ID is in Latin letters: the email keyboard (Latin, not Hangul), no capitals or corrections. The field the
              // server found empty is marked, and has the focus. ?>
        <label class="field"><?= t('signin.id') ?> <input name="user" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" inputmode="email" lang="en" required data-missing="<?= h(tp('signin.missing_id')) ?>"<?= $missing === 'signin.missing_id' ? ' aria-invalid="true" autofocus' : '' ?> value="<?= h($_POST['user'] ?? '') ?>"></label>
        <label class="field"><?= t('signin.password') ?> <input name="password" type="password" autocomplete="current-password" required data-missing="<?= h(tp('signin.missing_password')) ?>"<?= $missing === 'signin.missing_password' ? ' aria-invalid="true"' : '' ?><?= $error && $missing !== 'signin.missing_id' ? ' autofocus' : '' ?>></label>
        <button class="button" type="submit"><?= t('signin.button') ?></button>
      </form>
      </div>
    <?php endif; ?>
  </section>
  <?php // The form's own check (shared with any form marked novalidate), by its version as the other scripts. ?>
  <script src="<?= asset_url('forms.js') ?>" defer></script>
<?php page_footer();
