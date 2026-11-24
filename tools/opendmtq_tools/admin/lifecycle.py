"""The Server page: the server's own life in one place. Whether it runs, stopping and starting it again, the repair, the
server's data part by part (and deleting it), and removing the server from the PC. Each action is a function the page and
the API both call (api.py), as on the other pages.

What each install can do from here: a host install and the Windows bundle stop, start again and remove themselves (their
program reads a request in its run folder, as it does for the setup's restart); with Docker Compose and Kubernetes these
pages run inside the server and say the command that does it instead. The repair and the data work everywhere: they need
only the server's folders, which these pages have.
"""

import datetime
import ipaddress
import json
import os
import re
import socket
import time

from flask import abort, flash, redirect, render_template, request, session, url_for

from .. import repair as repairing, server_data
from . import apps, assets, auth, backups, core, jobs, setup, status
from .core import Refused, app, BASE, changed, t, tp

# The words a deletion and a removal must be confirmed with, typed: either language's word does it, whatever the page's.
CONFIRM_DELETE = ("delete", "삭제")
CONFIRM_REMOVE = ("uninstall", "제거")

# The page's words for each install, each part of the data (its name and what it holds), each thing a removal takes away,
# and each step of the repair in each state: the keys of strings.py, written out here.
KIND_WORDS = {"windows": "server.kind_windows", "host": "server.kind_host", "docker": "server.kind_docker",
              "kubernetes": "server.kind_kubernetes"}
REMOVE_LEADS = {"windows": "server.remove_lead_windows", "host": "server.remove_lead_host",
                "docker": "server.remove_lead_docker", "kubernetes": "server.remove_lead_kubernetes"}
COMMAND_LEADS = {"docker": "server.by_command_docker", "kubernetes": "server.by_command_kubernetes",
                 # A host install's pages started without its program's run folder (by hand): what stops and starts it.
                 "host": "server.by_command_host", "windows": "server.by_command_windows"}
PART_WORDS = {"database": ("data.database", "data.database_note"), "recordings": ("data.recordings", "data.recordings_note"),
              "songs": ("data.songs", "data.songs_note"), "apps": ("data.apps", "data.apps_note"),
              "backups": ("data.backups", "data.backups_note"), "logs": ("data.logs", "data.logs_note"),
              "game": ("data.game", "data.game_note")}
REMOVE_WORDS = {"folder": "server.removes_folder", "firewall": "server.removes_firewall", "startup": "server.removes_startup",
                "service": "server.removes_service", "link": "server.removes_link", "containers": "server.removes_containers",
                "images": "server.removes_images", "clone": "server.removes_clone", "release": "server.removes_release"}
REPAIR_WORDS = {
    ("folders", "ok"): "repair.folders_ok", ("folders", "fixed"): "repair.folders_fixed", ("folders", "bad"): "repair.folders_bad",
    ("database", "ok"): "repair.database_ok", ("database", "bad"): "repair.database_bad",
    ("database", "skip"): "repair.database_skip",
    ("owner", "ok"): "repair.owner_ok", ("owner", "fixed"): "repair.owner_fixed", ("owner", "bad"): "repair.owner_bad",
    ("songs", "fixed"): "repair.songs_fixed", ("songs", "bad"): "repair.songs_bad", ("songs", "skip"): "repair.songs_skip",
    ("app", "ok"): "repair.app_ok", ("app", "fixed"): "repair.app_fixed", ("app", "bad"): "repair.app_bad",
    ("app", "skip"): "repair.app_skip",
    ("files", "ok"): "repair.files_ok", ("files", "fixed"): "repair.files_fixed", ("files", "bad"): "repair.files_bad",
    ("files", "skip"): "repair.files_skip",
    ("copies", "fixed"): "repair.copies_fixed", ("copies", "bad"): "repair.copies_bad",
}


def install_kind():
    """What this server is, for what the page offers: "windows" (the bundle), "host" (Linux or macOS without
    containers), "kubernetes" or "docker"."""
    if setup.HOST_INSTALL:
        return "windows" if os.name == "nt" else "host"
    return "kubernetes" if setup.IN_KUBERNETES else "docker"


def can_run_itself():
    """True where these pages can stop, start again and remove the server: its own program reads the run folder."""
    return setup.HOST_INSTALL and bool(setup.RUN_DIR)


def kube_names():
    """The Helm release and its namespace, as the chart tells these pages (deploy/helm), for the commands they show."""
    return os.environ.get("OPENDMTQ_RELEASE") or "opendmtq", os.environ.get("POD_NAMESPACE") or "opendmtq"


def kube_port_command(release, ns):
    """The command that moves a Helm release to another port: the router Service's port named with the address's, as the
    chart reads them (deploy/helm/opendmtq/templates/_helpers.tpl, opendmtq.routerPort). --reuse-values keeps the
    release's own values, and a router.service.port among them (80, from a values file of before 0.11.0) would keep the
    Service where it was while the app is built for the new port, which then answers nothing. Where the address names
    another port than the Service's own (a router's or a load balancer's, forwarded to it), the Service moves alone and
    the address stays, as on every other install (move_port): the app phones have keeps working."""
    upgrade = f"helm upgrade {release} <chart> -n {ns} --reuse-values"
    # Behind a forward: only the Service's port; the forward then goes to it.
    if public_port() != port_now():
        return f"{upgrade} --set router.service.port=<port>"
    host, _ = setup.address_parts(core.PUBLIC_HOST)
    # The address and the Service on the same new port, the one the app is built for.
    return f"{upgrade} --set publicHost={host}:<port> --set router.service.port=<port>"


def commands():
    """The command for each action on an install where these pages cannot do it: Docker Compose's ./opendmtq, or
    Kubernetes' kubectl and helm. On a host install, which does each from here, only what its pages cannot do when they
    were started without its program's run folder or .env (by hand): the program's own command for it."""
    kind = install_kind()
    if kind == "docker":
        return {"stop": "./opendmtq down", "restart": "./opendmtq restart", "repair": "./opendmtq repair",
                "delete_data": "./opendmtq delete-data", "uninstall": "./opendmtq uninstall", "port": "./opendmtq port <port>",
                "name": "./opendmtq name <name>"}
    if kind == "kubernetes":
        release, ns = kube_names()
        return {"stop": f"kubectl -n {ns} scale deploy -l app.kubernetes.io/instance={release} --replicas=0",
                "restart": f"kubectl -n {ns} rollout restart deploy -l app.kubernetes.io/instance={release}",
                "uninstall": f"helm uninstall {release} -n {ns}",
                "delete_data": f"kubectl -n {ns} delete pvc -l app.kubernetes.io/instance={release}",
                "port": kube_port_command(release, ns),
                "name": f"helm upgrade {release} <chart> -n {ns} --reuse-values --set serverName=<name>"}
    # The install's own command: OpenDMTQ.exe on Windows, the opendmtq its setup put on the PATH elsewhere. On Windows
    # the server stops with its window and starts with OpenDMTQ.exe: no command for those (COMMAND_LEADS says so).
    cli = "OpenDMTQ.exe" if kind == "windows" else "opendmtq"
    found = {}
    if not can_run_itself():
        found.update({"stop": f"{cli} stop", "restart": f"{cli} restart"} if kind == "host" else {})
        found["uninstall"] = f"{cli} uninstall"
    if not setup.ENV_FILE:
        found.update(port=f"{cli} port <port>", name=f"{cli} name <name>")
    return found


def removes():
    """What a removal takes away on this install, as keys of the page's words (server.removes_<key>)."""
    kind = install_kind()
    if kind == "windows":
        return ["folder", "firewall", "startup"]
    if kind == "host":
        return ["folder", "service", "link"]
    if kind == "docker":
        return ["containers", "images", "clone"]
    return ["release"]


def request_file(name, body):
    """A request for the server's own program, in its run folder (it looks every two seconds): stop, restart or
    uninstall. Refused where there is no such program to read it."""
    if not can_run_itself():
        raise Refused(404, "host_only", message=setup.HOST_ONLY)
    try:
        # Whole before it is there: the program never reads half of one.
        path = os.path.join(setup.RUN_DIR, name)
        with open(path + ".new", "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(path + ".new", path)
    except OSError as e:
        raise Refused(500, f"{name.split('.')[0]}_failed", t("server.ask_failed", why=e.strerror or str(e)))


def restart_server():
    """Asks the server's program to stop every part and start it again with the settings as they are now (restart.request,
    as the setup's change of address does). These pages restart with it."""
    request_file("restart.request", str(int(time.time())))
    changed("server:restart", auth.client_ip())


def uninstall_server(keep_data, confirm):
    """Asks the server's program to stop and remove itself from this PC (uninstall.request), keeping data/ and .env when
    keep_data. confirm: the word typed to say yes (CONFIRM_REMOVE)."""
    if (confirm or "").strip().lower() not in CONFIRM_REMOVE:
        raise Refused(400, "not_confirmed", t("server.type_to_confirm", word=tp("server.remove_word")))
    request_file("uninstall.request", json.dumps({"keep_data": bool(keep_data)}))
    changed("server:uninstall", "keep data" if keep_data else "everything")


def port_now():
    """The server's own port, the one it serves now and that its port form (and ./opendmtq port) moves: LISTEN_PORT as
    the server started with it, which its host program and Docker Compose give these pages. Where none is given (on
    Kubernetes, whose command moves the port in publicHost; a start of an earlier version), the port in the address."""
    return core.own_port() or public_port()


def public_port():
    """The port in the server's address, the one the phones' app calls (80 for an address without one, as a URL means it):
    the server's own port, or another that is forwarded to it (a router's)."""
    return setup.address_parts(core.PUBLIC_HOST)[1]


def next_address():
    """The address the server moves to at its next start, when .env says another than the one it serves (a port moved
    on this page, or by the command line); None otherwise, and where these pages cannot read .env."""
    if not (setup.HOST_INSTALL and setup.ENV_FILE):
        return None
    try:
        with open(setup.ENV_FILE, encoding="utf-8-sig") as f:
            for line in f.read().splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip().removeprefix("export ").strip() == "PUBLIC_HOST":
                    value = value.strip().strip("'\"")
                    return value if value and value != core.PUBLIC_HOST else None
    except OSError:
        pass
    return None


def next_port():
    """The server's own port from its next start, when .env says another than the one it serves (moved on this page or by
    the command line), also where its address stays (a router's own port in it); None otherwise, and where these pages
    cannot read .env."""
    if not (setup.HOST_INSTALL and setup.ENV_FILE):
        return None
    kept = (env_setting("LISTEN_PORT") or "").strip()
    return int(kept) if kept.isdigit() and int(kept) != port_now() else None


def admin_address():
    """Where these pages open, for the Server page: (address, words or None). On a local network address at the address
    phones use, from anywhere there; on an internet address over HTTPS on the same port where they are on the public port
    (ADMIN_ON_PUBLIC_PORT=yes); else on the server PC alone, as localhost, and never through a proxy (words: what opens
    them from elsewhere, where something does)."""
    public = (os.environ.get("ADMIN_ON_PUBLIC_PORT") or env_setting("ADMIN_ON_PUBLIC_PORT") or "yes") == "yes"
    host, port = setup.address_parts(core.PUBLIC_HOST)
    try:
        lan = ipaddress.IPv4Address(host).is_private
    except ValueError:
        lan = False
    if public and lan:
        return f"http://{core.PUBLIC_HOST}/opendmtq/admin/", None
    if public and not setup.HOST_INSTALL:
        return f"https://{host}:{port}/opendmtq/admin/", None
    # Off the chart's router: on the machine with kubectl, by its port-forward to the admin service's own port.
    if setup.IN_KUBERNETES:
        return "http://localhost:8000/opendmtq/admin/", "server.admin_local_kubernetes"
    # A host install has no HTTPS: there an internet address keeps them on the server PC whatever .env says. On the server
    # PC its own port, not the address's (a router's, forwarded to it, answers nothing there).
    return f"http://localhost:{port_now()}/opendmtq/admin/", "server.admin_local" if setup.HOST_INSTALL else "server.admin_local_docker"


def env_setting(name):
    """A setting from .env, where these pages can read it (a host install); None elsewhere and when it is not there."""
    if not (setup.HOST_INSTALL and setup.ENV_FILE):
        return None
    try:
        with open(setup.ENV_FILE, encoding="utf-8-sig") as f:
            for line in f.read().splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip().removeprefix("export ").strip() == name:
                    return value.strip().strip("'\"")
    except OSError:
        pass
    return None


# How long the site's download page says that the server moved (server/game/src/config.php ODQ_MOVED_DAYS).
MOVED_DAYS = 30


def address_moved():
    """The server's last move to another address while the site's download page says it (address-moved.json, which the
    server's start writes, server/game/src/config.php odq_note_address: within a month, to the address served now), as
    {"from", "to", "at"}; None otherwise."""
    try:
        with open(os.path.join(os.path.dirname(core.DB), "address-moved.json"), encoding="utf-8") as f:
            moved = json.load(f)
    except (OSError, ValueError):
        return None
    if (not isinstance(moved, dict) or not isinstance(moved.get("from"), str) or moved.get("to") != core.PUBLIC_HOST
            or not isinstance(moved.get("at"), int) or time.time() - moved["at"] >= MOVED_DAYS * 86400):
        return None
    return {"from": moved["from"], "to": moved["to"], "at": moved["at"]}


def moved_view(moved):
    """A move off port 80 as the Server page says it: {"was", "now", "address", "public", "stays", "router"}: the port it
    left and the one it took, its address as a link, the port the address names, whether the address stayed as it was (a
    router's own port in it, which goes on to the new port: env.address_after_80), and whether the server is reached
    through a router (an internet address), which then forwards to the new port."""
    address = str(moved.get("address", ""))
    # The port the address names (80 when it names none, as a URL without one means).
    _, sep, port = address.rpartition(":")
    public = int(port) if sep and port.isdigit() else 80
    # The address stayed when its port is not the server's new one: a router's, forwarding it there.
    return {"was": moved.get("from", 80), "now": moved["to"], "address": f"http://{address}/", "public": public,
            "stays": public != moved["to"], "router": not core.lan_only(address)}


def moved_off_80_record():
    """The move off port 80 at the server's first start with this version (cli/opendmtq_cli/env.py note_move_off_80,
    port-moved.json), as {"from", "to", "address", "at", "said", ...}; None for a server that never moved."""
    try:
        with open(os.path.join(os.path.dirname(core.DB), "port-moved.json"), encoding="utf-8") as f:
            moved = json.load(f)
    except (OSError, ValueError):
        return None
    return moved if isinstance(moved, dict) and isinstance(moved.get("to"), int) else None


def moved_off_80(once=True):
    """The move off port 80 (moved_off_80_record) as moved_view() gives it. once: only while its notice is open, which the
    Server page and the Status page's things to look at show with the step it may need (a router's new forward) until
    the owner closes it (close_moved_off_80) or MOVED_DAYS after the move, as the site's download page tells players of
    it for as long; once=False: whenever it moved (the API's moved_from). None otherwise."""
    moved = moved_off_80_record()
    if moved is None:
        return None
    if once and (moved.get("closed") or time.time() - int(moved.get("at") or 0) >= MOVED_DAYS * 86400):
        return None
    return moved_view(moved)


def moved_off_80_words(view):
    """What the Server page and the Status page say of an open move off port 80 (moved_off_80): where it went, its address
    or that the address stays, and behind a router the forward to set there: a new forward of the new port where the
    address's port moved with the server's (the old one was of port 80), or the forward of a router's own port going on
    to the new one."""
    words = t("port.moved_80_stays" if view["stays"] else "port.moved_80", was=view["was"], now=view["now"], address=view["address"])
    if view["router"]:
        words += " " + (t("port.moved_80_router", public=view["public"], now=view["now"], was=view["was"]) if view["stays"]
                        else t("port.router_new", port=view["now"], was=view["was"]))
    return words


def close_moved_off_80():
    """The owner's Done on the notice of the move off port 80: closed, on the Server page and the Status page, from now on.
    Refused: no open notice (none, closed already, or older than MOVED_DAYS)."""
    if moved_off_80() is None:
        raise Refused(404, "no_move", t("port.moved_none"))
    moved = moved_off_80_record()
    moved["closed"] = int(time.time())
    path = os.path.join(os.path.dirname(core.DB), "port-moved.json")
    try:
        # Whole or not at all: shown again next time when it cannot be written.
        with open(path + ".new", "w", encoding="utf-8") as f:
            json.dump(moved, f)
        os.replace(path + ".new", path)
    except OSError as e:
        raise Refused(500, "close_failed", t("port.moved_not_closed", why=core.why(e)))
    changed("server:moved-80-closed", f"{moved.get('from', 80)} > {moved['to']}")


def port_free(port):
    """True when no other program holds the port on this computer (on Windows, as only the program holding it may use
    it then)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name == "nt":
            s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", 0), 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def port_allowed(port):
    """False when this computer keeps the port from the user the server runs as (below 1024 on Linux, without the right
    to take one); True otherwise, a port another program holds among them."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
        except PermissionError:
            return False
        except OSError:
            pass
    return True


def move_port(raw):
    """Moves the server to another port (a host install, the Windows bundle): LISTEN_PORT and the port in PUBLIC_HOST in
    .env, from its next start, when the app is built again for the new address and the site's download page tells players
    to install it. An address that names a router's own port (an internet address whose port is not the server's own,
    forwarded to it) stays, and the app with it: the server's own port moves alone, and the router's forward goes to it,
    as the move off port 80 keeps such a port (cli/opendmtq_cli/env.py, address_after_80). The port it serves, while a
    move waits for the next start, takes that move back. Refused: no such port, the one it is on, one another program
    holds, or an install where the command line does it (Docker Compose, Kubernetes: the command to use). Returns {port,
    address, from_next_start, new_app, router}: router, for an address the internet reaches through one, is the forward
    to set there from the next start ({public, to, was}: the port phones call, the server's new port, and the one it went
    to until then), None on a local network address and for a move taken back."""
    if not (setup.HOST_INSTALL and setup.ENV_FILE):
        raise Refused(409, "by_command", t("port.by_command", command=commands().get("port", "")))
    text = str(raw if raw is not None else "").strip()
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise Refused(400, "bad_port", t("port.bad"))
    port = int(text)
    own, public = port_now(), public_port()
    # A move waiting for the next start, of the address or of the server's own port alone.
    waiting = next_address() is not None or next_port() is not None
    if port == own and not waiting:
        raise Refused(409, "same_port", t("port.same", port=port), tone="ok")
    if port != own and not port_free(port):
        # Kept from the server's user, or held by another program: said as it is.
        if not port_allowed(port):
            raise Refused(409, "port_not_allowed", t("port.not_allowed", port=port))
        raise Refused(409, "port_taken", t("port.taken", port=port))
    host, _ = setup.address_parts(core.PUBLIC_HOST)
    internet = not core.lan_only(core.PUBLIC_HOST)
    # A router's own port in the address: it stays, with the app phones have.
    stays = internet and public != own
    if port == own:
        # Back to the port it serves: the move that waited goes, and the server stays as it runs.
        new = core.PUBLIC_HOST
    else:
        new = core.PUBLIC_HOST if stays else (host if port == 80 else f"{host}:{port}")
    # Port 80 by the owner's own choice: the server's start keeps it (one only set up on it before 0.11.0 moves off it,
    # cli/opendmtq_cli/env.py leaves_80).
    setup.save_env({"PUBLIC_HOST": new, "LISTEN_PORT": str(port), **({"PORT_80": "chosen"} if port == 80 else {})})
    moving = port != own
    changed("server:port", f"{core.PUBLIC_HOST} > {new}" if moving and not stays else
            f"{core.PUBLIC_HOST} (port {own} > {port})" if moving else f"{core.PUBLIC_HOST} (as it runs)")
    # The router's forward from the next start: the address's port moves with the server's, or a router's own stays and
    # goes on to the new port.
    router = {"public": public if stays else port, "to": port, "was": own} if moving and internet else None
    return {"port": port, "address": f"http://{new}/", "from_next_start": moving, "new_app": moving and new != core.PUBLIC_HOST,
            "router": router}


def port_words(moved):
    """What the Server page says of a move (move_port's answer): where the server answers from its next start (or that the
    waiting move is taken back), and, behind a router, where its forward goes then."""
    if not moved["from_next_start"]:
        return t("port.cancelled", port=moved["port"], address=moved["address"])
    words = t("port.saved" if moved["new_app"] else "port.saved_stays", port=moved["port"], address=moved["address"])
    router = moved["router"]
    if router:
        # The address's port moved with the server's: a new forward of that port, in place of the old one's. A router's own
        # port in the address: its forward goes on to the new port.
        words += " " + (t("port.router_new", port=router["to"], was=router["was"]) if moved["new_app"] else
                        t("port.moved_80_router", public=router["public"], now=router["to"], was=router["was"]))
    return words


# The server's name in the app's title (TECHNIKA Q (name)) as these pages take a new one: no longer than the app builder
# takes (patch_apk.MAX_SERVER_NAME), printable, and with nothing .env could read as something else (a quote, a $ that
# names a variable, a # that starts a comment, a backslash or a backquote), as ./opendmtq name takes it.
NAME_MAX = 80
NAME_REFUSED = re.compile(r"[\"'$#\\`]")


def name_now():
    """The server's name as it runs (SERVER_NAME, which the builder and the site read at their start), or "" while it
    has none: its address names the app then."""
    return os.environ.get("SERVER_NAME", "").strip()


def next_name():
    """The name .env gives the server from its next start, when it is another than the one it runs with (renamed on the
    Server page or by the command line): "" for none, the address then. None when it is the same, and where these pages
    cannot read .env."""
    if not (setup.HOST_INSTALL and setup.ENV_FILE):
        return None
    # Not in .env at all: no name, as the server reads it.
    kept = (env_setting("SERVER_NAME") or "").strip()
    return kept if kept != name_now() else None


def app_title(name):
    """The app's name on phones for a server of this name: the address in place of a name it does not have."""
    return f"TECHNIKA Q ({name or core.PUBLIC_HOST})"


def rename_server(raw):
    """The server's name in the app's title (SERVER_NAME in .env), on a host install and the Windows bundle: from its next
    start, when the app is built again with it. Phones keep working with the app they have: it calls the same address.
    Empty: the address names the app. Refused: too long, a character .env or the app cannot take, the name it has from
    its next start already, or an install where the command line does it (Docker Compose, Kubernetes: the command).
    Returns {name, app_name, from_next_start}."""
    if not (setup.HOST_INSTALL and setup.ENV_FILE):
        raise Refused(409, "by_command", t("name.by_command", command=commands().get("name", "")))
    name = str(raw if raw is not None else "").strip()
    if len(name) > NAME_MAX or not name.isprintable() or NAME_REFUSED.search(name):
        raise Refused(400, "bad_name", t("name.bad"))
    # The name it will have: the one waiting for the next start, else the one it runs with.
    waiting = next_name()
    if name == (waiting if waiting is not None else name_now()):
        raise Refused(409, "same_name", t("name.same", app=app_title(name)), tone="ok")
    try:
        setup.save_env({"SERVER_NAME": name})
    except OSError as e:
        # .env as it was: nothing changed.
        raise Refused(500, "name_failed", t("name.not_saved", why=core.why(e)))
    # The name it runs with, while another waited: the waiting one taken back, and nothing changes at the next start.
    renaming = name != name_now()
    changed("server:name", f"{app_title(name_now())} > {app_title(name)}" if renaming else f"{app_title(name)} (as it runs)")
    return {"name": name, "app_name": app_title(name), "from_next_start": renaming}


# The owner's password as these pages take a new one: it goes into .env as typed, where Docker Compose reads it too, so
# nothing there could read it as something else (a space, a quote, a $ that names a variable, a # that starts a comment, a
# backslash or a backquote), and at least as long as an account's with admin rights (accounts.ADMIN_PASSWORD_MIN).
OWNER_PASSWORD = re.compile(r"[^\s\"'$#\\`]{10,64}")


def admin_secret():
    """The Kubernetes Secret that holds the owner's password, as the chart tells these pages (OPENDMTQ_ADMIN_SECRET), else
    the name the chart gives its own: the release's full name with -admin."""
    release, _ = kube_names()
    full = release if "opendmtq" in release else f"{release}-opendmtq"
    return os.environ.get("OPENDMTQ_ADMIN_SECRET") or f"{full[:50].rstrip('-')}-admin"


def password_commands():
    """The commands that change the owner's password where these pages cannot write .env: Docker Compose's command line,
    or the Secret and a restart on Kubernetes. [] on a host install, which changes it here."""
    kind = install_kind()
    if kind == "docker":
        return ["./opendmtq password"]
    if kind == "kubernetes":
        release, ns = kube_names()
        return [f"kubectl -n {ns} create secret generic {admin_secret()} --from-literal=ADMIN_PASSWORD=<password> "
                "--dry-run=client -o yaml | kubectl apply -f -",
                f"kubectl -n {ns} rollout restart deploy -l app.kubernetes.io/instance={release}"]
    # A host install's pages started without its .env (by hand): its program's own command changes it.
    if not setup.ENV_FILE:
        return ["OpenDMTQ.exe password" if kind == "windows" else "opendmtq password"]
    return []


def change_owner_password(new, again, owner):
    """The owner's password (ADMIN_PASSWORD in .env) changed to new, typed twice (again), on a host install and the
    Windows bundle: written to .env, and taken by this service at once (core.PASSWORD), the owner's sign-in for the site
    written again with it (owner.pass), and the owner's other sign-ins to these pages ended (auth.owner_stamp()). owner:
    whether the owner asks (only they change it: an admin's account or token cannot). Refused with Docker Compose and
    Kubernetes, where the command line does it (the message names the command)."""
    if not owner:
        raise Refused(403, "owner_only", t("pw.owner_only"))
    if not (setup.HOST_INSTALL and setup.ENV_FILE):
        raise Refused(409, "by_command", t("pw.by_command", command=" && ".join(password_commands()) or "./opendmtq password"))
    if not new:
        raise Refused(400, "missing_password", t("pw.missing"))
    if not OWNER_PASSWORD.fullmatch(new):
        raise Refused(400, "bad_password", t("pw.bad"))
    if again != new:
        raise Refused(400, "password_mismatch", t("acc.mismatch"))
    old = core.PASSWORD
    try:
        setup.save_env({"ADMIN_PASSWORD": new})
    except OSError as e:
        # .env as it was: nothing changed.
        raise Refused(500, "password_failed", t("pw.not_saved", why=core.why(e)))
    core.PASSWORD = new
    # The site's copy of it (owner.pass): without it the site would keep the old password while these pages took the new
    # one, so what was is put back and the change is refused in words.
    if auth.owner_file_write() == "failed":
        core.PASSWORD = old
        try:
            setup.save_env({"ADMIN_PASSWORD": old})
        except OSError:
            app.logger.warning("the owner's password: .env could not be put back")
        raise Refused(500, "password_failed", t("pw.site_failed"))
    # When it changed: an owner's sign-in from before sessions kept their password's stamp ends with it too. Without the
    # settings' file the change stands all the same (the stamped sign-ins end anyway).
    try:
        core.save_settings(owner_password_at=int(time.time()))
    except OSError:
        app.logger.warning("the owner's password: the moment of its change could not be noted")
    changed("server:password", core.ADMIN_USER)


def layout():
    """Where the server's data is, as these pages see it."""
    return server_data.Layout()


def delete_part_command(part):
    """The command on the server PC that deletes this part of the data where these pages cannot (its files are not
    theirs to write): the install's own command line with the part's name, or on Kubernetes the volume's whole."""
    kind = install_kind()
    if kind == "docker":
        return f"./opendmtq delete-data {part}"
    if kind == "windows":
        return f"OpenDMTQ.exe delete-data {part}"
    if kind == "host":
        return f"opendmtq delete-data {part}"
    return commands().get("delete_data", "")


def data_parts():
    """Each part of the server's data, in the page's order: {"part", "bytes", "can_delete", "command"}, the command
    being the way to delete it on the server PC where these pages cannot ("" where they can)."""
    sizes = server_data.sizes(layout())
    return [{"part": part, "bytes": sizes[part]["bytes"], "can_delete": sizes[part]["can_delete"],
             "command": "" if sizes[part]["can_delete"] else delete_part_command(part)} for part in server_data.PARTS]


def start_delete(parts, make_backup, confirm):
    """Starts deleting these parts of the server's data as a job (a backup first when make_backup, kept whatever else
    goes). confirm: the word typed to say yes (CONFIRM_DELETE). Returns the job's id."""
    parts = [p for p in server_data.PARTS if p in set(parts or ())]
    if not parts:
        raise Refused(400, "no_parts", t("data.none_chosen"))
    if (confirm or "").strip().lower() not in CONFIRM_DELETE:
        raise Refused(400, "not_confirmed", t("server.type_to_confirm", word=tp("data.delete_word")))
    # Not while an import or a build works with the same folders.
    why = setup.busy()
    if why:
        raise Refused(409, "busy", why)

    def work(say):
        said, kept = [], []
        if make_backup:
            try:
                kept.append(backups.make_backup("before-delete"))
                said.append(("ok", t("data.backed_up", name=kept[0])))
            except Exception as e:  # noqa: BLE001 - nothing is deleted without the backup that was asked for
                return [("bad", t("data.not_backed_up", why=core.why(e)))], False
        done = server_data.delete(layout(), parts, keep=kept, say=say)
        # The status page's disk and the site copies count again.
        status._disk_cache.clear()
        gone = [p for p in parts if done.get(p)]
        left = [p for p in parts if not done.get(p)]
        if gone:
            said.append(("ok", t("data.deleted", what=", ".join(tp(PART_WORDS[p][0]) for p in gone))))
        if left:
            said.append(("bad", t("data.not_deleted", what=", ".join(tp(PART_WORDS[p][0]) for p in left))))
        changed("server:delete-data", ", ".join(gone))
        return said, not left

    return beside_no_restore("delete-data", work, parts=parts)


def beside_no_restore(kind, work, **details):
    """Starts a page's job (jobs.start_page_task) that no restore runs beside: refused while a restore, a backup made on
    the Backups page or another such job runs, and none of them starts until it ends (backups._restoring, taken here and
    given back when the job ends). Returns the job's id."""
    if not backups._restoring.acquire(blocking=False):
        raise Refused(409, "busy", t("bak.busy"))

    def held(say):
        # Given back whatever happens.
        try:
            return work(say)
        finally:
            backups._restoring.release()

    try:
        return jobs.start_page_task(kind, held, **details)
    except Exception:
        # No job to give it back: given back here.
        backups._restoring.release()
        raise


def start_repair():
    """Starts the repair as a job: the steps of repair.py, the site copies these pages keep, and the app's build when the
    one on offer is missing or for another address. Returns the job's id."""
    why = setup.busy()
    if why:
        raise Refused(409, "busy", why)

    def work(say):
        root = repairing.install_root()
        results = repairing.run(layout(), root=root, version=repairing.install_version(root), user=core.ADMIN_USER,
                                password=core.PASSWORD, public_host=core.PUBLIC_HOST, say=say)
        # The owner's sign-in for the site as these pages keep it (with their own way of keeping a password).
        results["owner"] = {"kept": ("ok", ""), "written": ("fixed", ""), "removed": ("fixed", "")}.get(
            auth.owner_file_write(), results["owner"])
        # The copies of the site's look these pages keep for when the game server is down: taken afresh.
        try:
            for name in os.listdir(assets.SITE_COPIES) if os.path.isdir(assets.SITE_COPIES) else []:
                os.remove(os.path.join(assets.SITE_COPIES, name))
            assets._css.clear()
            results["copies"] = ("fixed", "")
        except OSError as e:
            results["copies"] = ("bad", core.why(e))
        # The app: built again when the one on offer is missing or for another address, as the App page builds it.
        state, detail = results["app"]
        if state == "bad":
            try:
                job, _ = apps.start_build("")
                results["app"] = ("fixed", job)
            except Refused as e:
                results["app"] = ("bad", core.plain(e.words) or detail)
        said = []
        for step in repairing.STEPS + ("copies",):
            state, detail = results[step]
            # The program's files on an install with no list of them: said where it matters (a host install's own), and
            # only the steps that have words for the state they ended in (the owner's sign-in skipped has none).
            if step == "files" and state == "skip" and install_kind() not in ("windows", "host"):
                continue
            key = REPAIR_WORDS.get((step, state))
            if key:
                said.append(("bad" if state == "bad" else "ok", t(key, detail=detail)))
        changed("server:repair", ", ".join(f"{s} {results[s][0]}" for s in results if results[s][0] in ("fixed", "bad")))
        return said, not any(state == "bad" for state, _ in results.values())

    return beside_no_restore("repair", work)


# ------------------------------------------------------------------------------ the page

@app.route(BASE + "/server", methods=["GET"])
def server_page():
    """The Server page: its state and what can be done with it here."""
    wanted = request.args.get("job", "")
    if wanted and jobs.nothing_to_follow(wanted):
        return redirect(url_for("server_page"))
    job = jobs._jobs.get(wanted) if wanted else None
    parts = data_parts()
    # Since when this service has run: the server's own start, as these pages start with it.
    started = int(setup.STARTED.rsplit("-", 1)[1]) if "-" in setup.STARTED else 0
    moved = moved_off_80()
    moved_words = moved_off_80_words(moved) if moved else None
    return render_template("server.html", kind=install_kind(), can_run=can_run_itself(), commands=commands(),
                           removes=removes(), parts=parts, total=sum(p["bytes"] for p in parts),
                           since=datetime.datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M") if started else "",
                           version=os.environ.get("OPENDMTQ_VERSION") or "", root=repairing.install_root(),
                           port=port_now(), public_port=public_port(), next_address=next_address(), next_port=next_port(),
                           # A router's own port in an internet address, forwarded to the server's own: it stays at a move.
                           forwarded=public_port() != port_now() and not core.lan_only(core.PUBLIC_HOST),
                           # The move off port 80 while its notice is open, in the words it says it with.
                           moved_80=moved_words,
                           admin_at=admin_address(),
                           can_move_port=bool(setup.HOST_INSTALL and setup.ENV_FILE),
                           # The app's name: as phones show it now, and the one waiting for the next start.
                           app_name=app_title(name_now()), name=name_now(), next_name=next_name(),
                           # The owner's password: changed here by the owner, or the command that changes it.
                           password_here=bool(setup.HOST_INSTALL and setup.ENV_FILE), password_commands=password_commands(),
                           is_owner=session.get("stamp") == "owner", owner_id=core.ADMIN_USER,
                           kind_words=KIND_WORDS, command_leads=COMMAND_LEADS, part_words=PART_WORDS,
                           remove_leads=REMOVE_LEADS, remove_words=REMOVE_WORDS,
                           job=wanted or None, job_kind=job["kind"] if job else None)


@app.route(BASE + "/server/restart", methods=["POST"])
def server_restart():
    """Restart the server (a host install): the page then waits for these pages to answer again, and comes back here."""
    try:
        restart_server()
    except Refused as e:
        if e.code == "host_only":
            abort(404)
        flash(e.words, e.tone)
        return redirect(url_for("server_page"))
    return render_template("server_restart.html", instance=setup.STARTED, ping=url_for("setup_ping"),
                           back=url_for("server_page"))


@app.route(BASE + "/server/port", methods=["POST"])
def server_port():
    """Move the server to another port from its next start (a host install): said on this page, and from then on above
    the Restart that makes it now."""
    try:
        flash(port_words(move_port(request.form.get("port"))), "ok")
    except Refused as e:
        flash(e.words, e.tone)
    return redirect(url_for("server_page") + "#port")


@app.route(BASE + "/server/moved-80", methods=["POST"])
def server_moved_80():
    """Done on the notice of the move off port 80: it goes from this page and the Status page; nothing else changes."""
    try:
        close_moved_off_80()
    except Refused as e:
        flash(e.words, e.tone)
    return redirect(url_for("server_page") + "#port")


@app.route(BASE + "/server/name", methods=["POST"])
def server_name():
    """The server's name in the app's title from its next start (a host install): said on this page, and from then on
    above the Restart that makes it now, as a move to another port is."""
    try:
        renamed = rename_server(request.form.get("name"))
        flash(t("name.saved" if renamed["from_next_start"] else "name.cancelled", app=renamed["app_name"]), "ok")
    except Refused as e:
        flash(e.words, e.tone)
    return redirect(url_for("server_page") + "#name")


@app.route(BASE + "/server/password", methods=["POST"])
def server_password():
    """The owner's new password (a host install, the Windows bundle): from now on, this sign-in kept."""
    try:
        change_owner_password(request.form.get("password", ""), request.form.get("password2", ""), session.get("stamp") == "owner")
        # This sign-in goes on with the new password; the owner's others end.
        session["pw"] = auth.owner_stamp()
        flash(t("pw.done", user=core.ADMIN_USER), "ok")
    except Refused as e:
        flash(e.words, e.tone)
    return redirect(url_for("server_page") + "#password")


@app.route(BASE + "/server/repair", methods=["POST"])
def server_repair():
    try:
        return jobs.answer(start_repair(), "server_page")
    except Refused as e:
        flash(e.words, e.tone)
        return redirect(url_for("server_page"))


@app.route(BASE + "/server/data", methods=["POST"])
def server_delete():
    """Delete the parts ticked, a backup first when that is ticked (it is, as the page comes)."""
    try:
        job = start_delete(request.form.getlist("part"), request.form.get("backup") == "yes", request.form.get("confirm"))
        return jobs.answer(job, "server_page")
    except Refused as e:
        flash(e.words, e.tone)
        return redirect(url_for("server_page") + "#data")


@app.route(BASE + "/server/uninstall", methods=["POST"])
def server_uninstall():
    """Remove the server from this PC (a host install, the Windows bundle): the page says what happens, as it stops."""
    keep = request.form.get("keep") == "yes"
    try:
        uninstall_server(keep, request.form.get("confirm"))
    except Refused as e:
        if e.code == "host_only":
            abort(404)
        flash(e.words, e.tone)
        return redirect(url_for("server_page") + "#remove")
    return render_template("server_removing.html", kind=install_kind(), keep=keep, ping=url_for("setup_ping"),
                           instance=setup.STARTED)
