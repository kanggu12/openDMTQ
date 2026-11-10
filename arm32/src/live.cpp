// Live view: the game's picture and sound sent to the server while the server's owner has it on for
// this player. It is off by default, and nothing here may ever get in the way of the game: a broadcast
// may stutter or stop, the game may not.
//
// What runs where:
//
// - The render thread, at each swap (live_frame): with live view off, one atomic load. With it on,
//   a picture is due 30 times a second: it scales the finished frame into a small texture with one
//   GPU blit, leaves a fence behind it and goes on. It never waits for anything. When both textures
//   are still waiting for the encoder, that picture is skipped.
// - Each audio thread, at each buffer it hands to the system (live_audio): a copy into its ring buffer,
//   dropped when full. Nothing is copied with live view off.
// - The encoder thread: an EGL context of its own, sharing textures with the game's, draws each
//   picture onto the input surface of a hardware H.264 encoder, so no pixel passes through the CPU.
//   It also mixes the rings for a hardware AAC encoder and packs both into MPEG-TS segments (live_ts.cpp), cut
//   at a key frame every two seconds or so. Only this thread can block on the encoder.
// - The upload thread: posts the segments, a few at a time at most; a slow network drops segments
//   rather than holding on to them, and turns the quality down (below). It and the requests are
//   live_net.cpp's, which the player for Windows shares.
// - The control thread: asks the server about every 15 seconds, while the game is on screen, whether
//   live view is on for this player, and shows the server's two-line notice as a toast.
//
// Quality steps down by itself, on a slow upload or a warm phone: frame rate and bitrate first, then
// the picture's height. A height change means a new encoder, so its segments restart at 0, which is
// how the server's playlist knows to mark a discontinuity. The same goes for coming back from a pause.
//
// The server's address comes from the packer's tweaks file (a line "server <host[:port]>", read here;
// tweaks.cpp only takes lines of five fields). Requests are plain HTTP, like the game's own: this
// runtime has no TLS, and the game's RPC, with its session, already goes the same way.
//
// debug.arm32.live 0 turns it all off; debug.arm32.liveserver <host:port> asks another server (with
// adb reverse, a test server on the computer).
#include "live.h"

#include "host.h"
#include "live_net.h"
#include "live_ts.h"

#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <algorithm>
#include <android/native_window.h>
#include <atomic>
#include <csignal>
#include <cstring>
#include <dlfcn.h>
#include <fstream>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <sstream>
#include <sys/resource.h>
#include <sys/system_properties.h>
#include <system_error>
#include <thread>
#include <time.h>
#include <unistd.h>

namespace arm32 {

namespace {

using Nanos = std::int64_t;
constexpr Nanos kSecond = 1000000000;
// How often the control thread asks the server.
constexpr Nanos kPollEvery = 15 * kSecond;
// No swap for this long: the game is away, so nothing is sent and the server is not asked.
constexpr Nanos kAwayAfter = 5 * kSecond;
// No picture for this long (a pause, a load): the stream starts over from a new first segment.
constexpr Nanos kRestartAfter = 3 * kSecond;
// The stream's sound: 48 kHz stereo, as AAC at this bitrate whatever the picture's step is.
constexpr int kAudioRate = 48000;
constexpr int kAudioChunk = 1024;
// How much of each source is kept in hand: mixers deliver in bursts, and an empty round is a click.
constexpr Nanos kAudioDelay = 150000000;
// The mix's level: the game's two outputs together go past full scale, and clipping is what ears notice.
constexpr double kMixGain = 0.75;
constexpr int kAudioBitrate = 128000;
// A frame this much earlier than due still counts: frames come with some jitter around the display's
// beat, and without this the 30 pictures a second of a 60 fps game would come unevenly.
constexpr Nanos kCaptureTolerance = 4000000;

Nanos now_ns() {
    timespec t{};
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * kSecond + t.tv_nsec;
}

void sleep_ns(Nanos n) {
    timespec t{static_cast<time_t>(n / kSecond), static_cast<long>(n % kSecond)};
    nanosleep(&t, nullptr);
}

// These threads have nothing to do with the guest's signals, and start at low priority: when the
// phone is short of CPU, the game comes first.
void background_thread(const char* name) {
    sigset_t all;
    sigfillset(&all);
    pthread_sigmask(SIG_BLOCK, &all, nullptr);
    pthread_setname_np(pthread_self(), name);
    setpriority(PRIO_PROCESS, static_cast<id_t>(gettid()), 10);
}

// ---- system libraries, found at run time: the app also starts on phones without them

struct AMediaCodec;
struct AMediaFormat;
// As NdkMediaCodec.h has it.
struct CodecBufferInfo {
    std::int32_t offset, size;
    std::int64_t pts_us;
    std::uint32_t flags;
};
constexpr std::uint32_t kFlagKeyFrame = 1, kFlagCodecConfig = 2;
constexpr std::uint32_t kConfigureEncode = 1;
constexpr int kMediaOk = 0;
// AMEDIA_ERROR_BASE: a dequeue's answer at or below this is the codec's error (NdkMediaError.h), where -1 is "nothing
// yet" and -2 and -3 news of the format and buffers.
constexpr ssize_t kMediaErrorBase = -10000;
// AMEDIACODEC_ERROR_INSUFFICIENT_RESOURCE and AMEDIACODEC_ERROR_RECLAIMED (NdkMediaError.h): the codec's errors too, from
// Android 9 on, for a codec the system ran short for or took back, and positive, so that they would pass for a buffer.
constexpr ssize_t kCodecNoResource = 1100, kCodecReclaimed = 1101;

// A dequeue's answer that is the codec's error, not a buffer, nothing yet or news.
bool codec_error(ssize_t answer) { return answer <= kMediaErrorBase || answer == kCodecNoResource || answer == kCodecReclaimed; }
// A session that ran this long before its encoder broke was a good one: the failures in a row start over with it.
constexpr Nanos kGoodRun = 60 * kSecond;
// MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface.
constexpr int kColorFormatSurface = 0x7F000789;

struct Media {
    AMediaCodec* (*create_encoder)(const char*);
    int (*destroy)(AMediaCodec*);
    int (*configure)(AMediaCodec*, const AMediaFormat*, ANativeWindow*, void*, std::uint32_t);
    int (*start)(AMediaCodec*);
    int (*stop)(AMediaCodec*);
    int (*create_input_surface)(AMediaCodec*, ANativeWindow**);
    int (*set_parameters)(AMediaCodec*, const AMediaFormat*);
    std::uint8_t* (*input_buffer)(AMediaCodec*, std::size_t, std::size_t*);
    std::uint8_t* (*output_buffer)(AMediaCodec*, std::size_t, std::size_t*);
    ssize_t (*dequeue_input)(AMediaCodec*, std::int64_t);
    int (*queue_input)(AMediaCodec*, std::size_t, off_t, std::size_t, std::uint64_t, std::uint32_t);
    ssize_t (*dequeue_output)(AMediaCodec*, CodecBufferInfo*, std::int64_t);
    int (*release_output)(AMediaCodec*, std::size_t, bool);
    AMediaFormat* (*format_new)();
    int (*format_delete)(AMediaFormat*);
    void (*format_set_int)(AMediaFormat*, const char*, std::int32_t);
    void (*format_set_string)(AMediaFormat*, const char*, const char*);
    bool ok = false;
};

template <class T>
void look_up(void* lib, T& out, const char* name, bool& ok) {
    out = reinterpret_cast<T>(dlsym(lib, name));
    if (!out) ok = false;
}

const Media& media() {
    static const Media m = [] {
        Media x{};
        void* lib = dlopen("libmediandk.so", RTLD_NOW | RTLD_LOCAL);
        if (!lib) return x;
        bool ok = true;
        look_up(lib, x.create_encoder, "AMediaCodec_createEncoderByType", ok);
        look_up(lib, x.destroy, "AMediaCodec_delete", ok);
        look_up(lib, x.configure, "AMediaCodec_configure", ok);
        look_up(lib, x.start, "AMediaCodec_start", ok);
        look_up(lib, x.stop, "AMediaCodec_stop", ok);
        look_up(lib, x.create_input_surface, "AMediaCodec_createInputSurface", ok);
        look_up(lib, x.set_parameters, "AMediaCodec_setParameters", ok);
        look_up(lib, x.input_buffer, "AMediaCodec_getInputBuffer", ok);
        look_up(lib, x.output_buffer, "AMediaCodec_getOutputBuffer", ok);
        look_up(lib, x.dequeue_input, "AMediaCodec_dequeueInputBuffer", ok);
        look_up(lib, x.queue_input, "AMediaCodec_queueInputBuffer", ok);
        look_up(lib, x.dequeue_output, "AMediaCodec_dequeueOutputBuffer", ok);
        look_up(lib, x.release_output, "AMediaCodec_releaseOutputBuffer", ok);
        look_up(lib, x.format_new, "AMediaFormat_new", ok);
        look_up(lib, x.format_delete, "AMediaFormat_delete", ok);
        look_up(lib, x.format_set_int, "AMediaFormat_setInt32", ok);
        look_up(lib, x.format_set_string, "AMediaFormat_setString", ok);
        x.ok = ok;
        return x;
    }();
    return m;
}

struct Egl {
    EGLContext (*current_context)();
    EGLSurface (*current_surface)(EGLint);
    EGLBoolean (*query_surface)(EGLDisplay, EGLSurface, EGLint, EGLint*);
    EGLBoolean (*query_context)(EGLDisplay, EGLContext, EGLint, EGLint*);
    EGLBoolean (*choose_config)(EGLDisplay, const EGLint*, EGLConfig*, EGLint, EGLint*);
    EGLBoolean (*config_attrib)(EGLDisplay, EGLConfig, EGLint, EGLint*);
    EGLContext (*create_context)(EGLDisplay, EGLConfig, EGLContext, const EGLint*);
    EGLBoolean (*destroy_context)(EGLDisplay, EGLContext);
    EGLSurface (*create_window_surface)(EGLDisplay, EGLConfig, EGLNativeWindowType, const EGLint*);
    EGLBoolean (*destroy_surface)(EGLDisplay, EGLSurface);
    EGLBoolean (*make_current)(EGLDisplay, EGLSurface, EGLSurface, EGLContext);
    EGLBoolean (*swap)(EGLDisplay, EGLSurface);
    EGLBoolean (*release_thread)();
    EGLBoolean (*presentation_time)(EGLDisplay, EGLSurface, EGLnsecsANDROID);
    bool ok = false;
};

const Egl& egl() {
    static const Egl e = [] {
        Egl x{};
        void* lib = dlopen("libEGL.so", RTLD_NOW | RTLD_LOCAL);
        if (!lib) return x;
        bool ok = true;
        look_up(lib, x.current_context, "eglGetCurrentContext", ok);
        look_up(lib, x.current_surface, "eglGetCurrentSurface", ok);
        look_up(lib, x.query_surface, "eglQuerySurface", ok);
        look_up(lib, x.query_context, "eglQueryContext", ok);
        look_up(lib, x.choose_config, "eglChooseConfig", ok);
        look_up(lib, x.config_attrib, "eglGetConfigAttrib", ok);
        look_up(lib, x.create_context, "eglCreateContext", ok);
        look_up(lib, x.destroy_context, "eglDestroyContext", ok);
        look_up(lib, x.create_window_surface, "eglCreateWindowSurface", ok);
        look_up(lib, x.destroy_surface, "eglDestroySurface", ok);
        look_up(lib, x.make_current, "eglMakeCurrent", ok);
        look_up(lib, x.swap, "eglSwapBuffers", ok);
        look_up(lib, x.release_thread, "eglReleaseThread", ok);
        // An extension: through eglGetProcAddress.
        auto get = reinterpret_cast<void* (*)(const char*)>(dlsym(lib, "eglGetProcAddress"));
        if (get) x.presentation_time = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLSurface, EGLnsecsANDROID)>(get("eglPresentationTimeANDROID"));
        if (!x.presentation_time) ok = false;
        x.ok = ok;
        return x;
    }();
    return e;
}

struct Gl {
    void (*get_integer)(GLenum, GLint*);
    GLboolean (*is_enabled)(GLenum);
    void (*enable)(GLenum);
    void (*disable)(GLenum);
    void (*gen_textures)(GLsizei, GLuint*);
    void (*delete_textures)(GLsizei, const GLuint*);
    void (*bind_texture)(GLenum, GLuint);
    void (*tex_storage)(GLenum, GLsizei, GLenum, GLsizei, GLsizei);
    void (*tex_parameter)(GLenum, GLenum, GLint);
    void (*gen_framebuffers)(GLsizei, GLuint*);
    void (*delete_framebuffers)(GLsizei, const GLuint*);
    void (*bind_framebuffer)(GLenum, GLuint);
    void (*framebuffer_texture)(GLenum, GLenum, GLenum, GLuint, GLint);
    GLenum (*check_framebuffer)(GLenum);
    void (*blit)(GLint, GLint, GLint, GLint, GLint, GLint, GLint, GLint, GLbitfield, GLenum);
    GLsync (*fence)(GLenum, GLbitfield);
    GLenum (*client_wait)(GLsync, GLbitfield, GLuint64);
    void (*delete_sync)(GLsync);
    void (*flush)();
    bool ok = false;
};

const Gl& gl() {
    static const Gl g = [] {
        Gl x{};
        bool ok = true;
        auto get = [&](auto& out, const char* name) {
            out = reinterpret_cast<std::decay_t<decltype(out)>>(gl_proc(name));
            if (!out) ok = false;
        };
        get(x.get_integer, "glGetIntegerv");
        get(x.is_enabled, "glIsEnabled");
        get(x.enable, "glEnable");
        get(x.disable, "glDisable");
        get(x.gen_textures, "glGenTextures");
        get(x.delete_textures, "glDeleteTextures");
        get(x.bind_texture, "glBindTexture");
        get(x.tex_storage, "glTexStorage2D");
        get(x.tex_parameter, "glTexParameteri");
        get(x.gen_framebuffers, "glGenFramebuffers");
        get(x.delete_framebuffers, "glDeleteFramebuffers");
        get(x.bind_framebuffer, "glBindFramebuffer");
        get(x.framebuffer_texture, "glFramebufferTexture2D");
        get(x.check_framebuffer, "glCheckFramebufferStatus");
        get(x.blit, "glBlitFramebuffer");
        get(x.fence, "glFenceSync");
        get(x.client_wait, "glClientWaitSync");
        get(x.delete_sync, "glDeleteSync");
        get(x.flush, "glFlush");
        x.ok = ok;
        return x;
    }();
    return g;
}

// ---- state shared by the threads

std::atomic<bool> g_enabled{false};    // a server address, not turned off
JavaVM* g_vm = nullptr;
jclass g_device_class = nullptr;       // com.pmangplus.device.PPDevice
jclass g_base_class = nullptr;         // com.pmangplus.base.PPBase

std::atomic<Nanos> g_last_swap{0};     // when the game last swapped
std::atomic<bool> g_want{false};       // pictures and sound are to be sent right now (set_want)
std::atomic<bool> g_on{false};         // the server has live view on for this player
std::atomic<bool> g_gave_up{false};    // this phone cannot do it: the server is still asked, for notices
std::atomic<int> g_failures{0};        // encoders that failed in a row, to start or soon after; three end the attempts

// The requests to the server, the upload thread and the network's quality step (live_net.cpp), with the phone's names:
// its log's prefix, its User-Agent, and the names and start of its upload thread and of the thread that looks the
// server's name up.
live::Link g_link({"arm32: live", "arm32-live", "arm32-liveup", "arm32-livedns", background_thread});

// What the server asks for (the top step).
std::atomic<int> g_fps{30}, g_height{720}, g_bitrate{2000000}, g_segment{2};
// The quality step: the worse of the network's (g_link) and the phone's temperature's.
std::atomic<int> g_thermal_step{0};
constexpr int kLastStep = live::kLastStep;

int step() { return std::max(g_link.network_step.load(std::memory_order_relaxed), g_thermal_step.load(std::memory_order_relaxed)); }
int step_fps(int s) { return s == 0 ? g_fps.load() : s == 1 ? std::max(g_fps.load() * 2 / 3, 1) : std::max(g_fps.load() / 2, 1); }
int step_height(int s) { return s <= 1 ? g_height.load() : s == 2 ? g_height.load() * 3 / 4 : g_height.load() / 2; }
int step_bitrate(int s) {
    static constexpr int percent[] = {100, 60, 35, 20};
    return static_cast<int>(static_cast<std::int64_t>(g_bitrate.load()) * percent[s] / 100);
}

// For the log, once a minute while live (every ten seconds with stats on); the segments' counts are g_link's.
std::atomic<std::uint64_t> g_captures{0}, g_capture_ns{0}, g_capture_max_ns{0}, g_skipped{0}, g_audio_frames{0};

// ---- the audio: a ring per player, each with one writer (its mixer's thread) and one reader (the
// encoder thread)

constexpr std::size_t kRingBytes = 1u << 18;  // over a second of 48 kHz stereo
constexpr int kAudioSources = 4;

struct AudioSource {
    std::atomic<const void*> id{nullptr};
    std::atomic<int> rate{0}, channels{2};
    std::unique_ptr<std::uint8_t[]> ring;
    std::atomic<std::size_t> head{0}, tail{0};  // running counts of bytes in and out
    double phase = 0;                           // the encoder's place between two samples
    bool buffering = true;                      // silent until the source has built up kAudioDelay again
    std::atomic<bool> restart{false};           // a new source: the reader skips what is in the ring
    std::atomic<int> short_rounds{0}, last_have{0}, peak{0};
};
AudioSource g_sources[kAudioSources];
std::atomic<int> g_next_source{0};
std::atomic<bool> g_audio_gate{false};  // open while an encoder takes the sound

// ---- a capture session: textures shared between the render thread and the encoder thread

struct Slot {
    GLuint texture = 0;
    // 0 free, 1 holds a picture for the encoder. The render thread only takes free ones, and the
    // encoder thread only ready ones, so neither ever waits for the other.
    std::atomic<int> state{0};
    GLsync fence = nullptr;
    Nanos pts = 0;
};

struct Session {
    EGLDisplay display = EGL_NO_DISPLAY;
    EGLContext share = EGL_NO_CONTEXT;
    int width = 0, height = 0;
    Slot slots[2];
    std::atomic<bool> taken{false};   // the encoder thread has it
    std::atomic<bool> closed{false};  // and has let go of the encoder and the context again
    std::atomic<bool> stop{false};    // set by the render thread or by the encoder thread itself
    std::atomic<bool> failed{false};  // the encoder could not start or broke
};

// From the render thread to the encoder thread.
std::atomic<std::shared_ptr<Session>*> g_handoff{nullptr};

// The encoder thread's wait while broadcasts are off, which set_want ends.
std::mutex g_encoder_lock;
std::condition_variable g_encoder_wake;

// Pictures and sound wanted from now on, or not. Wanted, the encoder thread wakes from its wait. The notice goes under the
// lock, after the change: the thread looks at g_want under it before it waits, so it cannot miss it. Never on the render
// thread, which waits for nothing.
void set_want(bool want) {
    if (g_want.exchange(want) == want || !want) return;
    std::lock_guard<std::mutex> l(g_encoder_lock);
    g_encoder_wake.notify_all();
}

// ---- the encoder thread

AMediaFormat* video_format(int width, int height, int bitrate, bool baseline) {
    const Media& m = media();
    AMediaFormat* f = m.format_new();
    m.format_set_string(f, "mime", "video/avc");
    m.format_set_int(f, "width", width);
    m.format_set_int(f, "height", height);
    m.format_set_int(f, "bitrate", bitrate);
    m.format_set_int(f, "frame-rate", g_fps.load());
    m.format_set_int(f, "color-format", kColorFormatSurface);
    // Key frames are asked for by the segment clock below; this is only the encoder's own limit.
    m.format_set_int(f, "i-frame-interval", 10);
    // A background job for the codec's scheduler.
    m.format_set_int(f, "priority", 1);
    // No frame reordering: a frame's decode time is its show time, as the writer assumes.
    if (baseline) m.format_set_int(f, "profile", 1);
    return f;
}

// One running encoder pair and the segment being filled.
class Encoder {
public:
    explicit Encoder(std::shared_ptr<Session> session) : s_(std::move(session)) {}
    ~Encoder() { close_all(); }

    bool open() {
        const Media& m = media();
        const Egl& e = egl();
        const Gl& g = gl();
        // Video: the input is a surface.
        video_ = m.create_encoder("video/avc");
        if (!video_) return fail("no H.264 encoder");
        AMediaFormat* f = video_format(s_->width, s_->height, step_bitrate(step()), true);
        int r = m.configure(video_, f, nullptr, nullptr, kConfigureEncode);
        m.format_delete(f);
        if (r != kMediaOk) {
            // Some encoders will not name a profile here: their default still has no reordering at
            // a surface's real-time use on every phone seen, and players cope when it has.
            f = video_format(s_->width, s_->height, step_bitrate(step()), false);
            r = m.configure(video_, f, nullptr, nullptr, kConfigureEncode);
            m.format_delete(f);
        }
        if (r != kMediaOk) return fail("the H.264 encoder takes no such format");
        if (m.create_input_surface(video_, &window_) != kMediaOk || !window_) return fail("the encoder gives no input surface");

        // EGL: a context sharing the game's textures, drawing on that surface.
        const EGLint config_attributes[] = {EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT_KHR,
                                            EGL_SURFACE_TYPE, EGL_WINDOW_BIT, EGL_RECORDABLE_ANDROID, 1, EGL_NONE};
        EGLConfig config = nullptr;
        EGLint n = 0;
        if (!e.choose_config(s_->display, config_attributes, &config, 1, &n) || n < 1) return fail("no recordable EGL config");
        const EGLint context_attributes[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
        context_ = e.create_context(s_->display, config, s_->share, context_attributes);
        if (context_ == EGL_NO_CONTEXT) return fail("no shared EGL context");
        surface_ = e.create_window_surface(s_->display, config, window_, nullptr);
        if (surface_ == EGL_NO_SURFACE) return fail("no EGL surface on the encoder");
        if (!e.make_current(s_->display, surface_, surface_, context_)) return fail("cannot draw on the encoder");
        // Framebuffer objects do not share: one here for each shared texture, to read from.
        g.gen_framebuffers(2, read_fbo_);
        for (int i = 0; i < 2; ++i) {
            g.bind_framebuffer(GL_READ_FRAMEBUFFER, read_fbo_[i]);
            g.framebuffer_texture(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, s_->slots[i].texture, 0);
        }
        if (m.start(video_) != kMediaOk) return fail("the H.264 encoder does not start");
        video_started_ = true;
        bitrate_ = step_bitrate(step());
        open_audio();
        return true;
    }

    // One round of work; false when nothing was to be done.
    bool pump() {
        bool busy = draw_ready_pictures();
        busy |= drain_video();
        busy |= feed_audio();
        busy |= drain_audio();
        apply_step();
        return busy;
    }

    // The partial segment goes too, unless it is hardly anything.
    void finish() {
        if (segment_open_ && last_pts_us_ - segment_start_us_ > 500000) cut(last_pts_us_);
    }

private:
    bool fail(const char* what) {
        log("arm32: live: %s", what);
        s_->failed.store(true);
        return false;
    }

    void open_audio() {
        const Media& m = media();
        audio_ = m.create_encoder("audio/mp4a-latm");
        if (!audio_) {
            log("arm32: live: no AAC encoder, the stream stays silent");
            return;
        }
        AMediaFormat* f = m.format_new();
        m.format_set_string(f, "mime", "audio/mp4a-latm");
        m.format_set_int(f, "sample-rate", kAudioRate);
        m.format_set_int(f, "channel-count", 2);
        m.format_set_int(f, "bitrate", kAudioBitrate);
        // AAC-LC.
        m.format_set_int(f, "aac-profile", 2);
        m.format_set_int(f, "max-input-size", 16384);
        const int r = m.configure(audio_, f, nullptr, nullptr, kConfigureEncode);
        m.format_delete(f);
        if (r != kMediaOk || m.start(audio_) != kMediaOk) {
            log("arm32: live: no AAC encoder, the stream stays silent");
            m.destroy(audio_);
            audio_ = nullptr;
            return;
        }
        // From here on the mixers' buffers come in; what is left in the rings is from another time.
        for (AudioSource& source : g_sources) {
            source.tail.store(source.head.load());
            source.phase = 0;
            source.buffering = true;
        }
        g_audio_gate.store(true);
    }

    bool draw_ready_pictures() {
        const Egl& e = egl();
        const Gl& g = gl();
        // The older of the two first.
        int first = s_->slots[0].state.load(std::memory_order_acquire) == 1 ? 0 : -1;
        int other = s_->slots[1].state.load(std::memory_order_acquire) == 1 ? 1 : -1;
        if (first >= 0 && other >= 0 && s_->slots[1].pts < s_->slots[0].pts) std::swap(first, other);
        if (first < 0) std::swap(first, other);
        if (first < 0) return false;
        for (int i : {first, other}) {
            if (i < 0) continue;
            Slot& slot = s_->slots[i];
            // The game's blit has to be done on the GPU before reading its result.
            if (slot.fence) {
                g.client_wait(slot.fence, GL_SYNC_FLUSH_COMMANDS_BIT, 100000000);
                g.delete_sync(slot.fence);
                slot.fence = nullptr;
            }
            g.bind_framebuffer(GL_READ_FRAMEBUFFER, read_fbo_[i]);
            g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, 0);
            g.blit(0, 0, s_->width, s_->height, 0, 0, s_->width, s_->height, GL_COLOR_BUFFER_BIT, GL_NEAREST);
            e.presentation_time(s_->display, surface_, slot.pts);
            // Blocks only when the encoder has fallen behind: this thread is the one that may.
            e.swap(s_->display, surface_);
            slot.state.store(0, std::memory_order_release);
        }
        return true;
    }

    bool drain_video() {
        const Media& m = media();
        bool any = false;
        for (;;) {
            CodecBufferInfo info{};
            const ssize_t index = m.dequeue_output(video_, &info, 0);
            // Broken (a codec reclaimed by the system, a hardware fault): this session ends, and another is tried later.
            if (codec_error(index)) {
                fail("the H.264 encoder broke");
                return any;
            }
            // Nothing yet (-1), or news about the format and buffers (-2, -3).
            if (index == -2 || index == -3) continue;
            if (index < 0) return any;
            any = true;
            std::size_t capacity = 0;
            std::uint8_t* data = m.output_buffer(video_, static_cast<std::size_t>(index), &capacity);
            if (data && info.size > 0) on_video(data + info.offset, static_cast<std::size_t>(info.size), info.pts_us, info.flags);
            // A buffer the codec will not take back: broken too, whatever the number it came with (or this loop would ask
            // for the same answer for ever).
            if (m.release_output(video_, static_cast<std::size_t>(index), false) != kMediaOk) {
                fail("the H.264 encoder broke");
                return any;
            }
        }
    }

    void on_video(const std::uint8_t* data, std::size_t size, std::int64_t pts_us, std::uint32_t flags) {
        // The stream's headers come first, once: they go in front of each key frame.
        if (flags & kFlagCodecConfig) {
            config_.assign(data, data + size);
            return;
        }
        const bool key = flags & kFlagKeyFrame;
        // A stream can only start on a key frame.
        if (!segment_open_ && !key) return;
        if (!segment_open_) {
            first_pts_us_ = pts_us;
            start_segment(pts_us);
        } else if (key && pts_us - segment_start_us_ >= g_segment.load() * 1000000LL - 100000) {
            cut(pts_us);
            start_segment(pts_us);
        }
        // Time to ask for the next key frame.
        if (!sync_asked_ && pts_us - segment_start_us_ >= g_segment.load() * 1000000LL - 100000) {
            const Media& md = media();
            AMediaFormat* f = md.format_new();
            md.format_set_int(f, "request-sync", 0);
            md.set_parameters(video_, f);
            md.format_delete(f);
            sync_asked_ = true;
        }
        last_pts_us_ = pts_us;
        // An access unit delimiter, the headers on a key frame, the frame.
        static const std::uint8_t delimiter[] = {0, 0, 0, 1, 9, 0xF0};
        unit_.assign(delimiter, delimiter + sizeof delimiter);
        if (key) unit_.insert(unit_.end(), config_.begin(), config_.end());
        unit_.insert(unit_.end(), data, data + size);
        ts_.video(unit_.data(), unit_.size(), to_90khz(pts_us), key);
    }

    void start_segment(std::int64_t pts_us) {
        ts_.begin_segment();
        segment_start_us_ = pts_us;
        segment_open_ = true;
        sync_asked_ = false;
    }

    void cut(std::int64_t end_us) {
        live::Segment s;
        s.bytes = std::move(ts_.bytes());
        ts_.bytes().clear();
        s.seq = seq_++;
        s.duration_ms = static_cast<int>((end_us - segment_start_us_) / 1000);
        g_link.queue_segment(std::move(s));
    }

    // A second in, so the clock reference, which runs behind the frames, never goes below zero.
    std::uint64_t to_90khz(std::int64_t pts_us) const { return static_cast<std::uint64_t>((pts_us - first_pts_us_) * 9 / 100 + 90000); }

    // One source's next kAudioChunk frames at the stream's rate, added into `mix`; nothing when it has
    // not got that much.
    static void mix_source(AudioSource& source, std::int32_t* mix) {
        const int rate = source.rate.load(std::memory_order_relaxed);
        const int channels = source.channels.load(std::memory_order_relaxed);
        if (rate <= 0 || (channels != 1 && channels != 2)) return;
        const std::size_t frame_bytes = static_cast<std::size_t>(channels) * 2;
        const std::size_t head = source.head.load(std::memory_order_acquire);
        std::size_t tail = source.tail.load(std::memory_order_relaxed);
        if (source.restart.exchange(false)) {
            tail = head;
            source.phase = 0;
            source.buffering = true;
        }
        std::size_t have = (head - tail) / frame_bytes;
        const auto target = static_cast<std::size_t>(rate * kAudioDelay / kSecond);
        // Far ahead (the reader was held up): back to the target at once, so the sound keeps up with
        // the picture.
        if (have > target + static_cast<std::size_t>(rate) * 2 / 5) {
            tail = head - target * frame_bytes;
            have = target;
        }
        source.last_have.store(static_cast<int>(have), std::memory_order_relaxed);
        // Built up again after running dry, or still silent. A short gap once beats a click each round,
        // and without this the source would stay right at empty: it never gets ahead by itself.
        if (source.buffering && have < target) {
            source.tail.store(tail, std::memory_order_release);
            return;
        }
        source.buffering = false;
        // The source's clock is not ours: a tiny change of speed (at most half a percent, not audible)
        // brings what is in hand back to the target, so it neither runs dry nor needs a jump.
        const double off = (static_cast<double>(have) - static_cast<double>(target)) / rate;
        const double step = static_cast<double>(rate) / kAudioRate * (1.0 + std::clamp(off * 0.02, -0.005, 0.005));
        const auto needed = static_cast<std::size_t>(source.phase + kAudioChunk * step) + 2;
        if (have < needed) {
            source.short_rounds.fetch_add(1, std::memory_order_relaxed);
            source.buffering = true;
            source.tail.store(tail, std::memory_order_release);
            return;
        }
        auto sample = [&](std::size_t frame, int channel) {
            // Bytes one at a time: a sample can straddle the end of the ring.
            const std::size_t at = tail + frame * frame_bytes + static_cast<std::size_t>(channels == 2 ? channel : 0) * 2;
            const std::uint8_t lo = source.ring[at % kRingBytes], hi = source.ring[(at + 1) % kRingBytes];
            return static_cast<std::int32_t>(static_cast<std::int16_t>(static_cast<std::uint16_t>(lo | (hi << 8))));
        };
        double place = source.phase;
        for (int out = 0; out < kAudioChunk; ++out, place += step) {
            const auto whole = static_cast<std::size_t>(place);
            const double fraction = place - static_cast<double>(whole);
            for (int channel = 0; channel < 2; ++channel) {
                const std::int32_t a = sample(whole, channel), b = sample(whole + 1, channel);
                if (g_stats && std::abs(a) > source.peak.load(std::memory_order_relaxed)) source.peak.store(std::abs(a), std::memory_order_relaxed);
                mix[out * 2 + channel] += static_cast<std::int32_t>((a + static_cast<double>(b - a) * fraction) * kMixGain);
            }
        }
        const auto used = static_cast<std::size_t>(place);
        source.phase = place - static_cast<double>(used);
        source.tail.store(tail + used * frame_bytes, std::memory_order_release);
    }

    // The stream's sound runs by the clock: every kAudioChunk frames' time, whatever the sources have
    // by then, a little behind them so that they have all delivered. So a source that stops leaves
    // silence and not a gap, and the sound stays with the picture.
    bool feed_audio() {
        if (!audio_) return false;
        const Media& m = media();
        const Nanos now = now_ns();
        const Nanos chunk = kAudioChunk * kSecond / kAudioRate;
        bool any = false;
        if (audio_next_ == 0 || now - audio_next_ > kSecond / 2) audio_next_ = now;
        while (now >= audio_next_) {
            const ssize_t index = m.dequeue_input(audio_, 0);
            // Broken: as the picture's encoder (drain_video).
            if (codec_error(index)) {
                fail("the AAC encoder broke");
                return any;
            }
            // No free buffer yet (-1).
            if (index < 0) return any;
            std::size_t capacity = 0;
            std::uint8_t* in = m.input_buffer(audio_, static_cast<std::size_t>(index), &capacity);
            const std::size_t bytes = kAudioChunk * 4;
            if (!in || capacity < bytes) {
                // The buffer back, empty; not even that taken: broken.
                if (m.queue_input(audio_, static_cast<std::size_t>(index), 0, 0, 0, 0) != kMediaOk) fail("the AAC encoder broke");
                return any;
            }
            std::int32_t mix[kAudioChunk * 2] = {};
            for (AudioSource& source : g_sources)
                if (source.ring) mix_source(source, mix);
            auto* out = reinterpret_cast<std::int16_t*>(in);
            for (int i = 0; i < kAudioChunk * 2; ++i) out[i] = static_cast<std::int16_t>(std::clamp(mix[i], -32768, 32767));
            // The time these samples were made, by the same clock the pictures have. Not taken: broken.
            if (m.queue_input(audio_, static_cast<std::size_t>(index), 0, bytes, static_cast<std::uint64_t>((audio_next_ - kAudioDelay) / 1000), 0) !=
                kMediaOk) {
                fail("the AAC encoder broke");
                return any;
            }
            audio_next_ += chunk;
            any = true;
        }
        return any;
    }

    bool drain_audio() {
        if (!audio_) return false;
        const Media& m = media();
        bool any = false;
        for (;;) {
            CodecBufferInfo info{};
            const ssize_t index = m.dequeue_output(audio_, &info, 0);
            // Broken: as the picture's encoder (drain_video).
            if (codec_error(index)) {
                fail("the AAC encoder broke");
                return any;
            }
            if (index == -2 || index == -3) continue;
            if (index < 0) return any;
            any = true;
            std::size_t capacity = 0;
            std::uint8_t* data = m.output_buffer(audio_, static_cast<std::size_t>(index), &capacity);
            // Sound from before the stream's first picture has no place in it.
            if (data && info.size > 0 && !(info.flags & kFlagCodecConfig) && segment_open_ && info.pts_us >= first_pts_us_) {
                unit_.resize(7 + static_cast<std::size_t>(info.size));
                if (adts_header(unit_.data(), kAudioRate, 2, static_cast<std::size_t>(info.size))) {
                    std::memcpy(unit_.data() + 7, data + info.offset, static_cast<std::size_t>(info.size));
                    ts_.audio(unit_.data(), unit_.size(), to_90khz(info.pts_us));
                    g_audio_frames.fetch_add(1, std::memory_order_relaxed);
                }
            }
            // As the picture's (drain_video).
            if (m.release_output(audio_, static_cast<std::size_t>(index), false) != kMediaOk) {
                fail("the AAC encoder broke");
                return any;
            }
        }
    }

    // The bitrate can change on the running encoder. A new height needs a new one: the render thread
    // sees that the height is out of date and starts a new session.
    void apply_step() {
        const int wanted = step_bitrate(step());
        if (wanted == bitrate_) return;
        const Media& m = media();
        AMediaFormat* f = m.format_new();
        m.format_set_int(f, "video-bitrate", wanted);
        m.set_parameters(video_, f);
        m.format_delete(f);
        bitrate_ = wanted;
    }

    void close_all() {
        const Media& m = media();
        const Egl& e = egl();
        g_audio_gate.store(false);
        if (context_ != EGL_NO_CONTEXT) {
            const Gl& g = gl();
            if (read_fbo_[0]) g.delete_framebuffers(2, read_fbo_);
            // Fences of pictures that were never drawn: this context is the last one to know them.
            for (Slot& slot : s_->slots) {
                if (slot.state.load() == 1 && slot.fence) g.delete_sync(slot.fence);
                slot.fence = nullptr;
            }
            e.make_current(s_->display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
            if (surface_ != EGL_NO_SURFACE) e.destroy_surface(s_->display, surface_);
            e.destroy_context(s_->display, context_);
        }
        e.release_thread();
        if (video_) {
            if (video_started_) m.stop(video_);
            m.destroy(video_);
        }
        if (window_) ANativeWindow_release(window_);
        if (audio_) {
            m.stop(audio_);
            m.destroy(audio_);
        }
    }

    std::shared_ptr<Session> s_;
    AMediaCodec* video_ = nullptr;
    AMediaCodec* audio_ = nullptr;
    bool video_started_ = false;
    ANativeWindow* window_ = nullptr;
    EGLContext context_ = EGL_NO_CONTEXT;
    EGLSurface surface_ = EGL_NO_SURFACE;
    GLuint read_fbo_[2] = {0, 0};
    int bitrate_ = 0;
    TsWriter ts_;
    std::vector<std::uint8_t> config_, unit_;
    bool segment_open_ = false, sync_asked_ = false;
    std::int64_t first_pts_us_ = 0, segment_start_us_ = 0, last_pts_us_ = 0;
    int seq_ = 0;
    Nanos audio_next_ = 0;  // when the next chunk of sound is due
};

void log_stats_if_due(Nanos* next) {
    const Nanos now = now_ns();
    if (now < *next) return;
    *next = now + (g_stats ? 10 : 60) * kSecond;
    const std::uint64_t n = g_captures.exchange(0);
    const std::uint64_t total = g_capture_ns.exchange(0);
    log("arm32: live: step %d, %llu pictures, %llu skipped, render thread %llu us each (worst %llu), %llu segments up, %llu lost, %llu AAC frames", step(),
        static_cast<unsigned long long>(n), static_cast<unsigned long long>(g_skipped.exchange(0)),
        static_cast<unsigned long long>(n ? total / n / 1000 : 0), static_cast<unsigned long long>(g_capture_max_ns.exchange(0) / 1000),
        static_cast<unsigned long long>(g_link.uploaded.exchange(0)), static_cast<unsigned long long>(g_link.dropped.exchange(0)),
        static_cast<unsigned long long>(g_audio_frames.exchange(0)));
    if (g_stats) {
        for (const AudioSource& source : g_sources)
            if (source.id.load() && source.rate.load() > 0)
                log("arm32: live: source %d Hz: %d short rounds, %d frames in hand, peak %d", source.rate.load(), const_cast<AudioSource&>(source).short_rounds.exchange(0),
                    source.last_have.load(), const_cast<AudioSource&>(source).peak.exchange(0));
    }
}

void encoder_main() {
    background_thread("arm32-liveenc");
    Nanos next_stats = now_ns() + 60 * kSecond;
    for (;;) {
        std::shared_ptr<Session>* handed = g_handoff.exchange(nullptr);
        if (!handed && g_want.load()) {
            // Wanted: the render thread hands a session over at its next swap, which never waits to say so.
            sleep_ns(20000000);
            continue;
        }
        if (!handed) {
            // Off: nothing to do until it is wanted again, which set_want wakes this for. No timer meanwhile, so the
            // phone's processor is left alone for as long as broadcasts are off.
            std::unique_lock<std::mutex> l(g_encoder_lock);
            g_encoder_wake.wait(l, [] { return g_want.load() || g_handoff.load() != nullptr; });
            continue;
        }
        std::shared_ptr<Session> session = *handed;
        delete handed;
        session->taken.store(true);
        // Over before it started (the context may be gone with it): not a failure of this phone's.
        if (session->stop.load(std::memory_order_acquire)) {
            session->closed.store(true);
            continue;
        }
        {
            Encoder encoder(session);
            // An encoder that does not start, or breaks while it runs (the session's failed): one more in a row.
            bool failed = !encoder.open();
            if (!failed) {
                log("arm32: live: on, %dx%d", session->width, session->height);
                const Nanos started = now_ns();
                while (!session->stop.load(std::memory_order_acquire) && g_want.load(std::memory_order_relaxed) &&
                       !session->failed.load(std::memory_order_relaxed)) {
                    // Pictures come every 33 ms and AAC frames about every 21: a few milliseconds' rest
                    // when there is nothing to do is plenty.
                    if (!encoder.pump()) sleep_ns(4000000);
                    log_stats_if_due(&next_stats);
                }
                // What the encoders gave until then is a segment as usual.
                encoder.finish();
                // In case the render thread has not ended this session itself: it must not go on
                // filling textures nobody reads. A broken one it ends too, and tries again ten seconds later.
                session->stop.store(true, std::memory_order_release);
                failed = session->failed.load(std::memory_order_relaxed);
                log("arm32: live: stopped%s", failed ? ", the encoder broke" : "");
                // A good run (it ended as asked, or ran a minute before it broke): the failures in a row start over.
                if (!failed || now_ns() - started >= kGoodRun) g_failures.store(0);
            }
            if (failed && g_failures.fetch_add(1) + 1 >= 3) {
                log("arm32: live: this phone cannot encode the stream, giving up");
                g_gave_up.store(true);
            }
        }
        session->closed.store(true);
    }
}

// ---- the render thread

// A context the game has destroyed, until the render thread has seen it: a new one can get the same
// address, and object names of the old one would then be the game's own.
std::atomic<void*> g_destroyed_context{nullptr};

struct Capture {
    std::shared_ptr<Session> session;
    std::shared_ptr<Session> previous;  // the last one, until the encoder thread is done with it
    GLuint draw_fbo[2] = {0, 0};
    EGLContext context = EGL_NO_CONTEXT;
    EGLSurface surface = EGL_NO_SURFACE;
    int source_width = 0, source_height = 0;
    Nanos next_due = 0;
    Nanos last_picture = 0;
    Nanos retry_at = 0;
} g_capture;

void end_capture(Capture& c, bool context_is_current) {
    c.session->stop.store(true, std::memory_order_release);
    c.previous = c.session;
    // Names in the game's context: gone with it otherwise. A texture still attached in the encoder's
    // context lives on until that context lets go of it.
    if (context_is_current) {
        const Gl& g = gl();
        g.delete_framebuffers(2, c.draw_fbo);
        GLuint textures[2] = {c.session->slots[0].texture, c.session->slots[1].texture};
        g.delete_textures(2, textures);
    }
    c.session.reset();
}

// The picture's size: the height asked for, the frame's shape, in the 16-pixel blocks encoders like.
void picture_size(int source_width, int source_height, int height, int* width_out, int* height_out) {
    const int h = (height + 8) / 16 * 16;
    int w = static_cast<int>((static_cast<std::int64_t>(source_width) * h + source_height / 2) / source_height);
    w = (w + 8) / 16 * 16;
    *width_out = std::max(w, 16);
    *height_out = std::max(h, 16);
}

bool begin_capture(Capture& c, EGLDisplay d, EGLContext context, EGLSurface s, int source_width, int source_height, Nanos now) {
    const Gl& g = gl();
    const Egl& e = egl();
    // glBlitFramebuffer takes OpenGL ES 3, and a scaled copy a frame without multisampling: no
    // need to ask the driver twice, these do not change on a phone.
    EGLint version = 0, samples = 0, config_id = 0, found = 0;
    e.query_context(d, context, EGL_CONTEXT_CLIENT_VERSION, &version);
    // From the window's own config: GL's answer goes by whatever framebuffer the game has bound now.
    EGLConfig config = nullptr;
    e.query_surface(d, s, EGL_CONFIG_ID, &config_id);
    const EGLint by_id[] = {EGL_CONFIG_ID, config_id, EGL_NONE};
    if (e.choose_config(d, by_id, &config, 1, &found) && found == 1) e.config_attrib(d, config, EGL_SAMPLE_BUFFERS, &samples);
    if (version < 3 || samples != 0) {
        log("arm32: live: the game's context is not usable (ES %d, %d sample buffers)", version, samples);
        g_gave_up.store(true);
        return false;
    }
    auto session = std::make_shared<Session>();
    session->display = d;
    session->share = context;
    picture_size(source_width, source_height, step_height(step()), &session->width, &session->height);
    GLint texture = 0, read = 0, draw = 0;
    g.get_integer(GL_TEXTURE_BINDING_2D, &texture);
    g.get_integer(GL_READ_FRAMEBUFFER_BINDING, &read);
    g.get_integer(GL_DRAW_FRAMEBUFFER_BINDING, &draw);
    GLuint textures[2];
    g.gen_textures(2, textures);
    g.gen_framebuffers(2, c.draw_fbo);
    bool complete = true;
    for (int i = 0; i < 2; ++i) {
        session->slots[i].texture = textures[i];
        g.bind_texture(GL_TEXTURE_2D, textures[i]);
        g.tex_storage(GL_TEXTURE_2D, 1, GL_RGBA8, session->width, session->height);
        g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, c.draw_fbo[i]);
        g.framebuffer_texture(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, textures[i], 0);
        complete = complete && g.check_framebuffer(GL_DRAW_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    }
    // What the game had bound, as it was.
    g.bind_texture(GL_TEXTURE_2D, static_cast<GLuint>(texture));
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, static_cast<GLuint>(read));
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, static_cast<GLuint>(draw));
    if (!complete) {
        log("arm32: live: the picture's framebuffer is not complete");
        g.delete_framebuffers(2, c.draw_fbo);
        g.delete_textures(2, textures);
        g_gave_up.store(true);
        return false;
    }
    c.session = session;
    c.context = context;
    c.surface = s;
    c.source_width = source_width;
    c.source_height = source_height;
    c.next_due = now;
    c.last_picture = now;
    // A session the encoder thread never took is thrown away with this, with the fences of any
    // pictures it took meanwhile.
    if (std::shared_ptr<Session>* unused = g_handoff.exchange(new std::shared_ptr<Session>(session))) {
        for (Slot& slot : (*unused)->slots)
            if (slot.fence) {
                if (context == (*unused)->share) g.delete_sync(slot.fence);
                slot.fence = nullptr;
            }
        delete unused;
    }
    return true;
}

void take_picture(Capture& c, Nanos now) {
    const Gl& g = gl();
    Session& s = *c.session;
    // A free texture, or this picture is left out: the encoder is behind.
    int free_slot = -1;
    for (int i = 0; i < 2; ++i)
        if (s.slots[i].state.load(std::memory_order_acquire) == 0) free_slot = i;
    if (free_slot < 0) {
        g_skipped.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    Slot& slot = s.slots[free_slot];
    // A blit only cares for the two framebuffer bindings and the scissor test: nothing else of the
    // game's state is touched, and what is, is put back.
    GLint read = 0, draw = 0;
    g.get_integer(GL_READ_FRAMEBUFFER_BINDING, &read);
    g.get_integer(GL_DRAW_FRAMEBUFFER_BINDING, &draw);
    const GLboolean scissor = g.is_enabled(GL_SCISSOR_TEST);
    if (scissor) g.disable(GL_SCISSOR_TEST);
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, 0);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, c.draw_fbo[free_slot]);
    g.blit(0, 0, c.source_width, c.source_height, 0, 0, s.width, s.height, GL_COLOR_BUFFER_BIT, GL_LINEAR);
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, static_cast<GLuint>(read));
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, static_cast<GLuint>(draw));
    if (scissor) g.enable(GL_SCISSOR_TEST);
    slot.fence = g.fence(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
    // The other context can only wait for a fence that has reached the GPU; the swap would do this
    // a moment later anyway.
    g.flush();
    slot.pts = now;
    slot.state.store(1, std::memory_order_release);
    c.last_picture = now;
}

// ---- Java: the device ids and the notice

void clear_exception(JNIEnv* e) {
    if (e->ExceptionCheck()) e->ExceptionClear();
}

// A static String field of the platform SDK, read and not computed: its getters remember the first
// answer, and this must never be the first to ask, before the SDK has its settings. Once the game
// has signed in, the ids it signed in with are here.
void add_static_string(JNIEnv* e, jclass c, const char* name, std::string& ids) {
    jfieldID field = e->GetStaticFieldID(c, name, "Ljava/lang/String;");
    if (!field) {
        clear_exception(e);
        return;
    }
    auto value = static_cast<jstring>(e->GetStaticObjectField(c, field));
    clear_exception(e);
    if (!value) return;
    if (const char* chars = e->GetStringUTFChars(value, nullptr)) {
        // Into the list once, and only when made of what the login's ids are (live_net.cpp): it goes straight in a URL.
        live::add_id(ids, chars);
        e->ReleaseStringUTFChars(value, chars);
    }
    e->DeleteLocalRef(value);
}

std::string read_ids(JNIEnv* e) {
    std::string ids;
    if (!g_device_class) return ids;
    add_static_string(e, g_device_class, "udid", ids);
    add_static_string(e, g_device_class, "udid_share", ids);
    return ids;
}

// The looper of the thread showing the last notice, until it can go.
jobject g_toast_looper = nullptr;
std::mutex g_toast_lock;
Nanos g_toast_quit_at = 0;

// A toast needs a thread with a message loop that keeps running while it shows. Without Java code of
// our own to post to the main thread, the notice gets such a thread for itself, and the control
// thread ends the loop when the toast is over.
void toast_thread(std::string text) {
    background_thread("arm32-livemsg");
    JNIEnv* e = nullptr;
    if (g_vm->AttachCurrentThread(&e, nullptr) != JNI_OK) return;
    jclass looper = e->FindClass("android/os/Looper");
    jclass toast = e->FindClass("android/widget/Toast");
    jfieldID context_field = g_base_class ? e->GetStaticFieldID(g_base_class, "appContext", "Landroid/content/Context;") : nullptr;
    jobject context = context_field ? e->GetStaticObjectField(g_base_class, context_field) : nullptr;
    clear_exception(e);
    if (looper && toast && context) {
        e->CallStaticVoidMethod(looper, e->GetStaticMethodID(looper, "prepare", "()V"));
        jobject mine = e->CallStaticObjectMethod(looper, e->GetStaticMethodID(looper, "myLooper", "()Landroid/os/Looper;"));
        jmethodID make = e->GetStaticMethodID(toast, "makeText", "(Landroid/content/Context;Ljava/lang/CharSequence;I)Landroid/widget/Toast;");
        // The server's text, as modified UTF-8: what NewStringUTF reads on every Android (live_net.cpp).
        jstring message = e->NewStringUTF(live::modified_utf8(text).c_str());
        // LENGTH_LONG (1): three and a half seconds, for the notice's two lines; its loop runs for six.
        jobject shown = make && message ? e->CallStaticObjectMethod(toast, make, context, message, 1) : nullptr;
        if (shown && mine && !e->ExceptionCheck()) {
            e->CallVoidMethod(shown, e->GetMethodID(toast, "show", "()V"));
            {
                std::lock_guard<std::mutex> l(g_toast_lock);
                // A notice still up: its thread can go now.
                if (g_toast_looper) {
                    jclass old = e->GetObjectClass(g_toast_looper);
                    e->CallVoidMethod(g_toast_looper, e->GetMethodID(old, "quitSafely", "()V"));
                    clear_exception(e);
                    e->DeleteLocalRef(old);
                    e->DeleteGlobalRef(g_toast_looper);
                }
                g_toast_looper = e->NewGlobalRef(mine);
                g_toast_quit_at = now_ns() + 6 * kSecond;
            }
            e->CallStaticVoidMethod(looper, e->GetStaticMethodID(looper, "loop", "()V"));
        }
        clear_exception(e);
    }
    clear_exception(e);
    g_vm->DetachCurrentThread();
}

void end_toast_if_due(JNIEnv* e, Nanos now) {
    std::lock_guard<std::mutex> l(g_toast_lock);
    if (!g_toast_looper || now < g_toast_quit_at) return;
    jclass looper = e->GetObjectClass(g_toast_looper);
    e->CallVoidMethod(g_toast_looper, e->GetMethodID(looper, "quitSafely", "()V"));
    clear_exception(e);
    e->DeleteLocalRef(looper);
    e->DeleteGlobalRef(g_toast_looper);
    g_toast_looper = nullptr;
}

// ---- the control thread

// The phone's own word on its temperature, where it has one (Android 11 and later): MODERATE (2)
// takes a step down, SEVERE (3) goes to the lowest, and from CRITICAL (4) on nothing is sent.
int thermal_status() {
    using Acquire = void* (*)();
    using Status = int (*)(void*);
    static void* lib = dlopen("libandroid.so", RTLD_NOW | RTLD_LOCAL);
    static auto acquire = lib ? reinterpret_cast<Acquire>(dlsym(lib, "AThermal_acquireManager")) : nullptr;
    static auto status = lib ? reinterpret_cast<Status>(dlsym(lib, "AThermal_getCurrentThermalStatus")) : nullptr;
    static void* manager = acquire && status ? acquire() : nullptr;
    return manager ? status(manager) : 0;
}

// A thread, or false when the system will not give one: never an exception through the game's frame.
template <class... Args>
bool start_thread(Args&&... args) {
    try {
        std::thread(std::forward<Args>(args)...).detach();
        return true;
    } catch (const std::system_error&) {
        log("arm32: live: cannot start a thread");
        return false;
    }
}

void start_workers_once() {
    static bool started = false;
    if (started) return;
    started = true;
    for (AudioSource& source : g_sources) source.ring = std::make_unique<std::uint8_t[]>(kRingBytes);
    if (!start_thread(encoder_main) || !start_thread([] { g_link.run(); })) g_gave_up.store(true);
}

void control_main() {
    background_thread("arm32-live");
    JNIEnv* e = nullptr;
    if (g_vm->AttachCurrentThread(&e, nullptr) != JNI_OK) return;
    Nanos next_poll = 0;
    bool was_on = false;
    for (;;) {
        sleep_ns(kSecond);
        const Nanos now = now_ns();
        end_toast_if_due(e, now);
        const bool away = now - g_last_swap.load(std::memory_order_relaxed) > kAwayAfter;
        const bool want_now = g_on.load() && !away && !g_gave_up.load() && thermal_status() < 4;
        set_want(want_now);
        // Away from the screen: nothing to send, and no reason to wake the phone's radio. The next
        // request goes out as soon as the game is back.
        if (away) {
            next_poll = 0;
            continue;
        }
        if (now < next_poll && (g_on.load() || !was_on)) continue;
        std::string ids = read_ids(e);
        if (ids.empty()) {
            // Not signed in yet.
            next_poll = now + 5 * kSecond;
            continue;
        }
        next_poll = now + kPollEvery;
        static bool first_request = true;
        if (first_request) {
            first_request = false;
            log("arm32: live: signed in, asking the server");
        }
        {
            const int status = thermal_status();
            g_thermal_step.store(status >= 3 ? kLastStep : status == 2 ? 1 : 0);
        }
        // The language of the phone's system for the notice.
        char locale[PROP_VALUE_MAX] = "";
        __system_property_get("persist.sys.locale", locale);
        const char* lang = std::strncmp(locale, "ko", 2) == 0 ? "ko" : "en";
        // The answer, checked (live_net.cpp parse_state). None: as things were.
        const live::State state = g_link.ask_state(ids, lang);
        if (!state.answered) continue;
        g_link.set_identity(ids, state);
        if (state.on) {
            g_fps.store(state.fps);
            g_height.store(state.height);
            g_bitrate.store(state.bitrate);
            g_segment.store(state.segment);
            start_workers_once();
            if (g_failures.load() >= 3) g_gave_up.store(true);
        }
        // Gone off: the stream's end once its last segments are out, and the top step for the next time.
        if (was_on && !state.on) g_link.end_stream();
        g_on.store(state.on);
        was_on = state.on;
        if (!state.toast.empty()) start_thread(toast_thread, state.toast);
    }
}

}  // namespace

void live_load(JavaVM* vm, JNIEnv* env, const std::string& lib_dir) {
    if (!requested("ARM32_LIVE", "debug.arm32.live", true)) return;
    std::string server;
    // The packer's line for this: "server <host[:port]>".
    std::ifstream f(lib_dir + "/libarm32t-tweaks.so");
    std::string line;
    while (std::getline(f, line)) {
        std::istringstream in(line);
        std::string word, value;
        if ((in >> word >> value) && word == "server") server = value;
    }
    // A test server (see the top of the file).
    char test[PROP_VALUE_MAX] = "";
    __system_property_get("debug.arm32.liveserver", test);
    if (test[0]) server = test;
    if (server.empty()) return;
    if (!media().ok) {
        log("arm32: live: this Android has no media encoder API");
        return;
    }
    g_link.set_server(live::parse_server(server));
    // A refused segment (403): off until the control thread's next request says otherwise.
    g_link.on_refused = [] {
        g_on.store(false);
        set_want(false);
    };
    g_vm = vm;
    auto keep_class = [&](const char* name) -> jclass {
        jclass local = env->FindClass(name);
        clear_exception(env);
        if (!local) return nullptr;
        auto global = static_cast<jclass>(env->NewGlobalRef(local));
        env->DeleteLocalRef(local);
        return global;
    };
    g_device_class = keep_class("com/pmangplus/device/PPDevice");
    g_base_class = keep_class("com/pmangplus/base/PPBase");
    if (!g_device_class) {
        log("arm32: live: no platform SDK in this app");
        return;
    }
    log("arm32: live: asks %s", server.c_str());
    g_enabled.store(true);
}

void live_context_destroyed(EGLContext context) { g_destroyed_context.store(context, std::memory_order_relaxed); }

void live_frame(EGLDisplay d, EGLSurface s) {
    if (!g_enabled.load(std::memory_order_relaxed)) return;
    const Nanos start = now_ns();
    g_last_swap.store(start, std::memory_order_relaxed);
    static bool control_started = false;
    if (!control_started) {
        control_started = true;
        if (!start_thread(control_main)) g_enabled.store(false);
    }
    Capture& c = g_capture;
    const bool want = g_want.load(std::memory_order_relaxed);
    // The usual case, by far.
    if (!want && !c.session) return;
    const Egl& e = egl();
    if (!e.ok || !gl().ok) return;
    const EGLContext context = e.current_context();
    if (c.session) {
        // Each of these means this session is over: a new one follows at a later frame if wanted.
        EGLint w = 0, h = 0;
        const bool same_context = context == c.context && g_destroyed_context.load(std::memory_order_relaxed) != c.context;
        if (g_destroyed_context.load(std::memory_order_relaxed) == c.context) g_destroyed_context.store(nullptr, std::memory_order_relaxed);
        if (s == c.surface) {
            e.query_surface(d, s, EGL_WIDTH, &w);
            e.query_surface(d, s, EGL_HEIGHT, &h);
        }
        int picture_w = 0, picture_h = 0;
        picture_size(c.source_width, c.source_height, step_height(step()), &picture_w, &picture_h);
        if (!want || !same_context || s != c.surface || w != c.source_width || h != c.source_height || picture_h != c.session->height ||
            start - c.last_picture > kRestartAfter || c.session->stop.load(std::memory_order_acquire) ||
            c.session->failed.load(std::memory_order_relaxed)) {
            if (c.session->failed.load(std::memory_order_relaxed)) c.retry_at = start + 10 * kSecond;
            end_capture(c, same_context);
            return;
        }
    }
    if (!c.session) {
        if (!want || start < c.retry_at || g_gave_up.load(std::memory_order_relaxed)) return;
        // Not while the encoder thread is stuck in the last one: that would only pile up textures.
        if (c.previous && c.previous->taken.load() && !c.previous->closed.load()) return;
        c.previous.reset();
        // Only the frame going to the window, drawn on the current context.
        if (context == EGL_NO_CONTEXT || e.current_surface(EGL_DRAW) != s) return;
        EGLint w = 0, h = 0;
        e.query_surface(d, s, EGL_WIDTH, &w);
        e.query_surface(d, s, EGL_HEIGHT, &h);
        if (w <= 0 || h <= 0) return;
        begin_capture(c, d, context, s, w, h, start);
        return;
    }
    const Nanos interval = kSecond / step_fps(step());
    if (start + kCaptureTolerance < c.next_due) return;
    c.next_due = std::max(c.next_due + interval, start);
    take_picture(c, start);
    const std::uint64_t took = static_cast<std::uint64_t>(now_ns() - start);
    g_captures.fetch_add(1, std::memory_order_relaxed);
    g_capture_ns.fetch_add(took, std::memory_order_relaxed);
    if (took > g_capture_max_ns.load(std::memory_order_relaxed)) g_capture_max_ns.store(took, std::memory_order_relaxed);
}

void live_audio_source(const void* id, int sample_rate, int channels, int bits) {
    AudioSource* found = nullptr;
    for (AudioSource& source : g_sources)
        if (source.id.load(std::memory_order_relaxed) == id) found = &source;
    if (!found) {
        // Players come and go with the app's audio: the oldest slot goes to a new one.
        found = &g_sources[g_next_source.fetch_add(1) % kAudioSources];
        found->id.store(nullptr);
        found->restart.store(true);
    }
    found->rate.store(bits == 16 ? sample_rate : 0, std::memory_order_relaxed);
    found->channels.store(channels, std::memory_order_relaxed);
    found->id.store(id, std::memory_order_release);
}

void live_audio(const void* id, const void* buffer, std::size_t size) {
    if (!g_audio_gate.load(std::memory_order_acquire) || !buffer || size == 0) return;
    for (AudioSource& source : g_sources) {
        if (source.id.load(std::memory_order_acquire) != id || !source.ring) continue;
        auto* data = static_cast<const std::uint8_t*>(buffer);
        const std::size_t head = source.head.load(std::memory_order_relaxed);
        const std::size_t tail = source.tail.load(std::memory_order_acquire);
        // No room: left out of the broadcast.
        if (size > kRingBytes - (head - tail)) return;
        for (std::size_t i = 0, at = head % kRingBytes; i < size;) {
            const std::size_t run = std::min(size - i, kRingBytes - at);
            std::memcpy(source.ring.get() + at, data + i, run);
            i += run;
            at = (at + run) % kRingBytes;
        }
        source.head.store(head + size, std::memory_order_release);
        return;
    }
}

}  // namespace arm32
