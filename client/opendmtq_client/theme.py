"""Colours, fonts and sizes of the launcher: the OpenDMTQ site's look (server/portal/style.css) in a window.

The surfaces are the site's neutral gunmetal, never tinted by one brand colour. Colour marks a section or a meaning, as
the site colours its sections: the site's lime for PLAY, the timeline's cyan for the picture and the sound, the
rankings' violet for being online, and the admin pages' amber for the tools. The checks say "fine", "will change" and
"problem" in the site's own lime, yellow and red.

Titles lean in the wide face, as the TECHNIKA Q logo and the site's wordmark do. Fonts are bundled under open licences:
DMTQ Wide (the site's cut of Saira) for Latin headings and labels, Pretendard for text in both languages, Material Icons
for glyphs (assets/fonts/README.md).
"""

import os
import sys

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONT_DIR = os.path.join(ASSETS, "fonts")

# Surfaces, darkest first: the site's field, deck and rails, and the seam between them.
BG = "#11151a"          # the window behind everything (the site's --field)
SIDEBAR = "#0d1014"     # the menu column, a step darker than the page
PANEL = "#1a1f25"       # cards and the bottom bar (--deck)
PANEL_HI = "#21272e"    # a hovered or chosen row, the top of a card (--deck-top)
RAIL = "#272e36"        # quiet metal: buttons and tracks (--rail)
RAIL_UP = "#323a44"     # the same under the pointer (--rail-up)
LINE = "#3a434d"        # 1-pixel seams and rules (--seam)
FIELD = "#0b0e12"       # inside inputs and lists

# Text.
TEXT = "#eef2f6"        # body text (--chalk)
MUTED = "#aeb8c3"       # hints under a setting (--ash: 7:1 and more on the deck)
FAINT = "#8d98a4"       # disabled text and small labels (4.5:1 and more on every surface they sit on)
INK = "#0b0e12"         # words on a bright colour

# What the site's screens say with colour.
OK = "#8cf23d"          # fine (--ok), and the site's own accent
WARN = "#ffcf3d"        # something PLAY or the launcher will change, a warning (--warn)
BAD = "#ff5f72"         # a problem, an error, removing for good (--bad)
CYAN = "#6fd6ff"        # the keyboard's place (focus rings), and the picture and sound pages (--cyan)
VIOLET = "#c491ff"      # online: the server, signing in, the app (the site's rankings)
AMBER = "#ffb13d"       # the tools: help and the launcher's own page (the site's admin pages)

# A section's colour lights its header's shards, its title's tail, its menu entry and its main buttons: the accent,
# a bright and a deep shade for the shards, the fill of its main buttons and the ink that reads on that fill.
SECTION_COLOURS = {
    "home": {"accent": OK, "light": "#5fbf1f", "deep": "#1f3a08", "fill": OK, "ink": "#0d1c04"},
    "songs": {"accent": CYAN, "light": "#2fa8e0", "deep": "#0a3048", "fill": CYAN, "ink": "#04202e"},
    "ranking": {"accent": VIOLET, "light": "#9a62f0", "deep": "#2d1257", "fill": VIOLET, "ink": "#1b0a34"},
    "admin": {"accent": AMBER, "light": "#e3961f", "deep": "#4f3306", "fill": AMBER, "ink": "#2a1700"},
}
# Which section each page of the launcher belongs to.
PAGE_SECTIONS = {"play": "home", "screen": "songs", "sound": "songs", "controls": "songs", "online": "ranking",
                 "help": "admin", "about": "admin"}


def section_colours(page):
    """The colours of the section a page belongs to (PLAY's lime for anything unknown)."""
    return SECTION_COLOURS[PAGE_SECTIONS.get(page, "home")]


# Material Icons code points used by the launcher (a test checks each against the bundled font).
ICON = {
    "play": "", "screen": "", "sound": "", "controls": "", "help": "", "about": "",
    "ok": "", "warn": "", "error": "", "info": "", "folder": "", "refresh": "",
    "restore": "", "file": "", "language": "", "update": "", "chevron": "",
    "back": "", "next": "", "check": "", "radio_on": "", "radio_off": "",
    "touch": "", "history": "", "online": "", "person": "", "delete": "",
    "download": "", "server": "", "keyboard": "", "logout": "", "login": "",
    "link": "", "lock": "", "fullscreen": "", "speed": "", "computer": "",
    "volume_off": "", "timer": "", "account": "",
}

# Bundled font files Tk uses, and the family names Windows and fontconfig give them. The leaning wide face is drawn into
# pictures only (art.py), so it is not among them: two faces of one family and style would be one too many for Windows.
FONT_FILES = ("DMTQWide-ExtraBold.ttf", "Pretendard-Regular.ttf", "Pretendard-SemiBold.ttf", "Pretendard-Bold.ttf",
              "MaterialIcons-Regular.ttf")
DISPLAY = "DMTQ Wide"
TEXT_FONT = "Pretendard"
TEXT_BOLD = "Pretendard SemiBold"
ICONS = "Material Icons"
# Files for the titles drawn as pictures (art.py): Latin in the leaning wide face, Korean in Pretendard Bold (leant).
WIDE_FILE = os.path.join(FONT_DIR, "DMTQWide-ExtraBold.ttf")
WIDE_ITALIC_FILE = os.path.join(FONT_DIR, "DMTQWide-ExtraBoldItalic.ttf")
HANGUL_TITLE_FILE = os.path.join(FONT_DIR, "Pretendard-Bold.ttf")
TEXT_BOLD_FILE = os.path.join(FONT_DIR, "Pretendard-SemiBold.ttf")
ICON_FILE = os.path.join(FONT_DIR, "MaterialIcons-Regular.ttf")


def register_fonts():
    """Make the bundled fonts usable by Tk in this process only (nothing is installed on the PC).

    On Windows each file is added as a private font of this process. On Linux (development and the test containers)
    the files must already be known to fontconfig; the containers copy them in.
    """
    if sys.platform != "win32":
        return
    import ctypes
    # FR_PRIVATE: only this process sees the font, and it goes away when the launcher closes.
    fr_private = 0x10
    for name in FONT_FILES:
        ctypes.windll.gdi32.AddFontResourceExW(os.path.join(FONT_DIR, name), fr_private, 0)


class Fonts:
    """The named fonts, sized for the window's DPI and chosen for the language.

    DMTQ Wide has no Hangul, so in Korean the headings use Pretendard SemiBold at a size that matches the wide face's
    height; Latin-only labels (PLAY, the guide's step names) stay wide in both languages.
    """

    def __init__(self, root, language):
        import tkinter.font as tkfont
        korean = language == "ko"
        section = (TEXT_BOLD, 10) if korean else (DISPLAY, 8)
        self.title = tkfont.Font(root, family=TEXT_BOLD if korean else DISPLAY, size=21 if korean else 18)
        kicker = (TEXT_BOLD, 9) if korean else (DISPLAY, 8)
        self.kicker = tkfont.Font(root, family=kicker[0], size=kicker[1])            # the small line above a title
        self.section = tkfont.Font(root, family=section[0], size=section[1])         # section headings
        self.display = tkfont.Font(root, family=DISPLAY, size=10)                    # Latin labels in the site's style
        self.display_big = tkfont.Font(root, family=DISPLAY, size=17)                # PLAY
        self.body = tkfont.Font(root, family=TEXT_FONT, size=10)                     # text
        self.body_bold = tkfont.Font(root, family=TEXT_BOLD, size=10)                # labels and buttons
        self.small = tkfont.Font(root, family=TEXT_FONT, size=9)                     # hints
        self.nav = tkfont.Font(root, family=TEXT_BOLD if korean else DISPLAY, size=11 if korean else 9)  # menu
        self.icon = tkfont.Font(root, family=ICONS, size=15)                         # menu and check glyphs
        self.icon_small = tkfont.Font(root, family=ICONS, size=12)                   # glyphs inside rows
        tab = (TEXT_BOLD, 10) if korean else (DISPLAY, 8)
        self.dialog_tab = tkfont.Font(root, family=tab[0], size=tab[1])              # a dialog's title tab
        self.dialog_title = tkfont.Font(root, family=TEXT_BOLD, size=13)             # a dialog's question
        self.dialog_button = tkfont.Font(root, family=TEXT_BOLD, size=10)            # a dialog's buttons
        self.dialog_glyph = tkfont.Font(root, family=ICONS, size=24)                 # the glyph in its ring
        self.language = language


def scale_of(root):
    """Pixels per 1/96 inch: 1.0 at 100 % Windows scaling, 1.5 at 150 %."""
    return max(1.0, root.winfo_fpixels("1i") / 96.0)
