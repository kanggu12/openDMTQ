// What the player for Windows draws over the game: the bar that slides down from the top edge with full screen and the
// X, its handle at the top centre, the question before quitting, the server's notice, the frame counter, the cursor,
// the pieces as frosted glass over the game's own frame (see overlay_win32.cpp). Its windows and what they do on the UI
// thread; their pictures made on a thread of its own, so that the UI thread, which stamps the keys and the clicks,
// never waits for them.
#pragma once

#include <windows.h>

#include <string>

#include "frame_rate.h"

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
    // The question before quitting is coming (the game is held once its picture is made): what is pressed on the game
    // by keys lets go at once (keyboard play's lane keys).
    void (*question)() = nullptr;
    // A line for the player's log.
    void (*log)(const char* line) = nullptr;
    // The count of frames shown and when the last was (player::frames_shown): the frame counter's numbers, and the
    // game's first picture, which the bar comes down for.
    FrameCount (*frames)() = nullptr;
    // The player's stats are on (ARM32_STATS): every 5 s a line of what the overlay's pictures cost, and a line for
    // each way of the bar down or up (its steps, and the game's frames meanwhile).
    bool stats = false;
    // The display's refresh interval in nanoseconds as the window knows it (0: not known): the pace of a motion's steps
    // where the compositor gives none.
    long long (*refresh_ns)() = nullptr;
};

// Once the frame and the game's window are made; `korean` for the words.
void start(HWND frame, HWND game, const Hooks& hooks, bool korean);
// The server's notice ("title\ndetail"), with the LIVE mark while broadcasting, or the ended one.
void notice(const std::string& text, bool live);
// The mouse moved over the game, at (x, y) of its window, with its button down or not: resting at the very top edge or
// on the handle, with the button up, it brings the bar down.
void pointer_moved(int x, int y, bool pressed);
// A press or a release on the game (the mouse's button, a finger, a pen), with whether anything is still down on it:
// the bar comes from the top edge or the handle only after the pointer moved there again, the game quiet for 1.5 s.
void game_pressed(bool down);
// Whether the game has had no press or release for 1.5 s and nothing is down on it: a finger drawn down from the top
// edge brings the bar only then.
bool game_quiet();
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
// The frame switched between a window and full screen: the bar shows for a few seconds, its chip the other way.
void switched();
// The frame counter in a corner of the game (Settings::ShowFps's order: 0 none, 1 top left, 2 top right, 3 bottom left,
// 4 bottom right; the PC's settings put it at the bottom right unless another is chosen): the frames a second and the
// mean frame time over the last second, from the hooks' count of frames, in a window of its own. Once, after start().
void show_fps(int corner);
// The cursor over the game, pressed or not, at the display's scale.
HCURSOR cursor(bool pressed);
#ifdef OVERLAY_TEST_HOOKS
// The probe's look at every piece in each of its states over a frame of the game (`frame`, a PNG of the game's area's
// size): their pictures as PNGs named after `prefix` with their own transparency (and the counter's and the handle's
// window opacity in theirs), the frame behind read from it as the render thread reads it and blurred and tinted by the
// player's own code, and where each goes (layout.txt). No window is shown. Without `words`, the same pictures without
// their words (the glass under them, for their contrast).
void test_save(const std::wstring& prefix, const std::wstring& frame, bool words);
// The probe's look at the bar's way down and its way up over a frame of the game: what the screen shows at the start,
// a quarter, a half and three quarters of the way's time and at its end, the pieces laid over the frame where a step
// at that moment puts them (the same arithmetic the windows are moved by), the game's top of each as a PNG named after
// `prefix` (motion-plain-...: the handle and the bar; motion-busy-...: the notice and a counter at the top left moving
// with the bar), and each moment's numbers in motion.txt. No window is shown.
void test_motion(const std::wstring& prefix, const std::wstring& frame);
// Windows' scale as the probe wants it drawn (1.5 for 150 %), in place of the display's.
void test_set_dpi(float scale);
#endif

}  // namespace player::overlay
