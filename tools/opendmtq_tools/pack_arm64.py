"""Adds the arm32 runtime to a patched APK, so 64-bit-only phones can run the 32-bit game.

The result is one APK for every phone. lib/armeabi-v7a keeps the game's own libraries, and the
manifest asks for multiArch with use32bitAbi: a phone that runs 32-bit apps installs it as a
32-bit app and runs the game natively, as before. A phone without 32-bit support (Galaxy S24 and
later, Pixel 7 and later) only matches lib/arm64-v8a, which holds:

  libarm32.so              the runtime
  <name>                   for every 32-bit library: a proxy that loads it in the runtime
  libarm32g-<name>         the 32-bit library itself
  libarm32s-<name>         the guest system: linker, C library, stub libraries, agent

The runtime comes as a bundle that arm32/bundle.sh makes:

  bundle.json              version and the host ABIs it was built for
  <abi>/libarm32.so, <abi>/libarm32proxy.so
  sysroot/bin/linker, sysroot/lib/*.so
  arm32-agent
  notices/                 the licenses of all that, for assets/opendmtq in the app

Usage (inside the tools container):
  python3 -m opendmtq_tools.pack_arm64 --in A.apk --out B.apk --bundle DIR [--abi arm64-v8a]
      [--only-64bit] --keystore KS --password-file FILE
"""

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

from . import axml

GUEST_ABI = "lib/armeabi-v7a/"
# Where the app carries the licenses of the parts this adds (the bundle's notices/).
NOTICES = "assets/opendmtq/"
# The manifest attributes that make a 32-bit-capable phone pick lib/armeabi-v7a.
FLAGS = {"multiArch": (0x0101048E, True), "use32bitAbi": (0x01010515, True)}
# The signer and Java: the image's, or the ones a host install names (host/install.sh, the Windows bundle).
SIGNER = os.environ.get("OPENDMTQ_SIGNER") or "/opt/uber-apk-signer.jar"
JAVA = os.environ.get("OPENDMTQ_JAVA") or "java"


def read_bundle(bundle):
    """The bundle's manifest; fails when the folder is not a runtime bundle."""
    try:
        with open(os.path.join(bundle, "bundle.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"pack_arm64: {bundle} is not a runtime bundle ({e})")


# The shim's library and the tweaks file, as they are named in a library folder.
SHIM = "libopendmtq.so"
TWEAKS = "libarm32t-tweaks.so"


def pack(src_apk, unsigned_apk, bundle, abi, only_64bit, debuggable=False, tweaks=""):
    """Writes the unsigned APK; returns the number of 32-bit libraries carried. debuggable marks
    the app for profilers (simpleperf --app); test builds only. tweaks is the text of the
    runtime's tweaks file (arm32/src/tweaks.cpp), installed next to the libraries."""
    flags = dict(FLAGS)
    if debuggable:
        flags["debuggable"] = (0x0101000F, True)
    abi_dir = f"lib/{abi}/"
    runtime = os.path.join(bundle, abi)
    if not os.path.isfile(os.path.join(runtime, "libarm32.so")):
        raise SystemExit(f"pack_arm64: the bundle has no {abi} runtime")
    with zipfile.ZipFile(src_apk) as src, zipfile.ZipFile(unsigned_apk, "w") as out:
        names = src.namelist()
        # (Not what this packer itself adds there: see the end.)
        guest_libs = sorted(n[len(GUEST_ABI):] for n in names if n.startswith(GUEST_ABI) and n.endswith(".so")
                            and n not in (GUEST_ABI + SHIM, GUEST_ABI + TWEAKS))
        if not guest_libs:
            raise SystemExit("pack_arm64: the APK has no lib/armeabi-v7a libraries")
        # The 32-bit libraries, read once for both places they go.
        guest_data = {lib: src.read(GUEST_ABI + lib) for lib in guest_libs}
        for info in src.infolist():
            n = info.filename
            # Old signatures go; so does an earlier runtime, and the 32-bit folders if asked.
            if n.startswith("META-INF/") and n.rsplit(".", 1)[-1].upper() in ("SF", "RSA", "DSA", "EC", "MF"):
                continue
            if n.startswith(abi_dir) or (only_64bit and n.startswith(("lib/armeabi-v7a/", "lib/armeabi/"))):
                continue
            if n in (GUEST_ABI + SHIM, GUEST_ABI + TWEAKS) or n.startswith(NOTICES):
                continue
            data = src.read(n)
            if n == "AndroidManifest.xml" and (not only_64bit or debuggable):
                data = axml.set_application_flags(data, flags if not only_64bit else {k: v for k, v in flags.items() if k == "debuggable"})
            # writestr records the new offsets in the ZipInfo it gets: give it a copy, not the
            # source archive's own entry.
            out.writestr(copy.copy(info), data)

        def add(path, name):
            out.write(path, abi_dir + name, compress_type=zipfile.ZIP_DEFLATED)

        add(os.path.join(runtime, "libarm32.so"), "libarm32.so")
        for lib in guest_libs:
            out.writestr(zipfile.ZipInfo(abi_dir + "libarm32g-" + lib), guest_data[lib], compress_type=zipfile.ZIP_DEFLATED)
            add(os.path.join(runtime, "libarm32proxy.so"), lib)
        add(os.path.join(bundle, "sysroot", "bin", "linker"), "libarm32s-linker.so")
        for lib in sorted(os.listdir(os.path.join(bundle, "sysroot", "lib"))):
            if lib.endswith(".so"):
                add(os.path.join(bundle, "sysroot", "lib", lib), "libarm32s-" + lib)
        add(os.path.join(bundle, "arm32-agent"), "libarm32s-arm32-agent.so")
        # Their licenses go along: most ask to be in every copy. A bundle made before this has none.
        notices = os.path.join(bundle, "notices")
        if os.path.isdir(notices):
            for name in sorted(os.listdir(notices)):
                out.write(os.path.join(notices, name), NOTICES + name, compress_type=zipfile.ZIP_DEFLATED)
        if tweaks:
            # A library name, so the installer extracts it with the others.
            out.writestr(zipfile.ZipInfo(abi_dir + "libarm32t-tweaks.so"), tweaks.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        # For phones that keep running the game's own 32-bit libraries: the shim (arm32/shim/shim.cpp), with
        # the same tweaks file. It has no proxy: the runtime never loads it.
        shim = os.path.join(bundle, "armeabi-v7a", SHIM)
        # A bundle made before there was a shim still works; only say what it means.
        if not only_64bit and not os.path.isfile(shim):
            print("warning: the arm32 bundle has no shim: phones that run 32-bit get no broadcast and keep the game's "
                  "frame rate. Make the bundle again: arm32/bundle.sh", flush=True)
        if not only_64bit and os.path.isfile(shim):
            out.write(shim, GUEST_ABI + SHIM, compress_type=zipfile.ZIP_DEFLATED)
            if tweaks:
                out.writestr(zipfile.ZipInfo(GUEST_ABI + TWEAKS), tweaks.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
    return len(guest_libs)


def sign(unsigned_apk, out_apk, keystore, password, alias="opendmtq"):
    """Zip alignment and v1+v2+v3 signatures, as for the 32-bit builds."""
    work = tempfile.mkdtemp()
    try:
        r = subprocess.run([JAVA, "-jar", SIGNER, "-a", unsigned_apk, "-o", work, "--ks", keystore,
                            "--ksAlias", alias, "--ksPass", password, "--ksKeyPass", password],
                           # Java writes in the system's code page, this program reads UTF-8: a message in another
                           # language must not stop the build.
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            sys.stderr.write(r.stdout + r.stderr)
            raise SystemExit("pack_arm64: signing failed")
        signed = [f for f in os.listdir(work) if f.endswith(".apk")]
        shutil.copyfile(os.path.join(work, signed[0]), out_apk)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bundle", required=True, help="runtime bundle folder (arm32/bundle.sh)")
    ap.add_argument("--abi", default="arm64-v8a", help="host ABI of the runtime (x86_64 for the emulator)")
    ap.add_argument("--only-64bit", action="store_true", help="drop the 32-bit libraries (runtime always)")
    ap.add_argument("--debuggable", action="store_true", help="mark the app debuggable, for profiling (test builds)")
    ap.add_argument("--tweaks", help="runtime tweaks file to install with the libraries")
    ap.add_argument("--keystore", required=True)
    ap.add_argument("--password-file", required=True)
    a = ap.parse_args(argv)
    read_bundle(a.bundle)
    work = tempfile.mkdtemp()
    try:
        unsigned = os.path.join(work, "unsigned.apk")
        tweaks = open(a.tweaks, encoding="utf-8").read() if a.tweaks else ""
        n = pack(a.src, unsigned, a.bundle, a.abi, a.only_64bit, a.debuggable, tweaks)
        with open(a.password_file, encoding="utf-8") as f:
            password = f.read().strip()
        sign(unsigned, a.out, a.keystore, password)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"pack_arm64: {n} 32-bit libraries, runtime for {a.abi} -> {a.out}")


if __name__ == "__main__":
    main()
