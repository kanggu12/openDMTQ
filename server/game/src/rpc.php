<?php
/*
 * The game's RPC (POST /DMQ/rpc): a JSON list of calls in, a JSON list of results out, one per call and in the
 * same order. A call is {"id": .., "method": "<prefix>.<action>", "params": [..]}; its result goes back as
 * {"result": .., "error": .., "id": <the call's id>}.
 *
 * Errors the client knows: with an error the client skips the method's own handler. SVC.05008 it treats as
 * handled (no popup, the screen goes on); any other code opens its "retry?" popup, whose other button quits the
 * game. SVC.001 means "update required" to it and makes it quit: never sent. The client reads a missing list as
 * null and stops, so every list in a reply is present, even when empty.
 */

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/game.php';
require_once __DIR__ . '/shop.php';
require_once __DIR__ . '/user.php';
require_once __DIR__ . '/ranking.php';
require_once __DIR__ . '/achievement.php';
require_once __DIR__ . '/live.php';

/*
 * Every method this server answers, by its name in lower case (the game sends them in camel case; the name is
 * matched whatever its case). Anything else gets SVC.05008: the client goes on without it. So does what client 1.3.5
 * adds for FREE PASS, a time pass sold for real money: game.getUserFreePass, asked at every sign-in, leaves the client
 * with no pass, and every song is free here anyway; shop.buyFreePass and the purchase check shop.checkPurchasePayId
 * follow a Google Play purchase, which never happens here.
 */
function odq_methods(): array
{
    return [
        'game.checkkakao2global' => 'odq_game_check_migration',
        'game.checkpmang2global' => 'odq_game_check_migration',
        'game.checkold2global' => 'odq_game_check_migration',
        'game.getachievementcount' => 'odq_achievement_count',
        'game.getadsonglist' => 'odq_game_ad_songs',
        'game.getadticketchecked' => 'odq_game_ad_ticket_checked',
        'game.getadticketrequest' => 'odq_game_ad_ticket_request',
        'game.getadticketreceived' => 'odq_game_ad_ticket_received',
        'game.getadticketused' => 'odq_game_ad_ticket_used',
        'game.getdefaultsetting' => 'odq_game_default_setting',
        'game.getfirstresourcesonglist' => 'odq_game_first_resource_songs',
        'game.getgameassetbypuid' => 'odq_game_asset_by_puid',
        'game.getgameassetformigbytoken' => 'odq_game_asset_for_migration',
        'game.getgamesettinginfo' => 'odq_game_setting_info',
        'game.getlinescoremyrank' => 'odq_game_old_my_rank',
        'game.getlinescorerange' => 'odq_game_old_rank_range',
        'game.getlinescorerangewithlevel' => 'odq_song_rank_range',
        'game.getlinetoprankwithlevel' => 'odq_line_top_rank',
        'game.getlinescoremyrankwithnext' => 'odq_song_my_rank_with_next',
        'game.getlinescoremyrankwithlevel' => 'odq_song_my_rank',
        'game.getpatternusepointdata' => 'odq_game_point_charts',
        'game.getownachievementlist' => 'odq_own_achievements',
        'game.getownitemlist' => 'odq_game_own_items',
        'game.getownpatternscore' => 'odq_game_own_pattern_scores',
        'game.getownquestlist' => 'odq_game_own_quests',
        'game.getownsonglist' => 'odq_game_own_songs',
        'game.getpatternurl' => 'odq_game_pattern_url',
        'game.getpreviewplayinfo' => 'odq_game_preview_play',
        'game.getsonglist' => 'odq_game_song_list',
        'game.getsongurl' => 'odq_game_song_url',
        'game.getuserasset' => 'odq_game_user_asset',
        'game.saveplayresult' => 'odq_game_save_play',
        'game.saveplayresultfaillog' => 'odq_game_save_fail_log',
        'game.setslotitem' => 'odq_game_set_slots',
        'shop.buyfreeproduct' => 'odq_shop_buy_free',
        'shop.buyproductbyqpoint' => 'odq_shop_buy_with_points',
        'shop.getpackageinfobyguid' => 'odq_shop_packages',
        'shop.getproductforunlock' => 'odq_shop_unlock_product',
        'shop.getownitemlist' => 'odq_shop_own_items',
        'shop.getunlockedproductlist' => 'odq_shop_unlocked',
        'shop.upgradeingameitem' => 'odq_shop_upgrade_item',
        'shop.usecoupon' => 'odq_shop_use_coupon',
        'user.getconnectuuid' => 'odq_user_transfer_code',
        'user.getusersbypuid' => 'odq_user_by_puid',
        'user.loginv2' => 'odq_user_login',
        'user.setnickname' => 'odq_user_set_nickname',
        'user.setconnectuuid' => 'odq_user_use_transfer_code',
        'board.getnoticelist' => 'odq_board_news',
        'memo.getmemolist' => 'odq_memo_list',
        'service.getinfo' => 'odq_service_info',
    ];
}

/* A method's name as it is matched: lower case, without the leading backslashes PHP would ignore in a class name. */
function odq_method_key($method): string
{
    return is_string($method) ? ltrim(strtolower($method), '\\') : '';
}

/*
 * The game signs each request: an Fp header with md5(secret key + body), the key being the one the login reply
 * gave it. It is checked for what cannot be undone by a look at the rankings: saving a play and the shop. That
 * stops anything that merely posts to the address, not someone who has read the app and knows the key, and it
 * leaves health checks and other reads open. One such call makes the whole batch need the signature.
 */
function odq_signature_ok(string $body, $calls): bool
{
    if (!is_array($calls)) {
        return true;
    }
    $sensitive = false;
    foreach ($calls as $call) {
        $method = is_array($call) && isset($call['method']) ? odq_method_key($call['method']) : '';
        if (strpos($method, 'game.saveplayresult') === 0 || strpos($method, 'shop.') === 0) {
            $sensitive = true;
        }
    }
    if (!$sensitive) {
        return true;
    }
    // Header names arrive in any case; PHP gives them as HTTP_FP.
    $given = isset($_SERVER['HTTP_FP']) ? strtolower((string)$_SERVER['HTTP_FP']) : '';
    return hash_equals(md5(OPENDMTQ_SECRET_KEY . $body), $given);
}

/* The reply for a method this server does not have; the message only shows in the phone's log, next to the code. */
function odq_unknown_method($method): OdqReply
{
    $name = is_string($method) ? $method : '?';
    return odq_error('SVC.05008', "OpenDMTQ: $name is not available on this server");
}

/* One call: its handler's result as {result, error}, never an exception. */
function odq_call($method, $params): array
{
    $handler = odq_methods()[odq_method_key($method)] ?? null;
    // A parameter list that is not a list counts as an empty one: every value then reads as missing.
    $list = is_array($params) ? array_values($params) : [];
    try {
        $reply = $handler ? $handler($list) : odq_unknown_method($method);
    } catch (Throwable $e) {
        // A fault here must not cost the rest of the batch: logged, and answered like an unknown method.
        error_log("opendmtq: $method: " . $e->getMessage());
        $reply = odq_unknown_method($method);
    }
    if ($reply instanceof OdqReply) {
        return ['result' => $reply->result, 'error' => $reply->error];
    }
    return ['result' => $reply, 'error' => null];
}

/*
 * The whole request: [HTTP status, JSON body]. A bad signature refuses the batch before any call runs. A body that
 * is not a list of calls (empty, not JSON) gets an empty list back.
 */
function odq_rpc(string $body): array
{
    $data = json_decode($body, true);
    if (!odq_signature_ok($body, $data)) {
        return [403, '[]'];
    }
    // Nothing to do: an empty body, a body that is not JSON, an empty list.
    if (!$data) {
        return [200, '[]'];
    }
    // A single value instead of a list (a number, a text) is one call nobody can answer.
    if (!is_array($data)) {
        return [200, json_encode([['result' => null, 'error' => odq_unknown_method(null)->error, 'id' => null]])];
    }
    $out = [];
    // By position: a JSON object instead of a list has no call at position 0, 1, ..., and each of its places
    // answers as an unknown call without an id.
    $count = count($data);
    for ($i = 0; $i < $count; $i++) {
        $call = $data[$i] ?? null;
        $id = is_array($call) ? ($call['id'] ?? null) : null;
        $method = is_array($call) ? ($call['method'] ?? null) : null;
        $params = is_array($call) ? ($call['params'] ?? null) : null;
        // The live view follows who is in a song by these very calls (live.php); it never changes a reply.
        odq_live_seen($method, $params);
        $reply = odq_call($method, $params);
        $out[] = ['result' => $reply['result'], 'error' => $reply['error'], 'id' => $id];
    }
    return [200, odq_json_list($out)];
}

/*
 * The replies as the JSON the client reads. A stored text that is no UTF-8 (a player's name in the database of an older
 * server, which bin/setup-db.php writes as UTF-8 at the next start) goes out with U+FFFD in place of each bad byte:
 * json_encode() would otherwise give false, an empty body for every phone whose ranking lists that name. Anything else
 * JSON cannot hold (a number that is not finite) goes out as null or 0 instead of the whole batch, and is logged.
 */
function odq_json_list(array $out): string
{
    $json = json_encode($out, JSON_INVALID_UTF8_SUBSTITUTE | JSON_PARTIAL_OUTPUT_ON_ERROR);
    // Said once per batch: what JSON could not hold, for the owner to find in the server's log.
    if (json_last_error() !== JSON_ERROR_NONE) {
        error_log('opendmtq: rpc: part of a reply could not be written as JSON: ' . json_last_error_msg());
    }
    // False only past json_encode()'s nesting limit, which no reply comes near; even then the client gets a list.
    return $json === false ? '[]' : $json;
}
