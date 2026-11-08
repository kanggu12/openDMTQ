// Android's application classes as the game calls them: files, the context and the activity, the package manager,
// intents and bundles, shared preferences (Unity's PlayerPrefs), the Build constants, external storage, and the
// system services. What the phone's framework would answer for this app, from the App the player describes.
#include "player.h"

#include <cstdio>
#include <cstdlib>
#include <dirent.h>
#include <fstream>
#include <map>
#include <mutex>
#include <sstream>
#include <sys/stat.h>
#include <unistd.h>

namespace player {

namespace {

using jvm::Call;
using jvm::Class;
using jvm::Object;
using jvm::Ref;
using jvm::Value;

// ---------------------------------------------------------------------------------------------------------------------
// java.io.File: a path, and what the host's file system says about the file the guest path stands for.

class File : public Object {
public:
    File(Class* cls, std::string path) : Object(cls), path(std::move(path)) {}
    std::string path;
};

Class* g_file = nullptr;

Ref<Object> file(const std::string& path) { return Ref<Object>(new File(g_file, path)); }

// The parent of a path as File.getParent gives it: up to the last slash, null (empty) for a bare name.
std::string parent_of(const std::string& path) {
    std::size_t cut = path.find_last_of('/');
    if (cut == std::string::npos) return {};
    return cut == 0 ? "/" : path.substr(0, cut);
}

// mkdir -p on the host for a guest path.
bool make_dirs(const std::string& guest) {
    std::string host = host_of(guest);
    for (std::size_t i = 1; i <= host.size(); ++i) {
        if (i == host.size() || host[i] == '/') {
            std::string part = host.substr(0, i);
            // An existing folder on the way is fine; anything else that fails ends it.
            if (mkdir(part.c_str(), 0755) != 0 && errno != EEXIST) return false;
        }
    }
    struct stat st;
    return stat(host.c_str(), &st) == 0 && S_ISDIR(st.st_mode);
}

void define_file() {
    Class& c = jvm::define("java/io/File");
    g_file = &c;
    c.make = [](Class& k) -> Object* { return new File(&k, {}); };
    auto self = [](Call& c) -> File& { return c.self_as<File>(); };
    c.method("<init>", "(Ljava/lang/String;)V", [self](Call& c) {
        self(c).path = c.str(0);
        return Value();
    });
    c.method("<init>", "(Ljava/lang/String;Ljava/lang/String;)V", [self](Call& c) {
        self(c).path = c.str(0) + "/" + c.str(1);
        return Value();
    });
    c.method("<init>", "(Ljava/io/File;Ljava/lang/String;)V", [self](Call& c) {
        auto* dir = c.as<File>(0);
        self(c).path = (dir ? dir->path + "/" : std::string()) + c.str(1);
        return Value();
    });
    c.method("getPath", "()Ljava/lang/String;", [self](Call& c) { return Value(jvm::string(self(c).path)); });
    c.method("toString", "()Ljava/lang/String;", [self](Call& c) { return Value(jvm::string(self(c).path)); });
    // Guest paths are absolute already, and have no links to resolve.
    c.method("getAbsolutePath", "()Ljava/lang/String;", [self](Call& c) { return Value(jvm::string(self(c).path)); });
    c.method("getCanonicalPath", "()Ljava/lang/String;", [self](Call& c) { return Value(jvm::string(self(c).path)); });
    c.method("getAbsoluteFile", "()Ljava/io/File;", [](Call& c) { return Value(c.self); });
    c.method("getName", "()Ljava/lang/String;", [self](Call& c) {
        const std::string& p = self(c).path;
        return Value(jvm::string(p.substr(p.find_last_of('/') + 1)));
    });
    c.method("getParent", "()Ljava/lang/String;", [self](Call& c) {
        std::string p = parent_of(self(c).path);
        return p.empty() ? Value() : Value(jvm::string(p));
    });
    c.method("getParentFile", "()Ljava/io/File;", [self](Call& c) {
        std::string p = parent_of(self(c).path);
        return p.empty() ? Value() : Value(file(p));
    });
    c.method("exists", "()Z", [self](Call& c) { return Value::Z(access(host_of(self(c).path).c_str(), F_OK) == 0); });
    c.method("canRead", "()Z", [self](Call& c) { return Value::Z(access(host_of(self(c).path).c_str(), R_OK) == 0); });
    c.method("canWrite", "()Z", [self](Call& c) { return Value::Z(access(host_of(self(c).path).c_str(), W_OK) == 0); });
    c.method("isDirectory", "()Z", [self](Call& c) {
        struct stat st;
        return Value::Z(stat(host_of(self(c).path).c_str(), &st) == 0 && S_ISDIR(st.st_mode));
    });
    c.method("isFile", "()Z", [self](Call& c) {
        struct stat st;
        return Value::Z(stat(host_of(self(c).path).c_str(), &st) == 0 && S_ISREG(st.st_mode));
    });
    c.method("length", "()J", [self](Call& c) {
        struct stat st;
        return Value::J(stat(host_of(self(c).path).c_str(), &st) == 0 ? static_cast<jlong>(st.st_size) : 0);
    });
    c.method("mkdir", "()Z", [self](Call& c) { return Value::Z(mkdir(host_of(self(c).path).c_str(), 0755) == 0); });
    c.method("mkdirs", "()Z", [self](Call& c) {
        // Java's mkdirs is false when the folder was there already.
        struct stat st;
        bool existed = stat(host_of(self(c).path).c_str(), &st) == 0;
        return Value::Z(!existed && make_dirs(self(c).path));
    });
    c.method("delete", "()Z", [self](Call& c) {
        std::string host = host_of(self(c).path);
        return Value::Z(unlink(host.c_str()) == 0 || rmdir(host.c_str()) == 0);
    });
}

// ---------------------------------------------------------------------------------------------------------------------
// Shared preferences, kept as Android keeps them: <data>/shared_prefs/<name>.xml, in the same XML, so that a phone's
// file and this one are interchangeable.

class Prefs : public Object {
public:
    Prefs(Class* cls, std::string name) : Object(cls), name(std::move(name)) {}
    // A value with its type, as the XML file writes it (int, long, float, boolean, string).
    struct Entry {
        std::string type, value;
    };
    std::string name;
    std::mutex lock;
    std::map<std::string, Entry> values;
    std::string host_file() const { return host_of(app().data_dir + "/shared_prefs/" + name + ".xml"); }
    void load();
    void save();
};

// XML text escaped and unescaped (the five entities and numeric references, as Android's writer and reader use them).
std::string escape(const std::string& s) {
    std::string out;
    for (char ch : s) {
        switch (ch) {
        case '&': out += "&amp;"; break;
        case '<': out += "&lt;"; break;
        case '>': out += "&gt;"; break;
        case '"': out += "&quot;"; break;
        case '\'': out += "&apos;"; break;
        default: out.push_back(ch);
        }
    }
    return out;
}

std::string unescape(const std::string& s) {
    std::string out;
    for (std::size_t i = 0; i < s.size(); ++i) {
        if (s[i] != '&') {
            out.push_back(s[i]);
            continue;
        }
        std::size_t end = s.find(';', i);
        if (end == std::string::npos) {
            out.push_back(s[i]);
            continue;
        }
        std::string ent = s.substr(i + 1, end - i - 1);
        if (ent == "amp") out.push_back('&');
        else if (ent == "lt") out.push_back('<');
        else if (ent == "gt") out.push_back('>');
        else if (ent == "quot") out.push_back('"');
        else if (ent == "apos") out.push_back('\'');
        else if (!ent.empty() && ent[0] == '#') {
            // A character reference: written as UTF-8.
            unsigned long cp = ent.size() > 1 && (ent[1] == 'x' || ent[1] == 'X') ? std::strtoul(ent.c_str() + 2, nullptr, 16) : std::strtoul(ent.c_str() + 1, nullptr, 10);
            out += jvm::string16(std::u16string(1, static_cast<char16_t>(cp)))->utf8();
        } else {
            out += "&" + ent + ";";
        }
        i = end;
    }
    return out;
}

// The value of attribute `name` in an XML start tag, "" when it has none.
std::string attribute(const std::string& tag, const std::string& name) {
    std::string key = name + "=\"";
    std::size_t at = tag.find(key);
    if (at == std::string::npos) return {};
    at += key.size();
    std::size_t end = tag.find('"', at);
    return end == std::string::npos ? std::string() : unescape(tag.substr(at, end - at));
}

void Prefs::load() {
    std::ifstream in(utf8_path(host_file()));
    if (!in) return;
    std::stringstream buf;
    buf << in.rdbuf();
    std::string xml = buf.str();
    // Each entry is a start tag of its type: <int name=".." value=".." />, or <string name="..">text</string>.
    for (std::size_t at = xml.find('<'); at != std::string::npos; at = xml.find('<', at + 1)) {
        std::size_t end = xml.find('>', at);
        if (end == std::string::npos) break;
        std::string tag = xml.substr(at + 1, end - at - 1);
        std::string type = tag.substr(0, tag.find_first_of(" />"));
        if (type != "int" && type != "long" && type != "float" && type != "boolean" && type != "string") continue;
        std::string key = attribute(tag, "name");
        if (type == "string") {
            // Text up to the closing tag; <string name="x" /> is the empty string.
            if (!tag.empty() && tag.back() == '/') {
                values[key] = Entry{type, ""};
                continue;
            }
            std::size_t close = xml.find("</string>", end);
            if (close == std::string::npos) break;
            values[key] = Entry{type, unescape(xml.substr(end + 1, close - end - 1))};
            at = close;
        } else {
            values[key] = Entry{type, attribute(tag, "value")};
        }
    }
}

void Prefs::save() {
    std::ostringstream xml;
    xml << "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n";
    for (auto& [key, e] : values) {
        if (e.type == "string") xml << "    <string name=\"" << escape(key) << "\">" << escape(e.value) << "</string>\n";
        else xml << "    <" << e.type << " name=\"" << escape(key) << "\" value=\"" << escape(e.value) << "\" />\n";
    }
    xml << "</map>\n";
    make_dirs(app().data_dir + "/shared_prefs");
    // Written beside the file and renamed over it: a crash mid-write never leaves half a file.
    std::string target = host_file(), part = target + ".part";
    {
        std::ofstream out(utf8_path(part), std::ios::trunc);
        out << xml.str();
        if (!out) return;
    }
    std::rename(part.c_str(), target.c_str());
}

// One object per name, as Context.getSharedPreferences gives.
std::mutex g_prefs_lock;
std::map<std::string, Ref<Prefs>> g_prefs;
Class* g_prefs_class = nullptr;

Prefs* prefs(const std::string& name) {
    std::lock_guard<std::mutex> l(g_prefs_lock);
    Ref<Prefs>& p = g_prefs[name];
    if (!p) {
        p = Ref<Prefs>(new Prefs(g_prefs_class, name));
        p->load();
    }
    return p.get();
}

// The editor writes into its preferences directly and saves on apply or commit: the game never discards an edit.
class Editor : public Object {
public:
    Editor(Class* cls, Prefs* p) : Object(cls), prefs(p) {}
    Ref<Prefs> prefs;
};

void define_prefs() {
    Class& c = jvm::define("android/app/SharedPreferencesImpl");
    c.interfaces.push_back(&jvm::define_interface("android/content/SharedPreferences"));
    g_prefs_class = &c;
    Class& e = jvm::define("android/app/SharedPreferencesImpl$EditorImpl");
    e.interfaces.push_back(&jvm::define_interface("android/content/SharedPreferences$Editor"));
    auto p = [](Call& c) -> Prefs& { return c.self_as<Prefs>(); };
    // A getter for each type: the stored value when it has that type, else the default the caller gave.
    auto get = [p](Call& c, const char* type) -> const Prefs::Entry* {
        Prefs& pr = p(c);
        auto it = pr.values.find(c.str(0));
        return it != pr.values.end() && it->second.type == type ? &it->second : nullptr;
    };
    c.method("getInt", "(Ljava/lang/String;I)I", [get, p](Call& c) {
        std::lock_guard<std::mutex> l(p(c).lock);
        const Prefs::Entry* e = get(c, "int");
        return Value::I(e ? static_cast<jint>(std::strtol(e->value.c_str(), nullptr, 10)) : c.i(1));
    });
    c.method("getLong", "(Ljava/lang/String;J)J", [get, p](Call& c) {
        std::lock_guard<std::mutex> l(p(c).lock);
        const Prefs::Entry* e = get(c, "long");
        return Value::J(e ? static_cast<jlong>(std::strtoll(e->value.c_str(), nullptr, 10)) : c.j(1));
    });
    c.method("getFloat", "(Ljava/lang/String;F)F", [get, p](Call& c) {
        std::lock_guard<std::mutex> l(p(c).lock);
        const Prefs::Entry* e = get(c, "float");
        return Value::F(e ? std::strtof(e->value.c_str(), nullptr) : c.f(1));
    });
    c.method("getBoolean", "(Ljava/lang/String;Z)Z", [get, p](Call& c) {
        std::lock_guard<std::mutex> l(p(c).lock);
        const Prefs::Entry* e = get(c, "boolean");
        return Value::Z(e ? e->value == "true" : c.z(1));
    });
    c.method("getString", "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;", [get, p](Call& c) {
        std::lock_guard<std::mutex> l(p(c).lock);
        const Prefs::Entry* e = get(c, "string");
        return e ? Value(jvm::string(e->value)) : Value(c.l(1));
    });
    // Every entry, each value boxed by its type, in a HashMap.
    c.method("getAll", "()Ljava/util/Map;", [p](Call& c) {
        Prefs& pr = p(c);
        Ref<Object> map = jvm::new_object(*jvm::find_class("java/util/HashMap"), "()V");
        std::lock_guard<std::mutex> l(pr.lock);
        for (auto& [key, e] : pr.values) {
            Value v;
            if (e.type == "int") v = Value(jvm::box('I', Value::I(static_cast<jint>(std::strtol(e.value.c_str(), nullptr, 10)))));
            else if (e.type == "long") v = Value(jvm::box('J', Value::J(std::strtoll(e.value.c_str(), nullptr, 10))));
            else if (e.type == "float") v = Value(jvm::box('F', Value::F(std::strtof(e.value.c_str(), nullptr))));
            else if (e.type == "boolean") v = Value(jvm::box('Z', Value::Z(e.value == "true")));
            else v = Value(jvm::string(e.value));
            c.env.call(map.get(), "put", "(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;", {Value(jvm::string(key)), v});
        }
        return Value(map);
    });
    c.method("contains", "(Ljava/lang/String;)Z", [p](Call& c) {
        std::lock_guard<std::mutex> l(p(c).lock);
        return Value::Z(p(c).values.count(c.str(0)) != 0);
    });
    Class* editor_class = &e;
    c.method("edit", "()Landroid/content/SharedPreferences$Editor;", [p, editor_class](Call& c) { return Value(Ref<Object>(new Editor(editor_class, &p(c)))); });
    auto ed = [](Call& c) -> Prefs& { return *c.self_as<Editor>().prefs; };
    // Each put stores the value as the XML writes it, and returns the editor (the calls chain).
    auto put = [ed](Call& c, const char* type, std::string value) {
        Prefs& pr = ed(c);
        std::lock_guard<std::mutex> l(pr.lock);
        pr.values[c.str(0)] = Prefs::Entry{type, std::move(value)};
        return Value(c.self);
    };
    e.method("putInt", "(Ljava/lang/String;I)Landroid/content/SharedPreferences$Editor;", [put](Call& c) { return put(c, "int", std::to_string(c.i(1))); });
    e.method("putLong", "(Ljava/lang/String;J)Landroid/content/SharedPreferences$Editor;", [put](Call& c) { return put(c, "long", std::to_string(c.j(1))); });
    e.method("putFloat", "(Ljava/lang/String;F)Landroid/content/SharedPreferences$Editor;", [put](Call& c) {
        char text[32];
        std::snprintf(text, sizeof text, "%.9g", static_cast<double>(c.f(1)));
        return put(c, "float", text);
    });
    e.method("putBoolean", "(Ljava/lang/String;Z)Landroid/content/SharedPreferences$Editor;", [put](Call& c) { return put(c, "boolean", c.z(1) ? "true" : "false"); });
    e.method("putString", "(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;", [put, ed](Call& c) {
        // A null string removes the key, as Android's editor does.
        if (!c.l(1)) {
            Prefs& pr = ed(c);
            std::lock_guard<std::mutex> l(pr.lock);
            pr.values.erase(c.str(0));
            return Value(c.self);
        }
        return put(c, "string", c.str(1));
    });
    e.method("remove", "(Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;", [ed](Call& c) {
        Prefs& pr = ed(c);
        std::lock_guard<std::mutex> l(pr.lock);
        pr.values.erase(c.str(0));
        return Value(c.self);
    });
    e.method("clear", "()Landroid/content/SharedPreferences$Editor;", [ed](Call& c) {
        Prefs& pr = ed(c);
        std::lock_guard<std::mutex> l(pr.lock);
        pr.values.clear();
        return Value(c.self);
    });
    auto save = [ed](Call& c) {
        Prefs& pr = ed(c);
        std::lock_guard<std::mutex> l(pr.lock);
        pr.save();
    };
    e.method("apply", "()V", [save](Call& c) {
        save(c);
        return Value();
    });
    e.method("commit", "()Z", [save](Call& c) {
        save(c);
        return Value::Z(true);
    });
}

// ---------------------------------------------------------------------------------------------------------------------
// The context, the activity and the application.

Ref<Object> g_activity, g_application, g_player;
Ref<Object> g_package_manager, g_application_info, g_intent, g_assets, g_resources, g_window;
// System services by name (getSystemService), made on first ask.
std::mutex g_services_lock;
std::map<std::string, Ref<Object>> g_services;

// An object of a class, with fields set (for the classes whose fields the game reads: ApplicationInfo, PackageInfo).
Ref<Object> object_of(const char* cls, std::initializer_list<std::pair<const char*, Value>> fields = {}) {
    Class& c = *jvm::find_class(cls);
    Ref<Object> o = jvm::new_object(c, "()V");
    for (auto& [name, v] : fields) {
        jvm::Field* f = c.find_field(name, false);
        if (!f) {
            // Declared on first use, with the type the value has.
            std::string sig = v.l() ? "L" + v.l()->cls()->name + ";" : "I";
            c.field(name, sig);
            f = c.find_field(name, false);
        }
        o->set_field(f, v);
    }
    return o;
}

// The system service of that name: classes the game asks for, each with the methods it calls (android_view.cpp and
// the others define them); one object per name.
Value service(const std::string& name) {
    static const std::map<std::string, const char*> kClasses = {
        {"window", "android/view/WindowManagerImpl"},
        {"display", "android/hardware/display/DisplayManager"},
        {"input", "android/hardware/input/InputManager"},
        {"audio", "android/media/AudioManager"},
        {"connectivity", "android/net/ConnectivityManager"},
        {"vibrator", "android/os/SystemVibrator"},
        {"phone", "android/telephony/TelephonyManager"},
        {"activity", "android/app/ActivityManager"},
        {"sensor", "android/hardware/SystemSensorManager"},
        {"input_method", "android/view/inputmethod/InputMethodManager"},
        {"power", "android/os/PowerManager"},
        {"media_router", "android/media/MediaRouter"},
        {"uimode", "android/app/UiModeManager"},
        {"wifi", "android/net/wifi/WifiManager"},
        {"clipboard", "android/content/ClipboardManager"},
        {"location", "android/location/LocationManager"},
    };
    auto it = kClasses.find(name);
    if (it == kClasses.end()) {
        jvm::log("player: getSystemService(\"%s\"): none here", name.c_str());
        return Value();
    }
    std::lock_guard<std::mutex> l(g_services_lock);
    Ref<Object>& s = g_services[name];
    if (!s) s = jvm::new_object(*jvm::find_class(it->second), "()V");
    return Value(s);
}

void define_context() {
    // The class chain of the game's activity (its manifest's launcher), and the application's.
    jvm::define("android/content/Context", "java/lang/Object").modifiers |= jvm::kAbstract;
    jvm::define("android/content/ContextWrapper", "android/content/Context");
    jvm::define("android/view/ContextThemeWrapper", "android/content/ContextWrapper");
    jvm::define("android/app/Activity", "android/view/ContextThemeWrapper");
    jvm::define("com/unity3d/player/UnityPlayerActivity", "android/app/Activity").field("mUnityPlayer", "Lcom/unity3d/player/UnityPlayer;");
    jvm::define("net/gree/unitywebview/CUnityPlayerActivity", "com/unity3d/player/UnityPlayerActivity");
    jvm::define("android/app/Application", "android/content/ContextWrapper");
    // Context's methods, on ContextWrapper where Android has them: the activity and the application both answer.
    Class& c = jvm::define("android/content/ContextWrapper", "android/content/Context");
    c.method("getPackageName", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string(app().package)); });
    c.method("getPackageCodePath", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string(app().apk)); });
    c.method("getPackageResourcePath", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string(app().apk)); });
    c.method("getApplicationInfo", "()Landroid/content/pm/ApplicationInfo;", [](Call&) { return Value(g_application_info); });
    c.method("getApplicationContext", "()Landroid/content/Context;", [](Call&) { return Value(g_application); });
    c.method("getPackageManager", "()Landroid/content/pm/PackageManager;", [](Call&) { return Value(g_package_manager); });
    c.method("getAssets", "()Landroid/content/res/AssetManager;", [](Call&) { return Value(g_assets); });
    c.method("getResources", "()Landroid/content/res/Resources;", [](Call&) { return Value(g_resources); });
    c.method("getClassLoader", "()Ljava/lang/ClassLoader;", [](Call& c) { return c.env.call(c.self->cls(), "getClassLoader", "()Ljava/lang/ClassLoader;"); });
    c.method("getSystemService", "(Ljava/lang/String;)Ljava/lang/Object;", [](Call& c) { return service(c.str(0)); });
    c.method("getSharedPreferences", "(Ljava/lang/String;I)Landroid/content/SharedPreferences;", [](Call& c) { return Value(prefs(c.str(0))); });
    // The app's folders, made when asked for, as Android makes them.
    auto dir = [](const std::string& guest) {
        make_dirs(guest);
        return Value(file(guest));
    };
    c.method("getFilesDir", "()Ljava/io/File;", [dir](Call&) { return dir(app().data_dir + "/files"); });
    c.method("getCacheDir", "()Ljava/io/File;", [dir](Call&) { return dir(app().data_dir + "/cache"); });
    c.method("getCodeCacheDir", "()Ljava/io/File;", [dir](Call&) { return dir(app().data_dir + "/code_cache"); });
    c.method("getNoBackupFilesDir", "()Ljava/io/File;", [dir](Call&) { return dir(app().data_dir + "/no_backup"); });
    c.method("getExternalFilesDir", "(Ljava/lang/String;)Ljava/io/File;", [dir](Call& c) {
        std::string type = c.str(0);
        return dir(app().external_dir + "/files" + (type.empty() ? "" : "/" + type));
    });
    c.method("getExternalCacheDir", "()Ljava/io/File;", [dir](Call&) { return dir(app().external_dir + "/cache"); });
    c.method("getObbDir", "()Ljava/io/File;", [](Call&) { return Value(file("/storage/emulated/0/Android/obb/" + app().package)); });
    c.method("getDir", "(Ljava/lang/String;I)Ljava/io/File;", [dir](Call& c) { return dir(app().data_dir + "/app_" + c.str(0)); });
    // Permissions the manifest asks for are granted, as at install time on the phones the game was made for.
    c.method("checkCallingOrSelfPermission", "(Ljava/lang/String;)I", [](Call&) { return Value::I(0); });
    c.method("checkSelfPermission", "(Ljava/lang/String;)I", [](Call&) { return Value::I(0); });
    c.method("checkPermission", "(Ljava/lang/String;II)I", [](Call&) { return Value::I(0); });
    // Services the game starts (an SDK's background service) do not run here.
    c.method("startService", "(Landroid/content/Intent;)Landroid/content/ComponentName;", [](Call&) { return Value(); });
    // The activity's own methods.
    Class& a = jvm::define("android/app/Activity", "android/view/ContextThemeWrapper");
    a.method("getWindow", "()Landroid/view/Window;", [](Call&) { return Value(g_window); });
    a.method("getApplication", "()Landroid/app/Application;", [](Call&) { return Value(g_application); });
    a.method("getIntent", "()Landroid/content/Intent;", [](Call&) { return Value(g_intent); });
    a.method("isFinishing", "()Z", [](Call&) { return Value::Z(false); });
    a.method("getRequestedOrientation", "()I", [](Call&) { return Value::I(6); });  // sensorLandscape, as the manifest asks
    a.method("setRequestedOrientation", "(I)V", [](Call&) { return Value(); });
    a.method("getWindowManager", "()Landroid/view/WindowManager;", [](Call&) { return service("window"); });
    // The runnable runs on the UI thread, later, as Android posts it there (the player's main thread).
    a.method("runOnUiThread", "(Ljava/lang/Runnable;)V", [](Call& c) {
        Ref<Object> r(c.l(0));
        main_looper().post([r] {
            jvm::Env& e = jvm::attach();
            e.call(r.get(), "run", "()V");
            if (e.pending) {
                jvm::log("player: a runnable on the UI thread threw %s", e.pending->cls()->name.c_str());
                e.pending = {};
            }
        });
        return Value();
    });
}

// ---------------------------------------------------------------------------------------------------------------------
// The package: its ApplicationInfo and PackageInfo, and the package manager.

void define_package() {
    jvm::define("android/content/pm/PackageItemInfo");
    Class& info = jvm::define("android/content/pm/ApplicationInfo", "android/content/pm/PackageItemInfo");
    info.field("nativeLibraryDir", "Ljava/lang/String;").field("sourceDir", "Ljava/lang/String;").field("publicSourceDir", "Ljava/lang/String;");
    info.field("dataDir", "Ljava/lang/String;").field("packageName", "Ljava/lang/String;").field("flags", "I").field("targetSdkVersion", "I");
    info.field("metaData", "Landroid/os/Bundle;");
    Class& pi = jvm::define("android/content/pm/PackageInfo");
    pi.field("versionName", "Ljava/lang/String;").field("versionCode", "I").field("packageName", "Ljava/lang/String;");
    pi.field("firstInstallTime", "J").field("lastUpdateTime", "J").field("applicationInfo", "Landroid/content/pm/ApplicationInfo;");
    Class& pm = jvm::define("android/app/ApplicationPackageManager", "android/content/pm/PackageManager");
    pm.method("getApplicationInfo", "(Ljava/lang/String;I)Landroid/content/pm/ApplicationInfo;", [](Call&) { return Value(g_application_info); });
    pm.method("getPackageInfo", "(Ljava/lang/String;I)Landroid/content/pm/PackageInfo;", [](Call&) {
        return Value(object_of("android/content/pm/PackageInfo", {{"versionName", Value(jvm::string(app().version_name))},
                                                                  {"versionCode", Value::I(app().version_code)},
                                                                  {"packageName", Value(jvm::string(app().package))},
                                                                  {"applicationInfo", Value(g_application_info)}}));
    });
    // No phone hardware here: the features a game checks for (telephony, a compass, low-latency audio) are absent.
    pm.method("hasSystemFeature", "(Ljava/lang/String;)Z", [](Call& c) {
        std::string f = c.str(0);
        // A touch screen it does have (the mouse and the window's touch input stand in).
        return Value::Z(f == "android.hardware.touchscreen" || f == "android.hardware.touchscreen.multitouch" ||
                        f == "android.hardware.touchscreen.multitouch.distinct");
    });
    pm.method("checkPermission", "(Ljava/lang/String;Ljava/lang/String;)I", [](Call&) { return Value::I(0); });
    pm.method("getInstallerPackageName", "(Ljava/lang/String;)Ljava/lang/String;", [](Call&) { return Value(); });
}

// ---------------------------------------------------------------------------------------------------------------------
// Intents and bundles: the activity was started from the launcher, with nothing extra.

void define_intents() {
    Class& b = jvm::define("android/os/Bundle", "android/os/BaseBundle");
    b.method("<init>", "()V", [](Call&) { return Value(); });
    b.method("getString", "(Ljava/lang/String;)Ljava/lang/String;", [](Call&) { return Value(); });
    b.method("getString", "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;", [](Call& c) { return Value(c.l(1)); });
    b.method("getBoolean", "(Ljava/lang/String;)Z", [](Call&) { return Value::Z(false); });
    b.method("getBoolean", "(Ljava/lang/String;Z)Z", [](Call& c) { return Value::Z(c.z(1)); });
    b.method("getInt", "(Ljava/lang/String;)I", [](Call&) { return Value::I(0); });
    b.method("getInt", "(Ljava/lang/String;I)I", [](Call& c) { return Value::I(c.i(1)); });
    b.method("containsKey", "(Ljava/lang/String;)Z", [](Call&) { return Value::Z(false); });
    Class& i = jvm::define("android/content/Intent");
    i.method("getExtras", "()Landroid/os/Bundle;", [](Call&) { return Value(); });
    i.method("getAction", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string("android.intent.action.MAIN")); });
    i.method("getData", "()Landroid/net/Uri;", [](Call&) { return Value(); });
    i.method("getDataString", "()Ljava/lang/String;", [](Call&) { return Value(); });
    i.method("getStringExtra", "(Ljava/lang/String;)Ljava/lang/String;", [](Call&) { return Value(); });
    i.method("getBooleanExtra", "(Ljava/lang/String;Z)Z", [](Call& c) { return Value::Z(c.z(1)); });
    i.method("getIntExtra", "(Ljava/lang/String;I)I", [](Call& c) { return Value::I(c.i(1)); });
    i.method("hasExtra", "(Ljava/lang/String;)Z", [](Call&) { return Value::Z(false); });
}

// ---------------------------------------------------------------------------------------------------------------------
// android.os.Build: the device the game runs on, as the runtime's system properties describe it (syscalls.cpp gives
// the guest the same values).

void define_build() {
    Class& b = jvm::define("android/os/Build");
    auto text = [&b](const char* name, const char* value) { b.static_field(name, "Ljava/lang/String;", Value(jvm::string(value))); };
    text("MODEL", "OpenDMTQ");
    text("MANUFACTURER", "OpenDMTQ");
    text("BRAND", "OpenDMTQ");
    text("DEVICE", "opendmtq");
    text("PRODUCT", "opendmtq");
    text("HARDWARE", "opendmtq");
    text("BOARD", "opendmtq");
    text("FINGERPRINT", "OpenDMTQ/opendmtq/opendmtq:9/PQ3A/1:user/release-keys");
    text("ID", "PQ3A");
    text("DISPLAY", "PQ3A");
    text("TAGS", "release-keys");
    text("TYPE", "user");
    text("SERIAL", "unknown");
    text("CPU_ABI", "armeabi-v7a");
    text("CPU_ABI2", "armeabi");
    Class& v = jvm::define("android/os/Build$VERSION");
    v.static_field("SDK_INT", "I", Value::I(28));
    v.static_field("RELEASE", "Ljava/lang/String;", Value(jvm::string("9")));
    v.static_field("CODENAME", "Ljava/lang/String;", Value(jvm::string("REL")));
    v.static_field("INCREMENTAL", "Ljava/lang/String;", Value(jvm::string("1")));
    Class& e = jvm::define("android/os/Environment");
    e.static_method("getExternalStorageState", "()Ljava/lang/String;", [](Call&) { return Value(jvm::string("mounted")); });
    e.static_method("getExternalStorageDirectory", "()Ljava/io/File;", [](Call&) { return Value(file("/storage/emulated/0")); });
    e.static_method("isExternalStorageEmulated", "()Z", [](Call&) { return Value::Z(true); });
    e.static_method("isExternalStorageRemovable", "()Z", [](Call&) { return Value::Z(false); });
}

}  // namespace

jvm::Object* activity() { return g_activity.get(); }
jvm::Object* application() { return g_application.get(); }
jvm::Object* unity_player() { return g_player.get(); }

void define_android_app() {
    define_file();
    define_prefs();
    define_context();
    define_package();
    define_intents();
    define_build();
    // The app's objects, made once.
    g_application = jvm::new_object(*jvm::find_class("android/app/Application"), "()V");
    g_activity = jvm::new_object(*jvm::find_class("net/gree/unitywebview/CUnityPlayerActivity"), "()V");
    g_application_info = object_of("android/content/pm/ApplicationInfo", {{"nativeLibraryDir", Value(jvm::string(app().lib_dir))},
                                                                          {"sourceDir", Value(jvm::string(app().apk))},
                                                                          {"publicSourceDir", Value(jvm::string(app().apk))},
                                                                          {"dataDir", Value(jvm::string(app().data_dir))},
                                                                          {"packageName", Value(jvm::string(app().package))},
                                                                          {"targetSdkVersion", Value::I(26)}});
    g_package_manager = jvm::new_object(*jvm::find_class("android/app/ApplicationPackageManager"), "()V");
    g_intent = jvm::new_object(*jvm::find_class("android/content/Intent"), "()V");
    g_assets = jvm::new_object(*jvm::find_class("android/content/res/AssetManager"), "()V");
    g_resources = jvm::new_object(*jvm::find_class("android/content/res/Resources"), "()V");
    g_window = jvm::new_object(*jvm::find_class("com/android/internal/policy/PhoneWindow"), "()V");
    // The Unity player view, the activity's mUnityPlayer and the static currentActivity C# reads.
    g_player = jvm::new_object(*jvm::find_class("net/gree/unitywebview/CUnityPlayer"), "()V");
    Class* activity_class = jvm::find_class("com/unity3d/player/UnityPlayerActivity");
    g_activity->set_field(activity_class->find_field("mUnityPlayer", false), Value(g_player));
    Class* player_class = jvm::find_class("com/unity3d/player/UnityPlayer");
    player_class->static_field("currentActivity", "Landroid/app/Activity;", Value(g_activity));
}

}  // namespace player
