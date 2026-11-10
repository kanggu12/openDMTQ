"""The steps of an upgrade's test, for tests/upgrade/run.sh: what players and an owner leave on a server of the release
before, and whether all of it is still there, and still works, once this tree's server and admin pages run on the same
data folder.

  upgrade.py <step> <site> <admin> <admin password> <notes>

  before         the release before, in use: players and plays, an account, a token, limits, a broadcast, a backup
  after          this tree on that data: nothing lost, everything works, the backup restores
  quiet-before   the release before, on a server nobody broadcast on: one player
  quiet-after    this tree on that data: broadcasts stay off until the owner turns them on
  admin-says     this tree's admin service alone on either data, before the server has started: what it says of broadcasts
  site-says      the server started after it: the same answer

Everything goes the way people do it: the game's own requests, the admin pages' forms, the site's sign-in, the API with
a token made on the Accounts page. The notes are a JSON file that the first step on a data folder writes and the others
read.
"""

import hashlib
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MODE, SITE, ADMIN, ADMIN_PASSWORD, NOTES = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3].rstrip("/"), sys.argv[4], sys.argv[5]
# The key the login reply gives the client, which then signs every request with it.
KEY = b"DMQGLBlive1"
# The API's place beside the admin pages.
API = "/opendmtq/api/v1"
# The site account the owner makes before the upgrade, and the name of the API token.
ACCOUNT, ACCOUNT_PASSWORD, TOKEN_NAME = "keeper", "keeper-pass", "upgrade"
# The recordings' limits the owner sets before the upgrade: not the defaults (20 GB, 30 days), so that they show as kept.
CAP_GB, DAYS = 7, 12
failures = 0


def check(name, ok, detail=""):
    """One result line; the exit status counts the failures."""
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" | {detail}" if detail and not ok else ""), flush=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Lets a check see a redirect instead of following it."""

    def redirect_request(self, *args, **kwargs):
        return None


def request(opener, url, data=None, headers=None, method=None):
    """(status, headers, body) of one request, whatever the status."""
    req = urllib.request.Request(url, data, headers or {}, method=method)
    try:
        with opener.open(req, timeout=30) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


# Requests without cookies, as the game and the API's callers make them.
plain = urllib.request.build_opener(NoRedirect)


def notes():
    """What the first step on this data folder wrote down."""
    with open(NOTES, encoding="utf-8") as f:
        return json.load(f)


def note(what):
    """The first step's notes, for the steps after the upgrade."""
    with open(NOTES, "w", encoding="utf-8") as f:
        json.dump(what, f)


# ------------------------------------------------------------------ the game's side

def call(method, params):
    """One request of the game, signed as the game signs: its result. An error is a failure of the test itself."""
    body = json.dumps([{"id": 1, "method": method, "params": params}]).encode()
    fp = hashlib.md5(KEY + body).hexdigest()
    status, _, reply = request(plain, SITE + "/DMQ/rpc", body, {"Content-Type": "application/json", "Fp": fp})
    assert status == 200, f"{method}: HTTP {status}"
    answer = json.loads(reply)[0]
    assert answer["error"] is None, f"{method}: {answer['error']}"
    return answer["result"]


def phone(udid):
    """A phone's start: the platform login by its device id, then the game's. (the player's number, the account's id)."""
    fields = urllib.parse.urlencode({"app_id": "576", "udid": udid, "device_cd": "ANDROID"}).encode()
    token = json.loads(request(plain, SITE + "/api/accounts/v3/global/login_dmq", fields)[2])["value"]["access_token"]
    guid = int(call("user.loginV2", [token, " ", "", "1.3.4", "ANDROID", "KR"])["guid"])
    return guid, token.split("|")[0]


def play(guid, chart, misses=0):
    """A play of 100 notes saved, with that many of them missed: the server's reply."""
    counts = [0, misses] + [0] * 10 + [100 - misses]
    return call("game.savePlayResult", [guid, chart, counts, 100 - misses, 0, [0, 0, 0], [0, 0, 0], "t"])


def reads(guid, puid):
    """What a phone reads of its player at a start and on the rankings, as {request: reply}: the same before and after."""
    asked = [("game.getOwnPatternScore", [guid]), ("game.getOwnAchievementList", [guid]), ("game.getOwnSongList", [guid]),
             ("shop.getOwnItemList", [guid]), ("game.getUserAsset", [guid]), ("user.getConnectUuid", [guid, "ANDROID"]),
             ("user.getUsersByPuid", [[puid], ["display_name"]]), ("game.getLineScoreRangeWithLevel", [1, 3, 1, 5]),
             ("game.getLineScoreMyRankWithLevel", [guid, 1, 3])]
    return {method: call(method, params) for method, params in asked}


def changed(old, new):
    """The requests of reads() whose replies differ, with both replies, for a failed check's line."""
    return "; ".join(f"{m}: {json.dumps(old[m])[:150]} before, {json.dumps(new[m])[:150]} now" for m in old if old[m] != new[m])


def state(udid):
    """What the server tells a phone of its broadcast: on or off, the key to send video with, the stream to send."""
    status, _, body = request(plain, f"{SITE}/live/state?ids={udid}&lang=en")
    assert status == 200, f"state: HTTP {status}"
    return json.loads(body)


def segment(mark, size=188 * 40):
    """Not real video: MPEG-TS packets (the sync byte, a mark, filler), which the server can tell from junk."""
    packet = bytes([0x47, mark % 256]) + bytes(186)
    return packet * (size // 188)


def upload(udid, token, seq):
    """One segment of a broadcast sent: the status."""
    url = f"{SITE}/live/upload?ids={udid}&seq={seq}&dur=2000"
    return request(plain, url, segment(seq), {"Content-Type": "video/mp2t", "X-Live-Token": token})[0]


def end(udid, token):
    """The broadcast's end, as a phone says it."""
    return request(plain, f"{SITE}/live/end?ids={udid}", b"", {"X-Live-Token": token}, "POST")[0]


def health():
    """What the server says of itself (the door that compose's health check and the PC client ask)."""
    return json.loads(request(plain, SITE + "/opendmtq/health.php")[2])


# ------------------------------------------------------------------ the owner's side

def owner():
    """The admin pages, signed in with the owner's ID and password: the opener that holds the cookie."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    request(opener, ADMIN + "/opendmtq/admin/login", urllib.parse.urlencode({"name": "admin", "password": ADMIN_PASSWORD}).encode())
    return opener


def page(admin, path):
    """A page of the admin pages, as text."""
    return request(admin, ADMIN + path)[2].decode()


def form(admin, path, to=None, **fields):
    """A form of an admin page sent, with that page's token, to the page's own address or the form's: the page it leads to."""
    csrf = re.search(r'name="csrf" value="([^"]+)"', page(admin, path)).group(1)
    return request(admin, ADMIN + (to or path), urllib.parse.urlencode({"csrf": csrf, **fields}).encode())[2].decode()


def switch(admin, guid, action):
    """A player's broadcast switch flipped as the Players page does it, which says whom the page was loaded for: this tree's
    in the address its row's switch names (one form for every row), an older release's in each row's own form."""
    html = page(admin, "/opendmtq/admin/players")
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    address = re.search(rf'formaction="(/opendmtq/admin/players/{guid}\?seen=[0-9a-f]+)"', html)
    seen = re.search(rf'action="/opendmtq/admin/players/{guid}"[^>]*>\s*<input type="hidden" name="csrf" value="[^"]+">'
                     r'<input type="hidden" name="seen" value="([^"]+)"', html)
    fields = {"csrf": csrf, "action": action, "seen": seen.group(1) if seen else ""}
    request(admin, ADMIN + (address.group(1) if address else f"/opendmtq/admin/players/{guid}"), urllib.parse.urlencode(fields).encode())


def broadcasts(admin):
    """What the Broadcasts page says of broadcasts as a whole, by the button it offers: True for on (it offers to turn them
    off), False for off, None for neither (a release before 0.8 had no such switch: its page is the recordings' alone)."""
    html = page(admin, "/opendmtq/admin/recordings")
    return True if 'value="broadcasts-off"' in html else False if 'value="broadcasts-on"' in html else None


def recorded(admin):
    """The recordings the admin page lists: keys "player/id", newest first."""
    return re.findall(r'name="action" value="(?:hide|show) (\d+/\d+)"', page(admin, "/opendmtq/admin/recordings"))


def api(token, path, method="GET", body=None):
    """One call of the API with a token: (status, the answer when it is JSON)."""
    headers = {"Authorization": "Bearer " + token}
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    status, heads, raw = request(plain, ADMIN + API + path, data, headers, method)
    is_json = (heads.get("Content-Type") or "").split(";")[0].strip() == "application/json"
    return status, json.loads(raw) if is_json and raw else None


def routes():
    """Every route the API says it has (its OpenAPI document, which needs no token): [method, path], sorted."""
    spec = json.loads(request(plain, ADMIN + API + "/openapi.json")[2])
    return sorted([method.upper(), path] for path, ways in spec["paths"].items() for method in ways
                  if method in ("get", "post", "put", "patch", "delete"))


def portal():
    """The site, signed in with the account the owner made: the opener that holds the cookie, and the sign-in's status."""
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    fields = urllib.parse.urlencode({"user": ACCOUNT, "password": ACCOUNT_PASSWORD, "next": "/opendmtq/"}).encode()
    return opener, request(opener, SITE + "/opendmtq/login.php", fields)[0]


# ------------------------------------------------------------------ what the two ends compare

# The API's answers that hold what the data folder holds: every value of theirs is the same after the upgrade.
KEPT_WHOLE = ("/players", "/accounts", "/tokens", "/recordings", "/recordings/limits", "/maintenance", "/songs", "/backups",
              "/backups/auto", "/broadcasts", "/site/songs", "/site/rankings", "/site/rankings/month", "/site/plays/recent",
              "/site/live")
# Fields of those answers that are not the data folder's: the disk's free space, and the hours of broadcast that still fit,
# an estimate from that space (and, from 0.8, from the quality the phones are asked for).
CHANGING = {"/recordings/limits": ("free", "hours_left")}


def lost(old, new, where, skip=()):
    """What an answer no longer has of the one before it: fields gone, values changed. New fields are no loss."""
    if isinstance(old, dict):
        if not isinstance(new, dict):
            yield f"{where}: no longer an object"
            return
        for key, value in old.items():
            if key in skip:
                continue
            if key not in new:
                yield f"{where}.{key}: gone"
            else:
                yield from lost(value, new[key], f"{where}.{key}", skip)
    elif isinstance(old, list):
        if not isinstance(new, list) or len(new) != len(old):
            yield f"{where}: {len(old)} entries before, {len(new) if isinstance(new, list) else 'no list'} now"
            return
        for i, (a, b) in enumerate(zip(old, new)):
            yield from lost(a, b, f"{where}[{i}]", skip)
    elif old != new:
        yield f"{where}: {old!r} before, {new!r} now"


# ------------------------------------------------------------------ a server in use

def before():
    """The release before, in use: two players with plays, an account, a token, limits, a broadcast with its recording, a
    backup."""
    kept = {"quiet": False, "phone": "upgrade-phone-1"}
    # Two phones: one plays chart 1 without a miss, the other with ten, so the ranking has an order to keep.
    guid, puid = phone("upgrade-phone-1")
    call("user.setNickname", [guid, "Keeper"])
    first = play(guid, 1)
    check("before: a player's first play is saved as a record", first["is_new_record"] is True, json.dumps(first)[:200])
    other, other_puid = phone("upgrade-phone-2")
    call("user.setNickname", [other, "Other"])
    play(other, 1, misses=10)
    kept.update(guid=guid, puid=puid, other=other, other_puid=other_puid)

    # The owner: an account of the site for the first player, an API token that may change things, the recordings' limits.
    admin = owner()
    form(admin, "/opendmtq/admin/accounts", action="create", name=ACCOUNT, password=ACCOUNT_PASSWORD, password2=ACCOUNT_PASSWORD,
         note="made before the upgrade")
    form(admin, "/opendmtq/admin/accounts", action="link", name=ACCOUNT, player=str(guid))
    made = form(admin, "/opendmtq/admin/accounts", action="token", token_name=TOKEN_NAME, scope="write")
    token = re.search(r"odq_[0-9a-f]+_[A-Za-z0-9_-]{20,}", made)
    check("before: the Accounts page makes an API token and shows it", token is not None)
    kept["api_token"] = token.group(0) if token else ""
    form(admin, "/opendmtq/admin/recordings", action="limits", cap_gb=str(CAP_GB), days=str(DAYS), confirmed="1")
    # The daily backup, on unless the owner says otherwise: turned off, a choice of the owner's to keep.
    form(admin, "/opendmtq/admin/backups", to="/opendmtq/admin/backups/auto", action="off")

    # A release with a switch for broadcasts as a whole (0.8 and later) starts with them off: the owner turns them on.
    if broadcasts(admin) is False:
        form(admin, "/opendmtq/admin/recordings", action="broadcasts-on")
    # A broadcast by the first player: switched on by the owner, a song with three segments of video, its end.
    switch(admin, guid, "live-on")
    said = state("upgrade-phone-1")
    check("before: the player switched on gets the key to broadcast with", said["on"] is True and bool(said.get("token")), said)
    kept["live_token"], kept["broadcast_at"], kept["state"] = said.get("token", ""), int(time.time()), said
    call("game.getPreviewPlayInfo", [guid, 1])
    sent = [upload("upgrade-phone-1", kept["live_token"], seq) for seq in range(3)]
    play(guid, 1, misses=20)
    check("before: the video is taken and the broadcast ends", sent == [204, 204, 204] and end("upgrade-phone-1", kept["live_token"]) == 204, sent)
    keys = recorded(admin)
    check("before: the broadcast left one recording", len(keys) == 1, keys)
    kept["recording"] = keys[0] if keys else ""

    # What the phones read, at the last moment of the release before; then a backup of all that, as the Backups page makes
    # one; then what the API answers, the backup in its list.
    kept["reads"] = {str(guid): reads(guid, puid), str(other): reads(other, other_puid)}
    form(admin, "/opendmtq/admin/backups", action="create")
    name = re.search(r"/opendmtq/admin/backups/(opendmtq-[\w-]+\.tar\.gz)/download", page(admin, "/opendmtq/admin/backups"))
    check("before: the Backups page makes a backup", name is not None)
    kept["backup"] = name.group(1) if name else ""
    kept["routes"] = routes()
    kept["api"] = {path: list(api(kept["api_token"], path)) for method, path in kept["routes"]
                   if method == "GET" and "{" not in path and path != "/openapi.json"}
    # The answers the other end compares whole are answers, not refusals: two refusals would compare equal too.
    whole = {path: kept["api"][path][0] for path in KEPT_WHOLE if path in kept["api"]}
    check(f"before: the API answers its token ({len(kept['api'])} answers noted, {len(whole)} to compare whole)",
          len(whole) >= 14 and set(whole.values()) == {200}, whole)
    check("before: the daily backup is off, as the owner chose", kept["api"]["/backups/auto"][1].get("on") is False, kept["api"]["/backups/auto"])
    note(kept)


def after():
    """This tree on the same data: nothing lost, everything still working, and the backup from before restores."""
    kept = notes()
    guid, puid, other, token = kept["guid"], kept["puid"], kept["other"], kept["api_token"]

    well = health()
    check("the server is well on the data of the release before", well.get("ok") is True and well.get("database") is True
          and well.get("players") == 2, well)
    # Broadcasts, the server asked first: it broadcast before, so they are on as they were, with the same key.
    said = state("upgrade-phone-1")
    check("broadcasts stay on for a server that broadcast before, and the player's key is the one it had",
          said["on"] is True and said.get("token") == kept["live_token"], said)
    check("the stream a phone is asked for is the one it sent before (720p, 30 frames a second, 2 Mbit/s, 2 s segments)",
          (said.get("fps"), said.get("height"), said.get("bitrate"), said.get("segment")) == (30, 720, 2000000, 2), said)
    # The app of the release before reads this reply too: every field it had is there, with the value it had. The notice of
    # the switch is handed out once, and went out before the upgrade: empty now.
    diff = list(lost(kept["state"], said, "state", ("toast",)))
    check("the reply has everything the release before's had, and the notice already shown is not shown again",
          not diff and said.get("toast") == "", f"{diff} {said}")

    # The API, before anything else is done on the data: the token made before works, no route went away, and what it
    # answers of the data is what it answered.
    now = routes()
    gone = [f"{method} {path}" for method, path in kept["routes"] if [method, path] not in now]
    check(f"every route of the API is still there ({len(kept['routes'])} before, {len(now)} now)", not gone, gone)
    for path, (status, old) in sorted(kept["api"].items()):
        new_status, new = api(token, path)
        if path in KEPT_WHOLE:
            diff = list(lost(old, new, path, CHANGING.get(path, ())))
            check(f"the API's {path} answers what it answered before the upgrade", new_status == status and not diff,
                  f"{status} before, {new_status} now; " + "; ".join(diff[:6]))
        else:
            # What changes with the release or the hour (the status, the logs, the machine): the answer still comes, with
            # every field at its top that it had.
            missing = sorted(set(old) - set(new or {})) if isinstance(old, dict) else []
            check(f"the API's {path} still answers", new_status == status and not missing, f"{status} before, {new_status} now; gone: {missing}")

    # The game's side: the same phones are the same players, and read what they read before.
    check("a phone is the player it was", phone("upgrade-phone-1") == (guid, puid) and phone("upgrade-phone-2")[0] == other)
    for who, old in sorted(kept["reads"].items()):
        new = reads(int(who), puid if int(who) == guid else kept["other_puid"])
        check(f"player {who} reads the same records, achievements, items, transfer code, name and rankings", old == new, changed(old, new))

    # The owner's side: the same password opens the pages, and they show what was there.
    admin = owner()
    listed = page(admin, "/opendmtq/admin/recordings")
    check("the owner signs in as before, and the Broadcasts page says broadcasts are on", broadcasts(admin) is True)
    check("the recording made before is listed", recorded(admin) == [kept["recording"]], recorded(admin))
    check("the recordings' limits are the owner's", re.search(rf'name="cap_gb"[^>]* value="{CAP_GB}"', listed) is not None
          and re.search(rf'name="days"[^>]* value="{DAYS}"', listed) is not None)
    players = page(admin, "/opendmtq/admin/players")
    check("the Players page has both players by name", "Keeper" in players and "Other" in players)

    # The site: the account made before signs in, at the sign-in page and at the PC client's door, and watches the recording.
    site, status = portal()
    check("the account made before signs in to the site", status == 303 and request(site, SITE + "/opendmtq/")[0] == 200, status)
    fields = urllib.parse.urlencode({"user": ACCOUNT, "password": ACCOUNT_PASSWORD}).encode()
    status, _, body = request(plain, SITE + "/opendmtq/client.php?signin", fields)
    check("and through the PC client's sign-in", status == 200 and json.loads(body).get("account") == ACCOUNT, f"{status} {body[:160]}")
    past = json.loads(request(site, SITE + "/opendmtq/live.php?list=1&past=1")[2]).get("past", [])
    check("the site offers the recording made before", [r["key"] for r in past] == [kept["recording"].replace("/", "-")], past)
    status, _, m3u = request(site, f"{SITE}/opendmtq/live-media.php/rec/{kept['recording']}/index.m3u8")
    lines = m3u.decode().splitlines()
    pieces = [line for line in lines if line and not line.startswith("#")]
    check("its playlist is whole", status == 200 and len(pieces) == 3 and lines[-1] == "#EXT-X-ENDLIST", m3u[:300])
    got = [request(site, f"{SITE}/opendmtq/live-media.php/rec/{kept['recording']}/{piece}")[2] for piece in pieces]
    check("its video is the video that was sent", got == [segment(seq) for seq in range(3)], [len(g) for g in got])

    # Writing on the old data: a new record, a new phone, a switch flipped on the Players page.
    better = play(guid, 2)
    check("a play after the upgrade is saved", better["is_new_record"] is True, json.dumps(better)[:200])
    third = phone("upgrade-phone-3")[0]
    check("a new phone gets a new player", third not in (guid, other) and health()["players"] == 3)
    switch(admin, other, "live-on")
    check("the owner switches another player's broadcast on", state("upgrade-phone-2")["on"] is True, state("upgrade-phone-2"))

    # A broadcast after the upgrade, recorded as well. Uploads are recorded again half a minute after the start of the one
    # before (live_lib.php's LIVE_REC_MIN_START), and the upgrade may have taken less.
    time.sleep(max(0, kept["broadcast_at"] + 32 - time.time()))
    sent = [upload("upgrade-phone-1", kept["live_token"], seq) for seq in range(2)]
    on_air = json.loads(request(site, SITE + "/opendmtq/live.php?list=1")[2])["live"]
    check("a broadcast after the upgrade is on the site", sent == [204, 204] and [int(p["id"]) for p in on_air] == [guid], f"{sent} {on_air}")
    check("and ends, with a recording of its own", end("upgrade-phone-1", kept["live_token"]) == 204 and len(recorded(admin)) == 2, recorded(admin))

    # A backup made by the release before, restored by this one: the game's data as it was then, while who broadcasts, the
    # server's own switch, the tokens and the recordings stay as they are today.
    status, answer = api(token, f"/backups/{kept['backup']}/restore", "POST", {})
    job = (answer or {}).get("job", {}).get("id", "")
    check("the backup made before the upgrade is taken for a restore", status == 202 and bool(job), f"{status} {answer}")
    for _ in range(120):
        status, answer = api(token, f"/jobs/{job}")
        if status != 200 or answer["job"]["state"] != "running":
            break
        time.sleep(0.5)
    check("the restore ends well", status == 200 and answer["job"]["state"] == "done", f"{status} {json.dumps(answer)[:300]}")
    well = health()
    check("after it the server is well, with the two players of the backup", well.get("ok") is True and well.get("players") == 2, well)
    old, new = kept["reads"][str(guid)], reads(guid, puid)
    check("the player's records are those of the backup", old == new, changed(old, new))
    check("broadcasts are still on, and the switch flipped since stays as it is today", state("upgrade-phone-1")["on"] is True
          and state("upgrade-phone-2")["on"] is True and broadcasts(admin) is True)
    check("the token made before still works after the restore", api(token, "/players")[0] == 200)
    check("both recordings are still listed after it", len(recorded(admin)) == 2, recorded(admin))


# ------------------------------------------------------------------ a server nobody broadcast on

def quiet_before():
    """The release before with one player, and nothing of broadcasts."""
    guid, _ = phone("quiet-phone-1")
    call("user.setNickname", [guid, "Quiet"])
    check("before: a player on a server nobody broadcasts on", state("quiet-phone-1")["on"] is False)
    note({"quiet": True, "phone": "quiet-phone-1", "guid": guid})


def quiet_after():
    """This tree on that data, the server asked first: broadcasts are off until the owner turns them on."""
    guid = notes()["guid"]
    check("a server that never broadcast tells its phone that broadcasts are off", phone("quiet-phone-1")[0] == guid
          and state("quiet-phone-1")["on"] is False)
    admin = owner()
    check("the Broadcasts page says they are off", broadcasts(admin) is False, broadcasts(admin))
    # A player switched on does not turn broadcasts on for the server: the owner's switch for all of them does.
    switch(admin, guid, "live-on")
    said = state("quiet-phone-1")
    check("a player switched on gets no key while they are off", said["on"] is False and "token" not in said, said)
    form(admin, "/opendmtq/admin/recordings", action="broadcasts-on")
    said = state("quiet-phone-1")
    check("the owner turns broadcasts on, and the player gets the key", said["on"] is True and bool(said.get("token")), said)


# ------------------------------------------------------------------ the admin service up before the server

def admin_says():
    """This tree's admin service alone on the data of the release before: the server has not started yet (so has not
    brought the database up to date), and the pages open and say of broadcasts what the server would."""
    kept = notes()
    admin = owner()
    opened = [request(admin, ADMIN + "/opendmtq/admin/" + name)[0] for name in ("", "players", "recordings", "accounts", "backups")]
    check("the admin pages open before the server has started", opened == [200] * 5, opened)
    want = not kept["quiet"]
    check(f"asked first, the admin service says broadcasts are {'on' if want else 'off'}", broadcasts(admin) is want, broadcasts(admin))


def site_says():
    """The server, started after the admin service looked: the same answer, and for a server in use the same key."""
    kept = notes()
    well = health()
    check("the server starts well after it", well.get("ok") is True and well.get("database") is True, well)
    said = state(kept["phone"])
    if kept["quiet"]:
        check("and tells its phone the same: off", said["on"] is False and "token" not in said, said)
    else:
        check("and tells its phone the same: on, with the key it had", said["on"] is True and said.get("token") == kept["live_token"], said)
    check("the admin service still says so", broadcasts(owner()) is (not kept["quiet"]))


{"before": before, "after": after, "quiet-before": quiet_before, "quiet-after": quiet_after, "admin-says": admin_says,
 "site-says": site_says}[MODE]()
if failures:
    print(f"{failures} check(s) FAILED")
sys.exit(1 if failures else 0)
