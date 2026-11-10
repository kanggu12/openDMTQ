// The computer's broadcast's pictures (live_desktop.cpp says what runs where): on the game's render thread, at each swap,
// the finished frame scaled, turned into NV12 and read back without waiting, then handed to the encoder thread
// (live_mf.cpp); the conversion's program made ahead at the first screens; and the end of a capture whose context went.
#include "live_state.h"

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>

#include <algorithm>
#include <cstring>
#include <dlfcn.h>
#include <mutex>
#include <vector>

namespace arm32::desktop_live {

namespace {

// No picture for this long (a pause, a load): the stream starts over from a new first segment.
constexpr Nanos kRestartAfter = 3 * kSecond;
// A frame this much earlier than due still counts: swaps come with some jitter around the display's beat, and without
// this the 30 pictures a second of a 60 fps game would come unevenly.
constexpr Nanos kCaptureTolerance = 2000000;
// Pictures in flight between the render thread and the encoder: read back on the GPU, waiting to be copied out.
constexpr int kSlots = 3;
// Pictures copied out and waiting for the encoder: one more is dropped (the encoder is behind).
constexpr std::size_t kFrameQueue = 4;

// ---- the render thread: GL in the game's own context, everything of its state put back

// An EGL entry point of the system's library (ANGLE's on Windows), looked up by name.
void* egl_proc(const char* name) {
    static void* lib = dlopen(kHostEgl, RTLD_NOW | RTLD_LOCAL);
    return lib ? dlsym(lib, name) : nullptr;
}

// The host's GL entry points (gl_bridge.h's gl_proc), looked up once.
struct Gl {
    PFNGLGETINTEGERVPROC get_integer;
    PFNGLISENABLEDPROC is_enabled;
    PFNGLENABLEPROC enable;
    PFNGLDISABLEPROC disable;
    PFNGLGETBOOLEANVPROC get_boolean;
    PFNGLCOLORMASKPROC color_mask;
    PFNGLVIEWPORTPROC viewport;
    PFNGLGENTEXTURESPROC gen_textures;
    PFNGLDELETETEXTURESPROC delete_textures;
    PFNGLBINDTEXTUREPROC bind_texture;
    PFNGLACTIVETEXTUREPROC active_texture;
    PFNGLTEXSTORAGE2DPROC tex_storage;
    PFNGLTEXPARAMETERIPROC tex_parameter;
    PFNGLBINDSAMPLERPROC bind_sampler;
    PFNGLGENFRAMEBUFFERSPROC gen_framebuffers;
    PFNGLDELETEFRAMEBUFFERSPROC delete_framebuffers;
    PFNGLBINDFRAMEBUFFERPROC bind_framebuffer;
    PFNGLFRAMEBUFFERTEXTURE2DPROC framebuffer_texture;
    PFNGLCHECKFRAMEBUFFERSTATUSPROC check_framebuffer;
    PFNGLBLITFRAMEBUFFERPROC blit;
    PFNGLCREATESHADERPROC create_shader;
    PFNGLSHADERSOURCEPROC shader_source;
    PFNGLCOMPILESHADERPROC compile_shader;
    PFNGLGETSHADERIVPROC get_shader;
    PFNGLGETSHADERINFOLOGPROC shader_log;
    PFNGLDELETESHADERPROC delete_shader;
    PFNGLCREATEPROGRAMPROC create_program;
    PFNGLATTACHSHADERPROC attach_shader;
    PFNGLLINKPROGRAMPROC link_program;
    PFNGLGETPROGRAMIVPROC get_program;
    PFNGLDELETEPROGRAMPROC delete_program;
    PFNGLUSEPROGRAMPROC use_program;
    PFNGLGETUNIFORMLOCATIONPROC uniform_location;
    PFNGLUNIFORM1IPROC uniform_int;
    PFNGLGENVERTEXARRAYSPROC gen_vertex_arrays;
    PFNGLDELETEVERTEXARRAYSPROC delete_vertex_arrays;
    PFNGLBINDVERTEXARRAYPROC bind_vertex_array;
    PFNGLDRAWARRAYSPROC draw_arrays;
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
void gl_look_up(T& out, const char* name, bool& ok) {
    out = reinterpret_cast<T>(gl_proc(name));
    if (!out) ok = false;
}

const Gl& gl() {
    static const Gl g = [] {
        Gl x{};
        bool ok = true;
        gl_look_up(x.get_integer, "glGetIntegerv", ok);
        gl_look_up(x.is_enabled, "glIsEnabled", ok);
        gl_look_up(x.enable, "glEnable", ok);
        gl_look_up(x.disable, "glDisable", ok);
        gl_look_up(x.get_boolean, "glGetBooleanv", ok);
        gl_look_up(x.color_mask, "glColorMask", ok);
        gl_look_up(x.viewport, "glViewport", ok);
        gl_look_up(x.gen_textures, "glGenTextures", ok);
        gl_look_up(x.delete_textures, "glDeleteTextures", ok);
        gl_look_up(x.bind_texture, "glBindTexture", ok);
        gl_look_up(x.active_texture, "glActiveTexture", ok);
        gl_look_up(x.tex_storage, "glTexStorage2D", ok);
        gl_look_up(x.tex_parameter, "glTexParameteri", ok);
        gl_look_up(x.bind_sampler, "glBindSampler", ok);
        gl_look_up(x.gen_framebuffers, "glGenFramebuffers", ok);
        gl_look_up(x.delete_framebuffers, "glDeleteFramebuffers", ok);
        gl_look_up(x.bind_framebuffer, "glBindFramebuffer", ok);
        gl_look_up(x.framebuffer_texture, "glFramebufferTexture2D", ok);
        gl_look_up(x.check_framebuffer, "glCheckFramebufferStatus", ok);
        gl_look_up(x.blit, "glBlitFramebuffer", ok);
        gl_look_up(x.create_shader, "glCreateShader", ok);
        gl_look_up(x.shader_source, "glShaderSource", ok);
        gl_look_up(x.compile_shader, "glCompileShader", ok);
        gl_look_up(x.get_shader, "glGetShaderiv", ok);
        gl_look_up(x.shader_log, "glGetShaderInfoLog", ok);
        gl_look_up(x.delete_shader, "glDeleteShader", ok);
        gl_look_up(x.create_program, "glCreateProgram", ok);
        gl_look_up(x.attach_shader, "glAttachShader", ok);
        gl_look_up(x.link_program, "glLinkProgram", ok);
        gl_look_up(x.get_program, "glGetProgramiv", ok);
        gl_look_up(x.delete_program, "glDeleteProgram", ok);
        gl_look_up(x.use_program, "glUseProgram", ok);
        gl_look_up(x.uniform_location, "glGetUniformLocation", ok);
        gl_look_up(x.uniform_int, "glUniform1i", ok);
        gl_look_up(x.gen_vertex_arrays, "glGenVertexArrays", ok);
        gl_look_up(x.delete_vertex_arrays, "glDeleteVertexArrays", ok);
        gl_look_up(x.bind_vertex_array, "glBindVertexArray", ok);
        gl_look_up(x.draw_arrays, "glDrawArrays", ok);
        gl_look_up(x.gen_buffers, "glGenBuffers", ok);
        gl_look_up(x.delete_buffers, "glDeleteBuffers", ok);
        gl_look_up(x.bind_buffer, "glBindBuffer", ok);
        gl_look_up(x.buffer_data, "glBufferData", ok);
        gl_look_up(x.map_buffer, "glMapBufferRange", ok);
        gl_look_up(x.unmap_buffer, "glUnmapBuffer", ok);
        gl_look_up(x.pixel_store, "glPixelStorei", ok);
        gl_look_up(x.read_pixels, "glReadPixels", ok);
        gl_look_up(x.fence, "glFenceSync", ok);
        gl_look_up(x.client_wait, "glClientWaitSync", ok);
        gl_look_up(x.delete_sync, "glDeleteSync", ok);
        x.ok = ok;
        return x;
    }();
    return g;
}

// The game's state that the capture touches, saved before it and put back after.
struct Saved {
    GLint read = 0, draw = 0, program = 0, active = 0, texture = 0, sampler = 0, vertex_array = 0, pack_buffer = 0;
    GLint viewport[4] = {0, 0, 0, 0};
    GLint pack_alignment = 4, pack_row_length = 0, pack_skip_rows = 0, pack_skip_pixels = 0;
    GLboolean mask[4] = {GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE};
    GLboolean enabled[8] = {};
};
// The switches a full-screen draw has to have off, in the order Saved keeps them.
constexpr GLenum kSwitches[8] = {GL_SCISSOR_TEST, GL_BLEND, GL_DEPTH_TEST, GL_STENCIL_TEST, GL_CULL_FACE, GL_RASTERIZER_DISCARD,
                                 GL_SAMPLE_ALPHA_TO_COVERAGE, GL_SAMPLE_COVERAGE};

void save_state(const Gl& g, Saved& s) {
    g.get_integer(GL_READ_FRAMEBUFFER_BINDING, &s.read);
    g.get_integer(GL_DRAW_FRAMEBUFFER_BINDING, &s.draw);
    g.get_integer(GL_CURRENT_PROGRAM, &s.program);
    g.get_integer(GL_ACTIVE_TEXTURE, &s.active);
    g.active_texture(GL_TEXTURE0);
    g.get_integer(GL_TEXTURE_BINDING_2D, &s.texture);
    g.get_integer(GL_SAMPLER_BINDING, &s.sampler);
    g.get_integer(GL_VERTEX_ARRAY_BINDING, &s.vertex_array);
    g.get_integer(GL_PIXEL_PACK_BUFFER_BINDING, &s.pack_buffer);
    g.get_integer(GL_VIEWPORT, s.viewport);
    g.get_integer(GL_PACK_ALIGNMENT, &s.pack_alignment);
    g.get_integer(GL_PACK_ROW_LENGTH, &s.pack_row_length);
    g.get_integer(GL_PACK_SKIP_ROWS, &s.pack_skip_rows);
    g.get_integer(GL_PACK_SKIP_PIXELS, &s.pack_skip_pixels);
    g.get_boolean(GL_COLOR_WRITEMASK, s.mask);
    for (int i = 0; i < 8; ++i) s.enabled[i] = g.is_enabled(kSwitches[i]);
}

void restore_state(const Gl& g, const Saved& s) {
    for (int i = 0; i < 8; ++i) {
        if (s.enabled[i]) g.enable(kSwitches[i]);
        else g.disable(kSwitches[i]);
    }
    g.color_mask(s.mask[0], s.mask[1], s.mask[2], s.mask[3]);
    g.pixel_store(GL_PACK_ALIGNMENT, s.pack_alignment);
    g.pixel_store(GL_PACK_ROW_LENGTH, s.pack_row_length);
    g.pixel_store(GL_PACK_SKIP_ROWS, s.pack_skip_rows);
    g.pixel_store(GL_PACK_SKIP_PIXELS, s.pack_skip_pixels);
    g.viewport(s.viewport[0], s.viewport[1], s.viewport[2], s.viewport[3]);
    g.bind_buffer(GL_PIXEL_PACK_BUFFER, static_cast<GLuint>(s.pack_buffer));
    g.bind_vertex_array(static_cast<GLuint>(s.vertex_array));
    g.bind_sampler(0, static_cast<GLuint>(s.sampler));
    g.bind_texture(GL_TEXTURE_2D, static_cast<GLuint>(s.texture));
    g.active_texture(static_cast<GLenum>(s.active));
    g.use_program(static_cast<GLuint>(s.program));
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, static_cast<GLuint>(s.read));
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, static_cast<GLuint>(s.draw));
}

// The conversion to NV12, one draw for each plane. A texel of the luma target holds four luma samples of a row, and
// one of the chroma target two pairs of Cb and Cr, each from a 2x2 block: read back as RGBA bytes, they are NV12's rows
// as they are. The scaled picture is twice the stream's size where the frame is that large (`scale`), and each of the
// stream's pixels the average of its 2x2 block: a blit alone scales by sampling, which shimmers on a frame three times
// larger. The rows go top to bottom, as the encoder wants them: GL's first row is the picture's last. BT.709, in the
// limited range video uses.
const char* kVertex = R"(#version 300 es
void main() {
    // One triangle over the whole target, from the vertex's number alone: no buffers.
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
)";
const char* kFragment = R"(#version 300 es
precision highp float;
precision highp int;
uniform highp sampler2D picture;
uniform int chroma;
uniform int scale;
out vec4 color;
const vec3 kY = vec3(0.2126, 0.7152, 0.0722);
// The stream's pixel (x, y), y from the top: the average of its block of the scaled picture.
vec3 pixel(int x, int y) {
    int top = textureSize(picture, 0).y - 1;
    vec3 sum = vec3(0.0);
    for (int j = 0; j < scale; ++j)
        for (int i = 0; i < scale; ++i)
            sum += texelFetch(picture, ivec2(x * scale + i, top - (y * scale + j)), 0).rgb;
    return sum / float(scale * scale);
}
float luma(vec3 c) { return (16.0 + 219.0 * dot(c, kY)) / 255.0; }
vec2 chromas(vec3 c) {
    float y = dot(c, kY);
    return (vec2(128.0) + 224.0 * vec2((c.b - y) / 1.8556, (c.r - y) / 1.5748)) / 255.0;
}
void main() {
    ivec2 o = ivec2(gl_FragCoord.xy);
    int x = o.x * 4;
    if (chroma == 0) {
        color = vec4(luma(pixel(x, o.y)), luma(pixel(x + 1, o.y)), luma(pixel(x + 2, o.y)), luma(pixel(x + 3, o.y)));
    } else {
        int y = o.y * 2;
        vec3 a = (pixel(x, y) + pixel(x + 1, y) + pixel(x, y + 1) + pixel(x + 1, y + 1)) * 0.25;
        vec3 b = (pixel(x + 2, y) + pixel(x + 3, y) + pixel(x + 2, y + 1) + pixel(x + 3, y + 1)) * 0.25;
        color = vec4(chromas(a), chromas(b));
    }
}
)";

GLuint compile(const Gl& g, GLenum kind, const char* text) {
    GLuint shader = g.create_shader(kind);
    g.shader_source(shader, 1, &text, nullptr);
    g.compile_shader(shader);
    GLint ok = 0;
    g.get_shader(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char why[512] = "";
        g.shader_log(shader, sizeof why, nullptr, why);
        log("player: live: the conversion's shader does not compile: %s", why);
        g.delete_shader(shader);
        return 0;
    }
    return shader;
}

struct Slot {
    // The pixel buffers the picture is read into, one per plane: luma, then the chroma pairs. ANGLE copies a read into a
    // pixel buffer to a staging texture of the read's size and packs it into the buffer when the buffer is mapped; a
    // second read into the same buffer would make it wait for the GPU to finish the first right there, and the other
    // plane's size would make it a new staging texture each time.
    GLuint buffer = 0, chroma_buffer = 0;
    GLsync fence = nullptr; // done on the GPU once this signals
    Nanos pts = 0;
    bool busy = false;
};

struct Capture {
    EGLContext context = EGL_NO_CONTEXT;
    EGLSurface surface = EGL_NO_SURFACE;
    int source_width = 0, source_height = 0;
    int width = 0, height = 0, fps = 0;
    int scale = 1;  // the scaled picture's pixels per stream pixel, each way: 2 where the frame is that large
    GLuint picture = 0, picture_fbo = 0, luma = 0, luma_fbo = 0, chroma = 0, chroma_fbo = 0, program = 0, vertex_array = 0;
    GLint chroma_uniform = -1;
    Slot slots[kSlots];
    int next_slot = 0;
    Nanos next_due = 0, last_picture = 0, retry_at = 0;
    bool live = false;
    // What begin_capture took on the render thread, and of it the conversion's program (0: made before), until the
    // first picture is taken and the start's cost goes in the stats.
    Nanos setup_ns = 0, program_ns = 0;
    bool first = false;
} g_capture;

// The conversion's program and vertex array, kept for the context's life: made again only with another context, so a
// capture that starts over (a quality step mid-song, a resize) compiles nothing on the render thread, where a compile
// shows as a stutter. The capture's own fields name the same objects without owning them.
struct Conversion {
    EGLContext context = EGL_NO_CONTEXT;
    GLuint program = 0, vertex_array = 0;
    GLint scale_uniform = -1, chroma_uniform = -1;
} g_conversion;

// A context the game has destroyed, until the render thread has seen it: a new one can get the same address, and the
// names of the old one's objects would then be the game's own.
std::atomic<void*> g_destroyed_context{nullptr};

// The picture's size: the height asked for, the frame's shape, in steps of 8 pixels (1920x1080, 1280x720, 856x480 for a
// 16:9 frame). Windows' encoder takes any even size and pads to its 16-pixel blocks itself, telling the decoder to crop:
// 1080 lines stay 1080, where 16-pixel steps would stretch them to 1088. The conversion packs four pixels a texel.
void picture_size(int source_width, int source_height, int height, int* width_out, int* height_out) {
    const int h = (height + 4) / 8 * 8;
    int w = static_cast<int>((static_cast<std::int64_t>(source_width) * h + source_height / 2) / source_height);
    w = (w + 4) / 8 * 8;
    *width_out = std::max(w, 16);
    *height_out = std::max(h, 16);
}

// The capture's objects gone, in its own context; outside it they went with the context.
void end_capture(Capture& c, bool context_is_current) {
    if (context_is_current) {
        const Gl& g = gl();
        for (Slot& s : c.slots) {
            if (s.fence) g.delete_sync(s.fence);
            if (s.buffer) g.delete_buffers(1, &s.buffer);
            if (s.chroma_buffer) g.delete_buffers(1, &s.chroma_buffer);
        }
        GLuint fbos[3] = {c.picture_fbo, c.luma_fbo, c.chroma_fbo};
        g.delete_framebuffers(3, fbos);
        GLuint textures[3] = {c.picture, c.luma, c.chroma};
        g.delete_textures(3, textures);
    }
    // The program and the vertex array stay (g_conversion).
    c = Capture{};
}

// A texture of `width` x `height` RGBA bytes, with a framebuffer drawing into it. False when the driver will not.
bool target(const Gl& g, int width, int height, GLuint* texture, GLuint* fbo) {
    g.gen_textures(1, texture);
    g.bind_texture(GL_TEXTURE_2D, *texture);
    g.tex_storage(GL_TEXTURE_2D, 1, GL_RGBA8, width, height);
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    g.gen_framebuffers(1, fbo);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, *fbo);
    g.framebuffer_texture(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, *texture, 0);
    return g.check_framebuffer(GL_DRAW_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
}

// The conversion's program and vertex array in `context`, the current one, unless they are there already: made once and
// kept for the context's life (g_conversion; a context before this one took its own along). The program in use changes
// (the caller has the game's saved). What it took, 0 when they were there.
Nanos make_conversion(const Gl& g, EGLContext context) {
    Conversion& v = g_conversion;
    if (v.context == context && v.program) return 0;
    const Nanos began = now_ns();
    v = Conversion{};
    GLuint vertex = compile(g, GL_VERTEX_SHADER, kVertex);
    GLuint fragment = vertex ? compile(g, GL_FRAGMENT_SHADER, kFragment) : 0;
    if (vertex && fragment) {
        v.program = g.create_program();
        g.attach_shader(v.program, vertex);
        g.attach_shader(v.program, fragment);
        g.link_program(v.program);
        GLint linked = 0;
        g.get_program(v.program, GL_LINK_STATUS, &linked);
        if (linked) {
            g.use_program(v.program);
            g.uniform_int(g.uniform_location(v.program, "picture"), 0);
            v.scale_uniform = g.uniform_location(v.program, "scale");
            v.chroma_uniform = g.uniform_location(v.program, "chroma");
            g.gen_vertex_arrays(1, &v.vertex_array);
            v.context = context;
        } else {
            g.delete_program(v.program);
            v.program = 0;
        }
    }
    if (vertex) g.delete_shader(vertex);
    if (fragment) g.delete_shader(fragment);
    return now_ns() - began;
}

// The conversion's program made ahead, as soon as the server has answered (control_main), which is at the game's title as
// a rule, about a second before a broadcast the server already has on could start: a broadcast that starts later,
// perhaps in a song, then has no compiling to do on this thread (under Wine the program was 762 of the first start's
// 763 ms). False when it cannot be made at this swap (no context current, another surface): the next swap tries again.
bool warm_up(EGLDisplay d, EGLSurface s, EGLContext context, EGLSurface drawn) {
    if (context == EGL_NO_CONTEXT || drawn != s) return false;
    // The program is OpenGL ES 3's: on a context of another version a capture says why it cannot start.
    static auto query_context = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLContext, EGLint, EGLint*)>(egl_proc("eglQueryContext"));
    EGLint version = 0;
    if (query_context) query_context(d, context, EGL_CONTEXT_CLIENT_VERSION, &version);
    if (version < 3) return true;
    const Gl& g = gl();
    // The game's state as it was after: the program in use is all the making changes of it.
    Saved saved;
    save_state(g, saved);
    const Nanos took = make_conversion(g, context);
    restore_state(g, saved);
    log("player: live: the conversion's program made ahead of a broadcast: %llu us on the render thread", static_cast<unsigned long long>(took / 1000));
    return true;
}

// The capture's objects in the game's context, for pictures of the stream's size. The game's state as it was after.
bool begin_capture(Capture& c, EGLDisplay d, EGLContext context, EGLSurface s, int source_width, int source_height, Nanos now) {
    const Gl& g = gl();
    // A blit that scales takes OpenGL ES 3, and a frame without multisampling.
    static auto query_context = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLContext, EGLint, EGLint*)>(egl_proc("eglQueryContext"));
    static auto query_surface = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint, EGLint*)>(egl_proc("eglQuerySurface"));
    static auto choose_config = reinterpret_cast<EGLBoolean (*)(EGLDisplay, const EGLint*, EGLConfig*, EGLint, EGLint*)>(egl_proc("eglChooseConfig"));
    static auto config_attrib = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLConfig, EGLint, EGLint*)>(egl_proc("eglGetConfigAttrib"));
    EGLint version = 0, samples = 0, config_id = 0, found = 0;
    if (query_context) query_context(d, context, EGL_CONTEXT_CLIENT_VERSION, &version);
    EGLConfig config = nullptr;
    if (query_surface) query_surface(d, s, EGL_CONFIG_ID, &config_id);
    const EGLint by_id[] = {EGL_CONFIG_ID, config_id, EGL_NONE};
    if (choose_config && config_attrib && choose_config(d, by_id, &config, 1, &found) && found == 1) config_attrib(d, config, EGL_SAMPLE_BUFFERS, &samples);
    if (version < 3 || samples != 0) {
        log("player: live: the game's context is not usable (ES %d, %d sample buffers)", version, samples);
        g_gave_up.store(true);
        return false;
    }
    // From here the start's own cost on this thread, for the stats.
    const Nanos began = now_ns();
    Nanos program_ns = 0;
    Saved saved;
    save_state(g, saved);
    c.context = context;
    c.surface = s;
    c.source_width = source_width;
    c.source_height = source_height;
    picture_size(source_width, source_height, step_height(step()), &c.width, &c.height);
    c.fps = step_fps(step());
    c.scale = source_width >= c.width * 2 && source_height >= c.height * 2 ? 2 : 1;
    bool ok = target(g, c.width * c.scale, c.height * c.scale, &c.picture, &c.picture_fbo);
    ok = ok && target(g, c.width / 4, c.height, &c.luma, &c.luma_fbo);
    ok = ok && target(g, c.width / 4, c.height / 2, &c.chroma, &c.chroma_fbo);
    // The program, unless warm_up or a capture before made it in this context.
    if (ok) program_ns = make_conversion(g, context);
    Conversion& v = g_conversion;
    ok = ok && v.context == context && v.program;
    if (ok) {
        // This capture's scale, set in the program (its state, restored with the rest below).
        g.use_program(v.program);
        g.uniform_int(v.scale_uniform, c.scale);
        c.program = v.program;
        c.vertex_array = v.vertex_array;
        c.chroma_uniform = v.chroma_uniform;
    }
    // The pixel buffers, a plane of one NV12 picture each, read back by the CPU.
    const auto luma_bytes = static_cast<GLsizeiptr>(c.width) * c.height;
    for (Slot& slot : c.slots) {
        g.gen_buffers(1, &slot.buffer);
        g.bind_buffer(GL_PIXEL_PACK_BUFFER, slot.buffer);
        g.buffer_data(GL_PIXEL_PACK_BUFFER, luma_bytes, nullptr, GL_STREAM_READ);
        g.gen_buffers(1, &slot.chroma_buffer);
        g.bind_buffer(GL_PIXEL_PACK_BUFFER, slot.chroma_buffer);
        g.buffer_data(GL_PIXEL_PACK_BUFFER, luma_bytes / 2, nullptr, GL_STREAM_READ);
    }
    restore_state(g, saved);
    if (!ok) {
        log("player: live: the picture's conversion cannot be set up here");
        end_capture(c, true);
        g_gave_up.store(true);
        return false;
    }
    c.next_due = now;
    c.last_picture = now;
    c.live = true;
    // Its cost so far; the first picture's is added when it is taken (desktop_live_frame).
    c.setup_ns = now_ns() - began;
    c.program_ns = program_ns;
    c.first = true;
    return true;
}

// This frame into the next free slot: scaled, converted and read into its pixel buffer, none of it waited for.
void take_picture(Capture& c, Nanos now) {
    const Gl& g = gl();
    Slot& slot = c.slots[c.next_slot];
    if (slot.busy) {
        // The encoder side is behind: this picture is left out.
        g_skipped.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    // Each phase's time, for the stats (g_phase_ns): the clock read between them.
    Nanos mark = now_ns();
    auto phase = [&mark](int i) {
        const Nanos t = now_ns();
        g_phase_ns[i].fetch_add(static_cast<std::uint64_t>(t - mark), std::memory_order_relaxed);
        mark = t;
    };
    g_phase_ns[0].fetch_add(static_cast<std::uint64_t>(mark - now), std::memory_order_relaxed);
    Saved saved;
    save_state(g, saved);
    for (GLenum s : kSwitches) g.disable(s);
    g.color_mask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    phase(1);
    // The frame as it goes to the screen, scaled to the stream's size.
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, 0);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, c.picture_fbo);
    g.blit(0, 0, c.source_width, c.source_height, 0, 0, c.width * c.scale, c.height * c.scale, GL_COLOR_BUFFER_BIT, GL_LINEAR);
    phase(2);
    // Its two planes.
    g.use_program(c.program);
    g.bind_vertex_array(c.vertex_array);
    g.active_texture(GL_TEXTURE0);
    g.bind_texture(GL_TEXTURE_2D, c.picture);
    g.bind_sampler(0, 0);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, c.luma_fbo);
    g.viewport(0, 0, c.width / 4, c.height);
    g.uniform_int(c.chroma_uniform, 0);
    g.draw_arrays(GL_TRIANGLES, 0, 3);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, c.chroma_fbo);
    g.viewport(0, 0, c.width / 4, c.height / 2);
    g.uniform_int(c.chroma_uniform, 1);
    g.draw_arrays(GL_TRIANGLES, 0, 3);
    phase(3);
    // Each plane into its own buffer of the slot: NV12 once they are put one after the other.
    g.pixel_store(GL_PACK_ALIGNMENT, 4);
    g.pixel_store(GL_PACK_ROW_LENGTH, 0);
    g.pixel_store(GL_PACK_SKIP_ROWS, 0);
    g.pixel_store(GL_PACK_SKIP_PIXELS, 0);
    g.bind_buffer(GL_PIXEL_PACK_BUFFER, slot.buffer);
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, c.luma_fbo);
    g.read_pixels(0, 0, c.width / 4, c.height, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    g.bind_buffer(GL_PIXEL_PACK_BUFFER, slot.chroma_buffer);
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, c.chroma_fbo);
    g.read_pixels(0, 0, c.width / 4, c.height / 2, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    phase(4);
    slot.fence = g.fence(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
    phase(5);
    slot.pts = now;
    slot.busy = true;
    c.next_slot = (c.next_slot + 1) % kSlots;
    restore_state(g, saved);
    phase(6);
    c.last_picture = now;
}

// The slots the GPU is done with, oldest first, copied out for the encoder. A slot still on the GPU ends the round:
// the ones after it are later still.
void collect(Capture& c) {
    const Gl& g = gl();
    for (int n = 0; n < kSlots; ++n) {
        Slot& slot = c.slots[(c.next_slot + n) % kSlots];
        if (!slot.busy) continue;
        const GLenum state = g.client_wait(slot.fence, GL_SYNC_FLUSH_COMMANDS_BIT, 0);
        if (state != GL_ALREADY_SIGNALED && state != GL_CONDITION_SATISFIED) return;
        const Nanos began = now_ns();
        g.delete_sync(slot.fence);
        slot.fence = nullptr;
        slot.busy = false;
        GLint bound = 0;
        g.get_integer(GL_PIXEL_PACK_BUFFER_BINDING, &bound);
        const std::size_t luma = static_cast<std::size_t>(c.width) * static_cast<std::size_t>(c.height);
        Frame f;
        {
            // A buffer the encoder gave back, when there is one: its pages are the process's already.
            std::lock_guard<std::mutex> l(g_frame_lock);
            if (!g_spare.empty()) {
                f.nv12 = std::move(g_spare.back());
                g_spare.pop_back();
            }
        }
        // Luma, then the chroma pairs after it: NV12.
        f.nv12.resize(luma + luma / 2);
        bool whole = true;
        const GLuint planes[2] = {slot.buffer, slot.chroma_buffer};
        const std::size_t offsets[2] = {0, luma}, sizes[2] = {luma, luma / 2};
        for (int p = 0; p < 2; ++p) {
            g.bind_buffer(GL_PIXEL_PACK_BUFFER, planes[p]);
            const void* mapped = g.map_buffer(GL_PIXEL_PACK_BUFFER, 0, static_cast<GLsizeiptr>(sizes[p]), GL_MAP_READ_BIT);
            if (!mapped) {
                whole = false;
                break;
            }
            std::memcpy(f.nv12.data() + offsets[p], mapped, sizes[p]);
            g.unmap_buffer(GL_PIXEL_PACK_BUFFER);
        }
        if (whole) {
            f.width = c.width;
            f.height = c.height;
            f.pts = slot.pts;
            std::lock_guard<std::mutex> l(g_frame_lock);
            // The encoder is behind: the oldest picture goes, its buffer kept.
            if (g_frames.size() >= kFrameQueue) {
                recycle(std::move(g_frames.front().nv12));
                g_frames.pop_front();
                g_skipped.fetch_add(1, std::memory_order_relaxed);
                g_encoder_behind.fetch_add(1, std::memory_order_relaxed);
            }
            g_frames.push_back(std::move(f));
            g_frame_wake.notify_one();
        }
        g.bind_buffer(GL_PIXEL_PACK_BUFFER, static_cast<GLuint>(bound));
        // What handing it over took on this thread.
        const auto took = static_cast<std::uint64_t>(now_ns() - began);
        g_handed.fetch_add(1, std::memory_order_relaxed);
        g_hand_ns.fetch_add(took, std::memory_order_relaxed);
        if (took > g_hand_max_ns.load(std::memory_order_relaxed)) g_hand_max_ns.store(took, std::memory_order_relaxed);
    }
}

}  // namespace

}  // namespace arm32::desktop_live

namespace arm32 {

void desktop_live_frame(EGLDisplay d, EGLSurface s) {
    // The broadcast's own names (live_state.h, and this file's).
    using namespace desktop_live;
    static const bool ready = set_up();
    if (!ready) return;
    g_enabled.store(true, std::memory_order_relaxed);
    const Nanos start = now_ns();
    g_last_swap.store(start, std::memory_order_relaxed);
    Capture& c = g_capture;
    // A context the game destroyed took the program along: made again in the next one. Looked at every swap, before
    // anything else: the program may be made ahead (warm_up) with no broadcast, and a second context destroyed before the
    // next look would hide the first, whose address a new context could get.
    if (void* dead = g_destroyed_context.load(std::memory_order_relaxed)) {
        if (dead == g_conversion.context) g_conversion = Conversion{};
        // With no capture to end, nothing else waits for it: a new context at the same address is a new one.
        if (!c.live) g_destroyed_context.store(nullptr, std::memory_order_relaxed);
    }
    const bool want = g_want.load(std::memory_order_relaxed);
    // The conversion's program to make ahead of any broadcast (warm_up), once.
    const bool warm = g_warm_due.load(std::memory_order_relaxed);
    // The usual case, by far.
    if (!want && !c.live && !warm) return;
    if (!gl().ok) {
        // Nothing to make the program with: nothing to make ahead either.
        g_warm_due.store(false, std::memory_order_relaxed);
        return;
    }
    static auto current_context = reinterpret_cast<EGLContext (*)()>(egl_proc("eglGetCurrentContext"));
    static auto current_surface = reinterpret_cast<EGLSurface (*)(EGLint)>(egl_proc("eglGetCurrentSurface"));
    static auto query_surface = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint, EGLint*)>(egl_proc("eglQuerySurface"));
    if (!current_context || !current_surface || !query_surface) return;
    const EGLContext context = current_context();
    // Made ahead while no capture runs, on the frame going to the window; a capture that runs has made it already.
    if (warm && (c.live || warm_up(d, s, context, current_surface(EGL_DRAW)))) g_warm_due.store(false, std::memory_order_relaxed);
    if (!want && !c.live) return;
    if (c.live) {
        // Each of these means this capture is over: a new one follows at a later frame if wanted.
        const bool gone = g_destroyed_context.load(std::memory_order_relaxed) == c.context;
        if (gone) g_destroyed_context.store(nullptr, std::memory_order_relaxed);
        const bool same_context = context == c.context && !gone;
        EGLint w = 0, h = 0;
        if (s == c.surface) {
            query_surface(d, s, EGL_WIDTH, &w);
            query_surface(d, s, EGL_HEIGHT, &h);
        }
        int picture_w = 0, picture_h = 0;
        picture_size(c.source_width, c.source_height, step_height(step()), &picture_w, &picture_h);
        if (!want || !same_context || s != c.surface || w != c.source_width || h != c.source_height || picture_h != c.height ||
            c.fps != step_fps(step()) || start - c.last_picture > kRestartAfter) {
            end_capture(c, same_context);
            return;
        }
        // What the GPU has finished, out to the encoder.
        collect(c);
    }
    if (!c.live) {
        if (!want || start < c.retry_at || g_gave_up.load(std::memory_order_relaxed)) return;
        // Only the frame going to the window, drawn on the current context.
        if (context == EGL_NO_CONTEXT || current_surface(EGL_DRAW) != s) return;
        EGLint w = 0, h = 0;
        query_surface(d, s, EGL_WIDTH, &w);
        query_surface(d, s, EGL_HEIGHT, &h);
        if (w <= 0 || h <= 0) return;
        if (!begin_capture(c, d, context, s, w, h, start)) c.retry_at = start + 10 * kSecond;
        return;
    }
    const Nanos interval = kSecond / c.fps;
    if (start + kCaptureTolerance < c.next_due) return;
    c.next_due = std::max(c.next_due + interval, start);
    take_picture(c, start);
    const std::uint64_t took = static_cast<std::uint64_t>(now_ns() - start);
    g_captures.fetch_add(1, std::memory_order_relaxed);
    g_capture_ns.fetch_add(took, std::memory_order_relaxed);
    if (took > g_capture_max_ns.load(std::memory_order_relaxed)) g_capture_max_ns.store(took, std::memory_order_relaxed);
    if (c.first) {
        // The start's whole cost on this thread, its objects and its first picture, in the stats and once in the log: a
        // start can come in the middle of a song, when the server's owner turns the broadcast on.
        c.first = false;
        const auto cost = static_cast<std::uint64_t>(c.setup_ns) + took;
        g_starts.fetch_add(1, std::memory_order_relaxed);
        if (cost > g_start_max_ns.load(std::memory_order_relaxed)) g_start_max_ns.store(cost, std::memory_order_relaxed);
        log("player: live: a capture started on the render thread: %llu us for its objects (%llu us of it the conversion's program), %llu us "
            "for its first picture",
            static_cast<unsigned long long>(c.setup_ns / 1000), static_cast<unsigned long long>(c.program_ns / 1000),
            static_cast<unsigned long long>(took / 1000));
    }
}

// The game destroyed a context (egl_bridge.cpp, through live_context_destroyed in frames.cpp).
void desktop_live_context_destroyed(EGLContext context) { desktop_live::g_destroyed_context.store(context, std::memory_order_relaxed); }

}  // namespace arm32
