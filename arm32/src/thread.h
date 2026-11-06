// A guest thread: one Dynarmic JIT with its own registers, thread pointer and signal state.
#pragma once

#include "runtime.h"

#include <condition_variable>
#include <optional>
#include <pthread.h>

#include <dynarmic/interface/A32/a32.h>
#include <dynarmic/interface/A32/config.h>
#include <dynarmic/interface/A32/coprocessor.h>
#include <dynarmic/interface/exclusive_monitor.h>

namespace arm32 {

// Numbers in r7 at an svc that are not Linux system calls.
// End of a host-to-guest call: the guest function returned to the trap the call set as lr.
constexpr std::uint32_t kTrapReturn = 0x00f0f000;
// Host functions the guest's stub libraries reach. Those below kReentrantBase run inside the
// JIT callback and must not call guest code; those from kReentrantBase on run after the JIT
// has returned, so they may call guest code on the same thread (JNI does).
constexpr std::uint32_t kHostBase = 0x00100000;
constexpr std::uint32_t kReentrantBase = 0x00200000;
constexpr std::uint32_t kHostRange = 0x00010000;

class Thread;
// A host function: reads its arguments from the guest registers and stack, returns r0 | r1 << 32.
using HostFn = std::uint64_t (*)(Thread&);
// Makes `number` (in [kHostBase, kHostBase + kHostRange) or the same range at kReentrantBase,
// or one of the runtime's own trap numbers) call fn.
void register_host_fn(std::uint32_t number, HostFn fn);

class Thread final : public Dynarmic::A32::UserCallbacks {
public:
    Thread(Process& proc, int tid);
    ~Thread() override;

    // Makes the thread known to the process (signals, the hang dump, code invalidation). Called
    // once its registers and signal state are set: a signal for a thread that is listed but not
    // set up would run its handler on a zero stack pointer.
    void publish();

    // Runs guest code until the thread exits (exit, exit_group or a fatal fault).
    void run();

    // Calls the guest function at fn with 32-bit arguments (AAPCS: r0-r3, then the stack) on
    // this thread's guest stack, and returns r0 | r1 << 32. The thread's state is saved and
    // restored around the call, so calls can nest (guest -> host -> guest).
    std::uint64_t call(gaddr fn, const std::uint32_t* args, std::size_t count);
    std::uint64_t call(gaddr fn, std::initializer_list<std::uint32_t> args) { return call(fn, args.begin(), args.size()); }

    // Argument i of the host function being run: r0-r3, then the caller's stack, which the
    // stub moved down by the two words it pushed (r7 and lr).
    std::uint32_t arg(unsigned i);
    // Register n as the guest left it when it called the host function being run.
    std::uint32_t call_reg(unsigned n);

    // A host thread takes the guest context before it runs this thread's guest code and gives
    // it back afterwards: at the end of run() or call(), and while a reentrant host function
    // runs (a JNI call into Java can take long). While no host thread holds it, a signal for
    // this thread is run by a helper host thread instead, as the kernel would interrupt
    // whatever the real thread was doing; the garbage collector's stop-the-world needs this
    // for threads that are in Java between native calls.
    void enter_guest();
    void leave_guest();
    // Called after a signal was made pending: starts the helper if no host thread holds the
    // guest context.
    void wake_detached();
    // True while some host thread holds the guest context.
    bool attached() const { return guest_owner_.load() != 0; }
    // A pending signal the thread does not block.
    bool signal_ready() const;

    // Set by the runtime's "park" trap: the thread stops running until the host calls into it.
    bool parked = false;

    // What the thread is doing outside translated code, for the hang dump: 0 while it runs
    // guest code, else a system call (kBusySyscall | number) or a host function
    // (kBusyHost | number), with the first six argument registers of that call.
    static constexpr std::uint32_t kBusySyscall = 0x80000000, kBusyHost = 0x40000000;
    std::atomic<std::uint32_t> busy{0};
    std::array<std::uint32_t, 6> busy_args{};

    // Counts for the stats log, kept by whichever host thread runs the thread's code.
    std::uint64_t n_syscalls = 0, n_host_calls = 0, n_native_calls = 0, n_exclusive = 0;

    // Register access for system calls.
    std::array<std::uint32_t, 16>& regs() { return jit_->Regs(); }
    Dynarmic::A32::Jit& jit() { return *jit_; }

    // Stops this thread at the next instruction boundary (exit, or another thread asking).
    void halt() { jit_->HaltExecution(); }

    // Another thread changed guest code in [start, start + length): this thread's JIT drops the
    // range before it runs guest code again (only the thread that runs a JIT touches its cache),
    // and the thread is halted so a run in progress gets there soon.
    // all: drop the whole cache, not just the range.
    void queue_invalidation(gaddr start, std::uint32_t length, bool all = false);

    Process& proc;
    int tid;                          // host thread id, also the guest's
    std::uint32_t tls = 0;            // TPIDRURO, set by __ARM_NR_set_tls, read with mrc p15
    std::uint32_t tls_rw = 0;         // TPIDRURW
    gaddr clear_child_tid = 0;        // set_tid_address / CLONE_CHILD_CLEARTID
    std::uint64_t sigmask = 0;        // blocked signals
    gaddr altstack_sp = 0;            // sigaltstack
    std::uint32_t altstack_size = 0;
    std::uint32_t altstack_flags = 0;
    bool exited = false;
    pthread_t host_thread = pthread_self();

    // Signals sent to this thread and not delivered yet (bit n-1 for signal n).
    std::atomic<std::uint64_t> pending{0};
    // The mask an rt_sigsuspend replaced, put back when the handler returns.
    std::optional<std::uint64_t> suspend_saved_mask;
    // rt_sigsuspend sleeps here until a signal arrives.
    std::mutex wait_lock;
    std::condition_variable wait_cv;

    // Runs the handler of one pending, unblocked signal: builds the signal frame on the guest
    // stack and points the registers at the handler. False when nothing was delivered.
    bool deliver_signal();
    // rt_sigreturn / sigreturn: restores the context saved in the frame at sp; returns r0.
    std::uint32_t sigreturn();

    // Dynarmic callbacks.
    std::optional<std::uint32_t> MemoryReadCode(std::uint32_t vaddr) override;
    std::uint8_t MemoryRead8(std::uint32_t vaddr) override;
    std::uint16_t MemoryRead16(std::uint32_t vaddr) override;
    std::uint32_t MemoryRead32(std::uint32_t vaddr) override;
    std::uint64_t MemoryRead64(std::uint32_t vaddr) override;
    void MemoryWrite8(std::uint32_t vaddr, std::uint8_t value) override;
    void MemoryWrite16(std::uint32_t vaddr, std::uint16_t value) override;
    void MemoryWrite32(std::uint32_t vaddr, std::uint32_t value) override;
    void MemoryWrite64(std::uint32_t vaddr, std::uint64_t value) override;
    bool MemoryWriteExclusive8(std::uint32_t vaddr, std::uint8_t value, std::uint8_t expected) override;
    bool MemoryWriteExclusive16(std::uint32_t vaddr, std::uint16_t value, std::uint16_t expected) override;
    bool MemoryWriteExclusive32(std::uint32_t vaddr, std::uint32_t value, std::uint32_t expected) override;
    bool MemoryWriteExclusive64(std::uint32_t vaddr, std::uint64_t value, std::uint64_t expected) override;
    void InterpreterFallback(std::uint32_t pc, std::size_t num_instructions) override;
    // Constant-address reads from code pages (ARM literal pools) are folded into the translated
    // code: those pages never change once loaded (a change there clears whole caches).
    bool IsReadOnlyMemory(std::uint32_t vaddr) override;
    void CallSVC(std::uint32_t swi) override;
    void ExceptionRaised(std::uint32_t pc, Dynarmic::A32::Exception exception) override;
    void AddTicks(std::uint64_t) override {}
    std::uint64_t GetTicksRemaining() override { return UINT64_MAX / 2; }

    // Ends the thread or the whole process because of a fault the guest cannot handle yet.
    [[noreturn]] void fatal(const char* what, std::uint32_t addr);

private:
    void fault(const char* kind, std::uint32_t vaddr);
    // The helper's body: runs the handlers of the ready signals on the detached thread's state.
    void run_detached_handlers();

    std::mutex guest_lock_;
    std::atomic<int> guest_owner_{0};  // host thread id holding guest_lock_, 0 when none
    int guest_depth_ = 0;              // nested enter_guest calls of the owner
    std::atomic<bool> helper_active_{false};  // a helper is running or about to
    std::atomic<int> helpers_{0};      // helper threads that may still touch this object
    bool in_helper_ = false;           // the guest context is the helper's (no detaching)
    gaddr helper_frame_ = 0;           // the frame whose sigreturn ends the helper's handler
    bool helper_done_ = false;
    gaddr last_frame_ = 0;             // frame deliver_signal built, 0 if the signal had none

    // Records the call about to run for the hang dump (only the argument copy costs anything).
    void mark_busy(std::uint32_t what) {
        auto& r = jit_->Regs();
        busy_args = {r[0], r[1], r[2], r[3], r[4], r[5]};
        busy.store(what, std::memory_order_relaxed);
    }
    // After the JIT returned: runs a pending reentrant host function, delivers signals.
    void after_run();

    // Runs the JIT once, after dropping the code ranges other threads queued.
    void run_jit() {
        apply_invalidations();
        jit_->Run();
    }
    void apply_invalidations();
    std::mutex inval_lock_;
    std::vector<std::pair<gaddr, std::uint32_t>> inval_queue_;  // guarded by inval_lock_
    bool inval_all_ = false;                  // too many ranges queued: drop the whole cache
    std::atomic<bool> inval_pending_{false};  // something is queued (checked without the lock)

    std::uint32_t pending_host_ = 0;  // reentrant host function the guest is waiting for
    bool returned_ = false;           // the return trap of the innermost call was reached

    std::unique_ptr<Dynarmic::A32::Jit> jit_;
    std::size_t processor_id_;
};

// The exclusive monitor shared by every thread (LDREX/STREX across threads).
Dynarmic::ExclusiveMonitor& exclusive_monitor();
// A free processor slot in the monitor, and giving it back.
std::size_t acquire_processor_id();
void release_processor_id(std::size_t id);
// Drops translated code for a guest range from every thread's JIT: the calling thread's at once,
// the others' before they next run guest code.
void invalidate_code(gaddr start, std::uint32_t length);
// Thread currently running guest code on this host thread.
Thread* current_thread();

}  // namespace arm32
