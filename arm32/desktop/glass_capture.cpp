// The game's frame behind the overlay's glass (glass_capture.h says why): on the game's render thread, at each swap, while
// the overlay wants rectangles of it. Each wanted rectangle of the frame as it goes to the window (after the player's
// passes, at the window's own size or the render scale's) is scaled to a quarter of its size by one blit into a small
// picture of ours, stacked one under another, and the whole is read into a pixel buffer with one read and a fence. A
// later swap, once the GPU says it is done, copies it out for the overlay's thread; nothing here waits for the GPU. At
// most 20 reads a second, one in flight at a time; with nothing wanted and nothing in flight, a swap costs one atomic
// load. Everything of the game's GL state this touches is put back, as the broadcast's capture does (live_capture.cpp).
#include "glass_capture.h"

#include "host.h"

#include <EGL/egl.h>
#include <GLES3/gl3.h>

#include <algorithm>
#include <atomic>
#include <cstring>
#include <ctime>
#include <dlfcn.h>
#include <mutex>

namespace player::glass {

namespace {

// ---- what the two threads share

// The overlay's wish: its rectangles, the game's window's size they are in, and a number that changes with every new
// wish (the render thread reads at once for a new one rather than waiting out its 50 ms).
std::mutex g_wish_lock;
std::vector<Rect> g_wish;
int g_wish_w = 0, g_wish_h = 0;
unsigned g_wish_serial = 0;
// Whether there is anything to do at a swap: a wish, or a read in flight. The one load a swap makes otherwise.
std::atomic<bool> g_active{false};
// The last read, handed over whole, and how many reads have been.
std::mutex g_shot_lock;
std::shared_ptr<const std::vector<Shot>> g_shots;
std::atomic<unsigned> g_generation{0};

// What the reads cost the render thread, for the stats: the reads issued and the hand-overs, their time and the
// longest of either, and the swaps that did anything and the ones that did not.
std::atomic<std::uint64_t> g_reads{0}, g_read_ns{0}, g_handed{0}, g_hand_ns{0}, g_most_ns{0}, g_busy_swaps{0}, g_idle_swaps{0};
std::atomic<std::uint64_t> g_read_pixels{0};

// The monotonic clock in nanoseconds.
std::int64_t now_ns() {
    timespec t{};
    clock_gettime(CLOCK_MONOTONIC, &t);
    return static_cast<std::int64_t>(t.tv_sec) * 1000000000 + t.tv_nsec;
}

// The longest single cost so far, kept.
void note_most(std::uint64_t ns) {
    std::uint64_t was = g_most_ns.load(std::memory_order_relaxed);
    while (ns > was && !g_most_ns.compare_exchange_weak(was, ns, std::memory_order_relaxed)) {
    }
}

}  // namespace

Rect aligned(const Rect& r, int by, int w, int h) {
    // Grown, then out to the multiples of 4 around it, then within the area (whose own edges are rounded down to them:
    // a last column or row of fewer than 4 pixels stays out).
    const int area_w = w / 4 * 4, area_h = h / 4 * 4;
    int x0 = std::max(0, (r.x - by) / 4 * 4), y0 = std::max(0, (r.y - by) / 4 * 4);
    int x1 = std::min(area_w, (r.x + r.w + by + 3) / 4 * 4), y1 = std::min(area_h, (r.y + r.h + by + 3) / 4 * 4);
    // Nothing of it in the area: an empty rectangle, which a wish leaves out.
    if (x1 <= x0 || y1 <= y0) return Rect{};
    return Rect{x0, y0, x1 - x0, y1 - y0};
}

void want(const std::vector<Rect>& rects, int area_w, int area_h) {
    std::vector<Rect> kept;
    // Only rectangles with pixels, on whole quarters, within the window.
    for (const Rect& r : rects) {
        const Rect a = aligned(r, 0, area_w, area_h);
        if (a.w >= 4 && a.h >= 4) kept.push_back(a);
    }
    std::lock_guard<std::mutex> l(g_wish_lock);
    // The same wish again changes nothing: the render thread keeps its 20 reads a second.
    const bool same = kept.size() == g_wish.size() && area_w == g_wish_w && area_h == g_wish_h &&
                      std::equal(kept.begin(), kept.end(), g_wish.begin(), [](const Rect& a, const Rect& b) {
                          return a.x == b.x && a.y == b.y && a.w == b.w && a.h == b.h;
                      });
    if (same) return;
    g_wish = std::move(kept);
    g_wish_w = area_w;
    g_wish_h = area_h;
    ++g_wish_serial;
    // Something to do from the next swap; a read in flight finishes on its own and clears it after.
    if (!g_wish.empty()) g_active.store(true, std::memory_order_release);
}

bool take(unsigned& generation, std::shared_ptr<const std::vector<Shot>>& out) {
    const unsigned now = g_generation.load(std::memory_order_acquire);
    if (now == generation) return false;
    std::lock_guard<std::mutex> l(g_shot_lock);
    out = g_shots;
    generation = g_generation.load(std::memory_order_relaxed);
    return true;
}

unsigned generation() { return g_generation.load(std::memory_order_acquire); }

}  // namespace player::glass

namespace arm32 {

namespace {

using namespace player::glass;

// ---- the render thread: GL in the game's own context, everything of its state put back

// An EGL entry point of the host's library (ANGLE's on Windows), looked up by name.
void* egl_proc(const char* name) {
    static void* lib = dlopen(kHostEgl, RTLD_NOW | RTLD_LOCAL);
    return lib ? dlsym(lib, name) : nullptr;
}

// The GL entry points the reads use, looked up once.
struct Gl {
    PFNGLGETINTEGERVPROC get_integer;
    PFNGLGETBOOLEANVPROC get_boolean;
    PFNGLISENABLEDPROC is_enabled;
    PFNGLENABLEPROC enable;
    PFNGLDISABLEPROC disable;
    PFNGLCOLORMASKPROC color_mask;
    PFNGLGENTEXTURESPROC gen_textures;
    PFNGLDELETETEXTURESPROC delete_textures;
    PFNGLBINDTEXTUREPROC bind_texture;
    PFNGLTEXSTORAGE2DPROC tex_storage;
    PFNGLTEXPARAMETERIPROC tex_parameter;
    PFNGLGENFRAMEBUFFERSPROC gen_framebuffers;
    PFNGLDELETEFRAMEBUFFERSPROC delete_framebuffers;
    PFNGLBINDFRAMEBUFFERPROC bind_framebuffer;
    PFNGLFRAMEBUFFERTEXTURE2DPROC framebuffer_texture;
    PFNGLCHECKFRAMEBUFFERSTATUSPROC check_framebuffer;
    PFNGLBLITFRAMEBUFFERPROC blit;
    PFNGLGENBUFFERSPROC gen_buffers;
    PFNGLDELETEBUFFERSPROC delete_buffers;
    PFNGLBINDBUFFERPROC bind_buffer;
    PFNGLBUFFERDATAPROC buffer_data;
    PFNGLMAPBUFFERRANGEPROC map_buffer;
    PFNGLUNMAPBUFFERPROC unmap_buffer;
    PFNGLPIXELSTOREIPROC pixel_store;
    PFNGLREADPIXELSPROC read_pixels;
    PFNGLFENCESYNCPROC fence;
    PFNGLCLIENTWAITSYNCPROC client_wait;
    PFNGLDELETESYNCPROC delete_sync;
    bool ok = false;
};

template <class T>
void look_up(T& out, const char* name, bool& ok) {
    out = reinterpret_cast<T>(gl_proc(name));
    if (!out) ok = false;
}

const Gl& gl() {
    static const Gl g = [] {
        Gl x{};
        bool ok = true;
        look_up(x.get_integer, "glGetIntegerv", ok);
        look_up(x.get_boolean, "glGetBooleanv", ok);
        look_up(x.is_enabled, "glIsEnabled", ok);
        look_up(x.enable, "glEnable", ok);
        look_up(x.disable, "glDisable", ok);
        look_up(x.color_mask, "glColorMask", ok);
        look_up(x.gen_textures, "glGenTextures", ok);
        look_up(x.delete_textures, "glDeleteTextures", ok);
        look_up(x.bind_texture, "glBindTexture", ok);
        look_up(x.tex_storage, "glTexStorage2D", ok);
        look_up(x.tex_parameter, "glTexParameteri", ok);
        look_up(x.gen_framebuffers, "glGenFramebuffers", ok);
        look_up(x.delete_framebuffers, "glDeleteFramebuffers", ok);
        look_up(x.bind_framebuffer, "glBindFramebuffer", ok);
        look_up(x.framebuffer_texture, "glFramebufferTexture2D", ok);
        look_up(x.check_framebuffer, "glCheckFramebufferStatus", ok);
        look_up(x.blit, "glBlitFramebuffer", ok);
        look_up(x.gen_buffers, "glGenBuffers", ok);
        look_up(x.delete_buffers, "glDeleteBuffers", ok);
        look_up(x.bind_buffer, "glBindBuffer", ok);
        look_up(x.buffer_data, "glBufferData", ok);
        look_up(x.map_buffer, "glMapBufferRange", ok);
        look_up(x.unmap_buffer, "glUnmapBuffer", ok);
        look_up(x.pixel_store, "glPixelStorei", ok);
        look_up(x.read_pixels, "glReadPixels", ok);
        look_up(x.fence, "glFenceSync", ok);
        look_up(x.client_wait, "glClientWaitSync", ok);
        look_up(x.delete_sync, "glDeleteSync", ok);
        x.ok = ok;
        return x;
    }();
    return g;
}

// The game's state a read touches, saved before it and put back after.
struct Saved {
    GLint read = 0, draw = 0, pack_buffer = 0, texture = 0;
    GLint pack_alignment = 4, pack_row_length = 0, pack_skip_rows = 0, pack_skip_pixels = 0;
    GLboolean mask[4] = {GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE};
    // The scissor and the rasterizer's discard, which a blit heeds.
    GLboolean scissor = GL_FALSE, discard = GL_FALSE;
};

void save_state(const Gl& g, Saved& s) {
    g.get_integer(GL_READ_FRAMEBUFFER_BINDING, &s.read);
    g.get_integer(GL_DRAW_FRAMEBUFFER_BINDING, &s.draw);
    g.get_integer(GL_PIXEL_PACK_BUFFER_BINDING, &s.pack_buffer);
    // The texture bound on the unit in use: a new picture of ours is bound there while it is made.
    g.get_integer(GL_TEXTURE_BINDING_2D, &s.texture);
    g.get_integer(GL_PACK_ALIGNMENT, &s.pack_alignment);
    g.get_integer(GL_PACK_ROW_LENGTH, &s.pack_row_length);
    g.get_integer(GL_PACK_SKIP_ROWS, &s.pack_skip_rows);
    g.get_integer(GL_PACK_SKIP_PIXELS, &s.pack_skip_pixels);
    g.get_boolean(GL_COLOR_WRITEMASK, s.mask);
    s.scissor = g.is_enabled(GL_SCISSOR_TEST);
    s.discard = g.is_enabled(GL_RASTERIZER_DISCARD);
}

void restore_state(const Gl& g, const Saved& s) {
    if (s.scissor) g.enable(GL_SCISSOR_TEST);
    else g.disable(GL_SCISSOR_TEST);
    if (s.discard) g.enable(GL_RASTERIZER_DISCARD);
    else g.disable(GL_RASTERIZER_DISCARD);
    g.color_mask(s.mask[0], s.mask[1], s.mask[2], s.mask[3]);
    g.pixel_store(GL_PACK_ALIGNMENT, s.pack_alignment);
    g.pixel_store(GL_PACK_ROW_LENGTH, s.pack_row_length);
    g.pixel_store(GL_PACK_SKIP_ROWS, s.pack_skip_rows);
    g.pixel_store(GL_PACK_SKIP_PIXELS, s.pack_skip_pixels);
    g.bind_buffer(GL_PIXEL_PACK_BUFFER, static_cast<GLuint>(s.pack_buffer));
    g.bind_texture(GL_TEXTURE_2D, static_cast<GLuint>(s.texture));
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, static_cast<GLuint>(s.read));
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, static_cast<GLuint>(s.draw));
}

// Fewer than this many milliseconds between two reads: 20 a second at most.
constexpr std::int64_t kEveryNs = 50000000;

// The reads' objects in the game's context, and the read in flight.
struct Reader {
    EGLContext context = EGL_NO_CONTEXT;
    // The picture the rectangles are scaled into, one under another, its framebuffer, and its size.
    GLuint picture = 0, fbo = 0;
    int picture_w = 0, picture_h = 0;
    // The pixel buffer the picture is read into, and its size in bytes.
    GLuint buffer = 0;
    GLsizeiptr buffer_bytes = 0;
    // The read in flight: its fence, the rectangles it holds and where each sits in the picture, the width it read.
    GLsync fence = nullptr;
    std::vector<Rect> rects;
    std::vector<int> rows;
    int read_w = 0, read_h = 0;
    // The wish it read for, and when the last read was issued.
    unsigned serial = 0;
    std::int64_t last = 0;
    // The frame cannot be read here (no OpenGL ES 3, a multisampled window): said once, then nothing is tried.
    bool refused = false;
} g_reader;

// A context the game destroyed, until the render thread has seen it: its objects went with it.
std::atomic<void*> g_destroyed{nullptr};

// The reader's objects gone, in their own context; outside it they went with the context.
void drop(Reader& r, bool current) {
    if (current) {
        const Gl& g = gl();
        if (r.fence) g.delete_sync(r.fence);
        if (r.buffer) g.delete_buffers(1, &r.buffer);
        if (r.fbo) g.delete_framebuffers(1, &r.fbo);
        if (r.picture) g.delete_textures(1, &r.picture);
    }
    const bool refused = r.refused;
    r = Reader{};
    r.refused = refused;
}

// The picture at least `w` by `h`, and the pixel buffer for all of it: made again only when a wish needs more. Made at
// once as large as a quarter of the whole window (`area_w` by `area_h`) and a little more, which the question's read and
// any pieces' together fit in: the first read makes them (a millisecond or two, once), and no later wish makes them
// again. The caller has the game's state saved. False when the driver will not.
bool room(const Gl& g, Reader& r, int w, int h, int area_w, int area_h) {
    if (w > r.picture_w || h > r.picture_h) {
        if (r.fbo) g.delete_framebuffers(1, &r.fbo);
        if (r.picture) g.delete_textures(1, &r.picture);
        r.picture_w = std::max({w, r.picture_w, (area_w + 3) / 4});
        r.picture_h = std::max({h, r.picture_h, (area_h + 3) / 4 + 64});
        g.gen_textures(1, &r.picture);
        g.bind_texture(GL_TEXTURE_2D, r.picture);
        g.tex_storage(GL_TEXTURE_2D, 1, GL_RGBA8, r.picture_w, r.picture_h);
        g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        g.gen_framebuffers(1, &r.fbo);
        g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, r.fbo);
        g.framebuffer_texture(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, r.picture, 0);
        if (g.check_framebuffer(GL_DRAW_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) return false;
    }
    // The pixel buffer as large as the picture.
    const auto bytes = static_cast<GLsizeiptr>(r.picture_w) * r.picture_h * 4;
    if (bytes > r.buffer_bytes) {
        if (!r.buffer) g.gen_buffers(1, &r.buffer);
        g.bind_buffer(GL_PIXEL_PACK_BUFFER, r.buffer);
        g.buffer_data(GL_PIXEL_PACK_BUFFER, bytes, nullptr, GL_STREAM_READ);
        r.buffer_bytes = bytes;
    }
    return true;
}

// The read in flight copied out for the overlay once the GPU is done with it; nothing when it is not yet.
void collect(const Gl& g, Reader& r) {
    if (!r.fence) return;
    const GLenum state = g.client_wait(r.fence, GL_SYNC_FLUSH_COMMANDS_BIT, 0);
    if (state != GL_ALREADY_SIGNALED && state != GL_CONDITION_SATISFIED) return;
    const std::int64_t began = now_ns();
    g.delete_sync(r.fence);
    r.fence = nullptr;
    GLint bound = 0;
    g.get_integer(GL_PIXEL_PACK_BUFFER_BINDING, &bound);
    g.bind_buffer(GL_PIXEL_PACK_BUFFER, r.buffer);
    const auto bytes = static_cast<GLsizeiptr>(r.read_w) * r.read_h * 4;
    const auto* mapped = static_cast<const std::uint8_t*>(g.map_buffer(GL_PIXEL_PACK_BUFFER, 0, bytes, GL_MAP_READ_BIT));
    if (mapped) {
        // Each rectangle's rows out of the picture: its own width of each row, its rows from where it was put.
        std::vector<Shot> shots(r.rects.size());
        for (std::size_t i = 0; i < r.rects.size(); ++i) {
            Shot& s = shots[i];
            s.rect = r.rects[i];
            s.w = s.rect.w / 4;
            s.h = s.rect.h / 4;
            s.rgba.resize(static_cast<std::size_t>(s.w) * static_cast<std::size_t>(s.h) * 4);
            for (int y = 0; y < s.h; ++y) {
                const std::uint8_t* row = mapped + (static_cast<std::size_t>(r.rows[i] + y) * static_cast<std::size_t>(r.read_w)) * 4;
                std::memcpy(s.rgba.data() + static_cast<std::size_t>(y) * static_cast<std::size_t>(s.w) * 4, row, static_cast<std::size_t>(s.w) * 4);
            }
        }
        g.unmap_buffer(GL_PIXEL_PACK_BUFFER);
        {
            // Handed over whole, as a list the overlay shares: the next read makes a new one.
            auto handed = std::make_shared<const std::vector<Shot>>(std::move(shots));
            std::lock_guard<std::mutex> l(g_shot_lock);
            g_shots = std::move(handed);
        }
        g_generation.fetch_add(1, std::memory_order_release);
    }
    g.bind_buffer(GL_PIXEL_PACK_BUFFER, static_cast<GLuint>(bound));
    // What handing it over took on this thread.
    const auto took = static_cast<std::uint64_t>(now_ns() - began);
    g_handed.fetch_add(1, std::memory_order_relaxed);
    g_hand_ns.fetch_add(took, std::memory_order_relaxed);
    note_most(took);
}

// This frame's wanted rectangles read: scaled into the picture, read into the pixel buffer, a fence after; none of it
// waited for. False when it cannot be read here.
bool read(const Gl& g, Reader& r, const std::vector<Rect>& rects, int area_w, int area_h, int surface_w, int surface_h) {
    const std::int64_t began = now_ns();
    // Where each goes in the picture: one under another, from its top.
    std::vector<int> rows;
    int width = 0, height = 0;
    for (const Rect& rect : rects) {
        rows.push_back(height);
        width = std::max(width, rect.w / 4);
        height += rect.h / 4;
    }
    if (!width || !height) return true;
    Saved saved;
    save_state(g, saved);
    bool ok = room(g, r, width, height, area_w, area_h);
    if (ok) {
        g.disable(GL_SCISSOR_TEST);
        g.disable(GL_RASTERIZER_DISCARD);
        g.color_mask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        // The frame as it goes to the window: the window's framebuffer, whose size is the window's or, with a render
        // scale and the plain stretch, the scale's (ANGLE stretches it then).
        g.bind_framebuffer(GL_READ_FRAMEBUFFER, 0);
        g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, r.fbo);
        const double kx = static_cast<double>(surface_w) / area_w, ky = static_cast<double>(surface_h) / area_h;
        for (std::size_t i = 0; i < rects.size(); ++i) {
            const Rect& a = rects[i];
            // The window's rows from the top, GL's from the bottom; the destination upside down, so that the picture's
            // first row (the first one read) is the rectangle's top.
            const auto sx0 = static_cast<GLint>(a.x * kx + 0.5), sx1 = static_cast<GLint>((a.x + a.w) * kx + 0.5);
            const auto sy0 = static_cast<GLint>(surface_h - (a.y + a.h) * ky + 0.5), sy1 = static_cast<GLint>(surface_h - a.y * ky + 0.5);
            g.blit(sx0, sy0, sx1, sy1, 0, rows[i] + a.h / 4, a.w / 4, rows[i], GL_COLOR_BUFFER_BIT, GL_LINEAR);
        }
        // One read of the whole, into the pixel buffer: copied out at a later swap (collect).
        g.bind_framebuffer(GL_READ_FRAMEBUFFER, r.fbo);
        g.bind_buffer(GL_PIXEL_PACK_BUFFER, r.buffer);
        g.pixel_store(GL_PACK_ALIGNMENT, 4);
        g.pixel_store(GL_PACK_ROW_LENGTH, 0);
        g.pixel_store(GL_PACK_SKIP_ROWS, 0);
        g.pixel_store(GL_PACK_SKIP_PIXELS, 0);
        g.read_pixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        r.fence = g.fence(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
        r.rects = rects;
        r.rows = std::move(rows);
        r.read_w = width;
        r.read_h = height;
        g_read_pixels.fetch_add(static_cast<std::uint64_t>(width) * static_cast<std::uint64_t>(height), std::memory_order_relaxed);
    }
    restore_state(g, saved);
    const auto took = static_cast<std::uint64_t>(now_ns() - began);
    g_reads.fetch_add(1, std::memory_order_relaxed);
    g_read_ns.fetch_add(took, std::memory_order_relaxed);
    note_most(took);
    return ok && r.fence;
}

}  // namespace

void glass_frame(EGLDisplay d, EGLSurface s) {
    // The usual case, by far: no glass up, nothing in flight.
    if (!g_active.load(std::memory_order_acquire)) {
        if (g_stats) g_idle_swaps.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    const std::int64_t start = now_ns();
    Reader& r = g_reader;
    const Gl& g = gl();
    static auto current_context = reinterpret_cast<EGLContext (*)()>(egl_proc("eglGetCurrentContext"));
    static auto current_surface = reinterpret_cast<EGLSurface (*)(EGLint)>(egl_proc("eglGetCurrentSurface"));
    static auto query_surface = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint, EGLint*)>(egl_proc("eglQuerySurface"));
    static auto query_context = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLContext, EGLint, EGLint*)>(egl_proc("eglQueryContext"));
    if (!g.ok || !current_context || !current_surface || !query_surface || !query_context || r.refused) {
        // Nothing can be read here: the overlay keeps its plain tint, and the swaps are spared from now on.
        g_active.store(false, std::memory_order_release);
        return;
    }
    const EGLContext context = current_context();
    // A context the game destroyed took the objects along; one that is no longer current leaves them to it.
    if (void* dead = g_destroyed.exchange(nullptr, std::memory_order_relaxed)) {
        if (dead == r.context) drop(r, false);
    }
    // Only the frame going to the window, drawn on the current context.
    if (context == EGL_NO_CONTEXT || current_surface(EGL_DRAW) != s) return;
    if (r.context != context) {
        // Another context than the objects': theirs is left as it is (the game's own to end), and new ones are made here.
        drop(r, false);
        r.context = context;
        // A read that scales takes OpenGL ES 3, and a window that is not multisampled: its configuration's sample
        // buffers, by the configuration's id (a surface itself does not answer for its samples).
        static auto choose_config = reinterpret_cast<EGLBoolean (*)(EGLDisplay, const EGLint*, EGLConfig*, EGLint, EGLint*)>(egl_proc("eglChooseConfig"));
        static auto config_attrib = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLConfig, EGLint, EGLint*)>(egl_proc("eglGetConfigAttrib"));
        EGLint version = 0, samples = 0, config_id = 0, found = 0;
        query_context(d, context, EGL_CONTEXT_CLIENT_VERSION, &version);
        query_surface(d, s, EGL_CONFIG_ID, &config_id);
        const EGLint by_id[] = {EGL_CONFIG_ID, config_id, EGL_NONE};
        EGLConfig config = nullptr;
        if (choose_config && config_attrib && choose_config(d, by_id, &config, 1, &found) && found == 1) config_attrib(d, config, EGL_SAMPLE_BUFFERS, &samples);
        if (version < 3 || samples != 0) {
            log("player: glass: the frame cannot be read here (OpenGL ES %d, %d sample buffers): the overlay keeps its plain tint", version, samples);
            r.refused = true;
            g_active.store(false, std::memory_order_release);
            return;
        }
    }
    // What the GPU has finished, out to the overlay.
    collect(g, r);
    // The wish as it is now.
    std::vector<Rect> rects;
    int area_w = 0, area_h = 0;
    unsigned serial = 0;
    {
        std::lock_guard<std::mutex> l(g_wish_lock);
        rects = g_wish;
        area_w = g_wish_w;
        area_h = g_wish_h;
        serial = g_wish_serial;
        // Nothing wanted and nothing in flight: the swaps after this cost nothing again.
        if (rects.empty() && !r.fence) g_active.store(false, std::memory_order_release);
    }
    // A new read when one is wanted and none is in flight: at once for a new wish, else 50 ms after the last.
    if (!rects.empty() && !r.fence && area_w > 0 && area_h > 0 && (serial != r.serial || start - r.last >= kEveryNs)) {
        EGLint surface_w = 0, surface_h = 0;
        query_surface(d, s, EGL_WIDTH, &surface_w);
        query_surface(d, s, EGL_HEIGHT, &surface_h);
        if (surface_w > 0 && surface_h > 0) {
            if (!read(g, r, rects, area_w, area_h, surface_w, surface_h)) {
                log("player: glass: the frame's read cannot be set up here: the overlay keeps its plain tint");
                r.refused = true;
                g_active.store(false, std::memory_order_release);
            }
            r.serial = serial;
            r.last = start;
        }
    }
    if (g_stats) g_busy_swaps.fetch_add(1, std::memory_order_relaxed);
}

void glass_context_destroyed(EGLContext context) { g_destroyed.store(context, std::memory_order_relaxed); }

void glass_stats() {
    // Every 5 s with the stats on: what the reads cost this thread a frame over all frames, and a read and a hand-over
    // each; the longest of either since the last line.
    static std::int64_t last = 0;
    static std::uint64_t reads0 = 0, read_ns0 = 0, handed0 = 0, hand_ns0 = 0, busy0 = 0, idle0 = 0, pixels0 = 0;
    const std::int64_t now = now_ns();
    if (!last) last = now;
    if (now - last < 5000000000LL) return;
    last = now;
    const std::uint64_t reads = g_reads.load(), read_ns = g_read_ns.load(), handed = g_handed.load(), hand_ns = g_hand_ns.load();
    const std::uint64_t busy = g_busy_swaps.load(), idle = g_idle_swaps.load(), pixels = g_read_pixels.load();
    const std::uint64_t frames = (busy - busy0) + (idle - idle0), n_reads = reads - reads0, n_handed = handed - handed0;
    const std::uint64_t spent = (read_ns - read_ns0) + (hand_ns - hand_ns0);
    // Nothing to say while no glass was up: its cost is one atomic load a swap.
    if (busy != busy0 || n_reads) {
        log("stats: glass: %llu reads (%llu quarter pixels), %.3f ms a frame on the render thread over %llu frames (%llu with glass up): "
            "a read %.3f ms, a hand-over %.3f ms, the longest %.3f ms",
            static_cast<unsigned long long>(n_reads), static_cast<unsigned long long>(pixels - pixels0),
            frames ? static_cast<double>(spent) / static_cast<double>(frames) / 1e6 : 0.0, static_cast<unsigned long long>(frames),
            static_cast<unsigned long long>(busy - busy0), n_reads ? static_cast<double>(read_ns - read_ns0) / static_cast<double>(n_reads) / 1e6 : 0.0,
            n_handed ? static_cast<double>(hand_ns - hand_ns0) / static_cast<double>(n_handed) / 1e6 : 0.0,
            static_cast<double>(g_most_ns.exchange(0)) / 1e6);
    }
    reads0 = reads;
    read_ns0 = read_ns;
    handed0 = handed;
    hand_ns0 = hand_ns;
    busy0 = busy;
    idle0 = idle;
    pixels0 = pixels;
}

}  // namespace arm32
