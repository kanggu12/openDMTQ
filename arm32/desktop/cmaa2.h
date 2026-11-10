// Intel's Conservative Morphological Anti-Aliasing 2 over the game's frame (cmaa2.cpp), as compute shaders of OpenGL
// ES 3.1 in the game's context, for the player's passes (post_pass.cpp).
#pragma once

namespace player {

// A context's CMAA 2: its programs, and its working buffer and edge picture for the size last asked.
struct Cmaa2;

// CMAA 2's programs in the current context (OpenGL ES 3.1 or later); null when they do not build, said in the log.
// The program in use changes (the caller has the game's saved).
Cmaa2* cmaa2_make();

// The frame `source` (a texture of `width` x `height`) anti-aliased into `out`, an RGBA8 texture of the same size
// made with glTexStorage2D that already holds a copy of the frame (CMAA 2 writes only the pixels it changes). The
// compute state it binds (its buffer, its images, the indirect dispatch buffer) is put back as it was; the program and
// texture unit 0 the caller saves. False when its buffers cannot be made at that size (nothing written).
bool cmaa2_run(Cmaa2* c, unsigned source, unsigned out, int width, int height);

// The context the objects were made in has gone (its objects with it): only the memory goes.
void cmaa2_forget(Cmaa2* c);

}  // namespace player
