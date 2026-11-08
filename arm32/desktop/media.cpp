// android.media's video path, as Unity's VideoPlayer takes it when the phone's NDK media library is not there (the
// player has none, so it goes through JNI): MediaExtractor reads an MP4's samples (mp4.h), MediaCodec decodes them on a
// thread of its own with the computer's decoder (decoder.h), and a frame the game renders goes to its SurfaceTexture,
// which puts the latest into the game's GL texture when the game calls updateTexImage on its render thread. That
// texture is an external image (GL_TEXTURE_EXTERNAL_OES), which no upload can fill: the picture goes into a texture of
// the player's, and an EGL image of that texture is what the game's texture shows. MediaFormat carries the formats.
#include "decoder.h"
#include "gl_bridge.h"
#include "host.h"
#include "mp4.h"
#include "player.h"

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>
#include <algorithm>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <dlfcn.h>
#include <fcntl.h>
#include <map>
#include <mutex>
#include <optional>
#include <set>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>

namespace player {


namespace {

using jvm::Call;
using jvm::Class;
using jvm::Object;
using jvm::Ref;
using jvm::Value;

// ---------------------------------------------------------------------------------------------------------------------
// android.media.MediaFormat: keys and values of a few kinds.

class Format : public Object {
public:
    using Object::Object;
    // A value and its kind: 'I' int, 'J' long, 'F' float, 'S' string, 'B' a ByteBuffer.
    struct Entry {
        char kind;
        Value value;
    };
    std::mutex lock;
    std::map<std::string, Entry> entries;
    void set(const std::string& key, char kind, Value v) {
        std::lock_guard<std::mutex> l(lock);
        entries[key] = Entry{kind, std::move(v)};
    }
    std::optional<Entry> get(const std::string& key) {
        std::lock_guard<std::mutex> l(lock);
        auto it = entries.find(key);
        if (it == entries.end()) return std::nullopt;
        return it->second;
    }
};

Class* g_format = nullptr;

Ref<Format> new_format() { return Ref<Format>(new Format(g_format)); }

// A ByteBuffer of its own holding `bytes`, as the extractor's csd-0 and csd-1.
Ref<jvm::Buffer> buffer_of(const std::vector<std::uint8_t>& bytes) {
    Ref<jvm::Buffer> b = jvm::new_buffer(bytes.size());
    if (!bytes.empty()) std::memcpy(b->address, bytes.data(), bytes.size());
    return b;
}

void define_format() {
    Class& c = jvm::define("android/media/MediaFormat");
    g_format = &c;
    c.make = [](Class& k) -> Object* { return new Format(&k); };
    c.method("<init>", "()V", [](Call&) { return Value(); });
    // A value of the kind asked for, as Java's unboxing finds it: a key that is not there is a NullPointerException,
    // one of another kind a ClassCastException.
    auto typed = [](Call& c, char kind) -> Format::Entry {
        std::optional<Format::Entry> e = c.self_as<Format>().get(c.str(0));
        if (!e) jvm::throw_new("java/lang/NullPointerException", "no " + c.str(0) + " in the format");
        if (e->kind != kind) jvm::throw_new("java/lang/ClassCastException", c.str(0) + " is of another type");
        return *e;
    };
    c.method("getInteger", "(Ljava/lang/String;)I", [typed](Call& c) { return typed(c, 'I').value; });
    c.method("getLong", "(Ljava/lang/String;)J", [typed](Call& c) { return typed(c, 'J').value; });
    c.method("getFloat", "(Ljava/lang/String;)F", [typed](Call& c) { return typed(c, 'F').value; });
    c.method("getInteger", "(Ljava/lang/String;I)I", [](Call& c) {
        std::optional<Format::Entry> e = c.self_as<Format>().get(c.str(0));
        return e && e->kind == 'I' ? e->value : Value::I(c.i(1));
    });
    // Strings and buffers are null when missing.
    c.method("getString", "(Ljava/lang/String;)Ljava/lang/String;", [](Call& c) {
        std::optional<Format::Entry> e = c.self_as<Format>().get(c.str(0));
        return e && e->kind == 'S' ? e->value : Value();
    });
    c.method("getByteBuffer", "(Ljava/lang/String;)Ljava/nio/ByteBuffer;", [](Call& c) {
        std::optional<Format::Entry> e = c.self_as<Format>().get(c.str(0));
        return e && e->kind == 'B' ? e->value : Value();
    });
    c.method("containsKey", "(Ljava/lang/String;)Z", [](Call& c) { return Value::Z(c.self_as<Format>().get(c.str(0)).has_value()); });
    c.method("setInteger", "(Ljava/lang/String;I)V", [](Call& c) {
        c.self_as<Format>().set(c.str(0), 'I', Value::I(c.i(1)));
        return Value();
    });
    c.method("setLong", "(Ljava/lang/String;J)V", [](Call& c) {
        c.self_as<Format>().set(c.str(0), 'J', Value::J(c.j(1)));
        return Value();
    });
    c.method("setFloat", "(Ljava/lang/String;F)V", [](Call& c) {
        c.self_as<Format>().set(c.str(0), 'F', Value::F(c.f(1)));
        return Value();
    });
    c.method("setString", "(Ljava/lang/String;Ljava/lang/String;)V", [](Call& c) {
        c.self_as<Format>().set(c.str(0), 'S', Value(c.l(1)));
        return Value();
    });
    c.method("setByteBuffer", "(Ljava/lang/String;Ljava/nio/ByteBuffer;)V", [](Call& c) {
        c.self_as<Format>().set(c.str(0), 'B', Value(c.l(1)));
        return Value();
    });
    // As Android prints a format: {key=value, ...}.
    c.method("toString", "()Ljava/lang/String;", [](Call& c) {
        Format& f = c.self_as<Format>();
        std::lock_guard<std::mutex> l(f.lock);
        std::string out = "{";
        for (const auto& [key, e] : f.entries) {
            if (out.size() > 1) out += ", ";
            out += key + "=";
            if (e.kind == 'I') out += std::to_string(e.value.i());
            else if (e.kind == 'J') out += std::to_string(e.value.j());
            else if (e.kind == 'F') out += std::to_string(e.value.f());
            else if (e.kind == 'S') out += e.value.l() ? static_cast<jvm::String*>(e.value.l())->utf8() : "null";
            else out += "java.nio.ByteBuffer";
        }
        return Value(jvm::string(out + "}"));
    });
    c.static_method("createVideoFormat", "(Ljava/lang/String;II)Landroid/media/MediaFormat;", [](Call& c) {
        Ref<Format> f = new_format();
        f->set("mime", 'S', Value(c.l(0)));
        f->set("width", 'I', Value::I(c.i(1)));
        f->set("height", 'I', Value::I(c.i(2)));
        return Value(f);
    });
    c.static_method("createAudioFormat", "(Ljava/lang/String;II)Landroid/media/MediaFormat;", [](Call& c) {
        Ref<Format> f = new_format();
        f->set("mime", 'S', Value(c.l(0)));
        f->set("sample-rate", 'I', Value::I(c.i(1)));
        f->set("channel-count", 'I', Value::I(c.i(2)));
        return Value(f);
    });
}

// ---------------------------------------------------------------------------------------------------------------------
// android.media.MediaExtractor: an MP4's tracks, and the samples of those selected, in decoding order.

class Extractor : public Object {
public:
    using Object::Object;
    ~Extractor() override { close_fd(); }
    void close_fd() {
        if (fd >= 0) ::close(fd);
        fd = -1;
    }
    // The track of the next sample: of the selected tracks, the one whose next sample is decoded first; -1 at the end.
    int current() const {
        int best = -1;
        for (std::size_t t = 0; t < selected.size(); ++t) {
            const auto& samples = mp4.tracks()[t].samples;
            if (!selected[t] || next[t] >= samples.size()) continue;
            if (best < 0 || samples[next[t]].decode_us < mp4.tracks()[static_cast<std::size_t>(best)].samples[next[best]].decode_us) best = static_cast<int>(t);
        }
        return best;
    }
    std::mutex lock;
    media::Mp4 mp4;
    // A copy of the descriptor the game passed, which it may close once the source is set, as Android's extractor
    // keeps one.
    int fd = -1;
    std::vector<bool> selected;
    std::vector<std::size_t> next;
    std::vector<std::uint8_t> sample;
};

Extractor& extractor(Call& c) { return c.self_as<Extractor>(); }

// The source: `fd` from `offset` for `length` bytes (a length of 0 or less is the rest of the file).
void open_source(Call& c, int fd, std::int64_t offset, std::int64_t length) {
    Extractor& x = extractor(c);
    std::lock_guard<std::mutex> l(x.lock);
    x.close_fd();
    struct stat st {};
    if (fd < 0 || fstat(fd, &st) != 0) jvm::throw_new("java/io/IOException", "setDataSource: no such file");
    if (length <= 0 || offset + length > st.st_size) length = st.st_size - offset;
    x.fd = fcntl(fd, F_DUPFD_CLOEXEC, 0);
    std::string error;
    if (x.fd < 0 || !x.mp4.open(media::Source{x.fd, offset, length}, error)) {
        x.close_fd();
        jvm::log("player: video: cannot read the file: %s", error.c_str());
        jvm::throw_new("java/io/IOException", "setDataSource failed: " + error);
    }
    x.selected.assign(x.mp4.tracks().size(), false);
    x.next.assign(x.mp4.tracks().size(), 0);
    for (const media::Track& t : x.mp4.tracks())
        jvm::log("player: video: a track of %s, %dx%d %d Hz %d channels, %.2f s, %zu samples", t.mime.c_str(), t.width, t.height, t.sample_rate, t.channels,
                 static_cast<double>(t.duration_us) / 1e6, t.samples.size());
}

// The descriptor in a java.io.FileDescriptor: its "descriptor" field, as Android keeps it.
int descriptor_of(Object* o) {
    if (!o) return -1;
    jvm::Field* f = o->cls()->find_field("descriptor", false);
    return f ? o->field(f).i() : -1;
}

// java.io.FileDescriptor, and android.os.ParcelFileDescriptor, which Unity wraps the APK's descriptor in for the
// extractor (adoptFd, then getFileDescriptor).
class Parcel : public Object {
public:
    using Object::Object;
    ~Parcel() override { close_fd(); }
    void close_fd() {
        if (fd >= 0 && owned) ::close(fd);
        fd = -1;
    }
    int fd = -1;
    // adoptFd takes the descriptor over and closes it with the parcel; fromFd and dup work on a copy of their own.
    bool owned = true;
    Ref<Object> descriptor;
};

Class* g_file_descriptor = nullptr;
Class* g_parcel = nullptr;

Ref<Parcel> new_parcel(int fd) {
    Ref<Parcel> p(new Parcel(g_parcel));
    p->fd = fd;
    // Its FileDescriptor names the same descriptor.
    p->descriptor = Ref<Object>(jvm::new_object(*g_file_descriptor, "()V"));
    p->descriptor->set_field(g_file_descriptor->find_field("descriptor", false), Value::I(fd));
    return p;
}

void define_descriptors() {
    Class& f = jvm::define("java/io/FileDescriptor");
    g_file_descriptor = &f;
    f.field("descriptor", "I");
    f.method("<init>", "()V", [](Call& c) {
        c.self->set_field(c.self->cls()->find_field("descriptor", false), Value::I(-1));
        return Value();
    });
    f.method("valid", "()Z", [](Call& c) { return Value::Z(descriptor_of(c.self) >= 0); });
    Class& p = jvm::define("android/os/ParcelFileDescriptor");
    g_parcel = &p;
    p.make = [](Class& k) -> Object* { return new Parcel(&k); };
    p.static_method("adoptFd", "(I)Landroid/os/ParcelFileDescriptor;", [](Call& c) { return Value(new_parcel(c.i(0))); });
    p.static_method("fromFd", "(I)Landroid/os/ParcelFileDescriptor;", [](Call& c) {
        int copy = fcntl(c.i(0), F_DUPFD_CLOEXEC, 0);
        if (copy < 0) jvm::throw_new("java/io/IOException", "fromFd: not a descriptor");
        return Value(new_parcel(copy));
    });
    p.method("getFd", "()I", [](Call& c) { return Value::I(c.self_as<Parcel>().fd); });
    p.method("getFileDescriptor", "()Ljava/io/FileDescriptor;", [](Call& c) { return Value(c.self_as<Parcel>().descriptor); });
    // detachFd: the caller owns the descriptor from now on.
    p.method("detachFd", "()I", [](Call& c) {
        Parcel& parcel = c.self_as<Parcel>();
        parcel.owned = false;
        return Value::I(parcel.fd);
    });
    p.method("close", "()V", [](Call& c) {
        c.self_as<Parcel>().close_fd();
        return Value();
    });
}

void define_extractor() {
    Class& c = jvm::define("android/media/MediaExtractor");
    c.make = [](Class& k) -> Object* { return new Extractor(&k); };
    c.static_field("SEEK_TO_PREVIOUS_SYNC", "I", Value::I(0));
    c.static_field("SEEK_TO_NEXT_SYNC", "I", Value::I(1));
    c.static_field("SEEK_TO_CLOSEST_SYNC", "I", Value::I(2));
    c.static_field("SAMPLE_FLAG_SYNC", "I", Value::I(1));
    c.method("<init>", "()V", [](Call&) { return Value(); });
    c.method("setDataSource", "(Ljava/io/FileDescriptor;JJ)V", [](Call& c) {
        open_source(c, descriptor_of(c.l(0)), c.j(1), c.j(2));
        return Value();
    });
    c.method("setDataSource", "(Ljava/io/FileDescriptor;)V", [](Call& c) {
        open_source(c, descriptor_of(c.l(0)), 0, 0);
        return Value();
    });
    // A path the guest names: where it is on this computer.
    c.method("setDataSource", "(Ljava/lang/String;)V", [](Call& c) {
        std::string path = host_of(c.str(0));
        int fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
        if (fd < 0) jvm::throw_new("java/io/IOException", "setDataSource: cannot open " + c.str(0));
        open_source(c, fd, 0, 0);
        ::close(fd);
        return Value();
    });
    c.method("getTrackCount", "()I", [](Call& c) {
        Extractor& x = extractor(c);
        std::lock_guard<std::mutex> l(x.lock);
        return Value::I(static_cast<jint>(x.mp4.tracks().size()));
    });
    c.method("getTrackFormat", "(I)Landroid/media/MediaFormat;", [](Call& c) {
        Extractor& x = extractor(c);
        std::lock_guard<std::mutex> l(x.lock);
        if (c.i(0) < 0 || static_cast<std::size_t>(c.i(0)) >= x.mp4.tracks().size()) jvm::throw_new("java/lang/IllegalArgumentException", "no such track");
        const media::Track& t = x.mp4.tracks()[static_cast<std::size_t>(c.i(0))];
        // The keys Android's MP4 extractor gives a track.
        Ref<Format> f = new_format();
        f->set("mime", 'S', Value(jvm::string(t.mime)));
        f->set("durationUs", 'J', Value::J(t.duration_us));
        f->set("max-input-size", 'I', Value::I(static_cast<jint>(x.mp4.max_read_size(static_cast<std::size_t>(c.i(0))))));
        if (t.width) {
            f->set("width", 'I', Value::I(t.width));
            f->set("height", 'I', Value::I(t.height));
        }
        if (t.sample_rate) {
            f->set("sample-rate", 'I', Value::I(t.sample_rate));
            f->set("channel-count", 'I', Value::I(t.channels));
        }
        if (!t.csd0.empty()) f->set("csd-0", 'B', Value(buffer_of(t.csd0)));
        if (!t.csd1.empty()) f->set("csd-1", 'B', Value(buffer_of(t.csd1)));
        return Value(f);
    });
    auto select = [](bool on) {
        return [on](Call& c) {
            Extractor& x = extractor(c);
            std::lock_guard<std::mutex> l(x.lock);
            if (c.i(0) < 0 || static_cast<std::size_t>(c.i(0)) >= x.selected.size()) jvm::throw_new("java/lang/IllegalArgumentException", "no such track");
            x.selected[static_cast<std::size_t>(c.i(0))] = on;
            return Value();
        };
    };
    c.method("selectTrack", "(I)V", select(true));
    c.method("unselectTrack", "(I)V", select(false));
    // The current sample into the buffer at `offset`; its size, or -1 past the last. The buffer's position and limit
    // then frame it, as on Android 5 and later.
    c.method("readSampleData", "(Ljava/nio/ByteBuffer;I)I", [](Call& c) {
        Extractor& x = extractor(c);
        auto* b = c.as<jvm::Buffer>(0);
        std::lock_guard<std::mutex> l(x.lock);
        int t = x.current();
        if (t < 0 || !b) return Value::I(-1);
        if (!x.mp4.read(static_cast<std::size_t>(t), x.next[static_cast<std::size_t>(t)], x.sample)) return Value::I(-1);
        if (c.i(1) < 0 || static_cast<jlong>(c.i(1)) + static_cast<jlong>(x.sample.size()) > b->capacity)
            jvm::throw_new("java/lang/IllegalArgumentException", "the sample does not fit the buffer");
        std::memcpy(static_cast<std::uint8_t*>(b->address) + c.i(1), x.sample.data(), x.sample.size());
        b->position = c.i(1);
        b->limit = c.i(1) + static_cast<jint>(x.sample.size());
        return Value::I(static_cast<jint>(x.sample.size()));
    });
    c.method("getSampleTime", "()J", [](Call& c) {
        Extractor& x = extractor(c);
        std::lock_guard<std::mutex> l(x.lock);
        int t = x.current();
        return Value::J(t < 0 ? -1 : x.mp4.tracks()[static_cast<std::size_t>(t)].samples[x.next[static_cast<std::size_t>(t)]].time_us);
    });
    c.method("getSampleTrackIndex", "()I", [](Call& c) {
        Extractor& x = extractor(c);
        std::lock_guard<std::mutex> l(x.lock);
        return Value::I(x.current());
    });
    c.method("getSampleFlags", "()I", [](Call& c) {
        Extractor& x = extractor(c);
        std::lock_guard<std::mutex> l(x.lock);
        int t = x.current();
        return Value::I(t >= 0 && x.mp4.tracks()[static_cast<std::size_t>(t)].samples[x.next[static_cast<std::size_t>(t)]].sync ? 1 : 0);
    });
    c.method("advance", "()Z", [](Call& c) {
        Extractor& x = extractor(c);
        std::lock_guard<std::mutex> l(x.lock);
        int t = x.current();
        if (t < 0) return Value::Z(false);
        ++x.next[static_cast<std::size_t>(t)];
        return Value::Z(x.current() >= 0);
    });
    // Each selected track to a key frame near `time` (before it, after it, or the closest), as the mode says; a track
    // with no key frames (audio: all of them are) to its sample at or before the time.
    c.method("seekTo", "(JI)V", [](Call& c) {
        Extractor& x = extractor(c);
        std::lock_guard<std::mutex> l(x.lock);
        const std::int64_t time = c.j(0);
        const jint mode = c.i(1);
        for (std::size_t t = 0; t < x.selected.size(); ++t) {
            if (!x.selected[t]) continue;
            const auto& samples = x.mp4.tracks()[t].samples;
            std::optional<std::size_t> before, after;
            for (std::size_t k = 0; k < samples.size(); ++k) {
                if (!samples[k].sync) continue;
                if (samples[k].time_us <= time) before = k;
                if (samples[k].time_us >= time && !after) after = k;
            }
            std::size_t to = 0;
            if (mode == 1) to = after ? *after : (before ? *before : 0);
            else if (mode == 2 && before && after) to = time - samples[*before].time_us <= samples[*after].time_us - time ? *before : *after;
            else to = before ? *before : (after ? *after : 0);
            x.next[t] = to;
        }
        return Value();
    });
    c.method("release", "()V", [](Call& c) {
        Extractor& x = extractor(c);
        std::lock_guard<std::mutex> l(x.lock);
        x.close_fd();
        return Value();
    });
    c.method("getCachedDuration", "()J", [](Call&) { return Value::J(-1); });
    c.method("hasCacheReachedEndOfStream", "()Z", [](Call&) { return Value::Z(true); });
}

// ---------------------------------------------------------------------------------------------------------------------
// android.graphics.SurfaceTexture: the latest frame rendered to it, which updateTexImage puts in the game's texture.

// The host's EGL and GL functions updateTexImage uses.
struct Gl {
    PFNGLGENTEXTURESPROC gen_textures = nullptr;
    PFNGLDELETETEXTURESPROC delete_textures = nullptr;
    PFNGLBINDTEXTUREPROC bind_texture = nullptr;
    PFNGLTEXIMAGE2DPROC tex_image = nullptr;
    PFNGLTEXSUBIMAGE2DPROC tex_sub_image = nullptr;
    PFNGLTEXPARAMETERIPROC tex_parameter = nullptr;
    PFNGLGETINTEGERVPROC get_integer = nullptr;
    PFNGLPIXELSTOREIPROC pixel_store = nullptr;
    PFNGLGETSTRINGPROC get_string = nullptr;
    PFNGLBINDBUFFERPROC bind_buffer = nullptr;
    PFNGLEGLIMAGETARGETTEXTURE2DOESPROC image_target = nullptr;
    PFNEGLGETCURRENTDISPLAYPROC current_display = nullptr;
    PFNEGLGETCURRENTCONTEXTPROC current_context = nullptr;
    PFNEGLCREATEIMAGEKHRPROC create_image = nullptr;
    PFNEGLDESTROYIMAGEKHRPROC destroy_image = nullptr;
    bool ok = false;
};

const Gl& gl() {
    static const Gl g = [] {
        Gl g;
        auto get = [](const char* name, auto& fn) { fn = reinterpret_cast<std::remove_reference_t<decltype(fn)>>(arm32::gl_proc(name)); };
        get("glGenTextures", g.gen_textures);
        get("glDeleteTextures", g.delete_textures);
        get("glBindTexture", g.bind_texture);
        get("glTexImage2D", g.tex_image);
        get("glTexSubImage2D", g.tex_sub_image);
        get("glTexParameteri", g.tex_parameter);
        get("glGetIntegerv", g.get_integer);
        get("glPixelStorei", g.pixel_store);
        get("glGetString", g.get_string);
        get("glBindBuffer", g.bind_buffer);
        get("glEGLImageTargetTexture2DOES", g.image_target);
        // EGL's own functions from its library; the image ones are extensions.
        void* egl = dlopen(arm32::kHostEgl, RTLD_NOW | RTLD_LOCAL);
        auto egl_get = [egl](const char* name, auto& fn) {
            void* f = egl ? dlsym(egl, name) : nullptr;
            static auto proc = egl ? reinterpret_cast<void* (*)(const char*)>(dlsym(egl, "eglGetProcAddress")) : nullptr;
            if (!f && proc) f = proc(name);
            fn = reinterpret_cast<std::remove_reference_t<decltype(fn)>>(f);
        };
        egl_get("eglGetCurrentDisplay", g.current_display);
        egl_get("eglGetCurrentContext", g.current_context);
        egl_get("eglCreateImageKHR", g.create_image);
        egl_get("eglDestroyImageKHR", g.destroy_image);
        g.ok = g.gen_textures && g.delete_textures && g.bind_texture && g.tex_image && g.tex_sub_image && g.tex_parameter && g.get_integer &&
               g.pixel_store && g.get_string && g.bind_buffer && g.image_target && g.current_display && g.current_context && g.create_image && g.destroy_image;
        if (!g.ok) jvm::log("player: video: the computer's GL has no EGL images for external textures: no video");
        return g;
    }();
    return g;
}

class Texture : public Object {
public:
    using Object::Object;
    // The game's texture.
    jint name = 0;
    std::mutex lock;
    Ref<Object> listener;
    // The frame rendered last, not yet in the texture, and its time.
    media::Frame pending;
    bool fresh = false;
    std::int64_t pending_ns = 0, timestamp_ns = 0;
    // The player's texture behind the game's, its EGL image, and the context they belong to: the render thread's.
    GLuint plane = 0;
    EGLImageKHR image = EGL_NO_IMAGE_KHR;
    EGLContext context = EGL_NO_CONTEXT;
    int width = 0, height = 0;
    // A frame rendered to the texture (MediaCodec.releaseOutputBuffer with render): kept, and the listener told.
    void post(media::Frame&& p, std::int64_t time_ns) {
        Ref<Object> who;
        {
            std::lock_guard<std::mutex> l(lock);
            pending = std::move(p);
            pending_ns = time_ns;
            fresh = true;
            who = listener;
        }
        if (who) {
            jvm::Env& e = jvm::attach();
            e.call(who.get(), "onFrameAvailable", "(Landroid/graphics/SurfaceTexture;)V", {Value(this)});
            if (e.pending) {
                jvm::log("player: video: onFrameAvailable threw %s", e.pending->cls()->name.c_str());
                e.pending = {};
            }
        }
    }
    // The pending frame into the game's texture, in the current context; the GL state the game had is put back.
    void update() {
        std::lock_guard<std::mutex> l(lock);
        if (!fresh) return;
        fresh = false;
        timestamp_ns = pending_ns;
        const Gl& g = gl();
        if (!g.ok) return;
        EGLDisplay display = g.current_display();
        EGLContext now = g.current_context();
        if (now == EGL_NO_CONTEXT || pending.rgba.empty()) return;
        // What the game had bound and set for uploads, and an unpack buffer of OpenGL ES 3's, which an upload would
        // read from instead of memory.
        static const bool es3 = [&g] {
            const auto* v = reinterpret_cast<const char*>(g.get_string(GL_VERSION));
            return v && std::strncmp(v, "OpenGL ES 3", 11) == 0;
        }();
        GLint was_2d = 0, was_external = 0, alignment = 4, row_length = 0, skip_rows = 0, skip_pixels = 0, unpack = 0;
        g.get_integer(GL_TEXTURE_BINDING_2D, &was_2d);
        g.get_integer(GL_TEXTURE_BINDING_EXTERNAL_OES, &was_external);
        g.get_integer(GL_UNPACK_ALIGNMENT, &alignment);
        if (es3) {
            g.get_integer(0x0CF2 /* GL_UNPACK_ROW_LENGTH */, &row_length);
            g.get_integer(0x0CF3 /* GL_UNPACK_SKIP_ROWS */, &skip_rows);
            g.get_integer(0x0CF4 /* GL_UNPACK_SKIP_PIXELS */, &skip_pixels);
            g.get_integer(0x88EF /* GL_PIXEL_UNPACK_BUFFER_BINDING */, &unpack);
            g.pixel_store(0x0CF2, 0);
            g.pixel_store(0x0CF3, 0);
            g.pixel_store(0x0CF4, 0);
            if (unpack) g.bind_buffer(0x88EC /* GL_PIXEL_UNPACK_BUFFER */, 0);
        }
        g.pixel_store(GL_UNPACK_ALIGNMENT, 4);
        if (!plane || context != now || width != pending.width || height != pending.height) {
            // A new size or context: a new texture of the player's, an image of it, and the game's texture on that.
            if (image != EGL_NO_IMAGE_KHR && context == now) g.destroy_image(display, image);
            if (plane && context == now) g.delete_textures(1, &plane);
            g.gen_textures(1, &plane);
            g.bind_texture(GL_TEXTURE_2D, plane);
            g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
            g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
            g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
            g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
            g.tex_image(GL_TEXTURE_2D, 0, GL_RGBA, pending.width, pending.height, 0, GL_RGBA, GL_UNSIGNED_BYTE, pending.rgba.data());
            const EGLint attrs[] = {EGL_GL_TEXTURE_LEVEL_KHR, 0, EGL_IMAGE_PRESERVED_KHR, EGL_TRUE, EGL_NONE};
            image = g.create_image(display, now, EGL_GL_TEXTURE_2D_KHR, reinterpret_cast<EGLClientBuffer>(static_cast<std::uintptr_t>(plane)), attrs);
            context = now;
            width = pending.width;
            height = pending.height;
            if (image == EGL_NO_IMAGE_KHR) {
                jvm::log("player: video: no EGL image of a %dx%d texture: no video", width, height);
            } else {
                g.bind_texture(GL_TEXTURE_EXTERNAL_OES, static_cast<GLuint>(name));
                g.image_target(GL_TEXTURE_EXTERNAL_OES, image);
                jvm::log("player: video: frames of %dx%d into texture %d", width, height, name);
            }
        } else {
            // The same size: the picture into the player's texture, which the game's shows.
            g.bind_texture(GL_TEXTURE_2D, plane);
            g.tex_sub_image(GL_TEXTURE_2D, 0, 0, 0, pending.width, pending.height, GL_RGBA, GL_UNSIGNED_BYTE, pending.rgba.data());
        }
        // The game's state as it was.
        g.bind_texture(GL_TEXTURE_2D, static_cast<GLuint>(was_2d));
        g.bind_texture(GL_TEXTURE_EXTERNAL_OES, static_cast<GLuint>(was_external));
        g.pixel_store(GL_UNPACK_ALIGNMENT, alignment);
        if (es3) {
            g.pixel_store(0x0CF2, row_length);
            g.pixel_store(0x0CF3, skip_rows);
            g.pixel_store(0x0CF4, skip_pixels);
            if (unpack) g.bind_buffer(0x88EC, static_cast<GLuint>(unpack));
        }
    }
};

Texture& texture(Call& c) { return c.self_as<Texture>(); }

// android.view.Surface made from a SurfaceTexture: what MediaCodec renders to.
class TextureSurface : public Object {
public:
    using Object::Object;
    Ref<Texture> texture;
};

void define_texture() {
    jvm::define_interface("android/graphics/SurfaceTexture$OnFrameAvailableListener")
        .declare("onFrameAvailable", "(Landroid/graphics/SurfaceTexture;)V");
    Class& c = jvm::define("android/graphics/SurfaceTexture");
    c.make = [](Class& k) -> Object* { return new Texture(&k); };
    auto init = [](Call& c) {
        texture(c).name = c.i(0);
        return Value();
    };
    c.method("<init>", "(I)V", init);
    c.method("<init>", "(IZ)V", init);
    auto listen = [](Call& c) {
        Texture& t = texture(c);
        std::lock_guard<std::mutex> l(t.lock);
        t.listener = Ref<Object>(c.l(0));
        return Value();
    };
    c.method("setOnFrameAvailableListener", "(Landroid/graphics/SurfaceTexture$OnFrameAvailableListener;)V", listen);
    c.method("setOnFrameAvailableListener", "(Landroid/graphics/SurfaceTexture$OnFrameAvailableListener;Landroid/os/Handler;)V", listen);
    c.method("updateTexImage", "()V", [](Call& c) {
        texture(c).update();
        return Value();
    });
    // The pictures' rows come from the top, and texture coordinates count from the bottom: the matrix turns them
    // over, as a phone's decoder output asks.
    c.method("getTransformMatrix", "([F)V", [](Call& c) {
        auto* a = c.as<jvm::Array>(0);
        if (!a || a->length < 16) jvm::throw_new("java/lang/IllegalArgumentException", "the matrix needs 16 floats");
        static const jfloat kFlip[16] = {1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1, 0, 0, 1, 0, 1};
        std::memcpy(a->data<jfloat>(), kFlip, sizeof kFlip);
        return Value();
    });
    c.method("getTimestamp", "()J", [](Call& c) {
        Texture& t = texture(c);
        std::lock_guard<std::mutex> l(t.lock);
        return Value::J(t.timestamp_ns);
    });
    c.method("attachToGLContext", "(I)V", [](Call& c) {
        Texture& t = texture(c);
        std::lock_guard<std::mutex> l(t.lock);
        t.name = c.i(0);
        // The image goes on the new texture with the next frame.
        t.context = EGL_NO_CONTEXT;
        return Value();
    });
    for (const char* name : {"detachFromGLContext", "release", "releaseTexImage"}) c.method(name, "()V", [](Call&) { return Value(); });
    c.method("setDefaultBufferSize", "(II)V", [](Call&) { return Value(); });

    Class& s = jvm::define("android/view/Surface");
    s.make = [](Class& k) -> Object* { return new TextureSurface(&k); };
    s.method("<init>", "(Landroid/graphics/SurfaceTexture;)V", [](Call& c) {
        auto* t = c.as<Texture>(0);
        if (!t) jvm::throw_new("java/lang/IllegalArgumentException", "no SurfaceTexture");
        c.self_as<TextureSurface>().texture = Ref<Texture>(t);
        return Value();
    });
    s.method("isValid", "()Z", [](Call&) { return Value::Z(true); });
    s.method("release", "()V", [](Call&) { return Value(); });
}

// ---------------------------------------------------------------------------------------------------------------------
// android.media.MediaCodec, its synchronous API of Android 4.1: the game dequeues an input buffer, fills and queues it,
// and dequeues output buffers, which it releases to its surface. A thread of the codec's own decodes, as a phone's
// codec runs apart from the game's thread.

// MediaCodec's numbers.
constexpr jint kTryAgainLater = -1, kOutputFormatChanged = -2;
constexpr jint kFlagKeyFrame = 1, kFlagCodecConfig = 2, kFlagEndOfStream = 4;
// Its buffers: as many as a phone's software decoder has; a sound buffer holds a few AAC frames (2048 samples each at
// most, with HE-AAC) of up to eight channels.
constexpr std::size_t kInputs = 4, kOutputs = 4, kSoundBuffer = 65536;

class Codec : public Object {
public:
    using Object::Object;
    ~Codec() override { stop(); }
    struct Packet {
        std::vector<std::uint8_t> data;
        std::int64_t time_us = 0;
        jint flags = 0;
    };
    struct Output {
        media::Frame frame;
        std::int64_t time_us = 0;
        bool end = false;
    };

    void start() {
        std::lock_guard<std::mutex> l(lock);
        if (running) return;
        running = true;
        worker = std::thread([this] { decode_loop(); });
    }
    void stop() {
        {
            std::lock_guard<std::mutex> l(lock);
            running = false;
        }
        changed.notify_all();
        if (worker.joinable()) worker.join();
        std::lock_guard<std::mutex> l(lock);
        clear();
    }
    // Everything queued, decoded or held goes (flush, stop): the next input starts again from a key frame.
    void clear() {
        packets.clear();
        ready.clear();
        for (auto& h : held) h.reset();
        times.clear();
        std::fill(input_out.begin(), input_out.end(), false);
        input_ended = end_told = false;
        flush_decoder = true;
    }

    void decode_loop() {
        name_thread(audio ? "audio decoder" : "video decoder");
        jvm::attach();
        std::unique_lock<std::mutex> l(lock);
        while (running) {
            if (flush_decoder && decoder) {
                decoder->flush();
                flush_decoder = false;
                config_sent = false;
            }
            if (packets.empty()) {
                changed.wait(l);
                continue;
            }
            Packet p = std::move(packets.front());
            packets.pop_front();
            // H.264's parameter sets go in front of the first unit after a start or a flush: alone they are nothing
            // the decoder can show. Audio's setup opened the decoder and is no data.
            if (!audio && !config_sent && !config.empty() && !p.data.empty()) {
                p.data.insert(p.data.begin(), config.begin(), config.end());
                config_sent = true;
            }
            if (!p.data.empty()) times.insert(p.time_us);
            // Decoding without the lock: the game's thread queues and dequeues meanwhile.
            busy = true;
            l.unlock();
            std::vector<media::Frame> frames;
            if (decoder) {
                if (!p.data.empty()) decoder->send(p.data.data(), p.data.size());
                if (p.flags & kFlagEndOfStream) decoder->drain();
                for (media::Frame f; decoder->receive(f);) frames.push_back(std::move(f));
            }
            l.lock();
            busy = false;
            // A flush while decoding: what came out belongs to before it.
            if (flush_decoder) continue;
            for (media::Frame& f : frames) {
                // Frames come out in display order: each takes the earliest time not yet given out.
                std::int64_t t = times.empty() ? last_time : *times.begin();
                if (!times.empty()) times.erase(times.begin());
                last_time = t;
                if (!audio) {
                    width = f.width;
                    height = f.height;
                } else {
                    rate = f.rate;
                    channels = f.channels;
                }
                ready.push_back(Output{std::move(f), t, false});
                ++decoded;
            }
            if (p.flags & kFlagEndOfStream) input_ended = true;
            changed.notify_all();
        }
    }

    std::mutex lock;
    std::condition_variable changed;
    std::thread worker;
    bool running = false, busy = false, flush_decoder = false;
    std::string mime;
    // A sound decoder: its output is in its buffers, for the game to read, rather than on a surface.
    bool audio = false;
    std::unique_ptr<media::Decoder> decoder;
    Ref<Texture> texture;
    std::vector<Ref<jvm::Buffer>> inputs, outputs;
    std::vector<bool> input_out = std::vector<bool>(kInputs, false);
    std::deque<Packet> packets;
    std::deque<Output> ready;
    std::optional<Output> held[kOutputs];
    std::multiset<std::int64_t> times;
    std::int64_t last_time = 0;
    std::vector<std::uint8_t> config;
    bool config_sent = false, format_told = false, input_ended = false, end_told = false;
    int width = 0, height = 0, rate = 0, channels = 0;
    std::size_t max_input = 1 << 20;
    std::uint64_t decoded = 0, shown = 0;
};

Codec& codec(Call& c) { return c.self_as<Codec>(); }

// A wait of `timeout_us` as MediaCodec takes it: below zero for ever, zero not at all.
template <class Pred>
bool wait_for(std::unique_lock<std::mutex>& l, std::condition_variable& cv, jlong timeout_us, Pred&& ready) {
    if (timeout_us < 0) {
        cv.wait(l, ready);
        return true;
    }
    return cv.wait_for(l, std::chrono::microseconds(timeout_us), ready);
}

// The decoders the player has: H.264 for the pictures, AAC for a video's sound.
Ref<Object> new_codec(const std::string& mime) {
    if (mime != "video/avc" && mime != "audio/mp4a-latm") jvm::throw_new("java/io/IOException", "no decoder for " + mime);
    Class* cls = jvm::find_class("android/media/MediaCodec");
    Ref<Codec> c(new Codec(cls));
    c->mime = mime;
    c->audio = mime == "audio/mp4a-latm";
    return Ref<Object>(c);
}

void define_codec() {
    Class& info = jvm::define("android/media/MediaCodec$BufferInfo");
    info.field("offset", "I").field("size", "I").field("presentationTimeUs", "J").field("flags", "I");
    info.method("<init>", "()V", [](Call&) { return Value(); });
    info.method("set", "(IIJI)V", [](Call& c) {
        Class* k = c.self->cls();
        c.self->set_field(k->find_field("offset", false), Value::I(c.i(0)));
        c.self->set_field(k->find_field("size", false), Value::I(c.i(1)));
        c.self->set_field(k->find_field("presentationTimeUs", false), Value::J(c.j(2)));
        c.self->set_field(k->find_field("flags", false), Value::I(c.i(3)));
        return Value();
    });

    Class& c = jvm::define("android/media/MediaCodec");
    c.make = [](Class& k) -> Object* { return new Codec(&k); };
    c.static_field("INFO_TRY_AGAIN_LATER", "I", Value::I(kTryAgainLater));
    c.static_field("INFO_OUTPUT_FORMAT_CHANGED", "I", Value::I(kOutputFormatChanged));
    c.static_field("INFO_OUTPUT_BUFFERS_CHANGED", "I", Value::I(-3));
    c.static_field("BUFFER_FLAG_KEY_FRAME", "I", Value::I(kFlagKeyFrame));
    c.static_field("BUFFER_FLAG_SYNC_FRAME", "I", Value::I(kFlagKeyFrame));
    c.static_field("BUFFER_FLAG_CODEC_CONFIG", "I", Value::I(kFlagCodecConfig));
    c.static_field("BUFFER_FLAG_END_OF_STREAM", "I", Value::I(kFlagEndOfStream));
    c.static_field("CONFIGURE_FLAG_ENCODE", "I", Value::I(1));
    c.static_method("createDecoderByType", "(Ljava/lang/String;)Landroid/media/MediaCodec;", [](Call& c) { return Value(new_codec(c.str(0))); });
    c.static_method("createByCodecName", "(Ljava/lang/String;)Landroid/media/MediaCodec;", [](Call& c) {
        std::string name = c.str(0);
        bool video = name.find("avc") != std::string::npos || name.find("h264") != std::string::npos;
        bool aac = name.find("aac") != std::string::npos;
        return Value(new_codec(video ? "video/avc" : aac ? "audio/mp4a-latm" : name));
    });
    // The names of AOSP's software decoders for the same formats.
    c.method("getName", "()Ljava/lang/String;", [](Call& c) {
        return Value(jvm::string(codec(c).audio ? "OMX.google.aac.decoder" : "OMX.google.h264.decoder"));
    });
    // The format's size and setup, the surface to render to, and the computer's decoder.
    c.method("configure", "(Landroid/media/MediaFormat;Landroid/view/Surface;Landroid/media/MediaCrypto;I)V", [](Call& c) {
        Codec& k = codec(c);
        auto* f = c.as<Format>(0);
        if (!f) jvm::throw_new("java/lang/IllegalArgumentException", "no format");
        if (c.i(3) & 1) jvm::throw_new("java/lang/IllegalStateException", "the player has no encoders");
        std::lock_guard<std::mutex> l(k.lock);
        k.config.clear();
        for (const char* key : {"csd-0", "csd-1"}) {
            std::optional<Format::Entry> e = f->get(key);
            auto* b = e && e->kind == 'B' ? dynamic_cast<jvm::Buffer*>(e->value.l()) : nullptr;
            if (!b) continue;
            const auto* p = static_cast<const std::uint8_t*>(b->address);
            k.config.insert(k.config.end(), p + b->position, p + b->limit);
        }
        if (std::optional<Format::Entry> e = f->get("max-input-size"); e && e->kind == 'I' && e->value.i() > 0)
            k.max_input = static_cast<std::size_t>(e->value.i());
        // The size the format says, until the first picture says its own.
        if (std::optional<Format::Entry> w = f->get("width"), h = f->get("height"); w && h && w->kind == 'I' && h->kind == 'I') {
            k.width = w->value.i();
            k.height = h->value.i();
        }
        if (auto* s = c.as<TextureSurface>(1)) k.texture = s->texture;
        if (k.audio) {
            if (std::optional<Format::Entry> r = f->get("sample-rate"); r && r->kind == 'I') k.rate = r->value.i();
            if (std::optional<Format::Entry> n = f->get("channel-count"); n && n->kind == 'I') k.channels = n->value.i();
        }
        std::string error;
        // AAC's setup is its csd-0 alone.
        k.decoder = k.audio ? media::open_aac(k.config, error) : media::open_h264(error);
        if (!k.decoder) {
            // The video plays blank rather than not at all: a codec that fails to configure stops the game.
            jvm::log("player: video: %s; it plays blank", error.c_str());
            k.decoder = media::open_blank(k.audio, k.width > 0 ? k.width : 16, k.height > 0 ? k.height : 16, k.rate > 0 ? k.rate : 44100,
                                          k.channels > 0 ? k.channels : 2);
        }
        return Value();
    });
    c.method("start", "()V", [](Call& c) {
        Codec& k = codec(c);
        {
            std::lock_guard<std::mutex> l(k.lock);
            if (k.inputs.empty())
                for (std::size_t i = 0; i < kInputs; ++i) k.inputs.push_back(jvm::new_buffer(k.max_input));
        }
        k.start();
        return Value();
    });
    c.method("getInputBuffers", "()[Ljava/nio/ByteBuffer;", [](Call& c) {
        Codec& k = codec(c);
        std::lock_guard<std::mutex> l(k.lock);
        Ref<jvm::Array> a = jvm::new_array(jvm::array_class(*jvm::find_class("java/nio/ByteBuffer")), static_cast<jsize>(k.inputs.size()));
        for (std::size_t i = 0; i < k.inputs.size(); ++i) a->items[i] = Ref<Object>(k.inputs[i].get());
        return Value(a);
    });
    c.method("getInputBuffer", "(I)Ljava/nio/ByteBuffer;", [](Call& c) {
        Codec& k = codec(c);
        std::lock_guard<std::mutex> l(k.lock);
        if (c.i(0) < 0 || static_cast<std::size_t>(c.i(0)) >= k.inputs.size()) return Value();
        Ref<jvm::Buffer> b = k.inputs[static_cast<std::size_t>(c.i(0))];
        b->position = 0;
        b->limit = static_cast<jint>(b->capacity);
        return Value(b);
    });
    // Rendered to a surface, the frames are in no buffer the game reads; a phone still hands over buffers of a
    // picture's size, which Unity checks are there.
    c.method("getOutputBuffers", "()[Ljava/nio/ByteBuffer;", [](Call& c) {
        Codec& k = codec(c);
        std::lock_guard<std::mutex> l(k.lock);
        if (k.outputs.empty()) {
            std::size_t size = k.audio ? kSoundBuffer : static_cast<std::size_t>(std::max(k.width, 16)) * static_cast<std::size_t>(std::max(k.height, 16)) * 3 / 2;
            for (std::size_t i = 0; i < kOutputs; ++i) k.outputs.push_back(jvm::new_buffer(size));
        }
        Ref<jvm::Array> a = jvm::new_array(jvm::array_class(*jvm::find_class("java/nio/ByteBuffer")), static_cast<jsize>(kOutputs));
        for (std::size_t i = 0; i < kOutputs; ++i) a->items[i] = Ref<Object>(k.outputs[i].get());
        return Value(a);
    });
    c.method("getOutputBuffer", "(I)Ljava/nio/ByteBuffer;", [](Call& c) {
        Codec& k = codec(c);
        std::lock_guard<std::mutex> l(k.lock);
        return c.i(0) >= 0 && static_cast<std::size_t>(c.i(0)) < k.outputs.size() ? Value(k.outputs[static_cast<std::size_t>(c.i(0))]) : Value();
    });
    // A free input buffer, once the decoder is not too far ahead of what the game takes out.
    c.method("dequeueInputBuffer", "(J)I", [](Call& c) {
        Codec& k = codec(c);
        std::unique_lock<std::mutex> l(k.lock);
        if (!k.running) jvm::throw_new("java/lang/IllegalStateException", "the codec is not started");
        auto free_input = [&k] {
            if (k.packets.size() >= kInputs || k.ready.size() >= kOutputs) return false;
            return std::find(k.input_out.begin(), k.input_out.end(), false) != k.input_out.end();
        };
        if (!wait_for(l, k.changed, c.j(0), free_input)) return Value::I(kTryAgainLater);
        std::size_t i = static_cast<std::size_t>(std::find(k.input_out.begin(), k.input_out.end(), false) - k.input_out.begin());
        k.input_out[i] = true;
        return Value::I(static_cast<jint>(i));
    });
    c.method("queueInputBuffer", "(IIIJI)V", [](Call& c) {
        Codec& k = codec(c);
        std::lock_guard<std::mutex> l(k.lock);
        std::size_t i = static_cast<std::size_t>(c.i(0));
        if (c.i(0) < 0 || i >= k.inputs.size() || !k.input_out[i]) jvm::throw_new("java/lang/IllegalStateException", "not an input buffer of the game's");
        k.input_out[i] = false;
        const jvm::Buffer& b = *k.inputs[i];
        if (c.i(1) < 0 || c.i(2) < 0 || static_cast<jlong>(c.i(1)) + c.i(2) > b.capacity) jvm::throw_new("java/lang/IllegalArgumentException", "outside the buffer");
        Codec::Packet p;
        const auto* data = static_cast<const std::uint8_t*>(b.address) + c.i(1);
        p.data.assign(data, data + c.i(2));
        p.time_us = c.j(3);
        p.flags = c.i(4);
        // Parameter sets of the game's own: they go first, as part of the setup.
        if (p.flags & kFlagCodecConfig) {
            if (!k.audio) k.config.insert(k.config.end(), p.data.begin(), p.data.end());
            k.config_sent = false;
            p.data.clear();
        }
        k.packets.push_back(std::move(p));
        k.changed.notify_all();
        return Value();
    });
    // The next decoded frame in an output buffer; first, once, that the output's format is known; at the end of the
    // stream, a buffer with only that flag.
    c.method("dequeueOutputBuffer", "(Landroid/media/MediaCodec$BufferInfo;J)I", [](Call& c) {
        Codec& k = codec(c);
        Object* info = c.l(0);
        if (!info) jvm::throw_new("java/lang/NullPointerException", "no BufferInfo");
        std::unique_lock<std::mutex> l(k.lock);
        if (!k.running) jvm::throw_new("java/lang/IllegalStateException", "the codec is not started");
        auto free_slot = [&k] {
            for (std::size_t s = 0; s < kOutputs; ++s)
                if (!k.held[s]) return static_cast<int>(s);
            return -1;
        };
        auto something = [&] { return (!k.ready.empty() || (k.input_ended && !k.end_told)) && free_slot() >= 0; };
        if (!wait_for(l, k.changed, c.j(1), something)) return Value::I(kTryAgainLater);
        if (!k.format_told && !k.ready.empty()) {
            k.format_told = true;
            return Value::I(kOutputFormatChanged);
        }
        int s = free_slot();
        Codec::Output out;
        if (!k.ready.empty()) {
            out = std::move(k.ready.front());
            k.ready.pop_front();
        } else {
            out.end = true;
            out.time_us = k.last_time;
            k.end_told = true;
        }
        Class* ic = info->cls();
        jint size = 0;
        if (out.end) {
            size = 0;
        } else if (k.audio) {
            // Sound goes in the buffer, where the game reads it; more than the buffer holds would be cut off there.
            if (k.outputs.size() == kOutputs) {
                std::size_t bytes = std::min(out.frame.pcm.size() * sizeof(std::int16_t), static_cast<std::size_t>(k.outputs[static_cast<std::size_t>(s)]->capacity));
                std::memcpy(k.outputs[static_cast<std::size_t>(s)]->address, out.frame.pcm.data(), bytes);
                size = static_cast<jint>(bytes);
            }
        } else {
            // A picture's buffer would hold it as YUV on a phone; the size says so.
            size = out.frame.width * out.frame.height * 3 / 2;
        }
        info->set_field(ic->find_field("offset", false), Value::I(0));
        info->set_field(ic->find_field("size", false), Value::I(size));
        info->set_field(ic->find_field("presentationTimeUs", false), Value::J(out.time_us));
        info->set_field(ic->find_field("flags", false), Value::I(out.end ? kFlagEndOfStream : 0));
        k.held[s] = std::move(out);
        k.changed.notify_all();
        return Value::I(s);
    });
    // An output buffer back from the game: its frame to the surface if it says so.
    auto release = [](Call& c, bool render, std::int64_t time_ns) {
        Codec& k = codec(c);
        std::optional<Codec::Output> out;
        Ref<Texture> to;
        {
            std::lock_guard<std::mutex> l(k.lock);
            std::size_t s = static_cast<std::size_t>(c.i(0));
            if (c.i(0) < 0 || s >= kOutputs || !k.held[s]) jvm::throw_new("java/lang/IllegalStateException", "not an output buffer of the game's");
            out.swap(k.held[s]);
            to = k.texture;
            k.changed.notify_all();
            if (render && to && !out->end) ++k.shown;
        }
        if (render && to && !out->end) to->post(std::move(out->frame), time_ns >= 0 ? time_ns : out->time_us * 1000);
        return Value();
    };
    c.method("releaseOutputBuffer", "(IZ)V", [release](Call& c) { return release(c, c.z(1), -1); });
    c.method("releaseOutputBuffer", "(IJ)V", [release](Call& c) { return release(c, true, c.j(1)); });
    c.method("getOutputFormat", "()Landroid/media/MediaFormat;", [](Call& c) {
        Codec& k = codec(c);
        std::lock_guard<std::mutex> l(k.lock);
        Ref<Format> f = new_format();
        if (k.audio) {
            // What a phone's AAC decoder says: 16-bit PCM at the stream's rate and channels.
            f->set("mime", 'S', Value(jvm::string("audio/raw")));
            f->set("sample-rate", 'I', Value::I(k.rate));
            f->set("channel-count", 'I', Value::I(k.channels));
            f->set("pcm-encoding", 'I', Value::I(2));
            return Value(f);
        }
        // What a phone's decoder rendering to a surface says: the size, the whole picture as its crop, and the
        // surface's own colour format.
        f->set("mime", 'S', Value(jvm::string("video/raw")));
        f->set("width", 'I', Value::I(k.width));
        f->set("height", 'I', Value::I(k.height));
        f->set("stride", 'I', Value::I(k.width));
        f->set("slice-height", 'I', Value::I(k.height));
        f->set("crop-left", 'I', Value::I(0));
        f->set("crop-top", 'I', Value::I(0));
        f->set("crop-right", 'I', Value::I(k.width - 1));
        f->set("crop-bottom", 'I', Value::I(k.height - 1));
        f->set("color-format", 'I', Value::I(0x7F000789));
        return Value(f);
    });
    c.method("flush", "()V", [](Call& c) {
        Codec& k = codec(c);
        std::unique_lock<std::mutex> l(k.lock);
        // Not in the middle of a picture: the decoder is the worker's while it decodes.
        k.changed.wait(l, [&k] { return !k.busy; });
        k.clear();
        k.changed.notify_all();
        return Value();
    });
    auto halt = [](Call& c) {
        Codec& k = codec(c);
        k.stop();
        std::lock_guard<std::mutex> l(k.lock);
        if (k.audio) jvm::log("player: video: %llu frames of its sound decoded", static_cast<unsigned long long>(k.decoded));
        else jvm::log("player: video: %llu frames decoded, %llu shown", static_cast<unsigned long long>(k.decoded), static_cast<unsigned long long>(k.shown));
        return Value();
    };
    c.method("stop", "()V", halt);
    c.method("release", "()V", [halt](Call& c) {
        halt(c);
        Codec& k = codec(c);
        std::lock_guard<std::mutex> l(k.lock);
        k.decoder.reset();
        return Value();
    });
}

}  // namespace

void define_media() {
    define_descriptors();
    define_format();
    define_extractor();
    define_texture();
    define_codec();
}

}  // namespace player
