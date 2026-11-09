// Frame pacing for the app's window (see pacing.cpp).
#pragma once

#include <EGL/egl.h>

#include <atomic>
#include <cstdint>

namespace arm32 {

// A computer's display, as its player reads it from the system; a phone's compositor gives its timing with every frame
// instead, and these stay 0 there. The refresh interval of the display the app's window is on, in nanoseconds, and the
// time of one of its recent refreshes on the monotonic clock (0: not known). Such a display keeps its own rate whatever a
// window asks: following it, the frame rate starts at that rate and steps down through its whole fractions, and frames
// go out on its refreshes, held there by the swap interval. The player sets them again when the window moves to another
// display or the display's mode changes.
extern std::atomic<std::int64_t> g_display_interval;
extern std::atomic<std::int64_t> g_display_vblank;
// A computer player's choices for its frames (its PC settings; a phone keeps the defaults): on the display's refreshes
// (vsync) or as soon as drawn, and the most frames a second (0: the display's own rate; with vsync, a whole fraction of
// that rate when one is within 10 % below this, else this held by the clock, pacing.cpp host_top).
extern std::atomic<bool> g_host_vsync;
extern std::atomic<float> g_host_fps_cap;
// The size a computer player has the game's window surface made at, below the window's own pixels (its render scale:
// ANGLE stretches the picture to the window), as width << 32 | height; 0 for the window's own size, as on a phone.
extern std::atomic<std::int64_t> g_window_fixed_size;

// Whether frames are to be paced: debug.arm32.pacing (on unless "0") and an app frame rate.
bool pacing_enabled();
// True while the swaps are being paced; the game's own frame limiter then has to stay above the
// app frame rate, or the two fight.
bool pacing_active();
// The swap interval for the game's eglSwapInterval(asked): its own, except while frames are paced,
// which needs 1 on a phone (no swap may replace a queued frame) and on a computer's display the
// refreshes per frame. `asked` is kept for when pacing stops.
EGLint pacing_swap_interval(EGLint asked);
// While the frame rate follows the display (tweaks.h): the rate in use, 60 until the display's
// refresh rate is known, then that rate, one step lower each time frames did not keep up with it.
float followed_frame_rate();
// The rate the game's window asks the display for while following: 144, lower after each step down; on a computer's
// display, which keeps its own rate, that rate and its fractions.
float followed_window_rate();
// Reads the phone's thermal status for the frame rate's next check. A call into the system: from a
// thread of its own, every few seconds.
void pacing_thermal_tick();
// Called when the app destroys a surface: a new one at the same address starts over.
void pacing_surface_destroyed(EGLSurface surface);
// eglSwapBuffers with pacing: the frame is shown a whole number of refreshes after the one before,
// and the call returns when the next frame should start.
EGLBoolean paced_swap(EGLDisplay display, EGLSurface surface);

}  // namespace arm32
