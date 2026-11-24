# Changelog

What changed in each release of OpenDMTQ. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/): a release with a new feature raises the minor number,
one of fixes, changes and smaller additions raises the patch number. Each release's section here is its release notes.

## [Unreleased]

## [0.11.3] - 2026-11-24

OpenDMTQ 0.11.3 closes a hole that let anyone who could reach a game server take over another player's account, makes
backups, restores and port moves hold on every install kind, and smooths the launcher, the installer, the site, the
admin pages and the pieces over the game wherever a second full review found them wrong or awkward.

### Security

- A player's transfer code, name and equipped items are changed only by that player's own game: the calls that read or
  use a transfer code, rename a player or change what they wear are taken only when signed by one of that player's
  sign-ins. Before, anyone who reached the game server could read any player's code, move their account onto another
  phone, rename them, and then spend their MAX POINT as if from their own game. Transfer codes are random now: a code
  made by an earlier release is replaced at the server's first start of 0.11.3, so a player who wrote theirs down reads
  the new one in the game's OPTION.
- A deleted player's number is never handed out again, and their game's sign-ins go with them: before, the next new
  phone could get the same number and take the deleted player's game as its own. A restore keeps the highest number the
  server ever handed out, and only the sign-ins of players the restored database has.
- Two logins of one sign-in at the same moment get the same key; one of them could be refused at its next start, save
  or purchase.
- The live view counts a song as played only from the player's own signed start.
- The PC client's report leaves out an IPv4 address written in IPv6's form, and the name a sound device carries of its
  owner ("Sena's AirPods").

### Changed

- The FPS counter waits in the menus and shows in each song, with keyboard play on and off: no menu screen leaves it a
  place clear of the game's own tabs and panels. The launcher's Position line says so.
- The sound panel's frequencies and values are set in SemiBold, never under 10 pixels, over glass dark enough to keep
  every word at 4.5:1 or more; a notice beside the open panel takes the room it leaves, two lines where it took five.
- The loading tips that sent players to quests for MAX Point say it comes from playing. The patcher is 1.13.0 and the
  phones' runtime changes, so every server builds its app again; the site's home and download pages say when the server
  made a new app for phones.
- The first PLAY in the launcher links a site account with no player to this PC's game player, when that player has no
  account either, and says it once; the admin pages' Accounts page names each game player with their device and last
  play.
- The end of a maintenance is told only to players whose game was told it began.
- OpenDMTQ-cmd.exe has the launcher's My records (`--records`), My page on the site (`--my-page`), Reset keys
  (`--reset-keys`) and Use this address (`--use-found`).
- The launcher and the installer: no yellow buttons (Keep data is plain beside the red Delete all, Start over is the
  cannot-start window's main button); no card holds a single setting; a ready check row that is not fine says what is
  wrong; the background's shards and the lit top's panes stay clear of every card and window button; the person who
  runs a server is its owner, and downloads are 다운로드 throughout.
- The site and the admin pages: on a screen held sideways every section stays whole and its own to press; the
  background's shards stay out of the content column; the hall of fame's months are columns across its card; links in
  a sentence are in the words' colour; an account's changes wait under its More; the Status page's cards are as tall
  as what they hold; on a phone the Logs page lists its requests 50 at a time.
- The guides name the game's hosts by their role and none of its files, code or songs; the Docker way clones the
  release and updates to a release's tag; the guide for players is for players (its workings moved to the
  architecture), the move off port 80 is told once, and the guides state facts where they recommended or warned. The
  phone's and the PC's guides tell the account transfer in the game's own words (OPTION's TRANSFER CODE), and the
  README's first picture and the site's, the admin pages', the launcher's and the game's pictures show 0.11.3.
- The code, its comments, its logs and its tests name none of the game's servers, its app, its files or its code: the
  names the patcher, the game server, the player and the tools look for are one encoded table, read by their role,
  and the patcher finds the client's server address by its form.

### Fixed

- Backups: a restore on the admin pages failed for a server with gigabytes of added songs and said the disk was full;
  it unpacks beside the backups now. A backup whose bytes changed after it was made is refused on upload and at its
  restore. An upload or a backup on a full disk is answered in words. A sign-in noted while a restore runs is kept.
- Port moves: on Kubernetes the Server page's port command moves the router Service with the address, and the pods know
  the Service's own port; a move behind a router keeps the router's own port and names the forward on every install
  kind; a waiting change can be taken back; the move off port 80 stays in sight until Done; on Docker Compose the move
  is made whole or not at all, and a data folder of another user is said first.
- Docker Compose: BIND_ADDRESS is where `up` waits for the admin pages and what their link says; the refusal to a visit
  from elsewhere names the server's own port, and the API's refusal is the API's own JSON; the setup ends with the
  owner's password itself, as a host install's does.
- With the data disk full, a player's game reaches its own login and its own error message instead of waiting with
  nothing on the screen, and the Status page says that players cannot sign in or save once it is full.
- The Linux line tells a system without sudo how to have it first and says which release it brings; starting with the
  computer and uninstalling say so on a Linux without systemd instead of ending with a traceback; the setup's message
  for a player names the installer for Windows the site will hand out; an owner's ID the players' site does not take is
  said with its rule.
- A one-time link of a disabled account says that the account is disabled.
- The launcher: Korean PLAY said there were no records beside the list of them; the first-start guide's SERVER step
  stayed on "Connecting..." after the server answered; a connection test that finds the server gone says so at once; a
  game ended from outside after it started is no longer said to have not started; no paragraph leaves a short last
  word alone on its last line; the installer fits its choices with the launcher and the game open and dims its close
  button while it works.
- The site and the admin pages: the rankings podium's score is never broken in the middle of the number; the band of an
  answer's words keeps clear of the button just pressed and stays over a question; the Server page's answers come back
  to their card in sight; Esc closes a row's More; a ban's end is written as every other date; the setup names a folder
  it found by what it holds; Korean words as a Korean product says them.
- The PC client: every answer and update package comes whole within its time however a server trickles it, and so do
  the server's own downloads of a release; Use this address waits while a game started from the command line plays from
  the old app; a report of a server named OpenDMTQ keeps OpenDMTQ's own words.
- The runtime answers futex wakes at the edges of their arguments, and a tgkill naming another thread group, as a
  phone's kernel does.
- A rebuild of the phones' app stopped part-way never leaves latest.json describing another app than the file it names.
- The release with its files is published before main names it, so the README's lines never point at a release that is
  not there yet.

### For contributors

- Windows itself runs the futex and atomics tests, and the futex test's lost-signal phase has to run on the Windows
  layer; the launcher's UI suite draws 150 % and the smallest window at 200 % and fails on Tcl's background errors; the
  pages' suite sweeps screens held sideways and checks the shards against every card; the overlay's words are made on
  its painter's thread alone; a check reads every file of the repository for the game's own names, and the tests use
  made-up files.

## [0.11.2] - 2026-11-24

OpenDMTQ 0.11.2 keeps the game's music list at its page after songs are downloaded, gives the PC client's FPS counter
a clear card of the overlay's own glass, shortens the README's quick start, and fixes how the runtime answers a signal
sent to a thread that has ended.

### Added

- For contributors: `.github/doc_versions.py` checks that the README's and the guides' download lines name the release
  the chart carries and that every file they link exists in it (`--write` puts the version in); the release's gates
  and the docs' tests run it.

### Changed

- The PC client's FPS counter is a card of the same glass as the notices over the game: the frame rate as a large
  figure in the launcher's wide face with "FPS" after it and the frame time under it, the digits in steady columns,
  lit lime only after three seconds at the display's rate. Its words keep a contrast of 4.5:1 or more over the game at
  every size, and the live notice's second line does too.
- The README's quick start comes in two parts, Play and Run a server: a phone or a PC in two steps, and a server in a
  few lines for Windows, for Debian, Ubuntu or a Mac, and with Docker, each downloading the release by its own address;
  the install guide holds each way step by step.

### Fixed

- The game's music list went back to its first page after songs were downloaded from it (ticked one by one or with
  **Select ALL**, then **DOWNLOAD**), and after a download cancelled on the way; it now stays at the page the player was
  on. This is a new edit of client 1.3.4's code (1.3.5 already keeps the page), so the patcher is 1.12.0 and every
  server builds its app again: players get the new app.
- The runtime that plays the game on Windows and on phones without 32-bit support passed a signal meant for a thread
  that had ended (`tkill` or `tgkill` naming thread 0, as the C library does for a thread that has ended and is not
  joined yet) to the whole game, where another of its threads ran the signal's handler; it now refuses it, as a
  phone's kernel does.

## [0.11.1] - 2026-11-19

OpenDMTQ 0.11.1 closes holes in the game server's currency and bans, keeps a server's address and its phones through
the move off port 80 on every install kind, and makes the launcher, the installer, the site, the admin pages and the
pieces over the game plainer and quicker.

### Added

- The app's name on the Server page: a card with its field, `POST /server/name` in the API, and `opendmtq name` on a
  host install. The phones' app is called by it from the server's next start; the app players have keeps working.
- `GET /server` gives `port`, the server's own, and `public_port`, the address's, where a router forwards another
  public port to the server.
- For contributors: `.github/ci_local.py` runs CI's jobs on a computer as GitHub runs them, before a push to `main`, and
  `.github/release.sh` makes, checks and publishes a release from the computer that holds the signing key, with
  `--dry-run` to rehearse it.

### Changed

- The launcher's and the installer's pages are composed on one grid: **Play** opens on the server and the signed-in
  player, with the ready check and the last game side by side and My records under them as a scoreboard; the settings
  pages hold their groups as rows in cards, side by side where the window is wide, and a lone button is a row of its
  group. Each card takes a surface and a shape of its role (the page's head, the checklists, the results, the settings,
  About, the dialogs), and buttons, text sizes, paddings and alignment follow one scale. The window's background shows
  round the cards, its shards in the margin, clear of every card's edge and corner.
- The launcher's pages show what to do now and the state: the How to play card (on **Play** and the guide's last step),
  the **Controls** page's Mouse, Touch screen and Keyboard cards, and **Help**'s card on a game that does not start are
  gone; what they said is in the guides ([Playing on a server](docs/play.md), [the Windows player](docs/windows-player.md)).
- The launcher's links are in the words' colour with their chevron, lime staying the main button's alone, and Windows'
  title bar over the launcher is drawn dark in the launcher's colours.
- The launcher's words: **Play**'s Server card says when the server does not answer, and the status line says a sign-in
  that ended; **Use this address** names the server by its name; the connection test's verdict names the server once
  and its round trip each figure once; the **Screen** page's lines say what a setting does, and the FPS counter's says
  where it stands; the **Sound** page's card is Last game's sound; My records name a chart's mode as 3 LINE.
- The installer: **Uninstall** is its page's main button, filled red; the line that the launcher closes first shows
  only for a choice that closes it; a long program folder breaks after its separators; waiting for a game to close
  shows the chosen work's own steps and words.
- The site and the admin pages show what to do now and the state: the Download page's notes, its folded trouble card,
  the setup's "On each phone" steps, a player's page's economy lines and the API token card's path are in the guides.
  With no app yet, Home's download waits with a line saying why; after a move Home says the address changed; while
  players are on air the broadcasts button is plain with its red light. The owner is 소유자 and Notices are 공지 in
  Korean throughout, and a new webhook takes every event. Play on this PC gives its reason in the page's own words, and
  the Server page says where an action is done when the admin pages run without the server's own program.
- Over the game: the notice and the FPS counter stand clear of the game's own header and buttons (in the menus under
  the header, the counter at the top right where the game leaves room; in a song in the chosen corner, clear of the
  pause button); the question before quitting speaks of a song's record only while a song is being played; each of the
  equaliser's chips is as wide as its word.
- Quicker: the launcher and the installer make a page off the screen and put it in place whole, the launcher in about
  half the time of 0.11.0's (its controls draw a face only when they first show it), with its memory back to 0.10.0's; the game server looks players up by indexes and reads a player's ban once per
  request (the batch after a song's start takes about a third less); the site opens its database once per page; a
  player's admin page reads that player alone; the webhooks' loop writes nothing while nothing happens.
- The local test gate runs in about 18 minutes where it took 80, and CI in about 12 where it took 31: images built once,
  steps and the launcher's checks side by side, the pages in parts, a docs-only change skipping the heavy jobs, a newer
  push stopping the older run.

### Security

- The game server ties a player's calls to that player's own game: each sign-in gets a key of its own, and a chart's
  start, a save and a purchase are taken only when signed with one of that player's keys; a save is paid once, for the
  play its sign-in started. Before, anyone who reached the game server could spend another player's MAX POINT by
  naming their id, and made-up saves could earn MAX POINT, EXP and levels. A game left open while its server is updated
  to 0.11.1 has a key the server does not know: its next start, save or purchase fails until the game starts again.
- A ban holds whatever form a call gives the player id.
- A webhook's chat is looked up once per message and the message goes to the address that was checked; the server's
  own addresses, on any of its networks, are refused.
- Play on this PC is not offered to a visit passed on by another proxy on the server PC.
- The PC client's report leaves out every site ID and every server's address and name wherever the launcher wrote them,
  servers the settings no longer know included.

### Fixed

- On Windows every link's chevron in the launcher showed as a broken character; it is drawn as a picture.
- A change on a launcher page flashed (a card's field picture was cut again on every change, and a page was taken down
  piece by piece while it was on the screen), and so did the installer's page switches.
- Helm: values from before 0.11.0 that name `router.service.port: 80` beside a `publicHost` without a port put the
  Service and the phones' app on the same port, 8791.
- A server reached through a router's forward from another public port keeps its address through the move off port 80,
  and an exposed server is told where the router's forward now goes; the Server page's port card names the server's own
  port.
- Play on this PC shows for a browser on the server PC with Docker Engine on Linux.
- The App page says every refusal of the PC client's updates and of the installer.
- The connection test finds a server that moved also over HTTPS with its own certificate authority, and when another
  program answers the old port; **Use this address** takes the trust along; an unreachable network is said at once.
- A server built from a clone that names a version past its release no longer breaks its launchers' update check.
- **Use this address** moves the server and says it in one step (**Play** could show the new address under the old
  words).
- The setup's and the Server page's restart pages go on once the new server has answered twice in a row (they could
  land on an error while the server's other parts came up).
- A ban is told in the game as it is made, also in a song, and its notice stays for as long as the server refuses the
  game; a banned player's one-time link signs nobody in, and the sign-in page says why.
- An account the owner switched off, signing in with its right password on the site or in the launcher, is told it is
  disabled, and the try does not count toward the lockout.
- The owner stays signed in on the site with an ID of any length the server takes.
- With unlimited currency on, a MAX POINT pack gives nothing, as it takes nothing; a player equips only items they own.
- A ban's end further off than 3,650 days is refused in words.
- A restore onto a server with nothing of its own yet keeps the backup's webhooks, and every restore keeps the game's
  sign-ins of now.
- Webhook addresses of other chats are masked whole; a Discord address written with its host's last dot is Discord's.
- A broadcast that ends with nothing recorded says there is no replay.
- Accounts: the player list fits a long name; the setup's Build button stands clear of the box above it; the Backups
  card lists the kept daily backups with their days and sizes; a repair's messages stack, and on a phone held upright
  they stand at the foot of the screen; the hall of fame's own row keeps its rim off the place's figure; Expert's chart
  tab has the contrast of the others.
- The launcher's words that wrap beside other widgets are no longer cut at the right edge.
- Building the PC client leaves no Windows program executable in its folders.
- The Windows player read the two arguments of the game's FUTEX_WAKE_OP calls without their sign, where a phone's
  kernel reads them with it; it now answers as a phone does. The runtime's futex test asks what the kernel does, and
  its own clock and signals no longer stop it on a busy machine.

## [0.11.0] - 2026-11-17

OpenDMTQ 0.11.0 puts the site, the admin pages and the API on one port, 8791, and gives the owner a Server page, a
Notices page with Discord and Slack, and a page for each player's game state; players get MY PAGE on the site, and
the PC client a Sound page, a connection test, signed updates from its own server and the game's sound at 44.1 kHz.

### Added

- Play on this PC, on the admin pages' App page and the setup's last step, for a visit from the server PC itself: on
  the Windows bundle it installs the PC client set up for the server, quietly, and opens its launcher with the owner's
  ID filled in to sign in (or opens it when it is installed); on Linux and macOS the page says how to play from a
  Windows PC. Never for a visit from another PC. Its API route is `POST /app/play-here`.
- The PC client's connection test: **Test connection** on the **Online** page, and from the **Play** page's Server row
  while the server does not answer, follows the way to the server step by step (the address, the name, the port, the
  OpenDMTQ server and its HTTPS certificate, the version, the sign-in, the game server, the broadcast state, the
  downloads by their headers, the round trip), each with what it found and how long it took, in a card that fills in as
  it goes, with **Copy**. When the port does not answer, a server on 8791 or the ports after it is found and one press
  away (servers updated to 0.11.0 left port 80). `OpenDMTQ-cmd.exe --test-server [ADDRESS]` does the same.
- A report for whoever helps: the PC client's **Help**, **Save a report** (and `OpenDMTQ-cmd.exe --report FILE`) puts the
  launcher's logs, the end of the game's log, the settings, the displays, the sound devices, Windows, the graphics cards,
  the versions and the last connection test in one zip, with the user's name, the site IDs, the servers' addresses,
  the sign-ins, tokens and this PC's player id left out, and says what was left out.
- **My page on the site** on the PC client's **Play** page opens the player's MY PAGE in the browser, signed in already by a
  one-time link the server makes for the launcher's sign-in (it works once, within a minute; `POST /site/link` makes one
  through the API for the token's admin), and **My records** lists the player's latest plays and best records from the
  server, with the place on each chart and the keyboard's mark.
- The PC client's Sound page says how the last game's sound went, as the player measured it: shared or exclusive, the
  device's period, the time from the game's sound to the device's output by the device's own clock, and any gaps (the
  device running dry, or the game's sound falling behind). `--status` prints the same line. The player writes it beside
  its settings file, `last-game-sound.txt`.
- Discord and Slack on the admin pages' Notices page (the Maintenance page's new name, at the same address): a message to a
  chat through its webhook when a player starts broadcasting and, if wanted, when the broadcast ends; when someone takes a
  song's chart's #1 from another player; when this month's #1 changes; when maintenance begins and ends. Each webhook has
  its own language and choice of events, a Send a test button, the address masked, retries with a wait and the last
  failure on the card and the status page; Discord's embeds and Slack's blocks call nobody by what a name holds. The API
  has the same (`/webhooks`).
- A Server page on the admin pages for the server's whole life: its state and its one address; Restart and Stop the
  server where the install can do them (the Windows bundle, Linux and macOS), with a page after a stop that says when the
  server has stopped and when it runs again; Check and repair (the folders, the database's integrity, the owner's sign-in
  for the players' site, the song list, the phone app, and the program's own files against the install's list of them);
  the server's data part by part with its size, deleted part by part after a backup, once the word is typed; and
  Uninstall, which removes the server from this computer (with the data kept or not). With Docker Compose and Kubernetes
  the page names the commands. Each has its command, `repair`, `delete-data` and `uninstall`, and its API route.
- The server's start window, `./opendmtq up`, `setup` and `status`: the OpenDMTQ wordmark drawn in text, state words in
  colour, values in one column, and a block with the one address and the owner's sign-in. Plain text in a log, a pipe or
  with NO_COLOR.
- Notices in the game at every change of a broadcast switch, the player's or the server's under it, also when a
  broadcast ends and while the server's broadcasts are off, each with its own number (`toast_id`, `toast_kind` in
  `/live/state`); and at every change of the maintenance notice for players already in the game.
- The server hands the PC clients that play on it their updates: those of the version of the installer it hands out, at
  `/updates/` on its one port. A release's tools image brings them, a host install's kit carries them in, and any other
  install fetches them from the release. A launcher looks at its server first and at GitHub's releases second, and goes
  no further than the version its server hands out, or than the server's own version when it hands out none: launchers
  stay matched to their server, on a network with no way out too. The admin pages' App page says what the server hands
  out, and `GET /app/windows/updates` gives it file by file.
- Delta packages: each release has `opendmtq.client-<version>-delta.nupkg`, what changed since the release before, which
  a PC client of that release downloads instead of the whole update and its own updater puts the new version together
  from. When what it puts together does not hold the release's files, the whole package comes instead.
- The PC client's Sound page: master, music and effects volumes and an equaliser (Flat, Bass, Vocal, Treble, or three
  bands of the player's own at 120 Hz, 1 kHz and 6 kHz), with `--set music_volume=`, `effects_volume=`, `eq=` and
  `eq_low=` to `eq_high=`, and `--status`.
- A sound panel over the game, from the bar: the same volumes and equaliser, heard as they change, kept for the next game
  and shown by the launcher.
- The bar over the game by touch: a tap on its handle, a long press or a pull down brings it; a mouse brings it by
  pointing at the top or by pressing and pulling down. In a song a press reaches the game unless the game has been quiet
  for 1.5 s.
- The PC client's installer, run again, offers Open, Repair, Update and Uninstall (with the player's data kept or not),
  and Windows' Apps removes the PC client the same way, in OpenDMTQ's design.
- The launcher's log names each display's current rate, its highest rate at its size and whether Windows changes the
  rate by itself (dynamic refresh rate).
- A page of each player's own on the admin pages, from their name on the Players page, for what the game keeps of them:
  their MAX POINT and Q POINT, set, added to or taken from, as the game's top bar shows them; unlimited currency, the
  player's own and one for every player (the game is told 99,999,999 of each, nothing is taken, purchases are kept as
  usual; off until turned on); their level and experience, by the game's own table; the characters, add-ons, notes and
  skins they have, given and taken; a ban with a reason and an end, which the game refuses their sign-in for with the
  reason shown over it, and the site and the PC client refuse their accounts for, with their broadcast stopped; their
  purchases; every change made about them, who made it and from what to what; and their game state reset to a new
  player's. The Players page has what a new player starts with, unlimited currency for all, and the banned players. Each
  has its API route.
- The owner's notice: one line the owner sets on the admin pages, with an end of its own if wanted, at the top of every
  page of the players' site for everyone signed in. A visitor closes it until their next visit, and new words show again;
  the pages that look again by themselves take it up and drop it without being opened anew. The Maintenance page is now
  the Notices page, which holds it, maintenance, and the messages to Discord and Slack; its API routes are `GET`, `PUT`
  and `DELETE /notice`.
- MY PAGE on the players' site, from the name and badge at the top of every page: the player's profile as the game shows
  it (level, EXP, MAX POINT and Q POINT, the in-game items, the items owned and equipped), their achievements with the day each
  was earned, their places overall and this month, their broadcasts, and every play and best record a page at a time.
  The account tab shows everything the site keeps about the account and changes the password and the ID (with the
  current password, under the sign-in's limit; the plays and the API tokens stay with the account) and signs out
  everywhere else; each of the three ends the account's other sign-ins, to the admin pages too, and each is in the admin
  pages' log of changes. Its JSON twin, `me.php?json`, for a script with the site's cookie.
- The owner's password on the admin pages' Server page, by the owner alone: it works at once for the admin pages and the
  players' site, and the owner's other sign-ins end (also after a change on the command line, at the admin pages' next
  start). On the command line, also the way in when it is lost, `./opendmtq password` (`OpenDMTQ.exe password` on
  Windows); the API's `POST /server/password`.

### Changed

- The PC client's sound buffer is **Low** by default: Windows' shortest period for the device in its low-latency mode,
  or the shortest shared buffer Windows gives a device that has no shorter period than its standard one. Measured through whole songs on
  Windows, the sound reaches the device about 8 ms sooner than with **Normal** when shared and 21 ms sooner when
  exclusive, with no gap.
- The game server keeps each player's MAX POINT, Q POINT and level: a song played adds 150 MAX POINT and 10 EXP, the shop
  and the 4 LINE charts that cost MAX POINT take their price, and the rankings show each player's own level. Every player
  starts where all of them were before (999,999 of each, level 99), and an update leaves them there.
- One port for everything. The players' site, the admin pages (`/opendmtq/admin/`) and the API (`/opendmtq/api/v1/`)
  answer on the server's one port, `LISTEN_PORT`: 8791 on a new install, the first free port after it when it is taken,
  on the Windows bundle, a host install, Docker Compose and the Helm chart alike. An exposed server's admin pages stay on
  that same port for the server PC (`localhost`).
- A server updated from 0.10.0 ends with one port too. One on port 80 (no `LISTEN_PORT` and an address without a port,
  or `LISTEN_PORT=80`) moves at its first start to the port its admin pages had, 8791 unless its owner set another (the
  first free one after it when another program has it), as `port` moves a server: `LISTEN_PORT` and `PUBLIC_HOST` take
  the new port, the app is built again for the new address, the site's download page tells players to install it over
  the old one, and on WSL the Windows firewall rule moves with it. The start, `status` and the Server page each say it
  once. A port other than 80 stays as it is, and so does port 80 chosen with `port 80`. Its admin pages, which had a port
  of their own, answer on that one port, nothing answers on their old one, and `ADMIN_PORT` leaves `.env` at the first
  start. In the Helm chart a `publicHost` without a port is on 8791: the Service, the notes and the app built for that
  address. To move a server to another port, use `./opendmtq port <port>` (`OpenDMTQ.exe port <port>` on Windows) or the
  admin pages' Server page: it sets `LISTEN_PORT`, the server answers there from its next start with the app built
  again for the new address, and the site's download page tells players to install it over the old one.
- The owner's ID and password from `.env` sign in to the players' site too. A sign-in to the admin pages outlives a
  restart of the server.
- The name and badge at the top of the site lead to MY PAGE for every account (an account linked to its player led to
  the player's public page, which MY PAGE now links to).
- Sign-in and password forms: labels, Show inside the password field, what is missing said under the field, the ID kept
  for the next time, Enter sends; the other forms of the admin pages say what is wrong under the field, and every field
  and search box has the sign-in's look.
- Switches and small changes on the admin pages (the players' and the server's broadcasts, the Broadcasts page's
  settings, accounts, maintenance, songs) change the page in place, with the server's words in a band under the bar.
- Words shown only under a mouse pointer (the keyboard mark's count, dates, the marks of charts and days) also come with
  a tap and with the keyboard.
- The Broadcasts page, the Players page and the API say how the server's switch and each player's go together.
- The release's files say what each is, for which system and architecture and which version, in lower case:
  `opendmtq-pc-client-<version>-windows-x64-setup.exe` for players, `opendmtq-server-<version>-windows-x64.zip`,
  `opendmtq-server-<version>-helm-chart.tgz`, `opendmtq-phone-runtime-<version>-android-arm64-armv7.zip`, the PC client's
  update feed and packages, and one `opendmtq-<version>-sha256sums.txt` with its signature. The player alone,
  `RELEASES` and `assets.win.json` are no longer published, and installed PC clients update as before.
- What the server hands out and keeps is named for what it is, in lower case too:
  `opendmtq-pc-client-<version>-windows-x64-setup-<address>.exe`, `opendmtq-phone-app-<date>-android-<address>.apk`,
  `opendmtq-server-backup-<time>-<why>.tar.gz` (backups named before still count), the players' and plays' files, the
  request log and recordings.
- A server of 0.10.0 or older fetched the phones' runtime and the PC client's installer from the latest release by
  their old names; from 0.11.0 on a server fetches them from its own version's release by the new ones. One of 0.10.0
  that needs either again (its own copy gone) gets them by updating to 0.11.0 first.
- The launcher's menu is a column on the left again, and the first start's steps run down its side.
- The PC client's installer draws its own header, without Windows' title bar: its top moves the window, and its own
  minimise and close buttons sit at the top right.
- A setting changed in the launcher changes its own row only: no page is drawn again whole, and nothing flashes. The
  launcher's drop-down lists are in OpenDMTQ's design, open over everything else and close when the window moves.
- The launcher's sign-in forms work as the site's: labels, Show inside the password field (by the keyboard too), what is
  missing said under its field, the ID kept, Enter sends.
- The launcher's pages and lists scroll by dragging with a finger. Its notices come at every change (a newer launcher, a
  sign-in that ended, a server that stopped answering), and the files it reads are read the same after Notepad saved them
  (a byte order mark, Windows line ends, spaces, quotes).
- The upscaler, used below a render scale of 100 % only, is AMD FSR 1 by default: in the player's measurements it is as
  sharp as the game's own picture and nearest to it at 50 %. A PC client that kept the earlier default without choosing
  it takes FSR 1. SMAA is the highest anti-aliasing preset.
- The player asks the server for broadcast notices every 5 s (every 15 s before).

- A server takes the PC client's installer from the release of its own version when there is one, else from the latest
  release, so that the installer and the updates it hands out are of one version.
- The words in the product say what is, and what a person must do to go on: no advice on how to set or use the game,
  whom to ask or which address is best. Korean says 다운로드 for getting the app or a file again, and one word for each
  thing across the admin pages, the site, the launcher and the game. The launcher's About page, its installer and the
  Windows bundle's README carry the project's notice word for word as the site's footers have it.
- The server's start window on Windows' own console with a Korean, Japanese or Chinese code page or font draws its
  wordmark and headings' lines in plain characters of the same width, which that console does not draw two columns wide.
- The site's download page has one main button, the app's.
- `./opendmtq up --no-firewall` leaves the Windows firewall alone under WSL, as `setup` and `expose` do with it.
- The PC client's pages stand on the window's own background: between and round the cards the page shows its lit top,
  the shards at its edges and its dots, where a near-black slab covered them from under the page's title down, and each
  card has the site's glass edge, a hairline with a brighter top. The launcher, the site and the admin pages lose the
  details that said nothing: the glow round state lights, switches, a focused field, the S grade, the replay's knob and
  the live frame, the stripe along the menu's current page and along two boxes of the admin pages, the band on a job's
  log before it ends, and boxes inside cards where rows and a line say the same; the perfect play mark's letters and a
  hidden song's row read at 4.5:1 and more.

### Security

- Each release's checksums are signed with the OpenDMTQ project's Ed25519 key (`opendmtq-<version>-sha256sums.txt.sig`).
  A PC client takes an update only from a release whose checksums the project signed, wherever it comes from (its
  server's plain HTTP, GitHub), and checks what it downloads against them in a folder of its own before anything goes
  into the program's folder: a tampered package or checksums signed by another key are refused, said in words, and
  nothing changes. The server checks the runtime for newer phones, the installer and the PC clients' updates against the
  same before it uses or hands out any, and the admin pages say what it refused. A PC client of 0.10.0 or older checks
  no signature: it updates to this release from GitHub as before, over HTTPS, and every update after that is checked.
  The install guide has the public key, and how to check a release by hand.
- An exposed server's admin pages and API take a visit as the server PC's own only when it carries none of the headers
  a proxy adds to say whom it passes on (`X-Forwarded-For`, `Forwarded`, `X-Real-IP`, `X-Forwarded-Host`,
  `X-Forwarded-Proto`, `Via`): a reverse proxy on the server PC no longer passes visits from elsewhere to them. No
  header exempts a visit from the limit on sign-in tries. Rootless Docker counts as Docker Desktop, whose port driver
  hands the server every visit from one address: there an exposed server's admin pages are off without
  `--admin-public`.

### Fixed

- On a PC the game mixed its sound at 22,050 Hz, which cut everything above 11 kHz from every song. It mixes at
  44,100 Hz now, as on a phone: from 11 to 17 kHz a song is within 2 dB of its own samples, where it was about 35 dB
  down.
- A purchase in the game's shop kept nothing: a note bought for MAX POINT never became the player's, and nothing was
  taken from the balance the top bar showed. Purchases now take their price, unless the player's currency is unlimited,
  and the item stays theirs.
- The ID and password the server's window and `.env` named did not open the players' site, the page the server's own
  address shows, only the admin pages: signing in there failed every time.
- A player's menu on the admin Players page opened under the next card or was cut off by its own on a short list.
- Boxes that touched or ran into their padding on the admin pages, and gaps off the pages' own spacing.
- OFFLINE and the sentence about the game server came only when a page was opened; the site's maintenance word and the
  home page's broadcasts did not come back on a page left open.
- `.env` as Notepad saves it (a byte order mark, Windows line ends, spaces around `=`) is read the same everywhere.
- A sign-in refused for too many tries is in the log of changes; an account without admin rights is told so.
- On a display that Windows 11 runs slower while nothing moves (dynamic refresh rate), such as a 180 Hz panel shown as
  60 Hz, the launcher offered no frame limit above 60 and VSync held the game at 60. The launcher now offers every rate up
  to each display's highest at its size, and the player asks Windows for the panel's full rate, measures the refreshes
  and follows them.
- A window resized or switched to full screen after the game had started kept the game's first size and stretched its
  layout; the game now lays itself out again at the new size.
- Pulling the bar over the game down with a mouse could show the whole bar for a moment; the bar follows the pointer and
  settles where it is let go. The player's refresh meter no longer miscounts on a PC whose timing is unsteady.
- The sound set in the game's own menu during a game went back to the launcher's at the next PLAY: it is kept now, also
  when the launcher's window was closed during the game.
- A repair, an update or an uninstall in the launcher no longer names `OpenDMTQ-Setup.exe`, a file players never have:
  it says the installer, as players have it from the server's site or a release.
- The launcher's Screen page named a display's highest rate as the game's where Windows says nothing of a dynamic rate:
  it names the rate the display is set to, which the game plays at.
- Deleting the server's data and the repair run beside no restore: either is refused while a restore runs, and a
  restore or a backup waits for them.
- A move to a port below 1024 that the computer keeps from the server's user is refused as that, not as a port another
  program holds.
- `GET /server` gives the uninstall card's list and the download page's notice of a move, as the pages show them; its
  next address is a URL; `POST /server/restart` answers with the run's instance; a deletion naming a part the server
  cannot delete is refused.

## [0.10.0] - 2026-11-13

### Added

- Keyboard play in the PC client. While a song is played, each lane is a key, F J in 2 LINE, D F J in 3 LINE and
  D F J K in 4 LINE from the top, read by the key's place on the keyboard, so that any layout plays the same places; a
  lane can have two keys, to alternate on quick notes. Each press lands where the game judges the lane's next note, and
  the game judges it as it judges a finger: taps and chain points a press each, holds and drags held (the press follows
  a drag's curve), repeat notes a press for each point. The keys play only during a song, never while the game asks for
  text, and let go when the window loses the keyboard or is minimised, the song pauses or the question before quitting
  comes. A player that does not find the game's input where it expects it leaves keyboard play off and says why in its
  log.
- The launcher sets keyboard play on its Controls page: on or off, and the keys of each lane of 2, 3 and 4 LINE from
  the top, with a second key for a lane if wanted. A key goes in by its place on the keyboard, named as the US layout's
  key there, with what the PC's own layout prints there beside it; a key another lane of the same LINE plays, or one no
  lane takes, is refused in words, and Reset keys puts the defaults back. `--set keyboard=` and `--set keys_2line=` to
  `keys_4line=` do the same from the command line, and `--status` lists them.
- A score played with the keyboard is marked. The player's save says so (`X-OpenDMTQ-Keys: 1`); the game server marks
  the play and the best score it sets (a new best by touch clears the mark); the site shows a small keyboard before
  such scores (a song's leaderboard, a player's plays and best records, the home page's newest records) and, with how
  many, beside the totals on the rankings and the home page. The API says `keys` on every play and best it lists and
  `keys_charts` beside every total; the admin pages' Status and Plays mark such scores, and the plays file has a keys
  column. The rankings stay one for touch and keys, and the game's own replies do not change.
- The PC client's guide says how it runs on Linux under Wine, as the tests run it for every release.
- Checks: `PLAYER_KEYS` takes keys by their place on the keyboard, at a song's own time and from a file;
  `PLAYER_TRACE_KEYS=1` logs keyboard play's presses and the game's judgment of a song's notes by type.

### Changed

- The launcher's first start: each step's title is its question ("Which server?", "Who plays?"), in Korean too, and
  while Next waits, a line at the foot of the step says what for. The last step shows how to play, with the keys.
- The launcher's PLAY page: How to play starts with keyboard play's keys, or that it is off, with a link to Controls;
  a ready-check row's link is named after the page it opens, and what will change is a ring; the ready check is as tall
  as its column again.
- The launcher's words: in Korean a log is 로그 and play records stay 기록; outcomes are sentences; the game is open in
  every message; the window an error ends in opens the log's folder; the dialogs over Repair and Delete all say what
  comes of the work. The logo, the Launcher page and the command line show one version, the installed one.
- The player for Windows: the bar waits while a lane key is down, as it does for a finger on the game.
- The host install: `./opendmtq status` says the phone app waits for the game files before they are in, where it said
  the app's build had failed.
- The guides: the README opens with the players' site, then a quick start for playing and one for hosting, the
  system's figure and the guides by reader, shorter; players have a guide of their own (a phone, a PC), and the install
  guide, troubleshooting and the questions and answers have a part for players and one for server owners.
- The player for Windows: the bar's X stands as far in from the bar's right end as the wordmark from its left, so that
  the bar's two ends match.
- The PC client's guide: its pictures of the game again, from a song played with the keyboard on Windows (4 LINE HARD,
  ALL COMBO, 99.1 %), with the bar's new ends.

### Fixed

- The player for Windows: the FPS counter keeps to the game's own buttons in every shape of window. At 21:9 the
  counter at the top left lay on a song's pause button; at 16:10 and 4:3 the counter at the bottom right was drawn
  larger than the game's buttons beside it and covered more of the result's SELECT MUSIC (at 4:3, 49 % of it, now 29 %).
- The launcher's window could open partly under the taskbar on a laptop at 150 % (1920x1080) or at 1366x768, with the
  strip that holds PLAY under it: it opens inside the work area, its title bar counted.
- `--set` with several items kept the ones before a refused one: every item is checked before any is applied.
- The PC client's guide said Esc pauses a song: in a song it does nothing, and the game's pause button pauses.

## [0.9.6] - 2026-11-13

### Changed

- The player for Windows: typing in the game's text fields, such as a new player's name, replaces the text they open
  with; Backspace clears it, and an arrow key keeps it to add to.
- The player for Windows: the handle brings the bar from the handle, its line and the space right beside its tab, no
  longer from over the game's own buttons beside it, such as SKIN in the music list.
- The launcher looks for a newer version once at each start and shows it on the Launcher page and at the window's foot,
  with Update to that version; nothing installs by itself, and nothing is said offline. `--status` names it too.
- The launcher: an uninstall from Windows' Settings, Apps ends with the launcher's own card saying what went and what
  stayed; the PLAY page keeps its buttons in view, the ready check as tall as its rows; an opened drop-down's choices
  line up with its closed box. The installer names both shortcuts it makes.
- The admin pages: one primary button to a screen. Making an account has one name on every page and one heading after
  it, with names in quotes. The message for a new player names the server as its app is named on the phone, and the
  installer for Windows when the site has it.
- The admin pages: the setup's App step and the Status page say their code downloads the app; a server in containers
  says its game files come in through the command line; the empty Players page says when a player shows there; the
  Status page's disk bars are plain, fill with what is used and count recordings alone.
- The command line: `up`, `status` and the setup's end name one admin address, with where its password is. The setup
  says which file names it looks for when it finds none, asks which folder only when there are two real places, and
  writes a line of words where it wrote JSON, as the Windows bundle's window does.
- A release's images carry its number, and a copy without git (a source archive, the closed network's copy) shows its
  version.
- On a phone, the home page's broadcasts box with nobody on air is two lines high.

### Fixed

- The player for Windows: after the game was minimised and brought back from the taskbar, the bar came back as a still
  picture over the top of the game, its clicks going to the game underneath; an old FPS count or a finished notice
  could come back the same way.
- The player for Windows: a button of the bar pressed while the bar was still sliding down did nothing.
- The player for Windows: under Wine the overlay's words were not drawn in its own face, and its Korean showed as empty
  boxes.
- After a restore on the admin pages, the game's and the site's rankings showed the boards from before it until enough
  plays came after; they are worked out again from the restored data.
- The game server: a song list replaced while a request read it could leave saves and rankings with the old list's
  charts until the list changed again.
- The Accounts page: a new token or password was above the screen, the page back at its form; it is on screen, with
  the focus.
- The Status page counted the recordings' limits as recordings, and the Requests log counted the admin pages' own
  requests as a script or a bot.
- The launcher: Help's Start over stood 3 pixels off its column under Windows' fonts; Delete all left Velopack's log
  and the installer's logs behind.
- The guides: importing songs with Docker, the Status page's Add a player card, filling the Kubernetes game files
  volume, what the Windows bundle's backups hold, removing Docker's two images, the PC client's button and sound mode
  names.

### Security

- The game server takes at most 64 calls in one request and a body of at most 2 MB, as the Helm chart's router already
  did for bodies: a larger request is refused before any call runs.

## [0.9.5] - 2026-11-12

### Changed

- The player for Windows: the handle at the game's top centre is a short piece of the game's green line with a small
  glass tab hanging from it and a chevron pointing down, so that it shows where the bar comes from (26 by 19 pixels in
  a 1280x720 game, was a line 28 by 5). It follows the game's scale in a window of any shape, clear of the header's
  buttons and words.
- The player for Windows: the bar slides down out of the game's top edge and back up, in step with the display, with
  the handle on its foot; the broadcast notice and the FPS counter at the top move with it. With Windows' animation
  effects off it comes and goes at once.

### Fixed

- The game server: a save and a ranking no longer read the whole song list at each request; two processor cores now take
  671 saves a second, against 536.
- The server: with many clients asking back to back at once, a player's own request waited for a free worker for
  seconds. A kept connection now carries 25 requests: with 150 such connections a player's save waits 0.9 s at the
  median, against 4 to 6.

## [0.9.4] - 2026-11-12

### Changed

- The player for Windows: what it shows over the game (the bar, the broadcast notice, the FPS counter and the question
  before quitting) is drawn at the game's own scale, so on a display at 150 % or 200 % it covers no more of the game
  than at 100 %; it is never smaller than half its size at Windows' scale. The smallest game window is 480x270 at
  Windows' scale, and the launcher's Screen page and `--set window=` offer nothing smaller.
- The launcher: one lime button on each screen; the first-start guide's SOUND CHECK step shows the volume first, under
  the title Sound and screen, and its last step has no Skip; text picked in a field is in the launcher's colours.
- The site and the admin pages: one set of text sizes on every page; the download buttons in one size; the home page's
  new records in their charts' difficulty colours; the admin pages' meters, bars and charts in plain light, so that
  colour marks a state; the song tiles beside a long title no longer have a hole in them; the way to the broadcasts is
  red only while someone is on air.
- Every install shows the same version for the same code: the release, and past it the release and its commit.
- The API: a player's average accuracy is rounded as the site rounds it, and is null for a player with no plays. A
  maintenance message is at most 200 characters, on the page and in the API.

### Removed

- The player for Windows: F11 and Alt+Enter no longer switch full screen; the bar's full-screen button and the
  launcher's Screen page do.

### Fixed

- The game server: on a server with many plays a save read the player's whole history twice, 19 ms of a processor on
  a million plays; it now reads two indexes, made at the server's next start, and takes under 2.
- The game server and the site: the TOTAL ranking, the site's rankings, its home page and its list of songs added up
  every play or best again at each look (100 ms on a million plays); they now keep what they worked out until the
  next play or change of a player, and answer in about 1 ms. The home page read the whole log on a server whose
  newest plays were no records (2.4 s); it now reads an index of the records.
- The player for Windows: on a computer with two GPUs, as most gaming laptops have, it asks NVIDIA's and AMD's
  drivers for the fast one; its log names the GPU that draws the game.
- The player for Windows: no key changes the window while the question before quitting is up; closing a minimised game
  from the taskbar asks over the game's picture instead of a black one; in the smallest windows on a scaled display the
  bar's buttons no longer cover its wordmark.
- The launcher: an address with a space is refused in plain words, in the window and with `--server`; after a failed
  connection the typed address stays; opening OpenDMTQ from the installer no longer says it added a server already in
  use; update and install errors are in plain words in both languages; PLAY and Help show the game's end at once; Help
  no longer moves after one of its tools.
- The site: names with `&` or quotes show as typed on the Live page; the average accuracy is rounded, not cut; a
  broadcast's time on Live matches its card; pages no longer move when their fonts arrive; the download page says
  plainly when there is no app yet; the licenses page names the player's fonts and picture effects.
- The admin pages: the change log says every change in words, in both languages; the disk chart counts the game files,
  the app, the installer and the runtime as OpenDMTQ's own; the song search finds a song by the number the list shows;
  the Players page with no players says so plainly; counts of one read right; the Korean pages use one word for each
  thing.

## [0.9.3] - 2026-11-12

### Changed

- The player for Windows: the FPS counter's place is the bottom right unless another corner is chosen, as the top is
  the bar's: measured on the game's screens, it covers the least of the game's own labels and buttons there (none on
  28 of 37 screens; on the others the end of a button on two kinds of screen, the loading screen's version or a tile's
  edge). The launcher's Position row says it is the default. Another corner chosen before stays; the top left, which
  every launcher before this one wrote whether chosen or not, reads as the new default.

## [0.9.2] - 2026-11-12

### Added

- The player for Windows: a small tab at the top centre of the game shows where the bar is. Resting the pointer on it,
  or on the top edge, brings the bar down once the game has had no click, touch or held note for 1.5 seconds, so a song
  is never interrupted; clicks pass through it to the game. The bar also shows for 3 seconds when the game's picture
  first appears and after each switch between a window and full screen.
- The player for Windows: a minimise button on the bar.
- The launcher's command line: `--servers` lists the servers it knows, and `--skip-guide` skips the first-start guide.

### Changed

- The player for Windows: the bar carries the OpenDMTQ wordmark, and the buttons over the game are the launcher's: the
  bar's X is lime from the start, so it is seen at once, and in the question before quitting Keep playing is the main
  button. The window has a dark title bar and no buttons of its own: the game is minimised, put in full screen and quit
  from the bar.
- The player for Windows speaks the launcher's language: the game, what the player shows over it, and its messages.
  "Same as Windows" keeps Windows' display language.
- The FPS counter is off by default and fainter, so the game shows through it; on, it sits at the top left, and a
  Position row moves it to another corner (`--set show_fps=on|off`, `--set fps_position=<corner>`; an older corner
  setting still works).
- With VSync on, the frame rate steps down only when more than a quarter of the frames are late (it was 3 %), and tries
  the faster rate again sooner: on a 240 Hz display a song now holds 240 frames a second, where it fell to 120 or 60.
- NVIDIA NIS no longer sharpens, which drew rims around text and lines.
- A render scale keeps the window's exact shape: 67 % of 1920x1080 is 1280x720 (it was 1286x724).
- Keys and clicks reach the game without waiting for what the player draws over it.
- The launcher: buttons stand out and sink when pressed, and fields are set in; the wordmark has no "PC" after it; with
  VSync on, the Screen page offers no frame limit above the display's rate; `--set window=` refuses the sizes the
  Screen page leaves out.

### Removed

- MSAA 2x, 4x and 8x: they left the game's picture as it was, no pixel more than 2 levels off, as between two runs
  without them. A setting with MSAA reads as CMAA 2.

### Fixed

- The player for Windows: a song's start could freeze the picture for good while the sound went on (8 of 142 starts on
  one PC; 0 of 80 now).
- The FPS counter read 0 for the whole game after the first loading.
- The overlay's glass was missing at some sizes of the game (1366x768 and others), its picture could stay stuck on a
  driver that cannot wait on its read, and it kept 66 MB at 4K after the question closed; thin lines no longer shimmer
  in its blur.
- The broadcast notice no longer repeats its tag.
- Sound with the device alone and the safe buffer no longer starts each stream with a 1.6 ms gap.
- The player's settings file: a volume out of 0 to 100 is held to it (it fell back to full volume), keys and values are
  read in any case, and a byte order mark no longer hides the first key. The smallest window is 480x270 everywhere.
- The launcher: the status line no longer keeps a stale message once you act, and changes language with the window; the
  Sound page keeps its place and the keyboard's focus; Tab brings a control out of view into view; a server that does
  not answer no longer shows green in the ready check (PLAY still starts the app this PC has).
- The launcher's words are shorter and plainer, in both languages.
- The player for Windows: a timed wait in the game could end too early.

## [0.9.1] - 2026-11-11

### Fixed

- The player for Windows: the bar's chips and the question's buttons act only when let go where they were pressed, and
  look pressed while held; a press that slid from Keep playing onto Quit the game no longer quits.
- The player for Windows: while the bar is up, the broadcast notice and an FPS counter in a top corner move down under
  it instead of being covered by it.
- The player for Windows: the FPS counter reads a steady rate as it is (60, not 58 and 62 in turn), takes nothing from
  moving the window, reads 0 while the game holds still, and its small grey text keeps 4.5:1 over the game's white.
- The player for Windows: Alt pressed and let go alone, F10 and Alt+Space no longer put the window in Windows' menu mode,
  which held the next key.
- The player for Windows: the bar no longer flashes when the pointer crosses the game's top edge on its way to the
  window's title bar; it shows when the pointer rests a moment at the edge.
- The player for Windows: the broadcast notice breaks a long line into even lines, with no word left alone under it.
- The launcher's Screen page keeps its place and the keyboard's control when a choice redraws it (the render scale, the
  upscaler, anti-aliasing, VSync, the mode), instead of going back to its top.
- The player for Windows: the bar covers the game's own X at the top right of its song and music screens whole (74
  instead of 52 at 720 lines), with no tip of it showing under the bar.
- A restore of another PC's backup on a host install or in the Windows bundle told the owner to run `./opendmtq restore
  --with-key`, which only Docker Compose's command line has. There the Backups page now says to put the backup's
  `keystore` folder in place of `data/apk/keystore` with the server stopped, so that phones keep updating their app.

### Changed

- The player for Windows: the bar, the question before quitting, the broadcast notice and the FPS counter are frosted
  glass over the game, as Windows' acrylic is made: the game's own picture behind each, blurred and a little more
  saturated, under a charcoal tint, with a light edge, a faint light at the top and a soft shadow. Their words keep
  4.5:1 or more over the lightest picture behind them (the tint deepens under them where it is light). The picture is
  read from the game's frames at a quarter of its size, at most 20 times a second while a piece is up, without waiting
  for the graphics card, and not at all while none is.
- The player for Windows: the overlay's pieces take the game's own shapes on their glass: its small corners and its
  bevel, its green line along the bar's and the notice's foot and under the question's title, its OFF chips for the
  bar's (full screen lit with a lime edge under the pointer, the X red), its green button for Keep playing and the grey
  of its tabs for Quit the game (red under the pointer), both with white bold words, its lime border and glow for the
  keys' choice, a tag with a slanted end for the notice's LIVE (grey ENDED), and its Q and MAX box for the FPS counter.
  The words are set in Pretendard, titles and buttons bold, and the bar's name, OPEN DMTQ, in the launcher's wordmark
  face (both under the SIL Open Font License, in the player's `fonts` folder). The question's card sits over the game
  dimmed and blurred; the notice slides down as it fades in.
- The broadcast notices, on phones and PCs alike, no longer repeat the LIVE mark in their title and say where to watch
  more briefly: "Your play is live" / "Watch it now or later under LIVE on" the server's site; the end of broadcasts for
  the whole server says "Broadcasts are off on this server".
- The player for Windows: the question before quitting says what quitting mid-song loses ("Quitting mid-song loses
  that song's record"), which holds on any screen; it spoke of a song in progress where there was none.
- The player for Windows: an FPS counter at the top left sits just right of a song's pause button instead of over it.
- The player for Windows: the question before quitting keeps within three quarters of the game's width, its contents
  scaled with it, so a small window on a display at 150 % or 200 % gets a card in proportion to the game.
- The player for Windows: the bar's X turns red under the pointer, as Windows' own close does, instead of the game's
  green, which reads as go on.
- The launcher's Screen page: the upscaler's hints no longer say what 100 % does (the row is shown only below it), and
  the page's line under its title names the picture's quality too.
- The guides: the PC client's guide lists every setting `--set` takes with its values, installing has updates,
  backups and moving a server to another computer, troubleshooting leads to the PC client's, the notice names the
  picture's passes and their licenses, and CONTRIBUTING lists what a release publishes.

## [0.9.0] - 2026-11-11

### Added

- The player for Windows offers two upscalers for a render scale below 100 %, beside the plain stretch: AMD FidelityFX
  Super Resolution 1 (its edge-adaptive upscaling, then its sharpening) and NVIDIA Image Scaling. The game draws at the
  scaled size into a frame of the player's own, and the upscaler draws it to the window's full size. The launcher's
  Screen page offers them under the render scale (Upscaler, shown below 100 %), and `--set upscaler=bilinear|fsr1|nis`
  sets the same.
- The player for Windows offers anti-aliasing: Intel's CMAA 2 and SMAA over the finished picture, or MSAA at 2x, 4x or
  8x as the game draws. The launcher's Screen page offers it (Anti-aliasing), and `--set
  anti_aliasing=off|cmaa2|smaa|msaa2|msaa4|msaa8` sets the same. CMAA 2 runs on OpenGL ES 3.1's compute shaders; where
  the graphics card has none, the player uses SMAA and says so in its log. With an upscaler, the anti-aliasing comes
  first, at the size the game draws at.
- The player for Windows can show an FPS counter in a corner of the game: the frames a second and the frame time, twice
  a second, in the look of the game's own dialogs. The launcher's Screen page offers it (FPS counter: off, or a corner),
  and `--set show_fps=off|top_left|top_right|bottom_left|bottom_right` sets the same.

## [0.8.2] - 2026-11-11

### Changed

- The player for Windows draws what it shows over the game in the game's own look and at the game's size. A bar comes
  down when the pointer touches the game's top edge (or a finger draws down from it), with full screen and an X; the X
  asks in the game's own dialog, Keep playing or Quit the game, so that a click by mistake does not end a song, and the
  window's own X asks the same. The broadcast notice takes the same look. The menu is gone, Alt+F4 does nothing, and
  holding Esc no longer does anything: Esc is the game's Back key.
- The lines `.env` may hold are a table in docs/install.md (Settings); `.env.example` is gone from the repository's
  root, as the setup writes `.env` itself.
- For contributors: the player for Windows's planned keys (`PLAYER_KEYS`) also click (`click=x,y`), type (`text=...`)
  and compose through the input method (`ime=...`), which filled in the game's Set nickname on Windows in English, in
  Hangul and through the Korean input method; `debug.arm32.livebreak <seconds>` takes a phone's broadcast encoder as
  broken that long into each session, which showed the retry ten seconds later, the giving up after three, and the
  count starting over after a minute's session on a phone.

## [0.8.1] - 2026-11-10

### Security

- The player for Windows keeps the server's app in its own folders: a name with "..", a drive, a backslash, a device's
  name or a relative ".." above where it starts is refused as a missing file, the runtime's own names stay, and any
  other name lies in the game's own `data\root`, which is its "/" and its current folder. The game's system, its
  libraries and its APK are read-only to it, as on a phone.
- The player for Windows starts only when the app's package is a package name as Android's are made, and says why in
  its log and its error box otherwise. The PC client takes from a server only an app with a proper package and file
  name, stops a download at the size the server gave, and downloads again an app kept with no proper package name.
- The player's video reader keeps to what the file holds: a box size stepping back, a sample count or size the file
  only states, or many chunks and runs no longer hang the player or take gigabytes.
- The game server refuses a signed save whose counts no play gives (each is a whole number from 0 to 10,000), one for a
  player without an account, or one of a chart no song of the server has, with SVC.05008, which the game handles without
  a popup, and stores none of them. A play finished while the owner hides its song is kept.
- A sign-in or sign-out form on another site signs nobody in or out.
- Wrong passwords at accounts with admin rights count for the whole server, on the site's sign-in and the PC client's:
  30 in ten minutes.
- The site, the admin pages and the API may not be framed or sniffed, and keep their addresses from other sites.
- The importer leaves out links and linked folders, wherever they point, and its container has no network.
- On Windows the setup takes only a drive letter's path, and its looks at folders need an API token that writes.
- A password typed for an account with admin rights has 10 characters at least.
- A restore keeps today's site accounts and their passwords, as it keeps the API's tokens.
- A host install's `.env`, one-time sign-in and download key are readable by their owner only.
- The app's signer gets the key's password from a file, never on its command line.
- The firewall script runs from its elevated command itself, not from a copy in the temporary folder.
- The admin port's copy of the video player takes its own file name only.

### Added

- `networkPolicy.enabled` in the Helm chart, off by default: only the router's pods reach the api pod's port 8080.
  CI renders and checks it.
- A broken download goes on where it stopped: the app (`/apk`), and the installer for Windows from the site
  (`/windows`), the API (`GET /app/windows`) and the App page (`Range`, `If-Range`, `If-Match`; 206, 412, 416).
- `GET /site/live` gives `past_rev`, the sign of its list of recordings, as the live page has it.

### Changed

- The PC client switches pages, scrolls and changes language faster at 200 %: the picture behind its pages is drawn
  once for each width (the page area's background from about 200 to 31 ms). Its dialogs open faster, it keeps no copy
  of the page's picture (13.6 MB less at 200 %), and it asks for the ready check once at start. Its screens are checked
  at 200 % too.
- The player for Windows asks the game server for compressed answers, as the game on a phone does: the song list comes
  in 17 KB instead of 145 KB, and a heavy player's scores in 4 KB instead of 148 KB. A compressed answer cut short,
  broken or past 64 MB fails as a lost connection does.
- The Players page with many players opens three times as fast on a computer and twice as fast on a phone (400 players:
  1.7 s to 0.5 s and 0.8 s to 0.4 s, 1.37 MB to 0.78 MB). More's rename, reset and delete are made for a row when it
  opens.
- Making a backup, restoring one, and adding, hiding, showing or removing a song on the admin pages run as jobs: one
  that takes more than 3 seconds shows its progress on its page, then how it ended. `GET /jobs` lists them.
- The Accounts page sends the player list once (562 to 108 KB with 32 accounts and 400 players); the admin pages'
  scripts are one file the browser keeps; the admin port answers 304 for its copies of the site's files; Keep updating
  on the Logs page gets nothing until a request comes in, then a compressed list.
- The recordings count on the status page and in `GET /status` comes with the disk figures, at most a minute old and
  fresh after a deletion.
- Starting the server, or adding, hiding, removing or restoring songs, no longer remakes every added song's tile: each
  is made once and kept beside the song's files (with 100 added songs a song-list rebuild takes 0.4 s, not 4.8 s).
- The site's pages cost less to keep open: an open live page fetches the recordings' list only when it changed (7.3 to
  0.24 MB an hour), the home page takes pictures only of the broadcasts on the screen, every two and a half minutes (45
  to 11 MB an hour), and the site reads only the recordings it shows. Its stylesheet, scripts, icon and fonts are named
  by their versions and kept a year, and its scripts are compressed.
- A page in English loads 33 KB of the text font instead of 444 KB: the first visit to the sign-in page takes 83 KB
  instead of 491 KB.
- The site's sign-in says what is missing in its own words and look, and an empty form is not a wrong password.
- The monthly rankings read the play log from one index (TOTAL from 14.4 to 9.9 ms with 600 players and 15,000 plays
  in the month), and the site's This month is the game's own board (17.0 to 10.9 ms).
- The broadcast's encoder threads sleep while broadcasts are off. The player for Windows compiles its broadcast's
  shaders at the game's first screens, so a broadcast that starts mid-song no longer stalls a frame; each start's cost
  is in the log.
- The menu button over the game is drawn once, and fades by its opacity.
- For contributors: the PC client's unit tests take about 3 s instead of 38 s; `arm32/test_windows.sh` also runs the
  broadcast requests' test under Wine; the broadcast of the player for Windows is in `live_desktop.cpp`,
  `live_capture.cpp`, `live_mf.cpp` and `live_state.h`; the song list's rebuild runs in steps of its own.

### Fixed

- Each broadcast request has ten seconds in all, the server's name lookup included: a server that answers slowly or
  not at all no longer holds a phone's or a PC's uploads.
- A phone's encoder that breaks while it broadcasts, or that the system takes back, is tried again 10 s later and given
  up after three, instead of leaving the broadcast silent.
- Numbers from the server too large for an int count as the highest quality, not the lowest, and the server's notice
  keeps characters beyond U+FFFF. The player for Windows puts only letters, digits, '-' and '_' of its device id in a
  URL.
- The shared sound output of the player for Windows gives up on a device that takes nothing for two seconds, and moves
  at once when the devices change. AudioTrack.write checks its range without an int's overflow. Where its error box
  cannot be drawn, Windows' message box says the error.
- In the PC client: its settings are never saved with a Connect, a sign-in or the app's details half made; a ready check
  that answers after a newer one no longer leaves PLAY and the check's rows as they were before; a download stopped
  while the Online page or the guide's download step is drawn again says it is stopping, as the status line does.
- Also in the PC client: a turn of the wheel after a language switch no longer opens the error dialog; Clear game data
  and Uninstall count the data in the background instead of freezing, and Uninstall's size includes a data folder moved
  to another disk; PLAY has no frame on the bottom bar; Start over, Forget, `--reset` and `--forget` wait for a game
  started from the command line; a dialog over a scrolled page shows that page behind it; worker errors, refused
  sign-ins, app folders that cannot go and failed sound-device listings are in the log, and an update answer that cannot
  be read is a failed check.
- A player's name with bytes that are not UTF-8, as an older server's database can hold, emptied the game's start
  batch for every player who saw it and broke every admin page and API answer that lists players. It goes out with
  U+FFFD, and the server's next start stores it as UTF-8 (from CP949 when it reads as that).
- On servers west of UTC, the hall of fame named every month one month early.
- A player's levels, on the site and in the API, counted hidden songs' charts.
- The admin's routes for one recording, switching a player off and deleting a player's recordings read only that
  recording or player: switching a player off no longer holds the game's saves while every recording is read.
- The App and setup pages kept following a job's log only until one look failed.
- The admin pages' forms are checked in the pages' own look and language, not in the browser's bubbles.
- Two song-list rebuilds at once could fail or leave the added songs half made: every rebuild takes the songs' lock,
  and a restore puts the songs back and rebuilds under it, the command line's restore too.
- The PC client's build, run by a user other than root, can write into what its containers made.

## [0.8.0] - 2026-11-10

### Added

- The player for Windows takes a computer's settings for the picture and the sound, which the PC client chooses before a
  start (`--settings`): full screen from the start, the window's size, vsync on or off, a frame limit, a render scale,
  the sound device, the device alone or shared, how much sound is kept ahead of it, and the volume. With vsync on, a
  frame limit that is a whole fraction of the display's rate, or up to 10 % above one, keeps every frame on the same
  number of refreshes (120 frames a second on a 240 Hz display, every second refresh); another limit is held by the
  clock, each frame still on a refresh (144 on a 240 Hz display). With vsync off, frames go out as soon as drawn, evenly
  at the limit, which may be above the display's rate or none at all. A render scale draws the game at a share of the
  window's pixels, stretched to the window. The device alone (WASAPI's exclusive mode) plays with buffers of the
  device's own period, 3 ms on a device that has it, and gives way to the shared mode when Windows does not allow it; a
  low buffer in the shared mode takes Windows' low-latency mode where the device has a shorter period than its standard
  one.
- `player --audio-devices` lists the computer's sound devices, for the PC client.
- The player for Windows broadcasts, as phones do, while the server's owner has broadcasting on for its player: the same
  stream (H.264 at the server's size, frame rate and bitrate, AAC sound, two-second MPEG-TS segments), made by Windows'
  own encoders from the game's frames and its whole mix. The frames are scaled and turned into the encoder's format on
  the graphics card and read back without the game waiting for them; on a 240 Hz display the game keeps every refresh
  with the broadcast on. A PC whose encoder does not keep up steps the stream down (its frame rate, then its size), as a
  slow network does, and back up after a minute with time to spare. The server's notice that broadcasting went on or
  off shows as a card at the top of the game's window, with the LIVE mark while it is on.
- A menu in the player for Windows, over the game: back to the game, full screen or a window, and quitting the game. It
  comes up from a round button at the top right, from Esc held, from a finger drawn down from the top edge of the game,
  and from Alt+F4 or the window's close button. The button shows while the mouse moves in the top quarter of the game
  with its button up, so it stays out of the way of a song played with the mouse. The game holds still while the menu is open, as a
  phone's game does when its owner leaves it, a broadcast with it, and the arrow keys and Enter choose in it. Minimised,
  the game holds still behind the menu, which is there when the game comes back.
- Over the game, the player for Windows shows its own pointer: a dart in the logo's chrome and lime, all lime while the
  button is down, sized for the display's scaling.
- `client.php` on the site answers the PC client: whether the address is an OpenDMTQ server, a sign-in that gives the
  site's cookie, and the app on offer for a signed-in player.
- The PC client for Windows (`OpenDMTQ-Setup.exe`): an installer, and a launcher that starts the game in the player. It
  connects to a server, signs in, downloads the server's app and keeps it up to date, sets the picture and the sound up
  for the computer before PLAY, and starts the player. It updates itself from the project's releases. Downloaded from a
  server's site, it comes with that server already set; from the releases, it asks for the address on first start.
  Downloaded over HTTPS, it keeps the address with its port, and the server's own certificate authority where the
  server has one, which the launcher trusts for that server alone. The launcher speaks English or Korean, as
  Windows does until one is chosen, and the installer speaks the launcher's. `OpenDMTQ-cmd.exe` does the same from the command
  line.
- The PC client's Help page repairs, clears and removes, each with the same flag of `OpenDMTQ-cmd.exe`: Repair puts the
  program's files that are missing or changed back from the package it was installed from (`--repair`); Clear game
  data deletes what the game keeps, all but the device id, so the PC stays the same player (`--clear-game-data`);
  Start over forgets the servers, sign-ins, apps and settings (`--reset`); Uninstall removes the program, its shortcuts
  and its entry in Windows' Apps, keeping the data for a later install or deleting it too (`--uninstall`,
  `--uninstall --delete-data`). The Online page forgets the server in use as well as the others.
- A switch for broadcasts on the whole server, off on a new server: while off, nothing of broadcasts reaches a phone,
  the PC player or the site (no LIVE menu, no home box, no LIVE marks, no recordings to watch), and uploads are refused.
  The players' own switches are kept for when it is on again. The settings are kept in the database, so they go with
  its backups and with its copy on Kubernetes; a restore on the admin pages keeps today's.
- The admin pages' Broadcasts page has the server's switch, whether new players start switched on, and the stream's
  quality: Light (480p30, 1 Mbit/s), Standard (720p30, 2 Mbit/s), Smooth (720p60, 4 Mbit/s) or Sharp (1080p60, 8
  Mbit/s), each with what an hour takes on the disk. Phones and the PC player follow a change within 15 seconds.
  Turned to start new players on, it leaves every player already there as they are: only those who come after start
  on.
- `GET /broadcasts` and `PUT /broadcasts` in the admin API read and change those settings.
- The admin pages' Players page marks a switch kept on while broadcasts are off for the server, and the Logs page
  records broadcasts turned on or off and changes to their settings.
- Every message box of the PC client, the player for Windows and the Windows bundle is drawn as the launcher's dialogs:
  the player failing to start from its own folder and the bundle's `OpenDMTQ.exe` missing its parts show the
  launcher's dialog over the site's page in place of Windows' plain box, and an error nobody expected in the launcher
  or the installer ends in it too, with where the log is.
- An upgrade is tested in CI and in the local gate: the last release's images are used as people use them, then the new ones start on
  the same data and must have lost nothing (`tests/upgrade/run.sh`).

### Changed

- Alt+F4 and the window's close button open the player's menu instead of ending the game, so that no key pressed by
  mistake ends a song; the menu's Quit ends it.
- The site hands computers the installer for Windows, set up for the server (its address on the installer's end), in
  place of a zip with the player and the app in it. The installer is the same for every server: the builder keeps it
  beside the app (`windows.json`), from the release, from `data/apk`, or fetched from the latest release, and removes
  the zips of 0.6 and 0.7 and what they kept in `data/apk` for their player.
- Without internet, a host install takes the PC client's installer from the kit (`OpenDMTQ-Setup.exe` and
  `OpenDMTQ-Setup.exe.version`) in place of `opendmtq-player-windows.zip`.
- `player --refresh` sets the display's rate that the frame pacing follows too, for a display that gives none.
- The notice in the game when a broadcast starts or ends reads as two lines: what happened, then where the broadcast and
  its replay can be watched (the site's LIVE page, by the server's name). Phones show it for longer. A player on air
  when the owner turns broadcasts off for the server is told that the broadcast ended and that broadcasts are off on
  the server for now.
- Upgrading: a server that broadcast before the switch existed (a player switched on, or `LIVE_DEFAULT=on`) starts with
  broadcasts on; any other starts with them off. With `LIVE_DEFAULT=on`, new players also start switched on until the
  owner chooses on the Broadcasts page.
- The admin pages' Recordings page is now the Broadcasts page: the server's switch and settings at its top, the
  recordings under them.
- In the admin API: `GET /app/windows` gives the installer for Windows, set up for this server, in place of the zip
  with the player and the app; `AppOnOffer.windows` is a `WindowsInstaller` (`file`, `size`, `sha256`, `version`,
  `copied_at`) in place of a `WindowsPlayer`; a player's `broadcast` can be `held` (switched on while broadcasts are
  off for the server); `SiteLive` has `on`; the status page's `Counts` has `broadcasts`, and its `live` counts nobody
  while broadcasts are off.

### Fixed

- The player for Windows could stay behind after the game ended, frozen with its memory, when Windows' way out stopped
  in a DLL's own clean-up waiting for a thread it had already ended (the graphics driver's or Media Foundation's). It
  now ends at once, leaving the clean-up to Windows.

## [0.7.0] - 2026-11-08

### Added

- The player for Windows takes a computer's keyboard and mouse as a phone's: Esc is the phone's Back key (it pauses a
  song, closes what is open and asks before the game quits, and quitting there closes the player), and the mouse wheel
  scrolls what is under the pointer as a finger's drag, across with Shift. The other keys reach the game as the phone's
  keys. Text goes in through an input method as well, Hangul with its syllable still being composed, and Windows' touch
  keyboard comes up when a touch opens the game's text.

### Changed

- The player for Windows makes a touch screen the game's own: Windows' touch feedback is off over the game (no circles
  under the fingers, no press-and-hold square or right click), a finger from the screen's edge stays the game's in full
  screen, each touch reaches the game as Windows takes it in instead of at the window's next look up to 4 ms later, and
  it carries the time the screen saw it.
- The player for Windows runs the game at the refresh rate of the display its window is on, 60 Hz, 144 Hz, 240 Hz or
  another, with a refresh of its own for every frame, where it ran at 60 frames a second on every display. A PC that does
  not keep up takes every second refresh (120 frames a second on a 240 Hz display), then every third, and tries the
  faster rate again after a while. Moved to another display, the window takes that display's rate.
- The player for Windows fits the game to its window on any display: the game fills the window while its shape is
  between 4:3 and 21:9, the shapes the game lays itself out for, and has black around it beyond, as on a display turned
  upright. The first window is sized for the display it opens on.

### Fixed

- The player for Windows tells the game when its window changes size, as Android does: in full screen, after a resize and
  on a display with other scaling, the game draws at the window's new size.
- Text typed into the player for computers reaches the game, a nickname for one: the player closed the game's keyboard in
  the same turn as it gave it the text, and the game's field kept the text it had.

## [0.6.0] - 2026-11-08

### Added

- A player for Windows. The server makes one with its app in it, next to the app, and the site's Download page offers
  it to computers (`/windows`): unzip it and start `OpenDMTQ-Player.exe`, nothing is installed. It runs the same app as
  the phones, through the arm32 runtime on a layer for Windows, with OpenGL ES on Direct3D 11 (ANGLE), sound through
  WASAPI at the device's own rate, video through Media Foundation, the mouse, a pen or a touch screen's fingers, and
  Windows' display language. A release's tools image and the Windows bundle carry it. A server without it (Docker
  Compose built from the source, a host install) fetches the latest release's, again once its copy is a week old, and
  waits a day after a fetch that failed. The App page and the API (`GET /app/windows`) hand it out too
  ([the player for Windows](docs/windows-player.md)).

### Fixed

- On phones that run the game through the arm32 runtime, the game's clock follows the phone's current time zone rules:
  Android 10 and later keep them in a time zone module, which the runtime now reads.

## [0.5.0] - 2026-11-08

### Added

- An HTTP API at `/opendmtq/api/v1/`: all the admin pages show and do, and what the players' site shows, as JSON. A
  request carries a token for reading or for writing, made and revoked on the **Accounts** page or through the API
  itself. The OpenAPI document, `/opendmtq/api/v1/openapi.json`, needs none. The API is open where the admin pages are,
  and nowhere else. `docs/api.md` has the guide and every route.

### Fixed

- The App page starts one build when it is asked for two at once, and waits while an import or the server's own build
  runs, as the setup does.

### Security

- The setup takes `$NAME` and `%NAME%` in a path as they are written, `%USERPROFILE%` among them: a path no longer
  brings out a value of the server's settings. `~` is still the home folder. A path on another computer
  (`\\server\share`, `//server/share`, a `file://` address with a host) is refused before anything looks at it.
- A backup or a build is found by a plain name only. On Windows a name with a backslash or a drive's colon could lead
  outside its folder.

## [0.4.1] - 2026-11-08

### Changed

- The files the setup imports besides the game's app are called the client data (`patch/phone_new`, what the game
  downloads at its first start) and the song data (`DMQ` with `viewImg`: the songs' music, charts and jackets), in the
  setup, the admin pages, the command line, the pictures and the docs. OpenDMTQ's server is its own code: from those
  files it takes only these two.

## [0.4.0] - 2026-11-08

### Added

- A song package's files are checked before the song is added: the music pack, each chart, the video and the preview
  must be in the game's formats, and a chart must have notes and not end before its last note. A package that fails
  is refused with the file and the reason; every file of the game's own songs passes.

### Fixed

- A chart the song data carries empty or cut short, which the game cannot load, is served from its pair: a chart and
  its earphone variant have their notes at the same ticks. The song data tested carries four.

## [0.3.0] - 2026-11-07

### Added

- The songs on their own: the server files' `DMQ` folder, with `viewImg` for the jackets and `_info` for the song list
  or without them, imports as the songs onto the game data the server has, in the setup, on the **Songs** page and
  with `./opendmtq import --songs`. The game data and the songs may also come from two places in one import.
- The setup shows the game data and the songs as two things to import, and names each folder it finds for what it
  holds: the server files, the game data, or the songs.
- An install guide, `docs/install.md`, with each system step by step; the README's quick start is the commands alone,
  and on Windows four lines for PowerShell.

### Changed

- The songs' previews and their tiles in the song list come with the game data, in the patch folder they are in, so
  songs imported later have them. Without songs, a phone's first download is about 22 MB larger.

### Fixed

- `./opendmtq import` of the `DMQ` folder itself takes the jackets and the song list beside it too.
- A client table that cannot be read no longer stops the import: the song list made from it is empty, and the import
  says why.
- A failed import says why in the page's language, not only in the importer's English lines. A folder of the songs
  alone imports them whatever the songs box says, and an app file has no songs box. The **Songs** page lists songs
  imported before the game data, under its warning.
- The command line's search takes the game host's folder unpacked into Downloads as the whole files, not as its parts.
- An archive with the patch folder alone and the songs alone imports both, and an archive inside an archive no longer
  keeps the parts beside it out.
- `./opendmtq` runs on Docker 23, whose Compose has no `--progress` flag.
- Linux and macOS: the one command stops when it cannot ask GitHub for the latest release, instead of installing the
  newest untested code, and says how to start the server again when an update's download fails. `./opendmtq service`
  keeps a path with spaces, `%` or `&` in it whole.

## [0.2.1] - 2026-11-07

### Fixed

- Linux and macOS: the site and the admin pages show the release a one-command install fetched (`0.2.1`), and a copy
  from a clone the date and commit of its code. They showed nothing for the first, and `vv0.2.0` for the second.
- Releases: a rehearsal on a branch (`gh workflow run release.yml`) checks the chart's version against the changelog;
  it stopped at the version check, as a branch names no version.
- The import and the setup take the game's patch folder by itself (`patch/phone_new`, `phone_new`, or an archive of
  either) as what the game needs to start, as the setup says, and it replaces the server's patch folder only. They
  found nothing in it unless the songs' or the images' folder was beside it.
- Files without the songs' folder (`DMQ`), such as the patch folder alone, leave the server's songs as they are. With
  **Import the songs too** ticked, as it is at first, they emptied the song list. Where a folder holds the patch
  folder alone and the whole server files, the whole files come first.
- A song list kept in the folder with the songs (`_info/songList.json`) is read. Only one beside the folder was, and
  the list was made from the game's tables instead.

## [0.2.0] - 2026-11-07

### Added

- Version 1.3.5 of the game gets every fix 1.3.4 gets, as released or changed for another server: no notice at every
  start, no question before the first download, the shop opening on its MAX tab, the panel's own resolution, a menu's
  frame rate kept, a 32-bit screen and textures at full size. Like 1.3.4, it drew at the low resolution on every
  phone.
- With both versions imported, a server's first app is built from 1.3.5, the newer one.
- Every server builds its app again at its next start, as the patcher changed: one built from 1.3.5 gets these fixes,
  one built from 1.3.4 the same app as before.
- This changelog. Each release's notes are its section here, and a release whose tag, chart and changelog name
  different versions stops before anything is built.

### Fixed

- Kubernetes: the Helm chart in the repository carries its release's version, so a chart installed from a clone pulls
  images that exist. It asked for version 1.0.0, which was never published.

## [0.1.3] - 2026-11-07

### Fixed

- Install on Linux or macOS: a download that stalls is cut and tried again (the one command's programs) or stops with
  its message (the code), instead of waiting for ever.
- Releases and CI: the builds of the Windows bundle and of the runtime for newer phones do the same, and every job has
  a time limit.

### Changed

- The guides' sizes are the measured ones: the game's files take about 60 MB without the songs and 4.5 GB with all of
  them. The Quick start's table is shorter, and the last unclear lines were checked against the code.
- The bug form names the four ways to run a server, asks for the version as a release names it, and takes reports in
  English or Korean.

## [0.1.2] - 2026-11-07

### Added

- The Quick start says what the server's computer, its disk and the phones need, and what it was tested on.

### Fixed

- Setup, app step: an app already built is said to be ready, and only a new build asks for the game's Android app
  when it is gone.
- Korean pages write no particles in brackets.
- The guides, read through and checked against the code: the zip's folder, the admin sign-in, page and button names,
  and first-time steps that were missing.

## [0.1.1] - 2026-11-07

### Added

- Stop the server from the admin pages: Maintenance, Stop the server. It asks first, then stops every part, and the
  page says how to start it again.
- Setup, first step: type or paste the path of a folder or file (quotes, `%USERPROFILE%`, `~` and `file://` addresses
  work). The folder picker is open from the start at Downloads, with the way there as links. A path with nothing there
  opens the nearest folder above it and says so; a whole drive or home folder is not imported.

### Fixed

- Windows: OpenDMTQ.exe opens one window, its own. Apache's log programs no longer open two empty windows beside it.
- macOS: with `./opendmtq service`, a stop stays a stop; the server starts again by itself only when it fails, as on
  Linux.
- The Windows build falls back to this repository's copy of each tested download when its maker has taken it down.

### Changed

- Setup, address step: in Chrome and Edge 135 and later the list opens in the site's look.
- The Quick start says how to stop the server, and why iPhones cannot play.

## [0.1.0] - 2026-11-06

### Added

- The online side of DJMAX Technika Q on a computer of your own: accounts, scores, the monthly and per-song rankings,
  achievements and the in-game maintenance notice, from OpenDMTQ's own game server.
- The phones' app built from your copy of the game's Android app, pointed at your server, with the runtime for phones
  without 32-bit support; players download it from the server's site.
- A site for players (rankings, songs, profiles, live broadcasts and recordings) and admin pages with a setup in the
  browser.
- Four ways to run it: the Windows bundle, one command on Linux or macOS, Docker Compose, and a Helm chart for
  Kubernetes.

[Unreleased]: https://github.com/kanggu12/openDMTQ/compare/v0.10.0...HEAD
[0.10.0]: https://github.com/kanggu12/openDMTQ/compare/v0.9.6...v0.10.0
[0.9.6]: https://github.com/kanggu12/openDMTQ/compare/v0.9.5...v0.9.6
[0.9.5]: https://github.com/kanggu12/openDMTQ/compare/v0.9.4...v0.9.5
[0.9.4]: https://github.com/kanggu12/openDMTQ/compare/v0.9.3...v0.9.4
[0.9.3]: https://github.com/kanggu12/openDMTQ/compare/v0.9.2...v0.9.3
[0.9.2]: https://github.com/kanggu12/openDMTQ/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/kanggu12/openDMTQ/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/kanggu12/openDMTQ/compare/v0.8.2...v0.9.0
[0.8.2]: https://github.com/kanggu12/openDMTQ/compare/v0.8.1...v0.8.2
[0.8.1]: https://github.com/kanggu12/openDMTQ/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/kanggu12/openDMTQ/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/kanggu12/openDMTQ/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/kanggu12/openDMTQ/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/kanggu12/openDMTQ/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/kanggu12/openDMTQ/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/kanggu12/openDMTQ/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/kanggu12/openDMTQ/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/kanggu12/openDMTQ/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/kanggu12/openDMTQ/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/kanggu12/openDMTQ/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/kanggu12/openDMTQ/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/kanggu12/openDMTQ/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/kanggu12/openDMTQ/releases/tag/v0.1.0
