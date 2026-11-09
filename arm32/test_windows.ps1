# Runs the tests of arm32/test_windows.sh on Windows itself: the guest test programs with the Windows build of the
# runner, then the Java VM, the mixer and the video reader with Windows' own decoders (Media Foundation). CI's job
# arm32-windows-real runs it on what the job arm32-windows built (.github/workflows/ci.yml).
#
#   arm32/test_windows.ps1 -Folder <folder>
#
# The folder holds build-windows-x86_64\*.exe, sysroot\, guest\ and media-test.mp4 (a red picture and a 1000 Hz tone, as
# arm32/test_windows.sh makes it with FFmpeg). Each program has a time limit, as in arm32/test_windows.sh: one that hangs
# is ended and named as a failure, and the tests after it still run. Windows PowerShell 5.1 and PowerShell 7 both run it.
param([Parameter(Mandatory = $true)][string]$Folder)
# The programs write to stderr as they go, which is no failure: Windows PowerShell 5.1 would stop at its first line.
$ErrorActionPreference = 'Continue'
$root = (Resolve-Path $Folder).Path
$bin = Join-Path $root 'build-windows-x86_64'
$sysroot = Join-Path $root 'sysroot'
$guest = Join-Path $root 'guest'
# The guest names files as Linux does: from the root of this folder's drive, with forward slashes.
$guestDir = $guest.Substring(2) -replace '\\', '/'
$runner = Join-Path $bin 'arm32run.exe'
$script:failed = $false

# One argument as a Windows program reads its command line back (CommandLineToArgvW's rules): as it is when it has no
# space, tab or quote; else in quotes, its quotes escaped and the backslashes before a quote, or before the closing one,
# doubled. Start-Process takes the arguments as one line, and Windows PowerShell 5.1 would join them with no quotes at all.
function ConvertTo-Argument([string]$value) {
    if ($value -ne '' -and $value -notmatch '[\s"]') { return $value }
    return '"' + (($value -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
}

# A program run with a time limit: its whole output as one text (its error output after the rest, the CRs of Windows'
# line ends gone), and whether it had to be ended. Its output goes to files: a program that hangs can then be ended while
# nothing waits on its pipes, and no console window opens for it.
function Invoke-Program([string]$exe, [string[]]$arguments, [int]$seconds) {
    $stdout = [System.IO.Path]::GetTempFileName()
    $stderr = [System.IO.Path]::GetTempFileName()
    $start = @{ FilePath = $exe; NoNewWindow = $true; PassThru = $true; RedirectStandardOutput = $stdout; RedirectStandardError = $stderr }
    # Windows PowerShell 5.1 refuses an empty list of arguments: a program with none gets no -ArgumentList.
    if ($arguments.Count -gt 0) { $start.ArgumentList = (($arguments | ForEach-Object { ConvertTo-Argument $_ }) -join ' ') }
    try {
        $process = Start-Process @start -ErrorAction Stop
    } catch {
        # Not there, or not a program: the test fails with Windows' reason.
        Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
        return [pscustomobject]@{ Text = "cannot start ${exe}: $_"; TimedOut = $false; Seconds = $seconds }
    }
    # True when it ended in time.
    $ended = $process.WaitForExit($seconds * 1000)
    if ($ended) {
        # The last of its output too: where PowerShell copies the output to the files itself (on Linux and macOS), only
        # this wait, with no limit, waits for that copy to finish. On Windows the program writes the files itself.
        $process.WaitForExit()
    } else {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        # Its files are free to read once it is gone.
        $null = $process.WaitForExit(10000)
    }
    $text = [System.IO.File]::ReadAllText($stdout) + "`n" + [System.IO.File]::ReadAllText($stderr)
    Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
    return [pscustomobject]@{ Text = ($text -replace "`r", ''); TimedOut = (-not $ended); Seconds = $seconds }
}

# One line for a test; for a failure, the end of its output under it. A program ended at its time limit is a failure
# whatever its output says, and the line names it so.
function Write-Result([string]$name, [bool]$ok, $run) {
    if ($ok -and -not $run.TimedOut) {
        Write-Output "PASS $name"
        return
    }
    if ($run.TimedOut) {
        Write-Output "FAIL $name (still running after $($run.Seconds) s: ended)"
    } else {
        Write-Output "FAIL $name"
    }
    $run.Text -split "`n" | Where-Object { $_ -notmatch 'DT_FLAGS_1' } | Select-Object -Last 15 | ForEach-Object { Write-Output "    $_" }
    $script:failed = $true
}

# Each guest program prints ALL CHECKS PASSED when every check held. The signal, interrupt and wake tests run several
# times: thread handshakes are where timing bugs show. 300 s each, as under Wine.
$tests = @('basic', 'signals', 'signals', 'signals', 'signals', 'signals', 'interrupt', 'interrupt', 'interrupt', 'wakes', 'wakes', 'wakes',
    'restart', 'restart', 'coherence', 'cxx', 'neon', 'memory', 'calls', 'descriptors', 'zones', 'dl')
foreach ($test in $tests) {
    $arguments = @('--sysroot', $sysroot, (Join-Path $guest $test))
    if ($test -eq 'dl') { $arguments += "$guestDir/libplugin.so" }
    $run = Invoke-Program $runner $arguments 300
    Write-Result $test ($run.Text -match 'ALL CHECKS PASSED') $run
}
# With fastmem, a store into a PROT_NONE page (a thread stack guard) must still fault: the runtime ends the process
# there, so the line after the store never prints.
$run = Invoke-Program $runner @('--sysroot', $sysroot, '--fastmem', (Join-Path $guest 'guard')) 120
Write-Result 'guard' (($run.Text -match 'touching a PROT_NONE page') -and -not ($run.Text -match 'did not fault')) $run
# The bridge: four host threads become guest threads and call into a guest library.
$run = Invoke-Program $runner @('--sysroot', $sysroot, '--agent', (Join-Path $guest 'arm32-agent'), '--call', "$guestDir/libplugin.so", 'plugin_add', '--threads', '4', '2', '3') 120
Write-Result 'bridge' (([regex]::Matches($run.Text, 'returned 1005')).Count -eq 4) $run
# Eight host threads become guest threads 5 ms apart while the running ones create and join guest threads.
$run = Invoke-Program $runner @('--sysroot', $sysroot, '--agent', (Join-Path $guest 'arm32-agent'), '--call', "$guestDir/libplugin.so", 'plugin_spawn', '--threads', '8', '--stagger', '5', '100') 120
Write-Result 'bridge-spawn' (([regex]::Matches($run.Text, '(?m)returned 100$')).Count -eq 8) $run
# The Java VM the desktop player hosts the game in, the player's mixer, and its PC settings file.
foreach ($program in @('jvmtest', 'audiotest', 'settingstest')) {
    $run = Invoke-Program (Join-Path $bin "$program.exe") @() 300
    Write-Result $program ($run.Text -match 'ALL CHECKS PASSED') $run
}
# The video path with Windows' own decoders. A Windows without Media Foundation (Windows Server without its feature, the
# N editions without their pack) has none to test: the player plays its videos blank there.
if (Test-Path (Join-Path $env:SystemRoot 'System32\mfplat.dll')) {
    $run = Invoke-Program (Join-Path $bin 'mediatest.exe') @((Join-Path $root 'media-test.mp4')) 300
    Write-Result 'media' ($run.Text -match 'ALL CHECKS PASSED') $run
} else {
    Write-Output 'SKIP media: this Windows has no Media Foundation'
}
# One line for scripts to read, and the exit status CI goes by.
if ($script:failed) {
    Write-Output 'SOME GUEST TESTS FAILED'
    exit 1
}
Write-Output 'ALL GUEST TESTS PASSED ON WINDOWS'
exit 0
