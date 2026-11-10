// The computer's broadcast's encoder (live_desktop.cpp says what runs where): Windows' own H.264 and AAC encoders, from
// Media Foundation, on the encoder thread, which takes the render thread's pictures (live_capture.cpp) and the mixer's
// sound (mix_tap), and cuts the MPEG-TS segments the upload thread sends (live_ts.cpp, src/live_net.cpp).
#include "live_state.h"

#include "live_sps.h"
#include "live_ts.h"

#include <windows.h>
#include <codecapi.h>
#include <mfapi.h>
#include <mferror.h>
#include <mfidl.h>
#include <mftransform.h>
#include <strmif.h>

// ICodecAPI's interface id, which this toolchain's headers leave without one for __uuidof.
__CRT_UUID_DECL(ICodecAPI, 0x901db4c7, 0x31ce, 0x41a2, 0x85, 0xdc, 0x8f, 0xa0, 0xbf, 0x41, 0xb8, 0xda)

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>

namespace arm32::desktop_live {

namespace {

// The stream's sound: 48 kHz stereo AAC at this bitrate (bytes a second, as Media Foundation's AAC encoder takes it),
// in chunks of an AAC frame's 1024 samples.
constexpr int kAudioRate = 48000;
constexpr int kAudioChunk = 1024;
constexpr UINT32 kAudioBytesPerSecond = 16000;
// How much of the mix is kept in hand: the mixer writes a period at a time, and an empty round is a click.
constexpr Nanos kAudioDelay = 150000000;
// The ring of the mixer's sound: two seconds of the highest rate a device mixes at (192 kHz, 16-bit stereo).
constexpr std::size_t kRingBytes = 1u << 21;

// ---- the sound: the mixer's ring, one writer (the mixer's thread) and one reader (the encoder thread)

struct Ring {
    std::unique_ptr<std::uint8_t[]> bytes{new std::uint8_t[kRingBytes]};
    std::atomic<std::size_t> head{0}, tail{0};  // running counts of bytes in and out
    std::atomic<int> rate{0};                   // the mixer's rate (0: no sound yet)
    std::atomic<bool> restart{false};           // the reader skips what is in the ring
    double phase = 0;                           // the encoder's place between two samples
    bool buffering = true;                      // silent until the mix has built up kAudioDelay again
    std::atomic<int> short_rounds{0}, last_have{0};
} g_ring;
// Open while an encoder takes the sound: the mixer's thread does nothing here otherwise.
std::atomic<bool> g_audio_gate{false};

}  // namespace

// The mixer's period, as 16-bit stereo, into the ring (Mixer::run, on its thread). Never blocks: without room it is left
// out of the broadcast only.
void mix_tap(const float* stereo, std::size_t frames, int rate) {
    if (!g_audio_gate.load(std::memory_order_acquire) || frames == 0) return;
    if (g_ring.rate.load(std::memory_order_relaxed) != rate) {
        // A new rate (the output opened another device): what is in the ring is at the old one.
        g_ring.rate.store(rate, std::memory_order_relaxed);
        g_ring.restart.store(true, std::memory_order_release);
    }
    const std::size_t size = frames * 4;
    const std::size_t head = g_ring.head.load(std::memory_order_relaxed);
    const std::size_t tail = g_ring.tail.load(std::memory_order_acquire);
    if (size > kRingBytes - (head - tail)) return;
    std::uint8_t* ring = g_ring.bytes.get();
    for (std::size_t i = 0; i < frames * 2; ++i) {
        const auto v = static_cast<std::int16_t>(std::lround(std::clamp(stereo[i], -1.0f, 1.0f) * 32767.0f));
        const std::size_t at = (head + i * 2) % kRingBytes;
        ring[at] = static_cast<std::uint8_t>(v & 0xff);
        ring[(at + 1) % kRingBytes] = static_cast<std::uint8_t>((v >> 8) & 0xff);
    }
    g_ring.head.store(head + size, std::memory_order_release);
}

// ---- Media Foundation: from mfplat.dll when Windows has it (the N editions have none until their Media Feature Pack
// is installed): without it there is no broadcast, and the game plays all the same.

struct Functions {
    decltype(&MFStartup) startup = nullptr;
    decltype(&MFTEnumEx) enumerate = nullptr;
    decltype(&MFCreateMediaType) media_type = nullptr;
    decltype(&MFCreateSample) sample = nullptr;
    decltype(&MFCreateMemoryBuffer) memory_buffer = nullptr;
};

const Functions* mf() {
    static const Functions* loaded = []() -> const Functions* {
        HMODULE dll = LoadLibraryW(L"mfplat.dll");
        if (!dll) return nullptr;
        static Functions f;
        auto get = [dll](const char* name) { return reinterpret_cast<void*>(GetProcAddress(dll, name)); };
        f.startup = reinterpret_cast<decltype(f.startup)>(get("MFStartup"));
        f.enumerate = reinterpret_cast<decltype(f.enumerate)>(get("MFTEnumEx"));
        f.media_type = reinterpret_cast<decltype(f.media_type)>(get("MFCreateMediaType"));
        f.sample = reinterpret_cast<decltype(f.sample)>(get("MFCreateSample"));
        f.memory_buffer = reinterpret_cast<decltype(f.memory_buffer)>(get("MFCreateMemoryBuffer"));
        if (!f.startup || !f.enumerate || !f.media_type || !f.sample || !f.memory_buffer) return nullptr;
        return &f;
    }();
    return loaded;
}

namespace {

template <class T>
void release(T*& p) {
    if (p) p->Release();
    p = nullptr;
}

// The first synchronous encoder of `category` from `in` to `out`: Windows' own (H.264, AAC), which runs on the CPU and
// answers each input at once, so this thread can feed it and take what comes out in turn.
IMFTransform* find_encoder(const GUID& category, const GUID& major, const GUID& in, const GUID& out) {
    MFT_REGISTER_TYPE_INFO input{major, in}, output{major, out};
    IMFActivate** found = nullptr;
    UINT32 count = 0;
    if (FAILED(mf()->enumerate(category, MFT_ENUM_FLAG_SYNCMFT | MFT_ENUM_FLAG_LOCALMFT | MFT_ENUM_FLAG_SORTANDFILTER, &input, &output, &found, &count)) ||
        !count)
        return nullptr;
    IMFTransform* t = nullptr;
    found[0]->ActivateObject(IID_PPV_ARGS(&t));
    for (UINT32 i = 0; i < count; ++i) found[i]->Release();
    CoTaskMemFree(found);
    return t;
}

// A sample of `size` bytes copied from `data`, at `time` for `duration` (100-nanosecond units).
IMFSample* make_sample(const void* data, std::size_t size, LONGLONG time, LONGLONG duration) {
    IMFMediaBuffer* buffer = nullptr;
    IMFSample* sample = nullptr;
    if (FAILED(mf()->memory_buffer(static_cast<DWORD>(size), &buffer))) return nullptr;
    BYTE* to = nullptr;
    if (SUCCEEDED(buffer->Lock(&to, nullptr, nullptr))) {
        std::memcpy(to, data, size);
        buffer->Unlock();
        buffer->SetCurrentLength(static_cast<DWORD>(size));
    }
    if (SUCCEEDED(mf()->sample(&sample))) {
        sample->AddBuffer(buffer);
        sample->SetSampleTime(time);
        sample->SetSampleDuration(duration);
    }
    release(buffer);
    return sample;
}

// What one ProcessOutput gave: its bytes, its time, and whether a player can start on it.
struct Output {
    std::vector<std::uint8_t> bytes;
    LONGLONG time = 0;
    bool key = false;
};

// Everything the transform has ready, into `out`; false when it broke. A transform that does not make its own samples
// gets one of the size it asks for.
bool drain(IMFTransform* t, std::vector<Output>& out) {
    for (;;) {
        MFT_OUTPUT_STREAM_INFO info{};
        if (FAILED(t->GetOutputStreamInfo(0, &info))) return false;
        const bool provides = info.dwFlags & (MFT_OUTPUT_STREAM_PROVIDES_SAMPLES | MFT_OUTPUT_STREAM_CAN_PROVIDE_SAMPLES);
        MFT_OUTPUT_DATA_BUFFER data{};
        IMFSample* own = nullptr;
        if (!provides) {
            IMFMediaBuffer* buffer = nullptr;
            if (FAILED(mf()->memory_buffer(std::max<DWORD>(info.cbSize, 1 << 16), &buffer))) return false;
            // No sample from Windows (out of memory): this round's output waits, as for no buffer.
            if (FAILED(mf()->sample(&own)) || !own) {
                release(buffer);
                return false;
            }
            own->AddBuffer(buffer);
            release(buffer);
            data.pSample = own;
        }
        DWORD status = 0;
        const HRESULT hr = t->ProcessOutput(0, 1, &data, &status);
        if (data.pEvents) data.pEvents->Release();
        if (hr == MF_E_TRANSFORM_NEED_MORE_INPUT) {
            release(own);
            return true;
        }
        if (hr == MF_E_TRANSFORM_STREAM_CHANGE) {
            // The encoder's output type changed (its stream headers came): take its new one and go on.
            release(own);
            IMFMediaType* type = nullptr;
            if (FAILED(t->GetOutputAvailableType(0, 0, &type)) || FAILED(t->SetOutputType(0, type, 0))) {
                release(type);
                return false;
            }
            release(type);
            continue;
        }
        if (FAILED(hr)) {
            release(own);
            if (data.pSample && data.pSample != own) data.pSample->Release();
            return false;
        }
        IMFSample* sample = data.pSample;
        IMFMediaBuffer* buffer = nullptr;
        if (sample && SUCCEEDED(sample->ConvertToContiguousBuffer(&buffer))) {
            BYTE* bytes = nullptr;
            DWORD length = 0;
            if (SUCCEEDED(buffer->Lock(&bytes, nullptr, &length))) {
                Output o;
                o.bytes.assign(bytes, bytes + length);
                sample->GetSampleTime(&o.time);
                UINT32 clean = 0;
                o.key = SUCCEEDED(sample->GetUINT32(MFSampleExtension_CleanPoint, &clean)) && clean;
                out.push_back(std::move(o));
                buffer->Unlock();
            }
            release(buffer);
        }
        if (sample && sample != own) sample->Release();
        release(own);
    }
}

// A UINT32 value of the encoder's settings (ICodecAPI); a setting it does not have stays its own.
void set_codec(ICodecAPI* api, const GUID& what, ULONG value) {
    VARIANT v;
    VariantInit(&v);
    v.vt = VT_UI4;
    v.ulVal = value;
    api->SetValue(&what, &v);
}

// The NAL unit type of the first unit after a start code in an Annex B stream, or -1.
int first_nal_type(const std::vector<std::uint8_t>& b) {
    for (std::size_t i = 0; i + 3 < b.size(); ++i) {
        if (b[i] == 0 && b[i + 1] == 0 && b[i + 2] == 1) return b[i + 3] & 0x1f;
    }
    return -1;
}

// ---- the encoder thread

class Encoder {
public:
    ~Encoder() { close_all(); }

    // Windows' H.264 encoder for pictures of this size, and its AAC encoder (without which the stream is silent).
    bool open(int width, int height) {
        width_ = width;
        height_ = height;
        fps_ = step_fps(step());
        bitrate_ = step_bitrate(step());
        video_ = find_encoder(MFT_CATEGORY_VIDEO_ENCODER, MFMediaType_Video, MFVideoFormat_NV12, MFVideoFormat_H264);
        if (!video_) return fail("Windows has no H.264 encoder here");
        // The output's type first, as the encoder asks: H.264, Main profile, this size, rate and bitrate.
        IMFMediaType* out = nullptr;
        mf()->media_type(&out);
        out->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video);
        out->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_H264);
        out->SetUINT32(MF_MT_AVG_BITRATE, static_cast<UINT32>(bitrate_));
        MFSetAttributeSize(out, MF_MT_FRAME_SIZE, static_cast<UINT32>(width), static_cast<UINT32>(height));
        MFSetAttributeRatio(out, MF_MT_FRAME_RATE, static_cast<UINT32>(fps_), 1);
        MFSetAttributeRatio(out, MF_MT_PIXEL_ASPECT_RATIO, 1, 1);
        out->SetUINT32(MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive);
        out->SetUINT32(MF_MT_MPEG2_PROFILE, eAVEncH264VProfile_Main);
        // The colours as the conversion makes them (BT.709, limited range), in the stream for players to read: all four,
        // as the stream's colour description has them together.
        out->SetUINT32(MF_MT_VIDEO_PRIMARIES, MFVideoPrimaries_BT709);
        out->SetUINT32(MF_MT_TRANSFER_FUNCTION, MFVideoTransFunc_709);
        out->SetUINT32(MF_MT_YUV_MATRIX, MFVideoTransferMatrix_BT709);
        out->SetUINT32(MF_MT_VIDEO_NOMINAL_RANGE, MFNominalRange_16_235);
        HRESULT hr = video_->SetOutputType(0, out, 0);
        release(out);
        if (FAILED(hr)) return fail("the H.264 encoder takes no such stream");
        IMFMediaType* in = nullptr;
        mf()->media_type(&in);
        in->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video);
        in->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_NV12);
        MFSetAttributeSize(in, MF_MT_FRAME_SIZE, static_cast<UINT32>(width), static_cast<UINT32>(height));
        MFSetAttributeRatio(in, MF_MT_FRAME_RATE, static_cast<UINT32>(fps_), 1);
        MFSetAttributeRatio(in, MF_MT_PIXEL_ASPECT_RATIO, 1, 1);
        in->SetUINT32(MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive);
        in->SetUINT32(MF_MT_YUV_MATRIX, MFVideoTransferMatrix_BT709);
        in->SetUINT32(MF_MT_VIDEO_NOMINAL_RANGE, MFNominalRange_16_235);
        hr = video_->SetInputType(0, in, 0);
        release(in);
        if (FAILED(hr)) return fail("the H.264 encoder takes no NV12 pictures of this size");
        // A steady bitrate, no frames held back for reordering, a key frame every segment, and its faster end of
        // quality against speed: a stream watched live, encoded beside a game.
        if (SUCCEEDED(video_->QueryInterface(IID_PPV_ARGS(&codec_)))) {
            set_codec(codec_, CODECAPI_AVEncCommonRateControlMode, eAVEncCommonRateControlMode_CBR);
            set_codec(codec_, CODECAPI_AVEncMPVGOPSize, static_cast<ULONG>(fps_ * g_segment.load()));
            set_codec(codec_, CODECAPI_AVEncCommonQualityVsSpeed, 33);
            // The colour description again, as the encoder's own settings, for an encoder that reads it from there.
            set_codec(codec_, CODECAPI_AVEncVideoOutputColorPrimaries, eAVEncVideoColorPrimaries_BT709);
            set_codec(codec_, CODECAPI_AVEncVideoOutputColorTransferFunction, eAVEncVideoColorTransferFunction_22_709);
            set_codec(codec_, CODECAPI_AVEncVideoOutputColorTransferMatrix, eAVEncVideoColorTransferMatrix_BT709);
            VARIANT low;
            VariantInit(&low);
            low.vt = VT_BOOL;
            low.boolVal = VARIANT_TRUE;
            codec_->SetValue(&CODECAPI_AVLowLatencyMode, &low);
        }
        video_->ProcessMessage(MFT_MESSAGE_NOTIFY_BEGIN_STREAMING, 0);
        video_->ProcessMessage(MFT_MESSAGE_NOTIFY_START_OF_STREAM, 0);
        open_audio();
        return true;
    }

    // One picture into the encoder, and what comes out into the stream.
    bool picture(const Frame& f) {
        if (!first_pts_) first_pts_ = f.pts;
        const LONGLONG time = (f.pts - first_pts_) / 100;
        // Time to ask for the next key frame: the segment is long enough.
        if (segment_open_ && !key_asked_ && f.pts - segment_start_ >= g_segment.load() * kSecond - kSecond / 10 && codec_) {
            set_codec(codec_, CODECAPI_AVEncVideoForceKeyFrame, 1);
            key_asked_ = true;
        }
        IMFSample* sample = make_sample(f.nv12.data(), f.nv12.size(), time, 10000000LL / fps_);
        if (!sample) return false;
        const HRESULT hr = video_->ProcessInput(0, sample, 0);
        release(sample);
        if (FAILED(hr) && hr != MF_E_NOTACCEPTING) return fail("the H.264 encoder broke");
        std::vector<Output> out;
        if (!drain(video_, out)) return fail("the H.264 encoder broke");
        for (Output& o : out) on_video(o);
        return true;
    }

    // The sound by the clock: every chunk's time, whatever the mix has by then, a little behind it. So the sound stays
    // with the picture, and a mixer that stops leaves silence and not a gap.
    void sound(Nanos now) {
        if (!audio_ || !first_pts_) return;
        const Nanos chunk = kAudioChunk * kSecond / kAudioRate;
        if (audio_next_ == 0 || now - audio_next_ > kSecond / 2) audio_next_ = std::max(now, first_pts_);
        while (now >= audio_next_) {
            std::int16_t pcm[kAudioChunk * 2] = {};
            take_sound(pcm);
            const LONGLONG time = (audio_next_ - kAudioDelay - first_pts_) / 100;
            IMFSample* sample = make_sample(pcm, sizeof pcm, time, 10000000LL * kAudioChunk / kAudioRate);
            audio_next_ += chunk;
            if (!sample) continue;
            const HRESULT hr = audio_->ProcessInput(0, sample, 0);
            release(sample);
            if (FAILED(hr) && hr != MF_E_NOTACCEPTING) {
                log("player: live: the AAC encoder broke, the stream goes on silent");
                close_audio();
                return;
            }
            std::vector<Output> out;
            if (!drain(audio_, out)) {
                close_audio();
                return;
            }
            for (Output& o : out) on_audio(o);
        }
    }

    // The partial segment goes too, unless it is hardly anything.
    void finish() {
        if (segment_open_ && last_pts_ - segment_start_ > kSecond / 2) cut(last_pts_);
    }

    int width() const { return width_; }
    int height() const { return height_; }
    int fps() const { return fps_; }

    // The bitrate can change on the running encoder; a new frame rate or height needs a new one (the caller's).
    void apply_bitrate() {
        const int wanted = step_bitrate(step());
        if (wanted == bitrate_ || !codec_) return;
        set_codec(codec_, CODECAPI_AVEncCommonMeanBitRate, static_cast<ULONG>(wanted));
        bitrate_ = wanted;
    }

private:
    bool fail(const char* what) {
        log("player: live: %s", what);
        return false;
    }

    void open_audio() {
        audio_ = find_encoder(MFT_CATEGORY_AUDIO_ENCODER, MFMediaType_Audio, MFAudioFormat_PCM, MFAudioFormat_AAC);
        if (!audio_) {
            log("player: live: no AAC encoder, the stream stays silent");
            return;
        }
        IMFMediaType* in = nullptr;
        mf()->media_type(&in);
        in->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Audio);
        in->SetGUID(MF_MT_SUBTYPE, MFAudioFormat_PCM);
        in->SetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, 16);
        in->SetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND, kAudioRate);
        in->SetUINT32(MF_MT_AUDIO_NUM_CHANNELS, 2);
        IMFMediaType* out = nullptr;
        mf()->media_type(&out);
        out->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Audio);
        out->SetGUID(MF_MT_SUBTYPE, MFAudioFormat_AAC);
        out->SetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, 16);
        out->SetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND, kAudioRate);
        out->SetUINT32(MF_MT_AUDIO_NUM_CHANNELS, 2);
        out->SetUINT32(MF_MT_AUDIO_AVG_BYTES_PER_SECOND, kAudioBytesPerSecond);
        // Raw AAC frames: the ADTS header goes on here, as the transport stream wants it.
        out->SetUINT32(MF_MT_AAC_PAYLOAD_TYPE, 0);
        // The input's type first, then the output's: Windows' AAC encoder takes them in that order.
        const bool set = SUCCEEDED(audio_->SetInputType(0, in, 0)) && SUCCEEDED(audio_->SetOutputType(0, out, 0));
        release(in);
        release(out);
        if (!set) {
            log("player: live: the AAC encoder takes no 48 kHz stereo, the stream stays silent");
            close_audio();
            return;
        }
        audio_->ProcessMessage(MFT_MESSAGE_NOTIFY_BEGIN_STREAMING, 0);
        audio_->ProcessMessage(MFT_MESSAGE_NOTIFY_START_OF_STREAM, 0);
        // From here on the mixer's sound comes in; what is left in the ring is from another time.
        g_ring.restart.store(true, std::memory_order_release);
        g_audio_gate.store(true, std::memory_order_release);
    }

    void close_audio() {
        g_audio_gate.store(false, std::memory_order_release);
        release(audio_);
    }

    // The next chunk of the mix at the stream's rate, into `out`: silence while the mix builds up after a gap. The mix's
    // clock (the sound device's) is not the system's: a tiny change of speed, half a percent at most and not audible,
    // keeps what is in hand at the target, so it neither runs dry nor needs a jump.
    void take_sound(std::int16_t* out) {
        Ring& r = g_ring;
        const int rate = r.rate.load(std::memory_order_relaxed);
        if (rate <= 0) return;
        const std::size_t head = r.head.load(std::memory_order_acquire);
        std::size_t tail = r.tail.load(std::memory_order_relaxed);
        if (r.restart.exchange(false, std::memory_order_acq_rel)) {
            tail = head;
            r.phase = 0;
            r.buffering = true;
        }
        std::size_t have = (head - tail) / 4;
        const auto target = static_cast<std::size_t>(static_cast<Nanos>(rate) * kAudioDelay / kSecond);
        // Far ahead (this thread was held up): back to the target at once, so the sound keeps up with the picture.
        if (have > target + static_cast<std::size_t>(rate) * 2 / 5) {
            tail = head - target * 4;
            have = target;
        }
        r.last_have.store(static_cast<int>(have), std::memory_order_relaxed);
        if (r.buffering && have < target) {
            r.tail.store(tail, std::memory_order_release);
            return;
        }
        r.buffering = false;
        const double off = (static_cast<double>(have) - static_cast<double>(target)) / rate;
        const double step = static_cast<double>(rate) / kAudioRate * (1.0 + std::clamp(off * 0.02, -0.005, 0.005));
        const auto needed = static_cast<std::size_t>(r.phase + kAudioChunk * step) + 2;
        if (have < needed) {
            r.short_rounds.fetch_add(1, std::memory_order_relaxed);
            r.buffering = true;
            r.tail.store(tail, std::memory_order_release);
            return;
        }
        const std::uint8_t* ring = r.bytes.get();
        auto sample = [&](std::size_t frame, int channel) {
            // Bytes one at a time: a sample can straddle the end of the ring.
            const std::size_t at = tail + frame * 4 + static_cast<std::size_t>(channel) * 2;
            const std::uint8_t lo = ring[at % kRingBytes], hi = ring[(at + 1) % kRingBytes];
            return static_cast<double>(static_cast<std::int16_t>(static_cast<std::uint16_t>(lo | (hi << 8))));
        };
        double place = r.phase;
        for (int i = 0; i < kAudioChunk; ++i, place += step) {
            const auto whole = static_cast<std::size_t>(place);
            const double fraction = place - static_cast<double>(whole);
            for (int channel = 0; channel < 2; ++channel) {
                const double a = sample(whole, channel), b = sample(whole + 1, channel);
                out[i * 2 + channel] = static_cast<std::int16_t>(std::clamp(a + (b - a) * fraction, -32768.0, 32767.0));
            }
        }
        const auto used = static_cast<std::size_t>(place);
        r.phase = place - static_cast<double>(used);
        r.tail.store(tail + used * 4, std::memory_order_release);
    }

    void on_video(Output& o) {
        const Nanos pts = first_pts_ + o.time * 100;
        // The stream's colours in its sequence headers, where a key frame brings them.
        if (o.key) o.bytes = with_colours(o.bytes);
        // A stream can only start on a key frame.
        if (!segment_open_ && !o.key) return;
        if (!segment_open_) {
            start_segment(pts);
        } else if (o.key && pts - segment_start_ >= g_segment.load() * kSecond - kSecond / 10) {
            cut(pts);
            start_segment(pts);
        }
        last_pts_ = pts;
        // The stream's headers before each key frame, where the encoder leaves them out after the first: a player that
        // joins at any segment needs them. Kept from the key frame that had them.
        if (o.key && first_nal_type(o.bytes) == 7) {
            // SPS, then PPS, then the frame: everything before the first IDR slice.
            for (std::size_t i = 0; i + 3 < o.bytes.size(); ++i) {
                if (o.bytes[i] == 0 && o.bytes[i + 1] == 0 && o.bytes[i + 2] == 1 && (o.bytes[i + 3] & 0x1f) == 5) {
                    const std::size_t start = i > 0 && o.bytes[i - 1] == 0 ? i - 1 : i;
                    headers_.assign(o.bytes.begin(), o.bytes.begin() + static_cast<std::ptrdiff_t>(start));
                    break;
                }
            }
        }
        // An access unit delimiter, the headers on a key frame without them, the frame.
        static const std::uint8_t delimiter[] = {0, 0, 0, 1, 9, 0xF0};
        unit_.assign(delimiter, delimiter + sizeof delimiter);
        if (o.key && first_nal_type(o.bytes) != 7) unit_.insert(unit_.end(), headers_.begin(), headers_.end());
        unit_.insert(unit_.end(), o.bytes.begin(), o.bytes.end());
        ts_.video(unit_.data(), unit_.size(), to_90khz(pts), o.key);
    }

    void on_audio(Output& o) {
        const Nanos pts = first_pts_ + o.time * 100;
        // Sound from before the stream's first picture has no place in it.
        if (!segment_open_ || o.bytes.empty() || o.time < 0) return;
        unit_.resize(7 + o.bytes.size());
        if (!adts_header(unit_.data(), kAudioRate, 2, o.bytes.size())) return;
        std::memcpy(unit_.data() + 7, o.bytes.data(), o.bytes.size());
        ts_.audio(unit_.data(), unit_.size(), to_90khz(pts));
        g_audio_frames.fetch_add(1, std::memory_order_relaxed);
    }

    void start_segment(Nanos pts) {
        ts_.begin_segment();
        segment_start_ = pts;
        segment_open_ = true;
        key_asked_ = false;
    }

    void cut(Nanos end) {
        live::Segment s;
        s.bytes = std::move(ts_.bytes());
        ts_.bytes().clear();
        s.seq = seq_++;
        s.duration_ms = static_cast<int>((end - segment_start_) / 1000000);
        g_link.queue_segment(std::move(s));
    }

    // A second in, so the clock reference, which runs behind the frames, never goes below zero.
    std::uint64_t to_90khz(Nanos pts) const { return static_cast<std::uint64_t>((pts - first_pts_) * 9 / 100000 + 90000); }

    void close_all() {
        close_audio();
        release(codec_);
        release(video_);
    }

    IMFTransform* video_ = nullptr;
    IMFTransform* audio_ = nullptr;
    ICodecAPI* codec_ = nullptr;
    int width_ = 0, height_ = 0, fps_ = 30, bitrate_ = 0;
    TsWriter ts_;
    std::vector<std::uint8_t> headers_, unit_;
    bool segment_open_ = false, key_asked_ = false;
    Nanos first_pts_ = 0, segment_start_ = 0, last_pts_ = 0, audio_next_ = 0;
    int seq_ = 0;
};

void log_stats_if_due(Nanos* next) {
    const Nanos now = now_ns();
    if (now < *next) return;
    *next = now + (g_stats ? 10 : 60) * kSecond;
    const std::uint64_t n = g_captures.exchange(0);
    const std::uint64_t total = g_capture_ns.exchange(0);
    const std::uint64_t handed = g_handed.exchange(0);
    const std::uint64_t hand_total = g_hand_ns.exchange(0);
    log("player: live: step %d, %llu pictures, %llu skipped, render thread %llu us each to take (worst %llu) and %llu us to hand over "
        "(worst %llu), %llu starts (the dearest %llu us), %llu segments up, %llu lost, %llu AAC frames", step(),
        static_cast<unsigned long long>(n), static_cast<unsigned long long>(g_skipped.exchange(0)),
        static_cast<unsigned long long>(n ? total / n / 1000 : 0), static_cast<unsigned long long>(g_capture_max_ns.exchange(0) / 1000),
        static_cast<unsigned long long>(handed ? hand_total / handed / 1000 : 0), static_cast<unsigned long long>(g_hand_max_ns.exchange(0) / 1000),
        static_cast<unsigned long long>(g_starts.exchange(0)), static_cast<unsigned long long>(g_start_max_ns.exchange(0) / 1000),
        static_cast<unsigned long long>(g_link.uploaded.exchange(0)), static_cast<unsigned long long>(g_link.dropped.exchange(0)),
        static_cast<unsigned long long>(g_audio_frames.exchange(0)));
    if (g_stats) log("player: live: sound: %d short rounds, %d frames in hand", g_ring.short_rounds.exchange(0), g_ring.last_have.load());
    if (g_stats && n) {
        std::uint64_t us[kPhases];
        for (int i = 0; i < kPhases; ++i) us[i] = g_phase_ns[i].exchange(0) / n / 1000;
        log("player: live: taking a picture, us each: looks %llu, save %llu, copy %llu, convert %llu, read %llu, fence %llu, restore %llu",
            static_cast<unsigned long long>(us[0]), static_cast<unsigned long long>(us[1]), static_cast<unsigned long long>(us[2]),
            static_cast<unsigned long long>(us[3]), static_cast<unsigned long long>(us[4]), static_cast<unsigned long long>(us[5]),
            static_cast<unsigned long long>(us[6]));
    }
}

}  // namespace

void encoder_main() {
    background_thread("live-encode");
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    mf()->startup(MF_VERSION, MFSTARTUP_LITE);
    Nanos next_stats = now_ns() + 60 * kSecond;
    std::unique_ptr<Encoder> encoder;
    // How hard the encoder works, over five seconds at a time: its time on pictures against the time it had, and the
    // pictures it took. Twice behind, a step down (g_encoder_step); a minute with time to spare, a step back up.
    Nanos window_start = now_ns(), busy = 0;
    std::uint64_t pictures = 0;
    int heavy = 0, light = 0;
    for (;;) {
        Frame f;
        bool have = false;
        {
            std::unique_lock<std::mutex> l(g_frame_lock);
            if (encoder) {
                // A frame, or a look at the sound every 10 ms: its chunks are due by the clock.
                g_frame_wake.wait_for(l, std::chrono::milliseconds(10), [] { return !g_frames.empty(); });
            } else {
                // No stream: nothing to do until a picture comes, which the render thread takes only while a broadcast
                // is wanted, and hands over with a wake (collect). No timer meanwhile, so the processor is left alone for
                // as long as broadcasts are off.
                g_frame_wake.wait(l, [] { return !g_frames.empty(); });
            }
            if (!g_frames.empty()) {
                f = std::move(g_frames.front());
                g_frames.pop_front();
                have = true;
            }
        }
        const bool want = g_want.load(std::memory_order_relaxed);
        // Off, or a picture of another size or rate (a step, a resized window): this encoder's stream ends here.
        if (encoder && (!want || (have && (f.width != encoder->width() || f.height != encoder->height())) || encoder->fps() != step_fps(step()))) {
            encoder->finish();
            encoder.reset();
            log("player: live: stopped");
        }
        if (!want) {
            // Pictures taken before it went off belong to no stream: the next one starts with its own.
            std::lock_guard<std::mutex> l(g_frame_lock);
            g_frames.clear();
            continue;
        }
        if (have && !encoder && !g_gave_up.load()) {
            encoder = std::make_unique<Encoder>();
            if (encoder->open(f.width, f.height)) {
                g_failures.store(0);
                log("player: live: on, %dx%d at %d fps, %d kbit/s", f.width, f.height, step_fps(step()), step_bitrate(step()) / 1000);
            } else {
                encoder.reset();
                if (g_failures.fetch_add(1) + 1 >= 3) {
                    log("player: live: this PC cannot encode the stream, giving up");
                    g_gave_up.store(true);
                }
            }
        }
        if (!encoder) continue;
        bool sent = true;
        if (have) {
            const Nanos began = now_ns();
            sent = encoder->picture(f);
            // Checks stand in for a slower PC (PLAYER_LIVE_ENCODE_DELAY: milliseconds more for each picture).
            static const long slower = [] {
                const char* v = std::getenv("PLAYER_LIVE_ENCODE_DELAY");
                return v ? std::strtol(v, nullptr, 10) : 0L;
            }();
            if (slower > 0) sleep_ns(slower * 1000000);
            busy += now_ns() - began;
            ++pictures;
        }
        // The picture is in the encoder's own sample now: its buffer goes back for the render thread's next one.
        if (have) {
            std::lock_guard<std::mutex> l(g_frame_lock);
            recycle(std::move(f.nv12));
        }
        if (!sent) {
            encoder.reset();
            continue;
        }
        encoder->sound(now_ns());
        encoder->apply_bitrate();
        log_stats_if_due(&next_stats);
        const Nanos now = now_ns();
        if (now - window_start >= 5 * kSecond) {
            const double load = static_cast<double>(busy) / static_cast<double>(now - window_start);
            const std::uint64_t behind = g_encoder_behind.exchange(0);
            if (pictures > 0 && (load > 0.9 || behind * 20 > pictures)) {
                // Its time near all it had, or one picture in twenty left out for it: twice so, a step down.
                light = 0;
                if (++heavy >= 2 && g_encoder_step.load() < kLastStep) {
                    heavy = 0;
                    g_encoder_step.fetch_add(1);
                    log("player: live: the encoder does not keep up (%.0f %% busy, %llu pictures left out): a step down", load * 100,
                        static_cast<unsigned long long>(behind));
                }
            } else if (pictures > 0 && load < 0.4) {
                heavy = 0;
                if (++light >= 12 && g_encoder_step.load() > 0) {
                    light = 0;
                    g_encoder_step.fetch_sub(1);
                    log("player: live: the encoder has time to spare (%.0f %% busy): a step back up", load * 100);
                }
            } else {
                heavy = 0;
                light = 0;
            }
            window_start = now;
            busy = 0;
            pictures = 0;
        }
    }
}

}  // namespace arm32::desktop_live
