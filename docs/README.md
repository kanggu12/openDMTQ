<p align="center">
  <img src="images/diagram-architecture.svg" alt="How OpenDMTQ fits together: phones, PCs and browsers reach the server's one public port, where site.conf sends each path to the game server, the game's files, live broadcasts, the players' site or the admin pages, which keep their data in data/. The setup imports the owner's game files, and the app builder patches the owner's APK for this server" width="100%">
</p>

# Guides

OpenDMTQ is a server, which its owner runs, and the clients its players play on: the Android app the server builds,
and the PC client for Windows. Each has its own guides below. New here? The [README](../README.md#quick-start) has the
quick start for each way to run a server, and [Questions and answers](faq.md) covers what people ask first.

<a id="playing"></a>

## For players

| Guide | For |
| :--- | :--- |
| [Playing on a server](play.md) | Players: the app from the server's site on an Android phone or tablet, signing in, updates, broadcasting, which devices, what to tell the server's owner |
| [The PC client](windows-player.md) | Playing on a Windows PC: the installer from the site, the launcher, the controls and the bar over the game, the picture and the sound settings, broadcasting, what it needs and keeps |
| [Troubleshooting for players](troubleshooting.md#for-players) | What a phone or a PC can check when the site, the app or the game does not work |

<a id="running-a-server"></a>

## For server owners

| Guide | For |
| :--- | :--- |
| [Installing](install.md) | Each system step by step, the players' accounts, everyday use, updates, backups and moving to another computer, the `.env` settings, what it runs on |
| [The game's files](game-files.md) | What your APK, client data and song data have to be, the forms they come in, how to check them |
| [The site and the admin pages](admin.md) | The setup in the browser, the players' site, building the app, players, accounts, recordings, backups, the maintenance notice, the PC client's installer |
| [Songs](songs.md) | Importing the songs, hiding them, adding your own as song packages |
| [Playing from outside your home](internet.md) | A host name, one forwarded port, HTTPS |
| [Live broadcasts](live.md) | Turning broadcasts on for the server and its players, recordings, their limits |
| [Kubernetes](kubernetes.md) | The Helm chart, failover, the database replica |
| [Without internet](closed-network.md) | A server and phones on a network with no way out: what to carry in for each way of running it |
| [The API](api.md) | All the admin pages show and do, and what the players' site shows, as JSON |
| [Troubleshooting](troubleshooting.md#for-server-owners) | When a phone cannot connect, the app does not install or build, or the server does not start |
| [Questions and answers](faq.md) | What it needs, which phones, playing from outside your home, what leaves your computer |
| [License and notice](notice.md) | What the project is, its license, the third-party parts |

<a id="working-on-the-code"></a>

## For contributors

| Guide | For |
| :--- | :--- |
| [Architecture](architecture.md) | How the parts fit together: the server, the game server's code, the content, the app patch, the database |
| [Testing](testing.md) | What runs before a change reaches a server, and how to run it |
| [Test cases](test-cases.md) | Every case, one table per area, with what checks it |
| [The arm32 runtime](../arm32/README.md) | How the 32-bit game runs on phones without 32-bit support |
