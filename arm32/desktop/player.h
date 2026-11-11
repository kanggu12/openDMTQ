// The desktop player: the game's 32-bit libraries in the runtime, with the Java VM of arm32/jvm in place of the phone's.
// What its files share.
#pragma once

#include "guest_paths.h"
#include "jvm.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <mutex>
#include <numeric>
#include <string>
#include <filesystem>
#include <utility>
#include <vector>

namespace player {

// A host path as the C++ library's file streams take it, read as UTF-8: a narrow string would go through Windows' ANSI
// code page, which cannot spell every user folder's name (the player's manifest makes that UTF-8 too, from Windows 10
// 1903 on; this holds on any Windows).
inline std::filesystem::path utf8_path(const std::string& s) { return std::filesystem::path(std::u8string(s.begin(), s.end())); }

// The app as the game sees it on a phone: its package, where Android would have put its files and where they are on
// this computer (the layout host_of maps guest paths by, guest_paths.h), and its screen.
struct App : paths::Layout {
    // The window in pixels, the display's refresh rate, and Android's density (DisplayMetrics.density: 1 at 160 dpi).
    int width = 1920, height = 1080;
    // The window's title, and whether its size is the screen's to decide (a start with no size asked for).
    std::string title = "OpenDMTQ";
    bool fit_screen = false;
    float refresh = 60, density = 2;
    // Whether --refresh named the rate: then the game is told that one, and the display's own is not looked up.
    bool refresh_set = false;
    // What the package declares (PackageInfo).
    std::string version_name = "1.0";
    int version_code = 1;
};
App& app();

// The PC's own settings for the picture and the sound (settings.cpp has the file's keys), which the PC client chooses
// before a start: a phone's app sets these for itself, a computer's are the player's to apply.
struct Settings {
    // Full screen from the start, and the game's area in a window (0: fitted to the display).
    bool fullscreen = false;
    int window_w = 0, window_h = 0;
    // Frames on the display's refreshes, and the most a second (0: the display's own rate).
    bool vsync = true;
    float fps = 0;
    // The share of the game's area the game draws at, in percent: the picture is stretched to the area.
    int render_scale = 100;
    // What makes the picture of a render scale below 100 % the window's size (post_pass.cpp): the plain stretch ANGLE
    // gives a surface of a fixed size, or a pass of our own over the game's frame drawn at the scaled size.
    enum class Upscaler { kBilinear, kFsr1, kNis };
    Upscaler upscaler = Upscaler::kBilinear;
    // How the edges of the game's shapes are smoothed (post_pass.cpp): not at all, or by a pass over the finished picture
    // (CMAA 2, SMAA 1x).
    enum class AntiAliasing { kOff, kCmaa2, kSmaa };
    AntiAliasing anti_aliasing = AntiAliasing::kOff;
    // A counter of the frames a second in a corner of the game (overlay_win32.cpp): none, or on in its corner, the bottom
    // right unless another is chosen (measured on the game's screens, it covers the fewest of the game's own labels and
    // buttons there; every corner covers some on some screen).
    enum class ShowFps { kOff, kTopLeft, kTopRight, kBottomLeft, kBottomRight };
    ShowFps show_fps = ShowFps::kOff;
    // The sound's device ("" Windows' default output), the device alone, how much is kept ahead (0 low, 1 normal,
    // 2 safe) and the game's volume in percent.
    std::string audio_device;
    bool audio_exclusive = false;
    int audio_buffer = 1;
    int volume = 100;
    // The language the game and the player's own words speak, as the launcher chose it ("en", "ko"); "" for the
    // computer's (host_locale), as when the launcher follows Windows' display language.
    std::string language;
};
Settings& settings();

// The size the game draws at for an area of `w` x `h` at a render scale in percent (window_win32.cpp's place_game). Where
// the area's shape has fine enough whole steps (1920x1080 is 120 steps of 16x9) the size is a whole number of them, the
// nearest to the share asked: the shape kept exactly, so the game's layout scales alike both ways and lands where it
// does at full size (67 % of 1920x1080 is 1280x720, not the 1286x724 that rounding each side gave: a little wider than
// 16:9, stretched to the area 0.09 % more across than down). An area without such steps (1366x768) by its width, the
// height from it.
struct DrawSize {
    int w, h;
};
inline DrawSize draw_size(int w, int h, int scale) {
    if (scale >= 100 || w <= 0 || h <= 0) return {w, h};
    const int steps = std::gcd(w, h);
    // At 25 steps or more the nearest is within 2 % of the share asked.
    if (steps >= 25) {
        const int k = std::max(1, static_cast<int>(std::lround(steps * scale / 100.0)));
        return {w / steps * k, h / steps * k};
    }
    const int dw = std::max(1, static_cast<int>(std::lround(w * scale / 100.0)));
    return {dw, std::max(1, static_cast<int>(std::lround(static_cast<double>(dw) * h / w)))};
}
// Reads a settings file into settings(); false when there is none (the defaults stay).
bool load_settings(const std::string& path);
// The language a settings file names (language=), "" for none or one the player does not speak: read before the app's
// folder is in place, so that the player's first words (a folder it cannot use) speak it too.
std::string settings_language(const std::string& path);

// The host path of a guest path (the runtime's path_hook), and the guest name of a host file (guest_paths.h: on Windows
// nothing the guest names reaches past the player's folders and the app's data folder).
std::string host_of(const std::string& guest);
std::string guest_of(const std::string& host);

// An entry of the app's APK by its full name ("assets/bin/Data/..."), inflated (ndk.cpp); false when there is none.
bool apk_entry(const std::string& name, std::vector<std::uint8_t>& out);
// The names of the APK's files under `prefix` ("lib/armeabi-v7a/"), in order (ndk.cpp).
std::vector<std::string> apk_names(const std::string& prefix);
// An entry's content in short, its CRC-32 and size as the zip's directory gives them: two entries with the same stamp
// hold the same bytes ("" for none).
std::string apk_stamp(const std::string& name);

// A start with no arguments, or with --app (own_folder.cpp): the app from the player's own folder or from the folder named
// (player.conf and the APK; the PC client keeps one for each server), the runtime from the player's own (runtime/), its
// libraries unpacked and its data and log in the user's folder for programs; false with `error` when that cannot be.
bool use_own_folder(const std::string& folder, std::string& error);
// A reason the player cannot go on, in the log and, on Windows, in a message box: a double click has no console.
void show_error(const std::string& what);
// A name for the calling thread, which the stats and a debugger show (threads.cpp).
void name_thread(const char* name);
// The language and country the game and the player speak ("ko", "KR"), for the game's locale and the player's own words
// (java_lang.cpp): the language the launcher chose (settings' language=) when it chose one, else the computer's; the
// country always the computer's. The computer's: the environment's locale on Linux (LC_ALL, LC_MESSAGES, LANG), the
// user's display language on Windows unless the environment names one; en, US otherwise.
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

// The window (window_x11.cpp, window_win32.cpp): opened at the App's size; the android.view.Surface that names it; the
// window behind a Surface (0 for anything else); and its events, handled until the window is closed (false then).
bool open_window(const std::string& title);
jvm::Object* surface();
std::uintptr_t window_of(jvm::Object* surface);
bool pump_window();
// The UI thread's wait between turns: until `until`, a job posted to its looper, or a window event, whichever comes
// first, so that a touch reaches the game as soon as it comes (window_win32.cpp; X11 looks again every 4 ms).
void wait_for_events(std::chrono::steady_clock::time_point until);
// The game opened or closed its text input: on Windows the focus goes to a text field of the window's while it is open,
// so that Windows' touch keyboard offers itself on a PC without a keyboard, and an input method composes into it.
void soft_keyboard(bool open);
// The server's notice about this player's broadcast ("title\ndetail") over the game's window for a few seconds, as a
// phone shows its toast; `live` while broadcasting. From any thread.
void show_notice(const std::string& text, bool live);
// The game's part of the window changed size (the window resized, full screen, another display's scaling): the game is
// told as Android tells it, SurfaceHolder's surfaceChanged on the Unity thread (main.cpp). Calls that come while one is
// on its way are one.
void surface_changed();
// The game is done (it chose to quit: its last frame, System.exit, Process.killProcess, Activity.finish): the player
// leaves as an app's process ends on a phone, from the UI thread's next turn (main.cpp). `how` goes to the log.
void quit_game(const char* how);
// True once the game has quit.
bool game_quit();
// The game held still while the player's menu is open, as a phone's app is when its owner leaves it (focus away, then
// paused) and goes on as it comes back (resumed, then focus): the song stops where it was, and the game's own pause
// screen is there on return. The Unity thread draws nothing meanwhile (main.cpp). Repeated calls with the same value
// are one.
void pause_game(bool paused);
// True while the Unity thread holds the game still (on that thread).
bool game_paused();
// The refresh rate of the display the window is on, as the game asks for it (Display.getRefreshRate): the display's own
// once the window has read it (pacing.h's g_display_interval), the App's until then.
float display_rate();
// The first refresh of that display at or after `ns` on the monotonic clock, for the frame callbacks (Choreographer).
std::int64_t refresh_at_or_after(std::int64_t ns);

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
    // Called after each job posted, for a thread that waits on more than its jobs (the UI thread on Windows waits for
    // window messages too, and a posted job has to wake it there). Set once by that thread; read by every poster.
    std::atomic<void (*)()> wake{nullptr};

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
// calling thread, which is the UI thread; `at_ns` is when the touch screen saw it, on the monotonic clock (-1: now). touch() is one finger of its own: the mouse, and the taps a check planned by
// frame, through the hook the frame counter calls after each frame shown.
void finger(int id, int what, float x, float y, std::int64_t at_ns = -1);
void touch(int action, float x, float y);
void frame_shown(std::uint64_t n);
// The frames shown so far (frames.cpp's count at each swap), for the frame counter in the game's corner: read from any
// thread, one atomic load.
std::uint64_t frames_shown();
// When the last of them was shown, in nanoseconds on the steady clock (0 before the first).
std::int64_t frame_shown_ns();
// The mouse wheel at window pixels x,y, turned by notches (positive: away from the user; sideways: to the right), as a
// finger's drag that scrolls what is under it; on the UI thread.
void wheel(float x, float y, float notches_x, float notches_y);
// A key of the computer's keyboard as the phone's key `code` (Android's KEYCODE_ numbers), down or up, its repeat count
// while held, and its character (0 for none); on the UI thread.
void key(int code, bool down, int repeat, int unicode);
// Android's key codes that the computer's keys stand for.
constexpr int kKeycodeBack = 4, kKeycode0 = 7, kKeycodeDpadUp = 19, kKeycodeDpadDown = 20, kKeycodeDpadLeft = 21,
              kKeycodeDpadRight = 22, kKeycodeA = 29, kKeycodeTab = 61, kKeycodeSpace = 62, kKeycodeEnter = 66, kKeycodeDel = 67,
              kKeycodePageUp = 92, kKeycodePageDown = 93, kKeycodeForwardDel = 112, kKeycodeHome = 122, kKeycodeEnd = 123;
// The soft keyboard (input.cpp): whether the game asked for text, the text the keyboard types, and its keys.
constexpr int kKeyEnter = 1, kKeyEscape = 2, kKeyBackspace = 3;
bool typing();
void type_text(const std::string& utf8);
// What an input method is composing now ("" when nothing): shown to the game after the text, as on a phone.
void type_composing(const std::string& utf8);
void type_key(int key);

}  // namespace player
