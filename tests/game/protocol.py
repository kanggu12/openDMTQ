"""The game server's contract with the game: what the client sends and what it must get back, request by request.

Runs against a server on the stand-in game files of tests/ui/make_content.php (26 made-up songs, no client tables), as
tests/game/protocol.sh starts one; nothing here needs the game's own files. Each check names the client behaviour it
protects: a reply shape the client reads, or a quirk it depends on (an empty list where it wants an entry closes the
game, for one). The reply shapes are those of client 1.3.4.

Usage: python3 tests/game/protocol.py http://127.0.0.1:18701
"""

import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1].rstrip("/")
# The key the login reply gives the client, which then signs every request with it.
KEY = "DMQGLBlive1"
# The device id of the server's own check account (./opendmtq check logs in with it): never a player in a ranking.
CHECK_UDID = "opendmtq-check"
failures = 0
# Every reply the RPC gave in this run, as (the method it answers, its error code or None): the checks at the end look at
# all of them, whichever request a check above was about.
answered = []


def check(name, ok, detail=""):
    """One result line: PASS or FAIL with what was seen."""
    global failures
    if not ok:
        failures += 1
    print(("PASS " if ok else "FAIL ") + name + (f" | {detail}" if detail and not ok else ""), flush=True)


def keep_answers(sent, data):
    """Notes each reply of one RPC request in `answered`, by the place of its call in what was sent."""
    try:
        replies = json.loads(data)
    except ValueError:
        # Not JSON (an empty body, for one): no reply to note; the check of that request says what is wrong with it.
        return
    try:
        calls = json.loads(sent) if sent else None
    except ValueError:
        calls = None
    # A body that was no list of calls has no method at any place.
    calls = calls if isinstance(calls, list) else []
    for i, reply in enumerate(replies if isinstance(replies, list) else []):
        call = calls[i] if i < len(calls) else None
        method = call.get("method") if isinstance(call, dict) else None
        error = reply.get("error") if isinstance(reply, dict) else None
        # The code the client reads; an error of another shape is kept whole, so that it shows at the end too.
        answered.append((method, error.get("code") if isinstance(error, dict) else error))


def post(path, body, headers=None):
    """One request; returns (status, headers, body bytes). Redirects are not followed: they are what is checked."""
    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(Stay)
    req = urllib.request.Request(BASE + path, data=body, headers=headers or {}, method="POST" if body is not None else "GET")
    try:
        with opener.open(req, timeout=15) as r:
            status, got, data = r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        status, got, data = e.code, dict(e.headers), e.read()
    # Every answer of the RPC, also those of the requests below that post to it without rpc().
    if path == "/DMQ/rpc":
        keep_answers(body, data)
    return status, got, data


def rpc(calls, signed=True):
    """A batch of calls as the game sends it: a JSON list, signed with the key. Returns (status, decoded reply)."""
    body = json.dumps([{"id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]).encode()
    headers = {"Content-Type": "application/json"}
    if signed:
        headers["Fp"] = hashlib.md5(KEY.encode() + body).hexdigest()
    status, _, data = post("/DMQ/rpc", body, headers)
    return status, json.loads(data) if data else None


def one(method, params, signed=True):
    """One call's result and error."""
    status, reply = rpc([(method, params)], signed)
    return reply[0]["result"], reply[0]["error"]


def phone(udid, name):
    """A phone's account as the game makes it: the platform login by its device id, the game's login, the name the
    player picks. Its guid, as a number."""
    _, _, body = post("/api/accounts/v3/global/login_dmq", f"app_id=576&udid={udid}".encode(),
                      {"Content-Type": "application/x-www-form-urlencoded"})
    token = json.loads(body)["value"]["access_token"]
    result, _ = one("user.loginV2", [token, " ", "", "1.3.4", "ANDROID", "KR"])
    guid = int(result["guid"])
    one("user.setNickname", [guid, name])
    return guid


def notes(breaks=0, at1=0, at90=0, at100=0):
    """A play's judgementStat, as the client counts the notes: place 1 the breaks, 2 those judged 1 %, 3 to 12 those judged
    10 % to 100 %; place 0 the client fills with something the server does not read."""
    stat = [0] * 13
    stat[1], stat[2], stat[11], stat[12] = breaks, at1, at90, at100
    return stat


def save(guid, chart, stat):
    """A signed save of a play, as the result screen sends it; its result and error."""
    return one("game.savePlayResult", [guid, chart, stat, sum(stat[2:]), 0, [0, 0, 0], [0, 0, 0], "t"])


# ------------------------------------------------------------------ the start of a phone

status, _, body = post("/DMQ/rpc", json.dumps([{"id": 0, "method": "service.getInfo", "params": ["1.3.4", "ANDROID"]}]).encode(),
                       {"Content-Type": "application/json", "Fp": hashlib.md5(b"x").hexdigest()})
info = json.loads(body)[0]
check("service.getInfo answers before any login, signed or not", status == 200 and info["error"] is None)
host = urllib.parse.urlparse(BASE).netloc
check("it names this server for the RPC, the client data and the game's window",
      info["result"]["api_url"].endswith("/DMQ/rpc") and info["result"]["file_server_url"].endswith("/patch")
      and info["result"]["event_url"].endswith("/score/"), json.dumps(info["result"]))
check("no terms popup and no coupon row", info["result"]["terms_yn"] == "N" and info["result"]["coupon_yn"] == "N")
check("the client data folder a phone downloads from", info["result"]["file_manage_ver"] == "1.003.005", info["result"]["file_manage_ver"])

# The platform login makes the account of a phone, by its device id, once.
form = b"app_id=576&udid=protocol-phone-1&device_cd=ANDROID"
status, headers, body = post("/api/accounts/v3/global/login_dmq", form, {"Content-Type": "application/x-www-form-urlencoded"})
login = json.loads(body)
token = login["value"]["access_token"]
puid = token.split("|")[0]
check("the platform login answers with an access token for the phone's account", status == 200 and login["result_code"] == "000"
      and token.count("|") == 5, body[:120])
again = json.loads(post("/api/accounts/v3/global/login_dmq", form, {"Content-Type": "application/x-www-form-urlencoded"})[2])
check("the same phone logs in to the same account", again["value"]["access_token"].split("|")[0] == puid)
other = json.loads(post("/api/accounts/v3/global/login_dmq", b"app_id=576&udid=protocol-phone-2", {})[2])
check("another phone gets another account", other["value"]["access_token"].split("|")[0] != puid)

result, error = one("user.loginV2", [token, " ", "", "1.3.4", "ANDROID", "KR"], signed=False)
guid = result["guid"]
check("user.loginV2 gives the client its player id as text and the signing key",
      error is None and isinstance(guid, str) and guid == puid and result["SECRET_KEY"] == KEY, json.dumps(result)[:160])

# The batch a phone sends right after its login: every list present, and the ones the client turns into arrays of
# entries never empty.
status, reply = rpc([
    ("game.getLineTopRankWithLevel", [0, 1, 20, [int(guid)]]), ("game.getAchievementCount", []),
    ("board.getNoticeList", ["US", 0, 4]), ("user.getConnectUuid", [int(guid), "ANDROID"]), ("memo.getMemoList", [int(guid), 0, 50]),
    ("game.getUserAsset", [int(guid)]), ("game.getOwnSongList", [int(guid)]), ("shop.getOwnItemList", [int(guid)]),
    ("game.getOwnAchievementList", [int(guid)]), ("game.getOwnQuestList", [int(guid)]), ("game.getOwnPatternScore", [int(guid)]),
    ("shop.getUnlockedProductList", [int(guid)]), ("game.getFirstResourceSongList", []), ("user.getUsersByPuid", [[puid], ["display_name"]]),
])
by = {r["id"]: r for r in reply}
check("the start batch comes back whole, in order, without errors", status == 200 and len(reply) == 14
      and all(r["error"] is None for r in reply), json.dumps([r["error"] for r in reply]))
news = by[2]["result"]
check("one news entry at least: the client closes on an empty news list", isinstance(news, list) and len(news) >= 1, json.dumps(news))
check("the game's 34 achievements and their 1,288 points", by[1]["result"] == {"total_achievement_count": 34, "total_achievement_point_sum": 1288})
check("a transfer code for the player", by[3]["result"]["status"] == "SUCCESS" and len(by[3]["result"]["uuid"]) == 10)
asset = by[5]["result"]
check("everyone is level 99 with every MAX POINT", asset["lev"] == 99 and asset["mpoint"] == 999999 and asset["amt_total"] == "999999")
check("every song is the player's, from 1 to the highest id", by[6]["result"]["song_ids"] == list(range(1, 27)), str(by[6]["result"])[:80])
check("a new player holds the 13 achievements of level and MAX POINT",
      [a["achievement_id"] for a in by[8]["result"]["own_achievements"]] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 19, 20, 21])
check("no quests run on this server", by[9]["result"] == {"period_quest": None, "repeat_quest": None, "level_quest": None})
check("a new player has no scores", by[10]["result"] == [])
check("the first song a phone downloads is the first of the list", by[12]["result"] == {"first_resource_songs": [{"song_id": 1, "name": "fixture1"}]})
check("a new account's name is one space until the player picks one", by[13]["result"] == [{"display_name": " "}])

result, _ = one("user.setNickname", [int(guid), "Proto"])
check("the player picks a name", result is True and one("user.getUsersByPuid", [[puid], ["display_name"]])[0] == [{"display_name": "Proto"}])

songs = one("game.getSongList", [])[0]["songs"]
check("game.getSongList gives every song with its charts", len(songs) == 26 and all(s["song_patterns"] for s in songs))
url = one("game.getSongUrl", [int(guid), 1, "ANDROID", "1.3.4"])[0]
check("a song's music and video addresses on this server", url["pmang"] == [f"http://{host}/DMQ/Songs/1/1.fpk", f"http://{host}/DMQ/Songs/1/1.webm"]
      and url["amazon"] == url["pmang"], json.dumps(url))
check("a chart's address, and its earphone timing for \"e\"",
      one("game.getPatternUrl", [int(guid), 7, "", "P"])[0] == f"http://{host}/DMQ/Patterns/7"
      and one("game.getPatternUrl", [int(guid), 7, "e", "P"])[0] == f"http://{host}/DMQ/Patterns/7_EARPHONE")

# ------------------------------------------------------------------ a play

# Song 1, 2LINE NORMAL is chart 1 (make_content.php numbers the charts in order).
perfect = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100]
status, reply = rpc([("game.savePlayResult", [int(guid), 1, perfect, 100, 0, [0, 0, 0], [0, 0, 0], "t"])], signed=False)
check("an unsigned save is refused whole, and nothing is kept", status == 403 and reply == [])
saved, error = one("game.savePlayResult", [int(guid), 1, perfect, 100, 0, [0, 0, 0], [0, 0, 0], "t"])
check("a perfect first play: 100 notes at 100 %, the ALL COMBO and PERFECT PLAY bonuses, S, a new record",
      error is None and saved["score"] == 100 * 200 + 45000 and saved["judgement_name"] == "S" and saved["is_first_pattern"]
      and saved["is_new_record"] and saved["allcom_yn"] == "Y" and saved["perfect_yn"] == "Y", json.dumps(saved)[:200])
check("the play earns the 2LINE clear and the two marks' achievements, each once",
      sorted(a["achievement_id"] for a in saved["new_achievements"]) == [11, 13, 14], json.dumps(saved["new_achievements"])[:200])
worse = [0, 10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 90]
saved, _ = one("game.savePlayResult", [int(guid), 1, worse, 50, 0, [0, 0, 0], [0, 0, 0], "t"])
check("a worse play is no new record and changes no best", saved["is_new_record"] is False and saved["is_first_pattern"] is False
      and saved["allcom_yn"] == "N" and saved["new_achievements"] == [])
# Its accuracy is 90.0 % exactly (90 notes at 100 %, 10 breaks), the least an A takes.
check("the worse play, 90 notes at 100 % and 10 breaks, is an A at exactly 90.0 %: 18,000 points, no bonus",
      saved["judgement_name"] == "A" and saved["score"] == 18000 and saved["bonus_score"] == 0, json.dumps(saved)[:200])
best = one("game.getOwnPatternScore", [int(guid)])[0]
check("the best stays the perfect one, with its accuracy in percent", best == [{"guid": int(guid), "pattern_id": 1, "score": 65000,
      "judgement_name": "S", "allcom_yn": "Y", "perfect_yn": "Y", "judgement": 100}], json.dumps(best))
odd, error = one("game.savePlayResult", [int(guid), 1, [0, 0], 0, 0, [], [], "t"])
check("a save without notes is handled without a popup (SVC.05008) and stores nothing", odd is None and error["code"] == "SVC.05008")

ranks = one("game.getLineTopRankWithLevel", [0, 1, 20, [int(guid)]])[0]
check("the month's total ranking has the player, with the name they picked", any(r["guid"] == int(guid) and r["score"] == 65000
      and r["display_name"] == "Proto" for r in ranks["ranks"]) and len(ranks["rank_day"]) == 8, json.dumps(ranks)[:200])
song = one("game.getLineScoreRangeWithLevel", [1, 3, 1, 5])[0]
check("the song's 2LINE ranking has the player first", song["scores"][:1] and song["scores"][0]["guid"] == int(guid), json.dumps(song)[:160])
mine = one("game.getLineScoreMyRankWithLevel", [int(guid), 1, 3])[0]
check("the player's own row on the song's ranking", len(mine["scores"]) == 1 and mine["scores"][0]["rank"] == 1)
check("no row on a line they did not play (OUT OF RANK)", one("game.getLineScoreMyRankWithLevel", [int(guid), 1, 5])[0] == {"scores": []})

# ------------------------------------------------------------------ several players

# Three more phones and the server's own check account play song 2's 2LINE NORMAL (chart 10): Ann and Ben tie, Cid is
# behind with a play of mixed judgements, and the check account would lead if it counted. The accounts are made in
# this order, so Ann's is older than Ben's and Cid's.
ann, ben, cid = phone("protocol-phone-a", "Ann"), phone("protocol-phone-b", "Ben"), phone("protocol-phone-c", "Cid")
checker = phone(CHECK_UDID, "Check")
# Each row of a ranking as (rank, who, score), who by the names above.
names = {int(guid): "Proto", ann: "Ann", ben: "Ben", cid: "Cid", checker: "check account"}
rows = lambda reply: [(r["rank"], names.get(r["guid"], r["guid"]), r["score"]) for r in reply]
# 100 notes at 100 % each: 65,000 apiece, a tie.
for player in (ann, ben):
    save(player, 10, notes(at100=100))
# 70 notes at 100 %, 20 at 90 % and 10 at 1 %: 70 x 200 + 20 x 180 + 10 x 1 points and ALL COMBO's 15,000 (no break).
mixed, error = save(cid, 10, notes(at1=10, at90=20, at100=70))
check("a play of mixed judgements, 70 notes at 100 %, 20 at 90 % and 10 at 1 %: 32,610 with the ALL COMBO bonus, a B",
      error is None and mixed["score"] == 32610 and mixed["bonus_score"] == 15000 and mixed["judgement_name"] == "B"
      and mixed["allcom_yn"] == "Y" and mixed["perfect_yn"] == "N", json.dumps(mixed)[:200])
# The accuracy is the notes' mean judgement: (70 x 100 + 20 x 90 + 10 x 1) / 100 notes.
best = one("game.getOwnPatternScore", [cid])[0]
check("its accuracy is the notes' mean judgement, 88.1 %", best == [{"guid": cid, "pattern_id": 10, "score": 32610,
      "judgement_name": "B", "allcom_yn": "Y", "perfect_yn": "N", "judgement": 88.1}], json.dumps(best))
# 200 notes at 100 %: 85,000, more than anybody's.
save(checker, 10, notes(at100=200))

board = rows(one("game.getLineScoreRangeWithLevel", [2, 3, 1, 5])[0]["scores"])
check("a tie goes to the older account, and the server's check account is never ranked",
      board == [(1, "Ann", 65000), (2, "Ben", 65000), (3, "Cid", 32610)], str(board))
# The client asks for ranks from..to as from and to - from + 1.
board = rows(one("game.getLineScoreRangeWithLevel", [2, 3, 2, 2])[0]["scores"])
check("a song's ranking from rank 2 with a count of 2 has two rows", board == [(2, "Ben", 65000), (3, "Cid", 32610)], str(board))
# TOTAL: Proto, Ann and Ben at 65,000 each in the order of their accounts, Cid fourth.
board = rows(one("game.getLineTopRankWithLevel", [0, 1, 1, [cid]])[0]["ranks"])
check("TOTAL's first rank, then the asking player's own row (MY RANK)", board == [(1, "Proto", 65000), (4, "Cid", 32610)], str(board))
board = rows(one("game.getLineTopRankWithLevel", [0, 1, 20, [checker]])[0]["ranks"])
check("the check account is not in TOTAL, not even as the row it asks for", board == [(1, "Proto", 65000), (2, "Ann", 65000),
      (3, "Ben", 65000), (4, "Cid", 32610)], str(board))

# ------------------------------------------------------------------ what the client also relies on

result, error = one("game.noSuchMethod", [])
check("a method this server does not have is handled without a popup (SVC.05008)", result is None and error["code"] == "SVC.05008")
status, _, body = post("/DMQ/rpc", json.dumps({"id": 1, "method": "x", "params": []}).encode(), {"Content-Type": "application/json"})
check("a JSON object instead of a list answers each of its places without an id", status == 200
      and [r["id"] for r in json.loads(body)] == [None, None, None])
check("an empty body answers an empty list", post("/DMQ/rpc", b"", {})[2] == b"[]")
check("a coupon is never valid, in the client's own words", one("shop.useCoupon", [int(guid), "X"])[0]["error_Invalid"] is True)
check("the in-game item upgrade answers neither result nor error", one("shop.upgradeInGameItem", [int(guid), "FP", 10]) == (None, None))

prices = json.loads(post("/api/product/app/576", b"app_id=576", {})[2])
check("the price list the SDK waits for has one product, not on sale", len(prices["value"]) == 1 and prices["value"][0]["on_sale"] == "N")
check("the SDK's reports are answered OK", json.loads(post("/api/members/analytics", b"x=1", {})[2])["result_code"] == "000"
      and json.loads(post("/api/members/analytics/referrer/ANDROID", b"x=1", {})[2])["result_code"] == "000")
push = json.loads(post("/api/gcm/576/register/2", b"notification_yn=Y", {"Content-Type": "application/x-www-form-urlencoded"})[2])
check("the push registration echoes the phone's choice", push["value"]["c2dm_notification_yn"] == "Y")
status, _, body = post("/inspection/status.json", None)
check("no maintenance unless the admin pages set one", status == 200 and json.loads(body)["value"]["open_yn"] == "N")
status, headers, _ = post("/score/?access_token=" + urllib.parse.quote(token, safe=""), None)
check("the game's window asks a stranger to sign in to the site first", status == 302 and "login.php" in headers.get("Location", ""))
check("the help page the SDK opens answers", post("/www/mobile/help", None)[0] == 200)
check("an address the game never asks for is a 404", post("/DMQ/nothing", None)[0] == 404)
check("the game server's code is never served", all(post(p, None)[0] in (403, 404) for p in ("/game/src/rpc.php", "/src/config.php", "/game/index.php")))

# ------------------------------------------------------------------ every reply of the run

# The errors among all the replies above. The unknown method's SVC.05008 must be among them: without it, the replies
# were not looked at and the checks below would pass on nothing.
errors = [(method, code) for method, code in answered if code is not None]
check("SVC.001 is never sent: the client would quit for an update", ("game.noSuchMethod", "SVC.05008") in errors
      and all(code != "SVC.001" for _, code in errors), f"{len(answered)} replies, errors: {errors}")
# Any other code opens the client's "retry?" popup, whose other button quits the game: nothing above may cause one.
check("no reply of the run opens the client's retry popup: every error is SVC.05008",
      all(code == "SVC.05008" for _, code in errors), f"errors: {errors}")

print(f"{'FAIL' if failures else 'PASS'} the game server's contract: {failures} failure(s)", flush=True)
sys.exit(1 if failures else 0)
