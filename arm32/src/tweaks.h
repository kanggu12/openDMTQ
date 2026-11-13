// Tweaks: static int fields of IL2CPP classes set from outside the game (see tweaks.cpp).
#pragma once

#include "framerate.h"
#include "guest.h"

namespace arm32 {

// Reads the tweaks file from the app's library folder, if the packer put one there.
void tweaks_load(const std::string& lib_dir);
// Tells which guest library a proxy loaded (libil2cpp.so is the one tweaks need).
void tweaks_library_loaded(const std::string& name, gaddr handle);
// Called on Unity's main thread before each native render call; applies the tweaks when due.
void tweaks_render(Thread& thread);

}  // namespace arm32

// The desktop player's own work on Unity's main thread at each native render call (keyboard play, which reaches the game
// through libil2cpp as the tweaks do), set by that host and called first, whether or not there are tweaks. A phone's
// runtime has no such host: its build leaves the hook out and keeps every line of this file and tweaks.cpp where it
// was, so that its library is the same as before and a server keeps the app it made with it.
#ifndef __ANDROID__
namespace arm32 {
extern void (*g_render_hook)(Thread& thread);
}  // namespace arm32
#define ARM32_RENDER_HOOK(th) if (::arm32::g_render_hook) ::arm32::g_render_hook(th);
#else
#define ARM32_RENDER_HOOK(th)
#endif
