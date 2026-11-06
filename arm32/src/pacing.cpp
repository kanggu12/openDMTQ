// Frame pacing for the app's window: every frame stays on screen for the same number of refreshes.
//
// A game that holds its frame rate with a timer, as Unity's targetFrameRate does, runs out of step
// with a display that refreshes several times per frame: on a 120 Hz panel a 60 fps frame stays
// for two refreshes or three, which looks like judder. Here the swap paces the frames instead, the
// way Android's frame pacing library (Swappy) does:
//
// - The compositor's timing (EGL_ANDROID_get_frame_timestamps) gives the refresh interval, the
//   next deadline for a buffer to make a composition, and how long a composition takes to reach
//   the screen.
// - Each frame is meant for the refresh n refreshes after the frame before, n being the refresh
//   rate over the app frame rate, and asks the compositor to show it then
//   (EGL_ANDROID_presentation_time), so a frame that is ready early still waits its turn. A frame
//   too late for its refresh takes the next one it can make, and the frames after it follow on
//   from there.
// - After the swap the thread waits until shortly before that frame's composition deadline, so the
//   next frame starts with all of its n refreshes ahead of it and never queues behind another one
//   (which would add latency).
//
// Only n of 2 or more is paced. With one refresh per frame (the window asks the display for the
// app frame rate, and it usually switches) there is nothing to even out: on a Galaxy S26 Ultra the
// game's own limiter kept 99.8 % of the frames one refresh apart, at 60 Hz and at 120 Hz.
//
// While pacing, swaps use interval 1, so no swap replaces a frame still in the queue; otherwise
// the interval the game asked for stands. The game's own limiter is set above the app frame rate
// meanwhile (tweaks.cpp), so this is the only one. On Android 13 and later each frame's work time
// goes to the performance hint API (ADPF), which raises the CPU clock before frames run late
// instead of after. For an unpaced frame that is the time between its swaps less what the thread
// slept in nanosleep (the game's own limiter waiting, which is not work).
//
// The frame rate follows the display when debug.arm32.framerate is unset and the game's cap can be
// set and its target read (tweaks.h). The game's window asks for the highest rate there is any use for
// (144 Hz); whatever the panel then runs at decides, once that has held for a second (five for a rate
// outside the usual list), so a short switch (an adaptive panel's) changes nothing. The frame rate is
// the refresh rate, or a whole fraction of it when the window has come to ask for less: 72 fps on a
// panel that stays at 144 Hz. A pause over 100 ms (a load, the app away, a new surface) starts the waits
// over.
//
// Above 60 fps the pace is checked every two seconds while the game itself aims that high (without
// input it steps down to 48, 36, 24 and 18 fps, in menus and songs alike). It goes by what the screen
// showed: a window falls short when more than 3 % of the frames stayed on screen for more than one
// refresh (at 110 fps on a 120 Hz panel, 7 % did; at 120, 0.1 %). The gaps between swaps say little: on a
// Galaxy S26 Ultra a fifth of them were half a refresh off while every frame still got its own refresh.
// Only a device that does not report present times is judged by the rate frames came at (under 97 %
// falls short). Three short windows without a good one between take one step down the list (144, 120,
// 90, 72, 60): the window asks for that, and the panel follows if it can. So does the phone's own word
// that it is hot (thermal status SEVERE or worse), every half minute while that lasts. Nothing steps
// back up until the app starts again, and at 60 fps there is nothing left to check.
// A window with a stall over 100 ms (loading, the app paused) starts the count again.
//
// debug.arm32.pacing 0 turns the pacing off, debug.arm32.adpf 0 the performance hints, and
// debug.arm32.slowframe <ms> stretches every frame, to try the fallback out as on a slower phone.
#include "pacing.h"

#include "framerate.h"
#include "host.h"

#include <EGL/eglext.h>
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cmath>
#include <deque>
#include <dlfcn.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <sys/system_properties.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <vector>

namespace arm32 {

namespace {

using Nanos = std::int64_t;
constexpr Nanos kSecond = 1000000000;
// How long before a composition deadline a frame has to reach the swap: the swap itself, the GPU
// finishing the frame and the buffer travelling to the compositor.
constexpr Nanos kMargin = 4000000;
// eglPresentationTimeANDROID's value for "no presentation time": the window's
// NATIVE_WINDOW_TIMESTAMP_AUTO, the time of the swap itself.
constexpr EGLnsecsANDROID kAutoTimestamp = INT64_MIN;

Nanos now_ns() {
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return Nanos{ts.tv_sec} * kSecond + ts.tv_nsec;
}

void sleep_until(Nanos t) {
    timespec ts{static_cast<time_t>(t / kSecond), static_cast<long>(t % kSecond)};
    // An absolute time: a signal (the runtime's interrupt) does not stretch the wait.
    while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, nullptr) == EINTR) {
    }
}

float ms(Nanos n) { return static_cast<float>(static_cast<double>(n) / 1e6); }

// Host EGL entry points; the frame timestamp ones are extensions.
void* egl_fn(const char* name) {
    static void* lib = dlopen("libEGL.so", RTLD_NOW | RTLD_LOCAL);
    static auto get = reinterpret_cast<void* (*)(const char*)>(lib ? dlsym(lib, "eglGetProcAddress") : nullptr);
    void* f = lib ? dlsym(lib, name) : nullptr;
    return f || !get ? f : get(name);
}

struct Egl {
    EGLint (*get_error)();
    EGLBoolean (*swap)(EGLDisplay, EGLSurface);
    EGLBoolean (*swap_interval)(EGLDisplay, EGLint);
    EGLBoolean (*surface_attrib)(EGLDisplay, EGLSurface, EGLint, EGLint);
    EGLBoolean (*compositor_timing)(EGLDisplay, EGLSurface, EGLint, const EGLint*, EGLnsecsANDROID*);
    EGLBoolean (*presentation_time)(EGLDisplay, EGLSurface, EGLnsecsANDROID);
    EGLBoolean (*next_frame_id)(EGLDisplay, EGLSurface, EGLuint64KHR*);
    EGLBoolean (*frame_timestamps)(EGLDisplay, EGLSurface, EGLuint64KHR, EGLint, const EGLint*, EGLnsecsANDROID*);
};

const Egl& egl() {
    static const Egl e{
        reinterpret_cast<decltype(Egl::get_error)>(egl_fn("eglGetError")),
        reinterpret_cast<decltype(Egl::swap)>(egl_fn("eglSwapBuffers")),
        reinterpret_cast<decltype(Egl::swap_interval)>(egl_fn("eglSwapInterval")),
        reinterpret_cast<decltype(Egl::surface_attrib)>(egl_fn("eglSurfaceAttrib")),
        reinterpret_cast<decltype(Egl::compositor_timing)>(egl_fn("eglGetCompositorTimingANDROID")),
        reinterpret_cast<decltype(Egl::presentation_time)>(egl_fn("eglPresentationTimeANDROID")),
        reinterpret_cast<decltype(Egl::next_frame_id)>(egl_fn("eglGetNextFrameIdANDROID")),
        reinterpret_cast<decltype(Egl::frame_timestamps)>(egl_fn("eglGetFrameTimestampsANDROID")),
    };
    return e;
}

// The performance hint API (libandroid, Android 13 and later), looked up at run time: the runtime
// is built for Android 5.
struct Hints {
    void* (*get_manager)();
    void* (*create_session)(void*, const std::int32_t*, std::size_t, std::int64_t);
    int (*update_target)(void*, std::int64_t);
    int (*report_actual)(void*, std::int64_t);
    void (*close_session)(void*);
};

const Hints& hints() {
    static const Hints h = [] {
        Hints r{};
        void* lib = dlopen("libandroid.so", RTLD_NOW | RTLD_LOCAL);
        if (!lib) return r;
        r.get_manager = reinterpret_cast<decltype(r.get_manager)>(dlsym(lib, "APerformanceHint_getManager"));
        r.create_session = reinterpret_cast<decltype(r.create_session)>(dlsym(lib, "APerformanceHint_createSession"));
        r.update_target = reinterpret_cast<decltype(r.update_target)>(dlsym(lib, "APerformanceHint_updateTargetWorkDuration"));
        r.report_actual = reinterpret_cast<decltype(r.report_actual)>(dlsym(lib, "APerformanceHint_reportActualWorkDuration"));
        r.close_session = reinterpret_cast<decltype(r.close_session)>(dlsym(lib, "APerformanceHint_closeSession"));
        return r;
    }();
    return h;
}

// A frame swapped with stats on, until it is known when it reached the screen.
struct Swapped {
    EGLuint64KHR id;
    Nanos target;    // when it was asked to be shown (0: not paced)
    Nanos interval;  // the refresh interval then
    Nanos period;    // how long it was meant to stay on screen: the refreshes per frame in that interval
    Nanos at;        // when it was swapped
};

// The error a call of ours left, read so the game never sees it in its own eglGetError (EGL keeps
// one error per thread, and reading it clears it).
EGLint take_error(const Egl& e) { return e.get_error ? e.get_error() : EGL_SUCCESS; }

struct Pacer {
    EGLSurface surface = nullptr;
    Nanos last_swap = 0;      // when this surface was last swapped
    bool timestamps = false;  // frame timestamps on for this surface
    bool no_present = false;  // the device does not report when frames reach the screen
    Nanos logged_interval = -1;  // the refresh interval last logged (-1: nothing logged yet)
    Nanos target = 0;         // when the last frame was asked to be shown
    Nanos frame_start = 0;    // when the current frame's work began: the end of the last wait
    // Between unpaced swaps: when the last one returned, and the thread's sleep total then.
    Nanos unpaced_start = 0;
    std::int64_t unpaced_slept = 0;
    bool timed = false;       // a presentation time is set on the window
    std::deque<Swapped> swapped;
    Nanos last_shown = 0;     // when the last frame reached the screen
};

// The performance hint session of the swapping thread; it outlives window surfaces.
struct Session {
    void* handle = nullptr;
    int tid = 0;
    Nanos target = 0;
    bool unavailable = false;
};

std::mutex g_lock;
Pacer g_pacer;
Session g_session;
std::atomic<Nanos> g_active_until{0};
// The swap interval the game last asked for (EGL's default until it asks), and whether interval 1
// is in place for pacing instead.
std::atomic<EGLint> g_game_interval{1};
std::atomic<bool> g_paced_interval{false};

// Following the display (see the top of the file).
constexpr float kRates[] = {144, 120, 90, 72, 60};
constexpr Nanos kCheckWindow = 2 * kSecond;
constexpr int kShortWindows = 3;
// ATHERMAL_STATUS_SEVERE.
constexpr int kThermalSevere = 3;
struct Follow {
    float candidate = 0;        // a display rate other than the one in use, seen lately
    Nanos candidate_since = 0;  // since when the display has been at it (0: none)
    std::vector<float> gaps;    // ms between the swaps of the current check window
    Nanos window_start = 0;
    int window_game = 0;        // the game's frame target during the current check window
    int short_windows = 0;      // check windows in a row that fell short
    int drawing_short = 0;  // the same, of windows with the game drawing all along
    int timing_misses = 0;      // swaps in a row without the compositor's timing
    int shown = 0;              // frames of the window whose time on screen came
    int shown_late = 0;         // of those, frames that stayed for more than one refresh
};
Follow g_follow;
std::atomic<float> g_followed_rate{60};
// What the window asks the display for: the highest of kRates at first, one lower with each step down.
std::atomic<float> g_window_rate{kRates[0]};
// The phone's own word on its temperature (thermal_tick), and when it last took a step down.
std::atomic<int> g_thermal_status{0};
Nanos g_thermal_step_at = 0;
// A gap between swaps over this is a pause (a load, the app away), not a slow frame.
constexpr Nanos kPause = 100000000;

// The pace check's window and the wait for a new display rate start over (a new surface, a pause).
void follow_restart() {
    g_follow.gaps.clear();
    g_follow.window_start = 0;
    g_follow.shown = g_follow.shown_late = 0;
    g_follow.candidate_since = 0;
}

// Tells the system how long this frame's work took, against a target below the frame's budget.
void report_work(Nanos work, Nanos budget) {
    static const bool wanted = requested("ARM32_ADPF", "debug.arm32.adpf", true);
    const Hints& h = hints();
    Session& s = g_session;
    if (!wanted || s.unavailable || !h.get_manager || !h.create_session || !h.report_actual || work <= 0) return;
    // Room for the swap and the GPU after the work.
    Nanos target = budget * 8 / 10;
    int tid = static_cast<int>(gettid());
    if (s.handle && s.tid != tid) {
        // Another thread swaps now: a session for that one instead.
        if (h.close_session) h.close_session(s.handle);
        s.handle = nullptr;
    }
    if (!s.handle) {
        void* manager = h.get_manager();
        std::int32_t ids[1] = {tid};
        s.handle = manager ? h.create_session(manager, ids, 1, target) : nullptr;
        if (!s.handle) {
            s.unavailable = true;
            log("arm32: performance hints not available");
            return;
        }
        s.tid = tid;
        s.target = target;
        log("arm32: performance hints for thread %d, %.1f ms of work per frame", tid, static_cast<double>(ms(target)));
    } else if (std::llabs(target - s.target) > s.target / 20 && h.update_target) {
        // A new refresh rate or frame rate (small changes are estimate noise).
        h.update_target(s.handle, target);
        s.target = target;
    }
    h.report_actual(s.handle, work);
}

// With stats on: when the frames swapped a few frames ago reached the screen. The window keeps
// the timestamps of its last 8 frames; a frame not on screen by then is given up.
void collect_shown(Pacer& p, EGLDisplay d, EGLSurface s, const Egl& e) {
    static const EGLint kWhat[] = {EGL_DISPLAY_PRESENT_TIME_ANDROID};
    while (p.swapped.size() > 3) {
        Swapped f = p.swapped.front();
        EGLnsecsANDROID shown = EGL_TIMESTAMP_INVALID_ANDROID;
        bool known = e.frame_timestamps(d, s, f.id, 1, kWhat, &shown) == EGL_TRUE;
        // Not on screen yet: ask again after the next frame, while the window keeps its times (it
        // holds the last 8 frames).
        if (known && shown == EGL_TIMESTAMP_PENDING_ANDROID && p.swapped.size() <= 7) break;
        p.swapped.pop_front();
        // Given up while its time was still to come (a device that reports late): the gap to the
        // next frame is not known either.
        if (known && shown == EGL_TIMESTAMP_PENDING_ANDROID) {
            p.last_shown = 0;
            continue;
        }
        if (!known) {
            EGLint error = take_error(e);
            if (error == EGL_BAD_SURFACE) {
                // Timestamps off (the window was reconnected): on again; the history is gone.
                if (e.surface_attrib && e.surface_attrib(d, s, EGL_TIMESTAMPS_ANDROID, EGL_TRUE) != EGL_TRUE) take_error(e);
                p.swapped.clear();
                p.last_shown = 0;
                return;
            }
            if (error == EGL_BAD_PARAMETER) {
                // This device keeps no present times: stop asking.
                log("arm32: stats: this device does not report when frames reach the screen");
                p.no_present = true;
                p.swapped.clear();
                return;
            }
            // Out of the window's history: just this frame, and no gap to judge after it.
            p.last_shown = 0;
            continue;
        }
        // Dropped, still not shown, or not reported by this device.
        if (shown <= 0) continue;
        if (p.last_shown) {
            const Nanos gap = shown - p.last_shown;
            if (g_stats) note_shown(ms(gap), f.target && shown > f.target + f.interval / 2);
            // For the pace check of a followed frame rate: frames swapped in its open window.
            if (g_follow.window_start && f.at >= g_follow.window_start && f.interval > 0) {
                ++g_follow.shown;
                // Over its time by half a refresh or more: it stayed a refresh too long, whatever noise the times have.
                // A frame's time, not a refresh's: at 72 fps on a 144 Hz panel every frame stays for two.
                if (gap > f.period + f.interval / 2) ++g_follow.shown_late;
            }
        }
        p.last_shown = shown;
    }
}

// The frame rate for a display at `hz` when the window asks for `asked`: the refresh rate or the highest
// whole fraction of it that is not above that, so every frame stays for the same number of refreshes;
// `asked` itself when no such fraction is left at 60 fps or more (it then goes out unpaced).
float rate_for_display(double hz, float asked) {
    for (int n = 1; n <= 6; ++n) {
        const double r = hz / n;
        if (r < 57) break;
        if (r <= static_cast<double>(asked) * 1.03) return std::round(static_cast<float>(r));
    }
    return asked;
}

// The file that says this device could not keep its frame rate at the panel's resolution: in the app's own files, so that it stays
// across starts and updates and goes with the app. Empty when the app's folder cannot be told.
std::string low_resolution_mark() {
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
    const std::string files = "/data/user/" + std::to_string(getuid() / 100000) + "/" + name + "/files";
    // A first start: nothing may have made it yet.
    if (mkdir(files.c_str(), 0700) != 0 && errno != EEXIST) return "";
    return files + "/opendmtq-low-resolution";
}

// What low_resolution_wanted() has found: -1 until it has looked.
std::atomic<int> g_low_resolution{-1};

// Remembers for the next start that frames fell short here. Sharpness is what goes first: only after that the frame rate.
void note_low_resolution() {
    if (low_resolution_wanted()) return;
    g_low_resolution.store(1, std::memory_order_relaxed);
    const std::string mark = low_resolution_mark();
    std::FILE* f = mark.empty() ? nullptr : std::fopen(mark.c_str(), "w");
    if (f) std::fclose(f);
    log("arm32: resolution: frames fell short at the panel's own; the low resolution from the next start");
}

// The window asks for one step less than the frame rate in use (60 at the end, for good) and the frame
// rate follows at once as far as the panel's rate `hz` allows (0: not known). The caller then has the
// window ask, outside the lock.
bool step_down(double hz) {
    const float rate = g_followed_rate.load(std::memory_order_relaxed);
    float next = 60;
    for (float r : kRates) {
        if (r < rate) {
            next = r;
            break;
        }
    }
    g_window_rate.store(next, std::memory_order_relaxed);
    g_followed_rate.store(hz > 0 ? rate_for_display(hz, next) : next, std::memory_order_relaxed);
    g_active_until.store(0, std::memory_order_relaxed);
    g_follow.gaps.clear();
    g_follow.window_start = 0;
    g_follow.short_windows = 0;
    g_follow.shown = g_follow.shown_late = 0;
    g_follow.candidate_since = 0;
    return true;
}

// One swap of the window while following the display: `interval` is the display's refresh
// interval (0 when the compositor gave no timing), `gap` the time since the last swap (0 for the
// first). Returns true when the window has to ask the display again. Under g_lock.
bool follow_display(Nanos now, Nanos interval, Nanos gap) {
    Follow& f = g_follow;
    const float asked = g_window_rate.load(std::memory_order_relaxed);
    if (!interval) {
        // Nothing to follow for two seconds' worth of swaps: 60 fps, the window asking for 60 Hz.
        if (asked <= 60 || ++f.timing_misses < 120) return false;
        log("arm32: frame rate: no compositor timing; 60 fps from now on");
        g_followed_rate.store(60, std::memory_order_relaxed);
        return step_down(0);
    }
    f.timing_misses = 0;
    if (gap > kPause) {
        follow_restart();
        gap = 0;
    }
    const float rate = g_followed_rate.load(std::memory_order_relaxed);
    const double hz = 1e9 / static_cast<double>(interval);
    // What this refresh rate makes the frame rate. A new one counts once it has held for a second, one
    // outside the usual list after five; below 60 Hz (a panel idling) none does.
    const float display = hz < 57 ? rate : rate_for_display(hz, asked);
    bool listed = false;
    for (float r : kRates) {
        if (std::fabs(display - r) < 0.5f) listed = true;
    }
    if (std::fabs(display - rate) < 0.5f) {
        f.candidate_since = 0;
        // 60 fps is as low as this goes, on a panel that went on refreshing faster than the window asked (it was asked
        // for 90 and stays at 120). Ask for 60 itself: the panel may have that, and every late frame costs less there.
        if (rate <= 60 && asked > 61 && hz > 61) {
            g_window_rate.store(60, std::memory_order_relaxed);
            log("arm32: frame rate: 60 fps on a %.0f Hz panel; asking it for 60 Hz", hz);
            return true;
        }
    } else if (!f.candidate_since || std::fabs(display - f.candidate) >= 0.5f) {
        f.candidate = display;
        f.candidate_since = now;
    } else if (now - f.candidate_since >= (listed ? kSecond : 5 * kSecond)) {
        f.candidate_since = 0;
        g_followed_rate.store(display, std::memory_order_relaxed);
        // Not paced any more at the new rate: the game's cap is the rate again at the next tweak
        // turn, not twice it for another second.
        g_active_until.store(0, std::memory_order_relaxed);
        f.gaps.clear();
        f.window_start = 0;
        f.short_windows = 0;
        f.shown = f.shown_late = 0;
        log("arm32: frame rate %.0f fps, the display at %.0f Hz", static_cast<double>(display), hz);
        return false;
    }
    // Hot, as the phone itself says: a step down now and every half minute while that lasts.
    if (rate > 60 && g_thermal_status.load(std::memory_order_relaxed) >= kThermalSevere && now - g_thermal_step_at >= 30 * kSecond) {
        g_thermal_step_at = now;
        log("arm32: frame rate: the phone reports it is hot; a step down from %.0f fps", static_cast<double>(rate));
        return step_down(hz);
    }
    // The pace check: while the game itself aims at least as high as the frame rate. At 60 fps there is no lower rate to go to, and
    // it runs only as long as there is still a lower resolution to go to. A window in which the game's target changed mixes two
    // paces: it starts over (the count of short windows stays).
    const int game = game_target_frame_rate();
    if ((rate <= 60 && low_resolution_wanted()) || game < rate || game != f.window_game) {
        f.gaps.clear();
        f.window_start = 0;
        f.window_game = game;
        return false;
    }
    if (!gap) return false;
    if (!f.window_start) {
        f.window_start = now - gap;
        f.shown = f.shown_late = 0;
    }
    f.gaps.push_back(ms(gap));
    if (now - f.window_start < kCheckWindow) return false;
    const std::size_t frames = f.gaps.size();
    const double fps = static_cast<double>(frames) * 1e9 / static_cast<double>(now - f.window_start);
    const float longest = *std::max_element(f.gaps.begin(), f.gaps.end());
    // Present times came for most of the frames: judge by them, else by the rate.
    const int shown = f.shown, late = f.shown_late;
    const bool seen = static_cast<std::size_t>(shown) * 2 >= frames;
    f.gaps.clear();
    f.window_start = 0;
    f.shown = f.shown_late = 0;
    // (A pause never gets here: it starts the window over.)
    const bool fell_short = seen ? late * 100 > shown * 3 : fps < rate * 0.97;
    f.short_windows = fell_short ? f.short_windows + 1 : 0;
    // For the resolution, which stays changed from then on: windows in which the game was drawing all along and did not keep up. A
    // scene being loaded holds everything up for some seconds, far below this, and says nothing about drawing.
    f.drawing_short = fell_short && fps >= rate * 0.4 ? f.drawing_short + 1 : 0;
    if (g_stats) {
        log("stats: frame rate check at %.0f fps (game %d): %.1f fps, %d of %d frames shown late, longest %.0f ms%s",
            static_cast<double>(rate), game, fps, late, shown, static_cast<double>(longest), fell_short ? ", short" : "");
    }
    // The resolution of a song that has begun cannot change under it, so that waits for the next start. Until then the frame rate
    // gives way, as far as it can. At 60 fps, with no step to take first, it takes a little longer to be sure.
    if (f.drawing_short >= kShortWindows + (rate > 60 ? 0 : 2)) {
        log("arm32: frame rate: %.0f fps not kept while drawing (last 2 s: %.1f fps, %d of %d frames shown late)",
            static_cast<double>(rate), fps, late, shown);
        note_low_resolution();
    }
    if (rate <= 60 || f.short_windows < kShortWindows) return false;
    log("arm32: frame rate: %.0f fps not kept (last 2 s: %.1f fps, %d of %d frames shown late); a step down",
        static_cast<double>(rate), fps, late, shown);
    return step_down(hz);
}

}  // namespace

bool pacing_enabled() {
    static const bool wanted = requested("ARM32_PACING", "debug.arm32.pacing", true);
    return wanted && app_frame_rate() > 0;
}

bool pacing_active() { return now_ns() < g_active_until.load(std::memory_order_relaxed); }

bool low_resolution_wanted() {
    // Asked at every swap at 60 fps: looked up once, and note_low_resolution() says when it changes.
    int known = g_low_resolution.load(std::memory_order_relaxed);
    if (known < 0) {
        // The property decides when it is set, for trying both out. Otherwise the file.
        char value[PROP_VALUE_MAX] = "";
        __system_property_get("debug.arm32.lowres", value);
        const std::string mark = value[0] ? "" : low_resolution_mark();
        known = value[0] ? value[0] != '0' : (!mark.empty() && access(mark.c_str(), F_OK) == 0);
        g_low_resolution.store(known, std::memory_order_relaxed);
    }
    return known != 0;
}

float followed_frame_rate() { return g_followed_rate.load(std::memory_order_relaxed); }

float followed_window_rate() { return g_window_rate.load(std::memory_order_relaxed); }

void pacing_thermal_tick() {
    // AThermal_getCurrentThermalStatus is a call into the system: never on the render thread.
    using Acquire = void* (*)();
    using Status = int (*)(void*);
    static void* lib = dlopen("libandroid.so", RTLD_NOW | RTLD_LOCAL);
    static auto acquire = lib ? reinterpret_cast<Acquire>(dlsym(lib, "AThermal_acquireManager")) : nullptr;
    static auto status = lib ? reinterpret_cast<Status>(dlsym(lib, "AThermal_getCurrentThermalStatus")) : nullptr;
    static void* manager = acquire && status ? acquire() : nullptr;
    if (manager) g_thermal_status.store(status(manager), std::memory_order_relaxed);
}

EGLint pacing_swap_interval(EGLint asked) {
    g_game_interval.store(asked, std::memory_order_relaxed);
    return g_paced_interval.load(std::memory_order_relaxed) ? 1 : asked;
}

void pacing_surface_destroyed(EGLSurface s) {
    // A new surface may get the same address; its window starts with timestamps off again, and
    // with the swap interval the game asks for.
    std::lock_guard<std::mutex> lock(g_lock);
    if (g_pacer.surface == s) {
        g_pacer.surface = nullptr;
        g_paced_interval.store(false, std::memory_order_relaxed);
    }
}

EGLBoolean paced_swap(EGLDisplay d, EGLSurface s) {
    const Egl& e = egl();
    if (!e.swap) return EGL_FALSE;
    // No surface: the driver's error to give, nothing to pace.
    if (!s) return e.swap(d, s);
    // Test aid (see the top of the file).
    static const long slow = [] {
        char value[PROP_VALUE_MAX] = "";
        __system_property_get("debug.arm32.slowframe", value);
        return std::strtol(value, nullptr, 10);
    }();
    if (slow > 0) sleep_until(now_ns() + slow * 1000000);
    const bool pace = pacing_enabled() && e.compositor_timing && e.presentation_time;
    const bool count = g_stats && e.next_frame_id && e.frame_timestamps;
    // Following the display's refresh rate takes the compositor's timing too.
    const bool follow = frame_rate_follows_display() && e.compositor_timing;
    if (!pace && !count && !follow) return e.swap(d, s);
    std::unique_lock<std::mutex> lock(g_lock);
    Pacer& p = g_pacer;
    const Nanos now = now_ns();
    // One surface is paced: the window. Another one swapped meanwhile (a second surface, another
    // thread) goes out as it is, unless the paced one has not been swapped for a second.
    if (p.surface && p.surface != s && now - p.last_swap < kSecond) {
        lock.unlock();
        return e.swap(d, s);
    }
    // Timestamps are collected per window connection: turned on for each new surface, and again
    // whenever the window has been reconnected under the same surface (queries then fail).
    auto enable_timestamps = [&] {
        if (e.surface_attrib && e.surface_attrib(d, s, EGL_TIMESTAMPS_ANDROID, EGL_TRUE) == EGL_TRUE) return true;
        take_error(e);
        return false;
    };
    if (p.surface != s) {
        // A new window surface (the first one, or the app came back): start over. Its swap interval
        // is whatever the game set for it.
        p = Pacer{};
        p.surface = s;
        p.timestamps = enable_timestamps();
        log("arm32: frame timestamps %s for surface %p", p.timestamps ? "on" : "not available", s);
        // A presentation time or swap interval set while pacing belongs to the window, which an
        // earlier surface may have shared: back to the automatic time and the game's interval.
        if (e.presentation_time && e.presentation_time(d, s, kAutoTimestamp) != EGL_TRUE) take_error(e);
        if (g_paced_interval.exchange(false, std::memory_order_relaxed) && e.swap_interval &&
            e.swap_interval(d, g_game_interval.load(std::memory_order_relaxed)) != EGL_TRUE) {
            take_error(e);
        }
        follow_restart();
    }
    const Nanos gap = p.last_swap ? now - p.last_swap : 0;
    p.last_swap = now;
    // This frame's refresh: n refreshes after the last frame's, or the first one it can still make.
    Nanos interval = 0, latency = 0, target = 0, n = 0;
    bool ask_again = false;
    if ((pace || follow) && p.timestamps) {
        static const EGLint kNames[] = {EGL_COMPOSITE_DEADLINE_ANDROID, EGL_COMPOSITE_INTERVAL_ANDROID,
                                        EGL_COMPOSITE_TO_PRESENT_LATENCY_ANDROID};
        EGLnsecsANDROID t[3] = {};
        auto timing = [&] {
            if (e.compositor_timing(d, s, 3, kNames, t) == EGL_TRUE && t[1] > 0) return EGL_SUCCESS;
            EGLint error = take_error(e);
            return error == EGL_SUCCESS ? EGL_BAD_MATCH : error;
        };
        EGLint error = timing();
        if (error == EGL_BAD_SURFACE && enable_timestamps()) {
            // Reconnected: the frames before are gone from the history too.
            p.swapped.clear();
            p.last_shown = 0;
            error = timing();
        }
        if (error != EGL_SUCCESS && p.logged_interval) {
            log("arm32: pacing: no compositor timing (error %#x); frames go out unpaced", error);
            p.logged_interval = 0;
        }
        if (error == EGL_SUCCESS) {
            interval = t[1];
            latency = t[2] > 0 ? t[2] : interval;
        }
        if (follow) ask_again = follow_display(now, interval, gap);
        if (error == EGL_SUCCESS && pace) {
            // Refreshes per frame; even pacing needs a whole number of them.
            double ratio = 1e9 / (static_cast<double>(app_frame_rate()) * static_cast<double>(interval));
            n = std::llround(ratio);
            if (n < 1 || std::fabs(ratio - static_cast<double>(n)) > 0.1) n = 0;
            // Once per refresh rate (the display may switch when the window asks for one).
            if (std::llabs(interval - p.logged_interval) > interval / 20) {
                log("arm32: pacing: refresh every %.2f ms, on screen %.2f ms after composition, %lld refreshes per frame%s",
                    static_cast<double>(ms(interval)), static_cast<double>(ms(latency)), static_cast<long long>(n),
                    n == 0 ? " (not a whole number: unpaced)" : n == 1 ? " (unpaced: the game's limiter keeps step)" : "");
                p.logged_interval = interval;
            }
            // One refresh per frame: nothing to even out (see the top of the file).
            if (n == 1) {
                n = 0;
                // Pacing over (if it ran): the game's cap is the frame rate again at the next turn.
                g_active_until.store(0, std::memory_order_relaxed);
            }
            if (n) {
                // The next composition deadline far enough ahead, and when that composition shows.
                Nanos deadline = t[0];
                while (deadline < now + kMargin) deadline += interval;
                Nanos earliest = deadline + latency;
                target = earliest;
                if (p.target) {
                    Nanos want = p.target + n * interval;
                    // In time: on the latest estimate of the refresh grid, and never more than a
                    // frame ahead. Late: the first refresh it can make.
                    if (want >= earliest - interval / 2) target = earliest + std::min((want - earliest + interval / 2) / interval, n - 1) * interval;
                }
                if (p.frame_start) report_work(now - p.frame_start, n * interval);
                // Halfway between refreshes, so the compositor shows it at `target` and not one off.
                if (e.presentation_time(d, s, target - interval / 2) == EGL_TRUE) p.timed = true;
                else take_error(e);
            }
        }
    } else if (follow) {
        // No frame timestamps on this window: nothing to follow.
        ask_again = follow_display(now, 0, gap);
    }
    // Interval 1 while pacing, the game's own otherwise (see the top of the file).
    const bool paced = n > 1;
    // A presentation time stays on the window for every later frame until replaced. Unpaced frames
    // go back to the automatic one: the compositor drops a frame with a time of its own when a
    // newer one is due too. The adaptive panel of a Galaxy S26 Ultra goes to 120 Hz for a second
    // now and then (paced meanwhile), and afterwards 6 to 7 % of the frames never reached the
    // screen.
    if (!paced && p.timed) {
        if (e.presentation_time(d, s, kAutoTimestamp) != EGL_TRUE) take_error(e);
        p.timed = false;
    }
    if (paced != g_paced_interval.load(std::memory_order_relaxed) && e.swap_interval) {
        const EGLint use = paced ? 1 : g_game_interval.load(std::memory_order_relaxed);
        if (e.swap_interval(d, use) == EGL_TRUE) {
            g_paced_interval.store(paced, std::memory_order_relaxed);
            log("arm32: pacing: swap interval %d (%s)", use, paced ? "paced" : "the game's");
        } else {
            take_error(e);
        }
    }
    EGLuint64KHR id = 0;
    // Present times for the stats, and for the pace check of a followed rate above 60.
    bool tracked = (count || (follow && e.next_frame_id && e.frame_timestamps && followed_frame_rate() > 60)) &&
                   p.timestamps && !p.no_present;
    if (tracked && e.next_frame_id(d, s, &id) != EGL_TRUE) {
        take_error(e);
        tracked = false;
    }
    // The swap itself without the lock: it may block, and another thread may want to report a
    // destroyed surface meanwhile.
    lock.unlock();
    // A fallback's rate for the window, asked outside the lock (a call into the system).
    if (ask_again) request_window_frame_rate();
    EGLBoolean ok = e.swap(d, s);
    // A failed swap's error is the game's to read: no more EGL calls, no pacing.
    if (ok != EGL_TRUE) return ok;
    lock.lock();
    if (p.surface != s) return ok;
    if (tracked) {
        // Not paced, a frame's time is what the rate says; the game's limiter holds it there.
        const float pace_rate = app_frame_rate();
        const Nanos unpaced = pace_rate > 0 ? static_cast<Nanos>(1e9f / pace_rate) : interval;
        p.swapped.push_back(Swapped{id, target, interval, n ? interval * n : std::max(interval, unpaced), now});
        collect_shown(p, d, s, e);
    }
    if (!n) {
        // Not paced: the game's own limiter keeps the frame rate.
        p.target = 0;
        p.frame_start = 0;
        // The time since the last swap, without the limiter's sleep, is this frame's work. Not after
        // a pause: that gap says nothing about a frame.
#ifndef ARM32_SHIM
        // (The shim does not see the limiter's sleep, so it has nothing to report for these frames.)
        const Nanos returned = now_ns();
        if (p.unpaced_start && interval > 0 && now - p.unpaced_start < 100000000) {
            const Nanos budget = static_cast<Nanos>(1e9f / app_frame_rate());
            const Nanos slept = t_guest_sleep_ns - p.unpaced_slept;
            const Nanos work = now - p.unpaced_start - slept;
            // While the game itself aims lower (it steps down when idle) its limiter holds the frames back
            // in ways this thread's sleep does not show: 55 ms of "work" per frame at 18 fps. That must
            // not be reported, or an idle game would run at raised clocks.
            if (game_target_frame_rate() >= app_frame_rate()) report_work(work, budget);
            if (g_stats) {
                static thread_local Nanos sum = 0;
                static thread_local int count = 0;
                sum += work;
                if (++count == 240) {
                    log("arm32: unpaced work %.2f ms per frame, budget %.2f", static_cast<double>(sum) / count / 1e6, static_cast<double>(budget) / 1e6);
                    sum = 0;
                    count = 0;
                }
            }
        }
        p.unpaced_start = returned;
        p.unpaced_slept = t_guest_sleep_ns;
#endif
        return ok;
    }
    p.target = target;
    p.unpaced_start = 0;
    g_active_until.store(now + kSecond, std::memory_order_relaxed);
    // The next frame starts shortly before this one's composition deadline: it then has its n
    // refreshes, and this frame is no longer waiting in the queue.
    const Nanos resume = target - latency - kMargin;
    lock.unlock();
    if (resume > now_ns()) sleep_until(resume);
    lock.lock();
    if (p.surface == s) p.frame_start = now_ns();
    return ok;
}

}  // namespace arm32
