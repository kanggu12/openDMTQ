// The game's frames in a framebuffer of our own (offscreen.h says why). The game draws to its window through the
// default framebuffer, framebuffer 0; while a computer player redirects them, every GL call of the game's that names or
// reads framebuffer 0 reaches this file instead, and 0 stands for the offscreen framebuffer of the context:
//
//   glBindFramebuffer (every target)              0 binds the offscreen framebuffer
//   glGetIntegerv / Integer64v / Floatv / Booleanv the bindings answer 0 for it, its read and draw buffer GL_BACK, and
//                                                 its samples the window config's
//   glReadPixels, glReadnPixels(EXT/KHR),         read the frame (resolved first when it is multisampled, which GL
//   glCopyTex(Sub)Image2D/3D, glBlitFramebuffer   cannot read from directly where the window's could be read)
//   glInvalidate(Sub)Framebuffer,                 GL_COLOR, GL_DEPTH and GL_STENCIL become the framebuffer's
//   glDiscardFramebufferEXT                       attachments, which a framebuffer object names instead
//   glDrawBuffers(EXT), glReadBuffer              GL_BACK becomes its colour attachment
//   glFramebufferTexture*, glFramebufferRenderbuffer, glFramebufferParameteri,
//   glGetFramebufferAttachmentParameteriv, glGetFramebufferParameteriv
//                                                 asked of the real framebuffer 0, bound for the call: attaching to it
//                                                 is the error it always was, and its attachments' formats are the
//                                                 window's, as the game's config chose them
//   glCheckFramebufferStatus                      (generated, unchanged) the offscreen framebuffer is complete, as
//                                                 the window's is
//
// and eglQuerySurface answers the size the game draws at (egl_bridge.cpp). At the swap the frame goes to the window's own
// framebuffer through the player's passes (desktop/post_pass.cpp). Our own GL calls go to the host's functions directly,
// past the bridge, and see the real names.
#include "offscreen.h"

#include "gl_bridge.h"
#include "pacing.h"

#include <dlfcn.h>
#include <mutex>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#define GL_GLEXT_PROTOTYPES 1
#include <GLES3/gl32.h>
#include <GLES2/gl2ext.h>

namespace arm32 {

std::atomic<bool> g_offscreen{false};
std::atomic<bool> g_offscreen_window_size{false};
std::atomic<int> g_offscreen_samples{0};
std::atomic<bool> g_offscreen_es31{false};
std::atomic<OffscreenPresent> g_offscreen_present{nullptr};

namespace {

// A host EGL entry point by name (ANGLE's on Windows), looked up once by each caller.
void* egl_fn(const char* name) {
    static void* lib = dlopen(kHostEgl, RTLD_NOW | RTLD_LOCAL);
    return lib ? dlsym(lib, name) : nullptr;
}

// The host's GL entry points this file calls itself, looked up once.
struct Gl {
    PFNGLGETINTEGERVPROC get_integer;
    PFNGLBINDFRAMEBUFFERPROC bind_framebuffer;
    PFNGLGENFRAMEBUFFERSPROC gen_framebuffers;
    PFNGLDELETEFRAMEBUFFERSPROC delete_framebuffers;
    PFNGLFRAMEBUFFERTEXTURE2DPROC framebuffer_texture;
    PFNGLFRAMEBUFFERRENDERBUFFERPROC framebuffer_renderbuffer;
    PFNGLCHECKFRAMEBUFFERSTATUSPROC check_framebuffer;
    PFNGLGENTEXTURESPROC gen_textures;
    PFNGLDELETETEXTURESPROC delete_textures;
    PFNGLBINDTEXTUREPROC bind_texture;
    PFNGLTEXSTORAGE2DPROC tex_storage;
    PFNGLTEXPARAMETERIPROC tex_parameter;
    PFNGLGENRENDERBUFFERSPROC gen_renderbuffers;
    PFNGLDELETERENDERBUFFERSPROC delete_renderbuffers;
    PFNGLBINDRENDERBUFFERPROC bind_renderbuffer;
    PFNGLRENDERBUFFERSTORAGEMULTISAMPLEPROC renderbuffer_storage;
    PFNGLGETINTERNALFORMATIVPROC internalformat;
    PFNGLBLITFRAMEBUFFERPROC blit;
    PFNGLISENABLEDPROC is_enabled;
    PFNGLENABLEPROC enable;
    PFNGLDISABLEPROC disable;
    PFNGLGETBOOLEANVPROC get_boolean;
    PFNGLCOLORMASKPROC color_mask;
    PFNGLVIEWPORTPROC viewport;
    PFNGLSCISSORPROC scissor;
    PFNGLCLEARCOLORPROC clear_color;
    PFNGLCLEARPROC clear;
    bool ok = false;
};

// One entry point into `out`, and `ok` false when the host has none.
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
        look_up(x.bind_framebuffer, "glBindFramebuffer", ok);
        look_up(x.gen_framebuffers, "glGenFramebuffers", ok);
        look_up(x.delete_framebuffers, "glDeleteFramebuffers", ok);
        look_up(x.framebuffer_texture, "glFramebufferTexture2D", ok);
        look_up(x.framebuffer_renderbuffer, "glFramebufferRenderbuffer", ok);
        look_up(x.check_framebuffer, "glCheckFramebufferStatus", ok);
        look_up(x.gen_textures, "glGenTextures", ok);
        look_up(x.delete_textures, "glDeleteTextures", ok);
        look_up(x.bind_texture, "glBindTexture", ok);
        look_up(x.tex_storage, "glTexStorage2D", ok);
        look_up(x.tex_parameter, "glTexParameteri", ok);
        look_up(x.gen_renderbuffers, "glGenRenderbuffers", ok);
        look_up(x.delete_renderbuffers, "glDeleteRenderbuffers", ok);
        look_up(x.bind_renderbuffer, "glBindRenderbuffer", ok);
        look_up(x.renderbuffer_storage, "glRenderbufferStorageMultisample", ok);
        look_up(x.internalformat, "glGetInternalformativ", ok);
        look_up(x.blit, "glBlitFramebuffer", ok);
        look_up(x.is_enabled, "glIsEnabled", ok);
        look_up(x.enable, "glEnable", ok);
        look_up(x.disable, "glDisable", ok);
        look_up(x.get_boolean, "glGetBooleanv", ok);
        look_up(x.color_mask, "glColorMask", ok);
        look_up(x.viewport, "glViewport", ok);
        look_up(x.scissor, "glScissor", ok);
        look_up(x.clear_color, "glClearColor", ok);
        look_up(x.clear, "glClear", ok);
        x.ok = ok;
        return x;
    }();
    return g;
}

// The window surface whose frames are redirected, and the config it was made with (one at a time: the game has one
// window). Set and read under the lock: the game's threads may make and destroy surfaces apart from its render thread.
std::mutex g_lock;
EGLSurface g_surface = EGL_NO_SURFACE;
EGLConfig g_config = nullptr;

// A context's offscreen framebuffer: framebuffer objects are a context's own (shared contexts share textures and
// renderbuffers, not framebuffers), so each context the game draws to the window with has one.
struct Target {
    EGLContext context = EGL_NO_CONTEXT;
    EGLSurface surface = EGL_NO_SURFACE;  // the redirected surface it draws for now
    GLuint fbo = 0;          // the framebuffer that stands for 0
    GLuint color = 0;        // its colour as a texture, or, with MSAA, the resolved frame's
    GLuint ms_color = 0;     // with MSAA: the multisampled colour renderbuffer the game draws into
    GLuint depth = 0;        // the depth and stencil renderbuffer, when the window config has either
    GLuint resolve_fbo = 0;  // with MSAA: the framebuffer of `color`, the resolve's target
    int width = 0, height = 0, samples = 0;
    GLenum color_format = GL_RGBA8;  // the window config's colour: RGB8 without alpha, RGBA8 with it
    GLenum depth_format = 0;         // its depth and stencil (0: none)
    EGLint config_samples = 0, config_sample_buffers = 0;  // the window config's own, which the game is told
};
// The targets by context, made at the first redirected make-current of each; the contexts seen at all, whose initial
// viewport the first make-current set.
std::unordered_map<EGLContext, Target> g_targets;
std::unordered_set<EGLContext> g_seen_contexts;
// The target of the context current on this thread while it draws to the redirected surface; null otherwise (always on a
// phone). The framebuffer calls below look only at this, one thread-local load.
thread_local Target* t_target = nullptr;

// The framebuffer object standing for 0 on this thread (0: none, the calls pass through).
GLuint stand_in() { return t_target ? t_target->fbo : 0; }

// The binding a framebuffer target reads (GL_FRAMEBUFFER is the draw binding).
GLenum binding_of(GLenum target) { return target == GL_READ_FRAMEBUFFER ? GL_READ_FRAMEBUFFER_BINDING : GL_DRAW_FRAMEBUFFER_BINDING; }

// The framebuffer bound to `target` now, by the host's own answer.
GLuint bound(GLenum target) {
    GLint v = 0;
    gl().get_integer(binding_of(target), &v);
    return static_cast<GLuint>(v);
}

// The size the game draws at for the redirected surface: the render scale's (g_window_fixed_size), else the surface's own.
void wanted_size(EGLDisplay d, EGLSurface s, int* w, int* h) {
    const std::int64_t fixed = g_window_fixed_size.load(std::memory_order_relaxed);
    if (fixed) {
        *w = static_cast<int>(fixed >> 32);
        *h = static_cast<int>(fixed & 0xffffffff);
        return;
    }
    static auto query = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint, EGLint*)>(egl_fn("eglQuerySurface"));
    EGLint qw = 0, qh = 0;
    if (query) {
        query(d, s, EGL_WIDTH, &qw);
        query(d, s, EGL_HEIGHT, &qh);
    }
    *w = qw;
    *h = qh;
}

// The most samples at most `asked` that the host draws both of the target's formats with (0: none, or none asked).
int usable_samples(const Gl& g, const Target& t, int asked) {
    if (asked <= 1) return 0;
    int best = 0;
    // The counts a format takes, highest first, as glGetInternalformativ lists them.
    auto counts = [&g](GLenum format) {
        GLint n = 0;
        g.internalformat(GL_RENDERBUFFER, format, GL_NUM_SAMPLE_COUNTS, 1, &n);
        std::vector<GLint> list(static_cast<std::size_t>(n > 0 ? n : 0));
        if (n > 0) g.internalformat(GL_RENDERBUFFER, format, GL_SAMPLES, n, list.data());
        return list;
    };
    const std::vector<GLint> color = counts(t.color_format);
    const std::vector<GLint> depth = t.depth_format ? counts(t.depth_format) : color;
    for (GLint c : color) {
        // Taken when the depth format has the same count too, and it is no more than asked.
        if (c > asked || c <= best) continue;
        for (GLint d : depth) if (d == c) best = c;
    }
    return best;
}

// The target's objects gone (its context current), its names cleared.
void free_objects(const Gl& g, Target& t) {
    GLuint fbos[2] = {t.fbo, t.resolve_fbo};
    g.delete_framebuffers(2, fbos);
    g.delete_textures(1, &t.color);
    GLuint rbs[2] = {t.ms_color, t.depth};
    g.delete_renderbuffers(2, rbs);
    t.fbo = t.color = t.ms_color = t.depth = t.resolve_fbo = 0;
}

// The target's objects for `w` x `h`, made in its context (current), with the game's texture, renderbuffer and
// framebuffer bindings as they were. Its framebuffer is complete, or false and nothing made.
bool make_objects(const Gl& g, Target& t, int w, int h) {
    GLint was_texture = 0, was_renderbuffer = 0;
    g.get_integer(GL_TEXTURE_BINDING_2D, &was_texture);
    g.get_integer(GL_RENDERBUFFER_BINDING, &was_renderbuffer);
    const GLuint was_draw = bound(GL_DRAW_FRAMEBUFFER);
    // The samples asked for, as the host can draw them; said once each time it changes.
    const int asked = g_offscreen_samples.load(std::memory_order_relaxed);
    const int samples = usable_samples(g, t, asked);
    static int said = -1;
    if (asked > 1 && said != samples) {
        if (samples == asked) log("arm32: anti-aliasing: MSAA %dx", samples);
        else if (samples) log("arm32: anti-aliasing: MSAA %dx asked, %dx is the most this graphics card draws: MSAA %dx", asked, samples, samples);
        else log("arm32: anti-aliasing: MSAA %dx asked, none here (no multisampled renderbuffers): off", asked);
        said = samples;
    }
    // The frame's colour as a texture, which the passes sample: the game's frame itself, or the resolve's target.
    g.gen_textures(1, &t.color);
    g.bind_texture(GL_TEXTURE_2D, t.color);
    g.tex_storage(GL_TEXTURE_2D, 1, t.color_format, w, h);
    // Linear: a plain blit or a pass may sample between its pixels.
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    g.gen_framebuffers(1, &t.fbo);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, t.fbo);
    if (samples) {
        // MSAA: the game draws into multisampled colour, resolved into the texture through a framebuffer of its own.
        g.gen_renderbuffers(1, &t.ms_color);
        g.bind_renderbuffer(GL_RENDERBUFFER, t.ms_color);
        g.renderbuffer_storage(GL_RENDERBUFFER, samples, t.color_format, w, h);
        g.framebuffer_renderbuffer(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, t.ms_color);
    } else {
        // One sample: the game draws into the texture itself.
        g.framebuffer_texture(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, t.color, 0);
    }
    if (t.depth_format) {
        // Depth and stencil as the window config has them, with the colour's samples.
        g.gen_renderbuffers(1, &t.depth);
        g.bind_renderbuffer(GL_RENDERBUFFER, t.depth);
        g.renderbuffer_storage(GL_RENDERBUFFER, samples, t.depth_format, w, h);
        const bool stencil = t.depth_format == GL_DEPTH24_STENCIL8;
        g.framebuffer_renderbuffer(GL_DRAW_FRAMEBUFFER, stencil ? GL_DEPTH_STENCIL_ATTACHMENT : GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, t.depth);
    }
    bool ok = g.check_framebuffer(GL_DRAW_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    if (ok && samples) {
        // The resolve's target: the texture in a framebuffer of its own.
        g.gen_framebuffers(1, &t.resolve_fbo);
        g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, t.resolve_fbo);
        g.framebuffer_texture(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, t.color, 0);
        ok = g.check_framebuffer(GL_DRAW_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    }
    if (ok) {
        // A new frame starts black, as a new window surface's does, not with whatever the memory held.
        g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, t.fbo);
        GLfloat was_clear[4] = {0, 0, 0, 0};
        static auto get_float = reinterpret_cast<void (*)(GLenum, GLfloat*)>(gl_proc("glGetFloatv"));
        if (get_float) get_float(GL_COLOR_CLEAR_VALUE, was_clear);
        GLboolean mask[4] = {GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE};
        g.get_boolean(GL_COLOR_WRITEMASK, mask);
        const GLboolean scissor = g.is_enabled(GL_SCISSOR_TEST);
        g.disable(GL_SCISSOR_TEST);
        g.color_mask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        g.clear_color(0, 0, 0, 1);
        g.clear(GL_COLOR_BUFFER_BIT);
        // The game's clear colour, mask and scissor as they were.
        g.clear_color(was_clear[0], was_clear[1], was_clear[2], was_clear[3]);
        g.color_mask(mask[0], mask[1], mask[2], mask[3]);
        if (scissor) g.enable(GL_SCISSOR_TEST);
    }
    // The game's bindings back: the draw framebuffer the caller rebinds as it needs.
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, was_draw);
    g.bind_renderbuffer(GL_RENDERBUFFER, static_cast<GLuint>(was_renderbuffer));
    g.bind_texture(GL_TEXTURE_2D, static_cast<GLuint>(was_texture));
    if (!ok) {
        log("arm32: the offscreen frame of %dx%d cannot be made here: the window's own framebuffer", w, h);
        free_objects(g, t);
        return false;
    }
    t.width = w;
    t.height = h;
    t.samples = samples;
    return true;
}

// The window config's formats and samples for a target, from the config the redirected surface was made with.
void read_config(EGLDisplay d, EGLConfig config, Target& t) {
    static auto attrib = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLConfig, EGLint, EGLint*)>(egl_fn("eglGetConfigAttrib"));
    EGLint alpha = 0, depth = 0, stencil = 0;
    if (attrib && config) {
        attrib(d, config, EGL_ALPHA_SIZE, &alpha);
        attrib(d, config, EGL_DEPTH_SIZE, &depth);
        attrib(d, config, EGL_STENCIL_SIZE, &stencil);
        attrib(d, config, EGL_SAMPLES, &t.config_samples);
        attrib(d, config, EGL_SAMPLE_BUFFERS, &t.config_sample_buffers);
    }
    // Alpha only where the window has it: a window without reads its alpha as 1, and so does RGB8.
    t.color_format = alpha > 0 ? GL_RGBA8 : GL_RGB8;
    // Depth and stencil together when there is stencil; depth alone at the config's precision; else none.
    t.depth_format = stencil > 0 ? GL_DEPTH24_STENCIL8 : depth > 16 ? GL_DEPTH_COMPONENT24 : depth > 0 ? GL_DEPTH_COMPONENT16 : 0;
}

// The frame resolved into the target's texture (with MSAA), with the scissor off for the blit and back after.
void resolve(const Gl& g, const Target& t) {
    if (!t.samples) return;
    const GLuint was_read = bound(GL_READ_FRAMEBUFFER), was_draw = bound(GL_DRAW_FRAMEBUFFER);
    const GLboolean scissor = g.is_enabled(GL_SCISSOR_TEST);
    if (scissor) g.disable(GL_SCISSOR_TEST);
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, t.fbo);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, t.resolve_fbo);
    g.blit(0, 0, t.width, t.height, 0, 0, t.width, t.height, GL_COLOR_BUFFER_BIT, GL_NEAREST);
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, was_read);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, was_draw);
    if (scissor) g.enable(GL_SCISSOR_TEST);
}

// While a game's call reads the frame: with MSAA, which GL cannot read from directly, the frame resolved and its texture's
// framebuffer bound for reading, the multisampled one back after. Nothing to do without MSAA or another read binding.
class ReadResolved {
public:
    ReadResolved() {
        Target* t = t_target;
        if (!t || !t->samples || bound(GL_READ_FRAMEBUFFER) != t->fbo) return;
        resolve(gl(), *t);
        gl().bind_framebuffer(GL_READ_FRAMEBUFFER, t->resolve_fbo);
        fbo_ = t->fbo;
    }
    ~ReadResolved() {
        if (fbo_) gl().bind_framebuffer(GL_READ_FRAMEBUFFER, fbo_);
    }
    ReadResolved(const ReadResolved&) = delete;
    ReadResolved& operator=(const ReadResolved&) = delete;

private:
    GLuint fbo_ = 0;  // the stand-in to bind back, 0 when nothing was changed
};

// While a game's call is asked of framebuffer 0 itself (attaching, its parameters): the real 0 bound to `target` when the
// stand-in is bound there, the stand-in back after.
class OnRealDefault {
public:
    explicit OnRealDefault(GLenum target) {
        const GLuint fbo = stand_in();
        if (!fbo) return;
        // GL_FRAMEBUFFER and GL_DRAW_FRAMEBUFFER are the draw binding; anything else is the call's own error.
        target_ = target == GL_READ_FRAMEBUFFER ? GL_READ_FRAMEBUFFER : GL_DRAW_FRAMEBUFFER;
        if (bound(target_) != fbo) return;
        gl().bind_framebuffer(target_, 0);
        fbo_ = fbo;
    }
    ~OnRealDefault() {
        if (fbo_) gl().bind_framebuffer(target_, fbo_);
    }
    OnRealDefault(const OnRealDefault&) = delete;
    OnRealDefault& operator=(const OnRealDefault&) = delete;

private:
    GLenum target_ = GL_DRAW_FRAMEBUFFER;
    GLuint fbo_ = 0;
};

// An attachment of the default framebuffer as the stand-in names it: GL_COLOR (GL_COLOR_EXT, the same number), GL_DEPTH
// and GL_STENCIL; GL_BACK for the colour where a draw or read buffer is named. Others stay (the call's own error).
GLenum attachment_of(GLenum a) {
    switch (a) {
    case GL_COLOR: return GL_COLOR_ATTACHMENT0;
    case GL_BACK: return GL_COLOR_ATTACHMENT0;
    case GL_DEPTH: return GL_DEPTH_ATTACHMENT;
    case GL_STENCIL: return GL_STENCIL_ATTACHMENT;
    default: return a;
    }
}

// A value the game asked glGet* for, as the default framebuffer would answer it when the stand-in is bound; false
// when the answer stays the host's.
bool fix_value(GLenum pname, std::int64_t& v) {
    Target* t = t_target;
    if (!t) return false;
    switch (pname) {
    case GL_DRAW_FRAMEBUFFER_BINDING:  // GL_FRAMEBUFFER_BINDING too: the same number
    case GL_READ_FRAMEBUFFER_BINDING:
        // The stand-in is framebuffer 0 to the game.
        if (v != static_cast<std::int64_t>(t->fbo)) return false;
        v = 0;
        return true;
    case GL_READ_BUFFER:
        // Its colour attachment is the window's back buffer.
        if (bound(GL_READ_FRAMEBUFFER) != t->fbo || v != GL_COLOR_ATTACHMENT0) return false;
        v = GL_BACK;
        return true;
    case GL_DRAW_BUFFER0:
        if (bound(GL_DRAW_FRAMEBUFFER) != t->fbo || v != GL_COLOR_ATTACHMENT0) return false;
        v = GL_BACK;
        return true;
    case GL_SAMPLES:
        // MSAA of our own is no sample buffer of the window's: the game hears its config's.
        if (bound(GL_DRAW_FRAMEBUFFER) != t->fbo) return false;
        v = t->config_samples;
        return true;
    case GL_SAMPLE_BUFFERS:
        if (bound(GL_DRAW_FRAMEBUFFER) != t->fbo) return false;
        v = t->config_sample_buffers;
        return true;
    default:
        return false;
    }
}

#define ARM32_FN(type, name) static auto fn = reinterpret_cast<type>(gl_proc(#name))

// The draw buffers of glDrawBuffers(EXT), GL_BACK as the stand-in's colour attachment when it is the draw framebuffer.
void draw_buffers(void (*fn)(GLsizei, const GLenum*), const char* name, Thread& t) {
    Words w{t};
    auto n = static_cast<GLsizei>(w.u32());
    auto* bufs = static_cast<const GLenum*>(gl_ptr(w.u32()));
    if (!fn) {
        gl_missing(name);
        return;
    }
    const GLuint fbo = stand_in();
    if (!fbo || !bufs || n <= 0 || bound(GL_DRAW_FRAMEBUFFER) != fbo) {
        fn(n, bufs);
        return;
    }
    std::vector<GLenum> mapped(bufs, bufs + n);
    for (GLenum& b : mapped) b = b == GL_BACK ? GL_COLOR_ATTACHMENT0 : b;
    fn(n, mapped.data());
}

// The attachments of glInvalidate(Sub)Framebuffer and glDiscardFramebufferEXT, as the stand-in names them when it is
// bound to the call's target.
std::vector<GLenum> attachments(GLenum target, GLsizei n, const GLenum* list) {
    std::vector<GLenum> out(list ? list : nullptr, list ? list + (n > 0 ? n : 0) : nullptr);
    const GLuint fbo = stand_in();
    if (!fbo || bound(target) != fbo) return out;
    for (GLenum& a : out) a = attachment_of(a);
    return out;
}

}  // namespace

// ---------------------------------------------------------------------------------------------------------------------
// The EGL bridge's hooks.

void offscreen_surface_created(EGLDisplay, EGLConfig config, EGLSurface surface) {
    if (!g_offscreen.load(std::memory_order_relaxed) || !surface) return;
    std::lock_guard<std::mutex> l(g_lock);
    g_surface = surface;
    g_config = config;
}

void offscreen_surface_destroyed(EGLSurface surface) {
    std::lock_guard<std::mutex> l(g_lock);
    if (g_surface == surface) g_surface = EGL_NO_SURFACE;
    // The targets drew for it: they keep their objects for the context's next surface, the surface itself forgotten.
    for (auto& [context, target] : g_targets) if (target.surface == surface) target.surface = EGL_NO_SURFACE;
}

void offscreen_before_make_current() {
    Target* t = t_target;
    if (!t) return;
    const Gl& g = gl();
    // The context keeps the real 0 where the game sees 0: drawing to another surface, 0 is that surface's.
    if (bound(GL_DRAW_FRAMEBUFFER) == t->fbo) g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, 0);
    if (bound(GL_READ_FRAMEBUFFER) == t->fbo) g.bind_framebuffer(GL_READ_FRAMEBUFFER, 0);
    t_target = nullptr;
}

void offscreen_made_current(EGLDisplay d, EGLSurface draw, EGLContext context) {
    if (!g_offscreen.load(std::memory_order_relaxed) || context == EGL_NO_CONTEXT) return;
    const Gl& g = gl();
    if (!g.ok) return;
    EGLConfig config = nullptr;
    Target* t = nullptr;
    bool first = false;
    {
        std::lock_guard<std::mutex> l(g_lock);
        // A context new to us has the viewport its first surface gave it.
        first = g_seen_contexts.insert(context).second;
        if (draw == EGL_NO_SURFACE || draw != g_surface) return;
        config = g_config;
        t = &g_targets[context];
    }
    t->context = context;
    t->surface = draw;
    int w = 0, h = 0;
    wanted_size(d, draw, &w, &h);
    if (w <= 0 || h <= 0) return;
    if (!t->fbo) {
        // This context's framebuffer, at the size the game draws at.
        read_config(d, config, *t);
        if (!make_objects(g, *t, w, h)) return;
        log("arm32: the game's frames drawn offscreen at %dx%d (%s colour, %s)", w, h, t->color_format == GL_RGBA8 ? "RGBA" : "RGB",
            t->depth_format == GL_DEPTH24_STENCIL8 ? "depth and stencil" : t->depth_format ? "depth" : "no depth");
    }
    t_target = t;
    // Where the game has 0 bound, the stand-in.
    if (bound(GL_DRAW_FRAMEBUFFER) == 0) g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, t->fbo);
    if (bound(GL_READ_FRAMEBUFFER) == 0) g.bind_framebuffer(GL_READ_FRAMEBUFFER, t->fbo);
    if (first) {
        // A context's viewport and scissor box start as its first surface's size, which is the window's here: the game
        // expects the size it draws at.
        g.viewport(0, 0, w, h);
        g.scissor(0, 0, w, h);
    }
}

void offscreen_context_destroyed(EGLContext context) {
    std::lock_guard<std::mutex> l(g_lock);
    g_seen_contexts.erase(context);
    auto it = g_targets.find(context);
    if (it == g_targets.end()) return;
    // A thread still pointing at it (the game destroyed it while current) lets go: a new context may get its address.
    if (t_target == &it->second) t_target = nullptr;
    g_targets.erase(it);
}

bool offscreen_query(EGLSurface surface, EGLint attribute, EGLint* value) {
    if (!g_offscreen.load(std::memory_order_relaxed) || !value || (attribute != EGL_WIDTH && attribute != EGL_HEIGHT)) return false;
    EGLDisplay d = EGL_NO_DISPLAY;
    {
        std::lock_guard<std::mutex> l(g_lock);
        if (surface != g_surface || surface == EGL_NO_SURFACE) return false;
    }
    static auto current_display = reinterpret_cast<EGLDisplay (*)()>(egl_fn("eglGetCurrentDisplay"));
    if (current_display) d = current_display();
    int w = 0, h = 0;
    wanted_size(d, surface, &w, &h);
    if (w <= 0 || h <= 0) return false;
    // The size the game draws at, as a surface of a fixed size answers it.
    *value = attribute == EGL_WIDTH ? w : h;
    return true;
}

void offscreen_swap(EGLDisplay d, EGLSurface s) {
    Target* t = t_target;
    if (!t || s != t->surface) return;
    const Gl& g = gl();
    const GLuint was_read = bound(GL_READ_FRAMEBUFFER), was_draw = bound(GL_DRAW_FRAMEBUFFER);
    // The frame as a single-sampled texture.
    resolve(g, *t);
    static auto query = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint, EGLint*)>(egl_fn("eglQuerySurface"));
    EGLint ow = 0, oh = 0;
    if (query) {
        query(d, s, EGL_WIDTH, &ow);
        query(d, s, EGL_HEIGHT, &oh);
    }
    const OffscreenFrame frame{d, s, t->context, t->color, t->width, t->height, ow, oh, t->samples};
    OffscreenPresent present = g_offscreen_present.load(std::memory_order_relaxed);
    if (!present || !present(frame)) {
        // No passes here: the frame stretched to the window by a plain blit, the scissor and mask out of its way.
        const GLboolean scissor = g.is_enabled(GL_SCISSOR_TEST);
        if (scissor) g.disable(GL_SCISSOR_TEST);
        g.bind_framebuffer(GL_READ_FRAMEBUFFER, t->samples ? t->resolve_fbo : t->fbo);
        g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, 0);
        const bool same = ow == t->width && oh == t->height;
        g.blit(0, 0, t->width, t->height, 0, 0, ow, oh, GL_COLOR_BUFFER_BIT, same ? GL_NEAREST : GL_LINEAR);
        if (scissor) g.enable(GL_SCISSOR_TEST);
    }
    // The game's bindings as they were.
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, was_read);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, was_draw);
    // The size the game draws at changed (a resize, a new render scale): new objects for the next frame, rebound where
    // the stand-in was bound.
    int w = 0, h = 0;
    wanted_size(d, s, &w, &h);
    if (w > 0 && h > 0 && (w != t->width || h != t->height || t->samples != usable_samples(g, *t, g_offscreen_samples.load()))) {
        const GLuint old = t->fbo;
        free_objects(g, *t);
        if (!make_objects(g, *t, w, h)) {
            // Nothing to draw into: the game's frames go to the window as they would without us, from now on.
            t_target = nullptr;
            if (was_read == old) g.bind_framebuffer(GL_READ_FRAMEBUFFER, 0);
            if (was_draw == old) g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, 0);
            return;
        }
        if (was_read == old) g.bind_framebuffer(GL_READ_FRAMEBUFFER, t->fbo);
        if (was_draw == old) g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, t->fbo);
        log("arm32: the offscreen frame now %dx%d", w, h);
    }
}

// ---------------------------------------------------------------------------------------------------------------------
// The game's framebuffer calls (gl_bridge.h's specials).

std::uint64_t gl_special_glBindFramebuffer(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLuint), glBindFramebuffer);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto name = static_cast<GLuint>(w.u32());
    if (!fn) return gl_missing("glBindFramebuffer");
    // 0 is the stand-in while the frames are redirected.
    if (name == 0) name = stand_in();
    fn(target, name);
    return 0;
}

// glGet* of one value or more: the host's answer, then the values the default framebuffer would give (fix_value; each of
// those names one value).
std::uint64_t gl_special_glGetIntegerv(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLint*), glGetIntegerv);
    Words w{t};
    auto pname = static_cast<GLenum>(w.u32());
    auto* out = static_cast<GLint*>(gl_ptr(w.u32()));
    if (!fn) return gl_missing("glGetIntegerv");
    fn(pname, out);
    std::int64_t v = out ? *out : 0;
    if (out && fix_value(pname, v)) *out = static_cast<GLint>(v);
    return 0;
}

std::uint64_t gl_special_glGetInteger64v(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLint64*), glGetInteger64v);
    Words w{t};
    auto pname = static_cast<GLenum>(w.u32());
    auto* out = static_cast<GLint64*>(gl_ptr(w.u32()));
    if (!fn) return gl_missing("glGetInteger64v");
    fn(pname, out);
    std::int64_t v = out ? *out : 0;
    if (out && fix_value(pname, v)) *out = v;
    return 0;
}

std::uint64_t gl_special_glGetFloatv(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLfloat*), glGetFloatv);
    Words w{t};
    auto pname = static_cast<GLenum>(w.u32());
    auto* out = static_cast<GLfloat*>(gl_ptr(w.u32()));
    if (!fn) return gl_missing("glGetFloatv");
    fn(pname, out);
    std::int64_t v = out ? static_cast<std::int64_t>(*out) : 0;
    if (out && fix_value(pname, v)) *out = static_cast<GLfloat>(v);
    return 0;
}

std::uint64_t gl_special_glGetBooleanv(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLboolean*), glGetBooleanv);
    Words w{t};
    auto pname = static_cast<GLenum>(w.u32());
    auto* out = static_cast<GLboolean*>(gl_ptr(w.u32()));
    if (!fn) return gl_missing("glGetBooleanv");
    fn(pname, out);
    // A boolean of a binding is only whether one is bound: asked as an integer, then turned into one.
    if (out && t_target && (pname == GL_DRAW_FRAMEBUFFER_BINDING || pname == GL_READ_FRAMEBUFFER_BINDING || pname == GL_SAMPLES ||
                            pname == GL_SAMPLE_BUFFERS)) {
        GLint i = 0;
        gl().get_integer(pname, &i);
        std::int64_t v = i;
        fix_value(pname, v);
        *out = v ? GL_TRUE : GL_FALSE;
    }
    return 0;
}

// Reads of the frame: resolved first with MSAA (ReadResolved).
std::uint64_t gl_special_glReadPixels(Thread& t) {
    ARM32_FN(void (*)(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, void*), glReadPixels);
    Words w{t};
    auto x = static_cast<GLint>(w.u32());
    auto y = static_cast<GLint>(w.u32());
    auto width = static_cast<GLsizei>(w.u32());
    auto height = static_cast<GLsizei>(w.u32());
    auto format = static_cast<GLenum>(w.u32());
    auto type = static_cast<GLenum>(w.u32());
    void* pixels = gl_ptr(w.u32());
    if (!fn) return gl_missing("glReadPixels");
    ReadResolved read;
    fn(x, y, width, height, format, type, pixels);
    return 0;
}

// glReadnPixels and its two extension names: the same arguments, with the buffer's size.
static std::uint64_t read_n_pixels(Thread& t, void (*fn)(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, GLsizei, void*), const char* name) {
    Words w{t};
    auto x = static_cast<GLint>(w.u32());
    auto y = static_cast<GLint>(w.u32());
    auto width = static_cast<GLsizei>(w.u32());
    auto height = static_cast<GLsizei>(w.u32());
    auto format = static_cast<GLenum>(w.u32());
    auto type = static_cast<GLenum>(w.u32());
    auto size = static_cast<GLsizei>(w.u32());
    void* pixels = gl_ptr(w.u32());
    if (!fn) return gl_missing(name);
    ReadResolved read;
    fn(x, y, width, height, format, type, size, pixels);
    return 0;
}

std::uint64_t gl_special_glReadnPixels(Thread& t) {
    ARM32_FN(void (*)(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, GLsizei, void*), glReadnPixels);
    return read_n_pixels(t, fn, "glReadnPixels");
}

std::uint64_t gl_special_glReadnPixelsEXT(Thread& t) {
    ARM32_FN(void (*)(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, GLsizei, void*), glReadnPixelsEXT);
    return read_n_pixels(t, fn, "glReadnPixelsEXT");
}

std::uint64_t gl_special_glReadnPixelsKHR(Thread& t) {
    ARM32_FN(void (*)(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, GLsizei, void*), glReadnPixelsKHR);
    return read_n_pixels(t, fn, "glReadnPixelsKHR");
}

std::uint64_t gl_special_glCopyTexImage2D(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLint, GLenum, GLint, GLint, GLsizei, GLsizei, GLint), glCopyTexImage2D);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto level = static_cast<GLint>(w.u32());
    auto format = static_cast<GLenum>(w.u32());
    auto x = static_cast<GLint>(w.u32());
    auto y = static_cast<GLint>(w.u32());
    auto width = static_cast<GLsizei>(w.u32());
    auto height = static_cast<GLsizei>(w.u32());
    auto border = static_cast<GLint>(w.u32());
    if (!fn) return gl_missing("glCopyTexImage2D");
    ReadResolved read;
    fn(target, level, format, x, y, width, height, border);
    return 0;
}

std::uint64_t gl_special_glCopyTexSubImage2D(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLint, GLint, GLint, GLint, GLint, GLsizei, GLsizei), glCopyTexSubImage2D);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto level = static_cast<GLint>(w.u32());
    auto xoffset = static_cast<GLint>(w.u32());
    auto yoffset = static_cast<GLint>(w.u32());
    auto x = static_cast<GLint>(w.u32());
    auto y = static_cast<GLint>(w.u32());
    auto width = static_cast<GLsizei>(w.u32());
    auto height = static_cast<GLsizei>(w.u32());
    if (!fn) return gl_missing("glCopyTexSubImage2D");
    ReadResolved read;
    fn(target, level, xoffset, yoffset, x, y, width, height);
    return 0;
}

std::uint64_t gl_special_glCopyTexSubImage3D(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLint, GLint, GLint, GLint, GLint, GLint, GLsizei, GLsizei), glCopyTexSubImage3D);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto level = static_cast<GLint>(w.u32());
    auto xoffset = static_cast<GLint>(w.u32());
    auto yoffset = static_cast<GLint>(w.u32());
    auto zoffset = static_cast<GLint>(w.u32());
    auto x = static_cast<GLint>(w.u32());
    auto y = static_cast<GLint>(w.u32());
    auto width = static_cast<GLsizei>(w.u32());
    auto height = static_cast<GLsizei>(w.u32());
    if (!fn) return gl_missing("glCopyTexSubImage3D");
    ReadResolved read;
    fn(target, level, xoffset, yoffset, zoffset, x, y, width, height);
    return 0;
}

std::uint64_t gl_special_glBlitFramebuffer(Thread& t) {
    ARM32_FN(void (*)(GLint, GLint, GLint, GLint, GLint, GLint, GLint, GLint, GLbitfield, GLenum), glBlitFramebuffer);
    Words w{t};
    GLint c[8];
    for (GLint& v : c) v = static_cast<GLint>(w.u32());
    auto mask = static_cast<GLbitfield>(w.u32());
    auto filter = static_cast<GLenum>(w.u32());
    if (!fn) return gl_missing("glBlitFramebuffer");
    Target* target = t_target;
    // A blit into the multisampled frame is GL's error, which a single-sampled window would not give: said once.
    if (target && target->samples && bound(GL_DRAW_FRAMEBUFFER) == target->fbo) {
        static bool said = false;
        if (!said) log("arm32: anti-aliasing: the game blits into its frame, which MSAA's frame cannot take: choose another anti-aliasing");
        said = true;
    }
    // Colour read from the frame with MSAA comes from the resolved frame; depth and stencil stay the multisampled ones'.
    if (mask == GL_COLOR_BUFFER_BIT) {
        ReadResolved read;
        fn(c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7], mask, filter);
    } else {
        fn(c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7], mask, filter);
    }
    return 0;
}

std::uint64_t gl_special_glInvalidateFramebuffer(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLsizei, const GLenum*), glInvalidateFramebuffer);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto n = static_cast<GLsizei>(w.u32());
    auto* list = static_cast<const GLenum*>(gl_ptr(w.u32()));
    if (!fn) return gl_missing("glInvalidateFramebuffer");
    const std::vector<GLenum> a = attachments(target, n, list);
    fn(target, n, list ? a.data() : nullptr);
    return 0;
}

std::uint64_t gl_special_glInvalidateSubFramebuffer(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLsizei, const GLenum*, GLint, GLint, GLsizei, GLsizei), glInvalidateSubFramebuffer);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto n = static_cast<GLsizei>(w.u32());
    auto* list = static_cast<const GLenum*>(gl_ptr(w.u32()));
    auto x = static_cast<GLint>(w.u32());
    auto y = static_cast<GLint>(w.u32());
    auto width = static_cast<GLsizei>(w.u32());
    auto height = static_cast<GLsizei>(w.u32());
    if (!fn) return gl_missing("glInvalidateSubFramebuffer");
    const std::vector<GLenum> a = attachments(target, n, list);
    fn(target, n, list ? a.data() : nullptr, x, y, width, height);
    return 0;
}

std::uint64_t gl_special_glDiscardFramebufferEXT(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLsizei, const GLenum*), glDiscardFramebufferEXT);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto n = static_cast<GLsizei>(w.u32());
    auto* list = static_cast<const GLenum*>(gl_ptr(w.u32()));
    if (!fn) return gl_missing("glDiscardFramebufferEXT");
    const std::vector<GLenum> a = attachments(target, n, list);
    fn(target, n, list ? a.data() : nullptr);
    return 0;
}

std::uint64_t gl_special_glDrawBuffers(Thread& t) {
    ARM32_FN(void (*)(GLsizei, const GLenum*), glDrawBuffers);
    draw_buffers(fn, "glDrawBuffers", t);
    return 0;
}

std::uint64_t gl_special_glDrawBuffersEXT(Thread& t) {
    ARM32_FN(void (*)(GLsizei, const GLenum*), glDrawBuffersEXT);
    draw_buffers(fn, "glDrawBuffersEXT", t);
    return 0;
}

std::uint64_t gl_special_glReadBuffer(Thread& t) {
    ARM32_FN(void (*)(GLenum), glReadBuffer);
    Words w{t};
    auto src = static_cast<GLenum>(w.u32());
    if (!fn) return gl_missing("glReadBuffer");
    // GL_BACK is the stand-in's colour attachment while it is the read framebuffer.
    const GLuint fbo = stand_in();
    if (fbo && src == GL_BACK && bound(GL_READ_FRAMEBUFFER) == fbo) src = GL_COLOR_ATTACHMENT0;
    fn(src);
    return 0;
}

// The calls on framebuffer 0 itself: made with the real 0 bound (OnRealDefault).
std::uint64_t gl_special_glFramebufferTexture2D(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLenum, GLenum, GLuint, GLint), glFramebufferTexture2D);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto attachment = static_cast<GLenum>(w.u32());
    auto textarget = static_cast<GLenum>(w.u32());
    auto texture = static_cast<GLuint>(w.u32());
    auto level = static_cast<GLint>(w.u32());
    if (!fn) return gl_missing("glFramebufferTexture2D");
    OnRealDefault real(target);
    fn(target, attachment, textarget, texture, level);
    return 0;
}

std::uint64_t gl_special_glFramebufferRenderbuffer(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLenum, GLenum, GLuint), glFramebufferRenderbuffer);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto attachment = static_cast<GLenum>(w.u32());
    auto rbtarget = static_cast<GLenum>(w.u32());
    auto renderbuffer = static_cast<GLuint>(w.u32());
    if (!fn) return gl_missing("glFramebufferRenderbuffer");
    OnRealDefault real(target);
    fn(target, attachment, rbtarget, renderbuffer);
    return 0;
}

std::uint64_t gl_special_glFramebufferTextureLayer(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLenum, GLuint, GLint, GLint), glFramebufferTextureLayer);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto attachment = static_cast<GLenum>(w.u32());
    auto texture = static_cast<GLuint>(w.u32());
    auto level = static_cast<GLint>(w.u32());
    auto layer = static_cast<GLint>(w.u32());
    if (!fn) return gl_missing("glFramebufferTextureLayer");
    OnRealDefault real(target);
    fn(target, attachment, texture, level, layer);
    return 0;
}

// glFramebufferTexture and its EXT and OES names: the same arguments.
static std::uint64_t framebuffer_texture(Thread& t, void (*fn)(GLenum, GLenum, GLuint, GLint), const char* name) {
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto attachment = static_cast<GLenum>(w.u32());
    auto texture = static_cast<GLuint>(w.u32());
    auto level = static_cast<GLint>(w.u32());
    if (!fn) return gl_missing(name);
    OnRealDefault real(target);
    fn(target, attachment, texture, level);
    return 0;
}

std::uint64_t gl_special_glFramebufferTexture(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLenum, GLuint, GLint), glFramebufferTexture);
    return framebuffer_texture(t, fn, "glFramebufferTexture");
}

std::uint64_t gl_special_glFramebufferTextureEXT(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLenum, GLuint, GLint), glFramebufferTextureEXT);
    return framebuffer_texture(t, fn, "glFramebufferTextureEXT");
}

std::uint64_t gl_special_glFramebufferTextureOES(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLenum, GLuint, GLint), glFramebufferTextureOES);
    return framebuffer_texture(t, fn, "glFramebufferTextureOES");
}

std::uint64_t gl_special_glFramebufferTexture2DMultisampleEXT(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLenum, GLenum, GLuint, GLint, GLsizei), glFramebufferTexture2DMultisampleEXT);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto attachment = static_cast<GLenum>(w.u32());
    auto textarget = static_cast<GLenum>(w.u32());
    auto texture = static_cast<GLuint>(w.u32());
    auto level = static_cast<GLint>(w.u32());
    auto samples = static_cast<GLsizei>(w.u32());
    if (!fn) return gl_missing("glFramebufferTexture2DMultisampleEXT");
    OnRealDefault real(target);
    fn(target, attachment, textarget, texture, level, samples);
    return 0;
}

std::uint64_t gl_special_glFramebufferTexture3DOES(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLenum, GLenum, GLuint, GLint, GLint), glFramebufferTexture3DOES);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto attachment = static_cast<GLenum>(w.u32());
    auto textarget = static_cast<GLenum>(w.u32());
    auto texture = static_cast<GLuint>(w.u32());
    auto level = static_cast<GLint>(w.u32());
    auto zoffset = static_cast<GLint>(w.u32());
    if (!fn) return gl_missing("glFramebufferTexture3DOES");
    OnRealDefault real(target);
    fn(target, attachment, textarget, texture, level, zoffset);
    return 0;
}

std::uint64_t gl_special_glFramebufferParameteri(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLenum, GLint), glFramebufferParameteri);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto pname = static_cast<GLenum>(w.u32());
    auto param = static_cast<GLint>(w.u32());
    if (!fn) return gl_missing("glFramebufferParameteri");
    OnRealDefault real(target);
    fn(target, pname, param);
    return 0;
}

std::uint64_t gl_special_glGetFramebufferAttachmentParameteriv(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLenum, GLenum, GLint*), glGetFramebufferAttachmentParameteriv);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto attachment = static_cast<GLenum>(w.u32());
    auto pname = static_cast<GLenum>(w.u32());
    auto* params = static_cast<GLint*>(gl_ptr(w.u32()));
    if (!fn) return gl_missing("glGetFramebufferAttachmentParameteriv");
    OnRealDefault real(target);
    fn(target, attachment, pname, params);
    return 0;
}

std::uint64_t gl_special_glGetFramebufferParameteriv(Thread& t) {
    ARM32_FN(void (*)(GLenum, GLenum, GLint*), glGetFramebufferParameteriv);
    Words w{t};
    auto target = static_cast<GLenum>(w.u32());
    auto pname = static_cast<GLenum>(w.u32());
    auto* params = static_cast<GLint*>(gl_ptr(w.u32()));
    if (!fn) return gl_missing("glGetFramebufferParameteriv");
    OnRealDefault real(target);
    fn(target, pname, params);
    return 0;
}

}  // namespace arm32
