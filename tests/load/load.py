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

Each round lasts PHASE_S seconds, the heavy one until its work is done if that is later. Every save of the players is
counted: stored, refused (the client then offers to retry), an HTTP error, or no answer within TIMEOUT_S. The test passes
when none of the players' saves fails in any round, every segment of the broadcasts is taken, every look at the list of
who is on is answered, and the heavy work ends well; the times are printed for each round.

Usage: python3 tests/load/load.py SITE_URL                      the rounds
       python3 tests/load/load.py SITE_URL seed COUNT FILE      COUNT players through the game's logins: "guid udid" lines
Environment: PLAYERS (8), PHASE_S (60), SONG_S (3), FLOOD (24), BROADCASTERS (2), VIEWERS (30), SEGMENT_KB (500),
TIMEOUT_S (15), SEEDED (the seed step's file, at least PLAYERS + 1 + BROADCASTERS players), VIEWER (ID:password of a
site account), HEAVY_CMD, OUT (a folder for results.json).
"""

import hashlib
import http.client
import http.cookiejar
import json
import os
import random
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
# Where results.json goes, if anywhere.
OUT = os.environ.get("OUT", "")
# The game's signing key: the same in every copy of the game, so any client can sign (docs/architecture.md).
KEY = b"DMQGLBlive1"


class Conn:
    """One kept connection to the server, as a phone keeps one, opened again when the server closes it."""

    def __init__(self):
        # Not opened until the first request.
        self.c = None

    def send(self, method, path, body=None, headers=None):
        """(HTTP status, body) of one request; raises when no answer comes within TIMEOUT_S."""
        # Two tries: the server closes a kept connection after two idle seconds, which a request may meet.
        for attempt in (1, 2):
            # A fresh connection when there is none.
            if self.c is None:
                self.c = http.client.HTTPConnection(PARTS.hostname, PARTS.port, timeout=TIMEOUT_S)
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


def new_player(udid):
    """A player made through the game's own two logins: their guid."""
    conn = Conn()
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
    print(f"== {name} ({seconds:.0f} s)")
    for k, v in out.items():
        print(f"  {k}: {json.dumps(v)}")
    sys.stdout.flush()
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
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
