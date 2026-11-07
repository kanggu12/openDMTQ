# The game's files

OpenDMTQ ships none of the game's files: you need your own copy of the game's Android app and of its server files.
This page says what each has to be, the forms the import takes, and how to check your files before you import them.
Please use only files you have the right to use.

| | Needed | What it gives |
|---|---|---|
| [The Android app](#the-android-app) | Yes | Every phone's app is built from it |
| [The game data](#the-server-files): the server files' `patch/phone_new` | Yes | The game's tables, the images of its screens, its fonts, every song's preview and tile (about 120 MB) |
| [The songs](#the-songs-on-their-own): the server files' `DMQ`, with `viewImg` | No | Music, charts and jackets (4.5 GB); without them the song list is empty |

## The Android app

The game's Android client as an APK, under any file name. These work:

- **The original**, as released, or a copy someone signed again.
- **A copy changed for another server.** The build points every address of that server at yours, in the game's code and
  in its platform SDK, and keeps whatever else was changed for that server. The setup and the import name the server it
  was changed for.
- **Inside something else**: a `.zip`, `.7z` or `.rar`, or an APK bundle (`.xapk`, `.apks`). The import takes the app
  out and leaves the bundle's split parts.

OpenDMTQ also tidies a few of the game's screens: no notice at every start, no question before the first download,
the shop opening on its MAX tab, the panel's own resolution, menus kept at full frame rate when left alone. These fixes
fit versions 1.3.5 and 1.3.4, original or changed for another server, and both were played through on an emulator.
Another version plays the same, with those screens as the game had them.

These do not work:

| File | Why |
|---|---|
| The iPhone app (`.ipa`) | The game on the phones here is the Android app ([iPhones](#iphones)) |
| An app OpenDMTQ built (`OpenDMTQ-<address>-v<date>.apk`) | It is set to one server already. Import the client it was built from |
| Any other app | It is not the game |

If the build cannot find a place it has to change in a client (a copy changed in more than its addresses), it stops
before making anything and names the file of the client it could not change.

### iPhones

OpenDMTQ serves Android phones only. The iPhone app cannot be pointed at another server the way the Android app is:

- An `.ipa` from the App Store has its code encrypted for the Apple account that downloaded it. Any change means
  signing the app again, and an iPhone does not open a copy signed again while its code is still encrypted.
- Signing needs an Apple account on a computer for each phone, and with a free account the app stops opening after
  7 days. Players could not install it from the site.

So the setup says what an `.ipa` is and does not import it.

### Several clients

The import keeps every usable client in `data/apk/base`. The app is built from the one the phones' app came from, as
long as it is there: an app made from another version could not be installed over it. Before the first build it takes
the newest version (1.3.5 before 1.3.4); of one version, the original before a changed copy, then one every fix fits,
then the copy imported last. `BASE_APK=<file name>` in `.env` chooses another.

## The server files

The game's files as its server kept them. What counts is the folder of the game's host, under its own name or any
other, and in it the game data and the songs, together or apart:

```text
game host folder/                  any name: what counts is what is inside
    patch/phone_new/<version>/      the game data: its tables, screens and fonts, every song's preview and tile
    DMQ/Songs/<id>/                 the songs: their music and videos
    DMQ/Patterns/                   their charts
    viewImg/                        their jackets (eye), and the pictures of the news
    static/                         the pictures of HOW TO PLAY
_info/songList.json                 a song list beside the folder or in it (optional)
```

A folder of another name counts when it has `patch/phone_new` and `DMQ` or `viewImg` in it. Only the game's data files
are imported. Programs, databases and notes in the same folder or archive are left alone.

The forms the import takes:

| Form | Example |
|---|---|
| A folder, up to four folders below the one you choose | `Downloads/DMTQ/files/<game host folder>` |
| An archive | `server-files.zip`, `.7z`, `.rar` |
| An archive in parts, every part in one folder | `files.7z.001`, `files.part1.rar`, `files.zip.001`, `files.rar` with `files.r00` |
| An archive inside an archive | a `.zip` that holds a `.7z` (one level) |
| The content folder of another OpenDMTQ server | `content/web/...` with `content/songs.json` |
| The game data alone | `patch/phone_new`, `phone_new`, or an archive of either |
| The songs alone | `DMQ` (with `viewImg` and `_info` beside it, or without), or an archive of them |

For an archive in parts, choose its first part, or the folder that holds the parts. When a folder holds the whole
server files and parts of them, the whole files come first. When it holds the game data alone and the songs alone in
two places, each comes from its own.

### The songs on their own

The game data is all the game needs to start: with it alone, the song list is empty. The songs can come in the same
import (**Import the songs too** in the setup, `--songs` on the command line), or later on their own: choose the `DMQ`
folder, or the folder that holds it with `viewImg` for the jackets, in the setup or on the admin pages' **Songs** page.
On the command line:

```sh
./opendmtq import --songs ~/Downloads/DMQ
```

Each part of the files replaces only what it has. The game data alone replaces the server's patch folder; the songs
alone replace the songs, their list, and their jackets when they come with jackets. Files without the songs' folder
(`DMQ`) leave the songs on the server as they are. Songs imported later reach the installed apps at their next start.

If part of what the game needs to start is missing, the setup's lamp turns red (with Docker Compose, `./opendmtq doctor`
names the files): import the game data again.

### The song list

The list is optional. Without one, the import makes it from the game's own tables, for the songs whose music is there,
with the charts whose files are there: the tables of the files given, or for the songs alone those of the game data on
the server. A list that comes with the files (`_info/songList.json` beside the game host's folder or in it, or
`songs.json` beside a content folder) is used as it is.

## Check before you import

**In the setup** every file it finds, and every file in a folder you open, says what it is: the app and its version, a
copy changed for another server and that server, server files and how many songs, the iPhone app, a part of an archive,
an archive that cannot be read. A file of no use cannot be imported.

**On the command line** `./opendmtq import --check <folder>` (`OpenDMTQ.exe import --check <folder>` on Windows) says
the same, one line per file, and imports nothing:

```text
ok   files: the game's server files, 12 songs, no song list (made from the game's own tables)
ok   game.apk: client 1.3.4, original
ok   changed.apk: client 1.3.5, changed for another server (play.example.net): pointed at this one instead
no   game.ipa: the iPhone app: of no use here, the Android app (.apk) is needed
ok   files.7z.002: a part of an archive in parts: read through its first part, all parts in one folder
no   old.zip: 7-Zip cannot read it: damaged, or split in parts with one missing
```

## When the import finds nothing

| It says | What to do |
|---|---|
| `base APK: none found` | No Android app of the game there. Check the file with `--check`; the iPhone app does not work |
| `game files: none found` | No folder with `patch/phone_new` or `DMQ` in it. Choose the folder or archive that has it, or a folder above |
| `the song list needs the game data's tables` | The songs alone came before the game data. Import the game data, then the songs again |
| `7-Zip cannot list it` | The archive is damaged, or a part of it is missing. Put every part in one folder |
| `an app OpenDMTQ built` | Import the client that app was built from |

[Troubleshooting](troubleshooting.md) has what happens after the import: the app's build, the phones, the songs.
