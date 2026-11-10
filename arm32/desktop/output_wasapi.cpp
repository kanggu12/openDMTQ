// The sound output on Windows: WASAPI, shared with the computer's other sound or, as the PC's settings choose
// (Options), the device alone.
//
// Shared: at the rate the device mixes at, so that Windows resamples nothing, as stereo floats with Windows' own
// conversion to the device's channels. The buffer is 20 ms (normal) or 50 ms (safe); a low one is the shortest period
// Windows' audio engine offers for the device (Windows 10's low-latency shared mode, in the engine's own format), else
// 10 ms. Alone (exclusive mode): the device at that rate, in a format it takes (32-bit floats, then 32-, 24- and 16-bit
// integers; two channels, then its own), with its own period: its shortest for a low buffer, its default for a normal
// one, twice that for a safe one. When it cannot have the device alone (another program has it, Windows' sound settings
// do not allow it, no format suits), the output shares it instead and says so in the log.
//
// Event-driven: a write waits for the device to have room, which paces the mixer; the mixer's thread is a "Pro Audio"
// thread for Windows' scheduler (MMCSS). The device is the one the settings name by its id, or Windows' default output.
// A device can go while the game plays (headphones unplugged, another program taking it alone) and Windows' default
// output can change: the output then closes, keeps the mixer's time as if it played, and opens the device again, at once
// on a change and every second after a loss; a named device that is gone gives way to the default output until it is
// back. Its writes never fail: the mixer keeps it for the whole run.
#include "mixer.h"

#include "jvm.h"

#include <windows.h>
#include <audioclient.h>
#include <avrt.h>
#include <ksmedia.h>
#include <mmdeviceapi.h>
#include <propidl.h>
#include <propsys.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace player::audio {

namespace {

// The shared buffers: normal and safe, in milliseconds, and a low one where the engine has no shorter period.
constexpr double kSharedMs[] = {10, 20, 50};
// How long after a loss the device is asked for again.
constexpr auto kRetry = std::chrono::seconds(1);
// How long a full buffer may stay as it is before the device counts as gone: shared, its padding the same for that long
// (write_shared); alone, that long without its event (write_alone's ten waits of 200 ms).
constexpr auto kStalled = std::chrono::seconds(2);
// A device's friendly name ("Speakers (Realtek(R) Audio)"): PKEY_Device_FriendlyName, spelled out here so that no
// translation unit has to define every property key of its header.
const PROPERTYKEY kFriendlyName = {{0xa45c254e, 0xdf1c, 0x4efd, {0x80, 0x20, 0x67, 0xd1, 0x46, 0xa8, 0x50, 0xe0}}, 14};

// COM's handles, released with the output.
template <class T>
void release(T*& p) {
    if (p) p->Release();
    p = nullptr;
}

// UTF-16 and UTF-8, for the devices' ids and names.
std::wstring wide(const std::string& s) {
    const int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()), nullptr, 0);
    std::wstring out(static_cast<std::size_t>(n > 0 ? n : 0), L'\0');
    if (n > 0) MultiByteToWideChar(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()), out.data(), n);
    return out;
}
std::string narrow(const wchar_t* s) {
    if (!s) return "";
    const int n = WideCharToMultiByte(CP_UTF8, 0, s, -1, nullptr, 0, nullptr, nullptr);
    std::string out(static_cast<std::size_t>(n > 1 ? n - 1 : 0), '\0');
    if (n > 1) WideCharToMultiByte(CP_UTF8, 0, s, -1, out.data(), n, nullptr, nullptr);
    return out;
}

// What the output writes to the device: its channels, the two that left and right go to (the same one on a device of one
// channel, which gets their middle), and its samples.
struct Format {
    int channels = 2;
    int left = 0, right = 1;
    int bytes = 4;          // a sample's container: 4 (floats or 32-bit integers), 3 (packed 24-bit) or 2
    bool floats = true;
    int valid_bits = 32;    // an integer sample's bits that count (24 in a container of 32)
    // The mixer's own: stereo floats, copied as they are.
    bool plain() const { return floats && channels == 2 && left == 0 && right == 1; }
};

// The device format a WAVEFORMATEX describes, for writing to it; false for one this output cannot write.
bool format_of(const WAVEFORMATEX* w, Format& f) {
    if (!w || w->nChannels < 1) return false;
    bool floats = w->wFormatTag == WAVE_FORMAT_IEEE_FLOAT;
    int valid = w->wBitsPerSample;
    DWORD mask = 0;
    if (w->wFormatTag == WAVE_FORMAT_EXTENSIBLE && w->cbSize >= sizeof(WAVEFORMATEXTENSIBLE) - sizeof(WAVEFORMATEX)) {
        const auto* x = reinterpret_cast<const WAVEFORMATEXTENSIBLE*>(w);
        floats = IsEqualGUID(x->SubFormat, KSDATAFORMAT_SUBTYPE_IEEE_FLOAT);
        if (!floats && !IsEqualGUID(x->SubFormat, KSDATAFORMAT_SUBTYPE_PCM)) return false;
        if (x->Samples.wValidBitsPerSample) valid = x->Samples.wValidBitsPerSample;
        mask = x->dwChannelMask;
    } else if (!floats && w->wFormatTag != WAVE_FORMAT_PCM) {
        return false;
    }
    const int bytes = w->wBitsPerSample / 8;
    if (floats ? bytes != 4 : (bytes != 2 && bytes != 3 && bytes != 4)) return false;
    f.channels = w->nChannels;
    f.bytes = bytes;
    f.floats = floats;
    f.valid_bits = std::clamp(valid, 8, bytes * 8);
    // The channels come in the order of their bits in the mask: front left is the first bit, front right the second.
    f.left = 0;
    f.right = f.channels > 1 ? 1 : 0;
    if (mask && (mask & (SPEAKER_FRONT_LEFT | SPEAKER_FRONT_RIGHT)) != (SPEAKER_FRONT_LEFT | SPEAKER_FRONT_RIGHT)) {
        // No front pair (a centre speaker alone): both sides go to the first channel.
        f.right = 0;
    }
    return true;
}

// `frames` stereo floats from the mixer into the device's format at `out`; the device's other channels stay silent.
void put_frames(const Format& f, const float* in, std::size_t frames, BYTE* out) {
    if (f.plain()) {
        std::memcpy(out, in, frames * kChannels * sizeof(float));
        return;
    }
    const std::size_t frame = static_cast<std::size_t>(f.channels) * static_cast<std::size_t>(f.bytes);
    std::memset(out, 0, frames * frame);
    // An integer sample's full scale, and how far its bits sit up in the container.
    const double scale = std::ldexp(1.0, f.valid_bits - 1) - 1;
    const int shift = f.bytes * 8 - f.valid_bits;
    auto put = [&](BYTE* p, float v) {
        v = std::clamp(v, -1.0f, 1.0f);
        if (f.floats) {
            std::memcpy(p, &v, 4);
            return;
        }
        // Rounded to the nearest step, then moved up to the container's top bits (24 bits in 32: by 8).
        const auto n = static_cast<std::int64_t>(std::llround(static_cast<double>(v) * scale)) * (std::int64_t{1} << shift);
        for (int b = 0; b < f.bytes; ++b) p[b] = static_cast<BYTE>((n >> (8 * b)) & 0xff);
    };
    for (std::size_t k = 0; k < frames; ++k) {
        BYTE* at = out + k * frame;
        const float l = in[k * kChannels], r = in[k * kChannels + 1];
        if (f.left == f.right) {
            put(at + static_cast<std::size_t>(f.left) * static_cast<std::size_t>(f.bytes), (l + r) * 0.5f);
        } else {
            put(at + static_cast<std::size_t>(f.left) * static_cast<std::size_t>(f.bytes), l);
            put(at + static_cast<std::size_t>(f.right) * static_cast<std::size_t>(f.bytes), r);
        }
    }
}

// A WAVEFORMATEXTENSIBLE for these samples, channels and rate.
WAVEFORMATEXTENSIBLE extensible(int rate, int channels, DWORD mask, int bytes, int valid_bits, bool floats) {
    WAVEFORMATEXTENSIBLE fmt{};
    fmt.Format.wFormatTag = WAVE_FORMAT_EXTENSIBLE;
    fmt.Format.nChannels = static_cast<WORD>(channels);
    fmt.Format.nSamplesPerSec = static_cast<DWORD>(rate);
    fmt.Format.wBitsPerSample = static_cast<WORD>(bytes * 8);
    fmt.Format.nBlockAlign = static_cast<WORD>(channels * bytes);
    fmt.Format.nAvgBytesPerSec = fmt.Format.nSamplesPerSec * fmt.Format.nBlockAlign;
    fmt.Format.cbSize = sizeof(WAVEFORMATEXTENSIBLE) - sizeof(WAVEFORMATEX);
    fmt.Samples.wValidBitsPerSample = static_cast<WORD>(valid_bits);
    fmt.dwChannelMask = mask;
    fmt.SubFormat = floats ? KSDATAFORMAT_SUBTYPE_IEEE_FLOAT : KSDATAFORMAT_SUBTYPE_PCM;
    return fmt;
}

// What Windows says of its devices, read by the next write: the default output changed, or the named device came or
// went. Shared, so that a call Windows makes while the output is being closed still has it.
struct News {
    std::atomic<bool> changed{false};
    // The named device's id ("" for none), and whether the output plays on the default output now.
    std::wstring named;
    std::atomic<bool> on_default{true};
};

class Watch final : public IMMNotificationClient {
public:
    explicit Watch(std::shared_ptr<News> news) : news_(std::move(news)) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** out) override {
        if (iid == __uuidof(IUnknown) || iid == __uuidof(IMMNotificationClient)) {
            *out = static_cast<IMMNotificationClient*>(this);
            AddRef();
            return S_OK;
        }
        *out = nullptr;
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs_; }
    ULONG STDMETHODCALLTYPE Release() override {
        ULONG n = --refs_;
        if (n == 0) delete this;
        return n;
    }
    // The console's output is the one games play through; it matters while the output is on it.
    HRESULT STDMETHODCALLTYPE OnDefaultDeviceChanged(EDataFlow flow, ERole role, LPCWSTR) override {
        if (flow == eRender && role == eConsole && news_->on_default.load()) news_->changed.store(true);
        return S_OK;
    }
    // The named device plugged in again, or taken away.
    HRESULT STDMETHODCALLTYPE OnDeviceAdded(LPCWSTR id) override { return named(id); }
    HRESULT STDMETHODCALLTYPE OnDeviceRemoved(LPCWSTR id) override { return named(id); }
    HRESULT STDMETHODCALLTYPE OnDeviceStateChanged(LPCWSTR id, DWORD) override { return named(id); }
    HRESULT STDMETHODCALLTYPE OnPropertyValueChanged(LPCWSTR, const PROPERTYKEY) override { return S_OK; }

private:
    HRESULT named(LPCWSTR id) {
        if (id && !news_->named.empty() && news_->named == id) news_->changed.store(true);
        return S_OK;
    }
    std::atomic<ULONG> refs_{1};
    std::shared_ptr<News> news_;
};

class Wasapi : public Output {
public:
    ~Wasapi() override {
        close();
        if (devices_ && watch_) devices_->UnregisterEndpointNotificationCallback(watch_);
        release(watch_);
        release(devices_);
    }
    // Opens the device; false with a reason in the log when it cannot.
    bool open() {
        CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, __uuidof(IMMDeviceEnumerator), reinterpret_cast<void**>(&devices_))))
            return fail("no audio device enumerator");
        news_->named = wide(options().device);
        // The device's own mix rate, read once: the mixer runs at it for the whole run, and at the period this start has.
        if (!start(true)) return false;
        period_ = period_frames_;
        // Told when the default output changes or the named device comes and goes, to move.
        watch_ = new Watch(news_);
        devices_->RegisterEndpointNotificationCallback(watch_);
        return true;
    }
    const char* name() const override { return "WASAPI"; }
    int rate() const override { return rate_; }
    double buffer_ms() const override { return buffer_ms_; }
    std::size_t period() const override { return period_; }
    bool write(const float* data, std::size_t frames) override {
        if (!thread_ready_) {
            // The mixer's thread: in COM's shared apartment, and scheduled as audio by Windows.
            CoInitializeEx(nullptr, COINIT_MULTITHREADED);
            DWORD task = 0;
            AvSetMmThreadCharacteristicsW(L"Pro Audio", &task);
            thread_ready_ = true;
        }
        if (news_->changed.exchange(false)) {
            // The default output changed, or the named device came or went: to the one to play on now.
            jvm::log("player: WASAPI: the devices changed: opening the output again");
            close();
            retry_at_ = {};
        }
        if (!client_ && Clock::now() >= retry_at_) {
            if (start(false)) jvm::log("player: WASAPI: sound out again");
            else retry_at_ = Clock::now() + kRetry;
        }
        // No device for now: the mixer's time goes on as if it played.
        if (!client_) return keep_time(frames);
        return exclusive_ ? write_alone(data, frames) : write_shared(data, frames);
    }

private:
    using Clock = std::chrono::steady_clock;

    bool fail(const char* why) {
        jvm::log("player: WASAPI: %s", why);
        return false;
    }
    // Shared: as much as the device has room for, waiting for its event while it has none. A device whose padding stays
    // as it is for kStalled while the buffer is full has stopped taking frames, as alone (write_alone): lost. A change of
    // the devices ends the wait too, for the next write to move to the output to play on now.
    bool write_shared(const float* data, std::size_t frames) {
        std::size_t done = 0;
        // The padding last read, and since when it has been that: the device's progress.
        UINT32 last_padding = 0;
        bool read_once = false;
        Clock::time_point since = Clock::now();
        while (done < frames) {
            // The default output changed, or the named device came or went: the rest of these frames go by in time, and
            // write (which looks at the change first) opens the output again.
            if (news_->changed.load()) return keep_time(frames - done);
            UINT32 padding = 0;
            HRESULT hr = client_->GetCurrentPadding(&padding);
            if (FAILED(hr)) return lost(hr, frames - done);
            // Frames taken by the device or put in by this write move the padding: the time without progress starts again.
            if (!read_once || padding != last_padding) {
                last_padding = padding;
                read_once = true;
                since = Clock::now();
            }
            UINT32 room = frames_ > padding ? frames_ - padding : 0;
            if (room == 0) {
                // Full: the device's event says when it has taken a period.
                if (!started_) begin();
                // Full and still for kStalled: no event is coming, and the wait would never end.
                if (Clock::now() - since >= kStalled) return lost(E_FAIL, frames - done);
                WaitForSingleObject(event_, 100);
                continue;
            }
            UINT32 n = static_cast<UINT32>(std::min<std::size_t>(room, frames - done));
            BYTE* out = nullptr;
            hr = render_->GetBuffer(n, &out);
            if (FAILED(hr)) return lost(hr, frames - done);
            put_frames(format_, data + done * kChannels, n, out);
            render_->ReleaseBuffer(n, 0);
            done += n;
        }
        // Playing once the first buffer is in, so that it starts with sound and not with an underrun.
        if (!started_) begin();
        return true;
    }
    // Alone: the device plays whole buffers of its own size, one after each event that says it took the last. The mixer's
    // periods are that size, except after the output opened another device: what is left over waits for the next write.
    bool write_alone(const float* data, std::size_t frames) {
        pending_.insert(pending_.end(), data, data + frames * kChannels);
        while (pending_.size() >= static_cast<std::size_t>(frames_) * kChannels) {
            if (started_) {
                // Two seconds without an event: the device stopped, which its padding then says.
                int waits = 0;
                while (WaitForSingleObject(event_, 200) != WAIT_OBJECT_0) {
                    UINT32 padding = 0;
                    const HRESULT hr = client_->GetCurrentPadding(&padding);
                    if (FAILED(hr) || ++waits >= 10) return lost(FAILED(hr) ? hr : E_FAIL, pending_.size() / kChannels);
                }
            }
            BYTE* out = nullptr;
            const HRESULT hr = render_->GetBuffer(frames_, &out);
            if (FAILED(hr)) return lost(hr, pending_.size() / kChannels);
            put_frames(format_, pending_.data(), frames_, out);
            render_->ReleaseBuffer(frames_, 0);
            pending_.erase(pending_.begin(), pending_.begin() + static_cast<std::ptrdiff_t>(frames_) * kChannels);
            // Started once the first buffer is in, as the device alone wants it.
            if (!started_) begin();
        }
        return true;
    }
    // The device to play on: the named one while it is there, else Windows' default output.
    bool find_device() {
        if (!news_->named.empty()) {
            DWORD state = 0;
            if (SUCCEEDED(devices_->GetDevice(news_->named.c_str(), &device_)) && SUCCEEDED(device_->GetState(&state)) && state == DEVICE_STATE_ACTIVE) {
                news_->on_default.store(false);
                return true;
            }
            release(device_);
            if (!named_missing_logged_) jvm::log("player: WASAPI: the chosen device is not there: the default output until it is");
            named_missing_logged_ = true;
        }
        news_->on_default.store(true);
        return SUCCEEDED(devices_->GetDefaultAudioEndpoint(eRender, eConsole, &device_));
    }
    // A client of the device, made anew (an Initialize that fails leaves it unusable).
    bool activate() {
        release(client_);
        return SUCCEEDED(device_->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, reinterpret_cast<void**>(&client_)));
    }
    // The device opened for the mixer's rate, as the settings ask and as far as it lets: alone, in its low-latency shared
    // mode, or shared with Windows converting to the device's own format (AUTOCONVERTPCM) when it mixes at another rate.
    bool start(bool first) {
        if (!find_device()) return fail("no output device");
        if (!activate()) {
            close();
            return fail("cannot open the device");
        }
        if (first) {
            WAVEFORMATEX* mix = nullptr;
            if (FAILED(client_->GetMixFormat(&mix))) {
                close();
                return fail("no mix format");
            }
            rate_ = static_cast<int>(mix->nSamplesPerSec);
            CoTaskMemFree(mix);
        }
        const int buffer = std::clamp(options().buffer, 0, 2);
        exclusive_ = false;
        if (options().exclusive && start_alone(buffer)) return ready();
        if (buffer == 0 && start_low()) return ready();
        // Shared: stereo 32-bit floats at the mixer's rate; Windows maps two channels to the device's own.
        if (!activate()) {
            close();
            return fail("cannot open the device");
        }
        WAVEFORMATEXTENSIBLE fmt = extensible(rate_, kChannels, SPEAKER_FRONT_LEFT | SPEAKER_FRONT_RIGHT, 4, 32, true);
        const DWORD flags = AUDCLNT_STREAMFLAGS_EVENTCALLBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY;
        // 100-nanosecond units.
        const auto length = static_cast<REFERENCE_TIME>(kSharedMs[buffer] * 10000);
        if (FAILED(client_->Initialize(AUDCLNT_SHAREMODE_SHARED, flags, length, 0, &fmt.Format, nullptr))) {
            close();
            return fail("the device refuses stereo floats");
        }
        format_ = Format{};
        period_frames_ = 0;
        mode_ = "shared";
        return ready();
    }
    // The device alone, in the first format it takes at the mixer's rate, with the period the buffer setting asks for.
    bool start_alone(int buffer) {
        WAVEFORMATEX* mix = nullptr;
        int own_channels = kChannels;
        DWORD own_mask = SPEAKER_FRONT_LEFT | SPEAKER_FRONT_RIGHT;
        if (SUCCEEDED(client_->GetMixFormat(&mix))) {
            own_channels = mix->nChannels;
            if (mix->wFormatTag == WAVE_FORMAT_EXTENSIBLE) own_mask = reinterpret_cast<WAVEFORMATEXTENSIBLE*>(mix)->dwChannelMask;
            CoTaskMemFree(mix);
        }
        struct Samples {
            int bytes, valid;
            bool floats;
        };
        static constexpr Samples kSamples[] = {{4, 32, true}, {4, 32, false}, {4, 24, false}, {3, 24, false}, {2, 16, false}};
        WAVEFORMATEXTENSIBLE fmt{};
        bool found = false;
        // Two channels first, then the device's own (some take only theirs alone).
        for (int pass = 0; pass < 2 && !found; ++pass) {
            const int channels = pass == 0 ? kChannels : own_channels;
            const DWORD mask = pass == 0 ? SPEAKER_FRONT_LEFT | SPEAKER_FRONT_RIGHT : own_mask;
            if (pass == 1 && channels == kChannels) break;
            for (const Samples& s : kSamples) {
                fmt = extensible(rate_, channels, mask, s.bytes, s.valid, s.floats);
                if (client_->IsFormatSupported(AUDCLNT_SHAREMODE_EXCLUSIVE, &fmt.Format, nullptr) == S_OK) {
                    found = true;
                    break;
                }
            }
        }
        if (!found || !format_of(&fmt.Format, format_)) {
            jvm::log("player: WASAPI: the device takes no format at %d Hz alone: shared instead", rate_);
            return false;
        }
        REFERENCE_TIME standard = 0, shortest = 0;
        client_->GetDevicePeriod(&standard, &shortest);
        REFERENCE_TIME length = buffer == 0 ? shortest : buffer == 1 ? standard : 2 * standard;
        if (length <= 0) length = 100000;
        HRESULT hr = client_->Initialize(AUDCLNT_SHAREMODE_EXCLUSIVE, AUDCLNT_STREAMFLAGS_EVENTCALLBACK, length, length, &fmt.Format, nullptr);
        if (hr == AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED) {
            // The device's buffer comes in steps of its own: the frames it offered, as a length, on a new client.
            UINT32 aligned = 0;
            client_->GetBufferSize(&aligned);
            length = static_cast<REFERENCE_TIME>(std::llround(1e7 * aligned / rate_));
            hr = activate() ? client_->Initialize(AUDCLNT_SHAREMODE_EXCLUSIVE, AUDCLNT_STREAMFLAGS_EVENTCALLBACK, length, length, &fmt.Format, nullptr)
                            : E_FAIL;
        }
        if (FAILED(hr)) {
            const char* why = hr == AUDCLNT_E_DEVICE_IN_USE ? "another program has it alone"
                              : hr == AUDCLNT_E_EXCLUSIVE_MODE_NOT_ALLOWED ? "Windows' sound settings do not let programs have it alone"
                                                                           : "it refused";
            jvm::log("player: WASAPI: the device cannot be had alone (%s, %#lx): shared instead", why, static_cast<unsigned long>(hr));
            // A failed Initialize leaves the client unusable: shared starts on a new one.
            activate();
            return false;
        }
        exclusive_ = true;
        UINT32 frames = 0;
        client_->GetBufferSize(&frames);
        period_frames_ = frames;
        mode_ = "alone";
        jvm::log("player: WASAPI: the device alone, %d channels of %d-bit %s, %u frames a buffer", format_.channels, format_.valid_bits,
                 format_.floats ? "floats" : "integers", frames);
        return true;
    }
    // The low-latency shared mode: the engine's shortest period for the device, in the engine's own format, which must be
    // at the mixer's rate (a later device may mix at another: then the plain shared mode).
    bool start_low() {
        IAudioClient3* low = nullptr;
        if (FAILED(client_->QueryInterface(__uuidof(IAudioClient3), reinterpret_cast<void**>(&low)))) return false;
        WAVEFORMATEX* mix = nullptr;
        bool ok = false;
        UINT32 standard = 0, step = 0, shortest = 0, longest = 0;
        if (SUCCEEDED(low->GetMixFormat(&mix)) && static_cast<int>(mix->nSamplesPerSec) == rate_ && format_of(mix, format_) &&
            SUCCEEDED(low->GetSharedModeEnginePeriod(mix, &standard, &step, &shortest, &longest)) && shortest > 0 && shortest < standard) {
            ok = SUCCEEDED(low->InitializeSharedAudioStream(AUDCLNT_STREAMFLAGS_EVENTCALLBACK, shortest, mix, nullptr));
        }
        if (mix) CoTaskMemFree(mix);
        release(low);
        if (!ok) {
            // No shorter period than the standard one (most drivers' case), or no such mode: the plain shared one, with
            // the low buffer, on a new client.
            jvm::log("player: WASAPI: no low-latency mode for this device: a short shared buffer");
            return false;
        }
        period_frames_ = shortest;
        mode_ = "shared, low latency";
        jvm::log("player: WASAPI: low-latency shared mode, %u frames a period (the standard one %u)", shortest, standard);
        return true;
    }
    // The client opened: its event, its buffer and its render client.
    bool ready() {
        event_ = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        client_->SetEventHandle(event_);
        client_->GetBufferSize(&frames_);
        if (FAILED(client_->GetService(__uuidof(IAudioRenderClient), reinterpret_cast<void**>(&render_)))) {
            close();
            return fail("no render client");
        }
        buffer_ms_ = 1000.0 * frames_ / rate_;
        // What Windows adds after the buffer: its engine's latency for the stream.
        REFERENCE_TIME latency = 0;
        client_->GetStreamLatency(&latency);
        jvm::log("player: WASAPI: %s, %u frames buffered (%.1f ms), stream latency %.1f ms", mode_, frames_, buffer_ms_, static_cast<double>(latency) / 1e4);
        started_ = false;
        pending_.clear();
        return true;
    }
    // The device, closed: its client and its event.
    void close() {
        if (client_) client_->Stop();
        release(render_);
        release(client_);
        release(device_);
        if (event_) CloseHandle(event_);
        event_ = nullptr;
        started_ = false;
        exclusive_ = false;
        pending_.clear();
    }
    // The device went (unplugged, its format changed, taken by another program alone): closed, asked for again soon,
    // and the frames left this time given their time.
    bool lost(HRESULT hr, std::size_t left) {
        jvm::log("player: WASAPI: the output went (%#lx): opening it again soon", static_cast<unsigned long>(hr));
        close();
        retry_at_ = Clock::now() + kRetry;
        return keep_time(left);
    }
    // As long as `frames` take to play: the mixer's pace without a device.
    bool keep_time(std::size_t frames) {
        std::this_thread::sleep_for(std::chrono::microseconds(static_cast<long long>(frames) * 1000000 / rate_));
        return true;
    }
    void begin() {
        client_->Start();
        started_ = true;
    }
    IMMDeviceEnumerator* devices_ = nullptr;
    Watch* watch_ = nullptr;
    std::shared_ptr<News> news_ = std::make_shared<News>();
    IMMDevice* device_ = nullptr;
    IAudioClient* client_ = nullptr;
    IAudioRenderClient* render_ = nullptr;
    HANDLE event_ = nullptr;
    // The device's buffer in frames, and the frames the output takes at a time from this start's mode (0: any number),
    // which the first start sets for the mixer (period_).
    UINT32 frames_ = 0;
    std::size_t period_frames_ = 0, period_ = 0;
    // The device's format, and how it is had: alone, or shared (low latency or not), for the log.
    Format format_;
    bool exclusive_ = false;
    const char* mode_ = "shared";
    // Alone: the mixer's frames not yet in a whole buffer.
    std::vector<float> pending_;
    int rate_ = 48000;
    double buffer_ms_ = 20;
    bool started_ = false, thread_ready_ = false, named_missing_logged_ = false;
    Clock::time_point retry_at_{};
};

// A JSON string's contents for `s`: quotes, backslashes and control characters escaped.
std::string json_text(const std::string& s) {
    std::string out;
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') {
            out += '\\';
            out += static_cast<char>(c);
        } else if (c < 0x20) {
            char buf[8];
            std::snprintf(buf, sizeof buf, "\\u%04x", c);
            out += buf;
        } else {
            out += static_cast<char>(c);
        }
    }
    return out;
}

}  // namespace

std::string list_devices() {
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    IMMDeviceEnumerator* devices = nullptr;
    if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, __uuidof(IMMDeviceEnumerator), reinterpret_cast<void**>(&devices))))
        return "";
    // Windows' default output, to mark it.
    std::string fallback;
    IMMDevice* standard = nullptr;
    if (SUCCEEDED(devices->GetDefaultAudioEndpoint(eRender, eConsole, &standard))) {
        LPWSTR id = nullptr;
        if (SUCCEEDED(standard->GetId(&id))) {
            fallback = narrow(id);
            CoTaskMemFree(id);
        }
        release(standard);
    }
    std::string out;
    IMMDeviceCollection* all = nullptr;
    UINT count = 0;
    if (SUCCEEDED(devices->EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE, &all)) && SUCCEEDED(all->GetCount(&count))) {
        for (UINT i = 0; i < count; ++i) {
            IMMDevice* device = nullptr;
            if (FAILED(all->Item(i, &device))) continue;
            LPWSTR wid = nullptr;
            std::string id, name;
            if (SUCCEEDED(device->GetId(&wid))) {
                id = narrow(wid);
                CoTaskMemFree(wid);
            }
            IPropertyStore* props = nullptr;
            if (SUCCEEDED(device->OpenPropertyStore(STGM_READ, &props))) {
                PROPVARIANT v;
                PropVariantInit(&v);
                if (SUCCEEDED(props->GetValue(kFriendlyName, &v)) && v.vt == VT_LPWSTR) name = narrow(v.pwszVal);
                PropVariantClear(&v);
                release(props);
            }
            release(device);
            if (id.empty()) continue;
            out += "{\"id\": \"" + json_text(id) + "\", \"name\": \"" + json_text(name.empty() ? id : name) + "\", \"default\": " +
                   (id == fallback ? "true" : "false") + "}\n";
        }
    }
    release(all);
    release(devices);
    return out;
}

std::unique_ptr<Output> open_wasapi(int) {
    auto out = std::make_unique<Wasapi>();
    if (!out->open()) return nullptr;
    return out;
}

// No PulseAudio on Windows: the mixer asks for it by name only on Linux.
std::unique_ptr<Output> open_pulse(int) { return nullptr; }

}  // namespace player::audio
