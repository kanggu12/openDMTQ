<?php
/*
 * A player's game state as the server keeps it, and what the game is told of it: the two currencies the game shows on its
 * top bar (MAX POINT and Q), the experience the level comes from, the items a player has beyond or short of what everyone
 * has, the unlimited currency (a player's own switch and the server's), and bans. The admin pages set them
 * (tools/opendmtq_tools/admin/game.py, with the same tables and rules), and the game's own requests read and change them:
 * game.getUserAsset tells, a saved play earns, a chart that costs MAX POINT and the shop spend (game.php, shop.php).
 *
 * A player the server has kept nothing of yet has what the server gives a new player (GameSetting's start values: until the
 * owner changes them, the 999,999 of each currency and the level 99 every player had before these were kept). The first
 * change of theirs, by the game or on the admin pages, keeps a row of their own (PlayerState), from then on theirs alone.
 */

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/db.php';
require_once __DIR__ . '/content.php';
require_once __DIR__ . '/util.php';

/*
 * The experience each level starts at, as the client's own level table has it (client 1.3.4, its experience column): level 1 at 0,
 * level 2 at 10, ..., level 99 at 130,408. The top bar's gauge is the share of the way from the start of the player's level
 * to the next one's, so the level and the experience the game is told must agree: the server keeps the experience and
 * works the level out of it (odq_level_of()), and a level set on the admin pages sets the experience to that level's start.
 */
const OPENDMTQ_LEVEL_EXP = [
    0, 10, 30, 60, 100, 150, 210, 280, 360, 450, 545, 644, 748, 857, 972, 1093, 1219, 1352, 1492, 1639, 1793, 1954, 2004,
    2182, 2369, 2565, 2771, 2988, 3215, 3453, 3704, 3967, 4243, 4533, 4837, 5157, 5493, 5845, 6215, 6607, 7023, 7464, 7931,
    8426, 8951, 9508, 10081, 10683, 11314, 11978, 12674, 13406, 14174, 14980, 15827, 16716, 17650, 18630, 19610, 20630,
    21690, 22792, 23939, 25132, 26372, 27662, 29003, 29803, 31400, 33061, 34789, 36585, 38453, 40396, 42417, 44518, 46704,
    47904, 50404, 53004, 55708, 58520, 61445, 64487, 67650, 70940, 74361, 77919, 81620, 85469, 89471, 93634, 97963, 102465,
    107148, 108648, 114569, 120904, 130408,
];
// The highest level: the game's table ends there, and its gauge is full at it.
const OPENDMTQ_LEVEL_TOP = 99;
// The most experience kept: level 99's start, past which nothing the game shows changes.
const OPENDMTQ_EXP_MAX = 130408;
// The most of a currency a player may hold: the most the top bar shows whole in its place (8 digits with their commas, as
// measured in the game: 99,999,999 fits beside Q and MAX, 100,000,000 runs past the bar's edge).
const OPENDMTQ_POINTS_MAX = 99999999;
// What the game is told a player with unlimited currency has, of each: a figure that reads as "no end" and leaves room in
// the bar. Nothing is taken from it: a purchase and a chart's cost leave the player's own balance as it was.
const OPENDMTQ_POINTS_UNLIMITED = 99999999;
// What a saved play earns, as the save's reply has always said (the result screen shows both): MAX POINT and experience.
const OPENDMTQ_PLAY_MPOINT = 150;
const OPENDMTQ_PLAY_EXP = 10;
// The longest reason a ban keeps: two lines of the in-game notice.
const OPENDMTQ_BAN_REASON_MAX = 200;

/*
 * The server's game settings (GameSetting, a name and its value per row, which the admin pages write): unlimited currency
 * for every player (off until the owner turns it on), and what a player starts with: MAX POINT, Q and the level, the values
 * every player had before the server kept any (999,999, 999,999 and 99) until the owner sets others. Once per request.
 */
function odq_game_settings(?SQLite3 $db = null): array
{
    static $settings = null;
    if ($settings !== null && $db === null) {
        return $settings;
    }
    $out = ['unlimited' => false, 'start_mpoint' => 999999, 'start_qpoint' => 999999, 'start_level' => OPENDMTQ_LEVEL_TOP];
    $r = @($db ?? odq_db())->query('SELECT name, value FROM GameSetting');
    while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
        $name = (string)$row['name'];
        $value = (string)$row['value'];
        if ($name === 'unlimited') {
            $out['unlimited'] = $value === '1';
        } elseif ($name === 'start_level') {
            // A level the game has, whatever another program wrote there.
            $out['start_level'] = odq_clamp($value, 1, OPENDMTQ_LEVEL_TOP);
        } elseif ($name === 'start_mpoint' || $name === 'start_qpoint') {
            $out[$name] = odq_clamp($value, 0, OPENDMTQ_POINTS_MAX);
        }
    }
    // Kept for the rest of the request, unless read through another handle (a transaction's own).
    if ($db === null) {
        $settings = $out;
    }
    return $out;
}

/* The level a player of $exp experience is: the highest whose start it has reached, from 1 to 99. */
function odq_level_of(int $exp): int
{
    $level = 1;
    foreach (OPENDMTQ_LEVEL_EXP as $i => $start) {
        if ($exp >= $start) {
            $level = $i + 1;
        }
    }
    return min($level, OPENDMTQ_LEVEL_TOP);
}

/* The experience a level starts at: what a player set to that level has. */
function odq_level_exp(int $level): int
{
    return OPENDMTQ_LEVEL_EXP[odq_clamp($level, 1, OPENDMTQ_LEVEL_TOP) - 1];
}

/*
 * A player's game state: ['mpoint', 'qpoint', 'exp', 'level', 'own_unlimited' (their own switch), 'unlimited' (theirs or the
 * server's), 'kept' (a row of theirs exists)]. Without a row, the server's start values. $db: a handle in a transaction,
 * which then reads what it has written.
 */
function odq_player_state(int $guid, ?SQLite3 $db = null): array
{
    $db = $db ?? odq_db();
    $settings = odq_game_settings();
    $row = false;
    $q = @$db->prepare('SELECT mpoint, qpoint, exp, unlimited FROM PlayerState WHERE guid = :g');
    if ($q) {
        $q->bindValue(':g', $guid, SQLITE3_INTEGER);
        $r = @$q->execute();
        $row = $r ? $r->fetchArray(SQLITE3_ASSOC) : false;
    }
    if ($row) {
        // What another program may have written outside the game's range is read inside it.
        $exp = odq_clamp($row['exp'], 0, OPENDMTQ_EXP_MAX);
        $state = ['mpoint' => odq_clamp($row['mpoint'], 0, OPENDMTQ_POINTS_MAX), 'qpoint' => odq_clamp($row['qpoint'], 0, OPENDMTQ_POINTS_MAX),
                  'exp' => $exp, 'own_unlimited' => (int)$row['unlimited'] === 1, 'kept' => true];
    } else {
        $state = ['mpoint' => $settings['start_mpoint'], 'qpoint' => $settings['start_qpoint'],
                  'exp' => odq_level_exp($settings['start_level']), 'own_unlimited' => false, 'kept' => false];
    }
    $state['level'] = odq_level_of($state['exp']);
    // Unlimited for this player when their own switch or the server's is on.
    $state['unlimited'] = $state['own_unlimited'] || $settings['unlimited'];
    return $state;
}

/* What the game is told a player holds, [MAX POINT, Q]: the figure of no end while their currency is unlimited. */
function odq_shown_points(array $state): array
{
    if ($state['unlimited']) {
        return [OPENDMTQ_POINTS_UNLIMITED, OPENDMTQ_POINTS_UNLIMITED];
    }
    return [$state['mpoint'], $state['qpoint']];
}

/*
 * Changes a player's kept state by amounts (each may be negative), within the game's ranges, inside the caller's
 * transaction on $db: a player without a row gets one from the server's start values first. Returns the state after.
 */
function odq_state_add(SQLite3 $db, int $guid, int $mpoint, int $qpoint, int $exp): array
{
    $before = odq_player_state($guid, $db);
    $after = [
        'mpoint' => odq_clamp($before['mpoint'] + $mpoint, 0, OPENDMTQ_POINTS_MAX),
        'qpoint' => odq_clamp($before['qpoint'] + $qpoint, 0, OPENDMTQ_POINTS_MAX),
        'exp' => odq_clamp($before['exp'] + $exp, 0, OPENDMTQ_EXP_MAX),
    ];
    $w = $db->prepare('INSERT INTO PlayerState (guid, mpoint, qpoint, exp, unlimited, changed_at) VALUES (:g, :m, :q, :e, 0, :now)
                       ON CONFLICT (guid) DO UPDATE SET mpoint = excluded.mpoint, qpoint = excluded.qpoint, exp = excluded.exp,
                       changed_at = excluded.changed_at');
    $w->bindValue(':g', $guid, SQLITE3_INTEGER);
    $w->bindValue(':m', $after['mpoint'], SQLITE3_INTEGER);
    $w->bindValue(':q', $after['qpoint'], SQLITE3_INTEGER);
    $w->bindValue(':e', $after['exp'], SQLITE3_INTEGER);
    $w->bindValue(':now', time(), SQLITE3_INTEGER);
    if (!@$w->execute()) {
        throw new RuntimeException($db->lastErrorMsg());
    }
    return odq_player_state($guid, $db);
}

/* ------------------------------------------------------------------------------------------------------------- items */

/*
 * The items a player has: every item of the catalog everyone has (content.php's odq_catalog()['items']), but those taken
 * from them, and those they bought or were given (PlayerItem: owned 1 or 0 per item). In the catalog's order, then the
 * others by id.
 */
function odq_owned_items(int $guid): array
{
    $given = $taken = [];
    $q = @odq_db()->prepare('SELECT item_id, owned FROM PlayerItem WHERE guid = :g ORDER BY item_id');
    if ($q) {
        $q->bindValue(':g', $guid, SQLITE3_INTEGER);
        $r = @$q->execute();
        while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
            if ((int)$row['owned'] === 1) {
                $given[(int)$row['item_id']] = true;
            } else {
                $taken[(int)$row['item_id']] = true;
            }
        }
    }
    $items = [];
    foreach (odq_catalog()['items'] as $id) {
        if (!isset($taken[(int)$id])) {
            $items[(int)$id] = true;
        }
    }
    foreach ($given as $id => $_) {
        $items[$id] = true;
    }
    return array_keys($items);
}

/* Notes in $db that a player has an item now (bought, given): their own from then on, whatever the catalog says. */
function odq_item_owned(SQLite3 $db, int $guid, int $item, string $how): void
{
    $w = $db->prepare('INSERT INTO PlayerItem (guid, item_id, owned, how, at) VALUES (:g, :i, 1, :how, :now)
                       ON CONFLICT (guid, item_id) DO UPDATE SET owned = 1, how = excluded.how, at = excluded.at');
    $w->bindValue(':g', $guid, SQLITE3_INTEGER);
    $w->bindValue(':i', $item, SQLITE3_INTEGER);
    $w->bindValue(':how', $how, SQLITE3_TEXT);
    $w->bindValue(':now', time(), SQLITE3_INTEGER);
    if (!@$w->execute()) {
        throw new RuntimeException($db->lastErrorMsg());
    }
}

/* ------------------------------------------------------------------------------------------------------------------ bans */

/*
 * A player's ban while it lasts: ['reason', 'since', 'until' (null: until it is lifted), 'by'], or null. A ban whose end
 * has passed is over by itself: null, its row left for the admin pages to tidy. Read once per request through the
 * request's own handle: rpc.php asks before each call of a player's, fourteen of one player in the batch after the game's
 * sign-in. Through another handle (the site's) it is read each time.
 */
function odq_ban_of(int $guid, ?SQLite3 $db = null): ?array
{
    // What this request read of each player, by guid.
    static $seen = [];
    if ($db === null && array_key_exists($guid, $seen)) {
        return $seen[$guid];
    }
    $ban = null;
    $q = @($db ?? odq_db())->prepare('SELECT reason, since, until, by FROM PlayerBan WHERE guid = :g');
    if ($q) {
        $q->bindValue(':g', $guid, SQLITE3_INTEGER);
        $r = @$q->execute();
        $row = $r ? $r->fetchArray(SQLITE3_ASSOC) : false;
        // A ban that lasts: one without an end, or one whose end has not come.
        if ($row && ($row['until'] === null || (int)$row['until'] > time())) {
            $ban = ['reason' => (string)$row['reason'], 'since' => (int)$row['since'],
                    'until' => $row['until'] === null ? null : (int)$row['until'], 'by' => (string)$row['by']];
        }
    }
    // Kept for the rest of the request, unless read through another handle.
    if ($db === null) {
        $seen[$guid] = $ban;
    }
    return $ban;
}

/*
 * The calls whose first parameter is the player's id (guid): the ones a banned player's game is refused (rpc.php). The
 * rankings' calls that start with a line or a song, the start's service.getInfo and the news are not a player's.
 */
const OPENDMTQ_PLAYER_CALLS = [
    'game.getadsonglist', 'game.getadticketchecked', 'game.getadticketrequest', 'game.getadticketreceived',
    'game.getadticketused', 'game.getgameassetformigbytoken', 'game.getlinescoremyrank', 'game.getlinescoremyrankwithlevel',
    'game.getlinescoremyrankwithnext', 'game.getownachievementlist', 'game.getownitemlist', 'game.getownpatternscore',
    'game.getownquestlist', 'game.getownsonglist', 'game.getpatternurl', 'game.getpreviewplayinfo', 'game.getsongurl',
    'game.getuserasset', 'game.saveplayresult', 'game.saveplayresultfaillog', 'game.setslotitem', 'memo.getmemolist',
    'shop.buyfreeproduct', 'shop.buyproductbyqpoint', 'shop.getownitemlist', 'shop.getpackageinfobyguid',
    'shop.getproductforunlock', 'shop.getunlockedproductlist', 'shop.upgradeingameitem', 'shop.usecoupon',
    'user.getconnectuuid', 'user.setconnectuuid', 'user.setnickname',
];

/*
 * The player a call is made for, as a guid (0 for none): the first parameter of a player's call, read as the handlers read
 * it (odq_intval(): the leading digits of a text), and for the game's own login (user.loginV2) the account its access token
 * names.
 */
function odq_call_player(string $method, array $params): int
{
    if ($method === 'user.loginv2') {
        // The token's first part is the account's puid (platform.php makes it so).
        $puid = explode('|', odq_text($params[0] ?? null))[0];
        $member = $puid === '' ? null : odq_member_by('puid', $puid);
        return $member ? odq_intval($member['guid']) : 0;
    }
    if (!in_array($method, OPENDMTQ_PLAYER_CALLS, true)) {
        return 0;
    }
    // The handlers take "9302x" or " 9302" for player 9302 (shop.php, game.php: odq_intval()), so the ban does too: an id
    // with anything after its digits is the same player here as in the call it reaches.
    return odq_intval($params[0] ?? null);
}

/*
 * Tells a banned player why, in the game: the overlay of the PC client and the phones' runtime show the server's notice
 * (/live/state, docs/live.md) wherever the game is, a ban's in a song too; this one comes with the owner's reason and, when
 * the ban has an end, when it ends. $again: a new notice even while one is waiting (each refused sign-in, so that every
 * try of the game's says it again); otherwise one only where none waits (the other refused calls: a request's calls, all
 * refused at once, leave one notice, and each request after the notice was shown leaves the next). Never gets in the way
 * of the reply.
 */
function odq_ban_notice(int $guid, bool $again = true): void
{
    // The players this request left the notice for already: the other refused calls of the same request leave none, so
    // that a batch of a player's calls costs one write, not one a call.
    static $left = [];
    if (!$again && isset($left[$guid])) {
        return;
    }
    $left[$guid] = true;
    // Without $again, an update only of a row whose notice is not the ban's already (none waiting, or another kind).
    $only = $again ? '' : " WHERE LiveSwitch.toast IS NOT 'ban'";
    try {
        @odq_db()->exec("INSERT INTO LiveSwitch (guid, live, toast, toast_id) VALUES ($guid, 0, 'ban', 1)
                         ON CONFLICT (guid) DO UPDATE SET toast = 'ban', toast_id = LiveSwitch.toast_id + 1$only");
    } catch (Throwable $e) {
    }
}
