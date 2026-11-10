"""Colours, fonts and sizes of the launcher: the OpenDMTQ site's look (server/portal/style.css) in a window.

The surfaces are the site's neutral gunmetal, never tinted by one brand colour. Colour says what something is: the
site's lime for what is in use, the main action and what is fine; its yellow and red for a warning and a problem; cyan
for the keyboard's place.

Page titles, the menu and the guide's numerals are in the wide face, as the site's are. Fonts are bundled under open
licences: DMTQ Wide (the site's cut of Saira) for those, Pretendard for text in both languages, Material Icons for the
few glyphs left (assets/fonts/README.md).
"""

import os
import sys

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONT_DIR = os.path.join(ASSETS, "fonts")

# Surfaces, darkest first: the site's field, deck and rails, and the seam between them.
BG = "#11151a"          # the window behind everything (the site's --field)
SIDEBAR = BG            # the header bar: it melts into the page, as the site's does at the page's top
PANEL = "#1a1f25"       # cards (--deck)
PANEL_HI = "#21272e"    # a hovered row (--deck-top)
RAIL = "#272e36"        # quiet metal: tabs and tracks (--rail)
RAIL_UP = "#323a44"     # buttons, and tabs under the pointer (--rail-up)
LINE = "#3a434d"        # 1-pixel seams: an input's edge (--seam)
FIELD = "#0e1216"       # inside inputs and lists (the site's .input)
STRIP = "#151a20"       # the strip along the window's foot with PLAY (the site's bar once a page has moved)
DIVIDER = "#2b3035"     # the faint line between rows in a card (white at 7.5 % on the deck)

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
# Which section each page of the launcher belongs to: all of them the site's lime, the one colour for what is in use.
PAGE_SECTIONS = {"play": "home", "screen": "home", "sound": "home", "controls": "home", "online": "home",
                 "help": "home", "about": "home"}


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
    """The named fonts, sized for the window's DPI. The wide face only ever sets English (the menu, PLAY, the guide's
    step names), so the same fonts serve both languages; Pretendard sets all text, Korean and Latin."""

    def __init__(self, root, language):
        import tkinter.font as tkfont
        # The menu in the wide face, English in both languages as the site's and the game's menus are (13.5 px).
        self.nav = tkfont.Font(root, family=DISPLAY, size=10)
        # The same, a step smaller, where the window is too narrow for the menu in one line at the full size.
        self.nav_small = tkfont.Font(root, family=DISPLAY, size=9)
        self.step = tkfont.Font(root, family=DISPLAY, size=9)                        # the guide's step names
        self.display_big = tkfont.Font(root, family=DISPLAY, size=17)                # PLAY
        self.card_title = tkfont.Font(root, family=TEXT_FONT, size=13, weight="bold")  # a card's title (17 px)
        self.body = tkfont.Font(root, family=TEXT_FONT, size=10)                     # text
        self.body_bold = tkfont.Font(root, family=TEXT_BOLD, size=10)                # labels and buttons
        self.small = tkfont.Font(root, family=TEXT_FONT, size=9)                     # hints
        self.tab = tkfont.Font(root, family=TEXT_BOLD, size=10)                      # a choice in a row of tabs
        self.icon_small = tkfont.Font(root, family=ICONS, size=12)                   # the chevron after a link
        self.dialog_title = tkfont.Font(root, family=TEXT_FONT, size=13, weight="bold")  # a dialog's question
        self.dialog_button = tkfont.Font(root, family=TEXT_BOLD, size=10)            # a dialog's buttons
        self.language = language


def scale_of(root):
    """Pixels per 1/96 inch: 1.0 at 100 % Windows scaling, 1.5 at 150 %."""
    return max(1.0, root.winfo_fpixels("1i") / 96.0)
