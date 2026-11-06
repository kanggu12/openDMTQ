<?php
/*
 * The user.* methods (logging in, nicknames, the transfer code that moves a player to another phone), and the
 * three small services the client asks at its start: board (news), memo (mail) and service (where everything is).
 */

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/db.php';
require_once __DIR__ . '/game.php';

/*
 * user.loginV2 [accessToken, nickName, profileImg, version, os, area]: the game's own login, right after the
 * platform login (platform.php) gave the client an access token "<puid>|576|<device>|<server>|<token>|<time>".
 * The token's puid names the account; an unknown one gets a new account here. The reply gives the client its
 * player id (guid) and the key it signs its requests with.
 */
function odq_user_login(array $p)
{
    // The token's six parts; missing ones read as null.
    $parts = explode('|', odq_text($p[0] ?? null));
    $puid = $parts[0];
    $token = $parts[4] ?? null;
    $time = $parts[5] ?? null;
    $member = odq_member_by('puid', $puid);
    $guid = $member ? (string)$member['guid'] : '';
    // An account the platform login did not make (an old token, a test): made now, with the puid as its guid.
    if ($guid === '' || $guid === '0') {
        $db = odq_db();
        $id = (int)$db->querySingle('SELECT MAX(id) + 1 FROM Member') ?: 1;
        $q = $db->prepare("INSERT INTO Member (id, nickname, guid, puid, code) VALUES (:id, 'NewUser', :puid, :puid, :code)");
        $q->bindValue(':id', $id, SQLITE3_INTEGER);
        $q->bindValue(':puid', $puid, SQLITE3_TEXT);
        // The transfer code a player can type on another phone (user.setConnectUuid).
        $q->bindValue(':code', substr(md5("CODE_$id"), -10), SQLITE3_TEXT);
        @$q->execute();
        $guid = $puid;
    }
    return [
        // Made from the token, as the official server made it; nothing checks it later.
        'API_TOKEN' => strtoupper(substr(md5((string)$token) . md5((string)$time), -58)),
        'SECRET_KEY' => OPENDMTQ_SECRET_KEY,
        'SECRET_VER' => '1',
        // Text here, a number everywhere else: the shape the client reads.
        'guid' => $guid,
        'recom_code' => 'AAAAAA',
        'displayName' => $p[1] ?? null,
        'profileImg' => $p[2] ?? null,
        'INTRO_SERVER' => odq_base() . 'DMQ/rpc',
    ];
}

/* user.getConnectUuid [guid, os]: the player's transfer code, to type on another phone (OPTION, CONNECT ACCOUNT). */
function odq_user_transfer_code(array $p)
{
    $member = odq_member_by('guid', $p[0] ?? null);
    $code = $member ? (string)$member['code'] : '';
    if ($code === '' || $code === '0') {
        return odq_no_account();
    }
    return ['status' => 'SUCCESS', 'code' => 200, 'uuid' => $code, 'result_msg' => 'OK'];
}

/*
 * user.getUsersByPuid [[puid], [field]]: one field of a player by puid; the client asks for display_name. A single
 * space for a player the server does not know, as the official server answered.
 */
function odq_user_by_puid(array $p)
{
    $puid = is_array($p[0] ?? null) ? ($p[0][0] ?? null) : null;
    $field = is_array($p[1] ?? null) ? ($p[1][0] ?? null) : null;
    $member = odq_member_by('puid', $puid);
    return [[odq_text($field) => $member ? $member['nickname'] : ' ']];
}

/* user.setNickname [guid, nickName]: the name the player picks; on every row of the player. */
function odq_user_set_nickname(array $p)
{
    $q = @odq_db()->prepare('UPDATE Member SET nickname = :n WHERE guid = :g');
    if ($q) {
        $q->bindValue(':n', $p[1] ?? null, odq_sqlite_type($p[1] ?? null));
        $q->bindValue(':g', $p[0] ?? null, odq_sqlite_type($p[0] ?? null));
        @$q->execute();
    }
    return true;
}

/*
 * user.setConnectUuid [guid, code, os]: a transfer code typed on this phone (OPTION, RESTORE DATA): the phone's
 * player becomes the code's player. Every row of the phone's guid then points at that player, so the phone's
 * next login plays as them.
 */
function odq_user_use_transfer_code(array $p)
{
    $owner = odq_member_by('code', $p[1] ?? null);
    $found = $owner ? (string)$owner['guid'] : '';
    if ($found === '' || $found === '0') {
        return odq_no_account();
    }
    $q = @odq_db()->prepare('UPDATE Member SET guid = :found WHERE guid = :g');
    if ($q) {
        $q->bindValue(':found', $found, SQLITE3_TEXT);
        $q->bindValue(':g', $p[0] ?? null, odq_sqlite_type($p[0] ?? null));
        @$q->execute();
    }
    return ['status' => 'SUCCESS', 'code' => 200, 'result_msg' => 'OK'];
}

/*
 * board.getNoticeList [code, fromNewsId, limit]: news banners for the lobby. The official server's banners are not
 * this server's to show, so the one entry here has no picture and leads nowhere. One there must be: the client turns
 * the list into an array of entries and closes when the list is empty (an empty JSON list has no element it could
 * take the type from; InvalidCastException in WebResponseProcessor.getNoticeList).
 */
function odq_board_news(array $p)
{
    return [['news_id' => 1, 'link_url' => '', 'image_url' => '', 'content' => '0', 'news_type' => 'N']];
}

/* memo.getMemoList [guid, fromMemoId, limit]: in-game mail. None. */
function odq_memo_list(array $p)
{
    return [];
}

/*
 * service.getInfo [version, clientOS]: the first call of every start, before the login: where the RPC, the
 * client's data (patch folder) and the in-game web page are. No terms popup, no coupon row.
 */
function odq_service_info(array $p)
{
    return [
        'api_url' => odq_base() . 'DMQ/rpc',
        'file_server_url' => odq_base() . 'patch',
        // One old client version has its own, older data folder.
        'file_manage_ver' => ($p[0] ?? null) === OPENDMTQ_OLD_CLIENT ? OPENDMTQ_OLD_PATCH_ID : odq_patch_id(),
        'service_type' => 'LIVE',
        'coupon_yn' => 'N',
        'terms_yn' => 'N',
        'pp_live_status' => 'Y',
        'inspection_notice_yn' => 'N',
        'event_url' => odq_base() . 'score/',
    ];
}
