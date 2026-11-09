# The PC client on Windows itself (CI's client-windows job, a windows-2022 runner): the installer as a release builds it,
# silently, for this Windows user, then what it installed, without a window: the command line twin, the player it
# carries (found by the ready check, and its sound devices), and a second run of the same installer (a repair).
#
#   client/tests/windows/install.ps1 -Folder <client/packaging/windows/build.sh's releases folder>
#
# Prints one PASS or FAIL line a check and ends with 1 when any failed.
param([Parameter(Mandatory = $true)] [string] $Folder)
$ErrorActionPreference = 'Stop'
$setup = Join-Path $Folder 'OpenDMTQ-Setup.exe'
# The version the build gave the installer (the chart's).
$version = (Get-Content (Join-Path $Folder 'OpenDMTQ-Setup.exe.version') -Raw).Trim()
# Where Velopack installs for this user: its package id's folder (client/opendmtq_client/installer.py).
$installed = Join-Path $env:LOCALAPPDATA 'OpenDMTQ.Client'
$script:failed = 0

# One check: its line, and a failure counted.
function Check([string] $what, [bool] $ok) {
    if ($ok) { Write-Output "PASS $what" } else { Write-Output "FAIL $what"; $script:failed++ }
}

# A program run with a time limit, its output and exit code: a dialog nobody can answer must not hold CI for hours.
function Run([string] $exe, [string[]] $arguments, [int] $seconds = 300) {
    $out = Join-Path $env:TEMP ([guid]::NewGuid().ToString() + '.txt')
    $p = Start-Process $exe -ArgumentList $arguments -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError "$out.err"
    if (-not $p.WaitForExit($seconds * 1000)) {
        $p.Kill()
        return @{ code = -1; text = "(stopped after $seconds s)" }
    }
    $text = ((Get-Content $out -Raw -ErrorAction SilentlyContinue) + (Get-Content "$out.err" -Raw -ErrorAction SilentlyContinue))
    return @{ code = $p.ExitCode; text = "$text" }
}

# 1. Installed silently, the launcher not started.
$r = Run $setup @('--silent', '--no-start') 600
Check "the installer ends with 0 (exit $($r.code))" ($r.code -eq 0)
$cmd = Join-Path $installed 'current\OpenDMTQ-cmd.exe'
Check "the launcher's command line is installed ($cmd)" (Test-Path $cmd)
Check "the launcher's window program is installed" (Test-Path (Join-Path $installed 'current\OpenDMTQ.exe'))
Check "the licence texts came with it" (Test-Path (Join-Path $installed 'current\licenses\NOTICES.txt'))
$player = Get-ChildItem -Recurse -Filter 'OpenDMTQ-Player.exe' (Join-Path $installed 'current') | Select-Object -First 1
Check "the player came with it" ($null -ne $player)

# 2. The command line says its version and its state: no server yet, the player found.
$r = Run $cmd @('--version') 60
Check "it says its version, $version ($($r.text.Trim()))" ($r.text -match [regex]::Escape($version))
$r = Run $cmd @('--status') 120
Write-Output $r.text
Check "--status answers with no server yet (exit $($r.code))" (($r.code -eq 1) -and ($r.text -match 'server: none'))
Check "--status finds the player it installed" ($r.text -match '\[ok  \] player')

# 3. The player lists the sound devices without a window (none on a runner is an answer too).
$r = Run $cmd @('--audio-devices') 120
Write-Output $r.text
Check "the player answers --audio-devices (exit $($r.code))" ($r.code -eq 0)

# 4. The same installer again: a repair, as the dialog offers it, and still one program.
$r = Run $setup @('--silent', '--no-start') 600
Check "a second run of the installer ends with 0 (exit $($r.code))" ($r.code -eq 0)
$r = Run $cmd @('--version') 60
Check "after it, still $version" ($r.text -match [regex]::Escape($version))

# Velopack's and the installer's own logs, for a look when something failed.
Get-ChildItem $env:TEMP -Filter 'OpenDMTQ-setup*.log' -ErrorAction SilentlyContinue | Select-Object -Last 2 | ForEach-Object {
    Write-Output "--- $($_.Name)"
    Get-Content $_.FullName -Tail 15
}
if ($script:failed) {
    Write-Output "$script:failed check(s) FAILED"
    exit 1
}
Write-Output 'ALL CHECKS PASSED'
