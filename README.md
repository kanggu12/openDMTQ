<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg">
    <img alt="OpenDMTQ" src="docs/images/logo-light.svg" width="400">
  </picture>
</p>

<p align="center">
  <b>An open-source server for DJMAX Technika Q, on your own computer.</b><br>
  Logins, scores, rankings and live broadcasts, with nothing to set on a phone.
</p>

<p align="center">
  <a href="https://github.com/kanggu12/openDMTQ/actions/workflows/ci.yml"><img src="https://github.com/kanggu12/openDMTQ/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/kanggu12/openDMTQ/releases/latest"><img src="https://img.shields.io/badge/download-latest%20release-8cf23d" alt="Download the latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-8cf23d" alt="License: MIT"></a>
  <a href="#quick-start"><img src="https://img.shields.io/badge/runs%20on-Windows%20%7C%20Linux%20%7C%20macOS-2c343d" alt="Runs on Windows, Linux and macOS"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> &nbsp;|&nbsp;
  <a href="#how-it-works">How it works</a> &nbsp;|&nbsp;
  <a href="#features">Features</a> &nbsp;|&nbsp;
  <a href="#guides">Guides</a> &nbsp;|&nbsp;
  <a href="#contribute">Contribute</a>
</p>

<p align="center">
  <img src="docs/images/game-pc.jpg" alt="The game on a Windows PC through OpenDMTQ's player: notes and the judgment line over the song's blurred video, OpenDMTQ's bar of frosted glass across the top, its FPS counter at 240" width="100%">
  <br><sub>The game on a PC through OpenDMTQ's player, with its glass bar and FPS counter. The song's video is blurred here.</sub>
</p>

The official service of **DJMAX Technika Q**, the Android rhythm game, ended in 2019. OpenDMTQ is an open-source
project that brings its online side back on a computer of your own. The server builds a copy of your APK that talks to
it: phones install that copy from the server's web page, and Windows PCs play the same app through OpenDMTQ's PC client.

> [!IMPORTANT]
> **No game files are included.** You need your own copy of the game's Android app and its client data, and its song
> data for the songs. Please use only files you have the right to use. OpenDMTQ is an unofficial, non-commercial
> project, not affiliated with or endorsed by NEOWIZ.

| Play | Host a server | Contribute |
| :--- | :--- | :--- |
| Phones install the app from your server's page, 64-bit-only ones too; Windows PCs, the [PC client](docs/windows-player.md). | Your own copy of the game's files, then one download or one command. [Quick start](#quick-start) | No game files needed: the tests make their own. [Where to start](#contribute) |

## How it works

<p align="center">
  <img src="docs/images/diagram-architecture.svg" alt="How OpenDMTQ fits together: phones, PCs and browsers reach the server's one port, which sends each path to the game server, the game's files, live broadcasts, the players' site or the admin pages; the setup imports your game files and the app builder patches your APK" width="100%">
</p>

The app sends the game's four official hosts to one address, where a single server answers the game, its login, its
downloads and the website. The game server is OpenDMTQ's own code ([architecture](docs/architecture.md)). Accounts,
scores and recordings stay in `data/` on your computer ([privacy](docs/faq.md#privacy)).

## Quick start

You need your own copy of the game's Android app (`.apk`) and its client data, and its song data for the songs:
[what each has to be](docs/game-files.md).
Phones play on Android, on the same Wi-Fi as the server or [over the internet](docs/internet.md);
[iPhones cannot](docs/game-files.md#iphones). The setup says what each file is before it imports anything.

<p align="center">
  <img src="docs/images/setup.jpg" alt="The setup in the browser: the game's Android app, the client data and the song data found in Downloads, each labeled with what it is, with a button to import them" width="100%">
</p>

**Windows 10 or 11**, in Windows PowerShell:

```powershell
cd ~
curl.exe -LO https://github.com/kanggu12/openDMTQ/releases/latest/download/OpenDMTQ-windows.zip
tar.exe -xf OpenDMTQ-windows.zip
start .\OpenDMTQ\OpenDMTQ.exe
```

The server runs while its window is open. When Windows Firewall asks, allow it on private networks, and set your Wi-Fi
to Private if it is public.

**Debian, Ubuntu or macOS (Homebrew):**

```sh
curl -fsSL https://raw.githubusercontent.com/kanggu12/openDMTQ/main/host/get.sh | sh
```

**Docker:**

```sh
git clone https://github.com/kanggu12/openDMTQ.git
cd openDMTQ
./opendmtq setup
```

**Kubernetes:** the Helm chart, with a volume for the game files and S3 storage:
[install on a cluster](docs/kubernetes.md#install-on-a-cluster).

In the browser on Windows, Linux and macOS, the setup takes you through your files, the address, the players' accounts
and the app. With Docker it runs in the terminal, and the accounts are made on the admin pages, under **Accounts**. On
each Android phone, open the address the setup shows, sign in and install the app; on a Windows PC, download the
installer from the same page.

[Installing, step by step](docs/install.md).

### What it runs on

| | Minimum | Recommended |
| :--- | :--- | :--- |
| **Server** | 64-bit Windows 10 or 11, Debian 12, Ubuntu 24.04, macOS, or Docker; 2 GB of memory | 2 cores, 4 GB |
| **Disk** | 1 GB without the songs | 7 GB with every song |
| **Phones** | Android 5.0 | Android 8 or newer to broadcast |
| **PCs** | The PC client: 64-bit Windows 10 or 11 on an x64 processor (Intel or AMD), Direct3D 11, 390 MB of disk | A touch screen, for several fingers at once |

## Features

- **Nothing to set on a phone.** No hosts file, proxy app or certificate: one app from the server's page.
- **The game's online side.** Accounts, scores, the monthly and per-song rankings, achievements and the maintenance
  notice.
- **Your own songs.** Add songs as packages or hide others; phones get what changed at their next start.
- **Admin pages and an API.** A setup in the browser, the app, songs, players, accounts, broadcasts and their
  recordings, backups; all of it as JSON too ([the API](docs/api.md)).
- **No internet needed** once the files are in ([without internet](docs/closed-network.md)).

### On a PC too

The site offers an installer for Windows set up for the server. Its launcher signs in and keeps the game up to date;
its player runs the game through OpenDMTQ's runtime on Direct3D 11, each frame on a refresh of the display (240 a
second at 240 Hz, none late in 480), with AMD FSR 1 or NVIDIA NIS upscaling, CMAA 2 or SMAA, and a bar of frosted glass
that slides down from the top edge ([the PC client](docs/windows-player.md)).

<p align="center">
  <img src="docs/images/overlay-bar.webp" alt="The handle at the game's top centre lights, and the bar of frosted glass slides down with minimise, full screen and the X, then back up" width="100%">
</p>

<p align="center">
  <img src="docs/images/client-play.png" alt="The launcher's PLAY page: the server and the sign-in, the ready check, how to play, the last game, and PLAY" width="100%">
</p>

<p align="center">
  <img src="docs/images/fig-picture-passes.svg" alt="The game's close button from a run for each setting, enlarged: steps without anti-aliasing, smoothed by SMAA and CMAA 2, upscaled by AMD FSR 1 from 67 %" width="100%">
</p>

### Newer phones too

The game has only 32-bit code, which newer phones (Pixel 7 and later, Galaxy S24 and later) cannot install. OpenDMTQ
puts its own runtime in the app: it translates the game's code as it runs, and keeps the panel's full refresh rate.

<p align="center">
  <img src="docs/images/chart-phones.svg" alt="A 32-bit game at 120 frames a second on a Galaxy S26 Ultra, a phone with no 32-bit support: 1.4 of each frame's 8.3 milliseconds at work, and no frame late, with or without a live broadcast" width="100%">
</p>

### A site for players

Rankings, songs, profiles, and live broadcasts of players in a song with their recordings (off until you turn them
on), in English and Korean; and the admin pages beside it.

<p align="center">
  <img src="docs/images/screens.webp" alt="The site's home page, rankings and live page, and the admin pages' App page, with made-up players and songs" width="100%">
</p>

### Fast on little hardware

Plain PHP on SQLite, with no database server to look after. Two cores answer hundreds of the game's requests a second
([how it was measured](docs/testing.md#measurements)).

<p align="center">
  <img src="docs/images/chart-requests.svg" alt="The game's requests on two cores with eight phones and a million plays: half of the answers within 2.4 milliseconds for a sign-in, 2.5 for every chart's ranking, 6.8 for one song's, 8.5 for the song list and 18.3 for saving a play" width="100%">
</p>

## Guides

| Guide | What it covers |
|---|---|
| [Installing](docs/install.md) | Each system step by step, the phones and PCs, everyday use, updates and backups, what it runs on |
| [The game's files](docs/game-files.md) | What the app, the client data and the song data have to be |
| [Questions and answers](docs/faq.md) | What it needs, which phones, players outside the home, privacy |
| [The site and the admin pages](docs/admin.md) | The setup, the app, songs, players, backups |
| [The API](docs/api.md) | All the admin pages show and do, and what the players' site shows, as JSON |
| [The PC client](docs/windows-player.md) | Playing on a Windows PC: the installer, the launcher, the picture and the sound |
| [Songs](docs/songs.md) | Importing songs, adding your own |
| [Playing from outside your home](docs/internet.md) | A host name, one forwarded port, HTTPS |
| [Live broadcasts](docs/live.md) | Watching players in a song, recordings |
| [Kubernetes](docs/kubernetes.md) | The Helm chart, failover, backups to S3 |
| [Without internet](docs/closed-network.md) | A server and phones on a closed network |
| [Troubleshooting](docs/troubleshooting.md) | When something does not work |
| [Architecture](docs/architecture.md) · [Testing](docs/testing.md) | How it is built and checked |

## Contribute

OpenDMTQ is MIT licensed and built in the open: its own game server, site, app patcher, runtime and PC client, with
every change checked by the tests in this repository before it reaches a server.

- **Report a bug or ask for a feature** in [Issues](https://github.com/kanggu12/openDMTQ/issues/new/choose).
- **Change the code.** None of the game's files are needed: the tests make stand-ins of their own.
  [CONTRIBUTING.md](CONTRIBUTING.md) has each part, its code and its tests; [the architecture](docs/architecture.md),
  how they work together.
- **See what changed** in [CHANGELOG.md](CHANGELOG.md), and report security problems through
  [SECURITY.md](.github/SECURITY.md).

## Credits and license

Earlier DMTQ servers showed what the game asks for. The web pages follow the look of the DJMAX Technika "Platinum Crew"
site with original artwork and fonts cut down from Saira and Pretendard; live video plays with hls.js; the runtime is
built on Dynarmic.

OpenDMTQ's own code and documentation are under the MIT License ([LICENSE](LICENSE)); the parts it brings with it are
listed in [the notice](docs/notice.md#license). The license does not cover the game or its files, which are not in this
repository. DJMAX and TECHNIKA Q are trademarks of NEOWIZ. If a rights holder asks through the issues, the repository
will promptly be made private or taken down, in whole or in part ([notice](docs/notice.md)).
