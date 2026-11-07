"""The commands that start, stop and look at the server."""

import json
import os
import signal
import subprocess
import sys
import time
from xml.sax.saxutils import escape

from opendmtq_cli import checks, env
from .paths import HERE, CLI, DATA, ENV_FILE, LOGS, MAC, ROOT, START_WAIT, WINDOWS
from .output import die, ok, say
from .programs import programs
from .settings import admin_port, listen_port, require_settings, settings
from .folders import make_folders, tool
from .server import health, running_pid, wait_healthy


def cmd_start(args):
    """Start the server in the background (Linux and macOS), and wait until it answers."""
    if WINDOWS:
        die("on Windows the server runs in its window: start OpenDMTQ.exe")
    values = require_settings()
    programs()
    if running_pid():
        ok(f"already running: http://{values['PUBLIC_HOST']}/")
        return 0
    make_folders()
    # The same program in the background, its messages to data/state/logs/host.log; it outlives this terminal.
    with open(os.devnull, "wb") as null:
        run = subprocess.Popen([sys.executable, "-X", "utf8", HERE, "run", "--log-to-file"],
                               stdin=subprocess.DEVNULL, stdout=null, stderr=null, start_new_session=True, cwd=ROOT)
    h = wait_healthy(values, gone=lambda: run.poll() is not None)
    if h is None:
        # The background program has ended: the last line of its log is why.
        if run.poll() is not None:
            die(last_log_line() or f"the server stopped; see {os.path.join(LOGS, 'host.log')}")
        # Still running: only slow. Setup looks at it again, and opens what is left in the browser.
        die(f"no answer from the server after {START_WAIT} s; it may still be starting. Run {CLI} setup again in a "
            f"minute, or see {os.path.join(LOGS, 'host.log')} and {os.path.join(LOGS, 'server.log')}")
    ok(f"running: http://{values['PUBLIC_HOST']}/")
    return 0


def last_log_line():
    """The last thing the background program wrote to its log, without the time in front; '' when there is nothing."""
    try:
        with open(os.path.join(LOGS, "host.log"), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return ""
    # Each line starts with a date and a time (setup_logging).
    return lines[-1].split(" ", 2)[-1] if lines else ""


def cmd_stop(args):
    """Stop the server started in the background."""
    pid = running_pid()
    if not pid:
        ok("not running")
        return 0
    os.kill(pid, signal.SIGTERM)
    # It stops its programs first, then goes.
    for _ in range(60):
        if not running_pid():
            ok("stopped")
            return 0
        time.sleep(0.5)
    die(f"the server (process {pid}) did not stop; see {os.path.join(LOGS, 'host.log')}")


def cmd_restart(args):
    """Stop, then start."""
    cmd_stop(args)
    return cmd_start(args)


def app_manifest():
    """The newest phone app's manifest, or None."""
    try:
        with open(os.path.join(DATA, "apk", "out", "latest.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def build_status():
    """What the app builder last said (data/apk/out/build.json), or {}."""
    try:
        with open(os.path.join(DATA, "apk", "out", "build.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def cmd_status(args):
    """One screen: the address, whether it runs and answers, the files, the app."""
    values = settings()
    if not values.get("PUBLIC_HOST"):
        say(f"Not set up yet: run {CLI} setup.")
        return 1
    h = health(values)
    say(f"Address      http://{values['PUBLIC_HOST']}/")
    user = values.get("ADMIN_USER") or "admin"
    say(f"Admin pages  http://localhost:{admin_port(values)}/opendmtq/admin/  (user {user})")
    say(f"Server       {'running' if h is not None else 'not running'}")
    if h is not None:
        say(f"Client data  {'yes' if h.get('game_data') else f'missing: {CLI} import <folder>'}")
        say(f"Songs        {h.get('songs', 0)}")
        say(f"Players      {h.get('players', 0)}")
    m = app_manifest()
    b = build_status()
    say(f"Phone app    {m['file'] if m else 'not built yet'}" + (f" ({b.get('state')})" if b.get("state") else ""))
    return 0


def cmd_import(args):
    """Take the base APK and the client data (and with --songs the song data) from a folder or file."""
    values = settings()
    found = programs()
    src = os.path.abspath(os.path.expanduser(args.path))
    if not os.path.exists(src):
        die(f"{src} does not exist")
    make_folders()
    checking = getattr(args, "check", False)
    # A running server keeps serving the old files while the new ones are moved in, except on Windows, where a file
    # in use cannot be moved: there the server's window is closed first. A check moves nothing.
    if WINDOWS and running_pid() and not checking:
        die("close OpenDMTQ's window first (the server keeps the files in use), then import again")
    extra = {"IMPORT_SONGS": "yes" if args.songs else "no", "IMPORT_GAME": "no" if args.no_game_data else "yes"}
    if checking:
        # Only what each file is.
        extra["IMPORT_CHECK"] = "yes"
    if os.path.isfile(src):
        # A single file: its folder, and only that file in it.
        extra.update({"OPENDMTQ_IMPORT_IN": os.path.dirname(src), "IMPORT_ONLY": os.path.basename(src)})
    else:
        extra["OPENDMTQ_IMPORT_IN"] = src
    if getattr(args, "names", None):
        # Only the files setup's search matched in that folder.
        extra["IMPORT_ONLY"] = "/".join(args.names)
    status = tool("importer", values=values, found=found, extra=extra)
    if status == 1:
        die("nothing usable was found there (see the lines above)")
    if status != 0:
        die("the import failed (see the error above)")
    if checking:
        return 0
    # The song list follows what came in: rebuilt now, and read by the server at once.
    tool("songs", values=values, found=found)
    return 0


def cmd_apk(args):
    """Build the phone app now, for the address in .env."""
    values = require_settings()
    found = programs()
    if tool("builder", "--force", values=values, found=found) != 0:
        die("the app could not be built (see above)")
    show_address(values)
    return 0


def cmd_runtime(args):
    """The newest runtime for phones without 32-bit support, then the app with it. --no-app: only the runtime, for an update
    (host/get.sh), whose setup starts the server, which builds the app when anything has changed."""
    values = require_settings()
    found = programs()
    if tool("runtime", "--refresh", values=values, found=found) != 0:
        die("see above; the app stays as it is")
    return 0 if args.no_app else cmd_apk(args)


def show_address(values):
    """Where phones go, as text and (in a terminal that draws it) a QR code."""
    url = f"http://{values['PUBLIC_HOST']}/"
    where = "on the same Wi-Fi" if env.is_lan_only(values["PUBLIC_HOST"]) else "from anywhere"
    say(f"\nOn a phone {where}, open {url}, sign in, and tap Download app (.apk).")
    # The Windows console draws the QR code's blocks twice as wide in some fonts: the site shows it there instead.
    if not WINDOWS:
        tool("qr", url, values=values)


def cmd_host(args):
    """Show the address phones use, or change it (the app is built again for it)."""
    values = settings()
    if not args.address:
        say(values.get("PUBLIC_HOST") or "not set up yet")
        return 0
    problem = env.check_host(args.address)
    if problem:
        die(problem)
    host, port = env.split(args.address)
    port = port if ":" in args.address else listen_port(values)
    env.save(ENV_FILE, {"PUBLIC_HOST": env.join(host, port), "LISTEN_PORT": str(port)})
    ok(f"PUBLIC_HOST={env.join(host, port)}")
    # The server picks up the address at its next start; the builder then makes the app for it.
    if running_pid() and not WINDOWS:
        cmd_restart(args)
    return 0


def cmd_check(args):
    """Walk the game's whole path against the running server (the same walk as ./opendmtq check)."""
    values = require_settings()
    if health(values) is None:
        die("the server is not running")
    failures = checks.end_to_end()
    say("all checks passed" if not failures else f"{failures} check(s) failed")
    return 1 if failures else 0


def launchd_plist(python, me, root):
    """The launchd agent that starts the server at sign-in on macOS. Started again when it fails, not when it was
    stopped (./opendmtq stop, the admin pages' Stop the server, both end it well), as systemd's Restart=on-failure.
    The paths in it as XML text: one with & or < in it would break the file."""
    p, m, r = (escape(x) for x in (python, me, root))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>org.opendmtq.server</string>
  <key>ProgramArguments</key><array>
    <string>{p}</string><string>{m}</string><string>run</string><string>--log-to-file</string>
  </array>
  <key>WorkingDirectory</key><string>{r}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
</dict></plist>
"""


def systemd_word(text):
    """One word of a systemd unit's command: in quotes, its backslashes and quotes escaped, so that a path with spaces
    stays one; and % doubled, as systemd reads %h and the like everywhere in a unit."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def systemd_unit(python, me, root):
    """The user unit that starts the server at boot on Linux."""
    plain = root.replace("%", "%%")
    return f"""[Unit]
Description=OpenDMTQ server ({plain})
After=network-online.target

[Service]
ExecStart={systemd_word(python)} {systemd_word(me)} run --log-to-file
WorkingDirectory={plain}
Restart=on-failure

[Install]
WantedBy=default.target
"""


def cmd_service(args):
    """Start the server with the computer: a systemd unit on Linux, a launchd agent on macOS."""
    me = HERE
    if MAC:
        plist = os.path.expanduser("~/Library/LaunchAgents/org.opendmtq.server.plist")
        if args.remove:
            subprocess.run(["launchctl", "unload", plist], capture_output=True)
            if os.path.exists(plist):
                os.remove(plist)
            ok("removed the launchd agent")
            return 0
        os.makedirs(os.path.dirname(plist), exist_ok=True)
        with open(plist, "w", encoding="utf-8") as f:
            f.write(launchd_plist(sys.executable, me, ROOT))
        subprocess.run(["launchctl", "load", plist], check=False)
        ok(f"starts at sign-in: {plist}")
        return 0
    if WINDOWS:
        die("on Windows, put a shortcut to OpenDMTQ.exe in the Startup folder (Win+R, shell:startup)")
    # Linux: a unit for this user's systemd, which runs it at boot once lingering is on.
    unit_dir = os.path.expanduser("~/.config/systemd/user")
    unit = os.path.join(unit_dir, "opendmtq.service")
    if args.remove:
        subprocess.run(["systemctl", "--user", "disable", "--now", "opendmtq.service"], capture_output=True)
        if os.path.exists(unit):
            os.remove(unit)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        ok("removed the systemd unit")
        return 0
    os.makedirs(unit_dir, exist_ok=True)
    with open(unit, "w", encoding="utf-8") as f:
        f.write(systemd_unit(sys.executable, me, ROOT))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now", "opendmtq.service"], check=False)
    # Without lingering, a user's services stop when they sign out and start only when they sign in.
    subprocess.run(["loginctl", "enable-linger", os.environ.get("USER", "")], check=False)
    ok(f"starts at boot: {unit} (systemctl --user status opendmtq)")
    return 0
