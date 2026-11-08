// Diagnostics for apps: a hang dump and performance counters.
//
// Hang dump: a host-side stack (debuggerd) of a stuck app only shows guest threads sitting in
// the runtime's system call code. This adds the guest view: the call each thread is in, its
// registers, and the code addresses left on its guest stack, as library+offset for objdump.
//
// Stats: frames per second, and per guest thread the CPU it used and the system calls, host
// calls and JNI native calls it made, every five seconds, to see where an app's time goes. Also
// the smoothness: the intervals between swaps, between frames reaching the screen (when the
// device reports it), and the collector's pauses.
#include "thread.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace arm32 {

std::atomic<std::uint64_t> g_frames{0};

namespace {

// Frame intervals and garbage collector pauses since the last stats report.
std::mutex g_timing_lock;
std::vector<float> g_frame_ms;            // intervals between presented frames
std::vector<float> g_shown_ms;            // intervals between frames reaching the screen
std::size_t g_shown_late = 0;             // paced frames shown later than asked
std::vector<float> g_mix_ms;              // audio mixes: how long each took
std::vector<float> g_mix_period_ms;       // audio mixes: time since the one before
std::chrono::steady_clock::time_point g_last_frame;
std::chrono::steady_clock::time_point g_gc_start;
bool g_gc_open = false;
std::vector<float> g_gc_ms;               // stop-the-world pauses

double ms_since(std::chrono::steady_clock::time_point t) {
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t).count();
}

// The value at fraction q of the sorted samples.
float percentile(std::vector<float>& v, double q) {
    if (v.empty()) return 0;
    std::size_t i = std::min(v.size() - 1, static_cast<std::size_t>(q * static_cast<double>(v.size())));
    std::nth_element(v.begin(), v.begin() + static_cast<std::ptrdiff_t>(i), v.end());
    return v[i];
}

}  // namespace

void note_frame() {
    ++g_frames;
    if (!g_stats) return;
    std::lock_guard<std::mutex> g(g_timing_lock);
    auto now = std::chrono::steady_clock::now();
    if (g_last_frame.time_since_epoch().count()) {
        g_frame_ms.push_back(static_cast<float>(std::chrono::duration<double, std::milli>(now - g_last_frame).count()));
    }
    g_last_frame = now;
}

void note_shown(float interval_ms, bool late) {
    std::lock_guard<std::mutex> g(g_timing_lock);
    g_shown_ms.push_back(interval_ms);
    if (late) ++g_shown_late;
}

namespace {
// Guest system calls by number since the start (EABI numbers; the ARM private ones, 0xf0000 and
// up, in the last 256 slots).
constexpr std::size_t kSyscallSlots = 1024;
std::array<std::atomic<std::uint64_t>, kSyscallSlots> g_syscall_counts{};

std::size_t syscall_slot(std::uint32_t number) {
    return number >= 0xf0000 ? kSyscallSlots - 256 + (number & 0xff) : std::min<std::size_t>(number, kSyscallSlots - 257);
}

// Names of the calls a Unity game makes most, for the stats line.
const char* syscall_name(std::size_t slot) {
    switch (slot) {
    case 3: return "read";
    case 4: return "write";
    case 54: return "ioctl";
    case 78: return "gettimeofday";
    case 142: return "select";
    case 158: return "sched_yield";
    case 162: return "nanosleep";
    case 168: return "poll";
    case 175: return "rt_sigprocmask";
    case 224: return "gettid";
    case 240: return "futex";
    case 263: return "clock_gettime";
    case 265: return "clock_nanosleep";
    case 336: return "ppoll";
    case 0x5: return "set_tls";
    default: return slot >= kSyscallSlots - 256 ? "arm" : nullptr;
    }
}
}  // namespace

void note_syscall(std::uint32_t number) { g_syscall_counts[syscall_slot(number)].fetch_add(1, std::memory_order_relaxed); }

void note_audio(std::chrono::steady_clock::time_point start) {
    auto now = std::chrono::steady_clock::now();
    // The gap since this thread's last mix: each audio thread (Unity's player, FMOD's output)
    // mixes its own stream, and a gap over a second is a pause, not a stall.
    thread_local std::chrono::steady_clock::time_point last{};
    const double gap = last.time_since_epoch().count() ? std::chrono::duration<double, std::milli>(start - last).count() : -1;
    last = start;
    std::lock_guard<std::mutex> g(g_timing_lock);
    g_mix_ms.push_back(static_cast<float>(std::chrono::duration<double, std::milli>(now - start).count()));
    if (gap >= 0 && gap < 1000) g_mix_period_ms.push_back(static_cast<float>(gap));
}

void note_signal(int sig) {
    // The IL2CPP collector (Boehm) stops threads with SIGPWR and lets them go with SIGXCPU.
    std::lock_guard<std::mutex> g(g_timing_lock);
    if (sig == SIGPWR && !g_gc_open) {
        g_gc_open = true;
        g_gc_start = std::chrono::steady_clock::now();
    } else if (sig == SIGXCPU && g_gc_open) {
        g_gc_open = false;
        g_gc_ms.push_back(static_cast<float>(ms_since(g_gc_start)));
    }
}

namespace {

// The first line of a file of /proc, through open and read: on Windows the layer makes these files, which the C
// library's own file functions would not find.
std::string proc_read(const std::string& path) {
    int fd = open(path.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) return {};
    char buf[1024];
    ssize_t n = read(fd, buf, sizeof buf - 1);
    close(fd);
    return n > 0 ? std::string(buf, static_cast<std::size_t>(n)) : std::string();
}

// The host thread's name (guest threads name themselves with prctl, which reaches the host).
std::string thread_name(int tid) {
    std::string name = proc_read("/proc/self/task/" + std::to_string(tid) + "/comm");
    return name.substr(0, name.find('\n'));
}

void dump_thread(Process& p, Thread& t) {
    std::uint32_t what = t.busy.load(std::memory_order_relaxed);
    const auto& a = t.busy_args;
    const auto& r = t.regs();
    char doing[96];
    if (what & Thread::kBusySyscall)
        std::snprintf(doing, sizeof doing, "syscall %u(%#x, %#x, %#x, %#x, %#x, %#x)", what & ~Thread::kBusySyscall, a[0], a[1], a[2], a[3], a[4], a[5]);
    else if (what & Thread::kBusyHost)
        std::snprintf(doing, sizeof doing, "host function %#x(%#x, %#x, %#x, %#x)", what & ~Thread::kBusyHost, a[0], a[1], a[2], a[3]);
    else
        std::snprintf(doing, sizeof doing, "guest code");
    log("hang: %d %s: %s", t.tid, thread_name(t.tid).c_str(), doing);
    // pc is right after the svc (inside the C library's wrapper); lr usually names its caller.
    log("hang:   pc %#x %s, lr %#x %s, sp %#x", r[15], p.mem.code_location(r[15]).c_str(), r[14],
        p.mem.code_location(r[14]).c_str(), r[13]);
    // Return addresses are among the words above sp: list the ones pointing into code.
    std::string found;
    int count = 0;
    for (gaddr at = r[13]; count < 24 && at - r[13] < 8192 && p.mem.readable(at, 4); at += 4) {
        std::string where = p.mem.code_location(*p.mem.ptr<std::uint32_t>(at));
        if (where.empty()) continue;
        found += " " + where;
        ++count;
    }
    log("hang:   stack:%s", found.c_str());
}

}  // namespace

void dump_threads(Process& p) {
    std::lock_guard<std::mutex> g(p.threads_lock);
    log("hang: %zu guest threads, %llu frames presented", p.threads.size(),
        static_cast<unsigned long long>(g_frames.load()));
    for (auto& [tid, t] : p.threads) dump_thread(p, *t);
}

namespace {

// CPU time a host thread (or, with tid 0, the whole process) has used: user plus system, in
// clock ticks, from /proc.
std::uint64_t cpu_ticks(int tid) {
    char path[64];
    if (tid) std::snprintf(path, sizeof path, "/proc/self/task/%d/stat", tid);
    else std::snprintf(path, sizeof path, "/proc/self/stat");
    const std::string text = proc_read(path);
    if (text.empty()) return 0;
    char buf[1024];
    std::snprintf(buf, sizeof buf, "%s", text.c_str());
    // The fields after the name in parentheses (which may hold spaces): state, then ten
    // numbers, then utime and stime.
    const char* p = std::strrchr(buf, ')');
    if (!p) return 0;
    unsigned long long user = 0, sys = 0;
    std::sscanf(p + 2, "%*c %*d %*d %*d %*d %*d %*u %*u %*u %*u %*u %llu %llu", &user, &sys);
    return user + sys;
}

void stats_loop(Process& p) {
    struct Sample {
        std::uint64_t cpu = 0, syscalls = 0, host = 0, native = 0, exclusive = 0;
    };
    constexpr int kSeconds = 5;
    const double ticks = static_cast<double>(sysconf(_SC_CLK_TCK));
    std::map<int, Sample> last;
    std::uint64_t last_frames = g_frames.load(), last_process = cpu_ticks(0);
    for (;;) {
        std::this_thread::sleep_for(std::chrono::seconds(kSeconds));
        std::uint64_t frames = g_frames.load(), process = cpu_ticks(0);
        // Per guest thread: what it used since the last report.
        struct Row {
            int tid;
            double cpu;
            Sample delta;
        };
        std::vector<Row> rows;
        std::map<int, Sample> now;
        double guest_cpu = 0;
        // The counters are copied under the thread list's lock; the CPU times are read from /proc
        // after it is let go: every signal sent (the collector's stop-the-world sends one to each
        // thread) takes that lock, and fifty file reads held it up for milliseconds.
        {
            std::lock_guard<std::mutex> g(p.threads_lock);
            for (auto& [tid, t] : p.threads) now[tid] = Sample{0, t->n_syscalls, t->n_host_calls, t->n_native_calls, t->n_exclusive};
        }
        for (auto& [tid, s] : now) {
            s.cpu = cpu_ticks(tid);
            // A thread id used again by a new thread starts from zero.
            Sample before = last.count(tid) ? last[tid] : Sample{};
            if (before.cpu > s.cpu || before.syscalls > s.syscalls) before = Sample{};
            Sample d{s.cpu - before.cpu, s.syscalls - before.syscalls, s.host - before.host, s.native - before.native,
                     s.exclusive - before.exclusive};
            double cpu = 100.0 * static_cast<double>(d.cpu) / ticks / kSeconds;
            guest_cpu += cpu;
            if (d.cpu || d.syscalls || d.host || d.native) rows.push_back(Row{tid, cpu, d});
        }
        last = std::move(now);
        std::sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) { return a.cpu > b.cpu; });
        char line[1280];
        int len = std::snprintf(line, sizeof line, "stats: %.1f fps, process %.0f%% CPU, guest threads %.0f%%:",
                                static_cast<double>(frames - last_frames) / kSeconds,
                                100.0 * static_cast<double>(process - last_process) / ticks / kSeconds, guest_cpu);
        // The busiest threads, with their calls per second.
        for (std::size_t i = 0; i < rows.size() && i < 6 && len < static_cast<int>(sizeof line) - 112; ++i) {
            const Row& r = rows[i];
            len += std::snprintf(line + len, sizeof line - static_cast<std::size_t>(len), " %s %.0f%% (%llu sys, %llu host, %llu jni, %llu strex /s);",
                                 thread_name(r.tid).c_str(), r.cpu,
                                 static_cast<unsigned long long>(r.delta.syscalls / kSeconds),
                                 static_cast<unsigned long long>(r.delta.host / kSeconds),
                                 static_cast<unsigned long long>(r.delta.native / kSeconds),
                                 static_cast<unsigned long long>(r.delta.exclusive / kSeconds));
        }
        log("%s", line);
        // Smoothness: frame intervals and collector pauses over the same five seconds.
        std::vector<float> frame_ms, gc_ms, shown_ms, mix_ms, mix_period_ms;
        std::size_t shown_late = 0;
        {
            std::lock_guard<std::mutex> g(g_timing_lock);
            frame_ms.swap(g_frame_ms);
            gc_ms.swap(g_gc_ms);
            shown_ms.swap(g_shown_ms);
            std::swap(shown_late, g_shown_late);
            mix_ms.swap(g_mix_ms);
            mix_period_ms.swap(g_mix_period_ms);
        }
        if (!frame_ms.empty()) {
            std::size_t over33 = static_cast<std::size_t>(std::count_if(frame_ms.begin(), frame_ms.end(), [](float v) { return v > 33.4f; }));
            float gc_total = 0, gc_max = 0;
            for (float v : gc_ms) {
                gc_total += v;
                gc_max = std::max(gc_max, v);
            }
            float p50 = percentile(frame_ms, 0.5), p95 = percentile(frame_ms, 0.95), p99 = percentile(frame_ms, 0.99);
            float max = *std::max_element(frame_ms.begin(), frame_ms.end());
            log("stats: frame ms p50 %.1f p95 %.1f p99 %.1f max %.1f, %zu over 33 ms; GC %zu pauses, %.1f ms total, %.1f ms longest",
                p50, p95, p99, max, over33, gc_ms.size(), gc_total, gc_max);
        }
        if (!shown_ms.empty()) {
            // On screen: an even run has every interval at the median; count those off by more
            // than 2 ms (a refresh early or late).
            float p50 = percentile(shown_ms, 0.5);
            std::size_t uneven = static_cast<std::size_t>(std::count_if(shown_ms.begin(), shown_ms.end(), [p50](float v) { return std::fabs(v - p50) > 2.0f; }));
            float p5 = percentile(shown_ms, 0.05), p95 = percentile(shown_ms, 0.95), p99 = percentile(shown_ms, 0.99);
            float max = *std::max_element(shown_ms.begin(), shown_ms.end());
            log("stats: on screen ms p5 %.1f p50 %.1f p95 %.1f p99 %.1f max %.1f, %zu of %zu uneven, %zu later than asked",
                p5, p50, p95, p99, max, uneven, shown_ms.size(), shown_late);
        }
        if (!mix_ms.empty()) {
            // Audio: each mix fills one buffer (an OpenSL callback, or FMOD's Java loop before
            // AudioTrack.write, which blocks while AudioTrack's buffer is full, so those come in
            // bursts). What matters: how long a mix takes (far below a buffer's playing time), and
            // the longest gap between two mixes (longer than the queued audio means it ran dry).
            float m50 = percentile(mix_ms, 0.5), m99 = percentile(mix_ms, 0.99);
            float mmax = *std::max_element(mix_ms.begin(), mix_ms.end());
            float gap = mix_period_ms.empty() ? 0 : *std::max_element(mix_period_ms.begin(), mix_period_ms.end());
            log("stats: audio mix ms p50 %.2f p99 %.2f max %.2f, %zu mixes, longest gap %.1f ms",
                m50, m99, mmax, mix_ms.size(), gap);
        }
        {
            // The busiest system calls of the last window, per second.
            static std::array<std::uint64_t, kSyscallSlots> last{};
            std::vector<std::pair<std::uint64_t, std::size_t>> busiest;
            for (std::size_t i = 0; i < kSyscallSlots; ++i) {
                std::uint64_t now = g_syscall_counts[i].load(std::memory_order_relaxed);
                if (now > last[i]) busiest.emplace_back(now - last[i], i);
                last[i] = now;
            }
            std::sort(busiest.rbegin(), busiest.rend());
            char line[400];
            int len = std::snprintf(line, sizeof line, "stats: system calls /s:");
            for (std::size_t k = 0; k < busiest.size() && k < 8 && len < static_cast<int>(sizeof line) - 40; ++k) {
                const char* name = syscall_name(busiest[k].second);
                len += std::snprintf(line + len, sizeof line - static_cast<std::size_t>(len), " %s(%zu) %.0f", name ? name : "#",
                                     busiest[k].second, static_cast<double>(busiest[k].first) / kSeconds);
            }
            if (!busiest.empty()) log("%s", line);
        }
        last_frames = frames;
        last_process = process;
    }
}

void hang_watch(Process& p) {
    std::uint64_t last = g_frames.load();
    int still = 0;        // two-second checks without a new frame
    bool dumped = false;  // already dumped during this stall
    for (;;) {
        std::this_thread::sleep_for(std::chrono::seconds(2));
        std::uint64_t now = g_frames.load();
        if (now != last) {
            last = now;
            still = 0;
            dumped = false;
            continue;
        }
        // Before the first frame the app may still be loading: thirty seconds then, not eight.
        if (dumped || ++still < (now == 0 ? 15 : 4)) continue;
        dump_threads(p);
        dumped = true;
    }
}

}  // namespace

void start_diagnostics(Process& p) {
    // The hang watch with stats too: tracing slows every signal down, which can hide the very
    // stall being hunted.
    if (g_trace || g_stats) std::thread(hang_watch, std::ref(p)).detach();
    if (g_stats) std::thread(stats_loop, std::ref(p)).detach();
}

}  // namespace arm32
