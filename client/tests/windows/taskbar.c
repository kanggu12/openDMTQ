// What Windows' taskbar does to the player's window, for the end-to-end test under Wine, which has no taskbar (e2e.sh
// builds it with the player's toolchain and runs it in the same Wine as the player):
//
//   taskbar.exe restore   a minimised player's window brought back, as a click on its taskbar button does (its
//                         restore command)
//   taskbar.exe buttons   the buttons Windows draws on the window's title bar, from its style: "none" without a system
//                         menu, else each of minimise, maximise and close it has
//
// The player's window is found by its class (window_win32.cpp's frame). Exits 1 when there is none.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char** argv) {
    HWND frame = FindWindowW(L"OpenDMTQPlayer", NULL);
    if (argc < 2 || !frame) {
        printf("no player's window\n");
        return 1;
    }
    if (strcmp(argv[1], "restore") == 0) {
        // Posted, as the taskbar's own click is: the player hears it on its thread.
        PostMessageW(frame, WM_SYSCOMMAND, SC_RESTORE, 0);
        printf("restore sent\n");
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
