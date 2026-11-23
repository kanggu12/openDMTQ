#!/usr/bin/env bash
# The update of a Windows bundle of an earlier release to this tree's, under Wine, as its owner does it: the release's
# OpenDMTQ.exe started once (its first start writes .env: this PC's address on port 80, the password, and in 0.10.0 the
# admin pages' own port, ADMIN_PORT=8791), its window closed, this tree's bundle unpacked over the folder (the guide's four
# lines of the newer release: .env and data stay), and OpenDMTQ.exe started again. Afterwards the server has left port 80 for the port
# its admin pages had (8791): the players' site, the admin pages and the API answer there and nothing on port 80, .env
# names the new address and no longer the admin pages' own port, the window says the move once and names one address,
# status says it once, the site's download page tells players to install the app for the new address, the app builder
# works for it, and the owner's ID and password open both doors (DEP-47, DEP-72).
#
# Usage: tests/windows/update.sh      (FROM=v0.10.0, the release whose bundle is fetched into CACHE, default
#                                      _work/update-cache; OUT, default _work/windows, this tree's bundle, built unless
#                                      NO_BUILD=1; NEW=<a bundle's folder> updates to that one instead, so that the checks
#                                      can be seen to fail on a release that leaves the old port; NAME_PREFIX and TAG name
#                                      the container and the Wine image)
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
FROM=${FROM:-v0.10.0}
CACHE=${CACHE:-$ROOT/_work/update-cache}
OUT=${OUT:-$ROOT/_work/windows}
NAME_PREFIX=${NAME_PREFIX:-odq}
WINE_IMAGE=opendmtq-wine:${TAG:-local}
RELEASES=https://github.com/kanggu12/openDMTQ/releases/download

# ------------------------------------------------------------------------------ outside: the two bundles, then Wine

if [ -z "${IN_WINE:-}" ]; then
  # The release's bundle as people download it, checked against the checksum the release publishes beside it.
  mkdir -p "$CACHE"
  old=$CACHE/OpenDMTQ-windows-${FROM#v}.zip
  if [ ! -s "$old" ]; then
    curl -fsSL -o "$old.part" "$RELEASES/$FROM/OpenDMTQ-windows.zip"
    want=$(curl -fsSL "$RELEASES/$FROM/OpenDMTQ-windows.zip.sha256" | cut -d' ' -f1)
    [ "$(sha256sum "$old.part" | cut -d' ' -f1)" = "$want" ] || { echo "FAIL the release's bundle is not the one it names"; exit 1; }
    mv "$old.part" "$old"
  fi
  new=${NEW:-$OUT/OpenDMTQ}
  if [ -z "${NEW:-}" ] && [ -z "${NO_BUILD:-}" ]; then
    "$ROOT/host/windows/build.sh" "$OUT"
  fi
  [ -f "$new/OpenDMTQ.exe" ] || { echo "FAIL no bundle in $new (run host/windows/build.sh)"; exit 1; }
  # The same Wine as tests/windows/wine.sh (its notes say why this one).
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
  # Its own network namespace: the ports below are the container's, 80 and 8791 included, never this computer's.
  exec docker run --rm --name "$NAME_PREFIX-wine-update" -e IN_WINE=1 -e FROM="$FROM" -e WINEDEBUG=-all -e WINEPREFIX=/tmp/wine \
    -v "$old:/old.zip:ro" -v "$new:/new:ro" -v "$ROOT:/repo:ro" "$WINE_IMAGE" bash /repo/tests/windows/update.sh
fi

# ------------------------------------------------------------------------------ inside: the release, then the update

failures=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
# expect <name> <command...>: PASS when the command succeeds.
expect() {
  local name=$1
  shift
  if "$@"; then pass "$name"; else fail "$name"; fi
}
# The HTTP status of an address (000 when nothing answers).
code() { curl -s -o /dev/null -w '%{http_code}' -m 10 "$1" || true; }
is() { [ "$(code "$2")" = "$1" ]; }
# A setting from .env, as the bundle reads it (Windows line ends and all).
setting() { sed -n "s/^$1=//p" .env 2>/dev/null | tr -d '\r' | tail -n 1; }
# The bundle's own Wine changes, as tests/windows/wine.sh makes them: Wine lacks what Python's WMI module calls, and
# prefers its own C runtime, whose version PHP refuses.
wine_ready() {
  rm -f runtime/python/_wmi.pyd
}
export WINEDLLOVERRIDES="vcruntime140=n;vcruntime140_1=n"
# start <log>: OpenDMTQ.exe as a double-click starts it, its output through a pipe (Python under Wine cannot write to a
# file directly), until the port .env names answers (five minutes at most).
start() {
  (OPENDMTQ_START_WAIT=5 timeout 1200 wine OpenDMTQ.exe 2>&1 | cat > "$1" &)
  for _ in $(seq 1 150); do
    port=$(setting LISTEN_PORT)
    if [ -n "$port" ]; then
      case "$(code "http://127.0.0.1:$port/opendmtq/health.php")" in 200 | 503) return 0 ;; esac
    fi
    sleep 2
  done
  tail -n 20 "$1"
  return 1
}

# 1. The release's bundle, in a folder with a space in its name as under a user's own, started once as a double-click.
mkdir -p /tmp/unpacked
python3 -m zipfile -e /old.zip /tmp/unpacked
mv /tmp/unpacked/OpenDMTQ "/tmp/Open DMTQ"
cd "/tmp/Open DMTQ"
wine_ready
wine cmd /c ver >/dev/null 2>&1 || true
expect "the release's first start writes .env and serves" start /tmp/old.log
port=$(setting LISTEN_PORT)
host=$(setting PUBLIC_HOST)
password=$(setting ADMIN_PASSWORD)
old_admin=$(setting ADMIN_PORT)
echo "INFO the release's .env: PUBLIC_HOST=$host LISTEN_PORT=$port ADMIN_PORT=${old_admin:-none} (the password not shown)"
expect "the release put its admin pages on a port of their own (ADMIN_PORT=${old_admin:-none})" test -n "$old_admin"
expect "where they answered, as they did" is 200 "http://127.0.0.1:$old_admin/opendmtq/admin/login"
# Its window closed, as the guide's update begins: everything it started ends with it.
wineserver -k 2>/dev/null || true
sleep 3

expect "the release served port 80 (LISTEN_PORT=$port, PUBLIC_HOST=$host)" sh -c "test '$port' = 80 && test '${host#*:}' = '$host'"

# 2. This tree's bundle over it, as the guide's four lines unpack it: its files over the folder's, .env and data kept.
cp -r /new/. "/tmp/Open DMTQ/"
wine_ready
expect "after the update OpenDMTQ.exe starts the server again" start /tmp/new.log
# The port it moved to, the admin pages' own before (8791), and the address with it.
moved=$(setting LISTEN_PORT)
new_host=$host:$old_admin
expect "it left port 80 for the port its admin pages had ($moved)" sh -c "test '$moved' = '$old_admin' && test '$(setting PUBLIC_HOST)' = '$new_host'"
expect "the players' site answers there" sh -c "case \$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:$moved/opendmtq/health.php) in 200 | 503) exit 0 ;; esac; exit 1"
for _ in $(seq 1 30); do
  is 200 "http://127.0.0.1:$moved/opendmtq/admin/login" && break
  sleep 2
done
expect "the admin pages answer on that same port" is 200 "http://127.0.0.1:$moved/opendmtq/admin/login"
expect "and the API" is 401 "http://127.0.0.1:$moved/opendmtq/api/v1/status"
expect "nothing answers on port 80, where the release served" is 000 "http://127.0.0.1:80/opendmtq/health.php"
expect ".env no longer names the admin pages' own port, and keeps the rest" sh -c "! grep -q '^ADMIN_PORT=' .env && test '$(setting ADMIN_PASSWORD)' = '$password'"
inner=$(tr -d '\r\n' < .host/run/admin.port 2>/dev/null || true)
expect "the admin service's own port is not the server's (${inner:-none})" sh -c "test -n '$inner' && test '$inner' != '$moved'"
# The window: the move said once, and one address, the admin pages under the site's.
grep -E "moved|/opendmtq/admin/" /tmp/new.log | sed 's/^/INFO the window: /' | head -n 4 || true
expect "the window says the move from port 80 once" sh -c "test \$(grep -c 'The server moved from port 80 to $moved: http://$new_host/' /tmp/new.log) = 1"
expect "the window names the admin pages at the server's one address" grep -q "http://$new_host/opendmtq/admin/" /tmp/new.log
expect "and never the address on port 80" sh -c "! grep -Eq 'http://$host/' /tmp/new.log"
# status once, then no more.
wine OpenDMTQ.exe status 2>&1 | cat > /tmp/status1.log || true
wine OpenDMTQ.exe status 2>&1 | cat > /tmp/status2.log || true
expect "status says the move once" sh -c "grep -q 'moved from port 80 to $moved' /tmp/status1.log && ! grep -q 'moved from port' /tmp/status2.log"
# The app builder worked for the new address (without a game client here it waits for one: its status names the address).
expect "the app builder works for the new address" grep -q "\"host\": \"$new_host\"" data/apk/out/build.json
# The owner's ID and password from .env, on both doors, each in a browser of its own.
jar=$(mktemp)
curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null "http://127.0.0.1:$moved/opendmtq/admin/login"
signed=$(curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null -w '%{http_code}' --data-urlencode name=admin \
  --data-urlencode "password=$password" "http://127.0.0.1:$moved/opendmtq/admin/login" || true)
expect "the owner signs in to the admin pages there ($signed)" test "$signed" = 302
# The Server page says the move once.
page=$(curl -s -m 30 -b "$jar" "http://127.0.0.1:$moved/opendmtq/admin/server" || true)
again=$(curl -s -m 30 -b "$jar" "http://127.0.0.1:$moved/opendmtq/admin/server" || true)
first=$(printf '%s' "$page" | grep -c 'id="moved-80"' || true)
second=$(printf '%s' "$again" | grep -c 'id="moved-80"' || true)
expect "the Server page says the move once ($first, then $second)" test "$first$second" = 10
jar=$(mktemp)
curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null "http://127.0.0.1:$moved/opendmtq/login.php"
signed=$(curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null -w '%{http_code}' --data-urlencode user=admin \
  --data-urlencode "password=$password" -d next=/opendmtq/ "http://127.0.0.1:$moved/opendmtq/login.php" || true)
expect "and to the players' site with the same ID and password ($signed)" test "$signed" = 303
# The download page tells players where the server is now and that phones need the app for that address.
expect "the download page says the move" sh -c "curl -s -m 30 -b '$jar' http://127.0.0.1:$moved/opendmtq/download.php | grep -q 'it is at $new_host now, $host before'"
wineserver -k 2>/dev/null || true

echo "$([ $failures = 0 ] && echo PASS || echo FAIL) the update of a Windows bundle from $FROM under Wine: $failures failure(s)"
exit $((failures > 0))
