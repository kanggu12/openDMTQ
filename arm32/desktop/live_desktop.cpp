// Live view on a computer: while the server's owner has it on for this player, the game's picture and sound go to the
// server as MPEG-TS segments, with the requests a phone makes (src/live.cpp is the phone's, docs/live.md the protocol):
// /live/state about every 15 seconds while the game is on screen, /live/upload for each segment, /live/end when it goes
// off. It is off by default, and nothing here may ever get in the way of the game: a broadcast may stutter or stop, the
// game may not.
//
// What runs where:
//
// - The render thread, at each swap (live_frame): with live view off, one atomic load. With it on, a picture is due at
//   the stream's frame rate: the finished frame is scaled to the stream's size with one blit, turned into NV12 (the
//   encoder's format: a plane of luma, then one of chroma at half the size) by two small draws, and read into a pixel
//   buffer without waiting. A later swap, once the GPU says it is done, copies it out for the encoder. Nothing on this
//   thread waits for the GPU, and everything of the game's state it touches is put back.
// - The mixer's thread (mixer.cpp): its mix, before the player's volume, into a ring here (mix_tap), left out when full.
// - The encoder thread: Windows' own H.264 and AAC encoders (Media Foundation, found by type), and the MPEG-TS writer
//   (live_ts.cpp), cut at a key frame every segment. Only this thread waits on an encoder.
// - The upload thread and the control thread: as on a phone. A slow upload drops segments rather than holding on to
//   them, and turns the quality down: frame rate and bitrate first, then the picture's height.
//
// The server's address is the one the app was built for (the packer's tweaks file, its line "server <host[:port]>"),
// the ids are the one the game signs in with (device_id()), and the server's notice shows over the game's window
// (show_notice()). PLAYER_LIVE=0 turns it all off; PLAYER_LIVE_SERVER=<host:port> asks another server.
//
// Windows only: on Linux, a developer's player, there is no encoder to ask and nothing runs.
#include "player.h"

#include "host.h"
#include "live.h"

#include <EGL/egl.h>
#include <EGL/eglext.h>

namespace arm32 {
// The desktop's own entry points, which frames.cpp calls: at each swap, and when the game destroys a context.
void desktop_live_frame(EGLDisplay display, EGLSurface surface);
void desktop_live_context_destroyed(EGLContext context);
// The game held still behind the player's menu (true) or going on (false), which window_win32.cpp tells.
void desktop_live_paused(bool paused);
}  // namespace arm32

#ifndef _WIN32

namespace arm32 {
void desktop_live_frame(EGLDisplay, EGLSurface) {}
void desktop_live_context_destroyed(EGLContext) {}
void desktop_live_paused(bool) {}
}  // namespace arm32

#else

#include "live_sps.h"
#include "live_ts.h"
#include "mixer.h"

#include <GLES3/gl3.h>
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
#include <arpa/inet.h>
#include <atomic>
#include <cctype>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <dlfcn.h>
#include <fstream>
#include <memory>
#include <mutex>
#include <netdb.h>
#include <sstream>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace arm32 {

namespace {

using Nanos = std::int64_t;
constexpr Nanos kSecond = 1000000000;
// How often the control thread asks the server.
constexpr Nanos kPollEvery = 15 * kSecond;
// No swap for this long: the game is away (minimized, closed), so nothing is sent and the server is not asked.
constexpr Nanos kAwayAfter = 5 * kSecond;
// No picture for this long (a pause, a load): the stream starts over from a new first segment.
constexpr Nanos kRestartAfter = 3 * kSecond;
// Segments waiting for the network, at most: the oldest goes when another comes.
constexpr std::size_t kUploadQueue = 3;
// The server takes up to 4 MB; at these bitrates only a fault gets this far.
constexpr std::size_t kMaxSegment = 4 * 1024 * 1024 - 1024;
// The stream's sound: 48 kHz stereo AAC at this bitrate (bytes a second, as Media Foundation's AAC encoder takes it),
// in chunks of an AAC frame's 1024 samples.
constexpr int kAudioRate = 48000;
constexpr int kAudioChunk = 1024;
constexpr UINT32 kAudioBytesPerSecond = 16000;
// How much of the mix is kept in hand: the mixer writes a period at a time, and an empty round is a click.
constexpr Nanos kAudioDelay = 150000000;
// The ring of the mixer's sound: two seconds of the highest rate a device mixes at (192 kHz, 16-bit stereo).
constexpr std::size_t kRingBytes = 1u << 21;
// A frame this much earlier than due still counts: swaps come with some jitter around the display's beat, and without
// this the 30 pictures a second of a 60 fps game would come unevenly.
constexpr Nanos kCaptureTolerance = 2000000;
// Pictures in flight between the render thread and the encoder: read back on the GPU, waiting to be copied out.
constexpr int kSlots = 3;
// Pictures copied out and waiting for the encoder: one more is dropped (the encoder is behind).
constexpr std::size_t kFrameQueue = 4;

Nanos now_ns() {
    timespec t{};
    clock_gettime(CLOCK_MONOTONIC, &t);
    return static_cast<Nanos>(t.tv_sec) * kSecond + t.tv_nsec;
}

void sleep_ns(Nanos n) {
    if (n > 0) std::this_thread::sleep_for(std::chrono::nanoseconds(n));
}

// These threads start below the game's: when the PC is short of CPU, the game comes first.
void background_thread(const char* name) {
    player::name_thread(name);
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL);
}

// ---- state shared by the threads

std::atomic<bool> g_enabled{false};  // a server address, not turned off
std::string g_host;                  // the server's name
std::string g_host_header;           // and how a request names it
int g_port = 80;

std::atomic<Nanos> g_last_swap{0};   // when the game last swapped
std::atomic<bool> g_want{false};     // pictures and sound are to be sent right now
std::atomic<bool> g_on{false};       // the server has live view on for this player
std::atomic<bool> g_gave_up{false};  // this PC cannot do it: the server is still asked, for notices
std::atomic<bool> g_paused{false};   // the game is held still behind the player's menu: nothing is sent meanwhile
std::atomic<int> g_failures{0};      // encoder start-ups that failed; three end the attempts

// What the server asks for (the top step), and the step the network has taken it down to.
std::atomic<int> g_fps{30}, g_height{720}, g_bitrate{2000000}, g_segment{2};
std::atomic<int> g_network_step{0};
constexpr int kLastStep = 3;

int step() { return g_network_step.load(std::memory_order_relaxed); }
int step_fps(int s) { return s == 0 ? g_fps.load() : s == 1 ? std::max(g_fps.load() * 2 / 3, 1) : std::max(g_fps.load() / 2, 1); }
int step_height(int s) { return s <= 1 ? g_height.load() : s == 2 ? g_height.load() * 3 / 4 : g_height.load() / 2; }
int step_bitrate(int s) {
    static constexpr int percent[] = {100, 60, 35, 20};
    return static_cast<int>(static_cast<std::int64_t>(g_bitrate.load()) * percent[s] / 100);
}

// The identity and the key, set by the control thread.
std::mutex g_identity_lock;
std::string g_ids, g_token;

// For the log, once a minute while live (every ten seconds with stats on).
std::atomic<std::uint64_t> g_captures{0}, g_capture_ns{0}, g_capture_max_ns{0}, g_skipped{0}, g_dropped{0}, g_uploaded{0}, g_audio_frames{0};
// The other half of a picture's cost on the render thread: taking it out of its pixel buffer for the encoder, a frame or
// two after it was taken.
std::atomic<std::uint64_t> g_handed{0}, g_hand_ns{0}, g_hand_max_ns{0};
// Where a picture's taking goes, with stats on: the hook's own looks before it, saving the game's state, the scaled copy,
// the two conversion draws, the two reads into the pixel buffers, the fence, putting the state back.
constexpr int kPhases = 7;
std::atomic<std::uint64_t> g_phase_ns[kPhases];

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

// ---- HTTP: plain, one request per connection, a blocking socket with time limits (as the game's own requests go)

struct HttpResult {
    int status = 0;  // 0: no answer
    std::string body;
};

int connect_to_server() {
    addrinfo hints{};
    hints.ai_socktype = SOCK_STREAM;
    addrinfo* list = nullptr;
    const std::string port = std::to_string(g_port);
    if (getaddrinfo(g_host.c_str(), port.c_str(), &hints, &list) != 0) return -1;
    int fd = -1;
    for (addrinfo* a = list; a; a = a->ai_next) {
        fd = socket(a->ai_family, a->ai_socktype | SOCK_CLOEXEC, a->ai_protocol);
        if (fd < 0) continue;
        // Both limits, and the send one also limits connect.
        timeval limit{10, 0};
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &limit, sizeof limit);
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &limit, sizeof limit);
        if (connect(fd, a->ai_addr, a->ai_addrlen) == 0) break;
        close(fd);
        fd = -1;
    }
    freeaddrinfo(list);
    return fd;
}

bool send_all(int fd, const void* data, std::size_t size) {
    auto* p = static_cast<const char*>(data);
    while (size > 0) {
        ssize_t n = send(fd, p, size, MSG_NOSIGNAL);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return false;
        p += n;
        size -= static_cast<std::size_t>(n);
    }
    return true;
}

// HTTP/1.0, so the answer needs no chunk decoding: it ends where the connection does.
HttpResult http(const char* method, const std::string& path, const std::string& extra_headers, const void* body, std::size_t body_size) {
    HttpResult r;
    int fd = connect_to_server();
    if (fd < 0) return r;
    std::string head = std::string(method) + " " + path + " HTTP/1.0\r\nHost: " + g_host_header + "\r\nUser-Agent: opendmtq-player-live\r\n" + extra_headers;
    if (body) head += "Content-Length: " + std::to_string(body_size) + "\r\n";
    head += "\r\n";
    if (send_all(fd, head.data(), head.size()) && (!body || send_all(fd, body, body_size))) {
        std::string in;
        char buffer[4096];
        ssize_t n;
        // A notice and a few numbers: an answer past this is not one of ours.
        while (in.size() < 65536 && ((n = recv(fd, buffer, sizeof buffer, 0)) > 0 || (n < 0 && errno == EINTR))) {
            if (n > 0) in.append(buffer, static_cast<std::size_t>(n));
        }
        std::size_t space = in.find(' ');
        std::size_t end = in.find("\r\n\r\n");
        if (in.rfind("HTTP/", 0) == 0 && space != std::string::npos && end != std::string::npos) {
            r.status = std::atoi(in.c_str() + space + 1);
            r.body = in.substr(end + 4);
        }
    }
    close(fd);
    return r;
}

// ---- reading the server's small JSON answer: flat, with known keys

// Where the value of "key" starts, or npos.
std::size_t json_value(const std::string& json, const char* key) {
    const std::string quoted = std::string("\"") + key + "\"";
    std::size_t at = json.find(quoted);
    if (at == std::string::npos) return at;
    at = json.find(':', at + quoted.size());
    if (at == std::string::npos) return at;
    ++at;
    while (at < json.size() && (json[at] == ' ' || json[at] == '\t' || json[at] == '\n' || json[at] == '\r')) ++at;
    return at < json.size() ? at : std::string::npos;
}

bool json_bool(const std::string& json, const char* key) {
    std::size_t at = json_value(json, key);
    return at != std::string::npos && json.compare(at, 4, "true") == 0;
}

int json_int(const std::string& json, const char* key, int fallback) {
    std::size_t at = json_value(json, key);
    if (at == std::string::npos || !(json[at] >= '0' && json[at] <= '9')) return fallback;
    return std::atoi(json.c_str() + at);
}

void append_utf8(std::string& out, unsigned c) {
    if (c < 0x80) {
        out += static_cast<char>(c);
    } else if (c < 0x800) {
        out += static_cast<char>(0xC0 | (c >> 6));
        out += static_cast<char>(0x80 | (c & 0x3F));
    } else {
        out += static_cast<char>(0xE0 | (c >> 12));
        out += static_cast<char>(0x80 | ((c >> 6) & 0x3F));
        out += static_cast<char>(0x80 | (c & 0x3F));
    }
}

// A string value, with the escapes PHP's json_encode writes (\uXXXX for Korean).
std::string json_string(const std::string& json, const char* key) {
    std::string out;
    std::size_t at = json_value(json, key);
    if (at == std::string::npos || json[at] != '"') return out;
    for (++at; at < json.size() && json[at] != '"'; ++at) {
        if (json[at] != '\\') {
            out += json[at];
            continue;
        }
        if (++at >= json.size()) break;
        switch (json[at]) {
        case 'n': out += '\n'; break;
        case 't': out += '\t'; break;
        case 'u':
            if (at + 4 < json.size()) {
                append_utf8(out, static_cast<unsigned>(std::strtoul(json.substr(at + 1, 4).c_str(), nullptr, 16)));
                at += 4;
            }
            break;
        default: out += json[at];
        }
    }
    return out;
}

// ---- the upload thread

struct Segment {
    std::vector<std::uint8_t> bytes;
    int seq = 0;
    int duration_ms = 0;
};

std::mutex g_upload_lock;
std::condition_variable g_upload_wake;
std::deque<Segment> g_uploads;
std::atomic<bool> g_end_due{false};  // tell the server the stream has ended, once what is queued is out

void queue_segment(Segment&& s) {
    if (s.bytes.empty() || s.bytes.size() > kMaxSegment) return;
    std::lock_guard<std::mutex> l(g_upload_lock);
    // A network this slow: the newest pictures matter most, and the quality has to come down.
    if (g_uploads.size() >= kUploadQueue) {
        g_uploads.pop_front();
        g_dropped.fetch_add(1, std::memory_order_relaxed);
        g_network_step.store(std::min(g_network_step.load() + 1, kLastStep));
    }
    g_uploads.push_back(std::move(s));
    g_upload_wake.notify_one();
}

void upload_main() {
    background_thread("live-upload");
    int slow = 0, fast = 0;
    for (;;) {
        Segment s;
        bool end = false;
        {
            std::unique_lock<std::mutex> l(g_upload_lock);
            g_upload_wake.wait(l, [] { return !g_uploads.empty() || g_end_due.load(); });
            if (!g_uploads.empty()) {
                s = std::move(g_uploads.front());
                g_uploads.pop_front();
            } else {
                end = g_end_due.exchange(false);
            }
        }
        std::string ids, token;
        {
            std::lock_guard<std::mutex> l(g_identity_lock);
            ids = g_ids;
            token = g_token;
        }
        const std::string header = "X-Live-Token: " + token + "\r\n";
        if (end) {
            if (!token.empty()) http("POST", "/live/end?ids=" + ids, header, "", 0);
            continue;
        }
        const Nanos start = now_ns();
        HttpResult r = http("POST", "/live/upload?ids=" + ids + "&seq=" + std::to_string(s.seq) + "&dur=" + std::to_string(s.duration_ms),
                            header + "Content-Type: video/mp2t\r\n", s.bytes.data(), s.bytes.size());
        const Nanos took = now_ns() - start;
        if (r.status == 403) {
            // The server's owner turned it off, or a new key is out: the control thread asks next.
            log("player: live: the server refused a segment");
            g_on.store(false);
            g_want.store(false);
            continue;
        }
        if (r.status / 100 != 2) {
            log("player: live: upload failed, status %d", r.status);
            g_dropped.fetch_add(1, std::memory_order_relaxed);
        } else {
            g_uploaded.fetch_add(1, std::memory_order_relaxed);
        }
        // The share of a segment's own length its upload took. Two near the whole length: a step down. A long good run
        // (a minute of them): a step back up. A refusal (a full disk, say) says nothing about the network.
        const double share = s.duration_ms > 0 ? static_cast<double>(took) / (static_cast<double>(s.duration_ms) * 1e6) : 0;
        if (r.status == 0 || share > 0.8) {
            fast = 0;
            if (++slow >= 2) {
                slow = 0;
                g_network_step.store(std::min(g_network_step.load() + 1, kLastStep));
            }
        } else {
            slow = 0;
            if (share < 0.3 && ++fast >= 30) {
                fast = 0;
                g_network_step.store(std::max(g_network_step.load() - 1, 0));
            }
        }
    }
}

// ---- pictures from the render thread to the encoder thread

struct Frame {
    std::vector<std::uint8_t> nv12;  // width x height of luma, then width x height / 2 of chroma pairs
    int width = 0, height = 0;
    Nanos pts = 0;                   // when the frame went to the screen
};

std::mutex g_frame_lock;
std::condition_variable g_frame_wake;
std::deque<Frame> g_frames;
// Picture buffers the encoder is done with, for the render thread's next pictures: a 1080p picture is 3 MB, and a new
// one each time would cost the render thread its allocation and the first touch of every page. Under g_frame_lock.
std::vector<std::vector<std::uint8_t>> g_spare;
constexpr std::size_t kSpare = 8;

// A picture's buffer back to the spares (under g_frame_lock), as long as there are few.
void recycle(std::vector<std::uint8_t>&& buffer) {
    if (g_spare.size() < kSpare && buffer.capacity()) g_spare.push_back(std::move(buffer));
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
        Segment s;
        s.bytes = std::move(ts_.bytes());
        ts_.bytes().clear();
        s.seq = seq_++;
        s.duration_ms = static_cast<int>((end - segment_start_) / 1000000);
        queue_segment(std::move(s));
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
        "(worst %llu), %llu segments up, %llu lost, %llu AAC frames", step(),
        static_cast<unsigned long long>(n), static_cast<unsigned long long>(g_skipped.exchange(0)),
        static_cast<unsigned long long>(n ? total / n / 1000 : 0), static_cast<unsigned long long>(g_capture_max_ns.exchange(0) / 1000),
        static_cast<unsigned long long>(handed ? hand_total / handed / 1000 : 0), static_cast<unsigned long long>(g_hand_max_ns.exchange(0) / 1000),
        static_cast<unsigned long long>(g_uploaded.exchange(0)), static_cast<unsigned long long>(g_dropped.exchange(0)),
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

void encoder_main() {
    background_thread("live-encode");
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    mf()->startup(MF_VERSION, MFSTARTUP_LITE);
    Nanos next_stats = now_ns() + 60 * kSecond;
    std::unique_ptr<Encoder> encoder;
    for (;;) {
        Frame f;
        bool have = false;
        {
            std::unique_lock<std::mutex> l(g_frame_lock);
            // A frame, or a look at the sound every 10 ms.
            g_frame_wake.wait_for(l, std::chrono::milliseconds(10), [] { return !g_frames.empty(); });
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
        const bool sent = !have || encoder->picture(f);
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
    }
}

// ---- the render thread: GL in the game's own context, everything of its state put back

// An EGL entry point of the system's library (ANGLE's on Windows), looked up by name.
void* egl_proc(const char* name) {
    static void* lib = dlopen(kHostEgl, RTLD_NOW | RTLD_LOCAL);
    return lib ? dlsym(lib, name) : nullptr;
}

// The host's GL entry points (gl_bridge.h's gl_proc), looked up once.
struct Gl {
    PFNGLGETINTEGERVPROC get_integer;
    PFNGLISENABLEDPROC is_enabled;
    PFNGLENABLEPROC enable;
    PFNGLDISABLEPROC disable;
    PFNGLGETBOOLEANVPROC get_boolean;
    PFNGLCOLORMASKPROC color_mask;
    PFNGLVIEWPORTPROC viewport;
    PFNGLGENTEXTURESPROC gen_textures;
    PFNGLDELETETEXTURESPROC delete_textures;
    PFNGLBINDTEXTUREPROC bind_texture;
    PFNGLACTIVETEXTUREPROC active_texture;
    PFNGLTEXSTORAGE2DPROC tex_storage;
    PFNGLTEXPARAMETERIPROC tex_parameter;
    PFNGLBINDSAMPLERPROC bind_sampler;
    PFNGLGENFRAMEBUFFERSPROC gen_framebuffers;
    PFNGLDELETEFRAMEBUFFERSPROC delete_framebuffers;
    PFNGLBINDFRAMEBUFFERPROC bind_framebuffer;
    PFNGLFRAMEBUFFERTEXTURE2DPROC framebuffer_texture;
    PFNGLCHECKFRAMEBUFFERSTATUSPROC check_framebuffer;
    PFNGLBLITFRAMEBUFFERPROC blit;
    PFNGLCREATESHADERPROC create_shader;
    PFNGLSHADERSOURCEPROC shader_source;
    PFNGLCOMPILESHADERPROC compile_shader;
    PFNGLGETSHADERIVPROC get_shader;
    PFNGLGETSHADERINFOLOGPROC shader_log;
    PFNGLDELETESHADERPROC delete_shader;
    PFNGLCREATEPROGRAMPROC create_program;
    PFNGLATTACHSHADERPROC attach_shader;
    PFNGLLINKPROGRAMPROC link_program;
    PFNGLGETPROGRAMIVPROC get_program;
    PFNGLDELETEPROGRAMPROC delete_program;
    PFNGLUSEPROGRAMPROC use_program;
    PFNGLGETUNIFORMLOCATIONPROC uniform_location;
    PFNGLUNIFORM1IPROC uniform_int;
    PFNGLGENVERTEXARRAYSPROC gen_vertex_arrays;
    PFNGLDELETEVERTEXARRAYSPROC delete_vertex_arrays;
    PFNGLBINDVERTEXARRAYPROC bind_vertex_array;
    PFNGLDRAWARRAYSPROC draw_arrays;
    PFNGLGENBUFFERSPROC gen_buffers;
    PFNGLDELETEBUFFERSPROC delete_buffers;
    PFNGLBINDBUFFERPROC bind_buffer;
    PFNGLBUFFERDATAPROC buffer_data;
    PFNGLMAPBUFFERRANGEPROC map_buffer;
    PFNGLUNMAPBUFFERPROC unmap_buffer;
    PFNGLPIXELSTOREIPROC pixel_store;
    PFNGLREADPIXELSPROC read_pixels;
    PFNGLFENCESYNCPROC fence;
    PFNGLCLIENTWAITSYNCPROC client_wait;
    PFNGLDELETESYNCPROC delete_sync;
    bool ok = false;
};

template <class T>
void gl_look_up(T& out, const char* name, bool& ok) {
    out = reinterpret_cast<T>(gl_proc(name));
    if (!out) ok = false;
}

const Gl& gl() {
    static const Gl g = [] {
        Gl x{};
        bool ok = true;
        gl_look_up(x.get_integer, "glGetIntegerv", ok);
        gl_look_up(x.is_enabled, "glIsEnabled", ok);
        gl_look_up(x.enable, "glEnable", ok);
        gl_look_up(x.disable, "glDisable", ok);
        gl_look_up(x.get_boolean, "glGetBooleanv", ok);
        gl_look_up(x.color_mask, "glColorMask", ok);
        gl_look_up(x.viewport, "glViewport", ok);
        gl_look_up(x.gen_textures, "glGenTextures", ok);
        gl_look_up(x.delete_textures, "glDeleteTextures", ok);
        gl_look_up(x.bind_texture, "glBindTexture", ok);
        gl_look_up(x.active_texture, "glActiveTexture", ok);
        gl_look_up(x.tex_storage, "glTexStorage2D", ok);
        gl_look_up(x.tex_parameter, "glTexParameteri", ok);
        gl_look_up(x.bind_sampler, "glBindSampler", ok);
        gl_look_up(x.gen_framebuffers, "glGenFramebuffers", ok);
        gl_look_up(x.delete_framebuffers, "glDeleteFramebuffers", ok);
        gl_look_up(x.bind_framebuffer, "glBindFramebuffer", ok);
        gl_look_up(x.framebuffer_texture, "glFramebufferTexture2D", ok);
        gl_look_up(x.check_framebuffer, "glCheckFramebufferStatus", ok);
        gl_look_up(x.blit, "glBlitFramebuffer", ok);
        gl_look_up(x.create_shader, "glCreateShader", ok);
        gl_look_up(x.shader_source, "glShaderSource", ok);
        gl_look_up(x.compile_shader, "glCompileShader", ok);
        gl_look_up(x.get_shader, "glGetShaderiv", ok);
        gl_look_up(x.shader_log, "glGetShaderInfoLog", ok);
        gl_look_up(x.delete_shader, "glDeleteShader", ok);
        gl_look_up(x.create_program, "glCreateProgram", ok);
        gl_look_up(x.attach_shader, "glAttachShader", ok);
        gl_look_up(x.link_program, "glLinkProgram", ok);
        gl_look_up(x.get_program, "glGetProgramiv", ok);
        gl_look_up(x.delete_program, "glDeleteProgram", ok);
        gl_look_up(x.use_program, "glUseProgram", ok);
        gl_look_up(x.uniform_location, "glGetUniformLocation", ok);
        gl_look_up(x.uniform_int, "glUniform1i", ok);
        gl_look_up(x.gen_vertex_arrays, "glGenVertexArrays", ok);
        gl_look_up(x.delete_vertex_arrays, "glDeleteVertexArrays", ok);
        gl_look_up(x.bind_vertex_array, "glBindVertexArray", ok);
        gl_look_up(x.draw_arrays, "glDrawArrays", ok);
        gl_look_up(x.gen_buffers, "glGenBuffers", ok);
        gl_look_up(x.delete_buffers, "glDeleteBuffers", ok);
        gl_look_up(x.bind_buffer, "glBindBuffer", ok);
        gl_look_up(x.buffer_data, "glBufferData", ok);
        gl_look_up(x.map_buffer, "glMapBufferRange", ok);
        gl_look_up(x.unmap_buffer, "glUnmapBuffer", ok);
        gl_look_up(x.pixel_store, "glPixelStorei", ok);
        gl_look_up(x.read_pixels, "glReadPixels", ok);
        gl_look_up(x.fence, "glFenceSync", ok);
        gl_look_up(x.client_wait, "glClientWaitSync", ok);
        gl_look_up(x.delete_sync, "glDeleteSync", ok);
        x.ok = ok;
        return x;
    }();
    return g;
}

// The game's state that the capture touches, saved before it and put back after.
struct Saved {
    GLint read = 0, draw = 0, program = 0, active = 0, texture = 0, sampler = 0, vertex_array = 0, pack_buffer = 0;
    GLint viewport[4] = {0, 0, 0, 0};
    GLint pack_alignment = 4, pack_row_length = 0, pack_skip_rows = 0, pack_skip_pixels = 0;
    GLboolean mask[4] = {GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE};
    GLboolean enabled[8] = {};
};
// The switches a full-screen draw has to have off, in the order Saved keeps them.
constexpr GLenum kSwitches[8] = {GL_SCISSOR_TEST, GL_BLEND, GL_DEPTH_TEST, GL_STENCIL_TEST, GL_CULL_FACE, GL_RASTERIZER_DISCARD,
                                 GL_SAMPLE_ALPHA_TO_COVERAGE, GL_SAMPLE_COVERAGE};

void save_state(const Gl& g, Saved& s) {
    g.get_integer(GL_READ_FRAMEBUFFER_BINDING, &s.read);
    g.get_integer(GL_DRAW_FRAMEBUFFER_BINDING, &s.draw);
    g.get_integer(GL_CURRENT_PROGRAM, &s.program);
    g.get_integer(GL_ACTIVE_TEXTURE, &s.active);
    g.active_texture(GL_TEXTURE0);
    g.get_integer(GL_TEXTURE_BINDING_2D, &s.texture);
    g.get_integer(GL_SAMPLER_BINDING, &s.sampler);
    g.get_integer(GL_VERTEX_ARRAY_BINDING, &s.vertex_array);
    g.get_integer(GL_PIXEL_PACK_BUFFER_BINDING, &s.pack_buffer);
    g.get_integer(GL_VIEWPORT, s.viewport);
    g.get_integer(GL_PACK_ALIGNMENT, &s.pack_alignment);
    g.get_integer(GL_PACK_ROW_LENGTH, &s.pack_row_length);
    g.get_integer(GL_PACK_SKIP_ROWS, &s.pack_skip_rows);
    g.get_integer(GL_PACK_SKIP_PIXELS, &s.pack_skip_pixels);
    g.get_boolean(GL_COLOR_WRITEMASK, s.mask);
    for (int i = 0; i < 8; ++i) s.enabled[i] = g.is_enabled(kSwitches[i]);
}

void restore_state(const Gl& g, const Saved& s) {
    for (int i = 0; i < 8; ++i) {
        if (s.enabled[i]) g.enable(kSwitches[i]);
        else g.disable(kSwitches[i]);
    }
    g.color_mask(s.mask[0], s.mask[1], s.mask[2], s.mask[3]);
    g.pixel_store(GL_PACK_ALIGNMENT, s.pack_alignment);
    g.pixel_store(GL_PACK_ROW_LENGTH, s.pack_row_length);
    g.pixel_store(GL_PACK_SKIP_ROWS, s.pack_skip_rows);
    g.pixel_store(GL_PACK_SKIP_PIXELS, s.pack_skip_pixels);
    g.viewport(s.viewport[0], s.viewport[1], s.viewport[2], s.viewport[3]);
    g.bind_buffer(GL_PIXEL_PACK_BUFFER, static_cast<GLuint>(s.pack_buffer));
    g.bind_vertex_array(static_cast<GLuint>(s.vertex_array));
    g.bind_sampler(0, static_cast<GLuint>(s.sampler));
    g.bind_texture(GL_TEXTURE_2D, static_cast<GLuint>(s.texture));
    g.active_texture(static_cast<GLenum>(s.active));
    g.use_program(static_cast<GLuint>(s.program));
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, static_cast<GLuint>(s.read));
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, static_cast<GLuint>(s.draw));
}

// The conversion to NV12, one draw for each plane. A texel of the luma target holds four luma samples of a row, and
// one of the chroma target two pairs of Cb and Cr, each from a 2x2 block: read back as RGBA bytes, they are NV12's rows
// as they are. The scaled picture is twice the stream's size where the frame is that large (`scale`), and each of the
// stream's pixels the average of its 2x2 block: a blit alone scales by sampling, which shimmers on a frame three times
// larger. The rows go top to bottom, as the encoder wants them: GL's first row is the picture's last. BT.709, in the
// limited range video uses.
const char* kVertex = R"(#version 300 es
void main() {
    // One triangle over the whole target, from the vertex's number alone: no buffers.
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
)";
const char* kFragment = R"(#version 300 es
precision highp float;
precision highp int;
uniform highp sampler2D picture;
uniform int chroma;
uniform int scale;
out vec4 color;
const vec3 kY = vec3(0.2126, 0.7152, 0.0722);
// The stream's pixel (x, y), y from the top: the average of its block of the scaled picture.
vec3 pixel(int x, int y) {
    int top = textureSize(picture, 0).y - 1;
    vec3 sum = vec3(0.0);
    for (int j = 0; j < scale; ++j)
        for (int i = 0; i < scale; ++i)
            sum += texelFetch(picture, ivec2(x * scale + i, top - (y * scale + j)), 0).rgb;
    return sum / float(scale * scale);
}
float luma(vec3 c) { return (16.0 + 219.0 * dot(c, kY)) / 255.0; }
vec2 chromas(vec3 c) {
    float y = dot(c, kY);
    return (vec2(128.0) + 224.0 * vec2((c.b - y) / 1.8556, (c.r - y) / 1.5748)) / 255.0;
}
void main() {
    ivec2 o = ivec2(gl_FragCoord.xy);
    int x = o.x * 4;
    if (chroma == 0) {
        color = vec4(luma(pixel(x, o.y)), luma(pixel(x + 1, o.y)), luma(pixel(x + 2, o.y)), luma(pixel(x + 3, o.y)));
    } else {
        int y = o.y * 2;
        vec3 a = (pixel(x, y) + pixel(x + 1, y) + pixel(x, y + 1) + pixel(x + 1, y + 1)) * 0.25;
        vec3 b = (pixel(x + 2, y) + pixel(x + 3, y) + pixel(x + 2, y + 1) + pixel(x + 3, y + 1)) * 0.25;
        color = vec4(chromas(a), chromas(b));
    }
}
)";

GLuint compile(const Gl& g, GLenum kind, const char* text) {
    GLuint shader = g.create_shader(kind);
    g.shader_source(shader, 1, &text, nullptr);
    g.compile_shader(shader);
    GLint ok = 0;
    g.get_shader(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char why[512] = "";
        g.shader_log(shader, sizeof why, nullptr, why);
        log("player: live: the conversion's shader does not compile: %s", why);
        g.delete_shader(shader);
        return 0;
    }
    return shader;
}

struct Slot {
    // The pixel buffers the picture is read into, one per plane: luma, then the chroma pairs. ANGLE copies a read into a
    // pixel buffer to a staging texture of the read's size and packs it into the buffer when the buffer is mapped; a
    // second read into the same buffer would make it wait for the GPU to finish the first right there, and the other
    // plane's size would make it a new staging texture each time.
    GLuint buffer = 0, chroma_buffer = 0;
    GLsync fence = nullptr; // done on the GPU once this signals
    Nanos pts = 0;
    bool busy = false;
};

struct Capture {
    EGLContext context = EGL_NO_CONTEXT;
    EGLSurface surface = EGL_NO_SURFACE;
    int source_width = 0, source_height = 0;
    int width = 0, height = 0, fps = 0;
    int scale = 1;  // the scaled picture's pixels per stream pixel, each way: 2 where the frame is that large
    GLuint picture = 0, picture_fbo = 0, luma = 0, luma_fbo = 0, chroma = 0, chroma_fbo = 0, program = 0, vertex_array = 0;
    GLint chroma_uniform = -1;
    Slot slots[kSlots];
    int next_slot = 0;
    Nanos next_due = 0, last_picture = 0, retry_at = 0;
    bool live = false;
} g_capture;

// The conversion's program and vertex array, kept for the context's life: made again only with another context, so a
// capture that starts over (a quality step mid-song, a resize) compiles nothing on the render thread, where a compile
// shows as a stutter. The capture's own fields name the same objects without owning them.
struct Conversion {
    EGLContext context = EGL_NO_CONTEXT;
    GLuint program = 0, vertex_array = 0;
    GLint scale_uniform = -1, chroma_uniform = -1;
} g_conversion;

// A context the game has destroyed, until the render thread has seen it: a new one can get the same address, and the
// names of the old one's objects would then be the game's own.
std::atomic<void*> g_destroyed_context{nullptr};

// The picture's size: the height asked for, the frame's shape, in steps of 8 pixels (1920x1080, 1280x720, 856x480 for a
// 16:9 frame). Windows' encoder takes any even size and pads to its 16-pixel blocks itself, telling the decoder to crop:
// 1080 lines stay 1080, where 16-pixel steps would stretch them to 1088. The conversion packs four pixels a texel.
void picture_size(int source_width, int source_height, int height, int* width_out, int* height_out) {
    const int h = (height + 4) / 8 * 8;
    int w = static_cast<int>((static_cast<std::int64_t>(source_width) * h + source_height / 2) / source_height);
    w = (w + 4) / 8 * 8;
    *width_out = std::max(w, 16);
    *height_out = std::max(h, 16);
}

// The capture's objects gone, in its own context; outside it they went with the context.
void end_capture(Capture& c, bool context_is_current) {
    if (context_is_current) {
        const Gl& g = gl();
        for (Slot& s : c.slots) {
            if (s.fence) g.delete_sync(s.fence);
            if (s.buffer) g.delete_buffers(1, &s.buffer);
            if (s.chroma_buffer) g.delete_buffers(1, &s.chroma_buffer);
        }
        GLuint fbos[3] = {c.picture_fbo, c.luma_fbo, c.chroma_fbo};
        g.delete_framebuffers(3, fbos);
        GLuint textures[3] = {c.picture, c.luma, c.chroma};
        g.delete_textures(3, textures);
    }
    // The program and the vertex array stay (g_conversion).
    c = Capture{};
}

// A texture of `width` x `height` RGBA bytes, with a framebuffer drawing into it. False when the driver will not.
bool target(const Gl& g, int width, int height, GLuint* texture, GLuint* fbo) {
    g.gen_textures(1, texture);
    g.bind_texture(GL_TEXTURE_2D, *texture);
    g.tex_storage(GL_TEXTURE_2D, 1, GL_RGBA8, width, height);
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    g.tex_parameter(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    g.gen_framebuffers(1, fbo);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, *fbo);
    g.framebuffer_texture(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, *texture, 0);
    return g.check_framebuffer(GL_DRAW_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
}

// The capture's objects in the game's context, for pictures of the stream's size. The game's state as it was after.
bool begin_capture(Capture& c, EGLDisplay d, EGLContext context, EGLSurface s, int source_width, int source_height, Nanos now) {
    const Gl& g = gl();
    // A blit that scales takes OpenGL ES 3, and a frame without multisampling.
    static auto query_context = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLContext, EGLint, EGLint*)>(egl_proc("eglQueryContext"));
    static auto query_surface = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint, EGLint*)>(egl_proc("eglQuerySurface"));
    static auto choose_config = reinterpret_cast<EGLBoolean (*)(EGLDisplay, const EGLint*, EGLConfig*, EGLint, EGLint*)>(egl_proc("eglChooseConfig"));
    static auto config_attrib = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLConfig, EGLint, EGLint*)>(egl_proc("eglGetConfigAttrib"));
    EGLint version = 0, samples = 0, config_id = 0, found = 0;
    if (query_context) query_context(d, context, EGL_CONTEXT_CLIENT_VERSION, &version);
    EGLConfig config = nullptr;
    if (query_surface) query_surface(d, s, EGL_CONFIG_ID, &config_id);
    const EGLint by_id[] = {EGL_CONFIG_ID, config_id, EGL_NONE};
    if (choose_config && config_attrib && choose_config(d, by_id, &config, 1, &found) && found == 1) config_attrib(d, config, EGL_SAMPLE_BUFFERS, &samples);
    if (version < 3 || samples != 0) {
        log("player: live: the game's context is not usable (ES %d, %d sample buffers)", version, samples);
        g_gave_up.store(true);
        return false;
    }
    Saved saved;
    save_state(g, saved);
    c.context = context;
    c.surface = s;
    c.source_width = source_width;
    c.source_height = source_height;
    picture_size(source_width, source_height, step_height(step()), &c.width, &c.height);
    c.fps = step_fps(step());
    c.scale = source_width >= c.width * 2 && source_height >= c.height * 2 ? 2 : 1;
    bool ok = target(g, c.width * c.scale, c.height * c.scale, &c.picture, &c.picture_fbo);
    ok = ok && target(g, c.width / 4, c.height, &c.luma, &c.luma_fbo);
    ok = ok && target(g, c.width / 4, c.height / 2, &c.chroma, &c.chroma_fbo);
    Conversion& v = g_conversion;
    if (ok && (v.context != context || !v.program)) {
        // The first capture in this context: the program made once (a context before this one took its own along).
        v = Conversion{};
        GLuint vertex = compile(g, GL_VERTEX_SHADER, kVertex);
        GLuint fragment = vertex ? compile(g, GL_FRAGMENT_SHADER, kFragment) : 0;
        if (vertex && fragment) {
            v.program = g.create_program();
            g.attach_shader(v.program, vertex);
            g.attach_shader(v.program, fragment);
            g.link_program(v.program);
            GLint linked = 0;
            g.get_program(v.program, GL_LINK_STATUS, &linked);
            if (linked) {
                g.use_program(v.program);
                g.uniform_int(g.uniform_location(v.program, "picture"), 0);
                v.scale_uniform = g.uniform_location(v.program, "scale");
                v.chroma_uniform = g.uniform_location(v.program, "chroma");
                g.gen_vertex_arrays(1, &v.vertex_array);
                v.context = context;
            } else {
                g.delete_program(v.program);
                v.program = 0;
            }
        }
        if (vertex) g.delete_shader(vertex);
        if (fragment) g.delete_shader(fragment);
    }
    ok = ok && v.context == context && v.program;
    if (ok) {
        // This capture's scale, set in the program (its state, restored with the rest below).
        g.use_program(v.program);
        g.uniform_int(v.scale_uniform, c.scale);
        c.program = v.program;
        c.vertex_array = v.vertex_array;
        c.chroma_uniform = v.chroma_uniform;
    }
    // The pixel buffers, a plane of one NV12 picture each, read back by the CPU.
    const auto luma_bytes = static_cast<GLsizeiptr>(c.width) * c.height;
    for (Slot& slot : c.slots) {
        g.gen_buffers(1, &slot.buffer);
        g.bind_buffer(GL_PIXEL_PACK_BUFFER, slot.buffer);
        g.buffer_data(GL_PIXEL_PACK_BUFFER, luma_bytes, nullptr, GL_STREAM_READ);
        g.gen_buffers(1, &slot.chroma_buffer);
        g.bind_buffer(GL_PIXEL_PACK_BUFFER, slot.chroma_buffer);
        g.buffer_data(GL_PIXEL_PACK_BUFFER, luma_bytes / 2, nullptr, GL_STREAM_READ);
    }
    restore_state(g, saved);
    if (!ok) {
        log("player: live: the picture's conversion cannot be set up here");
        end_capture(c, true);
        g_gave_up.store(true);
        return false;
    }
    c.next_due = now;
    c.last_picture = now;
    c.live = true;
    return true;
}

// This frame into the next free slot: scaled, converted and read into its pixel buffer, none of it waited for.
void take_picture(Capture& c, Nanos now) {
    const Gl& g = gl();
    Slot& slot = c.slots[c.next_slot];
    if (slot.busy) {
        // The encoder side is behind: this picture is left out.
        g_skipped.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    // Each phase's time, for the stats (g_phase_ns): the clock read between them.
    Nanos mark = now_ns();
    auto phase = [&mark](int i) {
        const Nanos t = now_ns();
        g_phase_ns[i].fetch_add(static_cast<std::uint64_t>(t - mark), std::memory_order_relaxed);
        mark = t;
    };
    g_phase_ns[0].fetch_add(static_cast<std::uint64_t>(mark - now), std::memory_order_relaxed);
    Saved saved;
    save_state(g, saved);
    for (GLenum s : kSwitches) g.disable(s);
    g.color_mask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    phase(1);
    // The frame as it goes to the screen, scaled to the stream's size.
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, 0);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, c.picture_fbo);
    g.blit(0, 0, c.source_width, c.source_height, 0, 0, c.width * c.scale, c.height * c.scale, GL_COLOR_BUFFER_BIT, GL_LINEAR);
    phase(2);
    // Its two planes.
    g.use_program(c.program);
    g.bind_vertex_array(c.vertex_array);
    g.active_texture(GL_TEXTURE0);
    g.bind_texture(GL_TEXTURE_2D, c.picture);
    g.bind_sampler(0, 0);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, c.luma_fbo);
    g.viewport(0, 0, c.width / 4, c.height);
    g.uniform_int(c.chroma_uniform, 0);
    g.draw_arrays(GL_TRIANGLES, 0, 3);
    g.bind_framebuffer(GL_DRAW_FRAMEBUFFER, c.chroma_fbo);
    g.viewport(0, 0, c.width / 4, c.height / 2);
    g.uniform_int(c.chroma_uniform, 1);
    g.draw_arrays(GL_TRIANGLES, 0, 3);
    phase(3);
    // Each plane into its own buffer of the slot: NV12 once they are put one after the other.
    g.pixel_store(GL_PACK_ALIGNMENT, 4);
    g.pixel_store(GL_PACK_ROW_LENGTH, 0);
    g.pixel_store(GL_PACK_SKIP_ROWS, 0);
    g.pixel_store(GL_PACK_SKIP_PIXELS, 0);
    g.bind_buffer(GL_PIXEL_PACK_BUFFER, slot.buffer);
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, c.luma_fbo);
    g.read_pixels(0, 0, c.width / 4, c.height, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    g.bind_buffer(GL_PIXEL_PACK_BUFFER, slot.chroma_buffer);
    g.bind_framebuffer(GL_READ_FRAMEBUFFER, c.chroma_fbo);
    g.read_pixels(0, 0, c.width / 4, c.height / 2, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    phase(4);
    slot.fence = g.fence(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
    phase(5);
    slot.pts = now;
    slot.busy = true;
    c.next_slot = (c.next_slot + 1) % kSlots;
    restore_state(g, saved);
    phase(6);
    c.last_picture = now;
}

// The slots the GPU is done with, oldest first, copied out for the encoder. A slot still on the GPU ends the round:
// the ones after it are later still.
void collect(Capture& c) {
    const Gl& g = gl();
    for (int n = 0; n < kSlots; ++n) {
        Slot& slot = c.slots[(c.next_slot + n) % kSlots];
        if (!slot.busy) continue;
        const GLenum state = g.client_wait(slot.fence, GL_SYNC_FLUSH_COMMANDS_BIT, 0);
        if (state != GL_ALREADY_SIGNALED && state != GL_CONDITION_SATISFIED) return;
        const Nanos began = now_ns();
        g.delete_sync(slot.fence);
        slot.fence = nullptr;
        slot.busy = false;
        GLint bound = 0;
        g.get_integer(GL_PIXEL_PACK_BUFFER_BINDING, &bound);
        const std::size_t luma = static_cast<std::size_t>(c.width) * static_cast<std::size_t>(c.height);
        Frame f;
        {
            // A buffer the encoder gave back, when there is one: its pages are the process's already.
            std::lock_guard<std::mutex> l(g_frame_lock);
            if (!g_spare.empty()) {
                f.nv12 = std::move(g_spare.back());
                g_spare.pop_back();
            }
        }
        // Luma, then the chroma pairs after it: NV12.
        f.nv12.resize(luma + luma / 2);
        bool whole = true;
        const GLuint planes[2] = {slot.buffer, slot.chroma_buffer};
        const std::size_t offsets[2] = {0, luma}, sizes[2] = {luma, luma / 2};
        for (int p = 0; p < 2; ++p) {
            g.bind_buffer(GL_PIXEL_PACK_BUFFER, planes[p]);
            const void* mapped = g.map_buffer(GL_PIXEL_PACK_BUFFER, 0, static_cast<GLsizeiptr>(sizes[p]), GL_MAP_READ_BIT);
            if (!mapped) {
                whole = false;
                break;
            }
            std::memcpy(f.nv12.data() + offsets[p], mapped, sizes[p]);
            g.unmap_buffer(GL_PIXEL_PACK_BUFFER);
        }
        if (whole) {
            f.width = c.width;
            f.height = c.height;
            f.pts = slot.pts;
            std::lock_guard<std::mutex> l(g_frame_lock);
            // The encoder is behind: the oldest picture goes, its buffer kept.
            if (g_frames.size() >= kFrameQueue) {
                recycle(std::move(g_frames.front().nv12));
                g_frames.pop_front();
                g_skipped.fetch_add(1, std::memory_order_relaxed);
            }
            g_frames.push_back(std::move(f));
            g_frame_wake.notify_one();
        }
        g.bind_buffer(GL_PIXEL_PACK_BUFFER, static_cast<GLuint>(bound));
        // What handing it over took on this thread.
        const auto took = static_cast<std::uint64_t>(now_ns() - began);
        g_handed.fetch_add(1, std::memory_order_relaxed);
        g_hand_ns.fetch_add(took, std::memory_order_relaxed);
        if (took > g_hand_max_ns.load(std::memory_order_relaxed)) g_hand_max_ns.store(took, std::memory_order_relaxed);
    }
}

// ---- the control thread

void control_main() {
    background_thread("live-control");
    Nanos next_poll = 0;
    bool was_on = false;
    const std::string lang = player::host_locale().first == "ko" ? "ko" : "en";
    for (;;) {
        sleep_ns(kSecond);
        const Nanos now = now_ns();
        const bool away = now - g_last_swap.load(std::memory_order_relaxed) > kAwayAfter;
        const bool want_now = g_on.load() && !away && !g_gave_up.load() && !g_paused.load();
        if (g_want.load() != want_now) g_want.store(want_now);
        // Away from the screen: nothing to send. The next request goes out as soon as the game is back.
        if (away) {
            next_poll = 0;
            continue;
        }
        if (now < next_poll && (g_on.load() || !was_on)) continue;
        next_poll = now + kPollEvery;
        // The id the game signs in with, which the server knows this player by.
        const std::string ids = player::device_id();
        if (ids.empty()) continue;
        static bool first_request = true;
        if (first_request) {
            first_request = false;
            log("player: live: asking the server");
        }
        HttpResult r = http("GET", "/live/state?ids=" + ids + "&lang=" + lang, "", nullptr, 0);
        // No answer: as things were. A server without live view (an older one) answers 404: off.
        if (r.status == 0) continue;
        const std::string token = json_string(r.body, "token");
        // It goes into a request header: only what a token is made of.
        const bool token_ok = !token.empty() && token.size() <= 128 &&
                              std::all_of(token.begin(), token.end(), [](char x) { return std::isalnum(static_cast<unsigned char>(x)) || x == '-' || x == '_'; });
        const bool on = r.status == 200 && json_bool(r.body, "on") && token_ok;
        {
            std::lock_guard<std::mutex> l(g_identity_lock);
            g_ids = ids;
            if (on) g_token = token;
        }
        if (on) {
            g_fps.store(std::clamp(json_int(r.body, "fps", 30), 5, 60));
            g_height.store(std::clamp(json_int(r.body, "height", 720), 144, 1080));
            g_bitrate.store(std::clamp(json_int(r.body, "bitrate", 2000000), 100000, 20000000));
            g_segment.store(std::clamp(json_int(r.body, "segment", 2), 1, 10));
            static bool workers = false;
            if (!workers) {
                workers = true;
                std::thread(encoder_main).detach();
                std::thread(upload_main).detach();
            }
        }
        if (was_on && !on) {
            g_end_due.store(true);
            std::lock_guard<std::mutex> l(g_upload_lock);
            g_upload_wake.notify_one();
            // Back at the top step for the next time.
            g_network_step.store(0);
        }
        g_on.store(on);
        was_on = on;
        const std::string notice = json_string(r.body, "toast");
        // A PC that cannot encode sends nothing: the server's "you are live" would not be true here.
        if (!notice.empty() && on && g_gave_up.load()) {
            log("player: live: the server's notice left out, this PC sends no broadcast: %s", notice.c_str());
        } else if (!notice.empty()) {
            player::show_notice(notice, on);
        }
    }
}

// The server's address, from the packer's line in the tweaks file beside the app's libraries ("server <host[:port]>"),
// or PLAYER_LIVE_SERVER. Empty without one.
std::string server_address() {
    if (const char* test = std::getenv("PLAYER_LIVE_SERVER"); test && *test) return test;
    std::ifstream f(player::utf8_path(player::app().host_libs + "/libarm32t-tweaks.so"));
    std::string line, server;
    while (std::getline(f, line)) {
        std::istringstream in(line);
        std::string word, value;
        if ((in >> word >> value) && word == "server") server = value;
    }
    return server;
}

// Once, at the first swap: the server's address, and whether this Windows can encode at all.
bool set_up() {
    if (!requested("PLAYER_LIVE", "", true)) return false;
    const std::string server = server_address();
    if (server.empty()) return false;
    if (!mf()) {
        log("player: live: this Windows has no Media Foundation (an N edition without its Media Feature Pack): no broadcasts");
        return false;
    }
    const std::size_t colon = server.rfind(':');
    g_host = server.substr(0, colon);
    if (colon != std::string::npos) g_port = std::atoi(server.c_str() + colon + 1);
    g_host_header = server;
    player::audio::set_mix_tap(mix_tap);
    log("player: live: asks %s", server.c_str());
    std::thread(control_main).detach();
    return true;
}

}  // namespace

void desktop_live_frame(EGLDisplay d, EGLSurface s) {
    static const bool ready = set_up();
    if (!ready) return;
    g_enabled.store(true, std::memory_order_relaxed);
    const Nanos start = now_ns();
    g_last_swap.store(start, std::memory_order_relaxed);
    Capture& c = g_capture;
    const bool want = g_want.load(std::memory_order_relaxed);
    // The usual case, by far.
    if (!want && !c.live) return;
    if (!gl().ok) return;
    static auto current_context = reinterpret_cast<EGLContext (*)()>(egl_proc("eglGetCurrentContext"));
    static auto current_surface = reinterpret_cast<EGLSurface (*)(EGLint)>(egl_proc("eglGetCurrentSurface"));
    static auto query_surface = reinterpret_cast<EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint, EGLint*)>(egl_proc("eglQuerySurface"));
    if (!current_context || !current_surface || !query_surface) return;
    const EGLContext context = current_context();
    // A context the game destroyed took the program along: made again in the next one.
    if (void* dead = g_destroyed_context.load(std::memory_order_relaxed)) {
        if (dead == g_conversion.context) g_conversion = Conversion{};
        // With no capture to end, nothing else waits for it: a new context at the same address is a new one.
        if (!c.live) g_destroyed_context.store(nullptr, std::memory_order_relaxed);
    }
    if (c.live) {
        // Each of these means this capture is over: a new one follows at a later frame if wanted.
        const bool gone = g_destroyed_context.load(std::memory_order_relaxed) == c.context;
        if (gone) g_destroyed_context.store(nullptr, std::memory_order_relaxed);
        const bool same_context = context == c.context && !gone;
        EGLint w = 0, h = 0;
        if (s == c.surface) {
            query_surface(d, s, EGL_WIDTH, &w);
            query_surface(d, s, EGL_HEIGHT, &h);
        }
        int picture_w = 0, picture_h = 0;
        picture_size(c.source_width, c.source_height, step_height(step()), &picture_w, &picture_h);
        if (!want || !same_context || s != c.surface || w != c.source_width || h != c.source_height || picture_h != c.height ||
            c.fps != step_fps(step()) || start - c.last_picture > kRestartAfter) {
            end_capture(c, same_context);
            return;
        }
        // What the GPU has finished, out to the encoder.
        collect(c);
    }
    if (!c.live) {
        if (!want || start < c.retry_at || g_gave_up.load(std::memory_order_relaxed)) return;
        // Only the frame going to the window, drawn on the current context.
        if (context == EGL_NO_CONTEXT || current_surface(EGL_DRAW) != s) return;
        EGLint w = 0, h = 0;
        query_surface(d, s, EGL_WIDTH, &w);
        query_surface(d, s, EGL_HEIGHT, &h);
        if (w <= 0 || h <= 0) return;
        if (!begin_capture(c, d, context, s, w, h, start)) c.retry_at = start + 10 * kSecond;
        return;
    }
    const Nanos interval = kSecond / c.fps;
    if (start + kCaptureTolerance < c.next_due) return;
    c.next_due = std::max(c.next_due + interval, start);
    take_picture(c, start);
    const std::uint64_t took = static_cast<std::uint64_t>(now_ns() - start);
    g_captures.fetch_add(1, std::memory_order_relaxed);
    g_capture_ns.fetch_add(took, std::memory_order_relaxed);
    if (took > g_capture_max_ns.load(std::memory_order_relaxed)) g_capture_max_ns.store(took, std::memory_order_relaxed);
}

// The game destroyed a context (egl_bridge.cpp, through live_context_destroyed in frames.cpp).
void desktop_live_context_destroyed(EGLContext context) { g_destroyed_context.store(context, std::memory_order_relaxed); }

void desktop_live_paused(bool paused) {
    g_paused.store(paused);
    // Held still: the stream ends now, its last segment closed as usual, rather than after the seconds a game away from
    // the screen is given; a stream of its own starts as the game goes on (the control thread's next look).
    if (paused) g_want.store(false);
}

}  // namespace arm32

#endif
