#!/usr/bin/env bash
# What a viewer hears from a recording, against the recording itself. Called by tests/live/run.sh with BROWSER=1, whose stack
# must be up. Usage: tests/live/sound/run.sh <site port> <guid/id> <folder with the recording's .ts files>
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
port=$1
key=${2/\//-}
media=$3
image=opendmtq-sound:test
card=opendmtq-sound-card
work=$(mktemp -d)
cleanup() {
  docker rm -f "$card" >/dev/null 2>&1 || true
  # Written by the containers' user.
  docker run --rm -v "$work:/w" --entrypoint sh "$image" -c 'rm -rf /w/* /w/.[!.]*' 2>/dev/null || true
  rm -rf "$work"
}
trap cleanup EXIT
mkdir -p "$work/out" "$work/sock"
chmod -R a+rwx "$work"
docker build -q -t "$image" "$here" >/dev/null

# The recording's sound, decoded in order.
docker run --rm --network none -v "$media:/media:ro" -v "$work/out:/out" --entrypoint sh "$image" -c '
  cd /media
  for part in $(ls | grep "\.ts$" | sort -n); do echo "file /media/$part"; done > /tmp/parts
  ffmpeg -nostdin -v error -f concat -safe 0 -i /tmp/parts -map 0:a -ac 2 -ar 48000 -f s16le /out/reference.raw'

# The sound card, then the browser. Only the browser is capped.
docker rm -f "$card" >/dev/null 2>&1 || true
docker run -d --name "$card" -v "$here:/usr/src/app/x:ro" -v "$work/out:/out" -v "$work/sock:/sock" --entrypoint sh "$image" x/card.sh >/dev/null
for _ in $(seq 1 50); do [ -e "$work/sock/ready" ] && break; sleep 0.2; done
[ -e "$work/sock/ready" ] || { docker logs "$card" >&2; echo "FAIL the test's sound card did not start" >&2; exit 1; }
docker run --rm --network host --cpus 2 --memory 2g --shm-size 1g -e PULSE_SERVER=unix:/sock/native -e DISPLAY=:77 \
  -v "$here:/usr/src/app/x:ro" -v "$work/sock:/sock" --entrypoint sh "$image" -c \
  "export HOME=/tmp/home XDG_RUNTIME_DIR=/tmp/xdg; mkdir -p \$HOME \$XDG_RUNTIME_DIR; Xvfb :77 -screen 0 1280x900x24 >/dev/null 2>&1 & sleep 1; exec node x/play.js $port $key" \
  2> >(grep -v -E "dbus|ERROR:|WARNING:|INFO:" >&2)
touch "$work/sock/stop"
docker wait "$card" >/dev/null
docker run --rm --network none -v "$here:/x:ro" -v "$work/out:/out:ro" --entrypoint python3 "$image" /x/compare.py /out/heard.raw /out/reference.raw
