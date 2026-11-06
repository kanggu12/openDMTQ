"""Unit tests for the tools package.

python3-qrcode is installed in the tools image only. Outside it, empty stand-ins let the patcher
import; no test draws a QR code.
"""

import importlib.util
import sys
import types

if importlib.util.find_spec("qrcode") is None:
    for _name in ("qrcode", "qrcode.image", "qrcode.image.svg"):
        sys.modules[_name] = types.ModuleType(_name)
