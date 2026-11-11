// Following the display's refresh rate (follow.h): the state machine pacing.cpp feeds at each swap.
#include "follow.h"

#include "host.h"
#include "pacing_math.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <vector>

namespace arm32 {

namespace {

using Nanos = std::int64_t;
constexpr Nanos kSecond = 1000000000;

float ms(Nanos n) { return static_cast<float>(static_cast<double>(n) / 1e6); }

// A computer's display: the longest swap interval it is paced with (Direct3D's longest, four refreshes).
constexpr int kMaxHostInterval = kHostIntervalMost;
// A computer's display: after a step down, the wait before a step back up is tried (a song's load can hold the frames
// up for some seconds, after which the display's best holds again), doubled after each try that falls short, up to a
// minute; and how long a frame rate has to hold for the wait to start again from the first. A try costs little: one
// window short of the two it is checked over takes it back down at once.
constexpr Nanos kHostFirstRetry = 5LL * 1000000000, kHostLongestRetry = 60LL * 1000000000;
// Check windows (2 s each) that a rate stepped back up to has to pass, checked, for the wait to start from the first again:
// half a minute of frames that kept up, not half a minute of a menu left alone with the check off.
constexpr int kHostSettledWindows = 15;
// The check windows right after a step back up that decide the try: a short one among them steps down at once.
constexpr int kHostTryWindows = 2;
// A computer's check window falls short when more than a quarter of its frames were shown late: what a computer that is
// really behind shows (a frame a refresh late on every second refresh and worse, 49 % to 100 % of the frames, in the
// runs logged with the broadcast's encoder or a pass too slow for the card), and none of what a song that played well
// showed: at most 14 % in 99 windows of 100 at 240 Hz in the 4,451 windows of 76 runs on a 240 Hz display, the page
// before a song included (its loading, up to 10 %), and other programs busy on the computer meanwhile. A phone's panel
// keeps its 3 %: its steps down are to rates the panel itself switches to, and they also choose the resolution.
constexpr int kHostLatePercent = 25;
constexpr int kPhoneLatePercent = 3;

// Following the display (see pacing.cpp's top).
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
    double host_hz = 0;         // a computer's display: the rate followed from (0: none yet)
    int host_n = 1;             // and the refreshes per frame now (0: 60 fps, off its refreshes)
    int host_top = 1;           // the fewest refreshes per frame the player's frame cap allows (0: none, off them)
    Nanos host_retry_at = 0;    // when to try a step back up (0: at the top, or no try due)
    Nanos host_retry_wait = 0;  // the wait before the try after the next step down
    int host_held = -1;         // check windows passed since a step back up (-1: no step up to hold)
};
Follow g_follow;
std::atomic<float> g_followed_rate{60};
// What the window asks the display for: the highest of kRates at first, one lower with each step down.
std::atomic<float> g_window_rate{kRates[0]};
// The phone's own word on its temperature (follow_thermal), and when it last took a step down.
std::atomic<int> g_thermal_status{0};
Nanos g_thermal_step_at = 0;

}  // namespace

// The pace check's window and the wait for a new display rate start over (a new surface, a pause).
void follow_restart() {
    g_follow.gaps.clear();
    g_follow.window_start = 0;
    g_follow.shown = g_follow.shown_late = 0;
    g_follow.candidate_since = 0;
}

namespace {

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

// The window asks for one step less than the frame rate in use (60 at the end, for good) and the frame
// rate follows at once as far as the panel's rate `hz` allows (0: not known). The caller then has the
// window ask, outside the lock.
bool step_down(const FollowHooks& h, double hz) {
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
    h.rate_changed();
    g_follow.gaps.clear();
    g_follow.window_start = 0;
    g_follow.short_windows = 0;
    g_follow.shown = g_follow.shown_late = 0;
    g_follow.candidate_since = 0;
    return true;
}

// One step down on a computer's display, which keeps its rate (pacing.h): every second refresh, every third, and so on
// while that is 57 fps or more and the swap can hold a frame that long; after that 60 fps off its refreshes, for good.
// There is no window to ask: false.
bool step_down_host(const FollowHooks& h, Nanos now) {
    Follow& f = g_follow;
    const double hz = f.host_hz;
    const int n = f.host_n;
    float next = 0;
    if (n >= 1 && n < kMaxHostInterval && hz / (n + 1) >= 57) {
        f.host_n = n + 1;
        next = static_cast<float>(hz / (n + 1));
    } else if (g_followed_rate.load(std::memory_order_relaxed) > 61) {
        f.host_n = 0;
        next = 60;
    } else {
        return false;
    }
    g_window_rate.store(next, std::memory_order_relaxed);
    g_followed_rate.store(next, std::memory_order_relaxed);
    h.rate_changed();
    f.gaps.clear();
    f.window_start = 0;
    f.short_windows = f.drawing_short = 0;
    f.shown = f.shown_late = 0;
    f.candidate_since = 0;
    // A try back up after a wait, which doubles each time; a lower rate holding says nothing of the higher one.
    if (!f.host_retry_wait) f.host_retry_wait = kHostFirstRetry;
    f.host_retry_at = now + f.host_retry_wait;
    f.host_retry_wait = std::min(f.host_retry_wait * 2, kHostLongestRetry);
    f.host_held = -1;
    if (f.host_n) log("arm32: frame rate %.2f fps: every %d refreshes of the display", static_cast<double>(next), f.host_n);
    else log("arm32: frame rate 60 fps, off the display's refreshes");
    return false;
}

// One step back up on a computer's display, when the wait after a step down is over: every refresh again from every
// second, and so on, or from 60 fps off the refreshes to its nearest whole fraction. Another step up waits as long again;
// a step that falls short goes back down (pace_check), with the next wait doubled.
void step_up_host(const FollowHooks& h, Nanos now) {
    Follow& f = g_follow;
    const double hz = f.host_hz;
    int next = f.host_n - 1;
    if (f.host_n == 0) {
        // From 60 fps off the refreshes: the most refreshes per frame the swap can hold at 57 fps or more.
        next = 0;
        for (int k = kMaxHostInterval; k >= 1 && !next; --k) {
            if (hz / k >= 57) next = k;
        }
    }
    // Never above the player's frame cap (host_top: 1 without one).
    if (next < f.host_top) {
        f.host_retry_at = 0;
        return;
    }
    f.host_n = next;
    const float rate = static_cast<float>(hz / next);
    g_window_rate.store(rate, std::memory_order_relaxed);
    g_followed_rate.store(rate, std::memory_order_relaxed);
    h.rate_changed();
    f.gaps.clear();
    f.window_start = 0;
    f.short_windows = f.drawing_short = 0;
    f.shown = f.shown_late = 0;
    f.host_retry_at = next > 1 ? now + f.host_retry_wait : 0;
    f.host_held = 0;
    log("arm32: frame rate %.2f fps: a step back up, every %d refreshes of the display", static_cast<double>(rate), next);
}

// The frame limit's fraction of the display's rate, host_top(), is in pacing_math.h, tested on the build machine.

// The pace check of follow_display, on a phone's display and on a computer's (`host`), whose steps down differ. Returns
// true when the window has to ask the display again. Under the caller's lock (follow.h).
bool pace_check(const FollowHooks& h, Nanos now, Nanos gap, double hz, bool host) {
    Follow& f = g_follow;
    const float rate = g_followed_rate.load(std::memory_order_relaxed);
    // No lower rate to go to: 60 fps on a phone; on a computer's display also its fraction just above 60 (60.02 fps on a
    // 240.08 Hz display), and the 60 fps off its refreshes that comes after.
    const bool floor = host ? rate <= 61 : rate <= 60;
    // The pace check: while the game itself aims at least as high as the frame rate. At 60 fps there is no lower rate to go to, and
    // it runs only as long as there is still a lower resolution to go to. A window in which the game's target changed mixes two
    // paces: it starts over (the count of short windows stays).
    const int game = h.game_target();
    if ((!host && rate <= 60 && h.low_resolution_wanted()) || game < rate || game != f.window_game) {
        f.gaps.clear();
        f.window_start = 0;
        f.window_game = game;
        // Nothing is being checked: no window falls short meanwhile either (a step back up waits for none).
        if (host) f.short_windows = 0;
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
    // (A pause never gets here: it starts the window over, as a frame that stayed longer than kFollowPause does: a scene
    // being loaded is not judged.) Without present times, the rate the same share of late frames leaves: a quarter late
    // is four frames for every five refreshes.
    const int late_percent = host ? kHostLatePercent : kPhoneLatePercent;
    const bool fell_short = seen ? late * 100 > shown * late_percent : fps < rate * (host ? 0.8 : 0.97);
    f.short_windows = fell_short ? f.short_windows + 1 : 0;
    // For the resolution, which stays changed from then on: windows in which the game was drawing all along and did not keep up. A
    // scene being loaded holds everything up for some seconds, far below this, and says nothing about drawing.
    f.drawing_short = fell_short && fps >= rate * 0.4 ? f.drawing_short + 1 : 0;
    if (g_stats) {
        log("stats: frame rate check at %.0f fps (game %d): %.1f fps, %d of %d frames shown late, longest %.0f ms%s",
            static_cast<double>(rate), game, fps, late, shown, static_cast<double>(longest), fell_short ? ", short" : "");
    }
    // The resolution of a song that has begun cannot change under it, so that waits for the next start. Until then the frame rate
    // gives way, as far as it can. At 60 fps, with no step to take first, it takes a little longer to be sure. A computer's
    // display keeps its resolution: there it is the player's own choice (the render scale of the PC's settings), and the frame
    // rate's steps down are what the runtime does (nor could it keep the mark there).
    if (!host && f.drawing_short >= kShortWindows + (rate > 60 ? 0 : 2)) {
        log("arm32: frame rate: %.0f fps not kept while drawing (last 2 s: %.1f fps, %d of %d frames shown late)",
            static_cast<double>(rate), fps, late, shown);
        h.note_low_resolution();
    }
    // A try of a rate stepped back up to that falls short in its first windows: back down at once, the next try after the
    // doubled wait (step_down_host).
    if (host && f.host_held >= 0 && f.host_held < kHostTryWindows && fell_short && !floor) {
        log("arm32: frame rate: %.0f fps not kept after the step back up (last 2 s: %.1f fps, %d of %d frames shown late); back down",
            static_cast<double>(rate), fps, late, shown);
        return step_down_host(h, now);
    }
    // A rate stepped back up to that has kept up for a while: the next step down waits the first wait again.
    if (host && f.host_held >= 0 && !fell_short && ++f.host_held >= kHostSettledWindows) {
        f.host_retry_wait = kHostFirstRetry;
        f.host_held = -1;
    }
    if (floor || f.short_windows < kShortWindows) return false;
    log("arm32: frame rate: %.0f fps not kept (last 2 s: %.1f fps, %d of %d frames shown late); a step down",
        static_cast<double>(rate), fps, late, shown);
    return host ? step_down_host(h, now) : step_down(h, hz);
}

}  // namespace

// One swap of the window while following the display: `interval` is the display's refresh
// interval (0 when the compositor gave no timing), `gap` the time since the last swap (0 for the
// first), `host` true for a computer's display, whose interval the player gave (pacing.h). Returns
// true when the window has to ask the display again. Under the caller's lock (follow.h).
bool follow_display(const FollowHooks& h, Nanos now, Nanos interval, Nanos gap, bool host) {
    Follow& f = g_follow;
    const float asked = g_window_rate.load(std::memory_order_relaxed);
    if (!interval) {
        // Nothing to follow for two seconds' worth of swaps: 60 fps, the window asking for 60 Hz.
        if (asked <= 60 || ++f.timing_misses < 120) return false;
        log("arm32: frame rate: no compositor timing; 60 fps from now on");
        g_followed_rate.store(60, std::memory_order_relaxed);
        return step_down(h, 0);
    }
    f.timing_misses = 0;
    if (gap > kFollowPause) {
        follow_restart();
        gap = 0;
    }
    if (host) {
        // A computer's display keeps its own rate, which the player read from the system: no second of waiting for it to
        // settle, as for a phone's panel that switches. The frame rate starts at every refresh, whatever its rate (240 Hz,
        // 180 Hz, 59.94 Hz), or at the fraction of it the player's frame cap allows, and the steps down take its whole
        // fractions. Another display, or a new mode, starts over there.
        const double own = 1e9 / static_cast<double>(interval);
        if (std::fabs(own - f.host_hz) > own * 0.002) {
            const bool vsync = h.vsync();
            const float cap = h.fps_cap();
            f.host_hz = own;
            // Vsync off: no refreshes to keep to (0, as for a cap the swap cannot hold).
            f.host_top = vsync ? host_top(own, cap) : 0;
            f.host_n = f.host_top;
            f.host_retry_at = 0;
            f.host_retry_wait = kHostFirstRetry;
            f.host_held = -1;
            f.short_windows = f.drawing_short = 0;
            follow_restart();
            // On the refreshes, their fraction; off them, the cap, or the display's own rate without one.
            const float rate = f.host_n ? static_cast<float>(own / f.host_n) : cap > 0 ? cap : static_cast<float>(own);
            g_followed_rate.store(rate, std::memory_order_relaxed);
            g_window_rate.store(rate, std::memory_order_relaxed);
            h.rate_changed();
            if (!vsync) {
                log("arm32: frame rate %.2f fps: vsync off, frames as soon as drawn (the display at %.3f Hz)", static_cast<double>(rate), own);
            } else if (!f.host_n) {
                log("arm32: frame rate %.2f fps: the frame cap, off the refreshes of the display at %.3f Hz", static_cast<double>(rate), own);
            } else if (f.host_n == 1) {
                log("arm32: frame rate %.2f fps: every refresh of the display at %.3f Hz", static_cast<double>(rate), own);
            } else {
                // More than one refresh per frame from the start: the cap's doing.
                log("arm32: frame rate %.2f fps: every %d refreshes of the display at %.3f Hz, for the frame cap", static_cast<double>(rate), f.host_n, own);
            }
            return false;
        }
        // Off the refreshes by the player's choice (vsync off, or a cap the swap cannot hold): the game's own limiter keeps
        // the cap, and a frame that falls short is late by its own time alone, with no whole fraction to step down to.
        if (f.host_top == 0) return false;
        // The wait after a step down is over, and the last check window did not fall short: a step back up.
        if (f.host_retry_at && now >= f.host_retry_at && f.short_windows == 0) {
            step_up_host(h, now);
            return false;
        }
        return pace_check(h, now, gap, own, true);
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
        h.rate_changed();
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
        return step_down(h, hz);
    }
    return pace_check(h, now, gap, hz, false);
}

void follow_note_shown(Nanos at, bool late) {
    // Swapped in the check window that is open, if one is: a frame of a window that started over says nothing of this one.
    if (!g_follow.window_start || at < g_follow.window_start) return;
    ++g_follow.shown;
    if (late) ++g_follow.shown_late;
}

void follow_thermal(int status) { g_thermal_status.store(status, std::memory_order_relaxed); }

void follow_reset() {
    g_follow = Follow{};
    g_followed_rate.store(60, std::memory_order_relaxed);
    g_window_rate.store(kRates[0], std::memory_order_relaxed);
    g_thermal_status.store(0, std::memory_order_relaxed);
    g_thermal_step_at = 0;
}

float followed_frame_rate() { return g_followed_rate.load(std::memory_order_relaxed); }

float followed_window_rate() { return g_window_rate.load(std::memory_order_relaxed); }

}  // namespace arm32
