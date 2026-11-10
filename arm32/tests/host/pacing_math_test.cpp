// Checks the frame limit's arithmetic on a computer's display (arm32/src/pacing_math.h) on the build machine:
//   c++ -std=c++20 -Iarm32/src arm32/tests/host/pacing_math_test.cpp -o /tmp/pacing_math_test && /tmp/pacing_math_test
//
// For the displays people play on (60, 75, 120, 144, 165, 180, 240 and 360 Hz, and the odd rates displays really report,
// 59.94 and 240.084), and the limits the PC client offers: which keep every frame on the same number of refreshes (that
// number), and which go by the clock (0), each with the frame rate it gives. Then the frames that go by the clock (vsync
// off, or a limit no whole fraction holds): each one frame's time after the one before, whatever the game's own limiter
// does, and after a frame late by more than that, from it on with no burst.
#include "pacing_math.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include <string>
#include <vector>

namespace {

int g_checks = 0, g_failures = 0;

// One display and limit, the refreshes per frame expected (0: by the clock).
void expect(double hz, float cap, int want) {
    ++g_checks;
    const int got = arm32::host_top(hz, cap);
    if (got != want) {
        ++g_failures;
        std::printf("FAIL %.3f Hz, limit %.0f: %d refreshes a frame, expected %d\n", hz, static_cast<double>(cap), got, want);
    }
}

// One check of the frames by the clock: its name, and what was seen when it did not hold.
void check(bool ok, const std::string& what, const std::string& seen = "") {
    ++g_checks;
    if (ok) return;
    ++g_failures;
    std::printf("FAIL %s%s%s\n", what.c_str(), seen.empty() ? "" : ": ", seen.c_str());
}

// The refresh interval of a display at `hz`, in nanoseconds, as the player reads it.
std::int64_t interval_of(double hz) { return static_cast<std::int64_t>(1e9 / hz + 0.5); }

// The display at `hz` with the frame rate in use at `rate`: the refreshes per frame expected (0: by the clock).
void expect_refreshes(double hz, double rate, int want) {
    const int got = arm32::host_refreshes(rate, interval_of(hz));
    char seen[96];
    std::snprintf(seen, sizeof seen, "%d refreshes a frame, expected %d", got, want);
    check(got == want, "refreshes a frame at " + std::to_string(rate) + " fps on " + std::to_string(hz) + " Hz", seen);
}

// The swaps of `frames` frames paced by the clock at `rate`: each frame's work takes `work(i)` nanoseconds after the swap
// before it came back (the game drawing, its own limiter waiting), its swap goes out at clock_due, and the thread waits
// until then, as paced_swap does. The times the frames went out.
template <class Work>
std::vector<std::int64_t> run_clock(float rate, int frames, Work&& work) {
    std::vector<std::int64_t> out;
    std::int64_t now = 1000000000, last = 0;
    for (int i = 0; i < frames; ++i) {
        // The frame's work, then its swap, which comes back at once with vsync off.
        now += work(i);
        const std::int64_t due = arm32::clock_due(last, rate, now);
        last = due;
        out.push_back(due);
        // The wait until it is due, if it is not already.
        now = std::max(now, due);
    }
    return out;
}

// The gaps between the times frames went out, in nanoseconds.
std::vector<std::int64_t> gaps(const std::vector<std::int64_t>& t) {
    std::vector<std::int64_t> g;
    for (std::size_t i = 1; i < t.size(); ++i) g.push_back(t[i] - t[i - 1]);
    return g;
}

void clock_pacing() {
    // The first frame: at once.
    check(arm32::clock_due(0, 144, 5000000) == 5000000, "by the clock: the first frame at once");
    // A frame's time after the last one, rounded down to the nanosecond (6944444 at 144).
    check(arm32::clock_due(1000000000, 144, 1001000000) == 1006944444, "by the clock: one frame's time after the last");
    // Late by less than a frame's time: its own time still, already past, so it goes at once and the next one is early
    // again by as much.
    check(arm32::clock_due(1000000000, 144, 1010000000) == 1006944444, "by the clock: a little late keeps its time");
    // Late by exactly a frame's time: still its own time.
    check(arm32::clock_due(1000000000, 144, 1013888888) == 1006944444, "by the clock: a frame's time late keeps its time");
    // Late by more: from now.
    check(arm32::clock_due(1000000000, 144, 1013888889) == 1013888889, "by the clock: more than a frame's time late starts over");

    // The game's own limiter above the limit (246.6 frames a second for 240, in uneven steps): every frame one frame's
    // time after the one before, to the nanosecond, the rate the limit.
    const std::vector<std::int64_t> even = run_clock(240, 2400, [](int i) { return 3000000 + (i * 7919 % 1000000); });
    const std::vector<std::int64_t> g = gaps(even);
    const auto [low, high] = std::minmax_element(g.begin(), g.end());
    check(*low == 4166666 && *high == 4166666, "by the clock: an uneven limiter's frames go out evenly",
          std::to_string(*low) + " to " + std::to_string(*high) + " ns apart");
    const double fps = 1e9 * static_cast<double>(even.size() - 1) / static_cast<double>(even.back() - even.front());
    check(fps > 239.99 && fps < 240.01, "by the clock: 240 frames a second for a limit of 240", std::to_string(fps));

    // At 144 on a 240 Hz display: the same, 144 a second.
    const std::vector<std::int64_t> at144 = run_clock(144, 1440, [](int i) { return 5000000 + (i % 3) * 600000; });
    const double fps144 = 1e9 * static_cast<double>(at144.size() - 1) / static_cast<double>(at144.back() - at144.front());
    check(fps144 > 143.99 && fps144 < 144.01, "by the clock: 144 frames a second for a limit of 144", std::to_string(fps144));

    // One frame 3 ms late at 144 (less than its 6.9 ms): the frames after it make up the difference, none dropped, and
    // the count is back on its times two frames later.
    const std::vector<std::int64_t> late = run_clock(144, 20, [](int i) { return i == 10 ? 9900000 : 3000000; });
    const std::int64_t period = 6944444;
    bool on_grid = true;
    for (std::size_t i = 1; i < late.size(); ++i) on_grid = on_grid && late[i] == late[0] + static_cast<std::int64_t>(i) * period;
    check(on_grid, "by the clock: a frame a little late, and the times after it as they were");

    // A load holding a frame 50 ms at 240: it goes out as soon as it is done, and the count starts again from it, the
    // next frame one frame's time after it, not a burst of the eleven that would have been due meanwhile.
    const std::vector<std::int64_t> stall = run_clock(240, 30, [](int i) { return i == 15 ? 50000000 : 2000000; });
    const std::vector<std::int64_t> sg = gaps(stall);
    bool steady_after = true;
    for (std::size_t i = 15; i < sg.size(); ++i) steady_after = steady_after && sg[i] == 4166666;
    check(sg[14] == 50000000 && steady_after, "by the clock: after a 50 ms stall, frames one frame's time apart from it, no burst",
          std::to_string(sg[14]) + " ns for the late one");
}

}  // namespace

int main() {
    // No limit: every refresh, whatever the display.
    for (double hz : {59.94, 60.0, 75.0, 120.0, 144.0, 165.0, 180.0, 240.084, 360.0}) expect(hz, 0, 1);

    // A limit at or above the display's rate: every refresh.
    expect(60.0, 60, 1);
    expect(59.94, 60, 1);
    expect(60.0, 120, 1);
    expect(144.0, 144, 1);
    expect(180.0, 240, 1);
    expect(240.084, 240, 1);

    // A whole fraction of the rate: the same refreshes for every frame.
    expect(240.084, 120, 2);  // 120 fps, every second refresh
    expect(240.084, 80, 3);
    expect(240.084, 60, 4);
    expect(144.0, 72, 2);
    expect(144.0, 48, 3);
    expect(180.0, 90, 2);
    expect(180.0, 60, 3);
    expect(165.0, 82, 2);     // 82.5 fps: within 3 % of the limit
    expect(165.0, 60, 3);     // 55 fps: within 10 % under it
    expect(360.0, 120, 3);
    expect(360.0, 180, 2);
    expect(75.0, 37, 2);      // 37.5 fps
    expect(120.0, 60, 2);

    // Within 10 % above a fraction: that fraction (130 on a 240 Hz display is 120, 92 % of it).
    expect(240.084, 130, 2);

    // No fraction near: by the clock, each frame still on a refresh.
    expect(240.084, 144, 0);  // the fraction would be 120, 83 % of 144
    expect(144.0, 120, 0);    // 72, 60 %
    expect(144.0, 60, 0);     // 48, 80 %
    expect(165.0, 144, 0);    // 82.5
    expect(165.0, 120, 0);
    expect(180.0, 144, 0);    // 90
    expect(180.0, 120, 0);
    expect(360.0, 240, 0);    // 180, 75 %
    expect(60.0, 45, 0);      // 30

    // More refreshes a frame than the swap holds: by the clock.
    expect(240.084, 30, 0);   // would be 8
    expect(360.0, 60, 0);     // would be 6
    expect(180.0, 30, 0);     // would be 6

    // The refreshes a frame stays for at the frame rate in use, which decides between the two ways of pacing: a whole
    // fraction of the display's rate within a tenth of a refresh, at most the four the swap holds.
    expect_refreshes(240.084, 240.084, 1);
    expect_refreshes(240.084, 240.084 / 2, 2);
    expect_refreshes(240.084, 120, 2);       // the limit's 120: 2.0007 refreshes
    expect_refreshes(240.084, 60, 4);
    expect_refreshes(144.0, 72, 2);
    expect_refreshes(59.94, 59.94, 1);
    expect_refreshes(165.0, 82.5, 2);
    expect_refreshes(240.084, 144, 0);       // 1.67 refreshes: by the clock
    expect_refreshes(144.0, 120, 0);         // 1.2
    expect_refreshes(165.0, 144, 0);         // 1.15: more than a tenth off
    expect_refreshes(165.0, 155, 1);         // 1.06: within a tenth
    expect_refreshes(360.0, 60, 0);          // 6, more than the swap holds
    expect_refreshes(240.084, 30, 0);        // 8
    expect_refreshes(240.084, 0, 0);         // no rate
    expect_refreshes(240.084, 300, 0);       // faster than the display: no whole number of refreshes

    // The frames that go by the clock.
    clock_pacing();

    if (g_failures) {
        std::printf("%d of %d checks FAILED\n", g_failures, g_checks);
        return 1;
    }
    std::printf("%d checks\nALL CHECKS PASSED\n", g_checks);
    return 0;
}
