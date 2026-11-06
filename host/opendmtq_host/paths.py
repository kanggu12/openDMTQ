"""Where everything is: this program, the settings, the data, and the bundle's programs on Windows."""

import os
import sys

# This program's folder (host/opendmtq_host, what Python is given to run it), and the folder two up: a clone of the
# repository, or the bundle's app/.
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(os.path.dirname(HERE))

# The Windows bundle keeps the programs it brings in runtime/, next to app/. Elsewhere a folder of that name beside a
# clone means nothing.
BUNDLE = os.path.dirname(APP) if os.name == "nt" and os.path.isdir(os.path.join(os.path.dirname(APP), "runtime")) else None

# Where the settings and the data live: the bundle's folder, or the clone.
ROOT = BUNDLE or APP

# The command line's modules read .env and data/ from here too (cli/opendmtq_cli/system.py).
os.environ["OPENDMTQ_ROOT"] = ROOT

# The settings (.env) and the operator's files (data/), as with Docker Compose.
ENV_FILE = os.path.join(ROOT, ".env")
DATA = os.path.join(ROOT, "data")

# This install's own programs (install.sh puts the Python environment and the Java tools there) and run files.
LOCAL = os.path.join(ROOT, ".host")
RUN = os.path.join(LOCAL, "run")

# The program's log when it runs in the background, beside the server's own logs.
LOGS = os.path.join(DATA, "state", "logs")

# The command line's own helpers: the .env file, the address, the search for game files, the checks. Standard library
# only, so they import here without the containers' tools.
sys.path.insert(0, os.path.join(APP, "cli"))


# The operating system: the Windows bundle, macOS with Homebrew, or Linux.
WINDOWS = os.name == "nt"
MAC = sys.platform == "darwin"

# The command people type, for the messages that name one.
CLI = "OpenDMTQ.exe" if WINDOWS else "./opendmtq"

# The port the admin pages answer on, on this machine only, as with Docker Compose.
ADMIN_PORT = 8791

# How long a start waits for the server's first answer before it says so. A test makes it short, to see that wait run
# out on a server that is only slow.
START_WAIT = int(os.environ.get("OPENDMTQ_START_WAIT") or 60)

# How long the browser waits for the admin pages to listen, in seconds, once the server answers.
ADMIN_WAIT = 30

# Python for the tools: this install's own, isolated from the user's environment (-I), and writing UTF-8 whatever the
# system's code page (-X utf8): on Windows a folder name the code page lacks would stop the import otherwise.
PYTHON = [sys.executable, "-I", "-X", "utf8"]
