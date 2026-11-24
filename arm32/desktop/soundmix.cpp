// The game's music and its effects apart (soundmix.h): four of OpenAL's calls taken over by name, each a stub of the
// player's that runs a host function, which calls OpenAL's own.
#include "soundmix.h"

#include "client_names.h"

#include "guest.h"
#include "host.h"
#include "jvm.h"
#include "mixer.h"
#include "openal_rate.h"

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <map>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace player {

namespace {

using arm32::gaddr;
using arm32::Guest;
using arm32::Thread;

Guest& g() { return Guest::get(); }

// The stubs' numbers, past keyboard play's (keyplay.cpp's kReentrantBase + 0x7000): reentrant, as they call OpenAL.
constexpr std::uint32_t kNumber = arm32::kReentrantBase + 0x7100;

// OpenAL's names for what is asked and said (al.h).
constexpr std::uint32_t kAlGain = 0x100A, kAlSourceType = 0x1027, kAlStreaming = 0x1029;

// The calls taken over, in the stubs' order, and the one only called.
enum Call { kSourcef, kSourcePlay, kSourcePlayv, kDeleteSources, kCallCount };
const char* const kNames[kCallCount] = {"alSourcef", "alSourcePlay", "alSourcePlayv", "alDeleteSources"};
// OpenAL's own code for each, and its alGetSourcei, which says a source's kind.
gaddr g_original[kCallCount] = {};
gaddr g_get_sourcei = 0;
std::atomic<bool> g_in{false};

// The shares now (sound_mix.h percent_gain of the music and effects controls), and whether they changed since the render
// thread last gave them to every source.
std::atomic<float> g_music{1.0f}, g_effects{1.0f};
std::atomic<bool> g_changed{false};

// The gain the game set on each source (1, OpenAL's own, until it sets one), whether OpenAL called it streaming at its
// last play, and whether it is a song's (played by the score's own sounds, their class's Play: its share is its track's,
// given through the score's track volumes, so OpenAL gets the game's gain as it is): the panel's change is given to
// every source with it.
struct Source {
    float gain = 1.0f;
    bool streaming = false;
    bool score = false;
};
// Whether this thread is inside one of the score's sounds' Play (on_sound_play): the OpenAL calls it makes are a song's.
thread_local bool t_in_score_sound = false;
std::mutex g_lock;
std::unordered_map<std::uint32_t, Source> g_sources;
// For the stats: the gains the game set, and the plays of each kind.
std::atomic<std::uint64_t> g_gains{0}, g_music_plays{0}, g_effect_plays{0}, g_score_plays{0};

float from_bits(std::uint32_t v) {
    float f;
    std::memcpy(&f, &v, sizeof f);
    return f;
}
std::uint32_t to_bits(float f) {
    std::uint32_t v;
    std::memcpy(&v, &f, sizeof v);
    return v;
}

// Whether OpenAL says the source streams (queued buffers: music), asked on the calling thread with a guest word of its
// own for the answer (each thread one, made once).
bool streaming(Thread& t, std::uint32_t source) {
    thread_local gaddr answer = 0;
    if (!answer) answer = g().malloc(4);
    if (!answer || !g_get_sourcei) return false;
    *g().proc.mem.ptr<std::uint32_t>(answer) = 0;
    t.call(g_get_sourcei, {source, kAlSourceType, answer});
    return *g().proc.mem.ptr<std::uint32_t>(answer) == kAlStreaming;
}

// The source's gain as OpenAL is given it: the game's times its kind's share; a song's as the game set it (its track's
// share is in the track's volume already).
void give(Thread& t, std::uint32_t source, float gain, bool music, bool score) {
    const float share = score ? 1.0f : music ? g_music.load(std::memory_order_relaxed) : g_effects.load(std::memory_order_relaxed);
    t.call(g_original[kSourcef], {source, kAlGain, to_bits(gain * share)});
}

// alSourcef(source, param, value): the game's gain kept and given with its share; any other value as it is.
std::uint64_t on_sourcef(Thread& t) {
    const std::uint32_t source = t.arg(0), param = t.arg(1), value = t.arg(2);
    if (param != kAlGain) return t.call(g_original[kSourcef], {source, param, value});
    ++g_gains;
    const float gain = from_bits(value);
    const bool music = streaming(t, source);
    bool score = false;
    {
        std::lock_guard<std::mutex> l(g_lock);
        Source& s = g_sources[source];
        s.gain = gain;
        s.streaming = music;
        // A song's sound: so for as long as the source lives.
        if (t_in_score_sound) s.score = true;
        score = s.score;
    }
    give(t, source, gain, music, score);
    return 0;
}

// A source about to play: its kind is sure now (its buffers are on it), and its gain given with that kind's share.
void before_play(Thread& t, std::uint32_t source) {
    const bool music = streaming(t, source);
    float gain = 1.0f;
    bool score = false;
    {
        std::lock_guard<std::mutex> l(g_lock);
        Source& s = g_sources[source];
        s.streaming = music;
        if (t_in_score_sound) s.score = true;
        score = s.score;
        gain = s.gain;
    }
    ++(score ? g_score_plays : music ? g_music_plays : g_effect_plays);
    give(t, source, gain, music, score);
}

// alSourcePlay(source).
std::uint64_t on_play(Thread& t) {
    const std::uint32_t source = t.arg(0);
    before_play(t, source);
    return t.call(g_original[kSourcePlay], {source});
}

// alSourcePlayv(n, sources).
std::uint64_t on_playv(Thread& t) {
    const std::uint32_t n = t.arg(0), list = t.arg(1);
    for (std::uint32_t i = 0; i < n && i < 256; ++i) before_play(t, *g().proc.mem.ptr<std::uint32_t>(list + i * 4));
    return t.call(g_original[kSourcePlayv], {n, list});
}

// alDeleteSources(n, sources): forgotten.
std::uint64_t on_delete(Thread& t) {
    const std::uint32_t n = t.arg(0), list = t.arg(1);
    {
        std::lock_guard<std::mutex> l(g_lock);
        for (std::uint32_t i = 0; i < n && i < 4096; ++i) g_sources.erase(*g().proc.mem.ptr<std::uint32_t>(list + i * 4));
    }
    return t.call(g_original[kDeleteSources], {n, list});
}

constexpr arm32::HostFn kHooks[kCallCount] = {&on_sourcef, &on_play, &on_playv, &on_delete};

// ---- the device the game's OpenAL plays through, and the rate it mixes at
//
// The game's OpenAL (OpenAL Soft 1.13) has two ways out: OpenSL ES first and android.media.AudioTrack ("Android
// Legacy") second. Its OpenSL ES one mixes at 44,100 Hz whatever it is asked (its reset sets that rate), which is what a
// phone plays; its AudioTrack one, which opens here (the player has no OpenSL ES), mixes at the rate the game's context
// asks for, else at the 22,050 Hz its open sets. The game opens its default device and asks for no rate: its context
// on the AudioTrack device is given the phone's (openal_rate.h). Both calls are said in the log, with the rate the
// device mixes at then.

// ALC's name for a device's name (alc.h); its mixing rate's is audio::kAlcFrequency.
constexpr std::uint32_t kAlcDeviceSpecifier = 0x1005;
using audio::kAlcFrequency;
// The two calls taken over, after the four above in the stubs' numbers, and the two only called.
enum DeviceCall { kOpenDevice, kCreateContext, kDeviceCallCount };
const char* const kDeviceNames[kDeviceCallCount] = {"alcOpenDevice", "alcCreateContext"};
gaddr g_device_original[kDeviceCallCount] = {};
gaddr g_get_string = 0, g_get_integerv = 0;

// A string of guest memory, up to its end or `max` bytes; "" where it cannot be read.
std::string guest_text(gaddr at, std::uint32_t max = 256) {
    std::string out;
    for (std::uint32_t i = 0; i < max && at && g().proc.mem.readable(at + i, 1); ++i) {
        const char c = static_cast<char>(*g().proc.mem.ptr<std::uint8_t>(at + i));
        if (!c) break;
        out += c;
    }
    return out;
}

// The name OpenAL gives the device, as alcGetString says it.
std::string device_name(Thread& t, gaddr device) {
    if (!device || !g_get_string) return "";
    return guest_text(static_cast<gaddr>(t.call(g_get_string, {device, kAlcDeviceSpecifier})));
}

// The rate the device mixes at, as alcGetIntegerv says it (a guest word of the calling thread's own for the answer).
int device_rate(Thread& t, gaddr device) {
    thread_local gaddr answer = 0;
    if (!answer) answer = g().malloc(4);
    if (!answer || !device || !g_get_integerv) return 0;
    *g().proc.mem.ptr<std::uint32_t>(answer) = 0;
    t.call(g_get_integerv, {device, kAlcFrequency, 1, answer});
    return static_cast<int>(*g().proc.mem.ptr<std::uint32_t>(answer));
}

// An attribute list (pairs up to a 0) as the log says it: "ALC_FREQUENCY 22050, 0x1010 32", or "none".
std::string attributes_text(gaddr list) {
    std::string out;
    for (std::uint32_t i = 0; list && i < 64 && g().proc.mem.readable(list + i * 8, 8); ++i) {
        const std::uint32_t key = *g().proc.mem.ptr<std::uint32_t>(list + i * 8), value = *g().proc.mem.ptr<std::uint32_t>(list + i * 8 + 4);
        if (!key) break;
        char part[48];
        if (key == kAlcFrequency) std::snprintf(part, sizeof part, "%sALC_FREQUENCY %u", out.empty() ? "" : ", ", value);
        else std::snprintf(part, sizeof part, "%s0x%x %u", out.empty() ? "" : ", ", key, value);
        out += part;
    }
    return out.empty() ? "none" : out;
}

// alcOpenDevice(name): the game's own, said with the name it asked for and the device it got.
std::uint64_t on_open_device(Thread& t) {
    const gaddr asked = t.arg(0);
    const gaddr device = static_cast<gaddr>(t.call(g_device_original[kOpenDevice], {asked}));
    const std::string want = asked ? "\"" + guest_text(asked) + "\"" : "of its own choosing";
    if (device) jvm::log("player: sound: the game's OpenAL asked for the device %s and opened \"%s\"", want.c_str(), device_name(t, device).c_str());
    else jvm::log("player: sound: the game's OpenAL asked for the device %s and opened none", want.c_str());
    return device;
}

// An attribute list of guest memory (pairs up to a 0) as pairs without the 0; none for no list.
std::vector<std::uint32_t> attributes_of(gaddr list) {
    std::vector<std::uint32_t> out;
    for (std::uint32_t i = 0; list && i < 64 && g().proc.mem.readable(list + i * 8, 8); ++i) {
        const std::uint32_t key = *g().proc.mem.ptr<std::uint32_t>(list + i * 8);
        if (!key) break;
        out.push_back(key);
        out.push_back(*g().proc.mem.ptr<std::uint32_t>(list + i * 8 + 4));
    }
    return out;
}

// alcCreateContext(device, attributes): on OpenAL's AudioTrack device with the rate a phone's OpenAL mixes at
// (openal_rate.h), on any other as the game asked; said with what it asked and the rate the device mixes at then.
std::uint64_t on_create_context(Thread& t) {
    const gaddr device = t.arg(0), list = t.arg(1);
    const std::string name = device_name(t, device), asked = attributes_text(list);
    const std::vector<std::uint32_t> game = attributes_of(list), given = audio::context_attributes(name, game);
    gaddr copy = 0;
    if (given != game) {
        // The list OpenAL is given instead: a guest copy with its closing 0, kept until the call is done with it.
        copy = g().malloc(static_cast<std::uint32_t>((given.size() + 1) * 4));
        if (copy) {
            for (std::size_t i = 0; i < given.size(); ++i) *g().proc.mem.ptr<std::uint32_t>(copy + static_cast<gaddr>(i) * 4) = given[i];
            *g().proc.mem.ptr<std::uint32_t>(copy + static_cast<gaddr>(given.size()) * 4) = 0;
        }
    }
    const std::uint64_t context = t.call(g_device_original[kCreateContext], {device, copy ? copy : list});
    if (copy) {
        jvm::log("player: sound: the game's OpenAL made a context on \"%s\" (attributes: %s), asked for %u Hz as on a phone (attributes: %s): "
                 "it mixes at %d Hz",
                 name.c_str(), asked.c_str(), audio::kPhoneOpenAlRate, attributes_text(copy).c_str(), device_rate(t, device));
        g().free(copy);
    } else {
        jvm::log("player: sound: the game's OpenAL made a context on \"%s\" (attributes: %s): it mixes at %d Hz", name.c_str(), asked.c_str(),
                 device_rate(t, device));
    }
    return context;
}

constexpr arm32::HostFn kDeviceHooks[kDeviceCallCount] = {&on_open_device, &on_create_context};

// ---- a song's tracks: the music on its background tracks, the effects on the tracks the player plays
//
// A song's every sound is a sample of one of its tracks, whole buffers all of them: OpenAL cannot tell its music from
// its key sounds. The score player can: each of its tracks says whether the player plays it and holds the volume its
// sounds play at (which the chart's own volume events set too). Each frame, after the score player's own update, each
// track's volume is the game's own times its share: the music's for a background track, the effects' for a played one.
// The sounds the score plays (their class's Play) are marked meanwhile, so that OpenAL's share leaves them as the game
// set them. The game's classes, methods and fields are named by their role (client_names.h).

// libil2cpp.so's handle, and the hooks' state: still to be put in, in, or out for good.
gaddr g_il2cpp = 0;
enum { kScoreWaiting, kScoreIn, kScoreOff };
std::atomic<int> g_score_hook{kScoreWaiting};
// The class's virtual table in the IL2CPP class (as keyplay.cpp has it): each slot a method's code and its information.
constexpr std::uint32_t kVtable = 0xb4;
// The game's own OnUpdate of its score player and Play of its sounds, and the fields read.
gaddr g_update_original = 0, g_play_original = 0;
std::uint32_t g_off_tracks = 0, g_off_is_play = 0, g_off_volume = 0;
// Each track's volume as the game set it last, and as it was written here, by the track's object; the score player
// they belong to (a new one starts them over).
struct TrackVolume {
    float game, written;
};
std::unordered_map<gaddr, TrackVolume> g_tracks;
gaddr g_tracks_of = 0;
// For the stats: the tracks of the song played last, background and played.
std::atomic<std::uint64_t> g_background_tracks{0}, g_played_tracks{0};

float f32(gaddr a) { return *g().proc.mem.ptr<float>(a); }
std::uint8_t u8(gaddr a) { return *g().proc.mem.ptr<std::uint8_t>(a); }
bool readable(gaddr a, std::uint32_t n) { return a && g().proc.mem.readable(a, n); }

// Each track's volume as its share makes it, after the score player's own update.
void apply_tracks(gaddr player) {
    if (!readable(player + g_off_tracks, 4)) return;
    const gaddr list = *g().proc.mem.ptr<std::uint32_t>(player + g_off_tracks);
    if (!readable(list, 16)) return;
    if (player != g_tracks_of || g_tracks.size() > 1024) {
        g_tracks.clear();
        g_tracks_of = player;
    }
    const std::uint32_t n = std::min<std::uint32_t>(*g().proc.mem.ptr<std::uint32_t>(list + 0xc), 256);
    const float music = g_music.load(std::memory_order_relaxed), effects = g_effects.load(std::memory_order_relaxed);
    std::uint64_t background = 0, played = 0;
    const std::uint32_t reach = std::max({g_off_is_play, g_off_volume}) + 4;
    for (std::uint32_t i = 0; i < n; ++i) {
        const gaddr track = *g().proc.mem.ptr<std::uint32_t>(list + 0x10 + i * 4);
        if (!readable(track, reach)) continue;
        const bool play = u8(track + g_off_is_play) != 0;
        ++(play ? played : background);
        const float now = f32(track + g_off_volume);
        auto it = g_tracks.find(track);
        // The game's own: what it holds now, unless that is what was written here (the game set it again meanwhile).
        const float game = it == g_tracks.end() || now != it->second.written ? now : it->second.game;
        const float want = game * (play ? effects : music);
        if (want != now) *g().proc.mem.ptr<float>(track + g_off_volume) = want;
        g_tracks[track] = TrackVolume{game, want};
    }
    g_background_tracks.store(background, std::memory_order_relaxed);
    g_played_tracks.store(played, std::memory_order_relaxed);
}

// The score player's OnUpdate(mainLoop): the game's own, then the tracks' volumes.
std::uint64_t on_score_update(Thread& t) {
    const gaddr player = t.arg(0);
    const std::uint64_t r = t.call(g_update_original, {player, t.arg(1), t.arg(2)});
    apply_tracks(player);
    return r;
}

// A score's sound's Play(vol, pan, seekTimeMs, playStartTimeMs, dummy): the game's own, its OpenAL calls marked as a
// song's.
std::uint64_t on_sound_play(Thread& t) {
    const bool outer = t_in_score_sound;
    t_in_score_sound = true;
    const std::uint64_t r = t.call(g_play_original, {t.arg(0), t.arg(1), t.arg(2), t.arg(3), t.arg(4), t.arg(5), t.arg(6)});
    t_in_score_sound = outer;
    return r;
}

// The score's stubs' numbers, after OpenAL's four.
constexpr std::uint32_t kScoreNumber = kNumber + 0x10;

void score_out(const char* why) {
    g_score_hook.store(kScoreOff, std::memory_order_release);
    jvm::log("player: sound: a song's music and effects share one control (%s)", why);
}

// Finds the score player's and the sounds' classes, their methods in their virtual tables and the tracks' fields, and
// puts the stubs in the two slots. Returns while IL2CPP or the game's assembly is not up yet.
void install_score(Thread& th) {
    auto api = [&](const char* name) { return g().dlsym(g_il2cpp, name); };
    const gaddr thread_current = api("il2cpp_thread_current"), domain_get = api("il2cpp_domain_get"),
                assembly_open = api("il2cpp_domain_assembly_open"), assembly_image = api("il2cpp_assembly_get_image"),
                class_from_name = api("il2cpp_class_from_name"), method_from_name = api("il2cpp_class_get_method_from_name"),
                class_init = api("il2cpp_runtime_class_init"), field_from_name = api("il2cpp_class_get_field_from_name"),
                field_offset = api("il2cpp_field_get_offset"), field_type = api("il2cpp_field_get_type"), type_kind = api("il2cpp_type_get_type"),
                class_from_type = api("il2cpp_class_from_type"), element_class = api("il2cpp_class_get_element_class");
    if (!thread_current || !domain_get || !assembly_open || !assembly_image || !class_from_name || !method_from_name || !class_init ||
        !field_from_name || !field_offset || !field_type || !type_kind || !class_from_type || !element_class) {
        score_out("libil2cpp lacks the calls it needs");
        return;
    }
    // Before IL2CPP is up, or on a thread it does not know, its API must not be used.
    if (!th.call(thread_current, {})) return;
    auto call = [&](gaddr fn, std::initializer_list<std::uint32_t> args) { return static_cast<gaddr>(th.call(fn, args)); };
    // A guest copy of each name for the calls, which only read them: made once, kept (the looks repeat until IL2CPP is up).
    auto guest_copy = [&](const std::string& s) {
        static std::map<std::string, gaddr> kept;
        auto it = kept.find(s);
        if (it != kept.end()) return it->second;
        return kept[s] = g().strdup(s);
    };
    // A name of the game's code by its role, as a guest copy.
    auto name = [&](const char* role) { return guest_copy(client_names::text(role)); };
    const gaddr domain = call(domain_get, {});
    const gaddr assembly = domain ? call(assembly_open, {domain, guest_copy("Assembly-CSharp")}) : 0;
    const gaddr image = assembly ? call(assembly_image, {assembly}) : 0;
    if (!image) return;
    // The score player, and the class of the sounds the score plays (in no namespace).
    const gaddr player = call(class_from_name, {image, name(client_names::kScoreNamespace), name(client_names::kScorePlayerClass)});
    const gaddr sound = call(class_from_name, {image, guest_copy(""), name(client_names::kSoundClass)});
    if (!player || !sound) {
        score_out(!player ? "the game has not its score player" : "the game has not its score's sounds");
        return;
    }
    // The tracks' class, nested in the score player's base: the element of its array of tracks.
    const gaddr tracks_info = call(field_from_name, {player, name(client_names::kFieldTracks)});
    const gaddr tracks_type = tracks_info ? call(field_type, {tracks_info}) : 0;
    const gaddr tracks_class = tracks_type ? call(class_from_type, {tracks_type}) : 0;
    const gaddr track = tracks_class ? call(element_class, {tracks_class}) : 0;
    if (!track) {
        score_out("the score player has not its tracks");
        return;
    }
    call(class_init, {player});
    call(class_init, {sound});
    // A method's slot in its class's virtual table: the slot holding its code and its information.
    auto slot_of = [&](gaddr cls, const char* role, int args, gaddr& code) -> int {
        const gaddr info = call(method_from_name, {cls, name(role), static_cast<std::uint32_t>(args)});
        code = info && readable(info, 4) ? *g().proc.mem.ptr<std::uint32_t>(info) : 0;
        if (!code) return -1;
        for (int k = 0; k < 96; ++k) {
            const gaddr at = cls + kVtable + static_cast<gaddr>(k) * 8;
            if (!readable(at, 8)) return -1;
            if (*g().proc.mem.ptr<std::uint32_t>(at) == code && *g().proc.mem.ptr<std::uint32_t>(at + 4) == info) return k;
        }
        return -1;
    };
    gaddr update_code = 0, play_code = 0;
    // The score player's update once a frame, and the sound class's method that plays a sound of the score.
    const int update_slot = slot_of(player, client_names::kUpdate, 1, update_code), play_slot = slot_of(sound, client_names::kPlay, 5, play_code);
    if (update_slot < 0 || play_slot < 0) {
        score_out("the score player's update or the score's sounds' play is not in its class's virtual table");
        return;
    }
    // The fields, by name, their offsets; the volume a float (IL2CPP_TYPE_R4) and the flag a bool (BOOLEAN).
    auto field = [&](gaddr cls, const char* role, std::uint32_t kind, std::uint32_t& offset) {
        const gaddr info = call(field_from_name, {cls, name(role)});
        if (!info) return false;
        const gaddr type = call(field_type, {info});
        if (!type || static_cast<std::uint32_t>(th.call(type_kind, {type})) != kind) return false;
        offset = static_cast<std::uint32_t>(th.call(field_offset, {info}));
        return offset > 0;
    };
    constexpr std::uint32_t kBool = 0x02, kFloat = 0x0c, kArray = 0x1d;
    // The score player's tracks, and each track's flag (whether the player plays it) and volume.
    if (!field(player, client_names::kFieldTracks, kArray, g_off_tracks) || !field(track, client_names::kTrackPlayed, kBool, g_off_is_play) ||
        !field(track, client_names::kTrackVolume, kFloat, g_off_volume)) {
        score_out("the score's tracks are not as the player expects them (the tracks, each one's flag and volume)");
        return;
    }
    // The stubs, as OpenAL's: push {r7, lr}; movw r7, #number; movt r7, #number >> 16; svc 0; pop {r7, pc}.
    const std::int64_t page = g().proc.mem.map(0, arm32::kPageSize, arm32::kProtRead | arm32::kProtExec, false, "[soundmix score]");
    if (page < 0) {
        score_out("no guest memory for its stubs");
        return;
    }
    const arm32::HostFn fns[2] = {&on_score_update, &on_sound_play};
    const gaddr classes[2] = {player, sound};
    const int slots[2] = {update_slot, play_slot};
    g_update_original = update_code;
    g_play_original = play_code;
    for (int i = 0; i < 2; ++i) {
        const std::uint32_t number = kScoreNumber + static_cast<std::uint32_t>(i);
        const std::uint32_t lo = number & 0xffff, hi = number >> 16;
        const std::uint32_t stub[5] = {0xe92d4080, 0xe3007000 | ((lo & 0xf000) << 4) | (lo & 0xfff), 0xe3407000 | ((hi & 0xf000) << 4) | (hi & 0xfff),
                                       0xef000000, 0xe8bd8080};
        const gaddr at = static_cast<gaddr>(page) + static_cast<gaddr>(i) * sizeof stub;
        std::memcpy(g().proc.mem.host(at), stub, sizeof stub);
        arm32::register_host_fn(number, fns[i]);
        *g().proc.mem.ptr<std::uint32_t>(classes[i] + kVtable + static_cast<gaddr>(slots[i]) * 8) = at;
    }
    g_score_hook.store(kScoreIn, std::memory_order_release);
    jvm::log("player: sound: a song's background tracks are the music, its played tracks the effects (the score player's update in slot %d, "
             "the score's sounds' play in slot %d, a track's flag and volume at 0x%x and 0x%x)",
             update_slot, play_slot, g_off_is_play, g_off_volume);
}

// A 32-bit word and a 16-bit one of guest memory.
std::uint32_t u32(gaddr a) { return *g().proc.mem.ptr<std::uint32_t>(a); }
std::uint16_t u16(gaddr a) { return *g().proc.mem.ptr<std::uint16_t>(a); }

// The library's symbol table, from its ELF header in memory: where its file starts, its load bias, the symbols and their
// names, and how many there are (DT_HASH's chain count). False when any of it is not there.
struct Symbols {
    gaddr bias = 0, symtab = 0, strtab = 0;
    std::uint32_t count = 0;
};
bool symbols_of(gaddr inside, Symbols& out) {
    // Its first page, where the ELF header is: back from a symbol's code a page at a time (16 MB at most).
    gaddr base = inside & ~0xfffu;
    for (int pages = 0;; ++pages, base -= 0x1000) {
        if (pages > 4096 || !g().proc.mem.readable(base, 4)) return false;
        if (u32(base) == 0x464c457f) break;
    }
    const gaddr ph = base + u32(base + 0x1c);
    const unsigned phnum = u16(base + 0x2c), phsize = u16(base + 0x2a);
    // The lowest loaded address is where the file's start was put.
    gaddr lowest = ~0u, dynamic = 0;
    for (unsigned i = 0; i < phnum; ++i) {
        const gaddr p = ph + i * phsize;
        if (!g().proc.mem.readable(p, 32)) return false;
        if (u32(p) == 1) lowest = std::min<gaddr>(lowest, u32(p + 8) & ~0xfffu);
        if (u32(p) == 2) dynamic = u32(p + 8);
    }
    if (lowest == ~0u || !dynamic) return false;
    out.bias = base - lowest;
    gaddr hash = 0;
    for (gaddr d = out.bias + dynamic; g().proc.mem.readable(d, 8) && u32(d) != 0; d += 8) {
        if (u32(d) == 4) hash = out.bias + u32(d + 4);
        if (u32(d) == 5) out.strtab = out.bias + u32(d + 4);
        if (u32(d) == 6) out.symtab = out.bias + u32(d + 4);
    }
    if (!hash || !out.strtab || !out.symtab || !g().proc.mem.readable(hash, 8)) return false;
    out.count = u32(hash + 4);
    return out.count > 0;
}

// The symbol named `name` whose address is `at`: its entry, or 0.
gaddr symbol_entry(const Symbols& s, const char* name, gaddr at) {
    const std::size_t length = std::strlen(name);
    for (std::uint32_t i = 1; i < s.count; ++i) {
        const gaddr e = s.symtab + i * 16;
        if (!g().proc.mem.readable(e, 16)) return 0;
        const gaddr n = s.strtab + u32(e);
        if (!g().proc.mem.readable(n, static_cast<std::uint32_t>(length + 1))) continue;
        if (std::memcmp(g().proc.mem.host(n), name, length + 1) != 0) continue;
        return u32(e + 4) + s.bias == at ? e : 0;
    }
    return 0;
}

// What is said once.
void say(const char* line) { jvm::log("%s", line); }

// Puts the stub for host function `number` at `at` and points the symbol `entry` of the library (load bias `bias`) at it:
// push {r7, lr}; movw r7, #number; movt r7, #number >> 16; svc 0; pop {r7, pc}.
void take_over(gaddr at, std::uint32_t number, arm32::HostFn fn, gaddr entry, gaddr bias) {
    const std::uint32_t lo = number & 0xffff, hi = number >> 16;
    const std::uint32_t stub[5] = {0xe92d4080, 0xe3007000 | ((lo & 0xf000) << 4) | (lo & 0xfff), 0xe3407000 | ((hi & 0xf000) << 4) | (hi & 0xfff),
                                   0xef000000, 0xe8bd8080};
    std::memcpy(g().proc.mem.host(at), stub, sizeof stub);
    arm32::register_host_fn(number, fn);
    // The symbol's value from now on: the stub, as the library's own bias makes it an address.
    *g().proc.mem.ptr<std::uint32_t>(entry + 4) = at - bias;
}

// A stub's size, and where the device's two go in the page: after the four sharing ones.
constexpr gaddr kStubBytes = 20;
constexpr std::uint32_t kDeviceNumber = kNumber + kCallCount;

}  // namespace

void soundmix_library_loaded(const std::string& name, gaddr handle) {
    // The game's IL2CPP: the song's tracks are reached through it later (install_score).
    if (name == "libil2cpp.so") g_il2cpp = handle;
    if (name != "libopenal.so" || g_in.load()) return;
    gaddr at[kCallCount] = {};
    for (int i = 0; i < kCallCount; ++i) at[i] = g().dlsym(handle, kNames[i]);
    g_get_sourcei = g().dlsym(handle, "alGetSourcei");
    Symbols s;
    if (!at[0] || !g_get_sourcei || !symbols_of(at[0], s)) {
        say("player: sound: the game's OpenAL has not the calls or the symbol table the player expects: music and effects share one control");
        return;
    }
    // The stubs, in a page of their own.
    const std::int64_t page = g().proc.mem.map(0, arm32::kPageSize, arm32::kProtRead | arm32::kProtExec, false, "[soundmix]");
    if (page < 0) {
        say("player: sound: no guest memory for its stubs: music and effects share one control");
        return;
    }
    // The device and its context first, apart from the sharing: either works without the other.
    gaddr device_at[kDeviceCallCount] = {}, device_entries[kDeviceCallCount] = {};
    bool devices = true;
    for (int i = 0; i < kDeviceCallCount; ++i) {
        device_at[i] = g().dlsym(handle, kDeviceNames[i]);
        device_entries[i] = device_at[i] ? symbol_entry(s, kDeviceNames[i], device_at[i]) : 0;
        devices = devices && device_entries[i];
    }
    g_get_string = g().dlsym(handle, "alcGetString");
    g_get_integerv = g().dlsym(handle, "alcGetIntegerv");
    if (devices && g_get_string && g_get_integerv) {
        for (int i = 0; i < kDeviceCallCount; ++i) {
            g_device_original[i] = device_at[i];
            take_over(static_cast<gaddr>(page) + static_cast<gaddr>(kCallCount + i) * kStubBytes, kDeviceNumber + static_cast<std::uint32_t>(i),
                      kDeviceHooks[i], device_entries[i], s.bias);
        }
    } else {
        say("player: sound: the game's OpenAL has not alcOpenDevice, alcCreateContext, alcGetString and alcGetIntegerv as the player expects: "
            "its device is not said");
    }
    gaddr entries[kCallCount] = {};
    for (int i = 0; i < kCallCount; ++i) {
        entries[i] = at[i] ? symbol_entry(s, kNames[i], at[i]) : 0;
        if (!entries[i]) {
            jvm::log("player: sound: no %s in the game's OpenAL's symbol table: music and effects share one control", kNames[i]);
            return;
        }
    }
    for (int i = 0; i < kCallCount; ++i) {
        g_original[i] = at[i];
        take_over(static_cast<gaddr>(page) + static_cast<gaddr>(i) * kStubBytes, kNumber + static_cast<std::uint32_t>(i), kHooks[i], entries[i], s.bias);
    }
    // The shares the settings start with (the panel changes them later: soundmix_shares).
    const audio::Levels levels = audio::levels();
    g_music.store(audio::percent_gain(levels.music));
    g_effects.store(audio::percent_gain(levels.effects));
    g_in.store(true);
    say("player: sound: the game's OpenAL is the player's to share out (alSourcef, alSourcePlay, alSourcePlayv and alDeleteSources by name): "
        "streaming sources are the music, the rest the effects");
}

void soundmix_shares(float music, float effects) {
    g_music.store(music, std::memory_order_relaxed);
    g_effects.store(effects, std::memory_order_relaxed);
    g_changed.store(true, std::memory_order_release);
}

void soundmix_render(Thread& th) {
    // The song's tracks' hook, once IL2CPP and the game's assembly are up: a look every 30th render call until then.
    if (g_score_hook.load(std::memory_order_relaxed) == kScoreWaiting && g_il2cpp) {
        static unsigned renders = 0;
        if (renders++ % 30 == 0) install_score(th);
    }
    if (!g_in.load(std::memory_order_relaxed)) return;
    // The shares changed: each source the game has gets its gain again with its kind's share.
    if (g_changed.exchange(false, std::memory_order_acquire)) {
        std::vector<std::pair<std::uint32_t, Source>> all;
        {
            std::lock_guard<std::mutex> l(g_lock);
            all.assign(g_sources.begin(), g_sources.end());
        }
        for (const auto& [source, s] : all) give(th, source, s.gain, s.streaming, s.score);
    }
    // The stats every five seconds.
    if (!arm32::g_stats) return;
    static auto next = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    const auto now = std::chrono::steady_clock::now();
    if (now < next) return;
    next = now + std::chrono::seconds(5);
    std::size_t known = 0;
    {
        std::lock_guard<std::mutex> l(g_lock);
        known = g_sources.size();
    }
    jvm::log("stats: sound: %llu gains set, %llu plays of music (streaming), %llu of effects, %llu of a song's tracks (%llu background, %llu "
             "played); %zu sources; music %.0f %%, effects %.0f %% in gain",
             static_cast<unsigned long long>(g_gains.exchange(0)), static_cast<unsigned long long>(g_music_plays.exchange(0)),
             static_cast<unsigned long long>(g_effect_plays.exchange(0)), static_cast<unsigned long long>(g_score_plays.exchange(0)),
             static_cast<unsigned long long>(g_background_tracks.load()), static_cast<unsigned long long>(g_played_tracks.load()), known,
             static_cast<double>(g_music.load()) * 100.0, static_cast<double>(g_effects.load()) * 100.0);
}

}  // namespace player
