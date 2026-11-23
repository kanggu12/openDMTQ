// The player's PC settings file (settings.cpp), as the PC client writes it: each key read, a value it cannot read or a
// key it does not know leaving the default, a volume out of range held to 0 to 100, MSAA of earlier launchers read as
// CMAA 2, notes, Windows' line ends, a byte order mark and capitals taken in their stride, no file at all the defaults.
// Then the numbers of the frame counter that one of the settings shows (frame_rate.cpp): its looks at the count of
// frames through the game's start, a stretch with no frame, frames again and a hold; and its look (counter_look.h): its
// glass, its columns and rows at every scale, its figure lit at the display's rate, its frame time's words. Then the
// size the overlay over the game is drawn at and the smallest game area the window holds (overlay_scale.h), over
// Windows' scales and the game's sizes, with the size of the overlay's handle and the reach a resting pointer brings
// the bar from, which keep clear of the game's buttons and words in its header at every size, the bar's two ends, and
// the frame counter's scale and place against the game's own buttons in each shape (the pause button, the result's
// SELECT MUSIC). Then the overlay's bar on its way down and up (overlay_motion.h): its pace, a turn back midway,
// Windows' animations off, the rows of it in sight, and the handle and the pieces at the top that move with it. And the
// text the keyboard types into the game's soft keyboard (typed_text.h): the text the game opens it with taken as
// selected. And keyboard play's rules (keyboard_play.h): the lane keys' names and places, each mode's lanes from the
// settings file (one or two keys a lane, a value it cannot read keeping the default), the lane a key plays, a press,
// its repeats and every key let go, when the lane keys play at all, and which request of the game's saves a play.
// Prints ALL CHECKS PASSED when every check held.
#include "bar_gesture.h"
#include "frame_rate.h"
#include "keyboard_play.h"
#include "live_notice.h"
#include "mixer.h"
#include "overlay_motion.h"
#include "overlay_scale.h"
// The frame counter's look: its sizes, its columns, its figure's colour, its frame time's words.
#include "counter_look.h"
#include "player.h"
#include "refresh_meter.h"
#include "sound_panel.h"
#include "sound_mix.h"
#include "typed_text.h"

#include <cmath>

#include <cstdio>
// The counter's looks given one after another to its light (counter_look_checks).
#include <initializer_list>
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

// The bar's two ends (overlay_scale.h): the X as far in from the bar's right end as the wordmark from its left, at every
// scale the overlay is drawn at, and its buttons clear of the wordmark in the smallest area.
void bar_checks() {
    using player::overlay::chip_left;
    using player::overlay::kBarEnds;
    using player::overlay::kChipSize;
    using player::overlay::wordmark_left;
    // At each scale, on a bar as wide as a 16:9 area of that scale (and one wider): the X's right edge from the bar's
    // right end against the wordmark's left edge from its left, the pixel each is rounded to apart.
    bool ends_match = true;
    for (const float s : {0.5f, 0.75f, 1.0f, 1.0667f, 1.125f, 1.5f, 1.6667f, 2.0f, 2.2222f, 3.0f}) {
        for (const int w : {static_cast<int>(std::lround(1280 * s)), static_cast<int>(std::lround(1680 * s))}) {
            const int x_end = w - (chip_left(0, w, s) + static_cast<int>(std::lround(kChipSize * s)));
            if (std::fabs(static_cast<float>(x_end) - wordmark_left(s)) > 0.5f) {
                ends_match = false;
                std::printf("  at scale %.4f, %d wide: the X ends %d in from the bar's right end, the wordmark starts %.1f in\n", static_cast<double>(s), w, x_end,
                            static_cast<double>(wordmark_left(s)));
            }
        }
    }
    check(ends_match, "the bar's X ends as far in from its right end as the wordmark starts from its left, at every scale");
    check(kBarEnds == 22.0f, "both 22 in at 720 lines, as the wordmark always was");
    // The smallest area at the least scale (480x270 at 100 %, at 0.5): minimise, the third button from the right, starts
    // well right of the wordmark's end (its picture 101 wide at 720 lines).
    check(static_cast<float>(chip_left(2, 480, 0.5f)) > wordmark_left(0.5f) + 101 * 0.5f + 100, "in the smallest area the buttons keep clear of the wordmark");
}

// The frame counter's scale and place (overlay_scale.h), against the game's own buttons as measured on its frames in
// each shape: the game stretches its layout across by its width over 1280 and down by its height over 720.
// The counter's faces as the overlay measures them at scale `k` (1 at 720 lines), read once from their files: DMTQ Wide's
// widest digit (8) 802 of its 1000 units at 18 px, Pretendard SemiBold's (4) 1322 of its 2048 at 11 px, its full stop
// 558, and its wider unit, FPS, 3686 (ms 2844).
player::overlay::CounterFaces counter_faces_at(float k) {
    player::overlay::CounterFaces f;
    f.figure_cell = 802.0f / 1000.0f * player::overlay::kCounterFigure * k;
    // The small face at the size it is drawn at: 11 at 720 lines times the scale, never under its least.
    const float small = player::overlay::counter_small_px(k);
    f.small_cell = 1322.0f / 2048.0f * small;
    f.small_point = 558.0f / 2048.0f * small;
    f.unit_w = 3686.0f / 2048.0f * small;
    return f;
}

// The counter's glass at scale `k`, as fps_metrics lays it out: whole pixels.
struct Glass {
    int w, h;
};
Glass counter_glass(float k) {
    const player::overlay::CounterLayout l = player::overlay::counter_layout(counter_faces_at(k), k);
    return Glass{static_cast<int>(l.w), static_cast<int>(l.h)};
}

// A number's width as the counter sets it: a cell for each digit, its own advance for a full stop or a dash.
float tabular_width(const std::string& text, float cell, float point) {
    float w = 0;
    for (char c : text) w += c >= '0' && c <= '9' ? cell : point;
    return w;
}

// The frame counter's look (counter_look.h) with its faces as the overlay measures them: its window shown whole, its
// glass no larger than before, its two numbers right-aligned in one column and their units in the next, its rows on the
// glass's middle at every scale, the figure the larger, the figure lit (lime) only while the frames keep the display's
// rate, its colour changing only once a second's looks agree, and the frame time never wider than four digits (WIN-350,
// WIN-351, WIN-352, WIN-356; main showed it at 62 %, its words then 1.1 to 3.1 to 1 over light frames, its FPS in lime
// whatever the rate, and 333.3 ms).
void counter_look_checks() {
    using namespace player::overlay;
    check(kCounterOpacity == 255, "counter: its window shown whole, as the overlay's other pieces, so that its words keep their contrast over the game");
    const CounterFaces f = counter_faces_at(1);
    const CounterLayout l = counter_layout(f, 1);
    // At 720 lines: 10, three of the figure's cells, 6, FPS, 10 across; its two rows' ink and 8 above and below.
    check(l.w == 90 && l.h == 41, "counter: its glass 90 by 41 at 720 lines");
    check(l.w * l.h <= 88 * 44, "counter: its glass covers no more of the game than before (88 by 44)");
    // The figure's column: three cells from the glass's side room; the units 6 after it; the units' column within the room.
    check(std::fabs(l.numbers_right - (kCounterPadX + 3 * f.figure_cell)) < 0.01f && std::fabs(l.units_left - l.numbers_right - kCounterUnitGap) < 0.01f &&
              l.units_left + f.unit_w + kCounterPadX <= l.w,
          "counter: the numbers in one column, their units 6 after it in the next, both within the glass's room");
    // The frame time right-aligned on the figure's column, from 1.0 to 1000, never past the column's left edge.
    bool in_column = true;
    for (float k : {0.5f, 0.75f, 1.0f, 1.5f, 3.0f}) {
        // At each scale, its small words at their least size in a small window.
        const CounterFaces fk = counter_faces_at(k);
        const CounterLayout lk = counter_layout(fk, k);
        for (const char* time : {"1.0", "4.2", "16.7", "99.9", "333", "1000"}) {
            in_column = in_column && lk.numbers_right - tabular_width(time, fk.small_cell, fk.small_point) >= kCounterPadX * k - 0.01f;
        }
    }
    check(in_column, "counter: the frame time, 1.0 to 1000, stands right-aligned in the figure's column, within it");
    // The figure the larger: its digits half as tall again as the small words' at least.
    check(kCounterFigure * kFigureCap >= 1.5f * kCounterSmall * kSmallCap, "counter: the figure's digits half as tall again as its units' and the frame time's");
    // The rows on the glass's middle by their ink, and the glass in proportion, at every scale the counter is drawn at.
    bool middle = true, proportion = true;
    // Its size at 720 lines before it is made whole pixels, as its size at a hundred times that scale over a hundred
    // (a pixel's rounding there is a hundredth here): at every scale the glass is that times the scale, to a whole pixel.
    // The whole 720 size times the scale would count the 720 size's own rounding (up to a pixel) that many times over (2
    // pixels at 3).
    const CounterLayout hundred = counter_layout(counter_faces_at(100), 100);
    const float exact_w = hundred.w / 100, exact_h = hundred.h / 100;
    // In a small window (the counter at less than 10/11 of its 720 size) its small words stand at their least size, 10
    // pixels, the figure and the room round them at the counter's scale: the glass that much larger, never smaller than
    // its proportion (WIN-357; before, 8.25 at three quarters, the frame time's full stop at 2.4 to 1).
    bool least = kCounterSmallLeast == 10.0f;
    for (float k : {0.5f, 0.6f, 0.75f, 0.8f, 1.0f, 1.25f, 1.5f, 1.75f, 2.0f, 2.25f, 3.0f}) {
        const CounterLayout s = counter_layout(counter_faces_at(k), k);
        const float above = s.figure_base - kCounterFigure * k * kFigureCap, below = s.h - s.small_base;
        middle = middle && std::fabs(above - below) < 0.5f && above >= kCounterPadY * k - 0.5f;
        // The small row's digits as tall as the size they are set at: 11 at 720 lines times the scale, 10 at the least.
        const float small_cap = s.small_base - s.figure_base - kCounterRowGap * k;
        least = least && std::fabs(small_cap - std::max(kCounterSmall * k, 10.0f) * kSmallCap) < 0.01f;
        if (kCounterSmall * k >= 10.0f) {
            proportion = proportion && std::fabs(s.w - exact_w * k) <= 1.0f && std::fabs(s.h - exact_h * k) <= 1.0f;
        } else {
            least = least && s.w >= exact_w * k && s.h >= exact_h * k - 0.5f;
        }
    }
    check(middle, "counter: its two rows on the glass's middle by their ink, 8 at least above and below, at every scale from 0.5 to 3");
    check(proportion, "counter: its glass in proportion at every scale where its small words keep its scale (0.91 to 3), within a pixel");
    check(least, "counter: its small words never under 10 pixels: in a small window that size, its glass that much larger");
    // Lit while the frames keep the display's rate, give or take its second's rounding and two in a hundred; more with
    // VSync off too; never with no rate known, before a measure or at 0.
    check(counter_lit(240, 240) && counter_lit(235, 240) && !counter_lit(234, 240) && !counter_lit(227, 240) && counter_lit(999, 240),
          "counter: at 240 Hz its figure lit from 235 frames a second, not at 227, and lit at 999 with VSync off");
    check(counter_lit(60, 60) && counter_lit(59, 60) && !counter_lit(58, 60) && counter_lit(144, 143.86f) && counter_lit(165, 165.0f),
          "counter: lit at 60 and 59 on a display at 60 Hz, not at 58; at 144 on 143.86 Hz, at 165 on 165 Hz");
    check(!counter_lit(60, 240) && !counter_lit(240, 0) && !counter_lit(0, 240) && !counter_lit(-1, 240),
          "counter: not lit at a limit of 60 on 240 Hz, with the display's rate not known, at 0 or before a first measure");
    // The figure's light over the counter's looks (CounterLight, WIN-356): a light lit first (as many looks at the
    // display's rate as it takes) or not, given the looks `fps` one after another; how many times its figure changed
    // colour over them, and whether it is lit after the last.
    struct Run {
        int changes;
        bool lit;
    };
    auto run = [](std::initializer_list<int> fps, float hz, bool lit_first) {
        CounterLight light;
        const int rate = static_cast<int>(std::lround(hz));
        for (int i = 0; lit_first && i < kCounterLitLooks; ++i) light.look(rate, hz);
        Run r{0, light.lit};
        for (int each : fps) {
            const bool now = light.look(each, hz);
            r.changes += now != r.lit ? 1 : 0;
            r.lit = now;
        }
        return r;
    };
    // A rate at the edge of the display's, a look at it and a look short of it in turn (at 240 Hz 235 and 234; at 60 Hz 59
    // and 58; at 30 Hz 29 and 28, as a slow PC under Wine read), and wobbling about it in runs of up to two seconds, from
    // white and from lime: one colour throughout, where each look alone changed it twice a second and two looks in a row
    // every second or two.
    const int edge_240 = run({235, 234, 235, 234, 235, 234, 235, 234, 235, 234}, 240, false).changes + run({234, 235, 234, 235, 234, 235, 234, 235}, 240, true).changes;
    const int edge_60 = run({59, 58, 59, 58, 59, 58, 59, 58}, 60, false).changes + run({58, 59, 58, 59, 58, 59, 58, 59}, 60, true).changes;
    const int edge_30 = run({28, 29, 28, 29, 28, 29, 28, 29}, 30, false).changes + run({29, 28, 29, 28, 29, 28}, 30, true).changes;
    const int wobble = run({29, 29, 28, 28, 28, 29, 29, 29, 29, 28, 28, 29, 28, 28, 28, 28, 29, 29}, 30, false).changes +
                       run({29, 29, 28, 28, 28, 29, 29, 29, 29, 28, 28, 29, 28, 28, 28, 28, 29, 29}, 30, true).changes;
    check(edge_240 <= 1 && edge_60 <= 1 && edge_30 <= 1 && wobble <= 1,
          "counter: a rate at the edge of the display's changes its figure's colour once at most, not at every look");
    // Lit once six looks in a row (three seconds) keep the rate; not before.
    check(!run({240, 240, 240, 240, 240}, 240, false).lit && run({240, 240, 240, 240, 240, 240}, 240, false).lit &&
              run({234, 240, 240, 240, 240, 240, 240}, 240, false).lit && !run({240, 240, 240, 240, 240, 234, 240}, 240, false).lit,
          "counter: its figure lit once six looks in a row keep the display's rate, not before");
    // Out once six looks in a row fall short of it (a steady 232 at 240 Hz), or at once at a look clearly below it (200
    // at 240 Hz, 26 at 30 Hz); five short looks leave it lit.
    check(run({232, 232, 232, 232, 232}, 240, true).lit && !run({232, 232, 232, 232, 232, 232}, 240, true).lit && !run({200}, 240, true).lit &&
              !run({26}, 30, true).lit && run({27}, 30, true).lit,
          "counter: its figure out once six looks fall short of the display's rate, or at once clearly below it");
    // No reading (a second without a frame, the counter hidden) or no rate known: out, and the count from the start.
    check(!run({0}, 240, true).lit && !run({0, 240, 240, 240, 240, 240}, 240, true).lit && run({0, 240, 240, 240, 240, 240, 240}, 240, true).lit &&
              !run({240, 240, 240, 240, 240, 240}, 0, false).lit,
          "counter: no reading or no rate known puts its figure out and starts its count again");
    // The frame time's words: a tenth under 100 ms, whole from there on; dashes with none to give.
    check(counter_time(240, 4.2f) == "4.2" && counter_time(60, 16.67f) == "16.7" && counter_time(10, 99.94f) == "99.9" && counter_time(10, 99.96f) == "100" &&
              counter_time(3, 333.3f) == "333" && counter_time(1, 1000.0f) == "1000",
          "counter: the frame time 4.2, 16.7, 99.9, then whole: 100, 333, 1000");
    check(counter_time(0, 0) == "--" && counter_time(-1, 0) == "--" && counter_time(5, 0) == "--", "counter: no frame time to give: two dashes");
}

void counter_checks() {
    using player::overlay::counter_at;
    using player::overlay::counter_scale_for;
    using player::overlay::CounterAt;
    using player::overlay::kLeastAreaH;
    using player::overlay::kLeastAreaW;
    using player::overlay::scale_for;
    // The counter's inset (its glass's size: counter_glass, as the overlay lays it out at its scale).
    constexpr float kInset = 8;
    // At 16:9 and wider: the overlay's own scale, its height over 720.
    check(counter_scale_for(1280, 720, 1.0f) == 1.0f && counter_scale_for(1920, 1080, 1.0f) == 1.5f && counter_scale_for(3840, 2160, 1.0f) == 3.0f,
          "the counter at 1280x720, 1920x1080 and 4K: the overlay's own scale, 1, 1.5 and 3");
    check(counter_scale_for(2520, 1080, 1.0f) == 1.5f && counter_scale_for(3360, 1440, 1.0f) == 2.0f,
          "the counter at 21:9: its height's scale, as the rest of the overlay");
    // Narrower than 16:9: the game's width over 1280, not its height over 720.
    check(counter_scale_for(1920, 1200, 1.0f) == 1.5f && counter_scale_for(2560, 1600, 1.0f) == 2.0f,
          "the counter at 16:10 (1920x1200, 2560x1600): the game's width over 1280, 1.5 and 2, not the height's 1.67 and 2.22");
    check(counter_scale_for(1024, 768, 1.0f) == 0.8f, "the counter at 4:3 (1024x768): the game's width over 1280, 0.8, not the height's 1.07");
    // The floor: half of Windows' scale, as the overlay's.
    check(counter_scale_for(1024, 768, 2.0f) == 1.0f && counter_scale_for(480, 270, 1.0f) == 0.5f,
          "the counter keeps the overlay's floor: 1024x768 at 200 % at 1, the smallest area at 100 % at 0.5");
    // Every area the window holds, 4:3 to 21:9, at every scale: never larger than the rest of the overlay.
    bool never_larger = true;
    for (int dpi : {96, 144, 192, 288}) {
        const float s = static_cast<float>(dpi) / 96.0f;
        for (const float shape : {4.0f / 3.0f, 16.0f / 10.0f, 16.0f / 9.0f, 21.0f / 9.0f}) {
            for (int h = kLeastAreaH; h <= 2160; ++h) {
                const int w = std::max(kLeastAreaW, static_cast<int>(std::lround(static_cast<float>(h) * shape)));
                never_larger = never_larger && counter_scale_for(w, h, s) <= scale_for(h, s);
            }
        }
    }
    check(never_larger, "every area from 270 to 2160 lines, 4:3 to 21:9, at 100 to 300 %: the counter never larger than the rest of the overlay");
    // The game's pause button in a song, as measured on its frames: its right edge (its last column, plus one) at
    // 1280x720, 1920x1080, 1920x1200 (16:10), 1024x768 (4:3) and 2520x1080 (the 21:9 area of a 2560x1080 window, where
    // the game lays itself out at its height's scale once it knows its size, as at its start: 109 there, as at 1080).
    struct Pause {
        int w, h, right;
    };
    bool beside = true;
    for (const Pause& p : {Pause{1280, 720, 73}, Pause{1920, 1080, 109}, Pause{1920, 1200, 109}, Pause{1024, 768, 58}, Pause{2520, 1080, 109}}) {
        // The counter laid out as the overlay lays it at the top left: its inset and glass at its own scale.
        const float k = counter_scale_for(p.w, p.h, 1.0f);
        const int inset = static_cast<int>(std::lround(kInset * k));
        const Glass chip = counter_glass(k);
        const CounterAt at = counter_at(1, p.w, p.h, inset, chip.w, chip.h, 0);
        // Its gap from the button: its inset, give or take the pixel the button's edge is rounded to.
        const int gap = at.x - p.right;
        if (gap < inset - 1 || gap > inset + 1) {
            beside = false;
            std::printf("  the counter at the top left of %dx%d starts at %d, %d from the pause button's right edge (%d), not %d\n", p.w, p.h, at.x, gap, p.right,
                        inset);
        }
    }
    check(beside, "the counter at the top left stands its inset right of the game's pause button at 16:9, 16:10, 4:3 and 21:9, never on it");
    // The result's SELECT MUSIC at the bottom right, as measured on the game's frames (its right edge, its top and its
    // foot): the counter at the bottom right covers no more of it in another shape than at 16:9, as a share of the
    // counter.
    struct Button {
        int w, h, right, top, foot;
    };
    auto covered = [&](const Button& b) {
        const float k = counter_scale_for(b.w, b.h, 1.0f);
        const int inset = static_cast<int>(std::lround(kInset * k));
        const Glass chip = counter_glass(k);
        const int cw = chip.w, ch = chip.h;
        const CounterAt at = counter_at(4, b.w, b.h, inset, cw, ch, 0);
        // The part of the counter's glass left of the button's right edge and between its top and its foot.
        const int across = std::max(0, std::min(b.right - at.x, cw)), down = std::max(0, std::min(at.y + ch, b.foot) - std::max(at.y, b.top));
        return static_cast<float>(across * down) / static_cast<float>(cw * ch);
    };
    const float at_16_9 = covered(Button{1920, 1080, 1848, 946, 1048});
    const float at_16_10 = std::max(covered(Button{1920, 1200, 1848, 1051, 1164}), covered(Button{2560, 1600, 2464, 1402, 1552}));
    const float at_4_3 = covered(Button{1024, 768, 986, 673, 745});
    if (at_16_10 > at_16_9 || at_4_3 > at_16_9) {
        std::printf("  the counter over SELECT MUSIC: %.1f %% of it at 16:9, %.1f %% at 16:10, %.1f %% at 4:3\n", 100 * at_16_9, 100 * at_16_10, 100 * at_4_3);
    }
    check(at_16_10 <= at_16_9 && at_4_3 <= at_16_9, "the counter at the bottom right covers no more of the result's SELECT MUSIC at 16:10 and 4:3 than at 16:9");
}

// Where the frame counter and the notice stand against the game's own header, buttons and words (overlay_scale.h's
// counter_at, counter_has_menus_place, notice_top), as measured on the game's frames: the music list, the downloads, a
// song's page and its options, the result, the rankings before a song, and a song with its own pause screen, at 16:9
// (1280x720) and 4:3 (960x720 at 150 %). In the menus every corner's counter stands under the header at the right, on
// none of them, in every shape that has that room, and waits where none has; in a song each corner keeps clear of the
// pause button, the column under it and the pause screen's Q and MAX; the notice stands under the menus' header there and
// 16 under the top in a song, clear of the pause screen's Q and MAX (WIN-303, WIN-304; main put the top left counter on
// the player's name and level in every menu and the notice on the header's items and RANK).
void menus_place_checks() {
    using namespace player::overlay;
    // The counter's inset and its room from the right under the header (its glass: counter_glass, at its scale).
    constexpr float kInset = 8;
    struct Rect {
        const char* what;
        int x0, y0, x1, y1;
    };
    auto overlaps = [](const Rect& a, int x, int y, int w, int h) { return x < a.x1 && x + w > a.x0 && y < a.y1 && y + h > a.y0; };
    // The game's own at 16:9 (1280x720), measured on its frames: what a menu screen has in it, by screen.
    const Rect menus_16_9[] = {
        // The music list: its header (the level badge, the name, the items, RANK, Q and MAX, the shop's +, to its slanted
        // edge), the tabs, the grid, the next page's cards at the right edge, the arrows, the grid button, the page dots.
        {"the music list's header", 0, 0, 1280, 100}, {"MUSIC LIST", 0, 115, 190, 153}, {"FILTER", 195, 117, 240, 170},
        {"HOW TO PLAY", 8, 207, 145, 233}, {"the music list's grid", 300, 135, 1157, 648}, {"the next page's cards", 1268, 100, 1280, 720},
        {"the left arrow", 218, 330, 258, 460}, {"the right arrow", 1215, 330, 1255, 460}, {"the grid button", 0, 615, 100, 720},
        {"the page dots", 370, 675, 1085, 690},
        // The downloads: their own top row with the title and the X, the bottom row with Select ALL and DOWNLOAD.
        {"the downloads' title row", 0, 0, 1280, 100}, {"Select ALL", 35, 665, 210, 702}, {"DOWNLOAD", 987, 640, 1228, 705},
        // A song's page and its options: the song's title and score, the X, its Q and MAX, the tabs, the charts' cards, the
        // items, START, the rank row.
        {"the song's title and score", 40, 30, 470, 230}, {"the song page's X", 1205, 25, 1250, 70}, {"the song page's Q and MAX", 1010, 270, 1240, 360},
        {"the LINE tabs", 45, 322, 585, 376}, {"the charts' cards", 35, 418, 1255, 624}, {"START", 1028, 413, 1232, 615},
        {"the items", 68, 385, 967, 647}, {"the rank row", 0, 657, 375, 720},
        // The result: its header, the chart and title, the figures, the reward, RANKINGS, PLAY AGAIN, SELECT MUSIC.
        {"the result's header", 0, 0, 1280, 95}, {"the result's chart and title", 44, 110, 450, 195}, {"the result's figures", 45, 245, 585, 575},
        {"RANKINGS", 272, 632, 455, 698}, {"PLAY AGAIN", 756, 632, 941, 698}, {"SELECT MUSIC", 970, 632, 1232, 698},
        // The rankings before a song: its title, the list, MY RANK.
        {"RANKING", 15, 8, 380, 62}, {"the ranking's list", 20, 70, 420, 330}};
    // A song's own at 16:9: the column of the pause button, the life gauge, FEVER, the score, rate and combo; the pause
    // screen's Q and MAX, its title and its buttons.
    const Rect song_16_9[] = {{"the pause button", 13, 10, 73, 70}, {"the column's gauge and figures", 0, 75, 75, 720},
                              {"the pause screen's Q and MAX", 891, 15, 1264, 62}, {"PAUSE", 430, 150, 850, 250},
                              {"RESUME, RESTART, SELECT MUSIC", 170, 396, 1110, 540}};
    // The same of the music list and a song's page at 4:3 (960x720, the game at 0.75): the header, the grid and the next
    // page's cards, the song page's X and its Q and MAX.
    const Rect menus_4_3[] = {{"the music list's header", 0, 0, 960, 75}, {"the music list's grid", 222, 190, 868, 575},
                              {"the next page's cards", 933, 170, 960, 600}, {"the song page's X", 905, 22, 937, 53},
                              {"the song page's Q and MAX", 757, 385, 930, 450}, {"the song's title and score", 30, 25, 360, 175}};
    struct Area {
        int w, h;
        float dpi;
        const Rect* menus;
        int menus_n;
        bool song;
    };
    const Area areas[] = {{1280, 720, 1.0f, menus_16_9, static_cast<int>(sizeof menus_16_9 / sizeof menus_16_9[0]), true},
                          {960, 720, 1.5f, menus_4_3, static_cast<int>(sizeof menus_4_3 / sizeof menus_4_3[0]), false}};
    int bad = 0;
    for (const Area& a : areas) {
        const float k = counter_scale_for(a.w, a.h, a.dpi);
        const int inset = static_cast<int>(std::lround(kInset * k)), right = static_cast<int>(std::lround(kMenusRight * k));
        const Glass chip = counter_glass(k);
        const int cw = chip.w, ch = chip.h;
        const int bar = static_cast<int>(std::lround(kBarTall * scale_for(a.h, a.dpi)));
        for (int corner = 1; corner <= 4; ++corner) {
            // In the menus, with the bar up and down alike (it never reaches the counter there).
            for (const int room : {0, bar}) {
                const CounterAt at = counter_at(corner, a.w, a.h, inset, cw, ch, room, false, bar, right);
                for (int i = 0; i < a.menus_n; ++i) {
                    if (overlaps(a.menus[i], at.x, at.y, cw, ch)) {
                        ++bad;
                        std::printf("  %dx%d, the menus, corner %d: the counter at %d,%d on %s\n", a.w, a.h, corner, at.x, at.y, a.menus[i].what);
                    }
                }
                if (at.y < bar || at.x + cw > a.w || at.x < 0) {
                    ++bad;
                    std::printf("  %dx%d, the menus, corner %d: the counter at %d,%d under the bar or out of the area\n", a.w, a.h, corner, at.x, at.y);
                }
            }
            // In a song (measured at 16:9), the bar up.
            if (!a.song) continue;
            const CounterAt at = counter_at(corner, a.w, a.h, inset, cw, ch, 0, true, bar, right);
            for (const Rect& r : song_16_9) {
                if (overlaps(r, at.x, at.y, cw, ch)) {
                    ++bad;
                    std::printf("  %dx%d, a song, corner %d: the counter at %d,%d on %s\n", a.w, a.h, corner, at.x, at.y, r.what);
                }
            }
        }
        // The notice's top in the menus: under the header, the bar never reaching it; a card of 64 rows from there lies
        // on no header's button or word, whatever its width.
        const int top = notice_top(a.w, a.h, static_cast<int>(std::lround(16 * scale_for(a.h, a.dpi))), static_cast<int>(std::lround(8 * scale_for(a.h, a.dpi))), 0,
                                   bar, false);
        for (int i = 0; i < a.menus_n; ++i) {
            const Rect& r = a.menus[i];
            const bool header = std::string(r.what).find("header") != std::string::npos || std::string(r.what).find("title row") != std::string::npos;
            if (header && top < r.y1) {
                ++bad;
                std::printf("  %dx%d, the menus: the notice's top at %d, on %s\n", a.w, a.h, top, r.what);
            }
        }
    }
    check(bad == 0, "the counter in every corner and the notice stand on none of the game's own header, buttons and words, in the menus and in a song, at 16:9 and 4:3");
    // At the counter's least scale, its small words at their least size and its glass that much larger: a 960x540 window
    // at 100 % (the game at 0.75: its 16:9 frames' own at that scale), in the menus and in a song; the smallest windows at
    // 150 % (640x360 and 720x405: the game at 0.5 and 0.5625), in a song, the counter waiting in their menus (WIN-357).
    struct Least {
        int w, h;
        float dpi, game;
        bool menus;
    };
    int least_bad = 0;
    for (const Least& a : {Least{960, 540, 1.0f, 0.75f, true}, Least{640, 360, 1.5f, 0.5f, false}, Least{720, 405, 1.5f, 0.5625f, false}}) {
        const float k = counter_scale_for(a.w, a.h, a.dpi);
        const int inset = static_cast<int>(std::lround(kInset * k)), right = static_cast<int>(std::lround(kMenusRight * k));
        const Glass chip = counter_glass(k);
        const int bar = static_cast<int>(std::lround(kBarTall * scale_for(a.h, a.dpi)));
        // A box of the game's 16:9 frames at its scale here, grown to whole pixels.
        auto at_game = [&](const Rect& r) {
            return Rect{r.what, static_cast<int>(std::floor(static_cast<float>(r.x0) * a.game)), static_cast<int>(std::floor(static_cast<float>(r.y0) * a.game)),
                        static_cast<int>(std::ceil(static_cast<float>(r.x1) * a.game)), static_cast<int>(std::ceil(static_cast<float>(r.y1) * a.game))};
        };
        for (int corner = 1; corner <= 4; ++corner) {
            // In the menus where the counter has its place there, with the bar up and down alike.
            for (const int room : {0, bar}) {
                if (!a.menus) break;
                const CounterAt at = counter_at(corner, a.w, a.h, inset, chip.w, chip.h, room, false, bar, right);
                for (const Rect& r : menus_16_9) {
                    if (overlaps(at_game(r), at.x, at.y, chip.w, chip.h)) {
                        ++least_bad;
                        std::printf("  %dx%d at %.0f %%, the menus, corner %d: the counter (%dx%d) at %d,%d on %s\n", a.w, a.h, 100 * a.dpi, corner, chip.w, chip.h,
                                    at.x, at.y, r.what);
                    }
                }
                if (at.y < bar || at.x + chip.w > a.w || at.x < 0) {
                    ++least_bad;
                    std::printf("  %dx%d at %.0f %%, the menus, corner %d: the counter at %d,%d under the bar or out of the area\n", a.w, a.h, 100 * a.dpi, corner,
                                at.x, at.y);
                }
            }
            // In a song, the bar up.
            const CounterAt at = counter_at(corner, a.w, a.h, inset, chip.w, chip.h, 0, true, bar, right);
            for (const Rect& r : song_16_9) {
                if (overlaps(at_game(r), at.x, at.y, chip.w, chip.h)) {
                    ++least_bad;
                    std::printf("  %dx%d at %.0f %%, a song, corner %d: the counter (%dx%d) at %d,%d on %s\n", a.w, a.h, 100 * a.dpi, corner, chip.w, chip.h, at.x,
                                at.y, r.what);
                }
            }
            if (at.x < 0 || at.y < 0 || at.x + chip.w > a.w || at.y + chip.h > a.h) {
                ++least_bad;
                std::printf("  %dx%d at %.0f %%, a song, corner %d: the counter at %d,%d out of the area\n", a.w, a.h, 100 * a.dpi, corner, at.x, at.y);
            }
        }
    }
    check(least_bad == 0, "the counter at its least scale, its small words at their least size, stands on none of the game's own in a 960x540 window and in a song in the smallest windows at 150 %");
    // In a song the notice stands 16 under the top (lower by the bar's room while it is down), and keeps clear of the
    // pause screen's Q and MAX: a card centred no wider than the room their left edge leaves on both sides.
    check(notice_top(1280, 720, 16, 8, 0, 74, true) == 16 && notice_top(1280, 720, 16, 8, 74, 74, true) == 90,
          "the notice in a song: 16 under the top, under the bar while it is down");
    check(notice_top(1280, 720, 16, 8, 0, 74, false) == 108 && notice_top(1280, 720, 16, 8, 74, 74, false) == 108 && notice_top(960, 720, 16, 8, 0, 74, false) == 83,
          "the notice in the menus: 8 under their header (100 at 16:9, 75 at 4:3) or under the bar if that is lower, the same with the bar down");
    check(1280 - 2 * (kPauseBoxFromRight + 8) > 400, "a song's notice keeps 400 at least of room clear of the pause screen's Q and MAX at 16:9");
    // Where the menus leave the counter its place: up to 16:9 at the game's own size; not wider, nor in the smallest
    // windows at a large scale, where it waits for a song.
    check(counter_has_menus_place(1280, 720, 1) && counter_has_menus_place(1920, 1080, 1) && counter_has_menus_place(1366, 768, 1) &&
              counter_has_menus_place(1920, 1200, 1) && counter_has_menus_place(1024, 768, 1) && counter_has_menus_place(960, 720, 1.5f) &&
              counter_has_menus_place(640, 360, 1) && counter_has_menus_place(3840, 2160, 2),
          "the counter has its place in the menus at 16:9, 16:10 and 4:3, and in a 640x360 window at 100 %");
    check(!counter_has_menus_place(1680, 720, 1) && !counter_has_menus_place(2560, 1080, 1) && !counter_has_menus_place(3440, 1440, 1) &&
              !counter_has_menus_place(720, 405, 1.5f) && !counter_has_menus_place(480, 270, 1),
          "the counter waits in the menus at 21:9 and in the smallest windows at their scale's floor");
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
    check(keys::saves_play("POST", R"([{"method":"game.save\u0050layResult","params":[]}])"), "a method's name as JSON escapes it");
    check(keys::saves_play("POST", R"([{"\u006dethod":"game\u002esavePlayResult","params":[]}])"),
          "a key and a dot as JSON escapes them");
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

// The display's refreshes as the refresh thread meets them (refresh_meter.h): a display at `hz` whose wakes come every
// `wake_ns` (its own refreshes, or a fraction of them), late by a varying amount, some missed, for `seconds`, with the
// interval in use starting at `hz`'s and taking each interval the meter finds, as refresh_loop does. What it ends at, and
// when it first changed (-1: never).
struct Followed {
    long long interval;
    double changed_at;
};
Followed follow_refreshes(double hz, double wake_ns, double seconds, int miss_every = 0, long long late_most = 300000, bool whole_hertz = false) {
    player::RefreshMeter meter;
    // The rate in use as the system gave it: exactly, or in whole hertz (GDI's).
    meter.restart(whole_hertz);
    long long interval = std::llround(1e9 / hz);
    Followed out{interval, -1};
    // A fixed sequence of lateness (no clock, no random device): the same run each time.
    unsigned seed = 12345;
    for (long long i = 0;; ++i) {
        const double ideal = 1e6 + static_cast<double>(i) * wake_ns;
        if (ideal > seconds * 1e9) break;
        seed = seed * 1103515245u + 12345u;
        if (miss_every && i % miss_every == miss_every - 1) continue;
        const long long t = std::llround(ideal) + static_cast<long long>((seed >> 8) % static_cast<unsigned>(late_most + 1));
        if (const long long found = meter.wake(t, interval)) {
            interval = found;
            if (out.changed_at < 0) out.changed_at = ideal / 1e9;
        }
    }
    out.interval = interval;
    return out;
}

void refresh_meter_checks() {
    // A display that keeps the rate it gives: never another interval, the thread on time or a little late.
    const Followed steady = follow_refreshes(240.084, 1e9 / 240.084, 30);
    check(steady.changed_at < 0, "a 240.084 Hz display waking at its rate keeps its interval");
    // Some wakes missed (the thread late past a refresh now and then): still its own rate.
    const Followed missed = follow_refreshes(240.084, 1e9 / 240.084, 30, 7);
    check(missed.changed_at < 0, "a 240 Hz display with every 7th wake missed keeps its interval");
    const Followed missed160 = follow_refreshes(160, 1e9 / 160, 30, 3, 900000);
    check(missed160.changed_at < 0, "a 160 Hz display with every 3rd wake missed and wakes up to 0.9 ms late keeps its interval");
    // A busy computer: wakes up to 2.5 ms late at 240 Hz (more than half a refresh), some missed, as a song's load gives
    // them; the interval is never taken for another (it was, by a refresh miscounted in a second's 240: 241.07 Hz).
    const Followed busy = follow_refreshes(240.084, 1e9 / 240.084, 60, 9, 2500000);
    check(busy.changed_at < 0, "a 240 Hz display with wakes up to 2.5 ms late and some missed keeps its interval");
    // A display whose rate the system gave in whole hertz (59 for 59.94): its measured interval.
    const Followed whole = follow_refreshes(59, 1e9 / 59.94, 30, 0, 300000, true);
    check(whole.changed_at >= 0 && std::llabs(whole.interval - 16683350) < 20000, "a 59 Hz display waking at 59.94 Hz follows 59.94 Hz");
    // Dynamic refresh rate: the mode says 160, 180 or 240 Hz, the wakes come at 60 until the program is boosted. Its
    // wakes' 60 Hz within a few seconds, not the mode's rate with every frame waiting for a refresh three times as long.
    for (const double hz : {120.0, 160.0, 165.0, 180.0, 240.0}) {
        const Followed drr = follow_refreshes(hz, 1e9 / 60.0, 10);
        char what[160];
        std::snprintf(what, sizeof what, "a %.0f Hz display waking at 60 Hz follows 60 Hz within 3 s (at %.1f s, %.3f ms)", hz, drr.changed_at,
                      static_cast<double>(drr.interval) / 1e6);
        check(drr.changed_at >= 0 && drr.changed_at <= 3 && std::llabs(drr.interval - 16666667) < 50000, what);
    }
    // A busy computer whose wakes creep later and drop back now and then (0.3 and 0.6 of a refresh late, then on time,
    // every 80 refreshes): each drop's gap counts one refresh short, a measure says 237.1 Hz, and two say it alike. A rate
    // the system gives exactly keeps its interval (on this PC 0.11's first meter took 237.101 Hz in a quiet song run).
    {
        player::RefreshMeter meter;
        meter.restart(false);
        const double period = 1e9 / 240.084;
        long long interval = std::llround(period);
        bool changed = false;
        for (long long k = 0; k < 240 * 30; ++k) {
            const double late = k % 80 == 77 ? 0.3 : k % 80 == 78 ? 0.6 : 0.0;
            if (meter.wake(std::llround(1e6 + (static_cast<double>(k) + late) * period), interval)) changed = true;
        }
        check(!changed, "a 240.084 Hz display whose wakes creep late and drop back every 80 refreshes keeps its interval");
    }
    // Wakes all over the place: the thread late by up to more than a refresh, then waiting for the next one, as a computer
    // too busy for it gives them. No rate is taken from them (gaps counted in lower quarters said 298 Hz).
    {
        player::RefreshMeter meter;
        meter.restart(false);
        const double period = 1e9 / 240.084;
        long long interval = std::llround(period);
        bool changed = false;
        unsigned seed = 4242;
        for (double next = 1e6; next < 30e9;) {
            seed = seed * 1103515245u + 12345u;
            // Late by 0 to 1.2 refreshes.
            const double t = next + period * 1.2 * static_cast<double>((seed >> 8) % 10001) / 10000.0;
            if (meter.wake(std::llround(t), interval)) changed = true;
            // The next refresh after this wake.
            next = (std::floor((t - 1e6) / period) + 1) * period + 1e6;
        }
        check(!changed, "a 240 Hz display whose wakes come late by up to a refresh and more takes no other rate");
    }
    // And boosted after that: the wakes at the panel's own rate again, followed as fast.
    {
        player::RefreshMeter meter;
        long long interval = std::llround(1e9 / 60.0);
        double changed = -1;
        for (long long i = 0; i < 180 * 10; ++i) {
            const long long t = 1000000 + i * 5555556 + (i * 7919 % 200000);
            if (const long long found = meter.wake(t, interval)) {
                interval = found;
                if (changed < 0) changed = static_cast<double>(t) / 1e9;
            }
        }
        check(changed >= 0 && changed <= 3 && std::llabs(interval - 5555556) < 20000, "a display at 60 Hz boosted to 180 Hz follows 180 Hz within 3 s");
    }
}

// A press on the overlay's handle or the game's top edge, as made-up presses take it through bar_gesture.h: what brings
// the bar (a tap on the handle, a long press, a pull down that the bar follows and settles from), what stays the game's
// (a tap at the edge beside the handle, a press moved across or up, anything while a song is played and the game busy),
// and that the game gets every press the bar does not take, from where and when it came down.
void bar_gesture_checks() {
    using namespace player::overlay;
    const GestureSizes at720 = gesture_sizes(720);
    check(at720.slop == 10 && at720.bar == 74, "at 720 lines: a slop of 10 and a bar of 74");
    const GestureSizes at1080 = gesture_sizes(1080);
    check(at1080.slop == 15 && at1080.bar == 111, "at 1080 lines: a slop of 15 and a bar of 111");
    check(gesture_sizes(360).slop == 6, "a slop of 6 at least");
    const std::int64_t ms = 1000000;
    // A tap on the handle: held, then the bar's.
    {
        BarGesture g;
        check(g.down(640, 12, 0, Zone::kHandle, true, at720, true) == Act::kNone && g.held(), "a press on the handle is held from the game");
        check(g.move(643, 15, 30 * ms) == Act::kNone, "a move within the slop says nothing yet");
        check(g.up(643, 15, 80 * ms) == Act::kOpen && !g.active(), "a tap on the handle brings the bar, and the game hears nothing of it");
    }
    // A tap at the top edge beside the handle: the game's after all, from where and when it came down.
    {
        BarGesture g;
        check(g.down(200, 3, 5 * ms, Zone::kEdge, true, at720, true) == Act::kNone, "a press at the top edge is held");
        check(g.up(201, 4, 90 * ms) == Act::kGame && g.x0() == 200 && g.y0() == 3 && g.t0() == 5 * ms,
              "a tap at the top edge is the game's, from where and when it came down");
    }
    // A long press on the handle and at the edge: the bar, and the rest of the press is no one else's.
    for (const Zone zone : {Zone::kHandle, Zone::kEdge}) {
        BarGesture g;
        g.down(640, 8, 0, zone, true, at720, true);
        check(g.tick(300 * ms) == Act::kNone, "held 300 ms: not yet a long press");
        check(g.tick(460 * ms) == Act::kOpen && g.bars(), zone == Zone::kHandle ? "held 460 ms on the handle: the bar" : "held 460 ms at the edge: the bar");
        check(g.move(640, 60, 500 * ms) == Act::kNone && g.up(640, 60, 600 * ms) == Act::kNone, "after a long press its moves and release are the bar's");
    }
    // The mouse: its click on the handle and its press held still there are the game's, from where they came down (the
    // pointer resting on the handle brings the bar); drawn down, however long it was held first, it pulls the bar.
    {
        BarGesture g;
        check(g.down(640, 12, 0, Zone::kHandle, true, at720, false) == Act::kNone && g.held(), "the mouse's press on the handle is held from the game");
        check(g.up(641, 12, 90 * ms) == Act::kGame && g.x0() == 640 && g.y0() == 12, "the mouse's click on the handle is the game's, from where it came down");
    }
    {
        BarGesture g;
        g.down(640, 12, 0, Zone::kHandle, true, at720, false);
        check(g.tick(1000 * ms) == Act::kNone && g.held(), "the mouse held still on the handle for a second: no bar, still held");
        check(g.up(640, 12, 1000 * ms) == Act::kGame, "the mouse held still on the handle, then let go: the game's click");
    }
    {
        BarGesture g;
        g.down(640, 3, 0, Zone::kEdge, true, at720, false);
        g.tick(600 * ms);
        check(g.move(640, 30, 700 * ms) == Act::kPull, "the mouse held still at the edge for 600 ms, then drawn down: the bar follows");
        g.move(640, 60, 900 * ms);
        check(g.up(640, 60, 1000 * ms) == Act::kSettleOpen, "the mouse's pull let go at 60 of 74: the bar settles down");
    }
    // A pull down from the edge: the bar follows, its foot at the press; let go far enough down, it settles down.
    {
        BarGesture g;
        g.down(640, 2, 0, Zone::kEdge, true, at720, true);
        check(g.move(640, 9, 40 * ms) == Act::kNone, "7 down: within the slop");
        check(g.move(642, 20, 80 * ms) == Act::kPull && std::fabs(g.place() - 20.0f / 74.0f) < 0.001f, "20 down: the bar follows, its foot at the press");
        check(g.move(642, 40, 200 * ms) == Act::kPull && std::fabs(g.place() - 40.0f / 74.0f) < 0.001f, "40 down: more of the bar");
        g.move(642, 50, 400 * ms);
        check(g.up(642, 50, 500 * ms) == Act::kSettleOpen, "let go at 50 of 74, slowly: the bar settles down");
    }
    // Not far enough, slowly: back up.
    {
        BarGesture g;
        g.down(640, 2, 0, Zone::kHandle, true, at720, true);
        g.move(640, 20, 100 * ms);
        g.move(640, 30, 300 * ms);
        check(g.up(640, 30, 500 * ms) == Act::kSettleClosed, "let go at 30 of 74, slowly: the bar goes back up");
    }
    // A flick down from the handle: a short way, quickly, and the bar settles down.
    {
        BarGesture g;
        g.down(640, 10, 0, Zone::kHandle, true, at720, true);
        g.move(640, 22, 20 * ms);
        g.move(640, 34, 40 * ms);
        check(g.up(640, 34, 50 * ms) == Act::kSettleOpen, "a flick down to 34 of 74 in 50 ms: the bar settles down");
    }
    // Pulled most of the way, then flicked back up: up.
    {
        BarGesture g;
        g.down(640, 2, 0, Zone::kEdge, true, at720, true);
        g.move(640, 30, 100 * ms);
        g.move(640, 70, 300 * ms);
        g.move(640, 60, 330 * ms);
        g.move(640, 45, 360 * ms);
        check(g.up(640, 42, 370 * ms) == Act::kSettleClosed, "pulled to 70, flicked back up to 42: the bar goes back up");
    }
    // Pulled past the bar's foot: whole, no more.
    {
        BarGesture g;
        g.down(640, 2, 0, Zone::kEdge, true, at720, true);
        g.move(640, 300, 100 * ms);
        check(g.place() == 1.0f, "pulled past the bar's height: the bar whole, no more");
    }
    // Moved across or up: the game's after all, from where it came down, and so are its moves after.
    {
        BarGesture g;
        g.down(300, 5, 0, Zone::kEdge, true, at720, true);
        check(g.move(320, 8, 30 * ms) == Act::kGame && g.x0() == 300 && g.y0() == 5, "moved 20 across: the game's, from where it came down");
        check(g.move(400, 30, 60 * ms) == Act::kGame && g.up(400, 30, 90 * ms) == Act::kGame, "and its moves and release after");
    }
    {
        BarGesture g;
        g.down(640, 17, 0, Zone::kHandle, true, at720, true);
        check(g.move(640, 4, 30 * ms) == Act::kGame, "moved 13 up: the game's");
    }
    // Another finger while one is held: the held one is the game's; a pull settles where it is.
    {
        BarGesture g;
        g.down(640, 5, 0, Zone::kHandle, true, at720, true);
        check(g.other_press() == Act::kGame, "another finger while one is held: the held one is the game's after all");
        BarGesture h;
        h.down(640, 5, 0, Zone::kEdge, true, at720, true);
        h.move(640, 60, 50 * ms);
        check(h.other_press() == Act::kSettleOpen, "another finger during a pull at 60 of 74: the bar settles down");
        BarGesture c;
        c.down(640, 5, 0, Zone::kEdge, true, at720, true);
        c.move(640, 60, 50 * ms);
        check(c.cancel() == Act::kSettleClosed && !c.active(), "a pull taken away by the system: the bar goes back up");
    }
    // The zones: the handle while shown, the top 18 rows at 720 lines (8 at least), the game below.
    check(zone_at(640, 10, 720, true, true) == Zone::kHandle, "on the handle while it is shown: the handle");
    check(zone_at(640, 10, 720, false, true) == Zone::kEdge, "where the handle is, while it is hidden: the edge");
    check(zone_at(100, 0, 720, true, false) == Zone::kEdge && zone_at(100, 17, 720, true, false) == Zone::kEdge, "rows 0 to 17 at 720 lines: the edge");
    check(zone_at(100, 18, 720, true, false) == Zone::kGame, "row 18 at 720 lines: the game");
    check(zone_at(100, 26, 1080, true, false) == Zone::kEdge && zone_at(100, 27, 1080, true, false) == Zone::kGame, "rows 0 to 26 at 1080 lines: the edge");
    check(zone_at(100, 7, 270, true, false) == Zone::kEdge && zone_at(100, 8, 270, true, false) == Zone::kGame, "8 rows at least");
    // When the bar may come: never with another press down or the question up; in the menus at once; in a song (or
    // not knowing) only with the game quiet.
    check(bar_may_come(true, false, 0, false), "in the menus, the game just pressed: the bar may come");
    check(!bar_may_come(true, false, 1, false) && bar_may_come(true, false, 1, true), "in a song: only with the game quiet");
    check(!bar_may_come(true, false, -1, false) && bar_may_come(true, false, -1, true), "not knowing whether a song is played: only with the game quiet");
    check(!bar_may_come(false, false, 0, true) && !bar_may_come(true, true, 0, true), "another press down, or the question up: never");
    // A song's taps all over the top of the game while it is played: every one is the game's at once, none held.
    {
        int held = 0, given = 0;
        unsigned seed = 7;
        for (int i = 0; i < 400; ++i) {
            seed = seed * 1103515245u + 12345u;
            const int x = static_cast<int>((seed >> 8) % 1280), y = static_cast<int>((seed >> 4) % 80);
            const bool on = std::abs(x - 640) < 40 && y < 23;
            BarGesture g;
            const Act a = g.down(x, y, i * 30 * ms, zone_at(x, y, 720, true, on), bar_may_come(true, false, 1, false), at720, true);
            if (a == Act::kGame) ++given;
            if (g.held()) ++held;
            g.up(x, y, i * 30 * ms + 40 * ms);
        }
        check(given == 400 && held == 0, "400 taps at the top of a song being played: all 400 the game's at once, none held");
    }
}

// The sound's keys of the in-game panel (music_volume, effects_volume, eq, eq_low, eq_mid, eq_high), read as the
// launcher writes them, and written back by the player as the contract says: only the keys changed, each in its place,
// whatever the launcher wrote meanwhile kept, Windows' line ends and a byte order mark kept, by a rename.
std::string file_text(const std::string& path) {
    std::string out;
    if (std::FILE* f = std::fopen(path.c_str(), "rb")) {
        char buf[4096];
        std::size_t n;
        while ((n = std::fread(buf, 1, sizeof buf, f)) > 0) out.append(buf, n);
        std::fclose(f);
    }
    return out;
}
void write_text(const std::string& path, const std::string& text) {
    if (std::FILE* f = std::fopen(path.c_str(), "wb")) {
        std::fwrite(text.data(), 1, text.size(), f);
        std::fclose(f);
    }
}

void sound_settings_checks() {
    const std::string path = "settingstest-sound.txt";
    const player::Settings fresh;
    check(fresh.music_volume == 100 && fresh.effects_volume == 100 && fresh.eq == "flat" && fresh.eq_low == 0 && fresh.eq_mid == 0 &&
              fresh.eq_high == 0,
          "music and effects at 100 and a flat equaliser by default");
    const player::Settings& chosen = read(path, "volume=80\nmusic_volume=40\neffects_volume=70\neq=custom\neq_low=5\neq_mid=-3\neq_high=12\n");
    check(chosen.volume == 80 && chosen.music_volume == 40 && chosen.effects_volume == 70, "music_volume=40 and effects_volume=70 are read");
    check(chosen.eq == "custom" && chosen.eq_low == 5 && chosen.eq_mid == -3 && chosen.eq_high == 12, "eq=custom with its three bands");
    const player::Settings& held = read(path, "music_volume=150\neffects_volume=-5\neq_low=20\neq_high=-40\n");
    check(held.music_volume == 100 && held.effects_volume == 0 && held.eq_low == 12 && held.eq_high == -12, "shares and bands out of range held to them");
    const player::Settings& bad = read(path, "music_volume=loud\neq=rock\neq_mid=1.5\nvolume=60\n");
    check(bad.music_volume == 100 && bad.eq == "flat" && bad.eq_mid == 0 && bad.volume == 60, "a value it cannot read keeps the default, the rest read");
    check(read(path, "EQ=Treble\nMusic_Volume=10\n").eq == "treble" && read(path, "EQ=Treble\nMusic_Volume=10\n").music_volume == 10,
          "keys and presets in capitals");
    // Each preset's bands.
    using player::audio::EqPreset;
    using player::audio::preset_bands;
    check(preset_bands(EqPreset::kFlat, {3, 3, 3}).low == 0 && preset_bands(EqPreset::kBass, {}).low == 6 && preset_bands(EqPreset::kTreble, {}).high == 6 &&
              preset_bands(EqPreset::kVocal, {}).mid == 4 && preset_bands(EqPreset::kCustom, {1, 2, 3}).mid == 2,
          "the presets' bands, custom keeping its own");
    // Written back: only the key changed, in its place, the launcher's other keys and its CR LF and byte order mark kept.
    write_text(path, "\xEF\xBB\xBF" "display=window\r\nvolume=80\r\nkeyboard=on\r\neq=vocal\r\n");
    check(player::save_settings_keys(path, {{"music_volume", "40"}}), "a key written back");
    check(file_text(path) == "\xEF\xBB\xBF" "display=window\r\nvolume=80\r\nmusic_volume=40\r\nkeyboard=on\r\neq=vocal\r\n",
          "music_volume goes right after volume, every line ending CR LF, the mark kept");
    check(player::save_settings_keys(path, {{"volume", "55"}}) &&
              file_text(path) == "\xEF\xBB\xBF" "display=window\r\nvolume=55\r\nmusic_volume=40\r\nkeyboard=on\r\neq=vocal\r\n",
          "volume changed in its place; eq=vocal the launcher wrote stays");
    // The launcher writes the whole file meanwhile (another key changed, its own order): the player's next change keeps it.
    write_text(path, "volume=55\nmusic_volume=40\nrender_scale=75\neq=bass\n");
    check(player::save_settings_keys(path, {{"effects_volume", "30"}}) &&
              file_text(path) == "volume=55\nmusic_volume=40\neffects_volume=30\nrender_scale=75\neq=bass\n",
          "effects_volume after music_volume; render_scale=75 and eq=bass the launcher wrote stay, LF line ends kept");
    // A key in capitals from a hand-made file: changed where it is.
    write_text(path, "Volume=10\nMUSIC_VOLUME=20\n");
    check(player::save_settings_keys(path, {{"music_volume", "25"}}) && file_text(path) == "Volume=10\nmusic_volume=25\n", "a key in capitals is changed where it is");
    // A file without the sound's keys: at the end, in order.
    write_text(path, "display=window\n");
    check(player::save_settings_keys(path, {{"eq", "custom"}, {"eq_low", "-4"}}) && file_text(path) == "display=window\neq=custom\neq_low=-4\n",
          "keys the file has not go at its end in order");
    // The start's path to the mix (main.cpp): the file read as the player reads it at its start, then the mixer's
    // choices and controls from it, the launcher's volume, music, effects and equaliser among them.
    const player::Settings& launcher = read(path, "volume=33\r\nmusic_volume=44\r\neffects_volume=55\r\neq=custom\r\neq_low=-4\r\n"
                                                  "eq_mid=2\r\neq_high=7\r\naudio_device={0.0.0.00000000}.{xyz}\r\naudio_mode=exclusive\r\n"
                                                  "audio_buffer=safe\r\n");
    player::audio::Options given;
    player::sound_options(launcher, given);
    check(given.volume == 33 && given.levels.master == 33 && given.levels.music == 44 && given.levels.effects == 55,
          "the launcher's volume, music and effects reach the mixer at the start");
    check(given.levels.eq == player::audio::EqPreset::kCustom && given.levels.bands().low == -4 && given.levels.bands().mid == 2 &&
              given.levels.bands().high == 7,
          "the launcher's custom equaliser reaches the mixer at the start, its three bands");
    check(given.device == "{0.0.0.00000000}.{xyz}" && given.exclusive && given.buffer == 2, "the launcher's device, mode and buffer reach the mixer");
    // No temporary file left beside it.
    check(file_text(path + ".player.tmp").empty(), "no temporary file left");
    std::remove(path.c_str());
}

// The sound panel's layout (sound_panel.h) and the bar's Sound button, over the shapes and Windows' scales players have:
// within the game's area, apart from the bar and the window's edge, its rows apart, every word inside its padding, its
// gaps on its spacing scale, its controls large enough to hit, and room left for the notice beside it.
void sound_panel_checks() {
    using namespace player::overlay;
    // Every gap of the panel's on its spacing scale (4, 8, 12, 16, 20 at 720 lines).
    bool on_scale = true;
    for (const float gap : {kPanelSide, kPanelTop, kPanelFoot, kTitleLine, kAfterLine, kGroupGap, kChipsAfter, kLabelGap, kValueGap, kPanelInset, kChipsGap, kChipPad}) {
        if (!(gap == 4 || gap == 8 || gap == 12 || gap == 16 || gap == 20)) on_scale = false;
    }
    check(on_scale, "every gap of the sound panel's is 4, 8, 12, 16 or 20 at 720 lines");
    struct Shape {
        int w, h;
        float dpi;
    };
    const Shape shapes[] = {{480, 270, 1}, {720, 405, 1.5f}, {960, 540, 2}, {1024, 768, 1}, {1280, 720, 1}, {1366, 768, 1}, {1280, 960, 1.25f},
                            {1600, 900, 1.25f}, {1920, 1080, 1}, {1920, 1080, 1.5f}, {1920, 1200, 1}, {2520, 1080, 1}, {2560, 1440, 1.5f},
                            {3360, 1440, 1}, {3840, 2160, 2}, {5120, 2880, 2.25f}};
    int bad = 0;
    for (const Shape& sh : shapes) {
        const float k0 = scale_for(sh.h, sh.dpi);
        const int bar = static_cast<int>(std::lround(kBarTall * k0));
        const SoundLayout l = sound_layout(sh.w, sh.h, k0, bar);
        const float k = l.scale;
        auto fail = [&](const char* what) {
            ++bad;
            std::printf("  %dx%d at %.0f %%: %s\n", sh.w, sh.h, static_cast<double>(sh.dpi * 100), what);
        };
        // Within the area, apart from the bar's foot and the area's right edge and foot by its inset (whole pixels).
        const float inset = std::round(kPanelInset * k);
        if (l.panel.x < 0 || l.panel.right() > static_cast<float>(sh.w) - inset + 0.01f || l.panel.bottom() > static_cast<float>(sh.h) - inset + 0.01f) fail("the panel leaves the area or its inset");
        if (l.panel.y < static_cast<float>(bar) + inset - 0.01f) fail("the panel touches the bar");
        // Its rows one under another, none over the next; the titles' lines between their titles and the next row.
        float last = l.title.bottom();
        if (l.title_line <= l.title.bottom() || l.title_line >= l.row[kMaster].y) fail("the title's line is not between it and the first row");
        for (int i = kMaster; i <= kEffects; ++i) {
            if (l.row[i].y < last - 0.01f) fail("a volume's row over the one above it");
            last = l.row[i].bottom();
        }
        if (l.eq_title.y < last + kGroupGap * k - 0.01f) fail("the equaliser's title closer than its gap");
        if (l.eq_line <= l.eq_title.bottom() || l.eq_line >= l.chip[0].y) fail("the equaliser's line is not between its title and the chips");
        for (int i = 0; i < kPresets; ++i) {
            if (i + 1 < kPresets && l.chip[i].right() + 4 * k > l.chip[i + 1].x + 0.01f) fail("two chips closer than 4");
            if (l.chip[i].x < l.panel.x + kPanelSide * k - 0.01f || l.chip[i].right() > l.panel.right() - kPanelSide * k + 0.01f) fail("a chip outside the padding");
        }
        last = l.chip[0].bottom();
        for (int i = kLow; i <= kHigh; ++i) {
            if (l.row[i].y < last - 0.01f) fail("a band's row over what is above it");
            last = l.row[i].bottom();
        }
        if (last > l.panel.bottom() - kPanelFoot * k + 0.01f) fail("the last row inside the foot's padding");
        // Each slider: the thumb at either end clear of its label and its value by 4 at least, the value inside the padding.
        for (int i = kMaster; i <= kHigh; ++i) {
            const float half = kThumb / 2 * k;
            if (l.track[i].x - half < l.label[i].right() + 4 * k - 0.01f) fail("a thumb at its least over its label");
            if (l.track[i].right() + half > l.value[i].x - 4 * k + 0.01f) fail("a thumb at its most over its value");
            if (l.value[i].right() > l.panel.right() - kPanelSide * k + 0.01f) fail("a value outside the padding");
            if (l.track[i].w < 60 * k) fail("a track shorter than 60");
        }
        // Large enough to hit: a slider's row and a chip at least 20 and 16 of Windows' own pixels high.
        if (l.row[kMaster].h < 20 * sh.dpi - 0.01f || l.chip[0].h < 16 * sh.dpi - 0.01f) fail("a control too small to hit");
        // Room for the notice beside it: at least 300 at 720 lines left of it (its least).
        if (l.panel.x - 8 * k0 < 300 * k0 * 0.5f) fail("no room left for the notice beside the panel");
        // The bar's Sound button: left of minimise by the buttons' gap, clear of the wordmark (101 wide at 720 lines).
        const int sound_right = chip_left(2, sh.w, k0) - static_cast<int>(std::lround(kChipGap * k0));
        const float sound_left = static_cast<float>(sound_right) - std::round(kSoundChipWide * k0);
        if (sound_left < wordmark_left(k0) + 101 * k0 + 20 * k0) fail("the Sound button reaches the wordmark");
        // A point on each control is that control; a point in the panel's padding is none.
        for (int i = kMaster; i <= kHigh; ++i) {
            if (sound_control_at(l, l.track[i].x + l.track[i].w / 2, l.row[i].y + l.row[i].h / 2) != i) fail("a slider's middle is not it");
        }
        for (int i = 0; i < kPresets; ++i) {
            if (sound_control_at(l, l.chip[i].x + l.chip[i].w / 2, l.chip[i].y + l.chip[i].h / 2) != kChipFlat + i) fail("a chip's middle is not it");
        }
        if (sound_control_at(l, l.panel.x + 2, l.panel.y + 2) != kNoControl) fail("the panel's corner is a control");
        // A slider's ends give its range's ends, and its middle a band's 0 dB.
        if (slider_value_at(l, kMaster, l.track[kMaster].x - 5) != 0 || slider_value_at(l, kMaster, l.track[kMaster].right() + 5) != 100 ||
            slider_value_at(l, kLow, l.track[kLow].x + l.track[kLow].w / 2) != 0 || slider_value_at(l, kHigh, l.track[kHigh].right()) != 12) {
            fail("a slider's ends or middle give the wrong value");
        }
    }
    check(bad == 0, "the sound panel and its button over 16 shapes and scales: inside, apart, padded, large enough, room for the notice");
    // The equaliser's chips by their words (WIN-302; main made the five one width, "Custom" 3 and 4 pixels from its border
    // and "Flat" 18 and 19): in each shape and either language, each word in the middle of its chip with the same room on
    // both sides as every other chip's, at least the scale's 8, the chips 8 apart and the row as wide as the inside.
    int chips_bad = 0;
    for (const Shape& sh : shapes) {
        for (const bool korean : {false, true}) {
            const float k0 = scale_for(sh.h, sh.dpi);
            const SoundLayout l = sound_layout(sh.w, sh.h, k0, static_cast<int>(std::lround(kBarTall * k0)), korean);
            const float k = l.scale, inner_left = l.panel.x + kPanelSide * k, inner_right = l.panel.right() - kPanelSide * k;
            float first_room = -1;
            bool ok = std::fabs(l.chip[0].x - inner_left) < 0.01f && std::fabs(l.chip[kPresets - 1].right() - inner_right) < 0.01f;
            for (int i = 0; i < kPresets; ++i) {
                const float room = (l.chip[i].w - kChipWords[korean ? 1 : 0][i] * k) / 2;
                if (first_room < 0) first_room = room;
                ok = ok && room >= kChipPad * k - 0.01f && std::fabs(room - first_room) < 0.01f;
                if (i + 1 < kPresets) ok = ok && std::fabs(l.chip[i + 1].x - l.chip[i].right() - kChipsGap * k) < 0.01f;
            }
            if (!ok) {
                ++chips_bad;
                std::printf("  %dx%d at %.0f %% (%s): a chip's word off its middle, closer than 8 to its border, or the row not the inside\n", sh.w, sh.h,
                            static_cast<double>(sh.dpi * 100), korean ? "ko" : "en");
            }
        }
    }
    check(chips_bad == 0, "the equaliser's chips: each word in its chip's middle with the same room as the others, 8 at least, in both languages");
}

// The broadcast's notices as the PC player reads them (live_notice.h): each numbered notice once, never by its words,
// the LIVE tag by its kind, off notices shown even where the PC cannot send, keys found only with their colon, and the
// player's own notice when the server stops answering while it broadcasts and when it answers again.
void live_notice_checks() {
    using namespace player::live_notice;
    const Fields numbered = fields_of(R"({"on":false,"toast":"Ended\nWatch","toast_id":7,"toast_kind":"off","switch":false})");
    check(numbered.id == 7 && numbered.kind == "off", "notice: its number and its kind read");
    const Fields older = fields_of(R"({"on":true,"token":"abc","toast":"On air\nWatch"})");
    check(older.id == -1 && older.kind.empty(), "notice: an older server's answer has no number (-1) and no kind");
    check(fields_of(R"({"toast_kind":"on","on":true,"toast_id":3})").kind == "on" && value_at(R"({"toast_kind":"on","on":true})", "on") == 24,
          "notice: the kind's value on before the key on is no key");
    int last = 0;
    auto with = [](int id, const char* kind) {
        Fields f;
        f.id = id;
        f.kind = kind;
        return f;
    };
    const Notice a = notice_of(true, true, "On air\nWatch", with(1, "on"), last, false);
    check(a.show && a.live && last == 1, "notice: the first on notice shows, with the LIVE tag");
    const Notice b = notice_of(true, false, "Ended\nWatch", with(2, "off"), last, false);
    check(b.show && !b.live && last == 2, "notice: the off notice shows, without the tag");
    const Notice c = notice_of(true, true, "On air\nWatch", with(3, "on"), last, false);
    check(c.show && c.live, "notice: on again with the same words shows again");
    check(!notice_of(true, true, "On air\nWatch", with(3, "on"), last, false).show, "notice: the same number again is a repeat, left out");
    check(notice_of(true, false, "Ended\nOff here", with(4, "end"), last, false).show, "notice: the server's broadcasts off shows");
    check(notice_of(true, false, "Switched on\nWaits", with(5, "wait"), last, false).show && notice_of(true, false, "Off\nStays off", with(6, "held"), last, false).show,
          "notice: switched on or off while the server's are off shows");
    check(!notice_of(true, true, "On air\nWatch", with(7, "on"), last, true).show && last == 7, "notice: the on notice left out where this computer cannot send");
    check(notice_of(true, false, "Ended\nWatch", with(8, "off"), last, true).show, "notice: the off notice shows even where this computer cannot send");
    check(!notice_of(true, false, "", with(0, ""), last, false).show, "notice: an answer without a notice shows none");
    int old_last = 0;
    check(notice_of(true, true, "On air", Fields{}, old_last, false).live && notice_of(true, false, "Ended", Fields{}, old_last, false).show &&
              notice_of(true, true, "On air", Fields{}, old_last, false).show,
          "notice: an older server's notices each show, the tag while on air");
    // The server quiet while on air.
    int misses = 0;
    bool lost = false;
    check(!reach_notice(true, true, false, misses, lost, false).show, "reach: an answer on air says nothing");
    check(!reach_notice(false, false, true, misses, lost, false).show && !reach_notice(false, false, true, misses, lost, false).show,
          "reach: two asks unanswered say nothing yet");
    const Notice gone = reach_notice(false, false, true, misses, lost, false);
    check(gone.show && !gone.live && gone.text == "Your broadcast has stopped\nThe server is not answering", "reach: the third says the broadcast stopped");
    check(!reach_notice(false, false, true, misses, lost, false).show, "reach: once, not again while it stays quiet");
    const Notice back = reach_notice(true, true, true, misses, lost, false);
    check(back.show && back.live && back.text == "Your broadcast is back on\nThe server answers again", "reach: its next answer on air says it is back");
    for (int i = 0; i < 3; ++i) reach_notice(false, false, true, misses, lost, true);
    check(lost && !reach_notice(true, false, true, misses, lost, false).show && !lost, "reach: back off air says nothing");
    int m2 = 0;
    bool l2 = false, any = false;
    for (int i = 0; i < 6; ++i) any |= reach_notice(false, false, false, m2, l2, false).show;
    check(!any && !l2, "reach: asks unanswered while off air say nothing");
    int m3 = 0;
    bool l3 = false;
    reach_notice(false, false, true, m3, l3, true);
    reach_notice(false, false, true, m3, l3, true);
    check(reach_notice(false, false, true, m3, l3, true).text.rfind("\xeb\xb0\xa9\xec\x86\xa1", 0) == 0, "reach: in Korean when the player speaks it");
}

// The question before quitting (overlay_scale.h's ask_rows, ask_mid_song): its line about the song's record only when
// asked mid-song, the card without that line's row in the menus and its buttons 34 under the game's line there, as they
// are 34 under the line mid-song (WIN-300; main said the song's line on every screen, the menus' too).
void question_checks() {
    using player::overlay::ask_mid_song;
    using player::overlay::ask_rows;
    using player::overlay::AskRows;
    // Mid-song, as before: the line 12 under the game's line (74), 20 high; the buttons 34 under it, 48 high; 40 under them.
    const AskRows song = ask_rows(true);
    check(song.text_top == 86 && song.text_h == 20 && song.buttons_top == 140 && song.card_h == 228,
          "question: asked mid-song, the line about the song's record under the game's line and the card as before (228 high)");
    // In the menus: no line, the buttons 34 under the game's line, the card shorter by the line's row and its gap.
    const AskRows menus = ask_rows(false);
    check(menus.text_h == 0 && menus.buttons_top == 74 + 34 && menus.card_h == 228 - 32,
          "question: asked in the menus, no line about a song's record, the buttons 34 under the game's line, the card 196 high");
    check(menus.buttons_top - (menus.text_top + menus.text_h) == song.buttons_top - (song.text_top + song.text_h),
          "question: the buttons as far under what is above them in the menus as mid-song");
    // Only a song known to go on (keyboard play's word: 1) has a record at stake; none (0) or not known (-1) has not.
    check(ask_mid_song(1) && !ask_mid_song(0) && !ask_mid_song(-1), "question: the song's line only while a song is known to go on");
}

// A ban's notice as the PC player keeps it up (live_notice.h ban_of, hold_of): the server's "ban" read as a key with its
// JSON escapes, the notice held while every answer carries it and taken again when its words change, let go at the first
// answer with "" and the player's own words then, an older server or no answer changing nothing (WIN-301; main showed the
// ban's notice for six seconds, then the game's own network error alone).
void ban_hold_checks() {
    using namespace player::live_notice;
    // The key with its colon: the kind's value "ban", before it, is no key; escapes as json_encode writes them, and
    // UTF-8 as it is where JSON_UNESCAPED_UNICODE leaves it.
    const BanWord banned = ban_of(R"({"on":false,"toast":"","toast_id":3,"toast_kind":"ban","ban":"You cannot play on this server\nMade-up \"scores\" \/ \\ \u00e9 \ud83c\udfb5 · until Nov 26, 11:00"})");
    check(banned.given && banned.text == "You cannot play on this server\nMade-up \"scores\" / \\ \xc3\xa9 \xf0\x9f\x8e\xb5 \xc2\xb7 until Nov 26, 11:00",
          "ban: the server's words read, the kind's value ban no key, every escape of json_encode's");
    const BanWord free = ban_of(R"({"on":true,"toast":"","toast_id":0,"toast_kind":"","ban":""})");
    check(free.given && free.text.empty(), "ban: \"\" read as no ban, from a server that says it");
    check(!ban_of(R"({"on":true,"toast":"On air\nWatch","toast_id":4,"toast_kind":"on"})").given && !ban_of(R"({"toast_kind":"ban","toast":"x"})").given,
          "ban: an older server's answer, or one naming nobody, says nothing of a ban (the kind's value is no key)");
    check(!ban_of(R"({"ban":"You cannot play)").given, "ban: words without their end say nothing of a ban");
    // Held while it lasts, and again only when its words change.
    std::string held;
    const BanWord first{true, "You cannot play on this server\nMade-up scores \xc2\xb7 until Nov 26, 11:00"};
    const Hold up = hold_of(true, first, held, false);
    check(up.change && up.text == first.text && !up.over.show && held == first.text, "ban: the first answer with it holds the notice up");
    check(!hold_of(true, first, held, false).change, "ban: the same words in the next answers change nothing (it stays up, no timer)");
    const BanWord again{true, "You cannot play on this server\nScores sent from a program"};
    const Hold other = hold_of(true, again, held, false);
    check(other.change && other.text == again.text && !other.over.show, "ban: made again with another reason or end, the notice says the new one");
    // No answer, or an older server's, changes nothing: the game is still refused as far as anyone can tell.
    check(!hold_of(false, BanWord{}, held, false).change && !hold_of(true, BanWord{}, held, false).change && held == again.text,
          "ban: no answer, or one that says nothing of a ban, keeps the notice up");
    // Over: let go, with the player's own words, once.
    const Hold over = hold_of(true, BanWord{true, ""}, held, false);
    check(over.change && over.text.empty() && over.over.show && !over.over.live && over.over.text == "You can play on this server again\nThe ban has ended" &&
              held.empty(),
          "ban: the first answer without it lets the notice go and says the game can be played again");
    check(!hold_of(true, BanWord{true, ""}, held, false).change, "ban: said once, not at every answer after");
    std::string held_ko;
    hold_of(true, first, held_ko, true);
    check(hold_of(true, BanWord{true, ""}, held_ko, true).over.text ==
              "\xec\x9d\xb4 \xec\x84\x9c\xeb\xb2\x84\xec\x97\x90\xec\x84\x9c \xeb\x8b\xa4\xec\x8b\x9c \xed\x94\x8c\xeb\xa0\x88\xec\x9d\xb4\xed\x95\xa0 \xec\x88\x98 "
              "\xec\x9e\x88\xec\x96\xb4\xec\x9a\x94\n\xec\x9d\xb4\xec\x9a\xa9 \xec\xa0\x95\xec\xa7\x80\xea\xb0\x80 \xeb\x81\x9d\xeb\x82\xac\xec\x96\xb4\xec\x9a\x94",
          "ban: in Korean when the player speaks it");
    // Never held: "" says nothing.
    std::string never;
    check(!hold_of(true, BanWord{true, ""}, never, false).change, "ban: no ban and none held says nothing");
}

int main() {
    // A file of its own beside the program's current folder.
    const std::string path = "settingstest.txt";
    // Every key, each at a value other than its default, the way the client writes them.
    const player::Settings& all = read(path,
                                       "# written by the PC client\n"
                                       "display=window\nwindow=1600x900\nvsync=off\nfps=144\nrender_scale=75\nupscaler=nis\nanti_aliasing=smaa\n"
                                       "show_fps=bottom_right\n"
                                       "audio_device={0.0.0.00000000}.{abc}\naudio_mode=exclusive\naudio_buffer=low\nvolume=40\n");
    check(!all.fullscreen, "display=window is a window");
    check(all.window_w == 1600 && all.window_h == 900, "window=1600x900 is that size");
    check(!all.vsync, "vsync=off is off");
    check(all.fps == 144, "fps=144 is 144");
    check(all.render_scale == 75, "render_scale=75 is 75");
    check(all.upscaler == player::Settings::Upscaler::kNis, "upscaler=nis is NVIDIA NIS");
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
    const player::Settings& words = read(path, "display=fullscreen\nwindow=auto\nvsync=on\nfps=unlimited\naudio_device=default\n"
                                               "audio_mode=shared\naudio_buffer=safe\n");
    check(words.fullscreen && words.window_w == 0 && words.vsync && words.fps == 1000, "full screen, auto, on, unlimited");
    check(words.audio_device.empty() && !words.audio_exclusive && words.audio_buffer == 2, "default, shared, safe");
    check(read(path, "fps=auto\n").fps == 0, "fps=auto is the display's own rate");
    // Each upscaler and each anti-aliasing by its name, and the defaults: full screen, AMD FSR 1 below 100 %, no
    // anti-aliasing (player.h says why each).
    check(read(path, "upscaler=fsr1\n").upscaler == player::Settings::Upscaler::kFsr1, "upscaler=fsr1 is AMD FSR 1");
    check(read(path, "upscaler=bilinear\n").upscaler == player::Settings::Upscaler::kBilinear, "upscaler=bilinear is the plain stretch");
    check(player::Settings{}.upscaler == player::Settings::Upscaler::kFsr1, "AMD FSR 1 is the default upscaler, as the launcher's");
    check(player::Settings{}.fullscreen, "full screen is the default display, as the launcher's");
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
    // The low buffer where the file names none, as the launcher's own default: measured through whole songs on real
    // Windows, the least latency with no gap.
    check(player::Settings{}.audio_buffer == 0 && read(path, "volume=50\n").audio_buffer == 0, "the low buffer is the default, as the launcher's");
    // Values it cannot read keep the default, each on its own: the keys around them are still read.
    const player::Settings& bad = read(path, "display=huge\nwindow=200x100\nvsync=maybe\nfps=20\nrender_scale=40\naudio_mode=loud\nupscaler=dlss\n"
                                             "anti_aliasing=fxaa\n"
                                             "audio_buffer=tiny\nvolume=loud\nvolume2=5\nfps=120\n");
    check(bad.fullscreen && bad.window_w == 0 && bad.vsync, "a display, window or vsync it cannot read keeps the default");
    check(bad.render_scale == 100 && !bad.audio_exclusive && bad.audio_buffer == 0 && bad.volume == 100,
          "a render scale below 50, a mode, a buffer or a volume that is no number keeps the default");
    check(bad.fps == 120, "a frame limit below 30 is left out, and a later good one read");
    check(bad.upscaler == player::Settings::Upscaler::kFsr1, "an upscaler it does not know keeps the default, AMD FSR 1");
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
    const player::Settings& caps = read(path, "Display=Window\nVSYNC=Off\nUpscaler=NIS\nAnti_Aliasing=SMAA\nShow_FPS=Top_Right\n"
                                              "Audio_Mode=Exclusive\nAUDIO_DEVICE={0.0.0.00000000}.{ABC-def}\nLanguage=KO\n");
    check(!caps.fullscreen && !caps.vsync && caps.upscaler == player::Settings::Upscaler::kNis, "keys and names in capitals are read");
    check(caps.anti_aliasing == player::Settings::AntiAliasing::kSmaa && caps.show_fps == player::Settings::ShowFps::kTopRight &&
              caps.audio_exclusive,
          "SMAA, Top_Right and Exclusive in capitals");
    check(caps.audio_device == "{0.0.0.00000000}.{ABC-def}", "a device's id keeps its own capitals");
    check(caps.language == "ko", "Language=KO is Korean");
    check(read(path, "anti_aliasing=MSAA4\n").anti_aliasing == player::Settings::AntiAliasing::kCmaa2, "MSAA4 in capitals is CMAA 2 too");
    // A byte order mark at the file's start, as Notepad saves one: the first key still read.
    const player::Settings& marked = read(path, "\xEF\xBB\xBF" "display=window\r\nvolume=30\r\n");
    check(!marked.fullscreen && marked.volume == 30, "a byte order mark before the first key");
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
    // The bar's two ends, and the frame counter's scale and place against the game's buttons in each shape.
    bar_checks();
    counter_look_checks();
    counter_checks();
    // The counter and the notice against the game's own header, buttons and words, in the menus and in a song.
    menus_place_checks();
    overlay_motion_checks();
    // Keyboard play's rules.
    keyboard_play_checks();
    // The display's refreshes as the refresh thread follows them.
    refresh_meter_checks();
    // A press on the handle or the top edge: the bar's or the game's.
    bar_gesture_checks();
    // The sound panel's keys, read and written back.
    sound_settings_checks();
    // The sound panel's layout and the bar's Sound button.
    sound_panel_checks();
    // The broadcast's notices.
    live_notice_checks();
    // A ban's notice that stays.
    ban_hold_checks();
    // The question before quitting's line about a song's record.
    question_checks();
    if (g_failed) {
        std::printf("%d of %d checks FAILED\n", g_failed, g_checks);
        return 1;
    }
    std::printf("%d checks\nALL CHECKS PASSED\n", g_checks);
    return 0;
}
