// How large the player for Windows draws what it lays over the game (overlay_win32.cpp), the smallest game area its
// window holds (window_win32.cpp), and the size of the handle at the game's top centre, which has a scale of its own:
// plain arithmetic, apart from any window, so that a check (settingstest.cpp) can take it through Windows' scales and
// the game's sizes.
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

// ---- the handle

// The width the game lays its screens out for, beside its 720 lines.
constexpr float kGameWide = 1280;

// The handle at the game's top centre is the one piece of the overlay that is never pressed (the pointer rests on it,
// and its reach is larger than its picture), so it needs no least size to be hit: it is drawn at the game's own scale
// exactly, whatever Windows' scale. That is the scale the game fits its 1280 by 720 layout into its area at (measured
// on its frames at 4:3, 16:10, 16:9 and 21:9): its height over 720 in an area of 16:9 or wider, where the header's
// middle stays at the centre, and its width over 1280 in a narrower one, where the whole header is smaller than the
// height alone says. The handle then keeps its proportion to the game's own header in a window of any size and shape,
// and what it clears at 1280x720 it clears everywhere.
inline float handle_scale_for(int area_w, int area_h) {
    return std::min(static_cast<float>(area_w) / kGameWide, static_cast<float>(area_h) / kGameLines);
}

// The handle's tab at 720 lines: 25.6 wide where it hangs from the game's top edge, its sides leaning in 0.268 a pixel
// down as the game's own tabs' do (15 degrees), 18.5 high and 23 with the pointer on it; the line it hangs from (its
// rail) 2 high with a line of shade under it. As large as the game's header leaves room for (below).
constexpr float kTabTop = 25.6f, kTabTall = 18.5f, kTabTallLit = 23, kTabLean = 0.268f;
constexpr float kRailTall = 2, kRailShade = 1;

// The rail's rows and the rows of the shade under it, in pixels at the handle's `scale`: whole, so that both stay
// crisp; the rail at least one, the shade none where less than half a pixel of it is left (the smallest windows).
inline int rail_rows(float scale) { return std::max(1, static_cast<int>(std::lround(kRailTall * scale))); }
inline int shade_rows(float scale) { return static_cast<int>(std::lround(kRailShade * scale)); }

// Half the tab's width at `depth` below the game's top edge, at 720 lines.
constexpr float tab_half(float depth) { return kTabTop / 2 - depth * kTabLean; }

// What the game shows nearest its top centre, measured on its frames at 720 lines: on the screens with its header (the
// music list, the downloads, the nickname), the header's last button ends 12 left of the centre and starts at row 5;
// its rows above that hold no button and no word, and the words right of the centre start 34 away. So the handle may
// be any width in its first 5 rows, and must keep within 12 of the centre below them.
//
// One thing of the header's is at the centre itself, and no handle at the top centre is clear of it: the header's
// divider, an engraved hairline 3 wide (two columns darker than the header, one lighter) from the top edge down to the
// header's foot, about 58 rows. The tab stands on its top end and covers its first rows (as deep as the tab: 19 of
// them at rest, 23 with the pointer on it); the line goes on below the tab's foot. The checks hold the handle clear of
// the buttons and the words; they say nothing of the divider.
constexpr float kHeaderFreeRows = 5, kHeaderFreeHalf = 12;

}  // namespace player::overlay
