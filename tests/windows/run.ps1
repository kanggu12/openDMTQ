# The Windows bundle on Windows (CI's windows job): the zip unpacked into a folder whose name has a space, the pages'
# stand-in game files imported with OpenDMTQ.exe, the server run, the game server's contract (tests/game/protocol.py)
# and the admin pages checked, and the server stopped with its window's process tree. Needs Python 3 for the checks.
#
# Usage (PowerShell 7, from the repository): tests/windows/run.ps1 -Zip <OpenDMTQ-windows.zip> [-Port 18731]
param(
    [Parameter(Mandatory = $true)][string]$Zip,
    [int]$Port = 18731
)
$ErrorActionPreference = "Stop"
$failures = 0
function Pass([string]$name) { Write-Output "PASS $name" }
function Fail([string]$name) { Write-Output "FAIL $name"; $script:failures++ }
# The HTTP status of an address (0 when nothing answers), without following redirects. Windows' own curl.exe, as the Wine test
# asks curl: PowerShell's Invoke-WebRequest throws at a redirect it is told not to follow, and a 302 read as 0.
function Status([string]$url) {
    $code = & curl.exe -s -o NUL -w "%{http_code}" -m 10 $url
    if (-not $code) { return 0 }
    return [int]$code
}

$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
# A folder with a space in its name, as under a user's own name: every path the bundle writes must survive it.
$root = Join-Path $env:RUNNER_TEMP "Open DMTQ test"
if (Test-Path $root) { Remove-Item -Recurse -Force $root }
Expand-Archive -Path $Zip -DestinationPath $root
$bundle = Join-Path $root "OpenDMTQ"
$exe = Join-Path $bundle "OpenDMTQ.exe"

# 1. The launcher starts the bundle's Python and the host program.
$help = & $exe --help 2>&1 | Out-String
if ($help -match "Run an OpenDMTQ server without containers") { Pass "OpenDMTQ.exe starts the bundle's Python and the host program" }
else { Write-Output $help; Fail "OpenDMTQ.exe starts the bundle's Python and the host program" }

# 2. The pages' stand-in game files, made by the bundle's own PHP and laid out as the game's server files.
$content = Join-Path $env:RUNNER_TEMP "odq-content"
$game = Join-Path $env:RUNNER_TEMP "odq-game"
foreach ($d in @($content, $game)) { if (Test-Path $d) { Remove-Item -Recurse -Force $d } }
New-Item -ItemType Directory -Force -Path $content, "$game\dmqglb.mb.pmang.com", "$game\_info" | Out-Null
& (Join-Path $bundle "runtime\php\php.exe") -n (Join-Path $repo "tests\ui\make_content.php") $content | Out-Null
Copy-Item -Recurse -Path "$content\web\*" -Destination "$game\dmqglb.mb.pmang.com\"
Copy-Item -Path "$content\songs.json" -Destination "$game\_info\songList.json"
# A first start as a person makes it: no .env yet. OpenDMTQ.exe writes one (this PC's address, a free port, a password)
# and runs the server. Windows' Python lacks some of Linux's calls for that file (no fchmod, no user ids).
$envFile = Join-Path $bundle ".env"
$firstLog = Join-Path $env:RUNNER_TEMP "odq-first.log"
$firstErr = Join-Path $env:RUNNER_TEMP "odq-first.err"
$first = Start-Process -FilePath $exe -WorkingDirectory $bundle -PassThru -NoNewWindow `
    -RedirectStandardOutput $firstLog -RedirectStandardError $firstErr
$written = $false
for ($i = 0; $i -lt 90; $i++) {
    if ((Test-Path $envFile) -and (Select-String -Path $envFile -Pattern "^ADMIN_PASSWORD=" -Quiet)) { $written = $true; break }
    if ($first.HasExited) { break }
    Start-Sleep -Seconds 2
}
if ($written -and (Select-String -Path $envFile -Pattern "^PUBLIC_HOST=" -Quiet) -and
    (Select-String -Path $envFile -Pattern "^LISTEN_PORT=" -Quiet)) {
    Pass "a first start with no .env writes one: the address, the port, a password"
} else {
    Get-Content $firstLog, $firstErr -ErrorAction SilentlyContinue | Select-Object -Last 40
    Fail "a first start with no .env writes one: the address, the port, a password"
}
# Its window closed: everything it started stops with it. The rest runs with this test's own ports and settings.
taskkill /T /F /PID $first.Id 2>$null | Out-Null
Start-Sleep -Seconds 5
Remove-Item -Force -ErrorAction SilentlyContinue $envFile
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $bundle ".host\run")

# The settings setup would write, with this test's ports.
Set-Content -Path (Join-Path $bundle ".env") -Encoding utf8 -Value @(
    "PUBLIC_HOST=127.0.0.1:$Port", "LISTEN_PORT=$Port", "ADMIN_PORT=$($Port + 1)", "ADMIN_PASSWORD=ci")
$import = & $exe import $game --songs 2>&1 | Out-String
if ($LASTEXITCODE -eq 0 -and $import -match "game data and") { Pass "OpenDMTQ.exe imports the game data and the songs from a folder" }
else { Write-Output $import; Fail "OpenDMTQ.exe imports the game data and the songs from a folder" }

# 3. The server, until it answers.
$log = Join-Path $env:RUNNER_TEMP "odq-run.log"
$err = Join-Path $env:RUNNER_TEMP "odq-run.err"
$server = Start-Process -FilePath $exe -ArgumentList "run" -WorkingDirectory $bundle -PassThru -NoNewWindow `
    -RedirectStandardOutput $log -RedirectStandardError $err
$up = $false
for ($i = 0; $i -lt 90; $i++) {
    if ((Status "http://127.0.0.1:$Port/opendmtq/health.php") -eq 200) { $up = $true; break }
    Start-Sleep -Seconds 2
}
if ($up) { Pass "the server answers on the bundle's Apache and PHP" }
else {
    Get-Content $log, $err -ErrorAction SilentlyContinue | Select-Object -Last 40
    Get-Content (Join-Path $bundle "data\state\logs\server.log") -ErrorAction SilentlyContinue | Select-Object -Last 40
    Fail "the server answers on the bundle's Apache and PHP"
}

# 4. The game server's contract, the admin pages, the site signed out, a file of the imported content.
if ($up) {
    python (Join-Path $repo "tests\game\protocol.py") "http://127.0.0.1:$Port"
    if ($LASTEXITCODE -eq 0) { Pass "the game server's contract on Windows" } else { Fail "the game server's contract on Windows" }
    $checks = @(
        @("the admin pages answer on this machine", "http://127.0.0.1:$($Port + 1)/opendmtq/admin/login", 200),
        @("the admin pages answer on the public port", "http://127.0.0.1:$Port/opendmtq/admin/login", 200),
        @("signed out, the site asks to sign in", "http://127.0.0.1:$Port/opendmtq/index.php", 302),
        @("a song's jacket is served from the imported content", "http://127.0.0.1:$Port/viewImg/eye/fixture1.png", 200))
    foreach ($c in $checks) {
        $got = Status $c[1]
        if ($got -eq $c[2]) { Pass $c[0] } else { Fail "$($c[0]) ($got)" }
    }
    $phpLog = Get-Content (Join-Path $bundle "data\state\logs\server.log") -ErrorAction SilentlyContinue |
        Select-String -Pattern "PHP (Warning|Notice|Deprecated|Fatal error|Parse error)"
    if ($phpLog) { $phpLog; Fail "PHP said nothing in the server's log" } else { Pass "PHP said nothing in the server's log" }
}

# 5. Stopped as closing the window stops it: the whole process tree, and nothing keeps the port.
taskkill /T /F /PID $server.Id | Out-Null
Start-Sleep -Seconds 5
if ((Status "http://127.0.0.1:$Port/opendmtq/health.php") -eq 0) { Pass "with its window's processes gone, nothing answers" }
else { Fail "with its window's processes gone, nothing answers" }
$left = Get-Process -Name httpd, php, python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$bundle*" }
if (-not $left) { Pass "no program of the bundle is left running" }
else { $left | Format-Table Id, Path; Fail "no program of the bundle is left running" }

if ($failures -eq 0) { Write-Output "PASS the Windows bundle on Windows: 0 failure(s)"; exit 0 }
Write-Output "FAIL the Windows bundle on Windows: $failures failure(s)"
exit 1
