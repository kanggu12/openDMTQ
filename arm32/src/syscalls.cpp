// ARM EABI system calls, carried out by the host kernel.
//
// Guest file descriptors, process and thread ids are the host's own. Pointers are guest
// addresses and are turned into host pointers; structures whose 32-bit layout differs from the
// host's are converted field by field. Paths under /system/lib and /system/bin/linker lead to
// the guest's sysroot, and a few /proc files are generated for the guest's point of view.
#include "thread.h"

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <climits>
#include <condition_variable>
#include <cstdarg>
#include <cstddef>
#include <cstring>
#include <ctime>
#include <dirent.h>
#include <fcntl.h>
#include <linux/futex.h>
#include <poll.h>
#include <pthread.h>
#include <sched.h>
#include <sys/epoll.h>
#include <sys/file.h>
#include <sys/eventfd.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <mutex>
#include <string>
#include <set>
#include <netinet/in.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/syscall.h>
#include <sys/sysinfo.h>
#ifdef __ANDROID__
#include <sys/system_properties.h>
#endif
#include <sys/time.h>
#include <sys/times.h>
#include <sys/uio.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <termios.h>
#include <type_traits>
#include <ucontext.h>
#include <unistd.h>

namespace arm32 {

thread_local std::int64_t t_guest_sleep_ns = 0;

namespace {

// ---------------------------------------------------------------------------------------------
// 32-bit ARM structure layouts (EABI: 64-bit members are 8-byte aligned).

struct Timespec32 {
    std::int32_t tv_sec;
    std::int32_t tv_nsec;
};
struct Timeval32 {
    std::int32_t tv_sec;
    std::int32_t tv_usec;
};
struct Iovec32 {
    std::uint32_t base;
    std::uint32_t len;
};
struct Stat64Arm {
    std::uint64_t st_dev;
    std::uint8_t pad0[4];
    std::uint32_t st_ino_low;
    std::uint32_t st_mode;
    std::uint32_t st_nlink;
    std::uint32_t st_uid;
    std::uint32_t st_gid;
    std::uint64_t st_rdev;
    std::uint8_t pad3[4];
    std::uint8_t pad4[4];
    std::int64_t st_size;
    std::uint32_t st_blksize;
    std::uint8_t pad5[4];
    std::uint64_t st_blocks;
    std::uint32_t atime_s;
    std::uint32_t atime_ns;
    std::uint32_t mtime_s;
    std::uint32_t mtime_ns;
    std::uint32_t ctime_s;
    std::uint32_t ctime_ns;
    std::uint64_t st_ino;
};
static_assert(sizeof(Stat64Arm) == 104, "struct stat64 on ARM is 104 bytes");
static_assert(offsetof(Stat64Arm, st_size) == 48 && offsetof(Stat64Arm, st_blocks) == 64 && offsetof(Stat64Arm, st_ino) == 96);

struct __attribute__((packed, aligned(4))) Statfs64Arm {
    std::uint32_t f_type;
    std::uint32_t f_bsize;
    std::uint64_t f_blocks;
    std::uint64_t f_bfree;
    std::uint64_t f_bavail;
    std::uint64_t f_files;
    std::uint64_t f_ffree;
    std::int32_t f_fsid[2];
    std::uint32_t f_namelen;
    std::uint32_t f_frsize;
    std::uint32_t f_flags;
    std::uint32_t f_spare[4];
};
static_assert(sizeof(Statfs64Arm) == 84, "struct statfs64 on ARM EABI is packed to 84 bytes");

struct SigactionArm {
    std::uint32_t handler;
    std::uint32_t flags;
    std::uint32_t restorer;
    std::uint64_t mask;
} __attribute__((packed));
static_assert(sizeof(SigactionArm) == 20);

struct Rlimit32 {
    std::uint32_t cur;
    std::uint32_t max;
};

struct EpollEventArm {
    std::uint32_t events;
    std::uint32_t pad;
    std::uint64_t data;
};
static_assert(sizeof(EpollEventArm) == 16);

struct MsghdrArm {
    std::uint32_t name;
    std::uint32_t namelen;
    std::uint32_t iov;
    std::uint32_t iovlen;
    std::uint32_t control;
    std::uint32_t controllen;
    std::int32_t flags;
};

// ARM values of the open() flags that differ from the host's (asm-generic) ones.
constexpr std::uint32_t kArmDirectory = 040000, kArmNofollow = 0100000, kArmDirect = 0200000, kArmLargefile = 0400000;

int open_flags_to_host(std::uint32_t f) {
    int h = static_cast<int>(f & ~(kArmDirectory | kArmNofollow | kArmDirect | kArmLargefile));
    if (f & kArmDirectory) h |= O_DIRECTORY;
    if (f & kArmNofollow) h |= O_NOFOLLOW;
    if (f & kArmDirect) h |= O_DIRECT;
    return h;  // O_LARGEFILE is implied on 64-bit hosts
}

std::uint32_t open_flags_to_arm(int h) {
    std::uint32_t f = static_cast<std::uint32_t>(h & ~(O_DIRECTORY | O_NOFOLLOW | O_DIRECT | O_LARGEFILE));
    if (h & O_DIRECTORY) f |= kArmDirectory;
    if (h & O_NOFOLLOW) f |= kArmNofollow;
    if (h & O_DIRECT) f |= kArmDirect;
    return f | kArmLargefile;  // a 32-bit libc always asks for large files
}

// ---------------------------------------------------------------------------------------------
// Helpers.

std::uint32_t err(int e) { return static_cast<std::uint32_t>(-e); }
// Result of a host call that sets errno on failure.
std::uint32_t res(long r) { return r < 0 ? err(errno) : static_cast<std::uint32_t>(r); }

// What arm32_isys reads (isys_*.S): the field order is fixed.
struct IsysGate {
    const std::atomic<std::uint64_t>* pending;
    std::uint64_t blocked;
    long nr;
};
static_assert(sizeof(std::atomic<std::uint64_t>) == 8 && std::atomic<std::uint64_t>::is_always_lock_free);

}  // namespace
}  // namespace arm32

// Arguments as the host passes system call arguments: as wide as a pointer (Windows' long is not).
extern "C" std::intptr_t arm32_isys(std::intptr_t a0, std::intptr_t a1, std::intptr_t a2, std::intptr_t a3, std::intptr_t a4, std::intptr_t a5,
                                   const arm32::IsysGate* gate);
extern "C" char arm32_isys_begin[], arm32_isys_end[], arm32_isys_cancel[];

namespace arm32 {
namespace {

// Host system call nr for a guest thread, for every call that can block: a signal for the
// thread gets it out (EINTR) even when it arrives just before the call. Returns like a libc
// wrapper: -1 with errno on failure. Only calls that may sleep come here: one that never blocks
// (a futex wake) must not be skipped for a signal, the kernel would just have made it.
//
// The interrupt signal can come late, after the guest signal it was sent for was delivered some
// other way. It then never cancels a call (the handler checks that a signal is still ready), but
// it can still cut short a call that was asleep in the kernel. With restart set, such a call is
// made again, as the kernel would never have interrupted it; for the others (futex waits, epoll
// waits, connect) the caller sees EINTR, which they allow for.
long blocking(Thread& t, bool restart, long nr, std::intptr_t a0 = 0, std::intptr_t a1 = 0, std::intptr_t a2 = 0, std::intptr_t a3 = 0,
              std::intptr_t a4 = 0, std::intptr_t a5 = 0) {
    for (;;) {
        IsysGate gate{&t.pending, t.sigmask, nr};
        std::intptr_t r = arm32_isys(a0, a1, a2, a3, a4, a5, &gate);
        if (r == -EINTR && restart && !t.signal_ready()) continue;
        if (r < 0 && r > -4096) {
            errno = static_cast<int>(-r);
            return -1;
        }
        return static_cast<long>(r);
    }
}
constexpr bool kRestart = true, kNoRestart = false;

// Adds the time a guest thread spends in a sleep call to its t_guest_sleep_ns.
class GuestSleep {
public:
    GuestSleep() { clock_gettime(CLOCK_MONOTONIC, &start_); }
    ~GuestSleep() {
        timespec end{};
        clock_gettime(CLOCK_MONOTONIC, &end);
        t_guest_sleep_ns += (end.tv_sec - start_.tv_sec) * 1000000000LL + (end.tv_nsec - start_.tv_nsec);
    }
    GuestSleep(const GuestSleep&) = delete;
    GuestSleep& operator=(const GuestSleep&) = delete;

private:
    timespec start_{};
};

// Guest values as host system call arguments: signed ints keep their sign, pointers become host
// pointers (0 stays null).
long sint(std::uint32_t v) { return static_cast<std::int32_t>(v); }

// A NUL-terminated guest string, or false when it runs into an unmapped page.
bool guest_str(Process& p, gaddr g, std::string& out, std::size_t max = PATH_MAX) {
    out.clear();
    if (!g) return false;
    for (std::size_t i = 0; i < max; ++i) {
        if (!p.mem.readable(g + static_cast<gaddr>(i), 1)) return false;
        char c = static_cast<char>(*p.mem.host(g + static_cast<gaddr>(i)));
        if (!c) return true;
        out.push_back(c);
    }
    return false;
}

timespec to_host(const Timespec32& t) { return timespec{t.tv_sec, t.tv_nsec}; }
Timespec32 to_arm(const timespec& t) { return Timespec32{static_cast<std::int32_t>(t.tv_sec), static_cast<std::int32_t>(t.tv_nsec)}; }

void put_stat(Process& p, gaddr dst, const struct stat& st) {
    Stat64Arm a{};
    a.st_dev = st.st_dev;
    a.st_ino_low = static_cast<std::uint32_t>(st.st_ino);
    a.st_mode = st.st_mode;
    a.st_nlink = static_cast<std::uint32_t>(st.st_nlink);
    a.st_uid = st.st_uid;
    a.st_gid = st.st_gid;
    a.st_rdev = st.st_rdev;
    a.st_size = st.st_size;
    a.st_blksize = static_cast<std::uint32_t>(st.st_blksize);
    a.st_blocks = static_cast<std::uint64_t>(st.st_blocks);
    a.atime_s = static_cast<std::uint32_t>(st.st_atim.tv_sec);
    a.atime_ns = static_cast<std::uint32_t>(st.st_atim.tv_nsec);
    a.mtime_s = static_cast<std::uint32_t>(st.st_mtim.tv_sec);
    a.mtime_ns = static_cast<std::uint32_t>(st.st_mtim.tv_nsec);
    a.ctime_s = static_cast<std::uint32_t>(st.st_ctim.tv_sec);
    a.ctime_ns = static_cast<std::uint32_t>(st.st_ctim.tv_nsec);
    a.st_ino = st.st_ino;
    std::memcpy(p.mem.host(dst), &a, sizeof a);
}

void put_statfs(Process& p, gaddr dst, const struct statfs& s) {
    Statfs64Arm a{};
    a.f_type = static_cast<std::uint32_t>(s.f_type);
    a.f_bsize = static_cast<std::uint32_t>(s.f_bsize);
    a.f_blocks = s.f_blocks;
    a.f_bfree = s.f_bfree;
    a.f_bavail = s.f_bavail;
    a.f_files = s.f_files;
    a.f_ffree = s.f_ffree;
    std::memcpy(a.f_fsid, &s.f_fsid, sizeof a.f_fsid);
    a.f_namelen = static_cast<std::uint32_t>(s.f_namelen);
    a.f_frsize = static_cast<std::uint32_t>(s.f_frsize);
    a.f_flags = static_cast<std::uint32_t>(s.f_flags);
    std::memcpy(p.mem.host(dst), &a, sizeof a);
}

// Guest iovec array to host iovecs; false if any part is unmapped.
bool get_iovecs(Process& p, gaddr iov, std::uint32_t count, std::vector<iovec>& out) {
    if (count > IOV_MAX || !p.mem.readable(iov, count * sizeof(Iovec32))) return false;
    out.resize(count);
    for (std::uint32_t i = 0; i < count; ++i) {
        Iovec32 v;
        std::memcpy(&v, p.mem.host(iov + i * sizeof(Iovec32)), sizeof v);
        out[i].iov_base = p.mem.host(v.base);
        out[i].iov_len = v.len;
    }
    return true;
}

// A file descriptor reading `text` from the start, for generated /proc files.
int text_fd(const std::string& text, int flags) {
    int fd = static_cast<int>(syscall(__NR_memfd_create, "arm32-proc", (flags & O_CLOEXEC) ? 1u : 0u));
    if (fd < 0) return -1;
    std::size_t done = 0;
    while (done < text.size()) {
        ssize_t n = write(fd, text.data() + done, text.size() - done);
        if (n <= 0) break;
        done += static_cast<std::size_t>(n);
    }
    lseek(fd, 0, SEEK_SET);
    return fd;
}

// The CPUs the guest is told of: the host's, or fewer when the process says so (Process::max_cpus).
long guest_cpus(const Process& p) {
    long cpus = sysconf(_SC_NPROCESSORS_CONF);
    return p.max_cpus > 0 && p.max_cpus < cpus ? p.max_cpus : cpus;
}

// /proc/cpuinfo as a 32-bit ARMv7 kernel would show it, one entry per CPU the guest is told of.
std::string cpuinfo_text(const Process& p) {
    std::string out;
    long cpus = guest_cpus(p);
    for (long i = 0; i < cpus; ++i) {
        out += "processor\t: " + std::to_string(i) + "\n";
        out += "model name\t: ARMv7 Processor rev 1 (v7l)\n";
        out += "BogoMIPS\t: 38.40\n";
        out += "Features\t: half thumb fastmult vfp edsp neon vfpv3 tls vfpv4 idiva idivt vfpd32 lpae evtstrm\n";
        out += "CPU implementer\t: 0x41\nCPU architecture: 7\nCPU variant\t: 0x0\nCPU part\t: 0xc0f\nCPU revision\t: 1\n\n";
    }
    out += "Hardware\t: arm32 runtime\nRevision\t: 0000\nSerial\t\t: 0000000000000000\n";
    return out;
}

// The process id guest code may name this process by: the host's, or the one the guest's C library
// took at start-up (see Process::guest_pid).
bool is_own_pid(const Process& p, int pid) {
    int guest = p.guest_pid.load();
    return pid == getpid() || (guest && pid == guest);
}

bool is_self_proc(const Process& p, const std::string& path, const char* leaf) {
    // /proc/self/<leaf>, /proc/<our pid>/<leaf> (either pid) and /proc/self/task/<tid>/<leaf>.
    std::string pid = "/proc/" + std::to_string(getpid()) + "/";
    std::string guest_pid = "/proc/" + std::to_string(p.guest_pid.load()) + "/";
    std::string rest;
    if (path.rfind("/proc/self/", 0) == 0) rest = path.substr(11);
    else if (path.rfind(pid, 0) == 0) rest = path.substr(pid.size());
    else if (p.guest_pid.load() && path.rfind(guest_pid, 0) == 0) rest = path.substr(guest_pid.size());
    else if (path.rfind("/proc/thread-self/", 0) == 0) rest = path.substr(18);
    else return false;
    if (rest == leaf) return true;
    if (rest.rfind("task/", 0) == 0) {
        auto slash = rest.find('/', 5);
        return slash != std::string::npos && rest.substr(slash + 1) == leaf;
    }
    return false;
}

// The old stat calls (106-108) fill the 64-byte struct stat of 32-bit ARM, not struct stat64:
// 32-bit device, inode, size, block count and times, 16-bit mode, link count and ids.
struct OldStatArm {
    std::uint32_t st_dev, st_ino;
    std::uint16_t st_mode, st_nlink, st_uid, st_gid;
    std::uint32_t st_rdev, st_size, st_blksize, st_blocks;
    std::uint32_t atime_s, atime_ns, mtime_s, mtime_ns, ctime_s, ctime_ns;
    std::uint32_t unused[2];
};
static_assert(sizeof(OldStatArm) == 64, "struct stat on ARM is 64 bytes");

// 0 or -EOVERFLOW, as the kernel answers when a value does not fit the old structure.
int put_old_stat(Process& p, gaddr dst, const struct stat& st) {
    if (st.st_ino > 0xffffffffull || st.st_size > 0x7fffffffll) return -EOVERFLOW;
    // Ids that do not fit 16 bits read as the overflow id, 65534, as the kernel writes them.
    auto id16 = [](unsigned id) { return static_cast<std::uint16_t>(id > 0xffff ? 65534 : id); };
    OldStatArm a{};
    a.st_dev = static_cast<std::uint32_t>(st.st_dev);
    a.st_ino = static_cast<std::uint32_t>(st.st_ino);
    a.st_mode = static_cast<std::uint16_t>(st.st_mode);
    a.st_nlink = static_cast<std::uint16_t>(std::min<std::uint64_t>(st.st_nlink, 0xffff));
    a.st_uid = id16(st.st_uid);
    a.st_gid = id16(st.st_gid);
    a.st_rdev = static_cast<std::uint32_t>(st.st_rdev);
    a.st_size = static_cast<std::uint32_t>(st.st_size);
    a.st_blksize = static_cast<std::uint32_t>(st.st_blksize);
    a.st_blocks = static_cast<std::uint32_t>(st.st_blocks);
    a.atime_s = static_cast<std::uint32_t>(st.st_atim.tv_sec);
    a.atime_ns = static_cast<std::uint32_t>(st.st_atim.tv_nsec);
    a.mtime_s = static_cast<std::uint32_t>(st.st_mtim.tv_sec);
    a.mtime_ns = static_cast<std::uint32_t>(st.st_mtim.tv_nsec);
    a.ctime_s = static_cast<std::uint32_t>(st.st_ctim.tv_sec);
    a.ctime_ns = static_cast<std::uint32_t>(st.st_ctim.tv_nsec);
    std::memcpy(p.mem.host(dst), &a, sizeof a);
    return 0;
}

// struct flock of 32-bit ARM, for F_GETLK, F_SETLK and F_SETLKW: 32-bit offsets (the 64-bit
// commands 12-14 use struct flock64, which has the host's struct flock layout).
struct Flock32 {
    std::int16_t type, whence;
    std::int32_t start, len, pid;
};
static_assert(sizeof(Flock32) == 16);

// ---------------------------------------------------------------------------------------------
// System properties.
//
// The guest's Android 6 C library reads its properties from one file, /dev/__properties__,
// mapped whole: a 128-byte header and a trie of names split at '.', each level a binary tree
// (bionic's prop_area). Android 7 and later keep one such file per SELinux context in a
// directory of that name, which the old library cannot read: every property came back empty,
// the time zone included. The guest gets a file of its own instead: the CPU ABI of a 32-bit ARM
// process, and the host's values for what a 32-bit process of this device would see as well.
class PropArea {
public:
    PropArea() : data_(kBtSize, 0) {}  // the trie's root: no name, no property

    // The first value given for a name stays.
    void add(const std::string& name, const std::string& value) {
        if (name.empty() || value.empty()) return;
        std::uint32_t node = 0;
        for (std::size_t start = 0;;) {
            std::size_t dot = name.find('.', start);
            std::string token = name.substr(start, dot == std::string::npos ? std::string::npos : dot - start);
            if (token.empty() || token.size() > 255) return;
            node = child(node, token);
            if (dot == std::string::npos) break;
            start = dot + 1;
        }
        if (get(node + kBtProp)) return;
        // prop_info: serial (the value's length in the top byte, even: complete), the value in
        // 92 bytes with its terminating zero, then the full name.
        std::string v = value.substr(0, kValueMax - 1);
        std::uint32_t info = alloc(4 + kValueMax + name.size() + 1);
        set(info, static_cast<std::uint32_t>(v.size()) << 24);
        std::memcpy(data_.data() + info + 4, v.data(), v.size());
        std::memcpy(data_.data() + info + 4 + kValueMax, name.data(), name.size());
        set(node + kBtProp, info);
    }

    // The whole file: header, then the trie.
    std::vector<std::uint8_t> file() const {
        std::vector<std::uint8_t> out(128, 0);
        auto put = [&](std::size_t at, std::uint32_t v) { std::memcpy(out.data() + at, &v, 4); };
        put(0, static_cast<std::uint32_t>(data_.size()));  // bytes used
        put(8, 0x504f5250);                                  // magic
        put(12, 0xfc6ed0ab);                                 // version
        out.insert(out.end(), data_.begin(), data_.end());
        return out;
    }

private:
    // prop_bt: name length, three bytes, then offsets (from the start of the trie, 0 for none)
    // of the property, the left and right siblings and the first child; the name follows.
    static constexpr std::uint32_t kBtProp = 4, kBtLeft = 8, kBtRight = 12, kBtChildren = 16, kBtSize = 20;
    static constexpr std::size_t kValueMax = 92;  // PROP_VALUE_MAX

    std::uint32_t get(std::uint32_t at) const {
        std::uint32_t v;
        std::memcpy(&v, data_.data() + at, 4);
        return v;
    }
    void set(std::uint32_t at, std::uint32_t v) { std::memcpy(data_.data() + at, &v, 4); }
    std::uint32_t alloc(std::size_t size) {
        auto at = static_cast<std::uint32_t>(data_.size());
        data_.resize(data_.size() + ((size + 3) & ~std::size_t{3}), 0);
        return at;
    }
    // The node for token among parent's children, made if missing. Siblings are ordered as the
    // library searches them: by length first, then by the bytes.
    std::uint32_t child(std::uint32_t parent, const std::string& token) {
        std::uint32_t link = parent + kBtChildren;
        for (;;) {
            std::uint32_t cur = get(link);
            if (!cur) {
                std::uint32_t n = alloc(kBtSize + token.size() + 1);
                data_[n] = static_cast<std::uint8_t>(token.size());
                std::memcpy(data_.data() + n + kBtSize, token.data(), token.size());
                set(link, n);
                return n;
            }
            std::size_t len = data_[cur];
            int c = token.size() < len ? -1 : token.size() > len ? 1
                                                                 : std::strncmp(token.c_str(), reinterpret_cast<const char*>(data_.data() + cur + kBtSize), len);
            if (c == 0) return cur;
            link = cur + (c < 0 ? kBtLeft : kBtRight);
        }
    }

    std::vector<std::uint8_t> data_;
};

#ifndef __ANDROID__
// The host's time zone by its tz database name, for the guest's persist.sys.timezone: TZ when it is set (":Asia/Seoul"
// and a path into a zoneinfo folder name one too, and a POSIX rule such as "KST-9" goes as it is, which the guest's C
// library reads as well), else Debian's /etc/timezone, else the zone /etc/localtime links to. Empty when none says,
// and the guest keeps to GMT.
std::string host_time_zone() {
#ifdef _WIN32
    // Windows has no /etc: the layer asks Windows (src/win/sys.cpp).
    return arm32::posix::host_zone();
#endif
    auto zone_of = [](std::string s) {
        // A leading colon only says "a file", and a path into a zoneinfo folder ends in the zone's name.
        if (!s.empty() && s[0] == ':') s.erase(0, 1);
        std::size_t at = s.rfind("zoneinfo/");
        if (at != std::string::npos) s.erase(0, at + 9);
        // A line from a file ends at its line break; a zone's name has no spaces.
        s.erase(std::find_if(s.begin(), s.end(), [](char c) { return c == '\n' || c == '\r' || c == ' ' || c == '\t'; }), s.end());
        return s;
    };
    if (const char* tz = std::getenv("TZ"); tz && *tz) return zone_of(tz);
    // Debian's file: one line, the zone's name.
    int fd = open("/etc/timezone", O_RDONLY | O_CLOEXEC);
    if (fd >= 0) {
        char line[128];
        ssize_t n = read(fd, line, sizeof line);
        close(fd);
        if (n > 0) {
            std::string zone = zone_of(std::string(line, static_cast<std::size_t>(n)));
            if (!zone.empty()) return zone;
        }
    }
    // systemd's way: /etc/localtime is a link into the zoneinfo folder.
    char link[PATH_MAX];
    ssize_t n = readlink("/etc/localtime", link, sizeof link);
    if (n > 0) return zone_of(std::string(link, static_cast<std::size_t>(n)));
    return "";
}
#endif

// The guest's property file, built on first use: a memfd that stays open, and its identity, so
// that fstat on a guest's copy of it can say what the library checks (owned by root, not
// writable by others). -1 when the host has no memfd_create.
struct Properties {
    int fd = -1;
    dev_t dev = 0;
    ino_t ino = 0;
};
const Properties& properties() {
    static const Properties props = [] {
        PropArea area;
        // A 32-bit ARM process: its own ABI first (the first value of a name stays).
        area.add("ro.product.cpu.abi", "armeabi-v7a");
        area.add("ro.product.cpu.abi2", "armeabi");
        area.add("ro.product.cpu.abilist", "armeabi-v7a,armeabi");
        area.add("ro.product.cpu.abilist32", "armeabi-v7a,armeabi");
        // What the device says about itself, the same for every process.
        static const char* const kHost[] = {
            "ro.build.version.sdk", "ro.build.version.release", "ro.build.version.incremental", "ro.build.version.codename",
            "ro.build.version.security_patch", "ro.build.id", "ro.build.display.id", "ro.build.fingerprint", "ro.build.type",
            "ro.build.tags", "ro.build.date.utc", "ro.product.model", "ro.product.brand", "ro.product.manufacturer",
            "ro.product.name", "ro.product.device", "ro.product.board", "ro.board.platform", "ro.hardware", "ro.boot.hardware",
            "ro.revision", "ro.product.locale", "ro.opengles.version", "ro.sf.lcd_density", "ro.config.low_ram", "ro.kernel.qemu",
            "ro.debuggable", "ro.secure", "persist.sys.timezone", "persist.sys.locale", "dalvik.vm.heapsize",
            "dalvik.vm.heapgrowthlimit", "gsm.sim.operator.iso-country", "gsm.operator.iso-country",
        };
#ifdef __ANDROID__
        for (const char* key : kHost) {
            char value[PROP_VALUE_MAX] = "";
            if (__system_property_get(key, value) > 0) area.add(key, value);
        }
#else
        // A desktop host has no device to ask: an Android 9 phone of no particular make, as the game would see one.
        (void)kHost;
        static const char* const kDesktop[][2] = {
            {"ro.build.version.sdk", "28"}, {"ro.build.version.release", "9"}, {"ro.build.version.codename", "REL"},
            {"ro.build.type", "user"}, {"ro.build.tags", "release-keys"}, {"ro.product.model", "OpenDMTQ"},
            {"ro.product.brand", "OpenDMTQ"}, {"ro.product.manufacturer", "OpenDMTQ"}, {"ro.product.name", "opendmtq"},
            {"ro.product.device", "opendmtq"}, {"ro.hardware", "opendmtq"}, {"ro.opengles.version", "196610"},
            {"ro.sf.lcd_density", "320"}, {"ro.debuggable", "0"}, {"ro.secure", "1"}, {"ro.kernel.qemu", "0"},
            {"dalvik.vm.heapsize", "512m"},
        };
        for (const auto& kv : kDesktop) area.add(kv[0], kv[1]);
        // The host's time zone where a phone keeps its own, which the guest's C library reads when TZ is unset; a name
        // too long for a property's 92 bytes would be cut into another, and stays out.
        if (std::string zone = host_time_zone(); !zone.empty() && zone.size() < 92) area.add("persist.sys.timezone", zone);
#endif
        Properties p;
        std::vector<std::uint8_t> bytes = area.file();
        int fd = static_cast<int>(syscall(__NR_memfd_create, "arm32-properties", 1u /* MFD_CLOEXEC */));
        if (fd < 0) return p;
        std::size_t done = 0;
        while (done < bytes.size()) {
            ssize_t n = write(fd, bytes.data() + done, bytes.size() - done);
            if (n <= 0) break;
            done += static_cast<std::size_t>(n);
        }
        struct stat st {};
        if (done != bytes.size() || fstat(fd, &st) != 0) {
            close(fd);
            return p;
        }
        p.fd = fd;
        p.dev = st.st_dev;
        p.ino = st.st_ino;
        return p;
    }();
    return props;
}

// fstat of the guest's copy of the property file: what the library checks before mapping it.
void property_owner(struct stat& st) {
    const Properties& p = properties();
    if (p.fd >= 0 && st.st_dev == p.dev && st.st_ino == p.ino) {
        st.st_uid = 0;
        st.st_gid = 0;
        st.st_mode = S_IFREG | 0444;
    }
}

// ---------------------------------------------------------------------------------------------
// Threads.

struct CloneStart {
    Process* proc;
    CloneState state;
#ifdef _WIN32
    // The creating thread's name, which a Linux thread inherits from its creator and a Windows thread does not.
    char name[16] = {};
#endif
    // Filled in by the child before the parent's clone returns.
    std::mutex lock;
    std::condition_variable ready;
    int tid = 0;
};

void* clone_main(void* arg) {
    auto* cs = static_cast<CloneStart*>(arg);
    Process& proc = *cs->proc;
    int tid = static_cast<int>(gettid());
#ifdef _WIN32
    if (cs->name[0]) prctl(PR_SET_NAME, cs->name);
#endif
    auto* t = new Thread(proc, tid);
    const CloneState& st = cs->state;
    // Same registers as the parent at its next instruction, but clone returns 0 here.
    t->regs() = st.regs;
    t->regs()[0] = 0;
    t->jit().ExtRegs() = st.ext;
    t->jit().SetCpsr(st.cpsr);
    t->jit().SetFpscr(st.fpscr);
    t->tls = st.tls;
    t->sigmask = st.sigmask;
    if (st.flags & CLONE_CHILD_CLEARTID) t->clear_child_tid = st.ctid;
    if (st.flags & CLONE_CHILD_SETTID) *proc.mem.ptr<std::int32_t>(st.ctid) = tid;
    if (st.flags & CLONE_PARENT_SETTID) *proc.mem.ptr<std::int32_t>(st.ptid) = tid;
    // Visible to signals only now that its state is complete, before the parent's clone returns.
    t->publish();
    {
        // Notified under the lock: once the parent sees tid it returns and frees cs, so cs must
        // not be touched after the lock is let go.
        std::lock_guard<std::mutex> g(cs->lock);
        cs->tid = tid;
        cs->ready.notify_one();
    }
    t->run();
    // CLONE_CHILD_CLEARTID: pthread_join waits for this word to become 0.
    if (t->clear_child_tid) {
        auto* word = proc.mem.ptr<std::int32_t>(t->clear_child_tid);
        __atomic_store_n(word, 0, __ATOMIC_SEQ_CST);
        syscall(__NR_futex, word, FUTEX_WAKE, INT_MAX, nullptr, nullptr, 0);
    }
    delete t;
    return nullptr;
}

std::uint32_t do_clone(Thread& t) {
    auto& r = t.regs();
    // ARM argument order: flags, child stack, parent tid pointer, tls, child tid pointer.
    std::uint32_t flags = r[0];
    if (!(flags & CLONE_VM) || !(flags & CLONE_THREAD)) {
        log("arm32: clone without CLONE_VM|CLONE_THREAD (flags %#x) is not supported", flags);
        return err(ENOSYS);
    }
    auto cs = std::make_unique<CloneStart>();
    cs->proc = &t.proc;
#ifdef _WIN32
    prctl(PR_GET_NAME, cs->name);
#endif
    CloneState& st = cs->state;
    st.regs = r;
    if (r[1]) st.regs[13] = r[1];
    st.ext = t.jit().ExtRegs();
    st.cpsr = t.jit().Cpsr();
    st.fpscr = t.jit().Fpscr();
    st.tls = (flags & CLONE_SETTLS) ? r[3] : t.tls;
    st.sigmask = t.sigmask;
    st.flags = flags;
    st.ptid = r[2];
    st.ctid = r[4];
    // The embedding program may run this thread on a host thread it already has.
    if (t.proc.clone_hook) {
        if (int tid = t.proc.clone_hook(t.proc, st); tid > 0) {
            if (flags & CLONE_PARENT_SETTID) *t.proc.mem.ptr<std::int32_t>(st.ptid) = tid;
            if (flags & CLONE_CHILD_SETTID) *t.proc.mem.ptr<std::int32_t>(st.ctid) = tid;
            return static_cast<std::uint32_t>(tid);
        }
    }
    // A roomy host stack: translated code and the runtime's own frames run on it.
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, 4 * 1024 * 1024);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    pthread_t h;
    int e = pthread_create(&h, &attr, clone_main, cs.get());
    pthread_attr_destroy(&attr);
    if (e != 0) return err(e);
    std::unique_lock<std::mutex> g(cs->lock);
    cs->ready.wait(g, [&] { return cs->tid != 0; });
    return static_cast<std::uint32_t>(cs->tid);
}

}  // namespace

// ---------------------------------------------------------------------------------------------

#ifdef _WIN32
// Windows has no signals to interrupt a call with: the layer's waits wait on the thread's own event as well, which
// posix::interrupt sets (src/win), and arm32_isys checks the gate before it waits.
void install_interrupt_handler() {}
#else
void install_interrupt_handler() {
    struct sigaction sa {};
    sa.sa_sigaction = [](int, siginfo_t*, void* context) {
        // Landed between arm32_isys's check and its system call instruction: skip the call when a
        // guest signal is ready for the thread, as the signal would have cut it short anyway. An
        // interrupt can come late, after its signal was delivered some other way, or for a signal
        // the thread blocks: then the call goes ahead, since nothing would have stopped it.
        auto* uc = static_cast<ucontext_t*>(context);
#if defined(__aarch64__)
        auto& pc = uc->uc_mcontext.pc;
#else
        auto& pc = uc->uc_mcontext.gregs[REG_RIP];
#endif
        auto at = static_cast<std::uintptr_t>(pc);
        if (at < reinterpret_cast<std::uintptr_t>(arm32_isys_begin) || at >= reinterpret_cast<std::uintptr_t>(arm32_isys_end)) return;
        // The gate of the call in progress. On arm64 arm32_isys keeps it in x6 (its seventh
        // argument) all along; the kernel keeps every register but x0 when it rewinds a call to its
        // svc for a restart. On x86-64 it is the seventh argument on the stack, just above the
        // return address: the stub never moves the stack pointer, while registers would not do
        // (the syscall instruction overwrites rcx and r11, and a rewound call comes back with them).
#if defined(__aarch64__)
        const auto* gate = reinterpret_cast<const IsysGate*>(uc->uc_mcontext.regs[6]);
#else
        const auto* gate = *reinterpret_cast<const IsysGate* const*>(static_cast<std::uintptr_t>(uc->uc_mcontext.gregs[REG_RSP]) + 8);
#endif
        // Set before the interrupt was sent, so a signal it was sent for is visible here.
        if (!(gate->pending->load() & ~gate->blocked)) return;
        pc = static_cast<std::remove_reference_t<decltype(pc)>>(reinterpret_cast<std::uintptr_t>(arm32_isys_cancel));
    };
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = SA_SIGINFO;  // no SA_RESTART: a blocked system call must return EINTR
    sigaction(kInterruptSignal, &sa, nullptr);
}
#endif

int Process::send_signal(int tid, int sig) {
    if (sig < 1 || sig > 64) return -EINVAL;
    Thread* target = nullptr;
    {
        std::lock_guard<std::mutex> g(threads_lock);
        if (tid) {
            auto it = threads.find(tid);
            if (it == threads.end()) return -ESRCH;
            target = it->second;
        } else {
            // Process-directed: the first thread not blocking it, else the first thread.
            for (auto& [id, t] : threads) {
                if (!(t->sigmask & (1ull << (sig - 1)))) {
                    target = t;
                    break;
                }
            }
            if (!target && !threads.empty()) target = threads.begin()->second;
            if (!target) return -ESRCH;
        }
        // A signal whose action is to ignore it is discarded here, as the kernel does: queued, it
        // would end rt_sigsuspend and cut blocked calls short, which an ignored signal never does.
        // One the target blocks is kept: its action may change before it is unblocked.
        {
            std::lock_guard<std::mutex> s(sig_lock);
            const SigAction& act = sigactions[sig];
            bool ignored = act.handler == 1 /* SIG_IGN */ ||
                           (act.handler == 0 /* SIG_DFL */ && (sig == SIGCHLD || sig == SIGURG || sig == SIGWINCH || sig == SIGCONT));
            if (ignored && !(target->sigmask & (1ull << (sig - 1)))) return 0;
        }
        target->pending.fetch_or(1ull << (sig - 1));
        if (g_stats) note_signal(sig);
        if (g_trace) log("trace: %d sends %d to %d (mask %#llx)", static_cast<int>(gettid()), sig, target->tid, static_cast<unsigned long long>(target->sigmask));
        // Running translated code: stop at the next instruction boundary.
        target->halt();
        // Waiting in rt_sigsuspend.
        {
            std::lock_guard<std::mutex> w(target->wait_lock);
        }
        target->wait_cv.notify_all();
        if (target->tid != static_cast<int>(gettid())) {
            // Blocked in a host system call: interrupt it. Not in guest code at all (in Java
            // between native calls): a helper runs the handler.
#ifdef _WIN32
            if (target->attached()) arm32::posix::interrupt(target->tid);
#else
            if (target->attached()) pthread_kill(target->host_thread, kInterruptSignal);
#endif
            else target->wake_detached();
        }
    }
    return 0;
}

// Where the guest's C library looks for the time zones: where Android 6.0 kept them ($ANDROID_ROOT/usr/share/zoneinfo,
// and ANDROID_ROOT is /system).
constexpr const char* kGuestTzdata = "/system/usr/share/zoneinfo/tzdata";

// Where this host keeps them: on a phone the tzdata module's file (Android 11 on), the runtime module's (10), or the
// system's, where the guest finds it as it is (before 10); on a desktop host, the copy the build put in the sysroot
// (arm32/tools/tzdata.py).
static std::string tzdata_file(const Process& p) {
#ifdef __ANDROID__
    (void)p;
    // Looked for once: a module's file stays where it is while the phone runs.
    static const std::string file = [] {
        for (const char* f : {"/apex/com.android.tzdata/etc/tz/tzdata", "/apex/com.android.runtime/etc/tz/tzdata"})
            if (access(f, R_OK) == 0) return std::string(f);
        return std::string(kGuestTzdata);
    }();
    return file;
#else
    return p.sysroot + "/usr/share/zoneinfo/tzdata";
#endif
}

std::string Process::host_path(const std::string& given) const {
    // Repeated slashes are one, as the kernel reads them, so that every mapping below sees each spelling of a name: the
    // guest's C library asks for the time zones as "/system//usr/share/zoneinfo/tzdata" ($ANDROID_ROOT, "/", then its
    // own "/usr/...").
    std::string path;
    if (given.find("//") == std::string::npos) {
        path = given;
    } else {
        path.reserve(given.size());
        for (char c : given)
            if (c != '/' || path.empty() || path.back() != '/') path += c;
    }
    // The time zones from where this host keeps them, before any other mapping: every host has them somewhere else.
    if (path == kGuestTzdata) return tzdata_file(*this);
    if (path_hook) return path_hook(path);
    // The guest's own system libraries and linker live in the sysroot, not in the host /system.
    if (path.rfind("/system/lib/", 0) == 0) return sysroot + "/lib/" + path.substr(12);
    if (path == "/system/bin/linker") return sysroot + "/bin/linker";
    // There are no vendor libraries for the guest.
    if (path.rfind("/vendor/lib/", 0) == 0) return sysroot + "/vendor-lib/" + path.substr(12);
    return path;
}

// The address a guest Unix socket binds or connects to, with its file name where host_path puts the guest's files (the
// desktop player's log socket stands in for the phone's logd this way); other addresses, abstract names and names
// host_path leaves alone come back as they are. `len` is the address length, changed with the name.
const sockaddr* unix_address(const Process& p, const sockaddr* a, socklen_t& len, sockaddr_un& moved) {
    if (!a || len <= offsetof(sockaddr_un, sun_path) || a->sa_family != AF_UNIX) return a;
    const auto* u = reinterpret_cast<const sockaddr_un*>(a);
    // An abstract name (a zero first byte) is no file.
    if (!u->sun_path[0]) return a;
    std::string name(u->sun_path, strnlen(u->sun_path, std::min<std::size_t>(len - offsetof(sockaddr_un, sun_path), sizeof u->sun_path)));
    std::string host = p.host_path(name);
    if (host == name || host.size() >= sizeof moved.sun_path) return a;
    std::memset(&moved, 0, sizeof moved);
    moved.sun_family = AF_UNIX;
    std::memcpy(moved.sun_path, host.c_str(), host.size() + 1);
    len = static_cast<socklen_t>(offsetof(sockaddr_un, sun_path) + host.size() + 1);
    return reinterpret_cast<const sockaddr*>(&moved);
}

// With stats on: each place the guest connects to, once, with the outcome (`error` an errno, 0
// for success); a call made again every frame shows here once, and in the system call counts.
void note_connect(const sockaddr* a, std::uint32_t len, int error) {
    if (!a || len < sizeof(sa_family_t)) return;
    char where[128] = "";
    if (a->sa_family == AF_UNIX) {
        const auto* u = reinterpret_cast<const sockaddr_un*>(a);
        // An abstract name starts with a zero byte.
        std::snprintf(where, sizeof where, "unix %s%.100s", u->sun_path[0] ? "" : "@", u->sun_path[0] ? u->sun_path : u->sun_path + 1);
    } else if (a->sa_family == AF_INET && len >= sizeof(sockaddr_in)) {
        const auto* in = reinterpret_cast<const sockaddr_in*>(a);
        const auto* b = reinterpret_cast<const unsigned char*>(&in->sin_addr);
        std::snprintf(where, sizeof where, "inet %u.%u.%u.%u:%u", b[0], b[1], b[2], b[3], ntohs(in->sin_port));
    } else {
        std::snprintf(where, sizeof where, "family %d", a->sa_family);
    }
    static std::mutex lock;
    static std::set<std::string> seen;
    std::lock_guard<std::mutex> guard(lock);
    if (seen.insert(where).second) log("stats: connect %s: %s", where, error ? std::strerror(error) : "ok");
}

std::uint32_t do_syscall(Thread& t, std::uint32_t nr) {
    Process& p = t.proc;
    Memory& m = p.mem;
    auto& r = t.regs();
    std::uint32_t a0 = r[0], a1 = r[1], a2 = r[2], a3 = r[3], a4 = r[4], a5 = r[5];
    auto H = [&](gaddr g) -> void* { return g ? m.host(g) : nullptr; };
    auto P = [&](gaddr g) -> std::intptr_t { return reinterpret_cast<std::intptr_t>(H(g)); };
    auto path_arg = [&](gaddr g, std::string& host) -> bool {
        std::string s;
        if (!guest_str(p, g, s)) return false;
        host = p.host_path(s);
        return true;
    };
    auto dirfd = [](std::uint32_t fd) { return static_cast<int>(fd); };
    // A guest structure the runtime itself reads or writes (the conversions below): NULL or
    // unmapped memory is EFAULT, as the kernel would answer, rather than a fault in the host.
    auto mem_ok = [&](gaddr g, std::uint32_t n) { return g != 0 && m.readable(g, n); };

    switch (nr) {
    // ----------------------------------------------------------------- process and thread exit
    case 1:  // exit: this thread only
        t.exited = true;
        t.halt();
        return 0;
    case 248:  // exit_group
        p.exit_code = static_cast<int>(a0 & 0xff);
        p.exiting = true;
        exit_now(static_cast<int>(a0 & 0xff));

    // ----------------------------------------------------------------- files
    case 3:  // read
        return res(blocking(t, kRestart, __NR_read, sint(a0), P(a1), a2));
    case 4:  // write
        return res(blocking(t, kRestart, __NR_write, sint(a0), P(a1), a2));
    case 5:  // open
    case 322: {  // openat
        int dfd = nr == 5 ? AT_FDCWD : dirfd(a0);
        gaddr path = nr == 5 ? a0 : a1;
        std::uint32_t flags = nr == 5 ? a1 : a2;
        std::uint32_t mode = nr == 5 ? a2 : a3;
        std::string guest;
        if (!guest_str(p, path, guest)) return err(EFAULT);
        int hflags = open_flags_to_host(flags);
        // Generated files describing the guest rather than the host.
        if (is_self_proc(p, guest, "maps") || is_self_proc(p, guest, "smaps")) return res(text_fd(m.maps_text(), hflags));
        if (guest == "/proc/cpuinfo") return res(text_fd(cpuinfo_text(p), hflags));
        // With fewer CPUs than the host's, the lists the C library counts them by say so too.
        if (p.max_cpus > 0 && (guest == "/sys/devices/system/cpu/possible" || guest == "/sys/devices/system/cpu/present" || guest == "/sys/devices/system/cpu/online")) {
            long cpus = guest_cpus(p);
            return res(text_fd(cpus > 1 ? "0-" + std::to_string(cpus - 1) + "\n" : "0\n", hflags));
        }
        if (is_self_proc(p, guest, "exe")) return res(openat(AT_FDCWD, p.host_path(p.exe_path).c_str(), hflags, mode));
        // The guest's own system properties (a copy of the file shares its memfd's identity).
        if (guest == "/dev/__properties__" && properties().fd >= 0) {
            return res(fcntl(properties().fd, (hflags & O_CLOEXEC) ? F_DUPFD_CLOEXEC : F_DUPFD, 0));
        }
        return res(openat(dfd, p.host_path(guest).c_str(), hflags, mode));
    }
    case 6:  // close
        return res(close(static_cast<int>(a0)));
    case 19:  // lseek
        return res(lseek(static_cast<int>(a0), static_cast<std::int32_t>(a1), static_cast<int>(a2)));
    case 140: {  // _llseek(fd, offset_high, offset_low, result*, whence)
        if (!mem_ok(a3, 8)) return err(EFAULT);
        off_t off = static_cast<off_t>((std::uint64_t{a1} << 32) | a2);
        off_t r2 = lseek(static_cast<int>(a0), off, static_cast<int>(a4));
        if (r2 < 0) return err(errno);
        std::int64_t v = r2;
        std::memcpy(m.host(a3), &v, sizeof v);
        return 0;
    }
    case 180:  // pread64(fd, buf, count, pad, off_lo, off_hi)
        return res(blocking(t, kRestart, __NR_pread64, sint(a0), P(a1), a2, static_cast<std::intptr_t>((std::uint64_t{a5} << 32) | a4)));
    case 181:  // pwrite64
        return res(blocking(t, kRestart, __NR_pwrite64, sint(a0), P(a1), a2, static_cast<std::intptr_t>((std::uint64_t{a5} << 32) | a4)));
    case 145:    // readv
    case 146: {  // writev
        std::vector<iovec> v;
        if (!get_iovecs(p, a1, a2, v)) return err(EFAULT);
        return res(blocking(t, kRestart, nr == 145 ? __NR_readv : __NR_writev, sint(a0), reinterpret_cast<std::intptr_t>(v.data()), static_cast<long>(v.size())));
    }
    case 106:    // stat: the old 64-byte struct stat
    case 107:    // lstat
    case 195:    // stat64: struct stat64
    case 196: {  // lstat64
        std::string hp;
        if (!path_arg(a0, hp)) return err(EFAULT);
        struct stat st {};
        int rc = (nr == 107 || nr == 196) ? lstat(hp.c_str(), &st) : stat(hp.c_str(), &st);
        if (rc < 0) return err(errno);
        if (nr == 106 || nr == 107) return mem_ok(a1, sizeof(OldStatArm)) ? err(-put_old_stat(p, a1, st)) : err(EFAULT);
        if (!mem_ok(a1, sizeof(Stat64Arm))) return err(EFAULT);
        put_stat(p, a1, st);
        return 0;
    }
    case 108:    // fstat: the old 64-byte struct stat
    case 197: {  // fstat64
        struct stat st {};
        if (fstat(static_cast<int>(a0), &st) < 0) return err(errno);
        property_owner(st);
        if (nr == 108) return mem_ok(a1, sizeof(OldStatArm)) ? err(-put_old_stat(p, a1, st)) : err(EFAULT);
        if (!mem_ok(a1, sizeof(Stat64Arm))) return err(EFAULT);
        put_stat(p, a1, st);
        return 0;
    }
    case 327: {  // fstatat64
        std::string hp;
        if (!path_arg(a1, hp)) return err(EFAULT);
        struct stat st {};
        if (fstatat(dirfd(a0), hp.c_str(), &st, static_cast<int>(a3)) < 0) return err(errno);
        property_owner(st);
        if (!mem_ok(a2, sizeof(Stat64Arm))) return err(EFAULT);
        put_stat(p, a2, st);
        return 0;
    }
    case 266: {  // statfs64(path, size, buf)
        std::string hp;
        if (!path_arg(a0, hp)) return err(EFAULT);
        struct statfs s {};
        if (statfs(hp.c_str(), &s) < 0) return err(errno);
        if (!mem_ok(a2, sizeof(Statfs64Arm))) return err(EFAULT);
        put_statfs(p, a2, s);
        return 0;
    }
    case 267: {  // fstatfs64(fd, size, buf)
        struct statfs s {};
        if (fstatfs(static_cast<int>(a0), &s) < 0) return err(errno);
        if (!mem_ok(a2, sizeof(Statfs64Arm))) return err(EFAULT);
        put_statfs(p, a2, s);
        return 0;
    }
    case 33:     // access
    case 334: {  // faccessat
        std::string hp;
        if (!path_arg(nr == 33 ? a0 : a1, hp)) return err(EFAULT);
        return nr == 33 ? res(access(hp.c_str(), static_cast<int>(a1)))
                        : res(faccessat(dirfd(a0), hp.c_str(), static_cast<int>(a2), 0));
    }
    case 85:     // readlink
    case 332: {  // readlinkat
        gaddr path = nr == 85 ? a0 : a1;
        gaddr buf = nr == 85 ? a1 : a2;
        std::uint32_t size = nr == 85 ? a2 : a3;
        std::string guest;
        if (!guest_str(p, path, guest)) return err(EFAULT);
        std::string target;
        if (is_self_proc(p, guest, "exe")) {
            target = p.exe_path;
        } else {
            char tmp[PATH_MAX];
            ssize_t n = nr == 85 ? readlink(p.host_path(guest).c_str(), tmp, sizeof tmp)
                                 : readlinkat(dirfd(a0), p.host_path(guest).c_str(), tmp, sizeof tmp);
            if (n < 0) return err(errno);
            target.assign(tmp, static_cast<std::size_t>(n));
            // A sysroot file reads as its /system path, as the guest named it.
            std::string lib = p.sysroot + "/lib/";
            if (target.rfind(lib, 0) == 0) target = "/system/lib/" + target.substr(lib.size());
            target = p.guest_name(target);
        }
        std::uint32_t n = std::min<std::uint32_t>(size, static_cast<std::uint32_t>(target.size()));
        if (n && !mem_ok(buf, n)) return err(EFAULT);
        std::memcpy(m.host(buf), target.data(), n);
        return n;
    }
    case 10:     // unlink
    case 328: {  // unlinkat
        std::string hp;
        if (!path_arg(nr == 10 ? a0 : a1, hp)) return err(EFAULT);
        return nr == 10 ? res(unlink(hp.c_str())) : res(unlinkat(dirfd(a0), hp.c_str(), static_cast<int>(a2)));
    }
    case 39:     // mkdir
    case 323: {  // mkdirat
        std::string hp;
        if (!path_arg(nr == 39 ? a0 : a1, hp)) return err(EFAULT);
        return nr == 39 ? res(mkdir(hp.c_str(), a1)) : res(mkdirat(dirfd(a0), hp.c_str(), a2));
    }
    case 40: {  // rmdir
        std::string hp;
        if (!path_arg(a0, hp)) return err(EFAULT);
        return res(rmdir(hp.c_str()));
    }
    case 38:     // rename
    case 329: {  // renameat
        std::string from, to;
        if (!path_arg(nr == 38 ? a0 : a1, from) || !path_arg(nr == 38 ? a1 : a3, to)) return err(EFAULT);
        return nr == 38 ? res(rename(from.c_str(), to.c_str())) : res(renameat(dirfd(a0), from.c_str(), dirfd(a2), to.c_str()));
    }
    case 15:     // chmod
    case 333: {  // fchmodat
        std::string hp;
        if (!path_arg(nr == 15 ? a0 : a1, hp)) return err(EFAULT);
        return nr == 15 ? res(chmod(hp.c_str(), a1)) : res(fchmodat(dirfd(a0), hp.c_str(), a2, 0));
    }
    case 94:  // fchmod
        return res(fchmod(static_cast<int>(a0), a1));
    case 92:     // truncate
    case 193: {  // truncate64(path, pad, lo, hi)
        std::string hp;
        if (!path_arg(a0, hp)) return err(EFAULT);
        off_t len = nr == 92 ? static_cast<std::int32_t>(a1) : static_cast<off_t>((std::uint64_t{a3} << 32) | a2);
        return res(truncate(hp.c_str(), len));
    }
    case 93:  // ftruncate
        return res(ftruncate(static_cast<int>(a0), static_cast<std::int32_t>(a1)));
    case 194:  // ftruncate64(fd, pad, lo, hi)
        return res(ftruncate(static_cast<int>(a0), static_cast<off_t>((std::uint64_t{a3} << 32) | a2)));
    case 118:  // fsync
        return res(fsync(static_cast<int>(a0)));
    case 148:  // fdatasync
        return res(fdatasync(static_cast<int>(a0)));
    case 217:  // getdents64: same record layout on every Linux architecture
        return res(syscall(__NR_getdents64, static_cast<int>(a0), H(a1), a2));
    case 183: {  // getcwd: the kernel's call, which returns the length including the NUL (the C
                 // library's getcwd would allocate a buffer of its own for NULL)
        // The host's current folder by the guest's name for it (name_hook: the desktop player's folders by their guest
        // names, on Windows the guest's root as "/"), so that a name the guest makes from it leads back there.
        char host[PATH_MAX];
        if (syscall(__NR_getcwd, host, sizeof host) < 0) return err(errno);
        const std::string name = p.guest_name(host);
        // As the kernel answers: a buffer too small is ERANGE, one the guest has no memory at is EFAULT.
        if (name.size() + 1 > a1) return err(ERANGE);
        if (!mem_ok(a0, static_cast<std::uint32_t>(name.size() + 1))) return err(EFAULT);
        std::memcpy(m.host(a0), name.c_str(), name.size() + 1);
        return static_cast<std::uint32_t>(name.size() + 1);
    }
    case 12: {  // chdir
        std::string hp;
        if (!path_arg(a0, hp)) return err(EFAULT);
        return res(chdir(hp.c_str()));
    }
    case 133:  // fchdir
        return res(fchdir(static_cast<int>(a0)));
    case 60:  // umask
        return umask(a0);
    case 348: {  // utimensat(dirfd, path, times[2], flags)
        std::string hp;
        if (a1 && !path_arg(a1, hp)) return err(EFAULT);
        timespec ts[2];
        timespec* tp = nullptr;
        if (a2) {
            if (!mem_ok(a2, 2 * sizeof(Timespec32))) return err(EFAULT);
            auto* g = m.ptr<Timespec32>(a2);
            ts[0] = to_host(g[0]);
            ts[1] = to_host(g[1]);
            tp = ts;
        }
        return res(utimensat(dirfd(a0), a1 ? hp.c_str() : nullptr, tp, static_cast<int>(a3)));
    }
    case 41:  // dup
        return res(dup(static_cast<int>(a0)));
    case 63:  // dup2
        return res(dup2(static_cast<int>(a0), static_cast<int>(a1)));
    case 358:  // dup3
        return res(dup3(static_cast<int>(a0), static_cast<int>(a1), open_flags_to_host(a2)));
    case 42:     // pipe
    case 359: {  // pipe2
        int fds[2];
        if (!mem_ok(a0, sizeof fds)) return err(EFAULT);
        if (pipe2(fds, nr == 42 ? 0 : open_flags_to_host(a1)) < 0) return err(errno);
        std::memcpy(m.host(a0), fds, sizeof fds);
        return 0;
    }
    case 55:     // fcntl
    case 221: {  // fcntl64
        int fd = static_cast<int>(a0);
        switch (a1) {
        case F_GETFL: {
            int f = fcntl(fd, F_GETFL);
            return f < 0 ? err(errno) : open_flags_to_arm(f);
        }
        case F_SETFL:
            return res(fcntl(fd, F_SETFL, open_flags_to_host(a2)));
        case 12:    // F_GETLK64
        case 13:    // F_SETLK64
        case 14: {  // F_SETLKW64: struct flock64 has the host's struct flock layout
            if (!mem_ok(a2, sizeof(struct flock))) return err(EFAULT);
            int cmd = a1 == 12 ? F_GETLK : a1 == 13 ? F_SETLK : F_SETLKW;
            if (cmd == F_SETLKW) return res(blocking(t, kRestart, __NR_fcntl, fd, cmd, P(a2)));
            return res(fcntl(fd, cmd, H(a2)));
        }
        case F_GETLK:
        case F_SETLK:
        case F_SETLKW: {  // the 32-bit C library's struct flock: 32-bit offsets
            if (!mem_ok(a2, sizeof(Flock32))) return err(EFAULT);
            Flock32 g;
            std::memcpy(&g, m.host(a2), sizeof g);
            struct flock h {};
            h.l_type = g.type;
            h.l_whence = g.whence;
            h.l_start = g.start;
            h.l_len = g.len;
            h.l_pid = g.pid;
            long rc = a1 == F_SETLKW ? blocking(t, kRestart, __NR_fcntl, fd, F_SETLKW, reinterpret_cast<std::intptr_t>(&h))
                                     : fcntl(fd, static_cast<int>(a1), &h);
            if (rc < 0) return err(errno);
            if (a1 == F_GETLK) {
                // A conflicting lock past what 32 bits hold cannot be described.
                if (h.l_start > 0x7fffffff || h.l_len > 0x7fffffff) return err(EOVERFLOW);
                g.type = h.l_type;
                g.whence = h.l_whence;
                g.start = static_cast<std::int32_t>(h.l_start);
                g.len = static_cast<std::int32_t>(h.l_len);
                g.pid = h.l_pid;
                std::memcpy(m.host(a2), &g, sizeof g);
            }
            return 0;
        }
        case 15:    // F_SETOWN_EX
        case 16: {  // F_GETOWN_EX: struct f_owner_ex { int type; pid_t pid; }, the same everywhere
            if (!mem_ok(a2, 8)) return err(EFAULT);
            return res(fcntl(fd, static_cast<int>(a1), H(a2)));
        }
        case 17:  // F_GETOWNER_UIDS: two uid_t
            if (!mem_ok(a2, 8)) return err(EFAULT);
            return res(fcntl(fd, 17, H(a2)));
        case 36:    // F_OFD_GETLK
        case 37:    // F_OFD_SETLK
        case 38: {  // F_OFD_SETLKW: with fcntl64 the 64-bit struct flock64, the host's layout
            if (nr == 55) return err(EINVAL);  // the plain fcntl refuses them on 32-bit kernels too
            if (!mem_ok(a2, sizeof(struct flock))) return err(EFAULT);
            if (a1 == 38) return res(blocking(t, kRestart, __NR_fcntl, fd, 38, P(a2)));
            return res(fcntl(fd, static_cast<int>(a1), H(a2)));
        }
        case 1035:    // F_GET_RW_HINT
        case 1036:    // F_SET_RW_HINT
        case 1037:    // F_GET_FILE_RW_HINT
        case 1038: {  // F_SET_FILE_RW_HINT: a pointer to a 64-bit hint
            if (!mem_ok(a2, 8)) return err(EFAULT);
            return res(fcntl(fd, static_cast<int>(a1), H(a2)));
        }
        case F_DUPFD:
        case F_GETFD:
        case F_SETFD:
        case F_SETOWN:
        case F_GETOWN:
        case F_SETSIG:
        case F_GETSIG:
        case F_SETLEASE:
        case F_GETLEASE:
        case F_NOTIFY:
        case F_DUPFD_CLOEXEC:
        case 1031:  // F_SETPIPE_SZ
        case 1032:  // F_GETPIPE_SZ
        case 1033:  // F_ADD_SEALS
        case 1034:  // F_GET_SEALS
            // Plain ints, sign kept (F_SETOWN takes a negative process group).
            return res(fcntl(fd, static_cast<int>(a1), sint(a2)));
        default:
            // Unknown here: its argument might be a pointer the host must not take as is.
            log("arm32: unhandled fcntl %u on fd %d", a1, fd);
            return err(EINVAL);
        }
    }
    case 54: {  // ioctl
        int fd = static_cast<int>(a0);
        switch (a1) {
        case TCGETS:
        case TCSETS:
        case TCSETSW:
        case TCSETSF:
        case TIOCGWINSZ:
        case TIOCSWINSZ:
        case FIONREAD:
        case FIONBIO:
            // Same structure layouts on every architecture.
            return res(ioctl(fd, a1, H(a2)));
        case FIOCLEX:
        case FIONCLEX:
            return res(ioctl(fd, a1));
        default:
            log("arm32: unhandled ioctl %#x on fd %d", a1, fd);
            return err(ENOTTY);
        }
    }

    // ----------------------------------------------------------------- memory
    case 192: {  // mmap2(addr, length, prot, flags, fd, pgoffset)
        int flags = static_cast<int>(a3);
        bool fixed = flags & (MAP_FIXED | 0x100000 /* MAP_FIXED_NOREPLACE */);
        if ((flags & 0x100000) && !(flags & MAP_FIXED)) {
            // MAP_FIXED_NOREPLACE fails when anything is mapped in the range.
            for (gaddr g = a0; g < a0 + page_up(a1); g += kPageSize) {
                if (m.readable(g, 1)) return err(EEXIST);
            }
        }
        std::uint64_t offset = std::uint64_t{a5} * 4096;
        std::string name;
        if (!(flags & MAP_ANONYMOUS)) {
            char tmp[PATH_MAX];
            ssize_t n = readlink(("/proc/self/fd/" + std::to_string(static_cast<int>(a4))).c_str(), tmp, sizeof tmp);
            if (n > 0) name.assign(tmp, static_cast<std::size_t>(n));
            std::string lib = p.sysroot + "/lib/";
            if (name.rfind(lib, 0) == 0) name = "/system/lib/" + name.substr(lib.size());
            name = p.guest_name(name);
        }
        // A file mapping is copied in below; with no access at all its host pages could be closed
        // (Memory::host_guards), so it is made readable for the copy and closed after.
        bool file = !(flags & MAP_ANONYMOUS);
        int prot = static_cast<int>(a2);
        std::int64_t at = m.map(a0, a1, file && prot == 0 ? kProtRead : prot, fixed, name, offset);
        if (at < 0) return static_cast<std::uint32_t>(at);
        // File contents are copied in: the host page size may not match the guest's 4 KB.
        if (file) {
            std::uint8_t* dst = m.host(static_cast<gaddr>(at));
            std::size_t want = a1, done = 0;
            while (done < want) {
                ssize_t n = pread(static_cast<int>(a4), dst + done, want - done, static_cast<off_t>(offset + done));
                if (n < 0) {
                    if (errno == EINTR) continue;
                    m.unmap(static_cast<gaddr>(at), a1);
                    return err(errno);
                }
                if (n == 0) break;
                done += static_cast<std::size_t>(n);
            }
            if ((flags & MAP_SHARED) && (a2 & PROT_WRITE)) log("arm32: writable shared file mapping is private here (%s)", name.c_str());
            if (prot == 0) m.protect(static_cast<gaddr>(at), a1, 0);
        }
        return static_cast<std::uint32_t>(at);
    }
    case 91:  // munmap
        return static_cast<std::uint32_t>(m.unmap(a0, a1));
    case 125:  // mprotect
        return static_cast<std::uint32_t>(m.protect(a0, a1, static_cast<int>(a2)));
    case 163: {  // mremap(old, old_len, new_len, flags, new_addr)
        if (a3 & 2 /* MREMAP_FIXED */) return err(EINVAL);
        return static_cast<std::uint32_t>(m.remap(a0, a1, a2, a3 & 1 /* MREMAP_MAYMOVE */));
    }
    case 220:  // madvise: MADV_DONTNEED frees anonymous memory (it reads as zero after), the rest
               // are hints
        return a2 == MADV_DONTNEED ? static_cast<std::uint32_t>(m.discard(a0, a1)) : 0;
    case 144:  // msync
    case 150:  // mlock
    case 151:  // munlock
    case 152:  // mlockall
    case 153:  // munlockall
        return 0;
    case 219: {  // mincore: every mapped page is resident; a range with a hole is ENOMEM
        if (a0 & (kPageSize - 1)) return err(EINVAL);
        std::uint32_t pages = static_cast<std::uint32_t>(page_up(a1) / kPageSize);
        if (!m.mapped(a0, a1)) return err(ENOMEM);
        if (pages && !mem_ok(a2, pages)) return err(EFAULT);
        std::memset(m.host(a2), 1, pages);
        return 0;
    }
    case 45: {  // brk
        if (a0 <= m.brk_end) return m.brk_end;
        gaddr old_top = static_cast<gaddr>(page_up(m.brk_end));
        gaddr new_top = static_cast<gaddr>(page_up(a0));
        for (gaddr g = old_top; g < new_top; g += kPageSize) {
            if (m.readable(g, 1)) return m.brk_end;  // something else lives there
        }
        if (new_top > old_top && m.map(old_top, new_top - old_top, kProtRead | kProtWrite, true, "[heap]") < 0) return m.brk_end;
        m.brk_end = a0;
        return a0;
    }

    // ----------------------------------------------------------------- identity
    case 20:  // getpid
        return static_cast<std::uint32_t>(getpid());
    case 224:  // gettid
        return static_cast<std::uint32_t>(t.tid);
    case 64:  // getppid
        return static_cast<std::uint32_t>(getppid());
    case 24:   // getuid
    case 199:  // getuid32
        return getuid();
    case 47:   // getgid
    case 200:  // getgid32
        return getgid();
    case 49:   // geteuid
    case 201:  // geteuid32
        return geteuid();
    case 50:   // getegid
    case 202:  // getegid32
        return getegid();
    case 205: {  // getgroups32
        if (a0 > 65536) return err(EINVAL);  // NGROUPS_MAX
        if (a0 && !mem_ok(a1, a0 * 4)) return err(EFAULT);
        std::vector<gid_t> g(a0);
        int n = getgroups(static_cast<int>(a0), g.data());
        if (n < 0) return err(errno);
        for (int i = 0; i < n && a0; ++i) m.ptr<std::uint32_t>(a1)[i] = g[static_cast<std::size_t>(i)];
        return static_cast<std::uint32_t>(n);
    }
    case 132:  // getpgid
        return res(getpgid(static_cast<pid_t>(a0)));
    case 147:  // getsid
        return res(getsid(static_cast<pid_t>(a0)));
    case 66:  // setsid
        return res(setsid());
    case 122: {  // uname
        if (!mem_ok(a0, 6 * 65)) return err(EFAULT);
        struct utsname u {};
        uname(&u);
        std::strncpy(u.machine, "armv7l", sizeof u.machine);
        std::memcpy(m.host(a0), &u, 6 * 65);
        return 0;
    }
    case 116: {  // sysinfo: all fields are 32 bits on ARM
        if (!mem_ok(a0, 64)) return err(EFAULT);
        struct sysinfo s {};
        sysinfo(&s);
        std::uint32_t out[16] = {};
        out[0] = static_cast<std::uint32_t>(s.uptime);
        out[1] = static_cast<std::uint32_t>(s.loads[0]);
        out[2] = static_cast<std::uint32_t>(s.loads[1]);
        out[3] = static_cast<std::uint32_t>(s.loads[2]);
        // Memory in units of mem_unit: scale to fit 32 bits.
        std::uint64_t unit = s.mem_unit ? s.mem_unit : 1;
        std::uint64_t total = s.totalram * unit;
        std::uint32_t mem_unit = 1;
        while (total / mem_unit > 0xffffffffull) mem_unit *= 2;
        auto scale = [&](unsigned long v) { return static_cast<std::uint32_t>(v * unit / mem_unit); };
        out[4] = scale(s.totalram);
        out[5] = scale(s.freeram);
        out[6] = scale(s.sharedram);
        out[7] = scale(s.bufferram);
        out[8] = scale(s.totalswap);
        out[9] = scale(s.freeswap);
        out[10] = s.procs;
        out[11] = scale(s.totalhigh);
        out[12] = scale(s.freehigh);
        out[13] = mem_unit;
        std::memcpy(m.host(a0), out, 64);
        return 0;
    }
    case 191: {  // ugetrlimit
        if (!mem_ok(a1, sizeof(Rlimit32))) return err(EFAULT);
        struct rlimit rl {};
        if (getrlimit(static_cast<int>(a0), &rl) < 0) return err(errno);
        Rlimit32 o{rl.rlim_cur > 0xffffffffull ? 0xffffffffu : static_cast<std::uint32_t>(rl.rlim_cur),
                   rl.rlim_max > 0xffffffffull ? 0xffffffffu : static_cast<std::uint32_t>(rl.rlim_max)};
        std::memcpy(m.host(a1), &o, sizeof o);
        return 0;
    }
    case 75: {  // setrlimit
        if (!mem_ok(a1, sizeof(Rlimit32))) return err(EFAULT);
        auto* g = m.ptr<Rlimit32>(a1);
        struct rlimit rl {g->cur == 0xffffffffu ? RLIM_INFINITY : g->cur, g->max == 0xffffffffu ? RLIM_INFINITY : g->max};
        return res(setrlimit(static_cast<int>(a0), &rl));
    }
    case 369:  // prlimit64: struct rlimit64 is the same everywhere
        return res(syscall(__NR_prlimit64, static_cast<pid_t>(a0), static_cast<int>(a1), H(a2), H(a3)));
    case 77: {  // getrusage: two timevals and fourteen longs, all 32-bit
        if (!mem_ok(a1, 18 * 4)) return err(EFAULT);
        struct rusage ru {};
        if (getrusage(static_cast<int>(a0), &ru) < 0) return err(errno);
        std::uint32_t out[18];
        out[0] = static_cast<std::uint32_t>(ru.ru_utime.tv_sec);
        out[1] = static_cast<std::uint32_t>(ru.ru_utime.tv_usec);
        out[2] = static_cast<std::uint32_t>(ru.ru_stime.tv_sec);
        out[3] = static_cast<std::uint32_t>(ru.ru_stime.tv_usec);
        const long* longs = &ru.ru_maxrss;
        for (int i = 0; i < 14; ++i) out[4 + i] = static_cast<std::uint32_t>(longs[i]);
        std::memcpy(m.host(a1), out, sizeof out);
        return 0;
    }
    case 43: {  // times
        struct tms tm {};
        if (a0 && !mem_ok(a0, 16)) return err(EFAULT);
        clock_t c = times(&tm);
        if (a0) {
            std::uint32_t out[4] = {static_cast<std::uint32_t>(tm.tms_utime), static_cast<std::uint32_t>(tm.tms_stime),
                                    static_cast<std::uint32_t>(tm.tms_cutime), static_cast<std::uint32_t>(tm.tms_cstime)};
            std::memcpy(m.host(a0), out, sizeof out);
        }
        return static_cast<std::uint32_t>(c);
    }
    case 172: {  // prctl
        switch (a0) {
        case PR_SET_NAME:
        case PR_GET_NAME:
            return res(prctl(static_cast<int>(a0), H(a1)));
        case 0x53564d41:  // PR_SET_VMA (naming anonymous memory): nothing to name on the host
            return 0;
        case PR_SET_DUMPABLE:
        case PR_GET_DUMPABLE:
        case PR_SET_PDEATHSIG:
        case PR_SET_NO_NEW_PRIVS:
        case PR_GET_NO_NEW_PRIVS:
            return res(prctl(static_cast<int>(a0), a1, a2, a3, a4));
        default:
            log("arm32: unhandled prctl %u", a0);
            return err(EINVAL);
        }
    }
    case 136:  // personality
        return 0;
    case 384:  // getrandom
        return res(syscall(__NR_getrandom, H(a0), a1, a2));
    case 345: {  // getcpu
        if ((a0 && !mem_ok(a0, 4)) || (a1 && !mem_ok(a1, 4))) return err(EFAULT);
        unsigned cpu = 0, node = 0;
        syscall(__NR_getcpu, &cpu, &node, nullptr);
        if (a0) *m.ptr<std::uint32_t>(a0) = cpu;
        if (a1) *m.ptr<std::uint32_t>(a1) = node;
        return 0;
    }

    // ----------------------------------------------------------------- time
    case 263: {  // clock_gettime
        if (!mem_ok(a1, sizeof(Timespec32))) return err(EFAULT);
        timespec ts{};
        if (clock_gettime(static_cast<clockid_t>(a0), &ts) < 0) return err(errno);
        Timespec32 o = to_arm(ts);
        std::memcpy(m.host(a1), &o, sizeof o);
        return 0;
    }
    case 264: {  // clock_getres
        if (a1 && !mem_ok(a1, sizeof(Timespec32))) return err(EFAULT);
        timespec ts{};
        if (clock_getres(static_cast<clockid_t>(a0), &ts) < 0) return err(errno);
        if (a1) {
            Timespec32 o = to_arm(ts);
            std::memcpy(m.host(a1), &o, sizeof o);
        }
        return 0;
    }
    case 78: {  // gettimeofday
        if (a0 && !mem_ok(a0, sizeof(Timeval32))) return err(EFAULT);
        timeval tv{};
        gettimeofday(&tv, nullptr);
        if (a0) {
            Timeval32 o{static_cast<std::int32_t>(tv.tv_sec), static_cast<std::int32_t>(tv.tv_usec)};
            std::memcpy(m.host(a0), &o, sizeof o);
        }
        return 0;
    }
    case 162: {  // nanosleep
        if (!mem_ok(a0, sizeof(Timespec32)) || (a1 && !mem_ok(a1, sizeof(Timespec32)))) return err(EFAULT);
        timespec req = to_host(*m.ptr<Timespec32>(a0)), rem{};
        long rc;
        GuestSleep sleeping;
        for (;;) {
            // A call arm32_isys skipped for a ready signal never ran, and the kernel did not write
            // rem: all of req is left then.
            rem = req;
            rc = blocking(t, kNoRestart, __NR_nanosleep, reinterpret_cast<std::intptr_t>(&req), reinterpret_cast<std::intptr_t>(&rem));
            // A late interrupt meant for no signal: sleep the rest.
            if (!(rc < 0 && errno == EINTR && !t.signal_ready())) break;
            req = rem;
        }
        if (rc < 0 && errno == EINTR && a1) {
            Timespec32 o = to_arm(rem);
            std::memcpy(m.host(a1), &o, sizeof o);
        }
        return rc < 0 ? err(errno) : 0;
    }
    case 265: {  // clock_nanosleep(clock, flags, req, rem): returns the error number directly
        if (!mem_ok(a2, sizeof(Timespec32)) || (a3 && !mem_ok(a3, sizeof(Timespec32)))) return err(EFAULT);
        timespec req = to_host(*m.ptr<Timespec32>(a2)), rem{};
        long rc;
        GuestSleep sleeping;
        for (;;) {
            // As for nanosleep: a skipped call leaves all of req.
            rem = req;
            rc = blocking(t, kNoRestart, __NR_clock_nanosleep, sint(a0), sint(a1), reinterpret_cast<std::intptr_t>(&req), reinterpret_cast<std::intptr_t>(&rem));
            // A late interrupt meant for no signal: sleep the rest (an absolute end stays as it is).
            if (!(rc < 0 && errno == EINTR && !t.signal_ready())) break;
            if (!(a1 & TIMER_ABSTIME)) req = rem;
        }
        // The time left only means something for a relative sleep; the kernel leaves it alone for
        // an absolute one.
        if (rc < 0 && errno == EINTR && a3 && !(a1 & TIMER_ABSTIME)) {
            Timespec32 o = to_arm(rem);
            std::memcpy(m.host(a3), &o, sizeof o);
        }
        return rc < 0 ? err(errno) : 0;
    }

    // ----------------------------------------------------------------- synchronisation, scheduling
    case 240: {  // futex(uaddr, op, val, timeout_or_val2, uaddr2, val3)
        int op = static_cast<int>(a1);
        int cmd = op & FUTEX_CMD_MASK;
        // The operations that may sleep. The others (wakes, requeues, unlocking, trylock) never
        // block.
        bool waits = cmd == FUTEX_WAIT || cmd == FUTEX_WAIT_BITSET || cmd == FUTEX_LOCK_PI || cmd == FUTEX_LOCK_PI2 ||
                     cmd == FUTEX_WAIT_REQUEUE_PI;
        timespec ts{};
        void* arg4 = reinterpret_cast<void*>(static_cast<std::uintptr_t>(a3));
        // Only the waits take a timespec; the requeue operations pass a count there.
        if (waits && a3) {
            ts = to_host(*m.ptr<Timespec32>(a3));
            arg4 = &ts;
        }
        // A wake happens whatever signals are about: the kernel never fails one with EINTR, and the
        // C library ignores what its wakes return (mutex unlock, condition signal, sem_post), so a
        // wake skipped for a ready signal or cancelled by an interrupt would leave its waiter
        // asleep for good. It never blocks, so it needs no interruptible path.
        if (!waits) return res(syscall(__NR_futex, H(a0), op, a2, arg4, H(a4), sint(a5)));
        // A wait may last for good; a signal for the thread still gets it out.
        return res(blocking(t, kNoRestart, __NR_futex, P(a0), op, a2, reinterpret_cast<std::intptr_t>(arg4), P(a4), sint(a5)));
    }
    case 158:  // sched_yield
        return res(sched_yield());
    case 241:  // sched_setaffinity
        return res(syscall(__NR_sched_setaffinity, static_cast<pid_t>(a0), a1, H(a2)));
    case 242: {  // sched_getaffinity
        // The 32-bit C library's cpu_set_t is 4 bytes; the 64-bit kernel wants a length that is a
        // multiple of 8. The mask is asked for in a host buffer of whole longs, and as much of it
        // as the guest's set holds is copied back (the bits are in the same order).
        if (!mem_ok(a2, a1)) return err(EFAULT);
        std::vector<std::uint8_t> mask(std::max<std::size_t>(8, (std::size_t{a1} + 7) & ~std::size_t{7}), 0);
        long n = syscall(__NR_sched_getaffinity, static_cast<pid_t>(a0), mask.size(), mask.data());
        if (n < 0) return err(errno);
        // Only the CPUs the guest is told of.
        if (p.max_cpus > 0) {
            for (std::size_t bit = static_cast<std::size_t>(guest_cpus(p)); bit < mask.size() * 8; ++bit) mask[bit / 8] &= static_cast<std::uint8_t>(~(1u << (bit % 8)));
        }
        std::uint32_t copy = std::min<std::uint32_t>(a1, static_cast<std::uint32_t>(n));
        // Bits beyond the guest's length must be clear, or the guest's set misses CPUs it may use.
        for (std::size_t i = copy; i < static_cast<std::size_t>(n); ++i) {
            if (mask[i]) return err(EINVAL);
        }
        std::memcpy(m.host(a2), mask.data(), copy);
        return copy;
    }
    case 154:  // sched_setparam
        return res(syscall(__NR_sched_setparam, static_cast<pid_t>(a0), H(a1)));
    case 155:  // sched_getparam
        return res(syscall(__NR_sched_getparam, static_cast<pid_t>(a0), H(a1)));
    case 156:  // sched_setscheduler
        return res(syscall(__NR_sched_setscheduler, static_cast<pid_t>(a0), static_cast<int>(a1), H(a2)));
    case 157:  // sched_getscheduler
        return res(syscall(__NR_sched_getscheduler, static_cast<pid_t>(a0)));
    case 159:  // sched_get_priority_max
        return res(sched_get_priority_max(static_cast<int>(a0)));
    case 160:  // sched_get_priority_min
        return res(sched_get_priority_min(static_cast<int>(a0)));
    case 96:  // getpriority: the raw call returns 20 - nice
        return res(syscall(__NR_getpriority, static_cast<int>(a0), static_cast<id_t>(a1)));
    case 97:  // setpriority
        return res(setpriority(static_cast<int>(a0), static_cast<id_t>(a1), static_cast<int>(a2)));
    case 256:  // set_tid_address
        t.clear_child_tid = a0;
        return static_cast<std::uint32_t>(t.tid);
    case 338:  // set_robust_list: the futex list is not walked on thread exit
        return 0;
    case 120:  // clone
        return do_clone(t);
    case 2:    // fork
    case 190:  // vfork
    case 11:   // execve
        log("arm32: fork/exec is not supported (syscall %u)", nr);
        return err(ENOSYS);

    // ----------------------------------------------------------------- signals (bookkeeping only so far)
    case 174: {  // rt_sigaction(sig, act, oact, sigsetsize)
        if (a0 == 0 || a0 > 64) return err(EINVAL);
        std::lock_guard<std::mutex> g(p.sig_lock);
        auto& slot = p.sigactions[a0];
        if (a2) {
            SigactionArm o{slot.handler, slot.flags, slot.restorer, slot.mask};
            std::memcpy(m.host(a2), &o, sizeof o);
        }
        if (a1) {
            SigactionArm n;
            std::memcpy(&n, m.host(a1), sizeof n);
            slot = Process::SigAction{n.handler, n.flags, n.restorer, n.mask};
        }
        return 0;
    }
    case 175: {  // rt_sigprocmask(how, set, oset, sigsetsize)
        std::uint64_t old = t.sigmask;
        if (a1) {
            std::uint64_t s;
            std::memcpy(&s, m.host(a1), sizeof s);
            if (a0 == SIG_BLOCK) t.sigmask |= s;
            else if (a0 == SIG_UNBLOCK) t.sigmask &= ~s;
            else if (a0 == SIG_SETMASK) t.sigmask = s;
            else return err(EINVAL);
        }
        if (a2) std::memcpy(m.host(a2), &old, sizeof old);
        return 0;
    }
    case 186: {  // sigaltstack(ss, old_ss): stack_t is { void* sp; int flags; size_t size; }
        if (a1) {
            std::uint32_t o[3] = {t.altstack_sp, t.altstack_flags ? t.altstack_flags : 2 /* SS_DISABLE */, t.altstack_size};
            std::memcpy(m.host(a1), o, sizeof o);
        }
        if (a0) {
            std::uint32_t n[3];
            std::memcpy(n, m.host(a0), sizeof n);
            t.altstack_sp = n[0];
            t.altstack_flags = n[1];
            t.altstack_size = n[2];
        }
        return 0;
    }
    case 37: {  // kill(pid, sig): only this process can be signalled
        // The guest names itself by the pid its C library took (Process::guest_pid); passed on, that
        // is a host thread id, and the kernel would deliver the signal to the whole host process.
        if (!is_own_pid(p, static_cast<int>(a0)) && a0 != 0) return res(kill(static_cast<pid_t>(a0), static_cast<int>(a1)));
        if (a1 == 0) return 0;
        return static_cast<std::uint32_t>(p.send_signal(0, static_cast<int>(a1)));
    }
    case 238:    // tkill(tid, sig)
    case 268: {  // tgkill(tgid, tid, sig)
        int tid = static_cast<int>(nr == 268 ? a1 : a0);
        int sig = static_cast<int>(nr == 268 ? a2 : a1);
        if (sig == 0) {
            std::lock_guard<std::mutex> g(p.threads_lock);
            return p.threads.count(tid) ? 0 : err(ESRCH);
        }
        return static_cast<std::uint32_t>(p.send_signal(tid, sig));
    }
    case 67: {  // sigaction (old): handler, 32-bit mask, flags, restorer
        if (a0 == 0 || a0 > 64) return err(EINVAL);
        std::lock_guard<std::mutex> g(p.sig_lock);
        auto& slot = p.sigactions[a0];
        if (a2) {
            std::uint32_t o[4] = {slot.handler, static_cast<std::uint32_t>(slot.mask), slot.flags, slot.restorer};
            std::memcpy(m.host(a2), o, sizeof o);
        }
        if (a1) {
            std::uint32_t n[4];
            std::memcpy(n, m.host(a1), sizeof n);
            slot = Process::SigAction{n[0], n[2], n[3], n[1]};
        }
        return 0;
    }
    case 119:  // sigreturn
    case 173:  // rt_sigreturn
        return t.sigreturn();
    case 179: {  // rt_sigsuspend(mask, size): sleep with this mask until a signal is delivered
        std::uint64_t mask;
        std::memcpy(&mask, m.host(a0), sizeof mask);
        t.suspend_saved_mask = t.sigmask;
        t.sigmask = mask;
        if (g_trace) log("trace: %d sigsuspend mask %#llx pending %#llx", t.tid, static_cast<unsigned long long>(mask), static_cast<unsigned long long>(t.pending.load()));
        std::unique_lock<std::mutex> g(t.wait_lock);
        t.wait_cv.wait(g, [&] { return (t.pending.load() & ~t.sigmask) != 0 || p.exiting.load(); });
        return err(EINTR);  // the handler runs on the way out; its return restores the old mask
    }
    case 176: {  // rt_sigpending
        std::uint64_t s = t.pending.load() & t.sigmask;
        std::memcpy(m.host(a0), &s, sizeof s);
        return 0;
    }
    case 177: {  // rt_sigtimedwait(set, info, timeout, size): take a blocked signal from the set
        std::uint64_t set;
        std::memcpy(&set, m.host(a0), sizeof set);
        auto deadline = std::chrono::steady_clock::time_point::max();
        if (a2) {
            Timespec32 ts = *m.ptr<Timespec32>(a2);
            deadline = std::chrono::steady_clock::now() + std::chrono::seconds(ts.tv_sec) + std::chrono::nanoseconds(ts.tv_nsec);
        }
        std::unique_lock<std::mutex> g(t.wait_lock);
        // Ends for a signal of the set, and also for any signal the thread does not block: as on
        // Linux, that one is not left waiting behind the call but cuts it short (EINTR), and its
        // handler runs on the way out. Waiting on, a collector's suspend signal would never be
        // acknowledged.
        bool got = t.wait_cv.wait_until(g, deadline, [&] { return (t.pending.load() & (set | ~t.sigmask)) != 0 || p.exiting.load(); });
        if (!got) return err(EAGAIN);
        std::uint64_t in_set = t.pending.load() & set;
        if (!in_set) return err(EINTR);
        int sig = __builtin_ctzll(in_set) + 1;
        t.pending.fetch_and(~(1ull << (sig - 1)));
        if (a1) {
            std::memset(m.host(a1), 0, 128);
            *m.ptr<std::int32_t>(a1) = sig;
        }
        return static_cast<std::uint32_t>(sig);
    }

    // ----------------------------------------------------------------- polling
    case 168: {  // poll: struct pollfd is the same everywhere; ppoll is the call both hosts have
        auto ms = static_cast<std::int32_t>(a2);
        timespec ts{ms / 1000, (ms % 1000) * 1'000'000L};
        // The kernel counts the timeout down in ts, so a restart waits only for the rest.
        return res(blocking(t, kRestart, __NR_ppoll, P(a0), a1, ms < 0 ? 0 : reinterpret_cast<std::intptr_t>(&ts), 0, 8));
    }
    case 336: {  // ppoll(fds, n, timeout, sigmask, sigsetsize): the guest's mask is not applied
        timespec ts{};
        timespec* tp = nullptr;
        if (a2) {
            if (!mem_ok(a2, sizeof(Timespec32))) return err(EFAULT);
            ts = to_host(*m.ptr<Timespec32>(a2));
            tp = &ts;
        }
        return res(blocking(t, kRestart, __NR_ppoll, P(a0), a1, reinterpret_cast<std::intptr_t>(tp), 0, 8));
    }
    case 142: {  // _newselect: fd_set bit layout matches on little-endian hosts
        // pselect6 is the call both hosts have; like select it leaves the time not slept.
        timespec ts{};
        timespec* tp = nullptr;
        if (a4) {
            if (!mem_ok(a4, sizeof(Timeval32))) return err(EFAULT);
            auto* g = m.ptr<Timeval32>(a4);
            ts = timespec{g->tv_sec, g->tv_usec * 1000L};
            tp = &ts;
        }
        long rc = blocking(t, kRestart, __NR_pselect6, sint(a0), P(a1), P(a2), P(a3), reinterpret_cast<std::intptr_t>(tp), 0);
        if (rc >= 0 && a4) {
            Timeval32 o{static_cast<std::int32_t>(ts.tv_sec), static_cast<std::int32_t>(ts.tv_nsec / 1000)};
            std::memcpy(m.host(a4), &o, sizeof o);
        }
        return res(rc);
    }
    case 335: {  // pselect6(n, in, out, ex, timespec*, sigmask_and_size*): what the C library's
                 // select() and pselect() make. The guest's mask is not applied, as for ppoll.
        timespec ts{};
        timespec* tp = nullptr;
        if (a4) {
            if (!mem_ok(a4, sizeof(Timespec32))) return err(EFAULT);
            ts = to_host(*m.ptr<Timespec32>(a4));
            tp = &ts;
        }
        long rc = blocking(t, kRestart, __NR_pselect6, sint(a0), P(a1), P(a2), P(a3), reinterpret_cast<std::intptr_t>(tp), 0);
        // The kernel counts the timeout down; select() turns what is left back into its timeval.
        if (rc >= 0 && a4) {
            Timespec32 o = to_arm(ts);
            std::memcpy(m.host(a4), &o, sizeof o);
        }
        return res(rc);
    }
    case 250:  // epoll_create
        return res(epoll_create(static_cast<int>(a0)));
    case 357:  // epoll_create1
        return res(epoll_create1(open_flags_to_host(a0)));
    case 251: {  // epoll_ctl
        epoll_event ev{};
        if (a3) {
            if (!mem_ok(a3, sizeof(EpollEventArm))) return err(EFAULT);
            EpollEventArm g;
            std::memcpy(&g, m.host(a3), sizeof g);
            ev.events = g.events;
            ev.data.u64 = g.data;
        }
        return res(epoll_ctl(static_cast<int>(a0), static_cast<int>(a1), static_cast<int>(a2), a3 ? &ev : nullptr));
    }
    case 252:    // epoll_wait
    case 346: {  // epoll_pwait
        int max = static_cast<int>(a2);
        if (max <= 0 || max > 4096) return err(EINVAL);
        if (!mem_ok(a1, static_cast<std::uint32_t>(max) * sizeof(EpollEventArm))) return err(EFAULT);
        std::vector<epoll_event> evs(static_cast<std::size_t>(max));
        long n = blocking(t, kNoRestart, __NR_epoll_pwait, sint(a0), reinterpret_cast<std::intptr_t>(evs.data()), max, sint(a3), 0, 8);
        if (n < 0) return err(errno);
        for (int i = 0; i < n; ++i) {
            EpollEventArm g{evs[static_cast<std::size_t>(i)].events, 0, evs[static_cast<std::size_t>(i)].data.u64};
            std::memcpy(m.host(a1 + static_cast<gaddr>(i) * sizeof g), &g, sizeof g);
        }
        return static_cast<std::uint32_t>(n);
    }
    case 360:  // inotify_init1
        return res(syscall(__NR_inotify_init1, open_flags_to_host(a0)));
    case 317: {  // inotify_add_watch(fd, path, mask)
        std::string hp;
        if (!path_arg(a1, hp)) return err(EFAULT);
        return res(syscall(__NR_inotify_add_watch, static_cast<int>(a0), hp.c_str(), a2));
    }
    case 318:  // inotify_rm_watch
        return res(syscall(__NR_inotify_rm_watch, static_cast<int>(a0), static_cast<int>(a1)));
    case 143:  // flock
        return res(blocking(t, kRestart, __NR_flock, sint(a0), sint(a1)));
    case 351:  // eventfd
        return res(eventfd(a0, 0));
    case 356:  // eventfd2
        return res(eventfd(a0, open_flags_to_host(a1)));

    // ----------------------------------------------------------------- sockets
    case 281:  // socket
        return res(socket(static_cast<int>(a0), static_cast<int>(a1), static_cast<int>(a2)));
    case 288:  // socketpair
        return res(socketpair(static_cast<int>(a0), static_cast<int>(a1), static_cast<int>(a2), static_cast<int*>(H(a3))));
    case 282: {  // bind
        // A Unix socket's name is a file name: it goes where the guest's files go (host_path).
        sockaddr_un moved;
        socklen_t len = a2;
        const sockaddr* at = unix_address(p, static_cast<const sockaddr*>(H(a1)), len, moved);
        return res(bind(static_cast<int>(a0), at, len));
    }
    case 283: {  // connect
        sockaddr_un moved;
        socklen_t moved_len = a2;
        const auto* to = unix_address(p, static_cast<const sockaddr*>(H(a1)), moved_len, moved);
        const bool was_moved = to == reinterpret_cast<const sockaddr*>(&moved);
        // Setting a system property: apps may not since Android 8, and the host refuses it with an
        // SELinux denial written to the log each time; Technika Q tries once a frame. After the
        // host's first refusal the same answer comes from here.
        static const char kPropertyService[] = "/dev/socket/property_service";
        static std::atomic<int> property_refused{0};  // the host's errno for it (0: not refused)
        const bool property = to && a2 >= offsetof(sockaddr_un, sun_path) + sizeof kPropertyService &&
                              to->sa_family == AF_UNIX &&
                              std::strcmp(reinterpret_cast<const sockaddr_un*>(to)->sun_path, kPropertyService) == 0;
        const int refused = property ? property_refused.load(std::memory_order_relaxed) : 0;
        long r = refused ? -1 : blocking(t, kNoRestart, __NR_connect, sint(a0), was_moved ? reinterpret_cast<std::intptr_t>(&moved) : P(a1), moved_len);
        const int e = refused ? refused : r < 0 ? errno : 0;
        if (property && r < 0 && !refused && e != EINTR) property_refused.store(e, std::memory_order_relaxed);
        if (g_stats) note_connect(to, a2, e);
        return r < 0 ? err(e) : static_cast<std::uint32_t>(r);
    }
    case 284:  // listen
        return res(listen(static_cast<int>(a0), static_cast<int>(a1)));
    case 285:  // accept
        return res(blocking(t, kRestart, __NR_accept4, sint(a0), P(a1), P(a2), 0));
    case 366:  // accept4
        return res(blocking(t, kRestart, __NR_accept4, sint(a0), P(a1), P(a2), open_flags_to_host(a3)));
    case 286:  // getsockname
        return res(getsockname(static_cast<int>(a0), static_cast<sockaddr*>(H(a1)), static_cast<socklen_t*>(H(a2))));
    case 287:  // getpeername
        return res(getpeername(static_cast<int>(a0), static_cast<sockaddr*>(H(a1)), static_cast<socklen_t*>(H(a2))));
    case 289:  // send
    case 290:  // sendto
        return res(blocking(t, kRestart, __NR_sendto, sint(a0), P(a1), a2, sint(a3), nr == 290 ? P(a4) : 0, nr == 290 ? a5 : 0));
    case 291:  // recv
    case 292:  // recvfrom
        return res(blocking(t, kRestart, __NR_recvfrom, sint(a0), P(a1), a2, sint(a3), nr == 292 ? P(a4) : 0, nr == 292 ? P(a5) : 0));
    case 293:  // shutdown
        return res(shutdown(static_cast<int>(a0), static_cast<int>(a1)));
    case 294: {  // setsockopt: the timeouts are 32-bit timevals
        if (a1 == SOL_SOCKET && (a2 == SO_RCVTIMEO || a2 == SO_SNDTIMEO)) {
            if (!mem_ok(a3, sizeof(Timeval32))) return err(EFAULT);
            auto* g = m.ptr<Timeval32>(a3);
            timeval tv{g->tv_sec, g->tv_usec};
            return res(setsockopt(static_cast<int>(a0), SOL_SOCKET, static_cast<int>(a2), &tv, sizeof tv));
        }
        return res(setsockopt(static_cast<int>(a0), static_cast<int>(a1), static_cast<int>(a2), H(a3), a4));
    }
    case 295: {  // getsockopt
        if (a1 == SOL_SOCKET && (a2 == SO_RCVTIMEO || a2 == SO_SNDTIMEO)) {
            if (!mem_ok(a3, sizeof(Timeval32)) || !mem_ok(a4, 4)) return err(EFAULT);
            timeval tv{};
            socklen_t len = sizeof tv;
            if (getsockopt(static_cast<int>(a0), SOL_SOCKET, static_cast<int>(a2), &tv, &len) < 0) return err(errno);
            Timeval32 o{static_cast<std::int32_t>(tv.tv_sec), static_cast<std::int32_t>(tv.tv_usec)};
            std::memcpy(m.host(a3), &o, sizeof o);
            *m.ptr<std::uint32_t>(a4) = sizeof o;
            return 0;
        }
        return res(getsockopt(static_cast<int>(a0), static_cast<int>(a1), static_cast<int>(a2), H(a3), static_cast<socklen_t*>(H(a4))));
    }
    case 296:    // sendmsg
    case 297: {  // recvmsg
        if (!mem_ok(a1, sizeof(MsghdrArm))) return err(EFAULT);
        MsghdrArm g;
        std::memcpy(&g, m.host(a1), sizeof g);
        std::vector<iovec> v;
        if (!get_iovecs(p, g.iov, g.iovlen, v)) return err(EFAULT);
        if (g.controllen) {
            // Control messages (fd passing, credentials) differ in layout; nothing needs them yet.
            log("arm32: %s with control data is not supported", nr == 296 ? "sendmsg" : "recvmsg");
            return err(EOPNOTSUPP);
        }
        msghdr h{};
        h.msg_name = H(g.name);
        h.msg_namelen = g.namelen;
        h.msg_iov = v.data();
        h.msg_iovlen = v.size();
        long n = blocking(t, kRestart, nr == 296 ? __NR_sendmsg : __NR_recvmsg, sint(a0), reinterpret_cast<std::intptr_t>(&h), sint(a2));
        if (n < 0) return err(errno);
        if (nr == 297) {
            *m.ptr<std::uint32_t>(a1 + 4) = h.msg_namelen;
            *m.ptr<std::int32_t>(a1 + 24) = h.msg_flags;
        }
        return static_cast<std::uint32_t>(n);
    }

    // ----------------------------------------------------------------- ARM private calls
    case 0xf0001:  // breakpoint
        t.fatal("breakpoint system call", r[15]);
    case 0xf0002:  // cacheflush(start, end, flags): drop translated code there
        if (a1 > a0) invalidate_code(a0, a1 - a0);
        return 0;
    case 0xf0005:  // set_tls
        t.tls = a0;
        return 0;

    default:
        log("arm32: unhandled system call %u (r0 %#x r1 %#x r2 %#x) at pc %#x", nr, a0, a1, a2, r[15]);
        return err(ENOSYS);
    }
}

}  // namespace arm32
