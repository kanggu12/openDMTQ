// What Windows' taskbar and Windows itself do to the player's window, for the end-to-end test under Wine, which has no
// taskbar and does some of it otherwise (e2e.sh builds it with the player's toolchain and runs it in the same Wine as
// the player):
//
//   taskbar.exe minimise  the player's window minimised as Windows minimises it: Windows first hides the pop-ups the
//                         window owns itself (WM_SHOWWINDOW with SW_PARENTCLOSING to each one shown), which Wine does not
//                         do at a minimise, then the window goes, by its minimise command as the taskbar sends it
//   taskbar.exe restore   a minimised player's window brought back, as a click on its taskbar button does (its
//                         restore command); then, as Windows does once the window is back, the pop-ups it hid at the
//                         minimise shown again (WM_SHOWWINDOW with SW_PARENTOPENING to each pop-up the window owns: one
//                         Windows did not hide answers it by staying as it is)
//   taskbar.exe shown CLASS  whether the player's window of that class (the overlay's OpenDMTQBar, OpenDMTQBarHandle,
//                         ...) is on the screen: "shown", "hidden", or "none" when there is no such window
//   taskbar.exe buttons   the buttons Windows draws on the window's title bar, from its style: "none" without a system
//                         menu, else each of minimise, maximise and close it has
//
// The player's window is found by its class (window_win32.cpp's frame). Exits 1 when there is none.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>

// The player's window, which the pop-ups to show again belong to (EnumWindows passes it through).
static HWND g_frame = NULL;

// One window of the desktop: a pop-up of the player's window is shown again as Windows shows it when the window is back.
static BOOL CALLBACK show_again(HWND window, LPARAM unused) {
    (void)unused;
    // Sent, as Windows sends it: the pop-up answers before the next one is asked.
    if (GetWindow(window, GW_OWNER) == g_frame) SendMessageW(window, WM_SHOWWINDOW, TRUE, SW_PARENTOPENING);
    return TRUE;
}

// The window of the player's of a class, or NULL.
static HWND window_of(const char* name) {
    wchar_t wide[64];
    MultiByteToWideChar(CP_UTF8, 0, name, -1, wide, 64);
    // Every pop-up of the player's is a window of the desktop's own, owned by the player's window.
    return FindWindowW(wide, NULL);
}

int main(int argc, char** argv) {
    HWND frame = FindWindowW(L"OpenDMTQPlayer", NULL);
    if (argc < 2 || !frame) {
        printf("no player's window\n");
        return 1;
    }
    g_frame = frame;
    if (strcmp(argv[1], "minimise") == 0) {
        // Windows' own part first: the window's pop-ups hidden, each told why (SW_PARENTCLOSING), as before a minimise.
        ShowOwnedPopups(frame, FALSE);
        // Then the window, by the minimise command its taskbar button sends: the player hears it on its thread.
        PostMessageW(frame, WM_SYSCOMMAND, SC_MINIMIZE, 0);
        printf("minimise sent, its pop-ups hidden first\n");
        return 0;
    }
    if (strcmp(argv[1], "restore") == 0) {
        // Posted, as the taskbar's own click is: the player hears it on its thread.
        PostMessageW(frame, WM_SYSCOMMAND, SC_RESTORE, 0);
        // Back (no longer minimised) within 10 s, looked for every 10 ms; then Windows' own part, the pop-ups it hid.
        for (int waited = 0; waited < 1000 && IsIconic(frame); ++waited) Sleep(10);
        if (IsIconic(frame)) {
            printf("restore sent; the window is still minimised\n");
            return 0;
        }
        EnumWindows(show_again, 0);
        printf("restore sent, its pop-ups shown again as Windows does\n");
        return 0;
    }
    if (strcmp(argv[1], "shown") == 0 && argc >= 3) {
        HWND window = window_of(argv[2]);
        printf("%s\n", !window ? "none" : IsWindowVisible(window) ? "shown" : "hidden");
        return 0;
    }
    const LONG style = GetWindowLongW(frame, GWL_STYLE);
    // Windows draws the title bar's buttons only with a system menu: minimise and maximise with their boxes, close always.
    if (!(style & WS_SYSMENU)) {
        printf("buttons: none (style %08lx)\n", (unsigned long)style);
        return 0;
    }
    printf("buttons:%s%s close (style %08lx)\n", (style & WS_MINIMIZEBOX) ? " minimise" : "", (style & WS_MAXIMIZEBOX) ? " maximise" : "",
           (unsigned long)style);
    return 0;
}
