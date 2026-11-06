<?php
/*
 * Where everything is and what the game is told: one place for the addresses, folders and constants every
 * part of the game server reads. Everything comes from the environment, so the same code runs in the
 * container (the defaults below are its paths), on a host install and under Windows (their start scripts
 * set the variables).
 */

// The key the game signs its requests with: the login reply hands it to the client (user.loginV2), which
// then sends md5(key + body) in an Fp header. Any value works as long as the server checks the one it gave.
const OPENDMTQ_SECRET_KEY = 'DMQGLBlive1';
// The client patch folder version phones download from when the content has none of its own.
const OPENDMTQ_PATCH_ID = '1.003.005';
// The older patch folder, for the one old client version that asks for it (service.getInfo).
const OPENDMTQ_OLD_PATCH_ID = '1.000.030';
// The client version that gets the older patch folder.
const OPENDMTQ_OLD_CLIENT = '1.0.17';
// The account the server's own check (./opendmtq check) logs in with; never ranked, as on the web.
const OPENDMTQ_CHECK_UDID = 'opendmtq-check';

/*
 * One setting from the environment, $default when it is not set. Apache passes the variables named in
 * site.conf (PassEnv); the command line scripts see the process environment.
 */
function odq_env(string $name, string $default): string
{
    // getenv() with true reads the real environment first, then Apache's own.
    $value = getenv($name, true);
    // Apache's variables are only visible without the flag.
    if ($value === false) {
        $value = getenv($name);
    }
    // Unset or empty: the default.
    return ($value === false || $value === '') ? $default : $value;
}

/* The address phones use, host and port as in PUBLIC_HOST ("192.168.0.2:8790", or a name without a port for 80). */
function odq_host(): string
{
    return odq_env('PUBLIC_HOST', '127.0.0.1');
}

/* The base of every address the server hands out. The game always speaks plain HTTP. */
function odq_base(): string
{
    return 'http://' . odq_host() . '/';
}

/* The imported content (songs, charts, jackets, the client's tables), read only. Empty on a server without songs. */
function odq_content_dir(): string
{
    return rtrim(odq_env('OPENDMTQ_CONTENT', '/srv/content'), '/');
}

/* What the admin pages add over the content (added songs, rebuilt tables, the song list, the maintenance notice). */
function odq_custom_dir(): string
{
    return rtrim(odq_env('OPENDMTQ_CUSTOM', '/srv/custom'), '/');
}

/* The server's own writable folder: the database, the live view's streams and recordings, the logs, keys. */
function odq_state_dir(): string
{
    return rtrim(odq_env('OPENDMTQ_STATE', '/data'), '/');
}

/* The database file every part of the server shares. */
function odq_db_path(): string
{
    return odq_env('OPENDMTQ_DB', odq_state_dir() . '/dmtq.db3');
}

/*
 * Where the builder puts the phone app (the site's download offers it): OPENDMTQ_APK_OUT where it is not the image's
 * mount (the Helm chart, a host install), APK_DIR in charts from before 2026-11. (OPENDMTQ_APK is the tools' name for
 * all of data/apk.)
 */
function odq_apk_dir(): string
{
    return rtrim(odq_env('OPENDMTQ_APK_OUT', odq_env('APK_DIR', '/srv/apk')), '/');
}

/* The server's scratch files (the download sign-in throttle): the image's writable tree, a host install's run folder. */
function odq_run_dir(): string
{
    return rtrim(odq_env('OPENDMTQ_RUN', '/var/opendmtq/run'), '/');
}

/* The server's own certificate authority for HTTPS (ca.crt is offered to phones; the key never leaves). */
function odq_https_dir(): string
{
    return rtrim(odq_env('OPENDMTQ_HTTPS', '/srv/https'), '/');
}

/*
 * The song list the server offers: the admin's merged list (the imported songs, the added ones, which are
 * hidden), written by the tools at every start; before the first of those, the imported list itself.
 */
function odq_song_list_path(): string
{
    $custom = odq_custom_dir() . '/songList.json';
    return is_file($custom) ? $custom : odq_content_dir() . '/songs.json';
}

/*
 * The patch folder version the server announces: the newest one the content or the admin's tables have
 * (a folder phone_new/<version>/android with a manifest in it), else the default.
 */
function odq_patch_id(): string
{
    // Once per request: the folders do not change while it runs.
    static $id = null;
    if ($id !== null) {
        return $id;
    }
    $found = [];
    // The admin's rebuilt tables first, then the imported ones; both use the same layout.
    foreach ([odq_custom_dir() . '/web', odq_content_dir() . '/web'] as $root) {
        foreach (glob($root . '/patch/phone_new/*/android/patch_new.csv.lz4') ?: [] as $manifest) {
            // The version is the folder two levels above the manifest.
            $found[] = basename(dirname($manifest, 2));
        }
    }
    // Versions compare as numbers part by part (1.003.005 > 1.000.030).
    usort($found, 'version_compare');
    $id = $found ? end($found) : OPENDMTQ_PATCH_ID;
    return $id;
}

/*
 * A file the server serves, looked up as Apache looks it up: the admin's overlay first, then the content.
 * $path is the URL path without its leading slash. Null when neither has it.
 */
function odq_served_file(string $path): ?string
{
    foreach ([odq_custom_dir() . '/web/', odq_content_dir() . '/web/'] as $root) {
        if (is_file($root . $path)) {
            return $root . $path;
        }
    }
    return null;
}
