// The Windows layer's core (layer.h): Windows' errors as Linux's, the waits a guest signal can cut short, the clocks and
// sleeps, futexes, the process's own facts, shared libraries, and the system calls the runtime makes by number, among
// them the one a guest signal must be able to interrupt (arm32_isys, which is assembly on Linux).
#include "layer.h"

#include <cstdarg>

#include <algorithm>
#include <climits>
#include <cstring>
#include <map>
#include <unordered_map>

// The C runtime's _setmode and its binary mode (io.h and fcntl.h are Linux's here).
extern "C" int _setmode(int fd, int mode);

namespace arm32::win {

thread_local bool t_interruptible = false;

namespace {
// The runtime's own output (its log, the runner's lines) through the C runtime's stdout and stderr: binary, so that a
// line ends with \n alone, as on Linux and as the guest's own output (written straight to the handles) ends.
const bool g_binary_output = [] {
    _setmode(_fileno(stdout), 0x8000 /* _O_BINARY */);
    _setmode(_fileno(stderr), 0x8000);
    return true;
}();
}  // namespace

int errno_of(DWORD error) {
    switch (error) {
    case ERROR_FILE_NOT_FOUND:
    case ERROR_PATH_NOT_FOUND:
    case ERROR_INVALID_NAME:
    case ERROR_BAD_NETPATH:
    case ERROR_MOD_NOT_FOUND:
        return ENOENT;
    case ERROR_ACCESS_DENIED:
    case ERROR_SHARING_VIOLATION:
    case ERROR_LOCK_VIOLATION:
    case ERROR_WRITE_PROTECT:
        return EACCES;
    case ERROR_ALREADY_EXISTS:
    case ERROR_FILE_EXISTS:
        return EEXIST;
    case ERROR_DIR_NOT_EMPTY:
        return ENOTEMPTY;
    case ERROR_DIRECTORY:
        return ENOTDIR;
    case ERROR_INVALID_HANDLE:
        return EBADF;
    case ERROR_NOT_ENOUGH_MEMORY:
    case ERROR_OUTOFMEMORY:
    case ERROR_COMMITMENT_LIMIT:
        return ENOMEM;
    case ERROR_DISK_FULL:
    case ERROR_HANDLE_DISK_FULL:
        return ENOSPC;
    case ERROR_BROKEN_PIPE:
    case ERROR_NO_DATA:
        return EPIPE;
    case ERROR_NOT_SAME_DEVICE:
        return EXDEV;
    case ERROR_FILENAME_EXCED_RANGE:
        return ENAMETOOLONG;
    case ERROR_NOT_SUPPORTED:
    case ERROR_CALL_NOT_IMPLEMENTED:
        return ENOSYS;
    case ERROR_OPERATION_ABORTED:
        return EINTR;
    default:
        return EINVAL;
    }
}

std::wstring wide(const std::string& s) {
    if (s.empty()) return {};
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), nullptr, 0);
    std::wstring out(static_cast<std::size_t>(n), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), out.data(), n);
    return out;
}

std::string narrow(const wchar_t* s, int n) {
    int len = WideCharToMultiByte(CP_UTF8, 0, s, n, nullptr, 0, nullptr, nullptr);
    std::string out(static_cast<std::size_t>(std::max(len, 0)), '\0');
    WideCharToMultiByte(CP_UTF8, 0, s, n, out.data(), len, nullptr, nullptr);
    // A length of -1 counts the terminating NUL, which the string does not keep.
    if (n < 0 && !out.empty() && out.back() == '\0') out.pop_back();
    return out;
}

void Waitable::add_waiter(HANDLE event) {
    std::lock_guard<std::mutex> l(lock_);
    waiters_.push_back(event);
}

void Waitable::remove_waiter(HANDLE event) {
    std::lock_guard<std::mutex> l(lock_);
    auto it = std::find(waiters_.begin(), waiters_.end(), event);
    if (it != waiters_.end()) waiters_.erase(it);
}

void Waitable::notify() {
    // Counted before the wake, so that whoever wakes sees the change.
    ++changes_;
    std::lock_guard<std::mutex> l(lock_);
    for (HANDLE h : waiters_) SetEvent(h);
}

namespace {

// Windows 10 1607's thread description calls, from kernel32 when it has them.
using SetDescription = HRESULT(WINAPI*)(HANDLE, PCWSTR);
using GetDescription = HRESULT(WINAPI*)(HANDLE, PWSTR*);
struct Descriptions {
    SetDescription set = nullptr;
    GetDescription get = nullptr;
};
const Descriptions& descriptions() {
    static const Descriptions d = [] {
        Descriptions out;
        // kernel32 is in every process: no load of its own, and no reference to give back.
        if (HMODULE k = GetModuleHandleW(L"kernel32.dll")) {
            out.set = reinterpret_cast<SetDescription>(reinterpret_cast<void*>(GetProcAddress(k, "SetThreadDescription")));
            out.get = reinterpret_cast<GetDescription>(reinterpret_cast<void*>(GetProcAddress(k, "GetThreadDescription")));
        }
        return out;
    }();
    return d;
}

}  // namespace

void set_thread_name(HANDLE thread, const std::wstring& name) {
    if (auto set = descriptions().set) set(thread, name.c_str());
}

std::string thread_name(HANDLE thread) {
    auto get = descriptions().get;
    PWSTR text = nullptr;
    std::string name;
    if (get && SUCCEEDED(get(thread, &text)) && text) {
        name = narrow(text);
        // The text is Windows' to give, and LocalFree's to take back.
        LocalFree(text);
    }
    return name;
}

long long monotonic_ns() {
    static const long long frequency = [] {
        LARGE_INTEGER f;
        QueryPerformanceFrequency(&f);
        return f.QuadPart;
    }();
    LARGE_INTEGER c;
    QueryPerformanceCounter(&c);
    // Whole seconds and the rest apart, so that the product never overflows.
    return c.QuadPart / frequency * 1000000000LL + c.QuadPart % frequency * 1000000000LL / frequency;
}

namespace {

// Each host thread's events: the one objects set when it waits on them, the interrupt a guest signal sets, and a
// high-resolution timer for its deadlines. Registered by thread id for posix::interrupt.
struct ThreadEvents {
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    HANDLE interrupt = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    HANDLE timer = nullptr;
    DWORD id = GetCurrentThreadId();
    ThreadEvents();
    ~ThreadEvents();
};

std::mutex g_threads_lock;
std::unordered_map<DWORD, HANDLE>& interrupts() {
    static auto* m = new std::unordered_map<DWORD, HANDLE>;
    return *m;
}

ThreadEvents::ThreadEvents() {
    // High resolution where Windows has it (10, version 1803 on); a plain one elsewhere, which the system's timer
    // resolution rounds.
    timer = CreateWaitableTimerExW(nullptr, nullptr, 0x00000002 /* CREATE_WAITABLE_TIMER_HIGH_RESOLUTION */, TIMER_ALL_ACCESS);
    if (!timer) timer = CreateWaitableTimerExW(nullptr, nullptr, 0, TIMER_ALL_ACCESS);
    std::lock_guard<std::mutex> l(g_threads_lock);
    interrupts()[id] = interrupt;
}

ThreadEvents::~ThreadEvents() {
    {
        std::lock_guard<std::mutex> l(g_threads_lock);
        interrupts().erase(id);
    }
    CloseHandle(event);
    CloseHandle(interrupt);
    if (timer) CloseHandle(timer);
}

ThreadEvents& events() {
    thread_local ThreadEvents e;
    return e;
}

}  // namespace

HANDLE thread_event() { return events().event; }

int wait_any(const HANDLE* handles, int n, long long deadline_ns) {
    ThreadEvents& e = events();
    HANDLE all[MAXIMUM_WAIT_OBJECTS];
    int count = 0;
    for (int i = 0; i < n && count < MAXIMUM_WAIT_OBJECTS - 2; ++i) all[count++] = handles[i];
    const int interrupt_at = t_interruptible ? count : -1;
    if (t_interruptible) all[count++] = e.interrupt;
    // A deadline: the high-resolution timer, set to it, waited on with the rest.
    int timer_at = -1;
    if (deadline_ns >= 0) {
        long long left = deadline_ns - monotonic_ns();
        if (left <= 0) {
            // Already past: only what is set right now counts.
            DWORD r = count ? WaitForMultipleObjects(static_cast<DWORD>(count), all, FALSE, 0) : WAIT_TIMEOUT;
            if (r >= WAIT_OBJECT_0 && r < WAIT_OBJECT_0 + static_cast<DWORD>(count)) {
                int k = static_cast<int>(r - WAIT_OBJECT_0);
                return k == interrupt_at ? -EINTR : 0;
            }
            return -ETIMEDOUT;
        }
        LARGE_INTEGER due;
        // Relative, in 100-nanosecond units: a negative due time.
        due.QuadPart = -std::max(1LL, left / 100);
        SetWaitableTimer(e.timer, &due, 0, nullptr, nullptr, FALSE);
        timer_at = count;
        all[count++] = e.timer;
    }
    DWORD r = WaitForMultipleObjects(static_cast<DWORD>(count), all, FALSE, INFINITE);
    if (timer_at >= 0) {
        CancelWaitableTimer(e.timer);
        // A timer that fired while another object ended the wait is still signaled, and cancelling does not clear it:
        // taken here, so that it cannot end a later wait before its time.
        WaitForSingleObject(e.timer, 0);
    }
    if (r < WAIT_OBJECT_0 || r >= WAIT_OBJECT_0 + static_cast<DWORD>(count)) return -EINVAL;
    int k = static_cast<int>(r - WAIT_OBJECT_0);
    if (k == interrupt_at) return -EINTR;
    if (k == timer_at) return -ETIMEDOUT;
    return 0;
}

}  // namespace arm32::win

using namespace arm32::win;

// ---------------------------------------------------------------------------------------------------------------------
// Time.

namespace {

// Windows' FILETIME epoch (1601) to Unix's (1970), in 100-nanosecond units.
constexpr long long kEpochDelta = 116444736000000000LL;

void to_timespec(long long ns, struct timespec* ts) {
    ts->tv_sec = static_cast<time_t>(ns / 1000000000LL);
    ts->tv_nsec = static_cast<long>(ns % 1000000000LL);
}

long long realtime_ns() {
    FILETIME ft;
    GetSystemTimePreciseAsFileTime(&ft);
    long long t = (static_cast<long long>(ft.dwHighDateTime) << 32 | ft.dwLowDateTime) - kEpochDelta;
    return t * 100;
}

long long filetime_ns(const FILETIME& ft) { return (static_cast<long long>(ft.dwHighDateTime) << 32 | ft.dwLowDateTime) * 100; }

// A clock's time in nanoseconds; -1 for a clock Linux does not have.
long long clock_ns(int clock) {
    switch (clock) {
    case CLOCK_REALTIME:
    case CLOCK_REALTIME_COARSE:
        return realtime_ns();
    case CLOCK_MONOTONIC:
    case CLOCK_MONOTONIC_RAW:
    case CLOCK_MONOTONIC_COARSE:
    case CLOCK_BOOTTIME:
        return monotonic_ns();
    case CLOCK_PROCESS_CPUTIME_ID: {
        FILETIME c, e, k, u;
        GetProcessTimes(GetCurrentProcess(), &c, &e, &k, &u);
        return filetime_ns(k) + filetime_ns(u);
    }
    case CLOCK_THREAD_CPUTIME_ID: {
        FILETIME c, e, k, u;
        GetThreadTimes(GetCurrentThread(), &c, &e, &k, &u);
        return filetime_ns(k) + filetime_ns(u);
    }
    default:
        return -1;
    }
}

// A sleep until `deadline` on the monotonic clock, which a guest signal can cut short.
int sleep_until(long long deadline) {
    int r = wait_any(nullptr, 0, deadline);
    return r == -ETIMEDOUT ? 0 : r;
}

}  // namespace

int arm32_clock_gettime(int clock, struct timespec* ts) {
    long long ns = clock_ns(clock);
    if (ns < 0) return fail(EINVAL);
    to_timespec(ns, ts);
    return 0;
}

int arm32_clock_nanosleep(int clock, int flags, const struct timespec* request, struct timespec* remain) {
    long long want = static_cast<long long>(request->tv_sec) * 1000000000LL + request->tv_nsec;
    long long now = clock_ns(clock);
    if (now < 0) return EINVAL;
    // An absolute time on its own clock, as the monotonic deadline the wait takes.
    long long deadline = monotonic_ns() + ((flags & TIMER_ABSTIME) ? want - now : want);
    int r = sleep_until(deadline);
    if (r == -EINTR) {
        if (remain && !(flags & TIMER_ABSTIME)) to_timespec(std::max(0LL, deadline - monotonic_ns()), remain);
        return EINTR;
    }
    return 0;
}

int arm32_nanosleep(const struct timespec* request, struct timespec* remain) {
    int r = arm32_clock_nanosleep(CLOCK_MONOTONIC, 0, request, remain);
    return r ? fail(r) : 0;
}

namespace arm32::posix {

int gettimeofday(struct timeval* tv, void*) {
    long long ns = realtime_ns();
    tv->tv_sec = static_cast<long>(ns / 1000000000LL);
    tv->tv_usec = static_cast<long>(ns % 1000000000LL / 1000);
    return 0;
}

long long times(struct tms* t) {
    FILETIME c, e, k, u;
    GetProcessTimes(GetCurrentProcess(), &c, &e, &k, &u);
    // Clock ticks of 1/100 s, as sysconf(_SC_CLK_TCK) says.
    if (t) {
        t->tms_utime = filetime_ns(u) / 10000000;
        t->tms_stime = filetime_ns(k) / 10000000;
        t->tms_cutime = t->tms_cstime = 0;
    }
    return monotonic_ns() / 10000000;
}

}  // namespace arm32::posix

// ---------------------------------------------------------------------------------------------------------------------
// Futexes: the waiters of each address in a table of the layer's own, so that a requeue can move them and a guest signal
// can wake one.

namespace {

struct Waiter {
    const void* address;
    std::uint32_t bitset;
    HANDLE event;
    bool woken = false;
};

std::mutex g_futex_lock;
std::unordered_multimap<const void*, Waiter*>& futex_waiters() {
    static auto* m = new std::unordered_multimap<const void*, Waiter*>;
    return *m;
}

long futex_wait(const std::uint32_t* word, std::uint32_t expected, long long deadline, std::uint32_t bitset) {
    if (!bitset) return -EINVAL;
    Waiter w{word, bitset, thread_event()};
    {
        std::lock_guard<std::mutex> l(g_futex_lock);
        // The word read under the lock that wakers take: a wake after this sees the waiter.
        if (__atomic_load_n(word, __ATOMIC_SEQ_CST) != expected) return -EAGAIN;
        ResetEvent(w.event);
        futex_waiters().emplace(word, &w);
    }
    for (;;) {
        int r = wait_any(&w.event, 1, deadline);
        std::lock_guard<std::mutex> l(g_futex_lock);
        if (w.woken) return 0;
        // The thread's event is shared with its polls: a set that was not a wake waits on.
        if (r == 0) continue;
        // Timed out or interrupted: out of the table, unless a wake took it out just now.
        auto range = futex_waiters().equal_range(w.address);
        for (auto it = range.first; it != range.second; ++it) {
            if (it->second == &w) {
                futex_waiters().erase(it);
                break;
            }
        }
        return r;
    }
}

// Wakes up to `n` waiters of `word` whose bitset meets `bitset`; the number woken. Under g_futex_lock.
long wake_locked(const void* word, long n, std::uint32_t bitset) {
    long woken = 0;
    auto range = futex_waiters().equal_range(word);
    for (auto it = range.first; it != range.second && woken < n;) {
        if (it->second->bitset & bitset) {
            it->second->woken = true;
            SetEvent(it->second->event);
            it = futex_waiters().erase(it);
            ++woken;
        } else {
            ++it;
        }
    }
    return woken;
}

// FUTEX_WAKE_OP's operation on the second word, and its comparison of the old value.
bool wake_op(std::uint32_t* word2, std::uint32_t encoded) {
    std::uint32_t op = (encoded >> 28) & 7, cmp = (encoded >> 24) & 15;
    std::uint32_t oparg = (encoded >> 12) & 0xfff, cmparg = encoded & 0xfff;
    if ((encoded >> 28) & 8) oparg = 1u << (oparg & 31);
    std::uint32_t old = __atomic_load_n(word2, __ATOMIC_SEQ_CST), next;
    do {
        switch (op) {
        case 0: next = oparg; break;
        case 1: next = old + oparg; break;
        case 2: next = old | oparg; break;
        case 3: next = old & ~oparg; break;
        default: next = old ^ oparg; break;
        }
    } while (!__atomic_compare_exchange_n(word2, &old, next, false, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST));
    int o = static_cast<int>(old), a = static_cast<int>(cmparg);
    switch (cmp) {
    case 0: return o == a;
    case 1: return o != a;
    case 2: return o < a;
    case 3: return o <= a;
    case 4: return o > a;
    default: return o >= a;
    }
}

long futex(std::uint32_t* word, int op, std::uint32_t val, const struct timespec* timeout, std::uint32_t* word2, std::uint32_t val3) {
    const int cmd = op & FUTEX_CMD_MASK;
    switch (cmd) {
    case FUTEX_WAIT:
    case FUTEX_WAIT_BITSET: {
        long long deadline = -1;
        if (timeout) {
            long long t = static_cast<long long>(timeout->tv_sec) * 1000000000LL + timeout->tv_nsec;
            if (cmd == FUTEX_WAIT) {
                // Relative, on the monotonic clock.
                deadline = monotonic_ns() + t;
            } else {
                // Absolute, on the monotonic clock or, with FUTEX_CLOCK_REALTIME, the real one.
                long long now = (op & FUTEX_CLOCK_REALTIME) ? realtime_ns() : monotonic_ns();
                deadline = monotonic_ns() + (t - now);
            }
        }
        return futex_wait(word, val, deadline, cmd == FUTEX_WAIT ? 0xffffffffu : val3);
    }
    case FUTEX_WAKE:
    case FUTEX_WAKE_BITSET: {
        std::lock_guard<std::mutex> l(g_futex_lock);
        return wake_locked(word, static_cast<long>(val), cmd == FUTEX_WAKE ? 0xffffffffu : val3);
    }
    case FUTEX_REQUEUE:
    case FUTEX_CMP_REQUEUE: {
        std::lock_guard<std::mutex> l(g_futex_lock);
        if (cmd == FUTEX_CMP_REQUEUE && __atomic_load_n(word, __ATOMIC_SEQ_CST) != val3) return -EAGAIN;
        long woken = wake_locked(word, static_cast<long>(val), 0xffffffffu);
        // The requeue count travels in the timeout's place.
        long move = static_cast<long>(reinterpret_cast<std::uintptr_t>(timeout)), moved = 0;
        auto range = futex_waiters().equal_range(word);
        std::vector<Waiter*> taken;
        for (auto it = range.first; it != range.second && moved < move;) {
            taken.push_back(it->second);
            it = futex_waiters().erase(it);
            ++moved;
        }
        for (Waiter* w : taken) {
            w->address = word2;
            futex_waiters().emplace(word2, w);
        }
        return woken + moved;
    }
    case FUTEX_WAKE_OP: {
        std::lock_guard<std::mutex> l(g_futex_lock);
        bool also = wake_op(word2, val3);
        long woken = wake_locked(word, static_cast<long>(val), 0xffffffffu);
        // The second count travels in the timeout's place.
        if (also) woken += wake_locked(word2, static_cast<long>(reinterpret_cast<std::uintptr_t>(timeout)), 0xffffffffu);
        return woken;
    }
    default:
        // Priority-inheriting futexes: bionic does not use them.
        return -ENOSYS;
    }
}

}  // namespace

// ---------------------------------------------------------------------------------------------------------------------
// The process.

namespace arm32::posix {

int getpid() { return static_cast<int>(GetCurrentProcessId()); }
int gettid() { return static_cast<int>(GetCurrentThreadId()); }
int getppid() { return 1; }
// One user and group, as an Android app has: its own.
uid_t getuid() { return 10000; }
uid_t geteuid() { return 10000; }
gid_t getgid() { return 10000; }
gid_t getegid() { return 10000; }
int setsid() { return getpid(); }
int getsid(int) { return getpid(); }
int getpgid(int) { return getpid(); }
int getgroups(int, gid_t*) { return 0; }
int getpriority(int, id_t) { return 0; }
int setpriority(int, id_t, int) { return 0; }

int uname(struct utsname* u) {
    std::memset(u, 0, sizeof *u);
    std::strcpy(u->sysname, "Linux");
    std::strcpy(u->nodename, "localhost");
    // A kernel of the age the guest's system expects at least.
    std::strcpy(u->release, "4.19.0");
    std::strcpy(u->version, "#1 SMP");
    std::strcpy(u->machine, "x86_64");
    return 0;
}

int sysinfo(struct sysinfo* info) {
    std::memset(info, 0, sizeof *info);
    MEMORYSTATUSEX m{};
    m.dwLength = sizeof m;
    GlobalMemoryStatusEx(&m);
    info->uptime = static_cast<long long>(GetTickCount64() / 1000);
    info->totalram = m.ullTotalPhys;
    info->freeram = m.ullAvailPhys;
    info->totalswap = m.ullTotalPageFile > m.ullTotalPhys ? m.ullTotalPageFile - m.ullTotalPhys : 0;
    info->freeswap = m.ullAvailPageFile > m.ullAvailPhys ? m.ullAvailPageFile - m.ullAvailPhys : 0;
    info->procs = 1;
    info->mem_unit = 1;
    return 0;
}

long sysconf(int name) {
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    switch (name) {
    case _SC_PAGESIZE:
        return 4096;
    case _SC_CLK_TCK:
        return 100;
    case _SC_NPROCESSORS_CONF:
    case _SC_NPROCESSORS_ONLN:
        return static_cast<long>(si.dwNumberOfProcessors);
    case _SC_PHYS_PAGES: {
        MEMORYSTATUSEX m{};
        m.dwLength = sizeof m;
        GlobalMemoryStatusEx(&m);
        return static_cast<long>(m.ullTotalPhys / 4096);
    }
    default:
        errno = EINVAL;
        return -1;
    }
}

int getrlimit(int resource, struct rlimit* limit) {
    // Large enough not to be in the way: descriptors as the table holds them, a stack as a thread gets one.
    limit->rlim_cur = limit->rlim_max = resource == RLIMIT_NOFILE ? 4096 : resource == RLIMIT_STACK ? 8u << 20 : ~0ull;
    return 0;
}

int setrlimit(int, const struct rlimit*) { return 0; }

int pause() {
    // No signals come to the host process here: a tenth of a second, then the caller's own loop looks again.
    Sleep(100);
    return fail(EINTR);
}

int getrusage(int, struct rusage* usage) {
    std::memset(usage, 0, sizeof *usage);
    FILETIME c, e, k, u;
    GetProcessTimes(GetCurrentProcess(), &c, &e, &k, &u);
    long long user = filetime_ns(u) / 1000, sys = filetime_ns(k) / 1000;
    usage->ru_utime.tv_sec = static_cast<long>(user / 1000000);
    usage->ru_utime.tv_usec = static_cast<long>(user % 1000000);
    usage->ru_stime.tv_sec = static_cast<long>(sys / 1000000);
    usage->ru_stime.tv_usec = static_cast<long>(sys % 1000000);
    return 0;
}

int prctl(int option, ...) {
    va_list ap;
    va_start(ap, option);
    char* name = option == PR_SET_NAME || option == PR_GET_NAME ? va_arg(ap, char*) : nullptr;
    va_end(ap);
    if (option == PR_SET_NAME && name) {
        // The thread's name as Windows keeps it (a debugger's, and /proc's comm here): at most 15 bytes, as Linux's.
        set_thread_name(GetCurrentThread(), wide(std::string(name, strnlen(name, 15))));
        return 0;
    }
    if (option == PR_GET_NAME && name) {
        // Into the caller's 16 bytes, cut where Linux would cut it.
        const std::string have = thread_name(GetCurrentThread());
        std::memset(name, 0, 16);
        std::memcpy(name, have.data(), std::min<std::size_t>(have.size(), 15));
        return 0;
    }
    // The rest are the guest's business: accepted.
    return 0;
}

int kill(int pid, int sig) {
    // Only this process exists for the guest; a signal for it is the runtime's own (Process::send_signal).
    if (pid != getpid() && pid != 0) return fail(ESRCH);
    if (sig == SIGKILL) TerminateProcess(GetCurrentProcess(), 137);
    return 0;
}

int tgkill(int, int, int) { return 0; }

namespace {

// A POSIX TZ offset ("-9", "5:30"): the hours to add to local time for UTC, as Windows' bias in minutes says.
std::string posix_offset(long minutes) {
    char buf[16];
    long a = minutes < 0 ? -minutes : minutes;
    if (a % 60) std::snprintf(buf, sizeof buf, "%s%ld:%02ld", minutes < 0 ? "-" : "", a / 60, a % 60);
    else std::snprintf(buf, sizeof buf, "%s%ld", minutes < 0 ? "-" : "", a / 60);
    return buf;
}

// A name for an offset east of UTC in minutes, as tz names zones without names of their own: <+09>, <-0330>.
std::string offset_name(long east) {
    char buf[16];
    long a = east < 0 ? -east : east;
    if (a % 60) std::snprintf(buf, sizeof buf, "<%c%02ld%02ld>", east < 0 ? '-' : '+', a / 60, a % 60);
    else std::snprintf(buf, sizeof buf, "<%c%02ld>", east < 0 ? '-' : '+', a / 60);
    return buf;
}

// Windows' "nth weekday of a month at an hour" as POSIX's Mm.w.d/h (both count weekdays from Sunday, 5 for the last).
std::string posix_date(const SYSTEMTIME& t) {
    char buf[32];
    std::snprintf(buf, sizeof buf, "M%u.%u.%u/%u", t.wMonth, t.wDay, t.wDayOfWeek, t.wHour);
    return buf;
}

}  // namespace

const char* host_zone() {
    static const std::string zone = [] {
        if (const char* tz = std::getenv("TZ"); tz && *tz) return std::string(tz);
        // ICU's name for Windows' zone ("Asia/Seoul" for "Korea Standard Time"), which the guest finds in its tz file.
        if (HMODULE icu = LoadLibraryW(L"icu.dll")) {
            using Get = std::int32_t (*)(wchar_t*, std::int32_t, int*);
            if (auto get = reinterpret_cast<Get>(GetProcAddress(icu, "ucal_getDefaultTimeZone"))) {
                wchar_t buf[128];
                int status = 0;
                std::int32_t n = get(buf, 128, &status);
                if (status <= 0 && n > 0 && n < 128) return narrow(buf, n);
            }
        }
        // Windows' own rule as POSIX's: the standard offset, and with daylight saving time its offset and dates.
        TIME_ZONE_INFORMATION tz{};
        DWORD kind = GetTimeZoneInformation(&tz);
        long standard = tz.Bias + tz.StandardBias, daylight = tz.Bias + tz.DaylightBias;
        std::string rule = offset_name(-standard) + posix_offset(standard);
        if (kind != TIME_ZONE_ID_UNKNOWN && tz.DaylightDate.wMonth && tz.StandardDate.wMonth && tz.DaylightBias) {
            rule += offset_name(-daylight) + posix_offset(daylight) + "," + posix_date(tz.DaylightDate) + "," + posix_date(tz.StandardDate);
        }
        return rule;
    }();
    return zone.c_str();
}

void interrupt(int thread) {
    std::lock_guard<std::mutex> l(g_threads_lock);
    auto it = interrupts().find(static_cast<DWORD>(thread));
    if (it != interrupts().end()) SetEvent(it->second);
}

// Shared libraries: Windows' DLLs, by their names (a ".so" name asks for the DLL of the same stem).
namespace {
thread_local std::string t_dlerror;
}

void* dlopen(const char* name, int flags) {
    if (!name) return GetModuleHandleW(nullptr);
    std::wstring w = wide(name);
    HMODULE h = (flags & RTLD_NOLOAD) ? GetModuleHandleW(w.c_str()) : LoadLibraryW(w.c_str());
    if (!h) t_dlerror = std::string("cannot load ") + name;
    return h;
}

void* dlsym(void* handle, const char* name) {
    void* f = reinterpret_cast<void*>(GetProcAddress(static_cast<HMODULE>(handle), name));
    if (!f) t_dlerror = std::string("no ") + name;
    return f;
}

int dlclose(void* handle) { return FreeLibrary(static_cast<HMODULE>(handle)) ? 0 : -1; }

char* dlerror() {
    static thread_local std::string last;
    if (t_dlerror.empty()) return nullptr;
    last.swap(t_dlerror);
    t_dlerror.clear();
    return last.data();
}

}  // namespace arm32::posix

// ---------------------------------------------------------------------------------------------------------------------
// System calls by number, as the runtime makes some of them (syscall), and the ones a guest signal may cut short
// (arm32_isys). Kernel-style results: the value, or -errno.

namespace {

// A libc-style result (-1 and errno) as a kernel-style one.
long k(long r) { return r < 0 ? -errno : r; }

// A sched_getaffinity mask of every processor this computer has.
long affinity(std::size_t size, void* mask) {
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    std::size_t bytes = std::min<std::size_t>(size, 128);
    std::memset(mask, 0, bytes);
    for (DWORD c = 0; c < si.dwNumberOfProcessors && c / 8 < bytes; ++c) static_cast<std::uint8_t*>(mask)[c / 8] |= static_cast<std::uint8_t>(1u << (c % 8));
    return static_cast<long>(bytes);
}

long dispatch(long nr, std::intptr_t a0, std::intptr_t a1, std::intptr_t a2, std::intptr_t a3, std::intptr_t a4, std::intptr_t a5) {
    auto P = [](std::intptr_t v) { return reinterpret_cast<void*>(v); };
    auto I = [](std::intptr_t v) { return static_cast<int>(v); };
    switch (nr) {
    case __NR_futex:
        return futex(static_cast<std::uint32_t*>(P(a0)), I(a1), static_cast<std::uint32_t>(a2), static_cast<const struct timespec*>(P(a3)),
                     static_cast<std::uint32_t*>(P(a4)), static_cast<std::uint32_t>(a5));
    case __NR_read:
        return k(arm32::posix::read(I(a0), P(a1), static_cast<std::size_t>(a2)));
    case __NR_write:
        return k(arm32::posix::write(I(a0), P(a1), static_cast<std::size_t>(a2)));
    case __NR_readv:
        return k(arm32::posix::readv(I(a0), static_cast<const struct iovec*>(P(a1)), I(a2)));
    case __NR_writev:
        return k(arm32::posix::writev(I(a0), static_cast<const struct iovec*>(P(a1)), I(a2)));
    case __NR_pread64:
        return k(arm32::posix::pread(I(a0), P(a1), static_cast<std::size_t>(a2), a3));
    case __NR_pwrite64:
        return k(arm32::posix::pwrite(I(a0), P(a1), static_cast<std::size_t>(a2), a3));
    case __NR_fcntl:
        return k(arm32::posix::fcntl(I(a0), I(a1), a2));
    case __NR_flock:
        return k(arm32::posix::flock(I(a0), I(a1)));
    case __NR_getdents64:
        return k(arm32::posix::getdents64(I(a0), P(a1), static_cast<std::size_t>(a2)));
    case __NR_getcwd: {
        // The call writes into the caller's buffer: none is EFAULT, as the kernel answers.
        if (!a0) return -EFAULT;
        char* r = arm32::posix::getcwd(static_cast<char*>(P(a0)), static_cast<std::size_t>(a1));
        return r ? static_cast<long>(std::strlen(r) + 1) : -errno;
    }
    case __NR_memfd_create:
        return k(arm32::posix::memfd_create(static_cast<const char*>(P(a0)), static_cast<unsigned int>(a1)));
    case __NR_ppoll:
        return k(arm32::posix::ppoll(static_cast<struct pollfd*>(P(a0)), static_cast<nfds_t>(a1), static_cast<const struct timespec*>(P(a2)), P(a3)));
    case __NR_pselect6: {
        // The timeout is a timespec here, and Linux's call writes back what is left of it, which select's callers read.
        auto* ts = static_cast<struct timespec*>(P(a4));
        struct timeval tv {};
        long long deadline = 0;
        if (ts) {
            tv.tv_sec = static_cast<long>(ts->tv_sec);
            tv.tv_usec = static_cast<long>(ts->tv_nsec / 1000);
            deadline = monotonic_ns() + static_cast<long long>(ts->tv_sec) * 1000000000LL + ts->tv_nsec;
        }
        long r = k(arm32::posix::select(I(a0), static_cast<fd_set*>(P(a1)), static_cast<fd_set*>(P(a2)), static_cast<fd_set*>(P(a3)), ts ? &tv : nullptr));
        if (ts) {
            long long left = std::max(0LL, deadline - monotonic_ns());
            ts->tv_sec = static_cast<time_t>(left / 1000000000LL);
            ts->tv_nsec = static_cast<long>(left % 1000000000LL);
        }
        return r;
    }
    case __NR_epoll_pwait:
        return k(arm32::posix::epoll_wait(I(a0), static_cast<struct epoll_event*>(P(a1)), I(a2), I(a3)));
    case __NR_connect:
        return k(arm32::posix::connect(I(a0), static_cast<const struct sockaddr*>(P(a1)), static_cast<socklen_t>(a2)));
    case __NR_accept4:
        return k(arm32::posix::accept4(I(a0), static_cast<struct sockaddr*>(P(a1)), static_cast<socklen_t*>(P(a2)), I(a3)));
    case __NR_sendto:
        return k(arm32::posix::sendto(I(a0), P(a1), static_cast<std::size_t>(a2), I(a3), static_cast<const struct sockaddr*>(P(a4)),
                                      static_cast<socklen_t>(a5)));
    case __NR_recvfrom:
        return k(arm32::posix::recvfrom(I(a0), P(a1), static_cast<std::size_t>(a2), I(a3), static_cast<struct sockaddr*>(P(a4)),
                                        static_cast<socklen_t*>(P(a5))));
    case __NR_sendmsg:
        return k(arm32::posix::sendmsg(I(a0), static_cast<const struct msghdr*>(P(a1)), I(a2)));
    case __NR_recvmsg:
        return k(arm32::posix::recvmsg(I(a0), static_cast<struct msghdr*>(P(a1)), I(a2)));
    case __NR_nanosleep: {
        long r = arm32_nanosleep(static_cast<const struct timespec*>(P(a0)), static_cast<struct timespec*>(P(a1)));
        return r < 0 ? -errno : 0;
    }
    case __NR_clock_nanosleep:
        // Returns the error itself, as Linux's call does.
        return -arm32_clock_nanosleep(I(a0), I(a1), static_cast<const struct timespec*>(P(a2)), static_cast<struct timespec*>(P(a3)));
    case __NR_getrandom: {
        // The system's own random numbers (RtlGenRandom), its function looked up once: the library stays loaded for
        // the run, as every call needs it.
        using Generate = BOOLEAN(WINAPI*)(PVOID, ULONG);
        static const Generate gen = [] {
            HMODULE lib = LoadLibraryW(L"advapi32.dll");
            return lib ? reinterpret_cast<Generate>(reinterpret_cast<void*>(GetProcAddress(lib, "SystemFunction036"))) : nullptr;
        }();
        auto* p = static_cast<std::uint8_t*>(P(a0));
        std::size_t n = static_cast<std::size_t>(a1);
        if (!gen || !gen(p, static_cast<ULONG>(n))) return -EIO;
        return static_cast<long>(n);
    }
    case __NR_getcpu: {
        if (a0) *static_cast<unsigned*>(P(a0)) = GetCurrentProcessorNumber();
        if (a1) *static_cast<unsigned*>(P(a1)) = 0;
        return 0;
    }
    case __NR_sched_getaffinity:
        return affinity(static_cast<std::size_t>(a1), P(a2));
    case __NR_sched_setaffinity:
    case __NR_sched_setparam:
    case __NR_sched_setscheduler:
        return 0;
    case __NR_sched_getscheduler:
        return 0;
    case __NR_sched_getparam:
        if (a1) *static_cast<int*>(P(a1)) = 0;
        return 0;
    case __NR_getpriority:
        return 20;
    case __NR_prlimit64: {
        // Read only: the limits as getrlimit gives them.
        if (a3) return k(arm32::posix::getrlimit(I(a1), static_cast<struct rlimit*>(P(a3))));
        return 0;
    }
    case __NR_inotify_init1:
    case __NR_inotify_add_watch:
    case __NR_inotify_rm_watch:
        // No file system watches on this host.
        return -ENOSYS;
    default:
        return -ENOSYS;
    }
}

// What arm32_isys reads, as syscalls.cpp lays it out.
struct IsysGate {
    const std::atomic<std::uint64_t>* pending;
    std::uint64_t blocked;
    long nr;
};

}  // namespace

namespace arm32::posix {

long syscall(long nr, ...) {
    va_list ap;
    va_start(ap, nr);
    std::intptr_t a[6];
    // Every argument as a pointer-wide value: an int's upper half is garbage, which each call's own cast drops.
    for (auto& v : a) v = va_arg(ap, std::intptr_t);
    va_end(ap);
    long r = dispatch(nr, a[0], a[1], a[2], a[3], a[4], a[5]);
    if (r < 0 && r > -4096) {
        errno = static_cast<int>(-r);
        return -1;
    }
    return r;
}

}  // namespace arm32::posix

// A system call for a guest thread that a guest signal can cut short: a signal ready already means no call (-EINTR);
// one sent while it waits sets the thread's interrupt event, which every wait of the layer's waits on as well.
extern "C" std::intptr_t arm32_isys(std::intptr_t a0, std::intptr_t a1, std::intptr_t a2, std::intptr_t a3, std::intptr_t a4, std::intptr_t a5,
                                   const IsysGate* gate) {
    HANDLE interrupt;
    {
        // The event of this thread, made if it has none yet; reset before the check, so that an interrupt sent after
        // the check stays set for the wait.
        thread_event();
        std::lock_guard<std::mutex> l(g_threads_lock);
        interrupt = interrupts()[GetCurrentThreadId()];
    }
    ResetEvent(interrupt);
    if (gate->pending->load() & ~gate->blocked) return -EINTR;
    t_interruptible = true;
    long r = dispatch(gate->nr, a0, a1, a2, a3, a4, a5);
    t_interruptible = false;
    return r;
}
