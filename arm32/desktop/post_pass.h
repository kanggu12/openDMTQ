// The player's passes over the game's finished frame (post_pass.cpp): anti-aliasing and an upscaler, from the frame the
// runtime's bridge has the game draw offscreen (arm32/src/offscreen.h) to the window.
#pragma once

namespace player {

// What the player asks of the game's frames, from the PC's settings (player.h): its upscaler (0 the plain stretch,
// 1 AMD FSR 1, 2 NVIDIA NIS), its anti-aliasing (the Settings::AntiAliasing order: 0 off, 1 CMAA 2, 2 SMAA, 3 to 5
// MSAA 2x, 4x, 8x) and its render scale in percent. Sets the bridge's offscreen switches (offscreen.h) and hands it
// the passes; nothing changes from a start without it when neither is asked for. Called once, before the game makes
// its window's surface.
void post_configure(int upscaler, int anti_aliasing, int render_scale);

}  // namespace player
