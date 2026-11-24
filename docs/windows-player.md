# The PC client

For players on a Windows PC, or on Linux under Wine ([below](#on-linux-with-wine)): the PC client is an installer and a
launcher that connects to the server, signs in, downloads the server's app (the same app its phones install) and keeps
it up to date, sets the picture and the sound up for the PC, and starts the game in the player for Windows. The game
then plays against the server as it does on a phone.

<p align="center">
  <img src="images/game-pc-live.jpg" alt="The game on a Windows PC through the player: notes and the judgment line over
  the song's video, blurred in this picture; the bar of frosted glass down across the top with the OpenDMTQ wordmark and
  its buttons, Sound, minimise, full screen and the X; under it the broadcast notice, a red LIVE tag with Broadcasting
  your play, Watch it now or later under LIVE on 192.168.1.10:8791; the FPS counter at 240 at the bottom right"
  width="100%">
</p>

## <a id="for-players"></a>Installing

1. On the server's site, sign in and open **Download**. Under **On a computer (Windows)**, choose **Download the
   installer (.exe)**. The file it gives, `opendmtq-pc-client-<version>-windows-x64-setup-<address>.exe`, is set up for
   that server.
2. Run it: its page says what goes where (the program in your user folder, shortcuts on the desktop and in the Start
   menu, no administrator rights, the server it plays on). Its window has no Windows title bar: its top moves it, and
   its own buttons at the top right minimise it and close it. Choose **Install**: the bar follows the files as they land,
   and the last page says what was done, with **Open OpenDMTQ**. If Windows says it protected your PC from an unknown
   app: **More info**, then **Run anyway**. The installer is not signed by a publisher Windows knows. Windows 11's
   Smart App Control, when it is on, blocks unsigned programs, this one among them, and has no **Run anyway**.
3. The launcher's first start walks through the server (already filled in), the sign-in with your site ID, the app's
   download, the sound and the screen, then the ready check, and **PLAY**. Each step asks its
   question at the top; while **Next** waits, a line under the step says for what.

The installer from the project's [releases](https://github.com/kanggu12/openDMTQ/releases/latest)
(`opendmtq-pc-client-<version>-windows-x64-setup.exe`) is the same program without a server: its first start asks for
the server's address. One launcher keeps several servers, each with its own sign-in and app, and plays on the one
chosen on the **Online** page.

Run again on a PC that has OpenDMTQ, either installer offers what to do with it: **Open OpenDMTQ**, **Repair** (every
file of the program put back as it came), **Update** when the installer is newer (or going back to its older version),
and **Uninstall**. While the game is open, repairing, updating and uninstalling wait for it to close and then go on.
With `--silent` it installs or updates with no window and starts the launcher (`--no-start` leaves it closed); while a
game runs it installs nothing and ends with 3.

### On Linux, with Wine

The launcher and the player are Windows programs, and on Linux they run under Wine. The project's tests run them so for
every release, with Wine 11 from WineHQ's stable packages on Debian 12: the installer from the server's site, the first
start, the game to its menu with its bar, **Repair**, **Clear game data** and uninstalling, drawn by Mesa on the
processor and, under WSL, on a graphics card.

1. Install Wine from WineHQ's `winehq-stable` package, and GStreamer's decoders, which Wine plays the songs' videos and
   their sound with. On Debian or Ubuntu:

   ```sh
   sudo apt install gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav
   ```

2. Download the installer from the server's site as above, and run it with Wine. The launcher opens as on Windows:

   ```sh
   wine ~/Downloads/opendmtq-pc-client-*-windows-x64-setup-*.exe
   ```

Not tried yet: a Linux desktop's own graphics driver and sound, touch screens, and the Steam Deck.

## The launcher

![The launcher's PLAY page signed in as sena on 192.168.1.10:8791: the server's address at its head with the signed-in player and My page on the site, the ready check and the last game side by side, My records under them, and PLAY](images/client-play.png)

| Page | What it has |
| :--- | :--- |
| **Play** | The server and the account with **My page on the site**, the checks before a start (the player, the server, the sign-in, the app), one that is not fine with a link to the page that sees to it (a server that does not answer, to its connection test), the last play, **My records** under them, and **PLAY** |
| **Screen** | Full screen or a window, the window's size, VSync, the frame limit, the FPS counter and its position, the render scale and its upscaler, anti-aliasing ([the picture](#the-picture)) |
| **Sound** | The master, music and effects volumes, the equaliser (a preset or three bands), the device, **Shared** or **Exclusive**, the buffer, and how the last game's sound went ([the sound](#the-sound)) |
| **Controls** | Keyboard play: on or off, and the keys of each lane of 2, 3 and 4 LINE ([keyboard play](#keyboard-play)); what the touch screen, the mouse and the keyboard do is under [in the game](#in-the-game) |
| **Online** | The servers, the [connection test](#testing-the-connection), the sign-in, the app on this PC and a check for a newer one |
| **Help** | The checks, the game's log and the launcher's, [a report](#a-report-for-whoever-helps) to send, and repairing, clearing the game's data, starting over and uninstalling |
| **Launcher** | The language, the launcher's [updates](#updates), the first-start guide again |

The pages are in a column down the window's left, under the wordmark and the launcher's version; the status line and
**PLAY** are at the column's foot, and the first-start guide shows its six steps down the same column with **Back** and
**Next** under them. Pages move by the wheel, Page Up and Page Down, or a finger dragged on them. The sign-in names the
ID and the password over their fields, shows the password on **Show** (by the keyboard too), says what is wrong under
the field it is about, keeps the ID for the next time, and signs in on Enter.

### PLAY and your records

**PLAY** asks the server for a newer app first and downloads it when there is one; when the server cannot be asked, the
game starts with the app this PC has. The checks ask the server too: one that does not answer is said on the **Play**
and **Help** pages and does not stop **PLAY**. Every minute while it is on screen, the launcher asks the server again:
one that stops answering, a sign-in the server no longer takes, and a newer app are said as they come, each time they
do. While the game runs the launcher steps aside, and comes back when
the game ends.

Signed in, **My page on the site** on the **Play** page's server card opens your MY PAGE on the server's site in the
PC's browser, signed in already: the server makes a link for the launcher's sign-in that signs the browser in to the
same account once, within a minute. **My records**, under the page's columns, lists your three latest plays and three
best records from the server, each with the song, the chart, when, the score (with the keyboard's mark before it when a
keyboard played it) and the place on that chart (#2 of 5); it is asked for when the page shows and again after a game.
An account the server's owner has not linked to a game player says so instead, and signed out the card is not there.
The first **PLAY** links an account that has no player to this PC's game player, when that player has no account
either, and the bottom line says so once.

![My records, the PLAY page's last card: three recent plays and three best records, each with its song, chart and when, the score with the keyboard's mark before those a keyboard played, and the place on the chart; at its top right what the keyboard's mark means](images/client-records.png)

### <a id="testing-the-connection"></a>Testing the connection

**Test connection**, at the top of the **Online** page's server card (and the **Play** page's Server row while the
server does not answer), follows the way from this PC to the server a step at a time, in a card that fills in as each
step ends, with what it found and how long it took, under a line that says how it went; **Copy** puts the whole result
on the clipboard:

| Step | What it looks at |
| :--- | :--- |
| Address | The address as the launcher reads it: its scheme, host and port |
| Name lookup | The host's name, and the addresses it leads to |
| Port | A connection to the port: taken, refused, no answer within 5 seconds, or no way from this PC to it |
| OpenDMTQ server | Its answer as an OpenDMTQ server: its name and version, and over HTTPS whether Windows or the server's own authority vouches for its certificate |
| Version | The server's version against the launcher's |
| Sign-in | Whether the server still takes the launcher's sign-in (asked with it, no password) |
| Game server | The game server's own answers: its patch, and the owner's maintenance notice as the game asks for it at its start; or what keeps it from serving the game (no client data, no database or one it cannot write, no address of its own) |
| Broadcasts | The broadcast state the player asks for between songs |
| Downloads | The app and the client data's list of files, by their headers alone: nothing is downloaded |
| Round trip | Five small asks: the time in the middle, the fastest and the slowest |

![The connection test of 192.168.1.10:8791 on the Online page, every step passed: address, name lookup, port, the OpenDMTQ server and its version, sign-in, game server, broadcasts, downloads and round trip, each with its time, with Copy at the card's top](images/client-test.png)

A step after one that did not get through says it was not tried. When nothing answers on the address's port, or
another program answers there (a web server that took the port, or one with a certificate this PC does not trust), the
test also asks the same host on 8791 and the ports a new server takes when that one is taken (to 8799), over HTTPS
with the server's own authority the launcher trusts for the old address: an OpenDMTQ server found there is named, with
**Use this address**, which plays on it from then on with the sign-in and that authority kept
([a server that moved](install.md#the-servers-port)). The test changes nothing else, and its last result goes into the
report. `OpenDMTQ-cmd.exe --test-server` runs the same test on the command line.

### <a id="a-report-for-whoever-helps"></a>A report for whoever helps

**Help**, **Save a report** puts one zip in the Downloads folder (`opendmtq-report-<date>-<time>.zip`) and shows it
selected in File Explorer: the launcher's logs, the end of the game's log, the settings, the displays, the sound
devices, Windows and the graphics cards, the launcher's and the player's versions, and the last connection test. Left
out of every file, each replaced by a word in angle brackets: the Windows user's name in paths, every site ID, every
server's address and name (also of servers the settings no longer know: one forgotten since, an address typed, the last
test of any address), the sign-in cookies, tokens and keys, this PC's player id, what was typed in the game and the
name a sound device is named after (Windows names a Bluetooth headset as its owner's phone named it). The
window says which of those it found; `about.txt` in the zip lists them with how often.

### Updates

The launcher updates itself and the player: **Launcher**, **Check for updates**. It also looks at each start, in the
background for 10 seconds at most, and again every six hours while it is open: a newer version is said on the
**Launcher** page and in the status line, each with **Update to** that version. Nothing is installed by itself, and
without an answer nothing is said. The installer from the server's **Download** page updates it too, once the server has
a newer one; the servers and the settings stay.

The launcher takes its updates from the server it plays on first, and goes no further than the version that server
hands out. From a server that hands out none it takes the project's releases on GitHub, up to the server's own version,
and with no server GitHub's latest release; a server that does not answer sends it nowhere else. **Check for updates**
says where an update comes from. An update goes in only when the release's checksums carry the OpenDMTQ project's
signature, by the key built into the launcher (`8ead95551a5d5d216dca12de20138465d4cfbcec48ec2b2611c9e49fc47b77d7`,
[a release's files](install.md#a-releases-files)): one that does not is refused, said in words, and the program stays as
it was. How it is fetched and checked: [updates](architecture.md#updates).

### The command line

`OpenDMTQ-cmd.exe`, in `%LOCALAPPDATA%\OpenDMTQ.Client\current`, does the same from the command line: `--status` (exit 0
when PLAY can go; under **Sound** the last game's sound as the Sound page says it; its last line is the launcher's
version, and a newer one when there is), `--test-server [ADDRESS]` (the connection test of the server PLAY plays on
or of ADDRESS, each step as it ends; exit 0 when every step passed, 1 when one failed), `--server URL`, `--use-found`
(Online's **Use this address**: the server moved to the address the last test found it at, its sign-in with it),
`--sign-in ID` (the password from standard input), `--sign-out`, `--app`, `--records` (PLAY's **My records**),
`--my-page` (PLAY's **My page on the site**, in the browser), `--set NAME=VALUE`, `--reset-keys` (the Controls page's
**Reset keys**), `--audio-devices`,
`--language en|ko|system`, `--guide`, `--skip-guide` (the guide's **Skip**: the window opens on its pages), `--servers`
(the servers it knows, as **Online** lists them), `--open-log player|launcher`, `--report FILE` (Help's report, into
FILE, or into a folder under its own name), `--play`, `--update`, `--forget URL`, `--reset`, `--repair`,
`--clear-game-data` and `--uninstall [--delete-data]`, with `--yes` to answer their questions (`--help` lists them all,
in parts).

In a terminal it prints in the launcher's look: a title with the version, each part under its name, names and values in
columns, the ready check's marks and a download's bar in the launcher's colours; piped to a file or a script, the same
lines in plain words. Started with no flag by a double click, it opens the launcher's window and closes the console
Windows opened for it. While the launcher's window is open, the flags that change what it keeps are refused. `--set`
takes the settings of the **Screen**, **Sound** and **Controls** pages; every `--set` of a line is checked before any is
applied, so one the launcher does not take changes none of them:

| Setting | Values (the default first) | On the page |
| :--- | :--- | :--- |
| `display` | `fullscreen`, `window` | Mode |
| `window` | `auto` (fitted to the display), `1280x720`, `1600x900`, `1920x1080`, `2560x1440`, `3840x2160`, or any `WIDTHxHEIGHT` from 480x270 at Windows' scale (720x405 at 150 %) that fits the main display with room for the window's title bar and the taskbar, as the page offers them | Window size |
| `vsync` | `on`, `off` | VSync |
| `fps` | `auto` (the display's rate), `unlimited`, or any whole number from 30 to 1000; the page offers the rates up to the fastest connected display's (160, 165, 180 Hz and others) | Frame limit |
| `show_fps` | `off`, `on` (a corner's name, as `fps_position` takes it, is on in that corner) | FPS counter |
| `fps_position` | `bottom_right` (a song's play field's corner), `top_left` (beside a song's pause button), `top_right`, `bottom_left`: the corner in a song (not shown in the menus); kept while the counter is off | Position, while the counter is on |
| `render_scale` | `100`, `85`, `75`, `67`, `50` | Render scale |
| `upscaler` | `fsr1`, `nis`, `bilinear` | Upscaler, below 100 % |
| `anti_aliasing` | `off`, `cmaa2`, `smaa` | Anti-aliasing |
| `audio_device` | `default` (Windows' default output), or a device's id from `--audio-devices` | Device |
| `audio_mode` | `shared`, `exclusive` | Mode |
| `audio_buffer` | `low`, `normal`, `safe` | Buffer |
| `volume` | `100`, or any number from 0 to 100 | Master |
| `music_volume` | `100`, or any number from 0 to 100, a share of the master | Music |
| `effects_volume` | `100`, or any number from 0 to 100, a share of the master | Effects |
| `eq` | `flat`, `bass`, `vocal`, `treble`, `custom`; a preset sets the three bands | Equaliser's preset |
| `eq_low`, `eq_mid`, `eq_high` | `0`, or any number from -12 to 12 (dB); one set alone makes the equaliser `custom` | Low, Mid, High |
| `keyboard` | `on`, `off` | [Keyboard play](#keyboard-play), on the **Controls** page |
| `keys_2line` | `"F J"`: two lanes from the top separated by spaces, each lane one key or two joined by `/` (`"F/D J/K"`), each key by the name of the key a US layout has at that place: `A` to `Z`, `0` to `9`, `Space`, `Semicolon`, `Quote`, `Comma`, `Period`, `Slash`, `LeftBracket`, `RightBracket`, `Backslash`, `Minus`, `Equals`, `Grave`; a key in two lanes is refused | 2 LINE's keys, on the **Controls** page |
| `keys_3line` | `"D F J"`, or three lanes in the same way | 3 LINE's keys |
| `keys_4line` | `"D F J K"`, or four lanes in the same way | 4 LINE's keys |
| `language` | `system` (Windows' display language), `en`, `ko`: the same as `--language` | Language, on the **Launcher** page; the game and what the player draws over it speak it too |

## In the game

| Input | What it does in the game |
| :--- | :--- |
| A touch screen | Fingers, as many at once as the screen takes, each with the time it saw it |
| The mouse's left button | One finger on the screen: tap, hold and drag |
| The mouse wheel | Scrolls what is under the pointer, as a finger's drag; with Shift, across |
| A pen | One finger |
| Esc | The phone's Back key: closes what is open; in a song it does nothing, and the game's pause button pauses |
| The lane keys, while a song is played | [Keyboard play](#keyboard-play): each lane of the song a key, F J in 2 LINE, D F J in 3 LINE and D F J K in 4 LINE from the top lane, each press where the game judges the lane's next note |
| The keyboard | Text where the game asks for it, the text it opens with taken as selected: the first key types over it, Backspace clears it, an arrow keeps it (Enter ends it, Esc cancels it); Hangul too |
| The touch keyboard | Comes up when a touch opens the game's text, and types into it |
| The pointer resting at the game's top edge, or on the handle at its top centre | The bar: Sound, minimise, full screen, and the X that quits after asking |
| A finger's or a pen's tap on the handle or long press on it or at the top edge; a press drawn down from there by a finger, a pen or the mouse | The bar, following the press as it is pulled and settling down or back up when let go |
| Alt+F4 | Nothing: the bar's X quits |
| Alt alone, F10 | Nothing (no menu mode that would hold the next key) |

<p align="center">
  <img src="images/overlay-bar.webp" alt="The handle at the game's top centre lights under the pointer, and the bar of
  frosted glass slides down out of the game's top edge with the wordmark, Sound, minimise, full screen and the X, stays,
  then slides back up" width="100%">
</p>

### The bar

A PC has no phone's buttons around the game, so a bar of frosted glass comes down across the top of the game:

- **How it comes:** when the pointer rests a moment at the game's very top edge, or on the handle; when a finger or a
  pen taps the handle, or holds still on it or at the top edge for half a second; or when a press of a finger, a pen or
  the mouse is drawn down from there, which pulls the bar out with it. The press that brings the bar never reaches the
  game.
- **In a song** none of this happens unless the game has had no click, touch or held note for a second and a half:
  every tap at the top of a song plays the song at once.
- **By itself** it comes down for 3 seconds when the game's picture first shows and after each switch between a window
  and full screen, so that a player sees where it is.
- **How it goes:** it stays while the pointer is on it and goes up soon after the pointer leaves, so it never sits on
  the game's own controls at the top while they are used.
- **What is on it:** the OpenDMTQ wordmark on its left; on its right **Sound**, **minimise**, **full screen** (or back to
  a window) and the **X** that quits, in the launcher's lime. A finger works every button as the mouse does. Minimise
  holds the game still, and the taskbar brings it back with the bar up.

**The handle** is the game's green line along its top edge at the centre, with a small tab of glass hanging from it and
a chevron pointing down in the tab: the bar comes down from here. With the pointer on it the line and the chevron turn
lime. It is as large as the game's own header leaves room for at its top centre, so it covers none of the game's words or
buttons, and it goes while the bar is down.

### The sound panel

<p align="center">
  <img src="images/game-pc-sound.jpg" alt="The sound panel open under the bar during a song, its Sound button pressed in:
  Master, Music and Effects as sliders at 85, 80 and 90 %, the equaliser's presets, each as wide as its word, with Bass
  chosen, and its Low, Mid and High bands with their frequencies, in decibels, the panel's numbers in a heavier face over
  darker glass; beside the panel, in the room it leaves, the broadcast notice, LIVE, Broadcasting your play; the FPS
  counter at 240 at the bottom right" width="100%">
</p>

The bar's **Sound** button opens a card of glass under the bar at the game's right side: **Master**, **Music** and
**Effects** as sliders of 0 to 100 %, then the **Equaliser**'s presets (Flat, Bass, Vocal, Treble, Custom) and its three
bands, **Low** (120 Hz), **Mid** (1 kHz) and **High** (6 kHz), as sliders of -12 to +12 dB. A slider follows the mouse
or a finger from wherever its row is pressed, and every change is heard at once; moving a band makes the equaliser
Custom from the preset's bands. The launcher's **Sound** page shows what it changes, and the next game keeps it. The bar
stays down while the panel is open; the Sound button again, a press on the game, minimising or the question close it.
A notice shown meanwhile stands beside the panel, and an FPS counter it would cover hides until it closes.
[The sound](#the-sound) says what each control changes.

### Quitting, the window and the pointer

<p align="center">
  <img src="images/game-pc-quit.jpg" alt="The question before quitting, asked mid-song: a card of frosted glass over the
  game, dimmed and blurred behind it, Quit the game? with its line that quitting mid-song loses the song's record, Keep
  playing as the main button, ringed by the keyboard's choice, and Quit the game beside it" width="100%">
</p>

- **Quitting**: the X asks first, in a glass card over the game: **Keep playing**, or **Quit the game**; so a click by
  mistake does not end a song. Left, Right and Tab move the choice, Enter takes it and Esc keeps playing. Asked mid-song,
  a line under the question says that quitting mid-song loses the song's record. The taskbar's Close window asks the
  same. The game holds still while it asks: a song stops where it was, with the game's own pause screen after.
- **The window**: the game has a title bar to move it by and a frame to size it by, dark as the launcher's menu column,
  and no buttons of its own: it is minimised, put in full screen and quit from the bar. A double click on the title bar
  does nothing.
- **The pointer** over the game is a dart in the logo's look, sized for Windows' scale.
- **A touch screen** is the player's first input, as a phone's screen is the game's. Windows' own touch feedback stays
  off the game (no circles under the fingers, no square for a press and hold, no right click for it), and in full screen
  a finger that comes in from the screen's edge stays the game's instead of opening Windows' panels.

How each piece over the game is placed, sized and drawn: [the overlay](architecture.md#the-overlay).

### <a id="keyboard-play"></a>Keyboard play

While a song is played, each of its lanes is a key: **F J** in 2 LINE, **D F J** in 3 LINE and **D F J K** in 4 LINE,
from the top lane down. A key plays its lane wherever the note is along it: the player puts the press at the place the
game judges the lane's next note, and the game judges it as it judges a finger, with its own timing, combo and score.

- **Taps and chain points:** a press each, as the note meets the judgment line.
- **Holds:** the key held down to the hold's end; let go early, the hold breaks, as when a finger lifts.
- **Drags:** the key held down; the press follows the drag's curve.
- **Repeat notes:** a press for each of their points.
- **The keys are places on the keyboard,** named after a US keyboard's keys: on another layout the same places play
  (AZERTY's, a Korean or a Japanese keyboard's). A lane can have two keys, to alternate on quick notes (`S/D F J/K`).
- **Only while a song is played:** in the menus every key is the game's as before, and while the game asks for text (a
  new player's name) the keys type. Every lane key lets go when the window loses the keyboard or is minimised, when the
  song pauses (the game's pause button at its top left) and when the question before quitting comes; a key held
  through that plays again once it is let go and pressed again. Esc stays the Back key, and no other key does anything
  new.
- **The bar** waits while a lane key is down, as it does for a finger on the game.
- **A mark on the site:** a play that a lane key pressed is saved with a mark, which the server keeps with the play; its
  site shows a keyboard beside that play, so that keyboard plays and touch plays are told apart.
- **Off:** `keyboard=off` (the **Controls** page's switch) leaves every key the game's.

The launcher's **Controls** page sets it. **Play with keys** turns it on or off (on at first). While it is on, a table
shows the lanes of 2, 3 and 4 LINE from the top, each with a box for its key and one for a second key: click a box (or
Tab to it and press Enter), then press the key. The key goes in by its place on the keyboard, and is named as the US
layout's key at that place (`Semicolon` for the key right of L), so another layout plays the same places; in grey beside
the name, what the PC's own layout prints there when it says more (`;`, or `Ö` on a German keyboard). A key another
lane, or the same lane, already plays, or one no lane takes (Enter, the arrows, the numpad, Shift, Backspace), is
refused in words under the table, and the box waits for another. Esc keeps the key that was there, Delete removes one
of a lane's two keys, and **Reset keys** puts back F J, D F J and D F J K. A key held down counts once, and while a box
waits a Korean or Japanese input method is off, so that a letter goes in by its place. The game reads the keys at the
next **PLAY**; `--set` sets them too (`keys_3line`, above).

A player that does not find the game's input where it expects it (another version of the game) leaves keyboard play
off, says why in its log, and the game plays by touch as before.

## The picture

![The Screen page on a 2560 by 1600 display that Windows runs at 60 Hz and can run at 180 Hz: VSync on, a 180 fps limit, the FPS counter at the bottom right, a 50 % render scale with AMD FSR 1, and SMAA](images/client-screen.png)

- **Full screen or a window.** Full screen is a borderless window over the whole display, at the display's own pixels
  whatever its scaling. A window opens at three quarters of the display's height at 16:9, or at the size chosen. The
  game fills the window while its shape is between 4:3 and 21:9; a window of another shape, such as a display turned
  upright, has black around the game. A window resized, or switched to full screen and back, has the game lay its
  screens out again for the new shape.
- **VSync on** (the default): each frame goes out on a refresh of the display the window is on, 60 Hz, 144 Hz, 240 Hz or
  another. A PC that is really behind takes every second refresh (120 frames a second on a 240 Hz display), then every
  third, and tries the faster rate again after a while.
- **A panel with a dynamic refresh rate.** Windows 11 runs a laptop's or tablet's panel set to its dynamic refresh rate
  ("Dynamic" in its advanced display settings: 60 Hz, or 120, 160, 165, 180 Hz and so on) at 60 Hz for every program
  that does not ask for more. The player asks Windows for the panel's boost while its window is shown, so the game runs
  at the panel's full rate rather than 60.
- **The frame limit:** the display's rate (the default), a number, or none. The page offers every rate up to the
  highest any connected display runs at, and the line under the display's rows names the rate the main display runs a
  game at, and the others'. With VSync on, a limit that is a whole fraction of the display's rate keeps every frame the
  same length (60 or 120 on a 240 Hz display).
- **VSync off:** frames go out as soon as they are drawn, evenly at the limit, which may be above the display's rate, or
  as fast as the PC draws without one. A little less delay, and the picture may tear.
- **The FPS counter**, off by default, is a small card of the overlay's glass, as the notice is: the frames a second
  and, under them, the mean frame time, over the last second, twice a second. The figure is lime while the frames keep
  the display's rate and white below it or where the display's rate is not known. In a song it stands in its corner,
  clear of the song's own controls: at the bottom right by default; **Position** moves it to another corner. In the
  menus it waits, and it shows again in each song, with keyboard play on or off. It shows from the game's first frame
  and hides while the game holds still, and the broadcast does not show it.
- **The render scale** draws the game at a share of the window's pixels (100 % down to 50 %), stretched to fill it:
  lighter for the graphics card, and softer. 67 % of 1920x1080 is 1280x720, so the game lays itself out as it does at
  full size.
- **The upscaler**, below 100 %: how the smaller picture reaches the window's size. **AMD FSR 1** (FidelityFX Super
  Resolution 1, the default) enlarges it with its edge-adaptive filter and sharpens the result. **NVIDIA NIS** (Image
  Scaling) enlarges in one pass with its edge-adaptive filter. **Bilinear** is the plain stretch of the window's surface.
  FSR 1 and NIS keep the game's words as sharp as at 100 %, where bilinear softens them (0.81 of their sharpness at
  50 %). At 100 % no upscaler is used, and the row is not shown.
- **Anti-aliasing** smooths the jagged edges of the game's shapes. **CMAA 2** (Intel's Conservative Morphological
  Anti-Aliasing 2) keeps text and thin lines sharp; **SMAA** (SMAA 1x, Ultra preset) smooths a little more, the game's
  words 5 % softer. The game's pictures are soft at their own edges already, so either changes little. Off is the
  default: the game's picture as it drew it, at no cost.

How the player paces the frames, how the counter, the upscalers and the anti-aliasing work, and what was measured:
[the picture](architecture.md#the-picture).

## The sound

![The Sound page: the volumes and the output side by side, the output on Windows' default device, Shared, with the Low buffer, and under it the last game's sound: shared with low latency, a 7 ms period, 29 ms out, no gaps; the equaliser under them on Bass, its three bands side by side](images/client-sound.png)

The launcher's **Sound** page and the game's [sound panel](#the-sound-panel) set the same settings: a change in either
is the other's next time it looks.

- **Master**, the volume of the game, 0 to 100. Windows' own volume still applies.
- **Music** and **Effects**, each a share of the master, 0 to 100: the music is a song's background, the game's menu
  music and a song's preview; the effects are the sounds of the notes the player plays, and the menus' and the
  judgement's sounds.
- **The equaliser** on the game's whole sound: Flat (no filter), Bass (+6 dB at the low end), Vocal (+4 dB in the
  middle, -2 at the low end, +1 at the top), Treble (+6 dB at the top), or Custom, its three bands as chosen: a low
  shelf at 120 Hz, a peak at 1 kHz and a high shelf at 6 kHz, each -12 to +12 dB. The sound never clips where it was
  full.
- **The device:** Windows' default output, which the game follows when Windows changes it mid-game, or one chosen.
- **Shared or Exclusive.** Shared plays alongside other programs' sound. Exclusive (WASAPI's exclusive mode) takes the
  device for the game alone and has the least delay; other programs are silent meanwhile, and the sound is shared when
  Windows does not allow it.
- **The buffer:** low, the default (Windows' low-latency mode at the shortest period the device has), normal (20 ms) or
  safe (50 ms). From the game's sound to the device's output, on the device measured: 29 to 36 ms shared with the low
  buffer, 10 ms exclusive ([every mode](architecture.md#the-sound)). Where the notes and their sounds do not meet, the
  game's own calibration in its options moves one against the other; the player adds no offset of its own.
- **Last game's sound**, under the output's choices: how the last game's sound went as the player measured it, how it
  had the device (shared, shared at Windows' shortest period, or exclusive), the device's period, the time from the
  game's sound to the device's output, and the gaps (the device running dry, or the game's own sound falling behind),
  with a lime light when there were none and a yellow ring when there were. `--status` prints the same line.

The game mixes its sound at 44.1 kHz, as on every phone ([how](architecture.md#the-sound)).

## Broadcasting

While broadcasts are on for the server and its owner shows a player live, the player broadcasts from the PC as a phone
does, with Windows' own video and sound encoders, at the quality the owner chose ([live broadcasts](live.md#from-a-pc)).
A glass card slides down every time the broadcast's switches change, the player's own or the server's: on air, off air
(with where to watch the replay, or that there is none when nothing of it was recorded), switched on while the server's
broadcasts are off and the like, as the server words it, each once. In the menus it stands under the game's header, in
a song at the top, clear of the song's controls. The player asks the server every 5 seconds, so a switch flipped in the
admin pages shows within that, or when the song ends for one flipped during a song: the server keeps its notices until
then. On air it wears a red LIVE tag like the game's own tags; once over, its title says so alone, and it says where the
broadcast can be watched. When the server stops answering while the PC broadcasts (three asks in a row, 15 seconds), the
card says the broadcast has stopped, and when the server answers again on air, that it is back. The owner's maintenance
notice comes the same way, between songs, when it begins, at each new message and when it ends. A ban the owner makes
comes within the same 5 seconds, in a song too: "You cannot play on this server" with the owner's reason and the ban's
end, which stays over the game for as long as the ban lasts, under the game's own error at its next request (RETRY tries
again, CLOSE ends the game), and goes when the ban is over, the card then saying that the game can be played again
(RETRY goes on).

## What it needs, and what it keeps

- **What it needs:** 64-bit Windows 10 or 11 on an x64 PC (Intel or AMD), a graphics card with Direct3D 11 and about
  1 GB of free memory for the game, which takes 190 to 450 MB on the graphics card. About 390 MB of disk to start: the
  program about 125 MB with the package **Repair** takes its files from, each server's app about 110 MB, the app's
  libraries about 40 MB, and the game's data 111 MB after a first start and one song, more with each song it
  downloads. The installer itself is about 60 MB.
- **The videos** need Windows' Media Foundation. The N and KN editions of Windows come without it: there, install the
  Media Feature Pack, under Settings, Optional features (in Apps or in System, by the version of Windows). Without it
  the videos are black and silent, and the game goes on.
- **The language:** the launcher speaks Windows' display language, Korean or English, until one is chosen on the
  first-start guide's first step or the **Launcher** page, and the installer speaks the launcher's. The game and what
  the player draws over it (the bar, the sound panel, the question before quitting, the broadcast notice, its messages)
  speak the launcher's language once one is chosen, among the languages the game has, and Windows' display language
  until then; the country stays Windows'.
- **What it keeps on the PC,** per Windows user:
  - the program, in `%LOCALAPPDATA%\OpenDMTQ.Client`;
  - the launcher's settings and logs, and each server's app, in `%LOCALAPPDATA%\OpenDMTQ\client`;
  - what the game keeps, in a folder named after the app's package in `%LOCALAPPDATA%\OpenDMTQ`: the app's libraries
    (`lib`), the game's settings and the songs it downloaded (`data`), and the player's log, `player.log`, which starts
    over past 8 MB and keeps the part before as `player.log.1`.

  Scores are kept on the server. The launcher keeps the server's sign-in cookie, never the password.
- **Repairing, clearing and removing,** on the launcher's **Help** page, each with the same flag of `OpenDMTQ-cmd.exe`:
  - **Repair** compares the program's files with the package it was installed from and puts back what is missing or
    changed (`--repair`). Running the installer again and choosing **Repair** installs every file again.
  - **Clear game data** deletes what the game keeps, all but the device id: the game downloads its data again at the
    next start, and the PC stays the same player (`--clear-game-data`).
  - **Start over** forgets the servers, the sign-ins, the apps and the settings, and opens the first-start guide; the
    game's data and the language stay (`--reset`). **Forget** on the **Online** page does that for one server
    (`--forget URL`).
  - **Uninstall** removes the program, its shortcuts and its entry in Windows' Apps (`--uninstall`). It asks whether the
    settings, sign-ins and game data stay for a later install or go too (`--uninstall --delete-data`). With them go the
    device id and the logs of the installs (the installer's in `%TEMP%`, Velopack's in `%LOCALAPPDATA%\velopack`), and a
    later install is a new player, unless the account transfer below brings this one back. The installer uninstalls
    too, and so does **Uninstall** in Windows' Settings, Apps (and Control Panel's Programs): both open the installer's
    own uninstall, which asks whether the data stays, says each size, shows the work as it goes and ends on what went
    and what stayed; with **Delete everything** nothing of OpenDMTQ's is left on the PC. A tool that uninstalls quietly
    (the entry's quiet command) shows nothing and keeps the data.
- **The account:** a PC is a player of its own, apart from the same person's phone. The server gives each new device a
  new account, and the device id the PC goes by is kept in the game's folder: deleting that folder makes this PC a new
  player. The game's own account transfer carries a player to another device: on the device that has the player,
  **OPTION** shows its **TRANSFER CODE**; on the other, **OPTION**, the arrow beside the code opens the transfer code's
  input, which takes it with **Select**, and the game starts again as the same player, with its records.

## When something goes wrong

- **The game does not start:** the launcher says why on its bottom line, with a link to the player's log (**Open the
  game log**); **Help** opens it too. The log is `player.log` in the game's folder in `%LOCALAPPDATA%\OpenDMTQ`; the
  launcher's own is in `%LOCALAPPDATA%\OpenDMTQ\client\logs`.
- **It cannot reach the server:** the PC has to reach the server's address, as a phone does: on the same network, or
  over the internet when the server is set up for it
  ([the server's site does not open](troubleshooting.md#the-servers-site-does-not-open)). The
  [connection test](#testing-the-connection) says where the way to it stops, and finds a server that moved to 8791.
- **The launcher says the server runs an older OpenDMTQ:** the PC client needs a server of 0.8 or newer.
- **The sign-in is refused:** the ID and password are the site's. Too many wrong passwords make the server wait a while
  before the next try. A banned player's account is refused with the reason and the ban's end, as the server's owner
  set them, and an account the owner disabled on the Accounts page is told so, as the site's sign-in says it.
- **An update is refused:** the launcher installs only a release the OpenDMTQ project signed, and says so when one is
  not; the program stays as it was. The installer from the server's site installs the server's own version.
- **The player is missing or a file of the program is damaged:** **Help**, **Repair** puts the program's files back
  from the package it was installed from.
- **The installer says the game is open:** finish it and close the game; installing replaces the player it plays in.
- **The launcher stopped with an error:** its window says what happened and where its log is; **Open the log folder**
  opens the folder.
- **Windows blocks it with no Run anyway:** Smart App Control is on ([installing](#for-players), step 2).
- **The videos are black and silent:** see the Media Feature Pack above.
- **The sound breaks up:** the **Sound** page's **Last game's sound** says whether the last game had gaps; choose the **Normal**
  or **Safe** buffer there, or **Shared** instead of **Exclusive**.
- **Someone helps with a problem:** **Help**, **Save a report** gives them the logs and this PC's details in one zip
  ([a report](#a-report-for-whoever-helps)).

The rest is the server's: [what to tell its owner](play.md#when-something-does-not-work).

## How it works

The player runs the game's own Android code on Windows, as the app does on phones that cannot run 32-bit apps, and
draws it with Direct3D 11; the launcher writes the player's settings into a file and starts it with them. How each part
works, and what was measured: [the PC client](architecture.md#the-pc-client) in the architecture.

## For server owners

Nothing to do, unless the server has no internet: the site's **Download** page offers the installer to signed-in
players, set up for the server as it is handed out, and the launcher signs in with the site's accounts. The server hands
the launchers their updates too, of the installer's version ([updates](#updates)). Where the server gets the installer
and the updates, and what it needs without internet: [the PC client's installer](admin.md#the-pc-clients-installer).

To play on the server PC itself, nothing needs downloading: the admin pages' **App** page and the setup's last step,
opened on that PC, have **Play on this PC**, which installs the PC client set up for the server and opens it with the
owner's ID filled in, or opens it when it is installed ([Play on this PC](admin.md#play-on-this-pc)).
