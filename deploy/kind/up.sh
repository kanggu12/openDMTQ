#!/usr/bin/env bash
# Create the local three-node cluster and deploy OpenDMTQ into it from the locally built images.
# Usage: deploy/kind/up.sh        (run ./opendmtq setup first: it builds the images and data/)
set -euo pipefail
cd "$(dirname "$0")/../.."

# kind wants absolute mount paths; render them from this checkout.
CONFIG=$(mktemp)
trap 'rm -f "$CONFIG"' EXIT
sed "s#hostPath: ./data#hostPath: $PWD/data#" deploy/kind/cluster.yaml > "$CONFIG"

kind get clusters | grep -qx opendmtq || kind create cluster --config "$CONFIG" --image kindest/node:v1.33.1
# Same tags as the chart's values.yaml (the router's is pinned like compose's edge).
docker pull -q nginxinc/nginx-unprivileged:1.27.5-alpine >/dev/null
docker pull -q litestream/litestream:0.3.13 >/dev/null
docker pull -q chrislusf/seaweedfs:3.97 >/dev/null
# Locally built images are not in any registry; copy them onto the nodes.
kind load docker-image --name opendmtq opendmtq-server:local opendmtq-tools:local \
  nginxinc/nginx-unprivileged:1.27.5-alpine litestream/litestream:0.3.13 chrislusf/seaweedfs:3.97
kubectl --context kind-opendmtq wait --for=condition=Ready node --all --timeout=180s
# Same address the Compose stack uses (written by ./opendmtq setup).
HOST=$(sed -n 's/^PUBLIC_HOST=//p' .env | tr -d '"\r' | tail -1)
[[ -n "$HOST" ]] || { echo "no PUBLIC_HOST in .env; run ./opendmtq setup first" >&2; exit 1; }
helm --kube-context kind-opendmtq upgrade --install opendmtq deploy/helm/opendmtq \
  -n opendmtq --create-namespace -f deploy/kind/values.yaml --set publicHost="$HOST" --wait --timeout 10m
echo "OpenDMTQ on kind: http://127.0.0.1:18080/  (failover drill: tests/ha/failover.sh)"
