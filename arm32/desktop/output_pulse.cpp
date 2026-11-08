// The sound output on Linux: PulseAudio, which PipeWire serves as well, through its simple API. The library is loaded
// when the player starts rather than linked, so that the player still runs, without sound, on a computer without it.
#include "mixer.h"

#include "jvm.h"

#include <dlfcn.h>
#include <pulse/error.h>
#include <pulse/simple.h>

namespace player::audio {

namespace {

// What the player takes from the libraries.
struct Pulse {
    decltype(&pa_simple_new) simple_new = nullptr;
    decltype(&pa_simple_write) simple_write = nullptr;
    decltype(&pa_simple_free) simple_free = nullptr;
    decltype(&pa_strerror) error_text = nullptr;
};

// The server's buffer for the player's stream: how far ahead of what plays the mixer writes. Short, for a rhythm game's
// sounds, and four of the mixer's periods, so that a late period has three more to come in time.
constexpr double kBufferMs = 20;

class PulseOutput : public Output {
public:
    PulseOutput(const Pulse& api, pa_simple* stream, int rate) : api_(api), stream_(stream), rate_(rate) {}
    ~PulseOutput() override { api_.simple_free(stream_); }
    const char* name() const override { return "PulseAudio"; }
    int rate() const override { return rate_; }
    double buffer_ms() const override { return kBufferMs; }
    bool write(const float* data, std::size_t frames) override {
        int error = 0;
        // Waits while the server's buffer for the stream is full.
        if (api_.simple_write(stream_, data, frames * kChannels * sizeof(float), &error) < 0) {
            jvm::log("player: PulseAudio: %s", api_.error_text(error));
            return false;
        }
        return true;
    }

private:
    Pulse api_;
    pa_simple* stream_;
    int rate_;
};

}  // namespace

std::unique_ptr<Output> open_pulse(int rate) {
    // pa_strerror is in libpulse itself, which libpulse-simple uses.
    void* simple = dlopen("libpulse-simple.so.0", RTLD_NOW | RTLD_LOCAL);
    void* pulse = simple ? dlopen("libpulse.so.0", RTLD_NOW | RTLD_LOCAL) : nullptr;
    if (!simple || !pulse) return nullptr;
    Pulse api;
    api.simple_new = reinterpret_cast<decltype(api.simple_new)>(dlsym(simple, "pa_simple_new"));
    api.simple_write = reinterpret_cast<decltype(api.simple_write)>(dlsym(simple, "pa_simple_write"));
    api.simple_free = reinterpret_cast<decltype(api.simple_free)>(dlsym(simple, "pa_simple_free"));
    api.error_text = reinterpret_cast<decltype(api.error_text)>(dlsym(pulse, "pa_strerror"));
    if (!api.simple_new || !api.simple_write || !api.simple_free || !api.error_text) return nullptr;
    // The mixer's own format: stereo floats at its rate; the server converts for the sound card if it must.
    pa_sample_spec spec{};
    spec.format = PA_SAMPLE_FLOAT32LE;
    spec.rate = static_cast<std::uint32_t>(rate);
    spec.channels = kChannels;
    const auto bytes = [rate](double ms) { return static_cast<std::uint32_t>(rate * ms / 1000) * kChannels * sizeof(float); };
    pa_buffer_attr attr{};
    // The server's defaults for what the simple API leaves to it; the target fill and the smallest request ours.
    attr.maxlength = static_cast<std::uint32_t>(-1);
    attr.tlength = bytes(kBufferMs);
    attr.prebuf = static_cast<std::uint32_t>(-1);
    attr.minreq = bytes(static_cast<double>(Mixer::kPeriodMs));
    attr.fragsize = static_cast<std::uint32_t>(-1);
    int error = 0;
    pa_simple* stream = api.simple_new(nullptr, "OpenDMTQ", PA_STREAM_PLAYBACK, nullptr, "game", &spec, nullptr, &attr, &error);
    if (!stream) {
        jvm::log("player: PulseAudio: %s", api.error_text(error));
        return nullptr;
    }
    return std::make_unique<PulseOutput>(api, stream, rate);
}

}  // namespace player::audio
