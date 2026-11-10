// The game's frames in a framebuffer of our own instead of the window's (offscreen.cpp): a computer player's passes over
// the finished picture (desktop/post_pass.cpp: an upscaler from the render scale's size to the window's, anti-aliasing,
// MSAA) need the frame as a texture before it reaches the window. On a phone none of this is asked for, and the bridge's
// framebuffer calls pass through as they always did.
#pragma once

#include <EGL/egl.h>

#include <atomic>

namespace arm32 {

// What a computer player asks for its game's frames, set before the game makes its window's surface (0 and false on a
// phone): whether they are drawn offscreen at all; whether the window's surface keeps the window's own size (an
// upscaler draws the picture to it) instead of the render scale's fixed size (pacing.h's g_window_fixed_size, which
// stays the size the game draws at); and the samples a pixel the offscreen frame is drawn with (MSAA; 0 for one).
extern std::atomic<bool> g_offscreen;
extern std::atomic<bool> g_offscreen_window_size;
extern std::atomic<int> g_offscreen_samples;
// Whether the game's contexts of OpenGL ES 3.0 are made 3.1 instead (a computer player's CMAA 2 runs as compute
// shaders, which 3.1 has; 3.1 keeps everything of 3.0 the game uses). egl_bridge.cpp reads it at eglCreateContext.
extern std::atomic<bool> g_offscreen_es31;

// A finished frame, handed to the player's passes at the swap with the game's context current on its render thread.
struct OffscreenFrame {
    EGLDisplay display;    // the game's display
    EGLSurface surface;    // its window surface, whose default framebuffer (the real framebuffer 0) the picture goes to
    EGLContext context;    // the context the frame was drawn in (GL objects are the context's own)
    unsigned texture;      // the frame as a single-sampled 2D texture (resolved already when drawn with MSAA)
    int width, height;     // its size: the size the game draws at
    int out_width, out_height;  // the window surface's own size
    int samples;           // the samples a pixel it was drawn with (0: one), for the log
};
// The player's passes from the frame to the window surface's framebuffer, which they bind themselves and leave the
// game's GL state as it was; false when nothing was drawn (no program here), and the bridge then copies the frame with
// a plain blit. Null on a phone.
using OffscreenPresent = bool (*)(const OffscreenFrame&);
extern std::atomic<OffscreenPresent> g_offscreen_present;

// The EGL bridge's hooks (egl_bridge.cpp), each a no-op unless g_offscreen is on:
// a window surface made with this config, the one the game's frames are redirected from;
void offscreen_surface_created(EGLDisplay display, EGLConfig config, EGLSurface surface);
// that surface gone;
void offscreen_surface_destroyed(EGLSurface surface);
// before eglMakeCurrent, with the context that is current still current: the offscreen framebuffer bound where the game
// sees 0 is unbound again (the real 0), so that the context keeps nothing of ours while it is not drawing to the window;
void offscreen_before_make_current();
// after a successful eglMakeCurrent: drawing to the redirected surface, the context gets its offscreen framebuffer (made
// the first time) bound wherever the game has 0 bound;
void offscreen_made_current(EGLDisplay display, EGLSurface draw, EGLContext context);
// a context gone, with its framebuffer (its objects went with it);
void offscreen_context_destroyed(EGLContext context);
// eglQuerySurface's width and height of the redirected surface: the size the game draws at; false for anything else;
bool offscreen_query(EGLSurface surface, EGLint attribute, EGLint* value);
// before the swap of the redirected surface: the frame resolved, handed to the passes (or blitted) to the window's own
// framebuffer, and the offscreen framebuffer resized when the size the game draws at changed.
void offscreen_swap(EGLDisplay display, EGLSurface surface);

}  // namespace arm32
