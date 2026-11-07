#!/usr/bin/env bash
# A host install on a clean system: a container stands in for the computer (Ubuntu 24.04 by default), with a user who
# installs as people do. host/install.sh; the stand-in game files of the pages' tests in Downloads, laid out like the
# game's client data and song data; opendmtq setup, and its pages in the browser as the owner goes through them (the
# one-time link, the files found and imported, a player's account); the game server's contract (tests/game/protocol.py),
# the site, a stop and a start again, another address chosen in the setup and the restart it makes, the port taken by
# another program, and PHP's log. With APK=<file> the client
# goes beside the files and the setup builds the phone app from it (it never leaves this machine). Needs Docker and
# Python 3; nothing of the game's own.
#
# Usage: tests/host/run.sh      (DISTRO=debian:12 for another system; PORT, default 18711; KEEP=1 leaves it running)
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
DISTRO=${DISTRO:-ubuntu:24.04}
PORT=${PORT:-18711}
ADMIN=$((PORT + 1))
NAME=odq-hosttest
IMAGE=opendmtqtest:$(echo "$DISTRO" | tr ':/' '--')
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
# expect <name> <command...>: PASS when the command succeeds, FAIL otherwise.
expect() {
  local name=$1
  shift
  if "$@"; then pass "$name"; else fail "$name"; fi
}
# The HTTP status of an address (000 when nothing answers).
code() { curl -s -o /dev/null -w '%{http_code}' -m 10 "$1"; }
# is <status> <address>: the address answers with that status.
is() { [ "$(code "$2")" = "$1" ]; }
# A command as the user inside the computer, in their home folder.
inside() { docker exec -u player -w /home/player "$NAME" bash -lc "$1"; }

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
if [ -z "${KEEP:-}" ]; then
  trap cleanup EXIT
fi

# The computer: the system, sudo, and a user who may use it without a password (install.sh asks for nothing else).
docker build -q -t "$IMAGE" - >/dev/null <<EOF
FROM $DISTRO
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq sudo ca-certificates curl >/dev/null \
    && useradd -m -s /bin/bash player && echo 'player ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/player
EOF
docker rm -f "$NAME" >/dev/null 2>&1 || true
# On the host's network: the server's port is the computer's own, as for a real install.
docker run -d --name "$NAME" --network host "$IMAGE" sleep infinity >/dev/null
# This working tree as GitHub hands out a release (a folder with everything in it, without data/, the scratch folders or
# an earlier install's .host/), in place of the download.
tar -C "$ROOT" --exclude=./data --exclude=./_work --exclude=./.host --exclude=./.git --exclude=./.env \
  --transform 's,^\.,openDMTQ-main,' -czf - . | docker exec -i -u player -w /home/player "$NAME" sh -c 'cat > /tmp/release.tar.gz'
# The script the README's one command runs, as a pipe gives it to the shell.
tar -C "$ROOT" -cf - host/get.sh | docker exec -i -u player "$NAME" sh -c 'tar -C /tmp -xf -'

# 1. The install, as the README says: the one command, up to where it would start the setup. Through a pipe and with a
#    terminal, as a person runs it: a script that takes the terminal for its own input stops there without a word, with
#    bash as sh on most systems. So in bash here; the run near the end goes through this system's sh.
# With a time limit: what asks the terminal a question waits for ever here, as it did when apt asked for a time zone.
if timeout 900 docker exec -t -u player -w /home/player "$NAME" bash -lc \
    "cat /tmp/host/get.sh | OPENDMTQ_TARBALL=file:///tmp/release.tar.gz OPENDMTQ_DIR=\$HOME/OpenDMTQ OPENDMTQ_NO_SETUP=1 bash" \
    > /tmp/odq-hosttest-install.log 2>&1 && inside "test -f OpenDMTQ/.host/installed"; then
  pass "the one command downloads OpenDMTQ and installs everything on $DISTRO"
else
  tail -n 30 /tmp/odq-hosttest-install.log
  fail "the one command on $DISTRO"
  exit 1
fi
expect "opendmtq is on the PATH, and runs the host install" inside "opendmtq --help | grep -q 'without containers'"

# 2. The game's files where people keep them: the stand-in client data and song data unpacked in a folder in Downloads,
#    with the client beside them when one is given (it is copied in for this run only). Nothing is imported yet: the
#    setup pages find them there.
inside "mkdir -p /tmp/content && php OpenDMTQ/tests/ui/make_content.php /tmp/content >/dev/null \
  && mkdir -p Downloads/DMTQ/dmtq/dmqglb.mb.pmang.com Downloads/DMTQ/dmtq/_info \
  && cp -r /tmp/content/web/. Downloads/DMTQ/dmtq/dmqglb.mb.pmang.com/ && cp /tmp/content/songs.json Downloads/DMTQ/dmtq/_info/songList.json"
if [ -n "${APK:-}" ]; then
  docker cp "$APK" "$NAME:/home/player/Downloads/DMTQ/client.apk"
  docker exec "$NAME" chown player /home/player/Downloads/DMTQ/client.apk
fi
# The runtime for newer phones, as a server without internet gets it: a release's zip, put in data/apk by hand. This machine's
# own bundle stands in for the release's; without one (nothing here built it) the builder tries the release and says so.
BUNDLE=${ARM32_BUNDLE:-$ROOT/data/apk/arm32}
if [ -f "$BUNDLE/bundle.json" ]; then
  python3 "$ROOT/tools/opendmtq_tools/runtime.py" --pack "$BUNDLE" /tmp/odq-hosttest-runtime.zip >/dev/null
  inside "mkdir -p OpenDMTQ/data/apk"
  docker cp /tmp/odq-hosttest-runtime.zip "$NAME:/home/player/OpenDMTQ/data/apk/opendmtq-arm32-runtime.zip"
  docker exec "$NAME" chown -R player /home/player/OpenDMTQ/data
fi
# The settings setup would write, with this test's ports (a loopback address, which setup refuses for phones).
inside "printf 'PUBLIC_HOST=127.0.0.1:$PORT\nLISTEN_PORT=$PORT\nADMIN_PORT=$ADMIN\nADMIN_PASSWORD=hosttest\n' > OpenDMTQ/.env"

# 3. setup starts the server and, with nothing imported, hands over to its pages: there is no browser here, so it
#    prints their one-time link.
if inside "opendmtq setup" > /tmp/odq-hosttest-setup.log 2>&1; then
  pass "opendmtq setup: the server answers"
else
  cat /tmp/odq-hosttest-setup.log
  inside "tail -n 40 OpenDMTQ/data/state/logs/host.log OpenDMTQ/data/state/logs/server.log OpenDMTQ/data/state/logs/programs.log" || true
  fail "opendmtq setup"
  exit 1
fi
link=$(grep -o "http://localhost:$ADMIN/opendmtq/admin/setup/start?key=[A-Za-z0-9_-]*" /tmp/odq-hosttest-setup.log | tail -n 1 || true)
expect "setup prints the one-time link to its pages" test -n "$link"
expect "setup prints the way in from another computer" grep -q "From another computer: http://127.0.0.1:$PORT/opendmtq/admin/setup" /tmp/odq-hosttest-setup.log

# 4. The setup in the browser, as the owner goes through it: the link, the files found in Downloads, the import, an
#    account for a player, and the app.
admin=$(mktemp)
site=$(mktemp)
web() { curl -s -m 60 -c "$1" -b "$1" "${@:2}"; }
A="http://127.0.0.1:$ADMIN/opendmtq/admin"
# The form token on a page of the admin pages.
token() { grep -o 'name="csrf" value="[^"]*"' | head -n 1 | cut -d'"' -f4; }
# have <label>: the setup's files step says that file is in place (its lamp is on).
have() {
  python3 -c 'import re, sys; sys.exit(0 if re.search("<dt>" + re.escape(sys.argv[1]) + "</dt><dd><span class=\"lamp on\">", sys.stdin.read()) else 1)' "$1"
}
# follow <job>: the state a job of the admin pages ends in, followed as the page follows it (ten minutes at most). A
# job that did not end well has its output shown.
follow() {
  local state=running
  for _ in $(seq 600); do
    state=$(web "$admin" "$A/jobs/$1" | python3 -c 'import json, sys; print(json.load(sys.stdin)["state"])' 2>/dev/null || echo gone)
    [ "$state" = running ] || break
    sleep 1
  done
  [ "$state" = "done" ] || web "$admin" "$A/jobs/$1" | python3 -c 'import json, sys; print("\n".join(json.load(sys.stdin)["log"][-30:]))' 2>/dev/null || true
  echo "$state"
}
# The job a form started, from the page it led to.
job_of() { sed -n 's/.*[?&]job=\([0-9a-f]*\).*/\1/p'; }

# The link signs in once, from this computer, and the files step lists the folder in Downloads.
went=$(web "$admin" -o /dev/null -w '%{http_code} %{redirect_url}' "${link/localhost/127.0.0.1}")
expect "the one-time link signs the browser in ($went)" test "$went" = "302 $A/setup"
files=$(web "$admin" "$A/setup")
expect "the setup opens at the game's files, with the folder found in Downloads" grep -q 'value="/home/player/Downloads/DMTQ"' <<<"$files"
again=$(curl -s -o /dev/null -w '%{redirect_url}' "${link/localhost/127.0.0.1}")
expect "the link works once" grep -q "/login" <<<"$again"
# The import, as the button beside the found folder sends it, followed to its end.
job=$(web "$admin" -o /dev/null -w '%{redirect_url}' --data-urlencode "csrf=$(token <<<"$files")" \
  --data-urlencode "path=/home/player/Downloads/DMTQ" -d "songs=yes" "$A/setup/import" | job_of)
expect "the setup starts the import" test -n "$job"
state=$(follow "$job" | tail -n 1)
expect "the import ends well ($state)" test "$state" = "done"
files=$(web "$admin" "$A/setup?step=files")
expect "the files step has the client data" have "Client data" <<<"$files"
expect "the files step has the songs" have "Songs" <<<"$files"
expect "with the game's files in, the server is healthy" is 200 "http://127.0.0.1:$PORT/opendmtq/health.php"
expect "a song's jacket is served from the imported content" is 200 "http://127.0.0.1:$PORT/viewImg/eye/fixture1.png"

# 5. The game server's contract, as on the image, on the imported files.
if python3 "$ROOT/tests/game/protocol.py" "http://127.0.0.1:$PORT"; then
  pass "the game server's contract on a host install"
else
  fail "the game server's contract on a host install"
fi
# An account for a player, its password shown once.
made=$(web "$admin" -o /dev/null -w '%{http_code}' --data-urlencode "csrf=$(web "$admin" "$A/setup?step=players" | token)" \
  -d "name=tester" "$A/setup/player")
expect "the owner makes a player's account in the setup ($made)" test "$made" = 302
password=$(web "$admin" "$A/setup?step=players" | grep -o '<dd><code>[^<]*</code></dd>' | head -n 1 | sed 's/<[^>]*>//g')
expect "the setup shows the account's password" test -n "$password"

# 6. The site, for that player. Signed out, it asks for an account and answers only its sign-in and licenses.
expect "a bare visit goes to the site" is 302 "http://127.0.0.1:$PORT/"
expect "signed out, the site asks to sign in" is 302 "http://127.0.0.1:$PORT/opendmtq/index.php"
expect "the sign-in page answers" is 200 "http://127.0.0.1:$PORT/opendmtq/login.php"
expect "the licenses page answers anyone" is 200 "http://127.0.0.1:$PORT/opendmtq/licenses.php"
expect "the admin pages answer on this machine" is 200 "$A/login"
expect "the admin pages answer on the public port" is 200 "http://127.0.0.1:$PORT/opendmtq/admin/login"
web "$site" -o /dev/null "http://127.0.0.1:$PORT/opendmtq/login.php"
player=$(web "$site" -o /dev/null -w '%{http_code}' --data-urlencode "user=tester" --data-urlencode "password=$password" \
  -d "next=/opendmtq/" "http://127.0.0.1:$PORT/opendmtq/login.php")
expect "the player signs in to the site with that password ($player)" test "$player" = 303
for page in index.php songs.php ranking.php download.php live.php; do
  got=$(web "$site" -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/opendmtq/$page")
  expect "signed in, the site's $page answers ($got)" test "$got" = 200
done

# 7. The phone app, built on the setup's last step from the client that came in with the import.
if [ -n "${APK:-}" ]; then
  expect "the client came in with the import" have "Android app" <<<"$files"
  job=$(web "$admin" -o /dev/null -w '%{redirect_url}' --data-urlencode "csrf=$(web "$admin" "$A/setup?step=app" | token)" \
    "$A/setup/build" | job_of)
  expect "the setup starts the app's build" test -n "$job"
  state=$(follow "$job" | tail -n 1)
  expect "the build ends well ($state)" test "$state" = "done"
  page=$(web "$admin" "$A/setup?step=app")
  expect "the setup is done" grep -q "Your server is set up." <<<"$page"
  if [ -f "$BUNDLE/bundle.json" ]; then
    expect "the setup says the app runs on newer phones too, without having asked" grep -q "runs on newer phones too" <<<"$page"
    built=$(inside "ls -t OpenDMTQ/data/apk/out/*.apk | head -n 1")
    list=$(inside "python3 -m zipfile -l '$built'" | awk '{print $1}')
    expect "the app has the translator" grep -qx "lib/arm64-v8a/libarm32.so" <<<"$list"
    expect "and the licenses of what it adds" grep -qx "assets/opendmtq/NOTICES.txt" <<<"$list"
    rm -f /tmp/odq-hosttest-runtime.zip
  fi
  expect "signed out, the app's download asks to sign in" is 302 "http://127.0.0.1:$PORT/apk"
  size=$(web "$site" -o /dev/null -w '%{size_download}' "http://127.0.0.1:$PORT/apk")
  expect "signed in, the site offers the app ($size bytes)" test "${size:-0}" -gt 1000000
else
  expect "without a client the files step says the APK is missing" test "$(have "Android app" <<<"$files" && echo yes)" = ""
fi

# 8. Stopped, then started again: the same data, answering again. A stop the admin pages asked of the run before and that
#    it never read is not this run's: two of the watch's rounds later the server still answers.
inside "opendmtq stop" >/dev/null || true
expect "opendmtq stop: nothing answers" is 000 "http://127.0.0.1:$PORT/opendmtq/health.php"
inside "echo 0 > OpenDMTQ/.host/run/stop.request"
inside "opendmtq start" >/dev/null || true
expect "started again, healthy" is 200 "http://127.0.0.1:$PORT/opendmtq/health.php"
sleep 5
expect "a stop asked of an earlier run is not this run's" is 200 "http://127.0.0.1:$PORT/opendmtq/health.php"

# 8b. Stopped from the admin pages (Maintenance): the program that runs the server stops every part and ends, its log
#     says why, and a start brings it back. The owner signs in first (the stop above ended the sessions).
# A server already gone (a fault above) fails the checks below, not the whole run.
web "$admin" -o /dev/null -d "name=admin&password=hosttest" "$A/login" || true
stopped=$(web "$admin" -o /tmp/odq-hosttest-stopped.html -w '%{http_code}' \
  --data-urlencode "csrf=$(web "$admin" "$A/maintenance" | token)" "$A/server/stop" || true)
expect "the admin pages' Stop the server answers ($stopped)" test "$stopped" = 200
expect "and says the command that starts it again" grep -q "./opendmtq start" /tmp/odq-hosttest-stopped.html
for _ in $(seq 30); do
  inside "test ! -e OpenDMTQ/.host/run/host.pid" && break
  sleep 1
done
expect "and the server stops: nothing answers" is 000 "http://127.0.0.1:$PORT/opendmtq/health.php"
expect "and nothing of it stays running" inside "test ! -e OpenDMTQ/.host/run/host.pid"
expect "its log says the admin pages asked for the stop" inside "grep -q 'as asked on the admin pages' OpenDMTQ/data/state/logs/host.log"
inside "opendmtq start" >/dev/null || true
expect "started again after that, healthy" is 200 "http://127.0.0.1:$PORT/opendmtq/health.php"
inside "opendmtq status"

# 9. Another address, chosen in the setup: saved to .env, the server started again for it, and the browser back,
#    signed in, at the players' step. The owner signs in with the password first (the stop ended the sessions).
lan=$(inside "hostname -I" | tr ' ' '\n' | grep -E '^(10|172\.(1[6-9]|2[0-9]|3[01])|192\.168)\.' | head -n 1 || true)
if [ -n "$lan" ]; then
  web "$admin" -o /dev/null "$A/login"
  signin=$(web "$admin" -o /dev/null -w '%{http_code}' -d "name=admin&password=hosttest" "$A/login")
  expect "the owner signs in with the password in .env ($signin)" test "$signin" = 302
  before=$(web "$admin" "$A/setup/ping")
  page=$(web "$admin" --data-urlencode "csrf=$(web "$admin" "$A/setup?step=address" | token)" -d "host=$lan" "$A/setup/address")
  expect "the setup saves the new address to .env" inside "grep -qx 'PUBLIC_HOST=$lan:$PORT' OpenDMTQ/.env"
  # The page waits for another process to answer, then goes on with the key it carries.
  back=$(grep -o '"/opendmtq/admin/setup/start?key=[^"]*"' <<<"$page" | tr -d '"' | sed 's/\\u0026/\&/g')
  restarted=no
  for _ in $(seq 90); do
    # A short wait for each look: a closed port may swallow the connection rather than refuse it (WSL).
    now=$(curl -s -m 3 "$A/setup/ping" || true)
    if [ -n "$now" ] && [ "$now" != "$before" ]; then restarted=yes; break; fi
    sleep 1
  done
  expect "the server starts again by itself" test "$restarted" = yes
  went=$(web "$admin" -o /dev/null -w '%{http_code} %{redirect_url}' "http://127.0.0.1:$ADMIN$back")
  expect "the page comes back signed in, at the players' step ($went)" test "$went" = "302 $A/setup?step=players"
  expect "the server answers at the new address" is 200 "http://$lan:$PORT/opendmtq/health.php"
else
  echo "SKIP no private address on this machine: the address change is not tried"
fi
rm -f "$admin" "$site"

# 10. Another program on the server's port: start says so soon, with what usually causes it, and nothing stays running.
# Free again, the server starts.
inside "opendmtq stop" >/dev/null || true
inside "nohup python3 -m http.server $PORT >/dev/null 2>&1 & echo \$! > /tmp/holder.pid"
for _ in $(seq 10); do
  is 200 "http://127.0.0.1:$PORT/" && break
  sleep 1
done
before=$SECONDS
if said=$(inside "opendmtq start" 2>&1); then
  fail "with the port taken, opendmtq start says it worked"
else
  expect "with the port taken, opendmtq start says why" grep -q "apache keeps stopping. Often another program holds port $PORT" <<<"$said"
fi
expect "and does not wait out its minute ($((SECONDS - before)) s)" test "$((SECONDS - before))" -lt 50
expect "and nothing of it stays running" inside "test ! -e OpenDMTQ/.host/run/host.pid"
inside "kill \$(cat /tmp/holder.pid)"
if inside "opendmtq start" >/dev/null 2>&1; then
  pass "with the port free again, the server starts"
else
  fail "with the port free again, the server starts"
fi

# 11. The one command again: an update. It stops the server, puts the new code over the old, and the settings, the data
#     and the install stay.
marker=$(inside "sha256sum OpenDMTQ/.env | cut -d' ' -f1")
if timeout 600 docker exec -u player -w /home/player "$NAME" bash -lc \
    "cat /tmp/host/get.sh | OPENDMTQ_TARBALL=file:///tmp/release.tar.gz OPENDMTQ_DIR=\$HOME/OpenDMTQ OPENDMTQ_NO_SETUP=1 sh" \
    > /tmp/odq-hosttest-update.log 2>&1; then
  pass "the one command again updates the folder"
else
  tail -n 30 /tmp/odq-hosttest-update.log
  fail "the one command again updates the folder"
fi
expect "the update keeps the settings" test "$marker" = "$(inside "sha256sum OpenDMTQ/.env | cut -d' ' -f1")"
expect "and the database" inside "test -s OpenDMTQ/data/state/dmtq.db3"
if inside "opendmtq start" >/dev/null 2>&1; then
  pass "after the update the server starts"
else
  fail "after the update the server starts"
fi
expect "as root it says to use a normal user" sh -c "docker exec -u root -w /home/player/OpenDMTQ $NAME sh -c 'id -u; sh < host/get.sh' 2>&1 | grep -q 'not as root'"

# 12. PHP said nothing in the server's log.
if inside "grep -E 'PHP (Warning|Notice|Deprecated|Fatal error|Parse error)' OpenDMTQ/data/state/logs/server.log"; then
  fail "PHP complained in the server's log (above)"
else
  pass "PHP said nothing in the server's log"
fi

echo "$([ $failures = 0 ] && echo PASS || echo FAIL) the host install on $DISTRO: $failures failure(s)"
exit $((failures > 0))
