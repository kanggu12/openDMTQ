#!/usr/bin/env bash
# Players sharing one server (tests/load/load.py) on a throwaway server this script starts: the server, the admin service
# and the app's builder all held to the same two processor cores, the smallest computer the README lists. The database
# first gets SEED_PLAYERS players (through the game's own logins) and SEED_PLAYS earlier plays, the size the README's
# chart of the game's requests was measured at. Needs the client data and the song data in data/content and an app in
# data/apk/base, as the other tests of the game's server do. Removes everything it starts.
#
# Usage: tests/load/run.sh [OUT_DIR]
# Environment: CORES (the two cores; default the machine's last two), SEED_PLAYERS (300), SEED_PLAYS (1000000),
# NO_BUILD=1 (the images already tagged loadtest), SITE_PORT (18611), and load.py's own (PLAYERS, PHASE_S, ...).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${1:-$(mktemp -d)}
TAG=loadtest
NET=odq-loadtest
SITE=odq-loadtest-site
ADMIN=odq-loadtest-admin
BUILDER=odq-loadtest-builder
SITE_PORT=${SITE_PORT:-18611}
# Two cores for everything: the last two, unless asked for others.
N=$(nproc)
CORES=${CORES:-$((N - 2)),$((N - 1))}
SEED_PLAYERS=${SEED_PLAYERS:-300}
SEED_PLAYS=${SEED_PLAYS:-1000000}
HOST=load-test.example.net:8790
DATA=$(mktemp -d)
mkdir -p "$OUT"

# What the containers wrote belongs to their user: removed from inside an image.
cleanup() {
  docker rm -f "$SITE" "$ADMIN" "$BUILDER" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  docker run --rm -u 0 -v "$DATA:/d" --entrypoint sh "opendmtq-server:$TAG" -c 'rm -rf /d/* /d/.[!.]*' >/dev/null 2>&1 || true
  rmdir "$DATA" 2>/dev/null || true
}
trap cleanup EXIT

if [ -z "${NO_BUILD:-}" ]; then
  docker build -q -t "opendmtq-server:$TAG" "$ROOT/server" >/dev/null
  docker build -q -t "opendmtq-tools:$TAG" "$ROOT/tools" >/dev/null
fi

# The app the builder starts from: the owner's, in data/apk/base.
base=$(ls "$ROOT"/data/apk/base/*.apk 2>/dev/null | head -1 || true)
[ -n "$base" ] || { echo "no app in data/apk/base" >&2; exit 1; }
mkdir -p "$DATA/state" "$DATA/apk/base" "$DATA/apk/out" "$DATA/custom" "$DATA/backups"
cp "$base" "$DATA/apk/base/"
chmod -R a+rwX "$DATA"
docker network create "$NET" >/dev/null 2>&1 || true
docker rm -f "$SITE" "$ADMIN" "$BUILDER" >/dev/null 2>&1 || true
# As compose.yaml runs them, held to the same two cores; memory capped only so that a runaway cannot take the machine's.
docker run -d --name "$SITE" --network "$NET" --cpuset-cpus "$CORES" --memory 2g -u 33:33 --read-only \
  --tmpfs /var/opendmtq:mode=1777 --tmpfs /tmp:mode=1777 \
  -e PUBLIC_HOST="$HOST" -e ADMIN_ON_PUBLIC_PORT=no -e TZ=Asia/Seoul -e LIVE_DEFAULT=on \
  -v "$ROOT/data/content:/srv/content:ro" -v "$DATA/state:/data" -v "$DATA/apk/out:/srv/apk:ro" -v "$DATA/custom:/srv/custom:ro" \
  -p "127.0.0.1:$SITE_PORT:8080" "opendmtq-server:$TAG" >/dev/null
docker run -d --name "$ADMIN" --network "$NET" --cpuset-cpus "$CORES" --memory 1536m -u 33:33 --read-only --tmpfs /tmp:mode=1777 \
  -e PUBLIC_HOST="$HOST" -e ADMIN_PASSWORD=load -e SERVER_URL="http://$SITE:8080" -e HOME=/tmp -e TZ=Asia/Seoul \
  -v "$DATA/state:/data" -v "$DATA/apk:/apk" -v "$DATA/custom:/custom" -v "$DATA/backups:/backups" \
  -v "$ROOT/data/content:/srv/content:ro" \
  --entrypoint gunicorn "opendmtq-tools:$TAG" -w 1 --threads 8 -b 0.0.0.0:8000 opendmtq_tools.admin:app >/dev/null

# Until the server answers, or give up with its log.
for _ in $(seq 1 120); do
  curl -sf -o /dev/null "http://127.0.0.1:$SITE_PORT/opendmtq/health.php" && break
  sleep 1
done
if ! curl -sf -o /dev/null "http://127.0.0.1:$SITE_PORT/opendmtq/health.php"; then
  echo "the server did not come up" >&2
  docker logs --tail 30 "$SITE" >&2
  exit 1
fi

# The players through the game's own logins, then their earlier plays straight into the database.
python3 "$ROOT/tests/load/load.py" "http://127.0.0.1:$SITE_PORT" seed "$SEED_PLAYERS" "$DATA/state/load-guids.txt"
docker exec -i "$SITE" php -d memory_limit=512M -- "$SEED_PLAYS" < "$ROOT/tests/load/seed.php"
# The site account the viewers sign in with, made as the Accounts page makes one.
docker exec "$ADMIN" python3 -c 'import sys; from opendmtq_tools.admin import auth; sys.exit(0 if auth.account_create("loadviewer", "load-viewer-pass") else 1)'

# The rounds; the heavy one runs heavy.sh with what it needs to reach the containers.
export ADMIN BUILDER CORES HOST DATA TAG
# Not stopped by a failed round: the server's log below is what tells why.
set +e
SEEDED="$DATA/state/load-guids.txt" OUT="$OUT" HEAVY_CMD="bash $ROOT/tests/load/heavy.sh" VIEWER=loadviewer:load-viewer-pass \
  python3 "$ROOT/tests/load/load.py" "http://127.0.0.1:$SITE_PORT" | tee "$OUT/load.txt"
status=${PIPESTATUS[0]}
set -e
# The server's own log of the run: what it said about the saves it could not store.
docker logs "$SITE" > "$OUT/server.log" 2>&1 || true
exit "$status"
