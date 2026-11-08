// java.util, java.io and android.net.Uri beyond what the VM itself has: the HashMap native code fills (request
// headers) and reads back (SharedPreferences.getAll) with its sets and iterators, FileOutputStream for files the game's
// libraries write, Uri's encode and decode as Android's work, and the Locale of the computer.
#include "player.h"

#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#endif

namespace player {

namespace {

using jvm::Call;
using jvm::Class;
using jvm::Object;
using jvm::Ref;
using jvm::Value;

// Java's equals for keys: strings and boxes by value, everything else by identity.
bool same_key(Object* a, Object* b) {
    if (a == b) return true;
    if (!a || !b) return false;
    auto* sa = dynamic_cast<jvm::String*>(a);
    auto* sb = dynamic_cast<jvm::String*>(b);
    if (sa && sb) return sa->chars == sb->chars;
    auto* ba = dynamic_cast<jvm::Boxed*>(a);
    auto* bb = dynamic_cast<jvm::Boxed*>(b);
    return ba && bb && ba->type == bb->type && ba->value.raw().j == bb->value.raw().j;
}

// java.util.HashMap: entries in the order they were put (iteration order is unspecified in Java; insertion order is a
// valid one and keeps logs stable).
class Map : public Object {
public:
    using Object::Object;
    std::mutex lock;
    std::vector<std::pair<Ref<Object>, Ref<Object>>> entries;
    std::size_t find(Object* key) {
        for (std::size_t i = 0; i < entries.size(); ++i) {
            if (same_key(entries[i].first.get(), key)) return i;
        }
        return entries.size();
    }
};

// A snapshot of a map's keys, values or entries (keySet, values, entrySet): read-only views are all the game uses.
class Items : public Object {
public:
    using Object::Object;
    std::vector<Ref<Object>> items;
};

class Iter : public Object {
public:
    using Object::Object;
    Ref<Items> of;
    std::size_t next = 0;
};

class Entry : public Object {
public:
    using Object::Object;
    Ref<Object> key, value;
};

Class *g_items = nullptr, *g_iter = nullptr, *g_entry = nullptr;

Ref<Items> items_of(std::vector<Ref<Object>> v) {
    Ref<Items> s(new Items(g_items));
    s->items = std::move(v);
    return s;
}

void define_collections() {
    jvm::define_interface("java/util/Map");
    jvm::define_interface("java/util/Map$Entry");
    jvm::define_interface("java/util/Collection");
    jvm::define_interface("java/util/Set");
    jvm::define_interface("java/util/Iterator");
    Class& m = jvm::define("java/util/HashMap", "java/util/AbstractMap");
    m.interfaces.push_back(jvm::find_class("java/util/Map"));
    m.make = [](Class& k) -> Object* { return new Map(&k); };
    jvm::define("java/util/LinkedHashMap", "java/util/HashMap");
    jvm::define("java/util/TreeMap", "java/util/HashMap");
    auto map = [](Call& c) -> Map& { return c.self_as<Map>(); };
    m.method("<init>", "()V", [](Call&) { return Value(); });
    m.method("<init>", "(I)V", [](Call&) { return Value(); });
    m.method("<init>", "(IF)V", [](Call&) { return Value(); });
    m.method("put", "(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;", [map](Call& c) {
        Map& mp = map(c);
        std::lock_guard<std::mutex> l(mp.lock);
        std::size_t i = mp.find(c.l(0));
        if (i < mp.entries.size()) {
            Ref<Object> old = mp.entries[i].second;
            mp.entries[i].second = Ref<Object>(c.l(1));
            return Value(old);
        }
        mp.entries.emplace_back(Ref<Object>(c.l(0)), Ref<Object>(c.l(1)));
        return Value();
    });
    m.method("get", "(Ljava/lang/Object;)Ljava/lang/Object;", [map](Call& c) {
        Map& mp = map(c);
        std::lock_guard<std::mutex> l(mp.lock);
        std::size_t i = mp.find(c.l(0));
        return i < mp.entries.size() ? Value(mp.entries[i].second) : Value();
    });
    m.method("containsKey", "(Ljava/lang/Object;)Z", [map](Call& c) {
        Map& mp = map(c);
        std::lock_guard<std::mutex> l(mp.lock);
        return Value::Z(mp.find(c.l(0)) < mp.entries.size());
    });
    m.method("remove", "(Ljava/lang/Object;)Ljava/lang/Object;", [map](Call& c) {
        Map& mp = map(c);
        std::lock_guard<std::mutex> l(mp.lock);
        std::size_t i = mp.find(c.l(0));
        if (i >= mp.entries.size()) return Value();
        Ref<Object> old = mp.entries[i].second;
        mp.entries.erase(mp.entries.begin() + static_cast<std::ptrdiff_t>(i));
        return Value(old);
    });
    m.method("size", "()I", [map](Call& c) {
        Map& mp = map(c);
        std::lock_guard<std::mutex> l(mp.lock);
        return Value::I(static_cast<jint>(mp.entries.size()));
    });
    m.method("isEmpty", "()Z", [map](Call& c) {
        Map& mp = map(c);
        std::lock_guard<std::mutex> l(mp.lock);
        return Value::Z(mp.entries.empty());
    });
    m.method("clear", "()V", [map](Call& c) {
        Map& mp = map(c);
        std::lock_guard<std::mutex> l(mp.lock);
        mp.entries.clear();
        return Value();
    });
    m.method("keySet", "()Ljava/util/Set;", [map](Call& c) {
        Map& mp = map(c);
        std::lock_guard<std::mutex> l(mp.lock);
        std::vector<Ref<Object>> keys;
        for (auto& e : mp.entries) keys.push_back(e.first);
        return Value(items_of(std::move(keys)));
    });
    m.method("values", "()Ljava/util/Collection;", [map](Call& c) {
        Map& mp = map(c);
        std::lock_guard<std::mutex> l(mp.lock);
        std::vector<Ref<Object>> values;
        for (auto& e : mp.entries) values.push_back(e.second);
        return Value(items_of(std::move(values)));
    });
    m.method("entrySet", "()Ljava/util/Set;", [map](Call& c) {
        Map& mp = map(c);
        std::lock_guard<std::mutex> l(mp.lock);
        std::vector<Ref<Object>> entries;
        for (auto& e : mp.entries) {
            Ref<Entry> en(new Entry(g_entry));
            en->key = e.first;
            en->value = e.second;
            entries.push_back(en);
        }
        return Value(items_of(std::move(entries)));
    });
    Class& s = jvm::define("java/util/HashSet");
    s.interfaces.push_back(jvm::find_class("java/util/Set"));
    g_items = &s;
    s.make = [](Class& k) -> Object* { return new Items(&k); };
    s.method("size", "()I", [](Call& c) { return Value::I(static_cast<jint>(c.self_as<Items>().items.size())); });
    s.method("isEmpty", "()Z", [](Call& c) { return Value::Z(c.self_as<Items>().items.empty()); });
    s.method("iterator", "()Ljava/util/Iterator;", [](Call& c) {
        Ref<Iter> it(new Iter(g_iter));
        it->of = Ref<Items>(&c.self_as<Items>());
        return Value(it);
    });
    s.method("toArray", "()[Ljava/lang/Object;", [](Call& c) {
        const auto& items = c.self_as<Items>().items;
        Ref<jvm::Array> a = jvm::new_array(jvm::array_class(*jvm::find_class("java/lang/Object")), static_cast<jsize>(items.size()));
        for (std::size_t k = 0; k < items.size(); ++k) a->items[k] = items[k];
        return Value(a);
    });
    Class& it = jvm::define("java/util/HashMap$HashIterator");
    it.interfaces.push_back(jvm::find_class("java/util/Iterator"));
    g_iter = &it;
    it.method("hasNext", "()Z", [](Call& c) {
        Iter& i = c.self_as<Iter>();
        return Value::Z(i.next < i.of->items.size());
    });
    it.method("next", "()Ljava/lang/Object;", [](Call& c) {
        Iter& i = c.self_as<Iter>();
        if (i.next >= i.of->items.size()) jvm::throw_new("java/util/NoSuchElementException", "no more elements");
        return Value(i.of->items[i.next++]);
    });
    Class& e = jvm::define("java/util/HashMap$Node");
    e.interfaces.push_back(jvm::find_class("java/util/Map$Entry"));
    g_entry = &e;
    e.method("getKey", "()Ljava/lang/Object;", [](Call& c) { return Value(c.self_as<Entry>().key); });
    e.method("getValue", "()Ljava/lang/Object;", [](Call& c) { return Value(c.self_as<Entry>().value); });
    jvm::define("java/util/NoSuchElementException", "java/lang/RuntimeException");
}

// ---------------------------------------------------------------------------------------------------------------------
// FileOutputStream: a file the game's libraries write (a library unpacks a part of itself into the cache folder).

class OutStream : public Object {
public:
    using Object::Object;
    int fd = -1;
    ~OutStream() override {
        if (fd >= 0) close(fd);
    }
};

void define_streams() {
    Class& c = jvm::define("java/io/FileOutputStream", "java/io/OutputStream");
    c.make = [](Class& k) -> Object* { return new OutStream(&k); };
    // The path of a File argument, through File.getPath (java.io.File is the app's, android_app.cpp).
    auto path_of = [](Call& c, std::size_t k) {
        if (auto* s = dynamic_cast<jvm::String*>(c.l(k))) return s->utf8();
        // The result kept in a Value while it is read: the String it holds goes with the last reference to it.
        jvm::Value path = c.env.call(c.l(k), "getPath", "()Ljava/lang/String;");
        auto* p = dynamic_cast<jvm::String*>(path.l());
        return p ? p->utf8() : std::string();
    };
    auto open_at = [path_of](Call& c, bool append) {
        std::string path = path_of(c, 0);
        int fd = open(host_of(path).c_str(), O_WRONLY | O_CREAT | O_CLOEXEC | (append ? O_APPEND : O_TRUNC), 0644);
        if (fd < 0) jvm::throw_new("java/io/FileNotFoundException", path);
        c.self_as<OutStream>().fd = fd;
        return Value();
    };
    c.method("<init>", "(Ljava/io/File;)V", [open_at](Call& c) { return open_at(c, false); });
    c.method("<init>", "(Ljava/lang/String;)V", [open_at](Call& c) { return open_at(c, false); });
    c.method("<init>", "(Ljava/io/File;Z)V", [open_at](Call& c) { return open_at(c, c.z(1)); });
    c.method("<init>", "(Ljava/lang/String;Z)V", [open_at](Call& c) { return open_at(c, c.z(1)); });
    auto write_all = [](OutStream& s, const std::uint8_t* p, std::size_t n) {
        while (n) {
            ssize_t w = ::write(s.fd, p, n);
            if (w < 0 && errno == EINTR) continue;
            if (w <= 0) jvm::throw_new("java/io/IOException", "write failed");
            p += w;
            n -= static_cast<std::size_t>(w);
        }
    };
    c.method("write", "(I)V", [write_all](Call& c) {
        auto b = static_cast<std::uint8_t>(c.i(0));
        write_all(c.self_as<OutStream>(), &b, 1);
        return Value();
    });
    c.method("write", "([B)V", [write_all](Call& c) {
        auto* a = c.as<jvm::Array>(0);
        if (a) write_all(c.self_as<OutStream>(), a->bytes.data(), a->bytes.size());
        return Value();
    });
    c.method("write", "([BII)V", [write_all](Call& c) {
        auto* a = c.as<jvm::Array>(0);
        jint off = c.i(1), len = c.i(2);
        if (!a || off < 0 || len < 0 || off > a->length - len) jvm::throw_new("java/lang/IndexOutOfBoundsException", "write range");
        write_all(c.self_as<OutStream>(), a->bytes.data() + off, static_cast<std::size_t>(len));
        return Value();
    });
    c.method("flush", "()V", [](Call&) { return Value(); });
    c.method("close", "()V", [](Call& c) {
        OutStream& s = c.self_as<OutStream>();
        if (s.fd >= 0) close(s.fd);
        s.fd = -1;
        return Value();
    });
}

// ---------------------------------------------------------------------------------------------------------------------
// android.net.Uri's encode and decode, as Android's: letters, digits and _-!.~'()* stay, everything else is UTF-8 in
// %XX (Unity's PlayerPrefs keys go through them).

std::string uri_encode(const std::string& s, const std::string& allow) {
    static const char* kHex = "0123456789ABCDEF";
    std::string out;
    for (unsigned char ch : s) {
        bool keep = std::isalnum(ch) || std::string("_-!.~'()*").find(static_cast<char>(ch)) != std::string::npos || allow.find(static_cast<char>(ch)) != std::string::npos;
        if (keep && ch < 0x80) {
            out.push_back(static_cast<char>(ch));
        } else {
            out.push_back('%');
            out.push_back(kHex[ch >> 4]);
            out.push_back(kHex[ch & 15]);
        }
    }
    return out;
}

std::string uri_decode(const std::string& s) {
    std::string out;
    for (std::size_t i = 0; i < s.size(); ++i) {
        if (s[i] == '%' && i + 2 < s.size() && std::isxdigit(static_cast<unsigned char>(s[i + 1])) && std::isxdigit(static_cast<unsigned char>(s[i + 2]))) {
            out.push_back(static_cast<char>(std::strtol(s.substr(i + 1, 2).c_str(), nullptr, 16)));
            i += 2;
        } else {
            out.push_back(s[i]);
        }
    }
    return out;
}

class Uri : public Object {
public:
    using Object::Object;
    std::string text;
};

void define_uri() {
    Class& c = jvm::define("android/net/Uri");
    c.make = [](Class& k) -> Object* { return new Uri(&k); };
    c.static_method("encode", "(Ljava/lang/String;)Ljava/lang/String;", [](Call& c) { return c.l(0) ? Value(jvm::string(uri_encode(c.str(0), ""))) : Value(); });
    c.static_method("encode", "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;", [](Call& c) { return c.l(0) ? Value(jvm::string(uri_encode(c.str(0), c.str(1)))) : Value(); });
    c.static_method("decode", "(Ljava/lang/String;)Ljava/lang/String;", [](Call& c) { return c.l(0) ? Value(jvm::string(uri_decode(c.str(0)))) : Value(); });
    c.static_method("parse", "(Ljava/lang/String;)Landroid/net/Uri;", [&c](Call& call) {
        Ref<Uri> u(new Uri(&c));
        u->text = call.str(0);
        return Value(u);
    });
    c.method("toString", "()Ljava/lang/String;", [](Call& c) { return Value(jvm::string(c.self_as<Uri>().text)); });
}

// java.util.Locale: the computer's (host_locale).
void define_locale() {
    Class& c = jvm::define("java/util/Locale");
    const auto [lang, country] = host_locale();
    jvm::log("player: the game's locale is %s_%s", lang.c_str(), country.c_str());
    c.field("language", "Ljava/lang/String;").field("country", "Ljava/lang/String;");
    Ref<Object> def = jvm::new_object(c, "()V");
    def->set_field(c.find_field("language", false), Value(jvm::string(lang)));
    def->set_field(c.find_field("country", false), Value(jvm::string(country)));
    c.static_method("getDefault", "()Ljava/util/Locale;", [def](Call&) { return Value(def); });
    c.method("getLanguage", "()Ljava/lang/String;", [&c](Call& call) { return call.self->field(c.find_field("language", false)); });
    c.method("getCountry", "()Ljava/lang/String;", [&c](Call& call) { return call.self->field(c.find_field("country", false)); });
    c.method("toString", "()Ljava/lang/String;", [lang, country](Call&) { return Value(jvm::string(lang + "_" + country)); });
}

}  // namespace

std::pair<std::string, std::string> host_locale() {
    // A Linux locale's name, as the environment gives it ("ko_KR.UTF-8"): the first of these that says one.
    for (const char* name : {"LC_ALL", "LC_MESSAGES", "LANG"}) {
        const char* l = std::getenv(name);
        if (!l || !*l) continue;
        if (std::strlen(l) >= 5 && l[2] == '_') return {std::string(l, 2), std::string(l + 3, 2)};
        // "C" or "POSIX" says English; any other value says nothing more.
        break;
    }
#ifdef _WIN32
    // Windows' display language, the first of the user's ("ko-KR", "zh-Hans-CN"): its language is the first part, its
    // country the last. It is what the user reads Windows in, which the regional format (dates, numbers) may differ from.
    wchar_t name[LOCALE_NAME_MAX_LENGTH * 4] = {};
    ULONG count = 0, size = LOCALE_NAME_MAX_LENGTH * 4;
    if (GetUserPreferredUILanguages(MUI_LANGUAGE_NAME, &count, name, &size) && count > 0 && name[0]) {
        std::string tag;
        // The list is NUL-separated: the first name alone.
        for (int i = 0; name[i] && i < LOCALE_NAME_MAX_LENGTH; ++i) tag += static_cast<char>(name[i] < 128 ? name[i] : '?');
        std::size_t first = tag.find('-'), last = tag.rfind('-');
        std::string lang = tag.substr(0, first);
        for (char& ch : lang) ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
        if (first != std::string::npos && tag.size() - last == 3) return {lang, tag.substr(last + 1)};
        // A language without a country ("ko"): the country of the user's regional format, when it has one.
        wchar_t region[LOCALE_NAME_MAX_LENGTH];
        if (int n = GetUserDefaultLocaleName(region, LOCALE_NAME_MAX_LENGTH); n > 3 && region[n - 4] == L'-')
            return {lang, std::string{static_cast<char>(region[n - 3]), static_cast<char>(region[n - 2])}};
        if (!lang.empty()) return {lang, lang == "ko" ? "KR" : "US"};
    }
#endif
    return {"en", "US"};
}

std::vector<std::pair<std::string, std::string>> string_pairs(Object* map) {
    std::vector<std::pair<std::string, std::string>> out;
    auto* m = dynamic_cast<Map*>(map);
    if (!m) return out;
    std::lock_guard<std::mutex> l(m->lock);
    for (auto& [k, v] : m->entries) {
        auto* ks = dynamic_cast<jvm::String*>(k.get());
        auto* vs = dynamic_cast<jvm::String*>(v.get());
        if (ks) out.emplace_back(ks->utf8(), vs ? vs->utf8() : std::string());
    }
    return out;
}

void define_java() {
    define_collections();
    define_streams();
    define_uri();
    define_locale();
}

}  // namespace player
