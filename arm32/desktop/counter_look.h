// The frame counter's look over the game (overlay_win32.cpp draws it), as plain arithmetic apart from any window, so
// that a check (settingstest.cpp) can take it through its numbers and sizes: one more of the overlay's cards of glass,
// its words in the launcher's own forms for a figure. The frames a second as a figure in the launcher's wide face (DMTQ
// Wide, as its last game's length and its records' scores are set), with their unit after them on the figure's
// baseline, muted, as the launcher sets a figure's unit; the frame time under them, small and muted, as a figure's
// second line. The two numbers stand right-aligned in one column and their units in the next, each digit in a cell as
// wide as the face's widest (the faces' own tabular figures, which GDI+ does not set): nothing moves but the digits as
// the numbers change. The figure is lime while the frames keep the display's rate (the game's lime marks what is lit),
// white otherwise, changing only once three seconds' looks agree; the rest is the overlay's quiet grey. Its window is
// shown whole, as every other piece of the overlay: its words keep their contrast over any frame of the game, which the
// glass's tint under them sees to.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <string>

namespace player::overlay {

// ---- its sizes at 720 lines (times the counter's own scale, overlay_scale.h's counter_scale_for)

// The figure's size (DMTQ Wide, the launcher's figures' face) and the small words' (Pretendard at the overlay's small
// words' 11: the LIVE tag's, the equaliser's band names'), in its SemiBold, as the overlay sets its values: at 11 a
// regular stroke is thinner than a pixel and shows far darker than its grey (the least of the regular strokes' middles
// 0.27 in relative luminance, the semibold's 0.46, against the grey's own 0.52, measured over the game's frames).
constexpr float kCounterFigure = 18, kCounterSmall = 11;
// The least size of the small words, in the window's pixels, whatever the counter's scale: where the counter is drawn at
// less than its size at 720 lines (a small window: three quarters of it, its small words 8.25), their strokes fall under
// a pixel and the frame time's full stop, a dot of about one, under 4.5 to 1 however dark the glass under it (2.4,
// measured). At this size they keep it; the figure and the room round the words keep the counter's scale.
constexpr float kCounterSmallLeast = 10;
// The small words' size at the counter's scale `k`, in pixels: 11 at 720 lines times the scale, never under the least.
inline float counter_small_px(float k) { return std::max(kCounterSmall * k, kCounterSmallLeast); }
// The heights of the faces' digits as a share of their size, from their files: DMTQ Wide's capitals and digits 688 of
// its 1000 units, Pretendard's (SemiBold as Regular) 1448 of its 2048. The words stand on the middle of the glass by
// these (their ink), not by the faces' line boxes, which hold room above and below the digits.
constexpr float kFigureCap = 0.688f, kSmallCap = 1448.0f / 2048.0f;
// The room inside the glass: 10 at its sides (the counter's before); the unit 6 after its number (the launcher's step
// between a figure and its unit); 5 from the figure's baseline to the top of the frame time's digits. The glass is as
// tall as its two rows' ink and 8 above and below, to a whole pixel, the rows on its middle.
constexpr float kCounterPadX = 10, kCounterUnitGap = 6, kCounterRowGap = 5, kCounterPadY = 8;
// The overlay's cards' corners (the notice's, the sound panel's, the question's: the game's own small ones).
constexpr float kCounterRound = 6;
// The most the glass may light the counter's words from under them (relative luminance), for the overlay's tint to
// deepen to: its small words are 11 at 720 lines, their strokes about a pixel, and show darker than their grey (0.46 at
// the least), so that at the 0.074 the overlay holds its larger grey words to they would fall to 4.1. At 0.045 they
// keep 5 to 1 over any frame of the game at 720 lines and more (the tint keeps the glass under them that dark whatever
// is behind, its grain at most 0.0505), and its digits keep 4.5 in the smallest windows, where the counter is drawn at
// three quarters of that.
constexpr float kCounterUnder = 0.045f;
// Its window's opacity: whole, as the overlay's other pieces (it was 62 %: its words then fell to 1.1 to 3.1 to 1 over
// light frames of the game, measured, and read washed out).
constexpr int kCounterOpacity = 255;

// What the faces measure at the size they are drawn at (pixels), which the layout takes: the widest digit of each face
// (a digit's cell), the small face's full stop, and the widest of the units it sets ("FPS", "ms").
struct CounterFaces {
    float figure_cell = 0, small_cell = 0, small_point = 0, unit_w = 0;
};

// Where everything of the counter stands in its glass, in pixels from the glass's top left at scale `k`: the glass's
// size (whole pixels), the right edge of the numbers' column and the left edge of the units', and the two rows'
// baselines. The numbers' column holds three of the figure's digits: the frames a second are 999 at most (frame_rate's
// reading, the counter's room), and the frame time, set to a tenth or whole, four of the small face's at most.
struct CounterLayout {
    float w = 0, h = 0;
    float numbers_right = 0, units_left = 0;
    float figure_base = 0, small_base = 0;
};

// The layout for faces measured at kCounterFigure * k and counter_small_px(k).
inline CounterLayout counter_layout(const CounterFaces& f, float k) {
    CounterLayout l;
    // Three of the figure's cells make the numbers' column, or four of the small face's where those are wider (the frame
    // time's 1000 at the small words' least size in the smallest windows); the units' column is as wide as its widest
    // unit.
    l.numbers_right = kCounterPadX * k + std::max(f.figure_cell * 3, f.small_cell * 4);
    l.units_left = l.numbers_right + kCounterUnitGap * k;
    l.w = std::ceil(l.units_left + f.unit_w + kCounterPadX * k);
    // The two rows' ink, and the glass that much and its room above and below, to a whole pixel, the ink on its middle;
    // the small row's at its own size, its least in a small window.
    const float figure_cap = kCounterFigure * k * kFigureCap, small_cap = counter_small_px(k) * kSmallCap;
    const float ink = figure_cap + kCounterRowGap * k + small_cap;
    l.h = std::round(ink + 2 * kCounterPadY * k);
    const float top = (l.h - ink) / 2;
    l.figure_base = top + figure_cap;
    l.small_base = l.figure_base + kCounterRowGap * k + small_cap;
    return l;
}

// Whether one look's frames a second keep the display's rate `hz` (its refreshes a second, 0 when not known): every
// refresh with a frame of its own, give or take the second's own rounding and a refresh or two in a hundred (at 240 Hz
// from 235, at 60 Hz from 59). More frames than refreshes, with VSync off, keep it too. Never before a first measure
// (below 0), at 0, or with the display's rate not known. The figure is lit by CounterLight below, over several looks.
inline bool counter_lit(int fps, float hz) {
    if (fps <= 0 || hz < 1) return false;
    const int rate = static_cast<int>(std::lround(hz));
    return fps >= rate - std::max(1, static_cast<int>(std::lround(rate * 0.02f)));
}

// Whether one look's frames a second fall clearly below the display's rate: by more than one in twenty, and by three
// frames at least (at 240 Hz under 228, at 144 under 137, at 60 under 57, at 30 under 27), well past what the second's
// rounding and a refresh or two missed make. No reading, or no rate known, counts as below it.
inline bool counter_clearly_short(int fps, float hz) {
    if (fps <= 0 || hz < 1) return true;
    const int rate = static_cast<int>(std::lround(hz));
    return fps < rate - std::max(3, static_cast<int>(std::lround(rate * 0.05f)));
}

// The looks in a row (the counter looks twice a second, each look the last second's mean) the frames must keep the
// display's rate for the figure to light, and fall short of it for it to go out: three seconds either way. With frames
// that keep the rate only now and then (a refresh missed at random, the mean at the edge: 234 or 235 at 240 Hz, 28.8 at
// 30 Hz), two looks changed the colour every three seconds or so, measured and simulated (20 a minute); six change it
// every twelve to twenty seconds there (3 to 5 a minute), and it settles on the colour that holds most of the time.
constexpr int kCounterLitLooks = 6;

// The figure's light (lime) over the counter's looks, one after another: lit once the frames have kept the display's
// rate for kCounterLitLooks looks in a row; out again once they have fallen short of it for as many, or at once when a
// look falls clearly below it (a heavy scene shows at the next look). A rate at the edge of the display's (234 and 235
// at 240 Hz, 28 and 29 at 30 Hz) so keeps one colour instead of changing it at every look, twice a second, and a rate
// that settles a little under the display's (232 at 240 Hz) does not stay lime. No reading (not measured yet, a second
// without a frame, the counter hidden) or no rate known puts it out and starts the count again.
struct CounterLight {
    bool lit = false;
    // The looks in a row at the display's rate, and short of it.
    int kept = 0, short_of = 0;
    // The next look: its frames a second and the display's rate; whether the figure is lit after it.
    bool look(int fps, float hz) {
        // Nothing to light: out, and every count from the start.
        if (fps <= 0 || hz < 1) {
            *this = CounterLight{};
            return lit;
        }
        if (counter_lit(fps, hz)) {
            // At the rate: lit from the last of the looks in a row it takes.
            short_of = 0;
            if (++kept >= kCounterLitLooks) lit = true;
        } else {
            // Short of it: out after as many looks in a row, or now when clearly below it.
            kept = 0;
            if (++short_of >= kCounterLitLooks || counter_clearly_short(fps, hz)) lit = false;
        }
        return lit;
    }
};

// The frame time as the counter's second row sets its number (its unit is in the units' column): to a tenth of a
// millisecond under 100 ms (4.2, 16.7), whole from there on (333, 1000: a loading screen's few frames a second), so
// that it never takes more than four digits' room; two dashes with no frame time to give (not measured yet, or a
// second with no frame).
inline std::string counter_time(int fps, float ms) {
    if (fps <= 0 || !(ms > 0)) return "--";
    char text[16];
    // Rounded as it shows: 99.96 is 100, set whole.
    if (std::round(ms * 10.0f) < 1000.0f) std::snprintf(text, sizeof text, "%.1f", static_cast<double>(ms));
    else std::snprintf(text, sizeof text, "%.0f", static_cast<double>(ms));
    return text;
}

}  // namespace player::overlay
