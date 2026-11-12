#!/bin/bash
# The PC client from end to end under Wine, against a test server:
#   1. the installer as a player gets it: the build's OpenDMTQ-Setup.exe handed to the server (as a release's would
#      be), then downloaded from the server's /windows, signed in, with the server on its end
#   2. installed through its own dialog (Enter on Install), Velopack's setup underneath, the launcher started after
#   3. the launcher's first-start guide: the server the installer brought, the sign-in, the app's download, PLAY
#   4. the player reaching the game's menu (a frame of it saved); the bar sliding down by itself for 3 seconds when the
#      game's picture first shows, and back up, by steps; the handle at the game's top centre (the pointer resting on it
#      brings the bar, a click on its place reaches the game, the game's window keeps the keyboard); the bar at its top
#      edge switching to a window and back; in the window, no buttons of its own, and the bar's minimise (the game held
#      still) and the taskbar's restore (the game going on, no bar by itself), then a minimise with the bar down and a
#      restore as Windows makes them, the window's pop-ups hidden and shown again (the bar stays gone); the bar's X
#      pressed while the bar slides down (it asks all the same); the bar's X asking (the game held still), Keep playing,
#      then the X and Quit the game, the launcher back
#   5. Repair from the command line: a file of the player and one of the launcher put back as they were installed
#   6. Clear game data: the id alone stays; the FPS counter switched on from the command line (the launcher's window
#      closed for it, then opened again), and the game starts again with the same id and gets to its menu, the counter
#      up at its bottom right, a click on its place reaching the game
#   7. Uninstall with the data: refused while the window is open, then the program, its shortcut, its data and its
#      logs (Velopack's and the installer's) gone
# Every step leaves a screenshot of the virtual screen in OUT_DIR, and the logs.
#
#   TEST_SITE=URL TEST_NET=NETWORK TEST_APK=DIR TEST_TOOLS=IMAGE ACCOUNT_FILE=FILE client/tests/windows/e2e.sh BUILD_DIR OUT_DIR
#
# OPENDMTQ_WINE_GPU=1 runs it on WSL's graphics card instead of Mesa's llvmpipe (arm32/wine_gpu.sh), and fails when the
# player's process does not draw through WSL's D3D12 once the game is at its menu.
#
# The test server is a throwaway OpenDMTQ server with its app built, on a Docker network with no way out (as
# tests/closed/game.sh starts one): TEST_SITE is its site's address on the network TEST_NET, TEST_APK its data/apk folder
# (the installer is handed to it there) and TEST_TOOLS the tools image of its version. ACCOUNT_FILE holds a site account
# of it, its ID on the first line and its password on the second: read inside the containers only, never printed or
# copied. BUILD_DIR is client/packaging/windows/build.sh's OUT_DIR.
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
# The renderer: llvmpipe on the CPU, or WSL's graphics card with OPENDMTQ_WINE_GPU=1 (its image and docker's arguments).
. "$ROOT/arm32/wine_gpu.sh"
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
# The image the game runs in: that one, or its twin with Mesa 25 for WSL's graphics card (OPENDMTQ_WINE_GPU=1).
E2E_IMAGE=$(wine_gpu_e2e_image) || exit 1
# The taskbar's part, which Wine has none of (taskbar.c: bringing back a minimised window, reading its title bar's
# buttons), built with the player's toolchain into OUT_DIR.
docker image inspect opendmtq-arm32-windows >/dev/null 2>&1 \
  || docker build -q -t opendmtq-arm32-windows -f "$ROOT/arm32/windows.Dockerfile" "$ROOT/arm32" >/dev/null
docker run --rm --network none -u "$(id -u):$(id -g)" -v "$ROOT/client/tests/windows:/src:ro" -v "$OUT:/out" opendmtq-arm32-windows \
  x86_64-w64-mingw32-clang -O2 -Wall -o /out/taskbar.exe /src/taskbar.c -luser32 \
  || { echo "FAIL: the taskbar's helper did not build" >&2; exit 1; }

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
docker run --rm --network "$NET" -v "$OUT:/out" -v "$ACCOUNT_FILE:/account:ro" -v "$ROOT/arm32/wine_gpu.sh:/wine_gpu.sh:ro" -w /out \
  -e WINEPREFIX=/tmp/wine -e WINEDEBUG=-all -e TZ=Asia/Seoul -e PLAYER_SHOTS=@50 -e PLAYER_TRACE_INPUT=1 -e PLAYER_TRACE_MOTION=1 \
  "${WINE_GPU_ARGS[@]}" "$E2E_IMAGE" bash -c "
  set -u
  # The virtual screen without WSL's variables (on the GPU): it only shows what it is sent.
  env -u GALLIUM_DRIVER -u LD_LIBRARY_PATH Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
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
  # How many presses of the mouse reached the game's window (PLAYER_TRACE_INPUT), and the last one's place there.
  presses() { cat \"\$LOCAL\"/OpenDMTQ/*/player.log 2>/dev/null | grep -c 'input: the mouse.s button down on the game at'; }
  last_press() { cat \"\$LOCAL\"/OpenDMTQ/*/player.log 2>/dev/null | grep 'input: the mouse.s button down on the game at' | tail -n 1 | sed 's/.* at \\([0-9]*,[0-9]*\\) .*/\\1/'; }
  # The bar's coming and going from the game's first picture, as the player says them, with the time each line showed
  # (looked for every 0.2 s): the bar comes down by itself for 3 s, then goes up.
  watch_reveal() {
    local down='' up='' line
    for i in \$(seq 1 1500); do
      line=\$(cat \"\$LOCAL\"/OpenDMTQ/*/player.log 2>/dev/null | grep -n 'the bar comes down (the game.s first picture)\\|the bar goes up' | head -n 2)
      if [ -z \"\$down\" ] && echo \"\$line\" | grep -q 'first picture'; then down=\$(date +%s.%N); import -window root /out/reveal-down.png; fi
      if [ -n \"\$down\" ] && [ -z \"\$up\" ] && echo \"\$line\" | grep -q 'goes up'; then up=\$(date +%s.%N); fi
      [ -n \"\$up\" ] && break
      sleep 0.2
    done
    echo \"\$down \$up\" > /out/reveal.txt
  }
  # How many times the game's window lost the keyboard or stopped being the active window (PLAYER_TRACE_INPUT): the
  # overlay must never be why.
  focus_moves() { cat \"\$LOCAL\"/OpenDMTQ/*/player.log 2>/dev/null | grep -c 'input: the game.s window \\(is no longer active\\|lost the keyboard\\)'; }
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
  watch_reveal &
  sleep 20; snap game-starting
  # The frame PLAYER_SHOTS asks for comes 50 s in: then the game is at its menu.
  sleep 45; snap game-menu
  # What draws the game: the player's first frame names it. Under Wine the name is Wine's stand-in for the card on
  # either renderer, never llvmpipe's own; on the GPU (OPENDMTQ_WINE_GPU=1) the player's process must hold WSL's D3D12
  # and its device (arm32/wine_gpu.sh), or the run fails as one that fell back to the CPU.
  drawn=\$(cat \"\$LOCAL\"/OpenDMTQ/*/player.log 2>/dev/null | grep -m 1 'player: drawn by')
  [ -n \"\$drawn\" ] || { echo 'FAIL: the player did not say what draws the game'; exit 1; }
  echo \"\$drawn\"
  if [ -n \"\${WINE_GPU_IN_CONTAINER:-}\" ]; then
    case \"\$drawn\" in *llvmpipe*) echo 'FAIL: on the GPU the game is drawn by llvmpipe'; exit 1 ;; esac
    . /wine_gpu.sh
    wine_gpu_proof || exit 1
  fi
  # 4. Alt+F4 does nothing: the game runs on, not held still. The pointer at the game's top edge shows the bar; its full
  # screen chip switches to a window and back; its X asks first and holds the game still, Keep playing lets it go on,
  # and the X again with Quit the game ends the game, and the launcher comes back. The overlay's sizes are the game's at
  # 720 lines, times the game's height over 720 (Wine is at 96 dpi): 1.5 in full screen here (1920x1080), 1.125 in the
  # window (1440x810), each length rounded as the player rounds it (opx below). The bar is 74 high and shows for a
  # pointer that rests 150 ms within 4 of the top (y 0 here, for a second); its chips are 40 square, 16 in from the
  # right end and 10 apart, centred in its height (the card within three quarters of the game's width, which neither size
  # reaches). The question's card is 520 wide and 228 high, centred, its two buttons 210 by 48 with 16 between, centred,
  # their top 36 + 28 + 10 + 12 + 20 + 34 = 140 below the card's. In full screen: the X's centre 24 + 30 = 54 in from the
  # right and 25 + 30 = 55 down, the full screen chip's 24 + 60 + 15 + 30 = 129 in; the card 780 by 342 at y 369, its
  # buttons centred at y 369 + 210 + 36 = 615, Keep playing at x 633 + 157 = 790 (the middle less 170) and Quit the game
  # at 1129 (the middle and 169). Wine's window for the game is its client area (no window manager draws a frame), so
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
  # The bar came down by itself once the game's picture showed, for 3 s and its way up, 0.17 s (0.2 s each way for the
  # looks at the log), and went up.
  read down up < /out/reveal.txt
  [ -n \"\$down\" ] || { echo 'FAIL: the bar did not come down when the game first showed'; exit 1; }
  [ -n \"\$up\" ] || { echo 'FAIL: the bar that came down by itself did not go up'; exit 1; }
  held=\$(awk -v a=\"\$down\" -v b=\"\$up\" 'BEGIN { printf \"%.2f\", b - a }')
  awk -v h=\"\$held\" 'BEGIN { exit !(h >= 2.8 && h <= 4.2) }' || { echo \"FAIL: the bar stayed \$held s by itself, not 3 and its way up\"; exit 1; }
  echo \"the bar came down by itself for \$held s when the game first showed\"
  # It slid down and back up by steps, each way said with its steps (PLAYER_TRACE_MOTION): a way of a fifth of a second
  # has a dozen of them at 60 a second, and never fewer than six however Wine's timers fall.
  down_steps=\$(cat \"\$LOCAL\"/OpenDMTQ/*/player.log 2>/dev/null | sed -n 's/.*motion: the bar came down: \\([0-9]*\\) steps.*/\\1/p' | head -n 1)
  up_steps=\$(cat \"\$LOCAL\"/OpenDMTQ/*/player.log 2>/dev/null | sed -n 's/.*motion: the bar went up: \\([0-9]*\\) steps.*/\\1/p' | head -n 1)
  [ \"\${down_steps:-0}\" -ge 6 ] && [ \"\${up_steps:-0}\" -ge 6 ] \
    || { echo \"FAIL: the bar did not slide by steps (\${down_steps:-0} down, \${up_steps:-0} up)\"; exit 1; }
  echo \"the bar slid down in \$down_steps steps and back up in \$up_steps\"
  # The handle's reach at the game's top centre (overlay_scale.h: along its line in the header's top 5 rows at 720 lines,
  # and within 12 of the centre down to its tab's foot lit, 23; the tab drawn there hangs inside it): the pointer resting
  # on it 7 below the top edge brings the bar down; a click on its place, the pointer away at once, reaches the game; the
  # game's window keeps the keyboard throughout.
  eval \$(xdotool getwindowgeometry --shell \"\$game\")
  moves=\$(focus_moves)
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 0.5
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + \$(opx 7))); sleep 1.5; snap handle-rest
  player_said 'the bar comes down (the pointer on the handle)' || { echo 'FAIL: the pointer resting on the handle did not bring the bar'; exit 1; }
  echo 'the pointer resting on the handle brought the bar down'
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 2
  before=\$(presses)
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + \$(opx 7))) click 1 mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 1
  [ \"\$(presses)\" -gt \"\$before\" ] || { echo \"FAIL: a click on the handle's place did not reach the game\"; exit 1; }
  [ \"\$(last_press)\" = \"\$((WIDTH / 2)),\$(opx 7)\" ] || { echo \"FAIL: the handle's click reached the game at \$(last_press)\"; exit 1; }
  [ \"\$(focus_moves)\" = \"\$moves\" ] || { echo 'FAIL: the game lost the keyboard to the handle or the bar'; exit 1; }
  echo \"a click on the handle's place reached the game at \$(last_press), and the game kept the keyboard\"
  sleep 2
  # The bar comes from the handle only after a rest the pointer came to by moving, the game quiet (no press) for 1.5 s:
  # a click there with the pointer still after it brings nothing, nor a press held there; clicks there, then a move
  # away and back and a rest, bring it once the game has been quiet, not before. Counted in the player's log.
  bar_downs() { cat \"\$LOCAL\"/OpenDMTQ/*/player.log 2>/dev/null | grep -c 'the bar comes down (the pointer on the handle)'; }
  downs=\$(bar_downs)
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + \$(opx 7))) click 1; sleep 2.5
  [ \"\$(bar_downs)\" = \"\$downs\" ] || { snap click-still; echo 'FAIL: a click on the handle, the pointer still after it, brought the bar'; exit 1; }
  echo 'a click on the handle with the pointer still after it brought no bar'
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 0.5
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + \$(opx 7))) mousedown 1; sleep 1; xdotool mouseup 1; sleep 2.5
  [ \"\$(bar_downs)\" = \"\$downs\" ] || { snap press-held; echo 'FAIL: a press held on the handle brought the bar'; exit 1; }
  echo 'a press held on the handle brought no bar'
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 0.5
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + \$(opx 7))) click 1 sleep 0.2 click 1 sleep 0.2 click 1 \
    mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)) sleep 0.1 mousemove \$((X + WIDTH / 2)) \$((Y + \$(opx 7)))
  sleep 1
  [ \"\$(bar_downs)\" = \"\$downs\" ] || { snap clicks-then-rest; echo 'FAIL: the bar came within a second of clicks on the game'; exit 1; }
  wait_for 4 '[ \"\$(bar_downs)\" -gt \"\$downs\" ]' || { snap clicks-then-rest; echo 'FAIL: a rest on the handle after clicks did not bring the bar once the game was quiet'; exit 1; }
  echo 'clicks, then a move to the handle and a rest, brought the bar once the game had been quiet for 1.5 s'
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 2
  # The bar's chip (0 the X, 1 full screen, 2 minimise): its centre's distance from the right end and from the top.
  bar_chip() {
    eval \$(xdotool getwindowgeometry --shell \"\$game\")
    local size=\$(opx 40) gap=\$(opx 10) margin=\$(opx 16) bar=\$(opx 74)
    xdotool mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 0.5
    xdotool mousemove \$((X + WIDTH / 2)) \$Y; sleep 1
    xdotool mousemove \$((X + WIDTH - margin - size / 2 - \$1 * (size + gap))) \$((Y + (bar - size) / 2 + size / 2)); sleep 1
  }
  # The pointer on the question's button (0 Keep playing, 1 Quit the game), the game's place and size as last read.
  ask_button() {
    local width=\$(opx 520) high=\$(opx 228) each=\$(opx 210) gap=\$(opx 16)
    local left=\$(( (WIDTH - width) / 2 )) top=\$(( (HEIGHT - high) / 2 ))
    local keep=\$((left + (width - 2 * each - gap) / 2))
    xdotool mousemove \$((X + keep + \$1 * (each + gap) + each / 2)) \$((Y + top + \$(opx 140) + \$(opx 48) / 2)); sleep 1
  }
  # How many times the player has said it switched between full screen and a window.
  switches() { cat \"\$LOCAL\"/OpenDMTQ/*/player.log 2>/dev/null | grep -cE 'player: (full screen|in a window)'; }
  # How many times the bar went up.
  bar_ups() { cat \"\$LOCAL\"/OpenDMTQ/*/player.log 2>/dev/null | grep -c 'player: the bar goes up'; }
  # How many times the player said a line.
  said_count() { cat \"\$LOCAL\"/OpenDMTQ/*/player.log 2>/dev/null | grep -c \"\$1\"; }
  # The full screen chip, twice: to a window, then back, each said in the player's log. The bar stays down for 3 s
  # after each switch, the pointer taken off it at once.
  for way in window full-screen; do
    before=\$(switches); size_before=\$(xdotool getwindowgeometry \"\$game\" | grep Geometry)
    bar_chip 1; snap \"bar-to-\$way\"; ups=\$(bar_ups)
    xdotool click 1 mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 2.2
    [ \"\$(bar_ups)\" = \"\$ups\" ] || { snap bar-left; echo \"FAIL: the bar went up within 2 s of switching to \$way\"; exit 1; }
    echo \"the bar stayed down after switching to \$way, the pointer off it\"
    sleep 1
    wait_for 10 '[ \"\$(switches)\" -gt \"\$before\" ]' || { snap no-switch; echo \"FAIL: the bar's full screen chip did not switch to \$way\"; exit 1; }
    echo \"the bar switched to \$way: \$size_before, now \$(xdotool getwindowgeometry \"\$game\" | grep Geometry)\"
    sleep 2; snap \"in-\$way\"
    [ \"\$way\" = window ] || continue
    # In a window: no buttons of its own on its title bar (Windows draws none without a system menu), as its style says.
    buttons=\$(wine /out/taskbar.exe buttons 2>/dev/null | tr -d '\\r')
    case \"\$buttons\" in 'buttons: none'*) ;; *) echo \"FAIL: the window has buttons of its own: \$buttons\"; exit 1 ;; esac
    echo \"the window has no buttons of its own: \$buttons\"
    # The bar's minimise: the window minimised and the game held still. Then back as the taskbar brings it (taskbar.c
    # sends its restore command, Wine having no taskbar): the game goes on, and the bar does not come by itself.
    paused=\$(said_count 'player: the game is paused'); resumed=\$(said_count 'player: the game goes on')
    bar_chip 2; snap bar-minimise
    xdotool click 1 mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2))
    wait_for 10 'player_said \"player: minimised\"' || { snap not-minimised; echo \"FAIL: the bar's minimise did not minimise the window\"; exit 1; }
    wait_for 10 '[ \"\$(said_count \"player: the game is paused\")\" -gt \"\$paused\" ]' || { echo 'FAIL: minimised, the game did not hold still'; exit 1; }
    echo \"the bar's minimise minimised the window and held the game still\"
    sleep 2; snap minimised; downs=\$(said_count 'player: the bar comes down')
    wine /out/taskbar.exe restore >/dev/null 2>&1
    wait_for 10 'player_said \"player: back from minimised\"' || { snap not-restored; echo \"FAIL: the taskbar's restore did not bring the window back\"; exit 1; }
    wait_for 10 '[ \"\$(said_count \"player: the game goes on\")\" -gt \"\$resumed\" ]' || { echo 'FAIL: back from minimised, the game did not go on'; exit 1; }
    sleep 3.5; snap restored
    [ \"\$(said_count 'player: the bar comes down')\" = \"\$downs\" ] || { snap bar-after-restore; echo 'FAIL: the bar came down by itself after the restore'; exit 1; }
    echo 'back from the taskbar: the game went on, and the bar did not come by itself'
    # Windows hides the pop-ups a window owns when the window is minimised and shows them again when it is back,
    # whatever the program did with them meanwhile; Wine does neither, so taskbar.c does both, around a minimise and a
    # restore made as the taskbar makes them. Minimised with the bar down, the bar goes up; back, its last picture must
    # not be over the game (the overlay holds it gone: a click on its X there would reach the game's own X).
    mins=\$(said_count 'player: minimised'); backs=\$(said_count 'player: back from minimised'); ups=\$(bar_ups)
    bar_chip 2; downs=\$(said_count 'player: the bar comes down')
    [ \"\$(wine /out/taskbar.exe shown OpenDMTQBar 2>/dev/null | tr -d '\\r')\" = shown ] || { snap bar-not-down; echo 'FAIL: the bar did not come down at the top edge'; exit 1; }
    wine /out/taskbar.exe minimise >/dev/null 2>&1
    wait_for 10 '[ \"\$(said_count \"player: minimised\")\" -gt \"\$mins\" ]' || { snap not-minimised-2; echo \"FAIL: the taskbar's minimise did not minimise the window\"; exit 1; }
    wait_for 10 '[ \"\$(bar_ups)\" -gt \"\$ups\" ]' || { echo 'FAIL: minimised with the bar down, the bar did not go up'; exit 1; }
    xdotool mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 1
    wine /out/taskbar.exe restore >/dev/null 2>&1
    wait_for 10 '[ \"\$(said_count \"player: back from minimised\")\" -gt \"\$backs\" ]' || { snap not-restored-2; echo \"FAIL: the taskbar's restore did not bring the window back\"; exit 1; }
    sleep 1; snap restored-bar-gone
    [ \"\$(wine /out/taskbar.exe shown OpenDMTQBar 2>/dev/null | tr -d '\\r')\" = hidden ] || { echo \"FAIL: back from minimised, the bar's last picture was over the game again (Windows showed the window's pop-ups again)\"; exit 1; }
    [ \"\$(said_count 'player: the bar comes down')\" = \"\$downs\" ] || { echo 'FAIL: the bar came down by itself after the restore'; exit 1; }
    echo 'minimised with the bar down and back, its pop-ups hidden and shown again as Windows does: the bar stayed gone'
  done
  # A chip pressed while the bar slides down, the pointer still, and let go 90 ms later: by then the bar's way has moved
  # the chip from under the pointer, and the click still acts (its press and its release are read where the bar was at
  # the press). The X here: its question comes, and Esc keeps playing. taskbar.c presses and lets go as a mouse does once
  # half the chip is in sight with the way still going, the pointer resting at the top edge over it meanwhile; a way
  # Wine stepped past that place is tried again, up to three times.
  eval \$(xdotool getwindowgeometry --shell \"\$game\")
  asked=\$(said_count 'player: glass: the question over'); resumed=\$(said_count 'player: the game goes on')
  chip_x=\$((WIDTH - \$(opx 16) - \$(opx 40) / 2)); chip_top=\$(( (\$(opx 74) - \$(opx 40)) / 2 ))
  for try in 1 2 3; do
    xdotool mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 1.5
    ( wine /out/taskbar.exe slide-click \$chip_x \$chip_top \$(opx 40) \$((\$(opx 74) + \$(opx 28))) > /out/slide-click.txt 2>&1 & )
    sleep 1.5; xdotool mousemove \$((X + chip_x)) \$Y
    wait_for 6 'grep -q \"pressed\\|missed\" /out/slide-click.txt' || true
    grep -q missed /out/slide-click.txt || break
  done
  wait_for 10 '[ \"\$(said_count \"player: glass: the question over\")\" -gt \"\$asked\" ]' \\
    || { snap slide-click; echo \"FAIL: the X pressed as the bar slid down did not ask: \$(tr -d '\\r' < /out/slide-click.txt)\"; exit 1; }
  echo \"the X pressed as the bar slid down asked: \$(tr -d '\\r' < /out/slide-click.txt)\"
  xdotool key Escape
  wait_for 10 '[ \"\$(said_count \"player: the game goes on\")\" -gt \"\$resumed\" ]' || { echo 'FAIL: Esc on the question did not let the game go on'; exit 1; }
  xdotool mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 2
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
  # The FPS counter on, from the command line: refused while the launcher's window is open (it would write its own
  # copy over it), so the window closes first and opens again after.
  xdotool windowfocus --sync \$(window '^OpenDMTQ\$') 2>/dev/null; xdotool key alt+F4
  wait_for 20 '[ -z \"\$(window \"^OpenDMTQ\$\")\" ]' || { snap launcher-stays-for-set; echo 'FAIL: the launcher did not close for --set'; exit 1; }
  CMD --set show_fps=on | tee /out/set-counter.txt
  grep -q 'show_fps=on, fps_position=bottom_right' /out/set-counter.txt || { echo 'FAIL: --set show_fps=on did not put the counter on at the bottom right'; exit 1; }
  wine \"\$CUR/OpenDMTQ.exe\" > /out/launcher-again.log 2>&1 &
  wait_for 60 '[ -n \"\$(xdotool search --onlyvisible --name \"^OpenDMTQ\$\" 2>/dev/null)\" ]' \\
    || { snap launcher-not-again; echo 'FAIL: the launcher did not open again'; exit 1; }
  sleep 6; snap launcher-again
  echo 'the FPS counter is on (--set show_fps=on), the launcher open again'
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
  # The counter up at its bottom right (88 by 44, 8 in from the right and the foot, at 720 lines); a click well inside
  # it (52 in from the right and 30 up from the foot at 720), the pointer away at once, reaches the game, which keeps
  # the keyboard.
  player_said 'the frame counter is up' || { snap no-counter; echo 'FAIL: the FPS counter did not come up'; exit 1; }
  before=\$(presses); moves=\$(focus_moves)
  cx=\$((WIDTH - \$(opx 52))) cy=\$((HEIGHT - \$(opx 30)))
  xdotool mousemove \$((X + cx)) \$((Y + cy)) click 1 mousemove \$((X + WIDTH / 2)) \$((Y + HEIGHT / 2)); sleep 1
  [ \"\$(presses)\" -gt \"\$before\" ] || { snap counter-click; echo \"FAIL: a click on the counter's place did not reach the game\"; exit 1; }
  [ \"\$(last_press)\" = \"\$cx,\$cy\" ] || { echo \"FAIL: the counter's click reached the game at \$(last_press)\"; exit 1; }
  [ \"\$(focus_moves)\" = \"\$moves\" ] || { echo 'FAIL: the game lost the keyboard to the counter'; exit 1; }
  echo \"a click on the counter's place reached the game at \$(last_press), and the game kept the keyboard\"
  snap counter-up
  # The bar's X, then its question's Quit the game (as in step 4); the counter hides while the question holds the game.
  bar_chip 0; xdotool click 1; sleep 2
  wait_for 10 'player_said \"the frame counter hides while the game is held\"' || { snap counter-under-question; echo 'FAIL: the counter did not hide while the question held the game'; exit 1; }
  echo 'the counter hid while the question held the game'
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
  # Its logs elsewhere went too: Velopack's of OpenDMTQ (its uninstall's own went with the program's folder), and the
  # installer's in the temporary folder.
  TEMPDIR=\$(winepath -u 'C:\\users\\root\\AppData\\Local\\Temp' 2>/dev/null)
  left=\$(ls \"\$LOCAL\"/velopack/velopack_OpenDMTQ.Client.log* \"\$TEMPDIR\"/OpenDMTQ-setup*.log* 2>/dev/null)
  [ -z \"\$left\" ] || { echo \"FAIL: logs stayed: \$left\"; exit 1; }
  shortcut=\$(find / -iname 'OpenDMTQ*.lnk' -path '*drive_c*' 2>/dev/null | head -n 1)
  [ -z \"\$shortcut\" ] || { echo \"FAIL: a shortcut stayed: \$shortcut\"; exit 1; }
  echo 'uninstalled: the program, its shortcut, its data and its logs are gone'
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
