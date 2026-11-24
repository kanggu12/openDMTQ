"""The connection test (Online's Test connection, PLAY's Server row when the server does not answer, and
OpenDMTQ-cmd.exe --test-server): the way from this PC to its server, a step at a time, each with what it found and how
long it took.

  address     the address as the launcher reads it (server.normalize): its scheme, host and port
  lookup      the host's name looked up: its addresses (nothing to look up for an address given as one)
  port        a connection to the port: open, refused, no answer in time, or no way from this PC to it (a network it
              cannot reach). When nothing answers there, the same host on 8791 and the ports a new server takes when 8791
              is taken (to 8799): an OpenDMTQ server found there is named, with its address to use (a server updated to
              0.11.0 moved from port 80 to 8791), over HTTPS checked with the authority trusted for the old address
  server      the answer as an OpenDMTQ server (client.php?about): its name and version, and over HTTPS whose certificate.
              When another program answers there instead (another web server took the port, or one with a certificate
              this PC does not trust), the same look for the server on those ports
  version     the server's version against this launcher's
  signin      the sign-in this launcher keeps for the server, still taken (asked with its cookie: no password)
  game        the game server's own answer, as the game asks it at its start (its health page: its patch, maintenance)
  broadcasts  the broadcast state the player asks for between songs (/live/state)
  downloads   what the launcher and the game download, by heads alone: the app (/apk, signed in) and the client data's
              list of files (patch_new.csv.lz4 of the server's patch)
  round_trip  a few small asks one after another: the median time and the fastest and slowest

Each step's state: ok, warn (found, and not as it should be for everything to work: no sign-in, maintenance, another
version), bad (it fails), skip (not tried: a step before it failed). Nothing is downloaded whole and nothing the launcher
keeps is changed. The last result is kept beside the settings (LAST), for the report (report.py).
"""

import json
import os
import socket
import ssl
import statistics
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from opendmtq_client import __version__, i18n
from opendmtq_client import server as srv
from opendmtq_client import state as st

# The steps in order (i18n test.<key> names them).
STEPS = ("address", "lookup", "port", "server", "version", "signin", "game", "broadcasts", "downloads", "round_trip")
# How long a connection to the port may take before it counts as no answer (seconds).
CONNECT_TIMEOUT = 5
# The ports a new server takes, the first free of them (host/opendmtq_host/settings.py choose_port): looked at when
# nothing answers on the address's own port.
PORTS = tuple(range(8791, 8800))
# What the server says of its app to a sign-in (server.app_info's refusals), as the sign-in step words it.
APP_SAID = {"error.app.none": "app_building", "error.app.stale": "app_rebuilding", "error.app.failed": "app_failed",
            "error.app.named": "app_named"}
# How long each of those ports may take to answer (seconds): looked at together, so the whole look takes about this.
PROBE_TIMEOUT = 2
# How many small asks the round trip times.
ROUND_TRIPS = 5
# The file of the last result, beside the settings: what the report includes.
LAST = "connection-test.json"


class Step:
    """One step: its state, what it found (an i18n.Said, said in either language), how long it took (ms, or None)."""

    def __init__(self, key):
        self.key, self.state, self.said, self.ms = key, "wait", None, None

    def done(self, state, key, ms=None, **values):
        """The step's outcome: its state and its words (test.<step>.<key>; test.skip for a step not tried)."""
        words = "test.skip" if key == "skip" else "test.%s.%s" % (self.key, key)
        self.state, self.said, self.ms = state, i18n.Said(words, **values), ms
        return self

    def view(self):
        """The step as the saved result keeps it: its words' key and values, all plain."""
        return {"key": self.key, "state": self.state, "ms": self.ms,
                "said": [self.said.key, {k: str(v) for k, v in self.said.params.items()}] if self.said else None}


class Result:
    """A test of one address: its steps in order, a server found on another port (moved), and when it was made."""

    def __init__(self, url, at=None):
        self.url, self.at = url, at or time.time()
        self.steps = [Step(key) for key in STEPS]
        self.moved = None
        self.ended = False

    def step(self, key):
        return next(s for s in self.steps if s.key == key)

    def failed(self):
        """True when a step failed: the command line's exit code 1."""
        return any(s.state == "bad" for s in self.steps)

    def verdict(self):
        """The one line over the steps: a server found on another port, the first step that failed, the first warning
        after "the server answers" (in its own words where the step's would say the server again: an older version, no
        sign-in, maintenance), or that everything answers."""
        if self.moved:
            # Found elsewhere when nothing answered at the address, or when another server answered there instead (the
            # port took the connection: its step got through).
            key = "test.verdict.moved_other" if self.step("port").state == "ok" else "test.verdict.moved"
            return i18n.Said(key, url=self.url, found=self.moved)
        for state in ("bad", "warn"):
            first = next((s for s in self.steps if s.state == state and s.said), None)
            if first is not None:
                # A warning with a verdict of its own (test.verdict.<step>.<outcome>), with the step's own values.
                own = "test.verdict." + first.said.key[len("test."):]
                if state == "warn" and own in i18n.TEXT:
                    return i18n.Said(own, **first.said.params)
                return i18n.Said("test.verdict.%s" % state, step=i18n.Said("test." + first.key), found=first.said)
        if not self.ended:
            return i18n.Said("test.verdict.running")
        return i18n.Said("test.verdict.ok")

    def text(self, words):
        """The whole result as lines of text in `words`' language: the address and when, the verdict, then a line a
        step (what Copy copies, and the report keeps)."""
        lines = [words("test.text.title", url=self.url, at=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.at))),
                 words.say(self.verdict())]
        width = max(len(words("test." + key)) for key in STEPS)
        for s in self.steps:
            found = words.say(s.said) if s.said else words("test.waiting")
            lines.append("[%s] %s  %s%s" % (s.state.ljust(4), words("test." + s.key).ljust(width), found,
                                           "  (%s)" % took(s.ms) if s.ms is not None else ""))
        return "\n".join(lines) + "\n"

    def view(self):
        return {"url": self.url, "at": self.at, "moved": self.moved, "ended": self.ended,
                "steps": [s.view() for s in self.steps]}


def took(ms):
    """How long a step took, as a person reads it: whole milliseconds, or seconds past one."""
    return "%d ms" % round(ms) if ms < 1000 else "%.1f s" % (ms / 1000.0)


def _ms(since):
    """Milliseconds from `since` (time.perf_counter) to now."""
    return (time.perf_counter() - since) * 1000.0


def save(result):
    """The last result kept beside the settings, whole or not at all (the report reads it)."""
    folder = st.config_dir()
    os.makedirs(folder, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=folder, prefix=".test-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(result.view(), f, ensure_ascii=False, indent=1)
    os.replace(temp, os.path.join(folder, LAST))


def last():
    """The last result kept (Result), or None."""
    try:
        with open(os.path.join(st.config_dir(), LAST), encoding="utf-8-sig") as f:
            kept = json.load(f)
        result = Result(str(kept["url"]), float(kept["at"]))
        result.moved, result.ended = kept.get("moved"), bool(kept.get("ended"))
        for step, view in zip(result.steps, kept["steps"]):
            step.state, step.ms = view["state"], view["ms"]
            if view.get("said"):
                step.said = i18n.Said(view["said"][0], **view["said"][1])
        return result
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None


def version_key(text):
    """A version's numbers to compare ("0.11.0-abc1234" -> (0, 11, 0)); () for one that names none."""
    core = (text or "").split("-", 1)[0].split("+", 1)[0]
    try:
        return tuple(int(part) for part in core.split("."))
    except ValueError:
        return ()


def run(address, server=None, report=None, cancel=None):
    """The test of `address` (as typed, or a known server's), `server` the launcher's entry for it (its sign-in) or None.
    report(step) is told each step as it ends (from this thread: the window hands it to its own). Returns the Result,
    also kept as the last one."""
    report = report or (lambda step: None)
    try:
        url = srv.normalize(address)
    except srv.ServerError:
        url = (address or "").strip()
    result = Result(url)

    def end(step):
        report(step)
        return step

    def stop(after):
        """Every step after `after` not tried."""
        for s in result.steps[STEPS.index(after) + 1:]:
            end(s.done("skip", "skip"))

    try:
        _steps(result, address, server, end, stop, cancel)
    finally:
        result.ended = True
        try:
            save(result)
        except OSError:
            # A folder that cannot be written: the result is still shown, only not kept for a report.
            pass
    return result


def _steps(result, address, server, end, stop, cancel):
    """The steps in order, each told as it ends; a step a later one needs and that failed stops them there."""
    # 1. The address as the launcher reads it.
    started = time.perf_counter()
    try:
        url = srv.normalize(address)
    except srv.ServerError as e:
        end(result.step("address").done("bad", "bad", _ms(started), error=e))
        return stop("address")
    parts = urllib.parse.urlsplit(url)
    host, port = srv.host_port(url)
    end(result.step("address").done("ok", "ok", _ms(started), url=url, scheme=parts.scheme, host=host, port=port))
    # 2. The name looked up.
    started = time.perf_counter()
    literal = _is_address(host)
    try:
        found = sorted({info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    except (socket.gaierror, UnicodeError) as e:
        end(result.step("lookup").done("bad", "bad", _ms(started), host=host, why=str(e)))
        return stop("lookup")
    if literal:
        end(result.step("lookup").done("ok", "literal", _ms(started), host=host))
    else:
        end(result.step("lookup").done("ok", "ok", _ms(started), host=host, addresses=", ".join(found[:4])))
    if cancel is not None and cancel.is_set():
        return stop("lookup")
    # 3. The port.
    started = time.perf_counter()
    answer, why = _connect(found, port)
    if answer != "open":
        moved = _moved(parts.scheme, host, port)
        result.moved = moved
        key = answer + ("_moved" if moved else "_none")
        end(result.step("port").done("bad", key, _ms(started), host=host, port=port, url=moved or "",
                                     first=PORTS[0], last=PORTS[-1], seconds=CONNECT_TIMEOUT, why=why))
        return stop("port")
    end(result.step("port").done("ok", "ok", _ms(started), host=host, port=port))
    # 4. The answer as an OpenDMTQ server, and over HTTPS whose certificate. Another program answering there (a web
    # server that took the port, one with a certificate this PC does not trust): the server looked for on the ports a
    # new server takes, as when nothing answers.
    started = time.perf_counter()
    trusted = None
    if parts.scheme == "https":
        trusted = _certificate(url, host, port)
        if isinstance(trusted, Exception):
            moved = _moved(parts.scheme, host, port)
            result.moved = moved
            end(result.step("server").done("bad", "certificate_moved" if moved else "certificate", _ms(started),
                                           why=_reason(trusted), url=moved or ""))
            return stop("server")
    try:
        about = srv.about(url, timeout=srv.TIMEOUT)
    except srv.ServerError as e:
        key = {"error.server.too_old": "too_old", "error.server.not_opendmtq": "not_opendmtq"}.get(e.key, "error")
        moved = _moved(parts.scheme, host, port) if key == "not_opendmtq" else None
        result.moved = moved
        end(result.step("server").done("bad", key + ("_moved" if moved else ""), _ms(started), error=e, url=moved or ""))
        return stop("server")
    over = {None: "", "windows": "https_windows", "own": "https_own"}[trusted]
    end(result.step("server").done("ok", "ok" + ("_" + over if over else ""), _ms(started), name=about["name"],
                                   version=about["opendmtq"] or "?"))
    # 5. Its version against this launcher's.
    theirs, mine = version_key(about["opendmtq"]), version_key(__version__)
    if not theirs:
        end(result.step("version").done("warn", "unknown", 0.0, launcher=__version__))
    elif theirs[:2] == mine[:2]:
        end(result.step("version").done("ok", "same", 0.0, version=about["opendmtq"]))
    else:
        end(result.step("version").done("warn", "newer" if theirs > mine else "older", 0.0, server=about["opendmtq"],
                                        launcher=__version__))
    # 6. The sign-in, still taken: the app's description, which only a sign-in gets (nothing changed here).
    started = time.perf_counter()
    cookie = None
    if server is None or not server.get("cookie") or int(server.get("expires") or 0) <= time.time():
        end(result.step("signin").done("warn", "none", 0.0))
    else:
        try:
            srv.app_info(url, server["cookie"])
            cookie = server["cookie"]
            end(result.step("signin").done("ok", "ok", _ms(started), account=server.get("account") or "?",
                                           until=time.strftime("%Y-%m-%d", time.localtime(server["expires"]))))
        except srv.SignedOut:
            end(result.step("signin").done("bad", "ended", _ms(started), account=server.get("account") or "?"))
        except srv.ServerError as e:
            # Signed in, and the server says something of its app instead (none yet, for another address): the sign-in
            # holds all the same. Said in the test's own words, what the server found and nothing more.
            cookie = server["cookie"]
            outcome = APP_SAID.get(getattr(e, "key", None))
            if outcome:
                end(result.step("signin").done("ok", outcome, _ms(started), account=server.get("account") or "?"))
            else:
                end(result.step("signin").done("ok", "ok_app", _ms(started), account=server.get("account") or "?", error=e))
    # 7. The game server's own answers: its health page (the client data, the database), and the maintenance check the
    # game makes at its start (/inspection/status.json: open_yn Y while the owner's notice is on).
    started = time.perf_counter()
    health = None
    try:
        status, health, _ = srv._call(url, "/opendmtq/health.php", timeout=srv.TIMEOUT)
    except srv.ServerError as e:
        status, health = None, e
    try:
        _, inspection, _ = srv._call(url, "/inspection/status.json", timeout=srv.TIMEOUT)
    except srv.ServerError:
        inspection = None
    maintenance = isinstance(inspection, dict) and (inspection.get("value") or {}).get("open_yn") == "Y"
    if isinstance(health, dict) and "patch" in health:
        patch = health.get("patch") or "?"
        if health.get("ok") and status == 200:
            end(result.step("game").done("warn" if maintenance else "ok", "maintenance" if maintenance else "ok",
                                         _ms(started), patch=patch))
        elif health.get("game_data") is False:
            # Without the client data the game cannot start: the server says so first.
            end(result.step("game").done("bad", "no_data", _ms(started)))
        elif health.get("database") is False:
            end(result.step("game").done("bad", "no_database", _ms(started)))
        elif health.get("writable") is False:
            end(result.step("game").done("bad", "read_only", _ms(started)))
        elif not health.get("host"):
            # The address the server's app is made for, not set yet: the server's setup has not given it one.
            end(result.step("game").done("bad", "no_host", _ms(started)))
        else:
            end(result.step("game").done("bad", "down", _ms(started), problem="HTTP %s" % status))
    else:
        end(result.step("game").done("bad", "no_answer", _ms(started), error=_reason(health) or status))
    # 8. The broadcast state, as the player asks it between songs (for nobody's number: no notice is taken).
    started = time.perf_counter()
    try:
        status, live, _ = srv._call(url, "/live/state?ids=0", timeout=srv.TIMEOUT)
    except srv.ServerError as e:
        status, live = None, e
    if isinstance(live, dict) and "broadcasts" in live:
        end(result.step("broadcasts").done("ok", "on" if live.get("broadcasts") else "off", _ms(started)))
    else:
        end(result.step("broadcasts").done("bad", "no_answer", _ms(started), error=_reason(live) or status))
    # 9. The downloads, by heads alone: the client data's list for the server's patch, and the app when signed in.
    started = time.perf_counter()
    patch = health.get("patch") if isinstance(health, dict) else None
    listing = _head(url, "/patch/phone_new/%s/android/patch_new.csv.lz4" % patch) if patch else (False, "no patch")
    app = _head(url, "/apk", cookie) if cookie else None
    if not listing[0]:
        end(result.step("downloads").done("bad", "bad_listing", _ms(started), error=listing[1]))
    elif app is not None and not app[0]:
        end(result.step("downloads").done("bad", "bad_app", _ms(started), error=app[1]))
    else:
        # The app only for a sign-in that holds: the sign-in's step says when there is none.
        end(result.step("downloads").done("ok", "ok" if app else "ok_no_app", _ms(started), app=i18n.mb(app[1] if app else 0),
                                          listing=max(1, round(listing[1] / 1024))))
    # 10. The round trip: a few small asks one after another.
    times = []
    for _ in range(ROUND_TRIPS):
        started = time.perf_counter()
        try:
            status, _, _ = srv._call(url, "/opendmtq/client.php?about", timeout=srv.TIMEOUT)
        except srv.ServerError:
            continue
        if status == 200:
            times.append(_ms(started))
    state, key, values = round_trip(times)
    end(result.step("round_trip").done(state, key, statistics.median(times) if times else None, **values))


def round_trip(times):
    """The round trip's outcome from the times of the requests answered (ms): (state, its words' key under
    test.round_trip, their values). Every ask answered ("all") or some ("ok", a warning), each with the median and the
    fastest and slowest, or one figure when those are one ("_same": never "1~1 ms"); none ("bad", with how many were
    asked: its words stand alone as the test's verdict)."""
    if not times:
        return "bad", "bad", {"of": ROUND_TRIPS}
    fast, slow = round(min(times)), round(max(times))
    every = len(times) == ROUND_TRIPS
    key = ("all" if every else "ok") + ("_same" if fast == slow else "")
    return ("ok" if every else "warn"), key, {"n": len(times), "of": ROUND_TRIPS, "median": round(statistics.median(times)),
                                              "fast": fast, "slow": slow}


def _is_address(host):
    """True for a host given as an address (IPv4 or IPv6), with nothing to look up."""
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(family, host)
            return True
        except (OSError, ValueError):
            continue
    return False


def _connect(addresses, port, timeout=CONNECT_TIMEOUT):
    """A TCP connection to the port at the first of the addresses that takes it: ("open", ""), else how the last one
    answered and the system's words for it: "refused", "timeout" (no answer in time) or "unreachable" (no way from this
    PC to it: no route, a network that is down; said at once, never as a wait)."""
    answer, why = "timeout", ""
    for address in addresses:
        try:
            with socket.create_connection((address, port), timeout=timeout):
                return "open", ""
        except ConnectionRefusedError:
            answer, why = "refused", ""
        except (socket.timeout, TimeoutError):
            answer, why = "timeout", ""
        except OSError as e:
            # Unreachable, or no route: its own words, as the system gives them.
            answer, why = "unreachable", str(e)[:160]
    return answer, why


def _old_authority(scheme, host, port):
    """The server's own authority as the launcher trusts it for this address (server.trust), however the address was
    written: with its port, or without it when it is the scheme's own; None when there is none."""
    shown = "[%s]" % host if ":" in host else host
    bases = ["%s://%s:%d" % (scheme, shown, port)]
    if port == (443 if scheme == "https" else 80):
        bases.append("%s://%s" % (scheme, shown))
    return next((ca for ca in map(srv.authority, bases) if ca), None)


def _moved(scheme, host, port):
    """The address of an OpenDMTQ server on the same host on one of PORTS (the address's own port aside), the lowest
    that answers as one, or None. The ports are asked together, each for PROBE_TIMEOUT. Over HTTPS each is checked with
    the authority trusted for the old address as well (the same server on another port of its host has the same
    certificates: one that moved keeps them)."""
    found = {}
    ca = _old_authority(scheme, host, port)

    def probe(candidate):
        url = "%s://%s:%d" % (scheme, "[%s]" % host if ":" in host else host, candidate)
        try:
            srv.about(url, timeout=PROBE_TIMEOUT, ca=ca)
            found[candidate] = url
        except srv.ServerError:
            pass

    threads = [threading.Thread(target=probe, args=(p,), daemon=True, name="probe-%d" % p) for p in PORTS if p != port]
    for thread in threads:
        thread.start()
    for thread in threads:
        # The connection's own limit, and the answer's, and a little room: none takes longer.
        thread.join(PROBE_TIMEOUT * 2 + 1)
    return found[min(found)] if found else None


def _certificate(url, host, port):
    """Whose certificate the HTTPS answers with: "windows" (one Windows' authorities vouch for), "own" (the server's own
    authority, trusted for this server alone: server.trust), or the error of a certificate neither vouches for."""
    error = None
    own = srv._trusted().get(url)
    for kind, ca in (("windows", None), ("own", own)):
        if kind == "own" and not own:
            break
        context = ssl.create_default_context()
        try:
            if ca:
                context.load_verify_locations(cadata=ca)
            with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT) as raw:
                with context.wrap_socket(raw, server_hostname=host):
                    return kind
        except (ssl.SSLError, ssl.CertificateError, OSError, ValueError) as e:
            error = e
    return error


def _head(url, path, cookie=None):
    """A HEAD of a download: (True, its length in bytes), or (False, why not: its status, or the error). Nothing is
    downloaded. The app's answers a page instead of the app for a sign-in that ended (its type says so)."""
    request = srv._request(url + path, cookie=cookie)
    request.method = "HEAD"
    try:
        # Its answer whole within the wait, however it trickles in (server.within), as every other step's.
        with srv.within(srv.TIMEOUT), srv._opener(url).open(request, timeout=srv.TIMEOUT) as response:
            kind = (response.headers.get("Content-Type") or "").split(";")[0].strip()
            if path == "/apk" and kind != "application/vnd.android.package-archive":
                return False, "not the app (%s)" % (kind or "no type")
            return True, int(response.headers.get("Content-Length") or 0)
    except urllib.error.HTTPError as e:
        return False, "HTTP %d" % e.code
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, _reason(e)


def _reason(error):
    """What an error says, in a few words, for a step's line."""
    if error is None:
        return ""
    if isinstance(error, int):
        return "HTTP %d" % error
    reason = getattr(error, "reason", None) or getattr(error, "verify_message", None) or error
    return str(reason)[:160]
