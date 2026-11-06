<?php
/* The language switch in the header: remembers the choice and goes back to the page it was pressed on. */
require __DIR__ . '/lib.php';

$to = (string)($_GET['to'] ?? '');
if ($to === 'ko' || $to === 'en') {
    setcookie(LANG_COOKIE, $to, ['expires' => time() + LANG_DAYS * 86400, 'path' => '/', 'httponly' => true, 'samesite' => 'Lax']);
}
header('Location: ' . safe_next((string)($_GET['next'] ?? '/opendmtq/')), true, 303);
