// A start with no arguments (a double click): the player takes everything from the folder it is in, as the OpenDMTQ
// server's download for a computer lays it out:
//
//   the player and ANGLE's DLLs   the program
//   player.conf                   the app: its name, its package and its APK's file name, as the server wrote them
//   the APK                       the app the server built for its address, the one its phones install
//   runtime/sysroot, runtime/arm32-agent
//                                 the guest's system (its linker, libraries and time zones) and the agent
//
// The app's 32-bit libraries come out of the APK once for each APK. They, the app's data and the log stay in the user's
// own folder for programs: %LOCALAPPDATA%\OpenDMTQ\<package> on Windows, ~/.local/share/OpenDMTQ/<package> (or under
// $XDG_DATA_HOME) on Linux. A double click has no console: the log goes to player.log there, kept to a few megabytes.
#include "player.h"

#include "jvm.h"

#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <map>
#include <string>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>
#include <vector>

#ifdef _WIN32
#include <windows.h>

#include "error_box_win32.h"
// The C runtime's descriptors for a Windows handle (its io.h is Linux's here).
extern "C" int _open_osfhandle(intptr_t handle, int flags);
extern "C" int _dup2(int from, int to);
#endif

namespace player {

namespace {

// The log's size before it starts over, its last part kept as player.log.1: two of them on the disk at most.
constexpr long long kLogLimit = 8ll << 20;
// A start from the player's own folder (a double click), which has no console to say what went wrong in; and where its
// log goes once it is sent there, which a message box names.
bool g_own_folder = false;
std::string g_log_path;
// The folder under the user's folder for programs.
constexpr const char* kVendor = "OpenDMTQ";

// What a player can act on, in their language: English, or Korean on a Korean computer.
std::string say(const char* english, const char* korean) { return host_locale().first == "ko" ? korean : english; }

// A value the server wrote, as the log and a message box may show it: printable ASCII as it is and any other byte as
// '?' (no line break of its own in the log), cut to a line of the box.
std::string shown(const std::string& text) {
    std::string out;
    for (char c : text.substr(0, 80)) out += c >= ' ' && c <= '~' ? c : '?';
    return out;
}

#ifdef _WIN32
// UTF-8 of Windows' UTF-16, and back: the runtime's paths are UTF-8, as the user's folder may have any name.
std::string utf8(const std::wstring& w) {
    int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), static_cast<int>(w.size()), nullptr, 0, nullptr, nullptr);
    std::string out(static_cast<std::size_t>(n > 0 ? n : 0), '\0');
    if (n > 0) WideCharToMultiByte(CP_UTF8, 0, w.c_str(), static_cast<int>(w.size()), out.data(), n, nullptr, nullptr);
    return out;
}
std::wstring utf16(const std::string& s) {
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()), nullptr, 0);
    std::wstring out(static_cast<std::size_t>(n > 0 ? n : 0), L'\0');
    if (n > 0) MultiByteToWideChar(CP_UTF8, 0, s.c_str(), static_cast<int>(s.size()), out.data(), n);
    return out;
}
#endif

// The folder the player's program is in, with "/" between its parts (the runtime joins paths with "/").
std::string program_folder() {
    std::string path;
#ifdef _WIN32
    std::vector<wchar_t> buf(32768);
    DWORD n = GetModuleFileNameW(nullptr, buf.data(), static_cast<DWORD>(buf.size()));
    path = utf8(std::wstring(buf.data(), n));
    for (char& c : path)
        if (c == '\\') c = '/';
#else
    char buf[4096];
    ssize_t n = readlink("/proc/self/exe", buf, sizeof buf - 1);
    if (n > 0) path.assign(buf, static_cast<std::size_t>(n));
#endif
    std::size_t slash = path.rfind('/');
    return slash == std::string::npos ? std::string(".") : path.substr(0, slash);
}

// The user's own folder for programs' data.
std::string user_folder() {
#ifdef _WIN32
    if (const wchar_t* local = _wgetenv(L"LOCALAPPDATA"); local && *local) {
        std::string s = utf8(local);
        for (char& c : s)
            if (c == '\\') c = '/';
        return s;
    }
    // Every Windows sets LOCALAPPDATA; its usual place otherwise.
    const wchar_t* home = _wgetenv(L"USERPROFILE");
    std::string s = home ? utf8(home) + "/AppData/Local" : std::string(".");
    for (char& c : s)
        if (c == '\\') c = '/';
    return s;
#else
    if (const char* xdg = std::getenv("XDG_DATA_HOME"); xdg && *xdg == '/') return xdg;
    const char* home = std::getenv("HOME");
    return std::string(home && *home ? home : ".") + "/.local/share";
#endif
}

// A folder and its parents, made where missing; true when it is there.
bool make_folder(const std::string& path) {
    // Each parent in turn: one that exists already (a drive, the user's folder) only fails to be made again.
    for (std::size_t at = path.find('/', 1); at != std::string::npos; at = path.find('/', at + 1)) mkdir(path.substr(0, at).c_str(), 0755);
    mkdir(path.c_str(), 0755);
    struct stat st {};
    return stat(path.c_str(), &st) == 0 && S_ISDIR(st.st_mode);
}

// A whole file's text; false when it cannot be read.
bool read_text(const std::string& path, std::string& out) {
    int fd = open(path.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) return false;
    char buf[4096];
    for (ssize_t n; (n = read(fd, buf, sizeof buf)) > 0;) out.append(buf, static_cast<std::size_t>(n));
    close(fd);
    return true;
}

// Writes `data` to `path` through a file beside it that takes its name once complete, and on the disk before it does:
// a write stopped by the program or by the power leaves no half a library behind.
bool write_file(const std::string& path, const std::vector<std::uint8_t>& data) {
    const std::string part = path + ".part";
    int fd = open(part.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0755);
    if (fd < 0) return false;
    std::size_t done = 0;
    while (done < data.size()) {
        ssize_t n = write(fd, data.data() + done, data.size() - done);
        if (n <= 0) break;
        done += static_cast<std::size_t>(n);
    }
    const bool synced = done == data.size() && fsync(fd) == 0;
    close(fd);
    return synced && rename(part.c_str(), path.c_str()) == 0;
}

// player.conf's settings: one "name=value" a line, "#" for a comment.
std::map<std::string, std::string> settings(const std::string& text) {
    std::map<std::string, std::string> out;
    std::size_t start = 0;
    while (start < text.size()) {
        std::size_t end = text.find('\n', start);
        std::string line = text.substr(start, end == std::string::npos ? std::string::npos : end - start);
        start = end == std::string::npos ? text.size() : end + 1;
        // A file edited on Windows ends its lines with CR LF.
        while (!line.empty() && (line.back() == '\r' || line.back() == ' ')) line.pop_back();
        if (line.empty() || line[0] == '#') continue;
        std::size_t eq = line.find('=');
        if (eq != std::string::npos) out[line.substr(0, eq)] = line.substr(eq + 1);
    }
    return out;
}

// The app's 32-bit libraries, out of its APK into `libs` unless they are those of the APK there now: libs/.from names
// each by its CRC-32 and size, so that an APK built again with the same name and size (for another address of the
// server) still gives its own.
bool unpack_libraries(const std::string& apk_name, const std::string& libs, std::string& error) {
    struct stat st {};
    if (stat(app().host_apk.c_str(), &st) != 0) {
        error = say("The app is not beside the player: unzip the download again, whole, and start the player in its folder.",
                    "플레이어 옆에 앱이 없습니다. 내려받은 파일을 다시 통째로 압축 풀고, 그 폴더에서 플레이어를 실행하세요.") +
                "\n(" + apk_name + ")";
        return false;
    }
    const std::vector<std::string> names = apk_names("lib/armeabi-v7a/");
    if (names.empty()) {
        error = "the app holds no 32-bit libraries";
        return false;
    }
    // One line for each library: its name and its stamp.
    std::string from;
    for (const std::string& name : names) from += name + " " + apk_stamp(name) + "\n";
    std::string was;
    if (read_text(libs + "/.from", was) && was == from) return true;
    for (const std::string& name : names) {
        std::vector<std::uint8_t> data;
        const std::string file = name.substr(name.rfind('/') + 1);
        if (!apk_entry(name, data) || !write_file(libs + "/" + file, data)) {
            error = "cannot unpack " + file + " into " + libs;
            return false;
        }
    }
    // Written last: a stopped unpacking starts again.
    write_file(libs + "/.from", std::vector<std::uint8_t>(from.begin(), from.end()));
    jvm::log("player: %zu libraries unpacked from %s", names.size(), apk_name.c_str());
    return true;
}

// The log's file size; -1 when there is none.
long long file_size(const std::string& path) {
    struct stat st {};
    return stat(path.c_str(), &st) == 0 ? static_cast<long long>(st.st_size) : -1;
}

// The log's text so far goes to player.log.1, and player.log starts empty: the writers append, so they carry on at
// its new end.
void start_log_over(const std::string& path) {
    std::string text;
    if (read_text(path, text)) write_file(path + ".1", std::vector<std::uint8_t>(text.begin(), text.end()));
#ifdef _WIN32
    HANDLE h = CreateFileW(utf16(path).c_str(), GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
                           FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h != INVALID_HANDLE_VALUE) {
        SetEndOfFile(h);
        CloseHandle(h);
    }
#else
    if (::truncate(path.c_str(), 0) != 0) jvm::log("player: cannot start %s over", path.c_str());
#endif
}

// The player's output (its log, with the game's lines in it) appended to player.log in `folder` from now on.
void log_to(const std::string& folder) {
    const std::string path = folder + "/player.log";
    g_log_path = path;
    // A log grown past its limit starts over at the start too.
    if (file_size(path) > kLogLimit) start_log_over(path);
#ifdef _WIN32
    // Appending only: every write lands at the end, wherever another writer left it.
    HANDLE h = CreateFileW(utf16(path).c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_ALWAYS,
                           FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return;
    // Windows' standard output and error (the runtime's descriptors 1 and 2 write to them), and the C runtime's.
    SetStdHandle(STD_OUTPUT_HANDLE, h);
    SetStdHandle(STD_ERROR_HANDLE, h);
    int fd = _open_osfhandle(reinterpret_cast<intptr_t>(h), 0x0008 /* _O_APPEND */ | 0x8000 /* _O_BINARY */);
    if (fd >= 0) {
        _dup2(fd, 1);
        _dup2(fd, 2);
    }
#else
    int fd = open(path.c_str(), O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
    if (fd < 0) return;
    dup2(fd, 1);
    dup2(fd, 2);
    close(fd);
#endif
    // Line by line from here: a log read while the game runs, or after it stops, has every line written.
    std::setvbuf(stdout, nullptr, _IOLBF, 4096);
    std::setvbuf(stderr, nullptr, _IONBF, 0);
    // Looked at every half minute: past its limit, it starts over.
    std::thread([path] {
        for (;;) {
            std::this_thread::sleep_for(std::chrono::seconds(30));
            if (file_size(path) > kLogLimit) start_log_over(path);
        }
    }).detach();
}

}  // namespace

bool use_own_folder(const std::string& folder, std::string& error) {
    g_own_folder = true;
    App& a = app();
    // The runtime is the player's own; the app is beside it, or in the folder the PC client names (with "/" between its
    // parts, as the runtime joins paths).
    const std::string mine_dir = program_folder();
    std::string here = folder.empty() ? mine_dir : folder;
    for (char& c : here)
        if (c == '\\') c = '/';
    while (here.size() > 1 && here.back() == '/') here.pop_back();
    std::string text;
    if (!read_text(here + "/player.conf", text)) {
        error = say("The app's folder is missing player.conf: download the app again in the OpenDMTQ launcher (Online).",
                    "앱 폴더에 player.conf가 없습니다. OpenDMTQ 런처의 온라인에서 앱을 다시 받으세요.");
        return false;
    }
    std::map<std::string, std::string> conf = settings(text);
    if (conf["package"].empty() || conf["apk"].empty()) {
        error = say("player.conf names no app: download the app again in the OpenDMTQ launcher (Online).",
                    "player.conf에 앱이 적혀 있지 않습니다. OpenDMTQ 런처의 온라인에서 앱을 다시 받으세요.");
        return false;
    }
    // The package names the app's folder in the user's (below), and the server wrote it: only a name as Android's are
    // made, which can name no other folder ("..", a slash, a drive).
    if (!paths::valid_package(conf["package"])) {
        error = say("The app's package name in player.conf is not a valid one: download the app again in the OpenDMTQ launcher (Online).",
                    "player.conf에 적힌 앱의 패키지 이름이 올바르지 않습니다. OpenDMTQ 런처의 온라인에서 앱을 다시 받으세요.") +
                "\n(" + shown(conf["package"]) + ")";
        return false;
    }
    a.package = conf["package"];
    if (!conf["name"].empty()) a.title = conf["name"];
    a.host_apk = here + "/" + conf["apk"];
    a.host_sysroot = mine_dir + "/runtime/sysroot";
    a.host_agent = mine_dir + "/runtime/arm32-agent";
    // The app's own folder, its log first: what follows may fail, and its reason belongs in the log.
    const std::string mine = user_folder() + "/" + kVendor + "/" + a.package;
    if (!make_folder(mine + "/lib") || !make_folder(mine + "/data")) {
        error = "cannot make the folder " + mine;
        return false;
    }
    log_to(mine);
    a.host_libs = mine + "/lib";
    a.host_data = mine + "/data";
    return unpack_libraries(conf["apk"], a.host_libs, error);
}

void show_error(const std::string& what) {
    jvm::log("player: %s", what.c_str());
#ifdef _WIN32
    // Only a start by a double click has no console to say it in: a start with arguments (a test, a developer) has its
    // output, and no box that waits for a click.
    if (!g_own_folder) return;
    // The launcher's own dialog as a window of its own (error_box_win32.cpp): what happened in the user's language, the
    // reason as the log has it, and where the log is when it has one yet.
    const bool korean = host_locale().first == "ko";
    // The reason as a sentence: its first letter up, a full stop at its end.
    std::string detail = what;
    if (!detail.empty() && detail[0] >= 'a' && detail[0] <= 'z') detail[0] = static_cast<char>(detail[0] - 'a' + 'A');
    if (!detail.empty() && detail.back() != '.') detail += '.';
    if (!g_log_path.empty()) {
        std::string where = g_log_path;
        for (char& c : where)
            if (c == '/') c = '\\';
        detail += (korean ? "\n\n기록: " : "\n\nThe log: ") + where;
    }
    overlay::error_box(korean ? "게임을 시작하지 못했습니다." : "The game could not start.", detail, korean);
#endif
}

}  // namespace player
