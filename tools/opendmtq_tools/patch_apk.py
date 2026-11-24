"""Point a DJMAX Technika Q 1.3.x Android client at an OpenDMTQ server over plain HTTP.

The client reaches its backend through two layers:
  * Unity IL2CPP string literals in global-metadata.dat: the game RPC and the platform API.
  * The platform's Java SDK in classes.dex: login and platform calls, some forced to HTTPS.

Both are rewritten to http://HOST. The game keeps to plain HTTP: it would not trust the certificate
of the server's own authority (the HTTPS on the same port is for browsers). The manifest allows
cleartext HTTP, so the phone needs no hosts app, proxy or certificate.
Besides the addresses, a few edits to the SDK, the game code, the game's screens and its words take out what is of
no use on this server (smali_edits, IL2CPP_EDITS, ASSET_EDITS, patch_words). What the client calls its servers, its
package, its SDK's code and its screens' objects is read from client_marks, which keeps them encoded: this file says
what each is for.

Usage (inside the tools container): python3 -m opendmtq_tools.patch_apk --host 192.168.0.10 [--base FILE]
"""

import argparse
import contextlib
import csv
import datetime
import glob
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import signal
import struct
import subprocess
import sys
import threading
import zipfile

from . import axml, client_marks, filelock, il2cpp, pack_arm64, qr, unity_assets

# Tool version stamped into the manifest, so a portal can tell which patcher made an APK.
VERSION = "1.13.0"
# data/apk: base/ in, out/ and keystore/ written. The image mounts it at /apk; a host install names it.
APK_DIR = os.environ.get("OPENDMTQ_APK", "/apk")
# The command that imports on this install, for the messages that name it: the Windows bundle's program (the only one
# that runs these tools on Windows), else ./opendmtq (Docker Compose and the host installs on Linux and macOS).
CLI = "OpenDMTQ.exe" if os.name == "nt" else "./opendmtq"
# Pinned tools: baked into the image, fetched into .host/ by a host install (host/install.sh).
APKTOOL = os.environ.get("OPENDMTQ_APKTOOL") or "/opt/apktool.jar"
SIGNER = pack_arm64.SIGNER
# Java and its keytool: on the PATH in the image, the bundle's own on Windows.
JAVA = pack_arm64.JAVA
KEYTOOL = os.environ.get("OPENDMTQ_KEYTOOL") or "keytool"
# IL2CPP metadata inside the APK.
METADATA = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
# The game's RPC, the same path on every server: a scheme, a host, then /DMQ/rpc. How the client's server address is
# found, the original's and that of a client changed for another server alike, whatever host it was given there.
RPC_LITERAL = re.compile(r"(https?://)([^/\s]+)/DMQ/rpc")
# The original client's own hosts for it (client_marks), the live one first: those are no other server.
OFFICIAL_RPC_HOSTS = client_marks.RPC_HOSTS
# The literal every original client contains once, its live RPC address: how an original base APK is recognised.
MARKER = f"https://{OFFICIAL_RPC_HOSTS[0]}/DMQ/rpc"
# The class this patcher adds to the app (HOOK_SMALI): an app it built has it.
HOOK_CLASS = b"Lcom/opendmtq/Hook;"
# The game's code, where the code edits go (IL2CPP_EDITS).
CODE_FILE = "lib/armeabi-v7a/libil2cpp.so"
# Longest address accepted ("host" or "host:port"); long literals are appended, see il2cpp.py.
MAX_HOST_LEN = 80
# IPv4 address or DNS name, optionally with a port.
HOST_RE = re.compile(r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*(?::[0-9]{1,5})?")
# The original game's package name (client_marks): each server's app has its own after it (package_id).
BASE_PACKAGE = client_marks.PACKAGE
# The Android version the app says it was made for (patch_target), and android:usesCleartextTraffic's resource ID.
TARGET_SDK = 28
ATTR_CLEARTEXT = 0x010104ec
# The game's own title, and how long a server's name after it may be: an address fits.
APP_TITLE = "TECHNIKA Q"
MAX_SERVER_NAME = MAX_HOST_LEN
# Scratch space: the container's /tmp, or the system's temporary folder on a host install.
WORK = os.environ.get("OPENDMTQ_WORK") or "/tmp/opendmtq-apk"
# The arm32 runtime bundle (arm32/bundle.sh), when the server has one: with it the APK also runs
# on phones without 32-bit support.
RUNTIME_DIR = os.path.join(APK_DIR, "arm32")


# The game caps its frame rate in two static fields of its frame rate class: one while playing, one in the menus (the
# step down when they sit idle is taken out: see IL2CPP_EDITS). Both are 60 in its static constructor; the runtime sets
# them to the frame rate it runs at ("fps", debug.arm32.framerate), which its window also asks the display for: the
# tweaks file's two lines for them are client_marks'. Only the game's UI library reads Unity's frame count, to update
# once per frame; the game logic times itself with Unity's time and the audio. The build adds a line "server <address>":
# where the runtime's live view asks and sends (see arm32/src/live.cpp).
ARM32_TWEAKS = "# arm32 runtime tweaks: <assembly> <namespace or -> <class> <field> <value or fps>\n" + client_marks.TWEAKS


def server_name(host):
    """The server's name for the app's title: SERVER_NAME, or else the whole address it is hosted at. The
    port stays: one host can run several servers on different ports."""
    return os.environ.get("SERVER_NAME", "").strip() or host


def app_label(host):
    """The app's name on the phone, so that a player can tell the apps of several servers apart."""
    name = server_name(host)
    if len(name) > MAX_SERVER_NAME or not name.isprintable():
        raise SystemExit(f"SERVER_NAME must be printable and at most {MAX_SERVER_NAME} characters: {name!r}")
    return f"{APP_TITLE} ({name})"


def package_id(key_sha256):
    """This server's app's package name. Android tells apps apart by it, so each server's app can sit next
    to the others and to the original game. It comes from the signing key: that is what makes a server
    the same server to a phone (an update must carry the same key), it survives a change of address, and
    it comes back with the key from a backup."""
    return f"{BASE_PACKAGE}.s{key_sha256[:10]}"


def patch_package(src, package):
    """The package name in the manifest and the resource table, both kept compiled (apktool -r). A client changed for
    another server may have been given another package name, in the manifest only or in both."""
    log(f"package  {package}")
    with open(os.path.join(src, "AndroidManifest.xml"), "rb") as f:
        current = axml.manifest_info(f.read())["package"] or BASE_PACKAGE
    for name, edit in (("AndroidManifest.xml", axml.set_package), ("resources.arsc", axml.set_table_package)):
        path = os.path.join(src, name)
        with open(path, "rb") as f:
            data = f.read()
        for old in dict.fromkeys((current, BASE_PACKAGE)):
            try:
                data = edit(data, old, package)
                break
            except ValueError:
                if old == BASE_PACKAGE:
                    raise
        with open(path, "wb") as f:
            f.write(data)


def patch_label(path, host):
    """The name on the phone, in the manifest (which stays compiled: apktool -r). Returns the name."""
    label = app_label(host)
    log(f"naming   {label}")
    with open(path, "rb") as f:
        data = f.read()
    with open(path, "wb") as f:
        f.write(axml.set_application_label(data, label))
    return label


def patch_target(path):
    """The Android version the app says it was made for. Android 14 and later show every app made for one older than 9
    (API 28) a notice at its start, "this app was made for an older version of Android", and the game was made for 8.1.
    28 is the lowest that does not, and asks the least of the game: from 28 on Android refuses plain HTTP unless it is
    allowed, which is how the game reaches this server, and takes the Apache HTTP classes the game's SDK uses off the
    default class path unless the manifest asks for them. The game has a network security config, which decides for the
    app when there is one, so plain HTTP is allowed in that as well as in the manifest."""
    log(f"target   Android API {TARGET_SDK}")
    with open(path, "rb") as f:
        data = f.read()
    data = axml.set_target_sdk(data, TARGET_SDK)
    data = axml.set_application_flags(data, {"usesCleartextTraffic": (ATTR_CLEARTEXT, True)})
    data = axml.add_optional_library(data, "org.apache.http.legacy")
    with open(path, "wb") as f:
        f.write(data)
    config = os.path.join(os.path.dirname(path), "res", "xml", "network_security_config.xml")
    if os.path.isfile(config):
        with open(config, "rb") as f:
            data = f.read()
        with open(config, "wb") as f:
            f.write(axml.set_plain_flag(data, "base-config", "cleartextTrafficPermitted"))


def runtime_version():
    """Version of the runtime bundle the next build would add, or None without one."""
    try:
        with open(os.path.join(RUNTIME_DIR, "bundle.json"), encoding="utf-8") as f:
            return json.load(f).get("version") or "unknown"
    except (OSError, ValueError):
        return None


def log(msg):
    """Progress line, flushed so docker shows it immediately."""
    print(msg, flush=True)


def sha256(path):
    """Hex SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        # 1 MiB blocks: APKs are around 90 MB.
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def validate_host(host):
    """Accept "host" or "host:port" (IPv4 address or DNS name); it goes into URLs and smali strings."""
    if not HOST_RE.fullmatch(host or ""):
        raise SystemExit(f"invalid address {host!r}: use an IPv4 address or host name, optionally with :port")
    if len(host) > MAX_HOST_LEN:
        raise SystemExit(f"address {host!r} is {len(host)} characters; at most {MAX_HOST_LEN} are accepted")
    return host


def other_hosts(meta):
    """The hosts a client changed for another server reaches the game at, from its RPC literal: none for the original."""
    hosts = set()
    for i in range(len(meta.entries)):
        m = RPC_LITERAL.fullmatch(meta.literal(i).decode("utf-8", "replace"))
        if m and m.group(2) not in OFFICIAL_RPC_HOSTS:
            hosts.add(m.group(2))
    return sorted(hosts)


def inspect(path):
    """What an APK is, before anything is changed in it: {"kind", "version", "hosts", "known"}.
      kind     "original"      the game's Android client as released, still set to the official servers
               "other server"  the client changed to reach another server (hosts): pointed at this one instead
               "built here"    an app OpenDMTQ built for a server: not a base, the client it was built from is
               "not the game"  another app, or not an APK at all
      version  the client's version ("1.3.4"), or None
      known    True when every code edit fits its code, in one of the versions they were made for (IL2CPP_EDITS)"""
    info = {"kind": "not the game", "version": None, "hosts": [], "known": False}
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "AndroidManifest.xml" in names:
                info["version"] = axml.manifest_info(z.read("AndroidManifest.xml")).get("version")
            # The hook class is in the code of every app this patcher built: tell those apart first, as their RPC
            # literal names a server too.
            if any(z.read(n).find(HOOK_CLASS) >= 0 for n in names if re.fullmatch(r"classes\d*\.dex", n)):
                info["kind"] = "built here"
                return info
            if METADATA not in names:
                return info
            meta = il2cpp.Metadata(z.read(METADATA))
            info["known"] = CODE_FILE in names and len(code_versions(z.read(CODE_FILE))) == len(IL2CPP_EDITS)
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, struct.error, il2cpp.MetadataError):
        return info
    if len(meta.find(MARKER)) == 1:
        info["kind"] = "original"
    else:
        info["hosts"] = other_hosts(meta)
        if info["hosts"]:
            info["kind"] = "other server"
    return info


def is_patchable(path):
    """True when the APK is a client this patcher builds from: the original, or one changed for another server."""
    return inspect(path)["kind"] in ("original", "other server")


def metadata_edits(host):
    """The original client's IL2CPP literals: original -> replacement. Its two RPC addresses (the live one and a second of
    the same form), whose HTTPS becomes HTTP, and its platform API base and web base (client_marks)."""
    edits = {f"https://{name}/DMQ/rpc": f"http://{host}/DMQ/rpc" for name in OFFICIAL_RPC_HOSTS}
    edits.update({old: new.replace("{host}", host) for old, new in client_marks.ADDRESSES.items()})
    return edits


def host_pattern(name):
    """An address on the host `name` (with or without "http://" or "https://", with any port), and the path after it."""
    return re.compile(rf"(https?://)?{re.escape(name.split(':')[0])}(?::\d+)?(/.*)?")


def address_edits(meta, host):
    """The literals to rewrite in this client: every RPC address it has, found by its pattern (a scheme, a host, then
    /DMQ/rpc), the official platform addresses it has, and every address on the hosts of the other server it was changed
    for (its game RPC, its API and its web base, as the official ones are)."""
    edits = {}
    for i in range(len(meta.entries)):
        text = meta.literal(i).decode("utf-8", "replace")
        # The game's requests go to this server over plain HTTP, whatever server the client was made or changed for.
        if RPC_LITERAL.fullmatch(text):
            edits[text] = f"http://{host}/DMQ/rpc"
    edits.update({old: new for old, new in metadata_edits(host).items() if meta.find(old)})
    for name in other_hosts(meta):
        pattern = host_pattern(name)
        for i in range(len(meta.entries)):
            text = meta.literal(i).decode("utf-8", "replace")
            m = pattern.fullmatch(text)
            if m:
                edits[text] = f"{'http://' if m.group(1) else ''}{host}{m.group(2) or ''}"
    return edits


# The edits to the engine's own Java code (Unity's player and FMOD's audio device), which load and call the shim, each
# with what it does: (what it does, the file under smali/, the text there, the text it becomes, how many times).
ENGINE_EDITS = [
    # The shim, for phones that run the game's own 32-bit libraries (arm32/shim/shim.cpp): loaded once
    # libunity.so is, and called before each render call and after each mix of FMOD's Java output.
    # Harmless without it: the load only logs, and Hook.ready stays false.
    ("the shim loaded with the game's libraries", "com/unity3d/player/UnityPlayer.smali",
     "invoke-static {}, Lcom/unity3d/player/k;->a()V",
     'invoke-static {}, Lcom/unity3d/player/k;->a()V\n\n    const-string v0, "opendmtq"\n\n'
     "    invoke-static {v0}, Lcom/unity3d/player/UnityPlayer;->loadLibraryStatic(Ljava/lang/String;)Z", 1),
    ("the shim called before each render", "com/unity3d/player/UnityPlayer.smali",
     "invoke-direct {p0}, Lcom/unity3d/player/UnityPlayer;->nativeRender()Z",
     "invoke-static {}, Lcom/opendmtq/Hook;->render()V\n\n    "
     "invoke-direct {p0}, Lcom/unity3d/player/UnityPlayer;->nativeRender()Z", 1),
    ("the shim given each mix of FMOD's sound", "org/fmod/FMODAudioDevice.smali",
     "invoke-direct {p0, v2}, Lorg/fmod/FMODAudioDevice;->fmodProcess(Ljava/nio/ByteBuffer;)I",
     "invoke-direct {p0, v2}, Lorg/fmod/FMODAudioDevice;->fmodProcess(Ljava/nio/ByteBuffer;)I\n\n"
     "    iget-object v2, p0, Lorg/fmod/FMODAudioDevice;->e:Ljava/nio/ByteBuffer;\n\n"
     "    iget-object v3, p0, Lorg/fmod/FMODAudioDevice;->c:Landroid/media/AudioTrack;\n\n"
     "    invoke-static {v2, v3}, Lcom/opendmtq/Hook;->mix(Ljava/nio/ByteBuffer;Landroid/media/AudioTrack;)V", 1),
]


def smali_roles():
    """What each of smali_edits' edits does, in their order: the engine's, then the SDK's (client_marks), whose
    addresses point at this server and take its log uploads and its customer centre's links off the internet, whose
    requests are all built as plain HTTP (the server's HTTPS, for browsers, has a certificate the app would not trust),
    whose sign-in goes straight to the guest login (Google Play Games' cannot succeed for a re-signed app and only put up
    Google's screens at every start before the same guest login), which opens no Play Games screen after OPTION > Google
    Play log out, which leaves the clipboard alone (at every sign-in the game read it for a token an older edition of the
    game left there, took whatever text it found for one and emptied it, and Android 13 and later said so), and which
    asks Google Play for no local prices of the game's paid items at every start (its screen for that turned the display
    for a moment; nothing is sold through this server)."""
    return [edit[0] for edit in ENGINE_EDITS] + [edit[0] for edit in client_marks.SDK_EDITS]


def smali_edits(host):
    """Java edits: (file under smali/, old text, new text, expected count), in smali_roles' order."""
    engine = [(rel, old, new, count) for _, rel, old, new, count in ENGINE_EDITS]
    # The SDK's: what each becomes names this server ({host}).
    sdk = [(rel, old, new.replace("{host}", host), count) for _, _, rel, old, new, count in client_marks.SDK_EDITS]
    return engine + sdk


def arm_branch(at, to, link=False):
    """The ARM instruction bytes of a branch (or branch with link) from one code offset to another."""
    # The processor reads the offset from two instructions ahead, counted in instructions.
    distance = (to - (at + 8)) >> 2
    return ((0xEB if link else 0xEA) << 24 | distance & 0xFFFFFF).to_bytes(4, "little")


# The menu frame rate's edit (IL2CPP_EDITS): the ARM code it runs in the top bar's handler for the button of the
# publisher's other games (hidden on every screen: ASSET_EDITS) from 0x10 on (the shop's edit has the 16 bytes before), up
# to its branch back and its literal. The instruction it took the place of (the rate asked for, r1, kept in r4); the
# pointer to the game's frame rate class through the slot its set-up reads it from; stop if the class is not set up yet;
# its static fields (at 0x50 in the runtime's class); stop if there are none; the menus' cap (at 0x0c) when that is
# higher.
_KEEP_MENU_RATE = bytes.fromhex(
    "0140a0e1 2c009fe5 00008fe0 000090e5 000090e5 000050e3 0500000a 500090e5 000050e3 0200000a"
    "0c0090e5 000054e1 0040a0b1")


def _menu_rate(room, back, slot):
    """That code at room (the other games' handler + 0x10), its branch back to back (the frame rate's setter + 0x10), and
    the distance from its add (room + 8, which reads the program counter 8 ahead) to slot, the class's place in the GOT."""
    return _KEEP_MENU_RATE + arm_branch(room + 0x34, back) + ((slot - (room + 8 + 8)) & 0xFFFFFFFF).to_bytes(4, "little")


# The music list's page edit (IL2CPP_EDITS): the end of the music list's rebuild in 1.3.4, from +0x570, where the count
# of the list's pages is back, to the read of its page groups. As the game has it: the groups into r4 (from the method's
# frame, sp + 4); fewer than one page, return; this; the first page; the list's page setter; the GOT's List.get_Item for
# the groups (four instructions); the first group; that method's information; the groups.
_LIST_END = bytes.fromhex(
    "04409de5 010050e3 0f0000ba 0a00a0e1 0010a0e3 390800eb f8009fe5 f8109fe5 00008fe0 000091e7 0010a0e3 002090e5 0400a0e1")
# The same with four words changed. r4 gets the method's closure instead (sp + 0x10), whose field at 8 is the page of the
# song the rebuild looked for and found, 0 when it looked for none or did not find it; the page setter gets that page in
# place of the first; List.get_Item gets the list's current page (at 0x2c of the page, sl), which the page setter has
# just set to that page within the list's pages; and the groups are read from the frame where r4 had them from. Nothing
# else of the method moves.
_LIST_END_KEPT = bytes.fromhex(
    "10409de5 010050e3 0f0000ba 0a00a0e1 081094e5 390800eb f8009fe5 f8109fe5 00008fe0 000091e7 2c109ae5 002090e5 04009de5")
# 1.3.5's own rebuild keeps the page by itself: r4 set to 1 at the end of the part that looks for the song (+0x3a8),
# and its end returns before the page setter's turn to page 0 while r4 is set or there are no pages (+0x574: mov r1, #0;
# cmp r0, #1; movwlt r1, #1; orrs r0, r4, r1; beq to the turn to the first page).
_LIST_FLAG_135 = bytes.fromhex("0140a0e3")
_LIST_END_135 = bytes.fromhex("0010a0e3 010050e3 011000b3 010094e1 0100000a")


# Code edits in the game's libil2cpp.so: (what it does, {client version: [(offset, bytes there now, bytes to write)]}).
# All the parts of an edit apply together, in the first version whose bytes are all there; a client whose bytes differ in
# every version keeps that screen as it was. A client changed for another server has the code of its version: the address
# it was changed to is in the metadata. The offsets of 1.3.5 were found by method name (the metadata's methods, the code
# registration's method pointers and SymbolMap-ARMv7's functions), each edit's functions compared instruction by instruction
# with those of 1.3.4: they are the same but where they reach other code and data, which is all moved, and where noted.
IL2CPP_EDITS = [
    # The main menu opens the server's event page (its web page popup, "NOTICE") at every start, and this server has
    # nothing to announce there. In the main menu's start method the first instruction after the check of the client's
    # sign-in information becomes a branch past the notice popup, to the nickname, how-to-play and start popups that
    # follow; the notice's close callback (the method's first lambda) is empty, and the code after it rewrites every
    # register the skipped part set. 1.3.5: the same check and popup further on in a longer start method (+0x898, to
    # +0xa78). Its close callback is the third lambda there, empty too; the first two are new and hold FREE PASS's clock
    # while the popup track runs, set on the track itself.
    ("main menu skips the NOTICE popup", {
        "1.3.4": [(0xEF40F0, bytes.fromhex("0010a0e3" "ac61f9eb"), arm_branch(0xEF40F0, 0xEF42D0) + bytes.fromhex("ac61f9eb"))],
        "1.3.5": [(0xF39D24, bytes.fromhex("0010a0e3" "815ef9eb"), arm_branch(0xF39D24, 0xF39F04) + bytes.fromhex("815ef9eb"))],
    }),
    # A new install fetches about 42 MB of client data from this server, and the game first asks "Additional files will
    # be downloaded" with one button, OK. The login screen's method that shows that popup keeps its first part, which
    # saves the callback in the small object behind the popup's button, and then calls that button's own handler (a
    # lambda of that object, which only answers true and does not look at which button) instead of building the popup.
    ("the game's data download starts without asking", {
        "1.3.4": [(0xCF9250, bytes.fromhex("0500a0e1" "e98f0ceb" "0500a0e1"),
                   bytes.fromhex("0800a0e1") + arm_branch(0xCF9254, 0xCFD45C, link=True) + arm_branch(0xCF9258, 0xCF9618))],
        "1.3.5": [(0xCD9E50, bytes.fromhex("0500a0e1" "8a270eeb" "0500a0e1"),
                   bytes.fromhex("0800a0e1") + arm_branch(0xCD9E54, 0xCDDF90, link=True) + arm_branch(0xCD9E58, 0xCDA218))],
    }),
    # The shop's Q tab sells only for real money through Google Play, which reaches nothing here (its tab is hidden in
    # ASSET_EDITS), and the + by the points opens the shop on that tab. The shop's tab setter turns Q into MAX in four
    # instructions kept in the room left by the top bar's handler for the publisher's other games, a handler whose
    # button is hidden too: compare, swap, the first instruction it replaced, and back. (The tabs are numbered alike in
    # both versions: Q 0, MAX 1.)
    ("the shop opens on its MAX tab instead of the real-money one", {
        "1.3.4": [(0xD2F4B4, bytes.fromhex("f0482de9"), arm_branch(0xD2F4B4, 0x9D735C)),
                  (0x9D735C, bytes.fromhex("f04d2de9" "18b08de2" "0080a0e1" "a0039fe5"),
                   bytes.fromhex("000051e3" "0110a003" "f0482de9") + arm_branch(0x9D7368, 0xD2F4B8))],
        "1.3.5": [(0xC2C5EC, bytes.fromhex("f0482de9"), arm_branch(0xC2C5EC, 0xB4BF90)),
                  (0xB4BF90, bytes.fromhex("f04d2de9" "18b08de2" "0080a0e1" "a0039fe5"),
                   bytes.fromhex("000051e3" "0110a003" "f0482de9") + arm_branch(0xB4BF9C, 0xC2C5F0))],
    }),
    # At every start the game turned its low resolution option on for good (its start-up writes the option's saved
    # field, whatever was saved, just before the low resolution's apply reads it), so that on every phone it drew at two
    # thirds of the panel's height: 960 lines on a 1440 line panel, 720 on 1080. Written off, Apply takes the device's own
    # resolution. A device that then does not keep its frame rate goes back to the low one by itself (arm32/README.md, Resolution),
    # so the option's row is gone from the screen (ASSET_EDITS). Each part ends in the write itself (strb at 0x1a).
    # 1.3.5 writes it as the negation of its check for an iPhone's notch, which on Android always answers false (its
    # whole code: mov r0, #0; bx lr), so the option is on there too: the negation becomes a zero.
    ("the panel's own resolution", {
        "1.3.4": [(0x9C385C, bytes.fromhex("0110a0e3" "0040a0e3" "1a10c0e5"), bytes.fromhex("0010a0e3" "0040a0e3" "1a10c0e5"))],
        "1.3.5": [(0xB38A04, bytes.fromhex("010020e2" "1a00c5e5"), bytes.fromhex("0000a0e3" "1a00c5e5"))],
    }),
    # A menu left untouched drops step by step to 18 frames a second (the frame rate class's own adjustment, to save
    # battery on the phones of its day) and jumps back at the next touch, which shows. The frame rate's setter now never
    # goes below the game's cap for menus: 60 on a phone running the game's own libraries, the app's frame rate under
    # the runtime, so 120 on a 120 Hz phone (a limit of 60 there judders: a timer's frames stay for two refreshes or three,
    # one frame in five measured on a Galaxy S26 Ultra). In the rest of the same dead handler: _KEEP_MENU_RATE.
    # The runtime's fallback to a lower rate lowers that cap too, so this follows it.
    ("a menu left alone keeps its frame rate", {
        "1.3.4": [(0x9AFE60, bytes.fromhex("0140a0e1"), arm_branch(0x9AFE60, 0x9D736C)),
                  (0x9D736C, bytes.fromhex(
                   "a0539fe5 00008fe0 000085e0 2c01d0e5 000050e3"
                   "0800001a 8c039fe5 8c139fe5 00608fe0 060091e7"
                   "000090e5 e04a19eb 060085e0 0110a0e3 2c11c0e5"), _menu_rate(0x9D736C, 0x9AFE64, 0x1452058))],
        "1.3.5": [(0x1047700, bytes.fromhex("0140a0e1"), arm_branch(0x1047700, 0xB4BFA0)),
                  (0xB4BFA0, bytes.fromhex(
                   "a0539fe5 00008fe0 000085e0 5201d0e5 000050e3"
                   "0800001a 8c039fe5 8c139fe5 00608fe0 060091e7"
                   "000090e5 749214eb 060085e0 0110a0e3 5211c0e5"), _menu_rate(0xB4BFA0, 0x1047704, 0x1461F70))],
    }),
    # Songs downloaded from the music list (ticked, then DOWNLOAD; or a song's own download) left the list at its first
    # page, wherever the player was. At the download's end the game remembers the first song of the page the player is
    # at and builds the list again from what is on the device (the music list's rebuild): the rebuild finds that song
    # and turns the list to its page, then turned it to the first page every time (its page setter with page 0, centred
    # on the first page's group); the list's current page still held the player's page, so that turn moved the
    # list. Its end now goes to the page of the song it found (_LIST_END_KEPT), and to the first page as before when it
    # looked for none: a filter or a sort still opens the list at its start. 1.3.5 keeps the page in its own code: its
    # part only reads that code and writes it back as it is.
    ("the music list stays at its page after a download", {
        "1.3.4": [(0xD290D4, _LIST_END, _LIST_END_KEPT)],
        "1.3.5": [(0xC2612C, _LIST_FLAG_135, _LIST_FLAG_135), (0xC262F8, _LIST_END_135, _LIST_END_135)],
    }),
]


def code_versions(code):
    """{what: the client version whose bytes are all there} for each code edit that fits this libil2cpp.so."""
    fits = {}
    for what, versions in IL2CPP_EDITS:
        for version, parts in versions.items():
            if all(code[offset:offset + len(old)] == old for offset, old, _ in parts):
                fits[what] = version
                break
    return fits


def patch_il2cpp(path):
    """Apply the code edits whose bytes match; report the ones that do not. Returns what was applied (IL2CPP_EDITS' names)."""
    with open(path, "rb") as f:
        code = bytearray(f.read())
    fits = code_versions(code)
    for what, versions in IL2CPP_EDITS:
        if what in fits:
            for offset, _, new in versions[fits[what]]:
                code[offset:offset + len(new)] = new
            log(f"  code      {what} ({fits[what]})")
        else:
            log(f"  code      skipped ({what}): this client's code differs")
    with open(path, "wb") as f:
        f.write(code)
    return set(fits)


# Where the game keeps its screens inside the APK.
ASSET_DIR = "assets/bin/Data"
# The game's project settings (globalgamemanagers, a file with no names in it: the places were found by reading it with the class
# database for Unity 5.6.5, proven by changing the byte and reading the object again, and are checked against the real clients in
# tests/test_real_client.py): the object by its Unity class number and its size, the place in it, what is there, what goes
# there. 1.3.4 and 1.3.5 have both objects at those sizes, the settings at those places in them; the file of 1.3.5 has more
# before its quality settings. Its Android build asked for a 16-bit screen, which bands in every gradient of a jacket and a
# background, and for its lowest quality level at half-size textures.
SETTINGS_FILE = "globalgamemanagers"
CLASS_QUALITY_SETTINGS = 47
CLASS_PLAYER_SETTINGS = 129
SETTING_EDITS = {
    "PlayerSettings.use32BitDisplayBuffer": (CLASS_PLAYER_SETTINGS, 530, 302, 0, 1),
    "QualitySettings[Fastest].textureQuality": (CLASS_QUALITY_SETTINGS, 612, 68, 1, 0),
}

# Screens taken apart for this server (client_marks): the screen's asset file by its name in the APK -> its edits, each
# a hide, or a move by x and y, of an object by its path in the scene ("if there": only in a client that has it). Each
# entry leads nowhere here: what it did depended on the publisher's services, and what remains closes up around the gap.
#   every screen with a top bar: the button that lists the publisher's other games (it asks a server that no longer
#     exists and answers "Network connection error");
#   the lobby: PLAY FOR FREE (ad-paid songs from an ad network; every song is free here, and the page is empty; client
#     1.3.5 has a second button of its own for it and turns one of the two on as the lobby opens: both also go off the
#     screen, to the left), MUSIC SHOP (songs for sale; none are, so it is an empty page with a Purchase button), PACKAGE
#     (bundles for real money through Google Play) and QUEST (the server has a fixed answer from 2017, so nothing ever
#     progresses or pays out); the divider and HOW TO PLAY close up under MUSIC LIST;
#   the menu: the publisher's Instagram, Facebook and Twitter pages and the line that advertises them, and MESSAGE (the
#     mailbox of the publisher's operators; nobody sends anything here); the three entries left, centred;
#   the options: the account's row (it asks to write to the publisher's customer centre), the Google Play game account's
#     Log out (the game never signs in to Google Play here), CONTACT US (the publisher's customer centre), and the low
#     resolution graphics (the game wrote it on at every start, whatever was picked here; it is decided by itself now);
#   the shop: its Q tab (real money through Google Play, see IL2CPP_EDITS); the other three, which take the points every
#     player has, close up.
ASSET_EDITS = client_marks.SCREEN_EDITS


# Screen edits that go with a code edit (path prefix -> the code edit's name): a client the code edit does not fit keeps
# those parts of the screen as they were. The shop's Q tab is hidden only when the shop no longer opens on it.
ASSET_NEEDS = client_marks.SCREEN_NEEDS


def setting_places(data):
    """{name: (place in the file, what goes there)} for each setting edit whose object is there once, at its size, with the
    byte expected in it."""
    try:
        objects = unity_assets.SerializedFile(data).objects
    except (unity_assets.AssetError, struct.error):
        return {}
    places = {}
    for name, (class_id, size, at, old, new) in SETTING_EDITS.items():
        found = [offset for _, offset, length, kind in objects if kind == class_id and length == size]
        if len(found) == 1 and data[found[0] + at] == old:
            places[name] = (found[0] + at, new)
    return places


def patch_settings(root):
    """Make the edits to the game's project settings; a client whose settings differ keeps them."""
    path = os.path.join(root, ASSET_DIR, SETTINGS_FILE)
    with open(path, "rb") as f:
        data = bytearray(f.read())
    places = setting_places(bytes(data))
    for name in SETTING_EDITS:
        if name not in places:
            log(f"  settings  skipped ({name}): this client's settings differ")
            continue
        place, new = places[name]
        data[place] = new
        log(f"  settings  {name} = {new}")
    with open(path, "wb") as f:
        f.write(data)


def patch_assets(root, code=None):
    """Make the edits to the game's screens; a client whose screens differ keeps those screens. code: the code edits that
    were applied (patch_il2cpp); a screen edit that goes with one that was not is left out (ASSET_NEEDS)."""
    for name, edits in ASSET_EDITS.items():
        if code is not None:
            kept = [e for e in edits if all(not e[1].startswith(at) or need in code for at, need in ASSET_NEEDS.items())]
            if len(kept) < len(edits):
                gone = len(edits) - len(kept)
                # The words for one when one is left out.
                log(f"  screens   {name}: {gone} {'edit' if gone == 1 else 'edits'} left out, with the code edit "
                    f"{'it goes' if gone == 1 else 'they go'} with")
            edits = kept
        if not edits:
            continue
        path = os.path.join(root, ASSET_DIR, name)
        try:
            with open(path, "rb") as f:
                data = unity_assets.apply(f.read(), edits)
        except (OSError, unity_assets.AssetError) as e:
            log(f"  screens   skipped {name}: {e}")
            continue
        with open(path, "wb") as f:
            f.write(data)
        log(f"  screens   {name}: {len(edits)} {'edit' if len(edits) == 1 else 'edits'}")


# ---- the game's words

# The game's words for its screens are tables among the app's own files (.csv), a row for each string: its key, its words
# in each language the game speaks (columns named text_ and two capitals), then a note. Two of the tips its loading
# screens show say that MAX Point comes from quests as well, in four of its five languages; this server has no quests.
# Their words become those of a tip of their kind that says where MAX Point comes from with no quest in it, in each
# language: the game's own words (it shows some tips more than once anyway). Found by their words, never their keys: a
# word for quests in any language beside MAX Point. A tip's kind is its key without the number at its end. The rows stay,
# so that a tip the game picks by its number still has words; a table that is not of this form is left as it is.
WORDS_COLUMN = re.compile(r"text_[A-Z]{2}")
# Quests in the game's languages: Korean, Japanese, English (the word alone: a request is none), Chinese in its simplified
# and its traditional script.
QUEST_WORDS = re.compile(r"퀘스트|クエスト|\bquests?\b|任务|任務", re.I)
MAX_POINT = re.compile(r"max\s*points?", re.I)


def _csv_line(row):
    """One row of a table as the game's tables write it: its fields apart by commas, quoted only where they must be."""
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerow(row)
    return out.getvalue()[:-1]


def quest_free_words(text):
    """A table of the game's words with each tip that sends a player to quests for MAX Point given the words of a tip of
    its kind that says where MAX Point comes from without them: (the table, how many rows changed). The same text and 0
    for a table of another form, or with no such tip, or with none to take words from."""
    # Its lines as they end (the game's own end in a carriage return and a line feed), each a row.
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(eol)
    # A field that holds a line break is not of this form (the table is read a line at a time here).
    if any(line.count('"') % 2 for line in lines):
        return text, 0
    rows = [next(csv.reader([line])) if line else [] for line in lines]
    # The columns of words, by their names in its first row: none, and it is a table of another kind (a song list).
    header = rows[0] if rows else []
    words = [i for i, name in enumerate(header) if WORDS_COLUMN.fullmatch(name)]
    if not words:
        return text, 0

    def full(row):
        # A row of the table's own width, its key ending in a number (a numbered string: one of a kind).
        return len(row) == len(header) and re.search(r"\d$", row[0]) is not None

    def kind(row):
        # The key without its number: the tips of a screen share it.
        return re.sub(r"\d+$", "", row[0])

    def quests(row):
        # A word for quests in any of its languages.
        return any(QUEST_WORDS.search(row[i]) for i in words)

    def max_point(row):
        # MAX Point named in any of its languages (the game writes it in Latin letters in all of them).
        return any(MAX_POINT.search(row[i]) for i in words)

    changed = 0
    for n, row in enumerate(rows):
        # A numbered string that sends a player to quests for MAX Point.
        if n == 0 or not full(row) or not (quests(row) and max_point(row)):
            continue
        # The first tip of the same kind that speaks of MAX Point and of no quest, written in the table as this form
        # writes it (so that the line made from it reads as the game's own).
        source = next((r for m, r in enumerate(rows) if m and full(r) and kind(r) == kind(row) and max_point(r) and not quests(r)
                       and _csv_line(r) == lines[m]), None)
        if source is None:
            continue
        # Its key and its note stay; its words, in every language, are the other tip's.
        lines[n] = _csv_line([source[i] if i in words else value for i, value in enumerate(row)])
        changed += 1
    return eol.join(lines), changed


def patch_words(root):
    """Make the edits to the game's words (quest_free_words) in each of its tables among the app's files; a table that
    differs stays as it is."""
    # Every table among the app's files: those of other kinds come back unchanged.
    for path in sorted(glob.glob(os.path.join(root, "assets", "**", "*.csv"), recursive=True)):
        with open(path, "rb") as f:
            raw = f.read()
        # UTF-8, with a byte order mark before it or not; a table in another encoding is no table of the game's words.
        bom = raw.startswith(b"\xef\xbb\xbf")
        try:
            text = raw[3 if bom else 0:].decode("utf-8")
        except UnicodeDecodeError:
            continue
        new, changed = quest_free_words(text)
        if not changed:
            continue
        # Written as it was: its byte order mark, its line ends, every other line as it stood.
        with open(path, "wb") as f:
            f.write((b"\xef\xbb\xbf" if bom else b"") + new.encode("utf-8"))
        log(f"  words     {changed} {'tip' if changed == 1 else 'tips'} of the loading screens that sent players to quests "
            f"say where MAX Point comes from")


def patch_metadata(path, host):
    """Rewrite the IL2CPP literals (in place when they fit, appended when longer). Returns the hosts of the other server
    the client was changed for, if it was: the SDK's addresses name them too (redirect_smali)."""
    with open(path, "rb") as f:
        meta = il2cpp.Metadata(f.read())
    hosts = other_hosts(meta)
    for old, new in address_edits(meta, host).items():
        n = meta.replace_all(old, new)
        log(f"  metadata  {old}  ->  {new}" + (f"  ({n}x)" if n > 1 else ""))
    with open(path, "wb") as f:
        f.write(meta.tobytes())
    return hosts


# The Java end of the shim (arm32/shim/shim.cpp). Without the shim "ready" stays false, so the game's calls
# here are one field read each.
HOOK_SMALI = """.class public final Lcom/opendmtq/Hook;
.super Ljava/lang/Object;

.field public static ready:Z

.method public static final mix(Ljava/nio/ByteBuffer;Landroid/media/AudioTrack;)V
    .registers 3
    sget-boolean v0, Lcom/opendmtq/Hook;->ready:Z
    if-eqz v0, :end
    invoke-virtual {p1}, Landroid/media/AudioTrack;->getSampleRate()I
    move-result v0
    invoke-static {p0, v0}, Lcom/opendmtq/Hook;->onMix(Ljava/nio/ByteBuffer;I)V
    :end
    return-void
.end method

.method private static final native onMix(Ljava/nio/ByteBuffer;I)V
.end method

.method private static final native onRender()V
.end method

.method public static final render()V
    .registers 1
    sget-boolean v0, Lcom/opendmtq/Hook;->ready:Z
    if-eqz v0, :end
    invoke-static {}, Lcom/opendmtq/Hook;->onRender()V
    :end
    return-void
.end method
"""


def redirect_smali(root, hosts, host):
    """In a client changed for another server, every string in the SDK's code that is an address on that server's hosts
    now names this server (https becomes http, as in smali_edits). Returns how many strings changed."""
    names = sorted({h.split(":")[0] for h in hosts}, key=len, reverse=True)
    if not names:
        return 0
    # A string that starts with the address: "host", "host/api", "http://host/www", with any port.
    pattern = re.compile(r'"(https?://)?(?:' + "|".join(re.escape(n) for n in names) + r')(?::\d+)?(?=[/"])')
    changed = 0
    for d, _, files in os.walk(root):
        # Only the code: smali, smali_classes2 and so on.
        if not os.path.relpath(d, root).split(os.sep)[0].startswith("smali"):
            continue
        for f in files:
            if not f.endswith(".smali"):
                continue
            path = os.path.join(d, f)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            if not any(n in text for n in names):
                continue
            new, n = pattern.subn(lambda m: f'"{"http://" if m.group(1) else ""}{host}', text)
            if n:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new)
                # Said by what it is, not by the file: the SDK's files are named after its code.
                log(f"  smali     {n}x address of the other server in the SDK's code")
                changed += n
    return changed


def patch_smali(root, host):
    """Apply the SDK edits; every edit must match exactly its expected number of times, or be there already (a client
    changed for another server often has the same changes made by hand)."""
    hook = os.path.join(root, "smali", "com", "opendmtq", "Hook.smali")
    os.makedirs(os.path.dirname(hook), exist_ok=True)
    with open(hook, "w", encoding="utf-8") as f:
        f.write(HOOK_SMALI)
    for (rel, old, new, expected), role in zip(smali_edits(host), smali_roles()):
        path = os.path.join(root, "smali", rel)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            # Each edit is said by what it does: the files and the text are the client's own names (client_marks).
            raise SystemExit(f"smali: {role}: not in this client; unsupported base APK") from None
        n = text.count(old)
        if n == 0 and (text.count(new) >= expected if new else True):
            # Made already (by whoever changed the client), or a call to take out that is gone: nothing to do.
            log(f"  smali     {role}: made already")
            continue
        # Any other count means a different client build: stop before producing a half-patched APK.
        if n != expected:
            raise SystemExit(f"smali: {role}: expected {expected} match(es), found {n}; unsupported base APK")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(old, new))
        log(f"  smali     {role}: {n}x")


def signed_builds(out_dir):
    """Manifests in out_dir that record the key their app was signed with."""
    try:
        names = sorted(os.listdir(out_dir))
    except OSError:
        return []
    found = []
    for name in names:
        # Builds named in lower case since 0.11.0, and as before ("OpenDMTQ-"): one prefix, whatever its case.
        if name != "latest.json" and not (name.lower().startswith("opendmtq-") and name.endswith(".apk.json")):
            continue
        try:
            with open(os.path.join(out_dir, name), encoding="utf-8") as f:
                if json.load(f).get("key_sha256"):
                    found.append(name)
        except (OSError, ValueError, AttributeError):
            continue
    return found


def ensure_keystore(ks_dir):
    """Create the signing key once and reuse it, so later builds install over earlier ones.

    A key is only created for a server whose apps were never signed: phones install an update only
    when it is signed with the key of the app they have.
    """
    ks = os.path.join(ks_dir, "opendmtq.jks")
    pw_file = os.path.join(ks_dir, "password.txt")
    # Reuse: the same key is the same app to a phone, so a new build installs over it as an update.
    if os.path.exists(ks):
        with open(pw_file, encoding="utf-8") as f:
            return ks, f.read().strip()
    if signed_builds(os.path.join(os.path.dirname(ks_dir), "out")):
        raise SystemExit(
            "the signing key data/apk/keystore/opendmtq.jks is missing, but the apps in data/apk/out were "
            "signed with it, and phones only install an update signed with the same key. Put it back from a "
            "backup: ./opendmtq restore <backup> --with-key. If it is lost for good, delete the .json files in "
            "data/apk/out to build with a new key: that app has a package of its own, so phones install it next "
            "to the old one and can remove the old one afterwards.")
    os.makedirs(ks_dir, exist_ok=True)
    # Random per-install password; data/ is never committed.
    password = secrets.token_urlsafe(18)
    with open(pw_file, "w", encoding="utf-8") as f:
        f.write(password + "\n")
    os.chmod(pw_file, 0o600)
    # Long-lived RSA key. keytool reads the password from the environment (":env"), not from its
    # command line: a failed run's error, which the builder records in build.json and the admin pages
    # show, and the process list would otherwise carry it.
    subprocess.run([KEYTOOL, "-genkeypair", "-keystore", ks, "-alias", "opendmtq",
                    "-keyalg", "RSA", "-keysize", "2048", "-validity", "36500",
                    "-storepass:env", "OPENDMTQ_KEY_PASSWORD", "-keypass:env", "OPENDMTQ_KEY_PASSWORD",
                    "-dname", "CN=OpenDMTQ local build"], check=True, stdout=subprocess.DEVNULL,
                   env={**os.environ, "OPENDMTQ_KEY_PASSWORD": password})
    # The key file is as private as its password.
    os.chmod(ks, 0o600)
    log("  created signing key data/apk/keystore/opendmtq.jks (back it up with the database)")
    return ks, password


def keystore_sha256():
    """Fingerprint of the signing key file, or None before the first build."""
    ks = os.path.join(APK_DIR, "keystore", "opendmtq.jks")
    return sha256(ks) if os.path.isfile(ks) else None


def describe(info):
    """What inspect() found, in a few words for a log line or a page: "client 1.3.4, original"."""
    what = f"client {info['version']}" if info.get("version") else "client"
    return {
        "original": f"{what}, original",
        "other server": f"{what}, changed for another server ({', '.join(info['hosts'])}): pointed at this one instead",
        "built here": "an app OpenDMTQ built for a server: the client it was built from is needed",
        "not the game": "not the game's Android client",
    }[info["kind"]]


def last_base(base_dir):
    """The SHA-256 of the client the portal's app was built from, or None (no build yet)."""
    try:
        with open(os.path.join(os.path.dirname(os.path.normpath(base_dir)), "out", "latest.json"), encoding="utf-8") as f:
            return json.load(f).get("base_sha256")
    except (OSError, ValueError, AttributeError):
        return None


def clients(base_dir):
    """Every APK in base_dir and what it is: {path: inspect()} (no folder yet: none)."""
    names = os.listdir(base_dir) if os.path.isdir(base_dir) else []
    return {os.path.join(base_dir, f): inspect(os.path.join(base_dir, f)) for f in sorted(names) if f.lower().endswith(".apk")}


def choose(base_dir, infos):
    """The client to build from among infos ({path: inspect()}): (path, True when the last app was built from it), or
    (None, False) when none is a client this patcher builds from."""
    found = sorted(f for f, info in infos.items() if info["kind"] in ("original", "other server"))
    # The same file saved twice ("name (1).apk") is one client.
    distinct = {}
    for f in found:
        distinct.setdefault(sha256(f), f)
    if len(distinct) <= 1:
        return next(iter(distinct.values()), None), False
    # Different clients. The one the phones' app was built from, while it is there: an app from another version could
    # not be installed over it (a lower version number) and changes what the players have. Before the first build: the
    # game's newest version, then the original before a client changed for another server, then one every code edit fits,
    # then the last imported (the import writes each copy anew).
    last = distinct.get(last_base(base_dir))
    if last:
        return last, True
    return max(distinct.values(), key=lambda f: (version_key(infos[f]["version"]), infos[f]["kind"] == "original",
                                                  infos[f]["known"], os.path.getmtime(f))), False


def version_key(version):
    """A client's version ("1.3.5") as numbers that sort as versions do; () when it has none."""
    return tuple(int(part) for part in re.findall(r"\d+", version or ""))


def find_base(base_dir, name=None):
    """The base APK: the named one, or the client in data/apk/base to build from (choose())."""
    if name:
        path = name if os.path.isabs(name) else os.path.join(base_dir, name)
        if not os.path.isfile(path):
            there = sorted(f for f in os.listdir(base_dir) if f.lower().endswith(".apk")) if os.path.isdir(base_dir) else []
            raise SystemExit(f"{name}: no such file in data/apk/base (BASE_APK in .env, or baseApk in the Helm values?); "
                             f"there: {', '.join(there) or 'nothing'}")
        info = inspect(path)
        if info["kind"] not in ("original", "other server"):
            raise SystemExit(f"{path}: {describe(info)}")
        return path
    infos = clients(base_dir)
    best, was_last = choose(base_dir, infos)
    if best is None:
        # The text also reaches the admin pages (build.json), so it is plain: no Markdown quotes.
        if infos:
            # APKs there, but none usable: the import skips such files too, so another copy is needed, not another
            # import of these.
            why = "; ".join(f"{os.path.basename(f)}: {describe(info)}" for f, info in infos.items())
            raise SystemExit(f"data/apk/base holds no game client to build from ({why}); "
                             f"import the game's Android app with {CLI} import <folder>")
        # Named as this install runs it: OpenDMTQ.exe import in the Windows bundle's window, ./opendmtq import elsewhere.
        raise SystemExit(f"no base APK in data/apk/base; run {CLI} import <folder> first")
    usable = {sha256(f): f for f, info in infos.items() if info["kind"] in ("original", "other server")}
    if len(usable) > 1:
        print(f"data/apk/base holds different clients ({', '.join(os.path.basename(f) for f in sorted(usable.values()))}); "
              f"using {os.path.basename(best)}" + (", which the last app was built from" if was_last else "") +
              ". BASE_APK in .env, or baseApk in the Helm values, chooses another", file=sys.stderr, flush=True)
    return best


def prune_builds(out_dir, keep=10):
    """Keep the newest `keep` builds, and always the one latest.json offers: a build for another
    address (--keep-latest) must not delete the portal's download."""
    try:
        with open(os.path.join(out_dir, "latest.json"), encoding="utf-8") as f:
            offered = json.load(f).get("file")
    except (OSError, ValueError, AttributeError):
        offered = None
    # Builds named in lower case since 0.11.0, and as before ("OpenDMTQ-"): the older ones go first all the same.
    builds = sorted((f for f in os.listdir(out_dir) if f.lower().startswith("opendmtq-") and f.endswith(".apk")),
                    key=lambda f: os.path.getmtime(os.path.join(out_dir, f)))
    for old in builds[:-keep]:
        if old != offered:
            os.remove(os.path.join(out_dir, old))
            if os.path.exists(os.path.join(out_dir, old + ".json")):
                os.remove(os.path.join(out_dir, old + ".json"))


def app_file_name(host, stamp):
    """The phone app's file name: what it is, its build (the day's stamp), the system, and the server it is for, in lower
    case, an address written in capitals too (a name on the network reads the same either way)."""
    return f"opendmtq-phone-app-{stamp}-android-{re.sub(r'[^A-Za-z0-9.-]', '-', host)}.apk".lower()


def build_lock(out_dir):
    """Hold this while building. The builder, the admin pages and ./opendmtq apk can each start a
    build, and two at once would race for a new signing key and write the same file. An flock on a
    file in data/apk/out holds across containers (they share the host's kernel), and ends with the
    process however it ends. Returns the open lock file, or None where the file system cannot lock
    (some network shares): the build then goes on without it."""
    os.makedirs(out_dir, exist_ok=True)
    lock = open(os.path.join(out_dir, ".build.lock"), "a", encoding="utf-8")
    try:
        try:
            # Free in the usual case; otherwise say why nothing seems to happen, then wait.
            filelock.lock(lock, blocking=False)
        except BlockingIOError:
            log("waiting for another app build to finish")
            filelock.lock(lock)
    except OSError as e:
        log(f"  no build lock here ({e}); building anyway")
        lock.close()
        return None
    return lock


@contextlib.contextmanager
def stop_signals_held():
    """A stop that comes while the app and its manifests take the old ones' places (docker stop's, compose down's or a
    restart's SIGTERM, Ctrl-C's SIGINT) is kept until they all have, then handled as it would have been at once (the
    builder's handler, Python's KeyboardInterrupt, the end of the process): it never comes between them. Python runs
    signal handlers in its main thread only, and only there can they be changed: a build in another thread keeps none."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    came = []
    before = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        handler = signal.getsignal(signum)
        # One set outside Python (None) could not be put back: that signal is left as it is.
        if handler is None:
            continue
        before[signum] = handler
        # Only noted for now.
        signal.signal(signum, lambda number, frame: came.append(number))
    try:
        yield
    finally:
        # The handlers as they were, before any stop that came is handled.
        for signum, handler in before.items():
            signal.signal(signum, handler)
        # Each stop that came, now that the files agree, as it would have been handled then.
        for signum in came:
            handler = before[signum]
            if callable(handler):
                handler(signum, None)
            elif handler == signal.SIG_DFL:
                signal.raise_signal(signum)


def put_in_place(src, dest, manifest, manifests):
    """The new app (src) at dest, and its manifest at each of manifests (the build's own beside it, and latest.json unless
    the build keeps the portal's download), all taking the old ones' places together. A second build on the same day has
    the same name as the app the portal offers, and latest.json describes it to the PC clients, which check the file
    against it, and to the pages. Whatever takes time or room comes first, next to the old files under names nothing
    reads: the app's copy (a hundred MB, on a disk that may be full), its hash and size (filled into manifest), the
    manifests' text. Then three renames, with a stop held back until they are done (stop_signals_held). A phone that is
    downloading the old app keeps reading it, a copy that fails half-way leaves the old app as it was, and no stop leaves
    latest.json describing one app while its file is another. Returns the manifest."""
    # A dot in front: neither the admin pages, the pruning nor the portal take it for a build.
    part = os.path.join(os.path.dirname(dest), "." + os.path.basename(dest) + ".part")
    # What to take away again if the build ends before the renames.
    staged = [part]
    try:
        shutil.copyfile(src, part)
        # What phones and PC clients will check the app against: the bytes that take the old file's place.
        manifest["sha256"] = sha256(part)
        manifest["size"] = os.path.getsize(part)
        for target in manifests:
            staged.append(target + ".tmp")
            with open(target + ".tmp", "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
        # The app first, then its manifests, each swapped in whole so that readers never see half a file.
        with stop_signals_held():
            os.replace(part, dest)
            for target in manifests:
                os.replace(target + ".tmp", target)
    except BaseException:
        # Nothing half-made stays behind (a hundred MB on a disk that may be full); what took its place stays.
        for path in staged:
            try:
                os.remove(path)
            except OSError:
                pass
        raise
    return manifest


def main(argv=None):
    """Build the app; returns the file name in data/apk/out."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default=os.environ.get("PUBLIC_HOST"), help="server LAN address")
    ap.add_argument("--base", help="base APK in data/apk/base (default: the only one there)")
    # Date for the file name, from the host's clock and zone.
    ap.add_argument("--stamp", default=datetime.date.today().strftime("%Y.%m.%d"))
    # A build for another address (a friend's LAN, a test) must not replace the app the portal offers.
    ap.add_argument("--keep-latest", action="store_true", help="do not make this the portal's download")
    args = ap.parse_args(argv)
    host = validate_host(args.host)
    out_dir = os.path.join(APK_DIR, "out")
    # One build at a time, from the signing key to the manifests (see build_lock).
    lock = build_lock(out_dir)
    try:
        return build(args, host, out_dir)
    finally:
        # Closing the file releases the lock.
        if lock is not None:
            lock.close()


def build(args, host, out_dir):
    """The build itself, under the build lock; returns the file name in out_dir."""
    base = find_base(os.path.join(APK_DIR, "base"), args.base)
    client = inspect(base)
    log(f"base     {os.path.basename(base)} ({describe(client)})")
    log(f"server   http://{host}/")
    # The key first: a build that could not be signed with the phones' key stops before any work.
    ks, password = ensure_keystore(os.path.join(APK_DIR, "keystore"))

    # Fresh scratch space; decode code to smali, keep resources untouched (-r).
    shutil.rmtree(WORK, ignore_errors=True)
    try:
        src = os.path.join(WORK, "src")
        subprocess.run([JAVA, "-jar", APKTOOL, "d", "-q", "-f", "-r", "-o", src, base], check=True)

        log("patching")
        hosts = patch_metadata(os.path.join(src, METADATA), host)
        # A client changed for another server: its SDK names that server's hosts where the original names the official.
        redirect_smali(src, hosts, host)
        patch_smali(src, host)
        code = patch_il2cpp(os.path.join(src, "lib", "armeabi-v7a", "libil2cpp.so"))
        patch_assets(src, code)
        patch_settings(src)
        patch_words(src)
        label = patch_label(os.path.join(src, "AndroidManifest.xml"), host)
        patch_target(os.path.join(src, "AndroidManifest.xml"))
        package = package_id(keystore_sha256())
        patch_package(src, package)

        log("rebuilding and signing")
        unsigned = os.path.join(WORK, "unsigned.apk")
        subprocess.run([JAVA, "-jar", APKTOOL, "b", "-q", "-o", unsigned, src], check=True)
        # Phones that dropped 32-bit apps run the same game through the runtime; the others keep
        # running it natively (see pack_arm64).
        runtime = runtime_version()
        if runtime:
            log(f"adding   arm32 runtime {runtime} for phones without 32-bit support")
            universal = os.path.join(WORK, "universal.apk")
            pack_arm64.pack(unsigned, universal, RUNTIME_DIR, "arm64-v8a", only_64bit=False,
                            tweaks=ARM32_TWEAKS + f"server {host}\n")
            unsigned = universal
        signed_dir = os.path.join(WORK, "signed")
        # v1+v2+v3 so every Android version from 4.0 up accepts it; quiet unless it fails. The key's password reaches
        # the signer through a file only this user can read, not its command line (pack_arm64.run_signer).
        r = pack_arm64.run_signer(unsigned, signed_dir, ks, password)
        if r.returncode != 0:
            sys.stderr.write(r.stdout + r.stderr)
            raise SystemExit("signing failed")
        signed = [f for f in os.listdir(signed_dir) if f.endswith(".apk")]
        if len(signed) != 1:
            raise SystemExit(f"signer produced {signed}")

        # Name says what it is, which build, for which system and which server, in the release's files' order
        # (opendmtq-phone-app-2026.11.17-android-192.168.1.10-8791.apk). ":" (a port) is not allowed in file names on
        # Windows and confuses Android's downloads.
        name = app_file_name(host, args.stamp)
        os.makedirs(out_dir, exist_ok=True)
        dest = os.path.join(out_dir, name)
        # Manifest the CLI and the web portal read: which file to offer and which host it targets. Its hash and size are
        # the copy's that takes the old file's place (put_in_place).
        manifest = {
            "file": name, "host": host, "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "sha256": None, "size": None,
            "base": os.path.basename(base), "base_sha256": sha256(base), "base_version": client["version"],
            "base_kind": client["kind"], "patcher": VERSION,
            "key_sha256": keystore_sha256(), "runtime": runtime, "label": label, "package": package,
        }
        # Each build keeps its own manifest (the admin page lists them); latest.json is the portal's.
        targets = [dest + ".json"] + ([] if args.keep_latest else [os.path.join(out_dir, "latest.json")])
        # The app and its manifests in their places together: the same name may be the app the portal offers right now.
        put_in_place(os.path.join(signed_dir, signed[0]), dest, manifest, targets)
    finally:
        # Hundreds of MB, in the admin service's RAM-backed /tmp: never left behind.
        shutil.rmtree(WORK, ignore_errors=True)

    # Keep the newest ten builds (and never the one the portal offers).
    prune_builds(out_dir)

    # QR for the phone: the portal's download link. And the app's own launcher icon, for the download page's last step.
    if not args.keep_latest:
        qr.write(f"http://{host}/apk", os.path.join(out_dir, "download-qr.svg"))
        write_icon(dest, os.path.join(out_dir, "app-icon.png"))
    log(f"done     data/apk/out/{name}")
    return name


def write_icon(apk, target):
    """The app's launcher icon, the largest of its sizes, next to it as a PNG; nothing when the app has none by that name.
    Swapped in whole, as the portal may be reading the old one."""
    try:
        with zipfile.ZipFile(apk) as z:
            icons = [i for i in z.infolist() if re.fullmatch(r"res/(?:drawable|mipmap)[^/]*/app_icon\.png", i.filename)]
            if not icons:
                return False
            data = z.read(max(icons, key=lambda i: i.file_size).filename)
    except (OSError, zipfile.BadZipFile, KeyError):
        return False
    with open(target + ".tmp", "wb") as f:
        f.write(data)
    os.replace(target + ".tmp", target)
    return True


if __name__ == "__main__":
    main()
