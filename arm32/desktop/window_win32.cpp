// The player's window on Windows: a Win32 window that the game's EGL surface draws into, through ANGLE. The window's
// handle (HWND) is what the game gets as its ANativeWindow (ndk.cpp) and what ANGLE's EGL takes as the native window,
// so the runtime's EGL bridge passes it on as it is. The Java side is an android.view.Surface naming the window.
//
// The window keeps the screen's own pixels (per-monitor DPI awareness): the game renders at the size Windows shows,
// not at a smaller one stretched. A touch screen's fingers (several at once, through the pointer messages), a pen and
// the mouse's left button are the game's fingers; the keyboard types into the soft keyboard while the game asks for
// text. F11 and Alt+Enter switch full screen.
#include "player.h"

#include <windows.h>

#include <cstdlib>
#include <string>

namespace player {

namespace {

HWND g_window = nullptr;
// The close button was pressed.
bool g_closed = false;
// Whether the mouse's left button is down (a finger on the screen).
bool g_pressed = false;
// Full screen: the window's place and style before, to go back to.
bool g_fullscreen = false;
WINDOWPLACEMENT g_placement{};
// A UTF-16 high surrogate from WM_CHAR, waiting for its low half.
wchar_t g_high = 0;

// android.view.Surface: the window it stands for.
class Surface : public jvm::Object {
public:
    Surface(jvm::Class* cls, HWND window) : Object(cls), window(window) {}
    const HWND window;
};

jvm::Ref<jvm::Object> g_surface;

// The window over the whole monitor it is on, without its frame, and back.
void toggle_fullscreen(HWND h) {
    DWORD style = static_cast<DWORD>(GetWindowLongW(h, GWL_STYLE));
    if (!g_fullscreen) {
        MONITORINFO mi{};
        mi.cbSize = sizeof mi;
        g_placement.length = sizeof g_placement;
        if (GetWindowPlacement(h, &g_placement) && GetMonitorInfoW(MonitorFromWindow(h, MONITOR_DEFAULTTOPRIMARY), &mi)) {
            SetWindowLongW(h, GWL_STYLE, static_cast<LONG>(style & ~WS_OVERLAPPEDWINDOW));
            SetWindowPos(h, HWND_TOP, mi.rcMonitor.left, mi.rcMonitor.top, mi.rcMonitor.right - mi.rcMonitor.left, mi.rcMonitor.bottom - mi.rcMonitor.top,
                         SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
            g_fullscreen = true;
        }
    } else {
        SetWindowLongW(h, GWL_STYLE, static_cast<LONG>(style | WS_OVERLAPPEDWINDOW));
        SetWindowPlacement(h, &g_placement);
        SetWindowPos(h, nullptr, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
        g_fullscreen = false;
    }
}

// One character typed (WM_CHAR's UTF-16 units) as UTF-8, for the soft keyboard.
void typed(wchar_t c) {
    if (c >= 0xD800 && c <= 0xDBFF) {
        g_high = c;
        return;
    }
    wchar_t pair[2] = {c, 0};
    int n = 1;
    if (c >= 0xDC00 && c <= 0xDFFF && g_high) {
        pair[0] = g_high;
        pair[1] = c;
        n = 2;
    }
    g_high = 0;
    char out[8];
    int k = WideCharToMultiByte(CP_UTF8, 0, pair, n, out, sizeof out, nullptr, nullptr);
    if (k > 0) type_text(std::string(out, static_cast<std::size_t>(k)));
}

LRESULT CALLBACK window_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    switch (msg) {
    case WM_CLOSE:
        g_closed = true;
        return 0;
    case WM_SIZE:
        // The size ANativeWindow reports follows the window's.
        if (w != SIZE_MINIMIZED) {
            app().width = LOWORD(l);
            app().height = HIWORD(l);
        }
        return 0;
    case WM_LBUTTONDOWN:
        // The mouse's first button is a finger: pressed, moved while pressed, lifted; held even outside the window.
        SetCapture(h);
        g_pressed = true;
        touch(0, static_cast<float>(static_cast<short>(LOWORD(l))), static_cast<float>(static_cast<short>(HIWORD(l))));
        return 0;
    case WM_MOUSEMOVE:
        if (g_pressed) touch(2, static_cast<float>(static_cast<short>(LOWORD(l))), static_cast<float>(static_cast<short>(HIWORD(l))));
        return 0;
    case WM_LBUTTONUP:
        if (g_pressed) {
            g_pressed = false;
            ReleaseCapture();
            touch(1, static_cast<float>(static_cast<short>(LOWORD(l))), static_cast<float>(static_cast<short>(HIWORD(l))));
        }
        return 0;
    case WM_POINTERDOWN:
    case WM_POINTERUPDATE:
    case WM_POINTERUP: {
        // A touch screen's fingers and a pen, each one a finger of the game's; the mouse keeps its own messages above.
        const UINT32 id = GET_POINTERID_WPARAM(w);
        POINTER_INPUT_TYPE type = PT_POINTER;
        if (!GetPointerType(id, &type) || type == PT_MOUSE) break;
        // A pen above the screen moves without touching it.
        if (msg == WM_POINTERUPDATE && !IS_POINTER_INCONTACT_WPARAM(w)) return 0;
        // Screen pixels, into the window's.
        POINT p{static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l))};
        ScreenToClient(h, &p);
        finger(static_cast<int>(id), msg == WM_POINTERDOWN ? 0 : msg == WM_POINTERUP ? 1 : 2, static_cast<float>(p.x), static_cast<float>(p.y));
        return 0;
    }
    case WM_POINTERCAPTURECHANGED:
        // The system took the fingers away (a gesture of its own): the game's gesture is cancelled.
        finger(static_cast<int>(GET_POINTERID_WPARAM(w)), 3, 0, 0);
        return 0;
    case WM_CHAR:
        // Text while the game asks for it: printable characters only; the keys that end or edit it come as keys.
        if (typing() && w >= 0x20) typed(static_cast<wchar_t>(w));
        return 0;
    case WM_SYSKEYDOWN:
        // Alt+Enter: full screen, as Windows games switch.
        if (w == VK_RETURN && (HIWORD(l) & KF_ALTDOWN)) {
            toggle_fullscreen(h);
            return 0;
        }
        break;
    case WM_KEYDOWN:
        if (w == VK_F11) {
            toggle_fullscreen(h);
            return 0;
        }
        if (typing()) {
            if (w == VK_RETURN) type_key(kKeyEnter);
            else if (w == VK_ESCAPE) type_key(kKeyEscape);
            else if (w == VK_BACK) type_key(kKeyBackspace);
        }
        return 0;
    case WM_ERASEBKGND:
        // The game draws every pixel: no flash of the background between frames.
        return 1;
    default:
        break;
    }
    return DefWindowProcW(h, msg, w, l);
}

}  // namespace

bool open_window(const std::string& title) {
    // The screen's own pixels on every monitor: Windows 10's per-monitor awareness, where it has it.
    if (HMODULE user = GetModuleHandleW(L"user32.dll")) {
        using SetContext = BOOL(WINAPI*)(HANDLE);
        if (auto set = reinterpret_cast<SetContext>(GetProcAddress(user, "SetProcessDpiAwarenessContext"))) set(reinterpret_cast<HANDLE>(-4));
    }
    HINSTANCE instance = GetModuleHandleW(nullptr);
    if (app().fit_screen) {
        // Three quarters of the screen's height left by the taskbar, at 16:9, and no wider than nine tenths of it: a
        // window that fits whatever the screen and its scaling (the pixels are the screen's own).
        RECT work{};
        if (SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0)) {
            int w = work.right - work.left, h = work.bottom - work.top;
            app().height = h * 3 / 4;
            app().width = app().height * 16 / 9;
            if (app().width > w * 9 / 10) {
                app().width = w * 9 / 10;
                app().height = app().width * 9 / 16;
            }
        }
    }
    WNDCLASSEXW wc{};
    wc.cbSize = sizeof wc;
    wc.style = CS_OWNDC;
    wc.lpfnWndProc = window_proc;
    wc.hInstance = instance;
    // The system's arrow (IDC_ARROW is its number as a narrow-string name, which LoadCursorA takes).
    wc.hCursor = LoadCursorA(nullptr, IDC_ARROW);
    // The program's own icon (player.rc), in the title bar and the taskbar.
    wc.hIcon = LoadIconW(instance, MAKEINTRESOURCEW(1));
    wc.hbrBackground = static_cast<HBRUSH>(GetStockObject(BLACK_BRUSH));
    wc.lpszClassName = L"OpenDMTQPlayer";
    RegisterClassExW(&wc);
    // The client area is the game's size; the frame goes around it.
    RECT r{0, 0, app().width, app().height};
    AdjustWindowRectEx(&r, WS_OVERLAPPEDWINDOW, FALSE, 0);
    int n = MultiByteToWideChar(CP_UTF8, 0, title.c_str(), -1, nullptr, 0);
    std::wstring wtitle(static_cast<std::size_t>(n > 0 ? n - 1 : 0), L'\0');
    if (n > 1) MultiByteToWideChar(CP_UTF8, 0, title.c_str(), -1, wtitle.data(), n);
    g_window = CreateWindowExW(0, wc.lpszClassName, wtitle.c_str(), WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT, r.right - r.left, r.bottom - r.top, nullptr,
                               nullptr, instance, nullptr);
    if (!g_window) {
        jvm::log("player: cannot make a window (error %lu)", GetLastError());
        return false;
    }
    ShowWindow(g_window, SW_SHOW);
    UpdateWindow(g_window);
    // The size Windows gave the client area, which the scaling of the screen may have changed.
    RECT client;
    if (GetClientRect(g_window, &client)) {
        app().width = client.right - client.left;
        app().height = client.bottom - client.top;
    }
    g_surface = jvm::Ref<jvm::Object>(new Surface(&jvm::define("android/view/Surface"), g_window));
    return true;
}

jvm::Object* surface() { return g_surface.get(); }

std::uintptr_t window_of(jvm::Object* surface) {
    auto* s = dynamic_cast<Surface*>(surface);
    return s ? reinterpret_cast<std::uintptr_t>(s->window) : 0;
}

bool pump_window() {
    MSG m;
    while (PeekMessageW(&m, nullptr, 0, 0, PM_REMOVE)) {
        TranslateMessage(&m);
        DispatchMessageW(&m);
    }
    return !g_closed;
}

}  // namespace player
