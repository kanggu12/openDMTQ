// The frame limit's arithmetic on a computer's display (pacing.cpp), apart from the rest so that the build machine tests
// it on its own (arm32/tests/host/pacing_math_test.cpp): which displays and limits keep every frame on the same number
// of refreshes, and which go by the clock, and when each frame goes out by the clock.
#pragma once

#include <cmath>
#include <cstdint>

namespace arm32 {

// The most refreshes the swap interval holds a frame for on a computer's display.
inline constexpr int kHostIntervalMost = 4;

// The fewest refreshes per frame of a display at `hz` that keep the frame rate at the player's cap or below (a 3 %
// margin: 120.04 fps on a 240.08 Hz display is a cap of 120): 1 without a cap. 0 when no whole fraction comes near the
// cap (120 on a 144 Hz display would be 72, 60 on it 48) or the swap cannot hold a frame for that many (30 on a 240 Hz
// display): the frames are then paced to the cap by the clock, off the refreshes (pacing.cpp, swap_window).
inline int host_top(double hz, float cap) {
    // No cap: every refresh.
    if (cap <= 0) return 1;
    for (int n = 1; n <= kHostIntervalMost; ++n) {
        // Still above the cap at this many refreshes a frame: one more.
        if (hz / n > static_cast<double>(cap) * 1.03) continue;
        // A fraction under 90 % of the cap is not what the player chose: the cap by the clock instead.
        return n == 1 || hz / n >= static_cast<double>(cap) * 0.9 ? n : 0;
    }
    // Even the most refreshes a frame stay above the cap: by the clock.
    return 0;
}

// The refreshes each frame stays on screen for at the frame rate `rate` on a display that refreshes every `interval`
// nanoseconds, which the swap interval holds it for (pacing.cpp): the whole number the rate is a fraction of, within a
// tenth of a refresh. 0 when it is no such fraction (144 fps on a 240 Hz display), or one past the most the swap holds:
// those frames go by the clock (clock_due).
inline int host_refreshes(double rate, std::int64_t interval) {
    // No rate or no refreshes: nothing to keep to.
    if (rate <= 0 || interval <= 0) return 0;
    const double ratio = 1e9 / (rate * static_cast<double>(interval));
    const long long n = std::llround(ratio);
    // Off a whole number by more than a tenth: frames would stay for one number of refreshes, then another.
    if (n < 1 || std::fabs(ratio - static_cast<double>(n)) > 0.1 || n > kHostIntervalMost) return 0;
    return static_cast<int>(n);
}

// When a frame paced by the clock goes out (pacing.cpp: vsync off, or a frame limit no whole fraction of the display's
// rate holds): one frame's time at `rate` (above 0) after `last`, the time the frame before went out (0: none yet),
// and at `now` (when the swap came back) for the first. A frame later than that by more than a frame's time starts the
// count again from itself: the frames after it go one frame's time apart, with no burst to catch up. One late by less
// keeps its time, and the frames after it make up the difference.
inline std::int64_t clock_due(std::int64_t last, float rate, std::int64_t now) {
    // A frame's time in nanoseconds, at the rate in use.
    const auto period = static_cast<std::int64_t>(1e9 / static_cast<double>(rate));
    std::int64_t due = last ? last + period : now;
    // More than a frame behind: from now.
    if (due < now - period) due = now;
    return due;
}

}  // namespace arm32
