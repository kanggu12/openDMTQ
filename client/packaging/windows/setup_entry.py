"""The program PyInstaller freezes into OpenDMTQ-Setup.exe: the installer's dialogs around Velopack's setup."""

import sys

from opendmtq_client.installer import main

sys.exit(main())
