"""Run as python host/opendmtq_host <command>: this folder's parent goes on the path (Python is started isolated, so
nothing else puts it there), and the command line takes over."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opendmtq_host.cli import main  # noqa: E402  (needs the path above)

sys.exit(main())
