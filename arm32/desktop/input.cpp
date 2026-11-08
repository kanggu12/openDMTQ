// Touch input for the game: android.view.MotionEvent as Unity's native code reads it (its action, time and pointers,
// through JNI), a touch screen among the input devices, and the way events reach the game, which is the phone's:
// UnityPlayer.onTouchEvent on the UI thread, which calls nativeInjectEvent at once. The window's mouse is one finger;
// checks can also tap at a frame of their choosing (PLAYER_TAPS="frame:x,y;..."), through the same path.
#include "player.h"

#include <algorithm>

#include <cstdlib>
#include <ctime>
#include <map>
#include <mutex>
#include <vector>

namespace player {

namespace {

using jvm::Call;
using jvm::Class;
using jvm::Object;
using jvm::Ref;
using jvm::Value;

// MotionEvent's and InputDevice's numbers.
constexpr jint kSourceTouchscreen = 0x1002, kToolFinger = 1, kTouchDevice = 1;

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

Class* g_motion = nullptr;

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
    // The touch screen, the one input device.
    Class& dev = jvm::define("android/view/InputDevice");
    Ref<Object> touch = jvm::new_object(dev, "()V");
    dev.static_method("getDeviceIds", "()[I", [](Call&) {
        Ref<jvm::Array> ids = jvm::new_array(jvm::array_class(jvm::primitive_class('I')), 1);
        ids->data<jint>()[0] = kTouchDevice;
        return Value(ids);
    });
    dev.static_method("getDevice", "(I)Landroid/view/InputDevice;", [touch](Call& c) { return c.i(0) == kTouchDevice ? Value(touch) : Value(); });
    dev.method("getSources", "()I", [](Call&) { return Value::I(kSourceTouchscreen); });
    dev.method("getId", "()I", [](Call&) { return Value::I(kTouchDevice); });
    dev.method("getName", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string("OpenDMTQ touch")); });
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

// Taps a check asked for, by frame.
std::map<std::uint64_t, std::pair<float, float>>& planned_taps() {
    static std::map<std::uint64_t, std::pair<float, float>> taps = [] {
        std::map<std::uint64_t, std::pair<float, float>> out;
        const char* list = std::getenv("PLAYER_TAPS");
        for (const char* p = list; p && *p;) {
            char* end = nullptr;
            unsigned long long frame = std::strtoull(p, &end, 10);
            if (end == p || *end != ':') break;
            float x = std::strtof(end + 1, &end);
            if (*end != ',') break;
            float y = std::strtof(end + 1, &end);
            out[frame] = {x, y};
            p = *end == ';' ? end + 1 : end;
        }
        return out;
    }();
    return taps;
}

}  // namespace

void finger(int system, int what, float x, float y) {
    // On the UI thread, as onTouchEvent is called.
    jlong now = uptime_ms();
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
        // The smallest pointer id not in use, put in its place by id.
        jint id = 0;
        while (std::any_of(g_fingers.begin(), g_fingers.end(), [id](const Finger& f) { return f.id == id; })) ++id;
        auto at = std::find_if(g_fingers.begin(), g_fingers.end(), [id](const Finger& f) { return f.id > id; });
        auto index = static_cast<jint>(at - g_fingers.begin());
        g_fingers.insert(at, Finger{system, id, x, y});
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

void frame_shown(std::uint64_t n) {
    auto& taps = planned_taps();
    auto it = taps.find(n);
    if (it == taps.end()) return;
    // A tap on the UI thread: down now, up a tenth of a second later, as a finger taps.
    auto [x, y] = it->second;
    main_looper().post([x, y, n] {
        jvm::log("player: frame %llu: a tap at %.0f,%.0f", static_cast<unsigned long long>(n), x, y);
        touch(0, x, y);
    });
    main_looper().post([x, y] { touch(1, x, y); }, Looper::Clock::now() + std::chrono::milliseconds(100));
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

// reportSoftInputStr(text, close ? 1 : 0, canceled), on the Unity main thread.
void report(const std::string& text, bool close, bool canceled) {
    unity_looper().post([text, close, canceled] {
        jvm::Env& e = jvm::attach();
        Object* view = unity_player();
        if (canceled) e.call(view, "nativeSetInputCanceled", "(Z)V", {Value::Z(true)});
        else e.call(view, "nativeSetInputString", "(Ljava/lang/String;)V", {Value(jvm::string(text))});
        if (close) e.call(view, "nativeSoftInputClosed", "()V");
        if (e.pending) {
            jvm::log("player: the soft keyboard's report threw %s", e.pending->cls()->name.c_str());
            e.pending = {};
        }
    });
}

// Ends the session: done with its text, or canceled.
void finish(bool canceled) {
    std::string text;
    {
        std::lock_guard<std::mutex> l(g_text_lock);
        if (!g_typing) return;
        g_typing = false;
        text = g_text;
    }
    report(text, true, canceled);
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
        now = g_text;
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
        // One character back, whatever its UTF-8 length.
        std::size_t cut = g_text.size() - 1;
        while (cut > 0 && (static_cast<unsigned char>(g_text[cut]) & 0xc0) == 0x80) --cut;
        g_text.erase(cut);
        now = g_text;
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
        }
        jvm::log("player: the game asks for text (the keyboard types; Enter is done, Escape cancels)");
        if (const char* auto_text = std::getenv("PLAYER_TEXT")) {
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
        std::lock_guard<std::mutex> l(g_text_lock);
        g_typing = false;
        return Value();
    });
    p.method("setSoftInputStr", "(Ljava/lang/String;)V", [](Call& c) {
        std::lock_guard<std::mutex> l(g_text_lock);
        if (g_typing && c.l(0)) g_text = c.str(0);
        return Value();
    });
}

}  // namespace player
