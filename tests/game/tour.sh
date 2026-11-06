#!/usr/bin/env bash
# A tour of the game on a running Android emulator: the app of this server installed from nothing, through its first start and
# data download, into the lobby, the menu, the options, the album and the shop, with a screenshot of each stop. It fails when
# the game dies or leaves the screen, when a press changes nothing on it, or when the log shows a crash; what the screenshots
# show (no dead menu entries, nothing misplaced) is for a person to look at: the game's art cannot go in this repository.
#
# Needs: a running test server, an emulator on adb, and the app built for an address the emulator reaches. Point it at a test
# server, not the one people play on: a first start makes a new player there. Taps only while the game is on the screen, so that
# nothing else on the device gets pressed. Coordinates are for a 1280x720 screen.
#
# Usage: tests/game/tour.sh <report folder>
# ADB (default adb), DEVICE (default emulator-5554), APP_FOLDER (the builder's output; default data/apk/out).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
REPORT=${1:?usage: tests/game/tour.sh <report folder>}
ADB=${ADB:-adb}
DEVICE=${DEVICE:-emulator-5554}
APP_FOLDER=${APP_FOLDER:-$ROOT/data/apk/out}
# The app on offer and its package name, from the builder's manifest.
APK=$APP_FOLDER/$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['file'])" "$APP_FOLDER/latest.json")
PACKAGE=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['package'])" "$APP_FOLDER/latest.json")
mkdir -p "$REPORT"

device() { timeout 30 "$ADB" -s "$DEVICE" "$@"; }

# Is the game what the screen shows?
# (The whole answer first: with pipefail, grep stopping at its first line would count as a failure of what is writing to it.)
in_game() { local windows; windows=$(device shell dumpsys window); case "$(printf '%s\n' "$windows" | grep mCurrentFocus)" in *"$PACKAGE"*) return 0;; esac; return 1; }

# Stop here unless the game is on the screen; a press now would go to whatever else is.
stay_in_game() {
  if ! in_game; then
    echo "FAIL the game left the screen at: $1"
    device shell dumpsys window | grep -m1 mCurrentFocus | cut -c1-160
    exit 1
  fi
}

tap() {
  stay_in_game "tap $1 $2"
  device shell input tap "$1" "$2"
  sleep "${3:-3}"
}

back() {
  stay_in_game "back"
  device shell input keyevent 4
  sleep 3
}

# A picture of the screen for people, and its raw pixels to compare with the last stop.
shot() {
  device exec-out screencap -p > "$REPORT/$1.png"
  mv -f "$REPORT/.now.raw" "$REPORT/.last.raw" 2> /dev/null || true
  device exec-out screencap > "$REPORT/.now.raw"
  echo "stop $1"
}

# A press that changed nothing: the tour is stuck behind something it does not know, and its other stops would prove nothing.
# How much of the screen differs from the last stop, on every 97th pixel of the raw dump (a header of 16 bytes, then RGBA).
changed() {
  shot "$1"
  python3 - "$REPORT/.last.raw" "$REPORT/.now.raw" "$1" <<'PY'
import sys
last, now, name = open(sys.argv[1], "rb").read()[16:], open(sys.argv[2], "rb").read()[16:], sys.argv[3]
step = 97 * 4
differ = sum(abs(last[i] - now[i]) + abs(last[i + 1] - now[i + 1]) + abs(last[i + 2] - now[i + 2]) > 60 for i in range(0, min(len(last), len(now)) - 3, step))
share = differ / (min(len(last), len(now)) // step)
if share < 0.03:
    sys.exit(f"FAIL the screen did not change at {name}: {share:.1%} of it differs from the last stop")
PY
}

# A clean start: nothing of the app left, an empty log.
device uninstall "$PACKAGE" > /dev/null 2>&1 || true
# -g: Android's storage question answered at install. On a player's device the game explains it first and Android then asks:
# that part is in the tables of docs/test-cases.md, for a person to go through.
if ! timeout 300 "$ADB" -s "$DEVICE" install -r -g "$APK" > "$REPORT/install.txt" 2>&1; then
  echo "FAIL the app did not install:"
  cut -c1-200 "$REPORT/install.txt" | tail -5
  exit 1
fi
device logcat -c
device shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 > /dev/null 2>&1

# Its first start asks nothing and downloads its data, with its progress on the screen. A new player then picks a name.
sleep 20
shot 01-first-start
stay_in_game "first start"
sleep 40
shot 02-nickname
stay_in_game "data download"
tap 640 452
changed 03-how-to-play
tap 848 638
changed 04-lobby

# From the lobby: the menu, what is in it, and back. Only what works on this server is left on each of these screens.
tap 34 670
changed 05-menu
tap 882 304 5
changed 06-options
back
tap 34 670
tap 640 304 5
changed 07-album
back
tap 34 670
tap 398 304 5
changed 08-shop
back
changed 09-lobby
stay_in_game "the end of the tour"

# A second start must not download anything again: the data stays on the device, and the lobby is there at once.
device shell am force-stop "$PACKAGE"
device shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 > /dev/null 2>&1
sleep 30
shot 10-second-start
stay_in_game "second start"

# What the device's log says.
if device logcat -d -v brief -t 8000 | grep -E "FATAL|Fatal signal|NullReference|signal 11|ANR in" | grep -vE "NoSuchMethod|ClassNotFound|StrictMode" > "$REPORT/crashes.txt"; then
  echo "FAIL the log shows crashes:"
  cut -c1-200 "$REPORT/crashes.txt" | head -20
  exit 1
fi
rm -f "$REPORT/crashes.txt" "$REPORT/.last.raw" "$REPORT/.now.raw"
device shell am force-stop "$PACKAGE"
echo "PASS the tour went through without a crash; look through $REPORT"
