"""OpenDMTQ admin pages (served at /opendmtq/admin through the game server, beside the players' site at /opendmtq).

Runs in the tools image, which already has Java, apktool and the signer, so the phone app is built
right here. Sign-in with an ID and a password: the owner's from .env (ADMIN_USER, ADMIN_PASSWORD), or an
account with admin rights made on the Accounts page; every form carries a CSRF token; failed sign-ins are
throttled per address.

Run: gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 opendmtq_tools.admin:app
(one worker: build jobs and the sign-in throttle live in memory)
"""

from .. import songs, strings
# The application first; each page adds its addresses to it as it is imported.
from .core import app
from . import core, auth, assets, jobs, apps, players, recordings, song_pages, status, backups, accounts, logs
from . import charts, insights, setup

__all__ = ["app", "songs", "strings", "charts", "insights", "setup", "core", "auth", "assets", "jobs", "apps", "players", "recordings", "song_pages", "status", "backups", "accounts", "logs"]
