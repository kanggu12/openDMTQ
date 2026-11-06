"""`opendmtq doctor` (is everything in place?) and `opendmtq check` (does the game's path work?).

Each check prints one line and says how to fix a failure. A probe that cannot run is reported as a
failure, never as "nothing wrong".
"""

import base64
import hashlib
import json
import os
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from . import env, system
from .system import DATA, ENV_FILE, fail, ok, warn

def local_address(values):
    """The address this machine reaches the public port on: loopback, or BIND_ADDRESS when the
    port is published on that one address only."""
    bind = values.get("BIND_ADDRESS") or ""
    return bind if bind and bind != "0.0.0.0" else "127.0.0.1"


def _local():
    """Where the server answers on this machine: port LISTEN_PORT on local_address()."""
    values = env.load(ENV_FILE)
    return f"http://{local_address(values)}:{values.get('LISTEN_PORT') or '80'}"


# Another deployment to check instead of this machine's server (`check --url`, or OPENDMTQ_URL).
OTHER = os.environ.get("OPENDMTQ_URL", "").rstrip("/") or None
# Account the end-to-end check logs in with; the portal hides it from the player list.
CHECK_UDID = "opendmtq-check"


def base_url():
    """Base URL every check uses. This machine's is read from .env each time: expose and host
    change LISTEN_PORT and then wait for the server on the new port."""
    return OTHER or _local()


def _raw(method, path, body=None, headers=None):
    """One request without following redirects: (status, headers, body)."""
    import http.client
    u = urllib.parse.urlsplit(base_url())
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=10)
    try:
        conn.request(method, path, body, headers or {})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    except OSError:
        return 0, {}, b""
    finally:
        conn.close()


def http(url, data=None, json_body=None, method=None, timeout=10, headers=None):
    """(status, body bytes); (0, b'') when nothing answers."""
    # Some services refuse Python's default User-Agent.
    headers = {"User-Agent": "opendmtq", **(headers or {})}
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except OSError:
        return 0, b""


def ca_fingerprint():
    """SHA-256 fingerprint of the server's certificate authority (data/https/ca.crt), as phones show
    it in a certificate's details, or None. Compare it before trusting a downloaded ca.crt."""
    try:
        with open(os.path.join(DATA, "https", "ca.crt"), encoding="ascii") as f:
            pem = f.read()
        der = base64.b64decode("".join(l for l in pem.splitlines() if l and not l.startswith("-----")))
    except (OSError, ValueError):
        return None
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def https_problem(host):
    """None when the server's HTTPS door answers on this machine with a certificate that the
    server's own authority (data/https/ca.crt) vouches for under the address phones use, and that
    does not run out within 30 days; else what is wrong."""
    ca = os.path.join(DATA, "https", "ca.crt")
    if not os.path.isfile(ca):
        return "no HTTPS certificate yet (data/https); run ./opendmtq up"
    name = env.split(host)[0]
    values = env.load(ENV_FILE)
    port = env.listen_port(values)
    context = ssl.create_default_context(cafile=ca)
    try:
        with socket.create_connection((local_address(values), port), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=name) as tls:
                cert = tls.getpeercert()
                tls.sendall(f"GET /opendmtq/health.php HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
                head = tls.recv(64).decode("latin-1")
    except ssl.SSLCertVerificationError as e:
        return f"HTTPS presents a certificate that does not fit {name} ({e.verify_message}); run ./opendmtq up"
    except (OSError, ssl.SSLError) as e:
        return f"HTTPS does not answer on port {port} ({e}); see ./opendmtq logs edge"
    if not head.startswith("HTTP/1.1 200"):
        return f"HTTPS answers, but the health page says {head.splitlines()[0] if head else 'nothing'}"
    # What the edge presents, which may be older than the file if it was not restarted.
    days = (ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()) / 86400
    if days < 30:
        return f"the HTTPS certificate in use runs out in {max(days, 0):.0f} days; run ./opendmtq up"
    return None


def health():
    """The portal's health JSON, or None."""
    status, body = http(f"{base_url()}/opendmtq/health.php")
    try:
        return json.loads(body) if status in (200, 503) else None
    except ValueError:
        return None


# A status still saying "building" after this long belongs to a run that was cut off (its container
# stopped, the PC turned off). The builder (tools/opendmtq_tools/builder.py), the portal and the
# admin pages use the same limit.
STALE_BUILD = 15 * 60


def build_status():
    """The app builder's last outcome (data/apk/out/build.json) as a dict, or None. Its "time" is
    a number of Unix seconds (0 when the file has none)."""
    try:
        with open(os.path.join(DATA, "apk", "out", "build.json"), encoding="utf-8") as f:
            status = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(status, dict):
        return None
    try:
        status["time"] = float(status.get("time") or 0)
    except (TypeError, ValueError):
        status["time"] = 0.0
    return status


def runtime_problem():
    """Why the builder could not get the runtime for newer phones (data/apk/runtime-error.txt, which it writes), or nothing."""
    try:
        with open(os.path.join(DATA, "apk", "runtime-error.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def no_runtime_notice():
    """What to tell the owner about an app without the runtime. The builder noted why it could not get it: the fix for a server
    without internet is a different one."""
    why = runtime_problem()
    return (f"newer phones (Pixel 7, Galaxy S24 and later) cannot install this app{': ' + why if why else ''}. "
            "./opendmtq runtime tries again; without internet, docs/closed-network.md says what to bring")


def app_lacks_runtime():
    """True when there is an app on offer, and it has no runtime in it."""
    try:
        with open(os.path.join(DATA, "apk", "out", "latest.json"), encoding="utf-8") as f:
            return not json.load(f).get("runtime")
    except (OSError, ValueError, AttributeError):
        return False


def build_problem(host):
    """Why the builder's last run for host failed, or None (also when it never ran, or ran for
    another address). The portal and the admin pages read the same file."""
    status = build_status()
    if not status or status.get("host") != host:
        return None
    if status.get("state") == "failed":
        return status.get("error") or "no reason given"
    if status.get("state") == "building" and time.time() - status["time"] > STALE_BUILD:
        return "it stopped part-way (the builder was stopped or the PC turned off)"
    return None


def key_problem(manifest):
    """Why the newest app is not signed with the key in data/apk/keystore, or None."""
    recorded = manifest.get("key_sha256")
    # Builds from before the manifest recorded the key cannot be compared.
    if not recorded:
        return None
    try:
        with open(os.path.join(DATA, "apk", "keystore", "opendmtq.jks"), "rb") as f:
            current = hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        return ("the signing key data/apk/keystore/opendmtq.jks is missing, and phones' apps are signed with "
                "it (no update installs without it); put it back: ./opendmtq restore <backup> --with-key")
    except OSError as e:
        return f"cannot read the signing key to compare it with the app's: {e}"
    if current != recorded:
        return ("the app /apk offers was signed with another key than data/apk/keystore holds (restored "
                "from a backup?); run ./opendmtq apk so phones get an app that installs over theirs")
    return None


def doctor():
    """Check every precondition; returns the number of failures."""
    failures = 0
    values = env.load(ENV_FILE)
    host = values.get("PUBLIC_HOST", "")

    # Where the repository is.
    if env.windows_drive(system.ROOT):
        warn("the repository is on a Windows drive: the database is slow there and file owners cannot be "
             "set. Clone it inside WSL (for example ~/openDMTQ) and move data/ and .env over")

    # .env and the address.
    problem = env.check_host(host)
    if problem:
        fail(f"{problem}; run ./opendmtq setup (or ./opendmtq host <address>)")
        failures += 1
    else:
        detected = env.detect_host()
        # A WSL NAT address (Docker Desktop) is never the one phones use, so it is not a new address.
        bare = env.split(host)[0]
        if env.is_lan_only(host) and detected and detected != bare and not env.wsl_nat_address(detected) and not env.has_address(bare):
            new = env.join(detected, env.split(host)[1])
            warn(f"PUBLIC_HOST is {host} but this machine now uses {detected}; "
                 f"run ./opendmtq host {new} (rebuilds the APK)")
        else:
            ok(f"PUBLIC_HOST {host}")
        if env.wsl_nat_address(host):
            fail("WSL is in NAT mode, so phones cannot reach this address. Add networkingMode=mirrored "
                 "under [wsl2] in %UserProfile%\\.wslconfig, run `wsl --shutdown`, then ./opendmtq setup")
            failures += 1
        mismatch = env.port_problem(values)
        if mismatch:
            fail(mismatch)
            failures += 1

    # Docker.
    system.require_docker()
    r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True)
    if r.returncode != 0:
        fail("Docker is not running or not reachable (docker info failed)")
        return failures + 1
    ok(f"Docker {r.stdout.strip()}")

    # Content: the game data the game cannot start without, and the songs, which a server may well not have yet.
    import glob
    if glob.glob(os.path.join(DATA, "content", "web", "patch", "phone_new", "*", "android", "patch_new.csv.lz4")):
        ok("game data in data/content")
        # All of it: without the image bundles of its screens the game stops at its start and says nothing.
        try:
            with open(os.path.join(DATA, "custom", "missing-game-files.json"), encoding="utf-8") as f:
                missing = json.load(f)
        except (OSError, ValueError):
            missing = []
        if missing:
            fail(f"{len(missing)} of the game's own files are missing ({missing[0]}, ...): phones stop at the game's start "
                 "without them. Import the whole server files again: ./opendmtq import <folder with your game files>")
            failures += 1
    else:
        fail("no game data; run ./opendmtq import <folder with your game files>")
        failures += 1
    try:
        with open(os.path.join(DATA, "content", "songs.json"), encoding="utf-8-sig") as f:
            imported = len(json.load(f))
    except (OSError, ValueError):
        imported = 0
    if imported:
        ok(f"{imported} songs imported")
    else:
        warn("no songs imported: the game starts with an empty song list (./opendmtq import --songs <folder>)")
    bases = [f for f in os.listdir(os.path.join(DATA, "apk", "base"))] if os.path.isdir(os.path.join(DATA, "apk", "base")) else []
    if any(f.lower().endswith(".apk") for f in bases):
        ok(f"base APK: {', '.join(sorted(f for f in bases if f.lower().endswith('.apk')))}")
    else:
        fail("no base APK in data/apk/base; run ./opendmtq import <folder>")
        failures += 1

    # Who owns the data: a run with sudo leaves it to a user the server no longer runs as.
    owner = system.data_owner_problem()
    if owner:
        fail(owner)
        failures += 1

    # The edge holds the public port; without it phones reach nothing.
    edge = system.container_state("edge")
    if edge != "running":
        fail(f"the edge proxy (public port) is {edge or 'not created'}; run ./opendmtq up")
        failures += 1

    # Server.
    state = system.container_state()
    if state != "running":
        fail(f"server is {state or 'not created'}; run ./opendmtq up")
        failures += 1
    else:
        h = health()
        if not h:
            fail(f"server container runs but the portal does not answer at {base_url()}; see ./opendmtq logs")
            failures += 1
        elif not h.get("ok"):
            fail(f"server unhealthy: {json.dumps(h)}")
            failures += 1
        else:
            ok(f"server healthy: {h['songs']} songs, {h['players']} players, patch {h['patch']}")
            if h.get("host") != host:
                fail(f"server runs for {h.get('host')} but .env says {host}; run ./opendmtq up")
                failures += 1
            # The same port also takes HTTPS, for browsers.
            tls_problem = https_problem(host)
            if tls_problem:
                fail(tls_problem)
                failures += 1
            else:
                ok(f"HTTPS on the same port: https://{env.https_address(host)}/ (own certificate; a phone "
                   f"that installs http://{host}/ca.crt skips the browser warning)")
                ok(f"  its authority's SHA-256 fingerprint, to compare on the phone before trusting it: "
                   f"{ca_fingerprint()}")

    # APK, and the builder's last run (build.json): when it failed, ./opendmtq up stops on it and the
    # portal may tell players to ask the owner; its reason is the fix to look for.
    build_failure = build_problem(host) if host else None
    manifest = os.path.join(DATA, "apk", "out", "latest.json")
    m = None
    try:
        with open(manifest, encoding="utf-8") as f:
            m = json.load(f)
        if m["host"] == host:
            # With the arm32 runtime the same download also serves phones without 32-bit support, and
            # 64-bit phones on Android 5 and 6 (they cannot ask for the 32-bit libraries) run it too.
            runtime = (f", arm32 runtime {m['runtime']} for 64-bit-only phones and 64-bit Android 5-6"
                       if m.get("runtime") else ", for phones that still run 32-bit apps (no arm32 runtime bundle)")
            ok(f"APK {m['file']}{runtime}")
            if not m.get("runtime"):
                warn(no_runtime_notice())
            if build_failure:
                # An app for this address exists, but rebuilding it (a new patcher, base APK, runtime
                # bundle or key) failed: phones keep getting the earlier app, and every up fails.
                fail(f"the last rebuild of the app failed: {build_failure}; phones still get {m['file']}. "
                     "Fix that, then ./opendmtq apk")
                failures += 1
        else:
            fix = (f"building it for {host} failed: {build_failure}" if build_failure
                   else "run ./opendmtq apk and install it over the old one")
            fail(f"APK was built for {m['host']}, server is {host}; {fix}")
            failures += 1
    except (OSError, ValueError, KeyError, TypeError):
        fail("no patched APK yet; " + (f"the build failed: {build_failure}" if build_failure else "run ./opendmtq apk"))
        failures += 1
    key = key_problem(m) if isinstance(m, dict) else None
    if key:
        fail(key)
        failures += 1
    elif os.path.isfile(os.path.join(DATA, "apk", "keystore", "opendmtq.jks")):
        ok("signing key present (included in backups)")

    # Windows firewall (WSL only).
    port = env.listen_port(values)
    exposed = bool(host) and not env.is_lan_only(host)
    if env.is_wsl():
        present = system.firewall_rule_present(port, exposed)
        if present is None:
            warn("could not read the Windows firewall from here")
        elif present:
            ok(f"Windows firewall rule '{system.firewall_rule_name(port)}' ({'internet' if exposed else 'LAN'})")
        else:
            fail(f"Windows firewall does not let phones reach TCP {port}; run ./opendmtq firewall")
            failures += 1

    # Exposed: the forwarded port must answer from outside.
    if exposed and not problem:
        failures += external(host)

    print()
    where = "anywhere" if exposed else "the same Wi-Fi"
    print(f"  Last step only a phone can prove: open http://{host or '<address>'}/ in the phone's browser ({where}).")
    return failures


# Set when the outside test could not run, so the verdict does not claim more than was checked.
EXTERNAL_UNTESTED = False


def external(address, nodes=4):
    """Ask check-host.net to open TCP and fetch the health page from other countries; returns failures."""
    import time
    host, port = env.split(address)
    url = f"http://{address}/opendmtq/health.php"
    accept = {"Accept": "application/json"}
    try:
        st, body = http(f"https://check-host.net/check-http?host={urllib.parse.quote(url, safe='')}&max_nodes={nodes}",
                        headers=accept, timeout=15)
        req = json.loads(body)["request_id"]
    except (ValueError, KeyError):
        warn("could not reach check-host.net to test from outside; try again later")
        global EXTERNAL_UNTESTED
        EXTERNAL_UNTESTED = True
        return 0
    # Results arrive over a few seconds; null means "still running".
    results = {}
    for _ in range(15):
        time.sleep(2)
        _, body = http(f"https://check-host.net/check-result/{req}", headers=accept, timeout=15)
        try:
            results = json.loads(body)
        except ValueError:
            continue
        if results and all(v is not None for v in results.values()):
            break
    passed = [n for n, v in results.items() if v and v[0] and v[0][0] == 1 and str(v[0][3]) == "200"]
    names = ", ".join(n.split(".")[0] for n in passed)
    if passed:
        ok(f"reachable from outside: {len(passed)}/{len(results)} check-host nodes got HTTP 200 ({names})")
        return 0
    fail(f"not reachable from the internet at {url}: forward TCP {port} on every router to this PC "
         "(see docs/internet.md), then ./opendmtq doctor")
    return 1


def rpc(method, params):
    """One JSON-RPC call; (result, error text)."""
    status, body = http(f"{base_url()}/DMQ/rpc", json_body=[{"id": 1, "method": method, "params": params}])
    try:
        reply = json.loads(body)[0]
    except (ValueError, IndexError, KeyError, TypeError):
        return None, f"HTTP {status}, not JSON: {body[:100]!r}"
    return reply.get("result"), reply.get("error")


def end_to_end():
    """Walk the path the game takes against the running server; returns the number of failures."""
    server = base_url()
    # This machine's server, whose .env says what phones are told.
    here = server == _local()
    # The address the checked server was started with (it may be another deployment than .env's).
    h = health()
    host = (h or {}).get("host") or env.load(ENV_FILE).get("PUBLIC_HOST", "")
    failures = 0

    def bad(msg):
        nonlocal failures
        failures += 1
        fail(msg)

    # 0. Every request below goes to LISTEN_PORT, wherever the app would send it: on a LAN address
    # a different port in it is the one thing this walk cannot see by itself.
    if here:
        problem = env.port_problem(env.load(ENV_FILE))
        if problem:
            bad(problem)

    def lan(url):
        # The game fetches http://PUBLIC_HOST/...; map it back to this machine.
        prefix = f"http://{host}/"
        if not url.startswith(prefix):
            bad(f"server handed out a URL the phone cannot reach: {url}")
            return None
        return f"{server}/{url[len(prefix):]}"

    # 1. Boot: where the API, patches and score pages are.
    info, err = rpc("service.getInfo", ["1.3.5", "ANDROID"])
    if err or not info:
        bad(f"boot RPC service.getInfo: {err}")
        return failures
    for key in ("api_url", "file_server_url", "event_url"):
        if not str(info.get(key, "")).startswith(f"http://{host}/"):
            bad(f"service.getInfo {key} = {info.get(key)!r}")
    ok(f"boot RPC: api {info.get('api_url')}, patch {info.get('file_manage_ver')}")

    # 2. Platform login on both paths the SDK uses.
    token = None
    for path in ("/api/accounts/v3/global/login_dmq", "/accounts/v3/global/login_dmq"):
        status, body = http(server + path, data={"app_id": "576", "udid": CHECK_UDID, "device_cd": "ANDROID"})
        try:
            token = json.loads(body)["value"]["access_token"]
            ok(f"platform login {path}")
        except (ValueError, KeyError, TypeError):
            bad(f"platform login {path}: HTTP {status}")

    # 3. Game login.
    guid = None
    if token:
        res, err = rpc("user.loginV2", [token, " ", "", "1.3.5", "ANDROID", "KR"])
        guid = (res or {}).get("guid")
        if guid:
            ok(f"game login (check account {guid})")
        else:
            bad(f"game login: {err}")

    # 4. One song and one pattern, through the URLs the server hands out.
    if guid:
        urls, _ = rpc("game.getSongUrl", [int(guid), 1, "ANDROID", "1.3.5"])
        pattern, _ = rpc("game.getPatternUrl", [int(guid), 1, "", "P"])
        fetched = 0
        for u in (urls or {}).get("pmang", []) + ([pattern] if pattern else []):
            local = lan(u)
            if local and http(local, method="HEAD")[0] == 200:
                fetched += 1
            elif local:
                bad(f"missing file behind {u}")
        if fetched:
            ok(f"song and pattern downloads: {fetched} files")

    # 5. Every song in the list: archive and jacket (names are case-sensitive on Linux).
    # The list the server serves: the imported songs and the added ones (data/custom), else the imported list alone.
    served = os.path.join(DATA, "custom", "songList.json")
    try:
        with open(served if os.path.isfile(served) else os.path.join(DATA, "content", "songs.json"),
                  encoding="utf-8-sig") as f:
            songs = json.load(f)
    except (OSError, ValueError):
        # No songs at all is a server that works: it only has nothing to offer yet.
        songs = []
    missing = 0
    for s in songs:
        for path in (f"/DMQ/Songs/{s['song_id']}/{s['song_id']}.fpk", f"/viewImg/eye/{s['name']}.png"):
            if http(server + path, method="HEAD")[0] != 200:
                missing += 1
                bad(f"song {s['song_id']} ({s['name']}): {path} missing")
    if songs and not missing:
        ok(f"all {len(songs)} songs: archive and jacket present")

    # 6. The APK download a phone would use: behind the site's sign-in, so a stranger is sent there. Signing in takes an
    #    account, which only the owner makes; the file itself is checked above (the app is up to date).
    status, headers, _ = _raw("HEAD", "/apk")
    if status == 302 and "login.php" in headers.get("Location", ""):
        ok("APK download at /apk, behind the site's sign-in")
    else:
        bad(f"/apk without signing in answers HTTP {status}, not the sign-in page")

    return failures
