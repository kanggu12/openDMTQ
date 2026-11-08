// The Unity player's Java classes as the game's native code meets them: the natives its libraries register, declared
// with their signatures (so that calls from C++ pass the class to static ones and the object to the others, as the
// phone's VM does), the player view's methods native code calls, and the two ways C# scripts and Java reach each
// other: reflection through ReflectionHelper, and proxies (JNIBridge, ReflectionHelper.newProxyInstance) whose calls
// go back into C#. The rules follow Unity 5.6's own Java, which does not run here.
#include "player.h"

#include <atomic>
#include <map>
#include <mutex>
#include <unistd.h>

namespace player {

namespace {

using jvm::Call;
using jvm::Class;
using jvm::Method;
using jvm::Object;
using jvm::Ref;
using jvm::Value;

// ---------------------------------------------------------------------------------------------------------------------
// ReflectionHelper's lookups, scored as Unity scores them: C# asks with a signature it built from its own argument types
// (a null argument gives Object), and the best match among the methods of that name wins.

// How well a declared type serves for a wanted one: the same type 1, a subclass 0.5, a superclass 0.1, else 0.
float type_score(Class* declared, Class* wanted) {
    if (declared == wanted) return 1.0f;
    if (!declared || !wanted || declared->primitive || wanted->primitive) return 0.0f;
    if (declared->is(wanted)) return 0.5f;
    if (wanted->is(declared)) return 0.1f;
    return 0.0f;
}

// The types a signature names in order, the return type last ("(ILjava/lang/String;)V" gives int, String, void).
std::vector<Class*> signature_types(const std::string& sig) {
    std::vector<Class*> out;
    for (std::size_t i = 0; i < sig.size();) {
        if (sig[i] == '(' || sig[i] == ')') {
            ++i;
            continue;
        }
        std::size_t n = jvm::descriptor_length(std::string_view(sig).substr(i));
        // Unity's parser stops at the first type it cannot read.
        if (!n) break;
        Class* c = jvm::class_of_descriptor(std::string_view(sig).substr(i, n));
        if (!c) break;
        out.push_back(c);
        i += n;
    }
    return out;
}

// A method's score for the wanted types: 0.1 for no signature at all, 0 for another parameter count, else the product
// of each parameter's score and the return type's.
float method_score(const Method& m, const std::vector<Class*>& wanted) {
    if (wanted.empty()) return 0.1f;
    if (m.param_types.size() + 1 != wanted.size()) return 0.0f;
    float f = 1.0f;
    for (std::size_t k = 0; k < m.param_types.size(); ++k) f *= type_score(jvm::class_of_descriptor(m.param_types[k]), wanted[k]);
    Class* ret = m.name == "<init>" ? &jvm::primitive_class('V') : jvm::class_of_descriptor(m.ret_type);
    return f * type_score(ret, wanted.back());
}

// getMethodID and getConstructorID: the best method of that name (and static or not) in the class, then up its
// superclasses until a perfect match. Where the C++ library has none, the method is made up with the signature asked
// for: on the phone the app's own class had it, and calling it here does nothing, logged.
Method* unity_method(Class& cls, const std::string& name, const std::string& sig, bool is_static) {
    std::vector<Class*> wanted = signature_types(sig);
    Method* best = nullptr;
    float best_score = 0.0f;
    for (Class* k = &cls; k; k = k->super) {
        std::vector<Method*> methods = name == "<init>" ? k->all_methods() : k->declared_methods();
        for (Method* m : methods) {
            if (m->name != name || m->is_static() != is_static) continue;
            float f = method_score(*m, wanted);
            if (f > best_score) {
                best = m;
                best_score = f;
                if (f == 1.0f) break;
            }
        }
        // Constructors are the class's own; interfaces and Object end the search, as in Unity's loop.
        if (name == "<init>" || best_score == 1.0f || k->is_interface() || k->primitive || k->name == "java/lang/Object") break;
    }
    if (best) return best;
    return &cls.method_or_made_up(name, sig.empty() ? "()V" : sig, is_static);
}

jvm::Field* unity_field(Class& cls, const std::string& name, const std::string& sig, bool is_static) {
    std::vector<Class*> wanted = signature_types(sig);
    for (Class* k = &cls; k; k = k->super) {
        for (jvm::Field* f : k->declared_fields()) {
            if (f->name == name && f->is_static == is_static) return f;
        }
        if (k->is_interface() || k->name == "java/lang/Object") break;
    }
    return &cls.field_or_made_up(name, sig, is_static);
}

// A reflection object for a method (Constructor for <init>), as the phone's reflection returns.
Ref<Object> member(Method* m) {
    Class* kind = jvm::find_class(m->name == "<init>" ? "java/lang/reflect/Constructor" : "java/lang/reflect/Method");
    return Ref<Object>(new jvm::Member(kind, m, nullptr));
}

// ---------------------------------------------------------------------------------------------------------------------
// Proxies: an object of the interfaces asked for whose every call goes to a native method that hands it to C#.

// A proxy class per list of interfaces, as java.lang.reflect.Proxy keeps one.
Class& proxy_class(const std::vector<Class*>& interfaces) {
    static std::mutex lock;
    static std::map<std::string, Class*> classes;
    std::string key;
    for (Class* i : interfaces) key += (key.empty() ? "" : ",") + i->name;
    std::lock_guard<std::mutex> l(lock);
    Class*& c = classes[key];
    if (!c) {
        // Named as Android names them: $Proxy0, $Proxy1, ...
        static int next = 0;
        c = &jvm::define("$Proxy" + std::to_string(next++), "java/lang/reflect/Proxy");
        c->interfaces = interfaces;
        c->proxy = true;
        c->modifiers = jvm::kPublic | jvm::kFinal;
    }
    return *c;
}

// The interfaces in a Class[] argument.
std::vector<Class*> classes_in(jvm::Array* a) {
    std::vector<Class*> out;
    if (!a) return out;
    for (auto& item : a->items) {
        if (auto* c = dynamic_cast<Class*>(item.get())) out.push_back(c);
    }
    return out;
}

// A call's arguments as the Object[] a proxy hands on: primitives boxed. Null when the method has none, as Java passes.
Ref<jvm::Array> boxed_args(Call& c) {
    if (c.method.params.empty()) return {};
    Ref<jvm::Array> a = jvm::new_array(jvm::array_class(*jvm::find_class("java/lang/Object")), static_cast<jsize>(c.method.params.size()));
    for (std::size_t k = 0; k < c.method.params.size() && k < c.argc; ++k) {
        char t = c.method.params[k];
        a->items[k] = t == 'L' || t == '[' ? Ref<Object>(c.args[k].l()) : jvm::box(t, c.args[k]);
    }
    return a;
}

// What a proxy's handler returned, as the interface method's type: a box gives back its value.
Value unboxed(const Method& m, const Value& v) {
    if (m.ret == 'V') return Value();
    if (m.ret == 'L' || m.ret == '[') return v;
    auto* b = dynamic_cast<jvm::Boxed*>(v.l());
    return b ? b->value : Value();
}

// JNIBridge's proxies (C#'s AndroidJavaProxy): each call goes to JNIBridge.invoke(ptr, the method's interface, the
// method, the arguments) until disableInterfaceProxy clears ptr.
class BridgeProxy : public jvm::Proxy {
public:
    BridgeProxy(Class* cls, jlong ptr) : Proxy(cls), ptr(ptr) {}
    std::atomic<jlong> ptr;
};

void define_bridges() {
    Class& bridge = jvm::define("bitter/jnibridge/JNIBridge");
    bridge.static_method("newInterfaceProxy", "(J[Ljava/lang/Class;)Ljava/lang/Object;", [](Call& c) {
        Ref<BridgeProxy> p(new BridgeProxy(&proxy_class(classes_in(c.as<jvm::Array>(1))), c.j(0)));
        BridgeProxy* self = p.get();
        p->invoke = [self](Call& call) -> Value {
            jlong ptr = self->ptr.load();
            if (!ptr) return Value();
            Class& b = *jvm::find_class("bitter/jnibridge/JNIBridge");
            Value r = call.env.call_static(b, "invoke", "(JLjava/lang/Class;Ljava/lang/reflect/Method;[Ljava/lang/Object;)Ljava/lang/Object;",
                                           {Value::J(ptr), Value(call.method.owner), Value(member(&call.method)), Value(boxed_args(call))});
            return unboxed(call.method, r);
        };
        return Value(p);
    });
    bridge.static_method("disableInterfaceProxy", "(Ljava/lang/Object;)V", [](Call& c) {
        if (auto* p = c.as<BridgeProxy>(0)) p->ptr = 0;
        return Value();
    });
    Class& helper = jvm::define("com/unity3d/player/ReflectionHelper");
    helper.static_method("getMethodID", "(Ljava/lang/Class;Ljava/lang/String;Ljava/lang/String;Z)Ljava/lang/reflect/Method;", [](Call& c) {
        auto* cls = c.as<Class>(0);
        if (!cls) jvm::throw_new("java/lang/NullPointerException", "getMethodID on null");
        return Value(member(unity_method(*cls, c.str(1), c.str(2), c.z(3))));
    });
    helper.static_method("getConstructorID", "(Ljava/lang/Class;Ljava/lang/String;)Ljava/lang/reflect/Constructor;", [](Call& c) {
        auto* cls = c.as<Class>(0);
        if (!cls) jvm::throw_new("java/lang/NullPointerException", "getConstructorID on null");
        return Value(member(unity_method(*cls, "<init>", c.str(1), false)));
    });
    helper.static_method("getFieldID", "(Ljava/lang/Class;Ljava/lang/String;Ljava/lang/String;Z)Ljava/lang/reflect/Field;", [](Call& c) {
        auto* cls = c.as<Class>(0);
        if (!cls) jvm::throw_new("java/lang/NullPointerException", "getFieldID on null");
        jvm::Field* f = unity_field(*cls, c.str(1), c.str(2), c.z(3));
        return Value(Ref<Object>(new jvm::Member(jvm::find_class("java/lang/reflect/Field"), nullptr, f)));
    });
    // newProxyInstance's proxies (C# delegates as Java interfaces): each call goes to nativeProxyInvoke(id, the method's
    // name, the arguments).
    auto proxy = [](Call& c, std::vector<Class*> interfaces) {
        jint id = c.i(0);
        Ref<jvm::Proxy> p(new jvm::Proxy(&proxy_class(interfaces)));
        p->invoke = [id](Call& call) -> Value {
            Class& h = *jvm::find_class("com/unity3d/player/ReflectionHelper");
            Value r = call.env.call_static(h, "nativeProxyInvoke", "(ILjava/lang/String;[Ljava/lang/Object;)Ljava/lang/Object;",
                                           {Value::I(id), Value(jvm::string(call.method.name)), Value(boxed_args(call))});
            return unboxed(call.method, r);
        };
        return Value(p);
    };
    helper.static_method("newProxyInstance", "(ILjava/lang/Class;)Ljava/lang/Object;", [proxy](Call& c) {
        auto* cls = c.as<Class>(1);
        return proxy(c, cls ? std::vector<Class*>{cls} : std::vector<Class*>{});
    });
    helper.static_method("newProxyInstance", "(I[Ljava/lang/Class;)Ljava/lang/Object;", [proxy](Call& c) { return proxy(c, classes_in(c.as<jvm::Array>(1))); });
}

// ---------------------------------------------------------------------------------------------------------------------
// Loading the game's other libraries: System.load and loadLibrary, the player's loadLibrary, and the class loader's
// findLibrary, which Unity asks where a plugin library is.

std::string library_path(const std::string& name) { return app().lib_dir + "/lib" + name + ".so"; }

void define_loading() {
    Class& system = jvm::define("java/lang/System");
    system.static_method("load", "(Ljava/lang/String;)V", [](Call& c) {
        if (!load_library(c.str(0))) jvm::throw_new("java/lang/UnsatisfiedLinkError", "cannot load " + c.str(0));
        return Value();
    });
    system.static_method("loadLibrary", "(Ljava/lang/String;)V", [](Call& c) {
        if (!load_library(library_path(c.str(0)))) jvm::throw_new("java/lang/UnsatisfiedLinkError", "cannot load lib" + c.str(0) + ".so");
        return Value();
    });
    Class& loader = jvm::define("java/lang/ClassLoader");
    loader.method("findLibrary", "(Ljava/lang/String;)Ljava/lang/String;", [](Call& c) {
        std::string path = library_path(c.str(0));
        return access(host_of(path).c_str(), F_OK) == 0 ? Value(jvm::string(path)) : Value();
    });
    loader.method("findLoadedClass", "(Ljava/lang/String;)Ljava/lang/Class;", [](Call& c) { return Value(jvm::find_class(c.str(0))); });
    jvm::define("dalvik/system/DexClassLoader", "dalvik/system/BaseDexClassLoader");
}

}  // namespace

void send_to_unity(const std::string& object, const std::string& method, const std::string& message) {
    jvm::Env& e = jvm::attach();
    e.call_static(*jvm::find_class("com/unity3d/player/UnityPlayer"), "nativeUnitySendMessage", "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V",
                  {Value(jvm::string(object)), Value(jvm::string(method)), Value(jvm::string(message))});
    if (e.pending) {
        jvm::log("player: UnitySendMessage to %s.%s threw %s", object.c_str(), method.c_str(), e.pending->cls()->name.c_str());
        e.pending = {};
    }
}

void define_unity() {
    define_bridges();
    define_loading();
    // libmain registers these in its JNI_OnLoad; load(dir) then loads libunity from dir and runs its JNI_OnLoad.
    jvm::define("com/unity3d/player/NativeLoader")
        .native("load", "(Ljava/lang/String;)Z", jvm::kStatic)
        .native("unload", "()Z", jvm::kStatic);
    // The player's natives, which libunity registers: its life cycle, input, frames and messages to C# scripts.
    jvm::define("com/unity3d/player/UnityPlayer", "android/widget/FrameLayout")
        .native("initJni", "(Landroid/content/Context;)V")
        .native("isQuiting", "()Z")
        .native("nativeActivityIndicatorStyle", "()I")
        .native("nativeDone", "()V")
        .native("nativeFile", "(Ljava/lang/String;)V")
        .native("nativeFocusChanged", "(Z)V")
        .native("nativeInitWWW", "(Ljava/lang/Class;)V")
        .native("nativeInitWebRequest", "(Ljava/lang/Class;)V")
        .native("nativeInjectEvent", "(Landroid/view/InputEvent;)Z")
        .native("nativeLowMemory", "()V")
        .native("nativeMuteMasterAudio", "(Z)V")
        .native("nativePause", "()Z")
        .native("nativeRecreateGfxState", "(ILandroid/view/Surface;)V")
        .native("nativeRender", "()Z")
        .native("nativeResume", "()V")
        .native("nativeSetInputCanceled", "(Z)V")
        .native("nativeSetInputString", "(Ljava/lang/String;)V")
        .native("nativeSoftInputClosed", "()V")
        .native("nativeUnitySendMessage", "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V", jvm::kStatic)
        // Java plugins message C# scripts through this (native code may call it too).
        .static_method("UnitySendMessage", "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V",
                       [](Call& c) {
                           send_to_unity(c.str(0), c.str(1), c.str(2));
                           return Value();
                       })
        // Native code loads plugin libraries through the player (System.loadLibrary underneath).
        .method("loadLibrary", "(Ljava/lang/String;)Z", [](Call& c) { return Value::Z(load_library(library_path(c.str(0)))); })
        // The loading spinner: Unity draws its own loading screens; the phone's spinner view has no desktop counterpart.
        .method("startActivityIndicator", "()V", [](Call&) { return Value(); })
        .method("stopActivityIndicator", "()V", [](Call&) { return Value(); });
    // The game's own player class (the web view plugin's), which the activity makes.
    jvm::define("net/gree/unitywebview/CUnityPlayer", "com/unity3d/player/UnityPlayer");
    // C# scripts reach Java by reflection through ReflectionHelper, and Java reaches C# proxies through it and JNIBridge.
    jvm::define("com/unity3d/player/ReflectionHelper")
        .native("nativeProxyInvoke", "(ILjava/lang/String;[Ljava/lang/Object;)Ljava/lang/Object;", jvm::kStatic)
        .native("nativeProxyFinalize", "(I)V", jvm::kStatic);
    jvm::define("bitter/jnibridge/JNIBridge")
        .native("invoke", "(JLjava/lang/Class;Ljava/lang/reflect/Method;[Ljava/lang/Object;)Ljava/lang/Object;", jvm::kStatic)
        .native("delete", "(J)V", jvm::kStatic);
    // HTTP: the Java side of WWW and UnityWebRequest hands what it reads back through these.
    jvm::define("com/unity3d/player/WWW", "java/lang/Thread")
        .native("doneCallback", "(I)V", jvm::kStatic)
        .native("errorCallback", "(ILjava/lang/String;)V", jvm::kStatic)
        .native("headerCallback", "(ILjava/lang/String;)Z", jvm::kStatic)
        .native("progressCallback", "(IFFDI)V", jvm::kStatic)
        .native("readCallback", "(I[BI)Z", jvm::kStatic);
    jvm::define("com/unity3d/player/UnityWebRequest")
        .native("contentLengthCallback", "(JI)V", jvm::kStatic)
        .native("downloadCallback", "(JLjava/nio/ByteBuffer;I)Z", jvm::kStatic)
        .native("errorCallback", "(JILjava/lang/String;)V", jvm::kStatic)
        .native("headerCallback", "(JLjava/lang/String;Ljava/lang/String;)V", jvm::kStatic)
        .native("responseCodeCallback", "(JI)V", jvm::kStatic)
        .native("uploadCallback", "(JLjava/nio/ByteBuffer;)I", jvm::kStatic);
    // FMOD's Java output thread asks the mixer for each buffer through these.
    jvm::define("org/fmod/FMODAudioDevice")
        .native("fmodGetInfo", "(I)I")
        .native("fmodProcess", "(Ljava/nio/ByteBuffer;)I")
        .native("fmodProcessMicData", "(Ljava/nio/ByteBuffer;I)I");
}

}  // namespace player
