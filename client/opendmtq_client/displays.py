"""The PC's main display, for the Screen page: its size in pixels and its refresh rate, so the page can say what
"the display's own rate" is and leave out window sizes larger than it.

On Windows, from GDI (the launcher is DPI aware, so the size is the display's own pixels); elsewhere (development and
the tests) Tk's screen size and no rate.
"""

import sys


def main_display(root=None):
    """{"width", "height", "hz"} of the main display; hz None when the system does not say."""
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
                # HORZRES, VERTRES and VREFRESH: the main display's pixels and its rate in whole hertz.
                width, height, hz = gdi32.GetDeviceCaps(dc, 8), gdi32.GetDeviceCaps(dc, 10), gdi32.GetDeviceCaps(dc, 116)
            finally:
                user32.ReleaseDC(None, dc)
            # 0 and 1 mean the hardware's default rate, which says nothing.
            return {"width": width, "height": height, "hz": hz if hz > 1 else None}
        except (AttributeError, OSError):
            # No GDI to ask (a stripped-down Windows): the screen as Tk sees it.
            pass
    if root is not None:
        return {"width": root.winfo_screenwidth(), "height": root.winfo_screenheight(), "hz": None}
    return {"width": 0, "height": 0, "hz": None}
