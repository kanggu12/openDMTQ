// What the code shared by the runtime and the 32-bit shim needs from whichever it runs in: the runtime
// (runtime.h, log.cpp, diag.cpp) or the shim (shim/shim.cpp).
#pragma once

#include <atomic>
#include <cstdint>

namespace arm32 {

// Performance counters logged every five seconds, on with ARM32_STATS or debug.arm32.stats.
extern bool g_stats;
// A switch from the environment (command line) or a system property (apps): "1" on, "0" off,
// fallback when neither is set.
bool requested(const char* env, const char* property, bool fallback = false);

// Frames the app has presented (eglSwapBuffers); the hang watch looks for it standing still.
extern std::atomic<std::uint64_t> g_frames;
// Called at each presented frame: counts it and, with stats on, records the time since the last.
void note_frame();
// With stats on, called when a frame is known to have reached the screen: the time since the frame
// before it got there, and whether it came later than the pacing asked for.
void note_shown(float interval_ms, bool late);

// How long the calling guest thread has slept in nanosleep and clock_nanosleep, in all. Between two
// swaps that is the game's own frame limiter (pacing.cpp). The runtime only: the shim cannot tell.
extern thread_local std::int64_t t_guest_sleep_ns;

// A GL entry point of the system's library.
void* gl_proc(const char* name);

// Writes a diagnostic line to stderr and the Android log.
void log(const char* fmt, ...) __attribute__((format(printf, 1, 2)));

}  // namespace arm32
