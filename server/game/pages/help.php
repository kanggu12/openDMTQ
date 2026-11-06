<?php
/*
 * GET /www/mobile/help?app_id=576&member_id=<n>&...: the platform SDK's customer centre, opened in
 * the game's own browser by OPTION > CONTACT US and after OPTION > RESTORE DATA / CONNECT ACCOUNT.
 * The official one is gone and this server has none: one plain line says so, in Korean on Korean
 * phones (the browser's Accept-Language), in English otherwise. The phone's Back button closes the
 * page and returns to the game.
 */
header('Content-Type: text/html; charset=utf-8');
$korean = stripos((string)($_SERVER['HTTP_ACCEPT_LANGUAGE'] ?? ''), 'ko') === 0;
$text = $korean
    ? ['lang' => 'ko', 'title' => '지원하지 않는 기능', 'line' => '이 기능은 지원하지 않습니다.', 'back' => '뒤로 가기 버튼을 누르면 게임으로 돌아갑니다.']
    : ['lang' => 'en', 'title' => 'Not supported', 'line' => 'This feature is not supported.', 'back' => 'Press Back to return to the game.'];
?><!doctype html>
<html lang="<?= $text['lang'] ?>">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title><?= $text['title'] ?></title>
<style>
  /* The game's own colours: a near-black screen, white text. */
  html, body { height: 100%; margin: 0; background: #15171a; color: #f2f3f5; }
  body { display: flex; align-items: center; justify-content: center; text-align: center; padding: 16px;
         box-sizing: border-box; font: 18px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans KR", sans-serif; }
  p { margin: 0; }
  .back { margin-top: 10px; font-size: 15px; color: #b8bec7; }
</style>
</head>
<body>
<main>
  <p><?= $text['line'] ?></p>
  <p class="back"><?= $text['back'] ?></p>
</main>
</body>
</html>
