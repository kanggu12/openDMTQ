"""The PC settings the launcher offers for the picture, the sound and keyboard play: each one's choices and default,
and the settings file the player reads at a start (player --settings FILE; arm32/desktop/settings.cpp reads the same
keys).

A phone's app sets these for itself; on a PC they are the player's to apply, chosen here before PLAY.
"""

import math
import re

# The game's area: the whole display it is on, or a window.
DISPLAY = ("fullscreen", "window")
# The game's area in a window: fitted to the display, or one of these sizes (the launcher leaves out the ones larger
# than the display, or smaller than the game's window holds at Windows' scale there).
WINDOW_SIZES = ("auto", "1280x720", "1600x900", "1920x1080", "2560x1440", "3840x2160")
# Frames on the display's refreshes, or as soon as they are drawn.
VSYNC = ("on", "off")
# The most frames a second: the display's own rate, a number, or as many as the PC makes.
FPS = ("auto", "30", "60", "120", "144", "165", "180", "240", "360", "unlimited")
# The share of the game's area the game draws at, in percent (the picture is stretched to the area).
RENDER_SCALE = ("100", "85", "75", "67", "50")
# Below 100 %, how the picture reaches the area's size: the plain stretch, AMD FidelityFX Super Resolution 1, or NVIDIA
# Image Scaling (arm32/desktop/post_pass.cpp).
UPSCALER = ("bilinear", "fsr1", "nis")
# How the edges of the game's shapes are smoothed: not at all, or by Intel's CMAA 2 or SMAA over the finished picture.
ANTI_ALIASING = ("off", "cmaa2", "smaa")
# MSAA, which earlier launchers offered, left the game's picture as it was: what they kept reads as CMAA 2, the smoothing
# it was chosen for, as the player reads it.
OLD_ANTI_ALIASING = {"msaa2": "cmaa2", "msaa4": "cmaa2", "msaa8": "cmaa2"}
# A counter of the frames a second over the game, off or on.
SHOW_FPS = ("off", "on")
# The counter's corner while it is on: the bottom right unless another is chosen (measured on the game's screens, it
# covers the fewest of the game's own labels and buttons there; every corner covers some on some screen). Kept while the
# counter is off, for the next time it is on.
FPS_POSITION = ("top_left", "top_right", "bottom_left", "bottom_right")
# The corner every launcher before 0.9.3 wrote into its settings file whether or not the player chose it: read as no
# choice (the default above) unless the file says the player chose it.
OLD_FPS_POSITION = "top_left"
# The sound shared with the PC's other sound, or the device alone (less latency).
AUDIO_MODE = ("shared", "exclusive")
# How much sound is kept ahead of the device: less latency, or fewer breaks on a busy PC.
AUDIO_BUFFER = ("low", "normal", "safe")
# Keyboard play: the lanes' keys play a song's lanes, or play nothing (the mouse and a touch screen play either way).
KEYBOARD = ("on", "off")
# Each LINE mode's keys, by its setting's name, and how many lanes the mode has (the game's rows, counted from the top).
LANES = {"keys_2line": 2, "keys_3line": 3, "keys_4line": 4}
# The most keys one lane takes: its key, and a second one beside it.
LANE_KEYS = 2
# The keys a lane takes, each by its place on the keyboard: the name of the US layout's key at that place (the name the
# settings file, --set and the Controls page use), its scan code (set 1, as Windows' key messages carry it and as Linux
# numbers the main block's keys; the player binds the place by it, so another layout plays the same places), and what
# the US layout prints there (the Controls page shows another layout's print beside the name when it differs).
KEYS = tuple((letter, scan, letter.lower()) for row, first in (("QWERTYUIOP", 0x10), ("ASDFGHJKL", 0x1E),
                                                               ("ZXCVBNM", 0x2C))
             for scan, letter in enumerate(row, first)) + tuple(
    (digit, scan, digit) for scan, digit in enumerate("1234567890", 0x02)) + (
    ("Space", 0x39, " "), ("Semicolon", 0x27, ";"), ("Quote", 0x28, "'"), ("Comma", 0x33, ","), ("Period", 0x34, "."),
    ("Slash", 0x35, "/"), ("LeftBracket", 0x1A, "["), ("RightBracket", 0x1B, "]"), ("Backslash", 0x2B, "\\"),
    ("Minus", 0x0C, "-"), ("Equals", 0x0D, "="), ("Grave", 0x29, "`"))
# The names alone, in that order (the words that list them say A to Z, 0 to 9, then the rest).
KEY_NAMES = tuple(name for name, _scan, _print in KEYS)
# A name to its place, and a place back to its name.
SCAN = {name: scan for name, scan, _print in KEYS}
BY_SCAN = {scan: name for name, scan, _print in KEYS}
# A name to what the US layout prints at its place.
US_PRINT = {name: printed for name, _scan, printed in KEYS}
# A name as typed in any case ("leftbracket", "SPACE") to the name as the player takes it.
_BY_FOLDED = {name.lower(): name for name in KEY_NAMES}
# The names as one refusal lists them: the letters and the digits as ranges, then the others by name.
_LISTED = "A to Z, 0 to 9, " + ", ".join(name for name in KEY_NAMES if len(name) > 1)

# Every setting and its default. Full screen first: the game is made for a phone's whole screen, and a touch screen
# plays best over all of it.
DEFAULTS = {
    "display": "fullscreen",
    "window": "auto",
    "vsync": "on",
    "fps": "auto",
    "render_scale": "100",
    "upscaler": "bilinear",
    "anti_aliasing": "off",
    "show_fps": "off",
    "fps_position": "bottom_right",
    "audio_device": "default",
    "audio_mode": "shared",
    "audio_buffer": "normal",
    "volume": 100,
    # Keyboard play on, each lane on the home row's keys under the index and middle fingers, the lanes from the top
    # from left to right on the keyboard.
    "keyboard": "on",
    "keys_2line": "F J",
    "keys_3line": "D F J",
    "keys_4line": "D F J K",
}
# The order the settings file lists them in, the player's own order: the picture's, the sound's, then keyboard play's.
# The counter's corner is no key of the player's: show_fps carries it there (off, or the corner it is on in).
ORDER = ("display", "window", "vsync", "fps", "render_scale", "upscaler", "anti_aliasing", "show_fps", "audio_device",
         "audio_mode", "audio_buffer", "volume", "keyboard") + tuple(LANES)
# Every setting the launcher keeps, in the order it lists them (--set, --status): the player's, the counter's corner
# after the counter.
NAMES = ORDER[:ORDER.index("show_fps") + 1] + ("fps_position",) + ORDER[ORDER.index("show_fps") + 1:]
# The choices of each setting that has a fixed list.
CHOICES = {"display": DISPLAY, "vsync": VSYNC, "fps": FPS, "render_scale": RENDER_SCALE, "upscaler": UPSCALER,
           "anti_aliasing": ANTI_ALIASING, "show_fps": SHOW_FPS, "fps_position": FPS_POSITION, "audio_mode": AUDIO_MODE,
           "audio_buffer": AUDIO_BUFFER, "keyboard": KEYBOARD}
# A window size the player takes (its own bounds: 480x270 to 16384 a side). 480x270 is also the smallest area its window
# holds at 100 %; at Windows' scale it is that many of Windows' own pixels (smallest_on).
SIZE = re.compile(r"^(\d{3,5})x(\d{3,5})$")
SMALLEST = (480, 270)


class ChoiceError(ValueError):
    """A setting the launcher does not have, or a value it does not offer for it."""

    def __init__(self, message, key=None, **params):
        super().__init__(message)
        # The words the window shows for it (i18n.TEXT), and their gaps.
        self.key, self.params = key, params


def _one(name, value):
    """The value as the launcher keeps it, or ChoiceError."""
    if name in CHOICES:
        text = str(value).strip().lower()
        if name == "anti_aliasing":
            text = OLD_ANTI_ALIASING.get(text, text)
        if text not in CHOICES[name]:
            raise ChoiceError("%s cannot be %r: it is one of %s" % (name, value, ", ".join(CHOICES[name])), "error.choice",
                              name=name, value=value)
        return text
    if name == "window":
        text = str(value).strip().lower()
        found = SIZE.match(text)
        if text == "auto":
            return text
        if not found or not (SMALLEST[0] <= int(found.group(1)) <= 16384 and SMALLEST[1] <= int(found.group(2)) <= 16384):
            raise ChoiceError("window cannot be %r: it is auto or WIDTHxHEIGHT (%dx%d or more)" % ((value,) + SMALLEST), "error.choice",
                              name=name, value=value)
        return "%dx%d" % (int(found.group(1)), int(found.group(2)))
    if name == "volume":
        try:
            number = int(str(value).strip())
        except ValueError:
            raise ChoiceError("volume cannot be %r: it is a number from 0 to 100" % (value,), "error.choice", name=name,
                              value=value) from None
        if not 0 <= number <= 100:
            raise ChoiceError("volume cannot be %r: it is a number from 0 to 100" % (value,), "error.choice", name=name,
                              value=value)
        return number
    if name == "audio_device":
        text = str(value).strip()
        # An id goes on one line of the settings file: no line breaks, nothing the player would read as another key.
        if not text or any(c in text for c in "\r\n\0") or len(text) > 512:
            raise ChoiceError("audio_device cannot be %r: it is default or a device id" % (value,), "error.choice", name=name,
                              value=value)
        return text
    if name in LANES:
        # The lanes' keys checked as the Controls page checks them, kept as the player names them.
        return lanes_text(lanes_of(name, value))
    raise ChoiceError("there is no setting %r" % (name,), "error.no_setting", name=name)


def mode(name):
    """A keys setting's LINE mode as the game names it: keys_3line -> "3 LINE"."""
    return "%d LINE" % LANES[name]


def key_name(text):
    """A key's name typed in any case ("leftbracket") as the player takes it ("LeftBracket"); None for one it does not
    take."""
    return _BY_FOLDED.get(str(text).lower())


def lanes_of(name, value):
    """A keys setting's value ("D/E F J") as its lanes from the top, each a tuple of its key names as the player takes
    them ((("D", "E"), ("F",), ("J",))). ChoiceError when it is not the mode's lanes (as many as the mode has, each
    one key or two joined by /), names a key no lane takes, or has a key twice."""
    text = str(value)
    # Lanes apart by spaces, any number of them (a hand-made line), none at either end.
    parts = text.split()
    count = LANES[name]
    if len(parts) != count:
        raise ChoiceError("%s cannot be %r: it is %d lanes from the top, apart by spaces, each one key or two joined by /"
                          % (name, text, count), "error.keys.lanes", name=name, value=text, mode=mode(name), n=count)
    lanes, seen = [], {}
    for number, part in enumerate(parts, 1):
        found = part.split("/")
        # One key or two, and no empty name between, before or after a /.
        if not 1 <= len(found) <= LANE_KEYS or not all(found):
            raise ChoiceError("%s cannot be %r: a lane has one key or two, joined by /" % (name, text),
                              "error.keys.lane", name=name, value=text, lane=number)
        lane = []
        for typed in found:
            key = key_name(typed)
            if key is None:
                raise ChoiceError("%s cannot be %r: %s is no key a lane takes (%s)" % (name, text, typed, _LISTED),
                                  "error.keys.name", name=name, value=text, keyname=typed)
            if key in lane:
                # The same key twice in one lane: the second would add nothing.
                raise ChoiceError("%s cannot be %r: %s is in lane %d twice" % (name, text, key, number),
                                  "error.keys.twice_in_lane", name=name, value=text, keyname=key, lane=number)
            if key in seen:
                # One key, one lane: a press must say which lane it plays.
                raise ChoiceError("%s cannot be %r: %s is in lane %d and lane %d" % (name, text, key, seen[key], number),
                                  "error.keys.twice", name=name, value=text, keyname=key, first=seen[key], second=number)
            seen[key] = number
            lane.append(key)
        lanes.append(tuple(lane))
    return tuple(lanes)


def lanes_text(lanes):
    """Lanes as the settings file and --set write them: each lane's keys joined by /, the lanes apart by one space."""
    return " ".join("/".join(lane) for lane in lanes)


def with_key(name, lanes, lane, slot, key):
    """The lanes with `key` in box `slot` (0 for a lane's key, 1 for its second) of lane `lane` (0 for the top), as the
    Controls page sets it from a key pressed; slot 1 of a lane with one key adds its second. ChoiceError when another
    box of the mode plays that key already: the page refuses it in words and nothing changes."""
    for number, keys in enumerate(lanes):
        for place, other in enumerate(keys):
            if other == key and (number, place) != (lane, slot):
                raise ChoiceError("%s already plays lane %d of %s" % (key, number + 1, mode(name)), "error.keys.taken",
                                  keyname=key, lane=number + 1, mode=mode(name))
    changed = list(lanes[lane])
    if slot < len(changed):
        # The box had a key: the new one in its place.
        changed[slot] = key
    else:
        # The empty box after a lane's key: a second key added.
        changed.append(key)
    return tuple(tuple(changed) if number == lane else keys for number, keys in enumerate(lanes))


def without_key(name, lanes, lane, slot):
    """The lanes with the key of box `slot` of lane `lane` taken away (the Controls page's Delete): the other key of the
    lane plays it alone. ChoiceError for a lane's only key: a lane keeps one at least."""
    if len(lanes[lane]) < 2:
        raise ChoiceError("lane %d of %s keeps one key at least" % (lane + 1, mode(name)), "error.keys.one",
                          lane=lane + 1, mode=mode(name))
    kept = tuple(key for place, key in enumerate(lanes[lane]) if place != slot)
    return tuple(kept if number == lane else keys for number, keys in enumerate(lanes))


def normalize(values, strict=True):
    """Every setting filled in from `values` over the defaults. A bad value raises ChoiceError, or with strict=False
    keeps the default (a hand-edited state file). The counter's corner as show_fps's value (as an older launcher kept it,
    and as --set still takes it) is the counter on in that corner."""
    merged = dict(DEFAULTS)
    values = dict(values or {})
    corner = str(values.get("show_fps", "")).strip().lower()
    if corner in FPS_POSITION:
        values["show_fps"] = "on"
        values["fps_position"] = corner
    for name, value in values.items():
        try:
            merged[name] = _one(name, value)
        except ChoiceError:
            if strict:
                raise
    return merged


def settings_text(values):
    """The settings file the player reads, one key=value a line, in its own order: the counter as its corner when it is
    on (the player's show_fps names the corner), off when it is not."""
    filled = normalize(values)
    filled["show_fps"] = filled["fps_position"] if filled["show_fps"] == "on" else "off"
    lines = ["# The PC settings the OpenDMTQ launcher chose, written before each start."]
    lines += ["%s=%s" % (name, filled[name]) for name in ORDER]
    return "\n".join(lines) + "\n"


def size_of(text):
    """'1920x1080' -> (1920, 1080); None for auto."""
    found = SIZE.match(text or "")
    return (int(found.group(1)), int(found.group(2))) if found else None


# The room a window needs on its display beyond the game's area: its title bar and Windows' taskbar (pixels).
WINDOW_ROOM = 80


def smallest_on(display):
    """The smallest game area the player's window holds on `display` ({"scale"}, displays.main_display): 480x270 at
    Windows' scale there (720x405 at 150 %), as the player has it (arm32/desktop/overlay_scale.h, at_scale)."""
    scale = float(display.get("scale") or 1.0)
    # Whole pixels and never fewer than the scale gives; a hair over a whole number is that number, as the player's.
    return tuple(int(math.ceil(side * scale - 0.001)) for side in SMALLEST)


def too_small(size, display):
    """Whether a window size ("1920x1080") is smaller than the game's window holds on `display`: the player would open
    it at its smallest instead. False for auto."""
    found = size_of(size)
    if found is None:
        return False
    least = smallest_on(display)
    return found[0] < least[0] or found[1] < least[1]


def fits(size, display):
    """Whether a window size ("1920x1080", or "auto") fits `display` ({"width", "height", "scale"},
    displays.main_display): no smaller than the game's window holds at Windows' scale there, and no larger than the
    display with room for the window's title bar and the taskbar. The Screen page leaves out the sizes that do not, and
    --set window= refuses them. True for auto; while the display's size is not known, only the smallest is checked."""
    found = size_of(size)
    if found is None:
        return True
    if too_small(size, display):
        return False
    if not display.get("width") or not display.get("height"):
        return True
    return found[0] <= display["width"] and found[1] + WINDOW_ROOM <= display["height"]


# The most refreshes VSync holds a frame for on a computer's display (arm32/src/pacing_math.h, kHostIntervalMost).
VSYNC_MOST = 4


def vsync_refreshes(hz, fps):
    """With VSync on a display of `hz`, the refreshes each frame stays for at the frame limit `fps` ("auto", a number,
    "unlimited"), as the player paces it (arm32/src/pacing_math.h, host_top): 1 for every refresh (no limit, or one at
    or above the display's rate), a whole number for a whole fraction of the rate near the limit, 0 when none comes
    near it and the player keeps the limit by the clock instead (very nearly, each frame on a refresh)."""
    if fps in ("auto", "unlimited") or not hz:
        return 1
    cap = float(fps)
    for n in range(1, VSYNC_MOST + 1):
        # Still above the limit at this many refreshes a frame (a 3 % margin): one more.
        if hz / float(n) > cap * 1.03:
            continue
        # A fraction under 90 % of the limit is not what the player chose: the limit by the clock instead.
        return n if n == 1 or hz / float(n) >= cap * 0.9 else 0
    return 0


def above_rate(hz, fps):
    """Whether a frame limit is above a display's rate of `hz` (with the player's 3 % margin): with VSync, the game
    shows no more frames than the display refreshes, so such a limit changes nothing. Never for "auto"."""
    if fps == "auto" or not hz:
        return False
    return fps == "unlimited" or int(fps) > hz * 1.03
