// What the code shared by the runtime and the 32-bit shim needs from whichever it runs in: the runtime
// (runtime.h, log.cpp, diag.cpp) or the shim (shim/shim.cpp).
#pragma once

#include <atomic>
#include <cstdint>
#include <string>

namespace arm32 {

// Performance counters logged every five seconds, on with ARM32_STATS or debug.arm32.stats.
extern bool g_stats;
// A switch from the environment (command line) or a system property (apps): "1" on, "0" off,
// fallback when neither is set.
bool requested(const char* env, const char* property, bool fallback = false);
// A setting's text the same way: the environment variable when set, else the system property (a
// desktop host has none); "" when neither is.
std::string setting(const char* env, const char* property);

// The host's EGL and GLES libraries: the phone's own on Android; on Windows ANGLE's, which the player carries beside
// it (OpenGL ES on Direct3D 11); on a desktop Linux host the GL vendor-neutral dispatch's (Mesa's, or the graphics
// vendor's behind it), by their run-time names.
#ifdef __ANDROID__
inline constexpr const char* kHostEgl = "libEGL.so";
inline constexpr const char* kHostGles = "libGLESv3.so";
#elif defined(_WIN32)
inline constexpr const char* kHostEgl = "libEGL.dll";
inline constexpr const char* kHostGles = "libGLESv2.dll";
#else
inline constexpr const char* kHostEgl = "libEGL.so.1";
inline constexpr const char* kHostGles = "libGLESv2.so.2";
#endif

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
