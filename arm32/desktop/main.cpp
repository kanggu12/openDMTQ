// The desktop player: the game's 32-bit libraries started in the runtime with the Java VM of arm32/jvm in place of the
// phone's, and the Java side of Unity 5.6's player taken over in C++: the libraries load as UnityPlayer's Java loads them
// (System.loadLibrary("main"), then NativeLoader.load with the app's library folder), and the player starts as its
// constructor starts it (initJni, nativeFile, nativeInitWWW, nativeInitWebRequest).
//
//   player --sysroot DIR --agent FILE --package NAME --apk FILE --libs DIR --data DIR [--size WxH] [--refresh HZ] [--seconds N]
//   player --app DIR [--settings FILE]     the PC client's start
//   player                                 a double click: the app from the player's own folder
//   player --audio-devices                 the computer's sound devices, for the PC client
//
// --sysroot is the guest's system (bin/linker, lib/*.so, from the Android build), --agent the runtime's agent program,
// --package the app's package name, --apk the app's APK, --libs its 32-bit libraries (the APK's lib/armeabi-v7a, unpacked)
// and --data the folder for what the app keeps (its internal and external storage); --size the window (1920x1080),
// --refresh the display's rate (60, else the display's own where the window can read it), --seconds a time to leave
// after (none). --app names a folder with player.conf and the APK in place of all those (own_folder.cpp), and --settings
// the PC's settings for the picture and the sound (settings.cpp). ARM32_TRACE=1 logs every registration and every class
// and method the VM makes up.
#include "gl_bridge.h"
#include "guest.h"
#include "host.h"
#include "jni_bridge.h"
#include "mixer.h"
#include "pacing.h"
#include "player.h"
#include "tweaks.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <filesystem>
#include <mutex>
#include <set>
#include <string>
#include <string_view>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace player {

#ifdef _WIN32
// A computer with two GPUs (most gaming laptops: an integrated one and a fast one) runs a program on the integrated one
// unless the program asks otherwise. NVIDIA's and AMD's drivers read these two exports of the program itself, at its
// start, and put its Direct3D (ANGLE's, under the game's OpenGL ES) on the fast GPU. A computer with one GPU reads
// nothing from them.
extern "C" {
__declspec(dllexport) unsigned long NvOptimusEnablement = 1;
__declspec(dllexport) int AmdPowerXpressRequestHighPerformance = 1;
}
#endif

namespace {

// Whether the guest's names are fenced in (guest_paths.h): on Windows, where the app is a server's and the player is
// what a person runs; not in the desktop player for Linux, a developer's tool that reads the host's own /proc and /dev.
#ifdef _WIN32
constexpr bool kFenced = true;
#else
constexpr bool kFenced = false;
#endif

// How many of the names the fence refused or put in the guest's root the log names: enough for a game's few, not a
// line for each name of a game that walks a folder tree.
constexpr std::size_t kFencedNamesLogged = 32;

// A name of the guest's that the fence refused or put in the guest's root (`host` is where it went): in the log once
// each, the first kFencedNamesLogged of them, so that a run shows what the game names outside its own folders.
void note_fenced(const std::string& guest, const std::string& host) {
    const App& a = app();
    // Anything outside the data folder, or in one of the app's own folders there, is no news.
    if (host.compare(0, a.host_data.size(), a.host_data) != 0) return;
    const std::string_view rest = std::string_view(host).substr(a.host_data.size());
    const bool refused = rest == "/<refused>";
    if (!refused && rest != "/root" && !rest.starts_with("/root/")) return;
    // Guest threads ask at once: the names seen so far under a lock.
    static std::mutex lock;
    static std::set<std::string> seen;
    std::lock_guard<std::mutex> guard(lock);
    // Past the limit, one line says that the log stops naming them.
    if (seen.size() > kFencedNamesLogged || !seen.insert(guest).second) return;
    if (seen.size() > kFencedNamesLogged) {
        arm32::log("player: more of the guest's names outside its folders, not logged");
        return;
    }
    arm32::log("player: the guest's name %s %s", guest.c_str(), refused ? "is refused" : "is in the guest's root folder");
}

// The Windows layer's question before each call that would change a file or a folder (arm32_set_read_only): true for
// the player's folders that the guest only reads (guest_paths.h read_only). Each such path in the log once, the first
// kFencedNamesLogged of them, so that a run shows what was refused.
[[maybe_unused]] bool refuses_change(const char* path) {
    if (!paths::read_only(app(), path)) return false;
    // Guest threads ask at once: the paths seen so far under a lock.
    static std::mutex lock;
    static std::set<std::string> seen;
    std::lock_guard<std::mutex> guard(lock);
    if (seen.size() < kFencedNamesLogged && seen.insert(path).second) arm32::log("player: a change to %s is refused: the guest only reads it", path);
    return true;
}

}  // namespace

App& app() {
    static App a;
    return a;
}

std::string host_of(const std::string& path) {
    std::string host = paths::host_of(app(), path, kFenced);
    // On Windows a name outside the app's folders goes in the log, once.
    if (kFenced) note_fenced(path, host);
    return host;
}

std::string guest_of(const std::string& host) { return paths::guest_of(app(), host, kFenced); }

// Points /dev/socket/logdw at the player's log socket.
void set_log_socket(const std::string& path) { app().log_socket = path; }


bool load_library(const std::string& guest_path) {
    using namespace arm32;
    // Each library once, as the phone's VM loads each once; a second System.load of it succeeds at once.
    static std::mutex lock;
    static std::set<std::string> loaded;
    {
        std::lock_guard<std::mutex> l(lock);
        if (loaded.count(guest_path)) return true;
    }
    Guest& g = Guest::get();
    gaddr h = g.dlopen(guest_path, RTLD_NOW);
    if (!h) {
        log("player: cannot load %s: %s", guest_path.c_str(), g.dlerror().c_str());
        return false;
    }
    {
        std::lock_guard<std::mutex> l(lock);
        loaded.insert(guest_path);
    }
    // The tweaks set the game's fields through libil2cpp, which loads this way (UnityPlayer.loadLibrary).
    tweaks_library_loaded(guest_path.substr(guest_path.rfind('/') + 1), h);
    // The natives it exports by name first; its JNI_OnLoad registers its own after, and they win.
    jni_bind_exports(&jvm::attach().jni, h, host_of(guest_path));
    gaddr onload = g.dlsym(h, "JNI_OnLoad");
    jint version = onload ? jni_call_onload(onload) : JNI_VERSION_1_6;
    log("player: loaded %s, JNI_OnLoad %#x", guest_path.c_str(), static_cast<unsigned>(version));
    return true;
}

namespace {

// A size change on its way to the Unity thread (surface_changed): later ones while it waits are the same call.
std::atomic<bool> g_resize_posted{false};
// The game has quit (quit_game).
std::atomic<bool> g_quit{false};
// The game is held still (pause_game): asked for by the UI thread, and as the Unity thread last told the game.
std::atomic<bool> g_pause_wanted{false};
bool g_paused = false;

}  // namespace

void quit_game(const char* how) {
    if (g_quit.exchange(true)) return;
    jvm::log("player: the game quits (%s)", how);
    // The UI thread's wait ends at a posted job (its looper's wake), and its loop sees the flag.
    main_looper().post([] {});
}

bool game_quit() { return g_quit.load(); }

void pause_game(bool paused) {
    if (g_pause_wanted.exchange(paused) == paused) return;
    // On the Unity thread, in the order a phone's activity calls them: focus, then the life cycle, and back.
    unity_looper().post([] {
        const bool want = g_pause_wanted.load();
        // Several quick changes: only the last one counts, and none twice.
        if (want == g_paused) return;
        g_paused = want;
        jvm::Env& e = jvm::attach();
        if (want) {
            e.call(unity_player(), "nativeFocusChanged", "(Z)V", {jvm::Value::Z(false)});
            e.call(unity_player(), "nativePause", "()Z");
        } else {
            e.call(unity_player(), "nativeResume", "()V");
            e.call(unity_player(), "nativeFocusChanged", "(Z)V", {jvm::Value::Z(true)});
        }
        if (e.pending) {
            jvm::log("player: the game threw on %s", want ? "pause" : "resume");
            e.pending = {};
        }
        jvm::log("player: the game %s", want ? "is paused" : "goes on");
    });
}

bool game_paused() { return g_paused; }

void surface_changed() {
    // Before the game has its surface (the start makes it with the window's size) there is nothing to tell.
    jvm::Object* surface = player::surface();
    if (!surface || g_resize_posted.exchange(true)) return;
    // What UnityPlayer's surfaceChanged does on a phone: the graphics state again for the same surface, on the Unity
    // thread, which then reads the window's new size and draws at it.
    unity_looper().post([surface] {
        g_resize_posted.store(false);
        jvm::Env& e = jvm::attach();
        e.call(unity_player(), "nativeRecreateGfxState", "(ILandroid/view/Surface;)V", {jvm::Value::I(0), jvm::Value(surface)});
        if (e.pending) {
            jvm::log("player: nativeRecreateGfxState threw on a size change");
            e.pending = {};
        }
        jvm::log("player: the game's surface is now %dx%d", app().width, app().height);
    });
}

}  // namespace player

namespace {

// A pending exception after a step of the start is the step failing: logged with its message, and cleared for the
// next step.
bool step_ok(jvm::Env& env, const char* what) {
    if (!env.pending) return true;
    jvm::Ref<jvm::Object> ex = env.pending;
    env.pending = {};
    // The message kept in a Value while it is read (its String goes with the last reference to it).
    jvm::Value text = env.call(ex.get(), "getMessage", "()Ljava/lang/String;");
    auto* message = dynamic_cast<jvm::String*>(text.l());
    arm32::log("player: %s threw %s: %s", what, ex->cls()->java_name().c_str(), message ? message->utf8().c_str() : "");
    env.pending = {};
    return false;
}

// --seconds: how long the player runs before it reports and leaves (0: until the window closes).
int g_seconds = 0;

// With stats on: how long each of the game's frames took on its main thread (nativeRender, its wait for the render thread
// included), in the log every five seconds, so that a frame that came late shows which thread it lost its time on. On the
// Unity main thread only.
void note_game_frame(std::chrono::steady_clock::duration took) {
    static std::vector<float> frames;
    static auto since = std::chrono::steady_clock::now();
    frames.push_back(std::chrono::duration<float, std::milli>(took).count());
    const auto now = std::chrono::steady_clock::now();
    if (now - since < std::chrono::seconds(5)) return;
    std::sort(frames.begin(), frames.end());
    auto at = [](float q) { return frames[static_cast<std::size_t>(q * static_cast<float>(frames.size() - 1))]; };
    arm32::log("stats: the game's frames on its main thread ms p50 %.2f p95 %.2f p99 %.2f max %.2f, %zu frames", at(0.5f), at(0.95f),
               at(0.99f), frames.back(), frames.size());
    frames.clear();
    since = now;
}

// mkdir -p.
void make_dirs(const std::string& path) {
    for (std::size_t i = 1; i <= path.size(); ++i) {
        if (i == path.size() || path[i] == '/') mkdir(path.substr(0, i).c_str(), 0755);
    }
}

}  // namespace

int main(int argc, char** argv) {
    using namespace arm32;
    using player::app;
#ifdef _WIN32
    // A test's unlisted run (PLAYER_WINDOW_UNLISTED) asked about first thing: from here on Windows shows no box of its
    // own for it, a crash's included (window_win32.cpp).
    player::window_unlisted();
#endif
    // The sound devices this computer has, for the PC client's choice, as JSON lines: nothing else starts.
    if (argc == 2 && std::string(argv[1]) == "--audio-devices") {
        std::fputs(player::audio::list_devices().c_str(), stdout);
        return 0;
    }
    std::string settings_path, app_folder;
    bool size_given = false;
    for (int i = 1; i + 1 < argc; i += 2) {
        std::string k = argv[i], v = argv[i + 1];
        if (k == "--settings") settings_path = v;
        else if (k == "--app") app_folder = v;
        else if (k == "--sysroot") app().host_sysroot = v;
        else if (k == "--agent") app().host_agent = v;
        else if (k == "--package") app().package = v;
        else if (k == "--apk") app().host_apk = v;
        else if (k == "--libs") app().host_libs = v;
        else if (k == "--data") app().host_data = v;
        else if (k == "--seconds") g_seconds = std::atoi(v.c_str());
        else if (k == "--size") size_given = std::sscanf(v.c_str(), "%dx%d", &app().width, &app().height) == 2;
        else if (k == "--refresh") {
            app().refresh = std::strtof(v.c_str(), nullptr);
            app().refresh_set = true;
        }
    }
    player::App& a = app();
    // No arguments: a double click, the app from the player's own folder as the server's download lays it out; --app:
    // the PC client's start, the app from the folder it keeps for a server. Its log goes to the user's folder from here.
    const bool from_folder = argc == 1 || !app_folder.empty();
    // The language the launcher chose, before anything is said: a folder the player cannot use is said in it too.
    if (!settings_path.empty()) player::settings().language = player::settings_language(settings_path);
    if (from_folder) {
        std::string why;
        if (!player::use_own_folder(app_folder, why)) {
            player::show_error(why);
            return 1;
        }
    }
    // The PC's settings, from the client's file (in that log): the frame pacing's choices for the runtime, the sound's for
    // the mixer, and the window's size. A size on the command line comes first, then the settings' own; without either a
    // start from a folder or with settings fits the window to the display, and a test's start keeps 1920x1080.
    if (!settings_path.empty()) player::load_settings(settings_path);
    const player::Settings& st = player::settings();
    if (!size_given && st.window_w) {
        a.width = st.window_w;
        a.height = st.window_h;
    } else if (!size_given && (from_folder || !settings_path.empty())) {
        a.fit_screen = true;
    }
    g_host_vsync.store(st.vsync);
    g_host_fps_cap.store(st.fps);
    player::audio::Options& sound = player::audio::options();
    sound.device = st.audio_device;
    sound.exclusive = st.audio_exclusive;
    sound.buffer = st.audio_buffer;
    sound.volume = st.volume;
    if (a.host_sysroot.empty() || a.host_agent.empty() || a.package.empty() || a.host_apk.empty() || a.host_libs.empty() || a.host_data.empty()) {
        std::fprintf(stderr, "usage: %s --sysroot DIR --agent FILE --package NAME --apk FILE --libs DIR --data DIR\n", argv[0]);
        return 2;
    }
    // The folders and files given, as absolute paths: the player changes its current folder below.
    for (std::string* p : {&a.host_sysroot, &a.host_agent, &a.host_apk, &a.host_libs, &a.host_data}) {
        std::error_code ec;
        // UTF-8 in and out: a narrow string's conversion would go through Windows' ANSI code page.
        std::filesystem::path abs = std::filesystem::absolute(player::utf8_path(*p), ec);
        if (!ec) {
            // With "/" between the parts on Windows too (Win32 takes them): the runtime joins paths with "/", and the
            // folder the Windows layer's getcwd gives is spelt so, which guest_of must find the guest's root in.
            const std::u8string u = abs.lexically_normal().generic_u8string();
            *p = std::string(u.begin(), u.end());
        }
        // A folder's own trailing slash goes, for the prefix tests in host_of and guest_of.
        while (p->size() > 1 && p->back() == '/') p->pop_back();
    }
    // Where Android would have put the app (a 32-bit app's libraries under lib/arm).
    a.apk = "/data/app/" + a.package + "-1/base.apk";
    a.lib_dir = "/data/app/" + a.package + "-1/lib/arm";
    a.data_dir = "/data/data/" + a.package;
    a.external_dir = "/storage/emulated/0/Android/data/" + a.package;
    for (const char* sub : {"/internal", "/external", "/sdcard"}) make_dirs(a.host_data + sub);
    // The current folder: a phone app's is /, where it may not write. On Windows it is the guest's root in the data
    // folder, where its names outside the app's folders lie (guest_paths.h) and which getcwd names "/" as a phone does;
    // on Linux an empty folder of the data's. Either way a file the game names by a relative path lands there and
    // nowhere else.
    const std::string cwd = player::kFenced ? player::paths::root_folder(a) : a.host_data + "/cwd";
    make_dirs(cwd);
    if (chdir(cwd.c_str()) != 0) log("player: cannot enter %s", cwd.c_str());
    // The VM's log in the runtime's, one stream to read; the guest's own log lines too.
    jvm::set_log_sink([](const char* line) { log("%s", line); });
    player::set_log_socket(player::start_logd(a.host_data));
    // The Java classes, before any library loads and registers its natives with them.
    player::define_java();
    player::define_android_os();
    player::define_unity();
    player::define_android_app();
    player::define_audio();
    player::define_media();
    player::define_sdks();
    player::define_web();
    player::define_pmangplus();
    player::define_input();
    // This thread is the app's main thread: attached, as the phone's main thread is from the start, with the main looper.
    jvm::Env& env = jvm::attach();
    player::prepare_looper(&player::main_looper());
    Guest& g = Guest::get();
    g.proc.path_hook = player::host_of;
    g.proc.name_hook = player::guest_of;
#ifdef _WIN32
    // From here on the guest's system, the agent, the app's libraries and its APK only ever read (guest_paths.h
    // read_only): a write, a new file or folder, a delete or a rename there fails with EROFS in the Windows layer, as on
    // a phone's read-only /system, whether the game or the Java the player gives it asks. The libraries were unpacked
    // before (own_folder.cpp), and nothing of the player's writes there later.
    arm32_set_read_only(player::refuses_change);
#endif
    // The app's settings (app.cpp): fastmem, NEON without FPCR switches, atomics without the shared lock.
    g.proc.fastmem = requested("ARM32_FASTMEM", "", true);
    g.proc.mem.host_guards = g.proc.fastmem;
    g.proc.fast_neon = requested("ARM32_FAST_NEON", "", true);
    g.proc.fast_atomics = requested("ARM32_FAST_ATOMICS", "", true);
    // A phone's eight cores at most: the game sizes its worker threads by the count it is told (runtime.h says why).
    g.proc.max_cpus = 8;
    std::string error;
    if (!g.start(a.host_sysroot, "/system/bin/arm32-agent", {"PATH=/system/bin", "ANDROID_ROOT=/system", "ANDROID_DATA=/data", "LD_LIBRARY_PATH=/arm32/lib"}, error)) {
        player::show_error("cannot start the guest: " + error);
        return 1;
    }
    jni_init(jvm::java_vm());
    // The system API bridges behind the guest's libEGL, libGLESv2/3, libandroid and libOpenSLES, as in the app.
    gl_register();
    egl_register();
    android_register();
    opensl_register();
    // Hang dumps with tracing, performance counters with stats (ARM32_TRACE, ARM32_STATS), as in the app.
    start_diagnostics(g.proc);
    // PLAYER_DUMP_EVERY=N: every guest thread's place every N seconds, for finding what a busy thread is doing.
    if (const char* every = std::getenv("PLAYER_DUMP_EVERY"); every && std::atoi(every) > 0) {
        int seconds = std::atoi(every);
        std::thread([seconds, &g] {
            for (;;) {
                std::this_thread::sleep_for(std::chrono::seconds(seconds));
                dump_threads(g.proc);
            }
        }).detach();
    }
    // The packer's field settings for the game (its frame cap), from its file among the libraries.
    tweaks_load(a.host_libs);
    // UnityPlayer's static initializer: System.loadLibrary("main").
    if (!player::load_library(a.lib_dir + "/libmain.so")) {
        player::show_error("cannot load the app's libmain.so");
        return 1;
    }
    // Its constructor: NativeLoader.load(applicationInfo.nativeLibraryDir), where libmain loads libunity.
    jvm::Class& loader = *jvm::find_class("com/unity3d/player/NativeLoader");
    jvm::Value loaded = env.call_static(loader, "load", "(Ljava/lang/String;)Z", {jvm::Value(jvm::string(a.lib_dir))});
    log("player: NativeLoader.load returned %s", loaded.z() ? "true" : "false");
    if (!step_ok(env, "NativeLoader.load") || !loaded.z()) {
        player::show_error("the app's libraries did not load");
        return 1;
    }
    // Then initJni(context), nativeFile(getPackageCodePath()) and the two HTTP classes, in the constructor's order.
    jvm::Object* view = player::unity_player();
    env.call(view, "initJni", "(Landroid/content/Context;)V", {jvm::Value(player::activity())});
    step_ok(env, "initJni");
    env.call(view, "nativeFile", "(Ljava/lang/String;)V", {jvm::Value(jvm::string(a.apk))});
    step_ok(env, "nativeFile");
    env.call(view, "nativeInitWWW", "(Ljava/lang/Class;)V", {jvm::Value(jvm::find_class("com/unity3d/player/WWW"))});
    step_ok(env, "nativeInitWWW");
    env.call(view, "nativeInitWebRequest", "(Ljava/lang/Class;)V", {jvm::Value(jvm::find_class("com/unity3d/player/UnityWebRequest"))});
    step_ok(env, "nativeInitWebRequest");
    log("player: the player's constructor steps are done");
    // The window, and its surface as surfaceCreated hands it over: on this, the UI thread.
    if (!player::open_window(a.title)) {
        player::show_error("cannot open a window for the game");
        return 1;
    }
    env.call(view, "nativeRecreateGfxState", "(ILandroid/view/Surface;)V", {jvm::Value::I(0), jvm::Value(player::surface())});
    step_ok(env, "nativeRecreateGfxState");
    // windowFocusChanged(true), then resume: their jobs for the Unity main thread, in that order.
    player::unity_looper().post([view] {
        jvm::Env& e = jvm::attach();
        e.call(view, "nativeFocusChanged", "(Z)V", {jvm::Value::Z(true)});
        step_ok(e, "nativeFocusChanged");
    });
    player::unity_looper().post([view] {
        jvm::Env& e = jvm::attach();
        e.call(view, "nativeResume", "()V");
        step_ok(e, "nativeResume");
    });
    // The Unity main thread (UnityPlayer's "UnityMain", a looper thread): the jobs that are due, then a frame, for as
    // long as nativeRender says the game goes on.
    std::thread([view] {
        jvm::Env& e = jvm::attach();
        player::prepare_looper(&player::unity_looper());
        for (;;) {
            const auto next = player::unity_looper().run_due();
            // Paused: no frames, as a phone's Unity thread draws none while its app is away; only its jobs, until the
            // resume among them.
            if (player::game_paused()) {
                player::unity_looper().wait(std::min(next, std::chrono::steady_clock::now() + std::chrono::milliseconds(100)));
                continue;
            }
            const auto frame_start = std::chrono::steady_clock::now();
            jvm::Value more = e.call(view, "nativeRender", "()Z");
            if (arm32::g_stats) note_game_frame(std::chrono::steady_clock::now() - frame_start);
            step_ok(e, "nativeRender");
            if (!more.z()) {
                player::quit_game("its last frame");
                break;
            }
        }
    }).detach();
    // The UI thread: window events and the main looper's jobs, until the window closes or the time is up.
    const auto until = std::chrono::steady_clock::now() + std::chrono::seconds(g_seconds);
    while (player::pump_window() && !player::game_quit()) {
        auto next = player::main_looper().run_due();
        // Until the next job, a job posted, or a window event (a touch goes to the game as it comes).
        player::wait_for_events(next);
        if (g_seconds && std::chrono::steady_clock::now() >= until) break;
    }
    jvm::report_unimplemented();
    player::report_audio();
    std::fflush(stdout);
    // Guest threads are still running: leave without destructors or DLLs' detach code, as the runner does (log.cpp).
    arm32::exit_now(0);
}
