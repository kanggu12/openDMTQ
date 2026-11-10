// The game's sound output, both ways it has:
//   - FMOD's Java output (org.fmod.FMODAudioDevice), which the game's FMOD uses when the device has no low-latency
//     audio: a thread asks FMOD for each block (fmodProcess, 16-bit stereo at FMOD's rate) and writes it to an
//     AudioTrack, as FMODAudioDevice.run does;
//   - android.media.AudioTrack itself, which the game's OpenAL writes to from a mixing thread of its own.
// Every AudioTrack, FMOD's included, is a stream of the player's mixer (mixer.h) with a buffer of the size the game
// asked for: a write waits while it is full, which keeps the game's audio threads to the sound card's clock as on a
// phone.
#include "mixer.h"
#include "player.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <thread>

namespace player {

namespace {

using jvm::Call;
using jvm::Class;
using jvm::Object;
using jvm::Ref;
using jvm::Value;

// What fmodGetInfo answers, by its argument (FMODAudioDevice's own constants).
constexpr jint kSampleRate = 0, kBlockLength = 1, kBlockCount = 2, kRunning = 3;
// AudioTrack's play states and errors.
constexpr jint kStopped = 1, kPaused = 2, kPlaying = 3, kErrorBadValue = -2, kErrorInvalidOperation = -3;

// AudioFormat's channel configurations: the old CHANNEL_CONFIGURATION_MONO 2 and the newer CHANNEL_OUT_MONO 4 are one
// channel, anything else two.
int channel_count(jint config) { return config == 2 || config == 4 ? 1 : 2; }
// AudioFormat's encodings: 8-bit 3, float 4, anything else 16-bit.
audio::Encoding encoding_of(jint format) { return format == 3 ? audio::Encoding::U8 : format == 4 ? audio::Encoding::F32 : audio::Encoding::S16; }
jint frame_bytes(jint config, jint format) {
    jint sample = format == 3 ? 1 : format == 4 ? 4 : 2;
    return channel_count(config) * sample;
}

// AudioTracks by number, in the order they were made, for the counters' report.
std::atomic<int> g_tracks{0};

// android.media.AudioTrack: a stream of the mixer.
class Track : public Object {
public:
    using Object::Object;
    ~Track() override { release(); }
    // Out of the mix (AudioTrack.release, or the game letting go of it).
    void release() {
        std::shared_ptr<audio::Stream> s;
        {
            std::lock_guard<std::mutex> l(lock);
            s.swap(stream);
        }
        if (s) audio::Mixer::get().close(s);
    }
    std::shared_ptr<audio::Stream> current() {
        std::lock_guard<std::mutex> l(lock);
        return stream;
    }
    jint rate = 48000, config = 12, format = 2, bytes_per_frame = 4;
    std::atomic<jint> play_state{kStopped};
    std::mutex lock;
    std::shared_ptr<audio::Stream> stream;
};

Track& track(Call& c) { return c.self_as<Track>(); }

// Writes `bytes` bytes of the track's frames: all of them are taken, once the buffer has room for them.
Value write(Call& c, const void* data, jint bytes) {
    Track& t = track(c);
    std::shared_ptr<audio::Stream> s = t.current();
    if (!s) return Value::I(kErrorInvalidOperation);
    if (bytes <= 0) return Value::I(0);
    std::size_t frames = static_cast<std::size_t>(bytes / t.bytes_per_frame);
    std::size_t taken = s->write(data, frames);
    return Value::I(static_cast<jint>(taken) * t.bytes_per_frame);
}

void define_track() {
    Class& c = jvm::define("android/media/AudioTrack");
    c.make = [](Class& k) -> Object* { return new Track(&k); };
    c.static_field("MODE_STREAM", "I", Value::I(1));
    c.static_field("STATE_INITIALIZED", "I", Value::I(1));
    c.static_field("PLAYSTATE_STOPPED", "I", Value::I(kStopped));
    c.static_field("PLAYSTATE_PAUSED", "I", Value::I(kPaused));
    c.static_field("PLAYSTATE_PLAYING", "I", Value::I(kPlaying));
    c.static_field("ERROR_BAD_VALUE", "I", Value::I(kErrorBadValue));
    c.static_field("ERROR_INVALID_OPERATION", "I", Value::I(kErrorInvalidOperation));
    Class& f = jvm::define("android/media/AudioFormat");
    f.static_field("ENCODING_PCM_16BIT", "I", Value::I(2));
    f.static_field("ENCODING_PCM_8BIT", "I", Value::I(3));
    f.static_field("ENCODING_PCM_FLOAT", "I", Value::I(4));
    f.static_field("CHANNEL_OUT_MONO", "I", Value::I(4));
    f.static_field("CHANNEL_OUT_STEREO", "I", Value::I(12));
    f.static_field("CHANNEL_CONFIGURATION_MONO", "I", Value::I(2));
    f.static_field("CHANNEL_CONFIGURATION_STEREO", "I", Value::I(3));
    // The smallest buffer: 20 ms, a desktop sound card's period.
    c.static_method("getMinBufferSize", "(III)I", [](Call& c) {
        if (c.i(0) <= 0) return Value::I(kErrorBadValue);
        return Value::I(c.i(0) / 50 * frame_bytes(c.i(1), c.i(2)));
    });
    // The mixer's rate, which a track at it plays without resampling.
    c.static_method("getNativeOutputSampleRate", "(I)I", [](Call&) { return Value::I(audio::Mixer::get().rate()); });
    // (stream type, rate, channels, encoding, buffer bytes, mode): a stream of the mixer, stopped, with that buffer.
    c.method("<init>", "(IIIIII)V", [](Call& c) {
        Track& t = track(c);
        t.rate = c.i(1) > 0 ? c.i(1) : audio::Mixer::get().rate();
        t.config = c.i(2);
        t.format = c.i(3);
        t.bytes_per_frame = frame_bytes(t.config, t.format);
        std::size_t capacity = static_cast<std::size_t>(std::max<jint>(c.i(4), t.bytes_per_frame) / t.bytes_per_frame);
        std::string name = "AudioTrack " + std::to_string(++g_tracks);
        auto s = audio::Mixer::get().open(t.rate, channel_count(t.config), encoding_of(t.format), capacity, name);
        std::lock_guard<std::mutex> l(t.lock);
        t.stream = std::move(s);
        return Value();
    });
    c.method("getState", "()I", [](Call& c) { return Value::I(track(c).current() ? 1 : 0); });
    c.method("getPlayState", "()I", [](Call& c) { return Value::I(track(c).play_state.load()); });
    c.method("getSampleRate", "()I", [](Call& c) { return Value::I(track(c).rate); });
    c.method("getChannelCount", "()I", [](Call& c) { return Value::I(channel_count(track(c).config)); });
    c.method("getAudioFormat", "()I", [](Call& c) { return Value::I(track(c).format); });
    // Frames played since the track started, as the frame counter a phone gives (it wraps as an int does).
    c.method("getPlaybackHeadPosition", "()I", [](Call& c) {
        std::shared_ptr<audio::Stream> s = track(c).current();
        return Value::I(s ? static_cast<jint>(static_cast<std::uint32_t>(s->played())) : 0);
    });
    // The controls, each on the stream and in the play state the game reads back.
    auto control = [](jint state, void (audio::Stream::*act)()) {
        return [state, act](Call& c) {
            Track& t = track(c);
            std::shared_ptr<audio::Stream> s = t.current();
            if (!s) jvm::throw_new("java/lang/IllegalStateException", "the AudioTrack was released");
            ((*s).*act)();
            if (state) t.play_state = state;
            return Value();
        };
    };
    c.method("play", "()V", control(kPlaying, &audio::Stream::play));
    c.method("pause", "()V", control(kPaused, &audio::Stream::pause));
    c.method("stop", "()V", control(kStopped, &audio::Stream::stop));
    c.method("flush", "()V", control(0, &audio::Stream::flush));
    c.method("release", "()V", [](Call& c) {
        Track& t = track(c);
        t.release();
        t.play_state = kStopped;
        return Value();
    });
    c.method("setStereoVolume", "(FF)I", [](Call& c) {
        if (std::shared_ptr<audio::Stream> s = track(c).current()) s->volume(c.f(0), c.f(1));
        return Value::I(0);
    });
    c.method("setVolume", "(F)I", [](Call& c) {
        if (std::shared_ptr<audio::Stream> s = track(c).current()) s->volume(c.f(0), c.f(0));
        return Value::I(0);
    });
    // write(byte[], offset, bytes), write(short[], offset, shorts), and write(ByteBuffer, bytes, mode) from the buffer's
    // position, which moves on past what was taken; a range outside the array is the error a phone returns. The ranges
    // add up in 64 bits, as media.cpp's readSampleData does: two ints may add up past an int's range and wrap to a sum
    // that passes.
    c.method("write", "([BII)I", [](Call& c) {
        auto* a = c.as<jvm::Array>(0);
        if (!a || c.i(1) < 0 || c.i(2) < 0 || static_cast<jlong>(c.i(1)) + c.i(2) > a->length) return Value::I(kErrorBadValue);
        return write(c, a->data<jbyte>() + c.i(1), c.i(2));
    });
    c.method("write", "([SII)I", [](Call& c) {
        auto* a = c.as<jvm::Array>(0);
        if (!a || c.i(1) < 0 || c.i(2) < 0 || static_cast<jlong>(c.i(1)) + c.i(2) > a->length) return Value::I(kErrorBadValue);
        // As bytes, no more than an int holds (an even count, whole shorts): a billion shorts and more would wrap.
        const jint bytes = static_cast<jint>(std::min<jlong>(static_cast<jlong>(c.i(2)) * 2, std::numeric_limits<jint>::max() - 1));
        Value written = write(c, a->data<jshort>() + c.i(1), bytes);
        return written.i() > 0 ? Value::I(written.i() / 2) : written;
    });
    c.method("write", "(Ljava/nio/ByteBuffer;II)I", [](Call& c) {
        auto* b = c.as<jvm::Buffer>(0);
        // From the position to the limit at most, and within what the buffer holds: this VM's Buffer.position and limit
        // take any int, where a phone's would have thrown, so a position below 0 or a limit past the capacity is refused
        // here rather than read.
        if (!b || c.i(1) < 0 || b->position < 0 || static_cast<jlong>(b->position) + c.i(1) > std::min<jlong>(b->limit, b->capacity))
            return Value::I(kErrorBadValue);
        Value written = write(c, static_cast<std::uint8_t*>(b->address) + b->position, c.i(1));
        if (written.i() > 0) b->position += written.i();
        return written;
    });
}

// org.fmod.FMODAudioDevice, its thread and the stream it plays to.
class Fmod : public Object {
public:
    using Object::Object;
    std::atomic<bool> running{false};
    std::thread thread;
    std::mutex lock;
};

void run(Ref<Fmod> self) {
    name_thread("FMOD output");
    jvm::Env& e = jvm::attach();
    Object* o = self.get();
    auto info = [&](jint what) { return e.call(o, "fmodGetInfo", "(I)I", {Value::I(what)}).i(); };
    const jint rate = info(kSampleRate), block = info(kBlockLength), blocks = info(kBlockCount);
    // FMODAudioDevice's buffer: the smallest AudioTrack's a tenth larger, in whole frames, or FMOD's blocks if more.
    const jint smallest = rate / 50 * 4;
    const jint bytes = std::max(static_cast<jint>(std::lround(smallest * 1.1)) & ~3, block * blocks * 4);
    jvm::log("player: FMOD output: %d Hz, %d blocks of %d frames, a buffer of %d frames", rate, blocks, block, bytes / 4);
    // One block of 16-bit stereo, as FMODAudioDevice allocates it.
    Ref<jvm::Buffer> buffer = jvm::new_buffer(static_cast<std::size_t>(block) * 2 * 2);
    audio::Mixer& mixer = audio::Mixer::get();
    std::shared_ptr<audio::Stream> stream;
    while (self->running.load()) {
        if (info(kRunning) != 1) {
            // FMOD's mixer is not running: no stream until it is, as FMODAudioDevice lets its AudioTrack go then.
            if (stream) mixer.close(stream);
            stream.reset();
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            continue;
        }
        if (!stream) {
            stream = mixer.open(rate, 2, audio::Encoding::S16, static_cast<std::size_t>(bytes / 4), "FMOD");
            stream->play();
        }
        e.call(o, "fmodProcess", "(Ljava/nio/ByteBuffer;)I", {Value(buffer)});
        if (e.pending) {
            jvm::log("player: fmodProcess threw %s", e.pending->cls()->name.c_str());
            e.pending = {};
        }
        // Waits while the stream's buffer is full: the sound card's pace.
        stream->write(buffer->address, static_cast<std::size_t>(block));
    }
    if (stream) mixer.close(stream);
    jvm::detach();
}

void stop(Fmod& f) {
    f.running = false;
    if (f.thread.joinable()) f.thread.join();
}

}  // namespace

void define_audio() {
    define_track();
    Class& c = jvm::define("org/fmod/FMODAudioDevice");
    c.interfaces.push_back(jvm::find_class("java/lang/Runnable"));
    c.make = [](Class& k) -> Object* { return new Fmod(&k); };
    c.method("<init>", "()V", [](Call&) { return Value(); });
    c.method("start", "()V", [](Call& c) {
        Fmod& f = c.self_as<Fmod>();
        std::lock_guard<std::mutex> l(f.lock);
        stop(f);
        f.running = true;
        f.thread = std::thread(run, Ref<Fmod>(&f));
        return Value();
    });
    auto halt = [](Call& c) {
        Fmod& f = c.self_as<Fmod>();
        std::lock_guard<std::mutex> l(f.lock);
        stop(f);
        return Value();
    };
    c.method("stop", "()V", halt);
    c.method("close", "()V", halt);
    c.method("isRunning", "()Z", [](Call& c) { return Value::Z(c.self_as<Fmod>().running.load()); });
    // No microphone.
    c.method("startAudioRecord", "(III)I", [](Call&) { return Value::I(-1); });
    c.method("stopAudioRecord", "()V", [](Call&) { return Value(); });
}

void report_audio() {
    if (audio::Mixer* m = audio::Mixer::started()) m->report();
}

}  // namespace player
