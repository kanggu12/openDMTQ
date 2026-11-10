// Checks the MP4 reader of the player for Windows (arm32/desktop/mp4.cpp) on files made to break it, on the build machine:
//   c++ -std=c++20 -Wall -Wextra -Iarm32/desktop arm32/tests/host/mp4_test.cpp arm32/desktop/mp4.cpp -o /tmp/mp4_test && /tmp/mp4_test
//
// The game's videos come from its server, and the reader takes their sizes and counts from the file. Each made-up file
// below must be turned away, or read only as far as it is true, within a second and in bounded memory: each runs in a
// child process with a ceiling on both, so that a reader that loops or allocates gigabytes fails its check rather than
// the machine it runs on. A well-made file first, read as it always was.
#include "mp4.h"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <new>
#include <string>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>

namespace {

using Bytes = std::vector<std::uint8_t>;
using player::media::Mp4;
using player::media::Source;

// The ceilings of each file's child process: the address space of a reader that keeps to the file's size with room to
// spare (the old reader asked for 256 MB and more for a file of a few hundred bytes), and the time of one that ends.
constexpr rlim_t kMemory = 192u << 20;
constexpr unsigned kSeconds = 1;

int g_checks = 0, g_failures = 0;

// Big-endian fields, as MP4 writes them.
void u32(Bytes& b, std::uint32_t v) {
    for (int shift = 24; shift >= 0; shift -= 8) b.push_back(static_cast<std::uint8_t>(v >> shift));
}
void u64(Bytes& b, std::uint64_t v) {
    for (int shift = 56; shift >= 0; shift -= 8) b.push_back(static_cast<std::uint8_t>(v >> shift));
}
// A four-letter code, and more bytes after what is there.
void code(Bytes& b, const char* type) { b.insert(b.end(), type, type + 4); }
void append(Bytes& b, const Bytes& more) { b.insert(b.end(), more.begin(), more.end()); }

// A box: its size, its type and its contents.
Bytes box(const char* type, const Bytes& contents) {
    Bytes b;
    u32(b, static_cast<std::uint32_t>(8 + contents.size()));
    code(b, type);
    append(b, contents);
    return b;
}

// A full box's contents: version 0 and no flags before its fields.
Bytes full(const Bytes& fields) {
    Bytes b;
    u32(b, 0);
    append(b, fields);
    return b;
}

// The sample tables of a track, each a full box's fields.
struct Tables {
    Bytes stsz, stco, stsc, stts;
};

// A movie box of one sound track, AAC at 44100 Hz in stereo as the game's videos have it, with the given sample tables.
Bytes movie(const Tables& t) {
    // mdhd: its creation and modification times, a time scale of 44100 a second, a duration of 1024 of those.
    Bytes mdhd;
    for (std::uint32_t v : {0u, 0u, 44100u, 1024u, 0u}) u32(mdhd, v);
    // hdlr: a pre-defined zero, then a sound handler.
    Bytes hdlr;
    u32(hdlr, 0);
    code(hdlr, "soun");
    for (int k = 0; k < 4; ++k) u32(hdlr, 0);
    // stsd: one AudioSampleEntry 'mp4a' of 28 bytes of fields, its channels at byte 16 and its rate (16.16) at 24; no
    // esds, which the reader takes for AAC.
    Bytes entry(28, 0);
    entry[17] = 2;
    entry[24] = 44100 >> 8;
    entry[25] = 44100 & 0xff;
    Bytes stsd;
    u32(stsd, 1);
    u32(stsd, static_cast<std::uint32_t>(8 + entry.size()));
    code(stsd, "mp4a");
    append(stsd, entry);
    // The sample tables beside it, in stbl, in minf, in mdia, in trak, in moov.
    Bytes stbl = box("stsd", full(stsd));
    append(stbl, box("stsz", full(t.stsz)));
    append(stbl, box("stco", full(t.stco)));
    append(stbl, box("stsc", full(t.stsc)));
    append(stbl, box("stts", full(t.stts)));
    Bytes mdia = box("mdhd", full(mdhd));
    append(mdia, box("hdlr", full(hdlr)));
    append(mdia, box("minf", box("stbl", stbl)));
    return box("moov", box("trak", box("mdia", mdia)));
}

// The tables of one sample of `size` bytes at `offset`: one chunk, one run, one time.
Tables one_sample(std::uint32_t size, std::uint32_t offset) {
    Tables t;
    // stsz: no size for all, one sample, its size.
    for (std::uint32_t v : {0u, 1u, size}) u32(t.stsz, v);
    // stco: one chunk at the offset.
    for (std::uint32_t v : {1u, offset}) u32(t.stco, v);
    // stsc: one run from chunk 1, one sample a chunk, the first sample entry.
    for (std::uint32_t v : {1u, 1u, 1u, 1u}) u32(t.stsc, v);
    // stts: one sample of 1024 time units.
    for (std::uint32_t v : {1u, 1u, 1024u}) u32(t.stts, v);
    return t;
}

// A movie of one sample of `size` bytes whose stated offset is where its media data starts, then that media data.
Bytes file_of_one_sample(std::uint32_t size, const Bytes& data) {
    // The movie's size does not depend on the offset written in it: made once to learn it, then again with it.
    const std::size_t moov = movie(one_sample(size, 0)).size();
    Bytes file = movie(one_sample(size, static_cast<std::uint32_t>(moov + 8)));
    append(file, box("mdat", data));
    return file;
}

// Runs `check` on `file` in a child process held to kMemory bytes and kSeconds: true when it held there. The child's
// verdict is its exit status; the time's alarm (a signal) or running out of memory fails it.
bool within_limits(const char* what, const Bytes& file, const std::function<bool(Mp4&, const Source&)>& check) {
    ++g_checks;
    // The file on the disk, read as the player reads one (pread on a descriptor).
    std::FILE* f = std::tmpfile();
    if (!f || std::fwrite(file.data(), 1, file.size(), f) != file.size() || std::fflush(f) != 0) {
        std::printf("FAIL %s: cannot write the file\n", what);
        ++g_failures;
        return false;
    }
    const Source source{fileno(f), 0, static_cast<std::int64_t>(file.size())};
    // Nothing of the parent's output waiting in a buffer the child would have a copy of.
    std::fflush(stdout);
    const auto start = std::chrono::steady_clock::now();
    const pid_t pid = fork();
    if (pid == 0) {
        // The ceilings: an address space no larger than kMemory, and SIGALRM's default end after kSeconds.
        const rlimit memory{kMemory, kMemory};
        setrlimit(RLIMIT_AS, &memory);
        alarm(kSeconds);
        try {
            Mp4 mp4;
            _exit(check(mp4, source) ? 0 : 1);
        } catch (const std::bad_alloc&) {
            // More memory than the ceiling: the reader made something of a size the file only stated.
            _exit(3);
        }
    }
    int status = 0;
    const bool waited = pid > 0 && waitpid(pid, &status, 0) == pid;
    const double took = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    std::fclose(f);
    if (waited && WIFEXITED(status) && WEXITSTATUS(status) == 0 && took < kSeconds) {
        std::printf("ok %s (%.3f s)\n", what, took);
        return true;
    }
    ++g_failures;
    // Why, as far as the parent can tell.
    const char* why = !waited                                          ? "no child process"
                      : WIFSIGNALED(status)                            ? "it did not end within a second"
                      : WIFEXITED(status) && WEXITSTATUS(status) == 3 ? "it ran out of its memory"
                      : WIFEXITED(status) && WEXITSTATUS(status) == 0 ? "it took more than a second"
                                                                       : "its answer was wrong";
    std::printf("FAIL %s: %s (%.3f s)\n", what, why, took);
    return false;
}

}  // namespace

int main() {
    // A well-made file: one sample of four bytes, read back as it is.
    const Bytes good = file_of_one_sample(4, {1, 2, 3, 4});
    within_limits("a well-made file is read as before", good, [](Mp4& mp4, const Source& source) {
        std::string error;
        std::vector<std::uint8_t> out;
        return mp4.open(source, error) && mp4.tracks().size() == 1 && mp4.tracks()[0].mime == "audio/mp4a-latm" &&
               mp4.tracks()[0].samples.size() == 1 && mp4.max_read_size(0) == 4 && mp4.read(0, 0, out) && out == Bytes{1, 2, 3, 4};
    });

    // A box whose 64-bit size reads as -16 when taken as signed: from a box at 16 it would step back to the one at 0,
    // and from there to itself again, for ever. 32 bytes: a free box of 16, then that one.
    Bytes back = box("free", Bytes(8, 0));
    u32(back, 1);
    code(back, "free");
    u64(back, 0xfffffffffffffff0ull);
    within_limits("a box size that steps back ends the walk", back, [](Mp4& mp4, const Source& source) {
        std::string error;
        return !mp4.open(source, error) && error == "no movie box";
    });

    // One size of 4 bytes for 64 Mi samples, in a file of a few hundred: tables of gigabytes for samples that cannot be
    // there. Turned away before any table is made.
    Tables uniform = one_sample(4, 0);
    uniform.stsz.clear();
    for (std::uint32_t v : {4u, 64u << 20}) u32(uniform.stsz, v);
    const Bytes many = movie(uniform);
    within_limits("a sample count the file has no room for is turned away", many, [](Mp4& mp4, const Source& source) {
        std::string error;
        return !mp4.open(source, error) && error == "no tracks this can read";
    });

    // A sample of nearly 4 GiB in a file of a few hundred bytes: listed, but neither read (a buffer of its size would be
    // made and zeroed first) nor taken for the largest sample a decoder must hold.
    const Bytes huge = file_of_one_sample(0xfffffff0u, {1, 2, 3, 4});
    within_limits("a sample larger than the file is not read", huge, [&huge](Mp4& mp4, const Source& source) {
        std::string error;
        std::vector<std::uint8_t> out;
        return mp4.open(source, error) && mp4.tracks().size() == 1 && !mp4.read(0, 0, out) && mp4.max_read_size(0) <= huge.size();
    });

    // 200000 chunks and 100000 runs of one sample each, a byte a sample: a look through every run for each chunk would
    // take 2e10 steps. Read whole, at once.
    constexpr std::uint32_t kChunks = 200000, kRuns = 100000;
    Tables walk;
    // One size of a byte for every sample, one a chunk.
    for (std::uint32_t v : {1u, kChunks}) u32(walk.stsz, v);
    // The chunks, at offsets made right below once the movie's size is known.
    u32(walk.stco, kChunks);
    for (std::uint32_t c = 0; c < kChunks; ++c) u32(walk.stco, 0);
    // A run starting at each of the first kRuns chunks, one sample each; the last goes on to the end.
    u32(walk.stsc, kRuns);
    for (std::uint32_t r = 0; r < kRuns; ++r)
        for (std::uint32_t v : {r + 1, 1u, 1u}) u32(walk.stsc, v);
    // Every sample 1024 time units long.
    for (std::uint32_t v : {1u, kChunks, 1024u}) u32(walk.stts, v);
    // Chunk c is byte c of the media data after the movie: its offset written in place, in stco's entries (after the
    // box's type, its version and flags, and its count).
    Bytes runs = movie(walk);
    const std::size_t media = runs.size() + 8;
    Bytes stco_type;
    code(stco_type, "stco");
    const std::size_t at = static_cast<std::size_t>(std::search(runs.begin(), runs.end(), stco_type.begin(), stco_type.end()) - runs.begin()) + 4 + 4 + 4;
    for (std::uint32_t c = 0; c < kChunks; ++c) {
        Bytes offset;
        u32(offset, static_cast<std::uint32_t>(media + c));
        std::copy(offset.begin(), offset.end(), runs.begin() + static_cast<std::ptrdiff_t>(at + 4 * c));
    }
    append(runs, box("mdat", Bytes(kChunks, 7)));
    within_limits("many chunks and many runs are read in one walk", runs, [](Mp4& mp4, const Source& source) {
        std::string error;
        std::vector<std::uint8_t> out;
        return mp4.open(source, error) && mp4.tracks().size() == 1 && mp4.tracks()[0].samples.size() == kChunks &&
               mp4.read(0, kChunks - 1, out) && out == Bytes{7};
    });

    if (g_failures) {
        std::printf("%d of %d checks FAILED\n", g_failures, g_checks);
        return 1;
    }
    std::printf("%d checks\nALL CHECKS PASSED\n", g_checks);
    return 0;
}
