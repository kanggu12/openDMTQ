<?php
/*
 * The game.* methods: a player's assets and scores, the song and chart addresses, saving a play, and the
 * fixed answers for features this server does not run (advertising tickets, migrations from older editions).
 * The rankings are in ranking.php and the achievements in achievement.php; rpc.php names every method.
 *
 * Every handler takes the call's parameter list (the JSON list the game sent, missing values read as null)
 * and returns the call's result, or an OdqReply for an error. The reply shapes are the client's: its
 * response classes and their JSON names (client 1.3.4).
 */

require_once __DIR__ . '/db.php';
require_once __DIR__ . '/content.php';
require_once __DIR__ . '/util.php';
require_once __DIR__ . '/achievement.php';

/*
 * A call's result and error, for the replies that are not a plain result: an error (result null, error with its
 * code and message) or, once, neither.
 */
final class OdqReply
{
    public $result;
    public $error;

    public function __construct($result, $error)
    {
        $this->result = $result;
        $this->error = $error;
    }
}

/* An error reply: the client reads the code (see rpc.php for the codes it knows). */
function odq_error(string $code, string $message): OdqReply
{
    return new OdqReply(null, ['code' => $code, 'message' => $message]);
}

/* The error for a player id the server has no account for. The client's own message names the platform's id. */
function odq_no_account(): OdqReply
{
    return odq_error('SVC.05001', 'Error (Invalid pmangplus(member_id) user id)');
}

/* game.checkKakao2Global, checkPmang2Global, checkOld2Global [puid]: is there a player of an older edition to bring over? Never. */
function odq_game_check_migration(array $p)
{
    return false;
}

/* game.getAdSongList [guid]: songs unlocked by watching an advertisement. None: every song is free here. */
function odq_game_ad_songs(array $p)
{
    return ['status' => 200, 'message' => 'Ad song list', 'info' => ['songList' => []]];
}

/* game.getAdTicketChecked [guid]: the player's advertisement ticket. None; the guid comes back as it was sent. */
function odq_game_ad_ticket_checked(array $p)
{
    return ['status' => 200, 'message' => 'Check Ad ticket info',
            'info' => ['ticket' => ['guid' => $p[0] ?? null, 'song_id' => 0, 'has_ticket' => 'N', 'reg_date' => '20170101000000']]];
}

/* game.getAdTicketRequest [guid, songId]: the player starts an advertisement for a ticket. Granted at once. */
function odq_game_ad_ticket_request(array $p)
{
    return ['status' => 200, 'message' => 'I am watching ad movie', 'info' => ['has_ticket' => true, 'state' => 'S']];
}

/* game.getAdTicketReceived [guid, songId]: the advertisement ended and the ticket is the player's. */
function odq_game_ad_ticket_received(array $p)
{
    return ['status' => 200, 'message' => 'I got a ticket to play', 'info' => ['has_ticket' => true, 'state' => 'Y']];
}

/* game.getAdTicketUsed [guid, songId]: the ticket was spent on a play. */
function odq_game_ad_ticket_used(array $p)
{
    return ['status' => 200, 'message' => 'I used to play', 'info' => ['ticket' => ['use_ticket' => true, 'state' => 'N']]];
}

/*
 * game.getDefaultSetting []: settings the client reads at its start, as key and value pairs, all text. The two
 * "how to play" pages are images the client fetches from the server: offered only when the content has them.
 */
function odq_game_default_setting(array $p)
{
    // The two pages of the "how to play" popup and two banners of old screens, as the official server named them.
    $play = 'static/dmq/banner/180802_tuto2_package/howtoplay_play.png';
    $note = 'static/dmq/banner/180802_tuto2_package/howtoplay_note.png';
    $tstop = 'static/dmq/banner/180716_mucasummer/180716_tstop_summer.png';
    $twc = 'static/dmq/banner/180716_mucasummer/180716_twc_summer.png';
    // Without the images the popup would show two empty pages: it is not offered then.
    $howto = odq_served_file($play) && odq_served_file($note) ? 'Y' : 'N';
    $pairs = [
        '1' => '1',
        'gamesuggest_popup' => 'N',
        'howtoplay_page1' => odq_base() . $play,
        'howtoplay_page2' => odq_base() . $note,
        'howtoplay_popup' => $howto,
        'tstop_url' => odq_base() . $tstop,
        'twc_url' => odq_base() . $twc,
    ];
    $list = [];
    foreach ($pairs as $key => $value) {
        // The key "1" must stay text: PHP turns a numeric array key into a number.
        $list[] = ['key' => (string)$key, 'value' => $value];
    }
    return ['defaultKeyValue' => $list];
}

/* game.getFirstResourceSongList []: the song a phone downloads on its very first start. None without songs. */
function odq_game_first_resource_songs(array $p)
{
    $song = odq_first_song();
    return ['first_resource_songs' => $song ? [['song_id' => (int)$song['song_id'], 'name' => (string)($song['name'] ?? '')]] : []];
}

/*
 * game.getGameAssetByPuid [puid]: what a player of an older edition would bring over. Everyone has everything
 * here; song_count is the highest song id the server has (at least 1).
 */
function odq_game_asset_by_puid(array $p)
{
    $puid = $p[0] ?? null;
    return ['status' => 'SUCCESS', 'code' => 200, 'myAssetInfo' => [
        // The puid as text, the guid as a number: the shapes the client reads.
        'puid' => odq_text($puid), 'guid' => odq_intval($puid),
        'exp' => 99999, 'mpoint' => 999999, 'score' => 9999999, 'lev' => 99,
        'amt_total' => 999999, 'amt_cash' => 999999, 'amt_point' => 999999,
        'song_count' => max(1, odq_max_song_id()), 'migrated_yn' => 'Y',
    ]];
}

/* game.getGameAssetForMigByToken [guid, copy]: bring a player over with a token. There is nothing to bring. */
function odq_game_asset_for_migration(array $p)
{
    return odq_no_account();
}

/* game.getGameSettingInfo [key]: one setting by name. The client asks for the level above which HARD and EXPERT warn. */
function odq_game_setting_info(array $p)
{
    return ['status' => 200, 'code' => 200, 'message' => 'FOUND THE KEY', 'info' => ['key' => 'HARDEXPERT_ALERT_LEVEL', 'value' => 4]];
}

/* game.getLineScoreMyRank [guid, songId, line]: the client's old ranking call without levels. Unranked. */
function odq_game_old_my_rank(array $p)
{
    return ['rank' => 0];
}

/* game.getLineScoreRange [songId, line, fromRank, range]: the old ranking call without levels. Empty. */
function odq_game_old_rank_range(array $p)
{
    return ['scores' => []];
}

/*
 * game.getPatternUsePointData []: the charts that cost MAX POINT to open, and what they cost. From the client's
 * own chart table (catalog.json, written by the tools from the operator's tables); none without it.
 */
function odq_game_point_charts(array $p)
{
    return ['getPatternUsePointData' => array_values(odq_catalog()['point_charts'])];
}

/* game.getOwnItemList [guid]: an older item call the client no longer makes; shop.getOwnItemList is the real one. */
function odq_game_own_items(array $p)
{
    return [];
}

/*
 * game.getOwnPatternScore [guid]: the player's best on every chart they played (MAX SCORE, the marks on the song
 * list), by chart id. judgement is the accuracy in percent: 872 tenths give 87.2, 1000 give 100.
 */
function odq_game_own_pattern_scores(array $p)
{
    $guid = $p[0] ?? null;
    $rows = [];
    $q = @odq_db()->prepare('SELECT pattern_id, score, grade, isAllCombo, isPerfectPlay, judgement FROM Play WHERE user_id = :g ORDER BY pattern_id');
    if (!$q) {
        return $rows;
    }
    $q->bindValue(':g', $guid, odq_sqlite_type($guid));
    $r = @$q->execute();
    while ($r && ($row = $r->fetchArray(SQLITE3_ASSOC))) {
        $rows[] = [
            // The guid comes back as it was sent (number or text).
            'guid' => $guid,
            'pattern_id' => $row['pattern_id'],
            'score' => $row['score'],
            'judgement_name' => $row['grade'],
            'allcom_yn' => $row['isAllCombo'],
            'perfect_yn' => $row['isPerfectPlay'],
            // PHP's division gives an int when it is exact (98) and a float otherwise (87.2), as the client reads it.
            'judgement' => (int)$row['judgement'] / 10,
        ];
    }
    return $rows;
}

/*
 * game.getOwnQuestList [guid]: the player's quests (weekly and repeated missions). This server runs none: the
 * quests and their texts were the official server's, and nothing would ever complete them.
 */
function odq_game_own_quests(array $p)
{
    return ['period_quest' => null, 'repeat_quest' => null, 'level_quest' => null];
}

/*
 * game.getOwnSongList [guid]: the songs the player owns. Everyone owns everything: every id from 1 to the highest
 * song id, so that a song added later is owned at once too.
 */
function odq_game_own_songs(array $p)
{
    return ['song_ids' => range(1, max(1, odq_max_song_id()))];
}

/* game.getPatternUrl [guid, patternId, earphoneMode, deviceType]: where a chart's file is. "e" asks for the earphone timing. */
function odq_game_pattern_url(array $p)
{
    return odq_base() . 'DMQ/Patterns/' . odq_text($p[1] ?? null) . (($p[2] ?? null) === 'e' ? '_EARPHONE' : '');
}

/*
 * game.getPreviewPlayInfo [guid, patternId]: what a play starts with, asked when the player presses START: the
 * equipped items' effects (fever plus, gauge refill and anti break at their highest level for everyone) and a
 * token for the play, which the result sends back and nothing checks.
 */
function odq_game_preview_play(array $p)
{
    $now = time();
    return [
        'note_count' => 3,
        'slot_item_effect' => [
            'slot_item1' => null,
            'slot_item2' => null,
            // The text item id is what the client reads here.
            'slot_item3' => ['item_id' => '90008', 'effect_type' => 'N', 'effect_point' => 1, 'effect_count' => 1, 'effect_special' => ''],
        ],
        'in_game_item' => [
            'in_game_item1' => ['item_type' => 'FP', 'item_level' => 10, 'product_id' => 70020,
                                'item_effects' => [['item_id' => 70020, 'effect_type' => 'F', 'effect_point' => 5, 'effect_count' => 3, 'effect_special' => '']]],
            'in_game_item2' => ['item_type' => 'GR', 'item_level' => 10, 'product_id' => 70030,
                                'item_effects' => [['item_id' => 70030, 'effect_type' => 'G', 'effect_point' => 100, 'effect_count' => 1, 'effect_special' => '']]],
            'in_game_item3' => ['item_type' => 'AB', 'item_level' => 10, 'product_id' => 70010,
                                'item_effects' => [['item_id' => 70010, 'effect_type' => 'A', 'effect_point' => 12, 'effect_count' => 10, 'effect_special' => 'JUDGEMENT_MAX100']]],
        ],
        // 36 hex characters, like the official server's tokens: one per second is enough for a token nobody checks.
        'game_token' => md5((string)$now) . substr(md5((string)($now + 1)), -4),
        'freepass' => false,
    ];
}

/* game.getSongList []: every song the server offers, as the list has it (hidden ones marked hidden_yn Y). */
function odq_game_song_list(array $p)
{
    return ['songs' => odq_songs()];
}

/* game.getSongUrl [guid, songId, clientOS, version]: where a song's music and video are, for both stores' builds. */
function odq_game_song_url(array $p)
{
    $id = odq_text($p[1] ?? null);
    $files = [odq_base() . "DMQ/Songs/$id/$id.fpk", odq_base() . "DMQ/Songs/$id/$id.webm"];
    return ['pmang' => $files, 'amazon' => $files];
}

/*
 * game.getUserAsset [guid]: the player's level, points and equipped items. Everyone is level 99 with every MAX
 * POINT and every in-game item at level 10; the equipped items are the player's own (game.setSlotItem).
 */
function odq_game_user_asset(array $p)
{
    $member = odq_member_by('guid', $p[0] ?? null);
    // A stored NULL stays null; no account at all reads as nothing equipped.
    $slot = function ($n) use ($member) {
        return $member ? $member["slot_item$n"] : 0;
    };
    return [
        'exp' => 0, 'mpoint' => 999999, 'score' => 9999999,
        'slot_item1' => $slot(1), 'slot_item2' => $slot(2), 'slot_item3' => $slot(3), 'slot_item4' => $slot(4),
        'in_game_item1' => 10, 'in_game_item2' => 10, 'in_game_item3' => 10, 'lev' => OPENDMTQ_LEVEL,
        // Text here, numbers in getGameAssetByPuid: the shapes the client reads.
        'amt_total' => '999999', 'amt_cash' => '999999', 'amt_point' => '999999', 'amt_mileage' => '999999',
    ];
}

// The most notes of one judgement a save may count: far more than any chart has (a long one has a few thousand), so that
// no real play is refused, and few enough that the score of a save stays far inside what the client reads.
const OPENDMTQ_NOTES_MAX = 10000;

/*
 * True when a save's parameters describe a play: a player, a chart and the 12 counts of judged notes the score is made
 * of, each a whole number from 0 to OPENDMTQ_NOTES_MAX, at least one note in all. The client always sends that. Anything
 * else is no play and would store one nobody made: negative breaks gave an S at 100 %, a count of 1e308 a score of 0
 * with PERFECT PLAY; and the accuracy divides by the number of notes.
 */
function odq_save_valid($guid, $pattern, $stat): bool
{
    if (!is_numeric($guid) || (int)$guid <= 0 || !is_numeric($pattern) || (int)$pattern <= 0 || !is_array($stat)) {
        return false;
    }
    // The 12 counters the score is made of, 1 to 12; all there.
    $notes = 0;
    for ($i = 1; $i <= 12; $i++) {
        // An int, as JSON gives a whole number: a float (1e308, 0.5) or a text counts no notes.
        if (!isset($stat[$i]) || !is_int($stat[$i]) || $stat[$i] < 0 || $stat[$i] > OPENDMTQ_NOTES_MAX) {
            return false;
        }
        $notes += $stat[$i];
    }
    return $notes > 0;
}

/*
 * True when the server has an account for the player id, false when it has none, null when the database could not say.
 * Only a player with an account is ever ranked: a save for anyone else would be kept for nobody.
 */
function odq_account_known(int $guid): ?bool
{
    $q = @odq_db()->prepare('SELECT 1 FROM Member WHERE guid = :g LIMIT 1');
    if (!$q) {
        return null;
    }
    // As text, as the column holds the id.
    $q->bindValue(':g', (string)$guid, SQLITE3_TEXT);
    $r = @$q->execute();
    // A failed read is no answer: the caller must not take it for "no account".
    return $r ? $r->fetchArray(SQLITE3_NUM) !== false : null;
}

/*
 * True when the request that brings a save says the play was made with the keyboard: the PC client's player sends
 * X-OpenDMTQ-Keys: 1 with the save when any lane key was pressed during that song, and no such header otherwise; a phone
 * never sends it. Only the value 1 marks a play. The mark is kept with the play and its best (game.savePlayResult) for
 * the site and the admin pages to show; nothing the game reads, its rankings among them, depends on it.
 */
function odq_save_by_keys(): bool
{
    // Apache gives each header of the request as HTTP_ and its name in capitals, its dashes as underscores.
    return trim((string)($_SERVER['HTTP_X_OPENDMTQ_KEYS'] ?? '')) === '1';
}

/*
 * The reply for a save the database did not take. A code the client does not know opens its "retry?" popup
 * (see rpc.php), which sends the same result again: the score is not lost as long as the player retries,
 * instead of being shown as saved and gone.
 */
function odq_save_failed(): OdqReply
{
    return odq_error('SVC.05099', 'OpenDMTQ: the result could not be saved; try again');
}

/*
 * game.savePlayResult [guid, patternId, judgementStat, maxCombo, luckyBonus, effector, ingameItem, gameToken]:
 * the end of a play. judgementStat counts the notes by judgement: index 1 the breaks, 2 the 1 % judgement, 3 to
 * 12 the 10 % to 100 % ones. The score and the accuracy are worked out here from those counts, as the official
 * server did; the best of each per chart is kept (Play), every play is logged (PlayLog), and the reply names the
 * achievements the play earned. A play the request marks as made with the keyboard (odq_save_by_keys()) is marked on
 * its log row, and on the best row when it sets the best score; a new best by touch clears the mark again. The reply
 * is the same either way.
 */
function odq_game_save_play(array $p)
{
    [$guid, $pattern, $s] = [$p[0] ?? null, $p[1] ?? null, $p[2] ?? null];
    if (!odq_save_valid($guid, $pattern, $s)) {
        // Handled by the client without a popup: the result screen goes on, nothing is stored.
        return odq_error('SVC.05008', 'OpenDMTQ: game.savePlayResult is not available on this server');
    }
    $guid = (int)$guid;
    $pattern = (int)$pattern;
    // A chart no song of this server has, imported or added: no play on this server, and the month's TOTAL would count
    // it. A hidden song's charts are the server's (the list keeps a hidden song, marked hidden), so that a play finished
    // while the owner hid its song is kept. The list's charts are read once a request: the achievements below read them too.
    if (!isset(odq_chart_kinds()[$pattern])) {
        return odq_error('SVC.05008', 'OpenDMTQ: no song of this server has this chart; the result is not stored');
    }
    $known = odq_account_known($guid);
    // A player the server has no account for (an id made up, or a player the owner deleted): handled the same way.
    if ($known === false) {
        return odq_error('SVC.05008', 'OpenDMTQ: no player has this id on this server; the result is not stored');
    }
    // The database could not say: the code the client retries, as when the database does not take the save (below).
    if ($known === null) {
        error_log('opendmtq: savePlayResult: ' . odq_db()->lastErrorMsg());
        return odq_save_failed();
    }
    // Points per judgement, 1 % to 100 %: the notes' share of the score.
    $raw = $s[2] * 1 + $s[3] * 20 + $s[4] * 40 + $s[5] * 60 + $s[6] * 80 + $s[7] * 100 + $s[8] * 120
         + $s[9] * 140 + $s[10] * 160 + $s[11] * 180 + $s[12] * 200;
    // ALL COMBO: no break at all (the integer 0, as the client sends it). PERFECT PLAY: every note at 100 %.
    $allCombo = $s[1] === 0;
    $perfect = true;
    for ($i = 1; $i <= 11; $i++) {
        $perfect = $perfect && $s[$i] === 0;
    }
    $bonus = ($allCombo ? 15000 : 0) + ($perfect ? 30000 : 0);
    $total = $raw + $bonus;
    // The accuracy in tenths of a percent: the points won against the most a play of these notes can win.
    $maxPoint = ($s[1] + $s[2] + $s[3] + $s[4] + $s[5] + $s[6] + $s[7] + $s[8] + $s[9] + $s[10] + $s[11] + $s[12]) * 100;
    $nowPoint = ($raw - $s[2]) / 2 + $s[2];
    $ratio = (int)floor($nowPoint / $maxPoint * 1000);
    // The grade from the accuracy before it is capped.
    $grade = $ratio >= 980 ? 'S' : ($ratio >= 900 ? 'A' : ($ratio >= 800 ? 'B' : ($ratio >= 700 ? 'C' : ($ratio >= 600 ? 'D' : ($ratio >= 500 ? 'E' : 'F')))));
    // What may be stored: the client reads 32-bit numbers, and an accuracy is at most 100 %.
    $total = odq_clamp_score($total);
    $ratio = odq_clamp($ratio, 0, 1000);
    // What the player held before this play, to tell what it earns.
    $had = odq_achievement_ids($guid);
    // Whether this play was made with the keyboard, as the request says: 1 or 0, the column's values.
    $keys = odq_save_by_keys() ? 1 : 0;

    $db = odq_db();
    // The best row and the log row together or not at all, waiting out other writers (busy timeout).
    if (!@$db->exec('BEGIN IMMEDIATE')) {
        error_log('opendmtq: savePlayResult: ' . $db->lastErrorMsg());
        return odq_save_failed();
    }
    // The player's best on this chart so far.
    $q = $db->prepare('SELECT score FROM Play WHERE pattern_id = :p AND user_id = :g');
    $q->bindValue(':p', $pattern, SQLITE3_INTEGER);
    $q->bindValue(':g', $guid, SQLITE3_INTEGER);
    $r = @$q->execute();
    $row = $r ? $r->fetchArray(SQLITE3_ASSOC) : false;
    $last = $row ? $row['score'] : null;
    $first = $last === null;
    $record = $first || $total > $last;
    if ($first) {
        // The first play on the chart is its best: its keyboard mark with it.
        $w = $db->prepare('INSERT INTO Play (pattern_id, user_id, score, grade, isAllCombo, isPerfectPlay, judgement, keys)
                           VALUES (:p, :g, :score, :grade, :combo, :perfect, :ratio, :keys)');
    } else {
        // Every expression sees the old row: the score and the accuracy keep their best, the grade follows the best
        // accuracy, and the two marks only ever turn on. The keyboard's mark follows the best score: the mark of the play
        // that beats it (one by touch clears it), the old one's while no play does (a tie keeps the play that got there first).
        $w = $db->prepare("UPDATE Play SET score = max(score, :score), judgement = max(judgement, :ratio),
                           grade = CASE WHEN :ratio > judgement THEN :grade ELSE grade END,
                           isAllCombo = CASE WHEN isAllCombo = 'N' THEN :combo ELSE isAllCombo END,
                           isPerfectPlay = CASE WHEN isPerfectPlay = 'N' THEN :perfect ELSE isPerfectPlay END,
                           keys = CASE WHEN :score > score THEN :keys ELSE keys END
                           WHERE pattern_id = :p AND user_id = :g");
    }
    $stored = false;
    if ($w) {
        $w->bindValue(':p', $pattern, SQLITE3_INTEGER);
        $w->bindValue(':g', $guid, SQLITE3_INTEGER);
        $w->bindValue(':score', $total, SQLITE3_INTEGER);
        $w->bindValue(':grade', $grade, SQLITE3_TEXT);
        $w->bindValue(':combo', $allCombo ? 'Y' : 'N', SQLITE3_TEXT);
        $w->bindValue(':perfect', $perfect ? 'Y' : 'N', SQLITE3_TEXT);
        $w->bindValue(':ratio', $ratio, SQLITE3_INTEGER);
        $w->bindValue(':keys', $keys, SQLITE3_INTEGER);
        // A second save of the same first play at the same moment is refused by the index Play_one.
        $stored = @$w->execute() !== false;
    }
    // Every play is logged, for the monthly rankings and the achievements' dates; a failure here loses no score. With
    // the keyboard's mark: the site marks the play itself, and the month's best when this play set it.
    $l = @$db->prepare('INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at, keys)
                        VALUES (:g, :p, :score, :grade, :ratio, :record, :at, :keys)');
    if ($l) {
        $l->bindValue(':g', $guid, SQLITE3_INTEGER);
        $l->bindValue(':p', $pattern, SQLITE3_INTEGER);
        $l->bindValue(':score', $total, SQLITE3_INTEGER);
        $l->bindValue(':grade', $grade, SQLITE3_TEXT);
        $l->bindValue(':ratio', $ratio, SQLITE3_INTEGER);
        $l->bindValue(':record', $record ? 1 : 0, SQLITE3_INTEGER);
        $l->bindValue(':at', time(), SQLITE3_INTEGER);
        $l->bindValue(':keys', $keys, SQLITE3_INTEGER);
        @$l->execute();
    }
    // Kept only when the best row was written and the commit works; otherwise nothing of it.
    if (!$stored || !@$db->exec('COMMIT')) {
        error_log('opendmtq: savePlayResult: ' . $db->lastErrorMsg());
        @$db->exec('ROLLBACK');
        return odq_save_failed();
    }
    return [
        'is_success' => true,
        'is_first_pattern' => $first,
        'is_new_record' => $record,
        'judgement_name' => $grade,
        'allcom_yn' => $allCombo ? 'Y' : 'N',
        'perfect_yn' => $perfect ? 'Y' : 'N',
        'bonus_score' => $bonus,
        // The official server gave 300 points per lucky bonus; the score here never included them.
        'lucky_bonus_score' => 0,
        'score' => $total,
        'total_score' => $total,
        'exp' => 10,
        'total_exp' => 10,
        'mpoint' => 150,
        'total_mpoint' => 150,
        'lev' => OPENDMTQ_LEVEL,
        // What this play earned, shown by the game at once; always a list.
        'new_achievements' => odq_new_achievements($guid, $had),
        // No quests run here (game.getOwnQuestList), so none completes or goes on.
        'own_quests' => [
            'complete' => ['period_quest' => null, 'level_quest' => null, 'repeat_quest' => null],
            'going' => ['period_quest' => null, 'level_quest' => null, 'repeat_quest' => null],
        ],
    ];
}

/* game.savePlayResultFailLog [guid, patternId, gameToken, logType]: a play that failed or was given up. Nothing is kept. */
function odq_game_save_fail_log(array $p)
{
    return ['status' => true];
}

/*
 * game.setSlotItem [guid, slotItem1, slotItem2, slotItem3, slotItem4]: the partner, skin and note items the player
 * equips. Stored on every row of the player (a transfer code can give a player two); an empty slot is stored as
 * NULL. The reply gives the four values back as they were sent.
 */
function odq_game_set_slots(array $p)
{
    $q = @odq_db()->prepare('UPDATE Member SET slot_item1 = :s1, slot_item2 = :s2, slot_item3 = :s3, slot_item4 = :s4 WHERE guid = :g');
    if ($q) {
        for ($n = 1; $n <= 4; $n++) {
            $value = $p[$n] ?? null;
            // 0, "0", "", false and null all mean an empty slot.
            $q->bindValue(":s$n", $value ?: null, $value ? odq_sqlite_type($value) : SQLITE3_NULL);
        }
        $q->bindValue(':g', $p[0] ?? null, odq_sqlite_type($p[0] ?? null));
        @$q->execute();
    }
    return ['slot_item1' => $p[1] ?? null, 'slot_item2' => $p[2] ?? null, 'slot_item3' => $p[3] ?? null, 'slot_item4' => $p[4] ?? null];
}
