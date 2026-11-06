"""Point a DJMAX Technika Q 1.3.x Android client at an OpenDMTQ server over plain HTTP.

The client reaches its backend through two layers:
  * Unity IL2CPP string literals in global-metadata.dat: the game RPC and the platform API.
  * The Java "pmangplus" SDK in classes.dex: login and platform calls, some forced to HTTPS.

Both are rewritten to http://HOST. The game keeps to plain HTTP: it would not trust the certificate
of the server's own authority (the HTTPS on the same port is for browsers). The manifest allows
cleartext HTTP, so the phone needs no hosts app, proxy or certificate.
Besides the addresses, a few edits to the SDK, the game code and the game's screens take out what is of
no use on this server (smali_edits, IL2CPP_EDITS, ASSET_EDITS).

Usage (inside the tools container): python3 -m opendmtq_tools.patch_apk --host 192.168.0.10 [--base FILE]
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import secrets
import shutil
import struct
import subprocess
import sys
import zipfile

from . import axml, filelock, il2cpp, pack_arm64, qr, unity_assets

# Tool version stamped into the manifest, so a portal can tell which patcher made an APK.
VERSION = "1.10.0"
# data/apk: base/ in, out/ and keystore/ written. The image mounts it at /apk; a host install names it.
APK_DIR = os.environ.get("OPENDMTQ_APK", "/apk")
# Pinned tools: baked into the image, fetched into .host/ by a host install (host/install.sh).
APKTOOL = os.environ.get("OPENDMTQ_APKTOOL") or "/opt/apktool.jar"
SIGNER = pack_arm64.SIGNER
# Java and its keytool: on the PATH in the image, the bundle's own on Windows.
JAVA = pack_arm64.JAVA
KEYTOOL = os.environ.get("OPENDMTQ_KEYTOOL") or "keytool"
# IL2CPP metadata inside the APK.
METADATA = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
# The literal every original client contains; also how base APKs are recognised.
MARKER = "https://dmqglb.mb.pmang.com/DMQ/rpc"
# The game's RPC, the same path on every server: how a client changed for another server is recognised, whatever host it
# was given there. The original's two hosts for it are not another server.
RPC_LITERAL = re.compile(r"(https?://)([^/\s]+)/DMQ/rpc")
OFFICIAL_RPC_HOSTS = ("dmqglb.mb.pmang.com", "dmqglb-dq.mb.pmang.com")
# The class this patcher adds to the app (HOOK_SMALI): an app it built has it.
HOOK_CLASS = b"Lcom/opendmtq/Hook;"
# The client the code edits were made for (IL2CPP_EDITS: their offsets), by the CRC of its libil2cpp.so in the APK's
# zip directory. A client changed only in its addresses has the same code.
KNOWN_CODE = ("lib/armeabi-v7a/libil2cpp.so", 0xCE992EA5)
# Longest address accepted ("host" or "host:port"); long literals are appended, see il2cpp.py.
MAX_HOST_LEN = 80
# IPv4 address or DNS name, optionally with a port.
HOST_RE = re.compile(r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*(?::[0-9]{1,5})?")
# The original game's package name.
BASE_PACKAGE = "com.neowizinternet.game.technikaq_g_a"
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


# The game caps its frame rate in VariableFrameController: maxFpsVal while playing,
# maxOutgameFpsVal in the menus (the step down when they sit idle is taken out: see IL2CPP_EDITS). Both are
# 60 in its static constructor; the runtime sets them to the frame rate it runs at ("fps",
# debug.arm32.framerate), which its window also asks the display for. Only NGUI reads
# Time.frameCount, to update once per frame; the game logic times itself with Time and the audio.
# The build adds a line "server <address>": where the runtime's live view asks and sends (see
# arm32/src/live.cpp).
ARM32_TWEAKS = """# arm32 runtime tweaks: <assembly> <namespace or -> <class> <field> <value or fps>
Assembly-CSharp - VariableFrameController maxFpsVal fps
Assembly-CSharp - VariableFrameController maxOutgameFpsVal fps
"""


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
      known    True for the client the code edits were made for (KNOWN_CODE)"""
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
            code, crc = KNOWN_CODE
            info["known"] = code in names and z.getinfo(code).CRC == crc
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
    """IL2CPP literals: original -> replacement."""
    return {
        # Game RPC endpoint, live and the -dq variant; HTTPS becomes HTTP.
        "https://dmqglb.mb.pmang.com/DMQ/rpc": f"http://{host}/DMQ/rpc",
        "https://dmqglb-dq.mb.pmang.com/DMQ/rpc": f"http://{host}/DMQ/rpc",
        # Platform API base used by the Unity side.
        "http://www.neonapi.com/api": f"http://{host}/api",
        # Platform web base.
        "http://pmangplus.com": f"http://{host}",
    }


def host_pattern(name):
    """An address on the host `name` (with or without "http://" or "https://", with any port), and the path after it."""
    return re.compile(rf"(https?://)?{re.escape(name.split(':')[0])}(?::\d+)?(/.*)?")


def address_edits(meta, host):
    """The literals to rewrite in this client: the official addresses it has, and every address on the hosts of the other
    server it was changed for (its game RPC, its API and its web base, as the official ones are)."""
    edits = {old: new for old, new in metadata_edits(host).items() if meta.find(old)}
    for name in other_hosts(meta):
        pattern = host_pattern(name)
        for i in range(len(meta.entries)):
            text = meta.literal(i).decode("utf-8", "replace")
            m = pattern.fullmatch(text)
            if m:
                edits[text] = f"{'http://' if m.group(1) else ''}{host}{m.group(2) or ''}"
    return edits


def smali_edits(host):
    """Java SDK edits: (file under smali/, old text, new text, expected count)."""
    # Shared prefix of the SDK's request classes.
    req = "com/pmangplus/core/internal/request"
    return [
        # The shim, for phones that run the game's own 32-bit libraries (arm32/shim/shim.cpp): loaded once
        # libunity.so is, and called before each render call and after each mix of FMOD's Java output.
        # Harmless without it: the load only logs, and Hook.ready stays false.
        ("com/unity3d/player/UnityPlayer.smali", "invoke-static {}, Lcom/unity3d/player/k;->a()V",
         'invoke-static {}, Lcom/unity3d/player/k;->a()V\n\n    const-string v0, "opendmtq"\n\n'
         "    invoke-static {v0}, Lcom/unity3d/player/UnityPlayer;->loadLibraryStatic(Ljava/lang/String;)Z", 1),
        ("com/unity3d/player/UnityPlayer.smali", "invoke-direct {p0}, Lcom/unity3d/player/UnityPlayer;->nativeRender()Z",
         "invoke-static {}, Lcom/opendmtq/Hook;->render()V\n\n    "
         "invoke-direct {p0}, Lcom/unity3d/player/UnityPlayer;->nativeRender()Z", 1),
        ("org/fmod/FMODAudioDevice.smali", "invoke-direct {p0, v2}, Lorg/fmod/FMODAudioDevice;->fmodProcess(Ljava/nio/ByteBuffer;)I",
         "invoke-direct {p0, v2}, Lorg/fmod/FMODAudioDevice;->fmodProcess(Ljava/nio/ByteBuffer;)I\n\n"
         "    iget-object v2, p0, Lorg/fmod/FMODAudioDevice;->e:Ljava/nio/ByteBuffer;\n\n"
         "    iget-object v3, p0, Lorg/fmod/FMODAudioDevice;->c:Landroid/media/AudioTrack;\n\n"
         "    invoke-static {v2, v3}, Lcom/opendmtq/Hook;->mix(Ljava/nio/ByteBuffer;Landroid/media/AudioTrack;)V", 1),
        # REAL host (pmangplus.com) and its static host.
        (f"{req}/RequestProcessor$ApiHost.smali", '"pmangplus.com"', f'"{host}"', 1),
        (f"{req}/RequestProcessor$ApiHost.smali", '"static.pmangplus.com"', f'"{host}"', 1),
        # NEON_REAL host, listed as both host and static host.
        (f"{req}/RequestProcessor$ApiHost.smali", '"www.neonapi.com/api"', f'"{host}/api"', 2),
        # Log upload endpoints, so failed sends stay on the LAN.
        ("com/pmangplus/core/internal/PPCore.smali",
         '"http://www.neonapi.com/api/logstash/send/transaction"',
         f'"http://{host}/api/logstash/send/transaction"', 1),
        ("com/pmangplus/core/internal/PPCore.smali",
         '"http://www.neonapi.com/api/logstash/send/"', f'"http://{host}/api/logstash/send/"', 1),
        # Customer-centre web links.
        ("com/pmangplus/ui/activity/PPCustomerCenter.smali",
         '"https://www.neonapi.com/www"', f'"http://{host}/www"', 1),
        ("com/pmangplus/ui/activity/PPCustomerCenter.smali",
         '"https://www.pmangplus.com"', f'"http://{host}"', 1),
        # Some SDK requests ask for HTTPS. The app reaches the server over plain HTTP (the server's
        # HTTPS, for browsers, has a certificate the app would not trust), so build every URL as HTTP.
        (f"{req}/RequestProcessor.smali",
         "    invoke-interface {p2}, Lcom/pmangplus/core/internal/request/UrlRequest;"
         "->getScheme()Lcom/pmangplus/core/internal/request/RequestScheme;\n\n"
         "    move-result-object v2\n\n"
         "    invoke-virtual {v2}, Lcom/pmangplus/core/internal/request/RequestScheme;"
         "->name()Ljava/lang/String;\n\n"
         "    move-result-object v2\n",
         '    const-string v2, "HTTP"\n', 1),
        # Login goes straight to the guest login instead of trying Google Play Games first. That
        # sign-in cannot succeed for a re-signed APK and only puts up Google's profile or install
        # dialog at every start before falling back to the same guest login (PPImpl$21.onError).
        ("com/pmangplus/ui/PPImpl.smali",
         "    invoke-virtual {p0, v2, p1, v3}, Lcom/pmangplus/ui/PPImpl;->loginByGamePlayId_DMQ"
         "(Ljava/lang/String;Landroid/app/Activity;Lcom/pmangplus/core/PPCallback;)V\n",
         "    invoke-virtual {p0, v2, p1, p2}, Lcom/pmangplus/ui/PPImpl;->loginByGuest_share_tq"
         "(Ljava/lang/String;Landroid/app/Activity;Lcom/pmangplus/core/PPCallback;)V\n", 1),
        # After OPTION > Google Play log out the SDK opens Google's Play Games sign-out screen, or
        # on a phone without Play Games its install dialog. The game never signs in there (above),
        # and the server's answer has already gone to the game, which restarts: both callbacks
        # (onSuccess, onError) leave the screen out.
        ("com/pmangplus/ui/PPImpl$19.smali",
         "    invoke-virtual {v1, v0}, Landroid/app/Activity;->startActivity(Landroid/content/Intent;)V\n",
         "", 2),
        # At every sign-in the game reads the clipboard for a token the old Kakao edition left there
        # (MigrationProcessor.SearchValidKakaoToken, the only user of these two), takes whatever
        # text it finds for one, and empties the clipboard: the player's own copied text is lost,
        # and Android 13 and later say it was copied. No Kakao edition hands over to this server,
        # so the clipboard reads as empty and is never written.
        ("com/neowiz/externalsdkgbl/ExternalSDK.smali",
         ".method public static GetClipboard()Ljava/lang/String;\n    .locals 7\n\n    .prologue\n",
         ".method public static GetClipboard()Ljava/lang/String;\n    .locals 7\n\n    .prologue\n"
         "    const/4 v0, 0x0\n\n    return-object v0\n\n", 1),
        ("com/neowiz/externalsdkgbl/ExternalSDK.smali",
         ".method public static SetClipboard(Ljava/lang/String;)V\n    .locals 4\n"
         "    .param p0, \"data\"    # Ljava/lang/String;\n\n    .prologue\n",
         ".method public static SetClipboard(Ljava/lang/String;)V\n    .locals 4\n"
         "    .param p0, \"data\"    # Ljava/lang/String;\n\n    .prologue\n    return-void\n\n", 1),
        # Some seconds into every start the SDK opens its own screen to ask Google Play for the
        # local prices of the game's paid items (PPPurchaseGoogleLocalPrice), which turns the
        # display for a moment. Nothing is sold through this server: the game gets at once the
        # answer it gets on a phone without Google Play billing.
        ("com/pmangplus/ui/PPImpl.smali",
         ".method public getPriceLocalization(Landroid/app/Activity;[Ljava/lang/String;)V\n    .locals 6\n"
         "    .param p1, \"activity\"    # Landroid/app/Activity;\n    .param p2, \"list\"    # [Ljava/lang/String;\n\n"
         "    .prologue\n",
         ".method public getPriceLocalization(Landroid/app/Activity;[Ljava/lang/String;)V\n    .locals 6\n"
         "    .param p1, \"activity\"    # Landroid/app/Activity;\n    .param p2, \"list\"    # [Ljava/lang/String;\n\n"
         "    .prologue\n"
         "    new-instance v0, Lcom/pmangplus/core/exception/MarketFailException;\n\n"
         "    sget-object v1, Lcom/pmangplus/core/model/ErrorCode;->API_ERR_PAY_GOOGLE_NOT_SUPPORTED:Lcom/pmangplus/core/model/ErrorCode;\n\n"
         "    invoke-direct {v0, v1}, Lcom/pmangplus/core/exception/MarketFailException;-><init>(Lcom/pmangplus/core/model/ErrorCode;)V\n\n"
         "    const/4 v1, 0x0\n\n"
         "    invoke-static {v1, v0}, Lcom/pmangplus/ui/internal/JSONManager;->invokeOnLocalPriceFail(Ljava/lang/String;Ljava/lang/Throwable;)V\n\n"
         "    return-void\n\n", 1),
    ]


def arm_branch(at, to, link=False):
    """The ARM instruction bytes of a branch (or branch with link) from one code offset to another."""
    # The processor reads the offset from two instructions ahead, counted in instructions.
    distance = (to - (at + 8)) >> 2
    return ((0xEB if link else 0xEA) << 24 | distance & 0xFFFFFF).to_bytes(4, "little")


# Code edits in the game's libil2cpp.so: (what it does, [(offset, bytes there now, bytes to write)]).
# All the parts of an edit apply together. The offsets are those of client 1.3.4; a client whose
# bytes differ there keeps that screen as it was.
IL2CPP_EDITS = [
    # The main menu opens the server's event page (NoticeWebViewPopup, "NOTICE") at every start, and
    # this server has nothing to announce there. In MainMenu2SceneConfig.OnStart the first
    # instruction after the ClientAuthInfo check becomes a branch past the notice popup, to the
    # nickname, how-to-play and start popups that follow; the notice's close callback
    # (<OnStart>m__0) is empty, and the code after it rewrites every register the skipped part set.
    ("main menu skips the NOTICE popup",
     [(0xEF40F0, bytes.fromhex("0010a0e3" "ac61f9eb"), arm_branch(0xEF40F0, 0xEF42D0) + bytes.fromhex("ac61f9eb"))]),
    # A new install fetches about 42 MB of game data from this server, and the game first asks "Additional
    # files will be downloaded" with one button, OK. Login2SceneConfig.ShowStartPatchPopup keeps its
    # first part, which saves the callback in the small object behind the popup's button, and then
    # calls that button's own handler (<ShowStartPatchPopup>c__AnonStoreyA.<>m__0, which only
    # answers true and does not look at which button) instead of building the popup.
    ("the game's data download starts without asking",
     [(0xCF9250, bytes.fromhex("0500a0e1" "e98f0ceb" "0500a0e1"),
       bytes.fromhex("0800a0e1") + arm_branch(0xCF9254, 0xCFD45C, link=True) + arm_branch(0xCF9258, 0xCF9618))]),
    # The shop's Q tab sells only for real money through Google Play, which reaches nothing here
    # (its tab is hidden in ASSET_EDITS), and the + by the points opens the shop on that tab.
    # Shop2SceneConfig.SetTabType turns Q into MAX in four instructions kept in the room left by
    # TopFrame.OnClickMoreGames, a handler whose button is hidden too: compare, swap, the first
    # instruction it replaced, and back.
    ("the shop opens on its MAX tab instead of the real-money one",
     [(0xD2F4B4, bytes.fromhex("f0482de9"), arm_branch(0xD2F4B4, 0x9D735C)),
      (0x9D735C, bytes.fromhex("f04d2de9" "18b08de2" "0080a0e1" "a0039fe5"),
       bytes.fromhex("000051e3" "0110a003" "f0482de9") + arm_branch(0x9D7368, 0xD2F4B8))]),
    # At every start the game turned its low resolution option on for good (Startup.Initialize writes OptionData's
    # LowResolutionGrap, whatever was saved, just before LowResolution.Apply reads it), so that on every phone it drew at two
    # thirds of the panel's height: 960 lines on a 1440 line panel, 720 on 1080. Written off, Apply takes the device's own
    # resolution. A device that then does not keep its frame rate goes back to the low one by itself (arm32/README.md, Resolution),
    # so the option's row is gone from the screen (ASSET_EDITS).
    ("the panel's own resolution", [(0x9C385C, bytes.fromhex("01 10 a0 e3"), bytes.fromhex("00 10 a0 e3"))]),
    # A menu left untouched drops step by step to 18 frames a second (VariableFrameController.AutoAdjustFrameRate, to save
    # battery on the phones of its day) and jumps back at the next touch, which shows. SetTargetFrameRate now never goes below
    # the game's cap for menus, maxOutgameFpsVal: 60 on a phone running the game's own libraries, the app's frame rate under
    # the runtime, so 120 on a 120 Hz phone (a limit of 60 there judders: a timer's frames stay for two refreshes or three,
    # one frame in five measured on a Galaxy S26 Ultra). In the rest of the same dead handler: keep the rate asked for, load
    # the class's static fields through the slot InitFrameRate uses, stop if the class is not set up yet, raise, and back.
    # The runtime's fallback to a lower rate lowers that cap too, so this follows it.
    ("a menu left alone keeps its frame rate",
     [(0x9AFE60, bytes.fromhex("0140a0e1"), arm_branch(0x9AFE60, 0x9D736C)),
      (0x9D736C, bytes.fromhex(
       "a0539fe5 00008fe0 000085e0 2c01d0e5 000050e3"
       "0800001a 8c039fe5 8c139fe5 00608fe0 060091e7"
       "000090e5 e04a19eb 060085e0 0110a0e3 2c11c0e5"),
       bytes.fromhex(
       "0140a0e1 2c009fe5 00008fe0 000090e5 000090e5"
       "000050e3 0500000a 500090e5 000050e3 0200000a"
       "0c0090e5 000054e1 0040a0b1 af62ffea dcaca700"))]),
]


def patch_il2cpp(path):
    """Apply the code edits whose bytes match; report the ones that do not. Returns what was applied (IL2CPP_EDITS' names)."""
    with open(path, "rb") as f:
        code = bytearray(f.read())
    applied = set()
    for what, parts in IL2CPP_EDITS:
        if all(code[offset:offset + len(old)] == old for offset, old, _ in parts):
            for offset, _, new in parts:
                code[offset:offset + len(new)] = new
            log(f"  code      {what}")
            applied.add(what)
        else:
            log(f"  code      skipped ({what}): this client's code differs")
    with open(path, "wb") as f:
        f.write(code)
    return applied


# Where the game keeps its screens inside the APK.
ASSET_DIR = "assets/bin/Data"
# The button on every screen's top bar that lists the publisher's other games: it asks a server
# that no longer exists and answers "Network connection error".
_MORE_GAMES = "UI_Top/[CW_100]_BTN_MoreGames"
# The lobby's list of menu entries, and the main menu's page.
_LOBBY = "MainMenu2Scene/SelectSongPage/UI_Left/SET_BTN"
_MENU = "MainMenu2Scene/MenuPage/Contents"
_OPTIONS = "Option2Scene/Contents/[RQ_3300]_Scroll_view/grid"
_SHOP_TABS = "Shop2Scene/UI_Tab"
# The game's project settings (globalgamemanagers, a file with no names in it: the places were found by reading it with the class
# database for Unity 5.6.5 and are checked against the real client in tests/test_real_client.py): place, what is there, what goes
# there. Its Android build asked for a 16-bit screen, which bands in every gradient of a jacket and a background, and for its
# lowest quality level at half-size textures.
SETTINGS_FILE = "globalgamemanagers"
SETTING_EDITS = {
    "PlayerSettings.use32BitDisplayBuffer": (28334, 0, 1),
    "QualitySettings[Fastest].textureQuality": (84516, 1, 0),
}

# Screens taken apart for this server: file name -> edits. Each menu entry below leads nowhere here:
# what it did depended on the publisher's services, and what remains closes up around the gap.
ASSET_EDITS = {
    "0e6ef57ba72a94141971da1e5474e9c7": [
        ("hide", f"MainMenu2Scene/SelectSongPage/{_MORE_GAMES}"),
        # PLAY FOR FREE: ad-paid songs from an ad network; every song is free here, and the page is empty. Client 1.3.5
        # has a second button of its own for it and turns one of the two on as the lobby opens: both also go off the
        # screen, to the left.
        ("hide", f"{_LOBBY}/[CW_250]_BTN_FreeMusic"),
        ("move", f"{_LOBBY}/[CW_250]_BTN_FreeMusic", -4000, None),
        ("hide if there", f"{_LOBBY}/[CW_250]_BTN_FreeMusic_Disable"),
        ("move if there", f"{_LOBBY}/[CW_250]_BTN_FreeMusic_Disable", -4000, None),
        # MUSIC SHOP: songs for sale; none are, so it is an empty page with a Purchase button.
        ("hide", f"{_LOBBY}/[CW_250]_BTN_MusicShop"),
        # PACKAGE: bundles for real money through Google Play.
        ("hide", f"{_LOBBY}/[CW_250]_BTN_Package"),
        # QUEST: the server has a fixed answer from 2017, so nothing ever progresses or pays out.
        ("hide", f"{_LOBBY}/[CW_250]_BTN_QUEST"),
        # The divider and HOW TO PLAY close up under MUSIC LIST.
        ("move", f"{_LOBBY}/Line", None, -30),
        ("move", f"{_LOBBY}/[CW_250]_BTN_HowToPlay", None, -155),
        # The publisher's Instagram, Facebook and Twitter pages, and the line that advertises them.
        ("hide", f"{_MENU}/[CW_100]_BTN_Instagram"),
        ("hide", f"{_MENU}/[CW_100]_BTN_Facebook"),
        ("hide", f"{_MENU}/[CW_100]_BTN_Twitter"),
        ("hide", f"{_MENU}/txt_SNS"),
        # MESSAGE: the mailbox of the publisher's operators; nobody sends anything here.
        ("hide", f"{_MENU}/[CW_100]_BTN_Message"),
        # The three entries left, centred.
        ("move", f"{_MENU}/[CW_100]_BTN_Shop", -363, None),
        ("move", f"{_MENU}/[CW_100]_BTN_Album", 0, None),
        ("move", f"{_MENU}/[CW_100]_BTN_Option", 363, None),
    ],
    "8157950577fc8f3429896245b26a86c2": [
        # RESTORE DATA / CONNECT ACCOUNT: asks to write to the publisher's customer centre.
        ("hide", f"{_OPTIONS}/List_account"),
        # Google Play game account, Log out: the game never signs in to Google Play here.
        ("hide", f"{_OPTIONS}/List_logout"),
        # CONTACT US: the publisher's customer centre.
        ("hide", f"{_OPTIONS}/List_ask"),
        # Low resolution graphics: the game wrote it on at every start, whatever was picked here; it is decided by itself now.
        ("hide", f"{_OPTIONS}/List_low_resolution_graphics"),
    ],
    "36c46844b8387b5409454b553046b497": [
        ("hide", f"Shop2Scene/{_MORE_GAMES}"),
        # The Q tab: real money through Google Play (see IL2CPP_EDITS). The other three, which take
        # the points every player has, close up.
        ("hide", f"{_SHOP_TABS}/Btn_Tab1"),
        ("move", f"{_SHOP_TABS}/Btn_Tab2", -387, None),
        ("move", f"{_SHOP_TABS}/Btn_Tab3", 0, None),
        ("move", f"{_SHOP_TABS}/Btn_Tab4", 387, None),
    ],
    # The same button on the other screens with a top bar.
    "27c6912d68652cd4a9a5a5df6bff95e6": [("hide", f"MusicShop2Scene/MusicShopPage/{_MORE_GAMES}")],
    "29d8da18d5cb7a542a2acc18fadd4781": [("hide", f"Message2Scene/{_MORE_GAMES}")],
    "2f132335e85bef340aeb71c03c64c189": [("hide", f"MyPage2Scene/{_MORE_GAMES}")],
    "350ed6dbd6fc4a640a2788058a7903a6": [("hide", f"Package2Scene/{_MORE_GAMES}")],
    "588d0dca0ad8d1348be9fb473e4f7f26": [("hide", f"SongRank2Scene/{_MORE_GAMES}")],
    "6e3ed7e511e97a940a9f6c7ac18caa13": [("hide", f"TotalRank2Scene/{_MORE_GAMES}")],
    "cb78d9fa3663f9843a96a0784f091717": [("hide", f"Quest2Scene/{_MORE_GAMES}")],
}


# Screen edits that go with a code edit (path prefix -> the code edit's name): a client the code edit does not fit keeps
# those parts of the screen as they were. The shop's Q tab is hidden only when the shop no longer opens on it.
ASSET_NEEDS = {
    f"{_SHOP_TABS}/": "the shop opens on its MAX tab instead of the real-money one",
}


def patch_settings(root):
    """Make the edits to the game's project settings; a client whose bytes differ keeps its settings."""
    path = os.path.join(root, ASSET_DIR, SETTINGS_FILE)
    with open(path, "rb") as f:
        data = bytearray(f.read())
    if any(place >= len(data) or data[place] != old for place, old, _ in SETTING_EDITS.values()):
        log(f"  settings  skipped: {SETTINGS_FILE} is not this client's")
        return
    for name, (place, _, new) in SETTING_EDITS.items():
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
                log(f"  screens   {name}: {len(edits) - len(kept)} edits left out, with the code edit they go with")
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
        log(f"  screens   {name}: {len(edits)} edits")


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
                log(f"  smali     {f}: {n}x address of the other server")
                changed += n
    return changed


def patch_smali(root, host):
    """Apply the SDK edits; every edit must match exactly its expected number of times, or be there already (a client
    changed for another server often has the same changes made by hand)."""
    hook = os.path.join(root, "smali", "com", "opendmtq", "Hook.smali")
    os.makedirs(os.path.dirname(hook), exist_ok=True)
    with open(hook, "w", encoding="utf-8") as f:
        f.write(HOOK_SMALI)
    for rel, old, new, expected in smali_edits(host):
        path = os.path.join(root, "smali", rel)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            raise SystemExit(f"smali {rel}: not in this client; unsupported base APK") from None
        n = text.count(old)
        if n == 0 and (text.count(new) >= expected if new else True):
            # Made already (by whoever changed the client), or a call to take out that is gone: nothing to do.
            log(f"  smali     {rel.rsplit('/', 1)[-1]}: already {(new or 'without ' + old).strip()[:48]}")
            continue
        # Any other count means a different client build: stop before producing a half-patched APK.
        if n != expected:
            raise SystemExit(f"smali {rel}: expected {expected} match(es), found {n}; unsupported base APK")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(old, new))
        log(f"  smali     {rel.rsplit('/', 1)[-1]}: {n}x {old.strip()[:48]}")


def signed_builds(out_dir):
    """Manifests in out_dir that record the key their app was signed with."""
    try:
        names = sorted(os.listdir(out_dir))
    except OSError:
        return []
    found = []
    for name in names:
        if name != "latest.json" and not (name.startswith("OpenDMTQ-") and name.endswith(".apk.json")):
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
    # original before a client changed for another server, the client the code edits were made for before another
    # version, then the newest (the last imported: the import writes each copy anew).
    last = distinct.get(last_base(base_dir))
    if last:
        return last, True
    return min(distinct.values(), key=lambda f: (infos[f]["kind"] != "original", not infos[f]["known"],
                                                  -os.path.getmtime(f))), False


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
                             "import the game's Android app with ./opendmtq import <folder>")
        raise SystemExit("no base APK in data/apk/base; run ./opendmtq import <folder> first")
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
    builds = sorted((f for f in os.listdir(out_dir) if f.startswith("OpenDMTQ-") and f.endswith(".apk")),
                    key=lambda f: os.path.getmtime(os.path.join(out_dir, f)))
    for old in builds[:-keep]:
        if old != offered:
            os.remove(os.path.join(out_dir, old))
            if os.path.exists(os.path.join(out_dir, old + ".json")):
                os.remove(os.path.join(out_dir, old + ".json"))


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


def put_in_place(src, dest):
    """Copy src to dest through a temporary file next to dest that is then swapped in whole. A second
    build on the same day has the same name as the app the portal offers: a phone that is downloading
    it keeps reading the old file, and a copy that fails half-way (a full disk) leaves the old file
    as it was, never a truncated one under the name latest.json points at."""
    # A dot in front: neither the admin pages, the pruning nor the portal take it for a build.
    part = os.path.join(os.path.dirname(dest), "." + os.path.basename(dest) + ".part")
    try:
        shutil.copyfile(src, part)
        os.replace(part, dest)
    except BaseException:
        # Nothing half-copied stays behind (a hundred MB on a disk that may be full).
        try:
            os.remove(part)
        except OSError:
            pass
        raise


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
        # v1+v2+v3 so every Android version from 4.0 up accepts it; quiet unless it fails.
        r = subprocess.run([JAVA, "-jar", SIGNER, "-a", unsigned, "-o", signed_dir, "--ks", ks,
                            "--ksAlias", "opendmtq", "--ksPass", password, "--ksKeyPass", password],
                           # Java writes in the system's code page, this program reads UTF-8: a message in another
                           # language must not stop the build.
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            sys.stderr.write(r.stdout + r.stderr)
            raise SystemExit("signing failed")
        signed = [f for f in os.listdir(signed_dir) if f.endswith(".apk")]
        if len(signed) != 1:
            raise SystemExit(f"signer produced {signed}")

        # Name says what it is, for which server, and when.
        # ":" (a port) is not allowed in file names on Windows and confuses Android's downloads.
        name = f"OpenDMTQ-{host.replace(':', '-')}-v{args.stamp}.apk"
        os.makedirs(out_dir, exist_ok=True)
        dest = os.path.join(out_dir, name)
        # Swapped in whole: the same name may be the app the portal offers right now.
        put_in_place(os.path.join(signed_dir, signed[0]), dest)
    finally:
        # Hundreds of MB, in the admin service's RAM-backed /tmp: never left behind.
        shutil.rmtree(WORK, ignore_errors=True)

    # Manifest the CLI and the web portal read: which file to offer and which host it targets.
    manifest = {
        "file": name, "host": host, "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "sha256": sha256(dest), "size": os.path.getsize(dest),
        "base": os.path.basename(base), "base_sha256": sha256(base), "base_version": client["version"],
        "base_kind": client["kind"], "patcher": VERSION,
        "key_sha256": keystore_sha256(), "runtime": runtime, "label": label, "package": package,
    }
    # Each build keeps its own manifest (the admin page lists them); latest.json is the portal's.
    targets = [dest + ".json"] + ([] if args.keep_latest else [os.path.join(out_dir, "latest.json")])
    for target in targets:
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        # Atomic swap so readers never see a half-written manifest.
        os.replace(tmp, target)

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
