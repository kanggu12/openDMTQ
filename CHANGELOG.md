# Changelog

What changed in each release of OpenDMTQ. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/): a release that adds something raises the minor number,
one that only fixes raises the patch number. Each release's section here is its release notes.

## [Unreleased]

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

[Unreleased]: https://github.com/kanggu12/openDMTQ/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/kanggu12/openDMTQ/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/kanggu12/openDMTQ/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/kanggu12/openDMTQ/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/kanggu12/openDMTQ/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/kanggu12/openDMTQ/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/kanggu12/openDMTQ/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/kanggu12/openDMTQ/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/kanggu12/openDMTQ/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/kanggu12/openDMTQ/releases/tag/v0.1.0
