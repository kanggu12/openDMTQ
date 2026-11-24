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
# The game host's folder's name, which the import knows the game's files by (tests/game_host.py: the repository's text
# names none of the game's own).
GAME_HOST=$(python3 "$ROOT/tests/game_host.py")
DISTRO=${DISTRO:-ubuntu:24.04}
PORT=${PORT:-18711}
ADMIN=$((PORT + 1))
# NAME_PREFIX keeps this run's container apart from another run's on the same machine.
NAME=${NAME_PREFIX:-odq}-hosttest
IMAGE=opendmtqtest:$(echo "$DISTRO" | tr ':/' '--')
# The system's packages from a mirror near the machine when one is named (APT_MIRROR, an Ubuntu archive's URL): on GitHub's
# runners Azure's own copy of the Ubuntu archive, where the public archive answered at times so slowly that the one
# command's packages took longer than its time limit (the install itself is the same from any mirror).
APT_MIRROR=${APT_MIRROR:-}
if [ -z "$APT_MIRROR" ] && [ "${GITHUB_ACTIONS:-}" = true ] && [ "${DISTRO%%:*}" = ubuntu ]; then
  APT_MIRROR=http://azure.archive.ubuntu.com/ubuntu
fi
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
# The admin service's own port starts from $ADMIN here, within this test's ports: on the computer's own network the
# usual one (18791) would be another program's to use.
inside() { docker exec -u player -w /home/player -e OPENDMTQ_ADMIN_SERVICE_PORT="$ADMIN" "$NAME" bash -lc "$1"; }
# Waits up to five minutes for the app build the server runs at its start to end (its build.json no longer building).
builder_done() {
  local _
  for _ in $(seq 300); do
    inside "grep -q '\"state\": *\"building\"' OpenDMTQ/data/apk/out/build.json 2>/dev/null" || return 0
    sleep 1
  done
}

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
if [ -z "${KEEP:-}" ]; then
  trap cleanup EXIT
fi

# The computer: the system, sudo, and a user who may use it without a password (install.sh asks for nothing else).
docker build -q -t "$IMAGE" - >/dev/null <<EOF
FROM $DISTRO
RUN if [ -n "$APT_MIRROR" ]; then sed -i -e 's|http://archive.ubuntu.com/ubuntu|$APT_MIRROR|g' \
      -e 's|http://security.ubuntu.com/ubuntu|$APT_MIRROR|g' /etc/apt/sources.list.d/ubuntu.sources; fi
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
    > /tmp/$NAME-install.log 2>&1 && inside "test -f OpenDMTQ/.host/installed"; then
  pass "the one command downloads OpenDMTQ and installs everything on $DISTRO"
else
  tail -n 30 /tmp/$NAME-install.log
  fail "the one command on $DISTRO"
  exit 1
fi
expect "opendmtq is on the PATH, and runs the host install" inside "opendmtq --help | grep -q 'without containers'"

# 2. The game's files where people keep them: the stand-in client data and song data unpacked in a folder in Downloads,
#    with the client beside them when one is given (it is copied in for this run only). Nothing is imported yet: the
#    setup pages find them there.
inside "mkdir -p /tmp/content && php OpenDMTQ/tests/ui/make_content.php /tmp/content >/dev/null \
  && mkdir -p Downloads/DMTQ/dmtq/$GAME_HOST Downloads/DMTQ/dmtq/_info \
  && cp -r /tmp/content/web/. Downloads/DMTQ/dmtq/$GAME_HOST/ && cp /tmp/content/songs.json Downloads/DMTQ/dmtq/_info/songList.json"
if [ -n "${APK:-}" ]; then
  docker cp "$APK" "$NAME:/home/player/Downloads/DMTQ/client.apk"
  docker exec "$NAME" chown player /home/player/Downloads/DMTQ/client.apk
fi
# The runtime for newer phones, as a server without internet gets it: a release's zip, put in data/apk by hand. This machine's
# own bundle stands in for the release's; without one (nothing here built it) the builder tries the release and says so.
BUNDLE=${ARM32_BUNDLE:-$ROOT/data/apk/arm32}
if [ -f "$BUNDLE/bundle.json" ]; then
  python3 "$ROOT/tools/opendmtq_tools/runtime.py" --pack "$BUNDLE" /tmp/$NAME-runtime.zip >/dev/null
  inside "mkdir -p OpenDMTQ/data/apk"
  docker cp /tmp/$NAME-runtime.zip "$NAME:/home/player/OpenDMTQ/data/apk/opendmtq-arm32-runtime.zip"
  docker exec "$NAME" chown -R player /home/player/OpenDMTQ/data
fi
# The settings setup would write, with this test's ports (a loopback address, which setup refuses for phones): the
# server's one port, and the admin service's own beside it on loopback, as an install from before 0.11.0 has it.
inside "printf 'PUBLIC_HOST=127.0.0.1:$PORT\nLISTEN_PORT=$PORT\nADMIN_PASSWORD=hosttest\n' > OpenDMTQ/.env"

# 3. setup starts the server and, with nothing imported, hands over to its pages: there is no browser here, so it
#    prints their one-time link.
if inside "opendmtq setup" > /tmp/$NAME-setup.log 2>&1; then
  pass "opendmtq setup: the server answers"
else
  cat /tmp/$NAME-setup.log
  inside "tail -n 40 OpenDMTQ/data/state/logs/host.log OpenDMTQ/data/state/logs/server.log OpenDMTQ/data/state/logs/programs.log" || true
  fail "opendmtq setup"
  exit 1
fi
link=$(grep -o "http://localhost:$PORT/opendmtq/admin/setup/start?key=[A-Za-z0-9_-]*" /tmp/$NAME-setup.log | tail -n 1 || true)
expect "setup prints the one-time link to its pages, on the server's one port" test -n "$link"
expect "setup prints the way in from another computer" grep -q "From another computer: http://127.0.0.1:$PORT/opendmtq/admin/setup" /tmp/$NAME-setup.log

# 4. The setup in the browser, as the owner goes through it: the link, the files found in Downloads, the import, an
#    account for a player, and the app.
admin=$(mktemp)
site=$(mktemp)
web() { curl -s -m 60 -c "$1" -b "$1" "${@:2}"; }
# The admin pages on the server's one port, as the owner opens them (DEP-45).
A="http://127.0.0.1:$PORT/opendmtq/admin"
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
expect "the admin pages answer on the server's one port" is 200 "$A/login"
expect "the admin service's own port is loopback only" sh -c "! ss -ltn | grep -q '0.0.0.0:$ADMIN '"
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
    rm -f /tmp/$NAME-runtime.zip
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
# owner_signs_in <when>: the ID and password that .env and the console name open both the admin pages and the players'
# site (ADM-105), each in a browser of its own.
owner_signs_in() {
  local jar code
  jar=$(mktemp)
  web "$jar" -o /dev/null "$A/login"
  code=$(web "$jar" -o /dev/null -w '%{http_code}' -d "name=admin&password=hosttest" "$A/login")
  expect "$1, the owner signs in to the admin pages with .env's password ($code)" test "$code" = 302
  rm -f "$jar"
  jar=$(mktemp)
  web "$jar" -o /dev/null "http://127.0.0.1:$PORT/opendmtq/login.php"
  code=$(web "$jar" -o /dev/null -w '%{http_code}' --data-urlencode "user=admin" --data-urlencode "password=hosttest" \
    -d "next=/opendmtq/" "http://127.0.0.1:$PORT/opendmtq/login.php")
  expect "$1, the owner signs in to the players' site with the same ID and password ($code)" test "$code" = 303
  rm -f "$jar"
}
owner_signs_in "stopped and started again"
inside "opendmtq status" > /tmp/$NAME-status.log 2>&1 || true
expect "status names the admin pages on the one port" grep -q "Admin pages  http://127.0.0.1:$PORT/opendmtq/admin/" /tmp/$NAME-status.log
expect "and no other port" sh -c "! grep -q ':$ADMIN' /tmp/$NAME-status.log"

# 8b. Stopped from the admin pages (Maintenance): the program that runs the server stops every part and ends, its log
#     says why, and a start brings it back. The owner signs in first (the stop above ended the sessions).
# A server already gone (a fault above) fails the checks below, not the whole run.
web "$admin" -o /dev/null -d "name=admin&password=hosttest" "$A/login" || true
stopped=$(web "$admin" -o /tmp/$NAME-stopped.html -w '%{http_code}' \
  --data-urlencode "csrf=$(web "$admin" "$A/maintenance" | token)" "$A/server/stop" || true)
expect "the admin pages' Stop the server answers ($stopped)" test "$stopped" = 200
expect "and says the command that starts it again" grep -q "./opendmtq start" /tmp/$NAME-stopped.html
for _ in $(seq 30); do
  inside "test ! -e OpenDMTQ/.host/run/host.pid" && break
  sleep 1
done
expect "and the server stops: nothing answers" is 000 "http://127.0.0.1:$PORT/opendmtq/health.php"
expect "and nothing of it stays running" inside "test ! -e OpenDMTQ/.host/run/host.pid"
expect "its log says the admin pages asked for the stop" inside "grep -q 'as asked on the admin pages' OpenDMTQ/data/state/logs/host.log"
inside "opendmtq start" >/dev/null || true
expect "started again after that, healthy" is 200 "http://127.0.0.1:$PORT/opendmtq/health.php"
owner_signs_in "stopped from the admin pages and started again"
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
  # The way back, as the page's script reads it: its data-back attribute, its HTML escapes undone as a browser does.
  back=$(grep -o 'data-back="[^"]*"' <<<"$page" | sed -e 's/^data-back="//' -e 's/"$//' -e 's/&amp;/\&/g')
  expect "the page that waits for the restart carries the way back, with its one-time key" \
    test "${back#/opendmtq/admin/setup/start?key=}" != "$back"
  restarted=no
  # Through the server's one port: the answer comes once Apache is back too (the page itself waits for as long as it takes).
  for _ in $(seq 300); do
    # A short wait for each look: a closed port may swallow the connection rather than refuse it (WSL).
    now=$(curl -s -m 3 "$A/setup/ping" || true)
    if [ -n "$now" ] && [ "$now" != "$before" ]; then restarted=yes; break; fi
    sleep 1
  done
  expect "the server starts again by itself" test "$restarted" = yes
  # As the page does: the new process answering twice in a row before the way back, and the way back asked again while
  # the server's one port says 503 (its parts still coming up), as a person reloading would.
  curl -s -m 3 "$A/setup/ping" >/dev/null || true
  for _ in $(seq 30); do
    went=$(web "$admin" -o /dev/null -w '%{http_code} %{redirect_url}' "http://127.0.0.1:$PORT$back")
    [ "${went%% *}" = 503 ] || break
    sleep 1
  done
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
    > /tmp/$NAME-update.log 2>&1; then
  pass "the one command again updates the folder"
else
  tail -n 30 /tmp/$NAME-update.log
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

# 13. The Server page and its command lines: restart, repair, the data, uninstall. Last, as the uninstall takes the folder.
admin=$(mktemp)
# signed_in: the owner signs in again (a restart ends the pages' sessions).
signed_in() {
  web "$admin" -o /dev/null "$A/login"
  web "$admin" -o /dev/null -d "name=admin&password=hosttest" "$A/login"
}
# job_ends <redirect>: how a job the Server page started ended: followed to its end when the page did not wait for it,
# else what the page then says (a message of the bad kind: failed, shown).
job_ends() {
  local job said
  job=$(job_of <<<"$1")
  if [ -n "$job" ]; then
    follow "$job" | tail -n 1
    return
  fi
  said=$(web "$admin" "$A/server")
  if grep -q 'class="flash bad"' <<<"$said"; then
    grep -o '<p class="flash bad"[^>]*>[^<]*' <<<"$said" | sed 's/<[^>]*>//' >&2
    echo failed
  else
    echo "done"
  fi
}
# has_actions: the Server page in $page has each of the forms a host install has.
has_actions() {
  local a
  for a in restart stop repair data uninstall; do
    grep -q "action=\"/opendmtq/admin/server/$a\"" <<<"$page" || return 1
  done
}
signed_in
page=$(web "$admin" "$A/server")
expect "the Server page has Restart, Stop the server, the repair, the data and Uninstall (ADM-113)" has_actions
# The address as .env has it now (the setup's step moved it to this computer's network address).
address=$(inside "sed -n 's/^PUBLIC_HOST=//p' OpenDMTQ/.env" | tr -d '\r')
expect "and names the one address on the server's port ($address)" grep -q "http://$address/opendmtq/admin/" <<<"$page"
expect "the install wrote the list of the program's files" inside "test -s OpenDMTQ/.host/manifest.sha256"
# Restart: the server's program starts every part again, and these pages answer as another process.
before=$(web "$admin" "$A/setup/ping")
answer=$(web "$admin" -o /dev/null -w '%{http_code}' --data-urlencode "csrf=$(token <<<"$page")" "$A/server/restart")
expect "Restart on the Server page is asked for ($answer)" test "$answer" = 200
restarted=no
for _ in $(seq 90); do
  now=$(curl -s -m 3 "$A/setup/ping" || true)
  if [ -n "$now" ] && [ "$now" != "$before" ]; then restarted=yes; break; fi
  sleep 1
done
expect "and the server starts again" test "$restarted" = yes
expect "and answers" is 200 "http://127.0.0.1:$PORT/opendmtq/health.php"
# Repair: a program file gone, one changed, a data folder and the owner's sign-in for the site gone. The release's code is
# the test's own copy (as for the install), which the server's programs get from the start's environment.
inside "opendmtq stop" >/dev/null || true
inside "OPENDMTQ_TARBALL=file:///tmp/release.tar.gz opendmtq start" >/dev/null || true
# The app build the server runs at its start ends first (data/apk/out/build.json): a repair waits for any build, as the
# page says when it refuses one while it runs, and a person presses again after it.
builder_done
inside "rm OpenDMTQ/server/portal/robots.txt && echo changed >> OpenDMTQ/docs/faq.md && rm -rf OpenDMTQ/data/backups OpenDMTQ/data/state/owner.pass"
signed_in
went=$(web "$admin" -o /dev/null -w '%{redirect_url}' --data-urlencode "csrf=$(web "$admin" "$A/server" | token)" "$A/server/repair")
state=$(job_ends "$went")
expect "Check and repair on the Server page ends ($state) (SRV-47)" test "$state" = "done"
expect "the program file that was gone is back" inside "test -s OpenDMTQ/server/portal/robots.txt"
expect "the one that was changed is as the release has it" inside "! grep -q '^changed$' OpenDMTQ/docs/faq.md"
expect "the data folder is there again" inside "test -d OpenDMTQ/data/backups"
expect "and the owner's sign-in for the site" inside "test -s OpenDMTQ/data/state/owner.pass"
# The same from the command line, once the build of the repair's own restart has ended.
builder_done
inside "rm OpenDMTQ/server/portal/robots.txt"
expect "opendmtq repair puts a program file back too" inside "OPENDMTQ_TARBALL=file:///tmp/release.tar.gz opendmtq repair > /tmp/repair.log 2>&1 && test -s OpenDMTQ/server/portal/robots.txt"
inside "tail -n 4 /tmp/repair.log" || true
# It says the server started again only once it has: the next request finds the new run whole, not the old one leaving.
expect "and says the server started again once it has" inside "grep -q 'the server started again with it' /tmp/repair.log"
for _ in $(seq 60); do is 200 "http://127.0.0.1:$PORT/opendmtq/health.php" && break; sleep 1; done
# The data: an old backup and the logs, a backup made first and kept.
inside "mkdir -p OpenDMTQ/data/backups && echo old > OpenDMTQ/data/backups/opendmtq-20200101-000000-manual.tar.gz"
signed_in
went=$(web "$admin" -o /dev/null -w '%{redirect_url}' --data-urlencode "csrf=$(web "$admin" "$A/server" | token)" -d part=backups -d part=logs \
  -d backup=yes -d confirm=delete "$A/server/data")
state=$(job_ends "$went")
expect "deleting the backups and the logs on the Server page ends ($state) (ADM-113)" test "$state" = "done"
expect "the old backup is gone" inside "test ! -e OpenDMTQ/data/backups/opendmtq-20200101-000000-manual.tar.gz"
expect "the backup made first stays" inside "ls OpenDMTQ/data/backups | grep -q before-delete"
expect "the programs' log was emptied" inside "test \$(stat -c %s OpenDMTQ/data/state/logs/programs.log) -lt 4096"
went=$(web "$admin" -o /dev/null -w '%{http_code}' --data-urlencode "csrf=$(web "$admin" "$A/server" | token)" -d part=logs -d confirm=yes "$A/server/data")
expect "without the word typed nothing is deleted ($went)" test "$went" = 302
expect "opendmtq delete-data lists the parts with their size" inside "opendmtq delete-data | grep -q '^recordings'"
expect "opendmtq delete-data recordings --yes deletes them, a backup first" inside "opendmtq delete-data recordings --yes | grep -q 'deleted: recordings'"
# Uninstall from the Server page, keeping the data: the program stops every part, then removes everything else.
link=$(inside "command -v opendmtq" || true)
went=$(web "$admin" -o /tmp/$NAME-uninstall.html -w '%{http_code}' --data-urlencode "csrf=$(web "$admin" "$A/server" | token)" \
  -d keep=yes -d confirm=uninstall "$A/server/uninstall")
expect "Uninstall on the Server page is asked for ($went) (DEP-48)" test "$went" = 200
expect "and its page follows the stop" grep -q 'id="stop-wait"' /tmp/$NAME-uninstall.html
# The uninstall goes on after the server has stopped, file by file: the folder is read once it holds only what stays
# (a minute at most), and what is still there is said if it never does.
left=
for _ in $(seq 60); do
  left=$(inside "ls -A OpenDMTQ | tr '\n' ' '")
  [ "$left" = ".env data " ] && break
  sleep 1
done
expect "nothing answers afterwards" is 000 "http://127.0.0.1:$PORT/opendmtq/health.php"
expect "the folder keeps only the data and .env ($left)" test "$left" = ".env data "
expect "the command on the PATH is gone (${link:-none})" inside "test -n '$link' && test ! -e '$link'"
# Installed again over the data: the same server, which the command line then removes whole.
if timeout 600 docker exec -u player -w /home/player "$NAME" bash -lc \
    "cat /tmp/host/get.sh | OPENDMTQ_TARBALL=file:///tmp/release.tar.gz OPENDMTQ_DIR=\$HOME/OpenDMTQ OPENDMTQ_NO_SETUP=1 sh" \
    > /tmp/$NAME-again.log 2>&1 && inside "opendmtq start" >/dev/null 2>&1; then
  pass "installed again over the data kept, the server starts"
else
  tail -n 20 /tmp/$NAME-again.log
  fail "installed again over the data kept, the server starts"
fi
expect "with its players' accounts still there" inside "python3 -c \"import sqlite3, sys; sys.exit(0 if sqlite3.connect('OpenDMTQ/data/state/dmtq.db3').execute('SELECT COUNT(*) FROM SiteUser').fetchone()[0] else 1)\""
expect "opendmtq uninstall --yes removes it whole" inside "opendmtq uninstall --yes > /tmp/uninstall.log 2>&1; test ! -e OpenDMTQ"
inside "tail -n 5 /tmp/uninstall.log" || true
rm -f "$admin"

echo "$([ $failures = 0 ] && echo PASS || echo FAIL) the host install on $DISTRO: $failures failure(s)"
exit $((failures > 0))
