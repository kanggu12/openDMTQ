#!/usr/bin/env python3
"""Broadcasts for the pages' tests, by the real routes: the owner's switch in the admin pages, the phone's upload and end.

feed.py record       closed recordings: with songs, without, under a long name.
feed.py air <secs>   two players on air until the time is up: one in a song, one between songs. Ends both broadcasts.

Reads SITE_URL, ADMIN_URL, ADMIN_PASSWORD, SITE_CONTAINER and SEGMENTS (a folder of 0.ts, 1.ts ... two seconds each).
"""

import http.cookiejar
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SITE = os.environ["SITE_URL"]
ADMIN = os.environ["ADMIN_URL"]
# The admin pages need their sign-in cookie; the phone's routes do not.
SIGNED_IN = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
PLAIN = urllib.request.build_opener()
SEGMENT_MS = 2000
# Charts of the made-up songs (make_content.php gives every song nine, in order): of the first, of the second, and of the 25th,
# whose name is the longest.
FIRST_CHART, SECOND_SONG_CHART, LONG_NAME_CHART = 1, 14, 221


def request(opener, url, data=None, headers=None):
    """Status and body of one request; an error status is an answer here, not an exception."""
    req = urllib.request.Request(url, data, headers or {})
    try:
        with opener.open(req, timeout=20) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def sign_in():
    """The admin pages, as the owner."""
    fields = urllib.parse.urlencode({"name": "admin", "password": os.environ["ADMIN_PASSWORD"]}).encode()
    status, _ = request(SIGNED_IN, ADMIN + "/opendmtq/admin/login", fields)
    assert status == 200, status


def switch(guid, on):
    """The owner's broadcast switch for one player, as the players page sends it, with the row's own token of who it is."""
    page = request(SIGNED_IN, ADMIN + "/opendmtq/admin/players")[1].decode()
    csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    seen = re.search(rf'action="/opendmtq/admin/players/{guid}"[^>]*>\s*<input type="hidden" name="csrf" value="[^"]+"><input type="hidden" name="seen" value="([^"]*)"', page)
    fields = {"csrf": csrf, "action": "live-on" if on else "live-off", "seen": seen.group(1) if seen else ""}
    status, _ = request(SIGNED_IN, f"{ADMIN}/opendmtq/admin/players/{guid}", urllib.parse.urlencode(fields).encode())
    assert status == 200, status


def sql(statement):
    """A statement on the server's database, from inside the server: its user owns the file."""
    code = '$d = new SQLite3("/data/dmtq.db3"); $d->busyTimeout(5000); $d->exec($argv[1]);'
    subprocess.run(["docker", "exec", os.environ["SITE_CONTAINER"], "php", "-r", code, statement], check=True)


def in_song(guid, chart, later=0):
    """What the game's own request at a song's start does (opendmtq_live_playing): the stream knows the song from here on.
    later: how many seconds into the broadcast the song starts, as these uploads come much faster than a phone's."""
    sql(f"UPDATE LiveSwitch SET playing = 1, pattern_id = {chart}, play_at = strftime('%s', 'now') + {later} WHERE guid = {guid}")


def song_over(guid):
    sql(f"UPDATE LiveSwitch SET playing = 0 WHERE guid = {guid}")


def token_of(guid):
    """The upload key the phone is told while the switch is on."""
    status, body = request(PLAIN, f"{SITE}/live/state?ids=ui-{guid}&lang=en")
    assert status == 200, status
    return json.loads(body)["token"]


def upload(guid, token, seq, body):
    status, answer = request(PLAIN, f"{SITE}/live/upload?ids=ui-{guid}&seq={seq}&dur={SEGMENT_MS}", body,
                             {"Content-Type": "video/mp2t", "X-Live-Token": token})
    assert status == 204, (status, answer[:200])


def end(guid, token):
    request(PLAIN, f"{SITE}/live/end?ids=ui-{guid}", b"", {"X-Live-Token": token})


def segments():
    """The test video's pieces, in order."""
    folder = os.environ["SEGMENTS"]
    names = sorted((f for f in os.listdir(folder) if f.endswith(".ts")), key=lambda f: int(f.split(".")[0]))
    return [open(os.path.join(folder, name), "rb").read() for name in names]


def recording(guid, charts, pieces):
    """One whole broadcast: its songs one after another over the video, then its end."""
    switch(guid, True)
    token = token_of(guid)
    # Each song starts at its share of the video, as many as there are.
    starts = {len(pieces) * n // len(charts): chart for n, chart in enumerate(charts)}
    for seq, body in enumerate(pieces):
        if seq in starts:
            song_over(guid)
            in_song(guid, starts[seq], seq * SEGMENT_MS // 1000)
        upload(guid, token, seq, body)
    song_over(guid)
    end(guid, token)
    switch(guid, False)
    # A recording's number is the second it started.
    time.sleep(1.1)


def record():
    pieces = segments()
    # Three songs, the last chart being of the song with the longest name; none; one, under the longest player names.
    recording(1, [FIRST_CHART, SECOND_SONG_CHART, LONG_NAME_CHART], pieces)
    recording(1, [], pieces[:6])
    recording(4, [FIRST_CHART], pieces[:6])
    recording(5, [LONG_NAME_CHART], pieces[:6])


def air(seconds):
    pieces = segments()
    who = (1, 5)
    tokens = {}
    for guid in who:
        switch(guid, True)
        tokens[guid] = token_of(guid)
    # Sena is in a song, the other between songs.
    in_song(1, LONG_NAME_CHART)
    # Told to stop early (the stage is over), it ends the broadcasts all the same.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        start = time.time()
        seq = 0
        while time.time() - start < seconds:
            body = pieces[seq % len(pieces)]
            for guid in who:
                upload(guid, tokens[guid], seq, body)
            seq += 1
            time.sleep(SEGMENT_MS / 1000)
    finally:
        song_over(1)
        for guid in who:
            end(guid, tokens[guid])
            switch(guid, False)


if __name__ == "__main__":
    sign_in()
    if sys.argv[1] == "record":
        record()
    else:
        air(int(sys.argv[2]))
