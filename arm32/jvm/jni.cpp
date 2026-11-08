// The JNI function tables: every JNIEnv and JavaVM function, on the VM's objects and references. Native code reaches
// them through the JNIEnv and JavaVM it is given; the runtime's JNI bridge calls them for the 32-bit game code.
//
// The tables use designated initializers: the compiler checks each function's name and place against jni.h.
#include "internal.h"

#include <cstdarg>
#include <cstdlib>
#include <cstring>

namespace jvm {

namespace {

// ---------------------------------------------------------------------------------------------------------------------
// From JNI's handles to the VM's objects and back.

Env& E(JNIEnv* e) { return *Env::from(e); }
Object* O(jobject r) { return Env::deref(r); }
template <class T>
T* As(jobject r) {
    return dynamic_cast<T*>(O(r));
}
Class* C(jclass c) { return dynamic_cast<Class*>(O(c)); }
Method* M(jmethodID m) { return reinterpret_cast<Method*>(m); }
Field* F(jfieldID f) { return reinterpret_cast<Field*>(f); }
// A new local reference, cast to the handle type the function returns.
template <class T = jobject>
T L(JNIEnv* e, Object* o) {
    return static_cast<T>(E(e).local(o));
}

// Makes exc the thread's pending exception; JNI functions that fail this way return zero or null.
void raise(JNIEnv* e, std::string_view cls, const std::string& message) { E(e).pending = exception(cls, message); }

// ---------------------------------------------------------------------------------------------------------------------
// Arguments: from "..." and va_list (where float arrives promoted to double and narrow integers to int), or from a
// jvalue array, to Values.

std::vector<Value> from_va(const Method* m, va_list ap) {
    std::vector<Value> out;
    if (!m) return out;
    out.reserve(m->params.size());
    for (char t : m->params) {
        switch (t) {
        case 'Z': out.push_back(Value::Z(va_arg(ap, int) != 0)); break;
        case 'B': out.push_back(Value::B(static_cast<jbyte>(va_arg(ap, int)))); break;
        case 'C': out.push_back(Value::C(static_cast<jchar>(va_arg(ap, int)))); break;
        case 'S': out.push_back(Value::S(static_cast<jshort>(va_arg(ap, int)))); break;
        case 'I': out.push_back(Value::I(va_arg(ap, jint))); break;
        case 'J': out.push_back(Value::J(va_arg(ap, jlong))); break;
        case 'F': out.push_back(Value::F(static_cast<jfloat>(va_arg(ap, double)))); break;
        case 'D': out.push_back(Value::D(va_arg(ap, double))); break;
        default: out.push_back(Value(O(va_arg(ap, jobject)))); break;
        }
    }
    return out;
}

std::vector<Value> from_array(const Method* m, const jvalue* a) {
    std::vector<Value> out;
    if (!m) return out;
    out.reserve(m->params.size());
    for (std::size_t k = 0; k < m->params.size(); ++k) {
        // A method with parameters called without an array: zeros, rather than reading through null.
        if (!a) {
            out.emplace_back();
            continue;
        }
        switch (m->params[k]) {
        case 'Z': out.push_back(Value::Z(a[k].z)); break;
        case 'B': out.push_back(Value::B(a[k].b)); break;
        case 'C': out.push_back(Value::C(a[k].c)); break;
        case 'S': out.push_back(Value::S(a[k].s)); break;
        case 'I': out.push_back(Value::I(a[k].i)); break;
        case 'J': out.push_back(Value::J(a[k].j)); break;
        case 'F': out.push_back(Value::F(a[k].f)); break;
        case 'D': out.push_back(Value::D(a[k].d)); break;
        default: out.push_back(Value(O(a[k].l))); break;
        }
    }
    return out;
}

// A result as the function's return type: objects as new local references.
template <class T>
T ret(JNIEnv* e, const Value& v);
template <>
jobject ret<jobject>(JNIEnv* e, const Value& v) {
    return L(e, v.l());
}
template <>
jboolean ret<jboolean>(JNIEnv*, const Value& v) {
    return v.z();
}
template <>
jbyte ret<jbyte>(JNIEnv*, const Value& v) {
    return v.b();
}
template <>
jchar ret<jchar>(JNIEnv*, const Value& v) {
    return v.c();
}
template <>
jshort ret<jshort>(JNIEnv*, const Value& v) {
    return v.s();
}
template <>
jint ret<jint>(JNIEnv*, const Value& v) {
    return v.i();
}
template <>
jlong ret<jlong>(JNIEnv*, const Value& v) {
    return v.j();
}
template <>
jfloat ret<jfloat>(JNIEnv*, const Value& v) {
    return v.f();
}
template <>
jdouble ret<jdouble>(JNIEnv*, const Value& v) {
    return v.d();
}
template <>
void ret<void>(JNIEnv*, const Value&) {}

// A C value as a Value, for the Set*Field functions.
Value val(jobject v) { return Value(O(v)); }
Value val(jboolean v) { return Value::Z(v); }
Value val(jbyte v) { return Value::B(v); }
Value val(jchar v) { return Value::C(v); }
Value val(jshort v) { return Value::S(v); }
Value val(jint v) { return Value::I(v); }
Value val(jlong v) { return Value::J(v); }
Value val(jfloat v) { return Value::F(v); }
Value val(jdouble v) { return Value::D(v); }

// ---------------------------------------------------------------------------------------------------------------------
// The three kinds of call.

// Call<Type>Method: virtual dispatch on the object's class.
Value virtual_call(JNIEnv* e, jobject o, jmethodID m, const std::vector<Value>& args) {
    if (!m) {
        log("jvm: Call*Method with a null method");
        return {};
    }
    return E(e).call(*M(m), O(o), args.data(), args.size());
}

// CallNonvirtual<Type>Method: the method as the given class has it (a subclass calling its superclass's).
Value nonvirtual_call(JNIEnv* e, jobject o, jclass c, jmethodID m, const std::vector<Value>& args) {
    if (!m) {
        log("jvm: CallNonvirtual*Method with a null method");
        return {};
    }
    Class* cls = C(c);
    Method* impl = cls ? cls->resolve(M(m)) : M(m);
    return E(e).invoke(*impl, O(o), args.data(), args.size());
}

// CallStatic<Type>Method.
Value static_call(JNIEnv* e, jmethodID m, const std::vector<Value>& args) {
    if (!m) {
        log("jvm: CallStatic*Method with a null method");
        return {};
    }
    return E(e).invoke(*M(m), nullptr, args.data(), args.size());
}

// Each return type's nine call functions: three kinds, each with "...", va_list and jvalue[] arguments.
#define JVM_CALLS(Name, T)                                                                                             \
    T Call##Name##Method(JNIEnv* e, jobject o, jmethodID m, ...) {                                                   \
        va_list ap;                                                                                                    \
        va_start(ap, m);                                                                                               \
        std::vector<Value> args = from_va(M(m), ap);                                                                   \
        va_end(ap);                                                                                                    \
        return ret<T>(e, virtual_call(e, o, m, args));                                                                 \
    }                                                                                                                  \
    T Call##Name##MethodV(JNIEnv* e, jobject o, jmethodID m, va_list ap) { return ret<T>(e, virtual_call(e, o, m, from_va(M(m), ap))); } \
    T Call##Name##MethodA(JNIEnv* e, jobject o, jmethodID m, const jvalue* a) {                                      \
        return ret<T>(e, virtual_call(e, o, m, from_array(M(m), a)));                                                  \
    }                                                                                                                  \
    T CallNonvirtual##Name##Method(JNIEnv* e, jobject o, jclass c, jmethodID m, ...) {                                \
        va_list ap;                                                                                                    \
        va_start(ap, m);                                                                                               \
        std::vector<Value> args = from_va(M(m), ap);                                                                   \
        va_end(ap);                                                                                                    \
        return ret<T>(e, nonvirtual_call(e, o, c, m, args));                                                           \
    }                                                                                                                  \
    T CallNonvirtual##Name##MethodV(JNIEnv* e, jobject o, jclass c, jmethodID m, va_list ap) {                        \
        return ret<T>(e, nonvirtual_call(e, o, c, m, from_va(M(m), ap)));                                              \
    }                                                                                                                  \
    T CallNonvirtual##Name##MethodA(JNIEnv* e, jobject o, jclass c, jmethodID m, const jvalue* a) {                   \
        return ret<T>(e, nonvirtual_call(e, o, c, m, from_array(M(m), a)));                                            \
    }                                                                                                                  \
    T CallStatic##Name##Method(JNIEnv* e, jclass, jmethodID m, ...) {                                                 \
        va_list ap;                                                                                                    \
        va_start(ap, m);                                                                                               \
        std::vector<Value> args = from_va(M(m), ap);                                                                   \
        va_end(ap);                                                                                                    \
        return ret<T>(e, static_call(e, m, args));                                                                     \
    }                                                                                                                  \
    T CallStatic##Name##MethodV(JNIEnv* e, jclass, jmethodID m, va_list ap) { return ret<T>(e, static_call(e, m, from_va(M(m), ap))); } \
    T CallStatic##Name##MethodA(JNIEnv* e, jclass, jmethodID m, const jvalue* a) {                                   \
        return ret<T>(e, static_call(e, m, from_array(M(m), a)));                                                      \
    }

JVM_CALLS(Object, jobject)
JVM_CALLS(Boolean, jboolean)
JVM_CALLS(Byte, jbyte)
JVM_CALLS(Char, jchar)
JVM_CALLS(Short, jshort)
JVM_CALLS(Int, jint)
JVM_CALLS(Long, jlong)
JVM_CALLS(Float, jfloat)
JVM_CALLS(Double, jdouble)
JVM_CALLS(Void, void)

// ---------------------------------------------------------------------------------------------------------------------
// Fields.

Value get_field(JNIEnv* e, jobject o, jfieldID f) {
    Object* obj = O(o);
    if (!obj || !f) {
        raise(e, "java/lang/NullPointerException", "field read on null");
        return {};
    }
    return obj->field(F(f));
}

void set_field(JNIEnv* e, jobject o, jfieldID f, const Value& v) {
    Object* obj = O(o);
    if (!obj || !f) {
        raise(e, "java/lang/NullPointerException", "field write on null");
        return;
    }
    obj->set_field(F(f), v);
}

#define JVM_FIELDS(Name, T)                                                                                            \
    T Get##Name##Field(JNIEnv* e, jobject o, jfieldID f) { return ret<T>(e, get_field(e, o, f)); }                    \
    void Set##Name##Field(JNIEnv* e, jobject o, jfieldID f, T v) { set_field(e, o, f, val(v)); }                       \
    T GetStatic##Name##Field(JNIEnv* e, jclass, jfieldID f) { return f ? ret<T>(e, static_value(F(f))) : T{}; }        \
    void SetStatic##Name##Field(JNIEnv*, jclass, jfieldID f, T v) {                                                    \
        if (f) set_static_value(F(f), val(v));                                                                         \
    }

JVM_FIELDS(Object, jobject)
JVM_FIELDS(Boolean, jboolean)
JVM_FIELDS(Byte, jbyte)
JVM_FIELDS(Char, jchar)
JVM_FIELDS(Short, jshort)
JVM_FIELDS(Int, jint)
JVM_FIELDS(Long, jlong)
JVM_FIELDS(Float, jfloat)
JVM_FIELDS(Double, jdouble)

// ---------------------------------------------------------------------------------------------------------------------
// Primitive arrays. Element pointers point into the array itself (no copies): the array is held from Get to Release.

Array* typed_array(JNIEnv* e, jarray a, char type) {
    auto* arr = As<Array>(a);
    if (!arr) {
        raise(e, "java/lang/NullPointerException", "array is null");
        return nullptr;
    }
    // Another element type is a bug in the caller; ART would abort under CheckJNI.
    if (type && arr->type != type) {
        log("jvm: a %c array used as a %c array", arr->type, type);
        return nullptr;
    }
    return arr;
}

// Get*ArrayRegion and Set*ArrayRegion: n elements from start, within bounds or an exception.
void region(JNIEnv* e, jarray a, char type, jsize start, jsize n, void* buf, bool set) {
    Array* arr = typed_array(e, a, type);
    if (!arr) return;
    if (start < 0 || n < 0 || start > arr->length - n) {
        raise(e, "java/lang/ArrayIndexOutOfBoundsException", "region " + std::to_string(start) + "+" + std::to_string(n) + " of " + std::to_string(arr->length));
        return;
    }
    std::size_t size = arr->element_size();
    std::uint8_t* at = arr->bytes.data() + static_cast<std::size_t>(start) * size;
    std::size_t bytes = static_cast<std::size_t>(n) * size;
    if (!bytes) return;
    if (set) std::memcpy(at, buf, bytes);
    else std::memcpy(buf, at, bytes);
}

#define JVM_ARRAYS(Name, T, letter)                                                                                    \
    T##Array New##Name##Array(JNIEnv* e, jsize n) {                                                                    \
        if (n < 0) {                                                                                                   \
            raise(e, "java/lang/NegativeArraySizeException", std::to_string(n));                                       \
            return nullptr;                                                                                            \
        }                                                                                                              \
        return L<T##Array>(e, new_array(array_class(primitive_class(letter)), n).get());                               \
    }                                                                                                                  \
    T* Get##Name##ArrayElements(JNIEnv* e, T##Array a, jboolean* is_copy) {                                            \
        Array* arr = typed_array(e, a, letter);                                                                        \
        if (!arr) return nullptr;                                                                                      \
        arr->retain();                                                                                                 \
        if (is_copy) *is_copy = JNI_FALSE;                                                                             \
        return arr->data<T>();                                                                                         \
    }                                                                                                                  \
    void Release##Name##ArrayElements(JNIEnv* e, T##Array a, T*, jint mode) {                                          \
        /* JNI_COMMIT keeps the elements for another Release; 0 and JNI_ABORT end the hold. */                          \
        Array* arr = typed_array(e, a, letter);                                                                        \
        if (arr && mode != JNI_COMMIT) arr->release();                                                                 \
    }                                                                                                                  \
    void Get##Name##ArrayRegion(JNIEnv* e, T##Array a, jsize start, jsize n, T* buf) { region(e, a, letter, start, n, buf, false); } \
    void Set##Name##ArrayRegion(JNIEnv* e, T##Array a, jsize start, jsize n, const T* buf) {                           \
        region(e, a, letter, start, n, const_cast<T*>(buf), true);                                                     \
    }

JVM_ARRAYS(Boolean, jboolean, 'Z')
JVM_ARRAYS(Byte, jbyte, 'B')
JVM_ARRAYS(Char, jchar, 'C')
JVM_ARRAYS(Short, jshort, 'S')
JVM_ARRAYS(Int, jint, 'I')
JVM_ARRAYS(Long, jlong, 'J')
JVM_ARRAYS(Float, jfloat, 'F')
JVM_ARRAYS(Double, jdouble, 'D')

// ---------------------------------------------------------------------------------------------------------------------
// The other JNIEnv functions, in jni.h's order.

jint GetVersion(JNIEnv*) { return JNI_VERSION_1_6; }

jclass DefineClass(JNIEnv* e, const char* name, jobject, const jbyte*, jsize) {
    // There is no Java code to run here, so no class file to define.
    raise(e, "java/lang/NoClassDefFoundError", std::string("cannot define ") + (name ? name : "a class") + " from bytes");
    return nullptr;
}

jclass FindClass(JNIEnv* e, const char* name) {
    Class* c = name ? find_class(name) : nullptr;
    if (!c) {
        raise(e, "java/lang/NoClassDefFoundError", name ? name : "null");
        return nullptr;
    }
    return L<jclass>(e, c);
}

jmethodID FromReflectedMethod(JNIEnv*, jobject m) {
    auto* member = As<Member>(m);
    return member ? reinterpret_cast<jmethodID>(member->method) : nullptr;
}

jfieldID FromReflectedField(JNIEnv*, jobject f) {
    auto* member = As<Member>(f);
    return member ? reinterpret_cast<jfieldID>(member->field) : nullptr;
}

jobject ToReflectedMethod(JNIEnv* e, jclass, jmethodID m, jboolean) {
    if (!m) return nullptr;
    // A constructor's reflection object is a Constructor, any other method's a Method.
    Class* cls = M(m)->name == "<init>" ? core().constructor : core().method;
    return L(e, new Member(cls, M(m), nullptr));
}

jclass GetSuperclass(JNIEnv* e, jclass c) {
    Class* cls = C(c);
    // Interfaces, primitive types and java/lang/Object have none.
    return cls && !cls->is_interface() && !cls->primitive ? L<jclass>(e, cls->super) : nullptr;
}

jboolean IsAssignableFrom(JNIEnv*, jclass a, jclass b) {
    Class* from = C(a);
    Class* to = C(b);
    return from && to && from->is(to) ? JNI_TRUE : JNI_FALSE;
}

jobject ToReflectedField(JNIEnv* e, jclass, jfieldID f, jboolean) { return f ? L(e, new Member(core().field, nullptr, F(f))) : nullptr; }

// JNI's Throw (named apart from jvm::Throw, the C++ exception the library's bodies throw).
jint ThrowObject(JNIEnv* e, jthrowable t) {
    E(e).pending = Ref<Object>(O(t));
    return JNI_OK;
}

jint ThrowNew(JNIEnv* e, jclass c, const char* message) {
    Class* cls = C(c);
    if (!cls) return JNI_ERR;
    E(e).pending = exception(cls->name, message ? message : "");
    return JNI_OK;
}

jthrowable ExceptionOccurred(JNIEnv* e) { return L<jthrowable>(e, E(e).pending.get()); }

void ExceptionDescribe(JNIEnv* e) {
    Ref<Object> p = E(e).pending;
    if (!p) return;
    log("jvm: exception %s: %s", p->cls()->java_name().c_str(), message_of(p.get()).c_str());
    // The exception is cleared as a side effect, as the JNI specification has it.
    E(e).pending = {};
}

void ExceptionClear(JNIEnv* e) { E(e).pending = {}; }

void FatalError(JNIEnv*, const char* message) {
    log("jvm: fatal error: %s", message ? message : "");
    std::abort();
}

jint PushLocalFrame(JNIEnv* e, jint) {
    E(e).push_frame();
    return JNI_OK;
}

jobject PopLocalFrame(JNIEnv* e, jobject result) {
    // The result survives the frame as a reference in the frame below.
    Ref<Object> keep(O(result));
    E(e).pop_frame();
    return L(e, keep.get());
}

jobject NewGlobalRef(JNIEnv*, jobject o) { return new_global(O(o), false); }
void DeleteGlobalRef(JNIEnv*, jobject g) { delete_global(g); }
void DeleteLocalRef(JNIEnv* e, jobject r) { E(e).delete_local(r); }
jboolean IsSameObject(JNIEnv*, jobject a, jobject b) { return O(a) == O(b) ? JNI_TRUE : JNI_FALSE; }
jobject NewLocalRef(JNIEnv* e, jobject r) { return L(e, O(r)); }
// No limit to grow into: local references are a deque.
jint EnsureLocalCapacity(JNIEnv*, jint) { return JNI_OK; }

jobject AllocObject(JNIEnv* e, jclass c) {
    Class* cls = C(c);
    if (!cls) return nullptr;
    return L(e, instantiate(*cls));
}

// NewObject in its three forms: a new object, then its constructor.
jobject construct(JNIEnv* e, jclass c, jmethodID m, const std::vector<Value>& args) {
    Class* cls = C(c);
    if (!cls || !m) return nullptr;
    Ref<Object> o(instantiate(*cls));
    E(e).invoke(*M(m), o.get(), args.data(), args.size());
    // A constructor that threw leaves no object.
    if (E(e).pending) return nullptr;
    return L(e, o.get());
}

jobject NewObject(JNIEnv* e, jclass c, jmethodID m, ...) {
    va_list ap;
    va_start(ap, m);
    std::vector<Value> args = from_va(M(m), ap);
    va_end(ap);
    return construct(e, c, m, args);
}
jobject NewObjectV(JNIEnv* e, jclass c, jmethodID m, va_list ap) { return construct(e, c, m, from_va(M(m), ap)); }
jobject NewObjectA(JNIEnv* e, jclass c, jmethodID m, const jvalue* a) { return construct(e, c, m, from_array(M(m), a)); }

jclass GetObjectClass(JNIEnv* e, jobject o) {
    Object* obj = O(o);
    return obj ? L<jclass>(e, obj->cls()) : nullptr;
}

jboolean IsInstanceOf(JNIEnv*, jobject o, jclass c) {
    Object* obj = O(o);
    Class* cls = C(c);
    // Null is an instance of every class, as JNI defines it.
    if (!obj) return JNI_TRUE;
    return cls && obj->cls()->is(cls) ? JNI_TRUE : JNI_FALSE;
}

jmethodID GetMethodID(JNIEnv* e, jclass c, const char* name, const char* sig) {
    Class* cls = C(c);
    if (!cls || !name || !sig) {
        raise(e, "java/lang/NoSuchMethodError", name ? name : "null");
        return nullptr;
    }
    return reinterpret_cast<jmethodID>(&cls->method_or_made_up(name, sig, false));
}

jfieldID GetFieldID(JNIEnv* e, jclass c, const char* name, const char* sig) {
    Class* cls = C(c);
    if (!cls || !name || !sig) {
        raise(e, "java/lang/NoSuchFieldError", name ? name : "null");
        return nullptr;
    }
    return reinterpret_cast<jfieldID>(&cls->field_or_made_up(name, sig, false));
}

jmethodID GetStaticMethodID(JNIEnv* e, jclass c, const char* name, const char* sig) {
    Class* cls = C(c);
    if (!cls || !name || !sig) {
        raise(e, "java/lang/NoSuchMethodError", name ? name : "null");
        return nullptr;
    }
    return reinterpret_cast<jmethodID>(&cls->method_or_made_up(name, sig, true));
}

jfieldID GetStaticFieldID(JNIEnv* e, jclass c, const char* name, const char* sig) {
    Class* cls = C(c);
    if (!cls || !name || !sig) {
        raise(e, "java/lang/NoSuchFieldError", name ? name : "null");
        return nullptr;
    }
    return reinterpret_cast<jfieldID>(&cls->field_or_made_up(name, sig, true));
}

jstring NewString(JNIEnv* e, const jchar* chars, jsize n) {
    if (n < 0 || (!chars && n)) return nullptr;
    return L<jstring>(e, string16(std::u16string(reinterpret_cast<const char16_t*>(chars), static_cast<std::size_t>(n))).get());
}

jsize GetStringLength(JNIEnv*, jstring s) {
    auto* str = As<String>(s);
    return str ? static_cast<jsize>(str->chars.size()) : 0;
}

// The characters themselves (strings never change); the string is held until Release.
const jchar* GetStringChars(JNIEnv*, jstring s, jboolean* is_copy) {
    auto* str = As<String>(s);
    if (!str) return nullptr;
    str->retain();
    if (is_copy) *is_copy = JNI_FALSE;
    return reinterpret_cast<const jchar*>(str->chars.c_str());
}

void ReleaseStringChars(JNIEnv*, jstring s, const jchar*) {
    if (auto* str = As<String>(s)) str->release();
}

jstring NewStringUTF(JNIEnv* e, const char* text) { return text ? L<jstring>(e, string16(utf16_of(text)).get()) : nullptr; }

jsize GetStringUTFLength(JNIEnv*, jstring s) {
    auto* str = As<String>(s);
    return str ? static_cast<jsize>(str->mutf8().size()) : 0;
}

// A copy in modified UTF-8, zero-terminated, freed by Release.
const char* GetStringUTFChars(JNIEnv*, jstring s, jboolean* is_copy) {
    auto* str = As<String>(s);
    if (!str) return nullptr;
    std::string text = str->mutf8();
    auto* out = new char[text.size() + 1];
    std::memcpy(out, text.c_str(), text.size() + 1);
    if (is_copy) *is_copy = JNI_TRUE;
    return out;
}

void ReleaseStringUTFChars(JNIEnv*, jstring, const char* chars) { delete[] chars; }

jsize GetArrayLength(JNIEnv*, jarray a) {
    auto* arr = As<Array>(a);
    return arr ? arr->length : 0;
}

jobjectArray NewObjectArray(JNIEnv* e, jsize n, jclass element, jobject initial) {
    Class* cls = C(element);
    if (!cls || n < 0) {
        raise(e, n < 0 ? "java/lang/NegativeArraySizeException" : "java/lang/NullPointerException", "NewObjectArray");
        return nullptr;
    }
    Ref<Array> arr = new_array(array_class(*cls), n);
    if (Object* init = O(initial)) {
        for (auto& item : arr->items) item = Ref<Object>(init);
    }
    return L<jobjectArray>(e, arr.get());
}

jobject GetObjectArrayElement(JNIEnv* e, jobjectArray a, jsize i) {
    auto* arr = As<Array>(a);
    if (!arr || !arr->of_objects()) return nullptr;
    if (i < 0 || i >= arr->length) {
        raise(e, "java/lang/ArrayIndexOutOfBoundsException", std::to_string(i) + " of " + std::to_string(arr->length));
        return nullptr;
    }
    return L(e, arr->items[static_cast<std::size_t>(i)].get());
}

void SetObjectArrayElement(JNIEnv* e, jobjectArray a, jsize i, jobject v) {
    auto* arr = As<Array>(a);
    if (!arr || !arr->of_objects()) return;
    if (i < 0 || i >= arr->length) {
        raise(e, "java/lang/ArrayIndexOutOfBoundsException", std::to_string(i) + " of " + std::to_string(arr->length));
        return;
    }
    arr->items[static_cast<std::size_t>(i)] = Ref<Object>(O(v));
}

jint RegisterNatives(JNIEnv* e, jclass c, const JNINativeMethod* methods, jint n) {
    Class* cls = C(c);
    if (!cls || (n > 0 && !methods)) return JNI_ERR;
    for (jint k = 0; k < n; ++k) {
        const JNINativeMethod& nm = methods[k];
        if (!nm.name || !nm.signature) return JNI_ERR;
        Method& m = cls->registered(nm.name, nm.signature);
        m.native.store(nm.fnPtr, std::memory_order_release);
        if (trace_on()) log("jvm: RegisterNatives %s.%s%s", cls->name.c_str(), nm.name, nm.signature);
    }
    return JNI_OK;
}

jint UnregisterNatives(JNIEnv*, jclass c) {
    Class* cls = C(c);
    if (!cls) return JNI_ERR;
    for (Method* m : cls->all_methods()) m->native.store(nullptr, std::memory_order_release);
    return JNI_OK;
}

jint MonitorEnter(JNIEnv* e, jobject o) {
    Object* obj = O(o);
    if (!obj) {
        raise(e, "java/lang/NullPointerException", "MonitorEnter on null");
        return JNI_ERR;
    }
    obj->monitor().lock();
    return JNI_OK;
}

jint MonitorExit(JNIEnv* e, jobject o) {
    Object* obj = O(o);
    if (!obj) {
        raise(e, "java/lang/NullPointerException", "MonitorExit on null");
        return JNI_ERR;
    }
    obj->monitor().unlock();
    return JNI_OK;
}

jint GetJavaVM(JNIEnv*, JavaVM** vm) {
    if (!vm) return JNI_ERR;
    *vm = java_vm();
    return JNI_OK;
}

void GetStringRegion(JNIEnv* e, jstring s, jsize start, jsize n, jchar* buf) {
    auto* str = As<String>(s);
    if (!str) return;
    auto size = static_cast<jsize>(str->chars.size());
    if (start < 0 || n < 0 || start > size - n) {
        raise(e, "java/lang/StringIndexOutOfBoundsException", "region " + std::to_string(start) + "+" + std::to_string(n));
        return;
    }
    if (n) std::memcpy(buf, str->chars.data() + start, static_cast<std::size_t>(n) * 2);
}

// The characters start..start+n in modified UTF-8, not zero-terminated (as ART writes them).
void GetStringUTFRegion(JNIEnv* e, jstring s, jsize start, jsize n, char* buf) {
    auto* str = As<String>(s);
    if (!str) return;
    auto size = static_cast<jsize>(str->chars.size());
    if (start < 0 || n < 0 || start > size - n) {
        raise(e, "java/lang/StringIndexOutOfBoundsException", "region " + std::to_string(start) + "+" + std::to_string(n));
        return;
    }
    std::string text = mutf8_of(str->chars.data() + start, static_cast<std::size_t>(n));
    if (!text.empty()) std::memcpy(buf, text.data(), text.size());
}

void* GetPrimitiveArrayCritical(JNIEnv* e, jarray a, jboolean* is_copy) {
    Array* arr = typed_array(e, a, 0);
    if (!arr || arr->of_objects()) return nullptr;
    arr->retain();
    if (is_copy) *is_copy = JNI_FALSE;
    return arr->bytes.data();
}

void ReleasePrimitiveArrayCritical(JNIEnv* e, jarray a, void*, jint mode) {
    Array* arr = typed_array(e, a, 0);
    if (arr && mode != JNI_COMMIT) arr->release();
}

const jchar* GetStringCritical(JNIEnv* e, jstring s, jboolean* is_copy) { return GetStringChars(e, s, is_copy); }
void ReleaseStringCritical(JNIEnv* e, jstring s, const jchar* chars) { ReleaseStringChars(e, s, chars); }

jweak NewWeakGlobalRef(JNIEnv*, jobject o) { return new_global(O(o), true); }
void DeleteWeakGlobalRef(JNIEnv*, jweak w) { delete_global(w); }

jboolean ExceptionCheck(JNIEnv* e) { return E(e).pending ? JNI_TRUE : JNI_FALSE; }

jobject NewDirectByteBuffer(JNIEnv* e, void* address, jlong capacity) {
    if (!address || capacity < 0) return nullptr;
    return L(e, direct_buffer(address, capacity).get());
}

void* GetDirectBufferAddress(JNIEnv*, jobject b) {
    auto* buf = As<Buffer>(b);
    return buf ? buf->address : nullptr;
}

jlong GetDirectBufferCapacity(JNIEnv*, jobject b) {
    auto* buf = As<Buffer>(b);
    return buf ? buf->capacity : -1;
}

jobjectRefType GetObjectRefType(JNIEnv*, jobject r) { return ref_type(r); }

// ---------------------------------------------------------------------------------------------------------------------
// JavaVM.

jint DestroyJavaVM(JavaVM*) {
    // The VM lives as long as the process.
    return JNI_ERR;
}

jint AttachCurrentThread(JavaVM*, JNIEnv** env, void*) {
    if (!env) return JNI_ERR;
    *env = &attach().jni;
    return JNI_OK;
}

jint DetachCurrentThread(JavaVM*) {
    detach();
    return JNI_OK;
}

jint GetEnv(JavaVM*, void** env, jint version) {
    if (!env) return JNI_ERR;
    Env* cur = Env::current();
    if (!cur) {
        *env = nullptr;
        return JNI_EDETACHED;
    }
    // JNI 1.1 to 1.6 are all this table.
    if (version < JNI_VERSION_1_1 || version > JNI_VERSION_1_6) {
        *env = nullptr;
        return JNI_EVERSION;
    }
    *env = &cur->jni;
    return JNI_OK;
}

}  // namespace

#define JVM_CALL_ENTRIES(Name)                                                                                         \
    .Call##Name##Method = Call##Name##Method, .Call##Name##MethodV = Call##Name##MethodV, .Call##Name##MethodA = Call##Name##MethodA
#define JVM_NONVIRTUAL_ENTRIES(Name)                                                                                   \
    .CallNonvirtual##Name##Method = CallNonvirtual##Name##Method, .CallNonvirtual##Name##MethodV = CallNonvirtual##Name##MethodV, \
    .CallNonvirtual##Name##MethodA = CallNonvirtual##Name##MethodA
#define JVM_STATIC_ENTRIES(Name)                                                                                       \
    .CallStatic##Name##Method = CallStatic##Name##Method, .CallStatic##Name##MethodV = CallStatic##Name##MethodV,      \
    .CallStatic##Name##MethodA = CallStatic##Name##MethodA

const JNINativeInterface kNativeInterface = {
    .reserved0 = nullptr,
    .reserved1 = nullptr,
    .reserved2 = nullptr,
    .reserved3 = nullptr,
    .GetVersion = GetVersion,
    .DefineClass = DefineClass,
    .FindClass = FindClass,
    .FromReflectedMethod = FromReflectedMethod,
    .FromReflectedField = FromReflectedField,
    .ToReflectedMethod = ToReflectedMethod,
    .GetSuperclass = GetSuperclass,
    .IsAssignableFrom = IsAssignableFrom,
    .ToReflectedField = ToReflectedField,
    .Throw = ThrowObject,
    .ThrowNew = ThrowNew,
    .ExceptionOccurred = ExceptionOccurred,
    .ExceptionDescribe = ExceptionDescribe,
    .ExceptionClear = ExceptionClear,
    .FatalError = FatalError,
    .PushLocalFrame = PushLocalFrame,
    .PopLocalFrame = PopLocalFrame,
    .NewGlobalRef = NewGlobalRef,
    .DeleteGlobalRef = DeleteGlobalRef,
    .DeleteLocalRef = DeleteLocalRef,
    .IsSameObject = IsSameObject,
    .NewLocalRef = NewLocalRef,
    .EnsureLocalCapacity = EnsureLocalCapacity,
    .AllocObject = AllocObject,
    .NewObject = NewObject,
    .NewObjectV = NewObjectV,
    .NewObjectA = NewObjectA,
    .GetObjectClass = GetObjectClass,
    .IsInstanceOf = IsInstanceOf,
    .GetMethodID = GetMethodID,
    JVM_CALL_ENTRIES(Object),
    JVM_CALL_ENTRIES(Boolean),
    JVM_CALL_ENTRIES(Byte),
    JVM_CALL_ENTRIES(Char),
    JVM_CALL_ENTRIES(Short),
    JVM_CALL_ENTRIES(Int),
    JVM_CALL_ENTRIES(Long),
    JVM_CALL_ENTRIES(Float),
    JVM_CALL_ENTRIES(Double),
    JVM_CALL_ENTRIES(Void),
    JVM_NONVIRTUAL_ENTRIES(Object),
    JVM_NONVIRTUAL_ENTRIES(Boolean),
    JVM_NONVIRTUAL_ENTRIES(Byte),
    JVM_NONVIRTUAL_ENTRIES(Char),
    JVM_NONVIRTUAL_ENTRIES(Short),
    JVM_NONVIRTUAL_ENTRIES(Int),
    JVM_NONVIRTUAL_ENTRIES(Long),
    JVM_NONVIRTUAL_ENTRIES(Float),
    JVM_NONVIRTUAL_ENTRIES(Double),
    JVM_NONVIRTUAL_ENTRIES(Void),
    .GetFieldID = GetFieldID,
    .GetObjectField = GetObjectField,
    .GetBooleanField = GetBooleanField,
    .GetByteField = GetByteField,
    .GetCharField = GetCharField,
    .GetShortField = GetShortField,
    .GetIntField = GetIntField,
    .GetLongField = GetLongField,
    .GetFloatField = GetFloatField,
    .GetDoubleField = GetDoubleField,
    .SetObjectField = SetObjectField,
    .SetBooleanField = SetBooleanField,
    .SetByteField = SetByteField,
    .SetCharField = SetCharField,
    .SetShortField = SetShortField,
    .SetIntField = SetIntField,
    .SetLongField = SetLongField,
    .SetFloatField = SetFloatField,
    .SetDoubleField = SetDoubleField,
    .GetStaticMethodID = GetStaticMethodID,
    JVM_STATIC_ENTRIES(Object),
    JVM_STATIC_ENTRIES(Boolean),
    JVM_STATIC_ENTRIES(Byte),
    JVM_STATIC_ENTRIES(Char),
    JVM_STATIC_ENTRIES(Short),
    JVM_STATIC_ENTRIES(Int),
    JVM_STATIC_ENTRIES(Long),
    JVM_STATIC_ENTRIES(Float),
    JVM_STATIC_ENTRIES(Double),
    JVM_STATIC_ENTRIES(Void),
    .GetStaticFieldID = GetStaticFieldID,
    .GetStaticObjectField = GetStaticObjectField,
    .GetStaticBooleanField = GetStaticBooleanField,
    .GetStaticByteField = GetStaticByteField,
    .GetStaticCharField = GetStaticCharField,
    .GetStaticShortField = GetStaticShortField,
    .GetStaticIntField = GetStaticIntField,
    .GetStaticLongField = GetStaticLongField,
    .GetStaticFloatField = GetStaticFloatField,
    .GetStaticDoubleField = GetStaticDoubleField,
    .SetStaticObjectField = SetStaticObjectField,
    .SetStaticBooleanField = SetStaticBooleanField,
    .SetStaticByteField = SetStaticByteField,
    .SetStaticCharField = SetStaticCharField,
    .SetStaticShortField = SetStaticShortField,
    .SetStaticIntField = SetStaticIntField,
    .SetStaticLongField = SetStaticLongField,
    .SetStaticFloatField = SetStaticFloatField,
    .SetStaticDoubleField = SetStaticDoubleField,
    .NewString = NewString,
    .GetStringLength = GetStringLength,
    .GetStringChars = GetStringChars,
    .ReleaseStringChars = ReleaseStringChars,
    .NewStringUTF = NewStringUTF,
    .GetStringUTFLength = GetStringUTFLength,
    .GetStringUTFChars = GetStringUTFChars,
    .ReleaseStringUTFChars = ReleaseStringUTFChars,
    .GetArrayLength = GetArrayLength,
    .NewObjectArray = NewObjectArray,
    .GetObjectArrayElement = GetObjectArrayElement,
    .SetObjectArrayElement = SetObjectArrayElement,
    .NewBooleanArray = NewBooleanArray,
    .NewByteArray = NewByteArray,
    .NewCharArray = NewCharArray,
    .NewShortArray = NewShortArray,
    .NewIntArray = NewIntArray,
    .NewLongArray = NewLongArray,
    .NewFloatArray = NewFloatArray,
    .NewDoubleArray = NewDoubleArray,
    .GetBooleanArrayElements = GetBooleanArrayElements,
    .GetByteArrayElements = GetByteArrayElements,
    .GetCharArrayElements = GetCharArrayElements,
    .GetShortArrayElements = GetShortArrayElements,
    .GetIntArrayElements = GetIntArrayElements,
    .GetLongArrayElements = GetLongArrayElements,
    .GetFloatArrayElements = GetFloatArrayElements,
    .GetDoubleArrayElements = GetDoubleArrayElements,
    .ReleaseBooleanArrayElements = ReleaseBooleanArrayElements,
    .ReleaseByteArrayElements = ReleaseByteArrayElements,
    .ReleaseCharArrayElements = ReleaseCharArrayElements,
    .ReleaseShortArrayElements = ReleaseShortArrayElements,
    .ReleaseIntArrayElements = ReleaseIntArrayElements,
    .ReleaseLongArrayElements = ReleaseLongArrayElements,
    .ReleaseFloatArrayElements = ReleaseFloatArrayElements,
    .ReleaseDoubleArrayElements = ReleaseDoubleArrayElements,
    .GetBooleanArrayRegion = GetBooleanArrayRegion,
    .GetByteArrayRegion = GetByteArrayRegion,
    .GetCharArrayRegion = GetCharArrayRegion,
    .GetShortArrayRegion = GetShortArrayRegion,
    .GetIntArrayRegion = GetIntArrayRegion,
    .GetLongArrayRegion = GetLongArrayRegion,
    .GetFloatArrayRegion = GetFloatArrayRegion,
    .GetDoubleArrayRegion = GetDoubleArrayRegion,
    .SetBooleanArrayRegion = SetBooleanArrayRegion,
    .SetByteArrayRegion = SetByteArrayRegion,
    .SetCharArrayRegion = SetCharArrayRegion,
    .SetShortArrayRegion = SetShortArrayRegion,
    .SetIntArrayRegion = SetIntArrayRegion,
    .SetLongArrayRegion = SetLongArrayRegion,
    .SetFloatArrayRegion = SetFloatArrayRegion,
    .SetDoubleArrayRegion = SetDoubleArrayRegion,
    .RegisterNatives = RegisterNatives,
    .UnregisterNatives = UnregisterNatives,
    .MonitorEnter = MonitorEnter,
    .MonitorExit = MonitorExit,
    .GetJavaVM = GetJavaVM,
    .GetStringRegion = GetStringRegion,
    .GetStringUTFRegion = GetStringUTFRegion,
    .GetPrimitiveArrayCritical = GetPrimitiveArrayCritical,
    .ReleasePrimitiveArrayCritical = ReleasePrimitiveArrayCritical,
    .GetStringCritical = GetStringCritical,
    .ReleaseStringCritical = ReleaseStringCritical,
    .NewWeakGlobalRef = NewWeakGlobalRef,
    .DeleteWeakGlobalRef = DeleteWeakGlobalRef,
    .ExceptionCheck = ExceptionCheck,
    .NewDirectByteBuffer = NewDirectByteBuffer,
    .GetDirectBufferAddress = GetDirectBufferAddress,
    .GetDirectBufferCapacity = GetDirectBufferCapacity,
    .GetObjectRefType = GetObjectRefType,
};

const JNIInvokeInterface kInvokeInterface = {
    .reserved0 = nullptr,
    .reserved1 = nullptr,
    .reserved2 = nullptr,
    .DestroyJavaVM = DestroyJavaVM,
    .AttachCurrentThread = AttachCurrentThread,
    .DetachCurrentThread = DetachCurrentThread,
    .GetEnv = GetEnv,
    .AttachCurrentThreadAsDaemon = AttachCurrentThread,
};

}  // namespace jvm
