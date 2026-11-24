<?php
/*
 * The kind of device each account plays on, for the owner's Accounts page: its list of the players an account can be
 * linked to names each with its device and its last play, where every new player is NewUser. Noted at each platform login
 * (platform.php) from the login's User-Agent, in the login's own transaction; the newest kind of an account is kept.
 */

require_once __DIR__ . '/db.php';

// The table, as the platform's login makes it where it is not (a database from before it, or restored): one row per
// account (its puid), the kind of device it last signed in from and when.
const OPENDMTQ_DEVICE_TABLE = 'CREATE TABLE IF NOT EXISTS PlayerDevice (puid TEXT PRIMARY KEY, kind TEXT NOT NULL, at INTEGER NOT NULL)';

/*
 * The kind of device a login's User-Agent names: "pc" for the player for Windows (its own agent names OpenDMTQ's build),
 * "android" for a phone's or a tablet's game (Android's HTTP clients), '' for anything else (the server's own check, a
 * script), which is not noted.
 */
function odq_device_kind(string $agent): string
{
    if (strpos($agent, 'OpenDMTQ Build/') !== false) {
        return 'pc';
    }
    return preg_match('/Android|Dalvik|okhttp|UnityPlayer/i', $agent) ? 'android' : '';
}

/*
 * Notes the kind of device the account $puid signs in from ($agent: the login's User-Agent), in the caller's transaction
 * on $db. Nothing for an agent that names no kind; a database that does not take it leaves the login as it is (the list
 * then shows no device for the account until its next start).
 */
function odq_device_note(SQLite3 $db, string $puid, string $agent): void
{
    $kind = odq_device_kind($agent);
    if ($kind === '' || !@$db->exec(OPENDMTQ_DEVICE_TABLE)) {
        return;
    }
    $w = @$db->prepare('INSERT OR REPLACE INTO PlayerDevice (puid, kind, at) VALUES (:p, :k, :now)');
    if (!$w) {
        return;
    }
    $w->bindValue(':p', $puid, SQLITE3_TEXT);
    $w->bindValue(':k', $kind, SQLITE3_TEXT);
    $w->bindValue(':now', time(), SQLITE3_INTEGER);
    @$w->execute();
}
