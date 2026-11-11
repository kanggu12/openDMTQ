// The frame counter's numbers (overlay_win32.cpp shows them in its window): the frames a second and the mean frame time
// between two looks at the count of frames shown (frames.cpp keeps it), and whether the counter is up at all. Apart from
// any window, so that a check (settingstest.cpp) can take it through the game's own stretches: its start before a first
// frame, a loading screen that shows no frame for a while, the game held still for the overlay's question.
#pragma once

namespace player::overlay {

// The frames shown so far and when the last of them was shown (nanoseconds on a steady clock; 0 before the first).
struct FrameCount {
    unsigned long long count = 0;
    long long ns = 0;
};

// The frames a second and the mean frame time from two looks at the count: the frames between the two looks' last
// frames over the time between those frames, which are the display's own moments (a look's own time would add the
// timer's lateness, and a frame either side of a look would make a steady 60 read 58 or 62). No frame since the first
// look: 0 frames a second, no time. A first look without a frame (`before`'s time 0): `fps` and `ms` stay as they are.
void rate(const FrameCount& before, const FrameCount& now, int& fps, float& ms);

// What the counter shows after a look.
struct Reading {
    // Whether it is up: not before the game's first frame, nor while the game is held still for the overlay (the
    // question up, the window minimised), nor after a hold until a frame has been shown again.
    bool shown = false;
    // The frames a second (-1: not measured yet, dashes) and the mean frame time in milliseconds (0: none to give).
    int fps = -1;
    float ms = 0;
};

// The counter's looks at the count, one after another. A rate is measured between two looks that each saw a frame the
// one before had not: never across a stretch with no frame (its stillness would read as one long frame), never across
// a hold. A look that sees no new frame while the game runs says 0 (the game shows nothing new then); the first look
// that sees frames again starts a measure afresh, so that the second look after them gives the true rate again.
class FrameRate {
public:
    // A look at the count now; `held`: the game is held still for the overlay, and the counter hides.
    Reading look(const FrameCount& now, bool held);
    // Whether the next look should come soon: the counter waits for a frame, or for its first measure after one.
    bool waiting() const { return state_ == State::kWaiting || state_ == State::kMeasuring; }

private:
    enum class State {
        // Hidden until the count passes `after_` (the count before the first frame, or at the hold's end).
        kWaiting,
        // Up with dashes: `base_` is the look the first rate is measured from.
        kMeasuring,
        // Up with a rate: `base_` is the last look, which the next rate is measured from.
        kRunning,
        // Up at 0: the last look saw no new frame; `after_` is the count then, and frames past it start a measure.
        kStill,
    };
    State state_ = State::kWaiting;
    FrameCount base_{};
    unsigned long long after_ = 0;
    Reading shown_{};
};

}  // namespace player::overlay
