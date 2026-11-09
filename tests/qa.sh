#!/usr/bin/env bash
# The local quality gate: everything that needs the game's own files, which CI does not have, plus the tests CI also runs, on
# this machine, for the commit checked out. When all of it passes the commit gets the status qa/local on GitHub; a release
# (.github/workflows/release.yml) and ./opendmtq deploy ask for that status. See docs/testing.md.
#
# Usage: tests/qa.sh [--no-status]       --no-status: run everything, tell GitHub nothing (for a tree with changes in it)
#        EMULATOR=1 APP_FOLDER=<a test server's data/apk/out> tests/qa.sh
#                                        also the tour of the game on a running emulator (tests/game/tour.sh)
#        CLIENTS=<folder> tests/qa.sh    also every edit of the patcher against each APK in that folder: the game's other
#                                        version, a copy changed for another server (tools/tests/test_real_client.py)
#
# One report per commit under _work/qa, the newest five kept: each step's whole output and the list of results.
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1
SHA=$(git rev-parse HEAD)
SHORT=${SHA:0:7}
REPORT=$ROOT/_work/qa/$SHORT
POST_STATUS=yes
if [ "${1:-}" = --no-status ]; then
  POST_STATUS=no
fi

# A status says "this commit passed": with other changes in the tree the tests are not about that commit.
if [ "$POST_STATUS" = yes ] && [ -n "$(git status --porcelain)" ]; then
  echo "qa: the tree has changes that are not committed; commit them, or use --no-status" >&2
  exit 2
fi

mkdir -p "$REPORT"
# The newest five reports stay; these are large with their screenshots.
# (What a browser wrote in one may be another user's: then from inside an image, or _work would only ever grow.)
find "$ROOT/_work/qa" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | tail -n +6 | cut -d' ' -f2- | while read -r old; do
  rm -rf "$old" 2>/dev/null || docker run --rm -u 0 -v "$ROOT/_work/qa:/q" --entrypoint rm opendmtq-server:uitest -rf "/q/$(basename "$old")" || true
done

FAILED=0
: > "$REPORT/report.txt"
# One step: its output to a file of its own, one line for it in the report and on the screen.
step() {
  local name=$1
  shift
  local start status
  start=$(date +%s)
  "$@" > "$REPORT/$name.log" 2>&1
  status=$?
  local line
  if [ "$status" -eq 0 ]; then
    line="PASS $name ($(($(date +%s) - start)) s)"
  else
    line="FAIL $name ($(($(date +%s) - start)) s): see $REPORT/$name.log"
    FAILED=1
  fi
  echo "$line" | tee -a "$REPORT/report.txt"
}

tools_tests() {
  docker build -q -t opendmtq-tools:qa tools > /dev/null || return 1
  # The real game client, for the edits that must find their bytes and objects in it: the file ./opendmtq import brought.
  local base
  base=$(find data/apk/base -maxdepth 1 -name '*.apk' 2>/dev/null | head -1)
  # Without it those tests would skip themselves, and this gate would pass without having looked.
  if [ -z "$base" ]; then
    echo "no game client in data/apk/base: run ./opendmtq import first"
    return 1
  fi
  # More clients for the same edits, when a folder of them is named.
  local more=()
  if [ -n "${CLIENTS:-}" ]; then
    [ -d "$CLIENTS" ] || { echo "CLIENTS is not a folder: $CLIENTS"; return 1; }
    more=(-v "$(cd "$CLIENTS" && pwd):/clients:ro" -e OPENDMTQ_CLIENTS=/clients)
  fi
  # server/portal and the runtime's build beside tools/, as in the repository: the tests read them too.
  docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v "$ROOT/tools:/t:ro" -v "$ROOT/server/portal:/server/portal:ro" \
    -v "$ROOT/arm32:/arm32:ro" \
    -v "$ROOT/data/apk/base:/base:ro" "${more[@]}" \
    -e OPENDMTQ_BASE_APK="/base/$(basename "$base")" --entrypoint sh opendmtq-tools:qa \
    -c 'cd /t && python3 -m unittest discover -s tests -t . -v'
}

cli_tests() {
  (cd cli && python3 -m unittest discover -s tests -t . -v)
}

# CI's shell step, with the ShellCheck GitHub's runners have: another version passes what theirs does not, and the first run of
# CI after going public would have been the first to say so.
shell_tests() {
  local shellcheck=(docker run --rm -v "$ROOT:/mnt:ro" -w /mnt koalaman/shellcheck:v0.9.0 --severity=warning)
  git ls-files -z '*.sh' | grep -zv '^arm32/' | xargs -0 "${shellcheck[@]}" || return 1
  "${shellcheck[@]}" -x -P arm32 arm32/build.sh arm32/bundle.sh arm32/test.sh arm32/ndk.sh arm32/build_desktop.sh arm32/build_windows.sh \
    arm32/bundle_windows.sh arm32/test_desktop.sh arm32/test_windows.sh
}

# The PC client's launcher, as CI's client job runs it: its unit tests, then every screen on a virtual screen with the
# layout check, the screenshots kept with the report.
client_tests() {
  docker build -q -t opendmtq-client-ui:local client/tests/ui >/dev/null || return 1
  docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -v "$ROOT:/src:ro" -w /src/client opendmtq-client-ui:local \
    python -m unittest discover -s tests -t . -v || return 1
  client/tests/ui/run.sh "$REPORT/client-ui"
}

step shell shell_tests
step tools tools_tests
step cli cli_tests
step client client_tests
# The game server's contract with the game, on stand-in game files: every reply the client reads, and its quirks.
step game tests/game/protocol.sh
# The server on the real game files: the game's own requests, broadcasts, recordings, and a real video in Chromium.
step live env BROWSER=1 tests/live/run.sh
# The pages in a real browser. In CI too; here also for what the screenshots show.
step ui tests/ui/run.sh "$REPORT/ui"
# An upgrade: the last release's images used as people use them, then this tree's on the same data. In CI too.
step upgrade tests/upgrade/run.sh
# Without containers: host/install.sh on a clean Ubuntu, the server run by ./opendmtq, and the phone app built from the
# game client here (CI runs the same without a client).
host_tests() {
  APK="$ROOT/$(find data/apk/base -maxdepth 1 -name '*.apk' | head -1)" tests/host/run.sh
}
step host host_tests
# On a test server's app (APP_FOLDER): a first start makes a new player on the server the app belongs to.
if [ -n "${EMULATOR:-}" ]; then
  step tour tests/game/tour.sh "$REPORT/game"
fi

if [ "$FAILED" -ne 0 ]; then
  echo "qa: FAILED on $SHORT, report in $REPORT"
  exit 1
fi

passed="$(grep -c '^PASS' "$REPORT/report.txt") steps passed on this machine"
if [ "$POST_STATUS" = yes ]; then
  # The tree may have moved on during a run this long: the status would then be about something that was not tested.
  if [ -n "$(git status --porcelain)" ] || [ "$(git rev-parse HEAD)" != "$SHA" ]; then
    echo "qa: passed, but the tree changed during the run; no status sent" >&2
    exit 1
  fi
  if ! gh api "repos/{owner}/{repo}/statuses/$SHA" -f state=success -f context=qa/local -f description="$passed" > /dev/null; then
    echo "qa: passed, but the status could not be sent (is gh signed in, is the commit pushed?)" >&2
    exit 1
  fi
  echo "qa: $SHORT passed: status qa/local sent"
else
  echo "qa: $SHORT passed (no status sent)"
fi
