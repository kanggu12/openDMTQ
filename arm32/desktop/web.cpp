// HTTP for the game: the Java side of Unity's WWW and UnityWebRequest, as Unity 5.6's own Java has them (the callbacks
// in its order, with its arguments), on a small HTTP/1.1 client of the player's own. The game talks to its server over
// plain HTTP; HTTPS is refused with the error a failed handshake gives.
#include "player.h"

#include <algorithm>
#include <arpa/inet.h>
#include <cctype>
#include <cerrno>
#include <chrono>
#include <fstream>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <strings.h>
#include <sys/socket.h>
#include <unistd.h>

namespace player {

namespace {

using jvm::Call;
using jvm::Class;
using jvm::Object;
using jvm::Ref;
using jvm::Value;

// ---------------------------------------------------------------------------------------------------------------------
// The HTTP client.

// Why a request failed, in UnityWebRequest's error codes, and what to say.
struct Failure {
    int code = 0;  // 2 any, 4 bad protocol, 5 malformed URL, 7 unknown host, 14 timeout, 16 SSL
    std::string text;
    explicit operator bool() const { return code != 0; }
};

struct Url {
    std::string scheme, host, path;
    int port = 80;
};

// http://host[:port]/path?query; false for anything else.
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

class Http {
public:
    ~Http() {
        if (fd_ >= 0) close(fd_);
    }

    // Connects and sends the request; `timeout_ms` (0: none) bounds the connection and each read and write after it.
    bool send(const std::string& method, const Url& u, const std::vector<std::pair<std::string, std::string>>& headers, const std::string& body,
              int timeout_ms, Failure& f) {
        if (u.scheme == "https") {
            f = Failure{16, "javax.net.ssl.SSLHandshakeException: HTTPS is not available in this player"};
            return false;
        }
        if (u.scheme != "http") {
            f = Failure{4, "unsupported protocol: " + u.scheme};
            return false;
        }
        timeout_ms_ = timeout_ms;
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
        bool has_type = false, has_agent = false;
        for (auto& [k, v] : headers) {
            req += k + ": " + v + "\r\n";
            if (strcasecmp(k.c_str(), "Content-Type") == 0) has_type = true;
            if (strcasecmp(k.c_str(), "User-Agent") == 0) has_agent = true;
        }
        // What Android's HttpURLConnection adds when the caller does not.
        if (!has_agent) req += "User-Agent: Dalvik/2.1.0 (Linux; U; Android 9; OpenDMTQ Build/PQ3A)\r\n";
        if (!body.empty() || method == "POST" || method == "PUT") {
            if (!has_type) req += "Content-Type: application/x-www-form-urlencoded\r\n";
            req += "Content-Length: " + std::to_string(body.size()) + "\r\n";
        }
        req += "\r\n";
        req += body;
        return write_all(req.data(), req.size(), f);
    }

    // The status line and the headers.
    bool head(int& status, std::string& reason, std::vector<std::pair<std::string, std::string>>& headers, Failure& f) {
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
        for (std::size_t at = line_end == std::string::npos ? head.size() : line_end + 2; at < head.size();) {
            std::size_t next = head.find("\r\n", at);
            std::string h = head.substr(at, next == std::string::npos ? std::string::npos : next - at);
            at = next == std::string::npos ? head.size() : next + 2;
            std::size_t c = h.find(':');
            if (c == std::string::npos) continue;
            std::string name = h.substr(0, c), value = h.substr(c + 1);
            while (!value.empty() && (value.front() == ' ' || value.front() == '\t')) value.erase(0, 1);
            headers.emplace_back(name, value);
            if (strcasecmp(name.c_str(), "Content-Length") == 0) left_ = std::atoll(value.c_str());
            if (strcasecmp(name.c_str(), "Transfer-Encoding") == 0 && strcasecmp(value.c_str(), "chunked") == 0) chunked_ = true;
        }
        // No body for these, whatever the headers say.
        if (status == 204 || status == 304 || (status >= 100 && status < 200)) {
            left_ = 0;
            chunked_ = false;
        }
        return true;
    }

    const std::string& status_line() const { return status_line_; }
    long long content_length() const { return chunked_ ? -1 : left_; }

    // The body a piece at a time: up to n bytes, 0 at its end, -1 on an error.
    long read(char* out, std::size_t n, Failure& f) {
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

private:
    // Waits for the socket to be ready within the timeout.
    bool ready(short events, Failure& f) {
        pollfd p{fd_, events, 0};
        int r = poll(&p, 1, timeout_ms_ > 0 ? timeout_ms_ : -1);
        if (r == 0) f = Failure{14, "java.net.SocketTimeoutException: timeout"};
        return r == 1;
    }
    bool write_all(const char* p, std::size_t n, Failure& f) {
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
    // More of the answer into the buffer; false at its end (f set on an error).
    bool fill(Failure& f) {
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
    int fd_ = -1;
    int timeout_ms_ = 0;
    std::string buffer_, status_line_;
    long long left_ = -1, chunk_left_ = 0;
    bool chunked_ = false, chunk_seen_ = false, chunks_done_ = false;
};

// ---------------------------------------------------------------------------------------------------------------------
// Local URLs, which Java's own URL classes read: file:///path, and jar:file:///path.apk!/entry (Unity's StreamingAssets on
// Android are inside the APK, and the game reads its string tables from there through WWW).

// %XX as bytes.
std::string percent_decoded(const std::string& s) {
    std::string out;
    for (std::size_t i = 0; i < s.size(); ++i) {
        if (s[i] == '%' && i + 2 < s.size() && std::isxdigit(static_cast<unsigned char>(s[i + 1])) && std::isxdigit(static_cast<unsigned char>(s[i + 2]))) {
            out.push_back(static_cast<char>(std::strtol(s.substr(i + 1, 2).c_str(), nullptr, 16)));
            i += 2;
        } else {
            out.push_back(s[i]);
        }
    }
    return out;
}

// The path of a file: URL ("file:///a/b" and "file:/a/b" are both /a/b).
std::string file_path(const std::string& url) {
    std::string p = url.substr(5);
    if (p.rfind("//", 0) == 0) p = p.substr(2);
    return percent_decoded(p);
}

bool is_local(const std::string& url) {
    auto starts = [&url](const char* s) { return strncasecmp(url.c_str(), s, std::strlen(s)) == 0; };
    return starts("file:") || starts("jar:");
}

// A local URL's contents: an entry of the app's APK for jar:, the file for file:.
bool read_local(const std::string& url, std::vector<std::uint8_t>& out, Failure& f) {
    if (strncasecmp(url.c_str(), "jar:", 4) == 0) {
        std::size_t bang = url.find("!/");
        if (bang == std::string::npos || strncasecmp(url.c_str() + 4, "file:", 5) != 0) {
            f = Failure{5, "java.net.MalformedURLException: " + url};
            return false;
        }
        std::string archive = file_path(url.substr(4, bang - 4)), entry = percent_decoded(url.substr(bang + 2));
        // Only the app's own APK is a jar the game reads.
        if (host_of(archive) != app().host_apk || !apk_entry(entry, out)) {
            f = Failure{2, "java.io.FileNotFoundException: " + url};
            return false;
        }
        return true;
    }
    std::string host = host_of(file_path(url));
    std::ifstream in(utf8_path(host), std::ios::binary);
    if (!in) {
        f = Failure{2, "java.io.FileNotFoundException: " + url};
        return false;
    }
    char chunk[65536];
    while (in.read(chunk, sizeof chunk) || in.gcount() > 0) out.insert(out.end(), chunk, chunk + in.gcount());
    return true;
}

// ---------------------------------------------------------------------------------------------------------------------
// WWW: a thread per request; its callbacks take the request's number.

class Www : public JThread {
public:
    using JThread::JThread;
    jint id = 0;
    std::string url;
    std::string post;
    bool has_post = false;
    std::vector<std::pair<std::string, std::string>> headers;
};

// The headers as WWW.headerCallback(Map) joins them: "Name: value\r\n" each, the status line as "Status: ...".
std::string header_text(const std::string& status_line, const std::vector<std::pair<std::string, std::string>>& headers) {
    std::string out = "Status: " + status_line + "\r\n";
    for (auto& [k, v] : headers) out += k + ": " + v + "\r\n";
    return out;
}

void www_run(jvm::Env& e, Www& w) {
    Class& c = *jvm::find_class("com/unity3d/player/WWW");
    auto error = [&](const std::string& text) { e.call_static(c, "errorCallback", "(ILjava/lang/String;)V", {Value::I(w.id), Value(jvm::string(text))}); };
    std::string url = w.url;
    // A local URL: its length as WWW's single header ("\n\r" as its headerCallback(String, String) writes it), then the
    // contents in pieces of up to 32 KB, then done.
    if (is_local(url)) {
        std::vector<std::uint8_t> data;
        Failure f;
        if (!read_local(url, data, f)) return error(f.text);
        std::string header = "content-length: " + std::to_string(data.size()) + "\n\r";
        if (e.call_static(c, "headerCallback", "(ILjava/lang/String;)Z", {Value::I(w.id), Value(jvm::string(header))}).z()) return error(url + " aborted");
        std::size_t step = data.empty() ? 32768 : std::min<std::size_t>(data.size(), 32768);
        Ref<jvm::Array> piece = jvm::new_array(jvm::array_class(jvm::primitive_class('B')), static_cast<jsize>(step));
        for (std::size_t at = 0; at < data.size(); at += step) {
            std::size_t n = std::min(step, data.size() - at);
            std::memcpy(piece->bytes.data(), data.data() + at, n);
            if (e.call_static(c, "readCallback", "(I[BI)Z", {Value::I(w.id), Value(piece), Value::I(static_cast<jint>(n))}).z()) return error(url + " aborted");
            e.call_static(c, "progressCallback", "(IFFDI)V", {Value::I(w.id), Value::F(1.0f), Value::F(static_cast<float>(at + n) / static_cast<float>(data.size())), Value::D(0.0), Value::I(static_cast<jint>(data.size()))});
        }
        e.call_static(c, "progressCallback", "(IFFDI)V", {Value::I(w.id), Value::F(1.0f), Value::F(1.0f), Value::D(0.0), Value::I(static_cast<jint>(data.size()))});
        e.call_static(c, "doneCallback", "(I)V", {Value::I(w.id)});
        return;
    }
    // Redirects (301 and 302) are followed, five at most, as WWW.runSafe does.
    for (int hop = 0;; ++hop) {
        if (hop >= 5) return error("Too many redirects");
        Url u;
        Failure f;
        Http http;
        int status = 0;
        std::string reason;
        std::vector<std::pair<std::string, std::string>> headers;
        if (!parse_url(url, u, f) || !http.send(w.has_post ? "POST" : "GET", u, w.headers, w.post, 0, f) || !http.head(status, reason, headers, f)) return error(f.text);
        if (status == 301 || status == 302) {
            auto loc = std::find_if(headers.begin(), headers.end(), [](auto& h) { return strcasecmp(h.first.c_str(), "Location") == 0; });
            if (loc != headers.end()) {
                url = loc->second;
                continue;
            }
        }
        // The headers; a true answer means the game aborted the request.
        if (e.call_static(c, "headerCallback", "(ILjava/lang/String;)Z", {Value::I(w.id), Value(jvm::string(header_text(http.status_line(), headers)))}).z())
            return error(url + " aborted");
        // The body in pieces of 1428 bytes, the size WWW reads from a network connection.
        long long total = http.content_length() > 0 ? http.content_length() : 0;
        Ref<jvm::Array> piece = jvm::new_array(jvm::array_class(jvm::primitive_class('B')), 1428);
        long long got = 0;
        for (;;) {
            long n = http.read(reinterpret_cast<char*>(piece->bytes.data()), piece->bytes.size(), f);
            if (n < 0) return error(f.text);
            if (n == 0) break;
            if (e.call_static(c, "readCallback", "(I[BI)Z", {Value::I(w.id), Value(piece), Value::I(static_cast<jint>(n))}).z()) return error(url + " aborted");
            got += n;
            if (status < 400) {
                float done = total > 0 ? static_cast<float>(got) / static_cast<float>(total) : 0.0f;
                e.call_static(c, "progressCallback", "(IFFDI)V", {Value::I(w.id), Value::F(1.0f), Value::F(done), Value::D(0.0), Value::I(static_cast<jint>(total))});
            }
        }
        // An HTTP error's body was read as above; the error itself is "<code>: <message>".
        if (status >= 400) error(std::to_string(status) + ": " + reason);
        e.call_static(c, "progressCallback", "(IFFDI)V", {Value::I(w.id), Value::F(1.0f), Value::F(1.0f), Value::D(0.0), Value::I(static_cast<jint>(got))});
        e.call_static(c, "doneCallback", "(I)V", {Value::I(w.id)});
        return;
    }
}

// ---------------------------------------------------------------------------------------------------------------------
// UnityWebRequest: run() on the game's own thread; its callbacks take the request's native pointer.

class WebRequest : public Object {
public:
    using Object::Object;
    jlong ptr = 0;
    std::string method, url;
    std::vector<std::pair<std::string, std::string>> headers;
    jint timeout_ms = 0;
};

void uwr_run(jvm::Env& e, WebRequest& r) {
    Class& c = *jvm::find_class("com/unity3d/player/UnityWebRequest");
    const Value p = Value::J(r.ptr);
    auto error = [&](const Failure& f) { e.call_static(c, "errorCallback", "(JILjava/lang/String;)V", {p, Value::I(f.code), Value(jvm::string(f.text))}); };
    // The body to send: uploadCallback(null) says whether there is one, then fills a 128 KB buffer at a time.
    Ref<jvm::Buffer> buffer = jvm::new_buffer(131072);
    std::string body;
    if (e.call_static(c, "uploadCallback", "(JLjava/nio/ByteBuffer;)I", {p, Value()}).i() > 0) {
        for (;;) {
            jint n = e.call_static(c, "uploadCallback", "(JLjava/nio/ByteBuffer;)I", {p, Value(buffer)}).i();
            if (n <= 0) break;
            body.append(static_cast<const char*>(buffer->address), static_cast<std::size_t>(n));
        }
    }
    // jar: is refused, as UnityWebRequest's Java refuses it; file: is read whole.
    if (strncasecmp(r.url.c_str(), "jar:", 4) == 0) return error(Failure{4, "A URL Connection to a Java ARchive (JAR) file or an entry in a JAR file is not supported"});
    if (is_local(r.url)) {
        std::vector<std::uint8_t> data;
        Failure lf;
        if (!read_local(r.url, data, lf)) return error(lf);
        e.call_static(c, "headerCallback", "(JLjava/lang/String;Ljava/lang/String;)V", {p, Value(jvm::string("content-length")), Value(jvm::string(std::to_string(data.size())))});
        e.call_static(c, "contentLengthCallback", "(JI)V", {p, Value::I(static_cast<jint>(data.size()))});
        for (std::size_t at = 0; at < data.size();) {
            std::size_t n = std::min<std::size_t>(data.size() - at, static_cast<std::size_t>(buffer->capacity));
            std::memcpy(buffer->address, data.data() + at, n);
            at += n;
            if (!e.call_static(c, "downloadCallback", "(JLjava/nio/ByteBuffer;I)Z", {p, Value(buffer), Value::I(static_cast<jint>(n))}).z()) break;
        }
        return;
    }
    Url u;
    Failure f;
    Http http;
    int status = 0;
    std::string reason;
    std::vector<std::pair<std::string, std::string>> headers;
    if (!parse_url(r.url, u, f) || !http.send(r.method, u, r.headers, body, r.timeout_ms, f) || !http.head(status, reason, headers, f)) return error(f);
    e.call_static(c, "responseCodeCallback", "(JI)V", {p, Value::I(status)});
    e.call_static(c, "headerCallback", "(JLjava/lang/String;Ljava/lang/String;)V", {p, Value(jvm::string("Status")), Value(jvm::string(http.status_line()))});
    for (auto& [k, v] : headers) e.call_static(c, "headerCallback", "(JLjava/lang/String;Ljava/lang/String;)V", {p, Value(jvm::string(k)), Value(jvm::string(v))});
    e.call_static(c, "contentLengthCallback", "(JI)V", {p, Value::I(static_cast<jint>(http.content_length()))});
    e.call_static(c, "responseCodeCallback", "(JI)V", {p, Value::I(status)});
    // The body into the buffer, a read at a time; false from the game stops it.
    for (;;) {
        long n = http.read(static_cast<char*>(buffer->address), static_cast<std::size_t>(buffer->capacity), f);
        if (n < 0) return error(f);
        if (n == 0) break;
        if (!e.call_static(c, "downloadCallback", "(JLjava/nio/ByteBuffer;I)Z", {p, Value(buffer), Value::I(static_cast<jint>(n))}).z()) break;
    }
}

}  // namespace

bool http_request(const std::string& method, const std::string& url, const std::vector<std::pair<std::string, std::string>>& headers,
                  const std::string& body, int timeout_ms, int& status, std::string& reply, std::string& error) {
    Url u;
    Failure f;
    Http http;
    std::string reason;
    std::vector<std::pair<std::string, std::string>> got;
    if (!parse_url(url, u, f) || !http.send(method, u, headers, body, timeout_ms, f) || !http.head(status, reason, got, f)) {
        error = f.text;
        return false;
    }
    char chunk[16384];
    for (;;) {
        long n = http.read(chunk, sizeof chunk, f);
        if (n < 0) {
            error = f.text;
            return false;
        }
        if (n == 0) return true;
        reply.append(chunk, static_cast<std::size_t>(n));
    }
}

void define_web() {
    Class& w = jvm::define("com/unity3d/player/WWW", "java/lang/Thread");
    w.make = [](Class& k) -> Object* { return new Www(&k); };
    w.method("<init>", "(ILjava/lang/String;[BLjava/util/Map;)V", [](Call& c) {
        Www& self = c.self_as<Www>();
        self.id = c.i(0);
        self.url = c.str(1);
        if (auto* data = c.as<jvm::Array>(2)) {
            self.has_post = true;
            self.post.assign(reinterpret_cast<const char*>(data->bytes.data()), data->bytes.size());
        }
        self.headers = string_pairs(c.l(3));
        self.name = "WWW";
        return Value();
    });
    w.method("run", "()V", [](Call& c) {
        www_run(c.env, c.self_as<Www>());
        return Value();
    });
    Class& r = jvm::define("com/unity3d/player/UnityWebRequest");
    r.interfaces.push_back(jvm::find_class("java/lang/Runnable"));
    r.make = [](Class& k) -> Object* { return new WebRequest(&k); };
    r.method("<init>", "(JLjava/lang/String;Ljava/util/Map;Ljava/lang/String;I)V", [](Call& c) {
        WebRequest& self = c.self_as<WebRequest>();
        self.ptr = c.j(0);
        self.method = c.str(1);
        self.headers = string_pairs(c.l(2));
        self.url = c.str(3);
        self.timeout_ms = c.i(4);
        return Value();
    });
    r.method("run", "()V", [](Call& c) {
        uwr_run(c.env, c.self_as<WebRequest>());
        return Value();
    });
}

}  // namespace player
