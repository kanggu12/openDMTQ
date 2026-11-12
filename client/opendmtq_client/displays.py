"""The PC's main display, for the Screen page: its size in pixels, its refresh rate and Windows' scale on it, so the
page can say what "the display's own rate" is and leave out window sizes larger than it or smaller than the game's
window holds there.

On Windows, from GDI (the launcher is DPI aware, so the size is the display's own pixels); elsewhere (development and
the tests) Tk's screen size and no rate.
"""

import sys


def main_display(root=None):
    """{"width", "height", "hz", "scale"} of the main display; hz None when the system does not say, scale 1.0 (100 %)
    when it cannot be told."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            user32, gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
            # The screen's device context is a handle: its own type, so that it passes back whole.
            user32.GetDC.restype = wintypes.HDC
            user32.GetDC.argtypes = (wintypes.HWND,)
            user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
            gdi32.GetDeviceCaps.argtypes = (wintypes.HDC, ctypes.c_int)
            dc = user32.GetDC(None)
            try:
                # DESKTOPHORZRES, DESKTOPVERTRES and VREFRESH: the main display's own pixels, whatever the program's
                # DPI awareness (the command line has none, and HORZRES would give it the display shrunk by Windows'
                # scaling), and its rate in whole hertz.
                width, height, hz = gdi32.GetDeviceCaps(dc, 118), gdi32.GetDeviceCaps(dc, 117), gdi32.GetDeviceCaps(dc, 116)
                # Windows' scale on it, the same with DPI awareness (the launcher's window: LOGPIXELSX is the display's
                # dots per inch) and without (the command line: LOGPIXELSX says 96, and HORZRES the display shrunk by
                # the scale): whichever of the two says more.
                logical_dpi, logical_width = gdi32.GetDeviceCaps(dc, 88), gdi32.GetDeviceCaps(dc, 8)
            finally:
                user32.ReleaseDC(None, dc)
            scale = max(logical_dpi / 96.0 if logical_dpi > 0 else 1.0, width / float(logical_width) if logical_width > 0 else 1.0)
            # 0 and 1 mean the hardware's default rate, which says nothing.
            return {"width": width, "height": height, "hz": hz if hz > 1 else None, "scale": round(max(1.0, scale), 3)}
        except (AttributeError, OSError):
            # No GDI to ask (a stripped-down Windows): the screen as Tk sees it.
            pass
    if root is not None:
        return {"width": root.winfo_screenwidth(), "height": root.winfo_screenheight(), "hz": None, "scale": 1.0}
    return {"width": 0, "height": 0, "hz": None, "scale": 1.0}
