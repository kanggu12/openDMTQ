"""OpenDMTQ without containers: the same server, run straight on this computer.

Linux and macOS (after host/install.sh, which makes ./opendmtq run this program) and the Windows bundle (OpenDMTQ.exe)
run the server with it: Apache with PHP for the game server and the players' site, the admin pages on waitress, and the
tools (import, app builder, song list) as plain Python. The settings are in .env and the files in data/, as with Docker
Compose, so the guides apply to both.

  ./opendmtq setup [--from FOLDER] [--host ADDRESS] [--songs | --no-songs]
  ./opendmtq start | stop | restart | status | run
  ./opendmtq import FOLDER [--songs] [--no-game-data] [--check]
  ./opendmtq apk | host [ADDRESS] | check | service [--remove]

On Windows the commands are OpenDMTQ.exe <command>. Started without one (OpenDMTQ.exe double-clicked), it sets up what
is missing and runs the server until its window is closed.
"""
