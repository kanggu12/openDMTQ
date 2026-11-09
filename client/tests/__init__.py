"""The PC client's tests. Importing them marks the process as a test run, so nothing opens a window on a real screen.

  cd client && python3 -m unittest discover -s tests -t .
"""

import logging
import os

# Every function that opens a window (the launcher, a dialog, the game's player, Explorer) refuses while this is set,
# unless a test container's virtual screen is in use (opendmtq_client/safety.py).
os.environ["OPENDMTQ_TESTING"] = "1"
# What the launcher logs goes to its log file in a test's own folder (main._logging); the test run prints its own.
logging.getLogger("opendmtq_client").addHandler(logging.NullHandler())
