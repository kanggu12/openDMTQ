"""The programs a host install runs: finding Apache, PHP, Java and the rest, here or in the bundle."""

import glob
import os
import shutil

from .paths import BUNDLE, LOCAL, MAC, RUN
from .output import die, say


def brew_prefix():
    """Homebrew's folder on a Mac (/opt/homebrew on Apple silicon, /usr/local on Intel), or None."""
    for prefix in (os.environ.get("HOMEBREW_PREFIX", ""), "/opt/homebrew", "/usr/local"):
        if prefix and os.path.isdir(os.path.join(prefix, "opt", "httpd")):
            return prefix
    return None


def first(*paths):
    """The first of the paths that exists, or None."""
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def find_programs():
    """Every program the server needs, found once: {name: path}, with None for what is missing."""
    found = {}
    if BUNDLE:
        # The Windows bundle: everything is in runtime/.
        rt = os.path.join(BUNDLE, "runtime")
        found["httpd"] = first(os.path.join(rt, "apache", "bin", "httpd.exe"))
        found["modules"] = first(os.path.join(rt, "apache", "modules"))
        found["mime"] = first(os.path.join(rt, "apache", "conf", "mime.types"))
        found["rotatelogs"] = first(os.path.join(rt, "apache", "bin", "rotatelogs.exe"))
        found["php"] = first(os.path.join(rt, "php", "php.exe"))
        found["phpmod"] = first(os.path.join(rt, "php", "php8apache2_4.dll"))
        # PHP's extensions; its php.ini is written into the run folder at every start (php_ini()).
        found["phpext"] = first(os.path.join(rt, "php", "ext"))
        found["phpini"] = RUN
        found["java"] = first(os.path.join(rt, "java", "bin", "java.exe"))
        found["keytool"] = first(os.path.join(rt, "java", "bin", "keytool.exe"))
        found["7zip"] = first(os.path.join(rt, "7zip", "7z.exe"))
        found["apktool"] = first(os.path.join(rt, "jars", "apktool.jar"))
        found["signer"] = first(os.path.join(rt, "jars", "uber-apk-signer.jar"))
        return found
    brew = brew_prefix() if MAC else None
    if brew:
        # macOS: Homebrew's httpd and php (host/install.sh installs them).
        found["httpd"] = first(os.path.join(brew, "opt", "httpd", "bin", "httpd"))
        found["modules"] = first(os.path.join(brew, "lib", "httpd", "modules"))
        found["mime"] = first(os.path.join(brew, "etc", "httpd", "mime.types"))
        found["rotatelogs"] = first(os.path.join(brew, "opt", "httpd", "bin", "rotatelogs"))
        found["php"] = first(os.path.join(brew, "opt", "php", "bin", "php"))
        found["phpmod"] = first(os.path.join(brew, "opt", "php", "lib", "httpd", "modules", "libphp.so"))
    else:
        # Linux: the distribution's Apache (Debian and Ubuntu name it apache2) and its PHP module.
        found["httpd"] = first("/usr/sbin/apache2", "/usr/sbin/httpd", shutil.which("apache2"), shutil.which("httpd"))
        found["modules"] = first("/usr/lib/apache2/modules", "/usr/lib64/httpd/modules", "/usr/lib/httpd/modules")
        found["mime"] = first("/etc/mime.types", "/etc/httpd/conf/mime.types", "/etc/apache2/mime.types")
        found["rotatelogs"] = first(shutil.which("rotatelogs"), "/usr/bin/rotatelogs", "/usr/sbin/rotatelogs")
        found["php"] = first(shutil.which("php"))
        # The module is named after its version on Debian (libphp8.3.so), plainly elsewhere.
        mods = found["modules"] and sorted(glob.glob(os.path.join(found["modules"], "libphp*.so")))
        found["phpmod"] = mods[-1] if mods else None
    found["phpini"] = None
    # Java (Homebrew's is not on the PATH), and the tools install.sh fetched into .host/ (pinned, checked by hash).
    jdk = os.path.join(brew, "opt", "openjdk", "bin") if brew else ""
    found["java"] = first(jdk and os.path.join(jdk, "java"), shutil.which("java"))
    found["keytool"] = first(jdk and os.path.join(jdk, "keytool"), shutil.which("keytool"))
    found["7zip"] = first(os.path.join(LOCAL, "bin", "7zz"), shutil.which("7zz"))
    found["apktool"] = first(os.path.join(LOCAL, "jars", "apktool.jar"))
    found["signer"] = first(os.path.join(LOCAL, "jars", "uber-apk-signer.jar"))
    return found

# What each program is for, for the message when it is missing.
NEEDED = {
    "httpd": "Apache (the web server)",
    "modules": "Apache's modules",
    "mime": "Apache's list of file types (mime.types)",
    "rotatelogs": "Apache's rotatelogs (keeps the logs small)",
    "php": "PHP 8.1 or newer (the command line program)",
    "phpmod": "PHP's Apache module",
    "java": "Java 17 or newer (builds the phone app)",
    "keytool": "Java's keytool (makes the app's signing key)",
    "7zip": "7-Zip (opens the game's archives)",
    "apktool": "apktool (builds the phone app)",
    "signer": "uber-apk-signer (signs the phone app)",
}


def programs():
    """The programs, or stop with what is missing and how to get it."""
    found = find_programs()
    missing = [NEEDED[k] for k in NEEDED if not found.get(k)]
    if missing:
        for m in missing:
            say(f"  missing  {m}")
        die("run host/install.sh to install what is missing" if not BUNDLE else
            "the bundle is incomplete: unpack the whole zip again")
    return found
