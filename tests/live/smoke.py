"""Drive the live view's three endpoints, its gate and its switch against a disposable server.

The players it creates and the switches it flips are permanent: never point it at a server people
play on. tests/live/run.sh starts a throwaway server and admin service and runs this against them.

Usage: python3 tests/live/smoke.py <site url> <admin url> <admin password> <portal password>
"""

import hashlib
import http.cookiejar
import io
import json
import os
import random
import re
import socket
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

SITE, ADMIN, ADMIN_PASSWORD, SITE_PASSWORD = sys.argv[1].rstrip("/"), sys.argv[2].rstrip("/"), sys.argv[3], sys.argv[4]
# A new device id each run, so the script can run twice against the same server.
UDID = f"live-smoke-{random.randrange(10**9):09d}"
# As the phone sends them: every id it has, known to the server or not.
IDS = f"not-an-account,{UDID}"
failures = 0


def check(name, ok, detail=""):
    """One result line; the exit status counts the failures."""
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" | {detail}" if not ok else ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Lets a test see a redirect instead of following it."""

    def redirect_request(self, *args, **kwargs):
        return None


def request(opener, url, data=None, headers=None, method=None):
    """(status, headers, body) of one request, whatever the status."""
    req = urllib.request.Request(url, data, headers or {}, method=method)
    try:
        with opener.open(req, timeout=20) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


plain = urllib.request.build_opener(NoRedirect)


def call(method, params):
    """One game RPC, as the game sends it."""
    body = json.dumps([{"id": 1, "method": method, "params": params}]).encode()
    # Signed as the game signs: the key is what its login reply gives it.
    fp = hashlib.md5(b"DMQGLBlive1" + body).hexdigest()
    status, _, reply = request(plain, SITE + "/DMQ/rpc", body, {"Content-Type": "application/json", "Fp": fp})
    assert status == 200, f"{method}: HTTP {status}"
    return json.loads(reply)[0]["result"]


def state(lang="en"):
    status, headers, body = request(plain, f"{SITE}/live/state?ids={IDS}&lang={lang}")
    assert status == 200, f"state: HTTP {status}"
    return json.loads(body)


def segment(mark, size=188 * 20):
    """Not real video: MPEG-TS packets (sync byte, then filler) that the endpoint can tell from junk."""
    packet = bytes([0x47, mark % 256]) + bytes(186)
    return (packet * (size // 188 + 1))[:size]


def upload(token, seq, body=None, dur=2000, ids=IDS):
    headers = {"Content-Type": "video/mp2t"}
    if token is not None:
        headers["X-Live-Token"] = token
    url = f"{SITE}/live/upload?ids={ids}&seq={seq}&dur={dur}"
    return request(plain, url, segment(int(seq) if str(seq).isdigit() else 0) if body is None else body, headers)[0]


def end(token):
    return request(plain, f"{SITE}/live/end?ids={IDS}", b"", {"X-Live-Token": token}, "POST")[0]


def new_player(udid):
    """A player, through the game's own requests: their guid."""
    login = urllib.parse.urlencode({"udid": udid}).encode()
    token_reply = json.loads(request(plain, SITE + "/api/accounts/v3/global/login_dmq", login)[2])
    return int(call("user.loginV2", [token_reply["value"]["access_token"], " ", "", "1.3.5", "ANDROID", "KR"])["guid"])


guid = new_player(UDID)
call("user.setNickname", [guid, "LiveSmoke"])

# The admin service, signed in with the owner's ID and password.
admin = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
request(admin, ADMIN + "/opendmtq/admin/login", urllib.parse.urlencode({"name": "admin", "password": ADMIN_PASSWORD}).encode())


def account_post(**fields):
    """A form of the Accounts page, with its token; the page it leads to. A password typed to make an account is typed
    twice there, as on the page."""
    page = request(admin, ADMIN + "/opendmtq/admin/accounts")[2].decode()
    csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    if fields.get("action") == "create":
        fields.setdefault("password2", fields.get("password", ""))
    return request(admin, ADMIN + "/opendmtq/admin/accounts", urllib.parse.urlencode({"csrf": csrf, **fields}).encode())[2].decode()


# The site's account this test signs in with, made as the owner makes one; nobody can make their own.
account_post(action="create", name="dmtq", password=SITE_PASSWORD, note="smoke test")


def switch(action, who=None):
    """Flip a player's switch the way the Players page does, with that page's CSRF token."""
    page = request(admin, ADMIN + "/opendmtq/admin/players")[2].decode()
    csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    # Each form says who the page was loaded for.
    seen = re.search(rf'action="/opendmtq/admin/players/{who or guid}"[^>]*>\s*<input type="hidden" name="csrf" value="[^"]+"><input type="hidden" name="seen" value="([^"]+)"', page)
    request(admin, f"{ADMIN}/opendmtq/admin/players/{who or guid}", urllib.parse.urlencode({"csrf": csrf, "action": action, "seen": seen.group(1) if seen else ""}).encode())


def admin_page(path):
    return request(admin, ADMIN + path)[2].decode()


# The admin pages' address until 2026-11 (/admin) leads to the same page at /opendmtq/admin, query and all, by a permanent
# redirect that keeps a form's POST. (Through the server, on a site with the admin pages on its port: run.sh.)
status, headers, _ = request(plain, ADMIN + "/admin/players?sort=total")
check("the old admin address leads to the new one", status == 308 and headers.get("Location") == "/opendmtq/admin/players?sort=total",
      f"{status} {headers.get('Location')}")


def live_now_tile():
    return re.search(r'Broadcasting now</span><span class="num[^"]*">(\w+)<', admin_page("/opendmtq/admin/")).group(1)


# Off by default.
s = state()
check("off by default: no token, no notice", s["on"] is False and "token" not in s and s["toast"] == "", s)
check("the encoder settings are always there", (s["fps"], s["height"], s["bitrate"], s["segment"]) == (30, 720, 2000000, 2), s)
check("unknown ids are simply off", json.loads(request(plain, SITE + "/live/state?ids=nobody")[2])["on"] is False)
check("upload refused while off", upload("0" * 32, 0) == 403)
check("end refused while off", end("0" * 32) == 403)
check("the players page offers the switch", "Turn on" in admin_page("/opendmtq/admin/players"))


def broadcasts_post(**fields):
    """A form of the Broadcasts page's top (the server's switch, or its settings), with that page's token."""
    page = admin_page("/opendmtq/admin/recordings")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    request(admin, ADMIN + "/opendmtq/admin/recordings", urllib.parse.urlencode({"csrf": csrf, **fields}).encode())


# Broadcasts are off for the whole server until the owner turns them on: a player switched on meanwhile gets no key and no
# notice, and the switch is kept for then.
check("broadcasts off for the server at first", "Broadcasts are off" in admin_page("/opendmtq/admin/recordings"))
switch("live-on")
s = state("ko")
check("off for the server: a player switched on gets no key and no notice", s["on"] is False and "token" not in s and s["toast"] == "", s)
check("and the players page holds the switch for then", "Switched on" in admin_page("/opendmtq/admin/players"))
switch("live-off")
# The stream's quality, as the phones are asked for it: a named one, then the default again.
broadcasts_post(action="settings", new_players="off", quality="smooth")
s = state()
check("the quality the owner picks is the one the phones are asked for", (s["fps"], s["height"], s["bitrate"], s["segment"]) == (60, 720, 4000000, 2), s)
broadcasts_post(action="settings", new_players="off", quality="standard")
broadcasts_post(action="broadcasts-on")
check("the owner turns broadcasts on", "Broadcasts are on" in admin_page("/opendmtq/admin/recordings"))

# On: the notice comes once, in the phone's language.
switch("live-on")
s = state("ko")
token = s.get("token", "")
check("on: a token", s["on"] is True and re.fullmatch(r"[0-9a-f]{32}", token) is not None, s)
check("the notice in Korean", s["toast"].startswith("지금 이 플레이를 라이브로 방송하고 있어요\n") and "사이트의 LIVE에서" in s["toast"], s)
check("the notice only once", state("ko")["toast"] == "")
check("the admin says it waits for the phone", "live-state wait" in admin_page("/opendmtq/admin/players"))

# Saving a play takes the game's signature; a read does not.
unsigned = json.dumps([{"id": 1, "method": "game.savePlayResult", "params": [guid, 1, [0, 0] + [0] * 10 + [50], 50, 0, [0, 0, 0], [0, 0, 0], "smoke"]}]).encode()
check("unsigned play result refused", request(plain, SITE + "/DMQ/rpc", unsigned, {"Content-Type": "application/json"})[0] == 403)
check("play result under a wrong key refused", request(plain, SITE + "/DMQ/rpc", unsigned, {"Content-Type": "application/json", "Fp": hashlib.md5(b"wrong" + unsigned).hexdigest()})[0] == 403)
other_case = unsigned.replace(b"game.savePlayResult", b"Game.SavePlayResult")
check("the method's letter case does not get around the signature", request(plain, SITE + "/DMQ/rpc", other_case, {"Content-Type": "application/json"})[0] == 403)
open_read = json.dumps([{"id": 1, "method": "service.getInfo", "params": []}]).encode()
check("unsigned read still answered", request(plain, SITE + "/DMQ/rpc", open_read, {"Content-Type": "application/json"})[0] == 200)

# A notice waits for the end of a song: a saved result ends it.
call("game.getPreviewPlayInfo", [guid, 1])
switch("live-off")
check("off: no more token", "token" not in state())
check("the notice waits during a song", state()["toast"] == "")
call("game.savePlayResult", [guid, 1, [0, 0] + [0] * 10 + [50], 50, 0, [0, 0, 0], [0, 0, 0], "smoke"])
check("the notice comes after the result", state()["toast"].startswith("Your broadcast has ended\n"))

# A quit song sends no result: the next menu request after the start's own ends it.
call("game.getPreviewPlayInfo", [guid, 1])
switch("live-on")
s = state()
check("switched on during a song: a token, and the notice waits", s.get("token") and s["toast"] == "", s)
call("game.getUserAsset", [guid])
check("a menu request in the start's batch does not end the song", state()["toast"] == "")
time.sleep(11)
call("game.getUserAsset", [guid])
check("a later menu request does", state()["toast"].startswith("Your play is live now\nWatch it live or later under LIVE on "))

# Flipping back before the phone read the notice leaves nothing to say.
switch("live-off")
switch("live-on")
s = state()
token = s["token"]
check("a notice taken back is not shown", s["toast"] == "", s)

# Refused uploads.
check("wrong token", upload("f" * 32, 0) == 403)
check("no token", upload(None, 0) == 403)
check("end with a wrong token", end("f" * 32) == 403)
check("unknown ids with a good token", upload(token, 0, ids="nobody") == 403)
check("seq not a number", upload(token, "1;x") == 400)
check("seq below zero", upload(token, -1) == 400)
check("dur not a number", upload(token, 0, dur="x") == 400)
check("not MPEG-TS", upload(token, 0, b"<html>" * 100) == 400)
check("too short", upload(token, 0, b"\x47") == 400)
check("one packet is too little to be video", upload(token, 0, segment(0, 188)) == 400)
check("nine packets as well", upload(token, 0, segment(0, 188 * 9)) == 400)
try:
    too_big = upload(token, 0, segment(0, 4 * 1024 * 1024 + 188))
except OSError as e:
    # Apache may answer and close before the whole body is sent.
    too_big = f"closed: {e}"
check("over 4 MB refused", too_big == 413 or str(too_big).startswith("closed"), too_big)


def raw_upload(head, body):
    """A request written by hand, for what urllib will not send; the status, or 0 without an answer."""
    site = urllib.parse.urlsplit(SITE)
    with socket.create_connection((site.hostname, site.port), timeout=20) as c:
        c.sendall(f"POST /live/upload?ids={IDS}&seq=0&dur=2000 HTTP/1.1\r\nHost: x\r\nX-Live-Token: {token}\r\n{head}Connection: close\r\n\r\n".encode() + body)
        c.shutdown(socket.SHUT_WR)
        reply = c.recv(64)
    return int(reply.split()[1]) if reply else 0


def nothing_stored():
    return request(plain, f"{SITE}/opendmtq/health.php")[0] == 200 and not stream_exists()


def stream_exists():
    """Whether any video was stored, seen through the gate by a signed-in visitor."""
    jar_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    form = urllib.parse.urlencode({"user": "dmtq", "password": SITE_PASSWORD, "next": "/opendmtq/"}).encode()
    request(jar_opener, SITE + "/opendmtq/login.php", form)
    return request(jar_opener, f"{SITE}/opendmtq/live-media.php/{guid}/index.m3u8")[0] == 200


chunk = hex(188 * 20)[2:].encode() + b"\r\n" + segment(0) + b"\r\n0\r\n\r\n"
check("chunked refused", raw_upload("Transfer-Encoding: chunked\r\n", chunk) == 411)
check("a body cut short is not answered as stored", raw_upload(f"Content-Length: {188 * 20}\r\n", segment(0, 188 * 10)) != 204)
check("neither was stored", nothing_stored())
check("exactly 4 MB fits, and is the limit", upload(token, 0, segment(0, 4 * 1024 * 1024)) == 204)
try:
    big_state = request(plain, f"{SITE}/live/end?ids={IDS}", bytes(64 * 1024), {"X-Live-Token": token}, "POST")[0]
except OSError as e:
    big_state = f"closed: {e}"
check("the other endpoints take no large body", big_state == 413 or str(big_state).startswith("closed"), big_state)

# The gate.
portal = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
media = f"{SITE}/opendmtq/live-media.php/{guid}"
check("signed out: no playlist", request(plain, media + "/index.m3u8")[0] == 403)
status, headers, _ = request(plain, SITE + "/opendmtq/live.php")
check("signed out: the page sends to the sign-in", status == 302 and "login.php?next=" in headers["Location"], headers.get("Location"))
form = urllib.parse.urlencode({"user": "dmtq", "password": SITE_PASSWORD, "next": "/opendmtq/"}).encode()
request(portal, SITE + "/opendmtq/login.php", form)


def playlist():
    status, headers, body = request(portal, media + "/index.m3u8")
    return status, headers.get("Content-Type"), body.decode()


def on_page():
    """Who the live page lists as on air now."""
    return json.loads(request(portal, SITE + "/opendmtq/live.php?list=1")[2])["live"]


def past():
    """The recordings the live page offers: their keys."""
    return [r["key"] for r in json.loads(request(portal, SITE + "/opendmtq/live.php?list=1&past=1")[2])["past"]]


def page(path, lang="en", opener=None, headers=None):
    """A portal page's text, in a language: signed in (the site's pages are for those signed in) unless another opener is
    given."""
    opener = opener or portal
    # The language is the switch's cookie, sent next to what the opener's own jar holds.
    jar = next((h.cookiejar for h in getattr(opener, "handlers", []) if isinstance(h, urllib.request.HTTPCookieProcessor)), [])
    cookies = "; ".join([f"{c.name}={c.value}" for c in jar] + [f"opendmtq_lang={lang}"])
    return request(opener, SITE + "/opendmtq/" + path, None, {"Cookie": cookies, "Accept": "text/html", **(headers or {})})[2].decode()


def on_air_mark(html):
    """The menu's count of players on air, or None without one."""
    m = re.search(r'<span class="onair"[^>]*>(\d+)<', html)
    return int(m.group(1)) if m else None


# Upload's first numbers (the 4 MB one above was seq 0).
for seq in (1, 2):
    check(f"segment {seq} stored", upload(token, seq, dur=1960) == 204)
status, ctype, m3u = playlist()
check("the playlist is served", status == 200 and ctype == "application/vnd.apple.mpegurl", (status, ctype))
check("version 3", "#EXT-X-VERSION:3\n" in m3u, m3u)
check("target duration from the segments", "#EXT-X-TARGETDURATION:2\n" in m3u, m3u)
check("three segments so far", m3u.count("#EXTINF:") == 3 and "#EXTINF:1.960," in m3u, m3u)
check("no end yet", "ENDLIST" not in m3u, m3u)
first = re.findall(r"^(\d+)\.ts$", m3u, re.M)[1]
status, headers, body = request(portal, f"{media}/{first}.ts")
check("a segment comes back as sent", status == 200 and headers["Content-Type"] == "video/mp2t" and body == segment(1), status)
check("the same seq again is not stored twice", upload(token, 2) == 204 and playlist()[2].count("#EXTINF:") == 3)
for bad in ("/../../dmtq.db3", "/index.php", "/1.ts/x", "/1e3.ts", "/%2e%2e/stream.json"):
    check(f"the gate refuses {bad}", request(portal, f"{SITE}/opendmtq/live-media.php/{guid}{bad}")[0] in (403, 404))
check("the gate refuses another folder's name", request(portal, f"{SITE}/opendmtq/live-media.php/x/index.m3u8")[0] == 404)

# Listed as live.
cards = on_page()
check("the live list names the player", any(c["id"] == guid and c["name"] == "LiveSmoke" for c in cards), cards)
# What ordinary visitors see, signed in or not, in both languages.
for lang, heading in (("ko", "방송"), ("en", "Broadcasts")):
    home = page("", lang)
    # One box of broadcasts: its heading, its dot lit (not hidden) while someone is on, their card leading to their stream.
    check(f"home ({lang}): the box of broadcasts names the player, linking to their stream, its dot lit",
          heading in home and 'id="on-air-dot" aria-hidden="true"></span>' in home and "LiveSmoke" in home and f'live.php?p={guid}"' in home)
    check(f"home ({lang}): the menu counts one on air", on_air_mark(home) == 1)
for path in ("", "ranking.php", "songs.php", f"player.php?id={guid}", "song.php?id=1", "nope.php"):
    html = page(path)
    check(f"{path or 'home'}: the menu has LIVE, with its count", 'href="/opendmtq/live.php">LIVE' in html and on_air_mark(html) == 1)
# A stranger gets the sign-in page whatever page they asked for, and back to it afterwards; nothing of what is inside, not
# even who is on air, is in the sign-in page.
for path in ("", "ranking.php", "songs.php", "song.php?id=1", f"player.php?id={guid}", "download.php"):
    status, headers, _ = request(plain, f"{SITE}/opendmtq/{path}")
    check(f"signed out: {path or 'home'} sends to the sign-in, and back", status == 302 and headers.get("Location") == "/opendmtq/login.php?next=" + urllib.parse.quote(f"/opendmtq/{path}", safe=""), headers.get("Location"))
check("signed out: the pages' own looks and the QR code answer nothing", request(plain, SITE + "/opendmtq/?live=1")[0] == 403 and request(plain, SITE + "/opendmtq/qr.php")[0] == 403)
signin = request(plain, SITE + "/opendmtq/login.php", None, {"Accept": "text/html"})[2].decode()
check("the sign-in page shows nothing of what is inside", 'name="password"' in signin and all(x not in signin for x in ('class="nav"', 'class="tabbar"', 'class="onair"', "LiveSmoke")), signin[:200])
check("the licenses and the health check stay open", request(plain, SITE + "/opendmtq/licenses.php")[0] == 200 and request(plain, SITE + "/opendmtq/health.php")[0] == 200)
mark = f'<a class="live-mark" href="/opendmtq/live.php?p={guid}"'
# The licenses: for anyone, signed in or not, from every page's footer, with the texts the fonts ask to go along.
licenses = page("licenses.php")
check("the licenses page names the project's own license and what it does not cover",
      "MIT License" in licenses and "Permission is hereby granted" in licenses and "does not cover the game" in licenses)
check("the licenses page has the fonts' license text and the way to the player's", "SIL OPEN FONT LICENSE" in licenses and "/opendmtq/hls/LICENSE" in licenses)
check("every page's footer leads to the licenses", 'href="/opendmtq/licenses.php"' in page("ranking.php"))
check("the licenses page speaks Korean too", "라이선스" in page("licenses.php", lang="ko"))
check("rankings: a LIVE mark on the player", mark in page("ranking.php"))
check("the player's page: a LIVE mark", mark in page(f"player.php?id={guid}"))
check("only one mark on the rankings", page("ranking.php").count('class="live-mark"') == 1)
check("the dashboard counts one live", live_now_tile() == "1", live_now_tile())
check("the admin says video is coming in", "live-state on" in admin_page("/opendmtq/admin/players"))
call("game.getPreviewPlayInfo", [guid, 1])
cards = on_page()
check("the list shows the chart being played", any(c["id"] == guid and "·" in c["doing"] for c in cards), cards)
call("game.savePlayResult", [guid, 1, [0, 0] + [0] * 10 + [50], 50, 0, [0, 0, 0], [0, 0, 0], "smoke"])

# The app restarts: numbering from 0 again.
check("seq back to 0 accepted", upload(token, 0) == 204)
check("a discontinuity before it", "#EXT-X-DISCONTINUITY\n#EXTINF" in playlist()[2], playlist()[2])

# The window slides, with old files going.
names_before = re.findall(r"^(\d+)\.ts$", playlist()[2], re.M)
for seq in range(1, 9):
    upload(token, seq)
m3u = playlist()[2]
names = re.findall(r"^(\d+)\.ts$", m3u, re.M)
check("a window of six", len(names) == 6, m3u)
check("media sequence is the first in the window", f"#EXT-X-MEDIA-SEQUENCE:{names[0]}\n" in m3u, m3u)
check("the discontinuity sequence counted the one that left", "#EXT-X-DISCONTINUITY-SEQUENCE:1\n" in m3u, m3u)
check("older segments are gone", request(portal, f"{media}/{names_before[0]}.ts")[0] == 404)

# The end.
check("end accepted", end(token) == 204)
check("the playlist ends", playlist()[2].endswith("#EXT-X-ENDLIST\n"), playlist()[2])
check("not listed once ended", on_page() == [])
home = page("")
check("home: no section, the menu's LIVE without a count", '<div class="thumbs" id="live" hidden' in home and 'href="/opendmtq/live.php">LIVE' in home and on_air_mark(home) is None)
check("rankings: no mark", 'class="live-mark"' not in page("ranking.php"))
check("the dashboard counts none", live_now_tile() == "0", live_now_tile())
check("uploading again goes on after the end", upload(token, 0) == 204 and "ENDLIST" not in playlist()[2])

# Silence: told as ended, not listed, and the next upload starts clean.
time.sleep(31)
m3u = playlist()[2]
check("after 30 s of silence the playlist says it ended", m3u.endswith("#EXT-X-ENDLIST\n"), m3u)
check("not listed after silence", on_page() == [])
check("the next upload is accepted", upload(token, 1) == 204)
check("and starts a new window", playlist()[2].count("#EXTINF:") == 1, playlist()[2])

# Off: the phone is told to stop, nothing more is shown, the video is gone.
switch("live-off")
check("upload refused after switching off", upload(token, 2) == 403)
check("end refused after switching off", end(token) == 403)
check("the gate shows nothing any more", playlist()[0] == 404)

# A direct link to a player, signed out and signed in, while they are off air.
status, headers, _ = request(plain, f"{SITE}/opendmtq/live.php?p={guid}")
check("a direct link survives the sign-in", status == 302 and f"next=%2Fopendmtq%2Flive.php%3Fp%3D{guid}" in headers["Location"], headers.get("Location"))
html = page(f"live.php?p={guid}", "en", portal)
check("a direct link to someone off air says it waits for them", "LiveSmoke is not broadcasting right now" in html, html[:200])
html = page(f"live.php?p={guid}", "ko", portal)
check("the same in Korean", "LiveSmoke 님은 지금 방송 중이 아닙니다" in html)
html = page("live.php", "en", portal)
check("the empty page says when something appears", "Nobody is broadcasting right now" in html and "appear here while they play" in html)
check("a link to nobody real is just the page", "not broadcasting right now" not in page("live.php?p=999999", "en", portal).replace('hidden', ''))
# The game is Android's, watching is anyone's.
iphone = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1", "Accept": "text/html"}
html = request(plain, SITE + "/opendmtq/login.php?next=%2Fopendmtq%2Flive.php", None, iphone)[2].decode()
check("an iPhone can sign in to watch", 'name="password"' in html, html[:200])
html = request(plain, SITE + "/opendmtq/login.php?next=%2Fapk", None, iphone)[2].decode()
check("an iPhone on the way to the app is told it cannot install, and can still sign in", 'name="password"' in html and "ios-note" in html and 'class="warn ios-note" hidden' not in html)
for lang, word in (("ko", "로그인하고 보기"), ("en", "Sign in to watch")):
    check(f"the sign-in on the way to a broadcast speaks of watching ({lang})", word in page("login.php?next=%2Fopendmtq%2Flive.php", lang, plain))

# The language: the browser's by default, the switch's once pressed, on both the portal and the admin.
def html_lang(html):
    m = re.search(r'<html lang="(\w+)"', html)
    return m.group(1) if m else None


first_visit = request(portal, SITE + "/opendmtq/ranking.php", None, {"Accept-Language": "ko-KR,ko;q=0.9"})[2].decode()
check("the portal starts in English whatever the browser says", html_lang(first_visit) == "en")
status, headers, _ = request(plain, SITE + "/opendmtq/lang.php?to=ko&next=%2Fopendmtq%2Franking.php")
check("the switch remembers and goes back", status == 303 and headers["Location"] == "/opendmtq/ranking.php" and "opendmtq_lang=ko" in headers["Set-Cookie"], dict(headers))
status, headers, _ = request(plain, SITE + "/opendmtq/lang.php?to=ko&next=https%3A%2F%2Fexample.com%2F")
check("the switch goes back only within the site", headers["Location"] == "/opendmtq/")
korean = page("ranking.php", "ko", headers={"Accept-Language": "en"})
check("the portal's cookie beats the browser", html_lang(korean) == "ko" and 'class="lang-switch"' in korean)
english = request(plain, ADMIN + "/opendmtq/admin/login", None, {"Accept-Language": "ko"})[2].decode()
check("the admin starts in English whatever the browser says", html_lang(english) == "en")
status, headers, _ = request(plain, ADMIN + "/opendmtq/admin/lang?to=en&next=%2Fopendmtq%2Fadmin%2Flogin")
check("the admin's switch needs no sign-in and goes back", status == 303 and headers["Location"].endswith("/opendmtq/admin/login") and "opendmtq_lang=en" in headers["Set-Cookie"], dict(headers))
status, headers, _ = request(plain, ADMIN + "/opendmtq/admin/lang?to=en&next=https%3A%2F%2Fexample.com%2F")
check("the admin's switch goes back only within the admin", "example.com" not in headers["Location"])
check("the admin's cookie beats the browser", html_lang(request(plain, ADMIN + "/opendmtq/admin/login", None, {"Accept-Language": "ko", "Cookie": "opendmtq_lang=en"})[2].decode()) == "en")

# Sign-in in the header, on every page: the way there comes back to the page, and signed in it says sign out.
check("signed out: a sign-in link on the pages that stay open, coming back to them", 'href="/opendmtq/login.php?next=%2Fopendmtq%2Flicenses.php"' in request(plain, SITE + "/opendmtq/licenses.php")[2].decode())
check("signed in: a way to sign out", 'action="/opendmtq/login.php?logout=1"' in page("ranking.php", "en", portal))
check("none on the sign-in page itself", 'class="auth' not in page("login.php", "en", plain))
# The home page leads to the install page, which has the download and its steps.
home_page = page("", "en", portal)
install_page = page("download.php", "en", portal)
check("the home page leads to the download page, with no steps of its own", 'href="download.php"' in home_page and 'class="steps"' not in home_page)
check("the download page has its title and the help, whatever the app's state", "<title>Download the app" in install_page and 'id="help"' in install_page)
check("the home page's own look at who is on is plain JSON", isinstance(json.loads(request(portal, SITE + "/opendmtq/?live=1")[2]), list))
check("the cards' script is served", request(plain, SITE + "/opendmtq/thumbs.js")[0] == 200)
# What the game is told about its menus and its prices.
service = json.loads(request(plain, SITE + "/DMQ/rpc", json.dumps([{"id": 1, "method": "service.getInfo", "params": ["1.3.4", "ANDROID"]}]).encode(), {"Content-Type": "application/json"})[2])[0]["result"]
check("no coupon row in the game: no coupon works here", service["coupon_yn"] == "N" and service["terms_yn"] == "N", str(service)[:120])
prices = json.loads(request(plain, SITE + "/api/product/app/576", b"app_id=576", {"Content-Type": "application/x-www-form-urlencoded"})[2])
check("the price list the game waits for is one item, not half a megabyte", len(prices["value"]) == 1 and prices["result_code"] == "000")
status, headers, _ = request(plain, SITE + "/apk")
check("the app's address asks a stranger to sign in, and comes back to it", status == 302 and headers["Location"].endswith("login.php?next=%2Fapk"), headers.get("Location"))
check("the menu marks the section the download page is in", 'href="/opendmtq/download.php" class="on"' in install_page)
# What the sign-in page says follows where it came from: only the way to the download is about installing.
from_header = request(plain, SITE + "/opendmtq/login.php?next=%2Fopendmtq%2Franking.php", None, {"Accept-Language": "en"})[2].decode()
check("from the header it just signs in", "<h2>Sign in</h2>" in from_header and "Sign in to download" not in from_header)
check("an iPhone can sign in from the header, with no word about installing", 'name="password"' in (r := request(plain, SITE + "/opendmtq/login.php?next=%2Fopendmtq%2Franking.php", None, iphone)[2].decode()) and "ios-note" not in r)
check("an iPhone on the way to the download sees the note above the form", (r := request(plain, SITE + "/opendmtq/login.php?next=%2Fapk", None, iphone)[2].decode()).find("ios-note") < r.find('name="password"') and "ios-note" in r)
check("an iPad that says it is a Mac keeps the form when signing in to watch", 'class="get-app"' not in request(plain, SITE + "/opendmtq/login.php?next=%2Fopendmtq%2Flive.php", None, {"Accept-Language": "en"})[2].decode())
check("a page that depends on signing in is not kept", "no-store" in str(request(portal, SITE + "/opendmtq/ranking.php")[1].get("Cache-Control", "")))
# Signing out takes this site's own form.
request(portal, SITE + "/opendmtq/login.php?logout=1")
check("a link does not sign anyone out", 'action="/opendmtq/login.php?logout=1"' in page("ranking.php", "en", portal))
request(portal, SITE + "/opendmtq/login.php?logout=1", b"", {"Sec-Fetch-Site": "cross-site"})
check("nor a form on another site", 'action="/opendmtq/login.php?logout=1"' in page("ranking.php", "en", portal))
leaving = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
request(leaving, SITE + "/opendmtq/login.php", urllib.parse.urlencode({"user": "dmtq", "password": SITE_PASSWORD, "next": "/opendmtq/"}).encode())
signed_in = 'action="/opendmtq/login.php?logout=1"' in page("ranking.php", "en", leaving)
request(leaving, SITE + "/opendmtq/login.php?logout=1", b"", {"Sec-Fetch-Site": "same-origin"})
check("the site's own form does", signed_in and 'action="/opendmtq/login.php?logout=1"' not in page("ranking.php", "en", leaving))

# Accounts: an ID and a password from the Accounts page, and nothing else, signs in to the site.
def site_sign_in(name, password, headers=None):
    """A browser of its own, signed in (or not) with this ID and password, its form sent with these headers (what a
    browser says about the page it came from); and whether it got in."""
    jar = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    request(jar, SITE + "/opendmtq/login.php", urllib.parse.urlencode({"user": name, "password": password, "next": "/opendmtq/"}).encode(), headers)
    return jar, request(jar, SITE + "/opendmtq/ranking.php")[0] == 200


# Signing in takes this site's own form too: a form on another site cannot sign a visitor in to an account that site
# chose (its owner's, to see what the visitor does there). What the browser says decides: where the request comes from,
# or in an older browser the page the form came from (Origin, its host against the one asked; "null" names none).
form = urllib.parse.urlencode({"user": "dmtq", "password": SITE_PASSWORD, "next": "/opendmtq/live.php"}).encode()
status, headers, _ = request(plain, SITE + "/opendmtq/login.php", form, {"Sec-Fetch-Site": "cross-site"})
check("a sign-in form on another site leads to the empty sign-in page", status == 303 and headers.get("Location") == "/opendmtq/login.php?next=%2Fopendmtq%2Flive.php",
      f"{status} {headers.get('Location')}")
elsewhere = [{"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}, {"Origin": "http://elsewhere.example"}, {"Origin": "null"}]
check("and signs nobody in, nor does one on a neighbour of this site, nor one an older browser names",
      not any(site_sign_in("dmtq", SITE_PASSWORD, h)[1] for h in elsewhere))
here = [{"Sec-Fetch-Site": "same-origin"}, {"Sec-Fetch-Site": "none"}, {"Origin": SITE}, {}]
check("the site's own form signs in, from any browser, and so does a request that names no page",
      all(site_sign_in("dmtq", SITE_PASSWORD, h)[1] for h in here))
# The PC client's sign-in answers what a page of another site asks with 403, the launcher itself (it names no page) as before.
client_signin = urllib.parse.urlencode({"user": "dmtq", "password": SITE_PASSWORD}).encode()
check("the PC client's sign-in refuses another site's page too",
      all(request(plain, SITE + "/opendmtq/client.php?signin", client_signin, h)[0] == 403 for h in elsewhere)
      and request(plain, SITE + "/opendmtq/client.php?signin", client_signin)[0] == 200)


made = account_post(action="create", name="Smoke2", password="", note="")
password = re.search(r"<code>([a-z2-9]{10})</code>", made).group(1)
check("the password of a new account shows once", password not in request(admin, ADMIN + "/opendmtq/admin/accounts")[2].decode())
friend, inside = site_sign_in("smoke2", password)
check("an account signs in with its ID, in any letter case, and its password", inside)
check("a wrong password does not", not site_sign_in("Smoke2", password + "x")[1])
check("nor an ID that is not there, nor a shared one", not site_sign_in("nobody", password)[1] and not site_sign_in("dmtq", "smoke-not")[1])
account_post(action="off", name="Smoke2")
check("switched off, its sign-in ends and it cannot sign in", request(friend, SITE + "/opendmtq/ranking.php")[0] == 302 and not site_sign_in("Smoke2", password)[1])
account_post(action="on", name="Smoke2")
friend, inside = site_sign_in("Smoke2", password)
renewed = re.search(r"<code>([a-z2-9]{10})</code>", account_post(action="password", name="Smoke2")).group(1)
check("a new password ends the old sign-ins and replaces the old password",
      inside and request(friend, SITE + "/opendmtq/ranking.php")[0] == 302 and not site_sign_in("Smoke2", password)[1] and site_sign_in("Smoke2", renewed)[1])
friend, _ = site_sign_in("Smoke2", renewed)
account_post(action="delete", name="Smoke2")
check("deleted, its sign-in ends", request(friend, SITE + "/opendmtq/ranking.php")[0] == 302)
# An account with admin rights signs in to the admin pages too; one without does not.
account_post(action="create", name="helper", password="hunter22", note="", admin="1")
helper = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
request(helper, ADMIN + "/opendmtq/admin/login", urllib.parse.urlencode({"name": "helper", "password": "hunter22"}).encode())
check("admin rights open the admin pages", 'class="account-form"' in request(helper, ADMIN + "/opendmtq/admin/accounts")[2].decode())
outsider = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
request(outsider, ADMIN + "/opendmtq/admin/login", urllib.parse.urlencode({"name": "dmtq", "password": SITE_PASSWORD}).encode())
check("a site account does not", "Wrong ID or password" in request(outsider, ADMIN + "/opendmtq/admin/login")[2].decode() or 'name="password"' in request(outsider, ADMIN + "/opendmtq/admin/players")[2].decode())
# The site's sign-in takes such an account too, so guesses at it there count for the whole server, as on the admin pages'
# own sign-in: thirty failures in ten minutes from anywhere, and its sign-in waits. Here from an address each (the server
# takes a forwarded address from the test's own network, as from a proxy of its own), all at once, as many guessers
# would come: two past the limit, held back however close together they come.
answers = []


def guess(n):
    """A wrong password for the account with admin rights, from an address of its own; what the sign-in page said."""
    form = urllib.parse.urlencode({"user": "helper", "password": f"guess-{n}", "next": "/opendmtq/"}).encode()
    page_text = request(plain, SITE + "/opendmtq/login.php", form, {"X-Forwarded-For": f"198.51.100.{n}"})[2].decode()
    answers.append("wrong" if "Wrong ID or password" in page_text else "held" if "Too many failed sign-ins" in page_text else page_text[:80])


guessers = [threading.Thread(target=guess, args=(n,)) for n in range(1, 33)]
for g in guessers:
    g.start()
for g in guessers:
    g.join()
check("thirty wrong guesses at an account with admin rights from anywhere, and no more", sorted(answers) == ["held"] * 2 + ["wrong"] * 30,
      str(sorted(answers)))
right = urllib.parse.urlencode({"user": "helper", "password": "hunter22", "next": "/opendmtq/"}).encode()
fresh = {"X-Forwarded-For": "198.51.100.200"}
held = request(plain, SITE + "/opendmtq/login.php", right, fresh)
client_held = request(plain, SITE + "/opendmtq/client.php?signin", urllib.parse.urlencode({"user": "helper", "password": "hunter22"}).encode(), fresh)[0]
check("then that account waits, from a new address and with its right password, on the PC client's sign-in too",
      held[0] == 200 and "Too many failed sign-ins" in held[2].decode() and client_held == 429, f"{held[0]}, {client_held}")
check("while an account without admin rights signs in as before", site_sign_in("dmtq", SITE_PASSWORD, {"X-Forwarded-For": "198.51.100.201"})[1])
account_post(action="delete", name="helper")

# The game's own window (its event page, /score/) shows the site, behind the same sign-in: a stranger goes to the sign-in,
# someone signed in to the page of the player the game's token names (or to the rankings for a token nobody has).
window = SITE + "/score/?access_token=" + urllib.parse.quote("999999|576|IPHONE|KR|x|0", safe="")
status, headers, _ = request(plain, window)
check("signed out: the game's window sends to the sign-in", status == 302 and "login.php?next=" in headers.get("Location", ""), headers.get("Location"))
status, headers, _ = request(portal, window)
check("signed in: the game's window opens the site", status == 302 and headers.get("Location", "").startswith("/opendmtq/"), headers.get("Location"))
status, headers, _ = request(plain, SITE + "/djmaxQ/index?userId=1")
check("the old score viewer address leads to the game's window", status == 302 and headers.get("Location") == "/score/", headers.get("Location"))
check("what the pages load is never a page", all(request(plain, f"{SITE}/opendmtq/{name}")[0] == 403 for name in ("lib.php", "auth.php", "live_lib.php", "ranking_lib.php", "strings.php")))
check("nor is the game server's code", all(request(plain, f"{SITE}{path}")[0] in (403, 404) for path in ("/opendmtq/../game/src/rpc.php", "/game/src/rpc.php", "/src/config.php")))

# ---------------------------------------------------------------- recordings


def rec_post(**fields):
    """A form of the recordings page, with its token; the page it leads to."""
    html = admin_page("/opendmtq/admin/recordings")
    fields["csrf"] = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    return request(admin, ADMIN + "/opendmtq/admin/recordings", urllib.parse.urlencode(fields, doseq=True).encode())[2].decode()


def recorded():
    """What the admin page lists: keys "guid/id", newest first."""
    return re.findall(r'name="action" value="(?:hide|show) (\d+/\d+)"', admin_page("/opendmtq/admin/recordings"))


def rec_media(key, name="index.m3u8"):
    """Through the portal's gate; key "guid/id"."""
    return request(portal, f"{SITE}/opendmtq/live-media.php/rec/{key}/{name}")


def new_since(before):
    """The recording that is not among those listed before. (Not simply the newest: test recordings start
    within a second of each other, and a number freed by a deleted one can be used again.)"""
    fresh = [k for k in recorded() if k not in before]
    assert len(fresh) == 1, fresh
    return fresh[0]


def broadcast(*uploads, song=False, close=True):
    """One broadcast: switched on already, these segments ([seq, body]), then the end."""
    if song:
        call("game.getPreviewPlayInfo", [guid, 1])
    for seq, body in uploads:
        assert upload(token, seq, body) == 204
    if song:
        call("game.savePlayResult", [guid, 1, [0, 0] + [0] * 10 + [50], 50, 0, [0, 0, 0], [0, 0, 0], "smoke"])
    if close:
        assert end(token) == 204


# Switching off above kept what the two broadcasts before it recorded, closed at once.
done = recorded()
check("switching off kept the recordings, none left running", len(done) >= 2 and "Recording now" not in admin_page("/opendmtq/admin/recordings"), done)
check("the portal offers them", sorted(k.replace("-", "/") for k in past()) == sorted(done), past())
check("the live window went, the recording did not", playlist()[0] == 404 and rec_media(done[0])[0] == 200)
m3u = rec_media(done[0])[2].decode()
check("a VOD playlist", "#EXT-X-PLAYLIST-TYPE:VOD\n" in m3u and m3u.endswith("#EXT-X-ENDLIST\n"), m3u)
# Seeking back in a replay does not fetch the same pieces again; the playlist itself is always asked for anew.
piece = next(line for line in m3u.splitlines() if line and not line.startswith("#"))
check("a recording's pieces are kept by the browser", "immutable" in (rec_media(done[0], piece)[1].get("Cache-Control") or ""))
check("its playlist is not", rec_media(done[0])[1].get("Cache-Control") == "no-store")
# The page's look every few seconds stays light: the recordings only when asked for.
check("the page's quick look leaves the recordings out", "past" not in json.loads(request(portal, SITE + "/opendmtq/live.php?list=1")[2]))
# The one before: 0,1,2, the same 2 again, back to 0, on to 8: 12 segments with one break, and past the
# live window of six.
m3u = rec_media(done[1])[2].decode()
check("the whole broadcast is kept, not the window", m3u.count("#EXTINF:") == 12, m3u)
check("a discontinuity where seq restarted", m3u.count("#EXT-X-DISCONTINUITY\n") == 1, m3u)
listed = admin_page("/opendmtq/admin/recordings")
check("the admin lists player, length and size", "LiveSmoke" in listed and "0:24" in listed and "MB" in listed)

# A new one, with a song, while it runs and after.
switch("live-on")
token = state()["token"]
before = recorded()
broadcast([0, segment(0, 188 * 500)], [1, segment(1, 188 * 500)], song=True, close=False)
newest = new_since(before)
check("the switch starts a new recording with the first video", newest not in done)
check("a running recording says so", "Recording now" in admin_page("/opendmtq/admin/recordings"))
check("players do not get one still running", newest.replace("/", "-") not in past() and rec_media(newest)[0] == 404)
check("it cannot be deleted", "kept" in rec_post(action=f"delete {newest}") and newest in recorded())
assert end(token) == 204
check("the end closes it", "Recording now" not in admin_page("/opendmtq/admin/recordings") and rec_media(newest)[0] == 200)
item = next(r for r in json.loads(request(portal, SITE + "/opendmtq/live.php?list=1&past=1")[2])["past"] if r["key"] == newest.replace("/", "-"))
# The song of chart 1, by whatever name this server's song list gives it.
title = (item["songs"] or [{}])[0].get("title", "")
check("its song is listed for players", title and title in item["doing"], item)
check("and for the owner", title and title in unescape(admin_page("/opendmtq/admin/recordings")), title)
before = recorded()
check("looping end and upload makes no recordings", upload(token, 2) == 204 and end(token) == 204 and upload(token, 3) == 204 and recorded() == before)
check("the video still goes out", playlist()[0] == 200)
time.sleep(31)
check("after the wait uploads are recorded again", upload(token, 4) == 204 and len(recorded()) == len(before) + 1)
assert end(token) == 204
other = new_since(before)

# Download: one file, the segments in order.
status, headers, body = request(admin, f"{ADMIN}/opendmtq/admin/recordings/{newest}/download")
check("the download is the segments in order", status == 200 and body == segment(0, 188 * 500) + segment(1, 188 * 500), (status, len(body)))
check("with a sensible name and type", re.fullmatch(r'attachment; filename="opendmtq-player\d+-\d{8}-\d{4}\.ts"', headers["Content-Disposition"]) is not None and headers["Content-Type"].startswith("video/mp2t"), headers["Content-Disposition"])
check("watching in the admin page", '/opendmtq/admin/recordings/' + newest + '/index.m3u8' in admin_page("/opendmtq/admin/recordings?watch=" + newest).replace("\\/", "/"))
check("the admin's own gate serves it", request(admin, f"{ADMIN}/opendmtq/admin/recordings/{newest}/index.m3u8")[0] == 200)

# No access without signing in, and nothing but the media.
outside = urllib.request.build_opener(NoRedirect)
first_ts = re.search(r"^(\d+\.ts)$", rec_media(newest)[2].decode(), re.M).group(1)
for name in ("index.m3u8", first_ts):
    check(f"portal, signed out: {name} refused", request(outside, f"{SITE}/opendmtq/live-media.php/rec/{newest}/{name}")[0] == 403)
    check(f"admin, signed out: {name} refused", request(outside, f"{ADMIN}/opendmtq/admin/recordings/{newest}/{name}")[0] == 302)
check("admin, signed out: no download", request(outside, f"{ADMIN}/opendmtq/admin/recordings/{newest}/download")[0] == 302)
check("admin, signed out: no list", request(outside, ADMIN + "/opendmtq/admin/recordings")[0] == 302)
check("portal, signed out: no list", request(outside, SITE + "/opendmtq/live.php?list=1")[0] == 403)
check("admin, signed out: no changes", request(outside, ADMIN + "/opendmtq/admin/recordings", b"action=delete+" + newest.encode())[0] == 302 and newest in recorded())
check("no token, no changes", request(admin, ADMIN + "/opendmtq/admin/recordings", b"action=delete+" + newest.encode())[0] == 200 and newest in recorded())
g, i = newest.split("/")
for bad in (f"rec/{g}/{i}/meta.json", f"rec/{g}/{i}/segs.log", f"rec/{g}/{i}/.open", f"rec/{g}/../../dmtq.db3", f"rec/{g}/{i}/../../../dmtq.db3",
            f"rec/{g}/{i}/%2e%2e/%2e%2e/%2e%2e/dmtq.db3", f"rec/x/{i}/index.m3u8", f"rec/{g}/x/index.m3u8", "rec/limits.json"):
    check(f"the portal's gate refuses {bad}", request(portal, f"{SITE}/opendmtq/live-media.php/{bad}")[0] in (403, 404))
# Refused either way: through Apache, whose deny list covers .log (403), or by the admin itself (404).
for bad in (f"{g}/{i}/meta.json", f"{g}/{i}/segs.log", f"{g}/{i}/..%2f..%2f..%2fdmtq.db3", f"{g}/{i}/%2e%2e%2f%2e%2e%2f%2e%2e%2fdmtq.db3", f"x/{i}/index.m3u8"):
    check(f"the admin's gate refuses {bad}", request(admin, f"{ADMIN}/opendmtq/admin/recordings/{bad}")[0] in (403, 404))
check("a made-up form name changes nothing", "Those recordings are already gone." in rec_post(action="delete ../../../dmtq") and request(plain, SITE + "/opendmtq/health.php")[0] == 200)

# Hide and show.
key = newest.replace("/", "-")
rec_post(action=f"hide {newest}")
check("hidden: gone from players at once", key not in past() and rec_media(newest)[0] == 404 and rec_media(newest, first_ts)[0] == 404)
check("hidden: the owner still has it", request(admin, f"{ADMIN}/opendmtq/admin/recordings/{newest}/index.m3u8")[0] == 200 and "Hidden from players" in admin_page("/opendmtq/admin/recordings"))
rec_post(action=f"show {newest}")
check("shown again", key in past() and rec_media(newest)[0] == 200)

# Delete: one, selected, all of a player's.
check("delete one", "Recordings deleted: 1." in rec_post(action=f"delete {newest}") and newest not in recorded() and key not in past() and rec_media(newest)[0] == 404)
check("the admin's gate has nothing either", request(admin, f"{ADMIN}/opendmtq/admin/recordings/{newest}/download")[0] == 404)
check("delete selected", "Recordings deleted: 1." in rec_post(action="delete", sel=[other]) and other not in recorded())

# Backups stay small.
html = admin_page("/opendmtq/admin/backups")
rec_keep = recorded()
request(admin, ADMIN + "/opendmtq/admin/backups", urllib.parse.urlencode({"csrf": re.search(r'name="csrf" value="([^"]+)"', html).group(1), "action": "create"}).encode())
name = re.search(r"/opendmtq/admin/backups/(opendmtq-[\w-]+\.tar\.gz)/download", admin_page("/opendmtq/admin/backups")).group(1)
archive = request(admin, f"{ADMIN}/opendmtq/admin/backups/{name}/download")[2]
with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
    inside = tar.getnames()
check("a backup holds no recording or live window", "dmtq.db3" in inside and not any("live" in n or n.endswith(".ts") for n in inside), inside)
check("and recordings stay when one is made", recorded() == rec_keep)

def next_broadcast():
    """The owner flips the switch: a new key, and a new broadcast with nothing to wait for."""
    switch("live-off")
    switch("live-on")
    return state()["token"]


# The limits. The size limit of 1 MiB is the form's smallest sensible test value.
token = next_broadcast()
rec_post(action="delete-player x")
check("delete all of a player's, none running", "deleted" in rec_post(action=f"delete-player {guid}") and recorded() == [])
big = 188 * 3800  # about 0.7 MB
rec_post(action="limits", cap_gb="0.001", days="30", confirmed="1")
check("the limits are saved", 'name="cap_gb" type="number" min="0.001" step="any" value="0.001"' in admin_page("/opendmtq/admin/recordings"))
check("nonsense limits are refused", "Size must be" in rec_post(action="limits", cap_gb="-1", days="30") and "Size must be" in rec_post(action="limits", cap_gb="1", days="x"))
broadcast([0, segment(0, big)])
oldest = new_since([])
time.sleep(1.1)
token = next_broadcast()
broadcast([0, segment(1, big)])
second = new_since([oldest])
check("over the limit when one closes: the oldest goes", oldest not in recorded() and second in recorded(), recorded())
# One still running and over the limit alone: keeps its video, the others go.
token = next_broadcast()
broadcast([0, segment(2, big)], [1, segment(3, big)], close=False)
running = new_since([second])
rec_post(action="limits", cap_gb="0.001", days="30", confirmed="1")
time.sleep(0.2)
listed = recorded()
check("a running one over the limit evicts the rest", second not in listed and running in listed, listed)
check("and is not cut: closed whole", rec_media(running)[2].decode().count("#EXTINF:") == 2)
check("the broadcast goes on, recorded anew", upload(token, 2) == 204 and len(recorded()) == 2)
rec_post(action="limits", cap_gb="0.001", days="30", confirmed="1")
check("then the one too big goes as the oldest", running not in recorded(), recorded())
assert end(token) == 204
# Two running, each under the limit, together over it: the largest closes, the other goes on.
token = next_broadcast()
rec_post(action="delete-player " + str(guid))
second_udid = f"live-smoke2-{random.randrange(10**9):09d}"
second_guid = new_player(second_udid)
switch("live-on", second_guid)
second_token = json.loads(request(plain, f"{SITE}/live/state?ids={second_udid}")[2])["token"]
broadcast([0, segment(0, big)], close=False)
assert upload(second_token, 0, segment(1, 188 * 2500), ids=second_udid) == 204
before = recorded()
rec_post(action="limits", cap_gb="0.001", days="30", confirmed="1")
html = admin_page("/opendmtq/admin/recordings")
check("two running over the limit together: one closes, the largest", html.count("Recording now") == 1 and rec_media(f"{guid}/{[k for k in before if k.startswith(str(guid) + '/')][0].split('/')[1]}")[0] == 200, before)
check("and the other goes on recording", upload(second_token, 1, segment(2, 188 * 100), ids=second_udid) == 204 and "Recording now" in admin_page("/opendmtq/admin/recordings"))
switch("live-off", second_guid)
rec_post(action="limits", cap_gb="20", days="30", confirmed="1")
rec_post(action="delete-player " + str(second_guid))
switch("live-off")
check("the disk line against the limit", re.search(r"Recordings use <b>[\d.]+ \w+</b> of 20 GB", admin_page("/opendmtq/admin/recordings")) is not None)

# Broadcasts turned off for the whole server while a player is on air: told once that the broadcast ended and that
# broadcasts are off on this server for now (the site no longer shows its replays), between songs; then on again.
switch("live-on")
token = state()["token"]
check("on air as the owner turns broadcasts off", upload(token, 0) == 204)
broadcasts_post(action="broadcasts-off")
s = state()
check("the player on air is told it ended, and that broadcasts are off for now",
      s["on"] is False and s["toast"] == "Your broadcast has ended\nBroadcasts are off on this server for now", s)
check("that notice only once", state()["toast"] == "")
switch("live-off")
broadcasts_post(action="broadcasts-on")
check("and nothing waits once broadcasts are on again", state()["toast"] == "")
rec_post(action="delete-player " + str(guid))


def poll(udid):
    """What a phone with this one device id is told when it polls."""
    return json.loads(request(plain, f"{SITE}/live/state?ids={udid}")[2])


# New players start on, as the owner sets it on the Broadcasts page, through the server itself: the players already there
# stay off, a device the server meets after that is on at its first poll, with its key and the notice (which names the
# server as the site does), and a player the owner then turns off stays off.
before_udid = f"live-smoke-before-{random.randrange(10**9):09d}"
new_player(before_udid)
broadcasts_post(action="settings", new_players="on", quality="standard")
s = poll(before_udid)
check("new players starting on leaves the players already there off", s["on"] is False and "token" not in s and s["toast"] == "", s)
newcomer_udid = f"live-smoke-new-{random.randrange(10**9):09d}"
newcomer = new_player(newcomer_udid)
s = poll(newcomer_udid)
site_name = json.loads(request(plain, SITE + "/opendmtq/client.php?about")[2])["name"]
check("a new device's first poll: on, its key, and the notice naming the server as the site does",
      s["on"] is True and re.fullmatch(r"[0-9a-f]{32}", s.get("token", "")) is not None
      and s["toast"] == f"Your play is live now\nWatch it live or later under LIVE on {site_name}", s)
switch("live-off", newcomer)
s = poll(newcomer_udid)
check("a new player the owner turns off stays off at the next poll, and the one after",
      s["on"] is False and "token" not in s and poll(newcomer_udid)["on"] is False, s)
broadcasts_post(action="settings", new_players="off", quality="standard")

# A real stream for the browser check (tests/live/browser.js), left in place.
media = os.environ.get("LIVE_TS_DIR")
if media:
    switch("live-on")
    token = state()["token"]
    before = recorded()
    files = sorted(os.listdir(media), key=lambda f: int(f.split(".")[0]))
    call("game.getPreviewPlayInfo", [guid, 1])
    for seq, part in enumerate(files):
        with open(os.path.join(media, part), "rb") as f:
            assert upload(token, seq, f.read()) == 204
    assert end(token) == 204
    switch("live-off")
    print("RECORDING", new_since(before))

# ---- scores: what a save stores, whatever else is happening.


def rpc_reply(method, params, signed=True):
    """(HTTP status, first reply of the batch or None) of one game RPC, whatever it says."""
    body = json.dumps([{"id": 1, "method": method, "params": params}]).encode()
    headers = {"Content-Type": "application/json"}
    if signed:
        headers["Fp"] = hashlib.md5(b"DMQGLBlive1" + body).hexdigest()
    status, _, reply = request(plain, SITE + "/DMQ/rpc", body, headers)
    replies = json.loads(reply) if status == 200 else []
    return status, replies[0] if replies else None


# 500 perfect notes: a real result as the phone sends it.
RESULT = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 500]
scorer = new_player(f"live-smoke-score-{random.randrange(10**9):09d}")


def saves(pattern, stats=RESULT, who=None):
    return ["game.savePlayResult", [who or scorer, pattern, stats, 500, 0, [0, 0, 0], [0, 0, 0], "smoke"]]


def records(pattern, who=None):
    """The player's own rows for one chart, as the game reads them."""
    return [r for r in call("game.getOwnPatternScore", [who or scorer]) if r["pattern_id"] == pattern]


# Any spelling PHP would still run needs the signature: a leading backslash names the same class.
for spelling in ("game.savePlayResult", "Game.SavePlayResult", "\\game.savePlayResult"):
    check(f"unsigned {spelling} is refused", rpc_reply(spelling, saves(910001)[1], signed=False)[0] == 403)
check("nothing was stored by the refused saves", not records(910001))

# Two saves of one chart at the same moment each found no row and each inserted one, summed by every
# ranking. The phone resends a result it got no answer for, so this is not only for forgers.
# Timing decides whether one round shows it, so several charts get a round each.
for chart in range(910100, 910108):
    threads = [threading.Thread(target=rpc_reply, args=saves(chart)) for _ in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
counts = [len(records(chart)) for chart in range(910100, 910108)]
check("simultaneous saves of a chart leave one row", counts == [1] * 8, str(counts))

# A result without notes or a player stores nothing, and answers what the client skips.
status, reply = rpc_reply(*saves(910003, stats=[0] * 13))
check("a result with no notes is not stored", status == 200 and reply["result"] is None and reply["error"]["code"] == "SVC.05008" and not records(910003))
status, reply = rpc_reply("game.savePlayResult", [])
check("an empty save is not stored", status == 200 and reply["result"] is None and reply["error"]["code"] == "SVC.05008")

# The saved score, on the three pages that add scores up, ranked the same on each.
for i, points in enumerate((5000, 3000)):
    other = scorer if i == 0 else new_player(f"live-smoke-score-{random.randrange(10**9):09d}")
    if i == 1:
        second = other
    rpc_reply(*saves(910010 + i, stats=[0] * 12 + [points], who=other))
scorer_page = request(portal, f"{SITE}/opendmtq/player.php?id={scorer}")[2].decode()
second_page = request(portal, f"{SITE}/opendmtq/player.php?id={second}")[2].decode()
board = request(portal, f"{SITE}/opendmtq/ranking.php")[2].decode()
listed = [int(x) for x in re.findall(r'player\.php\?id=(\d+)', board)]
rank_of = lambda page: int(re.search(r"#(\d+) overall", page).group(1))
check("a player's page gives the rank the rankings list them at",
      rank_of(scorer_page) == listed.index(scorer) + 1 and rank_of(second_page) == listed.index(second) + 1,
      f"{rank_of(scorer_page)}, {rank_of(second_page)}, {listed}")
ingame = call("game.getLineTopRankWithLevel", [0, 1, 100, [scorer]])["ranks"]
check("the game's total ranking has that order too", [r["guid"] for r in ingame][:len(listed)] == listed[:len(ingame)], f"{ingame} {listed}")
# The site's This month tab is the game's own board of the month (odq_month_board()): the same players in the same order,
# above the months before.
this_month = request(portal, f"{SITE}/opendmtq/ranking.php?sort=month")[2].decode().split('class="past-months"')[0]
monthly = [int(x) for x in re.findall(r'player\.php\?id=(\d+)', this_month)]
check("the site's This month tab ranks the month as the game does", monthly and monthly == [r["guid"] for r in ingame][:len(monthly)],
      f"{monthly} {[r['guid'] for r in ingame]}")
home = request(portal, f"{SITE}/opendmtq/")[2].decode()
check("the front page lists the top of the rankings", [int(x) for x in re.findall(r'player\.php\?id=(\d+)', home.split('id="records"')[0])][:8] == listed[:8])
# The achievements on MY PAGE (after the rankings' checks: the plays here change the rankings): a new player has those every player has (level 99, MAX POINT 999,999); one who has
# played also those their records give (ALL COMBO, PERFECT PLAY, the TOTAL SCORE steps), against the game's 34.
ALWAYS = list(range(1, 11)) + [19, 20, 21]
fresh = new_player(f"live-smoke-ach-{random.randrange(10**9):09d}")
check("a new player has the achievements every player has", [a["achievement_id"] for a in call("game.getOwnAchievementList", [fresh])["own_achievements"]] == ALWAYS)
check("the game's achievements, counted", call("game.getAchievementCount", []) == {"total_achievement_count": 34, "total_achievement_point_sum": 1288})
mine = {a["achievement_id"] for a in call("game.getOwnAchievementList", [scorer])["own_achievements"]}
best = call("game.getOwnPatternScore", [scorer])
total = sum(r["score"] for r in best)
steps = {29: 1000000, 30: 2000000, 31: 4000000, 32: 7500000, 33: 10000000, 34: 15000000, 35: 30000000}
expected = set(ALWAYS) | {i for i, v in steps.items() if total >= v} | ({13} if any(r["allcom_yn"] == "Y" for r in best) else set()) | ({14} if any(r["perfect_yn"] == "Y" for r in best) else set())
check("a player's achievements follow their records", mine - {11, 12, 23, 24, 25} == expected and all(isinstance(a, str) for a in [x["reg_date"] for x in call("game.getOwnAchievementList", [scorer])["own_achievements"]]), f"{sorted(mine)} vs {sorted(expected)} (total {total})")
# A play that earns achievements says so in its reply, in the game's own shape: a new player's first all-perfect play
# earns ALL COMBO and PERFECT PLAY; the same play again earns nothing new.
earner = new_player(f"live-smoke-earn-{random.randrange(10**9):09d}")
first = call(*saves(1, who=earner))["new_achievements"]
# The dates MY PAGE gives the achievements now. The next play comes over a second later, so that a date taken from
# the latest play (as every date once was) would show it.
dated = {a["achievement_id"]: a["reg_date"] for a in call("game.getOwnAchievementList", [earner])["own_achievements"]}
time.sleep(1.1)
again = call(*saves(1, who=earner))["new_achievements"]
FIELDS = {"achievement_id", "obtain_point", "condition_type", "condition_value", "condition_count", "condition_special", "play_count", "reg_date", "complete_yn"}
check("a play that earns achievements says so", {13, 14} <= {a["achievement_id"] for a in first} and all(set(a) == FIELDS and a["complete_yn"] == "Y" for a in first), first)
check("and the same play again earns nothing new", again == [], again)
# Each achievement keeps the date it was earned on: the play that earns nothing does not move one, and the dates the
# first play's reply gave are those MY PAGE lists (the game merges the reply into the list it shows).
redated = {a["achievement_id"]: a["reg_date"] for a in call("game.getOwnAchievementList", [earner])["own_achievements"]}
check("a player's achievements keep the dates they were earned on",
      redated == dated and all(a["reg_date"] == dated.get(a["achievement_id"]) for a in first),
      f"{dated} then {redated}; the reply gave {[(a['achievement_id'], a['reg_date']) for a in first]}")
# ALL COMBO on a chart played before without one (one break, still a clear): dated by the play that made it, over a
# second after the first, in the reply and on MY PAGE alike. The log keeps no break count; the save stores its time.
combo = new_player(f"live-smoke-combo-{random.randrange(10**9):09d}")
call(*saves(2, stats=[0, 1] + [0] * 10 + [499], who=combo))
time.sleep(1.1)
made = {a["achievement_id"]: a["reg_date"] for a in call(*saves(2, who=combo))["new_achievements"]}
shown = {a["achievement_id"]: a["reg_date"] for a in call("game.getOwnAchievementList", [combo])["own_achievements"]}
check("ALL COMBO is dated by the play that made it",
      13 in made and shown.get(13) == made[13] and shown.get(13, "") > shown.get(1, ""),
      f"the reply gave {made}, MY PAGE {shown}")

# A browser that has the stylesheet gets a 304, not all of it again with every page.
_, headers, _ = request(plain, f"{SITE}/opendmtq/style.css", headers={"Accept-Encoding": "gzip"})
status, _, body = request(plain, f"{SITE}/opendmtq/style.css", headers={"Accept-Encoding": "gzip", "If-None-Match": headers["ETag"]})
check("the stylesheet revalidates", status == 304 and not body, f"{status}, {len(body)} bytes")
# So does the live page's script, a file of its own and not part of every page: compressed, and named by its version, so
# that a browser that kept it gets the new one with the next page after an update.
named = re.search(r'<script src="(/opendmtq/live\.js\?v=\d+)"></script>', request(portal, SITE + "/opendmtq/live.php")[2].decode())
_, headers, body = request(plain, SITE + named.group(1), headers={"Accept-Encoding": "gzip"}) if named else (0, {}, b"")
status, _, again = request(plain, SITE + named.group(1), headers={"Accept-Encoding": "gzip", "If-None-Match": headers.get("ETag", "")}) if named else (0, {}, b"")
check("the live page's script comes compressed, and revalidates", headers.get("Content-Encoding") == "gzip" and status == 304 and not again,
      f"{named and named.group(1)}, {headers.get('Content-Encoding')}, {status}")

# The video player comes from this server, on both of the admin's ways in: a local network has no internet.
HLS = "/opendmtq/hls/hls-1.5.17.min.js"
_, _, script = request(plain, SITE + HLS)
check("the portal serves the pinned video player", hashlib.sha384(script).hexdigest().startswith("f6fdc7"), hashlib.sha384(script).hexdigest()[:12])
check("the admin's own port brings the same file", request(admin, ADMIN + HLS)[2] == script)
check("the live page names no other site for it", b"cdnjs" not in request(portal, SITE + "/opendmtq/live.php")[2])

# A player left on for what run.sh tests from inside the server.
last_udid = f"live-smoke3-{random.randrange(10**9):09d}"
last_guid = new_player(last_udid)
switch("live-on", last_guid)
print("HARNESS", last_udid, json.loads(request(plain, f"{SITE}/live/state?ids={last_udid}")[2])["token"], last_guid)

print(f"{failures} failure(s)")
sys.exit(1 if failures else 0)
