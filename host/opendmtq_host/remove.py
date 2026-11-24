"""Uninstalling: the server removed from this computer, once it has stopped. What it set up goes first (its start with the
computer, the command on the PATH, on Windows the firewall rules for its programs and its shortcuts), then its folder:
all of it, or all but data/ and .env when the data is kept. Asked for on the admin pages' Server page (uninstall.request,
which the running server's program acts on as it stops) or with `uninstall` on the command line.

On Windows a program cannot delete the folder it runs from: a small script of its own, outside the folder, waits until
this program and the window that started it have ended, deletes the folder, and then itself.
"""

import base64
import os
import shutil
import subprocess
import tempfile

from .paths import CLI, MAC, ROOT, WINDOWS
from .output import ok, say, warn

# What stays when the data is kept: the data and the settings.
KEPT = ("data", ".env")

# Windows' flag for a program started outside its parent's job (the job must allow it: server.py sets BREAKAWAY_OK).
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def in_folder(text):
    """True when text (a path, a unit, a shortcut's target) points into this install's folder."""
    root = os.path.normcase(os.path.abspath(ROOT))
    return root in os.path.normcase(text)


def remove_service():
    """The start with the computer, when it is this folder's: the systemd user unit's links and file (not stopped: this
    program, which systemd may be running, ends by itself, and a clean end is not started again), or macOS' launchd agent's
    file (launchd does not start a clean end again either)."""
    if WINDOWS:
        return
    if MAC:
        plist = os.path.expanduser("~/Library/LaunchAgents/org.opendmtq.server.plist")
    else:
        plist = os.path.expanduser("~/.config/systemd/user/opendmtq.service")
    try:
        with open(plist, encoding="utf-8") as f:
            if not in_folder(f.read()):
                # Another install's.
                return
    except OSError:
        return
    # A Linux without systemd (the unit written by an earlier version, or the system changed since) has no systemctl to
    # ask: the file goes all the same, and the rest of the uninstall goes on.
    systemd = not MAC and shutil.which("systemctl") is not None
    if systemd:
        subprocess.run(["systemctl", "--user", "disable", "opendmtq.service"], capture_output=True)
    os.remove(plist)
    if systemd:
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    ok(f"removed {plist}")


def remove_link():
    """The opendmtq command on the PATH (host/install.sh put it there), when it is this folder's: without a password asked
    for, where sudo needs one it is said instead."""
    if WINDOWS:
        return
    for folder in ("/usr/local/bin", os.path.expanduser("~/.local/bin")):
        link = os.path.join(folder, "opendmtq")
        if not (os.path.islink(link) and in_folder(os.readlink(link))):
            continue
        try:
            os.remove(link)
        except OSError:
            # A folder of the system's: sudo, only when it asks nothing.
            if subprocess.run(["sudo", "-n", "rm", "-f", link], capture_output=True).returncode != 0:
                warn(f"{link} stays (sudo rm {link} removes it)")
                continue
        ok(f"removed {link}")


def powershell(script, elevated=False):
    """Runs a PowerShell script, quietly; with elevated, in a process of its own that Windows asks the person to allow,
    not waited for. False where there is no PowerShell (Wine) or it failed."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    args = ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]
    if elevated:
        # Windows asks for permission once; the rules go whatever this program does meanwhile.
        outer = ("Start-Process powershell -Verb RunAs -WindowStyle Hidden -ArgumentList " +
                 ",".join(f"'{a}'" for a in args))
        args = ["-NoProfile", "-NonInteractive", "-Command", outer]
    try:
        r = subprocess.run(["powershell"] + args, capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def windows_leftovers():
    """On Windows: the firewall rules Windows made for the bundle's programs (when it asked whether Apache may use the
    network), and shortcuts into the folder on the Desktop and in the Startup folder."""
    root = os.path.abspath(ROOT).replace("'", "''")
    # The rules first, counted without asking: only when there are some does Windows ask for permission to remove them.
    rules = ("@(Get-NetFirewallApplicationFilter | Where-Object { $_.Program -like '" + root + "\\*' }).Count")
    try:
        encoded = base64.b64encode(rules.encode("utf-16-le")).decode("ascii")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True,
                           text=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        count = int(r.stdout.strip() or 0) if r.returncode == 0 else 0
    except (OSError, subprocess.SubprocessError, ValueError):
        count = 0
    if count:
        remove = ("Get-NetFirewallApplicationFilter | Where-Object { $_.Program -like '" + root + "\\*' } | "
                  "Get-NetFirewallRule | Remove-NetFirewallRule")
        if powershell(remove, elevated=True):
            ok(f"the firewall rules for its programs ({count}) are removed once Windows has the permission")
    # Shortcuts whose target is in the folder: the Desktop's and the Startup folder's, this user's.
    shortcuts = ("$s = New-Object -ComObject WScript.Shell; foreach ($f in @([Environment]::GetFolderPath('Startup'), "
                 "[Environment]::GetFolderPath('Desktop'))) { Get-ChildItem -LiteralPath $f -Filter *.lnk -ErrorAction "
                 "SilentlyContinue | Where-Object { $s.CreateShortcut($_.FullName).TargetPath -like '" + root + "\\*' } | "
                 "Remove-Item -Force }")
    powershell(shortcuts)


def remover_script(root, keep_data):
    """The Windows script that deletes the folder once nothing runs from it: it tries again every two seconds, for two
    minutes at most (the window that started this program closes a moment after it), then deletes itself."""
    lines = [
        "@echo off",
        # UTF-8, as this file is written: a folder under a name with letters outside the system's code page stays itself.
        "chcp 65001 >nul",
        # The folder, quoted for cmd (a path may have spaces; cmd's own special characters cannot be in a Windows path
        # this program runs from but & and ^, which the quotes keep).
        f'set "D={root}"',
        "set /a N=0",
        ":again",
    ]
    if keep_data:
        lines += [
            # Every folder but data, every file but .env.
            'for /d %%i in ("%D%\\*") do if /i not "%%~nxi"=="data" rd /s /q "%%i" 2>nul',
            'for %%i in ("%D%\\*") do if /i not "%%~nxi"==".env" del /f /q "%%i" 2>nul',
            # Done once only the kept ones are left.
            'set LEFT=0',
            'for /d %%i in ("%D%\\*") do if /i not "%%~nxi"=="data" set LEFT=1',
            'for %%i in ("%D%\\*") do if /i not "%%~nxi"==".env" set LEFT=1',
            'if "%LEFT%"=="0" goto done',
        ]
    else:
        lines += [
            'rd /s /q "%D%" 2>nul',
            'if not exist "%D%" goto done',
        ]
    lines += [
        "set /a N+=1",
        "if %N% GEQ 60 goto done",
        # Two seconds (Windows' timeout needs a console; ping does not).
        "ping -n 3 127.0.0.1 >nul",
        "goto again",
        ":done",
        # Itself last: cmd has read it whole by then.
        '(goto) 2>nul & del /f /q "%~f0"',
    ]
    return "\r\n".join(lines) + "\r\n"


def remove_folder(keep_data):
    """The folder's files: all of them, or all but data/ and .env. On Windows by remover_script, started now and outliving
    this program; elsewhere at once."""
    root = os.path.abspath(ROOT)
    if WINDOWS:
        script = os.path.join(tempfile.gettempdir(), f"opendmtq-uninstall-{os.getpid()}.cmd")
        with open(script, "w", encoding="utf-8", newline="") as f:
            f.write(remover_script(root, keep_data))
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0))
        # Outside the job that ends every program of this one with it (server.py, end_with_this_program), or the script
        # would end with this program, before it deleted anything. Where another job around this one does not allow
        # that, in it all the same.
        for breakaway in (CREATE_BREAKAWAY_FROM_JOB, 0):
            try:
                # Out of the folder, so that it is not this script's own folder that is in use.
                subprocess.Popen(["cmd", "/c", script], cwd=tempfile.gettempdir(), creationflags=flags | breakaway,
                                 close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                break
            except OSError:
                continue
        ok(f"{root} is deleted once this window has closed" + (" (data and .env stay)" if keep_data else ""))
        return
    for name in os.listdir(root):
        if keep_data and name in KEPT:
            continue
        path = os.path.join(root, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass
    if keep_data:
        ok(f"removed the program from {root}; data/ and .env stay there")
        return
    try:
        os.rmdir(root)
        ok(f"removed {root}")
    except OSError:
        warn(f"{root} is not quite empty: something else put files there")


def uninstall(keep_data):
    """Everything this install set up, then its folder (keep_data: data/ and .env stay)."""
    say("Uninstalling OpenDMTQ" + (", keeping the data" if keep_data else ""))
    remove_service()
    remove_link()
    if WINDOWS:
        windows_leftovers()
    remove_folder(keep_data)
    say("OpenDMTQ is uninstalled." if not keep_data else
        f"OpenDMTQ is uninstalled. Its data stays in {os.path.join(os.path.abspath(ROOT), 'data')}; the same folder "
        f"with OpenDMTQ in it again takes it back ({CLI} setup).")
