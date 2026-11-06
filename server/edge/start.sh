#!/bin/sh
# Starts the edge proxy. With a certificate (data/https/serve, made by ./opendmtq up) it also ends
# HTTPS; without one it passes everything to the server's plain door, so the game keeps working.
set -eu
here=/etc/opendmtq/edge
if [ -r /etc/opendmtq/https/server.crt ] && [ -r /etc/opendmtq/https/server.key ]; then
    # nginx refuses to start with a certificate it cannot use (a key that belongs to another one,
    # after a renewal cut off half-way; an empty file after a full disk), and the public port, the
    # game's plain HTTP included, would be gone with it. Test first; nginx prints why it refuses.
    if nginx -t -q -c "$here/nginx.conf"; then
        # The server sends the admin pages' plain visits to HTTPS only while this marker is absent.
        rm -f /etc/opendmtq/state/edge-plain 2>/dev/null || true
        exec nginx -c "$here/nginx.conf" -g "daemon off;"
    fi
    echo "edge: the certificate in data/https/serve cannot be used (see above), plain HTTP only; ./opendmtq up makes a new one" >&2
else
    echo "edge: no certificate in data/https/serve, plain HTTP only (./opendmtq up makes one)" >&2
fi
# No HTTPS door: the server must not send the admin pages' plain visits there (it reads this as /srv/https/edge-plain).
touch /etc/opendmtq/state/edge-plain 2>/dev/null || echo "edge: cannot write data/https/public/edge-plain: the server will keep sending browsers to an HTTPS door that is not there" >&2
exec nginx -c "$here/plain.conf" -g "daemon off;"
