// Android's constants and system services as the game reads them: the static fields it asks for (service names, screen
// orientations, system UI flags, media keys...), the display and its metrics, the window and the views, input devices,
// audio focus, the network, vibration, memory, and the device's id. What a phone would answer, from the App the player
// describes.
#include "player.h"

#include <cstdio>
#include <fstream>
#include <random>

namespace player {

namespace {

using jvm::Call;
using jvm::Class;
using jvm::Object;
using jvm::Ref;
using jvm::Value;

// Static fields, int or String, of one class.
void ints(const char* cls, std::initializer_list<std::pair<const char*, jint>> fields) {
    Class& c = jvm::define(cls);
    for (auto& [name, v] : fields) c.static_field(name, "I", Value::I(v));
}
void strings(const char* cls, std::initializer_list<std::pair<const char*, const char*>> fields) {
    Class& c = jvm::define(cls);
    for (auto& [name, v] : fields) c.static_field(name, "Ljava/lang/String;", Value(jvm::string(v)));
}

void define_constants() {
    strings("android/content/Context", {{"ACTIVITY_SERVICE", "activity"},
                                        {"AUDIO_SERVICE", "audio"},
                                        {"CLIPBOARD_SERVICE", "clipboard"},
                                        {"CONNECTIVITY_SERVICE", "connectivity"},
                                        {"DISPLAY_SERVICE", "display"},
                                        {"INPUT_METHOD_SERVICE", "input_method"},
                                        {"INPUT_SERVICE", "input"},
                                        {"LOCATION_SERVICE", "location"},
                                        {"MEDIA_ROUTER_SERVICE", "media_router"},
                                        {"POWER_SERVICE", "power"},
                                        {"SENSOR_SERVICE", "sensor"},
                                        {"TELEPHONY_SERVICE", "phone"},
                                        {"UI_MODE_SERVICE", "uimode"},
                                        {"VIBRATOR_SERVICE", "vibrator"},
                                        {"WIFI_SERVICE", "wifi"},
                                        {"WINDOW_SERVICE", "window"}});
    ints("android/content/Context", {{"MODE_PRIVATE", 0}});
    ints("android/view/WindowManager$LayoutParams", {{"FLAG_FULLSCREEN", 1024}, {"FLAG_KEEP_SCREEN_ON", 128}});
    ints("android/view/View", {{"SYSTEM_UI_FLAG_VISIBLE", 0},
                               {"SYSTEM_UI_FLAG_LOW_PROFILE", 1},
                               {"SYSTEM_UI_FLAG_HIDE_NAVIGATION", 2},
                               {"SYSTEM_UI_FLAG_FULLSCREEN", 4},
                               {"SYSTEM_UI_FLAG_LAYOUT_STABLE", 256},
                               {"SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION", 512},
                               {"SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN", 1024},
                               {"SYSTEM_UI_FLAG_IMMERSIVE", 2048},
                               {"SYSTEM_UI_FLAG_IMMERSIVE_STICKY", 4096}});
    strings("android/os/Environment", {{"MEDIA_MOUNTED", "mounted"}});
    ints("android/net/ConnectivityManager", {{"TYPE_MOBILE", 0}, {"TYPE_WIFI", 1}, {"TYPE_ETHERNET", 9}});
    ints("android/media/MediaRouter", {{"ROUTE_TYPE_LIVE_AUDIO", 1}, {"ROUTE_TYPE_LIVE_VIDEO", 2}});
    strings("android/media/MediaFormat", {{"KEY_MIME", "mime"},
                                          {"KEY_WIDTH", "width"},
                                          {"KEY_HEIGHT", "height"},
                                          {"KEY_SAMPLE_RATE", "sample-rate"},
                                          {"KEY_CHANNEL_COUNT", "channel-count"},
                                          {"KEY_MAX_INPUT_SIZE", "max-input-size"},
                                          {"KEY_LANGUAGE", "language"},
                                          {"KEY_FRAME_RATE", "frame-rate"},
                                          {"KEY_DURATION", "durationUs"}});
    ints("android/media/AudioManager", {{"STREAM_MUSIC", 3}, {"AUDIOFOCUS_GAIN", 1}, {"AUDIOFOCUS_REQUEST_GRANTED", 1}, {"AUDIOFOCUS_LOSS", -1}});
    ints("android/content/pm/PackageManager", {{"GET_META_DATA", 128}, {"PERMISSION_GRANTED", 0}, {"PERMISSION_DENIED", -1}});
    strings("android/content/pm/PackageManager", {{"FEATURE_AUDIO_LOW_LATENCY", "android.hardware.audio.low_latency"},
                                                  {"FEATURE_TOUCHSCREEN", "android.hardware.touchscreen"}});
    ints("android/content/pm/ActivityInfo", {{"SCREEN_ORIENTATION_UNSPECIFIED", -1},
                                             {"SCREEN_ORIENTATION_LANDSCAPE", 0},
                                             {"SCREEN_ORIENTATION_PORTRAIT", 1},
                                             {"SCREEN_ORIENTATION_SENSOR", 4},
                                             {"SCREEN_ORIENTATION_SENSOR_LANDSCAPE", 6},
                                             {"SCREEN_ORIENTATION_SENSOR_PORTRAIT", 7},
                                             {"SCREEN_ORIENTATION_REVERSE_LANDSCAPE", 8},
                                             {"SCREEN_ORIENTATION_REVERSE_PORTRAIT", 9},
                                             {"SCREEN_ORIENTATION_FULL_SENSOR", 10}});
    strings("android/Manifest$permission", {{"VIBRATE", "android.permission.VIBRATE"},
                                            {"WRITE_EXTERNAL_STORAGE", "android.permission.WRITE_EXTERNAL_STORAGE"},
                                            {"READ_EXTERNAL_STORAGE", "android.permission.READ_EXTERNAL_STORAGE"}});
    strings("android/provider/Settings$Secure", {{"ANDROID_ID", "android_id"}});
}

// ---------------------------------------------------------------------------------------------------------------------
// The display: the window's size, the App's refresh rate and density.

Ref<Object> g_display;

// DisplayMetrics' fields, set from the App: widthPixels, heightPixels, density (1 at 160 dpi), densityDpi and the rest.
void fill_metrics(Object* m) {
    if (!m) return;
    Class& c = *jvm::find_class("android/util/DisplayMetrics");
    auto set = [&](const char* name, Value v) { m->set_field(c.find_field(name, false), v); };
    const App& a = app();
    set("widthPixels", Value::I(a.width));
    set("heightPixels", Value::I(a.height));
    set("density", Value::F(a.density));
    set("scaledDensity", Value::F(a.density));
    set("densityDpi", Value::I(static_cast<jint>(a.density * 160)));
    set("xdpi", Value::F(a.density * 160));
    set("ydpi", Value::F(a.density * 160));
}

void define_display() {
    jvm::define("android/util/DisplayMetrics")
        .field("widthPixels", "I")
        .field("heightPixels", "I")
        .field("density", "F")
        .field("scaledDensity", "F")
        .field("densityDpi", "I")
        .field("xdpi", "F")
        .field("ydpi", "F")
        .method("<init>", "()V", [](Call&) { return Value(); })
        .method("setToDefaults", "()V", [](Call& c) {
            fill_metrics(c.self);
            return Value();
        });
    jvm::define("android/graphics/Point").field("x", "I").field("y", "I").method("<init>", "()V", [](Call&) { return Value(); });
    auto size = [](Call& c) {
        if (Object* p = c.l(0)) {
            Class& k = *jvm::find_class("android/graphics/Point");
            p->set_field(k.find_field("x", false), Value::I(app().width));
            p->set_field(k.find_field("y", false), Value::I(app().height));
        }
        return Value();
    };
    Class& d = jvm::define("android/view/Display");
    d.method("getDisplayId", "()I", [](Call&) { return Value::I(0); })
        .method("getWidth", "()I", [](Call&) { return Value::I(app().width); })
        .method("getHeight", "()I", [](Call&) { return Value::I(app().height); })
        .method("getRefreshRate", "()F", [](Call&) { return Value::F(app().refresh); })
        .method("getRotation", "()I", [](Call&) { return Value::I(0); })
        .method("getName", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string("Built-in Screen")); })
        .method("getMetrics", "(Landroid/util/DisplayMetrics;)V", [](Call& c) {
            fill_metrics(c.l(0));
            return Value();
        })
        .method("getRealMetrics", "(Landroid/util/DisplayMetrics;)V", [](Call& c) {
            fill_metrics(c.l(0));
            return Value();
        })
        .method("getSize", "(Landroid/graphics/Point;)V", size)
        .method("getRealSize", "(Landroid/graphics/Point;)V", size)
        .method("getSupportedRefreshRates", "()[F", [](Call&) {
            Ref<jvm::Array> a = jvm::new_array(jvm::array_class(jvm::primitive_class('F')), 1);
            a->data<jfloat>()[0] = app().refresh;
            return Value(a);
        });
    g_display = jvm::new_object(d, "()V");
    Class& wm = jvm::define("android/view/WindowManagerImpl");
    wm.interfaces.push_back(&jvm::define_interface("android/view/WindowManager"));
    wm.method("getDefaultDisplay", "()Landroid/view/Display;", [](Call&) { return Value(g_display); });
    Class& dm = jvm::define("android/hardware/display/DisplayManager");
    dm.method("getDisplay", "(I)Landroid/view/Display;", [](Call& c) { return c.i(0) == 0 ? Value(g_display) : Value(); });
    dm.method("getDisplays", "()[Landroid/view/Display;", [](Call&) {
        Ref<jvm::Array> a = jvm::new_array(jvm::array_class(*jvm::find_class("android/view/Display")), 1);
        a->items[0] = g_display;
        return Value(a);
    });
    // Displays do not come and go here: listeners hear nothing.
    dm.method("registerDisplayListener", "(Landroid/hardware/display/DisplayManager$DisplayListener;Landroid/os/Handler;)V", [](Call&) { return Value(); });
    dm.method("unregisterDisplayListener", "(Landroid/hardware/display/DisplayManager$DisplayListener;)V", [](Call&) { return Value(); });
}

// ---------------------------------------------------------------------------------------------------------------------
// The window and views: the system UI flags the game sets are kept and read back; nothing else changes.

class View : public Object {
public:
    using Object::Object;
    std::atomic<jint> ui_flags{0};
};

Ref<Object> g_decor;

void define_views() {
    Class& v = jvm::define("android/view/View");
    v.make = [](Class& k) -> Object* { return new View(&k); };
    // The classes UnityPlayer and the decor view extend, so that code testing their classes gets the phone's answers.
    jvm::define("android/view/ViewGroup", "android/view/View");
    jvm::define("android/widget/FrameLayout", "android/view/ViewGroup");
    jvm::define("android/view/SurfaceView", "android/view/View");
    jvm::define("com/android/internal/policy/DecorView", "android/widget/FrameLayout");
    v.method("getSystemUiVisibility", "()I", [](Call& c) { return Value::I(c.self_as<View>().ui_flags.load()); });
    v.method("setSystemUiVisibility", "(I)V", [](Call& c) {
        c.self_as<View>().ui_flags = c.i(0);
        return Value();
    });
    v.method("setOnSystemUiVisibilityChangeListener", "(Landroid/view/View$OnSystemUiVisibilityChangeListener;)V", [](Call&) { return Value(); });
    v.method("getWidth", "()I", [](Call&) { return Value::I(app().width); });
    v.method("getHeight", "()I", [](Call&) { return Value::I(app().height); });
    v.method("getRootView", "()Landroid/view/View;", [](Call& c) { return Value(c.self); });
    v.method("requestFocus", "()Z", [](Call&) { return Value::Z(true); });
    v.method("setKeepScreenOn", "(Z)V", [](Call&) { return Value(); });
    g_decor = jvm::new_object(*jvm::find_class("com/android/internal/policy/DecorView"), "()V");
    Class& w = jvm::define("com/android/internal/policy/PhoneWindow", "android/view/Window");
    w.method("getDecorView", "()Landroid/view/View;", [](Call&) { return Value(g_decor); });
    for (const char* name : {"setFlags", "addFlags", "clearFlags"}) {
        bool two = std::string(name) == "setFlags";
        w.method(name, two ? "(II)V" : "(I)V", [](Call&) { return Value(); });
    }
    w.method("setFormat", "(I)V", [](Call&) { return Value(); });
    w.method("requestFeature", "(I)Z", [](Call&) { return Value::Z(true); });
}

// ---------------------------------------------------------------------------------------------------------------------
// The other services.

void define_services() {
    // Input devices: the touch screen's listeners hear nothing, devices do not come and go (input.cpp has the device).
    Class& im = jvm::define("android/hardware/input/InputManager");
    im.method("registerInputDeviceListener", "(Landroid/hardware/input/InputManager$InputDeviceListener;Landroid/os/Handler;)V", [](Call&) { return Value(); });
    im.method("unregisterInputDeviceListener", "(Landroid/hardware/input/InputManager$InputDeviceListener;)V", [](Call&) { return Value(); });
    im.method("getInputDeviceIds", "()[I", [](Call&) { return Value(jvm::new_array(jvm::array_class(jvm::primitive_class('I')), 0)); });
    // Audio: focus is granted at once, and the output's own rate and buffer are a desktop sound card's.
    Class& am = jvm::define("android/media/AudioManager");
    am.method("requestAudioFocus", "(Landroid/media/AudioManager$OnAudioFocusChangeListener;II)I", [](Call&) { return Value::I(1); });
    am.method("abandonAudioFocus", "(Landroid/media/AudioManager$OnAudioFocusChangeListener;)I", [](Call&) { return Value::I(1); });
    am.method("getProperty", "(Ljava/lang/String;)Ljava/lang/String;", [](Call& c) {
        std::string k = c.str(0);
        if (k == "android.media.property.OUTPUT_SAMPLE_RATE") return Value(jvm::string("48000"));
        if (k == "android.media.property.OUTPUT_FRAMES_PER_BUFFER") return Value(jvm::string("240"));
        return Value();
    });
    am.method("getStreamVolume", "(I)I", [](Call&) { return Value::I(10); });
    am.method("getStreamMaxVolume", "(I)I", [](Call&) { return Value::I(15); });
    am.method("getRingerMode", "()I", [](Call&) { return Value::I(2); });
    am.method("isMusicActive", "()Z", [](Call&) { return Value::Z(false); });
    am.method("isWiredHeadsetOn", "()Z", [](Call&) { return Value::Z(false); });
    // The network: one connected Wi-Fi network, whatever the computer has (the game only asks whether there is one).
    Class& ni = jvm::define("android/net/NetworkInfo");
    ni.method("getType", "()I", [](Call&) { return Value::I(1); });
    ni.method("getTypeName", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string("WIFI")); });
    ni.method("isConnected", "()Z", [](Call&) { return Value::Z(true); });
    ni.method("isConnectedOrConnecting", "()Z", [](Call&) { return Value::Z(true); });
    ni.method("isAvailable", "()Z", [](Call&) { return Value::Z(true); });
    Ref<Object> network = jvm::new_object(ni, "()V");
    jvm::define("android/net/ConnectivityManager").method("getActiveNetworkInfo", "()Landroid/net/NetworkInfo;", [network](Call&) { return Value(network); });
    // No vibration motor.
    Class& vib = jvm::define("android/os/SystemVibrator", "android/os/Vibrator");
    vib.method("hasVibrator", "()Z", [](Call&) { return Value::Z(false); });
    vib.method("vibrate", "(J)V", [](Call&) { return Value(); });
    vib.method("cancel", "()V", [](Call&) { return Value(); });
    // No phone.
    Class& tel = jvm::define("android/telephony/TelephonyManager");
    for (const char* name : {"getNetworkOperatorName", "getNetworkOperator", "getSimOperator", "getSimOperatorName", "getNetworkCountryIso", "getSimCountryIso"}) {
        tel.method(name, "()Ljava/lang/String;", [](Call&) { return Value(jvm::string("")); });
    }
    tel.method("getPhoneType", "()I", [](Call&) { return Value::I(0); });
    tel.method("listen", "(Landroid/telephony/PhoneStateListener;I)V", [](Call&) { return Value(); });
    // No second screen.
    Class& route = jvm::define("android/media/MediaRouter$RouteInfo");
    route.method("getPresentationDisplay", "()Landroid/view/Display;", [](Call&) { return Value(); });
    Ref<Object> selected = jvm::new_object(route, "()V");
    jvm::define("android/media/MediaRouter").method("getSelectedRoute", "(I)Landroid/media/MediaRouter$RouteInfo;", [selected](Call&) { return Value(selected); });
    // Memory: a computer's plenty.
    Class& mi = jvm::define("android/app/ActivityManager$MemoryInfo");
    mi.field("availMem", "J").field("totalMem", "J").field("threshold", "J").field("lowMemory", "Z");
    mi.method("<init>", "()V", [](Call&) { return Value(); });
    Class& actm = jvm::define("android/app/ActivityManager");
    actm.method("getMemoryInfo", "(Landroid/app/ActivityManager$MemoryInfo;)V", [](Call& c) {
        if (Object* m = c.l(0)) {
            Class& k = *jvm::find_class("android/app/ActivityManager$MemoryInfo");
            m->set_field(k.find_field("availMem", false), Value::J(4LL << 30));
            m->set_field(k.find_field("totalMem", false), Value::J(8LL << 30));
            m->set_field(k.find_field("threshold", false), Value::J(256LL << 20));
            m->set_field(k.find_field("lowMemory", false), Value::Z(false));
        }
        return Value();
    });
    actm.method("getMemoryClass", "()I", [](Call&) { return Value::I(512); });
    actm.method("getLargeMemoryClass", "()I", [](Call&) { return Value::I(1024); });
    actm.method("isLowRamDevice", "()Z", [](Call&) { return Value::Z(false); });
    // The screen stays on.
    Class& pm = jvm::define("android/os/PowerManager");
    pm.method("isScreenOn", "()Z", [](Call&) { return Value::Z(true); });
    pm.method("isInteractive", "()Z", [](Call&) { return Value::Z(true); });
    // The device's id, through the content resolver as Android has it.
    jvm::define("android/provider/Settings$Secure").static_method("getString", "(Landroid/content/ContentResolver;Ljava/lang/String;)Ljava/lang/String;", [](Call& c) {
        return c.str(1) == "android_id" ? Value(jvm::string(device_id())) : Value();
    });
    Ref<Object> resolver = jvm::new_object(jvm::define("android/content/ContentResolver"), "()V");
    jvm::define("android/content/ContextWrapper").method("getContentResolver", "()Landroid/content/ContentResolver;", [resolver](Call&) { return Value(resolver); });
}

}  // namespace

// The device's id (Settings.Secure.ANDROID_ID): random once, then kept in the data folder, since the game's platform
// login keys a guest account to it.
std::string device_id() {
    static const std::string id = [] {
        std::string path = app().host_data + "/android_id";
        std::ifstream in(utf8_path(path));
        std::string v;
        if (in >> v && v.size() == 16) return v;
        std::random_device rd;
        char text[17];
        std::snprintf(text, sizeof text, "%08x%08x", rd(), rd());
        std::ofstream(utf8_path(path)) << text << "\n";
        return std::string(text);
    }();
    return id;
}

void define_threads();

void define_android_os() {
    define_threads();
    define_constants();
    define_display();
    define_views();
    define_services();
}

}  // namespace player
