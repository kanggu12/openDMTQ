""".env reading and writing, and finding the LAN address phones should use."""

import ipaddress
import os
import re
import socket
import subprocess

# Longest address the client patcher accepts ("host" or "host:port").
MAX_HOST_LEN = 80
# A DNS name: labels of letters, digits and inner hyphens.
_NAME = re.compile(r"(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*")


# The owner's password as a new one is taken (./opendmtq password, the host install's password, and the admin pages'
# Server page: OWNER_PASSWORD in tools/opendmtq_tools/admin/lifecycle.py): it goes into .env as typed, where Docker Compose
# reads it too, so nothing there could read it as something else (a space, a quote, a $ that names a variable, a # that
# starts a comment, a backslash or a backquote).
OWNER_PASSWORD = r"[^\s\"'$#\\`]{10,64}"


def parse(text):
    """KEY=value pairs from .env text, the way docker compose reads them."""
    values = {}
    # Notepad may save the file with a byte order mark in front: not part of the first line's key.
    text = text.lstrip("\ufeff")
    for raw in text.splitlines():
        # Files saved by Windows editors carry CR; compose ignores it, so must we.
        line = raw.strip().rstrip("\r")
        if not line or line.startswith("#"):
            continue
        # `export KEY=value` is accepted by compose too.
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        # Matching outer quotes are removed, as compose does.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        # An unquoted value ends at " #" (an inline comment), as compose reads it.
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key.strip()] = value
    return values


def load(path):
    """Values from .env, or {} when it does not exist yet. A byte order mark in front (Notepad's) is not read as text."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return parse(f.read())
    except FileNotFoundError:
        return {}


def save(path, updates):
    """Set keys in .env, keeping every other line (and comments) as they are."""
    try:
        # Without a byte order mark in front (Notepad's): the file is written back without it.
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        lines = ["# OpenDMTQ settings. Written by ./opendmtq; safe to edit by hand."]
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip().removeprefix("export ").strip()
        if key in updates and "=" in line:
            lines[i] = f"{key}={updates[key]}"
            done.add(key)
    for key, value in updates.items():
        if key not in done:
            lines.append(f"{key}={value}")
    # The passwords live here: readable by its owner only.
    write_private(path, "\n".join(lines) + "\n")


def drop(path, keys):
    """Takes these settings out of .env (every line that sets one of them), keeping every other line as it is. For the
    settings a version no longer reads, whose lines would only mislead whoever opens the file."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return
    kept = [line for line in lines
            if not ("=" in line and line.split("=", 1)[0].strip().removeprefix("export ").strip() in keys)]
    if kept != lines:
        write_private(path, "\n".join(kept) + "\n")


# A setting as a person may type it in an editor: spaces around "=", "export" in front.
_LOOSE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def tidy(path):
    """Writes .env back in the one form every reader takes alike, when an editor left it otherwise: no byte order mark,
    no Windows line ends, no spaces around "=". The values stay as they are (quotes too). True when it was rewritten.
    Docker Compose reads the file itself, and some of its versions read such a line differently from this program."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return False
    text = raw.decode("utf-8", "replace").lstrip("\ufeff")
    lines = []
    for line in text.splitlines():
        m = _LOOSE.match(line)
        # Comments and blank lines as they are; a setting in its one form.
        lines.append(f"{m.group(1)}={m.group(2)}" if m and not line.lstrip().startswith("#") else line.rstrip("\r"))
    tidied = "\n".join(lines) + "\n"
    if tidied.encode("utf-8") == raw:
        return False
    write_private(path, tidied)
    return True


def write_private(path, text):
    """Writes text to path, readable by its owner only: .env, and the keys a host install keeps (the download sign-in's,
    the setup's one-time sign-in). Other users of the machine must not read them."""
    # Write a sibling first and swap, so an interrupted write never leaves half a file.
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        # O_CREAT's mode only applies to a new file: a sibling left from before is narrowed too. Windows has neither
        # call (its Python before 3.13 has no fchmod, and no user ids): there the file is as private as its folder.
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        # Run with sudo, keep the file the folder owner's, so the CLI and compose still read it without sudo.
        if hasattr(os, "getuid") and os.getuid() == 0:
            owner = os.stat(os.path.dirname(os.path.abspath(path)))
            os.fchown(fd, owner.st_uid, owner.st_gid)
        f.write(text)
    os.replace(tmp, path)


def split(address):
    """("host", port) from "host" or "host:port"; port 80 when none is given, as a URL without a port means (http://host/
    is port 80)."""
    host, sep, port = address.rpartition(":")
    if not sep:
        return address, 80
    return host, int(port) if port.isdigit() else -1


def join(host, port):
    """The address the app uses: "host:port", or "host" for port 80, as a URL without a port means (only an owner's own
    `port 80` makes one)."""
    return host if int(port) == 80 else f"{host}:{port}"


def https_address(address):
    """The address with its port always written out, for https:// links: HTTPS is served on the
    same port as plain HTTP, so a port-80 server is https://host:80/, not the default 443."""
    host, port = split(address)
    return f"{host}:{port}"


# The server's one port on a new install: the players' site, the admin pages (/opendmtq/admin) and the API on it.
DEFAULT_PORT = 8791


def listen_port(values):
    """Port the server publishes: LISTEN_PORT in .env; for a server set up before .env named one, the port its address
    then has (an address without a port is port 80, which its start moves it off: leaves_80); 8791 for one not set up
    yet."""
    if values.get("LISTEN_PORT"):
        return int(values["LISTEN_PORT"])
    return split(values["PUBLIC_HOST"])[1] if values.get("PUBLIC_HOST") else DEFAULT_PORT


# A server set up before 0.11.0 served port 80 when its .env named no port (Docker Compose published 80 then, and its
# address had no port). It moves at its first start to the port its admin pages had (leaves_80, port_after_80,
# note_move_off_80). `port 80` writes this setting, the owner's own choice of port 80, which every start then keeps.
CHOSE_80 = "PORT_80"


def leaves_80(values, port):
    """True for a set-up server whose start would serve port 80 (`port`) without its owner having chosen it with `port
    80`: one set up before 0.11.0 without LISTEN_PORT, its address without a port, or one whose .env says LISTEN_PORT=80
    from then."""
    return bool(values.get("PUBLIC_HOST")) and port == 80 and values.get(CHOSE_80) != "chosen"


def address_after_80(old, port):
    """PUBLIC_HOST once the server leaves port 80 for `port`: the port in it moves with the server's when it was the
    server's own (80, written or not); one that differs is a router's, forwarding it to the server's port (8443 to 80), and
    stays, the forward going to the new port from then on."""
    host, public = split(old)
    return join(host, port) if public == 80 else old


def port_after_80(values, free):
    """The port a server leaves 80 for: the one its admin pages had (ADMIN_PORT, which only a server set up before 0.11.0
    has; 8791 unless its owner set another), or the first one after it that free(port) allows."""
    try:
        first = int(values.get("ADMIN_PORT") or DEFAULT_PORT)
    except ValueError:
        first = DEFAULT_PORT
    # Never a port below 1024 (the server's user may not take one), nor past the last.
    if not 1024 <= first <= 65535:
        first = DEFAULT_PORT
    return next((p for p in range(first, min(first + 100, 65536)) if free(p)), first)


# In the server's state folder: the move off port 80, as {"from", "to", "address", "at", "said"} ("said": where it has
# been said, each of the start, status and the Server page once).
MOVED_80 = "port-moved.json"


def _write_state(folder, name, data):
    """A small JSON file in the server's state folder, whole or not at all, its folder owner's (a run with sudo)."""
    import json
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path + ".new", "w", encoding="utf-8") as f:
        json.dump(data, f)
    if hasattr(os, "getuid") and os.getuid() == 0:
        owner = os.stat(folder)
        os.chown(path + ".new", owner.st_uid, owner.st_gid)
    os.replace(path + ".new", path)


def note_move_off_80(folder, old, new, said="start", port=None):
    """Notes in the server's state folder that the server moved from port 80 to `port` (the port in `new` when not given)
    and its address from `old` to `new` (the same when a router's own port stays: address_after_80): the address served
    before, for the server's start to note the move as any move of its address (address.json, when no start of this
    version wrote one: the site's download page then tells players to install the app built for the new one), and the
    move itself, said already where `said` names."""
    import time
    if not os.path.isfile(os.path.join(folder, "address.json")):
        _write_state(folder, "address.json", {"host": old})
    _write_state(folder, MOVED_80, {"from": 80, "to": int(port or split(new)[1]), "address": new, "at": int(time.time()),
                                    "said": [said]})


def router_line(public, port, was, stays):
    """The router's step when the server moves from its port `was` to `port`, for an internet address: a router's own port
    in the address (`public`, not the server's own) stays and its forward goes on to the new port (stays); else the
    address's port moved with the server's, and the router forwards the new port in place of the old one's forward. The
    admin pages' Server page says the same (tools/opendmtq_tools/strings.py, port.moved_80_router and port.router_new)."""
    if stays:
        return f"On the router(s), forward TCP {public} to port {port} of this PC in place of port {was}."
    return f"On the router(s), forward TCP {port} to port {port} of this PC, in place of the forward of TCP {was}."


def port_move(address, own, port):
    """What moving the server from its own port `own` to `port` makes of its address, as every install's command line and
    the admin pages' Server page move it (tools/opendmtq_tools/admin/lifecycle.py, move_port): (the address from the next
    start, whether it stays, the router's line or None). An internet address whose port is not the server's own names a
    router's port, forwarded to it: it stays, with the app phones have, as the move off port 80 keeps it
    (address_after_80). A local network address has no router between: its port always moves with the server's."""
    host, public = split(address)
    internet = not is_lan_only(address)
    stays = internet and public != own
    new = address if stays else join(host, port)
    return new, stays, (router_line(public, port, own, stays) if internet else None)


def move_off_80_words(moved, start=False):
    """What a move off port 80 says (note_move_off_80's record: from, to, address), in lines: where the server went and
    its address with it, or that its address stays (a router's own port in it); for an internet address the router's
    forward to the new port; when the address moved, the phones' app for it. start: as the start says it, the site's
    download page named. The first line ends with the address, the others with their full stop."""
    was, port, address = moved.get("from", 80), moved["to"], moved["address"]
    public = split(address)[1]
    # The address moved with the server's port, unless a router's own port in it stayed.
    stays = public != port
    lines = [f"The server moved from port {was} to {port}; its address stays http://{address}/" if stays else
             f"The server moved from port {was} to {port}: http://{address}/"]
    if not is_lan_only(address):
        # The internet reaches the server through the router(s): what goes on to the server PC follows its port.
        lines.append(router_line(public, port, was, stays))
    if not stays:
        lines.append("Phones install the app again from that address" + (" (the site's download page says so)" if start else "")
                     + ", and PCs connect to it.")
    return lines


def move_off_80_unsaid(folder, where):
    """The move off port 80 (note_move_off_80) the first time `where` ("status", "page") asks for it, noted as said
    there; None after that, and for a server that never moved."""
    import json
    try:
        with open(os.path.join(folder, MOVED_80), encoding="utf-8") as f:
            moved = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(moved, dict) or where in moved.get("said", []) or not isinstance(moved.get("to"), int):
        return None
    moved["said"] = list(moved.get("said", [])) + [where]
    try:
        _write_state(folder, MOVED_80, moved)
    except OSError:
        # Said again next time rather than not at all.
        pass
    return moved


def port_problem(values):
    """Error text when phones would call another port than the server listens on, or None.

    Only for LAN addresses, which phones reach directly. Behind a router (exposed) the public port
    may be forwarded to another one.
    """
    address = values.get("PUBLIC_HOST", "")
    if not is_lan_only(address):
        return None
    host, port = split(address)
    listen = listen_port(values)
    if port == listen:
        return None
    return (f"PUBLIC_HOST={address} makes phones call port {port}, but the server listens on {listen} "
            f"(LISTEN_PORT); run ./opendmtq host {host}:{listen}")


def check_host(address):
    """Error text for an unusable PUBLIC_HOST ("host" or "host:port"), or None when it is fine."""
    if not address:
        return "PUBLIC_HOST is empty"
    if len(address) > MAX_HOST_LEN:
        return f"PUBLIC_HOST={address} is longer than {MAX_HOST_LEN} characters"
    host, port = split(address)
    if not 1 <= port <= 65535:
        return f"PUBLIC_HOST={address} has an invalid port"
    try:
        addr = ipaddress.IPv4Address(host)
    except ValueError:
        # Not an address: a DNS name (DDNS, your own domain) is fine.
        if not _NAME.fullmatch(host) or host.replace(".", "").isdigit():
            return f"PUBLIC_HOST={address!r} is neither an IPv4 address nor a host name"
        if host.lower() == "localhost":
            return "PUBLIC_HOST=localhost cannot be reached from a phone"
        return None
    # Loopback or link-local addresses are unreachable from a phone.
    if addr.is_loopback or addr.is_link_local or addr.is_unspecified:
        return f"PUBLIC_HOST={address} cannot be reached from a phone"
    return None


def is_lan_only(address):
    """True when the address is a private IPv4 address (phones must be on the same network)."""
    try:
        return ipaddress.IPv4Address(split(address)[0]).is_private
    except ValueError:
        return False


def route_source(output):
    """Source address from `ip -4 route get` output."""
    m = re.search(r"\bsrc (\d+\.\d+\.\d+\.\d+)", output)
    return m.group(1) if m else None


def detect_host():
    """The address this machine uses on its default route, or None."""
    try:
        out = subprocess.run(["ip", "-4", "route", "get", "1.1.1.1"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        # No `ip` (macOS): connecting a UDP socket picks the same address and sends nothing.
        out = ""
    # A network with no way out may have no default route to ask about: then the address the machine has on it.
    return route_source(out) or socket_source() or own_private_address()


def socket_source():
    """The address the system would send from towards the internet, or None."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 53))
            return s.getsockname()[0]
    except OSError:
        return None


# Interfaces no phone is on: those of containers, of virtual machines, and tunnels. The admin pages have the same list
# (tools/opendmtq_tools/admin/setup.py): these two packages do not import each other.
VIRTUAL_INTERFACES = re.compile(r"^(docker|br-|veth|virbr|vnet|vboxnet|vmnet|lxdbr|lxcbr|podman|cni|flannel|kube|cali|wg|tun|tap|tailscale|zt)")


def interface_addresses(output):
    """The IPv4 addresses in `ip -4 -o addr show scope global` output, without those of virtual interfaces."""
    found = re.findall(r"^\d+:\s+(\S+)\s+inet (\d+\.\d+\.\d+\.\d+)", output, re.M)
    return [address for name, address in found if not VIRTUAL_INTERFACES.match(name)]


def reachable(addresses):
    """Those of the addresses a phone can reach: private, and neither a loopback nor a self-assigned one."""
    return [a for a in addresses if ipaddress.IPv4Address(a).is_private and not ipaddress.IPv4Address(a).is_loopback
            and not ipaddress.IPv4Address(a).is_link_local]


def best_private(addresses):
    """The one phones most likely reach, or None: a home or office network's usual ranges before the one virtual networks
    are given (Hyper-V, WSL)."""
    private = reachable(addresses)
    return next((a for prefix in ("192.168.", "10.") for a in private if a.startswith(prefix)), private[0] if private else None)


def own_private_address():
    """A private address this machine has, whatever its routes, or None. `ip` names the interfaces, so what it leaves is real:
    with one left, that is it; with several, a wrong guess would build an app for an address no phone reaches, so whoever is at
    the terminal says which (--host). Without `ip` (Windows, macOS) only the machine's own name lists them: the likeliest of
    those, which the setup in the browser shows, with the others, before the app is built."""
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"],
                             capture_output=True, text=True, timeout=5, errors="replace").stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    listed = interface_addresses(out)
    if listed:
        private = reachable(listed)
        return private[0] if len(private) == 1 else None
    try:
        return best_private(socket.gethostbyname_ex(socket.gethostname())[2])
    # UnicodeError: a computer's name the lookup cannot encode (an empty label, one over 63 letters).
    except (OSError, UnicodeError):
        return None


def has_address(address):
    """True when this machine has the address, on any network. With several, the one towards the internet, or the likeliest, need
    not be the one the owner chose: that it still has the one the phones use is what counts."""
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, timeout=5, errors="replace").stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    if address in re.findall(r"\binet (\d+\.\d+\.\d+\.\d+)", out):
        return True
    try:
        return address in socket.gethostbyname_ex(socket.gethostname())[2]
    except (OSError, UnicodeError):
        return False


def is_wsl():
    """True inside WSL."""
    try:
        with open("/proc/version", encoding="utf-8") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def wsl_networking_mode():
    """"nat", "mirrored" or another mode WSL reports (wslinfo, WSL 2.0 and later), or None."""
    try:
        r = subprocess.run(["wslinfo", "--networking-mode"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip().lower() or None if r.returncode == 0 else None


def wsl_nat_address(host):
    """True when host is WSL's private NAT address, which phones cannot reach. A home network may
    use the same range (172.16.0.0/12: KT gateways hand out 172.30.1.x), so the range alone only
    decides when WSL cannot say which mode it runs in."""
    try:
        in_range = ipaddress.IPv4Address(host) in ipaddress.IPv4Network("172.16.0.0/12")
    except ValueError:
        return False
    if not in_range or not is_wsl():
        return False
    mode = wsl_networking_mode()
    return mode == "nat" if mode else True


def windows_drive(path, mounts=None):
    """True when path is on a Windows drive mounted into WSL (/mnt/c and the like).

    mounts is /proc/self/mounts text (read when not given). There SQLite is slow, and the owner of
    a file cannot be changed.
    """
    if mounts is None:
        try:
            with open("/proc/self/mounts", encoding="utf-8", errors="replace") as f:
                mounts = f.read()
        except OSError:
            return False
    best, windows = "", False
    for line in mounts.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        # The mount table writes a space as \040.
        point = fields[1].replace("\\040", " ")
        inside = path == point or path.startswith(point.rstrip("/") + "/")
        # The innermost mount holding the path decides.
        if inside and len(point) >= len(best):
            best = point
            windows = fields[2] == "drvfs" or (fields[2] == "9p" and "aname=drvfs" in fields[3])
    return windows
