# The API

Everything the admin pages show and do, and what the players' site shows, as JSON over HTTP. For a script that makes
a backup every night, a bot that posts new records, a monitor that asks whether the game server is well, or a program
of your own that runs the server. Whatever a person can do on the admin pages, the API can do the same way: each route
calls the same code as the page's form.

## Where it is

Beside the admin pages, at `/opendmtq/api/v1/`, and only where they are:

| Install | Address |
|:---|:---|
| Docker Compose, on the server PC | The admin pages' address `./opendmtq setup` gives at its end, with `/opendmtq/api/v1/` in place of `/opendmtq/admin/` (`ADMIN_PORT` and `ADMIN_BIND` in `.env` change it) |
| Docker Compose, from the local network | `https://<server>:<port>/opendmtq/api/v1/`, with port 80 `https://<server>:80/opendmtq/api/v1/`. A request over plain HTTP is refused while HTTPS works (`403 use_https`, with that address) |
| Docker Compose, exposed to the internet | Only on the server PC, unless `./opendmtq expose --admin-public`: then over HTTPS from anywhere |
| Host install and Windows | On the server PC, the admin pages' address `./opendmtq status` shows, and on Windows the server's window, with `/opendmtq/api/v1/` in place of `/opendmtq/admin/`; from the local network, `http://<server>:<port>/opendmtq/api/v1/` (without `:<port>` when it is 80) |
| Kubernetes | Through the router when `admin.onPublicPort` allows it, else `kubectl port-forward` to port 8000 of the api pod ([kubernetes.md](kubernetes.md)) |

The same settings open it or keep it closed as for the admin pages ([admin.md](admin.md), [internet.md](internet.md)):
`ADMIN_ON_PUBLIC_PORT`, `./opendmtq expose --admin-public`, `admin.onPublicPort`. Where the admin pages are not open,
the API is not either: the address answers `404`, or `403` with the reason. Without a password for the admin pages
(`ADMIN_PASSWORD`) the API is off as well.

Send every request to the HTTPS address from the start. Over plain HTTP the token travels in clear, and where HTTPS
works the server answers such a request `403 use_https` and passes nothing on. With Docker Compose the HTTPS door uses
the server's own certificate: give curl the server's authority, which the plain door offers at
`http://<server>:<port>/ca.crt` (`curl --cacert ca.crt https://...`, [internet.md](internet.md#https)). In Kubernetes,
`router.tls.secretName` names a Secret of type `kubernetes.io/tls` that holds a certificate of your own
([kubernetes.md](kubernetes.md)).

## Tokens

Every request carries a token, except `GET /opendmtq/api/v1/openapi.json`:

```http
Authorization: Bearer odq_3f9a1c2b7d4e_...
```

Make one on the admin pages' **Accounts** page, under **API tokens**: a name (what it is for) and a scope. The token
shows once, on the page after: copy it then. The server keeps only a hash of it, so a lost token cannot be shown again;
make another. A write token can make tokens too (`POST /tokens`), for the same admin.

| Scope | May |
|:---:|:---|
| `read` | Every `GET` route but three: a backup's download, and the setup's looks at the server PC's folders (`GET /setup/folder`, `GET /setup/what`) |
| `write` | Everything the pages do too, and those three: a backup holds the accounts' password hashes and the app's signing key, and the setup's looks show any folder the server can read |

A token belongs to the admin who made it. It works while that admin can open the admin pages: the owner's (`ADMIN_USER`
in `.env`) while the pages have a password, an account's while it is enabled and has admin rights. When the account is
disabled or loses its rights, its tokens stop; they work again once it has them back. Deleting the account deletes its
tokens. A new password for the account leaves its tokens as they are. A token revoked on the Accounts page, or with
`DELETE /tokens/{token}`, ends for good.

A restore leaves the tokens as they are now, on the Backups page, through `POST /backups/{backup}/restore` and with
`./opendmtq restore`: a token revoked since the backup stays revoked, and one made since keeps working. The accounts
come back as the backup has them, and their tokens follow them: an account's token works after a restore while the
restored accounts have that account, enabled and with admin rights. The owner's tokens follow the password in `.env`.
Where the live database was too damaged to copy and was set aside, its tokens are lost with it.

The token is looked at first, and a token that works is never held back. A wrong one counts as a failed sign-in of the
admin pages: after five in ten minutes from one address, wrong tokens from there are answered `429` (with
`Retry-After`), and the sign-in page makes that address wait too. Requests through the server also count together:
after thirty in ten minutes, every wrong token through the server is answered `429` ([admin.md](admin.md)). On the
admin service's own port, on the server PC, only each address's own count applies.

What a token changes goes into the log of changes (Logs, Changes, or `GET /logs/changes`), under the admin's ID with the
token's name: `sena (nightly backup)`. A refused token goes there as a failed sign-in does, by `API` with the address it
came from: once per address in ten minutes, however many come. The token itself is never written anywhere.

## Requests and answers

- JSON in and out. A body is a JSON object, sent with `Content-Type: application/json`; a field the route does not take
  is refused.
- A list comes as `{"items": [...]}`, with what else the page shows beside it.
- Times are Unix times (seconds since 1970, UTC). The few others say so: `built_at` is the time a build's manifest
  writes (`YYYY-MM-DDTHH:MM:SS`), `day`, `since` and `month` are dates (`YYYY-MM-DD`, `YYYY-MM`), the `at` of a song in
  a past broadcast is seconds into its recording, and `duration_ms` is in milliseconds.
- Sizes are bytes, but the recordings' limit `cap_gb`, in GB. Accuracies are percentages.
- Text that a page cuts to its field's length is refused here (`400 bad_field`): a player's name past 20 characters,
  an account's note past 40. Each field's limit is in the reference.
- Words are in English, whatever language the pages are set to.
- No cookies and no form tokens. Answers are never cached on the way (`Cache-Control: no-store`).
- A player's number is the game's player id, as the site's `player.php?id=` takes it. A number in a path is a whole
  number from 0 to 9223372036854775807, the most the database keeps; a larger one names nothing (`404`).

## Errors

A request that cannot be done answers with its status and:

```json
{"error": {"code": "build_running", "message": "A build is already running."}}
```

`code` is a short word to test for; `message` says the same for a person. Each route lists its own in the reference.
One error says more beside them: `404 cannot_open` of `GET /setup/folder` names in `nearest` the folder the setup's
picker opens instead.

| Status | When | Codes include |
|:---:|:---|:---|
| `400` | The request is not right | `bad_json`, `bad_field`, `bad_query`, `bad_request` (a body that cannot be read at all), and each route's own (`bad_id`, `bad_host`, `network_path`...) |
| `401` | No token, or one that does not work | `no_token`, `bad_token`, `token_stopped` |
| `403` | A read token on a route of the write scope, or plain HTTP where HTTPS is needed | `read_only`, `use_https`, `no_https` |
| `404` | Nothing there | `not_found`, and the thing's own (`player_not_found`...) |
| `405` | Another method of the address | `method_not_allowed` (the `Allow` header lists those it takes) |
| `409` | It cannot be done as things are now | `stale`, `already_so`, `build_running`, `busy`, `own_account`, `would_delete`... |
| `412` | A download's `If-Match` names another file than the one there now | `precondition_failed` |
| `413` | An upload over its limit | `too_large` |
| `416` | The part of a download that `Range` asks for begins past its end | `range_not_satisfiable` |
| `422` | A file that fails its checks | `package_refused`, `not_backup` |
| `429` | A wrong token, after too many wrong tokens or passwords from here | `throttled` |
| `500` | It could not be done here (the message says why) | `backup_failed`, `upload_failed`, `stop_failed`, `song_action_failed`, `internal_error` |
| `503` | The admin pages are off, or the database or the game server cannot be reached | `admin_off`, `database_unavailable`, `server_down`, `server_unwell` |

`409 already_so` is what the pages do nothing for: enabling an account that is enabled, linking an account to the player
it is linked to. `409 stale` comes from a player's number that went to someone else (a deleted player's number goes to
the next new phone): send the player's `seen` value as `?seen=` with a change, and it happens only while the number
still belongs to the player you saw.

## Jobs

What takes longer than a request answers `202` with the job: an app build (`POST /builds`, `POST /setup/build`), an
import (`POST /setup/import`) and a restore (`POST /backups/{backup}/restore`). Ask `GET /jobs/{job}` until its state is
`done` or `failed`. Its `log` holds the last 200 lines of its output, and `why` says why it failed when that can be said
in words. A backup made, or a change to the songs, on the admin pages is a job there too (`backup`, `songs`), which
`GET /jobs` lists; through the API the same is done when it answers.

```json
{"job": {"id": "6b0c3e1a9f24", "kind": "build", "state": "running", "started": 1794200000, "log": ["patching ..."], "why": null, "host": "192.168.1.10"}}
```

Jobs live in the admin service's memory: it keeps its last twenty, and a restart of it forgets them.

Two routes answer `202` with no job, as what they start ends the admin service itself. `PUT /setup/address` starts
every program again for the new address: its answer's `instance` is this run's, and `GET /status` gives another once
the new one answers. `POST /server/stop` stops the server, the API with it.

## Uploads and downloads

Uploads go as `multipart/form-data`, checked as on the pages:

| Route | Field | File |
|:---|:---:|:---|
| `POST /songs` | `package` | A song package, `.zip`, 300 MB at most ([songs.md](songs.md)) |
| `POST /backups/upload` | `file` | A backup archive, `.tar.gz`, 1 GB at most |

Downloads are the file itself, with its own type: an app build (`.apk`), the installer for Windows (`.exe`), a backup
(`.tar.gz`, with a write token), a recording (MPEG-TS), its playlist and segments, the request log, the players and the
plays as spreadsheets (CSV, UTF-8), the app's icon and QR code.

The installer for Windows (`GET /app/windows`) goes on where a broken download stopped, as the site's `/windows` does.
It says `Accept-Ranges: bytes` and a strong `ETag`, which covers the server's details on the installer's end as well as
the installer: the same installer for another address or name is another file. One part asked with `Range` answers `206`
with its `Content-Range`, kept to the same file by `If-Range` (the whole otherwise, `200`) or by `If-Match` (`412`
otherwise); a part that begins past the end is `416`, with `Content-Range: bytes */length`.

## Examples

`API` is the address [Where it is](#where-it-is) gives: on the server PC the admin service's own port, from another
computer the one for that computer.

```sh
API=http://<server>:<port>/opendmtq/api/v1    # the address Where it is gives
TOKEN=odq_...    # made on the Accounts page
```

What the status page says, and whether the game server is well (`curl -f` fails when it is not):

```sh
curl -s -H "Authorization: Bearer $TOKEN" "$API/status"
curl -sf -H "Authorization: Bearer $TOKEN" "$API/status/health" > /dev/null && echo well
```

Build the app for this server's address, and wait for it:

```sh
job=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}' "$API/builds" \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["job"]["id"])')
while state=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/jobs/$job" | python3 -c 'import json, sys; print(json.load(sys.stdin)["job"]["state"])') \
  && [ "$state" = running ]; do sleep 2; done
echo "$state"
```

Add a song package:

```sh
curl -s -H "Authorization: Bearer $TOKEN" -F package=@mysong.zip "$API/songs"
```

Make a backup and keep a copy of it here (a write token):

```sh
name=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" "$API/backups" | python3 -c 'import json, sys; print(json.load(sys.stdin)["backup"]["name"])')
curl -s -H "Authorization: Bearer $TOKEN" -o "$name" "$API/backups/$name/download"
```

A song's charts, then one chart's leaderboard. A chart's number is the `chart` of one of the song's `charts`:

```sh
song=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/site/songs" | python3 -c 'import json, sys; print(json.load(sys.stdin)["items"][0]["id"])')
chart=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/site/songs/$song" | python3 -c 'import json, sys; print(json.load(sys.stdin)["charts"][0]["chart"])')
curl -s -H "Authorization: Bearer $TOKEN" "$API/site/charts/$chart/ranking"
```

Turn the maintenance notice on with a message, then off:

```sh
curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"message": "Back at 21:00."}' "$API/maintenance"
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$API/maintenance"
```

On Windows, in PowerShell on the server PC of the Windows bundle or a host install there: the status, then a backup kept
here.

```powershell
$Api = "http://<server>:<port>/opendmtq/api/v1"    # the address Where it is gives
$Auth = @{ Authorization = "Bearer odq_..." }    # made on the Accounts page
Invoke-RestMethod -Headers $Auth "$Api/status"
$backup = (Invoke-RestMethod -Method Post -Headers $Auth "$Api/backups").backup
Invoke-WebRequest -Headers $Auth -OutFile $backup.name "$Api/backups/$($backup.name)/download"
```

## The OpenAPI document

`GET /opendmtq/api/v1/openapi.json` answers without a token: it holds no data. It is OpenAPI 3.1, made from the same
route table as the API itself (`tools/opendmtq_tools/admin/api_routes.py`), with every route's parameters, body and
answers, for tools that read it (Swagger UI, code generators).

## Where it runs

The API is part of the admin service (`tools/opendmtq_tools/admin/api.py`), on the same port and behind the same rules
as the pages. Its routes come from the route table, which also makes the OpenAPI document and the reference below:
after a change to the table, write the reference again with
`python3 tools/opendmtq_tools/admin/api_routes.py docs/api.md`. The repository's checks fail while this page and the
table differ.

<!-- reference: made from tools/opendmtq_tools/admin/api_routes.py -->

## Reference

Every route, by the page it belongs to. Paths are under `/opendmtq/api/v1`. Every route needs a token except `GET /openapi.json`; the scope column says which. Besides its own refusals, every route can answer `401`, `429` and `503` as [Errors](#errors) says, and a route of the write scope `403` to a read token.

### Status

The status page: the game server, the numbers, the machine.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /openapi.json`](#get-openapijson) | none | This API's OpenAPI 3.1 document. No token: it holds no data. |
| [`GET /status`](#get-status) | read | What the status page says: the game server, the numbers, the backups, the app, the disk, what needs a look. |
| [`GET /status/health`](#get-statushealth) | read | The game server's health, asked now. |
| [`GET /status/machine`](#get-statusmachine) | read | The machine's processors, memory, disk and load, now and over the last day. |
| [`GET /status/activity`](#get-statusactivity) | read | What the status page's charts draw: plays by day and by hour, who plays most, the most played songs, records by grade. |

#### `GET /openapi.json`

This API's OpenAPI 3.1 document. No token: it holds no data.

Answer: `200` with the OpenAPI document.

#### `GET /status`

What the status page says: the game server, the numbers, the backups, the app, the disk, what needs a look.

Answer: `200` with [StatusFacts](#statusfacts).

#### `GET /status/health`

The game server's health, asked now. 200 while it answers that all is well, 503 otherwise: a monitor can go by the status alone.

Answer: `200` with [Health](#health).

Refusals:

- `503 server_down`: The game server does not answer.
- `503 server_unwell`: It answers that something is wrong (the message says what).

#### `GET /status/machine`

The machine's processors, memory, disk and load, now and over the last day.

Answer: `200` with [Machine](#machine).

#### `GET /status/activity`

What the status page's charts draw: plays by day and by hour, who plays most, the most played songs, records by grade.

Answer: `200` with [Activity](#activity).

### Jobs

Work that runs in the background: app builds, imports, restores.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /jobs`](#get-jobs) | read | The jobs this service keeps: its last twenty, and every one running. |
| [`GET /jobs/{job}`](#get-jobsjob) | read | One job: whether it runs, is done or failed, its output, why it failed. |

#### `GET /jobs`

The jobs this service keeps: its last twenty, and every one running. Jobs live in the admin service's memory: a restart of it forgets them.

Answer: `200` with [JobList](#joblist).

#### `GET /jobs/{job}`

One job: whether it runs, is done or failed, its output, why it failed.

Parameters:

- `job` (path, string): A job's id, as the answer that started it gives it.

Answer: `200` with [JobAnswer](#jobanswer).

Refusals:

- `404 job_not_found`: No such job (or it was forgotten in a restart).

### App

The App page: the app on offer, its builds, the way players get it.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /app`](#get-app) | read | The app players get: its build, whether it is right for this server, a build running now. |
| [`GET /app/windows`](#get-appwindows) | read | The installer for Windows as the site hands it to computers, set up for this server (its address on the installer's end). |
| [`GET /app/icon`](#get-appicon) | read | The launcher icon of the app on offer, as the builder kept it. |
| [`GET /builds`](#get-builds) | read | Every build of the app, newest first. |
| [`POST /builds`](#post-builds) | write | Starts a build of the app, as the App page's buttons do. |
| [`GET /builds/{file}`](#get-buildsfile) | read | One build. |
| [`GET /builds/{file}/download`](#get-buildsfiledownload) | read | One build's APK. |
| [`DELETE /builds/{file}`](#delete-buildsfile) | write | Deletes a build. |
| [`POST /builds/prune`](#post-buildsprune) | write | Deletes every build but the one the site offers. |
| [`GET /invite`](#get-invite) | read | The download page by the address all phones use, as the message to a new player has it. |
| [`GET /invite/qr`](#get-inviteqr) | read | The download page's QR code. |

#### `GET /app`

The app players get: its build, whether it is right for this server, a build running now.

Answer: `200` with [AppOnOffer](#apponoffer).

#### `GET /app/windows`

The installer for Windows as the site hands it to computers, set up for this server (its address on the installer's end). Whole, or the part a broken download asks for to go on, as the site hands it out: it says `Accept-Ranges: bytes` and a strong `ETag`, which covers the server's details on the installer's end as well as the installer. `Range: bytes=first-last` (or `first-`, or `-count` for the last bytes) asks for one part, answered 206 with its `Content-Range`; with `If-Range`, only while the ETag is the same (else the whole, 200). `If-Match` with another ETag is 412. Several parts in one Range get the whole.

Answer: `200` with the file itself (`application/vnd.microsoft.portable-executable`), or `206` with the part a Range header asks for.

Refusals:

- `404 not_found`: This server keeps no installer for Windows.
- `412 precondition_failed`: `If-Match` names another file than this server hands out now (another installer, or other details on its end): download it again from the start.
- `416 range_not_satisfiable`: The part asked for begins past the end; `Content-Range: bytes */length` says the length.

#### `GET /app/icon`

The launcher icon of the app on offer, as the builder kept it.

Answer: `200` with the file itself (`image/png`).

Refusals:

- `404 not_found`: No icon is kept.

#### `GET /builds`

Every build of the app, newest first.

Answer: `200` with [BuildList](#buildlist).

#### `POST /builds`

Starts a build of the app, as the App page's buttons do. Without host, for this server's address: the build the site then offers. With another address, a build kept for download that the site does not offer (for a test on another network).

Body (JSON):

- `host` (string, optional): The address to build for, as typed or pasted from a browser (host or host:port). Empty or left out: this server's.

Answer: `202` with [JobAnswer](#jobanswer).

Refusals:

- `400 bad_host`: Not an address.
- `409 build_running`: A build runs already.
- `409 busy`: An import runs, or the server's own build at its start (the message says which).
- `409 no_client`: No client to build from in data/apk/base.

#### `GET /builds/{file}`

One build.

Parameters:

- `file` (path, string): A build's file name, as the list of builds gives it (OpenDMTQ-&lt;address&gt;-v&lt;date&gt;.apk).

Answer: `200` with [BuildAnswer](#buildanswer).

Refusals:

- `404 build_not_found`: No such build.

#### `GET /builds/{file}/download`

One build's APK.

Parameters:

- `file` (path, string): A build's file name, as the list of builds gives it (OpenDMTQ-&lt;address&gt;-v&lt;date&gt;.apk).

Answer: `200` with the file itself (`application/vnd.android.package-archive`).

Refusals:

- `404 not_found`: No such build.

#### `DELETE /builds/{file}`

Deletes a build.

Parameters:

- `file` (path, string): A build's file name, as the list of builds gives it (OpenDMTQ-&lt;address&gt;-v&lt;date&gt;.apk).

Answer: `200` with [Deleted](#deleted).

Refusals:

- `404 build_not_found`: No such build.
- `409 on_offer`: It is the one the site offers.

#### `POST /builds/prune`

Deletes every build but the one the site offers.

Answer: `200` with [Pruned](#pruned).

Refusals:

- `409 build_running`: A build runs.
- `409 offer_unknown`: It cannot be told which build is on offer.

#### `GET /invite`

The download page by the address all phones use, as the message to a new player has it.

Answer: `200` with [Invite](#invite).

#### `GET /invite/qr`

The download page's QR code.

Answer: `200` with the file itself (`image/svg+xml`).

Refusals:

- `404 not_found`: No QR code yet: the builder makes it with the app.

### Songs

The Songs page.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /songs`](#get-songs) | read | Every song, hidden ones too, with where it came from and its plays. |
| [`POST /songs`](#post-songs) | write | Adds a song package (a .zip, 300 MB at most). |
| [`GET /songs/{song}`](#get-songssong) | read | One song. |
| [`POST /songs/{song}/hide`](#post-songssonghide) | write | Hides a song from the game's song list and the site. |
| [`POST /songs/{song}/show`](#post-songssongshow) | write | Shows a hidden song again. |
| [`DELETE /songs/{song}`](#delete-songssong) | write | Removes an added song. The game's own songs can only be hidden. |

#### `GET /songs`

Every song, hidden ones too, with where it came from and its plays.

Answer: `200` with [SongList](#songlist).

#### `POST /songs`

Adds a song package (a .zip, 300 MB at most). Its files are checked before the song is added, as on the Songs page ([songs.md](songs.md)).

Upload (multipart/form-data): `package`, the song package (.zip).

Answer: `201` with [SongAnswer](#songanswer).

Refusals:

- `400 no_package`: No .zip in the package field.
- `413 too_large`: Over 300 MB.
- `422 package_refused`: A file of it fails its checks (the message says which, and why).
- `500 song_action_failed`: It could not be added for another reason (the message says why).

#### `GET /songs/{song}`

One song.

Parameters:

- `song` (path, integer): A song's id.

Answer: `200` with [SongAnswer](#songanswer).

Refusals:

- `404 song_not_found`: No such song.

#### `POST /songs/{song}/hide`

Hides a song from the game's song list and the site. Phones get the new list at their next start.

Parameters:

- `song` (path, integer): A song's id.

Answer: `200` with [SongHidden](#songhidden).

Refusals:

- `404 song_not_found`: No such song.
- `500 song_action_failed`: The song list could not be made with it (nothing changed).

#### `POST /songs/{song}/show`

Shows a hidden song again. A song that is not there is no error: its old flag is taken away.

Parameters:

- `song` (path, integer): A song's id.

Answer: `200` with [SongHidden](#songhidden).

Refusals:

- `500 song_action_failed`: The song list could not be made with it (nothing changed).

#### `DELETE /songs/{song}`

Removes an added song. The game's own songs can only be hidden.

Parameters:

- `song` (path, integer): A song's id.

Answer: `200` with [Deleted](#deleted).

Refusals:

- `404 song_not_found`: No such song.
- `409 not_added`: One of the game's own songs.
- `500 song_action_failed`: The song list could not be made without it.

### Maintenance

The Maintenance page: the notice, and stopping the server.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /maintenance`](#get-maintenance) | read | The in-game maintenance notice: on or off, and what it says. |
| [`PUT /maintenance`](#put-maintenance) | write | Turns the notice on, or changes what it says while it is on. |
| [`DELETE /maintenance`](#delete-maintenance) | write | Turns the notice off. |
| [`POST /server/stop`](#post-serverstop) | write | Stops the server, as the Maintenance page's Stop the server does. |

#### `GET /maintenance`

The in-game maintenance notice: on or off, and what it says.

Answer: `200` with [Notice](#notice).

#### `PUT /maintenance`

Turns the notice on, or changes what it says while it is on. Players then see it when the game starts, and cannot play; the site shows it too.

Body (JSON):

- `message` (string, optional): What it says, 200 characters at most (a line break is one). Empty or left out: the usual words.

Answer: `200` with [Notice](#notice).

Refusals:

- `400 message_too_long`: The message is longer than 200 characters.

#### `DELETE /maintenance`

Turns the notice off.

Answer: `200` with [Notice](#notice).

#### `POST /server/stop`

Stops the server, as the Maintenance page's Stop the server does. A host install and the Windows bundle only. Every part stops, these pages and the API too: the answer comes first.

Answer: `202` with [Stopping](#stopping).

Refusals:

- `404 host_only`: Not a host install: stop it with ./opendmtq down or Kubernetes.
- `500 stop_failed`: The stop could not be asked for (the message says why).

### Players

The Players page.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /players`](#get-players) | read | Every player, with how they have been playing and their broadcast. |
| [`GET /players/download`](#get-playersdownload) | read | Every player as a spreadsheet (CSV, UTF-8). |
| [`GET /players/{player}`](#get-playersplayer) | read | One player. |
| [`POST /players/{player}/rename`](#post-playersplayerrename) | write | Renames a player, on every phone of theirs. |
| [`POST /players/{player}/reset`](#post-playersplayerreset) | write | Resets a player's records: their scores, plays and achievements. |
| [`DELETE /players/{player}`](#delete-playersplayer) | write | Deletes a player, with their records, broadcast and recordings. |
| [`POST /players/{player}/live`](#post-playersplayerlive) | write | Turns a player's broadcast on. |
| [`DELETE /players/{player}/live`](#delete-playersplayerlive) | write | Turns a player's broadcast off. |

#### `GET /players`

Every player, with how they have been playing and their broadcast.

Answer: `200` with [PlayerList](#playerlist).

#### `GET /players/download`

Every player as a spreadsheet (CSV, UTF-8).

Answer: `200` with the file itself (`text/csv`).

#### `GET /players/{player}`

One player.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).

Answer: `200` with [PlayerAnswer](#playeranswer).

Refusals:

- `404 player_not_found`: No such player.

#### `POST /players/{player}/rename`

Renames a player, on every phone of theirs.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).
- `seen` (query, string, optional): The player's seen value from the list. When given, the change happens only while the number still belongs to the same player (409 stale otherwise). A deleted player's number goes to the next new phone.

Body (JSON):

- `name` (string, 20 characters at most): The new name. The Players page cuts a longer one; here it is refused. Empty: Player &lt;n&gt; again.

Answer: `200` with [PlayerAnswer](#playeranswer).

Refusals:

- `400 bad_field`: A name over 20 characters.
- `404 player_not_found`: No such player.
- `409 stale`: The number belongs to someone else now.
- `409 same_name`: That is the name already.

#### `POST /players/{player}/reset`

Resets a player's records: their scores, plays and achievements. A backup is made first; without it nothing changes.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).
- `seen` (query, string, optional): The player's seen value from the list. When given, the change happens only while the number still belongs to the same player (409 stale otherwise). A deleted player's number goes to the next new phone.

Answer: `200` with [PlayerReset](#playerreset).

Refusals:

- `404 player_not_found`: No such player.
- `409 stale`: The number belongs to someone else now.
- `500 backup_failed`: The backup could not be made (the message says why).

#### `DELETE /players/{player}`

Deletes a player, with their records, broadcast and recordings. A backup is made first; without it nothing changes.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).
- `seen` (query, string, optional): The player's seen value from the list. When given, the change happens only while the number still belongs to the same player (409 stale otherwise). A deleted player's number goes to the next new phone.

Answer: `200` with [PlayerDeleted](#playerdeleted).

Refusals:

- `404 player_not_found`: No such player.
- `409 stale`: The number belongs to someone else now.
- `500 backup_failed`: The backup could not be made (the message says why).

#### `POST /players/{player}/live`

Turns a player's broadcast on. The phone gets a new upload key and a line between songs that says so ([live.md](live.md)).

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).
- `seen` (query, string, optional): The player's seen value from the list. When given, the change happens only while the number still belongs to the same player (409 stale otherwise). A deleted player's number goes to the next new phone.

Answer: `200` with [PlayerAnswer](#playeranswer).

Refusals:

- `404 player_not_found`: No such player.
- `409 stale`: The number belongs to someone else now.

#### `DELETE /players/{player}/live`

Turns a player's broadcast off. The phone's next upload is refused, the live window goes at once and the recording is closed and kept.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).
- `seen` (query, string, optional): The player's seen value from the list. When given, the change happens only while the number still belongs to the same player (409 stale otherwise). A deleted player's number goes to the next new phone.

Answer: `200` with [PlayerAnswer](#playeranswer).

Refusals:

- `404 player_not_found`: No such player.
- `409 stale`: The number belongs to someone else now.

### Accounts

The Accounts page: the site's accounts.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /accounts`](#get-accounts) | read | Every account of the site, and the players an account can be linked to. |
| [`POST /accounts`](#post-accounts) | write | Makes an account. |
| [`GET /accounts/{account}`](#get-accountsaccount) | read | One account. |
| [`POST /accounts/{account}/password`](#post-accountsaccountpassword) | write | Makes a new password for an account. |
| [`POST /accounts/{account}/disable`](#post-accountsaccountdisable) | write | Disables an account: it cannot sign in until enabled again. |
| [`POST /accounts/{account}/enable`](#post-accountsaccountenable) | write | Enables an account again. |
| [`POST /accounts/{account}/make-admin`](#post-accountsaccountmake-admin) | write | Gives an account admin rights: it opens the admin pages too. |
| [`POST /accounts/{account}/make-player`](#post-accountsaccountmake-player) | write | Takes an account's admin rights away: it opens the site only. |
| [`POST /accounts/{account}/link`](#post-accountsaccountlink) | write | Links an account to the game player it is, or unlinks it. |
| [`DELETE /accounts/{account}`](#delete-accountsaccount) | write | Deletes an account, and its tokens. |

#### `GET /accounts`

Every account of the site, and the players an account can be linked to.

Answer: `200` with [AccountList](#accountlist).

#### `POST /accounts`

Makes an account. Its password is made when none is sent, and comes back this once, with the message to send.

Body (JSON):

- `name` (string): Its ID: 3 to 20 Latin letters, digits, dots, dashes or underscores.
- `password` (string, optional): Its password, 6 to 64 characters, 10 at least with admin rights. Left out or empty: one is made.
- `note` (string, optional, 40 characters at most): Whom it is for. The Accounts page cuts a longer one; here it is refused.
- `admin` (boolean, optional): True to open the admin pages to it too.
- `player` (integer, or null, optional): The game player it is.

Answer: `201` with [AccountPassword](#accountpassword).

Refusals:

- `400 bad_id`: Not an ID.
- `400 bad_password`: Not 6 to 64 characters, or under 10 with admin rights.
- `400 bad_player`: No such player.
- `400 bad_field`: A note over 40 characters.
- `409 id_taken`: The ID is taken (by an account in any letter case, or the owner's).

#### `GET /accounts/{account}`

One account.

Parameters:

- `account` (path, string): An account's ID, in any letter case.

Answer: `200` with [AccountAnswer](#accountanswer).

Refusals:

- `404 account_not_found`: No such account.

#### `POST /accounts/{account}/password`

Makes a new password for an account. The old one stops working and its sign-ins end; the new one comes back this once. A token's own account keeps its tokens.

Parameters:

- `account` (path, string): An account's ID, in any letter case.

Answer: `200` with [AccountPassword](#accountpassword).

Refusals:

- `404 account_not_found`: No such account.

#### `POST /accounts/{account}/disable`

Disables an account: it cannot sign in until enabled again. Its sign-ins end, and an admin's tokens stop working.

Parameters:

- `account` (path, string): An account's ID, in any letter case.

Answer: `200` with [AccountAnswer](#accountanswer).

Refusals:

- `404 account_not_found`: No such account.
- `409 already_so`: It is disabled already.
- `409 own_account`: The token's own account: for another admin, or the owner.

#### `POST /accounts/{account}/enable`

Enables an account again.

Parameters:

- `account` (path, string): An account's ID, in any letter case.

Answer: `200` with [AccountAnswer](#accountanswer).

Refusals:

- `404 account_not_found`: No such account.
- `409 already_so`: It is enabled already.
- `409 own_account`: The token's own account.

#### `POST /accounts/{account}/make-admin`

Gives an account admin rights: it opens the admin pages too.

Parameters:

- `account` (path, string): An account's ID, in any letter case.

Answer: `200` with [AccountAnswer](#accountanswer).

Refusals:

- `404 account_not_found`: No such account.
- `409 already_so`: It has them already.
- `409 own_account`: The token's own account.

#### `POST /accounts/{account}/make-player`

Takes an account's admin rights away: it opens the site only. Its sessions on the admin pages end, and its tokens stop working.

Parameters:

- `account` (path, string): An account's ID, in any letter case.

Answer: `200` with [AccountAnswer](#accountanswer).

Refusals:

- `404 account_not_found`: No such account.
- `409 already_so`: It has none.
- `409 own_account`: The token's own account.

#### `POST /accounts/{account}/link`

Links an account to the game player it is, or unlinks it. The site then shows that player's name for it and marks their places.

Parameters:

- `account` (path, string): An account's ID, in any letter case.

Body (JSON):

- `player` (integer, or null): The player's number; null to unlink.

Answer: `200` with [AccountAnswer](#accountanswer).

Refusals:

- `404 account_not_found`: No such account.
- `400 bad_player`: No such player.
- `409 already_so`: It is linked so already.

#### `DELETE /accounts/{account}`

Deletes an account, and its tokens.

Parameters:

- `account` (path, string): An account's ID, in any letter case.

Answer: `200` with [Deleted](#deleted).

Refusals:

- `404 account_not_found`: No such account.
- `409 own_account`: The token's own account.

### Tokens

The Accounts page: the API's tokens.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /tokens`](#get-tokens) | read | Every API token, with whose it is and whether it works. Never the tokens themselves. |
| [`POST /tokens`](#post-tokens) | write | Makes a token for the same admin as the token that asks. |
| [`DELETE /tokens/{token}`](#delete-tokenstoken) | write | Revokes a token for good. It may be the token that asks. |

#### `GET /tokens`

Every API token, with whose it is and whether it works. Never the tokens themselves.

Answer: `200` with [TokenList](#tokenlist).

#### `POST /tokens`

Makes a token for the same admin as the token that asks. The token comes back this once; only its hash is kept.

Body (JSON):

- `name` (string): What it is for, 1 to 40 characters.
- `scope` (string): What it may do: read only answers GET, and not a backup's download or a look at the server PC's folders. One of `read`, `write`.

Answer: `201` with [TokenMade](#tokenmade).

Refusals:

- `400 bad_name`: No name, or one over 40 characters.

#### `DELETE /tokens/{token}`

Revokes a token for good. It may be the token that asks.

Parameters:

- `token` (path, string): A token's id (the 12 hex digits after odq_ in the token).

Answer: `200` with [Deleted](#deleted).

Refusals:

- `404 token_not_found`: No such token.

### Broadcasts

The Broadcasts page's top: broadcasts on or off for the server, and their settings.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /broadcasts`](#get-broadcasts) | read | The server's broadcasts: on or off, what new players start with, the quality, and who is switched on and on air. |
| [`PUT /broadcasts`](#put-broadcasts) | write | Turns broadcasts on or off for the server, sets what new players start with and the quality. |

#### `GET /broadcasts`

The server's broadcasts: on or off, what new players start with, the quality, and who is switched on and on air.

Answer: `200` with [BroadcastSettings](#broadcastsettings).

#### `PUT /broadcasts`

Turns broadcasts on or off for the server, sets what new players start with and the quality. What is left out stays as it is. Off: phones and PCs send nothing and the site shows nothing of broadcasts; each player's switch is kept, whoever is on air is told once in the game that the broadcast ended, every live window goes at once and running recordings are closed. On: each player switched on is told in the game, between songs. New players turned to start on: every player already there counts as chosen for, so only those who come after start on. Phones and the PC player follow a new quality within 15 seconds.

Body (JSON):

- `on` (boolean, optional): Broadcasts on or off for the server.
- `new_players` (boolean, optional): Whether a new player's switch starts on.
- `quality` (string, optional): light, standard, smooth or sharp. One of `light`, `standard`, `smooth`, `sharp`.

Answer: `200` with [BroadcastSettings](#broadcastsettings).

Refusals:

- `400 bad_body`: None of the three was sent.
- `400 bad_field`: A quality there is not.

### Recordings

The Broadcasts page's recordings.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /recordings`](#get-recordings) | read | Every recording of a broadcast, newest first. |
| [`GET /recordings/limits`](#get-recordingslimits) | read | The limits the recordings are kept to, and how much of the disk they take. |
| [`PUT /recordings/limits`](#put-recordingslimits) | write | Sets the limits: a total size and an age. |
| [`POST /recordings/delete`](#post-recordingsdelete) | write | Deletes recordings: those named, or all of one player's. |
| [`GET /recordings/{player}/{recording}`](#get-recordingsplayerrecording) | read | One recording and its files. |
| [`GET /recordings/{player}/{recording}/download`](#get-recordingsplayerrecordingdownload) | read | A recording as one MPEG-TS file. |
| [`GET /recordings/{player}/{recording}/files/{part}`](#get-recordingsplayerrecordingfilespart) | read | A recording's playlist or one of its segments, for a player such as hls.js. |
| [`POST /recordings/{player}/{recording}/hide`](#post-recordingsplayerrecordinghide) | write | Hides a recording from players. |
| [`POST /recordings/{player}/{recording}/show`](#post-recordingsplayerrecordingshow) | write | Shows a hidden recording to players again. |
| [`DELETE /recordings/{player}/{recording}`](#delete-recordingsplayerrecording) | write | Deletes a recording. |

#### `GET /recordings`

Every recording of a broadcast, newest first.

Answer: `200` with [RecordingList](#recordinglist).

#### `GET /recordings/limits`

The limits the recordings are kept to, and how much of the disk they take.

Answer: `200` with [Limits](#limits).

#### `PUT /recordings/limits`

Sets the limits: a total size and an age. Lower limits delete recordings at once and for good. Without confirm they are refused with what they would delete.

Body (JSON):

- `cap_gb` (number): Their total size at most, in GB (0.001 to 1000000).
- `days` (integer): Their age at most, in days (1 to 36500).
- `confirm` (boolean, optional): True to save limits that delete recordings.

Answer: `200` with [Limits](#limits).

Refusals:

- `400 bad_limits`: Not numbers in those ranges.
- `409 would_delete`: They would delete recordings (the message says how many), and confirm was not true.

#### `POST /recordings/delete`

Deletes recordings: those named, or all of one player's. A recording still being made is kept.

Body (JSON):

- `items` (list of string, optional): The recordings, as &lt;player&gt;/&lt;id&gt; (their key).
- `player` (integer, optional): A player whose every recording goes.

Answer: `200` with [RecordingsDone](#recordingsdone).

Refusals:

- `400 bad_body`: Neither items nor player, or both.
- `404 recording_not_found`: None of them is there.
- `409 recording_open`: They are all still being made.

#### `GET /recordings/{player}/{recording}`

One recording and its files.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).
- `recording` (path, integer): A recording's id: the moment it began, in seconds since 1970.

Answer: `200` with [RecordingFiles](#recordingfiles).

Refusals:

- `404 recording_not_found`: No such recording.

#### `GET /recordings/{player}/{recording}/download`

A recording as one MPEG-TS file.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).
- `recording` (path, integer): A recording's id: the moment it began, in seconds since 1970.

Answer: `200` with the file itself (`video/mp2t`).

Refusals:

- `404 not_found`: No such recording, or one still being made.

#### `GET /recordings/{player}/{recording}/files/{part}`

A recording's playlist or one of its segments, for a player such as hls.js.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).
- `recording` (path, integer): A recording's id: the moment it began, in seconds since 1970.
- `part` (path, string): A recording's playlist (index.m3u8) or one of its segments (&lt;n&gt;.ts).

Answer: `200` with the file itself (`application/vnd.apple.mpegurl` or `video/mp2t`).

Refusals:

- `404 not_found`: No such file.

#### `POST /recordings/{player}/{recording}/hide`

Hides a recording from players.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).
- `recording` (path, integer): A recording's id: the moment it began, in seconds since 1970.

Answer: `200` with [RecordingAnswer](#recordinganswer).

Refusals:

- `404 recording_not_found`: No such recording.

#### `POST /recordings/{player}/{recording}/show`

Shows a hidden recording to players again.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).
- `recording` (path, integer): A recording's id: the moment it began, in seconds since 1970.

Answer: `200` with [RecordingAnswer](#recordinganswer).

Refusals:

- `404 recording_not_found`: No such recording.

#### `DELETE /recordings/{player}/{recording}`

Deletes a recording.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).
- `recording` (path, integer): A recording's id: the moment it began, in seconds since 1970.

Answer: `200` with [Deleted](#deleted).

Refusals:

- `404 recording_not_found`: No such recording.
- `409 recording_open`: It is still being made.

### Backups

The Backups page.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /backups`](#get-backups) | read | Every backup, newest first. |
| [`POST /backups`](#post-backups) | write | Makes a backup now: the database, the signing key and the added songs. |
| [`POST /backups/upload`](#post-backupsupload) | write | Brings in a backup archive (.tar.gz, 1 GB at most) from elsewhere. |
| [`GET /backups/auto`](#get-backupsauto) | read | The daily backup: on or off, those kept, when the next comes. |
| [`PUT /backups/auto`](#put-backupsauto) | write | Turns the daily backup on or off. |
| [`GET /backups/{backup}/download`](#get-backupsbackupdownload) | write | A backup archive. |
| [`POST /backups/{backup}/restore`](#post-backupsbackuprestore) | write | Restores a backup while the server runs. |
| [`DELETE /backups/{backup}`](#delete-backupsbackup) | write | Deletes a backup. |

#### `GET /backups`

Every backup, newest first.

Answer: `200` with [BackupList](#backuplist).

#### `POST /backups`

Makes a backup now: the database, the signing key and the added songs.

Answer: `201` with [BackupAnswer](#backupanswer).

Refusals:

- `409 busy`: A restore runs.
- `500 backup_failed`: It could not be made (the message says why: a full disk, a busy database).

#### `POST /backups/upload`

Brings in a backup archive (.tar.gz, 1 GB at most) from elsewhere. It joins the list; POST /backups/{backup}/restore puts it in place.

Upload (multipart/form-data): `file`, the backup archive (.tar.gz).

Answer: `201` with [BackupAnswer](#backupanswer).

Refusals:

- `400 no_file`: No .tar.gz in the file field.
- `413 too_large`: Over 1 GB.
- `422 not_backup`: Not a backup: no database in it.
- `500 upload_failed`: It could not be kept (a full disk).

#### `GET /backups/auto`

The daily backup: on or off, those kept, when the next comes.

Answer: `200` with [DailyBackup](#dailybackup).

#### `PUT /backups/auto`

Turns the daily backup on or off.

Body (JSON):

- `on` (boolean): True for on.

Answer: `200` with [DailyBackup](#dailybackup).

#### `GET /backups/{backup}/download`

A backup archive. A write token's: it holds the accounts' password hashes and the app's signing key, more than a token that only watches may take away. Keep it where only you can read it.

Parameters:

- `backup` (path, string): A backup's file name, as the list of backups gives it.

Answer: `200` with the file itself (`application/gzip`).

Refusals:

- `404 backup_not_found`: No such backup.

#### `POST /backups/{backup}/restore`

Restores a backup while the server runs. The current state is backed up first. Who is broadcasting, the site's accounts and the API's tokens stay as they are now: they are put into the restored database before it takes the current one's place. A server with no account yet takes the backup's.

Parameters:

- `backup` (path, string): A backup's file name, as the list of backups gives it.

Answer: `202` with [JobAnswer](#jobanswer).

Refusals:

- `404 backup_not_found`: No such backup.
- `409 busy`: Another restore runs.

#### `DELETE /backups/{backup}`

Deletes a backup.

Parameters:

- `backup` (path, string): A backup's file name, as the list of backups gives it.

Answer: `200` with [Deleted](#deleted).

Refusals:

- `404 backup_not_found`: No such backup.

### Logs

The Logs page: requests, plays, changes.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /logs/requests`](#get-logsrequests) | read | The server's requests, filtered as on the Requests tab, with the last 24 hours added up. |
| [`GET /logs/requests/download`](#get-logsrequestsdownload) | read | All of the request log that is kept, as one file, oldest first. |
| [`GET /logs/plays`](#get-logsplays) | read | Every play, filtered as on the Plays tab, a page of 50 at a time, with what they add up to. |
| [`GET /logs/plays/download`](#get-logsplaysdownload) | read | Every play the filter leaves, all its pages in one spreadsheet (CSV, UTF-8). |
| [`GET /logs/changes`](#get-logschanges) | read | What was changed on the admin pages and through the API, sign-ins too. |

#### `GET /logs/requests`

The server's requests, filtered as on the Requests tab, with the last 24 hours added up.

Parameters:

- `q` (query, string, optional): Words the request's line holds.
- `status` (query, string, optional): Its result: a class, or err for every failure. One of `err`, `2xx`, `3xx`, `4xx`, `5xx`.
- `kind` (query, string, optional): What it was for. One of `game`, `files`, `app`, `site`, `live`, `admin`, `other`.
- `limit` (query, integer, optional): How many to list, 1 to 400 (400).

Answer: `200` with [RequestLog](#requestlog).

Refusals:

- `400 bad_query`: A filter that is not one of its values.

#### `GET /logs/requests/download`

All of the request log that is kept, as one file, oldest first.

Answer: `200` with the file itself (`text/plain`).

#### `GET /logs/plays`

Every play, filtered as on the Plays tab, a page of 50 at a time, with what they add up to.

Parameters:

- `q` (query, string, optional): Words the player's name, the song or the chart holds.
- `player` (query, integer, optional): One player's plays. A player with none gives none (the Plays tab shows every play then, as its list of players has no such name).
- `from` (query, string, optional): From this day (YYYY-MM-DD), on this server's clock.
- `to` (query, string, optional): To this day, the whole of it.
- `page` (query, integer, optional): The page (1). Past the last, the last.

Answer: `200` with [PlayLog](#playlog).

Refusals:

- `400 bad_query`: A day that is not YYYY-MM-DD, or a player or page that is not a number.

#### `GET /logs/plays/download`

Every play the filter leaves, all its pages in one spreadsheet (CSV, UTF-8).

Parameters:

- `q` (query, string, optional): As for /logs/plays.
- `player` (query, integer, optional): As for /logs/plays.
- `from` (query, string, optional): As for /logs/plays.
- `to` (query, string, optional): As for /logs/plays.

Answer: `200` with the file itself (`text/csv`).

Refusals:

- `400 bad_query`: As for /logs/plays.

#### `GET /logs/changes`

What was changed on the admin pages and through the API, sign-ins too.

Answer: `200` with [ChangeList](#changelist).

### Setup

The setup's four steps.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /setup`](#get-setup) | read | The setup's four steps: what each has and whether it is done. |
| [`GET /setup/found`](#get-setupfound) | read | The game's files found on the server PC: in the home folder, Downloads, the Desktop, Documents and OneDrive's folders. |
| [`GET /setup/folder`](#get-setupfolder) | write | A folder of the server PC, as the setup's folder picker shows it. |
| [`GET /setup/what`](#get-setupwhat) | write | What one file or folder of the server PC is to the import. |
| [`POST /setup/import`](#post-setupimport) | write | Imports the game's files from a folder or file on the server PC: the app, the client data, the song data. |
| [`PUT /setup/address`](#put-setupaddress) | write | Changes the address phones use to another private address of the server PC, and starts the server again for it. |
| [`POST /setup/player`](#post-setupplayer) | write | Makes an account for a player, as the setup's players step does: its password is made. |
| [`POST /setup/build`](#post-setupbuild) | write | Builds the app for this server's address, as the setup's last step does. |

#### `GET /setup`

The setup's four steps: what each has and whether it is done.

Answer: `200` with [SetupState](#setupstate).

#### `GET /setup/found`

The game's files found on the server PC: in the home folder, Downloads, the Desktop, Documents and OneDrive's folders. A host install only. Each of those places is looked in, and each folder in it.

Answer: `200` with [FoundList](#foundlist).

Refusals:

- `404 host_only`: Not a host install.

#### `GET /setup/folder`

A folder of the server PC, as the setup's folder picker shows it. A host install only, and a write token's: any folder the server can read. A file's path gives its folder, with the file picked. With it the places the picker goes to in one step, as the setup page shows them.

Parameters:

- `path` (query, string, optional): The folder, as typed or pasted: quotes around it go, and ~ is the home folder. $NAME and %NAME% stay as they are written. A path on another computer is refused, and on Windows any path but a drive letter's. Left out: Downloads.

Answer: `200` with [Folder](#folder).

Refusals:

- `404 host_only`: Not a host install.
- `400 network_path`: A path on another computer (a network share), or on Windows not a drive letter's.
- `404 cannot_open`: The folder is not there, or cannot be read: nearest names the folder the page opens instead.

#### `GET /setup/what`

What one file or folder of the server PC is to the import. A host install only, and a write token's, as for /setup/folder. An archive's look can take 7-Zip a second.

Parameters:

- `path` (query, string): The file or folder, as for /setup/folder.

Answer: `200` with [What](#what).

Refusals:

- `404 host_only`: Not a host install.
- `400 network_path`: A path on another computer (a network share), or on Windows not a drive letter's.

#### `POST /setup/import`

Imports the game's files from a folder or file on the server PC: the app, the client data, the song data. A host install only. Then the song list is made. Song data alone is imported as the songs whatever songs says.

Body (JSON):

- `path` (string): The folder or file.
- `songs` (boolean, optional): True (the default) to import the song data too.

Answer: `202` with [JobAnswer](#jobanswer).

Refusals:

- `404 host_only`: Not a host install: use ./opendmtq import.
- `400 no_path`: No path.
- `400 network_path`: A path on another computer (a network share), or on Windows not a drive letter's.
- `404 path_not_found`: Nothing at the path.
- `400 cannot_read`: It cannot be read.
- `400 too_wide`: A whole drive or the home folder.
- `409 busy`: An import or a build runs.

#### `PUT /setup/address`

Changes the address phones use to another private address of the server PC, and starts the server again for it. A host install only. The port stays as it is. The app is built for the new address at the start.

Body (JSON):

- `address` (string): A private IPv4 address: one of the choices GET /setup gives, or any other private address, as the setup page takes one typed. Loopback and link-local addresses are refused; the address is not checked against the ones this PC has.

Answer: `202` with [Restarting](#restarting).

Refusals:

- `404 host_only`: Not a host install: use ./opendmtq host.
- `400 bad_address`: Not a private address phones can reach.
- `409 same_address`: The server uses it already.
- `409 busy`: An import or a build runs.

#### `POST /setup/player`

Makes an account for a player, as the setup's players step does: its password is made.

Body (JSON):

- `name` (string): Its ID: 3 to 20 Latin letters, digits, dots, dashes or underscores.

Answer: `201` with [AccountPassword](#accountpassword).

Refusals:

- `400 bad_id`: Not an ID.
- `409 id_taken`: The ID is taken.

#### `POST /setup/build`

Builds the app for this server's address, as the setup's last step does.

Answer: `202` with [JobAnswer](#jobanswer).

Refusals:

- `409 no_client`: No client to build from.
- `409 build_running`: A build runs already.
- `409 busy`: An import runs.

### Site

What the players' site shows.

| Route | Scope | What it does |
|:---|:---:|:---|
| [`GET /site/home`](#get-sitehome) | read | The home page: the app, the best players, the newest records, the broadcasts. |
| [`GET /site/songs`](#get-sitesongs) | read | The song list players see, by title, with the records on each. |
| [`GET /site/songs/{song}`](#get-sitesongssong) | read | A song's page: the song, who made it, its charts. |
| [`GET /site/charts/{chart}/ranking`](#get-sitechartschartranking) | read | A chart's leaderboard: the best 100. |
| [`GET /site/rankings`](#get-siterankings) | read | The rankings, by a tab of the rankings page. |
| [`GET /site/rankings/month`](#get-siterankingsmonth) | read | This month's rankings, as the game ranks them, and the months before. |
| [`GET /site/players/{player}`](#get-siteplayersplayer) | read | A player's page: figures, rank, grades, the last 12 weeks, levels, recent plays, broadcasts. |
| [`GET /site/players/{player}/records`](#get-siteplayersplayerrecords) | read | A player's best records, all of them. |
| [`GET /site/plays/recent`](#get-siteplaysrecent) | read | The newest plays, or the newest records as the home page lists them. |
| [`GET /site/live`](#get-sitelive) | read | Who is on air now, and the recordings players may watch. |
| [`GET /site/live/{player}/files/{part}`](#get-siteliveplayerfilespart) | read | A broadcast's live playlist or one of its segments, as the live page plays them. |

#### `GET /site/home`

The home page: the app, the best players, the newest records, the broadcasts.

Answer: `200` with [SiteHome](#sitehome).

#### `GET /site/songs`

The song list players see, by title, with the records on each.

Answer: `200` with [SiteSongList](#sitesonglist).

#### `GET /site/songs/{song}`

A song's page: the song, who made it, its charts.

Parameters:

- `song` (path, integer): A song's id.

Answer: `200` with [SiteSongPage](#sitesongpage).

Refusals:

- `404 song_not_found`: No such song.

#### `GET /site/charts/{chart}/ranking`

A chart's leaderboard: the best 100.

Parameters:

- `chart` (path, integer): A chart's id (the song list's pattern id).

Answer: `200` with [Board](#board).

Refusals:

- `404 chart_not_found`: No such chart.

#### `GET /site/rankings`

The rankings, by a tab of the rankings page.

Parameters:

- `sort` (query, string, optional): The tab: total best score (the default), S grades, perfect plays, charts played. One of `total`, `s_count`, `perfect`, `charts`.

Answer: `200` with [Rankings](#rankings).

Refusals:

- `400 bad_query`: Not one of the tabs.

#### `GET /site/rankings/month`

This month's rankings, as the game ranks them, and the months before.

Answer: `200` with [MonthRankings](#monthrankings).

#### `GET /site/players/{player}`

A player's page: figures, rank, grades, the last 12 weeks, levels, recent plays, broadcasts.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).

Answer: `200` with [SitePlayer](#siteplayer).

Refusals:

- `404 player_not_found`: No such player.

#### `GET /site/players/{player}/records`

A player's best records, all of them.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).

Answer: `200` with [SiteRecords](#siterecords).

Refusals:

- `404 player_not_found`: No such player.

#### `GET /site/plays/recent`

The newest plays, or the newest records as the home page lists them.

Parameters:

- `records` (query, boolean, optional): true: new records only, each with the best before it.
- `player` (query, integer, optional): One player's only.
- `limit` (query, integer, optional): How many, 1 to 100 (20).

Answer: `200` with [SitePlays](#siteplays).

Refusals:

- `400 bad_query`: A limit or a player that is not a number.

#### `GET /site/live`

Who is on air now, and the recordings players may watch.

Answer: `200` with [SiteLive](#sitelive).

#### `GET /site/live/{player}/files/{part}`

A broadcast's live playlist or one of its segments, as the live page plays them. Only while the player's broadcast is switched on. The playlist names its segments relatively, so a player such as hls.js asks for them here too; after 30 seconds without video it ends.

Parameters:

- `player` (path, integer): A player's number (the game's player id, which the site's player.php?id= takes too).
- `part` (path, string): The live playlist (index.m3u8) or one of the segments it names (&lt;n&gt;.ts), while the broadcast runs.

Answer: `200` with the file itself (`application/vnd.apple.mpegurl` or `video/mp2t`).

Refusals:

- `404 not_found`: The broadcast is off, or no such file.

### Shapes

The objects the routes answer with. A field marked optional comes only with some answers.

#### Error

What every refusal answers.

- `error` ([ErrorBody](#errorbody)): The refusal.

#### ErrorBody

A refusal.

- `code` (string): What went wrong, as a short word (snake_case). Each route lists its own.
- `message` (string): The same in an English sentence, for a person.
- `nearest` (string, optional): With 404 cannot_open from GET /setup/folder: the folder the setup's picker opens instead, the nearest one above that can be read.

#### Job

Work that runs in the background: an app build, an import, a restore, and on the admin pages a backup made or a change to the songs.

- `id` (string): Its id, for GET /jobs/{job}.
- `kind` (string): What it does. One of `build`, `import`, `restore`, `backup`, `songs`.
- `state` (string): Where it is. One of `running`, `done`, `failed`.
- `started` (integer): When it started (Unix time).
- `log` (list of string): Its last 200 lines of output.
- `why` (string, or null): Why it failed, when that can be said in words.
- `host` (string, optional): A build's address.
- `path` (string, optional): An import's folder or file on the server PC.
- `backup` (string, optional): A restore's backup.

#### JobAnswer

A job.

- `job` ([Job](#job)): The job.

#### JobList

The jobs this service keeps.

- `items` (list of [Job](#job)): The last twenty, and every one running, newest first.

#### StatusFacts

What the status page says.

- `version` (string, or null): The version of OpenDMTQ this server runs, when known.
- `address` (string): The address phones use (PUBLIC_HOST).
- `instance` (string): Which run of the admin service answers: it changes when the service starts again.
- `game_server` ([GameServer](#gameserver)): How the game server answered just now.
- `counts` ([Counts](#counts), or null): The numbers; null while the database cannot be read.
- `recent` (list of [DashPlay](#dashplay)): The newest plays.
- `backups` ([BackupFacts](#backupfacts)): The backups made here.
- `app` ([AppFacts](#appfacts)): The app on offer.
- `maintenance` (boolean): True while the maintenance notice is on.
- `recordings` (integer): How many recordings are kept, counted with the disk's figures: at most every minute, and again after one is deleted.
- `disk` ([Disk](#disk)): The data disk.
- `attention` (list of [Attention](#attention)): What needs a look, as the status page lists it.

#### GameServer

The game server's health, as the status page reads it.

- `answering` (boolean): True when it answered.
- `ok` (boolean): True when it answered that all is well.
- `problem` (string, or null): What it says is wrong, when it answered and is not well.
- `waiting_for_files` (boolean): True when only the client data is missing: a server being set up.
- `health` ([Health](#health), or null): Its own answer, as /opendmtq/health.php gives it.

#### Health

The game server's health check (/opendmtq/health.php). Other fields may come with it.

- `ok` (boolean): True when the server can serve the game.
- `host` (string): The address phones use.
- `songs` (integer): Songs on offer (hidden ones not counted).
- `game_data` (boolean): True when the client data is there.
- `patch` (string): The client data's version the game is told of.
- `database` (boolean): True when the database can be read.
- `players` (integer, or null): Players.
- `apk` (object, or null): The app on offer: file, host, built_at.
- `apk_matches_host` (boolean, or null): True when that app is for this address.
- `https` (boolean): True when browsers are sent to HTTPS.
- `role` (string): api, or assets for a replica that serves files only.
- `writable` (boolean, or null): True when the database can be written.

#### Counts

The status page's numbers.

- `players` (integer): Players.
- `records` (integer): Best records: one per player and chart.
- `plays_today` (integer): Plays in the last 24 hours.
- `plays_week` (integer): Plays in the last 7 days.
- `active_week` (integer): Players who played in the last 7 days.
- `live` (integer): Players on air now (none while broadcasts are off).
- `broadcasts` (boolean): True while broadcasts are on for the server (GET /broadcasts).

#### DashPlay

A play on the status page.

- `player` (integer): The player's number.
- `name` (string): The player's name.
- `song` (string): The song's title (empty for a chart the server does not list).
- `chart` (string): The chart, as the game names it (2LINE Hard 5).
- `score` (integer): The score.
- `grade` (string): The grade.
- `new_record` (boolean): True when it beat the player's best.
- `at` (integer): When (Unix time).

#### BackupFacts

The backups, as the status page counts them.

- `newest` (string, or null): The newest backup made here (uploaded ones do not count).
- `newest_at` (integer, or null): When it was made (Unix time).
- `daily` (boolean): True while the daily backup is on.
- `daily_failure` (string, or null): Why the last look could not make the daily backup.

#### AppFacts

The app on offer, as the status page has it.

- `on_offer` ([Build](#build), or null): The build the site offers.
- `build_error` (string, or null): Why the last build for this address failed.
- `other_address` (boolean): True when the app on offer is for another address.

#### Disk

The data disk.

- `total` (integer): Its size (bytes).
- `used` (integer): In use (bytes).
- `free` (integer): Free (bytes).
- `parts` ([DiskParts](#diskparts)): What takes it.

#### DiskParts

What takes the data disk (bytes), counted at most every minute: OpenDMTQ's parts, each folder as it is on this disk, a file linked twice once; then what is not OpenDMTQ's, and what is free.

- `recordings` (integer): Recordings.
- `backups` (integer): Backups.
- `builds` (integer): The apps for players and what the builder keeps to make them: the installer for Windows, the runtime for newer phones, the signing key (data/apk, but the game's client).
- `songs` (integer): Added songs.
- `database` (integer): The database.
- `game` (integer): The game's files brought in: the client data, the song data and the client (data/content, data/apk/base).
- `rest` (integer): The rest of what OpenDMTQ keeps: logs, settings, the site's copies of the jackets, broadcasts on their way.
- `other` (integer): Everything else on the disk.
- `free` (integer): Free.

#### Attention

A thing to look at.

- `level` (string): How much it matters. One of `warn`, `bad`.
- `text` (string): What it is, in words.
- `link` (string): The admin page that deals with it, or backup-now: POST /backups makes one.

#### Activity

What the status page's charts draw.

- `days` (list of [DayCount](#daycount)): Plays on each of the last 30 days, oldest first, on this server's clock.
- `hours` (list of list of integer): Plays by weekday (Monday first) and hour (0 to 23), over the last 4 weeks.
- `players` (list of [PlayerCount](#playercount)): Who played most over the last 30 days.
- `songs` (list of [SongCount](#songcount)): The most played songs over the last 30 days.
- `grades` (list of [GradeCount](#gradecount)): Best records by grade, S first.

#### DayCount

A day's plays.

- `day` (string): The day (YYYY-MM-DD).
- `plays` (integer): Plays.

#### PlayerCount

A player's plays.

- `player` (integer): The player's number.
- `name` (string): The player's name.
- `plays` (integer): Plays.

#### SongCount

A song's plays.

- `title` (string): The song's title.
- `plays` (integer): Plays, every chart of it together.

#### GradeCount

Records at a grade.

- `grade` (string): The grade.
- `records` (integer): Best records at it.

#### GradePlays

Plays at a grade.

- `grade` (string): The grade.
- `plays` (integer): Plays at it.

#### Machine

The machine the server runs on.

- `cores` (integer): Processors.
- `uptime` (integer, or null): Seconds since it started.
- `cpu` (number, or null): Processor use now (percent), null while measuring.
- `cpu_wait` (number, or null): The part of it waiting for the disk (percent).
- `memory` ([Amount](#amount), or null): Memory (bytes).
- `swap` ([Amount](#amount), or null): Swap (bytes).
- `disk` ([DiskSize](#disksize)): The data disk (bytes).
- `load` (list of number, or null): The load over 1, 5 and 15 minutes.
- `since` (integer): Since when the points are kept (Unix time).
- `points` (list of [MachinePoint](#machinepoint)): The last day, a point every five minutes.

#### Amount

An amount and how much of it is in use.

- `total` (integer): All of it.
- `used` (integer): In use.

#### DiskSize

A disk's size.

- `total` (integer): Its size.
- `used` (integer): In use.
- `free` (integer): Free.

#### MachinePoint

Five minutes of the machine.

- `at` (integer): When (Unix time).
- `cpu` (number): Average processor use (percent).
- `peak` (number): Highest processor use (percent).
- `wait` (number): Waiting for the disk (percent).
- `mem` (number, or null): Memory in use (percent).
- `game` (string): How the game server answered. One of `ok`, `warn`, `bad`.

#### AppOnOffer

The app players get.

- `name` (string): The app's name on phones: TECHNIKA Q (&lt;server name&gt;).
- `address` (string): The address it should be built for: this server's.
- `on_offer` ([Build](#build), or null): The build the site offers.
- `state` (string, or null): What can be said of it: right for this server, a rebuild that failed, or for another address. One of `fits`, `rebuild_failed`, `other_address`.
- `says` (string, or null): The same in words.
- `build_error` (string, or null): Why the last build for this address failed.
- `icon` (boolean): True when its icon is kept (GET /app/icon).
- `windows` ([WindowsInstaller](#windowsinstaller), or null): The installer for Windows (the PC client) that the site offers computers (GET /app/windows); null on a server without it.
- `building` ([Job](#job), or null): A build running now.

#### WindowsInstaller

The installer for Windows (the PC client) as the builder keeps it, before the server's address goes on its end as it is handed out.

- `file` (string): Its file name as kept: OpenDMTQ-Setup.exe.
- `size` (integer): Its size as kept (bytes); handed out, it is longer by the server's address.
- `sha256` (string): Its SHA-256 as kept.
- `version` (string, or null): The OpenDMTQ version it is from; null for a copy put on the server by hand.
- `copied_at` (string): When the builder put it beside the app (YYYY-MM-DDTHH:MM:SS).

#### Build

A build of the app.

- `file` (string): Its file name.
- `address` (string): The address it is built for.
- `built_at` (string): When it was built, as its manifest says (YYYY-MM-DDTHH:MM:SS).
- `size` (integer): Its size (bytes).
- `sha256` (string): Its SHA-256, as its manifest says (empty for an older build).
- `runtime` (string, or null): The version of the arm32 runtime inside, for phones without 32-bit support.
- `label` (string, or null): The app's name on phones.
- `on_offer` (boolean): True for the one the site offers.
- `made_at` (integer): When the file was written (Unix time).

#### BuildList

The builds.

- `items` (list of [Build](#build)): Every build, newest first.

#### BuildAnswer

A build.

- `build` ([Build](#build)): The build.

#### Pruned

What a prune removed.

- `deleted` (integer): Builds deleted.
- `freed` (integer): Bytes freed.

#### Deleted

What was deleted.

- `deleted` (string): Its name or id.

#### Invite

Where players get the app.

- `url` (string): The download page by the address all phones use.
- `qr` (boolean): True when its QR code is there (GET /invite/qr).

#### Song

A song on the Songs page.

- `id` (integer): Its id.
- `name` (string): Its key in the song data.
- `title` (string): Its title.
- `artist` (string): Its artist.
- `charts` (integer): Its charts.
- `hidden` (boolean): True when it is hidden from the game's song list and the site.
- `source` (string): Where it came from: imported with the song data, or added as a song package. One of `imported`, `added`.
- `plays` (integer): Plays over the last 30 days, every chart together.
- `last_played` (integer, or null): When it was last played (Unix time).

#### SongList

The Songs page's list.

- `items` (list of [Song](#song)): Every song, imported ones first.
- `client_data` (boolean): True when the client data is there: without it the game cannot start.
- `tile_failures` (list of string): Why songs have no picture on their tile in the game's song list.

#### SongAnswer

A song.

- `song` ([Song](#song)): The song.

#### SongHidden

A song hidden or shown.

- `id` (integer): Its id.
- `title` (string): Its title (its id when it is not listed).
- `hidden` (boolean): True when it is hidden now.

#### Notice

The in-game maintenance notice.

- `on` (boolean): True while it is on: players see it and cannot start the game.
- `message` (string): What it says (empty: the usual words).

#### Stopping

A stop asked for.

- `stopping` (boolean): True: the server stops within a few seconds, these pages and the API with it.

#### Player

A player on the Players page.

- `id` (integer): Their number.
- `name` (string): Their name as the pages show it (Player &lt;n&gt; until one is set).
- `nickname` (string): Their name as they set it (empty until then).
- `charts` (integer): Charts they hold a record on.
- `total` (integer): Their best scores summed.
- `last_played` (integer, or null): When they last played (Unix time).
- `plays_30_days` (integer): Plays over the last 30 days.
- `days` (list of integer): Plays on each of the last 14 days, oldest first.
- `phones` (integer): Phones they have played on.
- `broadcast` (string): Their broadcast: off, switched on and waiting for video, on air, or switched on and held while broadcasts are off for the server. One of `off`, `waiting`, `on_air`, `held`.
- `seen` (string): Who the number belongs to now: send it as ?seen= with a change.

#### PlayerList

The players.

- `items` (list of [Player](#player)): Every player, by number.

#### PlayerAnswer

A player.

- `player` ([Player](#player)): The player.

#### PlayerReset

A player's records reset.

- `player` ([Player](#player)): The player now.
- `backup` (string): The backup made first.

#### PlayerDeleted

A player deleted.

- `deleted` (integer): Their number.
- `backup` (string): The backup made first.

#### Account

An account of the site.

- `name` (string): Its ID.
- `note` (string): Whom it is for (admins only see this).
- `admin` (boolean): True when it also opens the admin pages.
- `enabled` (boolean): True when it can sign in.
- `created_at` (integer): When it was made (Unix time).
- `signed_in_at` (integer, or null): When it last signed in (Unix time).
- `player` (integer, or null): The game player it is linked to.
- `player_name` (string, or null): That player's name.

#### AccountList

The accounts.

- `items` (list of [Account](#account)): Every account, by ID.
- `owner` (string): The owner's ID (ADMIN_USER in .env), which is no account of the list.
- `players` (list of [PlayerChoice](#playerchoice)): The game's players an account can be linked to.

#### PlayerChoice

A game player to link to.

- `id` (integer): Their number.
- `name` (string): Their name, with the number when two share it.

#### AccountAnswer

An account.

- `account` ([Account](#account)): The account.

#### AccountPassword

An account with its password, shown this once.

- `account` ([Account](#account)): The account.
- `password` (string): Its password: made by the server, or the one sent.
- `message` (string): The message to send its player: where to sign in and get the app, the ID and the password.

#### Token

An API token. Never the token itself.

- `id` (string): Its id (the 12 hex digits after odq_ in the token).
- `name` (string): What it is for.
- `scope` (string): What it may do. One of `read`, `write`.
- `admin` (string): The admin it belongs to.
- `owner` (boolean): True for a token of the owner's account (.env).
- `created_at` (integer): When it was made (Unix time).
- `used_at` (integer, or null): When it was last used (Unix time, to the minute).
- `works` (boolean): True while its admin can use the admin pages.

#### TokenList

The tokens.

- `items` (list of [Token](#token)): Every token, newest first.

#### TokenMade

A new token.

- `token` ([Token](#token)): The token.
- `secret` (string): The token to send (odq_...): shown this once, never kept.

#### Recording

A recording of a broadcast.

- `key` (string): &lt;player&gt;/&lt;id&gt;, as POST /recordings/delete takes it.
- `player` (integer): The player's number.
- `id` (integer): Its id: the moment it began (Unix time).
- `name` (string): The player's name.
- `started` (integer): When it began (Unix time).
- `ended` (integer, or null): When its last segment came (Unix time); null while it is being made.
- `duration_ms` (integer): How long it is (milliseconds).
- `size` (integer): Its size (bytes).
- `songs` (list of [RecordedSong](#recordedsong)): The songs played in it, in order.
- `open` (boolean): True while it is being made: it cannot be watched, downloaded or deleted yet.
- `hidden` (boolean): True when players do not see it.

#### RecordedSong

A song in a recording.

- `title` (string): The song's title.
- `chart` (string): The chart, as the game names it.
- `at` (integer, or null): When it began (Unix time).

#### RecordingList

The recordings.

- `items` (list of [Recording](#recording)): Every recording, newest first.

#### RecordingFiles

A recording and its files.

- `recording` ([Recording](#recording)): The recording.
- `files` (list of [RecordingFile](#recordingfile)): Its playlist and segments, in the playlist's order (none while it is being made).

#### RecordingFile

A file of a recording.

- `name` (string): Its name (GET .../files/{part}).
- `size` (integer): Its size (bytes).

#### RecordingsDone

What an action on recordings did.

- `done` (integer): Recordings it was done to.
- `kept` (integer): Recordings still being made, which a delete keeps.

#### RecordingAnswer

A recording.

- `recording` ([Recording](#recording)): The recording.

#### Limits

The limits the recordings are kept to, and the disk.

- `cap_gb` (number): Their total size at most (GB).
- `days` (integer): Their age at most (days).
- `used` (integer): What they take now (bytes).
- `cap` (integer): The total size at most (bytes).
- `free` (integer): Free on the disk (bytes).
- `hours_left` (integer): About how many hours of broadcast still fit (an hour takes about 1 GB).
- `deleted` (integer, optional): Recordings the new limits deleted.

#### Backup

A backup archive.

- `name` (string): Its file name.
- `size` (integer): Its size (bytes).
- `made` (integer): When it was made (Unix time).
- `kind` (string): How it came to be: the daily backup, uploaded, before a change that cannot be undone, by ./opendmtq deploy, or by hand. One of `daily`, `uploaded`, `before`, `deploy`, `hand`.

#### BackupList

The backups.

- `items` (list of [Backup](#backup)): Every backup, newest first.

#### BackupAnswer

A backup.

- `backup` ([Backup](#backup)): The backup.

#### DailyBackup

The daily backup.

- `on` (boolean): True while it is on.
- `kept` (list of string): The daily backups kept, newest first (the latest seven).
- `next` (integer, or null): When the next one comes, at the first look after it if the game's data changed (Unix time); null when it is due.
- `failure` (string, or null): Why the last look could not make one.

#### RequestLog

The Requests tab.

- `items` (list of [Request](#request)): The newest requests the filters leave, newest first.
- `matched` (integer): Requests the filters leave.
- `kept` (integer): Requests read from the log.
- `covered_from` (integer, or null): Since when the log counts, when only its newest part could be read (Unix time).
- `hours` (list of [HourCount](#hourcount)): The last 24 hours of what the filters leave, an hour each, oldest first.
- `top_paths` (list of [NameCount](#namecount)): What was asked for most in those hours.
- `top_devices` (list of [NameCount](#namecount)): By which devices.
- `top_addresses` (list of [NameCount](#namecount)): From which addresses.

#### Request

A request in the log.

- `at` (integer): When (Unix time).
- `address` (string): The visitor's address.
- `method` (string): Its method.
- `path` (string): What was asked for.
- `status` (integer): The answer's status.
- `size` (integer): The answer's size (bytes).
- `referrer` (string): The page it came from.
- `agent` (string): The visitor's user agent.
- `kind` (string): What it was for. One of `game`, `files`, `app`, `site`, `live`, `admin`, `other`.
- `device` (string): The device, in a word or two.
- `line` (string): The log's own line.

#### HourCount

An hour of requests.

- `at` (integer): Its start (Unix time).
- `fine` (integer): Requests that went well.
- `failed` (integer): Requests the server or the game failed (scripts asking for files that are not there do not count).

#### NameCount

Something and how often.

- `name` (string): What.
- `requests` (integer): How often.

#### PlayLog

The Plays tab.

- `items` (list of [LoggedPlay](#loggedplay)): This page of the plays the filter leaves, newest first.
- `total` (integer): Plays the filter leaves.
- `page` (integer): This page.
- `pages` (integer): Pages of 50.
- `players` (list of [PlayerChoice](#playerchoice)): Those with plays, for the player filter.
- `summary` ([PlaysSummary](#playssummary), or null): What all the plays the filter leaves add up to; null when there are none.

#### LoggedPlay

A play in the log.

- `player` (integer): The player's number.
- `name` (string): The player's name.
- `song` (string): The song's title (empty for a chart the server does not list).
- `chart` (string): The chart, as the game names it.
- `score` (integer): The score.
- `grade` (string): The grade.
- `accuracy` (number): The accuracy (percent).
- `new_record` (boolean): True when it beat the player's best.
- `at` (integer): When (Unix time).

#### PlaysSummary

What a list of plays adds up to.

- `plays` (integer): Plays.
- `records` (integer): New records among them.
- `accuracy` (number): Their average accuracy (percent).
- `players` (integer): Players.
- `grades` (list of [GradePlays](#gradeplays)): Plays by grade, S first.
- `days` (list of [DayCount](#daycount)): Plays on each day that has any, oldest first.

#### ChangeList

The log of changes.

- `items` (list of [Change](#change)): The latest changes, newest first.

#### Change

A change made on the admin pages or through the API.

- `at` (integer): When (Unix time).
- `what` (string): The page and its action, as the log keeps it (accounts_page:create).
- `words` (string): The same in words.
- `target` (string): On whom or what.
- `who` (string): Who: an admin's ID, with the token's name in brackets for the API.

#### SetupState

The setup's four steps.

- `steps` ([SetupSteps](#setupsteps)): Each step, true when done.
- `next` (string, or null): The first step left. One of `files`, `address`, `players`, `app`.
- `host_install` (boolean): True on the server PC's own install: the setup imports from its folders and changes the address.
- `kubernetes` (boolean): True in Kubernetes.
- `files` ([SetupFiles](#setupfiles)): The game's files.
- `address` ([SetupAddress](#setupaddress)): The address.
- `accounts` (integer): Accounts made.
- `app` ([SetupApp](#setupapp)): The app.

#### SetupSteps

Each step of the setup.

- `files` (boolean): The client and all the client data are in.
- `address` (boolean): The address is set.
- `players` (boolean): There is an account.
- `app` (boolean): The app on offer is for this address and its last build did not fail.

#### SetupFiles

The setup's files step.

- `client` (string, or null): The client the app is built from (its file name).
- `client_says` (string, or null): What that client is, in words.
- `unusable` (list of string): APKs in data/apk/base that are no client to build from.
- `client_data` (boolean): True when the client data is in.
- `missing` (list of string): The client data's files the import did not bring.
- `songs` (integer): Songs on the server.
- `places` (list of string): Where the setup's folder picker goes in one step: the home folder, Downloads, the Desktop, Documents and OneDrive's folders, then the drives (a host install only; empty otherwise).

#### SetupAddress

The setup's address step.

- `address` (string): The address phones use.
- `port` (integer): Its port.
- `choices` (list of string): This PC's private addresses, the one towards the internet first (a host install only).

#### SetupApp

The setup's app step.

- `on_offer` ([Build](#build), or null): The build the site offers.
- `build_error` (string, or null): Why the last build for this address failed.
- `building` (boolean): True while a build runs (one of these pages', or the server's own at its start).
- `client` (boolean): True when there is a client to build from.
- `runtime` (boolean): True when the arm32 runtime is there, for phones without 32-bit support.
- `runtime_error` (string, or null): Why the last try to bring the runtime did not work.
- `qr` (boolean): True when the download page's QR code is there.

#### FoundList

The game's files found on the server PC.

- `items` (list of [Found](#found)): The folders, the most complete first.

#### Found

A folder with some of the game's files.

- `path` (string): The folder.
- `apps` (list of string): Clients in it (an APK, or a bundle with one).
- `archives` (list of string): Archives in it named like the game's, or beside an APK (one in parts by its first part).
- `iphone` (list of string): The iPhone app, which is of no use here.
- `folder` (string, or null): A folder of the client data, with the song data or alone, in it or under it.
- `folder_kind` (string, or null): What that folder holds. One of `whole`, `game`, `songs`.
- `songs_folder` (string, or null): A folder of the song data alone.
- `parts` (object of integer): Each archive in parts, with how many parts there are.

#### Folder

A folder of the server PC, as the setup's folder picker shows it.

- `path` (string): The folder.
- `parent` (string, or null): The folder above it (null at the top of a drive).
- `folders` (list of [FolderEntry](#folderentry)): The folders in it (400 at most).
- `files` (list of [FileEntry](#fileentry)): The game's kinds of file in it (400 at most).
- `more` (boolean): True when there were more than 400.
- `folder` (string, or null): The game's files in it or under it.
- `folder_kind` (string, or null): What they are. One of `whole`, `game`, `songs`.
- `songs_folder` (string, or null): The song data alone in it or under it.
- `picked` (string, or null): The file the path named, when it named a file.
- `places` (list of string): Where the picker goes in one step, as the setup page shows them: the home folder, Downloads, the Desktop, Documents and OneDrive's folders, then the drives.

#### FolderEntry

A folder in a folder.

- `name` (string): Its name.
- `path` (string): Its path.

#### FileEntry

A file in a folder.

- `name` (string): Its name.
- `size` (integer): Its size (bytes).
- `path` (string): Its path.
- `parts` (integer): For an archive in parts: how many parts there are (0 otherwise).

#### What

What a file or folder is to the import.

- `path` (string): The path.
- `ok` (boolean): True when the import can take it.
- `text` (string): What it is, in words.

#### Restarting

A new address, the server starting again for it.

- `address` (string): The new address.
- `restarting` (boolean): True: every program starts again within seconds, and the app is built for the address.
- `instance` (string): This run of the admin service: GET /status gives another once the new one answers.

#### SiteSong

A song of the players' site.

- `id` (integer): Its id (song.php?id=).
- `name` (string): Its key in the song data.
- `title` (string): Its title.
- `artist` (string): Its artist.
- `genre` (string): Its genre.
- `jacket` (string): Its picture's path on the server's address.
- `hidden` (boolean): True when it is hidden (the site lists only those that are not).
- `records` (integer, optional): Records on its charts (players with a record on each).

#### SiteSongList

The site's song list.

- `items` (list of [SiteSong](#sitesong)): Every song players can see, by title.

#### SiteSongPage

A song's page on the site.

- `song` ([SiteSong](#sitesong)): The song.
- `credits` ([Credits](#credits)): Who made it.
- `charts` (list of [SiteChart](#sitechart)): Its charts, in the game's order.

#### Credits

Who made a song.

- `composed_by` (string): Composer.
- `singer` (string): Singer.
- `feat_by` (string): Featuring.
- `arranged_by` (string): Arranger.
- `visualized_by` (string): Its video (BGA).

#### SiteChart

A chart of a song.

- `chart` (integer): Its id (GET /site/charts/{chart}/ranking).
- `line` (integer): Its mode: 2, 3 or 4 LINE.
- `difficulty` (string): Its difficulty. One of `Easy`, `Normal`, `Hard`, `Expert`.
- `level` (integer): Its level.
- `chart_name` (string): Its name, as the game writes it (2LINE Hard 5).
- `records` (integer): Records on it.

#### Board

A chart's leaderboard.

- `chart` (integer): The chart.
- `song` (integer): Its song.
- `title` (string): Its song's title.
- `chart_name` (string): Its name.
- `items` (list of [BoardPlace](#boardplace)): The best 100, best first.

#### BoardPlace

A place on a leaderboard.

- `place` (integer): The place.
- `player` (integer): The player's number.
- `name` (string): The player's name.
- `score` (integer): The score.
- `grade` (string): The grade.
- `all_combo` (boolean): An all combo (AC).
- `perfect_play` (boolean): A perfect play (PP).
- `accuracy` (number): The accuracy (percent).

#### Rankings

The site's rankings, by a tab.

- `sort` (string): The tab. One of `total`, `s_count`, `perfect`, `charts`.
- `items` (list of [Ranked](#ranked)): The players with some of what is ranked, in its order.

#### Ranked

A player of the rankings.

- `place` (integer): Their place in this order.
- `rank` (integer, or null): Their rank by total, among those who played.
- `id` (integer): Their number.
- `name` (string): Their name.
- `charts` (integer): Charts played (with a record).
- `total` (integer): Best scores summed.
- `s_count` (integer): S grades.
- `all_combos` (integer): All combos.
- `perfect_plays` (integer): Perfect plays.
- `accuracy` (number): Their average accuracy (percent, to the tenth, the half rounded up as the site does).

#### MonthRankings

This month's rankings, as the game ranks them.

- `items` (list of [MonthPlayer](#monthplayer)): This month's players, best first: the sum of each one's best score per chart this month.
- `starts_anew` (integer): When the next month begins: the first of the month at midnight UTC (Unix time).
- `past_months` (list of [PastMonth](#pastmonth)): The months before, newest first, with their first three (six months back at most).

#### MonthPlayer

A player of a month.

- `place` (integer, optional): Their place.
- `id` (integer): Their number.
- `name` (string): Their name.
- `score` (integer): Their month's score.
- `charts` (integer): Charts they played that month.

#### PastMonth

A month before.

- `month` (string): The month (YYYY-MM, UTC).
- `start` (integer): Its start (Unix time).
- `end` (integer): Its end (Unix time).
- `top` (list of [MonthPlayer](#monthplayer)): Its first three.

#### SitePlayer

A player's page on the site.

- `id` (integer): Their number.
- `name` (string): Their name.
- `rank` (integer, or null): Their rank by total, among those who played.
- `charts` (integer): Charts with a record.
- `total` (integer): Best scores summed.
- `s_count` (integer): S grades.
- `all_combos` (integer): All combos.
- `perfect_plays` (integer): Perfect plays.
- `accuracy` (number, or null): Their average accuracy (percent, to the tenth, the half rounded up as the site does); null with no plays.
- `grades` (object of integer): Their best records by grade, only the grades they have.
- `records` (integer): Their best records (GET /site/players/{player}/records lists them).
- `recent` (list of [SitePlay](#siteplay)): Their last 15 plays.
- `activity` ([Activity12](#activity12)): The last 12 weeks, day by day.
- `levels` (list of [Level](#level)): Their records by the chart's level.
- `broadcasts` (list of [PastBroadcast](#pastbroadcast)): Their newest 4 recordings.

#### Activity12

The last weeks, as a player's page draws them.

- `since` (string): The first day, a Monday (YYYY-MM-DD).
- `days` (object of integer): Plays on each day that has any (YYYY-MM-DD).

#### Level

A player's records at a level.

- `level` (integer): The level.
- `charts` (integer): The server's charts of that level, of the songs players see (none hidden).
- `records` (integer): Their records on them.
- `grades` (object of integer): Those records by grade.

#### SitePlay

A play on the site.

- `chart` (integer): The chart.
- `song` (integer, or null): Its song.
- `title` (string, or null): Its song's title.
- `chart_name` (string, or null): Its name.
- `score` (integer): The score.
- `grade` (string): The grade.
- `accuracy` (number): The accuracy (percent).
- `new_record` (boolean): True when it beat the player's best.
- `at` (integer): When (Unix time).
- `player` (integer, optional): The player's number.
- `name` (string, optional): The player's name.
- `best_before` (integer, or null, optional): The player's best on that chart before it.

#### SitePlays

Plays.

- `items` (list of [SitePlay](#siteplay)): Newest first.

#### SiteRecords

A player's best records.

- `items` (list of [SiteRecord](#siterecord)): Best score first.

#### SiteRecord

A best record.

- `chart` (integer): The chart.
- `song` (integer, or null): Its song.
- `title` (string, or null): Its song's title.
- `chart_name` (string, or null): Its name.
- `score` (integer): The score.
- `grade` (string): The grade.
- `all_combo` (boolean): An all combo (AC).
- `perfect_play` (boolean): A perfect play (PP).
- `accuracy` (number): The accuracy (percent).
- `set_at` (integer, or null): When it was set (null for a record older than the play log).

#### BroadcastSettings

The server's broadcasts as a whole (the Broadcasts page).

- `on` (boolean): True while broadcasts are on: only then do phones and PCs send video and does the site show broadcasts.
- `new_players` (boolean): True when a new player's switch starts on, from their first play.
- `quality` (string): The stream's quality the phones and the PC player are asked for. One of `light`, `standard`, `smooth`, `sharp`.
- `qualities` (list of [BroadcastQuality](#broadcastquality)): Every quality, with what it costs.
- `switched_on` (integer): Players whose own switch is on.
- `on_air` (integer): Players on air now (none while broadcasts are off).

#### BroadcastQuality

A quality of the stream.

- `key` (string): Its name: light, standard, smooth or sharp.
- `height` (integer): The picture's height in pixels.
- `fps` (integer): Frames a second.
- `bitrate` (integer): The picture's bitrate (bit/s).
- `segment` (integer): A segment's length (seconds).
- `hour_bytes` (integer): What an hour of broadcast takes on the disk, about (bytes).
- `viewer_bits` (integer): Each viewer's connection, about (bit/s), picture and sound.

#### SiteLive

The site's broadcasts.

- `on` (boolean): True while broadcasts are on for the server; while off, the site shows none of them.
- `live` (list of [LiveNow](#livenow)): Who is on air now.
- `past` (list of [PastBroadcast](#pastbroadcast)): The recordings players may watch, newest first (300 at most).
- `past_rev` (string): The sign of `past`, as the site's live page has it (`live.php?list=1`): the first 16 hex digits of the SHA-256 of its keys in order, joined by commas. It changes when a recording ends, is hidden, shown again or deleted: a client that keeps the list asks for it again only then.

#### LiveNow

A player on air.

- `player` (integer): Their number (live.php?p=).
- `name` (string): Their name.
- `song` (string, or null): The song they play, while in one.
- `chart` (string, or null): Its chart.
- `seconds` (integer): How long the broadcast has run.

#### PastBroadcast

A recording players may watch.

- `key` (string): &lt;player&gt;-&lt;id&gt;, as live.php?r= takes it.
- `player` (integer): The player's number.
- `name` (string): The player's name.
- `started` (integer): When it began (Unix time).
- `seconds` (integer): How long it is.
- `songs` (list of [PastSong](#pastsong)): Its songs, in order.

#### PastSong

A song in a recording, as the site lists it.

- `title` (string): The song's title.
- `chart` (string): Its chart.
- `at` (integer): Seconds into the recording where it begins (-1 when an older recording did not note it).
- `jacket` (string, or null): Its picture's path on the server's address.

#### SiteHome

The site's home page.

- `app` ([HomeApp](#homeapp), or null): The app on offer.
- `top` (list of [TopPlayer](#topplayer)): The best players, eight at most.
- `records` (list of [SitePlay](#siteplay)): The newest records.
- `live` (list of [LiveNow](#livenow)): Who is on air now.
- `past` (list of [PastBroadcast](#pastbroadcast)): The newest 4 recordings.

#### HomeApp

The app the site offers.

- `file` (string): Its file name.
- `host` (string): The address it is built for.
- `built_at` (string): When it was built.
- `size` (integer, or null): Its size (bytes).
- `for_this_address` (boolean): True when it is for this server's address: only then can players use it.

#### TopPlayer

A best player.

- `id` (integer): Their number.
- `name` (string): Their name.
- `total` (integer): Best scores summed.

<!-- reference: end -->
