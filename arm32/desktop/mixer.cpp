// The mixer, its resampler and streams, and the null output (mixer.h says what each is for).
#include "mixer.h"

#include "jvm.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <sys/prctl.h>

namespace player::audio {

namespace {

// The filter's table: phases between two input frames.
constexpr std::size_t kPhases = 256;
// Zero crossings of the filter each side of its centre: its length, and so how steep its cutoff is.
constexpr double kZeros = 32;
// The cutoff, as a part of the lower rate's Nyquist frequency: the filter falls from full to nothing around it, and is
// well down by the Nyquist frequency itself.
constexpr double kRolloff = 0.91;
// The Kaiser window's beta: about 90 dB down outside the band.
constexpr double kBeta = 9.0;
constexpr double kPi = 3.14159265358979323846;

// The modified Bessel function I0, which the Kaiser window is made of: its series converges fast for these arguments.
double bessel_i0(double x) {
    double sum = 1, term = 1;
    for (int k = 1; k < 64; ++k) {
        term *= (x / (2 * k)) * (x / (2 * k));
        sum += term;
        if (term < sum * 1e-17) break;
    }
    return sum;
}

}  // namespace

Resampler::Resampler(int in_rate, int out_rate)
    : in_rate_(in_rate > 0 ? in_rate : out_rate), out_rate_(out_rate), copy_(in_rate_ == out_rate_),
      step_(static_cast<double>(in_rate_) / out_rate_) {
    if (copy_) return;
    // The cutoff, relative to the input's Nyquist frequency: below the output's when the output is the lower rate.
    double cutoff = std::min(1.0, static_cast<double>(out_rate_) / in_rate_) * kRolloff;
    // The filter's half-length in input frames: its zero crossings are 1/cutoff frames apart.
    half_ = static_cast<std::size_t>(std::ceil(kZeros / cutoff));
    std::size_t taps = 2 * half_;
    table_.resize((kPhases + 1) * taps);
    double i0_beta = bessel_i0(kBeta);
    for (std::size_t p = 0; p <= kPhases; ++p) {
        // Row p: the output frame `p / kPhases` of the way from one input frame to the next.
        double frac = static_cast<double>(p) / kPhases;
        float* row = &table_[p * taps];
        double sum = 0;
        for (std::size_t k = 0; k < taps; ++k) {
            // Tap k is input frame (k - half_ + 1) from the one before the output frame: d frames from it.
            double d = static_cast<double>(k) - static_cast<double>(half_) + 1 - frac;
            double x = cutoff * d;
            double sinc = x == 0 ? 1 : std::sin(kPi * x) / (kPi * x);
            double t = d / static_cast<double>(half_);
            double window = std::abs(t) < 1 ? bessel_i0(kBeta * std::sqrt(1 - t * t)) / i0_beta : 0;
            double h = cutoff * sinc * window;
            row[k] = static_cast<float>(h);
            sum += h;
        }
        // Each row adds up to one: a steady input comes out at the same level whatever the phase.
        for (std::size_t k = 0; k < taps; ++k) row[k] = static_cast<float>(row[k] / sum);
    }
    reset();
}

void Resampler::reset() {
    if (copy_) return;
    // Silence before the first input frame, as far back as the filter reaches; the first output frame is the first
    // input frame's instant.
    in_.assign((half_ - 1) * kChannels, 0.0f);
    pos_ = static_cast<double>(half_ - 1);
}

void Resampler::make(float* out) const {
    std::size_t i = static_cast<std::size_t>(pos_);
    // Where the output frame falls between input frames i and i + 1, as a row of the table and the way to the next.
    double ph = (pos_ - static_cast<double>(i)) * kPhases;
    std::size_t p = std::min(static_cast<std::size_t>(ph), kPhases - 1);
    float w = static_cast<float>(ph - static_cast<double>(p));
    std::size_t taps = 2 * half_;
    const float* a = &table_[p * taps];
    const float* b = a + taps;
    // The first input frame the filter reaches.
    const float* x = &in_[(i + 1 - half_) * kChannels];
    float left = 0, right = 0;
    for (std::size_t k = 0; k < taps; ++k) {
        float c = a[k] + (b[k] - a[k]) * w;
        left += x[2 * k] * c;
        right += x[2 * k + 1] * c;
    }
    out[0] = left;
    out[1] = right;
}

void Resampler::trim() {
    // The first frame the next output frame's filter reaches; those before it are done with.
    std::size_t first = static_cast<std::size_t>(pos_) + 1 - half_;
    if (first == 0) return;
    in_.erase(in_.begin(), in_.begin() + static_cast<std::ptrdiff_t>(first * kChannels));
    pos_ -= static_cast<double>(first);
}

// ---------------------------------------------------------------------------------------------------------------------

Stream::Stream(int rate, int channels, Encoding encoding, std::size_t capacity, std::string name, int out_rate)
    : rate_(rate > 0 ? rate : out_rate), channels_(channels > 0 ? channels : 1), out_rate_(out_rate), encoding_(encoding), name_(std::move(name)),
      ring_(std::max<std::size_t>(capacity, 1) * kChannels), capacity_(std::max<std::size_t>(capacity, 1)),
      resampler_(rate_, out_rate) {}

std::size_t Stream::write(const void* data, std::size_t frames) {
    const auto* in = static_cast<const std::uint8_t*>(data);
    const std::size_t sample_bytes = encoding_ == Encoding::U8 ? 1 : encoding_ == Encoding::S16 ? 2 : 4;
    const std::size_t frame_bytes = sample_bytes * static_cast<std::size_t>(channels_);
    std::unique_lock<std::mutex> l(lock_);
    const std::uint64_t epoch = epoch_;
    std::size_t done = 0;
    while (done < frames) {
        // Full: wait for the mixer to take some, as AudioTrack.write waits; a stop or flush lets the write go.
        room_.wait(l, [&] { return size_ < capacity_ || epoch_ != epoch; });
        if (epoch_ != epoch) break;
        std::size_t n = std::min(frames - done, capacity_ - size_);
        for (std::size_t k = 0; k < n; ++k) {
            const std::uint8_t* f = in + (done + k) * frame_bytes;
            float s[2];
            // The first two channels; one channel is both.
            for (int c = 0; c < 2; ++c) {
                const std::uint8_t* v = f + static_cast<std::size_t>(std::min(c, channels_ - 1)) * sample_bytes;
                if (encoding_ == Encoding::U8) {
                    s[c] = (static_cast<float>(*v) - 128.0f) / 128.0f;
                } else if (encoding_ == Encoding::S16) {
                    std::int16_t x;
                    std::memcpy(&x, v, 2);
                    s[c] = static_cast<float>(x) / 32768.0f;
                } else {
                    std::memcpy(&s[c], v, 4);
                }
            }
            std::size_t at = ((head_ + size_ + k) % capacity_) * kChannels;
            ring_[at] = s[0];
            ring_[at + 1] = s[1];
        }
        size_ += n;
        done += n;
        fed_ = true;
        written_ += n;
    }
    return done;
}

std::size_t Stream::take(float* dst, std::size_t max) {
    std::size_t n = std::min(max, size_);
    for (std::size_t k = 0; k < n; ++k) {
        std::size_t at = ((head_ + k) % capacity_) * kChannels;
        dst[k * kChannels] = ring_[at];
        dst[k * kChannels + 1] = ring_[at + 1];
    }
    head_ = (head_ + n) % capacity_;
    size_ -= n;
    played_ += n;
    return n;
}

void Stream::play() {
    std::lock_guard<std::mutex> l(lock_);
    state_ = kPlaying;
}

void Stream::pause() {
    std::lock_guard<std::mutex> l(lock_);
    if (state_ == kPlaying) state_ = kPaused;
}

void Stream::stop() {
    {
        std::lock_guard<std::mutex> l(lock_);
        state_ = kStopped;
        // What was not played goes; the next play starts from what is written then, with nothing of the old.
        head_ = size_ = 0;
        fed_ = false;
        ++epoch_;
        resampler_.reset();
    }
    room_.notify_all();
}

void Stream::flush() {
    {
        std::lock_guard<std::mutex> l(lock_);
        // As AudioTrack.flush: only a stream that is not playing drops its buffer.
        if (state_ == kPlaying) return;
        head_ = size_ = 0;
        fed_ = false;
        ++epoch_;
        resampler_.reset();
    }
    room_.notify_all();
}

void Stream::volume(float left, float right) {
    std::lock_guard<std::mutex> l(lock_);
    gain_[0] = std::clamp(left, 0.0f, 1.0f);
    gain_[1] = std::clamp(right, 0.0f, 1.0f);
}

void Stream::mix_into(float* out, std::size_t frames) {
    std::size_t made;
    float gain[kChannels];
    {
        std::lock_guard<std::mutex> l(lock_);
        if (state_ != kPlaying) return;
        scratch_.resize(frames * kChannels);
        made = resampler_.run(scratch_.data(), frames, [this](float* dst, std::size_t max) { return take(dst, max); });
        // Short after the game had begun writing: it fell behind, and the gap is silence.
        if (made < frames && fed_) {
            ++underruns_;
            short_frames_ += frames - made;
        }
        gain[0] = gain_[0];
        gain[1] = gain_[1];
    }
    // Room for the writer, which may be waiting.
    room_.notify_all();
    for (std::size_t k = 0; k < made; ++k) {
        out[k * kChannels] += scratch_[k * kChannels] * gain[0];
        out[k * kChannels + 1] += scratch_[k * kChannels + 1] * gain[1];
    }
}

// ---------------------------------------------------------------------------------------------------------------------

Mixer::Mixer(std::unique_ptr<Output> output)
    : output_(std::move(output)), rate_(output_->rate()),
      period_(static_cast<std::size_t>(rate_) * kPeriodMs / 1000) {
    jvm::log("player: sound out through %s at %d Hz, %zu ms a period, %.0f ms buffered", output_->name(), rate_, kPeriodMs,
             output_->buffer_ms());
    thread_ = std::thread([this] { run(); });
}

Mixer::~Mixer() {
    running_ = false;
    if (thread_.joinable()) thread_.join();
}

namespace {
// The player's mixer, once it is made.
std::atomic<Mixer*> g_mixer{nullptr};
}  // namespace

Mixer* Mixer::started() { return g_mixer.load(); }

Mixer& Mixer::get() {
    static Mixer* mixer = [] {
        // The rate a desktop's sound runs at.
        const int rate = 48000;
        const char* want = std::getenv("PLAYER_AUDIO");
        std::string name = want ? want : "";
        std::unique_ptr<Output> out;
#ifdef _WIN32
        const char* own = "wasapi";
        if (name.empty() || name == own) out = open_wasapi(rate);
#else
        const char* own = "pulse";
        if (name.empty() || name == own) out = open_pulse(rate);
#endif
        if (!out && name == own) jvm::log("player: PLAYER_AUDIO=%s, and it cannot start: no sound", own);
        if (!out && name.empty()) jvm::log("player: no sound output found: no sound");
        if (!out && !name.empty() && name != own && name != "null") jvm::log("player: PLAYER_AUDIO=%s: no such output here: no sound", name.c_str());
        if (!out) out = open_null(rate);
        // Never destroyed: the player leaves with _exit while the game's threads still write.
        auto* m = new Mixer(std::move(out));
        g_mixer = m;
        return m;
    }();
    return *mixer;
}

std::shared_ptr<Stream> Mixer::open(int rate, int channels, Encoding encoding, std::size_t capacity, const std::string& name) {
    auto s = std::make_shared<Stream>(rate, channels, encoding, capacity, name, rate_);
    std::lock_guard<std::mutex> l(lock_);
    streams_.push_back(s);
    return s;
}

void Mixer::close(const std::shared_ptr<Stream>& stream) {
    if (!stream) return;
    // A write still waiting on it goes first.
    stream->stop();
    std::lock_guard<std::mutex> l(lock_);
    auto it = std::find(streams_.begin(), streams_.end(), stream);
    if (it == streams_.end()) return;
    streams_.erase(it);
    // Kept for the report while there are few; a game that opens streams without end keeps the last ones.
    closed_.push_back(stream);
    if (closed_.size() > 32) closed_.erase(closed_.begin());
}

void Mixer::report() {
    std::lock_guard<std::mutex> l(lock_);
    jvm::log("audio: %s at %d Hz: %.1f s in periods of %zu ms, %llu late", output_->name(), rate_,
             static_cast<double>(periods_.load() * period_) / rate_, kPeriodMs, static_cast<unsigned long long>(late_.load()));
    // Seconds, whatever each stream's rate.
    auto line = [](const Stream& s, const char* state) {
        jvm::log("audio: %s at %d Hz (%s): %.1f s written, %.1f s played, %llu underruns (%.1f ms short)", s.name().c_str(), s.rate(),
                 state, static_cast<double>(s.written()) / s.rate(), static_cast<double>(s.played()) / s.rate(),
                 static_cast<unsigned long long>(s.underruns()), 1000.0 * static_cast<double>(s.short_frames()) / s.out_rate());
    };
    for (const auto& s : streams_) line(*s, s->playing() ? "playing" : "not playing");
    for (const auto& s : closed_) line(*s, "closed");
}

void Mixer::run() {
    // Its name for the stats and a debugger (the mixer's tests run without the player's thread helpers).
    prctl(PR_SET_NAME, "mixer");
    std::vector<float> buf(period_ * kChannels);
    using Clock = std::chrono::steady_clock;
    Clock::time_point last{};
    // With ARM32_STATS=1 the counters go to the log every five seconds, beside the runtime's own.
    const char* stats = std::getenv("ARM32_STATS");
    const bool report_often = stats && std::atoi(stats) > 0;
    Clock::time_point next_report = Clock::now() + std::chrono::seconds(5);
    while (running_.load()) {
        if (report_often && Clock::now() >= next_report) {
            report();
            next_report += std::chrono::seconds(5);
        }
        std::fill(buf.begin(), buf.end(), 0.0f);
        {
            std::lock_guard<std::mutex> l(lock_);
            for (const auto& s : streams_) s->mix_into(buf.data(), period_);
        }
        // A sum louder than full scale is held at full scale, as a phone's mixer holds it.
        for (float& v : buf) v = std::clamp(v, -1.0f, 1.0f);
        // Away from the output longer than its buffer lasts: it ran dry.
        Clock::time_point now = Clock::now();
        if (last != Clock::time_point{} && now - last > std::chrono::duration<double, std::milli>(output_->buffer_ms())) ++late_;
        if (!output_->write(buf.data(), period_)) {
            jvm::log("player: %s failed: no sound from here on", output_->name());
            // Under the lock: report() reads the output from another thread.
            std::lock_guard<std::mutex> l(lock_);
            output_ = open_null(rate_);
        }
        last = Clock::now();
        ++periods_;
    }
}

// ---------------------------------------------------------------------------------------------------------------------
// The null output: no sound, the time it would take. It keeps a sound card's buffer of 20 ms ahead of the clock.

namespace {

class NullOutput : public Output {
public:
    explicit NullOutput(int rate) : rate_(rate) {}
    const char* name() const override { return "no output"; }
    int rate() const override { return rate_; }
    double buffer_ms() const override { return kBufferMs; }
    bool write(const float*, std::size_t frames) override {
        auto now = std::chrono::steady_clock::now();
        // What was written plays out from where the last write ended, or from now when that is past (the mixer was away).
        if (due_ < now) due_ = now;
        due_ += std::chrono::nanoseconds(static_cast<long long>(1e9 * static_cast<double>(frames) / rate_));
        // Full: wait until the buffer has room for the next period.
        auto room_at = due_ - std::chrono::microseconds(static_cast<long long>(kBufferMs * 1000));
        if (room_at > now) std::this_thread::sleep_until(room_at);
        return true;
    }

private:
    static constexpr double kBufferMs = 20;
    int rate_;
    std::chrono::steady_clock::time_point due_{};
};

}  // namespace

std::unique_ptr<Output> open_null(int rate) { return std::make_unique<NullOutput>(rate); }

}  // namespace player::audio
