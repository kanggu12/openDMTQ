// Checks the colours that go into a computer's broadcast (arm32/src/live_sps.cpp) on the build machine:
//
//   c++ -std=c++20 -Iarm32/src arm32/tests/host/live_sps_test.cpp arm32/src/live_sps.cpp -o /tmp/live_sps_test && /tmp/live_sps_test
//
// The sequence header is one Windows' H.264 encoder made for a 1280x720 broadcast (Main profile, a VUI with its timing,
// an emulation-prevention byte in it), and two made here: one with no VUI, one whose VUI has a signal type of its own.
// Each comes back read by this file's own reader: the colours BT.709 in the limited range, everything else as it was,
// and the other NAL units of the access unit untouched.
#include "live_sps.h"

#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

using namespace arm32;

namespace {

int g_failures = 0;
int g_checks = 0;
#define CHECK(c)                                                  \
    do {                                                          \
        ++g_checks;                                               \
        if (!(c)) {                                               \
            std::printf("FAIL line %d: %s\n", __LINE__, #c);      \
            ++g_failures;                                         \
        }                                                         \
    } while (0)

using Bytes = std::vector<std::uint8_t>;

// The bytes of a NAL unit's payload without its emulation-prevention bytes.
Bytes unescape(const Bytes& b, std::size_t from, std::size_t to) {
    Bytes out;
    int zeros = 0;
    for (std::size_t i = from; i < to; ++i) {
        if (zeros >= 2 && b[i] == 3) {
            zeros = 0;
            continue;
        }
        zeros = b[i] == 0 ? zeros + 1 : 0;
        out.push_back(b[i]);
    }
    return out;
}

// Reads bits and Exp-Golomb codes.
struct Reader {
    const Bytes& b;
    std::size_t pos = 0;
    std::uint32_t u(int n) {
        std::uint32_t v = 0;
        for (int i = 0; i < n; ++i, ++pos) v = (v << 1) | (pos / 8 < b.size() ? (b[pos / 8] >> (7 - pos % 8)) & 1 : 0);
        return v;
    }
    std::uint32_t ue() {
        int zeros = 0;
        while (u(1) == 0 && zeros < 32) ++zeros;
        return zeros ? (1u << zeros) - 1 + u(zeros) : 0;
    }
};

// What the checks look at in an SPS.
struct Sps {
    std::uint32_t profile = 0, level = 0, width_mbs = 0, height_units = 0;
    bool vui = false, signal = false, full_range = true, colours = false, timing = false;
    std::uint32_t format = 0, primaries = 0, transfer = 0, matrix = 0, units = 0, scale = 0, fixed = 0, aspect = 0;
};

// An SPS's RBSP read as far as the checks need, Main-profile style (no chroma fields).
Sps read_sps(const Bytes& rbsp) {
    Reader r{rbsp};
    Sps s;
    s.profile = r.u(8);
    r.u(8);
    s.level = r.u(8);
    r.ue();
    r.ue();
    const std::uint32_t poc = r.ue();
    if (poc == 0) r.ue();
    r.ue();
    r.u(1);
    s.width_mbs = r.ue() + 1;
    s.height_units = r.ue() + 1;
    if (!r.u(1)) r.u(1);
    r.u(1);
    if (r.u(1)) {
        for (int i = 0; i < 4; ++i) r.ue();
    }
    s.vui = r.u(1);
    if (s.vui) {
        if (r.u(1)) {
            s.aspect = r.u(8);
            if (s.aspect == 255) {
                r.u(16);
                r.u(16);
            }
        }
        if (r.u(1)) r.u(1);
        s.signal = r.u(1);
        if (s.signal) {
            s.format = r.u(3);
            s.full_range = r.u(1);
            s.colours = r.u(1);
            if (s.colours) {
                s.primaries = r.u(8);
                s.transfer = r.u(8);
                s.matrix = r.u(8);
            }
        }
        if (r.u(1)) {
            r.ue();
            r.ue();
        }
        s.timing = r.u(1);
        if (s.timing) {
            s.units = r.u(32);
            s.scale = r.u(32);
            s.fixed = r.u(1);
        }
    }
    return s;
}

// The SPS in an access unit: the payload after the first start code whose NAL type is 7, up to the next start code.
Bytes sps_of(const Bytes& unit) {
    for (std::size_t i = 0; i + 3 < unit.size(); ++i) {
        if (unit[i] == 0 && unit[i + 1] == 0 && unit[i + 2] == 1 && (unit[i + 3] & 0x1f) == 7) {
            std::size_t end = i + 4;
            while (end + 2 < unit.size() && !(unit[end] == 0 && unit[end + 1] == 0 && (unit[end + 2] == 1 || unit[end + 2] == 0))) ++end;
            if (end + 2 >= unit.size()) end = unit.size();
            return unescape(unit, i + 4, end);
        }
    }
    return {};
}

Bytes hex(const char* text) {
    Bytes out;
    for (const char* p = text; p[0] && p[1]; p += 2) out.push_back(static_cast<std::uint8_t>(std::strtoul(std::string(p, 2).c_str(), nullptr, 16)));
    return out;
}

// An access unit: a delimiter, the SPS given (its header byte first), the encoder's PPS, and a slice of made-up bytes.
Bytes unit_with(const Bytes& sps_nal) {
    Bytes u = {0, 0, 0, 1, 9, 0xF0, 0, 0, 0, 1};
    u.insert(u.end(), sps_nal.begin(), sps_nal.end());
    const Bytes rest = {0, 0, 0, 1, 0x68, 0xce, 0x3c, 0x80, 0, 0, 1, 0x65, 0x88, 0x84, 0x00, 0x33, 0xff};
    u.insert(u.end(), rest.begin(), rest.end());
    return u;
}

// Writes bits and Exp-Golomb codes, for the SPSs made here.
struct Writer {
    Bytes out;
    int bits = 0;
    void u(int n, std::uint32_t v) {
        for (int i = n - 1; i >= 0; --i) {
            if (bits % 8 == 0) out.push_back(0);
            if ((v >> i) & 1) out.back() |= static_cast<std::uint8_t>(0x80 >> (bits % 8));
            ++bits;
        }
    }
    void ue(std::uint32_t v) {
        const std::uint32_t x = v + 1;
        int len = 0;
        while ((x >> len) > 1) ++len;
        u(len, 0);
        u(len + 1, x);
    }
    void finish() {
        u(1, 1);
        while (bits % 8) u(1, 0);
    }
};

// A Main-profile SPS for 1280x720 up to its VUI flag, as Windows' encoder starts its own.
void sps_start(Writer& w) {
    w.u(8, 77);
    w.u(8, 0x40);
    w.u(8, 31);
    w.ue(0);
    w.ue(0);
    w.ue(2);
    w.ue(1);
    w.u(1, 0);
    w.ue(79);
    w.ue(44);
    w.u(1, 1);
    w.u(1, 1);
    w.u(1, 0);
}

// The SPS of a unit after the colours went in, read.
Sps coloured(const Bytes& unit) { return read_sps(sps_of(with_colours(unit))); }

void check_colours(const Sps& s) {
    CHECK(s.vui && s.signal && s.colours);
    CHECK(s.primaries == 1 && s.transfer == 1 && s.matrix == 1);
    CHECK(!s.full_range);
}

}  // namespace

int main() {
    // Windows' encoder's own header, as one of its broadcasts had it: 67 is the NAL header byte.
    const Bytes windows = hex("674d401f965602802dd80880000003008000001e06d044229c");
    const Sps before = read_sps(unescape(windows, 1, windows.size()));
    CHECK(before.profile == 77 && before.width_mbs == 80 && before.height_units == 45);
    CHECK(before.vui && !before.signal && before.timing);
    const Bytes unit = unit_with(windows);
    const Bytes out = with_colours(unit);
    const Sps after = read_sps(sps_of(out));
    check_colours(after);
    // Everything else as it was: the size, the level, the VUI's timing.
    CHECK(after.profile == before.profile && after.level == before.level && after.width_mbs == before.width_mbs && after.height_units == before.height_units);
    CHECK(after.timing && after.units == before.units && after.scale == before.scale && after.fixed == before.fixed);
    CHECK(after.format == 5);
    // The PPS and the slice after it, byte for byte: the unit's end is the same.
    const std::size_t tail = 17;
    CHECK(out.size() > unit.size() && Bytes(out.end() - tail, out.end()) == Bytes(unit.end() - tail, unit.end()));
    // The delimiter before it too.
    CHECK(Bytes(out.begin(), out.begin() + 10) == Bytes(unit.begin(), unit.begin() + 10));
    // No three bytes in the new SPS that a decoder would take for a start code or would unescape.
    bool clean = true;
    for (std::size_t i = 10; i + 2 < out.size() - tail; ++i) clean = clean && !(out[i] == 0 && out[i + 1] == 0 && out[i + 2] <= 2);
    CHECK(clean);
    // Twice is the same as once: the colours replace those there.
    CHECK(with_colours(out) == out);

    // An SPS with no VUI at all: one with the colours alone.
    Writer bare;
    bare.u(8, 0x67);
    sps_start(bare);
    bare.u(1, 0);
    bare.finish();
    const Sps from_bare = coloured(unit_with(bare.out));
    check_colours(from_bare);
    CHECK(from_bare.width_mbs == 80 && from_bare.height_units == 45 && !from_bare.timing);

    // An SPS whose VUI has an aspect ratio and a signal type of its own (BT.601, full range): the aspect ratio stays,
    // the signal type is the stream's.
    Writer own;
    own.u(8, 0x67);
    sps_start(own);
    own.u(1, 1);
    own.u(1, 1);
    own.u(8, 1);
    own.u(1, 0);
    own.u(1, 1);
    own.u(3, 2);
    own.u(1, 1);
    own.u(1, 1);
    own.u(8, 6);
    own.u(8, 6);
    own.u(8, 6);
    own.u(1, 0);
    own.u(1, 1);
    own.u(32, 1001);
    own.u(32, 60000);
    own.u(1, 1);
    own.u(1, 0);
    own.u(1, 0);
    own.u(1, 0);
    own.u(1, 0);
    own.finish();
    const Sps from_own = coloured(unit_with(own.out));
    check_colours(from_own);
    CHECK(from_own.aspect == 1 && from_own.format == 2);
    CHECK(from_own.timing && from_own.units == 1001 && from_own.scale == 60000 && from_own.fixed == 1);

    // A unit without an SPS (a P frame): the same bytes.
    const Bytes plain = {0, 0, 0, 1, 9, 0xF0, 0, 0, 0, 1, 0x41, 0x9a, 0x00, 0x00, 0x03, 0x01, 0x22};
    CHECK(with_colours(plain) == plain);

    if (g_failures) {
        std::printf("%d of %d checks FAILED\n", g_failures, g_checks);
        return 1;
    }
    std::printf("%d checks\nALL CHECKS PASSED\n", g_checks);
    return 0;
}
