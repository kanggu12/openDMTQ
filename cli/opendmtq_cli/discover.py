"""Find the game's files without asking: the usual download folders, Windows ones too on WSL."""

import glob
import os
import re

# Words the game's files are usually named with. An archive is taken for the game's only with one of them in its
# name: Downloads holds other archives too, and each would be opened.
GAME_WORDS = ("dmtq", "djmax", "technika")
# The kinds of file the import reads: the client (alone or in an APK bundle), and archives of the client data and the
# song data, whole or in parts (the first part stands for them all).
APK = ".apk"
APPS = (".apk", ".xapk", ".apks")
ARCHIVES = (".rar", ".zip", ".7z")
FIRST_PART = re.compile(r".+(?:\.part0*1\.rar|\.(?:7z|zip|rar)\.001)", re.I)
LATER_PART = re.compile(r".+(?:\.part0*(?:[2-9]|\d{2,})\.rar)", re.I)
# Inside an unpacked folder of the client data and the song data: the client's patch folder in the game host's folder,
# or in a folder of another name with the songs or the images beside it, or by itself (patch, phone_new: the client
# data alone, known by a client version's folder with the client's Android tables). The same marks as host_folder in
# tools/opendmtq_tools/importer.py.
HOST = "dmqglb.mb.pmang.com"
PATCH_DIR = os.path.join("patch", "phone_new")
GAME_DIR = os.path.join(HOST, PATCH_DIR)
PATCH_NAME = "phone_new"
PATCH_PARENT = "patch"
# The songs alone: their own folder, with their music in Songs/<id>/<id>.fpk.
SONGS_DIR = "DMQ"
CLIENT_VERSION = re.compile(r"\d+(?:\.\d+)+")
# This project's own downloads start with its name: the apps it builds, its Windows bundle. They are none of the game's.
OWN_APPS = "opendmtq"


def candidate_dirs():
    """Folders where people usually save downloads."""
    homes = [os.path.expanduser("~")]
    # Under sudo, ~ is root's home; the downloads are in the invoking user's.
    if os.environ.get("SUDO_USER"):
        homes.append(os.path.expanduser("~" + os.environ["SUDO_USER"]))
    dirs = [os.getcwd()]
    for home in homes:
        dirs += [os.path.join(home, "Downloads"), os.path.join(home, "Desktop")]
    # Under WSL the browser saved them on the Windows side.
    for user in glob.glob("/mnt/c/Users/*"):
        dirs += [os.path.join(user, "Downloads"), os.path.join(user, "Desktop")]
    return [d for d in dict.fromkeys(dirs) if os.path.isdir(d)]


def is_patch_folder(path):
    """True when path is the client's patch folder by what is in it: a client version's folder with its Android tables."""
    try:
        names = os.listdir(path)
    except OSError:
        return False
    return any(CLIENT_VERSION.fullmatch(n) and os.path.isdir(os.path.join(path, n, "android", "table")) for n in names)


def game_folder_kind(path):
    """What path is of the client data and the song data, whatever its name: "whole" with the game host's folder in it,
    the game host's folder itself under any name, or an OpenDMTQ server's content folder (its web/); "alone" for the
    client data alone, the client's patch folder in it by itself (patch/phone_new) or path that folder (patch,
    phone_new); "songs" for the songs alone, their DMQ folder with music in it, in path or path that folder; else
    None."""
    if os.path.isdir(os.path.join(path, GAME_DIR)):
        return "whole"
    # Each folder asked once: the search asks this of every folder it passes.
    patch = os.path.join(path, PATCH_DIR)
    has_patch = os.path.isdir(patch)
    for here, there in ((path, has_patch), (os.path.join(path, "web"), None)):
        if (there if there is not None else os.path.isdir(os.path.join(here, PATCH_DIR))) and (
                os.path.isdir(os.path.join(here, "DMQ")) or os.path.isdir(os.path.join(here, "viewImg"))):
            return "whole"
    # The patch folder alone, by what is in it; path itself looked into only when named as the client names it.
    name = os.path.basename(os.path.normpath(path))
    if ((has_patch and is_patch_folder(patch)) or (name == PATCH_NAME and is_patch_folder(path))
            or (name == PATCH_PARENT and is_patch_folder(os.path.join(path, PATCH_NAME)))):
        return "alone"
    if has_music(os.path.join(path, SONGS_DIR)) or (name == SONGS_DIR and has_music(path)):
        return "songs"
    return None


def has_music(dmq):
    """True when a songs' folder (DMQ) holds the music of at least one song."""
    folder = os.path.join(dmq, "Songs")
    try:
        names = os.listdir(folder)
    except OSError:
        return False
    return any(os.path.isfile(os.path.join(folder, d, d + ".fpk")) for d in names)


def is_game_folder(path):
    """True when path is an unpacked folder of the client data and the song data, whole or part of them
    (game_folder_kind)."""
    return game_folder_kind(path) is not None


def is_archive(name):
    """True for an archive to open: a whole one, or the first part of one in parts."""
    low = name.lower()
    if LATER_PART.fullmatch(low):
        return False
    return low.endswith(ARCHIVES) or bool(FIRST_PART.fullmatch(low))


def named_like_the_game(name):
    """True when a file name carries one of the game's words, in any letter case."""
    low = name.lower()
    return any(word in low for word in GAME_WORDS)


def matches(folder):
    """The game's files directly in folder: clients, archives and unpacked folders of the client data and the song
    data."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    # Each name once in lower case: the suffixes and the game's words are matched without letter case.
    low = {n: n.lower() for n in names}
    # The client data and the song data unpacked, in a folder of any name; not the parts of the game host's folder
    # itself (its patch and DMQ folders are its own, and the whole folder is found from the folder above).
    host_itself = os.path.isdir(os.path.join(folder, PATCH_DIR)) and (os.path.isdir(os.path.join(folder, "DMQ"))
                                                                     or os.path.isdir(os.path.join(folder, "viewImg")))
    trees = [n for n in names if not host_itself and is_game_folder(os.path.join(folder, n))]
    # Archives named like the game's, an archive in parts by its first part.
    archives = [n for n in names if is_archive(n) and named_like_the_game(n) and not low[n].startswith(OWN_APPS)
                and os.path.isfile(os.path.join(folder, n))]
    # Clients: any APK or APK bundle but this server's own apps.
    apks = [n for n in names if low[n].endswith(APPS) and not low[n].startswith(OWN_APPS)
            and os.path.isfile(os.path.join(folder, n))]
    # Beside the client data or the song data any APK may be the client (the import checks each); alone, only one named
    # like the game counts, since Downloads holds other apps too.
    if not (trees or archives):
        apks = [n for n in apks if named_like_the_game(n)]
    return apks + archives + trees


def find():
    """Folders holding game files, best first: [(folder, [names in it])]."""
    found = []
    for d in candidate_dirs():
        # The folder itself and its direct subfolders (a "DMTQ" folder inside Downloads, say).
        try:
            subs = [os.path.join(d, n) for n in os.listdir(d) if os.path.isdir(os.path.join(d, n))]
        except OSError:
            subs = []
        for folder in [d] + subs:
            hits = matches(folder)
            if hits:
                found.append((folder, hits))

    def has_client(hits):
        return any(h.lower().endswith(APPS) for h in hits)

    def files(hits):
        # The client data and the song data beside it (an archive or an unpacked folder: anything but an APK).
        return [h for h in hits if not h.lower().endswith(APPS)]

    def whole(folder, hits):
        # Of them, the whole files: an archive, or a folder with more than the patch folder alone.
        return any(is_archive(h) or game_folder_kind(os.path.join(folder, h)) == "whole" for h in files(hits))

    # A folder with both the client and the whole files (the client data with the song data) first, then with the client
    # and parts of them, then the whole files without a client, then the one with the most of them.
    found.sort(key=lambda f: (not (has_client(f[1]) and whole(*f)), not (has_client(f[1]) and files(f[1])),
                              not whole(*f), -len(f[1])))
    return found
