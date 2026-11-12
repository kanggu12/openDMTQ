// The player's PC settings file (settings.cpp), as the PC client writes it: each key read, a value it cannot read or a
// key it does not know leaving the default, a volume out of range held to 0 to 100, MSAA of earlier launchers read as
// CMAA 2, notes, Windows' line ends, a byte order mark and capitals taken in their stride, no file at all the
// defaults. Then the numbers of the frame counter that one of the settings shows (frame_rate.cpp): its looks at the
// count of frames through the game's start, a stretch with no frame, frames again and a hold. Then the size the overlay
// over the game is drawn at and the smallest game area the window holds (overlay_scale.h), over Windows' scales and the
// game's sizes, with the size of the overlay's handle, which keeps clear of the game's header at every size. Then the
// overlay's bar on its way down and up (overlay_motion.h): its pace, a turn back midway, Windows' animations off, the
// rows of it in sight, and the handle and the pieces at the top that move with it. Prints ALL CHECKS PASSED when every
// check held.
#include "frame_rate.h"
#include "overlay_motion.h"
#include "overlay_scale.h"
#include "player.h"

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
    check(handle_scale_for(720) == 1.0f && handle_scale_for(1080) == 1.5f && handle_scale_for(2160) == 3.0f,
          "the handle at 720, 1080 and 2160 lines: the game's own scale, 1, 1.5 and 3");
    check(handle_scale_for(720) == scale_for(720, 1.5f) && handle_scale_for(1080) == scale_for(1080, 1.5f) && handle_scale_for(2160) == scale_for(2160, 1.5f),
          "1280x720, 1920x1080 and 4K at 150 %: the handle at the scale of the rest of the overlay");
    // Below the other pieces' floor the handle still follows the game: it is never pressed, and so stays in proportion.
    check(handle_scale_for(405) == 0.5625f && scale_for(405, 1.5f) == 0.75f, "the smallest area at 150 %: the handle at the game's 0.5625, not at the floor's 0.75");
    check(handle_scale_for(270) == 0.375f && handle_scale_for(270) < scale_for(270, 1.0f), "the smallest area at 100 %: the game's 0.375, below the floor's 0.5");
    // The tab at 720 lines: below the header's empty rows it keeps within the room the header leaves beside the centre,
    // at rest and deeper with the pointer on it (deeper, never wider).
    check(tab_half(kHeaderFreeRows) <= kHeaderFreeHalf, "the tab keeps within 12 of the centre from the header's first row down, at 720 lines");
    check(tab_half(kTabTall) < tab_half(kHeaderFreeRows) && tab_half(kTabTallLit) < tab_half(kTabTall) && tab_half(kTabTallLit) > 0,
          "the tab narrows toward its foot, at rest and lit, and still has a foot");
    check(tab_half(0) * 2 == player::overlay::kTabTop, "the tab is as wide as its top at the game's edge");
    // Every area the window can hold, in pixels at the handle's scale: the rail and its shade stay within the header's
    // empty rows, and the tab below them within the header's room.
    bool rail_clear = true, tab_clear = true, rail_there = true;
    for (int h = kLeastAreaH; h <= 2160; ++h) {
        const float k = handle_scale_for(h);
        // The header's empty rows and its room beside the centre, at this size.
        const float rows = kHeaderFreeRows * k, half = kHeaderFreeHalf * k;
        rail_clear = rail_clear && static_cast<float>(rail_rows(k) + shade_rows(k)) <= rows;
        rail_there = rail_there && rail_rows(k) >= 1 && shade_rows(k) >= 0;
        tab_clear = tab_clear && tab_half(kHeaderFreeRows) * k <= half;
    }
    check(rail_clear, "every area from 270 to 2160 lines: the rail and its shade lie within the header's empty rows");
    check(rail_there, "and the rail is at least a pixel at every size");
    check(tab_clear, "and the tab below them keeps within the header's room beside the centre");
    check(rail_rows(1.0f) == 2 && shade_rows(1.0f) == 1 && rail_rows(1.5f) == 3 && rail_rows(3.0f) == 6 && shade_rows(3.0f) == 3 && shade_rows(0.375f) == 0,
          "the rail 2 rows and its shade 1 at 720 lines, 6 and 3 at 4K, the shade none in the smallest window");
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
    // The handle's size, and the bar's way down and up.
    handle_size_checks();
    overlay_motion_checks();
    if (g_failed) {
        std::printf("%d of %d checks FAILED\n", g_failed, g_checks);
        return 1;
    }
    std::printf("%d checks\nALL CHECKS PASSED\n", g_checks);
    return 0;
}
