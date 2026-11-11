// Checks following the display (arm32/src/follow.cpp) on the build machine, with a display and a game the test plays:
//   c++ -std=c++20 -Iarm32/src arm32/tests/host/follow_test.cpp arm32/src/follow.cpp -o /tmp/follow_test && /tmp/follow_test
//
// A computer's display at 240 Hz keeps every refresh through what a song that played well shows (a fifth of the frames
// late, a song's load), goes to every second refresh when more than a quarter are late three check windows in a row,
// tries every refresh again 5 s later, goes back down at once when the try falls short and waits 10 s for the next, and
// waits 5 s again once a rate has held for half a minute; vsync off keeps the limit. A phone's 120 Hz panel steps down
// to 90, 72 and 60 as it follows what the window asks (3 % of frames late make a window short there), a panel that stays
// at 120 Hz goes to 60 and is asked for it; the phone's own word that it is hot steps down every half minute.
#include "follow.h"

#include <algorithm>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <string>
#include <utility>
#include <vector>

// host.h's stats switch and log, which follow.cpp writes to: the log kept, for the checks that read it.
namespace arm32 {
bool g_stats = false;
std::vector<std::string> g_log;
void log(const char* fmt, ...) {
    char line[512];
    va_list ap;
    va_start(ap, fmt);
    std::vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    g_log.push_back(line);
}
}  // namespace arm32

namespace {

using arm32::followed_frame_rate;
using arm32::followed_window_rate;
using arm32::FollowHooks;

constexpr std::int64_t kSecond = 1000000000;

int g_checks = 0, g_failures = 0;

// One check: its name, and what was seen when it did not hold.
void check(bool ok, const std::string& what, const std::string& seen = "") {
    ++g_checks;
    if (ok) return;
    ++g_failures;
    std::printf("FAIL %s%s%s\n", what.c_str(), seen.empty() ? "" : ": ", seen.c_str());
}

// What the runtime around it answers, as the test sets it: the game aims high, the low resolution is not wanted until
// marked, vsync on and no limit; changes of rate counted.
int g_game = 1000;
bool g_low = false;
int g_low_noted = 0;
bool g_vsync = true;
float g_cap = 0;
int g_rate_changes = 0;
const FollowHooks kHooks{
    [] { return g_game; },
    [] { return g_low; },
    [] {
        // As pacing.cpp's: once marked it is wanted from then on, and marking it again does nothing.
        if (g_low) return;
        ++g_low_noted;
        g_low = true;
    },
    [] { return g_vsync; },
    [] { return g_cap; },
    [] { ++g_rate_changes; },
};

// A display and a game: frames at the followed rate on the display's refreshes, a share of them shown a refresh late.
// A phone's panel can follow what the window asks, as Android's switch when they have that rate.
struct Play {
    std::int64_t now = 100 * kSecond;  // the monotonic clock, far from 0
    double hz = 60;                    // the display's refresh rate
    bool host = false;                 // a computer's display, whose rate the player reads
    bool panel_follows = false;        // a phone's panel goes to the rate the window asks for
    int late_per_100 = 0;              // frames shown late, of each hundred
    double capacity = 0;               // the most frames a second the computer makes: above it every frame is late (0: no limit)
    long frame = 0;
    // Each change of the frame rate and of the window's ask, with when.
    std::vector<std::pair<std::int64_t, float>> rates, asks;

    // Frames until the frame rate changes, or `seconds` at most; true when it changed.
    bool run_to_change(double seconds) {
        const float rate = followed_frame_rate();
        for (double t = 0; t < seconds; t += 0.05) {
            run(0.05);
            if (followed_frame_rate() != rate) return true;
        }
        return false;
    }

    // `seconds` of frames.
    void run(double seconds) {
        const std::int64_t until = now + static_cast<std::int64_t>(seconds * 1e9);
        while (now < until) {
            const auto interval = static_cast<std::int64_t>(std::llround(1e9 / hz));
            // A frame stays for as many whole refreshes as the rate makes, one at least.
            const long long per = std::max(1LL, std::llround(hz / static_cast<double>(followed_frame_rate())));
            const std::int64_t gap = interval * per;
            now += gap;
            const float rate = followed_frame_rate(), ask = followed_window_rate();
            const bool ask_again = arm32::follow_display(kHooks, now, interval, gap, host);
            // Its time on screen came, as a phone's present time or a computer's refresh says.
            const bool behind = capacity > 0 && static_cast<double>(followed_frame_rate()) > capacity;
            arm32::follow_note_shown(now, behind || frame % 100 < late_per_100);
            ++frame;
            if (followed_frame_rate() != rate) rates.emplace_back(now, followed_frame_rate());
            if (followed_window_rate() != ask) asks.emplace_back(now, followed_window_rate());
            // The window asks the display again: a panel that follows goes there.
            if (ask_again && panel_follows) hz = followed_window_rate();
        }
    }
};

// A run from the state a start finds, the test's answers back at their own.
Play fresh(double hz, bool host) {
    arm32::follow_reset();
    arm32::g_log.clear();
    g_game = 1000;
    g_low = false;
    g_low_noted = 0;
    g_vsync = true;
    g_cap = 0;
    g_rate_changes = 0;
    Play p;
    p.hz = hz;
    p.host = host;
    return p;
}

// Seconds between two times of the clock.
double seconds(std::int64_t from, std::int64_t to) { return static_cast<double>(to - from) / 1e9; }

std::string rate_text(float r) {
    char text[32];
    std::snprintf(text, sizeof text, "%.2f", static_cast<double>(r));
    return text;
}

// A computer's display at 240 Hz: a fifth of the frames late (a song that played well, a song's load) keeps every refresh;
// 40 % late (more than the quarter that makes a window short) three windows in a row, every second refresh; every refresh again 5 s later; a try that falls
// short, back down in its first window, and the next try 10 s after that; half a minute held, the first wait again.
void computer_display() {
    Play p = fresh(240, true);
    p.run(1);
    check(std::fabs(followed_frame_rate() - 240) < 0.01f, "240 Hz: every refresh at first", rate_text(followed_frame_rate()));
    // 2 % late, then 20 % for 15 s (the page before a song while it loads showed up to 10 %): under the quarter that makes
    // a window short.
    p.late_per_100 = 2;
    p.run(20);
    check(std::fabs(followed_frame_rate() - 240) < 0.01f, "240 Hz, 2 % of frames late: no step down", rate_text(followed_frame_rate()));
    p.late_per_100 = 20;
    p.run(15);
    check(std::fabs(followed_frame_rate() - 240) < 0.01f && p.rates.size() == 1, "240 Hz, 20 % late for 15 s: no step down",
          rate_text(followed_frame_rate()));
    // 40 % late: three short windows of 2 s, a step down to every second refresh; on time again from the step on.
    p.late_per_100 = 40;
    const std::int64_t late_from = p.now;
    p.run_to_change(10);
    p.late_per_100 = 0;
    check(!p.rates.empty() && std::fabs(p.rates.back().second - 120) < 0.01f, "240 Hz, 40 % late: every second refresh",
          rate_text(followed_frame_rate()));
    const std::int64_t down = p.rates.empty() ? 0 : p.rates.back().first;
    check(seconds(late_from, down) > 5.9 && seconds(late_from, down) < 8.1, "240 Hz: the step after three windows of 2 s",
          std::to_string(seconds(late_from, down)) + " s");
    // Every frame on time from then on: every refresh again 5 s after the step down, not before.
    p.late_per_100 = 0;
    p.run(4.5 - seconds(down, p.now));
    check(std::fabs(followed_frame_rate() - 120) < 0.01f, "120 on 240 Hz: still 4.5 s after the step down");
    p.run(1);
    check(std::fabs(followed_frame_rate() - 240) < 0.01f, "120 on 240 Hz: every refresh again 5 s after the step down",
          rate_text(followed_frame_rate()));
    const std::int64_t up = p.rates.back().first;
    check(seconds(down, up) >= 5 && seconds(down, up) < 5.1, "240 Hz: the try 5 s after the step", std::to_string(seconds(down, up)) + " s");
    // The try falls short: back down within its first window (2 s), not after three.
    p.late_per_100 = 40;
    p.run_to_change(3);
    p.late_per_100 = 0;
    const std::int64_t down2 = p.rates.back().first;
    check(std::fabs(followed_frame_rate() - 120) < 0.01f && down2 > up && seconds(up, down2) < 2.1,
          "240 Hz: a try that falls short goes back down in its first window", std::to_string(seconds(up, down2)) + " s");
    // The next try 10 s after that, not 5.
    p.late_per_100 = 0;
    p.run(9.5 - seconds(down2, p.now));
    check(std::fabs(followed_frame_rate() - 120) < 0.01f, "240 Hz: after a failed try, not up again within 9.5 s");
    p.run(1);
    check(std::fabs(followed_frame_rate() - 240) < 0.01f && seconds(down2, p.rates.back().first) >= 10,
          "240 Hz: after a failed try, up again 10 s after", std::to_string(seconds(down2, p.rates.back().first)) + " s");
    // Held for half a minute: the next step down waits the first 5 s again.
    p.run(32);
    p.late_per_100 = 40;
    p.run_to_change(8);
    p.late_per_100 = 0;
    const std::int64_t down3 = p.rates.back().first;
    check(std::fabs(followed_frame_rate() - 120) < 0.01f, "240 Hz: down again when 40 % are late", rate_text(followed_frame_rate()));
    p.late_per_100 = 0;
    p.run(5.5 - seconds(down3, p.now));
    check(std::fabs(followed_frame_rate() - 240) < 0.01f && seconds(down3, p.rates.back().first) < 5.1,
          "240 Hz: after half a minute held, the first wait (5 s) again", std::to_string(seconds(down3, p.rates.back().first)) + " s");
    check(g_low_noted == 0, "a computer's display never marks the low resolution");
}

// A computer that is really behind: it makes 130 frames a second at most, so at 240 Hz every frame is a refresh late and
// at every second refresh none is. It steps down, each try back up falls short in its first window, and the waits
// between tries double to a minute and stay there; 120 holds meanwhile.
void computer_overloaded() {
    Play p = fresh(240, true);
    p.capacity = 130;
    p.run(240);
    // Down to every second refresh, then tries at 5, 10, 20, 40, 60 and 60 s gaps: 240 for at most 2 s each time.
    std::vector<double> ups;
    for (std::size_t i = 1; i < p.rates.size(); ++i) {
        if (p.rates[i].second > p.rates[i - 1].second) ups.push_back(seconds(p.rates[i - 1].first, p.rates[i].first));
    }
    check(ups.size() >= 5 && std::fabs(ups[0] - 5) < 0.1 && std::fabs(ups[1] - 10) < 0.1 && std::fabs(ups[2] - 20) < 0.1 &&
              std::fabs(ups[3] - 40) < 0.1 && std::fabs(ups[4] - 60) < 0.1,
          "overloaded: tries back up after 5, 10, 20, 40 and 60 s", std::to_string(ups.size()) + " tries");
    double at_240 = 0;
    for (std::size_t i = 0; i < p.rates.size(); ++i) {
        const std::int64_t until = i + 1 < p.rates.size() ? p.rates[i + 1].first : p.now;
        if (std::fabs(p.rates[i].second - 240) < 0.01f && i > 0) at_240 += seconds(p.rates[i].first, until);
    }
    check(at_240 < 2.1 * static_cast<double>(ups.size()), "overloaded: each try lasts one window at most", std::to_string(at_240) + " s at 240");
    check(std::fabs(followed_frame_rate() - 120) < 0.01f || std::fabs(followed_frame_rate() - 240) < 0.01f,
          "overloaded: at 120 between tries, never lower", rate_text(followed_frame_rate()));
    bool lower = false;
    for (const auto& r : p.rates) lower = lower || r.second < 119;
    check(!lower, "overloaded: no step below 120, which the computer makes");
}

// A computer's display with vsync off and a limit: the limit by the clock, and no steps however late the frames.
void computer_vsync_off() {
    Play p = fresh(240, true);
    g_vsync = false;
    g_cap = 144;
    p.late_per_100 = 20;
    p.run(30);
    check(std::fabs(followed_frame_rate() - 144) < 0.01f && p.rates.size() == 1, "vsync off, a limit of 144: 144 throughout",
          rate_text(followed_frame_rate()));
}

// A phone's 120 Hz panel that goes to the rate its window asks for: 120, then 90, 72 and 60, three short windows each.
void phone_panel_follows() {
    Play p = fresh(120, false);
    p.panel_follows = true;
    // The window asks for 144 at first; the panel stays at 120, which counts once it has held for a second.
    p.run(2);
    check(std::fabs(followed_frame_rate() - 120) < 0.01f && std::fabs(followed_window_rate() - 144) < 0.01f, "phone: 120 fps on a 120 Hz panel",
          rate_text(followed_frame_rate()));
    p.late_per_100 = 5;
    // Three windows short at each rate, and a second for the panel's new rate to count.
    p.run(9);
    check(std::fabs(followed_window_rate() - 90) < 0.01f && std::fabs(followed_frame_rate() - 90) < 0.01f, "phone: then 90 asked and followed",
          rate_text(followed_window_rate()) + " asked, " + rate_text(followed_frame_rate()));
    p.run(9);
    check(std::fabs(followed_window_rate() - 72) < 0.01f && std::fabs(followed_frame_rate() - 72) < 0.01f, "phone: then 72",
          rate_text(followed_window_rate()) + " asked, " + rate_text(followed_frame_rate()));
    p.run(9);
    check(std::fabs(followed_window_rate() - 60) < 0.01f && std::fabs(followed_frame_rate() - 60) < 0.01f, "phone: then 60",
          rate_text(followed_window_rate()) + " asked, " + rate_text(followed_frame_rate()));
    // 60 is as low as it goes.
    p.run(30);
    check(std::fabs(followed_frame_rate() - 60) < 0.01f, "phone: nothing below 60", rate_text(followed_frame_rate()));
    // The asks in order: 90, 72, 60, each once.
    std::vector<float> asked;
    for (const auto& a : p.asks) asked.push_back(a.second);
    check(asked == std::vector<float>({90, 72, 60}), "phone: the window asked 90, 72, 60 in turn");
    // Frames short while drawing at 120: the low resolution marked for the next start, once.
    check(g_low_noted == 1, "phone: the low resolution marked once", std::to_string(g_low_noted));
}

// A phone's panel that stays at 120 Hz whatever the window asks: 90 asked, which the panel's whole fractions make 60,
// and then the panel asked for 60 itself.
void phone_panel_stays() {
    Play p = fresh(120, false);
    p.run(2);
    p.late_per_100 = 5;
    p.run(9);
    check(std::fabs(followed_frame_rate() - 60) < 0.01f, "phone, panel at 120: 60 fps after the step", rate_text(followed_frame_rate()));
    check(std::fabs(followed_window_rate() - 60) < 0.01f, "phone, panel at 120: the panel asked for 60", rate_text(followed_window_rate()));
}

// The phone hot (thermal status SEVERE): a step down at once and every half minute while it lasts, down to 60.
void phone_hot() {
    Play p = fresh(120, false);
    p.panel_follows = true;
    p.run(2);
    arm32::follow_thermal(3);
    p.run(100);
    std::vector<float> asked;
    for (const auto& a : p.asks) asked.push_back(a.second);
    check(asked == std::vector<float>({90, 72, 60}), "hot: the window asked 90, 72, 60");
    if (p.asks.size() == 3) {
        const double first = seconds(p.asks[0].first, p.asks[1].first), second = seconds(p.asks[1].first, p.asks[2].first);
        check(first >= 30 && first < 30.1 && second >= 30 && second < 30.1, "hot: a step every 30 s",
              std::to_string(first) + " s, " + std::to_string(second) + " s");
    }
    check(std::fabs(followed_frame_rate() - 60) < 0.01f, "hot: 60 fps at the end", rate_text(followed_frame_rate()));
    // Cool again: nothing steps back up on a phone until the app starts again.
    arm32::follow_thermal(0);
    p.run(60);
    check(std::fabs(followed_frame_rate() - 60) < 0.01f, "cool again: a phone stays at 60 until the next start");
}

// The game aiming lower than the frame rate (it steps down by itself, idle): nothing is checked meanwhile.
void game_aims_lower() {
    Play p = fresh(240, true);
    g_game = 60;
    p.late_per_100 = 20;
    p.run(20);
    check(std::fabs(followed_frame_rate() - 240) < 0.01f, "the game aiming at 60: no check, no step", rate_text(followed_frame_rate()));
}

}  // namespace

int main() {
    computer_display();
    computer_overloaded();
    computer_vsync_off();
    phone_panel_follows();
    phone_panel_stays();
    phone_hot();
    game_aims_lower();
    if (g_failures) {
        std::printf("%d of %d checks FAILED\n", g_failures, g_checks);
        return 1;
    }
    std::printf("%d checks\nALL CHECKS PASSED\n", g_checks);
    return 0;
}
