// The guest process inside a host program: start-up through the agent, host threads becoming
// guest threads, and the guest linker and heap as host calls.
#include "guest.h"

#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <sched.h>
#include <unistd.h>

namespace arm32 {

namespace {

// The calling host thread's guest thread, once it has one.
thread_local Thread* t_guest_thread = nullptr;
// After a failed adoption: no new request from this host thread before then (an audio callback
// asks every few milliseconds).
thread_local std::chrono::steady_clock::time_point t_adopt_retry{};

// Ends the guest thread of a host thread that exits, as the 32-bit C library ends a thread whose
// start routine returned (Guest::retire). Without it every Java or audio thread that ever called
// guest code would leave its guest thread behind for good: an 8 MB guest stack, one of the
// monitor's 256 processor slots, a stale entry under a thread id the kernel hands out again, and,
// when it ran managed code, a registration the garbage collector keeps stopping and waiting for.
struct Retirement {
    Thread* thread = nullptr;
    ~Retirement() {
        // The main thread only ends with the process (exit() runs its thread-local destructors
        // first): no guest code then.
        if (thread && gettid() != getpid()) Guest::get().retire(thread);
    }
};
thread_local Retirement t_retirement;

// Kinds of request the agent's main thread serves.
constexpr std::uint32_t kRequestAdopt = 1;

// kTrapReady(table): the agent's table of { dlopen, dlsym, dlerror, dlclose, malloc, free,
// pthread_exit } (the agent is built and shipped with this runtime, so the table always has all).
std::uint64_t trap_ready(Thread& t) {
    Guest& g = Guest::get();
    gaddr table = t.arg(0);
    if (!g.proc.mem.readable(table, 7 * 4)) t.fatal("bad agent table", table);
    auto* f = g.proc.mem.ptr<std::uint32_t>(table);
    g.api = Guest::Api{f[0], f[1], f[2], f[3], f[4], f[5], f[6]};
    {
        std::lock_guard<std::mutex> l(g.requests_lock);
        g.ready = true;
    }
    g.requests_cv.notify_all();
    return 0;
}

// kTrapNextRequest(): the agent's main thread waits here for work and gets its kind back.
std::uint64_t trap_next_request(Thread&) {
    Guest& g = Guest::get();
    std::unique_lock<std::mutex> l(g.requests_lock);
    g.requests_cv.wait(l, [&] { return !g.requests.empty() || g.proc.exiting.load(); });
    if (g.requests.empty()) return 0;
    Guest::Request r = g.requests.front();
    g.requests.pop_front();
    // The thread the agent creates next is this host thread's.
    if (r.kind == kRequestAdopt) g.adopting.store(r.adoption);
    return r.kind;
}

// kTrapCreated(error): the agent's pthread_create for an adoption returned. Its clone took the
// adoption when it worked; one still here never got a thread (the call failed before cloning), and
// its host thread is told so instead of waiting for good. Nothing is left for a later clone.
std::uint64_t trap_created(Thread& t) {
    Guest& g = Guest::get();
    int error = static_cast<int>(t.arg(0));
    Guest::Adoption* a = g.adopting.exchange(nullptr);
    if (!a) return 0;
    {
        std::lock_guard<std::mutex> l(g.adopt_lock);
        a->error = error ? error : EAGAIN;
        a->ready = true;
    }
    g.adopt_cv.notify_all();
    return 0;
}

// kTrapPark(): a new guest thread reached the agent's thread entry; its host thread takes over.
std::uint64_t trap_park(Thread& t) {
    t.parked = true;
    t.halt();
    return 0;
}

// Offered every guest clone: the one an adoption request asked for is handed to the waiting
// host thread instead of getting a host thread of its own. Only the agent's main thread makes that
// clone: one any other guest thread makes meanwhile (the game creating a thread) must run its own
// start routine on a host thread of its own, not on the host thread waiting for a guest thread.
int adopt_clone(Process&, const CloneState& cs) {
    Guest& g = Guest::get();
    Thread* caller = current_thread();
    if (!caller || caller->tid != g.agent_tid.load()) return 0;
    Guest::Adoption* a = g.adopting.exchange(nullptr);
    if (!a) return 0;
    a->regs = cs.regs;
    a->ext = cs.ext;
    a->cpsr = cs.cpsr;
    a->fpscr = cs.fpscr;
    a->tls = cs.tls;
    a->sigmask = cs.sigmask;
    a->flags = cs.flags;
    a->ctid = cs.ctid;
    {
        std::lock_guard<std::mutex> l(g.adopt_lock);
        a->ready = true;
    }
    g.adopt_cv.notify_all();
    return a->tid;
}

}  // namespace

Guest& Guest::get() {
    static Guest g;
    return g;
}

bool Guest::start(const std::string& sysroot, const std::string& agent, std::vector<std::string> env, std::string& error) {
    // Interrupts blocked host system calls of a guest thread that has a signal to handle.
    install_interrupt_handler();
    register_host_fn(kTrapReady, trap_ready);
    register_host_fn(kTrapNextRequest, trap_next_request);
    register_host_fn(kTrapPark, trap_park);
    register_host_fn(kTrapCreated, trap_created);
    proc.sysroot = sysroot;
    proc.exe_path = agent;
    proc.argv = {agent};
    proc.envp = std::move(env);
    proc.clone_hook = &adopt_clone;
    if (!proc.mem.init()) {
        error = "cannot reserve the guest address space";
        return false;
    }
    proc.mem.on_code_change = &invalidate_code;
    EntryState entry;
    if (!load_program(proc, entry, error)) return false;
    // The agent's main thread runs on a host thread of its own for the life of the process.
    main_ = std::thread([this, entry] {
        Thread t(proc, static_cast<int>(gettid()));
        t.regs()[13] = entry.sp;
        t.regs()[15] = entry.pc;
        t.jit().SetCpsr(0x10 | (entry.thumb ? 0x20 : 0));
        // The only thread whose clones may be adoptions (adopt_clone).
        agent_tid.store(t.tid);
        // The guest's C library takes its main thread's id for the process id.
        proc.guest_pid.store(t.tid);
        t.publish();
        t.run();
    });
    main_.detach();
    std::unique_lock<std::mutex> l(requests_lock);
    requests_cv.wait(l, [&] { return ready || proc.exiting.load(); });
    if (!ready) error = "the agent did not start";
    return ready;
}

Thread* Guest::try_current() {
    // Inside guest code's call to the host (a helper running a signal handler included), the
    // thread running it.
    if (Thread* t = current_thread()) return t;
    if (t_guest_thread) return t_guest_thread;
    if (std::chrono::steady_clock::now() < t_adopt_retry) return nullptr;
    // Ask the agent for a guest thread and wait for its clone to arrive here, or for the agent to
    // say it could not make one.
    Adoption a;
    a.tid = static_cast<int>(gettid());
    {
        std::lock_guard<std::mutex> l(requests_lock);
        requests.push_back(Request{kRequestAdopt, &a});
    }
    requests_cv.notify_all();
    {
        std::unique_lock<std::mutex> l(adopt_lock);
        adopt_cv.wait(l, [&] { return a.ready; });
    }
    if (a.error) {
        log("arm32: no guest thread for host thread %d: the agent's pthread_create failed (%s)", a.tid, strerror(a.error));
        t_adopt_retry = std::chrono::steady_clock::now() + std::chrono::seconds(1);
        return nullptr;
    }
    auto* t = new Thread(proc, a.tid);
    // The clone's child state: the parent's registers at its next instruction, clone returning 0.
    t->regs() = a.regs;
    t->regs()[0] = 0;
    t->jit().ExtRegs() = a.ext;
    t->jit().SetCpsr(a.cpsr);
    t->jit().SetFpscr(a.fpscr);
    t->tls = a.tls;
    t->sigmask = a.sigmask;
    if (a.flags & CLONE_CHILD_CLEARTID) t->clear_child_tid = a.ctid;
    // Signals can reach it from here on, its state being complete.
    t->publish();
    // Run the C library's thread start until the agent's entry parks it.
    t->run();
    if (!t->parked) t->fatal("new guest thread ended before parking", 0);
    t_guest_thread = t;
    // Ended with this host thread. Thread-local objects are destroyed in the reverse order of
    // their construction: the bridges' per-thread state (JNI local references and the like) is
    // constructed first, so that it is still there when the guest code that retires the thread
    // (its TLS destructors) calls JNI functions.
    if (thread_init) thread_init();
    t_retirement.thread = t;
    return t;
}

Thread& Guest::current() {
    if (Thread* t = try_current()) return *t;
    // Loading libraries, the heap: nothing these callers do can go on without guest code.
    log("arm32: cannot go on without a guest thread on host thread %d", static_cast<int>(gettid()));
    std::abort();
}

void Guest::retire(Thread* t) {
    // Not while the process ends: nothing comes after.
    if (!api.pthread_exit || proc.exiting.load()) return;
    if (g_trace) log("trace: guest thread %d ends with its host thread", t->tid);
    // The bridges' guest memory for this thread goes back first, while guest code still runs here.
    if (thread_fini) thread_fini();
    // pthread_exit on the guest thread, as if its start routine had returned: its TLS destructors
    // run (the game's runtimes forget the thread, the collector included), the stack of the
    // detached thread is unmapped, and the exit system call ends call() without the function
    // returning. A helper running a handler for the thread finishes first (enter_guest).
    t->call(api.pthread_exit, {0});
    if (!t->exited) {
        log("arm32: guest thread %d did not end; it stays", t->tid);
        return;
    }
    t_guest_thread = nullptr;
    // Unlisted for signals and invalidations, its processor slot given back.
    delete t;
}

gaddr Guest::malloc(std::uint32_t size) {
    return static_cast<gaddr>(current().call(api.malloc, {size}));
}

void Guest::free(gaddr p) {
    if (p) current().call(api.free, {p});
}

gaddr Guest::strdup(const std::string& s) {
    gaddr p = malloc(static_cast<std::uint32_t>(s.size() + 1));
    if (p) std::memcpy(proc.mem.host(p), s.c_str(), s.size() + 1);
    return p;
}

gaddr Guest::dlopen(const std::string& path, int flags) {
    // In the 32-bit C library RTLD_NOW and RTLD_LOCAL are 0, RTLD_LAZY 1, RTLD_GLOBAL 2, RTLD_NOLOAD
    // 4 and RTLD_NODELETE 0x1000. The host's RTLD_NOW (2) passed on unchanged made every library
    // global, binding later libraries' symbols to the first copy loaded anywhere.
    std::uint32_t guest_flags = 0;
    if (flags & RTLD_LAZY) guest_flags |= 1;
    if (flags & RTLD_GLOBAL) guest_flags |= 2;
    if (flags & RTLD_NOLOAD) guest_flags |= 4;
    if (flags & RTLD_NODELETE) guest_flags |= 0x1000;
    gaddr s = strdup(path);
    auto h = static_cast<gaddr>(current().call(api.dlopen, {s, guest_flags}));
    free(s);
    return h;
}

gaddr Guest::dlsym(gaddr handle, const std::string& name) {
    gaddr s = strdup(name);
    auto f = static_cast<gaddr>(current().call(api.dlsym, {handle, s}));
    free(s);
    return f;
}

std::string Guest::dlerror() {
    auto p = static_cast<gaddr>(current().call(api.dlerror, {}));
    if (!p || !proc.mem.readable(p, 1)) return {};
    return reinterpret_cast<const char*>(proc.mem.host(p));
}

}  // namespace arm32
