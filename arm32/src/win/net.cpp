// Sockets on Windows (layer.h), with Linux's meaning: Internet sockets on Winsock (winsock.cpp, in plain numbers), which
// block as Linux's do unless O_NONBLOCK says otherwise, and Unix sockets inside the process: a datagram socket bound to
// a path (the player's log, which the guest's liblog writes to) and socket pairs. Addresses, options and flags go from
// Linux's numbers to Winsock's here; Winsock's errors come back as Linux's.
#include "layer.h"

#include <algorithm>
#include <cstring>
#include <deque>
#include <map>

namespace arm32::ws {
// winsock.cpp's side, in plain numbers.
struct Address {
    int family, socktype, protocol;
    std::vector<std::uint8_t> addr;
};
bool startup();
int last_error();
std::uintptr_t open(int family, int type, int protocol);
int close(std::uintptr_t s);
void* event_for(std::uintptr_t s);
void close_event(void* e);
int connect(std::uintptr_t s, const void* addr, int len);
int bind(std::uintptr_t s, const void* addr, int len);
int listen(std::uintptr_t s, int backlog);
std::uintptr_t accept(std::uintptr_t s, void* addr, int* len);
long send(std::uintptr_t s, const void* buf, int n, int flags);
long recv(std::uintptr_t s, void* buf, int n, int flags);
long sendto(std::uintptr_t s, const void* buf, int n, int flags, const void* to, int len);
long recvfrom(std::uintptr_t s, void* buf, int n, int flags, void* from, int* len);
int getsockopt(std::uintptr_t s, int level, int name, void* value, int* len);
int setsockopt(std::uintptr_t s, int level, int name, const void* value, int len);
int getsockname(std::uintptr_t s, void* addr, int* len);
int getpeername(std::uintptr_t s, void* addr, int* len);
int shutdown(std::uintptr_t s, int how);
int available(std::uintptr_t s);
int ready(std::uintptr_t s);
int connect_state(std::uintptr_t s);
int lookup(const char* host, const char* service, int family, int socktype, int flags, std::vector<Address>& out);
}  // namespace arm32::ws

namespace arm32::win {

namespace {

// Winsock's numbers where they are not Linux's.
constexpr int kWinAfInet6 = 23, kWinSolSocket = 0xffff, kWinIpv6V6only = 27, kWinMsgWaitall = 8;
constexpr int kWouldBlock = 10035, kInProgress = 10036, kAlready = 10037, kIsConn = 10056;
constexpr std::uintptr_t kInvalid = ~std::uintptr_t{0};

// A Winsock error as Linux's errno.
int errno_of_ws(int e) {
    switch (e) {
    case 10004: return EINTR;
    case 10009: return EBADF;
    case 10013: return EACCES;
    case 10014: return EFAULT;
    case 10022: return EINVAL;
    case 10024: return EMFILE;
    case kWouldBlock: return EAGAIN;
    case kInProgress: return EINPROGRESS;
    case kAlready: return EALREADY;
    case 10038: return ENOTSOCK;
    case 10039: return EDESTADDRREQ;
    case 10040: return EMSGSIZE;
    case 10041: return EPROTOTYPE;
    case 10042: return ENOPROTOOPT;
    case 10043: return EPROTONOSUPPORT;
    case 10044: return ESOCKTNOSUPPORT;
    case 10045: return EOPNOTSUPP;
    case 10046: return EPFNOSUPPORT;
    case 10047: return EAFNOSUPPORT;
    case 10048: return EADDRINUSE;
    case 10049: return EADDRNOTAVAIL;
    case 10050: return ENETDOWN;
    case 10051: return ENETUNREACH;
    case 10052: return ENETRESET;
    case 10053: return ECONNABORTED;
    case 10054: return ECONNRESET;
    case 10055: return ENOBUFS;
    case kIsConn: return EISCONN;
    case 10057: return ENOTCONN;
    case 10058: return ESHUTDOWN;
    case 10060: return ETIMEDOUT;
    case 10061: return ECONNREFUSED;
    case 10064: return EHOSTDOWN;
    case 10065: return EHOSTUNREACH;
    default: return EIO;
    }
}

int fail_ws() { return fail(errno_of_ws(ws::last_error())); }

// A Linux address as Winsock's: the same layout for IPv4 and IPv6, with IPv6's family number Windows' own.
std::vector<std::uint8_t> to_win(const struct sockaddr* a, socklen_t len) {
    std::vector<std::uint8_t> out(reinterpret_cast<const std::uint8_t*>(a), reinterpret_cast<const std::uint8_t*>(a) + len);
    if (len >= 2 && a->sa_family == AF_INET6) {
        std::uint16_t f = kWinAfInet6;
        std::memcpy(out.data(), &f, 2);
    }
    return out;
}

// And back, into the caller's buffer of `*len` bytes; *len becomes the address's whole length, as Linux sets it.
void from_win(const std::uint8_t* w, int wlen, struct sockaddr* a, socklen_t* len) {
    if (!a || !len) return;
    std::vector<std::uint8_t> v(w, w + wlen);
    if (wlen >= 2) {
        std::uint16_t f;
        std::memcpy(&f, v.data(), 2);
        if (f == kWinAfInet6) {
            f = AF_INET6;
            std::memcpy(v.data(), &f, 2);
        }
    }
    std::memcpy(a, v.data(), std::min<std::size_t>(*len, v.size()));
    *len = static_cast<socklen_t>(v.size());
}

// An Internet socket.
class Socket : public Fd {
public:
    Socket(std::uintptr_t s, int type) : s_(s), type_(type), event_(ws::event_for(s)) {}
    ~Socket() override {
        ws::close_event(event_);
        ws::close(s_);
    }
    std::uintptr_t handle() const { return s_; }
    HANDLE wait_handle() override { return static_cast<HANDLE>(event_); }
    void take_event() override {
        HANDLE h = static_cast<HANDLE>(event_);
        // Set since the last take: a network event, which may have changed what the socket is ready for.
        if (WaitForSingleObject(h, 0) == WAIT_OBJECT_0) {
            ResetEvent(h);
            ++changes_;
        }
    }
    long bytes_ready() override { return ws::available(s_); }
    short ready(short events) override {
        short out = 0;
        if (connecting.load()) {
            // A connect in progress: select's word, which tells of a failed one too.
            int c = ws::connect_state(s_);
            if (c & 1) out |= POLLIN;
            if (c & 2) out |= POLLOUT;
            // Failed: everything at once, as Linux says it, and SO_ERROR says why.
            if (c & 4) out |= POLLIN | POLLOUT | POLLERR | POLLHUP;
            // Connected: WSAPoll's word from now on.
            if ((c & 6) == 2) connecting = false;
        } else {
            int r = ws::ready(s_);
            if (r & 1) out |= POLLIN;
            if (r & 2) out |= POLLOUT;
            if (r & 4) out |= POLLERR;
            if (r & 8) out |= POLLHUP;
        }
        return static_cast<short>(out & (events | POLLERR | POLLHUP));
    }
    ssize_t read(void* buf, std::size_t n) override { return recv(buf, n, 0); }
    ssize_t write(const void* buf, std::size_t n) override { return send(buf, n, 0); }
    int stat(struct stat* st) override {
        std::memset(st, 0, sizeof *st);
        st->st_mode = S_IFSOCK | 0777;
        st->st_blksize = 4096;
        return 0;
    }

    // `op` until it does not say "would block": waiting, unless the socket or the call does not block, for `want`
    // (POLLIN or POLLOUT), up to the socket's own timeout for that direction.
    template <class Op>
    long blocking(short want, bool dontwait, Op&& op) {
        long long timeout = want == POLLIN ? recv_timeout_ns : send_timeout_ns;
        long long deadline = timeout > 0 ? monotonic_ns() + timeout : -1;
        for (;;) {
            // The event first, then the look: a change after the look sets it again.
            take_event();
            long r = op();
            if (r >= 0) return r;
            int e = ws::last_error();
            if (e != kWouldBlock) return fail(errno_of_ws(e));
            if (dontwait || (status_flags.load() & O_NONBLOCK)) return fail(EAGAIN);
            if (ready(want)) continue;
            // A look every 50 ms as well: a network event can come before the reset and be lost.
            long long slice = monotonic_ns() + 50000000LL;
            HANDLE h = static_cast<HANDLE>(event_);
            int w = wait_any(&h, 1, deadline < 0 ? slice : std::min(deadline, slice));
            if (w == -EINTR) return fail(EINTR);
            if (deadline >= 0 && monotonic_ns() >= deadline) return fail(EAGAIN);
        }
    }
    ssize_t recv(void* buf, std::size_t n, int flags) {
        int wf = (flags & MSG_PEEK ? 2 : 0) | (flags & MSG_OOB ? 1 : 0) | (flags & MSG_WAITALL ? kWinMsgWaitall : 0);
        return blocking(POLLIN, flags & MSG_DONTWAIT, [&] { return ws::recv(s_, buf, static_cast<int>(std::min<std::size_t>(n, 1 << 30)), wf); });
    }
    ssize_t send(const void* buf, std::size_t n, int flags) {
        // MSG_NOSIGNAL means nothing here: Windows sends no signal on a broken connection.
        int wf = flags & MSG_OOB ? 1 : 0;
        return blocking(POLLOUT, flags & MSG_DONTWAIT, [&] { return ws::send(s_, buf, static_cast<int>(std::min<std::size_t>(n, 1 << 30)), wf); });
    }
    int type() const { return type_; }
    std::atomic<long long> recv_timeout_ns{0}, send_timeout_ns{0};
    // A connect in progress: its result comes once the socket is writable, or failed.
    std::atomic<bool> connecting{false};

private:
    std::uintptr_t s_;
    int type_;
    void* event_;
};

// A Unix socket inside the process: datagrams or a byte stream, to a peer (a pair's other end, or the socket bound to
// the path it was connected to).
class Unix : public Fd, public std::enable_shared_from_this<Unix> {
public:
    explicit Unix(int type) : type_(type) {}
    ~Unix() override;
    int type() const { return type_; }
    // Takes a datagram, or bytes of the stream, from a peer.
    void deliver(const std::uint8_t* p, std::size_t n) {
        {
            std::lock_guard<std::mutex> l(lock_);
            if (type_ == SOCK_DGRAM) datagrams_.emplace_back(p, p + n);
            else stream_.insert(stream_.end(), p, p + n);
        }
        notify();
    }
    void peer_gone() {
        {
            std::lock_guard<std::mutex> l(lock_);
            peer_closed_ = true;
        }
        notify();
    }
    ssize_t read(void* buf, std::size_t n) override { return recv(buf, n, 0); }
    ssize_t write(const void* buf, std::size_t n) override { return send_to(peer_.lock(), buf, n); }
    ssize_t recv(void* buf, std::size_t n, int flags) {
        HANDLE ev = thread_event();
        for (;;) {
            add_waiter(ev);
            {
                std::lock_guard<std::mutex> l(lock_);
                if (type_ == SOCK_DGRAM && !datagrams_.empty()) {
                    remove_waiter(ev);
                    std::vector<std::uint8_t> d = std::move(datagrams_.front());
                    datagrams_.pop_front();
                    std::size_t k = std::min(n, d.size());
                    std::memcpy(buf, d.data(), k);
                    return static_cast<ssize_t>(k);
                }
                if (type_ != SOCK_DGRAM && (!stream_.empty() || peer_closed_)) {
                    remove_waiter(ev);
                    std::size_t k = std::min(n, stream_.size());
                    std::copy(stream_.begin(), stream_.begin() + static_cast<std::ptrdiff_t>(k), static_cast<std::uint8_t*>(buf));
                    stream_.erase(stream_.begin(), stream_.begin() + static_cast<std::ptrdiff_t>(k));
                    return static_cast<ssize_t>(k);
                }
            }
            if ((flags & MSG_DONTWAIT) || (status_flags.load() & O_NONBLOCK)) {
                remove_waiter(ev);
                return fail(EAGAIN);
            }
            int r = wait_any(&ev, 1, -1);
            remove_waiter(ev);
            if (r == -EINTR) return fail(EINTR);
        }
    }
    ssize_t send_to(const std::shared_ptr<Unix>& to, const void* buf, std::size_t n) {
        if (!to) return fail(type_ == SOCK_DGRAM ? ENOTCONN : EPIPE);
        to->deliver(static_cast<const std::uint8_t*>(buf), n);
        return static_cast<ssize_t>(n);
    }
    long bytes_ready() override {
        std::lock_guard<std::mutex> l(lock_);
        // A datagram socket's next datagram, as Linux's FIONREAD gives it; a stream's every byte.
        if (type_ == SOCK_DGRAM) return datagrams_.empty() ? 0 : static_cast<long>(datagrams_.front().size());
        return static_cast<long>(stream_.size());
    }
    short ready(short events) override {
        std::lock_guard<std::mutex> l(lock_);
        short r = POLLOUT;
        if (!datagrams_.empty() || !stream_.empty()) r |= POLLIN;
        if (peer_closed_) r |= POLLHUP;
        return static_cast<short>(r & (events | POLLHUP));
    }
    int stat(struct stat* st) override {
        std::memset(st, 0, sizeof *st);
        st->st_mode = S_IFSOCK | 0777;
        st->st_blksize = 4096;
        return 0;
    }
    std::weak_ptr<Unix> peer_;
    std::string bound_;

private:
    int type_;
    std::mutex lock_;
    std::deque<std::vector<std::uint8_t>> datagrams_;
    std::deque<std::uint8_t> stream_;
    bool peer_closed_ = false;
};

// Unix sockets bound to a path, by the path.
std::mutex g_unix_lock;
std::map<std::string, std::weak_ptr<Unix>>& bound() {
    static auto* m = new std::map<std::string, std::weak_ptr<Unix>>;
    return *m;
}

Unix::~Unix() {
    if (!bound_.empty()) {
        std::lock_guard<std::mutex> l(g_unix_lock);
        auto it = bound().find(bound_);
        if (it != bound().end() && it->second.expired()) bound().erase(it);
    }
    if (auto p = peer_.lock(); p && type_ != SOCK_DGRAM) p->peer_gone();
}

// A sockaddr_un's path (an abstract name keeps its leading NUL).
std::string unix_path(const struct sockaddr* a, socklen_t len) {
    const auto* u = reinterpret_cast<const struct sockaddr_un*>(a);
    std::size_t n = len > offsetof(struct sockaddr_un, sun_path) ? len - offsetof(struct sockaddr_un, sun_path) : 0;
    n = std::min(n, sizeof u->sun_path);
    std::string p(u->sun_path, n);
    if (!p.empty() && p[0] != '\0') p = p.substr(0, std::strlen(p.c_str()));
    return p;
}

// Linux's socket option as Winsock's level and name; false for one Winsock does not have.
bool win_option(int level, int name, int& wlevel, int& wname) {
    if (level == SOL_SOCKET) {
        wlevel = kWinSolSocket;
        switch (name) {
        case SO_REUSEADDR: wname = 4; return true;
        case SO_KEEPALIVE: wname = 8; return true;
        case SO_BROADCAST: wname = 0x20; return true;
        case SO_LINGER: wname = 0x80; return true;
        case SO_SNDBUF: wname = 0x1001; return true;
        case SO_RCVBUF: wname = 0x1002; return true;
        case SO_ERROR: wname = 0x1007; return true;
        case SO_TYPE: wname = 0x1008; return true;
        default: return false;
        }
    }
    if (level == IPPROTO_TCP && name == TCP_NODELAY) {
        wlevel = IPPROTO_TCP;
        wname = 1;
        return true;
    }
    if (level == IPPROTO_IPV6 && name == IPV6_V6ONLY) {
        wlevel = IPPROTO_IPV6;
        wname = kWinIpv6V6only;
        return true;
    }
    return false;
}

template <class T>
std::shared_ptr<T> as(int fd) {
    return std::dynamic_pointer_cast<T>(fd_get(fd));
}

}  // namespace

}  // namespace arm32::win

using namespace arm32::win;

namespace arm32::posix {

int socket(int domain, int type, int protocol) {
    const int kind = type & 0xf;
    const bool cloexec = type & SOCK_CLOEXEC, nonblock = type & SOCK_NONBLOCK;
    std::shared_ptr<Fd> f;
    if (domain == AF_UNIX) {
        if (kind != SOCK_DGRAM && kind != SOCK_STREAM) return fail(EPROTONOSUPPORT);
        f = std::make_shared<Unix>(kind);
    } else if (domain == AF_INET || domain == AF_INET6) {
        std::uintptr_t s = ws::open(domain == AF_INET6 ? kWinAfInet6 : domain, kind, protocol);
        if (s == kInvalid) return fail_ws();
        f = std::make_shared<Socket>(s, kind);
    } else {
        return fail(EAFNOSUPPORT);
    }
    f->status_flags = O_RDWR | (nonblock ? O_NONBLOCK : 0);
    return fd_add(std::move(f), cloexec);
}

int socketpair(int domain, int type, int, int fds[2]) {
    if (domain != AF_UNIX) return fail(EOPNOTSUPP);
    const int kind = type & 0xf;
    auto a = std::make_shared<Unix>(kind), b = std::make_shared<Unix>(kind);
    a->peer_ = b;
    b->peer_ = a;
    for (auto& u : {a, b}) u->status_flags = O_RDWR | ((type & SOCK_NONBLOCK) ? O_NONBLOCK : 0);
    fds[0] = fd_add(a, type & SOCK_CLOEXEC);
    if (fds[0] < 0) return -1;
    fds[1] = fd_add(b, type & SOCK_CLOEXEC);
    if (fds[1] < 0) {
        close(fds[0]);
        return -1;
    }
    return 0;
}

int bind(int fd, const struct sockaddr* addr, socklen_t len) {
    if (auto u = as<Unix>(fd)) {
        std::string path = unix_path(addr, len);
        std::lock_guard<std::mutex> l(g_unix_lock);
        auto it = bound().find(path);
        if (it != bound().end() && !it->second.expired()) return fail(EADDRINUSE);
        bound()[path] = u;
        u->bound_ = path;
        return 0;
    }
    if (auto s = as<Socket>(fd)) {
        std::vector<std::uint8_t> w = to_win(addr, len);
        return ws::bind(s->handle(), w.data(), static_cast<int>(w.size())) == 0 ? 0 : fail_ws();
    }
    return fail(fd_get(fd) ? ENOTSOCK : EBADF);
}

int listen(int fd, int backlog) {
    if (auto s = as<Socket>(fd)) return ws::listen(s->handle(), backlog) == 0 ? 0 : fail_ws();
    return fail(fd_get(fd) ? EOPNOTSUPP : EBADF);
}

int accept4(int fd, struct sockaddr* addr, socklen_t* len, int flags) {
    auto s = as<Socket>(fd);
    if (!s) return fail(fd_get(fd) ? EOPNOTSUPP : EBADF);
    std::uint8_t w[128];
    int wlen = sizeof w;
    std::uintptr_t a = kInvalid;
    long r = s->blocking(POLLIN, false, [&] {
        wlen = sizeof w;
        a = ws::accept(s->handle(), w, &wlen);
        return a == kInvalid ? -1L : 0L;
    });
    if (r < 0) return -1;
    from_win(w, wlen, addr, len);
    auto f = std::make_shared<Socket>(a, s->type());
    f->status_flags = O_RDWR | ((flags & SOCK_NONBLOCK) ? O_NONBLOCK : 0);
    return fd_add(f, flags & SOCK_CLOEXEC);
}

int connect(int fd, const struct sockaddr* addr, socklen_t len) {
    if (auto u = as<Unix>(fd)) {
        std::string path = unix_path(addr, len);
        std::shared_ptr<Unix> to;
        {
            std::lock_guard<std::mutex> l(g_unix_lock);
            auto it = bound().find(path);
            if (it != bound().end()) to = it->second.lock();
        }
        // Only a datagram socket can be bound here; a stream has no one listening.
        if (!to || to->type() != u->type() || u->type() != SOCK_DGRAM) return fail(ECONNREFUSED);
        u->peer_ = to;
        return 0;
    }
    auto s = as<Socket>(fd);
    if (!s) return fail(fd_get(fd) ? ENOTSOCK : EBADF);
    std::vector<std::uint8_t> w = to_win(addr, len);
    if (ws::connect(s->handle(), w.data(), static_cast<int>(w.size())) == 0) return 0;
    int e = ws::last_error();
    // The socket never blocks under Winsock (its event made it so): a connect in progress is waited for here.
    if (e != kWouldBlock && e != kInProgress && e != kAlready) return e == kIsConn ? 0 : fail(errno_of_ws(e));
    s->connecting = true;
    if (s->status_flags.load() & O_NONBLOCK) return fail(EINPROGRESS);
    // Up to the socket's send timeout, as Linux's connect waits (EINPROGRESS then, the connect going on).
    const long long timeout = s->send_timeout_ns.load();
    const long long deadline = timeout > 0 ? monotonic_ns() + timeout : -1;
    for (;;) {
        // The event first, then the look, as a blocking call's.
        s->take_event();
        short r = s->ready(POLLOUT);
        if (r & (POLLOUT | POLLERR | POLLHUP)) break;
        if (deadline >= 0 && monotonic_ns() >= deadline) return fail(EINPROGRESS);
        HANDLE h = s->wait_handle();
        // A look every 50 ms as well, as a blocking call's.
        long long slice = monotonic_ns() + 50000000LL;
        int k = wait_any(&h, 1, deadline < 0 ? slice : std::min(deadline, slice));
        if (k == -EINTR) return fail(EINTR);
    }
    int err = 0, elen = sizeof err;
    ws::getsockopt(s->handle(), kWinSolSocket, 0x1007, &err, &elen);
    s->connecting = false;
    return err ? fail(errno_of_ws(err)) : 0;
}

ssize_t send(int fd, const void* buf, std::size_t n, int flags) {
    if (auto u = as<Unix>(fd)) return u->send_to(u->peer_.lock(), buf, n);
    if (auto s = as<Socket>(fd)) return s->send(buf, n, flags);
    return fail(fd_get(fd) ? ENOTSOCK : EBADF);
}

ssize_t recv(int fd, void* buf, std::size_t n, int flags) {
    if (auto u = as<Unix>(fd)) return u->recv(buf, n, flags);
    if (auto s = as<Socket>(fd)) return s->recv(buf, n, flags);
    return fail(fd_get(fd) ? ENOTSOCK : EBADF);
}

ssize_t sendto(int fd, const void* buf, std::size_t n, int flags, const struct sockaddr* to, socklen_t len) {
    if (!to) return send(fd, buf, n, flags);
    if (auto u = as<Unix>(fd)) {
        std::shared_ptr<Unix> target;
        {
            std::lock_guard<std::mutex> l(g_unix_lock);
            auto it = bound().find(unix_path(to, len));
            if (it != bound().end()) target = it->second.lock();
        }
        if (!target) return fail(ECONNREFUSED);
        return u->send_to(target, buf, n);
    }
    auto s = as<Socket>(fd);
    if (!s) return fail(fd_get(fd) ? ENOTSOCK : EBADF);
    std::vector<std::uint8_t> w = to_win(to, len);
    return s->blocking(POLLOUT, flags & MSG_DONTWAIT,
                       [&] { return ws::sendto(s->handle(), buf, static_cast<int>(n), 0, w.data(), static_cast<int>(w.size())); });
}

ssize_t recvfrom(int fd, void* buf, std::size_t n, int flags, struct sockaddr* from, socklen_t* len) {
    if (auto u = as<Unix>(fd)) {
        // The sender of an in-process datagram has no name of its own.
        if (len) *len = 0;
        return u->recv(buf, n, flags);
    }
    auto s = as<Socket>(fd);
    if (!s) return fail(fd_get(fd) ? ENOTSOCK : EBADF);
    std::uint8_t w[128];
    int wlen = sizeof w;
    long r = s->blocking(POLLIN, flags & MSG_DONTWAIT, [&] {
        wlen = sizeof w;
        return ws::recvfrom(s->handle(), buf, static_cast<int>(n), flags & MSG_PEEK ? 2 : 0, w, &wlen);
    });
    if (r >= 0) from_win(w, wlen, from, len);
    return r;
}

ssize_t sendmsg(int fd, const struct msghdr* msg, int flags) {
    std::vector<std::uint8_t> all;
    for (std::size_t i = 0; i < msg->msg_iovlen; ++i) {
        const auto* p = static_cast<const std::uint8_t*>(msg->msg_iov[i].iov_base);
        all.insert(all.end(), p, p + msg->msg_iov[i].iov_len);
    }
    return sendto(fd, all.data(), all.size(), flags, static_cast<const struct sockaddr*>(msg->msg_name), msg->msg_namelen);
}

ssize_t recvmsg(int fd, struct msghdr* msg, int flags) {
    std::size_t total = 0;
    for (std::size_t i = 0; i < msg->msg_iovlen; ++i) total += msg->msg_iov[i].iov_len;
    std::vector<std::uint8_t> all(total);
    socklen_t namelen = msg->msg_namelen;
    ssize_t r = recvfrom(fd, all.data(), total, flags, static_cast<struct sockaddr*>(msg->msg_name), msg->msg_name ? &namelen : nullptr);
    if (r < 0) return r;
    msg->msg_namelen = namelen;
    msg->msg_controllen = 0;
    msg->msg_flags = 0;
    std::size_t at = 0;
    for (std::size_t i = 0; i < msg->msg_iovlen && at < static_cast<std::size_t>(r); ++i) {
        std::size_t k = std::min(msg->msg_iov[i].iov_len, static_cast<std::size_t>(r) - at);
        std::memcpy(msg->msg_iov[i].iov_base, all.data() + at, k);
        at += k;
    }
    return r;
}

int getsockopt(int fd, int level, int name, void* value, socklen_t* len) {
    if (auto u = as<Unix>(fd)) {
        // A Unix socket inside the process has no error to report, and its type is its own.
        if (level == SOL_SOCKET && (name == SO_ERROR || name == SO_TYPE) && value && len && *len >= sizeof(int)) {
            *static_cast<int*>(value) = name == SO_ERROR ? 0 : u->type();
            *len = sizeof(int);
            return 0;
        }
        return fail(ENOPROTOOPT);
    }
    auto s = as<Socket>(fd);
    if (!s) return fail(fd_get(fd) ? ENOTSOCK : EBADF);
    if (level == SOL_SOCKET && (name == SO_RCVTIMEO || name == SO_SNDTIMEO)) {
        // The layer's own timeouts, as setsockopt took them.
        if (!value || !len || *len < sizeof(struct timeval)) return fail(EINVAL);
        const long long ns = (name == SO_RCVTIMEO ? s->recv_timeout_ns : s->send_timeout_ns).load();
        auto* tv = static_cast<struct timeval*>(value);
        tv->tv_sec = static_cast<long>(ns / 1000000000LL);
        tv->tv_usec = static_cast<long>(ns % 1000000000LL / 1000);
        *len = sizeof(struct timeval);
        return 0;
    }
    int wlevel, wname;
    if (!win_option(level, name, wlevel, wname)) return fail(ENOPROTOOPT);
    if (level == SOL_SOCKET && name == SO_LINGER) {
        // Winsock's linger is two 16-bit numbers, Linux's two ints.
        if (!value || !len || *len < sizeof(struct linger)) return fail(EINVAL);
        std::uint16_t w[2] = {0, 0};
        int wlen = sizeof w;
        if (ws::getsockopt(s->handle(), wlevel, wname, w, &wlen) != 0) return fail_ws();
        auto* out = static_cast<struct linger*>(value);
        out->l_onoff = w[0];
        out->l_linger = w[1];
        *len = sizeof(struct linger);
        return 0;
    }
    int wlen = static_cast<int>(*len);
    if (ws::getsockopt(s->handle(), wlevel, wname, value, &wlen) != 0) return fail_ws();
    // SO_ERROR comes as Winsock's code: the caller reads Linux's.
    if (level == SOL_SOCKET && name == SO_ERROR && *static_cast<int*>(value)) {
        *static_cast<int*>(value) = errno_of_ws(*static_cast<int*>(value));
        // A connect that failed is over; one still going on reads no error, and stays watched by select.
        s->connecting = false;
    }
    *len = static_cast<socklen_t>(wlen);
    return 0;
}

int setsockopt(int fd, int level, int name, const void* value, socklen_t len) {
    if (as<Unix>(fd)) return 0;
    auto s = as<Socket>(fd);
    if (!s) return fail(fd_get(fd) ? ENOTSOCK : EBADF);
    // Timeouts are the layer's own: the socket never blocks under Winsock.
    if (level == SOL_SOCKET && (name == SO_RCVTIMEO || name == SO_SNDTIMEO) && len >= sizeof(struct timeval)) {
        const auto* tv = static_cast<const struct timeval*>(value);
        long long ns = static_cast<long long>(tv->tv_sec) * 1000000000LL + static_cast<long long>(tv->tv_usec) * 1000LL;
        (name == SO_RCVTIMEO ? s->recv_timeout_ns : s->send_timeout_ns) = ns;
        return 0;
    }
    int wlevel, wname;
    // Options Winsock does not have are accepted and do nothing, as an Android socket would hardly notice.
    if (!win_option(level, name, wlevel, wname)) return 0;
    if (level == SOL_SOCKET && name == SO_LINGER) {
        // Linux's two ints as Winsock's two 16-bit numbers.
        if (len < sizeof(struct linger)) return fail(EINVAL);
        const auto* in = static_cast<const struct linger*>(value);
        std::uint16_t w[2] = {static_cast<std::uint16_t>(in->l_onoff ? 1 : 0), static_cast<std::uint16_t>(std::clamp(in->l_linger, 0, 0xffff))};
        return ws::setsockopt(s->handle(), wlevel, wname, w, sizeof w) == 0 ? 0 : fail_ws();
    }
    return ws::setsockopt(s->handle(), wlevel, wname, value, static_cast<int>(len)) == 0 ? 0 : fail_ws();
}

int getsockname(int fd, struct sockaddr* addr, socklen_t* len) {
    if (auto u = as<Unix>(fd)) {
        struct sockaddr_un un {};
        un.sun_family = AF_UNIX;
        std::memcpy(un.sun_path, u->bound_.data(), std::min(u->bound_.size(), sizeof un.sun_path - 1));
        std::memcpy(addr, &un, std::min<std::size_t>(*len, sizeof un));
        *len = sizeof un;
        return 0;
    }
    auto s = as<Socket>(fd);
    if (!s) return fail(fd_get(fd) ? ENOTSOCK : EBADF);
    std::uint8_t w[128];
    int wlen = sizeof w;
    if (ws::getsockname(s->handle(), w, &wlen) != 0) return fail_ws();
    from_win(w, wlen, addr, len);
    return 0;
}

int getpeername(int fd, struct sockaddr* addr, socklen_t* len) {
    if (as<Unix>(fd)) return fail(ENOTCONN);
    auto s = as<Socket>(fd);
    if (!s) return fail(fd_get(fd) ? ENOTSOCK : EBADF);
    std::uint8_t w[128];
    int wlen = sizeof w;
    if (ws::getpeername(s->handle(), w, &wlen) != 0) return fail_ws();
    from_win(w, wlen, addr, len);
    return 0;
}

int shutdown(int fd, int how) {
    if (as<Unix>(fd)) return 0;
    auto s = as<Socket>(fd);
    if (!s) return fail(fd_get(fd) ? ENOTSOCK : EBADF);
    return ws::shutdown(s->handle(), how) == 0 ? 0 : fail_ws();
}

int getaddrinfo(const char* host, const char* service, const struct addrinfo* hints, struct addrinfo** res) {
    // Linux's hints as Winsock's: the family (IPv6's number differs), the type, and the flags both have.
    int family = hints ? hints->ai_family : AF_UNSPEC;
    int wfamily = family == AF_INET6 ? kWinAfInet6 : family;
    int socktype = hints ? hints->ai_socktype : 0;
    int flags = hints ? hints->ai_flags : 0;
    int wflags = (flags & AI_PASSIVE ? 1 : 0) | (flags & AI_CANONNAME ? 2 : 0) | (flags & AI_NUMERICHOST ? 4 : 0) | (flags & AI_NUMERICSERV ? 8 : 0);
    std::vector<ws::Address> found;
    int r = ws::lookup(host, service, wfamily, socktype, wflags, found);
    if (r != 0) {
        // WSAHOST_NOT_FOUND and WSANO_DATA: no such name; WSATRY_AGAIN: try later; the rest: a failure.
        if (r == 11001 || r == 11004) return EAI_NONAME;
        if (r == 11002) return EAI_AGAIN;
        if (r == 10047) return EAI_FAMILY;
        if (r == 10044) return EAI_SOCKTYPE;
        if (r == 10109) return EAI_SERVICE;
        return EAI_FAIL;
    }
    struct addrinfo* head = nullptr;
    struct addrinfo** tail = &head;
    for (const ws::Address& a : found) {
        // The entry and its address in one block, as freeaddrinfo frees them.
        auto* e = static_cast<struct addrinfo*>(std::calloc(1, sizeof(struct addrinfo) + a.addr.size()));
        auto* sa = reinterpret_cast<struct sockaddr*>(e + 1);
        std::memcpy(sa, a.addr.data(), a.addr.size());
        socklen_t len = static_cast<socklen_t>(a.addr.size());
        from_win(a.addr.data(), static_cast<int>(a.addr.size()), sa, &len);
        e->ai_family = a.family == kWinAfInet6 ? AF_INET6 : a.family;
        e->ai_socktype = a.socktype;
        e->ai_protocol = a.protocol;
        e->ai_addrlen = len;
        e->ai_addr = sa;
        *tail = e;
        tail = &e->ai_next;
    }
    *res = head;
    return head ? 0 : EAI_NONAME;
}

void freeaddrinfo(struct addrinfo* list) {
    while (list) {
        struct addrinfo* next = list->ai_next;
        std::free(list);
        list = next;
    }
}

const char* gai_strerror(int code) {
    switch (code) {
    case EAI_NONAME: return "Name or service not known";
    case EAI_AGAIN: return "Temporary failure in name resolution";
    case EAI_FAMILY: return "ai_family not supported";
    case EAI_SOCKTYPE: return "ai_socktype not supported";
    case EAI_SERVICE: return "Servname not supported for ai_socktype";
    default: return "Non-recoverable failure in name resolution";
    }
}

}  // namespace arm32::posix
