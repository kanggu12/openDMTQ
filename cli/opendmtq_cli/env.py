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


def parse(text):
    """KEY=value pairs from .env text, the way docker compose reads them."""
    values = {}
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
    """Values from .env, or {} when it does not exist yet."""
    try:
        with open(path, encoding="utf-8") as f:
            return parse(f.read())
    except FileNotFoundError:
        return {}


def save(path, updates):
    """Set keys in .env, keeping every other line (and comments) as they are."""
    try:
        with open(path, encoding="utf-8") as f:
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
    """("host", port) from "host" or "host:port"; port 80 when none is given."""
    host, sep, port = address.rpartition(":")
    if not sep:
        return address, 80
    return host, int(port) if port.isdigit() else -1


def join(host, port):
    """The address the app uses: "host", or "host:port" for any port but 80."""
    return host if int(port) == 80 else f"{host}:{port}"


def https_address(address):
    """The address with its port always written out, for https:// links: HTTPS is served on the
    same port as plain HTTP, so a port-80 server is https://host:80/, not the default 443."""
    host, port = split(address)
    return f"{host}:{port}"


def listen_port(values):
    """Port the server publishes (LISTEN_PORT in .env, 80 when unset)."""
    return int(values.get("LISTEN_PORT") or 80)


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
            f"(LISTEN_PORT); run ./opendmtq host {host} for port 80, or ./opendmtq host {join(host, listen)}")


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
