// The desktop player: the game's 32-bit libraries in the runtime, with the Java VM of arm32/jvm in place of the phone's.
// What its files share.
#pragma once

#include "jvm.h"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <filesystem>
#include <utility>
#include <vector>

namespace player {

// A host path as the C++ library's file streams take it, read as UTF-8: a narrow string would go through Windows' ANSI
// code page, which cannot spell every user folder's name (the player's manifest makes that UTF-8 too, from Windows 10
// 1903 on; this holds on any Windows).
inline std::filesystem::path utf8_path(const std::string& s) { return std::filesystem::path(std::u8string(s.begin(), s.end())); }

// The app as the game sees it on a phone: its package, where Android would have put its files (guest paths, which
// host_of maps to folders on this computer), and its screen.
struct App {
    std::string package;
    // The APK and the 32-bit library folder, where the package installer puts them.
    std::string apk, lib_dir;
    // Internal storage (Context.getFilesDir's parent) and the app's folder on external storage.
    std::string data_dir, external_dir;
    // On this computer: the guest's system, the agent, the game's libraries, the APK, and the folder for the app's data.
    std::string host_sysroot, host_agent, host_libs, host_apk, host_data;
    // The window in pixels, the display's refresh rate, and Android's density (DisplayMetrics.density: 1 at 160 dpi).
    int width = 1920, height = 1080;
    // The window's title, and whether its size is the screen's to decide (a start with no size asked for).
    std::string title = "OpenDMTQ";
    bool fit_screen = false;
    float refresh = 60, density = 2;
    // What the package declares (PackageInfo).
    std::string version_name = "1.0";
    int version_code = 1;
};
App& app();

// The host path of a guest path (the runtime's path_hook), and the guest name of a host file.
std::string host_of(const std::string& guest);
std::string guest_of(const std::string& host);

// An entry of the app's APK by its full name ("assets/bin/Data/..."), inflated (ndk.cpp); false when there is none.
bool apk_entry(const std::string& name, std::vector<std::uint8_t>& out);
// The names of the APK's files under `prefix` ("lib/armeabi-v7a/"), in order (ndk.cpp).
std::vector<std::string> apk_names(const std::string& prefix);
// An entry's content in short, its CRC-32 and size as the zip's directory gives them: two entries with the same stamp
// hold the same bytes ("" for none).
std::string apk_stamp(const std::string& name);

// A start with no arguments (own_folder.cpp): the app from the player's own folder (player.conf, the APK, runtime/), its
// libraries unpacked and its data and log in the user's folder for programs; false with `error` when that cannot be.
bool use_own_folder(std::string& error);
// A reason the player cannot go on, in the log and, on Windows, in a message box: a double click has no console.
void show_error(const std::string& what);
// A name for the calling thread, which the stats and a debugger show (threads.cpp).
void name_thread(const char* name);
// The computer's language and country ("ko", "KR"), for the game's locale (java_lang.cpp): the environment's locale on
// Linux (LC_ALL, LC_MESSAGES, LANG), the user's language on Windows unless the environment names one; en, US otherwise.
std::pair<std::string, std::string> host_locale();

// Loads a 32-bit library in the guest as System.load does on a phone with the runtime: dlopen, the natives it exports
// by name bound, then its JNI_OnLoad. Loading one again does nothing (the phone's VM keeps loaded libraries too).
bool load_library(const std::string& guest_path);

// Starts the stand-in for the phone's log daemon (logd.cpp) with its socket in dir; returns the socket's path, empty
// when it could not be made. set_log_socket points the guest's /dev/socket/logdw there.
std::string start_logd(const std::string& dir);
void set_log_socket(const std::string& path);

// The Java classes, by package. Each defines what the game calls in it.
void define_unity();
void define_android_app();

// The app's objects: the activity (also the context everything asks), the application, and the Unity player view.
jvm::Object* activity();
jvm::Object* application();
jvm::Object* unity_player();

// The window (window_x11.cpp): opened at the App's size; the android.view.Surface that names it; the window behind a
// Surface (0 for anything else); and its events, handled until the window is closed (false then).
bool open_window(const std::string& title);
jvm::Object* surface();
std::uintptr_t window_of(jvm::Object* surface);
bool pump_window();

// android.os.Looper (android_os.cpp): a thread's queue of jobs, each due at a time, run by that thread in time order
// (then in the order they were posted). Handlers, Choreographer and runOnUiThread post to one.
class Looper : public jvm::Object {
public:
    using Clock = std::chrono::steady_clock;
    explicit Looper(jvm::Class* cls) : Object(cls) {}
    // A job; `owner` and `what` let a handler take its messages back (removeMessages), `runnable` its runnables.
    void post(std::function<void()> job, Clock::time_point at, const void* owner = nullptr, int what = -1, const jvm::Object* runnable = nullptr);
    void post(std::function<void()> job) { post(std::move(job), Clock::now()); }
    // Takes back what an owner posted: its messages of one kind (what >= 0), a runnable of its, or all (neither).
    void remove(const void* owner, int what, const jvm::Object* runnable);
    bool has(const void* owner, int what);
    // Runs the jobs that are due, on the calling thread; returns when the next one is due (max() for none).
    Clock::time_point run_due();
    // Waits until `until` or until a job is posted.
    void wait(Clock::time_point until);
    std::atomic<bool> quitting{false};

private:
    struct Job {
        Clock::time_point at;
        std::uint64_t order;
        std::function<void()> fn;
        const void* owner;
        int what;
        const jvm::Object* runnable;
    };
    std::mutex lock_;
    std::condition_variable posted_;
    std::deque<Job> jobs_;
    std::uint64_t next_order_ = 0;
};
// java.lang.Thread (threads.cpp): what start, join and the rest need; classes that are threads (HandlerThread, Unity's
// WWW) derive from it.
class JThread : public jvm::Object {
public:
    using Object::Object;
    jvm::Ref<jvm::Object> target;
    std::string name;
    jint priority = 5;
    bool daemon = false;
    std::atomic<bool> interrupted{false};
    // 0 not started, 1 running, 2 ended.
    std::atomic<int> state{0};
    std::mutex lock;
    std::condition_variable ended;
    const jlong id = next_id();
    static jlong next_id() {
        static std::atomic<jlong> n{1};
        return n++;
    }
};

// A message to a C# script, as UnityPlayer.UnitySendMessage sends one (unity.cpp): the game object, its method, the text.
void send_to_unity(const std::string& object, const std::string& method, const std::string& message);
// One HTTP request with the player's client (web.cpp): false with `error` when no answer came; otherwise the status and
// the body, whatever the status.
bool http_request(const std::string& method, const std::string& url, const std::vector<std::pair<std::string, std::string>>& headers,
                  const std::string& body, int timeout_ms, int& status, std::string& reply, std::string& error);
// This computer's device id (Settings.Secure.ANDROID_ID, android_os.cpp): made once, kept in the data folder.
std::string device_id();

// The String keys and values of a java.util.Map (request headers), in its order.
std::vector<std::pair<std::string, std::string>> string_pairs(jvm::Object* map);

// The UI thread's looper (Looper.getMainLooper), the Unity main thread's, and the calling thread's (Looper.myLooper,
// null for a thread without one).
Looper& main_looper();
Looper& unity_looper();
Looper* current_looper();
// Gives the calling thread a looper (Looper.prepare), the one passed or a new one.
Looper& prepare_looper(Looper* looper = nullptr);
// The Java classes of android.os and android.view the game calls, and java.lang and java.util beyond what the VM itself
// has (java_lang.cpp), the sound output (audio.cpp) and the SDKs the game carries (sdk.cpp).
void define_android_os();
void define_java();
void define_audio();
// android.media's video classes and SurfaceTexture (media.cpp).
void define_media();
// The sound's counters in the log (mixer.h), if the game has used sound.
void report_audio();
void define_sdks();
void define_web();
void define_pmangplus();
void define_input();

// Touch input (input.cpp): finger `id` (the system's own number for it) put down (0), lifted (1), moved (2) or taken
// away by the system (3, the gesture cancelled) at window pixels, given to the game as Android's MotionEvents on the
// calling thread, which is the UI thread. touch() is one finger of its own: the mouse, and the taps a check planned by
// frame, through the hook the frame counter calls after each frame shown.
void finger(int id, int what, float x, float y);
void touch(int action, float x, float y);
void frame_shown(std::uint64_t n);
// The soft keyboard (input.cpp): whether the game asked for text, the text the keyboard types, and its keys.
constexpr int kKeyEnter = 1, kKeyEscape = 2, kKeyBackspace = 3;
bool typing();
void type_text(const std::string& utf8);
void type_key(int key);

}  // namespace player
