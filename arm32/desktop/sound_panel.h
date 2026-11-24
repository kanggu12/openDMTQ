// The in-game sound panel's layout (overlay_win32.cpp draws it and reads the pointer against it): plain arithmetic apart
// from any window, so that a check (settingstest.cpp) can lay it out over every shape and scale of the game's area and
// measure it: within the area, under the bar, its rows apart on one spacing scale, words inside their padding, its
// controls large enough to hit.
//
// The bar's Sound button (a word beside a speaker, left of minimise) opens it: a card of glass under the bar at the
// game's right side, 8 in from the area's right edge and 8 under the bar's foot as the overlay's other cards keep from
// the edges they stand by (nothing of it touches the bar or the window's edge), 360 wide at 720 lines. Its title, the game's green line under it; Master, Music and Effects,
// each a slider of 0 to 100 % with its value; the Equaliser's title and line; its presets as five chips in a row (Flat,
// Bass, Vocal, Treble, Custom), and its three bands, each a slider of -12 to +12 dB with its value. A row's whole height
// across its track takes the pointer, so that a finger needs no aim at the thin track.
#pragma once

#include <algorithm>
#include <cmath>

namespace player::overlay {

// The panel's sizes at 720 lines.
constexpr float kPanelWide = 360;
// Its inside: 20 at the sides, 16 at the top (its title's words sit 4 lower in their row), 20 at the foot. The spacing
// scale every gap in it is on: 4, 8, 12, 16, 20.
constexpr float kPanelSide = 20, kPanelTop = 16, kPanelFoot = 20;
// The title's row (its words 17 high), the line 8 under it, 12 more to the first row; a slider's row 40 high; 16
// between the volumes and the equaliser's title; the chips' row 32 high, 12 under the equaliser's line, 8 to the bands.
constexpr float kTitleRow = 24, kTitleLine = 8, kAfterLine = 12, kSliderRow = 40, kGroupGap = 16, kChipRow = 32, kChipsAfter = 8;
// A slider's label column, the gap to its track, the value's column at the right end.
constexpr float kLabelWide = 92, kLabelGap = 12, kValueWide = 52, kValueGap = 12;
// The chips: five in a row, 8 apart (a step of the spacing scale), each as wide as its word with the same room on both
// sides, the room the row leaves shared out evenly: never less than kChipPad a side (the padding of the scale's 8).
constexpr int kPresets = 5;
constexpr float kChipsGap = 8, kChipPad = 8;
// The presets' words as the overlay draws them on the chips (overlay_win32.cpp's control_name, Pretendard Bold 13), their
// advances at 720 lines as Windows' GDI+ sets them (the face's own), English (Flat, Bass, Vocal, Treble, Custom) then Korean
// (기본, 베이스, 보컬, 트레블, 커스텀): the chips are laid out by these on both of the overlay's threads, with no face at
// hand; glasstest.cpp measures the words as GDI+ sets them there and holds the room beside each to the padding.
constexpr float kChipWords[2][kPresets] = {{22.7f, 29.6f, 34.1f, 38.7f, 48.0f}, {22.5f, 33.7f, 22.5f, 33.7f, 33.7f}};
// The track's height and the thumb's diameter.
constexpr float kTrackTall = 4, kThumb = 16;

// The panel's quiet grey words: each band's corner frequency under its name (11 at 720 lines) and each slider's value at
// its right (13), set in Pretendard SemiBold, the weight the overlay sets its values and its small grey words in (the
// FPS counter's, the notice's second line): a regular stroke at 11 is thinner than a pixel and shows far darker than
// its grey (the band frequencies came to 4.2 to 1 in a 960x540 window, 8.25 pixels, measured over the game's frames).
// Never set under 10 pixels, the counter's least (counter_look.h), however small the panel is drawn.
constexpr float kBandHzSize = 11, kValueSize = 13, kGreyWordsLeast = 10;
// A grey word's size in pixels at the panel's scale `k`: its size at 720 lines times the scale, never under the least.
inline float sound_grey_px(float size, float k) { return std::max(size * k, kGreyWordsLeast); }
// The most the glass may light those words from under them (relative luminance), for the overlay's tint to deepen to over
// a light frame: the counter's bound for its small grey words (counter_look.h's kCounterUnder), under which SemiBold
// strokes of 10 pixels and more (0.46 at the least, measured) keep 5 to 1. At the 0.074 the overlay holds its larger grey
// words to, the values fell to 4.3 over a light song at 1280x720 (their strokes 0.47).
constexpr float kPanelGreyUnder = 0.045f;

// The panel's height at 720 lines: its top, the title, the volumes, the equaliser's title and chips, its bands, its foot.
constexpr float kPanelTall = kPanelTop + kTitleRow + kTitleLine + kAfterLine + 3 * kSliderRow + kGroupGap + kTitleRow + kTitleLine + kAfterLine + kChipRow +
                             kChipsAfter + 3 * kSliderRow + kPanelFoot;

// The Sound button on the bar at 720 lines: 96 wide (a speaker and the word), as tall as the bar's other buttons, 10
// left of minimise.
constexpr float kSoundChipWide = 96;

// The panel's controls: the three volumes, the three bands, the five presets.
enum SoundControl {
    kMaster, kMusic, kEffects, kLow, kMid, kHigh, kChipFlat, kChipBass, kChipVocal, kChipTreble, kChipCustom, kSoundControls, kNoControl = -1
};
inline bool is_slider(int c) { return c >= kMaster && c <= kHigh; }
inline bool is_band(int c) { return c >= kLow && c <= kHigh; }

// A rectangle in the game's area, in pixels (not rounded: the drawing rounds).
struct Box {
    float x = 0, y = 0, w = 0, h = 0;
    bool contains(float px, float py) const { return px >= x && px < x + w && py >= y && py < y + h; }
    float right() const { return x + w; }
    float bottom() const { return y + h; }
};

// Where everything of the panel lies in the game's area, and the scale it is laid out at.
struct SoundLayout {
    float scale = 1;
    Box panel, title, eq_title;
    float title_line = 0, eq_line = 0;
    // Each slider's row, its label, its track (the drawn line) and its value; each chip.
    Box row[6], label[6], track[6], value[6];
    Box chip[kPresets];
};

// The room the panel keeps from the bar's foot, from the area's right edge and from its foot, at 720 lines.
constexpr float kPanelInset = 8;

// The panel's scale: the overlay's, held so that the panel fits under the bar within the area with its insets.
inline float sound_scale(int area_w, int area_h, float overlay_scale, int bar_h) {
    const float room_down = (static_cast<float>(area_h) - static_cast<float>(bar_h)) / (kPanelTall + 2 * kPanelInset);
    const float room_across = static_cast<float>(area_w) / (kPanelWide + 2 * kPanelInset);
    return std::max(0.01f, std::min({overlay_scale, room_down, room_across}));
}

// The layout in an area of area_w by area_h, the bar bar_h high, at the overlay's scale: at the area's right side, its
// insets from the area's right edge and from the bar's foot, on whole pixels; the chips by their words in the panel's
// language (`korean`).
inline SoundLayout sound_layout(int area_w, int area_h, float overlay_scale, int bar_h, bool korean = false) {
    SoundLayout l;
    const float k = sound_scale(area_w, area_h, overlay_scale, bar_h);
    l.scale = k;
    // Its height up to the next whole pixel: the rows inside it, laid out unrounded, never reach into its foot's padding.
    const float w = std::round(kPanelWide * k), h = std::ceil(kPanelTall * k), inset = std::round(kPanelInset * k);
    l.panel = Box{static_cast<float>(area_w) - inset - w, static_cast<float>(bar_h) + inset, w, h};
    const float left = l.panel.x + kPanelSide * k, inner = w - 2 * kPanelSide * k;
    float y = l.panel.y + kPanelTop * k;
    l.title = Box{left, y, inner, kTitleRow * k};
    y += kTitleRow * k;
    l.title_line = y + kTitleLine * k;
    y += (kTitleLine + kAfterLine) * k;
    // A slider's row at y: its label, its track in the middle of its row, its value at the right.
    auto slider = [&](int i, float at) {
        l.row[i] = Box{left, at, inner, kSliderRow * k};
        l.label[i] = Box{left, at, kLabelWide * k, kSliderRow * k};
        l.value[i] = Box{left + inner - kValueWide * k, at, kValueWide * k, kSliderRow * k};
        const float tx = left + (kLabelWide + kLabelGap) * k, tw = l.value[i].x - kValueGap * k - tx;
        l.track[i] = Box{tx, at + (kSliderRow - kTrackTall) / 2 * k, tw, kTrackTall * k};
    };
    for (int i = kMaster; i <= kEffects; ++i) {
        slider(i, y);
        y += kSliderRow * k;
    }
    y += kGroupGap * k;
    l.eq_title = Box{left, y, inner, kTitleRow * k};
    y += kTitleRow * k;
    l.eq_line = y + kTitleLine * k;
    y += (kTitleLine + kAfterLine) * k;
    // The chips across the inside, kChipsGap apart: each its word's width and the same room on both of its sides, the
    // room the row leaves after the words and the gaps shared out evenly, so that each word stands in the middle of its
    // chip with as much room as the others (a long word no closer to its border than a short one).
    const float* words = kChipWords[korean ? 1 : 0];
    float all_words = 0;
    for (int i = 0; i < kPresets; ++i) all_words += words[i] * k;
    const float pad = (inner - (kPresets - 1) * kChipsGap * k - all_words) / (2 * kPresets);
    float x = left;
    for (int i = 0; i < kPresets; ++i) {
        const float w = words[i] * k + 2 * pad;
        l.chip[i] = Box{x, y, w, kChipRow * k};
        x += w + kChipsGap * k;
    }
    y += (kChipRow + kChipsAfter) * k;
    for (int i = kLow; i <= kHigh; ++i) {
        slider(i, y);
        y += kSliderRow * k;
    }
    return l;
}

// The control under a point of the game's area, or kNoControl: a slider by its whole row from its track's start to its
// end (and its thumb's half beyond either end), a chip by its box.
inline int sound_control_at(const SoundLayout& l, float x, float y) {
    for (int i = kMaster; i <= kHigh; ++i) {
        const Box& t = l.track[i];
        const float half = kThumb / 2 * l.scale;
        if (y >= l.row[i].y && y < l.row[i].bottom() && x >= t.x - half && x < t.right() + half) return i;
    }
    for (int i = 0; i < kPresets; ++i) {
        if (l.chip[i].contains(x, y)) return kChipFlat + i;
    }
    return kNoControl;
}

// A slider's range: 0 to 100 % for the volumes, -12 to +12 dB for the bands.
inline int slider_least(int c) { return is_band(c) ? -12 : 0; }
inline int slider_most(int c) { return is_band(c) ? 12 : 100; }

// The value a slider takes at x across its track: whole steps, held to its range.
inline int slider_value_at(const SoundLayout& l, int c, float x) {
    const Box& t = l.track[c];
    const float share = t.w > 0 ? std::clamp((x - t.x) / t.w, 0.0f, 1.0f) : 0.0f;
    const int lo = slider_least(c), hi = slider_most(c);
    return lo + static_cast<int>(std::lround(share * static_cast<float>(hi - lo)));
}

// Where a slider's thumb's middle is for a value.
inline float slider_x(const SoundLayout& l, int c, int value) {
    const Box& t = l.track[c];
    const int lo = slider_least(c), hi = slider_most(c);
    return t.x + t.w * static_cast<float>(std::clamp(value, lo, hi) - lo) / static_cast<float>(hi - lo);
}

}  // namespace player::overlay
