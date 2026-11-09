#!/usr/bin/env bash
# Failover drill for the Helm deployment on the local kind cluster (deploy/kind).
#
#   1. Write a player through the router and wait for it to replicate.
#   2. Kill the api pod: the replacement must restore the player from the object store.
#   3. Stop the worker node running the api: assets must keep serving, the api must come back
#      on the other worker with the player intact.
#
# Prints recovery times and how many probe requests failed while each failure was in progress.
# Usage: tests/ha/failover.sh   (needs the kind-opendmtq context and a deployed release)
set -euo pipefail

CTX=kind-opendmtq
NS=opendmtq
URL=http://127.0.0.1:18080
KC=(kubectl --context "$CTX" -n "$NS")
MARK="ha$(date +%s)"
# Give up on a recovery after this many seconds: the drill then fails instead of waiting forever.
LIMIT=180
PROBE_LOG=$(mktemp)
STOPPED_NODE=""
# On any exit: stop the probe, and never leave a node stopped.
cleanup() {
  if [[ -n "${PROBE_PID:-}" ]]; then kill "$PROBE_PID" 2>/dev/null || true; fi
  if [[ -n "$STOPPED_NODE" ]]; then docker start "$STOPPED_NODE" >/dev/null 2>&1 || true; fi
  rm -f "$PROBE_LOG"
}
trap cleanup EXIT

# One JSON-RPC call through the router; prints the reply body.
rpc() { curl -s -m 5 -X POST "$URL/DMQ/rpc" -H 'Content-Type: application/json' -d "$1"; }
# Value of a JSON path from stdin, e.g. jget '[0]["result"]["guid"]'.
jget() { python3 -I -c "import json,sys; print(json.load(sys.stdin)$1)"; }
# True once the game server (the api) knows the marker player by name. Through the game's own request: the site's pages
# are behind a sign-in.
has_marker() { rpc "[{\"id\":3,\"method\":\"user.getUsersByPuid\",\"params\":[[\"$GUID\"],[\"display_name\"]]}]" | grep -q "$MARK"; }
# Seconds since the epoch, with fractions.
now() { date +%s.%N; }
api_pod() { "${KC[@]}" get pod -l app.kubernetes.io/component=api -o jsonpath='{.items[0].metadata.name}'; }
# The owner's broadcast settings (LiveSetting in the game database, docs/live.md): written in the api pod before the
# failures, as the Broadcasts page writes them, and read in each replacement, which has the database back from the
# object store. A setting that came back as the first look's default would mean it was lost.
SQL_PHP='$d = new SQLite3("/data/dmtq.db3"); '
set_settings() {
  "${KC[@]}" exec "$1" -c server -- php -r "$SQL_PHP"'$d->exec("INSERT OR REPLACE INTO LiveSetting (name, value) VALUES (\x27on\x27, \x271\x27), (\x27quality\x27, \x27sharp\x27)");' >/dev/null
}
has_settings() {
  [[ "$("${KC[@]}" exec "$1" -c server -- php -r "$SQL_PHP"'echo $d->querySingle("SELECT group_concat(name || \x27=\x27 || value, \x27,\x27) FROM (SELECT * FROM LiveSetting ORDER BY name)");' 2>/dev/null)" == *"on=1"*"quality=sharp"* ]]
}

# Background probe: one asset download and one game RPC every 0.5 s, logging HTTP codes.
probe() {
  while :; do
    a=$(curl -s -o /dev/null -m 2 -w '%{http_code}' "$URL/DMQ/Patterns/1" || true)
    r=$(curl -s -o /dev/null -m 2 -w '%{http_code}' -X POST "$URL/DMQ/rpc" -H 'Content-Type: application/json' \
        -d '[{"id":0,"method":"service.getInfo","params":["1.3.5","ANDROID"]}]' || true)
    echo "$a $r" >> "$PROBE_LOG"
    sleep 0.5
  done
}
# "failed/total" for column $1 (1 = assets, 2 = api) of the probe log.
tally() { awk -v c="$1" '{t++; if ($c != "200") f++} END {printf "%d/%d", f, t}' "$PROBE_LOG"; }
# Name of an api pod other than $1 whose server container is ready, or nothing.
new_ready_pod() {
  "${KC[@]}" get pod -l app.kubernetes.io/component=api -o json | python3 -I -c '
import json, sys
for p in json.load(sys.stdin)["items"]:
    ready = {c["name"]: c["ready"] for c in p["status"].get("containerStatuses", [])}
    if p["metadata"]["name"] != sys.argv[1] and ready.get("server"):
        print(p["metadata"]["name"], p["spec"]["nodeName"]); break' "$1"
}
# Wait until a different api pod than $2 serves the marker; prints "<seconds> <pod> <node>".
# The old pod can answer for a moment after it is deleted; that must not count. A replacement
# that comes up without the marker means the restore lost data: fail.
wait_recovered() {
  local start=$1 old=$2 found elapsed
  while :; do
    elapsed=$(python3 -I -c "print(f'{$(now) - $start:.1f}')")
    found=$(new_ready_pod "$old")
    if [[ -n "$found" ]]; then
      for _ in $(seq 1 20); do has_marker && { echo "$elapsed $found"; return; }; sleep 0.5; done
      echo "FAIL: replacement pod $found is up but player $MARK is gone (data lost)" >&2; exit 1
    fi
    if python3 -I -c "import sys; sys.exit(not $elapsed > $LIMIT)"; then
      echo "FAIL: no replacement api pod within ${LIMIT}s" >&2; exit 1
    fi
    sleep 0.5
  done
}

echo "== write a player through the router"
TOKEN=$(curl -s -m 5 -X POST "$URL/api/accounts/v3/global/login_dmq" -d "udid=$MARK" | jget '["value"]["access_token"]')
GUID=$(rpc "[{\"id\":1,\"method\":\"user.loginV2\",\"params\":[\"$TOKEN\",\" \",\"\",\"1.3.5\",\"ANDROID\",\"KR\"]}]" | jget '[0]["result"]["guid"]')
rpc "[{\"id\":2,\"method\":\"user.setNickname\",\"params\":[$GUID,\"$MARK\"]}]" > /dev/null
has_marker || { echo "player $MARK not visible after writing it"; exit 1; }
set_settings "$(api_pod)"
has_settings "$(api_pod)" || { echo "the broadcast settings not readable after writing them"; exit 1; }
echo "   player $MARK (guid $GUID) and the broadcast settings (on, sharp) written; waiting 3 s for replication"
sleep 3

echo "== 1. kill the api pod"
POD=$(api_pod)
: > "$PROBE_LOG"; probe & PROBE_PID=$!
T0=$(now)
"${KC[@]}" delete pod "$POD" --grace-period=0 --force >/dev/null 2>&1
OUT=$(wait_recovered "$T0" "$POD") || exit 1
read -r RTO1 _ NODE1 <<< "$OUT"
kill "$PROBE_PID"; PROBE_PID=
echo "   api back with the player after ${RTO1}s on $NODE1"
has_settings "$(api_pod)" || { echo "FAIL: the broadcast settings did not come back with the replacement pod" >&2; exit 1; }
echo "   the broadcast settings came back with it"
echo "   failed probes during the outage: assets $(tally 1), api $(tally 2)"
P1A=$(tally 1); P1R=$(tally 2)

echo "== 2. stop the worker node running the api"
POD=$(api_pod)
NODE=$("${KC[@]}" get pod "$POD" -o jsonpath='{.spec.nodeName}')
: > "$PROBE_LOG"; probe & PROBE_PID=$!
T0=$(now)
STOPPED_NODE=$NODE
docker stop "$NODE" >/dev/null
OUT=$(wait_recovered "$T0" "$POD") || exit 1
read -r RTO2 NEWPOD NEW <<< "$OUT"
kill "$PROBE_PID"; PROBE_PID=
echo "   node $NODE stopped; api back with the player after ${RTO2}s ($NEWPOD on $NEW)"
has_settings "$NEWPOD" || { echo "FAIL: the broadcast settings did not come back on the other node" >&2; exit 1; }
echo "   the broadcast settings came back with it"
echo "   failed probes during the outage: assets $(tally 1), api $(tally 2)"
P2A=$(tally 1); P2R=$(tally 2)

echo "== bring $NODE back"
docker start "$NODE" >/dev/null
STOPPED_NODE=""
kubectl --context "$CTX" wait --for=condition=Ready "node/$NODE" --timeout=180s >/dev/null

cat <<SUMMARY

result                       recovery   failed probes (assets / api)
api pod killed               ${RTO1}s      ${P1A} / ${P1R}
api node stopped             ${RTO2}s      ${P2A} / ${P2R}
player $MARK and the broadcast settings present after both recoveries (checked in the replacement pods)
SUMMARY
