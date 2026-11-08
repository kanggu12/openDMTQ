// The decoders on Windows: Media Foundation's H.264 and AAC decoders, the system's own (found by type, so that a
// graphics card's own decoder is taken where Windows offers it). H.264 goes in as Android's extractor gives it (NAL
// units after start codes) and comes out as NV12, its visible part turned into RGBA; AAC goes in raw, with its
// AudioSpecificConfig in the input type, and comes out as 16-bit PCM.
#include "decoder.h"

#include "jvm.h"

#include <windows.h>
#include <mfapi.h>
#include <mferror.h>
#include <mfidl.h>
#include <mftransform.h>

#include <deque>
#include <vector>

namespace player::media {

namespace {

// Media Foundation's functions, from mfplat.dll when Windows has it: the N and KN editions have none until their Media
// Feature Pack is installed, and the player then starts all the same and plays the videos blank (media.cpp).
struct Functions {
    decltype(&MFStartup) startup = nullptr;
    decltype(&MFTEnumEx) enumerate = nullptr;
    decltype(&MFCreateMediaType) media_type = nullptr;
    decltype(&MFCreateSample) sample = nullptr;
    decltype(&MFCreateMemoryBuffer) memory_buffer = nullptr;
};

// The functions, or null when this Windows has no Media Foundation.
const Functions* mf() {
    static const Functions* loaded = []() -> const Functions* {
        HMODULE dll = LoadLibraryW(L"mfplat.dll");
        if (!dll) return nullptr;
        static Functions f;
        // Through void* first: a FARPROC is a function pointer of another type.
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

// COM and Media Foundation on the calling thread, once per thread: the codec decodes on a thread of its own.
void com_ready() {
    thread_local bool ready = [] {
        CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        if (const Functions* m = mf()) m->startup(MF_VERSION, MFSTARTUP_LITE);
        return true;
    }();
    (void)ready;
}

template <class T>
void release(T*& p) {
    if (p) p->Release();
    p = nullptr;
}

// The first synchronous decoder of `category` that takes `subtype`.
IMFTransform* find_decoder(const GUID& category, const GUID& major, const GUID& subtype) {
    MFT_REGISTER_TYPE_INFO in{major, subtype};
    IMFActivate** found = nullptr;
    UINT32 count = 0;
    if (FAILED(mf()->enumerate(category, MFT_ENUM_FLAG_SYNCMFT | MFT_ENUM_FLAG_LOCALMFT | MFT_ENUM_FLAG_SORTANDFILTER, &in, nullptr, &found, &count)) || !count)
        return nullptr;
    IMFTransform* t = nullptr;
    found[0]->ActivateObject(IID_PPV_ARGS(&t));
    for (UINT32 i = 0; i < count; ++i) found[i]->Release();
    CoTaskMemFree(found);
    return t;
}

// The output type of `t` with `subtype` among those it offers, set; false when it offers none.
bool set_output(IMFTransform* t, const GUID& subtype, UINT32 bits = 0) {
    for (DWORD i = 0;; ++i) {
        IMFMediaType* type = nullptr;
        if (FAILED(t->GetOutputAvailableType(0, i, &type))) return false;
        GUID got{};
        type->GetGUID(MF_MT_SUBTYPE, &got);
        UINT32 b = 0;
        if (bits) type->GetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, &b);
        bool ok = got == subtype && (!bits || b == bits) && SUCCEEDED(t->SetOutputType(0, type, 0));
        type->Release();
        if (ok) return true;
    }
}

// A decoder of Media Foundation's, which turns its samples into our frames.
class Mf : public Decoder {
public:
    explicit Mf(IMFTransform* t) : t_(t) {
        t_->ProcessMessage(MFT_MESSAGE_NOTIFY_BEGIN_STREAMING, 0);
        t_->ProcessMessage(MFT_MESSAGE_NOTIFY_START_OF_STREAM, 0);
    }
    ~Mf() override { release(t_); }
    bool send(const std::uint8_t* data, std::size_t size) override {
        com_ready();
        IMFSample* sample = nullptr;
        IMFMediaBuffer* buf = nullptr;
        mf()->sample(&sample);
        mf()->memory_buffer(static_cast<DWORD>(size), &buf);
        BYTE* p = nullptr;
        buf->Lock(&p, nullptr, nullptr);
        std::memcpy(p, data, size);
        buf->Unlock();
        buf->SetCurrentLength(static_cast<DWORD>(size));
        sample->AddBuffer(buf);
        bool ok = false;
        for (int tries = 0; tries < 64; ++tries) {
            HRESULT hr = t_->ProcessInput(0, sample, 0);
            if (SUCCEEDED(hr)) {
                ok = true;
                break;
            }
            // Its outputs waiting to come out first: taken into ours, and the input goes in after them.
            if (hr != MF_E_NOTACCEPTING || !take()) break;
        }
        buf->Release();
        sample->Release();
        return ok;
    }
    bool drain() override {
        com_ready();
        return SUCCEEDED(t_->ProcessMessage(MFT_MESSAGE_COMMAND_DRAIN, 0));
    }
    bool receive(Frame& out) override {
        com_ready();
        if (ready_.empty() && !take()) return false;
        out = std::move(ready_.front());
        ready_.pop_front();
        return true;
    }
    void flush() override {
        com_ready();
        t_->ProcessMessage(MFT_MESSAGE_COMMAND_FLUSH, 0);
        ready_.clear();
    }

protected:
    // A new output format (a stream change): set again, and its facts read.
    virtual bool reformat() = 0;
    // The output buffer as our frame.
    virtual void convert(IMFMediaBuffer* buf, Frame& out) = 0;
    IMFTransform* t_;

private:
    // One output from the decoder into ready_; false when it has none now.
    bool take() {
        for (;;) {
            MFT_OUTPUT_STREAM_INFO info{};
            t_->GetOutputStreamInfo(0, &info);
            MFT_OUTPUT_DATA_BUFFER out{};
            IMFSample* sample = nullptr;
            IMFMediaBuffer* buf = nullptr;
            // The decoder's own samples, or ours of the size it asks for.
            if (!(info.dwFlags & (MFT_OUTPUT_STREAM_PROVIDES_SAMPLES | MFT_OUTPUT_STREAM_CAN_PROVIDE_SAMPLES))) {
                mf()->sample(&sample);
                mf()->memory_buffer(info.cbSize ? info.cbSize : (1u << 22), &buf);
                sample->AddBuffer(buf);
                out.pSample = sample;
            }
            DWORD status = 0;
            HRESULT hr = t_->ProcessOutput(0, 1, &out, &status);
            if (out.pEvents) out.pEvents->Release();
            if (hr == MF_E_TRANSFORM_STREAM_CHANGE) {
                release(buf);
                release(sample);
                if (!reformat()) return false;
                continue;
            }
            if (FAILED(hr)) {
                release(buf);
                release(sample);
                return false;
            }
            IMFMediaBuffer* whole = nullptr;
            out.pSample->ConvertToContiguousBuffer(&whole);
            Frame f;
            if (whole) convert(whole, f);
            release(whole);
            if (out.pSample != sample) out.pSample->Release();
            release(buf);
            release(sample);
            ready_.push_back(std::move(f));
            return true;
        }
    }
    std::deque<Frame> ready_;
};

class H264 : public Mf {
public:
    using Mf::Mf;
    bool reformat() override {
        if (!set_output(t_, MFVideoFormat_NV12)) return false;
        IMFMediaType* type = nullptr;
        if (FAILED(t_->GetOutputCurrentType(0, &type))) return false;
        UINT32 w = 0, h = 0;
        MFGetAttributeSize(type, MF_MT_FRAME_SIZE, &w, &h);
        coded_w_ = static_cast<int>(w);
        coded_h_ = static_cast<int>(h);
        // The rows of each plane, as the decoder lays them out (a multiple of 16 rows, a stride of its own).
        UINT32 stride = 0;
        stride_ = SUCCEEDED(type->GetUINT32(MF_MT_DEFAULT_STRIDE, &stride)) ? static_cast<int>(stride) : coded_w_;
        // The visible part: the decoder rounds the size up to whole macroblocks and says what is shown.
        MFVideoArea area{};
        UINT32 got = 0;
        if (SUCCEEDED(type->GetBlob(MF_MT_MINIMUM_DISPLAY_APERTURE, reinterpret_cast<UINT8*>(&area), sizeof area, &got)) && got == sizeof area &&
            area.Area.cx > 0 && area.Area.cy > 0) {
            width_ = area.Area.cx;
            height_ = area.Area.cy;
        } else {
            width_ = coded_w_;
            height_ = coded_h_;
        }
        type->Release();
        return true;
    }
    void convert(IMFMediaBuffer* buf, Frame& out) override {
        BYTE* p = nullptr;
        DWORD len = 0;
        if (FAILED(buf->Lock(&p, nullptr, &len))) return;
        out.width = width_;
        out.height = height_;
        out.rgba.assign(static_cast<std::size_t>(width_) * static_cast<std::size_t>(height_) * 4, 0);
        // NV12: the luma plane, then the interleaved chroma one below its coded rows.
        std::size_t uv_at = static_cast<std::size_t>(stride_) * static_cast<std::size_t>(coded_h_);
        if (len >= uv_at + static_cast<std::size_t>(stride_) * static_cast<std::size_t>(height_ / 2))
            yuv420_to_rgba(p, stride_, p + uv_at, p + uv_at + 1, stride_, 2, width_, height_, false, out.rgba.data());
        buf->Unlock();
    }

private:
    int coded_w_ = 0, coded_h_ = 0, stride_ = 0, width_ = 0, height_ = 0;
};

class Aac : public Mf {
public:
    Aac(IMFTransform* t, int rate, int channels) : Mf(t), rate_(rate), channels_(channels) {}
    bool reformat() override {
        if (!set_output(t_, MFAudioFormat_PCM, 16)) return false;
        // The rate and channels as the decoder gives them out: HE-AAC's rate is twice its core's, and its parametric
        // stereo makes two channels of one, where the stream's config gives the core's.
        IMFMediaType* type = nullptr;
        if (SUCCEEDED(t_->GetOutputCurrentType(0, &type))) {
            UINT32 v = 0;
            if (SUCCEEDED(type->GetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND, &v)) && v) rate_ = static_cast<int>(v);
            if (SUCCEEDED(type->GetUINT32(MF_MT_AUDIO_NUM_CHANNELS, &v)) && v) channels_ = static_cast<int>(v);
            type->Release();
        }
        return true;
    }
    void convert(IMFMediaBuffer* buf, Frame& out) override {
        BYTE* p = nullptr;
        DWORD len = 0;
        if (FAILED(buf->Lock(&p, nullptr, &len))) return;
        out.rate = rate_;
        out.channels = channels_;
        out.pcm.resize(len / 2);
        std::memcpy(out.pcm.data(), p, out.pcm.size() * 2);
        buf->Unlock();
    }

private:
    int rate_, channels_;
};

}  // namespace

std::unique_ptr<Decoder> open_h264(std::string& error) {
    if (!mf()) {
        error = "Windows has no Media Foundation (an N or KN edition without its Media Feature Pack)";
        return nullptr;
    }
    com_ready();
    IMFTransform* t = find_decoder(MFT_CATEGORY_VIDEO_DECODER, MFMediaType_Video, MFVideoFormat_H264);
    if (!t) {
        error = "no H.264 decoder in Windows";
        return nullptr;
    }
    IMFMediaType* in = nullptr;
    mf()->media_type(&in);
    in->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video);
    in->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_H264);
    HRESULT hr = t->SetInputType(0, in, 0);
    in->Release();
    auto d = std::make_unique<H264>(t);
    if (FAILED(hr) || !d->reformat()) {
        error = "Windows' H.264 decoder takes no stream of this kind";
        return nullptr;
    }
    return d;
}

std::unique_ptr<Decoder> open_aac(const std::vector<std::uint8_t>& config, std::string& error) {
    if (!mf()) {
        error = "Windows has no Media Foundation (an N or KN edition without its Media Feature Pack)";
        return nullptr;
    }
    com_ready();
    if (config.size() < 2) {
        error = "no AudioSpecificConfig";
        return nullptr;
    }
    // The rate and channels from the AudioSpecificConfig: object type (5 bits), rate index (4), channels (4).
    static const int kRates[] = {96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350};
    int rate_index = ((config[0] & 7) << 1) | (config[1] >> 7);
    int channels = (config[1] >> 3) & 15;
    if (rate_index > 12 || channels < 1 || channels > 7) {
        error = "an AAC stream of a kind this does not read";
        return nullptr;
    }
    IMFTransform* t = find_decoder(MFT_CATEGORY_AUDIO_DECODER, MFMediaType_Audio, MFAudioFormat_AAC);
    if (!t) {
        error = "no AAC decoder in Windows";
        return nullptr;
    }
    IMFMediaType* in = nullptr;
    mf()->media_type(&in);
    in->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Audio);
    in->SetGUID(MF_MT_SUBTYPE, MFAudioFormat_AAC);
    in->SetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND, static_cast<UINT32>(kRates[rate_index]));
    in->SetUINT32(MF_MT_AUDIO_NUM_CHANNELS, static_cast<UINT32>(channels));
    // Raw AAC frames, described by the HEAACWAVEINFO's tail (payload type 0, profile "not given") and the config.
    in->SetUINT32(MF_MT_AAC_PAYLOAD_TYPE, 0);
    std::vector<std::uint8_t> user(12, 0);
    user[2] = 0xFE;
    user.insert(user.end(), config.begin(), config.end());
    in->SetBlob(MF_MT_USER_DATA, user.data(), static_cast<UINT32>(user.size()));
    HRESULT hr = t->SetInputType(0, in, 0);
    in->Release();
    auto d = std::make_unique<Aac>(t, kRates[rate_index], channels);
    if (FAILED(hr) || !d->reformat()) {
        error = "Windows' AAC decoder takes no stream of this kind";
        return nullptr;
    }
    return d;
}

}  // namespace player::media
