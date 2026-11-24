"""The commands that start, stop and look at the server."""

import glob
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from xml.sax.saxutils import escape

from opendmtq_cli import checks, env, look
from .paths import HERE, CLI, DATA, ENV_FILE, LOGS, MAC, ROOT, START_WAIT, WINDOWS
from .output import die, ok, say, tell
from .programs import programs
from .settings import admin_url, leave_port_80, listen_port, require_settings, settings, site_url
from .folders import make_folders, tool, version
from .server import health, running_pid, wait_healthy


def cmd_start(args):
    """Start the server in the background (Linux and macOS), and wait until it answers."""
    if WINDOWS:
        die("on Windows the server runs in its window: start OpenDMTQ.exe")
    require_settings()
    # The wordmark first (once per run: the setup that comes here showed it already).
    look.banner(version())
    # Off port 80, for a server set up on it before 0.11.0: before anything names its address.
    leave_port_80()
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
    # Started on its own (start, restart): the addresses and the owner's sign-in, as the setup's end shows them. (The
    # setup that comes here shows them itself, once.)
    if getattr(args, "cmd", None) in ("start", "restart"):
        say("")
        for line in look.address_block(site_url(values), admin_url(values),
                                       values.get("ADMIN_USER") or "admin", where="ADMIN_PASSWORD in .env"):
            say(line)
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
    look.banner(version())
    user = values.get("ADMIN_USER") or "admin"
    # Label and value lines in one column; a state word in its colour (running, missing). One address: the admin pages
    # are on the server's own port.
    lines = [("Address", site_url(values)),
             ("Admin pages", f"{admin_url(values)}  (ID {user}, password ADMIN_PASSWORD in .env)"),
             ("Server", ("running", "ok") if h is not None else ("not running", "warn"))]
    if h is not None:
        lines += [("Client data", ("yes", "ok") if h.get("game_data") else (f"missing: {CLI} import <folder>", "warn")),
                  ("Songs", str(h.get("songs", 0))), ("Players", str(h.get("players", 0)))]
    m = app_manifest()
    b = build_status()
    if not m and not glob.glob(os.path.join(DATA, "apk", "base", "*.apk")):
        # No game client to build from yet: the import brings it, and the app is built then. The builder's last end
        # without one is that wait, not a failure (the window's line at a start says the same: server.builder_outcome).
        lines.append(("Phone app", "waits for the game files: built once they are imported"))
    else:
        lines.append(("Phone app", f"{m['file'] if m else 'not built yet'}" + (f" ({b.get('state')})" if b.get("state") else "")))
    for line in look.rows(lines):
        say(line)
    # A move off port 80 at the first start of this version, said here once too.
    moved = env.move_off_80_unsaid(os.path.join(DATA, "state"), "status")
    if moved:
        say("")
        first, *rest = env.move_off_80_words(moved)
        tell(" ".join([first + "."] + rest))
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


def installer_offered():
    """True when the site hands out the PC client's installer: data/apk/out/windows.json says one, and its file is
    there at the size it says (tools/opendmtq_tools/windows_client.py offered(), which the site reads the same way)."""
    out = os.path.join(DATA, "apk", "out")
    try:
        with open(os.path.join(out, "windows.json"), encoding="utf-8") as f:
            made = json.load(f)
        # The file the site would hand out, at the size the builder wrote down when it put it there.
        return os.path.getsize(os.path.join(out, os.path.basename(str(made.get("file", ""))))) == made.get("size")
    # No installer yet (none was found or fetched), or one gone or not readable: the site offers none, nor is it said.
    except (OSError, ValueError, AttributeError):
        return False


def show_address(values):
    """Where phones and PCs go, as text and (in a terminal that draws it) a QR code."""
    url = f"http://{values['PUBLIC_HOST']}/"
    lan = env.is_lan_only(values["PUBLIC_HOST"])
    where = "on the same Wi-Fi" if lan else "from anywhere"
    say("")
    tell(f"On a phone {where}, open {url}, sign in, and tap Download app (.apk).")
    # The same site offers the PC client for Windows once the builder has put its installer beside the app (the Windows
    # bundle brings one; other installs fetch it): said with the button's own words, as the Download page shows them.
    if installer_offered():
        pc_where = "on the same network" if lan else "from anywhere"
        tell(f"On a Windows PC {pc_where}, open the same address, sign in, and choose Download the installer (.exe): it "
            "installs the PC client, set up for this server.")
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
    # Port 80 named in the address: the owner's own choice, kept at every start (env.leaves_80).
    env.save(ENV_FILE, {"PUBLIC_HOST": env.join(host, port), "LISTEN_PORT": str(port),
                        **({env.CHOSE_80: "chosen"} if port == 80 else {})})
    ok(f"PUBLIC_HOST={env.join(host, port)}")
    # The server picks up the address at its next start; the builder then makes the app for it.
    if running_pid() and not WINDOWS:
        cmd_restart(args)
    return 0


def cmd_port(args):
    """Show the server's one port, or move the server to another (LISTEN_PORT, and the port in PUBLIC_HOST): from the
    next start, with the app built again for the new address, which the site's download page then tells players to
    install. A port another program holds is refused, in words."""
    from .settings import bindable
    values = require_settings()
    now = listen_port(values)
    if args.port is None:
        say(f"Port {now}: the game, the players' site ({site_url(values)}), the admin pages and the API")
        return 0
    if not 1 <= args.port <= 65535:
        die("a port is a number from 1 to 65535")
    if args.port == now:
        ok(f"the server is on port {now} already")
        return 0
    if not bindable(args.port):
        die(f"port {args.port} is taken on this computer by another program (or this user may not use it); choose another")
    # A router's own port in an internet address stays, with the app phones have; the router's line where there is one
    # (opendmtq_cli.env.port_move, as the Server page and the compose command line move it).
    new, stays, router = env.port_move(values["PUBLIC_HOST"], now, args.port)
    # Port 80 by the owner's own choice: kept at every start (a server only set up on it before 0.11.0 moves off it).
    env.save(ENV_FILE, {"PUBLIC_HOST": new, "LISTEN_PORT": str(args.port),
                        **({env.CHOSE_80: "chosen"} if args.port == 80 else {})})
    if args.port != 80:
        env.drop(ENV_FILE, (env.CHOSE_80,))
    restart = "Close the server's window and start OpenDMTQ.exe again" if WINDOWS else f"{CLI} restart"
    if stays:
        ok(f"the server moves to port {args.port} at its next start; its address stays http://{new}/")
        tell(f"{restart} to move it now; phones keep the app they have.")
    else:
        ok(f"the server moves to port {args.port} at its next start: http://{new}/")
        tell(f"{restart} to move it now; the app is built again for the new address then. Players install the new app "
             "over the old one, which keeps each device's account; the site's download page says so.")
    if router:
        tell(router)
    return 0


def cmd_name(args):
    """Show the server's name in the app's title (TECHNIKA Q (name) on phones), or change it (SERVER_NAME in .env): from
    the next start, when the app is built again with it, as the admin pages' Server page does. Phones keep working with
    the app they have, which calls the same address. A running server is started again here, as host does (on Windows
    its window is closed and opened again). Empty: the address names the app."""
    values = require_settings()
    current = values.get("SERVER_NAME", "").strip()
    # The app's name for a name: the address in place of none.
    titled = lambda name: f"TECHNIKA Q ({name or values['PUBLIC_HOST']})"
    if args.name is None:
        say(f"{titled(current)} on phones" + ("" if current else ": the address, as the server has no name"))
        return 0
    name = args.name.strip()
    # What .env and the app take, as the Server page and ./opendmtq name take it.
    if len(name) > 80 or not name.isprintable() or any(c in name for c in "\"'$`\\#"):
        die("a name here is at most 80 characters, without quotes, $, #, \\ or `")
    if name == current:
        ok(f"the app is called {titled(name)} already")
        return 0
    env.save(ENV_FILE, {"SERVER_NAME": name})
    ok(f"the app is called {titled(name)} from the server's next start, when it is built again")
    # The server takes it at its start: a running one is started again now (on Windows, by its window).
    if running_pid():
        if WINDOWS:
            tell("Close the server's window and start OpenDMTQ.exe again: the app is built again with the new name then.")
        else:
            cmd_restart(args)
    return 0


def cmd_password(args):
    """Change the owner's password (ADMIN_PASSWORD in .env), which with the owner's ID opens the admin pages and the
    players' site: typed twice on a terminal, or one made when nothing is typed or there is no terminal. The admin pages'
    Server page does the same while the server runs; this is the way in when the password is lost. The server takes it at
    its next start: a running one is started again here, as host does (on Windows its window is closed and opened again)."""
    import getpass
    import re
    import secrets
    values = require_settings()
    new = ""
    # On a terminal: the new password, hidden as it is typed, then again; Enter alone has one made.
    if sys.stdin.isatty():
        new = getpass.getpass("New password for the admin pages (Enter to have one made): ")
        if new:
            if not re.fullmatch(env.OWNER_PASSWORD, new):
                die("a password here is 10 to 64 characters, without spaces, quotes, $, #, \\ or `")
            if getpass.getpass("The same again: ") != new:
                die("the two passwords are not the same; nothing changed")
    made = not new
    # Sixteen letters, digits, - and _, as setup makes the first one.
    new = new or secrets.token_urlsafe(12)
    env.save(ENV_FILE, {"ADMIN_PASSWORD": new})
    ok(f"the owner's password is changed: ID {values.get('ADMIN_USER') or 'admin'}, for the admin pages and the players' site")
    if made:
        say(f"The new password: {new}  (kept as ADMIN_PASSWORD in .env)")
    if running_pid():
        if WINDOWS:
            tell("Close the server's window and start OpenDMTQ.exe again: it takes the new password then.")
        else:
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
    import shutil
    unit_dir = os.path.expanduser("~/.config/systemd/user")
    unit = os.path.join(unit_dir, "opendmtq.service")
    # A Linux without systemd (a container, a system with another init) has no systemctl to start it with.
    systemd = shutil.which("systemctl") is not None
    if args.remove:
        if systemd:
            subprocess.run(["systemctl", "--user", "disable", "--now", "opendmtq.service"], capture_output=True)
        if os.path.exists(unit):
            os.remove(unit)
        if systemd:
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        ok("removed the systemd unit")
        return 0
    if not systemd:
        # Said before anything is written: nothing would read the unit here.
        die("this system has no systemd (no systemctl), which starts the server with the computer here; nothing was "
            f"set up. {CLI} start starts it now")
    os.makedirs(unit_dir, exist_ok=True)
    with open(unit, "w", encoding="utf-8") as f:
        f.write(systemd_unit(sys.executable, me, ROOT))
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    taken = subprocess.run(["systemctl", "--user", "enable", "--now", "opendmtq.service"], capture_output=True, text=True)
    if taken.returncode != 0:
        # systemd there, but not this user's (no session of theirs, a container): its own words, and nothing left behind.
        os.remove(unit)
        die(f"systemd did not take the unit ({(taken.stderr or taken.stdout).strip() or 'no reason given'}); nothing was "
            f"set up. {CLI} start starts the server now")
    # Without lingering, a user's services stop when they sign out and start only when they sign in.
    if shutil.which("loginctl"):
        subprocess.run(["loginctl", "enable-linger", os.environ.get("USER", "")], capture_output=True)
    ok(f"starts at boot: {unit} (systemctl --user status opendmtq)")
    return 0


# ------------------------------------------------------------------------------ the server's life: repair, data, uninstall
# The admin pages' Server page does each of these too; here they are for the terminal (and a server that does not start).

def typed_yes(word, question):
    """True when the person types word at the question (a terminal only: a script passes --yes)."""
    if not (sys.stdin and sys.stdin.isatty()):
        die(f"{question} Run it in a terminal to answer, or add --yes")
    try:
        return input(f"{question} Type {word} to go ahead: ").strip().lower() == word
    except EOFError:
        return False


def ask_running_program(name, body):
    """Writes a request for the running server's program (it looks every two seconds), as the Server page does."""
    from .paths import RUN
    with open(os.path.join(RUN, name + ".new"), "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(os.path.join(RUN, name + ".new"), os.path.join(RUN, name))


def cmd_repair(args):
    """Checks and repairs what the server can make again by itself (opendmtq_tools.repair), the app built when it has to
    be; then a running server starts again with all of it."""
    values = require_settings()
    found = programs()
    make_folders()
    status = tool("repair", "--build", values=values, found=found)
    if running_pid():
        # Its programs read what was put back at their start.
        restart_running(values)
    return status


def admin_instance(values):
    """Which run of the admin pages answers (their setup's ping), or None while none does."""
    from .settings import admin_port
    try:
        url = f"http://127.0.0.1:{admin_port(values)}/opendmtq/admin/setup/ping"
        with urllib.request.urlopen(url, timeout=2) as r:
            return json.loads(r.read()).get("instance")
    except (OSError, ValueError, AttributeError):
        return None


def restart_running(values):
    """Asks the running server's program to start every part again, and says so once it has: a new run of the admin pages
    answers and the server is healthy, so that what comes next (a page, a script's next request) finds it whole, never
    the old run on its way out."""
    before = admin_instance(values)
    ask_running_program("restart.request", str(int(time.time())))
    tell("The server is starting again with it.")
    # As long as a slow first start may take three times over (an antivirus looking at every program again, Wine), and
    # the request's own look every two seconds.
    deadline = time.time() + max(3 * START_WAIT, 180)
    while time.time() < deadline:
        now = admin_instance(values)
        if now is not None and now != before and health(values) is not None:
            ok("the server started again with it")
            return
        time.sleep(1)
    ok(f"the server is still starting again; {CLI} status says when it answers")


def data_sizes(values, found):
    """The server's data by part, as opendmtq_tools.server_data counts it: {part: {"bytes", "can_delete"}}."""
    from .folders import tools_env
    e = tools_env(values, found)
    r = subprocess.run([sys.executable, "-I", "-X", "utf8", "-m", "opendmtq_tools.server_data", "sizes"], env=e,
                       capture_output=True, text=True, encoding="utf-8")
    try:
        return json.loads(r.stdout)
    except ValueError:
        die(f"the data could not be counted: {r.stderr.strip()}")


def cmd_delete_data(args):
    """Deletes parts of the server's data (a backup first unless --no-backup): without parts, lists them with their size."""
    values = require_settings()
    found = programs()
    sizes = data_sizes(values, found)
    unknown = [part for part in args.parts if part not in sizes]
    if unknown:
        die(f"no such part: {', '.join(unknown)} (the parts: {', '.join(sizes)})")
    if not args.parts:
        for part, info in sizes.items():
            say(f"{part:<11} {info['bytes'] / 1024 / 1024:>9.1f} MB")
        say(f"\n{CLI} delete-data <part>... deletes those (database recordings songs apps backups logs game), a backup first.")
        return 0
    if not args.yes and not typed_yes("delete", f"Delete {', '.join(args.parts)} for good?"):
        die("nothing was deleted")
    status = tool("server_data", "delete", *args.parts, *([] if args.no_backup else ["--backup"]), values=values, found=found)
    if status != 0:
        die("not everything could be deleted (see above)")
    ok(f"deleted: {', '.join(args.parts)}")
    return 0


def cmd_uninstall(args):
    """Removes the server from this computer: stopped first, then what it set up, then its folder (--keep-data: data/
    and .env stay)."""
    from .remove import uninstall
    what = "OpenDMTQ, keeping data/ and .env," if args.keep_data else "OpenDMTQ and all its data"
    if not args.yes and not typed_yes("uninstall", f"Remove {what} from this computer?"):
        die("nothing was removed")
    if running_pid():
        if WINDOWS:
            # Its window's program stops, then removes it, as the Server page asks it to.
            ask_running_program("uninstall.request", json.dumps({"keep_data": bool(args.keep_data)}))
            ok("the server's window stops, then removes OpenDMTQ")
            return 0
        cmd_stop(args)
    uninstall(bool(args.keep_data))
    return 0
