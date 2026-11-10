// The computer's broadcast (live_desktop.cpp says what runs where): what its threads share, among the files that run them:
// the control thread (live_desktop.cpp), the encoder thread (live_mf.cpp) and the render thread (live_capture.cpp). One
// definition of each for all three (inline), in a namespace of their own. Windows only.
#pragma once

#include "player.h"

#include "host.h"
#include "live_net.h"

#include <windows.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <mutex>
#include <thread>
#include <vector>

namespace arm32::desktop_live {

using Nanos = std::int64_t;
constexpr Nanos kSecond = 1000000000;

inline Nanos now_ns() {
    timespec t{};
    clock_gettime(CLOCK_MONOTONIC, &t);
    return static_cast<Nanos>(t.tv_sec) * kSecond + t.tv_nsec;
}

inline void sleep_ns(Nanos n) {
    if (n > 0) std::this_thread::sleep_for(std::chrono::nanoseconds(n));
}

// These threads start below the game's: when the PC is short of CPU, the game comes first.
inline void background_thread(const char* name) {
    player::name_thread(name);
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL);
}

// ---- state shared by the threads

inline std::atomic<bool> g_enabled{false};  // a server address, not turned off

inline std::atomic<Nanos> g_last_swap{0};   // when the game last swapped
inline std::atomic<bool> g_want{false};     // pictures and sound are to be sent right now
inline std::atomic<bool> g_on{false};       // the server has live view on for this player
inline std::atomic<bool> g_gave_up{false};  // this PC cannot do it: the server is still asked, for notices
inline std::atomic<bool> g_paused{false};   // the game is held still behind the player's menu: nothing is sent meanwhile
inline std::atomic<bool> g_warm_due{false};  // the server has answered: the render thread makes the conversion's program (warm_up)
inline std::atomic<int> g_failures{0};      // encoder start-ups that failed; three end the attempts

// The requests to the server, the upload thread and the network's quality step (src/live_net.cpp, a phone's too), with
// this player's names: its log's prefix, its User-Agent, and the names and start of its upload thread and of the thread
// that looks the server's name up.
inline live::Link g_link({"player: live", "opendmtq-player-live", "live-upload", "live-lookup", background_thread});

// What the server asks for (the top step); the step the network has taken it down to is g_link's.
inline std::atomic<int> g_fps{30}, g_height{720}, g_bitrate{2000000}, g_segment{2};
// The step this PC's encoder keeps up at: Windows' H.264 encoder runs on the processor, and a slower PC may not encode
// 1080p60 in time. Kept apart from the network's, and kept across streams (the processor stays the same).
inline std::atomic<int> g_encoder_step{0};
constexpr int kLastStep = live::kLastStep;

// The step in use: the lower quality of what the network and the encoder can take.
inline int step() { return std::max(g_link.network_step.load(std::memory_order_relaxed), g_encoder_step.load(std::memory_order_relaxed)); }
inline int step_fps(int s) { return s == 0 ? g_fps.load() : s == 1 ? std::max(g_fps.load() * 2 / 3, 1) : std::max(g_fps.load() / 2, 1); }
inline int step_height(int s) { return s <= 1 ? g_height.load() : s == 2 ? g_height.load() * 3 / 4 : g_height.load() / 2; }
inline int step_bitrate(int s) {
    static constexpr int percent[] = {100, 60, 35, 20};
    return static_cast<int>(static_cast<std::int64_t>(g_bitrate.load()) * percent[s] / 100);
}

// For the log, once a minute while live (every ten seconds with stats on); the segments' counts are g_link's.
inline std::atomic<std::uint64_t> g_captures{0}, g_capture_ns{0}, g_capture_max_ns{0}, g_skipped{0}, g_audio_frames{0};
// The other half of a picture's cost on the render thread: taking it out of its pixel buffer for the encoder, a frame or
// two after it was taken.
inline std::atomic<std::uint64_t> g_handed{0}, g_hand_ns{0}, g_hand_max_ns{0};
// What starting a capture cost the render thread, for the stats: the starts, and the dearest. A start is its objects
// (three textures and six pixel buffers each time, the conversion's program the first time in a context) and its first
// picture, whose draws may be where the driver compiles that program in earnest.
inline std::atomic<std::uint64_t> g_starts{0}, g_start_max_ns{0};
// Pictures left out because the encoder had not taken the ones before (its queue full), for its own step.
inline std::atomic<std::uint64_t> g_encoder_behind{0};
// Where a picture's taking goes, with stats on: the hook's own looks before it, saving the game's state, the scaled copy,
// the two conversion draws, the two reads into the pixel buffers, the fence, putting the state back.
constexpr int kPhases = 7;
inline std::atomic<std::uint64_t> g_phase_ns[kPhases];

// ---- pictures from the render thread to the encoder thread

struct Frame {
    std::vector<std::uint8_t> nv12;  // width x height of luma, then width x height / 2 of chroma pairs
    int width = 0, height = 0;
    Nanos pts = 0;                   // when the frame went to the screen
};

inline std::mutex g_frame_lock;
inline std::condition_variable g_frame_wake;
inline std::deque<Frame> g_frames;
// Picture buffers the encoder is done with, for the render thread's next pictures: a 1080p picture is 3 MB, and a new
// one each time would cost the render thread its allocation and the first touch of every page. Under g_frame_lock.
inline std::vector<std::vector<std::uint8_t>> g_spare;
constexpr std::size_t kSpare = 8;

// A picture's buffer back to the spares (under g_frame_lock), as long as there are few.
inline void recycle(std::vector<std::uint8_t>&& buffer) {
    if (g_spare.size() < kSpare && buffer.capacity()) g_spare.push_back(std::move(buffer));
}

// ---- what each file gives the others

// Media Foundation's functions, from mfplat.dll when Windows has it (live_mf.cpp); null without it.
struct Functions;
const Functions* mf();
// The mixer's period into the broadcast's sound, on the mixer's thread (live_mf.cpp).
void mix_tap(const float* stereo, std::size_t frames, int rate);
// The encoder thread, which the control thread starts at the first broadcast (live_mf.cpp).
void encoder_main();
// Once, at the first swap (live_desktop.cpp): the server's address, and whether this Windows can encode at all.
bool set_up();

}  // namespace arm32::desktop_live
