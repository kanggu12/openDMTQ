"""A report for whoever helps with a problem: one zip with what the launcher and the player wrote, the settings, and this
PC's displays, sound devices, Windows and graphics cards, with what names a person or signs in left out (Help's Save a
report, and OpenDMTQ-cmd.exe --report FILE).

  opendmtq-report-<date>-<time>.zip
    about.txt                     the launcher's and the player's versions, Windows, the graphics cards, when it was
                                  made, and what was left out
    launcher/launcher.log         the launcher's log (and the two before it, .1 and .2)
    player/player.log             the end of the game's log for the current server's app: its last games
    settings/settings.json        the launcher's settings, the sign-ins taken out
    settings/player-settings.txt  the settings file the player reads
    system/displays.txt           each display, its size and its rates, as the launcher's log has them
    system/sound.txt              the sound devices the player plays on, the default marked
    system/connection-test.txt    the last connection test (connection.py), step by step, when there was one

What is left out is replaced by a word in angle brackets wherever it is found, in every file: the Windows user's name
and every path with it (the home folder, the temporary folder), every site ID where the launcher writes one (signed in
with, filled in, typed for a sign-in that failed), every server's address (as written, as host:port, its host, the
address its app is built for, its folder's name here) and its own name (where a server's name stands, and as itself
anywhere else unless it is a word OpenDMTQ writes itself: a server named OpenDMTQ leaves the report's OpenDMTQ alone),
the sign-in cookies, tokens (an API's, a broadcast's upload key, a one-time sign-in link's), this PC's player id (the
game's device id), the words typed in the game, and the name a sound device is named after (Windows names a Bluetooth
headset as its owner's phone named it: "Headphones (Sena's AirPods Pro)", "헤드폰(김세나의 Galaxy Buds2 Pro)").
Servers are left out whether the settings know them or not (a server forgotten since, an address typed that
never answered, the last connection test of any address): by their forms (web addresses, IP addresses, host:port), by
where the launcher writes an address or a name, and each one any file names is left out of all of them. The list of
what was left out, by kind and how often, is in about.txt and is what the window and the command line say after it is
made.
"""

import getpass
import ipaddress
import json
import logging
import os
import platform
import re
import sys
import time
import urllib.parse
import zipfile

from opendmtq_client import __version__, apps, displays, player, removal
from opendmtq_client import state as st

log = logging.getLogger("opendmtq_client")

# The report's name: what it is and when it was made, in lower case as every file OpenDMTQ hands a person.
NAME = "opendmtq-report-%s.zip"
# The most of the game's log taken: its end, the last games (the player adds to one file from game to game).
PLAYER_LOG_TAIL = 512 * 1024
# The kinds of what is left out, in the order the list says them (i18n report.left.<kind>).
KINDS = ("user", "person", "account", "server", "server_name", "cookie", "token", "device", "typed")
# The word each kind is replaced by.
WORDS = {"user": "<user>", "person": "<name>", "account": "<account>", "server": "<server>",
         "server_name": "<server name>", "cookie": "<cookie>", "token": "<token>", "device": "<device id>",
         "typed": "<typed>"}
# Whose a sound device is, where its name says it: the words right before an English possessive ("Sena Kim's AirPods
# Pro", the apostrophe straight or the curly one a phone writes) or the Korean one ("김세나의 Galaxy Buds2 Pro"), from the
# start of the device's own name: the name's start, or inside the brackets Windows puts it in after the kind of output
# ("Headphones (...)"), past the number Windows puts before a second device of the same name ("2- ").
OWNER = (re.compile(r"(?:^|\()\s*(?:\d+- )?(?P<who>[^()<>'’\s][^()<>'’]*?)['’]s(?=\s)"),
         re.compile(r"(?:^|\()\s*(?:\d+- )?(?P<who>[^()<>\s][^()<>]*?)의(?=\s)"))
# A sign-in cookie of the site as the launcher keeps it (server/portal/auth.php: when it ends, the account in hex, the
# signature), and under its name in a header.
COOKIE_VALUE = re.compile(r"\b\d{10}\.(?:[0-9a-f]{2}){3,40}\.[0-9a-f]{64}\b")
COOKIE_NAMED = re.compile(r"(opendmtq_dl=)[^;\s\"']+")
# An API token (odq_ and its id, then its secret), and what names a secret in an address or a JSON answer: a broadcast's
# upload key, a one-time sign-in link's token, a password.
API_TOKEN = re.compile(r"\bodq_[0-9a-f]{12}_[A-Za-z0-9_-]{43}")
SECRET_PARAM = re.compile(r"(?i)\b((?:token|once|key|secret|password|passwd)=)[^&\s\"'<>]+")
SECRET_JSON = re.compile(r"(?i)(\"(?:token|once|secret|password)\"\s*:\s*\")[^\"]*(\")")
# What the player says the game was typed (its text fields: a name, a message), its words left out.
TYPED = re.compile(r"(typed \")(?:[^\"\\]|\\.)*(\")")

# ------------------------------------------------------------------------------------- servers and site IDs by their form
# Every server's address and every site ID is left out by how and where it is written, whatever it is: also those the
# settings no longer know (a server forgotten, an address typed that never answered, an ID typed wrong, the last test of
# an address no settings name), in the logs before this one too.
# An address of the web: its scheme and what names the server (a user before an @, the host, its port); the path after it
# stays, the server's word in the server's place ("<server>/api"). A host's last character is no period (a sentence's).
URL = re.compile(r"(?i)\b(?:https?|wss?)://(?:[^\s/?#@\"'<>]*@)?(?P<host>\[[0-9a-f:.%a-z]*\]|"
                 r"[^\s/?#:\"'<>()\[\]\\,;]*[^\s/?#:\"'<>()\[\]\\,;.])(?::\d{1,5})?")
# An IPv4 address, with its port after a colon (or a dash: an address in a file's or a folder's name); never a part of a
# longer dotted number (a version of five parts) or of a word.
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
IPV4 = re.compile(r"(?<![\w.])%s(?:\.%s){3}(?:[:-]\d{1,5}(?!\d)|(?!\w|\.\w))" % (_OCTET, _OCTET))
# What may be an IPv6 address (bare, or in brackets with its port after them): taken only when it is one, so that neither
# a time of day (07:53:11) nor a name with colons in it is (_ipv6). Its last part may be an IPv4 address, as in IPv6's
# form for one (::ffff:192.0.2.7, which Windows' name lookup can give): taken whole with it, never its first part alone
# (which left the IPv4 address's last three parts in). The IPv4 part first: its first number is hex digits as well; and
# no part of a longer dotted number (a version of five parts), as for IPV4.
IPV6 = re.compile(r"(?i)(?<![\w:.%%])(\[)?((?:[0-9a-f]{0,4}:){2,7}"
                  r"(?:%s(?:\.%s){3}(?!\.?\w)|[0-9a-f]{0,4}(?!\.\d)))"
                  r"(%%[\w.-]+)?(?(1)\](?::\d{1,5})?)(?![\w:])" % (_OCTET, _OCTET))
# A host's name with a dot in it, or localhost, and its port (club.example.test:8443); its last part starts with a letter
# and has two at least (a domain's), so a C file's line (conf.c:5180) is none.
HOST_PORT = re.compile(r"(?i)(?<![\w.@/-])(?P<host>(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z][a-z0-9-]*[a-z0-9]|"
                       r"localhost):\d{1,5}(?!\d)")
# The project's own addresses, where the launcher looks for its updates: the same on every PC and nobody's server, so
# they stay as they are (an update's problem reads better with them).
PUBLIC_HOSTS = ("github.com", "api.github.com", "codeload.github.com", "objects.githubusercontent.com",
                "release-assets.githubusercontent.com")


def _shapes(*patterns):
    """Places in a line where the launcher writes one thing whatever it is: the words before it (group 1) and the thing
    (group 2), in any letter case, ^ and $ at each line's start and end."""
    return tuple(re.compile(p, re.I | re.M) for p in patterns)


# Where a server's address stands, whatever is written there: the command line's arguments as the log's first line of a
# start says them, an address typed in the window that it could not connect to, one an installer brought that is none,
# the launcher's folder of a server's app (servers\<host>-<port>), the phone app's file names (now's and 0.10.0's) and
# the PC client's installer set up for a server (now's and 0.10.0's).
SERVER_AT = _shapes(
    r"(--(?:server|test-server|forget)[ =])([^\s\"']+)",
    r"(\bcould not connect to )([^\n]+?)(?=: )",
    r"(\ban address that is none: )([^\n]+)$",
    r"([\\/]servers[\\/])([^\\/\s\"',;)]+)",
    r"(\bopendmtq-phone-app-[\d.]+-android-)([^\s\\/\"']+?)(?=\.apk\b)",
    r"(\bOpenDMTQ-)([^\s\\/\"']+?)(?=-v[\d.]+\.apk\b)",
    r"(\bopendmtq-pc-client-[\w.]+-windows-x64-setup-)([^\s\\/\"']+?)(?=\.exe\b)",
    r"(\bOpenDMTQ-Setup-)([^\s\\/\"']+?)(?=\.exe\b)")
# Where a server's own name stands: --server's line ("Connected to NAME (address)."), --use-found's ("Moved to NAME
# (address): ..."), a known server's that did not
# answer ("NAME did not answer; playing on it as known (address)."), a server as one line names it (state.label, NAME
# (address)) in --status and its ready check ("server: ...") and in --servers (each line "* " or "  " first, after the
# log's time, level and thread, the name right after: never a blank or a bracket, which the ready check's lines start
# with), and the settings' own fields: a server's name right after its address, and in its app's name the server's in
# brackets ("TECHNIKA Q (NAME)"). A name holds no angle brackets: those are the report's own words.
_IN_BRACKETS = r"(?= \((?:[a-z][a-z0-9+.-]*://|<server>)[^()\n]*\)"
NAME_AT = _shapes(
    r"(\bConnected to )([^<>\n]+?)%s)" % _IN_BRACKETS,
    r"(\bMoved to )([^<>\n]+?)%s)" % _IN_BRACKETS,
    r"(^\S+ \S+ [A-Z]+ \S+ )([^<>\n]+?)(?= did not answer; playing on it as known \()",
    r"(\bserver: )([^<>\n]+?)%s$)" % _IN_BRACKETS,
    r"(^\S+ \S+ [A-Z]+ \S+ [* ] )([^<>\n\[\s][^<>\n]*?)%s$)" % _IN_BRACKETS,
    r"(\"url\"\s*:\s*\"[^\"\n]*\",\s*\"name\"\s*:\s*\")([^\"<>\n]+)(?=\")",
    r"(\"label\"\s*:\s*\"[^\"\n(]*\()([^\"()<>\n]+)(?=\)\")")
# A site ID where it stands in a line: up to a blank or a mark no ID has, and never ending on a period (the sentence's).
_ID = r"[^\s,;:()<>\"']*[^\s,;:()<>\"'.]"
# Where the launcher writes a site ID, whatever it is: a sign-in that failed, with the ID as typed (to the error after
# it), a sign-in's line ("Signed in as player1.", "signed in as player1 on ..."), the command line's --sign-in, an
# installer's ("the ID player1 to sign in with"), --status's ("signed in: player1", "no (player1, ended)"), the ready
# check's ("[ok  ] account: player1"), --records' for an account linked to no player (i18n play.records.unlinked, at
# the log line's start), --play's for the account PLAY linked to this PC's player (status.linked), and the settings'
# fields.
ACCOUNT_AT = _shapes(
    r"(\bcould not sign in to \S+ as )([^\n]+?)(?=: )",
    r"(\bsign(?:ed)?[ -]in(?: to \S+)? as )(%s)" % _ID,
    r"(--sign-in[ =])(%s)" % _ID,
    r"(\bthe ID )(%s)(?= to sign in with)" % _ID,
    r"(\bsigned in: no \()(%s)(?=, ended\))" % _ID,
    r"(\bsigned in: )(?!no(?: \(|$))(%s)" % _ID,
    r"(\] account: )(?!not signed in$)(%s)" % _ID,
    r"(^\S+ \S+ [A-Z]+ \S+ )(%s)(?= is not linked to a player on this server\.)" % _ID,
    r"(\blinked to your site account )(%s)" % _ID,
    r"(\"(?:account|fill)\"\s*:\s*\")([^\"]+)(?=\")")
# The fields of the connection test's lines that name a server or a sign-in, and what each is (_worded).
WORDED = {"account": "account", "name": "server_name", "host": "server"}
# The words that stand for what was left out: never left out again.
LEFT = frozenset(WORDS.values())


def _worded():
    """The connection test's lines as they are worded now (its English words, which the log and the report's copy of the
    last test have), for each field of WORDED in them: (pattern, kind), group 1 the words before the field (the step's
    name and what follows it in the line, when the field opens the words: a colon, or the column's blanks), group 2
    what stands at the field, the words after it ahead. Made from the words themselves, so new words are covered too."""
    from opendmtq_client import connection, i18n
    found = []
    for key, (english, _korean) in sorted(i18n.TEXT.items()):
        if not key.startswith("test."):
            continue
        # Words and fields by turns: words at the even places, field names at the odd ones.
        parts = re.split(r"\{(\w+)\}", english)
        for i in range(1, len(parts), 2):
            kind = WORDED.get(parts[i])
            if kind is None:
                continue
            # The words before the field as they are, the other fields before it as anything on the line.
            before = "".join(re.escape(p) if j % 2 == 0 else r"[^\n]*?" for j, p in enumerate(parts[:i]))
            if not before:
                step = key.split(".")[1]
                if step not in connection.STEPS:
                    # Not a step's line (a verdict): nothing before the field tells where it starts.
                    continue
                before = re.escape(i18n.TEXT["test." + step][0]) + r"(?::\s+|\s{2,})"
            after = parts[i + 1]
            if not after and i + 2 < len(parts):
                # Two fields side by side: no words between them tell where one ends.
                continue
            # The words after it: a period that ends the sentence (an ID may hold one), its words, or the line's end.
            ahead = r"\.(?=\s|$)" if after == "." else re.escape(after) if after else "$"
            # A host has no blank in it; a name or an ID as typed may.
            value = r"[^\s<>]+?" if kind == "server" else r"[^<>\n]+?"
            found.append((re.compile(r"(%s)(%s)(?=%s)" % (before, value, ahead), re.M), kind))
    return found


# What OpenDMTQ writes itself, as one text once it is made (_own_text): a server named as one of its words or phrases
# ("OpenDMTQ", "OpenDMTQ server", "Player") is left out only where a server's name stands.
_OWN = []


def _own_text():
    """OpenDMTQ's own words as one text: the launcher's words in English (its log and its command line say them), the
    report's own lines, its programs' names and the log's levels and thread."""
    if not _OWN:
        from opendmtq_client import i18n
        words = [english for english, _korean in i18n.TEXT.values()]
        words += ["OpenDMTQ report, made", "launcher: player: Windows: graphics:", "INFO WARNING ERROR MainThread",
                  "OpenDMTQ.Client OpenDMTQ.exe OpenDMTQ-cmd.exe OpenDMTQ-Player.exe OpenDMTQ-Setup.exe"]
        _OWN.append("\n".join(words))
    return _OWN[0]


def own_word(name):
    """True when a server's name is a word or a phrase OpenDMTQ writes itself, in any letter case: left out as a word
    wherever it is, such a name would take OpenDMTQ's own words with it ("OpenDMTQ report", "OpenDMTQ 0.11.2 started",
    its programs' folder)."""
    return re.search(r"(?<![\w.-])%s(?![\w-])" % re.escape(name), _own_text(), re.I) is not None


def _ipv6(text):
    """True when `text` is an IPv6 address as people write one: with "::" or all eight parts, and a digit in it (a name
    of hex letters alone, such as face::add, is a program's)."""
    if not ("::" in text or text.count(":") == 7) or not re.search(r"\d", text):
        return False
    try:
        ipaddress.IPv6Address(text)
        return True
    except ValueError:
        return False


class Scrub:
    """What is left out of every file of a report, and how often each kind was found."""

    def __init__(self):
        # (pattern, its replacement, kind, length): the values found on this PC, the longest first.
        self.found = []
        # What was made known already (kind, value in lower case, whole): each once, however often a log has it.
        self.known = set()
        self.counts = dict.fromkeys(KINDS, 0)
        # The connection test's lines, worded as they are now.
        self.worded = _worded()

    def add(self, kind, value, whole=False, case=False):
        """Leave out `value` (a text) as `kind` wherever it is, in any letter case (Windows' paths and names, an
        address's host), or in its own alone with `case`: as a whole word only with `whole`, neither "a1" in "data1" nor
        10.0.0.5 in 110.0.0.5."""
        value = (value or "").strip()
        known = (kind, value if case else value.lower(), whole)
        if len(value) < 2 or value in LEFT or known in self.known:
            # One letter is in every word: nothing that short names anyone; a word of the report's own, or one known.
            return
        self.known.add(known)
        pattern = r"(?<![\w.-])%s(?![\w-])" % re.escape(value) if whole else re.escape(value)
        self.pattern(kind, pattern, WORDS[kind], len(value), flags=0 if case else re.I)

    def name(self, value):
        """A server's own name, left out wherever it is written as itself (a whole word or phrase, in its own letter
        case: as the server gave it), unless OpenDMTQ writes the same word or phrase itself (own_word). Such a name is
        left out only where a server's name stands (NAME_AT, the connection test's lines), as a site ID is."""
        value = (value or "").strip()
        if value and not own_word(value):
            self.add("server_name", value, whole=True, case=True)

    def pattern(self, kind, pattern, word, length, flags=re.I):
        """Leave out what `pattern` (a regular expression, any letter case unless `flags` say otherwise) finds as `kind`,
        replaced by `word` (which may keep the pattern's groups: \\1)."""
        self.found.append((re.compile(pattern, flags), word, kind, length))
        # The longest first: a server's whole address before its host alone.
        self.found.sort(key=lambda item: -item[3])

    def server(self, value):
        """A server's address as found written (an address of the web, host:port, a host, host-port as a folder's or a
        file's name has it, or what was typed for one), left out from now on in every form the launcher writes it: as
        written, as its address, as host:port and host-port, and as its host alone when that is no plain word (it has a
        dot, or is an IP address; a name without a dot is left out with its port, and where its places say it is one)."""
        value = (value or "").strip().strip("'\"").rstrip(".")
        if len(value) < 2 or "<" in value:
            # Nothing, or what the report wrote in its place already.
            return
        # A folder's or a file's name of it: the host and the port with a dash between (apps.key, the app's file).
        dashed = re.fullmatch(r"([^:/\s\[\]]+)-(\d{1,5})", value)
        from opendmtq_client import server as srv
        try:
            url = srv.normalize("%s:%s" % dashed.groups() if dashed else value)
        except srv.ServerError:
            # No address at all: left out where it stands, by its place's shape.
            return
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").strip("[]")
        if not host or host.lower() in PUBLIC_HOSTS:
            return
        port = parts.port or (443 if parts.scheme == "https" else 80)
        shown = "[%s]" % host if ":" in host else host
        forms = {url, "%s:%d" % (shown, port), "%s-%d" % (host, port), apps.key(url)}
        if "." in host or ":" in host:
            # A host with a dot, or an IP address: no word of a log's own, left out wherever it is.
            forms.add(host)
        if any(mark in value for mark in ".:/"):
            forms.add(value)
        for form in forms:
            self.add("server", form, whole=True)

    def learn(self, text):
        """What `text` (a file of the report) says of servers by its forms, made known so that it is left out wherever
        it is, in this file and in the others: each address a web address or a host:port names, what stands where the
        launcher writes an address or a server's name, and the hosts and names of the connection test's lines. Read
        with what is known already left out, so that a place holds only what is new (a known name before " at" and an
        address is no name of its own)."""
        for pattern, word, _kind, _length in self.found:
            text = pattern.sub(word, text)
        for match in URL.finditer(text):
            self.server(match.group(0))
        for match in HOST_PORT.finditer(text):
            self.server(match.group(0))
        for pattern in SERVER_AT:
            for match in pattern.finditer(text):
                self.server(match.group(2))
        for pattern in NAME_AT:
            for match in pattern.finditer(text):
                self.name(match.group(2))
        for pattern, kind in self.worded:
            for match in pattern.finditer(text):
                if kind == "server":
                    self.server(match.group(2))
                elif kind == "server_name":
                    self.name(match.group(2))

    def __call__(self, text):
        """`text` with everything left out, each kind counted: what this PC and the files made known, then what stands
        where an address, a server's name or a site ID is written, then every address by its form, then the secrets."""
        for pattern, word, kind, _length in self.found:
            text = self._sub(pattern, word, kind, text)
        for kind, shapes in (("server", SERVER_AT), ("server_name", NAME_AT), ("account", ACCOUNT_AT)):
            for pattern in shapes:
                text = self._placed(pattern, kind, text)
        for pattern, kind in self.worded:
            text = self._placed(pattern, kind, text)
        text = self._by(URL, lambda m: m.group("host").strip("[]").lower() not in PUBLIC_HOSTS, text)
        text = self._by(IPV6, lambda m: _ipv6(m.group(2)), text)
        text = self._sub(IPV4, WORDS["server"], "server", text)
        text = self._sub(HOST_PORT, WORDS["server"], "server", text)
        text = self._sub(COOKIE_NAMED, r"\1" + WORDS["cookie"], "cookie", text)
        text = self._sub(COOKIE_VALUE, WORDS["cookie"], "cookie", text)
        text = self._sub(API_TOKEN, WORDS["token"], "token", text)
        text = self._sub(SECRET_PARAM, r"\1" + WORDS["token"], "token", text)
        text = self._sub(SECRET_JSON, r"\1" + WORDS["token"] + r"\2", "token", text)
        text = self._sub(TYPED, r"\1" + WORDS["typed"] + r"\2", "typed", text)
        return text

    def _sub(self, pattern, word, kind, text):
        """One pattern replaced, its count added to its kind's."""
        text, n = pattern.subn(word, text)
        self.counts[kind] += n
        return text

    def _placed(self, pattern, kind, text):
        """What stands in a shape's place (its group 2) replaced by its kind's word, the words before it kept; a place
        that holds the report's own word already stays as it is, counted once."""
        def put(match):
            if match.group(2) in LEFT:
                return match.group(0)
            self.counts[kind] += 1
            return match.group(1) + WORDS[kind]
        return pattern.sub(put, text)

    def _by(self, pattern, taken, text):
        """A server's address by its form, replaced where `taken(match)` says it is one, counted as a server's."""
        def put(match):
            if not taken(match):
                return match.group(0)
            self.counts["server"] += 1
            return WORDS["server"]
        return pattern.sub(put, text)

    def left(self):
        """What was left out: [(kind, how many times)], the kinds found, in the list's order."""
        return [(kind, self.counts[kind]) for kind in KINDS if self.counts[kind]]


def _short_path(path):
    """A path in Windows' short form (C:\\Users\\KANGG~1), as the temporary folder may be written; the path itself
    elsewhere, or when Windows says nothing."""
    if sys.platform != "win32":
        return path
    try:
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(path, buffer, len(buffer)):
            return buffer.value
    except (AttributeError, OSError):
        pass
    return path


# A folder of a path: what comes before a name that is one (C:\\Users\\<name>, /home/<name>), and what may follow it.
IN_A_PATH = r"(?<=[\\/])%s(?=[\\/\"'\s,;)]|$)"


def _users(scrub):
    """The Windows user's name, in every path that has it (the home folder and every folder in it, the temporary folder
    in Windows' short form too): replaced where it is a folder's name. Anywhere else it may be a word a log uses
    ("player"), which stays."""
    home = os.path.expanduser("~").rstrip("\\/")
    names = {os.environ.get("USERNAME") or "", os.path.basename(home), os.path.basename(_short_path(home))}
    try:
        names.add(getpass.getuser())
    except (OSError, KeyError, ImportError):
        # No name to be had (no environment for it): the home folder's own name stands for it.
        pass
    for name in names - {""}:
        scrub.pattern("user", IN_A_PATH % re.escape(name), WORDS["user"], len(name))


def _servers(scrub, state):
    """Every server this launcher knows: its address as written, its host and port, its host, the address its app is
    built for and its folder's name here (host-port), its own name (Scrub.name: where a name stands, and as itself
    elsewhere unless it is a word of OpenDMTQ's own). Its site IDs are left out where an ID is written, as every ID is
    (ACCOUNT_AT): a whole word elsewhere may be a word of the logs' own (an ID "player")."""
    for server in state.servers:
        url = server.get("url") or ""
        parts = urllib.parse.urlsplit(url)
        scrub.add("server", url)
        scrub.add("server", parts.netloc, whole=True)
        scrub.add("server", (parts.hostname or "").strip("[]"), whole=True)
        address = str(server.get("address") or "")
        scrub.add("server", address, whole=True)
        # The address in a file's or a folder's name: its colon a dash (the app's file, the server's folder here).
        scrub.add("server", address.replace(":", "-"), whole=True)
        scrub.add("server", apps.key(url) if url else "", whole=True)
        if st.has_own_name(server):
            scrub.name(server.get("name") or "")


def _tested(scrub, tested):
    """The last connection test's own values, left out wherever they are: the address it tested and the one it found the
    server moved to, the host and its addresses it looked up, the server's name it was told."""
    for value in (tested.url, tested.moved):
        scrub.server(value)
    for step in tested.steps:
        params = step.said.params if step.said else {}
        for key in ("url", "host"):
            scrub.server(str(params.get(key) or ""))
        for address in str(params.get("addresses") or "").split(","):
            scrub.server(address)
        name = str(params.get("name") or "") if step.key == "server" else ""
        # A server without a name of its own calls itself by its address: left out as the address it is.
        if name and ("server", name.lower(), True) not in scrub.known:
            scrub.name(name)


def _devices(scrub):
    """This PC's player id in each game's folder (the game's device id, which the server knows the PC by)."""
    for folder in removal.game_folders():
        try:
            with open(os.path.join(folder, removal.ID_FOLDER, removal.ID_FILE), encoding="utf-8-sig",
                      errors="replace") as f:
                found = f.read().strip()
        except OSError:
            continue
        scrub.add("device", found)


def _owners(scrub, devices):
    """The names the sound devices are named after (OWNER), left out wherever such a name stands before its possessive:
    in the list of the devices, and in the player's log where it names the device it opened. Nowhere else: a first name
    may well be a word of the logs' own ("Max", "Will")."""
    for device in devices:
        name = str(device.get("name") or "")
        # The English possessive, then the Korean one, each with what must follow the name for it to be this one.
        for pattern, after in zip(OWNER, (r"(?=['’]s\s)", r"(?=의\s)")):
            for match in pattern.finditer(name):
                who = match.group("who").strip()
                if not who or ("person", who.lower(), after) in scrub.known:
                    # Nothing before the possessive, or a name left out already (a second device of the same owner).
                    continue
                scrub.known.add(("person", who.lower(), after))
                # Never inside a longer word, and only as the device's owner.
                scrub.pattern("person", r"(?<!\w)%s%s" % (re.escape(who), after), WORDS["person"], len(who))


def scrubber(state):
    """What every file of a report leaves out, for this launcher's state on this PC."""
    scrub = Scrub()
    _users(scrub)
    _servers(scrub, state)
    _devices(scrub)
    return scrub


def _settings(text):
    """The launcher's settings without the sign-ins: each server's cookie and when it ends taken out (its address and
    the IDs go as everywhere else)."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    for server in data.get("servers") or []:
        if isinstance(server, dict):
            for key in ("cookie", "expires"):
                if server.get(key):
                    server[key] = WORDS["cookie"]
    return json.dumps(data, indent=2, ensure_ascii=False)


def _read(path, tail=None):
    """A text file as text (None when it is not there), its last `tail` bytes alone when given, from a line's start."""
    try:
        with open(path, "rb") as f:
            if tail:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - tail))
                data = f.read()
                if size > tail:
                    # A line cut by the start is no line: from the next one.
                    data = data.split(b"\n", 1)[-1]
            else:
                data = f.read()
    except OSError:
        return None
    # The player writes UTF-8; Windows' own words may come in its code page: a byte that is not UTF-8 is no reason to fail.
    return data.decode("utf-8-sig", errors="replace")


def windows():
    """Windows as Python's platform module and Windows itself say it: its name, release, build and edition."""
    if sys.platform != "win32":
        return "%s %s (%s)" % (platform.system(), platform.release(), platform.version())
    try:
        release, version, service, _kind = platform.win32_ver()
        edition = platform.win32_edition() or ""
        build = sys.getwindowsversion()
        return "Windows %s %s%s, build %d.%d.%d%s" % (release, edition, " " + service if service else "", build.major,
                                                    build.minor, build.build, " (%s)" % version if version else "")
    except (AttributeError, OSError, ValueError):
        return "Windows (it did not say which)"


def graphics():
    """The graphics cards' names, as Windows lists its display adapters ("NVIDIA GeForce RTX 4090"); [] where it says
    nothing (off Windows, or nothing to ask)."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class Device(ctypes.Structure):
            # DISPLAY_DEVICEW: its size, the output's name, the adapter's own name, flags, ids.
            _fields_ = (("size", wintypes.DWORD), ("name", wintypes.WCHAR * 32), ("string", wintypes.WCHAR * 128),
                        ("flags", wintypes.DWORD), ("id", wintypes.WCHAR * 128), ("key", wintypes.WCHAR * 128))

        user32 = ctypes.WinDLL("user32")
        found, index = [], 0
        # At most a few dozen outputs: the loop ends at the first missing one.
        while index < 64:
            device = Device()
            device.size = ctypes.sizeof(Device)
            if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
                break
            index += 1
            # Each adapter once, whatever the number of its outputs (a card with three displays is one card).
            if device.string and device.string not in found:
                found.append(device.string)
        return found
    except (AttributeError, OSError, ValueError):
        return []


def player_version():
    """The player's version, as its folder says it (player\\bundle.json beside it: its build and when it was made), or
    None without a player."""
    path = player.player_path()
    if not path:
        return None
    try:
        with open(os.path.join(os.path.dirname(path), "bundle.json"), encoding="utf-8-sig") as f:
            made = json.load(f)
        return "%s (built %s)" % (made.get("version") or "?", made.get("built_at") or "?")
    except (OSError, ValueError, AttributeError):
        # A player without its note (a developer's build): there, without a version to say.
        return "beside the launcher, its version not said"


def left_words(w, left):
    """What a report left out (make()'s list of kinds) as one line in the words of `w` (an i18n.Words)."""
    return ", ".join(w("report.left." + kind) for kind, _count in left) or w("report.left.none")


def default_path(now=None):
    """Where Help's Save a report puts it: the user's Downloads folder, under the report's name for this moment."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    return os.path.join(downloads(), NAME % stamp)


def downloads():
    """The user's Downloads folder (Windows' own, wherever it was moved to), else Downloads in the home folder; the
    launcher's own folder where neither is there."""
    if sys.platform == "win32":
        try:
            import ctypes
            import uuid
            from ctypes import wintypes
            # FOLDERID_Downloads, asked of the shell: the folder a person finds downloads in, moved or not.
            folder = uuid.UUID("{374DE290-123F-4565-9164-39C4925E467B}")
            guid = (ctypes.c_byte * 16).from_buffer_copy(folder.bytes_le)
            found = wintypes.LPWSTR()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(found)) == 0:
                path = found.value
                ctypes.windll.ole32.CoTaskMemFree(found)
                if path and os.path.isdir(path):
                    return path
        except (AttributeError, OSError, ValueError):
            pass
    home = os.path.join(os.path.expanduser("~"), "Downloads")
    return home if os.path.isdir(home) else st.config_dir()


def make(state, path=None, devices=None, now=None):
    """The report, written whole or not at all; returns (its path, what was left out: [(kind, how many times)]).
    `devices`: the sound devices when the caller has them (the window's Sound page asked already), else the player is
    asked here (up to its time limit)."""
    path = path or default_path(now)
    scrub = scrubber(state)
    made = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    files = {}
    # The launcher's own log, the two before it too.
    logs = os.path.dirname(st.launcher_log())
    for name in removal.LOG_NAMES:
        text = _read(os.path.join(logs, name))
        if text is not None:
            files["launcher/" + name] = text
    # The game's log for the current server's app: its end, the last games.
    server = state.server()
    game_log = player.app_log(apps.local(server["url"]) if server else None)
    text = _read(game_log, tail=PLAYER_LOG_TAIL) if game_log else None
    if text is not None:
        files["player/player.log"] = text
    # The settings, the sign-ins out of the launcher's.
    text = _read(st.LauncherState.path())
    if text is not None:
        files["settings/settings.json"] = _settings(text)
    text = _read(player.settings_path())
    if text is not None:
        files["settings/player-settings.txt"] = text
    # The displays, as the launcher's log has them at each start, and the sound devices.
    files["system/displays.txt"] = "\n".join(displays.describe(displays.connected())) + "\n"
    listed = devices if devices is not None else player.audio_devices()
    # Whose a device is, where its name says it: left out of every file, this list's first.
    _owners(scrub, listed)
    files["system/sound.txt"] = "".join("%s%s\n    %s\n" % (d["name"], " (default)" if d["default"] else "", d["id"])
                                        for d in listed) or "The player listed no sound devices.\n"
    # The last connection test, as Copy gives it, in English.
    from opendmtq_client import connection, i18n
    tested = connection.last()
    if tested is not None:
        files["system/connection-test.txt"] = tested.text(i18n.Words("en"))
        _tested(scrub, tested)
    # What every file says of servers, made known first: an address or a name one file has is left out of all of them.
    for text in files.values():
        scrub.learn(text)
    # Every file with what is left out taken out, about.txt last: it says what was.
    written = {name: scrub(text) for name, text in files.items()}
    cards = graphics()
    about = ["OpenDMTQ report, made %s" % made, "",
             "launcher: %s" % __version__, "player: %s" % (player_version() or "none beside the launcher"),
             "Windows: %s" % windows(), "graphics: %s" % (", ".join(cards) if cards else "not said"), "",
             "Left out, each replaced by a word in angle brackets:"]
    about += ["  %s %s: %d" % (WORDS[kind], kind, n) for kind, n in scrub.left()] or ["  nothing found to leave out"]
    written["about.txt"] = scrub("\n".join(about) + "\n")
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    part = path + ".part"
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            for name in ["about.txt"] + sorted(n for n in written if n != "about.txt"):
                z.writestr(name, written[name])
        os.replace(part, path)
    finally:
        # Whatever stopped it (a full disk): nothing half made stays under the report's name or beside it.
        if os.path.exists(part):
            os.remove(part)
    left = scrub.left()
    # The launcher's own log names it as it is (a later report leaves the user's name out of that line too).
    log.info("saved a report: %s (left out: %s)", path, ", ".join("%s %d" % (kind, n) for kind, n in left) or "nothing")
    return path, left
