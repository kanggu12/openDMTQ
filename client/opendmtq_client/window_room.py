"""Where the launcher's window goes: the room windows have on the screen (on Windows its work area, the screen less the
taskbar wherever it sits), the height Windows puts around a window's own area (its title bar and frame), and the
window's box in that room.

Plain numbers and ctypes, no Tk: app.py places its window with them, and the tests check them with numbers alone. A
window sized and centred on the whole screen reaches under the taskbar on a laptop at 150 % (1920x1080, a 72 px
taskbar): the lower half of the strip at its foot, PLAY on it.
"""

import sys

# Windows' calls for the room a window has: SystemParametersInfo's SPI_GETWORKAREA, and GetSystemMetrics' caption
# height, sizing frame and padded border (each in this process's pixels, as the launcher is DPI aware).
SPI_GETWORKAREA = 0x0030
SM_CYCAPTION, SM_CYSIZEFRAME, SM_CXPADDEDBORDER = 4, 33, 92
# The share of the room the window takes at most, as before: some of the desktop stays in sight around it.
SHARE = 0.92


def work_area(root):
    """(left, top, width, height) of where a window may go: on Windows its work area (the main screen less the taskbar),
    elsewhere the whole screen as Tk sees it."""
    if sys.platform == "win32":
        try:
            # Imported here: only Windows has these calls.
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            # The work area in the pixels this process sees, as winfo_screenwidth's are.
            if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                # A work area with no room (a broken answer) is no answer: the screen below is.
                if rect.right > rect.left and rect.bottom > rect.top:
                    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except (AttributeError, OSError, ValueError):
            # A Windows or a Wine without the call: the whole screen, as the launcher did before.
            pass
    # Linux (the tests' virtual screen) and every fallback: the screen Tk reports.
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def title_bar_height():
    """What Windows puts above and below a window's own area (its title bar and its sizing frame), in pixels; 0 where the
    window manager's decorations are not Windows' (Linux, where the tests run)."""
    if sys.platform == "win32":
        try:
            # Imported here: only Windows has the call.
            import ctypes
            metric = ctypes.windll.user32.GetSystemMetrics
            # The caption, and the sizing frame with its padding at the top and at the bottom.
            return max(0, int(metric(SM_CYCAPTION) + 2 * (metric(SM_CYSIZEFRAME) + metric(SM_CXPADDEDBORDER))))
        except (AttributeError, OSError, ValueError):
            # No answer: nothing counted, as before.
            pass
    # No title bar of Windows' to count.
    return 0


def window_box(room, caption, want_w, want_h):
    """The window's (width, height, x, y) in `room` (left, top, width, height): its wanted size, never more than SHARE of
    the room, the title bar and frame (`caption`) counted in the height, centred across and a third of the way down, so
    that the whole window, its title bar included, stays inside the room."""
    left, top, room_w, room_h = room
    # As wide as wanted, or the room's share of it when the room is narrower.
    w = max(1, min(want_w, int(room_w * SHARE)))
    # As tall as wanted, or the room's share less the title bar and frame that Windows adds above and below it.
    h = max(1, min(want_h, int(room_h * SHARE) - caption))
    # Tk places the outer frame on Windows: the caption is part of what is centred, a third of the room's spare height
    # above it and two thirds below.
    x = left + (room_w - w) // 2
    y = top + max(0, (room_h - (h + caption)) // 3)
    return w, h, x, y
