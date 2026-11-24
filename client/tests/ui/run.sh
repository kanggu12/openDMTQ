#!/bin/bash
# Screenshots and layout measurements of the launcher, in containers with a virtual screen and no network. Nothing
# opens on the developer's screen. Usage: client/tests/ui/run.sh OUT_DIR [lang ...] (default: en ko)
# Window sizes: the default 1180x760, the smallest allowed 960x640, and a large 1600x1000, at 100 % scaling; then the
# default at 200 % (2360x1520, on a 3840x2160 screen at 192 dpi), where every picture is drawn at twice the pixels.
# OUT_DIR/sheet-<lang>.png puts every screenshot of a language on one page.
# Each check of a language (a window size's screenshots, the keyboard, the flicker film...) is a part that runs in a
# container of its own, JOBS of them side by side (default: half the processors, 8 at most), and each part's output is
# printed whole, in the order below, once it and the parts before it are done. The flicker film runs first and alone: it
# counts the frames a change shows, which a machine busy with the other parts would add to. QUIET_DONE=<file> is made
# once it is over (tests/qa.sh starts its other steps then). ONLY="flicker" runs those parts alone, SKIP="flicker" all
# but those; the parts are shots, keyboard, flicker, notices, sound, states, rows, setup and sheet.
set -u
OUT=$(realpath -m "${1:?usage: run.sh OUT_DIR [lang ...]}")
shift
LANGS=${*:-en ko}
# OPENDMTQ_REPO points the run at another copy of the repository.
REPO=${OPENDMTQ_REPO:-$(cd "$(dirname "$0")/../../.." && pwd)}
# Half the processors (each part keeps about one busy), at least one and at most eight.
JOBS=${JOBS:-$(($(getconf _NPROCESSORS_ONLN) / 2))}
[ "$JOBS" -ge 1 ] || JOBS=1
[ "$JOBS" -le 8 ] || JOBS=8
# The containers' names: this run's own (NAME_PREFIX keeps another run's apart, the process number another of this one).
NAME=${NAME_PREFIX:-odq}-client-ui-$$
# A part that has not ended after this many seconds fails (a dialog nobody answers would wait for ever): several times
# what the longest takes on a busy machine.
PART_TIMEOUT=${PART_TIMEOUT:-900}
mkdir -p "$OUT"
# Each part's output and exit status, until it is printed.
PARTS=$(mktemp -d)
# The image is small and built once (client/tests/ui/Dockerfile).
docker image inspect opendmtq-client-ui:local >/dev/null 2>&1 \
  || docker build -q -t opendmtq-client-ui:local "$REPO/client/tests/ui" >/dev/null

# The parts, in the order their output is printed: each one's language, kind, screen and command (from client/).
P_LANG=() P_KIND=() P_SCREEN=() P_CMD=()
part() {
  P_LANG+=("$1") P_KIND+=("$2") P_SCREEN+=("$3") P_CMD+=("$4")
}
for lang in $LANGS; do
  for size in 1180x760 960x640 1600x1000; do
    part "$lang" shots :99 "python tests/ui/shots.py --out /out --lang $lang --size $size"
  done
  part "$lang" shots :98 "python tests/ui/shots.py --out /out --lang $lang --size 2360x1520"
  # The keyboard alone: Tab's order, a control it reaches out of view brought into view, redraws in place.
  part "$lang" keyboard :99 "python tests/ui/keyboard.py --lang $lang"
  # A setting changed draws only what it changes: the screen filmed, no frame of a page half drawn.
  part "$lang" flicker :99 "python tests/ui/flicker.py --lang $lang --report /out/flicker-$lang.txt"
  # Each change of the server, the sign-in, the app and the launcher's version said as it comes, every time.
  part "$lang" notices :99 "python tests/ui/notices.py --lang $lang"
  # The sound the in-game menu sets during a game stays after it: on the Sound page, and at the next PLAY.
  part "$lang" sound :99 "python tests/ui/sound_back.py --lang $lang"
  # The states the pages' walk never reaches: the connection test's every verdict, the server gone under an open
  # window, the sign-in refused, PLAY while the server builds its app, the start after an update.
  part "$lang" states :99 "python tests/ui/states.py --out /out --lang $lang"
  # A field and its buttons on one height and middle, under their words; the settings' controls from one line.
  part "$lang" rows :99 "python tests/ui/rows.py --lang $lang"
  part "$lang" rows :98 "python tests/ui/rows.py --lang $lang --size 2360x1520"
  # The installer's window: every page at 100 %, at 200 % and on a small screen.
  part "$lang" setup :99 "python tests/ui/setup_shots.py --out /out --lang $lang"
  part "$lang" setup :98 "python tests/ui/setup_shots.py --out /out --lang $lang --tag 200"
  part "$lang" setup :97 "python tests/ui/setup_shots.py --out /out --lang $lang --tag small"
  # Every screenshot of the language on one page: after all the parts that take them.
  part "$lang" sheet :99 "python tests/ui/sheet.py /out $lang"
done

# Whether a part of this kind runs at all (ONLY, SKIP).
wanted() {
  if [ -n "${ONLY:-}" ] && ! grep -qw -- "$1" <<<"$ONLY"; then
    return 1
  fi
  ! { [ -n "${SKIP:-}" ] && grep -qw -- "$1" <<<"$SKIP"; }
}

# Each part's container: three virtual screens (the usual one at 96 dots to the inch, Windows' 100 %, where Xvfb's own
# 100 would scale the launcher by 1.04 and no window would be the size asked; one at twice that, as Windows draws at
# 200 % scaling; a small one at 100 %, as a netbook's, for the installer's window), the fonts Tk uses known to
# fontconfig the way Windows loads them privately (the leaning face and the icons are drawn into pictures only, from
# their files, as on Windows: a character a text font lacks then falls back as Windows' does, never to the icons), each
# screen waited for until it answers, then the part's command.
PREP='Xvfb :99 -screen 0 1920x1200x24 -dpi 96 -nolisten tcp >/dev/null 2>&1 &
Xvfb :98 -screen 0 3840x2160x24 -dpi 192 -nolisten tcp >/dev/null 2>&1 &
Xvfb :97 -screen 0 800x480x24 -dpi 96 -nolisten tcp >/dev/null 2>&1 &
mkdir -p /usr/local/share/fonts/opendmtq
for f in DMTQWide-ExtraBold Pretendard-Regular Pretendard-SemiBold Pretendard-Bold; do
  cp "opendmtq_client/assets/fonts/$f.ttf" /usr/local/share/fonts/opendmtq/
done
fc-cache -f >/dev/null
for d in 99 98 97; do
  for _ in $(seq 100); do xdpyinfo -display ":$d" >/dev/null 2>&1 && break; sleep 0.1; done
done'

# A part in the background: its output and status into PARTS/<number>.
start() {
  local i=$1
  (
    docker run --rm --name "$NAME-$i" --network none -e PYTHONDONTWRITEBYTECODE=1 -e DISPLAY="${P_SCREEN[$i]}" \
      -v "$REPO:/src:ro" -v "$OUT:/out" -w /src/client opendmtq-client-ui:local \
      bash -c "$PREP
timeout -k 10 $PART_TIMEOUT ${P_CMD[$i]}
status=\$?
[ \$status -ne 124 ] || echo 'FAIL ${P_KIND[$i]} ${P_LANG[$i]}: no end within $PART_TIMEOUT s (${P_CMD[$i]})'
exit \$status" > "$PARTS/$i.out" 2>&1
    echo $? > "$PARTS/$i.status.tmp"
    # Whole, or not there: the status is read as soon as the file is.
    mv "$PARTS/$i.status.tmp" "$PARTS/$i.status"
  ) &
}

# The parts that ended, printed in order up to the first one still to come; each status counted once.
SHOWN=0
STATUS=0
show() {
  while [ "$SHOWN" -lt "${#P_CMD[@]}" ]; do
    if ! wanted "${P_KIND[$SHOWN]}"; then
      SHOWN=$((SHOWN + 1))
      continue
    fi
    [ -f "$PARTS/$SHOWN.status" ] || return 0
    cat "$PARTS/$SHOWN.out"
    [ "$(cat "$PARTS/$SHOWN.status")" = 0 ] || STATUS=1
    SHOWN=$((SHOWN + 1))
  done
}

# The parts given, JOBS at a time, until every one has ended.
run() {
  local i running
  for i in "$@"; do
    while :; do
      running=0
      for j in "$@"; do
        [ -f "$PARTS/$j.started" ] && [ ! -f "$PARTS/$j.status" ] && running=$((running + 1))
      done
      [ "$running" -lt "$JOBS" ] && break
      show
      sleep 0.2
    done
    touch "$PARTS/$i.started"
    start "$i"
  done
  for i in "$@"; do
    while [ ! -f "$PARTS/$i.status" ]; do
      show
      sleep 0.2
    done
  done
  show
}

# Stopped half-way: the parts' containers go with it.
cleanup() {
  local i
  for i in "${!P_CMD[@]}"; do
    [ -f "$PARTS/$i.started" ] && [ ! -f "$PARTS/$i.status" ] && docker rm -f "$NAME-$i" >/dev/null 2>&1
  done
  rm -rf "$PARTS"
}
trap cleanup EXIT

# The film first, one language after the other, with nothing else of this run beside it.
films=()
for i in "${!P_CMD[@]}"; do
  [ "${P_KIND[$i]}" = flicker ] && wanted flicker && films+=("$i")
done
for i in ${films[@]+"${films[@]}"}; do
  JOBS=1 run "$i"
done
[ -z "${QUIET_DONE:-}" ] || touch "$QUIET_DONE"
# Then the rest side by side, the screenshots first (the longest), the sheets once every picture is taken.
first=() later=() sheets=()
for i in "${!P_CMD[@]}"; do
  wanted "${P_KIND[$i]}" || continue
  case ${P_KIND[$i]} in
    flicker) ;;
    shots) first+=("$i") ;;
    sheet) sheets+=("$i") ;;
    *) later+=("$i") ;;
  esac
done
# (An empty list expands to nothing, on the oldest bash too.)
[ $((${#first[@]} + ${#later[@]})) -eq 0 ] || run ${first[@]+"${first[@]}"} ${later[@]+"${later[@]}"}
[ "${#sheets[@]}" -eq 0 ] || run "${sheets[@]}"
exit "$STATUS"
