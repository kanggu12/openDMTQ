// What the player for Windows draws over the game: the server's notice, the menu and its button, the cursor (see
// overlay_win32.cpp). All of it on the UI thread.
#pragma once

#include <windows.h>

#include <string>

namespace player::overlay {

// What the menu does, which the window owns.
struct Hooks {
    void (*toggle_fullscreen)() = nullptr;
    void (*quit)() = nullptr;
    bool (*fullscreen)() = nullptr;
    // The menu came up (true) or went (false): the game is held still meanwhile.
    void (*shown)(bool) = nullptr;
};

// Once the frame and the game's window are made; `korean` for the menu's words.
void start(HWND frame, HWND game, const Hooks& hooks, bool korean);
// The server's notice ("title\ndetail"), with the LIVE mark while broadcasting, or the ended one.
void notice(const std::string& text, bool live);
// The mouse moved over the game, `y` pixels from its top, with its button down or not: near the top, and not while
// playing, the menu's button shows for a while.
void pointer_moved(int y, bool pressed);
bool menu_open();
void open_menu();
void close_menu();
void toggle_menu();
// The game's window was minimised (true) or came back (false): minimised, the game holds still and the menu waits for
// its return.
void minimised(bool now);
// A key while the menu is open: the arrows choose a row, Enter or Space does it, Esc closes. True when it was the menu's.
bool menu_key(UINT vk);
// The game's area moved or changed size: everything shown follows it.
void place();
// The cursor over the game, pressed or not, at the display's scale.
HCURSOR cursor(bool pressed);
// An error before the game came up, in the launcher's own dialog as a window of its own: `message` the question's line,
// `detail` what it means. Returns when the player answers it (its button, Enter, Space or Esc).
void error_box(const std::string& message, const std::string& detail, bool korean);
#ifdef OVERLAY_TEST_HOOKS
// The probe's look at the notice and the menu: their pictures as PNGs named after `prefix`.
void test_save(const std::wstring& prefix);
// The error box's pictures (as it is, under the pointer, pressed) at a scale, as PNGs named after `prefix`.
void test_save_error_box(const std::wstring& prefix, const std::string& message, const std::string& detail,
                         bool korean, float scale);
#endif

}  // namespace player::overlay
