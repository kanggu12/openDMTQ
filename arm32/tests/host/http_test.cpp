// Checks the player's HTTP client (arm32/desktop/http.cpp) on the build machine, against stand-in servers on 127.0.0.1:
//   c++ -std=c++20 -pthread -Iarm32/desktop arm32/tests/host/http_test.cpp arm32/desktop/http.cpp -lz -o /tmp/http_test && /tmp/http_test
//
// A request goes out asking for gzip, as a phone's does, unless the game chose its encodings itself. An answer the server
// compressed for it is inflated whole, whatever carries it (a length, chunks, the connection's close) and whatever the
// pieces it is read in, and comes without the headers of the compressed body; an answer not compressed, or compressed
// some other way, comes as it always did. A compressed answer cut short, broken, followed by more, or inflating past
// kMaxInflated fails as a lost connection does, after no more than that much.
#include "http.h"

#include <algorithm>
#include <arpa/inet.h>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <mutex>
#include <netinet/in.h>
#include <poll.h>
#include <string>
#include <strings.h>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>
#include <vector>
#include <zlib.h>

namespace {

namespace net = player::net;

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

// A stand-in server on 127.0.0.1, on a port of its own: each connection, one after another, goes to `handle`, which
// answers it and returns to close it. Stopping (the destructor) ends the thread.
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

    // Closes the port once the handler is done.
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

    std::string url(const std::string& path = "/DMQ/rpc") const { return "http://127.0.0.1:" + std::to_string(port_) + path; }

    // What the requests were, each as read (its head and body).
    std::vector<std::string> requests() {
        std::lock_guard<std::mutex> l(lock_);
        return requests_;
    }

    // A request's head and as much of its body as it says it has, read within five seconds: all of it, so that closing
    // the connection after the answer never resets it under the client's last bytes.
    std::string read_request(int fd) {
        std::string in;
        char buffer[65536];
        const auto start = std::chrono::steady_clock::now();
        while (since(start) < 5) {
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
        std::lock_guard<std::mutex> l(lock_);
        requests_.push_back(in);
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
            if (stopping_.load()) {
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

// A handler that reads the request and answers `text` whole, then closes.
Stand::Handler answer(const std::string& text) {
    return [text](int fd, Stand& s) {
        s.read_request(fd);
        Stand::send_text(fd, text);
    };
}

// `plain` compressed as a server compresses an answer: gzip's header, deflate's data, the CRC and the length.
std::string gzip(const std::string& plain) {
    z_stream z{};
    deflateInit2(&z, 6, Z_DEFLATED, 16 + MAX_WBITS, 8, Z_DEFAULT_STRATEGY);
    std::string out(deflateBound(&z, static_cast<uLong>(plain.size())), '\0');
    z.next_in = reinterpret_cast<Bytef*>(const_cast<char*>(plain.data()));
    z.avail_in = static_cast<uInt>(plain.size());
    z.next_out = reinterpret_cast<Bytef*>(out.data());
    z.avail_out = static_cast<uInt>(out.size());
    deflate(&z, Z_FINISH);
    out.resize(z.total_out);
    deflateEnd(&z);
    return out;
}

// `count` zero bytes compressed, a megabyte at a time: what a few KB that inflate to a great deal look like.
std::string gzip_zeros(std::uint64_t count) {
    z_stream z{};
    deflateInit2(&z, 9, Z_DEFLATED, 16 + MAX_WBITS, 8, Z_DEFAULT_STRATEGY);
    const std::vector<char> zeros(1 << 20, 0);
    std::string out;
    char piece[65536];
    for (std::uint64_t left = count;;) {
        const auto now = static_cast<uInt>(std::min<std::uint64_t>(left, zeros.size()));
        left -= now;
        z.next_in = reinterpret_cast<Bytef*>(const_cast<char*>(zeros.data()));
        z.avail_in = now;
        do {
            z.next_out = reinterpret_cast<Bytef*>(piece);
            z.avail_out = sizeof piece;
            deflate(&z, left ? Z_NO_FLUSH : Z_FINISH);
            out.append(piece, sizeof piece - z.avail_out);
        } while (z.avail_out == 0);
        if (!left) break;
    }
    deflateEnd(&z);
    return out;
}

// An answer of the game server's kind: a JSON list of a few hundred KB, as its song list is, with text that repeats.
std::string song_list() {
    std::string out = "[";
    for (int i = 1; i <= 1500; ++i) {
        if (i > 1) out += ",";
        out += "{\"id\":" + std::to_string(i) + ",\"name\":\"Song number " + std::to_string(i) + "\",\"artist\":\"Artist " +
               std::to_string(i % 37) + "\",\"levels\":[" + std::to_string(i % 15 + 1) + "," + std::to_string(i % 13 + 2) + "],\"bpm\":" +
               std::to_string(80 + i % 120) + ",\"free\":" + (i % 3 ? "true" : "false") + "}";
    }
    return out + "]";
}

// The head of an answer: its status line, its headers, the blank line.
std::string head_of(const std::string& status, const std::vector<std::string>& headers) {
    std::string out = "HTTP/1.1 " + status + "\r\n";
    for (const std::string& h : headers) out += h + "\r\n";
    return out + "\r\n";
}

// A compressed answer with its length, as Apache sends a small one.
std::string gzip_answer(const std::string& gz, const std::string& status = "200 OK") {
    return head_of(status, {"Content-Type: application/json", "Content-Encoding: gzip", "Vary: Accept-Encoding",
                            "Content-Length: " + std::to_string(gz.size()), "Connection: close"}) + gz;
}

// `body` in chunks of the sizes given in turn (the last size again until it is all out), then the closing chunk.
std::string chunked(const std::string& body, const std::vector<std::size_t>& sizes) {
    std::string out;
    std::size_t at = 0;
    for (std::size_t i = 0; at < body.size(); ++i) {
        const std::size_t n = std::min(sizes[std::min(i, sizes.size() - 1)], body.size() - at);
        char line[32];
        std::snprintf(line, sizeof line, "%zx\r\n", n);
        out += line + body.substr(at, n) + "\r\n";
        at += n;
    }
    return out + "0\r\n\r\n";
}

// What a request gave: the head, the length the client reported, the body read in pieces of `piece` bytes, and whether
// it was read to its end or failed (with the failure).
struct Got {
    bool headed = false, ok = false;
    int status = 0;
    net::Headers headers;
    long long length = -2;
    std::string body;
    std::uint64_t bytes = 0;  // the body's bytes, counted also when not kept
    net::Failure failure;
    double seconds = 0;
};

Got fetch(Stand& s, const std::string& method = "GET", const net::Headers& asked = {}, std::size_t piece = 4096, bool keep = true) {
    Got g;
    const auto start = std::chrono::steady_clock::now();
    net::Url u;
    net::Http http;
    std::string reason;
    if (!net::parse_url(s.url(), u, g.failure) || !http.send(method, u, asked, "", 5000, g.failure) || !http.head(g.status, reason, g.headers, g.failure))
        return g;
    g.headed = true;
    g.length = http.content_length();
    std::vector<char> buffer(piece);
    for (;;) {
        const long n = http.read(buffer.data(), buffer.size(), g.failure);
        if (n < 0) break;
        if (n == 0) {
            g.ok = true;
            break;
        }
        g.bytes += static_cast<std::uint64_t>(n);
        if (keep) g.body.append(buffer.data(), static_cast<std::size_t>(n));
    }
    g.seconds = since(start);
    return g;
}

// The value of a header the caller got, "" when there is none.
std::string header(const Got& g, const char* name) {
    for (const auto& [k, v] : g.headers) {
        if (strcasecmp(k.c_str(), name) == 0) return v;
    }
    return "";
}
bool has_header(const Got& g, const char* name) {
    for (const auto& [k, v] : g.headers) {
        if (strcasecmp(k.c_str(), name) == 0) return true;
    }
    return false;
}

// How many times a request line or header appears in what the server read.
int count_in(const std::string& request, const std::string& what) {
    int n = 0;
    for (std::size_t at = request.find(what); at != std::string::npos; at = request.find(what, at + 1)) ++n;
    return n;
}

// What a got was, for a failed check: its status, its body's size, and its failure.
std::string seen(const Got& g) {
    return std::to_string(g.status) + ", " + std::to_string(g.bytes) + " bytes, " + (g.ok ? "read to its end" : "failed: " + g.failure.text);
}

const std::string kList = song_list();

void plain_answers() {
    // With its length: the bytes and the headers as the server sent them, as before.
    Stand s(answer(head_of("200 OK", {"Content-Type: application/json", "Content-Length: " + std::to_string(kList.size())}) + kList));
    Got g = fetch(s);
    check(g.ok && g.body == kList, "a plain answer: its bytes as sent", seen(g));
    check(header(g, "Content-Length") == std::to_string(kList.size()) && g.length == static_cast<long long>(kList.size()),
          "a plain answer: its length kept", std::to_string(g.length));
    s.stop();
    const std::vector<std::string> requests = s.requests();
    // The request asks for gzip, once, as Android's HttpURLConnection asks when the game does not.
    check(requests.size() == 1 && count_in(requests[0], "\r\nAccept-Encoding: gzip\r\n") == 1, "the request asks for gzip",
          requests.empty() ? "" : requests[0]);
    // In chunks, not compressed: as before.
    Stand c(answer(head_of("200 OK", {"Content-Type: application/json", "Transfer-Encoding: chunked"}) + chunked(kList, {1, 7, 4093})));
    g = fetch(c);
    check(g.ok && g.body == kList && g.length == -1, "a plain answer in chunks: its bytes as sent", seen(g));
}

void compressed_answers() {
    const std::string gz = gzip(kList);
    std::printf("the list: %zu bytes, %zu compressed\n", kList.size(), gz.size());
    // With the compressed body's length (Apache's answer to a small reply).
    Stand s(answer(gzip_answer(gz)));
    Got g = fetch(s);
    check(g.ok && g.body == kList, "a compressed answer with its length: inflated whole", seen(g));
    check(!has_header(g, "Content-Encoding") && !has_header(g, "Content-Length") && g.length == -1,
          "a compressed answer: no encoding and no length in its headers, as on Android", std::to_string(g.length));
    check(header(g, "Content-Type") == "application/json" && header(g, "Vary") == "Accept-Encoding", "a compressed answer: its other headers kept");
    s.stop();
    // In chunks of odd sizes (Apache's answer to a larger one), and until the connection closes.
    Stand c(answer(head_of("200 OK", {"Content-Type: application/json", "Content-Encoding: gzip", "Transfer-Encoding: chunked"}) +
                   chunked(gz, {1, 2, 3, 1000, 7})));
    g = fetch(c);
    check(g.ok && g.body == kList, "a compressed answer in chunks: inflated whole", seen(g));
    c.stop();
    Stand e(answer(head_of("200 OK", {"Content-Encoding: gzip"}) + gz));
    g = fetch(e);
    check(g.ok && g.body == kList, "a compressed answer until the connection closes: inflated whole", seen(g));
    e.stop();
    // Read a byte at a time, and in WWW's pieces of 1428: the same bytes.
    Stand one(answer(gzip_answer(gz)));
    g = fetch(one, "GET", {}, 1);
    Got www = fetch(one, "GET", {}, 1428);
    check(g.ok && g.body == kList && www.ok && www.body == kList, "a compressed answer read a byte at a time, and in WWW's pieces", seen(g));
    one.stop();
    // An HTTP error's page, compressed: inflated too (WWW hands it to the game).
    Stand error(answer(gzip_answer(gzip("{\"error\":\"not here\"}"), "404 Not Found")));
    g = fetch(error);
    check(g.ok && g.status == 404 && g.body == "{\"error\":\"not here\"}", "a compressed 404: its page inflated", seen(g));
    error.stop();
    // The encoding's name in another case, with spaces around it.
    Stand upper(answer(head_of("200 OK", {"Content-Encoding:  GZIP ", "Content-Length: " + std::to_string(gz.size())}) + gz));
    g = fetch(upper);
    check(g.ok && g.body == kList, "Content-Encoding: GZIP, spaced: inflated", seen(g));
}

void the_callers_own() {
    // The game chose its encodings itself: its header goes out alone, and the answer is the game's to decode, untouched.
    const std::string gz = gzip(kList);
    Stand s(answer(gzip_answer(gz)));
    Got g = fetch(s, "GET", {{"Accept-Encoding", "identity, gzip"}});
    s.stop();
    const std::vector<std::string> requests = s.requests();
    check(requests.size() == 1 && count_in(requests[0], "Accept-Encoding: ") == 1 && count_in(requests[0], "\r\nAccept-Encoding: identity, gzip\r\n") == 1,
          "the game's own Accept-Encoding: sent alone", requests.empty() ? "" : requests[0]);
    check(g.ok && g.body == gz && header(g, "Content-Encoding") == "gzip" && g.length == static_cast<long long>(gz.size()),
          "the game's own Accept-Encoding: the answer as the server sent it", seen(g));
    // Another encoding than gzip, which this client never asks for: as it came, as before.
    Stand other(answer(head_of("200 OK", {"Content-Encoding: br", "Content-Length: 5"}) + "\x0b\x02\x80hi"));
    g = fetch(other);
    check(g.ok && g.body == "\x0b\x02\x80hi" && header(g, "Content-Encoding") == "br", "Content-Encoding: br: as it came", seen(g));
}

void no_body() {
    // A HEAD and the answers that have no body, though they name gzip: nothing to inflate, nothing failed, their headers kept.
    Stand head(answer(head_of("200 OK", {"Content-Encoding: gzip", "Content-Length: 1234"})));
    Got g = fetch(head, "HEAD");
    check(g.ok && g.bytes == 0 && header(g, "Content-Encoding") == "gzip" && g.length == 1234, "a HEAD naming gzip: no body, its headers kept", seen(g));
    head.stop();
    for (const char* status : {"204 No Content", "304 Not Modified"}) {
        Stand s(answer(head_of(status, {"Content-Encoding: gzip"})));
        g = fetch(s);
        check(g.ok && g.bytes == 0, std::string("a ") + status + " naming gzip: no body, no failure", seen(g));
    }
}

void broken_streams() {
    const std::string gz = gzip(kList);
    // Each fails as a lost connection does: no end reached, a failure the game hears of (code 2, an IOException).
    auto fails = [](const Got& g) { return g.headed && !g.ok && g.failure.code == 2 && g.failure.text.rfind("java.io.", 0) == 0; };
    // Cut in the middle: its length promised more than came, or the connection closed early.
    Stand cut(answer(head_of("200 OK", {"Content-Encoding: gzip", "Content-Length: " + std::to_string(gz.size())}) + gz.substr(0, gz.size() / 2)));
    Got g = fetch(cut);
    check(fails(g) && g.bytes < kList.size(), "cut in the middle: fails", seen(g));
    check(g.failure.text.find("EOFException") != std::string::npos, "cut in the middle: as an end of file", g.failure.text);
    cut.stop();
    Stand cut2(answer(head_of("200 OK", {"Content-Encoding: gzip"}) + gz.substr(0, gz.size() - 4)));
    g = fetch(cut2);
    check(fails(g), "cut inside its last eight bytes (the CRC and the length): fails", seen(g));
    cut2.stop();
    // No bytes at all where a stream was named.
    Stand empty(answer(head_of("200 OK", {"Content-Encoding: gzip", "Content-Length: 0"})));
    g = fetch(empty);
    check(fails(g) && g.bytes == 0, "an empty body named gzip: fails", seen(g));
    empty.stop();
    // Not gzip at all, though named so.
    Stand plain(answer(head_of("200 OK", {"Content-Encoding: gzip", "Content-Length: " + std::to_string(kList.size())}) + kList));
    g = fetch(plain);
    check(fails(g) && g.bytes == 0, "plain JSON named gzip: fails, nothing handed over", seen(g));
    plain.stop();
    // A byte changed in the middle of the data; the CRC changed; the length changed.
    std::string flipped = gz, crc = gz, length = gz;
    flipped[gz.size() / 2] = static_cast<char>(flipped[gz.size() / 2] ^ 0x55);
    crc[gz.size() - 8] = static_cast<char>(crc[gz.size() - 8] ^ 1);
    length[gz.size() - 4] = static_cast<char>(length[gz.size() - 4] ^ 1);
    for (const auto& [name, bytes] : {std::pair<const char*, const std::string*>{"a byte changed in its data", &flipped},
                                      {"its CRC wrong", &crc},
                                      {"its length wrong", &length}}) {
        Stand s(answer(gzip_answer(*bytes)));
        g = fetch(s);
        check(fails(g), std::string(name) + ": fails", seen(g));
    }
    // More after the stream's end, in the same body: a second stream, or other bytes.
    for (const auto& [name, extra] : {std::pair<const char*, std::string>{"a second stream after it", gzip("more")}, {"bytes after it", "xyz"}}) {
        Stand s(answer(gzip_answer(gz + extra)));
        g = fetch(s);
        check(fails(g), std::string(name) + ": fails", seen(g));
    }
}

void too_large() {
    // As much as is allowed: inflated whole.
    const std::string most = gzip_zeros(net::kMaxInflated);
    Stand s(answer(gzip_answer(most)));
    Got g = fetch(s, "GET", {}, 131072, false);
    check(g.ok && g.bytes == net::kMaxInflated, "an answer of the most that inflates: read whole", seen(g));
    s.stop();
    // A byte more: fails as a broken answer does, and nothing past the limit was handed over.
    const std::string over = gzip_zeros(net::kMaxInflated + 1);
    std::printf("%llu MB of zeros: %zu bytes compressed\n", static_cast<unsigned long long>(net::kMaxInflated >> 20), over.size());
    Stand t(answer(gzip_answer(over)));
    g = fetch(t, "GET", {}, 131072, false);
    check(g.headed && !g.ok && g.failure.code == 2 && g.failure.text.find("more than") != std::string::npos, "an answer that inflates a byte past the most: fails",
          seen(g));
    check(g.bytes <= net::kMaxInflated, "an answer that inflates past the most: no more than the most handed over", seen(g));
    t.stop();
    // Four times that, as a few hundred KB: given up at the limit, as quickly as the most itself is inflated.
    const std::string bomb = gzip_zeros(4 * net::kMaxInflated);
    Stand b(answer(gzip_answer(bomb)));
    g = fetch(b, "GET", {}, 131072, false);
    char seconds[96];
    std::snprintf(seconds, sizeof seconds, "%zu bytes compressed, %.2f s, %llu bytes handed over", bomb.size(), g.seconds,
                  static_cast<unsigned long long>(g.bytes));
    check(!g.ok && g.bytes <= net::kMaxInflated && g.seconds < 5, "256 MB from a few hundred KB: given up at the most", seconds);
}

}  // namespace

int main() {
    // Each check group, in turn; the servers on 127.0.0.1 only.
    const struct {
        const char* name;
        void (*run)();
    } groups[] = {{"answers not compressed", plain_answers},
                  {"compressed answers", compressed_answers},
                  {"the game's own encodings", the_callers_own},
                  {"answers without a body", no_body},
                  {"broken streams", broken_streams},
                  {"answers too large", too_large}};
    for (const auto& group : groups) {
        const int failures = g_failures;
        const auto start = std::chrono::steady_clock::now();
        group.run();
        std::printf("%s %s (%.2f s)\n", g_failures == failures ? "ok" : "FAILED", group.name, since(start));
    }
    if (g_failures) {
        std::printf("%d of %d checks FAILED\n", g_failures, g_checks);
        return 1;
    }
    std::printf("%d checks\nALL CHECKS PASSED\n", g_checks);
    return 0;
}
