"""Server-side app builder: keeps data/apk/out in step with the server.

Runs whenever the stack starts (compose service `builder`, Helm hook Job). Builds a new APK only
when there is none yet, or the newest one was made for another address, another base APK, an
older patcher, another signing key or another arm32 runtime bundle, or its file is damaged.
Otherwise it exits at once. The runtime for newer phones comes first, when it is not in place yet (runtime.py). Each run leaves its outcome in data/apk/out/build.json for the portal,
the admin pages and the command line. The installer for Windows (windows_client.py) is put beside the app once build.json
says the app is done: what becomes of it changes nothing for phones.

Usage (inside the tools container): python3 -m opendmtq_tools.builder [--force]
"""

import argparse
import datetime
import json
import os
import signal
import subprocess
import sys
import threading
import time

from . import patch_apk, runtime, windows_client

OUT = os.path.join(patch_apk.APK_DIR, "out")
# A status still saying "building" after this long belongs to a run that was cut off (its container
# killed, the PC turned off). The portal (server/portal/lib.php), the admin pages and the command
# line all read it as failed after this long.
STALE_BUILD = 15 * 60


def write_status(state, host, **details):
    """Record where the run stands in out/build.json: "building", "failed" (with the reason, for the
    owner) or "done" (with "file" when this run made a new app), and when (Unix seconds). While there
    is no app for the address, the portal reloads until it says done, and stops on failed. Not being
    able to write it never stops a run."""
    status = {"state": state, "host": host, "time": int(time.time()), **details}
    path = os.path.join(OUT, "build.json")
    try:
        os.makedirs(OUT, exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2)
        # Atomic swap, like the manifests: readers never see half a file.
        os.replace(path + ".tmp", path)
    except OSError as e:
        print(f"builder: cannot write {path}: {e}", file=sys.stderr, flush=True)


def short_reason(err):
    """One line for the owner: the patcher's own message, or which program failed. Never a failed
    program's command line: keytool's and the signer's carry the signing key's password, and the
    reason is shown on the admin pages and kept in a file everyone on the server PC can read."""
    if isinstance(err, (subprocess.CalledProcessError, subprocess.TimeoutExpired)):
        cmd = [str(c) for c in err.cmd] if isinstance(err.cmd, (list, tuple)) else str(err.cmd).split()
        program = os.path.basename(cmd[0]) if cmd else "a program"
        # "java -jar /opt/apktool.jar ...": the tool is the jar, not java (java.exe on Windows).
        if os.path.splitext(program)[0] == "java" and "-jar" in cmd[:-1]:
            program = os.path.basename(cmd[cmd.index("-jar") + 1])
        if isinstance(err, subprocess.TimeoutExpired):
            text = f"{program} did not finish in {err.timeout:g} s"
        else:
            text = f"{program} failed (exit status {err.returncode})"
    elif isinstance(err, KeyboardInterrupt):
        text = "stopped part-way (interrupted)"
    else:
        text = str(err.code if isinstance(err, SystemExit) else err) or err.__class__.__name__
    return " ".join(text.split())[:300]


def stopped(signum, frame):
    """SIGTERM handler: end the run like an error, so that build.json says what happened. Once the app is done, it ends
    only the installer for Windows (windows_installer), and build.json stays done."""
    raise SystemExit("stopped part-way (the builder was stopped)")


def current_manifest():
    """The manifest of the newest build, or None."""
    try:
        with open(os.path.join(OUT, "latest.json"), encoding="utf-8") as f:
            m = json.load(f)
        # A manifest whose file was deleted is no build at all.
        return m if os.path.isfile(os.path.join(OUT, os.path.basename(m["file"]))) else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def reason_to_build(host, base):
    """Why a build is needed, or None when the newest APK already fits."""
    m = current_manifest()
    if m is None:
        return "no app built yet"
    # A file that is not the size its manifest records was cut short or overwritten (by a copy that
    # failed half-way, before builds swapped their file in whole): phones would download a broken app.
    size = m.get("size")
    if isinstance(size, int) and os.path.getsize(os.path.join(OUT, os.path.basename(m["file"]))) != size:
        return "the app file does not match its manifest (damaged)"
    if m.get("host") != host:
        return f"address changed ({m.get('host')} -> {host})"
    if m.get("label") != patch_apk.app_label(host):
        return f"app name changed ({m.get('label')} -> {patch_apk.app_label(host)})"
    if m.get("base_sha256") != patch_apk.sha256(base):
        return "base APK changed"
    if m.get("patcher") != patch_apk.VERSION:
        return f"patcher updated ({m.get('patcher')} -> {patch_apk.VERSION})"
    key = patch_apk.keystore_sha256()
    if key is None and m.get("key_sha256"):
        # The build refuses a new key and says how to put the old one back: better now than at
        # the next address change.
        return "signing key missing"
    if key and m.get("key_sha256") != key:
        return "signing key changed (restored from a backup?)"
    runtime = patch_apk.runtime_version()
    if m.get("runtime") != runtime:
        return f"arm32 runtime changed ({m.get('runtime')} -> {runtime})"
    return None


def windows_installer():
    """The installer for Windows beside the app, for the site to hand out (windows_client.py), after build.json says the
    app is done. Its failure stops nothing: phones get their app all the same. A stop while it runs (docker stop's
    SIGTERM, through stopped(); Ctrl-C) ends it there, its half-copied file removed, and the app stays done: the next run
    puts it there."""
    try:
        name = windows_client.keep(OUT)
    except Exception as e:  # noqa: BLE001 - a full disk, a damaged file: the app is still good
        print(f"builder: no installer for Windows: {short_reason(e)}", flush=True)
        return
    # Not an error of the builder's: the run was asked to end, and it does, saying where.
    except (SystemExit, KeyboardInterrupt) as e:
        print(f"builder: the installer for Windows {short_reason(e)}", flush=True)
        return
    if name:
        print(f"builder: installer for Windows {name}", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default=os.environ.get("PUBLIC_HOST"))
    ap.add_argument("--force", action="store_true", help="build even if the newest APK fits")
    # BASE_APK (from .env, or baseApk in the Helm values) picks one when data/apk/base holds several different clients
    # (else the newest is used).
    ap.add_argument("--base", default=os.environ.get("BASE_APK") or None)
    args = ap.parse_args(argv)
    # docker stop (and compose down) sends SIGTERM. As the container's first process, Python would
    # ignore it (the kernel gives PID 1 no default action) until Docker kills it ten seconds later,
    # leaving "building" behind; with a handler the run stops at once and says so. Signal handlers can
    # only be set from the main thread.
    previous, handled = None, threading.current_thread() is threading.main_thread()
    if handled:
        previous = signal.signal(signal.SIGTERM, stopped)
    try:
        return run(args)
    finally:
        # Put back what was there (tests run this in a process that goes on).
        if handled:
            signal.signal(signal.SIGTERM, previous if previous is not None else signal.SIG_DFL)


def run(args):
    """The run, with the SIGTERM handler in place: the app when it needs building, its outcome in build.json, then the
    installer for Windows."""
    try:
        host = patch_apk.validate_host(args.host)
        base = patch_apk.find_base(os.path.join(patch_apk.APK_DIR, "base"), args.base)
        # Before the question whether to build: a runtime that has just come is a reason to. Its failure stops nothing, as
        # the app still runs on phones that run 32-bit apps; it is noted for the owner's pages.
        runtime.add_or_note(patch_apk.APK_DIR)
        why = "forced" if args.force else reason_to_build(host, base)
        # Up to date: no new app, and no "file" in build.json.
        name = None
        if why is None:
            print(f"builder: app for http://{host}/ is up to date", flush=True)
        else:
            print(f"builder: building ({why})", flush=True)
            write_status("building", host, reason=why)
            name = patch_apk.main(["--host", host, "--base", base,
                                   "--stamp", datetime.date.today().strftime("%Y.%m.%d")])
    except BaseException as e:  # noqa: BLE001 - the patcher stops with SystemExit, a tool's error, Ctrl-C or SIGTERM
        # Players are told the app could not be built; the owner finds why on the admin pages and
        # with ./opendmtq doctor.
        if not (isinstance(e, SystemExit) and e.code in (None, 0)):
            write_status("failed", args.host or "", error=short_reason(e))
        raise
    # The app is done, said before the installer for Windows: phones can have it now, and that step can take a while. "file":
    # this run made a new app (the command line reports a run with one as built).
    write_status("done", host, **({"file": name} if name else {}))
    # Still under the SIGTERM handler: a docker stop ends this step at once, and build.json goes on saying done.
    windows_installer()
    return 0


if __name__ == "__main__":
    sys.exit(main())
