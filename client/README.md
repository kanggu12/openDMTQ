# The PC client

`OpenDMTQ-Setup.exe` installs the launcher (portal) and the player for Windows for one Windows user, with no
administrator rights. The launcher connects to an OpenDMTQ server, signs in with an account its owner made, downloads
that server's app, sets the picture and the sound up for the PC, and starts the game in the player. An installer
downloaded from a server's site has that server on its end and starts with it; one from a release asks for the address.

| Path | What it is |
|---|---|
| `opendmtq_client/` | The launcher (Python and Tk): `app.py` (the window), `pages.py`, `guide.py` (the first-start guide), `actions.py` (what the buttons do, shared with the command line in `main.py`), `server.py` (the server's `client.php` and `/apk`), `apps.py` (each server's app on this PC), `player.py`, `values.py` (the PC settings), `installer.py` (the installer's dialogs), `repair.py` and `removal.py` (Help's Repair, Clear game data and Uninstall) |
| `packaging/windows/` | The Windows build: PyInstaller under Wine, the player beside the launcher, Velopack's packages, the installer |
| `tests/` | Unit tests, the UI screenshots on a virtual screen (`tests/ui`), and the installer to the game under Wine (`tests/windows`) |

What it keeps, per Windows user: the program in `%LOCALAPPDATA%\OpenDMTQ.Client`, the launcher's settings, logs and
each server's app in `%LOCALAPPDATA%\OpenDMTQ\client`, and the game's own data and the player's log in
`%LOCALAPPDATA%\OpenDMTQ\<package>`, as the player keeps them.

## Working on it

```sh
cd client && python3 -m unittest discover -s tests -t .     # no screen, no network: a stand-in server and player
client/tests/ui/run.sh OUT_DIR                               # every page, the guide and the dialogs, both languages, three sizes
arm32/bundle_windows.sh                                      # the player for Windows, which the installer brings
client/packaging/windows/build.sh OUT_DIR                    # OUT_DIR/releases: the installer and Velopack's packages
TEST_SITE=... TEST_NET=... TEST_APK=... TEST_TOOLS=... ACCOUNT_FILE=... \
  client/tests/windows/e2e.sh OUT_DIR E2E_DIR                # installer to game under Wine, against a test server
```

A build looks for updates where `OPENDMTQ_UPDATE_SOURCE` points when it is made: a GitHub repository's URL (its
releases), or a folder holding the packages `build.sh` leaves in `OUT_DIR/releases`. `OpenDMTQ-cmd.exe --help` lists
what the command line does: the same as the window, each step a flag.
