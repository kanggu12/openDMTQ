// Frame pacing for the app's window (see pacing.cpp).
#pragma once

#include <EGL/egl.h>

namespace arm32 {

// Whether frames are to be paced: debug.arm32.pacing (on unless "0") and an app frame rate.
bool pacing_enabled();
// True while the swaps are being paced; the game's own frame limiter then has to stay above the
// app frame rate, or the two fight.
bool pacing_active();
// The swap interval for the game's eglSwapInterval(asked): its own, except while frames are paced,
// which needs 1 (no swap may replace a queued frame). `asked` is kept for when pacing stops.
EGLint pacing_swap_interval(EGLint asked);
// While the frame rate follows the display (tweaks.h): the rate in use, 60 until the display's
// refresh rate is known, then that rate, one step lower each time frames did not keep up with it.
float followed_frame_rate();
// The rate the game's window asks the display for while following: 144, lower after each step down.
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
