// Tests of the VM through JNI, as native code uses it: strings, classes and dispatch, made-up classes and methods,
// fields, arrays, references and their counts, exceptions, native methods called through the platform's calling
// convention (registers and stack), reflection, threads, proxies and boxes. Prints ALL CHECKS PASSED when every check
// held, as the runtime's guest tests do.
#include "jvm.h"

#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>

namespace {

int g_failed = 0;
// Checks run, printed at the end: a count that drops means checks stopped running, which no failure would show.
int g_checks = 0;

// One check: its line and what it says, printed when it fails.
#define CHECK(cond)                                                                                                    \
    do {                                                                                                               \
        ++g_checks;                                                                                                    \
        if (!(cond)) {                                                                                                 \
            std::printf("FAILED line %d: %s\n", __LINE__, #cond);                                                      \
            ++g_failed;                                                                                                \
        }                                                                                                              \
    } while (0)

// A string's text through JNI, released again.
std::string text(JNIEnv* e, jstring s) {
    if (!s) return "(null)";
    const char* chars = e->GetStringUTFChars(s, nullptr);
    std::string out = chars;
    e->ReleaseStringUTFChars(s, chars);
    return out;
}

// Objects of a C++ class that count their destruction: references must free them, and only when the last one goes.
std::atomic<int> g_freed{0};
class Counted : public jvm::Object {
public:
    using Object::Object;
    ~Counted() override { ++g_freed; }
};

// Native methods as the game's code would register them, with arguments in registers and on the stack.
jint JNICALL native_mix(JNIEnv* e, jclass, jint a, jlong b, jfloat c, jdouble d, jboolean z, jbyte by, jchar ch, jshort sh, jstring s,
                        jint i6, jint i7, jint i8, jfloat f2, jfloat f3, jfloat f4, jfloat f5, jfloat f6, jfloat f7, jfloat f8, jdouble d9) {
    // Every argument in the sum, weighted, so that a swapped or lost one changes it.
    double sum = a + static_cast<double>(b) * 2 + c * 3 + d * 4 + z * 5 + by * 6 + ch * 7 + sh * 8 + static_cast<double>(text(e, s).size()) * 9 +
                 i6 * 10 + i7 * 11 + i8 * 12 + f2 * 13 + f3 * 14 + f4 * 15 + f5 * 16 + f6 * 17 + f7 * 18 + f8 * 19 + d9 * 20;
    return static_cast<jint>(std::lround(sum));
}
jfloat JNICALL native_float(JNIEnv*, jobject, jfloat x) { return x * 2; }
jdouble JNICALL native_double(JNIEnv*, jobject, jdouble x) { return x / 4; }
jlong JNICALL native_long(JNIEnv*, jobject, jlong x) { return x + 0x100000000LL; }
jboolean JNICALL native_bool(JNIEnv*, jobject, jint x) { return x > 0 ? JNI_TRUE : JNI_FALSE; }
jstring JNICALL native_string(JNIEnv* e, jobject self, jstring s) {
    // A local reference made inside the native call: the VM keeps the result alive past the call's frame.
    std::string t = text(e, s) + "!";
    return e->NewStringUTF(t.c_str());
}
jint JNICALL native_this(JNIEnv* e, jobject self) {
    // The object the method was called on: its class's field.
    jclass c = e->GetObjectClass(self);
    jfieldID f = e->GetFieldID(c, "count", "I");
    return e->GetIntField(self, f);
}

void strings(JNIEnv* e) {
    // Plain text and characters past ASCII.
    jstring s = e->NewStringUTF("h\xc3\xa9llo \xe2\x82\xac");
    CHECK(e->GetStringLength(s) == 7);
    CHECK(text(e, s) == "h\xc3\xa9llo \xe2\x82\xac");
    // U+0000 is two bytes in modified UTF-8.
    jchar zero[] = {'a', 0, 'b'};
    jstring z = e->NewString(zero, 3);
    CHECK(e->GetStringUTFLength(z) == 4);
    const char* zc = e->GetStringUTFChars(z, nullptr);
    CHECK(std::memcmp(zc, "a\xc0\x80" "b", 4) == 0);
    e->ReleaseStringUTFChars(z, zc);
    // A character past U+FFFF: two UTF-16 units, two three-byte surrogates in modified UTF-8, four bytes in UTF-8.
    jvm::Ref<jvm::String> emoji = jvm::string("\xf0\x9f\x98\x80");
    CHECK(emoji->chars.size() == 2);
    CHECK(emoji->mutf8().size() == 6);
    CHECK(emoji->utf8() == "\xf0\x9f\x98\x80");
    // GetStringRegion and GetStringUTFRegion.
    jchar region[3] = {};
    e->GetStringRegion(s, 1, 3, region);
    CHECK(region[0] == 0xe9 && region[1] == 'l' && region[2] == 'l');
    char utf[8] = {};
    e->GetStringUTFRegion(s, 0, 2, utf);
    CHECK(std::strcmp(utf, "h\xc3\xa9") == 0);
    const jchar* chars = e->GetStringChars(s, nullptr);
    CHECK(chars[6] == 0x20ac);
    e->ReleaseStringChars(s, chars);
    // String's own methods, through JNI as C# reaches them.
    jclass string_class = e->FindClass("java/lang/String");
    jmethodID length = e->GetMethodID(string_class, "length", "()I");
    CHECK(e->CallIntMethod(s, length) == 7);
    jmethodID hash = e->GetMethodID(string_class, "hashCode", "()I");
    jstring abc = e->NewStringUTF("abc");
    // "abc".hashCode() is 96354 in Java.
    CHECK(e->CallIntMethod(abc, hash) == 96354);
}

void classes(JNIEnv* e) {
    // A class and a subclass that overrides one method; the base's other method is inherited.
    jvm::Class& base = jvm::define("test/Base");
    base.method("<init>", "()V", [](jvm::Call&) { return jvm::Value(); });
    base.method("which", "()I", [](jvm::Call&) { return jvm::Value::I(1); });
    base.method("shared", "(I)I", [](jvm::Call& c) { return jvm::Value::I(c.i(0) * 10); });
    jvm::Class& sub = jvm::define("test/Sub", "test/Base");
    sub.method("<init>", "()V", [](jvm::Call&) { return jvm::Value(); });
    sub.method("which", "()I", [](jvm::Call&) { return jvm::Value::I(2); });
    jclass b = e->FindClass("test/Base");
    jclass s = e->FindClass("test/Sub");
    CHECK(b && s);
    CHECK(e->IsAssignableFrom(s, b) && !e->IsAssignableFrom(b, s));
    jobject obj = e->NewObject(s, e->GetMethodID(s, "<init>", "()V"));
    CHECK(e->IsInstanceOf(obj, b) && e->IsInstanceOf(obj, s));
    // The base's method ID dispatches to the subclass's body; the nonvirtual call takes the base's.
    jmethodID which = e->GetMethodID(b, "which", "()I");
    CHECK(e->CallIntMethod(obj, which) == 2);
    CHECK(e->CallNonvirtualIntMethod(obj, b, which) == 1);
    // A method only the base has, found through the subclass.
    jmethodID shared = e->GetMethodID(s, "shared", "(I)I");
    CHECK(e->CallIntMethod(obj, shared, 4) == 40);
    jvalue arg;
    arg.i = 5;
    CHECK(e->CallIntMethodA(obj, shared, &arg) == 50);
    // getName through reflection on the Class object.
    jclass class_class = e->FindClass("java/lang/Class");
    jmethodID get_name = e->GetMethodID(class_class, "getName", "()Ljava/lang/String;");
    CHECK(text(e, static_cast<jstring>(e->CallObjectMethod(s, get_name))) == "test.Sub");
    // getSuperclass, GetObjectClass.
    CHECK(e->IsSameObject(e->GetSuperclass(s), b));
    CHECK(e->IsSameObject(e->GetObjectClass(obj), s));
    // Arrays of a class, and their names.
    jclass arr = e->FindClass("[Ljava/lang/String;");
    CHECK(text(e, static_cast<jstring>(e->CallObjectMethod(arr, get_name))) == "[Ljava.lang.String;");
}

void made_up(JNIEnv* e) {
    // A class nothing defined, as an SDK the game carries: found, its methods do nothing.
    jclass c = e->FindClass("com/example/sdk/Tracker");
    CHECK(c && !e->ExceptionCheck());
    jmethodID start = e->GetStaticMethodID(c, "start", "(Ljava/lang/String;)Z");
    CHECK(start != nullptr);
    CHECK(e->CallStaticBooleanMethod(c, start, e->NewStringUTF("id")) == JNI_FALSE);
    // An object, an empty array and a null string: what lets the caller go on (see jvm.h).
    jmethodID get = e->GetStaticMethodID(c, "get", "()Ljava/lang/Object;");
    jobject got = e->CallStaticObjectMethod(c, get);
    CHECK(got != nullptr && e->IsInstanceOf(got, e->FindClass("java/lang/Object")));
    jmethodID list = e->GetStaticMethodID(c, "list", "()[I");
    auto ints = static_cast<jintArray>(e->CallStaticObjectMethod(c, list));
    CHECK(ints && e->GetArrayLength(ints) == 0);
    jmethodID name = e->GetStaticMethodID(c, "name", "()Ljava/lang/String;");
    CHECK(e->CallStaticObjectMethod(c, name) == nullptr);
    // A singleton's getInstance gives the same object each time.
    jmethodID instance = e->GetStaticMethodID(c, "getInstance", "()Lcom/example/sdk/Tracker;");
    jobject one = e->CallStaticObjectMethod(c, instance);
    CHECK(one && e->IsSameObject(one, e->CallStaticObjectMethod(c, instance)) && e->IsInstanceOf(one, c));
    // A name marked absent fails as on a phone without it.
    jvm::mark_absent("com/example/sdk/Missing");
    CHECK(e->FindClass("com/example/sdk/Missing") == nullptr);
    CHECK(e->ExceptionCheck());
    jthrowable t = e->ExceptionOccurred();
    e->ExceptionClear();
    CHECK(!e->ExceptionCheck());
    CHECK(e->IsInstanceOf(t, e->FindClass("java/lang/NoClassDefFoundError")));
    CHECK(e->IsInstanceOf(t, e->FindClass("java/lang/Throwable")));
}

void fields(JNIEnv* e) {
    jvm::define("test/Fields").field("count", "I").static_field("shared", "Ljava/lang/String;", jvm::Value(jvm::string("first")));
    jclass c = e->FindClass("test/Fields");
    jobject o = e->AllocObject(c);
    jfieldID count = e->GetFieldID(c, "count", "I");
    CHECK(e->GetIntField(o, count) == 0);
    e->SetIntField(o, count, 42);
    CHECK(e->GetIntField(o, count) == 42);
    jfieldID shared = e->GetStaticFieldID(c, "shared", "Ljava/lang/String;");
    CHECK(text(e, static_cast<jstring>(e->GetStaticObjectField(c, shared))) == "first");
    e->SetStaticObjectField(c, shared, e->NewStringUTF("second"));
    CHECK(text(e, static_cast<jstring>(e->GetStaticObjectField(c, shared))) == "second");
    // A field nothing declared reads as zero and keeps what is stored.
    jfieldID other = e->GetFieldID(c, "other", "J");
    CHECK(e->GetLongField(o, other) == 0);
    e->SetLongField(o, other, 1LL << 40);
    CHECK(e->GetLongField(o, other) == (1LL << 40));
    jfieldID d = e->GetFieldID(c, "ratio", "D");
    e->SetDoubleField(o, d, 0.25);
    CHECK(e->GetDoubleField(o, d) == 0.25);
}

void arrays(JNIEnv* e) {
    jintArray a = e->NewIntArray(4);
    CHECK(e->GetArrayLength(a) == 4);
    jint in[] = {1, 2, 3, 4};
    e->SetIntArrayRegion(a, 0, 4, in);
    jint* elems = e->GetIntArrayElements(a, nullptr);
    CHECK(elems[3] == 4);
    elems[0] = 9;
    e->ReleaseIntArrayElements(a, elems, 0);
    jint out[2];
    e->GetIntArrayRegion(a, 0, 2, out);
    CHECK(out[0] == 9 && out[1] == 2);
    // Out of bounds: an exception, and nothing copied.
    e->GetIntArrayRegion(a, 3, 2, out);
    CHECK(e->ExceptionCheck());
    e->ExceptionClear();
    // Byte arrays through the critical form.
    jbyteArray bytes = e->NewByteArray(3);
    auto* p = static_cast<jbyte*>(e->GetPrimitiveArrayCritical(bytes, nullptr));
    p[2] = 7;
    e->ReleasePrimitiveArrayCritical(bytes, p, 0);
    jbyte got = 0;
    e->GetByteArrayRegion(bytes, 2, 1, &got);
    CHECK(got == 7);
    // Object arrays.
    jclass string_class = e->FindClass("java/lang/String");
    jobjectArray strings = e->NewObjectArray(2, string_class, e->NewStringUTF("x"));
    CHECK(text(e, static_cast<jstring>(e->GetObjectArrayElement(strings, 1))) == "x");
    e->SetObjectArrayElement(strings, 0, e->NewStringUTF("y"));
    CHECK(text(e, static_cast<jstring>(e->GetObjectArrayElement(strings, 0))) == "y");
    CHECK(e->GetObjectArrayElement(strings, 2) == nullptr && e->ExceptionCheck());
    e->ExceptionClear();
    // Doubles and longs keep their bits.
    jdoubleArray ds = e->NewDoubleArray(1);
    jdouble dv = -1.5;
    e->SetDoubleArrayRegion(ds, 0, 1, &dv);
    jdouble* dp = e->GetDoubleArrayElements(ds, nullptr);
    CHECK(dp[0] == -1.5);
    e->ReleaseDoubleArrayElements(ds, dp, JNI_ABORT);
}

void references(JNIEnv* e) {
    jvm::Class& counted = jvm::define("test/Counted");
    counted.make = [](jvm::Class& k) -> jvm::Object* { return new Counted(&k); };
    jclass c = e->FindClass("test/Counted");
    jvm::Env& env = *jvm::Env::from(e);
    // An object only a local reference holds goes when its frame closes.
    int freed = g_freed;
    std::size_t before = env.local_count();
    e->PushLocalFrame(4);
    jobject a = e->AllocObject(c);
    CHECK(env.local_count() == before + 1);
    CHECK(e->GetObjectRefType(a) == JNILocalRefType);
    e->PopLocalFrame(nullptr);
    CHECK(env.local_count() == before);
    CHECK(g_freed == freed + 1);
    // A global reference keeps it past the frame, and deleting it frees it.
    e->PushLocalFrame(4);
    jobject b = e->AllocObject(c);
    jobject g = e->NewGlobalRef(b);
    CHECK(e->GetObjectRefType(g) == JNIGlobalRefType);
    CHECK(e->IsSameObject(b, g));
    e->PopLocalFrame(nullptr);
    CHECK(g_freed == freed + 1);
    e->DeleteGlobalRef(g);
    CHECK(g_freed == freed + 2);
    // PopLocalFrame's result survives as a reference in the frame below.
    e->PushLocalFrame(4);
    jobject kept = e->PopLocalFrame(e->AllocObject(c));
    CHECK(kept && e->IsInstanceOf(kept, c));
    CHECK(g_freed == freed + 2);
    e->DeleteLocalRef(kept);
    CHECK(g_freed == freed + 3);
    // Deleting local references as they are made keeps the table from growing (a thread the game attached and never
    // returns from makes them this way for its whole life).
    std::size_t start = env.local_count(), slots = env.local_slots();
    for (int i = 0; i < 10000; ++i) e->DeleteLocalRef(e->NewStringUTF("temporary"));
    CHECK(env.local_count() == start);
    CHECK(env.local_slots() == slots);
    // Weak references hold their object while they exist.
    jobject w = e->NewWeakGlobalRef(e->AllocObject(c));
    CHECK(e->GetObjectRefType(w) == JNIWeakGlobalRefType);
    CHECK(!e->IsSameObject(w, nullptr));
    e->DeleteWeakGlobalRef(w);
}

void exceptions(JNIEnv* e) {
    jvm::define("test/Thrower").static_method("fail", "(Ljava/lang/String;)V", [](jvm::Call& c) -> jvm::Value { jvm::throw_new("java/lang/IllegalStateException", c.str(0)); });
    jclass c = e->FindClass("test/Thrower");
    e->CallStaticVoidMethod(c, e->GetStaticMethodID(c, "fail", "(Ljava/lang/String;)V"), e->NewStringUTF("broken"));
    CHECK(e->ExceptionCheck());
    jthrowable t = e->ExceptionOccurred();
    e->ExceptionClear();
    CHECK(e->IsInstanceOf(t, e->FindClass("java/lang/RuntimeException")));
    jmethodID get_message = e->GetMethodID(e->FindClass("java/lang/Throwable"), "getMessage", "()Ljava/lang/String;");
    CHECK(text(e, static_cast<jstring>(e->CallObjectMethod(t, get_message))) == "broken");
    // ThrowNew with a class nothing defined: an exception of that name still, with its message.
    jclass odd = e->FindClass("com/example/OddException");
    e->ThrowNew(odd, "odd");
    jthrowable o = e->ExceptionOccurred();
    e->ExceptionClear();
    CHECK(text(e, static_cast<jstring>(e->CallObjectMethod(o, get_message))) == "odd");
    // A constructor with a message, inherited from Throwable by a class that defines none.
    jclass io = e->FindClass("java/io/IOException");
    jobject ex = e->NewObject(io, e->GetMethodID(io, "<init>", "(Ljava/lang/String;)V"), e->NewStringUTF("disk"));
    CHECK(text(e, static_cast<jstring>(e->CallObjectMethod(ex, get_message))) == "disk");
    // A call on null throws.
    e->CallIntMethod(nullptr, e->GetMethodID(e->FindClass("java/lang/String"), "length", "()I"));
    CHECK(e->ExceptionCheck());
    e->ExceptionClear();
}

void natives(JNIEnv* e) {
    jvm::define("test/Natives").native("mix", "(IJFDZBCSLjava/lang/String;IIIFFFFFFFD)I", jvm::kStatic);
    jclass c = e->FindClass("test/Natives");
    const JNINativeMethod methods[] = {
        {"mix", "(IJFDZBCSLjava/lang/String;IIIFFFFFFFD)I", reinterpret_cast<void*>(&native_mix)},
        {"twice", "(F)F", reinterpret_cast<void*>(&native_float)},
        {"quarter", "(D)D", reinterpret_cast<void*>(&native_double)},
        {"far", "(J)J", reinterpret_cast<void*>(&native_long)},
        {"positive", "(I)Z", reinterpret_cast<void*>(&native_bool)},
        {"shout", "(Ljava/lang/String;)Ljava/lang/String;", reinterpret_cast<void*>(&native_string)},
        {"count", "()I", reinterpret_cast<void*>(&native_this)},
    };
    CHECK(e->RegisterNatives(c, methods, 7) == JNI_OK);
    jvm::Env& env = *jvm::Env::from(e);
    jvm::Class& k = *jvm::find_class("test/Natives");
    // Twelve integer arguments (six on the stack) and ten vector ones (two on the stack), each kind in its place.
    jvm::Value r = env.call_static(k, "mix", "(IJFDZBCSLjava/lang/String;IIIFFFFFFFD)I",
                                   {jvm::Value::I(1), jvm::Value::J(1LL << 33), jvm::Value::F(0.5f), jvm::Value::D(0.25), jvm::Value::Z(true),
                                    jvm::Value::B(-2), jvm::Value::C(65), jvm::Value::S(-3), jvm::Value(jvm::string("four")), jvm::Value::I(6),
                                    jvm::Value::I(7), jvm::Value::I(8), jvm::Value::F(2), jvm::Value::F(3), jvm::Value::F(4), jvm::Value::F(5),
                                    jvm::Value::F(6), jvm::Value::F(7), jvm::Value::F(8), jvm::Value::D(9)});
    double expect = 1 + static_cast<double>(1LL << 33) * 2 + 0.5 * 3 + 0.25 * 4 + 5 + -2 * 6 + 65 * 7 + -3 * 8 + 4 * 9 + 6 * 10 + 7 * 11 + 8 * 12 +
                    2 * 13 + 3 * 14 + 4 * 15 + 5 * 16 + 6 * 17 + 7 * 18 + 8 * 19 + 9 * 20;
    CHECK(r.i() == static_cast<jint>(std::lround(expect)));
    // Each return type comes back whole.
    jvm::Ref<jvm::Object> o = jvm::new_object(k, "()V");
    CHECK(env.call(o.get(), "twice", "(F)F", {jvm::Value::F(1.25f)}).f() == 2.5f);
    CHECK(env.call(o.get(), "quarter", "(D)D", {jvm::Value::D(3.0)}).d() == 0.75);
    CHECK(env.call(o.get(), "far", "(J)J", {jvm::Value::J(5)}).j() == 0x100000005LL);
    CHECK(env.call(o.get(), "positive", "(I)Z", {jvm::Value::I(3)}).z() == JNI_TRUE);
    CHECK(env.call(o.get(), "positive", "(I)Z", {jvm::Value::I(-3)}).z() == JNI_FALSE);
    jvm::Value shout = env.call(o.get(), "shout", "(Ljava/lang/String;)Ljava/lang/String;", {jvm::Value(jvm::string("hey"))});
    auto* s = dynamic_cast<jvm::String*>(shout.l());
    CHECK(s && s->utf8() == "hey!");
    // The native sees its object: a field set from C++.
    jvm::define("test/Natives").field("count", "I");
    o->set_field(k.find_field("count", false), jvm::Value::I(17));
    CHECK(env.call(o.get(), "count", "()I").i() == 17);
    // The natives' frames are closed: no local references left behind.
    std::size_t before = env.local_count();
    for (int i = 0; i < 1000; ++i) env.call(o.get(), "shout", "(Ljava/lang/String;)Ljava/lang/String;", {jvm::Value(jvm::string("x"))});
    CHECK(env.local_count() == before);
    // Called through JNI as well (a Java method that is native, called by native code).
    jmethodID twice = e->GetMethodID(c, "twice", "(F)F");
    CHECK(e->CallFloatMethod(o.get() ? env.local(o.get()) : nullptr, twice, 4.0f) == 8.0f);
    // getDeclaredMethods sees the natives as native (the JNI bridge binds a library's exports by it).
    jclass class_class = e->FindClass("java/lang/Class");
    auto methods_array = static_cast<jobjectArray>(e->CallObjectMethod(c, e->GetMethodID(class_class, "getDeclaredMethods", "()[Ljava/lang/reflect/Method;")));
    jclass method_class = e->FindClass("java/lang/reflect/Method");
    jmethodID modifiers = e->GetMethodID(method_class, "getModifiers", "()I");
    jmethodID name = e->GetMethodID(method_class, "getName", "()Ljava/lang/String;");
    bool found = false;
    for (jsize i = 0; i < e->GetArrayLength(methods_array); ++i) {
        jobject m = e->GetObjectArrayElement(methods_array, i);
        if (text(e, static_cast<jstring>(e->CallObjectMethod(m, name))) == "mix") found = (e->CallIntMethod(m, modifiers) & jvm::kNative) != 0;
    }
    CHECK(found);
}

void reflection(JNIEnv* e) {
    jvm::define("test/Reflect").method("pick", "(ILjava/lang/String;[J)Ljava/lang/Object;", [](jvm::Call& c) { return jvm::Value(c.l(1)); });
    jclass c = e->FindClass("test/Reflect");
    jmethodID pick = e->GetMethodID(c, "pick", "(ILjava/lang/String;[J)Ljava/lang/Object;");
    jobject member = e->ToReflectedMethod(c, pick, JNI_FALSE);
    CHECK(e->FromReflectedMethod(member) == pick);
    // The parameter and return types, by name, as the JNI bridge reads them to rebuild the signature.
    jclass method_class = e->FindClass("java/lang/reflect/Method");
    auto params = static_cast<jobjectArray>(e->CallObjectMethod(member, e->GetMethodID(method_class, "getParameterTypes", "()[Ljava/lang/Class;")));
    jmethodID get_name = e->GetMethodID(e->FindClass("java/lang/Class"), "getName", "()Ljava/lang/String;");
    CHECK(e->GetArrayLength(params) == 3);
    CHECK(text(e, static_cast<jstring>(e->CallObjectMethod(e->GetObjectArrayElement(params, 0), get_name))) == "int");
    CHECK(text(e, static_cast<jstring>(e->CallObjectMethod(e->GetObjectArrayElement(params, 1), get_name))) == "java.lang.String");
    CHECK(text(e, static_cast<jstring>(e->CallObjectMethod(e->GetObjectArrayElement(params, 2), get_name))) == "[J");
    jobject ret = e->CallObjectMethod(member, e->GetMethodID(method_class, "getReturnType", "()Ljava/lang/Class;"));
    CHECK(text(e, static_cast<jstring>(e->CallObjectMethod(ret, get_name))) == "java.lang.Object");
    // Class.forName with dots, and getMethod by parameter classes.
    jclass class_class = e->FindClass("java/lang/Class");
    jobject found = e->CallStaticObjectMethod(class_class, e->GetStaticMethodID(class_class, "forName", "(Ljava/lang/String;)Ljava/lang/Class;"), e->NewStringUTF("test.Reflect"));
    CHECK(e->IsSameObject(found, c));
}

void threads() {
    // A thread that is not attached has no Env; attaching gives one, detaching takes it (and its references) away.
    JavaVM* vm = jvm::java_vm();
    std::atomic<bool> ok{false};
    std::thread t([&] {
        void* env = reinterpret_cast<void*>(1);
        bool detached = vm->functions->GetEnv(vm, &env, JNI_VERSION_1_6) == JNI_EDETACHED && env == nullptr;
        JNIEnv* e = nullptr;
        bool attached = vm->functions->AttachCurrentThread(vm, &e, nullptr) == JNI_OK && e;
        jstring s = e->NewStringUTF("from a thread");
        bool works = text(e, s) == "from a thread";
        void* again = nullptr;
        bool same = vm->functions->GetEnv(vm, &again, JNI_VERSION_1_6) == JNI_OK && again == e;
        vm->functions->DetachCurrentThread(vm);
        ok = detached && attached && works && same;
    });
    t.join();
    CHECK(ok);
}

void proxies(JNIEnv* e) {
    // An object of a proxy class takes every call of its interface; the handler sees which method was called.
    jvm::Class& callback = jvm::define_interface("test/Callback");
    jvm::Class& proxy_class = jvm::define("test/$Proxy0", "java/lang/reflect/Proxy");
    proxy_class.interfaces.push_back(&callback);
    proxy_class.proxy = true;
    jvm::Ref<jvm::Proxy> p(new jvm::Proxy(&proxy_class));
    std::string seen;
    p->invoke = [&seen](jvm::Call& c) {
        seen = c.method.name + ":" + std::to_string(c.j(0));
        return jvm::Value::I(5);
    };
    jclass cb = e->FindClass("test/Callback");
    jmethodID done = e->GetMethodID(cb, "done", "(J)I");
    jvm::Env& env = *jvm::Env::from(e);
    CHECK(e->CallIntMethod(env.local(p.get()), done, static_cast<jlong>(30)) == 5);
    CHECK(seen == "done:30");
    CHECK(e->IsInstanceOf(env.local(p.get()), cb));
}

void boxes(JNIEnv* e) {
    jvm::Ref<jvm::Object> five = jvm::box('I', jvm::Value::I(5));
    jvm::Env& env = *jvm::Env::from(e);
    jclass number = e->FindClass("java/lang/Number");
    CHECK(e->CallIntMethod(env.local(five.get()), e->GetMethodID(number, "intValue", "()I")) == 5);
    CHECK(e->CallLongMethod(env.local(five.get()), e->GetMethodID(number, "longValue", "()J")) == 5);
    jclass long_class = e->FindClass("java/lang/Long");
    jobject big = e->CallStaticObjectMethod(long_class, e->GetStaticMethodID(long_class, "valueOf", "(J)Ljava/lang/Long;"), static_cast<jlong>(1) << 40);
    CHECK(e->CallLongMethod(big, e->GetMethodID(number, "longValue", "()J")) == (static_cast<jlong>(1) << 40));
    CHECK(e->IsInstanceOf(big, number));
    jmethodID to_string = e->GetMethodID(e->FindClass("java/lang/Object"), "toString", "()Ljava/lang/String;");
    CHECK(text(e, static_cast<jstring>(e->CallObjectMethod(big, to_string))) == "1099511627776");
}

void buffers(JNIEnv* e) {
    char memory[16] = {};
    jobject b = e->NewDirectByteBuffer(memory, sizeof memory);
    CHECK(e->GetDirectBufferAddress(b) == memory);
    CHECK(e->GetDirectBufferCapacity(b) == 16);
    jclass buffer = e->FindClass("java/nio/ByteBuffer");
    CHECK(e->IsInstanceOf(b, buffer));
    jobject own = e->CallStaticObjectMethod(buffer, e->GetStaticMethodID(buffer, "allocateDirect", "(I)Ljava/nio/ByteBuffer;"), 64);
    CHECK(e->GetDirectBufferCapacity(own) == 64 && e->GetDirectBufferAddress(own));
    // A non-buffer has no address.
    CHECK(e->GetDirectBufferAddress(e->NewStringUTF("no")) == nullptr && e->GetDirectBufferCapacity(e->NewStringUTF("no")) == -1);
}

void monitors(JNIEnv* e) {
    jobject o = e->NewStringUTF("lock");
    // Entered twice by one thread (Java monitors are reentrant), left twice.
    CHECK(e->MonitorEnter(o) == JNI_OK && e->MonitorEnter(o) == JNI_OK);
    CHECK(e->MonitorExit(o) == JNI_OK && e->MonitorExit(o) == JNI_OK);
}

}  // namespace

int main() {
    JavaVM* vm = jvm::java_vm();
    JNIEnv* e = nullptr;
    CHECK(vm->functions->AttachCurrentThread(vm, &e, nullptr) == JNI_OK);
    CHECK(e->GetVersion() == JNI_VERSION_1_6);
    // Each group in a frame of its own, as a native call would be.
    void (*groups[])(JNIEnv*) = {strings, classes, made_up, fields, arrays, references, exceptions, natives, reflection, proxies, boxes, buffers, monitors};
    for (auto group : groups) {
        e->PushLocalFrame(16);
        group(e);
        // A group that left an exception pending is a failure of its own.
        CHECK(!e->ExceptionCheck());
        e->ExceptionClear();
        e->PopLocalFrame(nullptr);
    }
    threads();
    if (g_failed) {
        std::printf("%d OF %d CHECKS FAILED\n", g_failed, g_checks);
        return 1;
    }
    std::printf("%d checks\nALL CHECKS PASSED\n", g_checks);
    return 0;
}
