#!/usr/bin/env bash
# The live view's smoke test on a throwaway server: builds the images from this working tree, starts
# the server and the admin service on loopback with an empty database in a temporary folder, runs
# smoke.py against them and removes everything again. Needs the client data and the song data in data/content
# (./opendmtq import --songs <folder with your game files>).
#
# KEEP=1 leaves the stack up after the test and prints how to remove it. BROWSER=1 also plays a real
# H.264 recording in headless Chromium (pulls ffmpeg and Chromium images).
# Usage: tests/live/run.sh
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
TAG=livetest
NET=odq-livetest
SITE=odq-livetest-site
ADMIN=odq-livetest-admin
SITE_PORT=${SITE_PORT:-18597}
ADMIN_PORT=${ADMIN_PORT:-18598}
HOST=live-test.example.net:8790
DATA=$(mktemp -d)

# What the containers wrote belongs to their user: removed from inside an image.
cleanup() {
  docker rm -f "$SITE" "$ADMIN" "$SITE-small" "$SITE-tls" "$SITE-router" "$SITE-echo" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  docker run --rm -u 0 -v "$DATA:/d" --entrypoint sh "opendmtq-server:$TAG" -c 'rm -rf /d/* /d/.[!.]*' >/dev/null 2>&1 || true
  rmdir "$DATA" 2>/dev/null || true
}
if [ -z "${KEEP:-}" ]; then
  trap cleanup EXIT
fi

docker build -q -t "opendmtq-server:$TAG" "$ROOT/server" >/dev/null
docker build -q -t "opendmtq-tools:$TAG" "$ROOT/tools" >/dev/null

mkdir -p "$DATA/state" "$DATA/apk/out" "$DATA/custom" "$DATA/backups"
chmod -R a+rwX "$DATA"
docker network create "$NET" >/dev/null 2>&1 || true
docker rm -f "$SITE" "$ADMIN" "$SITE-small" >/dev/null 2>&1 || true
# Capped: a smoke test, not a load.
docker run -d --name "$SITE" --network "$NET" --cpus 2 --memory 1g -u 33:33 --read-only \
  --tmpfs /var/opendmtq:mode=1777 --tmpfs /tmp:mode=1777 \
  -e PUBLIC_HOST="$HOST" -e ADMIN_ON_PUBLIC_PORT=no -e TZ=Asia/Seoul \
  -v "$ROOT/data/content:/srv/content:ro" -v "$DATA/state:/data" -v "$DATA/apk/out:/srv/apk:ro" -v "$DATA/custom:/srv/custom:ro" \
  -p "127.0.0.1:$SITE_PORT:8080" "opendmtq-server:$TAG" >/dev/null
docker run -d --name "$ADMIN" --network "$NET" --cpus 2 --memory 1g -u 33:33 --read-only --tmpfs /tmp:mode=1777 \
  -e PUBLIC_HOST="$HOST" -e ADMIN_PASSWORD=smoke -e SERVER_URL="http://$SITE:8080" -e HOME=/tmp -e TZ=Asia/Seoul \
  -v "$DATA/state:/data" -v "$DATA/apk:/apk" -v "$DATA/custom:/custom" -v "$DATA/backups:/backups" \
  -v "$ROOT/data/content:/srv/content:ro" -p "127.0.0.1:$ADMIN_PORT:8000" \
  --entrypoint gunicorn "opendmtq-tools:$TAG" -w 1 --threads 4 -b 0.0.0.0:8000 opendmtq_tools.admin:app >/dev/null

# Until both answer, or give up with their logs.
for _ in $(seq 1 120); do
  if curl -sf -o /dev/null "http://127.0.0.1:$SITE_PORT/opendmtq/health.php" \
    && curl -sf -o /dev/null "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/login"; then
    break
  fi
  sleep 1
done
if ! curl -sf -o /dev/null "http://127.0.0.1:$SITE_PORT/opendmtq/health.php"; then
  echo "the server did not come up" >&2
  docker logs --tail 30 "$SITE" >&2
  exit 1
fi

# Forty seconds of real video for the browser, longer than a recording may fetch ahead, made with no network and capped
# like the rest. The sound is noise: no stretch of it is like another, so a skip or a repeat cannot pass for the music going on.
# Without the encoder's noise substitution, whose sound a decoder makes up: two decoders would differ with nothing wrong.
# The sound starts 155 ms after the picture, as a phone's does: a player has to fill that gap, and filling it with the wrong
# kind of silence garbled everything heard after it.
if [ -n "${BROWSER:-}" ]; then
  mkdir -p "$DATA/ts"
  docker run --rm --network none --cpus 2 --memory 1g -v "$DATA/ts:/o" mwader/static-ffmpeg:7.1 -hide_banner -loglevel error -y \
    -f lavfi -i testsrc2=size=1280x720:rate=30 -itsoffset 0.155 -f lavfi -i anoisesrc=color=pink:amplitude=0.25:seed=7 -t 40 -map 0:v -map 1:a \
    -c:v libx264 -preset veryfast -profile:v main -pix_fmt yuv420p -g 60 -keyint_min 60 -sc_threshold 0 -b:v 2M \
    -c:a aac -b:a 128k -ac 2 -aac_pns 0 -f segment -segment_time 2 -segment_format mpegts /o/%d.ts
  export LIVE_TS_DIR="$DATA/ts"
fi

OUT=$DATA/smoke.txt
set +e
# The admin password, then the password of the site account the test makes (six letters at least, as any account).
python3 "$ROOT/tests/live/smoke.py" "http://127.0.0.1:$SITE_PORT" "http://127.0.0.1:$ADMIN_PORT" smoke smoke-site | tee "$OUT"
status=${PIPESTATUS[0]}
set -e
if [ "$status" -ne 0 ]; then
  exit "$status"
fi

# What needs the clock or the files: a recording left open by a phone that vanished closes, and one past
# the age limit goes. From inside the server, whose user owns the files.
docker exec "$SITE" sh -c '
  old=/data/live-rec/999/1000000000; gone=/data/live-rec/999/1000000500
  mkdir -p $old $gone; : > $old/.open; echo "0 2000 0 188" > $old/segs.log; : > $old/0.ts; touch -d @1000000100 $old/segs.log
  echo "{\"guid\":999,\"id\":1000000500,\"started\":1000000500,\"ended\":1000000600,\"duration_ms\":2000,\"size\":188}" > $gone/meta.json
  rm -f /data/live/.swept'
curl -sf -o /dev/null "http://127.0.0.1:$SITE_PORT/opendmtq/health.php"
if docker exec "$SITE" sh -c 'ls /data/live-rec/999 2>/dev/null' | grep -q .; then
  echo "FAIL the sweep left the vanished phone's recording open, or kept one past the age limit" >&2
  exit 1
fi
echo "PASS the health check's sweep closes a vanished phone's recording and removes those past the age limit"

# A huge list must not stop the cleanup for everyone: 300000 lines, read and closed within PHP's memory.
docker exec "$SITE" sh -c '
  rec=/data/live-rec/999/1000000000
  mkdir -p $rec; : > $rec/.open; seq 1 300000 | sed "s/$/ 2000 0 1880/" > $rec/segs.log; touch -d @$(($(date +%s) - 400)) $rec/segs.log
  rm -f /data/live/.swept'
curl -sf -o /dev/null "http://127.0.0.1:$SITE_PORT/opendmtq/health.php"
if ! docker exec "$SITE" sh -c 'test ! -e /data/live-rec/999/1000000000/.open && grep -q "\"size\":564000000" /data/live-rec/999/1000000000/meta.json'; then
  echo "FAIL a recording with a very long list was not closed" >&2
  docker logs --tail 5 "$SITE" >&2
  exit 1
fi
docker exec "$SITE" rm -rf /data/live-rec/999
echo "PASS a 300000-line recording closes and the cleanup goes on"

# The cap on one recording's length, an hour (1800 segments of two seconds), with the stream's own count moved to it:
# the next video starts a new recording. (With the cap a day long, as before, it would not.)
read -r _ IDS TOKEN GUID < <(grep '^HARNESS ' "$OUT")
UPLOAD="http://127.0.0.1:$SITE_PORT/live/upload?ids=$IDS&dur=2000"
BODY=$DATA/seg.ts
head -c 3760 /dev/zero | tr '\0' G > "$BODY"
curl -s -o /dev/null -H "X-Live-Token: $TOKEN" --data-binary @"$BODY" "$UPLOAD&seq=0"
docker exec "$SITE" php -r '$p = "/data/live/" . $argv[1] . "/stream.json"; $s = json_decode(file_get_contents($p), true); $s["rec_segs"] = 1800; file_put_contents($p, json_encode($s));' "$GUID"
curl -s -o /dev/null -H "X-Live-Token: $TOKEN" --data-binary @"$BODY" "$UPLOAD&seq=1"
if [ "$(docker exec "$SITE" sh -c "ls /data/live-rec/$GUID | wc -l")" != 2 ]; then
  echo "FAIL a recording at its maximum length did not roll over" >&2
  exit 1
fi
echo "PASS a recording at its maximum length rolls over"

# The database in write-ahead mode, as a disk like this one allows.
if [ "$(docker exec "$SITE" php -r '$d = new SQLite3("/data/dmtq.db3"); echo $d->querySingle("PRAGMA journal_mode");')" != wal ]; then
  echo "FAIL the database is not in write-ahead mode" >&2
  exit 1
fi
echo "PASS the database runs in write-ahead mode"

# A save while something holds the database longer than a save waits: the phone must hear it failed,
# where it used to be told it was saved with nothing stored. Then the retry goes through.
save_body='[{"id":1,"method":"game.savePlayResult","params":['"$GUID"',920001,[0,0,0,0,0,0,0,0,0,0,0,0,500],500,0,[0,0,0],[0,0,0],"smoke"]}]'
save_fp=$(printf 'DMQGLBlive1%s' "$save_body" | md5sum | cut -d' ' -f1)
docker exec "$SITE" php -r '$d = new SQLite3("/data/dmtq.db3"); $d->exec("BEGIN IMMEDIATE"); touch("/tmp/held"); sleep(9); $d->exec("ROLLBACK");' &
holder=$!
for _ in $(seq 1 50); do docker exec "$SITE" test -e /tmp/held && break; sleep 0.1; done
reply=$(curl -s -H "Fp: $save_fp" --data-binary "$save_body" "http://127.0.0.1:$SITE_PORT/DMQ/rpc")
wait "$holder"
stored=$(docker exec "$SITE" php -r '$d = new SQLite3("/data/dmtq.db3"); echo $d->querySingle("SELECT COUNT(*) FROM Play WHERE pattern_id = 920001");')
case "$reply" in
  *SVC.05099*) [ "$stored" = 0 ] || { echo "FAIL a refused save was stored: $stored" >&2; exit 1; } ;;
  *) echo "FAIL a save the database did not take answered: $reply (rows: $stored)" >&2; exit 1 ;;
esac
reply=$(curl -s -H "Fp: $save_fp" --data-binary "$save_body" "http://127.0.0.1:$SITE_PORT/DMQ/rpc")
stored=$(docker exec "$SITE" php -r '$d = new SQLite3("/data/dmtq.db3"); echo $d->querySingle("SELECT COUNT(*) FROM Play WHERE pattern_id = 920001");')
case "$reply" in
  *is_success*) [ "$stored" = 1 ] || { echo "FAIL the retry stored $stored rows" >&2; exit 1; } ;;
  *) echo "FAIL the retried save answered: $reply" >&2; exit 1 ;;
esac
echo "PASS a save the database cannot take says so, stores nothing, and its retry goes through"

# Plays must not reach the database half: a statement failing inside a save loses all of it, and says so.
docker exec "$SITE" php -r '$d = new SQLite3("/data/dmtq.db3"); $d->exec("CREATE TRIGGER smoke_refuse BEFORE INSERT ON Play WHEN NEW.pattern_id = 920002 BEGIN SELECT RAISE(ABORT, \"refused\"); END");'
save_body2=${save_body/920001/920002}
save_fp2=$(printf 'DMQGLBlive1%s' "$save_body2" | md5sum | cut -d' ' -f1)
reply=$(curl -s -H "Fp: $save_fp2" --data-binary "$save_body2" "http://127.0.0.1:$SITE_PORT/DMQ/rpc")
logged=$(docker exec "$SITE" php -r '$d = new SQLite3("/data/dmtq.db3"); $d->exec("DROP TRIGGER smoke_refuse"); echo $d->querySingle("SELECT COUNT(*) FROM PlayLog WHERE pattern_id = 920002");')
case "$reply" in
  *SVC.05099*) [ "$logged" = 0 ] || { echo "FAIL a failed save left $logged history rows" >&2; exit 1; } ;;
  *) echo "FAIL a save whose statement failed answered: $reply" >&2; exit 1 ;;
esac
echo "PASS a save whose statement fails keeps nothing and says so"

# A database from before these rules: two rows for a player and chart become the best of each at start.
docker exec "$SITE" php -r '$d = new SQLite3("/data/dmtq.db3"); $d->exec("DROP INDEX Play_one"); $d->exec("INSERT INTO Play VALUES (920003, 77, 100, \"B\", \"Y\", \"N\", 800), (920003, 77, 300, \"A\", \"N\", \"N\", 700);");'
docker restart "$SITE" >/dev/null
for _ in $(seq 1 60); do curl -sf -o /dev/null "http://127.0.0.1:$SITE_PORT/opendmtq/health.php" && break; sleep 1; done
merged=$(docker exec "$SITE" php -r '$d = new SQLite3("/data/dmtq.db3"); echo json_encode($d->querySingle("SELECT COUNT(*) || \"/\" || MAX(score) || \"/\" || MAX(grade) || \"/\" || MAX(isAllCombo) || \"/\" || MAX(judgement) FROM Play WHERE pattern_id = 920003")), $d->querySingle("SELECT COUNT(*) FROM sqlite_master WHERE name = \"Play_one\"");')
if [ "$merged" != '"1\/300\/B\/Y\/800"1' ]; then
  echo "FAIL rows of one player and chart were not merged: $merged" >&2
  exit 1
fi
echo "PASS a player's two rows on one chart are merged at start, the best of each"

# The in-game rankings are this month's: a play from before the first of the month at midnight UTC (when the game's
# countdown ends) is not ranked, one of this month is; the player's own best keeps both (MAX SCORE on the song).
docker exec "$SITE" php -r '
  $d = new SQLite3("/data/dmtq.db3");
  $start = gmmktime(0, 0, 0, (int)gmdate("n"), 1, (int)gmdate("Y"));
  $d->exec("INSERT INTO Member (id, nickname, guid, udid) VALUES (4242, \"LastMonth\", \"4242\", \"live-smoke-last-month\")");
  $d->exec("INSERT INTO Play VALUES (920004, 4242, 999999, \"S\", \"N\", \"N\", 1000), (920005, 4242, 5, \"F\", \"N\", \"N\", 100)");
  $d->exec("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at) VALUES (4242, 920004, 999999, \"S\", 1000, 1, " . ($start - 3600) . "), (4242, 920005, 5, \"F\", 100, 1, " . time() . ")");'
rpc() {
  local body="[{\"id\":1,\"method\":\"$1\",\"params\":$2}]"
  curl -s -H "Content-Type: application/json" -H "Fp: $(printf 'DMQGLBlive1%s' "$body" | md5sum | cut -d' ' -f1)" --data "$body" "http://127.0.0.1:$SITE_PORT/DMQ/rpc"
}
ranked=$(rpc game.getLineTopRankWithLevel '[0, 1, 100, [4242]]' | python3 -c 'import json, sys; print([r["score"] for r in json.load(sys.stdin)[0]["result"]["ranks"] if r["guid"] == 4242])')
best=$(rpc game.getOwnPatternScore '[4242]' | python3 -c 'import json, sys; print(sorted(r["score"] for r in json.load(sys.stdin)[0]["result"]))')
if [ "$ranked" != "[5]" ] || [ "$best" != "[5, 999999]" ]; then
  echo "FAIL the in-game ranking is not this month's: ranked $ranked, own best $best" >&2
  exit 1
fi
echo "PASS the in-game ranking counts this month's plays only; the player's own best keeps every month"

# An achievement once earned stays earned, with its date, whatever the records give now (the log keeps a year, and
# the clears of a difficulty are counted there): one stored for a player whose records do not give it is listed
# with the stored date, and a save of theirs does not name it as new.
docker exec "$SITE" php -r '$d = new SQLite3("/data/dmtq.db3"); $d->exec("INSERT INTO AchievementDate (user_id, achievement_id, earned_at) VALUES (4242, 23, 1700000000)");'
kept=$(rpc game.getOwnAchievementList '[4242]' | python3 -c 'import json, sys; print([a["reg_date"] for a in json.load(sys.stdin)[0]["result"]["own_achievements"] if a["achievement_id"] == 23])')
again=$(rpc game.savePlayResult '[4242, 920006, [0,0,0,0,0,0,0,0,0,0,0,0,500], 500, 0, [0,0,0], [0,0,0], "smoke"]' | python3 -c 'import json, sys; print(sorted(a["achievement_id"] for a in json.load(sys.stdin)[0]["result"]["new_achievements"]))')
# 1700000000 in the test server's zone (TZ=Asia/Seoul, above): 2023-11-15 07:13:20. The save earns ALL COMBO and
# PERFECT PLAY, the first for this player, and only those.
if [ "$kept" != "['20231115071320']" ] || [ "$again" != "[13, 14]" ]; then
  echo "FAIL a stored achievement the records do not give: listed $kept, a save named $again as new" >&2
  exit 1
fi
echo "PASS a stored achievement stays listed with its date, and is not named as new again"

# A nearly full disk: the recordings' folder on a small disk of its own, in a second server on the same
# data. The upload is refused before anything is written.
docker run -d --name "$SITE-small" --network "$NET" --cpus 1 --memory 512m -u 33:33 --read-only \
  --tmpfs /var/opendmtq:mode=1777 --tmpfs /tmp:mode=1777 --tmpfs /data/live-rec:size=64m,mode=1777 \
  -e PUBLIC_HOST="$HOST" -e ADMIN_ON_PUBLIC_PORT=no -e TZ=Asia/Seoul \
  -v "$ROOT/data/content:/srv/content:ro" -v "$DATA/state:/data" -v "$DATA/apk/out:/srv/apk:ro" -v "$DATA/custom:/srv/custom:ro" \
  -p "127.0.0.1:$((SITE_PORT + 2)):8080" "opendmtq-server:$TAG" >/dev/null
for _ in $(seq 1 60); do
  curl -s -o /dev/null "http://127.0.0.1:$((SITE_PORT + 2))/opendmtq/health.php" && break
  sleep 1
done
code=$(curl -s -o /dev/null -w '%{http_code}' -H "X-Live-Token: $TOKEN" --data-binary @"$BODY" "http://127.0.0.1:$((SITE_PORT + 2))/live/upload?ids=$IDS&dur=2000&seq=2")
left=$(docker exec "$SITE-small" sh -c "ls /data/live/$GUID/*.ts 2>/dev/null | wc -l")
docker rm -f "$SITE-small" >/dev/null
if [ "$code" != 503 ] || [ "$left" != 0 ]; then
  echo "FAIL a nearly full disk: answer $code, $left segments written" >&2
  exit 1
fi
echo "PASS a nearly full disk: 503, nothing written"

# Browsers go to HTTPS while it works, and only browsers on the portal's pages: a server with a certificate on
# the same data, asked as the edge asks its plain door (PROXY header first).
mkdir -p "$DATA/https"
: > "$DATA/https/ca.crt"
chmod -R a+rX "$DATA/https"
docker run -d --name "$SITE-tls" --network "$NET" --cpus 1 --memory 512m -u 33:33 --read-only \
  --tmpfs /var/opendmtq:mode=1777 --tmpfs /tmp:mode=1777 \
  -e PUBLIC_HOST="$HOST" -e ADMIN_ON_PUBLIC_PORT=yes -e ADMIN_URL=http://$ADMIN:8000 -e TZ=Asia/Seoul \
  -v "$ROOT/data/content:/srv/content:ro" -v "$DATA/state:/data" -v "$DATA/apk/out:/srv/apk:ro" -v "$DATA/custom:/srv/custom:ro" \
  -v "$DATA/https:/srv/https:ro" -p "127.0.0.1:$((SITE_PORT + 3)):8080" "opendmtq-server:$TAG" >/dev/null
for _ in $(seq 1 60); do
  curl -s -o /dev/null "http://127.0.0.1:$((SITE_PORT + 3))/opendmtq/health.php" && break
  sleep 1
done
# The status and where it leads, for one request: method, path, user agent.
door() {
  docker exec "$SITE-tls" php -r '
    $s = fsockopen("127.0.0.1", 8081);
    fwrite($s, "PROXY TCP4 203.0.113.9 127.0.0.1 1234 8081\r\n$argv[1] $argv[2] HTTP/1.0\r\nHost: live-test.example.net:8790\r\nUser-Agent: $argv[3]\r\n\r\n");
    $head = stream_get_contents($s, 2048);
    preg_match("# (\d+) #", $head, $m); preg_match("#Location: (\S+)#i", $head, $l);
    echo $m[1], " ", $l[1] ?? "", "\n";' "$1" "$2" "$3"
}
expect_door() {
  got=$(door "$1" "$2" "$3")
  # A pattern on purpose: the expected answer may end in *.
  # shellcheck disable=SC2254
  case "$got" in
    $4) echo "PASS $1 $2 ($3) on the plain door: $got" ;;
    *) echo "FAIL $1 $2 ($3) on the plain door: $got, not $4" >&2; docker rm -f "$SITE-tls" >/dev/null; exit 1 ;;
  esac
}
to_https="https://live-test.example.net:8790"
expect_door GET "/" Chrome "302 $to_https/"
expect_door GET "/opendmtq/" Chrome "302 $to_https/opendmtq/"
expect_door GET "/opendmtq/ranking.php?sort=s_count" Chrome "302 $to_https/opendmtq/ranking.php?sort=s_count"
expect_door GET "/opendmtq/download.php" Chrome "302 $to_https/opendmtq/download.php"
expect_door GET "/opendmtq/login.php?next=%2Fapk" Chrome "302 $to_https/opendmtq/login.php?next=%2Fapk"
expect_door GET "/opendmtq/health.php" Chrome "200 *"
expect_door GET "/opendmtq/style.css" Chrome "200 *"
expect_door POST "/opendmtq/login.php" Chrome "200 *"
expect_door GET "/apk" Chrome "302 /opendmtq/login.php*"
# A messenger's own browser stays on plain HTTP, where the site's sign-in comes first.
expect_door GET "/opendmtq/" "Mozilla KAKAOTALK 10" "302 /opendmtq/login.php?next=%2Fopendmtq%2F"
expect_door GET "/opendmtq/login.php?next=%2Fopendmtq%2F" "Mozilla KAKAOTALK 10" "200 *"
# Any other app's own browser: an Android WebView says so in its user agent.
expect_door GET "/opendmtq/" "Mozilla/5.0 (Linux; Android 13; wv) AppleWebKit Telegram" "302 /opendmtq/login.php*"
expect_door GET "/opendmtq/login.php?next=%2Fopendmtq%2F" "Mozilla/5.0 (Linux; Android 13; wv) AppleWebKit Telegram" "200 *"
# To the address that was asked for: on the server's own network the public name may not lead here.
got=$(docker exec "$SITE-tls" php -r '$s = fsockopen("127.0.0.1", 8081); fwrite($s, "PROXY TCP4 203.0.113.9 127.0.0.1 1234 8081\r\nGET /opendmtq/ HTTP/1.0\r\nHost: other.example.net:8790\r\nUser-Agent: Chrome\r\n\r\n"); $head = stream_get_contents($s, 2048); preg_match("#Location: (\S+)#i", $head, $l); echo $l[1] ?? "";')
if [ "$got" != "https://other.example.net:8790/opendmtq/" ]; then
  echo "FAIL the plain door keeps the address that was asked for: $got" >&2
  docker rm -f "$SITE-tls" >/dev/null
  exit 1
fi
echo "PASS the plain door keeps the address that was asked for"
# What the plain door says to a browser asking for this Host.
door_location() {
  docker exec "$SITE-tls" php -r '$s = fsockopen("127.0.0.1", 8081); fwrite($s, "PROXY TCP4 203.0.113.9 127.0.0.1 1234 8081\r\nGET /opendmtq/ HTTP/1.0\r\nHost: $argv[1]\r\nUser-Agent: Chrome\r\n\r\n"); preg_match("/^Location: (.*?)\r$/m", stream_get_contents($s), $m); echo $m[1] ?? "stays";' "$1"
}
expect_location() {
  got=$(door_location "$1")
  if [ "$got" != "$2" ]; then
    echo "FAIL a browser at $1: $got, not $2" >&2
    docker rm -f "$SITE-tls" >/dev/null
    exit 1
  fi
  echo "PASS a browser at $1: $got"
}
# On port 80 the address has no port, and HTTPS is on the same port: nothing answers on 443.
expect_location game.example.com "https://game.example.com:80/opendmtq/"
# On a local network, a new player's first visit is not a certificate warning: the site's sign-in, on plain HTTP here.
here_sign_in="/opendmtq/login.php?next=%2Fopendmtq%2F"
expect_location 192.168.0.10 "$here_sign_in"
expect_location 192.168.0.10:8080 "$here_sign_in"
expect_location 172.30.1.5 "$here_sign_in"
expect_location 10.1.2.3:8790 "$here_sign_in"
expect_location localhost:8790 "$here_sign_in"
# A public address that only starts like a private one.
expect_location 172.32.1.5 "https://172.32.1.5:80/opendmtq/"
expect_location 10.example.com "https://10.example.com:80/opendmtq/"
expect_door GET "/live/state?ids=nobody" Chrome "200 *"
# The API is refused on the plain door while HTTPS works: its token went out in clear already, and a redirect would have a
# script send it again. A 403 in the API's own JSON, with the address to use (use_https), and nothing passed on.
expect_door GET "/opendmtq/api/v1/status" curl "403 "
expect_door POST "/opendmtq/api/v1/builds" curl "403 "
got=$(docker exec "$SITE-tls" php -r '
  $s = fsockopen("127.0.0.1", 8081);
  fwrite($s, "PROXY TCP4 203.0.113.9 127.0.0.1 1234 8081\r\nGET /opendmtq/api/v1/status HTTP/1.0\r\nHost: live-test.example.net:8790\r\nUser-Agent: curl\r\n\r\n");
  $all = stream_get_contents($s);
  preg_match("#Content-Type: ([^;\r\n]+)#i", $all, $c);
  $e = json_decode(substr($all, strpos($all, "\r\n\r\n") + 4), true)["error"] ?? [];
  echo $c[1] ?? "-", " ", $e["code"] ?? "-", " ", $e["message"] ?? "-";')
if [ "$got" != "application/json use_https This address takes the API over HTTPS only: $to_https/opendmtq/api/v1/" ]; then
  echo "FAIL the API's refusal on the plain door: $got" >&2
  docker rm -f "$SITE-tls" >/dev/null
  exit 1
fi
echo "PASS the API's refusal on the plain door: $got"
# Behind the Helm chart's router, which ends HTTPS and says how each visit came (router.tls): the one door takes both.
# In place of the admin service, something that answers with the visitor's address as the server passed it on.
docker run -d --name "$SITE-echo" --network "$NET" --entrypoint python3 "opendmtq-tools:$TAG" -c '
import http.server
class Echo(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = str(self.headers.get("X-Real-IP")).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
http.server.HTTPServer(("0.0.0.0", 8000), Echo).serve_forever()' >/dev/null
docker run -d --name "$SITE-router" --network "$NET" --cpus 2 --memory 1g -u 33:33 --read-only \
  --tmpfs /var/opendmtq:mode=1777 --tmpfs /tmp:mode=1777 \
  -e PUBLIC_HOST=game.example.com:8790 -e EDGE_DOORS=no -e ROUTER_TLS=yes -e ADMIN_ON_PUBLIC_PORT=yes -e ADMIN_URL="http://$SITE-echo:8000" -e TZ=Asia/Seoul \
  -v "$ROOT/data/content:/srv/content:ro" -v "$DATA/state:/data" -v "$DATA/apk/out:/srv/apk:ro" -v "$DATA/custom:/srv/custom:ro" \
  -p "127.0.0.1:$((SITE_PORT + 4)):8080" "opendmtq-server:$TAG" >/dev/null
for _ in $(seq 1 60); do
  curl -s -o /dev/null "http://127.0.0.1:$((SITE_PORT + 4))/opendmtq/health.php" && break
  sleep 1
done
# The status and where it leads, for a visit the router marked plain or HTTPS.
routed() {
  curl -s -m 10 -o /dev/null -w '%{http_code} %{redirect_url}' -A Chrome -H "Host: $1" -H "X-Forwarded-Proto: $2" "http://127.0.0.1:$((SITE_PORT + 4))$3"
}
expect_routed() {
  got=$(routed "$1" "$2" "$3")
  # shellcheck disable=SC2254  # The expected value is a pattern.
  case "$got" in
    $4) echo "PASS behind the router, $2 $1$3: $got" ;;
    *)
      echo "FAIL behind the router, $2 $1$3: $got, expected $4" >&2
      docker rm -f "$SITE-router" "$SITE-echo" "$SITE-tls" >/dev/null
      exit 1
      ;;
  esac
}
expect_routed game.example.com:8790 http /opendmtq/ "302 https://game.example.com:8790/opendmtq/"
expect_routed game.example.com http /opendmtq/ "302 https://game.example.com:80/opendmtq/"
# Over HTTPS the site's sign-in comes first, by a relative address that keeps the visitor on HTTPS (curl shows it resolved
# against the address it asked, the router's own).
expect_routed game.example.com:8790 https /opendmtq/ "302 http://127.0.0.1:$((SITE_PORT + 4))/opendmtq/login.php?next=%2Fopendmtq%2F"
expect_routed game.example.com:8790 https /opendmtq "301 https://game.example.com:8790/opendmtq/"
expect_routed game.example.com:8790 http /opendmtq/admin/login "302 https://game.example.com:8790/opendmtq/admin/login"
# Their address until 2026-11 goes straight to the new one there.
expect_routed game.example.com:8790 http /admin/login "302 https://game.example.com:8790/opendmtq/admin/login"
# The API is refused on a plain visit, as on the edge's plain door (403 use_https, in JSON).
expect_routed game.example.com:8790 http /opendmtq/api/v1/status "403 "
got=$(curl -s -m 10 -H "Host: game.example.com:8790" -H "X-Forwarded-Proto: http" "http://127.0.0.1:$((SITE_PORT + 4))/opendmtq/api/v1/status" \
  | python3 -c 'import json, sys; e = json.load(sys.stdin)["error"]; print(e["code"], e["message"])')
if [ "$got" != "use_https This address takes the API over HTTPS only: https://game.example.com:8790/opendmtq/api/v1/" ]; then
  echo "FAIL behind the router, the API's refusal: $got" >&2
  docker rm -f "$SITE-router" "$SITE-echo" "$SITE-tls" >/dev/null
  exit 1
fi
echo "PASS behind the router, the API's refusal: $got"
# A health check, or anything else in the cluster, says nothing about how it came and is left alone.
# (It may go to the site's sign-in, on the same door; not to HTTPS.)
got=$(curl -s -m 10 -o /dev/null -w '%{http_code} %{redirect_url}' -A Chrome "http://127.0.0.1:$((SITE_PORT + 4))/opendmtq/")
if [[ "$got" == *https:* ]] || [[ "$got" != 302\ http://* ]]; then
  echo "FAIL a request that does not say how it came is sent to HTTPS" >&2
  docker rm -f "$SITE-router" "$SITE-echo" "$SITE-tls" >/dev/null
  exit 1
fi
echo "PASS a request that does not say how it came stays"
# The admin's sign-in throttle counts per visitor: with no address passed on, one stranger locks everyone out.
got=$(curl -s -m 10 -H "X-Forwarded-Proto: https" -H "X-Forwarded-For: 198.51.100.7" "http://127.0.0.1:$((SITE_PORT + 4))/opendmtq/admin/who")
if [ "$got" != "198.51.100.7" ]; then
  echo "FAIL the admin service is told the visitor's address: $got" >&2
  docker rm -f "$SITE-router" "$SITE-echo" "$SITE-tls" >/dev/null
  exit 1
fi
echo "PASS the admin service is told the visitor's address"
# So are the API's requests: a wrong token counts against the visitor's own address in the same throttle.
got=$(curl -s -m 10 -H "X-Forwarded-Proto: https" -H "X-Forwarded-For: 198.51.100.7" "http://127.0.0.1:$((SITE_PORT + 4))/opendmtq/api/v1/who")
if [ "$got" != "198.51.100.7" ]; then
  echo "FAIL the API is told the visitor's address: $got" >&2
  docker rm -f "$SITE-router" "$SITE-echo" "$SITE-tls" >/dev/null
  exit 1
fi
echo "PASS the API is told the visitor's address"
docker rm -f "$SITE-router" "$SITE-echo" >/dev/null
# The portal's footer leads to the admin pages only where they are on this port.
# (A stranger sees the footer on the sign-in page the site sends them to.)
if ! curl -sL "http://127.0.0.1:$((SITE_PORT + 3))/opendmtq/" | grep -q 'href="/opendmtq/admin/"'; then
  echo "FAIL no way to the admin pages in the footer, with them on the public port" >&2
  docker rm -f "$SITE-tls" >/dev/null
  exit 1
fi
if curl -sL "http://127.0.0.1:$SITE_PORT/opendmtq/" | grep -q 'href="/opendmtq/admin/"'; then
  echo "FAIL a way to the admin pages in the footer, with them off the public port" >&2
  docker rm -f "$SITE-tls" >/dev/null
  exit 1
fi
echo "PASS the footer links to the admin pages only when they are on the public port"
# With the admin pages off the public port, the API is not there either.
got=$(curl -s -m 10 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$SITE_PORT/opendmtq/api/v1/status")
if [ "$got" != 404 ]; then
  echo "FAIL the API answers on a public port the admin pages are kept off: $got" >&2
  docker rm -f "$SITE-tls" >/dev/null
  exit 1
fi
echo "PASS the API is off the public port with the admin pages"
# The admin pages' address until 2026-11 (/admin) leads to the same page at /opendmtq/admin through the server too: here
# straight to HTTPS, which this server has.
got=$(curl -s -m 10 -o /dev/null -w '%{http_code} %{redirect_url}' "http://127.0.0.1:$((SITE_PORT + 3))/admin/players")
case "$got" in
  "302 https://"*"/opendmtq/admin/players") echo "PASS the old admin address leads to the new one through the server: $got" ;;
  *)
    echo "FAIL the old admin address through the server: $got, expected 302 to https://.../opendmtq/admin/players" >&2
    docker rm -f "$SITE-tls" >/dev/null
    exit 1
    ;;
esac
docker rm -f "$SITE-tls" >/dev/null

if [ -n "${BROWSER:-}" ]; then
  # The browser image runs as its own user: the folder for its screenshots must be open to it. Docker would
  # create a missing one as root, and the test would die on its first screenshot.
  SHOTS=${SHOTS:-$DATA/ts}
  mkdir -p "$SHOTS"
  chmod a+rwx "$SHOTS"
  docker run --rm --network host --cpus 2 --memory 2g -v "$ROOT/tests/live:/usr/src/app/x:ro" -v "$SHOTS:/shots" \
    --entrypoint node zenika/alpine-chrome:with-puppeteer x/browser.js "$SITE_PORT" "$ADMIN_PORT" "$(sed -n 's/^RECORDING //p' "$OUT")"
  "$ROOT/tests/live/sound/run.sh" "$SITE_PORT" "$(sed -n 's/^RECORDING //p' "$OUT")" "$DATA/ts"
fi

# Switching off removed the stream from disk (all the HTTP answers above could say that without).
if [ -n "$(find "$DATA/state/live" -name '*.ts')" ]; then
  echo "FAIL segments left on disk after switching off" >&2
  exit 1
fi

# PHP warnings in the server's log would mean an endpoint misbehaved even where its answer was right.
# (But for the one this script caused itself, by refusing a statement inside a save.)
if docker logs "$SITE" 2>&1 | grep -E "PHP (Warning|Notice|Fatal|Parse)" | grep -v "Unable to execute statement: refused"; then
  echo "FAIL PHP complained (above)" >&2
  exit 1
fi
if [ -n "${KEEP:-}" ]; then
  echo "left running: site http://127.0.0.1:$SITE_PORT admin http://127.0.0.1:$ADMIN_PORT (passwords: smoke)"
  echo "remove with: docker rm -f $SITE $ADMIN; docker network rm $NET; data in $DATA"
fi
