# The PC client

People can play on a Windows PC as well as on a phone or a tablet. On a PC the game runs in the player for Windows, and
the PC client sits between the player and the person: an installer, and a launcher that connects to the server, signs
in, downloads the server's app (the same app its phones install) and keeps it up to date, sets the picture and the
sound up for the PC, and starts the game. The game then plays against the server as it does on a phone.

![The launcher's PLAY page: the server and the sign-in, the ready check, how to play, the last game, and PLAY](images/client-play.png)

## For players

1. On the server's site, sign in and open **Download**. Under **On a computer (Windows)**, choose **Download the
   installer for Windows**. The file it gives, `OpenDMTQ-Setup-<address>.exe`, is set up for that server.
2. Run it and choose **Install**. It installs for your Windows user, with shortcuts on the desktop and in the Start
   menu and no administrator rights, and starts the launcher. If Windows says it protected your PC from an unknown app: **More info**, then **Run
   anyway**. The installer is not signed by a publisher Windows knows. Windows 11's Smart App Control, when it is on,
   blocks unsigned programs, this one among them, and has no **Run anyway**.
3. The launcher's first start walks through the server (already filled in), the sign-in with your site ID, the app's
   download, the picture and the sound, then **PLAY**.

The installer from the project's [releases](https://github.com/kanggu12/openDMTQ/releases/latest) (`OpenDMTQ-Setup.exe`)
is the same program without a server: its first start asks for the server's address. One launcher keeps several
servers, each with its own sign-in and app, and plays on the one chosen on the **Online** page.
`OpenDMTQ-Setup.exe --silent` installs or updates with no dialog and starts the launcher (`--no-start` leaves it
closed); while a game runs it installs nothing and ends with 3.

### The launcher

| Page | What it has |
| :--- | :--- |
| **Play** | The server and the account, the checks before a start (the player, the server, the sign-in, the app), how to play, the last play, and **PLAY** |
| **Screen** | Full screen or a window, the window's size, VSync, the frame limit, the FPS counter and its position, the render scale and its upscaler, anti-aliasing |
| **Sound** | The volume, the device, shared or the device alone, the buffer |
| **Controls** | What the touch screen, the mouse and the keyboard do |
| **Online** | The servers, the sign-in, the app on this PC and a check for a newer one |
| **Help** | The checks, what to try when something does not work, the logs, and repairing, clearing, starting over and uninstalling |
| **Launcher** | The language, updates of the launcher, the first-start guide again |

**PLAY** asks the server for a newer app first and downloads it when there is one; when the server cannot be asked, the
game starts with the app this PC has. The checks ask the server too: one that does not answer is said on the **Play** and
**Help** pages and does not stop **PLAY**. The launcher updates itself from the project's releases: **Launcher**, **Check for
updates**. Without internet, the installer from the server's **Download** page updates it instead, once the server has
a newer one; the servers and the settings stay. While the game runs the launcher steps aside, and comes back when the
game ends.

`OpenDMTQ-cmd.exe`, in `%LOCALAPPDATA%\OpenDMTQ.Client\current`, does the same from the command line: `--status`
(exit 0 when PLAY can go), `--server URL`, `--sign-in ID` (the password from standard input), `--sign-out`, `--app`,
`--set NAME=VALUE`, `--audio-devices`, `--language en|ko|system`, `--guide`, `--skip-guide` (the guide's **Skip**: the
window opens on its pages), `--servers` (the servers it knows, as **Online** lists them), `--open-log player|launcher`, `--play`,
`--update`, `--forget URL`, `--reset`, `--repair`, `--clear-game-data` and `--uninstall [--delete-data]`, with `--yes`
to answer their questions (`--help` lists them all). While the launcher's window is open, the flags that change what
it keeps are refused. `--set` takes the settings of the **Screen** and **Sound** pages:

| Setting | Values (the default first) | On the page |
| :--- | :--- | :--- |
| `display` | `fullscreen`, `window` | Mode |
| `window` | `auto` (fitted to the display), `1280x720`, `1600x900`, `1920x1080`, `2560x1440`, `3840x2160`, or any `WIDTHxHEIGHT` from 480x270 that fits the main display with room for the window's title bar and the taskbar, as the page offers them | Window size |
| `vsync` | `on`, `off` | VSync |
| `fps` | `auto` (the display's rate), `30`, `60`, `120`, `144`, `165`, `180`, `240`, `360`, `unlimited` | Frame limit |
| `show_fps` | `off`, `on` (a corner's name, as `fps_position` takes it, is on in that corner) | FPS counter |
| `fps_position` | `top_left` (beside a song's pause button), `top_right`, `bottom_left`, `bottom_right`; kept while the counter is off | Position, while the counter is on |
| `render_scale` | `100`, `85`, `75`, `67`, `50` | Render scale |
| `upscaler` | `bilinear`, `fsr1`, `nis` | Upscaler, below 100 % |
| `anti_aliasing` | `off`, `cmaa2`, `smaa` | Anti-aliasing |
| `audio_device` | `default` (Windows' default output), or a device's id from `--audio-devices` | Device |
| `audio_mode` | `shared`, `exclusive` (the device alone) | Mode |
| `audio_buffer` | `normal`, `low`, `safe` | Buffer |
| `volume` | `100`, or any number from 0 to 100 | Volume |
| `language` | `system` (Windows' display language), `en`, `ko`: the same as `--language` | Language, on the **Launcher** page; the game and what the player draws over it speak it too |

### In the game

| Input | What it does in the game |
| :--- | :--- |
| A touch screen | Fingers, as many at once as the screen takes, each with the time it saw it |
| The mouse's left button | One finger on the screen: tap, hold and drag |
| The mouse wheel | Scrolls what is under the pointer, as a finger's drag; with Shift, across |
| A pen | One finger |
| Esc | The phone's Back key: pauses a song, closes what is open |
| The keyboard | Text where the game asks for it (Enter ends it, Esc cancels it), Hangul too |
| The touch keyboard | Comes up when a touch opens the game's text, and types into it |
| F11, or Alt+Enter | Full screen, and back |
| The pointer resting at the game's top edge, or on the handle at its top centre | The bar: minimise, full screen, and the X that quits after asking |
| Alt+F4 | Nothing: the bar's X quits |
| Alt alone, F10 | Nothing (no menu mode that would hold the next key) |

- **The bar and quitting**: a PC has no phone's buttons around the game, so a bar of frosted glass comes down across
  the top of the game when the pointer moves to the game's very top edge or onto the handle and rests there a moment
  with its button up, or when a finger is drawn down from that edge on a touch screen, in either case only once the
  game has had no click, touch or held note for a second and a half: a click or a held note at the top of a song plays
  the song and never brings the bar, nor does a pointer on its way to the window's title bar. It also comes down by
  itself for 3 seconds when the game's picture first shows (not during its black start) and for 3 seconds after each
  switch between a window and full screen, whatever the pointer does, so that a player sees where it is. It stays while the
  pointer is on it and goes up soon after the pointer leaves, so it never sits on the game's own controls at the top
  while they are used; no key brings it. While it is down, the broadcast notice and an FPS counter in a top corner move
  down under it. It is tall enough to cover the game's own X at the top right of its song and music screens whole.
- **The handle**: a small tab hanging from the game's top edge at its centre, in the shape of the game's own tabs, the
  game's charcoal with its green line along the foot, says where the bar is; with the pointer on it, it grows a little
  and its line turns lime. The pointer resting on it, or just around it, brings the bar down. Clicks go through it to
  the game. It shows once the game's picture is up, and goes while the bar is down, while a notice or the question is
  up and while the game holds still.
  On its left, the OpenDMTQ wordmark as the launcher's header draws it; on its right three buttons in the launcher's own
  shape and depth (two corners cut, raised, sunk while held): **minimise** and **full screen** (or back to a window) as
  its secondary buttons, quiet metal with a lighter plate under the pointer, and an **X** that quits as its main button,
  in its lime from the start so that it is seen at once. A button acts only when let go where it was pressed (the
  question's buttons too). Minimise holds the game still, as a minimised window does, and the taskbar brings it back.
  The X asks first, in a glass card over the game dimmed and blurred behind it: **Keep playing** as the launcher's main
  button, or **Quit the game** as its secondary, red under the pointer; so a click by mistake does not end a song. In a
  window the game has a title bar to move it by and a frame to size it by, dark as the launcher's header (on Windows 11
  in its very colours; Windows 10 dark where it can), and no buttons of its own: it is minimised, put in full screen and
  quit from the bar. The taskbar's Close window asks the same, and Alt+F4 and a double click on the title bar do
  nothing. The card keeps within three quarters of the game's width, so a small window on a display at 150 % or 200 %
  gets a card in proportion to the game. The game holds still while it asks, as a phone's game does when its owner
  leaves it: a song stops where it was, with the game's own pause screen after. In the question, Left, Right and Tab
  move the choice (marked with the launcher's cyan keyboard ring), Enter takes it and Esc keeps playing. Minimised, the
  game holds still the same way, and goes on when it comes back.
- **Nothing of it is in the game's way**: the notice, the FPS counter and the handle let every click through to the game,
  and no piece takes the keyboard from the game's window (each is a window that never takes the focus; a click on the
  bar or the question gives the keyboard back to the game). Their pictures are made on a thread of their own, so the
  thread that stamps each key and click for the game never waits for them.
- **The glass**: the bar, the question, the broadcast notice and the FPS counter are frosted glass over the game, as
  Windows' own acrylic is made: the game's picture behind each, blurred and a little more saturated, under a charcoal
  tint, with a faint light at its top, a light edge and a soft shadow; in the game's own shapes, with its small corners,
  its bevel (a line of light along the top, of shade along the foot) and its green line along the bar's and the
  notice's foot. Their words keep 4.5:1 against the light behind them: where the game is light under the words, the
  tint deepens there. The picture behind is read from the game's frames at a quarter of its size (each of its pixels
  the mean of 4 by 4 of the frame's), at most 20 times a second while a piece is up and once while the game holds still;
  with none up, it costs the game nothing. A piece waits a moment for its first read; where none comes, it is its plain
  tint, nearly solid. The words are set in Pretendard, titles and buttons bold, which the player carries in its `fonts`
  folder with the launcher's wide face. The wordmark is a picture for each scale from 100 % to 400 %, drawn by the
  launcher's own code (`arm32/desktop/assets/make_wordmark.py`) and carried in the player's `images` folder: at those
  scales it is drawn pixel for pixel, between them the next larger is drawn down.
- **The pointer** over the game is a dart in the logo's look: a chrome left face and a lime right face with a dark rim.
  While the button is down it is all lime and a little smaller. It is sized for the display's scaling.
- **A touch screen** is the player's first input, as a phone's screen is the game's. Windows' own touch feedback stays
  off the game (no circles under the fingers, no square for a press and hold, no right click for it), and in full screen
  a finger that comes in from the screen's edge stays the game's instead of opening Windows' panels. Each touch reaches
  the game as Windows takes it in.

### The picture

![The launcher's Screen page: the frame limit, the FPS counter switched on with its position under it, then the render scale at 50 % with AMD FSR 1 as its upscaler, and SMAA](images/client-screen.png)

- **Full screen or a window.** Full screen is a borderless window over the whole display, at the display's own pixels
  whatever its scaling. A window opens at three quarters of the display's height at 16:9, or at the size chosen. The
  game fills the window while its shape is between 4:3 and 21:9; a window of another shape, such as a display turned
  upright, has black around the game. Moved to a display with other scaling, the game draws at the new size.
- **VSync on** (the default): each frame goes out on a refresh of the display the window is on, 60 Hz, 144 Hz, 240 Hz or
  another. A PC that is really behind, more than a quarter of its frames a refresh late through three checks of 2
  seconds in a row, takes every second refresh (120 frames a second on a 240 Hz display), then every third. It tries the
  faster rate again 5 seconds later, goes straight back when the try falls short, and waits twice as long before the
  next try, a minute at most. Some late frames, as the page before a song shows while the song loads (up to a tenth of
  them), and a pause of a tenth of a second or more, keep the display's rate.
- **The frame limit:** the display's rate (the default), a number, or none. With VSync on, a limit that is a whole
  fraction of the display's rate, or within 10 % above one, keeps every frame the same length (60 or 120 on a 240 Hz
  display); another limit is held by the clock, with each frame still on a refresh (144 on a 240 Hz display).
- **VSync off:** frames go out as soon as they are drawn, evenly at the limit, which may be above the display's rate, or
  as fast as the PC draws without one. A little less delay, and the picture may tear.
- **The FPS counter** is off by default. On, it shows at the top left, just right of a song's pause button; its
  **Position** can be changed to another corner (each corner has some of the game's own controls), and stays chosen
  while the counter is off. A small glass box like the game's Q and MAX box, faint as a whole so the game shows through
  it: FPS in the game's lime, the frames a second in white and the mean frame time under them, over the last second,
  twice a second. It counts the frames the player shows between their own moments, so a steady 60 reads 60; a loading
  screen that shows a frame now and then reads its few frames a second, and only a whole second without a frame reads
  0. It shows from the game's first frame, and hides while the game holds still (the question before
  quitting, a minimised window) instead of counting the stillness. It lets clicks through, and is drawn apart from the
  game's picture: it costs the game nothing, and the broadcast does not show it.
- **The render scale** draws the game at a share of the window's pixels (100 % down to 50 %), stretched to fill it:
  lighter for the graphics card, and softer. The share keeps the window's shape exactly where its size has fine enough
  steps (1920x1080 is 120 steps of 16x9): 67 % of 1920x1080 is 1280x720, so the game lays itself out as it does at full
  size, its parts where they belong.
- **The upscaler**, below 100 %: how the smaller picture reaches the window's size. **Bilinear** (the default) is the
  plain stretch of the window's surface. **AMD FSR 1** (FidelityFX Super Resolution 1) enlarges it with its
  edge-adaptive filter (EASU) and sharpens the result (RCAS, at AMD's sample's 0.25 stops). **NVIDIA NIS** (Image
  Scaling) enlarges in one pass with its edge-adaptive filter, with no sharpening added: the SDK's default of 50 % drew
  rims around the game's text and lines. Both are spatial: they need only the
  finished picture. At 100 % no upscaler is used, and the row is not shown.
- **Anti-aliasing** smooths the jagged edges of the game's shapes. **CMAA 2** (Intel's Conservative Morphological
  Anti-Aliasing 2) smooths them over the finished picture and keeps text and thin lines sharp; it runs on compute shaders
  (OpenGL ES 3.1), and where the graphics card has none the player uses SMAA instead and says so in its log. **SMAA**
  (SMAA 1x, High preset) smooths them with three light passes over the finished picture. With an upscaler,
  anti-aliasing comes first, at the size the game draws at. MSAA, which 0.9 offered, is gone: it left the game's picture
  as it was, and a setting of `msaa2`, `msaa4` or `msaa8` reads as CMAA 2. Temporal methods (DLSS, FSR 2 and 3, TAA, DLAA) need what a closed game does not hand
  over (its motion vectors and depth), and frame generation adds delay: none of them is offered.

How it works: with an upscaler or anti-aliasing, the game draws into a framebuffer of the player's own, of the size it
draws at, which stands in for the window's own framebuffer in every call the game makes that names or reads it (binding,
reading, invalidating and the questions about it), and the window's surface keeps the window's size. At each swap the
player's passes draw that frame to the window, the game's GL state saved before and put back after. The broadcast takes
the picture after them: what players see. The log says once what is in use (`the game draws at 640x360, upscaled by AMD
FSR 1 to 1280x720`, `anti-aliasing: SMAA`), and what the passes took on the render thread over the first 600 frames.
With the player's stats on (`ARM32_STATS=1`), every 5 seconds a `stats: picture` line gives each pass's mean time a frame
on the render thread and on the graphics card (by `EXT_disjoint_timer_query`, which ANGLE has; with its timestamps the
game's own time on the graphics card too), the swap's whole cost, and how often the game made its context current. `PLAYER_OFFSCREEN=1` has the frames drawn offscreen with no pass at all (a plain copy), to
measure the redirection by itself.

Measured on a 240 Hz display (4K, RTX 4090): 240 frames a second with VSync, none late in 480, in full screen at 100 %
and at 50 %; a limit of 120, 120.0 frames a second, none late; VSync off, 240.6 frames a second, 95 % of the frames
within 4.5 ms of their time; no limit, 733 to 965.

### The sound

- **The device:** Windows' default output, which the game follows when Windows changes it mid-game, or one chosen.
- **Shared or the device alone.** Shared plays alongside other programs' sound. The device alone (WASAPI's exclusive
  mode) has the least delay, with buffers of the device's own period (3 ms on a device that has it); other programs are
  silent meanwhile, and the sound is shared when Windows does not allow it.
- **The buffer:** low (Windows' low-latency mode, where the device has a shorter period than its standard one), normal,
  or safe for a busy PC.
- **The volume** of the game, 0 to 100. Windows' own volume still applies.

### Broadcasting

While broadcasts are on for the server and its owner shows a player live, the player broadcasts from the PC as a phone
does, with Windows' own video and sound encoders, at the quality the owner chose ([live broadcasts](live.md#from-a-pc)). A glass card slides down at the top of the game
when a broadcast starts and ends, with a red LIVE tag like the game's own tags while it is on (once it is over, its
title says so alone), and says where it can be watched.

### What it needs, and what it keeps

- **What it needs:** 64-bit Windows 10 or 11 on an x64 PC (Intel or AMD), and a graphics card with Direct3D 11. About
  390 MB of disk to start: the program about 125 MB with the package **Repair** takes its files from, each server's app
  about 110 MB, the app's libraries about 40 MB, and
  the game's data 111 MB after a first start and one song, more with each song it downloads. The installer itself is
  about 60 MB.
- **The videos** need Windows' Media Foundation. The N and KN editions of Windows come without it: there, install the
  Media Feature Pack, under Settings, Optional features (in Apps or in System, by the version of Windows). Without it
  the videos are black and silent, and the game goes on.
- **The language:** the launcher speaks Windows' display language, Korean or English, until one is chosen on the
  first-start guide's first step or the **Launcher** page, and the installer speaks the launcher's. The game and what
  the player draws over it (the bar, the question before quitting, the broadcast notice, its messages) speak the
  launcher's language once one is chosen, among the languages the game has, and Windows' display language until then;
  the country stays Windows'. The launcher hands it over in the settings file it writes before each start (`language=`).
- **What it keeps on the PC,** per Windows user:
  - the program, in `%LOCALAPPDATA%\OpenDMTQ.Client`;
  - the launcher's settings and logs, and each server's app, in `%LOCALAPPDATA%\OpenDMTQ\client`;
  - what the game keeps, in a folder named after the app's package in `%LOCALAPPDATA%\OpenDMTQ`: the app's libraries
    (`lib`), the game's settings and the songs it downloaded (`data`), and the player's log, `player.log`, which starts
    over past 8 MB and keeps the part before as `player.log.1`.

  Scores are kept on the server. The launcher keeps the server's sign-in cookie, never the password.
- **Repairing, clearing and removing,** on the launcher's **Help** page, each with the same flag of `OpenDMTQ-cmd.exe`:
  - **Repair** compares the program's files with the package it was installed from and puts back what is missing or
    changed (`--repair`). Running `OpenDMTQ-Setup.exe` again repairs too.
  - **Clear game data** deletes what the game keeps, all but the device id: the game downloads its data again at the
    next start, and the PC stays the same player (`--clear-game-data`).
  - **Start over** forgets the servers, the sign-ins, the apps and the settings, and opens the first-start guide; the
    game's data and the language stay (`--reset`). **Forget** on the **Online** page does that for one server (`--forget URL`).
  - **Uninstall** removes the program, its shortcuts and its entry in Windows' Apps (`--uninstall`). It asks whether
    the settings, sign-ins and game data stay for a later install or go too (`--uninstall --delete-data`). With them
    goes the device id, and a later install is a new player, unless the account transfer below brings this one back.
    Windows' Settings, Apps uninstalls too, and keeps the data.
- **The account:** a PC is a player of its own, apart from the same person's phone. The server gives each new device a
  new account, and the device id the PC goes by is kept in the game's folder: deleting that folder makes this PC a new
  player. The game's own account transfer carries a player to another device: on the device that has the player,
  **OPTION**, **CONNECT ACCOUNT** shows a code; on the other, **OPTION**, **RESTORE DATA** takes it, and that device
  then plays as the same player, with its records.

## For server owners

Nothing to do, unless the server has no internet (below). The site's Download page offers the installer to signed-in
players, with the server's address and name added to its end as it is handed out: the installer reads them and sets the
launcher up for the server. The file is the same for every server, so the server builds nothing for it. The admin
pages' **App** page offers the same installer, and the launcher downloads the app the site offers phones, signed in with
the player's site account (`client.php` answers it). The `OpenDMTQ.exe` of the server's Windows bundle, which runs the
server, and the PC client's `OpenDMTQ.exe`, the launcher, are two different programs.

Where the server gets the installer, the first that has one:

- **Beside the server's code:** a release's tools image and the Windows bundle bring it.
- **`data/apk`:** put there by hand, for a server without internet, or fetched there before.
- **The latest release:** fetched into `data/apk` when there is none, as Docker Compose from the source and a host
  install on Linux or macOS do.

A copy in `data/apk` gives way to the latest release's once it is a week old, and stays when that fetch fails. After a
fetch that failed, the builder waits a day before it tries again: a server without internet does not wait for an answer
at every start. Without internet, put the release's `OpenDMTQ-Setup.exe` and `OpenDMTQ-Setup.exe.version` in `data/apk`
([without internet](closed-network.md)). Without an installer the site shows no Windows button, and everything else
works as before.

The launcher signs in with the site's accounts, made on the admin pages' **Accounts** page, with the same limit on wrong
passwords as the site. A server reached over HTTPS hands out installers that use it, with the port named (HTTPS answers
on the game's port). Where the server has its own certificate authority (Docker Compose makes one), the installer
carries it, and the launcher trusts it for that server alone, beside Windows' own authorities.

## How it works

The player runs the game's own 32-bit Android code, as the app does on phones that cannot run 32-bit apps: the
[arm32 runtime](../arm32/README.md) translates the game's ARM code (Dynarmic), and a small layer gives it Linux's system
calls on Windows. In place of Android's Java side, the player has its own stand-in for the classes the game calls. The
game draws with OpenGL ES, which ANGLE runs on Direct3D 11; its sound goes out through WASAPI, and its videos are
decoded by Media Foundation. Its requests to the server go out as a phone's do, asking for the server's answers
compressed, which makes its lists of songs and scores many times smaller on the way. The bar, its handle, the question
before quitting, the notice, the FPS counter and the pointer are drawn by the player over the game's window, each a
window of its own whose picture a thread of the overlay's makes on the CPU; the UI thread, which stamps the game's keys
and clicks, only hands the finished pictures to Windows. For their glass, the render thread reads the rectangles of the
frame behind them as it goes to the window (after the passes), at half and then a quarter of their size, into a pixel
buffer that a later frame copies out once the graphics card is done, so nothing waits for it. With the stats on, a
`stats: glass` line every 5 seconds says what that took the render thread a frame, and a `stats: overlay` line what
the pictures took their thread and the UI thread.

The launcher is Python with Tk, made into a Windows program with PyInstaller; Velopack installs it and updates it. The
launcher writes the player's settings into a file and starts the player with it (`--app` names the folder of the
server's app, `--settings` the file).

## When something goes wrong

- **The game does not start:** the launcher says why on its bottom line, with a link to the player's log (**Open the
  game log**); **Help** opens it too. The log is `player.log` in the game's folder in `%LOCALAPPDATA%\OpenDMTQ`; the launcher's own is in
  `%LOCALAPPDATA%\OpenDMTQ\client\logs`.
- **The launcher says the server runs an older OpenDMTQ:** the PC client needs a server of 0.8 or newer.
- **The player is missing or a file of the program is damaged:** **Help**, **Repair** puts the program's files back
  from the package it was installed from.
- **The installer says a game is going on:** finish it and close the game; installing replaces the player it plays in.
- **The sign-in is refused:** the ID and password are the site's. Too many wrong passwords make the server wait a while
  before the next try.
- **Windows blocks it with no Run anyway:** Smart App Control is on (step 2 above).
- **The videos are black and silent:** see the Media Feature Pack above.
- **It cannot reach the server:** the PC has to reach the server's address, as a phone does: on the same network, or
  over the internet when the server is set up for it ([playing from outside your home](internet.md)).
- **The sound breaks up:** choose the **Safe** buffer on the **Sound** page, or shared instead of the device alone.
