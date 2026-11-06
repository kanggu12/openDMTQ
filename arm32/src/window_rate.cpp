// The frame rate the game's window asks the display for.
#include "framerate.h"
#include "host.h"
#include "pacing.h"

#include <android/native_window.h>
#include <cstdint>
#include <dlfcn.h>
#include <mutex>

namespace arm32 {

namespace {

// The game's last window, with a reference of our own: asking it again later never reaches a window the
// game has released.
std::mutex g_window_lock;
ANativeWindow* g_game_window = nullptr;

// The display at the game's frame rate gives each frame exactly one refresh. A 60 fps game on a
// 120 Hz panel otherwise gets two refreshes per frame, and three whenever a frame is a little
// late, which shows as judder. Following the display, the window asks for its highest rate (lower after a
// step down) and the frame rate takes whatever the display then runs at (pacing.cpp). Only the
// window the game renders to is asked (its EGL surface's), not other surfaces it may obtain.
// Android 11 and later only; the newer call also switches when the change is not seamless.
void ask_frame_rate(ANativeWindow* win) {
    // A set frame rate of 0 asks for nothing.
    float rate = frame_rate_follows_display() ? followed_window_rate() : app_frame_rate();
    if (!win || rate <= 0) return;
    using SetRate = int32_t (*)(ANativeWindow*, float, int8_t);
    using SetRateStrategy = int32_t (*)(ANativeWindow*, float, int8_t, int8_t);
    // An app library's RTLD_DEFAULT does not reach them: look in the library itself.
    static void* lib = dlopen("libnativewindow.so", RTLD_NOW | RTLD_LOCAL);
    static auto set_rate = reinterpret_cast<SetRate>(lib ? dlsym(lib, "ANativeWindow_setFrameRate") : nullptr);
    static auto set_rate_strategy = reinterpret_cast<SetRateStrategy>(lib ? dlsym(lib, "ANativeWindow_setFrameRateWithChangeStrategy") : nullptr);
    // Compatibility 0 (default: the game renders at whatever rate it gets), strategy 1 (always).
    int32_t rc = set_rate_strategy ? set_rate_strategy(win, rate, 0, 1) : set_rate ? set_rate(win, rate, 0) : -1;
    log("arm32: window frame rate %.0f Hz requested (%d)", static_cast<double>(rate), rc);
}

}  // namespace

void request_window_frame_rate() {
    std::lock_guard<std::mutex> lock(g_window_lock);
    ask_frame_rate(g_game_window);
}

void game_window_surface(ANativeWindow* win) {
    if (!win) return;
    std::lock_guard<std::mutex> lock(g_window_lock);
    if (win != g_game_window) {
        ANativeWindow_acquire(win);
        if (g_game_window) ANativeWindow_release(g_game_window);
        g_game_window = win;
    }
    ask_frame_rate(win);
}

}  // namespace arm32
