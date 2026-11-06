// NEON and VFP arithmetic, checked against plain C results.
#include <arm_neon.h>
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>

// Plain C versions of the narrowing, doubling and rounding operations, for comparison.
static int32_t sat32(int64_t v) { return v > INT32_MAX ? INT32_MAX : v < INT32_MIN ? INT32_MIN : (int32_t)v; }
static int64_t sat_add64(int64_t a, int64_t b) {
    int64_t r;
    return __builtin_add_overflow(a, b, &r) ? (b > 0 ? INT64_MAX : INT64_MIN) : r;
}
static int64_t sat_sub64(int64_t a, int64_t b) {
    int64_t r;
    return __builtin_sub_overflow(a, b, &r) ? (b < 0 ? INT64_MAX : INT64_MIN) : r;
}
// 2 * a * b for 32-bit a and b, saturated to 64 bits (only INT32_MIN squared overflows).
static int64_t doubling32(int32_t a, int32_t b) { return a == INT32_MIN && b == INT32_MIN ? INT64_MAX : 2 * (int64_t)a * b; }
// VQRSHL on one element of `bits` bits: shift by the signed bottom byte, round right shifts,
// saturate left shifts.
static int64_t qrshl_signed(int64_t x, int8_t shift, int bits) {
    int64_t max = (int64_t)((1ull << (bits - 1)) - 1), min = -max - 1;
    if (shift >= 0) {
        if (x == 0) return 0;
        if (shift >= bits) return x > 0 ? max : min;
        int64_t v = x * (int64_t)(1ull << shift);
        if (bits < 64 && (v > max || v < min)) return v > max ? max : min;
        if (bits == 64 && (shift && (x > (INT64_MAX >> shift) || x < (INT64_MIN >> shift)))) return x > 0 ? max : min;
        return v;
    }
    int r = -shift;
    if (r > bits) return 0;
    // (x + 2^(r-1)) >> r without overflowing 64 bits.
    return (x >> r) + ((x >> (r - 1)) & 1);
}
static uint64_t qrshl_unsigned(uint64_t x, int8_t shift, int bits) {
    uint64_t max = bits == 64 ? UINT64_MAX : (1ull << bits) - 1;
    if (shift >= 0) {
        if (x == 0) return 0;
        if (shift >= bits) return max;
        return (x > (max >> shift)) ? max : x << shift;
    }
    int r = -shift;
    if (r > bits) return 0;
    return (r == 64 ? 0 : x >> r) + ((x >> (r - 1)) & 1);
}

// Inputs the compiler cannot fold.
static volatile int seed = 3;

static int check_narrowing_and_doubling(void) {
    int f = 0;
    int16_t a16[8] = {0x7fff, -0x8000, 0x1234, -0x0101, 0x00ff, 0x7f80, -1, 0x4000};
    int16_t b16[8] = {0x7fff, -0x8000, 0x0f0f, 0x0101, 0x0081, 0x0080, -1, -0x4000};
    for (int i = 0; i < 8; i++) a16[i] = (int16_t)(a16[i] + seed - 3);
    int16x8_t va = vld1q_s16(a16), vb = vld1q_s16(b16);
    int8_t r8[8];
    // VADDHN, VRADDHN, VSUBHN, VRSUBHN on 16-bit elements.
    vst1_s8(r8, vaddhn_s16(va, vb));
    for (int i = 0; i < 8; i++) f += r8[i] != (int8_t)((uint16_t)(a16[i] + b16[i]) >> 8);
    vst1_s8(r8, vraddhn_s16(va, vb));
    for (int i = 0; i < 8; i++) f += r8[i] != (int8_t)((uint16_t)(a16[i] + b16[i] + 0x80) >> 8);
    vst1_s8(r8, vsubhn_s16(va, vb));
    for (int i = 0; i < 8; i++) f += r8[i] != (int8_t)((uint16_t)(a16[i] - b16[i]) >> 8);
    vst1_s8(r8, vrsubhn_s16(va, vb));
    for (int i = 0; i < 8; i++) f += r8[i] != (int8_t)((uint16_t)(a16[i] - b16[i] + 0x80) >> 8);
    // 32 -> 16 and 64 -> 32.
    uint32_t a32[4] = {0xffffffffu, 0x80008000u, 0x12345678u, 0x0000ffffu}, b32[4] = {1, 0x7fff8000u, 0x0f0f0f0fu, 0x00008000u};
    uint16_t r16[4];
    vst1_u16(r16, vraddhn_u32(vld1q_u32(a32), vld1q_u32(b32)));
    for (int i = 0; i < 4; i++) f += r16[i] != (uint16_t)((uint32_t)(a32[i] + b32[i] + 0x8000u) >> 16);
    vst1_u16(r16, vsubhn_u32(vld1q_u32(a32), vld1q_u32(b32)));
    for (int i = 0; i < 4; i++) f += r16[i] != (uint16_t)((uint32_t)(a32[i] - b32[i]) >> 16);
    int64_t a64[2] = {INT64_MAX, -5}, b64[2] = {1, INT64_MIN};
    int32_t r32[2];
    vst1_s32(r32, vaddhn_s64(vld1q_s64(a64), vld1q_s64(b64)));
    for (int i = 0; i < 2; i++) f += r32[i] != (int32_t)((uint64_t)((uint64_t)a64[i] + (uint64_t)b64[i]) >> 32);
    vst1_s32(r32, vrsubhn_s64(vld1q_s64(a64), vld1q_s64(b64)));
    for (int i = 0; i < 2; i++) f += r32[i] != (int32_t)((uint64_t)((uint64_t)a64[i] - (uint64_t)b64[i] + 0x80000000ull) >> 32);
    // VQDMULL, VQDMLAL, VQDMLSL (three registers and by scalar), saturating at INT_MIN squared.
    int16_t m16[4] = {-0x8000, 0x7fff, -3, 0x1234};
    int16_t n16[4] = {-0x8000, -0x8000, 0x4000, 0x0102};
    int32_t acc[4] = {5, INT32_MIN + 7, INT32_MAX - 1, -100};
    int32_t q[4];
    vst1q_s32(q, vqdmull_s16(vld1_s16(m16), vld1_s16(n16)));
    for (int i = 0; i < 4; i++) f += q[i] != sat32(2 * (int64_t)m16[i] * n16[i]);
    vst1q_s32(q, vqdmlal_s16(vld1q_s32(acc), vld1_s16(m16), vld1_s16(n16)));
    for (int i = 0; i < 4; i++) f += q[i] != sat32((int64_t)acc[i] + sat32(2 * (int64_t)m16[i] * n16[i]));
    vst1q_s32(q, vqdmlsl_s16(vld1q_s32(acc), vld1_s16(m16), vld1_s16(n16)));
    for (int i = 0; i < 4; i++) f += q[i] != sat32((int64_t)acc[i] - sat32(2 * (int64_t)m16[i] * n16[i]));
    vst1q_s32(q, vqdmlal_lane_s16(vld1q_s32(acc), vld1_s16(m16), vld1_s16(n16), 1));
    for (int i = 0; i < 4; i++) f += q[i] != sat32((int64_t)acc[i] + sat32(2 * (int64_t)m16[i] * n16[1]));
    int32_t m32[2] = {INT32_MIN, 0x12345678}, n32[2] = {INT32_MIN, -7};
    int64_t acc64[2] = {-1, INT64_MAX - 3}, q64[2];
    vst1q_s64(q64, vqdmull_s32(vld1_s32(m32), vld1_s32(n32)));
    for (int i = 0; i < 2; i++) f += q64[i] != doubling32(m32[i], n32[i]);
    vst1q_s64(q64, vqdmlal_s32(vld1q_s64(acc64), vld1_s32(m32), vld1_s32(n32)));
    for (int i = 0; i < 2; i++) f += q64[i] != sat_add64(acc64[i], doubling32(m32[i], n32[i]));
    vst1q_s64(q64, vqdmlsl_lane_s32(vld1q_s64(acc64), vld1_s32(m32), vld1_s32(n32), 0));
    for (int i = 0; i < 2; i++) f += q64[i] != sat_sub64(acc64[i], doubling32(m32[i], n32[0]));
    return f;
}

static int check_rounding_saturating_shifts(void) {
    int f = 0;
    int8_t shifts[16] = {0, 1, 3, 7, 8, 9, 15, 16, 17, -1, -3, -7, -8, -9, -17, 100};
    int16_t x16[8] = {1, -1, 0x4000, -0x8000, 0x7fff, 0x0155, -0x0155, 3};
    int32_t x32[4] = {1, -0x40000000, 0x7fffffff, -5};
    int8_t x8[16] = {1, -1, 64, -128, 127, 85, -85, 3, 0, 2, -2, 99, -99, 5, 6, -7};
    for (int round = 0; round < 2; round++) {
        // Shift vectors: each element's bottom byte, from the table, rotated each round.
        int16_t s16[8];
        int32_t s32[4];
        int8_t s8[16];
        for (int i = 0; i < 8; i++) s16[i] = (int16_t)((shifts[(i + round * 8) % 16] & 0xff) | 0x1200);  // upper byte ignored
        for (int i = 0; i < 4; i++) s32[i] = (int32_t)(0x55aa0000u | (uint8_t)shifts[(i * 3 + round) % 16]);
        for (int i = 0; i < 16; i++) s8[i] = shifts[(i + round) % 16];
        int16_t r16[8];
        vst1q_s16(r16, vqrshlq_s16(vld1q_s16(x16), vld1q_s16(s16)));
        for (int i = 0; i < 8; i++) f += r16[i] != qrshl_signed(x16[i], (int8_t)s16[i], 16);
        int32_t r32[4];
        vst1q_s32(r32, vqrshlq_s32(vld1q_s32(x32), vld1q_s32(s32)));
        for (int i = 0; i < 4; i++) f += r32[i] != qrshl_signed(x32[i], (int8_t)s32[i], 32);
        int8_t r8[16];
        vst1q_s8(r8, vqrshlq_s8(vld1q_s8(x8), vld1q_s8(s8)));
        for (int i = 0; i < 16; i++) f += r8[i] != qrshl_signed(x8[i], s8[i], 8);
        uint8_t u8[16], ru8[16];
        for (int i = 0; i < 16; i++) u8[i] = (uint8_t)x8[i];
        vst1q_u8(ru8, vqrshlq_u8(vld1q_u8(u8), vld1q_s8(s8)));
        for (int i = 0; i < 16; i++) f += ru8[i] != qrshl_unsigned(u8[i], s8[i], 8);
        uint16_t u16[4] = {1, 0xffff, 0x8001, 0x0155}, ru16[4];
        vst1_u16(ru16, vqrshl_u16(vld1_u16(u16), vld1_s16(s16)));
        for (int i = 0; i < 4; i++) f += ru16[i] != qrshl_unsigned(u16[i], (int8_t)s16[i], 16);
        int64_t x64[2] = {-3, INT64_MAX / 5}, s64[2] = {-1, 2 + round}, r64[2];
        vst1q_s64(r64, vqrshlq_s64(vld1q_s64(x64), vld1q_s64(s64)));
        for (int i = 0; i < 2; i++) f += r64[i] != qrshl_signed(x64[i], (int8_t)s64[i], 64);
    }
    return f;
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);  // show progress even if the test hangs
    int failures = 0;
    float a[8], b[8], out[8];
    for (int i = 0; i < 8; i++) { a[i] = (float)i * 1.5f; b[i] = 2.0f - (float)i; }
    for (int i = 0; i < 8; i += 4) {
        float32x4_t va = vld1q_f32(a + i), vb = vld1q_f32(b + i);
        vst1q_f32(out + i, vmlaq_f32(va, va, vb));
    }
    for (int i = 0; i < 8; i++) if (fabsf(out[i] - (a[i] + a[i] * b[i])) > 1e-5f) failures++;
    printf("%s neon float multiply-add\n", failures ? "FAIL" : "ok  ");
    int fails2 = 0;
    uint8_t x[16], y[16], z[16];
    for (int i = 0; i < 16; i++) { x[i] = (uint8_t)(i * 17); y[i] = (uint8_t)(255 - i * 9); }
    vst1q_u8(z, vqaddq_u8(vld1q_u8(x), vld1q_u8(y)));
    for (int i = 0; i < 16; i++) { int s = x[i] + y[i]; if (z[i] != (s > 255 ? 255 : s)) fails2++; }
    printf("%s neon saturating add\n", fails2 ? "FAIL" : "ok  ");
    volatile double d = 10.0;
    int fails3 = fabs(sin(d) * sin(d) + cos(d) * cos(d) - 1.0) > 1e-12;
    printf("%s vfp double trigonometry\n", fails3 ? "FAIL" : "ok  ");
    int fails4 = check_narrowing_and_doubling();
    printf("%s neon narrowing high half and saturating doubling multiplies (%d wrong)\n", fails4 ? "FAIL" : "ok  ", fails4);
    int fails5 = check_rounding_saturating_shifts();
    printf("%s neon saturating rounding shifts (%d wrong)\n", fails5 ? "FAIL" : "ok  ", fails5);
    failures += fails2 + fails3 + fails4 + fails5;
    printf("%s\n", failures ? "SOME CHECKS FAILED" : "ALL CHECKS PASSED");
    return failures ? 1 : 7;
}
