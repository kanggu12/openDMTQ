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
// Set by a host with more to do on Unity's main thread at each native render call (the desktop player's keyboard play,
// which reaches the game through libil2cpp as the tweaks do): called first, whether or not there are tweaks.
extern void (*g_render_hook)(Thread& thread);

}  // namespace arm32
