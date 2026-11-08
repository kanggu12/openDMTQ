// The java.lang classes JNI and the runtime's JNI bridge stand on: Object, Class and its reflection (the bridge reads a
// reflected method's signature through getParameterTypes and getReturnType, and finds a library's natives through
// getDeclaredMethods), ClassLoader, String, Throwable and the usual exceptions, the boxes, and ByteBuffer.
#include "internal.h"

#include <cstdio>
#include <typeinfo>

namespace jvm {

namespace {

// The object a method was called on, as the C++ class it is; Java would have thrown before calling on a wrong one.
template <class T>
T& self_as(Call& c) {
    auto* t = dynamic_cast<T*>(c.self);
    if (!t) throw_new("java/lang/ClassCastException", "not a " + std::string(typeid(T).name()));
    return *t;
}

// An array of classes (Class[]), as reflection returns parameter types.
Ref<Array> class_array(const std::vector<Class*>& classes) {
    Ref<Array> a = new_array(array_class(*core().class_class), static_cast<jsize>(classes.size()));
    for (std::size_t k = 0; k < classes.size(); ++k) a->items[k] = Ref<Object>(classes[k]);
    return a;
}

// Reflection objects for methods (Method, or Constructor for <init>).
Ref<Array> member_array(const std::vector<Method*>& methods, bool constructors) {
    Class* cls = constructors ? core().constructor : core().method;
    Ref<Array> a = new_array(array_class(*cls), static_cast<jsize>(methods.size()));
    for (std::size_t k = 0; k < methods.size(); ++k) a->items[k] = Ref<Object>(new Member(cls, methods[k], nullptr));
    return a;
}

// Java's String.hashCode: s[0]*31^(n-1) + ... + s[n-1], in 32-bit arithmetic that wraps.
jint java_hash(const std::u16string& s) {
    std::uint32_t h = 0;
    for (char16_t ch : s) h = 31 * h + ch;
    return static_cast<jint>(h);
}

// An object's identity hash: its address, without the low bits every allocation shares.
jint identity_hash(const Object* o) { return static_cast<jint>(reinterpret_cast<std::uintptr_t>(o) >> 4); }

// What Object.toString gives: the class name and the hash in hex.
std::string default_string(const Object* o) {
    char hex[16];
    std::snprintf(hex, sizeof hex, "%x", static_cast<unsigned>(identity_hash(o)));
    return o->cls()->java_name() + "@" + hex;
}

// A method's text as Method.toString writes it, near enough for logs: "public int a.B.c(int,java.lang.String)".
std::string method_text(const Method& m) {
    auto java_type = [](const std::string& d) {
        Class* c = class_of_descriptor(d);
        return c ? c->java_name() : d;
    };
    std::string s = m.is_static() ? "public static " : "public ";
    if (m.name != "<init>") s += java_type(m.ret_type) + " ";
    s += m.owner->java_name();
    if (m.name != "<init>") s += "." + m.name;
    s += "(";
    for (std::size_t k = 0; k < m.param_types.size(); ++k) s += (k ? "," : "") + java_type(m.param_types[k]);
    return s + ")";
}

void define_object() {
    Class& c = define("java/lang/Object", "");
    c.method("<init>", "()V", [](Call&) { return Value(); });
    c.method("getClass", "()Ljava/lang/Class;", [](Call& c) { return Value(c.self->cls()); });
    c.method("hashCode", "()I", [](Call& c) { return Value::I(identity_hash(c.self)); });
    c.method("equals", "(Ljava/lang/Object;)Z", [](Call& c) { return Value::Z(c.self == c.l(0)); });
    c.method("toString", "()Ljava/lang/String;", [](Call& c) { return Value(string(default_string(c.self))); });
    // One thread at a time here: waiting would only ever wait for itself.
    c.method("notify", "()V", [](Call&) { return Value(); });
    c.method("notifyAll", "()V", [](Call&) { return Value(); });
}

void define_class() {
    Class& c = define("java/lang/Class");
    c.method("getName", "()Ljava/lang/String;", [](Call& c) { return Value(string(self_as<Class>(c).java_name())); });
    c.method("getSimpleName", "()Ljava/lang/String;", [](Call& c) {
        // The part after the last dot or $ (inner classes).
        std::string n = self_as<Class>(c).java_name();
        std::size_t cut = n.find_last_of(".$");
        return Value(string(cut == std::string::npos ? n : n.substr(cut + 1)));
    });
    c.method("toString", "()Ljava/lang/String;", [](Call& c) {
        Class& k = self_as<Class>(c);
        std::string kind = k.primitive ? "" : k.is_interface() ? "interface " : "class ";
        return Value(string(kind + k.java_name()));
    });
    c.method("getDeclaredMethods", "()[Ljava/lang/reflect/Method;", [](Call& c) { return Value(member_array(self_as<Class>(c).declared_methods(), false)); });
    c.method("getMethods", "()[Ljava/lang/reflect/Method;", [](Call& c) {
        // Public methods, inherited ones too; the nearest declaration of each name and signature.
        std::vector<Method*> out;
        std::unordered_map<std::string, bool> seen;
        for (Class* k = &self_as<Class>(c); k; k = k->super) {
            for (Method* m : k->declared_methods()) {
                if (seen.emplace(m->name + m->sig, true).second) out.push_back(m);
            }
        }
        return Value(member_array(out, false));
    });
    c.method("getDeclaredConstructors", "()[Ljava/lang/reflect/Constructor;", [](Call& c) {
        std::vector<Method*> ctors;
        for (Method* m : self_as<Class>(c).all_methods()) {
            if (m->name == "<init>") ctors.push_back(m);
        }
        return Value(member_array(ctors, true));
    });
    c.method("getSuperclass", "()Ljava/lang/Class;", [](Call& c) {
        Class& k = self_as<Class>(c);
        return Value(k.is_interface() || k.primitive ? nullptr : k.super);
    });
    c.method("getInterfaces", "()[Ljava/lang/Class;", [](Call& c) { return Value(class_array(self_as<Class>(c).interfaces)); });
    c.method("getComponentType", "()Ljava/lang/Class;", [](Call& c) { return Value(self_as<Class>(c).component); });
    c.method("isArray", "()Z", [](Call& c) { return Value::Z(self_as<Class>(c).is_array()); });
    c.method("isInterface", "()Z", [](Call& c) { return Value::Z(self_as<Class>(c).is_interface()); });
    c.method("isPrimitive", "()Z", [](Call& c) { return Value::Z(self_as<Class>(c).primitive != 0); });
    c.method("getModifiers", "()I", [](Call& c) { return Value::I(self_as<Class>(c).modifiers); });
    c.method("isInstance", "(Ljava/lang/Object;)Z", [](Call& c) { return Value::Z(c.l(0) && c.l(0)->cls()->is(&self_as<Class>(c))); });
    c.method("isAssignableFrom", "(Ljava/lang/Class;)Z", [](Call& c) {
        auto* other = c.as<Class>(0);
        if (!other) throw_new("java/lang/NullPointerException", "isAssignableFrom(null)");
        return Value::Z(other->is(&self_as<Class>(c)));
    });
    // Every class shares the one loader there is.
    c.method("getClassLoader", "()Ljava/lang/ClassLoader;", [](Call&) { return Value(system_loader()); });
    c.method("getMethod", "(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;", [](Call& c) { return Value(reflect_method(self_as<Class>(c), c.str(0), c.as<Array>(1), false)); });
    c.method("getDeclaredMethod", "(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;", [](Call& c) { return Value(reflect_method(self_as<Class>(c), c.str(0), c.as<Array>(1), false)); });
    c.method("getConstructor", "([Ljava/lang/Class;)Ljava/lang/reflect/Constructor;", [](Call& c) { return Value(reflect_method(self_as<Class>(c), "<init>", c.as<Array>(0), true)); });
    c.method("getDeclaredConstructor", "([Ljava/lang/Class;)Ljava/lang/reflect/Constructor;", [](Call& c) { return Value(reflect_method(self_as<Class>(c), "<init>", c.as<Array>(0), true)); });
    // Class.forName: the class, made up if nothing defined it (as FindClass), or ClassNotFoundException for a name
    // marked absent.
    auto for_name = [](Call& c) {
        std::string name = c.str(0);
        Class* k = find_class(name);
        if (!k) throw_new("java/lang/ClassNotFoundException", name);
        return Value(k);
    };
    c.static_method("forName", "(Ljava/lang/String;)Ljava/lang/Class;", for_name);
    c.static_method("forName", "(Ljava/lang/String;ZLjava/lang/ClassLoader;)Ljava/lang/Class;", for_name);
}

void define_class_loader() {
    Class& c = define("java/lang/ClassLoader");
    auto load = [](Call& c) {
        std::string name = c.str(0);
        Class* k = find_class(name);
        if (!k) throw_new("java/lang/ClassNotFoundException", name);
        return Value(k);
    };
    c.method("loadClass", "(Ljava/lang/String;)Ljava/lang/Class;", load);
    c.method("loadClass", "(Ljava/lang/String;Z)Ljava/lang/Class;", load);
    c.method("getParent", "()Ljava/lang/ClassLoader;", [](Call&) { return Value(); });
    c.static_method("getSystemClassLoader", "()Ljava/lang/ClassLoader;", [](Call&) { return Value(system_loader()); });
    // Android's app loader is a PathClassLoader; Unity names it in a log line now and then.
    define("dalvik/system/BaseDexClassLoader", "java/lang/ClassLoader");
    define("dalvik/system/PathClassLoader", "dalvik/system/BaseDexClassLoader");
}

void define_string() {
    Class& c = define("java/lang/String");
    // Strings made through NewObject start empty and are filled by their constructor.
    c.make = [](Class& k) -> Object* { return new String(&k, {}); };
    c.method("<init>", "()V", [](Call&) { return Value(); });
    c.method("<init>", "(Ljava/lang/String;)V", [](Call& c) {
        auto* from = c.as<String>(0);
        if (from) self_as<String>(c).chars = from->chars;
        return Value();
    });
    // Bytes as UTF-8 whatever the charset named: the game's text is UTF-8 or ASCII.
    auto from_bytes = [](Call& c) {
        auto* bytes = c.as<Array>(0);
        if (bytes) self_as<String>(c).chars = utf16_of(std::string_view(reinterpret_cast<const char*>(bytes->bytes.data()), bytes->bytes.size()));
        return Value();
    };
    c.method("<init>", "([B)V", from_bytes);
    c.method("<init>", "([BLjava/lang/String;)V", from_bytes);
    c.method("toString", "()Ljava/lang/String;", [](Call& c) { return Value(c.self); });
    c.method("length", "()I", [](Call& c) { return Value::I(static_cast<jint>(self_as<String>(c).chars.size())); });
    c.method("isEmpty", "()Z", [](Call& c) { return Value::Z(self_as<String>(c).chars.empty()); });
    c.method("hashCode", "()I", [](Call& c) { return Value::I(java_hash(self_as<String>(c).chars)); });
    c.method("equals", "(Ljava/lang/Object;)Z", [](Call& c) {
        auto* other = c.as<String>(0);
        return Value::Z(other && other->chars == self_as<String>(c).chars);
    });
    c.method("charAt", "(I)C", [](Call& c) {
        const std::u16string& s = self_as<String>(c).chars;
        jint i = c.i(0);
        if (i < 0 || static_cast<std::size_t>(i) >= s.size()) throw_new("java/lang/StringIndexOutOfBoundsException", std::to_string(i));
        return Value::C(s[static_cast<std::size_t>(i)]);
    });
    auto to_bytes = [](Call& c) {
        std::string text = self_as<String>(c).utf8();
        Ref<Array> a = new_array(array_class(primitive_class('B')), static_cast<jsize>(text.size()));
        std::copy(text.begin(), text.end(), a->bytes.begin());
        return Value(a);
    };
    c.method("getBytes", "()[B", to_bytes);
    c.method("getBytes", "(Ljava/lang/String;)[B", to_bytes);
}

void define_throwable() {
    Class& c = define("java/lang/Throwable");
    c.field("detailMessage", "Ljava/lang/String;");
    c.field("cause", "Ljava/lang/Throwable;");
    Field* message = c.find_field("detailMessage", false);
    Field* cause = c.find_field("cause", false);
    c.method("<init>", "()V", [](Call&) { return Value(); });
    c.method("<init>", "(Ljava/lang/String;)V", [message](Call& c) {
        c.self->set_field(message, Value(c.l(0)));
        return Value();
    });
    c.method("<init>", "(Ljava/lang/String;Ljava/lang/Throwable;)V", [message, cause](Call& c) {
        c.self->set_field(message, Value(c.l(0)));
        c.self->set_field(cause, Value(c.l(1)));
        return Value();
    });
    c.method("<init>", "(Ljava/lang/Throwable;)V", [cause](Call& c) {
        c.self->set_field(cause, Value(c.l(0)));
        return Value();
    });
    c.method("getMessage", "()Ljava/lang/String;", [message](Call& c) { return c.self->field(message); });
    c.method("getLocalizedMessage", "()Ljava/lang/String;", [message](Call& c) { return c.self->field(message); });
    c.method("getCause", "()Ljava/lang/Throwable;", [cause](Call& c) { return c.self->field(cause); });
    c.method("toString", "()Ljava/lang/String;", [](Call& c) {
        std::string m = message_of(c.self);
        return Value(string(c.self->cls()->java_name() + (m.empty() ? "" : ": " + m)));
    });
    c.method("printStackTrace", "()V", [](Call& c) {
        log("jvm: %s: %s", c.self->cls()->java_name().c_str(), message_of(c.self).c_str());
        return Value();
    });
    // No Java frames run here: the trace is empty.
    define("java/lang/StackTraceElement");
    c.method("getStackTrace", "()[Ljava/lang/StackTraceElement;", [](Call&) { return Value(new_array(array_class(*find_class("java/lang/StackTraceElement")), 0)); });
    // The usual exceptions, with their places in the hierarchy (catching code tests them with IsInstanceOf).
    const std::pair<const char*, const char*> family[] = {
        {"java/lang/Exception", "java/lang/Throwable"},
        {"java/lang/Error", "java/lang/Throwable"},
        {"java/lang/RuntimeException", "java/lang/Exception"},
        {"java/lang/ReflectiveOperationException", "java/lang/Exception"},
        {"java/lang/ClassNotFoundException", "java/lang/ReflectiveOperationException"},
        {"java/lang/NoSuchMethodException", "java/lang/ReflectiveOperationException"},
        {"java/lang/NoSuchFieldException", "java/lang/ReflectiveOperationException"},
        {"java/lang/InterruptedException", "java/lang/Exception"},
        {"java/io/IOException", "java/lang/Exception"},
        {"java/io/FileNotFoundException", "java/io/IOException"},
        {"java/lang/NullPointerException", "java/lang/RuntimeException"},
        {"java/lang/IllegalArgumentException", "java/lang/RuntimeException"},
        {"java/lang/IllegalStateException", "java/lang/RuntimeException"},
        {"java/lang/UnsupportedOperationException", "java/lang/RuntimeException"},
        {"java/lang/ClassCastException", "java/lang/RuntimeException"},
        {"java/lang/IndexOutOfBoundsException", "java/lang/RuntimeException"},
        {"java/lang/ArrayIndexOutOfBoundsException", "java/lang/IndexOutOfBoundsException"},
        {"java/lang/StringIndexOutOfBoundsException", "java/lang/IndexOutOfBoundsException"},
        {"java/lang/NegativeArraySizeException", "java/lang/RuntimeException"},
        {"java/lang/SecurityException", "java/lang/RuntimeException"},
        {"java/lang/LinkageError", "java/lang/Error"},
        {"java/lang/NoClassDefFoundError", "java/lang/LinkageError"},
        {"java/lang/UnsatisfiedLinkError", "java/lang/LinkageError"},
        {"java/lang/IncompatibleClassChangeError", "java/lang/LinkageError"},
        {"java/lang/NoSuchMethodError", "java/lang/IncompatibleClassChangeError"},
        {"java/lang/NoSuchFieldError", "java/lang/IncompatibleClassChangeError"},
        {"java/lang/VirtualMachineError", "java/lang/Error"},
        {"java/lang/OutOfMemoryError", "java/lang/VirtualMachineError"},
    };
    for (auto& [name, super] : family) define(name, super);
}

void define_reflection() {
    // Method and Constructor share their reflection: the member's method says what it is.
    for (Class* k : {core().method, core().constructor}) {
        Class& c = *k;
        c.method("getName", "()Ljava/lang/String;", [](Call& c) {
            Method* m = self_as<Member>(c).method;
            // A constructor's name is its class's.
            return Value(string(m->name == "<init>" ? m->owner->java_name() : m->name));
        });
        c.method("getParameterTypes", "()[Ljava/lang/Class;", [](Call& c) {
            std::vector<Class*> types;
            for (const std::string& d : self_as<Member>(c).method->param_types) types.push_back(class_of_descriptor(d));
            return Value(class_array(types));
        });
        c.method("getReturnType", "()Ljava/lang/Class;", [](Call& c) { return Value(class_of_descriptor(self_as<Member>(c).method->ret_type)); });
        c.method("getModifiers", "()I", [](Call& c) { return Value::I(self_as<Member>(c).method->modifiers); });
        c.method("getDeclaringClass", "()Ljava/lang/Class;", [](Call& c) { return Value(self_as<Member>(c).method->owner); });
        c.method("toString", "()Ljava/lang/String;", [](Call& c) { return Value(string(method_text(*self_as<Member>(c).method))); });
        c.method("hashCode", "()I", [](Call& c) { return Value::I(identity_hash(reinterpret_cast<Object*>(self_as<Member>(c).method))); });
        c.method("equals", "(Ljava/lang/Object;)Z", [](Call& c) {
            auto* other = c.as<Member>(0);
            return Value::Z(other && other->method == self_as<Member>(c).method);
        });
    }
    Class& f = *core().field;
    f.method("getName", "()Ljava/lang/String;", [](Call& c) { return Value(string(self_as<Member>(c).field->name)); });
    f.method("getType", "()Ljava/lang/Class;", [](Call& c) { return Value(class_of_descriptor(self_as<Member>(c).field->sig)); });
    f.method("getModifiers", "()I", [](Call& c) { return Value::I(kPublic | (self_as<Member>(c).field->is_static ? kStatic : 0)); });
    f.method("getDeclaringClass", "()Ljava/lang/Class;", [](Call& c) { return Value(self_as<Member>(c).field->owner); });
}

void define_boxes() {
    // Each box makes its own kind of object, and its constructor and valueOf take the primitive.
    const std::pair<char, const char*> boxes[] = {
        {'Z', "(Z)"}, {'B', "(B)"}, {'C', "(C)"}, {'S', "(S)"}, {'I', "(I)"}, {'J', "(J)"}, {'F', "(F)"}, {'D', "(D)"},
    };
    for (auto& [type, params] : boxes) {
        Class& c = *core().boxes.at(type);
        const char t = type;
        c.make = [t](Class& k) -> Object* { return new Boxed(&k, t, Value()); };
        c.method("<init>", std::string(params) + "V", [](Call& c) {
            self_as<Boxed>(c).value = c.args[0];
            return Value();
        });
        c.static_method("valueOf", std::string(params) + c.descriptor(), [t](Call& c) { return Value(box(t, c.args[0])); });
        c.method("hashCode", "()I", [](Call& c) {
            // Java's: the value for int and narrower, the two halves xored for long.
            const Boxed& b = self_as<Boxed>(c);
            jlong v = b.type == 'J' ? b.value.j() : b.type == 'Z' ? (b.value.z() ? 1231 : 1237) : b.value.i();
            return Value::I(static_cast<jint>(v ^ (v >> 32)));
        });
        c.method("equals", "(Ljava/lang/Object;)Z", [](Call& c) {
            auto* other = c.as<Boxed>(0);
            const Boxed& b = self_as<Boxed>(c);
            return Value::Z(other && other->type == b.type && other->value.raw().j == b.value.raw().j);
        });
    }
    // Number's accessors convert, as Java's do (a Long asked for intValue gives its low half).
    auto number = [](const Boxed& b) -> double {
        switch (b.type) {
        case 'J': return static_cast<double>(b.value.j());
        case 'F': return b.value.f();
        case 'D': return b.value.d();
        case 'B': return b.value.b();
        case 'S': return b.value.s();
        case 'C': return b.value.c();
        case 'Z': return b.value.z();
        default: return b.value.i();
        }
    };
    auto integer = [](const Boxed& b) -> jlong {
        switch (b.type) {
        case 'J': return b.value.j();
        case 'F': return static_cast<jlong>(b.value.f());
        case 'D': return static_cast<jlong>(b.value.d());
        case 'B': return b.value.b();
        case 'S': return b.value.s();
        case 'C': return b.value.c();
        case 'Z': return b.value.z();
        default: return b.value.i();
        }
    };
    Class& n = define("java/lang/Number");
    n.method("intValue", "()I", [integer](Call& c) { return Value::I(static_cast<jint>(integer(self_as<Boxed>(c)))); });
    n.method("longValue", "()J", [integer](Call& c) { return Value::J(integer(self_as<Boxed>(c))); });
    n.method("shortValue", "()S", [integer](Call& c) { return Value::S(static_cast<jshort>(integer(self_as<Boxed>(c)))); });
    n.method("byteValue", "()B", [integer](Call& c) { return Value::B(static_cast<jbyte>(integer(self_as<Boxed>(c)))); });
    n.method("floatValue", "()F", [number](Call& c) { return Value::F(static_cast<jfloat>(number(self_as<Boxed>(c)))); });
    n.method("doubleValue", "()D", [number](Call& c) { return Value::D(number(self_as<Boxed>(c))); });
    core().boxes.at('Z')->method("booleanValue", "()Z", [](Call& c) { return Value::Z(self_as<Boxed>(c).value.z()); });
    core().boxes.at('C')->method("charValue", "()C", [](Call& c) { return Value::C(self_as<Boxed>(c).value.c()); });
    for (auto& [type, cls] : core().boxes) {
        cls->method("toString", "()Ljava/lang/String;", [number, integer](Call& c) {
            const Boxed& b = self_as<Boxed>(c);
            if (b.type == 'Z') return Value(string(b.value.z() ? "true" : "false"));
            if (b.type == 'C') return Value(string16(std::u16string(1, static_cast<char16_t>(b.value.c()))));
            if (b.type == 'F' || b.type == 'D') {
                char text[32];
                std::snprintf(text, sizeof text, "%g", number(b));
                return Value(string(text));
            }
            return Value(string(std::to_string(integer(b))));
        });
    }
}

void define_buffers() {
    Class& c = define("java/nio/ByteBuffer", "java/nio/Buffer");
    c.static_method("allocateDirect", "(I)Ljava/nio/ByteBuffer;", [](Call& c) {
        if (c.i(0) < 0) throw_new("java/lang/IllegalArgumentException", "negative capacity");
        return Value(new_buffer(static_cast<std::size_t>(c.i(0))));
    });
    Class& b = define("java/nio/Buffer");
    b.method("capacity", "()I", [](Call& c) { return Value::I(static_cast<jint>(self_as<Buffer>(c).capacity)); });
    b.method("position", "()I", [](Call& c) { return Value::I(self_as<Buffer>(c).position); });
    b.method("limit", "()I", [](Call& c) { return Value::I(self_as<Buffer>(c).limit); });
    b.method("remaining", "()I", [](Call& c) {
        const Buffer& buf = self_as<Buffer>(c);
        return Value::I(buf.limit - buf.position);
    });
    b.method("isDirect", "()Z", [](Call&) { return Value::Z(true); });
    b.method("isReadOnly", "()Z", [](Call&) { return Value::Z(false); });
    // The setters return the buffer itself, as Java's do (they chain).
    b.method("position", "(I)Ljava/nio/Buffer;", [](Call& c) {
        self_as<Buffer>(c).position = c.i(0);
        return Value(c.self);
    });
    b.method("limit", "(I)Ljava/nio/Buffer;", [](Call& c) {
        self_as<Buffer>(c).limit = c.i(0);
        return Value(c.self);
    });
    b.method("clear", "()Ljava/nio/Buffer;", [](Call& c) {
        Buffer& buf = self_as<Buffer>(c);
        buf.position = 0;
        buf.limit = static_cast<jint>(buf.capacity);
        return Value(c.self);
    });
    b.method("flip", "()Ljava/nio/Buffer;", [](Call& c) {
        Buffer& buf = self_as<Buffer>(c);
        buf.limit = buf.position;
        buf.position = 0;
        return Value(c.self);
    });
    b.method("rewind", "()Ljava/nio/Buffer;", [](Call& c) {
        self_as<Buffer>(c).position = 0;
        return Value(c.self);
    });
}

}  // namespace

Object* system_loader() {
    // One loader object for every class, made on first use.
    static Ref<Object>* loader = new Ref<Object>(new Object(find_class("dalvik/system/PathClassLoader")));
    return loader->get();
}

Ref<Object> reflect_method(Class& cls, const std::string& name, Array* params, bool constructor) {
    // The parameter classes make the descriptor; the return type is whatever the class has under that name.
    std::string sig = "(";
    if (params) {
        for (auto& p : params->items) {
            auto* k = dynamic_cast<Class*>(p.get());
            if (k) sig += k->descriptor();
        }
    }
    sig += ")";
    std::vector<Method*> candidates;
    for (Class* k = &cls; k; k = constructor ? nullptr : k->super) {
        for (Method* m : constructor ? k->all_methods() : k->declared_methods()) {
            if (m->name == name && m->sig.compare(0, sig.size(), sig) == 0) candidates.push_back(m);
        }
        if (!candidates.empty()) break;
    }
    if (candidates.empty()) throw_new("java/lang/NoSuchMethodException", cls.java_name() + "." + name + sig);
    Class* kind = constructor ? core().constructor : core().method;
    return Ref<Object>(new Member(kind, candidates.front(), nullptr));
}

void define_lang() {
    define_object();
    define_class();
    define_class_loader();
    define_string();
    define_throwable();
    define_reflection();
    define_boxes();
    define_buffers();
    // java.lang.reflect.Array.newInstance: an array of a component class.
    jvm::define("java/lang/reflect/Array").static_method("newInstance", "(Ljava/lang/Class;I)Ljava/lang/Object;", [](Call& c) {
        auto* k = c.as<Class>(0);
        if (!k) throw_new("java/lang/NullPointerException", "Array.newInstance(null)");
        if (c.i(1) < 0) throw_new("java/lang/NegativeArraySizeException", std::to_string(c.i(1)));
        return Value(new_array(array_class(*k), c.i(1)));
    });
    // Interfaces the VM's own classes name.
    define_interface("java/lang/Runnable");
    define_interface("java/lang/Cloneable");
    define_interface("java/io/Serializable");
    define_interface("java/lang/reflect/InvocationHandler");
}

}  // namespace jvm
