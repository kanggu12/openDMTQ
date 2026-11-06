// The shim: live view and the display's frame rate for phones that run the game's 32-bit libraries
// themselves. On those phones the arm32 runtime never starts (the manifest's use32bitAbi sends them to
// lib/armeabi-v7a), so nothing stands between the game and the system. This library does what the
// runtime's bridges do there, and nothing else: the game's code stays native and untouched.
//
// The app loads it right after libunity.so (a line the patcher adds to UnityPlayer). Then:
//
// - libunity.so's imports of a few functions get pointed here, by rewriting its global offset table:
//   eglSwapBuffers and friends, for pictures and frame pacing, and dlsym, because FMOD finds OpenSL ES
//   with it. No code is changed, and everything else goes straight to the system as before.
// - OpenSL ES objects hand out interfaces that begin with a pointer to their table of methods. The
//   object's own memory holds that pointer, so each one the game makes gets a copy of the table in which
//   a few methods come here first: that is how the sound reaches live view.
// - The patcher's Java class com.opendmtq.Hook calls here before each native render call on Unity's main
//   thread, where the il2cpp API may be used (the game's frame cap, as tweaks.cpp does in the runtime),
//   and after each mix of FMOD's Java output on phones where FMOD uses that and not OpenSL ES.
//
// Nothing here may stop the game. Whatever cannot be found is left as it was, and when the game has died
// several times in a row soon after starting, the shim does nothing until a day has passed (the guard
// below). debug.arm32.shim 0 turns it off.
#include "framerate.h"
#include "host.h"
#include "live.h"
#include "pacing.h"

#include <SLES/OpenSLES.h>
#include <SLES/OpenSLES_Android.h>
#include <algorithm>
#include <android/log.h>
#include <android/native_window.h>
#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <elf.h>
#include <fcntl.h>
#include <fstream>
#include <link.h>
#include <map>
#include <mutex>
#include <pthread.h>
#include <signal.h>
#include <sstream>
#include <string>
#include <system_error>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/system_properties.h>
#include <thread>
#include <time.h>
#include <unistd.h>
#include <vector>

namespace arm32 {

// ---- what the shared code expects of its host (host.h)

bool g_stats = false;
std::atomic<std::uint64_t> g_frames{0};
thread_local std::int64_t t_guest_sleep_ns = 0;

bool requested(const char* /*env*/, const char* property, bool fallback) {
    char value[PROP_VALUE_MAX] = "";
    __system_property_get(property, value);
    if (value[0] == '1') return true;
    if (value[0] == '0') return false;
    return fallback;
}

void note_frame() { g_frames.fetch_add(1, std::memory_order_relaxed); }
void note_shown(float, bool) {}

void log(const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    __android_log_vprint(ANDROID_LOG_INFO, "arm32", fmt, args);
    va_end(args);
}

void* gl_proc(const char* name) {
    static void* lib = dlopen("libGLESv3.so", RTLD_NOW | RTLD_LOCAL);
    static void* lib2 = dlopen("libGLESv2.so", RTLD_NOW | RTLD_LOCAL);
    static void* egl = dlopen("libEGL.so", RTLD_NOW | RTLD_LOCAL);
    static auto get = egl ? reinterpret_cast<void* (*)(const char*)>(dlsym(egl, "eglGetProcAddress")) : nullptr;
    void* f = lib ? dlsym(lib, name) : nullptr;
    if (!f && lib2) f = dlsym(lib2, name);
    if (!f && get) f = get(name);
    return f;
}

namespace {

// ---- the game's frame cap, on Unity's main thread (the runtime's tweaks.cpp, for native code)

struct Tweak {
    std::string assembly, ns, cls, field, value;
    void* field_info = nullptr;
    bool none = false;  // the field does not exist: never look again
    bool reported = false;
};
std::vector<Tweak> g_tweaks;
unsigned g_renders = 0;
bool g_fps_tweak = false;
std::atomic<bool> g_fps_ready{false};
std::atomic<int> g_game_target{0};

struct Il2cpp {
    void* (*thread_current)();
    void* (*domain_get)();
    void* (*assembly_open)(void*, const char*);
    void* (*assembly_image)(void*);
    void* (*class_from_name)(void*, const char*, const char*);
    void* (*field_from_name)(void*, const char*);
    void (*class_init)(void*);
    void (*static_get)(void*, void*);
    void (*static_set)(void*, void*);
    void* (*resolve_icall)(const char*);
    const void* (*method_from_name)(void*, const char*, int);
    bool ok = false;
} g_il2cpp;
int (*g_target_get)() = nullptr;
void (*g_target_set)(int) = nullptr;
bool g_target_looked = false;

float set_frame_rate() {
    static const float rate = [] {
        char value[PROP_VALUE_MAX] = "";
        __system_property_get("debug.arm32.framerate", value);
        return value[0] ? std::strtof(value, nullptr) : -1.0f;
    }();
    return rate;
}

template <class T>
void look_up(void* lib, T& out, const char* name, bool& ok) {
    out = reinterpret_cast<T>(dlsym(lib, name));
    if (!out) ok = false;
}

// The il2cpp API, once libil2cpp.so is loaded (libunity.so does that during start-up).
bool load_il2cpp() {
    if (g_il2cpp.ok) return true;
    void* lib = dlopen("libil2cpp.so", RTLD_NOW | RTLD_NOLOAD);
    if (!lib) return false;
    bool ok = true;
    look_up(lib, g_il2cpp.thread_current, "il2cpp_thread_current", ok);
    look_up(lib, g_il2cpp.domain_get, "il2cpp_domain_get", ok);
    look_up(lib, g_il2cpp.assembly_open, "il2cpp_domain_assembly_open", ok);
    look_up(lib, g_il2cpp.assembly_image, "il2cpp_assembly_get_image", ok);
    look_up(lib, g_il2cpp.class_from_name, "il2cpp_class_from_name", ok);
    look_up(lib, g_il2cpp.field_from_name, "il2cpp_class_get_field_from_name", ok);
    look_up(lib, g_il2cpp.class_init, "il2cpp_runtime_class_init", ok);
    look_up(lib, g_il2cpp.static_get, "il2cpp_field_static_get_value", ok);
    look_up(lib, g_il2cpp.static_set, "il2cpp_field_static_set_value", ok);
    look_up(lib, g_il2cpp.resolve_icall, "il2cpp_resolve_icall", ok);
    look_up(lib, g_il2cpp.method_from_name, "il2cpp_class_get_method_from_name", ok);
    if (!ok) {
        log("arm32: shim: libil2cpp lacks the API; the game's frame cap stays");
        g_tweaks.clear();
        return false;
    }
    g_il2cpp.ok = true;
    return true;
}

void apply_tweak(Tweak& t) {
    if (t.none) return;
    if (!t.field_info) {
        void* domain = g_il2cpp.domain_get();
        void* assembly = domain ? g_il2cpp.assembly_open(domain, t.assembly.c_str()) : nullptr;
        void* image = assembly ? g_il2cpp.assembly_image(assembly) : nullptr;
        void* cls = image ? g_il2cpp.class_from_name(image, t.ns == "-" ? "" : t.ns.c_str(), t.cls.c_str()) : nullptr;
        if (!cls) return;
        // Run the static constructor now, so it cannot overwrite the value later.
        g_il2cpp.class_init(cls);
        t.field_info = g_il2cpp.field_from_name(cls, t.field.c_str());
        if (!t.field_info) {
            log("arm32: shim: no field %s.%s", t.cls.c_str(), t.field.c_str());
            t.none = true;
            return;
        }
    }
    std::int32_t old = 0;
    g_il2cpp.static_get(t.field_info, &old);
    std::int32_t want = t.value == "fps" ? static_cast<std::int32_t>(app_frame_rate() * (pacing_active() ? 2.0f : 1.0f)) : std::atoi(t.value.c_str());
    // A frame rate of 0 asks the window for nothing; the game keeps its own cap then.
    if (old == want || (t.value == "fps" && want <= 0)) return;
    g_il2cpp.static_set(t.field_info, &want);
    // The game takes a new cap over only when it next sets its target. While it is at the old cap (not
    // stepped down for idling), the new one applies now.
    if (t.value == "fps" && g_target_set && g_game_target.load(std::memory_order_relaxed) == old) {
        g_target_set(want);
        g_game_target.store(want, std::memory_order_relaxed);
    }
    if (!t.reported) log("arm32: shim: %s.%s %d -> %d", t.cls.c_str(), t.field.c_str(), old, want);
    t.reported = true;
}

// The game's own way to its low resolution, LowResolution.Apply(true), on a device that did not keep its frame rate at the panel's
// (framerate.h). Its static methods take a null first and the method's own information last, which the game itself passes as null.
bool g_low_resolution_done = false;
void apply_low_resolution() {
    g_low_resolution_done = true;
    if (!low_resolution_wanted()) return;
    void* domain = g_il2cpp.domain_get();
    void* assembly = domain ? g_il2cpp.assembly_open(domain, "Assembly-CSharp") : nullptr;
    void* image = assembly ? g_il2cpp.assembly_image(assembly) : nullptr;
    void* cls = image ? g_il2cpp.class_from_name(image, "Ares.Utility", "LowResolution") : nullptr;
    const void* method = cls ? g_il2cpp.method_from_name(cls, "Apply", 1) : nullptr;
    if (!method) {
        log("arm32: resolution: no LowResolution.Apply; the panel's own stays");
        return;
    }
    g_il2cpp.class_init(cls);
    // The code's address is the first thing in a method's information.
    auto code = [](const void* info) { return *static_cast<void* const*>(info); };
    reinterpret_cast<void (*)(void*, std::int32_t, void*)>(code(method))(nullptr, 1, nullptr);
    // And what the game does after it at its start: the older of its two UI systems is told the new size.
    const void* width = g_il2cpp.method_from_name(cls, "get_Width", 0);
    const void* height = g_il2cpp.method_from_name(cls, "get_Height", 0);
    void* screen = g_il2cpp.class_from_name(image, "", "NGUI2Screen");
    const void* update = screen ? g_il2cpp.method_from_name(screen, "UpdateResolution", 2) : nullptr;
    if (width && height && update) {
        g_il2cpp.class_init(screen);
        auto size = [&](const void* getter) { return reinterpret_cast<std::int32_t (*)(void*, void*)>(code(getter))(nullptr, nullptr); };
        reinterpret_cast<void (*)(void*, std::int32_t, std::int32_t, void*)>(code(update))(nullptr, size(width), size(height), nullptr);
    }
    log("arm32: resolution: the game's low resolution, as this device did not keep its frame rate at the panel's");
}

// Before each native render call, on Unity's main thread (Hook.render).
void on_render() {
    if (g_tweaks.empty()) return;
    // The game's frame target every 10th render call (it changes as the game idles), the tweaks every
    // 120th: twice a second at 60 fps, once at 120.
    const bool tweak_turn = g_renders % 120 == 0;
    if (g_renders++ % 10) return;
    if (!load_il2cpp()) return;
    // Before il2cpp_init the API must not be used: the current IL2CPP thread is null there.
    if (!g_il2cpp.thread_current()) return;
    if (!g_target_looked) {
        g_target_looked = true;
        g_target_get = reinterpret_cast<int (*)()>(g_il2cpp.resolve_icall("UnityEngine.Application::get_targetFrameRate()"));
        g_target_set = reinterpret_cast<void (*)(int)>(g_il2cpp.resolve_icall("UnityEngine.Application::set_targetFrameRate(System.Int32)"));
        if (!g_target_get) log("arm32: shim: no Application.targetFrameRate getter; the frame rate stays");
    }
    if (g_target_get) g_game_target.store(g_target_get(), std::memory_order_relaxed);
    if (!g_low_resolution_done && g_renders > kLowResolutionRender) apply_low_resolution();
    if (!tweak_turn) return;
    for (Tweak& t : g_tweaks) apply_tweak(t);
    if (g_fps_tweak && g_target_get && !g_fps_ready.load(std::memory_order_relaxed)) {
        bool found = false;
        for (const Tweak& t : g_tweaks) found |= t.value == "fps" && t.field_info;
        if (found) {
            g_fps_ready.store(true, std::memory_order_relaxed);
            log("arm32: frame rate follows the display");
            request_window_frame_rate();
        }
    }
}

// ---- EGL, from libunity.so's imports

EGLSurface (*g_create_window_surface)(EGLDisplay, EGLConfig, EGLNativeWindowType, const EGLint*);
EGLBoolean (*g_destroy_surface)(EGLDisplay, EGLSurface);
EGLBoolean (*g_destroy_context)(EGLDisplay, EGLContext);
EGLBoolean (*g_swap_interval)(EGLDisplay, EGLint);
void* (*g_dlsym)(void*, const char*);

EGLBoolean hook_swap(EGLDisplay d, EGLSurface s) {
    live_frame(d, s);
    const EGLBoolean ok = paced_swap(d, s);
    note_frame();
    return ok;
}

EGLSurface hook_create_window_surface(EGLDisplay d, EGLConfig c, EGLNativeWindowType w, const EGLint* attribs) {
    const EGLSurface s = g_create_window_surface(d, c, w, attribs);
    if (s != EGL_NO_SURFACE) game_window_surface(reinterpret_cast<ANativeWindow*>(w));
    return s;
}

EGLBoolean hook_destroy_surface(EGLDisplay d, EGLSurface s) {
    const EGLBoolean ok = g_destroy_surface(d, s);
    if (ok) pacing_surface_destroyed(s);
    return ok;
}

EGLBoolean hook_destroy_context(EGLDisplay d, EGLContext c) {
    const EGLBoolean ok = g_destroy_context(d, c);
    if (ok) live_context_destroyed(c);
    return ok;
}

EGLBoolean hook_swap_interval(EGLDisplay d, EGLint interval) { return g_swap_interval(d, pacing_swap_interval(interval)); }

// ---- OpenSL ES: per-object copies of the method tables

SLresult (*g_create_engine)(SLObjectItf*, SLuint32, const SLEngineOption*, SLuint32, const SLInterfaceID*, const SLboolean*);
// The interfaces asked about (values of the library's own SL_IID_ variables), found with slCreateEngine.
SLInterfaceID g_iid_engine, g_iid_queue, g_iid_android_queue;
std::mutex g_sl_lock;
// Each kind's real table, and the copy objects are given.
const SLObjectItf_* g_object_real;
SLObjectItf_ g_object_copy;
const SLEngineItf_* g_engine_real;
SLEngineItf_ g_engine_copy;
const SLAndroidSimpleBufferQueueItf_* g_queue_real;
SLAndroidSimpleBufferQueueItf_ g_queue_copy;
// What each player's buffers hold: rate in Hz, channels, bits (0: not integer samples).
std::map<const void*, std::array<int, 3>> g_formats;

bool same_iid(SLInterfaceID a, SLInterfaceID b) { return a && b && std::memcmp(a, b, sizeof *a) == 0; }

SLresult hook_get_interface(SLObjectItf self, const SLInterfaceID iid, void* out);

void wrap_object(SLObjectItf object) {
    std::lock_guard<std::mutex> l(g_sl_lock);
    const SLObjectItf_* table = *object;
    if (!g_object_real) {
        g_object_real = table;
        g_object_copy = *table;
        g_object_copy.GetInterface = hook_get_interface;
    }
    // Only the table this copy is of: a table we do not know stays.
    if (table == g_object_real) *const_cast<const SLObjectItf_**>(object) = &g_object_copy;
}

SLresult hook_create_player(SLEngineItf self, SLObjectItf* player, SLDataSource* source, SLDataSink* sink, SLuint32 n,
                            const SLInterfaceID* ids, const SLboolean* required) {
    const SLresult r = g_engine_real->CreateAudioPlayer(self, player, source, sink, n, ids, required);
    if (r != SL_RESULT_SUCCESS || !player || !*player) return r;
    if (source && source->pFormat) {
        const auto type = *static_cast<const SLuint32*>(source->pFormat);
        std::array<int, 3> format{};
        // The rates are in thousandths of a hertz.
        if (type == SL_DATAFORMAT_PCM) {
            const auto* pcm = static_cast<const SLDataFormat_PCM*>(source->pFormat);
            format = {static_cast<int>(pcm->samplesPerSec / 1000), static_cast<int>(pcm->numChannels), static_cast<int>(pcm->bitsPerSample)};
        } else if (type == SL_ANDROID_DATAFORMAT_PCM_EX) {
            const auto* pcm = static_cast<const SLAndroidDataFormat_PCM_EX*>(source->pFormat);
            format = {static_cast<int>(pcm->sampleRate / 1000), static_cast<int>(pcm->numChannels),
                      pcm->representation == SL_ANDROID_PCM_REPRESENTATION_SIGNED_INT ? static_cast<int>(pcm->bitsPerSample) : 0};
        }
        std::lock_guard<std::mutex> l(g_sl_lock);
        g_formats[*player] = format;
    }
    wrap_object(*player);
    return r;
}

SLresult hook_enqueue(SLAndroidSimpleBufferQueueItf self, const void* buffer, SLuint32 size) {
    // The game's sound for live view, when that is on; this thread is the mixer's, and never waits.
    live_audio(self, buffer, size);
    return g_queue_real->Enqueue(self, buffer, size);
}

SLresult hook_get_interface(SLObjectItf self, const SLInterfaceID iid, void* out) {
    const SLresult r = g_object_real->GetInterface(self, iid, out);
    if (r != SL_RESULT_SUCCESS || !out) return r;
    if (same_iid(iid, g_iid_engine)) {
        auto engine = *static_cast<SLEngineItf*>(out);
        std::lock_guard<std::mutex> l(g_sl_lock);
        if (!g_engine_real) {
            g_engine_real = *engine;
            g_engine_copy = *g_engine_real;
            g_engine_copy.CreateAudioPlayer = hook_create_player;
        }
        if (*engine == g_engine_real) *const_cast<const SLEngineItf_**>(engine) = &g_engine_copy;
    } else if (same_iid(iid, g_iid_android_queue) || same_iid(iid, g_iid_queue)) {
        // The two share their layout up to Enqueue.
        auto queue = *static_cast<SLAndroidSimpleBufferQueueItf*>(out);
        std::array<int, 3> format{};
        {
            std::lock_guard<std::mutex> l(g_sl_lock);
            if (!g_queue_real) {
                g_queue_real = *queue;
                g_queue_copy = *g_queue_real;
                g_queue_copy.Enqueue = hook_enqueue;
            }
            if (*queue == g_queue_real) *const_cast<const SLAndroidSimpleBufferQueueItf_**>(queue) = &g_queue_copy;
            auto it = g_formats.find(self);
            if (it != g_formats.end()) {
                format = it->second;
                g_formats.erase(it);
            }
        }
        live_audio_source(queue, format[0], format[1], format[2]);
    }
    return r;
}

// The library's interface identifiers: variables holding pointers.
void find_interface_ids() {
    if (g_iid_engine) return;
    void* lib = dlopen("libOpenSLES.so", RTLD_NOW | RTLD_LOCAL);
    if (!lib) return;
    auto iid = [&](const char* what) {
        auto* variable = static_cast<SLInterfaceID*>(dlsym(lib, what));
        return variable ? *variable : nullptr;
    };
    g_iid_queue = iid("SL_IID_BUFFERQUEUE");
    g_iid_android_queue = iid("SL_IID_ANDROIDSIMPLEBUFFERQUEUE");
    g_iid_engine = iid("SL_IID_ENGINE");
}

SLresult hook_create_engine(SLObjectItf* engine, SLuint32 n, const SLEngineOption* options, SLuint32 m, const SLInterfaceID* ids, const SLboolean* required) {
    find_interface_ids();
    const SLresult r = g_create_engine(engine, n, options, m, ids, required);
    if (r == SL_RESULT_SUCCESS && engine && *engine) wrap_object(*engine);
    return r;
}

// FMOD finds slCreateEngine with dlsym in libOpenSLES.so.
void* hook_dlsym(void* handle, const char* name) {
    void* found = g_dlsym(handle, name);
    if (found && name && std::strcmp(name, "slCreateEngine") == 0) {
        g_create_engine = reinterpret_cast<decltype(g_create_engine)>(found);
        return reinterpret_cast<void*>(hook_create_engine);
    }
    return found;
}

// ---- pointing a library's imports here

void* (*g_dlopen)(const char*, int);
void* hook_dlopen(const char* path, int flags);

struct Import {
    const char* name;
    void* hook;
    void** real;  // gets the system's function (null: nothing keeps it)
};

// libunity.so's: the picture, and how it loads and looks into other libraries.
const Import kUnityImports[] = {
    {"eglSwapBuffers", reinterpret_cast<void*>(hook_swap), nullptr},
    {"eglCreateWindowSurface", reinterpret_cast<void*>(hook_create_window_surface), reinterpret_cast<void**>(&g_create_window_surface)},
    {"eglDestroySurface", reinterpret_cast<void*>(hook_destroy_surface), reinterpret_cast<void**>(&g_destroy_surface)},
    {"eglDestroyContext", reinterpret_cast<void*>(hook_destroy_context), reinterpret_cast<void**>(&g_destroy_context)},
    {"eglSwapInterval", reinterpret_cast<void*>(hook_swap_interval), reinterpret_cast<void**>(&g_swap_interval)},
    {"dlsym", reinterpret_cast<void*>(hook_dlsym), reinterpret_cast<void**>(&g_dlsym)},
    {"dlopen", reinterpret_cast<void*>(hook_dlopen), reinterpret_cast<void**>(&g_dlopen)},
};
// The libraries it loads that matter: libil2cpp.so, which loads libopenal.so, the game's music and
// sound, which links OpenSL ES directly.
const Import kLoadedImports[] = {
    {"dlsym", reinterpret_cast<void*>(hook_dlsym), reinterpret_cast<void**>(&g_dlsym)},
    {"dlopen", reinterpret_cast<void*>(hook_dlopen), reinterpret_cast<void**>(&g_dlopen)},
    {"slCreateEngine", reinterpret_cast<void*>(hook_create_engine), reinterpret_cast<void**>(&g_create_engine)},
};

struct Target {
    const char* wanted = nullptr;  // the end of the library's file name
    ElfW(Addr) base = 0;
    const ElfW(Phdr)* phdr = nullptr;
    int phnum = 0;
};

int find_library(struct dl_phdr_info* info, size_t, void* data) {
    auto* t = static_cast<Target*>(data);
    const char* name = info->dlpi_name;
    const std::size_t n = name ? std::strlen(name) : 0, m = std::strlen(t->wanted);
    if (n >= m && std::strcmp(name + n - m, t->wanted) == 0) {
        t->base = info->dlpi_addr;
        t->phdr = info->dlpi_phdr;
        t->phnum = info->dlpi_phnum;
        return 1;
    }
    return 0;
}

// `slot` to `value`. The part of a library that is read-only once linked (PT_GNU_RELRO, where such tables
// usually are) is made writable for that and put back; anywhere else the page is left as it is.
bool write_slot(void** slot, void* value, ElfW(Addr) relro_start, ElfW(Addr) relro_end) {
    const auto page = static_cast<std::uintptr_t>(sysconf(_SC_PAGESIZE));
    const auto at = reinterpret_cast<std::uintptr_t>(slot);
    void* start = reinterpret_cast<void*>(at & ~(page - 1));
    const bool relro = at >= relro_start && at < relro_end;
    // Two threads can finish loading a library at once, and its slots share a page: one must not put the page back
    // while the other is about to write. Only around this: no loader call while holding it, a thread in the loader
    // may be waiting for it.
    static std::mutex one_writer;
    std::lock_guard<std::mutex> hold(one_writer);
    if (relro && mprotect(start, page, PROT_READ | PROT_WRITE) != 0) return false;
    *slot = value;
    if (relro) mprotect(start, page, PROT_READ);
    return true;
}

// Points the imports of the loaded library whose file name ends in `file` here. The number done.
template <std::size_t N>
int hook_library(const char* file, const Import (&imports)[N]) {
    Target t;
    t.wanted = file;
    if (!dl_iterate_phdr(find_library, &t) || !t.phdr) return 0;
    const ElfW(Dyn)* dynamic = nullptr;
    ElfW(Addr) relro_start = 0, relro_end = 0;
    for (int i = 0; i < t.phnum; ++i) {
        if (t.phdr[i].p_type == PT_DYNAMIC) dynamic = reinterpret_cast<const ElfW(Dyn)*>(t.base + t.phdr[i].p_vaddr);
        if (t.phdr[i].p_type == PT_GNU_RELRO) {
            relro_start = t.base + t.phdr[i].p_vaddr;
            relro_end = relro_start + t.phdr[i].p_memsz;
        }
    }
    if (!dynamic) return 0;
    const Elf32_Sym* symbols = nullptr;
    const char* strings = nullptr;
    const Elf32_Rel* tables[2] = {nullptr, nullptr};
    std::size_t sizes[2] = {0, 0};
    for (const ElfW(Dyn)* d = dynamic; d->d_tag != DT_NULL; ++d) {
        switch (d->d_tag) {
        case DT_SYMTAB: symbols = reinterpret_cast<const Elf32_Sym*>(t.base + d->d_un.d_ptr); break;
        case DT_STRTAB: strings = reinterpret_cast<const char*>(t.base + d->d_un.d_ptr); break;
        case DT_REL: tables[0] = reinterpret_cast<const Elf32_Rel*>(t.base + d->d_un.d_ptr); break;
        case DT_RELSZ: sizes[0] = d->d_un.d_val; break;
        case DT_JMPREL: tables[1] = reinterpret_cast<const Elf32_Rel*>(t.base + d->d_un.d_ptr); break;
        case DT_PLTRELSZ: sizes[1] = d->d_un.d_val; break;
        default: break;
        }
    }
    if (!symbols || !strings) return 0;
    int done = 0;
    for (int which = 0; which < 2; ++which) {
        for (std::size_t i = 0; tables[which] && i < sizes[which] / sizeof(Elf32_Rel); ++i) {
            const Elf32_Rel& rel = tables[which][i];
            const auto type = ELF32_R_TYPE(rel.r_info);
            if (type != R_ARM_JUMP_SLOT && type != R_ARM_GLOB_DAT && type != R_ARM_ABS32) continue;
            const auto symbol = ELF32_R_SYM(rel.r_info);
            if (!symbol) continue;
            const char* name = strings + symbols[symbol].st_name;
            for (const Import& import : imports) {
                if (std::strcmp(name, import.name) != 0) continue;
                auto** slot = reinterpret_cast<void**>(t.base + rel.r_offset);
                if (import.real && !*import.real) *import.real = *slot;
                // Only a slot holding the system's function: not one holding an addend, or done before.
                if (*slot && (!import.real || *slot == *import.real) && write_slot(slot, import.hook, relro_start, relro_end)) ++done;
                break;
            }
        }
    }
    return done;
}

void* hook_dlopen(const char* path, int flags) {
    void* handle = g_dlopen(path, flags);
    if (handle && path) {
        for (const char* file : {"libil2cpp.so", "libopenal.so"}) {
            const std::size_t n = std::strlen(path), m = std::strlen(file);
            if (n >= m && std::strcmp(path + n - m, file) == 0) {
                const int done = hook_library(file, kLoadedImports);
                if (done) log("arm32: shim: %d imports of %s point here", done, file);
            }
        }
    }
    return handle;
}

// ---- the guard: a shim that makes the game die must not keep it dead
//
// What counts is a crash of this process, whenever it comes: broadcasting starts well after the game does. A person
// closing the game, or the system killing it, is not one. Three crashes within a day switch the shim off for a day,
// and then one more decides. Two ways to notice, both as small files in the app's own folder:
// - A fatal signal after the first frame leaves a mark on its way through (next to nothing is allowed in a signal
//   handler: making a file is).
// - A start that never got as far as a frame leaves its mark behind: it hung, or died before there was a handler.

// The app's own folder, from the process's name and the user it runs as. Empty when that cannot be read or made.
std::string own_folder() {
    char name[256] = "";
    std::FILE* f = std::fopen("/proc/self/cmdline", "r");
    if (!f) return "";
    const std::size_t n = std::fread(name, 1, sizeof name - 1, f);
    std::fclose(f);
    name[n] = 0;
    // A helper process has its name after a colon; the app's folder has none of that.
    if (char* colon = std::strchr(name, ':')) *colon = 0;
    if (!name[0]) return "";
    // /data/data is the first user's folder only; a work profile or second user has its own.
    const std::string data = "/data/user/" + std::to_string(getuid() / 100000) + "/" + name;
    const std::string files = data + "/files";
    // A first start: nothing may have made it yet.
    if (mkdir(files.c_str(), 0700) != 0 && errno != EEXIST) return "";
    return files;
}

// Where the marks go, fixed once before any handler can read them.
char g_crash_mark[320] = "";
std::string g_start_mark;
// Whether this process has left the mark: one file per incident, not one per signal.
std::atomic<bool> g_marked{false};

// The fatal signals, and what stood before this handler, to hand each signal on to.
struct sigaction g_before[NSIG];
const int kFatalSignals[] = {SIGSEGV, SIGBUS, SIGILL, SIGABRT, SIGFPE};

void on_fatal_signal(int sig, siginfo_t* info, void* context) {
    // Only what a signal handler may do: open(2) and close(2).
    if (g_crash_mark[0] && !g_marked.exchange(true, std::memory_order_relaxed)) {
        const int fd = open(g_crash_mark, O_CREAT | O_WRONLY | O_CLOEXEC, 0600);
        if (fd >= 0) close(fd);
    }
    const struct sigaction& to = g_before[sig];
    if ((to.sa_flags & SA_SIGINFO) && to.sa_sigaction) {
        to.sa_sigaction(sig, info, context);
        return;
    }
    if (!(to.sa_flags & SA_SIGINFO) && to.sa_handler != SIG_DFL && to.sa_handler != SIG_IGN) {
        to.sa_handler(sig);
        return;
    }
    // Nobody before this one: the system's default, which ends the process. An ignored fault would come back at once
    // and for ever. The signal is blocked here, so it comes the moment this handler returns.
    signal(sig, SIG_DFL);
    raise(sig);
}

// On top of the handlers there are, once, at the first frame: the game's libraries install their own while they start,
// and not all of them pass on what they cannot handle. Before that the start mark does the counting.
void watch_fatal_signals() {
    if (!g_crash_mark[0]) return;
    struct sigaction mine{};
    mine.sa_sigaction = on_fatal_signal;
    // On the thread's alternate stack: a stack overflow must get here too.
    mine.sa_flags = SA_SIGINFO | SA_ONSTACK | SA_RESTART;
    sigemptyset(&mine.sa_mask);
    for (const int sig : kFatalSignals) {
        // What this handler will call has to be there before the handler can run.
        if (sigaction(sig, nullptr, &g_before[sig]) != 0) continue;
        std::atomic_signal_fence(std::memory_order_seq_cst);
        sigaction(sig, &mine, nullptr);
    }
}

bool file_exists(const char* path) {
    struct stat st{};
    return stat(path, &st) == 0;
}

// Reads the marks the last run left. False when the shim is to stay off for now. The file holds the number of crashes
// and the folder of the app's libraries, which an update changes: a new version starts with a clean slate. Its age
// says when the last crash was.
bool guard_allows(const std::string& library_folder) {
    const std::string folder = own_folder();
    if (folder.empty() || folder.size() + 40 > sizeof g_crash_mark) {
        log("arm32: shim: no folder for the crash guard");
        return true;
    }
    const std::string path = folder + "/.opendmtq-shim";
    std::snprintf(g_crash_mark, sizeof g_crash_mark, "%s-crash", path.c_str());
    g_start_mark = path + "-start";
    int count = 0;
    std::string saved_for;
    {
        std::ifstream in(path);
        in >> count >> saved_for;
    }
    if (saved_for != library_folder) count = 0;
    const bool crashed = file_exists(g_crash_mark), never_drew = file_exists(g_start_mark.c_str());
    unlink(g_crash_mark);
    const auto write_count = [&](int n) {
        std::ofstream out(path, std::ios::trunc);
        out << n << ' ' << library_folder;
    };
    // The last crash was over a day ago: three a month apart are not "three within a day". After a day off: one more try,
    // and a crash now counts as the third again.
    struct stat st{};
    timespec now{};
    clock_gettime(CLOCK_REALTIME, &now);
    const bool old = stat(path.c_str(), &st) == 0 && now.tv_sec - st.st_mtime > 24 * 3600;
    if (old) count = count >= 3 ? 2 : 0;
    if (crashed || never_drew) {
        ++count;
        write_count(count);
        log("arm32: shim: the last run %s (%d)", crashed ? "crashed" : "ended before its first frame", count);
    } else if (old) {
        if (count) write_count(count); else unlink(path.c_str());
    }
    if (count >= 3) {
        unlink(g_start_mark.c_str());
        g_crash_mark[0] = 0;
        log("arm32: shim: %d crashes within a day; off for now", count);
        return false;
    }
    // Stays until the first frame.
    std::ofstream(g_start_mark, std::ios::trunc).flush();
    return true;
}

// The shim's own thread: the guard, and the phone's temperature for the frame rate.
void watch_thread() {
    // No signals meant for the game here; but a fault of this thread's own must reach the handler to be counted.
    sigset_t all;
    sigfillset(&all);
    for (const int sig : kFatalSignals) sigdelset(&all, sig);
    pthread_sigmask(SIG_BLOCK, &all, nullptr);
    pthread_setname_np(pthread_self(), "arm32-shim");
    setpriority(PRIO_PROCESS, static_cast<id_t>(gettid()), 10);
    bool drew = false, seen_mark = false;
    for (int tick = 1;; ++tick) {
        std::this_thread::sleep_for(std::chrono::seconds(2));
        if (!drew && g_frames.load(std::memory_order_relaxed) > 0) {
            drew = true;
            unlink(g_start_mark.c_str());
            // The game's libraries have installed theirs by now: on top of them, for the rest of this run.
            watch_fatal_signals();
        }
        // A signal's mark and still alive a full turn later: it was handled, so no crash after all. Not sooner: a real
        // crash takes a moment to stop this thread too.
        if (seen_mark) {
            unlink(g_crash_mark);
            g_marked.store(false, std::memory_order_relaxed);
            seen_mark = false;
        } else if (g_marked.load(std::memory_order_relaxed)) {
            seen_mark = true;
        }
        if (tick % 5 == 0) pacing_thermal_tick();
    }
}

// ---- Java: com.opendmtq.Hook

void JNICALL native_render(JNIEnv*, jclass) { on_render(); }

// FMOD's Java output has mixed into `buffer`: 16-bit stereo at `rate`.
void JNICALL native_mix(JNIEnv* env, jclass, jobject buffer, jint rate) {
    static const char tag = 0;
    live_audio_source(&tag, rate, 2, 16);
    live_audio(&tag, env->GetDirectBufferAddress(buffer), static_cast<std::size_t>(env->GetDirectBufferCapacity(buffer)));
}

void load_tweaks(const std::string& dir) {
    std::ifstream f(dir + "/libarm32t-tweaks.so");
    std::string line;
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream in(line);
        Tweak t;
        if (in >> t.assembly >> t.ns >> t.cls >> t.field >> t.value) {
            if (t.value == "fps") g_fps_tweak = true;
            g_tweaks.push_back(t);
        }
    }
}

}  // namespace

bool frame_rate_follows_display() { return set_frame_rate() < 0 && g_fps_ready.load(std::memory_order_relaxed); }

float app_frame_rate() {
    if (frame_rate_follows_display()) return followed_frame_rate();
    const float rate = set_frame_rate();
    return rate >= 0 ? rate : 60.0f;
}

int game_target_frame_rate() { return g_game_target.load(std::memory_order_relaxed); }

}  // namespace arm32

extern "C" __attribute__((visibility("default"))) jint JNI_OnLoad(JavaVM* vm, void*) {
    using namespace arm32;
    JNIEnv* env = nullptr;
    if (vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6) != JNI_OK) return JNI_VERSION_1_6;
    g_stats = requested("", "debug.arm32.stats", false);
    if (!requested("", "debug.arm32.shim", true)) return JNI_VERSION_1_6;
    // This library's folder holds the packer's tweaks file too, and tells versions of the app apart for the guard.
    Dl_info self{};
    std::string dir;
    if (dladdr(reinterpret_cast<void*>(JNI_OnLoad), &self) && self.dli_fname) {
        dir = self.dli_fname;
        dir = dir.substr(0, dir.rfind('/'));
    }
    if (!guard_allows(dir)) return JNI_VERSION_1_6;
    load_tweaks(dir);
    const int done = hook_library("libunity.so", kUnityImports);
    log("arm32: shim: %d imports of libunity.so point here", done);
    if (!done) return JNI_VERSION_1_6;
    live_load(vm, env, dir);
    // The Java side: until "ready" is set it does not call in.
    jclass hook = env->FindClass("com/opendmtq/Hook");
    if (hook) {
        const JNINativeMethod methods[] = {
            {"onRender", "()V", reinterpret_cast<void*>(native_render)},
            {"onMix", "(Ljava/nio/ByteBuffer;I)V", reinterpret_cast<void*>(native_mix)},
        };
        if (env->RegisterNatives(hook, methods, 2) == JNI_OK) {
            jfieldID ready = env->GetStaticFieldID(hook, "ready", "Z");
            if (ready) env->SetStaticBooleanField(hook, ready, JNI_TRUE);
        }
    }
    if (env->ExceptionCheck()) env->ExceptionClear();
    try {
        std::thread(watch_thread).detach();
    } catch (const std::system_error&) {
        log("arm32: shim: cannot start its thread");
    }
    log("arm32: shim: on");
    return JNI_VERSION_1_6;
}
