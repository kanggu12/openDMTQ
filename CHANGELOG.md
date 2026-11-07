# Changelog

What changed in each release of OpenDMTQ. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/): a release that adds something raises the minor number,
one that only fixes raises the patch number. Each release's section here is its release notes.

## [Unreleased]

## [0.2.0] - 2026-11-07

### Added

- Version 1.3.5 of the game gets every fix 1.3.4 gets, as released or changed for another server: no notice at every
  start, no question before the first download, the shop opening on its MAX tab, the panel's own resolution, a menu's
  frame rate kept, a 32-bit screen and textures at full size. Like 1.3.4, it drew at the low resolution on every
  phone.
- With both versions imported, a server's first app is built from 1.3.5, the newer one.
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

[Unreleased]: https://github.com/kanggu12/openDMTQ/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/kanggu12/openDMTQ/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/kanggu12/openDMTQ/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/kanggu12/openDMTQ/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/kanggu12/openDMTQ/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/kanggu12/openDMTQ/releases/tag/v0.1.0
