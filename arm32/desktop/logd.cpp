// The phone's log daemon, for the guest: the guest's liblog writes each line as a datagram to /dev/socket/logdw, and
// on a desktop host that socket is one the player made (host_path moves the name there), read by a thread of its own
// that writes the lines into the runtime's log as logcat would show them.
#include "player.h"

#include "host.h"

#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <string>
#include <sys/socket.h>
#include <sys/un.h>
#include <thread>
#include <unistd.h>

namespace player {

namespace {

// liblog's packet: a packed header (log buffer id, thread id, wall-clock time), then the priority byte, the tag and the
// message, each zero-terminated.
constexpr std::size_t kHeader = 1 + 2 + 8;
// Buffers that hold text (main, radio, system, crash); the events buffer holds binary records.
bool is_text(std::uint8_t id) { return id == 0 || id == 1 || id == 3 || id == 4; }

// logcat's priority letters, by Android's numbers (2 verbose to 7 fatal).
char letter(std::uint8_t prio) {
    static const char kLetters[] = "??VDIWEFS";
    return prio < sizeof kLetters - 1 ? kLetters[prio] : '?';
}

void serve(int fd) {
    name_thread("logd");
    // A datagram never exceeds liblog's own limit of about 4 KB of message.
    std::uint8_t packet[5120];
    for (;;) {
        ssize_t n = recv(fd, packet, sizeof packet, 0);
        if (n < 0) {
            if (errno == EINTR) continue;
            return;
        }
        if (static_cast<std::size_t>(n) < kHeader + 1 || !is_text(packet[0])) continue;
        std::uint16_t tid;
        std::memcpy(&tid, packet + 1, 2);
        std::uint8_t prio = packet[kHeader];
        // The tag and the message follow; a packet cut short leaves them empty rather than unterminated.
        const char* rest = reinterpret_cast<const char*>(packet + kHeader + 1);
        std::size_t left = static_cast<std::size_t>(n) - kHeader - 1;
        std::string tag(rest, strnlen(rest, left));
        std::size_t used = std::min(left, tag.size() + 1);
        std::string message(rest + used, strnlen(rest + used, left - used));
        // One log line per line of the message, as logcat shows them.
        std::size_t start = 0;
        while (start <= message.size()) {
            std::size_t end = message.find('\n', start);
            if (end == std::string::npos) end = message.size();
            if (end > start || start == 0) arm32::log("%c/%s(%u): %.*s", letter(prio), tag.c_str(), tid, static_cast<int>(end - start), message.c_str() + start);
            start = end + 1;
        }
    }
}

}  // namespace

std::string start_logd(const std::string& dir) {
    std::string path = dir + "/logdw";
    int fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return {};
    sockaddr_un a{};
    a.sun_family = AF_UNIX;
    if (path.size() >= sizeof a.sun_path) {
        close(fd);
        return {};
    }
    std::memcpy(a.sun_path, path.c_str(), path.size() + 1);
    // A socket file left by an earlier run of the same name would make bind fail.
    unlink(path.c_str());
    if (bind(fd, reinterpret_cast<sockaddr*>(&a), sizeof a) != 0) {
        close(fd);
        return {};
    }
    std::thread(serve, fd).detach();
    return path;
}

}  // namespace player
