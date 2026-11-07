<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg">
    <img alt="OpenDMTQ" src="docs/images/logo-light.svg" width="400">
  </picture>
</p>

<p align="center">
  <b>An open-source server for DJMAX Technika Q, on your own computer.</b><br>
  Logins, scores, rankings and live broadcasts for you and your friends, with nothing to set on a phone.
</p>

<p align="center">
  <a href="https://github.com/kanggu12/openDMTQ/actions/workflows/ci.yml"><img src="https://github.com/kanggu12/openDMTQ/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/kanggu12/openDMTQ/releases/latest"><img src="https://img.shields.io/badge/download-latest%20release-8cf23d" alt="Download the latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-8cf23d" alt="License: MIT"></a>
  <a href="#quick-start"><img src="https://img.shields.io/badge/runs%20on-Windows%20%7C%20Linux%20%7C%20macOS-2c343d" alt="Runs on Windows, Linux and macOS"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> &nbsp;|&nbsp;
  <a href="#features">Features</a> &nbsp;|&nbsp;
  <a href="#guides">Guides</a> &nbsp;|&nbsp;
  <a href="#open-source">Open source</a>
</p>

<p align="center">
  <img src="docs/images/screens.png" alt="The site's home page, rankings, live view and admin pages, with made-up players" width="100%">
</p>

The official service of **DJMAX Technika Q**, the Android rhythm game, ended in 2019. OpenDMTQ is an open-source
project that brings its online side back on a computer of your own. The server builds a copy of your APK that talks to
it, and your friends install that copy from the server's web page.

> [!IMPORTANT]
> **No game files are included.** You need your own copy of the game's Android app and its server files. Please use
> only files you have the right to use. OpenDMTQ is an unofficial, non-commercial project, not affiliated with or
> endorsed by NEOWIZ.

## Quick start

| Your computer | What to do |
|---|---|
| **Windows 10 or 11** | [Download, unzip, double-click](#windows). Nothing to install. |
| **Debian, Ubuntu or macOS** | [One command](#linux-or-macos) |
| **Docker** | [`./opendmtq setup`](#with-docker) |
| **Kubernetes** | [`helm install`](#kubernetes) |

All four run the same server. Phones join over the same Wi-Fi, or over the internet once the server is
[reachable from outside](docs/internet.md).

### What you need

- **The game's Android app** (`.apk`, any file name). Version 1.3.5 or 1.3.4, original or changed for another server,
  gets every fix; other versions play the same, with a few screens as the game had them. It may be in an archive,
  an `.xapk` or an `.apks`. Phones play on Android; [iPhones cannot](docs/game-files.md#iphones).
- **The game's server files**: a folder or an archive (`.zip`, `.7z`, `.rar`, also in parts) with the game's
  `patch/phone_new` folder in it. The songs in them are optional.

The setup says what each file is before it imports anything. [The game's files](docs/game-files.md) has every form it
accepts.

<p align="center">
  <img src="docs/images/setup.jpg" alt="The setup in the browser: the game's Android app and the server files found in Downloads, each labeled with what it is, with a button to import them" width="100%">
</p>

### Windows

1. Download `OpenDMTQ-windows.zip` from [Releases](https://github.com/kanggu12/openDMTQ/releases/latest) and unpack
   it outside OneDrive and Program Files, for example to `C:\OpenDMTQ`.
2. Start `OpenDMTQ.exe`. If Windows says it protected your PC, click **More info**, then **Run anyway**.
3. The setup opens in your browser. It finds your files in Downloads, on the Desktop or in Documents, or takes the path
   you paste. It then asks for the address phones use and an account for each player, and builds the app.
4. Allow Apache on private networks when Windows asks. If your Wi-Fi is a public network, set it to **Private** in
   Settings, or phones cannot connect.

The server runs while its window is open. To stop it, close the window, or press **Stop the server** under
**Maintenance** on the admin pages.

<details>
<summary>Checking the download</summary>

Each release has `OpenDMTQ-windows.zip.sha256` beside the zip. In PowerShell, compare
`Get-FileHash OpenDMTQ-windows.zip` with it; on Linux, run `sha256sum -c OpenDMTQ-windows.zip.sha256`.
</details>

### Linux or macOS

```sh
curl -fsSL https://raw.githubusercontent.com/kanggu12/openDMTQ/main/host/get.sh | sh
```

For Debian, Ubuntu, or a Mac with [Homebrew](https://brew.sh). It downloads OpenDMTQ into `~/openDMTQ`, installs
Apache, PHP, Java and Python from the system's packages, starts the server and opens the same setup in the browser.
It asks for your password (sudo) to install packages; without a screen it prints the setup's address instead. Running
it again updates OpenDMTQ. Its commands run in that folder, for example `./opendmtq status`. On another Linux, use
Docker.

### With Docker

Docker 23 or newer with Compose, and Python 3.9 or newer:

```sh
git clone https://github.com/kanggu12/openDMTQ.git && cd openDMTQ
./opendmtq setup
```

It finds the game files in Downloads or on the Desktop by a name with `dmtq`, `djmax` or `technika` in it (any other
name or place: `--from <folder>`), starts the server, builds the app, checks it all and ends with a QR code for phones.
Sign in to the admin pages as `admin` with `ADMIN_PASSWORD` from `.env`, and make an account for each player.

### Kubernetes

```sh
helm install opendmtq oci://ghcr.io/kanggu12/charts/opendmtq --set publicHost=game.example.com:8790
```

The game files go on the chart's volume first: see [Kubernetes](docs/kubernetes.md).

### On each Android phone

Each player needs an account: make them in the setup, or later on the admin pages' **Accounts** page.

1. In Chrome or Samsung Internet, open the server's address exactly as the setup shows it, or scan its QR code. Not
   inside a messenger app.
2. Sign in with the player's account, tap **Download app (.apk)** and install it. Allow installs from the browser when
   Android asks.
3. Start the game and allow storage access. It downloads its data from the server on the first start.

<details>
<summary>Everyday use</summary>

| To | Windows | Linux or macOS | Docker |
|---|---|---|---|
| Start | `OpenDMTQ.exe` | `./opendmtq start` | `./opendmtq up` |
| Stop | close the window | `./opendmtq stop` | `./opendmtq down` |
| See the address | the window shows it | `./opendmtq status` | `./opendmtq status` |
| Start with the computer | a shortcut in `shell:startup` | `./opendmtq service` | `RESTART=unless-stopped` in `.env` |
| Import songs | admin pages, **Songs** | admin pages, **Songs** | `./opendmtq import --songs <folder>` |

Everything else is on the admin pages: the app, songs, players, accounts, recordings and backups.
</details>

### What it runs on

| | Minimum | Recommended |
|---|---|---|
| **Server** | 64-bit Windows 10 or 11, Debian 12, Ubuntu 24.04, macOS, or Docker; 2 GB of memory | 2 cores, 4 GB |
| **Disk** | 1 GB without the songs | 7 GB with every song |
| **Phones** | Android 5.0 | Android 8 or newer to broadcast |

<details>
<summary>Measured sizes, and what it was tested on</summary>

At rest the server takes about 170 MB of memory, and up to 1.6 GB for half a minute while it builds the app. The game's
files take about 60 MB without the songs and 4.5 GB with them; each app build about 110 MB, the last ten kept. Broadcast
recordings take up to 20 GB more.

Tested on Windows Server 2022 and Wine, Debian 12, Ubuntu 24.04, Docker on Linux and a three-node Kubernetes cluster,
with a Galaxy S26 Ultra (Android 17, no 32-bit support) and the Android 11 emulator.
</details>

## Features

- **Nothing to set on a phone.** No hosts file, proxy app or certificate: one app from the server's page.
- **The game's online side.** Accounts, scores, the monthly and per-song rankings, achievements and the maintenance
  notice.
- **A site for players.** Rankings, songs, profiles, and live broadcasts of players in a song with their recordings, in
  English and Korean.
- **Admin pages.** A setup in the browser, the app, songs, players, accounts, recordings, backups.
- **Your own songs.** Add songs as packages or hide others; phones get what changed at their next start.
- **Newer phones too.** Phones without 32-bit support run the game through OpenDMTQ's runtime
  ([below](#newer-phones-too)).
- **No internet needed** once the files are in ([without internet](docs/closed-network.md)).

### Newer phones too

The game has only 32-bit code, which newer phones (Pixel 7 and later, Galaxy S24 and later) cannot install. OpenDMTQ
puts its own runtime in the app: it translates the game's code as it runs, and keeps the panel's full refresh rate.

<p align="center">
  <img src="docs/images/chart-phones.svg" alt="A 32-bit game at 120 frames a second on a Galaxy S26 Ultra, a phone with no 32-bit support. Of each frame's 8.3 milliseconds the game's thread works 1.4 and waits 6.9. No frame was late: 0 of 237 per two seconds, with and without a live broadcast. A broadcast takes the processor from 125 percent of one core to 130 to 133 percent" width="100%">
</p>

### Fast on little hardware

Plain PHP on SQLite, with no database server to look after. Two cores answer hundreds of the game's requests a second
([how it was measured](docs/testing.md#measurements)).

<p align="center">
  <img src="docs/images/chart-requests.svg" alt="The game's requests with eight phones at once, on two processor cores and a million saved plays. Half of the answers within: ranking of one song 6.3 milliseconds, sign-in 6.4, the song list 9, saving a play 17.9, ranking of every chart 195.5. Answers a second: 680, 1,199, 799, 410 and 44" width="100%">
</p>

## How it works

<p align="center">
  <img src="docs/images/diagram-pieces.svg" alt="Your APK and server files are imported by the setup into the OpenDMTQ server on your PC. The server answers the game, builds the app from your APK, and serves the players' site, live broadcasts and the admin pages. Phones get the app from the site and play; browsers see rankings and broadcasts; you set it up and run it on the admin pages" width="100%">
</p>

The app sends the game's four official hosts to one address, where a single server answers the game, its login, its
downloads and the website. The game server is OpenDMTQ's own code ([architecture](docs/architecture.md)). Accounts,
scores and recordings stay in `data/` on your computer ([privacy](docs/faq.md#privacy)).

## Guides

| Guide | What it covers |
|---|---|
| [The game's files](docs/game-files.md) | What the app and the server files have to be |
| [Questions and answers](docs/faq.md) | What it needs, which phones, playing with friends, privacy |
| [The site and the admin pages](docs/admin.md) | The setup, the app, songs, players, backups |
| [Songs](docs/songs.md) | Importing songs, adding your own |
| [Playing from outside your home](docs/internet.md) | A host name, one forwarded port, HTTPS |
| [Live broadcasts](docs/live.md) | Watching players in a song, recordings |
| [Kubernetes](docs/kubernetes.md) | The Helm chart, failover, backups to S3 |
| [Without internet](docs/closed-network.md) | A server and phones on a closed network |
| [Troubleshooting](docs/troubleshooting.md) | When something does not work |
| [Architecture](docs/architecture.md) · [Testing](docs/testing.md) | How it is built and checked |

## Open source

OpenDMTQ is MIT licensed and built in the open: its own game server, site, app patcher and runtime, with every change
checked by the tests in this repository before it reaches a server.

- **Report a bug or ask for a feature** in [Issues](https://github.com/kanggu12/openDMTQ/issues/new/choose).
- **Change the code.** None of the game's files are needed: the tests make stand-ins of their own.
  [CONTRIBUTING.md](CONTRIBUTING.md) has a map of the code and how a change goes in.
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
