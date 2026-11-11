OpenDMTQ player for Windows
===========================

The game on your computer, from your OpenDMTQ server: the app in this folder is the one the server built for its
address, the same app its phones install. It plays against that server.

OpenDMTQ is an unofficial, non-commercial project. It is not affiliated with or endorsed by NEOWIZ. DJMAX and
TECHNIKA Q are trademarks of NEOWIZ.

Start
-----

1. Keep this folder somewhere of your own, for example in Documents.
2. Start OpenDMTQ-Player.exe. The first start takes a little longer: the player unpacks the app's libraries.
3. If Windows says it protected your PC from an unknown app: "More info", then "Run anyway". The player is not signed by
   a publisher Windows knows. Windows 11's Smart App Control, when it is on, blocks unsigned programs, this one among
   them, and has no "Run anyway".

If the game cannot start, a message box says why and where its log is.

Playing
-------

- The bar over the game's top, which comes down with the pointer resting on the small tab at its top centre (or on its
  top edge): minimise, full screen, and X to quit. The window has no buttons of its own.
- A touch screen is the game's screen: as many fingers at once as it takes, and Windows' touch feedback and edge
  swipes (in full screen) stay out of the way. A pen is one finger, and so is the mouse's left button.
- The mouse wheel scrolls what is under the pointer; with Shift, across.
- Esc is the phone's Back key: it pauses a song and closes what is open. On the game's first screen it asks whether to
  quit, and quitting there closes the player.
- The keyboard types where the game asks for text, Hangul too: Enter to finish, Esc to cancel. When a touch opens the
  text, Windows' touch keyboard comes up for it.
- The game runs at your display's refresh rate (60 Hz, 144 Hz, 240 Hz or another) and at its own pixels, in a window
  of any size.

Good to know
------------

- It needs 64-bit Windows 10 or 11 on an x64 PC (Intel or AMD), and a graphics card with Direct3D 11.
- The videos need Windows' Media Foundation. The N and KN editions of Windows come without it: there, install the Media
  Feature Pack (Settings, Optional features, in Apps or in System by the version of Windows). Without it the videos are
  black and silent, and the game goes on.
- What the game keeps on this computer (its settings and the songs it downloaded), the app's libraries, and the log
  (player.log) are in %LOCALAPPDATA%\OpenDMTQ, in a folder named after the app's package. Scores are kept on the server.
- This computer is a player of its own. Deleting that folder makes it a new player. To play as the player you are on
  another device: there, OPTION, CONNECT ACCOUNT shows a code; here, OPTION, RESTORE DATA takes it.
- When your server builds its app again (a new address, an update), download the player again from the server's site
  and put its OpenDMTQ-Player folder in place of this one. What the game keeps stays.

If something does not work, please ask whoever runs your server. Guides: https://github.com/kanggu12/openDMTQ

The parts this player brings and their licenses: the licenses folder.
