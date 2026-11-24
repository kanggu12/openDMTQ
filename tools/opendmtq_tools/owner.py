"""The owner's account for the players' site (owner.pass beside the database): its ID, and its password as the site's
accounts table keeps one (PBKDF2-SHA256, which the site's PHP checks). The admin pages write it at their start
(admin/auth.py) and the repair writes it again (repair.py); standard library only, so the repair runs without the admin
pages' libraries."""

import hashlib
import hmac
import os
import re
import secrets

# An owner's ID the players' site takes (server/portal/auth.php site_owner(), whose sign-in cookie carries 1 to 40 of its
# bytes): any other opens the admin pages and never the site, whose sign-in then answers "Wrong ID or password". The
# command line's copy, for its starts: cli/opendmtq_cli/env.py OWNER_ID.
OWNER_ID = re.compile(r"[A-Za-z0-9._-]{1,40}")

# The rounds of the accounts' passwords (admin/auth.py ACCOUNT_ROUNDS, the site's SITE_ROUNDS): the same number.
ROUNDS = 120000


def password_hash(password, salt=None):
    """A password as the accounts table keeps it: pbkdf2_sha256$<rounds>$<salt, hex>$<hash, hex>."""
    salt = secrets.token_bytes(16) if salt is None else salt
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ROUNDS)
    return f"pbkdf2_sha256${ROUNDS}${salt.hex()}${digest.hex()}"


def password_ok(stored, password):
    """Whether password is the one stored, as password_hash wrote it (with the rounds it was written with)."""
    parts = (stored or "").split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256" or not parts[1].isdigit() or not 1000 <= int(parts[1]) <= 5000000:
        return False
    try:
        salt = bytes.fromhex(parts[2])
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8", "replace"), salt, int(parts[1]))
    return hmac.compare_digest(digest.hex(), parts[3])


def write_file(path, user, password, hash_fn=password_hash, check_fn=password_ok):
    """The file at path made right for this ID and password: "kept" when it was already, "written", "removed" (no
    password set: nothing to sign in with on the site either), or "failed" when its folder cannot be written."""
    try:
        if not password:
            if os.path.exists(path):
                os.remove(path)
                return "removed"
            return "kept"
        try:
            with open(path, encoding="utf-8") as f:
                name, stored = (f.read().splitlines() + ["", ""])[:2]
        except FileNotFoundError:
            name, stored = "", ""
        # Already right: the same ID and the same password (its salt kept, so a sign-in on the site outlives a restart).
        if name == user and check_fn(stored, password):
            return "kept"
        # A new file beside it, then moved over the old one, so the site never reads half of it. This user's only.
        temp = path + ".new"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{user}\n{hash_fn(password)}\n")
        os.replace(temp, path)
        return "written"
    except OSError:
        return "failed"
