// The broadcast's requests to the server, the same on a phone and on a computer (live_net.h).
#include "live_net.h"

#include "host.h"

#include <algorithm>
#include <cctype>
#include <cerrno>
#include <chrono>
#include <climits>
#include <cstdlib>
#include <cstring>
#include <netdb.h>
#include <poll.h>
#include <sys/socket.h>
#include <system_error>
#include <thread>
#include <time.h>
#include <unistd.h>

namespace arm32::live {

Nanos now_ns() {
    timespec t{};
    clock_gettime(CLOCK_MONOTONIC, &t);
    return static_cast<Nanos>(t.tv_sec) * kSecond + t.tv_nsec;
}

Server parse_server(const std::string& text) {
    Server s;
    // The port after the last colon, 80 without one.
    const std::size_t colon = text.rfind(':');
    s.host = text.substr(0, colon);
    if (colon != std::string::npos) s.port = std::atoi(text.c_str() + colon + 1);
    // The Host header names the server as it was given.
    s.host_header = text;
    return s;
}

// ---- HTTP: plain, one request per connection, all of it within the request's deadline

namespace {

// An address of the server's, as getaddrinfo found it.
struct Address {
    int family = 0, protocol = 0;
    sockaddr_storage address{};
    socklen_t length = 0;
};

// The addresses `resolve` finds for `host` and `port`, for a stream socket; none when it finds none or fails.
std::vector<Address> resolve_all(Resolver resolve, const std::string& host, const std::string& port, int flags) {
    std::vector<Address> out;
    addrinfo hints{};
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags = flags;
    addrinfo* list = nullptr;
    if (resolve(host.c_str(), port.c_str(), &hints, &list) != 0) return out;
    for (const addrinfo* a = list; a; a = a->ai_next) {
        // socklen_t is signed on some systems (32-bit Android): its size as a size, to compare and copy.
        const auto size = static_cast<std::size_t>(a->ai_addrlen);
        // One that would not fit is no address of any family this code connects to.
        if (!a->ai_addr || size > sizeof(sockaddr_storage)) continue;
        Address x;
        x.family = a->ai_family;
        x.protocol = a->ai_protocol;
        std::memcpy(&x.address, a->ai_addr, size);
        x.length = a->ai_addrlen;
        out.push_back(x);
    }
    freeaddrinfo(list);
    return out;
}

// Waits until `fd` is ready for `events` (or has failed, which the next call on it says), up to `deadline`: false once
// that has passed.
bool wait_ready(int fd, short events, Nanos deadline) {
    for (;;) {
        const Nanos left = deadline - now_ns();
        if (left <= 0) return false;
        pollfd p{};
        p.fd = fd;
        p.events = events;
        // What is left in milliseconds, rounded up: the last part of one is waited for, not spun through.
        const int ms = static_cast<int>(std::min<Nanos>((left + 999999) / 1000000, INT_MAX));
        const int n = poll(&p, 1, ms);
        if (n > 0) return true;
        // Interrupted: again, for what is left. Any other failure ends the wait as the deadline would.
        if (n < 0 && errno != EINTR) return false;
    }
}

// A connection to one of `addresses` within the deadline, or -1. The socket does not block: connect, send and recv
// come back at once, and poll waits for what is left. An address that does not answer leaves those after it their
// share of the time, rather than all of it.
int connect_any(const std::vector<Address>& addresses, Nanos deadline) {
    for (std::size_t i = 0; i < addresses.size(); ++i) {
        const Address& a = addresses[i];
        const Nanos now = now_ns();
        if (now >= deadline) break;
        // An equal part of what is left with each address after this one.
        const Nanos until = now + (deadline - now) / static_cast<Nanos>(addresses.size() - i);
        const int fd = socket(a.family, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, a.protocol);
        if (fd < 0) continue;
        // At once on a local address; otherwise under way, and done once the socket can be written to.
        if (connect(fd, reinterpret_cast<const sockaddr*>(&a.address), a.length) == 0) return fd;
        if (errno == EINPROGRESS && wait_ready(fd, POLLOUT, until)) {
            // Writable: connected, or failed, which SO_ERROR tells.
            int error = 0;
            socklen_t length = sizeof error;
            if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &length) == 0 && error == 0) return fd;
        }
        close(fd);
    }
    return -1;
}

// All of `data` by the deadline, or false: the connection broke, or the server took too long to take it.
bool send_all(int fd, const void* data, std::size_t size, Nanos deadline) {
    auto* p = static_cast<const char*>(data);
    while (size > 0) {
        // No SIGPIPE for a connection the server closed: the error is enough.
        const ssize_t n = send(fd, p, size, MSG_NOSIGNAL);
        if (n > 0) {
            p += n;
            size -= static_cast<std::size_t>(n);
            continue;
        }
        if (n < 0 && errno == EINTR) continue;
        // The socket's buffer is full: on once the server has taken some, if it does in time.
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) && wait_ready(fd, POLLOUT, deadline)) continue;
        return false;
    }
    return true;
}

// The answer, read until the server closes the connection, where an HTTP/1.0 answer ends: true with it in `in`. False
// when the deadline cuts it, or it runs past kMaxAnswer: neither is an answer to go by.
bool receive(int fd, std::string& in, Nanos deadline) {
    char buffer[4096];
    for (;;) {
        const ssize_t n = recv(fd, buffer, sizeof buffer, 0);
        // The connection's end: the answer's.
        if (n == 0) return true;
        if (n > 0) {
            // A notice and a few numbers: an answer past this is not one of ours.
            if (in.size() + static_cast<std::size_t>(n) > kMaxAnswer) return false;
            in.append(buffer, static_cast<std::size_t>(n));
            continue;
        }
        if (errno == EINTR) continue;
        // Nothing yet: more once there is some, if it comes in time.
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            if (wait_ready(fd, POLLIN, deadline)) continue;
            return false;
        }
        // Broken off (a reset): what came is the answer as far as it goes, which the status line and the headers' end
        // then have to be in.
        return true;
    }
}

}  // namespace

// A lookup of the server's name on a thread of its own (Link::look_up).
struct Link::Lookup {
    std::mutex lock;
    std::condition_variable done_wake;
    bool done = false;               // the thread has an answer
    std::vector<Address> addresses;  // what it found: none for no such name, or a resolver that failed
    Nanos done_at = 0;               // when it was done
};

std::shared_ptr<Link::Lookup> Link::look_up(Nanos deadline) {
    std::shared_ptr<Lookup> l;
    {
        std::lock_guard<std::mutex> guard(lookup_lock_);
        if (lookup_) {
            std::lock_guard<std::mutex> last(lookup_->lock);
            // Still out: this request waits for that one too, so that a resolver that does not answer holds one thread,
            // not one for each request. Done with addresses, lately: as it found them.
            if (!lookup_->done || (!lookup_->addresses.empty() && now_ns() - lookup_->done_at < kLookupKept)) l = lookup_;
        }
        if (!l) {
            l = std::make_shared<Lookup>();
            // Copies of what the thread needs: it may outlive this request, and in the tests this Link.
            const std::string host = server_.host, port = std::to_string(server_.port);
            const Resolver resolve = resolver ? resolver : &::getaddrinfo;
            const char* name = names_.lookup_thread;
            void (*start)(const char*) = names_.thread_start;
            try {
                std::thread([l, host, port, resolve, name, start] {
                    // This side's name, priority and signals for the thread.
                    if (start) start(name);
                    std::vector<Address> found = resolve_all(resolve, host, port, 0);
                    std::lock_guard<std::mutex> answer(l->lock);
                    l->addresses = std::move(found);
                    l->done = true;
                    l->done_at = now_ns();
                    l->done_wake.notify_all();
                }).detach();
            } catch (const std::system_error&) {
                // No thread to be had: no lookup, and this request fails as one with no answer.
                return nullptr;
            }
            lookup_ = l;
        }
    }
    std::unique_lock<std::mutex> wait(l->lock);
    while (!l->done) {
        // What is left of the request's time, by the same clock as its deadline.
        const Nanos left = deadline - now_ns();
        if (left <= 0) return nullptr;
        l->done_wake.wait_for(wait, std::chrono::nanoseconds(left));
    }
    return l;
}

void Link::forget(const std::shared_ptr<Lookup>& lookup) {
    std::lock_guard<std::mutex> guard(lookup_lock_);
    // Only that one: a newer lookup may have taken its place meanwhile.
    if (lookup_ == lookup) lookup_.reset();
}

HttpResult Link::request(const char* method, const std::string& path, const std::string& extra_headers, const void* body,
                         std::size_t body_size) {
    HttpResult r;
    // The time this request has in all, from the lookup to the answer's end.
    const Nanos deadline = now_ns() + limit;
    // A server named by its address needs no lookup, and asks nothing of the network for it.
    std::vector<Address> addresses = resolve_all(&::getaddrinfo, server_.host, std::to_string(server_.port), AI_NUMERICHOST);
    std::shared_ptr<Lookup> looked;
    if (addresses.empty()) {
        // A name: its lookup, waited for until the deadline at most. Done, its addresses no longer change.
        looked = look_up(deadline);
        if (!looked) return r;
        addresses = looked->addresses;
    }
    const int fd = connect_any(addresses, deadline);
    if (fd < 0) {
        // No address answered: the name is looked up again next time (the server may have moved).
        if (looked) forget(looked);
        return r;
    }
    // The request line and headers: this side's User-Agent, and a body's length when it has one.
    std::string head = std::string(method) + " " + path + " HTTP/1.0\r\nHost: " + server_.host_header + "\r\nUser-Agent: " + names_.user_agent +
                       "\r\n" + extra_headers;
    if (body) head += "Content-Length: " + std::to_string(body_size) + "\r\n";
    head += "\r\n";
    std::string in;
    if (send_all(fd, head.data(), head.size(), deadline) && (!body || send_all(fd, body, body_size, deadline)) && receive(fd, in, deadline)) {
        // The status line's number, and the body after the headers.
        const std::size_t space = in.find(' ');
        const std::size_t end = in.find("\r\n\r\n");
        if (in.rfind("HTTP/", 0) == 0 && space != std::string::npos && end != std::string::npos) {
            r.status = std::atoi(in.c_str() + space + 1);
            r.body = in.substr(end + 4);
        }
    }
    close(fd);
    return r;
}

// ---- reading the server's small JSON answer: flat, with known keys

std::size_t json_value(const std::string& json, const char* key) {
    // The key with its quotes: a value's own quotes are escaped, so no value can hold this.
    const std::string quoted = std::string("\"") + key + "\"";
    std::size_t at = json.find(quoted);
    if (at == std::string::npos) return at;
    at = json.find(':', at + quoted.size());
    if (at == std::string::npos) return at;
    ++at;
    // The white space JSON allows before a value.
    while (at < json.size() && (json[at] == ' ' || json[at] == '\t' || json[at] == '\n' || json[at] == '\r')) ++at;
    return at < json.size() ? at : std::string::npos;
}

bool json_bool(const std::string& json, const char* key) {
    std::size_t at = json_value(json, key);
    return at != std::string::npos && json.compare(at, 4, "true") == 0;
}

int json_int(const std::string& json, const char* key, int fallback) {
    std::size_t at = json_value(json, key);
    // A number starts with a digit here: the server sends no negative ones.
    if (at == std::string::npos || !(json[at] >= '0' && json[at] <= '9')) return fallback;
    return std::atoi(json.c_str() + at);
}

namespace {

// A character of the Basic Multilingual Plane, as UTF-8.
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

// Only what a key or an id is made of: letters, digits, '-' and '_', at most 128 of them.
bool plain(std::string_view text) {
    return !text.empty() && text.size() <= 128 &&
           std::all_of(text.begin(), text.end(), [](char x) { return std::isalnum(static_cast<unsigned char>(x)) || x == '-' || x == '_'; });
}

}  // namespace

std::string json_string(const std::string& json, const char* key) {
    std::string out;
    std::size_t at = json_value(json, key);
    // Not a string: nothing.
    if (at == std::string::npos || json[at] != '"') return out;
    for (++at; at < json.size() && json[at] != '"'; ++at) {
        if (json[at] != '\\') {
            out += json[at];
            continue;
        }
        // An escape: the character after the backslash says which.
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
        // A quote, a backslash or a slash: itself.
        default: out += json[at];
        }
    }
    return out;
}

State parse_state(const HttpResult& r) {
    State s;
    // No answer: as things were. A server without live view (an older one) answers 404: off.
    s.answered = r.status != 0;
    if (!s.answered) return s;
    const std::string token = json_string(r.body, "token");
    // It goes into a request header: only what a token is made of.
    s.on = r.status == 200 && json_bool(r.body, "on") && plain(token);
    if (s.on) s.token = token;
    // What the server asks for, within what the encoders here are set up for.
    s.fps = std::clamp(json_int(r.body, "fps", 30), 5, 60);
    s.height = std::clamp(json_int(r.body, "height", 720), 144, 1080);
    s.bitrate = std::clamp(json_int(r.body, "bitrate", 2000000), 100000, 20000000);
    s.segment = std::clamp(json_int(r.body, "segment", 2), 1, 10);
    s.toast = json_string(r.body, "toast");
    return s;
}

void add_id(std::string& ids, std::string_view id) {
    // Only what the login's ids are made of: this goes straight in a URL.
    if (!plain(id)) return;
    // Once: the same id under two of the platform SDK's names is one player. Whole ids are compared, not their parts.
    for (std::size_t at = 0; at <= ids.size();) {
        const std::size_t comma = std::min(ids.find(',', at), ids.size());
        if (std::string_view(ids).substr(at, comma - at) == id) return;
        at = comma + 1;
    }
    if (!ids.empty()) ids += ',';
    ids += id;
}

// ---- the upload thread

void Link::set_identity(const std::string& ids, const State& state) {
    std::lock_guard<std::mutex> l(identity_lock_);
    ids_ = ids;
    // Off keeps the last key: the stream's end still goes out with it.
    if (state.on) token_ = state.token;
}

void Link::queue_segment(Segment&& s) {
    // Nothing to send, or more than the server takes.
    if (s.bytes.empty() || s.bytes.size() > kMaxSegment) return;
    std::lock_guard<std::mutex> l(upload_lock_);
    // A network this slow: the newest pictures matter most, and the quality has to come down.
    if (uploads_.size() >= kUploadQueue) {
        uploads_.pop_front();
        dropped.fetch_add(1, std::memory_order_relaxed);
        network_step.store(std::min(network_step.load() + 1, kLastStep));
    }
    uploads_.push_back(std::move(s));
    upload_wake_.notify_one();
}

void Link::end_stream() {
    {
        // Under the queue's lock: the upload thread looks at it there before it waits.
        std::lock_guard<std::mutex> l(upload_lock_);
        end_due_.store(true);
        upload_wake_.notify_one();
    }
    // Back at the top step for the next time.
    network_step.store(0);
}

void Link::run() {
    // This side's name, priority and signals for the thread.
    if (names_.thread_start) names_.thread_start(names_.upload_thread);
    for (;;) upload_one();
}

void Link::upload_one() {
    Segment s;
    bool end = false;
    {
        // A segment, or the stream's end once every segment before it is out.
        std::unique_lock<std::mutex> l(upload_lock_);
        upload_wake_.wait(l, [this] { return !uploads_.empty() || end_due_.load(); });
        if (!uploads_.empty()) {
            s = std::move(uploads_.front());
            uploads_.pop_front();
        } else {
            end = end_due_.exchange(false);
        }
    }
    std::string ids, token;
    {
        std::lock_guard<std::mutex> l(identity_lock_);
        ids = ids_;
        token = token_;
    }
    const std::string header = "X-Live-Token: " + token + "\r\n";
    if (end) {
        // Without a key the stream never started on the server.
        if (!token.empty()) request("POST", "/live/end?ids=" + ids, header, "", 0);
        return;
    }
    const Nanos start = now_ns();
    HttpResult r = request("POST", "/live/upload?ids=" + ids + "&seq=" + std::to_string(s.seq) + "&dur=" + std::to_string(s.duration_ms),
                           header + "Content-Type: video/mp2t\r\n", s.bytes.data(), s.bytes.size());
    const Nanos took = now_ns() - start;
    if (r.status == 403) {
        // The server's owner turned it off, or a new key is out: the control thread asks next.
        arm32::log("%s: the server refused a segment", names_.log_prefix);
        if (on_refused) on_refused();
        return;
    }
    if (r.status / 100 != 2) {
        arm32::log("%s: upload failed, status %d", names_.log_prefix, r.status);
        dropped.fetch_add(1, std::memory_order_relaxed);
    } else {
        uploaded.fetch_add(1, std::memory_order_relaxed);
    }
    // The share of a segment's own length its upload took. Two near the whole length: a step down. A long good run (a
    // minute of them): a step back up.
    const double share = s.duration_ms > 0 ? static_cast<double>(took) / (static_cast<double>(s.duration_ms) * 1e6) : 0;
    // A refusal (a full disk, say) says nothing about the network: only no answer or a slow one does.
    if (r.status == 0 || share > 0.8) {
        fast_ = 0;
        if (++slow_ >= 2) {
            slow_ = 0;
            network_step.store(std::min(network_step.load() + 1, kLastStep));
        }
    } else {
        slow_ = 0;
        if (share < 0.3 && ++fast_ >= 30) {
            fast_ = 0;
            network_step.store(std::max(network_step.load() - 1, 0));
        }
    }
}

}  // namespace arm32::live
