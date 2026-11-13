// The player's PC settings file (settings.cpp), as the PC client writes it: each key read, a value it cannot read or a
// key it does not know leaving the default, a volume out of range held to 0 to 100, MSAA of earlier launchers read as
// CMAA 2, notes, Windows' line ends, a byte order mark and capitals taken in their stride, no file at all the
// defaults. Then the numbers of the frame counter that one of the settings shows (frame_rate.cpp): its looks at the
// count of frames through the game's start, a stretch with no frame, frames again and a hold. Then the size the overlay
// over the game is drawn at and the smallest game area the window holds (overlay_scale.h), over Windows' scales and the
// game's sizes, with the size of the overlay's handle and the reach a resting pointer brings the bar from, which keep
// clear of the game's buttons and words in its header at every size. Then the overlay's bar on its way down and up
// (overlay_motion.h): its pace, a turn back midway, Windows' animations off, the rows of it in sight, and the handle and
// the pieces at the top that move with it. And the text the keyboard types into the game's soft keyboard
// (typed_text.h): the text the game opens it with taken as selected. And keyboard play's rules (keyboard_play.h): the
// lane keys' names and places, each mode's lanes from the settings file (one or two keys a lane, a value it cannot read
// keeping the default), the lane a key plays, a press, its repeats and every key let go, when the lane keys play at all,
// and which request of the game's saves a play. Prints ALL CHECKS PASSED when every check held.
#include "frame_rate.h"
#include "keyboard_play.h"
#include "overlay_motion.h"
#include "overlay_scale.h"
#include "player.h"
#include "typed_text.h"

#include <cmath>

#include <cstdio>
#include <string>

namespace {

int g_checks = 0, g_failed = 0;

// One check, said only when it fails.
void check(bool ok, const char* what) {
    ++g_checks;
    if (!ok) {
        ++g_failed;
        std::printf("FAIL %s\n", what);
    }
}

// The settings read from `text`, from the defaults: each case starts from a fresh start's settings.
const player::Settings& read(const std::string& path, const std::string& text) {
    player::settings() = player::Settings{};
    if (std::FILE* f = std::fopen(path.c_str(), "wb")) {
        std::fwrite(text.data(), 1, text.size(), f);
        std::fclose(f);
    }
    player::load_settings(path);
    return player::settings();
}

// A game showing frames at a steady rate from a moment on, as the count of frames shown says it: frames at the display's
// own moments, `period` nanoseconds apart from `from` (the first at `from`), none before `from` or within a stretch
// left out, and a look at a moment seeing every frame up to it.
struct Frames {
    long long from = 0, period = 0;
    // The stretches with no frame (start and end, nanoseconds), each within the run.
    struct Gap {
        long long start, end;
    };
    Gap gaps[4] = {};
    int gap_count = 0;
    // Whether a frame at `t` was shown: past the start and in no stretch left out.
    bool shown(long long t) const {
        if (t < from) return false;
        for (int i = 0; i < gap_count; ++i) {
            if (t >= gaps[i].start && t < gaps[i].end) return false;
        }
        return true;
    }
    // The count and the last frame's moment at `t`: each frame up to it, one at a time (a few thousand at most here).
    player::overlay::FrameCount at(long long t) const {
        player::overlay::FrameCount c;
        for (long long f = from; f <= t; f += period) {
            if (!shown(f)) continue;
            ++c.count;
            c.ns = f;
        }
        return c;
    }
};

// Milliseconds as the count's nanoseconds.
constexpr long long ms(long long n) { return n * 1000000LL; }

// The frame counter through a run: what it shows at each look, against what the frames give.
void frame_counter_checks() {
    using player::overlay::FrameRate;
    using player::overlay::Reading;
    // 60 frames a second from 2 s on (the game's black start before that), with no frame from 10 s to 12 s (a
    // loading screen); looks every 500 ms as the counter's own, every 100 ms while it waits.
    Frames sixty;
    sixty.from = ms(2000);
    sixty.period = 16666667;
    sixty.gaps[sixty.gap_count++] = Frames::Gap{ms(10000), ms(12000)};
    FrameRate counter;
    auto look = [&](FrameRate& c, const Frames& f, long long t, bool held = false) { return c.look(f.at(t), t, held); };
    Reading r = look(counter, sixty, ms(500));
    check(!r.shown, "the counter is hidden before the game's first frame");
    r = look(counter, sixty, ms(1500));
    check(!r.shown && counter.waiting(), "and still hidden while no frame has come, looking soon again");
    // The first frame: a measure starts from it, still hidden until a second frame gives a rate.
    r = look(counter, sixty, ms(2005));
    check(!r.shown && counter.waiting(), "the first frame starts a measure, hidden until a second one");
    r = look(counter, sixty, ms(2105));
    check(r.shown && r.fps == 60 && r.ms > 16.6f && r.ms < 16.7f, "the next look reads 60 and 16.7 ms, from the first frame");
    check(!counter.waiting(), "measured: the counter looks at its own pace again");
    // Steady: 60 at every look, the rate over the last second.
    bool steady = true;
    for (long long t = ms(2605); t < ms(10000); t += ms(500)) steady = steady && look(counter, sixty, t).fps == 60;
    check(steady, "60 at every look while the game shows 60 frames a second");
    // The loading screen: no frame for 2 s. Within its first second the counter reads the last second's frames (not 0);
    // a whole second without a frame reads 0.
    r = look(counter, sixty, ms(10105));
    check(r.shown && r.fps > 30, "a look just into the stretch reads the last second's frames");
    r = look(counter, sixty, ms(10605));
    check(r.shown && r.fps >= 22 && r.fps <= 26,
          "0.6 s without a frame is no 0, and the last second's 24 frames read over the whole second, not at their own pace");
    r = look(counter, sixty, ms(11105));
    check(r.shown && r.fps == 0 && r.ms == 0, "a whole second without a frame reads 0 with no frame time");
    r = look(counter, sixty, ms(11605));
    check(r.shown && r.fps == 0, "and 0 again while the stretch goes on");
    // Frames again from 12 s: never dashes and never 0 while they come; the frames of the last second over their time,
    // so the number climbs back to 60 within a second.
    r = look(counter, sixty, ms(12105));
    check(r.shown && r.fps > 0, "the first look after frames come again reads a rate, not 0 and not dashes");
    r = look(counter, sixty, ms(12605));
    check(r.shown && r.fps > 0, "and the next one too");
    r = look(counter, sixty, ms(13105));
    check(r.shown && r.fps == 60, "a second after frames come again: 60");
    // A loading screen that shows a frame every 300 ms: about 3 at every look, never 0 in turn with it.
    Frames sparse;
    sparse.from = ms(1000);
    sparse.period = ms(300);
    FrameRate slow;
    look(slow, sparse, ms(1001));
    bool few = true;
    int seen = 0;
    for (long long t = ms(1101); t < ms(9000); t += slow.waiting() ? ms(100) : ms(500)) {
        r = look(slow, sparse, t);
        if (!r.shown) continue;
        ++seen;
        few = few && r.fps >= 3 && r.fps <= 4;
    }
    check(seen > 10 && few, "a frame every 300 ms reads 3 or 4 at every look, never 0");
    // Held still for the question from 20.1 s to 25.2 s: hidden at once. The game takes a moment to stop (its pause
    // goes through its own thread: frames until 20.2 s) and to start again (from 25.3 s); the frames it shows after the
    // hold began count for nothing. After the hold, hidden until two frames give a rate, which is the true one.
    Frames held = sixty;
    held.gaps[held.gap_count++] = Frames::Gap{ms(20200), ms(25300)};
    for (long long t = ms(13605); t < ms(20105); t += ms(500)) look(counter, held, t);
    r = look(counter, held, ms(20105), true);
    check(!r.shown, "the counter hides while the game is held");
    r = look(counter, held, ms(25105), true);
    check(!r.shown, "and stays hidden through the hold");
    r = look(counter, held, ms(25200));
    check(!r.shown && counter.waiting(), "let go with no frame yet: still hidden, waiting for one");
    r = look(counter, held, ms(25305));
    check(!r.shown, "the first frame after the hold starts a measure");
    r = look(counter, held, ms(25405));
    check(r.shown && r.fps == 60, "and the next look reads 60: the hold is no long frame");
    r = look(counter, held, ms(25905));
    check(r.shown && r.fps == 60, "nor counts in the second after it");
    // 144 frames a second, looked at every 500 ms, and a run so quick its rate is capped at three digits.
    Frames fast;
    fast.from = ms(1000);
    fast.period = 6944444;
    FrameRate quick;
    look(quick, fast, ms(1001));
    look(quick, fast, ms(1101));
    look(quick, fast, ms(1601));
    r = look(quick, fast, ms(2101));
    check(r.fps == 144 && r.ms > 6.9f && r.ms < 7.0f, "144 frames a second read as 144 and 6.9 ms");
    Frames faster;
    faster.from = ms(1000);
    faster.period = 500000;
    FrameRate capped;
    look(capped, faster, ms(1001));
    r = look(capped, faster, ms(1101));
    check(r.fps == 999, "2000 frames a second read as 999, the counter's room");
    // Frames that stop just after a look: the next look reads the second's few frames over the whole second.
    Frames stop;
    stop.from = ms(1000);
    stop.period = 16666667;
    stop.gaps[stop.gap_count++] = Frames::Gap{ms(5020), ms(60000)};
    FrameRate stopped;
    look(stopped, stop, ms(1001));
    look(stopped, stop, ms(1101));
    for (long long t = ms(1501); t <= ms(5001); t += ms(500)) look(stopped, stop, t);
    r = look(stopped, stop, ms(5501));
    check(r.fps >= 28 && r.fps <= 34, "frames that stop 20 ms after a look: the next look reads the second's 31 frames over the second, not the 60 they came at");
    r = look(stopped, stop, ms(6001));
    check(r.fps == 1, "and the one after it the second's one frame: 1");
    r = look(stopped, stop, ms(6501));
    check(r.fps == 0, "a whole second after the last frame, 0");
    // A stretch with no frame shorter than a second: the last second's frames over their time take it in (its mean).
    Frames hitch = sixty;
    hitch.gaps[hitch.gap_count++] = Frames::Gap{ms(30100), ms(30350)};
    FrameRate counted;
    look(counted, hitch, ms(28505));
    look(counted, hitch, ms(28605));
    for (long long t = ms(29105); t < ms(30100); t += ms(500)) look(counted, hitch, t);
    r = look(counted, hitch, ms(30105));
    check(r.fps == 60, "60 before the hitch");
    r = look(counted, hitch, ms(30605));
    check(r.fps > 40 && r.fps < 52, "a quarter second without frames in the last second reads its mean (about 45)");
    // A stall of 2.5 s, then frames again: a look whose last second holds a frame never reads 0, though the mean over the
    // stall is under half a frame a second (0 is only for a whole second without a frame).
    Frames stall;
    stall.from = ms(1000);
    stall.period = 16666667;
    stall.gaps[stall.gap_count++] = Frames::Gap{ms(5000), ms(7500)};
    FrameRate after;
    bool zero_with_a_frame = false, zero_without = false;
    for (long long t = ms(1005); t < ms(9000); t += ms(500)) {
        const Reading x = look(after, stall, t);
        // Whether the second before this look held a frame.
        const bool frame_in_second = stall.at(t).count > stall.at(t - ms(1000)).count;
        if (x.shown && frame_in_second && x.fps == 0) zero_with_a_frame = true;
        if (x.shown && !frame_in_second && x.fps == 0) zero_without = true;
    }
    check(!zero_with_a_frame, "after a 2.5 s stall, a look with a frame in its second reads at least 1, never 0");
    check(zero_without, "and the stall's whole seconds without a frame read 0");
}

// The overlay's scale and the smallest game area the window holds (overlay_scale.h), at Windows' scales from 100 % to
// 300 % and the game's sizes from the smallest to 4K.
void overlay_scale_checks() {
    using player::overlay::at_scale;
    using player::overlay::kLeastAreaH;
    using player::overlay::kLeastAreaW;
    using player::overlay::scale_for;
    // The game's own scale wherever it is above the floor (exact: these are whole binary fractions).
    check(scale_for(720, 1.0f) == 1.0f && scale_for(1080, 1.0f) == 1.5f && scale_for(1440, 1.0f) == 2.0f && scale_for(2160, 1.0f) == 3.0f,
          "at 100 %: the game's own scale, 1 at 720 lines, 1.5 at 1080, 2 at 1440, 3 at 2160");
    check(scale_for(720, 1.5f) == 1.0f, "1280x720 at 150 %: 1 as at 100 %, not Windows' 1.5, so the counter covers no more of the game");
    check(scale_for(720, 2.0f) == 1.0f && scale_for(1080, 3.0f) == 1.5f, "a display's scale does not grow the overlay over a game it fits");
    check(scale_for(2160, 1.5f) == 3.0f && scale_for(2160, 3.0f) == 3.0f, "4K at 150 % and at 300 %: the game's own 3");
    // The floor: half of Windows' scale, in the smallest windows.
    check(scale_for(270, 1.0f) == 0.5f && scale_for(405, 1.5f) == 0.75f && scale_for(540, 2.0f) == 1.0f && scale_for(810, 3.0f) == 1.5f,
          "the smallest area at 100, 150, 200 and 300 %: half of Windows' scale, the bar's buttons 20 of Windows' own pixels");
    check(scale_for(359, 1.0f) == 0.5f && scale_for(361, 1.0f) > 0.5f, "at 100 % the floor ends at 360 lines");
    // The smallest area in the display's pixels: whole, and never less than 480x270 of Windows' own.
    check(at_scale(kLeastAreaW, 1.0f) == 480 && at_scale(kLeastAreaH, 1.0f) == 270, "the smallest area: 480x270 at 100 %");
    check(at_scale(kLeastAreaW, 1.25f) == 600 && at_scale(kLeastAreaH, 1.25f) == 338, "600x338 at 125 % (337.5 rounded up)");
    check(at_scale(kLeastAreaW, 1.5f) == 720 && at_scale(kLeastAreaH, 1.5f) == 405, "720x405 at 150 %");
    check(at_scale(kLeastAreaW, 168.0f / 96.0f) == 840 && at_scale(kLeastAreaH, 168.0f / 96.0f) == 473, "840x473 at 175 % (168 dpi)");
    check(at_scale(kLeastAreaW, 2.0f) == 960 && at_scale(kLeastAreaH, 2.0f) == 540, "960x540 at 200 %");
    check(at_scale(kLeastAreaW, 3.0f) == 1440 && at_scale(kLeastAreaH, 3.0f) == 810, "1440x810 at 300 %");
    // Every area the window can hold, at each of Windows' scales: from the smallest up to 4K's height, at the narrowest
    // the window lets it be (4:3, its height rounded as place_game rounds it, so a little narrower; and never below the
    // smallest width). The overlay's 720-line layout has 960 by 540 of room in all of them (as over a 960x540 game at
    // 100 %), less two across for that rounding, so the bar's wordmark keeps clear of its buttons.
    bool roomy = true, own = true;
    for (int dpi : {96, 120, 144, 168, 192, 240, 288}) {
        const float s = static_cast<float>(dpi) / 96.0f;
        for (int h = at_scale(kLeastAreaH, s); h <= 2160; ++h) {
            // The narrowest area of this height: the least width whose three quarters round to it, or the smallest width.
            const int w = std::max(at_scale(kLeastAreaW, s), static_cast<int>(std::ceil((4.0 * h - 2.0) / 3.0)));
            const float k = scale_for(h, s);
            // Its room at 720 lines.
            roomy = roomy && static_cast<float>(w) / k >= 958.0f && static_cast<float>(h) / k >= 539.99f;
            // Above the floor's reach, the game's own scale exactly.
            if (static_cast<float>(h) >= 360.0f * s) own = own && k == static_cast<float>(h) / 720.0f;
        }
    }
    check(roomy, "every area at 100 % to 300 %: the overlay's 720-line layout has 960x540 of room (958 across at the narrowest)");
    check(own, "every area above the floor's reach: the game's own scale, its height over 720");
}

// The text the keyboard types into the game's soft keyboard (typed_text.h): the text the game opens it with taken as
// selected, as a desktop field opens with its text.
void typed_text_checks() {
    using player::TypedText;
    // A typed name over the game's own text: the name alone.
    TypedText t;
    t.open("Player1");
    t.type("A");
    t.type("B");
    check(t.shown() == "AB", "a name typed over the text the game opened with is the name alone");
    // Eight Backspaces, then a name and Enter's character left out (Enter ends it): the name, whatever the text's length.
    t.open("Player1");
    for (int i = 0; i < 8; ++i) t.erase(true);
    t.type("Tester");
    check(t.shown() == "Tester", "Backspace eight times, then a name: that name");
    // Backspace once over the selected text: all of it goes; Delete likewise; Backspace after that takes one character.
    t.open("Player1");
    check(t.erase(true) && t.shown().empty(), "Backspace over the selected text takes all of it away");
    t.open("Player1");
    check(t.erase(false) && t.shown().empty(), "Delete over the selected text takes all of it away");
    t.open("Player1");
    t.move();
    check(!t.erase(false) && t.shown() == "Player1", "Delete with the caret at the end takes nothing");
    check(t.erase(true) && t.shown() == "Player", "after an arrow, Backspace takes back one character");
    // An arrow, Home or End first: the text stays, and what is typed after is added at its end.
    t.open("Player1");
    t.move();
    t.type("AB");
    check(t.shown() == "Player1AB", "after an arrow, a name is added at the end of the text");
    // Enter at once keeps the text the game opened with.
    t.open("Player1");
    check(t.shown() == "Player1", "Enter at once keeps the text the game opened with");
    // An input method's first syllable takes the selected text's place; its finished text is then added.
    t.open("Player1");
    check(t.compose("\xea\xb0\x80") && t.shown() == "\xea\xb0\x80", "an input method's first syllable takes the selected text's place");
    t.compose("");
    t.type("\xea\xb0\x80");
    check(t.shown() == "\xea\xb0\x80", "and the syllable it finishes is the text");
    check(t.erase(true) && t.shown().empty(), "Backspace takes a Hangul syllable back whole, all its bytes");
    // No text to start with: nothing selected, typing adds.
    t.open("");
    t.type("x");
    check(t.shown() == "x", "a keyboard opened with no text types as it goes");
}

// The handle's size (overlay_scale.h): the game's own scale exactly, and clear of the game's header at every size.
void handle_size_checks() {
    using player::overlay::handle_scale_for;
    using player::overlay::kHeaderFreeHalf;
    using player::overlay::kHeaderFreeRows;
    using player::overlay::kLeastAreaH;
    using player::overlay::kTabTall;
    using player::overlay::kTabTallLit;
    using player::overlay::rail_rows;
    using player::overlay::scale_for;
    using player::overlay::shade_rows;
    using player::overlay::tab_half;
    check(handle_scale_for(1280, 720) == 1.0f && handle_scale_for(1920, 1080) == 1.5f && handle_scale_for(3840, 2160) == 3.0f,
          "the handle at 1280x720, 1920x1080 and 4K: the game's own scale, 1, 1.5 and 3");
    check(handle_scale_for(1280, 720) == scale_for(720, 1.5f) && handle_scale_for(1920, 1080) == scale_for(1080, 1.5f) &&
              handle_scale_for(3840, 2160) == scale_for(2160, 1.5f),
          "1280x720, 1920x1080 and 4K at 150 %: the handle at the scale of the rest of the overlay");
    // Below the other pieces' floor the handle still follows the game: it is never pressed, and so stays in proportion.
    check(handle_scale_for(720, 405) == 0.5625f && scale_for(405, 1.5f) == 0.75f, "the smallest area at 150 %: the handle at the game's 0.5625, not at the floor's 0.75");
    check(handle_scale_for(480, 270) == 0.375f && handle_scale_for(480, 270) < scale_for(270, 1.0f), "the smallest area at 100 %: the game's 0.375, below the floor's 0.5");
    // Another shape: the game fits its layout to the width in an area narrower than 16:9 (its header is smaller than the
    // height says) and to the height in a wider one (its header's middle stays at the centre), and the handle with it.
    check(handle_scale_for(960, 720) == 0.75f && handle_scale_for(1152, 720) == 0.9f, "a 4:3 and a 16:10 area 720 high: the handle at the width's 0.75 and 0.9");
    check(handle_scale_for(1680, 720) == 1.0f && handle_scale_for(2560, 1080) == 1.5f, "a 21:9 area: the handle at the height's scale");
    check(handle_scale_for(1920, 1200) == 1.5f && handle_scale_for(2560, 1600) == 2.0f, "a 16:10 display in full screen: the handle at the width's scale");
    // The tab at 720 lines: below the header's rows above its buttons it keeps within the room the buttons and the words
    // leave beside the centre, at rest and deeper with the pointer on it (deeper, never wider). The header's divider at
    // the centre itself is under any handle there, and is no part of these checks (overlay_scale.h).
    check(tab_half(kHeaderFreeRows) <= kHeaderFreeHalf, "the tab keeps within 12 of the centre from the header's first row down, at 720 lines");
    check(tab_half(kTabTall) < tab_half(kHeaderFreeRows) && tab_half(kTabTallLit) < tab_half(kTabTall) && tab_half(kTabTallLit) > 0,
          "the tab narrows toward its foot, at rest and lit, and still has a foot");
    check(tab_half(0) * 2 == player::overlay::kTabTop, "the tab is as wide as its top at the game's edge");
    // Every area the window can hold, in pixels at the handle's scale: the rail and its shade stay within the header's
    // rows above its buttons, and the tab below them within the room its buttons and words leave.
    // In each shape from 4:3 to 21:9: the header's own scale there is the smaller of the width's and the height's.
    bool rail_clear = true, tab_clear = true, rail_there = true, never_larger = true;
    const float shapes[] = {4.0f / 3.0f, 16.0f / 10.0f, 16.0f / 9.0f, 21.0f / 9.0f};
    for (const float shape : shapes) {
        for (int h = kLeastAreaH; h <= 2160; ++h) {
            // The area's width in this shape, never under the smallest the window holds.
            const int w = std::max(player::overlay::kLeastAreaW, static_cast<int>(std::lround(static_cast<float>(h) * shape)));
            const float k = handle_scale_for(w, h);
            // The game's header at this size: its layout fitted into the area, as measured on its frames.
            const float header = std::min(static_cast<float>(w) / 1280.0f, static_cast<float>(h) / 720.0f);
            // The header's rows above its buttons and its room beside the centre, at this size.
            const float rows = kHeaderFreeRows * header, half = kHeaderFreeHalf * header;
            never_larger = never_larger && k <= header;
            rail_clear = rail_clear && static_cast<float>(rail_rows(k) + shade_rows(k)) <= rows;
            rail_there = rail_there && rail_rows(k) >= 1 && shade_rows(k) >= 0;
            tab_clear = tab_clear && tab_half(kHeaderFreeRows) * k <= half;
        }
    }
    check(never_larger, "every area from 270 to 2160 lines, 4:3 to 21:9: the handle is never at a larger scale than the game's header");
    check(rail_clear, "there the rail and its shade lie within the header's rows above its buttons");
    check(rail_there, "and the rail is at least a pixel at every size");
    check(tab_clear, "and the tab below them keeps within the room the header's buttons and words leave beside the centre");
    check(rail_rows(1.0f) == 2 && shade_rows(1.0f) == 1 && rail_rows(1.5f) == 3 && rail_rows(3.0f) == 6 && shade_rows(3.0f) == 3 && shade_rows(0.375f) == 0,
          "the rail 2 rows and its shade 1 at 720 lines, 6 and 3 at 4K, the shade none in the smallest window");
}

// The handle's reach (overlay_scale.h), where the pointer lights it and, resting there, brings the bar: over the same
// areas as the handle's size, against the game's header at each, and against the handle as drawn, at rest and lit.
void handle_reach_checks() {
    using player::overlay::handle_scale_for;
    using player::overlay::in_handle_reach;
    using player::overlay::kHeaderFreeHalf;
    using player::overlay::kHeaderFreeRows;
    using player::overlay::kLeastAreaH;
    using player::overlay::kLeastAreaW;
    using player::overlay::kRailWide;
    using player::overlay::kTabTall;
    using player::overlay::kTabTallLit;
    using player::overlay::tab_half;
    // The reach in a 1280x720 area, a row at a time: its first place and its last (none: -1).
    auto row = [](int y, int& first, int& last) {
        first = last = -1;
        for (int x = 0; x < 1280; ++x) {
            if (!in_handle_reach(x, y, 1280, 720)) continue;
            if (first < 0) first = x;
            last = x;
        }
    };
    int f0 = 0, l0 = 0, f4 = 0, l4 = 0, f5 = 0, l5 = 0, f22 = 0, l22 = 0, f23 = 0, l23 = 0;
    row(0, f0, l0);
    row(4, f4, l4);
    row(5, f5, l5);
    row(22, f22, l22);
    row(23, f23, l23);
    // At 1280x720: the rail at rest spans 596 to 684 in the header's five rows above its buttons; below them its SKIN
    // button ends at 627 and its words start at 674, and the tab lit ends at row 22.
    check(f0 == 596 && l0 == 684 && f4 == 596 && l4 == 684 && f5 == 628 && l5 == 652 && f22 == 628 && l22 == 652 && f23 == -1,
          "at 1280x720 the reach is 596 to 684 in the header's rows 0 to 4, 628 to 652 from row 5 to the lit tab's last row 22, none below");
    // Every area the window can hold from 270 lines to 4K, 4:3 to 21:9 (the handle's checks' own), each place near the
    // top centre: where the reach is, against the header at that size, and against the handle drawn at its scale.
    bool clear = true, holds_tab = true, holds_rail = true, no_deeper = true;
    const float shapes[] = {4.0f / 3.0f, 16.0f / 10.0f, 16.0f / 9.0f, 21.0f / 9.0f};
    for (const float shape : shapes) {
        for (int h = kLeastAreaH; h <= 2160; ++h) {
            // The area's width in this shape, never under the smallest the window holds.
            const int w = std::max(kLeastAreaW, static_cast<int>(std::lround(static_cast<float>(h) * shape)));
            // The game's header at this size, as measured on its frames: its layout fitted into the area.
            const float header = std::min(static_cast<float>(w) / 1280.0f, static_cast<float>(h) / 720.0f);
            const float middle = static_cast<float>(w) / 2;
            // Its rows above its buttons, and the room its buttons and words leave either side of the centre below them.
            const float rows = kHeaderFreeRows * header, half = kHeaderFreeHalf * header;
            // The handle as drawn here.
            const float k = handle_scale_for(w, h);
            // Every place within 60 of the centre across and 40 down at 720 lines, wider than any reach there could be.
            const int x0 = static_cast<int>(std::floor(middle - 60 * header)), x1 = static_cast<int>(std::ceil(middle + 60 * header));
            const int y1 = static_cast<int>(std::ceil(40 * header));
            for (int y = 0; y <= y1; ++y) {
                for (int x = x0; x <= x1; ++x) {
                    const float across = std::fabs(static_cast<float>(x) - middle);
                    const bool in = in_handle_reach(x, y, w, h);
                    // In the reach: in the header's rows above its buttons along the rail at rest, or below them within the
                    // room beside the centre; never on a button or a word of the header's.
                    if (in && !(static_cast<float>(y) < rows ? across <= kRailWide / 2 * header : across <= half)) clear = false;
                    // Nowhere at or below the lit tab's foot: a pointer resting under the handle is the game's.
                    if (in && static_cast<float>(y) >= kTabTallLit * k) no_deeper = false;
                    // The rail at rest, along the top edge: the pointer on it lights the handle.
                    if (static_cast<float>(y) < kHeaderFreeRows * k && across <= kRailWide / 2 * k && !in) holds_rail = false;
                    // The tab at rest and lit, every place of it (its sides leaning in from its top, 0.268 a row).
                    for (const float tall : {kTabTall, kTabTallLit}) {
                        if (static_cast<float>(y) < tall * k && across <= tab_half(static_cast<float>(y) / k) * k && !in) holds_tab = false;
                    }
                }
            }
        }
    }
    check(clear, "every area from 270 to 2160 lines, 4:3 to 21:9: the handle's reach is along the rail in the header's rows above its buttons and "
                 "within the room its buttons and words leave beside the centre below them");
    check(holds_tab, "there the tab as drawn, at rest and lit, is inside the reach");
    check(holds_rail, "and the rail at rest along the top edge");
    check(no_deeper, "and the reach goes no lower than the lit tab's foot");
}

// The bar's way down and up (overlay_motion.h): its pace, its times, a turn back midway, Windows' animations off; the
// rows of it in sight; the handle's part; the pieces at the top.
void overlay_motion_checks() {
    using player::overlay::bar_rows;
    using player::overlay::ease_down;
    using player::overlay::ease_up;
    using player::overlay::handle_hang;
    using player::overlay::handle_opacity;
    using player::overlay::Hang;
    using player::overlay::kBarDownMs;
    using player::overlay::kBarUpMs;
    using player::overlay::piece_down;
    using player::overlay::Slide;
    // The paces: from 0 to 1, never back; down ahead of the time (it slows into its place), up behind it (it gathers
    // speed).
    check(ease_down(0) == 0 && ease_down(1) == 1 && ease_up(0) == 0 && ease_up(1) == 1, "both paces go from 0 to 1");
    check(ease_down(-1) == 0 && ease_down(2) == 1 && ease_up(-1) == 0 && ease_up(2) == 1, "and stay there before the start and after the end");
    bool rising = true;
    for (int i = 1; i <= 1000; ++i) {
        const float before = static_cast<float>(i - 1) / 1000, now = static_cast<float>(i) / 1000;
        rising = rising && ease_down(now) >= ease_down(before) && ease_up(now) >= ease_up(before);
    }
    check(rising, "neither pace ever goes back");
    check(ease_down(0.25f) > 0.5f && ease_down(0.5f) == 0.875f, "the way down is past its half at a quarter of its time, and at seven eighths at its half");
    check(ease_up(0.5f) == 0.25f && ease_up(0.25f) > 0.05f, "the way up is a quarter gone at half its time, and already under way at a quarter");
    // Its times: within what was asked, down longer than up.
    check(kBarDownMs >= 180 && kBarDownMs <= 240 && kBarUpMs >= 140 && kBarUpMs <= 200 && kBarDownMs > kBarUpMs,
          "down takes 180 to 240 ms, up 140 to 200 ms, down the longer");
    // Milliseconds as the clock's nanoseconds.
    const auto at_ms = [](double n) { return static_cast<std::int64_t>(n * 1e6); };
    // A whole way down from rest, from a moment of the clock that is not its start.
    const std::int64_t t0 = at_ms(5000);
    Slide bar;
    check(bar.at(t0) == 0 && !bar.moving(t0), "the bar starts up, at rest");
    bar.aim(1, t0, true);
    check(bar.moving(t0) && bar.at(t0) == 0, "headed down: on its way, still where it was");
    check(bar.lasts == at_ms(kBarDownMs), "a whole way down takes its whole time");
    check(bar.at(t0 + at_ms(kBarDownMs) / 2) == 0.875f, "half its time in, seven eighths down");
    bool down_rising = true;
    for (int ms = 1; ms <= kBarDownMs; ++ms) down_rising = down_rising && bar.at(t0 + at_ms(ms)) >= bar.at(t0 + at_ms(ms - 1));
    check(down_rising, "it never goes back on its way down");
    check(bar.at(t0 + at_ms(kBarDownMs)) == 1 && !bar.moving(t0 + at_ms(kBarDownMs)), "at its time's end it is down exactly, and at rest");
    check(bar.at(t0 + at_ms(60000)) == 1, "and stays down");
    // Headed where it already is, or already goes: nothing changes.
    const Slide before = bar;
    bar.aim(1, t0 + at_ms(700), true);
    check(bar.began == before.began && bar.lasts == before.lasts, "headed down while down: no new way");
    // A whole way up.
    const std::int64_t t1 = t0 + at_ms(3000);
    bar.aim(0, t1, true);
    check(bar.lasts == at_ms(kBarUpMs) && bar.at(t1) == 1, "a whole way up takes its whole time, from down");
    bool up_falling = true;
    for (int ms = 1; ms <= kBarUpMs; ++ms) up_falling = up_falling && bar.at(t1 + at_ms(ms)) <= bar.at(t1 + at_ms(ms - 1));
    check(up_falling && bar.at(t1 + at_ms(kBarUpMs)) == 0, "it never comes back on its way up, and is up exactly at its end");
    // A turn back midway on the way down (the question opens): from where it is, in the share of the way up's time
    // that its place is of the whole way.
    Slide turned;
    turned.aim(1, t0, true);
    const std::int64_t mid = t0 + at_ms(60);
    const float there = turned.at(mid);
    check(there > 0.5f && there < 1, "60 ms into its way down the bar is past half, not yet down");
    turned.aim(0, mid, true);
    check(std::fabs(turned.at(mid) - there) < 1e-6f, "turned back, it is where it was: no jump");
    check(turned.moving(mid) && std::llabs(turned.lasts - static_cast<std::int64_t>(static_cast<double>(at_ms(kBarUpMs)) * there)) <= 1,
          "and its way up from there takes that share of the way up's time");
    bool back_falling = true;
    float last = there;
    for (std::int64_t t = mid; t <= mid + turned.lasts; t += at_ms(1)) {
        back_falling = back_falling && turned.at(t) <= last + 1e-6f;
        last = turned.at(t);
    }
    check(back_falling && turned.at(mid + turned.lasts) == 0, "it goes up from there and ends up");
    // A turn back on the way up (the pointer comes back onto the bar): down again from where it is.
    Slide again;
    again.rest(1);
    again.aim(0, t0, true);
    const std::int64_t later = t0 + at_ms(100);
    const float left = again.at(later);
    check(left > 0 && left < 1, "100 ms into its way up the bar is between down and up");
    again.aim(1, later, true);
    check(std::fabs(again.at(later) - left) < 1e-6f, "turned back on its way up, it is where it was");
    check(std::llabs(again.lasts - static_cast<std::int64_t>(static_cast<double>(at_ms(kBarDownMs)) * static_cast<double>(1 - left))) <= 1,
          "and the rest of the way down takes its share of the way down's time");
    check(again.at(later + again.lasts) == 1, "it ends down");
    // Headed the same way while on that way: the way goes on as it is (a look at the pointer changes nothing).
    Slide steady;
    steady.aim(1, t0, true);
    steady.aim(1, t0 + at_ms(50), true);
    check(steady.began == t0 && steady.lasts == at_ms(kBarDownMs), "headed down again while on its way down: the same way");
    // Windows' animations off: there at once, both ways, and from midway.
    Slide still;
    still.aim(1, t0, false);
    check(still.at(t0) == 1 && !still.moving(t0), "with Windows' animations off the bar is down at once");
    still.aim(0, t0 + at_ms(10), false);
    check(still.at(t0 + at_ms(10)) == 0 && !still.moving(t0 + at_ms(10)), "and up at once");
    Slide switched_off;
    switched_off.aim(1, t0, true);
    switched_off.aim(0, t0 + at_ms(40), false);
    check(switched_off.at(t0 + at_ms(40)) == 0 && !switched_off.moving(t0 + at_ms(40)), "switched off midway: up at once, nothing left half shown");
    // Hidden at once (a minimised window): at rest up, whatever it was doing.
    Slide hidden;
    hidden.aim(1, t0, true);
    hidden.rest(0);
    check(hidden.at(t0 + at_ms(30)) == 0 && !hidden.moving(t0 + at_ms(30)), "put to rest midway: up, at rest");
    // The rows in sight: none up, all of them down, whole rows in between that never go back along a way, at the
    // bar's height at each scale (74 at 720 lines: 37 at the floor's half to 222 at 4K).
    bool rows_whole = true, rows_rising = true;
    for (int height : {37, 56, 74, 111, 148, 222}) {
        rows_whole = rows_whole && bar_rows(0, height) == 0 && bar_rows(1, height) == height && bar_rows(-0.5f, height) == 0 && bar_rows(1.5f, height) == height;
        Slide way;
        way.aim(1, 0, true);
        int seen = 0;
        // A step every 240th of a second, as the fastest display here gives them.
        for (std::int64_t t = 0; t <= way.lasts; t += 4166667) {
            const int rows = bar_rows(way.at(t), height);
            rows_rising = rows_rising && rows >= seen && rows <= height;
            seen = rows;
        }
    }
    check(rows_whole, "no row of the bar in sight while it is up, every row while it is down, at every scale");
    check(rows_rising, "and on its way down the rows in sight only grow, step by step");
    check(bar_rows(0.5f, 74) == 37 && bar_rows(0.875f, 74) == 65, "half down, 37 of 74 rows; seven eighths down, 65");
    // The handle: whole while the bar is up, gone when it is down, fading evenly between; on the bar's foot, its rail
    // cut as far as the bar covers it.
    check(handle_opacity(0) == 1 && handle_opacity(1) == 0 && handle_opacity(0.25f) == 0.75f && handle_opacity(2) == 0 && handle_opacity(-1) == 1,
          "the handle is whole with the bar up, gone with it down, and fades evenly between");
    const int lip = 3;
    bool hung = true;
    for (int rows = 0; rows <= 74; ++rows) {
        const Hang hang = handle_hang(rows, lip);
        // What is left of its picture starts at the bar's foot; its rail goes row by row as the bar covers it, and no
        // more than its rail is ever cut.
        hung = hung && hang.down == rows && hang.cut == (rows < lip ? rows : lip);
    }
    check(hung, "the handle hangs from the bar's foot, its rail cut row by row as the bar's first rows cover it, and only its rail");
    const Hang rest = handle_hang(0, lip);
    check(rest.down == 0 && rest.cut == 0, "with no bar the handle is whole at the game's top edge");
    // The pieces at the top: lower by the rows in sight; one placed for the bar down stands where one placed for no
    // bar stands with the whole bar in sight, so nothing moves when its picture is made again.
    const int height = 74, own = 16;
    check(piece_down(0, 0) == 0 && piece_down(43, 0) == 43 && piece_down(height, 0) == height, "a piece placed for no bar is lower by the rows of the bar in sight");
    check(own + piece_down(height, 0) == own + height + piece_down(height, height), "placed again for the bar down, it stands where it stood");
    check(own + height + piece_down(43, height) == own + piece_down(43, 0), "and on the way up it is where the piece placed for no bar would be");
}

// Keyboard play's rules apart from the settings file (keyboard_play.h): the names and their places, a mode's lanes, the
// lane a key plays, the lane keys' state through presses, repeats and let goes, when the lane keys play, and which request
// saves a play.
void keyboard_play_checks() {
    namespace keys = player::keys;
    // Every name the settings file takes, at the place a US layout has that key (set 1 scan codes), written out here
    // apart from the header's table: a name that moved or went would read as another key.
    struct Place {
        const char* name;
        unsigned scan;
    };
    const Place places[] = {{"A", 0x1e}, {"B", 0x30}, {"C", 0x2e}, {"D", 0x20}, {"E", 0x12}, {"F", 0x21}, {"G", 0x22}, {"H", 0x23}, {"I", 0x17},
                            {"J", 0x24}, {"K", 0x25}, {"L", 0x26}, {"M", 0x32}, {"N", 0x31}, {"O", 0x18}, {"P", 0x19}, {"Q", 0x10}, {"R", 0x13},
                            {"S", 0x1f}, {"T", 0x14}, {"U", 0x16}, {"V", 0x2f}, {"W", 0x11}, {"X", 0x2d}, {"Y", 0x15}, {"Z", 0x2c}, {"1", 0x02},
                            {"2", 0x03}, {"3", 0x04}, {"4", 0x05}, {"5", 0x06}, {"6", 0x07}, {"7", 0x08}, {"8", 0x09}, {"9", 0x0a}, {"0", 0x0b},
                            {"Space", 0x39}, {"Semicolon", 0x27}, {"Quote", 0x28}, {"Comma", 0x33}, {"Period", 0x34}, {"Slash", 0x35},
                            {"LeftBracket", 0x1a}, {"RightBracket", 0x1b}, {"Backslash", 0x2b}, {"Minus", 0x0c}, {"Equals", 0x0d},
                            {"Grave", 0x29}};
    bool every_place = true, every_case = true, every_name_back = true;
    for (const Place& p : places) {
        every_place = every_place && keys::scan_of(p.name) == p.scan;
        // In lower case, as the settings file's values reach the reader, and in capitals, as a hand-made file may have it.
        std::string lower = p.name, upper = p.name;
        for (char& c : lower) c = c >= 'A' && c <= 'Z' ? static_cast<char>(c - 'A' + 'a') : c;
        for (char& c : upper) c = c >= 'a' && c <= 'z' ? static_cast<char>(c - 'a' + 'A') : c;
        every_case = every_case && keys::scan_of(lower) == p.scan && keys::scan_of(upper) == p.scan;
        every_name_back = every_name_back && std::string(keys::name_of(p.scan)) == p.name;
    }
    check(every_place, "every lane key's name is the place of that key on a US layout (A to Z, 0 to 9, Space and the punctuation keys)");
    check(every_case, "a lane key's name is read in any case");
    check(every_name_back, "each place gives its name back, for the log and the launcher");
    check(sizeof keys::kNames / sizeof keys::kNames[0] == sizeof places / sizeof places[0], "no lane key's name beyond these 48");
    check(keys::scan_of("Escape") == 0 && keys::scan_of("Esc") == 0 && keys::scan_of("Enter") == 0 && keys::scan_of("") == 0 &&
              keys::scan_of("FF") == 0 && keys::scan_of("Spac") == 0,
          "Escape, Enter, an empty name, a doubled letter and a name cut short are no lane key's");
    // The defaults: the home row on a US layout.
    check(keys::text(keys::default_lanes(2)) == "F J" && keys::text(keys::default_lanes(3)) == "D F J" && keys::text(keys::default_lanes(4)) == "D F J K",
          "the default lanes are F J, D F J and D F J K");
    // A mode's lanes: one or two keys a lane, spaces between them in any number, tabs too.
    keys::Lanes lanes;
    std::string why;
    check(keys::parse("s/d f j k/l", 4, lanes, why) && lanes.count == 4 && lanes.scan[0][0] == 0x1f && lanes.scan[0][1] == 0x20 &&
              lanes.scan[1][0] == 0x21 && lanes.scan[1][1] == 0 && lanes.scan[3][0] == 0x25 && lanes.scan[3][1] == 0x26,
          "a lane's two keys joined by '/', the second 0 where a lane has one");
    check(keys::text(lanes) == "S/D F J K/L", "a mode's lanes are written back with each name in its own capitals");
    check(keys::parse("  Semicolon\t \tSpace ", 2, lanes, why) && keys::text(lanes) == "Semicolon Space", "spaces and tabs around and between the lanes");
    // What a mode's value cannot be, each with why.
    check(!keys::parse("D F", 3, lanes, why) && why.find("3 lanes") != std::string::npos, "3 LINE with two lanes is refused, saying why");
    check(!keys::parse("D F J", 2, lanes, why), "2 LINE with three lanes is refused");
    check(!keys::parse("", 2, lanes, why), "an empty value is refused");
    check(!keys::parse("F/G/H J", 2, lanes, why) && why.find("more than two") != std::string::npos, "a lane of three keys is refused");
    check(!keys::parse("F/ J", 2, lanes, why) && !keys::parse("/F J", 2, lanes, why) && !keys::parse("F//G J", 2, lanes, why),
          "a '/' with no key beside it is refused");
    check(!keys::parse("F Enter", 2, lanes, why) && why.find("Enter") != std::string::npos, "a name of no lane key is refused, naming it");
    check(!keys::parse("F F", 2, lanes, why) && !keys::parse("D/F F J", 3, lanes, why) && !keys::parse("F/f J", 2, lanes, why),
          "a key in two places, in two lanes or twice in one, is refused");
    check(!keys::parse("D F J K", 5, lanes, why) && !keys::parse("D", 1, lanes, why), "no mode but 2, 3 and 4 lanes");
    // The lane a key plays: by its place alone.
    const keys::Lanes four = keys::default_lanes(4);
    int slot = -1;
    check(keys::lane_of(four, 0x20, false, slot) == 0 && slot == 0 && keys::lane_of(four, 0x21, false, slot) == 1 &&
              keys::lane_of(four, 0x24, false, slot) == 2 && keys::lane_of(four, 0x25, false, slot) == 3,
          "D, F, J and K play 4 LINE's lanes from the top");
    check(keys::lane_of(keys::default_lanes(2), 0x20, false, slot) == -1 && keys::lane_of(four, 0x1e, false, slot) == -1 && slot == -1,
          "a key of no lane in the mode plays none");
    check(keys::parse("s/d f j k/l", 4, lanes, why) && keys::lane_of(lanes, 0x20, false, slot) == 0 && slot == 1 &&
              keys::lane_of(lanes, 0x26, false, slot) == 3 && slot == 1,
          "a lane's second key plays that lane, as its second");
    check(keys::parse("F Slash", 2, lanes, why) && keys::lane_of(lanes, 0x35, false, slot) == 1 && keys::lane_of(lanes, 0x35, true, slot) == -1,
          "the number pad's / (the extended 0x35) is not the Slash key");
    check(keys::lane_of(four, 0, false, slot) == -1, "a key with no scan code plays no lane");
    // The lane keys' state: presses, repeats, let goes.
    {
        keys::LaneState s;
        check(s.down(1, 0, false) && s.is_down(1, 0) && s.presses(1, 0) == 1, "a key down is a press, and down");
        check(!s.down(1, 0, true) && s.presses(1, 0) == 1, "its repeats while held are the same press");
        check(s.up(1, 0) && !s.is_down(1, 0) && !s.up(1, 0), "up, it lets its lane go, once");
        check(s.down(1, 0, false) && s.presses(1, 0) == 2, "down again, a new press");
        s.up(1, 0);
        // Two keys of one lane: each a press, the lane down while either is.
        check(s.down(2, 0, false) && s.down(2, 1, false) && s.presses(2, 0) == 1 && s.presses(2, 1) == 1, "a lane's two keys each press");
        s.up(2, 0);
        check(s.any_down() && s.is_down(2, 1), "the lane stays pressed while its other key is down");
        s.up(2, 1);
        check(!s.any_down(), "nothing down once both are up");
        // A tap shorter than a frame: counted, though already up when the frame looks.
        const unsigned before = s.presses(0, 0);
        s.down(0, 0, false);
        s.up(0, 0);
        check(s.presses(0, 0) == before + 1 && !s.is_down(0, 0), "a tap shorter than a frame is still one press for the next frame");
        // Every key let go at once: the window lost the keyboard, the song paused, the game held, the question.
        s.down(0, 0, false);
        s.down(3, 1, false);
        const unsigned epoch = s.epoch();
        check(s.let_go() == 2 && !s.any_down() && s.epoch() == epoch + 1, "a let go lifts every key that was down, and says how many");
        // A key held through it: Windows goes on repeating it, which presses nothing, until it comes up and down again.
        check(!s.down(0, 0, true) && !s.is_down(0, 0) && s.presses(0, 0) == before + 2, "a key held through a let go presses nothing as it repeats");
        check(!s.up(0, 0), "and coming up after it, it lets nothing go");
        check(s.down(0, 0, false) && s.presses(0, 0) == before + 3, "pressed again after that, it plays");
        check(s.let_go() == 1 && s.let_go() == 0, "a let go with nothing down lifts nothing");
        check(!s.down(4, 0, false) && !s.down(0, 2, false) && !s.down(-1, 0, false) && !s.up(4, 0), "no lane past the fourth, no key past a lane's second");
    }
    // When the lane keys play a song's lanes; any one thing missing, and every key is the game's.
    keys::When w;
    w.keyboard = w.hooked = w.playing = true;
    w.since_frame_ms = 16;
    check(keys::lanes_play(w), "the lane keys play while a song is being played, keyboard play on and the game's input hooked");
    {
        keys::When off = w;
        off.keyboard = false;
        check(!keys::lanes_play(off), "not with keyboard play off (keyboard=off)");
        off = w;
        off.hooked = false;
        check(!keys::lanes_play(off), "not when the game's input is not where expected (the hook stayed out)");
        off = w;
        off.playing = false;
        check(!keys::lanes_play(off), "not when no song is being played (a menu, the song paused, stopped or at its end)");
        off = w;
        off.since_frame_ms = keys::kSongFrameMs;
        check(keys::lanes_play(off), "a song whose last frame was a second ago still plays");
        off.since_frame_ms = keys::kSongFrameMs + 1;
        check(!keys::lanes_play(off), "not when the song's frames stopped coming for over a second");
        off = w;
        off.held = true;
        check(!keys::lanes_play(off), "not while the game is held still (the question before quitting, minimised)");
        off = w;
        off.typing = true;
        check(!keys::lanes_play(off), "not while the game asks for text (its name field types letters)");
    }
    // The request that saves a play.
    const std::string save = R"([{"id":0,"method":"game.savePlayResult","params":[1,15,[0,0,279],279,0,[0,0,0],[0,0,0],"t"]}])";
    check(keys::saves_play("POST", save), "the game's RPC with game.savePlayResult saves a play");
    check(keys::saves_play("POST", R"([ { "id" : 3 , "method" : "game.getUserInfo" , "params" : [ ] } , { "method" :
"game.savePlayResult", "params": [] } ])"),
          "among other calls, with JSON's spaces and line ends");
    check(keys::saves_play("POST", R"([{"method":"game.savePlayResult","params":[]}])"), "a method's name as JSON escapes it");
    check(!keys::saves_play("POST", R"([{"id":0,"method":"game.savePlayResultFailLog","params":[1,15,"t",0]}])"),
          "game.savePlayResultFailLog, which keeps nothing, saves no play");
    check(!keys::saves_play("GET", save), "a GET saves no play");
    check(!keys::saves_play("POST", R"([{"id":0,"method":"game.getUserInfo","params":["game.savePlayResult"]}])"),
          "the name in another string is no call");
    check(!keys::saves_play("POST", R"({"x":"method","y":"game.savePlayResult"})"), "\"method\" as a value is no key");
    check(!keys::saves_play("POST", R"({"method":7,"params":"game.savePlayResult"})"), "a method that is no string calls nothing");
    check(!keys::saves_play("POST", R"([{"method":"game.savePl)") && !keys::saves_play("POST", ""), "a body cut short or empty saves nothing");
}

}  // namespace

int main() {
    // A file of its own beside the program's current folder.
    const std::string path = "settingstest.txt";
    // Every key, each at a value other than its default, the way the client writes them.
    const player::Settings& all = read(path,
                                       "# written by the PC client\n"
                                       "display=fullscreen\nwindow=1600x900\nvsync=off\nfps=144\nrender_scale=75\nupscaler=fsr1\nanti_aliasing=smaa\n"
                                       "show_fps=bottom_right\n"
                                       "audio_device={0.0.0.00000000}.{abc}\naudio_mode=exclusive\naudio_buffer=low\nvolume=40\n");
    check(all.fullscreen, "display=fullscreen is full screen");
    check(all.window_w == 1600 && all.window_h == 900, "window=1600x900 is that size");
    check(!all.vsync, "vsync=off is off");
    check(all.fps == 144, "fps=144 is 144");
    check(all.render_scale == 75, "render_scale=75 is 75");
    check(all.upscaler == player::Settings::Upscaler::kFsr1, "upscaler=fsr1 is AMD FSR 1");
    check(all.anti_aliasing == player::Settings::AntiAliasing::kSmaa, "anti_aliasing=smaa is SMAA");
    check(all.show_fps == player::Settings::ShowFps::kBottomRight, "show_fps=bottom_right is the bottom right corner");
    check(all.audio_device == "{0.0.0.00000000}.{abc}", "audio_device keeps the id whole, braces and dots");
    check(all.audio_exclusive, "audio_mode=exclusive is the device alone");
    check(all.audio_buffer == 0, "audio_buffer=low is 0");
    check(all.volume == 40, "volume=40 is 40");
    // Each corner by its name, and none by default.
    check(player::Settings{}.show_fps == player::Settings::ShowFps::kOff, "no frame counter is the default");
    const char* const corners[] = {"off", "top_left", "top_right", "bottom_left", "bottom_right"};
    for (int i = 0; i < 5; ++i) {
        const std::string text = std::string("show_fps=") + corners[i] + "\n";
        check(read(path, text).show_fps == static_cast<player::Settings::ShowFps>(i), corners[i]);
    }
    check(read(path, "show_fps=middle\n").show_fps == player::Settings::ShowFps::kOff, "a corner it does not know shows no frame counter");
    check(read(path, "show_fps=on\n").show_fps == player::Settings::ShowFps::kBottomRight, "show_fps=on is the bottom right, its own place");
    // The other words each key takes.
    const player::Settings& words = read(path, "display=window\nwindow=auto\nvsync=on\nfps=unlimited\naudio_device=default\n"
                                               "audio_mode=shared\naudio_buffer=safe\n");
    check(!words.fullscreen && words.window_w == 0 && words.vsync && words.fps == 1000, "window, auto, on, unlimited");
    check(words.audio_device.empty() && !words.audio_exclusive && words.audio_buffer == 2, "default, shared, safe");
    check(read(path, "fps=auto\n").fps == 0, "fps=auto is the display's own rate");
    // Each upscaler and each anti-aliasing by its name, from the defaults (the plain stretch, none).
    check(read(path, "upscaler=nis\n").upscaler == player::Settings::Upscaler::kNis, "upscaler=nis is NVIDIA NIS");
    check(read(path, "upscaler=bilinear\n").upscaler == player::Settings::Upscaler::kBilinear, "upscaler=bilinear is the plain stretch");
    check(player::Settings{}.upscaler == player::Settings::Upscaler::kBilinear, "the plain stretch is the default upscaler");
    check(player::Settings{}.anti_aliasing == player::Settings::AntiAliasing::kOff, "no anti-aliasing is the default");
    const char* const aa_names[] = {"off", "cmaa2", "smaa"};
    for (int i = 0; i < 3; ++i) {
        // Each name gives its own kind, in the enum's order.
        const std::string text = std::string("anti_aliasing=") + aa_names[i] + "\n";
        check(read(path, text).anti_aliasing == static_cast<player::Settings::AntiAliasing>(i), aa_names[i]);
    }
    // MSAA, which earlier launchers wrote, is CMAA 2 now.
    for (const char* msaa : {"msaa2", "msaa4", "msaa8"}) {
        const std::string text = std::string("anti_aliasing=") + msaa + "\n";
        check(read(path, text).anti_aliasing == player::Settings::AntiAliasing::kCmaa2, (std::string(msaa) + " is read as CMAA 2").c_str());
    }
    check(read(path, "audio_buffer=normal\n").audio_buffer == 1, "audio_buffer=normal is 1");
    // Values it cannot read keep the default, each on its own: the keys around them are still read.
    const player::Settings& bad = read(path, "display=huge\nwindow=200x100\nvsync=maybe\nfps=20\nrender_scale=40\naudio_mode=loud\nupscaler=dlss\n"
                                             "anti_aliasing=fxaa\n"
                                             "audio_buffer=tiny\nvolume=loud\nvolume2=5\nfps=120\n");
    check(!bad.fullscreen && bad.window_w == 0 && bad.vsync, "a display, window or vsync it cannot read keeps the default");
    check(bad.render_scale == 100 && !bad.audio_exclusive && bad.audio_buffer == 1 && bad.volume == 100,
          "a render scale below 50, a mode, a buffer or a volume that is no number keeps the default");
    check(bad.fps == 120, "a frame limit below 30 is left out, and a later good one read");
    check(bad.upscaler == player::Settings::Upscaler::kBilinear, "an upscaler it does not know keeps the plain stretch");
    check(bad.anti_aliasing == player::Settings::AntiAliasing::kOff, "an anti-aliasing it does not know keeps it off");
    check(read(path, "window=1280x720x2\n").window_w == 0, "a size with more after it is not read");
    check(read(path, "fps=1001\n").fps == 0, "a frame limit above 1000 is left out");
    check(read(path, "volume=0\n").volume == 0, "volume=0 is silence, a value of its own");
    // A volume out of 0 to 100 is held to it: a hand-made -5 is silence, not the default's full sound.
    check(read(path, "volume=-5\n").volume == 0, "volume=-5 is held to 0");
    check(read(path, "volume=150\n").volume == 100, "volume=150 is held to 100");
    check(read(path, "volume=101\n").volume == 100, "volume=101 is held to 100");
    // The window's smallest area, 480x270: smaller is not read (the window could not hold it).
    check(read(path, "window=320x180\n").window_w == 0, "a window smaller than 480x270 is not read");
    check(read(path, "window=479x270\n").window_w == 0 && read(path, "window=480x269\n").window_w == 0, "one pixel short of 480x270 is not read");
    const player::Settings& least = read(path, "window=480x270\n");
    check(least.window_w == 480 && least.window_h == 270, "window=480x270, the smallest, is that size");
    // Capitals in keys and names, as a hand-made file may have them; a device's id kept as written.
    const player::Settings& caps = read(path, "Display=FullScreen\nVSYNC=Off\nUpscaler=FSR1\nAnti_Aliasing=SMAA\nShow_FPS=Top_Right\n"
                                              "Audio_Mode=Exclusive\nAUDIO_DEVICE={0.0.0.00000000}.{ABC-def}\nLanguage=KO\n");
    check(caps.fullscreen && !caps.vsync && caps.upscaler == player::Settings::Upscaler::kFsr1, "keys and names in capitals are read");
    check(caps.anti_aliasing == player::Settings::AntiAliasing::kSmaa && caps.show_fps == player::Settings::ShowFps::kTopRight &&
              caps.audio_exclusive,
          "SMAA, Top_Right and Exclusive in capitals");
    check(caps.audio_device == "{0.0.0.00000000}.{ABC-def}", "a device's id keeps its own capitals");
    check(caps.language == "ko", "Language=KO is Korean");
    check(read(path, "anti_aliasing=MSAA4\n").anti_aliasing == player::Settings::AntiAliasing::kCmaa2, "MSAA4 in capitals is CMAA 2 too");
    // A byte order mark at the file's start, as Notepad saves one: the first key still read.
    const player::Settings& marked = read(path, "\xEF\xBB\xBF" "display=fullscreen\r\nvolume=30\r\n");
    check(marked.fullscreen && marked.volume == 30, "a byte order mark before the first key");
    read(path, "\xEF\xBB\xBF" "language=ko\n");
    check(player::settings_language(path) == "ko", "the language read early past a byte order mark");
    // Spaces around the parts, notes, empty lines and Windows' line ends.
    const player::Settings& loose = read(path, "\r\n# a note\r\n  vsync = off \r\n\r\nvolume\t=\t55\r\nno equals sign here\r\n");
    check(!loose.vsync && loose.volume == 55, "spaces, tabs, notes and CR LF line ends");
    // The launcher's language: each it has, none by default (the computer's), another left out; read early on its own.
    check(player::Settings{}.language.empty(), "no language is the default: the computer's");
    check(read(path, "language=ko\n").language == "ko", "language=ko is Korean");
    check(read(path, "language=en\n").language == "en", "language=en is English");
    check(read(path, "language=fr\n").language.empty(), "a language the player does not speak keeps the computer's");
    read(path, "volume=40\nlanguage = ko\r\nlanguage=xx\n");
    check(player::settings_language(path) == "ko", "the language read early: spaces and CR LF, another after it left out");
    check(player::settings_language("no-such-settings-file.txt").empty(), "no file names no language");
    // Keyboard play: on by default with each mode's default keys; off; each mode's keys chosen, one or two a lane, in any
    // case; a value it cannot read keeping that mode's default, and the other keys of the file still read.
    {
        const player::Settings fresh;
        check(fresh.keyboard && player::keys::text(fresh.lanes[0]) == "F J" && player::keys::text(fresh.lanes[1]) == "D F J" &&
                  player::keys::text(fresh.lanes[2]) == "D F J K",
              "keyboard play is on by default, with F J, D F J and D F J K");
        const player::Settings& none = read(path, "volume=80\n");
        check(none.keyboard && player::keys::text(none.lanes_of(3)) == "D F J", "a file without its keys keeps keyboard play on with the default keys");
        check(!read(path, "keyboard=off\n").keyboard && read(path, "keyboard=on\n").keyboard, "keyboard=off turns keyboard play off, keyboard=on on");
        check(read(path, "keyboard=maybe\n").keyboard && !read(path, "keyboard=OFF\n").keyboard, "keyboard=maybe keeps it on; OFF in capitals is off");
        const player::Settings& chosen = read(path, "keys_2line=A L\nkeys_3line=s/d f j/k\nKEYS_4LINE=z x PERIOD slash\n");
        check(player::keys::text(chosen.lanes[0]) == "A L", "keys_2line=A L is 2 LINE's lanes");
        check(player::keys::text(chosen.lanes[1]) == "S/D F J/K", "keys_3line with two keys on a lane, in lower case");
        check(player::keys::text(chosen.lanes[2]) == "Z X Period Slash", "keys_4line's key and names in capitals");
        const player::Settings& bad = read(path, "keys_2line=F\nkeys_3line=D F Enter\nkeys_4line=D F J K L\nkeys_5line=A B C D E\nvolume=70\n");
        check(player::keys::text(bad.lanes[0]) == "F J" && player::keys::text(bad.lanes[1]) == "D F J" && player::keys::text(bad.lanes[2]) == "D F J K",
              "a mode's value it cannot read (too few lanes, a name of no key, too many) keeps that mode's default");
        check(bad.volume == 70 && bad.keyboard, "and the file's other keys are still read");
        const player::Settings& mixed = read(path, "keys_2line=Q P\nkeys_3line=D D J\nkeys_4line=1 2 3 4\n");
        check(player::keys::text(mixed.lanes[0]) == "Q P" && player::keys::text(mixed.lanes[1]) == "D F J" && player::keys::text(mixed.lanes[2]) == "1 2 3 4",
              "a key in two places keeps its mode's default, the modes around it read");
    }
    // The size the game draws at for a render scale: the area's shape kept in whole steps where it has them.
    auto drawn = [](int w, int h, int scale, int ew, int eh) {
        const player::DrawSize d = player::draw_size(w, h, scale);
        return d.w == ew && d.h == eh;
    };
    check(drawn(1920, 1080, 100, 1920, 1080), "100 %: the area itself");
    check(drawn(1920, 1080, 85, 1632, 918) && drawn(1920, 1080, 75, 1440, 810) && drawn(1920, 1080, 50, 960, 540),
          "85, 75 and 50 % of 1920x1080: 1632x918, 1440x810, 960x540");
    check(drawn(1920, 1080, 67, 1280, 720), "67 % of 1920x1080 is 1280x720, 16:9 exactly (not 1286x724)");
    check(drawn(1280, 720, 67, 864, 486) && drawn(2560, 1440, 67, 1712, 963) && drawn(3840, 2160, 67, 2576, 1449),
          "67 % of 1280x720, 2560x1440 and 3840x2160: whole steps of 16x9");
    check(drawn(2880, 1620, 67, 1936, 1089), "67 % of a fitted 2880x1620: 1936x1089");
    check(drawn(1366, 768, 67, 915, 514), "67 % of 1366x768, which has no fine steps: 915 wide, the height from it");
    // No file: the defaults, and false.
    player::settings() = player::Settings{};
    check(!player::load_settings("no-such-settings-file.txt"), "a missing file says so");
    std::remove(path.c_str());
    // The frame counter's numbers.
    frame_counter_checks();
    // The overlay's scale and the smallest game area.
    overlay_scale_checks();
    // The text the keyboard types into the game's soft keyboard.
    typed_text_checks();
    // The handle's size and its reach, and the bar's way down and up.
    handle_size_checks();
    handle_reach_checks();
    overlay_motion_checks();
    // Keyboard play's rules.
    keyboard_play_checks();
    if (g_failed) {
        std::printf("%d of %d checks FAILED\n", g_failed, g_checks);
        return 1;
    }
    std::printf("%d checks\nALL CHECKS PASSED\n", g_checks);
    return 0;
}
