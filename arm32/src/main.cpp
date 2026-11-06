// arm32run: runs a 32-bit ARM Android executable on a 64-bit host.
//
//   arm32run --sysroot DIR [--env NAME=VALUE]... [--fast-fp] [--fp-flags] [--fastmem] PROGRAM [ARGS]...
//   arm32run --sysroot DIR --agent AGENT --call LIBRARY SYMBOL [--threads N] [--stagger MS] [INT]...
//
// DIR holds the guest's bin/linker and lib/*.so (32-bit bionic). PROGRAM is a host path; the
// guest sees the same path. The second form tests the app bridge: the agent starts the guest,
// N host threads each become guest threads, load LIBRARY and call SYMBOL with the integers.
// With --stagger, host thread n starts n * MS milliseconds after the first, so later ones become
// guest threads while earlier ones already run guest code (creating threads, for one).
#include "guest.h"

#include <chrono>
#include <thread>

#include <android/log.h>
#include <csignal>
#include <dlfcn.h>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <unistd.h>

namespace {

int call_mode(const std::string& sysroot, const std::string& agent, int argc, char** argv, int i) {
    using namespace arm32;
    if (i + 2 > argc) return 2;
    std::string library = argv[i++], symbol = argv[i++];
    int threads = 1, stagger_ms = 0;
    std::vector<std::uint32_t> args;
    for (; i < argc; ++i) {
        if (!std::strcmp(argv[i], "--threads") && i + 1 < argc) threads = std::atoi(argv[++i]);
        else if (!std::strcmp(argv[i], "--stagger") && i + 1 < argc) stagger_ms = std::atoi(argv[++i]);
        else args.push_back(static_cast<std::uint32_t>(std::strtol(argv[i], nullptr, 0)));
    }
    Guest& g = Guest::get();
    std::string error;
    if (!g.start(sysroot, agent, {"PATH=/system/bin", "ANDROID_ROOT=/system", "ANDROID_DATA=/data"}, error)) {
        log("arm32: %s", error.c_str());
        return 1;
    }
    std::vector<std::uint64_t> results(static_cast<std::size_t>(threads));
    std::vector<std::thread> workers;
    for (int n = 0; n < threads; ++n) {
        workers.emplace_back([&, n] {
            std::this_thread::sleep_for(std::chrono::milliseconds(n * stagger_ms));
            gaddr h = g.dlopen(library, RTLD_NOW);
            if (!h) {
                log("arm32: dlopen %s: %s", library.c_str(), g.dlerror().c_str());
                return;
            }
            gaddr f = g.dlsym(h, symbol);
            if (!f) {
                log("arm32: dlsym %s: %s", symbol.c_str(), g.dlerror().c_str());
                return;
            }
            results[static_cast<std::size_t>(n)] = g.current().call(f, args.data(), args.size());
        });
    }
    for (auto& w : workers) w.join();
    // r0 only: the test functions return int, r1 is scratch.
    for (int n = 0; n < threads; ++n) std::printf("thread %d: %s returned %u\n", n, symbol.c_str(), static_cast<std::uint32_t>(results[static_cast<std::size_t>(n)]));
    std::fflush(stdout);
    _exit(0);
}

}  // namespace

int main(int argc, char** argv) {
    using namespace arm32;
    Process proc;
    std::string agent;
    int i = 1;
    for (; i < argc && argv[i][0] == '-'; ++i) {
        if (!std::strcmp(argv[i], "--sysroot") && i + 1 < argc) proc.sysroot = argv[++i];
        else if (!std::strcmp(argv[i], "--env") && i + 1 < argc) proc.envp.emplace_back(argv[++i]);
        else if (!std::strcmp(argv[i], "--fast-fp")) proc.fast_fp = true;
        else if (!std::strcmp(argv[i], "--fp-flags")) proc.fp_flags = true;
        else if (!std::strcmp(argv[i], "--fast-neon")) proc.fast_neon = true;
        else if (!std::strcmp(argv[i], "--fast-atomics")) proc.fast_atomics = true;
        else if (!std::strcmp(argv[i], "--fastmem")) proc.fastmem = true;
        else if (!std::strcmp(argv[i], "--agent") && i + 1 < argc) agent = argv[++i];
        else if (!std::strcmp(argv[i], "--call")) {
            ++i;
            break;
        }
        else {
            std::fprintf(stderr, "usage: %s --sysroot DIR [--env NAME=VALUE]... PROGRAM [ARGS]...\n", argv[0]);
            return 2;
        }
    }
    if (!agent.empty()) return call_mode(proc.sysroot, agent, argc, argv, i);
    if (i >= argc || proc.sysroot.empty()) {
        std::fprintf(stderr, "usage: %s --sysroot DIR [--env NAME=VALUE]... PROGRAM [ARGS]...\n", argv[0]);
        return 2;
    }
    proc.exe_path = argv[i];
    for (; i < argc; ++i) proc.argv.emplace_back(argv[i]);
    // A minimal Android environment unless the caller gave one.
    if (proc.envp.empty()) {
        proc.envp = {"PATH=/system/bin", "ANDROID_ROOT=/system", "ANDROID_DATA=/data"};
    }

    // Interrupts blocked host system calls of a guest thread that has a signal to handle.
    install_interrupt_handler();

    // Without the page table in the way, guard pages fault only if the host closes them too.
    proc.mem.host_guards = proc.fastmem;
    if (!proc.mem.init()) return 1;
    proc.mem.on_code_change = &invalidate_code;
    EntryState entry;
    std::string error;
    if (!load_program(proc, entry, error)) {
        log("arm32: %s", error.c_str());
        return 1;
    }
    Thread main_thread(proc, static_cast<int>(gettid()));
    main_thread.regs()[13] = entry.sp;
    main_thread.regs()[15] = entry.pc;
    // User mode, ARM or Thumb state as the entry address says.
    main_thread.jit().SetCpsr(0x10 | (entry.thumb ? 0x20 : 0));
    main_thread.publish();
    main_thread.run();
    // The main thread called exit() on its own; the process ends when the guest ends it.
    while (!proc.exiting.load()) pause();
    return proc.exit_code;
}
