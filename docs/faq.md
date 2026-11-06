# Questions and answers

## Running a server

**What do I need?**
A computer (Windows, Linux or macOS) and your own copy of the game's Android app and its server files. Please use only
files you have the right to use. OpenDMTQ does not come with any, and does not say where to get them.
[The game's files](game-files.md) says what each has to be.

**My copy of the app was changed for another server. Does it work?**
Yes. The app built from it reaches your server: every address of the other one is pointed at yours. A version other
than 1.3.4 plays the same, with a few of the game's own screens left as they were.

**Will my files work?**
The setup says of each file it finds what it is and whether it can be used, before anything is imported. On the command
line, `./opendmtq import --check <folder>` says the same.

**Do I need to know how to program, or use a command line?**
No. On Windows you unzip a folder and double-click a program, and the rest happens in the browser. On Linux or macOS one
command starts the same setup.

**Does the computer have to stay on?**
Only while people play. The server runs while its window is open on Windows, and you can have it start with the computer
([everyday use, in the README](../README.md#on-each-android-phone)).

**How big a computer does it need?**
About 170 MB of memory at rest, and the disk the songs take. Two processor cores serve hundreds of requests a second
([measured](../README.md#fast-on-little-hardware)).

**Can friends outside my home play?**
Yes, with a host name and one forwarded port: [Playing from outside your home](internet.md).

**How do I make backups?**
The server makes one a day by itself and keeps the last seven. The **Backups** page makes one at any time, downloads
them and restores them.

**What happens to the data if I update OpenDMTQ?**
Everything of yours is in the `data` folder and the `.env` file, and an update leaves those alone. On Windows, close the
server's window, then unpack the new zip where you unpacked the first, so that its `OpenDMTQ` folder lands on yours and
replaces the program's files. With the one command on Linux or macOS, run the same command again. With Docker,
`git pull`, then `./opendmtq up`; `./opendmtq runtime` also brings the newest runtime for newer phones.

## Playing

**What do my friends have to do?**
Open the address you give them, sign in with the account you made for them, tap **Download app (.apk)** and install it.
Nothing else on the phone changes: no DNS, no proxy, no certificate.

**Which phones work?**
Android phones and tablets, newer ones without 32-bit support (Pixel 7 and later, Galaxy S24 and later) too: what they need
goes into the app by itself. iPhones do not: the game is the Android app.

**Does it need the internet?**
Only to get its programs onto the server, and the Windows zip already has them all. After that the setup, the app's build, the
server and the game stay on your network. [Without internet](closed-network.md) says what to carry in for each way of running
it, and the one that cannot do without.

**Is the app safe to install?**
The app comes from your server, not from a store, so Android asks to allow installs from the browser and Play Protect may
warn about an app it does not know. It is the game's own app, with the server's address in it and the runtime for newer
phones.

**The game shows no songs.**
The song list is empty until the songs are imported: on the admin pages, **Songs**, **Choose the folder**, with
**Import the songs too** ticked.

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
