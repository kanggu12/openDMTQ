<?php
/* What the site and the app are made of, under which licenses. Open to everyone: these licenses ask that whoever receives
   the parts can see them, and a visitor's browser receives the player and the fonts. The texts come from the files next to
   those parts: .txt files are not served (site.conf), and these are the copies the licenses want kept with the parts. */
require __DIR__ . '/lib.php';

page_header(t('lic.title'));
// Part, what it is used for, and its license with a link where a page of ours has the text.
$parts = [
    ['hls.js 1.5.17', t('lic.use.player'), '<a href="/opendmtq/hls/LICENSE">Apache License 2.0</a>'],
    ['Saira, Pretendard', t('lic.use.fonts'), 'SIL Open Font License 1.1'],
    ['Dynarmic', t('lic.use.cpu'), '0BSD'],
    ['fmt, mcl, oaknut, robin-map', t('lic.use.cpu_libs'), 'MIT'],
    ['xbyak, Zydis, Zycore', t('lic.use.cpu_x86'), 'BSD 3-Clause (xbyak), MIT (Zydis, Zycore)'],
    ['Android linker, libc, libm, libdl, libstdc++, libc++, libz, liblog', t('lic.use.android'), t('lic.android')],
];
?>
  <?= masthead('LICENSE') ?>
  <section class="card">
    <p><?= t('lic.own') ?></p>
    <p><?= t('lic.game') ?></p>
    <details class="license-fold">
      <summary><?= t('lic.text', ['name' => 'MIT License']) ?></summary>
      <pre class="license-text"><?= h((string)@file_get_contents(__DIR__ . '/LICENSE')) ?></pre>
    </details>
  </section>
  <section class="card">
    <h2><?= t('lic.parts') ?></h2>
    <div class="table-scroll">
      <table class="board parts">
        <thead><tr><th class="name"><?= t('lic.th.part') ?></th><th class="name"><?= t('lic.th.use') ?></th><th class="name"><?= t('lic.th.license') ?></th></tr></thead>
        <tbody>
          <?php foreach ($parts as [$part, $use, $license]): ?>
            <tr><td class="name"><?= h($part) ?></td><td class="name"><?= $use ?></td><td class="name"><?= $license ?></td></tr>
          <?php endforeach; ?>
        </tbody>
      </table>
    </div>
    <p><?= t('lic.app') ?></p>
    <?php foreach (['Saira' => 'OFL-Saira.txt', 'Pretendard' => 'OFL-Pretendard.txt'] as $name => $file): ?>
      <details class="license-fold">
        <summary><?= t('lic.text', ['name' => 'SIL Open Font License 1.1, ' . $name]) ?></summary>
        <pre class="license-text"><?= h((string)@file_get_contents(__DIR__ . '/fonts/' . $file)) ?></pre>
      </details>
    <?php endforeach; ?>
  </section>
<?php page_footer();
