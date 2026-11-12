# Testing

Everything OpenDMTQ is tested with, where it runs, and what stands between a change and a live server. The cases themselves,
one table per area with what checks each, are in [test-cases.md](test-cases.md).

The game's files cannot go in this repository, and so not on GitHub's machines either. That splits the tests in two: what runs
in CI on every push, without them, and what runs on a machine that has them (`tests/qa.sh`). A release and a deploy ask for
both.

<p align="center">
  <img src="images/fig-testing-gates.svg" alt="Testing. A push or a pull request runs ci.yml on GitHub, without the game's files: the arm32 build, the unit tests and checks, a host install on Ubuntu and Debian, the images, the contract, an upgrade from the last release and the pages, the PC client's tests and screens, and three builds for Windows checked on a Windows runner: the player for Windows and the Windows bundle, each under Wine first, and the PC client's installer. tests/qa.sh runs on a machine with the game's files: shell, tools, cli, client, game, live, ui, upgrade and host, and the tour on an emulator with EMULATOR=1; it sets the commit status qa/local. With both passed, a tag v* runs release.yml, and ./opendmtq deploy updates a server" width="100%">
</p>

## What runs where

| Level | What | Command | Where | Game files |
|---|---|---|---|---|
| Unit | The admin pages and their API, the patcher, song packages, certificates (`tools/tests`) | `docker run ... python3 -m unittest discover -s tests -t .` in the tools image | CI, `qa.sh` | no |
| Unit | The command line (`cli/tests`), on the oldest Python it supports too | `(cd cli && python3 -m unittest discover -s tests -t .)` | CI, `qa.sh` | no |
| Unit | The broadcast's transport stream writer | see `ci.yml` | CI | no |
| Scripts | ShellCheck on every script, at the version GitHub's runners have | see `ci.yml`, `shell_tests` in `tests/qa.sh` | CI, `qa.sh` | no |
| PHP syntax | Every PHP file of the game server, the site's pages and the test helpers, on PHP 8.3 | see `ci.yml` | CI | no |
| Edge proxy | Its two configurations, and a port that stays open on plain HTTP when the certificate cannot be used | see `ci.yml` | CI | no |
| Build | The arm32 runtime and shim, both images, the Helm chart against Kubernetes' schemas, a start without game files | see `ci.yml` | CI | no |
| Windows player | The runtime's guest programs with the Windows runner, the player's Java VM, mixer, video reader and PC settings file: under Wine, then on Windows itself; the broadcast's requests on the player's own sockets, under Wine | `arm32/test_windows.sh` (Wine), `arm32/test_windows.ps1` (Windows) | CI (`arm32-windows`, `arm32-windows-real`) | no |
| Guest file names | Where the player for Windows puts each name the game gives: the app's folders as before, the runtime's own names, everything else in a folder of the app's data; no name reaching past them; and the guest's system, the app's libraries and its APK read only, by any spelling (`arm32/tests/host/guest_paths_test.cpp`) | see `ci.yml` | CI | no |
| Video reader | The player's MP4 reader on files made to break it (a box size that steps back, a sample count or a sample larger than the file, many chunks and runs): each turned away or read as far as it is true, within a second and in bounded memory (`arm32/tests/host/mp4_test.cpp`) | see `ci.yml` | CI | no |
| The player's HTTP | The player's requests to the game server, on stand-in servers: each asks for gzip as a phone's does, unless the game chose its encodings; an answer compressed for it inflated whole, with a length, in chunks or until the connection closes, read in any pieces, without the compressed body's headers; one cut short, broken, followed by more or inflating past 64 MB fails as a lost connection does, after no more than that; every other answer as it always was (`arm32/tests/host/http_test.cpp`) | see `ci.yml` | CI | no |
| PC client | The launcher's logic on a stand-in server and player (`client/tests`), then every page, the first-start guide and the dialogs on a virtual screen, in both languages at three window sizes and at 200 %, with a layout check | `(cd client && python3 -m unittest discover -s tests -t .)` (it needs Python with Tk, Pillow and fontTools; CI runs it in the image of `client/tests/ui`), `client/tests/ui/run.sh <folder>` | CI (`client`), `qa.sh` | no |
| PC client on Windows | The installer as a release builds it, installed silently on Windows itself for the runner's user; its command line (its version, no server yet, the player found), the player's sound devices without a window, the same installer again as a repair, the launcher's Repair of a file of the player gone, and Uninstall with the data: the program, its shortcuts and the data gone | `client/tests/windows/install.ps1` | CI (`client-build`, `client-windows`) | no |
| PC client, end to end | The installer as the site hands it out, under Wine against a throwaway server: installed through its own dialog, the first-start guide, the sign-in, the app's download, PLAY, Alt+F4 doing nothing, the bar at the game's top edge switching to a window and back, in the window no buttons of its own, the bar's minimise and the taskbar's restore, a minimise and a restore with the bar down as Windows makes them (the window's pop-ups hidden and shown again: the bar stays gone), its X asking with the game held still, Keep playing, then Quit the game, the launcher back; then Repair, a file of the player and one of the launcher put back as installed; Clear game data, after which the game starts again with the same id; Uninstall with the data, refused while the window is open, then the program, its shortcut and the data gone | `client/tests/windows/e2e.sh` | by hand, with a change to the client or the player | yes |
| Broadcast colours | The colours a broadcast from Windows says it has (`arm32/tests/host/live_sps_test.cpp`) | see `ci.yml` | CI | no |
| Broadcast requests | A phone's and the player's requests to the server, on stand-in servers: each within its deadline whether the server answers a byte at a time, not at all or takes no body, or the name's lookup does not answer; an answer too long as none; the server's answer read as meant and odd JSON as nothing; the ids that go in a URL; the upload queue and the quality steps the uploads take (`arm32/tests/host/live_net_test.cpp`); the same test built for Windows, under Wine on the sockets the player for Windows uses (`arm32/test_windows.sh`) | see `ci.yml` | CI | no |
| Frame limits | Which displays and frame limits keep every frame of the player for Windows on the same number of refreshes, and which go by the clock; by the clock, each frame one frame's time after the last whatever the game's limiter does, and no burst after a late one (`arm32/tests/host/pacing_math_test.cpp`) | see `ci.yml` | CI | no |
| Following the display | The frame rate's steps with a display and a game the test plays: a computer's 240 Hz display keeping every refresh with a fifth of its frames late, to every second refresh after three windows with more than a quarter late, every refresh again 5 s later, back down in the first window of a try that falls short and 10 s before the next, a computer that makes 130 frames a second settling at 120 between tries a minute apart at most; vsync off at its limit; a phone's 120 Hz panel to 90, 72 and 60, one that stays at 120 Hz to 60; the heat's step every half minute (`arm32/tests/host/follow_test.cpp`) | see `ci.yml` | CI | no |
| Contract | Every reply of the game server the client depends on, its quirks, a save under a held lock, players' names that are no UTF-8, and not one PHP warning | `tests/game/protocol.sh` (`protocol.py`, `lock.php`, `names.php`) | CI, `qa.sh` | no |
| Pages | All pages at five screen widths in both languages, empty and full, on air, under maintenance and with broadcasts off; the replay player and the owner's forms | `tests/ui/run.sh` | CI, `qa.sh` | no |
| Upgrade | The last release's images used as people use them (players and plays, a site account, an API token, the recordings' limits, a broadcast with its recording, a backup), then this tree's images on the same data: nothing lost, every route of the API and what it answers, the backup restored; then the same from this tree's own images, as a restart | `tests/upgrade/run.sh` (`FROM=<version>` for another release) | CI, `qa.sh` | no |
| Server | The real game files: every request the game makes, broadcasts, recordings, sign-ins | `tests/live/run.sh` (`BROWSER=1` adds a real video) | `qa.sh` | yes |
| Shared server | Eight players on a server held to two cores with 300 players and a million plays, while one address saves as fast as the edge lets it, two players broadcast to thirty browsers, and a backup and a build of the app run: every save stored, every segment taken, the server's memory sampled. Then the server killed mid-save and started again: nothing it answered as stored lost, its database whole. Then a full disk under the database: each save refused with the code the game retries on, nothing half kept, the server answering, and saves stored again once there is room | `tests/load/run.sh` | `qa.sh` | yes |
| Host install | The README's one command (`host/get.sh`, `host/install.sh`) on a clean system in a container, `./opendmtq setup`, then its setup in the browser (the one-time link, the files found and imported, an account, the app, another address and the restart), the contract, the pages, stop and start | `tests/host/run.sh` (`DISTRO=debian:12`; `APK=<file>` also builds the app) | CI (Ubuntu 24.04, Debian 12), `qa.sh` (with the app) | no (yes with `APK`) |
| Windows bundle | The bundle built from its pinned downloads, every program's DLLs found, then run: under Wine on Linux (a first start with no settings, then started as a double-click starts it, through the setup's sign-in, what it says of each file, import and restart, and with `APK=<client>` the phone app's build), and on Windows itself in a folder with a space; the import, the contract, the admin pages, nothing left running after its window | `host/windows/build.sh`, `tests/windows/wine.sh`, `tests/windows/run.ps1` | CI | no |
| Client | Every edit of the patcher finds its bytes, settings and screen objects in the real game clients, each in its own version | `tools/tests/test_real_client.py` (`OPENDMTQ_BASE_APK`; `CLIENTS=<folder>` for `qa.sh` adds the APKs in it) | `qa.sh` | yes |
| Sound | What leaves the phone comes out of the browser whole | `tests/live/sound/run.sh` | by hand, with a change to the sound path | yes |
| Closed network | [Without internet](closed-network.md), step by step, on a network with no way out: Docker Compose from a release's images, a host install from what is carried in, the chart. The host install's kit leaves out the PC client's installer, and nothing here checks the installer. The Windows bundle has the test too | `tests/closed/run.sh`, `CLOSED=1 tests/windows/wine.sh` | by hand, with a change to how a server gets its programs | stand-ins; a client for the app (`APK=`) |
| Game, closed | The real game on an emulator that reaches the server and nothing else: the tour, a song to its result, the shop, a server with no songs and the songs coming later | `tests/closed/game.sh <folder>` | by hand, with a change to how the app reaches the server | yes |
| Failover | The Kubernetes deployment losing its pods and a node | `tests/ha/failover.sh` | by hand, with a change to the chart | yes |
| Game | Install from nothing, first start, lobby, menu, options, shop, second start, on an emulator | `tests/game/tour.sh <folder>` (`EMULATOR=1 tests/qa.sh`) | by hand, with a change to the patcher | yes |
| Device | Real phones, by ear and by hand | the `hand` rows of [test-cases.md](test-cases.md) | before saying it works there | yes |

On a busy machine the closed game test can stall at a song's loading screen, with client 1.3.4 and 1.3.5 alike: the
game's own audio output (FMOD, writing to an `AudioTrack`) waits on the emulator's audio, and the game's threads wait on
it. On 2026-11-07 it stalled in 7 of 17 song starts while the machine also built, tested or ran a second copy of the
game, and in none of 12 on an otherwise idle machine. No stall was in OpenDMTQ's own code, which never waits there. A
run that stalls fails at "the song's score reaches the server".

## Tests without the game's files

`tests/game/protocol.sh` and `tests/ui/run.sh` need Docker, Python 3, `curl` and GNU coreutils, and none of the game's
files. They start the server by its **real start script** on stand-in game files (`tests/ui/make_content.php`): made-up
songs, plain coloured jackets, and a client data folder with an empty manifest, which is all the server checks for. No
game code or data is in them.

`tests/game/protocol.py` then goes through what the client sends, request by request, and checks each reply the client
reads and each quirk it depends on (an empty news list closes the game, for one). Each check names the client
behaviour it protects. A new method of the game server gets its checks there. `protocol.sh` gives that server the song
list the tools write once the owner hides a song, the last stand-in song hidden: a play of a hidden song's chart is kept,
one of a chart no song has is not.

In `tests/ui/run.sh` a real browser then takes the server through a life, in stages (`tests/ui/audit.js`):

| Stage | State | Looks at |
|---|---|---|
| `self` | | One planted fault of each kind (`defects.html`): a checker that stopped seeing something must not pass as a page without faults |
| `empty` | Nothing on the server | Every page, at a phone's and a laptop's width, in both languages |
| `full` | Players, plays, recordings, an app | Every page, at 360, 744, 1024, 1280 and 1920, in both languages |
| `air` | Two players broadcasting | The video playing; the pages that change |
| `maint` | Maintenance on, by the owner's form, with a long message | Every page that shows the notice; then off again |
| `flows` | | What people do: language, sign-in, searches, the replay player on a laptop and a phone, the owner's forms |
| `quiet` | Broadcasts off for the server, with the players, records and recordings in place | The pages that showed broadcasts, at 360, 744, 1024, 1280 and 1920, in both languages: nothing of broadcasts left on the site, each page whole without them; the owner's pages say they are off |
| `down` | The game server stopped | The owner's pages keep their look and say what is wrong |

On each view `layout.js` measures what can be measured about a page: text cut off, past its box, on other text or under another
box; rows and columns out of line; anything past the screen; a box that scrolls sideways; an ordinary word split over two
lines; a sentence a column or grid box cuts into lines of their own; a placeholder wider than its box; too little contrast; a control still in the browser's own look; a class no stylesheet
mentions; something too small to press; a picture that did not load. A failed
request or a script error also counts. The findings, the list of results and screenshots end up in the report folder
(`_work/ui-report`), and in CI as the workflow's `ui-report` artifact.

A rule that fits a page on purpose goes on that page's element as `data-layout-ok`, with the reason in a comment, not in the checker.

`tests/upgrade/run.sh` starts the last release's published images on the same stand-in files and an empty data folder, and
`tests/upgrade/upgrade.py` uses them the way people do: two phones play, the owner makes a site account and an API token, sets
the recordings' limits, turns the daily backup off and a player's broadcast on, the phone broadcasts a song, and the Backups
page makes a backup. Both services are stopped, this tree's images start on that data folder, and everything is asked for
again: the phones are the players they were and read what they read, every route of the API is still there, each answer that
holds the data folder's data is the same value for value, the account signs in, the recording plays, new plays and
broadcasts are saved, and the backup restores. A second server, which nobody broadcast on, must keep broadcasts off. Each
server is upgraded once more on a copy of its data with the admin service up first and alone, so that either service may be
the first to look at the old data. Then all of it runs from this tree's own images, which is a restart. A PHP warning or an
error in the upgraded services' logs fails it too.

It takes the newest release in CHANGELOG.md whose images there are: pulled from the registry, or loaded beforehand with
`docker load` on a machine with no way out.

## The gates

**CI** (`.github/workflows/ci.yml`) runs on every push to `main` and every pull request.

**The local gate** (`tests/qa.sh`) runs on the commit that is checked out, on a clean tree, and sends GitHub the commit status
`qa/local` when everything passed. `--no-status` runs it on a tree with changes, for a look. Its report, with each step's whole
output, is in `_work/qa/<commit>`; the newest five are kept.

**A release** (`.github/workflows/release.yml`, a tag `v*`) first checks that the tag, the chart and CHANGELOG.md name one
version (`.github/release_notes.py`), runs CI again on the tag's commit, asks for `qa/local`, and only then publishes the
images, the chart, the runtime for newer phones, the player for Windows, the Windows bundle, the PC client (its
installer, `OpenDMTQ-Setup.exe`, and the packages installed clients update themselves from) and the GitHub release, whose notes are that version's section of the changelog.
`gh workflow run release.yml` rehearses it on any commit: all the gates, with the chart's own version, and nothing
published.

**A deploy** (`./opendmtq deploy`) puts the commit that is checked out on this machine's server:

1. It refuses changes that are not committed: a deploy is of a commit. (`./opendmtq up` runs whatever is here.)
2. It asks GitHub whether CI and `qa/local` passed on that commit. `--no-gates` goes ahead anyway, and says so.
3. It asks the server whether anyone is in a song. `--now` goes ahead anyway.
4. A backup, then `up`, then the end-to-end check (`./opendmtq check`). When that fails it says the way back.

## Adding a test

- A new behaviour gets a row in [test-cases.md](test-cases.md) that points at what checks it, as `` `file#text` ``:
  `cli/tests/test_repo.py` fails when the file or the text is gone, and when a unit test file of the tools, the command
  line or the PC client is in no row at all.
- A new page goes in the lists at the top of `tests/ui/audit.js`, in each state where it looks different.
- Something a person found on a page that the checker did not: first a planted case in `defects.html` and the check in
  `layout.js`, then the fix.

## Measurements

The charts here and in the README come from runs like these, on a Ryzen 9 9950X with the server held to two cores.
The data is made up: 300 players and a million plays, and for the pages 1,500 charts, 200 MB of added songs, two full
request logs, and a home folder with 5,000 files and 600 folders.

- **The game's requests:** `REQUESTS=1 tests/load/run.sh`. The server's container on two cores of its own
  (`--cpuset-cpus`), 300 players and a million plays over 90 days on the owner's songs. Eight threads, each as a phone
  with its own account, send one kind of request back to back for six seconds (signed as the client signs). The chart
  shows the median, the 95th percentile and the answers a second. A save is the client's two requests, the result and
  the player's rank on the song. The ranking of every chart is kept until the next play, so these looks read what the
  first one kept; the first look after a play took 103 ms.
- **Before and after:** one request or page at a time on the code before and after the tuning, in the same container
  (`docker run --cpus 2`): the pages through their real paths in the test client, best of five (of two for the backup);
  0.9.4's three by the server's own handlers timed in its PHP (the median of ten to fifteen calls) and the rankings page
  by HTTP, on the requests' server and data.

<p align="center">
  <img src="images/chart-tuning.svg" alt="Before and after tuning: the in-game ranking of every chart from 100 to 0.9 milliseconds; the in-game ranking of one song from 190 to 6.3 milliseconds; the Logs page looking for new lines from 460 to 21 milliseconds; a backup with 200 MB of added songs from 8 seconds to 528 milliseconds; the site's rankings page from 90 to 6 milliseconds; saving a play, in the server, from 19 to 1.6 milliseconds; four threads on one counter in the runtime from 2.9 seconds to 250 milliseconds; the setup searching a full home folder from 143 to 20 milliseconds; the Songs page from 322 to 68 milliseconds; the Status page from 294 to 152 milliseconds; the Players page from 278 to 174 milliseconds" width="100%">
</p>

- **The phone and the runtime:** [arm32/README.md](../arm32/README.md) says how each was measured, on a Galaxy S26 Ultra and
  on the emulator.
- **Failover:** `tests/ha/failover.sh`, [kubernetes.md](kubernetes.md#measured).
