"""Simulate players through the game's own requests: sign-in, nickname, play results.

Feeds the rankings with realistic data for testing. Point it at a throwaway server, not the one
your friends play on: the players it creates are permanent.

Usage: python3 tests/e2e/play.py http://127.0.0.1:18097 [players] [plays per player]
"""

import hashlib
import json
import random
import sys
import urllib.parse
import urllib.request

BASE = sys.argv[1].rstrip("/")
PLAYERS = int(sys.argv[2]) if len(sys.argv) > 2 else 5
PLAYS = int(sys.argv[3]) if len(sys.argv) > 3 else 12
NAMES = ["Sena", "Minho", "Yuna", "Doyun", "Hana", "Jiwoo", "Taeyang", "Somin", "Riku", "Lena"]


def post(path, data=None, rpc=None):
    """One request; RPC bodies are JSON lists like the game sends."""
    if rpc is not None:
        body = json.dumps([rpc]).encode()
        # Signed as the game signs: the server wants it for saving a play.
        headers = {"Content-Type": "application/json", "Fp": hashlib.md5(b"DMQGLBlive1" + body).hexdigest()}
    else:
        body, headers = urllib.parse.urlencode(data).encode(), {}
    with urllib.request.urlopen(urllib.request.Request(BASE + path, body, headers), timeout=10) as r:
        return json.loads(r.read())


def call(method, params):
    reply = post("/DMQ/rpc", rpc={"id": 1, "method": method, "params": params})[0]
    if reply.get("error"):
        raise SystemExit(f"{method}: {reply['error']}")
    return reply["result"]


def judgement_stats(skill):
    """13 judgement counters (index 1 = breaks, 12 = perfect) for a chart of about 600 notes."""
    notes = 600
    breaks = max(0, int(random.gauss((1 - skill) * 40, 4)))
    perfect = int((notes - breaks) * min(1, skill + random.uniform(-0.05, 0.05)))
    rest = notes - breaks - perfect
    stats = [0, breaks] + [0] * 10 + [perfect]
    for _ in range(rest):
        stats[random.randint(5, 11)] += 1
    return stats


random.seed(7)
patterns = [p for p in range(1, 120)]
for i in range(PLAYERS):
    udid = f"e2e-player-{i}"
    token = post("/api/accounts/v3/global/login_dmq", {"udid": udid})["value"]["access_token"]
    guid = int(call("user.loginV2", [token, " ", "", "1.3.5", "ANDROID", "KR"])["guid"])
    call("user.setNickname", [guid, NAMES[i % len(NAMES)]])
    skill = random.uniform(0.6, 0.98)
    for pid in random.sample(patterns, PLAYS):
        stats = judgement_stats(skill)
        call("game.savePlayResult", [guid, pid, stats, sum(stats[2:]), 0, [0, 0, 0], [0, 0, 0], "e2e"])
    print(f"player {guid} ({NAMES[i % len(NAMES)]}): {PLAYS} plays")
