<?php
/* The page for addresses that lead nowhere (ErrorDocument 404 in site.conf). The address in the
   browser stays the one asked for, so every link here is absolute. */
require __DIR__ . '/lib.php';

http_response_code(404);
// No section: none of the header's headings is where the visitor is.
page_header(t('nf.title'));
?>
  <?= lost(t('nf.title'), t('nf.text'), [['/opendmtq/', t('go.home')]]) ?>
<?php page_footer();
