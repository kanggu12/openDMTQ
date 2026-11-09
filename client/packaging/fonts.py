"""Make the launcher's wide face from the site's: DMTQ Wide (server/portal/fonts) as TrueType files, which Tk and Pillow
read where a browser reads WOFF2.

  python3 client/packaging/fonts.py

Writes DMTQWide-ExtraBold.ttf (headings and labels in Tk) and DMTQWide-ExtraBoldItalic.ttf (the leaning titles and the
wordmark, drawn as pictures) into client/opendmtq_client/assets/fonts. The glyphs are the site's as they are: only the
container changes, so the files keep the site's name for its cut of Saira (fonts/README.md there).
"""

import os
import sys

from fontTools.ttLib import TTFont

# The repository, from this file's place in it.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# The site's fonts, and where the launcher keeps its own.
SITE = os.path.join(ROOT, "server", "portal", "fonts")
OUT = os.path.join(ROOT, "client", "opendmtq_client", "assets", "fonts")
# Each WOFF2 of the site and the TrueType file it becomes.
FILES = (("dmtq-wide-800.woff2", "DMTQWide-ExtraBold.ttf"), ("dmtq-wide-italic-800.woff2", "DMTQWide-ExtraBoldItalic.ttf"))


def main():
    for source, target in FILES:
        font = TTFont(os.path.join(SITE, source))
        # Plain TrueType: no WOFF2 container, the same tables.
        font.flavor = None
        font.save(os.path.join(OUT, target))
        print("%s -> %s" % (source, target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
