"""The PC settings the launcher offers for the picture and the sound: each one's choices and default, and the settings
file the player reads at a start (player --settings FILE; arm32/desktop/settings.cpp reads the same keys).

A phone's app sets these for itself; on a PC they are the player's to apply, chosen here before PLAY.
"""

import re

# The game's area: the whole display it is on, or a window.
DISPLAY = ("fullscreen", "window")
# The game's area in a window: fitted to the display, or one of these sizes (the launcher leaves out the ones larger
# than the display).
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
# The counter's corner while it is on: the top left, beside a song's pause button, or another (each corner has some of
# the game's own controls). Kept while the counter is off, for the next time it is on.
FPS_POSITION = ("top_left", "top_right", "bottom_left", "bottom_right")
# The sound shared with the PC's other sound, or the device alone (less latency).
AUDIO_MODE = ("shared", "exclusive")
# How much sound is kept ahead of the device: less latency, or fewer breaks on a busy PC.
AUDIO_BUFFER = ("low", "normal", "safe")

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
    "fps_position": "top_left",
    "audio_device": "default",
    "audio_mode": "shared",
    "audio_buffer": "normal",
    "volume": 100,
}
# The order the settings file lists them in, the player's own order. The counter's corner is no key of the player's:
# show_fps carries it there (off, or the corner it is on in).
ORDER = ("display", "window", "vsync", "fps", "render_scale", "upscaler", "anti_aliasing", "show_fps", "audio_device",
         "audio_mode", "audio_buffer", "volume")
# Every setting the launcher keeps, in the order it lists them (--set, --status): the player's, the counter's corner
# after the counter.
NAMES = ORDER[:ORDER.index("show_fps") + 1] + ("fps_position",) + ORDER[ORDER.index("show_fps") + 1:]
# The choices of each setting that has a fixed list.
CHOICES = {"display": DISPLAY, "vsync": VSYNC, "fps": FPS, "render_scale": RENDER_SCALE, "upscaler": UPSCALER,
           "anti_aliasing": ANTI_ALIASING, "show_fps": SHOW_FPS, "fps_position": FPS_POSITION, "audio_mode": AUDIO_MODE,
           "audio_buffer": AUDIO_BUFFER}
# A window size the player takes (its own bounds: 320x180 to 16384 a side).
SIZE = re.compile(r"^(\d{3,5})x(\d{3,5})$")


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
        if not found or not (320 <= int(found.group(1)) <= 16384 and 180 <= int(found.group(2)) <= 16384):
            raise ChoiceError("window cannot be %r: it is auto or WIDTHxHEIGHT (320x180 or more)" % (value,), "error.choice",
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
    raise ChoiceError("there is no setting %r" % (name,), "error.no_setting", name=name)


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


def fits(size, display):
    """Whether a window size ("1920x1080", or "auto") fits `display` ({"width", "height"}, displays.main_display) with
    room for the window's title bar and the taskbar: the Screen page leaves out the sizes that do not, and --set window=
    refuses them. True for auto, and for any size while the display's size is not known."""
    found = size_of(size)
    if found is None or not display.get("width") or not display.get("height"):
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
