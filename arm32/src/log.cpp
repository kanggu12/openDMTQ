// Diagnostics: stderr for the command-line runner, the Android log for both.
#include "runtime.h"

#include <android/log.h>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sys/system_properties.h>

namespace arm32 {

bool requested(const char* env, const char* property, bool fallback) {
    // The environment wins: set to anything but 0 means on.
    if (const char* e = getenv(env)) return std::strcmp(e, "0") != 0;
    char value[PROP_VALUE_MAX] = "";
    __system_property_get(property, value);
    if (!value[0]) return fallback;
    return std::strcmp(value, "1") == 0;
}

bool g_trace = requested("ARM32_TRACE", "debug.arm32.trace");
bool g_stats = requested("ARM32_STATS", "debug.arm32.stats");

void log(const char* fmt, ...) {
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    std::vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    std::fprintf(stderr, "%s\n", buf);
    __android_log_write(ANDROID_LOG_INFO, "arm32", buf);
}

}  // namespace arm32
