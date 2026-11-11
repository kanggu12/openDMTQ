// What the overlay's frosted glass shows behind it (overlay_win32.cpp): the game's own frame, read on the render thread
// at a swap (glass_capture.cpp). The overlay is layered windows drawn on the CPU, which cannot see the game's picture
// under them; so while a piece of glass is up, the overlay names the rectangles of the game's window behind its pieces,
// and the render thread reads those rectangles of the frame as it goes to the window, at a quarter of their size, at
// most 20 times a second, without waiting for the GPU. The overlay blurs and tints them itself.
#pragma once

#include <cstdint>
#include <memory>
#include <vector>

namespace player::glass {

// A rectangle of the game's window, in its pixels from its top left.
struct Rect {
    int x = 0, y = 0, w = 0, h = 0;
};

// One wanted rectangle as the render thread read it: `rect` in the window's pixels, its picture a quarter of that each
// way (`w` by `h`), RGBA bytes, its top row first.
struct Shot {
    Rect rect;
    int w = 0, h = 0;
    std::vector<std::uint8_t> rgba;
};

// The overlay's thread: the rectangles it wants read now, in a game's window of `area_w` by `area_h` pixels (each made
// whole multiples of 4 within the window here). None: the render thread reads nothing and costs nothing.
void want(const std::vector<Rect>& rects, int area_w, int area_h);
// The overlay's thread: the last read's shots, when a read newer than `generation` (which it moves on) has come; false
// when none has. Shared, not copied: the render thread makes a new list for each read.
bool take(unsigned& generation, std::shared_ptr<const std::vector<Shot>>& out);
// How many reads the render thread has handed over so far (the overlay waits for one after asking).
unsigned generation();
// Whether the render thread cannot read the frame here (OpenGL ES 2, a multisampled window, a read it could not set
// up): no read will come, and the overlay waits for none.
bool refused();

// A rectangle grown by `by` on every side, its edges on whole multiples of 4, kept within an area of `w` by `h`: what a
// request asks for, so that a quarter's pixel is four of the window's exactly.
Rect aligned(const Rect& r, int by, int w, int h);

}  // namespace player::glass
