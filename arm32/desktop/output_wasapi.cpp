// The sound output on Windows: WASAPI in shared mode, at the rate the device mixes at (so that Windows resamples
// nothing), stereo floats as the mixer makes them, with Windows' own conversion to the device's channels where they
// differ. Event-driven: a write waits for the device to have room, which paces the mixer. A short buffer (20 ms) for a
// rhythm game's sounds; the mixer thread is a "Pro Audio" thread for Windows' scheduler (MMCSS).
//
// A device can go while the game plays (headphones unplugged, another program taking it alone) and Windows' default
// output can change: the output then closes, keeps the mixer's time as if it played, and opens the default device
// again, at once on a change and every second after a loss. Its writes never fail: the mixer keeps it for the whole run.
#include "mixer.h"

#include "jvm.h"

#include <windows.h>
#include <audioclient.h>
#include <avrt.h>
#include <ksmedia.h>
#include <mmdeviceapi.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstring>
#include <memory>
#include <thread>

namespace player::audio {

namespace {

// What the output asks for: 20 ms of buffer, the mixer's period four times.
constexpr double kBufferMs = 20;
// How long after a loss the device is asked for again.
constexpr auto kRetry = std::chrono::seconds(1);

// COM's handles, released with the output.
template <class T>
void release(T*& p) {
    if (p) p->Release();
    p = nullptr;
}

// Windows' word that the default output changed: a flag the next write reads. The flag is shared, so that a call
// Windows makes while the output is being closed still has it.
class Watch final : public IMMNotificationClient {
public:
    explicit Watch(std::shared_ptr<std::atomic<bool>> changed) : changed_(std::move(changed)) {}
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
    // The console's output is the one games play through.
    HRESULT STDMETHODCALLTYPE OnDefaultDeviceChanged(EDataFlow flow, ERole role, LPCWSTR) override {
        if (flow == eRender && role == eConsole) changed_->store(true);
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE OnDeviceAdded(LPCWSTR) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE OnDeviceRemoved(LPCWSTR) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE OnDeviceStateChanged(LPCWSTR, DWORD) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE OnPropertyValueChanged(LPCWSTR, const PROPERTYKEY) override { return S_OK; }

private:
    std::atomic<ULONG> refs_{1};
    std::shared_ptr<std::atomic<bool>> changed_;
};

class Wasapi : public Output {
public:
    ~Wasapi() override {
        close();
        if (devices_ && watch_) devices_->UnregisterEndpointNotificationCallback(watch_);
        release(watch_);
        release(devices_);
    }
    // Opens the default output device; false with a reason in the log when it cannot.
    bool open() {
        CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, __uuidof(IMMDeviceEnumerator), reinterpret_cast<void**>(&devices_))))
            return fail("no audio device enumerator");
        // The device's own mix rate, read once: the mixer runs at it for the whole run.
        if (!start(true)) return false;
        // Told when the default output changes, to move to it.
        watch_ = new Watch(changed_);
        devices_->RegisterEndpointNotificationCallback(watch_);
        return true;
    }
    const char* name() const override { return "WASAPI"; }
    int rate() const override { return rate_; }
    double buffer_ms() const override { return buffer_ms_; }
    bool write(const float* data, std::size_t frames) override {
        if (!thread_ready_) {
            // The mixer's thread: in COM's shared apartment, and scheduled as audio by Windows.
            CoInitializeEx(nullptr, COINIT_MULTITHREADED);
            DWORD task = 0;
            AvSetMmThreadCharacteristicsW(L"Pro Audio", &task);
            thread_ready_ = true;
        }
        if (changed_->exchange(false)) {
            // Windows' default output changed: to it, now.
            jvm::log("player: WASAPI: the default output changed: moving to it");
            close();
            retry_at_ = {};
        }
        if (!client_ && Clock::now() >= retry_at_) {
            if (start(false)) jvm::log("player: WASAPI: sound out again");
            else retry_at_ = Clock::now() + kRetry;
        }
        // No device for now: the mixer's time goes on as if it played.
        if (!client_) return keep_time(frames);
        std::size_t done = 0;
        while (done < frames) {
            UINT32 padding = 0;
            HRESULT hr = client_->GetCurrentPadding(&padding);
            if (FAILED(hr)) return lost(hr, frames - done);
            UINT32 room = frames_ > padding ? frames_ - padding : 0;
            if (room == 0) {
                // Full: the device's event says when it has taken a period.
                if (!started_) begin();
                WaitForSingleObject(event_, 100);
                continue;
            }
            UINT32 n = static_cast<UINT32>(std::min<std::size_t>(room, frames - done));
            BYTE* out = nullptr;
            hr = render_->GetBuffer(n, &out);
            if (FAILED(hr)) return lost(hr, frames - done);
            std::memcpy(out, data + done * kChannels, n * kChannels * sizeof(float));
            render_->ReleaseBuffer(n, 0);
            done += n;
        }
        // Playing once the first buffer is in, so that it starts with sound and not with an underrun.
        if (!started_) begin();
        return true;
    }

private:
    using Clock = std::chrono::steady_clock;

    bool fail(const char* why) {
        jvm::log("player: WASAPI: %s", why);
        return false;
    }
    // The default output device, opened for the mixer's rate: on a later start, Windows converts from it to the
    // device's own (AUTOCONVERTPCM) when that one mixes at another.
    bool start(bool first) {
        if (FAILED(devices_->GetDefaultAudioEndpoint(eRender, eConsole, &device_))) return fail("no default output device");
        if (FAILED(device_->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, reinterpret_cast<void**>(&client_)))) {
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
        // Stereo 32-bit floats at that rate; Windows maps two channels to the device's own.
        WAVEFORMATEXTENSIBLE fmt{};
        fmt.Format.wFormatTag = WAVE_FORMAT_EXTENSIBLE;
        fmt.Format.nChannels = kChannels;
        fmt.Format.nSamplesPerSec = static_cast<DWORD>(rate_);
        fmt.Format.wBitsPerSample = 32;
        fmt.Format.nBlockAlign = static_cast<WORD>(kChannels * 4);
        fmt.Format.nAvgBytesPerSec = fmt.Format.nSamplesPerSec * fmt.Format.nBlockAlign;
        fmt.Format.cbSize = sizeof(WAVEFORMATEXTENSIBLE) - sizeof(WAVEFORMATEX);
        fmt.Samples.wValidBitsPerSample = 32;
        fmt.dwChannelMask = SPEAKER_FRONT_LEFT | SPEAKER_FRONT_RIGHT;
        fmt.SubFormat = KSDATAFORMAT_SUBTYPE_IEEE_FLOAT;
        const DWORD flags = AUDCLNT_STREAMFLAGS_EVENTCALLBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY;
        // 100-nanosecond units.
        const REFERENCE_TIME buffer = static_cast<REFERENCE_TIME>(kBufferMs * 10000);
        if (FAILED(client_->Initialize(AUDCLNT_SHAREMODE_SHARED, flags, buffer, 0, &fmt.Format, nullptr))) {
            close();
            return fail("the device refuses stereo floats");
        }
        event_ = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        client_->SetEventHandle(event_);
        client_->GetBufferSize(&frames_);
        if (FAILED(client_->GetService(__uuidof(IAudioRenderClient), reinterpret_cast<void**>(&render_)))) {
            close();
            return fail("no render client");
        }
        buffer_ms_ = 1000.0 * frames_ / rate_;
        started_ = false;
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
    std::shared_ptr<std::atomic<bool>> changed_ = std::make_shared<std::atomic<bool>>(false);
    IMMDevice* device_ = nullptr;
    IAudioClient* client_ = nullptr;
    IAudioRenderClient* render_ = nullptr;
    HANDLE event_ = nullptr;
    UINT32 frames_ = 0;
    int rate_ = 48000;
    double buffer_ms_ = kBufferMs;
    bool started_ = false, thread_ready_ = false;
    Clock::time_point retry_at_{};
};

}  // namespace

std::unique_ptr<Output> open_wasapi(int) {
    auto out = std::make_unique<Wasapi>();
    if (!out->open()) return nullptr;
    return out;
}

// No PulseAudio on Windows: the mixer asks for it by name only on Linux.
std::unique_ptr<Output> open_pulse(int) { return nullptr; }

}  // namespace player::audio
