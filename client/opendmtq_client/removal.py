"""Removing what OpenDMTQ keeps on this PC.

OpenDMTQ has three places, per Windows user:

  %LOCALAPPDATA%\\OpenDMTQ.Client      the program (installed.py)
  %LOCALAPPDATA%\\OpenDMTQ\\client      the launcher's settings, sign-ins and logs, and each server's app
  %LOCALAPPDATA%\\OpenDMTQ\\<package>   what the game keeps: the app's libraries, the game's settings and downloads, its
                                      log, and the id this PC is a player by

Three removals, from the least to the most:

  clear_game_data()    empties the game's folders and keeps the id: the game downloads its data again, and this PC
                       stays the player it is on the server
  delete_everything()  the second and third places whole, the id with them, and OpenDMTQ's own logs elsewhere: Velopack's
                       log of it and the installer's logs in the temporary folder (leftovers())
  uninstall()          the program, by Velopack's own uninstaller, which also takes the shortcuts and Windows' entry

Nothing here asks: the window and the command line ask first (maintenance.py, main.py). A link or a Windows junction is
removed as itself and never followed, except a game's folder or its data folder that is one (moved to another disk):
what it holds is the game's, and goes as if it were in place.
"""

import logging
import os
import stat
import subprocess
import sys
import tempfile

from opendmtq_client import apps, errors, installed, player, preset, safety, updates
from opendmtq_client import server as srv
from opendmtq_client import state as st

log = logging.getLogger("opendmtq_client")

# The folder of OpenDMTQ's data in the user's folder for programs, and the launcher's own folder in it.
VENDOR, LAUNCHER = "OpenDMTQ", "client"
# Where the player keeps the id this PC is a player by, inside a game's folder.
ID_FOLDER, ID_FILE = "data", "android_id"
# What the launcher writes in its folder: asked only for a folder OPENDMTQ_CLIENT_DIR names, where other programs'
# files may be. Its files by their names; in "logs" and "servers", which other programs may have too, only its own.
OWN_NAMES = (st.FILE_NAME, srv.TRUST_FILE, preset.FILE_NAME, updates.PENDING, player.SETTINGS)
OWN_STARTS = (st.FILE_NAME + ".broken-", player.SETTINGS + ".", ".settings-", ".trust-", ".preset-")
LOGS, LOG_NAMES = "logs", ("launcher.log", "launcher.log.1", "launcher.log.2")
SERVERS = "servers"
# Velopack's own log of OpenDMTQ's installs, updates and uninstalls, written by Update.exe (the one before it kept as .old
# past 1 MB), in the folder Velopack keeps for every program it installs (%LOCALAPPDATA%\velopack).
VELOPACK_FOLDER, VELOPACK_LOG = "velopack", "velopack_%s.log" % installed.PACKAGE_ID
# Velopack's log of the uninstall after Delete all: inside the install folder, which goes whole a few seconds after
# Update.exe ends, so that the uninstall leaves no log of its own behind in Velopack's folder.
UNINSTALL_LOG = "uninstall.log"
# Windows' tag of a junction (the stat module has it on Windows only).
JUNCTION = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
# CREATE_NO_WINDOW and CREATE_NEW_PROCESS_GROUP: the uninstaller shows nothing and outlives this program.
DETACHED = 0x08000000 | 0x00000200


class RemovalError(errors.Worded):
    """A removal that cannot be made here; its words say why."""


def data_root():
    """OpenDMTQ's folder in the user's folder for programs: the launcher's folder and the games' are in it."""
    return os.path.join(st.local_dir(), VENDOR)


def _link_stat(found):
    """True when what os.lstat (or a listing's entry) found is a symbolic link or a Windows junction."""
    # A junction is a folder to Windows: only its reparse tag (on Windows alone) tells it apart.
    return stat.S_ISLNK(found.st_mode) or getattr(found, "st_reparse_tag", 0) == JUNCTION


def _is_link(path):
    """True for a symbolic link or a Windows junction."""
    try:
        found = os.lstat(path)
    except OSError:
        return False
    return _link_stat(found)


def _entry_is_link(entry):
    """True for a symbolic link or a Windows junction in a folder's listing (os.scandir), asking the disk nothing on
    Windows: its listing has each entry's kind and reparse tag."""
    if entry.is_symlink():
        return True
    # Elsewhere there are no junctions, and the call below would cost a stat for each folder.
    return os.name == "nt" and _link_stat(entry.stat(follow_symlinks=False))


def _names(folder):
    """What is in a folder; nothing when it is not there."""
    try:
        return sorted(os.listdir(folder))
    except OSError:
        return []


def _real(path):
    """A path as the system finds it: links followed, Windows' short names long, in one case."""
    return os.path.normcase(os.path.realpath(path))


def _same(a, b):
    """Whether two paths name one place."""
    return _real(a) == _real(b)


def game_folders():
    """The games' folders on this PC: every folder in OpenDMTQ's but the launcher's own."""
    root, own = data_root(), st.config_dir()
    found = []
    for name in _names(root):
        path = os.path.join(root, name)
        if name.lower() != LAUNCHER and os.path.isdir(path) and not _same(path, own):
            found.append(path)
    return found


def _tree_bytes(folder):
    """The bytes of the files under a folder; the links in it are not followed and count nothing. One listing a folder
    and nothing more on Windows, whose listing has each file's size; one stat a file elsewhere."""
    total, folders = 0, [folder]
    # Folders still to list, one at a time: no recursion, however deep a game nests its files.
    while folders:
        try:
            with os.scandir(folders.pop()) as listing:
                entries = list(listing)
        except OSError:
            # Gone since, or not ours to read: it adds nothing, as the deletion would take nothing from it.
            continue
        for entry in entries:
            try:
                if _entry_is_link(entry):
                    # Removed as itself and never followed (delete_everything, clear_game_data).
                    continue
                if entry.is_dir(follow_symlinks=False):
                    folders.append(entry.path)
                else:
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                # A file gone between the listing and its size adds nothing.
                continue
    return total


def _counted(path, link_too=False):
    """The bytes under a path; links are not followed, except the path itself when link_too."""
    try:
        found = os.lstat(path)
    except OSError:
        return 0
    if _link_stat(found):
        if not link_too:
            return 0
        # Followed: a folder moved to another disk counts what it holds; a link to anything else is only itself.
        return _tree_bytes(path) if os.path.isdir(path) else found.st_size
    return _tree_bytes(path) if stat.S_ISDIR(found.st_mode) else found.st_size


def game_data_size():
    """How many bytes clear_game_data() would free."""
    total = 0
    for folder in game_folders():
        for name in _names(folder):
            path = os.path.join(folder, name)
            if name.lower() == ID_FOLDER and os.path.isdir(path):
                # The data folder (or the folder it links to): all of it but the id.
                total += sum(_counted(os.path.join(path, inner)) for inner in _names(path)
                             if inner.lower() != ID_FILE)
            else:
                total += _counted(path)
    return total


def everything_size():
    """How many bytes delete_everything() would free."""
    root, own = data_root(), st.config_dir()
    total = sum(_counted(os.path.join(root, name), link_too=True) for name in _names(root))
    for folder in game_folders():
        # A game's data folder moved to another disk: what it holds goes too, the id with it (delete_everything).
        total += sum(_counted(os.path.join(folder, name), link_too=True) for name in _names(folder)
                     if name.lower() == ID_FOLDER and _is_link(os.path.join(folder, name)))
    if not _inside(own, root):
        total += sum(_counted(path) for path in _own_paths(own))
    # OpenDMTQ's own logs outside its folders go too.
    total += sum(_counted(path) for path in leftovers())
    return total


def megabytes(size):
    """A size for a sentence: '640 KB', '85 MB', '1.2 GB'."""
    if size >= 1 << 30:
        return "%.1f GB" % (size / float(1 << 30))
    if size >= 1 << 20:
        return "%d MB" % round(size / float(1 << 20))
    # Anything at all is at least 1 KB, so that a sentence never says something small is nothing.
    return "%d KB" % max(1, round(size / 1024.0))


def _unlink(path):
    """A file or a link gone; a read-only one too, which Windows refuses at first."""
    try:
        os.unlink(path)
    except PermissionError:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        os.unlink(path)


def _delete(path, failed):
    """A file, a link or a folder with all in it gone. What Windows does not let go (a file in use) is added to
    `failed`, and the rest still goes."""
    try:
        if _is_link(path) or not os.path.isdir(path):
            _unlink(path)
            return
        for name in _names(path):
            _delete(os.path.join(path, name), failed)
        os.rmdir(path)
    except OSError as e:
        log.warning("could not delete %s: %s", path, e)
        # A folder that stays because of a file in it is that file's failure, said once.
        if not any(other.startswith(path + os.sep) for other in failed):
            failed.append(path)


def _rmdir(path):
    """A folder gone when nothing is left in it."""
    try:
        os.rmdir(path)
    except OSError:
        pass


def _inside(path, folder):
    """Whether a path is a folder or under it."""
    path, folder = _real(path), _real(folder)
    return path == folder or path.startswith(folder + os.sep)


def _own(name):
    """Whether a file in the launcher's folder is one the launcher writes."""
    return name in OWN_NAMES or name.startswith(OWN_STARTS)


def _own_paths(own):
    """What the launcher wrote in a folder of other programs' files too: its files, its logs, its servers' apps."""
    found = [os.path.join(own, name) for name in _names(own) if _own(name)]
    logs = os.path.join(own, LOGS)
    found += [os.path.join(logs, name) for name in _names(logs) if name in LOG_NAMES]
    servers = os.path.join(own, SERVERS)
    for name in _names(servers):
        # A server's folder is the launcher's when it holds what the launcher puts there (apps.py).
        path = os.path.join(servers, name)
        if any(os.path.isfile(os.path.join(path, mark)) for mark in (apps.CONF, apps.DETAILS)):
            found.append(path)
    return found


def _followed(path):
    """Stop a test before it deletes what a linked folder leads to, unless that is a temporary folder."""
    if _is_link(path):
        safety.refuse_deleting_in_tests(os.path.realpath(path))


def clear_game_data():
    """Empty the games' folders, all but the id this PC is a player by; returns what could not be deleted.

    The app's libraries, the game's settings and downloads and the player's log go; the player makes and downloads them
    again at the next start. The server knows this PC's player by the id, so with it kept the same player comes back.
    """
    failed = []
    safety.refuse_deleting_in_tests(data_root())
    for folder in game_folders():
        _followed(folder)
        for name in _names(folder):
            path = os.path.join(folder, name)
            if name.lower() == ID_FOLDER and os.path.isdir(path):
                # The data folder stays, with the id alone in it; a link to one elsewhere too, the id still behind it.
                _followed(path)
                for inner in _names(path):
                    if inner.lower() != ID_FILE:
                        _delete(os.path.join(path, inner), failed)
            else:
                _delete(path, failed)
        log.info("cleared the game's data in %s", folder)
    return failed


def close_log():
    """Close the launcher's log file: it is inside the folder that is about to go, and nothing may make it again."""
    logger = logging.getLogger("opendmtq_client")
    for handler in [h for h in logger.handlers if getattr(h, "odq_log", False)]:
        logger.removeHandler(handler)
        handler.close()
    # Something still listens, so that Python does not print what is logged from here on to the console itself.
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())


def delete_everything():
    """Delete all OpenDMTQ keeps for this Windows user besides the program: the launcher's settings, sign-ins, logs and
    servers' apps, and the games' folders with their ids. Returns what could not be deleted.

    The caller must not save the launcher's state afterwards: that would make the folder again.
    """
    failed = []
    root, own = data_root(), st.config_dir()
    safety.refuse_deleting_in_tests(root)
    safety.refuse_deleting_in_tests(own)
    log.info("deleting everything OpenDMTQ keeps on this PC")
    close_log()
    if not _inside(own, root):
        # A folder OPENDMTQ_CLIENT_DIR names: only what the launcher wrote goes, and each folder when that empties it.
        for path in _own_paths(own):
            _delete(path, failed)
        for name in (LOGS, SERVERS, ""):
            _rmdir(os.path.join(own, name))
    for folder in game_folders():
        # A game's data folder moved to another disk: what is in it goes, the id with it, then the link below.
        for name in _names(folder):
            path = os.path.join(folder, name)
            if name.lower() == ID_FOLDER and _is_link(path):
                _followed(path)
                for inner in _names(path):
                    _delete(os.path.join(path, inner), failed)
        if _is_link(folder):
            # A game's folder moved to another disk: what is in it goes, then the link below.
            _followed(folder)
            for name in _names(folder):
                _delete(os.path.join(folder, name), failed)
    # OpenDMTQ's own folder: everything in it is OpenDMTQ's.
    for name in _names(root):
        _delete(os.path.join(root, name), failed)
    _rmdir(root)
    # Then its own logs elsewhere: Velopack's and the installer's.
    _delete_leftovers(failed)
    return failed


def leftovers():
    """OpenDMTQ's own files outside its folders, which Delete all takes with them: Velopack's log of OpenDMTQ (and the
    one before it), and the installer's logs in the temporary folder (its own, and Velopack's setup's of each run).
    Other programs' files beside them stay."""
    from opendmtq_client import installer
    velopack = os.path.join(st.local_dir(), VELOPACK_FOLDER)
    # Velopack's folder holds the logs of every program it installed: only OpenDMTQ's own by their names.
    found = [os.path.join(velopack, name) for name in _names(velopack) if name in (VELOPACK_LOG, VELOPACK_LOG + ".old")]
    # The temporary folder holds everyone's files: only the installer's, by their names (installer.is_log).
    temp = installer.log_folder()
    found += [os.path.join(temp, name) for name in _names(temp) if installer.is_log(name)]
    # Files only: a folder by such a name is none of the installer's.
    return [path for path in found if not os.path.isdir(path) or _is_link(path)]


def _delete_leftovers(failed):
    """Delete OpenDMTQ's own files outside its folders (leftovers()), and Velopack's folder when that empties it."""
    for path in leftovers():
        # Each one inside the temporary folder in a test (a test points LOCALAPPDATA and the log folder at its own).
        safety.refuse_deleting_in_tests(path)
        _delete(path, failed)
    # Velopack's folder goes only when nothing of another program's is left in it.
    _rmdir(os.path.join(st.local_dir(), VELOPACK_FOLDER))


def can_uninstall():
    """The install folder when this launcher can be uninstalled from here; RemovalError when OpenDMTQ-Setup.exe did not
    install it."""
    root = installed.root()
    if not root or not installed.updater(root):
        raise RemovalError("uninstalling works in the launcher installed by OpenDMTQ-Setup.exe",
                           "error.uninstall.not_installed")
    return root


def uninstall(delete_all=False):
    """Start Velopack's uninstaller and return at once; the caller ends this program right after.

    Update.exe --uninstall --silent asks nothing and shows nothing: it closes what still runs from the install folder,
    removes the shortcuts, Windows' entry for the program and, a few seconds later, the folder itself. It leaves the
    data folders alone. After Delete all (`delete_all`), its own log goes into the install folder, which goes whole
    after it, instead of Velopack's folder, where the log Delete all has just deleted would come back.
    """
    root = can_uninstall()
    safety.refuse_deleting_in_tests(root)
    command = [installed.updater(root), "--uninstall", "--silent"]
    if delete_all:
        # Update.exe's --log names its log file for this run (a global option, after the command as before it).
        command += ["--log", os.path.join(root, UNINSTALL_LOG)]
    log.info("uninstalling: %s", " ".join(command))
    # Started from outside the install folder, which could not go while a program's current folder is in it.
    subprocess.Popen(command, cwd=tempfile.gettempdir(), close_fds=True,
                     creationflags=DETACHED if sys.platform == "win32" else 0,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
