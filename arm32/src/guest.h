// The guest process inside a host program (an Android app, or arm32run in --call mode).
//
// A small 32-bit program, the agent, is the guest's main program. Its main thread hands over the
// addresses of dlopen and friends, then serves requests from the host, the main one being to
// create a guest thread for a host thread: the clone it triggers is not run on a new host thread
// but given to the asking thread, which from then on runs guest code as that guest thread.
#pragma once

#include "thread.h"

#include <deque>
#include <thread>

namespace arm32 {

// Runtime traps the agent uses (r7 values).
constexpr std::uint32_t kTrapReady = 0x00f0f001;       // agent: here are the function addresses
constexpr std::uint32_t kTrapNextRequest = 0x00f0f002; // agent main thread: wait for work
constexpr std::uint32_t kTrapPark = 0x00f0f003;        // new thread: hand control to the host thread
constexpr std::uint32_t kTrapCreated = 0x00f0f004;     // agent main thread: pthread_create's result

class Guest {
public:
    static Guest& get();

    // Starts the guest process: the agent as main program, run by a host thread of its own.
    // Returns once the agent is ready, or false with a message.
    bool start(const std::string& sysroot, const std::string& agent, std::vector<std::string> env, std::string& error);

    // The guest thread of the calling host thread, created the first time. try_current() returns
    // null when the agent could not create one (pthread_create failed, logged; asked again a
    // second later at the earliest); current() ends the process then, for callers that cannot go
    // on without one.
    Thread* try_current();
    Thread& current();
    // Ends guest thread t, made by try_current() for a host thread that is exiting now.
    void retire(Thread* t);
    // Set by the bridges (JNI): constructs the calling host thread's thread-local state of theirs,
    // called by try_current() before it registers the thread's retirement (see there).
    void (*thread_init)() = nullptr;
    // Set by the bridges (JNI): gives back the guest memory the calling host thread's state holds
    // (direct buffer copies), called by retire() while the guest thread can still run the guest's
    // free().
    void (*thread_fini)() = nullptr;

    // Guest dynamic linker, called on the current thread. flags are the host's RTLD_* values;
    // the 32-bit C library's differ (its RTLD_NOW is 0 and its RTLD_GLOBAL is 2).
    gaddr dlopen(const std::string& path, int flags);
    gaddr dlsym(gaddr handle, const std::string& name);
    std::string dlerror();
    // Guest heap.
    gaddr malloc(std::uint32_t size);
    void free(gaddr p);
    // A guest copy of a string (free it with free()).
    gaddr strdup(const std::string& s);

    Process proc;

    // Filled in by the clone of an adoption request, picked up by the waiting host thread.
    struct Adoption {
        int tid = 0;                      // the host thread that becomes the guest thread
        bool ready = false;               // the clone arrived, or the agent gave up (error)
        int error = 0;                    // pthread_create's error in the agent, 0 when it worked
        std::array<std::uint32_t, 16> regs{};
        std::array<std::uint32_t, 64> ext{};
        std::uint32_t cpsr = 0, fpscr = 0, tls = 0, flags = 0;
        std::uint64_t sigmask = 0;
        gaddr ctid = 0;
    };
    // Set while the agent's main thread is creating a thread for an adoption request: from the
    // request it took until its own clone, or until pthread_create returned without one. Only a
    // clone made by the agent's main thread (agent_tid) takes it.
    std::atomic<Adoption*> adopting{nullptr};
    std::atomic<int> agent_tid{0};
    std::mutex adopt_lock;
    std::condition_variable adopt_cv;

    // Agent request queue (served by the agent's main thread through kTrapNextRequest).
    struct Request {
        std::uint32_t kind;
        Adoption* adoption;
    };
    std::mutex requests_lock;
    std::condition_variable requests_cv;
    std::deque<Request> requests;

    // Function addresses the agent handed over.
    struct Api {
        gaddr dlopen = 0, dlsym = 0, dlerror = 0, dlclose = 0, malloc = 0, free = 0, pthread_exit = 0;
    } api;
    bool ready = false;

private:
    std::thread main_;
};

}  // namespace arm32
