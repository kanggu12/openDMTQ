// How large the player for Windows draws what it lays over the game (overlay_win32.cpp), and the smallest game area its
// window holds (window_win32.cpp): plain arithmetic, apart from any window, so that a check (settingstest.cpp) can take
// it through Windows' scales and the game's sizes.
//
// The game lays itself out for 720 lines and grows with its area, whatever Windows' scale: its words and buttons are 1.5
// times their 720-line size at 1080 lines and 3 times at 4K. The overlay is drawn at the game's own scale, so that in a
// small window it is as small as the game's own words, and on a display at 150 % it covers no more of the game than at
// 100 %. In a very small window its buttons would get too small to hit: it is never drawn below half its 720-line size
// at Windows' scale, where the bar's 40-pixel buttons are 20 of Windows' own pixels. The pointer keeps Windows' own size.
#pragma once

#include <algorithm>
#include <cmath>

namespace player::overlay {

// The lines the game lays itself out for: at this height of its area, the overlay is drawn at its 720-line size.
constexpr float kGameLines = 720;
// The least the overlay is drawn at, as a share of Windows' scale: half its 720-line size.
constexpr float kLeastScale = 0.5f;

// The overlay's scale over a game area `area_h` pixels high on a display at Windows' scale `dpi` (1 at 96 dpi, 1.5 at
// 150 %): the game's own, its area's height over 720, and never below half of Windows' scale.
inline float scale_for(int area_h, float dpi) {
    // The game's scale, as its own words and buttons have it.
    const float game = static_cast<float>(area_h) / kGameLines;
    // The floor, which only a small window on a scaled display reaches (below 360 lines at 100 %, 540 at 150 %).
    return std::max(game, kLeastScale * dpi);
}

// The smallest game area the window holds, in Windows' own pixels (those of a display at 100 %). There, at the least
// scale, the overlay's 720-line layout has 960 by 540 of room, as over a 960x540 game at 100 %: the bar's wordmark and
// its buttons, the notice and the counter keep apart at any scale, and every larger area has more room.
constexpr int kLeastAreaW = 480, kLeastAreaH = 270;

// A length in Windows' own pixels as the display's pixels at Windows' scale `dpi`: whole, and never less than it is (270
// at 125 % is 338).
inline int at_scale(int logical, float dpi) {
    // A hair over a whole number is that number: a scale like 1.75 comes from a division of the display's dpi by 96.
    return static_cast<int>(std::ceil(static_cast<float>(logical) * dpi - 0.001f));
}

}  // namespace player::overlay
