// OpenSL ES for the guest.
//
// OpenSL objects and interfaces are pointers to pointers to tables of methods. The guest gets a
// proxy for every host interface: a guest word pointing at a guest method table whose entries
// trap to a host function per (interface kind, method). The host function finds the host
// interface behind the proxy and converts the arguments. Buffer queue and play callbacks run
// on the host's audio threads, which become guest threads to call the guest's callback.
#include "gl_bridge.h"
#include "live.h"
#include "opensl_numbers.h"

#include <SLES/OpenSLES.h>
#include <SLES/OpenSLES_Android.h>
#include <dlfcn.h>

namespace arm32 {

namespace {

enum Kind { kObject, kEngine, kPlay, kBufferQueue, kVolume, kConfig, kOther, kKinds };
constexpr std::uint32_t kMethodsPerKind = 32;
// Host numbers of the interface methods: kHostBase + 0x3100 + kind * 32 + method, or the same
// offset from kReentrantBase for the methods that run detached (see kDetached).
constexpr std::uint32_t kMethodOffset = 0x3100;
constexpr SLresult kUnsupported = SL_RESULT_FEATURE_UNSUPPORTED;
// SLObjectItf methods that can wait a while: Realize and Resume talk to the audio service, and
// Destroy waits for the player's callback thread to finish. They run detached from the guest
// (reentrant), so that a signal for the waiting thread, the garbage collector's stop-the-world
// among them, is handled while it waits; held up behind a callback that itself waits for the
// collector, it would never come back.
constexpr bool kDetached[kMethodsPerKind] = {true, true, false, false, false, false, true};

void* sl_lib() {
    static void* lib = dlopen("libOpenSLES.so", RTLD_NOW | RTLD_LOCAL);
    return lib;
}

// ---- interface IDs: the guest's are "ARM32IID" + an index into the generated name list.

SLInterfaceID host_iid(gaddr g) {
    if (!g || !gmem().readable(g, 16)) return nullptr;
    const std::uint8_t* b = gmem().host(g);
    if (std::memcmp(b, "ARM32IID", 8) != 0) return nullptr;
    std::uint64_t index = 0;
    for (int i = 8; i < 16; ++i) index = index << 8 | b[i];
    if (index >= kSl_data_count) return nullptr;
    void* sym = dlsym(sl_lib(), kSl_data_names[index]);
    return sym ? *static_cast<const SLInterfaceID*>(sym) : nullptr;
}

Kind kind_of(gaddr g) {
    if (!g || !gmem().readable(g, 16) || std::memcmp(gmem().host(g), "ARM32IID", 8) != 0) return kOther;
    std::uint64_t index = 0;
    for (int i = 8; i < 16; ++i) index = index << 8 | gmem().host(g)[i];
    if (index >= kSl_data_count) return kOther;
    std::string name = kSl_data_names[index];
    if (name == "SL_IID_ENGINE") return kEngine;
    if (name == "SL_IID_PLAY") return kPlay;
    if (name == "SL_IID_BUFFERQUEUE" || name == "SL_IID_ANDROIDSIMPLEBUFFERQUEUE") return kBufferQueue;
    if (name == "SL_IID_VOLUME") return kVolume;
    if (name == "SL_IID_ANDROIDCONFIGURATION") return kConfig;
    return kOther;
}

std::vector<SLInterfaceID> host_iids(gaddr array, SLuint32 n) {
    std::vector<SLInterfaceID> v(n);
    for (SLuint32 i = 0; i < n; ++i) v[i] = host_iid(*gmem().ptr<std::uint32_t>(array + i * 4));
    return v;
}

// ---- proxies

// A guest callback registered with a host interface: its function, the guest's context, and the
// proxy the host's callback is for.
struct Callback {
    gaddr fn;
    gaddr context;
    gaddr proxy;
};

struct Proxy {
    const void* host;    // the host interface (a pointer to a pointer to the method table)
    Kind kind;
    const void* parent;  // the host object an interface belongs to (null for an object)
    // Callback contexts registered through this interface, freed when its object is destroyed
    // (the host calls no callback after that; replaced ones may still be running before).
    std::vector<Callback*> callbacks;
};
std::mutex g_proxies_lock;
std::unordered_map<gaddr, Proxy> g_proxies;
std::unordered_map<const void*, gaddr> g_proxy_of;
std::array<gaddr, kKinds> g_tables{};  // guest method table per kind

// The proxy of a host interface or object. Interfaces live inside their object, so a host
// address seen before can belong to a new object now, as an interface of another kind: a proxy
// of the wrong kind sends the guest's calls through the wrong method table, so it is replaced.
gaddr proxy_for(const void* host, Kind kind, const void* parent = nullptr) {
    if (!host) return 0;
    std::lock_guard<std::mutex> l(g_proxies_lock);
    auto it = g_proxy_of.find(host);
    if (it != g_proxy_of.end()) {
        Proxy& old = g_proxies[it->second];
        if (old.kind == kind) {
            old.parent = parent;
            return it->second;
        }
        // Its object is gone (the address holds another now), and with it its callbacks.
        for (Callback* cb : old.callbacks) delete cb;
        g_proxies.erase(it->second);
        g_proxy_of.erase(it);
    }
    gaddr p = arena_alloc(4);
    *gmem().ptr<std::uint32_t>(p) = g_tables[kind];
    g_proxies[p] = Proxy{host, kind, parent, {}};
    g_proxy_of[host] = p;
    return p;
}

// A callback context kept with the interface it was registered through.
void keep_callback(gaddr proxy, Callback* cb) {
    std::lock_guard<std::mutex> l(g_proxies_lock);
    auto it = g_proxies.find(proxy);
    if (it != g_proxies.end()) it->second.callbacks.push_back(cb);
}

template <class T>
T host_of(gaddr proxy) {
    std::lock_guard<std::mutex> l(g_proxies_lock);
    auto it = g_proxies.find(proxy);
    return it == g_proxies.end() ? nullptr : static_cast<T>(it->second.host);
}

void put_u32(gaddr out, std::uint32_t v) {
    if (out) *gmem().ptr<std::uint32_t>(out) = v;
}

// ---- data locators and formats, 32-bit layouts to host ones

struct DataStorage {
    union {
        SLDataLocator_AndroidSimpleBufferQueue bq;
        SLDataLocator_OutputMix mix;
        SLDataLocator_URI uri;
        SLDataLocator_AndroidFD fd;
        SLDataLocator_IODevice io;
        SLuint32 type;
    } locator;
    union {
        SLDataFormat_PCM pcm;
        SLAndroidDataFormat_PCM_EX pcm_ex;
        SLDataFormat_MIME mime;
        SLuint32 type;
    } format;
    SLDataSource source;
    SLDataSink sink;
};

bool convert_locator(gaddr g, DataStorage& d) {
    if (!g) return false;
    auto* w = gmem().ptr<std::uint32_t>(g);
    d.locator.type = w[0];
    switch (w[0]) {
    case SL_DATALOCATOR_ANDROIDSIMPLEBUFFERQUEUE:
    case SL_DATALOCATOR_BUFFERQUEUE:
        d.locator.bq.numBuffers = w[1];
        return true;
    case SL_DATALOCATOR_OUTPUTMIX:
        d.locator.mix.outputMix = host_of<SLObjectItf>(w[1]);
        return true;
    case SL_DATALOCATOR_URI:
        d.locator.uri.URI = static_cast<SLchar*>(guest_ptr(w[1]));
        return true;
    case SL_DATALOCATOR_ANDROIDFD:
        // fd at 4, then two 64-bit values at 8 and 16, as on the host.
        d.locator.fd.fd = static_cast<SLint32>(w[1]);
        std::memcpy(&d.locator.fd.offset, gmem().host(g + 8), 8);
        std::memcpy(&d.locator.fd.length, gmem().host(g + 16), 8);
        return true;
    case SL_DATALOCATOR_IODEVICE:
        d.locator.io.deviceType = w[1];
        d.locator.io.deviceID = w[2];
        d.locator.io.device = host_of<SLObjectItf>(w[3]);
        return true;
    default:
        log("arm32: opensl: data locator %#x not supported", w[0]);
        return false;
    }
}

bool convert_format(gaddr g, DataStorage& d) {
    if (!g) return true;  // sinks may have no format
    auto* w = gmem().ptr<std::uint32_t>(g);
    switch (w[0]) {
    case SL_DATAFORMAT_PCM:
        std::memcpy(&d.format.pcm, w, sizeof(SLDataFormat_PCM));
        return true;
    case SL_ANDROID_DATAFORMAT_PCM_EX:
        std::memcpy(&d.format.pcm_ex, w, sizeof(SLAndroidDataFormat_PCM_EX));
        return true;
    case SL_DATAFORMAT_MIME:
        d.format.mime.formatType = w[0];
        d.format.mime.mimeType = static_cast<SLchar*>(guest_ptr(w[1]));
        d.format.mime.containerType = w[2];
        return true;
    default:
        log("arm32: opensl: data format %#x not supported", w[0]);
        return false;
    }
}

// A guest SLDataSource / SLDataSink: { pLocator, pFormat }.
bool convert_data(gaddr g, DataStorage& d, bool sink) {
    if (!g) return false;
    gaddr locator = *gmem().ptr<std::uint32_t>(g);
    gaddr format = *gmem().ptr<std::uint32_t>(g + 4);
    if (!convert_locator(locator, d) || !convert_format(format, d)) return false;
    void* f = format ? static_cast<void*>(&d.format) : nullptr;
    if (sink) d.sink = SLDataSink{&d.locator, f};
    else d.source = SLDataSource{&d.locator, f};
    return true;
}

// ---- callbacks into the guest, on host audio threads

// An audio thread the agent could not give a guest thread to (logged) skips the callback rather
// than blocking the audio system.
void bq_callback(SLAndroidSimpleBufferQueueItf, void* context) {
    auto* cb = static_cast<Callback*>(context);
    Thread* t = Guest::get().try_current();
    if (!t) return;
    // The game's mixer fills the next buffer here (FMOD's OpenSL output, as on phones): with stats
    // on, how long that takes and the time between buffers.
    const auto start = g_stats ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};
    t->call(cb->fn, {cb->proxy, cb->context});
    if (g_stats) note_audio(start);
}

void play_callback(SLPlayItf, void* context, SLuint32 event) {
    auto* cb = static_cast<Callback*>(context);
    if (Thread* t = Guest::get().try_current()) t->call(cb->fn, {cb->proxy, cb->context, event});
}

// ---- methods. Each reads (self, args...) and calls the host interface's method.

#define SELF(type) auto self = host_of<type>(w.u32()); if (!self) return SL_RESULT_PARAMETER_INVALID

// SLObjectItf
// Always synchronous: completion callbacks of asynchronous calls are not passed on.
std::uint64_t obj_Realize(Thread& t) { Words w{t}; SELF(SLObjectItf); return (*self)->Realize(self, SL_BOOLEAN_FALSE); }
std::uint64_t obj_Resume(Thread& t) { Words w{t}; SELF(SLObjectItf); return (*self)->Resume(self, SL_BOOLEAN_FALSE); }
std::uint64_t obj_GetState(Thread& t) {
    Words w{t};
    SELF(SLObjectItf);
    return (*self)->GetState(self, static_cast<SLuint32*>(guest_ptr(w.u32())));
}
// The player's format goes to live view with the buffer queue its sound will come through.
void player_queue_known(const void* player, const void* queue);

std::uint64_t obj_GetInterface(Thread& t) {
    Words w{t};
    SELF(SLObjectItf);
    gaddr iid = w.u32();
    gaddr out = w.u32();
    const void* itf = nullptr;
    SLresult r = (*self)->GetInterface(self, host_iid(iid), &itf);
    put_u32(out, r == SL_RESULT_SUCCESS ? proxy_for(itf, kind_of(iid), self) : 0);
    if (r == SL_RESULT_SUCCESS && kind_of(iid) == kBufferQueue) player_queue_known(self, itf);
    return r;
}
std::uint64_t obj_RegisterCallback(Thread&) {
    // Asynchronous realisation callbacks are not passed on; realise synchronously instead.
    return SL_RESULT_SUCCESS;
}
std::uint64_t obj_AbortAsyncOperation(Thread& t) { Words w{t}; SELF(SLObjectItf); (*self)->AbortAsyncOperation(self); return 0; }
std::uint64_t obj_Destroy(Thread& t) {
    Words w{t};
    gaddr p = w.u32();
    auto self = host_of<SLObjectItf>(p);
    if (!self) return 0;
    (*self)->Destroy(self);
    // The object's proxy goes, and so do those of its interfaces (with their callback contexts):
    // the memory they point into is free now, and may hold another object's interfaces soon.
    std::lock_guard<std::mutex> l(g_proxies_lock);
    for (auto it = g_proxies.begin(); it != g_proxies.end();) {
        if (it->first == p || it->second.parent == self) {
            for (Callback* cb : it->second.callbacks) delete cb;
            g_proxy_of.erase(it->second.host);
            it = g_proxies.erase(it);
        } else {
            ++it;
        }
    }
    return 0;
}
std::uint64_t obj_SetPriority(Thread& t) {
    Words w{t};
    SELF(SLObjectItf);
    auto priority = static_cast<SLint32>(w.u32());
    return (*self)->SetPriority(self, priority, static_cast<SLboolean>(w.u32()));
}
std::uint64_t obj_GetPriority(Thread& t) {
    Words w{t};
    SELF(SLObjectItf);
    auto* priority = static_cast<SLint32*>(guest_ptr(w.u32()));
    return (*self)->GetPriority(self, priority, static_cast<SLboolean*>(guest_ptr(w.u32())));
}
std::uint64_t obj_SetLossOfControlInterfaces(Thread& t) {
    Words w{t};
    SELF(SLObjectItf);
    auto n = static_cast<SLint16>(w.u32());
    auto ids = host_iids(w.u32(), static_cast<SLuint32>(n > 0 ? n : 0));
    return (*self)->SetLossOfControlInterfaces(self, n, ids.data(), static_cast<SLboolean>(w.u32()));
}

// SLEngineItf
// The PCM format each audio player was created with, until the game asks for its buffer queue.
std::mutex g_player_formats_lock;
std::unordered_map<const void*, std::array<int, 3>> g_player_formats;  // rate in Hz, channels, bits (0: not integer)

void keep_player_format(const void* player, const DataStorage& source) {
    std::array<int, 3> format{};
    // The rates are in thousandths of a hertz.
    if (source.format.pcm.formatType == SL_DATAFORMAT_PCM) {
        format = {static_cast<int>(source.format.pcm.samplesPerSec / 1000), static_cast<int>(source.format.pcm.numChannels),
                  static_cast<int>(source.format.pcm.bitsPerSample)};
    } else if (source.format.pcm_ex.formatType == SL_ANDROID_DATAFORMAT_PCM_EX) {
        format = {static_cast<int>(source.format.pcm_ex.sampleRate / 1000), static_cast<int>(source.format.pcm_ex.numChannels),
                  source.format.pcm_ex.representation == SL_ANDROID_PCM_REPRESENTATION_SIGNED_INT ? static_cast<int>(source.format.pcm_ex.bitsPerSample) : 0};
    } else {
        return;
    }
    std::lock_guard<std::mutex> l(g_player_formats_lock);
    g_player_formats[player] = format;
}

void player_queue_known(const void* player, const void* queue) {
    std::array<int, 3> format{};
    {
        std::lock_guard<std::mutex> l(g_player_formats_lock);
        auto it = g_player_formats.find(player);
        if (it == g_player_formats.end()) return;
        format = it->second;
        g_player_formats.erase(it);
    }
    live_audio_source(queue, format[0], format[1], format[2]);
}

std::uint64_t engine_CreateAudioPlayer(Thread& t) {
    Words w{t};
    SELF(SLEngineItf);
    gaddr out = w.u32();
    gaddr src = w.u32();
    gaddr snk = w.u32();
    SLuint32 n = w.u32();
    auto ids = host_iids(w.u32(), n);
    auto* required = static_cast<const SLboolean*>(guest_ptr(w.u32()));
    DataStorage source{}, sink{};
    if (!convert_data(src, source, false) || !convert_data(snk, sink, true)) return SL_RESULT_PARAMETER_INVALID;
    SLObjectItf player = nullptr;
    SLresult r = (*self)->CreateAudioPlayer(self, &player, &source.source, &sink.sink, n, ids.data(), required);
    // What this player's buffers hold, for live view; its buffer queue interface comes later.
    if (r == SL_RESULT_SUCCESS) keep_player_format(player, source);
    put_u32(out, r == SL_RESULT_SUCCESS ? proxy_for(player, kObject) : 0);
    return r;
}
std::uint64_t engine_CreateAudioRecorder(Thread& t) {
    Words w{t};
    SELF(SLEngineItf);
    gaddr out = w.u32();
    gaddr src = w.u32();
    gaddr snk = w.u32();
    SLuint32 n = w.u32();
    auto ids = host_iids(w.u32(), n);
    auto* required = static_cast<const SLboolean*>(guest_ptr(w.u32()));
    DataStorage source{}, sink{};
    if (!convert_data(src, source, false) || !convert_data(snk, sink, true)) return SL_RESULT_PARAMETER_INVALID;
    SLObjectItf recorder = nullptr;
    SLresult r = (*self)->CreateAudioRecorder(self, &recorder, &source.source, &sink.sink, n, ids.data(), required);
    put_u32(out, r == SL_RESULT_SUCCESS ? proxy_for(recorder, kObject) : 0);
    return r;
}
std::uint64_t engine_CreateOutputMix(Thread& t) {
    Words w{t};
    SELF(SLEngineItf);
    gaddr out = w.u32();
    SLuint32 n = w.u32();
    auto ids = host_iids(w.u32(), n);
    auto* required = static_cast<const SLboolean*>(guest_ptr(w.u32()));
    SLObjectItf mix = nullptr;
    SLresult r = (*self)->CreateOutputMix(self, &mix, n, ids.data(), required);
    put_u32(out, r == SL_RESULT_SUCCESS ? proxy_for(mix, kObject) : 0);
    return r;
}
std::uint64_t engine_QueryNumSupportedInterfaces(Thread& t) {
    Words w{t};
    SELF(SLEngineItf);
    auto id = static_cast<SLuint32>(w.u32());
    return (*self)->QueryNumSupportedInterfaces(self, id, static_cast<SLuint32*>(guest_ptr(w.u32())));
}
std::uint64_t engine_QueryNumSupportedExtensions(Thread& t) {
    Words w{t};
    SELF(SLEngineItf);
    return (*self)->QueryNumSupportedExtensions(self, static_cast<SLuint32*>(guest_ptr(w.u32())));
}
std::uint64_t engine_QuerySupportedExtension(Thread& t) {
    Words w{t};
    SELF(SLEngineItf);
    auto index = static_cast<SLuint32>(w.u32());
    auto* name = static_cast<SLchar*>(guest_ptr(w.u32()));
    return (*self)->QuerySupportedExtension(self, index, name, static_cast<SLint16*>(guest_ptr(w.u32())));
}
std::uint64_t engine_IsExtensionSupported(Thread& t) {
    Words w{t};
    SELF(SLEngineItf);
    auto* name = static_cast<const SLchar*>(guest_ptr(w.u32()));
    return (*self)->IsExtensionSupported(self, name, static_cast<SLboolean*>(guest_ptr(w.u32())));
}

// SLPlayItf
std::uint64_t play_SetPlayState(Thread& t) { Words w{t}; SELF(SLPlayItf); return (*self)->SetPlayState(self, w.u32()); }
std::uint64_t play_GetPlayState(Thread& t) { Words w{t}; SELF(SLPlayItf); return (*self)->GetPlayState(self, static_cast<SLuint32*>(guest_ptr(w.u32()))); }
std::uint64_t play_GetDuration(Thread& t) { Words w{t}; SELF(SLPlayItf); return (*self)->GetDuration(self, static_cast<SLmillisecond*>(guest_ptr(w.u32()))); }
std::uint64_t play_GetPosition(Thread& t) { Words w{t}; SELF(SLPlayItf); return (*self)->GetPosition(self, static_cast<SLmillisecond*>(guest_ptr(w.u32()))); }
std::uint64_t play_RegisterCallback(Thread& t) {
    Words w{t};
    gaddr p = w.u32();
    auto self = host_of<SLPlayItf>(p);
    if (!self) return SL_RESULT_PARAMETER_INVALID;
    gaddr fn = w.u32();
    gaddr context = w.u32();
    if (!fn) return (*self)->RegisterCallback(self, nullptr, nullptr);
    // Kept until the player is destroyed: a callback with the context it replaces may still be
    // running on the audio thread.
    auto* cb = new Callback{fn, context, p};
    keep_callback(p, cb);
    return (*self)->RegisterCallback(self, play_callback, cb);
}
std::uint64_t play_SetCallbackEventsMask(Thread& t) { Words w{t}; SELF(SLPlayItf); return (*self)->SetCallbackEventsMask(self, w.u32()); }
std::uint64_t play_GetCallbackEventsMask(Thread& t) { Words w{t}; SELF(SLPlayItf); return (*self)->GetCallbackEventsMask(self, static_cast<SLuint32*>(guest_ptr(w.u32()))); }
std::uint64_t play_SetMarkerPosition(Thread& t) { Words w{t}; SELF(SLPlayItf); return (*self)->SetMarkerPosition(self, w.u32()); }
std::uint64_t play_ClearMarkerPosition(Thread& t) { Words w{t}; SELF(SLPlayItf); return (*self)->ClearMarkerPosition(self); }
std::uint64_t play_GetMarkerPosition(Thread& t) { Words w{t}; SELF(SLPlayItf); return (*self)->GetMarkerPosition(self, static_cast<SLmillisecond*>(guest_ptr(w.u32()))); }
std::uint64_t play_SetPositionUpdatePeriod(Thread& t) { Words w{t}; SELF(SLPlayItf); return (*self)->SetPositionUpdatePeriod(self, w.u32()); }
std::uint64_t play_GetPositionUpdatePeriod(Thread& t) { Words w{t}; SELF(SLPlayItf); return (*self)->GetPositionUpdatePeriod(self, static_cast<SLmillisecond*>(guest_ptr(w.u32()))); }

// SLBufferQueueItf and SLAndroidSimpleBufferQueueItf share their layout.
std::uint64_t bq_Enqueue(Thread& t) {
    Words w{t};
    SELF(SLAndroidSimpleBufferQueueItf);
    // The buffer is guest memory, which is host memory too and stays put while it plays.
    const void* buffer = guest_ptr(w.u32());
    const std::uint32_t size = w.u32();
    // The game's sound for live view, when that is on; this thread is the mixer's, and never waits.
    live_audio(self, buffer, size);
    return (*self)->Enqueue(self, buffer, size);
}
std::uint64_t bq_Clear(Thread& t) { Words w{t}; SELF(SLAndroidSimpleBufferQueueItf); return (*self)->Clear(self); }
std::uint64_t bq_GetState(Thread& t) {
    Words w{t};
    SELF(SLAndroidSimpleBufferQueueItf);
    return (*self)->GetState(self, static_cast<SLAndroidSimpleBufferQueueState*>(guest_ptr(w.u32())));
}
std::uint64_t bq_RegisterCallback(Thread& t) {
    Words w{t};
    gaddr p = w.u32();
    auto self = host_of<SLAndroidSimpleBufferQueueItf>(p);
    if (!self) return SL_RESULT_PARAMETER_INVALID;
    gaddr fn = w.u32();
    gaddr context = w.u32();
    if (!fn) return (*self)->RegisterCallback(self, nullptr, nullptr);
    auto* cb = new Callback{fn, context, p};  // kept as for play_RegisterCallback
    keep_callback(p, cb);
    return (*self)->RegisterCallback(self, bq_callback, cb);
}

// SLVolumeItf
std::uint64_t vol_SetVolumeLevel(Thread& t) { Words w{t}; SELF(SLVolumeItf); return (*self)->SetVolumeLevel(self, static_cast<SLmillibel>(w.u32())); }
std::uint64_t vol_GetVolumeLevel(Thread& t) { Words w{t}; SELF(SLVolumeItf); return (*self)->GetVolumeLevel(self, static_cast<SLmillibel*>(guest_ptr(w.u32()))); }
std::uint64_t vol_GetMaxVolumeLevel(Thread& t) { Words w{t}; SELF(SLVolumeItf); return (*self)->GetMaxVolumeLevel(self, static_cast<SLmillibel*>(guest_ptr(w.u32()))); }
std::uint64_t vol_SetMute(Thread& t) { Words w{t}; SELF(SLVolumeItf); return (*self)->SetMute(self, static_cast<SLboolean>(w.u32())); }
std::uint64_t vol_GetMute(Thread& t) { Words w{t}; SELF(SLVolumeItf); return (*self)->GetMute(self, static_cast<SLboolean*>(guest_ptr(w.u32()))); }
std::uint64_t vol_EnableStereoPosition(Thread& t) { Words w{t}; SELF(SLVolumeItf); return (*self)->EnableStereoPosition(self, static_cast<SLboolean>(w.u32())); }
std::uint64_t vol_IsEnabledStereoPosition(Thread& t) { Words w{t}; SELF(SLVolumeItf); return (*self)->IsEnabledStereoPosition(self, static_cast<SLboolean*>(guest_ptr(w.u32()))); }
std::uint64_t vol_SetStereoPosition(Thread& t) { Words w{t}; SELF(SLVolumeItf); return (*self)->SetStereoPosition(self, static_cast<SLpermille>(w.u32())); }
std::uint64_t vol_GetStereoPosition(Thread& t) { Words w{t}; SELF(SLVolumeItf); return (*self)->GetStereoPosition(self, static_cast<SLpermille*>(guest_ptr(w.u32()))); }

// SLAndroidConfigurationItf
std::uint64_t cfg_SetConfiguration(Thread& t) {
    Words w{t};
    SELF(SLAndroidConfigurationItf);
    auto* key = static_cast<const SLchar*>(guest_ptr(w.u32()));
    const void* value = guest_ptr(w.u32());
    return (*self)->SetConfiguration(self, key, value, w.u32());
}
std::uint64_t cfg_GetConfiguration(Thread& t) {
    Words w{t};
    SELF(SLAndroidConfigurationItf);
    auto* key = static_cast<const SLchar*>(guest_ptr(w.u32()));
    auto* size = static_cast<SLuint32*>(guest_ptr(w.u32()));
    return (*self)->GetConfiguration(self, key, size, guest_ptr(w.u32()));
}

std::uint64_t unsupported(Thread&) { return kUnsupported; }

// ---- entry points

std::uint64_t sl_CreateEngine(Thread& t) {
    static auto fn = reinterpret_cast<SLresult (*)(SLObjectItf*, SLuint32, const SLEngineOption*, SLuint32, const SLInterfaceID*,
                                                   const SLboolean*)>(dlsym(sl_lib(), "slCreateEngine"));
    Words w{t};
    gaddr out = w.u32();
    SLuint32 options = w.u32();
    // SLEngineOption is two 32-bit words, as on the host.
    auto* option_array = static_cast<const SLEngineOption*>(guest_ptr(w.u32()));
    SLuint32 n = w.u32();
    auto ids = host_iids(w.u32(), n);
    auto* required = static_cast<const SLboolean*>(guest_ptr(w.u32()));
    if (!fn) return SL_RESULT_INTERNAL_ERROR;
    SLObjectItf engine = nullptr;
    SLresult r = fn(&engine, options, option_array, n, ids.data(), required);
    put_u32(out, r == SL_RESULT_SUCCESS ? proxy_for(engine, kObject) : 0);
    return r;
}

std::uint64_t sl_QueryNumSupportedEngineInterfaces(Thread& t) {
    static auto fn = reinterpret_cast<SLresult (*)(SLuint32*)>(dlsym(sl_lib(), "slQueryNumSupportedEngineInterfaces"));
    Words w{t};
    return fn ? fn(static_cast<SLuint32*>(guest_ptr(w.u32()))) : SL_RESULT_INTERNAL_ERROR;
}

// Writes the stub for host function `number` at guest address `at` (as for JNI).
void write_stub(gaddr at, std::uint32_t number) {
    std::uint32_t lo = number & 0xffff, hi = number >> 16;
    const std::uint32_t code[5] = {0xe92d4080, 0xe3007000 | ((lo & 0xf000) << 4) | (lo & 0xfff),
                                   0xe3407000 | ((hi & 0xf000) << 4) | (hi & 0xfff), 0xef000000, 0xe8bd8080};
    std::memcpy(gmem().host(at), code, sizeof code);
}

}  // namespace

void opensl_register() {
    register_host_fn(kSl_slCreateEngine, &sl_CreateEngine);
    register_host_fn(kSl_slQueryNumSupportedEngineInterfaces, &sl_QueryNumSupportedEngineInterfaces);
    register_host_fn(kSl_slQuerySupportedEngineInterfaces, &unsupported);
    // Method tables in the order of the OpenSL ES 1.0.1 headers.
    const std::vector<HostFn> methods[kKinds] = {
        {obj_Realize, obj_Resume, obj_GetState, obj_GetInterface, obj_RegisterCallback, obj_AbortAsyncOperation, obj_Destroy,
         obj_SetPriority, obj_GetPriority, obj_SetLossOfControlInterfaces},
        {unsupported, unsupported, engine_CreateAudioPlayer, engine_CreateAudioRecorder, unsupported, unsupported, unsupported,
         engine_CreateOutputMix, unsupported, unsupported, engine_QueryNumSupportedInterfaces, unsupported,
         engine_QueryNumSupportedExtensions, engine_QuerySupportedExtension, engine_IsExtensionSupported},
        {play_SetPlayState, play_GetPlayState, play_GetDuration, play_GetPosition, play_RegisterCallback, play_SetCallbackEventsMask,
         play_GetCallbackEventsMask, play_SetMarkerPosition, play_ClearMarkerPosition, play_GetMarkerPosition,
         play_SetPositionUpdatePeriod, play_GetPositionUpdatePeriod},
        {bq_Enqueue, bq_Clear, bq_GetState, bq_RegisterCallback},
        {vol_SetVolumeLevel, vol_GetVolumeLevel, vol_GetMaxVolumeLevel, vol_SetMute, vol_GetMute, vol_EnableStereoPosition,
         vol_IsEnabledStereoPosition, vol_SetStereoPosition, vol_GetStereoPosition},
        {cfg_SetConfiguration, cfg_GetConfiguration},
        {},
    };
    // Guest stubs and method tables: every kind gets kMethodsPerKind entries, unused ones say
    // the feature is unsupported.
    std::uint32_t code_bytes = kKinds * kMethodsPerKind * 20;
    auto code = static_cast<gaddr>(gmem().map(0, code_bytes, kProtRead | kProtExec, false, "[opensl stubs]"));
    for (std::uint32_t k = 0; k < kKinds; ++k) {
        gaddr table = arena_alloc(kMethodsPerKind * 4);
        g_tables[k] = table;
        for (std::uint32_t m = 0; m < kMethodsPerKind; ++m) {
            bool detached = k == kObject && kDetached[m];
            std::uint32_t number = (detached ? kReentrantBase : kHostBase) + kMethodOffset + k * kMethodsPerKind + m;
            gaddr stub = code + (k * kMethodsPerKind + m) * 20;
            write_stub(stub, number);
            *gmem().ptr<std::uint32_t>(table + m * 4) = stub;
            register_host_fn(number, m < methods[k].size() ? methods[k][m] : &unsupported);
        }
    }
}

}  // namespace arm32
