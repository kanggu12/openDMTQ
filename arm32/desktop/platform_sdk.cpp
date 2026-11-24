// The platform's SDK as the game's C# reaches it (its Java class; every name of the SDK's is in client_names.h, by its
// role), talking straight to the OpenDMTQ server the app was built for. On a phone the SDK does its own HTTP and answers
// C# with UnitySendMessage to its Unity object, "<callback id>|<event>|1|1|<JSON>"; here each call does the same request
// on a thread of its own and sends the same message:
//   - the sign-in with the device's guest account: the server's platform login with this computer's device id, the
//     account's key;
//   - a request (path, ...): the server's /api + path (the price list);
//   - the call to finish a purchase left unfinished: none ever is (nothing is sold);
//   - the store's prices: the failure a phone without Google's billing gets, after which the game goes on;
//   - whether a permission is granted: granted, as on the phones the game was made for.
#include "player.h"

#include "client_names.h"

#include <cctype>
#include <fstream>
#include <functional>
#include <thread>
#include <vector>

namespace player {

namespace {

using jvm::Call;
using jvm::Class;
using jvm::Object;
using jvm::Ref;
using jvm::Value;
// Each name of the SDK's by its role.
using client_names::text;

// The server's address, from the packer's tweaks file among the libraries (its "server <host[:port]>" line).
std::string server_base() {
    static const std::string base = [] {
        std::ifstream in(utf8_path(app().host_libs + "/libarm32t-tweaks.so"));
        std::string line;
        while (std::getline(in, line)) {
            if (line.rfind("server ", 0) == 0) return "http://" + line.substr(7);
        }
        return std::string();
    }();
    return base;
}

// The value of a key at the top of a JSON object, as text (an object, an array, a string with its quotes, a number),
// "null" when it is not there: enough to pass the server's "value" on as the SDK does.
std::string json_value(const std::string& json, const std::string& key) {
    int depth = 0;
    bool in_string = false;
    for (std::size_t i = 0; i < json.size(); ++i) {
        char ch = json[i];
        if (in_string) {
            if (ch == '\\') ++i;
            else if (ch == '"') in_string = false;
            continue;
        }
        if (ch == '{' || ch == '[') {
            ++depth;
        } else if (ch == '}' || ch == ']') {
            --depth;
        } else if (ch == '"') {
            // A key at the top level: the value after its colon, up to where its brackets close.
            std::size_t end = json.find('"', i + 1);
            if (depth == 1 && end != std::string::npos && json.compare(i + 1, end - i - 1, key) == 0) {
                std::size_t at = json.find(':', end);
                if (at == std::string::npos) return "null";
                ++at;
                while (at < json.size() && std::isspace(static_cast<unsigned char>(json[at]))) ++at;
                std::size_t from = at;
                int d = 0;
                bool s = false;
                for (; at < json.size(); ++at) {
                    char c = json[at];
                    if (s) {
                        if (c == '\\') ++at;
                        else if (c == '"') s = false;
                        continue;
                    }
                    if (c == '"') s = true;
                    else if (c == '{' || c == '[') ++d;
                    else if (c == '}' || c == ']') {
                        if (d == 0) break;
                        --d;
                    } else if (c == ',' && d == 0) {
                        break;
                    }
                }
                std::string v = json.substr(from, at - from);
                while (!v.empty() && std::isspace(static_cast<unsigned char>(v.back()))) v.pop_back();
                return v;
            }
            in_string = true;
        }
    }
    return "null";
}

// JSON without the white space between its tokens, as the SDK's serializer writes it: C# splits the message on spaces
// before the JSON part, and the server lays its replies out over many lines.
std::string compact(const std::string& json) {
    std::string out;
    out.reserve(json.size());
    bool in_string = false;
    for (std::size_t i = 0; i < json.size(); ++i) {
        char ch = json[i];
        if (in_string) {
            out.push_back(ch);
            if (ch == '\\' && i + 1 < json.size()) out.push_back(json[++i]);
            else if (ch == '"') in_string = false;
            continue;
        }
        if (ch == '"') in_string = true;
        if (!std::isspace(static_cast<unsigned char>(ch))) out.push_back(ch);
    }
    return out;
}

// A JSON string literal.
std::string quoted(const std::string& s) {
    std::string out = "\"";
    for (char ch : s) {
        if (ch == '"' || ch == '\\') out.push_back('\\');
        out.push_back(ch);
    }
    return out + "\"";
}

// The SDK's message to C#, as its Java class sends it: "<callback>|<event>|<n>|<count>|<part>", the JSON (compact) cut
// into parts of 850 UTF-16 units, one message each, to its Unity object; logged by event and length (the access token is
// in it).
void answer(const std::string& callback, const std::string& event, const std::string& json) {
    // The Unity object the SDK's messages go to, and its method that takes them.
    static const std::string object = text(client_names::kPlatformObject), method = text(client_names::kPlatformMessage);
    // The JSON as UTF-16, which the parts are counted in.
    std::u16string units = jvm::string(compact(json))->chars;
    std::vector<std::u16string> parts;
    for (std::size_t at = 0; at < units.size(); at += 850) parts.push_back(units.substr(at, 850));
    if (parts.empty()) parts.emplace_back();
    jvm::log("player: platform: %s for %s (%zu characters of JSON, %zu messages)", event.c_str(), callback.c_str(), units.size(), parts.size());
    for (std::size_t k = 0; k < parts.size(); ++k) {
        std::string head = callback + "|" + event + "|" + std::to_string(k + 1) + "|" + std::to_string(parts.size()) + "|";
        send_to_unity(object, method, head + jvm::string16(parts[k])->utf8());
    }
}

// A platform call on a thread of its own: a POST to the server, then the answer built from its reply.
void platform_call(std::string path, std::string form, std::function<std::string(int status, const std::string& reply)> build, std::string callback, std::string event) {
    std::thread([path, form, build, callback, event] {
        std::string reply, error;
        int status = 0;
        std::string base = server_base();
        bool ok = !base.empty() && http_request("POST", base + path, {{"Content-Type", "application/x-www-form-urlencoded"}}, form, 15000, status, reply, error);
        if (!ok) jvm::log("player: platform %s: %s", path.c_str(), base.empty() ? "no server address in the tweaks file" : error.c_str());
        // A failure as the SDK reports one: its status (or -1, no answer) and the reason.
        std::string json = ok && status == 200 ? build(status, reply)
                                               : "{\"response_code\":" + std::to_string(ok ? status : -1) + ",\"value\":{\"result_msg\":" + quoted(ok ? "HTTP " + std::to_string(status) : error) + "}}";
        answer(callback, event, json);
        jvm::detach();
    }).detach();
}

}  // namespace

void define_platform_sdk() {
    // The SDK's class the game's C# calls.
    Class& c = jvm::define(text(client_names::kPlatformFacade));
    c.method("<init>", "()V", [](Call&) { return Value(); });
    // At the game's start: nothing to set up.
    c.method(text(client_names::kPlatformInitialize), "(Landroid/app/Activity;)V", [](Call&) {
        jvm::log("player: platform: initialize");
        return Value();
    });
    // The SDK's settings: none of them is needed here.
    c.method(text(client_names::kPlatformProperties), "(Ljava/lang/String;)V", [](Call&) { return Value(); });
    // Whether a permission is granted: always.
    c.method(text(client_names::kPlatformPermission), "(Ljava/lang/String;)Z", [](Call& c) {
        jvm::log("player: platform: permission %s granted", c.str(0).c_str());
        return Value::Z(true);
    });
    // A purchase left unfinished: none ever is, so the answer is an empty list.
    c.method(text(client_names::kPlatformRetryPurchase), "(Ljava/lang/String;)V", [](Call& c) {
        std::string cb = c.str(0);
        std::thread([cb] {
            answer(cb, text(client_names::kEventRetryPurchase), "{\"response_code\":0,\"value\":[]}");
            jvm::detach();
        }).detach();
        return Value();
    });
    // The sign-in with the device's guest account: the server's platform login with this computer's device id.
    c.method(text(client_names::kPlatformLogin), "(Ljava/lang/String;)V", [](Call& c) {
        jvm::log("player: platform: login");
        platform_call("/api/accounts/v3/global/login_dmq", "udid=" + device_id(),
                      [](int, const std::string& reply) { return "{\"response_code\":0,\"value\":" + json_value(reply, "value") + "}"; }, c.str(0),
                      text(client_names::kEventLogin));
        return Value();
    });
    // A request to the platform's API: the server's /api + path.
    c.method(text(client_names::kPlatformRequest), "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;ZLjava/lang/String;Ljava/lang/String;)V", [](Call& c) {
        jvm::log("player: platform: request %s %s", c.str(2).c_str(), c.str(0).c_str());
        std::string path = c.str(0), extra = c.l(4) ? quoted(c.str(4)) : "null";
        // The parameters come as a JSON object; the server reads none of them for the calls the game makes.
        platform_call(
            "/api" + path, "", [path, extra](int, const std::string& reply) {
                return "{\"response_code\":0,\"path\":" + quoted(path) + ",\"extra_info\":" + extra + ",\"value\":" + json_value(reply, "value") + "}";
            },
            c.str(5), text(client_names::kEventRequest));
        return Value();
    });
    // The store's prices in the player's currency: the failure a phone without Google's billing gets.
    c.method(text(client_names::kPlatformPrices), "([Ljava/lang/String;)V", [](Call&) {
        std::thread([] {
            answer("main", text(client_names::kEventPricesFailed),
                   "{\"response_code\":400,\"value\":{\"result_msg\":\"API_ERR_PAY_GOOGLE_NOT_SUPPORTED\",\"error_params\":{},\"result_code\":\"20010\"}}");
            jvm::detach();
        }).detach();
        return Value();
    });
}

}  // namespace player
