// The runtime inside an Android app.
//
// The APK's lib/arm64-v8a holds, next to the runtime, the guest's files under names the package
// installer extracts and the host linker never confuses with its own: libarm32s-<name> for the
// guest system (linker, C library, agent) and libarm32g-<name> for the app's 32-bit libraries.
// In their place under their own names are proxy libraries: Java loads a proxy, whose
// JNI_OnLoad starts the guest once, loads the 32-bit library of the same name in it and runs
// that library's JNI_OnLoad.
#include "gl_bridge.h"
#include "jni_bridge.h"
#include "live.h"
#include "tweaks.h"

#include <dlfcn.h>
#include <mutex>
#include <unistd.h>

namespace arm32 {

namespace {

std::once_flag g_start_once;
bool g_started = false;
std::string g_dir;  // the app's native library folder

bool exists(const std::string& p) { return access(p.c_str(), F_OK) == 0; }

// Where the guest's files are in the app's library folder.
std::string app_path(const std::string& path) {
    if (path.rfind("/system/bin/", 0) == 0) return g_dir + "/libarm32s-" + path.substr(12) + ".so";
    if (path.rfind("/system/lib/", 0) == 0) return g_dir + "/libarm32s-" + path.substr(12);
    // The guest's library search path.
    if (path.rfind("/arm32/lib/", 0) == 0) return g_dir + "/libarm32g-" + path.substr(11);
    // Guest code opening a library in the app folder by full path means the 32-bit one.
    if (path.size() > g_dir.size() + 1 && path.compare(0, g_dir.size() + 1, g_dir + "/") == 0) {
        std::string file = path.substr(g_dir.size() + 1);
        if (file.find('/') == std::string::npos && file.rfind("libarm32", 0) != 0) {
            std::string guest = g_dir + "/libarm32g-" + file;
            if (exists(guest)) return guest;
        }
    }
    return path;
}

// The names those files have for the guest (in /proc/self/maps and readlink).
std::string app_name(const std::string& host) {
    std::string g = g_dir + "/libarm32g-", s = g_dir + "/libarm32s-";
    if (host.rfind(g, 0) == 0) return g_dir + "/" + host.substr(g.size());
    if (host.rfind(s, 0) == 0) return "/system/lib/" + host.substr(s.size());
    return host;
}

}  // namespace

}  // namespace arm32

// Called by every proxy's JNI_OnLoad with the proxy's own path.
extern "C" __attribute__((visibility("default"))) jint arm32_proxy_onload(JavaVM* vm, const char* self_path) {
    using namespace arm32;
    std::string self = self_path ? self_path : "";
    std::string name = self.substr(self.rfind('/') + 1);
    std::call_once(g_start_once, [&] {
        g_dir = self.substr(0, self.rfind('/'));
        Guest& g = Guest::get();
        g.proc.path_hook = app_path;
        g.proc.name_hook = app_name;
        // Guest loads and stores straight to base + address, without the page table: a fifth less
        // CPU on the game's main thread. setprop debug.arm32.fastmem 0 turns it off.
        g.proc.fastmem = requested("ARM32_FASTMEM", "debug.arm32.fastmem", true);
        if (!g.proc.fastmem) log("arm32: fastmem off");
        // Without the page table in the way, guard pages fault only if the host closes them too.
        g.proc.mem.host_guards = g.proc.fastmem;
        // NEON float instructions without an FPCR switch around each one: twelve times faster
        // NEON maths (Unity's vectors, FMOD's mixing). setprop debug.arm32.fastneon 0 turns it off.
        g.proc.fast_neon = requested("ARM32_FAST_NEON", "debug.arm32.fastneon", true);
        if (!g.proc.fast_neon) log("arm32: fast NEON off");
        // Atomics without the monitor lock all threads share; setprop debug.arm32.fastatomics 0.
        g.proc.fast_atomics = requested("ARM32_FAST_ATOMICS", "debug.arm32.fastatomics", true);
        if (!g.proc.fast_atomics) log("arm32: fast atomics off");
        // Unity games do not depend on exact FPSCR sticky flags; see Process::fp_flags.
        std::string error;
        g_started = g.start(g_dir, "/system/bin/arm32-agent",
                            {"PATH=/system/bin", "ANDROID_ROOT=/system", "ANDROID_DATA=/data", "LD_LIBRARY_PATH=/arm32/lib"}, error);
        if (!g_started) {
            log("arm32: cannot start the guest: %s", error.c_str());
            return;
        }
        jni_init(vm);
        // The system API bridges behind the guest's libEGL, libGLESv2/3, libandroid and libOpenSLES.
        gl_register();
        egl_register();
        android_register();
        opensl_register();
        // Hang dumps with tracing, performance counters with stats.
        start_diagnostics(g.proc);
        // Field settings the packer gave for this game (its frame cap, for one).
        tweaks_load(g_dir);
        // The way to the server, for live view; here FindClass still sees the app's classes.
        JNIEnv* env = nullptr;
        if (vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6) == JNI_OK) {
            live_load(vm, env, g_dir);
            focus_watch_start(vm, env);
        }
    });
    if (!g_started) return JNI_ERR;
    Guest& g = Guest::get();
    if (g_trace) log("trace: loading the 32-bit %s", name.c_str());
    gaddr h = g.dlopen(g_dir + "/" + name, RTLD_NOW);
    if (!h) {
        log("arm32: cannot load the 32-bit %s: %s", name.c_str(), g.dlerror().c_str());
        return JNI_ERR;
    }
    // Native methods the library implements by name rather than registering them.
    JNIEnv* env = nullptr;
    if (vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6) == JNI_OK) jni_bind_exports(env, h, g_dir + "/libarm32g-" + name);
    tweaks_library_loaded(name, h);
    gaddr onload = g.dlsym(h, "JNI_OnLoad");
    jint version = onload ? jni_call_onload(onload) : JNI_VERSION_1_6;
    if (g_trace) log("trace: %s loaded, JNI_OnLoad returned %#x", name.c_str(), version);
    return version;
}
