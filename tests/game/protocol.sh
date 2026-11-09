#!/usr/bin/env bash
# The game server's contract with the game (tests/game/protocol.py) on a throwaway server: builds the server image from
# this working tree, makes the stand-in game files of the pages' tests (tests/ui/make_content.php), starts the server on
# loopback with an empty database, runs the checks, and removes everything again. Needs nothing but Docker and Python 3.
#
# Usage: tests/game/protocol.sh        (PORT, default 18701; KEEP=1 leaves the server up)
# Also runs tests/game/lock.php on the same database, and fails on any PHP warning in the server's log.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
TAG=protocol
NAME=odq-protocol
PORT=${PORT:-18701}
DATA=$(mktemp -d)

# What the container wrote belongs to its user: removed from inside the image.
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run --rm -u 0 -v "$DATA:/d" --entrypoint sh "opendmtq-server:$TAG" -c 'rm -rf /d/* /d/.[!.]*' >/dev/null 2>&1 || true
  rmdir "$DATA" 2>/dev/null || true
}
if [ -z "${KEEP:-}" ]; then
  trap cleanup EXIT
fi

docker build -q -t "opendmtq-server:$TAG" "$ROOT/server" >/dev/null
mkdir -p "$DATA/content" "$DATA/state" "$DATA/custom" "$DATA/apk"
chmod -R a+rwX "$DATA"
docker run --rm -u 33:33 -v "$DATA/content:/content" -v "$ROOT/tests/ui:/ui:ro" --entrypoint php "opendmtq-server:$TAG" /ui/make_content.php /content >/dev/null
docker rm -f "$NAME" >/dev/null 2>&1 || true
# As compose starts it: read-only, unprivileged, capped.
docker run -d --name "$NAME" --cpus 2 --memory 1g -u 33:33 --read-only --tmpfs /var/opendmtq:mode=1777 --tmpfs /tmp:mode=1777 \
  -e PUBLIC_HOST="127.0.0.1:$PORT" -e ADMIN_ON_PUBLIC_PORT=no -e TZ=Asia/Seoul \
  -v "$DATA/content:/srv/content:ro" -v "$DATA/state:/data" -v "$DATA/apk:/srv/apk:ro" -v "$DATA/custom:/srv/custom:ro" \
  -p "127.0.0.1:$PORT:8080" "opendmtq-server:$TAG" >/dev/null
# Until it answers, or give up with its log.
for _ in $(seq 1 60); do
  curl -sf -m 3 -o /dev/null "http://127.0.0.1:$PORT/opendmtq/health.php" && break
  sleep 1
done
if ! curl -sf -m 3 -o /dev/null "http://127.0.0.1:$PORT/opendmtq/health.php"; then
  echo "FAIL the server did not come up on the stand-in game files" >&2
  docker logs --tail 30 "$NAME" >&2
  exit 1
fi
failed=0
python3 "$ROOT/tests/game/protocol.py" "http://127.0.0.1:$PORT" || failed=1
# Storing achievements while another writer holds the database, on the same database, beside the running server.
docker run --rm -u 33:33 -v "$DATA/state:/data" -v "$ROOT/tests/game:/t:ro" --entrypoint php "opendmtq-server:$TAG" \
  /t/lock.php /data/dmtq.db3 || failed=1
# The folder of the built apps that a deployment names (the Helm chart: OPENDMTQ_APK_OUT, APK_DIR in charts from before
# 2026-11) wins over the image's own default, or the site would find no app there.
for var in OPENDMTQ_APK_OUT APK_DIR; do
  # shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
  got=$(docker run --rm -e "$var=/srv/apk-all/out" --entrypoint php "opendmtq-server:$TAG" \
    -r 'require "/opt/opendmtq/game/src/config.php"; echo odq_apk_dir();')
  if [ "$got" = /srv/apk-all/out ]; then
    echo "PASS the site finds the apps where $var says"
  else
    echo "FAIL the site looks for the apps in $got, not where $var says"
    failed=1
  fi
done
# The installer's end as the site makes it (portal/lib.php) and as the admin pages make it (tools/opendmtq_tools/
# windows_client.py): the same bytes, for an address over plain HTTP, one over HTTPS on port 80 (its port named) with the
# server's own authority and a name in Korean, and one over HTTPS on a port of its own without an authority.
ca=$(printf -- '-----BEGIN CERTIFICATE-----\nMIIBszCCAVmgAwIBAgIUmadeup+/=\n-----END CERTIFICATE-----')
while IFS='|' read -r https host name with_ca; do
  given=""
  [ "$with_ca" = 1 ] && given=$ca
  # shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
  site=$(docker run --rm --network none -e "ODQ_HTTPS=$https" -e "ODQ_HOST=$host" -e "ODQ_NAME=$name" -e "ODQ_CA=$given" \
    --entrypoint php "opendmtq-server:$TAG" -r 'require "/opt/opendmtq/portal/lib.php";
      echo bin2hex(windows_preset_for(site_url_for(getenv("ODQ_HTTPS") === "1", getenv("ODQ_HOST")), getenv("ODQ_NAME"),
                                      (string)getenv("ODQ_CA")));')
  admin=$(ODQ_HTTPS=$https ODQ_HOST=$host ODQ_NAME=$name ODQ_CA=$given PYTHONPATH="$ROOT/tools" python3 -c '
import os
from opendmtq_tools import windows_client as w
e = os.environ
print(w.preset(w.site_url(e["ODQ_HTTPS"] == "1", e["ODQ_HOST"]), e["ODQ_NAME"], e["ODQ_CA"]).hex())')
  if [ -n "$site" ] && [ "$site" = "$admin" ]; then
    echo "PASS the installer's end is the same from the site and from the admin pages ($https $host)"
  else
    echo "FAIL the installer's end differs between the site and the admin pages ($https $host):"
    echo "  site:  $site"
    echo "  admin: $admin"
    failed=1
  fi
done <<'CASES'
0|127.0.0.1:8080|127.0.0.1:8080|0
1|game.example.net|우리 서버|1
1|game.example.net:8790|game.example.net:8790|0
CASES
# Whatever PHP said in the server's log during all of the above: a warning there is a bug, even when the reply was right.
if docker logs "$NAME" 2>&1 | grep -E "PHP (Warning|Notice|Deprecated|Fatal error|Parse error)"; then
  echo "FAIL PHP complained in the server's log (above)"
  failed=1
else
  echo "PASS PHP said nothing in the server's log"
fi
if [ -n "${KEEP:-}" ]; then
  # The data belongs to the container's user: removed from inside the image, as the cleanup does.
  echo "left running: http://127.0.0.1:$PORT/ (data in $DATA); remove with: docker rm -f $NAME;" \
    "docker run --rm -u 0 -v $DATA:/d --entrypoint sh opendmtq-server:$TAG -c 'rm -rf /d/*'; rmdir $DATA"
fi
exit "$failed"
