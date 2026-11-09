// Diagnostics: stderr for the command-line runner, the Android log for both on Android; on a desktop host, stderr
// alone, and switches from the environment only.
#include "runtime.h"

#ifdef __ANDROID__
#include <android/log.h>
#include <sys/system_properties.h>
#endif
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unistd.h>  // _exit

#ifdef _WIN32
// The two calls exit_now needs, declared here: the runtime's files have Linux's names, and windows.h stays in src/win.
extern "C" __declspec(dllimport) void* __stdcall GetCurrentProcess();
extern "C" __declspec(dllimport) int __stdcall TerminateProcess(void* process, unsigned code);
#endif

namespace arm32 {

bool requested(const char* env, const char* property, bool fallback) {
    // The environment wins: set to anything but 0 means on.
    if (const char* e = getenv(env)) return std::strcmp(e, "0") != 0;
#ifdef __ANDROID__
    char value[PROP_VALUE_MAX] = "";
    __system_property_get(property, value);
    if (!value[0]) return fallback;
    return std::strcmp(value, "1") == 0;
#else
    // A desktop host has no system properties: the environment alone decides.
    (void)property;
    return fallback;
#endif
}

std::string setting(const char* env, const char* property) {
    if (const char* e = getenv(env)) return e;
#ifdef __ANDROID__
    char value[PROP_VALUE_MAX] = "";
    __system_property_get(property, value);
    return value;
#else
    (void)property;
    return {};
#endif
}

bool g_trace = requested("ARM32_TRACE", "debug.arm32.trace");
bool g_stats = requested("ARM32_STATS", "debug.arm32.stats");

void exit_now(int code) {
    std::fflush(stdout);
    std::fflush(stderr);
#ifdef _WIN32
    // ExitProcess, which _exit calls on Windows, stops the other threads wherever they are (in the graphics driver mid
    // frame, in Media Foundation mid picture) and then runs every DLL's detach code, which can wait forever for a lock
    // one of those threads held: the process then stays, frozen, with its memory and its files. TerminateProcess runs
    // none of it, and Windows frees what the process had.
    TerminateProcess(GetCurrentProcess(), static_cast<unsigned>(code));
#endif
    _exit(code);
}

void log(const char* fmt, ...) {
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    std::vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    std::fprintf(stderr, "%s\n", buf);
#ifdef __ANDROID__
    __android_log_write(ANDROID_LOG_INFO, "arm32", buf);
#endif
}

}  // namespace arm32
