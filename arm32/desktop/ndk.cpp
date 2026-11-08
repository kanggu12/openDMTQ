// The NDK functions the runtime's Android bridge (android_bridge.cpp) calls, for a desktop host, where there is no
// libandroid: the bridge stays as it is on a phone, and what it reaches is this.
//   - Assets: the APK's assets/ folder, read from the zip itself (stored entries straight from a mapping of the file,
//     deflated ones inflated when opened), and file descriptors for stored entries, as Android gives them.
//   - The window: an ANativeWindow is the player's window handle itself (an X11 window), which is what EGL takes.
//   - The configuration (language, density, orientation), loopers, and the sensors this computer does not have.
#include "player.h"

#include <android/asset_manager.h>
#include <android/asset_manager_jni.h>
#include <android/configuration.h>
#include <android/input.h>
#include <android/looper.h>
#include <android/native_window_jni.h>
#include <android/sensor.h>

#include <cstring>
#include <fcntl.h>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>
#include <zlib.h>

namespace {

// ---------------------------------------------------------------------------------------------------------------------
// The APK as a zip: its entries under assets/, by name.

struct Entry {
    std::uint16_t method = 0;          // 0 stored, 8 deflated
    std::uint64_t offset = 0;          // where the entry's data starts in the file
    std::uint64_t size = 0;            // its length once inflated
    std::uint64_t compressed = 0;      // its length in the file
    std::uint32_t crc = 0;             // the CRC-32 of its content, as the zip's directory gives it
};

struct Apk {
    int fd = -1;
    const std::uint8_t* map = nullptr;
    std::size_t length = 0;
    // Every file entry by its full name ("assets/bin/Data/..."): assets are those under assets/.
    std::map<std::string, Entry> entries;
};

std::uint16_t u16(const std::uint8_t* p) { return static_cast<std::uint16_t>(p[0] | p[1] << 8); }
std::uint32_t u32(const std::uint8_t* p) { return static_cast<std::uint32_t>(p[0] | p[1] << 8 | p[2] << 16 | static_cast<std::uint32_t>(p[3]) << 24); }

// Reads the central directory once: the end record (within the last 64 KB, after the comment), then each entry, then
// each one's local header for where its data starts.
Apk& apk() {
    static Apk a;
    static std::once_flag once;
    std::call_once(once, [] {
        const std::string& path = player::app().host_apk;
        a.fd = open(path.c_str(), O_RDONLY | O_CLOEXEC);
        struct stat st;
        if (a.fd < 0 || fstat(a.fd, &st) != 0 || st.st_size < 22) {
            jvm::log("player: cannot read the APK %s", path.c_str());
            return;
        }
        a.length = static_cast<std::size_t>(st.st_size);
        void* m = mmap(nullptr, a.length, PROT_READ, MAP_SHARED, a.fd, 0);
        if (m == MAP_FAILED) return;
        a.map = static_cast<const std::uint8_t*>(m);
        std::size_t end = 0;
        for (std::size_t at = a.length - 22;; --at) {
            if (u32(a.map + at) == 0x06054b50) {
                end = at;
                break;
            }
            if (at == 0 || a.length - at > 65535 + 22) break;
        }
        if (!end) {
            jvm::log("player: %s is not a zip file", path.c_str());
            return;
        }
        std::size_t count = u16(a.map + end + 10), dir = u32(a.map + end + 16);
        for (std::size_t i = 0, at = dir; i < count && at + 46 <= a.length && u32(a.map + at) == 0x02014b50; ++i) {
            const std::uint8_t* h = a.map + at;
            std::size_t name_len = u16(h + 28), extra_len = u16(h + 30), comment_len = u16(h + 32);
            std::string name(reinterpret_cast<const char*>(h + 46), name_len);
            Entry e;
            e.method = u16(h + 10);
            e.crc = u32(h + 16);
            e.compressed = u32(h + 20);
            e.size = u32(h + 24);
            std::uint64_t local = u32(h + 42);
            // The local header has its own name and extra field lengths: the data follows them.
            if (local + 30 <= a.length && u32(a.map + local) == 0x04034b50) {
                e.offset = local + 30 + u16(a.map + local + 26) + u16(a.map + local + 28);
                if (!name.empty() && name.back() != '/' && e.offset + e.compressed <= a.length) a.entries.emplace(name, e);
            }
            at += 46 + name_len + extra_len + comment_len;
        }
    });
    return a;
}

}  // namespace

// The NDK's opaque types, as this file makes them.
struct AAssetManager {};
struct AAsset {
    const Entry* entry;
    // A deflated entry's contents, inflated when it is opened; a stored one is read from the mapping.
    std::vector<std::uint8_t> inflated;
    std::uint64_t pos = 0;
    const std::uint8_t* data() const { return entry->method == 0 ? apk().map + entry->offset : inflated.data(); }
};
struct AAssetDir {
    std::vector<std::string> names;
    std::size_t next = 0;
};
struct AConfiguration {
    char language[2] = {'e', 'n'};
    char country[2] = {'U', 'S'};
    int32_t density = ACONFIGURATION_DENSITY_XHIGH;
    int32_t orientation = ACONFIGURATION_ORIENTATION_LAND;
};
struct ALooper {};
struct ASensorManager {};
struct ASensorEventQueue {};

namespace {
// A deflated entry's contents, inflated; false when they will not inflate.
bool inflate_entry(const Entry& e, std::vector<std::uint8_t>& out) {
    out.resize(e.size);
    z_stream z{};
    z.next_in = const_cast<Bytef*>(apk().map + e.offset);
    z.avail_in = static_cast<uInt>(e.compressed);
    z.next_out = out.data();
    z.avail_out = static_cast<uInt>(out.size());
    // Raw deflate, as zip entries hold it (no zlib header).
    bool ok = inflateInit2(&z, -MAX_WBITS) == Z_OK && inflate(&z, Z_FINISH) == Z_STREAM_END;
    inflateEnd(&z);
    return ok;
}

// One asset manager, one sensor manager and one sensor queue: there is one APK and no sensor.
AAssetManager g_assets;
ASensorManager g_sensors;
ASensorEventQueue g_queue;
}  // namespace

extern "C" {

AAssetManager* AAssetManager_fromJava(JNIEnv*, jobject) { return &g_assets; }

AAsset* AAssetManager_open(AAssetManager*, const char* filename, int) {
    if (!filename) return nullptr;
    auto it = apk().entries.find(std::string("assets/") + filename);
    if (it == apk().entries.end()) return nullptr;
    auto a = std::make_unique<AAsset>();
    a->entry = &it->second;
    if (it->second.method == 8) {
        // Inflated whole: assets are opened to be read through, and most are small.
        if (!inflate_entry(it->second, a->inflated)) {
            jvm::log("player: cannot inflate the asset %s", filename);
            return nullptr;
        }
    } else if (it->second.method != 0) {
        return nullptr;
    }
    return a.release();
}

AAssetDir* AAssetManager_openDir(AAssetManager*, const char* dir) {
    // The files directly in that folder (Android lists no subfolders).
    std::string prefix = std::string("assets/") + (dir && *dir ? std::string(dir) + "/" : "");
    auto d = std::make_unique<AAssetDir>();
    for (auto& [name, e] : apk().entries) {
        if (name.compare(0, prefix.size(), prefix) == 0 && name.find('/', prefix.size()) == std::string::npos) d->names.push_back(name.substr(prefix.size()));
    }
    return d.release();
}

const char* AAssetDir_getNextFileName(AAssetDir* d) { return d && d->next < d->names.size() ? d->names[d->next++].c_str() : nullptr; }
void AAssetDir_rewind(AAssetDir* d) {
    if (d) d->next = 0;
}
void AAssetDir_close(AAssetDir* d) { delete d; }

int AAsset_read(AAsset* a, void* buf, size_t count) {
    if (!a) return -1;
    std::uint64_t left = a->entry->size - a->pos;
    std::size_t n = static_cast<std::size_t>(std::min<std::uint64_t>(count, left));
    std::memcpy(buf, a->data() + a->pos, n);
    a->pos += n;
    return static_cast<int>(n);
}

off64_t AAsset_seek64(AAsset* a, off64_t offset, int whence) {
    if (!a) return -1;
    off64_t base = whence == SEEK_SET ? 0 : whence == SEEK_CUR ? static_cast<off64_t>(a->pos) : static_cast<off64_t>(a->entry->size);
    off64_t to = base + offset;
    if (to < 0 || to > static_cast<off64_t>(a->entry->size)) return -1;
    a->pos = static_cast<std::uint64_t>(to);
    return to;
}
off_t AAsset_seek(AAsset* a, off_t offset, int whence) { return static_cast<off_t>(AAsset_seek64(a, offset, whence)); }

void AAsset_close(AAsset* a) { delete a; }
const void* AAsset_getBuffer(AAsset* a) { return a ? a->data() : nullptr; }
off_t AAsset_getLength(AAsset* a) { return a ? static_cast<off_t>(a->entry->size) : 0; }
off64_t AAsset_getLength64(AAsset* a) { return a ? static_cast<off64_t>(a->entry->size) : 0; }
off_t AAsset_getRemainingLength(AAsset* a) { return a ? static_cast<off_t>(a->entry->size - a->pos) : 0; }
off64_t AAsset_getRemainingLength64(AAsset* a) { return a ? static_cast<off64_t>(a->entry->size - a->pos) : 0; }

// A file descriptor of the APK with where the entry is in it: only for stored entries, as on Android (the video
// plugin hands it to the decoder this way).
int AAsset_openFileDescriptor64(AAsset* a, off64_t* start, off64_t* length) {
    if (!a || a->entry->method != 0) return -1;
    int fd = open(player::app().host_apk.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    *start = static_cast<off64_t>(a->entry->offset);
    *length = static_cast<off64_t>(a->entry->size);
    return fd;
}
int AAsset_openFileDescriptor(AAsset* a, off_t* start, off_t* length) {
    off64_t s = 0, n = 0;
    int fd = AAsset_openFileDescriptor64(a, &s, &n);
    *start = static_cast<off_t>(s);
    *length = static_cast<off_t>(n);
    return fd;
}
int AAsset_isAllocated(AAsset* a) { return a && a->entry->method != 0; }

// ---------------------------------------------------------------------------------------------------------------------
// The configuration: the language and country of the computer (player::host_locale), a high density, landscape.

AConfiguration* AConfiguration_new() {
    auto* c = new AConfiguration;
    const auto [lang, country] = player::host_locale();
    // Two letters each, as the configuration keeps them (a three-letter language keeps English).
    if (lang.size() == 2 && country.size() == 2) {
        c->language[0] = lang[0];
        c->language[1] = lang[1];
        c->country[0] = country[0];
        c->country[1] = country[1];
    }
    return c;
}
void AConfiguration_delete(AConfiguration* c) { delete c; }
void AConfiguration_fromAssetManager(AConfiguration*, AAssetManager*) {}
void AConfiguration_getLanguage(AConfiguration* c, char* out) { std::memcpy(out, c->language, 2); }
void AConfiguration_getCountry(AConfiguration* c, char* out) { std::memcpy(out, c->country, 2); }
int32_t AConfiguration_getDensity(AConfiguration* c) { return c->density; }
int32_t AConfiguration_getOrientation(AConfiguration* c) { return c->orientation; }

// ---------------------------------------------------------------------------------------------------------------------
// Input events: none reach the game through an input queue here (the player injects Java events), so nothing calls
// these with an event of its own.

int32_t AInputEvent_getType(const AInputEvent*) { return 0; }
int32_t AInputEvent_getDeviceId(const AInputEvent*) { return 0; }
int32_t AKeyEvent_getAction(const AInputEvent*) { return 0; }
int32_t AKeyEvent_getKeyCode(const AInputEvent*) { return 0; }
int32_t AKeyEvent_getMetaState(const AInputEvent*) { return 0; }

// A looper per thread, for code that only asks for one to hand on.
ALooper* ALooper_prepare(int) {
    thread_local ALooper looper;
    return &looper;
}
ALooper* ALooper_forThread() { return ALooper_prepare(0); }

// ---------------------------------------------------------------------------------------------------------------------
// The window: the Surface object the player hands the game names it.

ANativeWindow* ANativeWindow_fromSurface(JNIEnv*, jobject surface) { return reinterpret_cast<ANativeWindow*>(player::window_of(jvm::Env::deref(surface))); }
void ANativeWindow_acquire(ANativeWindow*) {}
void ANativeWindow_release(ANativeWindow*) {}
int32_t ANativeWindow_getWidth(ANativeWindow*) { return player::app().width; }
int32_t ANativeWindow_getHeight(ANativeWindow*) { return player::app().height; }
// The size the game asks its buffers to be: EGL draws at the window's size on this host, whatever is asked.
int32_t ANativeWindow_setBuffersGeometry(ANativeWindow*, int32_t, int32_t, int32_t) { return 0; }

// ---------------------------------------------------------------------------------------------------------------------
// Sensors: none.

ASensorManager* ASensorManager_getInstance() { return &g_sensors; }
int ASensorManager_getSensorList(ASensorManager*, ASensorList* list) {
    if (list) *list = nullptr;
    return 0;
}
ASensor const* ASensorManager_getDefaultSensor(ASensorManager*, int) { return nullptr; }
ASensorEventQueue* ASensorManager_createEventQueue(ASensorManager*, ALooper*, int, ALooper_callbackFunc, void*) { return &g_queue; }
int ASensorManager_destroyEventQueue(ASensorManager*, ASensorEventQueue*) { return 0; }
int ASensorEventQueue_enableSensor(ASensorEventQueue*, ASensor const*) { return -1; }
int ASensorEventQueue_disableSensor(ASensorEventQueue*, ASensor const*) { return -1; }
int ASensorEventQueue_setEventRate(ASensorEventQueue*, ASensor const*, int32_t) { return -1; }
int ASensorEventQueue_hasEvents(ASensorEventQueue*) { return 0; }
ssize_t ASensorEventQueue_getEvents(ASensorEventQueue*, ASensorEvent*, size_t) { return 0; }
const char* ASensor_getName(ASensor const*) { return ""; }
const char* ASensor_getVendor(ASensor const*) { return ""; }
int ASensor_getType(ASensor const*) { return 0; }
float ASensor_getResolution(ASensor const*) { return 0; }
int ASensor_getMinDelay(ASensor const*) { return 0; }

}  // extern "C"

namespace player {

std::vector<std::string> apk_names(const std::string& prefix) {
    std::vector<std::string> out;
    // The entries are kept by name: those under the prefix lie together from its first.
    for (auto it = apk().entries.lower_bound(prefix); it != apk().entries.end() && it->first.compare(0, prefix.size(), prefix) == 0; ++it)
        out.push_back(it->first);
    return out;
}

std::string apk_stamp(const std::string& name) {
    auto it = apk().entries.find(name);
    if (it == apk().entries.end()) return {};
    char buf[48];
    std::snprintf(buf, sizeof buf, "%08x %llu", static_cast<unsigned>(it->second.crc), static_cast<unsigned long long>(it->second.size));
    return buf;
}

bool apk_entry(const std::string& name, std::vector<std::uint8_t>& out) {
    auto it = apk().entries.find(name);
    if (it == apk().entries.end()) return false;
    if (it->second.method == 8) return inflate_entry(it->second, out);
    if (it->second.method != 0) return false;
    const std::uint8_t* p = apk().map + it->second.offset;
    out.assign(p, p + it->second.size);
    return true;
}

}  // namespace player
