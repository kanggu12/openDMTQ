// The frame rate the game runs at, shared by the runtime and the 32-bit shim.
#pragma once

struct ANativeWindow;

namespace arm32 {

// The frame rate the app runs at: debug.arm32.framerate when set (0: none, the game keeps its own
// cap); otherwise, with a tweak for the game's cap, what pacing.cpp makes of the display's refresh
// rate (60 until known), and without one the game's own 60. Tweaks with the value "fps" set the
// game's cap to it.
float app_frame_rate();
// True when the frame rate follows the display: debug.arm32.framerate unset, a tweak has set the
// game's cap and the game's target can be read (60 until then).
bool frame_rate_follows_display();
// Asks the game's window for its rate again, after it changed (window_rate.cpp).
void request_window_frame_rate();
// Called when the game makes an EGL window surface on `window`: the window the frame rate is asked
// of from then on (window_rate.cpp).
void game_window_surface(ANativeWindow* window);
// The game's own frame target (Unity's Application.targetFrameRate) as last read on its main
// thread; 0 until known.
int game_target_frame_rate();
// True when this device did not keep its frame rate at the panel's own resolution, in this run or an earlier one: from the next
// start of the app on, the game draws at its low resolution (debug.arm32.lowres 0 or 1 decides instead). Smooth comes before sharp.
bool low_resolution_wanted();
// How many of the game's render calls into a run the low resolution is applied: seconds in, past the game's own start, which sets
// the panel's resolution, and before any song could have begun, whose layout goes by the resolution it started with.
constexpr unsigned kLowResolutionRender = 300;

}  // namespace arm32
