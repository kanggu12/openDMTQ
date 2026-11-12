# Changelog

What changed in each release of OpenDMTQ. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/): a release with a new feature raises the minor number,
one of fixes, changes and smaller additions raises the patch number. Each release's section here is its release notes.

## [Unreleased]

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

[Unreleased]: https://github.com/kanggu12/openDMTQ/compare/v0.9.4...HEAD
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
