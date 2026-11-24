// How large the player for Windows draws what it lays over the game (overlay_win32.cpp), the smallest game area its
// window holds (window_win32.cpp), and the size of the handle at the game's top centre, which has a scale of its own:
// plain arithmetic, apart from any window, so that a check (settingstest.cpp) can take it through Windows' scales and
// the game's sizes.
//
// The game lays itself out for 720 lines and grows with its area, whatever Windows' scale: its words and buttons are
// 1.5 times their 720-line size at 1080 lines and 3 times at 4K. The overlay is drawn at the game's own scale, so that
// in a small window it is as small as the game's own words, and on a display at 150 % it covers no more of the game
// than at 100 %. In a very small window its buttons would get too small to hit: it is never drawn below half its
// 720-line size at Windows' scale, where the bar's 40-pixel buttons are 20 of Windows' own pixels. The pointer keeps
// Windows' own size. The game stretches its layout to its area's shape (wider than tall at 21:9, narrower at 4:3): the
// handle and the frame counter, which sit on its own buttons' corners and are never pressed, keep within the narrower
// of its two scales.
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
// exactly, whatever Windows' scale. That is the smaller of the two the game stretches its 1280 by 720 layout by
// (measured on its frames at 4:3, 16:10, 16:9 and 21:9; the frame counter's part below): its height over 720 in an area
// of 16:9 or wider, where the header's middle stays at the centre, and its width over 1280 in a narrower one, where the
// header's buttons are narrower than the height alone says. The handle then keeps within the game's own header in a
// window of any size and shape, and what it clears at 1280x720 it clears everywhere.
inline float handle_scale_for(int area_w, int area_h) {
    return std::min(static_cast<float>(area_w) / kGameWide, static_cast<float>(area_h) / kGameLines);
}

// ---- the question before quitting

// The question's card at 720 lines: 520 wide; its title 36 from its top and 28 high, the game's green line at 74. Mid-song
// a line of words about the song's record 12 under the green line (86, 20 high); the buttons 34 under what is above them,
// 48 high, and 40 under the buttons. Asked in the menus no song's record is at stake: no line of words, the buttons 34
// under the green line, the card shorter by the line's row and the gap above it (32).
struct AskRows {
    float card_h, text_top, text_h, buttons_top;
};
constexpr float kAskWide = 520, kAskTitleTop = 36, kAskTitleTall = 28, kAskGameLine = 74, kAskTextGap = 12, kAskTextTall = 20, kAskButtonsGap = 34,
                kAskButtonTall = 48, kAskFoot = 40;
constexpr AskRows ask_rows(bool song) {
    // The line of words under the game's line, mid-song only; none in the menus (no height, where it would start).
    const float text_top = song ? kAskGameLine + kAskTextGap : kAskGameLine, text_h = song ? kAskTextTall : 0;
    // The buttons under the line of words (or the game's line), and the card's foot under them.
    const float buttons_top = text_top + text_h + kAskButtonsGap;
    return AskRows{buttons_top + kAskButtonTall + kAskFoot, text_top, text_h, buttons_top};
}

// Whether the question is asked mid-song, from keyboard play's word (1 a song going on, from its first frame to its end;
// 0 none; -1 not known, keyboard play not hooked): only a song known to go on has a record that quitting would lose.
constexpr bool ask_mid_song(int song) { return song == 1; }

// ---- the bar

// The bar at 720 lines: 74 high (the game's own X at the top right of its song and music screens reaches row 70: the
// bar covers it whole), its three buttons 40 square and 10 apart, centred in its height, the X at its right end; the
// OpenDMTQ wordmark at its left end. Both ends are kBarEnds in, the wordmark's from the bar's left and the X's from its
// right, so that the bar's two ends match, as the launcher's header keeps its own two sides.
constexpr float kBarTall = 74, kChipSize = 40, kChipGap = 10, kBarEnds = 22;

// The left edge of a button on a bar `bar_w` pixels wide at the overlay's `scale` (0 the X, at the right end; 1 full
// screen, left of it; 2 minimise, left of that), each length rounded to whole pixels as the overlay rounds them.
inline int chip_left(int which, int bar_w, float scale) {
    // The button's size, the gap between two and the bar's end, each whole.
    const int size = static_cast<int>(std::lround(kChipSize * scale)), gap = static_cast<int>(std::lround(kChipGap * scale));
    const int end = static_cast<int>(std::lround(kBarEnds * scale));
    return bar_w - end - size - which * (size + gap);
}

// The wordmark's left edge at the overlay's `scale`, as GDI+ draws it (on a whole pixel where its picture is drawn at
// its own size).
inline float wordmark_left(float scale) { return kBarEnds * scale; }

// ---- the frame counter

// The game stretches its 1280 by 720 layout over its area: across by its width over 1280, down by its height over 720
// (measured on its frames at 4:3, 16:10, 16:9 and 21:9: its pause button, its X and its result's buttons are as wide as
// the width says and as tall as the height says, so at 21:9 they are wider than tall and at 4:3 narrower). The
// overlay's scale is the height's, which keeps the bar as tall as the game's top row it covers in every shape. The
// frame counter, which is never pressed and sits on the game's own corner, is drawn at the smaller of the two, as the
// handle is: in an area narrower than 16:9 it is no wider beside the game's buttons there than at 16:9 (at 1920x1200 at
// 1.5, not 1.67, and at 1024x768 at 0.8, not 1.07), and at 16:9 and wider it is at the overlay's own scale. Never below
// the overlay's floor, half of Windows' scale, so that its words stay as legible as the rest of the overlay's in a
// small window.
inline float counter_scale_for(int area_w, int area_h, float dpi) {
    // The game's narrower scale, at least the floor.
    return std::max(handle_scale_for(area_w, area_h), kLeastScale * dpi);
}

// The right edge of the game's pause button in a song, at 720 lines: the button spans 13 to 72 from the left, measured
// on the game's frames.
constexpr float kPauseRight = 73;

// The pause button's right edge in an area of area_w by area_h: at the game's own scale, the narrower of its width over
// 1280 and its height over 720 (73 at 1280x720, 109.5 at 1920x1080 and 1920x1200 and 2520x1080, 58.4 at 1024x768). The
// game lays its screens out at that one scale in every shape once it knows its size (game_screen.h); before 0.11 a
// window resized after the start left the game stretched across, its button 143.7 wide at 2520x1080.
inline float pause_right(int area_w, int area_h) { return kPauseRight * handle_scale_for(area_w, area_h); }

// ---- the menus' header, which the notice and the frame counter stand clear of

// The menus' header at 720 lines, at the game's narrower scale (handle_scale_for): the row across the top of the music
// list and the result (the player's level badge and name, the equipped items, RANK, Q and MAX with the shop's +) and the
// downloads' own row (its title and its X), to the foot of the header's slanted edge: its buttons end at row 78, its edge
// at 100, measured on the game's frames at 16:9, 21:9 and 4:3.
constexpr float kMenusHeader = 100;

// The top of a piece that stands under the menus' header (the frame counter at the right, the notice in the middle): 8
// (`inset`) under the header, at the game's scale, or under the bar's whole height (`bar`, at the overlay's own),
// whichever is lower, so that it stands on none of the header's buttons and words and the bar never reaches it: it stays
// where it is while the bar comes and goes.
inline int under_header(int area_w, int area_h, int inset, int bar) {
    const int header = static_cast<int>(std::lround(kMenusHeader * handle_scale_for(area_w, area_h)));
    return std::max(header, bar) + inset;
}

// The room the frame counter keeps from the area's right edge where it stands under the menus' header: 16 at 720 lines,
// at the counter's own scale, so that it keeps clear of the next page's cards the music list and the downloads show at
// their right edge (from 12 in at 16:9) as of their grid's last column (to 125 in).
constexpr float kMenusRight = 16;

// Where the counter's glass goes, chip_w by chip_h, for its corner (1 top left, 2 top right, 3 bottom left, 4 bottom right)
// in an area of area_w by area_h; `inset` is 8 at 720 lines and `right` kMenusRight, both at the counter's own scale.
// In a song (`song`): in its corner, 8 in from the area's edges, at the left `inset` right of the game's pause button and
// of the column under it (its life gauge, FEVER, score, rate and combo), so that it covers nothing a song uses; at the top
// left below `top_room` (the bar's room while it is down). At the top right of a song, and where the player cannot tell
// a song from the menus (keyboard play off), whatever its corner, under the menus' header at the right (under_header,
// `bar` the bar's whole height): clear of the Q and MAX a song's own pause screen shows at its top right, and of the
// header and the buttons of the music list, the downloads, a song's page and its options, the rankings before a song,
// the result and the loading screens, measured on their frames in each shape. In the menus it waits
// (counter_has_menus_place): ALBUM's FAVORITE tab ends under that place too.
struct CounterAt {
    int x, y;
};
inline CounterAt counter_at(int corner, int area_w, int area_h, int inset, int chip_w, int chip_h, int top_room, bool song = true, int bar = 0,
                            int right = 0) {
    // A song's top right, and where the player cannot tell a song from the menus (the menus have it wait): under the
    // menus' header at the right, as far in as the next page's cards need.
    if (!song || corner == 2) return CounterAt{area_w - std::max(inset, right) - chip_w, under_header(area_w, area_h, inset, bar)};
    // In a song: which sides of the area the corner touches.
    const bool at_right = corner == 4, bottom = corner == 3 || corner == 4;
    // The left: beside the pause button's right edge, rounded to a whole pixel (the column under it is no wider).
    const int left = static_cast<int>(std::lround(pause_right(area_w, area_h))) + inset;
    return CounterAt{at_right ? area_w - inset - chip_w : left, bottom ? area_h - inset - chip_h : inset + top_room};
}

// Whether the counter in `corner` moves with the bar's foot as the bar comes and goes: only at the top left of a song,
// where it stands 8 under the top (under the menus' header the bar never reaches it).
inline bool counter_under_bar(int corner, bool song) { return song && corner == 1; }

// Whether the counter has a place in the menus in an area of area_w by area_h at Windows' scale `dpi`: in none. Every
// place near a corner of the menu screens holds something of the game's own on one screen or another (the player's name
// and level, the music list's tabs and grid button, a song's title and score, SELECT MUSIC, DOWNLOAD), and the one place
// under the header at the right that the music list, the downloads, a song's page, the result and the rankings leave
// free has ALBUM's FAVORITE tab under it: the tab's slanted end reaches 1187 at 720 lines where the counter's glass starts
// at 1174 (and 891 at 4:3, where it starts at 878), and the shop's panel's top line runs 6 under its foot, measured on the
// game's frames at 16:9 and 4:3. Four pixels narrower it still lies on the tab; one narrow enough for the room between
// the tab and the music list's next page at the right (80 at 720 lines, 64 within the counter's insets) would be smaller
// in the menus than in a song, and where the counter is drawn at its least already (960x720 at 150 %: 70 wide, its small
// words at their least) no smaller one stays legible. So it waits in the menus in every shape, as it did in a window wider
// than 16:9 and in the smallest windows, and shows in each song. The parameters stay for the checks, which hold every
// place this gives to the game's measured menu screens.
inline bool counter_has_menus_place(int area_w, int area_h, float dpi) {
    // No shape and no scale gives it one (above): the frame counter waits in the menus and shows in a song.
    (void)area_w;
    (void)area_h;
    (void)dpi;
    return false;
}

// The notice's glass's top: in a song 16 under the top (`sixteen`, at the overlay's scale) and lower by the bar's room while
// it is down (`top_room`), its card centred over the play field, clear of the pause button and its column at the left;
// in the menus (and where the player cannot tell), 8 under the menus' header (under_header), as the game's own popups
// stand clear of it, so that it lies on none of the header's buttons and words, and never moves with the bar.
inline int notice_top(int area_w, int area_h, int sixteen, int inset, int top_room, int bar, bool song) {
    return song ? sixteen + top_room : under_header(area_w, area_h, inset, bar);
}

// The left edge, at 720 lines, of the Q and MAX a song's own pause screen shows at its top right (to row 62), from the
// area's right edge (measured on the game's frames: 891 of 1280, 389 in from the right): a notice in a song keeps clear of
// it on both of its sides as it is centred.
constexpr float kPauseBoxFromRight = 389;

// The widest a notice's card may be in a song, centred in the room it has across (`room`: the area's width, or the room
// left of the sound panel while that is open, from the area's left edge), `gap` clear of the pause button and the column
// under it at the area's left (pause_right) and of the pause screen's Q and MAX at its right (kPauseBoxFromRight in from
// the area's right edge, at the game's own scale): twice the nearer of the two from the room's middle. With the panel
// closed the Q and MAX are the nearer, as before (1280 - 2 x 397 at 720 lines); with it open the room is narrower and its
// middle further left, and the pause button's column is (at 1280x720, 742 for a room of 904; it was the room less 2 x 397,
// which left the words their least, 160, as if the Q and MAX stood at the panel's edge). Never below 0.
inline float notice_song_most(int room, int area_w, int area_h, float gap) {
    // The game's own scale for its pause button and its Q and MAX: the narrower of its two (pause_right's).
    const float k = handle_scale_for(area_w, area_h);
    const float middle = static_cast<float>(room) / 2;
    // From the room's middle to the pause button's column, and to the Q and MAX, each less the gap.
    const float to_left = middle - (pause_right(area_w, area_h) + gap);
    const float to_right = (static_cast<float>(area_w) - kPauseBoxFromRight * k - gap) - middle;
    return std::max(0.0f, 2 * std::min(to_left, to_right));
}

// ---- the handle's tab

// The handle's tab at 720 lines: 25.6 wide where it hangs from the game's top edge, its sides leaning in 0.268 a pixel
// down as the game's own tabs' do (15 degrees), 18.5 high and 23 with the pointer on it; the line it hangs from (its
// rail) 2 high with a line of shade under it, 88 wide (112 with the pointer on it). As large as the game's header
// leaves room for (below).
constexpr float kTabTop = 25.6f, kTabTall = 18.5f, kTabTallLit = 23, kTabLean = 0.268f;
constexpr float kRailTall = 2, kRailShade = 1, kRailWide = 88, kRailWideLit = 112;

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

// ---- the handle's reach

// Where the pointer lights the handle and, resting there, brings the bar down (the game's very top edge brings it across
// the whole width besides: overlay_win32.cpp). It keeps to the same room as the handle's picture, at the handle's own
// scale, which is the scale of the game's header: in the header's rows above its buttons, along the rail as wide as the
// rail at rest; below them, within the room the header's buttons and words leave beside the centre, down to the foot of
// the tab with the pointer on it. So the tab as drawn hangs inside it at rest and lit, and no place in it is on one of
// the header's buttons or words at any size or shape; the divider at the very centre is under it, as it is under the tab.
// The pointer's place is a point at whole pixels of the game's area, x from its left, y from its top, as Windows and the
// game's own buttons take it.
inline bool in_handle_reach(int x, int y, int area_w, int area_h) {
    // The handle's scale: the game's header's at this size and shape, with no floor.
    const float k = handle_scale_for(area_w, area_h);
    // How far the place is from the area's middle across, either way.
    const float across = std::fabs(static_cast<float>(x) - static_cast<float>(area_w) / 2);
    // Above the game's area: none of it.
    if (y < 0) return false;
    // In the header's rows above its buttons: as wide as the rail at rest.
    if (static_cast<float>(y) < kHeaderFreeRows * k) return across <= kRailWide / 2 * k;
    // Below them: within the room beside the centre, down to the lit tab's foot.
    return static_cast<float>(y) < kTabTallLit * k && across <= kHeaderFreeHalf * k;
}

}  // namespace player::overlay
