// Winsock for the Windows layer's sockets (net.cpp), in plain numbers only: this file sees Windows' socket headers and
// none of Linux's (ARM32_NO_LINUX), whose structures and constants share their names. Addresses go in and out in
// Winsock's own layout; failures come back as Winsock's error codes, which net.cpp turns into Linux's.
#include <winsock2.h>
#include <ws2tcpip.h>

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace arm32::ws {

// One address of a name lookup: Winsock's family, type and protocol, and its sockaddr bytes.
struct Address {
    int family, socktype, protocol;
    std::vector<std::uint8_t> addr;
};

bool startup() {
    static const bool ok = [] {
        WSADATA data;
        return WSAStartup(MAKEWORD(2, 2), &data) == 0;
    }();
    return ok;
}

int last_error() { return WSAGetLastError(); }

std::uintptr_t open(int family, int type, int protocol) {
    startup();
    SOCKET s = WSASocketW(family, type, protocol, nullptr, 0, WSA_FLAG_OVERLAPPED | WSA_FLAG_NO_HANDLE_INHERIT);
    return s == INVALID_SOCKET ? ~std::uintptr_t{0} : static_cast<std::uintptr_t>(s);
}

int close(std::uintptr_t s) { return closesocket(static_cast<SOCKET>(s)) == 0 ? 0 : -1; }

// An event that the socket's network events set (and which makes the socket non-blocking).
void* event_for(std::uintptr_t s) {
    WSAEVENT e = WSACreateEvent();
    if (e == WSA_INVALID_EVENT) return nullptr;
    WSAEventSelect(static_cast<SOCKET>(s), e, FD_READ | FD_WRITE | FD_ACCEPT | FD_CONNECT | FD_CLOSE | FD_OOB);
    return e;
}

void close_event(void* e) {
    if (e) WSACloseEvent(e);
}

int connect(std::uintptr_t s, const void* addr, int len) { return ::connect(static_cast<SOCKET>(s), static_cast<const sockaddr*>(addr), len) == 0 ? 0 : -1; }
int bind(std::uintptr_t s, const void* addr, int len) { return ::bind(static_cast<SOCKET>(s), static_cast<const sockaddr*>(addr), len) == 0 ? 0 : -1; }
int listen(std::uintptr_t s, int backlog) { return ::listen(static_cast<SOCKET>(s), backlog) == 0 ? 0 : -1; }

std::uintptr_t accept(std::uintptr_t s, void* addr, int* len) {
    SOCKET a = ::accept(static_cast<SOCKET>(s), static_cast<sockaddr*>(addr), len);
    return a == INVALID_SOCKET ? ~std::uintptr_t{0} : static_cast<std::uintptr_t>(a);
}

long send(std::uintptr_t s, const void* buf, int n, int flags) { return ::send(static_cast<SOCKET>(s), static_cast<const char*>(buf), n, flags); }
long recv(std::uintptr_t s, void* buf, int n, int flags) { return ::recv(static_cast<SOCKET>(s), static_cast<char*>(buf), n, flags); }

long sendto(std::uintptr_t s, const void* buf, int n, int flags, const void* to, int len) {
    return ::sendto(static_cast<SOCKET>(s), static_cast<const char*>(buf), n, flags, static_cast<const sockaddr*>(to), len);
}

long recvfrom(std::uintptr_t s, void* buf, int n, int flags, void* from, int* len) {
    return ::recvfrom(static_cast<SOCKET>(s), static_cast<char*>(buf), n, flags, static_cast<sockaddr*>(from), len);
}

int getsockopt(std::uintptr_t s, int level, int name, void* value, int* len) {
    return ::getsockopt(static_cast<SOCKET>(s), level, name, static_cast<char*>(value), len) == 0 ? 0 : -1;
}

int setsockopt(std::uintptr_t s, int level, int name, const void* value, int len) {
    return ::setsockopt(static_cast<SOCKET>(s), level, name, static_cast<const char*>(value), len) == 0 ? 0 : -1;
}

int getsockname(std::uintptr_t s, void* addr, int* len) { return ::getsockname(static_cast<SOCKET>(s), static_cast<sockaddr*>(addr), len) == 0 ? 0 : -1; }
int getpeername(std::uintptr_t s, void* addr, int* len) { return ::getpeername(static_cast<SOCKET>(s), static_cast<sockaddr*>(addr), len) == 0 ? 0 : -1; }
int shutdown(std::uintptr_t s, int how) { return ::shutdown(static_cast<SOCKET>(s), how) == 0 ? 0 : -1; }

// Bytes waiting to be read.
int available(std::uintptr_t s) {
    u_long n = 0;
    ioctlsocket(static_cast<SOCKET>(s), FIONREAD, &n);
    return static_cast<int>(n);
}

// WSAPoll's events now, without waiting: readable 1, writable 2, error 4, hung up 8.
int ready(std::uintptr_t s) {
    WSAPOLLFD p{};
    p.fd = static_cast<SOCKET>(s);
    p.events = POLLRDNORM | POLLWRNORM;
    if (WSAPoll(&p, 1, 0) <= 0) return 0;
    int r = 0;
    if (p.revents & (POLLRDNORM | POLLRDBAND)) r |= 1;
    if (p.revents & POLLWRNORM) r |= 2;
    if (p.revents & (POLLERR | POLLNVAL)) r |= 4;
    if (p.revents & POLLHUP) r |= 8;
    return r;
}

// The same for a socket whose connect is in progress, from select, which says when a connect failed on every Windows
// (WSAPoll says nothing of it before Windows 10 2004): readable 1, writable (connected) 2, failed 4.
int connect_state(std::uintptr_t s) {
    fd_set r, w, e;
    FD_ZERO(&r);
    FD_ZERO(&w);
    FD_ZERO(&e);
    FD_SET(static_cast<SOCKET>(s), &r);
    FD_SET(static_cast<SOCKET>(s), &w);
    FD_SET(static_cast<SOCKET>(s), &e);
    timeval now{0, 0};
    if (::select(0, &r, &w, &e, &now) <= 0) return 0;
    return (FD_ISSET(static_cast<SOCKET>(s), &r) ? 1 : 0) | (FD_ISSET(static_cast<SOCKET>(s), &w) ? 2 : 0) | (FD_ISSET(static_cast<SOCKET>(s), &e) ? 4 : 0);
}

// getaddrinfo: the addresses of `host` (and `service`), of the family and type asked for (0 for any).
int lookup(const char* host, const char* service, int family, int socktype, int flags, std::vector<Address>& out) {
    startup();
    addrinfo hints{};
    hints.ai_family = family;
    hints.ai_socktype = socktype;
    hints.ai_flags = flags;
    addrinfo* res = nullptr;
    int r = ::getaddrinfo(host, service, &hints, &res);
    if (r != 0) return r;
    for (addrinfo* a = res; a; a = a->ai_next) {
        Address x{a->ai_family, a->ai_socktype, a->ai_protocol, {}};
        const auto* p = reinterpret_cast<const std::uint8_t*>(a->ai_addr);
        x.addr.assign(p, p + a->ai_addrlen);
        out.push_back(std::move(x));
    }
    freeaddrinfo(res);
    return 0;
}

}  // namespace arm32::ws
