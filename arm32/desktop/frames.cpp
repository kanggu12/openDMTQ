// What the runtime's EGL bridge hands live view on a phone (live.h), on the desktop: each frame just before it is
// shown. The computer's broadcast takes it first (live_capture.cpp, on Windows), then the overlay's glass what it wants
// of it (glass_capture.cpp); then the frames are counted, the first one logged, what the display showed noted every
// five seconds with stats on, the taps a check planned by frame given (input.cpp), and the ones asked for
// (PLAYER_SHOTS="60,600,@12.5": frame numbers, and seconds from the first frame, which hold whatever the frame rate)
// saved as PNG files in the data folder's shots/, for checks to look at.
#include "live.h"
#include "player.h"

#include "host.h"

#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <dlfcn.h>
#include <fstream>
#include <set>
#include <string>
#include <sys/stat.h>
#include <vector>
#include <zlib.h>

namespace {

// Frames shown so far, counted here. Named apart from arm32::g_frames, the runtime's own count (note_frame), which
// a lookup from inside namespace arm32 would find first.
std::atomic<std::uint64_t> g_shown{0};
// When the last frame was shown (steady clock, nanoseconds; 0 before the first), for the frame counter.
std::atomic<std::int64_t> g_shown_ns{0};

// The frames to save, from PLAYER_SHOTS: by number, and by seconds from the first frame (the times still to come, in
// order).
struct Shots {
    std::set<std::uint64_t> frames;
    std::set<double> times;
};
Shots& shots() {
    static Shots s = [] {
        Shots out;
        const char* list = std::getenv("PLAYER_SHOTS");
        for (const char* p = list; p && *p;) {
            const bool timed = *p == '@';
            char* end = nullptr;
            if (timed) {
                const double at = std::strtod(p + 1, &end);
                if (end == p + 1) break;
                out.times.insert(at);
            } else {
                const unsigned long long n = std::strtoull(p, &end, 10);
                if (end == p) break;
                out.frames.insert(n);
            }
            p = *end == ',' ? end + 1 : end;
        }
        return out;
    }();
    return s;
}

// The monotonic clock in seconds, for the shots by time.
double now_seconds() {
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<double>(ts.tv_sec) + static_cast<double>(ts.tv_nsec) / 1e9;
}

// One PNG chunk: its length, type, data, and the CRC of type and data.
void chunk(std::vector<unsigned char>& png, const char* type, const unsigned char* data, std::size_t n) {
    auto be32 = [&png](std::uint32_t v) {
        for (int s = 24; s >= 0; s -= 8) png.push_back(static_cast<unsigned char>(v >> s));
    };
    be32(static_cast<std::uint32_t>(n));
    std::size_t start = png.size();
    png.insert(png.end(), type, type + 4);
    png.insert(png.end(), data, data + n);
    be32(static_cast<std::uint32_t>(crc32(0, png.data() + start, static_cast<uInt>(png.size() - start))));
}

// RGBA rows as GL reads them (bottom row first) to an RGBA PNG file.
bool write_png(const std::string& path, int w, int h, const std::vector<unsigned char>& rgba) {
    // Each PNG row: filter byte 0 (none), then the row, top row first.
    std::vector<unsigned char> raw;
    raw.reserve(static_cast<std::size_t>(h) * (static_cast<std::size_t>(w) * 4 + 1));
    for (int y = h - 1; y >= 0; --y) {
        raw.push_back(0);
        const unsigned char* row = rgba.data() + static_cast<std::size_t>(y) * static_cast<std::size_t>(w) * 4;
        raw.insert(raw.end(), row, row + static_cast<std::size_t>(w) * 4);
    }
    uLongf packed_len = compressBound(static_cast<uLong>(raw.size()));
    std::vector<unsigned char> packed(packed_len);
    if (compress(packed.data(), &packed_len, raw.data(), static_cast<uLong>(raw.size())) != Z_OK) return false;
    std::vector<unsigned char> png = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
    unsigned char ihdr[13] = {static_cast<unsigned char>(w >> 24), static_cast<unsigned char>(w >> 16), static_cast<unsigned char>(w >> 8), static_cast<unsigned char>(w),
                              static_cast<unsigned char>(h >> 24), static_cast<unsigned char>(h >> 16), static_cast<unsigned char>(h >> 8), static_cast<unsigned char>(h),
                              8, 6, 0, 0, 0};  // 8 bits, RGBA, deflate, no filter set, no interlace
    chunk(png, "IHDR", ihdr, sizeof ihdr);
    chunk(png, "IDAT", packed.data(), packed_len);
    chunk(png, "IEND", nullptr, 0);
    std::ofstream f(player::utf8_path(path), std::ios::binary | std::ios::trunc);
    f.write(reinterpret_cast<const char*>(png.data()), static_cast<std::streamsize>(png.size()));
    f.close();
    return static_cast<bool>(f);
}

// The frame about to be shown, read from the window's back buffer (the default framebuffer), whatever the game has
// bound for reading, which is put back after.
void save_frame(EGLDisplay display, EGLSurface surface, std::uint64_t n, const std::string& name) {
    static void* egl = dlopen(arm32::kHostEgl, RTLD_NOW | RTLD_LOCAL);
    auto query = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint, EGLint*)>(egl ? dlsym(egl, "eglQuerySurface") : nullptr);
    auto get_int = reinterpret_cast<void (*)(GLenum, GLint*)>(arm32::gl_proc("glGetIntegerv"));
    auto bind = reinterpret_cast<void (*)(GLenum, GLuint)>(arm32::gl_proc("glBindFramebuffer"));
    auto read = reinterpret_cast<void (*)(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, void*)>(arm32::gl_proc("glReadPixels"));
    auto pixel_store = reinterpret_cast<void (*)(GLenum, GLint)>(arm32::gl_proc("glPixelStorei"));
    EGLint w = 0, h = 0;
    if (!query || !get_int || !bind || !read || !pixel_store || !query(display, surface, EGL_WIDTH, &w) || !query(display, surface, EGL_HEIGHT, &h) || w <= 0 || h <= 0) return;
    GLint was_bound = 0, was_alignment = 4;
    get_int(GL_READ_FRAMEBUFFER_BINDING, &was_bound);
    get_int(GL_PACK_ALIGNMENT, &was_alignment);
    bind(GL_READ_FRAMEBUFFER, 0);
    pixel_store(GL_PACK_ALIGNMENT, 1);
    std::vector<unsigned char> rgba(static_cast<std::size_t>(w) * static_cast<std::size_t>(h) * 4);
    read(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
    pixel_store(GL_PACK_ALIGNMENT, was_alignment);
    bind(GL_READ_FRAMEBUFFER, static_cast<GLuint>(was_bound));
    std::string dir = player::app().host_data + "/shots";
    mkdir(dir.c_str(), 0755);
    std::string path = dir + "/" + name + ".png";
    if (write_png(path, w, h, rgba)) arm32::log("player: frame %llu saved to %s (%dx%d)", static_cast<unsigned long long>(n), path.c_str(), w, h);
}

// With stats on, every five seconds: what the display itself counted, where the host's EGL says it
// (EGL_CHROMIUM_sync_control, ANGLE's on Windows): its refreshes and the frames that reached it in that time. One frame
// per refresh is a refresh of its own for every frame; fewer frames than refreshes is a frame shown twice somewhere.
void present_stats(EGLDisplay display, EGLSurface surface) {
    using SyncValues = EGLBoolean (*)(EGLDisplay, EGLSurface, std::uint64_t*, std::uint64_t*, std::uint64_t*);
    static void* egl = dlopen(arm32::kHostEgl, RTLD_NOW | RTLD_LOCAL);
    static auto get_proc = reinterpret_cast<void* (*)(const char*)>(egl ? dlsym(egl, "eglGetProcAddress") : nullptr);
    static auto sync_values = reinterpret_cast<SyncValues>(get_proc ? get_proc("eglGetSyncValuesCHROMIUM") : nullptr);
    static auto get_error = reinterpret_cast<EGLint (*)()>(egl ? dlsym(egl, "eglGetError") : nullptr);
    static double last_report = 0;
    static std::uint64_t last_msc = 0, last_sbc = 0;
    static bool said = false;
    if (!sync_values) return;
    const double now = now_seconds();
    if (now - last_report < 5) return;
    std::uint64_t ust = 0, msc = 0, sbc = 0;
    if (sync_values(display, surface, &ust, &msc, &sbc) != EGL_TRUE) {
        // Its error is ours to clear, not the game's to read.
        if (get_error) get_error();
        if (!said) arm32::log("stats: the display does not say what it showed (no sync values for this window)");
        said = true;
        last_report = now;
        return;
    }
    if (last_report > 0 && last_msc && msc >= last_msc && sbc >= last_sbc) {
        const double span = now - last_report;
        arm32::log("stats: the display: %llu refreshes and %llu frames shown in %.1f s",
                   static_cast<unsigned long long>(msc - last_msc), static_cast<unsigned long long>(sbc - last_sbc), span);
    }
    last_report = now;
    last_msc = msc;
    last_sbc = sbc;
}

}  // namespace

namespace arm32 {

// The broadcast of a computer's player: its capture on the render thread (live_capture.cpp; live_desktop.cpp on Linux).
void desktop_live_frame(EGLDisplay display, EGLSurface surface);
void desktop_live_context_destroyed(EGLContext context);
// The overlay's glass: the frame behind its pieces read for its thread (glass_capture.cpp), a context gone, and what the
// reads cost, in the stats.
void glass_frame(EGLDisplay display, EGLSurface surface);
void glass_context_destroyed(EGLContext context);
void glass_stats();

// The phone's start of live view: the computer's starts at its first swap, from the player's own files.
void live_load(JavaVM*, JNIEnv*, const std::string&) {}

void live_frame(EGLDisplay display, EGLSurface surface) {
    // The broadcast first, while the frame is the one that goes to the screen.
    desktop_live_frame(display, surface);
    // Then what the overlay's glass wants of it, read without the overlay over it (one atomic load while none is up).
    glass_frame(display, surface);
    // The frame's moment first, then the count: a reader that sees the count sees this frame's time or a later one.
    g_shown_ns.store(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(),
                     std::memory_order_relaxed);
    std::uint64_t n = g_shown.fetch_add(1, std::memory_order_release) + 1;
    if (n == 1) {
        log("player: the game's first frame");
        // What draws it, with the game's context current as at every swap: on Windows ANGLE names the graphics card and
        // the Direct3D under it, so that a log shows the game on the computer's fast GPU (an integrated one, or
        // Microsoft's software renderer, would be named here). At the first frame, whatever the picture's settings.
        auto get_string = reinterpret_cast<const GLubyte* (*)(GLenum)>(arm32::gl_proc("glGetString"));
        const auto* renderer = get_string ? reinterpret_cast<const char*>(get_string(GL_RENDERER)) : nullptr;
        const auto* version = get_string ? reinterpret_cast<const char*>(get_string(GL_VERSION)) : nullptr;
        log("player: drawn by %s, %s", renderer ? renderer : "an unnamed renderer", version ? version : "no version");
    }
    if (g_stats) present_stats(display, surface);
    // What the glass's reads cost this thread, every five seconds while any glass was up.
    if (g_stats) glass_stats();
    Shots& s = shots();
    if (s.frames.count(n)) save_frame(display, surface, n, "frame-" + std::to_string(n));
    if (!s.times.empty()) {
        // Seconds from the first frame: a time that has come is saved once, as time-<seconds>.png.
        static const double first = now_seconds();
        const double at = *s.times.begin();
        if (now_seconds() - first >= at) {
            s.times.erase(s.times.begin());
            char name[32];
            std::snprintf(name, sizeof name, "time-%06.1f", at);
            save_frame(display, surface, n, name);
        }
    }
    player::frame_shown(n);
}

void live_context_destroyed(EGLContext context) {
    desktop_live_context_destroyed(context);
    // The glass's objects went with it too.
    glass_context_destroyed(context);
}
// The phone's sound for live view: a computer's broadcast takes the player's whole mix instead (mixer.h's tap).
void live_audio_source(const void*, int, int, int) {}
void live_audio(const void*, const void*, std::size_t) {}

}  // namespace arm32

// The count live_frame keeps, for the overlay's frame counter (player.h).
std::uint64_t player::frames_shown() { return g_shown.load(std::memory_order_acquire); }
// And when the last of them was shown, for the counter's frames a second between two frames' own moments.
std::int64_t player::frame_shown_ns() { return g_shown_ns.load(std::memory_order_relaxed); }
