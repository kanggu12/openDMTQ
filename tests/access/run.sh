#!/usr/bin/env bash
# Who reaches the admin pages and their API on a server's one port, on a throwaway server: the server image from this
# working tree with a stand-in for the admin service, which answers with what the server passed on. The visits come as
# compose's edge proxy hands them to the server, each with its PROXY protocol header saying where it came from: the server
# PC's own, from the stack network's gateway (Docker Engine passes a visit to localhost that way); the same address with a
# header that a proxy in front adds to say whom it passes on (X-Forwarded-For, Forwarded, X-Real-IP, X-Forwarded-Host,
# X-Forwarded-Proto, Via), as a reverse proxy on the server PC sends them; and an address from elsewhere. Then the same
# server where every visit comes from that address (ADMIN_LOCAL=none: Docker Desktop, rootless Docker's port driver), and
# with the admin pages on the public port (--admin-public). Last, a host install's settings for an internet address
# (host/opendmtq_host/apache.py) in the same Apache: loopback alone, and never with such a header.
# Needs Docker and Python 3; nothing of the game's own.
#
# Usage: tests/access/run.sh      (NAME_PREFIX, TAG and SUBNET keep a run's containers, image and network apart;
#                                  NO_BUILD=1 uses the image already tagged opendmtq-server:TAG)
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
# A run's own names: its image, its containers and its network.
TAG=${TAG:-access}
NAME=${NAME_PREFIX:-odq}-access
NET=$NAME-net
WORK=$(mktemp -d)
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }

cleanup() {
  docker rm -f "$NAME-site" "$NAME-echo" "$NAME-host" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

if [ -z "${NO_BUILD:-}" ]; then
  docker build -q -t "opendmtq-server:$TAG" "$ROOT/server" >/dev/null
fi
# A network of the run's own (a given subnet keeps it off another's); its gateway is where Docker Engine passes a visit
# to localhost from.
docker network create ${SUBNET:+--subnet "$SUBNET"} "$NET" >/dev/null
GATEWAY=$(docker network inspect -f '{{(index .IPAM.Config 0).Gateway}}' "$NET")
# An address from elsewhere (TEST-NET-3, never a real visitor).
OUTSIDE=203.0.113.9

# The stand-in for the admin service: every request answered 200 with the headers it came with, as JSON.
mkdir -p "$WORK/echo"
cat > "$WORK/echo/echo.php" <<'PHP'
<?php
header('Content-Type: application/json');
echo json_encode(['path' => $_SERVER['REQUEST_URI'], 'real_ip' => $_SERVER['HTTP_X_REAL_IP'] ?? null,
                  'server_pc' => $_SERVER['HTTP_X_SERVER_PC'] ?? null]);
PHP
chmod -R a+rX "$WORK"
docker run -d --name "$NAME-echo" --network "$NET" -u 33:33 -v "$WORK/echo:/echo:ro" --entrypoint php \
  "opendmtq-server:$TAG" -S 0.0.0.0:8000 /echo/echo.php >/dev/null

# The server as compose starts it, exposed to the internet (an internet address), with these settings.
site() {
  docker rm -f "$NAME-site" >/dev/null 2>&1 || true
  docker run -d --name "$NAME-site" --network "$NET" -u 33:33 --read-only --tmpfs /var/opendmtq:mode=1777 \
    --tmpfs /tmp:mode=1777 --tmpfs /data:mode=1777 -e PUBLIC_HOST=game.example.com:8790 -e TZ=UTC \
    -e ADMIN_URL="http://$NAME-echo:8000" "$@" "opendmtq-server:$TAG" >/dev/null
  for _ in $(seq 1 60); do
    # Both doors listening (its health check says 503 without game files, which this test needs none of).
    docker exec "$NAME-site" php -r 'exit(@fsockopen("127.0.0.1", 8081) && @fsockopen("127.0.0.1", 8443) ? 0 : 1);' \
      2>/dev/null && return 0
    sleep 1
  done
  echo "the server did not come up" >&2
  docker logs --tail 30 "$NAME-site" >&2
  exit 1
}

# visit <door> <from> <path> [header...]: the status the server answers on its door (8081 plain, 8443 HTTPS as the edge
# decrypted it) to a visit the edge passes on from that address, with those headers; then what the admin service saw.
visit() {
  local door=$1 from=$2 path=$3
  shift 3
  local extra=""
  for header in "$@"; do
    extra="$extra$header\r\n"
  done
  # shellcheck disable=SC2016  # PHP code: its $variables are PHP's.
  docker exec -e DOOR="$door" -e FROM="$from" -e WANT="$path" -e EXTRA="$extra" "$NAME-site" php -r '
    $s = fsockopen("127.0.0.1", (int) getenv("DOOR"));
    $extra = str_replace("\\r\\n", "\r\n", getenv("EXTRA"));
    fwrite($s, "PROXY TCP4 " . getenv("FROM") . " 127.0.0.1 40000 " . getenv("DOOR") . "\r\n"
      . "GET " . getenv("WANT") . " HTTP/1.0\r\nHost: game.example.com:8790\r\nUser-Agent: curl\r\n" . $extra . "\r\n");
    $all = stream_get_contents($s);
    preg_match("#^HTTP/1\.[01] (\d+)#", $all, $m);
    echo ($m[1] ?? "000"), " ", substr($all, strpos($all, "\r\n\r\n") + 4);'
}

# expect <status> <door> <from> <path> [header...]: PASS when the server answers so.
expect() {
  local want=$1 door=$2 from=$3 path=$4
  shift 4
  local got
  got=$(visit "$door" "$from" "$path" "$@")
  local what="door $door, from $from, $path${*:+ with $*}"
  if [ "${got%% *}" = "$want" ]; then pass "$what: $want"; else fail "$what: ${got%% *}, expected $want"; fi
}

# Each header a proxy in front adds to say whom it passes on.
FORWARDED=("X-Forwarded-For: 198.51.100.7" "Forwarded: for=198.51.100.7" "X-Real-IP: 198.51.100.7"
           "X-Forwarded-Host: game.example.com:8790" "X-Forwarded-Proto: https" "Via: 1.1 proxy")

echo "-- exposed, the admin pages kept to the server PC, Docker Engine (ADMIN_LOCAL=gateway)"
site -e ADMIN_ON_PUBLIC_PORT=no -e ADMIN_LOCAL=gateway
for door in 8081 8443; do
  for path in /opendmtq/admin/login /opendmtq/api/v1/status; do
    # The server PC's own visit (a browser on localhost, the command line's wait at up): passed on.
    expect 200 "$door" "$GATEWAY" "$path"
    # The same address with a proxy's header: a visit from elsewhere that a proxy on the server PC passes on.
    for header in "${FORWARDED[@]}"; do
      expect 403 "$door" "$GATEWAY" "$path" "$header"
    done
    # From elsewhere.
    expect 403 "$door" "$OUTSIDE" "$path"
  done
done
# The admin service is told the visitor's address, and nothing that marks a visit as the server PC's, whatever the
# visitor sent.
seen=$(visit 8081 "$GATEWAY" /opendmtq/admin/login "X-Server-PC: yes")
if [ "$seen" = "200 {\"path\":\"\\/opendmtq\\/admin\\/login\",\"real_ip\":\"$GATEWAY\",\"server_pc\":null}" ]; then
  pass "the admin service sees the visitor's address and no mark of the server PC"
else
  fail "what the admin service sees: $seen"
fi

echo "-- exposed at a router's own port (PUBLIC_HOST=game.example.com:8443, the server's own LISTEN_PORT=8790): the refusals name the server's own"
site -e ADMIN_ON_PUBLIC_PORT=no -e ADMIN_LOCAL=gateway -e PUBLIC_HOST=game.example.com:8443 -e LISTEN_PORT=8790
for door in 8081 8443; do
  # Where the admin pages open on the server PC: its own port, where a visit to localhost arrives (main named the router's
  # 8443, where nothing answers on the server PC).
  said=$(visit "$door" "$OUTSIDE" /opendmtq/admin/login)
  if [ "$said" = "403 The admin pages open on the server PC: http://localhost:8790/opendmtq/admin/" ]; then
    pass "door $door, from elsewhere, the admin pages' refusal names port 8790"
  else
    fail "door $door, from elsewhere, the admin pages' refusal: $said"
  fi
done

echo "-- exposed, every visit from the gateway's address (ADMIN_LOCAL=none: Docker Desktop, rootless Docker)"
site -e ADMIN_ON_PUBLIC_PORT=no -e ADMIN_LOCAL=none
for door in 8081 8443; do
  for path in /opendmtq/admin/login /opendmtq/api/v1/status; do
    got=$(visit "$door" "$GATEWAY" "$path")
    # Refused on the plain door, not passed on at all on the HTTPS one.
    case "${got%% *}" in
      403|404) pass "door $door, from $GATEWAY, $path: ${got%% *}" ;;
      *) fail "door $door, from $GATEWAY, $path: ${got%% *}, expected 403 or 404" ;;
    esac
  done
done

echo "-- exposed with --admin-public: over HTTPS from anywhere"
site -e ADMIN_ON_PUBLIC_PORT=yes -e ADMIN_LOCAL=gateway
expect 200 8443 "$OUTSIDE" /opendmtq/admin/login
expect 200 8443 "$OUTSIDE" /opendmtq/api/v1/status
expect 200 8443 "$GATEWAY" /opendmtq/admin/login "X-Forwarded-For: 198.51.100.7"

echo "-- a host install on an internet address: its admin settings (apache.py) in the same Apache"
mkdir -p "$WORK/host"
# The admin service's own port, as the host install's start chooses it: here the stand-in, inside the same container.
OPENDMTQ_ADMIN_SERVICE_PORT=18000 PYTHONPATH="$ROOT/host:$ROOT/cli" python3 -I -c '
import sys
sys.path[:0] = sys.argv[2:]
from opendmtq_host import apache
open(sys.argv[1], "w").write(apache.admin_conf({"PUBLIC_HOST": "game.example.com:8790", "LISTEN_PORT": "8790"}))
' "$WORK/host/admin.conf" "$ROOT/host" "$ROOT/cli"
# One door with those settings, as the host install's Apache has it (proxy and headers are in the image).
printf 'Listen 8090\n<VirtualHost *:8090>\n    Include /host/admin.conf\n</VirtualHost>\n' > "$WORK/host/door.conf"
chmod -R a+rX "$WORK"
docker run -d --name "$NAME-host" --network "$NET" -u 33:33 --tmpfs /var/opendmtq:mode=1777 --tmpfs /tmp:mode=1777 \
  --tmpfs /data:mode=1777 -e PUBLIC_HOST=game.example.com:8790 -v "$WORK/host:/host:ro" -v "$WORK/echo:/echo:ro" \
  -v "$WORK/host/door.conf:/etc/apache2/conf-enabled/zz-host-door.conf:ro" "opendmtq-server:$TAG" >/dev/null
docker exec -d -u 33:33 "$NAME-host" php -S 127.0.0.1:18000 /echo/echo.php
# host_visit <loopback|elsewhere> <path> [header...]: the status of a visit to that door from inside its own container
# (loopback), or from another container on the same network (elsewhere), with those headers.
host_visit() {
  local where=$1 path=$2
  shift 2
  local from=$NAME-host target=127.0.0.1
  if [ "$where" = elsewhere ]; then
    from=$NAME-echo
    target=$NAME-host
  fi
  # shellcheck disable=SC2016  # PHP code: its $variables are PHP's.
  docker exec -e TARGET="$target" -e WANT="$path" -e HEADERS="$(printf '%s\n' "$@")" "$from" php -r '
    $headers = array_values(array_filter(explode("\n", getenv("HEADERS"))));
    $c = stream_context_create(["http" => ["header" => $headers, "ignore_errors" => true, "timeout" => 10]]);
    @file_get_contents("http://" . getenv("TARGET") . ":8090" . getenv("WANT"), false, $c);
    preg_match("#^HTTP/1\.[01] (\d+)#", $http_response_header[0] ?? "", $m);
    echo $m[1] ?? "000";'
}
for _ in $(seq 1 60); do
  [ "$(host_visit loopback /opendmtq/admin/login)" != 000 ] && break
  sleep 1
done
for path in /opendmtq/admin/login /opendmtq/api/v1/status; do
  got=$(host_visit loopback "$path")
  if [ "$got" = 200 ]; then pass "host install, loopback, $path: 200"; else fail "host install, loopback, $path: $got"; fi
  for header in "${FORWARDED[@]}"; do
    got=$(host_visit loopback "$path" "$header")
    if [ "$got" = 403 ]; then pass "host install, loopback with $header, $path: 403"; else
      fail "host install, loopback with $header, $path: $got, expected 403"; fi
  done
  got=$(host_visit elsewhere "$path")
  if [ "$got" = 403 ]; then pass "host install, from elsewhere, $path: 403"; else
    fail "host install, from elsewhere, $path: $got, expected 403"; fi
done

echo "$failures failed"
[ "$failures" -eq 0 ]
