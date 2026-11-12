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
//   taskbar.exe slide-click X TOP SIZE FULL
//                         a click on a chip of the overlay's bar while the bar slides down, as a mouse makes it, the
//                         pointer still: the button pressed on the chip where it is in sight then and let go 90 ms
//                         later at the same place, by which time the bar's way has moved the chip on. X is the chip's
//                         middle across the bar's window, TOP its top row in the bar's picture, SIZE its height, FULL
//                         the picture's rows (the bar and its shadow's room): the window shows the picture without its
//                         top rows on the way, so the rows it lacks say where the chip is. The bar must be coming down
//                         when it is run. It presses once the chip is in sight while the bar still has half a chip's
//                         height or more of its way to go, a fifth of the chip's height under the top of its part in
//                         sight: on the chip still should a step of the bar come before the press is read, and off it
//                         once the bar is down, so that only a release read where the bar was at the press acts. It says
//                         what it did; "missed" when it never saw the bar there (a step of Wine's may jump past it).
//   taskbar.exe buttons   the buttons Windows draws on the window's title bar, from its style: "none" without a system
//                         menu, else each of minimise, maximise and close it has
//
// The player's window is found by its class (window_win32.cpp's frame). Exits 1 when there is none.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
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
    if (strcmp(argv[1], "slide-click") == 0 && argc >= 6) {
        const int x = atoi(argv[2]), top = atoi(argv[3]), size = atoi(argv[4]), full = atoi(argv[5]);
        HWND bar = window_of("OpenDMTQBar");
        if (!bar) {
            printf("no bar\n");
            return 0;
        }
        // The bar's window looked at every millisecond for 5 s: shown, with the rows of its picture it lacks (cut) few
        // enough to show more of the chip than the press's place, and no fewer than half the chip's height, the way still
        // to go.
        const int below = size / 5;
        for (int waited = 0; waited < 5000; ++waited) {
            RECT r;
            if (IsWindowVisible(bar) && GetWindowRect(bar, &r)) {
                const int cut = full - (int)(r.bottom - r.top);
                if (cut < size / 2) {
                    printf("missed: the bar was %d rows from down when it was first seen with the chip in sight\n", cut);
                    return 0;
                }
                if (cut < top + size - below) {
                    // A fifth of the chip's height under its first row in sight, in the bar's window.
                    const int y = (cut > top ? 0 : top - cut) + below;
                    PostMessageW(bar, WM_LBUTTONDOWN, MK_LBUTTON, MAKELPARAM(x, y));
                    Sleep(90);
                    PostMessageW(bar, WM_LBUTTONUP, 0, MAKELPARAM(x, y));
                    // Where the bar was at the release, for the log of the test.
                    GetWindowRect(bar, &r);
                    printf("pressed at %d,%d with %d rows of the bar's picture cut, let go there 90 ms later with %d cut\n", x, y, cut,
                           full - (int)(r.bottom - r.top));
                    return 0;
                }
            }
            Sleep(1);
        }
        printf("missed: no bar came down in 5 s\n");
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
