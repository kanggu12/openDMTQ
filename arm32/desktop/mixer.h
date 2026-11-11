// The desktop player's sound: every stream the game plays (FMOD's output, each android.media.AudioTrack) goes into one
// mixer, which plays them together on the computer's sound output at its rate, as a phone's audio server mixes its
// apps. Each stream keeps what was written in a buffer of the size the game asked for; a write waits while it is full,
// so the output's clock paces the game's audio threads as a phone's does. A stream at another rate than the output's
// is resampled (Resampler). Each stream counts the frames it was short when the output wanted them (an underrun, the
// game falling behind), and the mixer the times it came back to the output too late (the output running dry).
#pragma once

#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace player::audio {

// The output's channels: everything is mixed to stereo.
constexpr int kChannels = 2;

// A computer's choices for its sound (the player's settings file; a phone's app has its own): which device, the device
// alone or shared with the computer's other sound, how much is kept ahead of it, and how loud the game is. Set before the
// game's first sound, when the output starts.
struct Options {
    // A device's id as list_devices gives it ("": the system's default output).
    std::string device;
    // The device alone (WASAPI's exclusive mode: no other program's sound meanwhile, less latency); shared when it cannot.
    bool exclusive = false;
    // How much is kept ahead of the device: 0 low (less latency), 1 normal, 2 safe (fewer breaks on a busy computer).
    int buffer = 1;
    // The game's sound in percent, its amplitude the square of that share (half way is about half as loud).
    int volume = 100;
};
Options& options();
// The sound devices this computer has, one JSON object a line, {"id": ..., "name": ..., "default": true or false}, for
// the PC client's choice; empty where the output has no list of its own (on Linux, the sound server picks).
std::string list_devices();

// Turns stereo frames at one rate into stereo frames at another with a windowed-sinc filter: a Kaiser window over 32
// zero crossings each side of the centre, the cutoff a little below the lower rate's Nyquist frequency so that what is
// above it (the images of upsampling, what downsampling would fold back) is gone; the filter comes from a table of 256
// phases, between which it is interpolated. The same rate in and out is a copy.
class Resampler {
public:
    Resampler(int in_rate, int out_rate);
    // Makes up to `frames` output frames into `out` (interleaved stereo floats), taking input frames as it needs them
    // from `pull(dst, max)`, which puts up to `max` stereo frames in `dst` and says how many; fewer than asked means the
    // input ran out. Returns the frames made: fewer than `frames` when the input ran out, and the next call goes on
    // from there.
    template <class Pull>
    std::size_t run(float* out, std::size_t frames, Pull&& pull);
    // Starts over, as when the stream is flushed: no input kept.
    void reset();
    // How far ahead of an output frame the filter reaches, in input frames: what must be in before it can be made.
    std::size_t reach() const { return half_; }

private:
    // Makes the output frame at `pos_` from the input in `in_`.
    void make(float* out) const;
    // Drops the input frames in `in_` the filter no longer reaches.
    void trim();

    int in_rate_, out_rate_;
    bool copy_;
    // Input frames per output frame.
    double step_;
    // Taps each side of the centre, in input frames, and the table: (kPhases + 1) rows of 2 * half_ taps.
    std::size_t half_ = 0;
    std::vector<float> table_;
    // Input kept for the filter (interleaved stereo), and the position of the next output frame in it, in frames.
    std::vector<float> in_;
    double pos_ = 0;
};

// What a stream's frames are, as AudioFormat names them.
enum class Encoding { U8, S16, F32 };

// One stream: what the game writes, at its own rate, waiting to be mixed.
class Stream {
public:
    // `capacity`: the frames the buffer holds (the game's buffer size); `name`: for the counters' report.
    Stream(int rate, int channels, Encoding encoding, std::size_t capacity, std::string name, int out_rate);
    // Puts `frames` frames of the stream's format into the buffer, waiting while it is full. Returns the frames taken:
    // all of them, unless the stream was stopped or flushed while it waited.
    std::size_t write(const void* data, std::size_t frames);
    // AudioTrack's controls: play mixes the buffer from where it is, pause holds it, stop and flush drop it (and let a
    // waiting write go).
    void play();
    void pause();
    void stop();
    void flush();
    // Each channel's gain (AudioTrack.setStereoVolume).
    void volume(float left, float right);
    bool playing() const { return state_.load() == kPlaying; }
    int rate() const { return rate_; }
    const std::string& name() const { return name_; }
    // The counters, in the stream's own frames: written, and played (taken from the buffer into the mix); then the
    // output's periods the stream was short in, and the output frames it was short by.
    std::uint64_t written() const { return written_.load(); }
    std::uint64_t played() const { return played_.load(); }
    std::uint64_t underruns() const { return underruns_.load(); }
    std::uint64_t short_frames() const { return short_frames_.load(); }
    int out_rate() const { return out_rate_; }

    // The mixer's side: adds up to `frames` output frames of this stream to `out`. Not for the game's threads.
    void mix_into(float* out, std::size_t frames);

private:
    enum State { kStopped, kPaused, kPlaying };
    // Up to `max` frames from the buffer into `dst` as stereo floats; the frames taken. Under lock_.
    std::size_t take(float* dst, std::size_t max);

    const int rate_, channels_, out_rate_;
    const Encoding encoding_;
    const std::string name_;
    std::mutex lock_;
    std::condition_variable room_;
    // The buffer: stereo floats, a ring of `capacity` frames from `head_`, `size_` of them full.
    std::vector<float> ring_;
    std::size_t capacity_, head_ = 0, size_ = 0;
    // Bumped by stop and flush: a write that waited sees it and gives up on the rest.
    std::uint64_t epoch_ = 0;
    std::atomic<int> state_{kStopped};
    // Whether anything was written since play or flush: before that an empty buffer is not the game falling behind.
    bool fed_ = false;
    // Whether the stream has begun to play since it was fed: its first frames wait until a period of the output's worth is
    // there with what the resampler's filter reaches past it, while the game's buffer has room for more, or for one
    // period at most (a sound shorter than a period still plays), as Android's mixer waits for a track's first buffer;
    // what the first period lacks is silence before the stream's first frames, not a gap after them (the device alone
    // with the safe buffer's 20 ms periods, a game's buffer of 20 ms and the filter's 36 frames gave each stream a gap
    // of 1.6 ms). The periods waited so far.
    bool primed_ = false;
    int waits_ = 0;
    float gain_[kChannels] = {1.0f, 1.0f};
    Resampler resampler_;
    // The mixer's scratch for this stream's frames.
    std::vector<float> scratch_;
    std::atomic<std::uint64_t> written_{0}, played_{0}, underruns_{0}, short_frames_{0};
};

// The computer's sound output, as the mixer writes to it.
class Output {
public:
    virtual ~Output() = default;
    virtual const char* name() const = 0;
    virtual int rate() const = 0;
    // How much the output holds ahead of what is playing, in milliseconds: a mixer away longer than that let it run dry.
    virtual double buffer_ms() const = 0;
    // The frames the output takes at a time, which the mixer then makes a period of (0: the mixer's own 5 ms): a device
    // held alone plays whole buffers of its own size.
    virtual std::size_t period() const { return 0; }
    // Plays `frames` stereo float frames, waiting while the output's buffer is full: this is what paces the mixer. False
    // when the output failed and is gone.
    virtual bool write(const float* data, std::size_t frames) = 0;
};

// The mixer: one thread that mixes every playing stream, a period at a time, and writes the period to the output. It
// counts the times it came back to the output later than the output's buffer lasts (late: the output ran dry, and
// what was playing broke off), from the gaps between its writes, which no difference between clocks can fake.
class Mixer {
public:
    // The mixer of the player, its output started on first use: PLAYER_AUDIO names it ("pulse", "wasapi", "null");
    // unset, the host's own (PulseAudio on Linux, which PipeWire also serves; WASAPI on Windows), else none: the null
    // output keeps time alone.
    static Mixer& get();
    // That mixer if the game has used sound by now, else null: a report does not start an output.
    static Mixer* started();
    // A mixer on an output of the caller's (the tests'), which it starts with.
    explicit Mixer(std::unique_ptr<Output> output);
    ~Mixer();
    Mixer(const Mixer&) = delete;
    Mixer& operator=(const Mixer&) = delete;
    // A new stream in the mix, stopped.
    std::shared_ptr<Stream> open(int rate, int channels, Encoding encoding, std::size_t capacity, const std::string& name);
    // Takes the stream out of the mix (AudioTrack.release).
    void close(const std::shared_ptr<Stream>& stream);
    int rate() const { return rate_; }
    // The counters in the log: the output's, and each stream's.
    void report();
    // A period's length, unless the output takes another (Output::period): what the mixer makes at a time.
    static constexpr std::size_t kPeriodMs = 5;

private:
    void run();

    std::unique_ptr<Output> output_;
    // The output's rate, and its name and buffer, which stay when a failed output is replaced by the null one; the
    // frames of a period.
    const int rate_;
    std::size_t period_;
    // The game's volume as a gain on every sample (Options::volume).
    const float gain_;
    std::mutex lock_;
    std::vector<std::shared_ptr<Stream>> streams_;
    // Streams closed, kept for the report.
    std::vector<std::shared_ptr<Stream>> closed_;
    std::atomic<bool> running_{true};
    std::atomic<std::uint64_t> periods_{0}, late_{0};
    std::thread thread_;
};

// Another taker of the mix, the computer's broadcast (live_mf.cpp): each period on the mixer's thread, before the
// player's volume, as interleaved stereo floats at the output's rate. It must not block. Null: none.
using MixTap = void (*)(const float* stereo, std::size_t frames, int rate);
void set_mix_tap(MixTap tap);

// The outputs this host has, by name: nullptr when that one cannot start here. WASAPI takes the device's own rate.
std::unique_ptr<Output> open_null(int rate);
std::unique_ptr<Output> open_pulse(int rate);
std::unique_ptr<Output> open_wasapi(int rate);

// ---------------------------------------------------------------------------------------------------------------------

template <class Pull>
std::size_t Resampler::run(float* out, std::size_t frames, Pull&& pull) {
    if (frames == 0) return 0;
    if (copy_) {
        // The same rate: the input as it is.
        std::size_t made = 0;
        while (made < frames) {
            std::size_t got = pull(out + made * kChannels, frames - made);
            if (got == 0) break;
            made += got;
        }
        return made;
    }
    // The input all of them need, and no more: what is taken early waits here, which the game would hear as delay.
    // The filter reaches `half_` frames past each output frame's position.
    std::size_t need = static_cast<std::size_t>(pos_ + static_cast<double>(frames - 1) * step_) + half_ + 1;
    std::size_t have = in_.size() / kChannels;
    if (have < need) {
        in_.resize(need * kChannels);
        while (have < need) {
            std::size_t got = pull(in_.data() + have * kChannels, need - have);
            if (got == 0) break;
            have += got;
        }
        in_.resize(have * kChannels);
    }
    // As many as the input allows; the rest come next time, from the same place.
    std::size_t made = 0;
    while (made < frames && static_cast<std::size_t>(pos_) + half_ + 1 <= have) {
        make(out + made * kChannels);
        pos_ += step_;
        ++made;
    }
    trim();
    return made;
}

}  // namespace player::audio
