#!/usr/bin/env bash
# The real game on an emulator on a network with no way out: the emulator reaches the server and nothing else, and nothing in
# the phone is changed for that. The tour of tests/game/tour.sh; a song downloaded, played, paused and played to its result, with
# the score on the server; something bought in the shop; then a server with the game data and no songs, whose songs come later.
# The app is built with no network at all, with the runtime from a zip, as on a closed server.
#
# Needs: this machine's game files in data/ (read, never written), the Android SDK with its emulator, platform tools and the
# system image below, and KVM. The server is a throwaway one, with a database of its own.
#
# Usage: tests/closed/game.sh <report folder>     (ANDROID_HOME, default ~/android-sdk; KEEP=1 leaves it all running;
#        CLIENT=<apk> builds from that client instead of data/apk/base's, one changed for another server say)
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
REPORT=${1:?usage: tests/closed/game.sh <report folder>}
SDK=${ANDROID_HOME:-$HOME/android-sdk}
SYSTEM_IMAGE=system-images/android-30/google_apis/x86_64
NET=odq-closed-game
SERVER=192.168.99.10
PORT=8080
EMU=odq-closed-emu
SITE=odq-closed-site
SERVER_IMAGE=opendmtq-server:closed-game
TOOLS_IMAGE=opendmtq-tools:closed-game
WORK=$(mktemp -d)
failures=0
mkdir -p "$REPORT"
REPORT=$(cd "$REPORT" && pwd)

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
expect() {
  local name=$1
  shift
  if "$@"; then pass "$name"; else fail "$name"; fi
}

cleanup() {
  docker rm -fv "$EMU" "$SITE" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  # What the containers wrote belongs to their users: removed from inside an image.
  docker run --rm -u 0 -v "$WORK:/w" --entrypoint sh "$TOOLS_IMAGE" -c 'rm -rf /w/* /w/.[!.]*' >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
if [ -z "${KEEP:-}" ]; then
  trap cleanup EXIT
fi

[ -d "$SDK/$SYSTEM_IMAGE" ] || { echo "FAIL no $SYSTEM_IMAGE in $SDK"; exit 1; }
[ -f "$ROOT/data/apk/arm32/bundle.json" ] || { echo "FAIL no runtime bundle in data/apk/arm32"; exit 1; }
if [ -n "${CLIENT:-}" ]; then
  [ -f "$CLIENT" ] || { echo "FAIL no such client: $CLIENT"; exit 1; }
else
  ls "$ROOT"/data/apk/base/*.apk >/dev/null 2>&1 || { echo "FAIL no client in data/apk/base"; exit 1; }
fi

docker rm -fv "$EMU" "$SITE" >/dev/null 2>&1
docker network rm "$NET" >/dev/null 2>&1
docker network create --internal --subnet 192.168.99.0/24 "$NET" >/dev/null

# The app, built with no network at all, the runtime from the zip a release hands out, in a copy of what it needs.
docker build -q -t "$TOOLS_IMAGE" "$ROOT/tools" >/dev/null
docker build -q -t "$SERVER_IMAGE" "$ROOT/server" >/dev/null
mkdir -p "$WORK/state" "$WORK/apk/out" "$WORK/apk/base" "$WORK/avd/odq.avd"
if [ -n "${CLIENT:-}" ]; then
  cp "$CLIENT" "$WORK/apk/base/"
else
  cp "$ROOT"/data/apk/base/*.apk "$WORK/apk/base/"
fi
python3 "$ROOT/tools/opendmtq_tools/runtime.py" --pack "$ROOT/data/apk/arm32" "$WORK/apk/opendmtq-arm32-runtime.zip" >/dev/null
chmod -R a+rwX "$WORK"
if docker run --rm --network none -u 33:33 -e PUBLIC_HOST=$SERVER:$PORT -e HOME=/tmp -v "$WORK/apk:/apk" "$TOOLS_IMAGE" \
    opendmtq_tools.builder > "$REPORT/builder.txt" 2>&1; then
  pass "the app is built with no network at all"
else
  tail -n 20 "$REPORT/builder.txt"
  fail "the app's build"
  exit 1
fi
APP=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['file'])" "$WORK/apk/out/latest.json")
PACKAGE=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['package'])" "$WORK/apk/out/latest.json")
expect "it has the runtime" sh -c "python3 -m zipfile -l '$WORK/apk/out/$APP' | grep -q 'lib/arm64-v8a/libarm32.so'"

# The server, read-only on the game's files in <content> and the song list in <custom>, with its database in <state>.
start_server() {
  docker rm -fv "$SITE" >/dev/null 2>&1
  docker run -d --name "$SITE" --network "$NET" --ip "$SERVER" -u 33:33 --read-only --tmpfs /var/opendmtq:mode=1777 --tmpfs /tmp:mode=1777 \
    -e PUBLIC_HOST=$SERVER:$PORT -e ADMIN_ON_PUBLIC_PORT=no -e TZ=Asia/Seoul -v "$1:/srv/content:ro" -v "$3:/data" \
    -v "$WORK/apk/out:/srv/apk:ro" -v "$2:/srv/custom:ro" "$SERVER_IMAGE" >/dev/null
  for _ in $(seq 1 60); do
    [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' "http://$SERVER:$PORT/opendmtq/health.php")" = 200 ] && return 0
    sleep 2
  done
  return 1
}
expect "the server answers" start_server "$ROOT/data/content" "$ROOT/data/custom" "$WORK/state"

# The emulator: Android 11 with its ARM translation, on the same network and nothing else.
docker build -q -t opendmtq-emu:closed-game - >/dev/null <<'DOCKERFILE'
FROM ubuntu:22.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      libpulse0 libnss3 libxcomposite1 libxcursor1 libxi6 libxtst6 libasound2 libgl1 libx11-6 libx11-xcb1 \
      libxkbfile1 libxdamage1 libxrandr2 libfontconfig1 libdbus-1-3 libbsd0 libxkbcommon0 libc++1 libtcmalloc-minimal4 \
      libdrm2 libgbm1 libxshmfence1 libegl1 ca-certificates && rm -rf /var/lib/apt/lists
ENV ANDROID_SDK_ROOT=/sdk ANDROID_AVD_HOME=/avd
ENTRYPOINT ["/sdk/emulator/emulator"]
DOCKERFILE
cat > "$WORK/avd/odq.ini" <<'INI'
avd.ini.encoding=UTF-8
path=/avd/odq.avd
path.rel=avd/odq.avd
target=android-30
INI
# 1280x720 lying down: the coordinates of the tour and of the song below.
cat > "$WORK/avd/odq.avd/config.ini" <<INI
AvdId=odq
abi.type=x86_64
avd.ini.displayname=odq
avd.ini.encoding=UTF-8
disk.dataPartition.size=8G
hw.accelerometer=yes
hw.audioInput=no
hw.battery=yes
hw.cpu.arch=x86_64
hw.cpu.ncore=4
hw.gpu.enabled=yes
hw.gpu.mode=swiftshader_indirect
hw.initialOrientation=landscape
hw.keyboard=yes
hw.lcd.density=240
hw.lcd.height=720
hw.lcd.width=1280
hw.ramSize=4096
image.sysdir.1=$SYSTEM_IMAGE/
tag.display=Google APIs
tag.id=google_apis
INI
docker run -d --name "$EMU" --device /dev/kvm --cpus 8 --memory 8g --network "$NET" --ip 192.168.99.20 -v "$SDK:/sdk:ro" -v "$WORK/avd:/avd" \
  -v "$WORK/apk/out:$WORK/apk/out:ro" opendmtq-emu:closed-game -avd odq -no-window -no-audio -no-boot-anim -no-snapshot \
  -gpu swiftshader_indirect -no-metrics -accel on >/dev/null
# adb inside the emulator's container: the tour takes it as one command, and an APK path it knows.
cat > "$WORK/adb" <<ADB
#!/bin/sh
exec docker exec -i $EMU /sdk/platform-tools/adb "\$@"
ADB
chmod +x "$WORK/adb"
adb() { timeout 40 "$WORK/adb" -s emulator-5554 "$@"; }
for _ in $(seq 1 120); do
  [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ] && break
  sleep 3
done
expect "the emulator has started" test "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1
adb shell settings put global stay_on_while_plugged_in 7
adb shell input keyevent 82

# Closed means closed, or this test would prove nothing. A well-known address, then the server.
expect "the phone has no way out" sh -c "! '$WORK/adb' -s emulator-5554 shell 'nc -w 5 8.8.8.8 53 </dev/null >/dev/null 2>&1'"
expect "it reaches the server" "$WORK/adb" -s emulator-5554 shell "nc -w 5 $SERVER $PORT </dev/null >/dev/null 2>&1"
expect "and it resolves no name" sh -c "! '$WORK/adb' -s emulator-5554 shell 'ping -c 1 -W 3 www.google.com >/dev/null 2>&1'"

# The tour: install, first start and its data, the lobby, the menu, the options, the album, the shop, a second start.
if ADB="$WORK/adb" DEVICE=emulator-5554 APP_FOLDER="$WORK/apk/out" "$ROOT/tests/game/tour.sh" "$REPORT" > "$REPORT/tour.txt" 2>&1; then
  pass "the tour of the game, without a crash"
else
  tail -n 10 "$REPORT/tour.txt"
  fail "the tour of the game"
  exit 1
fi

# ------------------------------------------------------------------------------ a song

in_game() { local windows; windows=$(adb shell dumpsys window); case "$(printf '%s\n' "$windows" | grep mCurrentFocus)" in *"$PACKAGE"*) return 0;; esac; return 1; }
# A press only while the game is on the screen: elsewhere it would go to whatever else is.
tap() {
  in_game || { fail "the game left the screen before the press at $1 $2 ($3)"; return 1; }
  adb shell input tap "$1" "$2"
  sleep "${4:-4}"
  adb exec-out screencap -p > "$REPORT/song-$3.png"
}
played() { docker exec "$SITE" php -r '$d = new SQLite3("/data/dmtq.db3", SQLITE3_OPEN_READONLY); echo (int)$d->querySingle("SELECT COUNT(*) FROM PlayLog");' 2>/dev/null; }
requests() { docker logs "$SITE" 2>&1 | grep -c "$1"; }

adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
sleep 25
# The second song of the list is not on the phone yet: a press on it asks to download it.
tap 720 215 1-chosen 6
tap 1107 673 2-download 5
before=$(requests "/DMQ/Songs/")
tap 512 451 3-downloading 30
expect "the song's music and video come from the server" test "$(requests "/DMQ/Songs/")" -gt "$before"
tap 640 451 4-downloaded 3
tap 720 215 5-charts 6
tap 178 520 6-chart 8
tap 1130 515 7-start 6
# Only the first time, the choice of the screen's layout.
tap 928 520 8-layout 25
expect "the chart comes from the server" test "$(requests "/DMQ/Patterns/")" -gt 0
expect "the song is on the screen, with the game still in front" in_game
# Paused and on again: the pause button, then RESUME on the pause screen.
tap 40 40 9-paused 4
tap 310 470 10-resumed 6
for _ in $(seq 1 30); do
  [ "$(played)" -gt 0 ] && break
  sleep 10
done
expect "the song's score reaches the server" test "$(played)" -gt 0
sleep 8
adb exec-out screencap -p > "$REPORT/song-11-result.png"
docker exec "$SITE" php -r '$d = new SQLite3("/data/dmtq.db3", SQLITE3_OPEN_READONLY); $r = $d->query("SELECT pattern_id, score, grade FROM PlayLog"); while ($x = $r->fetchArray(SQLITE3_ASSOC)) echo json_encode($x), "\n";'

# ------------------------------------------------------------------------------ the shop

# From the start again, as the result screen has buttons of its own: the menu, the shop, the first thing on it, and BUY.
start_game() {
  adb shell am force-stop "$PACKAGE"
  adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
  sleep "${1:-28}"
}
start_game
tap 34 670 12-menu 3
tap 398 304 13-shop 5
tap 292 620 14-purchase 4
before=$(requests "POST /DMQ/rpc")
tap 514 451 15-bought 5
expect "the shop's purchase reaches the server" test "$(requests "POST /DMQ/rpc")" -gt "$before"
in_game || fail "the game left the screen in the shop"

# ------------------------------------------------------------------------------ no songs yet, then songs

# What an import without the songs leaves, by the import's own rule, and the song list made from it, as a server's start does.
mkdir -p "$WORK/nosongs" "$WORK/nosongs-custom" "$WORK/nosongs-state"
chmod -R a+rwX "$WORK/nosongs" "$WORK/nosongs-custom" "$WORK/nosongs-state"
docker run --rm --network none -u 33:33 -v "$ROOT/data/content:/c:ro" -v "$WORK/nosongs:/o" --entrypoint python3 "$TOOLS_IMAGE" -I -c '
import os, shutil
from opendmtq_tools.importer import part_of
for folder, _, names in os.walk("/c"):
    for name in names:
        rel = os.path.relpath(os.path.join(folder, name), "/c")
        if part_of(rel) == "game":
            os.makedirs(os.path.dirname(os.path.join("/o", rel)), exist_ok=True)
            shutil.copyfile(os.path.join(folder, name), os.path.join("/o", rel))
'
docker run --rm --network none -u 33:33 -e HOME=/tmp -v "$WORK/nosongs:/srv/content:ro" -v "$WORK/nosongs-custom:/custom" -v "$WORK/nosongs-state:/data" \
  "$TOOLS_IMAGE" opendmtq_tools.songs >/dev/null
failed() { docker logs "$SITE" 2>&1 | grep -cE '" (4|5)[0-9][0-9] '; }
expect "a server with the game data and no songs answers" start_server "$WORK/nosongs" "$WORK/nosongs-custom" "$WORK/nosongs-state"
# A phone that has never seen this server's songs: the app's data goes, and with it Android's answer on storage.
adb shell am force-stop "$PACKAGE"
adb shell pm clear "$PACKAGE" >/dev/null
for permission in READ_EXTERNAL_STORAGE WRITE_EXTERNAL_STORAGE; do
  adb shell pm grant "$PACKAGE" "android.permission.$permission"
done
start_game 60
adb exec-out screencap -p > "$REPORT/nosongs-1-first-start.png"
expect "the game starts with no songs, the game still in front" in_game
expect "and asks the server for nothing it has not got ($(failed) failed)" test "$(failed)" = 0
# Past the first start's name, then the songs arrive: the real files, the same database, the app as it is.
tap 640 452 nosongs-2-named 5
expect "with the songs imported the server answers" start_server "$ROOT/data/content" "$ROOT/data/custom" "$WORK/nosongs-state"
start_game 55
adb exec-out screencap -p > "$REPORT/nosongs-3-with-songs.png"
expect "the installed app fetches what changed at its next start" test "$(requests "GET /patch/")" -gt 0
expect "and gets all of it ($(failed) failed)" test "$(failed)" = 0
expect "the game is still in front" in_game

if adb logcat -d -v brief -t 20000 > "$REPORT/logcat.txt"; then
  crashes=$(grep -cE "FATAL|Fatal signal|signal 11|ANR in" "$REPORT/logcat.txt")
  expect "no crash in the phone's log ($crashes)" test "$crashes" = 0
  echo "What the phone looked for outside, in vain:"
  grep -oE 'Unable to resolve host "[^"]+"' "$REPORT/logcat.txt" | sort | uniq -c | sort -rn | head -n 12
fi
echo "$([ "$failures" = 0 ] && echo PASS || echo FAIL) the game on a closed network: $failures failure(s)"
if [ -n "${KEEP:-}" ]; then
  echo "left running: $EMU, $SITE, network $NET; adb: $WORK/adb; work folder: $WORK"
fi
exit $((failures > 0))
