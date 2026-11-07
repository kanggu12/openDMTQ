#!/usr/bin/env bash
# What docs/closed-network.md says, done on a network with no way out: everything is carried in, nothing is fetched, and the
# server and the phone app come out all the same. A container on an internal network stands in for each computer, and each
# first checks that it really cannot reach the internet. The Windows bundle has the same test in tests/windows/wine.sh
# (CLOSED=1). A release's images and zip are made here from this tree, as .github/workflows/release.yml makes them.
#
# Usage: tests/closed/run.sh [docker|host|kubernetes|all]    (default all; kubernetes needs kind, helm, kubectl, and root for
#                                                            a firewall rule that closes that cluster's network, taken away after)
#        ARM32_BUNDLE=<folder>   the runtime bundle to hand out (default data/apk/arm32)
#        APK=<file>              also builds the phone app from this client, and looks into it (it never leaves this machine)
#        DISTRO=debian:12        the system of the host install's computer (default ubuntu:24.04)
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WHAT=${1:-all}
BUNDLE=${ARM32_BUNDLE:-$ROOT/data/apk/arm32}
DISTRO=${DISTRO:-ubuntu:24.04}
NET=odq-closed
DOCKER_NAME=odq-closed-docker
HOST_NAME=odq-closed-host
SERVER_IMAGE=ghcr.io/kanggu12/opendmtq-server:closed-test
TOOLS_IMAGE=ghcr.io/kanggu12/opendmtq-tools:closed-test
EDGE_IMAGE=$(sed -n 's/^ *image: \(nginxinc\/nginx-unprivileged:.*\)$/\1/p' "$ROOT/compose.yaml")
ZIP=opendmtq-arm32-runtime.zip
KIT=$(mktemp -d)
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
expect() {
  local name=$1
  shift
  if "$@"; then pass "$name"; else fail "$name"; fi
}
# The HTTP status of an address (000 when nothing answers).
code() { curl -s -o /dev/null -w '%{http_code}' -m 10 "$1"; }
is() { [ "$(code "$2")" = "$1" ]; }
# How long a computer may take over all of it: what waits for a question or a network hangs until then, not for ever.
LIMIT=1500
KIND_CLUSTER=odq-closed
# The cluster's network address while it is closed: what the cleanup has to open again.
CLOSED_SUBNET=

# kind's network has a way out, and needs its default route to work at all: rules on Docker's own chain close it instead, for
# what goes out of that network and nothing else. Two things stay open: replies to what comes in (this machine's requests,
# through the node's port), and traffic between the nodes to the pods' addresses, which passes the same chain on the bridge.
kind_network_rules() {
  local action=$1 rule
  for rule in "-m conntrack --ctstate ESTABLISHED,RELATED -j RETURN" "-d 10.244.0.0/16 -j RETURN" "! -d $CLOSED_SUBNET -j REJECT"; do
    # shellcheck disable=SC2086  # The rule's words are meant to be split.
    if [ "$action" = open ]; then iptables -D DOCKER-USER -s "$CLOSED_SUBNET" $rule || true; else iptables -A DOCKER-USER -s "$CLOSED_SUBNET" $rule; fi
  done
}

close_kind_network() {
  CLOSED_SUBNET=$(docker network inspect kind --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}' | tr ' ' '\n' | grep -m1 '\.')
  kind_network_rules close
}

open_kind_network() {
  if [ -n "$CLOSED_SUBNET" ]; then
    kind_network_rules open
    CLOSED_SUBNET=
  fi
}

cleanup() {
  open_kind_network
  if command -v kind >/dev/null; then
    kind delete cluster --name "$KIND_CLUSTER" >/dev/null 2>&1 || true
  fi
  docker rm -fv "$DOCKER_NAME" "$HOST_NAME" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  # What the servers wrote belongs to their user: removed from inside an image.
  docker run --rm -u 0 -v "$KIT:/k" --entrypoint sh "$SERVER_IMAGE" -c 'rm -rf /k/* /k/.[!.]*' >/dev/null 2>&1 || true
  docker image rm "$SERVER_IMAGE" "$TOOLS_IMAGE" >/dev/null 2>&1 || true
  rm -rf "$KIT"
}
trap cleanup EXIT

# This tree as GitHub hands out a release's source.
release_source() {
  tar -C "$ROOT" --exclude=./data --exclude=./_work --exclude=./.host --exclude=./.git --exclude=./.env \
    --transform 's,^\.,openDMTQ-1.0.0,' -czf "$1" .
}

# The runtime for newer phones, as a release hands it out.
[ -f "$BUNDLE/bundle.json" ] || { echo "FAIL no runtime bundle in $BUNDLE (arm32/bundle.sh makes one)"; exit 1; }
python3 "$ROOT/tools/opendmtq_tools/runtime.py" --pack "$BUNDLE" "$KIT/$ZIP" >/dev/null
# A home network's range, as Docker's own choice may be a 172 one: under WSL's kernel a container takes that for WSL's NAT address.
docker network rm "$NET" >/dev/null 2>&1 || true
docker network create --internal --subnet 192.168.98.0/24 "$NET" >/dev/null

# The game's files, as the owner carries them in: the pages' stand-in files, laid out like the game's client data and
# song data, with a file behind each song's address for the setup's self-check to find, and the client beside them when
# there is one.
docker build -q -t "$SERVER_IMAGE" "$ROOT/server" >/dev/null
mkdir -p "$KIT/content"
docker run --rm -u "$(id -u):$(id -g)" -v "$KIT/content:/content" -v "$ROOT/tests/ui:/ui:ro" --entrypoint php "$SERVER_IMAGE" \
  /ui/make_content.php /content >/dev/null
mkdir -p "$KIT/DMTQ/dmtq/dmqglb.mb.pmang.com" "$KIT/DMTQ/dmtq/_info"
cp -r "$KIT/content/web/." "$KIT/DMTQ/dmtq/dmqglb.mb.pmang.com/"
cp "$KIT/content/songs.json" "$KIT/DMTQ/dmtq/_info/songList.json"
python3 - "$KIT/DMTQ/dmtq" <<'PY'
import json, os, sys

root = sys.argv[1]


def stand_in(rel):
    path = os.path.join(root, "dmqglb.mb.pmang.com", rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(b"stand-in")


with open(os.path.join(root, "_info", "songList.json"), encoding="utf-8") as f:
    songs = json.load(f)
for song in songs if isinstance(songs, list) else songs["songs"]:
    number = song["song_id"]
    for rel in (f"DMQ/Songs/{number}/{number}.fpk", f"DMQ/Songs/{number}/{number}.webm", f"viewImg/eye/{song['name']}.png"):
        stand_in(rel)
stand_in("DMQ/Patterns/1")
PY
if [ -n "${APK:-}" ]; then
  cp "$APK" "$KIT/DMTQ/client.apk"
fi

# The tools image as a release publishes it: with the runtime in it, beside the code that looks for it.
release_tools_image() {
  local context=$KIT/tools-context
  rm -rf "$context"
  mkdir -p "$context"
  tar -C "$ROOT/tools" --exclude=__pycache__ --exclude=./tests -cf - . | tar -C "$context" -xf -
  cp "$KIT/$ZIP" "$context/opendmtq_tools/"
  docker build -q -t "$TOOLS_IMAGE" "$context" >/dev/null
}

# What a built app has when the runtime came with it. <list> is the app's file names, one per line.
app_has_the_runtime() {
  expect "the app was built" test -n "$1"
  expect "with the translator" grep -qx "lib/arm64-v8a/libarm32.so" <<<"$1"
  expect "Android's libraries" grep -qx "lib/arm64-v8a/libarm32s-libc.so" <<<"$1"
  expect "and their licenses" grep -qx "assets/opendmtq/android-NOTICE.html.gz" <<<"$1"
}

# ------------------------------------------------------------------------------ Docker Compose

docker_way() {
  echo "== Docker Compose, with a release's images"
  # On a computer with internet: the images as a release publishes them, saved to a file, and the source. (The guide pulls
  # them; there is no published image of this tree to pull.)
  release_tools_image
  docker pull -q "$EDGE_IMAGE" >/dev/null
  docker save "$SERVER_IMAGE" "$TOOLS_IMAGE" "$EDGE_IMAGE" | gzip -1 > "$KIT/opendmtq-images.tar.gz"
  release_source "$KIT/source.tar.gz"

  # The computer on the closed network: Docker with Compose, Python, and the game's files, nothing else.
  docker build -q -t opendmtq-closed-docker:local - >/dev/null <<'DOCKERFILE'
FROM docker:28-dind
RUN apk add --no-cache python3 bash curl iproute2 >/dev/null
DOCKERFILE
  docker rm -fv "$DOCKER_NAME" >/dev/null 2>&1 || true
  docker run -d --name "$DOCKER_NAME" --privileged --network "$NET" -e DOCKER_TLS_CERTDIR= opendmtq-closed-docker:local >/dev/null
  local in=(docker exec "$DOCKER_NAME")
  for _ in $(seq 1 60); do
    "${in[@]}" docker info >/dev/null 2>&1 && break
    sleep 2
  done
  expect "the computer has Docker running" "${in[@]}" docker info --format '{{.ServerVersion}}'
  expect "and no way out" "${in[@]}" sh -c '! curl -s -m 5 -o /dev/null https://registry-1.docker.io/v2/'
  local ip
  ip=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" "$DOCKER_NAME")

  # The guide's steps, one by one.
  docker cp "$KIT/opendmtq-images.tar.gz" "$DOCKER_NAME:/root/" >/dev/null
  docker cp "$KIT/source.tar.gz" "$DOCKER_NAME:/root/" >/dev/null
  docker cp "$KIT/DMTQ" "$DOCKER_NAME:/root/DMTQ" >/dev/null
  expect "docker load brings the images" "${in[@]}" docker load -q -i /root/opendmtq-images.tar.gz
  "${in[@]}" sh -c 'cd /root && tar -xzf source.tar.gz && rm opendmtq-images.tar.gz'
  "${in[@]}" sh -c "printf 'OPENDMTQ_SERVER_IMAGE=$SERVER_IMAGE\nOPENDMTQ_TOOLS_IMAGE=$TOOLS_IMAGE\n' > /root/openDMTQ-1.0.0/.env"
  # Without --host: finding its own address with no route out is part of what this tries.
  if timeout "$LIMIT" docker exec -w /root/openDMTQ-1.0.0 "$DOCKER_NAME" ./opendmtq setup --from /root/DMTQ --songs --no-firewall > "$KIT/docker-setup.log" 2>&1; then
    pass "./opendmtq setup, with the files carried in and nothing fetched"
  else
    tail -n 40 "$KIT/docker-setup.log"
    fail "./opendmtq setup"
  fi
  grep -n "could not\|arm32\|Fetching" "$KIT/docker-setup.log" | cut -c1-200 || true
  expect "it found its own address ($ip)" "${in[@]}" grep -qx "PUBLIC_HOST=$ip" /root/openDMTQ-1.0.0/.env
  expect "the server answers on the closed network" is 200 "http://$ip/opendmtq/health.php"
  if python3 "$ROOT/tests/game/protocol.py" "http://$ip" > "$KIT/docker-protocol.log" 2>&1; then
    pass "the game server's contract"
  else
    tail -n 20 "$KIT/docker-protocol.log"
    fail "the game server's contract"
  fi
  if [ -n "${APK:-}" ]; then
    # Python's own zip listing: this computer has no unzip.
    local app
    app=$("${in[@]}" sh -c 'ls -t /root/openDMTQ-1.0.0/data/apk/out/*.apk | head -n 1')
    app_has_the_runtime "$("${in[@]}" python3 -m zipfile -l "$app" | awk '{print $1}')"
    expect "doctor says the runtime is in" sh -c "docker exec -w /root/openDMTQ-1.0.0 $DOCKER_NAME ./opendmtq doctor 2>&1 | grep -q 'arm32 runtime'"
  fi

  # An update, as the guide says, with these images under another tag for the new release's.
  "${in[@]}" docker tag "$SERVER_IMAGE" "${SERVER_IMAGE%:*}:closed-new"
  "${in[@]}" docker tag "$TOOLS_IMAGE" "${TOOLS_IMAGE%:*}:closed-new"
  local player_before player_after
  player_before=$(curl -s -m 10 "http://$ip/opendmtq/health.php" || true)
  "${in[@]}" sh -c 'cd /root && tar -xzf source.tar.gz --strip-components=1 -C openDMTQ-1.0.0 && sed -i "s/:closed-test\$/:closed-new/" openDMTQ-1.0.0/.env'
  if timeout "$LIMIT" docker exec -w /root/openDMTQ-1.0.0 "$DOCKER_NAME" ./opendmtq up > "$KIT/docker-update.log" 2>&1; then
    pass "an update: ./opendmtq up, with nothing fetched"
  else
    tail -n 20 "$KIT/docker-update.log"
    fail "an update"
  fi
  expect "it runs the new images" sh -c "docker exec $DOCKER_NAME docker inspect -f '{{.Config.Image}}' opendmtq-server | grep -q ':closed-new\$'"
  expect "and keeps its address" "${in[@]}" grep -qx "PUBLIC_HOST=$ip" /root/openDMTQ-1.0.0/.env
  player_after=$(curl -s -m 10 "http://$ip/opendmtq/health.php" || true)
  expect "and answers as before" test -n "$player_after"
  echo "    before: $(cut -c1-120 <<<"$player_before")"
  echo "    after:  $(cut -c1-120 <<<"$player_after")"
  docker rm -fv "$DOCKER_NAME" >/dev/null 2>&1 || true
}

# ------------------------------------------------------------------------------ a host install

host_way() {
  echo "== A host install on $DISTRO"
  # On a computer with internet: the system's packages, on a clean copy of the same system, and the three pinned programs;
  # the source; the runtime. All as host/install.sh names them, so this cannot drift from it.
  local packages
  packages=$(sed -n '/^APT_PACKAGES=(/,/^)/p' "$ROOT/host/install.sh" | sed -e '1d' -e '$d' | tr -s ' \n' ' ')
  mkdir -p "$KIT/kit/debs"
  docker run --rm -v "$KIT/kit/debs:/debs" "$DISTRO" sh -c "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    --download-only --no-install-recommends -o Dir::Cache::archives=/debs $packages >/dev/null && rm -rf /debs/partial /debs/lock && chmod -R a+rX /debs"
  expect "the system's packages come down ($(find "$KIT/kit/debs" -name '*.deb' | wc -l) files)" sh -c "ls '$KIT/kit/debs'/*.deb >/dev/null"
  # shellcheck disable=SC1090  # The addresses, from the script that checks them.
  . <(grep -E '^(APKTOOL_URL|SIGNER_URL|SEVENZIP_LINUX_X64_URL)=' "$ROOT/host/install.sh")
  curl -fsSL -o "$KIT/kit/apktool.jar" "$APKTOOL_URL"
  curl -fsSL -o "$KIT/kit/uber-apk-signer.jar" "$SIGNER_URL"
  curl -fsSL -o "$KIT/kit/7zip.tar.xz" "$SEVENZIP_LINUX_X64_URL"
  release_source "$KIT/kit/opendmtq-source.tar.gz"
  cp "$KIT/$ZIP" "$KIT/kit/"
  cp -r "$KIT/DMTQ" "$KIT/kit/DMTQ"

  # The computer on the closed network: the system and a user who may use sudo; the same image as the host install's test.
  local image
  image=opendmtqtest:$(echo "$DISTRO" | tr ':/' '--')
  docker build -q -t "$image" - >/dev/null <<EOF
FROM $DISTRO
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq sudo ca-certificates curl >/dev/null \
    && useradd -m -s /bin/bash player && echo 'player ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/player
EOF
  docker rm -fv "$HOST_NAME" >/dev/null 2>&1 || true
  docker run -d --name "$HOST_NAME" --network "$NET" "$image" sleep infinity >/dev/null
  inside() { timeout "$LIMIT" docker exec -u player -w /home/player "$HOST_NAME" bash -lc "$1"; }
  expect "the computer has no way out" inside '! curl -s -m 5 -o /dev/null https://deb.debian.org'
  local ip
  ip=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" "$HOST_NAME")
  tar -C "$KIT" -cf - kit | docker exec -i -u player -w /home/player "$HOST_NAME" tar -xf -

  # The guide's steps, one by one.
  if inside 'tar -xzf kit/opendmtq-source.tar.gz && cd openDMTQ-1.0.0 && host/install.sh --from ../kit' > "$KIT/host-install.log" 2>&1; then
    pass "host/install.sh --from, with the packages and programs carried in"
  else
    tail -n 30 "$KIT/host-install.log"
    fail "host/install.sh --from"
    return
  fi
  # Port 8711: an unprivileged user cannot bind 80. The address is left for it to find, with no route out.
  inside 'cd openDMTQ-1.0.0 && printf "LISTEN_PORT=8711\n" > .env'
  if inside 'cd openDMTQ-1.0.0 && ./opendmtq setup --from ~/kit/DMTQ --songs' > "$KIT/host-setup.log" 2>&1; then
    pass "./opendmtq setup"
  else
    tail -n 30 "$KIT/host-setup.log"
    fail "./opendmtq setup"
  fi
  grep -n "could not\|arm32\|Fetching" "$KIT/host-setup.log" | cut -c1-200 || true
  expect "it found its own address ($ip)" inside "grep -qx 'PUBLIC_HOST=$ip:8711' openDMTQ-1.0.0/.env"
  expect "the server answers on the closed network" is 200 "http://$ip:8711/opendmtq/health.php"
  if python3 "$ROOT/tests/game/protocol.py" "http://$ip:8711" > "$KIT/host-protocol.log" 2>&1; then
    pass "the game server's contract"
  else
    tail -n 20 "$KIT/host-protocol.log"
    fail "the game server's contract"
  fi
  if [ -n "${APK:-}" ]; then
    inside 'cd openDMTQ-1.0.0 && ./opendmtq apk' > "$KIT/host-apk.log" 2>&1 || { tail -n 20 "$KIT/host-apk.log"; fail "./opendmtq apk"; }
    local app
    app=$(inside 'ls -t openDMTQ-1.0.0/data/apk/out/*.apk | head -n 1')
    app_has_the_runtime "$(inside "python3 -m zipfile -l '$app'" | awk '{print $1}')"
    expect "the zip carried in was taken" inside '! test -e openDMTQ-1.0.0/data/apk/opendmtq-arm32-runtime.zip'
  fi

  # An update, as the guide says, over the first install's folder.
  inside 'openDMTQ-1.0.0/opendmtq stop' >/dev/null 2>&1 || true
  if inside 'tar -xzf kit/opendmtq-source.tar.gz --strip-components=1 -C openDMTQ-1.0.0 && cd openDMTQ-1.0.0 && host/install.sh --from ../kit && ./opendmtq start' > "$KIT/host-update.log" 2>&1; then
    pass "an update: over the first install's folder, with nothing fetched"
  else
    tail -n 20 "$KIT/host-update.log"
    fail "an update"
  fi
  expect "it keeps its address and settings" inside "grep -qx 'PUBLIC_HOST=$ip:8711' openDMTQ-1.0.0/.env"
  expect "and answers again" is 200 "http://$ip:8711/opendmtq/health.php"
  docker rm -fv "$HOST_NAME" >/dev/null 2>&1 || true
}

# ------------------------------------------------------------------------------ Kubernetes

kube_way() {
  echo "== Kubernetes, with a release's images and the guide's values"
  # The images in the guide's registry, by the names its values give them. kind copies them onto the nodes, as
  # `ctr images import` does on a cluster without a registry.
  release_tools_image
  local registry=registry.example.internal names=() image
  for image in "$SERVER_IMAGE" "$TOOLS_IMAGE" "$EDGE_IMAGE" litestream/litestream:0.3.13 chrislusf/seaweedfs:3.97; do
    docker image inspect "$image" >/dev/null 2>&1 || docker pull -q "$image" >/dev/null
    docker tag "$image" "$registry/${image##*/}"
    names+=("$registry/${image##*/}")
  done
  # The cluster: the repository's local one, over a data folder of stand-in files and not this checkout's.
  local data=$KIT/data
  mkdir -p "$data/content" "$data/state" "$data/custom" "$data/backups" "$data/apk/out" "$data/apk/base"
  cp -r "$KIT/content/." "$data/content/"
  mkdir -p "$data/content/web/DMQ/Patterns" && echo stand-in > "$data/content/web/DMQ/Patterns/1"
  if [ -n "${APK:-}" ]; then
    cp "$APK" "$data/apk/base/"
  fi
  chmod -R a+rwX "$data"
  sed -e "s#hostPath: ./data#hostPath: $data#" -e "s/^name: .*/name: $KIND_CLUSTER/" "$ROOT/deploy/kind/cluster.yaml" > "$KIT/cluster.yaml"
  kind delete cluster --name "$KIND_CLUSTER" >/dev/null 2>&1 || true
  kind create cluster -q --config "$KIT/cluster.yaml" --image kindest/node:v1.33.1
  kind load docker-image -q --name "$KIND_CLUSTER" "${names[@]}"
  local kc=(kubectl --context "kind-$KIND_CLUSTER")
  "${kc[@]}" wait --for=condition=Ready node --all --timeout=180s >/dev/null
  close_kind_network
  expect "the nodes have no way out" docker exec "$KIND_CLUSTER-control-plane" sh -c '! curl -s -m 5 -o /dev/null https://ghcr.io'

  # The chart as helm pull leaves it, and the values as the guide writes them; the rest is this cluster's own.
  helm package "$ROOT/deploy/helm/opendmtq" --version 1.0.0 --app-version closed-test -d "$KIT" >/dev/null
  # shellcheck disable=SC2016  # Markdown's backticks, not the shell's.
  sed -n '/^```yaml$/,/^```$/p' "$ROOT/docs/closed-network.md" | sed '/^```/d' > "$KIT/closed-network.yaml"
  expect "the guide's values name the registry for every image" test "$(grep -c "$registry" "$KIT/closed-network.yaml")" = 5
  local builder=false
  if [ -n "${APK:-}" ]; then
    builder=true
  fi
  if helm --kube-context "kind-$KIND_CLUSTER" install opendmtq "$KIT/opendmtq-1.0.0.tgz" -n opendmtq --create-namespace \
      -f "$ROOT/deploy/kind/values.yaml" -f "$KIT/closed-network.yaml" --set image.server.tag=closed-test --set image.tools.tag=closed-test \
      --set builder.enabled=$builder --set publicHost=127.0.0.1:18080 --wait --timeout 15m > "$KIT/helm.log" 2>&1; then
    pass "helm install, with nothing pulled"
  else
    tail -n 20 "$KIT/helm.log"
    "${kc[@]}" -n opendmtq get pods -o wide | cut -c1-120
    fail "helm install"
  fi
  local pulls
  pulls=$("${kc[@]}" -n opendmtq get events 2>/dev/null | grep -cE 'ErrImagePull|ImagePullBackOff|Failed to pull' || true)
  expect "no pod tried to pull an image ($pulls)" test "$pulls" = 0
  expect "the server answers through the router" is 200 "http://127.0.0.1:18080/opendmtq/health.php"
  if python3 "$ROOT/tests/game/protocol.py" "http://127.0.0.1:18080" > "$KIT/kube-protocol.log" 2>&1; then
    pass "the game server's contract"
  else
    tail -n 20 "$KIT/kube-protocol.log"
    fail "the game server's contract"
  fi
  if [ -n "${APK:-}" ]; then
    local app
    app=$(find "$data/apk/out" -name '*.apk' | head -n 1)
    app_has_the_runtime "$(python3 -m zipfile -l "$app" | awk '{print $1}')"
  fi
  open_kind_network
  kind delete cluster --name "$KIND_CLUSTER" >/dev/null 2>&1 || true
  docker image rm "${names[@]}" >/dev/null 2>&1 || true
}

case "$WHAT" in
  docker) docker_way ;;
  host) host_way ;;
  kubernetes) kube_way ;;
  all) docker_way; host_way; kube_way ;;
  *) echo "usage: tests/closed/run.sh [docker|host|kubernetes|all]"; exit 2 ;;
esac

echo "$([ "$failures" = 0 ] && echo PASS || echo FAIL) on a closed network: $failures failure(s)"
exit $((failures > 0))
