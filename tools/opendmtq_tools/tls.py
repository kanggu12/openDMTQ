"""Certificates for the server's HTTPS door, made here: an authority of the server's own and the
server's certificate signed by it.

A public authority (Let's Encrypt and the like) only vouches for a home server that answers on port
80 or 443 from the internet; OpenDMTQ needs neither. Browsers that do not know this authority warn
once and let the visitor go on. A phone that installs ca.crt trusts the server without the warning.
The authority is name-constrained to the server's own names (its host name or IP, names under that
host name, and localhost), carries no e-mail or URI names and only vouches for web servers, so for
clients that honour the constraints a leaked authority key could not vouch for another site.

Files (data/https in the repository; ./opendmtq runs this in the one-shot tools container, which
mounts data/ at /data, with --dir /data/https):
  ca.key             the authority's key; no long-running container mounts it, and neither does the
                     import (which unpacks the owner's archives)
  ca.crt             the authority's certificate
  serve/server.crt   the server's certificate (what the edge proxy presents)
  serve/server.key   its key; of the running containers only the edge proxy reads it
  public/ca.crt      a copy of ca.crt, offered for download at /ca.crt
  state.json         the names and the profile they were made with

Every file is written to a temporary name and swapped in whole, and the server key is checked
against its certificate on each run: a run cut off half-way is repaired by the next one, instead of
leaving a pair the edge proxy cannot start with.

Usage (inside the tools container):
  python3 -m opendmtq_tools.tls --host HOST[:PORT] [--dir DIR]
Makes only what is missing, outdated, mismatched or about to expire, and prints what it did.
"""

import argparse
import ipaddress
import json
import os
import secrets
import subprocess
import tempfile

HTTPS_DIR = "/https"
# The authority outlives many server certificates; the server certificate stays within the 825
# days some clients accept for a certificate from an installed authority.
CA_DAYS = 3650
SERVER_DAYS = 825
# Renewed this long before it expires (each start checks).
RENEW_SECONDS = 30 * 24 * 3600
# What the authority looks like; a new profile makes a new authority on the next start.
PROFILE = 2


def log(msg):
    print(f"tls: {msg}", flush=True)


def is_ip(name):
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def names_for(host):
    """The names the server certificate carries: the address phones use and the loopback (for
    checks on the server PC), in a fixed order."""
    names = [host]
    for extra in ("localhost", "127.0.0.1"):
        if extra not in names:
            names.append(extra)
    return names


def name_constraints(names):
    """nameConstraints value limiting an authority to these names (a DNS name also allows names
    under it). Every name type gets an entry, as a type without one is not constrained at all: a
    DNS entry is always there (localhost is one), and e-mail and URI names may only be under
    .invalid, which never resolves."""
    parts = ["permitted;email:.invalid", "permitted;URI:.invalid"]
    for n in names:
        if is_ip(n):
            mask = "255.255.255.255" if ipaddress.ip_address(n).version == 4 else "FFFF:" * 7 + "FFFF"
            parts.append(f"permitted;IP:{n}/{mask}")
        else:
            parts.append(f"permitted;DNS:{n}")
    return "critical, " + ", ".join(parts)


def subject_alt_names(names):
    return ", ".join(("IP:" if is_ip(n) else "DNS:") + n for n in names)


def openssl(*args, config=None):
    """Runs openssl quietly; on failure shows what it said and stops."""
    cmd = ["openssl", *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"openssl {args[0]} failed: {(r.stderr or r.stdout).strip()}")
    return r.stdout


def write_file(path, data, private=False):
    """Writes path whole: the text goes to a temporary file next to it, which then replaces it, so a
    run that is cut off (Ctrl-C, a full disk, the PC turned off) leaves the old file, never half of
    one. private: readable by its owner only (keys)."""
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o666)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        if private:
            # O_CREAT's mode only applies to a new file; one left over from an earlier run is narrowed.
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        # Nothing half-written stays behind.
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def pair_matches(serve):
    """True when serve/server.key is the key of serve/server.crt. They are two files: a renewal cut
    off between them, or a file put there by hand, can leave a pair that nginx refuses, and the edge
    proxy would then not start at all."""
    key = subprocess.run(["openssl", "pkey", "-in", os.path.join(serve, "server.key"), "-pubout"],
                         capture_output=True, text=True)
    crt = subprocess.run(["openssl", "x509", "-in", os.path.join(serve, "server.crt"), "-noout", "-pubkey"],
                         capture_output=True, text=True)
    # A file that is not a key or a certificate (truncated, empty) does not match anything.
    return key.returncode == 0 and crt.returncode == 0 and key.stdout == crt.stdout


def make_ca(d, names):
    """A new name-constrained authority (replaces any old one)."""
    with tempfile.TemporaryDirectory() as tmp:
        cnf = os.path.join(tmp, "ca.cnf")
        with open(cnf, "w", encoding="utf-8") as f:
            f.write("[req]\ndistinguished_name = dn\n[dn]\n[v3_ca]\n"
                    "basicConstraints = critical, CA:TRUE, pathlen:0\n"
                    "keyUsage = critical, keyCertSign, cRLSign\n"
                    # Web servers only (clients that check it refuse anything else it signs).
                    "extendedKeyUsage = serverAuth\n"
                    "subjectKeyIdentifier = hash\n"
                    f"nameConstraints = {name_constraints(names)}\n")
        key = os.path.join(tmp, "ca.key")
        crt = os.path.join(tmp, "ca.crt")
        openssl("req", "-x509", "-new", "-nodes", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                "-keyout", key, "-out", crt, "-days", str(CA_DAYS), "-sha256",
                "-subj", f"/O=OpenDMTQ/CN=OpenDMTQ {names[0]}", "-config", cnf, "-extensions", "v3_ca")
        with open(key, encoding="utf-8") as f:
            write_file(os.path.join(d, "ca.key"), f.read(), private=True)
        with open(crt, encoding="utf-8") as f:
            ca = f.read()
    write_file(os.path.join(d, "ca.crt"), ca)


def make_server(d, names):
    """A new server certificate from the authority in d."""
    serve = os.path.join(d, "serve")
    with tempfile.TemporaryDirectory() as tmp:
        ext = os.path.join(tmp, "server.cnf")
        with open(ext, "w", encoding="utf-8") as f:
            f.write("[v3_server]\nbasicConstraints = critical, CA:FALSE\n"
                    "keyUsage = critical, digitalSignature\nextendedKeyUsage = serverAuth\n"
                    f"subjectAltName = {subject_alt_names(names)}\n"
                    "authorityKeyIdentifier = keyid\nsubjectKeyIdentifier = hash\n")
        key = os.path.join(tmp, "server.key")
        csr = os.path.join(tmp, "server.csr")
        crt = os.path.join(tmp, "server.crt")
        openssl("req", "-new", "-nodes", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                "-keyout", key, "-out", csr, "-subj", f"/CN={names[0]}")
        openssl("x509", "-req", "-in", csr, "-CA", os.path.join(d, "ca.crt"), "-CAkey", os.path.join(d, "ca.key"),
                "-set_serial", "0x" + secrets.token_hex(16), "-days", str(SERVER_DAYS), "-sha256",
                "-extfile", ext, "-extensions", "v3_server", "-out", crt)
        # The authority's constraints and the names must agree, or browsers would refuse it.
        openssl("verify", "-CAfile", os.path.join(d, "ca.crt"), crt)
        with open(key, encoding="utf-8") as f:
            write_file(os.path.join(serve, "server.key"), f.read(), private=True)
        with open(crt, encoding="utf-8") as f:
            cert = f.read()
    write_file(os.path.join(serve, "server.crt"), cert)


def expiring(path):
    """True when the certificate at path is missing or expires within RENEW_SECONDS."""
    if not os.path.isfile(path):
        return True
    r = subprocess.run(["openssl", "x509", "-checkend", str(RENEW_SECONDS), "-noout", "-in", path],
                       capture_output=True, text=True)
    return r.returncode != 0


def ensure(d, host):
    """Makes the files in d fit host (no port); returns what was made, as words."""
    names = names_for(host)
    os.makedirs(os.path.join(d, "serve"), exist_ok=True)
    os.makedirs(os.path.join(d, "public"), exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except PermissionError:
        # A folder another user made: the keys in it are still readable by their owner only.
        pass
    try:
        with open(os.path.join(d, "state.json"), encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    made = []
    # A new authority only when its names no longer fit: phones that installed it keep it.
    if (state.get("names") != names or state.get("profile") != PROFILE
            or not os.path.isfile(os.path.join(d, "ca.key")) or expiring(os.path.join(d, "ca.crt"))):
        make_ca(d, names)
        made.append("authority")
    serve = os.path.join(d, "serve")
    # A new server certificate also when its key does not belong to it (see pair_matches): the edge
    # proxy would otherwise fall back to plain HTTP for good.
    if (made or expiring(os.path.join(serve, "server.crt")) or not os.path.isfile(os.path.join(serve, "server.key"))
            or not pair_matches(serve)):
        make_server(d, names)
        made.append("server certificate")
    # The download copy follows the authority (an older layout kept it next to the key).
    with open(os.path.join(d, "ca.crt"), encoding="utf-8") as f:
        ca = f.read()
    write_file(os.path.join(d, "public", "ca.crt"), ca)
    old_copy = os.path.join(serve, "ca.crt")
    if os.path.exists(old_copy):
        os.remove(old_copy)
    if made:
        write_file(os.path.join(d, "state.json"), json.dumps({"names": names, "profile": PROFILE}))
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", required=True, help="the address phones use (PUBLIC_HOST)")
    ap.add_argument("--dir", default=HTTPS_DIR)
    args = ap.parse_args(argv)
    # The port does not belong in a certificate.
    host = args.host.rsplit(":", 1)[0] if args.host.count(":") == 1 else args.host
    made = ensure(args.dir, host)
    if made:
        log(f"made a new {' and '.join(made)} for {', '.join(names_for(host))}")
    else:
        log("certificates up to date")


if __name__ == "__main__":
    main()
