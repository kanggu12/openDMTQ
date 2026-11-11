// The frame counter's numbers (overlay_win32.cpp shows them in its window): the frames a second and the mean frame time
// over the last second, from looks at the count of frames shown (frames.cpp keeps it), and whether the counter is up at
// all. Apart from any window, so that a check (settingstest.cpp) can take it through the game's own stretches: its start
// before a first frame, a loading screen that shows a frame now and then or none for a while, the game held still for
// the overlay's question.
#pragma once

#include <deque>

namespace player::overlay {

// The frames shown so far and when the last of them was shown (nanoseconds on a steady clock; 0 before the first).
struct FrameCount {
    unsigned long long count = 0;
    long long ns = 0;
};

// What the counter shows after a look.
struct Reading {
    // Whether it is up: not before the game's first frame, nor while the game is held still for the overlay (the
    // question up, the window minimised), nor after a hold until frames come again and give a rate.
    bool shown = false;
    // The frames a second (-1: none to give yet) and the mean frame time in milliseconds (0: none to give).
    int fps = -1;
    float ms = 0;
};

// The counter's looks at the count, one after another, each at a moment of the count's own clock. What it shows is the
// rate over the last second: the frames shown in it over the time they took, measured between the frames' own moments
// where frames keep coming (a steady 60 reads 60, never 59 and 61 in turn), and to the look itself where they slowed or
// stopped (a few frames early in the second read as a few frames a second); 0 only once a whole second has passed
// without a frame. A loading screen that shows a frame every few hundred milliseconds reads its few frames a second, never 0 in
// turn with them. Never across a hold: after one, and after the start, it measures from the first frame that came, and
// shows once there are two.
class FrameRate {
public:
    // A look at the count now, at `at` (nanoseconds on the count's clock); `held`: the game is held still for the
    // overlay, and the counter hides.
    Reading look(const FrameCount& now, long long at, bool held);
    // Whether the next look should come soon: the counter waits for a frame, or for a second one after it.
    bool waiting() const { return state_ != State::kRunning; }

private:
    enum class State {
        // Hidden until the count passes `after_` (the count before the first frame, or at the hold's end).
        kWaiting,
        // Hidden: `first_` is the first frame after a start or a hold, which the first rate is measured from.
        kMeasuring,
        // Up: each look's rate over the last second.
        kRunning,
    };
    // A look: when it was, and the count then.
    struct Seen {
        long long at;
        FrameCount count;
    };
    State state_ = State::kWaiting;
    unsigned long long after_ = 0;
    // The first frame after a start or a hold, and when the look that saw it was: no rate reaches back past it.
    Seen first_{};
    // The looks while running, oldest first, kept back to a little more than a second.
    std::deque<Seen> seen_;
    Reading shown_{};
};

}  // namespace player::overlay
