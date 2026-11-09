// Checks the frame limit's arithmetic on a computer's display (arm32/src/pacing_math.h) on the build machine:
//   c++ -std=c++20 -Iarm32/src arm32/tests/host/pacing_math_test.cpp -o /tmp/pacing_math_test && /tmp/pacing_math_test
//
// For the displays people play on (60, 75, 120, 144, 165, 180, 240 and 360 Hz, and the odd rates displays really report,
// 59.94 and 240.084), and the limits the PC client offers: which keep every frame on the same number of refreshes (that
// number), and which go by the clock (0), each with the frame rate it gives.
#include "pacing_math.h"

#include <cstdio>
#include <initializer_list>

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

    if (g_failures) {
        std::printf("%d of %d checks FAILED\n", g_failures, g_checks);
        return 1;
    }
    std::printf("%d checks\nALL CHECKS PASSED\n", g_checks);
    return 0;
}
