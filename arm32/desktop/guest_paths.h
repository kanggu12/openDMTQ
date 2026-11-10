// The guest's file names as this computer's and back (the runtime's path_hook and name_hook, main.cpp), apart from the
// rest so that the build machine tests them on their own (arm32/tests/host/guest_paths_test.cpp): where each of the app's
// folders lies here, and on Windows the fence around everything else.
//
// The app comes from a server, any server, and a name it gives may be made to lead out of its folders: by "..", by a
// drive ("C:/"), by Windows' own separator, or by a device's name ("COM1"). On Windows every name the guest gives lands
// in the player's folders (the guest's system and libraries), in the app's data folder, or nowhere: the call then fails
// as on a missing file. The desktop player for Linux is a developer's tool that reads the host's own /proc and /dev, and
// there the names keep their old way (fenced false).
#pragma once

#include <cstddef>
#include <string>
#include <string_view>

namespace player::paths {

// The app's folders: where Android would have put them (guest names), and where they are on this computer.
struct Layout {
    // The app's package name.
    std::string package;
    // The APK and the 32-bit library folder, where the package installer puts them.
    std::string apk, lib_dir;
    // Internal storage (Context.getFilesDir's parent) and the app's folder on external storage.
    std::string data_dir, external_dir;
    // On this computer: the guest's system, the agent, the game's libraries, the APK, and the folder for the app's data.
    std::string host_sysroot, host_agent, host_libs, host_apk, host_data;
    // The player's log socket, where /dev/socket/logdw points ("" before there is one).
    std::string log_socket;
};

// Where the guest's C library looks for the time zones (src/syscalls.cpp's kGuestTzdata).
inline constexpr std::string_view kGuestZoneFile = "/system/usr/share/zoneinfo/tzdata";

// A folder's name and what follows it, as one string (C++20 has no + for a string and a string_view).
inline std::string join(std::string_view folder, std::string_view rest) {
    std::string out(folder);
    out.append(rest);
    return out;
}

// True when `path` is `base` or inside it; `rest` is then what follows base ("" or "/..."). An empty base is no folder:
// every absolute name would be inside it.
inline bool under(std::string_view path, std::string_view base, std::string_view& rest) {
    // Not that folder, or a longer name beside it ("/sdcard2" is not in "/sdcard").
    if (base.empty() || path.compare(0, base.size(), base) != 0) return false;
    if (path.size() != base.size() && path[base.size()] != '/') return false;
    rest = path.substr(base.size());
    return true;
}

// Calls `f` with each part of a name between its slashes, the empty ones of repeated slashes included.
template <class F>
void each_part(std::string_view path, F&& f) {
    std::size_t at = 0;
    for (;;) {
        // The part runs to the next slash, or to the end.
        const std::size_t slash = path.find('/', at);
        f(path.substr(at, slash == std::string_view::npos ? std::string_view::npos : slash - at));
        if (slash == std::string_view::npos) return;
        at = slash + 1;
    }
}

// An absolute name as Linux reads it: repeated slashes as one, "." gone, ".." the folder above ("/.." is "/", as on
// Linux). A slash at its end stays, since it asks for a folder.
inline std::string normal(std::string_view path) {
    std::string out;
    each_part(path, [&out](std::string_view part) {
        // The space between two slashes, and "this folder": nothing.
        if (part.empty() || part == ".") return;
        // The folder above: the last part goes (at the root there is none, and the root stays).
        if (part == "..") {
            const std::size_t slash = out.rfind('/');
            out.resize(slash == std::string::npos ? 0 : slash);
            return;
        }
        out += '/';
        out += part;
    });
    // Nothing left is the root itself.
    if (out.empty()) return "/";
    // A folder asked for as one keeps its slash.
    if (path.back() == '/') out += '/';
    return out;
}

// True when a relative name's ".." go above where it starts: "a/../.." does, "a/.." and "./b" do not.
inline bool climbs(std::string_view path) {
    long depth = 0;
    bool above = false;
    each_part(path, [&](std::string_view part) {
        // One up: below the start is past where the name may go.
        if (part == "..") above = above || --depth < 0;
        // A name: one down. Empty parts and "." stay where they are.
        else if (!part.empty() && part != ".") ++depth;
    });
    return above;
}

// True when Windows names a device by `part` whatever folder it is in, with any extension: CON, PRN, AUX, NUL, COM and
// LPT with a digit or with ¹, ² or ³, CONIN$ and CONOUT$ ("nul.txt" and "Com1 " are devices too). A file of the
// guest's by such a name would be a port, a printer or the console.
inline bool windows_device(std::string_view part) {
    // What comes before the first dot, the spaces at its end aside, in capitals.
    std::string_view base = part.substr(0, part.find('.'));
    while (!base.empty() && base.back() == ' ') base.remove_suffix(1);
    std::string name(base);
    for (char& c : name)
        if (c >= 'a' && c <= 'z') c = static_cast<char>(c - 'a' + 'A');
    if (name == "CON" || name == "PRN" || name == "AUX" || name == "NUL" || name == "CONIN$" || name == "CONOUT$") return true;
    // The serial and parallel ports: a digit after COM or LPT, or a superscript one, two or three (UTF-8's C2 B9, C2 B2,
    // C2 B3), which Windows takes for theirs as well.
    const bool port = name.starts_with("COM") || name.starts_with("LPT");
    if (port && name.size() == 4 && name[3] >= '0' && name[3] <= '9') return true;
    return port && name.size() == 5 && name[3] == '\xC2' && (name[4] == '\xB9' || name[4] == '\xB2' || name[4] == '\xB3');
}

// True when Windows would read some part of `path` as something other than a file by that name: a device, or a name of
// dots and spaces alone, which Windows trims into another name or into none. "." and ".." are not looked at here:
// normal() takes them out of an absolute name, and climbs() counts them in a relative one.
inline bool windows_reads_otherwise(std::string_view path) {
    bool other = false;
    each_part(path, [&other](std::string_view part) {
        // The space between two slashes, and the two relative names.
        if (part.empty() || part == "." || part == "..") return;
        other = other || windows_device(part) || part.find_first_not_of(". ") == std::string_view::npos;
    });
    return other;
}

// The runtime's own names under /dev and /proc, which its Windows layer answers by name (src/win/files.cpp: the devices,
// /proc's files about the process and the machine, /proc/self/fd's links) and keeps from Windows' file system: they go
// to it as they are.
inline bool runtime_name(std::string_view path) { return path.starts_with("/dev/") || path.starts_with("/proc/"); }

// Where a refused name goes: a name in the data folder that Windows never lets be made ('<' and '>' are in no file's
// name), so that every call on it fails as on a missing file (ENOENT), a folder made on its way included.
inline std::string refused(const Layout& a) { return a.host_data + "/<refused>"; }

// The guest's root folder on Windows, where every name outside the app's folders lies, and the player's current folder
// there (main.cpp), which getcwd names "/" (guest_of).
inline std::string root_folder(const Layout& a) { return a.host_data + "/root"; }

// True when `path` is in one of the folders that stand for the guest's, with `host` its name on this computer. With
// `fenced`, a part of what follows the folder that Windows reads otherwise refuses the name.
inline bool in_folders(const Layout& a, const std::string& path, bool fenced, std::string& host) {
    std::string_view rest;
    // The rest of the name in the folder `folder` stands for, or refused.
    auto in = [&](const std::string& folder) {
        host = fenced && windows_reads_otherwise(rest) ? refused(a) : join(folder, rest);
        return true;
    };
    // The guest's system: its linker and libraries in the sysroot, the agent where it was built. No vendor libraries.
    if (path == "/system/bin/arm32-agent") return host = a.host_agent, true;
    if (path == "/system/bin/linker") return host = a.host_sysroot + "/bin/linker", true;
    if (under(path, "/system/lib", rest)) return in(a.host_sysroot + "/lib");
    if (under(path, "/vendor/lib", rest)) return in(a.host_sysroot + "/vendor-lib");
    // The game's libraries, under the linker's search path and under the folder the package installer would use.
    if (under(path, "/arm32/lib", rest) || under(path, a.lib_dir, rest)) return in(a.host_libs);
    if (path == a.apk) return host = a.host_apk, true;
    // The guest's log goes to the player's log socket.
    if (path == "/dev/socket/logdw" && !a.log_socket.empty()) return host = a.log_socket, true;
    // Internal storage, under both of the names Android gives it.
    if (under(path, a.data_dir, rest) || under(path, "/data/user/0/" + a.package, rest)) return in(a.host_data + "/internal");
    // The app's folder on external storage, and the rest of external storage, under each of its names.
    if (under(path, a.external_dir, rest) || under(path, "/sdcard/Android/data/" + a.package, rest)) return in(a.host_data + "/external");
    if (under(path, "/storage/emulated/0", rest) || under(path, "/sdcard", rest)) return in(a.host_data + "/sdcard");
    return false;
}

// The name on this computer of the guest's `given`. Fenced (Windows): nothing the guest names reaches outside the
// player's folders and the app's data folder; unfenced (Linux): a name outside the app's folders stays as it is.
inline std::string host_of(const Layout& a, const std::string& given, bool fenced) {
    std::string host;
    // Linux: the app's folders, and any other name as it is, the host's own /proc and /dev among them.
    if (!fenced) return in_folders(a, given, false, host) ? host : given;
    // An empty name as it is: fstatat's AT_EMPTY_PATH names its folder descriptor by it, and every other call fails on it.
    if (given.empty()) return given;
    // A drive or a stream ("C:/", "//?/C:/", "name:stream") or Windows' own separator: neither is in a name of the
    // guest's, and either leads past the folders below.
    if (given.find_first_of(":\\") != std::string::npos) return refused(a);
    // A relative name: the layer puts it below the current folder (the guest's root at the start, main.cpp, or one the
    // guest moved to among its own) or below a folder descriptor's, where it stays unless its ".." climb above that.
    if (given[0] != '/') return climbs(given) || windows_reads_otherwise(given) ? refused(a) : given;
    // An absolute name, "." and ".." and repeated slashes gone first, so that no folder below can be climbed out of.
    const std::string path = normal(given);
    if (in_folders(a, path, true, host)) return host;
    // The runtime's names its Windows layer answers by itself.
    if (runtime_name(path)) return path;
    // The time zones by any spelling (src/syscalls.cpp maps the usual one before this hook).
    if (path == kGuestZoneFile) return a.host_sysroot + "/usr/share/zoneinfo/tzdata";
    // Anything else (the rest of /data and /system, /sys, /etc...): under the guest's root in the data folder, missing
    // until the guest makes it there, as a phone keeps the rest of its file system from an app.
    if (windows_reads_otherwise(path)) return refused(a);
    return path == "/" ? root_folder(a) : root_folder(a) + path;
}

// The guest's name of the file `host` on this computer (a descriptor's, a mapping's): the folders above, back; on
// Windows the guest's root too. Anything else is as it is.
inline std::string guest_of(const Layout& a, const std::string& host, bool fenced) {
    std::string_view rest;
    if (under(host, a.host_libs, rest)) return join(a.lib_dir, rest);
    if (under(host, a.host_sysroot + "/lib", rest)) return join("/system/lib", rest);
    if (host == a.host_apk) return a.apk;
    if (under(host, a.host_data + "/internal", rest)) return join(a.data_dir, rest);
    if (under(host, a.host_data + "/external", rest)) return join(a.external_dir, rest);
    if (under(host, a.host_data + "/sdcard", rest)) return join("/storage/emulated/0", rest);
    // The guest's root is its "/", and what is in it is named from there.
    if (fenced && under(host, root_folder(a), rest)) return rest.empty() ? std::string("/") : std::string(rest);
    return host;
}

// Whether `name` is a package name as Android's are made, ^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$: parts of letters,
// digits and underscores between dots, two at least, the first starting with a letter. The player names the app's folder
// on this computer after it, which nothing else may reach (a slash, "..", a drive).
inline bool valid_package(std::string_view name) {
    auto letter = [](char c) { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'); };
    auto word = [&letter](char c) { return letter(c) || (c >= '0' && c <= '9') || c == '_'; };
    // The first part starts with a letter (so not with a dot either).
    if (name.empty() || !letter(name.front())) return false;
    int dots = 0;
    for (std::size_t i = 0; i < name.size(); ++i) {
        if (name[i] != '.') {
            // Within a part: letters, digits and underscores only.
            if (!word(name[i])) return false;
            continue;
        }
        // A dot between two parts: neither at the end nor beside another, so that no part is empty.
        if (i + 1 == name.size() || name[i + 1] == '.') return false;
        ++dots;
    }
    // Two parts at least.
    return dots > 0;
}

}  // namespace player::paths
