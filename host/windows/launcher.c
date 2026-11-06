/*
 * OpenDMTQ.exe, the Windows bundle's launcher: runs the bundle's own Python with the host program
 * (app\host\opendmtq_host) in this console window, passes on whatever it was given (a command, or the folder a person
 * dropped on it), and ends with its exit status. The host program does all the work; this only has to find it.
 *
 * Built on Linux with MinGW-w64 (host/windows/build.sh), linked statically, so that it needs nothing but Windows.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <wchar.h>

/* Room for long folder names (Windows allows paths beyond MAX_PATH with long path support on). */
#define PATH_ROOM 4096

/* The rest of this program's command line, after its own name (quoted or not) and the spaces after it. */
static const wchar_t *arguments(void)
{
    const wchar_t *cmd = GetCommandLineW();
    if (*cmd == L'"') {
        /* A quoted name ends at the next quote. */
        cmd++;
        while (*cmd && *cmd != L'"') {
            cmd++;
        }
        if (*cmd) {
            cmd++;
        }
    } else {
        /* An unquoted one at the first space or tab. */
        while (*cmd && *cmd != L' ' && *cmd != L'\t') {
            cmd++;
        }
    }
    while (*cmd == L' ' || *cmd == L'\t') {
        cmd++;
    }
    return cmd;
}

/* A message box for what went wrong before there is a program to say it (the window may close at once). */
static int fail(const wchar_t *text)
{
    MessageBoxW(NULL, text, L"OpenDMTQ", MB_OK | MB_ICONERROR);
    return 1;
}

int wmain(void)
{
    static wchar_t dir[PATH_ROOM], python[PATH_ROOM], script[PATH_ROOM], line[PATH_ROOM * 3];
    /* This program's own path; the bundle is the folder it is in. */
    DWORD n = GetModuleFileNameW(NULL, dir, PATH_ROOM);
    if (n == 0 || n >= PATH_ROOM) {
        return fail(L"OpenDMTQ could not find its own folder.");
    }
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (!slash) {
        return fail(L"OpenDMTQ could not find its own folder.");
    }
    *slash = 0;
    /* The bundle's Python and the host program, by full path. */
    swprintf(python, PATH_ROOM, L"%ls\\runtime\\python\\python.exe", dir);
    swprintf(script, PATH_ROOM, L"%ls\\app\\host\\opendmtq_host", dir);
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES || GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        return fail(L"Parts of OpenDMTQ are missing. Unpack the whole zip again, into a folder of its own, and start "
                    L"OpenDMTQ.exe from there.");
    }
    /* Isolated (-I: no Python settings of this PC change it) and in UTF-8 (-X utf8: Korean file names read right),
       then the host program and what this program was given. */
    swprintf(line, PATH_ROOM * 3, L"\"%ls\" -I -X utf8 \"%ls\" %ls", python, script, arguments());
    /* The window's title, and UTF-8 for what is printed in it. */
    SetConsoleTitleW(L"OpenDMTQ");
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
    /* Ctrl+C and closing the window reach the host program through the window it shares; this one only waits. */
    SetConsoleCtrlHandler(NULL, TRUE);
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    /* This program's own input and output, whatever they are: the window, or files and pipes when a script started it
       with its output sent elsewhere (handed on explicitly: Python stops at once without them). */
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    si.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    ZeroMemory(&pi, sizeof pi);
    /* In the bundle's folder, so that a relative path given to a command means the same as in a terminal there. The
       handles above are inherited, nothing else of this program is open. */
    if (!CreateProcessW(python, line, NULL, NULL, TRUE, 0, NULL, dir, &si, &pi)) {
        return fail(L"OpenDMTQ could not start its Python (runtime\\python). Unpack the whole zip again.");
    }
    CloseHandle(pi.hThread);
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    return (int)code;
}
