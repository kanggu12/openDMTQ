// EGL for the guest. Displays, configs, contexts, surfaces, images, syncs and native windows
// are host pointers, so the guest holds 32-bit handles; strings are copied into guest memory.
#include "egl_numbers.h"
#include "gl_bridge.h"
#include "live.h"
#include "pacing.h"
#include "tweaks.h"

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <dlfcn.h>
#include <type_traits>

namespace arm32 {

namespace {

// Host EGL entry points, looked up once (extensions through eglGetProcAddress).
void* egl_proc(const char* name) {
    static void* lib = dlopen(kHostEgl, RTLD_NOW | RTLD_LOCAL);
    void* f = lib ? dlsym(lib, name) : nullptr;
    if (!f && lib) {
        static auto get = reinterpret_cast<void* (*)(const char*)>(dlsym(lib, "eglGetProcAddress"));
        if (get) f = get(name);
    }
    return f;
}

#define FN(type, name) static auto fn = reinterpret_cast<type>(egl_proc(#name))

template <class T>
T* ptr(std::uint32_t g) { return static_cast<T*>(guest_ptr(g)); }

// The host object behind a guest handle of each kind of EGL object (see HandleKind): a handle
// of another kind is null here, as an invalid object is to EGL.
void* dpy(std::uint32_t h) { return handles().get(HandleKind::kEglDisplay, h); }
void* cfg(std::uint32_t h) { return handles().get(HandleKind::kEglConfig, h); }
void* ctx(std::uint32_t h) { return handles().get(HandleKind::kEglContext, h); }
void* srf(std::uint32_t h) { return handles().get(HandleKind::kEglSurface, h); }
void* img(std::uint32_t h) { return handles().get(HandleKind::kEglImage, h); }
void* syn(std::uint32_t h) { return handles().get(HandleKind::kEglSync, h); }
std::uint32_t put(HandleKind kind, const void* p) { return handles().put(kind, p); }

// The host's EGL error, for tracing (the guest's own eglGetError comes through the bridge).
EGLint host_error() {
    static auto fn = reinterpret_cast<EGLint (*)()>(egl_proc("eglGetError"));
    return fn ? fn() : EGL_SUCCESS;
}

// An error read on this thread for a trace line, kept for the guest's next eglGetError: reading
// the host's error clears it.
thread_local EGLint t_traced_error = EGL_SUCCESS;

std::uint64_t missing(const char* name) {
    gl_missing(name);
    return 0;
}

gaddr cached(const char* s) {
    static std::mutex lock;
    static std::unordered_map<const char*, gaddr> copies;
    if (!s) return 0;
    std::lock_guard<std::mutex> l(lock);
    auto it = copies.find(s);
    if (it != copies.end()) return it->second;
    return copies[s] = arena_strdup(s);
}

// Fills a guest array of config handles from host configs.
void put_configs(gaddr out, const std::vector<EGLConfig>& configs, EGLint n) {
    for (EGLint i = 0; i < n && out; ++i) *gmem().ptr<std::uint32_t>(out + static_cast<gaddr>(i) * 4) = put(HandleKind::kEglConfig, configs[static_cast<std::size_t>(i)]);
}

std::uint64_t egl_GetDisplay(Thread&) {
    FN(EGLDisplay (*)(EGLNativeDisplayType), eglGetDisplay);
    // The guest can only mean the default display.
    return fn ? put(HandleKind::kEglDisplay, fn(EGL_DEFAULT_DISPLAY)) : missing("eglGetDisplay");
}

std::uint64_t egl_Initialize(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLint*, EGLint*), eglInitialize);
    Words w{t};
    void* d = dpy(w.u32());
    auto major = ptr<EGLint>(w.u32());
    auto minor = ptr<EGLint>(w.u32());
    return fn ? fn(d, major, minor) : missing("eglInitialize");
}

std::uint64_t egl_Terminate(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay), eglTerminate);
    Words w{t};
    return fn ? fn(dpy(w.u32())) : 0;
}

std::uint64_t egl_QueryString(Thread& t) {
    FN(const char* (*)(EGLDisplay, EGLint), eglQueryString);
    Words w{t};
    void* d = dpy(w.u32());
    auto name = static_cast<EGLint>(w.u32());
    return fn ? cached(fn(d, name)) : 0;
}

std::uint64_t egl_GetConfigs(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLConfig*, EGLint, EGLint*), eglGetConfigs);
    Words w{t};
    void* d = dpy(w.u32());
    gaddr configs = w.u32();
    auto size = static_cast<EGLint>(w.u32());
    gaddr num = w.u32();
    if (!fn) return missing("eglGetConfigs");
    std::vector<EGLConfig> host(static_cast<std::size_t>(size > 0 ? size : 0));
    EGLint n = 0;
    EGLBoolean ok = fn(d, configs ? host.data() : nullptr, size, &n);
    if (ok) put_configs(configs, host, n);
    if (num) *gmem().ptr<EGLint>(num) = n;
    return ok;
}

std::uint64_t egl_ChooseConfig(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, const EGLint*, EGLConfig*, EGLint, EGLint*), eglChooseConfig);
    Words w{t};
    void* d = dpy(w.u32());
    auto attribs = ptr<const EGLint>(w.u32());
    gaddr configs = w.u32();
    auto size = static_cast<EGLint>(w.u32());
    gaddr num = w.u32();
    if (!fn) return missing("eglChooseConfig");
    std::vector<EGLConfig> host(static_cast<std::size_t>(size > 0 ? size : 0));
    EGLint n = 0;
    EGLBoolean ok = fn(d, attribs, configs ? host.data() : nullptr, size, &n);
    if (ok) put_configs(configs, host, configs ? std::min(n, size) : 0);
    if (num) *gmem().ptr<EGLint>(num) = n;
    return ok;
}

std::uint64_t egl_GetConfigAttrib(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLConfig, EGLint, EGLint*), eglGetConfigAttrib);
    Words w{t};
    void* d = dpy(w.u32());
    void* c = cfg(w.u32());
    auto attr = static_cast<EGLint>(w.u32());
    return fn ? fn(d, c, attr, ptr<EGLint>(w.u32())) : 0;
}

// A host window handle as EGL takes it: an ANativeWindow pointer on Android; an integer on a desktop
// host (an X11 window there, which the desktop player's ANativeWindow handles are).
// A template, so that the branch the platform's type rules out is never compiled.
template <class W>
W native_window(void* handle) {
    if constexpr (std::is_pointer_v<W>) return static_cast<W>(handle);
    else return reinterpret_cast<W>(handle);
}

// ANGLE's window surface of a fixed size (EGL_ANGLE_window_fixed_size), stretched to its window when shown.
#ifndef EGL_FIXED_SIZE_ANGLE
#define EGL_FIXED_SIZE_ANGLE 0x3201
#endif

// The window surface made at a fixed size for a computer player's render scale (pacing.h's g_window_fixed_size), and the
// size it has now: a resized window gives it a new one at the next swap. The game makes, swaps and destroys its window
// surface on its render thread; the lock keeps another thread's surface calls in order with it.
std::mutex g_fixed_lock;
void* g_fixed_surface = nullptr;
std::int64_t g_fixed_now = 0;

std::uint64_t egl_CreateWindowSurface(Thread& t) {
    FN(EGLSurface (*)(EGLDisplay, EGLConfig, EGLNativeWindowType, const EGLint*), eglCreateWindowSurface);
    Words w{t};
    void* d = dpy(w.u32());
    void* c = cfg(w.u32());
    void* win = handles().get(HandleKind::kWindow, w.u32());
    const EGLint* asked = ptr<const EGLint>(w.u32());
    // A computer player's render scale: the game's attributes, then a fixed size, the one the player told the game.
    const std::int64_t fixed = g_window_fixed_size.load(std::memory_order_relaxed);
    std::vector<EGLint> attribs;
    if (fixed) {
        for (const EGLint* a = asked; a && *a != EGL_NONE; a += 2) {
            if (a[0] == EGL_FIXED_SIZE_ANGLE || a[0] == EGL_WIDTH || a[0] == EGL_HEIGHT) continue;
            attribs.push_back(a[0]);
            attribs.push_back(a[1]);
        }
        attribs.insert(attribs.end(), {EGL_FIXED_SIZE_ANGLE, EGL_TRUE, EGL_WIDTH, static_cast<EGLint>(fixed >> 32),
                                       EGL_HEIGHT, static_cast<EGLint>(fixed & 0xffffffff), EGL_NONE});
    }
    EGLSurface s = fn ? fn(d, c, native_window<EGLNativeWindowType>(win), fixed ? attribs.data() : asked) : nullptr;
    if (!s && fixed && fn) {
        // An EGL without fixed sizes: the window's own, with the picture in a corner of it until the scale is 100 %.
        log("arm32: render scale: no surface of a fixed size here (error %#x); the window's own size", host_error());
        s = fn(d, c, native_window<EGLNativeWindowType>(win), asked);
    } else if (s && fixed) {
        std::lock_guard<std::mutex> lock(g_fixed_lock);
        g_fixed_surface = s;
        g_fixed_now = fixed;
        log("arm32: render scale: the window's surface drawn at %dx%d", static_cast<int>(fixed >> 32), static_cast<int>(fixed & 0xffffffff));
    }
    if (g_trace) log("trace: eglCreateWindowSurface(window %p) -> %p, error %#x", win, s, host_error());
    // The window the game renders to: the one asked for the frame rate.
    if (s) game_window_surface(static_cast<ANativeWindow*>(win));
    return put(HandleKind::kEglSurface, s);
}

// Before a swap of the surface of a fixed size: the size the player asks for now, when that changed (the window was
// resized, and the game was told the new size), from this frame on.
void follow_fixed_size(void* d, void* s) {
    const std::int64_t want = g_window_fixed_size.load(std::memory_order_relaxed);
    // No fixed size wanted (every phone): no lock either.
    if (!want) return;
    std::lock_guard<std::mutex> lock(g_fixed_lock);
    if (s != g_fixed_surface || want == g_fixed_now) return;
    FN(EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint, EGLint), eglSurfaceAttrib);
    const auto width = static_cast<EGLint>(want >> 32), height = static_cast<EGLint>(want & 0xffffffff);
    const bool ok = fn && fn(d, s, EGL_WIDTH, width) == EGL_TRUE && fn(d, s, EGL_HEIGHT, height) == EGL_TRUE;
    // Asked once either way: a refusal would be the same at every frame.
    g_fixed_now = want;
    if (ok) log("arm32: render scale: the surface now drawn at %dx%d", width, height);
    else log("arm32: render scale: the surface keeps its size (error %#x)", host_error());
}

std::uint64_t egl_CreatePbufferSurface(Thread& t) {
    FN(EGLSurface (*)(EGLDisplay, EGLConfig, const EGLint*), eglCreatePbufferSurface);
    Words w{t};
    void* d = dpy(w.u32());
    void* c = cfg(w.u32());
    return fn ? put(HandleKind::kEglSurface, fn(d, c, ptr<const EGLint>(w.u32()))) : 0;
}

std::uint64_t egl_CreatePixmapSurface(Thread&) {
    // Android has no native pixmaps.
    return 0;
}

std::uint64_t egl_CreatePbufferFromClientBuffer(Thread& t) {
    FN(EGLSurface (*)(EGLDisplay, EGLenum, EGLClientBuffer, EGLConfig, const EGLint*), eglCreatePbufferFromClientBuffer);
    Words w{t};
    void* d = dpy(w.u32());
    auto type = static_cast<EGLenum>(w.u32());
    void* buffer = handles().get(HandleKind::kAny, w.u32());
    void* c = cfg(w.u32());
    return fn ? put(HandleKind::kEglSurface, fn(d, type, buffer, c, ptr<const EGLint>(w.u32()))) : 0;
}

std::uint64_t egl_DestroySurface(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLSurface), eglDestroySurface);
    Words w{t};
    void* d = dpy(w.u32());
    std::uint32_t s = w.u32();
    void* surface = srf(s);
    EGLBoolean ok = fn ? fn(d, surface) : EGL_FALSE;
    if (ok) {
        pacing_surface_destroyed(surface);
        handles().drop(HandleKind::kEglSurface, s);
        // A new surface at the same address is not the one of a fixed size.
        std::lock_guard<std::mutex> lock(g_fixed_lock);
        if (g_fixed_surface == surface) g_fixed_surface = nullptr;
    }
    return ok;
}

std::uint64_t egl_QuerySurface(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint, EGLint*), eglQuerySurface);
    Words w{t};
    void* d = dpy(w.u32());
    void* s = srf(w.u32());
    auto attr = static_cast<EGLint>(w.u32());
    return fn ? fn(d, s, attr, ptr<EGLint>(w.u32())) : 0;
}

std::uint64_t egl_SurfaceAttrib(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint, EGLint), eglSurfaceAttrib);
    Words w{t};
    void* d = dpy(w.u32());
    void* s = srf(w.u32());
    auto attr = static_cast<EGLint>(w.u32());
    return fn ? fn(d, s, attr, static_cast<EGLint>(w.u32())) : 0;
}

std::uint64_t egl_BindTexImage(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint), eglBindTexImage);
    Words w{t};
    void* d = dpy(w.u32());
    void* s = srf(w.u32());
    return fn ? fn(d, s, static_cast<EGLint>(w.u32())) : 0;
}

std::uint64_t egl_ReleaseTexImage(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint), eglReleaseTexImage);
    Words w{t};
    void* d = dpy(w.u32());
    void* s = srf(w.u32());
    return fn ? fn(d, s, static_cast<EGLint>(w.u32())) : 0;
}

std::uint64_t egl_SwapInterval(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLint), eglSwapInterval);
    Words w{t};
    void* d = dpy(w.u32());
    auto interval = static_cast<EGLint>(w.u32());
    // The game's choice, except while frames are paced (pacing.cpp).
    EGLint used = pacing_swap_interval(interval);
    // Each change: what the game asks for decides how unpaced frames go to the screen.
    static std::atomic<EGLint> logged{-1};
    if (logged.exchange(interval) != interval) log("arm32: the game asks for swap interval %d, using %d", interval, used);
    else if (g_trace) log("trace: eglSwapInterval(%d), using %d", interval, used);
    return fn ? fn(d, used) : 0;
}

std::uint64_t egl_CreateContext(Thread& t) {
    FN(EGLContext (*)(EGLDisplay, EGLConfig, EGLContext, const EGLint*), eglCreateContext);
    Words w{t};
    void* d = dpy(w.u32());
    void* c = cfg(w.u32());
    void* share = ctx(w.u32());
    return fn ? put(HandleKind::kEglContext, fn(d, c, share, ptr<const EGLint>(w.u32()))) : 0;
}

std::uint64_t egl_DestroyContext(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLContext), eglDestroyContext);
    Words w{t};
    void* d = dpy(w.u32());
    std::uint32_t c = w.u32();
    EGLBoolean ok = fn ? fn(d, ctx(c)) : EGL_FALSE;
    if (ok) {
        live_context_destroyed(ctx(c));
        handles().drop(HandleKind::kEglContext, c);
    }
    return ok;
}

std::uint64_t egl_MakeCurrent(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLSurface, EGLSurface, EGLContext), eglMakeCurrent);
    Words w{t};
    void* d = dpy(w.u32());
    void* draw = srf(w.u32());
    void* read = srf(w.u32());
    void* context = ctx(w.u32());
    EGLBoolean ok = fn ? fn(d, draw, read, context) : EGL_FALSE;
    if (g_trace) log("trace: eglMakeCurrent(draw %p, ctx %p) on %d -> %d", draw, context, t.tid, ok);
    return ok;
}

std::uint64_t egl_GetCurrentContext(Thread&) {
    FN(EGLContext (*)(), eglGetCurrentContext);
    return fn ? put(HandleKind::kEglContext, fn()) : 0;
}

std::uint64_t egl_GetCurrentSurface(Thread& t) {
    FN(EGLSurface (*)(EGLint), eglGetCurrentSurface);
    Words w{t};
    return fn ? put(HandleKind::kEglSurface, fn(static_cast<EGLint>(w.u32()))) : 0;
}

std::uint64_t egl_GetCurrentDisplay(Thread&) {
    FN(EGLDisplay (*)(), eglGetCurrentDisplay);
    return fn ? put(HandleKind::kEglDisplay, fn()) : 0;
}

std::uint64_t egl_QueryContext(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLContext, EGLint, EGLint*), eglQueryContext);
    Words w{t};
    void* d = dpy(w.u32());
    void* c = ctx(w.u32());
    auto attr = static_cast<EGLint>(w.u32());
    return fn ? fn(d, c, attr, ptr<EGLint>(w.u32())) : 0;
}

std::uint64_t egl_SwapBuffers(Thread& t) {
    // Runs detached from the guest (a reentrant stub): the pacing may wait here for a good part of
    // a frame, and the garbage collector's signals must not wait with it.
    Words w{t};
    void* d = dpy(w.u32());
    void* s = srf(w.u32());
    // The finished frame, for live view when it is on.
    live_frame(d, s);
    // A render scale's surface: its size as the window's is now.
    follow_fixed_size(d, s);
    EGLBoolean ok = paced_swap(d, s);
    note_frame();
    unsigned n = static_cast<unsigned>(g_frames.load());
    if (g_trace && (n <= 3 || n % 120 == 0 || !ok)) {
        EGLint error = EGL_SUCCESS;
        if (!ok) t_traced_error = error = host_error();
        log("trace: eglSwapBuffers #%u (surface %p) -> %d, error %#x", n, s, ok, error);
    }
    return ok;
}

std::uint64_t egl_CopyBuffers(Thread&) { return EGL_FALSE; }

std::uint64_t egl_GetError(Thread&) {
    FN(EGLint (*)(), eglGetError);
    // One a trace line read first.
    if (t_traced_error != EGL_SUCCESS) {
        EGLint e = t_traced_error;
        t_traced_error = EGL_SUCCESS;
        return static_cast<std::uint32_t>(e);
    }
    return fn ? static_cast<std::uint32_t>(fn()) : EGL_SUCCESS;
}

std::uint64_t egl_BindAPI(Thread& t) {
    FN(EGLBoolean (*)(EGLenum), eglBindAPI);
    Words w{t};
    return fn ? fn(static_cast<EGLenum>(w.u32())) : 0;
}

std::uint64_t egl_QueryAPI(Thread&) {
    FN(EGLenum (*)(), eglQueryAPI);
    return fn ? fn() : EGL_OPENGL_ES_API;
}

std::uint64_t egl_ReleaseThread(Thread&) {
    FN(EGLBoolean (*)(), eglReleaseThread);
    return fn ? fn() : EGL_TRUE;
}

std::uint64_t egl_WaitClient(Thread&) {
    FN(EGLBoolean (*)(), eglWaitClient);
    return fn ? fn() : EGL_TRUE;
}

std::uint64_t egl_WaitGL(Thread&) {
    FN(EGLBoolean (*)(), eglWaitGL);
    return fn ? fn() : EGL_TRUE;
}

std::uint64_t egl_WaitNative(Thread& t) {
    FN(EGLBoolean (*)(EGLint), eglWaitNative);
    Words w{t};
    return fn ? fn(static_cast<EGLint>(w.u32())) : EGL_TRUE;
}

// EGL images: the client buffer is a handle (a host pointer) or, for GL texture and
// renderbuffer targets, an object name passed as a pointer.
std::uint64_t egl_CreateImageKHR(Thread& t) {
    FN(EGLImageKHR (*)(EGLDisplay, EGLContext, EGLenum, EGLClientBuffer, const EGLint*), eglCreateImageKHR);
    Words w{t};
    void* d = dpy(w.u32());
    void* c = ctx(w.u32());
    auto target = static_cast<EGLenum>(w.u32());
    std::uint32_t b = w.u32();
    void* buffer = (b & 0xf0000000) == 0x70000000 ? handles().get(HandleKind::kAny, b) : reinterpret_cast<void*>(static_cast<std::uintptr_t>(b));
    return fn ? put(HandleKind::kEglImage, fn(d, c, target, buffer, ptr<const EGLint>(w.u32()))) : 0;
}

std::uint64_t egl_DestroyImageKHR(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLImageKHR), eglDestroyImageKHR);
    Words w{t};
    void* d = dpy(w.u32());
    std::uint32_t i = w.u32();
    EGLBoolean ok = fn ? fn(d, img(i)) : EGL_FALSE;
    if (ok) handles().drop(HandleKind::kEglImage, i);
    return ok;
}

std::uint64_t egl_CreateSyncKHR(Thread& t) {
    FN(EGLSyncKHR (*)(EGLDisplay, EGLenum, const EGLint*), eglCreateSyncKHR);
    Words w{t};
    void* d = dpy(w.u32());
    auto type = static_cast<EGLenum>(w.u32());
    return fn ? put(HandleKind::kEglSync, fn(d, type, ptr<const EGLint>(w.u32()))) : 0;
}

std::uint64_t egl_DestroySyncKHR(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLSyncKHR), eglDestroySyncKHR);
    Words w{t};
    void* d = dpy(w.u32());
    std::uint32_t s = w.u32();
    EGLBoolean ok = fn ? fn(d, syn(s)) : EGL_FALSE;
    if (ok) handles().drop(HandleKind::kEglSync, s);
    return ok;
}

std::uint64_t egl_ClientWaitSyncKHR(Thread& t) {
    FN(EGLint (*)(EGLDisplay, EGLSyncKHR, EGLint, EGLTimeKHR), eglClientWaitSyncKHR);
    Words w{t};
    void* d = dpy(w.u32());
    void* s = syn(w.u32());
    auto flags = static_cast<EGLint>(w.u32());
    auto timeout = static_cast<EGLTimeKHR>(w.u64());
    return fn ? static_cast<std::uint32_t>(fn(d, s, flags, timeout)) : 0;
}

std::uint64_t egl_WaitSyncKHR(Thread& t) {
    FN(EGLint (*)(EGLDisplay, EGLSyncKHR, EGLint), eglWaitSyncKHR);
    Words w{t};
    void* d = dpy(w.u32());
    void* s = syn(w.u32());
    return fn ? static_cast<std::uint32_t>(fn(d, s, static_cast<EGLint>(w.u32()))) : 0;
}

std::uint64_t egl_SignalSyncKHR(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLSyncKHR, EGLenum), eglSignalSyncKHR);
    Words w{t};
    void* d = dpy(w.u32());
    void* s = syn(w.u32());
    return fn ? fn(d, s, static_cast<EGLenum>(w.u32())) : 0;
}

std::uint64_t egl_GetSyncAttribKHR(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLSyncKHR, EGLint, EGLint*), eglGetSyncAttribKHR);
    Words w{t};
    void* d = dpy(w.u32());
    void* s = syn(w.u32());
    auto attr = static_cast<EGLint>(w.u32());
    return fn ? fn(d, s, attr, ptr<EGLint>(w.u32())) : 0;
}

std::uint64_t egl_PresentationTimeANDROID(Thread& t) {
    FN(EGLBoolean (*)(EGLDisplay, EGLSurface, EGLnsecsANDROID), eglPresentationTimeANDROID);
    Words w{t};
    void* d = dpy(w.u32());
    void* s = srf(w.u32());
    auto time = static_cast<EGLnsecsANDROID>(w.u64());
    return fn ? fn(d, s, time) : 0;
}

std::uint64_t egl_LockSurfaceKHR(Thread&) { return EGL_FALSE; }
std::uint64_t egl_UnlockSurfaceKHR(Thread&) { return EGL_FALSE; }

std::uint64_t egl_GetSystemTimeFrequencyNV(Thread&) {
    FN(EGLuint64NV (*)(), eglGetSystemTimeFrequencyNV);
    return fn ? fn() : 0;
}

std::uint64_t egl_GetSystemTimeNV(Thread&) {
    FN(EGLuint64NV (*)(), eglGetSystemTimeNV);
    return fn ? fn() : 0;
}

// eglGetProcAddress: the guest stub of that name, if the host has the function. Reentrant:
// it asks the guest linker for the stub's address.
std::uint64_t egl_GetProcAddress(Thread& t) {
    Words w{t};
    gaddr name_ptr = w.u32();
    auto* name = static_cast<const char*>(gl_ptr(name_ptr));
    if (!name) return 0;
    bool is_egl = std::strncmp(name, "egl", 3) == 0;
    if (is_egl ? !egl_proc(name) : !gl_proc(name)) return 0;
    static gaddr gles = 0, egl = 0;
    Guest& g = Guest::get();
    if (!gles) gles = g.dlopen("libGLESv3.so", RTLD_NOW);
    if (!egl) egl = g.dlopen("libEGL.so", RTLD_NOW);
    return g.dlsym(is_egl ? egl : gles, name);
}

}  // namespace

void egl_register() {
#define R(name) register_host_fn(kEgl_egl##name, &egl_##name)
    R(BindAPI);
    R(BindTexImage);
    R(ChooseConfig);
    R(ClientWaitSyncKHR);
    R(CopyBuffers);
    R(CreateContext);
    R(CreateImageKHR);
    R(CreatePbufferFromClientBuffer);
    R(CreatePbufferSurface);
    R(CreatePixmapSurface);
    R(CreateSyncKHR);
    R(CreateWindowSurface);
    R(DestroyContext);
    R(DestroyImageKHR);
    R(DestroySurface);
    R(DestroySyncKHR);
    R(GetConfigAttrib);
    R(GetConfigs);
    R(GetCurrentContext);
    R(GetCurrentDisplay);
    R(GetCurrentSurface);
    R(GetDisplay);
    R(GetError);
    R(GetProcAddress);
    R(GetSyncAttribKHR);
    R(GetSystemTimeFrequencyNV);
    R(GetSystemTimeNV);
    R(Initialize);
    R(LockSurfaceKHR);
    R(MakeCurrent);
    R(PresentationTimeANDROID);
    R(QueryAPI);
    R(QueryContext);
    R(QueryString);
    R(QuerySurface);
    R(ReleaseTexImage);
    R(ReleaseThread);
    R(SignalSyncKHR);
    R(SurfaceAttrib);
    R(SwapBuffers);
    R(SwapInterval);
    R(Terminate);
    R(UnlockSurfaceKHR);
    R(WaitClient);
    R(WaitGL);
    R(WaitNative);
    R(WaitSyncKHR);
#undef R
}

}  // namespace arm32
