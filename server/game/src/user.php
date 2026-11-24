<?php
/*
 * The user.* methods (logging in, nicknames, the transfer code that moves a player to another phone), and the
 * three small services the client asks at its start: board (news), memo (mail) and service (where everything is).
 */

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/db.php';
require_once __DIR__ . '/game.php';
require_once __DIR__ . '/signin.php';
require_once __DIR__ . '/account.php';

/*
 * user.loginV2 [accessToken, nickName, profileImg, version, os, area]: the game's own login, right after the
 * platform login (platform.php) gave the client an access token "<puid>|576|<device>|<server>|<token>|<time>".
 * Only a token the platform login handed out for that account is taken (signin.php); the game's code it does not know
 * (SVC.05401) answers any other, which opens its own popup, whose CLOSE ends the game: the next start signs in anew.
 * The token's puid names the account; an unknown one gets a new account here. The reply gives the client its player id
 * (guid) and the key it signs its requests with, a key of this sign-in's own.
 */
function odq_user_login(array $p)
{
    // The token's six parts; missing ones read as null.
    $access = odq_text($p[0] ?? null);
    $parts = explode('|', $access);
    $puid = $parts[0];
    $token = $parts[4] ?? null;
    $time = $parts[5] ?? null;
    if ($puid === '' || !odq_sign_in_known($access, $puid)) {
        return odq_error('SVC.05401', 'OpenDMTQ: this server did not hand out this sign-in');
    }
    $member = odq_member_by('puid', $puid);
    $guid = $member ? (string)$member['guid'] : '';
    // No account for the token's puid (the owner deleted the player after the platform login): made now, with the puid as
    // its guid.
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
    // The key this sign-in signs with, kept with it (signin.php): the signature then tells this player's game.
    $key = odq_sign_in_key($access, odq_intval($guid));
    if ($key === null) {
        // The database did not take it: the code the client offers to retry, as for a save it did not take.
        error_log('opendmtq: loginV2: ' . odq_db()->lastErrorMsg());
        return odq_error('SVC.05099', 'OpenDMTQ: the sign-in could not be kept; try again');
    }
    return [
        // Made from the token, as the official server made it; the game sends it back in a header nothing reads (proxies
        // drop a header named with an underscore): the signature's key tells a sign-in.
        'API_TOKEN' => strtoupper(substr(md5((string)$token) . md5((string)$time), -58)),
        'SECRET_KEY' => $key,
        'SECRET_VER' => '1',
        // Text here, a number everywhere else: the shape the client reads.
        'guid' => $guid,
        'recom_code' => 'AAAAAA',
        'displayName' => $p[1] ?? null,
        'profileImg' => $p[2] ?? null,
        'INTRO_SERVER' => odq_base() . 'DMQ/rpc',
    ];
}

/*
 * user.getConnectUuid [guid, os]: the player's transfer code, to type on another phone (OPTION, CONNECT ACCOUNT). Taken
 * only from the player's own game (signin.php). A code made from the account's number (a database restored from a backup
 * of before, until the next start replaces it: account.php) is never handed out: the account gets a random one in its
 * place first.
 */
function odq_user_transfer_code(array $p)
{
    $member = odq_member_by('guid', $p[0] ?? null);
    $code = $member ? (string)$member['code'] : '';
    if ($code === '' || $code === '0') {
        return odq_no_account();
    }
    if (odq_code_from_number($code, $member)) {
        $db = odq_db();
        $new = odq_new_code($db);
        // On the very row it was read from, and only while it still holds that code (another request may have replaced it).
        $w = @$db->prepare('UPDATE Member SET code = :new WHERE rowid = (SELECT rowid FROM Member WHERE guid = :g AND code = :old ORDER BY rowid LIMIT 1)');
        if ($w) {
            $w->bindValue(':new', $new, SQLITE3_TEXT);
            $w->bindValue(':g', $member['guid'], SQLITE3_TEXT);
            $w->bindValue(':old', $code, SQLITE3_TEXT);
        }
        if (!$w || !@$w->execute()) {
            // Not kept (the disk full): the code the game offers to retry, never the old one.
            error_log('opendmtq: getConnectUuid: ' . $db->lastErrorMsg());
            return odq_error('SVC.05099', 'OpenDMTQ: the transfer code could not be kept; try again');
        }
        // The code the account holds now: this one, or the one another request wrote first.
        $member = odq_member_by('guid', $p[0] ?? null);
        $code = $member ? (string)$member['code'] : '';
        if ($code === '' || odq_code_from_number($code, $member)) {
            return odq_no_account();
        }
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

/* user.setNickname [guid, nickName]: the name the player picks; on every row of the player. Taken only from the player's
   own game (signin.php). */
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
 * user.setConnectUuid [guid, code, os]: a transfer code typed on this phone (OPTION, the transfer code's input): the
 * phone's player becomes the code's player. Every row of the phone's guid then points at that player, so the phone's next
 * login, after the restart the game makes at once, plays as them. Taken only from the phone's own game, for its own player
 * (signin.php), and only with a code the code's owner was shown: never one made from that account's number (account.php),
 * which anyone could work out.
 */
function odq_user_use_transfer_code(array $p)
{
    // A phone's own player: a call that names nobody moves nobody.
    if (odq_intval($p[0] ?? null) <= 0) {
        return odq_no_account();
    }
    $owner = odq_member_by('code', $p[1] ?? null);
    $found = $owner ? (string)$owner['guid'] : '';
    if ($found === '' || $found === '0' || odq_code_from_number($owner['code'], $owner)) {
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
