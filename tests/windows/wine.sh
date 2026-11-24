#!/usr/bin/env bash
# The Windows bundle under Wine, on Linux: a smoke test for when no Windows is at hand (CI's windows job runs the bundle
# on Windows itself, tests/windows/run.ps1). Builds the bundle (host/windows/build.sh), lays out the pages' stand-in game
# files like the game's client data and song data, starts OpenDMTQ.exe as a double-click does, and checks the game
# server's contract (tests/game/protocol.py), the admin pages, and the setup pages: the one-time sign-in, the import
# from the folder, and another address with the restart it makes. Needs Docker; nothing of the game's own, but with APK=
# the game's client goes through the setup too and the phone app is built with the bundle's Java, Apktool and signer.
#
# Wine is not Windows. Four things differ, and the test changes only its own copy of the bundle for them:
# - Wine (8.0 at least) lacks propsys' VariantToString, which Python's WMI module calls for platform details: it goes,
#   and so does its line in the bundle's list of its files (the repair would rightly call it missing).
# - Wine prefers its own C runtime, whose version PHP refuses: Wine is told to take the bundle's copies.
# - Under Wine, Python cannot start with its output sent to a file: the output goes through a pipe.
# - PHP's opcache cannot share its memory between Apache's processes there; it is off by default anyway.
#
# Usage: tests/windows/wine.sh      (NO_BUILD=1 tests the bundle already in OUT, default _work/windows; PORT, default 18731;
#                                    CLOSED=1 runs all of it on a network with no way out, as docs/closed-network.md says it works;
#                                    APK=<the game's client> also imports it in the setup and builds the phone app with it)
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${OUT:-$ROOT/_work/windows}
PORT=${PORT:-18731}
# NAME_PREFIX names this run's container and network, TAG its Wine image, apart from another run's on the same machine.
NAME_PREFIX=${NAME_PREFIX:-odq}
WINE_IMAGE=opendmtq-wine:${TAG:-local}

# ------------------------------------------------------------------------------ outside: build, then the Wine container

if [ -z "${IN_WINE:-}" ]; then
  if [ -z "${NO_BUILD:-}" ]; then
    "$ROOT/host/windows/build.sh" "$OUT"
  fi
  [ -f "$OUT/OpenDMTQ/OpenDMTQ.exe" ] || { echo "FAIL no bundle in $OUT (run host/windows/build.sh)"; exit 1; }
  # WineHQ's stable Wine, at a fixed version. Debian's own (8.0) lacks a network call Java makes when it seeds its random
  # numbers (java.net.NetworkInterface.getAll), so keytool and the signer died there and the app's build could not be tried.
  docker build -q -t "$WINE_IMAGE" - >/dev/null <<'DOCKERFILE'
FROM debian:12
RUN dpkg --add-architecture i386 && apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      --no-install-recommends ca-certificates curl gnupg python3 php-cli >/dev/null \
    && mkdir -pm755 /etc/apt/keyrings \
    && curl -fsSL https://dl.winehq.org/wine-builds/winehq.key | gpg --dearmor -o /etc/apt/keyrings/winehq-archive.key \
    && curl -fsSL -o /etc/apt/sources.list.d/winehq-bookworm.sources \
      https://dl.winehq.org/wine-builds/debian/dists/bookworm/winehq-bookworm.sources \
    && apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --install-recommends \
      winehq-stable=11.0.0.0~bookworm-1 wine-stable=11.0.0.0~bookworm-1 wine-stable-amd64=11.0.0.0~bookworm-1 \
      wine-stable-i386=11.0.0.0~bookworm-1 >/dev/null \
    && rm -rf /var/lib/apt/lists/*
ENV PATH=/opt/wine-stable/bin:$PATH
DOCKERFILE
  network=()
  status=0
  if [ -n "${CLOSED:-}" ]; then
    # An internal network: the container gets a private address, and nothing it sends gets past this machine.
    docker network inspect "$NAME_PREFIX-closed" >/dev/null 2>&1 || docker network create --internal --subnet "${CLOSED_SUBNET:-192.168.98.0/24}" "$NAME_PREFIX-closed" >/dev/null
    network=(--network "$NAME_PREFIX-closed")
  fi
  client=()
  if [ -n "${APK:-}" ]; then
    [ -f "$APK" ] || { echo "FAIL no such client: $APK"; exit 1; }
    client=(-v "$(cd "$(dirname "$APK")" && pwd)/$(basename "$APK"):/client.apk:ro" -e CLIENT=/client.apk)
  fi
  docker run --rm --name "$NAME_PREFIX-wine" "${network[@]}" "${client[@]}" -e IN_WINE=1 -e PORT="$PORT" -e CLOSED="${CLOSED:-}" -e WINEDEBUG=-all \
    -e WINEPREFIX=/tmp/wine -v "$OUT/OpenDMTQ:/bundle:ro" -v "$ROOT:/repo:ro" "$WINE_IMAGE" bash /repo/tests/windows/wine.sh \
    || status=$?
  if [ -n "${CLOSED:-}" ]; then
    docker network rm "$NAME_PREFIX-closed" >/dev/null 2>&1 || true
  fi
  exit "$status"
fi

# ------------------------------------------------------------------------------ inside: the bundle under Wine

failures=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
# expect <name> <command...>: PASS when the command succeeds.
expect() {
  local name=$1
  shift
  if "$@"; then pass "$name"; else fail "$name"; fi
}
code() { curl -s -o /dev/null -w '%{http_code}' -m 10 "$1"; }
is() { [ "$(code "$2")" = "$1" ]; }

# Closed means closed, or this test would prove nothing.
if [ -n "${CLOSED:-}" ]; then
  expect "this container has no way out" sh -c '! curl -s -m 5 -o /dev/null https://github.com'
fi
# The bundle's copy, with the Wine changes above, in a folder with a space in its name, as under a user's own name: every
# path the bundle writes, and every one its Apache reads, must survive it.
cp -r /bundle "/tmp/Open DMTQ"
cd "/tmp/Open DMTQ"
rm -f runtime/python/_wmi.pyd
sed -i '/runtime\/python\/_wmi\.pyd$/d' app/MANIFEST.sha256 2>/dev/null || true
export WINEDLLOVERRIDES="vcruntime140=n;vcruntime140_1=n"
# Wine sets itself up on its first program, with a line or two about it: not part of what is checked.
wine cmd /c ver >/dev/null 2>&1 || true

expect "OpenDMTQ.exe starts the bundle's Python and the host program" sh -c 'wine OpenDMTQ.exe --help 2>&1 | grep -q "Run an OpenDMTQ server without containers"'

# The pages' stand-in game files, laid out like the game's client data and song data.
# Under the name of the game host's folder, which the import knows them by (tests/game_host.py: the repository's text
# names none of the game's own).
GAME_HOST=$(python3 /repo/tests/game_host.py)
mkdir -p /tmp/content "/tmp/game/$GAME_HOST" /tmp/game/_info
php /repo/tests/ui/make_content.php /tmp/content >/dev/null
cp -r /tmp/content/web/. "/tmp/game/$GAME_HOST/"
cp /tmp/content/songs.json /tmp/game/_info/songList.json
# A first start as a person makes it: no .env yet. OpenDMTQ.exe writes one (this PC's address, a free port, a password)
# and runs the server, the setup pages opened. Windows' Python lacks some of Linux's calls for that file (no fchmod, no
# user ids), and the address is found on Windows' own terms, also on a network with no way out.
(OPENDMTQ_START_WAIT=5 timeout 900 wine OpenDMTQ.exe 2>&1 | cat > /tmp/first.log &)
for _ in $(seq 1 150); do
  grep -q '^ADMIN_PASSWORD=' .env 2>/dev/null && break
  grep -q 'Traceback\|error:' /tmp/first.log 2>/dev/null && break
  sleep 2
done
expect "a first start with no .env writes one: the address, the port, a password" \
  sh -c "grep -q '^PUBLIC_HOST=' .env && grep -q '^LISTEN_PORT=' .env && grep -q '^ADMIN_PASSWORD=' .env"
# (Nothing written: the checks below say so too, and the test goes on to the rest.)
first=$(sed -n 's/^LISTEN_PORT=\([0-9]*\).*/\1/p' .env 2>/dev/null | tr -d '\r' || true)
for _ in $(seq 1 150); do
  case "$(code "http://127.0.0.1:${first:-1}/opendmtq/health.php")" in 200 | 503) break ;; esac
  grep -q 'Traceback\|error:' /tmp/first.log 2>/dev/null && break
  sleep 2
done
expect "and runs the server on the port it chose (${first:-none})" sh -c "case \$(curl -s -o /dev/null -w '%{http_code}' -m 10 \
  http://127.0.0.1:${first:-1}/opendmtq/health.php) in 200 | 503) exit 0 ;; esac; exit 1"
expect "with nothing gone wrong in its window" sh -c "! grep -q 'Traceback\|error:' /tmp/first.log"
grep -q 'Traceback\|error:' /tmp/first.log && tail -n 30 /tmp/first.log
# A new install's one port is 8791: the players' site, the admin pages and the API on it (DEP-46), the admin service's own
# port elsewhere on loopback, never shown.
expect "a new install takes port 8791 (${first:-none})" test "${first:-}" = 8791
inner=$(tr -d '\r\n' < .host/run/admin.port 2>/dev/null || true)
expect "the admin service's own port is another, chosen at the start and not in .env (${inner:-none})" \
  sh -c "test -n '$inner' && test '$inner' != 8791 && ! grep -q '^ADMIN_PORT=' .env"
expect "the window names the admin pages on that port" grep -q "/opendmtq/admin/" /tmp/first.log
expect "and no other port" sh -c "! grep -q ':$inner' /tmp/first.log"
expect "the admin pages answer on it" is 200 "http://127.0.0.1:${first:-1}/opendmtq/admin/login"
# owner_signs_in <port> <password> <when>: the ID and password the window and .env name open the admin pages and the
# players' site alike (ADM-105), each in a browser of its own. The owner's own case: the site refused them.
owner_signs_in() {
  local jar code
  jar=$(mktemp)
  curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null "http://127.0.0.1:$1/opendmtq/admin/login"
  code=$(curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null -w '%{http_code}' --data-urlencode "name=admin" \
    --data-urlencode "password=$2" "http://127.0.0.1:$1/opendmtq/admin/login")
  expect "$3, the owner signs in to the admin pages with .env's password ($code)" test "$code" = 302
  rm -f "$jar"
  jar=$(mktemp)
  curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null "http://127.0.0.1:$1/opendmtq/login.php"
  code=$(curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null -w '%{http_code}' --data-urlencode "user=admin" \
    --data-urlencode "password=$2" -d "next=/opendmtq/" "http://127.0.0.1:$1/opendmtq/login.php")
  expect "$3, the owner signs in to the players' site with the same ID and password ($code)" test "$code" = 303
  rm -f "$jar"
}
made=$(sed -n 's/^ADMIN_PASSWORD=//p' .env 2>/dev/null | tr -d '\r' || true)
owner_signs_in "${first:-1}" "$made" "on a first start"
# Its window closed: everything it started stops with it. The rest runs with this test's own ports and settings.
wineserver -k 2>/dev/null || true
sleep 3
rm -rf .env .host/run

# The settings setup would write, with this test's ports.
ADMIN=$((PORT + 1))
printf 'PUBLIC_HOST=127.0.0.1:%s\r\nLISTEN_PORT=%s\r\nADMIN_PORT=%s\r\nADMIN_PASSWORD=winetest\r\n' "$PORT" "$PORT" "$ADMIN" > .env
# A stop the admin pages asked of an earlier run whose window closed before it read it: not this run's to do.
mkdir -p .host/run && echo 0 > .host/run/stop.request

# OpenDMTQ.exe as a double-click starts it: setup, then the server in its window, the setup pages opened for what is
# left. Its output goes through a pipe (see above). The wait for the first answer is cut to a few seconds, far less than
# Apache takes here: this is the slow first start of a PC whose antivirus looks at every new program. Until it answers:
# with nothing imported yet, its health page says so (503, no client data).
(OPENDMTQ_START_WAIT=5 timeout 1500 wine OpenDMTQ.exe 2>&1 | cat > /tmp/run.log &)
for _ in $(seq 1 150); do
  case "$(code "http://127.0.0.1:$PORT/opendmtq/health.php")" in 200 | 503) break ;; esac
  sleep 2
done
if [ "$(code "http://127.0.0.1:$PORT/opendmtq/health.php")" = 503 ]; then
  pass "a double-click on OpenDMTQ.exe runs the server on the bundle's Apache and PHP, waiting for the game's files"
  # Two of the watch's rounds later: the earlier run's stop did not end this one.
  sleep 5
  expect "a stop asked of an earlier run is not this run's" is 503 "http://127.0.0.1:$PORT/opendmtq/health.php"
else
  tail -n 30 /tmp/run.log data/state/logs/server.log data/state/logs/programs.log 2>/dev/null || true
  fail "a double-click on OpenDMTQ.exe runs the server on the bundle's Apache and PHP, waiting for the game's files"
  exit 1
fi
expect "the admin pages answer on the server's one port" is 200 "http://127.0.0.1:$PORT/opendmtq/admin/login"
# The settings above are a server set up before 0.11.0 (ADMIN_PORT beside the rest, Windows line ends): that line leaves
# .env at the start, and nothing answers on the admin pages' old port (DEP-47).
expect "an ADMIN_PORT from before 0.11.0 leaves .env at the start" sh -c "! grep -q '^ADMIN_PORT=' .env && grep -q '^ADMIN_PASSWORD=winetest' .env"
expect "and nothing answers on the admin pages' old port" is 000 "http://127.0.0.1:$ADMIN/opendmtq/admin/login"
expect "signed out, the site asks to sign in" is 302 "http://127.0.0.1:$PORT/opendmtq/index.php"

# The setup pages, as the browser the window opened sees them: signed in by the one-time key it carries (the file the
# window wrote, though the server answered only after the wait ran out), the PC's drives to pick from, and the import of
# the folder.
A="http://127.0.0.1:$PORT/opendmtq/admin"
jar=/tmp/admin.cookies
web() { curl -s -m 60 -c "$jar" -b "$jar" "$@"; }
token() { grep -o 'name="csrf" value="[^"]*"' | head -n 1 | cut -d'"' -f4; }
for _ in $(seq 1 30); do
  [ -s .host/run/signin.token ] && break
  sleep 1
done
expect "a first start slower than the wait: the window says it is still waiting" grep -q "still waiting" /tmp/run.log
went=$(web -o /dev/null -w '%{http_code} %{redirect_url}' "$A/setup/start?key=$(cat .host/run/signin.token 2>/dev/null)")
expect "the window's one-time link signs the browser in ($went)" test "$went" = "302 $A/setup"
files=$(web "$A/setup")
expect "the setup offers the PC's drives to pick a folder from" grep -q '>Z:\\</a>' <<<"$files"
job=$(web -o /dev/null -w '%{redirect_url}' --data-urlencode "csrf=$(token <<<"$files")" --data-urlencode 'path=Z:\tmp\game' \
  -d "songs=yes" "$A/setup/import" | sed -n 's/.*[?&]job=\([0-9a-f]*\).*/\1/p')
expect "the setup starts the import" test -n "$job"
state=running
for _ in $(seq 1 300); do
  state=$(web "$A/jobs/$job" | python3 -c 'import json, sys; print(json.load(sys.stdin)["state"])' 2>/dev/null || echo gone)
  [ "$state" = running ] || break
  sleep 1
done
[ "$state" = "done" ] || web "$A/jobs/$job" | python3 -c 'import json, sys; print("\n".join(json.load(sys.stdin)["log"][-30:]))' || true
expect "the import from Z:\\tmp\\game ends well ($state)" test "$state" = "done"
expect "with the game's files in, the server is healthy" is 200 "http://127.0.0.1:$PORT/opendmtq/health.php"
expect "a song's jacket is served from the imported content" is 200 "http://127.0.0.1:$PORT/viewImg/eye/fixture1.png"
# An archive of them, as many people have them: Windows' 7-Zip lists its paths with backslashes.
wine runtime/7zip/7z.exe a -tzip -bso0 -bsp0 'Z:\tmp\game-files.zip' 'Z:\tmp\game' >/dev/null 2>&1
job=$(web -o /dev/null -w '%{redirect_url}' --data-urlencode "csrf=$(web "$A/setup" | token)" --data-urlencode 'path=Z:\tmp\game-files.zip' \
  -d "songs=yes" "$A/setup/import" | sed -n 's/.*[?&]job=\([0-9a-f]*\).*/\1/p')
state=running
for _ in $(seq 1 300); do
  state=$(web "$A/jobs/$job" | python3 -c 'import json, sys; print(json.load(sys.stdin)["state"])' 2>/dev/null || echo gone)
  [ "$state" = running ] || break
  sleep 1
done
[ "$state" = "done" ] || web "$A/jobs/$job" | python3 -c 'import json, sys; print("\n".join(json.load(sys.stdin)["log"][-30:]))' || true
expect "the import from an archive ends well ($state)" test "$state" = "done"
expect "and it found the game's files in the archive" sh -c "web() { curl -s -m 60 -b $jar \"\$@\"; }; web '$A/jobs/$job' | grep -q 'game-files.zip'"
expect "with the archive's files in, the server is healthy" is 200 "http://127.0.0.1:$PORT/opendmtq/health.php"
# What the setup says of each file, as its lists ask (Windows' 7-Zip lists the archive): the folder and the archive of the
# client data and the song data, and the iPhone app, which is of no use.
: > /tmp/game.ipa
what() { web -G --data-urlencode "path=$1" "$A/setup/what"; }
# said <path> <true|false> <words>: the setup's answer for that file, shown, has that verdict and those words.
said() {
  what "$1" > /tmp/said.json
  echo "    $(cat /tmp/said.json)"
  grep -q "\"ok\": *$2" /tmp/said.json && grep -q "$3" /tmp/said.json
}
expect "the setup says the folder holds the client data" said 'Z:\tmp\game' true 'Client data'
expect "and so does the archive, read by Windows' 7-Zip" said 'Z:\tmp\game-files.zip' true 'Client data'
expect "and the iPhone app is of no use" said 'Z:\tmp\game.ipa' false 'iPhone app'
# The game server's contract, as on the image and on a host install.
if python3 /repo/tests/game/protocol.py "http://127.0.0.1:$PORT"; then
  pass "the game server's contract on the Windows bundle"
else
  fail "the game server's contract on the Windows bundle"
fi

# Another address, chosen in the setup: the window starts every program again for it (on Windows, Apache's worker is
# ended with its parent, or the new Apache would find the port taken), and the page comes back signed in.
lan=$(hostname -I | tr ' ' '\n' | grep -E '^(10|172\.(1[6-9]|2[0-9]|3[01])|192\.168)\.' | head -n 1 || true)
if [ -n "$lan" ]; then
  before=$(web "$A/setup/ping")
  page=$(web --data-urlencode "csrf=$(web "$A/setup?step=address" | token)" -d "host=$lan" "$A/setup/address")
  expect "the setup saves the new address to .env" grep -q "^PUBLIC_HOST=$lan:$PORT" .env
  # The way back, as the page's script reads it: its data-back attribute, its HTML escapes undone as a browser does.
  back=$(grep -o 'data-back="[^"]*"' <<<"$page" | sed -e 's/^data-back="//' -e 's/"$//' -e 's/&amp;/\&/g')
  expect "the page that waits for the restart carries the way back, with its one-time key" \
    test "${back#/opendmtq/admin/setup/start?key=}" != "$back"
  restarted=no
  # Through the server's one port: the answer comes once Apache is back too, which takes longer under Wine than the
  # admin service alone (the page itself waits for as long as it takes).
  for _ in $(seq 1 300); do
    now=$(curl -s -m 3 "$A/setup/ping" || true)
    if [ -n "$now" ] && [ "$now" != "$before" ]; then restarted=yes; break; fi
    sleep 1
  done
  expect "the window starts the server again by itself" test "$restarted" = yes
  for _ in $(seq 1 60); do
    [ "$(code "http://$lan:$PORT/opendmtq/health.php")" = 200 ] && break
    sleep 2
  done
  expect "the server answers at the new address" is 200 "http://$lan:$PORT/opendmtq/health.php"
  went=$(web -o /dev/null -w '%{http_code} %{redirect_url}' "http://127.0.0.1:$PORT$back")
  expect "the page comes back signed in, at the players' step ($went)" test "$went" = "302 $A/setup?step=players"
else
  echo "SKIP no private address in this container: the address change is not tried"
fi
# The runtime for newer phones, from the bundle alone (it has one when the PC that built it had one). The app's build after it
# needs a client, which this test has not got.
if [ -f app/tools/opendmtq_tools/opendmtq-arm32-runtime.zip ]; then
  # Through a pipe, as the start above: Python under Wine cannot start with its output going straight to a file.
  timeout 300 wine OpenDMTQ.exe runtime 2>&1 | cat > /tmp/runtime.log || true
  tail -n 6 /tmp/runtime.log
  expect "the runtime comes out of the bundle: Android's libraries" test -s data/apk/arm32/sysroot/lib/libc.so
  expect "the translator" test -s data/apk/arm32/arm64-v8a/libarm32.so
  expect "and every license" test -s data/apk/arm32/notices/android-NOTICE.html.gz
  expect "nothing was fetched for it" sh -c '! grep -q "Fetching" /tmp/runtime.log'
  sha256sum data/apk/arm32/sysroot/lib/libc.so data/apk/arm32/arm64-v8a/libarm32.so
else
  echo "SKIP this bundle has no runtime: the PC that built it had none"
fi
# The phone app, built from a real client (APK=...): imported in the setup, said to be the original or a copy changed for
# another server, then the setup's own build with the bundle's Java, Apktool and signer, and the runtime above.
if [ -n "${CLIENT:-}" ]; then
  mkdir -p /tmp/client
  cp "$CLIENT" /tmp/client/game.apk
  expect "the setup says what the client is" said 'Z:\tmp\client\game.apk' true 'original: ready\|changed for another server'
  job=$(web -o /dev/null -w '%{redirect_url}' --data-urlencode "csrf=$(web "$A/setup" | token)" --data-urlencode 'path=Z:\tmp\client' \
    "$A/setup/import" | sed -n 's/.*[?&]job=\([0-9a-f]*\).*/\1/p')
  state=running
  for _ in $(seq 1 300); do
    state=$(web "$A/jobs/$job" | python3 -c 'import json, sys; print(json.load(sys.stdin)["state"])' 2>/dev/null || echo gone)
    [ "$state" = running ] || break
    sleep 1
  done
  expect "the client is imported ($state)" test -f data/apk/base/game.apk
  job=$(web -o /dev/null -w '%{redirect_url}' --data-urlencode "csrf=$(web "$A/setup?step=app" | token)" "$A/setup/build" \
    | sed -n 's/.*[?&]job=\([0-9a-f]*\).*/\1/p')
  expect "the setup starts the app's build" test -n "$job"
  state=running
  for _ in $(seq 1 1500); do
    state=$(web "$A/jobs/$job" | python3 -c 'import json, sys; print(json.load(sys.stdin)["state"])' 2>/dev/null || echo gone)
    [ "$state" = running ] || break
    sleep 1
  done
  web "$A/jobs/$job" | python3 -c 'import json, sys; print("\n".join(json.load(sys.stdin)["log"][-40:]))' > /tmp/build.log 2>&1 || true
  grep -E "base |code |skipped|signing|adding|done|error" /tmp/build.log | head -20
  expect "the app's build ends well ($state)" test "$state" = "done"
  built=$(ls -t data/apk/out/opendmtq-phone-app-*.apk 2>/dev/null | head -n 1 || true)
  expect "the app is there (${built:-none})" test -n "$built"
  if [ -n "$built" ]; then
    list=$(python3 -m zipfile -l "$built" | awk '{print $1}')
    expect "it is signed" grep -q '^META-INF/.*\.RSA$' <<<"$list"
    expect "it carries the runtime for newer phones" grep -qx 'lib/arm64-v8a/libarm32.so' <<<"$list"
    expect "every code edit of the client went in" sh -c "! grep -q 'skipped' /tmp/build.log"
  fi
fi

# Apache's logs through logpipe.py on pythonw.exe (no console window of their own): written, the requests above in them
# (the health checks are left out of the access log on purpose).
expect "Apache writes its logs through logpipe.py on pythonw.exe" grep -q 'pythonw\.exe.* -I .*logpipe\.py' .host/run/httpd.conf
expect "Apache's error log is written" test -s data/state/logs/server.log
expect "and its access log, with the requests above" grep -q "GET /viewImg/eye/fixture1.png" data/state/logs/access.log
if grep -E "PHP (Warning|Notice|Deprecated|Fatal error|Parse error)" data/state/logs/server.log; then
  fail "PHP complained in the server's log (above)"
else
  pass "PHP said nothing in the server's log"
fi

# Stopped from the admin pages (Maintenance): the window's program stops every part, says so, and ends.
stopped=$(web -o /tmp/stopped.html -w '%{http_code}' --data-urlencode "csrf=$(web "$A/maintenance" | token)" "$A/server/stop")
expect "the admin pages' Stop the server answers ($stopped)" test "$stopped" = 200
expect "and says to start OpenDMTQ.exe to run it again" grep -q "start OpenDMTQ.exe" /tmp/stopped.html
for _ in $(seq 1 60); do
  [ "$(code "http://127.0.0.1:$PORT/opendmtq/health.php")" = 000 ] && break
  sleep 1
done
expect "and the server stops" is 000 "http://127.0.0.1:$PORT/opendmtq/health.php"
# Its last words come once every part has stopped: within seconds, not one wait for each program.
for _ in $(seq 1 30); do
  grep -q "Stopped from the admin pages" /tmp/run.log && break
  sleep 1
done
expect "its window says it was stopped from the admin pages" grep -q "Stopped from the admin pages" /tmp/run.log
# The bundle's programs still running, from /proc (the image has no ps): each pattern in brackets, so that the grep
# does not find itself.
left() {
  for f in /proc/[0-9]*/cmdline; do tr '\0' ' ' < "$f" 2>/dev/null; echo; done |
    grep -i -E '[o]pendmtq\.exe|[h]ttpd\.exe|[p]hp\.exe|[p]ython\.exe|[p]ythonw\.exe|[r]otatelogs\.exe' || true
}
for _ in $(seq 1 15); do
  [ -z "$(left)" ] && break
  sleep 1
done
left
expect "and nothing of it is left running" test -z "$(left)"

# Started again as the owner did (a double-click on OpenDMTQ.exe), with the .env the first run used, Windows line ends
# and all: the same ID and password open both doors (the owner's report: they did not).
(timeout 600 wine OpenDMTQ.exe 2>&1 | cat > /tmp/again.log &)
for _ in $(seq 1 150); do
  case "$(code "http://127.0.0.1:$PORT/opendmtq/health.php")" in 200 | 503) break ;; esac
  sleep 2
done
for _ in $(seq 1 30); do
  is 200 "http://127.0.0.1:$PORT/opendmtq/admin/login" && break
  sleep 1
done
owner_signs_in "$PORT" winetest "stopped from the admin pages and started again"

# The Server page: Restart (every part again, the window stays), then Uninstall: the window's program stops every part,
# and a script of its own outside the folder deletes it once the window has closed (ADM-114).
rm -f "$jar"
web -o /dev/null "$A/login"
web -o /dev/null -d "name=admin&password=winetest" "$A/login"
page=$(web "$A/server")
offers() { grep -q 'action="/opendmtq/admin/server/restart"' <<<"$page" && grep -q 'action="/opendmtq/admin/server/uninstall"' <<<"$page"; }
expect "the Server page offers Restart and Uninstall here" offers
before=$(web "$A/setup/ping")
web -o /dev/null --data-urlencode "csrf=$(token <<<"$page")" "$A/server/restart"
restarted=no
for _ in $(seq 1 120); do
  now=$(curl -s -m 3 "$A/setup/ping" || true)
  if [ -n "$now" ] && [ "$now" != "$before" ]; then restarted=yes; break; fi
  sleep 1
done
expect "Restart on the Server page starts every part again in the same window" test "$restarted" = yes
rm -f "$jar"
for _ in $(seq 1 30); do
  is 200 "$A/login" && break
  sleep 1
done
web -o /dev/null "$A/login"
web -o /dev/null -d "name=admin&password=winetest" "$A/login"
# job_state <redirect>: how a job the Server page started ended: followed while it runs, or what the page then says.
job_state() {
  local job state said
  job=$(sed -n 's/.*[?&]job=\([0-9a-f]*\).*/\1/p' <<<"$1")
  if [ -n "$job" ]; then
    state=running
    for _ in $(seq 1 600); do
      state=$(web "$A/jobs/$job" | python3 -c 'import json, sys; print(json.load(sys.stdin)["state"])' 2>/dev/null || echo gone)
      [ "$state" = running ] || break
      sleep 1
    done
    [ "$state" = "done" ] || web "$A/jobs/$job" | python3 -c 'import json, sys; print("\n".join(json.load(sys.stdin)["log"][-20:]))' || true
    echo "$state"
    return
  fi
  said=$(web "$A/server")
  if grep -q 'class="flash bad"' <<<"$said"; then
    grep -o '<p class="flash bad"[^>]*>[^<]*' <<<"$said" | sed 's/<[^>]*>//' >&2
    echo failed
  else
    echo "done"
  fi
}
# Check and repair, and the data, from the Server page, and the same from the command line (OpenDMTQ.exe repair and
# delete-data, through a pipe as above).
went=$(web -o /dev/null -w '%{redirect_url}' --data-urlencode "csrf=$(web "$A/server" | token)" "$A/server/repair")
state=$(job_state "$went")
expect "Check and repair on the Server page ends ($state)" test "$state" = "done"
echo old > data/backups/opendmtq-20200101-000000-manual.tar.gz
went=$(web -o /dev/null -w '%{redirect_url}' --data-urlencode "csrf=$(web "$A/server" | token)" -d part=backups -d part=logs \
  -d backup=yes -d confirm=delete "$A/server/data")
state=$(job_state "$went")
expect "deleting the backups and the logs on the Server page ends ($state)" test "$state" = "done"
expect "the old backup is gone, the one made first stays" sh -c "test ! -e data/backups/opendmtq-20200101-000000-manual.tar.gz && ls data/backups | grep -q before-delete"
timeout 300 wine OpenDMTQ.exe delete-data recordings --yes 2>&1 | cat > /tmp/delete.log || true
expect "OpenDMTQ.exe delete-data recordings --yes deletes them" grep -q "deleted: recordings" /tmp/delete.log
tail -n 4 /tmp/delete.log
before=$(web "$A/setup/ping")
timeout 600 wine OpenDMTQ.exe repair 2>&1 | cat > /tmp/repair.log || true
tail -n 8 /tmp/repair.log
expect "OpenDMTQ.exe repair checks everything and the window starts the server again with it" grep -q "the server started again with it" /tmp/repair.log
restarted=no
for _ in $(seq 1 120); do
  now=$(curl -s -m 3 "$A/setup/ping" || true)
  if [ -n "$now" ] && [ "$now" != "$before" ]; then restarted=yes; break; fi
  sleep 1
done
expect "and it answers again" test "$restarted" = yes
rm -f "$jar"
for _ in $(seq 1 30); do
  is 200 "$A/login" && break
  sleep 1
done
web -o /dev/null "$A/login"
web -o /dev/null -d "name=admin&password=winetest" "$A/login"
asked=$(web -o /tmp/uninstall.html -w '%{http_code}' --data-urlencode "csrf=$(web "$A/server" | token)" -d confirm=uninstall \
  "$A/server/uninstall")
expect "Uninstall on the Server page is asked for ($asked)" test "$asked" = 200
# The folder goes once the window has closed: its script tries again every two seconds.
for _ in $(seq 1 180); do
  [ -e "/tmp/Open DMTQ" ] || break
  sleep 1
done
expect "and the bundle's folder is gone once its window has closed" test ! -e "/tmp/Open DMTQ"
[ -e "/tmp/Open DMTQ" ] && { ls -A "/tmp/Open DMTQ"; tail -n 8 /tmp/again.log; }
cd /tmp
wineserver -k 2>/dev/null || true

echo "$([ $failures = 0 ] && echo PASS || echo FAIL) the Windows bundle under Wine: $failures failure(s)"
exit $((failures > 0))
