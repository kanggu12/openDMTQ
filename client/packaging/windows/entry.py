"""The program PyInstaller freezes: both OpenDMTQ.exe (window) and OpenDMTQ-cmd.exe (console) start here."""

import sys

from opendmtq_client.main import main

sys.exit(main())
