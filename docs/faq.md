# Questions and answers

What people ask first: running a server, playing on one, what leaves your computer, and the project.

## Running a server

**What do I need?**
A computer (Windows, Linux or macOS) and your own copy of the game's Android app and its client data, and its song data
for the songs. Please use only files you have the right to use. OpenDMTQ does not come with any, and does not say where
to get them.
[The game's files](game-files.md) says what each has to be.

**My copy of the app was changed for another server. Does it work?**
Yes. The build points every address of the other server at yours. A version other than 1.3.5 or 1.3.4 plays the same, with
a few of the game's own screens left as they were.

**Will my files work?**
For each file it finds, the setup says what it is and whether it can be used, before importing anything. On the command
line, `./opendmtq import --check <folder>` says the same.

**Do I need to know how to program, or use a command line?**
No. On Windows you paste four lines into PowerShell, and the rest happens in the browser. On Linux or macOS one command
starts the same setup.

**Does the computer have to stay on?**
Only while people play. The server runs while its window is open on Windows, and you can have it start with the computer
([everyday use](install.md#everyday-use)).

**How big a computer does it need?**
Two processor cores and 2 GB of memory; 4 GB leaves room for building the app. At rest the server takes about 170 MB,
and two cores serve hundreds of requests a second ([measured](../README.md#fast-on-little-hardware)). Disk: about 1 GB,
plus the songs. [What it runs on](install.md#what-it-runs-on) has the details and the phones.

**Can friends outside my home play?**
Yes, with a host name and one forwarded port: [Playing from outside your home](internet.md).

**How do I make backups?**
The server makes one a day by itself and keeps the last seven. The **Backups** page makes one at any time, downloads
them and restores them.

**What happens to the data if I update OpenDMTQ?**
Everything of yours is in the `data` folder and the `.env` file, and an update leaves those alone. On Windows, close the
server's window and run the same four lines again; on Linux or macOS, the same command ([installing](install.md)). With
Docker, `git pull`, then `./opendmtq up`; `./opendmtq runtime` also brings the newest runtime for newer phones.

## Playing

**What do my friends have to do?**
Open the address you give them, sign in with the account you made for them, tap **Download app (.apk)** and install it.
Nothing else on the phone changes: no DNS, no proxy, no certificate.

**Which phones work?**
Android 5.0 or newer, phones and tablets. Newer ones without 32-bit support (Pixel 7 and later, Galaxy S24 and later)
work too: the server adds what they need to the app. iPhones do not ([why](game-files.md#iphones)).

**Can I play on a computer?**
On a PC with 64-bit Windows 10 or 11 on an x64 processor (Intel or AMD): the site's Download page has the PC client, an installer set up for the server.
It installs for your Windows account without administrator rights; sign in there with your site ID, and it downloads the
game and keeps it up to date. The PC is a player of its own, apart from your phone, and the game's account transfer
carries a player from one to the other ([the PC client](windows-player.md)).

**Does it need the internet?**
Only to get its programs onto the server. The server's Windows bundle (`OpenDMTQ-windows.zip`) already has them all.
After that the setup, the app's build, the server and the game stay on your network. [Without internet](closed-network.md)
says what to carry in for each way of running it, and why the macOS install cannot run without it.

**Is the app safe to install?**
The app comes from your server, not from a store, so Android asks to allow installs from the browser and Play Protect may
warn about an app it does not know. It is the game's own app, with the server's address in it and the runtime for newer
phones.

**The game shows no songs.**
The song list is empty until the songs are imported: on the admin pages, **Songs**, **Choose the folder**, then the
client data and the song data together, or the `DMQ` folder alone, with **Import the songs too** ticked.

## Privacy

**What leaves my computer?**
Accounts, scores, recordings and backups stay on the server's computer, in `data/`, and phones talk to the server alone.
The server asks the internet for two things, from this repository's latest release: the runtime for newer phones, when
it builds the app without one, and the PC client's installer, when none came with it, then once a week for a newer one
(a release's images and the Windows bundle carry both, and ask for neither). The PC client asks the same releases when
**Check for updates** is pressed, and nothing else on its own. `./opendmtq doctor` on a server reachable from the
internet asks check-host.net to open its page from outside, which tells that site the server's address. The game's own
app, and Android, also look up a few Google and ad addresses; the game plays the same without them
([without internet](closed-network.md)).

## The project

**Is this official?**
No. OpenDMTQ is an unofficial, non-commercial project, not affiliated with or endorsed by NEOWIZ. See
[License and notice](notice.md).

**Does it cost anything?**
No. It is MIT licensed, and everything runs on your own computer.

**Something does not work.**
[Troubleshooting](troubleshooting.md) answers most of it. If not, please [open an
issue](https://github.com/kanggu12/openDMTQ/issues/new/choose), without any of the game's files.

**Can I help?**
Yes: [CONTRIBUTING.md](../CONTRIBUTING.md). You do not need the game's files to work on the code.
