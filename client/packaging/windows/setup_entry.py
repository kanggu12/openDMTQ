"""The program PyInstaller freezes into OpenDMTQ-Setup.exe: the installer's dialogs around Velopack's setup."""

import sys

from opendmtq_client import stopped


def install():
    # Imported here: an installer damaged enough to break an import is said in the dialog too.
    from opendmtq_client.installer import main
    return main()


def setup_log():
    import os
    import tempfile
    return os.path.join(tempfile.gettempdir(), "OpenDMTQ-setup.log")


sys.exit(stopped.run(install, setup_log))
