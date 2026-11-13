// Keyboard play: a song's lanes played with the computer's keys (keyboard_play.h has the rules, settings.cpp the keys).
//
// How the game takes a touch screen's fingers (libil2cpp.so, by IL2CPP's own names): once a frame while a song plays, the
// score player (DMTScorePlayer) has its input (DMQInput) update. DMTInputBase.Run calls the class's OnUpdate through its
// virtual table (slot 7), which reads Unity's touches and hands each to DMTInputBase.SetPress with its place; the press
// lands in the track whose band holds it, and the score player then judges the presses against its notes in that frame,
// at that frame's song time. Keyboard play puts a stub of its own in that slot. The game's own OnUpdate runs first, as it
// always does; then each lane key that is down gives one press of its own, at the place the game will judge the lane's
// next note at: the note's own place, a repeat point's group's first note (where the game judges repeats), a drag's
// point on its curve while it runs; or where the timeline crosses the lane when no note is near. A key held keeps its
// press there, so a hold is held. The game judges these presses as it judges fingers: the timing, the windows, the
// combo, the score and the gauge are all its own.
//
// Three more slots say what the song does: OnReset (slot 5) at each play's start (a retry too), Pause (8) and Stop (10).
// The score player skips the input's update while paused, so the pause and the stop let every lane key go: a key held
// through them is no press until it comes up and down again. The game's code is found by name through IL2CPP's API and
// checked against the places this player was written for: each method's address, the slots that hold them and the
// fields read. Anything else, and keyboard play stays out (said once in the log): the game plays by touch as before.
//
// A play that a lane key pressed is marked to the server: the request that saves it (game.savePlayResult) goes with the
// header X-OpenDMTQ-Keys: 1 (keyplay_mark_save, from web.cpp), which the server keeps with the play.
//
// The log says a song's lanes as it starts and its count of presses as it ends; with the player's stats on, what its
// frames cost (a stats line every five seconds); with PLAYER_TRACE_KEYS=1 (a check's), each press and the note it aims
// at, and at the song's end the game's own judgement of its notes by type.
#include "keyplay.h"

#include "guest.h"
#include "host.h"
#include "player.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <vector>

namespace player {

namespace {

using arm32::gaddr;
using arm32::Guest;
using arm32::Thread;

// The game's code as this player was written for it: places in libil2cpp.so (RVAs, offsets from its start), checked
// at the start, never trusted.
// Where an Il2CppClass's virtual table starts in this IL2CPP (metadata 23, 32-bit): each slot two words, the code and
// its method's information.
constexpr std::uint32_t kVtable = 0xb4;
// The input class's slots keyboard play takes, each with the name of DMQInput's override in it and that override's RVA
// (all but OnUpdate are empty: the class has nothing to do there). OnUpdate is kSlots[1].
struct Slot {
    std::uint32_t slot;
    const char* name;
    std::uint32_t rva;
};
constexpr Slot kSlots[] = {{5, "OnReset", 0x10b597c}, {7, "OnUpdate", 0x10b5984}, {8, "Pause", 0x10b5b70}, {10, "Stop", 0x10b5b78}};
constexpr int kSlotCount = sizeof kSlots / sizeof kSlots[0];
// The host functions behind the stubs, one a slot: reentrant ones (they call the game's code), at a range nothing else
// of the runtime's uses (the JNI and the bridges are below 0x4000).
constexpr std::uint32_t kHookNumber = arm32::kReentrantBase + 0x7000;
// The methods keyboard play calls, by class, name and their count of arguments, and their RVAs.
constexpr std::uint32_t kRvaSetPress = 0x1095e40, kRvaTickToReal = 0x109c574, kRvaDragPos = 0x10a0608, kRvaTickToTime = 0xbc8050;

// The fields read, at their offsets in the objects (checked by name at the start). The score player (DMTScorePlayer and
// its base ScorePlayerBase): the song's tick and its time as the game judges by (the calibration in it), its state
// (Playing 0, Paused 1, Stop 2, Closed 3), its tracks, its clock of ticks to milliseconds, whether it is over or at its
// end, and its notes.
namespace sp {
constexpr std::uint32_t CurTick = 0x50, CalMsTime = 0x70, State = 0x88, TrackStart = 0x8c, TrackCount = 0x90, TimeSection = 0x9c,
                        Gameover = 0x12d, End = 0x12e, NoteEvents = 0x138;
}  // namespace sp
// A note (DMTScoreEvent and its base ScoreEventBase): its track, tick, judgement (0 until judged), place, the tick a hold or
// drag was taken at (0 until then), its type, and a repeat point's group's first note.
namespace ev {
constexpr std::uint32_t Track = 0xc, Tick = 0x18, Duration = 0x1c, Judgement = 0x1e, Place = 0x2c, StartTick = 0x48, Type = 0x50, First = 0x60;
}  // namespace ev
// The fields with their names as IL2CPP has them, in the class they are looked up in (a base's are found from it).
struct Field {
    int cls;
    const char* name;
    std::uint32_t offset;
};
// The classes they are in: 0 the score player, 1 the note.
constexpr Field kFields[] = {
    {0, "<CurTick>k__BackingField", sp::CurTick},
    {0, "<CurCalibrationMsTime>k__BackingField", sp::CalMsTime},
    {0, "<State>k__BackingField", sp::State},
    {0, "<PlayTrackStartNum>k__BackingField", sp::TrackStart},
    {0, "<PlayTrackCnt>k__BackingField", sp::TrackCount},
    {0, "<TimeSection>k__BackingField", sp::TimeSection},
    {0, "<Gameover>k__BackingField", sp::Gameover},
    {0, "<End>k__BackingField", sp::End},
    {0, "<NoteEvents>k__BackingField", sp::NoteEvents},
    {1, "<TrackIdx>k__BackingField", ev::Track},
    {1, "tick", ev::Tick},
    {1, "duration", ev::Duration},
    {1, "<Judgement>k__BackingField", ev::Judgement},
    {1, "<RealPosition>k__BackingField", ev::Place},
    {1, "<JudgementStartTick>k__BackingField", ev::StartTick},
    {1, "<NoteType>k__BackingField", ev::Type},
    {1, "<FirstNote>k__BackingField", ev::First},
};
// The note types the press is placed differently for: repeat points (judged at their group's first note: 2, and the
// Vita's 5 and 7, which no chart has) and drags (4).
bool is_repeat(std::uint32_t type) { return type == 2 || type == 5 || type == 7; }
constexpr std::uint32_t kDrag = 4;
// The game's windows around a note's time, from its judgement table (BREAK's 210 ms: 1.4 times it early, 0.6 late): a
// press further from every note than these is judged against none, so a lane's next note is the first one inside them.
constexpr std::int64_t kEarlyMs = 294, kLateMs = 126;
// The keys of keyboard play's presses, as the game tells its fingers apart: far above Unity's finger numbers. Each lane's
// two keys have two numbers each, used in turn at each fresh press, so that a key let go and pressed again between two
// frames (even twice, in a long frame) is a new finger for the game (a press that came in), as a finger lifted and put
// down again is.
constexpr int kKeyBase = 0x4b00;
// A check's trace (PLAYER_TRACE_KEYS=1): each lane key's press with the note it aims at, and at a song's end the game's
// own judgement of its notes by type, in the log. Read once.
bool trace_keys() {
    static const bool on = [] {
        const char* v = std::getenv("PLAYER_TRACE_KEYS");
        return v && *v && *v != '0';
    }();
    return on;
}
// The note types by name, as the trace says them, and the judgements (0 none yet, 1 BREAK, 2 to 12 MAX 1 to MAX 100).
const char* type_name(std::uint32_t type, std::uint16_t duration) {
    switch (type) {
    case 0: return "tap";
    case 1: return "chain point";
    case 2: return duration > 6 ? "long repeat" : "repeat point";
    case 3: return "hold";
    case 4: return "drag";
    default: return "other";
    }
}

// The guest's memory, read where the game keeps its objects.
Guest& g() { return Guest::get(); }
std::uint32_t u32(gaddr a) { return *g().proc.mem.ptr<std::uint32_t>(a); }
std::uint8_t u8(gaddr a) { return *g().proc.mem.ptr<std::uint8_t>(a); }
float f32(gaddr a) { return *g().proc.mem.ptr<float>(a); }
std::int64_t i64(gaddr a) {
    // Copied, not read through a cast: a 64-bit field of the guest's may be 4-byte aligned.
    std::int64_t v;
    std::memcpy(&v, g().proc.mem.host(a), 8);
    return v;
}
bool readable(gaddr a, std::uint32_t n) { return a && g().proc.mem.readable(a, n); }
// A float as the 32 bits a guest call takes it in.
std::uint32_t bits(float f) {
    std::uint32_t b;
    std::memcpy(&b, &f, 4);
    return b;
}
// An IL2CPP array's length and its first element (the object's header, its bounds, its length, then the data).
std::uint32_t array_length(gaddr a) { return readable(a, 16) ? u32(a + 0xc) : 0; }
gaddr array_data(gaddr a) { return a + 0x10; }
// The steady clock in milliseconds, which the window's thread compares the last frame's with.
long long steady_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

// The hook's state: still to be put in, in, or out for good (keyboard off, or the game not the one expected).
enum { kWaiting, kIn, kOff };
std::atomic<int> g_hook{kWaiting};
// libil2cpp.so's handle in the guest, once loaded.
gaddr g_il2cpp = 0;
// The game's code, once checked: the input's own overrides in the slots (kSlots' order), the calls made, and guest
// memory for what those calls hand back through a hidden pointer.
gaddr g_original[kSlotCount] = {};
gaddr g_set_press = 0, g_tick_to_real = 0, g_drag_pos = 0, g_tick_to_time = 0, g_scratch = 0;

// The lane keys as the window's thread gives them (keyboard_play.h): read by the game's thread once a frame.
keys::LaneState g_lanes;
// What the game's thread last said of the song: being played, when its last frame was (steady_ms), how many lanes it has.
std::atomic<bool> g_playing{false};
std::atomic<long long> g_frame_ms{0};
std::atomic<int> g_lane_count{0};
// The game held still by the window (the question, minimised).
std::atomic<bool> g_held{false};
// A lane key pressed in the play being played or just ended: the save of that play is a keyboard play's.
std::atomic<bool> g_keyed{false};
// A check's keys at song times (keyplay_song_keys), in time order: set before the game starts, read by its thread only.
std::vector<SongKey> g_song_keys;

// One note of a lane, as the play's first frame read it: the game's object, its time in the song (milliseconds, as the
// game judges it), and whether it is a drag.
struct Note {
    gaddr at;
    std::int64_t ms;
    bool drag;
};
// A lane key's press, as the game's thread keeps it: the count of its key's presses it has seen, where it presses, the
// note it aims at (0: none), and for a drag the tick its curve starts at.
struct Finger {
    unsigned seen = 0;
    float x = 0, y = 0;
    gaddr target = 0;
    bool drag = false;
    std::uint32_t drag_tick = 0;
    // Whether it pressed in the last frame (a check's trace says when it stops).
    bool pressing = false;
    // Which of the key's two finger numbers it presses with: the other one at each fresh press, whatever the count of
    // presses between two frames was.
    int which = 0;
};
// The play being played (on the game's thread only).
struct Play {
    // The score player it is, and whether its notes are still to be read (its first frame, or a start again).
    gaddr player = 0;
    bool fresh = true;
    // The game's first track of the play and how many there are (the lanes, top first).
    std::uint32_t start = 0;
    int lanes = 0;
    // Each lane's notes in time order, and the first of them not yet past the late window for good.
    std::vector<Note> notes[4];
    std::size_t past[4] = {};
    // Each lane's two keys' presses.
    Finger fingers[4][2];
    // The let go the fingers last caught up with (keyboard_play.h's epoch).
    unsigned epoch = 0;
    // The lane keys' presses in the play, and whether its end was said.
    unsigned presses = 0;
    bool ended = false;
    // The check's next key at a song time.
    std::size_t song_key = 0;
};
Play g_play;

// What a frame costs with the player's stats on (ARM32_STATS): the game's own input update and keyboard play's part after
// it, over the frames of a song, said every five seconds.
struct Cost {
    std::vector<float> game, ours;
    long long since = 0;
    // The last frame's time: a gap of a second (a pause, a song's end, the next song) starts the five seconds again.
    long long last = 0;
    // This frame's time in sending a check's keys (PLAYER_KEYS at song times), which is the check's and not keyboard
    // play's: under Wine each key sent takes a trip through its server.
    float posting_us = 0;
} g_cost;

// A guest copy of a string for the il2cpp calls, which only read them: one for each name, kept.
gaddr guest_string(const std::string& s) {
    static std::map<std::string, gaddr> strings;
    auto it = strings.find(s);
    if (it != strings.end()) return it->second;
    const gaddr a = g().strdup(s);
    strings[s] = a;
    return a;
}

// The game's TickToRealPosition(track, tick) and GetDragNoteCurvePos(note): a point handed back through a hidden pointer.
void tick_to_real(Thread& t, gaddr player, std::uint32_t track, std::uint32_t tick, float& x, float& y) {
    t.call(g_tick_to_real, {g_scratch, player, track, tick, 0});
    x = f32(g_scratch);
    y = f32(g_scratch + 4);
}
void drag_pos(Thread& t, gaddr player, gaddr note, float& x, float& y) {
    t.call(g_drag_pos, {g_scratch, player, note, 0});
    x = f32(g_scratch);
    y = f32(g_scratch + 4);
}

// The play's end, once (`how` it ended: "ended", "is over", "stopped", "was left"): every lane key lets go, and the log
// says how many presses the lane keys made in it.
void finish(Play& p, const char* how) {
    if (p.ended || !p.player) return;
    p.ended = true;
    const std::string why = std::string("the song ") + how;
    keyplay_let_go(why.c_str());
    // A song that ended with no lane key pressed saves as a touch play's; one over or left saves nothing to say so of.
    const bool saves = std::string(how) == "ended";
    jvm::log("player: keyboard play: %s, with %u presses of the lane keys%s", why.c_str(), p.presses,
             p.presses || !saves ? "" : " (its save is a touch play's)");
    if (!trace_keys()) return;
    // The game's judgement of every note, by type: how many, at MAX 100, lower, BREAK, and none yet (left before it).
    struct Count {
        int notes = 0, top = 0, lower = 0, broke = 0, none = 0;
    };
    std::map<std::string, Count> by_type;
    for (const auto& lane : p.notes) {
        for (const Note& n : lane) {
            Count& c = by_type[type_name(u32(n.at + ev::Type), *g().proc.mem.ptr<std::uint16_t>(n.at + ev::Duration))];
            const std::uint8_t j = u8(n.at + ev::Judgement);
            ++c.notes;
            if (j == 12) ++c.top;
            else if (j >= 2) ++c.lower;
            else if (j == 1) ++c.broke;
            else ++c.none;
        }
    }
    for (const auto& [type, c] : by_type) {
        jvm::log("player: keys: %s: %d notes, %d MAX 100, %d lower, %d BREAK, %d not judged", type.c_str(), c.notes, c.top, c.lower, c.broke, c.none);
    }
}

// An address or an offset as the log gives them, in hex.
std::string hex(std::uint32_t v) {
    char b[16];
    std::snprintf(b, sizeof b, "%#x", v);
    return b;
}

// A play's first frame: its lanes, and each lane's notes with their times from the game's own clock of ticks, in order.
void begin(Thread& t, gaddr player) {
    Play& p = g_play;
    // The play before, if it had not said its end (a retry from its pause): said now.
    if (p.player && !p.ended) finish(p, "was left");
    const auto from = std::chrono::steady_clock::now();
    p = Play{};
    p.player = player;
    p.fresh = false;
    p.start = u32(player + sp::TrackStart);
    p.lanes = static_cast<int>(std::min<std::uint32_t>(u32(player + sp::TrackCount), 4));
    // The notes: a FixedArray of the game's (its items' array at 0x8, its count at 0xc).
    const gaddr list = u32(player + sp::NoteEvents);
    const gaddr items = readable(list, 16) ? u32(list + 8) : 0;
    const std::uint32_t count = readable(list, 16) ? u32(list + 0xc) : 0;
    const gaddr section = u32(player + sp::TimeSection);
    std::size_t notes = 0;
    for (std::uint32_t i = 0; i < count && i < array_length(items); ++i) {
        const gaddr n = u32(array_data(items) + i * 4);
        // A note of the play's tracks, each field read within the object.
        if (!readable(n, ev::First + 4)) continue;
        const std::uint32_t track = u32(n + ev::Track);
        if (track < p.start || track >= p.start + static_cast<std::uint32_t>(p.lanes)) continue;
        // Its time as the game's own clock gives it for its tick (tempo changes and all), in milliseconds.
        const std::int64_t ms = readable(section, 4) ? static_cast<std::int64_t>(t.call(g_tick_to_time, {section, u32(n + ev::Tick), 0})) : 0;
        p.notes[track - p.start].push_back({n, ms, u32(n + ev::Type) == kDrag});
        ++notes;
    }
    // Each lane in time order (the game's own order of notes is by tick, so mostly already).
    for (auto& lane : p.notes) std::stable_sort(lane.begin(), lane.end(), [](const Note& a, const Note& b) { return a.ms < b.ms; });
    // The keys' presses so far are no news to the play: only presses from now on play it.
    p.epoch = g_lanes.epoch();
    for (int l = 0; l < 4; ++l) {
        for (int k = 0; k < 2; ++k) p.fingers[l][k].seen = g_lanes.presses(l, k);
    }
    g_lane_count.store(p.lanes, std::memory_order_release);
    // A new play: no lane key has pressed it yet (its save goes without the mark until one does).
    g_keyed.store(false, std::memory_order_release);
    const double took = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - from).count();
    jvm::log("player: keyboard play: a song of %d lanes (%s), %zu notes read in %.1f ms", p.lanes, keys::text(settings().lanes_of(p.lanes)).c_str(),
             notes, took);
}

// A fresh press of lane `lane`: the note it aims at, the lane's first one the game would judge now (unjudged, in the
// windows, the earliest; not `skip`, which the lane's other key took in this frame), and the place it presses at.
void aim(Thread& t, gaddr player, Play& p, int lane, std::int64_t now, std::uint32_t tick, gaddr skip, Finger& f) {
    std::vector<Note>& notes = p.notes[lane];
    std::size_t& past = p.past[lane];
    // Notes later than the late window behind now are past for good: the game has judged them or will break them.
    while (past < notes.size() && notes[past].ms < now - kLateMs) ++past;
    f.target = 0;
    f.drag = false;
    for (std::size_t i = past; i < notes.size() && notes[i].ms <= now + kEarlyMs; ++i) {
        const gaddr n = notes[i].at;
        // Judged already, or a hold or drag the game is holding now, or the other key's: the next one.
        if (n == skip || u8(n + ev::Judgement) != 0 || u32(n + ev::StartTick) != 0) continue;
        f.target = n;
        f.drag = notes[i].drag;
        break;
    }
    if (f.target) {
        // Where the game judges a press for it: a repeat point at its group's first note, any other note at its own.
        gaddr at = f.target;
        if (is_repeat(u32(f.target + ev::Type)) && readable(u32(f.target + ev::First), ev::First + 4)) at = u32(f.target + ev::First);
        f.x = f32(at + ev::Place);
        f.y = f32(at + ev::Place + 4);
        // A drag: its curve from its own tick on.
        if (f.drag) f.drag_tick = u32(f.target + ev::Tick);
    } else {
        // No note near: where the timeline crosses the lane now, as a finger put down there would be.
        tick_to_real(t, player, p.start + static_cast<std::uint32_t>(lane), tick, f.x, f.y);
    }
}

// One frame of a play, after the game's own update: the check's keys due, then each lane key's press.
void frame(Thread& t, gaddr self, gaddr player) {
    Play& p = g_play;
    // A new score player, or a play started again (OnReset): its notes and lanes now, at its first frame.
    if (player != p.player || p.fresh) begin(t, player);
    // Over (the gauge ran out) or at its end: no lane plays any more. The game runs this update only while Playing.
    const bool over = u8(player + sp::Gameover) || u8(player + sp::End);
    const bool playing = u32(player + sp::State) == 0 && !over;
    g_frame_ms.store(steady_ms(), std::memory_order_release);
    g_playing.store(playing, std::memory_order_release);
    if (!playing) {
        finish(p, u8(player + sp::Gameover) ? "is over" : "ended");
        return;
    }
    // The song's time as the game judges by, and its tick.
    const std::int64_t now = i64(player + sp::CalMsTime);
    const std::uint32_t tick = u32(player + sp::CurTick);
    // A check's keys whose time has come, to the window as Windows sends keys: the window's thread takes them as any.
    // Their time is kept apart from keyboard play's own with the stats on.
    if (p.song_key < g_song_keys.size() && g_song_keys[p.song_key].ms <= static_cast<double>(now)) {
        const auto from = std::chrono::steady_clock::now();
        while (p.song_key < g_song_keys.size() && g_song_keys[p.song_key].ms <= static_cast<double>(now)) {
            keyplay_post_key(g_song_keys[p.song_key].scan, g_song_keys[p.song_key].down);
            ++p.song_key;
        }
        g_cost.posting_us += std::chrono::duration<float, std::micro>(std::chrono::steady_clock::now() - from).count();
    }
    // A let go since the last frame: the presses made before it are forgotten with it.
    if (const unsigned epoch = g_lanes.epoch(); epoch != p.epoch) {
        p.epoch = epoch;
        for (int l = 0; l < 4; ++l) {
            for (int k = 0; k < 2; ++k) p.fingers[l][k].seen = g_lanes.presses(l, k);
        }
    }
    for (int l = 0; l < p.lanes; ++l) {
        // The note the lane's first key aimed at in this frame, which its second does not take too.
        gaddr taken = 0;
        for (int k = 0; k < 2; ++k) {
            Finger& f = p.fingers[l][k];
            const unsigned presses = g_lanes.presses(l, k);
            const bool down = g_lanes.is_down(l, k);
            const bool fresh = presses != f.seen;
            f.seen = presses;
            if (fresh) {
                // A new press (or one shorter than a frame, already up: still pressed for this frame).
                aim(t, player, p, l, now, tick, taken, f);
                taken = f.target;
                ++p.presses;
                // The other finger number: the game sees the last one lifted and this one come in, a new press.
                f.which ^= 1;
                if (trace_keys()) {
                    // The press and what it aims at: the note's type and time, or none near.
                    if (f.target) {
                        const std::int64_t at = std::find_if(p.notes[l].begin(), p.notes[l].end(), [&](const Note& n) { return n.at == f.target; })->ms;
                        jvm::log("player: keys: lane %d key %d down at %lld ms, aiming at a %s of %lld ms (%+lld)", l, k, static_cast<long long>(now),
                                 type_name(u32(f.target + ev::Type), *g().proc.mem.ptr<std::uint16_t>(f.target + ev::Duration)), static_cast<long long>(at),
                                 static_cast<long long>(now - at));
                    } else {
                        jvm::log("player: keys: lane %d key %d down at %lld ms, no note near", l, k, static_cast<long long>(now));
                    }
                }
                // This play is a keyboard play's from now on: its save says so.
                g_keyed.store(true, std::memory_order_release);
            } else if (!down) {
                // Up: no press, so the game sees this finger lifted.
                if (f.pressing && trace_keys()) jvm::log("player: keys: lane %d key %d up at %lld ms", l, k, static_cast<long long>(now));
                f.pressing = false;
                f.target = 0;
                continue;
            }
            // A drag on its way: the press goes along its curve, as the game draws and judges it.
            if (f.drag && f.target && tick >= f.drag_tick) drag_pos(t, player, f.target, f.x, f.y);
            // The press, as DMQInput.OnUpdate makes one for a finger: touch type 0, the key's number, the place.
            const std::uint32_t key = static_cast<std::uint32_t>(kKeyBase + (l * 2 + k) * 2 + f.which);
            t.call(g_set_press, {g_scratch + 16, self, player, 0, key, bits(f.x), bits(f.y), 0});
            f.pressing = true;
        }
    }
}

// With stats on: one frame's costs, and every five seconds their mean, 99th percentile and most, over a song's frames.
void note_cost(float game_us, float ours_us) {
    const long long now = steady_ms();
    // After a gap of a second or more the frames before it are left out, so that a line covers frames played together.
    if (g_cost.last && now - g_cost.last > 1000) {
        g_cost.game.clear();
        g_cost.ours.clear();
        g_cost.since = 0;
    }
    g_cost.last = now;
    g_cost.game.push_back(game_us);
    g_cost.ours.push_back(ours_us);
    if (!g_cost.since) g_cost.since = now;
    if (now - g_cost.since < 5000) return;
    auto line = [](std::vector<float>& v, float& mean, float& p99, float& most) {
        std::sort(v.begin(), v.end());
        double sum = 0;
        for (float x : v) sum += x;
        mean = static_cast<float>(sum / static_cast<double>(v.size()));
        p99 = v[static_cast<std::size_t>(0.99 * static_cast<double>(v.size() - 1))];
        most = v.back();
    };
    float gm = 0, gp = 0, gx = 0, om = 0, op = 0, ox = 0;
    line(g_cost.game, gm, gp, gx);
    line(g_cost.ours, om, op, ox);
    jvm::log("stats: keyboard play: %zu frames of a song: its presses took mean %.1f us p99 %.1f max %.1f a frame, the game's own input update "
             "mean %.1f us p99 %.1f max %.1f",
             g_cost.ours.size(), static_cast<double>(om), static_cast<double>(op), static_cast<double>(ox), static_cast<double>(gm),
             static_cast<double>(gp), static_cast<double>(gx));
    g_cost.game.clear();
    g_cost.ours.clear();
    g_cost.since = now;
}

// The stubs' host functions, one a slot (kSlots' order), each with the game's own override first. Their arguments are the
// override's: the input, the score player, the method's information.
std::uint64_t on_reset(Thread& t) {
    t.call(g_original[0], {t.arg(0), t.arg(1), t.arg(2)});
    // A play starts (a retry too): its notes are read at its first frame, and nothing held from before plays it.
    g_play.fresh = true;
    keyplay_let_go("a play starts");
    return 0;
}
std::uint64_t on_update(Thread& t) {
    const gaddr self = t.arg(0), player = t.arg(1), method = t.arg(2);
    // The times only with stats on: two clock reads a frame are all this costs otherwise. Not with a check's trace, whose
    // lines in the log would be the most of what is measured.
    const bool timed = arm32::g_stats && !trace_keys();
    const auto a = timed ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};
    t.call(g_original[1], {self, player, method});
    const auto b = timed ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};
    // The score player's fields read whole (its notes' list is the last of them).
    if (readable(player, sp::NoteEvents + 4)) frame(t, self, player);
    if (timed && g_playing.load(std::memory_order_relaxed)) {
        // Keyboard play's part: the frame's work after the game's own, less the check's keys sent in it.
        const float ours = std::chrono::duration<float, std::micro>(std::chrono::steady_clock::now() - b).count() - g_cost.posting_us;
        note_cost(std::chrono::duration<float, std::micro>(b - a).count(), std::max(ours, 0.0f));
    }
    g_cost.posting_us = 0;
    return 0;
}
std::uint64_t on_pause(Thread& t) {
    const gaddr player = t.arg(1);
    t.call(g_original[2], {t.arg(0), player, t.arg(2)});
    // Paused: no lane plays until the song goes on, and a key held through the pause is no press after it.
    g_playing.store(false, std::memory_order_release);
    // The gauge ran out: the game over holds the song through this same pause, and the song is over.
    if (readable(player, sp::NoteEvents + 4) && u8(player + sp::Gameover)) finish(g_play, "is over");
    keyplay_let_go("the song paused");
    return 0;
}
std::uint64_t on_stop(Thread& t) {
    t.call(g_original[3], {t.arg(0), t.arg(1), t.arg(2)});
    // Stopped (left, or after its end): no lane plays any more.
    g_playing.store(false, std::memory_order_release);
    finish(g_play, "stopped");
    keyplay_let_go("the song stopped");
    return 0;
}
constexpr arm32::HostFn kHooks[kSlotCount] = {&on_reset, &on_update, &on_pause, &on_stop};

// Out for good, said once: the game plays by touch as before.
void stay_out(const std::string& why) {
    g_hook.store(kOff, std::memory_order_release);
    jvm::log("player: keyboard play is off: %s; the game plays by touch as before", why.c_str());
}

// Finds the game's classes, methods and fields, checks each against what this player expects, and puts the stubs in the
// input class's slots. Returns while IL2CPP or the game's assembly is not up yet (a later render call looks again).
void install(Thread& th) {
    Guest& gg = g();
    auto api = [&](const char* name) { return gg.dlsym(g_il2cpp, name); };
    const gaddr thread_current = api("il2cpp_thread_current"), domain_get = api("il2cpp_domain_get"),
                assembly_open = api("il2cpp_domain_assembly_open"), assembly_image = api("il2cpp_assembly_get_image"),
                class_from_name = api("il2cpp_class_from_name"), method_from_name = api("il2cpp_class_get_method_from_name"),
                class_init = api("il2cpp_runtime_class_init"), field_from_name = api("il2cpp_class_get_field_from_name"),
                field_offset = api("il2cpp_field_get_offset");
    if (!thread_current || !domain_get || !assembly_open || !assembly_image || !class_from_name || !method_from_name || !class_init ||
        !field_from_name || !field_offset) {
        stay_out("libil2cpp lacks the calls it needs");
        return;
    }
    // Before IL2CPP is up, or on a thread it does not know, its API must not be used (tweaks.cpp does the same).
    if (!th.call(thread_current, {})) return;
    auto call = [&](gaddr fn, std::initializer_list<std::uint32_t> args) { return static_cast<gaddr>(th.call(fn, args)); };
    const gaddr domain = call(domain_get, {});
    const gaddr assembly = domain ? call(assembly_open, {domain, guest_string("Assembly-CSharp")}) : 0;
    const gaddr image = assembly ? call(assembly_image, {assembly}) : 0;
    // The game's assembly not loaded yet: a later look.
    if (!image) return;
    auto klass = [&](const char* ns, const char* name) { return call(class_from_name, {image, guest_string(ns), guest_string(name)}); };
    const gaddr input = klass("", "DMQInput"), base = klass("DJMAXTECHNIKA", "DMTInputBase"), player = klass("DJMAXTECHNIKA", "DMTScorePlayer"),
                note = klass("DJMAXTECHNIKA", "DMTScoreEvent"), section = klass("ScorePlayer.Base.Timer", "ScoreTimeSection");
    if (!input || !base || !player || !note || !section) {
        stay_out("the game has not the classes it plays through (DMQInput, DMTInputBase, DMTScorePlayer, DMTScoreEvent, ScoreTimeSection)");
        return;
    }
    // The input class set up (its virtual table filled in) before its slots are read.
    call(class_init, {input});
    // A method's information by class, name and count of arguments, and its code (the first word of the information).
    auto method = [&](gaddr cls, const char* name, int args) { return call(method_from_name, {cls, guest_string(name), static_cast<std::uint32_t>(args)}); };
    auto code = [&](gaddr info) -> gaddr { return info ? u32(info) : 0; };
    // Where libil2cpp.so starts, from OnUpdate's place: every other method is checked against its RVA from there.
    const gaddr update_info = method(input, "OnUpdate", 1);
    if (!code(update_info)) {
        stay_out("the game's input has no OnUpdate");
        return;
    }
    const gaddr lib = code(update_info) - kSlots[1].rva;
    gaddr infos[kSlotCount] = {};
    for (int i = 0; i < kSlotCount; ++i) {
        const Slot& s = kSlots[i];
        infos[i] = method(input, s.name, 1);
        const gaddr at = input + kVtable + s.slot * 8;
        // The override at its RVA, and in its slot as the class's virtual table holds it (its code and its information).
        if (!code(infos[i]) || code(infos[i]) - lib != s.rva || u32(at) != code(infos[i]) || u32(at + 4) != infos[i]) {
            stay_out(std::string("DMQInput.") + s.name + " is not where this player expects it (libil2cpp+" + hex(code(infos[i]) - lib) + ", expected " +
                     hex(s.rva) + " in slot " + std::to_string(s.slot) + ")");
            return;
        }
    }
    // The calls keyboard play makes, each at its RVA.
    struct Call {
        const char* name;
        gaddr code;
        std::uint32_t rva;
        gaddr* into;
    } calls[] = {
        {"DMTInputBase.SetPress", code(method(base, "SetPress", 4)), kRvaSetPress, &g_set_press},
        {"DMTScorePlayer.TickToRealPosition", code(method(player, "TickToRealPosition", 2)), kRvaTickToReal, &g_tick_to_real},
        {"DMTScorePlayer.GetDragNoteCurvePos", code(method(player, "GetDragNoteCurvePos", 1)), kRvaDragPos, &g_drag_pos},
        {"ScoreTimeSection.CalcTickToTime", code(method(section, "CalcTickToTime", 1)), kRvaTickToTime, &g_tick_to_time},
    };
    for (const Call& c : calls) {
        if (!c.code || c.code - lib != c.rva) {
            stay_out(std::string(c.name) + " is not where this player expects it (libil2cpp+" + hex(c.code - lib) + ", expected " + hex(c.rva) + ")");
            return;
        }
    }
    // The fields read, each at its offset.
    for (const Field& f : kFields) {
        const gaddr info = call(field_from_name, {f.cls == 0 ? player : note, guest_string(f.name)});
        const std::uint32_t offset = info ? static_cast<std::uint32_t>(th.call(field_offset, {info})) : 0;
        if (!info || offset != f.offset) {
            stay_out(std::string("the field ") + f.name + " is not where this player expects it (" + (info ? hex(offset) : std::string("none")) +
                     ", expected " + hex(f.offset) + ")");
            return;
        }
    }
    for (const Call& c : calls) *c.into = c.code;
    // The guest memory the calls hand their points back in, and SetPress its result (16 bytes each).
    g_scratch = gg.malloc(64);
    // The stubs, in a page of their own: push {r7, lr}; movw r7, #number; movt r7, #number >> 16; svc 0; pop {r7, pc}.
    // The svc reaches the runtime, which runs the host function of that number on this thread and returns its result.
    const std::int64_t page = gg.proc.mem.map(0, arm32::kPageSize, arm32::kProtRead | arm32::kProtExec, false, "[keyplay]");
    if (!g_scratch || page < 0) {
        stay_out("no guest memory for its stubs");
        return;
    }
    for (int i = 0; i < kSlotCount; ++i) {
        const std::uint32_t number = kHookNumber + static_cast<std::uint32_t>(i);
        const std::uint32_t lo = number & 0xffff, hi = number >> 16;
        const std::uint32_t stub[5] = {0xe92d4080, 0xe3007000 | ((lo & 0xf000) << 4) | (lo & 0xfff), 0xe3407000 | ((hi & 0xf000) << 4) | (hi & 0xfff),
                                       0xef000000, 0xe8bd8080};
        const gaddr at = static_cast<gaddr>(page) + static_cast<gaddr>(i) * sizeof stub;
        std::memcpy(gg.proc.mem.host(at), stub, sizeof stub);
        arm32::register_host_fn(number, kHooks[i]);
        // The game's own override kept to be called first, and the stub in its slot from now on.
        g_original[i] = code(infos[i]);
        *gg.proc.mem.ptr<std::uint32_t>(input + kVtable + kSlots[i].slot * 8) = at;
    }
    g_hook.store(kIn, std::memory_order_release);
    jvm::log("player: keyboard play: the game's input is hooked (DMQInput's OnReset, OnUpdate, Pause and Stop, every method and field at its "
             "place); the lane keys play while a song is played");
}

}  // namespace

void keyplay_library_loaded(const std::string& name, gaddr handle) {
    if (name == "libil2cpp.so") g_il2cpp = handle;
}

void keyplay_render(Thread& th) {
    if (g_hook.load(std::memory_order_relaxed) != kWaiting || !g_il2cpp) return;
    // Keyboard play off in the settings: no hook at all, every key the game's.
    if (!settings().keyboard) {
        g_hook.store(kOff, std::memory_order_release);
        jvm::log("player: keyboard play is off (keyboard=off): every key is the game's");
        return;
    }
    // Once IL2CPP is up and the game's assembly is loaded: a look every 30th render call until then.
    static unsigned renders = 0;
    if (renders++ % 30) return;
    install(th);
}

bool keyplay_key(unsigned scan, bool extended, bool down, bool repeat) {
    if (g_hook.load(std::memory_order_acquire) != kIn) return false;
    // The key's lane in the song's mode (none before the first song).
    int slot = -1;
    const int lane = keys::lane_of(settings().lanes_of(g_lane_count.load(std::memory_order_acquire)), scan, extended, slot);
    if (lane < 0) return false;
    if (!down) {
        // Coming up: the lane's when it was down, whether or not the song still plays (a let go took the others).
        if (!g_lanes.up(lane, slot)) return false;
        return true;
    }
    // Going down: the lane's only while a song is being played, the game not held and not asking for text.
    keys::When when;
    when.keyboard = settings().keyboard;
    when.hooked = true;
    when.playing = g_playing.load(std::memory_order_acquire);
    when.since_frame_ms = steady_ms() - g_frame_ms.load(std::memory_order_acquire);
    when.held = g_held.load(std::memory_order_acquire);
    when.typing = typing();
    if (!keys::lanes_play(when)) return false;
    // The lane's: a new press, or its repeat (held), or a key held through a let go, none of them the game's key.
    g_lanes.down(lane, slot, repeat);
    return true;
}

void keyplay_let_go(const char* why) {
    const int n = g_lanes.let_go();
    // Said only when a key was down: the window loses the keyboard at every Alt+Tab.
    if (n) jvm::log("player: keyboard play: %d lane key%s let go: %s", n, n == 1 ? "" : "s", why);
    // The window's thread hears it (the overlay's bar waits only while something is down on the game).
    if (n) {
        if (current_looper() == &main_looper()) keyplay_released();
        else main_looper().post([] { keyplay_released(); });
    }
}

void keyplay_hold(bool held) {
    g_held.store(held, std::memory_order_release);
    // Held still: what the lane keys held lets go, as a finger's touch does when a phone's game is left.
    if (held) keyplay_let_go("the game is held still");
}

bool keyplay_any_down() { return g_lanes.any_down(); }

void keyplay_song_keys(std::vector<SongKey> keys) {
    // In time order, a key's going down before its coming up at the same time.
    std::stable_sort(keys.begin(), keys.end(), [](const SongKey& a, const SongKey& b) { return a.ms < b.ms; });
    g_song_keys = std::move(keys);
}

void keyplay_mark_save(const std::string& method, const std::string& body, std::vector<std::pair<std::string, std::string>>& headers) {
    // Only the request that saves a play, and only for a play a lane key pressed.
    if (!keys::saves_play(method, body)) return;
    if (!g_keyed.load(std::memory_order_acquire)) {
        jvm::log("player: keyboard play: the play's save goes as a touch play's (no lane key pressed in it)");
        return;
    }
    headers.emplace_back("X-OpenDMTQ-Keys", "1");
    jvm::log("player: keyboard play: the play's save goes with X-OpenDMTQ-Keys: 1 (lane keys pressed in it)");
}

#ifndef _WIN32
// A desktop Linux host's player (a developer's tool) has no lane keys in its window: a check's keys at song times go
// straight to the lanes, as the window's thread would put them, and nothing over the game waits for them.
void keyplay_post_key(unsigned scan, bool down) { keyplay_key(scan, false, down, false); }
void keyplay_released() {}
#endif

}  // namespace player
