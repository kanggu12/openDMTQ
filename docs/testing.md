# Testing

For anyone changing the code: everything OpenDMTQ is tested with, where it runs, and what stands between a change and a live
server. The cases themselves, one table per area with what checks each, are in [test-cases.md](test-cases.md).

The game's files cannot go in this repository, and so not on GitHub's machines either. That splits the tests in two: what runs
in CI on every push, without them, and what runs on a machine that has them (`tests/qa.sh`). A release and a deploy ask for
both.

<p align="center">
  <img src="images/fig-testing-gates.svg" alt="Testing. A push or a pull request runs ci.yml on GitHub, without the game's files: the arm32 build, the unit tests and checks, who reaches the admin pages, the contract and an upgrade from the last release, the pages, the PC client's tests and screens, a host install on Ubuntu and Debian, the images, and three builds for Windows checked on a Windows runner: the player for Windows and the Windows bundle, each under Wine first, and the PC client's installer. tests/qa.sh runs on a machine with the game's files: shell, tools, cli, client, access, game, live, load, ui, upgrade and host, and the tour on an emulator with EMULATOR=1; it sets the commit status qa/local. With both passed, a tag v* runs release.yml, and ./opendmtq deploy updates a server" width="100%">
</p>

## What runs where

| Level | What | Command | Where | Game files |
|---|---|---|---|---|
| Unit | The admin pages and their API, the patcher, song packages, certificates, the PC client's installer and updates a server hands out, the release's signature (`tools/tests`) | `docker run ... python3 -m unittest discover -s tests -t .` in the tools image | CI, `qa.sh` | no |
| Unit | The command line (`cli/tests`), on the oldest Python it supports too, and the repository's own checks: every test case's pointer, the API's reference, the release's files and their names (`test_repo.py`, `test_release.py`) | `(cd cli && python3 -m unittest discover -s tests -t .)` | CI, `qa.sh` | no |
| Unit | The broadcast's transport stream writer | see `ci.yml` | CI | no |
| Scripts | ShellCheck on every script, at the version GitHub's runners have | see `ci.yml`, `shell_tests` in `tests/qa.sh` | CI, `qa.sh` | no |
| PHP syntax | Every PHP file of the game server, the site's pages and the test helpers, on PHP 8.3 | see `ci.yml` | CI | no |
| Edge proxy | Its two configurations, and a port that stays open on plain HTTP when the certificate cannot be used | see `ci.yml` | CI | no |
| Build | The arm32 runtime and shim, both images, the Helm chart against Kubernetes' schemas, a start without game files | see `ci.yml` | CI | no |
| Windows player | The runtime's guest programs with the Windows runner, the player's Java VM, mixer (its resampler, the equaliser, the game's OpenAL asked for 44,100 Hz, the last game's sound result), video reader and PC settings file (the sound keys written back, the bar's gestures, the sound panel's layout at every shape and scale), and the faces its overlay draws its words in (Pretendard for English and Korean): under Wine, then on Windows itself; the broadcast's requests on the player's own sockets, under Wine | `arm32/test_windows.sh` (Wine), `arm32/test_windows.ps1` (Windows) | CI (`arm32-windows`, `arm32-windows-wine`, `arm32-windows-real`) | no |
| Guest file names | Where the player for Windows puts each name the game gives: the app's folders as before, the runtime's own names, everything else in a folder of the app's data; no name reaching past them; and the guest's system, the app's libraries and its APK read only, by any spelling (`arm32/tests/host/guest_paths_test.cpp`) | see `ci.yml` | CI | no |
| Video reader | The player's MP4 reader on files made to break it (a box size that steps back, a sample count or a sample larger than the file, many chunks and runs): each turned away or read as far as it is true, within a second and in bounded memory (`arm32/tests/host/mp4_test.cpp`) | see `ci.yml` | CI | no |
| The player's HTTP | The player's requests to the game server, on stand-in servers: each asks for gzip as a phone's does, unless the game chose its encodings; an answer compressed for it inflated whole, with a length, in chunks or until the connection closes, read in any pieces, without the compressed body's headers; one cut short, broken, followed by more or inflating past 64 MB fails as a lost connection does, after no more than that; every other answer as it always was (`arm32/tests/host/http_test.cpp`) | see `ci.yml` | CI | no |
| PC client | The launcher's logic on a stand-in server and player (`client/tests`), then on a virtual screen (`client/tests/ui`): every page, the first-start guide and the dialogs in both languages at three window sizes, at 150 % (the default and the smallest window) and at 200 % (the default and the smallest), with the layout, the spacing and the design measured and the page's field compared with the window's own background picture (`shots.py`); the states that walk never reaches: the connection test's every verdict, the server gone under an open window, the refused sign-ins, PLAY while the server builds its app and the start after an update (`states.py`); every page by the keyboard alone (`keyboard.py`); a setting's change and a page switch filmed, with no frame of a page half drawn, no picture cut for the page's field, no card taken off the screen for a moment and the page before kept whole while the next is made (`flicker.py`); each change of the server, the sign-in, the app and the launcher's version said every time (`notices.py`); the sound set in the game kept after it, with no error Tcl meets in the background (`sound_back.py`); a field and its buttons on one line, a state row's value by its words (`rows.py`); the installer's window at 100 %, at 150 %, at 200 % and on a small screen, every page whole in its window, with its own header in place of Windows' title bar: its minimise and close buttons, by the keyboard and the pointer, and its top moving it; its page switches filmed as the launcher's, the page before kept whole while the next is made (`setup_shots.py`); each check a part in a container of its own, side by side (`JOBS`), the flicker film first and alone | `(cd client && python3 -m unittest discover -s tests -t .)` (it needs Python with Tk, Pillow and fontTools; CI runs it in the image of `client/tests/ui`), `client/tests/ui/run.sh <folder>` | CI (`client`), `qa.sh` | no |
| PC client on Windows | The installer as a release builds it, installed silently on Windows itself for the runner's user; its command line (its version, no server yet, the player found), the player's sound devices without a window, the same installer again as a repair, the launcher's Repair of a file of the player gone, and Uninstall with the data: the program, its shortcuts and the data gone | `client/tests/windows/install.ps1` | CI (`client-build`, `client-windows`) | no |
| PC client, end to end | The installer as the site hands it out, under Wine against a throwaway server (on llvmpipe, or on WSL's graphics card, [below](#under-wine)): installed through its own window, the first-start guide, the sign-in, the app's download, PLAY; the bar down by itself for 3 seconds when the game's picture first shows, the pointer resting on the handle bringing it, a click on its place reaching the game; the bar at the game's top edge switching to a window and back, in the window no buttons of its own, the bar's minimise and the taskbar's restore, a minimise and a restore with the bar down as Windows makes them (the window's pop-ups hidden and shown again: the bar stays gone), its X pressed while the bar slides down, its X asking with the game held still, Keep playing, then Quit the game, the launcher back; the Screen, Sound and Controls pages by the keyboard alone, keyboard play's keys on a US and a French layout; the last game's sound the player wrote, as `--status` says it; the connection test on the command line, of the server and of an address no network leads to, and a report whose files keep none of the server's address, the site ID or the address tested; then Repair, a file of the player and one of the launcher put back as installed; Clear game data, after which the game starts again with the same id; Uninstall with the data, refused while the window is open, then the program, its shortcut, the data and the installs' logs gone | `client/tests/windows/e2e.sh` (`OPENDMTQ_WINE_GPU=1` on the graphics card) | by hand, with a change to the client or the player | yes |
| PC client's installer | The installer under Wine as a person uses it, with no server and no game: its window without Windows' title bar (Wine drawing Windows' own title bars), its styles read back, a drag of its top, its own minimise and close buttons, the taskbar's restore and Alt+F4; its Install page and its end page, which opens the launcher; run again to Repair, then to Uninstall with the data kept; Windows' quiet uninstall; Windows' Apps opening OpenDMTQ's own uninstall, whose Delete everything leaves nothing of OpenDMTQ on the PC | `client/tests/windows/setup_e2e.sh` | by hand, with a change to the installer | no |
| PC client's updates | Installed PC clients updating under Wine on a network with no way out, from releases signed with a key made for the test: through their server's `/updates/` by the delta package and by the whole one, staying with their server's version while GitHub has a newer one, from a stand-in for GitHub's releases; a tampered package and checksums signed by another key refused, nothing put in; the last release's launchers, which check no signature, updating by Velopack's GitHub source and by their own `--update`. And the last release's PC client updating to this release's files as they are published, with this release's servers fetching the runtime and the installer by their names | `tests/release/update_signed.sh`, `tests/release/update.sh` | by hand, with a change to the updates or to a release's files | no |
| Broadcast colours | The colours a broadcast from Windows says it has (`arm32/tests/host/live_sps_test.cpp`) | see `ci.yml` | CI | no |
| Broadcast requests | A phone's and the player's requests to the server, on stand-in servers: each within its deadline whether the server answers a byte at a time, not at all or takes no body, or the name's lookup does not answer; an answer too long as none; the server's answer read as meant and odd JSON as nothing; the ids that go in a URL; the upload queue and the quality steps the uploads take (`arm32/tests/host/live_net_test.cpp`); the same test built for Windows, under Wine on the sockets the player for Windows uses (`arm32/test_windows.sh`) | see `ci.yml` | CI | no |
| Frame limits | Which displays and frame limits keep every frame of the player for Windows on the same number of refreshes, and which go by the clock; by the clock, each frame one frame's time after the last whatever the game's limiter does, and no burst after a late one (`arm32/tests/host/pacing_math_test.cpp`) | see `ci.yml` | CI | no |
| Following the display | The frame rate's steps with a display and a game the test plays: a computer's 240 Hz display keeping every refresh with a fifth of its frames late, to every second refresh after three windows with more than a quarter late, every refresh again 5 s later, back down in the first window of a try that falls short and 10 s before the next, a computer that makes 130 frames a second settling at 120 between tries a minute apart at most; vsync off at its limit; a phone's 120 Hz panel to 90, 72 and 60, one that stays at 120 Hz to 60; the heat's step every half minute (`arm32/tests/host/follow_test.cpp`) | see `ci.yml` | CI | no |
| Admin access | Who reaches the admin pages and their API on an exposed server's one port: the server PC's own visit, the same address with a header a proxy adds (a reverse proxy on the server PC), one from elsewhere; every visit from one address (Docker Desktop, rootless Docker); `--admin-public`; a host install's settings | `tests/access/run.sh` | CI, `qa.sh` | no |
| Contract | Every reply of the game server the client depends on, its quirks, a save under a held lock, players' names that are no UTF-8, the keyboard's mark a save keeps, a server moved to another address, a player's game state (the currencies, the level, items, purchases, unlimited currency, a ban refused in the game, on the site and in the PC client), whose game may make a call (each sign-in's own key, a chart's start, a save that earns once), the site's sign-in of the owner, of a banned player's one-time link and of an account switched off (the PC client's too), and not one PHP warning | `tests/game/protocol.sh` (`protocol.py`, `lock.php`, `names.php`, `keys.php`, `moved.php`, `state.php`, `trust.php`, `signin.php`) | CI, `qa.sh` | no |
| Pages | All pages at five screen widths in both languages, empty and full, on air, under maintenance, with the owner's notice and with broadcasts off; MY PAGE; Play on this PC; the replay player and the owner's forms; the game server going away and coming back with the owner's pages open | `tests/ui/run.sh` | CI, `qa.sh` | no |
| Upgrade | The last release's images used as people use them (players and plays, a site account, an API token, the recordings' limits, a broadcast with its recording, a backup), then this tree's images on the same data: nothing lost, every route of the API and what it answers, the backup restored; then the same from this tree's own images, as a restart | `tests/upgrade/run.sh` (`FROM=<version>` for another release) | CI, `qa.sh` | no |
| A server updated | A server of the last release updated as its owner does it, with Docker Compose, as a host install in a clean container and as the Windows bundle under Wine: one on port 80 moves to the port its admin pages had (8791), the players' site, the admin pages and the API answer there and nothing on port 80, the start and `status` each say it once, the site's download page tells players to install the app for the new address, the app is built for it, and the owner's ID and password open both the admin pages and the site | `tests/upgrade/compose.sh`, `tests/host/update.sh`, `tests/windows/update.sh` (`FROM=v0.10.0`) | by hand, with a change to an install or to a server's start | no |
| The server's life | With Docker Compose, the commands the Server page names: the data listed by part and some deleted after a backup, the repair, and the uninstall keeping the data, then whole | `tests/lifecycle/compose.sh` | by hand, with a change to the Server page's commands | no |
| Server | The real game files: every request the game makes, broadcasts, recordings, sign-ins | `tests/live/run.sh` (`BROWSER=1` adds a real video) | `qa.sh` | yes |
| Shared server | Eight players on a server held to two cores with 300 players and a million plays, while one address saves as fast as the edge lets it, two players broadcast to thirty browsers, and a backup and a build of the app run: every save stored, every segment taken, the server's memory sampled. Then the server killed mid-save and started again: nothing it answered as stored lost, its database whole. Then a full disk under the database: each save refused with the code the game retries on, nothing half kept, the server answering, and saves stored again once there is room | `tests/load/run.sh` | `qa.sh` | yes |
| Host install | The README's one command (`host/get.sh`, `host/install.sh`) on a clean system in a container, `./opendmtq setup`, then its setup in the browser (the one-time link, the files found and imported, an account, the app, another address and the restart), the contract, the pages, stop and start | `tests/host/run.sh` (`DISTRO=debian:12`; `APK=<file>` also builds the app) | CI (Ubuntu 24.04, Debian 12), `qa.sh` (with the app) | no (yes with `APK`) |
| Windows bundle | The bundle built from its pinned downloads, every program's DLLs found, then run: under Wine on Linux (a first start with no settings, then started as a double-click starts it, through the setup's sign-in, what it says of each file, import and restart, and with `APK=<client>` the phone app's build), and on Windows itself in a folder with a space; the import, the contract, the admin pages, nothing left running after its window | `host/windows/build.sh`, `tests/windows/wine.sh`, `tests/windows/run.ps1` | CI | no |
| Play on this PC | The Windows bundle with the PC client's installer in it, under Wine: the owner on the server PC presses Play on this PC, the PC client installs quietly and its launcher opens with the owner's ID filled in, then the same with it installed and through the API; the connection test against this server and against port 80 of the same host (the server found on 8791); the report, with none of the Windows user's name or the server's address in it | `tests/windows/play_here.sh` | by hand, with a change to Play on this PC, the connection test or the report | no |
| Client | Every edit of the patcher finds its bytes, settings and screen objects in the real game clients, each in its own version | `tools/tests/test_real_client.py` (`OPENDMTQ_BASE_APK`; `CLIENTS=<folder>` for `qa.sh` adds the APKs in it) | `qa.sh` | yes |
| Sound | What leaves the phone comes out of the browser whole | `tests/live/sound/run.sh` | by hand, with a change to the sound path | yes |
| Closed network | [Without internet](closed-network.md), step by step, on a network with no way out: Docker Compose from a release's images, a host install from what is carried in, the chart. The host install's kit here carries no PC client's installer or updates, and nothing here checks them. The Windows bundle has the test too | `tests/closed/run.sh`, `CLOSED=1 tests/windows/wine.sh` | by hand, with a change to how a server gets its programs | stand-ins; a client for the app (`APK=`) |
| Game, closed | The real game on an emulator that reaches the server and nothing else: the tour, a song to its result, the shop, a server with no songs and the songs coming later | `tests/closed/game.sh <folder>` | by hand, with a change to how the app reaches the server | yes |
| Failover | The Kubernetes deployment losing its pods and a node | `tests/ha/failover.sh` | by hand, with a change to the chart | yes |
| Game | Install from nothing, first start, lobby, menu, options, shop, second start, on an emulator | `tests/game/tour.sh <folder>` (`EMULATOR=1 tests/qa.sh`) | by hand, with a change to the patcher | yes |
| Device | Real phones, by ear and by hand | the `hand` rows of [test-cases.md](test-cases.md) | before saying it works there | yes |

On a busy machine the closed game test can stall at a song's loading screen, with client 1.3.4 and 1.3.5 alike: the
game's own audio output (FMOD, writing to an `AudioTrack`) waits on the emulator's audio, and the game's threads wait on
it. On 2026-11-07 it stalled in 7 of 17 song starts while the machine also built, tested or ran a second copy of the
game, and in none of 12 on an otherwise idle machine. No stall was in OpenDMTQ's own code, which never waits there. A
run that stalls fails at "the song's score reaches the server".

## Tests off the desktop

The tests of the player for Windows and of the PC client run on a PC someone may be working at. They put nothing on its
desktop: no window, no taskbar button, no animation, no sound.

### Under Wine

`arm32/test_windows.sh` and `client/tests/windows/e2e.sh` run in containers. The first one's programs open no window;
every window the second opens is on the container's own virtual screen (Xvfb), which nothing shows. The game's frames
are drawn there by Mesa's llvmpipe on the CPU, as on CI's machines. On WSL 2 with a graphics card, `OPENDMTQ_WINE_GPU=1 client/tests/windows/e2e.sh ...` draws
them on the card instead (`arm32/wine_gpu.sh`):

- The player is a 64-bit program, so Wine's 64-bit side and Mesa's 64-bit d3d12 driver are all it needs; that driver
  hands its calls to the card through WSL's `/dev/dxg`. Debian 12's own Mesa (22.3) has it without
  `ARB_polygon_offset_clamp`, on which Wine's Direct3D offers no more than feature level 9_3 and ANGLE finds no Direct3D
  11 device: the game would draw nothing. `arm32/wine-gpu.Dockerfile` is the player's Wine image with Mesa 25 from
  Debian's backports, built at each run from Docker's cache (a minute the first time); the two images differ in Mesa
  (with what Mesa 25 needs from the backports) and in `glxinfo`.
- The container gets WSL's GPU device `/dev/dxg`, and `/usr/lib/wsl/lib` and `/usr/lib/wsl/drivers` read only, with
  `LD_LIBRARY_PATH=/usr/lib/wsl/lib` and `GALLIUM_DRIVER=d3d12` as WSLg sets them, and no core dumps (WSL would copy
  each into Windows' temporary folder). Each frame is drawn on the card and read back to the virtual screen.
- Once the game is at its menu the run fails unless the container's OpenGL is D3D12 and the player's own process holds
  WSL's `libd3d12` in its memory and `/dev/dxg` open, with none of llvmpipe's drawing threads: a GPU run that fell back
  to the CPU does not pass. The player's `drawn by` line names Wine's stand-in for the card (an NVIDIA GeForce GTX 470)
  on either renderer; the run says the container's OpenGL renderer beside it (`D3D12 (<the card>)`).
- What it changes is the test machine's load: the game takes one to one and a half cores instead of six to eight, and
  anti-aliasing no longer costs it frames. Its numbers are still Wine's (Direct3D 11 becomes OpenGL, then D3D12, and each
  frame is copied back to the virtual screen), and the GPU timers the player's stats read come back as zero through that
  chain: a player's PC is measured on Windows itself.

`arm32/test_windows.sh` has nothing to draw, and stays on the CPU image.

### On Windows itself

What Wine does not have is checked on Windows: the display's composition and pace, the card's own Direct3D 11 driver,
WASAPI's timing, and how Windows treats a window and the pop-ups it owns. Those runs start the player through `cmd`'s
own `set`, never through a program that presses keys or moves the pointer (Windows Defender once took such a launcher
away as a trojan); the player's own switches tap, type and save frames inside it (`PLAYER_TAPS`, `PLAYER_KEYS`,
`PLAYER_SHOTS`). They stay off the desktop with:

- `PLAYER_WINDOW_AT=10000,10000`: the window at a place no monitor has, shown without taking the focus, and a window
  there even where the settings ask for full screen or name no display (full screen is the default);
- `PLAYER_WINDOW_UNLISTED=1`: a tool window, which Windows gives no taskbar button and no place in Alt+Tab or Task View,
  with DWM's animations off for it and never in full screen (which would cover a monitor); a reason the player cannot
  start said in its log (or its output before there is a log) with no box, and no box of Windows' own for a crash. The
  pop-ups over the game are owned tool windows already. The PC client never sets it;
- `--seconds N`, so that the player ends by itself, and a PC settings file with a window (full screen covers a monitor)
  and the volume at 0.

Some checks still need the visible desktop, and run only when the person at the PC says so:

- a minimise and a restore from the taskbar: an unlisted window has no button to come back from, and Windows hides and
  shows again the window's pop-ups on that way;
- the display's own pace: a window on no monitor is paced by none, and Windows has let such a window's frames out at
  a 240 Hz display's rate on one evening and at about 21 a second on another, so a run off every monitor says nothing
  about 240 Hz;
- full screen, which covers a monitor;
- what a person has to see or hear.

## Tests without the game's files

`tests/game/protocol.sh` and `tests/ui/run.sh` need Docker, Python 3, `curl` and GNU coreutils, and none of the game's
files. They start the server by its **real start script** on stand-in game files (`tests/ui/make_content.php`): made-up
songs, plain coloured jackets, and a client data folder with an empty manifest, which is all the server checks for. No
game code or data is in them.

`tests/game/protocol.py` then goes through what the client sends, request by request, and checks each reply the client
reads and each quirk it depends on (an empty news list closes the game, for one). Each check names the client
behaviour it protects. A new method of the game server gets its checks there. `protocol.sh` gives that server the song
list the tools write once the owner hides a song, the last stand-in song hidden: a play of a hidden song's chart is kept,
one of a chart no song has is not. Inside the running server it then saves plays with the PC client's keyboard header
and without it (`tests/game/keys.php`): the game's replies, rankings and own scores the same, what the database kept of
each told apart; it starts a database from before the keyboard's mark; it starts the server at its address again and at another
one, the move noted for the site's download page (`tests/game/moved.php`); and it writes players' game states as the admin pages write them and reads what the game is
told through its own calls, signed as the game signs them: the currencies and the level, purchases, unlimited currency,
items given and taken, and a ban refused in the game, on the site and in the PC client (`tests/game/state.php`).

In `tests/ui/run.sh` a real browser then takes the server through a life, in stages (`tests/ui/audit.js`):

| Stage | State | Looks at |
|---|---|---|
| `self` | | One planted fault of each kind (`defects.html`): a checker that stopped seeing something must not pass as a page without faults |
| `empty` | Nothing on the server | Every page, at a phone's and a laptop's width, in both languages |
| `full` | Players, plays, recordings, an app | Every page, at 360, 744, 1024, 1280 and 1920, in both languages |
| `thispc` | The admin pages from the server PC itself (the browser on the admin service's own network), as a host install on Linux and as the Windows bundle (`as_windows.py`) | Play on this PC on the App page and the setup's last step, at every width in both languages: how to play from a Windows PC on Linux; on the bundle the button, pressed, and its job followed to the words it ends with |
| `keys` | The same, two players playing with the keyboard (`run.sh` writes what the database holds of their plays and bests) | Every keyboard mark of the site and the admin pages against the database: there where a keyboard play made the score, with how many beside a total, nowhere else; beside what it marks, at a phone's and a laptop's width, in both languages |
| `air` | Two players broadcasting | The video playing; the pages that change; the site's and the admin pages' bars on screens held sideways, 600 to 1000 px wide, with LIVE and its count in the menu: every section whole, clear of the keys and its own to press |
| `notices` | The home page and the live page left open, broadcasts on | Maintenance begun, given a new message and ended, twice, by the owner on the Notices page: each time the pages left open take it up and drop it by themselves |
| `maint` | Maintenance on, by the owner's form, with a long message | Every page that shows the notice; then off again |
| `notice` | The owner's notice put up on the Notices page, with words that wrap on a phone | Every page of the site with it under the bar, at five widths in both languages, none of it for a stranger; closed for a visit and back on the next, back with new words; the home page and the live page left open taking it up, changing it and dropping it by themselves |
| `flows` | A stand-in chat for the webhooks (below) | What people do: language, sign-in, searches, the replay player on a laptop and a phone, the owner's forms; a player's own admin page (a currency, a level and an item changed in place, the questions before a ban and a reset); the Notices page's Discord and Slack card; the PC client's one-time link and records |
| `mine` | An account of the stage's own, linked to a player, with admin rights and an API token (`run.sh` makes it) | MY PAGE for that account, for one linked to no player and for the owner's, at 360, 744, 1024, 1280 and 1920, in both languages; its password, its ID and Sign out everywhere else with other browsers signed in; its JSON twin, for a visitor who has not signed in and from another site |
| `patterns` | | Nothing said only under a mouse pointer (each such word also by a tap and the keyboard), switches and small changes made in place with the server's words under the bar, the forms' words under their fields |
| `quiet` | Broadcasts off for the server, with the players, records and recordings in place | The pages that showed broadcasts, at 360, 744, 1024, 1280 and 1920, in both languages: nothing of broadcasts left on the site, each page whole without them; the owner's pages say they are off |
| `away` | The game server stopped and started again, twice, with the owner's pages open | The Players page and the status page saying OFFLINE and dropping it by themselves, each time |
| `down` | The game server stopped | The owner's pages keep their look and say what is wrong |

Between the seed and the stages, `tests/ui/account.php` checks MY PAGE's account changes inside the running server, on
accounts of its own and from an address of its own (the browser's sign-ins are never held back by it): a wrong current
password refused and counted toward the sign-in's limit, the limit reached, a new password, a new ID with its game player
and API tokens, Sign out everywhere else, the server's own account, and each change in the log of changes.

On each view `layout.js` measures what can be measured about a page: text cut off, past its box, on other text or under another
box; rows and columns out of line; anything past the screen; a box that scrolls sideways; an ordinary word or a figure (a
score with its commas) split over two lines; a sentence a column or grid box cuts into lines of their own; a placeholder wider than its box; too little contrast; a control still in the browser's own look; a class no stylesheet
mentions; something too small to press; a picture that did not load. Beside it `spacing.js` measures the room between
things: two boxes that touch or overlap, a box against its box's inner edge, text closer to its box's edge than the box's
padding, gaps of different sizes in one row or column, and a gap off the page's own spacing. A failed request or a
script error also counts. The views of a list are looked at side by side (`SWEEP_WORKERS`, one for each of the browser's
processors): each in a window of its own, as its front tab, so that it is in sight as a person sees it (a view measured
out of sight is a fault). The findings, the list of results and screenshots end up in the report folder
(`_work/ui-report`), and in CI as the workflow's `ui-report` artifact.

A rule that fits a page on purpose goes on that page's element as `data-layout-ok` (or `data-spacing-ok` for its room), with the reason in a comment, not in the checker.

Beside the server and the admin service, `run.sh` starts a stand-in chat (`tests/ui/chat.py`) on the test's own network,
with two webhooks of the Notices page pointing at it (one whose chat deleted it): the messages the server's plays,
broadcasts and maintenance make go there, and the `flows` stage reads what it got. No message leaves the test's network.

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

**CI** (`.github/workflows/ci.yml`) runs on every push to `main` and every pull request. Its jobs run side by side: the
pages' tests in three parts, each a server of its own taken through its stages in their order; the contract, admin
access and upgrade as a job of their own; the PC client's suite one language in each job; the Windows programs' tests
under Wine beside the PC client's build and the tests on Windows itself, which take the programs as soon as they are
built. A newer push stops the older run of the same branch or pull request (a tag's run is never stopped), and a change
to the guides alone (README.md, CONTRIBUTING.md, docs/ but the guide the launcher's tests read: `.github/changes.py`)
runs the test job, whose repository checks read them, and skips the others.

**Before a push to main**, `python3 .github/ci_local.py` runs CI's jobs on this computer the way GitHub runs them: each in a
container that stands in for GitHub's runner (`.github/ci-runner.Dockerfile`: Ubuntu 24.04, as a user who is not root),
on a fresh clone of the commit, its steps as the workflow has them and the actions it uses done the same way here (the
checkout, the images' builds, Helm, the cache, the artifacts between jobs), side by side as their needs allow, each with
names, an image tag and ports of its own. The changes job decides what runs, as on GitHub (for what the commit changes
since `origin/main`; `--all` runs everything); `ci_local.py JOB...` runs those jobs and the ones they need. Each job's log
is in `_work/ci/<commit>`. The jobs for a Windows runner run on GitHub only: it names them.

**The local gate** (`tests/qa.sh`) runs on the commit that is checked out, on a clean tree, and sends GitHub the commit status
`qa/local` when everything passed. `--no-status` runs it on a tree with changes, for a look. The launcher's flicker film runs
first, with nothing else of the gate beside it: it counts the frames a change shows, which a machine busy with the other
steps adds to. Then the server's and the tools' images are built once for every step, and the steps run in four lanes side
by side: the launcher's other parts; the pages; the server on the real game files, under load, upgraded and as a host
install; and the quick ones (shell, cli, tools, access, game). `SERIAL=1` runs one step after another, for a machine with
few processors, and `NAME_PREFIX`, `TAG` and `PORTS` (the first of nine in a row) keep a run's containers, images and
ports apart from another's on the same machine. Its report, with each step's whole output and one line for each step in
the steps' order, is in `_work/qa/<commit>`; the newest five are kept.

**A release** (`.github/workflows/release.yml`, a tag `v*`) first checks that the tag, the chart and CHANGELOG.md name
one version (`.github/release_notes.py`), runs CI again on the tag's commit, whose repository checks find the README's
and the guides' download lines naming that version too (`.github/doc_versions.py`), and asks for `qa/local`. Its files
are then made, laid out, signed, checked and published on the machine that holds the project's signing key by
`.github/release.sh`, with the steps of the workflow's own publishing job, which stops on GitHub as it has no key
([CONTRIBUTING.md](../CONTRIBUTING.md#releases)): the runtime for newer phones, the player for Windows, the PC client's
installer and its update packages (the delta from the last release's full package), the Windows bundle, then the
release's files under their names (`.github/release_assets.py`: the PC client's installer, the server for Windows, the
chart, the runtime for newer phones, the PC client's update feed and its full and delta packages, the checksums and
their signature), whose notes are that version's section of the changelog. Before anything is pushed it runs the
release's own checks: the Windows bundle under Wine, a host install on Debian 12, and the last release's PC client
updating to these files (`tests/release/update.sh`; `tests/release/update_signed.sh` does the same with a key made for
the test, [above](#what-runs-where)). `.github/release.sh --dry-run VERSION` does all of it, the images for both
platforms included, and publishes nothing; `gh workflow run release.yml` rehearses the gates on GitHub, with the chart's
own version.

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
- A new stage of `tests/ui/run.sh` goes into one of the `ui` job's parts in `.github/workflows/ci.yml`, in its order:
  `cli/tests/test_ci.py` fails while a stage is in no part, or in two.
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
