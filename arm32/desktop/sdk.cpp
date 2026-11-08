// The SDKs and plugins the game carries, where doing nothing is not enough:
//   - Firebase: its C++ library hands work to the Java main thread (CppThreadDispatcher, which on a phone it unpacks
//     from its own library and loads) and needs an app with options, which a phone's Firebase made at start-up from the
//     app's resources; here the options come from the configuration file the APK carries among its assets.
//   - SDK singletons C# keeps calling (AppsFlyer's getInstance): an object, so that the calls go on doing nothing,
//     rather than null, which C# scripts dereference.
//   - The video plugin's start (it loads its libraries and hands its native code the asset manager) and the game's
//     asset reader (an asset of the APK as a byte array).
// Everything else of the SDKs is left to the VM's made-up methods, which do nothing.
#include "player.h"

#include <android/asset_manager.h>
#include <android/asset_manager_jni.h>

#include <thread>
#include <vector>

namespace player {

namespace {

using jvm::Call;
using jvm::Class;
using jvm::Object;
using jvm::Ref;
using jvm::Value;

// CppThreadDispatcherContext: a C++ function, its data and its cancel function, run once by execute or cancel.
class DispatchContext : public Object {
public:
    using Object::Object;
    std::mutex lock;
    jlong function = 0, data = 0, cancel = 0;
};

// Runs the context's function (or its cancel function) through the static native nativeFunction, once.
void run_context(DispatchContext& ctx, bool cancel) {
    jlong fn, data;
    {
        std::lock_guard<std::mutex> l(ctx.lock);
        fn = cancel ? ctx.cancel : ctx.function;
        data = ctx.data;
        ctx.function = ctx.cancel = 0;
    }
    if (!fn) return;
    jvm::Env& e = jvm::attach();
    e.call_static(*ctx.cls(), "nativeFunction", "(JJ)V", {Value::J(fn), Value::J(data)});
    if (e.pending) {
        jvm::log("player: a Firebase main-thread call threw %s", e.pending->cls()->name.c_str());
        e.pending = {};
    }
}

void define_firebase() {
    Class& ctx = jvm::define("com/google/firebase/app/internal/cpp/CppThreadDispatcherContext");
    ctx.make = [](Class& k) -> Object* { return new DispatchContext(&k); };
    ctx.native("nativeFunction", "(JJ)V", jvm::kStatic);
    ctx.method("<init>", "(JJJ)V", [](Call& c) {
        auto& d = c.self_as<DispatchContext>();
        std::lock_guard<std::mutex> l(d.lock);
        d.function = c.j(0);
        d.data = c.j(1);
        d.cancel = c.j(2);
        return Value();
    });
    ctx.method("execute", "()V", [](Call& c) {
        run_context(c.self_as<DispatchContext>(), false);
        return Value();
    });
    ctx.method("cancel", "()V", [](Call& c) {
        run_context(c.self_as<DispatchContext>(), true);
        return Value();
    });
    ctx.method("release", "()V", [](Call& c) {
        auto& d = c.self_as<DispatchContext>();
        std::lock_guard<std::mutex> l(d.lock);
        d.function = d.cancel = 0;
        return Value();
    });
    Class& disp = jvm::define("com/google/firebase/app/internal/cpp/CppThreadDispatcher");
    disp.static_method("runOnMainThread", "(Landroid/app/Activity;Lcom/google/firebase/app/internal/cpp/CppThreadDispatcherContext;)V", [](Call& c) {
        Ref<DispatchContext> d(c.as<DispatchContext>(1));
        if (d) main_looper().post([d] { run_context(*d, false); });
        return Value();
    });
    disp.static_method("runOnBackgroundThread", "(Lcom/google/firebase/app/internal/cpp/CppThreadDispatcherContext;)V", [](Call& c) {
        Ref<DispatchContext> d(c.as<DispatchContext>(0));
        if (d) std::thread([d] {
            run_context(*d, false);
            jvm::detach();
        }).detach();
        return Value();
    });
}

// An asset of the APK, whole ("" when it is missing).
std::vector<std::uint8_t> read_asset(const std::string& name, bool* found = nullptr) {
    std::vector<std::uint8_t> out;
    AAsset* a = AAssetManager_open(AAssetManager_fromJava(nullptr, nullptr), name.c_str(), AASSET_MODE_BUFFER);
    if (found) *found = a != nullptr;
    if (!a) return out;
    out.resize(static_cast<std::size_t>(AAsset_getLength64(a)));
    if (!out.empty()) AAsset_read(a, out.data(), out.size());
    AAsset_close(a);
    return out;
}

// The first string value of a key in a JSON text ("" when there is none): enough for the flat configuration file.
std::string json_string(const std::string& json, const std::string& key) {
    std::size_t at = json.find("\"" + key + "\"");
    if (at == std::string::npos) return {};
    at = json.find(':', at + key.size() + 2);
    if (at == std::string::npos) return {};
    at = json.find('"', at);
    if (at == std::string::npos) return {};
    std::size_t end = json.find('"', at + 1);
    return end == std::string::npos ? std::string() : json.substr(at + 1, end - at - 1);
}

// FirebaseOptions: the six values a Firebase app is made with.
class Options : public Object {
public:
    using Object::Object;
    std::string api_key, app_id, database_url, sender_id, storage_bucket, project_id;
};

Class* g_options = nullptr;
Ref<Object> g_firebase_app;

// The options a phone's Firebase reads from the app's resources: here from the APK's own Firebase configuration file.
// Without one, values that say so: Firebase only needs them to be there, and nothing of it reaches a server here.
Ref<Options> options_from_app() {
    Ref<Options> o(new Options(g_options));
    std::vector<std::uint8_t> raw = read_asset("google-services-desktop.json");
    std::string json(raw.begin(), raw.end());
    auto pick = [&json](const char* key) {
        std::string v = json_string(json, key);
        return v.empty() ? std::string("unset") : v;
    };
    o->api_key = pick("current_key");
    o->app_id = pick("mobilesdk_app_id");
    o->database_url = pick("firebase_url");
    o->sender_id = pick("project_number");
    o->storage_bucket = pick("storage_bucket");
    o->project_id = pick("project_id");
    return o;
}

void define_firebase_app() {
    Class& o = jvm::define("com/google/firebase/FirebaseOptions");
    g_options = &o;
    o.make = [](Class& k) -> Object* { return new Options(&k); };
    o.static_method("fromResource", "(Landroid/content/Context;)Lcom/google/firebase/FirebaseOptions;", [](Call&) { return Value(options_from_app()); });
    const std::pair<const char*, std::string Options::*> fields[] = {
        {"ApiKey", &Options::api_key},           {"ApplicationId", &Options::app_id},          {"DatabaseUrl", &Options::database_url},
        {"GcmSenderId", &Options::sender_id},    {"StorageBucket", &Options::storage_bucket}, {"ProjectId", &Options::project_id},
    };
    // getApiKey() and the others; the builder's setApiKey(String) and the others, which return the builder.
    Class& b = jvm::define("com/google/firebase/FirebaseOptions$Builder");
    b.make = [](Class& k) -> Object* { return new Options(&k); };
    for (auto& [name, member] : fields) {
        auto m = member;
        o.method(std::string("get") + name, "()Ljava/lang/String;", [m](Call& c) { return Value(jvm::string(c.self_as<Options>().*m)); });
        b.method(std::string("set") + name, "(Ljava/lang/String;)Lcom/google/firebase/FirebaseOptions$Builder;", [m](Call& c) {
            c.self_as<Options>().*m = c.str(0);
            return Value(c.self);
        });
    }
    b.method("<init>", "()V", [](Call&) { return Value(); });
    b.method("build", "()Lcom/google/firebase/FirebaseOptions;", [](Call& c) {
        Ref<Options> out(new Options(g_options));
        const Options& from = c.self_as<Options>();
        out->api_key = from.api_key;
        out->app_id = from.app_id;
        out->database_url = from.database_url;
        out->sender_id = from.sender_id;
        out->storage_bucket = from.storage_bucket;
        out->project_id = from.project_id;
        return Value(out);
    });
    // The app: the default one exists from the start, as a phone's Firebase makes it before the activity.
    Class& a = jvm::define("com/google/firebase/FirebaseApp");
    a.field("options", "Lcom/google/firebase/FirebaseOptions;");
    g_firebase_app = jvm::new_object(a, "()V");
    g_firebase_app->set_field(a.find_field("options", false), Value(options_from_app()));
    a.static_method("getInstance", "()Lcom/google/firebase/FirebaseApp;", [](Call&) { return Value(g_firebase_app); });
    a.static_method("getInstance", "(Ljava/lang/String;)Lcom/google/firebase/FirebaseApp;", [](Call&) { return Value(g_firebase_app); });
    auto init = [&a](Call& c, Object* options) {
        Ref<Object> app = jvm::new_object(a, "()V");
        app->set_field(a.find_field("options", false), Value(options ? Ref<Object>(options) : Ref<Object>(options_from_app())));
        return Value(app);
    };
    a.static_method("initializeApp", "(Landroid/content/Context;)Lcom/google/firebase/FirebaseApp;", [init](Call& c) { return init(c, nullptr); });
    a.static_method("initializeApp", "(Landroid/content/Context;Lcom/google/firebase/FirebaseOptions;)Lcom/google/firebase/FirebaseApp;", [init](Call& c) { return init(c, c.l(1)); });
    a.static_method("initializeApp", "(Landroid/content/Context;Lcom/google/firebase/FirebaseOptions;Ljava/lang/String;)Lcom/google/firebase/FirebaseApp;", [init](Call& c) { return init(c, c.l(1)); });
    a.method("getOptions", "()Lcom/google/firebase/FirebaseOptions;", [&a](Call& c) { return c.self->field(a.find_field("options", false)); });
    a.method("getName", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string("[DEFAULT]")); });
    a.method("isDataCollectionDefaultEnabled", "()Z", [](Call&) { return Value::Z(false); });
    // Google Play services are there, as on the phones the game was made for (0 is ConnectionResult.SUCCESS).
    Class& g = jvm::define("com/google/android/gms/common/GoogleApiAvailability");
    Ref<Object> availability = jvm::new_object(g, "()V");
    g.static_method("getInstance", "()Lcom/google/android/gms/common/GoogleApiAvailability;", [availability](Call&) { return Value(availability); });
    g.method("isGooglePlayServicesAvailable", "(Landroid/content/Context;)I", [](Call&) { return Value::I(0); });
}

// A class with a static method returning one object of it, for SDKs whose singletons C# calls on.
void singleton(const char* cls, const char* method, std::initializer_list<const char*> classes_it_is = {}) {
    Class& c = jvm::define(cls);
    for (const char* i : classes_it_is) c.interfaces.push_back(&jvm::define_interface(i));
    Ref<Object> one = jvm::new_object(c, "()V");
    c.static_method(method, std::string("()L") + cls + ";", [one](Call&) { return Value(one); });
}

void define_singletons() {
    singleton("com/appsflyer/AppsFlyerLib", "getInstance");
    singleton("com/appsflyer/AppsFlyerProperties", "getInstance");
    singleton("com/google/firebase/analytics/FirebaseAnalytics", "getInstance");
    singleton("com/google/firebase/messaging/FirebaseMessaging", "getInstance");
    // FirebaseAnalytics.getInstance takes the context.
    Class& fa = *jvm::find_class("com/google/firebase/analytics/FirebaseAnalytics");
    Ref<Object> analytics = jvm::new_object(fa, "()V");
    fa.static_method("getInstance", "(Landroid/content/Context;)Lcom/google/firebase/analytics/FirebaseAnalytics;", [analytics](Call&) { return Value(analytics); });
    // HockeyApp's crash reporter asks the app what it is; strings, not nulls, for the C# that formats them.
    Class& h = jvm::define("net/hockeyapp/unity/HockeyUnityPlugin");
    h.static_method("getVersionCode", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string(std::to_string(app().version_code))); });
    h.static_method("getVersionName", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string(app().version_name)); });
    h.static_method("getManufacturer", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string("OpenDMTQ")); });
    h.static_method("getModel", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string("OpenDMTQ")); });
    h.static_method("getCrashReporterKey", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string("")); });
    h.static_method("getSdkName", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string("")); });
    h.static_method("getSdkVersion", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string("")); });
    // The game's own SDK: its clipboard is empty for now.
    jvm::define("com/neowiz/externalsdkgbl/ExternalSDK").static_method("GetClipboard", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string("")); });
}

void define_plugins() {
    // The video plugin: its class's static initializer loads its libraries; loadAssetManager hands the asset manager on.
    Class& env = jvm::define("com/gpuv/env");
    env.native("onLoadAssetManager", "(Landroid/content/res/AssetManager;)V", jvm::kStatic);
    env.native("onUnloadAssetManager", "()V", jvm::kStatic);
    env.static_method("loadAssetManager", "(Landroid/content/res/AssetManager;)V", [](Call& c) {
        for (const char* lib : {"libvpx.so", "libgpuv2.so"}) {
            if (!load_library(app().lib_dir + "/" + lib)) jvm::throw_new("java/lang/UnsatisfiedLinkError", lib);
        }
        c.env.call_static(*jvm::find_class("com/gpuv/env"), "onLoadAssetManager", "(Landroid/content/res/AssetManager;)V", {Value(c.l(0))});
        return Value();
    });
    // The game's asset reader: an asset of the APK whole, or null.
    Class& acc = jvm::define("com/neowizgames/plugins/androidassetaccessor/AndroidAssetAccessor");
    acc.static_method("ReadAssetFromJar", "(Ljava/lang/String;)[B", [](Call& c) {
        bool found = false;
        std::vector<std::uint8_t> data = read_asset(c.str(0), &found);
        if (!found) return Value();
        Ref<jvm::Array> a = jvm::new_array(jvm::array_class(jvm::primitive_class('B')), static_cast<jsize>(data.size()));
        std::copy(data.begin(), data.end(), a->bytes.begin());
        return Value(a);
    });
    acc.static_method("CheckFileExistsJar", "(Ljava/lang/String;)Z", [](Call& c) {
        AAsset* a = AAssetManager_open(AAssetManager_fromJava(nullptr, nullptr), c.str(0).c_str(), AASSET_MODE_UNKNOWN);
        if (a) AAsset_close(a);
        return Value::Z(a != nullptr);
    });
}

}  // namespace

void define_sdks() {
    define_firebase();
    define_firebase_app();
    define_singletons();
    define_plugins();
}

}  // namespace player
