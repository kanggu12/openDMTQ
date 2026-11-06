// Live view: the game's picture and sound sent to the server while the server's owner has it on for
// this player (see live.cpp).
#pragma once

#include <EGL/egl.h>
#include <cstddef>
#include <jni.h>
#include <string>

namespace arm32 {

// Reads the server's address from the packer's tweaks file and keeps what Java access needs. Call
// where FindClass sees the app's classes (a proxy's JNI_OnLoad). Without an address nothing runs.
void live_load(JavaVM* vm, JNIEnv* env, const std::string& lib_dir);
// Called on the game's render thread just before each eglSwapBuffers of `surface`. Takes next to no
// time unless a picture is due while live view is on.
void live_frame(EGLDisplay display, EGLSurface surface);
// Called when the game destroys an EGL context.
void live_context_destroyed(EGLContext context);
// A source of the game's sound and its format. A game may have several players at once (this one has
// two FMOD outputs, at different rates); they are mixed. Only 16-bit PCM can go into the stream.
void live_audio_source(const void* id, int sample_rate, int channels, int bits);
// A buffer of that source's sound, as it goes to the system. Never blocks: without room in the live
// view's queue it is left out of the broadcast only.
void live_audio(const void* id, const void* data, std::size_t bytes);

}  // namespace arm32
