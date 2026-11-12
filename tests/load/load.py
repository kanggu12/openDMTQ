"""Players sharing one server: whether what one of them does reaches the others' plays.

Run by tests/load/run.sh against a throwaway server it starts on two processor cores. Five rounds:

  capacity   PLAYERS phones saving plays back to back, nothing else: how many saves two cores answer, and how fast (the
             README's chart measures the same).
  quiet      PLAYERS players playing: a song's start (its preview and its chart's address), the song (SONG_S seconds),
             the save, and the result screen's two rankings.
  flood      the same players while one address saves as fast as it can over FLOOD connections at once (the most the
             edge lets one address hold): a broken or hostile client.
  broadcast  the same players while BROADCASTERS players broadcast (a SEGMENT_KB segment every two seconds) and VIEWERS
             browsers watch them on the site (the list of who is on, the playlist and the newest segment, every 2.5 s).
  heavy      the same players while HEAVY_CMD runs (run.sh: a backup and a build of the app on the same two cores).
  crash      the players saving back to back while the server is killed and started again (CRASH_CMD).
  full disk  a second server whose database's disk fills up (FULL_SITE and its commands).

Each round lasts PHASE_S seconds, the heavy one until its work is done if that is later; MEM_CMD's samples give the
server's most memory in each. Every save of the players is counted: stored, refused (the client then offers to retry), an
HTTP error, or no answer within TIMEOUT_S. The test passes when none of the players' saves fails in any of the first
rounds, every segment of the broadcasts is taken, every look at the list of who is on is answered, and the heavy work
ends well; after the kill nothing answered as stored is gone, the database is whole and saves are stored again; on the
full disk each save is refused with the retry code and nothing of it kept, the server answers, and with room again saves
are stored. The times are printed for each round.

Usage: python3 tests/load/load.py SITE_URL                      the rounds
       python3 tests/load/load.py SITE_URL seed COUNT FILE      COUNT players through the game's logins: "guid udid" lines
       python3 tests/load/load.py SITE_URL requests             the game's requests one kind at a time, as the README's
                                                                chart shows them (docs/testing.md, Measurements)
Environment: PLAYERS (8), PHASE_S (60), SONG_S (3), FLOOD (24), BROADCASTERS (2), VIEWERS (30), SEGMENT_KB (500),
TIMEOUT_S (15), SEEDED (the seed step's file, at least PLAYERS + 1 + BROADCASTERS players), VIEWER (ID:password of a
site account), REQUEST_S (6, each kind's seconds in the requests mode), HEAVY_CMD, MEM_CMD, CRASH_CMD, CHECK_CMD, FULL_SITE, FULL_FILL_CMD, FULL_FREE_CMD, FULL_CHECK_CMD (run.sh
sets them), OUT (a folder for results.json).
"""

import hashlib
import http.client
import http.cookiejar
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# The server under test, from the command line.
SITE = sys.argv[1].rstrip("/")
# Its host and port, for the connections opened by hand below.
PARTS = urllib.parse.urlsplit(SITE)
# How many players play at once (and how many phones save back to back in the capacity round).
PLAYERS = int(os.environ.get("PLAYERS", "8"))
# How long each round lasts.
PHASE_S = float(os.environ.get("PHASE_S", "60"))
# How long a song lasts here: shorter than a real one, so each player saves more often than on a real evening.
SONG_S = float(os.environ.get("SONG_S", "3"))
# How many connections the flooding address holds at once: the edge lets one address hold 24 (server/edge/nginx.conf).
FLOOD = int(os.environ.get("FLOOD", "24"))
# How many players broadcast in the broadcast round, how many browsers watch, and each segment's size (two seconds of
# 720p at 2 Mbit/s are about 500 KB).
BROADCASTERS = int(os.environ.get("BROADCASTERS", "2"))
VIEWERS = int(os.environ.get("VIEWERS", "30"))
SEGMENT_KB = int(os.environ.get("SEGMENT_KB", "500"))
# How long a request may take before it counts as unanswered.
TIMEOUT_S = float(os.environ.get("TIMEOUT_S", "15"))
# How long each kind of request is sent in the requests mode.
REQUEST_S = float(os.environ.get("REQUEST_S", "6"))
# Where results.json goes, if anywhere.
OUT = os.environ.get("OUT", "")
# What run.sh gives for the rounds that reach past HTTP: a command printing the server's memory in use (Docker's own
# figure), one that kills the server and starts it again until it answers, one printing its database's integrity check;
# a second server whose database's disk is small, with commands that fill that disk, free it and check its database.
MEM_CMD = os.environ.get("MEM_CMD", "")
CRASH_CMD = os.environ.get("CRASH_CMD", "")
CHECK_CMD = os.environ.get("CHECK_CMD", "")
FULL_SITE = os.environ.get("FULL_SITE", "").rstrip("/")
FULL_FILL_CMD = os.environ.get("FULL_FILL_CMD", "")
FULL_FREE_CMD = os.environ.get("FULL_FREE_CMD", "")
FULL_CHECK_CMD = os.environ.get("FULL_CHECK_CMD", "")
# The game's signing key: the same in every copy of the game, so any client can sign (docs/architecture.md).
KEY = b"DMQGLBlive1"


class Conn:
    """One kept connection to the server (or to `base`, another one), as a phone keeps one, opened again when the server
    closes it."""

    def __init__(self, base=None):
        # Not opened until the first request.
        self.c = None
        # Where it goes: the server under test unless another is named.
        self.parts = urllib.parse.urlsplit(base) if base else PARTS

    def send(self, method, path, body=None, headers=None):
        """(HTTP status, body) of one request; raises when no answer comes within TIMEOUT_S."""
        # Two tries: the server closes a kept connection after two idle seconds, which a request may meet.
        for attempt in (1, 2):
            # A fresh connection when there is none.
            if self.c is None:
                self.c = http.client.HTTPConnection(self.parts.hostname, self.parts.port, timeout=TIMEOUT_S)
            try:
                # The request, read whole so the connection can carry the next one.
                self.c.request(method, path, body, headers or {})
                r = self.c.getresponse()
                return r.status, r.read()
            except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError):
                # The server had closed the kept connection: another one and the request again, once.
                self.c.close()
                self.c = None
                if attempt == 2:
                    raise
            except Exception:
                # Anything else (above all a timeout) is an answer that never came: a new connection next time.
                self.c.close()
                self.c = None
                raise

    def post(self, path, body, headers):
        return self.send("POST", path, body, headers)


def rpc(conn, method, params):
    """(HTTP status, the call's reply or None, seconds taken) of one signed game call over `conn`."""
    # One call in a batch, as the game sends its calls.
    body = json.dumps([{"id": 1, "method": method, "params": params}]).encode()
    # Signed as the game signs every request.
    headers = {"Content-Type": "application/json", "Fp": hashlib.md5(KEY + body).hexdigest()}
    # Timed from sending to the whole reply read.
    t0 = time.perf_counter()
    status, raw = conn.post("/DMQ/rpc", body, headers)
    took = time.perf_counter() - t0
    # The first reply of the batch, when there is one.
    reply = json.loads(raw)[0] if status == 200 and raw.startswith(b"[{") else None
    return status, reply, took


def new_player(udid, base=None):
    """A player made through the game's own two logins (on `base`, another server, when named): their guid."""
    conn = Conn(base)
    # The platform login, which trusts the device id it is given.
    _, raw = conn.post("/api/accounts/v3/global/login_dmq", urllib.parse.urlencode({"udid": udid}).encode(),
                       {"Content-Type": "application/x-www-form-urlencoded"})
    token = json.loads(raw)["value"]["access_token"]
    # The game login, which gives the player's guid.
    _, reply, _ = rpc(conn, "user.loginV2", [token, " ", "", "1.3.5", "ANDROID", "KR"])
    return int(reply["result"]["guid"])


def stats():
    """A result's 13 judgement counters for 600 notes, a little different each time."""
    s = [0] * 13
    # Index 1 counts breaks, 12 perfects, the ones between the other judgements.
    s[1] = random.randint(0, 20)
    s[12] = random.randint(400, 560)
    s[random.randint(5, 11)] = 600 - s[1] - s[12]
    return s


def save(conn, guid, pattern):
    """One save of a play, signed, as the game sends it: (HTTP status, reply, seconds)."""
    s = stats()
    return rpc(conn, "game.savePlayResult", [guid, pattern, s, sum(s[2:]), 0, [0, 0, 0], [0, 0, 0], "load"])


def outcome(status, reply):
    """What a save came to: stored, refused (with the error's code), or an HTTP error."""
    if status != 200:
        return f"http {status}"
    if reply is None:
        return "no reply in the batch"
    # SVC.05099 is the server's "not saved", after which the client offers to retry.
    if reply.get("error"):
        return "refused " + str(reply["error"].get("code"))
    return "stored"


def answered(st, r):
    """How a game call other than a save ended, for its tally."""
    if st != 200:
        return f"http {st}"
    return "answered" if r is not None and not r.get("error") else "error"


class Tally:
    """What one kind of request came to in one round, added to by every thread at once."""

    def __init__(self):
        self.lock = threading.Lock()
        # Seconds of the answered requests.
        self.times = []
        # How many ended each way ("stored", "refused SVC.05099", "http 503", "no answer").
        self.ends = {}

    def add(self, end, took=None):
        with self.lock:
            self.ends[end] = self.ends.get(end, 0) + 1
            # Unanswered requests have no time.
            if took is not None:
                self.times.append(took)

    def summary(self, seconds):
        """Count, rate, ends, and the answers' 50th, 95th and 99th percentiles and the slowest, in milliseconds."""
        t = sorted(self.times)

        def pct(q):
            # Nearest rank: the value at or above the q-th share of the answers.
            return round(t[min(len(t) - 1, int(q * len(t)))] * 1000, 1) if t else None

        n = sum(self.ends.values())
        return {"n": n, "per_s": round(n / seconds, 1), "ends": dict(sorted(self.ends.items())), "p50_ms": pct(0.50),
                "p95_ms": pct(0.95), "p99_ms": pct(0.99), "max_ms": round(t[-1] * 1000, 1) if t else None}


def player(guid, charts, stop, tally):
    """One player playing until `stop` is set: a song's start, the song, the save, the result screen; each timed."""
    conn = Conn()
    # Each player starts at a different moment, as people do.
    time.sleep(random.uniform(0, SONG_S))
    while not stop.is_set():
        # A song and one of its charts, as the player picks one.
        song, line, pattern = random.choice(charts)
        try:
            # The song's start: its preview and its chart's address.
            st, r, took = rpc(conn, "game.getPreviewPlayInfo", [guid, song])
            tally["start"].add(answered(st, r), took)
            st, r, took = rpc(conn, "game.getPatternUrl", [guid, pattern, "", "P"])
            tally["start"].add(answered(st, r), took)
        except Exception:
            tally["start"].add("no answer")
        # The song itself, a little longer or shorter each time.
        time.sleep(SONG_S * random.uniform(0.8, 1.2))
        try:
            # The save at the end of the song: what this test is about.
            st, r, took = save(conn, guid, pattern)
            tally["save"].add(outcome(st, r), took)
        except Exception:
            tally["save"].add("no answer")
        try:
            # The result screen: the player's own rank on the song's line, then the top of it.
            st, r, took = rpc(conn, "game.getLineScoreMyRankWithLevel", [guid, song, line])
            tally["ranking"].add(answered(st, r), took)
            st, r, took = rpc(conn, "game.getLineScoreRangeWithLevel", [song, line, 1, 50])
            tally["ranking"].add(answered(st, r), took)
        except Exception:
            tally["ranking"].add("no answer")


def saver(guid, charts, stop, tally):
    """Saves back to back over one kept connection until `stop` is set: the capacity round's phones, and the flood."""
    conn = Conn()
    while not stop.is_set():
        pattern = random.choice(charts)[2]
        try:
            st, r, took = save(conn, guid, pattern)
            tally.add(outcome(st, r), took)
        except Exception:
            tally.add("no answer")


def ts_segment(seq, size):
    """A segment the upload takes for video: MPEG-TS packets (the sync byte, a counter, filler), `size` bytes."""
    packet = bytes([0x47, seq % 256]) + bytes(186)
    return (packet * (size // 188 + 1))[: size - size % 188]


def broadcaster(guid, udid, charts, stop, tally):
    """One player broadcasting until `stop` is set: in a song, a segment every two seconds, as the phone's encoder sends
    them; the broadcast ended at the round's end."""
    conn = Conn()
    # In a song: the live view shows a player who opened a play (server/game/src/live.php).
    song, _, pattern = random.choice(charts)
    rpc(conn, "game.getPreviewPlayInfo", [guid, song])
    # The broadcast's token, as the phone asks for it with its device id.
    ids = urllib.parse.quote(udid)
    st, raw = conn.send("GET", f"/live/state?ids={ids}&lang=en")
    token = json.loads(raw).get("token") if st == 200 else None
    if not token:
        tally["upload"].add(f"no token (http {st})")
        return
    seq, next_at = 0, time.time()
    while not stop.is_set():
        # One segment, timed, then the next one two seconds after this one was due.
        t0 = time.perf_counter()
        try:
            st, _ = conn.post(f"/live/upload?ids={ids}&seq={seq}&dur=2000", ts_segment(seq, SEGMENT_KB * 1024),
                              {"Content-Type": "video/mp2t", "X-Live-Token": token})
            tally["upload"].add("taken" if st == 204 else f"http {st}", time.perf_counter() - t0)
        except Exception:
            tally["upload"].add("no answer")
        seq += 1
        next_at += 2
        time.sleep(max(0.0, next_at - time.time()))
    # The end of the broadcast, as the phone sends it.
    try:
        conn.post(f"/live/end?ids={ids}", b"", {"X-Live-Token": token})
    except Exception:
        pass


def viewer(account, stop, tally):
    """One browser watching the site's live page until `stop` is set: who is on, then each one's playlist and newest
    segment, every 2.5 seconds, signed in with the site account `account` (ID, password)."""
    jar = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(path):
        """(HTTP status, body, seconds) of one GET in this browser."""
        t0 = time.perf_counter()
        try:
            with jar.open(SITE + path, timeout=TIMEOUT_S) as r:
                return r.status, r.read(), time.perf_counter() - t0
        except urllib.error.HTTPError as e:
            return e.code, e.read(), time.perf_counter() - t0

    # People open the page at different moments within the first seconds.
    time.sleep(random.uniform(0, 5))
    # Signed in as the site's form signs in; in when the list of who is on then answers as JSON.
    form = urllib.parse.urlencode({"user": account[0], "password": account[1], "next": "/opendmtq/live.php"}).encode()
    try:
        jar.open(urllib.request.Request(SITE + "/opendmtq/login.php", form), timeout=TIMEOUT_S).read()
        st, body, _ = get("/opendmtq/live.php?list=1")
        json.loads(body)
        tally["signin"].add("signed in")
    except Exception:
        tally["signin"].add("not signed in")
        return
    while not stop.is_set():
        t_next = time.time() + 2.5
        try:
            st, body, took = get("/opendmtq/live.php?list=1")
            cards = json.loads(body).get("live", []) if st == 200 else []
            tally["list"].add("answered" if st == 200 else f"http {st}", took)
            for card in cards:
                # The playlist of the card's player, then its newest segment, as the page's player fetches them.
                st, body, took = get(f"/opendmtq/live-media.php/{card['id']}/index.m3u8")
                tally["media"].add("answered" if st == 200 else f"http {st}", took)
                names = [ln for ln in body.decode(errors="replace").splitlines() if ln and not ln.startswith("#")]
                if st == 200 and names:
                    st, _, took = get(f"/opendmtq/live-media.php/{card['id']}/{names[-1].rsplit('/', 1)[-1]}")
                    tally["media"].add("answered" if st == 200 else f"http {st}", took)
        except Exception:
            tally["list"].add("no answer")
        time.sleep(max(0.0, t_next - time.time()))


def run_round(name, charts, players=(), savers=(), flood_guid=None, broadcasters=(), viewers=0, account=None,
              heavy_cmd=None):
    """One round with the given players, back-to-back savers, flood, broadcasts and heavy work: its tallies, printed."""
    stop = threading.Event()
    kinds = ("start", "save", "ranking", "capacity", "flood", "upload", "signin", "list", "media")
    tally = {k: Tally() for k in kinds}
    threads = [threading.Thread(target=player, args=(g, charts, stop, tally)) for g in players]
    threads += [threading.Thread(target=saver, args=(g, charts, stop, tally["capacity"])) for g in savers]
    if flood_guid is not None:
        # The flooding address: one player, every connection the edge would let one address hold.
        threads += [threading.Thread(target=saver, args=(flood_guid, charts, stop, tally["flood"])) for _ in range(FLOOD)]
    threads += [threading.Thread(target=broadcaster, args=(g, u, charts, stop, tally)) for g, u in broadcasters]
    threads += [threading.Thread(target=viewer, args=(account, stop, tally)) for _ in range(viewers)]
    t0 = time.time()
    for t in threads:
        t.start()
    # The server's memory through the round, sampled beside it.
    memory_stop, peak = threading.Event(), [0.0]
    memory = threading.Thread(target=sampler, args=(memory_stop, peak))
    if MEM_CMD:
        memory.start()
    heavy = None
    if heavy_cmd:
        # The heavy work starts once the players are under way; its own time and end are kept.
        time.sleep(min(5.0, PHASE_S / 4))
        h0 = time.time()
        p = subprocess.run(heavy_cmd, shell=True, capture_output=True, text=True)
        heavy = {"seconds": round(time.time() - h0, 1), "exit": p.returncode, "tail": (p.stdout + p.stderr)[-600:]}
    # The round ends after PHASE_S, or when the heavy work ends if that is later.
    time.sleep(max(0.0, t0 + PHASE_S - time.time()))
    stop.set()
    for t in threads:
        t.join()
    seconds = time.time() - t0
    out = {k: v.summary(seconds) for k, v in tally.items() if v.ends}
    if heavy:
        out["heavy work"] = heavy
    if MEM_CMD:
        memory_stop.set()
        memory.join()
        out["server memory"] = {"peak_mib": peak[0]}
    print(f"== {name} ({seconds:.0f} s)")
    for k, v in out.items():
        print(f"  {k}: {json.dumps(v)}")
    sys.stdout.flush()
    return out


def mib(text):
    """Docker's "123.4MiB / 2GiB" as MiB, from the part before the slash; None when it says nothing that reads so."""
    found = re.match(r"\s*([\d.]+)\s*(B|kB|KiB|MB|MiB|GB|GiB)\b", text or "")
    if not found:
        return None
    # Docker's own units, decimal and binary, each as MiB.
    per = {"B": 1 / 2**20, "kB": 1000 / 2**20, "KiB": 1 / 1024, "MB": 10**6 / 2**20, "MiB": 1, "GB": 10**9 / 2**20, "GiB": 1024}
    return round(float(found.group(1)) * per[found.group(2)], 1)


def sampler(stop, peak):
    """The server's memory (MEM_CMD) about every second until `stop` is set: the most seen, in MiB, kept in peak[0]."""
    while not stop.is_set():
        try:
            got = mib(subprocess.run(MEM_CMD, shell=True, capture_output=True, text=True, timeout=10).stdout)
            if got is not None:
                peak[0] = max(peak[0], got)
        except Exception:
            # A sample missed (the command slow or gone for a moment): the next one counts.
            pass
        stop.wait(1)


def crash_round(players, charts):
    """The server killed (SIGKILL, as a crash or an out-of-memory kill would end it) while the players save back to back,
    then started again (CRASH_CMD, which returns once it answers): every save it answered as stored must still be there,
    its database whole (CHECK_CMD), and saves stored again once it answers. Returns its figures, printed too."""
    stop, lock = threading.Event(), threading.Lock()
    # (guid, chart) -> the best score the server answered as stored for it.
    told = {}
    # Before the kill, while it is down and once it answers again.
    phase = ["before"]
    tally = {k: Tally() for k in ("before", "down", "after")}

    def keep_saving(guid):
        conn = Conn()
        while not stop.is_set():
            pattern = random.choice(charts)[2]
            # The phase it was sent in, which the answer counts for.
            when = phase[0]
            try:
                st, r, took = save(conn, guid, pattern)
                end = outcome(st, r)
                tally[when].add(end, took)
                if end == "stored":
                    with lock:
                        told[(guid, pattern)] = max(told.get((guid, pattern), 0), int(r["result"]["score"]))
            except Exception:
                tally[when].add("no answer")
                # Not a busy loop against a server that is down.
                time.sleep(0.2)

    threads = [threading.Thread(target=keep_saving, args=(g,)) for g in players]
    t0 = time.time()
    for t in threads:
        t.start()
    time.sleep(5)
    phase[0] = "down"
    k0 = time.time()
    p = subprocess.run(CRASH_CMD, shell=True, capture_output=True, text=True)
    back = round(time.time() - k0, 1)
    phase[0] = "after"
    time.sleep(5)
    stop.set()
    for t in threads:
        t.join()
    seconds = time.time() - t0
    # What each player was told against what the server has now, through the game's own request for a player's bests.
    wanted = {}
    for (g, pattern), score in told.items():
        wanted.setdefault(g, {})[pattern] = score
    lost, conn = [], Conn()
    for g, charts_told in wanted.items():
        _, r, _ = rpc(conn, "game.getOwnPatternScore", [g])
        have = {int(row["pattern_id"]): int(row["score"]) for row in ((r or {}).get("result") or [])}
        lost += [(g, pt, s, have.get(pt)) for pt, s in charts_told.items() if have.get(pt, -1) < s]
    integrity = subprocess.run(CHECK_CMD, shell=True, capture_output=True, text=True).stdout.strip() if CHECK_CMD else ""
    out = {k: v.summary(seconds) for k, v in tally.items() if v.ends}
    out["restart"] = {"seconds": back, "exit": p.returncode, "tail": (p.stdout + p.stderr)[-300:]}
    out["stored and told"] = len(told)
    out["lost"] = lost[:5] + ([f"and {len(lost) - 5} more"] if len(lost) > 5 else [])
    out["integrity"] = integrity
    print(f"== crash ({seconds:.0f} s)")
    for k, v in out.items():
        print(f"  {k}: {json.dumps(v)}")
    sys.stdout.flush()
    return out


def full_round():
    """A second server whose database's disk is small (FULL_SITE): a player's saves stored; the disk filled to its last
    byte (FULL_FILL_CMD); the saves then refused with the code after which the client offers to retry, nothing of them
    kept, the server answering its other requests; room again (FULL_FREE_CMD) and the saves stored; the database whole
    after (FULL_CHECK_CMD). Returns its figures, printed too."""
    conn = Conn(FULL_SITE)
    _, reply, _ = rpc(conn, "game.getSongList", [])
    charts = [p["pattern_id"] for s in reply["result"]["songs"] for p in s["song_patterns"]]
    guid = new_player(f"load-full-{random.randrange(10**9)}", FULL_SITE)

    def saves(n):
        """How n saves of the player ended, each on a chart of its own (none of them earlier on this server)."""
        ends = {}
        for _ in range(n):
            try:
                st, r, _ = save(conn, guid, charts.pop(random.randrange(len(charts))))
                end = outcome(st, r)
            except Exception:
                end = "no answer"
            ends[end] = ends.get(end, 0) + 1
        return ends

    out = {"before": saves(3)}
    fill = subprocess.run(FULL_FILL_CMD, shell=True, capture_output=True, text=True)
    out["filled"] = (fill.stdout + fill.stderr).strip()[-200:]
    out["full"] = saves(10)
    # The rest of the game's requests while the disk is full: its song list and the player's bests.
    st, r, _ = rpc(conn, "game.getSongList", [])
    st2, r2, _ = rpc(conn, "game.getOwnPatternScore", [guid])
    out["answers while full"] = st == 200 and r is not None and st2 == 200 and r2 is not None
    # What the full disk kept: the three saves from before, nothing of the ten.
    out["rows while full"] = len((r2 or {}).get("result") or [])
    subprocess.run(FULL_FREE_CMD, shell=True, capture_output=True, text=True)
    out["after"] = saves(3)
    out["integrity"] = subprocess.run(FULL_CHECK_CMD, shell=True, capture_output=True, text=True).stdout.strip()
    print("== full disk")
    for k, v in out.items():
        print(f"  {k}: {json.dumps(v)}")
    sys.stdout.flush()
    return out


def requests_round(made, charts):
    """The game's requests one kind at a time, as the README's chart shows them: PLAYERS phones, each a player of its
    own, send one kind back to back for REQUEST_S seconds. Returns {kind: {n, per_s, p50_ms, p95_ms, ends}}, printed
    too, and how long the first look at the ranking of every chart takes after a play (that board is kept until the next
    play, so the looks of a round with no play in it all read what the first one kept)."""
    players = made[:PLAYERS]

    def token_of(udid):
        # The platform login's token, which the game login takes.
        _, raw = Conn().post("/api/accounts/v3/global/login_dmq", urllib.parse.urlencode({"udid": udid}).encode(),
                             {"Content-Type": "application/x-www-form-urlencoded"})
        return json.loads(raw)["value"]["access_token"]

    tokens = {g: token_of(u) for g, u in players}

    def login(conn, g):
        st, r, took = rpc(conn, "user.loginV2", [tokens[g], " ", "", "1.3.5", "ANDROID", "KR"])
        return answered(st, r), took

    def song_list(conn, g):
        st, r, took = rpc(conn, "game.getSongList", [])
        return answered(st, r), took

    def save_a_play(conn, g):
        # The game's two requests at a song's end: the result, then the player's rank on the song.
        song, line, pattern = random.choice(charts)
        st, r, took = save(conn, g, pattern)
        st2, r2, took2 = rpc(conn, "game.getLineScoreMyRankWithNext", [g, song, line])
        end = outcome(st, r)
        return (end if end != "stored" else answered(st2, r2)), took + took2

    def every_chart(conn, g):
        st, r, took = rpc(conn, "game.getLineTopRankWithLevel", [0, 1, 50, [g]])
        return answered(st, r), took

    def one_song(conn, g):
        song, line, _ = random.choice(charts)
        st, r, took = rpc(conn, "game.getLineScoreRangeWithLevel", [song, line, 1, 50])
        return answered(st, r), took

    out = {}
    for name, one in (("login", login), ("song list", song_list), ("save a play", save_a_play),
                      ("ranking, all charts", every_chart), ("ranking, one song", one_song)):
        stop, tally = threading.Event(), Tally()

        def phone(g, one=one, stop=stop, tally=tally):
            # One phone: this kind of request back to back over one kept connection.
            conn = Conn()
            while not stop.is_set():
                try:
                    end, took = one(conn, g)
                    tally.add(end, took)
                except Exception:
                    tally.add("no answer")

        threads = [threading.Thread(target=phone, args=(g,)) for g, _ in players]
        t0 = time.time()
        for t in threads:
            t.start()
        time.sleep(REQUEST_S)
        stop.set()
        for t in threads:
            t.join()
        s = tally.summary(time.time() - t0)
        out[name] = {"n": s["n"], "per_s": s["per_s"], "p50_ms": s["p50_ms"], "p95_ms": s["p95_ms"], "ends": s["ends"]}
        print(f"  {name}: {json.dumps(out[name])}")
        sys.stdout.flush()
    # The first look at the ranking of every chart after a play: ten plays, each followed by one look.
    conn, g = Conn(), players[0][0]
    first = []
    for _ in range(10):
        save(conn, g, random.choice(charts)[2])
        first.append(rpc(conn, "game.getLineTopRankWithLevel", [0, 1, 50, [g]])[2])
    out["ranking, all charts, first look after a play"] = {"p50_ms": round(sorted(first)[5] * 1000, 1)}
    print(f"  ranking, all charts, first look after a play: {json.dumps(out['ranking, all charts, first look after a play'])}")
    return out


def seed(count, path):
    """`count` players made through the game's own logins, eight at a time: "guid udid" lines in `path`."""
    from concurrent.futures import ThreadPoolExecutor

    def make(i):
        # Each a device id of its own, as each phone has.
        udid = f"load-{i}-{random.randrange(10**9)}"
        return new_player(udid), udid

    with ThreadPoolExecutor(8) as pool:
        made = list(pool.map(make, range(count)))
    with open(path, "w") as f:
        f.write("".join(f"{g} {u}\n" for g, u in made))
    print(f"players made: {len(made)}")
    return 0


def main():
    # run.sh asks for the players first: `load.py SITE seed COUNT FILE`.
    if len(sys.argv) > 2 and sys.argv[2] == "seed":
        return seed(int(sys.argv[3]), sys.argv[4])
    random.seed(11)
    # Every chart of the server's songs: (song, its line, the chart), from the game's own song list.
    _, reply, _ = rpc(Conn(), "game.getSongList", [])
    charts = [(s["song_id"], p["line"], p["pattern_id"]) for s in reply["result"]["songs"] for p in s["song_patterns"]]
    # The players: the seed step's, or new ones.
    seeded = os.environ.get("SEEDED")
    need = PLAYERS + 1 + BROADCASTERS
    if seeded:
        with open(seeded) as f:
            made = [(int(ln.split()[0]), ln.split()[1]) for ln in f if ln.strip()][:need]
    else:
        made = []
        for i in range(need):
            udid = f"load-{i}-{random.randrange(10**9)}"
            made.append((new_player(udid), udid))
    # The requests mode: each kind on its own, with these players, and nothing else.
    if len(sys.argv) > 2 and sys.argv[2] == "requests":
        print(f"players {PLAYERS}, charts {len(charts)}, {REQUEST_S:.0f} s a kind")
        kinds = requests_round(made, charts)
        if OUT:
            with open(os.path.join(OUT, "requests.json"), "w") as f:
                json.dump(kinds, f, indent=2)
        # Every request answered (a save stored), or the figures are of something else.
        wrong = {k: v["ends"] for k, v in kinds.items() if "ends" in v and set(v["ends"]) - {"answered", "stored"}}
        print("FAIL some requests were not answered: " + json.dumps(wrong) if wrong else "PASS every request of every kind answered")
        return 1 if wrong else 0
    players = [g for g, _ in made[:PLAYERS]]
    flooder = made[PLAYERS][0]
    casters = made[PLAYERS + 1:need]
    # The site account the viewers sign in with (run.sh makes it), as "ID:password".
    account = tuple(os.environ.get("VIEWER", "viewer:viewer-password").split(":", 1))
    print(f"players {len(players)}, charts {len(charts)}, rounds of {PHASE_S:.0f} s")
    results = {
        "capacity": run_round("capacity", charts, savers=players),
        "quiet": run_round("quiet", charts, players=players),
        "flood": run_round("flood", charts, players=players, flood_guid=flooder),
        "broadcast": run_round("broadcast", charts, players=players, broadcasters=casters, viewers=VIEWERS, account=account),
        "heavy": run_round("heavy", charts, players=players, heavy_cmd=os.environ.get("HEAVY_CMD")),
    }
    # The server killed and started again, then a full disk: when run.sh gives the commands for them.
    if CRASH_CMD:
        results["crash"] = crash_round(players, charts)
    if FULL_SITE:
        results["full"] = full_round()
    if OUT:
        with open(os.path.join(OUT, "results.json"), "w") as f:
            json.dump(results, f, indent=2)
    bad = 0

    def verdict(ok, text):
        nonlocal bad
        bad += 0 if ok else 1
        print(("PASS " if ok else "FAIL ") + text)

    # Every save of the players stored, in every round with players.
    for name in ("quiet", "flood", "broadcast", "heavy"):
        ends = results[name].get("save", {}).get("ends", {})
        stored = ends.get("stored", 0)
        failed = sum(n for end, n in ends.items() if end != "stored")
        verdict(stored and not failed, f"{name}: the players' saves: {stored} stored, {failed} not {ends if failed else ''}".rstrip())
    # Every segment of the broadcasts taken, every look at who is on answered.
    up = results["broadcast"].get("upload", {}).get("ends", {})
    verdict(up.get("taken", 0) and len(up) == 1, f"broadcast: segments {up}")
    signins = results["broadcast"].get("signin", {}).get("ends", {})
    verdict(signins.get("signed in", 0) == VIEWERS, f"broadcast: the viewers' sign-ins {signins}")
    looks = results["broadcast"].get("list", {}).get("ends", {})
    verdict(looks.get("answered", 0) and len(looks) == 1, f"broadcast: the viewers' looks at who is on {looks}")
    # A heavy round whose work failed measured nothing heavy.
    hw = results["heavy"].get("heavy work")
    verdict(hw is None or hw["exit"] == 0, f"heavy: its work {'ended well' if not hw or hw['exit'] == 0 else hw['tail']}")
    # Killed mid-save and started again: nothing it said it stored is gone, the database whole, saves stored again.
    crash = results.get("crash")
    if crash:
        verdict(crash["restart"]["exit"] == 0, f"crash: the server answers again {crash['restart']['seconds']} s after the kill")
        verdict(crash["stored and told"] > 0 and not crash["lost"],
                f"crash: every save answered as stored is still there ({crash['stored and told']}; lost {crash['lost']})")
        verdict(crash["integrity"] == "ok", f"crash: the database is whole after the kill ({crash['integrity']})")
        after = crash.get("after", {}).get("ends", {})
        verdict(after.get("stored", 0) > 0, f"crash: saves are stored again once it answers {after}")
    # A full disk: refused with the retry code and nothing kept, the server answering; room again and they are stored.
    full = results.get("full")
    if full:
        verdict(full["before"] == {"stored": 3} and full["after"] == {"stored": 3},
                f"full disk: saves stored before it and after room comes back ({full['before']}, {full['after']})")
        verdict(full["full"] == {"refused SVC.05099": 10} and full["rows while full"] == 3,
                f"full disk: each save refused with the code the client retries on, nothing of it kept ({full['full']})")
        verdict(full["answers while full"], "full disk: the server answers its other requests meanwhile")
        verdict(full["integrity"] == "ok", f"full disk: the database is whole after ({full['integrity']})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
