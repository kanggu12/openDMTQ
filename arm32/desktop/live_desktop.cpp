// Live view on a computer: while the server's owner has it on for this player, the game's picture and sound go to the
// server as MPEG-TS segments, with the requests a phone makes (src/live.cpp is the phone's, docs/live.md the protocol):
// /live/state about every 15 seconds while the game is on screen, /live/upload for each segment, /live/end when it goes
// off. It is off by default, and nothing here may ever get in the way of the game: a broadcast may stutter or stop, the
// game may not.
//
// What runs where, and in which file (what the threads share is in live_state.h):
//
// - The render thread, at each swap (desktop_live_frame, live_capture.cpp): with live view off, a few atomic loads. With
//   it on, a picture is due at the stream's frame rate: the finished frame is scaled to the stream's size with one blit,
//   turned into NV12 (the encoder's format: a plane of luma, then one of chroma at half the size) by two small draws, and
//   read into a pixel buffer without waiting. A later swap, once the GPU says it is done, copies it out for the encoder.
//   Nothing on this thread waits for the GPU, and everything of the game's state it touches is put back.
// - The mixer's thread (mixer.cpp): its mix, before the player's volume, into a ring of the encoder's (mix_tap,
//   live_mf.cpp), left out when full.
// - The encoder thread (live_mf.cpp): Windows' own H.264 and AAC encoders (Media Foundation, found by type), and the
//   MPEG-TS writer (live_ts.cpp), cut at a key frame every segment. Only this thread waits on an encoder.
// - The upload thread and the control thread (this file): as on a phone, with its requests and upload queue
//   (src/live_net.cpp). A slow upload drops segments rather than holding on to them, and turns the quality down: frame
//   rate and bitrate first, then the picture's height.
//
// The server's address is the one the app was built for (the packer's tweaks file, its line "server <host[:port]>"),
// the ids are the one the game signs in with (device_id()), and the server's notice shows over the game's window
// (show_notice()). PLAYER_LIVE=0 turns it all off; PLAYER_LIVE_SERVER=<host:port> asks another server.
//
// Windows only: on Linux, a developer's player, there is no encoder to ask and nothing runs (the other two files are
// Windows' alone, arm32/CMakeLists.txt).
#include "player.h"

#include "host.h"
#include "live.h"

#include <EGL/egl.h>
#include <EGL/eglext.h>

namespace arm32 {
// The desktop's own entry points, which frames.cpp calls: at each swap, and when the game destroys a context.
void desktop_live_frame(EGLDisplay display, EGLSurface surface);
void desktop_live_context_destroyed(EGLContext context);
// The game held still behind the player's menu (true) or going on (false), which window_win32.cpp tells.
void desktop_live_paused(bool paused);
}  // namespace arm32

#ifndef _WIN32

namespace arm32 {
void desktop_live_frame(EGLDisplay, EGLSurface) {}
void desktop_live_context_destroyed(EGLContext) {}
void desktop_live_paused(bool) {}
}  // namespace arm32

#else

#include "live_state.h"
#include "mixer.h"

#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <thread>

namespace arm32::desktop_live {

namespace {

// How often the control thread asks the server.
constexpr Nanos kPollEvery = 15 * kSecond;
// No swap for this long: the game is away (minimized, closed), so nothing is sent and the server is not asked.
constexpr Nanos kAwayAfter = 5 * kSecond;
// The server's first answer within this of the control thread's start comes at the game's first screens, where making
// the conversion's program ahead costs nobody a frame (warm_up); one later may come in a song.
constexpr Nanos kWarmWithin = 20 * kSecond;

// ---- the control thread

void control_main() {
    background_thread("live-control");
    // When it started: the game's first frame, about (warm_up).
    const Nanos started = now_ns();
    Nanos next_poll = 0;
    bool was_on = false;
    const std::string lang = player::host_locale().first == "ko" ? "ko" : "en";
    for (;;) {
        sleep_ns(kSecond);
        const Nanos now = now_ns();
        const bool away = now - g_last_swap.load(std::memory_order_relaxed) > kAwayAfter;
        const bool want_now = g_on.load() && !away && !g_gave_up.load() && !g_paused.load();
        if (g_want.load() != want_now) g_want.store(want_now);
        // Away from the screen: nothing to send. The next request goes out as soon as the game is back.
        if (away) {
            next_poll = 0;
            continue;
        }
        if (now < next_poll && (g_on.load() || !was_on)) continue;
        next_poll = now + kPollEvery;
        // The id the game signs in with, which the server knows this player by: kept from the data folder, where anything
        // may stand, and so through the same filter as a phone's ids (live_net.cpp) before it goes in a URL.
        std::string ids;
        live::add_id(ids, player::device_id());
        if (ids.empty()) {
            // An id a request cannot name as it is (a hand-edited file): said once, and no broadcast.
            static bool told = false;
            if (!told) log("player: live: the device id is not letters, digits, '-' and '_': no broadcasts");
            told = true;
            continue;
        }
        static bool first_request = true;
        if (first_request) {
            first_request = false;
            log("player: live: asking the server");
        }
        // The answer, checked (live_net.cpp parse_state). None: as things were.
        const live::State state = g_link.ask_state(ids, lang.c_str());
        if (!state.answered) continue;
        // The server's first answer, at the game's first screens: the render thread makes the conversion's program now,
        // once (warm_up), ahead of any broadcast. A first answer later than kWarmWithin (a server or network down at the
        // start) may come in a song, where a compile would hold a frame even of a player who never broadcasts: the first
        // capture makes it then, as before.
        static bool warmed = false;
        if (!warmed && now_ns() - started < kWarmWithin) g_warm_due.store(true, std::memory_order_relaxed);
        warmed = true;
        g_link.set_identity(ids, state);
        if (state.on) {
            g_fps.store(state.fps);
            g_height.store(state.height);
            g_bitrate.store(state.bitrate);
            g_segment.store(state.segment);
            static bool workers = false;
            if (!workers) {
                workers = true;
                std::thread(encoder_main).detach();
                std::thread([] { g_link.run(); }).detach();
            }
        }
        // Gone off: the stream's end once its last segments are out, and the top step for the next time.
        if (was_on && !state.on) g_link.end_stream();
        g_on.store(state.on);
        was_on = state.on;
        const std::string& notice = state.toast;
        // A PC that cannot encode sends nothing: the server's "you are live" would not be true here.
        if (!notice.empty() && state.on && g_gave_up.load()) {
            log("player: live: the server's notice left out, this PC sends no broadcast: %s", notice.c_str());
        } else if (!notice.empty()) {
            player::show_notice(notice, state.on);
        }
    }
}

// The server's address, from the packer's line in the tweaks file beside the app's libraries ("server <host[:port]>"),
// or PLAYER_LIVE_SERVER. Empty without one.
std::string server_address() {
    if (const char* test = std::getenv("PLAYER_LIVE_SERVER"); test && *test) return test;
    std::ifstream f(player::utf8_path(player::app().host_libs + "/libarm32t-tweaks.so"));
    std::string line, server;
    while (std::getline(f, line)) {
        std::istringstream in(line);
        std::string word, value;
        if ((in >> word >> value) && word == "server") server = value;
    }
    return server;
}

}  // namespace

// Once, at the first swap: the server's address, and whether this Windows can encode at all.
bool set_up() {
    if (!requested("PLAYER_LIVE", "", true)) return false;
    const std::string server = server_address();
    if (server.empty()) return false;
    if (!mf()) {
        log("player: live: this Windows has no Media Foundation (an N edition without its Media Feature Pack): no broadcasts");
        return false;
    }
    g_link.set_server(live::parse_server(server));
    // A refused segment (403): off until the control thread's next request says otherwise.
    g_link.on_refused = [] {
        g_on.store(false);
        g_want.store(false);
    };
    player::audio::set_mix_tap(mix_tap);
    log("player: live: asks %s", server.c_str());
    std::thread(control_main).detach();
    return true;
}

}  // namespace arm32::desktop_live

namespace arm32 {

void desktop_live_paused(bool paused) {
    // The broadcast's own names (live_state.h).
    using namespace desktop_live;
    g_paused.store(paused);
    // Held still: the stream ends now, its last segment closed as usual, rather than after the seconds a game away from
    // the screen is given; a stream of its own starts as the game goes on (the control thread's next look).
    if (paused) g_want.store(false);
}

}  // namespace arm32

#endif
