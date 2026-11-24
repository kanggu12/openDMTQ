<?php
/*
 * The kind of device an account plays on, as the platform's login notes it for the owner's Accounts page (src/device.php):
 * tests/game/protocol.sh runs this inside the throwaway server, after the contract, on its database, at its own address.
 *
 *   - the kind each User-Agent names: the player for Windows' own (its build named OpenDMTQ), a phone's game (Android's
 *     HTTP clients), and nothing for the server's own check or a script;
 *   - a platform login as the player for Windows sends it, then one as a phone sends it, for two new devices: each
 *     account's kind noted in PlayerDevice, and none for a login that names no kind.
 *
 * Usage: php tests/game/device.php <database file> <base address of the server>      (exit status 0 when every check passed)
 */

// The server's own code: the image's, or a host install's (OPENDMTQ_APP names its server/ folder).
$app = getenv('OPENDMTQ_APP') ?: '/opt/opendmtq';
require_once "$app/game/src/config.php";
require_once "$app/game/src/device.php";
[$_, $path, $base] = $argv;

// One line per check, as protocol.py prints them; the count of failures decides the exit status.
$failures = 0;
function check(string $name, bool $ok, string $detail = ''): void
{
    global $failures;
    if (!$ok) {
        $failures++;
    }
    echo ($ok ? 'PASS ' : 'FAIL ') . $name . ($detail !== '' && !$ok ? " | $detail" : '') . "\n";
}

// The agents as each client sends them: the player for Windows' (arm32/desktop/http.cpp), a phone's game's (made up, in
// Android's own form), the server's own check's (./opendmtq check) and a script's.
const PC_AGENT = 'Dalvik/2.1.0 (Linux; U; Android 9; OpenDMTQ Build/PQ3A)';
const PHONE_AGENT = 'Dalvik/2.1.0 (Linux; U; Android 13; SM-A000N Build/TP1A.220624.014)';
check('SRV-112 the kind of device each agent names: the PC, a phone, and none for the check or a script',
    odq_device_kind(PC_AGENT) === 'pc' && odq_device_kind(PHONE_AGENT) === 'android' && odq_device_kind('opendmtq') === ''
    && odq_device_kind('curl/8.5.0') === '', implode(' ', array_map('odq_device_kind', [PC_AGENT, PHONE_AGENT, 'opendmtq', 'curl/8.5.0'])));

/* A platform login of a new device ($udid) with the agent given, as the SDK sends it: the account's puid, or ''. */
function login(string $base, string $udid, string $agent): string
{
    $context = stream_context_create(['http' => ['method' => 'POST', 'ignore_errors' => true, 'timeout' => 15,
        'header' => "Content-Type: application/x-www-form-urlencoded\r\nUser-Agent: $agent\r\n", 'content' => "udid=$udid"]]);
    $reply = json_decode((string)@file_get_contents("$base/api/accounts/v3/global/login_dmq", false, $context), true);
    return (string)explode('|', (string)($reply['value']['access_token'] ?? ''))[0];
}

$stamp = getmypid() . '-' . time();
$pc = login($base, "device-pc-$stamp", PC_AGENT);
$phone = login($base, "device-phone-$stamp", PHONE_AGENT);
$script = login($base, "device-script-$stamp", 'curl/8.5.0');
$db = new SQLite3($path, SQLITE3_OPEN_READONLY);
$db->busyTimeout(5000);
$kind = function (string $puid) use ($db): ?string {
    $q = @$db->prepare('SELECT kind FROM PlayerDevice WHERE puid = :p');
    if (!$q) {
        return null;
    }
    $q->bindValue(':p', $puid, SQLITE3_TEXT);
    $row = $q->execute()->fetchArray(SQLITE3_NUM);
    return $row ? $row[0] : null;
};
check('SRV-112 the platform login notes the kind of device each account signs in from, and none it does not name',
    $pc !== '' && $phone !== '' && $script !== '' && $kind($pc) === 'pc' && $kind($phone) === 'android' && $kind($script) === null,
    json_encode([$pc => $kind($pc), $phone => $kind($phone), $script => $kind($script)]));
$db->close();

exit($failures > 0 ? 1 : 0);
