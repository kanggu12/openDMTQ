// The player's window on Windows: a frame window and, inside it, the game's own window, a child that the game's EGL
// surface draws into through ANGLE. The child's handle (HWND) is what the game gets as its ANativeWindow (ndk.cpp) and
// what ANGLE's EGL takes as the native window, so the runtime's EGL bridge passes it on as it is. The Java side is an
// android.view.Surface naming it.
//
// The game's window keeps the screen's own pixels (per-monitor DPI awareness): the game renders at the size Windows
// shows, not at a smaller one stretched. It fills the frame while the frame's shape is one the game lays itself out for,
// from a tablet's 4:3 to a long phone's 21:9; a frame of another shape (a portrait monitor in full screen) gets the
// largest such area, centred, with black around it. When its size changes (the frame resized, full screen, another
// display's scaling) the game is told, as Android tells it (surface_changed).
//
// The display the window is on gives the frame rate: its exact refresh rate from the display configuration, and its
// refreshes from DXGI's wait for them, on a thread of its own (pacing.h). Both are read again when the window moves to
// another display or a display's mode changes.
//
// Input: a touch screen's fingers (several at once, through the pointer messages, with the time the screen saw each), a
// pen and the mouse's left button are the game's fingers, and the wheel a finger's drag that scrolls. Windows' own touch
// feedback and gestures stay out of the game's way (no circles, no press-and-hold, no edge swipes in full screen), and
// the UI thread takes each event as it comes. The keyboard types into the soft keyboard while the
// game asks for text, through a text field of the window's that it focuses meanwhile (Windows' touch keyboard offers
// itself there on a PC without a keyboard); otherwise its keys are the phone's, Escape the Back key (it pauses a song and
// closes what is open). No key switches full screen or quits: full screen is the overlay's bar's button (or the
// launcher's Screen page before a start), quitting the bar's X, which asks first; F11, Alt+Enter and Alt+F4 do nothing.
#include "player.h"

#include "overlay_scale.h"
#include "overlay_win32.h"
#include "post_pass.h"
#include "offscreen.h"
#include "pacing.h"

#include <windows.h>
#include <dxgi.h>
#include <imm.h>
#include <inspectable.h>
#include <propsys.h>
#include <shellapi.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <cwchar>
#include <chrono>
#include <cstdlib>
#include <map>
#include <set>
#include <string>
#include <thread>
#include <vector>

namespace arm32 {
// live_desktop.cpp: the game held still (the question before quitting is up, or the window is minimised), or going on.
void desktop_live_paused(bool paused);
// The player's stats (ARM32_STATS; log.cpp): the overlay says what its pictures cost with them.
extern bool g_stats;
}  // namespace arm32

namespace player {

namespace {

// The frame (title, border, the black around the game) and the game's window in it.
HWND g_frame = nullptr;
HWND g_window = nullptr;
// The close button was pressed.
bool g_closed = false;
// The window is open and the game has its surface: size changes are the game's to hear from then on.
bool g_started = false;
// Whether the mouse's left button is down (a finger on the screen).
bool g_pressed = false;
// Full screen: the frame's place and style before, to go back to.
bool g_fullscreen = false;
WINDOWPLACEMENT g_placement{};
// Whether the frame is minimised (by the bar's minimise, the taskbar or Windows), as the log tells it once each way.
bool g_minimised = false;
// A UTF-16 high surrogate from WM_CHAR, waiting for its low half.
wchar_t g_high = 0;
// The keys held down, as the phone's keys, with how often each has repeated: lifted when the window loses the keyboard.
std::map<WPARAM, int> g_keys_down;
// The UI thread, which a job posted to its looper wakes (wait_for_events), and the text field the keyboard types into
// while the game asks for text (soft_keyboard).
DWORD g_ui_thread = 0;
HWND g_edit = nullptr;
// Whether the last input on the game was a touch (a pen's too): the touch keyboard then offers itself for text.
bool g_last_touch = false;
// The game's area in the window's pixels. The game draws at app()'s size, which is the area's own or, with a render
// scale below 100 % in the PC's settings, that share of it, and ANGLE stretches its picture over the area (pacing.h's
// g_window_fixed_size). Input comes in the area's pixels and goes to the game in its own.
int g_area_w = 0, g_area_h = 0;
// Quit the game chosen on the overlay's question, to the frame: the bar's X and the window's own close ask it first.
constexpr UINT kQuitMessage = WM_APP + 1;
// A check's character for the input method (PLAYER_KEYS ime=): composed on the text field's own thread, where the input
// context lives. wParam the character, lParam 1 to compose it and 2 to finish it.
constexpr UINT kImeMessage = WM_APP + 2;
// A check's planned key (PLAYER_KEYS): when it was posted, on the steady clock in nanoseconds (0: none waits), so that
// the window says how long it waited before the UI thread took it, which is when the key is stamped for the game.
std::atomic<long long> g_key_posted{0};
// A check's trace of the mouse on the game's window (PLAYER_TRACE_INPUT=1): each press and release said in the log, where
// the game has it, so that a check sees a click reach the game through what the overlay draws over it.
bool trace_input() {
    static const bool on = [] {
        const char* v = std::getenv("PLAYER_TRACE_INPUT");
        return v && *v && *v != '0';
    }();
    return on;
}
// Which window a trace line names: its class (the overlay's are OpenDMTQBar, OpenDMTQNotice and so on), or none of
// this program's.
std::string window_class(HWND h) {
    if (!h) return "to no window of this program";
    wchar_t name[128] = {};
    GetClassNameW(h, name, 128);
    char out[256] = {};
    WideCharToMultiByte(CP_UTF8, 0, name, -1, out, sizeof out, nullptr, nullptr);
    return std::string("to ") + out;
}
// The steady clock in nanoseconds, as the planned keys' poster stamps them.
long long steady_ns() { return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
// Esc is the phone's Back key, sent when it comes up: whether it went down over the game, and whether the question took
// it (Esc answering Keep playing is no Back key when it comes up).
bool g_esc_down = false, g_esc_held = false;
// A finger that came down on the game's top edge: drawn down, it shows the overlay's bar instead of reaching the game;
// lifted where it was, it is a tap after all. Its pointer id (0: none) and where it started, in the game's window.
UINT32 g_edge_finger = 0;
// The touch screen's fingers and the pens on the game now, by their ids: with the mouse's button, whether anything is
// down on the game, which the overlay hears of with each press and release (no bar from the top while one is).
std::set<UINT32> g_contacts;
POINT g_edge_from{};
// When it came down, for the tap's own time if it is one.
std::int64_t g_edge_time = 0;

// The shapes the game lays itself out for: a tablet's 4:3 to a long phone's 21:9. Beyond them its screens fall apart
// (a portrait shape squeezes its whole layout into the middle).
constexpr double kNarrowest = 4.0 / 3.0, kWidest = 21.0 / 9.0;

// The display the frame is on, for its refresh rate and refreshes, and a display's mode change for the refresh thread.
std::atomic<HMONITOR> g_monitor{nullptr};
std::atomic<bool> g_displays_changed{false};

// android.view.Surface: the window it stands for.
class Surface : public jvm::Object {
public:
    Surface(jvm::Class* cls, HWND window) : Object(cls), window(window) {}
    const HWND window;
};

jvm::Ref<jvm::Object> g_surface;

// The monotonic clock, as the runtime's pacing reads it (the Windows layer's clock_gettime).
std::int64_t now_ns() {
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<std::int64_t>(ts.tv_sec) * 1000000000 + ts.tv_nsec;
}

std::string narrow(const wchar_t* s) {
    int n = WideCharToMultiByte(CP_UTF8, 0, s, -1, nullptr, 0, nullptr, nullptr);
    std::string out(static_cast<std::size_t>(n > 0 ? n - 1 : 0), '\0');
    if (n > 1) WideCharToMultiByte(CP_UTF8, 0, s, -1, out.data(), n, nullptr, nullptr);
    return out;
}

// A point on the game's window, in its pixels, as the game's: the same, or smaller by the render scale.
float game_x(int x) { return g_area_w > 0 ? static_cast<float>(x) * static_cast<float>(app().width) / static_cast<float>(g_area_w) : static_cast<float>(x); }
float game_y(int y) { return g_area_h > 0 ? static_cast<float>(y) * static_cast<float>(app().height) / static_cast<float>(g_area_h) : static_cast<float>(y); }

// The dpi of the display a window is on, as Windows scales it there (96 at 100 %); 0 where Windows cannot say (before
// Windows 10 1607, which has the call).
UINT window_dpi(HWND h) {
    using DpiOf = UINT(WINAPI*)(HWND);
    static HMODULE user = GetModuleHandleW(L"user32.dll");
    static auto dpi_of = reinterpret_cast<DpiOf>(user ? GetProcAddress(user, "GetDpiForWindow") : nullptr);
    return dpi_of && h ? dpi_of(h) : 0;
}

// The frame's outer size for a client area of w by h at the frame's own scaling (Windows 10 1607 has the call that
// takes it; an older Windows sizes by the system's).
SIZE frame_size(int w, int h) {
    RECT r{0, 0, w, h};
    using ForDpi = BOOL(WINAPI*)(LPRECT, DWORD, BOOL, DWORD, UINT);
    static HMODULE user = GetModuleHandleW(L"user32.dll");
    static auto for_dpi = reinterpret_cast<ForDpi>(user ? GetProcAddress(user, "AdjustWindowRectExForDpi") : nullptr);
    const DWORD style = static_cast<DWORD>(GetWindowLongW(g_frame, GWL_STYLE));
    // A tool window's title bar is a shorter one (a test's unlisted window, window_unlisted): that style is asked about
    // too, so that its game's area is the size asked for as well. A player's window never has it, and its frame is the
    // size it always was.
    const DWORD ex = static_cast<DWORD>(GetWindowLongW(g_frame, GWL_EXSTYLE)) & WS_EX_TOOLWINDOW;
    const UINT dpi = window_dpi(g_frame);
    if (for_dpi && dpi) for_dpi(&r, style, FALSE, ex, dpi);
    else AdjustWindowRectEx(&r, style, FALSE, ex);
    return SIZE{r.right - r.left, r.bottom - r.top};
}

// The game's window in the frame: all of its client area while that has a shape the game lays itself out for, else the
// largest such area in the middle. The game hears of a new size.
void place_game() {
    if (!g_frame || !g_window) return;
    RECT c{};
    GetClientRect(g_frame, &c);
    const int cw = c.right - c.left, ch = c.bottom - c.top;
    // Minimized: the game keeps its size.
    if (cw <= 0 || ch <= 0) return;
    int w = cw, h = ch;
    const double shape = static_cast<double>(cw) / static_cast<double>(ch);
    if (shape > kWidest) w = static_cast<int>(std::lround(ch * kWidest));
    else if (shape < kNarrowest) h = static_cast<int>(std::lround(cw / kNarrowest));
    MoveWindow(g_window, (cw - w) / 2, (ch - h) / 2, w, h, TRUE);
    // The text field stays under the game's window, out of sight whatever the black around it.
    if (g_edit) SetWindowPos(g_edit, HWND_BOTTOM, (cw - w) / 2, (ch - h) / 2, 1, 1, SWP_NOACTIVATE);
    // What the game draws at: the area, or its share by the render scale, of the same shape; the surface is made at
    // that size and stretched over the area (egl_bridge.cpp).
    const int scale = settings().render_scale;
    const DrawSize drawn = draw_size(w, h, scale);
    const int dw = drawn.w, dh = drawn.h;
    g_area_w = w;
    g_area_h = h;
    arm32::g_window_fixed_size.store(scale < 100 ? (static_cast<std::int64_t>(dw) << 32) | dh : 0);
    // The size the game draws at, always: a redirected frame's size with no call into EGL at each swap (offscreen.h).
    arm32::g_offscreen_size.store((static_cast<std::int64_t>(dw) << 32) | dh);
    const bool changed = dw != app().width || dh != app().height;
    app().width = dw;
    app().height = dh;
    if (changed && g_started) surface_changed();
}

// The refresh rate of a display: exact from the display configuration (240084/1000 Hz), else GDI's whole hertz; 0 when
// neither says.
double monitor_rate(HMONITOR m, MONITORINFOEXW& mi) {
    mi.cbSize = sizeof mi;
    if (!GetMonitorInfoW(m, &mi)) return 0;
    UINT32 np = 0, nm = 0;
    if (GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, &np, &nm) == ERROR_SUCCESS) {
        std::vector<DISPLAYCONFIG_PATH_INFO> paths(np);
        std::vector<DISPLAYCONFIG_MODE_INFO> modes(nm);
        if (QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, &np, paths.data(), &nm, modes.data(), nullptr) == ERROR_SUCCESS) {
            for (UINT32 i = 0; i < np; ++i) {
                // The path whose source is this monitor's GDI device (\\.\DISPLAY1).
                DISPLAYCONFIG_SOURCE_DEVICE_NAME source{};
                source.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME;
                source.header.size = sizeof source;
                source.header.adapterId = paths[i].sourceInfo.adapterId;
                source.header.id = paths[i].sourceInfo.id;
                if (DisplayConfigGetDeviceInfo(&source.header) != ERROR_SUCCESS) continue;
                if (std::wcscmp(source.viewGdiDeviceName, mi.szDevice) != 0) continue;
                const DISPLAYCONFIG_RATIONAL& r = paths[i].targetInfo.refreshRate;
                if (r.Numerator && r.Denominator) return static_cast<double>(r.Numerator) / static_cast<double>(r.Denominator);
            }
        }
    }
    DEVMODEW dm{};
    dm.dmSize = sizeof dm;
    if (EnumDisplaySettingsW(mi.szDevice, ENUM_CURRENT_SETTINGS, &dm) && dm.dmDisplayFrequency > 1) return dm.dmDisplayFrequency;
    return 0;
}

// The display the frame is on, read again when that is another one or `changed` (a display's mode changed): its rate
// for the runtime (or the one --refresh named, for a display that gives none, as a test's), and the display for the
// refresh thread.
void watch_display(bool changed) {
    if (!g_frame) return;
    HMONITOR m = MonitorFromWindow(g_frame, MONITOR_DEFAULTTONEAREST);
    if (m == g_monitor.load() && !changed) return;
    MONITORINFOEXW mi{};
    const double hz = monitor_rate(m, mi);
    // A rate below 20 Hz, or none, is no display's to pace by: frames then go as they would without one.
    const double rate = app().refresh_set ? static_cast<double>(app().refresh) : hz;
    arm32::g_display_interval.store(rate >= 20 ? std::llround(1e9 / rate) : 0);
    if (changed) g_displays_changed.store(true);
    const bool moved = g_monitor.load() && m != g_monitor.load();
    g_monitor.store(m);
    // In full screen on another display (Win+Shift+arrow): over the whole of that one.
    if (moved && g_fullscreen) {
        SetWindowPos(g_frame, nullptr, mi.rcMonitor.left, mi.rcMonitor.top, mi.rcMonitor.right - mi.rcMonitor.left, mi.rcMonitor.bottom - mi.rcMonitor.top,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    }
    jvm::log("player: the window is on %s, %ldx%ld at %.3f Hz%s", narrow(mi.szDevice).c_str(), mi.rcMonitor.right - mi.rcMonitor.left,
             mi.rcMonitor.bottom - mi.rcMonitor.top, hz, app().refresh_set ? " (the rate given is used)" : "");
}

// DXGI's output that shows a display, or null (a remote session's, or one gone).
IDXGIOutput* output_for(IDXGIFactory1* factory, HMONITOR m) {
    IDXGIAdapter1* adapter = nullptr;
    for (UINT i = 0; SUCCEEDED(factory->EnumAdapters1(i, &adapter)); ++i) {
        IDXGIOutput* out = nullptr;
        for (UINT j = 0; SUCCEEDED(adapter->EnumOutputs(j, &out)); ++j) {
            DXGI_OUTPUT_DESC d{};
            if (SUCCEEDED(out->GetDesc(&d)) && d.Monitor == m) {
                adapter->Release();
                return out;
            }
            out->Release();
        }
        adapter->Release();
    }
    return nullptr;
}

// The display's refreshes, as the runtime paces by them (pacing.h's g_display_vblank): DXGI wakes this thread at each
// one. A wake comes a little after its refresh and by a varying amount, so the time kept follows the wakes slowly (an
// eighth of each one's difference from where the last refreshes put it), and the refreshes in between are whole
// intervals. A wake far off that grid is not followed alone: three such in a row (the display changed its timing) start
// the grid over from the last of them. A wait that comes back at once (a display asleep, a remote session) is no refresh
// and leaves the time as it was; failures in a row look for the output again. The intervals the wakes keep are measured
// too: a display whose rate the system gave in whole hertz only (59 for 59.94) gets its measured interval instead.
void refresh_loop() {
    name_thread("refreshes");
    // Woken on time: the thread waits for a refresh and does almost nothing else.
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_HIGHEST);
    IDXGIFactory1* factory = nullptr;
    IDXGIOutput* output = nullptr;
    HMONITOR current = nullptr;
    std::int64_t phase = 0, last = 0, measured_from = 0, measured_wakes = 0;
    int off_grid = 0, failures = 0;
    for (;;) {
        HMONITOR want = g_monitor.load();
        if (want != current || g_displays_changed.exchange(false) || failures >= 20) {
            if (output) output->Release();
            output = nullptr;
            // Adapters and outputs as they are now: a display added or taken away needs a new factory.
            if (factory) factory->Release();
            factory = nullptr;
            if (FAILED(CreateDXGIFactory1(__uuidof(IDXGIFactory1), reinterpret_cast<void**>(&factory)))) factory = nullptr;
            if (factory && want) output = output_for(factory, want);
            if (want != current || failures < 20) {
                jvm::log("player: the display's refreshes %s", output ? "are followed" : "cannot be followed: frames go by its rate");
            }
            current = want;
            phase = last = measured_from = measured_wakes = 0;
            off_grid = failures = 0;
            arm32::g_display_vblank.store(0);
        }
        const std::int64_t interval = arm32::g_display_interval.load();
        if (!output || interval <= 0 || FAILED(output->WaitForVBlank())) {
            ++failures;
            Sleep(50);
            continue;
        }
        const std::int64_t t = now_ns();
        // Back at once, with no refresh in between (a display asleep): not one.
        if (last && t - last < interval / 2) {
            ++failures;
            Sleep(1);
            continue;
        }
        failures = 0;
        last = t;
        if (phase) {
            // Where the refreshes so far put this one, and the wake's difference from it.
            const std::int64_t k = (t - phase + interval / 2) / interval;
            const std::int64_t predicted = phase + k * interval;
            const std::int64_t off = t - predicted;
            if (std::llabs(off) < interval / 4) {
                phase = predicted + off / 8;
                off_grid = 0;
            } else if (++off_grid >= 3) {
                phase = t;
                off_grid = 0;
                measured_from = measured_wakes = 0;
            }
        } else {
            phase = t;
        }
        arm32::g_display_vblank.store(phase);
        // The interval the wakes keep, over some seconds: one off the rate the system gave by more than a few in a
        // thousand is the display's real one.
        if (!measured_from) {
            measured_from = phase;
            measured_wakes = 0;
        } else if (++measured_wakes >= 4 * 240) {
            const std::int64_t refreshes = (phase - measured_from + interval / 2) / interval;
            if (refreshes > 0) {
                const std::int64_t real = (phase - measured_from) / refreshes;
                if (std::llabs(real - interval) * 1000 > interval * 3 && arm32::g_display_interval.load() == interval) {
                    arm32::g_display_interval.store(real);
                    jvm::log("player: the display refreshes every %.4f ms, not the %.4f ms its rate says: %.3f Hz from now on",
                             static_cast<double>(real) / 1e6, static_cast<double>(interval) / 1e6, 1e9 / static_cast<double>(real));
                }
            }
            measured_from = phase;
            measured_wakes = 0;
        }
    }
}

// The frame's style in a window: a title bar to move it by and a frame to size it by, and no buttons on the title bar:
// without a system menu Windows draws neither minimise, maximise nor close, so that the game is minimised, put in full
// screen and quit from its own bar over the game. The minimise box stays, which Windows draws nothing for without the
// system menu: with it the taskbar minimises the window and brings it back with a click on its button, as any window's.
constexpr DWORD kWindowStyle = WS_OVERLAPPED | WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX;

// The window's title bar and border dark, as the launcher's header (client/opendmtq_client/theme.py: SIDEBAR #11151A,
// its words TEXT #EEF2F6), so that no white bar sits over the dark game: Windows' dark title bar (attribute 20, or 19
// before Windows 10 20H1), and on Windows 11 the header's own colours for the bar (35), its words (36) and the border
// (34). Best effort: an older Windows says no and keeps its own. dwmapi is looked up in System32 rather than linked, so
// the player starts wherever it did. Said in the log: whether the bar went dark, and whether it took the colours.
void dark_title_bar(HWND h) {
    using SetAttribute = HRESULT(WINAPI*)(HWND, DWORD, LPCVOID, DWORD);
    static const SetAttribute set = [] {
        HMODULE dwm = LoadLibraryExW(L"dwmapi.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
        return dwm ? reinterpret_cast<SetAttribute>(GetProcAddress(dwm, "DwmSetWindowAttribute")) : nullptr;
    }();
    if (!set) return;
    const BOOL dark = TRUE;
    const bool dark_ok = SUCCEEDED(set(h, 20, &dark, sizeof dark)) || SUCCEEDED(set(h, 19, &dark, sizeof dark));
    const COLORREF bar = RGB(0x11, 0x15, 0x1A), words = RGB(0xEE, 0xF2, 0xF6);
    const bool colours_ok = SUCCEEDED(set(h, 35, &bar, sizeof bar));
    set(h, 36, &words, sizeof words);
    set(h, 34, &bar, sizeof bar);
    static bool said = false;
    if (!said) {
        said = true;
        jvm::log("player: the title bar %s, %s", dark_ok ? "dark" : "as Windows has it", colours_ok ? "in the launcher's colours" : "in Windows' own colours");
    }
}

// The frame over the whole display it is on, without its border, and back.
void toggle_fullscreen(HWND h) {
    // A test's unlisted window (window_unlisted) stays a window: full screen covers the display nearest to it, which a
    // window kept off every monitor would put on the person's own. Said in the log, which the test reads.
    if (!g_fullscreen && window_unlisted()) {
        jvm::log("player: no full screen for a test's unlisted window: it would cover a monitor");
        return;
    }
    DWORD style = static_cast<DWORD>(GetWindowLongW(h, GWL_STYLE));
    if (!g_fullscreen) {
        MONITORINFO mi{};
        mi.cbSize = sizeof mi;
        g_placement.length = sizeof g_placement;
        if (GetWindowPlacement(h, &g_placement) && GetMonitorInfoW(MonitorFromWindow(h, MONITOR_DEFAULTTONEAREST), &mi)) {
            // Full screen from the start (the PC's settings), before the frame first shows: back to a window, it shows.
            if (!IsWindowVisible(h)) g_placement.showCmd = SW_SHOWNORMAL;
            SetWindowLongW(h, GWL_STYLE, static_cast<LONG>(style & ~WS_OVERLAPPEDWINDOW));
            SetWindowPos(h, HWND_TOP, mi.rcMonitor.left, mi.rcMonitor.top, mi.rcMonitor.right - mi.rcMonitor.left, mi.rcMonitor.bottom - mi.rcMonitor.top,
                         SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
            g_fullscreen = true;
        }
    } else {
        SetWindowLongW(h, GWL_STYLE, static_cast<LONG>(style | kWindowStyle));
        dark_title_bar(h);
        SetWindowPlacement(h, &g_placement);
        SetWindowPos(h, nullptr, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
        g_fullscreen = false;
    }
    // Said in the log, which a check reads (the end-to-end test clicks the bar's chip).
    jvm::log("player: %s", g_fullscreen ? "full screen" : "in a window");
    // What is drawn over the game, again with the new state: the bar's chip shows the other way now, and the bar comes
    // down for a moment to say where it went.
    overlay::place();
    overlay::switched();
}

// A first size that fits the display the frame is on: three quarters of the height its taskbar leaves, at 16:9, and no
// wider than nine tenths of it, the pixels being the display's own. Where Windows put the frame stays, moved in as far
// as it would run off that area.
void fit_display() {
    MONITORINFO mi{};
    mi.cbSize = sizeof mi;
    if (!GetMonitorInfoW(MonitorFromWindow(g_frame, MONITOR_DEFAULTTONEAREST), &mi)) return;
    const RECT work = mi.rcWork;
    const int ww = work.right - work.left, wh = work.bottom - work.top;
    int h = wh * 3 / 4, w = h * 16 / 9;
    if (w > ww * 9 / 10) {
        w = ww * 9 / 10;
        h = w * 9 / 16;
    }
    const SIZE outer = frame_size(w, h);
    RECT at{};
    GetWindowRect(g_frame, &at);
    LONG x = std::max(work.left, std::min(at.left, work.right - outer.cx));
    LONG y = std::max(work.top, std::min(at.top, work.bottom - outer.cy));
    SetWindowPos(g_frame, nullptr, x, y, outer.cx, outer.cy, SWP_NOZORDER | SWP_NOACTIVATE);
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

// The phone's key for a computer's key (0: the phone has none for it), and the character it types (0: none).
int phone_key(WPARAM vk, int& unicode) {
    unicode = 0;
    if (vk >= 'A' && vk <= 'Z') {
        unicode = static_cast<int>('a' + (vk - 'A'));
        return kKeycodeA + static_cast<int>(vk - 'A');
    }
    if (vk >= '0' && vk <= '9') {
        unicode = static_cast<int>(vk);
        return kKeycode0 + static_cast<int>(vk - '0');
    }
    switch (vk) {
    case VK_ESCAPE: return kKeycodeBack;
    case VK_RETURN: unicode = '\n'; return kKeycodeEnter;
    case VK_SPACE: unicode = ' '; return kKeycodeSpace;
    case VK_BACK: return kKeycodeDel;
    case VK_TAB: unicode = '\t'; return kKeycodeTab;
    case VK_UP: return kKeycodeDpadUp;
    case VK_DOWN: return kKeycodeDpadDown;
    case VK_LEFT: return kKeycodeDpadLeft;
    case VK_RIGHT: return kKeycodeDpadRight;
    case VK_PRIOR: return kKeycodePageUp;
    case VK_NEXT: return kKeycodePageDown;
    case VK_HOME: return kKeycodeHome;
    case VK_END: return kKeycodeEnd;
    case VK_DELETE: return kKeycodeForwardDel;
    default: return 0;
    }
}

// Every key still held, lifted: the window lost the keyboard, and would not see them go up.
void lift_keys() {
    for (auto& [vk, repeat] : g_keys_down) {
        int unicode = 0;
        if (int code = phone_key(vk, unicode)) key(code, false, 0, unicode);
    }
    g_keys_down.clear();
}

// The wheel at screen point p turned by `delta` (WHEEL_DELTA a notch), sideways or not: the game's finger drag, when the
// point is on the game and no mouse button holds a finger down already.
void wheel_at(POINT p, int delta, bool sideways) {
    // While the question is up the game holds still: nothing of the wheel's piles up for it.
    if (g_pressed || !g_window || overlay::asking()) return;
    ScreenToClient(g_window, &p);
    if (p.x < 0 || p.y < 0 || p.x >= g_area_w || p.y >= g_area_h) return;
    float notches = static_cast<float>(delta) / WHEEL_DELTA;
    // Shift with the wheel turns it sideways, as in most programs: a turn down goes to the right.
    if (!sideways && (GetKeyState(VK_SHIFT) & 0x8000)) {
        sideways = true;
        notches = -notches;
    }
    wheel(game_x(p.x), game_y(p.y), sideways ? notches : 0.0f, sideways ? 0.0f : notches);
}

// A touch screen is the game's, as a phone's is: no circle under each finger, no square for a press and hold, no right
// click for it, no flicks. Windows 8 has the call for its touch feedback; the tablet service's property covers what still
// goes through it.
void quiet_touch(HWND h) {
    using SetFeedback = BOOL(WINAPI*)(HWND, FEEDBACK_TYPE, DWORD, UINT32, const VOID*);
    static auto set = reinterpret_cast<SetFeedback>(GetProcAddress(GetModuleHandleW(L"user32.dll"), "SetWindowFeedbackSetting"));
    if (set) {
        const BOOL off = FALSE;
        for (FEEDBACK_TYPE t : {FEEDBACK_TOUCH_CONTACTVISUALIZATION, FEEDBACK_TOUCH_TAP, FEEDBACK_TOUCH_DOUBLETAP, FEEDBACK_TOUCH_PRESSANDHOLD,
                                FEEDBACK_TOUCH_RIGHTTAP, FEEDBACK_GESTURE_PRESSANDTAP, FEEDBACK_PEN_BARRELVISUALIZATION, FEEDBACK_PEN_TAP,
                                FEEDBACK_PEN_DOUBLETAP, FEEDBACK_PEN_PRESSANDHOLD, FEEDBACK_PEN_RIGHTTAP}) {
            set(h, t, 0, sizeof off, &off);
        }
    }
    // tpcshrd.h's flags: press and hold, pen tap and barrel feedback, flicks and their keys, smooth scrolling.
    constexpr ULONG_PTR kNoPressAndHold = 0x1, kNoPenTap = 0x8, kNoPenBarrel = 0x10, kNoFlicks = 0x10000, kNoSmoothScroll = 0x80000,
                        kNoFlickKeys = 0x100000;
    const ATOM atom = GlobalAddAtomW(L"MicrosoftTabletPenServiceProperty");
    SetPropW(h, L"MicrosoftTabletPenServiceProperty",
             reinterpret_cast<HANDLE>(kNoPressAndHold | kNoPenTap | kNoPenBarrel | kNoFlicks | kNoSmoothScroll | kNoFlickKeys));
    GlobalDeleteAtom(atom);
}

// In full screen, a finger that comes in from the screen's edge stays the game's: Windows keeps its edge swipes (the
// notifications, the task view) for windows that do not cover the screen.
void keep_edges(HWND h) {
    // PKEY_EdgeGesture_DisableTouchWhenFullscreen, as propkey.h names it.
    static const PROPERTYKEY key{{0x32CE38B2, 0x2C9A, 0x41B1, {0x9B, 0xC5, 0xB3, 0x78, 0x43, 0x94, 0xAA, 0x44}}, 2};
    IPropertyStore* store = nullptr;
    if (FAILED(SHGetPropertyStoreForWindow(h, IID_PPV_ARGS(&store))) || !store) return;
    PROPVARIANT on{};
    on.vt = VT_BOOL;
    on.boolVal = VARIANT_TRUE;
    store->SetValue(key, on);
    store->Release();
}

// When a touch screen saw a pointer's contact, on the monotonic clock (the performance counter, as the Windows layer's
// clock counts); now when Windows does not say.
std::int64_t contact_time(UINT32 id) {
    POINTER_INFO info{};
    if (!GetPointerInfo(id, &info) || !info.PerformanceCount) return now_ns();
    static const std::int64_t frequency = [] {
        LARGE_INTEGER f;
        QueryPerformanceFrequency(&f);
        return static_cast<std::int64_t>(f.QuadPart);
    }();
    const std::int64_t c = static_cast<std::int64_t>(info.PerformanceCount);
    return c / frequency * 1000000000LL + c % frequency * 1000000000LL / frequency;
}

// Windows' touch keyboard, shown and hidden for the text field through the input pane of the window (Windows 10's
// Windows.UI.ViewManagement.InputPane, by its interop for desktop windows): a field focused by the program, and not by a
// tap on it, does not bring the keyboard up by itself. The interfaces as the Windows SDK declares them.
struct IInputPaneInterop : IInspectable {
    virtual HRESULT STDMETHODCALLTYPE GetForWindow(HWND window, REFIID riid, void** pane) = 0;
};
struct IInputPane2 : IInspectable {
    virtual HRESULT STDMETHODCALLTYPE TryShow(boolean* shown) = 0;
    virtual HRESULT STDMETHODCALLTYPE TryHide(boolean* hidden) = 0;
};

void touch_keyboard(bool show) {
    using CreateString = HRESULT(WINAPI*)(PCWSTR, UINT32, HSTRING*);
    using DeleteString = HRESULT(WINAPI*)(HSTRING);
    using GetFactory = HRESULT(WINAPI*)(HSTRING, REFIID, void**);
    static HMODULE combase = LoadLibraryW(L"combase.dll");
    static auto create = reinterpret_cast<CreateString>(combase ? GetProcAddress(combase, "WindowsCreateString") : nullptr);
    static auto remove = reinterpret_cast<DeleteString>(combase ? GetProcAddress(combase, "WindowsDeleteString") : nullptr);
    static auto factory = reinterpret_cast<GetFactory>(combase ? GetProcAddress(combase, "RoGetActivationFactory") : nullptr);
    if (!create || !remove || !factory) return;
    static const IID kInterop{0x75CF2C57, 0x9195, 0x4931, {0x83, 0x32, 0xF0, 0xB4, 0x09, 0xE9, 0x16, 0xAF}};
    static const IID kPane2{0x8A6B3F26, 0x7090, 0x4793, {0x94, 0x4C, 0xC3, 0xF2, 0xCD, 0xE2, 0x62, 0x76}};
    static const wchar_t kClass[] = L"Windows.UI.ViewManagement.InputPane";
    HSTRING name = nullptr;
    if (FAILED(create(kClass, static_cast<UINT32>(std::wcslen(kClass)), &name))) return;
    IInputPaneInterop* interop = nullptr;
    IInputPane2* pane = nullptr;
    boolean done = 0;
    if (SUCCEEDED(factory(name, kInterop, reinterpret_cast<void**>(&interop))) && interop &&
        SUCCEEDED(interop->GetForWindow(g_frame, kPane2, reinterpret_cast<void**>(&pane))) && pane) {
        if (show) pane->TryShow(&done);
        else pane->TryHide(&done);
        jvm::log("player: the touch keyboard %s", show ? (done ? "is up" : "did not come up") : "is down");
    }
    if (pane) pane->Release();
    if (interop) interop->Release();
    remove(name);
}

// An input method's string for the text field: what it composes (GCS_COMPSTR) or what it has done (GCS_RESULTSTR).
std::string ime_string(HWND h, DWORD which) {
    std::string out;
    HIMC imc = ImmGetContext(h);
    if (!imc) return out;
    const LONG bytes = ImmGetCompositionStringW(imc, which, nullptr, 0);
    if (bytes > 0) {
        std::wstring w(static_cast<std::size_t>(bytes) / sizeof(wchar_t), L'\0');
        ImmGetCompositionStringW(imc, which, w.data(), static_cast<DWORD>(bytes));
        out = narrow(w.c_str());
    }
    ImmReleaseContext(h, imc);
    return out;
}

// The text field's input method stops composing and drops what it had: the game has it already (type_composing).
void ime_cancel(HWND h) {
    if (HIMC imc = ImmGetContext(h)) {
        ImmNotifyIME(imc, NI_COMPOSITIONSTR, CPS_CANCEL, 0);
        ImmReleaseContext(h, imc);
    }
}

// Checks press keys at seconds of their choosing (PLAYER_KEYS="@seconds:key[/hold_ms];...", the seconds from the window's
// first showing): esc, enter, space, up, down, f11, alt+enter, alt+f4, each posted to the frame as Windows would send it,
// down, then up after hold_ms (50 when not given); f11, alt+enter and alt+f4 are there for a check to show that they do
// nothing. close, the window's own close (its X). bar, the overlay's bar as a finger drawn down from the game's top edge
// brings it (no key of a player's does), for a check of its way down and up. Three more act as the mouse
// and the keyboard do: click=x,y presses and lifts the mouse's first button at x,y of the game's pixels on the game's
// area; text=... types into whichever window has the keyboard then (the text field while the game asks for text), a
// key at a time, \uXXXX for a character cmd's own set would not carry and \b for Backspace; ime=... the same, each
// character composed and finished by the input method of the text field. Nothing goes through Windows' own input, and
// the keys reach the window while the game is held still (the planned taps follow the game's frames, which stop then).
void plan_keys() {
    const char* list = std::getenv("PLAYER_KEYS");
    if (!list || !*list) return;
    // What a press is: a key, a click, text, the window's close, or the overlay's bar as a finger brings it.
    enum class Kind { key, click, text, ime, close, bar };
    struct Press {
        double at;
        Kind kind;
        UINT vk;
        bool alt;
        int hold;
        std::string name;
        float x, y;
        std::wstring text;
    };
    std::vector<Press> presses;
    for (const char* p = list; *p == '@';) {
        char* end = nullptr;
        const double at = std::strtod(p + 1, &end);
        if (*end != ':') break;
        const char* name = end + 1;
        const char* stop = name;
        // Text runs to the next item: a '/' in it is the text's, not a hold.
        const bool is_text = std::strncmp(name, "text=", 5) == 0 || std::strncmp(name, "ime=", 4) == 0;
        // ime= is text the input method composes: the same reading after its shorter name.
        const bool is_ime = std::strncmp(name, "ime=", 4) == 0;
        while (*stop && *stop != ';' && (is_text || *stop != '/')) ++stop;
        const std::string key(name, static_cast<std::size_t>(stop - name));
        int hold = 50;
        if (*stop == '/') hold = static_cast<int>(std::strtol(stop + 1, const_cast<char**>(&stop), 10));
        // Each name's key and whether Alt is held with it. F11, Alt+Enter and Alt+F4 do nothing in the window: they stay
        // here so that a check can press them and see that nothing happens.
        static const std::map<std::string, std::pair<UINT, bool>> names = {
            {"esc", {VK_ESCAPE, false}}, {"enter", {VK_RETURN, false}}, {"space", {VK_SPACE, false}}, {"up", {VK_UP, false}},
            {"down", {VK_DOWN, false}}, {"f11", {VK_F11, false}}, {"alt+enter", {VK_RETURN, true}}, {"alt+f4", {VK_F4, true}}};
        if (auto it = names.find(key); it != names.end()) {
            presses.push_back({at, Kind::key, it->second.first, it->second.second, hold, key, 0, 0, {}});
        } else if (key == "close") {
            // The window's own close, as its X or the taskbar's Close sends it.
            presses.push_back({at, Kind::close, 0, false, hold, key, 0, 0, {}});
        } else if (key == "bar") {
            // The overlay's bar, as a finger drawn down from the game's top edge brings it: down for its 4 s, then up.
            presses.push_back({at, Kind::bar, 0, false, hold, key, 0, 0, {}});
        } else if (key.rfind("click=", 0) == 0) {
            // x,y in the game's pixels, as PLAYER_TAPS takes them.
            float x = 0, y = 0;
            if (std::sscanf(key.c_str() + 6, "%f,%f", &x, &y) == 2) presses.push_back({at, Kind::click, 0, false, hold, key, x, y, {}});
            else jvm::log("player: PLAYER_KEYS: no click in \"%s\"", key.c_str());
        } else if (is_text) {
            // UTF-8 as given, with \uXXXX read as the character it names.
            std::string utf8;
            for (std::size_t i = is_ime ? 4 : 5; i < key.size(); ++i) {
                if (key[i] == '\\' && i + 5 < key.size() && key[i + 1] == 'u') {
                    const unsigned code = static_cast<unsigned>(std::strtoul(key.substr(i + 2, 4).c_str(), nullptr, 16));
                    wchar_t one[2] = {static_cast<wchar_t>(code), 0};
                    char bytes[8] = {};
                    const int n = WideCharToMultiByte(CP_UTF8, 0, one, 1, bytes, sizeof bytes, nullptr, nullptr);
                    utf8.append(bytes, static_cast<std::size_t>(n > 0 ? n : 0));
                    i += 5;
                } else if (key[i] == '\\' && i + 1 < key.size() && key[i + 1] == 'b') {
                    // \b: the Backspace key, as when a field's text is taken back.
                    utf8 += '\b';
                    ++i;
                } else {
                    utf8 += key[i];
                }
            }
            const int n = MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), -1, nullptr, 0);
            std::wstring wide(static_cast<std::size_t>(n > 0 ? n - 1 : 0), L'\0');
            if (n > 1) MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), -1, wide.data(), n);
            presses.push_back({at, is_ime ? Kind::ime : Kind::text, 0, false, hold, (is_ime ? "composed \"" : "text \"") + utf8 + "\"", 0, 0, wide});
        } else {
            // A name it does not know: said, and the rest still read.
            jvm::log("player: PLAYER_KEYS: no key \"%s\"", key.c_str());
        }
        p = *stop == ';' ? stop + 1 : stop;
    }
    std::sort(presses.begin(), presses.end(), [](const Press& a, const Press& b) { return a.at < b.at; });
    std::thread([presses] {
        const auto start = std::chrono::steady_clock::now();
        for (const Press& k : presses) {
            std::this_thread::sleep_until(start + std::chrono::milliseconds(static_cast<long long>(k.at * 1000)));
            if (k.kind == Kind::click) {
                // The game's pixels on the area's own, as the mouse would give them there.
                const int cx = g_area_w > 0 ? static_cast<int>(k.x * static_cast<float>(g_area_w) / static_cast<float>(app().width)) : static_cast<int>(k.x);
                const int cy = g_area_h > 0 ? static_cast<int>(k.y * static_cast<float>(g_area_h) / static_cast<float>(app().height)) : static_cast<int>(k.y);
                jvm::log("player: %.1f s: a click at %.0f,%.0f (%d,%d on the window)", k.at, k.x, k.y, cx, cy);
                PostMessageW(g_window, WM_LBUTTONDOWN, MK_LBUTTON, MAKELPARAM(cx, cy));
                std::this_thread::sleep_for(std::chrono::milliseconds(k.hold));
                PostMessageW(g_window, WM_LBUTTONUP, 0, MAKELPARAM(cx, cy));
                continue;
            }
            if (k.kind == Kind::close) {
                jvm::log("player: %.1f s: the window's close", k.at);
                PostMessageW(g_frame, WM_CLOSE, 0, 0);
                continue;
            }
            if (k.kind == Kind::bar) {
                // On the UI thread, which owns the overlay's windows.
                jvm::log("player: %.1f s: the bar, as a finger from the top edge", k.at);
                main_looper().post([] { overlay::show_bar(); });
                continue;
            }
            if (k.kind == Kind::ime) {
                // Each character composed by the input method, then finished, as a syllable typed in Hangul mode is.
                jvm::log("player: %.1f s: %s by the input method", k.at, k.name.c_str());
                for (const wchar_t c : k.text) {
                    PostMessageW(g_edit, kImeMessage, c, 1);
                    std::this_thread::sleep_for(std::chrono::milliseconds(300));
                    PostMessageW(g_edit, kImeMessage, c, 2);
                    std::this_thread::sleep_for(std::chrono::milliseconds(100));
                }
                continue;
            }
            if (k.kind == Kind::text) {
                // The window with the keyboard on the game's thread: the text field while the game asks for text.
                GUITHREADINFO gui{};
                gui.cbSize = sizeof gui;
                const HWND to = GetGUIThreadInfo(GetWindowThreadProcessId(g_frame, nullptr), &gui) && gui.hwndFocus ? gui.hwndFocus : g_frame;
                jvm::log("player: %.1f s: %s into the %s", k.at, k.name.c_str(), to == g_edit ? "text field" : "window");
                for (const wchar_t c : k.text) {
                    const SHORT scan = VkKeyScanW(c);
                    if (scan != -1 && HIBYTE(scan) == 0) {
                        // A key of its own, as typed: its character made by TranslateMessage in the window's loop.
                        const UINT vk = LOBYTE(scan);
                        const LPARAM down = 1 | (static_cast<LPARAM>(MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)) << 16);
                        PostMessageW(to, WM_KEYDOWN, vk, down);
                        std::this_thread::sleep_for(std::chrono::milliseconds(30));
                        PostMessageW(to, WM_KEYUP, vk, down | (1L << 30) | static_cast<LPARAM>(1UL << 31));
                    } else {
                        // Shifted, or no key on this layout (Hangul without its input method): the character itself.
                        PostMessageW(to, WM_CHAR, c, 1);
                    }
                    std::this_thread::sleep_for(std::chrono::milliseconds(60));
                }
                continue;
            }
            // The scan code in bits 16-23, Alt held in bit 29; coming up, bits 30 and 31 too, as Windows sets them.
            const LPARAM down = 1 | (static_cast<LPARAM>(MapVirtualKeyW(k.vk, MAPVK_VK_TO_VSC)) << 16) | (k.alt ? (1L << 29) : 0);
            const LPARAM up = down | (1L << 30) | static_cast<LPARAM>(1UL << 31);
            jvm::log("player: %.1f s: the key %s, held %d ms", k.at, k.name.c_str(), k.hold);
            // When it went: the window says how long it waited for the UI thread (frame_proc).
            g_key_posted.store(steady_ns(), std::memory_order_release);
            PostMessageW(g_frame, k.alt ? WM_SYSKEYDOWN : WM_KEYDOWN, k.vk, down);
            std::this_thread::sleep_for(std::chrono::milliseconds(k.hold));
            PostMessageW(g_frame, k.alt ? WM_SYSKEYUP : WM_KEYUP, k.vk, up);
        }
    }).detach();
}

// While the question before quitting is up the keys are its own, even with the game asking for text: Left, Right and
// Tab move its choice, Enter takes it, Esc keeps playing, the rest waits. True when the key was the question's.
bool ask_key(WPARAM w, LPARAM l) {
    if (!overlay::asking()) return false;
    // Enter and Esc act once per press, not again while held (a held Enter must not quit after keeping on).
    const bool repeat = (l & (1L << 30)) != 0;
    if (repeat && (w == VK_RETURN || w == VK_ESCAPE)) return true;
    // Esc answering the question: its coming up is no Back key.
    if (w == VK_ESCAPE) g_esc_held = true;
    return overlay::ask_key(static_cast<UINT>(w));
}

// The edit control's own window procedure, which edit_proc hands on to.
WNDPROC g_edit_default = nullptr;

// Whether a key moves a text field's caret: an arrow, Home or End.
bool moves_caret(WPARAM vk) { return vk == VK_LEFT || vk == VK_RIGHT || vk == VK_UP || vk == VK_DOWN || vk == VK_HOME || vk == VK_END; }

// The text field's keys and characters while the game asks for text: to the game's text as the frame's would go; the
// rest (an input method composing, a touch keyboard's own keys) as an edit control has them.
LRESULT CALLBACK edit_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    // A check's character for the input method: given to the field's input context, which answers with the same
    // WM_IME_COMPOSITION messages as a key typed in Hangul mode.
    if (msg == kImeMessage) {
        HIMC imc = ImmGetContext(h);
        if (!imc) {
            jvm::log("player: no input method on the text field");
            return 0;
        }
        const wchar_t one[2] = {static_cast<wchar_t>(w), 0};
        BOOL done = FALSE;
        if (l == 1) {
            // Open, then the character shown as being composed.
            ImmSetOpenStatus(imc, TRUE);
            done = ImmSetCompositionStringW(imc, SCS_SETSTR, const_cast<wchar_t*>(one), sizeof(wchar_t), nullptr, 0);
        } else {
            // Finished: the input method hands it over as its result.
            done = ImmNotifyIME(imc, NI_COMPOSITIONSTR, CPS_COMPLETE, 0);
        }
        if (!done) jvm::log("player: the input method did not take U+%04X (%s)", static_cast<unsigned>(w), l == 1 ? "compose" : "finish");
        ImmReleaseContext(h, imc);
        return 0;
    }
    switch (msg) {
    case WM_CHAR:
        if (typing() && w >= 0x20 && !overlay::asking()) typed(static_cast<wchar_t>(w));
        return 0;
    case WM_IME_COMPOSITION:
        // An input method's done text goes in as typed; what it still composes shows after it (a Hangul syllable before
        // its last key), as a phone's field shows it. Taken here, the edit control inserts none of it itself.
        if (l & GCS_RESULTSTR) type_text(ime_string(h, GCS_RESULTSTR));
        type_composing((l & GCS_COMPSTR) ? ime_string(h, GCS_COMPSTR) : std::string());
        return 0;
    case WM_IME_ENDCOMPOSITION:
        type_composing("");
        break;
    case WM_KEYDOWN:
        // The question before quitting takes every key first, as over the game.
        if (ask_key(w, l)) return 0;
        // Enter takes what is being composed along (finish adds it).
        if (w == VK_RETURN) type_key(kKeyEnter);
        else if (w == VK_ESCAPE) type_key(kKeyEscape);
        else if (w == VK_BACK) type_key(kKeyBackspace);
        else if (w == VK_DELETE) type_key(kKeyDelete);
        // The rest as an edit control has them (F11 among them: nothing, as over the game); a key that moves the caret
        // first says so, the text the game opened with no longer being selected.
        else {
            if (moves_caret(w)) type_key(kKeyMove);
            break;
        }
        return 0;
    case WM_SYSKEYDOWN:
        // Alt+Enter while the game asks for text: nothing, as over the game (full screen is the bar's button); its
        // character makes no beep (WM_SYSCHAR below).
        if (w == VK_RETURN && (HIWORD(l) & KF_ALTDOWN)) return 0;
        // Alt+F4 while the game asks for text: nothing, as over the game (quitting is the bar's X's, which asks first).
        if (w == VK_F4 && (HIWORD(l) & KF_ALTDOWN)) return 0;
        // F10 alone would put the window in Windows' menu mode, which eats the next key: nothing.
        if (w == VK_F10) return 0;
        break;
    case WM_SYSKEYUP:
        if (w == VK_F10) return 0;
        break;
    case WM_SYSCHAR:
        // Alt+Enter's character: no beep for it.
        if (w == VK_RETURN) return 0;
        break;
    default:
        break;
    }
    return CallWindowProcW(g_edit_default, h, msg, w, l);
}

// Keys and window events for the frame.
LRESULT CALLBACK frame_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    switch (msg) {
    case WM_CLOSE:
        // The taskbar's Close window, or another program asking it to close (the window has no X of its own): asked
        // first in the overlay's question, so that a click by mistake mid-song never ends the game.
        overlay::ask_quit();
        return 0;
    case WM_SYSCOMMAND:
        // Windows' menu mode from the keyboard (Alt pressed and let go alone, F10, Alt+Space): nothing. It would hold the
        // next keys for the window's menu, so that a note's key after a lone Alt did nothing, or opened the menu.
        if ((w & 0xFFF0) == SC_KEYMENU) return 0;
        // A maximise asked for by command (a shortcut's, another program's): nothing, as the window has no maximise
        // button; full screen is the bar's.
        if ((w & 0xFFF0) == SC_MAXIMIZE) return 0;
        break;
    case kQuitMessage:
        // The question's Quit the game.
        g_closed = true;
        return 0;
    case WM_SIZE:
        // Minimised, the game holds still; back, it goes on, to its own pause screen mid-song (overlay_win32.cpp).
        if (w == SIZE_MINIMIZED) {
            // Said in the log, which the end-to-end test reads (the bar's minimise, the taskbar's restore).
            if (!g_minimised) jvm::log("player: minimised");
            g_minimised = true;
            overlay::minimised(true);
            return 0;
        }
        if (g_minimised) jvm::log("player: back from minimised");
        g_minimised = false;
        overlay::minimised(false);
        place_game();
        overlay::place();
        return 0;
    case WM_WINDOWPOSCHANGED:
        // Moved to another display, perhaps: its rate and refreshes from now on; what is drawn over the game follows.
        watch_display(false);
        overlay::place();
        break;
    case WM_DISPLAYCHANGE:
        // A display's mode (size, rate) changed, or a display came or went.
        watch_display(true);
        // In full screen the frame covers the display at its new size.
        if (g_fullscreen) {
            MONITORINFO mi{};
            mi.cbSize = sizeof mi;
            if (GetMonitorInfoW(MonitorFromWindow(h, MONITOR_DEFAULTTONEAREST), &mi)) {
                SetWindowPos(h, nullptr, mi.rcMonitor.left, mi.rcMonitor.top, mi.rcMonitor.right - mi.rcMonitor.left,
                             mi.rcMonitor.bottom - mi.rcMonitor.top, SWP_NOZORDER | SWP_NOACTIVATE);
            }
        }
        return 0;
    case WM_DPICHANGED: {
        // On a display of another scaling: the size Windows proposes keeps the window's size on screen; the game then
        // draws at the pixels that has there.
        if (!g_fullscreen) {
            const RECT* r = reinterpret_cast<const RECT*>(l);
            SetWindowPos(h, nullptr, r->left, r->top, r->right - r->left, r->bottom - r->top, SWP_NOZORDER | SWP_NOACTIVATE);
        }
        return 0;
    }
    case WM_GETMINMAXINFO: {
        // The frame never so small that the game's area falls below its smallest: 480x270 of Windows' own pixels, as
        // many of the display's as its scale makes them (720x405 at 150 %), where the overlay's bar keeps its wordmark
        // and its buttons apart at any scale (overlay_scale.h). Windows' scale of the display it is on now: moved to
        // another, the smallest follows.
        const UINT dpi = window_dpi(h);
        const float scale = dpi ? static_cast<float>(dpi) / 96.0f : 1.0f;
        const SIZE least = frame_size(overlay::at_scale(overlay::kLeastAreaW, scale), overlay::at_scale(overlay::kLeastAreaH, scale));
        auto* mm = reinterpret_cast<MINMAXINFO*>(l);
        mm->ptMinTrackSize.x = least.cx;
        mm->ptMinTrackSize.y = least.cy;
        return 0;
    }
    case WM_ACTIVATE:
        // A check's trace: the frame the active window, or no longer and which window is instead (another program's, or
        // one of the overlay's, which must never be).
        if (trace_input()) {
            if (LOWORD(w) == WA_INACTIVE) jvm::log("player: input: the game's window is no longer active (%s)", window_class(reinterpret_cast<HWND>(l)).c_str());
            else jvm::log("player: input: the game's window is active");
        }
        break;
    case WM_KILLFOCUS:
        // A check's trace: the keyboard gone from the frame, and to which window.
        if (trace_input()) jvm::log("player: input: the game's window lost the keyboard (%s)", window_class(reinterpret_cast<HWND>(w)).c_str());
        lift_keys();
        // An Esc whose coming up goes elsewhere (Ctrl+Shift+Esc, Alt+Tab while held): no Back.
        g_esc_down = false;
        return 0;
    case WM_SETFOCUS:
        // Back in the window while the game asks for text (Alt+Tab, a click): the text field has the keyboard again.
        if (typing() && g_edit) {
            SetFocus(g_edit);
            return 0;
        }
        break;
    case WM_SYSCHAR:
        // Alt+Enter's character: no beep for it.
        if (w == VK_RETURN) return 0;
        break;
    case WM_CHAR:
        // Text while the game asks for it: printable characters only; the keys that end or edit it come as keys.
        if (typing() && w >= 0x20 && !overlay::asking()) typed(static_cast<wchar_t>(w));
        return 0;
    case WM_SYSKEYUP:
        // F10's coming up: no menu mode either.
        if (w == VK_F10) return 0;
        break;
    case WM_SYSKEYDOWN:
        // F10 alone would put the window in Windows' menu mode, which eats the next key (a note): nothing.
        if (w == VK_F10) return 0;
        // Alt+F4: nothing. Windows would close the window with it; quitting is the bar's X's, which asks first.
        if (w == VK_F4 && (HIWORD(l) & KF_ALTDOWN)) return 0;
        // Alt+Enter: nothing either, though many Windows games switch with it: full screen is the bar's button, which
        // nobody presses by mistake mid-song. Its character makes no beep (WM_SYSCHAR above).
        if (w == VK_RETURN && (HIWORD(l) & KF_ALTDOWN)) return 0;
        break;
    case WM_KEYDOWN: {
        // A check's planned key: how long it waited for this thread, which stamps it for the game below.
        if (const long long posted = g_key_posted.exchange(0, std::memory_order_acquire)) {
            jvm::log("player: the key came to the window %.3f ms after it was posted", static_cast<double>(steady_ns() - posted) / 1e6);
        }
        g_last_touch = false;
        // The question before quitting takes every key first: none of them changes the window while it is up. F11
        // goes on to the phone's keys below, which have none for it: nothing.
        if (ask_key(w, l)) return 0;
        if (typing()) {
            if (w == VK_RETURN) type_key(kKeyEnter);
            else if (w == VK_ESCAPE) type_key(kKeyEscape);
            else if (w == VK_BACK) type_key(kKeyBackspace);
            else if (w == VK_DELETE) type_key(kKeyDelete);
            else if (moves_caret(w)) type_key(kKeyMove);
            return 0;
        }
        // Esc: the Back key when it comes up.
        if (w == VK_ESCAPE) {
            // With Ctrl, Shift or Alt it is Windows' (Ctrl+Shift+Esc), not the game's.
            if (GetKeyState(VK_CONTROL) < 0 || GetKeyState(VK_SHIFT) < 0 || GetKeyState(VK_MENU) < 0) return 0;
            if (!(l & (1L << 30))) {
                g_esc_down = true;
                g_esc_held = false;
            }
            return 0;
        }
        int unicode = 0;
        const int code = phone_key(w, unicode);
        if (!code) return 0;
        // A key that came down while the question had the keys (Enter on Keep playing, held): its repeats are no new
        // press for the game.
        if ((l & (1L << 30)) && !g_keys_down.count(w)) return 0;
        // Held, it repeats: Windows says so in bit 30 (it was down before).
        const bool again = (l & (1L << 30)) != 0 && g_keys_down.count(w);
        const int repeat = again ? ++g_keys_down[w] : (g_keys_down[w] = 0);
        key(code, true, repeat, unicode);
        return 0;
    }
    case WM_KEYUP: {
        if (w == VK_ESCAPE && g_esc_down) {
            g_esc_down = false;
            // The phone's Back key, down and up, unless the question took this Esc.
            if (!g_esc_held) {
                int unicode = 0;
                if (int code = phone_key(VK_ESCAPE, unicode)) {
                    key(code, true, 0, unicode);
                    key(code, false, 0, unicode);
                }
            }
            g_esc_held = false;
            return 0;
        }
        auto it = g_keys_down.find(w);
        if (it == g_keys_down.end()) return 0;
        g_keys_down.erase(it);
        int unicode = 0;
        if (int code = phone_key(w, unicode)) key(code, false, 0, unicode);
        return 0;
    }
    case WM_MOUSEWHEEL:
    case WM_MOUSEHWHEEL: {
        // The point is on the screen; the turn sideways for a tilt wheel.
        POINT p{static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l))};
        wheel_at(p, GET_WHEEL_DELTA_WPARAM(w), msg == WM_MOUSEHWHEEL);
        return 0;
    }
    default:
        break;
    }
    return DefWindowProcW(h, msg, w, l);
}

// Fingers, the pen and the mouse on the game's window.
LRESULT CALLBACK game_proc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    switch (msg) {
    case WM_SETCURSOR:
        // Over the game, the game's own arrow (overlay_win32.cpp), lime while the mouse's finger is down.
        if (LOWORD(l) == HTCLIENT) {
            SetCursor(overlay::cursor(g_pressed));
            return TRUE;
        }
        break;
    case WM_LBUTTONDOWN:
        // The mouse's first button is a finger: pressed, moved while pressed, lifted; held even outside the window.
        SetCapture(h);
        g_pressed = true;
        // A press on the game: the overlay's bar waits for the game to be quiet.
        overlay::game_pressed(true);
        SetCursor(overlay::cursor(true));
        g_last_touch = false;
        if (trace_input()) {
            jvm::log("player: input: the mouse's button down on the game at %d,%d (the game's %.0f,%.0f)", static_cast<short>(LOWORD(l)),
                     static_cast<short>(HIWORD(l)), static_cast<double>(game_x(static_cast<short>(LOWORD(l)))), static_cast<double>(game_y(static_cast<short>(HIWORD(l)))));
        }
        touch(0, game_x(static_cast<short>(LOWORD(l))), game_y(static_cast<short>(HIWORD(l))));
        return 0;
    case WM_MOUSEMOVE:
        // The mouse moving over the game: resting at its very top edge or on the overlay's handle, the bar comes down (a
        // touch's moves are pointer messages, and their copies as mouse moves are marked).
        if ((GetMessageExtraInfo() & 0xFFFFFF00) != 0xFF515700) overlay::pointer_moved(static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l)), g_pressed);
        if (g_pressed) touch(2, game_x(static_cast<short>(LOWORD(l))), game_y(static_cast<short>(HIWORD(l))));
        return 0;
    case WM_LBUTTONUP:
        if (g_pressed) {
            g_pressed = false;
            overlay::game_pressed(!g_contacts.empty());
            SetCursor(overlay::cursor(false));
            ReleaseCapture();
            if (trace_input()) jvm::log("player: input: the mouse's button up on the game at %d,%d", static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l)));
            touch(1, game_x(static_cast<short>(LOWORD(l))), game_y(static_cast<short>(HIWORD(l))));
        }
        return 0;
    case WM_CAPTURECHANGED:
        // The mouse taken away while pressed (another window, a system dialog): the finger lifts where it was last.
        if (g_pressed && reinterpret_cast<HWND>(l) != h) {
            g_pressed = false;
            overlay::game_pressed(!g_contacts.empty());
            touch(3, 0, 0);
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
        if (msg == WM_POINTERDOWN) g_last_touch = true;
        // Screen pixels, into the window's, then the game's.
        POINT p{static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l))};
        ScreenToClient(h, &p);
        // A finger that comes down on the top edge waits: drawn down, it shows the bar; lifted, it is a tap. Only when it is
        // alone on the game and the game has had no press for a moment: a finger playing at the top of a song plays.
        const bool edge_alone = g_contacts.empty() && !g_pressed && overlay::game_quiet();
        if (msg == WM_POINTERDOWN) {
            g_contacts.insert(id);
            overlay::game_pressed(true);
        } else if (msg == WM_POINTERUP) {
            g_contacts.erase(id);
            overlay::game_pressed(g_pressed || !g_contacts.empty());
        }
        if (msg == WM_POINTERDOWN && g_edge_finger && id != g_edge_finger) {
            // Another finger while one waits at the edge: that one plays after all, from where and when it came down.
            const UINT32 waiting = g_edge_finger;
            g_edge_finger = 0;
            finger(static_cast<int>(waiting), 0, game_x(g_edge_from.x), game_y(g_edge_from.y), g_edge_time);
        }
        if (msg == WM_POINTERDOWN && !g_edge_finger && edge_alone && p.y < std::max(8, g_area_h / 40)) {
            g_edge_finger = id;
            g_edge_from = p;
            g_edge_time = contact_time(id);
            return 0;
        }
        if (id == g_edge_finger) {
            if (msg == WM_POINTERUPDATE && p.y - g_edge_from.y > g_area_h / 12) {
                g_edge_finger = 0;
                overlay::show_bar();
            } else if (msg == WM_POINTERUP) {
                g_edge_finger = 0;
                finger(static_cast<int>(id), 0, game_x(g_edge_from.x), game_y(g_edge_from.y), g_edge_time);
                finger(static_cast<int>(id), 1, game_x(p.x), game_y(p.y), contact_time(id));
            }
            return 0;
        }
        finger(static_cast<int>(id), msg == WM_POINTERDOWN ? 0 : msg == WM_POINTERUP ? 1 : 2, game_x(p.x), game_y(p.y), contact_time(id));
        return 0;
    }
    case WM_POINTERCAPTURECHANGED:
        // The finger gone from the game either way.
        if (g_contacts.erase(GET_POINTERID_WPARAM(w))) overlay::game_pressed(g_pressed || !g_contacts.empty());
        if (GET_POINTERID_WPARAM(w) == g_edge_finger) {
            g_edge_finger = 0;
            return 0;
        }
        // The system took the fingers away (a gesture of its own): the game's gesture is cancelled.
        finger(static_cast<int>(GET_POINTERID_WPARAM(w)), 3, 0, 0);
        return 0;
    case WM_MOUSEWHEEL:
    case WM_MOUSEHWHEEL: {
        // Sent here when Windows scrolls the window under the pointer.
        POINT p{static_cast<short>(LOWORD(l)), static_cast<short>(HIWORD(l))};
        wheel_at(p, GET_WHEEL_DELTA_WPARAM(w), msg == WM_MOUSEHWHEEL);
        return 0;
    }
    case WM_ERASEBKGND:
        // The game draws every pixel: no flash of the background between frames.
        return 1;
    default:
        break;
    }
    return DefWindowProcW(h, msg, w, l);
}

// A test's window with no animation of its own (window_unlisted), should a check minimise or restore it: DWM's
// transitions off for it (DWMWA_TRANSITIONS_FORCEDISABLED). dwmapi is looked up in System32 rather than linked, as for the
// title bar. Best effort: false where Windows has no such call or turned it down, and the window animates as any other.
bool no_transitions(HWND h) {
    using SetAttribute = HRESULT(WINAPI*)(HWND, DWORD, LPCVOID, DWORD);
    // The call once, from System32's dwmapi.dll.
    static const SetAttribute set = [] {
        HMODULE dwm = LoadLibraryExW(L"dwmapi.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
        return dwm ? reinterpret_cast<SetAttribute>(GetProcAddress(dwm, "DwmSetWindowAttribute")) : nullptr;
    }();
    // Attribute 3 is DWMWA_TRANSITIONS_FORCEDISABLED; TRUE turns the window's minimise, restore, show and hide
    // animations off.
    const BOOL off = TRUE;
    return set && SUCCEEDED(set(h, 3, &off, sizeof off));
}

}  // namespace

bool window_unlisted() {
    // Read once: the player's environment does not change while it runs, and only "1" turns it on.
    static const bool unlisted = [] {
        const char* value = std::getenv("PLAYER_WINDOW_UNLISTED");
        const bool on = value && std::strcmp(value, "1") == 0;
        // Nor any box of Windows' own for a crash or a missing disk, from here on (main asks first thing): a test's
        // crash is in its log and its exit code, and Windows' "stopped working" box would be on the person's desktop.
        if (on) SetErrorMode(GetErrorMode() | SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
        return on;
    }();
    return unlisted;
}

bool open_window(const std::string& title) {
    // The screen's own pixels on every monitor: Windows 10's per-monitor awareness, where it has it.
    if (HMODULE user = GetModuleHandleW(L"user32.dll")) {
        using SetContext = BOOL(WINAPI*)(HANDLE);
        if (auto set = reinterpret_cast<SetContext>(GetProcAddress(user, "SetProcessDpiAwarenessContext"))) set(reinterpret_cast<HANDLE>(-4));
    }
    HINSTANCE instance = GetModuleHandleW(nullptr);
    // The frame: the program's icon, the system's arrow (IDC_ARROW is its number as a narrow-string name, which
    // LoadCursorA takes), black around the game.
    WNDCLASSEXW frame{};
    frame.cbSize = sizeof frame;
    frame.lpfnWndProc = frame_proc;
    frame.hInstance = instance;
    frame.hCursor = LoadCursorA(nullptr, IDC_ARROW);
    frame.hIcon = LoadIconW(instance, MAKEINTRESOURCEW(1));
    frame.hbrBackground = static_cast<HBRUSH>(GetStockObject(BLACK_BRUSH));
    frame.lpszClassName = L"OpenDMTQPlayer";
    RegisterClassExW(&frame);
    // The game's window: a device context of its own for the surface, the arrow, no background of its own.
    WNDCLASSEXW game{};
    game.cbSize = sizeof game;
    game.style = CS_OWNDC;
    game.lpfnWndProc = game_proc;
    game.hInstance = instance;
    game.hCursor = LoadCursorA(nullptr, IDC_ARROW);
    game.lpszClassName = L"OpenDMTQGame";
    RegisterClassExW(&game);
    int n = MultiByteToWideChar(CP_UTF8, 0, title.c_str(), -1, nullptr, 0);
    std::wstring wtitle(static_cast<std::size_t>(n > 0 ? n - 1 : 0), L'\0');
    if (n > 1) MultiByteToWideChar(CP_UTF8, 0, title.c_str(), -1, wtitle.data(), n);
    // A test's unlisted window (window_unlisted) is a tool window: Windows gives one no taskbar button and no place in
    // Alt+Tab or Task View. A player's window has no extended style.
    const DWORD ex = window_unlisted() ? WS_EX_TOOLWINDOW : 0;
    // Made hidden, where Windows places a new window (or where the program that started this one asked), and sized for
    // its display before it shows.
    g_frame = CreateWindowExW(ex, frame.lpszClassName, wtitle.c_str(), kWindowStyle | WS_CLIPCHILDREN, CW_USEDEFAULT, CW_USEDEFAULT,
                              app().width, app().height, nullptr, nullptr, instance, nullptr);
    if (!g_frame) {
        jvm::log("player: cannot make a window (error %lu)", GetLastError());
        return false;
    }
    if (window_unlisted()) {
        // Nor any animation of its own where Windows allows, then said in the log, which a test's run reads to know the
        // switch took.
        const bool still = no_transitions(g_frame);
        jvm::log("player: the window is on no taskbar and in no Alt+Tab, %s (a test's, PLAYER_WINDOW_UNLISTED, extended style %08lx)",
                 still ? "with no animation" : "its animations as Windows has them",
                 static_cast<unsigned long>(GetWindowLongW(g_frame, GWL_EXSTYLE)));
    }
    jvm::log("player: the window has a title bar and a frame, no buttons of its own (style %08lx)",
             static_cast<unsigned long>(GetWindowLongW(g_frame, GWL_STYLE)));
    dark_title_bar(g_frame);
    if (app().fit_screen) {
        fit_display();
    } else {
        // The size asked for is the game's area.
        const SIZE outer = frame_size(app().width, app().height);
        SetWindowPos(g_frame, nullptr, 0, 0, outer.cx, outer.cy, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
    }
    g_window = CreateWindowExW(0, game.lpszClassName, L"", WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS, 0, 0, app().width, app().height, g_frame,
                               nullptr, instance, nullptr);
    if (!g_window) {
        jvm::log("player: cannot make the game's window (error %lu)", GetLastError());
        return false;
    }
    place_game();
    // A touch screen's fingers are the game's alone, up to its edges in full screen.
    quiet_touch(g_frame);
    quiet_touch(g_window);
    // No input method on the game itself: keys in a Hangul mode stay keys (no composition box over a song); the text
    // field keeps its own.
    ImmAssociateContextEx(g_frame, nullptr, 0);
    ImmAssociateContextEx(g_window, nullptr, 0);
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    keep_edges(g_frame);
    // The text field for the game's text input: one pixel under the game's window (place_game), which it never paints
    // over, focused only while the game asks for text.
    g_edit = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS | ES_AUTOHSCROLL, 0, 0, 1, 1, g_frame, nullptr, instance, nullptr);
    if (g_edit) {
        place_game();
        g_edit_default = reinterpret_cast<WNDPROC>(SetWindowLongPtrW(g_edit, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(edit_proc)));
    }
    // What is drawn over the game: the bar at its top edge, the question before quitting, the server's notice, the cursor.
    overlay::Hooks hooks;
    hooks.toggle_fullscreen = [] { toggle_fullscreen(g_frame); };
    hooks.quit = [] { PostMessageW(g_frame, kQuitMessage, 0, 0); };
    hooks.fullscreen = [] { return g_fullscreen; };
    hooks.hold = [](bool held) {
        pause_game(held);
        // The broadcast holds too: what viewers see stops with the game, and starts again with it.
        arm32::desktop_live_paused(held);
    };
    hooks.log = [](const char* line) { jvm::log("%s", line); };
    // The count of frames shown, for the frame counter and the game's first picture.
    hooks.frames = [] {
        // The count, the last frame's time, the count again: a frame shown between the two reads is read again, so that
        // the time is the counted frame's.
        overlay::FrameCount c;
        for (int tries = 0; tries < 4; ++tries) {
            c.count = frames_shown();
            c.ns = frame_shown_ns();
            if (frames_shown() == c.count) break;
        }
        return c;
    };
    // What the overlay's pictures cost, with the player's stats.
    hooks.stats = arm32::g_stats;
    // The display's refresh interval, as the frames are paced by it (watch_display): a motion's steps fall back on it.
    hooks.refresh_ns = [] { return static_cast<long long>(arm32::g_display_interval.load()); };
    overlay::start(g_frame, g_window, hooks, host_locale().first == "ko");
    // The frame counter in the corner the PC's settings name (none: no counter).
    overlay::show_fps(static_cast<int>(settings().show_fps));
    // A check's planned keys (PLAYER_KEYS), from now on.
    plan_keys();
    // This thread waits for window messages and its looper's jobs together: a job posted wakes it.
    g_ui_thread = GetCurrentThreadId();
    main_looper().wake = [] { PostThreadMessageW(g_ui_thread, WM_NULL, 0, 0); };
    // The display it is on, and its refreshes from a thread of their own.
    watch_display(false);
    std::thread(refresh_loop).detach();
    // A test's run on a person's screen (PLAYER_WINDOW_AT=x,y): the window there, shown without taking the focus from
    // what the person is doing. At a place off every monitor and unlisted (window_unlisted), nothing of it is on the
    // person's desktop.
    int show = SW_SHOW;
    if (const char* at = std::getenv("PLAYER_WINDOW_AT")) {
        int x = 0, y = 0;
        if (std::sscanf(at, "%d,%d", &x, &y) == 2) {
            SetWindowPos(g_frame, nullptr, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
            show = SW_SHOWNOACTIVATE;
        }
    }
    // Full screen from the start when the PC's settings say so: over the display it would have opened on.
    if (settings().fullscreen) toggle_fullscreen(g_frame);
    ShowWindow(g_frame, show);
    UpdateWindow(g_frame);
    // The size the game's area has once shown (the frame's scaling may have changed it).
    place_game();
    // The passes over the game's frames the PC's settings ask for (post_pass.h), before the game makes its surface: an
    // upscaler below 100 %, anti-aliasing. Neither asked for, the game's frames reach the window as they always did.
    post_configure(static_cast<int>(settings().upscaler), static_cast<int>(settings().anti_aliasing), settings().render_scale);
    if ((g_area_w != app().width || g_area_h != app().height) && settings().upscaler != Settings::Upscaler::kBilinear) {
        // The upscaler's own line follows at the first frame (post_pass.cpp), with the sizes it scales between.
        jvm::log("player: the game draws at %dx%d for an area of %dx%d (render scale %d%%), upscaled by %s", app().width, app().height, g_area_w,
                 g_area_h, settings().render_scale, settings().upscaler == Settings::Upscaler::kFsr1 ? "AMD FSR 1" : "NVIDIA NIS");
    } else if (g_area_w != app().width || g_area_h != app().height) {
        jvm::log("player: the game draws at %dx%d, stretched to %dx%d (render scale %d%%)", app().width, app().height, g_area_w, g_area_h,
                 settings().render_scale);
    } else {
        jvm::log("player: the game draws at %dx%d", app().width, app().height);
    }
    g_surface = jvm::Ref<jvm::Object>(new Surface(&jvm::define("android/view/Surface"), g_window));
    g_started = true;
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

void wait_for_events(Looper::Clock::time_point until) {
    // Until the next job, at most a tenth of a second (the time limit is looked at then); a window message or a posted
    // job (its wake) ends the wait at once. The time on a high-resolution timer of the thread's: a plain wait rounds
    // to the system's 15.6 ms tick, which a wheel's 8 ms steps would wait for.
    const auto now = Looper::Clock::now();
    const auto cap = now + std::chrono::milliseconds(100);
    const auto end = until <= now ? now : std::min(until, cap);
    const auto left = std::chrono::duration_cast<std::chrono::nanoseconds>(end - now).count();
    static HANDLE timer = CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
    if (left <= 0) {
        MsgWaitForMultipleObjectsEx(0, nullptr, 0, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
        return;
    }
    LARGE_INTEGER due;
    // Relative, in 100 ns units.
    due.QuadPart = -std::max<long long>(1, left / 100);
    if (timer && SetWaitableTimer(timer, &due, 0, nullptr, nullptr, FALSE)) {
        MsgWaitForMultipleObjectsEx(1, &timer, 200, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
    } else {
        MsgWaitForMultipleObjectsEx(0, nullptr, static_cast<DWORD>((left + 999999) / 1000000), QS_ALLINPUT, MWMO_INPUTAVAILABLE);
    }
}

void show_notice(const std::string& text, bool live) {
    jvm::log("player: notice: %s", text.c_str());
    // On the UI thread, which owns the windows: a card over the game (overlay_win32.cpp).
    main_looper().post([text, live] { overlay::notice(text, live); });
}

void soft_keyboard(bool open) {
    // On the UI thread, which owns the windows: the text field focused while the game asks for text, the frame after.
    main_looper().post([open] {
        if (!g_edit || !g_frame) return;
        if (open) {
            SetWindowTextW(g_edit, L"");
            SetFocus(g_edit);
            // Asked by a touch: the touch keyboard comes up for it.
            if (g_last_touch) touch_keyboard(true);
        } else {
            // What an input method was still composing the game has already (type_composing): it goes from the field.
            ime_cancel(g_edit);
            if (GetFocus() == g_edit) SetFocus(g_frame);
            if (g_last_touch) touch_keyboard(false);
        }
    });
}

}  // namespace player
