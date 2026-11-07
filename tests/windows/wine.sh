#!/usr/bin/env bash
# The Windows bundle under Wine, on Linux: a smoke test for when no Windows is at hand (CI's windows job runs the bundle
# on Windows itself, tests/windows/run.ps1). Builds the bundle (host/windows/build.sh), lays out the pages' stand-in game
# files like the game's client data and song data, starts OpenDMTQ.exe as a double-click does, and checks the game
# server's contract (tests/game/protocol.py), the admin pages, and the setup pages: the one-time sign-in, the import
# from the folder, and another address with the restart it makes. Needs Docker; nothing of the game's own, but with APK=
# the game's client goes through the setup too and the phone app is built with the bundle's Java, Apktool and signer.
#
# Wine is not Windows. Four things differ, and the test changes only its own copy of the bundle for them:
# - Wine (8.0 at least) lacks propsys' VariantToString, which Python's WMI module calls for platform details: it goes.
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

# ------------------------------------------------------------------------------ outside: build, then the Wine container

if [ -z "${IN_WINE:-}" ]; then
  if [ -z "${NO_BUILD:-}" ]; then
    "$ROOT/host/windows/build.sh" "$OUT"
  fi
  [ -f "$OUT/OpenDMTQ/OpenDMTQ.exe" ] || { echo "FAIL no bundle in $OUT (run host/windows/build.sh)"; exit 1; }
  # WineHQ's stable Wine, at a fixed version. Debian's own (8.0) lacks a network call Java makes when it seeds its random
  # numbers (java.net.NetworkInterface.getAll), so keytool and the signer died there and the app's build could not be tried.
  docker build -q -t opendmtq-wine:local - >/dev/null <<'DOCKERFILE'
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
    docker network inspect odq-closed >/dev/null 2>&1 || docker network create --internal --subnet 192.168.98.0/24 odq-closed >/dev/null
    network=(--network odq-closed)
  fi
  client=()
  if [ -n "${APK:-}" ]; then
    [ -f "$APK" ] || { echo "FAIL no such client: $APK"; exit 1; }
    client=(-v "$(cd "$(dirname "$APK")" && pwd)/$(basename "$APK"):/client.apk:ro" -e CLIENT=/client.apk)
  fi
  docker run --rm "${network[@]}" "${client[@]}" -e IN_WINE=1 -e PORT="$PORT" -e CLOSED="${CLOSED:-}" -e WINEDEBUG=-all \
    -e WINEPREFIX=/tmp/wine -v "$OUT/OpenDMTQ:/bundle:ro" -v "$ROOT:/repo:ro" opendmtq-wine:local bash /repo/tests/windows/wine.sh \
    || status=$?
  if [ -n "${CLOSED:-}" ]; then
    docker network rm odq-closed >/dev/null 2>&1 || true
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
export WINEDLLOVERRIDES="vcruntime140=n;vcruntime140_1=n"
# Wine sets itself up on its first program, with a line or two about it: not part of what is checked.
wine cmd /c ver >/dev/null 2>&1 || true

expect "OpenDMTQ.exe starts the bundle's Python and the host program" sh -c 'wine OpenDMTQ.exe --help 2>&1 | grep -q "Run an OpenDMTQ server without containers"'

# The pages' stand-in game files, laid out like the game's client data and song data.
mkdir -p /tmp/content /tmp/game/dmqglb.mb.pmang.com /tmp/game/_info
php /repo/tests/ui/make_content.php /tmp/content >/dev/null
cp -r /tmp/content/web/. /tmp/game/dmqglb.mb.pmang.com/
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
expect "the admin pages answer on this machine" is 200 "http://127.0.0.1:$ADMIN/opendmtq/admin/login"
expect "the admin pages answer on the public port" is 200 "http://127.0.0.1:$PORT/opendmtq/admin/login"
expect "signed out, the site asks to sign in" is 302 "http://127.0.0.1:$PORT/opendmtq/index.php"

# The setup pages, as the browser the window opened sees them: signed in by the one-time key it carries (the file the
# window wrote, though the server answered only after the wait ran out), the PC's drives to pick from, and the import of
# the folder.
A="http://127.0.0.1:$ADMIN/opendmtq/admin"
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
  back=$(grep -o '"/opendmtq/admin/setup/start?key=[^"]*"' <<<"$page" | tr -d '"' | sed 's/\\u0026/\&/g')
  restarted=no
  for _ in $(seq 1 90); do
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
  went=$(web -o /dev/null -w '%{http_code} %{redirect_url}' "http://127.0.0.1:$ADMIN$back")
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
  built=$(ls -t data/apk/out/OpenDMTQ-*.apk 2>/dev/null | head -n 1 || true)
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

echo "$([ $failures = 0 ] && echo PASS || echo FAIL) the Windows bundle under Wine: $failures failure(s)"
exit $((failures > 0))
