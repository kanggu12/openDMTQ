"""A key pressed in the launcher's window, as keyboard play takes it: by its place on the keyboard, named as the US
layout's key at that place (values.KEYS), whatever layout the PC types with; and what the PC's own layout prints there.

The player binds each lane's key by its scan code (arm32/desktop, keyboard play), so a key chosen here plays the same
place on any layout: a French keyboard's A, at the US Q's place, is Q, and the Controls page shows A beside it.
"""

import sys

from opendmtq_client import values as choices

# Windows' MapVirtualKeyW translations: a virtual key to its scan code with an extended key's prefix kept (E0 or E1 in
# the high byte), to its scan code alone, a scan code to the virtual key the layout gives it, and a virtual key to the
# character the layout prints for it unshifted (in the answer's low word; its top bit marks a dead key, an accent that
# waits for the next letter).
MAPVK_VK_TO_VSC, MAPVK_VSC_TO_VK, MAPVK_VK_TO_CHAR, MAPVK_VK_TO_VSC_EX = 0, 1, 2, 4
# What a Tk key code on X11 is: the Linux key number plus 8, and Linux numbers the main block's keys by their scan code.
X11_OFFSET = 8

# The keys a person may press that no lane takes, as their caps name them, by Tk's names for them (the same on Windows
# and on X11). Others are said by what they print, or as "this key".
WORDS = {
    "Return": "Enter", "KP_Enter": "Enter", "Shift_L": "Shift", "Shift_R": "Shift", "Control_L": "Ctrl",
    "Control_R": "Ctrl", "Alt_L": "Alt", "Alt_R": "Alt", "Meta_L": "Alt", "Meta_R": "Alt", "Super_L": "Windows",
    "Super_R": "Windows", "Win_L": "Windows", "Win_R": "Windows", "Caps_Lock": "Caps Lock", "Num_Lock": "Num Lock",
    "Scroll_Lock": "Scroll Lock", "Insert": "Insert", "Home": "Home", "End": "End", "Prior": "Page Up",
    "Next": "Page Down", "Up": "↑", "Down": "↓", "Left": "←", "Right": "→", "Menu": "Menu",
    "App": "Menu", "Pause": "Pause", "Print": "Print Screen", "BackSpace": "Backspace",
}
# ImmAssociateContextEx's flag that gives a window its own default input context back (typing_back).
IACE_DEFAULT = 0x10


def _user32():
    """Windows' user32, where the keyboard layout is asked."""
    import ctypes
    return ctypes.windll.user32


def _map(code, kind):
    """MapVirtualKeyW(code, kind) for the keyboard layout of the window's thread (the launcher's one Tk thread): 0 when
    there is no translation."""
    import ctypes
    call = _user32().MapVirtualKeyW
    # Both the code and the answer are unsigned 32-bit numbers.
    call.argtypes, call.restype = (ctypes.c_uint, ctypes.c_uint), ctypes.c_uint
    return int(call(code, kind))


def _vk_to_scan(vk):
    """The scan code the layout in use makes the virtual key `vk` from, with an extended key's prefix (0xE035 for the
    numpad's /); 0 when the key has none (a key an input method held, VK_PROCESSKEY)."""
    found = _map(vk, MAPVK_VK_TO_VSC_EX)
    # A Windows without the extended translation answers 0 for every key: its plain translation instead.
    return found or _map(vk, MAPVK_VK_TO_VSC)


def _scan_to_vk(scan):
    """The virtual key the layout in use gives the key at scan code `scan`."""
    return _map(scan, MAPVK_VSC_TO_VK)


def _vk_to_char(vk):
    """The character the layout in use prints for the virtual key `vk` unshifted (letters in capitals) in the low word,
    a dead key's with the top bit set; 0 for none."""
    return _map(vk, MAPVK_VK_TO_CHAR)


def place_of(event):
    """The place of the key a Tk key press is for, as the name of the US layout's key there (values.KEYS); None for a
    key no lane takes (Enter, the arrows, the numpad, a modifier) or one whose place cannot be told."""
    if sys.platform == "win32":
        # Tk's key code on Windows is the virtual key, which the layout made of the place: the layout gives it back.
        scan = _vk_to_scan(event.keycode)
        # A prefixed code is a key of its own (the numpad's / at the main block's / place, the right Ctrl): no lane's.
        if not scan or scan > 0xFF:
            return None
    else:
        # X11: the server's key code less its offset is the place's scan code on the main block.
        scan = event.keycode - X11_OFFSET
    return choices.BY_SCAN.get(scan)


def printed(name, seen=None):
    """What the PC's keyboard layout prints at the place of key `name` (a name of values.KEYS), unshifted, or None when
    it cannot be told. On Windows the layout in use is asked; elsewhere (a developer's Linux, the tests) only a press
    tells it: `seen` holds what Tk said at the presses of this run, by name."""
    if sys.platform != "win32":
        return (seen or {}).get(name)
    vk = _scan_to_vk(choices.SCAN[name])
    # The character is the answer's low word: a dead key's mark, its top bit, is no part of it.
    char = (_vk_to_char(vk) & 0xFFFF) if vk else 0
    return chr(char) if char else None


def beside(name, print_):
    """What a key's box shows in grey beside its name: what the PC's layout prints there when that says more than the
    name (a sign, another layout's letter), in capitals as a key's cap prints it; None for a letter or a digit that is
    the name, a space, or a character that does not print."""
    if not print_ or len(print_) != 1 or not print_.isprintable() or print_.isspace():
        return None
    # The letters a to z in capitals, as their caps print them; any other character as the layout prints it: ß, whose
    # capital is two letters (SS), and é or à, which a French layout's caps print small.
    shown = print_.upper() if "a" <= print_ <= "z" else print_
    return None if shown == name.upper() else shown


def label(event):
    """A key no lane takes, named for the words that refuse it: as its cap names it (Enter, Shift, an arrow), a numpad
    key as Num and what it prints, an F key by its name, another by what it prints; None for one with no name to give
    (the words then say "this key")."""
    keysym = getattr(event, "keysym", "") or ""
    if keysym in WORDS:
        return WORDS[keysym]
    char = getattr(event, "char", "") or ""
    if keysym.startswith("KP_"):
        # The numpad's keys print as the main block's do: said as the numpad's.
        return "Num " + (char if char.isprintable() and char.strip() else keysym[3:])
    if len(keysym) >= 2 and keysym[0] == "F" and keysym[1:].isdigit():
        # F1 to F24, as their caps name them.
        return keysym
    if len(char) == 1 and char.isprintable() and not char.isspace():
        # Another key that prints (the ISO keyboard's extra key, <): the sign it prints.
        return char
    return None


def _imm32():
    """Windows' imm32, where a window's input context (the Korean, Japanese or Chinese input method) is set."""
    import ctypes
    return ctypes.windll.imm32


def typing_off(widget):
    """Turn Windows' input method off on the windows that get the keys while `widget` has Tk's focus, so that a key in
    Hangul mode (or Hiragana) comes as itself, with its place, not as the input method's key (VK_PROCESSKEY, keycode 229,
    no place to read). Tk gives the keyboard to the toplevel (its focus calls Windows' SetFocus on the toplevel's window,
    never on the widget's own), so the toplevel's input context is the one to take away; the window Windows says has
    the keyboard is taken too when it is another. Returns the windows turned off, for typing_back; none off Windows."""
    if sys.platform != "win32":
        return []
    windows = []
    try:
        import ctypes
        imm, user32 = _imm32(), _user32()
        # Each call's types: a window's handle and an input context's handle in, the old context's handle out.
        imm.ImmAssociateContext.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        imm.ImmAssociateContext.restype = ctypes.c_void_p
        user32.GetFocus.restype = ctypes.c_void_p
        # The toplevel Tk focuses, then the window with the keyboard now, if it is another (Tk's frame around it).
        for hwnd in (widget.winfo_toplevel().winfo_id(), user32.GetFocus()):
            if hwnd and hwnd not in windows:
                # No input context: the keys reach the window as they are pressed.
                imm.ImmAssociateContext(ctypes.c_void_p(hwnd), None)
                windows.append(hwnd)
    except (AttributeError, OSError):
        # A Windows without input methods: the keys come as they are already.
        pass
    return windows


def typing_back(windows):
    """Give `windows` (typing_off's) their own input context back, so that a text field of the window (the Online
    page's ID) types Korean again once no box waits. Nothing off Windows or for no windows."""
    if sys.platform != "win32" or not windows:
        return
    try:
        import ctypes
        imm = _imm32()
        # A window's handle, no context of the caller's, and the flag that puts the window's default one back.
        imm.ImmAssociateContextEx.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint)
        imm.ImmAssociateContextEx.restype = ctypes.c_int
        for hwnd in windows:
            imm.ImmAssociateContextEx(ctypes.c_void_p(hwnd), None, IACE_DEFAULT)
    except (AttributeError, OSError):
        # As typing_off: nothing was taken away there.
        pass
