<?php
/*
 * What the game's platform SDK asks (the pmangplus "Neon SDK" inside the app): its login, which makes the
 * player's account, and a handful of reports and lookups that only need to succeed. Every reply is the SDK's
 * JsonResult shape: {"value": .., "result_code": "000", "result_msg": "API_OK"}.
 */

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/db.php';

/* The SDK's plain success. */
const OPENDMTQ_API_OK = ['value' => true, 'result_code' => '000', 'result_msg' => 'API_OK'];

/* Sends a reply: its status, its type and its body. */
function odq_send(int $status, string $type, string $body, array $headers = []): void
{
    http_response_code($status);
    header("Content-Type: $type");
    foreach ($headers as $header) {
        header($header);
    }
    echo $body;
}

/*
 * A form body as the official server read it: split on & and =, the values left as they came (not URL-decoded),
 * so that a device id is stored exactly as the phone sent it. A part without = has a null value.
 */
function odq_raw_form(string $body): array
{
    $form = [];
    foreach (explode('&', $body) as $part) {
        $pair = explode('=', $part, 3);
        $form[$pair[0]] = $pair[1] ?? null;
    }
    return $form;
}

/*
 * POST /api/accounts/v3/global/login_dmq (the Android SDK) and /accounts/v3/global/login_dmq (the old iOS SDK and
 * ./opendmtq check): the platform login. The phone's device id (udid) is its account: a new one gets a new
 * account, in one transaction so that two phones starting together never share one. The reply's access token
 * carries the account's puid, which the game's own login (user.loginV2) then reads.
 *
 * $old: the /accounts path, whose transfer codes and reply text differ slightly, as they always have.
 */
function odq_platform_login(string $body, bool $old): void
{
    $udid = odq_text(odq_raw_form($body)['udid'] ?? '');
    $db = odq_db();
    $puid = null;
    try {
        if (!@$db->exec('BEGIN IMMEDIATE')) {
            throw new RuntimeException($db->lastErrorMsg());
        }
        $q = $db->prepare('SELECT puid FROM Member WHERE udid = :u ORDER BY rowid LIMIT 1');
        $q->bindValue(':u', $udid, SQLITE3_TEXT);
        $row = $q->execute()->fetchArray(SQLITE3_ASSOC);
        if ($row) {
            $puid = (string)$row['puid'];
        } else {
            // A new account: the next number, which is its puid and its guid too.
            $id = (int)$db->querySingle('SELECT MAX(id) + 1 FROM Member') ?: 1;
            $w = $db->prepare("INSERT INTO Member (id, nickname, guid, puid, udid, code) VALUES (:id, ' ', :p, :p, :u, :c)");
            $w->bindValue(':id', $id, SQLITE3_INTEGER);
            $w->bindValue(':p', (string)$id, SQLITE3_TEXT);
            $w->bindValue(':u', $udid, SQLITE3_TEXT);
            // The transfer code (user.getConnectUuid); the old path's never had the underscore.
            $w->bindValue(':c', substr(md5(($old ? 'CODE' : 'CODE_') . $id), -10), SQLITE3_TEXT);
            if (!$w->execute()) {
                throw new RuntimeException($db->lastErrorMsg());
            }
            $puid = (string)$id;
        }
        if (!@$db->exec('COMMIT')) {
            throw new RuntimeException($db->lastErrorMsg());
        }
    } catch (Throwable $e) {
        // Never a token for an account that was not saved: the SDK tries again a moment later.
        @$db->exec('ROLLBACK');
        error_log('opendmtq: platform login: ' . $e->getMessage());
        odq_send(503, 'application/json', '{"result_code":"503","result_msg":"SERVER_BUSY"}', ['Retry-After: 1']);
        return;
    }
    // The token's random part and the times, in milliseconds as the SDK reads them.
    $random = '';
    for ($i = 0; $i < 40; $i++) {
        $random .= '0123456789abcdef'[random_int(0, 15)];
    }
    $t = time() . '000';
    $token = "$puid|576|IPHONE|KR|$random|$t";
    if ($old) {
        // The old SDK's reply, on one line, as the official server sent it.
        $reply = '{"value":{"access_token":"' . $token . '","member":{"crt_dt":' . $t . ',"upd_dt":' . $t . ',"status_cd":"OK","member_id":' . $puid
            . ',"nickname":"NewUser","profile_img_url":"","feeling":null,"adult_auth_yn":"N","adult_auth_dt":null,"recent_login_dt":' . $t
            . ',"recent_app_id":null,"email":null,"anonymous_yn":"N","reg_path":"GAMECENTER","recent_app_title":null,"last_msg_dt":null,'
            . '"new_msg_yn":null,"friend_accept_cd":"MANUAL","achieve_detail_info_list":null,"member_achievement_summary":null,'
            . '"conflict_member_id":null,"reg_ip":"127.0.0.1","reg_nation":"US","is_guest_login":true,"provider_display_name":"",'
            . '"pushgroup":null,"locale":null,"sanction":false,"profile_img_url_raw":""},"conflict_member_id":null,"is_guest_login":true,'
            . '"old_member_id":null,"jailbreak_yn":"N","unreg_status":"NO","callTime":0},"result_code":"000","result_msg":"API_OK"}';
    } else {
        // The Android SDK's reply, laid out as the official server sent it.
        $reply = "{\n        \"value\":{\n            \"access_token\":\"$token\",\n            \"member\":{\n"
            . "                \"crt_dt\":$t,\n                \"upd_dt\":$t,\n                \"status_cd\":\"OK\",\n"
            . "                \"member_id\":$puid,\n                \"nickname\":\"NewUser\",\n                \"profile_img_url\":\"\",\n"
            . "                \"feeling\":null,\n                \"adult_auth_yn\":\"N\",\n                \"adult_auth_dt\":null,\n"
            . "                \"recent_login_dt\":$t,\n                \"recent_app_id\":null,\n                \"email\":null,\n"
            . "                \"anonymous_yn\":\"N\",\n                \"reg_path\":\"GAMECENTER\",\n                \"recent_app_title\":null,\n"
            . "                \"last_msg_dt\":null,\n                \"new_msg_yn\":null,\n                \"friend_accept_cd\":\"MANUAL\",\n"
            . "                \"conflict_member_id\":null,\n                \"reg_ip\":\"127.0.0.1\",\n                \"reg_nation\":\"HK\",\n"
            . "                \"is_guest_login\":false,\n                \"provider_display_name\":\"\",\n                \"pushgroup\":null,\n"
            . "                \"locale\":null,\n                \"sanction\":false,\n                \"profile_img_url_raw\":\"\"\n"
            . "            },\n            \"conflict_member_id\":null,\n            \"is_guest_login\":false,\n"
            . "            \"old_member_id\":null,\n            \"jailbreak_yn\":\"N\",\n            \"unreg_status\":\"NO\",\n"
            . "            \"callTime\":0\n        },\n        \"result_msg\":\"API_OK\",\n        \"result_code\":\"000\"\n    }";
    }
    odq_send(200, 'text/html; charset=UTF-8', $reply);
}

/*
 * POST /api/gcm/576/register/2: the SDK registers the phone for push messages at every start. This server sends
 * none; the SDK only needs the registration to succeed. It stores c2dm_notification_yn as the phone's "push
 * allowed" setting, so the phone's own choice comes back.
 */
function odq_platform_push(): void
{
    $allow = (($_POST['notification_yn'] ?? 'N') === 'Y') ? 'Y' : 'N';
    odq_send(200, 'application/json', json_encode(['value' => ['register' => true, 'c2dm_notification_yn' => $allow,
        'subscription' => [], 'unsubscription' => []], 'result_code' => '000', 'result_msg' => 'API_OK']));
}

/*
 * POST /api/product/app/576 (and the old SDK's /product/app/576 and /product/vcash/576): the app's price list.
 * The SDK waits for a list with something in it and stays on its loading screen otherwise; nothing is sold here,
 * so the list is one product that is not on sale.
 */
function odq_platform_prices(): void
{
    $product = [
        'crt_dt' => 1387175024000, 'upd_dt' => 1387175024000, 'app_id' => 576, 'product_id' => 781, 'app_cash_id' => 528,
        'currency' => 'WWW', 'price_org' => 0, 'price_vat' => 0, 'inapp_id' => 'opendmtq.free', 'product_name' => 'OpenDMTQ',
        'product_detail' => 'Everything is free on this server', 'product_category' => null, 'product_disp_price' => null,
        'sale_start_dt' => null, 'sale_end_dt' => null, 'std_price_org' => 0, 'std_price_vat' => 0, 'sale_price_org' => null,
        'sale_price_vat' => null, 'use_type' => 'NONCONSUMABLE', 'use_count' => null, 'use_period' => null, 'display_yn' => 'Y',
        'bo_display_yn' => 'Y', 'first_pay_yn' => 'N', 'pay_type' => 'CASH', 'moshop_id' => null, 'mopoint_amt' => null,
        'track_id' => null, 'on_sale' => 'N',
    ];
    odq_send(200, 'text/html; charset=UTF-8', json_encode(['value' => [$product], 'result_msg' => 'API_OK', 'result_code' => '000'],
        JSON_UNESCAPED_UNICODE));
}

/*
 * GET /inspection/status.json: the SDK's maintenance check. The admin pages' Maintenance page writes its own file
 * in the overlay, which Apache serves first; without one, no maintenance. The misspelt resulr_msg is the SDK's.
 */
function odq_platform_inspection(): void
{
    odq_send(200, 'application/json', json_encode(['value' => ['open_yn' => 'N', 'disable_apps' => [], 'non_kill_apps' => [],
        'noti_url' => odq_base() . 'inspection/noti.html'], 'result_code' => '000', 'resulr_msg' => 'API_OK']));
}

/*
 * Answers a platform path, whatever the HTTP method (the SDK posts most of them); false when $path is none of them.
 * The SDK's reports (analytics, transaction logs, referrer) need only an OK, its lookups (rooted apps, banners) an
 * empty list.
 */
function odq_platform(string $path, string $body): bool
{
    // The two logins.
    if (preg_match('#^/api/accounts/v3/global/login_dmq(?:\.php)?$#', $path)) {
        odq_platform_login($body, false);
        return true;
    }
    if (preg_match('#^/accounts/v3/global/login_dmq(?:\.php)?$#', $path)) {
        odq_platform_login($body, true);
        return true;
    }
    if (preg_match('#^/api/gcm/576/register/2(?:\.php)?$#', $path)) {
        odq_platform_push();
        return true;
    }
    if (preg_match('#^/(?:api/)?product/(?:app|vcash)/576(?:\.php)?$#', $path)) {
        odq_platform_prices();
        return true;
    }
    if (preg_match('#^/inspection/status\.json$#', $path)) {
        odq_platform_inspection();
        return true;
    }
    // The device report (and its iOS and referrer forms), the Google Play logout, the iOS push registration.
    if (preg_match('#^/(?:api/)?members/analytics(?:/.*)?$|^/api/accounts/v2/sns/2/logout(?:\.php)?$|^/api/apns/576/register/2(?:\.php)?$#', $path)) {
        odq_send(200, 'application/json', json_encode(OPENDMTQ_API_OK));
        return true;
    }
    if (preg_match('#^/api/referrer/save(?:\.php)?$#', $path)) {
        odq_send(200, 'text/html; charset=UTF-8', '{"value":"OK","result_code":"000","result_msg":"API_OK"}');
        return true;
    }
    if (preg_match('#^/api/resource/rooting_app\.json$#', $path)) {
        odq_send(200, 'application/json', '{"value":[],"result_msg":"API_OK","result_code":"000"}');
        return true;
    }
    if (preg_match('#^/apps/576/banners(?:\.php)?$#', $path)) {
        odq_send(200, 'application/json', '{"value":[],"result_code":"000","result_msg":"API_OK"}');
        return true;
    }
    // The SDK's transaction and latency logs: kept nowhere.
    if (preg_match('#^/api/logstash/send/(?:transaction|latency)(?:\.php)?$#', $path)) {
        odq_send(200, 'text/html; charset=UTF-8', '');
        return true;
    }
    return false;
}
