// Tests of the desktop player's mixer (mixer.h), on the host alone: the resampler's accuracy (a tone in the band comes
// out as the same tone with everything else far below it, a tone above the output's band does not fold back into it),
// a stream's formats, its write waiting while the buffer is full and its underrun counter, the mix of two streams and
// its clipping, and the null output keeping real time. Prints one line per check, then "ALL CHECKS PASSED".
#include "mixer.h"

#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <thread>
#include <vector>

using namespace player::audio;

namespace {

int g_checks = 0, g_failures = 0;

void check(bool ok, const char* what) {
    ++g_checks;
    if (!ok) ++g_failures;
    std::printf("%s %s\n", ok ? "ok  " : "FAIL", what);
}

constexpr double kPi = 3.14159265358979323846;

// A tone of `freq` Hz at `rate`, `seconds` long, as interleaved stereo.
std::vector<float> tone(double freq, int rate, double seconds, double amplitude) {
    std::size_t frames = static_cast<std::size_t>(rate * seconds);
    std::vector<float> v(frames * kChannels);
    for (std::size_t n = 0; n < frames; ++n) {
        float x = static_cast<float>(amplitude * std::sin(2 * kPi * freq * static_cast<double>(n) / rate));
        v[n * 2] = x;
        v[n * 2 + 1] = x;
    }
    return v;
}

// `input` through a resampler, a period of output at a time as the mixer asks for it.
std::vector<float> resample(const std::vector<float>& input, int in_rate, int out_rate) {
    Resampler r(in_rate, out_rate);
    std::size_t at = 0, in_frames = input.size() / kChannels;
    std::vector<float> out;
    std::vector<float> period(240 * kChannels);
    for (;;) {
        std::size_t made = r.run(period.data(), 240, [&](float* dst, std::size_t max) {
            std::size_t n = std::min(max, in_frames - at);
            std::memcpy(dst, input.data() + at * kChannels, n * kChannels * sizeof(float));
            at += n;
            return n;
        });
        out.insert(out.end(), period.begin(), period.begin() + static_cast<std::ptrdiff_t>(made * kChannels));
        if (made < 240) break;
    }
    return out;
}

// The ratio of a tone's power to that of everything else in `out` (the tone `freq` at `rate` it should be), in dB, left
// channel, away from the ends where the input starts and stops.
double snr_db(const std::vector<float>& out, double freq, int rate, double amplitude) {
    double signal = 0, noise = 0;
    std::size_t frames = out.size() / kChannels;
    for (std::size_t n = 500; n + 500 < frames; ++n) {
        double want = amplitude * std::sin(2 * kPi * freq * static_cast<double>(n) / rate);
        double got = out[n * 2];
        signal += want * want;
        noise += (got - want) * (got - want);
    }
    return 10 * std::log10(signal / std::max(noise, 1e-30));
}

// The level of `out` against `amplitude`, in dB, away from the ends.
double level_db(const std::vector<float>& out, double amplitude) {
    double power = 0;
    std::size_t frames = out.size() / kChannels, n0 = 500, count = 0;
    for (std::size_t n = n0; n + 500 < frames; ++n, ++count) power += static_cast<double>(out[n * 2]) * out[n * 2];
    double rms = std::sqrt(power / std::max<std::size_t>(count, 1));
    return 20 * std::log10(std::max(rms, 1e-30) / (amplitude / std::sqrt(2.0)));
}

// An output for the tests: keeps what the mixer writes, a period every millisecond. Made shut, it holds the mixer at
// its first write until the test opens it: what the test sets up meanwhile starts in one and the same period.
class Capture : public Output {
public:
    Capture(int rate, bool open) : rate_(rate), open_(open) {}
    const char* name() const override { return "capture"; }
    int rate() const override { return rate_; }
    double buffer_ms() const override { return 1000; }
    bool write(const float* data, std::size_t frames) override {
        std::unique_lock<std::mutex> l(lock_);
        frames_.insert(frames_.end(), data, data + frames * kChannels);
        opened_.wait(l, [this] { return open_; });
        l.unlock();
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
        return true;
    }
    void open() {
        {
            std::lock_guard<std::mutex> l(lock_);
            open_ = true;
        }
        opened_.notify_all();
    }
    std::vector<float> taken() {
        std::lock_guard<std::mutex> l(lock_);
        return frames_;
    }

private:
    int rate_;
    std::mutex lock_;
    std::condition_variable opened_;
    bool open_;
    std::vector<float> frames_;
};

}  // namespace

int main() {
    char what[200];

    // Tones well inside the band, through each change of rate the game's streams need: FMOD at 24000 Hz and OpenAL at
    // 44100 Hz to the output's 48000 Hz, and a 48000 Hz stream to a 44100 Hz sound card.
    struct Case {
        int in, out;
        double freq;
    } cases[] = {{24000, 48000, 1000}, {24000, 48000, 9000}, {44100, 48000, 1000}, {44100, 48000, 17000},
                 {48000, 44100, 1000}, {48000, 44100, 17000}, {22050, 48000, 8000}};
    for (const Case& k : cases) {
        std::vector<float> out = resample(tone(k.freq, k.in, 1.0, 0.5), k.in, k.out);
        double snr = snr_db(out, k.freq, k.out, 0.5);
        std::snprintf(what, sizeof what, "%d Hz to %d Hz, a %.0f Hz tone: %.1f dB above the rest (want 80)", k.in, k.out, k.freq, snr);
        check(snr >= 80, what);
        // As long as the input says: a second in, a second out.
        std::size_t frames = out.size() / kChannels;
        std::snprintf(what, sizeof what, "%d Hz to %d Hz: %zu frames from a second (want %d, less the filter's reach)", k.in, k.out, frames, k.out);
        check(frames <= static_cast<std::size_t>(k.out) && frames + 100 >= static_cast<std::size_t>(k.out), what);
    }
    // Above the output's band: a 23000 Hz tone at 48000 Hz has no place at 44100 Hz, and must not fold back to 21100 Hz.
    {
        std::vector<float> out = resample(tone(23000, 48000, 1.0, 0.5), 48000, 44100);
        double level = level_db(out, 0.5);
        std::snprintf(what, sizeof what, "48000 Hz to 44100 Hz, a 23000 Hz tone: %.1f dB (want -80 or less)", level);
        check(level <= -80, what);
    }
    // The same rate in and out: the very samples.
    {
        std::vector<float> in = tone(440, 48000, 0.1, 0.5);
        std::vector<float> out = resample(in, 48000, 48000);
        check(out == in, "48000 Hz to 48000 Hz: the input as it is");
    }

    // A stream's formats: one channel is both, 8-bit is unsigned, 16-bit and float as they are. Streams of no mixer,
    // which the test mixes itself.
    {
        Stream s16(48000, 1, Encoding::S16, 1000, "s16", 48000), u8(48000, 2, Encoding::U8, 1000, "u8", 48000),
            f32(48000, 2, Encoding::F32, 1000, "f32", 48000);
        const std::int16_t mono[2] = {16384, -32768};
        const std::uint8_t bytes[4] = {192, 64, 128, 255};
        const float floats[4] = {0.25f, -0.5f, 0.0f, 1.0f};
        check(s16.write(mono, 2) == 2 && u8.write(bytes, 2) == 2 && f32.write(floats, 2) == 2, "writes of each format take every frame");
        std::vector<float> out(2 * kChannels, 0.0f);
        s16.play();
        s16.mix_into(out.data(), 2);
        check(out[0] == 0.5f && out[1] == 0.5f && out[2] == -1.0f && out[3] == -1.0f, "16-bit mono: each sample on both channels");
        std::fill(out.begin(), out.end(), 0.0f);
        u8.play();
        u8.mix_into(out.data(), 2);
        check(out[0] == 0.5f && out[1] == -0.5f && out[2] == 0.0f && out[3] == 127.0f / 128.0f, "8-bit stereo: 128 is silence");
        std::fill(out.begin(), out.end(), 0.0f);
        f32.play();
        f32.volume(0.5f, 1.0f);
        f32.mix_into(out.data(), 2);
        check(out[0] == 0.125f && out[1] == -0.5f && out[2] == 0.0f && out[3] == 1.0f, "float stereo, with each channel's gain");
    }

    // A write waits while the buffer is full, and goes on as the mixer takes frames; a stop lets it go.
    {
        Mixer mixer(std::make_unique<Capture>(48000, true));
        auto s = mixer.open(48000, 2, Encoding::F32, 100, "blocking");
        std::vector<float> data(300 * kChannels, 0.25f);
        std::atomic<std::size_t> taken{0};
        std::thread writer([&] { taken = s->write(data.data(), 300); });
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        std::snprintf(what, sizeof what, "a write of 300 frames into a buffer of 100 waits: %zu frames in", static_cast<std::size_t>(s->written()));
        check(taken.load() == 0 && s->written() == 100, what);
        // Playing: the mixer takes a period at a time, and the rest goes in.
        s->play();
        writer.join();
        check(taken.load() == 300, "once the stream plays, the write takes all 300");
        // A stop lets a waiting write go with what it got in.
        auto t = mixer.open(48000, 2, Encoding::F32, 100, "stopped");
        std::thread second([&] { taken = t->write(data.data(), 300); });
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        t->stop();
        second.join();
        std::snprintf(what, sizeof what, "a stop lets a waiting write go: %zu frames taken (want 100)", taken.load());
        check(taken.load() == 100, what);
        mixer.close(s);
        mixer.close(t);
    }

    // Underruns: a playing stream that had frames and runs out counts the period and the frames it was short; one
    // that never had any does not.
    {
        Stream fed(48000, 2, Encoding::F32, 1000, "fed", 48000), empty(48000, 2, Encoding::F32, 1000, "never fed", 48000);
        std::vector<float> data(100 * kChannels, 0.25f);
        fed.write(data.data(), 100);
        std::vector<float> out(240 * kChannels, 0.0f);
        fed.play();
        empty.play();
        fed.mix_into(out.data(), 240);
        empty.mix_into(out.data(), 240);
        std::snprintf(what, sizeof what, "a stream 140 frames short: %llu underrun, %llu frames short", static_cast<unsigned long long>(fed.underruns()),
                      static_cast<unsigned long long>(fed.short_frames()));
        check(fed.underruns() == 1 && fed.short_frames() == 140 && fed.played() == 100, what);
        check(empty.underruns() == 0, "a stream nothing was written to is not short");
    }

    // The mix: two streams add up, and a sum beyond full scale is held at it.
    {
        // Shut until both streams play, so that they start in the same period.
        auto capture = std::make_unique<Capture>(48000, false);
        Capture* cap = capture.get();
        Mixer mixer(std::move(capture));
        auto a = mixer.open(48000, 2, Encoding::F32, 4800, "a");
        auto b = mixer.open(48000, 2, Encoding::F32, 4800, "b");
        std::vector<float> quarter(2400 * kChannels, 0.25f), loud(2400 * kChannels, 0.9f);
        a->write(quarter.data(), 2400);
        b->write(quarter.data(), 2400);
        b->write(loud.data(), 2400);
        a->write(loud.data(), 2400);
        a->play();
        b->play();
        cap->open();
        // Until both have been mixed whole.
        for (int k = 0; k < 400 && (a->played() < 4800 || b->played() < 4800); ++k) std::this_thread::sleep_for(std::chrono::milliseconds(5));
        std::vector<float> got = cap->taken();
        // Somewhere in the first half both quarters, in the second both loud ones.
        std::size_t halves = 0, clipped = 0;
        for (std::size_t n = 0; n < got.size(); ++n) {
            if (got[n] == 0.5f) ++halves;
            if (got[n] == 1.0f) ++clipped;
        }
        std::snprintf(what, sizeof what, "two streams mixed: %zu samples at 0.25 + 0.25, %zu at 0.9 + 0.9 held at 1 (want 4800 each)", halves, clipped);
        check(halves == 4800 && clipped == 4800, what);
        mixer.close(a);
        mixer.close(b);
    }

    // The null output keeps real time: a second of periods in a second, give or take its 20 ms buffer and a period.
    {
        Mixer mixer(open_null(48000));
        auto s = mixer.open(48000, 2, Encoding::F32, 96000, "timed");
        std::vector<float> data(96000 * kChannels, 0.0f);
        s->write(data.data(), 96000);
        auto t0 = std::chrono::steady_clock::now();
        s->play();
        std::this_thread::sleep_for(std::chrono::milliseconds(1000));
        double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        double mixed_s = static_cast<double>(s->played()) / 48000;
        std::snprintf(what, sizeof what, "the null output: %.3f s of sound in %.3f s (want the same, give or take 40 ms)", mixed_s, seconds);
        check(std::abs(mixed_s - seconds) < 0.04, what);
        mixer.close(s);
    }

    std::printf("%d checks\n", g_checks);
    if (g_failures == 0) std::printf("ALL CHECKS PASSED\n");
    return g_failures == 0 ? 0 : 1;
}
