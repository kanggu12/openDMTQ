# The player for Windows

People can play on a Windows PC as well as on a phone or a tablet. The server makes a player for Windows with its own
app in it, the same app its phones install, and the site offers it next to the app. People download it, unzip it and
start it: nothing is installed, and the game plays against the server as it does on a phone.

## For players

1. On the server's site, sign in and open **Download**. Under **On a computer (Windows)**, choose
   **Download for Windows (.zip)**.
2. Unzip it (right-click, **Extract All**), open the `OpenDMTQ-Player` folder it holds and start `OpenDMTQ-Player.exe`.
   The first start takes a little longer: the player unpacks the app's libraries.
3. If Windows says it protected your PC from an unknown app: **More info**, then **Run anyway**. The player is not
   signed by a publisher Windows knows. Windows 11's Smart App Control, when it is on, blocks unsigned programs, this
   one among them, and has no **Run anyway**.

| Input                    | What it does in the game                                                    |
| :----------------------- | :-------------------------------------------------------------------------- |
| The mouse's left button  | One finger on the screen: tap, hold and drag                                |
| The mouse wheel          | Scrolls what is under the pointer, as a finger's drag; with Shift, across   |
| A touch screen           | Fingers, as many at once as the screen takes, each with the time it saw it  |
| A pen                    | One finger                                                                  |
| Esc                      | The phone's Back key: pauses a song, closes what is open, asks to quit      |
| The keyboard             | Text where the game asks for it (Enter ends it, Esc cancels it), Hangul too |
| The touch keyboard       | Comes up when a touch opens the game's text, and types into it              |
| F11, or Alt+Enter        | Full screen, and back                                                       |

- **What it needs:** 64-bit Windows 10 or 11 on an x64 PC (Intel or AMD), and a graphics card with Direct3D 11. About
  500 MB of disk to start: the zip is about 120 MB, the folder it unpacks, with the app, about 130 MB, and the app's
  libraries about 40 MB. The game's data takes more with each song it downloads: 111 MB after a first start and one
  song.
- **The window** opens at three quarters of the height of the display it starts on, at 16:9. The game draws at the
  display's own pixels, whatever its scaling, and fills the window while its shape is between 4:3 and 21:9; a window of
  another shape, such as a display turned upright in full screen, has black around the game. Resized, in full screen or
  moved to a display with other scaling, the game draws at the new size.
- **A touch screen** is the player's first input, as a phone's screen is the game's. Windows' own touch feedback stays
  off the game (no circles under the fingers, no square for a press and hold, no right click for it), and in full screen
  a finger that comes in from the screen's edge stays the game's instead of opening Windows' panels. Each touch reaches
  the game as Windows takes it in.
- **The frame rate** is the refresh rate of the display the window is on, 60 Hz, 144 Hz, 240 Hz or another, with a
  refresh of its own for every frame. A PC that does not keep up takes every second refresh (120 frames a second on a
  240 Hz display), then every third, and tries the faster rate again after a while: a song's load holds the frames up
  for some seconds. Moved to another display, the window takes that display's rate.
- **The videos** need Windows' Media Foundation. The N and KN editions of Windows come without it: there, install the
  Media Feature Pack, under Settings, Optional features (in Apps or in System, by the version of Windows). Without it
  the videos are black and silent, and the game goes on.
- **The language** is Windows' display language, among those the game has. LC_ALL, LC_MESSAGES or LANG comes first
  when one is set.
- **Live broadcasts** go out from phones and tablets: the player for Windows has no video encoder and sends none.
- **What it keeps on the PC** is in `%LOCALAPPDATA%\OpenDMTQ`, in a folder named after the app's package: the app's
  libraries (`lib`), what the game keeps, such as its settings and the songs it downloaded (`data`), and the log. The
  log, `player.log`, starts over past 8 MB and keeps the part before as `player.log.1`: 16 MB at most. Scores are kept
  on the server.
- **The account:** a PC is a player of its own, apart from the same person's phone. The server gives each new device a
  new account, and the device id the PC goes by is kept in that folder: deleting the folder makes this PC a new player.
  The game's own account transfer carries a player to another device: on the device that has the player, **OPTION**,
  **CONNECT ACCOUNT** shows a code; on the other, **OPTION**, **RESTORE DATA** takes it, and that device then plays as
  the same player, with its records.
- **When the server builds its app again** (a new address, an update of the server), the site offers a new player with
  it. Download it again and put its `OpenDMTQ-Player` folder in place of the old one. What the game keeps in
  `%LOCALAPPDATA%` stays.

## For server owners

Nothing to do, unless the server has no internet (below). A release ships the player without an app. The app builder
adds the server's app to it and puts the zip next to the app in `data/apk/out`, under the app's name with
`-windows.zip` at the end (`OpenDMTQ-<address>-v<date>-windows.zip`), with `windows.json` saying what it holds. It makes
the zip again only when the app or the player changed, or the zip is missing. A build for another address makes none.
The site offers the zip on the Download page, and the App page has it too. The server keeps it as one more file in
`data/apk/out`, about the size of the app.

Where the player comes from:

- **A release's images:** the player is in the tools image. The Helm chart runs it, and Docker Compose does when `.env`
  names a release's images ([without internet](closed-network.md) shows how).
- **Docker Compose from the source:** Compose builds its images from this repository by default (`build:` in
  `compose.yaml`), and those have no player in them. The builder fetches the latest release's into `data/apk`.
- **The Windows bundle:** the player is in it.
- **A host install on Linux or macOS:** the builder fetches the latest release's into `data/apk`.

A copy in `data/apk` gives way to the latest release's once it is a week old, and stays when that fetch fails. After a
fetch that failed, the builder waits a day before it tries again: a server without internet does not wait for an answer
at every start. Without internet, put the release's `opendmtq-player-windows.zip` in `data/apk`
([without internet](closed-network.md)).

Without a player the site shows no Windows button, and everything else works as before.

## How it works

The player runs the game's own 32-bit Android code, as the app does on phones that cannot run 32-bit apps: the
[arm32 runtime](../arm32/README.md) translates the game's ARM code (Dynarmic), and a small layer gives it Linux's system
calls on Windows. In place of Android's Java side, the player has its own stand-in for the classes the game calls. The
game draws with OpenGL ES, which ANGLE runs on Direct3D 11; its sound goes out through WASAPI at the device's own rate,
and its videos are decoded by Media Foundation.

## When something goes wrong

- **"The game could not start":** the message box gives the reason and where the log is, `player.log` in the app's
  folder in `%LOCALAPPDATA%\OpenDMTQ`.
- **It closes at once, or nothing shows:** `player.log` says why.
- **"player.conf is not beside the player", or "The app is not beside the player":** the zip was not unpacked whole.
  Unzip it again with **Extract All**, and start the player from its `OpenDMTQ-Player` folder.
- **Windows blocks it with no Run anyway:** Smart App Control is on (step 3 above).
- **The videos are black and silent:** see the Media Feature Pack above.
- **It cannot reach the server:** the PC has to reach the server's address, as a phone does: on the same network, or
  over the internet when the server is set up for it ([playing from outside your home](internet.md)).
