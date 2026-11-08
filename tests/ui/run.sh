#!/usr/bin/env bash
# The pages' tests on a throwaway server, with no game files: builds the images from this working tree, makes stand-in game
# files (make_content.php), starts the server and the admin service by their real start paths on loopback, and takes them
# through a server's life with a real browser (audit.js): empty, full of players and recordings, players on air, under
# maintenance, and what people do on the pages. Layout findings, screenshots and the list of results go to the report folder.
#
# Usage: tests/ui/run.sh [report folder, default _work/ui-report]
# ONLY="full flows" runs those stages (the checker's own, self, and the setup always run first). KEEP=1 leaves the stack up afterwards.
# NO_BUILD=1 uses the images already tagged opendmtq-*:uitest.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
UI=$ROOT/tests/ui
REPORT=$(realpath -m "${1:-$ROOT/_work/ui-report}")
TAG=uitest
NET=odq-uitest
SITE=odq-uitest-site
ADMIN=odq-uitest-admin
SITE_PORT=${SITE_PORT:-18801}
ADMIN_PORT=${ADMIN_PORT:-18802}
# The owner's admin password and the site account's (an account's has six letters at least).
PASSWORD=smoke-pass
# The browser's share of the machine: four processors at most, or what there is (GitHub gives a private repository two).
BROWSER_CPUS=${BROWSER_CPUS:-$(($(nproc) < 4 ? $(nproc) : 4))}
BROWSER_IMAGE=zenika/alpine-chrome:with-puppeteer
FFMPEG_IMAGE=mwader/static-ffmpeg:7.1
DATA=$(mktemp -d)
FEED_PID=

# What the containers wrote belongs to their user: removed from inside an image.
cleanup() {
  if [ -n "$FEED_PID" ]; then kill "$FEED_PID" 2>/dev/null || true; fi
  docker rm -f "$SITE" "$ADMIN" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  docker run --rm -u 0 -v "$DATA:/d" --entrypoint sh "opendmtq-server:$TAG" -c 'rm -rf /d/* /d/.[!.]*' >/dev/null 2>&1 || true
  rmdir "$DATA" 2>/dev/null || true
}
if [ -z "${KEEP:-}" ]; then
  trap cleanup EXIT
fi

if [ -z "${NO_BUILD:-}" ]; then
  docker build -q -t "opendmtq-server:$TAG" "$ROOT/server" >/dev/null
  docker build -q -t "opendmtq-tools:$TAG" "$ROOT/tools" >/dev/null
fi

# A fresh report; the browser's user writes into it.
# (What an earlier run's browser wrote there may be another user's: then from inside an image.)
rm -rf "$REPORT" 2>/dev/null || docker run --rm -u 0 -v "$(dirname "$REPORT"):/p" --entrypoint rm "opendmtq-server:$TAG" -rf "/p/$(basename "$REPORT")"
mkdir -p "$REPORT/shots"
chmod -R a+rwX "$REPORT"

# The stand-in game files, and the folders a server keeps its state in.
mkdir -p "$DATA/content" "$DATA/state" "$DATA/apk/out" "$DATA/custom" "$DATA/backups" "$DATA/ts"
chmod -R a+rwX "$DATA"
docker run --rm -u 33:33 -v "$DATA/content:/content" -v "$UI:/ui:ro" --entrypoint php "opendmtq-server:$TAG" /ui/make_content.php /content

# Started as tests/live/run.sh starts them, and as compose does: read-only, unprivileged, capped.
docker network create "$NET" >/dev/null 2>&1 || true
docker rm -f "$SITE" "$ADMIN" >/dev/null 2>&1 || true
HOST=127.0.0.1:$SITE_PORT
docker run -d --name "$SITE" --network "$NET" --cpus 2 --memory 1g -u 33:33 --read-only \
  --tmpfs /var/opendmtq:mode=1777 --tmpfs /tmp:mode=1777 \
  -e PUBLIC_HOST="$HOST" -e ADMIN_ON_PUBLIC_PORT=no -e TZ=Asia/Seoul \
  -e OPENDMTQ_VERSION=2026.11.02-abc1234 \
  -v "$DATA/content:/srv/content:ro" -v "$DATA/state:/data" -v "$DATA/apk/out:/srv/apk:ro" -v "$DATA/custom:/srv/custom:ro" \
  -p "127.0.0.1:$SITE_PORT:8080" "opendmtq-server:$TAG" >/dev/null
# The setup pages as a host install shows them (OPENDMTQ_HOST_INSTALL): they look in the owner's home folder, made below.
docker run -d --name "$ADMIN" --network "$NET" --cpus 2 --memory 1g -u 33:33 --read-only --tmpfs /tmp:mode=1777 \
  --tmpfs /home/player:mode=1777 -e HOME=/home/player -e OPENDMTQ_HOST_INSTALL=yes \
  -e PUBLIC_HOST="$HOST" -e ADMIN_PASSWORD="$PASSWORD" -e SERVER_URL="http://$SITE:8080" -e TZ=Asia/Seoul \
  -e OPENDMTQ_VERSION=2026.11.02-abc1234 \
  -v "$DATA/state:/data" -v "$DATA/apk:/apk" -v "$DATA/custom:/custom" -v "$DATA/backups:/backups" \
  -v "$DATA/content:/srv/content:ro" -p "127.0.0.1:$ADMIN_PORT:8000" \
  --entrypoint gunicorn "opendmtq-tools:$TAG" -w 1 --threads 4 -b 0.0.0.0:8000 opendmtq_tools.admin:app >/dev/null

# Until both answer, or give up with their logs.
for _ in $(seq 1 90); do
  if curl -sf -m 3 -o /dev/null "http://127.0.0.1:$SITE_PORT/opendmtq/health.php" \
    && curl -sf -m 3 -o /dev/null "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/login"; then
    break
  fi
  sleep 1
done
if ! curl -sf -m 3 -o /dev/null "http://127.0.0.1:$SITE_PORT/opendmtq/health.php"; then
  echo "FAIL the server did not come up on the stand-in game files" >&2
  docker logs --tail 30 "$SITE" >&2
  exit 1
fi
echo "PASS the real start script starts on the stand-in game files"
# The game's files where the setup pages look for them: a client beside a folder of the client data and the song data in
# Downloads (laid out as one, with nothing in it), an archive of them, and the other folders a home has.
docker exec "$ADMIN" sh -c 'd=/home/player/Downloads/DMTQ && mkdir -p "$d/dmtq/dmqglb.mb.pmang.com/patch/phone_new" "$d/dmtq/_info" \
  /home/player/Desktop /home/player/Documents /home/player/Downloads/Music && echo "[]" > "$d/dmtq/_info/songList.json" \
  && head -c 4096 /dev/zero > "$d/game.apk" && head -c 2048 /dev/zero > "/home/player/Downloads/dmtq-files.rar"'

# The site's account the browser signs in with, made as the owner makes one: on the admin pages' Accounts page.
JAR=$DATA/admin-jar
curl -sf -m 10 -c "$JAR" -b "$JAR" -o /dev/null --data-urlencode name=admin --data-urlencode "password=$PASSWORD" "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/login"
CSRF=$(curl -sf -m 10 -b "$JAR" "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/accounts" | grep -o 'name="csrf" value="[^"]*"' | head -1 | cut -d'"' -f4)
curl -sf -m 10 -b "$JAR" -o /dev/null --data-urlencode "csrf=$CSRF" --data-urlencode action=create --data-urlencode name=dmtq \
  --data-urlencode "password=$PASSWORD" --data-urlencode "password2=$PASSWORD" --data-urlencode "note=pages test" "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/accounts"
# And one with admin rights, linked to no player and with a note, as a server's second keeper has it: the row with the
# longest buttons (Remove admin rights) beside the list's longest word (Not linked).
curl -sf -m 10 -b "$JAR" -o /dev/null --data-urlencode "csrf=$CSRF" --data-urlencode action=create --data-urlencode name=manager \
  --data-urlencode admin=1 --data-urlencode "note=runs the server too" "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/accounts"
# Two API tokens, made as the owner makes them on the same page: one to write, one to read with a name as long as one may be.
curl -sf -m 10 -b "$JAR" -o /dev/null --data-urlencode "csrf=$CSRF" --data-urlencode action=token --data-urlencode "token_name=nightly backup" \
  --data-urlencode scope=write "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/accounts"
curl -sf -m 10 -b "$JAR" -o /dev/null --data-urlencode "csrf=$CSRF" --data-urlencode action=token \
  --data-urlencode "token_name=health monitor on the living-room PC" --data-urlencode scope=read "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/accounts"
rm -f "$JAR"

# One stage in the browser; goes on after a failure, so that the report has everything. No network of its own beyond the
# host's loopback; capped like the rest.
FAILED=0
wanted() {
  [ -z "${ONLY:-}" ] || [ "$1" = self ] || grep -qw "$1" <<<"$ONLY"
}
stage() {
  if ! wanted "$1"; then
    return 0
  fi
  local status=0
  docker run --rm --network host --cpus "$BROWSER_CPUS" --memory 3g \
    -e SITE="http://127.0.0.1:$SITE_PORT" -e ADMIN="http://127.0.0.1:$ADMIN_PORT" -e PASSWORD="$PASSWORD" -e OUT=/out \
    -v "$UI:/usr/src/app/ui:ro" -v "$REPORT:/out" --entrypoint node "$BROWSER_IMAGE" ui/audit.js "$1" 2>&1 \
    | tee "$REPORT/last.txt" >> "$REPORT/results.txt" || status=$?
  if [ "$status" -ne 0 ]; then
    FAILED=1
    # What went wrong; when the browser could not even start, that is all there is to show.
    if grep -q '^FAIL' "$REPORT/last.txt"; then
      grep -A32 '^FAIL' "$REPORT/last.txt" | cut -c1-200 || true
    else
      tail -5 "$REPORT/last.txt" | cut -c1-200
    fi
  fi
  echo "stage $1: $(grep -c '^PASS' "$REPORT/last.txt") passed, $(grep -c '^FAIL' "$REPORT/last.txt") failed"
}

stage self
stage empty

# Players and plays. An app, as the builder leaves one: the real thing needs the game's own file.
docker exec -i "$SITE" php < "$UI/seed.php"
APP=OpenDMTQ-127.0.0.1-$SITE_PORT-v2026.11.02.apk
head -c 1048576 /dev/zero > "$DATA/apk/out/$APP"
printf '{"file": "%s", "host": "%s", "built_at": "2026-11-02T09:28:08", "sha256": "0", "size": 1048576, "patcher": "1.8.0", "runtime": "test", "label": "TECHNIKA Q (%s)", "package": "com.test.opendmtq"}' \
  "$APP" "$HOST" "$HOST" | tee "$DATA/apk/out/latest.json" > "$DATA/apk/out/$APP.json"
# The player for Windows beside it, as the builder leaves it (tools/opendmtq_tools/player_windows.py): the download page's
# part for computers.
WIN=${APP%.apk}-windows.zip
head -c 2097152 /dev/zero > "$DATA/apk/out/$WIN"
printf '{"file": "%s", "size": 2097152, "sha256": "0", "apk": "%s", "apk_sha256": "0", "player": "test", "built_at": "2026-11-02T09:29:00"}' \
  "$WIN" "$APP" > "$DATA/apk/out/windows.json"
# And one for another address, kept for download: the App page lists it with why players do not get it.
OTHER=OpenDMTQ-10.0.0.5-8080-v2026.11.01.apk
head -c 524288 /dev/zero > "$DATA/apk/out/$OTHER"
printf '{"file": "%s", "host": "10.0.0.5:8080", "built_at": "2026-11-01T21:10:00", "sha256": "0", "size": 524288, "patcher": "1.8.0", "runtime": "test", "label": "TECHNIKA Q (10.0.0.5:8080)", "package": "com.test.opendmtq"}' \
  "$OTHER" > "$DATA/apk/out/$OTHER.json"
docker run --rm -v "$DATA/apk/out:/o" --entrypoint python3 "opendmtq-tools:$TAG" -I -c \
  "from opendmtq_tools import qr; qr.write('http://$HOST/apk', '/o/download-qr.svg')"

# Two minutes of video with sound, as phones send it: pieces of two seconds. Long enough for what a replay does at its
# beginning and its end to be apart. Made with no network, capped.
docker run --rm --network none --cpus 2 --memory 1g -v "$DATA/ts:/o" "$FFMPEG_IMAGE" -hide_banner -loglevel error -y \
  -f lavfi -i testsrc2=size=1280x720:rate=30 -f lavfi -i anoisesrc=color=pink:amplitude=0.25:seed=7 -t 120 -map 0:v -map 1:a \
  -c:v libx264 -preset veryfast -profile:v main -pix_fmt yuv420p -g 60 -keyint_min 60 -sc_threshold 0 -b:v 1M \
  -c:a aac -b:a 96k -ac 2 -f segment -segment_time 2 -segment_format mpegts /o/%d.ts
export SITE_URL="http://127.0.0.1:$SITE_PORT" ADMIN_URL="http://127.0.0.1:$ADMIN_PORT" ADMIN_PASSWORD=$PASSWORD SITE_CONTAINER=$SITE SEGMENTS=$DATA/ts
python3 "$UI/feed.py" record

stage full

# Two players on air while the pages that change are looked at; told to stop, the feed ends both broadcasts.
if wanted air; then
  python3 "$UI/feed.py" air 300 &
  FEED_PID=$!
  sleep 6
  stage air
  kill "$FEED_PID" 2>/dev/null || true
  wait "$FEED_PID" 2>/dev/null || true
  FEED_PID=
fi

stage maint
stage flows

# The game server gone: the owner's pages are what is left. Last, as the other stages need it.
if wanted down; then
  docker stop "$SITE" >/dev/null
  stage down
  docker start "$SITE" >/dev/null
fi

# Every view's faults in one place, for reading in the workflow's log.
if [ -s "$REPORT/findings.txt" ]; then
  echo "findings: $(wc -l < "$REPORT/findings.txt") ($REPORT/findings.txt)"
fi
if [ "$FAILED" -ne 0 ]; then
  echo "FAIL the pages' tests: see $REPORT"
  exit 1
fi
rm -f "$REPORT/last.txt"
echo "PASS the pages' tests: $(grep -c '^PASS' "$REPORT/results.txt") checks, screenshots in $REPORT/shots"
