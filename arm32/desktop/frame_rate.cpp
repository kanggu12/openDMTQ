// The frame counter's numbers (frame_rate.h): the frames a second between two looks at the count, and when the counter
// is up.
#include "frame_rate.h"

#include <algorithm>
#include <cmath>

namespace player::overlay {

void rate(const FrameCount& before, const FrameCount& now, int& fps, float& ms) {
    // No frame at the first look: nothing to measure from, and what was shown stays.
    if (!before.ns) return;
    const unsigned long long frames = now.count - before.count;
    const long long span = now.ns - before.ns;
    if (!frames || span <= 0) {
        // No frame between the looks: the game showed nothing new.
        fps = 0;
        ms = 0;
        return;
    }
    // The mean time between the frames, in milliseconds, and its frames a second.
    const double mean = static_cast<double>(span) / 1e6 / static_cast<double>(frames);
    // Three digits at most: the counter's room.
    fps = std::min(999, static_cast<int>(std::lround(1000.0 / mean)));
    ms = static_cast<float>(mean);
}

Reading FrameRate::look(const FrameCount& now, bool held) {
    if (held) {
        // Held still for the overlay: hidden, and waiting from the count as it is now for a frame after the hold (one
        // the game shows meanwhile is no frame after it).
        state_ = State::kWaiting;
        after_ = now.count;
        shown_ = Reading{};
        return shown_;
    }
    switch (state_) {
    case State::kWaiting:
        // A frame past the one it waits from (the first frame of all, or the first after a hold): the first measure
        // starts from it, still hidden until it gives a rate.
        if (now.count > after_ && now.ns) {
            state_ = State::kMeasuring;
            base_ = now;
        }
        break;
    case State::kStill:
        // Frames again after a look that saw none: a measure afresh from here (the stillness is no long frame), dashes
        // meanwhile rather than the 0 the game no longer shows.
        if (now.count > after_) {
            state_ = State::kMeasuring;
            base_ = now;
            shown_ = Reading{true, -1, 0};
        }
        break;
    case State::kMeasuring:
    case State::kRunning:
        if (now.count == base_.count) {
            // No frame since the last look while the game runs (a loading screen): 0, and frames after this count
            // start a new measure.
            state_ = State::kStill;
            after_ = now.count;
            shown_ = Reading{true, 0, 0};
            break;
        }
        // Frames since the last look: their rate, shown, and measured on from this look.
        {
            int fps = shown_.fps;
            float ms = shown_.ms;
            rate(base_, now, fps, ms);
            shown_ = Reading{true, fps, ms};
        }
        state_ = State::kRunning;
        base_ = now;
        break;
    }
    return shown_;
}

}  // namespace player::overlay
