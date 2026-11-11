// The frame counter's numbers (frame_rate.h): the frames a second over the last second, and when the counter is up.
#include "frame_rate.h"

#include <algorithm>
#include <cmath>

namespace player::overlay {

namespace {

// A second on the count's clock.
constexpr long long kSecond = 1000000000LL;

}  // namespace

Reading FrameRate::look(const FrameCount& now, long long at, bool held) {
    if (held) {
        // Held still for the overlay: hidden, and waiting from the count as it is now for a frame after the hold (one
        // the game shows meanwhile is no frame after it).
        state_ = State::kWaiting;
        after_ = now.count;
        seen_.clear();
        shown_ = Reading{};
        return shown_;
    }
    switch (state_) {
    case State::kWaiting:
        // A frame past the one it waits from (the first frame of all, or the first after a hold): measured from here,
        // still hidden until a second frame gives a rate.
        if (now.count > after_ && now.ns) {
            state_ = State::kMeasuring;
            first_ = Seen{at, now};
        }
        return shown_;
    case State::kMeasuring:
        if (now.count == first_.count.count) {
            // Still that one frame. A whole second without another: up, at 0 (the game shows nothing new).
            if (at - now.ns >= kSecond) {
                state_ = State::kRunning;
                seen_.assign(1, Seen{at, now});
                shown_ = Reading{true, 0, 0};
            }
            return shown_;
        }
        // A second frame: running, the first rate measured from the first frame.
        state_ = State::kRunning;
        seen_.assign(1, first_);
        break;
    case State::kRunning:
        break;
    }
    seen_.push_back(Seen{at, now});
    // The looks it needs: the newest one at least a second old (the last second's start) and those after it.
    while (seen_.size() > 2 && seen_[1].at <= at - kSecond) seen_.pop_front();
    if (at - now.ns >= kSecond) {
        // A whole second without a frame: 0, no frame time.
        shown_ = Reading{true, 0, 0};
        return shown_;
    }
    // The second's start: the newest look a second old, or the first frame when running for less than a second.
    const Seen& base = seen_.front();
    const unsigned long long frames = now.count - base.count.count;
    // No frame since that look, but one within the second (the look was less than a second ago): what was shown stays.
    if (!frames) return shown_;
    // Between the frames' own moments while they keep coming (a steady rate read exactly, a frame either side of a look
    // making no difference): from the frame the second's first look saw last, to the last frame. Where more than a
    // frame's interval and a half lies between a look and its last frame (the frames slowed or stopped there, or came in
    // a clump), that end of the second is the look itself instead: a second with a few frames early in it reads those
    // few over the whole second, not the pace they came at.
    long long from = base.count.ns ? base.count.ns : base.at, to = now.ns;
    if (to <= from) return shown_;
    const auto interval = [&] { return static_cast<double>(to - from) / static_cast<double>(frames); };
    if (static_cast<double>(base.at - from) > 1.5 * interval()) from = base.at;
    if (to <= from) to = at;
    if (static_cast<double>(at - to) > 1.5 * interval()) to = at;
    const long long span = to - from;
    if (span <= 0) return shown_;
    const double mean = static_cast<double>(span) / 1e6 / static_cast<double>(frames);
    // Three digits at most: the counter's room.
    shown_ = Reading{true, std::min(999, static_cast<int>(std::lround(1000.0 / mean))), static_cast<float>(mean)};
    return shown_;
}

}  // namespace player::overlay
