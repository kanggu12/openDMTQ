// Linux's interface as the runtime's core uses it, on a Windows host: Linux's numbers (arm32_linux_abi.h, generated from Linux
// x86-64's own headers), its structures with their x86-64 layouts, and the calls, which src/win implements on Win32 with
// Linux's meaning (an int descriptor of the layer's own table, errno with Linux's values, -1 on failure). The headers in
// src/win/include, found before the system's, bring this in under the names the core includes (<sys/mman.h> and the
// rest), so the core's code is the same on every host. The calls live in arm32::posix and are named at global scope by
// using-declarations: they never meet the C runtime's functions of the same names.
#pragma once

// Forced into every file of the runtime on Windows (CMake); a file that talks to Winsock defines ARM32_NO_LINUX, and
// sees none of it.
#ifndef ARM32_NO_LINUX

// The C library's own headers first, pthread.h's (winpthreads) among them: their declarations stand before the names
// below take theirs over. pid_t first of all, which winpthreads' headers use and the C library leaves out without its
// old names (NO_OLDNAMES, so that read and the others are not the C library's).
#ifndef _PID_T_
#define _PID_T_
typedef int pid_t;
#endif
#include <cerrno>
#include <cstdarg>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <pthread.h>
#include <sys/types.h>

#include "arm32_linux_abi.h"

// Numbers the generator leaves out: strings and pointers, and sysconf's names, which glibc has as enumerators.
#undef MAP_FAILED
#define MAP_FAILED ((void*)-1)
#undef SIG_DFL
#undef SIG_IGN
#undef ELFMAG
#define ELFMAG "\177ELF"
#define SELFMAG 4
#define RTLD_NODELETE 0x1000
#define _SC_CLK_TCK 2
#define _SC_PAGESIZE 30
#define _SC_PAGE_SIZE 30
#define _SC_NPROCESSORS_CONF 83
#define _SC_NPROCESSORS_ONLN 84
#define _SC_PHYS_PAGES 85

// dlopen's flags, as glibc numbers them.
#define RTLD_LAZY 1
#define RTLD_NOW 2
#define RTLD_LOCAL 0
#define RTLD_GLOBAL 0x100
#define RTLD_NOLOAD 4
#define RTLD_DEFAULT nullptr

// The types Linux has and Windows' C library does not, or has narrower.
typedef unsigned int uid_t;
typedef unsigned int gid_t;
typedef unsigned int id_t;
typedef unsigned int socklen_t;
typedef unsigned short sa_family_t;
typedef unsigned long long nfds_t;
typedef unsigned long long rlim_t;
typedef std::uint64_t eventfd_t;
typedef long long blksize_t;
typedef long long blkcnt_t;
typedef unsigned long long fsblkcnt_t;
typedef unsigned long long fsfilcnt_t;
// The C library has these only as old names, which are left out (NO_OLDNAMES).
typedef long long off_t;
typedef long long off64_t;
typedef std::uint64_t dev_t;
typedef std::uint64_t ino_t;

// struct stat as x86-64 Linux lays it out; the time fields as timespecs, with the old names on top.
struct stat {
    std::uint64_t st_dev;
    std::uint64_t st_ino;
    std::uint64_t st_nlink;
    std::uint32_t st_mode;
    std::uint32_t st_uid;
    std::uint32_t st_gid;
    std::int32_t pad0_;
    std::uint64_t st_rdev;
    std::int64_t st_size;
    std::int64_t st_blksize;
    std::int64_t st_blocks;
    struct timespec st_atim;
    struct timespec st_mtim;
    struct timespec st_ctim;
    std::int64_t reserved_[3];
};
#define st_atime st_atim.tv_sec
#define st_mtime st_mtim.tv_sec
#define st_ctime st_ctim.tv_sec
#define S_ISDIR(m) (((m) & S_IFMT) == S_IFDIR)
#define S_ISREG(m) (((m) & S_IFMT) == S_IFREG)
#define S_ISLNK(m) (((m) & S_IFMT) == S_IFLNK)
#define S_ISFIFO(m) (((m) & S_IFMT) == S_IFIFO)
#define S_ISSOCK(m) (((m) & S_IFMT) == S_IFSOCK)
#define S_ISCHR(m) (((m) & S_IFMT) == S_IFCHR)

struct statfs {
    std::int64_t f_type, f_bsize;
    std::uint64_t f_blocks, f_bfree, f_bavail, f_files, f_ffree;
    struct {
        int val[2];
    } f_fsid;
    std::int64_t f_namelen, f_frsize, f_flags, f_spare[4];
};

struct sysinfo {
    long long uptime;
    unsigned long long loads[3];
    unsigned long long totalram, freeram, sharedram, bufferram, totalswap, freeswap;
    unsigned short procs, pad;
    unsigned long long totalhigh, freehigh;
    unsigned int mem_unit;
    char f_[0];
};

struct utsname {
    char sysname[65], nodename[65], release[65], version[65], machine[65], domainname[65];
};

struct rlimit {
    rlim_t rlim_cur, rlim_max;
};

struct pollfd {
    int fd;
    short events, revents;
};

// Packed on x86-64, as Linux has it.
typedef union epoll_data {
    void* ptr;
    int fd;
    std::uint32_t u32;
    std::uint64_t u64;
} epoll_data_t;
struct __attribute__((packed)) epoll_event {
    std::uint32_t events;
    epoll_data_t data;
};

struct iovec {
    void* iov_base;
    std::size_t iov_len;
};

struct msghdr {
    void* msg_name;
    socklen_t msg_namelen;
    struct iovec* msg_iov;
    std::size_t msg_iovlen;
    void* msg_control;
    std::size_t msg_controllen;
    int msg_flags;
};

struct cmsghdr {
    std::size_t cmsg_len;
    int cmsg_level, cmsg_type;
};

struct sockaddr {
    sa_family_t sa_family;
    char sa_data[14];
};
struct sockaddr_storage {
    sa_family_t ss_family;
    char pad_[118];
    unsigned long long align_;
};
struct sockaddr_un {
    sa_family_t sun_family;
    char sun_path[108];
};
struct in_addr {
    std::uint32_t s_addr;
};
struct sockaddr_in {
    sa_family_t sin_family;
    std::uint16_t sin_port;
    struct in_addr sin_addr;
    unsigned char sin_zero[8];
};
struct in6_addr {
    unsigned char s6_addr[16];
};
struct sockaddr_in6 {
    sa_family_t sin6_family;
    std::uint16_t sin6_port;
    std::uint32_t sin6_flowinfo;
    struct in6_addr sin6_addr;
    std::uint32_t sin6_scope_id;
};
struct linger {
    int l_onoff, l_linger;
};
// getaddrinfo's results, as glibc lays them out.
struct addrinfo {
    int ai_flags, ai_family, ai_socktype, ai_protocol;
    socklen_t ai_addrlen;
    struct sockaddr* ai_addr;
    char* ai_canonname;
    struct addrinfo* ai_next;
};

struct tms {
    long long tms_utime, tms_stime, tms_cutime, tms_cstime;
};
struct winsize {
    unsigned short ws_row, ws_col, ws_xpixel, ws_ypixel;
};
// select's set: 1024 descriptors, as Linux's.
typedef struct {
    unsigned long long fds_bits[16];
} fd_set;
#define FD_SETSIZE 1024
#define FD_ZERO(s) (void)(std::memset((s), 0, sizeof(fd_set)))
#define FD_SET(d, s) ((s)->fds_bits[(d) / 64] |= (1ull << ((d) % 64)))
#define FD_CLR(d, s) ((s)->fds_bits[(d) / 64] &= ~(1ull << ((d) % 64)))
#define FD_ISSET(d, s) (((s)->fds_bits[(d) / 64] >> ((d) % 64)) & 1ull)

// fcntl's record locks, as x86-64 Linux lays them out.
struct flock {
    short l_type, l_whence;
    long long l_start, l_len;
    int l_pid;
};
// Its counters are longs, as the core reads them in a row.
struct rusage {
    struct timeval ru_utime, ru_stime;
    long ru_maxrss, ru_ixrss, ru_idrss, ru_isrss, ru_minflt, ru_majflt, ru_nswap, ru_inblock, ru_oublock, ru_msgsnd, ru_msgrcv, ru_nsignals,
        ru_nvcsw, ru_nivcsw;
};

struct linux_dirent64 {
    std::uint64_t d_ino;
    std::int64_t d_off;
    unsigned short d_reclen;
    unsigned char d_type;
    char d_name[];
};

inline std::uint16_t htons(std::uint16_t v) { return static_cast<std::uint16_t>((v << 8) | (v >> 8)); }
inline std::uint16_t ntohs(std::uint16_t v) { return htons(v); }
inline std::uint32_t htonl(std::uint32_t v) { return __builtin_bswap32(v); }
inline std::uint32_t ntohl(std::uint32_t v) { return __builtin_bswap32(v); }

static_assert(sizeof(struct stat) == 144, "struct stat as x86-64 Linux has it");
static_assert(sizeof(struct statfs) == 120, "struct statfs as x86-64 Linux has it");
static_assert(sizeof(struct utsname) == 390, "struct utsname as Linux has it");
static_assert(sizeof(struct epoll_event) == 12, "struct epoll_event as x86-64 Linux has it");
static_assert(sizeof(struct msghdr) == 56, "struct msghdr as x86-64 Linux has it");
static_assert(sizeof(struct sockaddr_un) == 110, "struct sockaddr_un as Linux has it");
static_assert(sizeof(struct sockaddr_in6) == 28, "struct sockaddr_in6 as Linux has it");
static_assert(sizeof(fd_set) == 128, "fd_set as Linux has it");

namespace arm32::posix {

// Files and descriptors.
int open(const char* path, int flags, ...);
int openat(int dirfd, const char* path, int flags, ...);
int close(int fd);
ssize_t read(int fd, void* buf, std::size_t n);
ssize_t write(int fd, const void* buf, std::size_t n);
ssize_t pread(int fd, void* buf, std::size_t n, long long offset);
ssize_t pwrite(int fd, const void* buf, std::size_t n, long long offset);
ssize_t pread64(int fd, void* buf, std::size_t n, long long offset);
ssize_t readv(int fd, const struct iovec* iov, int n);
ssize_t writev(int fd, const struct iovec* iov, int n);
long long lseek(int fd, long long offset, int whence);
int fstat(int fd, struct stat* st);
int stat(const char* path, struct stat* st);
int lstat(const char* path, struct stat* st);
int fstatat(int dirfd, const char* path, struct stat* st, int flags);
int fstatfs(int fd, struct statfs* st);
int statfs(const char* path, struct statfs* st);
int fcntl(int fd, int cmd, ...);
int ioctl(int fd, unsigned long request, ...);
int dup(int fd);
int dup2(int fd, int to);
int dup3(int fd, int to, int flags);
int pipe2(int fds[2], int flags);
int ftruncate(int fd, long long size);
int ftruncate64(int fd, long long size);
int truncate(const char* path, long long size);
int fsync(int fd);
int fdatasync(int fd);
int flock(int fd, int op);
int access(const char* path, int mode);
int faccessat(int dirfd, const char* path, int mode, int flags);
int unlink(const char* path);
int unlinkat(int dirfd, const char* path, int flags);
int mkdir(const char* path, unsigned int mode);
int mkdirat(int dirfd, const char* path, unsigned int mode);
int rmdir(const char* path);
int renameat(int fromfd, const char* from, int tofd, const char* to);
ssize_t readlink(const char* path, char* buf, std::size_t n);
ssize_t readlinkat(int dirfd, const char* path, char* buf, std::size_t n);
int chdir(const char* path);
int fchdir(int fd);
char* getcwd(char* buf, std::size_t n);
unsigned int umask(unsigned int mask);
int utimensat(int dirfd, const char* path, const struct timespec times[2], int flags);
int chmod(const char* path, unsigned int mode);
int fchmod(int fd, unsigned int mode);
int fchmodat(int dirfd, const char* path, unsigned int mode, int flags);
int eventfd(unsigned int initial, int flags);
int memfd_create(const char* name, unsigned int flags);
// Directory entries in Linux's linux_dirent64 records.
long getdents64(int fd, void* buf, std::size_t n);

// Memory of the host process (the runtime's own: the guest's block, its own buffers).
void* mmap(void* addr, std::size_t length, int prot, int flags, int fd, long long offset);
int munmap(void* addr, std::size_t length);
int mprotect(void* addr, std::size_t length, int prot);
int madvise(void* addr, std::size_t length, int advice);
void* mremap(void* old, std::size_t old_size, std::size_t new_size, int flags, ...);

// Sockets.
int socket(int domain, int type, int protocol);
int socketpair(int domain, int type, int protocol, int fds[2]);
int bind(int fd, const struct sockaddr* addr, socklen_t len);
int listen(int fd, int backlog);
int accept4(int fd, struct sockaddr* addr, socklen_t* len, int flags);
int connect(int fd, const struct sockaddr* addr, socklen_t len);
ssize_t send(int fd, const void* buf, std::size_t n, int flags);
ssize_t recv(int fd, void* buf, std::size_t n, int flags);
ssize_t sendto(int fd, const void* buf, std::size_t n, int flags, const struct sockaddr* to, socklen_t len);
ssize_t recvfrom(int fd, void* buf, std::size_t n, int flags, struct sockaddr* from, socklen_t* len);
ssize_t sendmsg(int fd, const struct msghdr* msg, int flags);
ssize_t recvmsg(int fd, struct msghdr* msg, int flags);
int getsockopt(int fd, int level, int name, void* value, socklen_t* len);
int setsockopt(int fd, int level, int name, const void* value, socklen_t len);
int getsockname(int fd, struct sockaddr* addr, socklen_t* len);
int getpeername(int fd, struct sockaddr* addr, socklen_t* len);
int shutdown(int fd, int how);
int getaddrinfo(const char* host, const char* service, const struct addrinfo* hints, struct addrinfo** res);
void freeaddrinfo(struct addrinfo* list);
const char* gai_strerror(int code);

// Waiting on descriptors.
int poll(struct pollfd* fds, nfds_t n, int timeout_ms);
int ppoll(struct pollfd* fds, nfds_t n, const struct timespec* timeout, const void* sigmask);
int select(int n, fd_set* r, fd_set* w, fd_set* e, struct timeval* timeout);
int epoll_create(int size);
int epoll_create1(int flags);
int epoll_ctl(int epfd, int op, int fd, struct epoll_event* event);
int epoll_wait(int epfd, struct epoll_event* events, int max, int timeout_ms);

// Time.
int gettimeofday(struct timeval* tv, void* tz);

// The process.
int getpid();
int gettid();
int getppid();
uid_t getuid();
uid_t geteuid();
gid_t getgid();
gid_t getegid();
int uname(struct utsname* u);
int sysinfo(struct sysinfo* info);
int getrlimit(int resource, struct rlimit* limit);
int getrusage(int who, struct rusage* usage);
long long times(struct tms* t);
int setsid();
int getsid(int pid);
int getpgid(int pid);
int getgroups(int n, gid_t* list);
int getpriority(int which, id_t who);
int setpriority(int which, id_t who, int prio);
int setrlimit(int resource, const struct rlimit* limit);
int prctl(int option, ...);
long sysconf(int name);
// Waits for a signal; here a short sleep, after which the caller looks again at what it waits for.
int pause();
int kill(int pid, int sig);
int tgkill(int pid, int tid, int sig);
// A system call of Linux's by its x86-64 number, for those the core makes that way (futex, sched_*, getrandom, ...).
long syscall(long nr, ...);

// The host's shared libraries (DLLs), as dlopen gives them: by name, then their exports by name.
void* dlopen(const char* name, int flags);
void* dlsym(void* handle, const char* name);
int dlclose(void* handle);
char* dlerror();

// Wakes the host thread `thread` (its id, from gettid) out of a call it waits in, which then fails with EINTR: what the
// interrupt signal does on Linux.
void interrupt(int thread);

// The computer's time zone, as the guest's C library reads one: TZ when it is set, else ICU's tz database name of
// Windows' zone (Windows 10 has ICU), else a POSIX rule made from Windows' own offset and daylight saving dates.
const char* host_zone();

}  // namespace arm32::posix

using arm32::posix::accept4;
using arm32::posix::access;
using arm32::posix::bind;
using arm32::posix::chdir;
using arm32::posix::close;
using arm32::posix::connect;
using arm32::posix::dlclose;
using arm32::posix::dlerror;
using arm32::posix::dlopen;
using arm32::posix::dlsym;
using arm32::posix::dup;
using arm32::posix::dup2;
using arm32::posix::dup3;
using arm32::posix::epoll_create;
using arm32::posix::epoll_create1;
using arm32::posix::epoll_ctl;
using arm32::posix::epoll_wait;
using arm32::posix::eventfd;
using arm32::posix::faccessat;
using arm32::posix::fchdir;
using arm32::posix::fcntl;
using arm32::posix::fdatasync;
using arm32::posix::flock;
using arm32::posix::fstat;
using arm32::posix::fstatat;
using arm32::posix::fstatfs;
using arm32::posix::fsync;
using arm32::posix::ftruncate;
using arm32::posix::ftruncate64;
using arm32::posix::getaddrinfo;
using arm32::posix::freeaddrinfo;
using arm32::posix::gai_strerror;
using arm32::posix::getcwd;
using arm32::posix::getdents64;
using arm32::posix::getpeername;
using arm32::posix::getpid;
using arm32::posix::getppid;
using arm32::posix::getrlimit;
using arm32::posix::getsockname;
using arm32::posix::getsockopt;
using arm32::posix::gettid;
using arm32::posix::gettimeofday;
using arm32::posix::getuid;
using arm32::posix::chmod;
using arm32::posix::fchmod;
using arm32::posix::fchmodat;
using arm32::posix::getrusage;
using arm32::posix::times;
using arm32::posix::setsid;
using arm32::posix::getsid;
using arm32::posix::getpgid;
using arm32::posix::getgroups;
using arm32::posix::getpriority;
using arm32::posix::setpriority;
using arm32::posix::geteuid;
using arm32::posix::getgid;
using arm32::posix::getegid;
using arm32::posix::ioctl;
using arm32::posix::kill;
using arm32::posix::listen;
using arm32::posix::lseek;
using arm32::posix::lstat;
using arm32::posix::madvise;
using arm32::posix::memfd_create;
using arm32::posix::mkdir;
using arm32::posix::mkdirat;
using arm32::posix::mmap;
using arm32::posix::mprotect;
using arm32::posix::mremap;
using arm32::posix::munmap;
using arm32::posix::open;
using arm32::posix::openat;
using arm32::posix::pipe2;
using arm32::posix::pause;
using arm32::posix::poll;
using arm32::posix::ppoll;
using arm32::posix::prctl;
using arm32::posix::pread;
using arm32::posix::pread64;
using arm32::posix::pwrite;
using arm32::posix::read;
using arm32::posix::readlink;
using arm32::posix::readlinkat;
using arm32::posix::readv;
using arm32::posix::recv;
using arm32::posix::recvfrom;
using arm32::posix::recvmsg;
using arm32::posix::renameat;
using arm32::posix::rmdir;
using arm32::posix::select;
using arm32::posix::send;
using arm32::posix::sendmsg;
using arm32::posix::sendto;
using arm32::posix::setrlimit;
using arm32::posix::setsockopt;
using arm32::posix::shutdown;
using arm32::posix::socket;
using arm32::posix::socketpair;
using arm32::posix::syscall;
using arm32::posix::sysconf;
using arm32::posix::sysinfo;
using arm32::posix::tgkill;
using arm32::posix::truncate;
using arm32::posix::umask;
using arm32::posix::uname;
using arm32::posix::unlink;
using arm32::posix::unlinkat;
using arm32::posix::utimensat;
using arm32::posix::write;
using arm32::posix::writev;
// stat and statfs are structs and calls at once, as in C: the call needs its own declaration at global scope.
int stat(const char* path, struct stat* st);
int statfs(const char* path, struct statfs* st);

// The layer's own versions of calls the C library or winpthreads have under the same names and parameters, which do not
// mean Linux's (rename replaces what is there; the clocks are all of Linux's).
int arm32_clock_gettime(int clock, struct timespec* ts);
int arm32_clock_nanosleep(int clock, int flags, const struct timespec* request, struct timespec* remain);
int arm32_nanosleep(const struct timespec* request, struct timespec* remain);
int arm32_rename(const char* from, const char* to);
#define clock_gettime arm32_clock_gettime
#define clock_nanosleep arm32_clock_nanosleep
#define nanosleep arm32_nanosleep
#define rename arm32_rename
// std::rename is the same call under the same macro.
namespace std {
using ::arm32_rename;
}

// The POSIX names for comparing without case, which the C runtime has as _stricmp and _strnicmp: its old names are
// off (NO_OLDNAMES), and <strings.h> gives nothing more than <string.h>.
namespace arm32::posix {
inline int strcasecmp(const char* a, const char* b) { return _stricmp(a, b); }
inline int strncasecmp(const char* a, const char* b, std::size_t n) { return _strnicmp(a, b, n); }
}  // namespace arm32::posix
using arm32::posix::strcasecmp;
using arm32::posix::strncasecmp;

#endif  // ARM32_NO_LINUX
