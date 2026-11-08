// JNI across the 32/64-bit boundary: the guest's JavaVM and JNIEnv, 32-bit handles for
// references and IDs, every JNI function, and native methods registered by guest code.
#include "jni_bridge.h"

#include "live.h"
#include "tweaks.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstring>
#include <elf.h>
#include <fcntl.h>
#include <map>
#include <sys/mman.h>
#include <sys/stat.h>
#include <tuple>
#include <unistd.h>
#include <unordered_map>
#include <utility>

namespace arm32 {

namespace {

JavaVM* g_vm = nullptr;
gaddr g_guest_vm = 0, g_guest_env = 0;
gaddr g_stubs = 0;  // first JNIEnv stub; JavaVM stubs follow
thread_local JNIEnv* t_env = nullptr;

// The calling thread's host JNIEnv.
JNIEnv* env() {
    if (!t_env && g_vm) g_vm->GetEnv(reinterpret_cast<void**>(&t_env), JNI_VERSION_1_6);
    return t_env;
}

Memory& mem() { return Guest::get().proc.mem; }
std::uint32_t& word(gaddr g) { return *mem().ptr<std::uint32_t>(g); }

// Host function numbers: JNIEnv function i at kEnvBase + i, JavaVM function i at kVmBase + i.
constexpr std::uint32_t kEnvBase = kReentrantBase;
constexpr std::uint32_t kVmBase = kReentrantBase + 0x100;
constexpr std::size_t kEnvCount = sizeof(JNINativeInterface) / sizeof(void*);
constexpr std::size_t kVmCount = sizeof(JNIInvokeInterface) / sizeof(void*);
constexpr std::uint32_t kStubSize = 20;  // push {r7, lr}; movw; movt; svc 0; pop {r7, pc}
#define ENV_INDEX(name) (offsetof(JNINativeInterface, name) / sizeof(void*))
#define VM_INDEX(name) (offsetof(JNIInvokeInterface, name) / sizeof(void*))

std::string guest_string(gaddr p) {
    std::string s;
    if (!p) return s;
    for (gaddr g = p; mem().readable(g, 1); ++g) {
        char c = static_cast<char>(*mem().host(g));
        if (!c) break;
        s.push_back(c);
    }
    return s;
}

float as_float(std::uint32_t bits) {
    float f;
    std::memcpy(&f, &bits, 4);
    return f;
}
double as_double(std::uint64_t bits) {
    double d;
    std::memcpy(&d, &bits, 8);
    return d;
}
std::uint32_t float_bits(float f) {
    std::uint32_t b;
    std::memcpy(&b, &f, 4);
    return b;
}
std::uint64_t double_bits(double d) {
    std::uint64_t b;
    std::memcpy(&b, &d, 8);
    return b;
}

// ---------------------------------------------------------------------------------------------
// Handles. The tag in the top four bits says which table the index is for.

constexpr std::uint32_t kTagMask = 0xf0000000, kLocal = 0x10000000, kGlobal = 0x20000000, kWeak = 0x30000000,
                        kMethod = 0x40000000, kField = 0x50000000;

// Local references of this thread, with the table size at each open frame (native method call
// or PushLocalFrame). Index 0 is never used.
struct Locals {
    std::vector<jobject> refs{nullptr};
    std::vector<std::size_t> frames;
};
thread_local Locals t_locals;

std::mutex g_refs_lock;
std::vector<jobject> g_globals{nullptr}, g_weaks{nullptr};
std::vector<std::uint32_t> g_globals_free, g_weaks_free;

std::uint32_t local(jobject o) {
    if (!o) return 0;
    t_locals.refs.push_back(o);
    return kLocal | static_cast<std::uint32_t>(t_locals.refs.size() - 1);
}

std::uint32_t global(jobject o, bool weak) {
    if (!o) return 0;
    std::lock_guard<std::mutex> g(g_refs_lock);
    auto& table = weak ? g_weaks : g_globals;
    auto& free = weak ? g_weaks_free : g_globals_free;
    std::uint32_t i;
    if (!free.empty()) {
        i = free.back();
        free.pop_back();
        table[i] = o;
    } else {
        i = static_cast<std::uint32_t>(table.size());
        table.push_back(o);
    }
    return (weak ? kWeak : kGlobal) | i;
}

jobject obj(std::uint32_t h) {
    if (!h) return nullptr;
    std::uint32_t i = h & ~kTagMask;
    switch (h & kTagMask) {
    case kLocal:
        return i < t_locals.refs.size() ? t_locals.refs[i] : nullptr;
    case kGlobal: {
        std::lock_guard<std::mutex> g(g_refs_lock);
        return i < g_globals.size() ? g_globals[i] : nullptr;
    }
    case kWeak: {
        std::lock_guard<std::mutex> g(g_refs_lock);
        return i < g_weaks.size() ? g_weaks[i] : nullptr;
    }
    default:
        log("arm32: jni: bad reference handle %#x", h);
        return nullptr;
    }
}

void push_frame() { t_locals.frames.push_back(t_locals.refs.size()); }

void pop_frame() {
    if (t_locals.frames.empty()) return;
    t_locals.refs.resize(t_locals.frames.back());
    t_locals.frames.pop_back();
}

void delete_local(std::uint32_t h) {
    if ((h & kTagMask) != kLocal) return;
    std::uint32_t i = h & ~kTagMask;
    auto& refs = t_locals.refs;
    if (i == 0 || i >= refs.size() || !refs[i]) return;
    env()->DeleteLocalRef(refs[i]);
    refs[i] = nullptr;
    // Deleting the newest references (the usual pattern) shrinks the table again.
    std::size_t floor = t_locals.frames.empty() ? 1 : std::max<std::size_t>(1, t_locals.frames.back());
    while (refs.size() > floor && !refs.back()) refs.pop_back();
}

// Method and field IDs, with each method's parameter and return types for converting calls.
struct Method {
    jmethodID id = nullptr;
    std::string params;  // one character per parameter: ZBCSIJFD, or L for any reference
    char ret = 'V';
};
std::mutex g_ids_lock;
std::vector<Method> g_methods{Method{}};
std::unordered_map<jmethodID, std::uint32_t> g_method_index;
std::vector<jfieldID> g_fields{nullptr};
std::unordered_map<jfieldID, std::uint32_t> g_field_index;

// "(ILjava/lang/String;[J)V" -> params "ILL", ret 'V'.
bool parse_signature(const std::string& sig, std::string& params, char& ret) {
    params.clear();
    std::size_t i = 0;
    if (i >= sig.size() || sig[i] != '(') return false;
    ++i;
    auto skip_type = [&](char& kind) -> bool {
        std::size_t start = i;
        while (i < sig.size() && sig[i] == '[') ++i;
        if (i >= sig.size()) return false;
        if (sig[i] == 'L') {
            std::size_t end = sig.find(';', i);
            if (end == std::string::npos) return false;
            i = end + 1;
        } else {
            ++i;
        }
        kind = (sig[start] == '[' || sig[start] == 'L') ? 'L' : sig[start];
        return true;
    };
    while (i < sig.size() && sig[i] != ')') {
        char k;
        if (!skip_type(k)) return false;
        params.push_back(k);
    }
    if (i >= sig.size()) return false;
    ++i;
    return skip_type(ret);
}

std::uint32_t method_handle(jmethodID id, const std::string& sig) {
    if (!id) return 0;
    std::lock_guard<std::mutex> g(g_ids_lock);
    auto it = g_method_index.find(id);
    if (it != g_method_index.end()) return kMethod | it->second;
    Method m;
    m.id = id;
    if (!parse_signature(sig, m.params, m.ret)) log("arm32: jni: cannot parse method signature %s", sig.c_str());
    auto i = static_cast<std::uint32_t>(g_methods.size());
    g_methods.push_back(std::move(m));
    g_method_index[id] = i;
    return kMethod | i;
}

// A copy of the method's entry: the table may grow (and move) under another thread.
bool method(std::uint32_t h, Method& out) {
    std::lock_guard<std::mutex> g(g_ids_lock);
    std::uint32_t i = h & ~kTagMask;
    if ((h & kTagMask) != kMethod || i == 0 || i >= g_methods.size()) {
        log("arm32: jni: bad method ID %#x", h);
        return false;
    }
    out = g_methods[i];
    return true;
}

std::uint32_t field_handle(jfieldID id) {
    if (!id) return 0;
    std::lock_guard<std::mutex> g(g_ids_lock);
    auto it = g_field_index.find(id);
    if (it != g_field_index.end()) return kField | it->second;
    auto i = static_cast<std::uint32_t>(g_fields.size());
    g_fields.push_back(id);
    g_field_index[id] = i;
    return kField | i;
}

jfieldID field(std::uint32_t h) {
    std::lock_guard<std::mutex> g(g_ids_lock);
    std::uint32_t i = h & ~kTagMask;
    if ((h & kTagMask) != kField || i == 0 || i >= g_fields.size()) {
        log("arm32: jni: bad field ID %#x", h);
        return nullptr;
    }
    return g_fields[i];
}

// The handle of a method ID seen before, else 0.
std::uint32_t known_method(jmethodID id) {
    std::lock_guard<std::mutex> g(g_ids_lock);
    auto it = g_method_index.find(id);
    return it == g_method_index.end() ? 0 : kMethod | it->second;
}

// A class as a global reference, looked up once by the caller (boot classes only: any thread's
// class loader finds them).
jclass global_class(JNIEnv* e, const char* name) {
    jclass local_class = e->FindClass(name);
    auto c = static_cast<jclass>(e->NewGlobalRef(local_class));
    e->DeleteLocalRef(local_class);
    return c;
}

// The reflection classes and methods the signatures below need, looked up once.
struct Reflect {
    jclass method_class;
    jmethodID class_get_name, method_params, method_return, constructor_params;
};
const Reflect& reflect(JNIEnv* e) {
    static const Reflect r = [e] {
        jclass class_class = global_class(e, "java/lang/Class");
        jclass method_class = global_class(e, "java/lang/reflect/Method");
        jclass constructor_class = global_class(e, "java/lang/reflect/Constructor");
        return Reflect{method_class, e->GetMethodID(class_class, "getName", "()Ljava/lang/String;"),
                       e->GetMethodID(method_class, "getParameterTypes", "()[Ljava/lang/Class;"),
                       e->GetMethodID(method_class, "getReturnType", "()Ljava/lang/Class;"),
                       e->GetMethodID(constructor_class, "getParameterTypes", "()[Ljava/lang/Class;")};
    }();
    return r;
}

// The JNI signature of a java.lang.reflect.Method or Constructor, for FromReflectedMethod. Every
// local reference made here is deleted again: on a thread the guest attached, nothing else would
// free them, and Unity asks through reflection for each call it makes into Java.
std::string descriptor_of(JNIEnv* e, jclass c) {
    auto name_obj = static_cast<jstring>(e->CallObjectMethod(c, reflect(e).class_get_name));
    std::string name;
    if (name_obj) {
        if (const char* chars = e->GetStringUTFChars(name_obj, nullptr)) {
            name = chars;
            e->ReleaseStringUTFChars(name_obj, chars);
        }
        e->DeleteLocalRef(name_obj);
    }
    static const std::pair<const char*, const char*> primitives[] = {
        {"int", "I"}, {"long", "J"}, {"boolean", "Z"}, {"byte", "B"}, {"char", "C"},
        {"short", "S"}, {"float", "F"}, {"double", "D"}, {"void", "V"},
    };
    for (auto& [n, d] : primitives) {
        if (name == n) return d;
    }
    for (char& ch : name) {
        if (ch == '.') ch = '/';
    }
    return !name.empty() && name[0] == '[' ? name : "L" + name + ";";
}

std::string reflected_signature(JNIEnv* e, jobject member) {
    const Reflect& r = reflect(e);
    bool is_method = e->IsInstanceOf(member, r.method_class);
    auto params = static_cast<jobjectArray>(e->CallObjectMethod(member, is_method ? r.method_params : r.constructor_params));
    std::string sig = "(";
    jsize n = params ? e->GetArrayLength(params) : 0;
    for (jsize i = 0; i < n; ++i) {
        auto c = static_cast<jclass>(e->GetObjectArrayElement(params, i));
        sig += descriptor_of(e, c);
        e->DeleteLocalRef(c);
    }
    if (params) e->DeleteLocalRef(params);
    sig += ")";
    if (is_method) {
        auto ret = static_cast<jclass>(e->CallObjectMethod(member, r.method_return));
        sig += descriptor_of(e, ret);
        e->DeleteLocalRef(ret);
    } else {
        sig += "V";
    }
    return sig;
}

// ---------------------------------------------------------------------------------------------
// Reading guest arguments.

// A JNI stub's arguments: r0-r3, then the caller's stack. 64-bit values start at an even word.
struct Words {
    Thread& t;
    unsigned i = 0;
    std::uint32_t u32() { return t.arg(i++); }
    std::uint64_t u64() {
        if (i & 1) ++i;
        std::uint64_t lo = t.arg(i++);
        return lo | (std::uint64_t{t.arg(i++)} << 32);
    }
};

// A guest va_list (ARM EABI: a pointer to the next argument word); 64-bit values 8-aligned.
struct VaList {
    gaddr ap;
    std::uint32_t u32() {
        std::uint32_t v = word(ap);
        ap += 4;
        return v;
    }
    std::uint64_t u64() {
        ap = (ap + 7) & ~gaddr{7};
        std::uint64_t lo = word(ap), hi = word(ap + 4);
        ap += 8;
        return lo | (hi << 32);
    }
};

// Method arguments passed through "..." or a va_list: floats arrive promoted to double.
template <class Reader>
std::vector<jvalue> values(const std::string& params, Reader& r) {
    std::vector<jvalue> v(params.size());
    for (std::size_t k = 0; k < params.size(); ++k) {
        switch (params[k]) {
        case 'Z': v[k].z = static_cast<jboolean>(r.u32()); break;
        case 'B': v[k].b = static_cast<jbyte>(r.u32()); break;
        case 'C': v[k].c = static_cast<jchar>(r.u32()); break;
        case 'S': v[k].s = static_cast<jshort>(r.u32()); break;
        case 'I': v[k].i = static_cast<jint>(r.u32()); break;
        case 'J': v[k].j = static_cast<jlong>(r.u64()); break;
        case 'F': v[k].f = static_cast<float>(as_double(r.u64())); break;
        case 'D': v[k].d = as_double(r.u64()); break;
        default: v[k].l = obj(r.u32()); break;
        }
    }
    return v;
}

// Method arguments as a guest jvalue array (8 bytes per element).
std::vector<jvalue> values_array(const std::string& params, gaddr array) {
    std::vector<jvalue> v(params.size());
    for (std::size_t k = 0; k < params.size(); ++k) {
        gaddr p = array + static_cast<gaddr>(k * 8);
        switch (params[k]) {
        case 'Z': v[k].z = *mem().ptr<std::uint8_t>(p); break;
        case 'B': v[k].b = *mem().ptr<std::int8_t>(p); break;
        case 'C': v[k].c = *mem().ptr<std::uint16_t>(p); break;
        case 'S': v[k].s = *mem().ptr<std::int16_t>(p); break;
        case 'I': v[k].i = *mem().ptr<std::int32_t>(p); break;
        case 'J': std::memcpy(&v[k].j, mem().host(p), 8); break;
        case 'F': std::memcpy(&v[k].f, mem().host(p), 4); break;
        case 'D': std::memcpy(&v[k].d, mem().host(p), 8); break;
        default: v[k].l = obj(word(p)); break;
        }
    }
    return v;
}

// ---------------------------------------------------------------------------------------------
// Call<Type>Method, CallNonvirtual<Type>Method, CallStatic<Type>Method in their three forms.

enum Kind { kVirtual, kNonvirtual, kStatic };
enum Form { kDots, kVa, kArray };
constexpr char kCallTypes[10] = {'L', 'Z', 'B', 'C', 'S', 'I', 'J', 'F', 'D', 'V'};

template <int K, int F, int T>
std::uint64_t call_method(Thread& t) {
    constexpr char R = kCallTypes[T];
    Words w{t};
    w.u32();  // the guest JNIEnv
    jobject target = obj(w.u32());
    jclass cls = K == kNonvirtual ? static_cast<jclass>(obj(w.u32())) : nullptr;
    Method m;
    if (!method(w.u32(), m)) return 0;
    jmethodID id = m.id;
    const std::string& params = m.params;
    std::vector<jvalue> v;
    if constexpr (F == kDots) {
        v = values(params, w);
    } else if constexpr (F == kVa) {
        VaList va{w.u32()};
        v = values(params, va);
    } else {
        v = values_array(params, w.u32());
    }
    JNIEnv* e = env();
#define ARM32_CALL(Type)                                                                        \
    (K == kStatic       ? e->CallStatic##Type##MethodA(static_cast<jclass>(target), id, v.data()) \
     : K == kNonvirtual ? e->CallNonvirtual##Type##MethodA(target, cls, id, v.data())          \
                        : e->Call##Type##MethodA(target, id, v.data()))
    if constexpr (R == 'V') {
        ARM32_CALL(Void);
        return 0;
    } else if constexpr (R == 'L') {
        return local(ARM32_CALL(Object));
    } else if constexpr (R == 'Z') {
        return ARM32_CALL(Boolean);
    } else if constexpr (R == 'B') {
        return static_cast<std::uint32_t>(static_cast<std::int32_t>(ARM32_CALL(Byte)));
    } else if constexpr (R == 'C') {
        return ARM32_CALL(Char);
    } else if constexpr (R == 'S') {
        return static_cast<std::uint32_t>(static_cast<std::int32_t>(ARM32_CALL(Short)));
    } else if constexpr (R == 'I') {
        return static_cast<std::uint32_t>(ARM32_CALL(Int));
    } else if constexpr (R == 'J') {
        return static_cast<std::uint64_t>(ARM32_CALL(Long));
    } else if constexpr (R == 'F') {
        return float_bits(ARM32_CALL(Float));
    } else {
        return double_bits(ARM32_CALL(Double));
    }
#undef ARM32_CALL
}

template <int K, int F, std::size_t... T>
void register_calls(std::size_t base, std::index_sequence<T...>) {
    ((register_host_fn(kEnvBase + static_cast<std::uint32_t>(base + T * 3 + F), &call_method<K, F, static_cast<int>(T)>)), ...);
}

template <int F>
std::uint64_t new_object(Thread& t) {
    Words w{t};
    w.u32();
    auto cls = static_cast<jclass>(obj(w.u32()));
    Method m;
    if (!method(w.u32(), m)) return 0;
    jmethodID id = m.id;
    const std::string& params = m.params;
    std::vector<jvalue> v;
    if constexpr (F == kDots) {
        v = values(params, w);
    } else if constexpr (F == kVa) {
        VaList va{w.u32()};
        v = values(params, va);
    } else {
        v = values_array(params, w.u32());
    }
    return local(env()->NewObjectA(cls, id, v.data()));
}

// ---------------------------------------------------------------------------------------------
// Fields.

constexpr char kFieldTypes[9] = {'L', 'Z', 'B', 'C', 'S', 'I', 'J', 'F', 'D'};

template <bool Static, int T>
std::uint64_t get_field(Thread& t) {
    constexpr char R = kFieldTypes[T];
    Words w{t};
    w.u32();
    jobject o = obj(w.u32());
    jfieldID f = field(w.u32());
    JNIEnv* e = env();
#define ARM32_GET(Type) (Static ? e->GetStatic##Type##Field(static_cast<jclass>(o), f) : e->Get##Type##Field(o, f))
    if constexpr (R == 'L') return local(ARM32_GET(Object));
    else if constexpr (R == 'Z') return ARM32_GET(Boolean);
    else if constexpr (R == 'B') return static_cast<std::uint32_t>(static_cast<std::int32_t>(ARM32_GET(Byte)));
    else if constexpr (R == 'C') return ARM32_GET(Char);
    else if constexpr (R == 'S') return static_cast<std::uint32_t>(static_cast<std::int32_t>(ARM32_GET(Short)));
    else if constexpr (R == 'I') return static_cast<std::uint32_t>(ARM32_GET(Int));
    else if constexpr (R == 'J') return static_cast<std::uint64_t>(ARM32_GET(Long));
    else if constexpr (R == 'F') return float_bits(ARM32_GET(Float));
    else return double_bits(ARM32_GET(Double));
#undef ARM32_GET
}

template <bool Static, int T>
std::uint64_t set_field(Thread& t) {
    constexpr char R = kFieldTypes[T];
    Words w{t};
    w.u32();
    jobject o = obj(w.u32());
    jfieldID f = field(w.u32());
    JNIEnv* e = env();
#define ARM32_SET(Type, value) \
    (Static ? e->SetStatic##Type##Field(static_cast<jclass>(o), f, value) : e->Set##Type##Field(o, f, value))
    if constexpr (R == 'L') ARM32_SET(Object, obj(w.u32()));
    else if constexpr (R == 'Z') ARM32_SET(Boolean, static_cast<jboolean>(w.u32()));
    else if constexpr (R == 'B') ARM32_SET(Byte, static_cast<jbyte>(w.u32()));
    else if constexpr (R == 'C') ARM32_SET(Char, static_cast<jchar>(w.u32()));
    else if constexpr (R == 'S') ARM32_SET(Short, static_cast<jshort>(w.u32()));
    else if constexpr (R == 'I') ARM32_SET(Int, static_cast<jint>(w.u32()));
    else if constexpr (R == 'J') ARM32_SET(Long, static_cast<jlong>(w.u64()));
    else if constexpr (R == 'F') ARM32_SET(Float, as_float(w.u32()));
    else ARM32_SET(Double, as_double(w.u64()));
#undef ARM32_SET
    return 0;
}

template <bool Static, std::size_t... T>
void register_fields(std::size_t get_base, std::size_t set_base, std::index_sequence<T...>) {
    ((register_host_fn(kEnvBase + static_cast<std::uint32_t>(get_base + T), &get_field<Static, static_cast<int>(T)>)), ...);
    ((register_host_fn(kEnvBase + static_cast<std::uint32_t>(set_base + T), &set_field<Static, static_cast<int>(T)>)), ...);
}

// ---------------------------------------------------------------------------------------------
// Primitive arrays. Element pointers handed to the guest are copies in the guest heap.

constexpr char kArrayTypes[8] = {'Z', 'B', 'C', 'S', 'I', 'J', 'F', 'D'};
constexpr std::size_t element_size(char c) {
    return (c == 'Z' || c == 'B') ? 1 : (c == 'C' || c == 'S') ? 2 : (c == 'I' || c == 'F') ? 4 : 8;
}

#define ARM32_BY_TYPE(c, MACRO)        \
    switch (c) {                       \
    case 'Z': MACRO(Boolean, jboolean) \
    case 'B': MACRO(Byte, jbyte)       \
    case 'C': MACRO(Char, jchar)       \
    case 'S': MACRO(Short, jshort)     \
    case 'I': MACRO(Int, jint)         \
    case 'J': MACRO(Long, jlong)       \
    case 'F': MACRO(Float, jfloat)     \
    default: MACRO(Double, jdouble)    \
    }

template <int T>
std::uint64_t new_array(Thread& t) {
    Words w{t};
    w.u32();
    auto n = static_cast<jsize>(w.u32());
    JNIEnv* e = env();
#define ARM32_NEW(Type, ctype) return local(e->New##Type##Array(n));
    ARM32_BY_TYPE(kArrayTypes[T], ARM32_NEW)
#undef ARM32_NEW
}

void region(JNIEnv* e, char c, jarray a, jsize start, jsize n, void* buf, bool set) {
#define ARM32_REGION(Type, ctype)                                                                  \
    if (set) e->Set##Type##ArrayRegion(static_cast<ctype##Array>(a), start, n, static_cast<ctype*>(buf)); \
    else e->Get##Type##ArrayRegion(static_cast<ctype##Array>(a), start, n, static_cast<ctype*>(buf));     \
    return;
    ARM32_BY_TYPE(c, ARM32_REGION)
#undef ARM32_REGION
}

template <int T>
std::uint64_t get_elements(Thread& t) {
    Words w{t};
    w.u32();
    auto a = static_cast<jarray>(obj(w.u32()));
    gaddr is_copy = w.u32();
    JNIEnv* e = env();
    if (!a) return 0;
    jsize n = e->GetArrayLength(a);
    std::size_t bytes = static_cast<std::size_t>(n) * element_size(kArrayTypes[T]);
    gaddr g = Guest::get().malloc(static_cast<std::uint32_t>(bytes ? bytes : 1));
    if (!g) return 0;
    region(e, kArrayTypes[T], a, 0, n, mem().host(g), false);
    if (is_copy) *mem().host(is_copy) = JNI_TRUE;
    return g;
}

template <int T>
std::uint64_t release_elements(Thread& t) {
    Words w{t};
    w.u32();
    auto a = static_cast<jarray>(obj(w.u32()));
    gaddr g = w.u32();
    auto mode = static_cast<jint>(w.u32());
    JNIEnv* e = env();
    if (a && g && mode != JNI_ABORT) region(e, kArrayTypes[T], a, 0, e->GetArrayLength(a), mem().host(g), true);
    if (mode != JNI_COMMIT) Guest::get().free(g);
    return 0;
}

template <int T, bool Set>
std::uint64_t array_region(Thread& t) {
    Words w{t};
    w.u32();
    auto a = static_cast<jarray>(obj(w.u32()));
    auto start = static_cast<jsize>(w.u32());
    auto n = static_cast<jsize>(w.u32());
    gaddr buf = w.u32();
    region(env(), kArrayTypes[T], a, start, n, mem().host(buf), Set);
    return 0;
}

template <std::size_t... T>
void register_arrays(std::index_sequence<T...>) {
    ((register_host_fn(kEnvBase + static_cast<std::uint32_t>(ENV_INDEX(NewBooleanArray) + T), &new_array<static_cast<int>(T)>)), ...);
    ((register_host_fn(kEnvBase + static_cast<std::uint32_t>(ENV_INDEX(GetBooleanArrayElements) + T), &get_elements<static_cast<int>(T)>)), ...);
    ((register_host_fn(kEnvBase + static_cast<std::uint32_t>(ENV_INDEX(ReleaseBooleanArrayElements) + T), &release_elements<static_cast<int>(T)>)), ...);
    ((register_host_fn(kEnvBase + static_cast<std::uint32_t>(ENV_INDEX(GetBooleanArrayRegion) + T), &array_region<static_cast<int>(T), false>)), ...);
    ((register_host_fn(kEnvBase + static_cast<std::uint32_t>(ENV_INDEX(SetBooleanArrayRegion) + T), &array_region<static_cast<int>(T), true>)), ...);
}

// GetPrimitiveArrayCritical does not name the element type; the array's class does.
struct Critical {
    jobject array;  // global reference while the guest holds the copy
    char type;
};
std::mutex g_critical_lock;
std::unordered_map<gaddr, Critical> g_critical;

char array_type(JNIEnv* e, jarray a) {
    // One instance check per primitive array class, looked up once: no Java call, no local
    // reference left behind per call.
    static const std::array<jclass, 8> classes = [e] {
        static const char* const kNames[8] = {"[Z", "[B", "[C", "[S", "[I", "[J", "[F", "[D"};
        std::array<jclass, 8> c{};
        for (std::size_t k = 0; k < 8; ++k) c[k] = global_class(e, kNames[k]);
        return c;
    }();
    for (std::size_t k = 0; k < 8; ++k) {
        if (e->IsInstanceOf(a, classes[k])) return kArrayTypes[k];
    }
    return 'B';
}

// ---------------------------------------------------------------------------------------------
// Direct buffers. Buffers created from guest memory are guest memory already; buffers Java
// allocated get a guest copy, written back whenever a native method returns on this thread.

// A Java direct buffer outside guest memory, as the guest sees it: a copy in the guest heap,
// filled when the guest asks for the buffer's address and written back when the native call
// that asked returns. Kept per thread for the next call with the same buffer (natives such as
// an audio or video callback get the same buffer every time).
struct Shadow {
    void* host;
    gaddr guest;
    std::size_t size;
    bool writable;   // read-only buffers (MediaCodec output, for one) are never written back
    int frame;       // native call depth that took it and writes it back, 0 when idle
    // Handed out outside any native call (a thread the guest made): the guest may keep using the
    // address for as long as it likes, so the copy is never dropped to make room, only with its
    // thread.
    bool outside;
    std::uint64_t last_use;
    // The contents as copied in, for writable buffers: the write-back compares against this,
    // not against the Java memory, which the native call may have released meanwhile (a
    // decoder buffer handed back during the call), so a buffer the guest only read is never
    // touched again.
    std::vector<std::uint8_t> pristine;
};

// Guest copies of a thread that ended without its guest thread retiring first (one the guest
// created runs out on its own): freeing them needs guest code, so the next thread that makes a
// copy frees them. Never destroyed, since threads can still end while the process exits.
std::mutex g_orphans_lock;
std::vector<gaddr>* const g_orphans = new std::vector<gaddr>;
std::atomic<bool> g_have_orphans{false};

// A thread's copies. The ones still allocated when the thread is gone are orphans (above);
// retire() frees a Java or audio thread's own while its guest thread still runs.
struct Shadows {
    std::vector<Shadow> list;
    ~Shadows() {
        if (list.empty()) return;
        std::lock_guard<std::mutex> l(g_orphans_lock);
        for (const Shadow& s : list) g_orphans->push_back(s.guest);
        g_have_orphans.store(true);
    }
};
thread_local Shadows t_shadows;
thread_local int t_native_depth = 0;     // Java -> guest native calls open on this thread
thread_local std::uint64_t t_shadow_clock = 0;
// Idle copies kept per thread beyond this many bytes are freed, oldest first.
constexpr std::size_t kShadowCache = 16 << 20;

gaddr shadow_for(void* host, std::size_t size, bool writable) {
    if (g_have_orphans.load(std::memory_order_relaxed)) {
        std::vector<gaddr> orphans;
        {
            std::lock_guard<std::mutex> l(g_orphans_lock);
            orphans.swap(*g_orphans);
            g_have_orphans.store(false);
        }
        for (gaddr g : orphans) Guest::get().free(g);
    }
    auto& shadows = t_shadows.list;
    ++t_shadow_clock;
    for (auto& s : shadows) {
        if (s.host != host || s.size != size) continue;
        // Taken earlier in this call: the guest may have written to it already.
        if (!s.frame) {
            std::memcpy(mem().host(s.guest), host, size);
            s.frame = t_native_depth;
            s.writable = writable;
            if (writable) s.pristine.assign(static_cast<const std::uint8_t*>(host), static_cast<const std::uint8_t*>(host) + size);
            else s.pristine.clear();
        }
        s.outside |= t_native_depth == 0;
        s.last_use = t_shadow_clock;
        return s.guest;
    }
    // Room for the new copy: drop idle copies until the cache fits. Only copies of finished
    // native calls are idle; one handed out outside a call may still be in use.
    std::size_t idle = 0;
    for (auto& s : shadows) idle += s.frame || s.outside ? 0 : s.size;
    while (idle + size > kShadowCache) {
        auto oldest = shadows.end();
        for (auto it = shadows.begin(); it != shadows.end(); ++it) {
            if (!it->frame && !it->outside && (oldest == shadows.end() || it->last_use < oldest->last_use)) oldest = it;
        }
        if (oldest == shadows.end()) break;
        idle -= oldest->size;
        Guest::get().free(oldest->guest);
        shadows.erase(oldest);
    }
    gaddr g = Guest::get().malloc(static_cast<std::uint32_t>(size ? size : 1));
    if (!g) return 0;
    if (g_trace) log("trace: direct buffer %p (%zu bytes, %s) copied to %#x", host, size, writable ? "writable" : "read-only", g);
    std::memcpy(mem().host(g), host, size);
    shadows.push_back(Shadow{host, g, size, writable, t_native_depth, t_native_depth == 0, t_shadow_clock, {}});
    if (writable) shadows.back().pristine.assign(static_cast<const std::uint8_t*>(host), static_cast<const std::uint8_t*>(host) + size);
    return g;
}

// Guest::thread_fini: the copies of a thread that is ending go back to the guest heap while its
// guest thread can still run free(). A thread per web request, each with a 128 KB buffer of its
// own, left that much behind every time.
void release_thread_state() {
    for (const Shadow& s : t_shadows.list) Guest::get().free(s.guest);
    t_shadows.list.clear();
}

// At the end of the native call at depth `depth`: the blocks the guest changed in the buffers it
// took go back to Java. Buffers taken outside any native call (by guest threads) are never
// written back, since nothing tells when Java would look.
void sync_shadows(int depth) {
    for (auto& s : t_shadows.list) {
        if (s.frame != depth || !depth) continue;
        s.frame = 0;
        if (!s.writable || s.pristine.size() != s.size) continue;
        const auto* g = mem().host(s.guest);
        auto* h = static_cast<std::uint8_t*>(s.host);
        // Compared in 4 KB blocks against the contents copied in.
        for (std::size_t off = 0; off < s.size; off += 4096) {
            std::size_t n = std::min<std::size_t>(4096, s.size - off);
            if (std::memcmp(s.pristine.data() + off, g + off, n) != 0) std::memcpy(h + off, g + off, n);
        }
        // Emptied but kept allocated: the same buffer comes back on the next call (an audio
        // device's, every few milliseconds), and reallocating it each time costs page faults.
        s.pristine.clear();
    }
}

// Guest::thread_init: constructs this host thread's local references and buffer copies now, before
// the guest thread's retirement is registered, so they outlive it at thread exit (the guest's TLS
// destructors may call JNI functions; DetachCurrentThread, for one, clears the local references).
void touch_thread_state() {
    (void)t_locals.refs.size();
    (void)t_shadows.list.size();
}

// ---------------------------------------------------------------------------------------------
// Native methods registered by guest code.

struct NativeMethod {
    gaddr fn;
    std::string params;
    char ret;
    std::string name;
    std::atomic<bool> called{false};
    // Unity's per-frame call from Java (UnityPlayer.nativeRender), where tweaks are applied.
    bool render = false;
    // FMOD's audio callback (FMODAudioDevice.fmodProcess: mix the next buffer), timed with stats on
    // and passed on to live view.
    bool audio = false;
    // FMOD's fmodGetInfo: index 0 gives its sample rate, which live view needs.
    bool audio_info = false;
    // Unity's nativeFocusChanged: what the game was last told about the window's focus.
    bool focus = false;
};

#if defined(_WIN32)
// Microsoft's x64 convention: four registers, each argument's position taking an integer one or a vector one.
constexpr int kHostIntRegs = 4, kHostFpRegs = 4;
constexpr bool kPositional = true;
#elif defined(__aarch64__)
constexpr int kHostIntRegs = 8, kHostFpRegs = 8;
constexpr bool kPositional = false;
#elif defined(__x86_64__)
constexpr int kHostIntRegs = 6, kHostFpRegs = 8;
constexpr bool kPositional = false;
#else
#error "unsupported host architecture"
#endif

// What arm32_jni_entry saved: the integer argument registers, then the vector ones (jni_entry_*.S lays them out so).
struct SavedRegs {
    std::uint64_t gpr[kHostIntRegs];
    std::uint64_t fpr[kHostFpRegs];
};

struct DispatchResult {
    std::uint64_t ival;
    std::uint64_t fbits;
};

extern "C" void arm32_jni_entry();

// One stub per method: load the method's context into the scratch register the entry reads,
// and jump to the shared entry.
void write_stub(std::uint8_t* at, NativeMethod* m) {
    auto ctx = reinterpret_cast<std::uint64_t>(m);
    auto entry = reinterpret_cast<std::uint64_t>(&arm32_jni_entry);
#if defined(__aarch64__)
    const std::uint32_t code[4] = {
        0x58000090,  // ldr x16, [pc, #16]
        0x580000b1,  // ldr x17, [pc, #20]
        0xd61f0220,  // br x17
        0xd503201f,  // nop
    };
    std::memcpy(at, code, sizeof code);
    std::memcpy(at + 16, &ctx, 8);
    std::memcpy(at + 24, &entry, 8);
#else
    at[0] = 0x49;  // movabs r10, ctx
    at[1] = 0xba;
    std::memcpy(at + 2, &ctx, 8);
    at[10] = 0x49;  // movabs r11, entry
    at[11] = 0xbb;
    std::memcpy(at + 12, &entry, 8);
    at[20] = 0x41;  // jmp r11
    at[21] = 0xff;
    at[22] = 0xe3;
#endif
}

// A guest function to register as the native method name + signature.
struct GuestNative {
    std::string name, sig;
    gaddr fn;
};

// Registers guest functions as native methods of cls with the host VM, each behind a stub of
// its own that enters arm32_jni_dispatch.
// Stubs made so far, by guest function, name and signature. A library that registers the same
// natives again (each time its activity is made, say) gets the stubs it had, not another code
// page and another set of methods each time.
std::mutex g_natives_lock;
std::map<std::tuple<gaddr, std::string, std::string>, void*> g_native_stubs;

jint register_guest_natives(JNIEnv* e, jclass cls, const std::vector<GuestNative>& list) {
    if (list.empty()) return 0;
    std::vector<JNINativeMethod> table(list.size());
    {
        std::lock_guard<std::mutex> l(g_natives_lock);
        std::vector<std::size_t> fresh;
        for (std::size_t k = 0; k < list.size(); ++k) {
            const GuestNative& g = list[k];
            auto it = g_native_stubs.find(std::make_tuple(g.fn, g.name, g.sig));
            if (it != g_native_stubs.end()) table[k] = JNINativeMethod{g.name.c_str(), g.sig.c_str(), it->second};
            else fresh.push_back(k);
        }
        if (!fresh.empty()) {
            // Executable stubs for the new ones, written while writable, then made executable.
            constexpr std::size_t kSlot = 32;
            std::size_t page = static_cast<std::size_t>(sysconf(_SC_PAGESIZE));
            std::size_t size = (fresh.size() * kSlot + page - 1) / page * page;
            void* code = mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
            if (code == MAP_FAILED) return JNI_ERR;
            for (std::size_t i = 0; i < fresh.size(); ++i) {
                const GuestNative& g = list[fresh[i]];
                auto* m = new NativeMethod{g.fn, {}, 'V', g.name};
                m->render = g.name == "nativeRender";
                m->audio = g.name == "fmodProcess";
                m->audio_info = g.name == "fmodGetInfo";
                m->focus = g.name == "nativeFocusChanged";
                if (g_trace) log("trace: RegisterNatives %s%s -> %#x", g.name.c_str(), g.sig.c_str(), m->fn);
                if (!parse_signature(g.sig, m->params, m->ret)) log("arm32: jni: cannot parse %s %s", g.name.c_str(), g.sig.c_str());
                auto* stub = static_cast<std::uint8_t*>(code) + i * kSlot;
                write_stub(stub, m);
                table[fresh[i]] = JNINativeMethod{g.name.c_str(), g.sig.c_str(), stub};
                g_native_stubs.emplace(std::make_tuple(g.fn, g.name, g.sig), stub);
            }
            mprotect(code, size, PROT_READ | PROT_EXEC);
            __builtin___clear_cache(static_cast<char*>(code), static_cast<char*>(code) + size);
        }
    }
    return e->RegisterNatives(cls, table.data(), static_cast<jint>(table.size()));
}

std::uint64_t jni_RegisterNatives(Thread& t) {
    Words w{t};
    w.u32();
    auto cls = static_cast<jclass>(obj(w.u32()));
    gaddr methods = w.u32();
    auto n = static_cast<jint>(w.u32());
    if (n <= 0) return 0;
    std::vector<GuestNative> list;
    for (jint i = 0; i < n; ++i) {
        gaddr entry = methods + static_cast<gaddr>(i) * 12;
        list.push_back(GuestNative{guest_string(word(entry)), guest_string(word(entry + 4)), word(entry + 8)});
    }
    return static_cast<std::uint32_t>(register_guest_natives(env(), cls, list));
}

// ---------------------------------------------------------------------------------------------
// Native methods the host VM would find by name (Java_<class>_<method>[__<arguments>]).

// The defined function symbols starting with Java_ in a 32-bit ELF file's dynamic symbol table.
std::vector<std::string> java_exports(const std::string& file) {
    std::vector<std::string> out;
    int fd = open(file.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) return out;
    struct stat st {};
    void* map = fstat(fd, &st) == 0 ? mmap(nullptr, static_cast<std::size_t>(st.st_size), PROT_READ, MAP_PRIVATE, fd, 0) : MAP_FAILED;
    close(fd);
    if (map == MAP_FAILED) return out;
    auto* b = static_cast<const std::uint8_t*>(map);
    auto size = static_cast<std::size_t>(st.st_size);
    // Every table must lie inside the file.
    auto inside = [&](std::size_t off, std::size_t len) { return off <= size && len <= size - off; };
    const auto* eh = reinterpret_cast<const Elf32_Ehdr*>(b);
    if (inside(0, sizeof *eh) && std::memcmp(eh->e_ident, ELFMAG, SELFMAG) == 0 && eh->e_ident[EI_CLASS] == ELFCLASS32 &&
        inside(eh->e_shoff, std::size_t{eh->e_shnum} * sizeof(Elf32_Shdr))) {
        const auto* sh = reinterpret_cast<const Elf32_Shdr*>(b + eh->e_shoff);
        for (unsigned i = 0; i < eh->e_shnum; ++i) {
            if (sh[i].sh_type != SHT_DYNSYM || sh[i].sh_link >= eh->e_shnum) continue;
            const Elf32_Shdr& strs = sh[sh[i].sh_link];
            if (!inside(sh[i].sh_offset, sh[i].sh_size) || !inside(strs.sh_offset, strs.sh_size)) continue;
            const auto* syms = reinterpret_cast<const Elf32_Sym*>(b + sh[i].sh_offset);
            const char* names = reinterpret_cast<const char*>(b + strs.sh_offset);
            for (std::size_t k = 0; k < sh[i].sh_size / sizeof(Elf32_Sym); ++k) {
                const Elf32_Sym& s = syms[k];
                if (s.st_shndx == SHN_UNDEF || ELF32_ST_TYPE(s.st_info) != STT_FUNC || s.st_name >= strs.sh_size) continue;
                // The name must end inside the string table.
                const char* name = names + s.st_name;
                std::size_t len = strnlen(name, strs.sh_size - s.st_name);
                if (len < strs.sh_size - s.st_name && std::strncmp(name, "Java_", 5) == 0) out.emplace_back(name, len);
            }
        }
    }
    munmap(map, size);
    return out;
}

// JNI name mangling undone: _1 '_', _2 ';', _3 '[', _0xxxx a UTF-16 unit; a plain '_' is the
// separator, which is '/' in the class and argument parts. "Java_a_B_run__I" gives class "a/B",
// method "run" and arguments "I" (has_args), for overloaded methods.
bool decode_jni_name(const std::string& symbol, std::string& cls, std::string& method, std::string& args, bool& has_args) {
    std::vector<std::string> parts{""};
    std::string* out = &parts.back();
    has_args = false;
    args.clear();
    const std::string s = symbol.substr(5);
    for (std::size_t i = 0; i < s.size(); ++i) {
        char c = s[i];
        if (c != '_') {
            *out += c;
            continue;
        }
        char next = i + 1 < s.size() ? s[i + 1] : '\0';
        if (next == '1' || next == '2' || next == '3') {
            *out += next == '1' ? '_' : next == '2' ? ';' : '[';
            ++i;
        } else if (next == '0') {
            if (i + 6 > s.size()) return false;
            unsigned u = static_cast<unsigned>(std::strtoul(s.substr(i + 2, 4).c_str(), nullptr, 16));
            // Modified UTF-8, as the VM keeps names.
            if (u && u < 0x80) {
                *out += static_cast<char>(u);
            } else if (u < 0x800) {
                *out += static_cast<char>(0xc0 | (u >> 6));
                *out += static_cast<char>(0x80 | (u & 0x3f));
            } else {
                *out += static_cast<char>(0xe0 | (u >> 12));
                *out += static_cast<char>(0x80 | ((u >> 6) & 0x3f));
                *out += static_cast<char>(0x80 | (u & 0x3f));
            }
            i += 5;
        } else if (has_args) {
            *out += '/';
        } else if (next == '_') {
            // "__": the rest is the argument descriptor.
            has_args = true;
            out = &args;
            ++i;
        } else {
            parts.emplace_back();
            out = &parts.back();
        }
    }
    if (parts.size() < 2 || parts.back().empty()) return false;
    method = parts.back();
    cls.clear();
    for (std::size_t k = 0; k + 1 < parts.size(); ++k) cls += (k ? "/" : "") + parts[k];
    return true;
}

// ---------------------------------------------------------------------------------------------
// The other JNIEnv functions.

#define ARM32_JNI(name) std::uint64_t jni_##name(Thread& t)
#define ARGS   \
    Words w{t}; \
    w.u32()

ARM32_JNI(GetVersion) {
    (void)t;
    return static_cast<std::uint32_t>(env()->GetVersion());
}
ARM32_JNI(DefineClass) {
    ARGS;
    std::string name = guest_string(w.u32());
    jobject loader = obj(w.u32());
    gaddr buf = w.u32();
    auto len = static_cast<jsize>(w.u32());
    return local(env()->DefineClass(name.c_str(), loader, reinterpret_cast<const jbyte*>(mem().host(buf)), len));
}
ARM32_JNI(FindClass) {
    ARGS;
    return local(env()->FindClass(guest_string(w.u32()).c_str()));
}
ARM32_JNI(FromReflectedMethod) {
    ARGS;
    jobject m = obj(w.u32());
    JNIEnv* e = env();
    jmethodID id = e->FromReflectedMethod(m);
    if (!id) return 0;
    // Unity's AndroidJavaObject asks for a method this way on every call into Java: the signature
    // (several calls into reflection) is worked out the first time only.
    if (std::uint32_t h = known_method(id)) return h;
    return method_handle(id, reflected_signature(e, m));
}
ARM32_JNI(FromReflectedField) {
    ARGS;
    return field_handle(env()->FromReflectedField(obj(w.u32())));
}
ARM32_JNI(ToReflectedMethod) {
    ARGS;
    auto cls = static_cast<jclass>(obj(w.u32()));
    Method m;
    bool ok = method(w.u32(), m);
    auto is_static = static_cast<jboolean>(w.u32());
    return ok ? local(env()->ToReflectedMethod(cls, m.id, is_static)) : 0;
}
ARM32_JNI(GetSuperclass) {
    ARGS;
    return local(env()->GetSuperclass(static_cast<jclass>(obj(w.u32()))));
}
ARM32_JNI(IsAssignableFrom) {
    ARGS;
    auto a = static_cast<jclass>(obj(w.u32()));
    auto b = static_cast<jclass>(obj(w.u32()));
    return env()->IsAssignableFrom(a, b);
}
ARM32_JNI(ToReflectedField) {
    ARGS;
    auto cls = static_cast<jclass>(obj(w.u32()));
    jfieldID f = field(w.u32());
    auto is_static = static_cast<jboolean>(w.u32());
    return local(env()->ToReflectedField(cls, f, is_static));
}
ARM32_JNI(Throw) {
    ARGS;
    return static_cast<std::uint32_t>(env()->Throw(static_cast<jthrowable>(obj(w.u32()))));
}
ARM32_JNI(ThrowNew) {
    ARGS;
    auto cls = static_cast<jclass>(obj(w.u32()));
    return static_cast<std::uint32_t>(env()->ThrowNew(cls, guest_string(w.u32()).c_str()));
}
ARM32_JNI(ExceptionOccurred) {
    (void)t;
    return local(env()->ExceptionOccurred());
}
ARM32_JNI(ExceptionDescribe) {
    (void)t;
    env()->ExceptionDescribe();
    return 0;
}
ARM32_JNI(ExceptionClear) {
    (void)t;
    env()->ExceptionClear();
    return 0;
}
ARM32_JNI(FatalError) {
    ARGS;
    env()->FatalError(guest_string(w.u32()).c_str());
    return 0;
}
ARM32_JNI(PushLocalFrame) {
    ARGS;
    jint r = env()->PushLocalFrame(static_cast<jint>(w.u32()));
    if (r == 0) push_frame();
    return static_cast<std::uint32_t>(r);
}
ARM32_JNI(PopLocalFrame) {
    ARGS;
    jobject result = env()->PopLocalFrame(obj(w.u32()));
    pop_frame();
    return local(result);
}
ARM32_JNI(NewGlobalRef) {
    ARGS;
    return global(env()->NewGlobalRef(obj(w.u32())), false);
}
ARM32_JNI(DeleteGlobalRef) {
    ARGS;
    std::uint32_t h = w.u32();
    if ((h & kTagMask) != kGlobal) return 0;
    jobject o;
    {
        std::lock_guard<std::mutex> g(g_refs_lock);
        std::uint32_t i = h & ~kTagMask;
        if (i == 0 || i >= g_globals.size() || !g_globals[i]) return 0;
        o = g_globals[i];
        g_globals[i] = nullptr;
        g_globals_free.push_back(i);
    }
    env()->DeleteGlobalRef(o);
    return 0;
}
ARM32_JNI(DeleteLocalRef) {
    ARGS;
    delete_local(w.u32());
    return 0;
}
ARM32_JNI(IsSameObject) {
    ARGS;
    jobject a = obj(w.u32());
    jobject b = obj(w.u32());
    return env()->IsSameObject(a, b);
}
ARM32_JNI(NewLocalRef) {
    ARGS;
    return local(env()->NewLocalRef(obj(w.u32())));
}
ARM32_JNI(EnsureLocalCapacity) {
    ARGS;
    return static_cast<std::uint32_t>(env()->EnsureLocalCapacity(static_cast<jint>(w.u32())));
}
ARM32_JNI(AllocObject) {
    ARGS;
    return local(env()->AllocObject(static_cast<jclass>(obj(w.u32()))));
}
ARM32_JNI(GetObjectClass) {
    ARGS;
    return local(env()->GetObjectClass(obj(w.u32())));
}
ARM32_JNI(IsInstanceOf) {
    ARGS;
    jobject o = obj(w.u32());
    return env()->IsInstanceOf(o, static_cast<jclass>(obj(w.u32())));
}
template <bool Static>
std::uint64_t get_method_id(Thread& t) {
    ARGS;
    auto cls = static_cast<jclass>(obj(w.u32()));
    std::string name = guest_string(w.u32());
    std::string sig = guest_string(w.u32());
    JNIEnv* e = env();
    jmethodID id = Static ? e->GetStaticMethodID(cls, name.c_str(), sig.c_str()) : e->GetMethodID(cls, name.c_str(), sig.c_str());
    return method_handle(id, sig);
}
template <bool Static>
std::uint64_t get_field_id(Thread& t) {
    ARGS;
    auto cls = static_cast<jclass>(obj(w.u32()));
    std::string name = guest_string(w.u32());
    std::string sig = guest_string(w.u32());
    JNIEnv* e = env();
    return field_handle(Static ? e->GetStaticFieldID(cls, name.c_str(), sig.c_str()) : e->GetFieldID(cls, name.c_str(), sig.c_str()));
}
ARM32_JNI(NewString) {
    ARGS;
    gaddr chars = w.u32();
    auto len = static_cast<jsize>(w.u32());
    return local(env()->NewString(reinterpret_cast<const jchar*>(mem().host(chars)), len));
}
ARM32_JNI(GetStringLength) {
    ARGS;
    return static_cast<std::uint32_t>(env()->GetStringLength(static_cast<jstring>(obj(w.u32()))));
}
// GetStringChars / GetStringCritical: a NUL-terminated UTF-16 copy in the guest heap.
ARM32_JNI(GetStringChars) {
    ARGS;
    auto s = static_cast<jstring>(obj(w.u32()));
    gaddr is_copy = w.u32();
    JNIEnv* e = env();
    jsize n = e->GetStringLength(s);
    gaddr g = Guest::get().malloc(static_cast<std::uint32_t>((n + 1) * 2));
    if (!g) return 0;
    e->GetStringRegion(s, 0, n, reinterpret_cast<jchar*>(mem().host(g)));
    *mem().ptr<std::uint16_t>(g + static_cast<gaddr>(n) * 2) = 0;
    if (is_copy) *mem().host(is_copy) = JNI_TRUE;
    return g;
}
ARM32_JNI(ReleaseStringChars) {
    ARGS;
    w.u32();
    Guest::get().free(w.u32());
    return 0;
}
ARM32_JNI(NewStringUTF) {
    ARGS;
    gaddr p = w.u32();
    if (!p) return 0;
    return local(env()->NewStringUTF(reinterpret_cast<const char*>(mem().host(p))));
}
ARM32_JNI(GetStringUTFLength) {
    ARGS;
    return static_cast<std::uint32_t>(env()->GetStringUTFLength(static_cast<jstring>(obj(w.u32()))));
}
ARM32_JNI(GetStringUTFChars) {
    ARGS;
    auto s = static_cast<jstring>(obj(w.u32()));
    gaddr is_copy = w.u32();
    JNIEnv* e = env();
    if (!s) return 0;
    const char* chars = e->GetStringUTFChars(s, nullptr);
    if (!chars) return 0;
    gaddr g = Guest::get().strdup(chars);
    e->ReleaseStringUTFChars(s, chars);
    if (is_copy) *mem().host(is_copy) = JNI_TRUE;
    return g;
}
ARM32_JNI(ReleaseStringUTFChars) {
    ARGS;
    w.u32();
    Guest::get().free(w.u32());
    return 0;
}
ARM32_JNI(GetArrayLength) {
    ARGS;
    return static_cast<std::uint32_t>(env()->GetArrayLength(static_cast<jarray>(obj(w.u32()))));
}
ARM32_JNI(NewObjectArray) {
    ARGS;
    auto n = static_cast<jsize>(w.u32());
    auto cls = static_cast<jclass>(obj(w.u32()));
    jobject init = obj(w.u32());
    return local(env()->NewObjectArray(n, cls, init));
}
ARM32_JNI(GetObjectArrayElement) {
    ARGS;
    auto a = static_cast<jobjectArray>(obj(w.u32()));
    return local(env()->GetObjectArrayElement(a, static_cast<jsize>(w.u32())));
}
ARM32_JNI(SetObjectArrayElement) {
    ARGS;
    auto a = static_cast<jobjectArray>(obj(w.u32()));
    auto i = static_cast<jsize>(w.u32());
    env()->SetObjectArrayElement(a, i, obj(w.u32()));
    return 0;
}
ARM32_JNI(UnregisterNatives) {
    ARGS;
    return static_cast<std::uint32_t>(env()->UnregisterNatives(static_cast<jclass>(obj(w.u32()))));
}
ARM32_JNI(MonitorEnter) {
    ARGS;
    return static_cast<std::uint32_t>(env()->MonitorEnter(obj(w.u32())));
}
ARM32_JNI(MonitorExit) {
    ARGS;
    return static_cast<std::uint32_t>(env()->MonitorExit(obj(w.u32())));
}
ARM32_JNI(GetJavaVM) {
    ARGS;
    gaddr out = w.u32();
    if (out) word(out) = g_guest_vm;
    return 0;
}
ARM32_JNI(GetStringRegion) {
    ARGS;
    auto s = static_cast<jstring>(obj(w.u32()));
    auto start = static_cast<jsize>(w.u32());
    auto n = static_cast<jsize>(w.u32());
    env()->GetStringRegion(s, start, n, reinterpret_cast<jchar*>(mem().host(w.u32())));
    return 0;
}
ARM32_JNI(GetStringUTFRegion) {
    ARGS;
    auto s = static_cast<jstring>(obj(w.u32()));
    auto start = static_cast<jsize>(w.u32());
    auto n = static_cast<jsize>(w.u32());
    env()->GetStringUTFRegion(s, start, n, reinterpret_cast<char*>(mem().host(w.u32())));
    return 0;
}
ARM32_JNI(GetPrimitiveArrayCritical) {
    ARGS;
    auto a = static_cast<jarray>(obj(w.u32()));
    gaddr is_copy = w.u32();
    JNIEnv* e = env();
    if (!a) return 0;
    char type = array_type(e, a);
    jsize n = e->GetArrayLength(a);
    std::size_t bytes = static_cast<std::size_t>(n) * element_size(type);
    gaddr g = Guest::get().malloc(static_cast<std::uint32_t>(bytes ? bytes : 1));
    if (!g) return 0;
    region(e, type, a, 0, n, mem().host(g), false);
    {
        std::lock_guard<std::mutex> l(g_critical_lock);
        g_critical[g] = Critical{e->NewGlobalRef(a), type};
    }
    if (is_copy) *mem().host(is_copy) = JNI_TRUE;
    return g;
}
ARM32_JNI(ReleasePrimitiveArrayCritical) {
    ARGS;
    w.u32();
    gaddr g = w.u32();
    auto mode = static_cast<jint>(w.u32());
    Critical c{};
    {
        std::lock_guard<std::mutex> l(g_critical_lock);
        auto it = g_critical.find(g);
        if (it == g_critical.end()) return 0;
        c = it->second;
        if (mode != JNI_COMMIT) g_critical.erase(it);
    }
    JNIEnv* e = env();
    auto a = static_cast<jarray>(c.array);
    if (mode != JNI_ABORT) region(e, c.type, a, 0, e->GetArrayLength(a), mem().host(g), true);
    if (mode != JNI_COMMIT) {
        e->DeleteGlobalRef(c.array);
        Guest::get().free(g);
    }
    return 0;
}
ARM32_JNI(NewWeakGlobalRef) {
    ARGS;
    return global(env()->NewWeakGlobalRef(obj(w.u32())), true);
}
ARM32_JNI(DeleteWeakGlobalRef) {
    ARGS;
    std::uint32_t h = w.u32();
    if ((h & kTagMask) != kWeak) return 0;
    jobject o;
    {
        std::lock_guard<std::mutex> g(g_refs_lock);
        std::uint32_t i = h & ~kTagMask;
        if (i == 0 || i >= g_weaks.size() || !g_weaks[i]) return 0;
        o = g_weaks[i];
        g_weaks[i] = nullptr;
        g_weaks_free.push_back(i);
    }
    env()->DeleteWeakGlobalRef(static_cast<jweak>(o));
    return 0;
}
ARM32_JNI(ExceptionCheck) {
    (void)t;
    return env()->ExceptionCheck();
}
ARM32_JNI(NewDirectByteBuffer) {
    ARGS;
    gaddr address = w.u32();
    auto capacity = static_cast<jlong>(w.u64());
    return local(env()->NewDirectByteBuffer(mem().host(address), capacity));
}
ARM32_JNI(GetDirectBufferAddress) {
    ARGS;
    jobject b = obj(w.u32());
    JNIEnv* e = env();
    auto* h = static_cast<std::uint8_t*>(e->GetDirectBufferAddress(b));
    if (!h) return 0;
    // A buffer over guest memory needs no copy.
    if (h >= mem().base() && h < mem().base() + (std::uint64_t{1} << 32)) return static_cast<gaddr>(h - mem().base());
    // An exception the guest left pending stays pending, as JNI does not touch it here: it is
    // set aside for the call into Java below and thrown again after.
    jthrowable pending = e->ExceptionOccurred();
    if (pending) e->ExceptionClear();
    struct BufferApi {
        jmethodID is_read_only;
        // The view classes whose capacity counts elements wider than a byte, by size shift.
        std::array<std::pair<jclass, int>, 6> wide;
    };
    static const BufferApi api = [e] {
        jclass buffer = e->FindClass("java/nio/Buffer");
        jmethodID ro = e->GetMethodID(buffer, "isReadOnly", "()Z");
        e->DeleteLocalRef(buffer);
        return BufferApi{ro, {{{global_class(e, "java/nio/CharBuffer"), 1}, {global_class(e, "java/nio/ShortBuffer"), 1},
                               {global_class(e, "java/nio/IntBuffer"), 2}, {global_class(e, "java/nio/FloatBuffer"), 2},
                               {global_class(e, "java/nio/LongBuffer"), 3}, {global_class(e, "java/nio/DoubleBuffer"), 3}}}};
    }();
    bool writable = !e->CallBooleanMethod(b, api.is_read_only);
    if (e->ExceptionCheck()) {
        e->ExceptionClear();
        writable = false;
    }
    // The capacity counts elements: a float view of a direct buffer (asFloatBuffer) spans four
    // bytes per element, and a copy of one byte each left the guest writing past its end.
    int shift = 0;
    for (const auto& [c, s] : api.wide) {
        if (e->IsInstanceOf(b, c)) {
            shift = s;
            break;
        }
    }
    auto bytes = static_cast<std::size_t>(e->GetDirectBufferCapacity(b)) << shift;
    if (pending) {
        e->Throw(pending);
        e->DeleteLocalRef(pending);
    }
    return shadow_for(h, bytes, writable);
}
ARM32_JNI(GetDirectBufferCapacity) {
    ARGS;
    return static_cast<std::uint64_t>(env()->GetDirectBufferCapacity(obj(w.u32())));
}
ARM32_JNI(GetObjectRefType) {
    ARGS;
    switch (w.u32() & kTagMask) {
    case kLocal: return JNILocalRefType;
    case kGlobal: return JNIGlobalRefType;
    case kWeak: return JNIWeakGlobalRefType;
    default: return JNIInvalidRefType;
    }
}

// Unimplemented functions say which one was called; the stub index follows from the pc.
std::uint64_t jni_unsupported(Thread& t) {
    std::uint32_t index = (t.call_reg(15) - g_stubs) / kStubSize;
    log("arm32: jni: function %u is not supported", index);
    return 0;
}

// ---------------------------------------------------------------------------------------------
// JavaVM functions.

std::uint64_t vm_DestroyJavaVM(Thread&) { return static_cast<std::uint32_t>(JNI_ERR); }

template <bool Daemon>
std::uint64_t vm_AttachCurrentThread(Thread& t) {
    Words w{t};
    w.u32();
    gaddr penv = w.u32();
    gaddr args = w.u32();
    JavaVMAttachArgs a{JNI_VERSION_1_6, nullptr, nullptr};
    std::string name;
    if (args) {
        a.version = static_cast<jint>(word(args));
        name = guest_string(word(args + 4));
        a.name = name.empty() ? nullptr : name.c_str();
        a.group = obj(word(args + 8));
    }
    JNIEnv* e = nullptr;
    jint r = Daemon ? g_vm->AttachCurrentThreadAsDaemon(&e, args ? &a : nullptr) : g_vm->AttachCurrentThread(&e, args ? &a : nullptr);
    if (r == JNI_OK) {
        t_env = e;
        if (penv) word(penv) = g_guest_env;
    }
    return static_cast<std::uint32_t>(r);
}

std::uint64_t vm_DetachCurrentThread(Thread&) {
    jint r = g_vm->DetachCurrentThread();
    t_env = nullptr;
    t_locals = Locals{};
    return static_cast<std::uint32_t>(r);
}

std::uint64_t vm_GetEnv(Thread& t) {
    Words w{t};
    w.u32();
    gaddr penv = w.u32();
    auto version = static_cast<jint>(w.u32());
    JNIEnv* e = nullptr;
    jint r = g_vm->GetEnv(reinterpret_cast<void**>(&e), version);
    if (r == JNI_OK) t_env = e;
    if (penv) word(penv) = r == JNI_OK ? g_guest_env : 0;
    return static_cast<std::uint32_t>(r);
}

// Writes the trap stub for host function `number` at guest address `at`.
void write_guest_stub(gaddr at, std::uint32_t number) {
    std::uint32_t lo = number & 0xffff, hi = number >> 16;
    const std::uint32_t code[5] = {
        0xe92d4080,                                                    // push {r7, lr}
        0xe3007000 | ((lo & 0xf000) << 4) | (lo & 0xfff),              // movw r7, #lo
        0xe3407000 | ((hi & 0xf000) << 4) | (hi & 0xfff),              // movt r7, #hi
        0xef000000,                                                    // svc 0
        0xe8bd8080,                                                    // pop {r7, pc}
    };
    std::memcpy(mem().host(at), code, sizeof code);
}

}  // namespace

// What Unity's game code last heard about the window's focus (see focus_watch.cpp).
std::atomic<bool> g_game_focus{false};

// FMOD's output rate, for live view, when it plays through its Java class.
std::atomic<int> g_fmod_rate{0};

extern "C" DispatchResult arm32_jni_dispatch(NativeMethod* m, SavedRegs* r, std::uint8_t* stack) {
    if (g_trace && !m->called.exchange(true)) log("trace: first call of native %s", m->name.c_str());
    jni_set_env(reinterpret_cast<JNIEnv*>(r->gpr[0]));
    Thread* tp = Guest::get().try_current();
    if (!tp) {
        // A new Java thread the agent could not give a guest thread to (logged): the call fails
        // in Java with an exception instead of hanging the thread.
        JNIEnv* e = reinterpret_cast<JNIEnv*>(r->gpr[0]);
        if (jclass c = e->FindClass("java/lang/OutOfMemoryError")) e->ThrowNew(c, "arm32: no guest thread for this thread");
        return DispatchResult{0, 0};
    }
    Thread& t = *tp;
    ++t.n_native_calls;
    if (m->render) tweaks_render(t);
    if (m->focus) g_game_focus.store(r->gpr[2] & 1, std::memory_order_relaxed);
    const std::size_t frames_at_entry = t_locals.frames.size();
    push_frame();
    int depth = ++t_native_depth;
    // Guest arguments: JNIEnv, this or the class, then the parameters (AAPCS: 64-bit values at
    // even word positions).
    std::vector<std::uint32_t> words;
    words.push_back(g_guest_env);
    words.push_back(local(reinterpret_cast<jobject>(r->gpr[1])));
    // JNIEnv and the object took the first two registers; on Windows they took the first two positions of either kind.
    int gi = 2, fi = kPositional ? 2 : 0;
    std::uint8_t* sp = stack;
    auto next_int = [&]() -> std::uint64_t {
        if (gi < kHostIntRegs) {
            std::uint64_t v = r->gpr[gi++];
            if (kPositional) fi = gi;
            return v;
        }
        std::uint64_t v;
        std::memcpy(&v, sp, 8);
        sp += 8;
        return v;
    };
    auto next_fp = [&]() -> std::uint64_t {
        if (fi < kHostFpRegs) {
            std::uint64_t v = r->fpr[fi++];
            if (kPositional) gi = fi;
            return v;
        }
        std::uint64_t v;
        std::memcpy(&v, sp, 8);
        sp += 8;
        return v;
    };
    auto put64 = [&](std::uint64_t v) {
        if (words.size() & 1) words.push_back(0);
        words.push_back(static_cast<std::uint32_t>(v));
        words.push_back(static_cast<std::uint32_t>(v >> 32));
    };
    jobject mix_buffer = nullptr;
    for (char c : m->params) {
        switch (c) {
        case 'J': put64(next_int()); break;
        case 'D': put64(next_fp()); break;
        case 'F': words.push_back(static_cast<std::uint32_t>(next_fp())); break;
        case 'Z': words.push_back(static_cast<std::uint8_t>(next_int())); break;
        case 'C': words.push_back(static_cast<std::uint16_t>(next_int())); break;
        case 'B': words.push_back(static_cast<std::uint32_t>(static_cast<std::int32_t>(static_cast<std::int8_t>(next_int())))); break;
        case 'S': words.push_back(static_cast<std::uint32_t>(static_cast<std::int32_t>(static_cast<std::int16_t>(next_int())))); break;
        case 'I': words.push_back(static_cast<std::uint32_t>(next_int())); break;
        default: {
            auto object = reinterpret_cast<jobject>(next_int());
            if (m->audio) mix_buffer = object;
            words.push_back(local(object));
            break;
        }
        }
    }
    // The audio mix has to keep up with playback: with stats on, how long each one takes.
    const bool timed = m->audio && g_stats;
    const auto mix_start = timed ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};
    std::uint64_t v = t.call(m->fn, words.data(), words.size());
    if (timed) note_audio(mix_start);
    if (m->audio_info && words.size() > 2 && words[2] == 0) g_fmod_rate.store(static_cast<int>(v), std::memory_order_relaxed);
    DispatchResult res{0, 0};
    switch (m->ret) {
    case 'V': break;
    case 'Z': res.ival = v & 0xff ? 1 : 0; break;
    case 'B': res.ival = static_cast<std::uint64_t>(static_cast<std::int64_t>(static_cast<std::int8_t>(v))); break;
    case 'C': res.ival = v & 0xffff; break;
    case 'S': res.ival = static_cast<std::uint64_t>(static_cast<std::int64_t>(static_cast<std::int16_t>(v))); break;
    case 'I': res.ival = static_cast<std::uint64_t>(static_cast<std::int64_t>(static_cast<std::int32_t>(v))); break;
    case 'J': res.ival = v; break;
    case 'F': res.fbits = v & 0xffffffff; break;
    case 'D': res.fbits = v; break;
    default: res.ival = reinterpret_cast<std::uint64_t>(obj(static_cast<std::uint32_t>(v))); break;
    }
    sync_shadows(depth);
    // After the sync: a direct buffer's mix is in its host memory only now.
    if (m->audio && mix_buffer) {
        live_audio_source(m, g_fmod_rate.load(std::memory_order_relaxed), 2, 16);
        // FMOD's Java output (phones where it does not use OpenSL): 16-bit stereo in a direct buffer.
        auto* env = reinterpret_cast<JNIEnv*>(r->gpr[0]);
        live_audio(m, env->GetDirectBufferAddress(mix_buffer), static_cast<std::size_t>(env->GetDirectBufferCapacity(mix_buffer)));
    }
    --t_native_depth;
    // The VM ends every local frame the method pushed when it returns, ones it left open too;
    // the table follows (popping just one left the rest, and the table grew with every call).
    while (t_locals.frames.size() > frames_at_entry) pop_frame();
    return res;
}

void jni_set_env(JNIEnv* e) { t_env = e; }
bool jni_game_has_focus() { return g_game_focus.load(std::memory_order_relaxed); }

JNIEnv* jni_env() { return env(); }
jobject jni_object(std::uint32_t handle) { return obj(handle); }
gaddr jni_guest_vm() { return g_guest_vm; }
gaddr jni_guest_env() { return g_guest_env; }

void jni_bind_exports(JNIEnv* e, gaddr handle, const std::string& file) {
    // Long names (with arguments) name one overload and take precedence over short names.
    std::map<std::tuple<std::string, std::string, std::string>, gaddr> bound;  // class, method, signature
    std::vector<std::string> exports = java_exports(file);
    std::stable_sort(exports.begin(), exports.end(), [](const std::string& a, const std::string& b) {
        return (a.find("__", 5) != std::string::npos) > (b.find("__", 5) != std::string::npos);
    });
    jclass class_class = e->FindClass("java/lang/Class");
    jclass method_class = e->FindClass("java/lang/reflect/Method");
    jmethodID declared = e->GetMethodID(class_class, "getDeclaredMethods", "()[Ljava/lang/reflect/Method;");
    jmethodID get_name = e->GetMethodID(method_class, "getName", "()Ljava/lang/String;");
    jmethodID get_mods = e->GetMethodID(method_class, "getModifiers", "()I");
    for (const std::string& symbol : exports) {
        std::string cls, method, args;
        bool has_args;
        if (!decode_jni_name(symbol, cls, method, args, has_args)) continue;
        // The class through the loader of the library being loaded (JNI_OnLoad's context).
        jclass c = e->FindClass(cls.c_str());
        if (!c) {
            e->ExceptionClear();
            if (g_trace) log("trace: %s: no class %s", symbol.c_str(), cls.c_str());
            continue;
        }
        gaddr fn = Guest::get().dlsym(handle, symbol);
        auto methods = static_cast<jobjectArray>(e->CallObjectMethod(c, declared));
        if (e->ExceptionCheck() || !methods) {
            e->ExceptionClear();
            e->DeleteLocalRef(c);
            continue;
        }
        // Every native method of that name (the short form binds any overload) whose
        // arguments match the long form.
        for (jsize i = 0; i < e->GetArrayLength(methods); ++i) {
            jobject m = e->GetObjectArrayElement(methods, i);
            auto name_obj = static_cast<jstring>(e->CallObjectMethod(m, get_name));
            const char* chars = e->GetStringUTFChars(name_obj, nullptr);
            bool same = method == chars;
            e->ReleaseStringUTFChars(name_obj, chars);
            e->DeleteLocalRef(name_obj);
            if (same && (e->CallIntMethod(m, get_mods) & 0x100 /* Modifier.NATIVE */)) {
                std::string sig = reflected_signature(e, m);
                if (!has_args || sig.compare(0, args.size() + 2, "(" + args + ")") == 0) bound.emplace(std::make_tuple(cls, method, sig), fn);
            }
            e->DeleteLocalRef(m);
        }
        e->DeleteLocalRef(methods);
        e->DeleteLocalRef(c);
    }
    // One registration per class.
    std::map<std::string, std::vector<GuestNative>> by_class;
    for (const auto& [key, fn] : bound) by_class[std::get<0>(key)].push_back(GuestNative{std::get<1>(key), std::get<2>(key), fn});
    for (const auto& [cls, list] : by_class) {
        jclass c = e->FindClass(cls.c_str());
        if (c && register_guest_natives(e, c, list) != JNI_OK) log("arm32: jni: cannot bind the natives of %s", cls.c_str());
        e->ExceptionClear();
        if (c) e->DeleteLocalRef(c);
    }
    e->DeleteLocalRef(method_class);
    e->DeleteLocalRef(class_class);
}

void jni_init(JavaVM* vm) {
    g_vm = vm;
    Guest::get().thread_init = &touch_thread_state;
    Guest::get().thread_fini = &release_thread_state;
    Memory& m = mem();
    // Stubs: one per JNIEnv function, then one per JavaVM function.
    std::uint32_t stub_bytes = static_cast<std::uint32_t>((kEnvCount + kVmCount) * kStubSize);
    g_stubs = static_cast<gaddr>(m.map(0, stub_bytes, kProtRead | kProtExec, false, "[jni stubs]"));
    // Tables, then the JNIEnv and JavaVM objects (each a pointer to its table).
    std::uint32_t table_bytes = static_cast<std::uint32_t>((kEnvCount + kVmCount + 2) * 4);
    auto tables = static_cast<gaddr>(m.map(0, table_bytes, kProtRead | kProtWrite, false, "[jni tables]"));
    gaddr env_table = tables;
    gaddr vm_table = tables + static_cast<gaddr>(kEnvCount * 4);
    g_guest_env = vm_table + static_cast<gaddr>(kVmCount * 4);
    g_guest_vm = g_guest_env + 4;
    word(g_guest_env) = env_table;
    word(g_guest_vm) = vm_table;
    for (std::size_t i = 0; i < kEnvCount; ++i) {
        gaddr stub = g_stubs + static_cast<gaddr>(i * kStubSize);
        write_guest_stub(stub, kEnvBase + static_cast<std::uint32_t>(i));
        word(env_table + static_cast<gaddr>(i * 4)) = i < 4 ? 0 : stub;  // the first four are reserved
        register_host_fn(kEnvBase + static_cast<std::uint32_t>(i), &jni_unsupported);
    }
    for (std::size_t i = 0; i < kVmCount; ++i) {
        gaddr stub = g_stubs + static_cast<gaddr>((kEnvCount + i) * kStubSize);
        write_guest_stub(stub, kVmBase + static_cast<std::uint32_t>(i));
        word(vm_table + static_cast<gaddr>(i * 4)) = i < 3 ? 0 : stub;
    }

    auto reg = [](std::size_t index, HostFn fn) { register_host_fn(kEnvBase + static_cast<std::uint32_t>(index), fn); };
#define ARM32_REG(name) reg(ENV_INDEX(name), &jni_##name)
    ARM32_REG(GetVersion);
    ARM32_REG(DefineClass);
    ARM32_REG(FindClass);
    ARM32_REG(FromReflectedMethod);
    ARM32_REG(FromReflectedField);
    ARM32_REG(ToReflectedMethod);
    ARM32_REG(GetSuperclass);
    ARM32_REG(IsAssignableFrom);
    ARM32_REG(ToReflectedField);
    ARM32_REG(Throw);
    ARM32_REG(ThrowNew);
    ARM32_REG(ExceptionOccurred);
    ARM32_REG(ExceptionDescribe);
    ARM32_REG(ExceptionClear);
    ARM32_REG(FatalError);
    ARM32_REG(PushLocalFrame);
    ARM32_REG(PopLocalFrame);
    ARM32_REG(NewGlobalRef);
    ARM32_REG(DeleteGlobalRef);
    ARM32_REG(DeleteLocalRef);
    ARM32_REG(IsSameObject);
    ARM32_REG(NewLocalRef);
    ARM32_REG(EnsureLocalCapacity);
    ARM32_REG(AllocObject);
    ARM32_REG(GetObjectClass);
    ARM32_REG(IsInstanceOf);
    ARM32_REG(NewString);
    ARM32_REG(GetStringLength);
    ARM32_REG(GetStringChars);
    ARM32_REG(ReleaseStringChars);
    ARM32_REG(NewStringUTF);
    ARM32_REG(GetStringUTFLength);
    ARM32_REG(GetStringUTFChars);
    ARM32_REG(ReleaseStringUTFChars);
    ARM32_REG(GetArrayLength);
    ARM32_REG(NewObjectArray);
    ARM32_REG(GetObjectArrayElement);
    ARM32_REG(SetObjectArrayElement);
    ARM32_REG(RegisterNatives);
    ARM32_REG(UnregisterNatives);
    ARM32_REG(MonitorEnter);
    ARM32_REG(MonitorExit);
    ARM32_REG(GetJavaVM);
    ARM32_REG(GetStringRegion);
    ARM32_REG(GetStringUTFRegion);
    ARM32_REG(GetPrimitiveArrayCritical);
    ARM32_REG(ReleasePrimitiveArrayCritical);
    ARM32_REG(NewWeakGlobalRef);
    ARM32_REG(DeleteWeakGlobalRef);
    ARM32_REG(ExceptionCheck);
    ARM32_REG(NewDirectByteBuffer);
    ARM32_REG(GetDirectBufferAddress);
    ARM32_REG(GetDirectBufferCapacity);
    ARM32_REG(GetObjectRefType);
#undef ARM32_REG
    // GetStringCritical and ReleaseStringCritical behave like GetStringChars here.
    reg(ENV_INDEX(GetStringCritical), &jni_GetStringChars);
    reg(ENV_INDEX(ReleaseStringCritical), &jni_ReleaseStringChars);
    reg(ENV_INDEX(GetMethodID), &get_method_id<false>);
    reg(ENV_INDEX(GetStaticMethodID), &get_method_id<true>);
    reg(ENV_INDEX(GetFieldID), &get_field_id<false>);
    reg(ENV_INDEX(GetStaticFieldID), &get_field_id<true>);
    reg(ENV_INDEX(NewObject), &new_object<kDots>);
    reg(ENV_INDEX(NewObjectV), &new_object<kVa>);
    reg(ENV_INDEX(NewObjectA), &new_object<kArray>);
    register_calls<kVirtual, kDots>(ENV_INDEX(CallObjectMethod), std::make_index_sequence<10>{});
    register_calls<kVirtual, kVa>(ENV_INDEX(CallObjectMethod), std::make_index_sequence<10>{});
    register_calls<kVirtual, kArray>(ENV_INDEX(CallObjectMethod), std::make_index_sequence<10>{});
    register_calls<kNonvirtual, kDots>(ENV_INDEX(CallNonvirtualObjectMethod), std::make_index_sequence<10>{});
    register_calls<kNonvirtual, kVa>(ENV_INDEX(CallNonvirtualObjectMethod), std::make_index_sequence<10>{});
    register_calls<kNonvirtual, kArray>(ENV_INDEX(CallNonvirtualObjectMethod), std::make_index_sequence<10>{});
    register_calls<kStatic, kDots>(ENV_INDEX(CallStaticObjectMethod), std::make_index_sequence<10>{});
    register_calls<kStatic, kVa>(ENV_INDEX(CallStaticObjectMethod), std::make_index_sequence<10>{});
    register_calls<kStatic, kArray>(ENV_INDEX(CallStaticObjectMethod), std::make_index_sequence<10>{});
    register_fields<false>(ENV_INDEX(GetObjectField), ENV_INDEX(SetObjectField), std::make_index_sequence<9>{});
    register_fields<true>(ENV_INDEX(GetStaticObjectField), ENV_INDEX(SetStaticObjectField), std::make_index_sequence<9>{});
    register_arrays(std::make_index_sequence<8>{});
    // The families above rely on the standard order inside each block of the table.
    static_assert(ENV_INDEX(CallVoidMethodA) == ENV_INDEX(CallObjectMethod) + 29);
    static_assert(ENV_INDEX(CallStaticVoidMethodA) == ENV_INDEX(CallStaticObjectMethod) + 29);
    static_assert(ENV_INDEX(SetDoubleField) == ENV_INDEX(SetObjectField) + 8);
    static_assert(ENV_INDEX(SetDoubleArrayRegion) == ENV_INDEX(SetBooleanArrayRegion) + 7);

    register_host_fn(kVmBase + VM_INDEX(DestroyJavaVM), &vm_DestroyJavaVM);
    register_host_fn(kVmBase + VM_INDEX(AttachCurrentThread), &vm_AttachCurrentThread<false>);
    register_host_fn(kVmBase + VM_INDEX(DetachCurrentThread), &vm_DetachCurrentThread);
    register_host_fn(kVmBase + VM_INDEX(GetEnv), &vm_GetEnv);
    register_host_fn(kVmBase + VM_INDEX(AttachCurrentThreadAsDaemon), &vm_AttachCurrentThread<true>);
}

jint jni_call_onload(gaddr fn) {
    JNIEnv* e = nullptr;
    g_vm->GetEnv(reinterpret_cast<void**>(&e), JNI_VERSION_1_6);
    jni_set_env(e);
    Thread& t = Guest::get().current();
    const std::size_t frames_at_entry = t_locals.frames.size();
    push_frame();
    int depth = ++t_native_depth;
    auto version = static_cast<jint>(t.call(fn, {g_guest_vm, 0}));
    sync_shadows(depth);
    --t_native_depth;
    // Local frames JNI_OnLoad left open end with it, as in a native method.
    while (t_locals.frames.size() > frames_at_entry) pop_frame();
    return version;
}

}  // namespace arm32
