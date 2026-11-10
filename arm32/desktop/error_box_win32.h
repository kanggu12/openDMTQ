// The player for Windows' box for an error before the game came up (error_box_win32.cpp): the launcher's own dialog in a
// window of its own, or Windows' message box where that cannot be made.
#pragma once

#include <string>

namespace player::overlay {

// An error before the game came up, in the launcher's own dialog as a window of its own: `message` the question's line,
// `detail` what it means. Returns when the player answers it (its button, Enter, Space or Esc). Without GDI+ or the
// window, Windows' own message box says the same.
void error_box(const std::string& message, const std::string& detail, bool korean);
#ifdef OVERLAY_TEST_HOOKS
// The error box's pictures (as it is, under the pointer, pressed) at a scale, as PNGs named after `prefix`.
void test_save_error_box(const std::wstring& prefix, const std::string& message, const std::string& detail,
                         bool korean, float scale);
#endif

}  // namespace player::overlay
