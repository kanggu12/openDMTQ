// Tweaks: static int fields of IL2CPP classes set from outside the game, such as its frame cap.
//
// The packer can put a text file next to the runtime (lib/<abi>/libarm32t-tweaks.so, extracted
// with the libraries), one tweak per line:
//
//   <assembly> <namespace, or - for none> <class> <field> <value, or fps>
//
// "fps" stands for the frame rate the app runs at (app_frame_rate: debug.arm32.framerate when
// set, otherwise the display's refresh rate as pacing.cpp follows it). While the swaps are paced
// it is twice that, so the game's own timer never holds a frame back from its refresh. The fields
// are set through the il2cpp API on Unity's main thread, at a native render call, once IL2CPP is
// up and that thread attached; the class is initialised first, so its static constructor cannot
// overwrite them afterwards. They are checked again every couple of seconds in case the game
// writes them back. The same calls read the game's own frame target (Application.targetFrameRate)
// for pacing.cpp's pace check.
#include "tweaks.h"

#include "pacing.h"

#include <atomic>
#include <fcntl.h>
#include <sstream>
#include <unistd.h>

namespace arm32 {

namespace {

struct Tweak {
    std::string assembly, ns, cls, field, value;
    gaddr field_info = 0;  // FieldInfo*, once found
    bool reported = false; // the first change was logged
};

std::vector<Tweak> g_tweaks;
gaddr g_il2cpp = 0;  // guest handle of libil2cpp.so
unsigned g_renders = 0;

// The il2cpp API entry points.
struct Api {
    gaddr thread_current, domain_get, assembly_open, assembly_image, class_from_name, field_from_name,
        class_init, static_get, static_set;
} g_api{};

// A tweak sets the game's frame cap ("fps"), and has found its field with the game's target getter
// resolved: only then does the frame rate follow the display (a cap that cannot follow would leave
// a 60 fps game on a 120 Hz panel, and a target that cannot be read leaves no pace check).
bool g_fps_tweak = false;
std::atomic<bool> g_fps_ready{false};
// Set once the low resolution has had its turn in this run.
bool g_low_resolution_done = false;
// Unity's Application.targetFrameRate getter (an internal call; 1: not found), and what it last
// gave: what the game itself aims at right now (without input it steps down, in menus and songs).
gaddr g_target_getter = 0;
std::atomic<int> g_game_target{0};
// Its setter (1: not found), so a new cap applies at once while the game is at the old one.
gaddr g_target_setter = 0;

// debug.arm32.framerate, read once; negative when unset.
float set_frame_rate() {
    static const float rate = [] {
        std::string value = setting("ARM32_FRAMERATE", "debug.arm32.framerate");
        return !value.empty() ? std::strtof(value.c_str(), nullptr) : -1.0f;
    }();
    return rate;
}

// A guest copy of a string, kept for the life of the process (the il2cpp calls only read them).
gaddr guest_string(const std::string& s) {
    static std::map<std::string, gaddr> strings;
    auto it = strings.find(s);
    if (it != strings.end()) return it->second;
    gaddr g = Guest::get().strdup(s);
    strings[s] = g;
    return g;
}

int value_of(const Tweak& t) {
    if (t.value != "fps") return std::atoi(t.value.c_str());
    return static_cast<int>(app_frame_rate() * (pacing_active() ? 2.0f : 1.0f));
}

// Finds the field and sets it when it differs. Runs on Unity's main thread.
void apply(Thread& th, Tweak& t) {
    Guest& g = Guest::get();
    auto call = [&](gaddr fn, std::initializer_list<std::uint32_t> args) { return static_cast<gaddr>(th.call(fn, args)); };
    if (!t.field_info) {
        gaddr domain = call(g_api.domain_get, {});
        gaddr assembly = domain ? call(g_api.assembly_open, {domain, guest_string(t.assembly)}) : 0;
        gaddr image = assembly ? call(g_api.assembly_image, {assembly}) : 0;
        gaddr cls = image ? call(g_api.class_from_name, {image, guest_string(t.ns == "-" ? "" : t.ns), guest_string(t.cls)}) : 0;
        if (!cls) return;
        // Run the static constructor now, so it cannot overwrite the value later.
        call(g_api.class_init, {cls});
        t.field_info = call(g_api.field_from_name, {cls, guest_string(t.field)});
        if (!t.field_info) {
            log("arm32: tweak: no field %s.%s", t.cls.c_str(), t.field.c_str());
            t.field_info = 1;  // never look again
            return;
        }
    }
    if (t.field_info == 1) return;
    static gaddr cell = g.malloc(4);
    call(g_api.static_get, {t.field_info, cell});
    int old = *g.proc.mem.ptr<std::int32_t>(cell);
    int want = value_of(t);
    // A frame rate of 0 asks the window for nothing; the game keeps its own cap then.
    if (old == want || (t.value == "fps" && want <= 0)) return;
    *g.proc.mem.ptr<std::int32_t>(cell) = want;
    call(g_api.static_set, {t.field_info, cell});
    // The game takes a new cap over only when it next sets its target. While it is at the old cap
    // (not stepped down for idling), the new one applies now: a fallback to 60 does not wait.
    if (t.value == "fps" && g_target_setter > 1 && g_game_target.load(std::memory_order_relaxed) == old) {
        call(g_target_setter, {static_cast<std::uint32_t>(want)});
        g_game_target.store(want, std::memory_order_relaxed);
    }
    if (!t.reported || g_trace) log("arm32: tweak: %s.%s %d -> %d", t.cls.c_str(), t.field.c_str(), old, want);
    t.reported = true;
}

// The game's own way to its low resolution, LowResolution.Apply(true), on a device that did not keep its frame rate at the panel's
// (framerate.h). Its static methods take a null first and the method's own information last, which the game itself passes as null.
void apply_low_resolution(Thread& th) {
    g_low_resolution_done = true;
    if (!low_resolution_wanted()) return;
    Guest& g = Guest::get();
    auto call = [&](gaddr fn, std::initializer_list<std::uint32_t> args) { return static_cast<gaddr>(th.call(fn, args)); };
    const gaddr method_from_name = g.dlsym(g_il2cpp, "il2cpp_class_get_method_from_name");
    gaddr domain = call(g_api.domain_get, {});
    gaddr assembly = domain ? call(g_api.assembly_open, {domain, guest_string("Assembly-CSharp")}) : 0;
    gaddr image = assembly ? call(g_api.assembly_image, {assembly}) : 0;
    gaddr cls = image ? call(g_api.class_from_name, {image, guest_string("Ares.Utility"), guest_string("LowResolution")}) : 0;
    gaddr method = cls && method_from_name ? call(method_from_name, {cls, guest_string("Apply"), 1}) : 0;
    if (!method) {
        log("arm32: resolution: no LowResolution.Apply; the panel's own stays");
        return;
    }
    call(g_api.class_init, {cls});
    // The code's address is the first thing in a method's information.
    auto code = [&](gaddr info) { return *g.proc.mem.ptr<std::uint32_t>(info); };
    call(code(method), {0, 1, 0});
    // And what the game does after it at its start: the older of its two UI systems is told the new size.
    gaddr width = call(method_from_name, {cls, guest_string("get_Width"), 0});
    gaddr height = call(method_from_name, {cls, guest_string("get_Height"), 0});
    gaddr screen = call(g_api.class_from_name, {image, guest_string(""), guest_string("NGUI2Screen")});
    gaddr update = screen ? call(method_from_name, {screen, guest_string("UpdateResolution"), 2}) : 0;
    if (width && height && update) {
        call(g_api.class_init, {screen});
        call(code(update), {0, call(code(width), {0, 0}), call(code(height), {0, 0}), 0});
    }
    log("arm32: resolution: the game's low resolution, as this device did not keep its frame rate at the panel's");
}

}  // namespace

bool frame_rate_follows_display() { return set_frame_rate() < 0 && g_fps_ready.load(std::memory_order_relaxed); }

float app_frame_rate() {
    if (frame_rate_follows_display()) return followed_frame_rate();
    // Set, or no tweak to raise the game's cap: the game's own 60 then.
    float rate = set_frame_rate();
    return rate >= 0 ? rate : 60.0f;
}

int game_target_frame_rate() { return g_game_target.load(std::memory_order_relaxed); }

void tweaks_load(const std::string& lib_dir) {
    // Read through open and read: on Windows the runtime's layer opens the path as UTF-8, which the C++ library's file
    // streams would not.
    std::string text;
    if (int fd = open((lib_dir + "/libarm32t-tweaks.so").c_str(), O_RDONLY | O_CLOEXEC); fd >= 0) {
        char buf[4096];
        for (ssize_t n; (n = read(fd, buf, sizeof buf)) > 0;) text.append(buf, static_cast<std::size_t>(n));
        close(fd);
    }
    std::istringstream f(text);
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
    if (!g_tweaks.empty()) log("arm32: %zu tweaks", g_tweaks.size());
}

void tweaks_library_loaded(const std::string& name, gaddr handle) {
    if (name == "libil2cpp.so") g_il2cpp = handle;
}

// None unless a host sets one (tweaks.h).
void (*g_render_hook)(Thread&) = nullptr;

void tweaks_render(Thread& th) {
    // The host's own work first: it needs no tweaks to run.
    if (g_render_hook) g_render_hook(th);
    if (g_tweaks.empty() || !g_il2cpp) return;
    // The game's frame target every 10th render call (it changes as the game idles), the tweaks
    // every 120th: twice a second at 60 fps, once at 120.
    const bool tweak_turn = g_renders % 120 == 0;
    if (g_renders++ % 10) return;
    Guest& g = Guest::get();
    if (!g_api.static_set) {
        g_api = Api{g.dlsym(g_il2cpp, "il2cpp_thread_current"), g.dlsym(g_il2cpp, "il2cpp_domain_get"),
                    g.dlsym(g_il2cpp, "il2cpp_domain_assembly_open"), g.dlsym(g_il2cpp, "il2cpp_assembly_get_image"),
                    g.dlsym(g_il2cpp, "il2cpp_class_from_name"), g.dlsym(g_il2cpp, "il2cpp_class_get_field_from_name"),
                    g.dlsym(g_il2cpp, "il2cpp_runtime_class_init"), g.dlsym(g_il2cpp, "il2cpp_field_static_get_value"),
                    g.dlsym(g_il2cpp, "il2cpp_field_static_set_value")};
        if (!g_api.thread_current || !g_api.static_set || !g_api.class_init) {
            log("arm32: tweaks: libil2cpp lacks the API; none applied");
            g_tweaks.clear();
            return;
        }
    }
    // Before il2cpp_init, or on a thread IL2CPP does not know, the API must not be used: the
    // current IL2CPP thread is null there (a thread-local read, safe at any time).
    if (!th.call(g_api.thread_current, {})) return;
    // The game's own frame target, for the pace check of a followed frame rate (pacing.cpp).
    if (!g_target_getter) {
        gaddr resolve = g.dlsym(g_il2cpp, "il2cpp_resolve_icall");
        g_target_getter = resolve ? static_cast<gaddr>(th.call(resolve, {guest_string("UnityEngine.Application::get_targetFrameRate")})) : 0;
        g_target_setter = resolve ? static_cast<gaddr>(th.call(resolve, {guest_string("UnityEngine.Application::set_targetFrameRate")})) : 0;
        if (!g_target_getter) {
            log("arm32: tweaks: no Application.targetFrameRate getter; frame rate pace check off");
            g_target_getter = 1;
        }
        if (!g_target_setter) g_target_setter = 1;
    }
    if (g_target_getter > 1) {
        const auto target = static_cast<std::int32_t>(th.call(g_target_getter, {}));
        if (g_game_target.exchange(target, std::memory_order_relaxed) != target && g_stats) log("stats: game frame target %d", target);
    }
    if (!g_low_resolution_done && g_renders > kLowResolutionRender) apply_low_resolution(th);
    if (!tweak_turn) return;
    for (Tweak& t : g_tweaks) apply(th, t);
    // The first turn on which the cap tweak found its field and the target can be read: the frame
    // rate follows the display from now on, and the window asks for its highest rate instead of 60.
    if (g_fps_tweak && g_target_getter > 1 && !g_fps_ready.load(std::memory_order_relaxed)) {
        bool found = false;
        for (const Tweak& t : g_tweaks) found |= t.value == "fps" && t.field_info > 1;
        if (found) {
            g_fps_ready.store(true, std::memory_order_relaxed);
            log("arm32: frame rate follows the display");
            request_window_frame_rate();
        }
    }
}

}  // namespace arm32
