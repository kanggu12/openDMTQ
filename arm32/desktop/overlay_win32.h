// What the player for Windows draws over the game: the bar at the top edge with full screen and the X, the question
// before quitting, the server's notice, the cursor (see overlay_win32.cpp). All of it on the UI thread.
#pragma once

#include <windows.h>

#include <string>

namespace player::overlay {

// What the bar and the question do, which the window owns.
struct Hooks {
    // The bar's full screen chip: full screen and back.
    void (*toggle_fullscreen)() = nullptr;
    // The question's Quit the game.
    void (*quit)() = nullptr;
    // Whether the frame is in full screen now: the chip's icon shows the other way.
    bool (*fullscreen)() = nullptr;
    // The game held still (true: a question is up, or the window is minimised) or let go on (false).
    void (*hold)(bool) = nullptr;
};

// Once the frame and the game's window are made; `korean` for the words.
void start(HWND frame, HWND game, const Hooks& hooks, bool korean);
// The server's notice ("title\ndetail"), with the LIVE mark while broadcasting, or the ended one.
void notice(const std::string& text, bool live);
// The mouse moved over the game, `y` pixels from its top, with its button down or not: at the very top edge, with the
// button up, the bar shows.
void pointer_moved(int y, bool pressed);
// A finger drawn down from the game's top edge: the bar shows for a few seconds.
void show_bar();
// Whether the question before quitting is up (the game is held still and the keys are the question's meanwhile).
bool asking();
// The question before quitting (the bar's X, the window's own close): Keep playing first, so that Enter at once goes on.
void ask_quit();
// The game's window was minimised (true) or came back (false): minimised, the game holds still until it is back.
void minimised(bool now);
// A key while the question is up: Left, Right and Tab move the choice, Enter takes it, Esc keeps playing. True when it
// was the question's (every key is, while it is up).
bool ask_key(UINT vk);
// The game's area moved or changed size: everything shown follows it.
void place();
// The frames shown so far and when the last of them was shown (nanoseconds on a steady clock; 0 before the first).
struct FrameCount {
    unsigned long long count = 0;
    long long ns = 0;
};
// The frame counter in a corner of the game (Settings::ShowFps's order: 0 none, 1 top left, 2 top right, 3 bottom left,
// 4 bottom right): the frames a second and the mean frame time over the last half second, from `frames`
// (player::frames_shown), drawn twice a second in a window of its own. Once, after start().
void show_fps(int corner, FrameCount (*frames)());
// The counter's numbers from two looks at the count (overlay_win32.cpp says how); no window needed, so a check can
// call it.
void rate(const FrameCount& before, const FrameCount& now, int& fps, float& ms);
// The cursor over the game, pressed or not, at the display's scale.
HCURSOR cursor(bool pressed);
#ifdef OVERLAY_TEST_HOOKS
// The probe's look at the bar, the question and the notice: their pictures as PNGs named after `prefix`, with no window
// shown.
void test_save(const std::wstring& prefix);
// The frame counter's picture alone, at the game area's scale now, showing these numbers.
void test_save_fps(const std::wstring& path, int fps, float ms);
// Windows' scale as the probe wants it drawn (1.5 for 150 %), in place of the display's.
void test_set_dpi(float scale);
#endif

}  // namespace player::overlay
