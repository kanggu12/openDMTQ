# Live broadcasts

![The live page: a player's broadcast, who is on air, and past broadcasts](images/live.jpg)

A player's play can be shown on the site as a live broadcast. It is off by default. The owner turns it on for a player
on the admin pages, or for everyone with `LIVE_DEFAULT=on`. The game then shows that player a short message between
songs, when it is turned on and when it is turned off. Playing is not affected: the phone encodes and uploads on its own
threads, and drops video rather than hold the game up.

Broadcasting needs Android 8 or newer, for its video encoder, on a phone or a tablet. The app must include the arm32
bundle, which the server's app builder adds by itself. The bundle also holds the shim used on phones that still run
32-bit apps. On an older device a switched-on player's row stays at "Waiting"; they can still play and watch.

<p align="center">
  <img src="images/fig-live-flow.svg" alt="A live broadcast: once the owner turns a player's broadcast on, the phone asks about every 15 seconds and uploads a two-second MPEG-TS segment every two seconds; a browser plays it with hls.js about ten seconds behind; switched off, the next upload gets a 403; ended on the phone, the playlist ends and the recording is closed, and a past broadcast plays as a recording with its songs as chapters" width="100%">
</p>

## Using it

While someone is on air the site's home page shows a card for each: a picture of the broadcast, how long it has run, who
and what they play. The browser takes the pictures from the stream itself, for those signed in to watch (one segment per
player, every half minute at most); others see the card without one. The live page's player has the LIVE mark and the
running time on the picture, and the player's name and profile under it.

- **For everyone by default:** `LIVE_DEFAULT=on` in `.env` starts each player's switch on, with the same
  notice in the game. Players turned off in the admin pages stay off.

- **Turn it on:** admin pages, Players, Turn on in the player's Broadcast column. The column then says "Waiting" until
  video arrives, and "On air" with a Watch link while it does. The Status page counts the players broadcasting now.
- **Find it:** LIVE is in the site's main menu on every page, with a small count while someone is on air. While someone
  is, the home page has a section listing them with nickname and song, and the rankings and player pages show a small
  LIVE link next to their name. Those lists, like the rest of the site, are for those signed in.
- **Watch:** `/opendmtq/live.php`, after signing in on the site with an account (made on the admin pages' Accounts page;
  the same as for every page of the site). `live.php?p=<player>` links to one player: it plays them, or says it waits
  for them and starts by itself when they go on air.
- **Past broadcasts:** the same page lists recordings the owner has not hidden, and `live.php?r=<player>-<id>` links to
  one.
- **Turn it off:** Turn off in the same place. The next upload is refused, which stops the device. The live window is
  deleted at once; the recording stays.

While a broadcast is live, the video player shows a LIVE mark and a few controls: play and pause, sound, connection
details, picture in picture, a wider view, full screen. It has no timeline, because viewers see what is going out now. A
viewer who falls behind, or resumes after a pause, is brought back to the newest picture. On a connection too slow for
that, a button on the picture skips ahead. The other players on air are beside the picture, one press away, and the
page does not reload.

Past broadcasts have the same controls with a timeline, a REPLAY mark, ten seconds back and on, the speed (up to double), the
songs marked on the timeline and listed as chapters, and keyboard keys (space to play and pause, the arrow keys for five seconds,
s for the speed, m for sound on and off, f for full screen, and on a phone a double tap on either side of the
picture). A recording left half-way goes on from there next time,
and says so. At its end the page offers it again, or the next one. The list beside it can be searched by player or song, and
narrowed to one player.

For someone on a slow connection a recording needs a moment to fill its buffer (the stream is about 2.3 Mbit/s, and there is
no lower quality to fall back on: that would take the server transcoding every broadcast).

The video shows the game's picture and sound. Nothing else on the device is captured.

## Limits

Each stream is 720p at 30 frames per second and 2 Mbit/s, plus sound: about 1 GB an hour of upload for the player, and
the same again for each viewer, through the server's own connection. Viewers are roughly 10 seconds behind the phone, as
usual for HLS: a segment is two seconds, the phone records and uploads one before it can be served, and the player stays
two segments behind the newest.

## Endpoints

On the site's public port, plain HTTP and HTTPS alike, answered by `server/game/live/state.php`, `upload.php` and
`end.php`. `ids` is every device id the phone knows, comma
separated, at most 16, each `[A-Za-z0-9._:-]{1,128}`. Account rows with those ids are matched as the
game matches them; a player switched on wins over a forgotten old account on the same phone.

| Request | Answer |
|---|---|
| `GET /live/state?ids=...&lang=ko\|en` | JSON `{"on", "token" (only when on), "fps", "height", "bitrate", "segment", "toast"}` |
| `POST /live/upload?ids=...&seq=<n>&dur=<ms>` with `X-Live-Token`, body one MPEG-TS segment | `204` stored; `403` off or wrong token, the phone stops; `400` bad numbers, not MPEG-TS, under 1880 bytes or fewer bytes than announced; `411` no `Content-Length` (chunked); `413` over 4 MiB; `503` could not store it or the disk is nearly full, try the next one |
| `POST /live/end?ids=...` with `X-Live-Token` | `204`; `403` as above. Ends the playlist. |

- `token` is random and new each time the switch is turned on.
- `toast` is set when the owner flips the switch and returned once, and only outside a song. A song
  starts with `game.getPreviewPlayInfo` or `game.getPatternUrl`. It ends with `game.savePlayResult`
  or `game.savePlayResultFailLog`. A quit song sends no result, so a menu request more than 10 seconds
  after the start ends it too, and after 20 minutes it counts as over regardless.
  `odq_live_seen()` in `server/game/src/live.php` watches for these for every player, since
  the owner may flip the switch during a song: one small write when a song starts and one when it ends.
- `seq` is 0 to 2147483647 and restarts at 0 with the app. A number that does not follow on from the
  last adds `#EXT-X-DISCONTINUITY`. The same number twice in a row is a retry: `204` and not stored
  again.
- `dur` is 1 to 30000.
- The body must start with the MPEG-TS sync byte and be at least 1880 bytes, ten packets.

`server/apache/site.conf` caps `/live/upload` at 4 MiB and `/live/state` and `/live/end` at 8 KiB. On
Kubernetes the router's `client_max_body_size` (`templates/router-config.yaml`) applies first, and
`/live/upload` has its own location there with 4 MiB.

On Kubernetes, live broadcasts work with the chart's single api pod and no more: the window and open
recordings are that pod's files, with no shared storage or routing by player for a second one. When
the pod is replaced the window is rebuilt from the next uploads, and recordings are lost unless
`live.recordings.persistence` gives them a claim. See [kubernetes.md](kubernetes.md#live-broadcasts).

## Storage

`data/state/live/<guid>/` (`/data/live` in the container): up to eight `<n>.ts` segments (six in the
playlist, two more for a viewer still fetching what it read just before), `index.m3u8`, `stream.json`
and a lock file. Files are written to a temporary name and renamed, so a viewer never reads half a
segment. `n` counts up for the life of the folder, independent of the phone's `seq`.

| When | What happens |
|---|---|
| No upload for 15 seconds | No longer listed as live |
| No upload for 30 seconds | The playlist is served with `#EXT-X-ENDLIST`; the next upload starts a clean window |
| No upload for 5 minutes | Files removed, at most once a minute, when any phone or visitor asks |
| Switch turned off | Folder removed at once, the recording closed and kept |
| Player deleted | Folder and all their recordings removed at once |
| Server start | Everything under `data/state/live` removed |

These requests stay out of the access logs: a phone polls and uploads constantly, and device ids are
in the addresses.

The cleanup runs at most once a minute, on any request. The health check makes one every 30 seconds.

The switch is the `LiveSwitch` table in the game database, created by `server/game/bin/setup-db.php` at every
start. A backup carries it. Restoring a backup from the admin pages keeps the switches as they are now, so that a
restore never starts showing a player who has since been turned off; `opendmtq restore` on the
command line brings back those in the backup. Video and recordings are not backed up.

## Recordings

Every broadcast is recorded: about 1 GB per hour (2 Mbit/s of video and the sound), or 20 hours of
broadcast in the default limit. The owner manages them on the admin pages' Recordings page: watch, download
as one MPEG-TS file, hide from players, delete, and set the limits.

`data/state/live-rec/<player>/<id>/` (`/data/live-rec`), `id` being the start in epoch seconds: the segments,
`segs.log`, `songs.log`, and once closed `index.m3u8` (a VOD playlist) and a complete `meta.json` (player,
started, ended, length, size, songs). `limits.json` next to the player folders holds the limits. Segments are
hard links to the live window's files, so an upload writes each one once; the window's sliding only removes
the other name. Where a link is impossible (the two folders on different mounts) it copies instead.

| When | What happens |
|---|---|
| First video after the switch goes on | A new recording starts; a switch without video makes none |
| Silence under 5 minutes | The same recording goes on, with a discontinuity |
| Silence of 5 minutes or more | The cleanup closes it (a phone that vanished); the next video starts a new one |
| `/live/end`, switch off | Closed; the next video starts a new one. After `/live/end` within 30 seconds of the recording's start, video in the rest of those 30 seconds is broadcast but not recorded |
| 1800 segments, an hour at two seconds each | Closed; the next video starts a new one (a long broadcast is kept as hour-long recordings) |

**Limits:** a total size, 20 GB by default, and an age, 30 days by default, both set on the Recordings page
(1 GB is 1024 MiB here, as everywhere on that page). They are enforced when a recording closes and by the
cleanup while one grows. The oldest closed recordings go first, hidden ones included, and at most 2000 are
kept however small. A running recording is never cut. If the total is still over the limit, the largest
running ones are closed whole, their broadcasts go on in new recordings, and the closed ones go as the oldest
at the next check, so phones left on cannot fill the disk, however many. The disk itself also counts: 1 GiB
stays free whatever the limit says, and with less than that and one segment free, uploads get `503` before
anything is written.

**Hide and delete** act at once: the gate refuses a hidden or deleted recording's playlist and segments on
the next request, and an open page drops it from its list within five seconds. A running recording can be
hidden but not deleted.

Recordings need the same sign-in as watching live, or the owner's sign-in for the admin pages. Backups never include
them. See [admin.md](admin.md).

## Who can see it

`server/portal/live-media.php` serves the playlist and the segments, only to a browser signed in on
the site, and only while the player's switch is on; a recording, under `/rec/<player>/<id>/`, only when it
is closed and not hidden. Neither folder is under any web root. The site's page, its list and the media all
need the same sign-in. Who is on air, with nickname and song, shows on the site's other pages too, to those
signed in.

## Testing

The pages, the player and its controls are tested in a real browser by `tests/ui/run.sh`, in CI too
([testing.md](testing.md)).

`tests/live/run.sh` builds the images from the working tree and runs `tests/live/smoke.py` against a
throwaway server and admin service on loopback, with an empty database. It needs the game data and the songs in
`data/content` and Docker, so it does not run in CI (`tests/qa.sh` runs it). `BROWSER=1` also plays a real recording in headless Chromium
(`tests/live/browser.js`), and in a Chromium with a sound card that records, whose output has to match the
recording almost to the bit (`tests/live/sound`). Never point `smoke.py` at a server people play on: it makes
accounts and flips switches.
