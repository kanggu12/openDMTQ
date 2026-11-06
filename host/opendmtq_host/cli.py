"""The command line: which command runs what."""

import argparse
import os
import sys

from .paths import CLI, WINDOWS
from .output import die
from .server import cmd_run
from .commands import (cmd_apk, cmd_check, cmd_runtime, cmd_host, cmd_import, cmd_restart, cmd_service, cmd_start, cmd_status,
                       cmd_stop)
from .setup import cmd_setup


def main(argv=None):
    p = argparse.ArgumentParser(prog=CLI, description="Run an OpenDMTQ server without containers.")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")
    s = sub.add_parser("setup", help="first run, or again at any time: settings, game files, server, phone app")
    s.add_argument("--from", dest="from_folder", metavar="FOLDER", help="folder (or file) with your game files")
    s.add_argument("--host", help="the address phones use, if not this computer's own (host:port for another port)")
    songs = s.add_mutually_exclusive_group()
    songs.add_argument("--songs", dest="songs", action="store_true", default=None, help="import the songs too")
    songs.add_argument("--no-songs", dest="songs", action="store_false", help="leave the songs out")
    s.set_defaults(fn=cmd_setup)
    r = sub.add_parser("run", help="run the server in the foreground (for services, and the Windows window)")
    r.add_argument("--log-to-file", action="store_true", help=argparse.SUPPRESS)
    r.set_defaults(fn=cmd_run)
    sub.add_parser("start", help="start the server in the background").set_defaults(fn=cmd_start)
    sub.add_parser("stop", help="stop the server").set_defaults(fn=cmd_stop)
    sub.add_parser("restart", help="stop, then start").set_defaults(fn=cmd_restart)
    sub.add_parser("status", help="one-screen summary").set_defaults(fn=cmd_status)
    i = sub.add_parser("import", help="take the base APK and the game data (with --songs the songs) from a folder")
    i.add_argument("path")
    i.add_argument("--songs", action="store_true", help="import the songs too")
    i.add_argument("--no-game-data", action="store_true", help="leave the game data as it is")
    i.add_argument("--check", action="store_true", help="only say what each file there is and whether it can be used")
    i.set_defaults(fn=cmd_import)
    sub.add_parser("apk", help="build the phone app now").set_defaults(fn=cmd_apk)
    r = sub.add_parser("runtime", help="get the newest runtime for phones without 32-bit support, then build the app")
    r.add_argument("--no-app", action="store_true", help="only the runtime: the server's next start builds the app")
    r.set_defaults(fn=cmd_runtime)
    h = sub.add_parser("host", help="show or change the address phones use")
    h.add_argument("address", nargs="?")
    h.set_defaults(fn=cmd_host)
    sub.add_parser("check", help="walk the game's whole path against the running server").set_defaults(fn=cmd_check)
    v = sub.add_parser("service", help="start the server with the computer (systemd or launchd)")
    v.add_argument("--remove", action="store_true", help="stop starting it with the computer")
    v.set_defaults(fn=cmd_service)
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 1 and argv[0] not in sub.choices and os.path.exists(argv[0]):
        # A folder or file dropped on OpenDMTQ.exe: imported, the songs with it.
        status = cmd_import(argparse.Namespace(path=argv[0], songs=True, no_game_data=False, names=None))
        if WINDOWS and sys.stdin and sys.stdin.isatty():
            try:
                input("Imported. Start OpenDMTQ.exe to run the server. Press Enter to close this window.")
            except EOFError:
                pass
        return status
    args = p.parse_args(argv)
    # As root Apache would have to be told whom to become, and every file would end up root's.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        die("please run this as a normal user, not as root (host/install.sh asks for sudo when it needs it)")
    if not args.cmd:
        # No command (OpenDMTQ.exe double-clicked): set up what is missing, then run.
        args = p.parse_args(["setup"])
    return args.fn(args)
