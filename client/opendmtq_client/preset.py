"""The server a downloaded installer is set up for: its end, which the server's site adds as it hands the installer out
(tools/opendmtq_tools/windows_client.py), and the hand-over from the installer to the launcher.

The end is the server's details as JSON, their length in 4 bytes (little-endian), and OPENDMTQ-PRESET1:

    <{"version": 1, "url": "https://host:port", "name": "...", "ca": "-----BEGIN ..."}><length><OPENDMTQ-PRESET1>

"ca" comes with an address over HTTPS when the server answers HTTPS with a certificate of its own authority: the
launcher trusts that authority for that server alone (server.trust). The installer reads the end from its own file and
leaves it in the launcher's folder as preset.json; the launcher takes it at its next start and plays on that server from
then on. An installer from a release has no end and asks nothing.
"""

import json
import os
import struct
import tempfile

from opendmtq_client import state as st

MAGIC = b"OPENDMTQ-PRESET1"
FORMAT = 1
# The details are a few hundred bytes; anything far longer is no server's end.
LIMIT = 64 * 1024
# The hand-over file in the launcher's folder.
FILE_NAME = "preset.json"
# A certificate authority's certificate is two kilobytes or so: anything far larger is none.
CA_LIMIT = 16 * 1024


def _valid(details):
    """The details when they are a server's address and name in a format this launcher reads, else None; with "ca", the
    server's own authority, when the address is over HTTPS and it is one whole certificate."""
    if not isinstance(details, dict) or details.get("version") != FORMAT:
        return None
    url = details.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")) or len(url) > 300:
        return None
    name = details.get("name")
    found = {"url": url.rstrip("/"), "name": name if isinstance(name, str) and name.strip() else url}
    ca = details.get("ca").strip() if isinstance(details.get("ca"), str) else ""
    # Only for HTTPS (plain HTTP has no certificate to check), and only a certificate, whole.
    whole = ca.startswith("-----BEGIN CERTIFICATE-----") and ca.endswith("-----END CERTIFICATE-----")
    if url.startswith("https://") and whole and len(ca) <= CA_LIMIT:
        found["ca"] = ca
    return found


def read(path):
    """The server an installer's file is set up for, {"url", "name"} (and "ca"), or None (none, or an end that cannot be
    read)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            # The length and the mark come last.
            if size < len(MAGIC) + 4:
                return None
            f.seek(size - len(MAGIC) - 4)
            tail = f.read(len(MAGIC) + 4)
            if tail[4:] != MAGIC:
                return None
            length = struct.unpack("<I", tail[:4])[0]
            if not 0 < length <= LIMIT or length > size - len(MAGIC) - 4:
                return None
            f.seek(size - len(MAGIC) - 4 - length)
            details = json.loads(f.read(length).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, struct.error):
        return None
    return _valid(details)


def tail(url, name, ca=""):
    """The end for a server, as the site makes it (the tests make installers with it); `ca` left out when ""."""
    details = {"version": FORMAT, "url": url, "name": name}
    if ca:
        details["ca"] = ca
    data = json.dumps(details, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return data + struct.pack("<I", len(data)) + MAGIC


def hand_over(details):
    """Leave the server for the launcher to take at its next start (the installer, before it starts the launcher)."""
    folder = st.config_dir()
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".preset-")
    kept = {"version": FORMAT, "url": details["url"], "name": details["name"]}
    # The server's own authority goes along, for the launcher to trust.
    if details.get("ca"):
        kept["ca"] = details["ca"]
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(folder, FILE_NAME))


def take():
    """The server an installer left, once: {"url", "name"} (and "ca"), or None. The file goes either way (one it cannot
    read would otherwise be read again at every start). A server's own authority is trusted for that server from here
    on (server.trust), under its address as the launcher writes every address."""
    path = os.path.join(st.config_dir(), FILE_NAME)
    try:
        with open(path, encoding="utf-8") as f:
            details = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        details = None
    try:
        os.remove(path)
    except OSError:
        pass
    found = _valid(details)
    if found and found.get("ca"):
        # Here only, in the launcher: the installer reads and leaves the end without the network modules, which its
        # build leaves out (client/packaging/windows/setup.spec).
        from opendmtq_client import server as srv
        try:
            srv.trust(srv.normalize(found["url"]), found["ca"])
        except (srv.ServerError, OSError):
            # An address the launcher cannot read (the guide asks for another), or a folder it cannot write: no trust.
            pass
    return found
