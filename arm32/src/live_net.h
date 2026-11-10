// The broadcast's requests to the server, the same on a phone (live.cpp) and on a computer (desktop/live_desktop.cpp):
// plain HTTP, one request per connection, each within a deadline from the name's lookup to the answer's end; the
// server's small JSON answers and the checks on them; the upload thread with its queue of segments; and the network's
// quality step, which the uploads move. What differs between the two comes in as arguments (Link::Names): the log's
// prefix, the requests' User-Agent, and the names and start of the threads here.
#pragma once

#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <vector>

// getaddrinfo's list, for the lookup's form below (<netdb.h> has it).
struct addrinfo;

namespace arm32::live {

using Nanos = std::int64_t;
inline constexpr Nanos kSecond = 1000000000;
// Segments waiting for the network, at most: the oldest goes when another comes.
inline constexpr std::size_t kUploadQueue = 3;
// The server takes up to 4 MB; at these bitrates only a fault gets this far.
inline constexpr std::size_t kMaxSegment = 4 * 1024 * 1024 - 1024;
// The lowest of the quality steps (each side has its own frame rate, bitrate and height for them).
inline constexpr int kLastStep = 3;
// A request's time in all, from the lookup of the server's name to the answer's last byte: a server that answers a byte
// at a time, or never, and a resolver that does not answer, hold a thread no longer than this. A request cut there has
// no answer, as one that failed. A segment is ten seconds at most, so an upload this slow counts as slow anyway.
inline constexpr Nanos kRequestLimit = 10 * kSecond;
// The most of an answer read: a notice and a few numbers. A longer one is none of the server's, and counts as none.
inline constexpr std::size_t kMaxAnswer = 65536;
// How long the addresses a lookup found are used without another: a phone uploads every two seconds or so.
inline constexpr Nanos kLookupKept = 60 * kSecond;

// The lookup of a name, getaddrinfo's form: getaddrinfo itself, or the tests' stand-in (its list freed by freeaddrinfo).
using Resolver = int (*)(const char* host, const char* service, const struct addrinfo* hints, struct addrinfo** result);

// The monotonic clock, in nanoseconds.
Nanos now_ns();

// The server: its name or address, its port, and how a request names it (the Host header).
struct Server {
    std::string host;
    int port = 80;
    std::string host_header;
};

// "host[:port]", as the packer's line in the tweaks file and the test settings give it.
Server parse_server(const std::string& text);

// A request's answer: its status (0: no answer, one cut by the deadline or past kMaxAnswer included) and its body.
struct HttpResult {
    int status = 0;
    std::string body;
};

// ---- the server's small JSON answers: flat, with known keys

// Where the value of "key" starts, or npos.
std::size_t json_value(const std::string& json, const char* key);
// The value of "key" is true.
bool json_bool(const std::string& json, const char* key);
// The value of "key" as a whole number, `fallback` when it is none.
int json_int(const std::string& json, const char* key, int fallback);
// A string value as UTF-8, with the escapes PHP's json_encode writes (\uXXXX for Korean, a pair of them for a character
// past U+FFFF); "" for one without its end. NUL is left out, and half a pair alone is U+FFFD.
std::string json_string(const std::string& json, const char* key);
// UTF-8 text as JNI's NewStringUTF takes it, modified UTF-8: a character past U+FFFF as its two UTF-16 halves of three
// bytes each, NUL as two bytes, and each byte that starts no character as U+FFFD (CheckJNI ends the app on those).
std::string modified_utf8(std::string_view text);

// What GET /live/state answered, checked.
struct State {
    bool answered = false;  // any answer at all: without one everything stays as it was
    bool on = false;        // live view is on for this player, with a key that can go in a request
    std::string token;      // that key ("" when off)
    // The stream the server asks for, within what this code makes; its defaults where the answer has none.
    int fps = 30, height = 720, bitrate = 2000000, segment = 2;
    std::string toast;      // the server's notice for the player ("" for none)
};

// The checks on GET /live/state's answer: on only with status 200, "on" true and a token of at most 128 letters,
// digits, '-' and '_' (it goes into a request header as it is); the numbers within 5 to 60 frames a second, 144 to 1080
// lines, 100 kbit/s to 20 Mbit/s and 1 to 10 s a segment.
State parse_state(const HttpResult& r);

// Adds a device id to the comma-separated list the requests name the player by, once, and only when it is made of what
// the login's ids are made of (letters, digits, '-' and '_', at most 128): the list goes into a URL as it is.
void add_id(std::string& ids, std::string_view id);

// A segment of the stream, for the upload thread.
struct Segment {
    std::vector<std::uint8_t> bytes;
    int seq = 0;
    int duration_ms = 0;
};

// The requests of one broadcast's side, its upload queue and thread, and the network's step: one for the process.
class Link {
public:
    // What differs between a phone and a computer.
    struct Names {
        const char* log_prefix;             // before each log line ("arm32: live", "player: live")
        const char* user_agent;             // every request's User-Agent
        const char* upload_thread;          // the upload thread's name
        const char* lookup_thread;          // the name of the thread that looks the server's name up
        void (*thread_start)(const char*);  // run first on those threads with their names: name, priority, signals
    };

    explicit Link(const Names& names) : names_(names) {}

    // The server every request goes to. Set once, before the first request.
    void set_server(const Server& server) { server_ = server; }
    const Server& server() const { return server_; }

    // One request, within `limit` in all: HTTP/1.0, so the answer needs no chunk decoding and ends where the connection
    // does. The control thread and the upload thread may each make one at the same time.
    HttpResult request(const char* method, const std::string& path, const std::string& extra_headers, const void* body,
                       std::size_t body_size);
    // GET /live/state for these ids, in this language for the notice ("ko" or "en"), checked.
    State ask_state(const std::string& ids, const char* lang) { return parse_state(request("GET", "/live/state?ids=" + ids + "&lang=" + lang, "", nullptr, 0)); }

    // The ids the requests name the player by, and from an answer that has it on, the stream's key.
    void set_identity(const std::string& ids, const State& state);
    // A segment for the upload thread. A full queue loses its oldest segment, which also takes the network's step down:
    // the newest pictures matter most. An empty one, or one past kMaxSegment, is not sent.
    void queue_segment(Segment&& s);
    // The stream has ended: the server is told once what is queued is out, and the network's step is back at the top
    // for the next stream.
    void end_stream();

    // The upload thread: names it and runs upload_one() for ever.
    [[noreturn]] void run();
    // One round of the upload thread: waits for a segment or the stream's end and sends it, then moves the network's
    // step by how the upload went.
    void upload_one();

    // The network's quality step: down for a full queue or two slow uploads, up after a minute of quick ones.
    std::atomic<int> network_step{0};
    // For the stats: segments the server took, and segments lost (queue full, or the upload failed).
    std::atomic<std::uint64_t> uploaded{0}, dropped{0};
    // Called on the upload thread when the server refuses a segment (403): its owner turned live view off, or a new
    // key is out, which the control thread's next request brings.
    void (*on_refused)() = nullptr;
    // A request's time in all (kRequestLimit; the tests give less), and how a name is looked up (nullptr: getaddrinfo;
    // the tests give a stand-in). Both set before the first request.
    Nanos limit = kRequestLimit;
    Resolver resolver = nullptr;

private:
    // A lookup of the server's name on a thread of its own, which requests wait for no longer than their deadlines.
    struct Lookup;
    // The lookup a request goes by once it is done: the last one, while it is out or under kLookupKept old with
    // addresses, or a new one. nullptr when none is done by the deadline, or no thread could be started for one.
    std::shared_ptr<Lookup> look_up(Nanos deadline);
    // Drops `lookup` (no address of it answered): the next request looks the name up again.
    void forget(const std::shared_ptr<Lookup>& lookup);

    const Names names_;
    Server server_;
    // The last lookup, under its lock.
    std::mutex lookup_lock_;
    std::shared_ptr<Lookup> lookup_;
    // The identity and the key, set by the control thread, read by the upload thread.
    std::mutex identity_lock_;
    std::string ids_, token_;
    // The queue, and the end of a stream to tell the server about once what is queued is out.
    std::mutex upload_lock_;
    std::condition_variable upload_wake_;
    std::deque<Segment> uploads_;
    std::atomic<bool> end_due_{false};
    // The upload thread's own: slow uploads in a row, and quick ones in a row.
    int slow_ = 0, fast_ = 0;
};

}  // namespace arm32::live
