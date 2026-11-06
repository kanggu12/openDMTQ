"""The settings in .env: read, written, and filled in on a first start."""

import secrets
import socket

from opendmtq_cli import env
from .paths import ADMIN_PORT, CLI, ENV_FILE, WINDOWS
from .output import die, ok


def settings():
    """The settings in .env (an empty dict before setup)."""
    return env.load(ENV_FILE)


def listen_port(values):
    """The port the server listens on: LISTEN_PORT, else the one in the address, else 80."""
    if values.get("LISTEN_PORT"):
        return int(values["LISTEN_PORT"])
    return env.split(values.get("PUBLIC_HOST", ""))[1] if values.get("PUBLIC_HOST") else 80


def admin_port(values):
    """The port of the admin pages, on this machine only."""
    return int(values.get("ADMIN_PORT") or ADMIN_PORT)


def bindable(port, address="0.0.0.0"):
    """True when this program may listen on the port (nothing else holds it, and the system allows it)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Windows lets a second program take a port another holds unless this is set.
        if WINDOWS:
            s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", 0), 1)
        try:
            s.bind((address, port))
            return True
        except OSError:
            return False


def choose_port():
    """Port 80 when it is free and allowed (phones then need no port in the address), else the first free of 8080,
    8790 and on."""
    for port in (80, 8080, 8790, 8792, 8793, 8794, 8795):
        if bindable(port):
            return port
    die("no free port for the server among 80, 8080, 8790 and 8792 to 8795: close the program that uses them (another "
        "web server, Skype), or set another one as LISTEN_PORT in the file .env (Notepad opens it)")


def ensure_settings(host=None, quiet=False):
    """Write what .env lacks: the address phones use, the port, the admin pages' password. Returns the settings."""
    values = settings()
    updates = {}
    # The port first: the address carries it when it is not 80.
    port = listen_port(values) if values.get("PUBLIC_HOST") or values.get("LISTEN_PORT") else choose_port()
    if host:
        # An address given on the command line, with or without its port.
        problem = env.check_host(host)
        if problem:
            die(problem)
        h, p = env.split(host)
        port = p if ":" in host else port
        updates["PUBLIC_HOST"] = env.join(h, port)
    elif not values.get("PUBLIC_HOST"):
        # This machine's address on its network: what phones on the same Wi-Fi reach.
        found = env.detect_host()
        if not found or env.check_host(found):
            die("could not find this PC's network address. Connect it to the same Wi-Fi as the phones, then start "
                "OpenDMTQ.exe again" if WINDOWS else
                "could not find this computer's network address; pass it with --host 192.168.x.y")
        updates["PUBLIC_HOST"] = env.join(found, port)
    if str(values.get("LISTEN_PORT", "")) != str(port):
        updates["LISTEN_PORT"] = str(port)
    # The owner's password for the admin pages, made once and kept.
    if not values.get("ADMIN_PASSWORD"):
        updates["ADMIN_PASSWORD"] = secrets.token_urlsafe(12)
    # The admin pages' own port, free on this machine.
    if not values.get("ADMIN_PORT"):
        updates["ADMIN_PORT"] = str(next((p for p in range(ADMIN_PORT, ADMIN_PORT + 20) if bindable(p, "127.0.0.1")),
                                         ADMIN_PORT))
    if updates:
        env.save(ENV_FILE, updates)
        if not quiet:
            for k, v in updates.items():
                ok(f"{k}={'(made, see below)' if k == 'ADMIN_PASSWORD' else v} written to .env")
    return settings()


def require_settings():
    """The settings, or stop when setup has not run."""
    values = settings()
    if not values.get("PUBLIC_HOST"):
        die(f"not set up yet: run {CLI} setup")
    return values
