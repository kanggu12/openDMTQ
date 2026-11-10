// Intel's CMAA 2 (Conservative Morphological Anti-Aliasing, version 2.3) over the game's frame: the reference's four
// compute shaders (EdgesColor2x2CS, ComputeDispatchArgsCS, ProcessCandidatesCS, DeferredColorApply2x2CS), ported from
// its HLSL to GLSL ES 3.10, with its High preset and its defaults (luma edge detection computed in place, edges packed
// two to a texel, blend items collected in group memory). What differs from the reference, all of it for OpenGL ES:
//   - one shader storage buffer holds all of its buffers at offsets (the control and indirect arguments, the shape
//     candidates, the blend locations, the blend items and the per-quad list heads): ES 3.1 promises only four storage
//     blocks to a compute shader, and Direct3D 11 under ANGLE has eight UAV slots in all;
//   - the list heads are in that buffer, not a texture: an atomic exchange on an image needs an extension ES 3.1 lacks;
//   - the edge texture is R32UI (ES 3.1 has no R8UI images), still two pixels' edges a texel;
//   - the frame's colours are read clamped to its edge, where Direct3D's out-of-range loads read black (which would
//     find an edge along the picture's border and darken its corners), and every write into a buffer is checked
//     against its size, which Direct3D does for structured buffers by itself;
//   - the frame is an 8-bit RGBA texture holding sRGB values, as the reference's usual target (an sRGB texture read and
//     written through a UAV that converts by hand): read through the sRGB curve to linear, written back through it;
//   - the output is a separate texture holding a copy of the frame, written where CMAA 2 changes a pixel, as the
//     reference writes into its input.
#include "cmaa2.h"

#include "host.h"

#include <GLES3/gl31.h>

#include <cstdint>
#include <vector>

namespace player {

namespace {

// The shaders' source: the four passes, one chosen by a #define before it (CMAA2_PASS_*).
const char* kCmaa2 = R"(
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
// Copyright (c) 2018, Intel Corporation
//
// Licensed under the Apache License, Version 2.0 ( the "License" );
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
//
// Conservative Morphological Anti-Aliasing, version: 2.3
//
// Author(s):       Filip Strugar (filip.strugar@intel.com)
//
// More info:       https://github.com/GameTechDev/CMAA2
//
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
//
// Modified for OpenDMTQ (2026): ported from CMAA2.hlsl to GLSL ES 3.10 compute shaders (single sample, luma edge
// detection, High preset); all buffers in one storage buffer at offsets, the list heads among them; R32UI edges;
// colours read clamped to the picture's edge and through the sRGB curve; writes checked against the buffers' sizes.
precision highp float;
precision highp int;
precision highp image2D;
precision highp uimage2D;

#define CMAA2_CS_INPUT_KERNEL_SIZE_X 16
#define CMAA2_CS_INPUT_KERNEL_SIZE_Y 16
#define CMAA2_CS_OUTPUT_KERNEL_SIZE_X (CMAA2_CS_INPUT_KERNEL_SIZE_X - 2)
#define CMAA2_CS_OUTPUT_KERNEL_SIZE_Y (CMAA2_CS_INPUT_KERNEL_SIZE_Y - 2)
#define CMAA2_PROCESS_CANDIDATES_NUM_THREADS 128
#define CMAA2_DEFERRED_APPLY_NUM_THREADS 32
#define CMAA2_BLEND_ITEM_SLM_SIZE 768
// The High preset, without extra sharpness.
#define c_maxLineLength 86.0
#define g_CMAA2_EdgeThreshold 0.07
#define g_CMAA2_LocalContrastAdaptationAmount 0.10
#define g_CMAA2_SimpleShapeBlurinessAmount 0.10
#define c_symmetryCorrectionOffset 0.22
#define c_dampeningEffect 0.15

// The input colour, the output colour and the edges.
layout(binding = 0) uniform highp sampler2D g_inoutColorReadonly;
layout(rgba8, binding = 0) writeonly uniform highp image2D g_inoutColorWriteonly;
layout(r32ui, binding = 1) uniform highp uimage2D g_workingEdges;
// Every buffer, at its offset in 32-bit words: the control buffer's 16 words at 0 (its byte offsets of 4*N are word N
// here), the indirect arguments at 16, then the rest (g_*At), each with its capacity in items (g_*Max).
layout(std430, binding = 0) buffer Work { uint work[]; };
uniform ivec2 g_size;
uniform uint g_candidatesAt;
uniform uint g_candidatesMax;
uniform uint g_locationsAt;
uniform uint g_locationsMax;
uniform uint g_itemsAt;
uniform uint g_itemsMax;
uniform uint g_headsAt;
uniform uint g_headsPitch;
#define kIndirectAt 16u

bool Inside(ivec2 p) { return all(greaterThanEqual(p, ivec2(0))) && all(lessThan(p, g_size)); }

uint PackEdges(vec4 edges) { return uint(dot(edges, vec4(1.0, 2.0, 4.0, 8.0))); }
vec4 UnpackEdgesFlt(uint value) {
    return vec4(bvec4((value & 0x01u) != 0u, (value & 0x02u) != 0u, (value & 0x04u) != 0u, (value & 0x08u) != 0u));
}

float SRGB_to_LINEAR(float v) { return v <= 0.04045 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4); }
vec3 LoadSourceColor(ivec2 pixelPos, ivec2 offset) {
    vec3 c = texelFetch(g_inoutColorReadonly, clamp(pixelPos + offset, ivec2(0), g_size - 1), 0).rgb;
    return vec3(SRGB_to_LINEAR(c.r), SRGB_to_LINEAR(c.g), SRGB_to_LINEAR(c.b));
}

uint f32tof16(float x) { return packHalf2x16(vec2(x, 0.0)) & 0xFFFFu; }
float f16tof32(uint x) { return unpackHalf2x16(x).x; }
uint Pack_R11G11B10_E4_FLOAT(vec3 rgb) {
    rgb = clamp(rgb, 0.0, uintBitsToFloat(0x3FFFFFFFu));
    uint r = ((f32tof16(rgb.r) + 4u) >> 3) & 0x000007FFu;
    uint g = ((f32tof16(rgb.g) + 4u) << 8) & 0x003FF800u;
    uint b = ((f32tof16(rgb.b) + 8u) << 18) & 0xFFC00000u;
    return r | g | b;
}
vec3 Unpack_R11G11B10_E4_FLOAT(uint rgb) {
    float r = f16tof32((rgb << 3) & 0x3FF8u);
    float g = f16tof32((rgb >> 8) & 0x3FF8u);
    float b = f16tof32((rgb >> 18) & 0x3FF0u);
    return vec3(r, g, b);
}
vec3 InternalUnpackColor(uint packedColor) { return Unpack_R11G11B10_E4_FLOAT(packedColor); }
uint InternalPackColor(vec3 color) { return Pack_R11G11B10_E4_FLOAT(color); }

void StoreColorSample(ivec2 pixelPos, vec3 color, bool isComplexShape) {
    if (!Inside(pixelPos)) return;
    uint counterIndex = atomicAdd(work[12], 1u);
    if (counterIndex >= g_itemsMax) return;
    uvec2 quadPos = uvec2(pixelPos) / uvec2(2u, 2u);
    uint offsetXY = (uint(pixelPos.y) % 2u) * 2u + (uint(pixelPos.x) % 2u);
    uint header = (offsetXY << 30) | ((isComplexShape ? 1u : 0u) << 26);
    uint counterIndexWithHeader = counterIndex | header;
    uint originalIndex = atomicExchange(work[g_headsAt + quadPos.y * g_headsPitch + quadPos.x], counterIndexWithHeader);
    work[g_itemsAt + counterIndex * 2u] = originalIndex;
    work[g_itemsAt + counterIndex * 2u + 1u] = InternalPackColor(color);
    if (originalIndex == 0xFFFFFFFFu) {
        uint edgeListCounter = atomicAdd(work[8], 1u);
        if (edgeListCounter < g_locationsMax) work[g_locationsAt + edgeListCounter] = (quadPos.x << 16) | quadPos.y;
    }
}

float LINEAR_to_SRGB(float val) {
    if (val < 0.0031308) val *= 12.92;
    else val = 1.055 * pow(abs(val), 1.0 / 2.4) - 0.055;
    return val;
}
vec3 LINEAR_to_SRGB(vec3 val) { return vec3(LINEAR_to_SRGB(val.x), LINEAR_to_SRGB(val.y), LINEAR_to_SRGB(val.z)); }
void FinalUAVStore(ivec2 pixelPos, vec3 color) {
    if (!Inside(pixelPos)) return;
    imageStore(g_inoutColorWriteonly, pixelPos, vec4(LINEAR_to_SRGB(color), 1.0));
}

uint LoadEdge(ivec2 pixelPos, ivec2 offset) {
    ivec2 p = pixelPos + offset;
    if (!Inside(p)) return 0u;
    uint a = uint(p.x) % 2u;
    uint edge = imageLoad(g_workingEdges, ivec2(p.x / 2, p.y)).x;
    return (edge >> (a * 4u)) & 0xFu;
}

#ifdef CMAA2_PASS_EDGES
layout(local_size_x = CMAA2_CS_INPUT_KERNEL_SIZE_X, local_size_y = CMAA2_CS_INPUT_KERNEL_SIZE_Y, local_size_z = 1) in;
shared vec4 g_groupShared2x2FracEdgesH[CMAA2_CS_INPUT_KERNEL_SIZE_X * CMAA2_CS_INPUT_KERNEL_SIZE_Y];
shared vec4 g_groupShared2x2FracEdgesV[CMAA2_CS_INPUT_KERNEL_SIZE_X * CMAA2_CS_INPUT_KERNEL_SIZE_Y];
float RGBToLumaForEdges(vec3 linearRGB) { return dot(sqrt(linearRGB.rgb), vec3(0.299, 0.587, 0.114)); }
vec2 ComputeEdgeLuma(int x, int y, float pixelLumas[8]) {
    vec2 temp;
    temp.x = abs(pixelLumas[x + y * 3] - pixelLumas[x + 1 + y * 3]);
    temp.y = abs(pixelLumas[x + y * 3] - pixelLumas[x + (y + 1) * 3]);
    return temp;
}
// neighbourhood[x][y] of the reference, flattened as [x * 4 + y].
#define N(x, y) neighbourhood[(x) * 4 + (y)]
float ComputeLocalContrastV(int x, int y, vec2 neighbourhood[16]) {
    return max(max(N(x + 1, y + 0).y, N(x + 1, y + 1).y), max(N(x + 2, y + 0).y, N(x + 2, y + 1).y)) * g_CMAA2_LocalContrastAdaptationAmount;
}
float ComputeLocalContrastH(int x, int y, vec2 neighbourhood[16]) {
    return max(max(N(x + 0, y + 1).x, N(x + 1, y + 1).x), max(N(x + 0, y + 2).x, N(x + 1, y + 2).x)) * g_CMAA2_LocalContrastAdaptationAmount;
}
void GroupsharedLoadQuadHV(uint addr, out vec2 e00, out vec2 e10, out vec2 e01, out vec2 e11) {
    vec4 valH = g_groupShared2x2FracEdgesH[addr];
    e00.y = valH.x;
    e10.y = valH.y;
    e01.y = valH.z;
    e11.y = valH.w;
    vec4 valV = g_groupShared2x2FracEdgesV[addr];
    e00.x = valV.x;
    e10.x = valV.y;
    e01.x = valV.z;
    e11.x = valV.w;
}
void main() {
    uvec2 groupID = gl_WorkGroupID.xy;
    uvec2 groupThreadID = gl_LocalInvocationID.xy;
    ivec2 pixelPos = ivec2(groupID) * ivec2(CMAA2_CS_OUTPUT_KERNEL_SIZE_X, CMAA2_CS_OUTPUT_KERNEL_SIZE_Y) + ivec2(groupThreadID) - ivec2(1, 1);
    pixelPos *= ivec2(2, 2);
    const ivec2 qeOffsets[4] = ivec2[4](ivec2(0, 0), ivec2(1, 0), ivec2(0, 1), ivec2(1, 1));
    const uint rowStride2x2 = uint(CMAA2_CS_INPUT_KERNEL_SIZE_X);
    uint centerAddr2x2 = groupThreadID.x + groupThreadID.y * rowStride2x2;
    bool inOutputKernel = !any(bvec4(groupThreadID.x == uint(CMAA2_CS_INPUT_KERNEL_SIZE_X - 1), groupThreadID.x == 0u,
                                     groupThreadID.y == uint(CMAA2_CS_INPUT_KERNEL_SIZE_Y - 1), groupThreadID.y == 0u));
    vec2 qe0, qe1, qe2, qe3;
    uvec4 outEdges = uvec4(0u);
    float pixelLumas[8];
    for (int i = 0; i < 8; i++) pixelLumas[i] = RGBToLumaForEdges(LoadSourceColor(pixelPos, ivec2(i % 3, i / 3)));
    qe0 = ComputeEdgeLuma(0, 0, pixelLumas);
    qe1 = ComputeEdgeLuma(1, 0, pixelLumas);
    qe2 = ComputeEdgeLuma(0, 1, pixelLumas);
    qe3 = ComputeEdgeLuma(1, 1, pixelLumas);
    g_groupShared2x2FracEdgesV[centerAddr2x2 + rowStride2x2 * 0u] = vec4(qe0.x, qe1.x, qe2.x, qe3.x);
    g_groupShared2x2FracEdgesH[centerAddr2x2 + rowStride2x2 * 0u] = vec4(qe0.y, qe1.y, qe2.y, qe3.y);
    memoryBarrierShared();
    barrier();
    if (inOutputKernel) {
        vec2 topRow = g_groupShared2x2FracEdgesH[centerAddr2x2 - rowStride2x2].zw;
        vec2 leftColumn = g_groupShared2x2FracEdgesV[centerAddr2x2 - 1u].yw;
        bool someNonZeroEdges = any(notEqual(vec4(qe0, qe1) + vec4(qe2, qe3) + vec4(topRow[0], topRow[1], leftColumn[0], leftColumn[1]), vec4(0.0)));
        if (someNonZeroEdges) {
            uvec2 quad = uvec2(pixelPos) / uvec2(2u, 2u);
            if (Inside(pixelPos)) work[g_headsAt + quad.y * g_headsPitch + quad.x] = 0xFFFFFFFFu;
            vec4 ce[4];
            vec2 dummyd0, dummyd1, dummyd2;
            vec2 neighbourhood[16];
            GroupsharedLoadQuadHV(centerAddr2x2 - rowStride2x2 - 1u, dummyd0, dummyd1, dummyd2, N(0, 0));
            GroupsharedLoadQuadHV(centerAddr2x2 - rowStride2x2, dummyd0, dummyd1, N(1, 0), N(2, 0));
            GroupsharedLoadQuadHV(centerAddr2x2 - rowStride2x2 + 1u, dummyd0, dummyd1, N(3, 0), dummyd2);
            GroupsharedLoadQuadHV(centerAddr2x2 - 1u, dummyd0, N(0, 1), dummyd1, N(0, 2));
            GroupsharedLoadQuadHV(centerAddr2x2 + 1u, N(3, 1), dummyd0, N(3, 2), dummyd1);
            GroupsharedLoadQuadHV(centerAddr2x2 - 1u + rowStride2x2, dummyd0, N(0, 3), dummyd1, dummyd2);
            GroupsharedLoadQuadHV(centerAddr2x2 + rowStride2x2, N(1, 3), N(2, 3), dummyd0, dummyd1);
            N(1, 0).y = topRow[0];
            N(2, 0).y = topRow[1];
            N(0, 1).x = leftColumn[0];
            N(0, 2).x = leftColumn[1];
            N(1, 1) = qe0;
            N(2, 1) = qe1;
            N(1, 2) = qe2;
            N(2, 2) = qe3;
            topRow[0] = float((topRow[0] - ComputeLocalContrastH(0, -1, neighbourhood)) > g_CMAA2_EdgeThreshold);
            topRow[1] = float((topRow[1] - ComputeLocalContrastH(1, -1, neighbourhood)) > g_CMAA2_EdgeThreshold);
            leftColumn[0] = float((leftColumn[0] - ComputeLocalContrastV(-1, 0, neighbourhood)) > g_CMAA2_EdgeThreshold);
            leftColumn[1] = float((leftColumn[1] - ComputeLocalContrastV(-1, 1, neighbourhood)) > g_CMAA2_EdgeThreshold);
            ce[0].x = float((qe0.x - ComputeLocalContrastV(0, 0, neighbourhood)) > g_CMAA2_EdgeThreshold);
            ce[0].y = float((qe0.y - ComputeLocalContrastH(0, 0, neighbourhood)) > g_CMAA2_EdgeThreshold);
            ce[1].x = float((qe1.x - ComputeLocalContrastV(1, 0, neighbourhood)) > g_CMAA2_EdgeThreshold);
            ce[1].y = float((qe1.y - ComputeLocalContrastH(1, 0, neighbourhood)) > g_CMAA2_EdgeThreshold);
            ce[2].x = float((qe2.x - ComputeLocalContrastV(0, 1, neighbourhood)) > g_CMAA2_EdgeThreshold);
            ce[2].y = float((qe2.y - ComputeLocalContrastH(0, 1, neighbourhood)) > g_CMAA2_EdgeThreshold);
            ce[3].x = float((qe3.x - ComputeLocalContrastV(1, 1, neighbourhood)) > g_CMAA2_EdgeThreshold);
            ce[3].y = float((qe3.y - ComputeLocalContrastH(1, 1, neighbourhood)) > g_CMAA2_EdgeThreshold);
            ce[0].z = leftColumn[0];
            ce[1].z = ce[0].x;
            ce[2].z = leftColumn[1];
            ce[3].z = ce[2].x;
            ce[0].w = topRow[0];
            ce[1].w = topRow[1];
            ce[2].w = ce[0].y;
            ce[3].w = ce[1].y;
            for (int i = 0; i < 4; i++) {
                ivec2 localPixelPos = pixelPos + qeOffsets[i];
                vec4 edges = ce[i];
                bool isCandidate = (edges.x * edges.y + edges.y * edges.z + edges.z * edges.w + edges.w * edges.x) != 0.0;
                if (isCandidate && Inside(localPixelPos)) {
                    uint counterIndex = atomicAdd(work[4], 1u);
                    if (counterIndex < g_candidatesMax) work[g_candidatesAt + counterIndex] = (uint(localPixelPos.x) << 18) | uint(localPixelPos.y);
                }
                outEdges[i] = PackEdges(edges);
            }
        }
    }
    if (inOutputKernel && Inside(pixelPos)) {
        imageStore(g_workingEdges, ivec2(pixelPos.x / 2, pixelPos.y + 0), uvec4((outEdges[1] << 4) | outEdges[0]));
        if (pixelPos.y + 1 < g_size.y) imageStore(g_workingEdges, ivec2(pixelPos.x / 2, pixelPos.y + 1), uvec4((outEdges[3] << 4) | outEdges[2]));
    }
}
#endif

#ifdef CMAA2_PASS_DISPATCH_ARGS
layout(local_size_x = 1, local_size_y = 1, local_size_z = 1) in;
void main() {
    if (gl_WorkGroupID.x == 1u) {
        uint shapeCandidateCount = min(work[4], g_candidatesMax);
        work[kIndirectAt + 0u] = (shapeCandidateCount + uint(CMAA2_PROCESS_CANDIDATES_NUM_THREADS) - 1u) / uint(CMAA2_PROCESS_CANDIDATES_NUM_THREADS);
        work[kIndirectAt + 1u] = 1u;
        work[kIndirectAt + 2u] = 1u;
        work[3] = shapeCandidateCount;
    } else if (gl_WorkGroupID.y == 1u) {
        uint blendLocationCount = min(work[8], g_locationsMax);
        work[kIndirectAt + 0u] = 1u;
        work[kIndirectAt + 1u] = (blendLocationCount + uint(CMAA2_DEFERRED_APPLY_NUM_THREADS) - 1u) / uint(CMAA2_DEFERRED_APPLY_NUM_THREADS);
        work[kIndirectAt + 2u] = 1u;
        work[3] = blendLocationCount;
        work[4] = 0u;
        work[8] = 0u;
        work[12] = 0u;
    }
}
#endif

#ifdef CMAA2_PASS_PROCESS_CANDIDATES
layout(local_size_x = CMAA2_PROCESS_CANDIDATES_NUM_THREADS, local_size_y = 1, local_size_z = 1) in;
shared uint g_groupSharedBlendItemCount;
shared uvec2 g_groupSharedBlendItems[CMAA2_BLEND_ITEM_SLM_SIZE];
vec4 ComputeSimpleShapeBlendValues(vec4 edges, vec4 edgesLeft, vec4 edgesRight, vec4 edgesTop, vec4 edgesBottom, bool dontTestShapeValidity) {
    float fromRight = edges.r;
    float fromBelow = edges.g;
    float fromLeft = edges.b;
    float fromAbove = edges.a;
    float blurCoeff = g_CMAA2_SimpleShapeBlurinessAmount;
    float numberOfEdges = dot(edges, vec4(1.0, 1.0, 1.0, 1.0));
    float numberOfEdgesAllAround = dot(edgesLeft.bga + edgesRight.rga + edgesTop.rba + edgesBottom.rgb, vec3(1.0, 1.0, 1.0));
    if (!dontTestShapeValidity) {
        if (numberOfEdges == 1.0) blurCoeff = 0.0;
        if (numberOfEdges == 2.0) blurCoeff *= ((1.0 - fromBelow * fromAbove) * (1.0 - fromRight * fromLeft));
    }
    if (numberOfEdges == 2.0) {
        blurCoeff *= 0.75;
        float k = 0.9;
        fromRight += k * (edges.g * edgesTop.r * (1.0 - edgesLeft.g) + edges.a * edgesBottom.r * (1.0 - edgesLeft.a));
        fromBelow += k * (edges.b * edgesRight.g * (1.0 - edgesTop.b) + edges.r * edgesLeft.g * (1.0 - edgesTop.r));
        fromLeft += k * (edges.a * edgesBottom.b * (1.0 - edgesRight.a) + edges.g * edgesTop.b * (1.0 - edgesRight.g));
        fromAbove += k * (edges.r * edgesLeft.a * (1.0 - edgesBottom.r) + edges.b * edgesRight.a * (1.0 - edgesBottom.b));
    }
    blurCoeff *= clamp(1.30 - numberOfEdgesAllAround / 10.0, 0.0, 1.0);
    return vec4(fromLeft, fromAbove, fromRight, fromBelow) * blurCoeff;
}
void FindZLineLengths(out float lineLengthLeft, out float lineLengthRight, ivec2 screenPos, bool horizontal, bool invertedZShape, vec2 stepRight) {
    uint maskLeft, bitsContinueLeft, maskRight, bitsContinueRight;
    {
        uint maskTraceLeft, maskTraceRight;
        if (horizontal) {
            maskTraceLeft = 0x08u;
            maskTraceRight = 0x02u;
        } else {
            maskTraceLeft = 0x04u;
            maskTraceRight = 0x01u;
        }
        if (invertedZShape) {
            uint temp = maskTraceLeft;
            maskTraceLeft = maskTraceRight;
            maskTraceRight = temp;
        }
        maskLeft = maskTraceLeft;
        bitsContinueLeft = maskTraceLeft;
        maskRight = maskTraceRight;
        bitsContinueRight = maskTraceRight;
    }
    bool continueLeft = true;
    bool continueRight = true;
    lineLengthLeft = 1.0;
    lineLengthRight = 1.0;
    for (;;) {
        uint edgeLeft = LoadEdge(ivec2(vec2(screenPos) - stepRight * float(lineLengthLeft)), ivec2(0, 0));
        uint edgeRight = LoadEdge(ivec2(vec2(screenPos) + stepRight * (float(lineLengthRight) + 1.0)), ivec2(0, 0));
        continueLeft = continueLeft && ((edgeLeft & maskLeft) == bitsContinueLeft);
        continueRight = continueRight && ((edgeRight & maskRight) == bitsContinueRight);
        lineLengthLeft += continueLeft ? 1.0 : 0.0;
        lineLengthRight += continueRight ? 1.0 : 0.0;
        float maxLR = max(lineLengthRight, lineLengthLeft);
        if (!continueLeft && !continueRight) maxLR = c_maxLineLength;
        if (maxLR >= min(c_maxLineLength, (1.25 * min(lineLengthRight, lineLengthLeft) - 0.25))) break;
    }
}
bool CollectBlendZs(ivec2 screenPos, bool horizontal, bool invertedZShape, float shapeQualityScore, float lineLengthLeft, float lineLengthRight, vec2 stepRight) {
    float leftOdd = c_symmetryCorrectionOffset * mod(lineLengthLeft, 2.0);
    float rightOdd = c_symmetryCorrectionOffset * mod(lineLengthRight, 2.0);
    float dampenEffect = clamp(float(lineLengthLeft + lineLengthRight - shapeQualityScore) * c_dampeningEffect, 0.0, 1.0);
    float loopFrom = -floor((lineLengthLeft + 1.0) / 2.0) + 1.0;
    float loopTo = floor((lineLengthRight + 1.0) / 2.0);
    uint blendItemCount = uint(loopTo - loopFrom + 1.0);
    uint itemIndex = atomicAdd(g_groupSharedBlendItemCount, blendItemCount);
    if ((itemIndex + blendItemCount) > uint(CMAA2_BLEND_ITEM_SLM_SIZE)) return false;
    float totalLength = float(loopTo - loopFrom) + 1.0 - leftOdd - rightOdd;
    float lerpStep = 1.0 / totalLength;
    float lerpFromK = (0.5 - leftOdd - loopFrom) * lerpStep;
    uint itemHeader = (uint(screenPos.x) << 18) | uint(screenPos.y);
    uint itemValStatic = ((horizontal ? 1u : 0u) << 31) | ((invertedZShape ? 1u : 0u) << 30);
    for (float i = loopFrom; i <= loopTo; i++) {
        float secondPart = float(i > 0.0);
        float srcOffset = 1.0 - secondPart * 2.0;
        float lerpK = (lerpStep * i + lerpFromK) * srcOffset + secondPart;
        lerpK *= dampenEffect;
        uvec2 encodedItem;
        encodedItem.x = itemHeader;
        encodedItem.y = itemValStatic | (uint(i + 256.0) << 20) | (uint(srcOffset + 256.0) << 10) | uint(clamp(lerpK, 0.0, 1.0) * 1023.0 + 0.5);
        g_groupSharedBlendItems[itemIndex++] = encodedItem;
    }
    return true;
}
void BlendZs(ivec2 screenPos, bool horizontal, bool invertedZShape, float shapeQualityScore, float lineLengthLeft, float lineLengthRight, vec2 stepRight) {
    vec2 blendDir = (horizontal) ? (vec2(0.0, -1.0)) : (vec2(-1.0, 0.0));
    if (invertedZShape) blendDir = -blendDir;
    float leftOdd = c_symmetryCorrectionOffset * mod(lineLengthLeft, 2.0);
    float rightOdd = c_symmetryCorrectionOffset * mod(lineLengthRight, 2.0);
    float dampenEffect = clamp(float(lineLengthLeft + lineLengthRight - shapeQualityScore) * c_dampeningEffect, 0.0, 1.0);
    float loopFrom = -floor((lineLengthLeft + 1.0) / 2.0) + 1.0;
    float loopTo = floor((lineLengthRight + 1.0) / 2.0);
    float totalLength = float(loopTo - loopFrom) + 1.0 - leftOdd - rightOdd;
    float lerpStep = 1.0 / totalLength;
    float lerpFromK = (0.5 - leftOdd - loopFrom) * lerpStep;
    for (float i = loopFrom; i <= loopTo; i++) {
        float secondPart = float(i > 0.0);
        float srcOffset = 1.0 - secondPart * 2.0;
        float lerpK = (lerpStep * i + lerpFromK) * srcOffset + secondPart;
        lerpK *= dampenEffect;
        vec2 pixelPos = vec2(screenPos) + stepRight * float(i);
        vec3 colorCenter = LoadSourceColor(ivec2(pixelPos), ivec2(0, 0)).rgb;
        vec3 colorFrom = LoadSourceColor(ivec2(pixelPos.xy + blendDir * vec2(srcOffset)), ivec2(0, 0)).rgb;
        vec3 outputColor = mix(colorCenter.rgb, colorFrom.rgb, lerpK);
        StoreColorSample(ivec2(pixelPos.xy), outputColor, true);
    }
}
void DetectZsHorizontal(vec4 edges, vec4 edgesM1P0, vec4 edgesP1P0, vec4 edgesP2P0, out float invertedZScore, out float normalZScore) {
    {
        invertedZScore = edges.r * edges.g * edgesP1P0.a;
        invertedZScore *= 2.0 + ((edgesM1P0.g + edgesP2P0.a)) - (edges.a + edgesP1P0.g) - 0.7 * (edgesP2P0.g + edgesM1P0.a + edges.b + edgesP1P0.r);
    }
    {
        normalZScore = edges.r * edges.a * edgesP1P0.g;
        normalZScore *= 2.0 + ((edgesM1P0.a + edgesP2P0.g)) - (edges.g + edgesP1P0.a) - 0.7 * (edgesP2P0.a + edgesM1P0.g + edges.b + edgesP1P0.r);
    }
}
void main() {
    uint dispatchThreadID = gl_GlobalInvocationID.x;
    uint groupThreadID = gl_LocalInvocationID.x;
    if (groupThreadID == 0u) g_groupSharedBlendItemCount = 0u;
    memoryBarrierShared();
    barrier();
    uint numCandidates = work[3];
    if (dispatchThreadID < numCandidates) {
        uint pixelID = work[g_candidatesAt + dispatchThreadID];
        ivec2 pixelPos = ivec2(int(pixelID >> 18), int(pixelID & 0x3FFFu));
        uint edgesCenterPacked = LoadEdge(pixelPos, ivec2(0, 0));
        vec4 edges = UnpackEdgesFlt(edgesCenterPacked);
        vec4 edgesLeft = UnpackEdgesFlt(LoadEdge(pixelPos, ivec2(-1, 0)));
        vec4 edgesRight = UnpackEdgesFlt(LoadEdge(pixelPos, ivec2(1, 0)));
        vec4 edgesBottom = UnpackEdgesFlt(LoadEdge(pixelPos, ivec2(0, 1)));
        vec4 edgesTop = UnpackEdgesFlt(LoadEdge(pixelPos, ivec2(0, -1)));
        {
            vec4 blendVal = ComputeSimpleShapeBlendValues(edges, edgesLeft, edgesRight, edgesTop, edgesBottom, true);
            float fourWeightSum = dot(blendVal, vec4(1.0, 1.0, 1.0, 1.0));
            float centerWeight = 1.0 - fourWeightSum;
            vec3 outColor = LoadSourceColor(pixelPos, ivec2(0, 0)).rgb * centerWeight;
            if (blendVal.x > 0.0) outColor.rgb += blendVal.x * LoadSourceColor(pixelPos, ivec2(-1, 0)).rgb;
            if (blendVal.y > 0.0) outColor.rgb += blendVal.y * LoadSourceColor(pixelPos, ivec2(0, -1)).rgb;
            if (blendVal.z > 0.0) outColor.rgb += blendVal.z * LoadSourceColor(pixelPos, ivec2(1, 0)).rgb;
            if (blendVal.w > 0.0) outColor.rgb += blendVal.w * LoadSourceColor(pixelPos, ivec2(0, 1)).rgb;
            StoreColorSample(pixelPos, outColor, false);
        }
        {
            float invertedZScore;
            float normalZScore;
            float maxScore;
            bool horizontal = true;
            bool invertedZ = false;
            {
                vec4 edgesM1P0 = edgesLeft;
                vec4 edgesP1P0 = edgesRight;
                vec4 edgesP2P0 = UnpackEdgesFlt(LoadEdge(pixelPos, ivec2(2, 0)));
                DetectZsHorizontal(edges, edgesM1P0, edgesP1P0, edgesP2P0, invertedZScore, normalZScore);
                maxScore = max(invertedZScore, normalZScore);
                if (maxScore > 0.0) invertedZ = invertedZScore > normalZScore;
            }
            {
                vec4 edgesM1P0 = edgesBottom;
                vec4 edgesP1P0 = edgesTop;
                vec4 edgesP2P0 = UnpackEdgesFlt(LoadEdge(pixelPos, ivec2(0, -2)));
                DetectZsHorizontal(edges.argb, edgesM1P0.argb, edgesP1P0.argb, edgesP2P0.argb, invertedZScore, normalZScore);
                float vertScore = max(invertedZScore, normalZScore);
                if (vertScore > maxScore) {
                    maxScore = vertScore;
                    horizontal = false;
                    invertedZ = invertedZScore > normalZScore;
                }
            }
            if (maxScore > 0.0) {
                float shapeQualityScore = floor(clamp(4.0 - maxScore, 0.0, 3.0));
                vec2 stepRight = (horizontal) ? (vec2(1.0, 0.0)) : (vec2(0.0, -1.0));
                float lineLengthLeft, lineLengthRight;
                FindZLineLengths(lineLengthLeft, lineLengthRight, pixelPos, horizontal, invertedZ, stepRight);
                lineLengthLeft -= shapeQualityScore;
                lineLengthRight -= shapeQualityScore;
                if ((lineLengthLeft + lineLengthRight) >= (5.0)) {
                    if (!CollectBlendZs(pixelPos, horizontal, invertedZ, shapeQualityScore, lineLengthLeft, lineLengthRight, stepRight))
                        BlendZs(pixelPos, horizontal, invertedZ, shapeQualityScore, lineLengthLeft, lineLengthRight, stepRight);
                }
            }
        }
    }
    memoryBarrierShared();
    barrier();
    uint totalItemCount = min(uint(CMAA2_BLEND_ITEM_SLM_SIZE), g_groupSharedBlendItemCount);
    uint loops = (totalItemCount + (uint(CMAA2_PROCESS_CANDIDATES_NUM_THREADS) - 1u) - groupThreadID) / uint(CMAA2_PROCESS_CANDIDATES_NUM_THREADS);
    for (uint loop = 0u; loop < loops; loop++) {
        uint index = loop * uint(CMAA2_PROCESS_CANDIDATES_NUM_THREADS) + groupThreadID;
        uvec2 itemVal = g_groupSharedBlendItems[index];
        ivec2 startingPos = ivec2(int(itemVal.x >> 18), int(itemVal.x & 0x3FFFu));
        bool itemHorizontal = ((itemVal.y >> 31) & 1u) != 0u;
        bool itemInvertedZ = ((itemVal.y >> 30) & 1u) != 0u;
        float itemStepIndex = float((itemVal.y >> 20) & 0x3FFu) - 256.0;
        float itemSrcOffset = float((itemVal.y >> 10) & 0x3FFu) - 256.0;
        float itemLerpK = float(itemVal.y & 0x3FFu) / 1023.0;
        vec2 itemStepRight = (itemHorizontal) ? (vec2(1.0, 0.0)) : (vec2(0.0, -1.0));
        vec2 itemBlendDir = (itemHorizontal) ? (vec2(0.0, -1.0)) : (vec2(-1.0, 0.0));
        if (itemInvertedZ) itemBlendDir = -itemBlendDir;
        vec2 itemPixelPos = vec2(startingPos) + itemStepRight * float(itemStepIndex);
        vec3 colorCenter = LoadSourceColor(ivec2(itemPixelPos), ivec2(0, 0)).rgb;
        vec3 colorFrom = LoadSourceColor(ivec2(itemPixelPos.xy + itemBlendDir * vec2(itemSrcOffset)), ivec2(0, 0)).rgb;
        vec3 outputColor = mix(colorCenter.rgb, colorFrom.rgb, itemLerpK);
        StoreColorSample(ivec2(itemPixelPos.xy), outputColor, true);
    }
}
#endif

#ifdef CMAA2_PASS_DEFERRED_APPLY
layout(local_size_x = 4, local_size_y = CMAA2_DEFERRED_APPLY_NUM_THREADS, local_size_z = 1) in;
void main() {
    uint numCandidates = work[3];
    uint currentCandidate = gl_GlobalInvocationID.y;
    uint currentQuadOffsetXY = gl_LocalInvocationID.x;
    if (currentCandidate >= numCandidates) return;
    uint pixelID = work[g_locationsAt + currentCandidate];
    uvec2 quadPos = uvec2((pixelID >> 16), pixelID & 0xFFFFu);
    const ivec2 qeOffsets[4] = ivec2[4](ivec2(0, 0), ivec2(1, 0), ivec2(0, 1), ivec2(1, 1));
    ivec2 pixelPos = ivec2(quadPos) * 2 + qeOffsets[currentQuadOffsetXY];
    uint counterIndexWithHeader = work[g_headsAt + quadPos.y * g_headsPitch + quadPos.x];
    vec4 outColors = vec4(0.0, 0.0, 0.0, 0.0);
    const uint maxLoops = 32u;
    for (uint i = 0u; (counterIndexWithHeader != 0xFFFFFFFFu) && (i < maxLoops); i++) {
        uint offsetXY = (counterIndexWithHeader >> 30) & 0x03u;
        bool isComplexShape = ((counterIndexWithHeader >> 26) & 0x01u) != 0u;
        uint item = counterIndexWithHeader & ((1u << 26) - 1u);
        // A head left from an earlier frame may point past this frame's items: the list ends there.
        if (item >= g_itemsMax) break;
        uvec2 val = uvec2(work[g_itemsAt + item * 2u], work[g_itemsAt + item * 2u + 1u]);
        counterIndexWithHeader = val.x;
        if (offsetXY == currentQuadOffsetXY) {
            vec3 color = InternalUnpackColor(val.y);
            float weight = 0.8 + 1.0 * float(isComplexShape);
            outColors += vec4(color * weight, weight);
        }
    }
    if (outColors.a == 0.0) return;
    vec4 outColor = outColors;
    outColor.rgb /= outColor.a;
    FinalUAVStore(pixelPos, vec3(outColor.rgb));
}
#endif
)";

// The host's GL entry points CMAA 2 needs beyond the passes' own, looked up once.
struct Gl {
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
    PFNGLUNIFORM1UIPROC uniform_uint;
    PFNGLUNIFORM2IPROC uniform_ivec2;
    PFNGLUNIFORM1IPROC uniform_int;
    PFNGLGETINTEGERVPROC get_integer;
    PFNGLGETINTEGERI_VPROC get_integer_i;
    PFNGLGETINTEGER64I_VPROC get_integer64_i;
    PFNGLGETBOOLEANI_VPROC get_boolean_i;
    PFNGLGENBUFFERSPROC gen_buffers;
    PFNGLDELETEBUFFERSPROC delete_buffers;
    PFNGLBINDBUFFERPROC bind_buffer;
    PFNGLBINDBUFFERBASEPROC bind_buffer_base;
    PFNGLBINDBUFFERRANGEPROC bind_buffer_range;
    PFNGLBUFFERDATAPROC buffer_data;
    PFNGLGENTEXTURESPROC gen_textures;
    PFNGLDELETETEXTURESPROC delete_textures;
    PFNGLBINDTEXTUREPROC bind_texture;
    PFNGLACTIVETEXTUREPROC active_texture;
    PFNGLTEXSTORAGE2DPROC tex_storage;
    PFNGLBINDIMAGETEXTUREPROC bind_image;
    PFNGLDISPATCHCOMPUTEPROC dispatch;
    PFNGLDISPATCHCOMPUTEINDIRECTPROC dispatch_indirect;
    PFNGLMEMORYBARRIERPROC memory_barrier;
    PFNGLGETERRORPROC get_error;
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
        look_up(x.uniform_uint, "glUniform1ui", ok);
        look_up(x.uniform_ivec2, "glUniform2i", ok);
        look_up(x.uniform_int, "glUniform1i", ok);
        look_up(x.get_integer, "glGetIntegerv", ok);
        look_up(x.get_integer_i, "glGetIntegeri_v", ok);
        look_up(x.get_integer64_i, "glGetInteger64i_v", ok);
        look_up(x.get_boolean_i, "glGetBooleani_v", ok);
        look_up(x.gen_buffers, "glGenBuffers", ok);
        look_up(x.delete_buffers, "glDeleteBuffers", ok);
        look_up(x.bind_buffer, "glBindBuffer", ok);
        look_up(x.bind_buffer_base, "glBindBufferBase", ok);
        look_up(x.bind_buffer_range, "glBindBufferRange", ok);
        look_up(x.buffer_data, "glBufferData", ok);
        look_up(x.gen_textures, "glGenTextures", ok);
        look_up(x.delete_textures, "glDeleteTextures", ok);
        look_up(x.bind_texture, "glBindTexture", ok);
        look_up(x.active_texture, "glActiveTexture", ok);
        look_up(x.tex_storage, "glTexStorage2D", ok);
        look_up(x.bind_image, "glBindImageTexture", ok);
        look_up(x.dispatch, "glDispatchCompute", ok);
        look_up(x.dispatch_indirect, "glDispatchComputeIndirect", ok);
        look_up(x.memory_barrier, "glMemoryBarrier", ok);
        look_up(x.get_error, "glGetError", ok);
        x.ok = ok;
        return x;
    }();
    return g;
}

// The passes in the order they run, each the source with its #define.
enum Pass { kEdges, kDispatchArgs, kProcessCandidates, kDeferredApply, kPasses };
const char* const kPassDefines[kPasses] = {"#define CMAA2_PASS_EDGES 1\n", "#define CMAA2_PASS_DISPATCH_ARGS 1\n",
                                           "#define CMAA2_PASS_PROCESS_CANDIDATES 1\n", "#define CMAA2_PASS_DEFERRED_APPLY 1\n"};
const char* const kPassNames[kPasses] = {"EdgesColor2x2CS", "ComputeDispatchArgsCS", "ProcessCandidatesCS", "DeferredColorApply2x2CS"};
// The uniforms every pass declares, set before each run.
enum Uniform { kSize, kCandidatesAt, kCandidatesMax, kLocationsAt, kLocationsMax, kItemsAt, kItemsMax, kHeadsAt, kHeadsPitch, kUniforms };
const char* const kUniformNames[kUniforms] = {"g_size", "g_candidatesAt", "g_candidatesMax", "g_locationsAt", "g_locationsMax",
                                              "g_itemsAt", "g_itemsMax", "g_headsAt", "g_headsPitch"};

}  // namespace

struct Cmaa2 {
    GLuint programs[kPasses] = {};
    GLint uniforms[kPasses][kUniforms] = {};
    // The working buffer and the edges, for frames of this size.
    int width = 0, height = 0;
    GLuint work = 0, edges = 0;
    // The buffer's layout in 32-bit words (cmaa2.cpp's header says what is where).
    std::uint32_t candidates_at = 0, candidates_max = 0, locations_at = 0, locations_max = 0, items_at = 0, items_max = 0, heads_at = 0,
                  heads_pitch = 0;
};

namespace {

// A compute program of the source for one pass; 0 and its log said when it fails.
GLuint build(const Gl& g, Pass pass) {
    const char* texts[3] = {"#version 310 es\n", kPassDefines[pass], kCmaa2};
    GLuint shader = g.create_shader(GL_COMPUTE_SHADER);
    g.shader_source(shader, 3, texts, nullptr);
    g.compile_shader(shader);
    GLint ok = 0;
    g.get_shader(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char why[1024] = "";
        g.shader_log(shader, sizeof why, nullptr, why);
        arm32::log("player: picture: CMAA 2's %s does not compile: %s", kPassNames[pass], why);
        g.delete_shader(shader);
        return 0;
    }
    GLuint program = g.create_program();
    g.attach_shader(program, shader);
    g.link_program(program);
    g.delete_shader(shader);
    g.get_program(program, GL_LINK_STATUS, &ok);
    if (!ok) {
        char why[1024] = "";
        g.program_log(program, sizeof why, nullptr, why);
        arm32::log("player: picture: CMAA 2's %s does not link: %s", kPassNames[pass], why);
        g.delete_program(program);
        return 0;
    }
    return program;
}

// The working buffer and the edges for `w` x `h`, at the reference's sizes ("99.99 % safe": a quarter of the pixels as
// candidates, half as blend items, a sixth as blend locations), its list heads empty and its counters 0.
bool size_buffers(const Gl& g, Cmaa2& c, int w, int h) {
    if (c.width == w && c.height == h && c.work) return true;
    g.delete_buffers(1, &c.work);
    g.delete_textures(1, &c.edges);
    c.work = c.edges = 0;
    const std::uint32_t pixels = static_cast<std::uint32_t>(w) * static_cast<std::uint32_t>(h);
    c.heads_pitch = static_cast<std::uint32_t>((w + 1) / 2);
    const std::uint32_t heads = c.heads_pitch * static_cast<std::uint32_t>((h + 1) / 2);
    // The control buffer's 16 words, the indirect arguments' 3 at word 16, then the rest.
    c.candidates_at = 20;
    c.candidates_max = pixels / 4;
    c.locations_at = c.candidates_at + c.candidates_max;
    c.locations_max = (pixels + 3) / 6;
    c.items_at = c.locations_at + c.locations_max;
    c.items_max = pixels / 2;
    c.heads_at = c.items_at + c.items_max * 2;
    const std::uint32_t words = c.heads_at + heads;
    std::vector<std::uint32_t> init(words, 0);
    // Empty lists: a head of all ones ends a list.
    for (std::uint32_t i = 0; i < heads; ++i) init[c.heads_at + i] = 0xFFFFFFFFu;
    GLint was_buffer = 0;
    g.get_integer(GL_SHADER_STORAGE_BUFFER_BINDING, &was_buffer);
    g.gen_buffers(1, &c.work);
    g.bind_buffer(GL_SHADER_STORAGE_BUFFER, c.work);
    g.buffer_data(GL_SHADER_STORAGE_BUFFER, static_cast<GLsizeiptr>(words) * 4, init.data(), GL_DYNAMIC_COPY);
    g.bind_buffer(GL_SHADER_STORAGE_BUFFER, static_cast<GLuint>(was_buffer));
    // The edges: two pixels' four bits a texel, as R32UI.
    GLint was_texture = 0;
    g.get_integer(GL_TEXTURE_BINDING_2D, &was_texture);
    g.gen_textures(1, &c.edges);
    g.bind_texture(GL_TEXTURE_2D, c.edges);
    g.tex_storage(GL_TEXTURE_2D, 1, GL_R32UI, static_cast<GLsizei>(c.heads_pitch), h);
    g.bind_texture(GL_TEXTURE_2D, static_cast<GLuint>(was_texture));
    c.width = w;
    c.height = h;
    return c.work && c.edges;
}

// An image unit's binding, saved and put back.
struct ImageUnit {
    GLint name = 0, level = 0, layer = 0, access = GL_READ_ONLY, format = GL_R32UI;
    GLboolean layered = GL_FALSE;
};

void save_image(const Gl& g, GLuint unit, ImageUnit& u) {
    g.get_integer_i(GL_IMAGE_BINDING_NAME, unit, &u.name);
    g.get_integer_i(GL_IMAGE_BINDING_LEVEL, unit, &u.level);
    g.get_integer_i(GL_IMAGE_BINDING_LAYER, unit, &u.layer);
    g.get_integer_i(GL_IMAGE_BINDING_ACCESS, unit, &u.access);
    g.get_integer_i(GL_IMAGE_BINDING_FORMAT, unit, &u.format);
    g.get_boolean_i(GL_IMAGE_BINDING_LAYERED, unit, &u.layered);
}

void restore_image(const Gl& g, GLuint unit, const ImageUnit& u) {
    g.bind_image(unit, static_cast<GLuint>(u.name), u.level, u.layered, u.layer, static_cast<GLenum>(u.access), static_cast<GLenum>(u.format));
}

}  // namespace

Cmaa2* cmaa2_make() {
    const Gl& g = gl();
    if (!g.ok) return nullptr;
    // Its group memory: the edge pass's two tables of 16 x 16 vec4s is the most.
    GLint shared = 0;
    g.get_integer(GL_MAX_COMPUTE_SHARED_MEMORY_SIZE, &shared);
    if (shared < 16 * 16 * 16 * 2) {
        arm32::log("player: picture: CMAA 2 needs %d bytes of group memory, this graphics card has %d", 16 * 16 * 16 * 2, shared);
        return nullptr;
    }
    auto* c = new Cmaa2;
    for (int p = 0; p < kPasses; ++p) {
        c->programs[p] = build(g, static_cast<Pass>(p));
        if (!c->programs[p]) {
            for (int q = 0; q < p; ++q) g.delete_program(c->programs[q]);
            delete c;
            return nullptr;
        }
        for (int u = 0; u < kUniforms; ++u) c->uniforms[p][u] = g.uniform_location(c->programs[p], kUniformNames[u]);
        // The colour's sampler on texture unit 0 (its binding says so too; set for drivers that read only this).
        g.use_program(c->programs[p]);
        GLint sampler = g.uniform_location(c->programs[p], "g_inoutColorReadonly");
        if (sampler >= 0) g.uniform_int(sampler, 0);
    }
    // A run over a small picture of its own: a driver may build a compute shader only at its first dispatch, and refuse
    // it there (Wine's Direct3D shader compiler, under ANGLE, has no loads from a storage buffer). An error left by the
    // game before this, at its first frame, is read here too.
    while (g.get_error() != GL_NO_ERROR) {
    }
    GLint was_texture = 0;
    g.get_integer(GL_TEXTURE_BINDING_2D, &was_texture);
    GLuint test[2] = {0, 0};
    g.gen_textures(2, test);
    for (GLuint t : test) {
        g.bind_texture(GL_TEXTURE_2D, t);
        g.tex_storage(GL_TEXTURE_2D, 1, GL_RGBA8, 16, 16);
    }
    g.bind_texture(GL_TEXTURE_2D, static_cast<GLuint>(was_texture));
    const bool ran = cmaa2_run(c, test[0], test[1], 16, 16);
    const GLenum error = g.get_error();
    g.delete_textures(2, test);
    // Its buffers go too: the frame's own size makes them again.
    g.delete_buffers(1, &c->work);
    g.delete_textures(1, &c->edges);
    c->work = c->edges = 0;
    c->width = c->height = 0;
    if (!ran || error != GL_NO_ERROR) {
        arm32::log("player: picture: CMAA 2's compute shaders do not run here (GL error %#x at their first run)", error);
        for (GLuint program : c->programs) g.delete_program(program);
        delete c;
        return nullptr;
    }
    return c;
}

bool cmaa2_run(Cmaa2* c, unsigned source, unsigned out, int width, int height) {
    const Gl& g = gl();
    if (!size_buffers(g, *c, width, height)) return false;
    // The compute state it binds, as the game left it: the storage buffer's generic and first indexed binding, the
    // indirect dispatch buffer, and image units 0 and 1.
    GLint was_storage = 0, was_storage0 = 0, was_indirect = 0;
    GLint64 was_start = 0, was_size = 0;
    g.get_integer(GL_SHADER_STORAGE_BUFFER_BINDING, &was_storage);
    g.get_integer_i(GL_SHADER_STORAGE_BUFFER_BINDING, 0, &was_storage0);
    g.get_integer64_i(GL_SHADER_STORAGE_BUFFER_START, 0, &was_start);
    g.get_integer64_i(GL_SHADER_STORAGE_BUFFER_SIZE, 0, &was_size);
    g.get_integer(GL_DISPATCH_INDIRECT_BUFFER_BINDING, &was_indirect);
    ImageUnit was_images[2];
    save_image(g, 0, was_images[0]);
    save_image(g, 1, was_images[1]);
    // Its own: the buffer for every pass, the output and the edges as images, the frame on texture unit 0.
    g.bind_buffer_base(GL_SHADER_STORAGE_BUFFER, 0, c->work);
    g.bind_buffer(GL_DISPATCH_INDIRECT_BUFFER, c->work);
    g.bind_image(0, out, 0, GL_FALSE, 0, GL_WRITE_ONLY, GL_RGBA8);
    g.bind_image(1, c->edges, 0, GL_FALSE, 0, GL_READ_WRITE, GL_R32UI);
    g.active_texture(GL_TEXTURE0);
    g.bind_texture(GL_TEXTURE_2D, source);
    // Each pass's uniforms: the picture's size and the buffer's layout.
    for (int p = 0; p < kPasses; ++p) {
        g.use_program(c->programs[p]);
        const GLint* u = c->uniforms[p];
        g.uniform_ivec2(u[kSize], width, height);
        g.uniform_uint(u[kCandidatesAt], c->candidates_at);
        g.uniform_uint(u[kCandidatesMax], c->candidates_max);
        g.uniform_uint(u[kLocationsAt], c->locations_at);
        g.uniform_uint(u[kLocationsMax], c->locations_max);
        g.uniform_uint(u[kItemsAt], c->items_at);
        g.uniform_uint(u[kItemsMax], c->items_max);
        g.uniform_uint(u[kHeadsAt], c->heads_at);
        g.uniform_uint(u[kHeadsPitch], c->heads_pitch);
    }
    // The reference's order: edges in 2x2 blocks (14 x 14 blocks a group), the candidates' dispatch, the candidates, the
    // blend's dispatch, the blend; each pass sees what the one before wrote.
    const GLbitfield written = GL_SHADER_STORAGE_BARRIER_BIT | GL_SHADER_IMAGE_ACCESS_BARRIER_BIT;
    const int kernel = (16 - 2) * 2;
    g.use_program(c->programs[kEdges]);
    g.dispatch(static_cast<GLuint>((width + kernel - 1) / kernel), static_cast<GLuint>((height + kernel - 1) / kernel), 1);
    g.memory_barrier(written);
    g.use_program(c->programs[kDispatchArgs]);
    g.dispatch(2, 1, 1);
    g.memory_barrier(written | GL_COMMAND_BARRIER_BIT);
    g.use_program(c->programs[kProcessCandidates]);
    g.dispatch_indirect(16 * 4);
    g.memory_barrier(written);
    g.use_program(c->programs[kDispatchArgs]);
    g.dispatch(1, 2, 1);
    g.memory_barrier(written | GL_COMMAND_BARRIER_BIT);
    g.use_program(c->programs[kDeferredApply]);
    g.dispatch_indirect(16 * 4);
    // The output as the passes after read it: sampled, or blitted.
    g.memory_barrier(GL_TEXTURE_FETCH_BARRIER_BIT | GL_FRAMEBUFFER_BARRIER_BIT | GL_SHADER_IMAGE_ACCESS_BARRIER_BIT);
    // The game's compute state back.
    restore_image(g, 1, was_images[1]);
    restore_image(g, 0, was_images[0]);
    g.bind_buffer(GL_DISPATCH_INDIRECT_BUFFER, static_cast<GLuint>(was_indirect));
    if (was_size > 0) g.bind_buffer_range(GL_SHADER_STORAGE_BUFFER, 0, static_cast<GLuint>(was_storage0), static_cast<GLintptr>(was_start),
                                          static_cast<GLsizeiptr>(was_size));
    else g.bind_buffer_base(GL_SHADER_STORAGE_BUFFER, 0, static_cast<GLuint>(was_storage0));
    g.bind_buffer(GL_SHADER_STORAGE_BUFFER, static_cast<GLuint>(was_storage));
    return true;
}

void cmaa2_forget(Cmaa2* c) { delete c; }

}  // namespace player
