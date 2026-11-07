#!/bin/sh
# Prepares the database and the server's settings, then hands over to Apache.
set -eu

# The database on the data volume (the image names it).
DB=${OPENDMTQ_DB:-/data/dmtq.db3}
# api (default): the whole server. assets: a replica that only serves the static files (the Helm chart).
ROLE=${ROLE:-api}

# The address the game will be sent to; compose passes it from .env.
: "${PUBLIC_HOST:?PUBLIC_HOST is not set (run ./opendmtq setup)}"

# The writable folder for the settings made below and Apache's own files.
mkdir -p /var/opendmtq/run

# Without the client data the game cannot start (it downloads the images of its screens from here): say what to do. A
# server without songs works: the game starts with an empty song list.
if ! ls "${OPENDMTQ_CONTENT:-/srv/content}"/web/patch/phone_new/*/android/patch_new.csv.lz4 >/dev/null 2>&1; then
    echo "opendmtq: no client data yet; import it with ./opendmtq import <folder with your game files>"
elif [ ! -s "${OPENDMTQ_CONTENT:-/srv/content}/songs.json" ]; then
    echo "opendmtq: no songs yet; add them with ./opendmtq import --songs <folder> or on the admin pages"
fi

# The edge doors (8081 for plain HTTP, 8443 for decrypted HTTPS, opendmtq.conf) take each visitor's
# address from a PROXY protocol header, whoever sends it. They are for compose's edge proxy only:
# Kubernetes sets EDGE_DOORS=no, as its router uses 8080 and any pod of the cluster could reach the
# doors there and claim any address (or the HTTPS door's admin pages).
DOORS=/var/opendmtq/run/doors.conf
if [ "${EDGE_DOORS:-yes}" = no ]; then
    echo "# EDGE_DOORS=no: no edge proxy in front of this server, so only the 8080 door." > "$DOORS"
else
    echo "Define OPENDMTQ_EDGE_DOORS" > "$DOORS"
fi

# PHP's dates (the in-game ranking's day) follow TZ when it names a zone PHP knows (compose passes
# the host's zone); otherwise they stay in UTC, the default in php/opendmtq.ini. Read at Apache's
# start from a folder of extra settings next to the image's own.
PHP_EXTRA=/var/opendmtq/run/php
mkdir -p "$PHP_EXTRA"
rm -f "$PHP_EXTRA"/*.ini
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
if [ -n "${TZ:-}" ] && php -r 'exit(in_array(getenv("TZ"), timezone_identifiers_list(), true) ? 0 : 1);'; then
    echo "date.timezone = \"$TZ\"" > "$PHP_EXTRA/timezone.ini"
fi
export PHP_INI_SCAN_DIR="/usr/local/etc/php/conf.d:$PHP_EXTRA"

# The admin pages (/opendmtq/admin, and /admin, their address until 2026-11, which leads there) go to the admin service
# (compose service "admin", or a sidecar in Kubernetes).
PROXY=/var/opendmtq/run/admin-proxy.conf
rm -f "$PROXY"
# Exposed to the internet, the admin pages stay off the public port unless ADMIN_ON_PUBLIC_PORT=yes:
# they are reachable on this machine instead (compose publishes the admin service on loopback).
if [ -n "${ADMIN_URL:-}" ] && [ "${ADMIN_ON_PUBLIC_PORT:-yes}" = yes ]; then
    cat > "$PROXY" <<CONF
# The visitor's real address for the admin's sign-in throttle; any client-sent value is replaced.
RequestHeader set X-Real-IP "expr=%{REMOTE_ADDR}"
# Sign-in forms are tiny; uploads (songs, backups) go to their own pages.
<LocationMatch "^/(opendmtq/)?admin/login">
    LimitRequestBody 8192
</LocationMatch>
# disablereuse: a fresh connection (and name lookup) per request, so a re-created admin container
# with a new address is found again without restarting the server.
ProxyPass "/opendmtq/admin" "$ADMIN_URL/opendmtq/admin" timeout=900 disablereuse=On
ProxyPassReverse "/opendmtq/admin" "$ADMIN_URL/opendmtq/admin"
# Their address until 2026-11: the admin service answers it with a permanent redirect to the same page here.
ProxyPass "/admin" "$ADMIN_URL/admin" disablereuse=On
ProxyPassReverse "/admin" "$ADMIN_URL/admin"
CONF
fi

# The address phones use, split for the doors' own names (opendmtq.conf): the port is 80 when the
# address has none.
case "$PUBLIC_HOST" in
    *:*) OPENDMTQ_NAME=${PUBLIC_HOST%:*}; OPENDMTQ_PORT=${PUBLIC_HOST##*:} ;;
    *) OPENDMTQ_NAME=$PUBLIC_HOST; OPENDMTQ_PORT=80 ;;
esac
export OPENDMTQ_NAME OPENDMTQ_PORT

# The admin pages on the plain doors. With HTTPS working they go there, so the admin password never travels
# in clear; the edge ends HTTPS on the same port. Without HTTPS it is proxied as on the HTTPS door
# for a local network address, and refused for an internet one.
#
# Whether HTTPS works is decided per request, not now: the server follows the certificate and the
# edge without a restart. It counts as working while the authority's certificate is there
# (/srv/https/ca.crt, made by ./opendmtq up) and the edge has not said it runs without HTTPS
# (/srv/https/edge-plain, which an edge that fell back to plain HTTP leaves there).
# The portal's pages on the plain door: a browser that asks for them goes to HTTPS while it works (the same
# test per request as the admin pages below). Only pages a person reads, only GET and HEAD. The game's paths, /apk,
# /ca.crt (how a phone comes to trust HTTPS at all), the assets and the health check stay as they are, and
# so do apps' own browsers (the messengers by name, any other Android WebView by its "; wv)"): they may not offer a
# way past the certificate warning, so they would never reach the button that opens the page in a real browser.
# To the address that was asked for, not the public name: on the server's own network that name may not even lead here.
# With its port: HTTPS is on the same port, so a visit on port 80 (no port in the address) goes to https://host:80/ and not
# to 443, where nothing answers.
# Not on a local network address: it brings nothing there but a certificate warning on every new player's first visit,
# between them and the app. HTTPS still answers for whoever asks for it.
#
# On the Helm chart with router.tls (ROUTER_TLS=yes) the router ends HTTPS and says how each visit came, in a header
# only it sets (visitors reach this door through it). So there the test is that header, on the one door.
https_works='RewriteCond /srv/https/ca.crt -f
RewriteCond /srv/https/edge-plain !-f'
ROUTER_TLS_CONF=/var/opendmtq/run/router-tls.conf
rm -f "$ROUTER_TLS_CONF"
if [ "${ROUTER_TLS:-no}" = yes ]; then
    https_works='RewriteCond %{HTTP:X-Forwarded-Proto} =http'
    # shellcheck disable=SC2016  # Apache's own $1.
    cat > "$ROUTER_TLS_CONF" <<'CONF'
# The visit is HTTPS even though it reaches Apache decrypted: PHP sees so, and the admin session cookie stays on HTTPS.
SetEnvIfExpr "%{HTTP:X-Forwarded-Proto} == 'https'" HTTPS=on
Header always edit Set-Cookie "^(session=(?!.*;\s*Secure).*)$" "$1; Secure" "expr=%{HTTP:X-Forwarded-Proto} == 'https'"
Header onsuccess edit Set-Cookie "^(session=(?!.*;\s*Secure).*)$" "$1; Secure" "expr=%{HTTP:X-Forwarded-Proto} == 'https'"
CONF
fi
plain_pages() {
    cat <<PAGES
RewriteEngine On
$https_works
RewriteCond %{REQUEST_METHOD} ^(GET|HEAD)$
RewriteCond %{HTTP_USER_AGENT} !(KAKAOTALK|NAVER\\(inapp|\\bBAND\\b|Instagram|\\bLine/|FBAN|FBAV|FB_IAB|FB4A|;.wv\\)) [NC]
RewriteCond %{HTTP_HOST} !^(?:10\\.[0-9]+\\.[0-9]+\\.[0-9]+|192\\.168\\.[0-9]+\\.[0-9]+|172\\.(?:1[6-9]|2[0-9]|3[01])\\.[0-9]+\\.[0-9]+|127\\.[0-9]+\\.[0-9]+\\.[0-9]+|localhost)(?::|\$)
RewriteCond %{HTTP_HOST}:80 ^([^:]+:[0-9]+)
RewriteRule ^/(?:opendmtq/(?:(?:index|download|ranking|songs|song|player|live|login|licenses)\\.php)?)?\$ https://%1%{REQUEST_URI} [R=302,L]
PAGES
}
plain_pages > /var/opendmtq/run/plain-pages.conf
if [ "${ROUTER_TLS:-no}" = yes ]; then
    plain_pages >> "$ROUTER_TLS_CONF"
    # Apache's own redirect from /opendmtq to /opendmtq/ says http, as this door's name does, and a Header rule does not
    # reach it (it is made as an error reply). The one a person types, answered first, so a visit over HTTPS stays there.
    cat >> "$ROUTER_TLS_CONF" <<'CONF'
RewriteCond %{HTTP:X-Forwarded-Proto} =https
RewriteRule ^/opendmtq$ https://%{HTTP_HOST}/opendmtq/ [R=301,L]
CONF
fi
PLAIN_ADMIN=/var/opendmtq/run/plain-admin.conf
rm -f "$PLAIN_ADMIN"
if [ -f "$PROXY" ]; then
    case "$OPENDMTQ_NAME" in
        10.*|192.168.*|127.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*|localhost) lan=yes ;;
        *) lan=no ;;
    esac
    {
        # Sent to the HTTPS door while it works (a redirect answers before any access rule below).
        echo "$https_works"
        # The old address (/admin) straight to the new one there.
        echo "RewriteRule ^/(?:opendmtq/)?admin(/.*)?\$ https://$OPENDMTQ_NAME:$OPENDMTQ_PORT/opendmtq/admin\$1 [R=302,L]"
        if [ "$lan" = yes ] || [ "${ROUTER_TLS:-no}" = yes ]; then
            # Otherwise, on a local network address: proxied in clear, as it was before HTTPS. Behind the chart's
            # router this door also takes the visits it decrypted, which the line above lets through.
            echo "Include $PROXY"
        else
            # Otherwise, on an internet address: refused, with the ways in that still work.
            cat <<'CONF'
<LocationMatch "^/(opendmtq/)?admin(/|$)">
    Require all denied
    ErrorDocument 403 "The admin pages need HTTPS on this address, and it is not working. With Docker Compose, run ./opendmtq up (or ./opendmtq doctor) on the server PC, or open http://localhost:8791/opendmtq/admin/ there. In Kubernetes, use kubectl port-forward to port 8000 of the api pod and open http://localhost:8000/admin/."
</LocationMatch>
CONF
        fi
    } > "$PLAIN_ADMIN"
    if [ -f /srv/https/ca.crt ]; then
        echo "opendmtq: HTTPS on the public port too (own certificate); /opendmtq/admin over HTTPS only"
    fi
fi

# Log copy for the admin page (the folder may not exist on a fresh volume).
mkdir -p /data/logs 2>/dev/null || true

# The database: created on a first start, its journal mode picked for this disk, the tables and indexes later
# versions added, and repairs of what older versions or forged results left (game/bin/setup-db.php). Asset
# replicas never touch it.
if [ "$ROLE" = api ]; then
    php /opt/opendmtq/game/bin/setup-db.php "$DB"
fi

# The live view's window: nothing in it outlives a restart (a stream would have stopped anyway). The
# recordings stay, as links to the same files; ones a restart left open are closed by the sweep.
if [ "$ROLE" = api ]; then
    mkdir -p /data/live /data/live-rec 2>/dev/null && find /data/live -mindepth 1 -delete 2>/dev/null \
        || echo "opendmtq: could not prepare data/state/live; the live view cannot store video" >&2
fi

# The key that signs the download sign-in cookie (with the ID and the password), on the data volume
# so sign-ins survive restarts. A cookie seen on the network then no longer lets anyone test
# password guesses offline: they would need this key as well (portal/lib.php, dl_key()).
if [ "$ROLE" = api ] && [ ! -s /data/download.key ]; then
    (umask 077 && head -c 32 /dev/urandom | od -An -v -tx1 | tr -d ' \n' > /data/download.key.new \
        && mv /data/download.key.new /data/download.key) \
        || echo "opendmtq: could not write /data/download.key; nobody can sign in to the site until it can be written" >&2
fi

# One handle kept open for as long as the server runs. Every PHP request opens and closes its own, and
# in write-ahead mode the last handle to close folds the log into the database and removes it, waiting
# for the disk: a lone player's save then took as long as without the mode. With this one open that
# never happens on a close; SQLite folds the log in now and then during a commit instead. Should it
# die, requests still work, as slowly as before. Holds no read open, so it blocks nothing.
if [ "$ROLE" = api ]; then
    # shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
    php -r '
        $db = new SQLite3($argv[1]);
        $db->busyTimeout(5000);
        @$db->querySingle("SELECT 1 FROM sqlite_master LIMIT 1");
        while (true) {
            sleep(86400);
        }
    ' "$DB" &
fi

echo "opendmtq: $ROLE serving http://$PUBLIC_HOST/ as uid $(id -u)"

# Apache (or the command compose passed) becomes PID 1.
exec docker-php-entrypoint "$@"
