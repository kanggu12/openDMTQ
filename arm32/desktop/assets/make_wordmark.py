"""The OpenDMTQ wordmark for the player's bar over the game (arm32/desktop/overlay_win32.cpp), drawn by the launcher's own
code (client/opendmtq_client/art.py wordmark(): OPEN small and spaced over its lime line, DMTQ in the leaning face in
chrome with the Q lit), as the launcher's header draws it, without the version beside it. Transparent PNGs, one for
each of the overlay's scales from 100 % to 400 %, beside this script:

    bar-wordmark-<percent>.png

The bar is 74 pixels high at 720 lines, the launcher's header 64: the mark is the header's (26) times 74 / 64, 30 at
100 %, so that it sits in the bar as the header's sits in its header. The player draws the picture of its scale, or the
next larger one drawn down to it (arm32/desktop/overlay_glass.cpp), and the bundle carries them in images\\ beside it
(arm32/bundle_windows.sh).

Run from the repository's root with the launcher's Python and its fonts, as its screens are made (client/tests/ui):

    docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/src" -w /src/client opendmtq-client-ui:local \\
      python ../arm32/desktop/assets/make_wordmark.py
"""
import os
import sys

# The launcher's package, from the repository (client/opendmtq_client), whatever the folder this runs from.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "client"))

from opendmtq_client import art  # noqa: E402

# The launcher header's mark (art.brand's) and the two bars' heights at 100 %: the header's 64, the bar's 74 at 720.
HEADER_MARK, HEADER_HEIGHT, BAR_HEIGHT = 26, 64, 74
MARK = round(HEADER_MARK * BAR_HEIGHT / HEADER_HEIGHT)
# The overlay's scales a bar is drawn at (the game's own, its height over 720 lines, never below half of Windows' scale):
# each picture is drawn for its own, a scale between two takes the larger drawn down, and a scale below 100 % (a small
# window: down to 50 %) the 100 % picture drawn down.
PERCENTS = (100, 125, 150, 175, 200, 250, 300, 400)


def main():
    for percent in PERCENTS:
        picture = art.wordmark(MARK, percent / 100)
        path = os.path.join(HERE, "bar-wordmark-%d.png" % percent)
        # Straight alpha, as PNG holds it; nothing else in the file (no time, no text chunks), so the same run makes the
        # same bytes.
        picture.save(path, optimize=True)
        print("%s %dx%d" % (os.path.relpath(path, ROOT), picture.width, picture.height))


if __name__ == "__main__":
    main()
