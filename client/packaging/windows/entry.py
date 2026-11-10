"""The program PyInstaller freezes: both OpenDMTQ.exe (window) and OpenDMTQ-cmd.exe (console) start here."""

import sys

from opendmtq_client import stopped


def launch():
    # Imported here: an install damaged enough to break an import is said in the dialog too.
    from opendmtq_client.main import main
    return main()


def launcher_log():
    # Imported only when an error asks where the log is: what failed may be in what the import brings.
    from opendmtq_client import state as st
    return st.launcher_log()


sys.exit(stopped.run(launch, launcher_log))
