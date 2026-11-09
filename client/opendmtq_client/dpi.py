"""Sharp at any Windows scaling: the launcher's window and the installer's dialogs both draw at the screen's own
resolution.

System DPI awareness, the same for both: drawn at the main display's scale, which the launcher measures once at its
start (theme.scale_of). Per-monitor awareness would leave a window at the wrong size on a second display with another
scale, since Tk 8.6 does not redraw itself when Windows says the scale changed; with system awareness Windows scales the
window there instead.
"""

import sys


def aware():
    """Set the process's DPI awareness, before any of its windows opens (afterwards Windows keeps the first choice)."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        # Windows 8.1 and later: system DPI awareness.
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        # Older Windows: the same through the older call.
        ctypes.windll.user32.SetProcessDPIAware()
