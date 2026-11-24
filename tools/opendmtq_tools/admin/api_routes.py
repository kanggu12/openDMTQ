"""The API's route table: every route of /opendmtq/api/v1 with what it does, what it takes and what it answers. The one
source of the routes api.py registers, of the OpenAPI document it serves (openapi()) and of the reference in docs/api.md
(reference()). The standard library only, and Python 3.9: the repository's checks read it without Flask
(cli/tests/test_repo.py).

Write the reference in docs/api.md again after a change here:

    python3 tools/opendmtq_tools/admin/api_routes.py docs/api.md
"""

import json
import re
import sys

# Where the API is, beside the admin pages (core.API_V1 says the same).
BASE = "/opendmtq/api/v1"

# The marks around the reference in docs/api.md: what is between them is made here.
REFERENCE_START = "<!-- reference: made from tools/opendmtq_tools/admin/api_routes.py -->"
REFERENCE_END = "<!-- reference: end -->"


class Field:
    """A field of a body or an answer: its name, its type, what it is. type: string, integer, number, boolean, object (any
    object), a shape's name, [type] for a list, or {type} for an object of named values. nullable: it may be null.
    optional: it may be left out (a body's field, or an answer's that only some answers have). enum: the values it takes.
    max_length: the most characters a string of a body may have (longer ones are refused, 400 bad_field)."""

    def __init__(self, name, type, doc, nullable=False, optional=False, enum=None, max_length=None):
        self.name, self.type, self.doc, self.nullable, self.optional, self.enum = name, type, doc, nullable, optional, enum
        self.max_length = max_length


class Shape:
    """An object the API answers with: its fields. open: other fields may come with it (the game server's own answer)."""

    def __init__(self, doc, fields, open=False):
        self.doc, self.fields, self.open = doc, fields, open


class Route:
    """One route: its method, its path (after BASE, {name} for a part of it, PARAMS says what each is, unless parts says
    otherwise for this route), the scope a token needs (None: no token), its handler's name in api.py (also its
    operationId), its section, what it does (summary, one sentence; doc, more when there is more to say), its query
    (Fields), its JSON body (Fields), its upload (a multipart field's name and what it is), what it answers (a shape's
    name, with status), or the file it gives (download, its content types: a playlist's route gives its segments too; ranges,
    True where a Range header gets the part it asks for, 206), and the errors it has besides those every route has:
    [(status, code, when)]."""

    def __init__(self, method, path, scope, name, tag, summary, doc="", query=(), body=(), upload=None, answer=None,
                 status=200, download=None, errors=(), parts=None, ranges=False):
        self.method, self.path, self.scope, self.name, self.tag = method, path, scope, name, tag
        self.summary, self.doc, self.query, self.body, self.upload = summary, doc, list(query), list(body), upload
        self.answer, self.status, self.errors, self.parts = answer, status, list(errors), dict(parts or {})
        # A file whose part a broken download may ask for: 206 besides the whole.
        self.ranges = ranges
        # One content type or several: always a list here.
        self.download = [download] if isinstance(download, str) else list(download) if download else None

    def params(self):
        """The names of the path's own parts, in order."""
        return re.findall(r"{(\w+)}", self.path)

    def param(self, name):
        """A part of this route's path: (its type, what it is), this route's own words first."""
        return self.parts.get(name) or PARAMS[name]


# The parts of a path, by their name: their type and what they are.
PARAMS = {
    "job": ("string", "A job's id, as the answer that started it gives it."),
    "file": ("string", "A build's file name, as the list of builds gives it (opendmtq-phone-app-<date>-android-<address>.apk)."),
    "song": ("integer", "A song's id."),
    "player": ("integer", "A player's number (the game's player id, which the site's player.php?id= takes too)."),
    "account": ("string", "An account's ID, in any letter case."),
    "token": ("string", "A token's id (the 12 hex digits after odq_ in the token)."),
    "recording": ("integer", "A recording's id: the moment it began, in seconds since 1970."),
    "part": ("string", "A recording's playlist (index.m3u8) or one of its segments (<n>.ts)."),
    "backup": ("string", "A backup's file name, as the list of backups gives it."),
    "chart": ("integer", "A chart's id (the song list's pattern id)."),
    "item": ("integer", "An item's id, as a player's game state lists it (items)."),
    "webhook": ("integer", "A webhook's id, as the list of webhooks gives it."),
}

# Whether a play was made with the keyboard, which the PC client's player says with its save (the header X-OpenDMTQ-Keys):
# on a play, and on a best for the play that set it. The site marks such a score with a small keyboard.
KEYS_PLAY = "True when it was played with the keyboard of the PC client's player."
KEYS_BEST = "True when the play that set it was played with the keyboard of the PC client's player."

# A player's own token of who a number belongs to (?seen=), for the players' writes.
SEEN = Field("seen", "string", "The player's seen value from the list. When given, the change happens only while the number "
             "still belongs to the same player (409 stale otherwise). A number is never handed out again, but a restore brings "
             "back the backup's players.",
             optional=True)

# The objects the API answers with, by name.
SHAPES = {
    # What every refusal answers, and the jobs.
    "Error": Shape("What every refusal answers.", [
        Field("error", "ErrorBody", "The refusal.")]),
    "ErrorBody": Shape("A refusal.", [
        Field("code", "string", "What went wrong, as a short word (snake_case). Each route lists its own."),
        Field("message", "string", "The same in an English sentence, for a person."),
        Field("nearest", "string", "With 404 cannot_open from GET /setup/folder: the folder the setup's picker opens instead, "
              "the nearest one above that can be read.", optional=True)]),
    "Job": Shape("Work that runs in the background: an app build, an import, a restore, and on the admin pages a backup made, "
                 "a change to the songs, a repair or a deletion of the server's data, and Play on this PC.", [
        Field("id", "string", "Its id, for GET /jobs/{job}."),
        Field("kind", "string", "What it does.", enum=["build", "import", "restore", "backup", "songs", "repair", "delete-data",
                                                       "pc-client"]),
        Field("state", "string", "Where it is.", enum=["running", "done", "failed"]),
        Field("started", "integer", "When it started (Unix time)."),
        Field("log", "[string]", "Its last 200 lines of output."),
        Field("why", "string", "Why it failed, when that can be said in words.", nullable=True),
        Field("host", "string", "A build's address.", optional=True),
        Field("path", "string", "An import's folder or file on the server PC.", optional=True),
        Field("backup", "string", "A restore's backup.", optional=True),
        Field("parts", "[string]", "A deletion's parts of the server's data.", optional=True)]),
    "JobAnswer": Shape("A job.", [Field("job", "Job", "The job.")]),
    "JobList": Shape("The jobs this service keeps.", [Field("items", "[Job]", "The last twenty, and every one running, newest first.")]),
    # The Status page.
    "StatusFacts": Shape("What the status page says.", [
        Field("version", "string", "The version of OpenDMTQ this server runs, when known.", nullable=True),
        Field("address", "string", "The address phones use (PUBLIC_HOST)."),
        Field("instance", "string", "Which run of the admin service answers: it changes when the service starts again."),
        Field("game_server", "GameServer", "How the game server answered just now."),
        Field("counts", "Counts", "The numbers; null while the database cannot be read.", nullable=True),
        Field("recent", "[DashPlay]", "The newest plays."),
        Field("backups", "BackupFacts", "The backups made here."),
        Field("app", "AppFacts", "The app on offer."),
        Field("maintenance", "boolean", "True while the maintenance notice is on."),
        Field("recordings", "integer", "How many recordings are kept, counted with the disk's figures: at most every minute, and "
              "again after one is deleted."),
        Field("disk", "Disk", "The data disk."),
        Field("attention", "[Attention]", "What needs a look, as the status page lists it.")]),
    "GameServer": Shape("The game server's health, as the status page reads it.", [
        Field("answering", "boolean", "True when it answered."),
        Field("ok", "boolean", "True when it answered that all is well."),
        Field("problem", "string", "What it says is wrong, when it answered and is not well.", nullable=True),
        Field("waiting_for_files", "boolean", "True when only the client data is missing: a server being set up."),
        Field("health", "Health", "Its own answer, as /opendmtq/health.php gives it.", nullable=True)]),
    "Health": Shape("The game server's health check (/opendmtq/health.php).", [
        Field("ok", "boolean", "True when the server can serve the game."),
        Field("host", "string", "The address phones use."),
        Field("songs", "integer", "Songs on offer (hidden ones not counted)."),
        Field("game_data", "boolean", "True when the client data is there."),
        Field("patch", "string", "The client data's version the game is told of."),
        Field("database", "boolean", "True when the database can be read."),
        Field("players", "integer", "Players.", nullable=True),
        Field("apk", "object", "The app on offer: file, host, built_at.", nullable=True),
        Field("apk_matches_host", "boolean", "True when that app is for this address.", nullable=True),
        Field("https", "boolean", "True when browsers are sent to HTTPS."),
        Field("role", "string", "api, or assets for a replica that serves files only."),
        Field("writable", "boolean", "True when the database can be written.", nullable=True)], open=True),
    "Counts": Shape("The status page's numbers.", [
        Field("players", "integer", "Players."),
        Field("records", "integer", "Best records: one per player and chart."),
        Field("plays_today", "integer", "Plays in the last 24 hours."),
        Field("plays_week", "integer", "Plays in the last 7 days."),
        Field("active_week", "integer", "Players who played in the last 7 days."),
        Field("live", "integer", "Players on air now (none while broadcasts are off)."),
        Field("broadcasts", "boolean", "True while broadcasts are on for the server (GET /broadcasts).")]),
    "DashPlay": Shape("A play on the status page.", [
        Field("player", "integer", "The player's number."),
        Field("name", "string", "The player's name."),
        Field("song", "string", "The song's title (empty for a chart the server does not list)."),
        Field("chart", "string", "The chart, as the game names it (2LINE Hard 5)."),
        Field("score", "integer", "The score."),
        Field("grade", "string", "The grade."),
        Field("new_record", "boolean", "True when it beat the player's best."),
        Field("keys", "boolean", KEYS_PLAY),
        Field("at", "integer", "When (Unix time).")]),
    "BackupFacts": Shape("The backups, as the status page counts them.", [
        Field("newest", "string", "The newest backup made here (uploaded ones do not count).", nullable=True),
        Field("newest_at", "integer", "When it was made (Unix time).", nullable=True),
        Field("daily", "boolean", "True while the daily backup is on."),
        Field("daily_failure", "string", "Why the last look could not make the daily backup.", nullable=True)]),
    "AppFacts": Shape("The app on offer, as the status page has it.", [
        Field("on_offer", "Build", "The build the site offers.", nullable=True),
        Field("build_error", "string", "Why the last build for this address failed.", nullable=True),
        Field("other_address", "boolean", "True when the app on offer is for another address.")]),
    "Disk": Shape("The data disk.", [
        Field("total", "integer", "Its size (bytes)."),
        Field("used", "integer", "In use (bytes)."),
        Field("free", "integer", "Free (bytes)."),
        Field("parts", "DiskParts", "What takes it.")]),
    "DiskParts": Shape("What takes the data disk (bytes), counted at most every minute: OpenDMTQ's parts, each folder as it is on "
                       "this disk, a file linked twice once; then what is not OpenDMTQ's, and what is free.", [
        Field("recordings", "integer", "Recordings."),
        Field("backups", "integer", "Backups."),
        Field("builds", "integer", "The apps for players and what the builder keeps to make them: the installer for Windows, the runtime "
              "for newer phones, the signing key (data/apk, but the game's client)."),
        Field("songs", "integer", "Added songs."),
        Field("database", "integer", "The database."),
        Field("game", "integer", "The game's files brought in: the client data, the song data and the client (data/content, data/apk/base)."),
        Field("rest", "integer", "The rest of what OpenDMTQ keeps: logs, settings, the site's copies of the jackets, broadcasts on their way."),
        Field("other", "integer", "Everything else on the disk."),
        Field("free", "integer", "Free.")]),
    "Attention": Shape("A thing to look at.", [
        Field("level", "string", "How much it matters.", enum=["warn", "bad"]),
        Field("text", "string", "What it is, in words."),
        Field("link", "string", "The admin page that deals with it, or backup-now: POST /backups makes one.")]),
    "Activity": Shape("What the status page's charts draw.", [
        Field("days", "[DayCount]", "Plays on each of the last 30 days, oldest first, on this server's clock."),
        Field("hours", "[[integer]]", "Plays by weekday (Monday first) and hour (0 to 23), over the last 4 weeks."),
        Field("players", "[PlayerCount]", "Who played most over the last 30 days."),
        Field("songs", "[SongCount]", "The most played songs over the last 30 days."),
        Field("grades", "[GradeCount]", "Best records by grade, S first.")]),
    "DayCount": Shape("A day's plays.", [Field("day", "string", "The day (YYYY-MM-DD)."), Field("plays", "integer", "Plays.")]),
    "PlayerCount": Shape("A player's plays.", [Field("player", "integer", "The player's number."),
                                               Field("name", "string", "The player's name."), Field("plays", "integer", "Plays.")]),
    "SongCount": Shape("A song's plays.", [Field("title", "string", "The song's title."), Field("plays", "integer", "Plays, every chart of it together.")]),
    "GradeCount": Shape("Records at a grade.", [Field("grade", "string", "The grade."), Field("records", "integer", "Best records at it.")]),
    "GradePlays": Shape("Plays at a grade.", [Field("grade", "string", "The grade."), Field("plays", "integer", "Plays at it.")]),
    "Machine": Shape("The machine the server runs on.", [
        Field("cores", "integer", "Processors."),
        Field("uptime", "integer", "Seconds since it started.", nullable=True),
        Field("cpu", "number", "Processor use now (percent), null while measuring.", nullable=True),
        Field("cpu_wait", "number", "The part of it waiting for the disk (percent).", nullable=True),
        Field("memory", "Amount", "Memory (bytes).", nullable=True),
        Field("swap", "Amount", "Swap (bytes).", nullable=True),
        Field("disk", "DiskSize", "The data disk (bytes)."),
        Field("load", "[number]", "The load over 1, 5 and 15 minutes.", nullable=True),
        Field("since", "integer", "Since when the points are kept (Unix time)."),
        Field("points", "[MachinePoint]", "The last day, a point every five minutes.")]),
    "Amount": Shape("An amount and how much of it is in use.", [Field("total", "integer", "All of it."), Field("used", "integer", "In use.")]),
    "DiskSize": Shape("A disk's size.", [Field("total", "integer", "Its size."), Field("used", "integer", "In use."), Field("free", "integer", "Free.")]),
    "MachinePoint": Shape("Five minutes of the machine.", [
        Field("at", "integer", "When (Unix time)."),
        Field("cpu", "number", "Average processor use (percent)."),
        Field("peak", "number", "Highest processor use (percent)."),
        Field("wait", "number", "Waiting for the disk (percent)."),
        Field("mem", "number", "Memory in use (percent).", nullable=True),
        Field("game", "string", "How the game server answered.", enum=["ok", "warn", "bad"])]),
    # The App page, and what a delete answers anywhere.
    "AppOnOffer": Shape("The app players get.", [
        Field("name", "string", "The app's name on phones: TECHNIKA Q (<server name>)."),
        Field("address", "string", "The address it should be built for: this server's."),
        Field("on_offer", "Build", "The build the site offers.", nullable=True),
        Field("state", "string", "What can be said of it: right for this server, a rebuild that failed, or for another address.",
              nullable=True, enum=["fits", "rebuild_failed", "other_address"]),
        Field("says", "string", "The same in words.", nullable=True),
        Field("build_error", "string", "Why the last build for this address failed.", nullable=True),
        Field("icon", "boolean", "True when its icon is kept (GET /app/icon)."),
        Field("windows", "WindowsInstaller", "The installer for Windows (the PC client) that the site offers computers "
              "(GET /app/windows); null on a server without it.", nullable=True),
        Field("building", "Job", "A build running now.", nullable=True)]),
    "WindowsInstaller": Shape("The installer for Windows (the PC client) as the builder keeps it, before the server's address "
                              "goes on its end as it is handed out.", [
        Field("file", "string", "Its file name as kept: OpenDMTQ-Setup.exe."),
        Field("size", "integer", "Its size as kept (bytes); handed out, it is longer by the server's address."),
        Field("sha256", "string", "Its SHA-256 as kept."),
        Field("version", "string", "The OpenDMTQ version it is from; null for a copy put on the server by hand.", nullable=True),
        Field("copied_at", "string", "When the builder put it beside the app (YYYY-MM-DDTHH:MM:SS).")]),
    "PcClientUpdates": Shape("The PC client's updates the site hands to the launchers that play on this server, at /updates/ on "
                             "its one port, as the builder keeps them: those of the installer's version, checked against the "
                             "OpenDMTQ project's signature.", [
        Field("version", "string", "The version they update to; null when the site hands out none (the launchers then look "
              "at GitHub's releases, up to this server's version).", nullable=True),
        Field("files", "[UpdateFile]", "Each file the site hands out: the update feed, the full package, the delta "
              "package, the release's checksums and their signature."),
        Field("full", "string", "The full package's file name.", nullable=True),
        Field("delta", "string", "The delta package's file name; null when there is none.", nullable=True),
        Field("delta_from", "string", "The version the delta package starts from: a launcher of that version downloads it "
              "instead of the full package.", nullable=True),
        Field("signed_by", "string", "The public key (hex) whose signature the checksums carry.", nullable=True),
        Field("source", "string", "Where the builder took them from.", nullable=True,
              enum=["beside the code", "data/apk", "the release"]),
        Field("kept_at", "string", "When the builder put them there (YYYY-MM-DDTHH:MM:SS).", nullable=True),
        Field("refused", "[string]", "What the builder refused of a release, the installer or these updates, each said "
              "in a sentence: a file the OpenDMTQ project did not sign, or any other refusal with the builder's own words "
              "after what it was of. A fetch that only failed is not among them: what was handed out stays.")]),
    "UpdateFile": Shape("One file of the PC client's updates.", [
        Field("file", "string", "Its name, as the release has it and /updates/ hands it out."),
        Field("size", "integer", "Its size (bytes)."),
        Field("sha256", "string", "Its SHA-256.")]),
    "Build": Shape("A build of the app.", [
        Field("file", "string", "Its file name."),
        Field("address", "string", "The address it is built for."),
        Field("built_at", "string", "When it was built, as its manifest says (YYYY-MM-DDTHH:MM:SS)."),
        Field("size", "integer", "Its size (bytes)."),
        Field("sha256", "string", "Its SHA-256, as its manifest says (empty for an older build)."),
        Field("runtime", "string", "The version of the arm32 runtime inside, for phones without 32-bit support.", nullable=True),
        Field("label", "string", "The app's name on phones.", nullable=True),
        Field("on_offer", "boolean", "True for the one the site offers."),
        Field("made_at", "integer", "When the file was written (Unix time).")]),
    "BuildList": Shape("The builds.", [Field("items", "[Build]", "Every build, newest first.")]),
    "BuildAnswer": Shape("A build.", [Field("build", "Build", "The build.")]),
    "Pruned": Shape("What a prune removed.", [Field("deleted", "integer", "Builds deleted."), Field("freed", "integer", "Bytes freed.")]),
    "Deleted": Shape("What was deleted.", [Field("deleted", "string", "Its name or id.")]),
    "Invite": Shape("Where players get the app.", [
        Field("url", "string", "The download page by the address all phones use."),
        Field("qr", "boolean", "True when its QR code is there (GET /invite/qr).")]),
    # The Songs page and the Notices page's maintenance card.
    "Song": Shape("A song on the Songs page.", [
        Field("id", "integer", "Its id."),
        Field("name", "string", "Its key in the song data."),
        Field("title", "string", "Its title."),
        Field("artist", "string", "Its artist."),
        Field("charts", "integer", "Its charts."),
        Field("hidden", "boolean", "True when it is hidden from the game's song list and the site."),
        Field("source", "string", "Where it came from: imported with the song data, or added as a song package.", enum=["imported", "added"]),
        Field("plays", "integer", "Plays over the last 30 days, every chart together."),
        Field("last_played", "integer", "When it was last played (Unix time).", nullable=True)]),
    "SongList": Shape("The Songs page's list.", [
        Field("items", "[Song]", "Every song, imported ones first."),
        Field("client_data", "boolean", "True when the client data is there: without it the game cannot start."),
        Field("tile_failures", "[string]", "Why songs have no picture on their tile in the game's song list.")]),
    "SongAnswer": Shape("A song.", [Field("song", "Song", "The song.")]),
    "SongHidden": Shape("A song hidden or shown.", [
        Field("id", "integer", "Its id."), Field("title", "string", "Its title (its id when it is not listed)."),
        Field("hidden", "boolean", "True when it is hidden now.")]),
    "Notice": Shape("The in-game maintenance notice.", [
        Field("on", "boolean", "True while it is on: players see it and cannot start the game."),
        Field("message", "string", "What it says (empty: the usual words)."),
        Field("change", "integer", "The number of its last change (turned on, a new message, ended), higher with each one; 0 before the "
              "first. The game's notice page is asked for under it, and players in the game are told of each change once."),
        Field("changed_at", "integer", "When that change was made (Unix time); null before the first.", nullable=True)]),
    # The Notices page's notice on the site (notice.py).
    "SiteNotice": Shape("The notice on the site: one line at the top of every page of the players' site, for everyone signed in.", [
        Field("text", "string", "What it says; empty when there is none."),
        Field("shown", "boolean", "True while it is up: there is one, and its end has not come."),
        Field("until", "integer", "When it ends by itself (Unix time); null for no end.", nullable=True),
        Field("set_at", "integer", "When it was set (Unix time); null when there is none.", nullable=True),
        Field("by", "string", "Who set it: the admin, or through the API the admin whose token it was.", nullable=True)]),
    # The Notices page's Discord and Slack (webhooks.py).
    "Webhook": Shape("A chat the server sends messages to, through its webhook.", [
        Field("id", "integer", "Its id."),
        Field("address", "string", "Its address masked: the host and the path, the secret at the path's end as dots and its last four "
              "characters. The whole address never leaves the server but for the chat."),
        Field("kind", "string", "The format its messages take, by its host: Discord's for Discord's hosts, Slack's for every other.",
              enum=["discord", "slack"]),
        Field("language", "string", "The language of its messages.", enum=["en", "ko"]),
        Field("events", "[string]", "What it hears of, in the card's order: live_on (a player starts broadcasting), live_off (their "
              "broadcast ends), chart_top (a new #1 on a song's chart, taken from another player), month_top (a new #1 of the month), "
              "maint_on and maint_off (maintenance begins, ends)."),
        Field("made_by", "string", "Who added it."),
        Field("made_at", "integer", "When it was added (Unix time)."),
        Field("last_sent", "integer", "When its last message went through (Unix time).", nullable=True),
        Field("last_failure", "WebhookFailure", "Its last failure, while nothing went through since.", nullable=True),
        Field("waiting", "integer", "Its messages waiting to be sent (tried again after a failure, or queued just now)."),
        Field("given_up", "integer", "Its messages given up on, not sent within half an hour of what they tell.")]),
    "WebhookFailure": Shape("A message a chat did not take.", [
        Field("at", "integer", "When (Unix time)."),
        Field("code", "string", "What happened: gone (404: no such webhook), refused (401, 403: its address is wrong or no longer "
              "valid), bad (another 4xx: the message refused), limited (429: the chat asked to wait), server (5xx), timeout, "
              "unreachable, redirect (the address leads elsewhere), local (its name leads to the server itself or its network "
              "link's own address).",
              enum=["gone", "refused", "bad", "limited", "server", "timeout", "unreachable", "redirect", "local"]),
        Field("status", "integer", "The chat's HTTP status; null without an answer.", nullable=True),
        Field("message", "string", "The same in a sentence.")]),
    "WebhookList": Shape("The webhooks.", [Field("items", "[Webhook]", "Every one, the first added first.")]),
    "WebhookAnswer": Shape("A webhook.", [Field("webhook", "Webhook", "The webhook.")]),
    "WebhookTest": Shape("A test message sent.", [
        Field("sent", "boolean", "True when the chat took it."),
        Field("status", "integer", "The chat's HTTP status; null without an answer.", nullable=True),
        Field("code", "string", "When it did not go through, what happened, as a failure's code.", nullable=True),
        Field("message", "string", "How it went, in a sentence.")]),
    # The owner's password on the Server page (lifecycle.py).
    "PasswordChanged": Shape("The owner's password changed.", [
        Field("changed", "boolean", "True: the new password works from now on, for the admin pages and the players' site alike."),
        Field("user", "string", "The owner's ID (ADMIN_USER), which signs in with it.")]),
    "Stopping": Shape("A stop asked for.", [Field("stopping", "boolean", "True: the server stops within a few seconds, these pages and the API with it.")]),
    # The Server page.
    "ServerState": Shape("The server as the Server page shows it.", [
        Field("install", "string", "How it is installed.", enum=["windows", "host", "docker", "kubernetes"]),
        Field("address", "string", "Its one address: the players' site, with the admin pages under /opendmtq/admin/ and this API under /opendmtq/api/."),
        Field("version", "string", "Its version.", nullable=True),
        Field("started", "integer", "When the admin service started, with the server (Unix time).", nullable=True),
        Field("runs_itself", "boolean", "True where this API can stop, restart and uninstall the server (a host install, the Windows bundle)."),
        Field("commands", "{string}", "Where it cannot: the command for each action, on the server PC or the cluster. With Docker Compose stop, restart, repair, delete_data, uninstall, port and name; on Kubernetes stop, restart, delete_data, uninstall, port and name; on a host install, which does each through this API, none, or the install's own command for what this API cannot do when its pages were started without the install's run folder or .env."),
        Field("port", "integer", "Its one port, its own: the game, the players' site, the admin pages and this API, the port POST /server/port moves."),
        Field("public_port", "integer", "The port in its address, the one the phones' app calls: the same as port, or another that is forwarded to port (a router's)."),
        Field("name", "string", "Its name in the app's title, TECHNIKA Q (name) on phones (SERVER_NAME): \"\" while it has none, its address naming the app then."),
        Field("app_name", "string", "The app's name on phones now: TECHNIKA Q and the name, or the address while there is none."),
        Field("next_name", "string", "The name it takes at its next start (POST /server/name), when another than now: \"\" for none; null otherwise.", nullable=True),
        Field("next_address", "string", "The address it moves to at its next start (http://host:port/), when it was moved (POST /server/port); null otherwise.", nullable=True),
        Field("moved_from", "integer", "The port it left at its first start with this version: 80, for a server set up on it before 0.11.0 without its owner choosing it, which moved to the port its admin pages had; null for one that never moved.", nullable=True),
        Field("moved", "Moved", "Its last move to another address, which the site's download page tells players of for a month: null otherwise.", nullable=True),
        Field("removes", "[string]", "What Uninstall removes on this install, as the Server page lists it: of folder, firewall, startup, service, link, containers, images, clone and release."),
        Field("data", "[DataPart]", "The server's data, part by part.")]),
    "Moved": Shape("A move of the server to another address.", [
        Field("from", "string", "The address it served before (host:port)."),
        Field("to", "string", "The address it serves now (host:port)."),
        Field("at", "integer", "When its first start there noted it (Unix time).")]),
    "DataPart": Shape("One part of the server's data.", [
        Field("part", "string", "Which part.", enum=["database", "recordings", "songs", "apps", "backups", "logs", "game"]),
        Field("bytes", "integer", "How much it holds."),
        Field("can_delete", "boolean", "True when this API can delete it here (with Docker Compose the game files are the command line's)."),
        Field("command", "string", "Where this API cannot delete it, the command that does on the server PC, with the part's name; \"\" where it can.")]),
    "DataParts": Shape("The server's data.", [Field("items", "[DataPart]", "Every part, in the Server page's order.")]),
    "Renamed": Shape("The server's name in the app's title, from its next start.", [
        Field("name", "string", "The new name: \"\" for none, its address naming the app then."),
        Field("app_name", "string", "The app's name on phones from the next start, when the app is built again with it."),
        Field("from_next_start", "boolean", "True: the server takes it at its next start, and builds the app again with it then.")]),
    "PortMoved": Shape("A move to another port, from the server's next start.", [
        Field("port", "integer", "The new port."),
        Field("address", "string", "The server's address from its next start: the players' site, with the admin pages and this API under it."),
        Field("from_next_start", "boolean", "True: the server answers there from its next start, with the app built again for it.")]),
    "ServerRestarting": Shape("A restart asked for.", [Field("restarting", "boolean", "True: every part stops and starts again within seconds, this API with it."),
        Field("instance", "string", "This run's: GET /status gives another once the new one answers.")]),
    "Uninstalling": Shape("An uninstall asked for.", [
        Field("uninstalling", "boolean", "True: the server stops, then its program removes itself."),
        Field("keep_data", "boolean", "True when the data folder and .env stay.")]),
    # The Players page.
    "Player": Shape("A player on the Players page.", [
        Field("id", "integer", "Their number."),
        Field("name", "string", "Their name as the pages show it (Player <n> until one is set)."),
        Field("nickname", "string", "Their name as they set it (empty until then)."),
        Field("charts", "integer", "Charts they hold a record on."),
        Field("total", "integer", "Their best scores summed."),
        Field("last_played", "integer", "When they last played (Unix time).", nullable=True),
        Field("plays_30_days", "integer", "Plays over the last 30 days."),
        Field("days", "[integer]", "Plays on each of the last 14 days, oldest first."),
        Field("phones", "integer", "Phones they have played on."),
        Field("broadcast", "string", "Their broadcast: off, switched on and waiting for video, on air, or switched on and held while "
              "broadcasts are off for the server.", enum=["off", "waiting", "on_air", "held"]),
        Field("switch", "boolean", "Their own switch (POST or DELETE /players/{player}/live). A player is on air only while it and the "
              "server's (GET /broadcasts, on) are both on; while the server's is off, theirs is kept for then."),
        Field("seen", "string", "Who the number belongs to now: send it as ?seen= with a change.")]),
    "PlayerList": Shape("The players.", [Field("items", "[Player]", "Every player, by number.")]),
    "PlayerAnswer": Shape("A player.", [Field("player", "Player", "The player.")]),
    "PlayerReset": Shape("A player's records reset.", [
        Field("player", "Player", "The player now."), Field("backup", "string", "The backup made first.")]),
    "PlayerDeleted": Shape("A player deleted.", [
        Field("deleted", "integer", "Their number."), Field("backup", "string", "The backup made first.")]),
    # A player's game state (game.py): what the game keeps of them besides their scores.
    "PlayerGame": Shape("A player's game state: the currencies and the level the game's top bar shows, their items, a ban.", [
        Field("player", "integer", "Their number."),
        Field("name", "string", "Their name as the pages show it."),
        Field("mpoint", "integer", "Their MAX POINT, 0 to 99,999,999."),
        Field("qpoint", "integer", "Their Q POINT, 0 to 99,999,999."),
        Field("shown_mpoint", "integer", "The MAX POINT the game is told: 99,999,999 while their currency is unlimited, else mpoint."),
        Field("shown_qpoint", "integer", "The Q POINT the game is told, likewise."),
        Field("unlimited", "boolean", "True while their currency is unlimited: their own switch or the server's (GET /game)."),
        Field("own_unlimited", "boolean", "Their own switch (POST or DELETE /players/{player}/game/unlimited)."),
        Field("level", "integer", "Their level, 1 to 99, worked out of their experience by the game's own table."),
        Field("exp", "integer", "Their experience, 0 to 130,408 (level 99's start)."),
        Field("level_start", "integer", "The experience their level starts at."),
        Field("level_next", "integer", "The experience the next level starts at; null at the top.", nullable=True),
        Field("kept", "boolean", "False while the server keeps nothing of theirs yet: they have what a new player starts with."),
        Field("items", "[GameItem]", "The items a player equips, kind by kind, each with whether they have it."),
        Field("ban", "Ban", "Their ban while it lasts.", nullable=True),
        Field("purchases", "[Purchase]", "What they bought in the game, newest first (20 at most)."),
        Field("seen", "string", "Who the number belongs to now: send it as ?seen= with a change.")]),
    "GameItem": Shape("An item a player equips.", [
        Field("id", "integer", "Its id."),
        Field("kind", "string", "C a character, F an add-on, N a note, K a skin: the four places on the game's top bar.", enum=["C", "F", "N", "K"]),
        Field("name", "string", "Its name, as the client's tables give it."),
        Field("owned", "boolean", "True when the player has it."),
        Field("how", "string", "How they have it: everyone (every player has it), bought, given; empty when they have not.",
              enum=["everyone", "bought", "given", ""])]),
    "Ban": Shape("A ban.", [
        Field("reason", "string", "The owner's reason, which the game shows the player."),
        Field("since", "integer", "When it began (Unix time)."),
        Field("until", "integer", "When it ends (Unix time); null until it is lifted.", nullable=True),
        Field("by", "string", "Who made it: the admin, or the admin and their token's name.")]),
    "Purchase": Shape("A purchase in the game.", [
        Field("at", "integer", "When (Unix time)."),
        Field("product", "integer", "The shop's product."),
        Field("item", "integer", "The item it gave (a pack of MAX POINT its own id)."),
        Field("name", "string", "The item's name."),
        Field("currency", "string", "What its price is in.", enum=["max", "q", "free"]),
        Field("price", "integer", "Its price."),
        Field("paid", "integer", "What was taken: 0 while the player's currency was unlimited.")]),
    "PlayerGameAnswer": Shape("A player's game state.", [Field("game", "PlayerGame", "The player's game state now.")]),
    "PlayerGameReset": Shape("A player's game state reset.", [
        Field("game", "PlayerGame", "The player's game state now."), Field("backup", "string", "The backup made first.")]),
    "BannedPlayer": Shape("A banned player.", [
        Field("id", "integer", "Their number."), Field("name", "string", "Their name."),
        Field("reason", "string", "The owner's reason."), Field("since", "integer", "When the ban began (Unix time)."),
        Field("until", "integer", "When it ends (Unix time); null until it is lifted.", nullable=True),
        Field("by", "string", "Who made it."), Field("seen", "string", "Who the number belongs to now: send it as ?seen= with a change.")]),
    "BanList": Shape("The bans that last.", [Field("items", "[BannedPlayer]", "Every banned player, the newest ban first.")]),
    "GameSettings": Shape("The server's game settings.", [
        Field("unlimited", "boolean", "True while every player's currency is unlimited, whatever their own switch says."),
        Field("start_mpoint", "integer", "The MAX POINT a new player starts with."),
        Field("start_qpoint", "integer", "The Q POINT a new player starts with."),
        Field("start_level", "integer", "The level a new player starts at.")]),
    # The Accounts page: accounts, then tokens.
    "Account": Shape("An account of the site.", [
        Field("name", "string", "Its ID."),
        Field("note", "string", "Whom it is for (admins only see this)."),
        Field("admin", "boolean", "True when it also opens the admin pages."),
        Field("enabled", "boolean", "True when it can sign in."),
        Field("created_at", "integer", "When it was made (Unix time)."),
        Field("signed_in_at", "integer", "When it last signed in (Unix time).", nullable=True),
        Field("player", "integer", "The game player it is linked to.", nullable=True),
        Field("player_name", "string", "That player's name.", nullable=True)]),
    "AccountList": Shape("The accounts.", [
        Field("items", "[Account]", "Every account, by ID."),
        Field("owner", "string", "The owner's ID (ADMIN_USER in .env), which is no account of the list."),
        Field("players", "[PlayerChoice]", "The game's players an account can be linked to.")]),
    "PlayerChoice": Shape("A game player to link to.", [Field("id", "integer", "Their number."), Field("name", "string", "Their name, with the number when two share it.")]),
    "AccountAnswer": Shape("An account.", [Field("account", "Account", "The account.")]),
    "AccountPassword": Shape("An account with its password, shown this once.", [
        Field("account", "Account", "The account."),
        Field("password", "string", "Its password: made by the server, or the one sent."),
        Field("message", "string", "The message to send its player: where to sign in and get the app, the ID and the password.")]),
    "Token": Shape("An API token. Never the token itself.", [
        Field("id", "string", "Its id (the 12 hex digits after odq_ in the token)."),
        Field("name", "string", "What it is for."),
        Field("scope", "string", "What it may do.", enum=["read", "write"]),
        Field("admin", "string", "The admin it belongs to."),
        Field("owner", "boolean", "True for a token of the owner's account (.env)."),
        Field("created_at", "integer", "When it was made (Unix time)."),
        Field("used_at", "integer", "When it was last used (Unix time, to the minute).", nullable=True),
        Field("works", "boolean", "True while its admin can use the admin pages.")]),
    "TokenList": Shape("The tokens.", [Field("items", "[Token]", "Every token, newest first.")]),
    "TokenMade": Shape("A new token.", [
        Field("token", "Token", "The token."),
        Field("secret", "string", "The token to send (odq_...): shown this once, never kept.")]),
    # The Recordings page.
    "Recording": Shape("A recording of a broadcast.", [
        Field("key", "string", "<player>/<id>, as POST /recordings/delete takes it."),
        Field("player", "integer", "The player's number."),
        Field("id", "integer", "Its id: the moment it began (Unix time)."),
        Field("name", "string", "The player's name."),
        Field("started", "integer", "When it began (Unix time)."),
        Field("ended", "integer", "When its last segment came (Unix time); null while it is being made.", nullable=True),
        Field("duration_ms", "integer", "How long it is (milliseconds)."),
        Field("size", "integer", "Its size (bytes)."),
        Field("songs", "[RecordedSong]", "The songs played in it, in order."),
        Field("open", "boolean", "True while it is being made: it cannot be watched, downloaded or deleted yet."),
        Field("hidden", "boolean", "True when players do not see it.")]),
    "RecordedSong": Shape("A song in a recording.", [
        Field("title", "string", "The song's title."),
        Field("chart", "string", "The chart, as the game names it."),
        Field("at", "integer", "When it began (Unix time).", nullable=True)]),
    "RecordingList": Shape("The recordings.", [Field("items", "[Recording]", "Every recording, newest first.")]),
    "RecordingFiles": Shape("A recording and its files.", [
        Field("recording", "Recording", "The recording."),
        Field("files", "[RecordingFile]", "Its playlist and segments, in the playlist's order (none while it is being made).")]),
    "RecordingFile": Shape("A file of a recording.", [Field("name", "string", "Its name (GET .../files/{part})."), Field("size", "integer", "Its size (bytes).")]),
    "RecordingsDone": Shape("What an action on recordings did.", [
        Field("done", "integer", "Recordings it was done to."),
        Field("kept", "integer", "Recordings still being made, which a delete keeps.")]),
    "RecordingAnswer": Shape("A recording.", [Field("recording", "Recording", "The recording.")]),
    "Limits": Shape("The limits the recordings are kept to, and the disk.", [
        Field("cap_gb", "number", "Their total size at most (GB)."),
        Field("days", "integer", "Their age at most (days)."),
        Field("used", "integer", "What they take now (bytes)."),
        Field("cap", "integer", "The total size at most (bytes)."),
        Field("free", "integer", "Free on the disk (bytes)."),
        Field("hours_left", "integer", "About how many hours of broadcast still fit (an hour takes about 1 GB)."),
        Field("deleted", "integer", "Recordings the new limits deleted.", optional=True)]),
    # The Backups page.
    "Backup": Shape("A backup archive.", [
        Field("name", "string", "Its file name."),
        Field("size", "integer", "Its size (bytes)."),
        Field("made", "integer", "When it was made (Unix time)."),
        Field("kind", "string", "How it came to be: the daily backup, uploaded, before a change that cannot be undone, by ./opendmtq deploy, or by hand.",
              enum=["daily", "uploaded", "before", "deploy", "hand"])]),
    "BackupList": Shape("The backups.", [Field("items", "[Backup]", "Every backup, newest first.")]),
    "BackupAnswer": Shape("A backup.", [Field("backup", "Backup", "The backup.")]),
    "DailyBackup": Shape("The daily backup.", [
        Field("on", "boolean", "True while it is on."),
        Field("kept", "[string]", "The daily backups kept, newest first (the latest seven)."),
        Field("next", "integer", "When the next one comes, at the first look after it if the game's data changed (Unix time); null when it is due.", nullable=True),
        Field("failure", "string", "Why the last look could not make one.", nullable=True)]),
    # The Logs page.
    "RequestLog": Shape("The Requests tab.", [
        Field("items", "[Request]", "The newest requests the filters leave, newest first."),
        Field("matched", "integer", "Requests the filters leave."),
        Field("kept", "integer", "Requests read from the log."),
        Field("covered_from", "integer", "Since when the log counts, when only its newest part could be read (Unix time).", nullable=True),
        Field("hours", "[HourCount]", "The last 24 hours of what the filters leave, an hour each, oldest first."),
        Field("top_paths", "[NameCount]", "What was asked for most in those hours."),
        Field("top_devices", "[NameCount]", "By which devices."),
        Field("top_addresses", "[NameCount]", "From which addresses.")]),
    "Request": Shape("A request in the log.", [
        Field("at", "integer", "When (Unix time)."),
        Field("address", "string", "The visitor's address."),
        Field("method", "string", "Its method."),
        Field("path", "string", "What was asked for."),
        Field("status", "integer", "The answer's status."),
        Field("size", "integer", "The answer's size (bytes)."),
        Field("referrer", "string", "The page it came from."),
        Field("agent", "string", "The visitor's user agent."),
        Field("kind", "string", "What it was for.", enum=["game", "files", "app", "site", "live", "admin", "other"]),
        Field("device", "string", "The device, in a word or two."),
        Field("line", "string", "The log's own line.")]),
    "HourCount": Shape("An hour of requests.", [
        Field("at", "integer", "Its start (Unix time)."), Field("fine", "integer", "Requests that went well."),
        Field("failed", "integer", "Requests the server or the game failed (scripts asking for files that are not there do not count).")]),
    "NameCount": Shape("Something and how often.", [Field("name", "string", "What."), Field("requests", "integer", "How often.")]),
    "PlayLog": Shape("The Plays tab.", [
        Field("items", "[LoggedPlay]", "This page of the plays the filter leaves, newest first."),
        Field("total", "integer", "Plays the filter leaves."),
        Field("page", "integer", "This page."),
        Field("pages", "integer", "Pages of 50."),
        Field("players", "[PlayerChoice]", "Those with plays, for the player filter."),
        Field("summary", "PlaysSummary", "What all the plays the filter leaves add up to; null when there are none.", nullable=True)]),
    "LoggedPlay": Shape("A play in the log.", [
        Field("player", "integer", "The player's number."),
        Field("name", "string", "The player's name."),
        Field("song", "string", "The song's title (empty for a chart the server does not list)."),
        Field("chart", "string", "The chart, as the game names it."),
        Field("score", "integer", "The score."),
        Field("grade", "string", "The grade."),
        Field("accuracy", "number", "The accuracy (percent)."),
        Field("new_record", "boolean", "True when it beat the player's best."),
        Field("keys", "boolean", KEYS_PLAY),
        Field("at", "integer", "When (Unix time).")]),
    "PlaysSummary": Shape("What a list of plays adds up to.", [
        Field("plays", "integer", "Plays."),
        Field("records", "integer", "New records among them."),
        Field("accuracy", "number", "Their average accuracy (percent)."),
        Field("players", "integer", "Players."),
        Field("grades", "[GradePlays]", "Plays by grade, S first."),
        Field("days", "[DayCount]", "Plays on each day that has any, oldest first.")]),
    "ChangeList": Shape("The log of changes.", [Field("items", "[Change]", "The latest changes, newest first.")]),
    "Change": Shape("A change made on the admin pages or through the API.", [
        Field("at", "integer", "When (Unix time)."),
        Field("what", "string", "The page and its action, as the log keeps it (accounts_page:create)."),
        Field("words", "string", "The same in words."),
        Field("target", "string", "On whom or what."),
        Field("who", "string", "Who: an admin's ID, with the token's name in brackets for the API.")]),
    # The setup.
    "SetupState": Shape("The setup's four steps.", [
        Field("steps", "SetupSteps", "Each step, true when done."),
        Field("next", "string", "The first step left.", nullable=True, enum=["files", "address", "players", "app"]),
        Field("host_install", "boolean", "True on the server PC's own install: the setup imports from its folders and changes the address."),
        Field("kubernetes", "boolean", "True in Kubernetes."),
        Field("files", "SetupFiles", "The game's files."),
        Field("address", "SetupAddress", "The address."),
        Field("accounts", "integer", "Accounts made."),
        Field("app", "SetupApp", "The app.")]),
    "SetupSteps": Shape("Each step of the setup.", [
        Field("files", "boolean", "The client and all the client data are in."), Field("address", "boolean", "The address is set."),
        Field("players", "boolean", "There is an account."), Field("app", "boolean", "The app on offer is for this address and its last build did not fail.")]),
    "SetupFiles": Shape("The setup's files step.", [
        Field("client", "string", "The client the app is built from (its file name).", nullable=True),
        Field("client_says", "string", "What that client is, in words.", nullable=True),
        Field("unusable", "[string]", "APKs in data/apk/base that are no client to build from."),
        Field("client_data", "boolean", "True when the client data is in."),
        Field("missing", "[string]", "The client data's files the import did not bring."),
        Field("songs", "integer", "Songs on the server."),
        Field("places", "[string]", "Where the setup's folder picker goes in one step: the home folder, Downloads, the Desktop, "
              "Documents and OneDrive's folders, then the drives (a host install only; empty otherwise).")]),
    "SetupAddress": Shape("The setup's address step.", [
        Field("address", "string", "The address phones use."),
        Field("port", "integer", "Its port."),
        Field("choices", "[string]", "This PC's private addresses, the one towards the internet first (a host install only).")]),
    "SetupApp": Shape("The setup's app step.", [
        Field("on_offer", "Build", "The build the site offers.", nullable=True),
        Field("build_error", "string", "Why the last build for this address failed.", nullable=True),
        Field("building", "boolean", "True while a build runs (one of these pages', or the server's own at its start)."),
        Field("client", "boolean", "True when there is a client to build from."),
        Field("runtime", "boolean", "True when the arm32 runtime is there, for phones without 32-bit support."),
        Field("runtime_error", "string", "Why the last try to bring the runtime did not work.", nullable=True),
        Field("qr", "boolean", "True when the download page's QR code is there.")]),
    "FoundList": Shape("The game's files found on the server PC.", [Field("items", "[Found]", "The folders, the most complete first.")]),
    "Found": Shape("A folder with some of the game's files.", [
        Field("path", "string", "The folder."),
        Field("apps", "[string]", "Clients in it (an APK, or a bundle with one)."),
        Field("archives", "[string]", "Archives in it named like the game's, or beside an APK (one in parts by its first part)."),
        Field("iphone", "[string]", "The iPhone app, which is of no use here."),
        Field("folder", "string", "A folder of the client data, with the song data or alone, in it or under it.", nullable=True),
        Field("folder_kind", "string", "What that folder holds.", nullable=True, enum=["whole", "game", "songs"]),
        Field("songs_folder", "string", "A folder of the song data alone.", nullable=True),
        Field("parts", "{integer}", "Each archive in parts, with how many parts there are.")]),
    "Folder": Shape("A folder of the server PC, as the setup's folder picker shows it.", [
        Field("path", "string", "The folder."),
        Field("parent", "string", "The folder above it (null at the top of a drive).", nullable=True),
        Field("folders", "[FolderEntry]", "The folders in it (400 at most)."),
        Field("files", "[FileEntry]", "The game's kinds of file in it (400 at most)."),
        Field("more", "boolean", "True when there were more than 400."),
        Field("folder", "string", "The game's files in it or under it.", nullable=True),
        Field("folder_kind", "string", "What they are.", nullable=True, enum=["whole", "game", "songs"]),
        Field("songs_folder", "string", "The song data alone in it or under it.", nullable=True),
        Field("picked", "string", "The file the path named, when it named a file.", nullable=True),
        Field("places", "[string]", "Where the picker goes in one step, as the setup page shows them: the home folder, Downloads, "
              "the Desktop, Documents and OneDrive's folders, then the drives.")]),
    "FolderEntry": Shape("A folder in a folder.", [Field("name", "string", "Its name."), Field("path", "string", "Its path.")]),
    "FileEntry": Shape("A file in a folder.", [
        Field("name", "string", "Its name."), Field("size", "integer", "Its size (bytes)."), Field("path", "string", "Its path."),
        Field("parts", "integer", "For an archive in parts: how many parts there are (0 otherwise).")]),
    "What": Shape("What a file or folder is to the import.", [
        Field("path", "string", "The path."), Field("ok", "boolean", "True when the import can take it."),
        Field("text", "string", "What it is, in words.")]),
    "Restarting": Shape("A new address, the server starting again for it.", [
        Field("address", "string", "The new address."),
        Field("restarting", "boolean", "True: every program starts again within seconds, and the app is built for the address."),
        Field("instance", "string", "This run of the admin service: GET /status gives another once the new one answers.")]),
    # The players' site, as server/portal shows it.
    "SiteSong": Shape("A song of the players' site.", [
        Field("id", "integer", "Its id (song.php?id=)."),
        Field("name", "string", "Its key in the song data."),
        Field("title", "string", "Its title."),
        Field("artist", "string", "Its artist."),
        Field("genre", "string", "Its genre."),
        Field("jacket", "string", "Its picture's path on the server's address."),
        Field("hidden", "boolean", "True when it is hidden (the site lists only those that are not)."),
        Field("records", "integer", "Records on its charts (players with a record on each).", optional=True)]),
    "SiteSongList": Shape("The site's song list.", [Field("items", "[SiteSong]", "Every song players can see, by title.")]),
    "SiteSongPage": Shape("A song's page on the site.", [
        Field("song", "SiteSong", "The song."),
        Field("credits", "Credits", "Who made it."),
        Field("charts", "[SiteChart]", "Its charts, in the game's order.")]),
    "Credits": Shape("Who made a song.", [
        Field("composed_by", "string", "Composer."), Field("singer", "string", "Singer."), Field("feat_by", "string", "Featuring."),
        Field("arranged_by", "string", "Arranger."), Field("visualized_by", "string", "Its video (BGA).")]),
    "SiteChart": Shape("A chart of a song.", [
        Field("chart", "integer", "Its id (GET /site/charts/{chart}/ranking)."),
        Field("line", "integer", "Its mode: 2, 3 or 4 LINE."),
        Field("difficulty", "string", "Its difficulty.", enum=["Easy", "Normal", "Hard", "Expert"]),
        Field("level", "integer", "Its level."),
        Field("chart_name", "string", "Its name, as the game writes it (2LINE Hard 5)."),
        Field("records", "integer", "Records on it.")]),
    "Board": Shape("A chart's leaderboard.", [
        Field("chart", "integer", "The chart."), Field("song", "integer", "Its song."), Field("title", "string", "Its song's title."),
        Field("chart_name", "string", "Its name."), Field("items", "[BoardPlace]", "The best 100, best first.")]),
    "BoardPlace": Shape("A place on a leaderboard.", [
        Field("place", "integer", "The place."), Field("player", "integer", "The player's number."), Field("name", "string", "The player's name."),
        Field("score", "integer", "The score."), Field("grade", "string", "The grade."), Field("all_combo", "boolean", "An all combo (AC)."),
        Field("perfect_play", "boolean", "A perfect play (PP)."), Field("accuracy", "number", "The accuracy (percent)."),
        Field("keys", "boolean", KEYS_BEST)]),
    "Rankings": Shape("The site's rankings, by a tab.", [
        Field("sort", "string", "The tab.", enum=["total", "s_count", "perfect", "charts"]),
        Field("items", "[Ranked]", "The players with some of what is ranked, in its order.")]),
    "Ranked": Shape("A player of the rankings.", [
        Field("place", "integer", "Their place in this order."),
        Field("rank", "integer", "Their rank by total, among those who played.", nullable=True),
        Field("id", "integer", "Their number."), Field("name", "string", "Their name."),
        Field("charts", "integer", "Charts played (with a record)."), Field("total", "integer", "Best scores summed."),
        Field("s_count", "integer", "S grades."), Field("all_combos", "integer", "All combos."), Field("perfect_plays", "integer", "Perfect plays."),
        Field("accuracy", "number", "Their average accuracy (percent, to the tenth, the half rounded up as the site does)."),
        Field("keys_charts", "integer", "Of their records, those a keyboard play set: the site marks their total with a keyboard when there are any.")]),
    "MonthRankings": Shape("This month's rankings, as the game ranks them.", [
        Field("items", "[MonthPlayer]", "This month's players, best first: the sum of each one's best score per chart this month."),
        Field("starts_anew", "integer", "When the next month begins: the first of the month at midnight UTC (Unix time)."),
        Field("past_months", "[PastMonth]", "The months before, newest first, with their first three (six months back at most).")]),
    "MonthPlayer": Shape("A player of a month.", [
        Field("place", "integer", "Their place.", optional=True), Field("id", "integer", "Their number."), Field("name", "string", "Their name."),
        Field("score", "integer", "Their month's score."), Field("charts", "integer", "Charts they played that month."),
        Field("keys_charts", "integer", "Of those charts, those whose best that month a keyboard play set: the site marks their score with a "
              "keyboard when there are any.")]),
    "PastMonth": Shape("A month before.", [
        Field("month", "string", "The month (YYYY-MM, UTC)."), Field("start", "integer", "Its start (Unix time)."),
        Field("end", "integer", "Its end (Unix time)."), Field("top", "[MonthPlayer]", "Its first three.")]),
    "SitePlayer": Shape("A player's page on the site.", [
        Field("id", "integer", "Their number."), Field("name", "string", "Their name."),
        Field("rank", "integer", "Their rank by total, among those who played.", nullable=True),
        Field("charts", "integer", "Charts with a record."), Field("total", "integer", "Best scores summed."),
        Field("s_count", "integer", "S grades."), Field("all_combos", "integer", "All combos."), Field("perfect_plays", "integer", "Perfect plays."),
        Field("accuracy", "number", "Their average accuracy (percent, to the tenth, the half rounded up as the site does); null with no plays.",
              nullable=True),
        Field("grades", "{integer}", "Their best records by grade, only the grades they have."),
        Field("records", "integer", "Their best records (GET /site/players/{player}/records lists them)."),
        Field("keys_charts", "integer", "Of those records, those a keyboard play set."),
        Field("recent", "[SitePlay]", "Their last 15 plays."),
        Field("activity", "Activity12", "The last 12 weeks, day by day."),
        Field("levels", "[Level]", "Their records by the chart's level."),
        Field("broadcasts", "[PastBroadcast]", "Their newest 4 recordings.")]),
    "Activity12": Shape("The last weeks, as a player's page draws them.", [
        Field("since", "string", "The first day, a Monday (YYYY-MM-DD)."),
        Field("days", "{integer}", "Plays on each day that has any (YYYY-MM-DD).")]),
    "Level": Shape("A player's records at a level.", [
        Field("level", "integer", "The level."), Field("charts", "integer", "The server's charts of that level, of the songs players see (none hidden)."),
        Field("records", "integer", "Their records on them."), Field("grades", "{integer}", "Those records by grade.")]),
    "SitePlay": Shape("A play on the site.", [
        Field("chart", "integer", "The chart."), Field("song", "integer", "Its song.", nullable=True),
        Field("title", "string", "Its song's title.", nullable=True), Field("chart_name", "string", "Its name.", nullable=True),
        Field("score", "integer", "The score."), Field("grade", "string", "The grade."), Field("accuracy", "number", "The accuracy (percent)."),
        Field("new_record", "boolean", "True when it beat the player's best."), Field("keys", "boolean", KEYS_PLAY),
        Field("at", "integer", "When (Unix time)."),
        Field("player", "integer", "The player's number.", optional=True), Field("name", "string", "The player's name.", optional=True),
        Field("best_before", "integer", "The player's best on that chart before it.", nullable=True, optional=True)]),
    "SitePlays": Shape("Plays.", [Field("items", "[SitePlay]", "Newest first.")]),
    "SiteRecords": Shape("A player's best records.", [Field("items", "[SiteRecord]", "Best score first.")]),
    "SiteRecord": Shape("A best record.", [
        Field("chart", "integer", "The chart."), Field("song", "integer", "Its song.", nullable=True),
        Field("title", "string", "Its song's title.", nullable=True), Field("chart_name", "string", "Its name.", nullable=True),
        Field("score", "integer", "The score."), Field("grade", "string", "The grade."), Field("all_combo", "boolean", "An all combo (AC)."),
        Field("perfect_play", "boolean", "A perfect play (PP)."), Field("accuracy", "number", "The accuracy (percent)."),
        Field("keys", "boolean", KEYS_BEST),
        Field("set_at", "integer", "When it was set (null for a record older than the play log).", nullable=True)]),
    "BroadcastSettings": Shape("The server's broadcasts as a whole (the Broadcasts page).", [
        Field("on", "boolean", "True while broadcasts are on: only then do phones and PCs send video and does the site show broadcasts."),
        Field("new_players", "boolean", "True when a new player's switch starts on, from their first play (also while broadcasts are off: "
              "it is kept for then)."),
        Field("quality", "string", "The stream's quality the phones and the PC player are asked for.", enum=["light", "standard", "smooth", "sharp"]),
        Field("qualities", "[BroadcastQuality]", "Every quality, with what it costs."),
        Field("switched_on", "integer", "Players whose own switch is on."),
        Field("on_air", "integer", "Players on air now (none while broadcasts are off).")]),
    "BroadcastQuality": Shape("A quality of the stream.", [
        Field("key", "string", "Its name: light, standard, smooth or sharp."),
        Field("height", "integer", "The picture's height in pixels."), Field("fps", "integer", "Frames a second."),
        Field("bitrate", "integer", "The picture's bitrate (bit/s)."), Field("segment", "integer", "A segment's length (seconds)."),
        Field("hour_bytes", "integer", "What an hour of broadcast takes on the disk, about (bytes)."),
        Field("viewer_bits", "integer", "Each viewer's connection, about (bit/s), picture and sound.")]),
    "SiteLink": Shape("A one-time link that signs a browser in to the players' site.", [
        Field("url", "string", "Its address on the site, after the server's address: it works once, for a minute."),
        Field("account", "string", "The site account it signs in to: the token's admin's own."),
        Field("expires", "integer", "When it stops working (Unix time).")]),
    "SiteLive": Shape("The site's broadcasts.", [
        Field("on", "boolean", "True while broadcasts are on for the server; while off, the site shows none of them."),
        Field("live", "[LiveNow]", "Who is on air now."),
        Field("past", "[PastBroadcast]", "The recordings players may watch, newest first (300 at most)."),
        Field("past_rev", "string", "The sign of `past`, as the site's live page has it (`live.php?list=1`): the first 16 hex digits "
              "of the SHA-256 of its keys in order, joined by commas. It changes when a recording ends, is hidden, shown again or "
              "deleted: a client that keeps the list asks for it again only then.")]),
    "LiveNow": Shape("A player on air.", [
        Field("player", "integer", "Their number (live.php?p=)."), Field("name", "string", "Their name."),
        Field("song", "string", "The song they play, while in one.", nullable=True), Field("chart", "string", "Its chart.", nullable=True),
        Field("seconds", "integer", "How long the broadcast has run.")]),
    "PastBroadcast": Shape("A recording players may watch.", [
        Field("key", "string", "<player>-<id>, as live.php?r= takes it."), Field("player", "integer", "The player's number."),
        Field("name", "string", "The player's name."), Field("started", "integer", "When it began (Unix time)."),
        Field("seconds", "integer", "How long it is."), Field("songs", "[PastSong]", "Its songs, in order.")]),
    "PastSong": Shape("A song in a recording, as the site lists it.", [
        Field("title", "string", "The song's title."), Field("chart", "string", "Its chart."),
        Field("at", "integer", "Seconds into the recording where it begins (-1 when an older recording did not note it)."),
        Field("jacket", "string", "Its picture's path on the server's address.", nullable=True)]),
    "SiteHome": Shape("The site's home page.", [
        Field("app", "HomeApp", "The app on offer.", nullable=True),
        Field("top", "[TopPlayer]", "The best players, eight at most."),
        Field("records", "[SitePlay]", "The newest records."),
        Field("live", "[LiveNow]", "Who is on air now."),
        Field("past", "[PastBroadcast]", "The newest 4 recordings.")]),
    "HomeApp": Shape("The app the site offers.", [
        Field("file", "string", "Its file name."), Field("host", "string", "The address it is built for."),
        Field("built_at", "string", "When it was built."), Field("size", "integer", "Its size (bytes).", nullable=True),
        Field("for_this_address", "boolean", "True when it is for this server's address: only then can players use it.")]),
    "TopPlayer": Shape("A best player.", [Field("id", "integer", "Their number."), Field("name", "string", "Their name."),
                                          Field("total", "integer", "Best scores summed."),
                                          Field("keys_charts", "integer", "Of their records, those a keyboard play set.")]),
}

# Each part of the API, in the order the reference has them.
TAGS = [
    ("Status", "The status page: the game server, the numbers, the machine."),
    ("Jobs", "Work that runs in the background: app builds, imports, restores."),
    ("App", "The App page: the app on offer, its builds, the way players get it."),
    ("Songs", "The Songs page."),
    ("Maintenance", "The Notices page's maintenance card: the in-game notice."),
    # The Notices page's notice on the site (notice.py).
    ("Notice", "The Notices page's notice on the site: one line at the top of every page of the players' site."),
    # The Notices page's Discord and Slack (webhooks.py).
    ("Webhooks", "The Notices page's Discord and Slack card: the chats the server sends messages to."),
    ("Server", "The Server page: the server's state, stopping and restarting it, the repair, its data, and uninstalling it."),
    ("Players", "The Players page."),
    ("Accounts", "The Accounts page: the site's accounts."),
    ("Tokens", "The Accounts page: the API's tokens."),
    ("Broadcasts", "The Broadcasts page's top: broadcasts on or off for the server, and their settings."),
    ("Recordings", "The Broadcasts page's recordings."),
    ("Backups", "The Backups page."),
    ("Logs", "The Logs page: requests, plays, changes."),
    ("Setup", "The setup's four steps."),
    ("Site", "What the players' site shows."),
]

ROUTES = [
    # The Status page (status.py), and the document itself.
    Route("GET", "/openapi.json", None, "openapi", "Status", "This API's OpenAPI 3.1 document. No token: it holds no data.",
          answer="object"),
    Route("GET", "/status", "read", "status", "Status", "What the status page says: the game server, the numbers, the backups, the app, the disk, what needs a look.",
          answer="StatusFacts"),
    Route("GET", "/status/health", "read", "status_health", "Status", "The game server's health, asked now.",
          "200 while it answers that all is well, 503 otherwise: a monitor can go by the status alone.", answer="Health",
          errors=[(503, "server_down", "The game server does not answer."), (503, "server_unwell", "It answers that something is wrong (the message says what).")]),
    Route("GET", "/status/machine", "read", "status_machine", "Status", "The machine's processors, memory, disk and load, now and over the last day.",
          answer="Machine"),
    Route("GET", "/status/activity", "read", "status_activity", "Status", "What the status page's charts draw: plays by day and by hour, who plays most, the most played songs, records by grade.",
          answer="Activity"),
    # The jobs the pages run in the background (jobs.py): what a 202 answer points at.
    Route("GET", "/jobs", "read", "jobs_list", "Jobs", "The jobs this service keeps: its last twenty, and every one running.",
          "Jobs live in the admin service's memory: a restart of it forgets them.", answer="JobList"),
    Route("GET", "/jobs/{job}", "read", "job_get", "Jobs", "One job: whether it runs, is done or failed, its output, why it failed.",
          answer="JobAnswer", errors=[(404, "job_not_found", "No such job (or it was forgotten in a restart).")]),
    # The App page (apps.py): the build on offer, every build, the invite link.
    Route("GET", "/app", "read", "app_get", "App", "The app players get: its build, whether it is right for this server, a build running now.",
          answer="AppOnOffer"),
    Route("GET", "/app/windows", "read", "app_windows", "App", "The installer for Windows as the site hands it to computers, set up "
          "for this server (its address on the installer's end).",
          # A broken download goes on where it stopped, by the same rules as the site's /windows (lib.php, send_download()).
          "Whole, or the part a broken download asks for to go on, as the site hands it out: it says `Accept-Ranges: bytes` and "
          "a strong `ETag`, which covers the server's details on the installer's end as well as the installer. "
          "`Range: bytes=first-last` (or `first-`, or `-count` for the last bytes) asks for one part, answered 206 with its "
          "`Content-Range`; with `If-Range`, only while the ETag is the same (else the whole, 200). `If-Match` with another "
          "ETag is 412. Several parts in one Range get the whole.",
          download="application/vnd.microsoft.portable-executable", ranges=True,
          errors=[(404, "not_found", "This server keeps no installer for Windows."),
                  (412, "precondition_failed", "`If-Match` names another file than this server hands out now (another installer, "
                                               "or other details on its end): download it again from the start."),
                  (416, "range_not_satisfiable", "The part asked for begins past the end; `Content-Range: bytes */length` says the "
                                                 "length.")]),
    # What the site hands the launchers that play here (client_updates.py, apps.pc_updates).
    Route("GET", "/app/windows/updates", "read", "app_windows_updates", "App", "The PC client's updates the site hands out "
          "to the launchers that play on this server, and what the builder refused.",
          "Those of the installer's version, at `/updates/<file>` on the server's one port, with no sign-in: a launcher asks "
          "there before GitHub's releases and takes nothing the OpenDMTQ project did not sign.", answer="PcClientUpdates"),
    Route("POST", "/app/play-here", "write", "app_play_here", "App", "Installs the PC client on the server PC and opens it, as the "
          "App page's Play on this PC does.",
          "From the server PC itself only, on the Windows bundle: the installer this server keeps, set up for this server with "
          "the token's admin's ID on its end, runs with `--silent` for the Windows user the server runs as, and the launcher "
          "opens with this server and that ID filled in to sign in (never a password). With the PC client installed already, "
          "its launcher opens the same way. The job's log says what it did.",
          answer="JobAnswer", status=202,
          errors=[(403, "not_this_pc", "The call does not come from the server PC itself (loopback, or one of its own addresses)."),
                  (404, "not_windows", "The server runs on Linux or macOS, or in Docker: the message says how to play from a "
                                       "Windows PC."),
                  (404, "no_installer", "The PC client is not installed here and this server keeps no installer for Windows."),
                  (409, "busy", "Play on this PC runs already.")]),
    Route("GET", "/app/icon", "read", "app_icon", "App", "The launcher icon of the app on offer, as the builder kept it.",
          download="image/png", errors=[(404, "not_found", "No icon is kept.")]),
    Route("GET", "/builds", "read", "builds_list", "App", "Every build of the app, newest first.", answer="BuildList"),
    Route("POST", "/builds", "write", "builds_start", "App", "Starts a build of the app, as the App page's buttons do.",
          "Without host, for this server's address: the build the site then offers. With another address, a build kept for download "
          "that the site does not offer (for a test on another network).",
          body=[Field("host", "string", "The address to build for, as typed or pasted from a browser (host or host:port). Empty or left out: this server's.", optional=True)],
          answer="JobAnswer", status=202,
          errors=[(400, "bad_host", "Not an address."), (409, "build_running", "A build runs already."),
                  (409, "busy", "An import runs, or the server's own build at its start (the message says which)."),
                  (409, "no_client", "No client to build from in data/apk/base.")]),
    Route("GET", "/builds/{file}", "read", "build_get", "App", "One build.", answer="BuildAnswer",
          errors=[(404, "build_not_found", "No such build.")]),
    Route("GET", "/builds/{file}/download", "read", "build_download", "App", "One build's APK.",
          download="application/vnd.android.package-archive", errors=[(404, "not_found", "No such build.")]),
    Route("DELETE", "/builds/{file}", "write", "build_delete", "App", "Deletes a build.", answer="Deleted",
          errors=[(404, "build_not_found", "No such build."), (409, "on_offer", "It is the one the site offers.")]),
    Route("POST", "/builds/prune", "write", "builds_prune", "App", "Deletes every build but the one the site offers.", answer="Pruned",
          errors=[(409, "build_running", "A build runs."), (409, "offer_unknown", "It cannot be told which build is on offer.")]),
    Route("GET", "/invite", "read", "invite_get", "App", "The download page by the address all phones use, as the message to a new player has it.",
          answer="Invite"),
    Route("GET", "/invite/qr", "read", "invite_qr", "App", "The download page's QR code.", download="image/svg+xml",
          errors=[(404, "not_found", "No QR code yet: the builder makes it with the app.")]),
    # The Songs page (song_pages.py).
    Route("GET", "/songs", "read", "songs_list", "Songs", "Every song, hidden ones too, with where it came from and its plays.",
          answer="SongList"),
    Route("POST", "/songs", "write", "songs_add", "Songs", "Adds a song package (a .zip, 300 MB at most).",
          "Its files are checked before the song is added, as on the Songs page ([songs.md](songs.md)).",
          upload=("package", "The song package (.zip)."), answer="SongAnswer", status=201,
          errors=[(400, "no_package", "No .zip in the package field."), (413, "too_large", "Over 300 MB."),
                  (422, "package_refused", "A file of it fails its checks (the message says which, and why)."),
                  (500, "song_action_failed", "It could not be added for another reason (the message says why).")]),
    Route("GET", "/songs/{song}", "read", "song_get", "Songs", "One song.", answer="SongAnswer",
          errors=[(404, "song_not_found", "No such song.")]),
    Route("POST", "/songs/{song}/hide", "write", "song_hide", "Songs", "Hides a song from the game's song list and the site.",
          "Phones get the new list at their next start.", answer="SongHidden",
          errors=[(404, "song_not_found", "No such song."), (500, "song_action_failed", "The song list could not be made with it (nothing changed).")]),
    Route("POST", "/songs/{song}/show", "write", "song_show", "Songs", "Shows a hidden song again.",
          "A song that is not there is no error: its old flag is taken away.", answer="SongHidden",
          errors=[(500, "song_action_failed", "The song list could not be made with it (nothing changed).")]),
    Route("DELETE", "/songs/{song}", "write", "song_remove", "Songs", "Removes an added song. The game's own songs can only be hidden.",
          answer="Deleted",
          errors=[(404, "song_not_found", "No such song."), (409, "not_added", "One of the game's own songs."),
                  (500, "song_action_failed", "The song list could not be made without it.")]),
    # The Notices page's maintenance card: the notice (song_pages.set_notice).
    Route("GET", "/maintenance", "read", "maintenance_get", "Maintenance", "The in-game maintenance notice: on or off, and what it says.",
          answer="Notice"),
    Route("PUT", "/maintenance", "write", "maintenance_set", "Maintenance", "Turns the notice on, or changes what it says while it is on.",
          "Players then see it when the game starts, and cannot play; the site shows it too. A player already in the game is told "
          "between songs, and told again with each new message.",
          body=[Field("message", "string", "What it says, 200 characters at most (a line break is one). Empty or left out: the usual words.",
                      optional=True)], answer="Notice",
          errors=[(400, "message_too_long", "The message is longer than 200 characters.")]),
    Route("DELETE", "/maintenance", "write", "maintenance_clear", "Maintenance", "Turns the notice off.",
          "Players in the game who were told of it are told between songs that it is over.", answer="Notice"),
    # The Notices page's notice on the site (notice.py).
    Route("GET", "/notice", "read", "notice_get", "Notice", "The notice on the site: what it says, whether it is up, when it ends.",
          answer="SiteNotice"),
    Route("PUT", "/notice", "write", "notice_set", "Notice", "Puts the notice up, or gives it new words or a new end.",
          "Everyone signed in sees it at the top of every page of the site at once. A visitor who closed it sees it again on "
          "their next visit, and when its words change. Its whitespace, line breaks too, becomes single spaces.",
          body=[Field("text", "string", "What it says: one line of up to 200 characters."),
                Field("until", "integer", "When it ends by itself (Unix time). Null or left out: no end.", nullable=True, optional=True)],
          answer="SiteNotice",
          errors=[(400, "notice_empty", "No words, or only spaces."),
                  (400, "notice_too_long", "Longer than 200 characters."),
                  (400, "notice_not_text", "Characters that cannot be shown (control or formatting characters)."),
                  (400, "notice_end_past", "The end has come already."),
                  (400, "notice_end_far", "The end is more than ten years away.")]),
    Route("DELETE", "/notice", "write", "notice_clear", "Notice", "Takes the notice down.",
          "No notice to take down is no error: the answer says there is none.", answer="SiteNotice"),
    # The Notices page's Discord and Slack (webhooks.py).
    Route("GET", "/webhooks", "read", "webhooks_list", "Webhooks", "Every chat the server sends messages to, with how its last message went.",
          answer="WebhookList"),
    Route("POST", "/webhooks", "write", "webhooks_add", "Webhooks", "Adds a webhook, as the card's Add does.",
          "Its chat hears of what it takes from the next look on (every few seconds), nothing of what happened before.",
          body=[Field("url", "string", "The webhook's address, http or https (Discord's or Slack's, or any chat that takes Slack's).",
                      max_length=1000),
                Field("language", "string", "The language of its messages. Left out: English.", optional=True, enum=["en", "ko"]),
                Field("events", "[string]", "What it hears of (Webhook's events). Left out: all of them.", optional=True)],
          answer="WebhookAnswer", status=201,
          errors=[(400, "bad_url", "No address of a webhook: another scheme, a name or password in it, spaces, too long, Discord's "
                   "ending for GitHub's events, or the server itself or its network link's own address (loopback, link-local)."),
                  (400, "bad_events", "No events, or one this server does not know."),
                  (409, "webhook_taken", "A webhook with that address is here already.")]),
    Route("PUT", "/webhooks/{webhook}", "write", "webhook_set", "Webhooks", "Changes what a webhook hears of and its language, as the card's Save does.",
          body=[Field("language", "string", "The language of its messages.", optional=True, enum=["en", "ko"]),
                Field("events", "[string]", "What it hears of.", optional=True)],
          answer="WebhookAnswer",
          errors=[(404, "webhook_not_found", "No such webhook."), (400, "bad_events", "No events, or one this server does not know.")]),
    Route("DELETE", "/webhooks/{webhook}", "write", "webhook_delete", "Webhooks", "Deletes a webhook, and its messages waiting.",
          answer="Deleted", errors=[(404, "webhook_not_found", "No such webhook.")]),
    Route("POST", "/webhooks/{webhook}/test", "write", "webhook_test", "Webhooks", "Sends a test message now, as the card's Send a test does.",
          "It waits for the chat's answer (five seconds at most) and says how it went; the webhook's last result is this one's.",
          answer="WebhookTest", errors=[(404, "webhook_not_found", "No such webhook.")]),
    # The Server page (lifecycle.py): the state, stop and restart (setup.stop_server, lifecycle.restart_server), the repair,
    # the data, the uninstall.
    Route("GET", "/server", "read", "server_get", "Server", "The server as the Server page shows it: how it is installed, its address, "
          "what this API can do with it there, and its data part by part.", answer="ServerState"),
    Route("POST", "/server/stop", "write", "server_stop", "Server", "Stops the server, as the Server page's Stop the server does.",
          "A host install and the Windows bundle only. Every part stops, these pages and the API too: the answer comes first.",
          answer="Stopping", status=202,
          errors=[(404, "host_only", "Not a host install: stop it with ./opendmtq down or Kubernetes."),
                  (500, "stop_failed", "The stop could not be asked for (the message says why).")]),
    Route("POST", "/server/restart", "write", "server_restart", "Server", "Restarts the server, as the Server page's Restart does.",
          "A host install and the Windows bundle only. Every part stops and starts again with the settings in .env as they are "
          "now, the API too: the answer comes first, and `GET /status` answers again within seconds.",
          answer="ServerRestarting", status=202,
          errors=[(404, "host_only", "Not a host install: ./opendmtq restart, or Kubernetes' rollout restart."),
                  (500, "restart_failed", "The restart could not be asked for (the message says why).")]),
    Route("POST", "/server/port", "write", "server_port", "Server", "Moves the server to another port, as the Server page's Move to this port does.",
          "A host install and the Windows bundle only. LISTEN_PORT and the port in PUBLIC_HOST in .env: the server answers there from its "
          "next start (POST /server/restart makes it now), when the app is built again for the new address and the site's download page "
          "tells players to install it over the old one.",
          body=[Field("port", "integer", "The new port, 1 to 65535.")], answer="PortMoved",
          errors=[(400, "bad_port", "Not a port from 1 to 65535."),
                  (409, "same_port", "The server is on that port already."),
                  (409, "port_taken", "Another program holds that port on this computer."),
                  (409, "port_not_allowed", "This computer keeps that port from the user the server runs as (below 1024)."),
                  (409, "by_command", "Docker Compose or Kubernetes: the command line moves the server (the message names the command).")]),
    Route("POST", "/server/name", "write", "server_name", "Server", "Changes the server's name in the app's title, as the Server page's Change the name does.",
          "A host install and the Windows bundle only. SERVER_NAME in .env: the server takes it at its next start (POST /server/restart makes "
          "it now), when the app is built again with it. Phones keep working with the app they have, which calls the same address. With "
          "Docker Compose `./opendmtq name <name>` changes it, on Kubernetes the chart's serverName (the refusal names the command).",
          body=[Field("name", "string", "The new name: at most 80 characters, without quotes, $, #, \\ or `. Empty: the address names the app.", max_length=80)],
          answer="Renamed",
          errors=[(400, "bad_name", "Longer than 80 characters, with a character that cannot be printed, or with a quote, $, #, \\ or `."),
                  (409, "same_name", "The server has that name from its next start already."),
                  (409, "by_command", "Docker Compose or Kubernetes: the command line changes it (the message names the command)."),
                  (500, "name_failed", ".env could not be written: nothing changed.")]),
    Route("POST", "/server/password", "write", "server_password", "Server", "Changes the owner's password, as the Server page's Change the password does.",
          "A host install and the Windows bundle, with a token of the owner's own: ADMIN_PASSWORD in .env, taken at once by the "
          "admin pages and this API (the owner's tokens keep working), the owner's sign-in for the players' site written again "
          "with it, and every sign-in of the owner's made with the old one ended. With Docker Compose `./opendmtq password` "
          "changes it, on Kubernetes the Secret (the refusal names the commands).",
          body=[Field("password", "string", "The new password: 10 to 64 characters, without spaces, quotes, $, #, \\ or `.", max_length=64)],
          answer="PasswordChanged",
          errors=[(400, "missing_password", "No password."),
                  (400, "bad_password", "Not 10 to 64 characters, or with a space, a quote, $, #, \\ or `."),
                  (403, "owner_only", "The token is not the owner's: only the owner changes the owner's password."),
                  (409, "by_command", "Docker Compose or Kubernetes: the command line changes it (the message names the commands)."),
                  (500, "password_failed", ".env or the players' site's copy of the password could not be written: nothing changed (the message says which).")]),
    Route("POST", "/server/repair", "write", "server_repair", "Server", "Checks and repairs the server, as the Server page's Check and repair does.",
          "Its folders, the database's integrity, the owner's sign-in for the players' site, the song list, the site's look kept here, "
          "the phone app (built again when it is missing or for another address) and the program's own files against the install's "
          "list of them. The job's log says what each step found and did.",
          answer="JobAnswer", status=202,
          errors=[(409, "busy", "An import or an app build runs (the message says which).")]),
    Route("GET", "/server/data", "read", "server_data_get", "Server", "The server's data, part by part, with how much each holds.",
          answer="DataParts"),
    Route("POST", "/server/data/delete", "write", "server_data_delete", "Server", "Deletes parts of the server's data, as the Server page's Delete does.",
          "A backup comes first unless `backup` is false, and stays whatever else goes. The database keeps its tables and the API's "
          "tokens, and a recording still being made stays. The job's log says what went.",
          body=[Field("parts", "[string]", "The parts to delete: any of database, recordings, songs, apps, backups, logs, game."),
                Field("backup", "boolean", "Make a backup first (default true).", optional=True),
                Field("confirm", "string", "The word that confirms it: delete.")],
          answer="JobAnswer", status=202,
          errors=[(400, "no_parts", "No part, or none this server has (the message says which ones there are)."),
                  (400, "not_confirmed", "confirm is not the word."),
                  (409, "busy", "An import or an app build runs (the message says which).")]),
    Route("POST", "/server/uninstall", "write", "server_uninstall", "Server", "Uninstalls the server, as the Server page's Uninstall does.",
          "A host install and the Windows bundle only. The server stops, then its program removes itself: the folder (all but data/ "
          "and .env with keep_data), and what it set up on the computer. The answer comes first; nothing answers afterwards.",
          body=[Field("keep_data", "boolean", "Keep the data folder and .env (default false).", optional=True),
                Field("confirm", "string", "The word that confirms it: uninstall.")],
          answer="Uninstalling", status=202,
          errors=[(400, "not_confirmed", "confirm is not the word."),
                  (404, "host_only", "Not a host install: ./opendmtq uninstall, or helm uninstall."),
                  (500, "uninstall_failed", "The uninstall could not be asked for (the message says why).")]),
    # The Players page (players.py). The writes take ?seen= as the page's forms send it.
    Route("GET", "/players", "read", "players_list", "Players", "Every player, with how they have been playing and their broadcast.",
          answer="PlayerList"),
    Route("GET", "/players/download", "read", "players_download", "Players", "Every player as a spreadsheet (CSV, UTF-8).",
          download="text/csv"),
    Route("GET", "/players/{player}", "read", "player_get", "Players", "One player.", answer="PlayerAnswer",
          errors=[(404, "player_not_found", "No such player.")]),
    Route("POST", "/players/{player}/rename", "write", "player_rename", "Players", "Renames a player, on every phone of theirs.",
          query=[SEEN], body=[Field("name", "string", "The new name. The Players page cuts a longer one; here it is refused. "
                                     "Empty: Player <n> again.", max_length=20)], answer="PlayerAnswer",
          errors=[(400, "bad_field", "A name over 20 characters."), (404, "player_not_found", "No such player."),
                  (409, "stale", "The number belongs to someone else now."), (409, "same_name", "That is the name already.")]),
    Route("POST", "/players/{player}/reset", "write", "player_reset", "Players", "Resets a player's records: their scores, plays and achievements.",
          "A backup is made first; without it nothing changes.", query=[SEEN], answer="PlayerReset",
          errors=[(404, "player_not_found", "No such player."), (409, "stale", "The number belongs to someone else now."),
                  (500, "backup_failed", "The backup could not be made (the message says why).")]),
    Route("DELETE", "/players/{player}", "write", "player_delete", "Players", "Deletes a player, with their records, broadcast, recordings and "
          "game sign-ins; their number is never handed out again.",
          "A backup is made first; without it nothing changes.", query=[SEEN], answer="PlayerDeleted",
          errors=[(404, "player_not_found", "No such player."), (409, "stale", "The number belongs to someone else now."),
                  (500, "backup_failed", "The backup could not be made (the message says why).")]),
    Route("POST", "/players/{player}/live", "write", "player_live_on", "Players", "Turns a player's broadcast on.",
          "The phone gets a new upload key and a notice between songs that says so; while broadcasts are off for the server, the notice says "
          "the broadcast starts once they are on ([live.md](live.md)).", query=[SEEN], answer="PlayerAnswer",
          errors=[(404, "player_not_found", "No such player."), (409, "stale", "The number belongs to someone else now.")]),
    Route("DELETE", "/players/{player}/live", "write", "player_live_off", "Players", "Turns a player's broadcast off.",
          "The phone's next upload is refused, the live window goes at once and the recording is closed and kept. The player gets a "
          "notice between songs that says so, also while broadcasts are off for the server ([live.md](live.md)).", query=[SEEN],
          answer="PlayerAnswer",
          errors=[(404, "player_not_found", "No such player."), (409, "stale", "The number belongs to someone else now.")]),
    # A player's own page: their game state (game.py). The writes take ?seen= as the page's forms send it.
    Route("GET", "/players/{player}/game", "read", "player_game_get", "Players", "A player's game state: currencies, level, items, ban, purchases.",
          answer="PlayerGameAnswer", errors=[(404, "player_not_found", "No such player.")]),
    Route("POST", "/players/{player}/game/currency", "write", "player_game_currency", "Players",
          "Sets a player's MAX POINT or Q POINT, or adds to it or takes from it.",
          "Within what the game's top bar shows: 0 to 99,999,999 after the change. The game shows it at its next look at the "
          "player's state: after a song, a purchase, or its next start.", query=[SEEN],
          body=[Field("currency", "string", "Which: max (MAX POINT) or q (Q POINT).", enum=["max", "q"]),
                Field("how", "string", "set it to amount, add amount, or take amount.", enum=["set", "add", "take"]),
                Field("amount", "integer", "0 to 99,999,999 (not 0 to add or take).")], answer="PlayerGameAnswer",
          errors=[(400, "bad_amount", "An amount outside 0 to 99,999,999, or 0 to add or take."),
                  (400, "too_much", "The change would go past 99,999,999."), (400, "too_little", "They hold less than amount."),
                  (404, "player_not_found", "No such player."), (409, "stale", "The number belongs to someone else now.")]),
    Route("POST", "/players/{player}/game/unlimited", "write", "player_game_unlimited_on", "Players", "Makes a player's currency unlimited.",
          "The game is told they have 99,999,999 of each; a purchase or a chart that costs MAX POINT takes nothing, and the "
          "purchase is kept as usual. Their own balance stays as it is underneath.", query=[SEEN], answer="PlayerGameAnswer",
          errors=[(404, "player_not_found", "No such player."), (409, "stale", "The number belongs to someone else now.")]),
    Route("DELETE", "/players/{player}/game/unlimited", "write", "player_game_unlimited_off", "Players",
          "Turns a player's own unlimited currency off: the game shows their own balance again.",
          "While the server's is on (GET /game), their currency stays unlimited.", query=[SEEN], answer="PlayerGameAnswer",
          errors=[(404, "player_not_found", "No such player."), (409, "stale", "The number belongs to someone else now.")]),
    Route("POST", "/players/{player}/game/level", "write", "player_game_level", "Players", "Sets a player's level or their experience.",
          "A level sets the experience to that level's start, as the game's own table has it; an experience sets the level it "
          "falls in. One of the two.", query=[SEEN],
          body=[Field("level", "integer", "1 to 99.", optional=True), Field("exp", "integer", "0 to 130,408.", optional=True)],
          answer="PlayerGameAnswer",
          errors=[(400, "level_or_exp", "Both or neither of level and exp."), (400, "bad_level", "A level outside 1 to 99."),
                  (400, "bad_exp", "An experience outside 0 to 130,408."), (404, "player_not_found", "No such player."),
                  (409, "stale", "The number belongs to someone else now.")]),
    Route("POST", "/players/{player}/game/items/{item}", "write", "player_game_give", "Players", "Gives a player an item they equip.",
          "A character, an add-on, a note or a skin (the items of GET /players/{player}/game). The game lists it as theirs in "
          "MY PAGE and the shop from its next look.", query=[SEEN], answer="PlayerGameAnswer",
          errors=[(404, "item_not_found", "No such item to give."), (404, "player_not_found", "No such player."),
                  (409, "stale", "The number belongs to someone else now.")]),
    Route("DELETE", "/players/{player}/game/items/{item}", "write", "player_game_take", "Players", "Takes an item from a player.",
          "Equipped, it is unequipped too: the game shows its own default in its place.", query=[SEEN], answer="PlayerGameAnswer",
          errors=[(404, "item_not_found", "No such item to take."), (404, "player_not_found", "No such player."),
                  (409, "stale", "The number belongs to someone else now.")]),
    Route("POST", "/players/{player}/ban", "write", "player_ban", "Players", "Bans a player, with a reason and an end.",
          "The game refuses their sign-in and every request of theirs with its own Network connection error, and OpenDMTQ's notice over "
          "the game shows the reason (and the end): within seconds of the ban, in a song too, and at each request refused after (the PC "
          "client keeps it up while the ban lasts); the site and the PC client refuse their accounts, and their broadcast ends. A ban "
          "there already is replaced. The end: days from now, or until (Unix time); neither, until it is lifted.", query=[SEEN],
          body=[Field("reason", "string", "Why, as the game shows it to the player.", max_length=200),
                Field("days", "integer", "Days from now, 1 to 3,650; 0 (as when left out without until): until it is lifted.", optional=True),
                Field("until", "integer", "When it ends (Unix time, to come, within 3,650 days).", optional=True)], answer="PlayerGameAnswer",
          errors=[(400, "no_reason", "No reason."), (400, "bad_days", "days outside 0 to 3,650."), (400, "bad_until", "until has passed, or is more than 3,650 days away."),
                  (404, "player_not_found", "No such player."), (409, "stale", "The number belongs to someone else now.")]),
    Route("DELETE", "/players/{player}/ban", "write", "player_unban", "Players", "Lifts a player's ban.", query=[SEEN],
          answer="PlayerGameAnswer",
          errors=[(404, "player_not_found", "No such player."), (409, "stale", "The number belongs to someone else now.")]),
    Route("POST", "/players/{player}/game/reset", "write", "player_game_reset", "Players",
          "Resets a player's game state to what a new player starts with: currencies, level, items, purchases.",
          "Their scores, achievements, name and ban stay. A backup is made first; without it nothing changes.", query=[SEEN],
          answer="PlayerGameReset",
          errors=[(404, "player_not_found", "No such player."), (409, "stale", "The number belongs to someone else now."),
                  (500, "backup_failed", "The backup could not be made (the message says why).")]),
    Route("GET", "/bans", "read", "bans_list", "Players", "Every banned player, with the reason and the end.", answer="BanList"),
    Route("GET", "/game", "read", "game_get", "Players", "The server's game settings: unlimited currency for every player, what a new player starts with.",
          answer="GameSettings"),
    Route("PUT", "/game", "write", "game_set", "Players", "Changes the server's game settings.",
          "What is left out stays as it is. New start values reach new players alone: every player there is now keeps what they have.",
          body=[Field("unlimited", "boolean", "Unlimited currency for every player.", optional=True),
                Field("start_mpoint", "integer", "0 to 99,999,999.", optional=True),
                Field("start_qpoint", "integer", "0 to 99,999,999.", optional=True),
                Field("start_level", "integer", "1 to 99.", optional=True)], answer="GameSettings",
          errors=[(400, "bad_body", "None of the four was sent."), (400, "bad_start_mpoint", "A start value outside its range."),
                  (400, "bad_start_qpoint", "A start value outside its range."), (400, "bad_start_level", "A start level outside 1 to 99.")]),
    # The Accounts page's accounts (accounts.py).
    Route("GET", "/accounts", "read", "accounts_list", "Accounts", "Every account of the site, and the players an account can be linked to.",
          answer="AccountList"),
    Route("POST", "/accounts", "write", "accounts_create", "Accounts", "Makes an account.",
          "Its password is made when none is sent, and comes back this once, with the message to send.",
          body=[Field("name", "string", "Its ID: 3 to 20 Latin letters, digits, dots, dashes or underscores."),
                Field("password", "string", "Its password, 6 to 64 characters, 10 at least with admin rights. Left out or empty: "
                      "one is made.", optional=True),
                Field("note", "string", "Whom it is for. The Accounts page cuts a longer one; here it is refused.", optional=True,
                      max_length=40),
                Field("admin", "boolean", "True to open the admin pages to it too.", optional=True),
                Field("player", "integer", "The game player it is.", nullable=True, optional=True)],
          answer="AccountPassword", status=201,
          errors=[(400, "bad_id", "Not an ID."), (400, "bad_password", "Not 6 to 64 characters, or under 10 with admin rights."), (400, "bad_player", "No such player."),
                  (400, "bad_field", "A note over 40 characters."),
                  (409, "id_taken", "The ID is taken (by an account in any letter case, or the owner's).")]),
    Route("GET", "/accounts/{account}", "read", "account_get", "Accounts", "One account.", answer="AccountAnswer",
          errors=[(404, "account_not_found", "No such account.")]),
    Route("POST", "/accounts/{account}/password", "write", "account_password", "Accounts", "Makes a new password for an account.",
          "The old one stops working and its sign-ins end; the new one comes back this once. A token's own account keeps its tokens.",
          answer="AccountPassword", errors=[(404, "account_not_found", "No such account.")]),
    Route("POST", "/accounts/{account}/disable", "write", "account_disable", "Accounts", "Disables an account: it cannot sign in until enabled again.",
          "Its sign-ins end, and an admin's tokens stop working.", answer="AccountAnswer",
          errors=[(404, "account_not_found", "No such account."), (409, "already_so", "It is disabled already."),
                  (409, "own_account", "The token's own account: for another admin, or the owner.")]),
    Route("POST", "/accounts/{account}/enable", "write", "account_enable", "Accounts", "Enables an account again.", answer="AccountAnswer",
          errors=[(404, "account_not_found", "No such account."), (409, "already_so", "It is enabled already."),
                  (409, "own_account", "The token's own account.")]),
    Route("POST", "/accounts/{account}/make-admin", "write", "account_make_admin", "Accounts", "Gives an account admin rights: it opens the admin pages too.",
          answer="AccountAnswer",
          errors=[(404, "account_not_found", "No such account."), (409, "already_so", "It has them already."),
                  (409, "own_account", "The token's own account.")]),
    Route("POST", "/accounts/{account}/make-player", "write", "account_make_player", "Accounts", "Takes an account's admin rights away: it opens the site only.",
          "Its sessions on the admin pages end, and its tokens stop working.", answer="AccountAnswer",
          errors=[(404, "account_not_found", "No such account."), (409, "already_so", "It has none."),
                  (409, "own_account", "The token's own account.")]),
    Route("POST", "/accounts/{account}/link", "write", "account_link", "Accounts", "Links an account to the game player it is, or unlinks it.",
          "The site then shows that player's name for it and marks their places.",
          body=[Field("player", "integer", "The player's number; null to unlink.", nullable=True)], answer="AccountAnswer",
          errors=[(404, "account_not_found", "No such account."), (400, "bad_player", "No such player."),
                  (409, "already_so", "It is linked so already.")]),
    Route("DELETE", "/accounts/{account}", "write", "account_delete", "Accounts", "Deletes an account, and its tokens.", answer="Deleted",
          errors=[(404, "account_not_found", "No such account."), (409, "own_account", "The token's own account.")]),
    # The Accounts page's tokens (tokens.py).
    Route("GET", "/tokens", "read", "tokens_list", "Tokens", "Every API token, with whose it is and whether it works. Never the tokens themselves.",
          answer="TokenList"),
    Route("POST", "/tokens", "write", "tokens_create", "Tokens", "Makes a token for the same admin as the token that asks.",
          "The token comes back this once; only its hash is kept.",
          body=[Field("name", "string", "What it is for, 1 to 40 characters."),
                Field("scope", "string", "What it may do: read only answers GET, and not a backup's download or a look at the "
                      "server PC's folders.", enum=["read", "write"])],
          answer="TokenMade", status=201,
          errors=[(400, "bad_name", "No name, or one over 40 characters.")]),
    Route("DELETE", "/tokens/{token}", "write", "token_revoke", "Tokens", "Revokes a token for good. It may be the token that asks.",
          answer="Deleted", errors=[(404, "token_not_found", "No such token.")]),
    # The Broadcasts page's top: the server's switch, what new players start with, the quality (recordings.py).
    Route("GET", "/broadcasts", "read", "broadcasts_get", "Broadcasts", "The server's broadcasts: on or off, what new players start with, the "
          "quality, and who is switched on and on air.", answer="BroadcastSettings"),
    Route("PUT", "/broadcasts", "write", "broadcasts_set", "Broadcasts", "Turns broadcasts on or off for the server, sets what new players "
          "start with and the quality.",
          "What is left out stays as it is. Off: phones and PCs send nothing and the site shows nothing of broadcasts; each player's switch "
          "is kept, each player switched on is told once in the game that their broadcast ended, every live window goes at once and running "
          "recordings are closed. On: each player switched on is told in the game, between songs. Players switched off hear of neither: "
          "nothing changes for them. New players turned to start on: "
          "every player already there counts as chosen for, so only those who come after start on. Phones and the PC player follow "
          "a new quality within 15 seconds.",
          body=[Field("on", "boolean", "Broadcasts on or off for the server.", optional=True),
                Field("new_players", "boolean", "Whether a new player's switch starts on.", optional=True),
                Field("quality", "string", "light, standard, smooth or sharp.", optional=True, enum=["light", "standard", "smooth", "sharp"])],
          answer="BroadcastSettings", errors=[(400, "bad_body", "None of the three was sent."), (400, "bad_field", "A quality there is not.")]),
    # The Broadcasts page's recordings (recordings.py).
    Route("GET", "/recordings", "read", "recordings_list", "Recordings", "Every recording of a broadcast, newest first.", answer="RecordingList"),
    Route("GET", "/recordings/limits", "read", "recordings_limits", "Recordings", "The limits the recordings are kept to, and how much of the disk they take.",
          answer="Limits"),
    Route("PUT", "/recordings/limits", "write", "recordings_set_limits", "Recordings", "Sets the limits: a total size and an age.",
          "Lower limits delete recordings at once and for good. Without confirm they are refused with what they would delete.",
          body=[Field("cap_gb", "number", "Their total size at most, in GB (0.001 to 1000000)."),
                Field("days", "integer", "Their age at most, in days (1 to 36500)."),
                Field("confirm", "boolean", "True to save limits that delete recordings.", optional=True)],
          answer="Limits",
          errors=[(400, "bad_limits", "Not numbers in those ranges."), (409, "would_delete", "They would delete recordings (the message says how many), and confirm was not true.")]),
    Route("POST", "/recordings/delete", "write", "recordings_delete", "Recordings", "Deletes recordings: those named, or all of one player's.",
          "A recording still being made is kept.",
          body=[Field("items", "[string]", "The recordings, as <player>/<id> (their key).", optional=True),
                Field("player", "integer", "A player whose every recording goes.", optional=True)],
          answer="RecordingsDone",
          errors=[(400, "bad_body", "Neither items nor player, or both."), (404, "recording_not_found", "None of them is there."),
                  (409, "recording_open", "They are all still being made.")]),
    Route("GET", "/recordings/{player}/{recording}", "read", "recording_get", "Recordings", "One recording and its files.",
          answer="RecordingFiles", errors=[(404, "recording_not_found", "No such recording.")]),
    Route("GET", "/recordings/{player}/{recording}/download", "read", "recording_download", "Recordings", "A recording as one MPEG-TS file.",
          download="video/mp2t", errors=[(404, "not_found", "No such recording, or one still being made.")]),
    Route("GET", "/recordings/{player}/{recording}/files/{part}", "read", "recording_file", "Recordings", "A recording's playlist or one of its segments, for a player such as hls.js.",
          download=["application/vnd.apple.mpegurl", "video/mp2t"], errors=[(404, "not_found", "No such file.")]),
    Route("POST", "/recordings/{player}/{recording}/hide", "write", "recording_hide", "Recordings", "Hides a recording from players.",
          answer="RecordingAnswer", errors=[(404, "recording_not_found", "No such recording.")]),
    Route("POST", "/recordings/{player}/{recording}/show", "write", "recording_show", "Recordings", "Shows a hidden recording to players again.",
          answer="RecordingAnswer", errors=[(404, "recording_not_found", "No such recording.")]),
    Route("DELETE", "/recordings/{player}/{recording}", "write", "recording_delete", "Recordings", "Deletes a recording.", answer="Deleted",
          errors=[(404, "recording_not_found", "No such recording."), (409, "recording_open", "It is still being made.")]),
    # The Backups page (backups.py).
    Route("GET", "/backups", "read", "backups_list", "Backups", "Every backup, newest first.", answer="BackupList"),
    Route("POST", "/backups", "write", "backups_create", "Backups", "Makes a backup now: the database, the signing key and the added songs.",
          answer="BackupAnswer", status=201,
          errors=[(409, "busy", "A restore runs."), (500, "backup_failed", "It could not be made (the message says why: a full disk, a busy database).")]),
    Route("POST", "/backups/upload", "write", "backups_upload", "Backups", "Brings in a backup archive (.tar.gz, 1 GB at most) from elsewhere.",
          "It joins the list; POST /backups/{backup}/restore puts it in place.", upload=("file", "The backup archive (.tar.gz)."),
          answer="BackupAnswer", status=201,
          errors=[(400, "no_file", "No .tar.gz in the file field."), (413, "too_large", "Over 1 GB."),
                  (422, "not_backup", "Not a backup: no database in it."), (500, "upload_failed", "It could not be kept (a full disk).")]),
    Route("GET", "/backups/auto", "read", "backups_auto_get", "Backups", "The daily backup: on or off, those kept, when the next comes.",
          answer="DailyBackup"),
    Route("PUT", "/backups/auto", "write", "backups_auto_set", "Backups", "Turns the daily backup on or off.",
          body=[Field("on", "boolean", "True for on.")], answer="DailyBackup"),
    Route("GET", "/backups/{backup}/download", "write", "backup_download", "Backups", "A backup archive.",
          "A write token's: it holds the accounts' password hashes and the app's signing key, more than a token that only "
          "watches may take away. Keep it where only you can read it.", download="application/gzip",
          errors=[(404, "backup_not_found", "No such backup.")]),
    Route("POST", "/backups/{backup}/restore", "write", "backup_restore", "Backups", "Restores a backup while the server runs.",
          "The current state is backed up first. Who is broadcasting, the site's accounts, the API's tokens and the webhooks "
          "stay as they are now: they are put into the restored database before it takes the current one's place, and nothing "
          "of the restored data goes to a chat. A server with no account yet takes the backup's accounts, and one with no webhook, "
          "account or player yet the backup's webhooks.",
          answer="JobAnswer", status=202,
          errors=[(404, "backup_not_found", "No such backup."), (409, "busy", "Another restore runs.")]),
    Route("DELETE", "/backups/{backup}", "write", "backup_delete", "Backups", "Deletes a backup.", answer="Deleted",
          errors=[(404, "backup_not_found", "No such backup.")]),
    # The Logs page's three tabs (logs.py).
    Route("GET", "/logs/requests", "read", "logs_requests", "Logs", "The server's requests, filtered as on the Requests tab, with the last 24 hours added up.",
          query=[Field("q", "string", "Words the request's line holds.", optional=True),
                 Field("status", "string", "Its result: a class, or err for every failure.", optional=True, enum=["err", "2xx", "3xx", "4xx", "5xx"]),
                 Field("kind", "string", "What it was for.", optional=True, enum=["game", "files", "app", "site", "live", "admin", "other"]),
                 Field("limit", "integer", "How many to list, 1 to 400 (400).", optional=True)],
          answer="RequestLog", errors=[(400, "bad_query", "A filter that is not one of its values.")]),
    Route("GET", "/logs/requests/download", "read", "logs_requests_download", "Logs", "All of the request log that is kept, as one file, oldest first.",
          download="text/plain"),
    Route("GET", "/logs/plays", "read", "logs_plays", "Logs", "Every play, filtered as on the Plays tab, a page of 50 at a time, with what they add up to.",
          query=[Field("q", "string", "Words the player's name, the song or the chart holds.", optional=True),
                 Field("player", "integer", "One player's plays. A player with none gives none (the Plays tab shows every play "
                       "then, as its list of players has no such name).", optional=True),
                 Field("from", "string", "From this day (YYYY-MM-DD), on this server's clock.", optional=True),
                 Field("to", "string", "To this day, the whole of it.", optional=True),
                 Field("page", "integer", "The page (1). Past the last, the last.", optional=True)],
          answer="PlayLog", errors=[(400, "bad_query", "A day that is not YYYY-MM-DD, or a player or page that is not a number.")]),
    Route("GET", "/logs/plays/download", "read", "logs_plays_download", "Logs", "Every play the filter leaves, all its pages in one spreadsheet (CSV, UTF-8).",
          query=[Field("q", "string", "As for /logs/plays.", optional=True), Field("player", "integer", "As for /logs/plays.", optional=True),
                 Field("from", "string", "As for /logs/plays.", optional=True), Field("to", "string", "As for /logs/plays.", optional=True)],
          download="text/csv", errors=[(400, "bad_query", "As for /logs/plays.")]),
    Route("GET", "/logs/changes", "read", "logs_changes", "Logs", "What was changed on the admin pages and through the API, sign-ins too.",
          answer="ChangeList"),
    # The setup (setup.py): its four steps, and what it finds on the server PC.
    Route("GET", "/setup", "read", "setup_get", "Setup", "The setup's four steps: what each has and whether it is done.", answer="SetupState"),
    Route("GET", "/setup/found", "read", "setup_found", "Setup", "The game's files found on the server PC: in the home folder, Downloads, the Desktop, Documents and OneDrive's folders.",
          "A host install only. Each of those places is looked in, and each folder in it.", answer="FoundList",
          errors=[(404, "host_only", "Not a host install.")]),
    # The two looks at the server PC's folders take a write token: they show any folder the server can read, more than a
    # token that only watches the pages may see.
    Route("GET", "/setup/folder", "write", "setup_folder", "Setup", "A folder of the server PC, as the setup's folder picker shows it.",
          "A host install only, and a write token's: any folder the server can read. A file's path gives its folder, with the "
          "file picked. With it the places the picker goes to in one step, as the setup page shows them.",
          query=[Field("path", "string", "The folder, as typed or pasted: quotes around it go, and ~ is the home folder. $NAME and "
                       "%NAME% stay as they are written. A path on another computer is refused, and on Windows any path but a "
                       "drive letter's. Left out: Downloads.", optional=True)],
          answer="Folder",
          errors=[(404, "host_only", "Not a host install."), (400, "network_path", "A path on another computer (a network share), or on Windows not a drive letter's."),
                  (404, "cannot_open", "The folder is not there, or cannot be read: nearest names the folder the page opens instead.")]),
    Route("GET", "/setup/what", "write", "setup_what", "Setup", "What one file or folder of the server PC is to the import.",
          "A host install only, and a write token's, as for /setup/folder. An archive's look can take 7-Zip a second.",
          query=[Field("path", "string", "The file or folder, as for /setup/folder.")], answer="What",
          errors=[(404, "host_only", "Not a host install."), (400, "network_path", "A path on another computer (a network share), or on Windows not a drive letter's.")]),
    Route("POST", "/setup/import", "write", "setup_import", "Setup", "Imports the game's files from a folder or file on the server PC: the app, the client data, the song data.",
          "A host install only. Then the song list is made. Song data alone is imported as the songs whatever songs says.",
          body=[Field("path", "string", "The folder or file."),
                Field("songs", "boolean", "True (the default) to import the song data too.", optional=True)],
          answer="JobAnswer", status=202,
          errors=[(404, "host_only", "Not a host install: use ./opendmtq import."), (400, "no_path", "No path."),
                  (400, "network_path", "A path on another computer (a network share), or on Windows not a drive letter's."),
                  (404, "path_not_found", "Nothing at the path."), (400, "cannot_read", "It cannot be read."),
                  (400, "too_wide", "A whole drive or the home folder."), (409, "busy", "An import or a build runs.")]),
    Route("PUT", "/setup/address", "write", "setup_address", "Setup", "Changes the address phones use to another private address of the server PC, and starts the server again for it.",
          "A host install only. The port stays as it is. The app is built for the new address at the start.",
          body=[Field("address", "string", "A private IPv4 address: one of the choices GET /setup gives, or any other private "
                      "address, as the setup page takes one typed. Loopback and link-local addresses are refused; the address "
                      "is not checked against the ones this PC has.")],
          answer="Restarting", status=202,
          errors=[(404, "host_only", "Not a host install: use ./opendmtq host."), (400, "bad_address", "Not a private address phones can reach."),
                  (409, "same_address", "The server uses it already."), (409, "busy", "An import or a build runs.")]),
    Route("POST", "/setup/player", "write", "setup_player", "Setup", "Makes an account for a player, as the setup's players step does: its password is made.",
          body=[Field("name", "string", "Its ID: 3 to 20 Latin letters, digits, dots, dashes or underscores.")],
          answer="AccountPassword", status=201,
          errors=[(400, "bad_id", "Not an ID."), (409, "id_taken", "The ID is taken.")]),
    Route("POST", "/setup/build", "write", "setup_build", "Setup", "Builds the app for this server's address, as the setup's last step does.",
          answer="JobAnswer", status=202,
          errors=[(409, "no_client", "No client to build from."), (409, "build_running", "A build runs already."),
                  (409, "busy", "An import runs.")]),
    # What the players' site shows (site.py, the queries of server/portal).
    Route("GET", "/site/home", "read", "site_home", "Site", "The home page: the app, the best players, the newest records, the broadcasts.",
          answer="SiteHome"),
    Route("GET", "/site/songs", "read", "site_songs", "Site", "The song list players see, by title, with the records on each.",
          answer="SiteSongList"),
    Route("GET", "/site/songs/{song}", "read", "site_song", "Site", "A song's page: the song, who made it, its charts.",
          answer="SiteSongPage", errors=[(404, "song_not_found", "No such song.")]),
    Route("GET", "/site/charts/{chart}/ranking", "read", "site_chart_ranking", "Site", "A chart's leaderboard: the best 100.",
          answer="Board", errors=[(404, "chart_not_found", "No such chart.")]),
    Route("GET", "/site/rankings", "read", "site_rankings", "Site", "The rankings, by a tab of the rankings page.",
          query=[Field("sort", "string", "The tab: total best score (the default), S grades, perfect plays, charts played.", optional=True,
                       enum=["total", "s_count", "perfect", "charts"])],
          answer="Rankings", errors=[(400, "bad_query", "Not one of the tabs.")]),
    Route("GET", "/site/rankings/month", "read", "site_rankings_month", "Site", "This month's rankings, as the game ranks them, and the months before.",
          answer="MonthRankings"),
    Route("GET", "/site/players/{player}", "read", "site_player", "Site", "A player's page: figures, rank, grades, the last 12 weeks, levels, recent plays, broadcasts.",
          answer="SitePlayer", errors=[(404, "player_not_found", "No such player.")]),
    Route("GET", "/site/players/{player}/records", "read", "site_player_records", "Site", "A player's best records, all of them.",
          answer="SiteRecords", errors=[(404, "player_not_found", "No such player.")]),
    Route("GET", "/site/plays/recent", "read", "site_plays_recent", "Site", "The newest plays, or the newest records as the home page lists them.",
          query=[Field("records", "boolean", "true: new records only, each with the best before it.", optional=True),
                 Field("player", "integer", "One player's only.", optional=True),
                 Field("limit", "integer", "How many, 1 to 100 (20).", optional=True)],
          answer="SitePlays", errors=[(400, "bad_query", "A limit or a player that is not a number.")]),
    Route("POST", "/site/link", "write", "site_link", "Site", "A one-time link that signs a browser in to the players' site as the "
          "token's admin, as the PC client's My page on the site does for its own sign-in.",
          "The link is a path on the site (`/opendmtq/login.php?once=...`): opened in a browser on the server's address within a "
          "minute, it signs that browser in to the token's admin's account (the owner's ID for the owner's token) and opens "
          "`next`. It works once.",
          body=[Field("next", "string", "The site's page to open once signed in, a path on the site (default `/opendmtq/`).",
                      optional=True, max_length=200)],
          answer="SiteLink", errors=[(400, "bad_field", "next is not a path on the site."),
                                     (503, "links_unavailable", "The link could not be kept beside the database.")]),
    Route("GET", "/site/live", "read", "site_live", "Site", "Who is on air now, and the recordings players may watch.", answer="SiteLive"),
    Route("GET", "/site/live/{player}/files/{part}", "read", "site_live_file", "Site", "A broadcast's live playlist or one of its segments, as the live page plays them.",
          "Only while the player's broadcast is switched on. The playlist names its segments relatively, so a player such as "
          "hls.js asks for them here too; after 30 seconds without video it ends.", download=["application/vnd.apple.mpegurl", "video/mp2t"],
          errors=[(404, "not_found", "The broadcast is off, or no such file.")],
          parts={"part": ("string", "The live playlist (index.m3u8) or one of the segments it names (<n>.ts), while the broadcast "
                                    "runs.")}),
]

# The refusals every route can give, besides its own: (status, code, when). The routes that take a write token also refuse
# a read one.
COMMON_ERRORS = [
    (401, "no_token", "No Authorization: Bearer header."),
    (401, "bad_token", "A token that is not one of this server's (revoked, mistyped)."),
    (401, "token_stopped", "The token's admin cannot use the admin pages now (disabled, or without admin rights)."),
    (429, "throttled", "A wrong token, after too many wrong tokens or passwords from this address lately (Retry-After says when "
                       "to try again). A token that works is never held back."),
    (503, "admin_off", "The admin pages have no password (ADMIN_PASSWORD), so the API is off too."),
    (503, "database_unavailable", "The database cannot be read."),
]
WRITE_ERRORS = [(403, "read_only", "A read token, on a route that takes a write token.")]

# What an error may say besides its code and message, in ErrorBody: these of a refusal's own details only.
ERROR_FIELDS = ("nearest",)

# The largest whole number the database keeps (SQLite's 64-bit integers): the most a number in a path may be.
INT_MAX = 2 ** 63 - 1
BODY_ERRORS = [(400, "bad_json", "A body that is not a JSON object."), (400, "bad_field", "A field missing, of the wrong type, or not one of its values.")]
QUERY_ERRORS = [(400, "bad_query", "A parameter of the wrong type, or not one of its values.")]


def by_name():
    """The routes by their handler's name."""
    return {route.name: route for route in ROUTES}


def errors_of(route):
    """Every refusal a route can give, its own first."""
    if route.scope is None:
        return []
    out = list(route.errors)
    if route.body:
        out += BODY_ERRORS
    if route.query and not any(code == "bad_query" for _, code, _ in out):
        out += QUERY_ERRORS
    out += COMMON_ERRORS
    if route.scope == "write":
        out += WRITE_ERRORS
    return out


# ------------------------------------------------------------------------------ the OpenAPI document

BASIC = {"string", "integer", "number", "boolean", "object"}


def schema(type_name):
    """A field's type as JSON Schema: a basic type, a shape (by reference), [type] a list, {type} an object of values."""
    if type_name.startswith("[") and type_name.endswith("]"):
        return {"type": "array", "items": schema(type_name[1:-1])}
    if type_name.startswith("{") and type_name.endswith("}"):
        return {"type": "object", "additionalProperties": schema(type_name[1:-1])}
    if type_name in BASIC:
        return {"type": type_name}
    return {"$ref": f"#/components/schemas/{type_name}"}


def field_schema(field):
    """A field as JSON Schema, with what it is, its values and whether it may be null."""
    out = schema(field.type)
    if field.enum:
        out = dict(out, enum=list(field.enum) + ([None] if field.nullable else []))
    if field.nullable:
        # JSON Schema 2020-12 (OpenAPI 3.1): a type that may also be null, or a reference beside null.
        out = {"type": [out["type"], "null"], **{k: v for k, v in out.items() if k != "type"}} if "type" in out and isinstance(out["type"], str) \
            else {"anyOf": [out, {"type": "null"}]}
    # A string the API refuses past a length, as the reference says.
    if field.max_length is not None:
        out = dict(out, maxLength=field.max_length)
    return dict(out, description=field.doc)


def path_schema(type_name):
    """A part of a path as JSON Schema: a number is a whole number from 0 to INT_MAX (any other matches no route)."""
    if type_name == "integer":
        return {"type": "integer", "minimum": 0, "maximum": INT_MAX}
    return {"type": type_name}


def object_schema(fields, doc="", open_=False):
    """An object with these fields: the ones not optional are required."""
    out = {"type": "object", "properties": {f.name: field_schema(f) for f in fields},
           "required": [f.name for f in fields if not f.optional], "additionalProperties": open_}
    if doc:
        out["description"] = doc
    if not out["required"]:
        del out["required"]
    return out


def openapi(version="1"):
    """The OpenAPI 3.1 document of this API, from the route table."""
    paths = {}
    for route in ROUTES:
        op = {"operationId": route.name, "summary": route.summary, "tags": [route.tag]}
        if route.doc:
            op["description"] = route.doc
        params = [{"name": name, "in": "path", "required": True, "schema": path_schema(route.param(name)[0]),
                   "description": route.param(name)[1]} for name in route.params()]
        params += [{"name": f.name, "in": "query", "required": not f.optional, "schema": dict(schema(f.type), **({"enum": f.enum} if f.enum else {})),
                    "description": f.doc} for f in route.query]
        if params:
            op["parameters"] = params
        if route.body:
            op["requestBody"] = {"required": any(not f.optional for f in route.body),
                                 "content": {"application/json": {"schema": object_schema(route.body)}}}
        elif route.upload:
            field, doc = route.upload
            op["requestBody"] = {"required": True, "content": {"multipart/form-data": {"schema": {
                "type": "object", "properties": {field: {"type": "string", "format": "binary", "description": doc}}, "required": [field]}}}}
        responses = {}
        if route.download:
            # Each type the route gives (a playlist's route gives its segments too).
            responses[str(route.status)] = {"description": route.summary,
                                            "content": {t: {"schema": {"type": "string", "format": "binary"}} for t in route.download}}
            # The part a Range asks for, in the same types, where the route gives one.
            if route.ranges:
                responses["206"] = {"description": "The part a Range header asks for, which Content-Range places in the whole.",
                                    "content": {t: {"schema": {"type": "string", "format": "binary"}} for t in route.download}}
        else:
            responses[str(route.status)] = {"description": route.summary, "content": {"application/json": {"schema": schema(route.answer)}}}
        for status, codes in grouped(errors_of(route)).items():
            responses[str(status)] = {"description": "; ".join(f"{code}: {when}" for code, when in codes),
                                      "content": {"application/json": {"schema": schema("Error")}}}
        op["responses"] = responses
        if route.scope is None:
            op["security"] = []
        else:
            op["x-scope"] = route.scope
        paths.setdefault(route.path, {})[route.method.lower()] = op
    return {
        "openapi": "3.1.0",
        "info": {"title": "OpenDMTQ API", "version": version,
                 "description": "Everything the admin pages show and do, and what the players' site shows, as JSON. A token from "
                                "the admin pages' Accounts page, as Authorization: Bearer <token>. docs/api.md says the rest."},
        "servers": [{"url": BASE}],
        "tags": [{"name": name, "description": doc} for name, doc in TAGS],
        "paths": paths,
        "components": {
            "securitySchemes": {"token": {"type": "http", "scheme": "bearer", "description": "A token made on the Accounts page: odq_<id>_<secret>."}},
            "schemas": {name: object_schema(shape.fields, shape.doc, shape.open) for name, shape in SHAPES.items()},
        },
        "security": [{"token": []}],
    }


def grouped(errors):
    """Refusals by their status, in order: {status: [(code, when)]}."""
    out = {}
    for status, code, when in sorted(errors, key=lambda e: e[0]):
        out.setdefault(status, []).append((code, when))
    return out


# ------------------------------------------------------------------------------ the reference in docs/api.md

def anchor(text):
    """A heading's anchor as GitHub makes it: lower case, its words joined by dashes, nothing else."""
    return re.sub(r"[^a-z0-9 _-]", "", text.lower()).replace(" ", "-")


def prose(text):
    """Words of the table for the reference: < and > written as entities outside code spans, where GitHub would take
    <player> for a tag of HTML and show nothing of it."""
    # Even pieces are prose, odd ones the insides of `code`, which shows its signs as they are.
    pieces = text.split("`")
    return "`".join(p.replace("<", "&lt;").replace(">", "&gt;") if i % 2 == 0 else p for i, p in enumerate(pieces))


# How the reference's tables align each column: short values in the middle, words to the left.
TEXT, SHORT = ":---", ":---:"


def type_words(type_name):
    """A field's type in the reference, a shape's name linked to its place."""
    if type_name.startswith("[") and type_name.endswith("]"):
        return f"list of {type_words(type_name[1:-1])}"
    if type_name.startswith("{") and type_name.endswith("}"):
        return f"object of {type_words(type_name[1:-1])}"
    if type_name in BASIC:
        return type_name
    return f"[{type_name}](#{anchor(type_name)})"


def field_line(field):
    """One field in the reference."""
    marks = [type_words(field.type)]
    if field.nullable:
        marks.append("or null")
    if field.optional:
        marks.append("optional")
    if field.max_length is not None:
        marks.append(f"{field.max_length} characters at most")
    values = f" One of {', '.join(f'`{v}`' for v in field.enum)}." if field.enum else ""
    return f"- `{field.name}` ({', '.join(marks)}): {prose(field.doc)}{values}"


def query_line(field):
    """One parameter of a route's query in the reference."""
    values = f" One of {', '.join(f'`{v}`' for v in field.enum)}." if field.enum else ""
    return f"- `{field.name}` (query, {type_words(field.type)}{', optional' if field.optional else ''}): {prose(field.doc)}{values}"


def reference():
    """The reference part of docs/api.md: each section's routes in a table, then each route, then the shapes."""
    out = [REFERENCE_START, "", "## Reference", "",
           "Every route, by the page it belongs to. Paths are under `/opendmtq/api/v1`. Every route needs a token except "
           "`GET /openapi.json`; the scope column says which. Besides its own refusals, every route can answer `401`, `429` "
           "and `503` as [Errors](#errors) says, and a route of the write scope `403` to a read token.", ""]
    for tag, doc in TAGS:
        routes = [r for r in ROUTES if r.tag == tag]
        # The route is the row's name, the scope a short value, what it does words.
        out += [f"### {tag}", "", prose(doc), "", "| Route | Scope | What it does |", f"|{TEXT}|{SHORT}|{TEXT}|"]
        out += [f"| [`{r.method} {r.path}`](#{anchor(r.method + ' ' + r.path)}) | {r.scope or 'none'} | {prose(r.summary)} |" for r in routes]
        out.append("")
        for r in routes:
            out += [f"#### `{r.method} {r.path}`", "", prose(r.summary + (" " + r.doc if r.doc else "")), ""]
            lines = []
            for name in r.params():
                kind, words = r.param(name)
                lines.append(f"- `{name}` (path, {kind}): {prose(words)}")
            lines += [query_line(f) for f in r.query]
            if lines:
                out += ["Parameters:", ""] + lines + [""]
            if r.body:
                out += ["Body (JSON):", ""] + [field_line(f) for f in r.body] + [""]
            if r.upload:
                out += [f"Upload (multipart/form-data): `{r.upload[0]}`, {prose(r.upload[1][0].lower() + r.upload[1][1:])}", ""]
            if r.download:
                # Every type the file may come in: a playlist's route gives its segments too. And the part a Range asks for,
                # where the route gives one.
                out.append(f"Answer: `{r.status}` with the file itself ({' or '.join(f'`{t}`' for t in r.download)})"
                           + (", or `206` with the part a Range header asks for." if r.ranges else "."))
            elif r.answer == "object":
                out.append(f"Answer: `{r.status}` with the OpenAPI document.")
            else:
                out.append(f"Answer: `{r.status}` with {type_words(r.answer)}.")
            out.append("")
            if r.errors:
                out += ["Refusals:", ""] + [f"- `{status} {code}`: {prose(when)}" for status, code, when in r.errors] + [""]
    out += ["### Shapes", "", "The objects the routes answer with. A field marked optional comes only with some answers.", ""]
    for name, shape in SHAPES.items():
        out += [f"#### {name}", "", prose(shape.doc) + (" Other fields may come with it." if shape.open else ""), ""]
        out += [field_line(f) for f in shape.fields] + [""]
    out.append(REFERENCE_END)
    return "\n".join(out) + "\n"


def write_reference(path):
    """Puts reference() between the marks in the document at path, the rest of it as it is."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    start, end = text.index(REFERENCE_START), text.index(REFERENCE_END) + len(REFERENCE_END) + 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(text[:start] + reference() + text[end:])


if __name__ == "__main__":
    # python3 tools/opendmtq_tools/admin/api_routes.py docs/api.md: the reference written again; with no file, the
    # OpenAPI document on stdout.
    if len(sys.argv) > 1:
        write_reference(sys.argv[1])
    else:
        print(json.dumps(openapi(), indent=1))
