// The player's passes over the game's finished frame, on the game's render thread at each swap, in its own context with
// every piece of its GL state the passes touch saved before and put back after (as the broadcast's capture does,
// live_capture.cpp). The runtime's bridge has the game draw into a framebuffer of ours (arm32/src/offscreen.h) and hands
// the frame here as a texture; what reaches the window's own framebuffer:
//
//   anti-aliasing over the finished picture, at the size the game draws at:
//     CMAA 2   Intel's Conservative Morphological Anti-Aliasing 2 (cmaa2.cpp), compute shaders of OpenGL ES 3.1
//     SMAA     SMAA 1x at its High preset: edges by luma, blending weights, neighbourhood blending (three draws), the
//              reference shader itself (third_party/smaa/SMAA.hlsl, which has a GLSL path) with its area and search
//              textures
//   then, below 100 %, the upscaler to the window's size:
//     AMD FSR 1      EASU (edge-adaptive upsampling), then RCAS (sharpening) at AMD's sample's 0.25 stops
//     NVIDIA NIS     NVScaler with its coefficient textures, at the SDK's default sharpness of 50 %
//     (the plain stretch is no pass: the window's surface keeps the render scale's fixed size, and ANGLE stretches it)
//   or a plain copy when the picture is already the window's size.
//
// The programs are made once per context, at the first frame (before the title, in the game's first second, when no
// frame of a song can stutter for it), and what that took is logged; what the passes take a frame on this thread is
// logged every 600 frames (PLAYER_POST_FINISH=1 waits for the GPU at both ends, to count its work too). A program that
// does not compile or link leaves its pass out, said in the log: the bridge then copies the frame plainly.
#include "post_pass.h"

#include "cmaa2.h"
#include "offscreen.h"
#include "player.h"

#include "host.h"

#include <EGL/egl.h>
#include <GLES3/gl31.h>
// EXT_disjoint_timer_query's names, for the GPU times in the stats.
#include <GLES2/gl2ext.h>

#include <atomic>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <initializer_list>
#include <string>
#include <vector>

// NVIDIA's own configuration of NIS: its coefficient tables and NVScalerUpdateConfig, which sets the scaler's constants
// from a sharpness (the SDK's header as it is, MIT).
#include <nis/NIS_Config.h>
// SMAA's precomputed area and search textures (the reference's headers as they are, MIT).
#include <smaa/AreaTex.h>
#include <smaa/SearchTex.h>

namespace player {

namespace {

// What the settings asked for (post_configure), read at every frame.
std::atomic<int> g_upscaler{0};      // 0 the plain stretch, 1 AMD FSR 1, 2 NVIDIA NIS
std::atomic<int> g_anti_aliasing{0};  // Settings::AntiAliasing's order
// RCAS's sharpness in stops (AMD's sample's default) and NIS's sharpness (the SDK's samples' default, 50 %).
constexpr float kRcasStops = 0.25f;
constexpr float kNisSharpness = 0.5f;

// The monotonic clock in nanoseconds, for the costs.
std::int64_t now_ns() {
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<std::int64_t>(ts.tv_sec) * 1000000000 + ts.tv_nsec;
}

// ---- the host's GL entry points, looked up once

struct Gl {
    PFNGLGETINTEGERVPROC get_integer;
    PFNGLGETINTEGERI_VPROC get_integer_i;
    PFNGLGETBOOLEANVPROC get_boolean;
    PFNGLGETFLOATVPROC get_float;
    PFNGLISENABLEDPROC is_enabled;
    PFNGLENABLEPROC enable;
    PFNGLDISABLEPROC disable;
    PFNGLCOLORMASKPROC color_mask;
    PFNGLVIEWPORTPROC viewport;
    PFNGLCLEARCOLORPROC clear_color;
    PFNGLCLEARPROC clear;
    PFNGLGENTEXTURESPROC gen_textures;
    PFNGLDELETETEXTURESPROC delete_textures;
    PFNGLBINDTEXTUREPROC bind_texture;
    PFNGLACTIVETEXTUREPROC active_texture;
    PFNGLTEXSTORAGE2DPROC tex_storage;
    PFNGLTEXSUBIMAGE2DPROC tex_sub_image;
    PFNGLTEXPARAMETERIPROC tex_parameter;
    PFNGLPIXELSTOREIPROC pixel_store;
    PFNGLBINDSAMPLERPROC bind_sampler;
    PFNGLGENFRAMEBUFFERSPROC gen_framebuffers;
    PFNGLDELETEFRAMEBUFFERSPROC delete_framebuffers;
    PFNGLBINDFRAMEBUFFERPROC bind_framebuffer;
    PFNGLFRAMEBUFFERTEXTURE2DPROC framebuffer_texture;
    PFNGLCHECKFRAMEBUFFERSTATUSPROC check_framebuffer;
    PFNGLBLITFRAMEBUFFERPROC blit;
    PFNGLCREATESHADERPROC create_shader;
    PFNGLSHADERSOURCEPROC shader_source;
    PFNGLCOMPILESHADERPROC compile_shader;
    PFNGLGETSHADERIVPROC get_shader;
    PFNGLGETSHADERINFOLOGPROC shader_log;
    PFNGLDELETESHADERPROC delete_shader;
    PFNGLCREATEPROGRAMPROC create_program;
    PFNGLATTACHSHADERPROC attach_shader;
    PFNGLLINKPROGRAMPROC link_program;
    PFNGLGETPROGRAMIVPROC get_program;
    PFNGLGETPROGRAMINFOLOGPROC program_log;
    PFNGLDELETEPROGRAMPROC delete_program;
    PFNGLUSEPROGRAMPROC use_program;
    PFNGLGETUNIFORMLOCATIONPROC uniform_location;
    PFNGLUNIFORM1IPROC uniform_int;
    PFNGLUNIFORM1FPROC uniform_float;
    PFNGLUNIFORM4FPROC uniform_vec4;
    PFNGLUNIFORM4FVPROC uniform_vec4s;
    PFNGLGENVERTEXARRAYSPROC gen_vertex_arrays;
    PFNGLBINDVERTEXARRAYPROC bind_vertex_array;
    PFNGLDRAWARRAYSPROC draw_arrays;
    PFNGLBINDBUFFERPROC bind_buffer;
    PFNGLFINISHPROC finish;
    bool ok = false;
};

template <class T>
void look_up(T& out, const char* name, bool& ok) {
    out = reinterpret_cast<T>(arm32::gl_proc(name));
    if (!out) ok = false;
}

const Gl& gl() {
    static const Gl g = [] {
        Gl x{};
        bool ok = true;
        look_up(x.get_integer, "glGetIntegerv", ok);
        look_up(x.get_integer_i, "glGetIntegeri_v", ok);
        look_up(x.get_boolean, "glGetBooleanv", ok);
        look_up(x.get_float, "glGetFloatv", ok);
        look_up(x.is_enabled, "glIsEnabled", ok);
        look_up(x.enable, "glEnable", ok);
        look_up(x.disable, "glDisable", ok);
        look_up(x.color_mask, "glColorMask", ok);
        look_up(x.viewport, "glViewport", ok);
        look_up(x.clear_color, "glClearColor", ok);
        look_up(x.clear, "glClear", ok);
        look_up(x.gen_textures, "glGenTextures", ok);
        look_up(x.delete_textures, "glDeleteTextures", ok);
        look_up(x.bind_texture, "glBindTexture", ok);
        look_up(x.active_texture, "glActiveTexture", ok);
        look_up(x.tex_storage, "glTexStorage2D", ok);
        look_up(x.tex_sub_image, "glTexSubImage2D", ok);
        look_up(x.tex_parameter, "glTexParameteri", ok);
        look_up(x.pixel_store, "glPixelStorei", ok);
        look_up(x.bind_sampler, "glBindSampler", ok);
        look_up(x.gen_framebuffers, "glGenFramebuffers", ok);
        look_up(x.delete_framebuffers, "glDeleteFramebuffers", ok);
        look_up(x.bind_framebuffer, "glBindFramebuffer", ok);
        look_up(x.framebuffer_texture, "glFramebufferTexture2D", ok);
        look_up(x.check_framebuffer, "glCheckFramebufferStatus", ok);
        look_up(x.blit, "glBlitFramebuffer", ok);
        look_up(x.create_shader, "glCreateShader", ok);
        look_up(x.shader_source, "glShaderSource", ok);
        look_up(x.compile_shader, "glCompileShader", ok);
        look_up(x.get_shader, "glGetShaderiv", ok);
        look_up(x.shader_log, "glGetShaderInfoLog", ok);
        look_up(x.delete_shader, "glDeleteShader", ok);
        look_up(x.create_program, "glCreateProgram", ok);
        look_up(x.attach_shader, "glAttachShader", ok);
        look_up(x.link_program, "glLinkProgram", ok);
        look_up(x.get_program, "glGetProgramiv", ok);
        look_up(x.program_log, "glGetProgramInfoLog", ok);
        look_up(x.delete_program, "glDeleteProgram", ok);
        look_up(x.use_program, "glUseProgram", ok);
        look_up(x.uniform_location, "glGetUniformLocation", ok);
        look_up(x.uniform_int, "glUniform1i", ok);
        look_up(x.uniform_float, "glUniform1f", ok);
        look_up(x.uniform_vec4, "glUniform4f", ok);
        look_up(x.uniform_vec4s, "glUniform4fv", ok);
        look_up(x.gen_vertex_arrays, "glGenVertexArrays", ok);
        look_up(x.bind_vertex_array, "glBindVertexArray", ok);
        look_up(x.draw_arrays, "glDrawArrays", ok);
        look_up(x.bind_buffer, "glBindBuffer", ok);
        look_up(x.finish, "glFinish", ok);
        x.ok = ok;
        return x;
    }();
    return g;
}

// ---- the game's state the passes touch, saved before them and put back after

// The texture units the passes bind: the frame and up to two tables (SMAA's area and search textures, NIS's two
// coefficient tables).
constexpr int kUnits = 3;
// The switches a full-screen draw has to have off, and dither, which a plain copy should not add.
constexpr GLenum kSwitches[] = {GL_SCISSOR_TEST, GL_BLEND, GL_DEPTH_TEST, GL_STENCIL_TEST, GL_CULL_FACE, GL_RASTERIZER_DISCARD,
                                GL_SAMPLE_ALPHA_TO_COVERAGE, GL_SAMPLE_COVERAGE, GL_DITHER, GL_POLYGON_OFFSET_FILL};
constexpr int kSwitchCount = static_cast<int>(sizeof kSwitches / sizeof kSwitches[0]);

struct Saved {
    GLint read = 0, draw = 0, program = 0, active = 0, vertex_array = 0, array_buffer = 0;
    GLint textures[kUnits] = {}, samplers[kUnits] = {};
    GLint viewport[4] = {0, 0, 0, 0};
    GLfloat clear[4] = {0, 0, 0, 0};
    GLboolean mask[4] = {GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE};
    GLboolean enabled[kSwitchCount] = {};
};

void save_state(const Gl& g, Saved& s) {
    g.get_integer(GL_READ_FRAMEBUFFER_BINDING, &s.read);
    g.get_integer(GL_DRAW_FRAMEBUFFER_BINDING, &s.draw);
    g.get_integer(GL_CURRENT_PROGRAM, &s.program);
    g.get_integer(GL_ACTIVE_TEXTURE, &s.active);
    for (int u = 0; u < kUnits; ++u) {
        // Each unit's 2D texture and sampler object, the units the passes bind.
        g.active_texture(GL_TEXTURE0 + static_cast<GLenum>(u));
        g.get_integer(GL_TEXTURE_BINDING_2D, &s.textures[u]);
        g.get_integer(GL_SAMPLER_BINDING, &s.samplers[u]);
    }
    g.get_integer(GL_VERTEX_ARRAY_BINDING, &s.vertex_array);
    g.get_integer(GL_ARRAY_BUFFER_BINDING, &s.array_buffer);
    g.get_integer(GL_VIEWPORT, s.viewport);
    g.get_float(GL_COLOR_CLEAR_VALUE, s.clear);
    g.get_boolean(GL_COLOR_WRITEMASK, s.mask);
    for (int i = 0; i < kSwitchCount; ++i) s.enabled[i] = g.is_enabled(kSwitches[i]);
}

void restore_state(const Gl& g, const Saved& s) {
    for (int i = 0; i < kSwitchCount; ++i) {
        if (s.enabled[i]) g.enable(kSwitches[i]);
        else g.disable(kSwitches[i]);
    }
    g.color_mask(s.mask[0], s.mask[1], s.mask[2], s.mask[3]);
    g.clear_color(s.clear[0], s.clear[1], s.clear[2], s.clear[3]);
    g.viewport(s.viewport[0], s.viewport[1], s.viewport[2], s.viewport[3]);
    g.bind_vertex_array(static_cast<GLuint>(s.vertex_array));
    g.bind_buffer(GL_ARRAY_BUFFER, static_cast<GLuint>(s.array_buffer));
    for (int u = kUnits - 1; u >= 0; --u) {
        g.active_texture(GL_TEXTURE0 + static_cast<GLenum>(u));
        g.bind_texture(GL_TEXTURE_2D, static_cast<GLuint>(s.textures[u]));
        g.bind_sampler(static_cast<GLuint>(u), static_cast<GLuint>(s.samplers[u]));
    }
    g.active_texture(static_cast<GLenum>(s.active));
    g.use_program(static_cast<GLuint>(s.program));
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, static_cast<GLuint>(s.read));
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, static_cast<GLuint>(s.draw));
}

// ---- the shaders

// One triangle over the whole target from the vertex's number alone (no buffers), and its texture coordinate.
const char* kVertex = R"(#version 300 es
out vec2 texcoord;
void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    texcoord = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
)";

// AMD FidelityFX Super Resolution 1: EASU, the upscaling.
const char* kEasu = R"(#version 300 es
// AMD FidelityFX SUPER RESOLUTION [FSR 1] - v1.20210629, EASU (FsrEasuF, its 32-bit version), from ffx_fsr1.h and the
// helpers of ffx_a.h it uses.
//
// Copyright (c) 2021 Advanced Micro Devices, Inc. All rights reserved.
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files(the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and / or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions :
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.
//
// Ported to a GLSL ES 3.00 fragment shader for OpenDMTQ: the twelve taps are read with texelFetch, clamped to the
// picture's edge as the reference's clamped gather4 reads them; the weights, the direction and the dering are the
// reference's, line for line.
precision highp float;
precision highp int;
uniform highp sampler2D source;
// FsrEasuCon's con0: the output pixel to the input's (scale, then offset).
uniform vec4 con0;
out vec4 color;
float APrxLoRcpF1(float a) { return uintBitsToFloat(0x7ef07ebbu - floatBitsToUint(a)); }
float APrxLoRsqF1(float a) { return uintBitsToFloat(0x5f347d74u - (floatBitsToUint(a) >> 1u)); }
vec3 AMin3F3(vec3 x, vec3 y, vec3 z) { return min(x, min(y, z)); }
vec3 AMax3F3(vec3 x, vec3 y, vec3 z) { return max(x, max(y, z)); }
ivec2 last;
vec3 at(ivec2 p) { return texelFetch(source, clamp(p, ivec2(0), last), 0).rgb; }
void FsrEasuTapF(inout vec3 aC, inout float aW, vec2 off, vec2 dir, vec2 len, float lob, float clp, vec3 c) {
    vec2 v;
    v.x = (off.x * (dir.x)) + (off.y * dir.y);
    v.y = (off.x * (-dir.y)) + (off.y * dir.x);
    v *= len;
    float d2 = v.x * v.x + v.y * v.y;
    d2 = min(d2, clp);
    float wB = (2.0 / 5.0) * d2 + (-1.0);
    float wA = lob * d2 + (-1.0);
    wB *= wB;
    wA *= wA;
    wB = (25.0 / 16.0) * wB + (-(25.0 / 16.0 - 1.0));
    float w = wB * wA;
    aC += c * w;
    aW += w;
}
void FsrEasuSetF(inout vec2 dir, inout float len, vec2 pp, bool biS, bool biT, bool biU, bool biV,
                 float lA, float lB, float lC, float lD, float lE) {
    float w = 0.0;
    if (biS) w = (1.0 - pp.x) * (1.0 - pp.y);
    if (biT) w = pp.x * (1.0 - pp.y);
    if (biU) w = (1.0 - pp.x) * pp.y;
    if (biV) w = pp.x * pp.y;
    float dc = lD - lC;
    float cb = lC - lB;
    float lenX = max(abs(dc), abs(cb));
    lenX = APrxLoRcpF1(lenX);
    float dirX = lD - lB;
    dir.x += dirX * w;
    lenX = clamp(abs(dirX) * lenX, 0.0, 1.0);
    lenX *= lenX;
    len += lenX * w;
    float ec = lE - lC;
    float ca = lC - lA;
    float lenY = max(abs(ec), abs(ca));
    lenY = APrxLoRcpF1(lenY);
    float dirY = lE - lA;
    dir.y += dirY * w;
    lenY = clamp(abs(dirY) * lenY, 0.0, 1.0);
    lenY *= lenY;
    len += lenY * w;
}
float luma2(vec3 c) { return c.b * 0.5 + (c.r * 0.5 + c.g); }
void main() {
    last = textureSize(source, 0) - 1;
    vec2 pp = floor(gl_FragCoord.xy) * con0.xy + con0.zw;
    vec2 fp = floor(pp);
    pp -= fp;
    ivec2 f0 = ivec2(fp);
    //    b c
    //  e f g h
    //  i j k l
    //    n o
    vec3 b = at(f0 + ivec2(0, -1)), c = at(f0 + ivec2(1, -1));
    vec3 e = at(f0 + ivec2(-1, 0)), f = at(f0), g = at(f0 + ivec2(1, 0)), h = at(f0 + ivec2(2, 0));
    vec3 i = at(f0 + ivec2(-1, 1)), j = at(f0 + ivec2(0, 1)), k = at(f0 + ivec2(1, 1)), l = at(f0 + ivec2(2, 1));
    vec3 n = at(f0 + ivec2(0, 2)), o = at(f0 + ivec2(1, 2));
    float bL = luma2(b), cL = luma2(c), eL = luma2(e), fL = luma2(f), gL = luma2(g), hL = luma2(h);
    float iL = luma2(i), jL = luma2(j), kL = luma2(k), lL = luma2(l), nL = luma2(n), oL = luma2(o);
    vec2 dir = vec2(0.0);
    float len = 0.0;
    FsrEasuSetF(dir, len, pp, true, false, false, false, bL, eL, fL, gL, jL);
    FsrEasuSetF(dir, len, pp, false, true, false, false, cL, fL, gL, hL, kL);
    FsrEasuSetF(dir, len, pp, false, false, true, false, fL, iL, jL, kL, nL);
    FsrEasuSetF(dir, len, pp, false, false, false, true, gL, jL, kL, lL, oL);
    vec2 dir2 = dir * dir;
    float dirR = dir2.x + dir2.y;
    bool zro = dirR < (1.0 / 32768.0);
    dirR = APrxLoRsqF1(dirR);
    dirR = zro ? 1.0 : dirR;
    dir.x = zro ? 1.0 : dir.x;
    dir *= vec2(dirR);
    len = len * 0.5;
    len *= len;
    float stretch = (dir.x * dir.x + dir.y * dir.y) * APrxLoRcpF1(max(abs(dir.x), abs(dir.y)));
    vec2 len2 = vec2(1.0 + (stretch - 1.0) * len, 1.0 + (-0.5) * len);
    float lob = 0.5 + ((1.0 / 4.0 - 0.04) - 0.5) * len;
    float clp = APrxLoRcpF1(lob);
    vec3 min4 = min(AMin3F3(f, g, j), k);
    vec3 max4 = max(AMax3F3(f, g, j), k);
    vec3 aC = vec3(0.0);
    float aW = 0.0;
    FsrEasuTapF(aC, aW, vec2(0.0, -1.0) - pp, dir, len2, lob, clp, b);
    FsrEasuTapF(aC, aW, vec2(1.0, -1.0) - pp, dir, len2, lob, clp, c);
    FsrEasuTapF(aC, aW, vec2(-1.0, 1.0) - pp, dir, len2, lob, clp, i);
    FsrEasuTapF(aC, aW, vec2(0.0, 1.0) - pp, dir, len2, lob, clp, j);
    FsrEasuTapF(aC, aW, vec2(0.0, 0.0) - pp, dir, len2, lob, clp, f);
    FsrEasuTapF(aC, aW, vec2(-1.0, 0.0) - pp, dir, len2, lob, clp, e);
    FsrEasuTapF(aC, aW, vec2(1.0, 1.0) - pp, dir, len2, lob, clp, k);
    FsrEasuTapF(aC, aW, vec2(2.0, 1.0) - pp, dir, len2, lob, clp, l);
    FsrEasuTapF(aC, aW, vec2(2.0, 0.0) - pp, dir, len2, lob, clp, h);
    FsrEasuTapF(aC, aW, vec2(1.0, 0.0) - pp, dir, len2, lob, clp, g);
    FsrEasuTapF(aC, aW, vec2(1.0, 2.0) - pp, dir, len2, lob, clp, o);
    FsrEasuTapF(aC, aW, vec2(0.0, 2.0) - pp, dir, len2, lob, clp, n);
    color = vec4(min(max4, max(min4, aC * vec3(1.0 / aW))), 1.0);
}
)";

// AMD FidelityFX Super Resolution 1: RCAS, the sharpening after EASU.
const char* kRcas = R"(#version 300 es
// AMD FidelityFX SUPER RESOLUTION [FSR 1] - v1.20210629, RCAS (FsrRcasF, its 32-bit version, without the optional
// denoise), from ffx_fsr1.h and the helpers of ffx_a.h it uses.
//
// Copyright (c) 2021 Advanced Micro Devices, Inc. All rights reserved.
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files(the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and / or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions :
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.
//
// Ported to a GLSL ES 3.00 fragment shader for OpenDMTQ: the five taps read with texelFetch, clamped to the picture's
// edge; the limiters and the resolve are the reference's, per channel as vectors.
precision highp float;
precision highp int;
uniform highp sampler2D source;
// FsrRcasCon's con.x: the sharpness as a linear amount, exp2(-stops).
uniform float sharpness;
out vec4 color;
#define FSR_RCAS_LIMIT (0.25 - (1.0 / 16.0))
float APrxMedRcpF1(float a) {
    float b = uintBitsToFloat(0x7ef19fffu - floatBitsToUint(a));
    return b * (-b * a + 2.0);
}
vec3 AMin3F3(vec3 x, vec3 y, vec3 z) { return min(x, min(y, z)); }
vec3 AMax3F3(vec3 x, vec3 y, vec3 z) { return max(x, max(y, z)); }
ivec2 last;
vec3 at(ivec2 p) { return texelFetch(source, clamp(p, ivec2(0), last), 0).rgb; }
void main() {
    last = textureSize(source, 0) - 1;
    ivec2 sp = ivec2(gl_FragCoord.xy);
    //    b
    //  d e f
    //    h
    vec3 b = at(sp + ivec2(0, -1));
    vec3 d = at(sp + ivec2(-1, 0));
    vec3 e = at(sp);
    vec3 f = at(sp + ivec2(1, 0));
    vec3 h = at(sp + ivec2(0, 1));
    vec3 mn4 = min(AMin3F3(b, d, f), h);
    vec3 mx4 = max(AMax3F3(b, d, f), h);
    vec2 peakC = vec2(1.0, -1.0 * 4.0);
    vec3 hitMin = min(mn4, e) * (vec3(1.0) / (4.0 * mx4));
    vec3 hitMax = (peakC.x - max(mx4, e)) * (vec3(1.0) / (4.0 * mn4 + peakC.y));
    vec3 lobeRGB = max(-hitMin, hitMax);
    float lobe = max(-FSR_RCAS_LIMIT, min(max(lobeRGB.r, max(lobeRGB.g, lobeRGB.b)), 0.0)) * sharpness;
    float rcpL = APrxMedRcpF1(4.0 * lobe + 1.0);
    color = vec4((lobe * b + lobe * d + lobe * h + lobe * f + e) * rcpL, 1.0);
}
)";

// NVIDIA Image Scaling: NVScaler.
const char* kNis = R"(#version 300 es
// The MIT License(MIT)
//
// Copyright(c) 2022 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
//
// Permission is hereby granted, free of charge, to any person obtaining a copy of
// this software and associated documentation files(the "Software"), to deal in
// the Software without restriction, including without limitation the rights to
// use, copy, modify, merge, publish, distribute, sublicense, and / or sell copies of
// the Software, and to permit persons to whom the Software is furnished to do so,
// subject to the following conditions :
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
// FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.IN NO EVENT SHALL THE AUTHORS OR
// COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
// IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
// CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
//
// NVIDIA Image Scaling SDK - v1.0.3, NVScaler (NIS_Scaler.h with NIS_SCALER 1, SDR, no viewport, 32-bit floats).
// Ported to a GLSL ES 3.00 fragment shader for OpenDMTQ: each output pixel reads its own 6x6 support of luma, where the
// compute shader loads a tile of them into group memory for a block of pixels. The support is kept as six rows of a
// vec4 (columns 0 to 3) and a vec2 (columns 4 and 5), and every loop of the reference over it is written out, so that
// nothing indexes an array at run time: Direct3D's shader compiler, under ANGLE, takes minutes over local arrays read
// with a variable index (the reference's own shape). GetEdgeMap, CalcLTI, EvalPoly6, FilterNormal, AddDirFilters and the
// final luma correction compute what the reference's do; the coefficient tables come in two textures, as the SDK gives
// them, a phase's six taps in two texels.
precision highp float;
precision highp int;
uniform highp sampler2D source;
uniform highp sampler2D coef_scaler;
uniform highp sampler2D coef_usm;
// NISConfig's first eighteen values, in its order (NVScalerUpdateConfig sets them).
uniform vec4 config[5];
#define kDetectRatio config[0].x
#define kDetectThres config[0].y
#define kMinContrastRatio config[0].z
#define kRatioNorm config[0].w
#define kContrastBoost config[1].x
#define kEps config[1].y
#define kSharpStartY config[1].z
#define kSharpScaleY config[1].w
#define kSharpStrengthMin config[2].x
#define kSharpStrengthScale config[2].y
#define kSharpLimitMin config[2].z
#define kSharpLimitScale config[2].w
#define kScaleX config[3].x
#define kScaleY config[3].y
#define kSrcNormX config[4].x
#define kSrcNormY config[4].y
#define kPhaseCount 64
#define NIS_SCALE_INT 1.0
#define NIS_SCALE_FLOAT 1.0
out vec4 color;
float getY(vec3 rgba) { return 0.2126 * rgba.x + 0.7152 * rgba.y + 0.0722 * rgba.z; }
// GetEdgeMap over a 3x3 window, its rows r0 to r2 (each the window's three columns).
vec4 GetEdgeMap(vec3 r0, vec3 r1, vec3 r2) {
    float g_0 = abs(r0.x + r0.y + r0.z - r2.x - r2.y - r2.z);
    float g_45 = abs(r1.x + r0.x + r0.y - r2.y - r2.z - r1.z);
    float g_90 = abs(r0.x + r1.x + r2.x - r0.z - r1.z - r2.z);
    float g_135 = abs(r1.x + r2.x + r2.y - r0.y - r0.z - r1.z);
    float g_0_90_max = max(g_0, g_90);
    float g_0_90_min = min(g_0, g_90);
    float g_45_135_max = max(g_45, g_135);
    float g_45_135_min = min(g_45, g_135);
    float e_0_90 = 0.0;
    float e_45_135 = 0.0;
    if (g_0_90_max + g_45_135_max == 0.0) return vec4(0.0);
    e_0_90 = min(g_0_90_max / (g_0_90_max + g_45_135_max), 1.0);
    e_45_135 = 1.0 - e_0_90;
    bool c_0_90 = (g_0_90_max > (g_0_90_min * kDetectRatio)) && (g_0_90_max > kDetectThres) && (g_0_90_max > g_45_135_min);
    bool c_45_135 = (g_45_135_max > (g_45_135_min * kDetectRatio)) && (g_45_135_max > kDetectThres) && (g_45_135_max > g_0_90_min);
    bool c_g_0_90 = g_0_90_max == g_0;
    bool c_g_45_135 = g_45_135_max == g_45;
    float f_e_0_90 = (c_0_90 && c_45_135) ? e_0_90 : 1.0;
    float f_e_45_135 = (c_0_90 && c_45_135) ? e_45_135 : 1.0;
    float weight_0 = (c_0_90 && c_g_0_90) ? f_e_0_90 : 0.0;
    float weight_90 = (c_0_90 && !c_g_0_90) ? f_e_0_90 : 0.0;
    float weight_45 = (c_45_135 && c_g_45_135) ? f_e_45_135 : 0.0;
    float weight_135 = (c_45_135 && !c_g_45_135) ? f_e_45_135 : 0.0;
    return vec4(weight_0, weight_90, weight_45, weight_135);
}
float CalcLTI(float p0, float p1, float p2, float p3, float p4, float p5, int phase_index) {
    bool selector = (phase_index <= kPhaseCount / 2);
    float sel = selector ? p0 : p3;
    float a_min = min(min(p1, p2), sel);
    float a_max = max(max(p1, p2), sel);
    sel = selector ? p2 : p5;
    float b_min = min(min(p3, p4), sel);
    float b_max = max(max(p3, p4), sel);
    float a_cont = a_max - a_min;
    float b_cont = b_max - b_min;
    float cont_ratio = max(a_cont, b_cont) / (min(a_cont, b_cont) + kEps);
    return (1.0 - clamp((cont_ratio - kMinContrastRatio) * kRatioNorm, 0.0, 1.0)) * kContrastBoost;
}
vec4 GetInterpEdgeMap(vec4 e00, vec4 e01, vec4 e10, vec4 e11, float phase_frac_x, float phase_frac_y) {
    vec4 h0 = mix(e00, e01, phase_frac_x);
    vec4 h1 = mix(e10, e11, phase_frac_x);
    return mix(h0, h1, phase_frac_y);
}
// EvalPoly6 of six values (v03 the first four, v45 the last two) at a phase: its taps from the tables' row.
float EvalPoly6(vec4 v03, vec2 v45, int phase_int) {
    float y = dot(texelFetch(coef_scaler, ivec2(0, phase_int), 0), v03) + dot(texelFetch(coef_scaler, ivec2(1, phase_int), 0).xy, v45);
    float y_usm = dot(texelFetch(coef_usm, ivec2(0, phase_int), 0), v03) + dot(texelFetch(coef_usm, ivec2(1, phase_int), 0).xy, v45);
    float y_scale = 1.0 - clamp((y * (1.0 / NIS_SCALE_FLOAT) - kSharpStartY) * kSharpScaleY, 0.0, 1.0);
    float y_sharpness = y_scale * kSharpStrengthScale + kSharpStrengthMin;
    y_usm *= y_sharpness;
    float y_sharpness_limit = (y_scale * kSharpLimitScale + kSharpLimitMin) * y;
    y_usm = min(y_sharpness_limit, max(-y_sharpness_limit, y_usm));
    y_usm *= CalcLTI(v03.x, v03.y, v03.z, v03.w, v45.x, v45.y, phase_int);
    return y + y_usm;
}
void main() {
    ivec2 last = textureSize(source, 0) - 1;
    vec2 dst = floor(gl_FragCoord.xy);
    float srcX = (0.5 + dst.x) * kScaleX - 0.5;
    float srcY = (0.5 + dst.y) * kScaleY - 0.5;
    ivec2 base = ivec2(floor(srcX), floor(srcY));
    float fx = srcX - floor(srcX);
    float fy = srcY - floor(srcY);
    int fx_int = int(fx * float(kPhaseCount));
    int fy_int = int(fy * float(kPhaseCount));
    // The 6x6 support of luma, p[row][column] of the reference: row r is a<r> (columns 0 to 3) and b<r> (4 and 5), from
    // two above and two to the left of the pixel the output falls in.
#define LUMA(dx, dy) getY(texelFetch(source, clamp(base + ivec2(dx, dy), ivec2(0), last), 0).rgb)
#define ROW_A(dy) vec4(LUMA(-2, dy), LUMA(-1, dy), LUMA(0, dy), LUMA(1, dy))
#define ROW_B(dy) vec2(LUMA(2, dy), LUMA(3, dy))
    vec4 a0 = ROW_A(-2), a1 = ROW_A(-1), a2 = ROW_A(0), a3 = ROW_A(1), a4 = ROW_A(2), a5 = ROW_A(3);
    vec2 b0 = ROW_B(-2), b1 = ROW_B(-1), b2 = ROW_B(0), b3 = ROW_B(1), b4 = ROW_B(2), b5 = ROW_B(3);
    // The edge map of the four source pixels around the output (edge[i][j]: i down, j across), each from its 3x3
    // neighbours: rows 1 to 3 or 2 to 4, columns 1 to 3 or 2 to 4.
    vec4 e00 = GetEdgeMap(a1.yzw, a2.yzw, a3.yzw);
    vec4 e01 = GetEdgeMap(vec3(a1.zw, b1.x), vec3(a2.zw, b2.x), vec3(a3.zw, b3.x));
    vec4 e10 = GetEdgeMap(a2.yzw, a3.yzw, a4.yzw);
    vec4 e11 = GetEdgeMap(vec3(a2.zw, b2.x), vec3(a3.zw, b3.x), vec3(a4.zw, b4.x));
    vec4 w = GetInterpEdgeMap(e00, e01, e10, e11, fx, fy) * NIS_SCALE_INT;
    float baseWeight = NIS_SCALE_FLOAT - w.x - w.y - w.z - w.w;
    float opY = 0.0;
    // FilterNormal: down each column by the y phase's taps, then across by the x phase's.
    vec4 cy03 = texelFetch(coef_scaler, ivec2(0, fy_int), 0);
    vec2 cy45 = texelFetch(coef_scaler, ivec2(1, fy_int), 0).xy;
    vec4 cx03 = texelFetch(coef_scaler, ivec2(0, fx_int), 0);
    vec2 cx45 = texelFetch(coef_scaler, ivec2(1, fx_int), 0).xy;
    vec4 v03 = a0 * cy03.x + a1 * cy03.y + a2 * cy03.z + a3 * cy03.w + a4 * cy45.x + a5 * cy45.y;
    vec2 v45 = b0 * cy03.x + b1 * cy03.y + b2 * cy03.z + b3 * cy03.w + b4 * cy45.x + b5 * cy45.y;
    opY += (dot(v03, cx03) + dot(v45, cx45)) * baseWeight;
    // AddDirFilters.
    if (w.x > 0.0) {
        // 0 deg: across the middle two columns, then down by the y phase.
        vec4 i03 = mix(vec4(a0.z, a1.z, a2.z, a3.z), vec4(a0.w, a1.w, a2.w, a3.w), fx);
        vec2 i45 = mix(vec2(a4.z, a5.z), vec2(a4.w, a5.w), fx);
        opY += EvalPoly6(i03, i45, fy_int) * w.x;
    }
    if (w.y > 0.0) {
        // 90 deg: down the middle two rows, then across by the x phase.
        opY += EvalPoly6(mix(a2, a3, fy), mix(b2, b3, fy), fx_int) * w.y;
    }
    if (w.z > 0.0) {
        // 45 deg.
        float pphase_b45 = 0.5 + 0.5 * (fx - fy);
        float t1 = mix(a2.y, a1.z, pphase_b45);
        float t3 = mix(a3.z, a2.w, pphase_b45);
        float t5 = mix(a4.w, b3.x, pphase_b45);
        pphase_b45 = pphase_b45 - 0.5;
        bool ahead = pphase_b45 >= 0.0;
        float a = ahead ? a0.z : a2.x;
        float b = ahead ? a1.w : a3.y;
        float c = ahead ? b2.x : a4.z;
        float d = ahead ? b3.y : a5.w;
        float t0 = mix(a1.y, a, abs(pphase_b45));
        float t2 = mix(a2.z, b, abs(pphase_b45));
        float t4 = mix(a3.w, c, abs(pphase_b45));
        float t6 = mix(b4.x, d, abs(pphase_b45));
        float pphase_p45 = fx + fy;
        bool over = pphase_p45 >= 1.0;
        // Taps 1 to 6 of the seven, or 0 to 5.
        vec4 i03 = over ? vec4(t1, t2, t3, t4) : vec4(t0, t1, t2, t3);
        vec2 i45 = over ? vec2(t5, t6) : vec2(t4, t5);
        if (over) pphase_p45 = pphase_p45 - 1.0;
        opY += EvalPoly6(i03, i45, int(pphase_p45 * 64.0)) * w.z;
    }
    if (w.w > 0.0) {
        // 135 deg.
        float pphase_b135 = 0.5 * (fx + fy);
        float t1 = mix(a3.y, a4.z, pphase_b135);
        float t3 = mix(a2.z, a3.w, pphase_b135);
        float t5 = mix(a1.w, b2.x, pphase_b135);
        pphase_b135 = pphase_b135 - 0.5;
        bool ahead = pphase_b135 >= 0.0;
        float a = ahead ? a5.z : a3.x;
        float b = ahead ? a4.w : a2.y;
        float c = ahead ? b3.x : a1.z;
        float d = ahead ? b2.y : a0.w;
        float t0 = mix(a4.y, a, abs(pphase_b135));
        float t2 = mix(a3.z, b, abs(pphase_b135));
        float t4 = mix(a2.w, c, abs(pphase_b135));
        float t6 = mix(b1.x, d, abs(pphase_b135));
        float pphase_p135 = 1.0 + (fx - fy);
        bool over = pphase_p135 >= 1.0;
        vec4 i03 = over ? vec4(t1, t2, t3, t4) : vec4(t0, t1, t2, t3);
        vec2 i45 = over ? vec2(t5, t6) : vec2(t4, t5);
        if (over) pphase_p135 = pphase_p135 - 1.0;
        opY += EvalPoly6(i03, i45, int(pphase_p135 * 64.0)) * w.w;
    }
    vec2 coord = vec2((srcX + 0.5) * kSrcNormX, (srcY + 0.5) * kSrcNormY);
    vec4 op = textureLod(source, coord, 0.0);
    float y = getY(op.xyz);
    float corr = opY * (1.0 / NIS_SCALE_FLOAT) - y;
    color = vec4(op.xyz + vec3(corr), 1.0);
}
)";

// SMAA's reference shader (third_party/smaa/SMAA.hlsl as it is, its bytes put into the build by CMake as an array,
// smaa_hlsl.inc, ending in a 0), between a preamble that chooses its GLSL path and its High preset and a main for each
// pass.
const unsigned char kSmaaBytes[] = {
#include "smaa_hlsl.inc"
};
// Its text for the compiler: two of its comments' diagrams have a byte of Latin-1 (a middle dot), which a GLSL source
// may not have; a space in their place.
const std::string& smaa_source() {
    static const std::string text = [] {
        std::string t(reinterpret_cast<const char*>(kSmaaBytes));
        for (char& ch : t) if (static_cast<unsigned char>(ch) >= 0x80) ch = ' ';
        return t;
    }();
    return text;
}
// The preamble before it, for each stage; the stage's own lines come after.
const char* kSmaaVertexHead = "#version 300 es\nprecision highp float;\nprecision highp int;\n#define SMAA_GLSL_3 1\n"
                              "#define SMAA_PRESET_HIGH 1\n#define SMAA_INCLUDE_VS 1\n#define SMAA_INCLUDE_PS 0\n"
                              "uniform highp vec4 metrics;\n#define SMAA_RT_METRICS metrics\n";
const char* kSmaaFragmentHead = "#version 300 es\nprecision highp float;\nprecision highp int;\n#define SMAA_GLSL_3 1\n"
                                "#define SMAA_PRESET_HIGH 1\n#define SMAA_INCLUDE_VS 0\n#define SMAA_INCLUDE_PS 1\n"
                                "uniform highp vec4 metrics;\n#define SMAA_RT_METRICS metrics\n";
// Each pass's vertex and fragment main, with the varyings SMAA's vertex functions fill.
const char* kSmaaEdgesVertex = R"(
out vec2 texcoord;
out vec4 offset[3];
void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    texcoord = p;
    SMAAEdgeDetectionVS(texcoord, offset);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
)";
const char* kSmaaEdgesFragment = R"(
uniform highp sampler2D colorTex;
in vec2 texcoord;
in vec4 offset[3];
out vec4 color;
void main() { color = vec4(SMAALumaEdgeDetectionPS(texcoord, offset, colorTex), 0.0, 0.0); }
)";
const char* kSmaaWeightsVertex = R"(
out vec2 texcoord;
out vec2 pixcoord;
out vec4 offset[3];
void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    texcoord = p;
    SMAABlendingWeightCalculationVS(texcoord, pixcoord, offset);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
)";
const char* kSmaaWeightsFragment = R"(
uniform highp sampler2D edgesTex;
uniform highp sampler2D areaTex;
uniform highp sampler2D searchTex;
in vec2 texcoord;
in vec2 pixcoord;
in vec4 offset[3];
out vec4 color;
void main() { color = SMAABlendingWeightCalculationPS(texcoord, pixcoord, offset, edgesTex, areaTex, searchTex, vec4(0.0)); }
)";
const char* kSmaaBlendVertex = R"(
out vec2 texcoord;
out vec4 offset;
void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    texcoord = p;
    SMAANeighborhoodBlendingVS(texcoord, offset);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
)";
const char* kSmaaBlendFragment = R"(
uniform highp sampler2D colorTex;
uniform highp sampler2D blendTex;
in vec2 texcoord;
in vec4 offset;
out vec4 color;
void main() { color = vec4(SMAANeighborhoodBlendingPS(texcoord, offset, colorTex, blendTex).rgb, 1.0); }
)";

// A shader from its parts (glShaderSource's strings, one after the other); 0 and its log said when it does not compile.
GLuint compile(const Gl& g, GLenum kind, const char* what, std::initializer_list<const char*> parts) {
    std::vector<const char*> texts(parts);
    GLuint shader = g.create_shader(kind);
    g.shader_source(shader, static_cast<GLsizei>(texts.size()), texts.data(), nullptr);
    g.compile_shader(shader);
    GLint ok = 0;
    g.get_shader(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char why[1024] = "";
        g.shader_log(shader, sizeof why, nullptr, why);
        arm32::log("player: picture: %s does not compile: %s", what, why);
        g.delete_shader(shader);
        return 0;
    }
    return shader;
}

// A program of a vertex and a fragment shader; 0 when either fails or it does not link (said in the log).
GLuint link(const Gl& g, const char* what, GLuint vertex, GLuint fragment) {
    GLuint program = 0;
    if (vertex && fragment) {
        program = g.create_program();
        g.attach_shader(program, vertex);
        g.attach_shader(program, fragment);
        g.link_program(program);
        GLint linked = 0;
        g.get_program(program, GL_LINK_STATUS, &linked);
        if (!linked) {
            char why[1024] = "";
            g.program_log(program, sizeof why, nullptr, why);
            arm32::log("player: picture: %s does not link: %s", what, why);
            g.delete_program(program);
            program = 0;
        }
    }
    if (vertex) g.delete_shader(vertex);
    if (fragment) g.delete_shader(fragment);
    return program;
}

// A texture of `w` x `h` in `format` with a framebuffer drawing into it, linear and clamped; false when the driver will
// not. Bindings change (the caller has the game's saved).
bool target(const Gl& g, GLenum format, int w, int h, GLuint* texture, GLuint* fbo) {
    g.gen_textures(1, texture);
    g.bind_texture(GL_TEXTURE_2D, *texture);
    g.tex_storage(GL_TEXTURE_2D, 1, format, w, h);
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    g.gen_framebuffers(1, fbo);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, *fbo);
    g.framebuffer_texture(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, *texture, 0);
    return g.check_framebuffer(GL_DRAW_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
}

// A table as a texture, uploaded with the unpack state of a plain upload and the game's put back.
GLuint table(const Gl& g, GLenum format, GLenum data_format, GLenum type, int w, int h, const void* data, GLenum filter) {
    GLint unpack[6] = {4, 0, 0, 0, 0, 0};
    const GLenum names[6] = {GL_UNPACK_ALIGNMENT, GL_UNPACK_ROW_LENGTH, GL_UNPACK_SKIP_ROWS, GL_UNPACK_SKIP_PIXELS,
                             GL_UNPACK_IMAGE_HEIGHT, GL_UNPACK_SKIP_IMAGES};
    for (int i = 0; i < 6; ++i) g.get_integer(names[i], &unpack[i]);
    GLint unpack_buffer = 0;
    g.get_integer(GL_PIXEL_UNPACK_BUFFER_BINDING, &unpack_buffer);
    g.bind_buffer(GL_PIXEL_UNPACK_BUFFER, 0);
    for (int i = 0; i < 6; ++i) g.pixel_store(names[i], i == 0 ? 1 : 0);
    GLuint t = 0;
    g.gen_textures(1, &t);
    g.bind_texture(GL_TEXTURE_2D, t);
    g.tex_storage(GL_TEXTURE_2D, 1, format, w, h);
    g.tex_sub_image(GL_TEXTURE_2D, 0, 0, 0, w, h, data_format, type, data);
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, static_cast<GLint>(filter));
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, static_cast<GLint>(filter));
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    for (int i = 0; i < 6; ++i) g.pixel_store(names[i], unpack[i]);
    g.bind_buffer(GL_PIXEL_UNPACK_BUFFER, static_cast<GLuint>(unpack_buffer));
    return t;
}

// ---- a context's programs, tables and intermediate pictures

struct Passes {
    EGLContext context = EGL_NO_CONTEXT;
    bool made = false;             // tried in this context (made or not)
    GLuint vertex_array = 0;       // an empty one: the draws take no attributes
    GLuint easu = 0, rcas = 0, nis = 0, smaa_edges = 0, smaa_weights = 0, smaa_blend = 0;
    GLint easu_con = -1, rcas_sharpness = -1, nis_config = -1;
    GLint smaa_metrics[3] = {-1, -1, -1};
    GLuint nis_scaler = 0, nis_usm = 0, smaa_area = 0, smaa_search = 0;  // the tables
    Cmaa2* cmaa2 = nullptr;        // CMAA 2's own objects (cmaa2.cpp), when it runs here
    int aa = 0;                    // the anti-aliasing in use here: CMAA 2 becomes SMAA where compute cannot run
    // The intermediate pictures, at the sizes they were made for.
    int in_w = 0, in_h = 0, out_w = 0, out_h = 0;
    GLuint edges = 0, edges_fbo = 0, weights = 0, weights_fbo = 0, aa_out = 0, aa_fbo = 0, easu_out = 0, easu_fbo = 0;
    GLuint read_fbo = 0;           // a framebuffer for a plain copy's source
    GLuint read_texture = 0;       // the texture attached to it now: attached again only when another is read
};
Passes g_passes;

// The intermediate pictures for frames of `in` drawn to a window of `out`, made again when either size changed.
bool size_targets(const Gl& g, Passes& p, int in_w, int in_h, int out_w, int out_h) {
    if (p.in_w == in_w && p.in_h == in_h && p.out_w == out_w && p.out_h == out_h) return true;
    GLuint textures[4] = {p.edges, p.weights, p.aa_out, p.easu_out};
    g.delete_textures(4, textures);
    GLuint fbos[4] = {p.edges_fbo, p.weights_fbo, p.aa_fbo, p.easu_fbo};
    g.delete_framebuffers(4, fbos);
    p.edges = p.weights = p.aa_out = p.easu_out = p.edges_fbo = p.weights_fbo = p.aa_fbo = p.easu_fbo = 0;
    // The plain copy's source is attached again: a new texture may have the name of one that went.
    p.read_texture = 0;
    bool ok = true;
    if (p.aa == 2) {
        // SMAA's edges (two channels) and blending weights, at the frame's size.
        ok = ok && target(g, GL_RG8, in_w, in_h, &p.edges, &p.edges_fbo);
        ok = ok && target(g, GL_RGBA8, in_w, in_h, &p.weights, &p.weights_fbo);
    }
    // The anti-aliased frame, at its size.
    if (p.aa == 1 || p.aa == 2) ok = ok && target(g, GL_RGBA8, in_w, in_h, &p.aa_out, &p.aa_fbo);
    // EASU's output, which RCAS reads, at the window's size.
    if (g_upscaler.load() == 1 && (in_w != out_w || in_h != out_h)) ok = ok && target(g, GL_RGBA8, out_w, out_h, &p.easu_out, &p.easu_fbo);
    p.in_w = in_w;
    p.in_h = in_h;
    p.out_w = out_w;
    p.out_h = out_h;
    return ok;
}

// The programs and tables the settings need, in `context` (current), once; what it took logged.
void make_passes(const Gl& g, Passes& p, EGLContext context) {
    const std::int64_t began = now_ns();
    p = Passes{};
    p.context = context;
    p.made = true;
    p.aa = g_anti_aliasing.load();
    const int upscaler = g_upscaler.load();
    g.gen_vertex_arrays(1, &p.vertex_array);
    if (upscaler == 1) {
        p.easu = link(g, "AMD FSR 1's EASU", compile(g, GL_VERTEX_SHADER, "the passes' vertex shader", {kVertex}),
                      compile(g, GL_FRAGMENT_SHADER, "AMD FSR 1's EASU", {kEasu}));
        p.rcas = link(g, "AMD FSR 1's RCAS", compile(g, GL_VERTEX_SHADER, "the passes' vertex shader", {kVertex}),
                      compile(g, GL_FRAGMENT_SHADER, "AMD FSR 1's RCAS", {kRcas}));
        if (p.easu) {
            g.use_program(p.easu);
            g.uniform_int(g.uniform_location(p.easu, "source"), 0);
            p.easu_con = g.uniform_location(p.easu, "con0");
        }
        if (p.rcas) {
            g.use_program(p.rcas);
            g.uniform_int(g.uniform_location(p.rcas, "source"), 0);
            // FsrRcasCon: the stops as a linear amount.
            g.uniform_float(g.uniform_location(p.rcas, "sharpness"), std::exp2(-kRcasStops));
        }
        // Both or neither: EASU's output wants its sharpening.
        if (!p.easu || !p.rcas) {
            g.delete_program(p.easu);
            g.delete_program(p.rcas);
            p.easu = p.rcas = 0;
        }
    } else if (upscaler == 2) {
        p.nis = link(g, "NVIDIA NIS", compile(g, GL_VERTEX_SHADER, "the passes' vertex shader", {kVertex}),
                     compile(g, GL_FRAGMENT_SHADER, "NVIDIA NIS", {kNis}));
        if (p.nis) {
            g.use_program(p.nis);
            g.uniform_int(g.uniform_location(p.nis, "source"), 0);
            g.uniform_int(g.uniform_location(p.nis, "coef_scaler"), 1);
            g.uniform_int(g.uniform_location(p.nis, "coef_usm"), 2);
            p.nis_config = g.uniform_location(p.nis, "config");
            // The SDK's tables, 64 phases of 8 taps (6 used): two RGBA texels a phase, read with texelFetch.
            p.nis_scaler = table(g, GL_RGBA32F, GL_RGBA, GL_FLOAT, 2, 64, coef_scale, GL_NEAREST);
            p.nis_usm = table(g, GL_RGBA32F, GL_RGBA, GL_FLOAT, 2, 64, coef_usm, GL_NEAREST);
        }
    }
    if (p.aa == 1) {
        // CMAA 2 needs OpenGL ES 3.1's compute shaders: where the context has none, SMAA in its place.
        GLint major = 0, minor = 0;
        g.get_integer(GL_MAJOR_VERSION, &major);
        g.get_integer(GL_MINOR_VERSION, &minor);
        if (major > 3 || (major == 3 && minor >= 1)) p.cmaa2 = cmaa2_make();
        if (!p.cmaa2) {
            arm32::log("player: anti-aliasing: CMAA 2 cannot run here (OpenGL ES %d.%d%s): SMAA in its place", major, minor,
                       major > 3 || (major == 3 && minor >= 1) ? ", its compute shaders do not run" : ", no compute shaders");
            p.aa = 2;
        }
    }
    if (p.aa == 2) {
        p.smaa_edges = link(g, "SMAA's edge detection", compile(g, GL_VERTEX_SHADER, "SMAA's edge detection", {kSmaaVertexHead, smaa_source().c_str(), kSmaaEdgesVertex}),
                            compile(g, GL_FRAGMENT_SHADER, "SMAA's edge detection", {kSmaaFragmentHead, smaa_source().c_str(), kSmaaEdgesFragment}));
        p.smaa_weights = link(g, "SMAA's blending weights", compile(g, GL_VERTEX_SHADER, "SMAA's blending weights", {kSmaaVertexHead, smaa_source().c_str(), kSmaaWeightsVertex}),
                              compile(g, GL_FRAGMENT_SHADER, "SMAA's blending weights", {kSmaaFragmentHead, smaa_source().c_str(), kSmaaWeightsFragment}));
        p.smaa_blend = link(g, "SMAA's neighbourhood blending", compile(g, GL_VERTEX_SHADER, "SMAA's neighbourhood blending", {kSmaaVertexHead, smaa_source().c_str(), kSmaaBlendVertex}),
                            compile(g, GL_FRAGMENT_SHADER, "SMAA's neighbourhood blending", {kSmaaFragmentHead, smaa_source().c_str(), kSmaaBlendFragment}));
        if (p.smaa_edges && p.smaa_weights && p.smaa_blend) {
            g.use_program(p.smaa_edges);
            g.uniform_int(g.uniform_location(p.smaa_edges, "colorTex"), 0);
            p.smaa_metrics[0] = g.uniform_location(p.smaa_edges, "metrics");
            g.use_program(p.smaa_weights);
            g.uniform_int(g.uniform_location(p.smaa_weights, "edgesTex"), 0);
            g.uniform_int(g.uniform_location(p.smaa_weights, "areaTex"), 1);
            g.uniform_int(g.uniform_location(p.smaa_weights, "searchTex"), 2);
            p.smaa_metrics[1] = g.uniform_location(p.smaa_weights, "metrics");
            g.use_program(p.smaa_blend);
            g.uniform_int(g.uniform_location(p.smaa_blend, "colorTex"), 0);
            g.uniform_int(g.uniform_location(p.smaa_blend, "blendTex"), 1);
            p.smaa_metrics[2] = g.uniform_location(p.smaa_blend, "metrics");
            // The precomputed tables: the area texture filtered, the search texture read point by point.
            p.smaa_area = table(g, GL_RG8, GL_RG, GL_UNSIGNED_BYTE, AREATEX_WIDTH, AREATEX_HEIGHT, areaTexBytes, GL_LINEAR);
            p.smaa_search = table(g, GL_R8, GL_RED, GL_UNSIGNED_BYTE, SEARCHTEX_WIDTH, SEARCHTEX_HEIGHT, searchTexBytes, GL_NEAREST);
        } else {
            // A part missing: none of it.
            g.delete_program(p.smaa_edges);
            g.delete_program(p.smaa_weights);
            g.delete_program(p.smaa_blend);
            p.smaa_edges = p.smaa_weights = p.smaa_blend = 0;
            p.aa = 0;
        }
    }
    arm32::log("player: picture: the passes' programs made in %lld ms on the render thread",
               static_cast<long long>((now_ns() - began) / 1000000));
}

// A full-screen draw of `program` into `fbo` (0: the window's own) of `w` x `h`.
void draw(const Gl& g, GLuint program, GLuint fbo, int w, int h) {
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, fbo);
    g.viewport(0, 0, w, h);
    g.use_program(program);
    g.draw_arrays(GL_TRIANGLES, 0, 3);
}

// `texture` on texture unit `unit`, read through its own parameters.
void bind_unit(const Gl& g, int unit, GLuint texture) {
    g.active_texture(GL_TEXTURE0 + static_cast<GLenum>(unit));
    g.bind_texture(GL_TEXTURE_2D, texture);
    g.bind_sampler(static_cast<GLuint>(unit), 0);
}

// ---- what the passes cost, for the player's stats (every 5 s, with ARM32_STATS) and once in the log

// The steps of a frame's picture timed apart: the passes, each on the CPU (this thread's time) and on
// the GPU (EXT_disjoint_timer_query, where the driver has it). kStepGame is the GPU's time from the end of the last frame's
// passes to the start of this one's: the game's own drawing of the frame (timestamps only).
enum Step { kStepGame, kStepCopy, kStepCmaa2, kStepSmaaEdges, kStepSmaaWeights, kStepSmaaBlend, kStepEasu, kStepRcas, kStepNis, kSteps };
const char* const kStepNames[kSteps] = {"game", "copy", "CMAA 2", "SMAA edges", "SMAA weights", "SMAA blend", "EASU", "RCAS", "NIS"};

// The GPU's clock by EXT_disjoint_timer_query: a timestamp at each step's start and at the end, in a ring of frames read
// back a few frames later when they are there (never waited for); where the driver has no timestamps, the time of each
// step by its own elapsed-time query instead (the game's own time is then not known).
struct GpuTimes {
    PFNGLGENQUERIESEXTPROC gen = nullptr;
    PFNGLQUERYCOUNTEREXTPROC counter = nullptr;
    PFNGLBEGINQUERYEXTPROC begin = nullptr;
    PFNGLENDQUERYEXTPROC end = nullptr;
    PFNGLGETQUERYOBJECTUIVEXTPROC available = nullptr;
    PFNGLGETQUERYOBJECTUI64VEXTPROC result = nullptr;
    PFNGLGETQUERYIVEXTPROC query_iv = nullptr;
    EGLContext context = EGL_NO_CONTEXT;
    bool on = false, stamps = false;
    static constexpr int kRing = 4;
    // Per frame of the ring: the queries of each step (start stamps, or elapsed times), the end stamp, and which steps ran.
    GLuint queries[kRing][kSteps] = {}, ends[kRing] = {};
    bool used[kRing][kSteps] = {}, pending[kRing] = {};
    int frame = 0;
    int open = -1;  // the step whose elapsed-time query is open, -1 none
    // The sums since the last report, per step: GPU nanoseconds and the frames they cover.
    std::uint64_t gpu_ns[kSteps] = {}, gpu_frames[kSteps] = {};
    bool disjoint = false;
} g_gpu;

// The timer queries in this context, when the driver has the extension; said once either way.
void gpu_times_start(const Gl& g, EGLContext context) {
    GpuTimes& t = g_gpu;
    if (t.context == context) return;
    t = GpuTimes{};
    t.context = context;
    // The extension, by name among the context's.
    auto get_stringi = reinterpret_cast<const GLubyte* (*)(GLenum, GLuint)>(arm32::gl_proc("glGetStringi"));
    GLint count = 0;
    g.get_integer(GL_NUM_EXTENSIONS, &count);
    bool has = false;
    for (GLint i = 0; get_stringi && i < count; ++i) {
        const char* name = reinterpret_cast<const char*>(get_stringi(GL_EXTENSIONS, static_cast<GLuint>(i)));
        if (name && std::strcmp(name, "GL_EXT_disjoint_timer_query") == 0) has = true;
    }
    t.gen = reinterpret_cast<PFNGLGENQUERIESEXTPROC>(arm32::gl_proc("glGenQueriesEXT"));
    t.counter = reinterpret_cast<PFNGLQUERYCOUNTEREXTPROC>(arm32::gl_proc("glQueryCounterEXT"));
    t.begin = reinterpret_cast<PFNGLBEGINQUERYEXTPROC>(arm32::gl_proc("glBeginQueryEXT"));
    t.end = reinterpret_cast<PFNGLENDQUERYEXTPROC>(arm32::gl_proc("glEndQueryEXT"));
    t.available = reinterpret_cast<PFNGLGETQUERYOBJECTUIVEXTPROC>(arm32::gl_proc("glGetQueryObjectuivEXT"));
    t.result = reinterpret_cast<PFNGLGETQUERYOBJECTUI64VEXTPROC>(arm32::gl_proc("glGetQueryObjectui64vEXT"));
    t.query_iv = reinterpret_cast<PFNGLGETQUERYIVEXTPROC>(arm32::gl_proc("glGetQueryivEXT"));
    t.on = has && t.gen && t.begin && t.end && t.available && t.result;
    if (!t.on) {
        arm32::log("player: picture: no GPU timer here (no EXT_disjoint_timer_query): the passes' stats say their CPU time alone");
        return;
    }
    // Timestamps where the driver counts them: then the game's own time between the frames' passes too.
    GLint bits = 0;
    if (t.counter && t.query_iv) t.query_iv(GL_TIMESTAMP_EXT, GL_QUERY_COUNTER_BITS_EXT, &bits);
    t.stamps = bits > 0;
    for (int f = 0; f < GpuTimes::kRing; ++f) {
        t.gen(kSteps, t.queries[f]);
        t.gen(1, &t.ends[f]);
    }
    arm32::log("player: picture: GPU times by EXT_disjoint_timer_query (%s)", t.stamps ? "timestamps" : "elapsed time per pass; the game's own not known");
}

// The results of the ring's frames that are there, added to the sums; a frame whose results are not there yet stays.
void gpu_times_collect() {
    GpuTimes& t = g_gpu;
    if (!t.on) return;
    GLint disjoint = 0;
    // A clock change on the GPU (its speed, a power state) makes these results meaningless: they are dropped.
    static auto get_integer = reinterpret_cast<void (*)(GLenum, GLint*)>(arm32::gl_proc("glGetIntegerv"));
    if (get_integer) get_integer(GL_GPU_DISJOINT_EXT, &disjoint);
    if (disjoint) t.disjoint = true;
    for (int f = 0; f < GpuTimes::kRing; ++f) {
        if (!t.pending[f] || f == t.frame) continue;
        // Ready when its last query is (they finish in order).
        GLuint ready = 0;
        t.available(t.stamps ? t.ends[f] : t.queries[f][kSteps - 1], GL_QUERY_RESULT_AVAILABLE_EXT, &ready);
        if (t.stamps) {
            if (!ready) continue;
            GLuint64 end = 0;
            t.result(t.ends[f], GL_QUERY_RESULT_EXT, &end);
            // Each step from its start stamp to the next one's (or the end).
            GLuint64 next = end;
            for (int k = kSteps - 1; k >= 0; --k) {
                if (!t.used[f][k]) continue;
                GLuint64 at = 0;
                t.result(t.queries[f][k], GL_QUERY_RESULT_EXT, &at);
                if (!disjoint && next >= at) {
                    t.gpu_ns[k] += next - at;
                    ++t.gpu_frames[k];
                }
                next = at;
            }
        } else {
            // Each step's own elapsed time, when every one of them is there.
            bool all = true;
            for (int k = 0; k < kSteps && all; ++k) {
                if (!t.used[f][k]) continue;
                GLuint r = 0;
                t.available(t.queries[f][k], GL_QUERY_RESULT_AVAILABLE_EXT, &r);
                all = r != 0;
            }
            if (!all) continue;
            for (int k = 0; k < kSteps; ++k) {
                if (!t.used[f][k]) continue;
                GLuint64 ns = 0;
                t.result(t.queries[f][k], GL_QUERY_RESULT_EXT, &ns);
                if (!disjoint) {
                    t.gpu_ns[k] += ns;
                    ++t.gpu_frames[k];
                }
            }
        }
        t.pending[f] = false;
        for (bool& u : t.used[f]) u = false;
    }
}

// The CPU's time of each step since the last report, and the frames.
std::uint64_t g_cpu_ns[kSteps] = {};
std::uint64_t g_cpu_frames = 0, g_cpu_total_ns = 0;
// Where the current step started on the CPU.
std::int64_t g_step_from = 0;
int g_step = -1;

// A step of this frame's picture starts (the one before it ends): its CPU time from here, its GPU time by a timestamp or
// an elapsed-time query.
void step(int which) {
    const std::int64_t t = now_ns();
    if (g_step >= 0) g_cpu_ns[g_step] += static_cast<std::uint64_t>(t - g_step_from);
    g_step = which;
    g_step_from = t;
    GpuTimes& gt = g_gpu;
    if (!gt.on || which < 0) return;
    if (gt.stamps) {
        gt.counter(gt.queries[gt.frame][which], GL_TIMESTAMP_EXT);
    } else {
        if (gt.open >= 0) gt.end(GL_TIME_ELAPSED_EXT);
        gt.begin(GL_TIME_ELAPSED_EXT, gt.queries[gt.frame][which]);
        gt.open = which;
    }
    gt.used[gt.frame][which] = true;
}

// This frame's picture is done: the last step ends, the frame's end stamp, and the ring moves on.
void steps_done() {
    if (g_step >= 0) g_cpu_ns[g_step] += static_cast<std::uint64_t>(now_ns() - g_step_from);
    g_step = -1;
    GpuTimes& gt = g_gpu;
    if (!gt.on) return;
    if (gt.stamps) {
        gt.counter(gt.ends[gt.frame], GL_TIMESTAMP_EXT);
        // The game's time for the next frame: from here to its first step.
        const int next = (gt.frame + 1) % GpuTimes::kRing;
        gt.pending[gt.frame] = true;
        gt.frame = next;
        // A frame of the ring still waiting for its results is let go: its queries are about to be used again.
        gt.pending[next] = false;
        for (bool& u : gt.used[next]) u = false;
        gt.counter(gt.queries[next][kStepGame], GL_TIMESTAMP_EXT);
        gt.used[next][kStepGame] = true;
    } else {
        if (gt.open >= 0) gt.end(GL_TIME_ELAPSED_EXT);
        gt.open = -1;
        gt.pending[gt.frame] = true;
        gt.frame = (gt.frame + 1) % GpuTimes::kRing;
        gt.pending[gt.frame] = false;
        for (bool& u : gt.used[gt.frame]) u = false;
    }
}

// Every 5 s with the player's stats on: each step's mean CPU and GPU time a frame, and the bridge's own share (the swap
// as a whole, and the game's make-currents).
void report_steps(const char* what) {
    static std::int64_t last = 0;
    static std::uint64_t swaps0 = 0, swap_ns0 = 0, makes0 = 0;
    const std::int64_t t = now_ns();
    if (!last) last = t;
    if (t - last < 5000000000LL || !g_cpu_frames) return;
    const double seconds = static_cast<double>(t - last) / 1e9;
    last = t;
    gpu_times_collect();
    const std::uint64_t swaps = arm32::g_offscreen_swaps.load(), swap_ns = arm32::g_offscreen_swap_ns.load();
    const std::uint64_t makes = arm32::g_offscreen_make_currents.load();
    std::string line;
    char part[96];
    for (int k = 0; k < kSteps; ++k) {
        const bool cpu = g_cpu_ns[k] > 0, gpu = g_gpu.gpu_frames[k] > 0;
        if (!cpu && !gpu) continue;
        if (k == kStepGame) std::snprintf(part, sizeof part, " game GPU %.3f;", static_cast<double>(g_gpu.gpu_ns[k]) / static_cast<double>(g_gpu.gpu_frames[k]) / 1e6);
        else if (gpu)
            std::snprintf(part, sizeof part, " %s CPU %.3f GPU %.3f;", kStepNames[k], static_cast<double>(g_cpu_ns[k]) / static_cast<double>(g_cpu_frames) / 1e6,
                          static_cast<double>(g_gpu.gpu_ns[k]) / static_cast<double>(g_gpu.gpu_frames[k]) / 1e6);
        else std::snprintf(part, sizeof part, " %s CPU %.3f;", kStepNames[k], static_cast<double>(g_cpu_ns[k]) / static_cast<double>(g_cpu_frames) / 1e6);
        line += part;
    }
    const std::uint64_t n = swaps - swaps0;
    arm32::log("stats: picture (%s), ms a frame:%s the swap's whole CPU %.3f (the passes' %.3f), %.1f make-currents/s%s%s",
               what, line.c_str(), n ? static_cast<double>(swap_ns - swap_ns0) / static_cast<double>(n) / 1e6 : 0.0,
               static_cast<double>(g_cpu_total_ns) / static_cast<double>(g_cpu_frames) / 1e6, static_cast<double>(makes - makes0) / seconds,
               g_gpu.on ? "" : "; no GPU timer here", g_gpu.disjoint ? "; a GPU clock change dropped some" : "");
    swaps0 = swaps;
    swap_ns0 = swap_ns;
    makes0 = makes;
    for (std::uint64_t& v : g_cpu_ns) v = 0;
    g_cpu_frames = g_cpu_total_ns = 0;
    for (std::uint64_t& v : g_gpu.gpu_ns) v = 0;
    for (std::uint64_t& v : g_gpu.gpu_frames) v = 0;
    g_gpu.disjoint = false;
}

// The names of the passes in use, for the log.
std::string names(const Passes& p, bool scaled) {
    std::string s;
    if (p.aa == 1) s = "CMAA 2";
    else if (p.aa == 2) s = "SMAA";
    const char* up = !scaled ? nullptr : p.easu ? "AMD FSR 1" : p.nis ? "NVIDIA NIS" : nullptr;
    if (up) s += s.empty() ? up : std::string(" + ") + up;
    // No pass of its own drew the picture: the copy.
    else if (p.aa != 1 && p.aa != 2) s += s.empty() ? "a plain copy" : ", a plain copy";
    return s;
}

// `texture` bound for reading through the passes' own framebuffer, attached again only when it is another texture than
// last time (a new attachment makes the driver check the framebuffer again).
void read_from(const Gl& g, Passes& p, GLuint texture) {
    if (!p.read_fbo) g.gen_framebuffers(1, &p.read_fbo);
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, p.read_fbo);
    if (p.read_texture != texture) {
        g.framebuffer_texture(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
        p.read_texture = texture;
    }
}

// The bridge's hook (offscreen.h): the frame through the passes to the window's framebuffer.
bool present(const arm32::OffscreenFrame& f) {
    const Gl& g = gl();
    if (!g.ok) return false;
    Passes& p = g_passes;
    // A context the passes were not made in (the first frame, or the game's new context): made now, the game's state
    // as it was after.
    if (!p.made || p.context != f.context) {
        Saved saved;
        save_state(g, saved);
        if (p.cmaa2) cmaa2_forget(p.cmaa2);  // the old context's objects went with it
        make_passes(g, p, f.context);
        restore_state(g, saved);
    }
    static const bool finish = [] {
        const char* v = std::getenv("PLAYER_POST_FINISH");
        return v && *v == '1';
    }();
    if (finish) g.finish();
    const std::int64_t began = now_ns();
    // The GPU timer in this context (with the stats on), the results that are there taken in.
    if (arm32::g_stats) {
        gpu_times_start(g, f.context);
        gpu_times_collect();
    }
    const bool scaled = f.width != f.out_width || f.height != f.out_height;
    // Said once, then at each change of sizes: what the game draws at and what makes the window's picture of it.
    static int said_w = 0, said_h = 0, said_ow = 0, said_oh = 0;
    if (said_w != f.width || said_h != f.height || said_ow != f.out_width || said_oh != f.out_height) {
        said_w = f.width;
        said_h = f.height;
        said_ow = f.out_width;
        said_oh = f.out_height;
        const char* up = p.easu ? "AMD FSR 1" : p.nis ? "NVIDIA NIS" : "a plain stretch";
        if (scaled) arm32::log("player: the game draws at %dx%d, upscaled by %s to %dx%d", f.width, f.height, up, f.out_width, f.out_height);
        else arm32::log("player: the game draws at %dx%d, the window's own size: no upscaler", f.width, f.height);
        arm32::log("player: anti-aliasing: %s", p.aa == 1 ? "CMAA 2" : p.aa == 2 ? "SMAA" : "off");
    }
    Saved saved;
    save_state(g, saved);
    if (!size_targets(g, p, f.width, f.height, f.out_width, f.out_height)) {
        arm32::log("player: picture: the passes' pictures of %dx%d cannot be made here: a plain copy", f.width, f.height);
        p.aa = 0;
        p.easu = p.rcas = p.nis = 0;
    }
    for (GLenum s : kSwitches) g.disable(s);
    g.color_mask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    g.bind_vertex_array(p.vertex_array);
    GLuint source = f.texture;
    // Whether the upscaler (or the plain copy) still has to draw the window's picture.
    bool drawn = false;
    if (p.aa == 1 && p.cmaa2) {
        // CMAA 2 writes only the pixels it changes: its picture starts as a copy of the frame.
        if (arm32::g_stats) step(kStepCmaa2);
        read_from(g, p, source);
        g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, p.aa_fbo);
        g.blit(0, 0, f.width, f.height, 0, 0, f.width, f.height, GL_COLOR_BUFFER_BIT, GL_NEAREST);
        // Then CMAA 2 from the frame into it.
        if (cmaa2_run(p.cmaa2, source, p.aa_out, f.width, f.height)) source = p.aa_out;
    } else if (p.aa == 2) {
        const float metrics[4] = {1.0f / static_cast<float>(f.width), 1.0f / static_cast<float>(f.height), static_cast<float>(f.width),
                                  static_cast<float>(f.height)};
        g.clear_color(0, 0, 0, 0);
        // 1. Edges by luma: only the pixels on an edge are written (the rest are discarded), so cleared first.
        if (arm32::g_stats) step(kStepSmaaEdges);
        g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, p.edges_fbo);
        g.clear(GL_COLOR_BUFFER_BIT);
        bind_unit(g, 0, source);
        g.use_program(p.smaa_edges);
        g.uniform_vec4s(p.smaa_metrics[0], 1, metrics);
        draw(g, p.smaa_edges, p.edges_fbo, f.width, f.height);
        // 2. Blending weights from the edges and the tables.
        if (arm32::g_stats) step(kStepSmaaWeights);
        g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, p.weights_fbo);
        g.clear(GL_COLOR_BUFFER_BIT);
        bind_unit(g, 0, p.edges);
        bind_unit(g, 1, p.smaa_area);
        bind_unit(g, 2, p.smaa_search);
        g.use_program(p.smaa_weights);
        g.uniform_vec4s(p.smaa_metrics[1], 1, metrics);
        draw(g, p.smaa_weights, p.weights_fbo, f.width, f.height);
        // 3. Neighbourhood blending of the frame by the weights: straight to the window when nothing is scaled after.
        if (arm32::g_stats) step(kStepSmaaBlend);
        bind_unit(g, 0, source);
        bind_unit(g, 1, p.weights);
        g.use_program(p.smaa_blend);
        g.uniform_vec4s(p.smaa_metrics[2], 1, metrics);
        const bool last = !scaled;
        draw(g, p.smaa_blend, last ? 0 : p.aa_fbo, f.width, f.height);
        if (last) drawn = true;
        source = p.aa_out;
    }
    if (!drawn && scaled && p.easu) {
        // AMD FSR 1: EASU to the window's size, then RCAS from that to the window.
        if (arm32::g_stats) step(kStepEasu);
        bind_unit(g, 0, source);
        g.use_program(p.easu);
        // FsrEasuCon's con0 for a viewport of the whole frame.
        const float sx = static_cast<float>(f.width) / static_cast<float>(f.out_width);
        const float sy = static_cast<float>(f.height) / static_cast<float>(f.out_height);
        g.uniform_vec4(p.easu_con, sx, sy, 0.5f * sx - 0.5f, 0.5f * sy - 0.5f);
        draw(g, p.easu, p.easu_fbo, f.out_width, f.out_height);
        if (arm32::g_stats) step(kStepRcas);
        bind_unit(g, 0, p.easu_out);
        draw(g, p.rcas, 0, f.out_width, f.out_height);
        drawn = true;
    } else if (!drawn && scaled && p.nis) {
        // NVIDIA NIS: its scaler straight to the window, with its tables.
        if (arm32::g_stats) step(kStepNis);
        bind_unit(g, 0, source);
        bind_unit(g, 1, p.nis_scaler);
        bind_unit(g, 2, p.nis_usm);
        g.use_program(p.nis);
        NISConfig config{};
        NVScalerUpdateConfig(config, kNisSharpness, 0, 0, static_cast<uint32_t>(f.width), static_cast<uint32_t>(f.height),
                             static_cast<uint32_t>(f.width), static_cast<uint32_t>(f.height), 0, 0, static_cast<uint32_t>(f.out_width),
                             static_cast<uint32_t>(f.out_height), static_cast<uint32_t>(f.out_width), static_cast<uint32_t>(f.out_height));
        // Its first sixteen values in order, then the source's pixel size.
        const float values[20] = {config.kDetectRatio, config.kDetectThres, config.kMinContrastRatio, config.kRatioNorm,
                                  config.kContrastBoost, config.kEps, config.kSharpStartY, config.kSharpScaleY,
                                  config.kSharpStrengthMin, config.kSharpStrengthScale, config.kSharpLimitMin, config.kSharpLimitScale,
                                  config.kScaleX, config.kScaleY, config.kDstNormX, config.kDstNormY,
                                  config.kSrcNormX, config.kSrcNormY, 0, 0};
        g.uniform_vec4s(p.nis_config, 5, values);
        draw(g, p.nis, 0, f.out_width, f.out_height);
        drawn = true;
    }
    if (!drawn) {
        // A plain copy of the picture to the window, stretched when its size differs (no upscaler, or none here).
        if (arm32::g_stats) step(kStepCopy);
        read_from(g, p, source);
        g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, 0);
        g.blit(0, 0, f.width, f.height, 0, 0, f.out_width, f.out_height, GL_COLOR_BUFFER_BIT, scaled ? GL_LINEAR : GL_NEAREST);
    }
    if (arm32::g_stats) steps_done();
    restore_state(g, saved);
    if (finish) g.finish();
    // The cost on this thread: once in the log after the first 600 frames; with the stats on, every 5 s by step.
    const std::int64_t took = now_ns() - began;
    g_cpu_total_ns += static_cast<std::uint64_t>(took);
    ++g_cpu_frames;
    static std::uint64_t first_ns = 0, first_frames = 0;
    if (first_frames < 600) {
        first_ns += static_cast<std::uint64_t>(took);
        if (++first_frames == 600) {
            arm32::log("player: picture: %s took %.3f ms a frame on the render thread on average over its first 600 frames%s",
                       names(p, scaled).c_str(), static_cast<double>(first_ns) / 600.0 / 1e6, finish ? ", with the GPU's work waited for" : "");
        }
    }
    if (arm32::g_stats) report_steps(names(p, scaled).c_str());
    return true;
}

}  // namespace

void post_configure(int upscaler, int anti_aliasing, int render_scale) {
    // An upscaler only below 100 %: at the window's size there is nothing to scale.
    const int up = render_scale < 100 ? upscaler : 0;
    g_upscaler.store(up);
    g_anti_aliasing.store(anti_aliasing);
    // The frames go offscreen for any of these; with none, the bridge is as it was without them. A check can have them go
    // offscreen with neither (PLAYER_OFFSCREEN=1: a plain copy to the window), to measure the redirection by itself.
    const char* forced = std::getenv("PLAYER_OFFSCREEN");
    const bool offscreen = up != 0 || anti_aliasing != 0 || (forced && *forced == '1');
    // With an upscaler the window's surface keeps its own size, the picture drawn to it from the scaled frame.
    arm32::g_offscreen_window_size.store(up != 0);
    // CMAA 2's compute shaders want OpenGL ES 3.1.
    arm32::g_offscreen_es31.store(anti_aliasing == 1);
    arm32::g_offscreen_present.store(offscreen ? &present : nullptr);
    arm32::g_offscreen.store(offscreen);
}

}  // namespace player
