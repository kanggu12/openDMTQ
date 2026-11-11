// The player's PC settings (player.h): what a computer chooses for the picture and the sound, where a phone's app has
// its own. The PC client writes them to a file before a start and names it with --settings; each line is key=value,
// and a line that starts with # is a note. A key it does not know, or a value it cannot read, keeps the default and is
// said in the log: an older player reads a newer client's file.
//
//   display       window | fullscreen        the window, or the whole display it is on (F11 switches either way)
//   window        auto | WxH                 the game's area in a window: fitted to the display, or this size
//   vsync         on | off                   frames on the display's refreshes, or as soon as they are drawn
//   fps           auto | N | unlimited       the most frames a second: the display's own rate, N (30 to 1000; with vsync
//                                            on, a whole fraction of the display's rate when one is within 10 % below
//                                            N, else N held by the clock with each frame on a refresh), or as many as
//                                            the computer makes (1000 at most)
//   render_scale  50..100                    the share of the game's area, in percent, the game draws at; the picture
//                                            is stretched to the area (less for the graphics card to draw)
//   upscaler      bilinear | fsr1 | nis      below 100 %, how the picture reaches the area's size: the plain stretch,
//                                            AMD FidelityFX Super Resolution 1 (EASU then RCAS), or NVIDIA Image Scaling
//   anti_aliasing off | cmaa2 | smaa |       the edges of the game's shapes smoothed: not at all, by Intel's CMAA 2 or by
//                 msaa2 | msaa4 | msaa8      SMAA 1x over the finished picture, or by drawing with 2, 4 or 8 samples
//   show_fps      off | on | top_left |      the frames a second and the frame time in that corner of the game; on is
//                 top_right | bottom_left |  the top left, beside a song's pause button (where the launcher puts it
//                 bottom_right               unless its position is chosen)
//   audio_device  default | <endpoint id>    the sound's device: Windows' default output, or one by its id
//                                            (player --audio-devices lists them)
//   audio_mode    shared | exclusive         with the computer's other sound, or the device alone (less latency)
//   audio_buffer  low | normal | safe        how much sound is kept ahead of the device: less latency, or fewer breaks
//   volume        0..100                     the game's sound, in percent
//
// On Linux, a developer's player, the window takes only its size (it reads no display timing and has no full screen),
// and the sound server picks the device and shares it: the buffer and the volume apply.
#include "player.h"

#include "jvm.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>

namespace player {

Settings& settings() {
    static Settings s;
    return s;
}

namespace {

// The text without the spaces and tabs around it.
std::string trim(const std::string& s) {
    const auto b = s.find_first_not_of(" \t\r");
    if (b == std::string::npos) return "";
    const auto e = s.find_last_not_of(" \t\r");
    return s.substr(b, e - b + 1);
}

// A whole number in [lo, hi] from the whole text, or false.
bool number(const std::string& v, int lo, int hi, int& out) {
    char* end = nullptr;
    const long n = std::strtol(v.c_str(), &end, 10);
    if (v.empty() || *end != '\0' || n < lo || n > hi) return false;
    out = static_cast<int>(n);
    return true;
}

}  // namespace

bool load_settings(const std::string& path) {
    std::ifstream f(utf8_path(path));
    if (!f) {
        jvm::log("player: no settings at %s: the defaults", path.c_str());
        return false;
    }
    Settings& s = settings();
    std::string line;
    while (std::getline(f, line)) {
        line = trim(line);
        if (line.empty() || line[0] == '#') continue;
        const auto eq = line.find('=');
        if (eq == std::string::npos) continue;
        const std::string key = trim(line.substr(0, eq)), value = trim(line.substr(eq + 1));
        bool ok = true;
        int n = 0;
        if (key == "display") {
            ok = value == "window" || value == "fullscreen";
            if (ok) s.fullscreen = value == "fullscreen";
        } else if (key == "window") {
            // The whole value two numbers: "1280x720x2" is not a size.
            int w = 0, h = 0, used = 0;
            if (value == "auto") {
                s.window_w = s.window_h = 0;
            } else if (std::sscanf(value.c_str(), "%dx%d%n", &w, &h, &used) == 2 && used == static_cast<int>(value.size()) && w >= 320 &&
                       h >= 180 && w <= 16384 && h <= 16384) {
                s.window_w = w;
                s.window_h = h;
            } else {
                ok = false;
            }
        } else if (key == "vsync") {
            ok = value == "on" || value == "off";
            if (ok) s.vsync = value == "on";
        } else if (key == "fps") {
            if (value == "auto") s.fps = 0;
            else if (value == "unlimited") s.fps = 1000;
            else if ((ok = number(value, 30, 1000, n))) s.fps = static_cast<float>(n);
        } else if (key == "render_scale") {
            if ((ok = number(value, 50, 100, n))) s.render_scale = n;
        } else if (key == "upscaler") {
            // The three names the client writes; anything else keeps the plain stretch.
            ok = value == "bilinear" || value == "fsr1" || value == "nis";
            if (ok) s.upscaler = value == "fsr1" ? Settings::Upscaler::kFsr1 : value == "nis" ? Settings::Upscaler::kNis : Settings::Upscaler::kBilinear;
        } else if (key == "anti_aliasing") {
            // Each name to its kind, in the order of the enum; a name it does not know keeps it off.
            static const char* const kNames[] = {"off", "cmaa2", "smaa", "msaa2", "msaa4", "msaa8"};
            ok = false;
            for (int i = 0; i < 6; ++i) {
                if (value != kNames[i]) continue;
                s.anti_aliasing = static_cast<Settings::AntiAliasing>(i);
                ok = true;
            }
        } else if (key == "show_fps") {
            // Each corner's name to its kind, in the order of the enum, and on for the top left, the counter's own
            // place; a name it does not know shows none.
            static const char* const kCorners[] = {"off", "top_left", "top_right", "bottom_left", "bottom_right"};
            ok = value == "on";
            if (ok) s.show_fps = Settings::ShowFps::kTopLeft;
            for (int i = 0; i < 5; ++i) {
                if (value != kCorners[i]) continue;
                s.show_fps = static_cast<Settings::ShowFps>(i);
                ok = true;
            }
        } else if (key == "audio_device") {
            s.audio_device = value == "default" ? "" : value;
        } else if (key == "audio_mode") {
            ok = value == "shared" || value == "exclusive";
            if (ok) s.audio_exclusive = value == "exclusive";
        } else if (key == "audio_buffer") {
            ok = value == "low" || value == "normal" || value == "safe";
            if (ok) s.audio_buffer = value == "low" ? 0 : value == "normal" ? 1 : 2;
        } else if (key == "volume") {
            if ((ok = number(value, 0, 100, n))) s.volume = n;
        } else {
            jvm::log("player: settings: %s is no setting of this player's: left out", key.c_str());
            continue;
        }
        if (!ok) jvm::log("player: settings: %s=%s cannot be read: the default stays", key.c_str(), value.c_str());
    }
    // The picture's passes by the names the file uses, for the line below.
    static const char* const kUpscalers[] = {"bilinear", "fsr1", "nis"};
    static const char* const kAntiAliasing[] = {"off", "cmaa2", "smaa", "msaa2", "msaa4", "msaa8"};
    static const char* const kCorners[] = {"off", "top left", "top right", "bottom left", "bottom right"};
    jvm::log("player: settings: %s, %s, vsync %s, fps %s, render %d%% (upscaler %s), anti-aliasing %s, frame counter %s; sound %s, %s, %s buffer, "
             "volume %d%%",
             s.fullscreen ? "full screen" : "a window",
             s.window_w ? (std::to_string(s.window_w) + "x" + std::to_string(s.window_h)).c_str() : "sized to the display",
             s.vsync ? "on" : "off", s.fps > 0 ? std::to_string(static_cast<int>(s.fps)).c_str() : "the display's",
             s.render_scale, kUpscalers[static_cast<int>(s.upscaler)], kAntiAliasing[static_cast<int>(s.anti_aliasing)],
             kCorners[static_cast<int>(s.show_fps)],
             s.audio_device.empty() ? "the default device" : "a chosen device", s.audio_exclusive ? "exclusive" : "shared",
             s.audio_buffer == 0 ? "a low" : s.audio_buffer == 1 ? "a normal" : "a safe", s.volume);
    return true;
}

}  // namespace player
