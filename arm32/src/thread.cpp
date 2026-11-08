// Guest threads on Dynarmic: memory callbacks for pages outside the page table, CP15 thread
// registers, system calls, and the run loop.
#include "thread.h"

#include <dynarmic/interface/optimization_flags.h>

#include <algorithm>
#include <cerrno>
#include <csignal>
#include <cstring>
#include <ctime>
#include <linux/futex.h>
#include <thread>
#include <unistd.h>

namespace arm32 {

namespace {

// Room for this many guest threads at once in the exclusive monitor.
constexpr std::size_t kMaxProcessors = 256;

thread_local Thread* g_current = nullptr;
// The registers a reentrant host function was called with, on the host thread running it: it
// reads its arguments from this copy, since the live registers may be lent to a helper.
thread_local const std::uint32_t* t_call_regs = nullptr;

std::mutex g_ids_lock;
std::vector<bool> g_ids_used(kMaxProcessors, false);

// Published threads, for invalidate_code to reach every JIT. A lock of its own: invalidate_code
// runs under the memory map's lock, and the hang dump takes that one while holding threads_lock.
std::mutex g_jits_lock;
std::vector<Thread*> g_jits;

// Guest pages some JIT translated code from, one bit per 4 KB page (set in MemoryReadCode, never
// cleared): a change to memory no thread ever ran code from concerns no other thread's cache.
// Most mappings are data, and the memory map reports every one of them.
using PageMap = std::array<std::atomic<std::uint64_t>, kPageCount / 64>;
PageMap g_translated{};
// Code pages a translation folded a constant from (IsReadOnlyMemory, the literal pools): a block
// keeps such a value however far from its own code the page is, so a change there clears whole
// caches rather than ranges.
PageMap g_folded{};

void mark_page(PageMap& map, gaddr vaddr) {
    std::uint32_t page = vaddr >> kPageShift;
    auto& word = map[page / 64];
    std::uint64_t bit = std::uint64_t{1} << (page % 64);
    // Checked first: translation reads every instruction, and the bit is nearly always set already.
    if (!(word.load(std::memory_order_relaxed) & bit)) word.fetch_or(bit, std::memory_order_relaxed);
}

void mark_translated(gaddr vaddr) { mark_page(g_translated, vaddr); }

bool any_page(const PageMap& map, gaddr start, std::uint32_t length) {
    std::uint64_t first = start >> kPageShift;
    std::uint64_t last = (std::uint64_t{start} + length - 1) >> kPageShift;
    for (std::uint64_t page = first; page <= last; ++page) {
        std::uint64_t word = map[page / 64].load(std::memory_order_relaxed);
        // A whole word of pages at once where the range covers it.
        if (page % 64 == 0 && page + 63 <= last) {
            if (word) return true;
            page += 63;
            continue;
        }
        if (word & (std::uint64_t{1} << (page % 64))) return true;
    }
    return false;
}

bool translated(gaddr start, std::uint32_t length) { return any_page(g_translated, start, length); }

// Code ranges a thread keeps queued before dropping its whole cache instead.
constexpr std::size_t kMaxQueuedRanges = 64;

// Generic timer frequency the guest sees through CNTFRQ, and the counter derived from it.
constexpr std::uint32_t kTimerHz = 19'200'000;

std::uint64_t read_counter(void*, std::uint32_t, std::uint32_t) {
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<std::uint64_t>(ts.tv_sec) * kTimerHz + static_cast<std::uint64_t>(ts.tv_nsec) * (kTimerHz / 1'000'000) / 1000;
}

std::uint64_t no_op(void*, std::uint32_t, std::uint32_t) { return 0; }

// Coprocessor 15 as user mode sees it: the two thread ID registers, barriers written the
// ARMv6 way, and the generic timer.
class Cp15 final : public Dynarmic::A32::Coprocessor {
public:
    explicit Cp15(Thread* t) : t_(t) {}
    using CoprocReg = Dynarmic::A32::CoprocReg;

    std::optional<Callback> CompileInternalOperation(bool, unsigned, CoprocReg, CoprocReg, CoprocReg, unsigned) override {
        return std::nullopt;
    }
    CallbackOrAccessOneWord CompileSendOneWord(bool two, unsigned opc1, CoprocReg crn, CoprocReg crm, unsigned opc2) override {
        if (two || opc1 != 0) return std::monostate{};
        // mcr p15, 0, rX, c13, c0, 2: TPIDRURW is writable from user mode.
        if (crn == CoprocReg::C13 && crm == CoprocReg::C0 && opc2 == 2) return &t_->tls_rw;
        // mcr p15, 0, rX, c7, c10, 4/5 and c7, c5, 4: DSB, DMB, ISB in the old encoding.
        if (crn == CoprocReg::C7 && ((crm == CoprocReg::C10 && (opc2 == 4 || opc2 == 5)) || (crm == CoprocReg::C5 && opc2 == 4))) {
            return Callback{&no_op, std::nullopt};
        }
        return std::monostate{};
    }
    CallbackOrAccessTwoWords CompileSendTwoWords(bool, unsigned, CoprocReg) override { return std::monostate{}; }
    CallbackOrAccessOneWord CompileGetOneWord(bool two, unsigned opc1, CoprocReg crn, CoprocReg crm, unsigned opc2) override {
        if (two || opc1 != 0) return std::monostate{};
        // mrc p15, 0, rX, c13, c0, 3 / 2: the thread pointer (TPIDRURO) and TPIDRURW.
        if (crn == CoprocReg::C13 && crm == CoprocReg::C0 && opc2 == 3) return &t_->tls;
        if (crn == CoprocReg::C13 && crm == CoprocReg::C0 && opc2 == 2) return &t_->tls_rw;
        // mrc p15, 0, rX, c14, c0, 0: CNTFRQ.
        if (crn == CoprocReg::C14 && crm == CoprocReg::C0 && opc2 == 0) return &frequency_;
        return std::monostate{};
    }
    CallbackOrAccessTwoWords CompileGetTwoWords(bool two, unsigned opc, CoprocReg crm) override {
        // mrrc p15, 1, rX, rY, c14: CNTVCT, the virtual counter.
        if (!two && opc == 1 && crm == CoprocReg::C14) return Callback{&read_counter, std::nullopt};
        return std::monostate{};
    }
    std::optional<Callback> CompileLoadWords(bool, bool, CoprocReg, std::optional<std::uint8_t>) override { return std::nullopt; }
    std::optional<Callback> CompileStoreWords(bool, bool, CoprocReg, std::optional<std::uint8_t>) override { return std::nullopt; }

private:
    Thread* t_;
    std::uint32_t frequency_ = kTimerHz;
};

}  // namespace

Dynarmic::ExclusiveMonitor& exclusive_monitor() {
    static Dynarmic::ExclusiveMonitor monitor{kMaxProcessors};
    return monitor;
}

std::size_t acquire_processor_id() {
    std::lock_guard<std::mutex> g(g_ids_lock);
    for (std::size_t i = 0; i < kMaxProcessors; ++i) {
        if (!g_ids_used[i]) {
            g_ids_used[i] = true;
            return i;
        }
    }
    log("arm32: more than %zu guest threads", kMaxProcessors);
    abort();
}

void release_processor_id(std::size_t id) {
    std::lock_guard<std::mutex> g(g_ids_lock);
    g_ids_used[id] = false;
}

Thread* current_thread() { return g_current; }

Thread::Thread(Process& p, int id) : proc(p), tid(id), processor_id_(acquire_processor_id()) {
    Dynarmic::A32::UserConfig config;
    config.callbacks = this;
    // Guest memory through the page table: host address = base + guest address.
    config.page_table = proc.mem.page_table();
    config.absolute_offset_page_table = true;
    // Faster: translated loads and stores go straight to base + address; the host's fault on an
    // unmapped page sends that access back through the callbacks.
    if (proc.fastmem) config.fastmem_pointer = reinterpret_cast<std::uintptr_t>(proc.mem.base());
    // LDREX/STREX pairs must see each other across threads.
    config.global_monitor = &exclusive_monitor();
    config.processor_id = processor_id_;
    config.coprocessors[15] = std::make_shared<Cp15>(this);
    // A user-mode process has no notion of cycles; run until halted.
    config.enable_cycle_counting = false;
    // Unpredictable encodings behave like common hardware instead of stopping the guest.
    config.define_unpredictable_behaviour = true;
    if (!proc.fp_flags) {
        config.unsafe_optimizations = true;
        config.optimizations |= Dynarmic::OptimizationFlag::Unsafe_IgnoreFPSR;
    }
    if (proc.fast_atomics) {
        config.unsafe_optimizations = true;
        config.optimizations |= Dynarmic::OptimizationFlag::Unsafe_IgnoreGlobalMonitor;
        // x86-64 backend: inline compare-and-swap through fastmem.
        if (proc.fastmem) config.fastmem_exclusive_access = true;
    }
    if (proc.fast_neon) {
        config.unsafe_optimizations = true;
        config.optimizations |= Dynarmic::OptimizationFlag::Unsafe_IgnoreStandardFPCRValue;
    }
    if (proc.fast_fp) {
        config.unsafe_optimizations = true;
        config.optimizations |= Dynarmic::OptimizationFlag::Unsafe_UnfuseFMA | Dynarmic::OptimizationFlag::Unsafe_ReducedErrorFP |
                                Dynarmic::OptimizationFlag::Unsafe_InaccurateNaN | Dynarmic::OptimizationFlag::Unsafe_IgnoreStandardFPCRValue;
    }
    // Translated code per thread; most threads run little code.
    config.code_cache_size = 64 * 1024 * 1024;
    jit_ = std::make_unique<Dynarmic::A32::Jit>(config);
    // Not listed in proc.threads yet: publish() does that once the caller has set the state.
}

void Thread::publish() {
    {
        std::lock_guard<std::mutex> g(proc.threads_lock);
        proc.threads[tid] = this;
    }
    std::lock_guard<std::mutex> g(g_jits_lock);
    g_jits.push_back(this);
}

Thread::~Thread() {
    {
        std::lock_guard<std::mutex> g(proc.threads_lock);
        // Only this thread's own entry: its id may name a newer thread by now.
        auto it = proc.threads.find(tid);
        if (it != proc.threads.end() && it->second == this) proc.threads.erase(it);
    }
    {
        // No more invalidations queued here: the JIT goes away with this object.
        std::lock_guard<std::mutex> g(g_jits_lock);
        g_jits.erase(std::remove(g_jits.begin(), g_jits.end(), this), g_jits.end());
    }
    // Nobody can signal the thread any more; wait for a helper that is still on its way out.
    while (helpers_.load()) std::this_thread::yield();
    release_processor_id(processor_id_);
}

namespace {

// Host functions by number: the two ranges in tables, the runtime's own traps in a map.
std::array<HostFn, kHostRange> g_host_fns{};
std::array<HostFn, kHostRange> g_reentrant_fns{};
std::mutex g_other_fns_lock;
std::map<std::uint32_t, HostFn> g_other_fns;

HostFn find_other_fn(std::uint32_t number) {
    std::lock_guard<std::mutex> g(g_other_fns_lock);
    auto it = g_other_fns.find(number);
    return it == g_other_fns.end() ? nullptr : it->second;
}

}  // namespace

void register_host_fn(std::uint32_t number, HostFn fn) {
    if (number >= kHostBase && number < kHostBase + kHostRange) g_host_fns[number - kHostBase] = fn;
    else if (number >= kReentrantBase && number < kReentrantBase + kHostRange) g_reentrant_fns[number - kReentrantBase] = fn;
    else {
        std::lock_guard<std::mutex> g(g_other_fns_lock);
        g_other_fns[number] = fn;
    }
}

std::uint32_t Thread::call_reg(unsigned n) {
    return t_call_regs ? t_call_regs[n] : jit_->Regs()[n];
}

std::uint32_t Thread::arg(unsigned i) {
    if (i < 4) return call_reg(i);
    gaddr at = call_reg(13) + 8 + (i - 4) * 4;
    if (!proc.mem.readable(at, 4)) fatal("bad stack argument", at);
    return *proc.mem.ptr<std::uint32_t>(at);
}

void Thread::after_run() {
    if (pending_host_) {
        std::uint32_t number = pending_host_;
        pending_host_ = 0;
        HostFn fn = g_reentrant_fns[number - kReentrantBase];
        ++n_host_calls;
        mark_busy(kBusyHost | number);
        // The function reads its arguments from a copy of the registers: while it runs the
        // thread is detached, and a helper may borrow the registers for a signal handler (and
        // put them back before this thread can take the guest context again).
        std::array<std::uint32_t, 16> regs = jit_->Regs();
        const std::uint32_t* outer_regs = t_call_regs;
        t_call_regs = regs.data();
        // A helper running a handler keeps the guest context until the handler returns.
        bool detach = !in_helper_;
        if (detach) leave_guest();
        std::uint64_t v = fn(*this);
        if (detach) enter_guest();
        t_call_regs = outer_regs;
        busy.store(0, std::memory_order_relaxed);
        jit_->Regs()[0] = static_cast<std::uint32_t>(v);
        jit_->Regs()[1] = static_cast<std::uint32_t>(v >> 32);
    }
    // Halted: maybe because another thread sent a signal.
    while (!exited && deliver_signal()) {
    }
}

void Thread::run() {
    enter_guest();
    Thread* outer = g_current;
    g_current = this;
    const std::uint32_t* outer_regs = t_call_regs;
    t_call_regs = nullptr;
    host_thread = pthread_self();
    while (!exited && !proc.exiting.load() && !parked) {
        run_jit();
        // The park trap ends this run for good (the host thread goes back to Java): a signal frame
        // built now would never be run, and the signal would stay blocked in the mask, never to be
        // acknowledged. leave_guest() below hands a pending signal to a helper instead, which runs
        // the handler to its sigreturn. (The trap is not a reentrant host function, so after_run()
        // has nothing else to do here.)
        if (parked) break;
        after_run();
    }
    t_call_regs = outer_regs;
    g_current = outer;
    leave_guest();
}

std::uint64_t Thread::call(gaddr fn, const std::uint32_t* args, std::size_t count) {
    enter_guest();
    Thread* outer = g_current;
    g_current = this;
    // Host functions the called code reaches read the live registers, not the caller's copy.
    const std::uint32_t* outer_regs = t_call_regs;
    t_call_regs = nullptr;
    host_thread = pthread_self();
    // Everything the interrupted guest code needs back afterwards.
    auto saved_regs = jit_->Regs();
    auto saved_ext = jit_->ExtRegs();
    std::uint32_t saved_cpsr = jit_->Cpsr();
    std::uint32_t saved_fpscr = jit_->Fpscr();
    bool saved_returned = returned_;
    // Arguments past the fourth go on the stack, which stays 8-byte aligned (AAPCS).
    auto& r = jit_->Regs();
    std::size_t on_stack = count > 4 ? count - 4 : 0;
    gaddr sp = static_cast<gaddr>((saved_regs[13] - on_stack * 4) & ~gaddr{7});
    for (std::size_t i = 0; i < on_stack; ++i) *proc.mem.ptr<std::uint32_t>(sp + static_cast<gaddr>(i * 4)) = args[4 + i];
    for (std::size_t i = 0; i < 4; ++i) r[i] = i < count ? args[i] : 0;
    r[13] = sp;
    // Return to the trap in the vectors page, which stops the JIT.
    r[14] = 0xffff0f20;
    r[15] = fn & ~gaddr{1};
    jit_->SetCpsr((saved_cpsr & ~(0x20u | 0x0600fc00u)) | ((fn & 1) ? 0x20u : 0u));
    returned_ = false;
    while (!returned_ && !exited && !proc.exiting.load()) {
        run_jit();
        if (!returned_) after_run();
    }
    std::uint64_t result = r[0] | (std::uint64_t{r[1]} << 32);
    jit_->Regs() = saved_regs;
    jit_->ExtRegs() = saved_ext;
    jit_->SetCpsr(saved_cpsr);
    jit_->SetFpscr(saved_fpscr);
    returned_ = saved_returned;
    t_call_regs = outer_regs;
    g_current = outer;
    leave_guest();
    return result;
}

void Thread::enter_guest() {
    int me = static_cast<int>(gettid());
    if (guest_owner_.load(std::memory_order_relaxed) == me) {
        ++guest_depth_;
        return;
    }
    guest_lock_.lock();
    guest_owner_.store(me);
    guest_depth_ = 1;
}

void Thread::leave_guest() {
    if (--guest_depth_ > 0) return;
    guest_owner_.store(0);
    guest_lock_.unlock();
    // A signal that came in while this host thread was on its way out has nobody to run it.
    if (signal_ready()) wake_detached();
}

bool Thread::signal_ready() const {
    std::uint64_t p = pending.load();
    return (p & ~sigmask) || (p & ((1ull << (SIGKILL - 1)) | (1ull << (SIGSTOP - 1))));
}

void Thread::wake_detached() {
    // Counted first, so the destructor cannot miss a helper being started.
    helpers_.fetch_add(1);
    if (exited || attached() || helper_active_.exchange(true)) {
        helpers_.fetch_sub(1);
        return;
    }
    std::thread([this] { run_detached_handlers(); }).detach();
}

void Thread::run_detached_handlers() {
    pthread_setname_np(pthread_self(), "arm32 signal");
    for (;;) {
        enter_guest();
        if (!exited && !proc.exiting.load()) {
            Thread* outer = g_current;
            g_current = this;
            pthread_t owner_thread = host_thread;
            host_thread = pthread_self();
            in_helper_ = true;
            // The detached state, put back once the handlers are done: the registers of the
            // park point, or of the svc whose reentrant host function is still running.
            auto saved_regs = jit_->Regs();
            auto saved_ext = jit_->ExtRegs();
            std::uint32_t saved_cpsr = jit_->Cpsr(), saved_fpscr = jit_->Fpscr();
            bool saved_parked = parked, saved_returned = returned_;
            std::uint32_t saved_busy = busy.load();
            auto saved_busy_args = busy_args;
            for (;;) {
                last_frame_ = 0;
                if (!deliver_signal()) break;
                // Ignored signals build no frame and run nothing.
                if (!last_frame_) continue;
                if (g_trace) log("trace: helper runs the handler for %d", tid);
                helper_frame_ = last_frame_;
                helper_done_ = false;
                parked = false;
                while (!helper_done_ && !exited && !proc.exiting.load()) {
                    run_jit();
                    if (!helper_done_) after_run();
                }
                helper_frame_ = 0;
                jit_->Regs() = saved_regs;
                jit_->ExtRegs() = saved_ext;
                jit_->SetCpsr(saved_cpsr);
                jit_->SetFpscr(saved_fpscr);
            }
            parked = saved_parked;
            returned_ = saved_returned;
            busy_args = saved_busy_args;
            busy.store(saved_busy);
            in_helper_ = false;
            host_thread = owner_thread;
            g_current = outer;
        }
        leave_guest();
        helper_active_.store(false);
        // A signal that arrived after the last check, with the thread still detached: again.
        if (exited || !signal_ready() || attached() || helper_active_.exchange(true)) break;
    }
    // The last access to this object.
    helpers_.fetch_sub(1);
}

namespace {

// ARM signal frame, as the Linux kernel builds it (struct rt_sigframe): siginfo, then ucontext.
constexpr std::uint32_t kInfoSize = 128;
constexpr std::uint32_t kUcOffset = kInfoSize;
// Inside the ucontext: flags, link, stack_t, then struct sigcontext.
constexpr std::uint32_t kUcStack = 8;
constexpr std::uint32_t kUcMcontext = 20;
// sigcontext: trap_no, error_code, oldmask, then r0..r15, cpsr, fault_address.
constexpr std::uint32_t kMcRegs = 12;
constexpr std::uint32_t kMcCpsr = kMcRegs + 16 * 4;
constexpr std::uint32_t kUcSigmask = 104;
constexpr std::uint32_t kUcRegspace = 232;
// VFP state in uc_regspace: magic, size, d0..d31, fpscr.
constexpr std::uint32_t kVfpMagic = 0x56465001;
constexpr std::uint32_t kVfpSize = 8 + 32 * 8 + 4 + 12;
constexpr std::uint32_t kFrameSize = kUcOffset + 744 + 16;

constexpr std::uint32_t kSaOnstack = 0x08000000, kSaRestart = 0x10000000,
                        kSaNodefer = 0x40000000, kSaResethand = 0x80000000, kSaRestorer = 0x04000000;

// Whether Linux makes a system call again after a handler returns, when the signal cut the call
// short (the kernel's restart codes). Calls that wait for data, a connection or a lock do when the
// handler has SA_RESTART; sleeps, polls, signal waits and timed waits never do: they return EINTR,
// and the C library works out what time is left (made again with the same arguments, a relative
// timeout would start over at every handler, and a stream of signals, such as a collector's,
// would postpone it for as long as it lasts). A futex lock attempt is made again even without
// SA_RESTART. Sockets with a send or receive timeout would return EINTR on Linux; they are not
// told apart here.
enum class Restart { kNever, kWithSaRestart, kAlways };
Restart restart_after_handler(std::uint32_t nr, const std::array<std::uint32_t, 16>& r) {
    switch (nr) {
    case 3: case 4: case 145: case 146: case 180: case 181:  // read, write, readv, writev, pread64, pwrite64
    case 54:                                                 // ioctl
    case 143:                                                // flock
    case 283: case 285: case 366:                            // connect, accept, accept4
    case 289: case 290: case 291: case 292: case 296: case 297:  // send(to), recv(from), sendmsg, recvmsg
        return Restart::kWithSaRestart;
    case 55: case 221:  // fcntl, fcntl64: only the lock that waits (F_SETLKW, F_SETLKW64)
        return r[1] == 7 || r[1] == 14 ? Restart::kWithSaRestart : Restart::kNever;
    case 240: {  // futex: a wait without a timeout; a priority-inheritance lock always
        int cmd = static_cast<int>(r[1]) & FUTEX_CMD_MASK;
        if (cmd == FUTEX_LOCK_PI || cmd == FUTEX_LOCK_PI2) return Restart::kAlways;
        if ((cmd == FUTEX_WAIT || cmd == FUTEX_WAIT_BITSET) && !r[3]) return Restart::kWithSaRestart;
        return Restart::kNever;
    }
    default:  // nanosleep, clock_nanosleep, poll, ppoll, select, epoll_wait, rt_sigsuspend, ...
        return Restart::kNever;
    }
}

}  // namespace

bool Thread::deliver_signal() {
    std::uint64_t ready = pending.load() & ~sigmask;
    // SIGKILL and SIGSTOP cannot be blocked.
    ready |= pending.load() & ((1ull << (SIGKILL - 1)) | (1ull << (SIGSTOP - 1)));
    if (!ready) return false;
    int sig = __builtin_ctzll(ready) + 1;
    pending.fetch_and(~(1ull << (sig - 1)));
    if (g_trace) log("trace: %d delivers %d at pc %#x", tid, sig, jit_->Regs()[15]);
    Process::SigAction act;
    {
        std::lock_guard<std::mutex> g(proc.sig_lock);
        act = proc.sigactions[sig];
        if (act.handler > 1 && (act.flags & kSaResethand)) proc.sigactions[sig].handler = 0;
    }
    if (act.handler == 1 /* SIG_IGN */) return true;
    if (act.handler == 0 /* SIG_DFL */) {
        // Default action: ignored for these, fatal for the rest.
        if (sig == SIGCHLD || sig == SIGURG || sig == SIGWINCH || sig == SIGCONT) return true;
        log("arm32: guest killed by signal %d", sig);
        _exit(128 + sig);
    }
    auto& r = jit_->Regs();
    gaddr sp = r[13];
    // SA_ONSTACK runs the handler on the alternate stack, unless already on it.
    bool on_alt = altstack_size && sp - altstack_sp < altstack_size;
    if ((act.flags & kSaOnstack) && altstack_size && !(altstack_flags & 2 /* SS_DISABLE */) && !on_alt) {
        sp = altstack_sp + altstack_size;
    }
    gaddr frame = (sp - kFrameSize) & ~gaddr{7};
    if (!proc.mem.readable(frame, kFrameSize)) fatal("no stack room for a signal frame", frame);
    std::memset(proc.mem.host(frame), 0, kFrameSize);
    auto put = [&](gaddr at, std::uint32_t v) { std::memcpy(proc.mem.host(at), &v, 4); };
    // siginfo: signo, errno, code (SI_TKILL), sender pid and uid.
    put(frame + 0, static_cast<std::uint32_t>(sig));
    put(frame + 8, static_cast<std::uint32_t>(-6));
    put(frame + 12, static_cast<std::uint32_t>(getpid()));
    put(frame + 16, getuid());
    gaddr uc = frame + kUcOffset;
    put(uc + kUcStack + 0, altstack_sp);
    put(uc + kUcStack + 4, altstack_flags);
    put(uc + kUcStack + 8, altstack_size);
    for (int i = 0; i < 16; ++i) put(uc + kUcMcontext + kMcRegs + i * 4, r[i]);
    put(uc + kUcMcontext + kMcCpsr, jit_->Cpsr());
    std::uint64_t old_mask = suspend_saved_mask ? *suspend_saved_mask : sigmask;
    std::memcpy(proc.mem.host(uc + kUcSigmask), &old_mask, 8);
    // VFP registers and FPSCR, so the handler cannot disturb the interrupted code's floats.
    put(uc + kUcRegspace, kVfpMagic);
    put(uc + kUcRegspace + 4, kVfpSize);
    std::memcpy(proc.mem.host(uc + kUcRegspace + 8), jit_->ExtRegs().data(), 32 * 8);
    put(uc + kUcRegspace + 8 + 256, jit_->Fpscr());
    // Block the signal itself (unless SA_NODEFER) and the handler's mask while it runs.
    sigmask |= act.mask | ((act.flags & kSaNodefer) ? 0 : (1ull << (sig - 1)));
    suspend_saved_mask.reset();
    // Enter the handler: (sig, &info, &uc), returning to the restorer that calls rt_sigreturn.
    r[0] = static_cast<std::uint32_t>(sig);
    r[1] = frame;
    r[2] = uc;
    r[13] = frame;
    last_frame_ = frame;
    r[14] = (act.flags & kSaRestorer) ? act.restorer : 0xffff0f00;
    r[15] = act.handler & ~1u;
    // Thumb state from the handler address; clear the IT (if-then) state.
    std::uint32_t cpsr = jit_->Cpsr() & ~(0x20u | 0x0600fc00u);
    jit_->SetCpsr(cpsr | ((act.handler & 1) ? 0x20u : 0u));
    // Taking an exception clears the exclusive monitor (the kernel's CLREX). A reservation the
    // interrupted code opened must not survive into the handler, or come back after it: with the
    // store-exclusive done as a compare-and-swap against the value LDREX saw, a STREX after the
    // handler would succeed whenever the word holds that value again.
    jit_->ClearExclusiveState();
    return true;
}

std::uint32_t Thread::sigreturn() {
    auto& r = jit_->Regs();
    if (g_trace) log("trace: %d sigreturn", tid);
    // The handler a helper is running for a detached thread is done.
    if (helper_frame_ && r[13] == helper_frame_) {
        helper_done_ = true;
        halt();
    }
    // The restorer runs with sp back at the frame; the ucontext follows the siginfo.
    gaddr uc = r[13] + kUcOffset;
    if (!proc.mem.readable(uc, 744)) fatal("bad signal frame", r[13]);
    auto get = [&](gaddr at) {
        std::uint32_t v;
        std::memcpy(&v, proc.mem.host(at), 4);
        return v;
    };
    for (int i = 0; i < 16; ++i) r[i] = get(uc + kUcMcontext + kMcRegs + i * 4);
    jit_->SetCpsr(get(uc + kUcMcontext + kMcCpsr));
    std::memcpy(&sigmask, proc.mem.host(uc + kUcSigmask), 8);
    if (get(uc + kUcRegspace) == kVfpMagic) {
        std::memcpy(jit_->ExtRegs().data(), proc.mem.host(uc + kUcRegspace + 8), 32 * 8);
        jit_->SetFpscr(get(uc + kUcRegspace + 8 + 256));
    }
    // The return from the handler clears the exclusive monitor too: a reservation the handler
    // left open (a compare-exchange that failed and skipped its STREX) must not pair with a STREX
    // of the interrupted code.
    jit_->ClearExclusiveState();
    return r[0];
}

void invalidate_code(gaddr start, std::uint32_t length) {
    if (!length) return;
    Thread* self = current_thread();
    // A constant folded from the range may sit in any block, wherever its code is: then every
    // cache goes, not just the range.
    const bool all = any_page(g_folded, start, length);
    // The calling thread's own cache at once: from inside a JIT callback Dynarmic halts and drops
    // the range before the thread runs on.
    if (self) {
        if (all) self->jit().ClearCache();
        else self->jit().InvalidateCacheRange(start, length);
    }
    // Every other thread may hold translations of the range as well (a library unloaded and
    // another loaded at its address, code rewritten in place and flushed): on ARM Linux a cache
    // flush reaches every CPU. Each one gets the range queued and drops it itself before it next
    // runs guest code. Memory no thread ever ran code from (most mappings) needs nothing.
    if (!all && !translated(start, length)) return;
    std::lock_guard<std::mutex> g(g_jits_lock);
    for (Thread* t : g_jits) {
        if (t != self) t->queue_invalidation(start, length, all);
    }
}

void Thread::queue_invalidation(gaddr start, std::uint32_t length, bool all) {
    {
        std::lock_guard<std::mutex> g(inval_lock_);
        // A thread that has not run for long (parked in Java) could collect ranges forever.
        if (all || inval_queue_.size() >= kMaxQueuedRanges) {
            inval_queue_.clear();
            inval_all_ = true;
        }
        if (!inval_all_) inval_queue_.emplace_back(start, length);
    }
    inval_pending_.store(true);
    // A run in progress stops at its next halt check and goes through run_jit() again.
    halt();
}

void Thread::apply_invalidations() {
    if (!inval_pending_.exchange(false)) return;
    std::vector<std::pair<gaddr, std::uint32_t>> ranges;
    bool all;
    {
        std::lock_guard<std::mutex> g(inval_lock_);
        ranges.swap(inval_queue_);
        all = inval_all_;
        inval_all_ = false;
    }
    // Called outside Run, on the thread that runs this JIT: Dynarmic drops the code at the start
    // of the Run that follows.
    if (all) jit_->ClearCache();
    else for (const auto& [s, n] : ranges) jit_->InvalidateCacheRange(s, n);
}

void Thread::fault(const char* kind, std::uint32_t vaddr) {
    fatal(kind, vaddr);
}

void Thread::fatal(const char* what, std::uint32_t addr) {
    auto& r = jit_->Regs();
    // Where pc and lr are when they are in code: the library and the offset readelf and objdump use.
    const std::string pc_at = proc.mem.code_location(r[15]), lr_at = proc.mem.code_location(r[14]);
    log("arm32: thread %d: %s at 0x%08x (pc 0x%08x%s%s lr 0x%08x%s%s sp 0x%08x)", tid, what, addr, r[15], pc_at.empty() ? "" : " ",
        pc_at.c_str(), r[14], lr_at.empty() ? "" : " ", lr_at.c_str(), r[13]);
    // No guest signal delivery for faults yet: end the process like an unhandled SIGSEGV would.
    proc.exit_code = 128 + 11;
    proc.exiting = true;
    _exit(proc.exit_code);
}

// Page-table misses: the page is unmapped or has no access. Re-check under the current table
// (it may have been mapped since the code was translated), else fault.
#define ARM32_READ(bits)                                                                 \
    std::uint##bits##_t Thread::MemoryRead##bits(std::uint32_t vaddr) {                  \
        if (!proc.mem.readable(vaddr, (bits) / 8)) fault("read" #bits " fault", vaddr);  \
        std::uint##bits##_t v;                                                           \
        std::memcpy(&v, proc.mem.host(vaddr), sizeof v);                                 \
        return v;                                                                        \
    }
#define ARM32_WRITE(bits)                                                                         \
    void Thread::MemoryWrite##bits(std::uint32_t vaddr, std::uint##bits##_t value) {              \
        if (!proc.mem.readable(vaddr, (bits) / 8)) fault("write" #bits " fault", vaddr);          \
        std::memcpy(proc.mem.host(vaddr), &value, sizeof value);                                  \
    }                                                                                             \
    bool Thread::MemoryWriteExclusive##bits(std::uint32_t vaddr, std::uint##bits##_t value,       \
                                            std::uint##bits##_t expected) {                       \
        if (!proc.mem.readable(vaddr, (bits) / 8)) fault("exclusive write fault", vaddr);         \
        ++n_exclusive;                                                                            \
        auto* p = reinterpret_cast<std::uint##bits##_t*>(proc.mem.host(vaddr));                   \
        return __atomic_compare_exchange_n(p, &expected, value, false, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST); \
    }
ARM32_READ(8)
ARM32_READ(16)
ARM32_READ(32)
ARM32_READ(64)
ARM32_WRITE(8)
ARM32_WRITE(16)
ARM32_WRITE(32)
ARM32_WRITE(64)
#undef ARM32_READ
#undef ARM32_WRITE

bool Thread::IsReadOnlyMemory(std::uint32_t vaddr) {
    if (!proc.mem.constant_code(vaddr, 8)) return false;
    // The value becomes part of translated code: remember its page (and the next, for a read that
    // crosses a page end).
    mark_page(g_folded, vaddr);
    mark_page(g_folded, vaddr + 7);
    return true;
}

std::optional<std::uint32_t> Thread::MemoryReadCode(std::uint32_t vaddr) {
    // Instruction fetch from an unmapped page: Dynarmic raises NoExecuteFault for us.
    if (!proc.mem.readable(vaddr, 4)) return std::nullopt;
    // Only read while translating: this page's code is in a code cache from now on.
    mark_translated(vaddr);
    std::uint32_t v;
    std::memcpy(&v, proc.mem.host(vaddr), sizeof v);
    return v;
}

void Thread::InterpreterFallback(std::uint32_t pc, std::size_t) {
    fatal("instruction the JIT cannot translate", pc);
}

void Thread::CallSVC(std::uint32_t) {
    auto& r = jit_->Regs();
    // ARM EABI: the call number is in r7 whatever the svc immediate says.
    std::uint32_t number = r[7];
    // Not system calls: the end of a host-to-guest call, and the host functions.
    if (number == kTrapReturn) {
        returned_ = true;
        halt();
        return;
    }
    if (number >= kReentrantBase && number < kReentrantBase + kHostRange) {
        if (!g_reentrant_fns[number - kReentrantBase]) fatal("unknown host function", number);
        pending_host_ = number;
        halt();
        return;
    }
    if (number >= kHostBase && number < kHostBase + kHostRange) {
        HostFn fn = g_host_fns[number - kHostBase];
        if (!fn) fatal("unknown host function", number);
        ++n_host_calls;
        mark_busy(kBusyHost | number);
        std::uint64_t v = fn(*this);
        busy.store(0, std::memory_order_relaxed);
        r[0] = static_cast<std::uint32_t>(v);
        r[1] = static_cast<std::uint32_t>(v >> 32);
        return;
    }
    if (number > 0xf0f000 && number < 0xf10000) {
        HostFn fn = find_other_fn(number);
        if (!fn) fatal("unknown runtime trap", number);
        std::uint64_t v = fn(*this);
        r[0] = static_cast<std::uint32_t>(v);
        r[1] = static_cast<std::uint32_t>(v >> 32);
        return;
    }
    std::uint32_t first_arg = r[0];
    ++n_syscalls;
    if (g_stats) note_syscall(number);
    mark_busy(kBusySyscall | number);
    std::uint32_t result = do_syscall(*this, number);
    busy.store(0, std::memory_order_relaxed);
    r[0] = result;
    // rt_sigreturn / sigreturn replaced every register, the mode included: restart the JIT there.
    if (number == 173 || number == 119) {
        halt();
        return;
    }
    if (!((pending.load() & ~sigmask) || (pending.load() & ((1ull << (SIGKILL - 1)) | (1ull << (SIGSTOP - 1)))))) return;
    // A call cut short by the signal is made again after the handler where Linux would do so:
    // back to the svc, with the first argument the result replaced.
    if (result == static_cast<std::uint32_t>(-EINTR)) {
        Restart kind = restart_after_handler(number, r);
        bool again = kind == Restart::kAlways;
        std::uint64_t ready = pending.load() & ~sigmask;
        if (kind == Restart::kWithSaRestart && ready) {
            int sig = __builtin_ctzll(ready) + 1;
            std::lock_guard<std::mutex> g(proc.sig_lock);
            again = proc.sigactions[sig].flags & kSaRestart;
        }
        if (again) {
            r[0] = first_arg;
            r[15] -= (jit_->Cpsr() & 0x20) ? 2 : 4;
        }
    }
    if (deliver_signal()) halt();
}

void Thread::ExceptionRaised(std::uint32_t pc, Dynarmic::A32::Exception exception) {
    using E = Dynarmic::A32::Exception;
    switch (exception) {
    case E::SendEvent:
    case E::SendEventLocal:
    case E::WaitForInterrupt:
    case E::PreloadData:
    case E::PreloadDataWithIntentToWrite:
    case E::PreloadInstruction:
        return;
    case E::WaitForEvent:
    case E::Yield:
        // Spin-wait hints: let other threads run.
        sched_yield();
        return;
    case E::NoExecuteFault:
        fault("instruction fetch fault", pc);
        break;
    case E::Breakpoint:
        fatal("breakpoint", pc);
        break;
    default: {
        // Show the instruction bytes, so missing JIT support is easy to identify.
        std::uint32_t word = proc.mem.readable(pc, 4) ? *proc.mem.ptr<std::uint32_t>(pc) : 0;
        log("arm32: undefined instruction %08x (thumb %d)", word, (jit_->Cpsr() >> 5) & 1);
        fatal("undefined instruction", pc);
    }
    }
}

}  // namespace arm32
