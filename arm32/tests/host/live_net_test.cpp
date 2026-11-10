// Checks the broadcast's requests to the server (arm32/src/live_net.cpp) on the build machine, against stand-in servers
// on 127.0.0.1:
//   c++ -std=c++20 -pthread -Iarm32/src arm32/tests/host/live_net_test.cpp arm32/src/live_net.cpp -o /tmp/live_net_test && /tmp/live_net_test
//
// A request's deadline holds whatever the other side does: an answer a byte at a time, no answer, a server that takes
// no body, a resolver that does not answer; an answer longer than any of the server's is none. The server's answer to
// /live/state is read as meant, and odd JSON as nothing; the ids that go in a URL are filtered; the upload queue loses
// its oldest segment when full and steps the quality down, slow uploads step it down, quick ones back up, a refusal
// stops the stream, and the stream's end goes out last.
#include "live_net.h"

#include <arpa/inet.h>
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <functional>
#include <mutex>
#include <netdb.h>
#include <netinet/in.h>
#include <poll.h>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>
#include <vector>

// The log live_net.cpp writes to (host.h): kept, for the checks that look at it.
namespace arm32 {
std::mutex g_log_lock;
std::vector<std::string> g_log;
void log(const char* fmt, ...) {
    char line[512];
    va_list ap;
    va_start(ap, fmt);
    std::vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    std::lock_guard<std::mutex> l(g_log_lock);
    g_log.push_back(line);
}
}  // namespace arm32

namespace {

using namespace arm32::live;

int g_checks = 0, g_failures = 0;

// One check: its name and whether it held, with what was seen when it did not.
void check(bool ok, const std::string& what, const std::string& seen = "") {
    ++g_checks;
    if (ok) return;
    ++g_failures;
    std::printf("FAIL %s%s%s\n", what.c_str(), seen.empty() ? "" : ": ", seen.c_str());
}

// Seconds since `start`.
double since(std::chrono::steady_clock::time_point start) { return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count(); }

// A stand-in server on 127.0.0.1, on a port of its own: each connection, one after another, goes to `handle`, which may
// hold it while the server is not stopping. Stopping (the destructor) ends the handler's waits and the thread.
class Stand {
public:
    using Handler = std::function<void(int fd, Stand& server)>;

    explicit Stand(Handler handle) : handle_(std::move(handle)) {
        listener_ = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
        sockaddr_in a{};
        a.sin_family = AF_INET;
        a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        // Port 0: one the system picks, free.
        bind(listener_, reinterpret_cast<sockaddr*>(&a), sizeof a);
        listen(listener_, 16);
        socklen_t length = sizeof a;
        getsockname(listener_, reinterpret_cast<sockaddr*>(&a), &length);
        port_ = ntohs(a.sin_port);
        thread_ = std::thread([this] { run(); });
    }

    ~Stand() { stop(); }

    // Ends the handler's waits and closes the port: a request after this finds nobody there.
    void stop() {
        if (stopping_.exchange(true)) return;
        // A connection of its own wakes the accept below, which then sees stopping_ (shutting the listener down would
        // on Linux only, not on Windows).
        const int poke = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
        sockaddr_in a{};
        a.sin_family = AF_INET;
        a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        a.sin_port = htons(static_cast<std::uint16_t>(port_));
        connect(poke, reinterpret_cast<sockaddr*>(&a), sizeof a);
        thread_.join();
        close(poke);
        close(listener_);
    }

    int port() const { return port_; }
    std::string address() const { return "127.0.0.1:" + std::to_string(port_); }
    bool stopping() const { return stopping_.load(); }

    // Waits `ms` milliseconds, less when stopping. False when it stopped.
    bool hold(int ms) {
        for (int waited = 0; waited < ms; waited += 10) {
            if (stopping()) return false;
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        return !stopping();
    }

    // What the requests were, each its head and body, as read (read_request).
    std::vector<std::string> requests() {
        std::lock_guard<std::mutex> l(lock_);
        return requests_;
    }
    void note(const std::string& request) {
        std::lock_guard<std::mutex> l(lock_);
        requests_.push_back(request);
    }

    // A request's head and as much of its body as it says it has, read within five seconds.
    std::string read_request(int fd) {
        std::string in;
        char buffer[65536];
        const auto start = std::chrono::steady_clock::now();
        while (since(start) < 5 && !stopping()) {
            pollfd p{fd, POLLIN, 0};
            if (poll(&p, 1, 50) <= 0) continue;
            const ssize_t n = recv(fd, buffer, sizeof buffer, 0);
            if (n <= 0) break;
            in.append(buffer, static_cast<std::size_t>(n));
            const std::size_t end = in.find("\r\n\r\n");
            if (end == std::string::npos) continue;
            // The body's length, from its header (none: no body).
            const std::size_t at = in.find("Content-Length: ");
            const std::size_t length = at == std::string::npos || at > end ? 0 : std::strtoul(in.c_str() + at + 16, nullptr, 10);
            if (in.size() >= end + 4 + length) break;
        }
        note(in);
        return in;
    }

    // Sends all of `text`, as far as the client takes it.
    static void send_text(int fd, const std::string& text) {
        std::size_t at = 0;
        while (at < text.size()) {
            const ssize_t n = send(fd, text.data() + at, text.size() - at, MSG_NOSIGNAL);
            if (n <= 0) return;
            at += static_cast<std::size_t>(n);
        }
    }

private:
    void run() {
        for (;;) {
            const int fd = accept4(listener_, nullptr, nullptr, SOCK_CLOEXEC);
            if (fd < 0) return;
            // The stop's own connection, or one after it: nothing more to serve.
            if (stopping()) {
                close(fd);
                return;
            }
            handle_(fd, *this);
            close(fd);
        }
    }

    Handler handle_;
    int listener_ = -1, port_ = 0;
    std::atomic<bool> stopping_{false};
    std::thread thread_;
    std::mutex lock_;
    std::vector<std::string> requests_;
};

// A handler that reads the request and answers `text` at once.
Stand::Handler answer(const std::string& text) {
    return [text](int fd, Stand& s) {
        s.read_request(fd);
        Stand::send_text(fd, text);
    };
}

// The names each side gives its link, here the tests'.
const Link::Names kNames{"test: live", "live-net-test", "test-upload", "test-lookup", nullptr};

// Points `link` at `server`, with the tests' time limit.
void aim(Link& link, const std::string& server, Nanos limit) {
    link.set_server(parse_server(server));
    link.limit = limit;
}

// The request's time against the deadline: no shorter than the limit (less a little for the clock), and not much longer.
void check_cut(double took, double limit, const std::string& what) {
    char seen[64];
    std::snprintf(seen, sizeof seen, "%.3f s for a limit of %.3f s", took, limit);
    check(took >= limit - 0.05 && took < limit + 0.4, what + ": cut at the deadline", seen);
}

constexpr Nanos kTestLimit = 500000000;  // half a second, so the deadline's checks run quickly
constexpr double kTestLimitSeconds = 0.5;

void quick_answer() {
    Stand s(answer("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{\"on\":true,\"token\":\"k-1_A\",\"fps\":60,\"height\":1080,"
                   "\"bitrate\":6000000,\"segment\":4,\"toast\":\"\\uc624\\ub298\\n\\\"live\\\" \\\\ now\"}"));
    Link link(kNames);
    aim(link, s.address(), kTestLimit);
    const State st = link.ask_state("0123456789abcdef", "ko");
    check(st.answered && st.on && st.token == "k-1_A", "a quick answer: on, with its key");
    check(st.fps == 60 && st.height == 1080 && st.bitrate == 6000000 && st.segment == 4, "a quick answer: the stream's numbers");
    check(st.toast == "\xec\x98\xa4\xeb\x8a\x98\n\"live\" \\ now", "a quick answer: the notice, its escapes read", st.toast);
    s.stop();
    const std::vector<std::string> seen = s.requests();
    check(seen.size() == 1 && seen[0].rfind("GET /live/state?ids=0123456789abcdef&lang=ko HTTP/1.0\r\n", 0) == 0, "a quick answer: the request line",
          seen.empty() ? "" : seen[0]);
    check(seen.size() == 1 && seen[0].find("\r\nHost: " + s.address() + "\r\n") != std::string::npos &&
              seen[0].find("\r\nUser-Agent: live-net-test\r\n") != std::string::npos,
          "a quick answer: the Host and the side's User-Agent");
}

void trickle() {
    // The status line and the headers' end at once, then a byte every 50 ms for as long as the client stays.
    Stand s([](int fd, Stand& server) {
        server.read_request(fd);
        Stand::send_text(fd, "HTTP/1.0 200 OK\r\n\r\n{");
        while (server.hold(50)) {
            if (send(fd, " ", 1, MSG_NOSIGNAL) <= 0) return;
        }
    });
    Link link(kNames);
    aim(link, s.address(), kTestLimit);
    const auto start = std::chrono::steady_clock::now();
    const HttpResult r = link.request("GET", "/live/state?ids=a&lang=en", "", nullptr, 0);
    check_cut(since(start), kTestLimitSeconds, "an answer a byte at a time");
    check(r.status == 0, "an answer a byte at a time: no answer");
}

void silent() {
    // The request read, then nothing until the client goes.
    Stand s([](int fd, Stand& server) {
        server.read_request(fd);
        while (server.hold(50)) {
            pollfd p{fd, POLLIN, 0};
            // The client gone: nothing left to hold.
            if (poll(&p, 1, 0) > 0) return;
        }
    });
    Link link(kNames);
    aim(link, s.address(), kTestLimit);
    const auto start = std::chrono::steady_clock::now();
    const HttpResult r = link.request("GET", "/live/state?ids=a&lang=en", "", nullptr, 0);
    check_cut(since(start), kTestLimitSeconds, "no answer at all");
    check(r.status == 0, "no answer at all: no answer");
}

void takes_no_body() {
    // The connection taken, nothing read: the client's sending stops once the buffers between are full.
    Stand s([](int, Stand& server) { server.hold(5000); });
    Link link(kNames);
    aim(link, s.address(), kTestLimit);
    // More than the buffers of a connection on one machine hold.
    std::vector<std::uint8_t> body(64 * 1024 * 1024, 0x47);
    const auto start = std::chrono::steady_clock::now();
    const HttpResult r = link.request("POST", "/live/upload?ids=a&seq=0&dur=2000", "X-Live-Token: k\r\n", body.data(), body.size());
    check_cut(since(start), kTestLimitSeconds, "a server that takes no body");
    check(r.status == 0, "a server that takes no body: no answer");
}

void too_long() {
    // An answer just under the limit is read whole; one past it is no answer.
    const std::string head = "HTTP/1.0 200 OK\r\n\r\n";
    Stand under(answer(head + std::string(kMaxAnswer - head.size(), 'x')));
    Link a(kNames);
    aim(a, under.address(), 5 * kSecond);
    const HttpResult r1 = a.request("GET", "/", "", nullptr, 0);
    check(r1.status == 200 && r1.body.size() == kMaxAnswer - head.size(), "an answer of the most that is read: read whole",
          std::to_string(r1.status) + ", " + std::to_string(r1.body.size()) + " bytes");
    Stand over(answer(head + std::string(10 * 1024 * 1024, 'x')));
    Link b(kNames);
    aim(b, over.address(), 5 * kSecond);
    const auto start = std::chrono::steady_clock::now();
    const HttpResult r2 = b.request("GET", "/", "", nullptr, 0);
    check(r2.status == 0 && r2.body.empty(), "an answer of 10 MB: none of the server's, so no answer", std::to_string(r2.status));
    check(since(start) < 1, "an answer of 10 MB: given up at once, not read to its end");
}

void nobody_there() {
    // A port that was free a moment ago: refused at once.
    int port = 0;
    {
        Stand s(answer(""));
        port = s.port();
    }
    Link link(kNames);
    aim(link, "127.0.0.1:" + std::to_string(port), 5 * kSecond);
    const auto start = std::chrono::steady_clock::now();
    const HttpResult r = link.request("GET", "/", "", nullptr, 0);
    check(r.status == 0 && since(start) < 1, "nobody at the address: no answer, at once");
}

// The stand-in resolver: answers 127.0.0.1 and the port asked for, after g_resolve_ms, counting its calls.
std::atomic<int> g_resolves{0}, g_resolve_ms{0};
int slow_resolver(const char*, const char* service, const addrinfo* hints, addrinfo** result) {
    ++g_resolves;
    std::this_thread::sleep_for(std::chrono::milliseconds(g_resolve_ms.load()));
    addrinfo numeric = *hints;
    numeric.ai_flags |= AI_NUMERICHOST;
    return getaddrinfo("127.0.0.1", service, &numeric, result);
}

void slow_lookup() {
    Stand s([](int fd, Stand& server) {
        server.read_request(fd);
        Stand::send_text(fd, "HTTP/1.0 204 No Content\r\n\r\n");
    });
    // A name, not an address: it is looked up, by the stand-in, which takes two seconds.
    g_resolves = 0;
    g_resolve_ms = 2000;
    Link link(kNames);
    aim(link, "live.test:" + std::to_string(s.port()), 300000000);
    link.resolver = slow_resolver;
    auto start = std::chrono::steady_clock::now();
    const HttpResult r1 = link.request("GET", "/", "", nullptr, 0);
    check_cut(since(start), 0.3, "a resolver that does not answer");
    check(r1.status == 0, "a resolver that does not answer: no answer");
    start = std::chrono::steady_clock::now();
    const HttpResult r2 = link.request("GET", "/", "", nullptr, 0);
    check_cut(since(start), 0.3, "a second request while the lookup is out");
    check(r2.status == 0 && g_resolves == 1, "a second request while the lookup is out: waits for the same one",
          std::to_string(g_resolves.load()) + " lookups");
    // The lookup done (two seconds from the first request): its addresses serve the next requests, without another.
    std::this_thread::sleep_for(std::chrono::milliseconds(2000));
    const HttpResult r3 = link.request("GET", "/", "", nullptr, 0);
    const HttpResult r4 = link.request("GET", "/", "", nullptr, 0);
    check(r3.status == 204 && r4.status == 204 && g_resolves == 1, "the lookup done: its addresses for the next requests",
          std::to_string(r3.status) + " " + std::to_string(r4.status) + ", " + std::to_string(g_resolves.load()) + " lookups");
    // Nobody there any more: that request fails, and the next looks the name up again.
    s.stop();
    g_resolve_ms = 0;
    const HttpResult r5 = link.request("GET", "/", "", nullptr, 0);
    const HttpResult r6 = link.request("GET", "/", "", nullptr, 0);
    check(r5.status == 0 && r6.status == 0 && g_resolves == 2, "no address answering: the name looked up again",
          std::to_string(g_resolves.load()) + " lookups");
}

// ---- the server's answers, without a network

HttpResult answer_of(int status, const std::string& body) {
    HttpResult r;
    r.status = status;
    r.body = body;
    return r;
}

void state_answers() {
    const std::string good = R"({"on":true,"token":"abc","fps":30,"height":720,"bitrate":2000000,"segment":2,"toast":""})";
    check(parse_state(answer_of(200, good)).on, "state: on with a key");
    check(!parse_state(answer_of(0, good)).answered, "state: no answer is none");
    // Off, though answered: another status, no key, a key a header cannot carry, "on" not JSON's true.
    State s404 = parse_state(answer_of(404, good));
    check(s404.answered && !s404.on && s404.token.empty(), "state: 404 (a server without live view) is off");
    check(!parse_state(answer_of(500, good)).on, "state: 500 is off");
    check(!parse_state(answer_of(200, R"({"on":true})")).on, "state: on without a key is off");
    check(!parse_state(answer_of(200, R"({"on":true,"token":"a b"})")).on, "state: a key with a space is off");
    check(!parse_state(answer_of(200, R"({"on":true,"token":"a\r\nX-Evil: 1"})")).on, "state: a key with a line break is off");
    check(!parse_state(answer_of(200, "{\"on\":true,\"token\":\"" + std::string(129, 'a') + "\"}")).on, "state: a key of 129 is off");
    check(parse_state(answer_of(200, "{\"on\":true,\"token\":\"" + std::string(128, 'a') + "\"}")).on, "state: a key of 128 is on");
    check(!parse_state(answer_of(200, R"({"on":"true","token":"abc"})")).on, "state: \"on\" as a string is off");
    check(!parse_state(answer_of(200, R"({"on":1,"token":"abc"})")).on, "state: \"on\" as a number is off");
    check(!parse_state(answer_of(200, R"({"ON":true,"token":"abc"})")).on, "state: another key's case is off");
    check(parse_state(answer_of(200, "{ \"on\" :\n true , \"token\" : \"abc\" }")).on, "state: white space between is read");
    // A key's name inside a string is no key.
    check(!parse_state(answer_of(200, R"({"toast":"\"on\":true","token":"abc"})")).on, "state: \"on\" inside a string is no key");
    // An answer cut in the middle: a string without its end is no string.
    State cut = parse_state(answer_of(200, R"({"on":true,"token":"ab)"));
    check(!cut.on && cut.token.empty(), "state: a key cut short is none", cut.token);
    check(parse_state(answer_of(200, "<html>502 Bad Gateway</html>")).answered && !parse_state(answer_of(200, "<html></html>")).on,
          "state: a page that is no JSON is off");
    check(!parse_state(answer_of(200, "")).on, "state: an empty body is off");
    // The numbers: within what this code makes, the defaults where they are missing or no numbers.
    // Past what an int holds too (4294967300 would be 4 cut to 32 bits, 3000000000 a negative number).
    State big = parse_state(answer_of(200, R"({"on":true,"token":"a","fps":4294967300,"height":4294968296,"bitrate":3000000000,"segment":4294967297})"));
    check(big.fps == 60 && big.height == 1080 && big.bitrate == 20000000 && big.segment == 10, "state: numbers too large go to the most",
          std::to_string(big.fps) + " " + std::to_string(big.height) + " " + std::to_string(big.bitrate) + " " + std::to_string(big.segment));
    State small = parse_state(answer_of(200, R"({"on":true,"token":"a","fps":0,"height":1,"bitrate":1,"segment":0})"));
    check(small.fps == 5 && small.height == 144 && small.bitrate == 100000 && small.segment == 1, "state: numbers too small go to the least");
    State odd = parse_state(answer_of(200, R"({"on":true,"token":"a","fps":"60","height":-5,"bitrate":null,"segment":3.5})"));
    check(odd.fps == 30 && odd.height == 720 && odd.bitrate == 2000000 && odd.segment == 3, "state: what is no number is the default, a fraction its whole part",
          std::to_string(odd.fps) + " " + std::to_string(odd.height) + " " + std::to_string(odd.bitrate) + " " + std::to_string(odd.segment));
    // The notice's escapes, as PHP's json_encode writes them, and what is not a string.
    check(parse_state(answer_of(200, R"({"toast":"다시\r\n\t\/\b\f"})")).toast == "\xeb\x8b\xa4\xec\x8b\x9c\r\n\t/\b\f", "state: the notice's escapes");
    check(parse_state(answer_of(200, R"({"toast":"a\u0000b"})")).toast == "ab", "state: a NUL in the notice is left out");
    // An escape that is no number: its backslash and u left out, what follows read as it is, the string's end kept.
    check(parse_state(answer_of(200, R"({"toast":"a\u00zzb"})")).toast == "a00zzb", "state: an escape that is no number is left out");
    check(parse_state(answer_of(200, R"({"toast":"a\u0","on":true,"token":"abc"})")).toast == "a0" &&
              parse_state(answer_of(200, R"({"toast":"a\u0","on":true,"token":"abc"})")).on,
          "state: an escape cut short ends at the string's end");
    // A character past U+FFFF, as json_encode writes it (a UTF-16 pair): UTF-8's four bytes. Half of a pair: U+FFFD.
    check(parse_state(answer_of(200, R"({"toast":"\ud83c\udfb5 DMTQ"})")).toast == "\xf0\x9f\x8e\xb5 DMTQ", "state: a pair is one character");
    check(parse_state(answer_of(200, R"({"toast":"a\ud83cb"})")).toast == "a\xef\xbf\xbd" "b", "state: half a pair alone is U+FFFD");
    check(parse_state(answer_of(200, R"({"toast":"a\udfb5\ud83cb"})")).toast == "a\xef\xbf\xbd\xef\xbf\xbd" "b",
          "state: a pair the wrong way round is two U+FFFD");
    check(parse_state(answer_of(200, R"({"toast":5})")).toast.empty(), "state: a notice that is no string is none");
}

void modified() {
    // As NewStringUTF reads it: what is below U+10000 as it is, a character past it as two halves of three bytes.
    check(modified_utf8("a \xec\x98\xa4\n") == "a \xec\x98\xa4\n", "modified UTF-8: ASCII and Korean as they are");
    check(modified_utf8("\xf0\x9f\x8e\xb5!") == "\xed\xa0\xbc\xed\xbe\xb5!", "modified UTF-8: past U+FFFF as two halves");
    check(modified_utf8(std::string_view("a\0b", 3)) == "a\xc0\x80" "b", "modified UTF-8: NUL in two bytes");
    // What starts no character, byte by byte: a lone continuation byte, a cut character, a longer form of '/', a half.
    check(modified_utf8("a\x80" "b") == "a\xef\xbf\xbd" "b", "modified UTF-8: a lone continuation byte is U+FFFD");
    check(modified_utf8("\xec\x98") == "\xef\xbf\xbd\xef\xbf\xbd", "modified UTF-8: a character cut short, each byte U+FFFD");
    check(modified_utf8("\xc0\xaf") == "\xef\xbf\xbd\xef\xbf\xbd", "modified UTF-8: an overlong form is no character");
    check(modified_utf8("\xed\xa0\xbc") == "\xef\xbf\xbd\xef\xbf\xbd\xef\xbf\xbd", "modified UTF-8: a half in the UTF-8 is no character");
    check(modified_utf8("\xf4\x90\x80\x80") == "\xef\xbf\xbd\xef\xbf\xbd\xef\xbf\xbd\xef\xbf\xbd", "modified UTF-8: past U+10FFFF is no character");
}

void ids() {
    std::string list;
    add_id(list, "0123456789abcdef");
    add_id(list, "0123456789abcde");   // another id, not a part of the first
    add_id(list, "0123456789abcdef");  // the first again: once
    add_id(list, "Ab_9-z");
    check(list == "0123456789abcdef,0123456789abcde,Ab_9-z", "ids: plain ones, each once, compared whole", list);
    // What a URL would take otherwise.
    for (const char* bad : {"", "a&b=1", "a b", "a/b", "..", "a,b", "a%20b", "\xc3\xa9", "a\nb"}) {
        std::string l2 = "x";
        add_id(l2, bad);
        check(l2 == "x", std::string("ids: refused: ") + bad);
    }
    std::string l3;
    add_id(l3, std::string(129, 'a'));
    add_id(l3, std::string(128, 'b'));
    check(l3 == std::string(128, 'b'), "ids: at most 128 characters");
}

// ---- the upload queue and thread

// A segment of `bytes` bytes, numbered `seq`, `ms` long.
Segment segment(int seq, int ms, std::size_t bytes = 2000) {
    Segment s;
    s.bytes.assign(bytes, 0x47);
    s.seq = seq;
    s.duration_ms = ms;
    return s;
}

// The seq= of each upload request a server saw.
std::vector<int> seqs(Stand& s) {
    std::vector<int> out;
    for (const std::string& r : s.requests()) {
        const std::size_t at = r.find("&seq=");
        if (r.rfind("POST /live/upload", 0) == 0 && at != std::string::npos) out.push_back(std::atoi(r.c_str() + at + 5));
    }
    return out;
}

void full_queue() {
    Stand s(answer("HTTP/1.0 204 No Content\r\n\r\n"));
    Link link(kNames);
    aim(link, s.address(), 5 * kSecond);
    State on;
    on.on = true;
    on.token = "key";
    link.set_identity("dev1", on);
    // Nothing sent meanwhile (no upload thread): the queue holds three.
    for (int i = 0; i < 3; ++i) link.queue_segment(segment(i, 2000));
    check(link.dropped == 0 && link.network_step == 0, "a queue of three: nothing lost");
    // The fourth: the oldest goes, and the quality steps down.
    link.queue_segment(segment(3, 2000));
    check(link.dropped == 1 && link.network_step == 1, "a full queue: the oldest lost, a step down");
    for (int i = 0; i < 3; ++i) link.upload_one();
    s.stop();
    const std::vector<int> sent = seqs(s);
    check(sent == std::vector<int>({1, 2, 3}), "a full queue: the newest three sent, in order",
          sent.empty() ? "none" : std::to_string(sent.front()) + ".." + std::to_string(sent.back()));
    // More losses: a step each, down to the last step and no further.
    for (int i = 0; i < 8; ++i) link.queue_segment(segment(10 + i, 2000));
    check(link.network_step == kLastStep && link.dropped == 6, "a full queue again and again: down to the last step",
          std::to_string(link.network_step.load()) + ", " + std::to_string(link.dropped.load()) + " lost");
    // An empty segment and one larger than the server takes are not queued.
    Link other(kNames);
    aim(other, s.address(), kTestLimit);
    for (int i = 0; i < 3; ++i) other.queue_segment(segment(i, 2000, 0));
    other.queue_segment(segment(9, 2000, kMaxSegment + 1));
    other.queue_segment(segment(9, 2000, 0));
    check(other.dropped == 0 && other.network_step == 0, "empty and oversized segments are not queued");
}

void upload_steps() {
    // Answers after 150 ms: a 100 ms segment's upload takes longer than the segment.
    Stand slow([](int fd, Stand& server) {
        server.read_request(fd);
        server.hold(150);
        Stand::send_text(fd, "HTTP/1.0 204 No Content\r\n\r\n");
    });
    Link link(kNames);
    aim(link, slow.address(), 5 * kSecond);
    State on;
    on.on = true;
    on.token = "key";
    link.set_identity("dev1", on);
    link.queue_segment(segment(0, 100));
    link.upload_one();
    check(link.network_step == 0, "one slow upload: no step yet");
    link.queue_segment(segment(1, 100));
    link.upload_one();
    check(link.network_step == 1 && link.uploaded == 2, "two slow uploads: a step down", std::to_string(link.network_step.load()));
    slow.stop();
    // Quick ones: thirty in a row (a minute of two-second segments) take a step back up.
    Stand quick(answer("HTTP/1.0 204 No Content\r\n\r\n"));
    link.set_server(parse_server(quick.address()));
    for (int i = 0; i < 29; ++i) {
        link.queue_segment(segment(2 + i, 2000));
        link.upload_one();
    }
    check(link.network_step == 1, "29 quick uploads: still a step down");
    link.queue_segment(segment(31, 2000));
    link.upload_one();
    check(link.network_step == 0 && link.uploaded == 32, "30 quick uploads: back at the top", std::to_string(link.network_step.load()));
    quick.stop();
    // No answer at all counts as slow: two of them, a step down.
    Stand silent([](int fd, Stand& server) {
        server.read_request(fd);
        server.hold(5000);
    });
    link.set_server(parse_server(silent.address()));
    link.limit = 200000000;
    for (int i = 0; i < 2; ++i) {
        link.queue_segment(segment(40 + i, 2000));
        link.upload_one();
    }
    check(link.network_step == 1 && link.dropped == 2, "two uploads without an answer: lost, and a step down",
          std::to_string(link.network_step.load()) + ", " + std::to_string(link.dropped.load()) + " lost");
}

std::atomic<int> g_refused{0};

void refusal_and_end() {
    // 403 for the upload; 204 for anything else.
    Stand s([](int fd, Stand& server) {
        const std::string request = server.read_request(fd);
        Stand::send_text(fd, request.rfind("POST /live/upload", 0) == 0 ? "HTTP/1.0 403 Forbidden\r\n\r\n" : "HTTP/1.0 204 No Content\r\n\r\n");
    });
    Link link(kNames);
    aim(link, s.address(), 5 * kSecond);
    link.on_refused = [] { ++g_refused; };
    // The end of a stream that never had a key: nothing to tell the server.
    link.end_stream();
    link.upload_one();
    check(s.requests().empty(), "the end without a key: no request");
    State on;
    on.on = true;
    on.token = "key-2";
    link.set_identity("dev1,dev2", on);
    link.queue_segment(segment(0, 2000));
    {
        std::lock_guard<std::mutex> l(arm32::g_log_lock);
        arm32::g_log.clear();
    }
    link.upload_one();
    bool logged = false;
    {
        std::lock_guard<std::mutex> l(arm32::g_log_lock);
        for (const std::string& line : arm32::g_log) logged = logged || line == "test: live: the server refused a segment";
    }
    check(g_refused == 1 && link.uploaded == 0 && link.dropped == 0 && link.network_step == 0,
          "a refused segment: the side told, nothing counted, no step");
    check(logged, "a refused segment: in the log with the side's prefix");
    // Off, then the stream's end: after the segment queued before it, with the last key; the step back at the top.
    link.network_step = 2;
    link.queue_segment(segment(1, 2000));
    State off;
    link.set_identity("dev1,dev2", off);
    link.end_stream();
    check(link.network_step == 0, "the stream's end: the step back at the top");
    link.upload_one();
    link.upload_one();
    s.stop();
    const std::vector<std::string> seen = s.requests();
    check(seen.size() == 3 && seen[1].rfind("POST /live/upload?ids=dev1,dev2&seq=1&dur=2000 ", 0) == 0 &&
              seen[2].rfind("POST /live/end?ids=dev1,dev2 HTTP/1.0\r\n", 0) == 0 && seen[2].find("\r\nX-Live-Token: key-2\r\n") != std::string::npos,
          "the stream's end: last, with the stream's key", seen.empty() ? "" : seen.back());
}

}  // namespace

int main() {
    // Each check group, in turn; the network ones on 127.0.0.1 only.
    const struct {
        const char* name;
        void (*run)();
    } groups[] = {{"a quick answer", quick_answer},
                  {"an answer a byte at a time", trickle},
                  {"no answer at all", silent},
                  {"a server that takes no body", takes_no_body},
                  {"answers too long", too_long},
                  {"nobody there", nobody_there},
                  {"a resolver that does not answer", slow_lookup},
                  {"the state answer, odd JSON", state_answers},
                  {"the notice for a phone's Java", modified},
                  {"the ids", ids},
                  {"a full upload queue", full_queue},
                  {"the uploads' steps", upload_steps},
                  {"a refusal and the stream's end", refusal_and_end}};
    for (const auto& g : groups) {
        const int failures = g_failures;
        const auto start = std::chrono::steady_clock::now();
        g.run();
        std::printf("%s %s (%.2f s)\n", g_failures == failures ? "ok" : "FAILED", g.name, since(start));
    }
    if (g_failures) {
        std::printf("%d of %d checks FAILED\n", g_failures, g_checks);
        return 1;
    }
    std::printf("%d checks\nALL CHECKS PASSED\n", g_checks);
    return 0;
}
