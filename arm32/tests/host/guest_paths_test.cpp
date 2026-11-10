// Checks the guest's file names as the desktop player maps them (arm32/desktop/guest_paths.h) on the build machine:
//   c++ -std=c++20 -Wall -Wextra -Iarm32/desktop arm32/tests/host/guest_paths_test.cpp -o /tmp/guest_paths_test && /tmp/guest_paths_test
//
// The app's folders where they were (both ways, on Linux and on Windows); on Windows the names that would lead out of
// them (.., a drive, a backslash, //?/, a relative ..), refused or kept in the data folder; the runtime's own names under
// /dev and /proc as they are; everything else under the guest's root; the package names a data folder may be named
// after; and the player's folders the guest may only read (its system, the app's libraries and the APK).
#include "guest_paths.h"

#include <cstdio>
#include <string>
#include <utility>
#include <vector>

namespace {

using player::paths::guest_of;
using player::paths::host_of;
using player::paths::Layout;
using player::paths::read_only;
using player::paths::valid_package;

int g_checks = 0, g_failures = 0;

// An app as a PC client's start lays it out: the runtime beside the player, the libraries and the data in the user's
// folder, with "/" between the parts as main.cpp spells them (made-up names).
Layout layout() {
    Layout a;
    a.package = "org.example.game";
    a.apk = "/data/app/org.example.game-1/base.apk";
    a.lib_dir = "/data/app/org.example.game-1/lib/arm";
    a.data_dir = "/data/data/org.example.game";
    a.external_dir = "/storage/emulated/0/Android/data/org.example.game";
    a.host_sysroot = "C:/Program Files/OpenDMTQ/player/runtime/sysroot";
    a.host_agent = "C:/Program Files/OpenDMTQ/player/runtime/arm32-agent";
    a.host_libs = "C:/Users/someone/AppData/Local/OpenDMTQ/org.example.game/lib";
    a.host_apk = "C:/Users/someone/AppData/Local/OpenDMTQ/client/servers/a/app.apk";
    a.host_data = "C:/Users/someone/AppData/Local/OpenDMTQ/org.example.game/data";
    a.log_socket = a.host_data + "/logdw";
    return a;
}

// One answer against the one expected.
void expect(const char* what, const std::string& given, const std::string& got, const std::string& want) {
    ++g_checks;
    if (got == want) return;
    ++g_failures;
    std::printf("FAIL %s \"%s\": \"%s\", expected \"%s\"\n", what, given.c_str(), got.c_str(), want.c_str());
}

// A guest name's host name, fenced (Windows) and unfenced (Linux).
void fenced(const std::string& guest, const std::string& want) { expect("fenced", guest, host_of(layout(), guest, true), want); }
void unfenced(const std::string& guest, const std::string& want) { expect("unfenced", guest, host_of(layout(), guest, false), want); }

}  // namespace

int main() {
    const Layout a = layout();
    const std::string data = a.host_data, root = data + "/root", refused = data + "/<refused>";

    // The app's folders, the same on both: the names the game was seen to use, and each folder's own name.
    const std::vector<std::pair<std::string, std::string>> folders = {
        {"/system/bin/arm32-agent", a.host_agent},
        {"/system/bin/linker", a.host_sysroot + "/bin/linker"},
        {"/system/lib/libc.so", a.host_sysroot + "/lib/libc.so"},
        {"/system/lib", a.host_sysroot + "/lib"},
        {"/vendor/lib/libEGL.so", a.host_sysroot + "/vendor-lib/libEGL.so"},
        {"/arm32/lib/libz.so", a.host_libs + "/libz.so"},
        {a.lib_dir + "/libmain.so", a.host_libs + "/libmain.so"},
        {a.apk, a.host_apk},
        {"/dev/socket/logdw", a.log_socket},
        {a.data_dir, data + "/internal"},
        {a.data_dir + "/", data + "/internal/"},
        {a.data_dir + "/files/settings.bin", data + "/internal/files/settings.bin"},
        {"/data/user/0/org.example.game/shared_prefs/prefs.xml", data + "/internal/shared_prefs/prefs.xml"},
        {a.external_dir + "/files/il2cpp/Metadata", data + "/external/files/il2cpp/Metadata"},
        {a.external_dir + "/cache/UnityShaderCache/0154ffd8", data + "/external/cache/UnityShaderCache/0154ffd8"},
        {"/sdcard/Android/data/org.example.game/files/logs", data + "/external/files/logs"},
        {"/storage/emulated/0/Download/a.png", data + "/sdcard/Download/a.png"},
        {"/sdcard", data + "/sdcard"},
        {"/sdcard/a.txt", data + "/sdcard/a.txt"},
    };
    for (const auto& [guest, host] : folders) {
        fenced(guest, host);
        unfenced(guest, host);
    }

    // Linux: any other name as it is, the host's own /proc and /dev among them, and nothing taken apart (the developer's
    // tool keeps its old way, dots and all).
    for (const char* name : {"/proc/self/maps", "/proc/cpuinfo", "/dev/null", "/sys/devices/system/cpu/possible", "/etc/openal/alsoft.conf",
                             "relative/name", "../up", "C:/x", "/sdcard2/x", ""})
        unfenced(name, name);
    unfenced("/data/data/org.example.game/../../x", data + "/internal/../../x");

    // Windows, "..": an absolute name cannot climb out of a folder or above the root, wherever the dots are.
    fenced("/data/data/org.example.game/files/../../../../Users/someone/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/a.bat",
           root + "/Users/someone/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/a.bat");
    fenced("/../../../x", root + "/x");
    fenced("/sdcard/../../x", root + "/x");
    fenced("/system/lib/../../../../x", root + "/x");
    fenced("/arm32/lib/./../lib/libz.so", a.host_libs + "/libz.so");
    fenced("/data/data/org.example.game/files/../cache/a", data + "/internal/cache/a");
    fenced(a.external_dir + "/files/./a//b", data + "/external/files/a/b");
    fenced("/proc/../x", root + "/x");
    fenced("/dev/socket/../../x", root + "/x");

    // A drive, a stream and Windows' separator: refused, wherever they are.
    for (const char* name : {"C:/Windows/System32/a.dll", "c:a", "/C:/x", "/sdcard/a:b", "//?/C:/x", "\\\\?\\C:\\x", "\\\\server\\share\\x",
                             "/data\\..\\x", "a\\b", "/sdcard/x\\..\\..\\y", "::$DATA"})
        fenced(name, refused);
    // A name that starts as Windows' device or network names do is only the root's: no network, no device namespace.
    fenced("//server/share/x", root + "/server/share/x");
    fenced("//?/UNC/server/share/x", root + "/?/UNC/server/share/x");
    fenced("//./PhysicalDrive0", root + "/PhysicalDrive0");

    // Relative names: below where they start, as they are; climbing above it, refused.
    for (const char* name : {"a.txt", "a/b", "./a", "a/./b", "a/../b", "a/..", "a//b/../../c"}) fenced(name, name);
    for (const char* name : {"..", "../a", "a/../../b", "./../a", "a/b/../../../c"}) fenced(name, refused);

    // Windows' devices and the names it trims, in any folder: refused.
    for (const char* name : {"/COM1", "//./COM1", "/sdcard/LPT1", "/sdcard/lpt9.log", "/data/data/org.example.game/files/con.txt",
                             "/data/data/org.example.game/files/nul", "/x/aux/y", "/x/Prn .txt", "/x/COM\xC2\xB9", "/x/CONIN$", "nul",
                             "a/con.log", "/x/...", "/x/. ./y", "/sdcard/ ", "a/.../b"})
        fenced(name, refused);
    // Names that only look like them are files.
    for (const char* name : {"/x/console", "/x/COM10", "/x/com", "/x/nul_", "/x/..a", "/x/.a"}) fenced(name, root + name);

    // The runtime's own names: as they are, for its Windows layer to answer.
    for (const char* name : {"/proc/self/maps", "/proc/self/stat", "/proc/self/task/123/comm", "/proc/self/fd/3", "/proc/cpuinfo",
                             "/proc/meminfo", "/dev/null", "/dev/zero", "/dev/random", "/dev/urandom", "/dev/__properties__"})
        fenced(name, name);
    fenced("/dev/./null", "/dev/null");
    fenced("/proc//self/stat", "/proc/self/stat");
    // The time zones by any spelling.
    fenced("/system/usr/share/zoneinfo/tzdata", a.host_sysroot + "/usr/share/zoneinfo/tzdata");
    fenced("/system//usr/./share/zoneinfo/tzdata", a.host_sysroot + "/usr/share/zoneinfo/tzdata");

    // Everything else: under the guest's root, where it is missing until the guest makes it.
    fenced("/", root);
    fenced("/.", root);
    fenced("/..", root);
    for (const char* name : {"/data/misc/zoneinfo/current/tzdata", "/system/fonts/a.ttf", "/etc/openal/alsoft.conf",
                             "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", "/sys/devices/system/cpu/online", "/SymbolMap-ARMv7",
                             "/data/app/org.example.game-1/base.apk/assets/a", "/sdcard2/x", "/dev", "/proc", "/Users/someone/x"})
        fenced(name, root + name);
    fenced("/data/local/tmp/", root + "/data/local/tmp/");
    // An empty name stays empty (fstatat's AT_EMPTY_PATH).
    fenced("", "");

    // Back: each folder's files by the guest's names for them, and on Windows the root's.
    auto back = [&](const std::string& host, bool fence, const std::string& want) { expect(fence ? "guest_of fenced" : "guest_of", host, guest_of(a, host, fence), want); };
    for (bool fence : {false, true}) {
        back(a.host_libs + "/libmain.so", fence, a.lib_dir + "/libmain.so");
        back(a.host_sysroot + "/lib/libc.so", fence, "/system/lib/libc.so");
        back(a.host_apk, fence, a.apk);
        back(data + "/internal/files/a", fence, a.data_dir + "/files/a");
        back(data + "/external/cache", fence, a.external_dir + "/cache");
        back(data + "/sdcard/Download/a.png", fence, "/storage/emulated/0/Download/a.png");
        back("/memfd:jit-cache", fence, "/memfd:jit-cache");
    }
    back(root + "/etc/openal/alsoft.conf", true, "/etc/openal/alsoft.conf");
    back(root, true, "/");
    back(root + "s/x", true, root + "s/x");
    back(root + "/x", false, root + "/x");
    // There and back: a name the guest gave, as the guest would name its file.
    for (const char* name : {"/etc/a/b", "/", "/data/data/org.example.game/files/a", "/storage/emulated/0/a", "/system/lib/libm.so"})
        back(host_of(a, name, true), true, name);

    // Package names: Android's, which may name a folder; anything else, refused.
    auto package = [](const char* name, bool want) {
        ++g_checks;
        if (valid_package(name) == want) return;
        ++g_failures;
        std::printf("FAIL package \"%s\": %s, expected %s\n", name, want ? "refused" : "taken", want ? "taken" : "refused");
    };
    for (const char* name : {"org.example.game", "a.b", "com.example_2.x9", "A1_.b2", "a.1", "a._", "a.b.c.d.e"}) package(name, true);
    for (const char* name : {"", "game", ".a.b", "a..b", "a.b.", "1a.b", "_a.b", "a/b.c", "a.b/../c", "..", "a.b c", "a.b-c", "C:.x",
                             "a.b\\c", "\xC3\xA9.x", "a.b\n"})
        package(name, false);

    // Read only on Windows: the guest's system, the agent, the app's libraries and the APK, whichever way a call names
    // them; the app's data and the guest's root stay its own to change.
    auto fixed = [](const std::string& host, bool want) {
        ++g_checks;
        if (read_only(layout(), host) == want) return;
        ++g_failures;
        std::printf("FAIL read only \"%s\": %s, expected %s\n", host.c_str(), want ? "changeable" : "read only", want ? "read only" : "changeable");
    };
    // Each name the guest has for them, through the fence.
    for (const char* name : {"/system/lib/libc.so", "/system/lib", "/system/lib/", "/system/bin/linker", "/system/bin/arm32-agent", "/vendor/lib/a.so",
                             "/arm32/lib/libmain.so", "/arm32/lib", "/data/app/org.example.game-1/lib/arm/libil2cpp.so",
                             "/data/app/org.example.game-1/base.apk", "/system/usr/share/zoneinfo/tzdata", "/system/lib/../lib/libm.so"})
        fixed(host_of(a, name, true), true);
    // The app's own folders and the guest's root, through the fence: as before.
    for (const char* name : {"/data/data/org.example.game/files/a", "/data/user/0/org.example.game/shared_prefs/b.xml",
                             "/storage/emulated/0/Android/data/org.example.game/cache/c", "/sdcard/Download/d", "/system", "/system/etc/hosts",
                             "/system/lib2/x", "/data/app/org.example.game-1/oat", "/data/local/tmp/e", "/"})
        fixed(host_of(a, name, true), false);
    // The same folders as Windows may spell them: its separator, another case, "." and "..", a slash at the end, the
    // relative names the layer puts after a folder.
    fixed("C:\\Program Files\\OpenDMTQ\\player\\runtime\\sysroot\\lib\\libc.so", true);
    fixed("c:/program files/opendmtq/PLAYER/Runtime/SysRoot/lib/libc.so", true);
    fixed(a.host_libs + "/./sub/../libmain.so", true);
    fixed(a.host_libs + "/", true);
    fixed(a.host_data + "/root/../../lib/libmain.so", true);
    fixed(a.host_apk + "/", true);
    // Beside them, by a longer name, or above them: not theirs.
    fixed(a.host_sysroot + "2/lib/libc.so", false);
    fixed(a.host_libs + ".old/libmain.so", false);
    fixed(a.host_apk + ".part", false);
    fixed(a.host_agent + "-new", false);
    fixed("C:/Program Files/OpenDMTQ/player/runtime", false);
    fixed(a.host_sysroot + "/lib/../../../player.log", false);
    fixed(a.host_data + "/internal/files/a", false);
    fixed("", false);
    // A layout with an empty folder (none given) makes nothing read only.
    {
        Layout none = layout();
        none.host_sysroot = none.host_libs = none.host_apk = none.host_agent = "";
        ++g_checks;
        if (read_only(none, a.host_sysroot + "/lib/libc.so") || read_only(none, "/")) {
            ++g_failures;
            std::printf("FAIL read only with no folders given: something read only\n");
        }
    }

    if (g_failures) {
        std::printf("%d of %d checks FAILED\n", g_failures, g_checks);
        return 1;
    }
    std::printf("%d checks\nALL CHECKS PASSED\n", g_checks);
    return 0;
}
