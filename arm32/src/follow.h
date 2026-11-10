// Following the display's refresh rate (see pacing.cpp's top): the frame rate the game runs at, the rate its window asks
// the display for, and when either steps down or back up. pacing.cpp feeds it each swap and each frame whose time on
// screen came. Apart from pacing.cpp so that the build machine runs it as the state machine it is
// (arm32/tests/host/follow_test.cpp): the clock is an argument, and what it needs of the rest of the runtime comes
// through FollowHooks, no EGL in between.
//
// Who calls what: follow_display, follow_note_shown and follow_restart, which change the state, run one at a time
// under their caller's lock (pacing.cpp's g_lock, which guards its Pacer too and is never held across a swap or a
// sleep). The rates (followed_frame_rate, followed_window_rate) are read without it from any thread, as tweaks.cpp and
// window_rate.cpp do, and follow_thermal is called from the thermal thread: all three are atomics.
#pragma once

#include <cstdint>

namespace arm32 {

// A gap between swaps over this is a pause (a load, the app away), not a slow frame: the check starts over.
inline constexpr std::int64_t kFollowPause = 100000000;

// What following the display asks of the runtime around it: pacing.cpp gives the real ones, the tests their stand-ins.
struct FollowHooks {
    int (*game_target)();             // the game's own frame target now (framerate.h's game_target_frame_rate)
    bool (*low_resolution_wanted)();  // the game's low resolution is on, or marked for the next start (pacing.h)
    void (*note_low_resolution)();    // marks it for the next start: frames fell short at the panel's own
    bool (*vsync)();                  // a computer's display: frames on its refreshes (the player's choice, g_host_vsync)
    float (*fps_cap)();               // and its frame limit (0: none; g_host_fps_cap)
    void (*rate_changed)();           // a new frame rate: pacing that ran stops, and the game's limiter goes back to it
};

// One swap of the window while following the display, at `now` (the monotonic clock, nanoseconds): `interval` is the
// display's refresh interval (0 when the compositor gave no timing), `gap` the time since the last swap (0 for the first),
// `host` true for a computer's display, whose interval the player gave (pacing.h). True when the window has to ask the
// display again (request_window_frame_rate, outside the lock).
bool follow_display(const FollowHooks& hooks, std::int64_t now, std::int64_t interval, std::int64_t gap, bool host);
// A frame whose time on screen came: `at` when it was swapped, `late` when it stayed on screen a refresh too long. Counted
// for the pace check when it was swapped in the check window that is open.
void follow_note_shown(std::int64_t at, bool late);
// The pace check's window and the wait for a new display rate start over (a new surface, a pause).
void follow_restart();
// The phone's own word on its temperature (AThermal's status; SEVERE is 3), from the thread that asks the system.
void follow_thermal(int status);
// Back to how a start finds it: for the tests, each from the same place.
void follow_reset();

// The frame rate in use, and the rate the window asks the display for (pacing.h has them too).
float followed_frame_rate();
float followed_window_rate();

}  // namespace arm32
