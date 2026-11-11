#!/bin/bash
# Screenshots and layout measurements of the launcher, in a container with a virtual screen and no network. Nothing
# opens on the developer's screen. Usage: client/tests/ui/run.sh OUT_DIR [lang ...] (default: en ko)
# Window sizes: the default 1180x760, the smallest allowed 960x640, and a large 1600x1000, at 100 % scaling; then the
# default at 200 % (2360x1520, on a 3840x2160 screen at 192 dpi), where every picture is drawn at twice the pixels.
# OUT_DIR/sheet-<lang>.png puts every screenshot of a language on one page.
set -u
OUT=$(realpath -m "${1:?usage: run.sh OUT_DIR [lang ...]}")
shift
LANGS=${*:-en ko}
# OPENDMTQ_REPO points the run at another copy of the repository.
REPO=${OPENDMTQ_REPO:-$(cd "$(dirname "$0")/../../.." && pwd)}
mkdir -p "$OUT"
# The image is small and built once (client/tests/ui/Dockerfile).
docker image inspect opendmtq-client-ui:local >/dev/null 2>&1 \
  || docker build -q -t opendmtq-client-ui:local "$REPO/client/tests/ui" >/dev/null
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -v "$REPO:/src:ro" -v "$OUT:/out" -w /src/client \
  opendmtq-client-ui:local bash -c "
    Xvfb :99 -screen 0 1920x1200x24 -nolisten tcp >/dev/null 2>&1 &
    # A second screen at twice the pixels to the inch, as Windows draws at 200 % scaling.
    Xvfb :98 -screen 0 3840x2160x24 -dpi 192 -nolisten tcp >/dev/null 2>&1 &
    sleep 1
    # The fonts Tk uses, known to fontconfig the way Windows loads them privately (the leaning face is drawn into
    # pictures only, as on Windows).
    mkdir -p /usr/local/share/fonts/opendmtq
    for f in DMTQWide-ExtraBold Pretendard-Regular Pretendard-SemiBold Pretendard-Bold MaterialIcons-Regular; do
      cp opendmtq_client/assets/fonts/\$f.ttf /usr/local/share/fonts/opendmtq/
    done
    fc-cache -f >/dev/null
    status=0
    for lang in $LANGS; do
      for size in 1180x760 960x640 1600x1000; do
        python tests/ui/shots.py --out /out --lang \$lang --size \$size || status=1
      done
      DISPLAY=:98 python tests/ui/shots.py --out /out --lang \$lang --size 2360x1520 || status=1
      # The keyboard alone: Tab's order, a control it reaches out of view brought into view, redraws in place.
      python tests/ui/keyboard.py --lang \$lang || status=1
      python tests/ui/sheet.py /out \$lang || status=1
    done
    exit \$status"
