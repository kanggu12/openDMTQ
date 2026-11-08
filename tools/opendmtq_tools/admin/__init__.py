"""OpenDMTQ admin pages (served at /opendmtq/admin through the game server, beside the players' site at /opendmtq), and its
HTTP API at /opendmtq/api/v1 (api.py, docs/api.md).

Runs in the tools image, which already has Java, apktool and the signer, so the phone app is built
right here. Sign-in with an ID and a password: the owner's from .env (ADMIN_USER, ADMIN_PASSWORD), or an
account with admin rights made on the Accounts page; every form carries a CSRF token; failed sign-ins are
throttled per address. The API takes a token made on the Accounts page instead.

Run: gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 opendmtq_tools.admin:app
(one worker: build jobs and the sign-in throttle live in memory)
"""

from .. import songs, strings
# The application first; each page adds its addresses to it as it is imported.
from .core import app
from . import core, auth, assets, jobs, apps, players, recordings, song_pages, status, backups, accounts, logs
from . import charts, insights, setup
# The API last: its routes call every page's actions, and its token check comes after the pages' sign-in gate.
from . import tokens, site, api_routes, api

__all__ = ["app", "songs", "strings", "charts", "insights", "setup", "core", "auth", "assets", "jobs", "apps", "players", "recordings", "song_pages",
           "status", "backups", "accounts", "logs", "tokens", "site", "api_routes", "api"]
