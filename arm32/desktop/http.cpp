// The player's HTTP client (http.h): the game's requests as Android's HttpURLConnection makes them, on plain HTTP.
#include "http.h"

#include <algorithm>
#include <arpa/inet.h>
#include <cctype>
#include <cerrno>
#include <climits>
#include <cstdlib>
#include <cstring>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <strings.h>
#include <sys/socket.h>
#include <unistd.h>
#include <zlib.h>

namespace player::net {

namespace {

// A header's value without the spaces and tabs around it.
std::string trimmed(const std::string& value) {
    std::size_t from = value.find_first_not_of(" \t"), to = value.find_last_not_of(" \t");
    return from == std::string::npos ? std::string() : value.substr(from, to - from + 1);
}

// Whether a header's name is `name`, in any case.
bool named(const std::string& header, const char* name) { return strcasecmp(header.c_str(), name) == 0; }

}  // namespace

bool parse_url(const std::string& text, Url& u, Failure& f) {
    std::size_t colon = text.find("://");
    if (colon == std::string::npos) {
        f = Failure{5, "no protocol: " + text};
        return false;
    }
    u.scheme = text.substr(0, colon);
    for (char& ch : u.scheme) ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
    std::size_t start = colon + 3;
    std::size_t slash = text.find_first_of("/?", start);
    std::string authority = text.substr(start, slash == std::string::npos ? std::string::npos : slash - start);
    u.path = slash == std::string::npos ? "/" : text.substr(slash);
    if (u.path[0] == '?') u.path = "/" + u.path;
    // user:password@ is not used by the game.
    std::size_t at = authority.rfind('@');
    if (at != std::string::npos) authority = authority.substr(at + 1);
    std::size_t port = authority.rfind(':');
    if (port != std::string::npos && authority.find(']') == std::string::npos) {
        u.host = authority.substr(0, port);
        u.port = std::atoi(authority.c_str() + port + 1);
    } else {
        u.host = authority;
        u.port = u.scheme == "https" ? 443 : 80;
    }
    if (u.host.empty()) {
        f = Failure{5, "no host: " + text};
        return false;
    }
    return true;
}

// The inflater of an answer the server compressed: zlib's, for gzip's wrapping alone (its header, then deflate's data,
// then the CRC and length zlib checks), as Android's GzipSource reads it. What came over the connection waits in `in`
// until inflated: one piece at a time, never the whole answer.
struct Http::Gunzip {
    z_stream z{};
    // inflateInit2 took: inflateEnd is due.
    bool open = false;
    // The stream's end was reached, its CRC and length right: what follows is the answer's end, or an error.
    bool ended = false;
    // Inflated so far, against kMaxInflated.
    std::uint64_t total = 0;
    // The connection's bytes for zlib: z.next_in points into it while z.avail_in is left.
    char in[16384];

    Gunzip() {
        // 16 + the largest window: gzip's header and trailer, not zlib's or raw deflate.
        open = inflateInit2(&z, 16 + MAX_WBITS) == Z_OK;
    }
    ~Gunzip() {
        if (open) inflateEnd(&z);
    }
};

Http::Http() = default;

Http::~Http() {
    if (fd_ >= 0) close(fd_);
}

bool Http::send(const std::string& method, const Url& u, const Headers& headers, const std::string& body, int timeout_ms, Failure& f) {
    if (u.scheme == "https") {
        f = Failure{16, "javax.net.ssl.SSLHandshakeException: HTTPS is not available in this player"};
        return false;
    }
    if (u.scheme != "http") {
        f = Failure{4, "unsupported protocol: " + u.scheme};
        return false;
    }
    timeout_ms_ = timeout_ms;
    // A HEAD's answer has headers only (head() and read() go by it).
    head_request_ = method == "HEAD";
    addrinfo hints{}, *found = nullptr;
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(u.host.c_str(), std::to_string(u.port).c_str(), &hints, &found) != 0 || !found) {
        f = Failure{7, "java.net.UnknownHostException: Unable to resolve host \"" + u.host + "\""};
        return false;
    }
    // Each address in turn until one connects.
    for (addrinfo* a = found; a && fd_ < 0; a = a->ai_next) {
        int fd = socket(a->ai_family, a->ai_socktype | SOCK_CLOEXEC | SOCK_NONBLOCK, a->ai_protocol);
        if (fd < 0) continue;
        int r = connect(fd, a->ai_addr, a->ai_addrlen);
        if (r != 0 && errno == EINPROGRESS) {
            pollfd p{fd, POLLOUT, 0};
            int err = 0;
            socklen_t len = sizeof err;
            r = poll(&p, 1, timeout_ms > 0 ? timeout_ms : -1) == 1 && getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len) == 0 && err == 0 ? 0 : -1;
        }
        if (r == 0) fd_ = fd;
        else close(fd);
    }
    freeaddrinfo(found);
    if (fd_ < 0) {
        f = Failure{14, "java.net.ConnectException: failed to connect to " + u.host + " (port " + std::to_string(u.port) + ")"};
        return false;
    }
    int one = 1;
    setsockopt(fd_, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    // The request: the game's headers, Host and a close at the end (one request per connection), and the body.
    std::string host = u.host + (u.port != 80 ? ":" + std::to_string(u.port) : "");
    std::string req = method + " " + u.path + " HTTP/1.1\r\nHost: " + host + "\r\nConnection: close\r\n";
    bool has_type = false, has_agent = false, has_encoding = false;
    for (auto& [k, v] : headers) {
        req += k + ": " + v + "\r\n";
        if (named(k, "Content-Type")) has_type = true;
        if (named(k, "User-Agent")) has_agent = true;
        // The caller's own choice of encodings: then its answer is the caller's to decode, as on Android.
        if (named(k, "Accept-Encoding")) has_encoding = true;
    }
    // What Android's HttpURLConnection adds when the caller does not: its User-Agent, and a request for gzip, which it
    // then inflates itself (read()). A phone's game gets the server's JSON compressed so; the player's now does too.
    if (!has_agent) req += "User-Agent: Dalvik/2.1.0 (Linux; U; Android 9; OpenDMTQ Build/PQ3A)\r\n";
    asked_gzip_ = !has_encoding;
    if (asked_gzip_) req += "Accept-Encoding: gzip\r\n";
    if (!body.empty() || method == "POST" || method == "PUT") {
        if (!has_type) req += "Content-Type: application/x-www-form-urlencoded\r\n";
        req += "Content-Length: " + std::to_string(body.size()) + "\r\n";
    }
    req += "\r\n";
    req += body;
    return write_all(req.data(), req.size(), f);
}

bool Http::head(int& status, std::string& reason, Headers& headers, Failure& f) {
    std::size_t end;
    while ((end = buffer_.find("\r\n\r\n")) == std::string::npos) {
        if (!fill(f)) {
            if (!f) f = Failure{2, "java.io.IOException: the server closed the connection before answering"};
            return false;
        }
    }
    std::string head = buffer_.substr(0, end);
    buffer_.erase(0, end + 4);
    std::size_t line_end = head.find("\r\n");
    std::string line = head.substr(0, line_end);
    // "HTTP/1.1 200 OK"
    std::size_t sp = line.find(' ');
    if (line.compare(0, 5, "HTTP/") != 0 || sp == std::string::npos) {
        f = Failure{2, "java.io.IOException: not an HTTP answer"};
        return false;
    }
    status = std::atoi(line.c_str() + sp + 1);
    std::size_t sp2 = line.find(' ', sp + 1);
    reason = sp2 == std::string::npos ? "" : line.substr(sp2 + 1);
    status_line_ = line;
    // The encoding the server says it compressed the body with: the last such header, as Android reads one.
    std::string encoding;
    for (std::size_t at = line_end == std::string::npos ? head.size() : line_end + 2; at < head.size();) {
        std::size_t next = head.find("\r\n", at);
        std::string h = head.substr(at, next == std::string::npos ? std::string::npos : next - at);
        at = next == std::string::npos ? head.size() : next + 2;
        std::size_t c = h.find(':');
        if (c == std::string::npos) continue;
        std::string name = h.substr(0, c), value = h.substr(c + 1);
        while (!value.empty() && (value.front() == ' ' || value.front() == '\t')) value.erase(0, 1);
        headers.emplace_back(name, value);
        if (named(name, "Content-Length")) left_ = std::atoll(value.c_str());
        if (named(name, "Transfer-Encoding") && strcasecmp(value.c_str(), "chunked") == 0) chunked_ = true;
        if (named(name, "Content-Encoding")) encoding = trimmed(value);
    }
    // No body for these, whatever the headers say.
    if (status == 204 || status == 304 || (status >= 100 && status < 200)) {
        left_ = 0;
        chunked_ = false;
        return true;
    }
    // A HEAD's answer has none either: its headers stay the server's (their length is the GET's body's), nothing to inflate.
    if (head_request_) return true;
    // A body compressed because this client asked: inflated as it is read (read()), and its headers as Android leaves
    // them, without the encoding and the length, which are the compressed body's and not what the caller reads. Any other
    // encoding, or none, and the body and its headers are the server's, as before.
    if (asked_gzip_ && strcasecmp(encoding.c_str(), "gzip") == 0) {
        gunzip_ = std::make_unique<Gunzip>();
        if (!gunzip_->open) {
            // zlib could not start (no memory): as a lost connection.
            f = Failure{2, "java.io.IOException: the answer cannot be inflated here"};
            return false;
        }
        headers.erase(std::remove_if(headers.begin(), headers.end(),
                                     [](const auto& h) { return named(h.first, "Content-Encoding") || named(h.first, "Content-Length"); }),
                      headers.end());
    }
    return true;
}

long long Http::content_length() const {
    // An inflated body's length is known only at its end, as on Android (getContentLength() is -1 then).
    if (gunzip_) return -1;
    return chunked_ ? -1 : left_;
}

long Http::read(char* out, std::size_t n, Failure& f) { return gunzip_ ? read_inflated(out, n, f) : read_raw(out, n, f); }

long Http::read_raw(char* out, std::size_t n, Failure& f) {
    if (chunked_) {
        if (chunk_left_ == 0) {
            if (chunks_done_) return 0;
            // The chunk's size line (after the CRLF that ended the chunk before).
            std::size_t eol;
            while ((eol = buffer_.find("\r\n", chunk_seen_ ? 2 : 0)) == std::string::npos) {
                if (!fill(f)) return f ? -1 : 0;
            }
            std::size_t from = chunk_seen_ ? 2 : 0;
            chunk_left_ = std::strtoll(buffer_.c_str() + from, nullptr, 16);
            buffer_.erase(0, eol + 2);
            chunk_seen_ = true;
            if (chunk_left_ == 0) {
                chunks_done_ = true;
                return 0;
            }
        }
        n = static_cast<std::size_t>(std::min<long long>(static_cast<long long>(n), chunk_left_));
    } else if (left_ >= 0) {
        if (left_ == 0) return 0;
        n = static_cast<std::size_t>(std::min<long long>(static_cast<long long>(n), left_));
    }
    if (buffer_.empty() && !fill(f)) return f ? -1 : 0;
    std::size_t take = std::min(n, buffer_.size());
    std::memcpy(out, buffer_.data(), take);
    buffer_.erase(0, take);
    if (chunked_) chunk_left_ -= static_cast<long long>(take);
    else if (left_ >= 0) left_ -= static_cast<long long>(take);
    return static_cast<long>(take);
}

long Http::read_inflated(char* out, std::size_t n, Failure& f) {
    Gunzip& g = *gunzip_;
    // Past the stream's end, checked once: the body is over.
    if (g.ended || n == 0) return 0;
    for (;;) {
        // zlib has used up what came: the next piece of the connection's body.
        if (g.z.avail_in == 0) {
            const long got = read_raw(g.in, sizeof g.in, f);
            // The connection failed: its own error, as for a body that is not compressed.
            if (got < 0) return -1;
            if (got == 0) {
                // The body ended before the stream did (a connection cut, or no gzip at all): Android's EOFException.
                f = Failure{2, "java.io.EOFException: the answer ends before its gzip stream does"};
                return -1;
            }
            g.z.next_in = reinterpret_cast<Bytef*>(g.in);
            g.z.avail_in = static_cast<uInt>(got);
        }
        // Into the caller's buffer, never past the limit by more than the one byte that shows it was passed.
        const std::uint64_t room = std::min<std::uint64_t>({n, kMaxInflated - g.total + 1, UINT_MAX});
        g.z.next_out = reinterpret_cast<Bytef*>(out);
        g.z.avail_out = static_cast<uInt>(room);
        // What zlib had before this call: a call that takes none of it and gives nothing has stopped for good.
        const uInt had = g.z.avail_in;
        const int r = inflate(&g.z, Z_NO_FLUSH);
        const std::size_t made = static_cast<std::size_t>(room - g.z.avail_out);
        g.total += made;
        if (g.total > kMaxInflated) {
            // Far larger than any answer of the server's: what a few KB that inflate without end would give.
            f = Failure{2, "java.io.IOException: the answer inflates to more than " + std::to_string(kMaxInflated >> 20) + " MB"};
            return -1;
        }
        if (r == Z_STREAM_END) {
            // The stream is whole, its CRC and length checked: nothing may follow it in the body, neither in what zlib
            // was given nor still on the connection (Android: "gzip finished without exhausting source").
            char more = 0;
            const long after = g.z.avail_in ? 1 : read_raw(&more, 1, f);
            if (after < 0) return -1;
            if (after > 0) {
                f = Failure{2, "java.io.IOException: the answer goes on after its gzip stream"};
                return -1;
            }
            g.ended = true;
            // The last of the inflated bytes; the next read is the end.
            return static_cast<long>(made);
        }
        // Z_BUF_ERROR: nothing to do without more input (the loop reads it); anything else not Z_OK, or no step taken
        // with input and room both there: the data are not gzip's, or wrong (its CRC, its length), or zlib ran out of
        // memory.
        if ((r != Z_OK && r != Z_BUF_ERROR) || (made == 0 && had > 0 && g.z.avail_in == had)) {
            f = Failure{2, std::string("java.io.IOException: the answer's gzip stream is broken (") + (g.z.msg ? g.z.msg : "no detail") + ")"};
            return -1;
        }
        // Something for the caller; else zlib took the bytes it had (a header, a block's start) and wants more.
        if (made > 0) return static_cast<long>(made);
    }
}

bool Http::ready(short events, Failure& f) {
    pollfd p{fd_, events, 0};
    int r = poll(&p, 1, timeout_ms_ > 0 ? timeout_ms_ : -1);
    if (r == 0) f = Failure{14, "java.net.SocketTimeoutException: timeout"};
    return r == 1;
}

bool Http::write_all(const char* p, std::size_t n, Failure& f) {
    while (n) {
        if (!ready(POLLOUT, f)) return false;
        ssize_t w = ::send(fd_, p, n, MSG_NOSIGNAL);
        if (w < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (w <= 0) {
            f = Failure{2, std::string("java.io.IOException: ") + std::strerror(errno)};
            return false;
        }
        p += w;
        n -= static_cast<std::size_t>(w);
    }
    return true;
}

bool Http::fill(Failure& f) {
    char chunk[16384];
    for (;;) {
        if (!ready(POLLIN, f)) return false;
        ssize_t r = recv(fd_, chunk, sizeof chunk, 0);
        if (r < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (r < 0) {
            f = Failure{2, std::string("java.io.IOException: ") + std::strerror(errno)};
            return false;
        }
        if (r == 0) return false;
        buffer_.append(chunk, static_cast<std::size_t>(r));
        return true;
    }
}

}  // namespace player::net
