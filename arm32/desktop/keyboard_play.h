// Keyboard play's rules, apart from the game (keyplay.cpp is the game's side; settingstest.cpp checks these): the names
// of the keys a lane can have and the place of each on the keyboard, a mode's lanes as the settings file names them, the
// lane a key plays, the lane keys' state as the window's thread keeps it, when the lane keys play at all, and which
// request of the game's saves a play.
#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <string>

namespace player::keys {

// A key by its place on the keyboard: the scan code Windows gives with it (set 1, a WM_KEYDOWN's bits 16 to 23), named
// after the key a US layout has at that place, so that a lane is the same place on every layout (AZERTY's A is where the
// US Q is). None of them has the extended flag: the number pad's / (extended 0x35) is not the Slash key.
struct Name {
    // The name the settings file uses, in its own capitals (read in any case).
    const char* name;
    // The scan code of that place.
    std::uint8_t scan;
};
inline constexpr Name kNames[] = {
    // The letters, row by row as the scan codes run: QWERTYUIOP, ASDFGHJKL, ZXCVBNM.
    {"Q", 0x10}, {"W", 0x11}, {"E", 0x12}, {"R", 0x13}, {"T", 0x14}, {"Y", 0x15}, {"U", 0x16}, {"I", 0x17}, {"O", 0x18},
    {"P", 0x19}, {"A", 0x1e}, {"S", 0x1f}, {"D", 0x20}, {"F", 0x21}, {"G", 0x22}, {"H", 0x23}, {"J", 0x24}, {"K", 0x25},
    {"L", 0x26}, {"Z", 0x2c}, {"X", 0x2d}, {"C", 0x2e}, {"V", 0x2f}, {"B", 0x30}, {"N", 0x31}, {"M", 0x32},
    // The digits of the top row (not the number pad's), 1 to 9 then 0, as the keyboard has them.
    {"1", 0x02}, {"2", 0x03}, {"3", 0x04}, {"4", 0x05}, {"5", 0x06}, {"6", 0x07}, {"7", 0x08}, {"8", 0x09}, {"9", 0x0a},
    {"0", 0x0b},
    // The rest a lane may have: the space bar and the punctuation keys around the letters.
    {"Space", 0x39}, {"Semicolon", 0x27}, {"Quote", 0x28}, {"Comma", 0x33}, {"Period", 0x34}, {"Slash", 0x35},
    {"LeftBracket", 0x1a}, {"RightBracket", 0x1b}, {"Backslash", 0x2b}, {"Minus", 0x0c}, {"Equals", 0x0d}, {"Grave", 0x29},
};

// Two names the same when they differ only in capitals (ASCII: the names are).
inline bool same_name(const std::string& a, const char* b) {
    std::size_t i = 0;
    for (; i < a.size() && b[i]; ++i) {
        // Each letter in lower case on both sides.
        const char x = a[i] >= 'A' && a[i] <= 'Z' ? static_cast<char>(a[i] - 'A' + 'a') : a[i];
        const char y = b[i] >= 'A' && b[i] <= 'Z' ? static_cast<char>(b[i] - 'A' + 'a') : b[i];
        if (x != y) return false;
    }
    // Both at their end: neither is the other's beginning only.
    return i == a.size() && !b[i];
}

// The scan code of a key's name, in any case; 0 for a name that is none of them.
inline std::uint8_t scan_of(const std::string& name) {
    for (const Name& n : kNames) {
        if (same_name(name, n.name)) return n.scan;
    }
    return 0;
}

// The name of a scan code, for the log and for the settings the launcher writes back; "" for one that has none.
inline const char* name_of(unsigned scan) {
    for (const Name& n : kNames) {
        if (n.scan == scan) return n.name;
    }
    return "";
}

// A mode's lanes from the top (the first is the game's top track): each lane's keys by scan code, one or two (0: none).
struct Lanes {
    // How many lanes the mode has: 2, 3 or 4 (2 LINE to 4 LINE).
    int count = 0;
    // Each lane's first key and its second, which plays the same lane (two keys to alternate on quick notes).
    std::uint8_t scan[4][2] = {};
};

// A mode's lanes from a value of the settings file: `count` lanes from the top, separated by spaces, a lane's keys joined
// by '/' (one or two), each key by its name. False, with why for the log, for anything else: another number of lanes, a
// lane of no key or of three, a name of no key, or a key twice in the mode (it would play two lanes, or one twice).
inline bool parse(const std::string& value, int count, Lanes& out, std::string& why) {
    Lanes got;
    got.count = count;
    // The modes the game has: 2 to 4 lanes.
    if (count < 2 || count > 4) {
        why = "no mode of " + std::to_string(count) + " lanes";
        return false;
    }
    int lanes = 0;
    std::size_t i = 0;
    for (;;) {
        // Past the spaces (and tabs) between lanes.
        while (i < value.size() && (value[i] == ' ' || value[i] == '\t')) ++i;
        if (i >= value.size()) break;
        // One lane: up to the next space.
        std::size_t end = i;
        while (end < value.size() && value[end] != ' ' && value[end] != '\t') ++end;
        const std::string lane = value.substr(i, end - i);
        i = end;
        // More lanes than the mode has: said with how many were given, once all are counted.
        if (lanes >= count) {
            ++lanes;
            continue;
        }
        // Its keys, joined by '/': one or two, each a name.
        int keys = 0;
        std::size_t from = 0;
        for (;;) {
            const std::size_t slash = lane.find('/', from);
            const std::string name = lane.substr(from, slash == std::string::npos ? std::string::npos : slash - from);
            // A third key, or a '/' with no name beside it, is no lane.
            if (keys >= 2) {
                why = "a lane has more than two keys (" + lane + ")";
                return false;
            }
            const std::uint8_t scan = scan_of(name);
            if (!scan) {
                why = name.empty() ? "a lane has a '/' with no key beside it (" + lane + ")" : "no key is named " + name;
                return false;
            }
            // A key that plays a lane already, this one or another: refused, not guessed.
            for (int l = 0; l <= lanes; ++l) {
                for (int k = 0; k < 2; ++k) {
                    if (got.scan[l][k] == scan) {
                        why = std::string(name_of(scan)) + " is in two places";
                        return false;
                    }
                }
            }
            got.scan[lanes][keys++] = scan;
            if (slash == std::string::npos) break;
            from = slash + 1;
        }
        ++lanes;
    }
    // Every lane of the mode, no more and no fewer.
    if (lanes != count) {
        why = std::to_string(count) + " lanes need " + std::to_string(count) + " keys or pairs, not " + std::to_string(lanes);
        return false;
    }
    out = got;
    return true;
}

// The lanes as the settings file names them ("D F J", "D/S F J/K"), each key's name in its own capitals.
inline std::string text(const Lanes& lanes) {
    std::string out;
    for (int l = 0; l < lanes.count; ++l) {
        // A space between lanes, a '/' between a lane's two keys.
        if (l) out += ' ';
        out += name_of(lanes.scan[l][0]);
        if (lanes.scan[l][1]) out += std::string("/") + name_of(lanes.scan[l][1]);
    }
    return out;
}

// The default keys of a mode: F J; D F J; D F J K. The home row's fingers on a US layout, the index fingers on the keys
// with the bumps, and the 4 LINE lanes split two and two between the hands.
inline const char* default_text(int count) { return count == 2 ? "F J" : count == 3 ? "D F J" : "D F J K"; }
inline Lanes default_lanes(int count) {
    Lanes lanes;
    std::string why;
    // The defaults always read: their names are in the table above.
    parse(default_text(count), count, lanes, why);
    return lanes;
}

// The lane a key plays in a mode, and which of the lane's keys it is (`slot`, 0 or 1); -1 for none. A key with the
// extended flag is never a lane's: its scan code names another key (the number pad's / beside Slash's 0x35).
inline int lane_of(const Lanes& lanes, unsigned scan, bool extended, int& slot) {
    slot = -1;
    if (extended || !scan) return -1;
    for (int l = 0; l < lanes.count && l < 4; ++l) {
        for (int k = 0; k < 2; ++k) {
            if (lanes.scan[l][k] && lanes.scan[l][k] == scan) {
                slot = k;
                return l;
            }
        }
    }
    return -1;
}

// The lane keys' state, as the window's thread writes it and the game's thread reads it once a frame (keyplay.cpp): each
// lane's two keys, down or not, how many times each came down (a tap shorter than a frame is still one press), and how
// many times every key was let go at once (the game's thread then forgets the presses made before it).
class LaneState {
public:
    // Lane `lane`'s key `slot` came down. `repeat` when Windows says it was down already (bit 30 of a WM_KEYDOWN): a key
    // held down repeats, and is one press. A key held through a let go repeats too and stays no press until it comes up
    // and down again. True when it is a new press.
    bool down(int lane, int slot, bool repeat) {
        if (!valid(lane, slot) || repeat) return false;
        down_[lane][slot].store(true, std::memory_order_release);
        // Counted after it is down: the game's thread that sees the count sees the key down too.
        presses_[lane][slot].fetch_add(1, std::memory_order_acq_rel);
        return true;
    }
    // The key came up: true when it was down (a key let go already comes up as no lane's).
    bool up(int lane, int slot) { return valid(lane, slot) && down_[lane][slot].exchange(false, std::memory_order_acq_rel); }
    // Every key let go at once: the window lost the keyboard, the song paused, stopped or ended, the game was held still
    // or asked for text. How many were down.
    int let_go() {
        int n = 0;
        for (auto& lane : down_) {
            for (auto& key : lane) n += key.exchange(false, std::memory_order_acq_rel) ? 1 : 0;
        }
        // After the keys: a frame that sees the new count sees them up.
        epoch_.fetch_add(1, std::memory_order_acq_rel);
        return n;
    }
    // What the game's thread reads.
    bool is_down(int lane, int slot) const { return valid(lane, slot) && down_[lane][slot].load(std::memory_order_acquire); }
    unsigned presses(int lane, int slot) const { return valid(lane, slot) ? presses_[lane][slot].load(std::memory_order_acquire) : 0; }
    unsigned epoch() const { return epoch_.load(std::memory_order_acquire); }
    // Whether any lane's key is down: the game is being played, as with a finger on it (the overlay's bar waits).
    bool any_down() const {
        for (const auto& lane : down_) {
            for (const auto& key : lane) {
                if (key.load(std::memory_order_acquire)) return true;
            }
        }
        return false;
    }

private:
    // A lane of the four and a key of its two.
    static bool valid(int lane, int slot) { return lane >= 0 && lane < 4 && slot >= 0 && slot < 2; }
    std::atomic<bool> down_[4][2]{};
    std::atomic<unsigned> presses_[4][2]{};
    std::atomic<unsigned> epoch_{0};
};

// When the lane keys play a song's lanes. Otherwise every key is the game's as it was, a phone's key.
struct When {
    // Keyboard play on in the settings (keyboard=on).
    bool keyboard = false;
    // The game's input in reach: its code where this player expects it, the hook in its place (keyplay.cpp).
    bool hooked = false;
    // A song being played, as its last frame said: not paused, stopped, ended or over.
    bool playing = false;
    // Milliseconds since that frame: the song's frames still coming.
    long long since_frame_ms = 0;
    // The game held still (the question before quitting is up, or the window is minimised).
    bool held = false;
    // The game asking for text (its text field is open: the keys type into it).
    bool typing = false;
};
// A song whose last frame is older than this is no longer being played (left in a way the game did not say).
constexpr long long kSongFrameMs = 1000;
inline bool lanes_play(const When& w) {
    return w.keyboard && w.hooked && w.playing && w.since_frame_ms >= 0 && w.since_frame_ms <= kSongFrameMs && !w.held && !w.typing;
}

// A JSON string at text[i] (its opening quote) as JSON writes it, into `out`, and i past its closing quote; false when it
// does not end. The escapes as JSON has them: a \uXXXX of ASCII is that character, another a '?' (no name has one).
inline bool json_string(const std::string& text, std::size_t& i, std::string& out) {
    out.clear();
    for (++i; i < text.size(); ++i) {
        const char c = text[i];
        if (c == '"') {
            ++i;
            return true;
        }
        if (c != '\\') {
            out += c;
            continue;
        }
        // An escape: its letter, and for \u its four hex digits.
        if (++i >= text.size()) return false;
        const char e = text[i];
        if (e == 'u') {
            if (i + 4 >= text.size()) return false;
            const std::string hex = text.substr(i + 1, 4);
            char* end = nullptr;
            const unsigned long v = std::strtoul(hex.c_str(), &end, 16);
            if (end != hex.c_str() + 4) return false;
            out += v < 0x80 ? static_cast<char>(v) : '?';
            i += 4;
        } else {
            out += e == 'n' ? '\n' : e == 't' ? '\t' : e == 'r' ? '\r' : e == 'b' ? '\b' : e == 'f' ? '\f' : e;
        }
    }
    return false;
}

// Whether an HTTP request saves a play: the game's RPC, a POST of a JSON list of calls, with a call whose method is
// game.savePlayResult (not game.savePlayResultFailLog, which keeps nothing). Read as JSON reads it: a "method" key's
// string value, never the same words inside another string.
inline bool saves_play(const std::string& method, const std::string& body) {
    if (method != "POST") return false;
    std::string s;
    // After a "method" key's colon: its value is next.
    bool method_value = false;
    for (std::size_t i = 0; i < body.size();) {
        const char c = body[i];
        if (c == '"') {
            if (!json_string(body, i, s)) return false;
            if (method_value) {
                if (s == "game.savePlayResult") return true;
                method_value = false;
                continue;
            }
            // A string followed by a colon is a key.
            std::size_t j = i;
            while (j < body.size() && (body[j] == ' ' || body[j] == '\t' || body[j] == '\r' || body[j] == '\n')) ++j;
            if (j < body.size() && body[j] == ':') {
                method_value = s == "method";
                i = j + 1;
            }
            continue;
        }
        // Anything but a space between a "method" key and a string: its value is no string.
        if (c != ' ' && c != '\t' && c != '\r' && c != '\n') method_value = false;
        ++i;
    }
    return false;
}

}  // namespace player::keys
