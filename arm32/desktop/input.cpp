// Input for the game: android.view.MotionEvent and KeyEvent as Unity's native code reads them (action, time, pointers or
// key, through JNI), a touch screen and a keyboard among the input devices, and the way events reach the game, which is
// the phone's: UnityPlayer's onTouchEvent and onKeyDown on the UI thread, which call nativeInjectEvent at once. The
// window's mouse is one finger and its wheel a finger's drag; the computer's keys are a phone's keys (Escape its Back
// key). Checks can also tap at a frame or a time of their choosing (PLAYER_TAPS="frame:x,y;@seconds:x,y;..."), through
// the same path.
#include "player.h"

#include "host.h"

#include <algorithm>

#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <map>
#include <mutex>
#include <string>
#include <vector>

namespace player {

namespace {

using jvm::Call;
using jvm::Class;
using jvm::Object;
using jvm::Ref;
using jvm::Value;

// MotionEvent's, KeyEvent's and InputDevice's numbers: a touch screen and a keyboard, the two devices.
constexpr jint kSourceTouchscreen = 0x1002, kToolFinger = 1, kTouchDevice = 1;
constexpr jint kSourceKeyboard = 0x101, kKeyboardDevice = 2, kKeyboardAlphabetic = 2;

struct Pointer {
    jint id;
    jfloat x, y;
};

class MotionEvent : public Object {
public:
    using Object::Object;
    jint action = 0;
    jlong down_time = 0, event_time = 0;
    std::vector<Pointer> pointers;
};

// A key of the computer's keyboard as the phone's: its Android key code, down or up, how often it repeated, its
// character (0 for none) and when it went down.
class KeyEvent : public Object {
public:
    using Object::Object;
    jint action = 0, code = 0, repeat = 0, unicode = 0;
    jlong down_time = 0, event_time = 0;
};

Class* g_motion = nullptr;
Class* g_key = nullptr;

jlong uptime_ms() {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<jlong>(ts.tv_sec) * 1000 + ts.tv_nsec / 1000000;
}

MotionEvent& motion(Call& c) { return c.self_as<MotionEvent>(); }
// Pointer k of an event, or an IllegalArgumentException as Android throws for an index out of range.
const Pointer& pointer(Call& c, std::size_t k) {
    const auto& ps = motion(c).pointers;
    if (k >= ps.size()) jvm::throw_new("java/lang/IllegalArgumentException", "pointerIndex out of range");
    return ps[k];
}

void define_events() {
    Class& input = jvm::define("android/view/InputEvent");
    input.method("getSource", "()I", [](Call&) { return Value::I(kSourceTouchscreen); });
    input.method("getDeviceId", "()I", [](Call&) { return Value::I(kTouchDevice); });
    Class& m = jvm::define("android/view/MotionEvent", "android/view/InputEvent");
    g_motion = &m;
    m.make = [](Class& k) -> Object* { return new MotionEvent(&k); };
    m.method("getAction", "()I", [](Call& c) { return Value::I(motion(c).action); });
    m.method("getActionMasked", "()I", [](Call& c) { return Value::I(motion(c).action & 0xff); });
    m.method("getActionIndex", "()I", [](Call& c) { return Value::I((motion(c).action >> 8) & 0xff); });
    m.method("getEventTime", "()J", [](Call& c) { return Value::J(motion(c).event_time); });
    m.method("getDownTime", "()J", [](Call& c) { return Value::J(motion(c).down_time); });
    // One sample per event: no history in between.
    m.method("getHistorySize", "()I", [](Call&) { return Value::I(0); });
    m.method("getPointerCount", "()I", [](Call& c) { return Value::I(static_cast<jint>(motion(c).pointers.size())); });
    m.method("getPointerId", "(I)I", [](Call& c) { return Value::I(pointer(c, static_cast<std::size_t>(c.i(0))).id); });
    m.method("getToolType", "(I)I", [](Call&) { return Value::I(kToolFinger); });
    m.method("getX", "(I)F", [](Call& c) { return Value::F(pointer(c, static_cast<std::size_t>(c.i(0))).x); });
    m.method("getY", "(I)F", [](Call& c) { return Value::F(pointer(c, static_cast<std::size_t>(c.i(0))).y); });
    m.method("getX", "()F", [](Call& c) { return Value::F(pointer(c, 0).x); });
    m.method("getY", "()F", [](Call& c) { return Value::F(pointer(c, 0).y); });
    m.method("getRawX", "()F", [](Call& c) { return Value::F(pointer(c, 0).x); });
    m.method("getRawY", "()F", [](Call& c) { return Value::F(pointer(c, 0).y); });
    m.method("getPressure", "(I)F", [](Call&) { return Value::F(1.0f); });
    m.method("getSize", "(I)F", [](Call&) { return Value::F(0.1f); });
    m.method("getMetaState", "()I", [](Call&) { return Value::I(0); });
    m.method("getFlags", "()I", [](Call&) { return Value::I(0); });
    m.method("getButtonState", "()I", [](Call&) { return Value::I(0); });
    m.method("recycle", "()V", [](Call&) { return Value(); });
    // obtain(MotionEvent): a copy, which the game keeps after the event is gone.
    m.static_method("obtain", "(Landroid/view/MotionEvent;)Landroid/view/MotionEvent;", [](Call& c) {
        auto* from = c.as<MotionEvent>(0);
        if (!from) jvm::throw_new("java/lang/NullPointerException", "obtain(null)");
        Ref<MotionEvent> copy(new MotionEvent(g_motion));
        copy->action = from->action;
        copy->down_time = from->down_time;
        copy->event_time = from->event_time;
        copy->pointers = from->pointers;
        return Value(copy);
    });
    // KeyEvent: the computer's keys (key()).
    Class& k = jvm::define("android/view/KeyEvent", "android/view/InputEvent");
    g_key = &k;
    k.make = [](Class& cls) -> Object* { return new KeyEvent(&cls); };
    auto key_of = [](Call& c) -> KeyEvent& { return c.self_as<KeyEvent>(); };
    k.method("getSource", "()I", [](Call&) { return Value::I(kSourceKeyboard); });
    k.method("getDeviceId", "()I", [](Call&) { return Value::I(kKeyboardDevice); });
    k.method("getAction", "()I", [key_of](Call& c) { return Value::I(key_of(c).action); });
    k.method("getKeyCode", "()I", [key_of](Call& c) { return Value::I(key_of(c).code); });
    k.method("getScanCode", "()I", [](Call&) { return Value::I(0); });
    k.method("getRepeatCount", "()I", [key_of](Call& c) { return Value::I(key_of(c).repeat); });
    k.method("getMetaState", "()I", [](Call&) { return Value::I(0); });
    k.method("getModifiers", "()I", [](Call&) { return Value::I(0); });
    k.method("getFlags", "()I", [](Call&) { return Value::I(0); });
    k.method("getDownTime", "()J", [key_of](Call& c) { return Value::J(key_of(c).down_time); });
    k.method("getEventTime", "()J", [key_of](Call& c) { return Value::J(key_of(c).event_time); });
    k.method("getUnicodeChar", "()I", [key_of](Call& c) { return Value::I(key_of(c).unicode); });
    k.method("getUnicodeChar", "(I)I", [key_of](Call& c) { return Value::I(key_of(c).unicode); });
    k.method("isSystem", "()Z", [key_of](Call& c) { return Value::Z(key_of(c).code == 4); });
    k.method("hasNoModifiers", "()Z", [](Call&) { return Value::Z(true); });
    k.method("isAltPressed", "()Z", [](Call&) { return Value::Z(false); });
    k.method("isShiftPressed", "()Z", [](Call&) { return Value::Z(false); });
    k.method("isCtrlPressed", "()Z", [](Call&) { return Value::Z(false); });
    k.method("getCharacters", "()Ljava/lang/String;", [](Call&) { return Value(); });
    // The touch screen and the keyboard, the input devices.
    Class& dev = jvm::define("android/view/InputDevice");
    Ref<Object> touch = jvm::new_object(dev, "()V");
    Ref<Object> keyboard = jvm::new_object(dev, "()V");
    dev.static_method("getDeviceIds", "()[I", [](Call&) {
        Ref<jvm::Array> ids = jvm::new_array(jvm::array_class(jvm::primitive_class('I')), 2);
        ids->data<jint>()[0] = kTouchDevice;
        ids->data<jint>()[1] = kKeyboardDevice;
        return Value(ids);
    });
    dev.static_method("getDevice", "(I)Landroid/view/InputDevice;", [touch, keyboard](Call& c) {
        return c.i(0) == kTouchDevice ? Value(touch) : c.i(0) == kKeyboardDevice ? Value(keyboard) : Value();
    });
    // Which of the two a call is about, by the object.
    auto is_keyboard = [keyboard](Call& c) { return c.self == keyboard.get(); };
    dev.method("getSources", "()I", [is_keyboard](Call& c) { return Value::I(is_keyboard(c) ? kSourceKeyboard : kSourceTouchscreen); });
    dev.method("getId", "()I", [is_keyboard](Call& c) { return Value::I(is_keyboard(c) ? kKeyboardDevice : kTouchDevice); });
    dev.method("getName", "()Ljava/lang/String;", [is_keyboard](Call& c) { return Value(jvm::string(is_keyboard(c) ? "OpenDMTQ keyboard" : "OpenDMTQ touch")); });
    dev.method("getKeyboardType", "()I", [is_keyboard](Call& c) { return Value::I(is_keyboard(c) ? kKeyboardAlphabetic : 0); });
    dev.method("isVirtual", "()Z", [](Call&) { return Value::Z(false); });
}

// MotionEvent's actions; the pointer's index goes in the second byte of POINTER_DOWN and POINTER_UP.
constexpr jint kActionDown = 0, kActionUp = 1, kActionMove = 2, kActionCancel = 3, kActionPointerDown = 5, kActionPointerUp = 6;
// The number touch() gives its one finger: the system numbers fingers from 0 up.
constexpr int kOwnFinger = -1;

// A finger on the screen: the system's number for it, and the pointer id the game sees, the smallest one not in use as
// Android gives them.
struct Finger {
    int system;
    jint id;
    jfloat x, y;
};
// The fingers down, in the order of their pointer ids, as Android lists a MotionEvent's pointers.
std::vector<Finger> g_fingers;
// When the first of them went down, for every event until the last is lifted.
jlong g_down_time = 0;
// The most fingers down at once since the stats last said (note_touch).
std::size_t g_most_fingers = 0;

// One MotionEvent with every finger down, to the game on the UI thread.
void send_motion(jint action, jlong now) {
    Ref<MotionEvent> e(new MotionEvent(g_motion));
    e->action = action;
    e->down_time = g_down_time;
    e->event_time = now;
    for (const Finger& f : g_fingers) e->pointers.push_back(Pointer{f.id, f.x, f.y});
    jvm::Env& env = jvm::attach();
    env.call(unity_player(), "nativeInjectEvent", "(Landroid/view/InputEvent;)Z", {Value(e)});
    if (env.pending) {
        jvm::log("player: nativeInjectEvent threw %s", env.pending->cls()->name.c_str());
        env.pending = {};
    }
}

// Taps a check asked for: by frame ("600:x,y"), and by time from the first frame ("@12.5:x,y", seconds), which holds
// whatever the frame rate (a display at 240 Hz runs four times the frames of one at 60).
struct PlannedTaps {
    std::map<std::uint64_t, std::pair<float, float>> by_frame;
    std::multimap<double, std::pair<float, float>> by_time;
};
PlannedTaps& planned_taps() {
    static PlannedTaps taps = [] {
        PlannedTaps out;
        const char* list = std::getenv("PLAYER_TAPS");
        for (const char* p = list; p && *p;) {
            const bool timed = *p == '@';
            char* end = nullptr;
            const double at = timed ? std::strtod(p + 1, &end) : static_cast<double>(std::strtoull(p, &end, 10));
            if (end == p + (timed ? 1 : 0) || *end != ':') break;
            float x = std::strtof(end + 1, &end);
            if (*end != ',') break;
            float y = std::strtof(end + 1, &end);
            if (timed) out.by_time.emplace(at, std::make_pair(x, y));
            else out.by_frame[static_cast<std::uint64_t>(at)] = {x, y};
            p = *end == ';' ? end + 1 : end;
        }
        return out;
    }();
    return taps;
}

// With stats on: how long after the touch screen saw a touch the game had it, and the most fingers down at once, in the
// log every five seconds. On the UI thread.
void note_touch(std::int64_t at_ns) {
    if (!arm32::g_stats) return;
    static std::vector<float> delays;
    static std::size_t most = 0;
    static jlong since = 0;
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    const std::int64_t now = static_cast<std::int64_t>(ts.tv_sec) * 1000000000 + ts.tv_nsec;
    delays.push_back(static_cast<float>(now - at_ns) / 1e6f);
    most = std::max(most, g_most_fingers);
    g_most_fingers = 0;
    const jlong t = uptime_ms();
    if (!since) since = t;
    if (t - since < 5000) return;
    std::sort(delays.begin(), delays.end());
    auto at = [&](float q) { return delays[static_cast<std::size_t>(q * static_cast<float>(delays.size() - 1))]; };
    jvm::log("stats: touches reached the game ms p50 %.2f p99 %.2f max %.2f after the screen saw them, %zu events, up to %zu fingers", at(0.5f),
             at(0.99f), delays.back(), delays.size(), most);
    delays.clear();
    most = 0;
    since = t;
}

// A planned tap on the UI thread: down now, up a tenth of a second later, as a finger taps.
void planned_tap(float x, float y, const std::string& when) {
    main_looper().post([x, y, when] {
        jvm::log("player: %s: a tap at %.0f,%.0f", when.c_str(), x, y);
        touch(0, x, y);
    });
    main_looper().post([x, y] { touch(1, x, y); }, Looper::Clock::now() + std::chrono::milliseconds(100));
}

// The wheel's finger (wheel()): a number no system finger has, and its drag still to go, in game pixels.
constexpr int kWheelFinger = -2;
struct WheelDrag {
    bool down = false;
    float x = 0, y = 0, left_x = 0, left_y = 0;
    // When it last moved, for the rest before it lifts.
    Looper::Clock::time_point moved;
};
WheelDrag g_wheel;

// One step of the wheel's drag, every 8 ms on the UI thread: a quarter notch's way at most, then a rest of 60 ms with no
// movement, so that the list stops where the drag left it instead of flinging on, then the finger lifts.
void wheel_step() {
    WheelDrag& w = g_wheel;
    if (!w.down) return;
    const auto now = Looper::Clock::now();
    if (w.left_x == 0 && w.left_y == 0) {
        if (now - w.moved < std::chrono::milliseconds(60)) {
            main_looper().post(wheel_step, now + std::chrono::milliseconds(8));
            return;
        }
        finger(kWheelFinger, 1, w.x, w.y);
        w.down = false;
        return;
    }
    const float step = static_cast<float>(app().height) / 32.0f;
    auto toward = [step](float& left) {
        const float d = std::clamp(left, -step, step);
        left -= d;
        return d;
    };
    const float nx = std::clamp(w.x + toward(w.left_x), 0.0f, static_cast<float>(app().width - 1));
    const float ny = std::clamp(w.y + toward(w.left_y), 0.0f, static_cast<float>(app().height - 1));
    // At the game's edge the rest of the way is lost, as a finger runs out of screen.
    if (nx == w.x && ny == w.y) w.left_x = w.left_y = 0;
    w.x = nx;
    w.y = ny;
    w.moved = now;
    finger(kWheelFinger, 2, w.x, w.y);
    main_looper().post(wheel_step, now + std::chrono::milliseconds(8));
}

}  // namespace

void finger(int system, int what, float x, float y, std::int64_t at_ns) {
    // On the UI thread, as onTouchEvent is called. The event's time is the touch screen's own when it gave one.
    jlong now = at_ns >= 0 ? static_cast<jlong>(at_ns / 1000000) : uptime_ms();
    if (at_ns >= 0) note_touch(at_ns);
    auto it = std::find_if(g_fingers.begin(), g_fingers.end(), [system](const Finger& f) { return f.system == system; });
    if (what == 3) {
        // The system took the gesture away: every finger goes, cancelled.
        if (g_fingers.empty()) return;
        send_motion(kActionCancel, now);
        g_fingers.clear();
        return;
    }
    if (what == 0) {
        if (it != g_fingers.end()) return;
        // Another finger on the game ends the wheel's drag first: the two would make one gesture of two fingers.
        if (system != kWheelFinger && g_wheel.down) {
            g_wheel.left_x = g_wheel.left_y = 0;
            g_wheel.down = false;
            finger(kWheelFinger, 1, g_wheel.x, g_wheel.y);
            it = g_fingers.end();
        }
        // The smallest pointer id not in use, put in its place by id.
        jint id = 0;
        while (std::any_of(g_fingers.begin(), g_fingers.end(), [id](const Finger& f) { return f.id == id; })) ++id;
        auto at = std::find_if(g_fingers.begin(), g_fingers.end(), [id](const Finger& f) { return f.id > id; });
        auto index = static_cast<jint>(at - g_fingers.begin());
        g_fingers.insert(at, Finger{system, id, x, y});
        g_most_fingers = std::max(g_most_fingers, g_fingers.size());
        // The first finger starts the gesture; the others join it at their index.
        if (g_fingers.size() == 1) {
            g_down_time = now;
            send_motion(kActionDown, now);
        } else {
            send_motion(kActionPointerDown | (index << 8), now);
        }
        return;
    }
    if (it == g_fingers.end()) return;
    it->x = x;
    it->y = y;
    if (what == 2) {
        send_motion(kActionMove, now);
        return;
    }
    // Lifted: the event still lists it, and it goes after.
    auto index = static_cast<jint>(it - g_fingers.begin());
    send_motion(g_fingers.size() == 1 ? kActionUp : (kActionPointerUp | (index << 8)), now);
    g_fingers.erase(g_fingers.begin() + index);
}

void touch(int action, float x, float y) { finger(kOwnFinger, action, x, y); }

void wheel(float x, float y, float notches_x, float notches_y) {
    // On the UI thread. A notch is an eighth of the game's height; up and down drag the finger down and up, as a list
    // follows a finger: a turn away from the user shows what is above. A sideways turn drags across the same way.
    WheelDrag& w = g_wheel;
    // A finger, a pen or the mouse's button down already: the wheel waits (its finger would join their gesture).
    if (!w.down && !g_fingers.empty()) return;
    const float notch = static_cast<float>(app().height) / 8.0f;
    w.left_x -= notches_x * notch;
    w.left_y += notches_y * notch;
    if (w.down) return;
    w.down = true;
    w.x = x;
    w.y = y;
    w.moved = Looper::Clock::now();
    finger(kWheelFinger, 0, x, y);
    main_looper().post(wheel_step, Looper::Clock::now() + std::chrono::milliseconds(8));
}

void key(int code, bool down, int repeat, int unicode) {
    // On the UI thread, as onKeyDown and onKeyUp are called: to the game at once, as a phone's key.
    static jlong down_time = 0;
    const jlong now = uptime_ms();
    if (down && repeat == 0) down_time = now;
    Ref<KeyEvent> e(new KeyEvent(g_key));
    e->action = down ? 0 : 1;
    e->code = code;
    e->repeat = repeat;
    e->unicode = unicode;
    e->down_time = down_time;
    e->event_time = now;
    jvm::Env& env = jvm::attach();
    env.call(unity_player(), "nativeInjectEvent", "(Landroid/view/InputEvent;)Z", {Value(e)});
    if (env.pending) {
        jvm::log("player: nativeInjectEvent threw %s for a key", env.pending->cls()->name.c_str());
        env.pending = {};
    }
}

void frame_shown(std::uint64_t n) {
    PlannedTaps& taps = planned_taps();
    if (auto it = taps.by_frame.find(n); it != taps.by_frame.end()) {
        planned_tap(it->second.first, it->second.second, "frame " + std::to_string(n));
    }
    if (taps.by_time.empty()) return;
    // Seconds since the first frame.
    static const jlong first = uptime_ms();
    const double seconds = static_cast<double>(uptime_ms() - first) / 1000.0;
    while (!taps.by_time.empty() && taps.by_time.begin()->first <= seconds) {
        auto [at, where] = *taps.by_time.begin();
        taps.by_time.erase(taps.by_time.begin());
        char when[48];
        std::snprintf(when, sizeof when, "%.1f s (frame %llu)", at, static_cast<unsigned long long>(n));
        planned_tap(where.first, where.second, when);
    }
}

// ---------------------------------------------------------------------------------------------------------------------
// The soft keyboard: Unity asks for one with showSoftInput and hears the text through nativeSetInputString (as it
// changes, and when done) and nativeSoftInputClosed, on its main thread, as UnityPlayer.reportSoftInputStr sends them.
// Here the computer's keyboard types into it: Enter is done, Escape cancels. A check sets PLAYER_TEXT to have it filled
// in and done half a second after it opens.

namespace {

std::mutex g_text_lock;
bool g_typing = false;
std::string g_text;
// What an input method is still composing (a Hangul syllable before it is done), shown to the game after the text, as
// a phone's text field holds its composing text.
std::string g_composing;

// reportSoftInputStr(text, close ? 1 : 0, canceled), on the Unity main thread. The close goes a tenth of a second after
// the text: the game's text field takes the keyboard's text only while the keyboard is open, as a phone's keyboard reports
// each change before it closes, and a text and its close in one turn left the field with the text it had.
void report(const std::string& text, bool close, bool canceled) {
    unity_looper().post([text, canceled] {
        jvm::Env& e = jvm::attach();
        Object* view = unity_player();
        if (canceled) e.call(view, "nativeSetInputCanceled", "(Z)V", {Value::Z(true)});
        else e.call(view, "nativeSetInputString", "(Ljava/lang/String;)V", {Value(jvm::string(text))});
        if (e.pending) {
            jvm::log("player: the soft keyboard's report threw %s", e.pending->cls()->name.c_str());
            e.pending = {};
        }
    });
    if (!close) return;
    unity_looper().post(
        [] {
            jvm::Env& e = jvm::attach();
            e.call(unity_player(), "nativeSoftInputClosed", "()V");
            if (e.pending) {
                jvm::log("player: the soft keyboard's close threw %s", e.pending->cls()->name.c_str());
                e.pending = {};
            }
        },
        Looper::Clock::now() + std::chrono::milliseconds(100));
}

// Ends the session: done with its text, the composing part included, or canceled.
void finish(bool canceled) {
    std::string text;
    {
        std::lock_guard<std::mutex> l(g_text_lock);
        if (!g_typing) return;
        g_typing = false;
        text = g_text + g_composing;
        g_composing.clear();
    }
    report(text, true, canceled);
    soft_keyboard(false);
}

}  // namespace

bool typing() {
    std::lock_guard<std::mutex> l(g_text_lock);
    return g_typing;
}

void type_text(const std::string& utf8) {
    std::string now;
    {
        std::lock_guard<std::mutex> l(g_text_lock);
        if (!g_typing) return;
        g_text += utf8;
        now = g_text + g_composing;
    }
    report(now, false, false);
}

void type_composing(const std::string& utf8) {
    std::string now;
    {
        std::lock_guard<std::mutex> l(g_text_lock);
        if (!g_typing || g_composing == utf8) return;
        g_composing = utf8;
        now = g_text + g_composing;
    }
    report(now, false, false);
}

void type_key(int key) {
    if (key == kKeyEnter) return finish(false);
    if (key == kKeyEscape) return finish(true);
    if (key != kKeyBackspace) return;
    std::string now;
    {
        std::lock_guard<std::mutex> l(g_text_lock);
        if (!g_typing || g_text.empty()) return;
        // One character back, whatever its UTF-8 length (an input method takes back its own composing ones).
        std::size_t cut = g_text.size() - 1;
        while (cut > 0 && (static_cast<unsigned char>(g_text[cut]) & 0xc0) == 0x80) --cut;
        g_text.erase(cut);
        now = g_text + g_composing;
    }
    report(now, false, false);
}

void define_input() {
    define_events();
    Class& p = *jvm::find_class("com/unity3d/player/UnityPlayer");
    p.method("showSoftInput", "(Ljava/lang/String;IZZZZLjava/lang/String;)V", [](Call& c) {
        {
            std::lock_guard<std::mutex> l(g_text_lock);
            g_typing = true;
            g_text = c.str(0);
            g_composing.clear();
        }
        jvm::log("player: the game asks for text (the keyboard types; Enter is done, Escape cancels)");
        soft_keyboard(true);
        // An empty PLAYER_TEXT is none (a check that passes the variable on whether or not it has one).
        if (const char* auto_text = std::getenv("PLAYER_TEXT"); auto_text && *auto_text) {
            std::string text = auto_text;
            main_looper().post(
                [text] {
                    {
                        std::lock_guard<std::mutex> l(g_text_lock);
                        g_text = text;
                    }
                    jvm::log("player: typed \"%s\"", text.c_str());
                    finish(false);
                },
                Looper::Clock::now() + std::chrono::milliseconds(500));
        }
        return Value();
    });
    p.method("hideSoftInput", "()V", [](Call&) {
        {
            std::lock_guard<std::mutex> l(g_text_lock);
            g_typing = false;
        }
        soft_keyboard(false);
        return Value();
    });
    p.method("setSoftInputStr", "(Ljava/lang/String;)V", [](Call& c) {
        std::lock_guard<std::mutex> l(g_text_lock);
        if (g_typing && c.l(0)) g_text = c.str(0);
        return Value();
    });
}

}  // namespace player
