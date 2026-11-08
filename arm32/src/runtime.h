// arm32 runtime: runs a 32-bit ARM Android program inside a 64-bit process.
//
// The guest is a normal ARM32 Linux user-space process as far as its own code can tell: it gets
// a 4 GB address space, the real 32-bit Android dynamic linker and C library, and the ARM EABI
// system call interface. Underneath, Dynarmic translates its instructions to host code, guest
// memory is a 4 GB block of host address space, and every system call is carried out by the
// host kernel after its arguments are converted from the 32-bit to the 64-bit layout.
#pragma once

#include "host.h"

#include <array>
#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace arm32 {

// A guest (32-bit) address.
using gaddr = std::uint32_t;

// ARM32 Linux uses 4 KB pages, whatever the host uses (16 KB on some new phones).
constexpr std::uint32_t kPageSize = 4096;
constexpr std::uint32_t kPageShift = 12;
constexpr std::size_t kPageCount = std::size_t{1} << (32 - kPageShift);

// Round down / up to a guest page boundary.
constexpr std::uint64_t page_down(std::uint64_t v) { return v & ~std::uint64_t{kPageSize - 1}; }
constexpr std::uint64_t page_up(std::uint64_t v) { return (v + kPageSize - 1) & ~std::uint64_t{kPageSize - 1}; }

// Protection bits as the guest passes them (same values as PROT_READ/WRITE/EXEC on Linux).
enum : int { kProtRead = 1, kProtWrite = 2, kProtExec = 4 };

// mmap places nothing below this address unless the guest asks for that exact address
// (MAP_FIXED): the graphics bridge takes smaller non-zero pointer arguments for offsets into GL
// buffers, so a guest buffer down there would reach the host as a raw low address.
constexpr gaddr kLowestGuestPointer = 0x08000000;

// One guest mapping, as /proc/self/maps would list it.
struct Vma {
    gaddr end = 0;            // one past the last byte
    int prot = 0;             // kProt* bits
    std::string name;         // file path or [stack]-style label, empty for anonymous memory
    std::uint64_t offset = 0; // file offset of the first byte
};

// The guest's 4 GB address space.
class Memory {
public:
    // Reserves the host address range. False if the host has no 4 GB hole left.
    bool init();

    // Host address of guest address g. Every guest address has one, mapped or not.
    std::uint8_t* host(gaddr g) const { return base_ + g; }
    template <class T>
    T* ptr(gaddr g) const { return reinterpret_cast<T*>(base_ + g); }
    std::uint8_t* base() const { return base_; }

    // mmap semantics. With fixed set the range is replaced; otherwise a free range is chosen,
    // near hint when possible. Returns the guest address, or a negative errno.
    std::int64_t map(gaddr hint, std::uint32_t length, int prot, bool fixed, const std::string& name,
                     std::uint64_t offset = 0);
    int unmap(gaddr addr, std::uint32_t length);
    int protect(gaddr addr, std::uint32_t length, int prot);
    // mremap with MREMAP_MAYMOVE; returns the new address or a negative errno.
    std::int64_t remap(gaddr old_addr, std::uint32_t old_len, std::uint32_t new_len, bool may_move);

    // True when every page of [addr, addr + length) is mapped readable.
    bool readable(gaddr addr, std::uint32_t length) const;
    // True when every page of [addr, addr + length) belongs to some mapping, inaccessible ones
    // (PROT_NONE) included, as mincore and madvise see it.
    bool mapped(gaddr addr, std::uint32_t length) const;
    // madvise(MADV_DONTNEED): anonymous memory in the range reads as zero afterwards and its host
    // pages go back to the system; memory copied from a file keeps the file's contents. 0 or a
    // negative errno.
    int discard(gaddr addr, std::uint32_t length);

    // Guest PROT_NONE pages are made inaccessible on the host as well (whole host pages): with
    // fastmem, translated code reaches memory without the page table, and a guard page that the
    // host leaves readable would let a stack overflow run on into the mapping below. Set before
    // anything is mapped.
    bool host_guards = false;

    // Text of /proc/self/maps for the guest.
    std::string maps_text() const;
    // "file+offset" for an address in executable guest memory, empty for anything else.
    std::string code_location(gaddr addr) const;
    // True when [addr, addr + length) lies in one executable, non-writable mapping of a file:
    // code and the constants beside it, which nothing writes once loaded.
    bool constant_code(gaddr addr, std::uint32_t length) const;

    // Page table in Dynarmic's "absolute offset" form: base_ for an accessible page, null otherwise.
    std::array<std::uint8_t*, kPageCount>* page_table() { return page_table_.get(); }

    // Program break, for brk().
    gaddr brk_start = 0;
    gaddr brk_end = 0;

    // Called with (address, length) whenever code may have changed there, so JIT caches drop it.
    void (*on_code_change)(gaddr, std::uint32_t) = nullptr;

private:
    std::int64_t find_free(gaddr hint, std::uint32_t length) const;
    void commit(gaddr start, gaddr end);
    void release(gaddr start, gaddr end);
    void set_access(gaddr start, gaddr end, bool accessible);
    // With host_guards: the host protection of every host page under [start, end) follows its
    // guest pages, open when any of them is accessible, closed (contents kept) when none is.
    void sync_host_access(gaddr start, gaddr end);
    void set_host(std::size_t first, std::size_t last, int prot, std::uint8_t state);
    bool host_page_in_use(std::size_t hp) const;
    void insert(gaddr start, Vma vma);
    void erase(gaddr start, gaddr end);

    std::uint8_t* base_ = nullptr;
    std::size_t host_page_ = 4096;
    std::map<gaddr, Vma> vmas_;  // keyed by start address, never overlapping
    std::unique_ptr<std::array<std::uint8_t*, kPageCount>> page_table_;
    // One state per host page of the reservation: released (no access, no contents), open (read
    // and write) or closed (no access, contents kept: every guest page in it is PROT_NONE).
    enum : std::uint8_t { kHostReleased = 0, kHostOpen = 1, kHostClosed = 2 };
    std::vector<std::uint8_t> committed_;
    mutable std::recursive_mutex lock_;
};

class Thread;

// A guest thread clone as the parent's svc made it: the child's registers (clone returning 0 is
// applied by whoever runs it), its stack, thread pointer and flags.
struct CloneState {
    std::array<std::uint32_t, 16> regs{};
    std::array<std::uint32_t, 64> ext{};
    std::uint32_t cpsr = 0, fpscr = 0, tls = 0;
    std::uint64_t sigmask = 0;
    std::uint32_t flags = 0;
    gaddr ptid = 0, ctid = 0;
};

// Process-wide state shared by every guest thread.
struct Process {
    Memory mem;
    std::string sysroot;   // host folder with bin/linker and lib/*.so of the guest
    std::string exe_path;  // what /proc/self/exe reads as
    std::vector<std::string> argv;
    std::vector<std::string> envp;
    std::atomic<bool> exiting{false};
    // Faster floating point: NaN payloads and FPSCR corner cases are not reproduced exactly.
    bool fast_fp = false;
    // Track the FPSCR cumulative exception flags. Off by default: results are the same, only
    // the sticky flags (which Android code does not read) stay clear, and reading the host FPSR
    // at every translated block made float loops 2.7 times slower.
    bool fp_flags = false;
    // NEON float instructions run under the guest's FPSCR instead of switching the host FPCR to
    // the ASIMD standard value (flush-to-zero, default NaN) around each one: two FPCR writes per
    // instruction otherwise. Only denormals and NaN payloads can come out differently.
    bool fast_neon = false;
    // Exclusive loads and stores (LDREX/STREX) without the monitor lock all threads share: the
    // store is a compare-and-swap against the value the load saw, as in QEMU's user mode. With the
    // lock, a thread preempted while holding it stalls every other thread's atomics at once.
    bool fast_atomics = false;
    // Guest memory accesses without the page table lookup.
    bool fastmem = false;
    // The most CPUs the guest is told of (/proc/cpuinfo, /sys/devices/system/cpu, its affinity); 0 for the host's own.
    // A game sizes its worker threads by them: on a computer with many cores, Unity's job system made thirty-one, and
    // the main thread spent most of its time waking them all (on a virtual machine each wake-up is costly).
    int max_cpus = 0;
    std::atomic<int> exit_code{0};

    // Signal dispositions set by rt_sigaction (handler, flags, restorer, mask), per signal 1..64.
    struct SigAction {
        std::uint32_t handler = 0;
        std::uint32_t flags = 0;
        std::uint32_t restorer = 0;
        std::uint64_t mask = 0;
    };
    std::array<SigAction, 65> sigactions{};
    std::mutex sig_lock;

    // Offered every thread clone first; returns the new thread's id if it took the clone, or 0
    // to have it run on a new host thread as usual.
    int (*clone_hook)(Process&, const CloneState&) = nullptr;

    // Live guest threads by host thread id.
    std::map<int, Thread*> threads;
    std::mutex threads_lock;

    // The process id the guest's C library works with, 0 when it is the host's. The library takes
    // its main thread's id for the process id at start-up, and in an app the main thread is the
    // agent's own host thread, not the host process's. Calls naming this process (kill,
    // /proc/<pid>/) accept both.
    std::atomic<int> guest_pid{0};

    // Maps a guest path to the host path to open (sysroot redirection, virtual /proc files).
    std::string host_path(const std::string& guest_path) const;
    // In an app the guest's files live under other names: path_hook replaces host_path's
    // mapping, name_hook turns a host file name back into the one the guest knows.
    std::function<std::string(const std::string&)> path_hook;
    std::function<std::string(const std::string&)> name_hook;
    std::string guest_name(const std::string& host) const { return name_hook ? name_hook(host) : host; }

    // Sends signal sig to guest thread tid (or, with tid 0, to any thread that does not block
    // it). Returns 0 or a negative errno.
    int send_signal(int tid, int sig);
};

// Loads the executable and its interpreter, builds the initial stack and returns the entry state.
struct EntryState {
    gaddr pc = 0;
    gaddr sp = 0;
    bool thumb = false;
};
bool load_program(Process& proc, EntryState& entry, std::string& error);

// Runs ARM EABI system call `number` for thread t; returns the value for r0.
std::uint32_t do_syscall(Thread& t, std::uint32_t number);

// Host signal used to interrupt a guest thread blocked in a host system call.
constexpr int kInterruptSignal = 23;  // SIGURG: ignored by default, unused by Android runtimes
// Installs the handler of kInterruptSignal (no SA_RESTART, so blocked calls return EINTR).
void install_interrupt_handler();

// Signal tracing, on when ARM32_TRACE is set in the environment.
extern bool g_trace;


// With stats on, called after each audio mix that started at `start` (FMOD's fmodProcess, which
// fills one whole buffer for AudioTrack.write, or an OpenSL buffer queue callback): how long it
// took, and how long since the one before.
void note_audio(std::chrono::steady_clock::time_point start);
// With stats on, called for each guest system call: the stats name the busiest numbers.
void note_syscall(std::uint32_t number);
// Called when a guest thread sends signal sig to another: with stats on, times the garbage
// collector's stop-the-world (its suspend and resume signals).
void note_signal(int sig);
// Logs, for every guest thread, the system call or host function it is in, its registers and
// the code addresses found on its stack.
void dump_threads(Process& proc);
// Starts what tracing and stats ask for: with either, a host thread that runs dump_threads once
// whenever no frame was presented for eight seconds (thirty before the first one); with stats, a host
// thread logging frames per second and, per guest thread, CPU use and call counts.
void start_diagnostics(Process& proc);


}  // namespace arm32
