// Checks the live view's transport stream writer on the build machine, with no phone:
//
//   c++ -std=c++20 -Iarm32/src arm32/tests/host/live_ts_test.cpp arm32/src/live_ts.cpp -o /tmp/live_ts_test && /tmp/live_ts_test
//
// It writes frames of many sizes (those around a packet's room are where stuffing goes wrong), then
// reads the packets back as a player would: sync bytes, continuity counters, table checksums, times
// and clock references, and each frame's bytes reassembled unchanged.
#include "live_ts.h"

#include <cstdio>
#include <cstdlib>
#include <map>
#include <vector>

using namespace arm32;

namespace {

int g_failures = 0;
#define CHECK(c)                                                  \
    do {                                                          \
        if (!(c)) {                                               \
            std::printf("FAIL line %d: %s\n", __LINE__, #c);      \
            ++g_failures;                                         \
        }                                                         \
    } while (0)

std::uint32_t crc32_mpeg(const std::uint8_t* d, std::size_t n) {
    std::uint32_t crc = 0xFFFFFFFFu;
    for (std::size_t i = 0; i < n; ++i) {
        crc ^= static_cast<std::uint32_t>(d[i]) << 24;
        for (int b = 0; b < 8; ++b) crc = (crc & 0x80000000u) ? (crc << 1) ^ 0x04C11DB7u : crc << 1;
    }
    return crc;
}

std::uint64_t read_pts(const std::uint8_t* p) {
    return (static_cast<std::uint64_t>(p[0] >> 1 & 7) << 30) | (static_cast<std::uint64_t>(p[1]) << 22) |
           (static_cast<std::uint64_t>(p[2] >> 1) << 15) | (static_cast<std::uint64_t>(p[3]) << 7) | (p[4] >> 1);
}

struct Unit {
    std::uint64_t pts = 0;
    bool key = false, pcr = false;
    std::uint64_t pcr_value = 0;
    std::vector<std::uint8_t> bytes;
};

// Reads one segment: the units of each PID, with counters kept across segments in `counters`.
std::map<int, std::vector<Unit>> read_segment(const std::vector<std::uint8_t>& ts, std::map<int, int>& counters) {
    std::map<int, std::vector<Unit>> units;
    CHECK(ts.size() % 188 == 0);
    for (std::size_t at = 0; at + 188 <= ts.size(); at += 188) {
        const std::uint8_t* p = ts.data() + at;
        CHECK(p[0] == 0x47);
        const int pid = ((p[1] & 0x1F) << 8) | p[2];
        const bool start = p[1] & 0x40;
        const int control = p[3] >> 4 & 3;
        const int counter = p[3] & 15;
        auto seen = counters.find(pid);
        if (seen != counters.end()) CHECK(counter == ((seen->second + 1) & 15));
        counters[pid] = counter;
        std::size_t i = 4;
        bool key = false, has_pcr = false;
        std::uint64_t pcr = 0;
        if (control & 2) {
            const std::size_t length = p[i];
            CHECK(i + 1 + length <= 188);
            if (length > 0) {
                key = p[i + 1] & 0x40;
                has_pcr = p[i + 1] & 0x10;
                if (has_pcr) pcr = (static_cast<std::uint64_t>(p[i + 2]) << 25) | (p[i + 3] << 17) | (p[i + 4] << 9) | (p[i + 5] << 1) | (p[i + 6] >> 7);
            }
            i += 1 + length;
        }
        CHECK(control & 1);
        if (pid == 0 || pid == 0x1000) {
            // A table: its checksum covers everything up to its end.
            CHECK(start);
            const std::uint8_t* section = p + i + 1 + p[i];
            const std::size_t length = 3 + (((section[1] & 0x0F) << 8) | section[2]);
            CHECK(crc32_mpeg(section, length) == 0);
            continue;
        }
        if (start) {
            CHECK(p[i] == 0 && p[i + 1] == 0 && p[i + 2] == 1);
            CHECK(p[i + 7] == 0x80 && p[i + 8] == 5);
            Unit u;
            u.pts = read_pts(p + i + 9);
            u.key = key;
            u.pcr = has_pcr;
            u.pcr_value = pcr;
            units[pid].push_back(u);
            i += 14;
        }
        CHECK(!units[pid].empty());
        units[pid].back().bytes.insert(units[pid].back().bytes.end(), p + i, p + 188);
    }
    return units;
}

std::vector<std::uint8_t> pattern(std::size_t size, unsigned seed) {
    std::vector<std::uint8_t> v(size);
    for (std::size_t i = 0; i < size; ++i) v[i] = static_cast<std::uint8_t>(seed + i * 7);
    return v;
}

}  // namespace

int main() {
    TsWriter w;
    std::map<int, int> counters;
    // Every size around one and two packets' room, then some large frames.
    std::vector<std::size_t> sizes;
    for (std::size_t s = 1; s < 400; ++s) sizes.push_back(s);
    for (std::size_t s : {1000u, 65000u, 70000u, 300000u}) sizes.push_back(s);
    std::uint64_t pts = 90000;
    unsigned seed = 1;
    for (int segment = 0; segment < 2; ++segment) {
        w.begin_segment();
        std::vector<std::vector<std::uint8_t>> video, audio;
        std::vector<std::uint64_t> times;
        for (std::size_t s : sizes) {
            video.push_back(pattern(s, seed));
            audio.push_back(pattern(s % 700 + 1, seed + 3));
            times.push_back(pts);
            w.video(video.back().data(), video.back().size(), pts, video.size() % 5 == 1);
            w.audio(audio.back().data(), audio.back().size(), pts + 100);
            pts += 3000;
            ++seed;
        }
        auto units = read_segment(w.bytes(), counters);
        CHECK(units[0x100].size() == video.size());
        CHECK(units[0x101].size() == audio.size());
        for (std::size_t i = 0; i < video.size() && i < units[0x100].size(); ++i) {
            const Unit& u = units[0x100][i];
            CHECK(u.bytes == video[i]);
            CHECK(u.pts == times[i]);
            CHECK(u.key == (i % 5 == 0));
            CHECK(u.pcr);
            CHECK(u.pcr_value <= u.pts);
            CHECK(u.pts - u.pcr_value <= 27000);
        }
        for (std::size_t i = 0; i < audio.size() && i < units[0x101].size(); ++i) {
            CHECK(units[0x101][i].bytes == audio[i]);
            CHECK(units[0x101][i].pts == times[i] + 100);
            CHECK(!units[0x101][i].pcr);
        }
    }
    // An ADTS header reads back as what it says.
    std::uint8_t h[7];
    CHECK(adts_header(h, 48000, 2, 400));
    CHECK(h[0] == 0xFF && (h[1] & 0xF0) == 0xF0);
    CHECK((h[2] >> 6) == 1 && ((h[2] >> 2) & 15) == 3);
    CHECK((((h[2] & 1) << 2) | (h[3] >> 6)) == 2);
    CHECK((((h[3] & 3) << 11) | (h[4] << 3) | (h[5] >> 5)) == 407);
    CHECK(!adts_header(h, 12345, 2, 400));
    if (g_failures == 0) std::printf("ALL CHECKS PASSED\n");
    return g_failures ? 1 : 0;
}
