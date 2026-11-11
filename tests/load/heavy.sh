#!/usr/bin/env bash
# The heavy round's work (tests/load/load.py runs it as HEAVY_CMD; run.sh sets what it reads): a backup by the admin
# service and a build of the app by the builder, both at once and on the cores the server has, as an owner's Back up now
# and an address change would bring. Both must end well, or the round measured nothing heavy.
set -u
# The backup, in the admin service, by the function its Back up now calls.
docker exec "$ADMIN" python3 -c 'from opendmtq_tools.admin import backups; print("backup", backups.make_backup("load"))' &
backup=$!
# The app built again from the base APK, by the builder as ./opendmtq runs it, on the same cores.
docker run --rm --name "$BUILDER" --network none --cpuset-cpus "$CORES" --memory 2g -u 33:33 \
  -e PUBLIC_HOST="$HOST" -e HOME=/tmp -v "$DATA/apk:/apk" "opendmtq-tools:$TAG" opendmtq_tools.builder --force
built=$?
wait "$backup"
backed=$?
echo "build exit $built, backup exit $backed"
[ "$built" -eq 0 ] && [ "$backed" -eq 0 ]
