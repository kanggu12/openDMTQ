#!/bin/bash
# The PC client from end to end under Wine, against a test server:
#   1. the installer as a player gets it: the build's OpenDMTQ-Setup.exe handed to the server (as a release's would
#      be), then downloaded from the server's /windows, signed in, with the server on its end
#   2. installed through its own dialog (Enter on Install), Velopack's setup underneath, the launcher started after
#   3. the launcher's first-start guide: the server the installer brought, the sign-in, the app's download, PLAY
#   4. the player reaching the game's menu (a frame of it saved), the bar at its top edge switching to a window and back,
#      its X asking (the game held still), Keep playing, then the X and Quit the game, the launcher back
#   5. Repair from the command line: a file of the player and one of the launcher put back as they were installed
#   6. Clear game data: the id alone stays, and the game starts again with it and gets to its menu
#   7. Uninstall with the data: refused while the window is open, then the program, its shortcut and its data gone
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
  # 4. Alt+F4 does nothing: the game runs on, not held still. The pointer at the game's top edge shows the bar; its full
  # screen chip switches to a window and back; its X asks first and holds the game still, Keep playing lets it go on,
  # and the X again with Quit the game ends the game, and the launcher comes back. The overlay's sizes are the game's at
  # 720 lines, times the game's height over 720 (Wine is at 96 dpi): 1.5 in full screen here (1920x1080), 1.125 in the
  # window (1440x810), each length rounded as the player rounds it (opx below). The bar is 52 high and shows for a
  # pointer within 4 of the top (y 0 here); its chips are 36 square, 14 in from the right end and 10 apart, centred in
  # its height. The question's card is 600 wide and 62 + 2 + 74 + 56 + 24 high, centred, its two buttons 220 by 56 with
  # 16 between, centred, their top 62 + 2 + 74 below the card's. In full screen: the X's centre 21 + 27 = 48 in from
  # the right and 12 + 27 = 39 down, the full screen chip's 21 + 54 + 15 + 27 = 117 in; the card 900 by 327 at y 376, its
  # buttons centred at y 376 + 207 + 42 = 625, Keep playing at x 618 + 165 = 783 (the middle less 177) and Quit the game
  # at 1137 (the middle and 177). Wine's window for the game is its client area (no window manager draws a frame), so
  # its geometry is the game's area, in a window as in full screen.
  game=\$(xdotool search --name 'TECHNIKA' 2>/dev/null | tail -n 1)
  [ -n \"\$game\" ] && xdotool windowfocus --sync \"\$game\" 2>/dev/null; xdotool key alt+F4
  sleep 5; snap alt-f4
  player_running || { echo 'FAIL: Alt+F4 ended the game'; exit 1; }
  if player_said \"the game is paused\"; then echo 'FAIL: Alt+F4 held the game still'; exit 1; fi
  echo 'Alt+F4 did nothing'
  # The bar: the pointer from the middle of the game to its top edge, then onto a chip of the bar. The game's place and size read again first: the full screen chip changes them.
  # A length of the overlay's at 720 lines in the game's pixels now: times HEIGHT / 720, rounded half up as lround.
  opx() { echo \$(( (2 * \$1 * HEIGHT + 720) / 1440 )); }
  # The bar's chip (0 the X, 1 full screen): its centre's distance from the right end and from the top.
  bar_chip() {
    eval \$(xdotool getwindowgeometry --shell \"\$game\")
    local size=\$(opx 36) gap=\$(opx 10) margin=\$(opx 14) bar=\$(opx 52)
    xdotool mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 0.5
    xdotool mousemove \$((X + WIDTH / 2)) \$Y; sleep 1
    xdotool mousemove \$((X + WIDTH - margin - size / 2 - \$1 * (size + gap))) \$((Y + (bar - size) / 2 + size / 2)); sleep 1
  }
  # The pointer on the question's button (0 Keep playing, 1 Quit the game), the game's place and size as last read.
  ask_button() {
    local width=\$(opx 600) high=\$((\$(opx 62) + \$(opx 2) + \$(opx 74) + \$(opx 56) + \$(opx 24))) each=\$(opx 220) gap=\$(opx 16)
    local left=\$(( (WIDTH - width) / 2 )) top=\$(( (HEIGHT - high) / 2 ))
    local keep=\$((left + (width - 2 * each - gap) / 2))
    xdotool mousemove \$((X + keep + \$1 * (each + gap) + each / 2)) \$((Y + top + \$(opx 62) + \$(opx 2) + \$(opx 74) + \$(opx 56) / 2)); sleep 1
  }
  # How many times the player has said it switched between full screen and a window.
  switches() { cat \"\$LOCAL\"/OpenDMTQ/*/player.log 2>/dev/null | grep -cE 'player: (full screen|in a window)'; }
  # The full screen chip, twice: to a window, then back, each said in the player's log.
  for way in window full-screen; do
    before=\$(switches); size_before=\$(xdotool getwindowgeometry \"\$game\" | grep Geometry)
    bar_chip 1; snap \"bar-to-\$way\"; xdotool click 1; sleep 3
    wait_for 10 '[ \"\$(switches)\" -gt \"\$before\" ]' || { snap no-switch; echo \"FAIL: the bar's full screen chip did not switch to \$way\"; exit 1; }
    echo \"the bar switched to \$way: \$size_before, now \$(xdotool getwindowgeometry \"\$game\" | grep Geometry)\"
    sleep 2; snap \"in-\$way\"
  done
  # The X asks first, and the game holds still while it asks.
  bar_chip 0; snap bar-quit
  xdotool click 1; sleep 2; snap quit-asked
  player_running || { echo 'FAIL: the X ended the game without asking'; exit 1; }
  echo 'the X asked first'
  wait_for 10 'player_said \"the game is paused\"' || { echo 'FAIL: the question did not hold the game still'; exit 1; }
  echo 'the question held the game still'
  # Keep playing: the game goes on, and still runs well after.
  ask_button 0; snap keep-playing; xdotool click 1
  wait_for 10 'player_said \"the game goes on\"' || { echo 'FAIL: Keep playing did not let the game go on'; exit 1; }
  echo 'the game went on'
  sleep 15; player_running || { echo 'FAIL: the game ended after Keep playing'; exit 1; }
  snap after-keep-playing
  # The X again, and Quit the game.
  bar_chip 0; xdotool click 1; sleep 2
  ask_button 1; snap quit-the-game; xdotool click 1
  wait_for 60 '! player_running' || { snap player-stays; echo 'FAIL: the X did not end the game'; exit 1; }
  echo 'player closed'
  # Back in sight, with how the game went.
  wait_for 20 '[ -n \"\$(xdotool search --onlyvisible --name \"^OpenDMTQ\$\" 2>/dev/null)\" ]' \\
    || { snap launcher-hidden; echo 'FAIL: the launcher did not come back'; exit 1; }
  echo 'launcher back'
  sleep 3; snap launcher-back
  # The Screen page with what Windows says of the display, and the Sound page with the devices the player lists, by the
  # keyboard as a person without a mouse goes: Tab takes the menu first (its ring on PLAY), Right moves the ring along,
  # Enter opens the page. A menu that does not answer shows the same page twice, and the run fails on it below.
  launcher=\$(window '^OpenDMTQ\$'); xdotool windowfocus --sync \"\$launcher\" 2>/dev/null
  xdotool key Tab; sleep 0.5; xdotool key Right Return; sleep 3; snap screen-page
  xdotool key Right Return; sleep 10; snap sound-page
  if [ \"\$(md5sum < /out/\$(printf %02d \$((step - 1)))-screen-page.png | cut -d' ' -f1)\" = \
       \"\$(md5sum < /out/\$(printf %02d \$step)-sound-page.png | cut -d' ' -f1)\" ]; then
    echo 'FAIL: the Screen and Sound clicks showed the same page'; exit 1
  fi
  # The command line's view of the same state, without secrets.
  wine \"\$LOCAL/OpenDMTQ.Client/current/OpenDMTQ-cmd.exe\" --status 2>&1 | tr -d '\r' > /out/status.txt
  # The sound devices as the Sound page asks the player for them (Wine's own, here).
  wine \"\$LOCAL/OpenDMTQ.Client/current/OpenDMTQ-cmd.exe\" --audio-devices 2>&1 | tr -d '\r' >> /out/status.txt
  cat /out/status.txt
  CUR=\"\$LOCAL/OpenDMTQ.Client/current\"
  CMD() { wine \"\$CUR/OpenDMTQ-cmd.exe\" \"\$@\" 2>&1 | tr -d '\r'; }
  # 5. Repair: a file of the player and one of the launcher's own gone, put back from the installed package as they were.
  damaged='player/libEGL.dll _internal/opendmtq_client/assets/fonts/DMTQWide-ExtraBoldItalic.ttf'
  sums=\$(cd \"\$CUR\" && md5sum \$damaged)
  (cd \"\$CUR\" && rm \$damaged)
  CMD --repair | tee /out/repair.txt
  (cd \"\$CUR\" && echo \"\$sums\" | md5sum -c --quiet) || { echo 'FAIL: the repair did not put the files back'; exit 1; }
  grep -q 'Put back 2 files' /out/repair.txt || { echo 'FAIL: the repair did not say what it put back'; exit 1; }
  echo 'repair: both files back as installed'
  # 6. Clear game data: all of the game's but the id this PC plays by. The first game's log and frame are kept aside.
  ID=\$(ls \"\$LOCAL\"/OpenDMTQ/*/data/android_id | head -n 1)
  GAME=\${ID%/data/android_id}
  id_before=\$(md5sum < \"\$ID\")
  cp \"\$GAME/player.log\" /out/player-first.log; cp -r \"\$GAME/data/shots\" /out/shots-first 2>/dev/null
  CMD --clear-game-data --yes | tee /out/clear.txt
  [ \"\$(cd \"\$GAME\" && find . -type f)\" = './data/android_id' ] || { echo 'FAIL: clearing left more than the id'; exit 1; }
  echo 'cleared: the id alone stayed'
  # PLAY again: the game makes its data anew and gets to its menu with the same id.
  click_from_corner 66 31
  wait_for 60 player_running || { snap no-player-again; echo 'FAIL: the player did not start after clearing'; exit 1; }
  wait_for 180 '[ -n \"\$(ls \"\$GAME\"/data/shots 2>/dev/null)\" ]' \\
    || { snap no-menu-again; echo 'FAIL: the game did not get to its menu after clearing'; exit 1; }
  sleep 5; snap game-again
  [ \"\$(md5sum < \"\$ID\")\" = \"\$id_before\" ] || { echo 'FAIL: the game took another id after clearing'; exit 1; }
  echo 'the game started again with the same id'
  game=\$(xdotool search --name 'TECHNIKA' 2>/dev/null | tail -n 1)
  eval \$(xdotool getwindowgeometry --shell \"\$game\")
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 0.5
  # The bar's X, then its question's Quit the game (as in step 4).
  bar_chip 0; xdotool click 1; sleep 2
  ask_button 1; xdotool click 1
  wait_for 60 '! player_running' || { snap player-stays-again; echo 'FAIL: the X did not end the game'; exit 1; }
  wait_for 20 '[ -n \"\$(xdotool search --onlyvisible --name \"^OpenDMTQ\$\" 2>/dev/null)\" ]' \\
    || { snap launcher-hidden-again; echo 'FAIL: the launcher did not come back'; exit 1; }
  sleep 3; snap launcher-back-again
  # 7. Uninstall with the data: refused while the window is open, which would write its settings back.
  CMD --uninstall --delete-data --yes | tee /out/uninstall-refused.txt
  grep -q 'window is open' /out/uninstall-refused.txt || { echo 'FAIL: the uninstall did not wait for the window'; exit 1; }
  xdotool windowfocus --sync \$(window '^OpenDMTQ\$') 2>/dev/null; xdotool key alt+F4
  wait_for 20 '[ -z \"\$(window \"^OpenDMTQ\$\")\" ]' || { snap launcher-stays; echo 'FAIL: the launcher did not close'; exit 1; }
  # The logs, before they go.
  collect
  CMD --uninstall --delete-data --yes | tee /out/uninstall.txt
  wait_for 60 '[ ! -e \"\$LOCAL/OpenDMTQ.Client\" ]' || { echo 'FAIL: the program stayed'; ls \"\$LOCAL/OpenDMTQ.Client\"; exit 1; }
  # Velopack's uninstall hook starts the launcher once more: it must not make the data folder again.
  sleep 3
  [ ! -e \"\$LOCAL/OpenDMTQ\" ] || { echo 'FAIL: the data stayed'; find \"\$LOCAL/OpenDMTQ\" | head; exit 1; }
  shortcut=\$(find / -iname 'OpenDMTQ*.lnk' -path '*drive_c*' 2>/dev/null | head -n 1)
  [ -z \"\$shortcut\" ] || { echo \"FAIL: a shortcut stayed: \$shortcut\"; exit 1; }
  echo 'uninstalled: the program, its shortcut and its data are gone'
  snap uninstalled
  wineserver -k
  echo 'e2e done'
  # The last step's mark: a run that ends early with 0 (its script cut short) is no pass outside.
  touch /out/e2e-done
"
status=$?
# Ended with 0 but short of its last step: a failure.
if [ "$status" = 0 ] && [ ! -f "$OUT/e2e-done" ]; then
  echo "FAIL: the run inside ended before its last step"
  status=1
fi
echo "screens and logs in $OUT"
# The run inside says FAIL and ends with 1 at the step that failed: this script ends the same way.
exit $status
