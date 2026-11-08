// A Java VM in C++ for hosts without Android (the desktop player first, later iOS): the JNI that the game's native code
// reaches through the runtime's JNI bridge, the java.lang classes JNI itself stands on, and a way to write the Android,
// Unity and game classes the game calls as C++.
//
// No Java code runs here. Every method is a C++ function bound to a class by name and signature (Class::method). A class
// or method nobody defined is made the first time code asks for it, the way the phone's VM would have found it in the
// app: calling it does nothing and returns zero, an empty object of the class it returns, or an empty array (a String
// stays null), logged the first time. Most of what the game carries (analytics, ads, crash reports) is meant to do
// nothing here, and the log names what still needs a body.
//
// References behave as ART's do: a local reference belongs to its thread and to the native call (or local frame) that
// made it, a global one to the whole VM. Objects count the references to them and go when the last one does.
#pragma once

#include <jni.h>

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <functional>
#include <initializer_list>
#include <mutex>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace jvm {

class Object;
class Value;
class Class;
class Env;
struct Method;
struct Field;
struct Call;

// One line of the VM's log. Lines go to stderr until the host program sets a sink (the player hands them to the
// runtime's log, so both read in one place).
void log(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
void set_log_sink(void (*sink)(const char* line));

// Modifier bits as java.lang.reflect.Modifier numbers them: getModifiers() returns them, and the runtime's JNI bridge
// looks for native methods by kNative when it binds a library's exported Java_ functions.
constexpr jint kPublic = 0x1, kStatic = 0x8, kFinal = 0x10, kNative = 0x100, kInterface = 0x200, kAbstract = 0x400;

// A counted reference to an object, for C++ code that keeps objects (a class's singleton, a queue of runnables).
template <class T>
class Ref {
public:
    Ref() = default;
    // Taking a pointer counts a reference: a new object starts at none and lives from its first Ref on.
    Ref(T* p) : p_(p) {
        if (p_) p_->retain();
    }
    Ref(const Ref& o) : Ref(o.p_) {}
    // Moving hands the reference over without touching the count.
    Ref(Ref&& o) noexcept : p_(o.p_) { o.p_ = nullptr; }
    // A reference to a derived class converts to one to its base, as the pointers do.
    template <class U>
    Ref(const Ref<U>& o) : Ref(static_cast<T*>(o.get())) {}
    ~Ref() {
        if (p_) p_->release();
    }
    // By value: the old object is released when the parameter goes, after the new one is in place.
    Ref& operator=(Ref o) noexcept {
        std::swap(p_, o.p_);
        return *this;
    }
    T* get() const { return p_; }
    T* operator->() const { return p_; }
    T& operator*() const { return *p_; }
    explicit operator bool() const { return p_ != nullptr; }

private:
    T* p_ = nullptr;
};

// A Java object. Classes of the C++ library that keep state of their own derive from it.
class Object {
public:
    explicit Object(Class* cls) : cls_(cls) {}
    Object(const Object&) = delete;
    Object& operator=(const Object&) = delete;
    virtual ~Object();
    Class* cls() const { return cls_; }
    // Reference counting: JNI references, Ref<> and Value, fields and array elements all count.
    void retain() const { refs_.fetch_add(1, std::memory_order_relaxed); }
    void release() const {
        // acq_rel: whatever another thread did to the object happens before it is freed here.
        if (refs_.fetch_sub(1, std::memory_order_acq_rel) == 1) delete this;
    }
    // Instance fields set through JNI or by the C++ classes; a field never set reads as zero or null.
    Value field(const Field* f) const;
    void set_field(const Field* f, const Value& v);
    // The object's monitor (MonitorEnter, synchronized), made on first use.
    std::recursive_mutex& monitor();

private:
    friend void set_class(Object& o, Class* cls);
    // The class; patched once while the VM makes java/lang/Class, which is its own class.
    Class* cls_;
    mutable std::atomic<std::uint32_t> refs_{0};
    // Field values by field, made on the first store. Guarded by one lock for all objects: fields are rare here (the
    // C++ classes keep their state as C++ members).
    std::unordered_map<const Field*, Value>* fields_ = nullptr;
    std::atomic<std::recursive_mutex*> monitor_{nullptr};
};

// A Java value: a primitive, as the jvalue member of its type, or an object, which the value keeps alive. Methods return
// one, and C++ code passes them as arguments.
class Value {
public:
    // Zero, false, null, or nothing (void).
    Value() { prim_.j = 0; }
    // An object, or null.
    Value(Object* o);
    template <class T>
    Value(const Ref<T>& o) : Value(static_cast<Object*>(o.get())) {}
    // The primitives, by their descriptor letters: Value::I(5) is an int, Value::J(5) a long.
    static Value Z(bool v) {
        Value r;
        r.prim_.z = v ? JNI_TRUE : JNI_FALSE;
        return r;
    }
    static Value B(jbyte v) {
        Value r;
        r.prim_.b = v;
        return r;
    }
    static Value C(jchar v) {
        Value r;
        r.prim_.c = v;
        return r;
    }
    static Value S(jshort v) {
        Value r;
        r.prim_.s = v;
        return r;
    }
    static Value I(jint v) {
        Value r;
        r.prim_.i = v;
        return r;
    }
    static Value J(jlong v) {
        Value r;
        r.prim_.j = v;
        return r;
    }
    static Value F(jfloat v) {
        Value r;
        r.prim_.f = v;
        return r;
    }
    static Value D(jdouble v) {
        Value r;
        r.prim_.d = v;
        return r;
    }
    jboolean z() const { return prim_.z; }
    jbyte b() const { return prim_.b; }
    jchar c() const { return prim_.c; }
    jshort s() const { return prim_.s; }
    jint i() const { return prim_.i; }
    jlong j() const { return prim_.j; }
    jfloat f() const { return prim_.f; }
    jdouble d() const { return prim_.d; }
    Object* l() const { return obj_.get(); }
    // The primitive as JNI passes it (the member of the value's own type is the one set).
    const jvalue& raw() const { return prim_; }

private:
    jvalue prim_;
    Ref<Object> obj_;
};

// A method's C++ body. It gets the call (the object, the arguments) and returns the result; it throws Throw to throw a
// Java exception.
using Handler = std::function<Value(Call&)>;

// A method: its name and signature, what the signature says, and its body. Never freed: a jmethodID is its address.
struct Method {
    Class* owner = nullptr;
    std::string name, sig;
    jint modifiers = kPublic;
    // One letter per parameter, the first of its descriptor ('L' for objects, '[' for arrays), for converting
    // arguments; and each parameter's whole descriptor, for reflection (getParameterTypes).
    std::string params;
    std::vector<std::string> param_types;
    // The return type's descriptor and its first letter ('V' for void).
    std::string ret_type;
    char ret = 'V';
    // The C++ body, if there is one.
    Handler fn;
    // A native method's body, registered by the game's code (RegisterNatives) or bound from a library's export.
    std::atomic<void*> native{nullptr};
    // Made because code asked for it, not defined by the C++ library: it does nothing.
    bool made_up = false;
    // Calls so far, for the report of what nothing implements.
    std::atomic<std::uint64_t> calls{0};
    // A made-up getInstance's one object (inert_result).
    Ref<Object> instance;
    bool is_static() const { return modifiers & kStatic; }
};

// A field. Never freed: a jfieldID is its address. A static field keeps its value here.
struct Field {
    Class* owner = nullptr;
    std::string name, sig;
    bool is_static = false;
    // The first letter of its descriptor.
    char type = 'I';
    bool made_up = false;
    // A static field's value (guarded by the same lock as instance fields).
    Value value;
};

// A class, which is a Java object too (java.lang.Class). Never freed.
class Class : public Object {
public:
    // A class named by its binary name ("java/lang/String"), an array's descriptor ("[I", "[Ljava/lang/String;") or a
    // primitive type's keyword ("int").
    Class(Class* class_class, std::string name);

    const std::string name;
    Class* super = nullptr;
    std::vector<Class*> interfaces;
    jint modifiers = kPublic;
    // A primitive type's descriptor letter ('I' for int.class), 0 for every other class.
    char primitive = 0;
    // An array class's element class.
    Class* component = nullptr;
    // A proxy class (java.lang.reflect.Proxy): every method of its interfaces goes to the object's handler.
    bool proxy = false;
    // Made because code asked for it (FindClass, a signature), not defined by the C++ library.
    bool made_up = false;
    // Makes this class's objects for NewObject, AllocObject and C++ code; empty, a plain Object. A class of the C++ library
    // with state of its own sets it.
    std::function<Object*(Class&)> make;

    // Defining. A method with a body; a native method, whose body the game registers; a field (static ones with their
    // first value). Defining a method again replaces the body.
    Class& method(std::string_view name, std::string_view sig, Handler fn);
    Class& static_method(std::string_view name, std::string_view sig, Handler fn);
    Class& native(std::string_view name, std::string_view sig, jint modifiers = 0);
    // A method an interface (or an abstract class) declares without a body: proxies and implementing classes find it
    // by its interface, as Java code would name it.
    Class& declare(std::string_view name, std::string_view sig);
    Class& field(std::string_view name, std::string_view sig);
    Class& static_field(std::string_view name, std::string_view sig, Value value = {});

    // Looking up a method or field: this class, its superclasses, then its interfaces, as GetMethodID does. Null when
    // none of them has it.
    Method* find_method(std::string_view name, std::string_view sig) const;
    Field* find_field(std::string_view name, bool is_static) const;
    // The method RegisterNatives binds: this class's own of that name and signature, declared native here if the C++
    // library did not declare it.
    Method& registered(std::string_view name, std::string_view sig);
    // This class's own method or field, made up when it has none (JNI asked for something nothing defined).
    Method& method_or_made_up(std::string_view name, std::string_view sig, bool is_static);
    Field& field_or_made_up(std::string_view name, std::string_view sig, bool is_static);
    // The methods this class itself declares, constructors left out (getDeclaredMethods).
    std::vector<Method*> declared_methods() const;
    // Every method of this class, for the report of what nothing implements.
    std::vector<Method*> all_methods() const;
    // The fields this class itself declares (getDeclaredFields), by name.
    std::vector<Field*> declared_fields() const;
    // The implementation of `m` for objects of this class (virtual dispatch): the nearest class up the chain with the
    // same name and signature that has a body, else m itself.
    Method* resolve(Method* m);

    // True if an object of this class can be used as one of `other`: the class itself, a superclass, an interface it
    // implements (IsAssignableFrom).
    bool is(const Class* other) const;
    bool is_interface() const { return modifiers & kInterface; }
    bool is_array() const { return component != nullptr; }
    // The descriptor: "Ljava/lang/String;", "[I", "I".
    std::string descriptor() const;
    // The name Java code sees (Class.getName): "java.lang.String", "[I", "int".
    std::string java_name() const;

private:
    Method& add_method(std::string_view name, std::string_view sig, jint modifiers);
    mutable std::mutex lock_;
    // By name and signature together ("getName()Ljava/lang/String;").
    std::unordered_map<std::string, Method*> methods_;
    // By name; a class cannot have a static and an instance field of one name.
    std::unordered_map<std::string, Field*> fields_;
    // resolve()'s answers so far.
    std::unordered_map<const Method*, Method*> resolved_;
};

// java.lang.String: UTF-16 text, as Java keeps it.
class String : public Object {
public:
    String(Class* cls, std::u16string chars) : Object(cls), chars(std::move(chars)) {}
    // Set once, when the string is made or constructed (NewObject); strings never change after that.
    std::u16string chars;
    // The text in UTF-8, for C++ code; and in the modified UTF-8 JNI uses (GetStringUTFChars).
    std::string utf8() const;
    std::string mutf8() const;
};

// An array. Primitive elements are packed bytes, as JNI hands them out; object elements are references.
class Array : public Object {
public:
    Array(Class* cls, jsize length);
    const jsize length;
    // The elements' descriptor letter: 'I' for int[], 'L' or '[' for arrays of objects or arrays.
    const char type;
    std::vector<std::uint8_t> bytes;
    std::vector<Ref<Object>> items;
    bool of_objects() const { return type == 'L' || type == '['; }
    std::size_t element_size() const;
    template <class T>
    T* data() {
        return reinterpret_cast<T*>(bytes.data());
    }
};

// java.lang.Integer and the other boxes. Unity's C# unboxes what Java hands its proxies.
class Boxed : public Object {
public:
    Boxed(Class* cls, char type, Value v) : Object(cls), type(type), value(std::move(v)) {}
    const char type;
    // Set once, when the box is made or constructed.
    Value value;
};

// java.nio.ByteBuffer made by NewDirectByteBuffer, or by C++ code with memory of its own.
class Buffer : public Object {
public:
    Buffer(Class* cls, void* address, jlong capacity) : Object(cls), address(address), capacity(capacity), limit(static_cast<jint>(capacity)) {}
    void* address;
    jlong capacity;
    // Memory the buffer owns (C++ code made it), where address points.
    std::vector<std::uint8_t> own;
    jint position = 0, limit;
};

// java.lang.reflect.Method, Constructor or Field: one method or field as an object.
class Member : public Object {
public:
    Member(Class* cls, Method* method, Field* field) : Object(cls), method(method), field(field) {}
    Method* const method;
    Field* const field;
};

// An object of a proxy class: every call of its interfaces' methods goes to invoke, with the interface method as
// call.method.
class Proxy : public Object {
public:
    explicit Proxy(Class* cls) : Object(cls) {}
    Handler invoke;
};

// A method call as its C++ body sees it.
struct Call {
    Env& env;
    // The method called: for a proxy object, the interface's method.
    Method& method;
    // The object; null for a static method.
    Object* self;
    const Value* args;
    std::size_t argc;
    // Argument k as the type the signature gives it.
    jboolean z(std::size_t k) const { return args[k].z(); }
    jint i(std::size_t k) const { return args[k].i(); }
    jlong j(std::size_t k) const { return args[k].j(); }
    jfloat f(std::size_t k) const { return args[k].f(); }
    jdouble d(std::size_t k) const { return args[k].d(); }
    Object* l(std::size_t k) const { return args[k].l(); }
    // A String argument in UTF-8, "" for null.
    std::string str(std::size_t k) const;
    // An argument of a C++ class, null if it is null or of another class.
    template <class T>
    T* as(std::size_t k) const {
        return dynamic_cast<T*>(args[k].l());
    }
    // The object as the C++ class its body expects; a ClassCastException (a Java one, which the caller sees) if it is
    // another.
    template <class T>
    T& self_as() const;
};

// Thrown by a C++ body to throw a Java exception: the VM makes it the thread's pending exception and the call returns
// zero or null to its caller.
struct Throw {
    Ref<Object> exception;
};
// Throws a new exception of class cls (a Throwable) with a message.
[[noreturn]] void throw_new(std::string_view cls, std::string_view message);

template <class T>
T& Call::self_as() const {
    auto* t = dynamic_cast<T*>(self);
    if (!t) throw_new("java/lang/ClassCastException", "the object is not of the class this method's body expects");
    return *t;
}

// A thread's side of the VM: its JNIEnv, local references and pending exception. One per attached thread.
class Env {
public:
    // First member: the JNIEnv pointer native code gets is this Env.
    JNIEnv jni;
    Env();
    ~Env();
    Env(const Env&) = delete;
    Env& operator=(const Env&) = delete;
    static Env* from(JNIEnv* e) { return reinterpret_cast<Env*>(e); }
    // The calling thread's Env, null when it is not attached.
    static Env* current();

    // A new local reference to o in the open frame (null stays null).
    jobject local(Object* o);
    // The object a reference of any kind refers to.
    static Object* deref(jobject r);
    // Local frames: a native call or PushLocalFrame opens one, and closing it frees every local reference made in it.
    void push_frame();
    void pop_frame();
    void delete_local(jobject r);
    // References the thread holds now, and the slots its table has (deleted ones in the middle included), for tests and
    // leak checks: a thread that deletes as it goes must not grow its table.
    std::size_t local_count() const { return locals_.size() - nulls_; }
    std::size_t local_slots() const { return locals_.size(); }

    // The pending Java exception, or null.
    Ref<Object> pending;

    // Calling a method from C++: virtual dispatch on self for an instance method, the C++ body or the registered
    // native. A pending exception afterwards is left for the caller to look at.
    Value call(Method& m, Object* self, const Value* args, std::size_t n);
    Value call(Method& m, Object* self, std::initializer_list<Value> args) { return call(m, self, args.begin(), args.size()); }
    // The method name + sig of self's class (or of cls for a static method), made up if nothing defines it.
    Value call(Object* self, std::string_view name, std::string_view sig, std::initializer_list<Value> args = {});
    Value call_static(Class& cls, std::string_view name, std::string_view sig, std::initializer_list<Value> args = {});
    // The body of m itself, without virtual dispatch (CallNonvirtual, a proxy's own method).
    Value invoke(Method& m, Object* self, const Value* args, std::size_t n);

private:
    // Local references, in a deque so that each slot keeps its address (a local reference points at its slot).
    std::deque<Object*> locals_;
    // Slots deleted while newer ones were still in use: local_count() leaves them out.
    std::size_t nulls_ = 0;
    // Where each open frame starts in locals_.
    std::vector<std::size_t> frames_;
};

// The VM: one per process, as on Android.
JavaVM* java_vm();
// The calling thread's Env, attaching the thread first if it is not attached.
Env& attach();
// Detaches the calling thread: its local references go.
void detach();

// Defines a class, or adds to one defined before. Its superclass is defined too if it is not yet (a made-up class
// that extends java/lang/Object): the C++ library names the Android classes it extends without writing all of them.
Class& define(std::string_view name, std::string_view super = "java/lang/Object");
// Defines an interface.
Class& define_interface(std::string_view name);
// What FindClass gives: a defined class, a class made up the first time something asks for it, or null for a name
// marked absent. Array names ("[I") give array classes.
Class* find_class(std::string_view name);
// FindClass and Class.forName fail for this class (code that checks for an SDK and goes without it).
void mark_absent(std::string_view name);
// The array class of a component class, and the class of a primitive type.
Class& array_class(Class& component);
Class& primitive_class(char type);
// The class a descriptor names ("I", "Ljava/lang/String;", "[J"); the length of the descriptor at the start of s, 0 if
// there is none.
Class* class_of_descriptor(std::string_view descriptor);
std::size_t descriptor_length(std::string_view s);

// Making objects.
Ref<String> string(std::string_view utf8);
Ref<String> string16(std::u16string chars);
Ref<Array> new_array(Class& array_cls, jsize length);
// A new object of cls made by its constructor with signature ctor_sig ("()V", "(Ljava/lang/String;)V").
Ref<Object> new_object(Class& cls, std::string_view ctor_sig, std::initializer_list<Value> args = {});
// A box (java.lang.Integer for 'I', and so on).
Ref<Object> box(char type, const Value& v);
// A new exception of class cls with a message.
Ref<Object> exception(std::string_view cls, std::string_view message);
// A direct ByteBuffer over memory outside the VM, or with `size` bytes of its own.
Ref<Buffer> direct_buffer(void* address, jlong capacity);
Ref<Buffer> new_buffer(std::size_t size);

// Logs what code called that nothing implements, most called first, with counts.
void report_unimplemented();
// Every class the VM has (defined or made up), for reports such as the natives the game registered.
std::vector<Class*> all_classes();

// The java.lang classes JNI itself needs (lang.cpp). The VM defines them the first time it is used.
void define_lang();

}  // namespace jvm
