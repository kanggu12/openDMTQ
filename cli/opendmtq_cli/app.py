"""opendmtq: the one command for running an OpenDMTQ server."""

import argparse
import hashlib
import os
import sys
import time

from . import backup, checks, discover, env, look, system
from .system import DATA, ENV_FILE, ROOT, count, die, ok, step, warn


def require_host():
    """PUBLIC_HOST from .env, or stop with the fix."""
    host = env.load(ENV_FILE).get("PUBLIC_HOST", "")
    problem = env.check_host(host)
    if problem:
        die(f"{problem}; run ./opendmtq setup")
    return host


def ensure_env(host=None, quiet=False, reset=None, adopt=True, retry="./opendmtq setup"):
    """Make sure .env has a usable PUBLIC_HOST; detect it when not given. Returns it.

    A given address must be a LAN address, and the server then listens on its port (the one it has
    now when it names none). Internet addresses go through `expose`, which also sets up what they need.

    reset: settings to write together with the address (expose --off). The address is chosen as if
    they were in .env already, and nothing at all is written when none can be chosen: a .env left
    without an address stops every command, ./opendmtq down included.
    adopt: whether a saved LAN address that this machine no longer uses may be replaced (setup asks).
    Import and restore only say so: moving the server also needs a new app, which `host` builds.
    retry: the command to run again with --host when the address must be given by hand.
    """
    values = env.load(ENV_FILE)
    # As if already written (see reset).
    values.update(reset or {})
    current = values.get("PUBLIC_HOST", "")
    detected = env.detect_host()
    moved = False
    if host:
        problem = env.check_host(host)
        if problem:
            die(problem)
        if not env.is_lan_only(host):
            die(f"{host} is not a local network address. To reach the server from the internet, run "
                f"./opendmtq expose {env.split(host)[0]} instead: it also forwards one port, sets a password "
                "for the app download and keeps the admin pages off the internet")
        # Swapping only the address would keep the exposed port and protections for a LAN address.
        if current and not env.check_host(current) and not env.is_lan_only(current):
            die(f"the server is exposed to the internet as {current}. To go back to the local network, "
                "run ./opendmtq expose --off (then ./opendmtq host <address> for another LAN address)")
        # Without a port, on the port the server has now: for a new one 8791, or the first free one after it when
        # another program has it (not this server itself, whose .env is gone). Port 80 only when named.
        port = env.listen_port(values)
        if (":" not in host and env.check_host(current) and not values.get("LISTEN_PORT") and system.port_busy(port)
                and not system.edge_holds(port)):
            taken = port
            port = system.free_port(port + 1)
            moved = True
            ok(f"port {taken} is taken on this machine: this server uses {port}")
        chosen = env.join(*env.split(host)) if ":" in host else env.join(host, port)
    else:
        # A detected address carries the port the server listens on: for a server set up for the first time, 8791 unless
        # that is taken (another copy of this server, another program), then the first free one after it.
        port = env.listen_port(values)
        # (Not by this server itself, whose .env is gone.)
        if (detected and env.check_host(current) and not values.get("LISTEN_PORT") and system.port_busy(port)
                and not system.edge_holds(port)):
            taken = port
            port = system.free_port(port + 1)
            moved = True
            ok(f"port {taken} is taken on this machine: this server uses {port}")
        found = env.join(detected, port) if detected else None
        chosen = (current if not env.check_host(current) else None) or found
        # A saved LAN address that no longer matches this machine (DHCP change, copied example file).
        # A host name (exposed to the internet) is the user's choice and is left alone; so is a WSL
        # NAT address detected under Docker Desktop, which phones never use.
        if (chosen == current and env.is_lan_only(current) and detected and detected != env.split(current)[0]
                and not env.wsl_nat_address(detected) and not env.has_address(env.split(current)[0])):
            new = env.join(detected, env.split(current)[1])
            warn(f".env says PUBLIC_HOST={current}, but this machine now uses {detected}")
            if not adopt:
                # Keep the address; moving the server is a command of its own.
                print(f"  To move the server there (with a new app for the phones): ./opendmtq host {new}")
            elif sys.stdin.isatty() and input(f"  Use {new} instead? [Y/n] ").strip().lower() in ("", "y", "yes"):
                chosen = new
    if not chosen:
        die(f"could not detect this machine's LAN address; pass it: {retry} --host 192.168.x.y")
    problem = env.check_host(chosen)
    if problem:
        die(problem)
    # An address given by hand is the owner's call (a home network may use 172.16.0.0/12 too).
    if not host and env.wsl_nat_address(env.split(chosen)[0]):
        die(f"{chosen} is WSL's private NAT address and phones cannot reach it. Add networkingMode=mirrored "
            "under [wsl2] in %UserProfile%\\.wslconfig, run `wsl --shutdown` in Windows, then retry. "
            "With Docker Desktop, which publishes ports on Windows itself, NAT mode works too: pass the "
            f"PC's Windows LAN address (ipconfig shows it): {retry} --host 192.168.x.y")
    # The reset settings go into the same write as the address.
    updates = dict(reset or {})
    if not values.get("TZ"):
        # Dates in app file names and the admin pages follow this machine's zone.
        updates["TZ"] = system.host_timezone()
    if chosen != current:
        updates["PUBLIC_HOST"] = chosen
    # An address given by hand brings its port, and so does a port chosen above: the server listens where phones will call.
    port = env.split(chosen)[1]
    if (host or moved) and env.listen_port(values) != port:
        updates["LISTEN_PORT"] = str(port)
    # Asked to start over (expose --off), or never written (a new server, or one set up before .env named its port):
    # whichever port was chosen is written, so compose publishes that one.
    if updates.get("LISTEN_PORT") == "" or not values.get("LISTEN_PORT"):
        updates["LISTEN_PORT"] = str(port)
    # Port 80 named in an address given by hand: the owner's own choice, kept at every start (env.leaves_80).
    if host and ":" in host and port == 80:
        updates[env.CHOSE_80] = "chosen"
    if updates:
        env.save(ENV_FILE, updates)
    if chosen != current:
        ok(f"PUBLIC_HOST={chosen} written to .env")
    elif not quiet:
        ok(f"PUBLIC_HOST {chosen}")
    if "LISTEN_PORT" in updates:
        ok(f"LISTEN_PORT={port} written to .env (the port in the address)")
    return chosen


def have_game_data():
    """True once the client data is imported: the client's patch folder with its manifest (data/content). Without it the
    game cannot start: it downloads the images of its screens from the server."""
    import glob
    return bool(glob.glob(os.path.join(DATA, "content", "web", "patch", "phone_new", "*", "android", "patch_new.csv.lz4")))


def song_count():
    """How many songs are imported (data/content/songs.json); 0 before any song import."""
    import json
    try:
        with open(os.path.join(DATA, "content", "songs.json"), encoding="utf-8-sig") as f:
            songs = json.load(f)
    except (OSError, ValueError):
        return 0
    return len(songs) if isinstance(songs, list) else 0


def has_base():
    base = os.path.join(DATA, "apk", "base")
    return os.path.isdir(base) and any(f.lower().endswith(".apk") for f in os.listdir(base))


def apk_manifest():
    """The newest build's manifest (data/apk/out/latest.json), or None."""
    import json
    try:
        with open(os.path.join(DATA, "apk", "out", "latest.json"), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return None
    return m if isinstance(m, dict) and "host" in m else None


def apk_host():
    """Host the newest APK was built for, or None."""
    m = apk_manifest()
    return m["host"] if m else None


def wait_healthy(timeout=60):
    """Poll the portal until it reports healthy; returns its health dict or None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        h = checks.health()
        if h and h.get("ok"):
            return h
        time.sleep(1)
    return None


def not_healthy():
    """Stop after wait_healthy() gave up, naming the part that is down. The check goes through the
    edge proxy (the public port): when that one stopped, the server's own log shows nothing wrong."""
    edge = system.container_state("edge")
    if edge != "running":
        die(f"the edge proxy, which holds the public port, is {edge or 'not created'}; see ./opendmtq logs edge")
    die("the server did not become healthy within 60 s; see ./opendmtq logs")


def ensure_https(host):
    """Certificates for the HTTPS door (data/https), made or renewed for the address phones use.
    True when the server certificate changed (the edge reads it at start). Without certificates the
    server still runs; browsers then have plain HTTP only."""
    cert = os.path.join(DATA, "https", "serve", "server.crt")

    def current():
        try:
            with open(cert, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except OSError:
            return None

    before = current()
    if system.tool("tls", "--host", host, "--dir", "/data/https").returncode != 0:
        warn("could not make the HTTPS certificates (see above); the server runs with plain HTTP only")
    return current() != before


def restart_server():
    """Recreate the server and admin pages with the current .env; stop when the server does not
    come back."""
    # The song list first: after an import the server must offer what came in.
    if system.tool("songs").returncode != 0:
        die("could not prepare data/custom (see above)")
    ensure_https(env.load(ENV_FILE).get("PUBLIC_HOST", ""))
    # The edge too: it reads the certificate when it starts.
    system.compose("up", "-d", "--force-recreate", "server", "admin", "edge")
    if not wait_healthy():
        not_healthy()


def on_loopback(values):
    """True when this PC reaches the server's one port on its loopback (checks.local_address): published on every address,
    or on a loopback one alone (BIND_ADDRESS). False for a port published on one other address (BIND_ADDRESS, a LAN
    address on a machine the internet reaches): a visit from this PC there comes from that address, and the server takes
    it for one from elsewhere (only its stack's gateway, through which Docker passes a visit to localhost, is the server
    PC's own)."""
    import ipaddress
    try:
        return ipaddress.ip_address(checks.local_address(values)).is_loopback
    except ValueError:
        # A name in BIND_ADDRESS, which Docker would refuse: no loopback to count on.
        return False


def admin_address(values):
    """host:port where this PC reaches the admin pages on the server's one port over plain HTTP, or None where it has no
    such door: on its loopback (a visit to localhost stays on plain HTTP and counts as the server PC's own,
    server/entrypoint.sh), or at BIND_ADDRESS for a local network address, whose pages open from anywhere there; none
    for a port on one other address alone with the pages kept off the local network's plain HTTP."""
    public = values.get("ADMIN_ON_PUBLIC_PORT", "yes") == "yes"
    if on_loopback(values) or (public and env.is_lan_only(values.get("PUBLIC_HOST", ""))):
        return f"{checks.local_address(values)}:{env.listen_port(values)}"
    return None


def admin_link(values):
    """The admin pages' address, to print: on the server's one port, at the address phones use on a local network; on
    an internet address over HTTPS when they are on the public port, else on this PC as localhost, never through a
    proxy; off where Docker hands the server every visit from one address (Docker Desktop, rootless Docker), or where
    the port is published on one other address than this PC's loopback (BIND_ADDRESS), with the way to have them."""
    host = values.get("PUBLIC_HOST", "")
    public = values.get("ADMIN_ON_PUBLIC_PORT", "yes") == "yes"
    if public and env.is_lan_only(host):
        return f"http://{host}/opendmtq/admin/"
    if public:
        return f"https://{env.https_address(host)}/opendmtq/admin/"
    kind = system.cannot_tell()
    if kind:
        return (f"off ({kind} cannot tell this PC's visits from the internet's; ./opendmtq expose "
                f"{env.split(host)[0]} --admin-public puts them on the public port over HTTPS)")
    if not on_loopback(values):
        return (f"off (the port is published on {values.get('BIND_ADDRESS')} alone, where a visit from this PC counts as "
                f"one from elsewhere; ./opendmtq expose {env.split(host)[0]} --admin-public puts them on the public port "
                "over HTTPS)")
    # On a loopback address of its own (BIND_ADDRESS=127.0.0.2), there; else localhost.
    local = checks.local_address(values)
    where = "localhost" if local == "127.0.0.1" else local
    return (f"http://{where}:{env.listen_port(values)}/opendmtq/admin/ on this PC (a visit through a proxy is one "
            "from elsewhere: --admin-public puts them on the public port over HTTPS)")


def admin_answers(values):
    """True once the admin pages answer: at the door this PC has to them (admin_address), else the admin service itself,
    asked from its own container."""
    door = admin_address(values)
    if door:
        return checks.http(f"http://{door}/opendmtq/admin/login")[0] == 200
    import subprocess
    r = subprocess.run(["docker", "exec", system.container("admin"), "python3", "-c",
                        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/opendmtq/admin/login', timeout=3)"],
                       capture_output=True, text=True)
    return r.returncode == 0


def address_lines(host, values, password=False):
    """The block `up` and the setup's end close with: the players' site, the admin pages and the owner's sign-in.
    password: the password itself, beside where it is kept (the setup's end, as a host install's first start and the
    Windows bundle's window show it); else only where it is kept."""
    if password and values.get("ADMIN_PASSWORD"):
        return look.address_block(f"http://{host}/", admin_link(values), values.get("ADMIN_USER") or "admin",
                                  password=values["ADMIN_PASSWORD"], where="kept as ADMIN_PASSWORD in .env")
    return look.address_block(f"http://{host}/", admin_link(values), values.get("ADMIN_USER") or "admin",
                              where="ADMIN_PASSWORD in .env")


def admin_sign_in(values):
    """Where the owner signs in to the admin pages on this PC, and with what: the one address `up`, `status` and the
    setup's end all name (on the server's one port, admin_link), and the ID and where its password is."""
    return f"{admin_link(values)}  (ID {values.get('ADMIN_USER') or 'admin'}, password: ADMIN_PASSWORD in .env)"


def open_firewall(port, internet, replaces=None):
    """Allow phones through the Windows firewall (replaces: the port this server used until now). On trouble, warn with the
    way to do it by hand: the rest of the command (setup, host, expose) still applies."""
    print("Windows will ask for administrator permission once.", flush=True)
    problem = system.run_firewall_script(port=port, internet=internet, replaces=replaces)
    if problem:
        warn(f"the Windows firewall was not opened: {problem}. Phones cannot connect until TCP {port} "
             "is allowed; ./opendmtq firewall tries again")
    else:
        scope = "from anywhere" if internet else "from the local network"
        ok(f"firewall rule in place: {system.firewall_rule_name(port)} ({scope})")


# ----------------------------------------------------------------------------- commands

# The admin pages' own port before 0.11.0 (compose published them on 127.0.0.1:8791): no longer read, taken out of .env.
OLD_ADMIN_KEYS = ("ADMIN_PORT", "ADMIN_BIND")


def leave_port_80():
    """A server whose one port is 80 without its owner having chosen it (env.leaves_80: set up before 0.11.0) moves to
    the port its admin pages had, 8791 unless the owner set another, as `port` moves one: LISTEN_PORT and the port in
    PUBLIC_HOST (a router's own port there stays, env.address_after_80), the app built for the new address at this start,
    the site's download page saying so. Returns the words that say it (this start says them once, status and the Server
    page once each, env.move_off_80_words), or None."""
    values = env.load(ENV_FILE)
    if env.check_host(values.get("PUBLIC_HOST", "")) or not env.leaves_80(values, env.listen_port(values)):
        return None
    old = values["PUBLIC_HOST"]
    # A data/state another user owns (an earlier run with sudo): the way to take it back, before anything moves. The move
    # would otherwise be half made: .env on the new port, and nothing noted to say it at the start, by status and on the
    # Server page, nor for the site's download page to tell players of the new app.
    owner = system.data_owner_problem()
    if owner:
        die(owner)
    # Free, or held by this copy's own admin pages on their port of their own before 0.11.0, which go below.
    port = env.port_after_80(values, lambda p: not system.port_busy(p) or system.admin_holds(p))
    new = env.address_after_80(old, port)
    # The notes first, .env after: when they cannot be written, nothing has moved, and the next start moves it.
    try:
        env.note_move_off_80(os.path.join(DATA, "state"), old, new, port=port)
    except OSError as e:
        die(f"the move off port 80 could not be noted in data/state ({e.strerror or e}); nothing moved yet. "
            "./opendmtq up moves it once data/state can be written")
    env.save(ENV_FILE, {"PUBLIC_HOST": new, "LISTEN_PORT": str(port)})
    # Their old container holds the port the edge now takes (127.0.0.1:ADMIN_PORT): it goes first, made again by up.
    if system.admin_holds(port):
        system.compose("rm", "-sf", "admin")
    return env.move_off_80_words({"to": port, "address": new}, start=True)


def cmd_up(args):
    # Off port 80 first, while .env still names the admin pages' old port (the one it moves to).
    moved = leave_port_80()
    host = require_host()
    # A server set up before 0.11.0: its admin pages are on the server's one port now, and nothing answers on their old
    # one; the lines that named it go, so that nobody looks for them there.
    env.drop(ENV_FILE, OLD_ADMIN_KEYS)
    # The wordmark with this copy's version, once (setup shows it first and comes here after).
    look.banner(system.code_version())
    if moved:
        for line in moved:
            ok(line)
        # The rule for phones on WSL follows the server's port, as `port` moves it (a router's own port in the address
        # is the router's); --no-firewall (up's, or the setup's that comes here) leaves Windows' firewall alone.
        if env.is_wsl() and not getattr(args, "no_firewall", False):
            open_firewall(env.listen_port(env.load(ENV_FILE)), internet=not env.is_lan_only(host), replaces=80)
    if not have_game_data():
        die("no client data yet; run ./opendmtq import <folder with your game files>")
    # Folders the containers mount must exist and belong to the user they run as, not be created by
    # docker as root; and after a run with sudo they may belong to another user.
    system.make_data_dirs()
    owner = system.data_owner_problem()
    if owner:
        die(owner)
    system.build("server", "builder", "admin")
    # The song list the server reads (shipped plus songs added on the admin page), rebuilt every time
    # so re-imported game files are picked up. Quick: only missing thumbnails are made.
    if system.tool("songs").returncode != 0:
        die("could not prepare data/custom (see above)")
    renewed = ensure_https(host)
    # An admin password, created once.
    if not env.load(ENV_FILE).get("ADMIN_PASSWORD"):
        import secrets
        env.save(ENV_FILE, {"ADMIN_PASSWORD": secrets.token_urlsafe(12)})
    # The builder's status file and log keep earlier runs: this run's are the ones from now on.
    since = time.time()
    system.compose("up", "-d", "--quiet-pull", "server", "builder", "admin", "edge")
    if renewed:
        # A running edge keeps the certificate it started with; the server offers the new authority.
        system.compose("up", "-d", "--force-recreate", "server", "edge")
    h = wait_healthy()
    if not h:
        not_healthy()
    ok(f"server up: http://{host}/  ({h['songs']} songs, {h['players']} players)")
    https = not checks.https_problem(host)
    if https:
        ok(f"HTTPS on the same port: https://{env.https_address(host)}/  (own certificate: browsers warn "
           f"once; a phone that installs http://{host}/ca.crt does not; its fingerprint: ./opendmtq doctor)")
    values = env.load(ENV_FILE)
    # The admin service starts a few seconds after the server; wait so the link works at once (at this PC's door to
    # them, the address BIND_ADDRESS narrows the port to among them, or the service itself where this PC has none).
    for _ in range(30):
        if admin_answers(values):
            break
        time.sleep(1)
    else:
        warn("admin pages are not answering yet; see ./opendmtq logs admin")
    # The addresses and the owner's sign-in, as status and the setup's end name them too.
    print()
    for line in address_lines(host, values):
        print(line)
    # An owner's ID the players' site does not take: said with the sign-in, as the admin pages' Status page says it.
    problem = env.owner_id_problem(values)
    if problem:
        warn(problem)
    wait_builder(since)
    if checks.app_lacks_runtime():
        warn(checks.no_runtime_notice())


def wait_builder(since=None):
    """Wait for the server-side app build and report its outcome; True when it built a new app.

    since: when this run of the builder was started (Unix seconds). Its status file
    (data/apk/out/build.json) and its container's log also hold earlier runs; only this one counts.
    """
    import subprocess
    r = subprocess.run(["docker", "wait", system.container("builder")], capture_output=True, text=True)
    status = checks.build_status()
    # Written before this run started: an earlier run's (this one could not write it). A few seconds
    # of slack for clocks that differ between the host and Docker's machine (Docker Desktop).
    if status and since is not None and status["time"] < since - 5:
        status = None
    state = (status or {}).get("state")
    if r.stdout.strip() != "0":
        # The builder's own reason, the one the admin pages and doctor show too.
        reason = status.get("error") if state == "failed" else None
        die("the app build failed" + (f": {reason}" if reason else "") + "; see ./opendmtq logs builder")
    if state == "done":
        # "file": this run made a new app; without it the app was already up to date.
        if status.get("file"):
            ok(f"app built: data/apk/out/{status['file']}")
            return True
        ok(f"app for http://{status.get('host')}/ is up to date")
        return False
    # No status from this run (a builder image from before build.json, or one that could not write it):
    # this run's own output, stdout only. The builder's complaints go to stderr, and docker logs would
    # put them after every line of stdout, as if they were the last thing it said.
    logs = subprocess.run(["docker", "logs", *(["--since", str(int(since) - 5)] if since else []), system.container("builder")],
                          capture_output=True, text=True)
    lines = [l for l in logs.stdout.splitlines() if l.startswith(("builder:", "done"))]
    last = lines[-1] if lines else ""
    if last.startswith("done"):
        # "done     data/apk/out/<file>"
        ok(f"app built: {last.split(None, 1)[-1]}")
        return True
    if last:
        # "builder: app for http://<address>/ is up to date"
        ok(last.removeprefix("builder: "))
    return False


def cmd_down(args):
    # Stop first: with nothing writing, a plain copy of the database is consistent, and an online
    # snapshot that fails (a large database, a full disk) cannot keep the server from stopping.
    system.compose("down")
    path = backup.create("stop")
    if path:
        ok(f"backup {os.path.relpath(path, ROOT)}")


def cmd_restart(args):
    cmd_down(args)
    cmd_up(args)


def cmd_status(args):
    host = env.load(ENV_FILE).get("PUBLIC_HOST", "?")
    look.banner(system.code_version())
    if host == "?":
        print("Not set up yet. Start with: ./opendmtq setup\n")
    state = system.container_state()
    # Label and value lines in one column, a state in its colour (look.rows).
    lines = [("server", (state, "ok") if state == "running" else (state or "not created", "warn"))]
    h = checks.health() if state == "running" else None
    if h:
        lines += [("address", f"http://{h['host']}/"), ("content", f"{h['songs']} songs, patch {h['patch']}"),
                  ("players", str(h["players"]))]
    m = apk_manifest()
    apk = m["host"] if m else None
    note = ""
    if apk and apk != host:
        note = "  (STALE: run ./opendmtq apk)"
    elif m and checks.key_problem(m):
        note = "  (signing key problem: see ./opendmtq doctor)"
    lines.append(("apk", (f"{'built for ' + apk if apk else 'not built'}{note}", "warn" if note or not apk else "ok")))
    # The builder's last run for this address failed: `up` stops on it, and players may be told to
    # ask the owner. Also when an earlier app is still offered.
    failed = checks.build_problem(host) if host != "?" else None
    if failed:
        lines.append(("build", (f"FAILED: {failed} (./opendmtq logs builder)", "bad")))
    files = backup.listing()
    lines.append(("backups", f"{len(files)}{', newest ' + files[0] if files else ''}"))
    # Where to sign in on this PC, as up and the setup's end say it: once there is a server to sign in to.
    if host != "?":
        lines.append(("admin", admin_sign_in(env.load(ENV_FILE))))
    for line in look.rows(lines):
        print(line)
    # A move off port 80 at the first start of this version, said here once too.
    moved = env.move_off_80_unsaid(os.path.join(DATA, "state"), "status")
    if moved:
        first, *rest = env.move_off_80_words(moved)
        print("\n" + " ".join([first + "."] + rest))


def cmd_logs(args):
    extra = ["-f"] if args.follow else []
    try:
        system.compose("logs", "--tail", str(args.tail), *extra, args.service, check=False)
    except KeyboardInterrupt:
        # Ctrl-C is how following ends.
        print()
    return 0


def cmd_import(args):
    src = os.path.abspath(os.path.expanduser(args.path))
    if not os.path.exists(src):
        die(f"{src} does not exist")
    # compose needs PUBLIC_HOST to parse the file at all. A saved address is kept even when this
    # machine now uses another one: the server would move without a new app (`host` does both).
    ensure_env(quiet=True, adopt=False)
    os.makedirs(os.path.join(DATA, "apk", "base"), exist_ok=True)
    # The client data unless --no-game-data, the song data with --songs; with --check only what each file is.
    extra = {"IMPORT_FROM": src, "IMPORT_SONGS": "yes" if getattr(args, "songs", False) else "no",
             "IMPORT_GAME": "no" if getattr(args, "no_game_data", False) else "yes"}
    checking = getattr(args, "check", False)
    if checking:
        extra["IMPORT_CHECK"] = "yes"
    names = getattr(args, "names", None)
    inside = os.path.relpath(src, DATA)
    if names:
        # Only these files in the folder (what setup's search matched), not everything else there:
        # other archives would be opened and other clients imported. No file name holds a "/".
        extra["IMPORT_ONLY"] = "/".join(names)
    elif not inside.startswith(".."):
        # A folder inside data/ (data/server of an earlier OpenDMTQ) is read where it is: its files are linked into
        # data/content instead of copied, on the same disk.
        extra["IMPORT_DATA"] = inside
    elif os.path.isfile(src) or os.path.basename(os.path.normpath(src)) == "DMQ":
        # A single file is imported by mounting its folder and naming the file. So is the songs' folder itself (DMQ):
        # the jackets (viewImg) and the song list (_info) are beside it, in the folder mounted.
        extra.update({"IMPORT_FROM": os.path.dirname(os.path.normpath(src)), "IMPORT_ONLY": os.path.basename(os.path.normpath(src))})
    # What it says it reads, by the path on this PC: the container sees the folder as /in (IMPORT_SHOWN, importer.py).
    extra["IMPORT_SHOWN"] = extra["IMPORT_FROM"]
    # In its own service: 7-Zip opens the owner's archives there, out of sight of the keys, the
    # backups, the database and what phones download (compose.yaml, service "importer").
    r = system.tool("importer", extra_env=extra, as_invoker=True, service="importer")
    if r.returncode == 1:
        die("nothing usable was found there (see the lines above)")
    if r.returncode != 0:
        die("the import failed (see the error above)")
    if checking:
        return
    # The song list and the client's tables follow what came in at once; the app for phones is rebuilt at the next up.
    if system.container_state() == "running":
        restart_server()


def cmd_apk(args, show_qr=True):
    host = require_host()
    name = getattr(args, "base", None)
    if name:
        # The choice is kept as BASE_APK: the builder at every start, the admin pages and later builds
        # then use the same client, instead of stopping on the others in data/apk/base or going back
        # to another one without a word.
        folder = os.path.join(DATA, "apk", "base")
        if os.sep in name or not os.path.isfile(os.path.join(folder, name)):
            there = sorted(f for f in os.listdir(folder) if f.lower().endswith(".apk")) if os.path.isdir(folder) else []
            die(f"{name}: no such file in data/apk/base; there: {', '.join(there) or 'nothing'}")
        env.save(ENV_FILE, {"BASE_APK": name})
        ok(f"BASE_APK={name} written to .env")
    # Same builder the server runs on start, forced; it records its outcome in build.json.
    r = system.tool("builder", "--force")
    if r.returncode != 0:
        die("APK build failed (see above)")
    if show_qr:
        where = "same Wi-Fi" if env.is_lan_only(host) else "from anywhere"
        print(f"\nOn the phone, open http://{host}/ ({where}), sign in and tap Download app (.apk), or scan:", flush=True)
        system.tool("qr", f"http://{host}/")


def cmd_qr(args):
    host = require_host()
    system.tool("qr", f"http://{host}/")


def cmd_host(args):
    values = env.load(ENV_FILE)
    current = values.get("PUBLIC_HOST", "")
    if not args.address:
        detected = env.detect_host()
        print(f"PUBLIC_HOST {current or '(unset)'}; this machine uses {detected or '?'}")
        return
    port = env.listen_port(values)
    if args.address == current and env.split(current)[1] == port:
        ok(f"PUBLIC_HOST is already {current}")
        return
    moved = ensure_env(args.address) != current
    # The server's URLs depend on the address, and LISTEN_PORT on the port.
    if system.container_state() == "running":
        restart_server()
    # The client's literals depend on the address only.
    if moved:
        cmd_apk(args)
    new_port = env.listen_port(env.load(ENV_FILE))
    if env.is_wsl() and new_port != port:
        open_firewall(new_port, internet=False, replaces=port)
    if moved:
        # What happens to the phones: the new app goes over theirs, which keeps each device's account.
        print("\nPhones install the new app over the old one, which keeps each device's account.")


def cmd_port(args):
    """Show the server's one port, or move the server to another (LISTEN_PORT, and the port in PUBLIC_HOST): from the next
    start, with the app built again for the new address, which the site's download page then tells players to install. A
    port another program holds is refused, in words."""
    values = env.load(ENV_FILE)
    current = values.get("PUBLIC_HOST", "")
    if env.check_host(current):
        die("no address set up yet; run ./opendmtq setup")
    now = env.listen_port(values)
    if args.port is None:
        print(f"port {now}: the game, the players' site (http://{current}/), the admin pages and the API")
        return
    if not 1 <= args.port <= 65535:
        die("a port is a number from 1 to 65535")
    if args.port == now:
        ok(f"the server is on port {now} already")
        return
    # This copy's own edge holds the port it serves now; any other program's port is refused.
    if system.port_busy(args.port) and not system.edge_holds(args.port):
        die(f"port {args.port} is taken on this computer by another program; choose another")
    # A router's own port in an internet address stays, with the app phones have (env.port_move).
    new, stays, router = env.port_move(current, now, args.port)
    # Port 80 by the owner's own choice: kept at every start (a server only set up on it before 0.11.0 moves off it).
    env.save(ENV_FILE, {"PUBLIC_HOST": new, "LISTEN_PORT": str(args.port),
                        **({env.CHOSE_80: "chosen"} if args.port == 80 else {})})
    if args.port != 80:
        env.drop(ENV_FILE, (env.CHOSE_80,))
    if stays:
        ok(f"the server moves to port {args.port} at its next start; its address stays http://{new}/")
    else:
        ok(f"the server moves to port {args.port} at its next start: http://{new}/")
    # The rule for phones on WSL follows the port now: the next start needs it.
    if env.is_wsl():
        open_firewall(args.port, internet=not env.is_lan_only(new), replaces=now)
    if stays:
        lines = ["./opendmtq restart (or up) starts it there; phones keep the app they have."]
    else:
        lines = ["./opendmtq restart (or up) starts it there and builds the app for the new address.",
                 "Players install the new app over the old one, which keeps each device's account; the site's download "
                 "page says so."]
    if router:
        lines.append(router)
    print()
    for line in lines:
        print(line)


def cmd_password(args):
    """Change the owner's password (ADMIN_PASSWORD in .env), which with the owner's ID (ADMIN_USER) opens the admin pages
    and the players' site: typed twice on a terminal, or one made when nothing is typed or there is no terminal (a
    script). The admin pages take it when they start, so a running admin service is started again with it; the owner's
    sign-ins made with the old one end, as on the Server page."""
    import getpass
    import re
    import secrets
    values = env.load(ENV_FILE)
    if env.check_host(values.get("PUBLIC_HOST", "")):
        die("no server set up yet; run ./opendmtq setup")
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
    user = values.get("ADMIN_USER") or "admin"
    if system.container_state("admin") == "running":
        # The admin service reads the password from its environment at its start: a new container with the new one. The
        # owner's sign-in for the players' site is written again as it starts.
        system.compose("up", "-d", "--force-recreate", "admin")
        ok(f"the owner's password is changed: ID {user}, for the admin pages and the players' site")
    else:
        ok(f"the owner's password is changed: ID {user}, from the server's next start (./opendmtq up)")
    if made:
        print(f"\nThe new password: {new}  (kept as ADMIN_PASSWORD in .env)")


def cmd_name(args):
    values = env.load(ENV_FILE)
    current = values.get("SERVER_NAME", "")
    if args.name is None:
        print(f"SERVER_NAME {current or '(unset: the address)'}; on phones the app is TECHNIKA Q (name)")
        return
    name = args.name.strip()
    if len(name) > 80 or not name.isprintable() or any(c in name for c in "\"'$`\\#"):
        die("the name must be at most 80 printable characters, without quotes, $, # or backslashes")
    if name == current:
        ok(f"SERVER_NAME is already {name or '(unset)'}")
        return
    env.save(ENV_FILE, {"SERVER_NAME": name})
    # The portal shows the name, and the app carries it.
    if system.container_state() == "running":
        restart_server()
    cmd_apk(args)
    # What happens to the phones: the new app goes over theirs, which keeps each device's account.
    print("\nPhones install the new app over the old one, which keeps each device's account.")


def cmd_check(args):
    if args.url:
        # Another deployment (a Kubernetes router, say): check it instead of the local container.
        checks.OTHER = args.url.rstrip("/")
    elif system.container_state() != "running":
        die("the server is not running; ./opendmtq up")
    failures = checks.end_to_end()
    print(f"\nRESULT: {'PASS' if not failures else f'FAIL ({failures})'}")
    return 1 if failures else 0


def cmd_doctor(args):
    failures = checks.doctor()
    if failures:
        print(f"\n{failures} problem(s) above.")
    elif checks.EXTERNAL_UNTESTED:
        print("\nAll good here; reachability from the internet was not tested (see the warning).")
    else:
        print("\nAll good.")
    return 1 if failures else 0


def cmd_backup(args):
    path = backup.create("manual")
    if not path:
        die("no database yet (it is created on the first ./opendmtq up)")
    ok(f"backup {os.path.relpath(path, ROOT)}")


def cmd_backups(args):
    files = backup.listing()
    print("\n".join(files) if files else "no backups yet")


def rebuild_with_restored_key():
    """Phones' apps are signed with the restored key: have the builder sign the app the server
    offers with it too (it rebuilds when the key changed), so it installs over theirs."""
    if not has_base():
        print("  The first app build (./opendmtq setup) signs with the restored key, so the app installs "
              "over phones' existing one.")
        return
    if system.tool("builder").returncode != 0:
        die("the app could not be rebuilt with the restored key (see above); fix that, then ./opendmtq apk")
    ok("the app the server offers is signed with the restored key; phones install it over theirs")


def cmd_restore(args):
    # The archive first: a misspelt name must change nothing (and push no backup out).
    path = backup.locate(args.name)
    # compose needs PUBLIC_HOST even to run the copy job (a new machine may not have run setup yet).
    # A saved address is kept: the server is only stopped and started again, with its old settings.
    ensure_env(quiet=True, adopt=False)
    running = system.container_state() == "running"
    # Safety copy of what is about to be replaced; the pruning keeps the archive being restored.
    saved = backup.create("before-restore", protect=path)
    if saved:
        ok(f"current state saved as {os.path.relpath(saved, ROOT)}")
    if running:
        system.compose("stop", "server")
    back = True
    try:
        key = backup.restore(path, with_key=args.with_key)
        ok(f"restored {os.path.basename(path)}" + (" and its signing key" if key else ""))
    finally:
        # Whatever happened, leave the server as it was found.
        if running:
            system.compose("start", "server")
            back = wait_healthy() is not None
            if not back:
                warn("the server did not become healthy within 60 s after the restore; see ./opendmtq logs")
    if key:
        rebuild_with_restored_key()
    return 0 if back else 1


# ----------------------------------------------------------------------------- the server's life: repair, data, uninstall
# The admin pages' Server page names these commands: in containers it cannot rebuild the images, delete the game files it
# only reads, or remove the containers it runs in.

# Where the tools container sees each part of the server's data (compose.yaml, service "tools": data/ is /data there), for
# opendmtq_tools.server_data and opendmtq_tools.repair.
TOOLS_PATHS = {"OPENDMTQ_DB": "/data/state/dmtq.db3", "OPENDMTQ_APK": "/apk", "OPENDMTQ_BACKUPS": "/data/backups",
               "OPENDMTQ_CUSTOM": "/custom", "OPENDMTQ_LOGS": "/data/state/logs", "OPENDMTQ_CONTENT": "/data/content"}

# The parts of the data, in the Server page's order (tools/opendmtq_tools/server_data.py PARTS).
DATA_PARTS = ("database", "recordings", "songs", "apps", "backups", "logs", "game")


def typed_yes(word, question):
    """True when the person types word at the question (a terminal only: a script passes --yes)."""
    if not sys.stdin.isatty():
        die(f"{question} Run it in a terminal to answer, or add --yes")
    try:
        return input(f"{question} Type {word} to go ahead: ").strip().lower() == word
    except EOFError:
        return False


def program_files_changed():
    """The program's tracked files that differ from the commit (a clone: git knows them), or None where git cannot say."""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--untracked-files=no"], capture_output=True,
                           text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return [line[3:] for line in r.stdout.splitlines() if line.strip()]


def cmd_repair(args):
    """Checks and repairs the server: its folders and their owner, the images (built again from this folder), the HTTPS
    certificates, the database's integrity, the owner's sign-in for the players' site, the song list; then the server
    started again with all of it, and the phone app built when it has to be."""
    host = require_host()
    system.make_data_dirs()
    owner = system.data_owner_problem()
    if owner:
        die(owner)
    ok("folders in place")
    changed = program_files_changed()
    if changed:
        warn(f"files changed from this folder's commit: {', '.join(changed[:8])}{' ...' if len(changed) > 8 else ''}"
             " (git checkout -- <file> puts one back)")
    elif changed == []:
        ok("program files as the commit has them")
    system.build("server", "builder", "admin")
    ok("images built from this folder")
    ensure_https(host)
    # The steps that look at the data, in the tools container as the admin pages run them.
    values = env.load(ENV_FILE)
    extra = dict(TOOLS_PATHS, ADMIN_USER=values.get("ADMIN_USER", ""), ADMIN_PASSWORD=values.get("ADMIN_PASSWORD", ""))
    status = system.tool("repair", container_env=extra).returncode
    # Every part again, with the images and certificates as they are now; the builder makes the app when it has to.
    since = time.time()
    system.compose("up", "-d", "--force-recreate", "server", "admin", "edge")
    system.compose("up", "-d", "builder")
    if not wait_healthy():
        not_healthy()
    ok("the server runs again")
    wait_builder(since)
    return status


def cmd_delete_data(args):
    """Deletes parts of the server's data (a backup first unless --no-backup); without parts, lists them with their size."""
    import json as jsonlib
    require_host()
    unknown = [part for part in args.parts if part not in DATA_PARTS]
    if unknown:
        die(f"no such part: {', '.join(unknown)} (the parts: {', '.join(DATA_PARTS)})")
    if not args.parts:
        r = system.tool("server_data", "sizes", container_env=TOOLS_PATHS, capture=True)
        try:
            sizes = jsonlib.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            die(f"the data could not be counted: {(r.stderr or r.stdout).strip()}")
        for part in DATA_PARTS:
            print(f"{part:<11} {sizes[part]['bytes'] / 1024 / 1024:>9.1f} MB")
        print("\n./opendmtq delete-data <part>... deletes those, a backup first.")
        return 0
    if not args.yes and not typed_yes("delete", f"Delete {', '.join(args.parts)} for good?"):
        die("nothing was deleted")
    keep = []
    if not args.no_backup:
        made = backup.create("before-delete")
        if made:
            ok(f"backup {os.path.relpath(made, ROOT)}")
            keep = ["--keep", os.path.basename(made)]
    # In the tools container, as the server's own files are seen there; while the server runs, as on the admin pages.
    status = system.tool("server_data", "delete", *args.parts, *keep, container_env=TOOLS_PATHS).returncode
    if status != 0:
        die("not everything could be deleted (see above)")
    if "songs" in args.parts or "game" in args.parts:
        # The song list without them, read by the server at once.
        system.tool("songs")
    ok(f"deleted: {', '.join(args.parts)}")
    if "apps" in args.parts and system.container_state() == "running":
        # The app for players again, as at every start.
        since = time.time()
        system.compose("up", "-d", "builder")
        wait_builder(since)
    return 0


def remove_path_link():
    """The opendmtq command on the PATH (cli/install.sh put it there), when it is this folder's: without a password asked
    for, where sudo needs one it is said instead."""
    import subprocess
    for folder in ("/usr/local/bin", os.path.expanduser("~/.local/bin")):
        link = os.path.join(folder, "opendmtq")
        if not (os.path.islink(link) and os.path.realpath(link) == os.path.realpath(os.path.join(ROOT, "opendmtq"))):
            continue
        try:
            os.remove(link)
        except OSError:
            if subprocess.run(["sudo", "-n", "rm", "-f", link], capture_output=True).returncode != 0:
                warn(f"{link} stays (sudo rm {link} removes it)")
                continue
        ok(f"removed {link}")


def cmd_uninstall(args):
    """Removes this server: its containers and their network, the images built for it, the Windows firewall rule its setup
    made (WSL), the command on the PATH, and its folder (--keep-data: data/ and .env stay)."""
    import shutil
    import subprocess
    keep = bool(args.keep_data)
    what = "this server, keeping data/ and .env," if keep else "this server and all its data"
    if not args.yes and not typed_yes("uninstall", f"Remove {what} from this computer?"):
        die("nothing was removed")
    values = env.load(ENV_FILE)
    images = system.image_names()
    # The containers and their network: stopped and gone.
    system.compose("--profile", "tools", "down", "--volumes", "--remove-orphans", check=False)
    ok("containers removed")
    if not keep:
        # What the containers wrote may not be this user's (an earlier run with sudo): removed from inside the server's
        # image, while it is still here.
        shutil.rmtree(DATA, ignore_errors=True)
        if os.path.exists(DATA):
            subprocess.run(["docker", "run", "--rm", "-u", "0", "-v", f"{DATA}:/d", "--entrypoint", "sh", images[0], "-c",
                            "rm -rf /d/* /d/.[!.]*"], capture_output=True)
            shutil.rmtree(DATA, ignore_errors=True)
    for image in images:
        # An image another copy still uses stays: docker refuses it.
        if subprocess.run(["docker", "image", "rm", image], capture_output=True).returncode == 0:
            ok(f"removed the image {image}")
    # The Windows firewall rule the setup made under WSL, when there is one: Windows asks for permission to remove it.
    if env.is_wsl() and values.get("PUBLIC_HOST") and system.firewall_rule_exists(env.listen_port(values)):
        problem = system.run_firewall_script(port=env.listen_port(values), remove=True)
        if problem:
            warn(f"the Windows firewall rule stays: {problem}")
        else:
            ok(f"removed the firewall rule {system.firewall_rule_name(env.listen_port(values))}")
    remove_path_link()
    # The folder last: this command runs from it, which Linux and macOS allow.
    for name in os.listdir(ROOT):
        if keep and name in ("data", ".env"):
            continue
        path = os.path.join(ROOT, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass
    if keep:
        ok(f"removed the program from {ROOT}; data/ and .env stay there")
    else:
        try:
            os.rmdir(ROOT)
            ok(f"removed {ROOT}")
        except OSError:
            warn(f"{ROOT} is not quite empty: something else put files there")
    print("OpenDMTQ is uninstalled.")
    return 0


def cmd_firewall(args):
    if not env.is_wsl():
        die("the firewall command is for WSL on Windows; on Linux, open the port in your own firewall if you use one")
    values = env.load(ENV_FILE)
    host = values.get("PUBLIC_HOST", "")
    # The rule's scope follows the address; without one it would be opened from anywhere.
    if not args.remove and env.check_host(host):
        die("no address set up yet; run ./opendmtq setup (it opens the firewall too)")
    port = env.listen_port(values)
    internet = not env.is_lan_only(host)
    print("Windows will ask for administrator permission once.", flush=True)
    problem = system.run_firewall_script(port=port, internet=internet, remove=args.remove)
    if problem:
        die(problem)
    scope = "from anywhere" if internet else "from the local network"
    ok(f"firewall rule {'removed' if args.remove else 'in place'}: {system.firewall_rule_name(port)} ({scope})")


def forward_target(before):
    """This PC's LAN address, for the router's port forward, or None when it is not known. Never
    WSL's NAT address (WSL under Docker Desktop): no router reaches that one; the Windows address,
    which setup was given with --host, is the one."""
    detected = env.detect_host()
    if detected and not env.wsl_nat_address(detected):
        return detected
    # The LAN address the server had before it was exposed.
    if before and env.is_lan_only(before):
        return env.split(before)[0]
    return None


def cmd_expose(args):
    """Make the server reachable from the internet under a host name (DDNS or your domain)."""
    values = env.load(ENV_FILE)
    before = (values.get("PUBLIC_HOST", ""), env.listen_port(values))
    if not args.off and not args.name:
        die("give the host name that points at your public IP: ./opendmtq expose myhome.example.com")
    if args.off:
        # Back to the local network: no password, admin pages on the main port, port 8791 unless taken, and
        # the address picked as setup picks it (detected, or --host). All of it is written together, once
        # an address is found: the exposed server keeps running meanwhile, and a .env without an
        # address would leave no command, ./opendmtq down included, able to reach it.
        lan = ensure_env(host=args.host, quiet=True, retry="./opendmtq expose --off",
                         reset={"PUBLIC_HOST": "", "LISTEN_PORT": "", "ADMIN_ON_PUBLIC_PORT": "yes"})
        ok(f"back to the local network: http://{lan}/")
    else:
        address = env.join(args.name, args.port)
        problem = env.check_host(address)
        if problem:
            die(problem)
        # The admin pages: off the internet unless asked; on it, over the HTTPS door. Port 80 given with --port is the
        # owner's own choice, kept at every start.
        env.save(ENV_FILE, {"PUBLIC_HOST": address, "LISTEN_PORT": str(args.port),
                            "ADMIN_ON_PUBLIC_PORT": "yes" if args.admin_public else "no",
                            **({env.CHOSE_80: "chosen"} if args.port == 80 else {})})
        ok(f"PUBLIC_HOST={address}, listening on TCP {args.port}")
        ok("the site is for accounts made on the admin pages' Accounts page; nobody makes their own")
        if args.admin_public:
            ok(f"admin pages: https://{env.https_address(address)}/opendmtq/admin/ once HTTPS is up (own certificate, "
               "see docs/internet.md#https)")
        else:
            # Off where Docker hands the server every visit from one address of its own (Docker Desktop, rootless
            # Docker); else on this PC, not through a proxy (admin_link says each).
            ok(f"admin pages: {admin_link(env.load(ENV_FILE))}")
    values = env.load(ENV_FILE)
    after = (values["PUBLIC_HOST"], env.listen_port(values))
    # New settings: restart (the builder rebuilds the app when the address changed), open the
    # firewall, then say what is left to do.
    built = False
    if system.container_state() == "running" or have_game_data():
        restart_server()
        # This run of the builder, not an earlier one, is the one to report.
        since = time.time()
        system.compose("up", "-d", "builder")
        built = wait_builder(since)
    if env.is_wsl() and not args.no_firewall:
        open_firewall(after[1], internet=not env.is_lan_only(after[0]), replaces=before[1])
    if not args.off:
        if after != before:
            target = forward_target(before[0]) or "its LAN address; on Windows, ipconfig shows it"
            print(f"\nNext, on the router(s): forward TCP {after[1]} to this PC ({target}).\n"
                  "With chained routers, add the rule on each one (docs/internet.md).")
        print("\nCheck from outside: ./opendmtq doctor")
    if built:
        print("Phones install the new app over the old one, which keeps each device's account.")


def cmd_runtime(args):
    """The runtime that lets newer phones run the game and adds broadcasts on the others, and the app with it. The builder
    adds it by itself when there is none: this is for the newest one after an update of this repository, or (--build) one
    made here from this source."""
    if args.build:
        # The tools image's own copy would replace it at the next build, a moment after saying it is built.
        if env.load(ENV_FILE).get("OPENDMTQ_TOOLS_IMAGE"):
            die("this server runs a release's tools image, whose runtime would replace one made here. To make your own, take "
                "OPENDMTQ_TOOLS_IMAGE out of .env first")
        print("  Building it in a container. The first time takes some minutes and downloads about 1 GB (the Android NDK and "
              "Android's 32-bit libraries); later builds take seconds.", flush=True)
        if system.run_bundle() != 0:
            warn("the arm32 runtime could not be built (see above); the app stays as it is")
            return 1
        ok("arm32 runtime built")
    # From the latest release, unless this server has a copy at hand (docs/closed-network.md).
    elif system.tool("runtime", "--refresh").returncode != 0:
        warn("the arm32 runtime could not be had (see above); the app stays as it is. "
             "./opendmtq runtime --build makes it here from this source")
        return 1
    cmd_apk(argparse.Namespace(base=None), show_qr=False)
    return 0


# Jobs of .github/workflows/release.yml that are no tests of the commit themselves.
RELEASE_JOBS = ("qa", "publish")


def commit_gates(sha):
    """What stands against this commit going live, in words: CI on GitHub and the local quality gate (tests/qa.sh)."""
    def ask(path, query):
        r = system.run_program(["gh", "api", f"repos/{{owner}}/{{repo}}/commits/{sha}/{path}", "--jq", query], cwd=ROOT)
        return r.stdout.strip() if r and r.returncode == 0 else None

    # Everything CI ran on this commit: finished, and nothing that went wrong.
    runs = ask("check-runs?per_page=100", '.check_runs[] | "\\(.name)=\\(.status)/\\(.conclusion)"')
    if runs is None:
        return ["cannot ask GitHub about this commit: is gh signed in, and is the commit pushed?"]
    problems = []
    if not runs:
        problems.append("CI has not run on this commit")
    for line in runs.splitlines():
        name, _, state = line.partition("=")
        # The release workflow's own steps, when it has run on this commit: its gate may have been tried before tests/qa.sh.
        if name in RELEASE_JOBS:
            continue
        if state not in ("completed/success", "completed/skipped"):
            problems.append(f"CI: {name} is {state}")
    status = ask("status", '[.statuses[] | select(.context == "qa/local")][0].state')
    if status != "success":
        problems.append(f"the local quality gate has not passed on this commit (tests/qa.sh; it is {status or 'not run'})")
    return problems


def players_now():
    """How many players are in a song or on air right now, by the server's own table; None when it cannot be asked."""
    code = ('$d = new SQLite3("/data/dmtq.db3", SQLITE3_OPEN_READONLY); $d->busyTimeout(3000);'
            'echo (int)$d->querySingle("SELECT COUNT(*) FROM LiveSwitch WHERE playing = 1 AND play_at > strftime(\'%s\', \'now\') - 900");')
    r = system.compose("exec", "-T", "server", "php", "-r", code, check=False, capture=True)
    return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else None


def cmd_deploy(args):
    """This commit on the live server: only what passed its tests, not over anyone's song, a backup first, and checked after."""
    sha = system.git("rev-parse", "HEAD")
    if not sha:
        die("this copy is no git checkout: use ./opendmtq up")
    if system.git("status", "--porcelain"):
        die("the tree has changes that are not committed: a deploy is of a commit (./opendmtq up runs what is here)")
    if args.no_gates:
        warn("not asking whether this commit passed its tests (--no-gates)")
    else:
        problems = commit_gates(sha)
        if problems:
            for problem in problems:
                warn(problem)
            die("not deploying this commit; --no-gates goes ahead anyway")
        ok("CI and the local quality gate passed on this commit")
    # The images first: it takes minutes, and whoever starts a song meanwhile counts. A failure here stops the deploy, or the
    # old code would go on running under this commit's name.
    system.build("server", "builder", "admin", strict=True)
    if system.container_state() == "running":
        playing = players_now()
        if playing and not args.now:
            die(f"{playing} player(s) in a song right now: try again later; --now goes ahead anyway")
        if playing is None:
            warn("could not ask the server whether anyone is playing")
    # With the server stopped as well: nothing about that makes a backup less wanted.
    path = backup.create("deploy")
    if path:
        ok(f"backup {os.path.relpath(path, ROOT)}")
    cmd_up(args)
    failures = checks.end_to_end()
    if failures:
        die(f"the new version failed {failures} check(s) above. The way back: git checkout <the commit before>, ./opendmtq up, "
            "and ./opendmtq restore if the data needs it")
    ok(f"deployed {system.code_version()}")


def cmd_setup(args):
    # The wordmark, its blank line from the first step's heading (step() brings one).
    look.banner(system.code_version(), gap=False)
    if env.windows_drive(ROOT):
        print()
        warn("this repository is on a Windows drive: the database is slow there and file owners cannot be set")
    step("1/5  Address phones will use")
    host = ensure_env(args.host)

    step("2/5  Game files")
    source, names = args.source, None
    if not source and not (have_game_data() and has_base()):
        # Nothing imported yet and no folder given: look where downloads usually land.
        found = discover.find()
        if not found:
            # Where it looked and the names it takes: a file of another name was there, maybe.
            die(f"{discover.not_found()}. Put one of those words in the file's name, or run: ./opendmtq setup "
                "--from <folder> (docs/troubleshooting.md, \"Setup cannot find the game files\")")
        source, names = found[0]
        if len(found) > 1 and sys.stdin.isatty():
            print("  Game files found in more than one place:")
            for i, (folder, hits) in enumerate(found, 1):
                print(f"    {i}. {folder}  ({count(len(hits), 'file')})")
            pick = input("  Use which? [1] ").strip() or "1"
            if not pick.isdigit() or not 1 <= int(pick) <= len(found):
                die("no folder chosen")
            source, names = found[int(pick) - 1]
        ok(f"using game files in {source}: {', '.join(names)}")
    if source:
        # Found by name: those files only. Given with --from: the whole folder. The songs come in a step of their own.
        songs = args.songs
        if songs is None and song_count() == 0 and sys.stdin.isatty():
            songs = (input("  Import the songs from there too? [Y/n] ").strip().lower() or "y").startswith("y")
        cmd_import(argparse.Namespace(path=source, names=names, songs=bool(songs), no_game_data=False))
    if not have_game_data() or not has_base():
        die("still missing the client data or the base APK after the import (see above)"
            + ("; if they are in another folder, pass it: ./opendmtq setup --from <folder>" if names else ""))
    ok("client data and base APK present")
    songs_in = song_count()
    if songs_in:
        ok(count(songs_in, "song"))
    else:
        warn("no songs yet: the game starts with an empty song list. Add them with "
             "./opendmtq import --songs <folder with your game files>, or one by one on the admin pages")

    step("3/5  Server (also builds the phone app)")
    cmd_up(args)
    # As up left it: a server set up on port 80 before 0.11.0 has moved to its new port there.
    host = require_host()

    step("4/5  Phone app")
    if args.rebuild_apk:
        cmd_apk(argparse.Namespace(base=None), show_qr=False)
    elif apk_host() == host:
        ok(f"app for {host} is ready")

    step("5/5  Network access")
    port = env.listen_port(env.load(ENV_FILE))
    internet = not env.is_lan_only(host)
    if env.is_wsl():
        # --no-firewall leaves Windows' firewall alone, its question to PowerShell about the rule too.
        if args.no_firewall:
            warn(f"skipped the firewall; phones cannot connect until TCP {port} is allowed")
        elif system.firewall_rule_present(port, internet):
            ok(f"Windows firewall rule '{system.firewall_rule_name(port)}'")
        else:
            open_firewall(port, internet)
    else:
        ok(f"phones connect on TCP {port} from {'anywhere' if internet else 'the local network'}")

    step("Self-check")
    failures = checks.end_to_end()
    if failures:
        die(f"{failures} check(s) failed above")

    lan = env.is_lan_only(host)
    where = "same Wi-Fi" if lan else "anywhere"
    # Only a server set up for the internet sends the browser to HTTPS, and only there does the browser ask about the
    # server's own certificate: what it shows then, said where it applies.
    https = "" if lan else (f" The page opens on HTTPS with the server's own certificate, which browsers warn about once (a phone "
                            f"that installs http://{host}/ca.crt does not).")
    for line in setup_end_lines(host, where, https, env.load(ENV_FILE)):
        print(line)
    system.tool("qr", f"http://{host}/")
    return 0


def setup_end_lines(host, where, https, values):
    """What the setup ends with, before the QR code: the addresses block, what is done and the phone's steps, each block
    one blank line from the next, every line on the common left edge (look.py)."""
    # The owner's sign-in with its password, as a host install's setup gives it: the first time anyone signs in.
    lines = [""] + address_lines(host, values, password=True) + [""]
    lines += look.para("Done. The site and the app download open to accounts you make: on the admin pages, under "
                       "Accounts, make one for each player.")
    lines += [""] + look.para(f"On the phone ({where}):")
    steps = [f"Open http://{host}/ in the browser, or scan the code below, and sign in.{https}",
             'Tap "Download app (.apk)" and install it (allow installs from the browser when asked). Other servers\' '
             "apps and the original game can stay installed next to it. Later updates install over this one, which keeps "
             "the device's account.",
             "Start the game."]
    lines += [look.item(n, text) for n, text in enumerate(steps, 1)]
    return lines + [""]


# ----------------------------------------------------------------------------- entry point

def main(argv=None):
    # Our lines and docker's output interleave in the right order even when piped.
    sys.stdout.reconfigure(line_buffering=True)
    # The epilog as written, its lines kept: deploy, a maintainer's command for a live server, under a heading of its own
    # there rather than in the list a newcomer reads.
    ap = argparse.ArgumentParser(prog="opendmtq", description="Run a DJMAX Technika Q server for phones on your network.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="New here? Run ./opendmtq setup. It finds the game files and does the rest.\n\n"
                                        "for a live server's maintainers (docs/testing.md, \"A deploy\"):\n"
                                        "  deploy    put this commit on the live server: only if its tests passed, not\n"
                                        "            during a song, with a backup first")
    sub = ap.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("setup", help="first run, or re-run any time: address, files, server, APK, firewall, check")
    p.add_argument("--from", dest="source", metavar="FOLDER", help="folder (or file) with the downloaded game files")
    p.add_argument("--host", help="LAN address to use instead of the detected one (host:port for another port)")
    p.add_argument("--rebuild-apk", action="store_true", help="rebuild the APK even if it is current")
    p.add_argument("--no-firewall", action="store_true", help="do not touch the Windows firewall")
    songs = p.add_mutually_exclusive_group()
    songs.add_argument("--songs", dest="songs", action="store_true", default=None, help="import the songs found with the game files, without asking")
    songs.add_argument("--no-songs", dest="songs", action="store_false", help="leave the songs out (the game starts with an empty song list)")
    p.set_defaults(fn=cmd_setup)

    p = sub.add_parser("import", help="take the base APK and the client data (and with --songs the song data) from a folder of your game files")
    p.add_argument("path")
    p.add_argument("--songs", action="store_true", help="import the songs too (on their own with --no-game-data)")
    p.add_argument("--no-game-data", action="store_true", help="leave the client data as it is")
    p.add_argument("--check", action="store_true", help="only say what each file there is and whether it can be used")
    p.set_defaults(fn=cmd_import)

    p = sub.add_parser("up", help="start (or update) the server")
    p.add_argument("--no-firewall", action="store_true", help="do not touch the Windows firewall")
    p.set_defaults(fn=cmd_up)
    # No help here: under the epilog's heading, out of the list (argparse lists the commands that have one).
    p = sub.add_parser("deploy", description="Put this commit on the live server: only if its tests passed, not during a song, "
                                             "with a backup first.")
    p.add_argument("--now", action="store_true", help="go ahead although someone is in a song")
    p.add_argument("--no-gates", action="store_true", help="go ahead without asking whether this commit passed its tests")
    p.set_defaults(fn=cmd_deploy)
    sub.add_parser("down", help="stop the server, then back it up").set_defaults(fn=cmd_down)
    sub.add_parser("restart", help="down, then up").set_defaults(fn=cmd_restart)
    sub.add_parser("status", help="one-screen summary").set_defaults(fn=cmd_status)

    p = sub.add_parser("logs", help="server request log (or the app builder's: logs builder)")
    p.add_argument("service", nargs="?", default="server", choices=["server", "builder", "admin", "edge"])
    p.add_argument("-f", "--follow", action="store_true")
    p.add_argument("-n", "--tail", type=int, default=100)
    p.set_defaults(fn=cmd_logs)

    p = sub.add_parser("runtime", help="get the newest arm32 runtime for newer phones and broadcasts, then build the app")
    p.add_argument("--build", action="store_true", help="make it here from this source instead (about 1 GB of downloads the first time)")
    p.set_defaults(fn=cmd_runtime)

    p = sub.add_parser("apk", help="rebuild the phone app now (the server also builds it on start)")
    p.add_argument("--base", help="base APK file name in data/apk/base; kept as BASE_APK in .env for later builds")
    p.set_defaults(fn=cmd_apk)

    sub.add_parser("qr", help="show a QR code of the portal address").set_defaults(fn=cmd_qr)

    p = sub.add_parser("name", help="show or change the server's name in the app's title (rebuilds the APK)")
    p.add_argument("name", nargs="?", help='what goes in "TECHNIKA Q (name)"; empty: the address')
    p.set_defaults(fn=cmd_name, base=None)
    p = sub.add_parser("password", help="change the owner's password for the admin pages and the players' site (typed, or one made)")
    p.set_defaults(fn=cmd_password)
    p = sub.add_parser("port", help="show the server's one port, or move it to another (from the next start, with a new app)")
    p.add_argument("port", nargs="?", type=int, help="the new port, 1 to 65535; one another program holds is refused")
    p.set_defaults(fn=cmd_port)
    p = sub.add_parser("host", help="show or change the LAN address (rebuilds the APK)")
    p.add_argument("address", nargs="?")
    p.set_defaults(fn=cmd_host, base=None)

    p = sub.add_parser("check", help="walk the game's whole path against the running server")
    p.add_argument("--url", help="check this server instead of the local one, e.g. http://127.0.0.1:18080")
    p.set_defaults(fn=cmd_check)
    sub.add_parser("doctor", help="find what is missing or wrong, with the fix for each").set_defaults(fn=cmd_doctor)
    sub.add_parser("backup", help="back up database, signing key and settings").set_defaults(fn=cmd_backup)
    sub.add_parser("backups", help="list backups").set_defaults(fn=cmd_backups)

    p = sub.add_parser("restore", help="restore a backup (the current state is backed up first)")
    p.add_argument("name", help="a name from ./opendmtq backups, or the path of an archive copied here")
    p.add_argument("--with-key", action="store_true",
                   help="also replace the signing key (moving to a new machine: phones keep their app)")
    p.set_defaults(fn=cmd_restore)

    p = sub.add_parser("expose", help="reach the server from the internet under a host name (DDNS or domain)")
    p.add_argument("name", nargs="?", help="host name that points at your public IP, e.g. myhome.example.com")
    p.add_argument("--port", type=int, default=8790, help="TCP port to forward on the router (default 8790)")
    p.add_argument("--off", action="store_true", help="go back to local-network only")
    p.add_argument("--host", help="with --off: the LAN address to use instead of the detected one (host:port for another port)")
    p.add_argument("--no-firewall", action="store_true", help="do not touch the Windows firewall")
    p.add_argument("--admin-public", action="store_true",
                   help="also serve the admin pages on the public port (over HTTPS with the server's own certificate)")
    p.set_defaults(fn=cmd_expose)

    sub.add_parser("repair", help="check and repair: folders, images, certificates, database, song list, app").set_defaults(
        fn=cmd_repair)
    p = sub.add_parser("delete-data", help="list the server's data by part, or delete parts of it (a backup first)")
    p.add_argument("parts", nargs="*", metavar="part", help="database, recordings, songs, apps, backups, logs or game")
    p.add_argument("--no-backup", action="store_true", help="no backup first")
    p.add_argument("--yes", action="store_true", help="do not ask")
    p.set_defaults(fn=cmd_delete_data)
    p = sub.add_parser("uninstall", help="remove this server: containers, images, its folder")
    p.add_argument("--keep-data", action="store_true", help="leave data/ and .env in the folder")
    p.add_argument("--yes", action="store_true", help="do not ask")
    p.set_defaults(fn=cmd_uninstall)
    p = sub.add_parser("firewall", help="allow phones through the Windows firewall (WSL; asks for admin once)")
    p.add_argument("--remove", action="store_true")
    p.set_defaults(fn=cmd_firewall)

    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        ap.print_help()
        return 0
    try:
        return args.fn(args) or 0
    except PermissionError as e:
        # Files in data/ of another user (an earlier run with sudo): the way out, not a traceback.
        die(f"no permission: {e}. If an earlier run used sudo, take data/ back once: sudo chown -R "
            f"{os.getuid()}:{os.getgid()} {DATA}")
