// libandroid for the guest: assets, native windows, sensors, loopers, input events and the
// configuration. Host objects are handles; buffers and strings the host returns are copied
// into guest memory.
#include "android_numbers.h"
#include "gl_bridge.h"
#include "jni_bridge.h"
#include "pacing.h"
#include "tweaks.h"

#include <android/asset_manager.h>
#include <android/asset_manager_jni.h>
#include <android/configuration.h>
#include <android/input.h>
#include <android/looper.h>
#include <android/native_window_jni.h>
#include <android/sensor.h>
#include <climits>
#include <cstdlib>
#include <mutex>
#include <dlfcn.h>

namespace arm32 {

namespace {

// The host object behind a guest handle of the given kind (see HandleKind), and a host object's
// handle.
#define H(kind, x) handles().get(HandleKind::kind, x)
#define PUT(kind, x) handles().put(HandleKind::kind, x)

template <class T>
T* ptr(std::uint32_t g) { return static_cast<T*>(guest_ptr(g)); }

// Guest copies tied to an asset or a directory, freed with it.
std::mutex g_copies_lock;
std::unordered_map<std::uint32_t, std::pair<gaddr, std::uint32_t>> g_copies;

void forget_copy(std::uint32_t h) {
    std::lock_guard<std::mutex> l(g_copies_lock);
    auto it = g_copies.find(h);
    if (it == g_copies.end()) return;
    gmem().unmap(it->second.first, it->second.second);
    g_copies.erase(it);
}

// The guest copy for handle h, made from size bytes at data the first time (without data: size
// zero bytes, a buffer to fill).
gaddr copy_for(std::uint32_t h, const void* data, std::size_t size) {
    {
        std::lock_guard<std::mutex> l(g_copies_lock);
        auto it = g_copies.find(h);
        if (it != g_copies.end()) return it->second.first;
    }
    std::int64_t g = gmem().map(0, static_cast<std::uint32_t>(size ? size : 1), kProtRead | kProtWrite, false, "[asset]");
    if (g < 0) return 0;
    if (size && data) std::memcpy(gmem().host(static_cast<gaddr>(g)), data, size);
    std::lock_guard<std::mutex> l(g_copies_lock);
    g_copies[h] = {static_cast<gaddr>(g), static_cast<std::uint32_t>(size ? size : 1)};
    return static_cast<gaddr>(g);
}

// ---- assets

std::uint64_t a_AAssetManager_fromJava(Thread& t) {
    Words w{t};
    w.u32();  // JNIEnv: the calling thread's own is used
    return PUT(kAssetManager, AAssetManager_fromJava(jni_env(), jni_object(w.u32())));
}
std::uint64_t a_AAssetManager_open(Thread& t) {
    Words w{t};
    auto* m = static_cast<AAssetManager*>(H(kAssetManager, w.u32()));
    auto* name = ptr<const char>(w.u32());
    return PUT(kAsset, AAssetManager_open(m, name, static_cast<int>(w.u32())));
}
std::uint64_t a_AAssetManager_openDir(Thread& t) {
    Words w{t};
    auto* m = static_cast<AAssetManager*>(H(kAssetManager, w.u32()));
    return PUT(kAssetDir, AAssetManager_openDir(m, ptr<const char>(w.u32())));
}
std::uint64_t a_AAssetDir_getNextFileName(Thread& t) {
    Words w{t};
    std::uint32_t h = w.u32();
    const char* name = AAssetDir_getNextFileName(static_cast<AAssetDir*>(H(kAssetDir, h)));
    if (!name) return 0;
    // One name buffer per directory, reused for every name like the host's (made empty: copying
    // PATH_MAX bytes from "" read past the end of the literal).
    gaddr buf = copy_for(h, nullptr, PATH_MAX);
    if (!buf) return 0;
    std::strncpy(reinterpret_cast<char*>(gmem().host(buf)), name, PATH_MAX - 1);
    return buf;
}
std::uint64_t a_AAssetDir_close(Thread& t) {
    Words w{t};
    std::uint32_t h = w.u32();
    AAssetDir_close(static_cast<AAssetDir*>(H(kAssetDir, h)));
    forget_copy(h);
    handles().drop(HandleKind::kAssetDir, h);
    return 0;
}
std::uint64_t a_AAsset_close(Thread& t) {
    Words w{t};
    std::uint32_t h = w.u32();
    AAsset_close(static_cast<AAsset*>(H(kAsset, h)));
    forget_copy(h);
    handles().drop(HandleKind::kAsset, h);
    return 0;
}
std::uint64_t a_AAsset_read(Thread& t) {
    Words w{t};
    auto* a = static_cast<AAsset*>(H(kAsset, w.u32()));
    void* buf = guest_ptr(w.u32());
    return static_cast<std::uint32_t>(AAsset_read(a, buf, w.u32()));
}
std::uint64_t a_AAsset_seek(Thread& t) {
    Words w{t};
    auto* a = static_cast<AAsset*>(H(kAsset, w.u32()));
    auto offset = static_cast<std::int32_t>(w.u32());
    return static_cast<std::uint32_t>(AAsset_seek(a, offset, static_cast<int>(w.u32())));
}
std::uint64_t a_AAsset_seek64(Thread& t) {
    Words w{t};
    auto* a = static_cast<AAsset*>(H(kAsset, w.u32()));
    auto offset = static_cast<off64_t>(w.u64());
    return static_cast<std::uint64_t>(AAsset_seek64(a, offset, static_cast<int>(w.u32())));
}
std::uint64_t a_AAsset_getLength(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(AAsset_getLength(static_cast<AAsset*>(H(kAsset, w.u32()))));
}
std::uint64_t a_AAsset_getLength64(Thread& t) {
    Words w{t};
    return static_cast<std::uint64_t>(AAsset_getLength64(static_cast<AAsset*>(H(kAsset, w.u32()))));
}
std::uint64_t a_AAsset_getRemainingLength(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(AAsset_getRemainingLength(static_cast<AAsset*>(H(kAsset, w.u32()))));
}
std::uint64_t a_AAsset_getRemainingLength64(Thread& t) {
    Words w{t};
    return static_cast<std::uint64_t>(AAsset_getRemainingLength64(static_cast<AAsset*>(H(kAsset, w.u32()))));
}
std::uint64_t a_AAsset_getBuffer(Thread& t) {
    Words w{t};
    std::uint32_t h = w.u32();
    auto* a = static_cast<AAsset*>(H(kAsset, h));
    const void* data = AAsset_getBuffer(a);
    if (!data) return 0;
    return copy_for(h, data, static_cast<std::size_t>(AAsset_getLength64(a)));
}
std::uint64_t a_AAsset_openFileDescriptor(Thread& t) {
    Words w{t};
    auto* a = static_cast<AAsset*>(H(kAsset, w.u32()));
    gaddr start = w.u32(), length = w.u32();
    off_t s = 0, n = 0;
    int fd = AAsset_openFileDescriptor(a, &s, &n);
    if (start) *gmem().ptr<std::int32_t>(start) = static_cast<std::int32_t>(s);
    if (length) *gmem().ptr<std::int32_t>(length) = static_cast<std::int32_t>(n);
    return static_cast<std::uint32_t>(fd);
}
std::uint64_t a_AAsset_openFileDescriptor64(Thread& t) {
    Words w{t};
    auto* a = static_cast<AAsset*>(H(kAsset, w.u32()));
    auto* start = ptr<off64_t>(w.u32());
    auto* length = ptr<off64_t>(w.u32());
    return static_cast<std::uint32_t>(AAsset_openFileDescriptor64(a, start, length));
}

// ---- configuration

std::uint64_t a_AConfiguration_new(Thread&) { return PUT(kConfiguration, AConfiguration_new()); }
std::uint64_t a_AConfiguration_delete(Thread& t) {
    Words w{t};
    std::uint32_t h = w.u32();
    AConfiguration_delete(static_cast<AConfiguration*>(H(kConfiguration, h)));
    handles().drop(HandleKind::kConfiguration, h);
    return 0;
}
std::uint64_t a_AConfiguration_fromAssetManager(Thread& t) {
    Words w{t};
    auto* c = static_cast<AConfiguration*>(H(kConfiguration, w.u32()));
    AConfiguration_fromAssetManager(c, static_cast<AAssetManager*>(H(kAssetManager, w.u32())));
    return 0;
}
std::uint64_t a_AConfiguration_getDensity(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(AConfiguration_getDensity(static_cast<AConfiguration*>(H(kConfiguration, w.u32()))));
}
std::uint64_t a_AConfiguration_getOrientation(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(AConfiguration_getOrientation(static_cast<AConfiguration*>(H(kConfiguration, w.u32()))));
}
std::uint64_t a_AConfiguration_getLanguage(Thread& t) {
    Words w{t};
    auto* c = static_cast<AConfiguration*>(H(kConfiguration, w.u32()));
    AConfiguration_getLanguage(c, ptr<char>(w.u32()));
    return 0;
}
std::uint64_t a_AConfiguration_getCountry(Thread& t) {
    Words w{t};
    auto* c = static_cast<AConfiguration*>(H(kConfiguration, w.u32()));
    AConfiguration_getCountry(c, ptr<char>(w.u32()));
    return 0;
}

// ---- input events (pointers the host handed out before)

std::uint64_t a_AInputEvent_getType(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(AInputEvent_getType(static_cast<AInputEvent*>(H(kInputEvent, w.u32()))));
}
std::uint64_t a_AInputEvent_getDeviceId(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(AInputEvent_getDeviceId(static_cast<AInputEvent*>(H(kInputEvent, w.u32()))));
}
std::uint64_t a_AKeyEvent_getAction(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(AKeyEvent_getAction(static_cast<AInputEvent*>(H(kInputEvent, w.u32()))));
}
std::uint64_t a_AKeyEvent_getKeyCode(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(AKeyEvent_getKeyCode(static_cast<AInputEvent*>(H(kInputEvent, w.u32()))));
}
std::uint64_t a_AKeyEvent_getMetaState(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(AKeyEvent_getMetaState(static_cast<AInputEvent*>(H(kInputEvent, w.u32()))));
}

// ---- loopers

std::uint64_t a_ALooper_forThread(Thread&) { return PUT(kLooper, ALooper_forThread()); }
std::uint64_t a_ALooper_prepare(Thread& t) {
    Words w{t};
    return PUT(kLooper, ALooper_prepare(static_cast<int>(w.u32())));
}

// ---- native windows

std::uint64_t a_ANativeWindow_fromSurface(Thread& t) {
    Words w{t};
    w.u32();
    ANativeWindow* win = ANativeWindow_fromSurface(jni_env(), jni_object(w.u32()));
    return PUT(kWindow, win);
}
std::uint64_t a_ANativeWindow_acquire(Thread& t) {
    Words w{t};
    ANativeWindow_acquire(static_cast<ANativeWindow*>(H(kWindow, w.u32())));
    return 0;
}
std::uint64_t a_ANativeWindow_release(Thread& t) {
    Words w{t};
    // The handle stays: the window may still be referenced by others.
    ANativeWindow_release(static_cast<ANativeWindow*>(H(kWindow, w.u32())));
    return 0;
}
std::uint64_t a_ANativeWindow_getWidth(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(ANativeWindow_getWidth(static_cast<ANativeWindow*>(H(kWindow, w.u32()))));
}
std::uint64_t a_ANativeWindow_getHeight(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(ANativeWindow_getHeight(static_cast<ANativeWindow*>(H(kWindow, w.u32()))));
}
std::uint64_t a_ANativeWindow_setBuffersGeometry(Thread& t) {
    Words w{t};
    auto* win = static_cast<ANativeWindow*>(H(kWindow, w.u32()));
    auto width = static_cast<int32_t>(w.u32());
    auto height = static_cast<int32_t>(w.u32());
    return static_cast<std::uint32_t>(ANativeWindow_setBuffersGeometry(win, width, height, static_cast<int32_t>(w.u32())));
}

// ---- sensors. ASensorEvent has no pointers and the same layout on 32 and 64 bits.

std::uint64_t a_ASensorManager_getInstance(Thread&) {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    return PUT(kSensorManager, ASensorManager_getInstance());
#pragma clang diagnostic pop
}
std::uint64_t a_ASensorManager_getSensorList(Thread& t) {
    Words w{t};
    auto* m = static_cast<ASensorManager*>(H(kSensorManager, w.u32()));
    gaddr out = w.u32();
    ASensorList list = nullptr;
    int n = ASensorManager_getSensorList(m, &list);
    if (n < 0) return static_cast<std::uint32_t>(n);
    // The guest gets an array of sensor handles in long-lived memory.
    gaddr array = arena_alloc(static_cast<std::size_t>(n) * 4 + 4);
    for (int i = 0; i < n; ++i) *gmem().ptr<std::uint32_t>(array + static_cast<gaddr>(i) * 4) = PUT(kSensor, list[i]);
    if (out) *gmem().ptr<std::uint32_t>(out) = array;
    return static_cast<std::uint32_t>(n);
}
std::uint64_t a_ASensorManager_getDefaultSensor(Thread& t) {
    Words w{t};
    auto* m = static_cast<ASensorManager*>(H(kSensorManager, w.u32()));
    return PUT(kSensor, ASensorManager_getDefaultSensor(m, static_cast<int>(w.u32())));
}
std::uint64_t a_ASensorManager_createEventQueue(Thread& t) {
    Words w{t};
    auto* m = static_cast<ASensorManager*>(H(kSensorManager, w.u32()));
    auto* looper = static_cast<ALooper*>(H(kLooper, w.u32()));
    auto ident = static_cast<int>(w.u32());
    gaddr callback = w.u32();
    // A callback would be guest code run by the looper; queues are polled instead.
    if (callback) log("arm32: sensor queue callback ignored");
    return PUT(kSensorQueue, ASensorManager_createEventQueue(m, looper, ident, nullptr, nullptr));
}
std::uint64_t a_ASensorManager_destroyEventQueue(Thread& t) {
    Words w{t};
    auto* m = static_cast<ASensorManager*>(H(kSensorManager, w.u32()));
    std::uint32_t q = w.u32();
    int r = ASensorManager_destroyEventQueue(m, static_cast<ASensorEventQueue*>(H(kSensorQueue, q)));
    handles().drop(HandleKind::kSensorQueue, q);
    return static_cast<std::uint32_t>(r);
}
std::uint64_t a_ASensorEventQueue_enableSensor(Thread& t) {
    Words w{t};
    auto* q = static_cast<ASensorEventQueue*>(H(kSensorQueue, w.u32()));
    return static_cast<std::uint32_t>(ASensorEventQueue_enableSensor(q, static_cast<const ASensor*>(H(kSensor, w.u32()))));
}
std::uint64_t a_ASensorEventQueue_disableSensor(Thread& t) {
    Words w{t};
    auto* q = static_cast<ASensorEventQueue*>(H(kSensorQueue, w.u32()));
    return static_cast<std::uint32_t>(ASensorEventQueue_disableSensor(q, static_cast<const ASensor*>(H(kSensor, w.u32()))));
}
std::uint64_t a_ASensorEventQueue_setEventRate(Thread& t) {
    Words w{t};
    auto* q = static_cast<ASensorEventQueue*>(H(kSensorQueue, w.u32()));
    auto* s = static_cast<const ASensor*>(H(kSensor, w.u32()));
    return static_cast<std::uint32_t>(ASensorEventQueue_setEventRate(q, s, static_cast<int32_t>(w.u32())));
}
std::uint64_t a_ASensorEventQueue_hasEvents(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(ASensorEventQueue_hasEvents(static_cast<ASensorEventQueue*>(H(kSensorQueue, w.u32()))));
}
std::uint64_t a_ASensorEventQueue_getEvents(Thread& t) {
    static_assert(sizeof(ASensorEvent) == 104, "ASensorEvent must keep its 32-bit layout");
    Words w{t};
    auto* q = static_cast<ASensorEventQueue*>(H(kSensorQueue, w.u32()));
    auto* events = ptr<ASensorEvent>(w.u32());
    return static_cast<std::uint32_t>(ASensorEventQueue_getEvents(q, events, w.u32()));
}
std::uint64_t a_ASensor_getName(Thread& t) {
    Words w{t};
    return arena_strdup(ASensor_getName(static_cast<const ASensor*>(H(kSensor, w.u32()))));
}
std::uint64_t a_ASensor_getVendor(Thread& t) {
    Words w{t};
    return arena_strdup(ASensor_getVendor(static_cast<const ASensor*>(H(kSensor, w.u32()))));
}
std::uint64_t a_ASensor_getType(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(ASensor_getType(static_cast<const ASensor*>(H(kSensor, w.u32()))));
}
std::uint64_t a_ASensor_getResolution(Thread& t) {
    Words w{t};
    return float_bits(ASensor_getResolution(static_cast<const ASensor*>(H(kSensor, w.u32()))));
}
std::uint64_t a_ASensor_getMinDelay(Thread& t) {
    Words w{t};
    return static_cast<std::uint32_t>(ASensor_getMinDelay(static_cast<const ASensor*>(H(kSensor, w.u32()))));
}

}  // namespace

void android_register() {
#define R(name) register_host_fn(kAndroid_##name, &a_##name)
    R(AAssetManager_fromJava);
    R(AAssetManager_open);
    R(AAssetManager_openDir);
    R(AAssetDir_getNextFileName);
    R(AAssetDir_close);
    R(AAsset_close);
    R(AAsset_read);
    R(AAsset_seek);
    R(AAsset_seek64);
    R(AAsset_getLength);
    R(AAsset_getLength64);
    R(AAsset_getRemainingLength);
    R(AAsset_getRemainingLength64);
    R(AAsset_getBuffer);
    R(AAsset_openFileDescriptor);
    R(AAsset_openFileDescriptor64);
    R(AConfiguration_new);
    R(AConfiguration_delete);
    R(AConfiguration_fromAssetManager);
    R(AConfiguration_getDensity);
    R(AConfiguration_getOrientation);
    R(AConfiguration_getLanguage);
    R(AConfiguration_getCountry);
    R(AInputEvent_getType);
    R(AInputEvent_getDeviceId);
    R(AKeyEvent_getAction);
    R(AKeyEvent_getKeyCode);
    R(AKeyEvent_getMetaState);
    R(ALooper_forThread);
    R(ALooper_prepare);
    R(ANativeWindow_fromSurface);
    R(ANativeWindow_acquire);
    R(ANativeWindow_release);
    R(ANativeWindow_getWidth);
    R(ANativeWindow_getHeight);
    R(ANativeWindow_setBuffersGeometry);
    R(ASensorManager_getInstance);
    R(ASensorManager_getSensorList);
    R(ASensorManager_getDefaultSensor);
    R(ASensorManager_createEventQueue);
    R(ASensorManager_destroyEventQueue);
    R(ASensorEventQueue_enableSensor);
    R(ASensorEventQueue_disableSensor);
    R(ASensorEventQueue_setEventRate);
    R(ASensorEventQueue_hasEvents);
    R(ASensorEventQueue_getEvents);
    R(ASensor_getName);
    R(ASensor_getVendor);
    R(ASensor_getType);
    R(ASensor_getResolution);
    R(ASensor_getMinDelay);
#undef R
}

}  // namespace arm32
