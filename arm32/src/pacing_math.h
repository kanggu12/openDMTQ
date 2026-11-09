// The frame limit's arithmetic on a computer's display (pacing.cpp), apart from the rest so that the build machine tests
// it on its own (arm32/tests/host/pacing_math_test.cpp): which displays and limits keep every frame on the same number
// of refreshes, and which go by the clock.
#pragma once

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

}  // namespace arm32
