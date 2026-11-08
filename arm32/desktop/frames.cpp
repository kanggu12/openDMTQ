// What the runtime's EGL bridge hands live view on a phone (live.h), on the desktop: each frame just before it is
// shown. Live view itself is not here yet; the frames are counted, the first one logged, and the ones asked for
// (PLAYER_SHOTS="60,600", frame numbers) saved as PNG files in the data folder's shots/, for checks to look at.
#include "live.h"
#include "player.h"

#include "host.h"

#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <atomic>
#include <cstdio>
#include <cstdlib>
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

// The frame numbers to save, from PLAYER_SHOTS.
const std::set<std::uint64_t>& shots() {
    static const std::set<std::uint64_t> s = [] {
        std::set<std::uint64_t> out;
        const char* list = std::getenv("PLAYER_SHOTS");
        for (const char* p = list; p && *p;) {
            char* end = nullptr;
            unsigned long long n = std::strtoull(p, &end, 10);
            if (end == p) break;
            out.insert(n);
            p = *end == ',' ? end + 1 : end;
        }
        return out;
    }();
    return s;
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
void save_frame(EGLDisplay display, EGLSurface surface, std::uint64_t n) {
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
    std::string path = dir + "/frame-" + std::to_string(n) + ".png";
    if (write_png(path, w, h, rgba)) arm32::log("player: frame %llu saved to %s (%dx%d)", static_cast<unsigned long long>(n), path.c_str(), w, h);
}

}  // namespace

namespace arm32 {

void live_load(JavaVM*, JNIEnv*, const std::string&) {}

void live_frame(EGLDisplay display, EGLSurface surface) {
    std::uint64_t n = g_shown.fetch_add(1, std::memory_order_relaxed) + 1;
    if (n == 1) log("player: the game's first frame");
    if (shots().count(n)) save_frame(display, surface, n);
    player::frame_shown(n);
}

void live_context_destroyed(EGLContext) {}
void live_audio_source(const void*, int, int, int) {}
void live_audio(const void*, const void*, std::size_t) {}

}  // namespace arm32
