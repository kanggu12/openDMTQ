"""The program PyInstaller freezes: both OpenDMTQ.exe (window) and OpenDMTQ-cmd.exe (console) start here."""

import sys

from opendmtq_client import stopped


def launch():
    # Imported here: an install damaged enough to break an import is said in the dialog too.
    from opendmtq_client.main import main
    return main()


def launcher_log():
    import os
    from opendmtq_client import state as st
    return os.path.join(st.config_dir(), "logs", "launcher.log")


sys.exit(stopped.run(launch, launcher_log))
