#!/usr/bin/env bash
# An upgrade, on throwaway servers with no game files. The last release's server and admin service (the images it
# published) are used the way people use them (upgrade.py: players and their plays, a site account, an API token, the
# recordings' limits, a broadcast with its recording, a backup), are stopped as an upgrade stops them, and this tree's
# images start on the same data folder. Everything must still be there and work, and the backup must restore. A second
# server, which nobody broadcast on, must keep broadcasts off. Each is upgraded a second time on a copy of its data with the
# admin service up first and alone, as a restart can have it: whichever of the two looks at the data first, the answer is
# the same. Then all of it once more from this tree's own images: a restart loses nothing either, and the steps of the
# first half are known to work on the release this tree becomes.
#
# Usage: tests/upgrade/run.sh
#   FROM=0.7.0             the release to upgrade from. Default: the newest release in CHANGELOG.md whose images there are
#                          (here already, or pulled), so the one before this tree's until this tree's is published.
#   OLD_SERVER, OLD_TOOLS  its images, when they are not the chart's (deploy/helm/opendmtq/values.yaml) tagged FROM
#   TAG=uitest NO_BUILD=1  this tree's images are those already tagged opendmtq-*:TAG (default: built here, as "upgrade")
#   SITE_PORT, ADMIN_PORT  default 18721 and 18722
#   KEEP=1                 leaves the last server up and the data folders in place
# Needs Docker and Python 3, and the last release's images: from the registry, or loaded here beforehand (docker load).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
TAG=${TAG:-upgrade}
NET=odq-upgrade
SITE=odq-upgrade-site
ADMIN=odq-upgrade-admin
SITE_PORT=${SITE_PORT:-18721}
ADMIN_PORT=${ADMIN_PORT:-18722}
# The owner's admin password, on both sides of the upgrade.
PASSWORD=upgrade-pass
WORK=$(mktemp -d)
NEW_SERVER=opendmtq-server:$TAG
NEW_TOOLS=opendmtq-tools:$TAG
failed=0

# What the containers wrote belongs to their user: removed from inside an image.
cleanup() {
  docker rm -f "$SITE" "$ADMIN" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  docker run --rm -u 0 -v "$WORK:/d" --entrypoint sh "$NEW_SERVER" -c 'rm -rf /d/* /d/.[!.]*' >/dev/null 2>&1 || true
  rmdir "$WORK" 2>/dev/null || true
}
if [ -z "${KEEP:-}" ]; then
  trap cleanup EXIT
fi

if [ -z "${NO_BUILD:-}" ]; then
  docker build -q -t "$NEW_SERVER" "$ROOT/server" >/dev/null
  docker build -q -t "$NEW_TOOLS" "$ROOT/tools" >/dev/null
fi

# True when an image is here already, or can be pulled.
have() {
  docker image inspect "$1" >/dev/null 2>&1 || docker pull -q "$1" >/dev/null 2>&1
}

# The images a release publishes, as the chart names them.
values=$ROOT/deploy/helm/opendmtq/values.yaml
server_repo=$(sed -n 's|^ *repository: *\(.*/opendmtq-server\) *$|\1|p' "$values")
tools_repo=$(sed -n 's|^ *repository: *\(.*/opendmtq-tools\) *$|\1|p' "$values")
if [ -z "${FROM:-}" ] && [ -z "${OLD_SERVER:-}" ]; then
  # The newest release that has images: the one this tree becomes has none before it is published.
  for version in $(sed -n 's/^## \[\([0-9][0-9.]*\)\].*/\1/p' "$ROOT/CHANGELOG.md" | head -3); do
    if have "$server_repo:$version" && have "$tools_repo:$version"; then
      FROM=$version
      break
    fi
  done
fi
OLD_SERVER=${OLD_SERVER:-$server_repo:${FROM:-}}
OLD_TOOLS=${OLD_TOOLS:-$tools_repo:${FROM:-}}
if ! have "$OLD_SERVER" || ! have "$OLD_TOOLS"; then
  echo "FAIL no images of a release to upgrade from ($OLD_SERVER, $OLD_TOOLS): pull or load them, or name them with" \
    "OLD_SERVER and OLD_TOOLS" >&2
  exit 1
fi

# The stand-in game files (the pages' tests make them), the same before and after: an upgrade does not touch them.
mkdir -p "$WORK/content"
chmod -R a+rwX "$WORK"
docker run --rm -u 33:33 -v "$WORK/content:/content" -v "$ROOT/tests/ui:/ui:ro" --entrypoint php "$NEW_SERVER" \
  /ui/make_content.php /content >/dev/null
docker network create "$NET" >/dev/null 2>&1 || true
docker rm -f "$SITE" "$ADMIN" >/dev/null 2>&1 || true

# The folders a server keeps its state in, empty. $1: the data folder.
new_data() {
  mkdir -p "$1/state" "$1/apk/out" "$1/custom" "$1/backups"
  chmod -R a+rwX "$1"
}

# Waits until an address answers, or gives up with the container's log. $1: the address, $2: the container.
answers() {
  for _ in $(seq 1 90); do
    if curl -sf -m 3 -o /dev/null "$1"; then
      return 0
    fi
    sleep 1
  done
  echo "FAIL $2 did not come up" >&2
  docker logs --tail 30 "$2" >&2
  return 1
}

# The server on a data folder, as compose starts it: read-only, unprivileged, capped. $1: its image, $2: the data folder.
start_site() {
  docker run -d --name "$SITE" --network "$NET" --cpus 2 --memory 1g -u 33:33 --read-only \
    --tmpfs /var/opendmtq:mode=1777 --tmpfs /tmp:mode=1777 \
    -e PUBLIC_HOST="127.0.0.1:$SITE_PORT" -e ADMIN_ON_PUBLIC_PORT=no -e TZ=Asia/Seoul \
    -v "$WORK/content:/srv/content:ro" -v "$2/state:/data" -v "$2/apk/out:/srv/apk:ro" -v "$2/custom:/srv/custom:ro" \
    -p "127.0.0.1:$SITE_PORT:8080" "$1" >/dev/null
  answers "http://127.0.0.1:$SITE_PORT/opendmtq/health.php" "$SITE"
}

# The admin service on the same data folder. $1: its image, $2: the data folder.
start_admin() {
  docker run -d --name "$ADMIN" --network "$NET" --cpus 2 --memory 1g -u 33:33 --read-only --tmpfs /tmp:mode=1777 \
    -e PUBLIC_HOST="127.0.0.1:$SITE_PORT" -e ADMIN_PASSWORD="$PASSWORD" -e SERVER_URL="http://$SITE:8080" -e HOME=/tmp \
    -e TZ=Asia/Seoul \
    -v "$2/state:/data" -v "$2/apk:/apk" -v "$2/custom:/custom" -v "$2/backups:/backups" \
    -v "$WORK/content:/srv/content:ro" -p "127.0.0.1:$ADMIN_PORT:8000" \
    --entrypoint gunicorn "$1" -w 1 --threads 4 -b 0.0.0.0:8000 opendmtq_tools.admin:app >/dev/null
  answers "http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/login" "$ADMIN"
}

# Both stopped the way an upgrade stops them (asked to end, given the time), and gone. $1: "new" when they ran this tree's
# images: then what they said in their logs is looked at first, a warning of PHP's or an error of the admin service's being
# a bug even when every answer was right.
stop_both() {
  docker stop -t 20 "$SITE" "$ADMIN" >/dev/null 2>&1 || true
  if [ "${1:-}" = new ]; then
    if docker logs "$SITE" 2>&1 | grep -E "PHP (Warning|Notice|Deprecated|Fatal error|Parse error)"; then
      echo "FAIL PHP complained in the upgraded server's log (above)"
      failed=1
    fi
    if docker logs "$ADMIN" 2>&1 | grep -E -B2 -A12 "Traceback \(most recent call last\)"; then
      echo "FAIL the upgraded admin service logged an error (above)"
      failed=1
    fi
  fi
  docker rm -f "$SITE" "$ADMIN" >/dev/null 2>&1 || true
}

# One step of upgrade.py against the servers running now. $1: the step, $2: its notes.
step() {
  python3 "$ROOT/tests/upgrade/upgrade.py" "$1" "http://127.0.0.1:$SITE_PORT" "http://127.0.0.1:$ADMIN_PORT" "$PASSWORD" "$2" \
    || failed=1
}

# A data folder copied whole, with its owners. $1: from, $2: to.
copy_data() {
  mkdir -p "$2"
  docker run --rm -u 0 -v "$1:/from:ro" -v "$2:/to" --entrypoint sh "$NEW_SERVER" -c 'cp -a /from/. /to/'
}

# The upgrade on a copy of a data folder with the admin service up first and alone; the server starts after it has looked.
# $1: the data folder, $2: its notes.
admin_first() {
  start_admin "$NEW_TOOLS" "$1"
  step admin-says "$2"
  start_site "$NEW_SERVER" "$1"
  step site-says "$2"
  stop_both new
}

# Everything from one pair of images. $1: the server's image, $2: the admin service's, $3: a name for the data folders.
upgrade_from() {
  local old_server=$1 old_tools=$2 at=$WORK/$3
  # A server in use.
  new_data "$at/used"
  start_site "$old_server" "$at/used"
  start_admin "$old_tools" "$at/used"
  step before "$at/used.json"
  stop_both
  copy_data "$at/used" "$at/used-admin-first"
  start_site "$NEW_SERVER" "$at/used"
  start_admin "$NEW_TOOLS" "$at/used"
  step after "$at/used.json"
  stop_both new
  admin_first "$at/used-admin-first" "$at/used.json"
  # A server nobody broadcast on.
  new_data "$at/quiet"
  start_site "$old_server" "$at/quiet"
  step quiet-before "$at/quiet.json"
  stop_both
  copy_data "$at/quiet" "$at/quiet-admin-first"
  admin_first "$at/quiet-admin-first" "$at/quiet.json"
  start_site "$NEW_SERVER" "$at/quiet"
  start_admin "$NEW_TOOLS" "$at/quiet"
  step quiet-after "$at/quiet.json"
  if [ -z "${KEEP:-}" ]; then
    stop_both new
  fi
}

echo "== from $OLD_SERVER and $OLD_TOOLS"
upgrade_from "$OLD_SERVER" "$OLD_TOOLS" release
docker rm -f "$SITE" "$ADMIN" >/dev/null 2>&1 || true
echo "== from this tree's own images (a restart)"
upgrade_from "$NEW_SERVER" "$NEW_TOOLS" tree

if [ -n "${KEEP:-}" ]; then
  echo "left running: http://127.0.0.1:$SITE_PORT/ and http://127.0.0.1:$ADMIN_PORT/opendmtq/admin/ (admin, $PASSWORD)," \
    "data in $WORK; remove with: docker rm -f $SITE $ADMIN; docker network rm $NET;" \
    "docker run --rm -u 0 -v $WORK:/d --entrypoint sh $NEW_SERVER -c 'rm -rf /d/*'; rmdir $WORK"
fi
if [ "$failed" -ne 0 ]; then
  echo "upgrade: FAILED"
  exit 1
fi
echo "ALL CHECKS PASSED"
