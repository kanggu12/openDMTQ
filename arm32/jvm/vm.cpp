// The VM's core: the class registry, objects and their fields, method lookup and dispatch, references, strings, and
// calls from C++ into methods (C++ bodies, or the game's native code through the platform's calling convention).
#include "jvm.h"
#include "internal.h"

#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <memory>
#include <shared_mutex>
#include <unordered_set>

namespace jvm {

// ---------------------------------------------------------------------------------------------------------------------
// The log.

namespace {
// Where lines go; stderr until the host program says otherwise.
void (*g_sink)(const char*) = nullptr;
}  // namespace

void log(const char* fmt, ...) {
    // One line, cut at the runtime log's own line size.
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    std::vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    if (g_sink) g_sink(buf);
    else std::fprintf(stderr, "%s\n", buf);
}

void set_log_sink(void (*sink)(const char* line)) { g_sink = sink; }

// ---------------------------------------------------------------------------------------------------------------------
// The registry: every class by name, the VM's global references, and the classes the VM itself uses often.

namespace {

struct Registry {
    // Class lookups far outnumber definitions: readers share the lock.
    std::shared_mutex lock;
    std::unordered_map<std::string, Class*> classes;
    // Names FindClass fails for (mark_absent).
    std::unordered_set<std::string> absent;
    // Global and weak global references: slots in a deque keep their addresses, freed slots are taken again first.
    std::mutex globals_lock;
    std::deque<Object*> globals;
    std::vector<Object**> free_globals;
    // The JavaVM native code gets: a pointer to the invocation table.
    JavaVM vm{};
    Core core;

    Registry();
    // A class with a superclass, made without the lazy java.lang definitions (the registry uses it while it is built).
    Class* make(const std::string& name, Class* super, jint modifiers = kPublic);
};

// Never destroyed: threads may still release objects (and so take the fields lock) while the process exits.
Registry& reg() {
    static Registry* r = new Registry;
    return *r;
}

// One lock for every object's fields and the static fields (fields are rare: the C++ classes keep C++ members).
std::mutex& fields_lock() {
    static auto* m = new std::mutex;
    return *m;
}

Registry::Registry() {
    vm.functions = &kInvokeInterface;
    // java/lang/Object first, then java/lang/Class, which is the class of every class, itself included: the first two
    // get their class once it exists.
    Class* object = new Class(nullptr, "java/lang/Object");
    Class* class_class = new Class(nullptr, "java/lang/Class");
    class_class->super = object;
    for (Class* c : {object, class_class}) {
        set_class(*c, class_class);
        // The registry holds every class for good.
        c->retain();
        classes.emplace(c->name, c);
    }
    core.object = object;
    core.class_class = class_class;
    // The rest of what the VM itself makes: strings, exceptions, reflection, boxes, buffers, proxies.
    core.string = make("java/lang/String", object, kPublic | kFinal);
    core.throwable = make("java/lang/Throwable", object);
    Class* exception = make("java/lang/Exception", core.throwable);
    Class* runtime = make("java/lang/RuntimeException", exception);
    make("java/lang/Error", core.throwable);
    core.null_pointer = make("java/lang/NullPointerException", runtime);
    Class* accessible = make("java/lang/reflect/AccessibleObject", object);
    Class* executable = make("java/lang/reflect/Executable", accessible);
    core.method = make("java/lang/reflect/Method", executable, kPublic | kFinal);
    core.constructor = make("java/lang/reflect/Constructor", executable, kPublic | kFinal);
    core.field = make("java/lang/reflect/Field", accessible, kPublic | kFinal);
    core.proxy = make("java/lang/reflect/Proxy", object);
    Class* number = make("java/lang/Number", object, kPublic | kAbstract);
    const std::pair<char, const char*> boxes[] = {
        {'Z', "java/lang/Boolean"}, {'B', "java/lang/Byte"},  {'C', "java/lang/Character"}, {'S', "java/lang/Short"},
        {'I', "java/lang/Integer"}, {'J', "java/lang/Long"},  {'F', "java/lang/Float"},     {'D', "java/lang/Double"},
    };
    for (auto& [type, name] : boxes) {
        // Boolean and Character are not numbers in Java.
        Class* super = type == 'Z' || type == 'C' ? object : number;
        core.boxes[type] = make(name, super, kPublic | kFinal);
    }
    Class* buffer = make("java/nio/Buffer", object, kPublic | kAbstract);
    Class* byte_buffer = make("java/nio/ByteBuffer", buffer, kPublic | kAbstract);
    core.direct_buffer = make("java/nio/DirectByteBuffer", byte_buffer);
    // The primitive types' classes (int.class), which reflection hands out as parameter and return types.
    const std::pair<char, const char*> primitives[] = {
        {'Z', "boolean"}, {'B', "byte"}, {'C', "char"},  {'S', "short"}, {'I', "int"},
        {'J', "long"},    {'F', "float"}, {'D', "double"}, {'V', "void"},
    };
    for (auto& [type, name] : primitives) {
        auto* c = new Class(class_class, name);
        c->primitive = type;
        c->modifiers = kPublic | kFinal | kAbstract;
        c->retain();
        // Not in the name table: FindClass("int") finds nothing on Android either.
        core.primitives[type] = c;
    }
}

Class* Registry::make(const std::string& name, Class* super, jint modifiers) {
    auto* c = new Class(core.class_class, name);
    c->super = super;
    c->modifiers = modifiers;
    c->retain();
    classes.emplace(name, c);
    return c;
}

// Defines java.lang the first time anything outside the registry needs the VM. The lock is recursive: define_lang
// itself calls back in (define(), string()) on the same thread, and finds the state past 0 and goes on. Other threads
// wait until it is done.
void ready() {
    static std::atomic<int> state{0};
    if (state.load(std::memory_order_acquire) == 2) return;
    static auto* boot = new std::recursive_mutex;
    std::lock_guard<std::recursive_mutex> l(*boot);
    if (state.load(std::memory_order_relaxed) != 0) return;
    state.store(1, std::memory_order_relaxed);
    reg();
    define_lang();
    state.store(2, std::memory_order_release);
}

}  // namespace

const Core& core() {
    ready();
    return reg().core;
}

void set_class(Object& o, Class* cls) { o.cls_ = cls; }

// ---------------------------------------------------------------------------------------------------------------------
// Objects.

Object::~Object() {
    delete fields_;
    delete monitor_.load(std::memory_order_relaxed);
}

Value::Value(Object* o) : obj_(o) { prim_.j = 0; }

Value Object::field(const Field* f) const {
    std::lock_guard<std::mutex> l(fields_lock());
    if (!fields_) return {};
    auto it = fields_->find(f);
    return it == fields_->end() ? Value{} : it->second;
}

void Object::set_field(const Field* f, const Value& v) {
    // The old value (an object, perhaps the last reference to it) is released after the lock, by `old` going.
    Value old;
    std::lock_guard<std::mutex> l(fields_lock());
    if (!fields_) fields_ = new std::unordered_map<const Field*, Value>;
    Value& slot = (*fields_)[f];
    old = slot;
    slot = v;
}

std::recursive_mutex& Object::monitor() {
    std::recursive_mutex* m = monitor_.load(std::memory_order_acquire);
    if (m) return *m;
    // Two threads may race to make it: the one that loses frees its own and takes the winner's.
    auto* fresh = new std::recursive_mutex;
    if (monitor_.compare_exchange_strong(m, fresh, std::memory_order_acq_rel)) return *fresh;
    delete fresh;
    return *m;
}

// ---------------------------------------------------------------------------------------------------------------------
// Signatures.

// The length of the descriptor at the start of s ("I", "Ljava/lang/String;", "[[J"), 0 if there is none.
std::size_t descriptor_length(std::string_view s) {
    std::size_t i = 0;
    // Array dimensions first.
    while (i < s.size() && s[i] == '[') ++i;
    if (i >= s.size()) return 0;
    if (s[i] == 'L') {
        std::size_t end = s.find(';', i);
        return end == std::string_view::npos ? 0 : end + 1;
    }
    // A primitive (V only as a return type, which the caller checks for).
    return std::strchr("ZBCSIJFDV", s[i]) ? i + 1 : 0;
}

bool parse_signature(std::string_view sig, Method& m) {
    m.params.clear();
    m.param_types.clear();
    if (sig.empty() || sig[0] != '(') return false;
    std::size_t i = 1;
    while (i < sig.size() && sig[i] != ')') {
        std::size_t n = descriptor_length(sig.substr(i));
        // A void parameter is no parameter.
        if (!n || sig[i] == 'V') return false;
        m.params.push_back(sig[i]);
        m.param_types.emplace_back(sig.substr(i, n));
        i += n;
    }
    if (i >= sig.size()) return false;
    std::string_view ret = sig.substr(i + 1);
    if (descriptor_length(ret) != ret.size() || ret.empty()) return false;
    m.ret_type = std::string(ret);
    m.ret = ret[0];
    return true;
}

// ---------------------------------------------------------------------------------------------------------------------
// Classes.

Class::Class(Class* class_class, std::string name) : Object(class_class), name(std::move(name)) {}

Method& Class::add_method(std::string_view name, std::string_view sig, jint modifiers) {
    std::string key = std::string(name) + std::string(sig);
    std::lock_guard<std::mutex> l(lock_);
    Method*& m = methods_[key];
    if (!m) {
        m = new Method;
        m->owner = this;
        m->name = std::string(name);
        m->sig = std::string(sig);
        if (!parse_signature(sig, *m)) log("jvm: %s.%s: cannot read the signature %s", this->name.c_str(), m->name.c_str(), m->sig.c_str());
    }
    // A definition makes a method real, whatever a JNI lookup made up before.
    m->modifiers = modifiers;
    m->made_up = false;
    // Dispatch answers may change with the new method.
    resolved_.clear();
    return *m;
}

Class& Class::method(std::string_view name, std::string_view sig, Handler fn) {
    add_method(name, sig, kPublic).fn = std::move(fn);
    return *this;
}

Class& Class::static_method(std::string_view name, std::string_view sig, Handler fn) {
    add_method(name, sig, kPublic | kStatic).fn = std::move(fn);
    return *this;
}

Class& Class::native(std::string_view name, std::string_view sig, jint modifiers) {
    add_method(name, sig, kPublic | kNative | modifiers);
    return *this;
}

Class& Class::declare(std::string_view name, std::string_view sig) {
    add_method(name, sig, kPublic | kAbstract);
    return *this;
}

Class& Class::field(std::string_view name, std::string_view sig) {
    std::lock_guard<std::mutex> l(lock_);
    Field*& f = fields_[std::string(name)];
    if (!f) f = new Field;
    f->owner = this;
    f->name = std::string(name);
    f->sig = std::string(sig);
    f->type = sig.empty() ? 'I' : sig[0];
    f->is_static = false;
    f->made_up = false;
    return *this;
}

Class& Class::static_field(std::string_view name, std::string_view sig, Value value) {
    Field* f;
    {
        std::lock_guard<std::mutex> l(lock_);
        Field*& slot = fields_[std::string(name)];
        if (!slot) slot = new Field;
        f = slot;
        f->owner = this;
        f->name = std::string(name);
        f->sig = std::string(sig);
        f->type = sig.empty() ? 'I' : sig[0];
        f->is_static = true;
        f->made_up = false;
    }
    std::lock_guard<std::mutex> l(fields_lock());
    f->value = std::move(value);
    return *this;
}

Method& Class::registered(std::string_view name, std::string_view sig) {
    std::string key = std::string(name) + std::string(sig);
    {
        std::lock_guard<std::mutex> l(lock_);
        auto it = methods_.find(key);
        if (it != methods_.end()) {
            // Declared or made up before: a native now, whatever the lookup that made it up thought.
            it->second->modifiers |= kNative;
            it->second->made_up = false;
            return *it->second;
        }
    }
    // Not declared: an instance method as far as the VM knows (C++ code calling it says which it is by how it calls).
    if (trace_on()) log("jvm: %s.%s%s registered without a declaration", this->name.c_str(), std::string(name).c_str(), std::string(sig).c_str());
    return add_method(name, sig, kPublic | kNative);
}

Method* Class::find_method(std::string_view name, std::string_view sig) const {
    std::string key = std::string(name) + std::string(sig);
    {
        std::lock_guard<std::mutex> l(lock_);
        auto it = methods_.find(key);
        if (it != methods_.end()) return it->second;
    }
    // Constructors are not inherited.
    if (name == "<init>") return nullptr;
    if (super) {
        if (Method* m = super->find_method(name, sig)) return m;
    }
    for (Class* i : interfaces) {
        if (Method* m = i->find_method(name, sig)) return m;
    }
    // An interface's methods include java/lang/Object's (toString, hashCode).
    if (is_interface() && this != reg().core.object) return reg().core.object->find_method(name, sig);
    return nullptr;
}

Field* Class::find_field(std::string_view name, bool is_static) const {
    {
        std::lock_guard<std::mutex> l(lock_);
        auto it = fields_.find(std::string(name));
        if (it != fields_.end() && it->second->is_static == is_static) return it->second;
    }
    if (super) {
        if (Field* f = super->find_field(name, is_static)) return f;
    }
    // Interfaces hold constants (static fields) only.
    if (is_static) {
        for (Class* i : interfaces) {
            if (Field* f = i->find_field(name, true)) return f;
        }
    }
    return nullptr;
}

Method& Class::method_or_made_up(std::string_view name, std::string_view sig, bool is_static) {
    if (Method* m = find_method(name, sig)) return *m;
    // A proxy class's methods are its interfaces': one nothing declares is made up there, so that its declaring class is
    // the interface, as the proxy's handler reports it.
    if (proxy && !interfaces.empty() && name != "<init>") return interfaces.front()->method_or_made_up(name, sig, is_static);
    std::string key = std::string(name) + std::string(sig);
    std::lock_guard<std::mutex> l(lock_);
    // Another thread may have made it meanwhile.
    Method*& m = methods_[key];
    if (!m) {
        m = new Method;
        m->owner = this;
        m->name = std::string(name);
        m->sig = std::string(sig);
        m->modifiers = kPublic | (is_static ? kStatic : 0);
        m->made_up = true;
        if (!parse_signature(sig, *m)) log("jvm: %s.%s: cannot read the signature %s", this->name.c_str(), m->name.c_str(), m->sig.c_str());
        resolved_.clear();
    }
    return *m;
}

Field& Class::field_or_made_up(std::string_view name, std::string_view sig, bool is_static) {
    if (Field* f = find_field(name, is_static)) return *f;
    std::lock_guard<std::mutex> l(lock_);
    Field*& f = fields_[std::string(name)];
    if (!f) {
        f = new Field;
        f->owner = this;
        f->name = std::string(name);
        f->sig = std::string(sig);
        f->type = sig.empty() ? 'I' : sig[0];
        f->is_static = is_static;
        f->made_up = true;
    }
    return *f;
}

std::vector<Method*> Class::declared_methods() const {
    std::vector<Method*> out;
    std::lock_guard<std::mutex> l(lock_);
    for (auto& [key, m] : methods_) {
        if (m->name != "<init>" && m->name != "<clinit>") out.push_back(m);
    }
    // A stable order (by name, then signature), as tests and logs want.
    std::sort(out.begin(), out.end(), [](Method* a, Method* b) { return a->name != b->name ? a->name < b->name : a->sig < b->sig; });
    return out;
}

std::vector<Field*> Class::declared_fields() const {
    std::vector<Field*> out;
    std::lock_guard<std::mutex> l(lock_);
    for (auto& [name, f] : fields_) out.push_back(f);
    std::sort(out.begin(), out.end(), [](Field* a, Field* b) { return a->name < b->name; });
    return out;
}

std::vector<Method*> Class::all_methods() const {
    std::vector<Method*> out;
    std::lock_guard<std::mutex> l(lock_);
    for (auto& [key, m] : methods_) out.push_back(m);
    return out;
}

Method* Class::resolve(Method* m) {
    // Statics and constructors are what they are.
    if (m->is_static() || m->name == "<init>") return m;
    {
        std::lock_guard<std::mutex> l(lock_);
        auto it = resolved_.find(m);
        if (it != resolved_.end()) return it->second;
    }
    // The nearest declaration up the superclass chain, then in the interfaces (a proxy-free class implementing an
    // interface method declares it itself, so these are the interface's own made-up or defined methods).
    std::string key = m->name + m->sig;
    Method* found = nullptr;
    for (const Class* c = this; c && !found; c = c->super) {
        std::lock_guard<std::mutex> l(c->lock_);
        auto it = c->methods_.find(key);
        if (it != c->methods_.end()) found = it->second;
    }
    if (!found) found = m;
    std::lock_guard<std::mutex> l(lock_);
    resolved_.emplace(m, found);
    return found;
}

bool Class::is(const Class* other) const {
    if (this == other) return true;
    if (!other) return false;
    // Every reference type is an Object; primitives are not.
    if (other == reg().core.object) return !primitive;
    // Arrays: by their elements (String[] is an Object[]), and every array is Cloneable and Serializable.
    if (component) {
        if (other->component) return component->primitive ? component == other->component : component->is(other->component);
        return other->name == "java/lang/Cloneable" || other->name == "java/io/Serializable";
    }
    for (const Class* c = this; c; c = c->super) {
        if (c == other) return true;
        for (const Class* i : c->interfaces) {
            if (i->is(other)) return true;
        }
    }
    return false;
}

std::string Class::descriptor() const {
    if (primitive) return std::string(1, primitive);
    if (component) return name;
    return "L" + name + ";";
}

std::string Class::java_name() const {
    if (primitive) return name;
    // Array names keep their descriptor form with dots: "[Ljava.lang.String;".
    std::string n = name;
    std::replace(n.begin(), n.end(), '/', '.');
    return n;
}

// ---------------------------------------------------------------------------------------------------------------------
// Finding and defining classes.

namespace {

// The class of `name` if the registry has it.
Class* lookup(const std::string& name) {
    std::shared_lock<std::shared_mutex> l(reg().lock);
    auto it = reg().classes.find(name);
    return it == reg().classes.end() ? nullptr : it->second;
}

// Makes a class that extends super unless one of that name exists; under the registry's lock.
Class* make_locked(const std::string& name, Class* super, bool made_up, bool* fresh) {
    auto it = reg().classes.find(name);
    if (it != reg().classes.end()) {
        if (fresh) *fresh = false;
        return it->second;
    }
    Class* c = reg().make(name, super);
    c->made_up = made_up;
    if (fresh) *fresh = true;
    return c;
}

}  // namespace

Class& define(std::string_view name, std::string_view super) {
    ready();
    // The superclass first (made up if nothing defined it): its own superclass is then java/lang/Object.
    Class* parent = super.empty() ? nullptr : &define(super, super == "java/lang/Object" ? "" : "java/lang/Object");
    std::string n(name);
    std::unique_lock<std::shared_mutex> l(reg().lock);
    bool fresh = false;
    Class* c = make_locked(n, parent, false, &fresh);
    // A class defined now that was made up before, or defined again with its real superclass: take what this says.
    // java/lang/Object keeps no superclass.
    if (!fresh && parent && c != reg().core.object && (c->made_up || c->super == reg().core.object)) c->super = parent;
    c->made_up = false;
    return *c;
}

Class& define_interface(std::string_view name) {
    Class& c = define(name);
    // Interfaces have no superclass in Java (getSuperclass gives null); Object's methods are found through
    // find_method's own rule for interfaces.
    c.super = nullptr;
    c.modifiers = kPublic | kInterface | kAbstract;
    return c;
}

Class* find_class(std::string_view name) {
    ready();
    std::string n(name);
    // Code sometimes asks with dots (Class.forName passes them on): the registry keys by slashes.
    std::replace(n.begin(), n.end(), '.', '/');
    if (n.empty()) return nullptr;
    if (Class* c = lookup(n)) return c;
    {
        std::shared_lock<std::shared_mutex> l(reg().lock);
        if (reg().absent.count(n)) return nullptr;
    }
    // An array class: by its element class.
    if (n[0] == '[') {
        Class* element = class_of_descriptor(std::string_view(n).substr(1));
        return element ? &array_class(*element) : nullptr;
    }
    // A class nothing defined, as the phone's VM would have found it in the app.
    std::unique_lock<std::shared_mutex> l(reg().lock);
    bool fresh = false;
    Class* c = make_locked(n, reg().core.object, true, &fresh);
    if (fresh && trace_on()) log("jvm: made up class %s", n.c_str());
    return c;
}

void mark_absent(std::string_view name) {
    ready();
    std::unique_lock<std::shared_mutex> l(reg().lock);
    reg().absent.emplace(name);
}

Class& array_class(Class& component) {
    std::string name = "[" + component.descriptor();
    if (Class* c = lookup(name)) return *c;
    std::unique_lock<std::shared_mutex> l(reg().lock);
    bool fresh = false;
    Class* c = make_locked(name, reg().core.object, false, &fresh);
    if (fresh) {
        c->component = &component;
        c->modifiers = kPublic | kFinal | kAbstract;
    }
    return *c;
}

Class& primitive_class(char type) { return *core().primitives.at(type); }

Class* class_of_descriptor(std::string_view d) {
    if (d.empty()) return nullptr;
    if (d[0] == 'L') {
        // "Ljava/lang/String;" names java/lang/String.
        if (d.back() != ';' || d.size() < 3) return nullptr;
        return find_class(d.substr(1, d.size() - 2));
    }
    if (d[0] == '[') {
        Class* element = class_of_descriptor(d.substr(1));
        return element ? &array_class(*element) : nullptr;
    }
    auto it = core().primitives.find(d[0]);
    return d.size() == 1 && it != core().primitives.end() ? it->second : nullptr;
}

// ---------------------------------------------------------------------------------------------------------------------
// Strings: UTF-16 inside, UTF-8 for C++ code, modified UTF-8 for JNI.

namespace {

// Appends one code point as UTF-16.
void put16(std::u16string& out, std::uint32_t cp) {
    if (cp >= 0x10000) {
        cp -= 0x10000;
        out.push_back(static_cast<char16_t>(0xd800 + (cp >> 10)));
        out.push_back(static_cast<char16_t>(0xdc00 + (cp & 0x3ff)));
    } else {
        out.push_back(static_cast<char16_t>(cp));
    }
}

}  // namespace

// UTF-8 or modified UTF-8 to UTF-16: the two differ only in how they write U+0000 (one byte or two) and characters past
// U+FFFF (four bytes or two three-byte surrogates), and this reads both forms of each. A broken sequence reads as U+FFFD.
std::u16string utf16_of(std::string_view s) {
    std::u16string out;
    out.reserve(s.size());
    for (std::size_t i = 0; i < s.size();) {
        auto b0 = static_cast<unsigned char>(s[i]);
        // How many continuation bytes follow, and the bits the lead byte carries.
        int extra;
        std::uint32_t cp;
        if (b0 < 0x80) {
            extra = 0;
            cp = b0;
        } else if ((b0 & 0xe0) == 0xc0) {
            extra = 1;
            cp = b0 & 0x1f;
        } else if ((b0 & 0xf0) == 0xe0) {
            extra = 2;
            cp = b0 & 0x0f;
        } else if ((b0 & 0xf8) == 0xf0) {
            extra = 3;
            cp = b0 & 0x07;
        } else {
            out.push_back(u'\ufffd');
            ++i;
            continue;
        }
        if (extra && i + extra >= s.size()) {
            // Cut off at the end.
            out.push_back(u'\ufffd');
            break;
        }
        bool ok = true;
        for (int k = 1; k <= extra; ++k) {
            auto b = static_cast<unsigned char>(s[i + k]);
            if ((b & 0xc0) != 0x80) {
                ok = false;
                break;
            }
            cp = (cp << 6) | (b & 0x3f);
        }
        if (!ok) {
            out.push_back(u'\ufffd');
            ++i;
            continue;
        }
        // A three-byte surrogate (modified UTF-8's way past U+FFFF) is one UTF-16 unit as it stands.
        put16(out, cp);
        i += extra + 1;
    }
    return out;
}

std::string String::utf8() const {
    std::string out;
    out.reserve(chars.size());
    for (std::size_t i = 0; i < chars.size(); ++i) {
        std::uint32_t cp = chars[i];
        // A surrogate pair is one code point; a lone surrogate has no UTF-8 form and becomes U+FFFD.
        if (cp >= 0xd800 && cp < 0xdc00 && i + 1 < chars.size() && chars[i + 1] >= 0xdc00 && chars[i + 1] < 0xe000) {
            cp = 0x10000 + ((cp - 0xd800) << 10) + (chars[i + 1] - 0xdc00);
            ++i;
        } else if (cp >= 0xd800 && cp < 0xe000) {
            cp = 0xfffd;
        }
        if (cp < 0x80) {
            out.push_back(static_cast<char>(cp));
        } else if (cp < 0x800) {
            out.push_back(static_cast<char>(0xc0 | (cp >> 6)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3f)));
        } else if (cp < 0x10000) {
            out.push_back(static_cast<char>(0xe0 | (cp >> 12)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3f)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3f)));
        } else {
            out.push_back(static_cast<char>(0xf0 | (cp >> 18)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3f)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3f)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3f)));
        }
    }
    return out;
}

std::string String::mutf8() const { return mutf8_of(chars.data(), chars.size()); }

std::string mutf8_of(const char16_t* chars, std::size_t n) {
    std::string out;
    out.reserve(n);
    for (std::size_t i = 0; i < n; ++i) {
        std::uint32_t c = chars[i];
        // U+0000 takes two bytes, so that the text never holds a zero byte; every UTF-16 unit, surrogates included,
        // is written on its own.
        if (c != 0 && c < 0x80) {
            out.push_back(static_cast<char>(c));
        } else if (c < 0x800) {
            out.push_back(static_cast<char>(0xc0 | (c >> 6)));
            out.push_back(static_cast<char>(0x80 | (c & 0x3f)));
        } else {
            out.push_back(static_cast<char>(0xe0 | (c >> 12)));
            out.push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3f)));
            out.push_back(static_cast<char>(0x80 | (c & 0x3f)));
        }
    }
    return out;
}

Ref<String> string(std::string_view utf8) { return string16(utf16_of(utf8)); }

Ref<String> string16(std::u16string chars) { return Ref<String>(new String(core().string, std::move(chars))); }

std::string Call::str(std::size_t k) const {
    auto* s = dynamic_cast<String*>(args[k].l());
    return s ? s->utf8() : std::string();
}

// ---------------------------------------------------------------------------------------------------------------------
// Arrays.

namespace {
// Bytes per element of each primitive type.
std::size_t size_of(char type) {
    switch (type) {
    case 'Z':
    case 'B': return 1;
    case 'C':
    case 'S': return 2;
    case 'I':
    case 'F': return 4;
    case 'J':
    case 'D': return 8;
    default: return 0;
    }
}
}  // namespace

Array::Array(Class* cls, jsize length)
    : Object(cls), length(length < 0 ? 0 : length), type(cls->component->primitive ? cls->component->primitive : cls->component->descriptor()[0]) {
    if (of_objects()) items.resize(static_cast<std::size_t>(this->length));
    else bytes.resize(static_cast<std::size_t>(this->length) * element_size());
}

std::size_t Array::element_size() const { return size_of(type); }

Ref<Array> new_array(Class& array_cls, jsize length) { return Ref<Array>(new Array(&array_cls, length)); }

// ---------------------------------------------------------------------------------------------------------------------
// Other objects the VM makes.

Ref<Object> box(char type, const Value& v) {
    auto it = core().boxes.find(type);
    if (it == core().boxes.end()) return {};
    return Ref<Object>(new Boxed(it->second, type, v));
}

Ref<Buffer> direct_buffer(void* address, jlong capacity) { return Ref<Buffer>(new Buffer(core().direct_buffer, address, capacity)); }

Ref<Buffer> new_buffer(std::size_t size) {
    Ref<Buffer> b(new Buffer(core().direct_buffer, nullptr, static_cast<jlong>(size)));
    b->own.resize(size);
    b->address = b->own.data();
    return b;
}

Object* instantiate(Class& cls) {
    // A class of the C++ library with state of its own makes its own kind of object; one with none, an Object.
    if (cls.make) return cls.make(cls);
    // Exceptions and other library classes find their maker up the chain (an IOException is made as a Throwable).
    for (Class* c = cls.super; c; c = c->super) {
        if (c->make) return c->make(cls);
    }
    return new Object(&cls);
}

Ref<Object> new_object(Class& cls, std::string_view ctor_sig, std::initializer_list<Value> args) {
    Ref<Object> o(instantiate(cls));
    Method& ctor = cls.method_or_made_up("<init>", ctor_sig, false);
    Env& e = attach();
    e.invoke(ctor, o.get(), args.begin(), args.size());
    return o;
}

Ref<Object> exception(std::string_view cls, std::string_view message) {
    Class* c = find_class(cls);
    // An exception class nothing defined (or one made up as a plain class): an unchecked exception of that name.
    if (!c || !c->is(core().throwable)) c = &define(cls, "java/lang/RuntimeException");
    // Made and given its message directly, without a constructor: classes made up have none of their own.
    Ref<Object> o(instantiate(*c));
    if (Field* f = core().throwable->find_field("detailMessage", false)) o->set_field(f, Value(string(message)));
    return o;
}

void throw_new(std::string_view cls, std::string_view message) { throw Throw{exception(cls, message)}; }

// ---------------------------------------------------------------------------------------------------------------------
// Threads and references.

namespace {

// The calling thread's Env. A thread that ends while attached is detached by its destructor.
thread_local std::unique_ptr<Env> t_env;

// A reference is the address of its slot with its kind in the low bits (slots are pointers, 8-aligned).
constexpr std::uintptr_t kKindMask = 7, kLocal = 1, kGlobal = 2, kWeak = 3;

jobject tag(Object** slot, std::uintptr_t kind) { return reinterpret_cast<jobject>(reinterpret_cast<std::uintptr_t>(slot) | kind); }
Object** slot_of(jobject r) { return reinterpret_cast<Object**>(reinterpret_cast<std::uintptr_t>(r) & ~kKindMask); }

}  // namespace

Env::Env() { jni.functions = &kNativeInterface; }

Env::~Env() {
    // Every local reference of the thread goes with it.
    frames_.clear();
    for (Object* o : locals_) {
        if (o) o->release();
    }
}

Env* Env::current() { return t_env.get(); }

JavaVM* java_vm() {
    ready();
    return &reg().vm;
}

Env& attach() {
    ready();
    if (!t_env) t_env = std::make_unique<Env>();
    return *t_env;
}

void detach() { t_env.reset(); }

jobject Env::local(Object* o) {
    if (!o) return nullptr;
    o->retain();
    locals_.push_back(o);
    return tag(&locals_.back(), kLocal);
}

Object* Env::deref(jobject r) {
    if (!r) return nullptr;
    auto kind = reinterpret_cast<std::uintptr_t>(r) & kKindMask;
    if (kind != kLocal && kind != kGlobal && kind != kWeak) {
        log("jvm: %p is not a reference", static_cast<void*>(r));
        return nullptr;
    }
    return *slot_of(r);
}

jobjectRefType ref_type(jobject r) {
    switch (reinterpret_cast<std::uintptr_t>(r) & kKindMask) {
    case kLocal: return JNILocalRefType;
    case kGlobal: return JNIGlobalRefType;
    case kWeak: return JNIWeakGlobalRefType;
    default: return JNIInvalidRefType;
    }
}

void Env::push_frame() { frames_.push_back(locals_.size()); }

void Env::pop_frame() {
    if (frames_.empty()) return;
    std::size_t mark = frames_.back();
    frames_.pop_back();
    while (locals_.size() > mark) {
        Object* o = locals_.back();
        locals_.pop_back();
        if (o) o->release();
        else --nulls_;
    }
}

void Env::delete_local(jobject r) {
    if (!r || (reinterpret_cast<std::uintptr_t>(r) & kKindMask) != kLocal) return;
    Object** slot = slot_of(r);
    Object* o = *slot;
    if (!o) return;
    *slot = nullptr;
    ++nulls_;
    o->release();
    // Deleting the newest references (the usual order) gives their slots back, down to the open frame's start.
    std::size_t floor = frames_.empty() ? 0 : frames_.back();
    while (locals_.size() > floor && !locals_.back()) {
        locals_.pop_back();
        --nulls_;
    }
}

Value static_value(const Field* f) {
    std::lock_guard<std::mutex> l(fields_lock());
    return f->value;
}

void set_static_value(Field* f, const Value& v) {
    // The old value goes after the lock, as in Object::set_field.
    Value old;
    std::lock_guard<std::mutex> l(fields_lock());
    old = f->value;
    f->value = v;
}

std::string message_of(Object* throwable) {
    if (!throwable) return {};
    Field* f = core().throwable->find_field("detailMessage", false);
    auto* s = f ? dynamic_cast<String*>(throwable->field(f).l()) : nullptr;
    return s ? s->utf8() : std::string();
}

jobject new_global(Object* o, bool weak) {
    if (!o) return nullptr;
    o->retain();
    Registry& r = reg();
    std::lock_guard<std::mutex> l(r.globals_lock);
    Object** slot;
    if (!r.free_globals.empty()) {
        slot = r.free_globals.back();
        r.free_globals.pop_back();
    } else {
        r.globals.push_back(nullptr);
        slot = &r.globals.back();
    }
    *slot = o;
    // A weak reference holds its object like a global one: an object goes when nothing references it, and while a
    // weak reference exists something does, so Java code cannot tell (it never knows when a collection runs).
    return tag(slot, weak ? kWeak : kGlobal);
}

void delete_global(jobject g) {
    auto kind = reinterpret_cast<std::uintptr_t>(g) & kKindMask;
    if (!g || (kind != kGlobal && kind != kWeak)) return;
    Object** slot = slot_of(g);
    Object* o;
    {
        std::lock_guard<std::mutex> l(reg().globals_lock);
        o = *slot;
        if (!o) return;
        *slot = nullptr;
        reg().free_globals.push_back(slot);
    }
    // Released outside the lock: freeing the object may release others, whose globals... are not touched, but the
    // destructors of C++ classes may make JNI calls of their own.
    o->release();
}

std::size_t global_count() {
    std::lock_guard<std::mutex> l(reg().globals_lock);
    return reg().globals.size() - reg().free_globals.size();
}

// ---------------------------------------------------------------------------------------------------------------------
// Calls.

namespace {

// Methods that were called without a body, logged once each.
void note_unimplemented(Method& m) {
    if (m.calls.load(std::memory_order_relaxed) == 1 || trace_on()) {
        const char* why = m.modifiers & kNative ? "native, never registered" : "no body";
        log("jvm: %s.%s%s called (%s)", m.owner->name.c_str(), m.name.c_str(), m.sig.c_str(), why);
    }
}

}  // namespace

Value Env::call(Method& m, Object* self, const Value* args, std::size_t n) {
    if (m.is_static() || m.name == "<init>") return invoke(m, self, args, n);
    if (!self) {
        pending = exception("java/lang/NullPointerException", "call of " + m.name + " on null");
        return {};
    }
    // A proxy takes every call of its interfaces (Object's own methods included, as Java's proxies do).
    if (self->cls()->proxy) {
        auto* p = dynamic_cast<Proxy*>(self);
        // Not counted: the method is the interface's, and the handler is its body for this object.
        if (p && p->invoke) {
            Call c{*this, m, self, args, n};
            try {
                return p->invoke(c);
            } catch (Throw& t) {
                pending = t.exception;
                return {};
            } catch (std::exception& x) {
                pending = exception("java/lang/RuntimeException", std::string("proxy ") + m.name + ": " + x.what());
                return {};
            }
        }
    }
    return invoke(*self->cls()->resolve(&m), self, args, n);
}

Value Env::call(Object* self, std::string_view name, std::string_view sig, std::initializer_list<Value> args) {
    if (!self) {
        pending = exception("java/lang/NullPointerException", "call of " + std::string(name) + " on null");
        return {};
    }
    return call(self->cls()->method_or_made_up(name, sig, false), self, args.begin(), args.size());
}

Value Env::call_static(Class& cls, std::string_view name, std::string_view sig, std::initializer_list<Value> args) {
    return invoke(cls.method_or_made_up(name, sig, true), nullptr, args.begin(), args.size());
}

Value Env::invoke(Method& m, Object* self, const Value* args, std::size_t n) {
    m.calls.fetch_add(1, std::memory_order_relaxed);
    // A registered native first: the game's code is what the Java method was.
    if (void* fn = m.native.load(std::memory_order_acquire)) return call_native(*this, m, fn, m.is_static() ? m.owner : self, args, n);
    if (m.fn) {
        // Fewer arguments than the signature has (C++ code calling loosely) read as zeros.
        std::vector<Value> padded;
        if (n < m.params.size()) {
            padded.assign(args, args + n);
            padded.resize(m.params.size());
            args = padded.data();
            n = padded.size();
        }
        Call c{*this, m, self, args, n};
        try {
            return m.fn(c);
        } catch (Throw& t) {
            pending = t.exception;
            return {};
        } catch (std::exception& x) {
            // A C++ failure in a body must not unwind into the game's native code: it becomes a Java exception there.
            pending = exception("java/lang/RuntimeException", std::string(m.owner->name) + "." + m.name + ": " + x.what());
            return {};
        }
    }
    // A constructor nothing defined for this class runs its superclass's of the same signature, as an implicit
    // super(...) would: the library defines Throwable(String) once, and every exception class has it.
    if (m.name == "<init>") {
        for (Class* c = m.owner->super; c; c = c->super) {
            Method* base = c->find_method("<init>", m.sig);
            if (base && (base->fn || base->native.load(std::memory_order_relaxed))) return invoke(*base, self, args, n);
        }
        // No constructor anywhere up the chain: the object stays as it was made, which is what an empty one does.
        return {};
    }
    note_unimplemented(m);
    return inert_result(m);
}

Value inert_result(Method& m) {
    // A method nothing implements returns what lets its caller go on, as the real one would have: an object of the
    // class it returns (empty, its own methods made up in turn), an empty array, zero. SDK code calls on what it gets
    // without testing for null, since the real methods never return null there. A String stays null: no text is the
    // honest answer for one nobody knows.
    if (m.ret == '[') {
        Class* c = class_of_descriptor(m.ret_type);
        return c ? Value(new_array(*c, 0)) : Value();
    }
    if (m.ret != 'L' || m.ret_type == "Ljava/lang/String;") return {};
    Class* c = class_of_descriptor(m.ret_type);
    if (!c || c->primitive) return {};
    // getInstance is a singleton's: the same object every time.
    if (m.is_static() && m.name == "getInstance") {
        std::lock_guard<std::mutex> l(fields_lock());
        if (!m.instance) m.instance = Ref<Object>(instantiate(*c));
        return Value(m.instance);
    }
    return Value(Ref<Object>(instantiate(*c)));
}

Value call_native(Env& e, Method& m, void* fn, Object* self, const Value* args, std::size_t n) {
    // The call is a native method call as the platform's VM makes it: a local frame for the references it is handed
    // and the ones it makes, freed when it returns.
    e.push_frame();
    NativeArgs a;
    // JNIEnv, then the object (or the class for a static method).
    a.integer(reinterpret_cast<std::uintptr_t>(&e.jni));
    a.integer(reinterpret_cast<std::uintptr_t>(e.local(self)));
    for (std::size_t k = 0; k < m.params.size(); ++k) {
        // Arguments C++ code left out are zeros.
        static const Value zero;
        const Value& v = k < n ? args[k] : zero;
        switch (m.params[k]) {
        case 'Z': a.integer(v.z()); break;
        // Signed narrow types are passed sign-extended, as compilers do.
        case 'B': a.integer(static_cast<std::uint64_t>(static_cast<std::int64_t>(v.b()))); break;
        case 'C': a.integer(v.c()); break;
        case 'S': a.integer(static_cast<std::uint64_t>(static_cast<std::int64_t>(v.s()))); break;
        case 'I': a.integer(static_cast<std::uint64_t>(static_cast<std::int64_t>(v.i()))); break;
        case 'J': a.integer(static_cast<std::uint64_t>(v.j())); break;
        case 'F': {
            // A float travels in the low half of a vector register (or stack slot).
            std::uint32_t bits;
            float f = v.f();
            std::memcpy(&bits, &f, 4);
            a.floating(bits);
            break;
        }
        case 'D': {
            std::uint64_t bits;
            double d = v.d();
            std::memcpy(&bits, &d, 8);
            a.floating(bits);
            break;
        }
        default: a.integer(reinterpret_cast<std::uintptr_t>(e.local(v.l()))); break;
        }
    }
    std::uint64_t fp_result = 0;
    std::uint64_t r = jvm_call_native(fn, a.gpr, a.fpr, a.stack.data(), a.stack.size(), &fp_result);
    Value out;
    switch (m.ret) {
    case 'V': break;
    // A bool comes back in the low byte, narrow types in their low bits: the rest of the register is undefined.
    case 'Z': out = Value::Z(r & 0xff); break;
    case 'B': out = Value::B(static_cast<jbyte>(r)); break;
    case 'C': out = Value::C(static_cast<jchar>(r)); break;
    case 'S': out = Value::S(static_cast<jshort>(r)); break;
    case 'I': out = Value::I(static_cast<jint>(r)); break;
    case 'J': out = Value::J(static_cast<jlong>(r)); break;
    case 'F': {
        float f;
        auto bits = static_cast<std::uint32_t>(fp_result);
        std::memcpy(&f, &bits, 4);
        out = Value::F(f);
        break;
    }
    case 'D': {
        double d;
        std::memcpy(&d, &fp_result, 8);
        out = Value::D(d);
        break;
    }
    // The returned reference is one of the frame's: the value holds the object before the frame goes.
    default: out = Value(Env::deref(reinterpret_cast<jobject>(r))); break;
    }
    e.pop_frame();
    return out;
}

#ifdef _WIN32
// Windows x64: an argument's position picks its register, whatever its kind; both counts move together.
void NativeArgs::integer(std::uint64_t v) {
    if (n_gpr < kIntRegs) gpr[n_gpr] = v;
    else stack.push_back(v);
    n_fpr = ++n_gpr;
}

void NativeArgs::floating(std::uint64_t bits) {
    if (n_fpr < kFloatRegs) fpr[n_fpr] = bits;
    else stack.push_back(bits);
    n_gpr = ++n_fpr;
}
#else
void NativeArgs::integer(std::uint64_t v) {
    if (n_gpr < kIntRegs) gpr[n_gpr++] = v;
    else stack.push_back(v);
}

void NativeArgs::floating(std::uint64_t bits) {
    if (n_fpr < kFloatRegs) fpr[n_fpr++] = bits;
    else stack.push_back(bits);
}
#endif

// ---------------------------------------------------------------------------------------------------------------------
// The report.

void report_unimplemented() {
    std::vector<Method*> called;
    {
        std::shared_lock<std::shared_mutex> l(reg().lock);
        for (auto& [name, c] : reg().classes) {
            for (Method* m : c->all_methods()) {
                // A constructor nothing defines does what an empty one does, and a proxy's calls go to its handler: neither
                // is worth a line.
                bool bodyless = !m->fn && !m->native.load(std::memory_order_relaxed) && m->name != "<init>" && !c->proxy;
                if (bodyless && m->calls.load(std::memory_order_relaxed)) called.push_back(m);
            }
        }
    }
    std::sort(called.begin(), called.end(), [](Method* a, Method* b) { return a->calls > b->calls; });
    log("jvm: %zu methods were called without a body", called.size());
    for (Method* m : called) log("jvm:   %8llu  %s.%s%s", static_cast<unsigned long long>(m->calls.load()), m->owner->name.c_str(), m->name.c_str(), m->sig.c_str());
}

std::vector<Class*> all_classes() {
    ready();
    std::vector<Class*> out;
    std::shared_lock<std::shared_mutex> l(reg().lock);
    for (auto& [name, c] : reg().classes) out.push_back(c);
    // By name, for reports that read the same from run to run.
    std::sort(out.begin(), out.end(), [](Class* a, Class* b) { return a->name < b->name; });
    return out;
}

bool trace_on() {
    // ARM32_TRACE turns the runtime's tracing on; the VM's follows it.
    static const bool on = [] {
        const char* e = std::getenv("ARM32_TRACE");
        return e && std::strcmp(e, "0") != 0;
    }();
    return on;
}

}  // namespace jvm
