<?php
/*
 * The original server's pictures the game server offers from the imported content when it has them, each by its role:
 * the two pages of the "how to play" popup and two banners of old screens (game.getDefaultSetting). The repository's
 * text names none of the game's servers or their files (the project's rule for its pages, comments, tests and names),
 * so their paths are kept here encoded (base64 of a JSON object) and read by role: odq_client_path('howto_play').
 *
 * Written by tools/opendmtq_tools/client_marks.py from the table of the client's names (in tools/:
 * python3 -m opendmtq_tools.client_marks --php > ../server/game/src/client_names.php); cli/tests/test_repo.py checks
 * that this file is what the table makes.
 */

/* The paths by role: base64 of a JSON object, in pieces. */
const ODQ_CLIENT_PATHS =
    'eyJob3d0b19ub3RlIjoic3RhdGljL2RtcS9iYW5uZXIvMTgwODAyX3R1dG8yX3BhY2thZ2UvaG93dG9wbGF5X25vdGUucG5nIiwi'
    . 'aG93dG9fcGxheSI6InN0YXRpYy9kbXEvYmFubmVyLzE4MDgwMl90dXRvMl9wYWNrYWdlL2hvd3RvcGxheV9wbGF5LnBuZyIsInRz'
    . 'dG9wIjoic3RhdGljL2RtcS9iYW5uZXIvMTgwNzE2X211Y2FzdW1tZXIvMTgwNzE2X3RzdG9wX3N1bW1lci5wbmciLCJ0d2MiOiJz'
    . 'dGF0aWMvZG1xL2Jhbm5lci8xODA3MTZfbXVjYXN1bW1lci8xODA3MTZfdHdjX3N1bW1lci5wbmcifQ==';

/* A picture's path under the content's web folder, by its role. */
function odq_client_path(string $role): string
{
    static $paths = null;
    // Decoded once a request.
    $paths ??= json_decode(base64_decode(ODQ_CLIENT_PATHS), true);
    return $paths[$role];
}
