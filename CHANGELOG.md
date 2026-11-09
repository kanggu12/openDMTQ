# Changelog

What changed in each release of OpenDMTQ. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/): a release that adds something raises the minor number,
one that only fixes raises the patch number. Each release's section here is its release notes.

## [Unreleased]

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
  with its button up, not while a song is played with the mouse. The game holds still while the menu is open, as a
  phone's game does when its owner leaves it, a broadcast with it, and the arrow keys and Enter choose in it. Minimised,
  the game holds still behind the menu, which is there when the game comes back.
- Over the game, the player for Windows shows its own pointer: a dart in the logo's chrome and lime, all lime while the
  button is down, sized for the display's scaling.
- `client.php` on the site answers the PC client: whether the address is an OpenDMTQ server, a sign-in that gives the
  site's cookie, and the app on offer for a signed-in player.
- The PC client for Windows (`OpenDMTQ-Setup.exe`): an installer, and a launcher between the player and the game. It
  connects to a server, signs in, downloads the server's app and keeps it up to date, sets the picture and the sound up
  for the computer before PLAY, and starts the player. It updates itself from the project's releases. Downloaded from a
  server's site, it comes with that server already set; from the releases, it asks for the address on first start.
  Downloaded over HTTPS, it keeps the address with its port, and the server's own certificate authority where the
  server has one, which the launcher trusts for that server alone. The installer and the launcher speak English or
  Korean, as Windows does, and the launcher can be set to either. `OpenDMTQ-cmd.exe` does the same from the command
  line.
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

### Changed

- Alt+F4 and the window's close button open the player's menu instead of ending the game, so that no key pressed by
  mistake ends a song; the menu's Quit ends it.
- The site hands computers the installer for Windows, set up for the server (its address on the installer's end), in
  place of a zip with the player and the app in it. The installer is the same for every server: the builder keeps it
  beside the app (`windows.json`), from the release, from `data/apk`, or fetched from the latest release, and removes
  the zips of 0.6 and 0.7 and what they kept in `data/apk` for their player.
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

[Unreleased]: https://github.com/kanggu12/openDMTQ/compare/v0.8.0...HEAD
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
