#!/usr/bin/env bash
# The pages' tests on a throwaway server, with no game files: builds the images from this working tree, makes stand-in game
# files (make_content.php), starts the server and the admin service by their real start paths on loopback, and takes them
# through a server's life with a real browser (audit.js): empty (broadcasts off, as a server starts), full of players and
# recordings, players on air, under maintenance, what people do on the pages, and broadcasts off again with all of that. Layout findings, screenshots and the list of results go to the report folder.
#
# Usage: tests/ui/run.sh [report folder, default _work/ui-report]
# ONLY="full flows" runs those stages (the checker's own, self, and the setup always run first); keys is the keyboard's marks,
# mine MY PAGE, moved the app's states after a move and with a new app.
# KEEP=1 leaves the stack up afterwards.
# NO_BUILD=1 uses the images already tagged opendmtq-*:uitest.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
UI=$ROOT/tests/ui
REPORT=$(realpath -m "${1:-$ROOT/_work/ui-report}")
# NAME_PREFIX and TAG keep a run's containers, network and images apart from another run's on the same machine.
NAME_PREFIX=${NAME_PREFIX:-odq}
TAG=${TAG:-uitest}
NET=$NAME_PREFIX-uitest
SITE=$NAME_PREFIX-uitest-site
ADMIN=$NAME_PREFIX-uitest-admin
SITE_PORT=${SITE_PORT:-18801}
ADMIN_PORT=${ADMIN_PORT:-18802}
# A stand-in chat for the webhooks of the Notices page (chat.py), beside the admin service; the browser reads what it got on
# this port of the loopback.
CHAT=$NAME_PREFIX-uitest-chat
CHAT_PORT=${CHAT_PORT:-18803}
# The owner's admin password and the site account's (an account's has six letters at least).
PASSWORD=smoke-pass
# The browser's share of the machine: four processors at most, or what there is (GitHub gives a private repository two).
BROWSER_CPUS=${BROWSER_CPUS:-$(($(nproc) < 4 ? $(nproc) : 4))}
# The views of a list looked at side by side (audit.js sweep()), each in a window of its own: one for each of the browser's
# processors. Its memory: 3 GB, and half a gigabyte more for each view at once past four.
SWEEP_WORKERS=${SWEEP_WORKERS:-$BROWSER_CPUS}
BROWSER_MEMORY=${BROWSER_MEMORY:-$((3072 + (SWEEP_WORKERS > 4 ? SWEEP_WORKERS - 4 : 0) * 512))m}
BROWSER_IMAGE=zenika/alpine-chrome:with-puppeteer
FFMPEG_IMAGE=mwader/static-ffmpeg:7.1
DATA=$(mktemp -d)
FEED_PID=

# What the containers wrote belongs to their user: removed from inside an image.
cleanup() {
  if [ -n "$FEED_PID" ]; then kill "$FEED_PID" 2>/dev/null || true; fi
  docker rm -f "$SITE" "$ADMIN" "$ADMIN-pc" "$CHAT" >/dev/null 2>&1 || true
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
mkdir -p "$DATA/content" "$DATA/state" "$DATA/apk/out" "$DATA/custom" "$DATA/backups" "$DATA/ts" "$DATA/install/run"
# The install's own folder, as a host install's program hands it to the admin pages: its .env as the setup writes it
# (the same address and password the services start with) and its run folder, where the Server page leaves its requests
# (restart, stop, uninstall) for a program that nobody runs here.
printf '# OpenDMTQ settings. Written by ./opendmtq; safe to edit by hand.\nPUBLIC_HOST=127.0.0.1:%s\nLISTEN_PORT=%s\nADMIN_PASSWORD=%s\n' \
  "$SITE_PORT" "$SITE_PORT" "$PASSWORD" > "$DATA/install/.env"
chmod -R a+rwX "$DATA"
docker run --rm -u 33:33 -v "$DATA/content:/content" -v "$UI:/ui:ro" --entrypoint php "opendmtq-server:$TAG" /ui/make_content.php /content

# The catalog as the tools make it from the client's tables (songs.py's rebuild), made up: the items a player equips, with
# names of the lengths and scripts the player's page must cope with, a few of them with the game's own names in each
# language, and a few products of the shop.
# Written now and again before MY PAGE's stage: the admin flows hide a song and show it again, which rebuilds the
# catalog from the stand-in game files, which have none of these items or names.
stand_in_catalog() {
  local file
  file=$(mktemp)
  cat > "$file" <<'CATALOG'
{"items": [30001, 30002, 30003, 40001, 100001, 100002], "unlock_product": null, "point_charts": [],
 "products": {"90001": {"item": 90001, "kind": "N", "point": 2000, "cash": 0, "amount": 0},
                "1050001": {"item": 50001, "kind": "M", "point": 0, "cash": 10, "amount": 2500}},
 "gear": {"C": [[30001, "지미"], [30002, "A Partner With A Name Long Enough To Wrap In Any Narrow List"], [30003, "소향"]],
            "F": [[40001, "안티 게임오버"]],
            "N": [[90001, "레인보우 노트"], [90002, "미러볼 노트"], [90003, "Crystal Note"]],
            "K": [[100001, "Yellow Metal Skin"], [100002, "워터멜론 메탈 스킨"]]},
 "names": {"en": {"100001": "Yellow", "30001": "Jimmy"}, "ko": {"100001": "옐로메탈", "30001": "지미"}}}
CATALOG
  # The admin flows' rebuild leaves the file the containers' user's: written through a container where this user
  # cannot write it (a CI runner; root here can).
  if ! cp "$file" "$DATA/custom/catalog.json" 2>/dev/null; then
    docker run --rm -i -u 0 -v "$DATA/custom:/c" --entrypoint sh "opendmtq-tools:$TAG" -c 'cat > /c/catalog.json' < "$file"
  fi
  chmod a+rw "$DATA/custom/catalog.json" 2>/dev/null \
    || docker run --rm -u 0 -v "$DATA/custom:/c" --entrypoint chmod "opendmtq-tools:$TAG" a+rw /c/catalog.json
  rm -f "$file"
}
stand_in_catalog
# Started as tests/live/run.sh starts them, and as compose does: read-only, unprivileged, capped.
docker network create "$NET" >/dev/null 2>&1 || true
docker rm -f "$SITE" "$ADMIN" >/dev/null 2>&1 || true
HOST=127.0.0.1:$SITE_PORT
docker run -d --name "$SITE" --network "$NET" --cpus 2 --memory 1g -u 33:33 --read-only \
  --tmpfs /var/opendmtq:mode=1777 --tmpfs /tmp:mode=1777 \
  -e PUBLIC_HOST="$HOST" -e TZ=Asia/Seoul \
  -e OPENDMTQ_VERSION=0.9.3-abc1234 \
  -e ADMIN_URL="http://$ADMIN:8000" -e ADMIN_ON_PUBLIC_PORT=yes \
  -v "$DATA/content:/srv/content:ro" -v "$DATA/state:/data" -v "$DATA/apk/out:/srv/apk:ro" -v "$DATA/custom:/srv/custom:ro" \
  -p "127.0.0.1:$SITE_PORT:8080" "opendmtq-server:$TAG" >/dev/null
# (The admin pages on the site's one port, as a server has them; the checks also reach the admin service on its own port.)
# The setup pages as a host install shows them (OPENDMTQ_HOST_INSTALL): they look in the owner's home folder, made below.
docker run -d --name "$ADMIN" --network "$NET" --cpus 2 --memory 1g -u 33:33 --read-only --tmpfs /tmp:mode=1777 \
  --tmpfs /home/player:mode=1777 -e HOME=/home/player -e OPENDMTQ_HOST_INSTALL=yes \
  -e PUBLIC_HOST="$HOST" -e ADMIN_PASSWORD="$PASSWORD" -e SERVER_URL="http://$SITE:8080" -e TZ=Asia/Seoul \
  -e OPENDMTQ_VERSION=0.9.3-abc1234 \
  -e OPENDMTQ_ENV_FILE=/install/.env -e OPENDMTQ_RUN=/install/run -e OPENDMTQ_ROOT=/install -v "$DATA/install:/install" \
  -v "$DATA/state:/data" -v "$DATA/apk:/apk" -v "$DATA/custom:/custom" -v "$DATA/backups:/backups" \
  -v "$DATA/content:/srv/content:ro" -p "127.0.0.1:$ADMIN_PORT:8000" \
  --entrypoint gunicorn "opendmtq-tools:$TAG" -w 1 --threads 4 -b 0.0.0.0:8000 opendmtq_tools.admin:app >/dev/null

# The stand-in chat, on the same network: the admin service sends it the webhooks' messages, and nothing leaves the network.
docker rm -f "$CHAT" >/dev/null 2>&1 || true
docker run -d --name "$CHAT" --network "$NET" --cpus 0.5 --memory 128m -u 33:33 --read-only -v "$UI:/ui:ro" \
  -p "127.0.0.1:$CHAT_PORT:8080" --entrypoint python3 "opendmtq-tools:$TAG" -I /ui/chat.py 8080 >/dev/null

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
# Two webhooks to the stand-in chat, added as the owner adds them on the Notices page: one in English that hears of
# everything, one in Korean whose chat deleted it (its messages fail, and the card says so).
curl -sf -m 10 -b "$JAR" -o /dev/null --data-urlencode "csrf=$CSRF" --data-urlencode "url=http://$CHAT:8080/services/T01/B02/ui-secret-5432" \
  --data-urlencode language=en --data-urlencode event=live_on --data-urlencode event=live_off --data-urlencode event=chart_top \
  --data-urlencode event=month_top --data-urlencode event=maint_on --data-urlencode event=maint_off "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/webhooks"
curl -sf -m 10 -b "$JAR" -o /dev/null --data-urlencode "csrf=$CSRF" --data-urlencode "url=http://$CHAT:8080/gone/ui-secret-0404" \
  --data-urlencode language=ko --data-urlencode event=chart_top --data-urlencode event=maint_on "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/webhooks"
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
  docker run --rm --name "$NAME_PREFIX-uitest-browser" --network host --cpus "$BROWSER_CPUS" --memory "$BROWSER_MEMORY" \
    -e SITE="http://127.0.0.1:$SITE_PORT" -e ADMIN="http://127.0.0.1:$ADMIN_PORT" -e PASSWORD="$PASSWORD" -e OUT=/out \
    -e SWEEP_WORKERS="$SWEEP_WORKERS" \
    -e CHAT="http://$CHAT:8080" -e CHAT_LOCAL="http://127.0.0.1:$CHAT_PORT" \
    -e SHOTS_ALL="${SHOTS_ALL:-}" -e MOVED="${MOVED:-}" \
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
# MY PAGE's own account (stage mine), whose password and ID that stage changes, so that the account every stage signs in
# with stays as it is: with admin rights (an ID's change takes its API tokens along), linked to the seed's first player,
# and a read token of its own, made as an admin makes one, beside the report for the stage.
JAR=$DATA/admin-jar
curl -sf -m 10 -c "$JAR" -b "$JAR" -o /dev/null --data-urlencode name=admin --data-urlencode "password=$PASSWORD" "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/login"
CSRF=$(curl -sf -m 10 -b "$JAR" "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/accounts" | grep -o 'name="csrf" value="[^"]*"' | head -1 | cut -d'"' -f4)
curl -sf -m 10 -b "$JAR" -o /dev/null --data-urlencode "csrf=$CSRF" --data-urlencode action=create --data-urlencode name=mypage \
  --data-urlencode password=mypage-pass-1 --data-urlencode password2=mypage-pass-1 --data-urlencode admin=1 --data-urlencode player=1 \
  --data-urlencode "note=my page's checks" "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/accounts"
# A player's account linked to one of the seed's long names (player 5, sixteen Korean syllables), as the owner links one:
# its row on the Accounts page shows that name in the player's list, beside the Link button, at every width.
curl -sf -m 10 -b "$JAR" -o /dev/null --data-urlencode "csrf=$CSRF" --data-urlencode action=create --data-urlencode name=wide \
  --data-urlencode player=5 "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/accounts"
rm -f "$JAR"
curl -sf -m 10 -c "$JAR" -b "$JAR" -o /dev/null --data-urlencode name=mypage --data-urlencode password=mypage-pass-1 "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/login"
CSRF=$(curl -sf -m 10 -b "$JAR" "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/accounts" | grep -o 'name="csrf" value="[^"]*"' | head -1 | cut -d'"' -f4)
curl -sf -m 10 -b "$JAR" -c "$JAR" -L --data-urlencode "csrf=$CSRF" --data-urlencode action=token --data-urlencode "token_name=my page check" \
  --data-urlencode scope=read "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/accounts" | grep -o 'id="token-secret">[^<]*' | cut -d'>' -f2 > "$REPORT/mypage-token.txt"
rm -f "$JAR"
# MY PAGE's account changes inside the server, on accounts of the check's own (tests/ui/account.php): its lines with the
# stages', what failed said here.
if ! docker exec -i "$SITE" php < "$UI/account.php" > "$REPORT/account.txt" 2>&1; then
  FAILED=1
  # Stopped before its end (a page's code missing or broken): said as a failure of its own, with the server's words in the file.
  grep -q '^FAIL' "$REPORT/account.txt" || echo "FAIL account: the checks stopped before their end (account.txt says why)" >> "$REPORT/account.txt"
fi
cat "$REPORT/account.txt" >> "$REPORT/results.txt"
grep '^FAIL' "$REPORT/account.txt" || true
echo "stage account: $(grep -c '^PASS' "$REPORT/account.txt") passed, $(grep -c '^FAIL' "$REPORT/account.txt") failed"
# Named as the builder names it (patch_apk.app_file_name): what it is, the day's stamp, the system and the address, in
# lower case.
APP=opendmtq-phone-app-2026.11.02-android-127.0.0.1-$SITE_PORT.apk
head -c 1048576 /dev/zero > "$DATA/apk/out/$APP"
# With its SHA-256, as the builder writes it: the site tags the download with it, for a broken download to go on.
APP_SHA=$(sha256sum "$DATA/apk/out/$APP" | cut -d' ' -f1)
printf '{"file": "%s", "host": "%s", "built_at": "2026-11-02T09:28:08", "sha256": "%s", "size": 1048576, "patcher": "1.8.0", "runtime": "test", "label": "TECHNIKA Q (%s)", "package": "com.test.opendmtq"}' \
  "$APP" "$HOST" "$APP_SHA" "$HOST" | tee "$DATA/apk/out/latest.json" > "$DATA/apk/out/$APP.json"
# The installer for Windows beside it, as the builder leaves it (tools/opendmtq_tools/windows_client.py): the download
# page's part for computers. Its manifest's hash is left a stand-in, no SHA-256: the site then tags this download by the
# file's size and time, its other way of tagging one, which is checked so.
{ printf 'MZ'; head -c 2097150 /dev/zero; } > "$DATA/apk/out/OpenDMTQ-Setup.exe"
printf '{"file": "OpenDMTQ-Setup.exe", "size": 2097152, "sha256": "0", "version": "0.8.0", "copied_at": "2026-11-02T09:29:00"}' \
  > "$DATA/apk/out/windows.json"
# And one for another address, kept for download: the App page lists it with why players do not get it.
OTHER=opendmtq-phone-app-2026.11.01-android-10.0.0.5-8080.apk
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

# The app's states the home page and the download page speak of, set as the server's start and the builder leave them and
# then put back (audit.js moved): the server moved here an hour ago, the app on offer the old address's and the new one
# being made (address-moved.json, build.json); then the app on offer for this address, made anew a day ago for phones
# (app-new.json, tools/opendmtq_tools/builder.py).
if wanted moved; then
  cp "$DATA/apk/out/latest.json" "$DATA/latest.json.kept"
  now=$(date +%s)
  printf '{"from": "192.168.1.10:8791", "to": "%s", "at": %s}' "$HOST" $((now - 3600)) > "$DATA/state/address-moved.json"
  sed "s/\"host\": \"$HOST\"/\"host\": \"192.168.1.10:8791\"/" "$DATA/latest.json.kept" > "$DATA/apk/out/latest.json"
  printf '{"host": "%s", "state": "building", "time": %s}' "$HOST" "$now" > "$DATA/apk/out/build.json"
  MOVED=building stage moved
  rm -f "$DATA/state/address-moved.json" "$DATA/apk/out/build.json"
  cp "$DATA/latest.json.kept" "$DATA/apk/out/latest.json"
  printf '{"file": "%s", "at": %s, "changed": ["patcher"]}' "$APP" $((now - 86400)) > "$DATA/apk/out/app-new.json"
  MOVED=news stage moved
  rm -f "$DATA/apk/out/app-new.json" "$DATA/latest.json.kept"
fi

# The admin pages from the server PC itself, its browser on the admin service's own network (its loopback): Play on this
# PC as a host install on Linux shows it (how to play from a Windows PC), then as the Windows bundle does, from a second
# admin service on the same data that says it is the bundle (tests/ui/as_windows.py).
here_stage() {
  local target=$1 windows=$2 status=0
  docker run --rm --name "$NAME_PREFIX-uitest-browser" --network "container:$target" --cpus "$BROWSER_CPUS" --memory "$BROWSER_MEMORY" \
    -e SITE="http://127.0.0.1:8000" -e ADMIN="http://127.0.0.1:8000" -e PASSWORD="$PASSWORD" -e OUT=/out -e WINDOWS="$windows" \
    -e SWEEP_WORKERS="$SWEEP_WORKERS" \
    -v "$UI:/usr/src/app/ui:ro" -v "$REPORT:/out" --entrypoint node "$BROWSER_IMAGE" ui/audit.js thispc 2>&1 \
    | tee "$REPORT/last.txt" >> "$REPORT/results.txt" || status=$?
  if [ "$status" -ne 0 ]; then
    FAILED=1
    grep -A32 '^FAIL' "$REPORT/last.txt" | cut -c1-200 || tail -5 "$REPORT/last.txt" | cut -c1-200
  fi
  echo "stage thispc ($([ "$windows" = 1 ] && echo windows || echo linux)): $(grep -c '^PASS' "$REPORT/last.txt") passed, $(grep -c '^FAIL' "$REPORT/last.txt") failed"
}
if wanted thispc; then
  here_stage "$ADMIN" 0
  docker run -d --name "$ADMIN-pc" --network "$NET" --cpus 2 --memory 1g -u 33:33 --read-only --tmpfs /tmp:mode=1777 \
    --tmpfs /home/player:mode=1777 -e HOME=/home/player -e OPENDMTQ_HOST_INSTALL=yes \
    -e PUBLIC_HOST="$HOST" -e ADMIN_PASSWORD="$PASSWORD" -e SERVER_URL="http://$SITE:8080" -e TZ=Asia/Seoul \
    -v "$DATA/state:/data" -v "$DATA/apk:/apk" -v "$DATA/custom:/custom" -v "$DATA/backups:/backups" \
    -v "$DATA/content:/srv/content:ro" -v "$UI:/ui:ro" \
    --entrypoint gunicorn "opendmtq-tools:$TAG" -w 1 --threads 4 -b 0.0.0.0:8000 --pythonpath /ui as_windows:app >/dev/null
  for _ in $(seq 1 30); do
    docker exec "$ADMIN-pc" python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/opendmtq/admin/login', timeout=3)" \
      >/dev/null 2>&1 && break
    sleep 1
  done
  here_stage "$ADMIN-pc" 1
  docker rm -f "$ADMIN-pc" >/dev/null 2>&1 || true
fi

# The keyboard's mark: what the database holds of the plays and bests (seed.php made some with the keyboard), for the pages'
# marks to be held to (audit.js keys): every play [id, player, chart, score, when, keys, record], every best [player, chart,
# score, keys], and each chart's song.
# shellcheck disable=SC2016  # PHP code: its $variables are PHP's, not the shell's.
docker exec "$SITE" php -r '
  $d = new SQLite3("/data/dmtq.db3", SQLITE3_OPEN_READONLY);
  $out = ["plays" => [], "bests" => [], "songs" => []];
  $r = $d->query("SELECT id, user_id, pattern_id, score, played_at, keys, is_record FROM PlayLog ORDER BY id");
  while ($row = $r->fetchArray(SQLITE3_NUM)) { $out["plays"][] = $row; }
  $r = $d->query("SELECT user_id, pattern_id, score, keys FROM Play ORDER BY user_id, pattern_id");
  while ($row = $r->fetchArray(SQLITE3_NUM)) { $out["bests"][] = $row; }
  foreach (json_decode(file_get_contents("/srv/content/songs.json"), true) as $song) {
      foreach ($song["song_patterns"] as $chart) { $out["songs"][$chart["pattern_id"]] = $song["song_id"]; }
  }
  echo json_encode($out);' > "$REPORT/keys.json"
stage keys

# Two players on air while the pages that change are looked at; told to stop, the feed ends both broadcasts.
if wanted air; then
  python3 "$UI/feed.py" air 420 > "$DATA/feed-air.txt" &
  FEED_PID=$!
  # Until both have sent enough to play (feed.py says so), a minute at most.
  for _ in $(seq 1 120); do
    grep -q "^on air" "$DATA/feed-air.txt" 2>/dev/null && break
    sleep 0.5
  done
  stage air
  kill "$FEED_PID" 2>/dev/null || true
  wait "$FEED_PID" 2>/dev/null || true
  FEED_PID=
fi

# The site's pages left open while the owner begins, changes and ends maintenance (broadcasts still on, so that the home
# page and the live page look at the server by themselves).
stage notices

stage maint
# The owner's notice on the site: put up, on every page, closed for a visit, new words, and the pages left open.
stage notice
stage flows
# MY PAGE: the account's own page for an account linked to its player, one that is not and the owner's; its changes.
# The stand-in catalog again first, with the names its slots are shown by.
stand_in_catalog
stage mine
# Nothing said only under a mouse pointer, switches that change the page where it is, the forms' words under their fields.
stage patterns

# Broadcasts off again, as most servers have them, with the players, records and recordings in place: nothing of
# broadcasts on the site, every page whole without them, and the owner's pages saying they are off.
if wanted quiet; then
  python3 "$UI/feed.py" quiet
  stage quiet
fi

# The game server going away and coming back, twice, while the owner's pages stay open in the browser (audit.js away): the
# browser says where it is through files in the report folder, and this side stops the server when it is ready and starts
# it again once the pages have said it is gone. In the background, the browser's stage in front, as every stage.
if wanted away; then
  rm -f "$REPORT"/away-*
  (
    seen() { for _ in $(seq 1 240); do [ -f "$REPORT/$1" ] && return 0; sleep 1; done; return 1; }
    for round in 1 2; do
      seen "away-ready-$round" || break
      docker stop "$SITE" >/dev/null
      touch "$REPORT/away-down-$round"
      seen "away-seen-down-$round" || true
      docker start "$SITE" >/dev/null
      for _ in $(seq 1 60); do curl -sf -m 3 -o /dev/null "http://127.0.0.1:$SITE_PORT/opendmtq/health.php" && break; sleep 1; done
      touch "$REPORT/away-up-$round"
      seen "away-seen-up-$round" || true
    done
  ) &
  AWAY_PID=$!
  stage away
  wait "$AWAY_PID" 2>/dev/null || true
  # Running again for what comes after, whatever happened in the browser.
  docker start "$SITE" >/dev/null 2>&1 || true
  for _ in $(seq 1 60); do curl -sf -m 3 -o /dev/null "http://127.0.0.1:$SITE_PORT/opendmtq/health.php" && break; sleep 1; done
fi

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
