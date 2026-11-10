// The player's HTTP client, which the game's WWW and UnityWebRequest (web.cpp) and the platform's requests (pmangplus.cpp)
// go through: HTTP/1.1, one request per connection, with what Android's HttpURLConnection adds to a request the caller
// left without: a User-Agent, and Accept-Encoding: gzip. An answer the server compressed for that is inflated as it is
// read, as a phone's is, and loses its Content-Encoding and Content-Length (Android clears both). Plain HTTP only: HTTPS
// is refused with the error a failed handshake gives. Nothing here knows the Java VM, so the build machine tests it on
// its own (arm32/tests/host/http_test.cpp).
#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace player::net {

// Why a request failed, in UnityWebRequest's error codes, and what to say.
struct Failure {
    int code = 0;  // 2 any, 4 bad protocol, 5 malformed URL, 7 unknown host, 14 timeout, 16 SSL
    std::string text;
    explicit operator bool() const { return code != 0; }
};

// An address as parse_url takes it apart.
struct Url {
    std::string scheme, host, path;
    int port = 80;
};

// A request's or an answer's headers, names and values in their order.
using Headers = std::vector<std::pair<std::string, std::string>>;

// http://host[:port]/path?query; false for anything else.
bool parse_url(const std::string& text, Url& u, Failure& f);

// The most an answer the server compressed may come to once inflated. The game server compresses its JSON and its pages
// (server/apache/site.conf), whose largest, the song list, is a few hundred KB inflated, a few MB on a server with ten
// times the songs: far below this. A few KB of gzip can inflate to gigabytes, which the game would try to hold whole;
// past this the answer fails as a broken one does instead, and only this much is ever inflated.
constexpr std::uint64_t kMaxInflated = 64ull << 20;

class Http {
public:
    Http();
    ~Http();
    // One connection each: not copied.
    Http(const Http&) = delete;
    Http& operator=(const Http&) = delete;

    // Connects and sends the request; `timeout_ms` (0: none) bounds the connection and each read and write after it.
    bool send(const std::string& method, const Url& u, const Headers& headers, const std::string& body, int timeout_ms, Failure& f);
    // The status line and the headers (those an inflated answer keeps).
    bool head(int& status, std::string& reason, Headers& headers, Failure& f);

    const std::string& status_line() const { return status_line_; }
    // The body's length as the caller will read it: -1 when it is not known ahead (chunked, or inflated here).
    long long content_length() const;

    // The body a piece at a time, inflated when the server compressed it for this request: up to n bytes, 0 at its end,
    // -1 on an error (f says which: a stream cut short, broken or too large fails as a lost connection does).
    long read(char* out, std::size_t n, Failure& f);

private:
    // The inflater of a compressed answer (http.cpp): zlib's, kept out of this header.
    struct Gunzip;

    // Waits for the socket to be ready within the timeout.
    bool ready(short events, Failure& f);
    // All of n bytes out, within the timeout.
    bool write_all(const char* p, std::size_t n, Failure& f);
    // More of the answer into the buffer; false at its end (f set on an error).
    bool fill(Failure& f);
    // The body as it came over the connection: up to n bytes, 0 at its end, -1 on an error.
    long read_raw(char* out, std::size_t n, Failure& f);
    // The body inflated (gunzip_), read_raw's bytes going in as they are needed.
    long read_inflated(char* out, std::size_t n, Failure& f);

    int fd_ = -1;
    int timeout_ms_ = 0;
    std::string buffer_, status_line_;
    long long left_ = -1, chunk_left_ = 0;
    bool chunked_ = false, chunk_seen_ = false, chunks_done_ = false;
    // A HEAD request, whose answer has no body whatever its headers say.
    bool head_request_ = false;
    // Accept-Encoding: gzip went with the request because the caller sent none: an answer compressed for it is this
    // client's to inflate. One the caller asked for itself is the caller's, its bytes untouched.
    bool asked_gzip_ = false;
    // Set while the answer is a compressed one being inflated.
    std::unique_ptr<Gunzip> gunzip_;
};

}  // namespace player::net
