// Tests of the desktop player's video path below Java (mp4.h, decoder.h), on a file FFmpeg's own tool made: two
// seconds of a red 320x240 picture at 30 frames a second in H.264, and a 1000 Hz tone at 48000 Hz in stereo AAC. The
// reader must find both tracks as Android's extractor describes them, and give every sample; the decoders must give
// every picture, red, and two seconds of the tone. Prints one line per check, then "ALL CHECKS PASSED".
//
//   mediatest <file.mp4>
#include "decoder.h"
#include "mp4.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

using namespace player::media;

namespace {

int g_checks = 0, g_failures = 0;

void check(bool ok, const char* what) {
    ++g_checks;
    if (!ok) ++g_failures;
    std::printf("%s %s\n", ok ? "ok  " : "FAIL", what);
}

// Whether `bytes` start with a start code and a NAL unit of `type`.
bool starts_with_nal(const std::vector<std::uint8_t>& bytes, int type) {
    return bytes.size() > 4 && bytes[0] == 0 && bytes[1] == 0 && bytes[2] == 0 && bytes[3] == 1 && (bytes[4] & 0x1f) == type;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: mediatest <file.mp4>\n");
        return 2;
    }
    char what[200];
    int fd = open(argv[1], O_RDONLY | O_CLOEXEC);
    struct stat st {};
    if (fd < 0 || fstat(fd, &st) != 0) {
        std::fprintf(stderr, "mediatest: cannot open %s\n", argv[1]);
        return 2;
    }
    Mp4 mp4;
    std::string error;
    check(mp4.open(Source{fd, 0, st.st_size}, error), "the file opens as an MP4");
    const std::vector<Track>& tracks = mp4.tracks();
    auto video = std::find_if(tracks.begin(), tracks.end(), [](const Track& t) { return t.mime == "video/avc"; });
    auto audio = std::find_if(tracks.begin(), tracks.end(), [](const Track& t) { return t.mime == "audio/mp4a-latm"; });
    check(tracks.size() == 2 && video != tracks.end() && audio != tracks.end(), "two tracks: video/avc and audio/mp4a-latm");
    if (video == tracks.end() || audio == tracks.end()) {
        std::printf("%d checks\n", g_checks);
        return 1;
    }
    const std::size_t vt = static_cast<std::size_t>(video - tracks.begin()), at = static_cast<std::size_t>(audio - tracks.begin());

    // The video track as Android's extractor gives it.
    std::snprintf(what, sizeof what, "video: %dx%d, %zu samples, %.2f s (want 320x240, 60, 2.00)", video->width, video->height, video->samples.size(),
                  static_cast<double>(video->duration_us) / 1e6);
    check(video->width == 320 && video->height == 240 && video->samples.size() == 60 && std::abs(video->duration_us - 2000000) < 40000, what);
    check(starts_with_nal(video->csd0, 7) && starts_with_nal(video->csd1, 8), "csd-0 is the sequence parameter set after a start code, csd-1 the picture's");
    check(video->samples[0].sync && video->samples[0].time_us == 0, "the first sample is a key frame at 0");
    // Presentation times, in display order, a frame apart (the encoder's B-frames reorder them in decoding order).
    std::vector<std::int64_t> times;
    for (const Sample& s : video->samples) times.push_back(s.time_us);
    std::sort(times.begin(), times.end());
    bool even = true;
    for (std::size_t k = 0; k < times.size(); ++k) even = even && std::llabs(times[k] - static_cast<std::int64_t>(k) * 1000000 / 30) <= 1;
    check(even, "presentation times are 1/30 s apart, from 0");

    // Every picture, decoded, and red.
    std::unique_ptr<Decoder> h264 = open_h264(error);
    check(h264 != nullptr, h264 ? "an H.264 decoder" : error.c_str());
    if (h264) {
        std::vector<std::uint8_t> unit;
        std::size_t pictures = 0, red = 0;
        auto take = [&] {
            for (Frame f; h264->receive(f);) {
                ++pictures;
                const std::uint8_t* p = &f.rgba[(static_cast<std::size_t>(f.height / 2) * static_cast<std::size_t>(f.width) + static_cast<std::size_t>(f.width / 2)) * 4];
                if (f.width == 320 && f.height == 240 && p[0] >= 240 && p[1] <= 16 && p[2] <= 16 && p[3] == 255) ++red;
            }
        };
        // The parameter sets go in front of the first unit, as the player's MediaCodec sends them.
        bool read_all = true;
        for (std::size_t k = 0; k < video->samples.size(); ++k) {
            // Each sample reads, and starts with a start code where the file had a length.
            read_all = read_all && mp4.read(vt, k, unit) && unit.size() > 4 && unit[0] == 0 && unit[1] == 0 && unit[2] == 0 && unit[3] == 1;
            if (k == 0) {
                std::vector<std::uint8_t> first = video->csd0;
                first.insert(first.end(), video->csd1.begin(), video->csd1.end());
                first.insert(first.end(), unit.begin(), unit.end());
                unit.swap(first);
            }
            h264->send(unit.data(), unit.size());
            take();
        }
        h264->drain();
        take();
        check(read_all, "every video sample reads, as NAL units after start codes");
        std::snprintf(what, sizeof what, "pictures: %zu decoded, %zu of them red in the middle (want 60 and 60)", pictures, red);
        check(pictures == 60 && red == 60, what);
    }

    // The sound: AAC's setup, every frame decoded, two seconds of a 1000 Hz tone on both channels.
    std::snprintf(what, sizeof what, "audio: %d Hz, %d channels, csd-0 of %zu bytes (want 48000, 2, 2 or more)", audio->sample_rate, audio->channels,
                  audio->csd0.size());
    check(audio->sample_rate == 48000 && audio->channels == 2 && audio->csd0.size() >= 2, what);
    std::unique_ptr<Decoder> aac = open_aac(audio->csd0, error);
    check(aac != nullptr, aac ? "an AAC decoder for the track's setup" : error.c_str());
    if (aac) {
        std::vector<std::uint8_t> unit;
        std::vector<std::int16_t> left;
        bool stereo = true;
        auto take = [&] {
            for (Frame f; aac->receive(f);) {
                stereo = stereo && f.channels == 2 && f.rate == 48000;
                for (std::size_t k = 0; k + 1 < f.pcm.size(); k += 2) left.push_back(f.pcm[k]);
            }
        };
        for (std::size_t k = 0; k < audio->samples.size(); ++k) {
            if (!mp4.read(at, k, unit)) break;
            aac->send(unit.data(), unit.size());
            take();
        }
        aac->drain();
        take();
        // The tone's frequency from its rising zero crossings, away from the encoder's fade in and out.
        std::size_t rising = 0, from = 4800, to = left.size() > 9600 ? left.size() - 4800 : 0;
        for (std::size_t k = from + 1; k < to; ++k)
            if (left[k - 1] < 0 && left[k] >= 0) ++rising;
        double seconds = static_cast<double>(left.size()) / 48000, hz = to > from ? rising / (static_cast<double>(to - from) / 48000) : 0;
        std::snprintf(what, sizeof what, "sound: %.3f s, stereo at 48000 Hz, a tone of %.1f Hz (want 2 s give or take an AAC frame, 1000 Hz)", seconds, hz);
        check(stereo && std::abs(seconds - 2.0) < 0.05 && std::abs(hz - 1000) < 5, what);
    }
    // What stands in for a missing decoder: a black picture per unit, an AAC frame of silence per frame, nothing after a
    // flush, and a unit of no bytes is no picture.
    {
        std::unique_ptr<Decoder> blank = open_blank(false, 32, 18, 0, 0);
        const std::uint8_t unit_bytes[4] = {0, 0, 0, 1};
        blank->send(unit_bytes, sizeof unit_bytes);
        blank->send(unit_bytes, sizeof unit_bytes);
        blank->send(unit_bytes, 0);
        int pictures = 0;
        bool black = true;
        for (Frame f; blank->receive(f);) {
            ++pictures;
            black = black && f.width == 32 && f.height == 18 && f.rgba.size() == 32u * 18u * 4u;
            for (std::size_t k = 0; black && k < f.rgba.size(); k += 4) black = f.rgba[k] == 0 && f.rgba[k + 1] == 0 && f.rgba[k + 2] == 0 && f.rgba[k + 3] == 255;
        }
        blank->send(unit_bytes, sizeof unit_bytes);
        blank->flush();
        Frame after;
        std::snprintf(what, sizeof what, "blank video: %d black opaque pictures of 32x18 for two units (want 2), none after a flush", pictures);
        check(pictures == 2 && black && !blank->receive(after), what);
        std::unique_ptr<Decoder> quiet = open_blank(true, 0, 0, 44100, 2);
        quiet->send(unit_bytes, sizeof unit_bytes);
        Frame f;
        bool got = quiet->receive(f);
        bool silent = got && f.rate == 44100 && f.channels == 2 && f.pcm.size() == 2048;
        for (std::int16_t v : f.pcm) silent = silent && v == 0;
        check(silent && !quiet->receive(f), "blank sound: one AAC frame of silence (1024 samples a channel, 44100 Hz, stereo) per frame");
    }
    close(fd);
    std::printf("%d checks\n", g_checks);
    if (g_failures == 0) std::printf("ALL CHECKS PASSED\n");
    return g_failures == 0 ? 0 : 1;
}
