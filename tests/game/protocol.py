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
failures = 0


def check(name, ok, detail=""):
    """One result line: PASS or FAIL with what was seen."""
    global failures
    if not ok:
        failures += 1
    print(("PASS " if ok else "FAIL ") + name + (f" | {detail}" if detail and not ok else ""), flush=True)


def post(path, body, headers=None):
    """One request; returns (status, headers, body bytes). Redirects are not followed: they are what is checked."""
    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(Stay)
    req = urllib.request.Request(BASE + path, data=body, headers=headers or {}, method="POST" if body is not None else "GET")
    try:
        with opener.open(req, timeout=15) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


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

# ------------------------------------------------------------------ what the client also relies on

result, error = one("game.noSuchMethod", [])
check("a method this server does not have is handled without a popup (SVC.05008)", result is None and error["code"] == "SVC.05008")
check("SVC.001 is never sent: the client would quit for an update", all(r["error"] is None or r["error"]["code"] != "SVC.001" for r in reply))
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

print(f"{'FAIL' if failures else 'PASS'} the game server's contract: {failures} failure(s)", flush=True)
sys.exit(1 if failures else 0)
