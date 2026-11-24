"""The first start: the settings, the game's files, the server, and the setup in the browser."""

import argparse
import glob
import os
import sys
import time

from opendmtq_cli import discover, env, look
from .paths import DATA, ROOT, WINDOWS
from .output import die, ok, say, tell, warn
from .programs import programs
from .settings import admin_url, ensure_settings, leave_port_80, settings, site_url
from .folders import make_folders, version
from .server import cmd_run, open_setup
from .commands import app_manifest, build_status, cmd_import, cmd_start, show_address


def search_dirs():
    """discover's folders, and on Windows the Desktop OneDrive keeps."""
    dirs = []
    if WINDOWS:
        home = os.path.expanduser("~")
        dirs += [os.path.join(home, "OneDrive", "Desktop"), os.path.join(home, "OneDrive", "바탕 화면")]
    return dirs


def find_files(given):
    """The folder with the game files: --from, else the search in Downloads and Desktop, else (in a window) asked.
    Returns (folder, [file names] or None)."""
    if given:
        return os.path.abspath(os.path.expanduser(given)), None
    found = discover.find()
    for d in search_dirs():
        hits = discover.matches(d)
        if hits:
            found.append((d, sorted(hits)))
    if found:
        folder, names = found[0]
        ok(f"game files in {folder}: {', '.join(names)}")
        return folder, names
    if sys.stdin and sys.stdin.isatty():
        say("No game files found in Downloads or on the Desktop.")
        say("Drag the folder with your game files (the APK and the client data) onto this window, then press Enter:")
        for _ in range(3):
            try:
                answer = input("> ").strip().strip('"').strip("'")
            except EOFError:
                break
            if answer and os.path.exists(answer):
                return os.path.abspath(answer), None
            say("That folder was not found. Drag it onto this window again, then press Enter:")
    # Where it looked and the names it takes, on Linux and macOS: a file of another name was there, maybe.
    die("no game files: drag their folder onto OpenDMTQ.exe, or put it in Downloads, then start OpenDMTQ.exe again"
        if WINDOWS else f"{discover.not_found()}. Put one of those words in the file's name, or pass its folder with "
        "--from <folder> (docs/troubleshooting.md, \"Setup cannot find the game files\")")


def ask_songs(args):
    """Whether to import the songs too: --songs or --no-songs, else asked (yes by default)."""
    if args.songs is not None:
        return args.songs
    if sys.stdin and sys.stdin.isatty():
        answer = input("Import the songs found with the game files too? [Y/n] ").strip().lower()
        return answer in ("", "y", "yes")
    return False


def have_game_data():
    """True when data/content holds the client data (the client's tables)."""
    tables = os.path.join(DATA, "content", "web", "patch", "phone_new", "*", "android", "patch_new.csv.lz4")
    return bool(glob.glob(tables))


def have_base_apk():
    """True when data/apk/base holds a client to build the app from."""
    return bool(glob.glob(os.path.join(DATA, "apk", "base", "*.apk")))


def cmd_setup(args):
    """First run, or again at any time: settings, files, server, app. Only what is missing is done."""
    found = opening()
    make_folders()
    # Off port 80 before the settings are filled in and named, for a server set up on it before 0.11.0.
    leave_port_80()
    values = ensure_settings(args.host)
    # Files named on the command line are imported here; otherwise the setup pages find them (or let the owner pick
    # them) in the browser.
    if args.from_folder:
        folder, names = find_files(args.from_folder)
        songs = ask_songs(args)
        cmd_import(argparse.Namespace(path=folder, songs=songs, no_game_data=False, names=names))
    values = settings()
    unfinished = not setup_finished(values)
    if WINDOWS:
        # In the window: the server runs here until the window is closed, with the setup in the browser until it is
        # done.
        summary(values)
        args.open_setup = unfinished
        return cmd_run(args, values, found)
    cmd_start(args)
    if unfinished:
        # The files, the address, the players and the app, in the browser.
        open_setup(values)
        return 0
    # The app builder runs with the server; wait for its outcome so the summary can say it.
    say("Building the phone app (a few minutes the first time)...")
    for _ in range(900):
        b = build_status()
        if b.get("state") in ("done", "failed") and b.get("host") == values["PUBLIC_HOST"]:
            break
        time.sleep(1)
    b = build_status()
    if b.get("state") == "failed":
        warn(f"the app could not be built: {b.get('error', 'see data/state/logs/programs.log')}")
    summary(values)
    return 0


def opening():
    """The start of the setup, the first thing the window shows: the wordmark with the version, then the programs it
    found. Returns them."""
    look.banner(version())
    found = programs()
    ok("Apache, PHP, Java and 7-Zip are there")
    return found


def setup_finished(values):
    """True when the setup pages have nothing left to do: the game's files, a client, an account and the app for the
    address (tools/opendmtq_tools/admin/setup.py says the same of each)."""
    if not (have_game_data() and have_base_apk()):
        return False
    try:
        import sqlite3
        con = sqlite3.connect(os.path.join(DATA, "state", "dmtq.db3"))
        try:
            accounts = con.execute("SELECT COUNT(*) FROM SiteUser").fetchone()[0]
        finally:
            con.close()
    except Exception:  # pylint: disable=broad-except  (no database or no table yet: no account)
        accounts = 0
    m = app_manifest()
    return bool(accounts) and bool(m) and m.get("host") == values["PUBLIC_HOST"]


def summary(values):
    """Where everything is, once the server runs."""
    say("")
    # The addresses and the owner's sign-in in one block, the password with where it is kept.
    for line in look.address_block(site_url(values), admin_url(values),
                                   values.get("ADMIN_USER") or "admin", values.get("ADMIN_PASSWORD"),
                                   f"kept in .env in {ROOT}" + ("; Notepad opens it" if WINDOWS else "")):
        say(line)
    # An owner's ID the players' site does not take: said where the owner reads their sign-in (env.owner_id_problem).
    problem = env.owner_id_problem(values)
    if problem:
        warn(problem)
    say("")
    tell("Players need an account: make one for each on the admin pages, under Accounts.")
    show_address(values)
    if WINDOWS:
        tell(f"The QR code for phones is on the site's home page: open http://{values['PUBLIC_HOST']}/ in a browser and "
            "sign in.")
        say("")
        tell("Leave this window open while people play. To stop the server, close it, or press Stop the server on the "
            "admin pages' Server page.")
        # Phones and the PC client reach the server alike: a public network keeps both out.
        tell("Windows may ask whether Apache may use the network: allow it on private networks. If your Wi-Fi is set "
            "as a public network, phones and other PCs cannot connect: in Settings, Network & internet, choose Private "
            "for it.")
    # A line of room before the running server's own lines.
    say("")
