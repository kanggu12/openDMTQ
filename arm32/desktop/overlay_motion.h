// How the overlay's bar comes down out of the game's top edge and goes back up, and what its handle does meanwhile
// (overlay_win32.cpp moves its windows by it): plain arithmetic on a clock's nanoseconds, apart from any window, so that
// a check (settingstest.cpp) can take a motion through its whole way, a turn back midway and Windows' animations
// switched off.
//
// The bar's place is a number from 0 (up: out of sight above the game's top edge) to 1 (down: whole). A way down takes
// kBarDownMs and slows into its place, as a thing that arrives; a way up takes kBarUpMs and gathers speed, as a thing
// that leaves. A way begun from between the two takes the share of that time its length is of the whole way, from where
// the bar is at that moment, so that a turn back midway never jumps. With Windows' animations off a way takes no time.
//
// The handle hands over to the bar in the same motion: it hangs from the bar's foot as the bar comes down, its rail cut
// row by row as the bar's own foot line takes its place, and fades out on the way; on the way up it comes back the same
// way and is whole as the bar goes out of sight.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace player::overlay {

// The whole way down and the whole way up, in milliseconds: down a little longer than up, as a thing that comes is
// watched and one that goes is not waited for (picked from frame strips at a quarter, a half and three quarters).
constexpr int kBarDownMs = 220, kBarUpMs = 170;

// A share of a way's time, held to 0..1.
inline float share(float t) { return std::min(1.0f, std::max(0.0f, t)); }

// The way down's pace: quick at first, slowing into its place (a cubic ease out). 0 at 0, 1 at 1, never back.
inline float ease_down(float t) {
    // What is left of the time, cubed: the last of the way goes slowest.
    const float left = 1.0f - share(t);
    return 1.0f - left * left * left;
}

// The way up's pace: slow at first, gathering speed (a quadratic ease in: gentler than the way down's cubic, so that
// the bar is seen to set out at once rather than to wait and then be gone). 0 at 0, 1 at 1, never back.
inline float ease_up(float t) {
    const float done = share(t);
    return done * done;
}

// The bar's way between up (0) and down (1): where it set out, where it is headed, when it set out and how long the
// way takes (0: at rest at `to`), on any steady clock's nanoseconds.
struct Slide {
    float from = 0, to = 0;
    std::int64_t began = 0, lasts = 0;

    // Whether it is on its way at `now` (not yet where it is headed).
    bool moving(std::int64_t now) const { return lasts > 0 && now < began + lasts; }

    // Where it is at `now`: its place between 0 and 1.
    float at(std::int64_t now) const {
        // At rest, or past the way's end: where it was headed, exactly.
        if (!moving(now)) return to;
        // Before its start (a clock read a moment earlier): where it set out.
        if (now <= began) return from;
        const float t = static_cast<float>(now - began) / static_cast<float>(lasts);
        // Down slows into its place, up gathers speed; each over the way's own length.
        const float pace = to > from ? ease_down(t) : ease_up(t);
        return from + (to - from) * pace;
    }

    // Headed for `target` (0 or 1) from where it is at `now`. A way already headed there goes on as it is; another
    // starts from the bar's place at this moment and takes the share of the whole way's time that its length is of the
    // whole way. Without `animate` (Windows' animations are off) it is there at once.
    void aim(float target, std::int64_t now, bool animate) {
        const float here = at(now);
        // Headed there already, or there: nothing changes (a way under way keeps its own pace).
        if (target == to && (moving(now) || here == target)) return;
        from = here;
        to = target;
        began = now;
        // The way's length, and the time the whole of such a way takes.
        const float way = std::fabs(target - here);
        const int whole = target > here ? kBarDownMs : kBarUpMs;
        lasts = animate ? static_cast<std::int64_t>(std::llround(static_cast<double>(whole) * 1e6 * static_cast<double>(way))) : 0;
    }

    // At rest at `place` from now on, whatever it was doing (the bar hidden at once: a minimised window).
    void rest(float place) {
        from = to = place;
        began = lasts = 0;
    }
};

// The rows of the bar in sight at `place`, of its `height` rows: whole rows, none at 0 and all of them at 1.
inline int bar_rows(float place, int height) {
    return std::min(height, std::max(0, static_cast<int>(std::lround(share(place) * static_cast<float>(height)))));
}

// The handle's share of its own opacity while the bar is at `place`: whole while the bar is out of sight, fading
// evenly as the bar comes down and gone when the bar is whole, so that it is seen going down with the bar's foot; the
// same on the way back up.
inline float handle_opacity(float place) { return 1.0f - share(place); }

// Where the handle hangs while `rows` of the bar are in sight: `down` rows below the game's top edge (on the bar's
// foot), with the top `cut` rows of its picture left out. Its picture's first `lip` rows are its rail, the line along
// the game's top edge, which the bar's own foot line takes the place of as the bar comes out: cut row by row.
struct Hang {
    int down = 0, cut = 0;
};
inline Hang handle_hang(int rows, int lip) { return Hang{std::max(0, rows), std::min(std::max(0, rows), std::max(0, lip))}; }

// How much lower than its picture's own place a piece at the game's top (the notice, a counter in a top corner) is
// shown while `rows` of the bar are in sight: by those rows, less the `room` the bar took where its place was worked
// out (none for a picture made while the bar was up, the bar's height for one made while it was down). A picture
// made for the bar down stands, with the bar down, exactly where one made for no bar stands lowered by the whole bar:
// when the bar settles and the piece's picture is made again for its new place, nothing on the screen moves.
inline int piece_down(int rows, int room) { return rows - room; }

}  // namespace player::overlay
