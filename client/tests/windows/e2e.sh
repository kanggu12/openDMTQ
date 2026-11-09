#!/bin/bash
# The PC client from end to end under Wine, against a test server:
#   1. the installer as a player gets it: the build's OpenDMTQ-Setup.exe handed to the server (as a release's would
#      be), then downloaded from the server's /windows, signed in, with the server on its end
#   2. installed through its own dialog (Enter on Install), Velopack's setup underneath, the launcher started after
#   3. the launcher's first-start guide: the server the installer brought, the sign-in, the app's download, PLAY
#   4. the player reaching the game's menu (a frame of it saved), closed as a person closes a window, the launcher back
# Every step leaves a screenshot of the virtual screen in OUT_DIR, and the logs.
#
#   TEST_SITE=URL TEST_NET=NETWORK TEST_APK=DIR TEST_TOOLS=IMAGE ACCOUNT_FILE=FILE client/tests/windows/e2e.sh BUILD_DIR OUT_DIR
#
# The test server is a throwaway OpenDMTQ server with its app built, on a Docker network with no way out (as
# tests/closed/game.sh starts one): TEST_SITE is its site's address on the network TEST_NET, TEST_APK its data/apk folder
# (the installer is handed to it there) and TEST_TOOLS the tools image of its version. ACCOUNT_FILE holds a site account
# of it, its ID on the first line and its password on the second: read inside the containers only, never printed or
# copied. BUILD_DIR is client/packaging/windows/build.sh's OUT_DIR.
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
BUILD=$(realpath -m "${1:?usage: e2e.sh BUILD_DIR OUT_DIR}")
OUT=$(realpath -m "${2:?usage: e2e.sh BUILD_DIR OUT_DIR}")
SITE=${TEST_SITE:?the site address of the test server}
NET=${TEST_NET:?the Docker network of the test server}
APK=$(realpath -m "${TEST_APK:?the data/apk folder of the test server}")
TOOLS=${TEST_TOOLS:?the tools image of the test server}
ACCOUNT_FILE=$(realpath -m "${ACCOUNT_FILE:?ACCOUNT_FILE: a site account of the test server}")
[ -f "$BUILD/releases/OpenDMTQ-Setup.exe" ] || { echo "no $BUILD/releases/OpenDMTQ-Setup.exe: run build.sh first" >&2; exit 1; }
[ -f "$ACCOUNT_FILE" ] || { echo "no account file $ACCOUNT_FILE" >&2; exit 1; }
docker network inspect "$NET" >/dev/null 2>&1 || { echo "no Docker network $NET" >&2; exit 1; }
rm -rf "$OUT" && mkdir -p "$OUT"
# The test machine: the player's Wine image with xdotool and screenshots (built once, with the network it needs).
docker image inspect opendmtq-arm32-wine >/dev/null 2>&1 \
  || docker build -q -t opendmtq-arm32-wine -f "$ROOT/arm32/wine.Dockerfile" "$ROOT/arm32" >/dev/null
docker image inspect opendmtq-client-e2e:local >/dev/null 2>&1 \
  || docker build -q -t opendmtq-client-e2e:local "$ROOT/client/tests/windows" >/dev/null

# ---- 1. the installer on the server, and back from its /windows as a player downloads it
cp "$BUILD/releases/OpenDMTQ-Setup.exe" "$BUILD/releases/OpenDMTQ-Setup.exe.version" "$APK/"
chmod a+rw "$APK/OpenDMTQ-Setup.exe" "$APK/OpenDMTQ-Setup.exe.version"
docker run --rm --network none -u 33:33 -e HOME=/tmp -v "$APK:/apk" --entrypoint python3 "$TOOLS" -c \
  "from opendmtq_tools import windows_client; print('server offers', windows_client.keep('/apk/out', '/apk/OpenDMTQ-Setup.exe'))"
docker run --rm --network "$NET" -e PYTHONDONTWRITEBYTECODE=1 -v "$ROOT:/src:ro" -v "$OUT:/out" \
  -v "$ACCOUNT_FILE:/account:ro" -w /src/client opendmtq-client-ui:local python3 -c "
import re, sys, urllib.request
from opendmtq_client import preset, server
user, password = open('/account', encoding='utf-8').read().splitlines()[:2]
cookie = server.sign_in('$SITE', user, password)['cookie']
request = urllib.request.Request('$SITE/windows', headers={'Cookie': 'opendmtq_dl=' + cookie})
with urllib.request.urlopen(request, timeout=60) as response:
    name = re.search(r'filename=\"([^\"]+)\"', response.headers.get('Content-Disposition', '')).group(1)
    data = response.read()
open('/out/' + name, 'wb').write(data)
print('downloaded', name, len(data), 'bytes; it brings', preset.read('/out/' + name))
" || { echo "FAIL: the installer could not be downloaded from the server" >&2; exit 1; }
SETUP=$(cd "$OUT" && ls OpenDMTQ-Setup-*.exe | head -n 1)
[ -n "$SETUP" ] || { echo "FAIL: no installer came" >&2; exit 1; }

# ---- 2 to 4 under Wine, on the virtual screen
docker run --rm --network "$NET" -v "$OUT:/out" -v "$ACCOUNT_FILE:/account:ro" -w /out \
  -e WINEPREFIX=/tmp/wine -e WINEDEBUG=-all -e TZ=Asia/Seoul -e PLAYER_SHOTS=@50 opendmtq-client-e2e:local bash -c "
  set -u
  Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
  export DISPLAY=:99
  for i in \$(seq 1 30); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.3; done
  WINEDLLOVERRIDES='mscoree=;mshtml=' wineboot -i >/dev/null 2>&1
  LOCAL=\$(winepath -u 'C:\\users\\root\\AppData\\Local' 2>/dev/null || echo /tmp/wine/drive_c/users/root/AppData/Local)
  step=0
  snap() { step=\$((step + 1)); import -window root \"/out/\$(printf %02d \$step)-\$1.png\"; echo \"screen \$step: \$1\"; }
  # The launcher's window, its place and size, and a click at a point given from its bottom-right corner.
  window() { xdotool search --name \"\$1\" 2>/dev/null | tail -n 1; }
  click_from_corner() {
    local id=\$(window '^OpenDMTQ\$'); eval \$(xdotool getwindowgeometry --shell \"\$id\")
    xdotool mousemove \$((X + WIDTH - \$1)) \$((Y + HEIGHT - \$2)) click 1
  }
  # A click at a point given from the window's top-left corner (the menu column's entries).
  click_from_top() {
    local id=\$(window '^OpenDMTQ\$'); eval \$(xdotool getwindowgeometry --shell \"\$id\")
    xdotool mousemove \$((X + \$1)) \$((Y + \$2)) click 1
  }
  # The guide's Next (and, on its last step, PLAY): the bottom bar's right end.
  next() { sleep 1; click_from_corner 66 31; sleep 2; }
  wait_for() { local i; for i in \$(seq 1 \$1); do eval \"\$2\" && return 0; sleep 1; done; return 1; }
  # The player as Wine runs it, by its own command line: this script holds the name too, so a plain match on the name
  # would always find the script itself.
  player_running() { ps -eo args | grep -q '[O]penDMTQ-Player[.]exe'; }
  # A line of the player's log so far (it sits in the app's folder under the launcher's).
  player_said() { cat \"\$LOCAL\"/OpenDMTQ/*/player.log 2>/dev/null | grep -q \"\$1\"; }
  # The logs and the game's frame, whatever happens: a failure needs them most.
  collect() {
    cp \"\$LOCAL\"/OpenDMTQ/client/logs/launcher.log /out/ 2>/dev/null
    for d in \"\$LOCAL\"/OpenDMTQ/*/; do
      [ -f \"\$d/player.log\" ] && cp \"\$d/player.log\" /out/player.log
      [ -d \"\$d/data/shots\" ] && cp -r \"\$d/data/shots\" /out/shots
    done
    cp \"\$(winepath -u 'C:\\users\\root\\AppData\\Local\\Temp' 2>/dev/null)\"/OpenDMTQ-setup*.log /out/ 2>/dev/null
    chmod -R a+rwX /out
  }
  trap collect EXIT

  # 2. the installer and its dialog: Enter on Install
  wine '$SETUP' > /out/setup-stdout.log 2>&1 &
  wait_for 120 '[ -n \"\$(window \"OpenDMTQ Setup\")\" ]' || { snap setup-missing; echo 'FAIL: no installer window'; exit 1; }
  sleep 4; snap setup-asks
  xdotool windowfocus --sync \$(window 'OpenDMTQ Setup') 2>/dev/null; xdotool key Return
  wait_for 240 '[ -n \"\$(window \"^OpenDMTQ\$\")\" ]' || { snap setup-stuck; echo 'FAIL: the launcher did not start'; exit 1; }
  echo \"installed: \$(cat \"\$LOCAL/OpenDMTQ.Client/current/sq.version\" 2>/dev/null | grep -o '<version>[^<]*' | cut -c10-)\"
  sleep 6; snap guide-welcome
  # 3. the guide: the server the installer brought answers by itself
  next; sleep 3; snap guide-server
  next; snap guide-login
  # The ID field has the keyboard on this step: the ID, Tab, the password, Enter signs in.
  xdotool windowfocus --sync \$(window '^OpenDMTQ\$') 2>/dev/null
  xdotool type --delay 40 \"\$(sed -n 1p /account)\"; xdotool key Tab
  xdotool type --delay 40 \"\$(sed -n 2p /account)\"; xdotool key Return
  sleep 4; snap guide-signed-in
  next; sleep 2; snap guide-downloading
  wait_for 300 'ls \"\$LOCAL\"/OpenDMTQ/client/servers/*/app.json >/dev/null 2>&1' || { snap download-stuck; echo 'FAIL: no app'; exit 1; }
  sleep 3; snap guide-downloaded
  next; snap guide-sound
  next; sleep 3; snap guide-stage
  # PLAY: the game starts in the player, and the launcher steps aside.
  click_from_corner 66 31
  wait_for 60 player_running || { snap no-player; echo 'FAIL: the player did not start'; exit 1; }
  echo 'player started'
  sleep 20; snap game-starting
  # The frame PLAYER_SHOTS asks for comes 50 s in: then the game is at its menu.
  sleep 45; snap game-menu
  # 4. Alt+F4 does not end the game (it opens the player's menu); the menu's Quit does, and the launcher comes back. The
  # game fills the screen (full screen at 96 dpi): the menu button sits 33 px in from the top right corner, and Quit is
  # the menu's third row, 193 px below the top of its card of 264 px, centred.
  game=\$(xdotool search --name 'TECHNIKA' 2>/dev/null | tail -n 1)
  [ -n \"\$game\" ] && xdotool windowfocus --sync \"\$game\" 2>/dev/null; xdotool key alt+F4
  sleep 5; snap alt-f4-menu
  player_running || { echo 'FAIL: Alt+F4 ended the game'; exit 1; }
  echo 'Alt+F4 left the game running'
  # The menu holds the game still, and lets it go on when it closes (Esc); the game still drawing well after.
  wait_for 10 'player_said \"the game is paused\"' || { echo 'FAIL: the menu did not pause the game'; exit 1; }
  echo 'the menu paused the game'
  xdotool key Escape
  wait_for 10 'player_said \"the game goes on\"' || { echo 'FAIL: closing the menu did not resume the game'; exit 1; }
  echo 'the game went on'
  sleep 15; player_running || { echo 'FAIL: the game ended after the menu closed'; exit 1; }
  snap after-menu
  eval \$(xdotool getwindowgeometry --shell \"\$game\")
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 0.5
  xdotool mousemove \$((X + WIDTH - 33)) \$((Y + 33)); sleep 1; snap menu-button
  xdotool click 1; sleep 2; snap menu-open
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + (HEIGHT - 264) / 2 + 193)); sleep 1; xdotool click 1
  wait_for 60 '! player_running' || { snap player-stays; echo 'FAIL: the menu did not end the game'; exit 1; }
  echo 'player closed'
  # Back in sight, with how the game went.
  wait_for 20 '[ -n \"\$(xdotool search --onlyvisible --name \"^OpenDMTQ\$\" 2>/dev/null)\" ]' \\
    || { snap launcher-hidden; echo 'FAIL: the launcher did not come back'; exit 1; }
  echo 'launcher back'
  sleep 3; snap launcher-back
  # The Screen page with what Windows says of the display, and the Sound page with the devices the player lists: the
  # middles of their rows in the menu column at 96 dpi (rows 49 px apart, PLAY's at 166). A layout that moves them
  # shows the same page twice, and the run fails on it below rather than passing with the wrong screens.
  click_from_top 90 215; sleep 3; snap screen-page
  click_from_top 90 264; sleep 10; snap sound-page
  if [ \"\$(md5sum < /out/\$(printf %02d \$((step - 1)))-screen-page.png | cut -d' ' -f1)\" = \
       \"\$(md5sum < /out/\$(printf %02d \$step)-sound-page.png | cut -d' ' -f1)\" ]; then
    echo 'FAIL: the Screen and Sound clicks showed the same page'; exit 1
  fi
  # The command line's view of the same state, without secrets.
  wine \"\$LOCAL/OpenDMTQ.Client/current/OpenDMTQ-cmd.exe\" --status 2>&1 | tr -d '\r' > /out/status.txt
  # The sound devices as the Sound page asks the player for them (Wine's own, here).
  wine \"\$LOCAL/OpenDMTQ.Client/current/OpenDMTQ-cmd.exe\" --audio-devices 2>&1 | tr -d '\r' >> /out/status.txt
  cat /out/status.txt
  collect
  wineserver -k
  echo 'e2e done'
"
status=$?
echo "screens and logs in $OUT"
# The run inside says FAIL and ends with 1 at the step that failed: this script ends the same way.
exit $status
