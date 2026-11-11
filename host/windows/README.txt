OpenDMTQ for Windows
====================

An open-source server for DJMAX Technika Q. No game files are included: it runs with your own copy of the game's
Android app (an .apk; the original, or a copy changed for another server) and its client data and song data (a
folder or an archive, also one in parts). Please use only files you have the right to use. Importing the song data,
the songs' music, charts and jackets, is optional.

OpenDMTQ is an unofficial, non-commercial project, not affiliated with or endorsed by NEOWIZ. DJMAX and TECHNIKA Q are
trademarks of NEOWIZ. If a rights holder asks, the project will be made private or taken down.

Start
-----

1. Keep this folder somewhere of your own, outside OneDrive and Program Files (for example C:\OpenDMTQ).
2. Start OpenDMTQ.exe. The setup opens in your browser.
3. The setup finds your files in Downloads, on the Desktop or in Documents. If they are elsewhere, paste their path or
   open their folder. Each file says what it is and whether it can be used. Then the setup takes you through the address
   phones use, an account for each player, and the app.
4. When Windows asks whether Apache may use the network, allow it on private networks. If your Wi-Fi is set as a public
   network, phones cannot connect: in Settings, Network & internet, open your Wi-Fi and choose Private.
5. On a phone on the same Wi-Fi, open the address the setup shows, sign in with the player's account, tap "Download app
   (.apk)", and install it.

The server runs while the window is open. To stop it, close the window, or on the admin pages open Maintenance and
press "Stop the server".

If Windows says it protected your PC from an unknown app: "More info", then "Run anyway". OpenDMTQ.exe is not signed
by a publisher Windows knows.

Later
-----

- Songs: on the admin pages, Songs, then "Choose the folder": the client data and the song data together, or the DMQ
  folder alone. An import replaces the songs imported before; single songs can be added on the same page and stay.
- The admin pages: the window shows their address, the user (admin) and the password.
- Commands: open a terminal in this folder (type cmd in Explorer's address bar, then Enter), then for example
  OpenDMTQ.exe status, OpenDMTQ.exe apk or OpenDMTQ.exe --help. OpenDMTQ.exe import --check <folder> says what each file
  in a folder is, and imports nothing.
- The admin password is in the file .env in this folder; open it with Notepad.
- Your data (players, scores, recordings, the app's signing key) is in the data folder: back it up from the admin pages.

Guides, and where to report a problem: https://github.com/kanggu12/openDMTQ

The programs this bundle brings, and their licenses: THIRD-PARTY-NOTICES.txt. OpenDMTQ itself: LICENSE.txt (MIT).
